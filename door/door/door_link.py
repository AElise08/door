"""Link between the cloud agent (cloud.Cloud) and the Door owner panel.

Outbound only: the agent pushes a snapshot and pulls owner commands over HTTPS. The panel never reaches the
agent, and neither of them ever reaches the owner's Mac. Same interface as HubLink.rpc so service.cycle is unchanged.
"""
import json
import urllib.request
from urllib.parse import urlparse

DOOR_OWNER = "owner"


def _name(guest):
    return guest.get("display_name") or guest.get("phone", "?")


def to_panel_snapshot(snap):
    """Cloud.snapshot() -> the JSON the Door panel renders. Never includes phone numbers of non-guests, host ids or paths."""
    guests = {g["guest_id"]: g for g in snap["guests"]}
    for oid in snap.get("owner_ids", []):
        guests[oid] = {"display_name": "You"}                      # the owner's own requests (not a guest, never listed as one)
    usage = snap["guest_usage"]
    reqs = sorted(snap["requests"], key=lambda r: r["created_at"], reverse=True)
    queue, held = [], []
    for r in sorted(snap["requests"], key=lambda r: r["created_at"]):
        g = guests.get(r["guest_id"], {})
        if r["state"] == "waitingApproval":
            queue.append({"request_id": r["request_id"], "text_hash": r["text_hash"], "guest": _name(g), "agent": "Boss (auto)" if r["agent_alias"] == "auto" else r["agent_alias"],
                          "text": r.get("text", ""), "used_today": usage.get(r["guest_id"], {}).get("daily_requests", 0),
                          "limit_today": g.get("limits", {}).get("daily_requests", 0), "deadline_at": r["deadline_at"]})
        rep = r.get("reply") or {}
        if rep.get("held") and not rep.get("reviewed") and rep.get("held_text"):
            held.append({"request_id": r["request_id"], "guest": _name(g), "held_text": rep["held_text"]})
    tel = snap["telemetry"]
    return {
        "mac": {"online": bool(snap["host_online"]), "paused": bool(snap["paused"])},
        "plan": snap["plan"], "queue": queue, "held": held, "approval": snap.get("settings", {}).get("approval", "each"),
        "history": [{"request_id": r["request_id"], "guest": _name(guests.get(r["guest_id"], {})), "state": r["state"],
                     "text": " ".join(str(r.get("text", "")).split())[:160], "kind": "task" if r.get("capability") == "act" else "question",
                     "reason": r.get("terminal_reason") or ("out_of_scope" if r.get("refused") else ""), "updated_at": r["updated_at"],
                     "verification": (r.get("verification") or {}).get("status", ""), "files": (r.get("verification") or {}).get("files", [])} for r in reqs[:50]],
        "invites": [{"code": i["code"], "name": i["name"], "expires_at": i["expires_at"], "days": i["days"]} for i in snap.get("invites", [])],
        "access_requests": [{"phone": a["phone"], "name": a["name"], "at": a["at"]} for a in snap.get("access_requests", [])],
        "guests": [{"guest_id": g["guest_id"], "phone": g["phone"] or "web link", "name": g.get("display_name", ""), "status": g["status"],
                    "expires_at": g["expires_at"], "approval": g.get("approval") or "", "level": g.get("level", "ask"),
                    "link_id": g.get("link_id") or ""} for g in snap["guests"]],
        "actions": [{"request_id": a["request_id"], "action_id": a["id"], "guest": _name(guests.get(a["guest_id"], {})), "tool": a["tool"], "summary": a["summary"], "at": a["at"]}
                    for a in snap.get("actions", [])],
        "act_enabled": bool((snap.get("agent") or {}).get("act_agent")),
        "owner_keys": ["g_" + i for i in snap.get("owner_ids", [])] + ["g_owner"],     # board cards the owner made by text (older builds used "g_owner")
        "setup": snap.get("setup") or {},
        "usage_by_guest": [{"guest": _name(guests.get(gid, {})), "tokens": u["tokens"], "cost": u["cost"]}
                           for gid, u in usage.items() if u["tokens"]],
        "cost": {"month_spent": tel["total_cost"], "budget": (tel.get("budget") or {}).get("limit", 0),
                 "currency": tel["currency"], "pct": tel["budget_percent"] * 100},
    }


