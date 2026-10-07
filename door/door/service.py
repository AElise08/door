"""Loop nuvem e conexão WSS de saída ao Hub dedicado do Colmeia."""
import argparse
import base64
import json
import os
import time
from pathlib import Path
from websockets.sync.client import connect

from .cloud import Cloud
from .common import now, ulid
from .plow import PlowAPI, LatchRelay
from .door_link import DoorLink


class HubLink:
    def __init__(self, url, token, local=False):
        if not url.startswith("wss://") and not (local and url.startswith("ws://127.0.0.1:")):
            raise ValueError("Hub requires WSS (or explicit loopback in development)")
        self.url, self.token, self.ws = url, token, None

    def rpc(self, method, params):
        if self.ws is None:
            self.ws = connect(self.url, open_timeout=10, max_size=2 * 1024 * 1024)
            self.rpc("hello", {"protocol_version": 1, "client": "door-cloud", "author": "agente:ignored", "token": self.token})
        rid = ulid()
        self.ws.send(json.dumps({"kind": "request", "id": rid, "method": method, "params": params}))
        while True:
            out = json.loads(self.ws.recv(timeout=10))
            if out.get("id") != rid:
                continue
            if not out.get("ok"):
                raise ValueError("Hub recusou RPC")
            return out.get("result", {})

    def close(self):
        if self.ws:
            self.ws.close()
        self.ws = None


def panel_command(cloud, command):
    """owner_session é emitida pelo Hub, nunca recebida de convidado/SMS."""
    op, rid = command["op"], command.get("request_id")
    if op == "decide":
        cloud.decide(rid, command["decision"], command["owner_session"], command["text_hash"])
    elif op == "guest.add":
        cloud.add_guest(command["phone"], command.get("name", ""), command.get("days", 30), command.get("limits"))
    elif op == "guest.status":
        cloud.set_guest_status(command["guest_id"], command["status"])
    elif op == "guest.limits":
        cloud.guest_limits(command["guest_id"], command["limits"], command.get("expires_at"))
    elif op == "invite.create":
        cloud.create_invite(command.get("name", ""), command.get("days", 30), command.get("ttl_days", 7))
    elif op == "invite.revoke":
        cloud.revoke_invite(command["code"])
    elif op == "access.resolve":
        cloud.resolve_access(command["phone"], command["allow"])
    elif op == "guest.level":
        cloud.set_guest_level(command["guest_id"], command["level"])
    elif op == "action.decide":
        cloud.decide_action(command["request_id"], command["action_id"], command["decision"], "panel:" + command["owner_session"])
    elif op == "merge.request":
        cloud.request_merge()
    elif op == "settings.change":
        cloud.request_settings(command["change"])
    elif op == "settings.approval":
        cloud.set_approval(command["mode"])
    elif op == "guest.approval":
        cloud.set_guest_approval(command["guest_id"], command["mode"])
    elif op == "link.revoked":
        cloud.set_link_status(command["link_id"], "revoked")
    elif op == "pause":
        cloud.pause(command["paused"])
    elif op == "cancel":
        cloud.cancel(rid)
    elif op == "held":
        cloud.held(rid, command["release"])
    else:
        raise ValueError("unknown panel command")


def _door(relay):
    """The command that reaches the client on the Mac (a full path when Latch runs it, see LatchRelay._bin)."""
    return relay._bin() if hasattr(relay, "_bin") else "door"