def to_cloud_command(c):
    """Panel command -> service.panel_command format. Unknown types raise ValueError (the cycle records them as refused)."""
    t, rid = c["type"], c.get("request_id")
    base = {"id": c["id"], "owner_session": DOOR_OWNER}
    if t in ("approve", "deny"):
        return {**base, "op": "decide", "decision": t, "request_id": rid, "text_hash": c["text_hash"]}
    if t == "cancel":
        return {**base, "op": "cancel", "request_id": rid}
    if t in ("release", "discard"):
        return {**base, "op": "held", "request_id": rid, "release": t == "release"}
    if t in ("suspend", "revoke", "reactivate"):
        return {**base, "op": "guest.status", "guest_id": c["guest_id"],
                "status": {"suspend": "suspended", "revoke": "revoked", "reactivate": "active"}[t]}
    if t in ("pause", "resume"):
        return {**base, "op": "pause", "paused": t == "pause"}
    if t == "guest_level":
        return {**base, "op": "guest.level", "guest_id": c["guest_id"], "level": c["level"]}
    if t in ("action_allow", "action_deny"):
        return {**base, "op": "action.decide", "request_id": c["request_id"], "action_id": c["action_id"], "decision": "allow" if t == "action_allow" else "deny"}
    if t == "set_approval":
        return {**base, "op": "settings.approval", "mode": c["mode"]}
    if t == "guest_approval":
        return {**base, "op": "guest.approval", "guest_id": c["guest_id"], "mode": None if c["mode"] == "default" else c["mode"]}
    if t == "link_revoked":
        return {**base, "op": "link.revoked", "link_id": c["link_id"]}
    if t == "invite":
        return {**base, "op": "invite.create", "name": c.get("display_name", ""), "days": c.get("days", 30), "ttl_days": c.get("ttl_days", 7)}
    if t == "revoke_invite":
        return {**base, "op": "invite.revoke", "code": c["code"]}
    if t in ("allow_access", "ignore_access"):
        return {**base, "op": "access.resolve", "phone": c["phone"], "allow": t == "allow_access"}
    if t == "add_guest":
        limits = {k: c[k] for k in ("daily_requests", "daily_tokens") if k in c}
        if "max_open" in c:
            limits["max_open_requests"] = c["max_open"]
        return {**base, "op": "guest.add", "phone": c["phone"], "name": c.get("display_name", ""), "days": c.get("days", 30), "limits": limits}
    raise ValueError("unknown panel command")


class DoorLink:
    def __init__(self, url, token, local=False, timeout=10):
        u = urlparse(url)
        if u.scheme != "https" and not (local and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
            raise ValueError("Door panel requires HTTPS (or explicit loopback in development)")
        self.base, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _req(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=self.timeout) as resp:
            return json.loads(resp.read() or b"{}")

    def rpc(self, method, params):
        if method != "door.publish" and method != "door.publish":
            raise ValueError("unsupported method")
        ack = list(params.get("ack", []))
        if ack:
            self._req("POST", "/agent/ack", {"ids": ack})
        self._req("PUT", "/agent/snapshot", to_panel_snapshot(params["snapshot"]))
        commands = []
        got = self._req("GET", "/agent/commands")
        for c in got.get("commands", []):
            try:
                commands.append(to_cloud_command(c))
            except (KeyError, ValueError):
                commands.append({"id": c.get("id", "bad"), "op": "invalid"})   # recorded as refused by panel_command
        out = {"commands": commands}
        if isinstance(got.get("plan"), dict):    # billing phase A: the operator sets the plan, the agent enforces it
            out["plan"] = got["plan"]
        return out

    # --- shared chat links (the panel hosts the page) ---
    def inbox(self):
        return self._req("GET", "/agent/inbox").get("messages", [])

    def ack_inbox(self, ids):
        if ids:
            self._req("POST", "/agent/inbox/ack", {"ids": ids})

    def card(self, job):
        """Create or move a board card for a task. Failures raise, so the cloud keeps the job and retries."""
        body = {k: job[k] for k in ("owner", "card_id", "title", "note", "column", "request_id", "verdict", "proof") if job.get(k) is not None}
        self._req("POST", "/agent/card", dict(body, op="update" if job["op"] == "card.update" else "add"))

    def create_link(self, job):
        """Ask the panel for a chat link; returns its path (the secret part). Shown to the owner once, by text message."""
        return self._req("POST", "/agent/links", {"name": job.get("name", ""), "days": job.get("days", 30), "ttl_days": job.get("ttl_days", 7)})["path"]

    def signin(self):
        return self._req("POST", "/agent/signin", {})["path"]

    def chat(self, link_id, text, kind="system"):
        self._req("POST", "/agent/chat", {"link_id": link_id, "text": text, "kind": kind})

    def close(self):
        pass