def cycle(cloud, sms, relay, hub, line_uid):
    for message in sms.messages(line_uid, cloud.s["started_at"]):
        cloud.receive(**message)
    cloud.tick()
    # Comandos de controle também atravessam o Latch; plugin declara escrita.
    for cid, cmd in list(cloud.s["commands"].items()):
        if cmd["done"]:
            continue
        if relay is None:                      # no Mac is connected to this Plow account (no Latch): say so once, do not retry forever
            cmd["done"] = True
            if cmd["op"] == "pair-confirm":
                cloud._sms(cloud.s["owner_thread"], "No Mac is connected to this Plow account yet. Install Plow Latch on your Mac, then try again.")
            continue
        argv = [_door(relay), cmd["op"]]
        if cmd["op"] == "pair-confirm":
            argv += ["--code", cmd["code"], "--public-key", cloud.public_key()]
        elif cmd["op"] == "cancel":
            argv += ["--request", cmd["request"], "--reason", cmd["reason"]]
        elif cmd["op"] == "decide":
            argv += ["--request", cmd["request"], "--action", cmd["action"], "--decision", cmd["decision"]]
        elif cmd["op"] == "settings":
            argv += ["--payload", base64.b64encode(json.dumps(cmd["change"]).encode()).decode()]
        elif cmd["op"] == "merge":
            argv += ["--head", cmd["head"], "--target", cmd["target"]]
        try:
            out = relay.command(argv)
        except (OSError, TimeoutError, PermissionError):
            continue                                # the Mac cannot be reached right now (Latch closed, Mac asleep): try again next cycle
        if cmd["op"] == "settings" and not out.get("ok") and out.get("reason") in ("bad_payload", "unknown_op"):
            cmd["done"] = True                          # an old Mac that does not know this operation, or a damaged request: say so, do not retry forever
            cloud.note_settings_result({"applied": False, "error": "This Mac could not take that change. Update Door on the Mac and try again."})
            continue
        if cmd["op"] in ("work", "merge") and not out.get("ok") and out.get("reason") in ("bad_payload", "unknown_op"):
            cmd["done"] = True
            (cloud.merge_preview if cmd["op"] == "work" else cloud.merge_done)({"reason": "This Mac does not know how to merge yet. Update Door on the Mac."})
            continue
        if out.get("ok"):
            cmd["done"] = True
            if cmd["op"] == "work":
                cloud.merge_preview(out.get("work"))
            if cmd["op"] == "merge":
                cloud.merge_done(out)
            if cmd["op"] == "settings":
                cloud.note_settings_result(out)
            if cmd["op"] == "pair-confirm" and out.get("ok"):
                cloud.s["host_id"] = out["host_id"]
                cloud.s["summary"] = out["summary"]
                cloud._sms(cloud.s["owner_thread"], "Mac paired. Set up the local profile and the read rule in Latch.")
            cloud._save()
    if cloud.s["host_id"] and relay is not None:
        # An unreachable Mac must never stop the rest of the cycle: the panel, the chat links and the owner's texts keep working,
        # and waiting requests are told the Mac is not available yet.
        try:
            if now() - cloud.s.get("summary_at", 0) >= 60 or cloud.s.get("host_online_at", 0) == 0:   # each call crosses Plow and Latch: once a minute is enough
                summary = relay.command([_door(relay), "summary"])
                if summary.get("ok"):
                    cloud.s["summary"] = summary["summary"]
                    cloud.s["host_online_at"] = cloud.s["summary_at"] = now()
                    cloud._save()
            cloud.poll(relay)
            cloud.dispatch(relay)
        except (OSError, TimeoutError, PermissionError):
            pass
    cloud.s.setdefault("panel_seen", {})
    try:
        published = hub.rpc("door.publish", {"snapshot": cloud.snapshot(), "ack": list(cloud.s["panel_seen"])})
    except (OSError, TimeoutError):
        hub.close()
        published = {}
    plan = published.get("plan")
    if plan and plan.get("status") in {"active", "inactive", "canceled"} and plan != cloud.s["plan"]:
        cloud.set_plan(plan["status"], plan["active_until"])
    for command in published.get("commands", []):
        if command["id"] in cloud.s["panel_seen"]:
            continue
        # Uma única transação engloba mutação + deduplicação no mesmo banco.
        with cloud.lock:
            before = json.loads(json.dumps(cloud.s))
            cloud.defer_save = True
            try:
                panel_command(cloud, command)
                cloud.s["panel_seen"][command["id"]] = {"ok": True}
            except (ValueError, KeyError, TypeError) as exc:
                cloud.s = before
                cloud.s["panel_seen"][command["id"]] = {"ok": False, "error": str(exc)}
            finally:
                cloud.defer_save = False
            cloud._save()
    if hasattr(hub, "inbox"):                       # messages typed in shared chat links
        try:
            web = hub.inbox()
            done = []
            for m in web:
                cloud.receive_web(m["link_id"], m["id"], m["text"], m.get("name", ""), m.get("days", 30), m.get("kind", "chat"), m.get("card_id"))
                done.append("%s:%s" % (m["link_id"], m["id"]))
            hub.ack_inbox(done)
        except (OSError, TimeoutError, KeyError, ValueError):
            pass
    if hasattr(hub, "card"):                          # board cards that follow tasks (created, moved to Done or Review)
        for job in list(cloud.s.get("panel_jobs", [])):
            try:
                if job["op"] in ("link.create", "signin"):                                   # the owner asked the agent by text message
                    path = hub.create_link(job) if job["op"] == "link.create" else hub.signin()
                    base = cloud.panel_url
                    if job["op"] == "link.create":
                        cloud._sms(job["thread"], "Link%s: %s%s (opens on one device, valid 7 days; you can turn it off in the panel)." % (
                            (" for " + job["name"]) if job.get("name") else "", base, path))
                    else:
                        cloud._sms(job["thread"], "Your panel (one-time link, 10 minutes): %s%s" % (base, path))
                else:
                    hub.card(job)
                cloud.s["panel_jobs"].remove(job)
            except (OSError, TimeoutError, ValueError, KeyError):
                job["tries"] = job.get("tries", 0) + 1
                if job["tries"] > 20:
                    cloud.s["panel_jobs"].remove(job)
        cloud._save()
    for item in cloud.pending_sms():
        # API de mensagens atual não tem idempotency_key. Em erro incerto, não
        # repetir automaticamente: deixar operador conciliar no provedor.
        item_id = item["id"]
        if item["thread"].startswith("web:"):       # a browser chat, not a text message: deliver through the panel
            try:
                hub.chat(item["thread"][4:], item["text"], "agent" if item_id.endswith((":final", ":released")) else "system")
                cloud.sms_sent(item_id)
            except (OSError, TimeoutError, AttributeError):
                pass                                # stays pending; retried next cycle
            continue
        cloud.s["outbox"][item_id]["status"] = "sending"
        cloud._save()
        sms.send(item["thread"], item["text"])
        cloud.sms_sent(item_id)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="door-cloud")
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", default=".state/cloud.db")
    parser.add_argument("--local-hub", action="store_true")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--plan-until", type=float)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    cloud = Cloud(args.state, config["owner_id"], config["summary"], config["panel_url"])
    cloud.s.setdefault("started_at", now())
    cloud.s.setdefault("relay_pending", {})
    cloud._save()
    if args.plan_until:
        cloud.set_plan("active", args.plan_until)
    if args.init:
        print("Activation code (10 min): Door Activate: " + cloud.s["activation"])
        print("Public key for pairing: " + cloud.public_key())
        return 0
    sms = PlowAPI(os.environ["DOOR_PLOW_TOKEN"])
    relay = LatchRelay(PlowAPI(os.environ["DOOR_PLOW_RELAY_TOKEN"]), config["device_uid"],
                       cloud.s["relay_pending"], cloud._save, config.get("fallback", False))
    if config.get("door_url"):
        hub = DoorLink(config["door_url"], os.environ["DOOR_AGENT_TOKEN"], args.local_hub)
    else:
        hub = HubLink(config["hub_url"], os.environ["DOOR_HUB_AGENT_TOKEN"], args.local_hub)
    while True:
        try:
            cycle(cloud, sms, relay, hub, config["line_uid"])
        except KeyboardInterrupt:
            hub.close()
            return 0
        except Exception as exc:
            # Sem corpos de SMS, tokens, caminhos do Mac ou payloads nos logs.
            print("Ciclo pendente:", type(exc).__name__, flush=True)
            hub.close()
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
