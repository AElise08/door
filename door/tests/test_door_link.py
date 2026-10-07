"""Cloud agent <-> Door panel, with the real Swift panel binary (skipped if it is not built)."""
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from door.cloud import Cloud
from door.common import now
from door.door_link import DoorLink, to_panel_snapshot
from door.service import panel_command

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "panel" / ".build" / "debug" / "door-panel"
OWNER, AGENT = "o" * 32, "a" * 32
SUMMARY = {"alias": "desk", "description": "d", "max_capability": "ask",
           "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10,
                      "guest_daily_tokens": 400000, "monthly_budget": 50.0, "currency": "USD"}}


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@unittest.skipUnless(BINARY.exists(), "build the panel first: (cd panel && swift build)")
class DoorPanelWithCloud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        env = dict(os.environ, DOOR_PANEL_OWNER_TOKEN=OWNER, DOOR_PANEL_AGENT_TOKEN=AGENT, DOOR_PANEL_PORT=str(self.port))
        self.proc = subprocess.Popen([str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        self.t = now()
        self.cloud = Cloud(Path(self.tmp.name) / "c.db", "owner-1", SUMMARY, "https://panel.example", approval="each")
        self.cloud.set_plan("active", self.t + 86400 * 30)
        self.cloud.s.update(owner_phone="+15550000001", owner_thread="owner-thread")
        self.gid = self.cloud.add_guest("+15551234567", "Ana")
        self.link = DoorLink("http://127.0.0.1:%d" % self.port, AGENT, local=True)
        self.cookie = self.login()

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(5); self.tmp.cleanup()

    def http(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body, headers or {})
        r = c.getresponse(); data = r.read()
        return r.status, r.getheader("Set-Cookie"), data

    def login(self):
        st, cookie, _ = self.http("POST", "/login", "token=" + OWNER, {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(st, 302)
        return cookie.split(";")[0]

    def state(self):
        st, _, data = self.http("GET", "/api/state", headers={"Cookie": self.cookie})
        self.assertEqual(st, 200)
        return json.loads(data)

    def command(self, cmd):
        return self.http("POST", "/api/command", json.dumps(cmd), {"Cookie": self.cookie, "Content-Type": "application/json", "X-Door-Panel": "1"})[0]

    def publish(self):
        """One sync cycle exactly like service.cycle does for the panel."""
        out = self.link.rpc("door.publish", {"snapshot": self.cloud.snapshot(), "ack": list(self.cloud.s.setdefault("panel_seen", {}))})
        for c in out["commands"]:
            if c["id"] in self.cloud.s["panel_seen"]:
                continue
            try:
                panel_command(self.cloud, c); self.cloud.s["panel_seen"][c["id"]] = {"ok": True}
            except (ValueError, KeyError, TypeError) as e:
                self.cloud.s["panel_seen"][c["id"]] = {"ok": False, "error": str(e)}
            self.cloud._save()

    def ask(self):
        return self.cloud.receive("m" + str(time.time_ns()), "+15551234567", "guest-thread", "How does mp send route messages?")

    def test_request_shows_up_and_owner_approves_in_panel(self):
        rid = self.ask()
        self.publish()
        q = self.state()["snapshot"]["queue"]
        self.assertEqual([x["request_id"] for x in q], [rid])
        self.assertEqual(q[0]["guest"], "Ana")
        self.assertEqual(q[0]["text"], "How does mp send route messages?")
        self.assertEqual(self.command({"type": "approve", "request_id": rid, "text_hash": q[0]["text_hash"]}), 200)
        self.publish()
        self.assertEqual(self.cloud.s["requests"][rid]["state"], "queued")
        self.assertEqual(self.cloud.s["requests"][rid]["approval"]["decided_by"], "panel:owner")
        self.publish()     # acked: not applied twice
        self.assertEqual(self.http("GET", "/agent/commands", headers={"Authorization": "Bearer " + AGENT})[2], b'{"commands":[],"owner_present":true}')

    def test_approval_is_bound_to_the_exact_text(self):
        rid = self.ask()
        self.publish()
        self.assertEqual(self.command({"type": "approve", "request_id": rid, "text_hash": "0" * 64}), 200)   # well-formed, but not this text
        self.publish()
        self.assertEqual(self.cloud.s["requests"][rid]["state"], "waitingApproval")
        self.assertFalse(self.cloud.s["panel_seen"][list(self.cloud.s["panel_seen"])[0]]["ok"])

    def test_deny_guests_and_pause_from_panel(self):
        rid = self.ask(); self.publish()
        h = self.state()["snapshot"]["queue"][0]["text_hash"]
        self.command({"type": "deny", "request_id": rid, "text_hash": h})
        self.command({"type": "add_guest", "phone": "+15557654321", "display_name": "Bo", "days": 7})
        self.command({"type": "pause"})
        self.publish()
        self.assertEqual(self.cloud.s["requests"][rid]["terminal_reason"], "denied_owner")
        self.assertTrue(self.cloud.s["paused"])
        self.assertEqual(sorted(g["display_name"] for g in self.cloud.s["guests"].values()), ["Ana", "Bo"])
        self.publish()   # the next cycle publishes the new state
        snap = self.state()["snapshot"]
        self.assertTrue(snap["mac"]["paused"])
        self.assertEqual(sorted(g["name"] for g in snap["guests"]), ["Ana", "Bo"])

    def test_invite_and_access_request_from_the_panel(self):
        self.assertEqual(self.command({"type": "invite", "display_name": "Cy", "days": 14}), 200)
        self.publish()                                   # cloud creates the code
        self.publish()                                   # next cycle shows it in the panel
        inv = self.state()["snapshot"]["invites"]
        self.assertEqual(len(inv), 1); self.assertEqual(inv[0]["name"], "Cy")
        self.cloud.receive("j1", "+15553330003", "cy-thread", "Door Join: " + inv[0]["code"])
        self.assertEqual([g["display_name"] for g in self.cloud.s["guests"].values()].count("Cy"), 1)
        self.publish()
        self.assertEqual(self.state()["snapshot"]["invites"], [])          # used codes disappear
        # a stranger asks to be let in; the owner allows it in the panel
        self.cloud.receive("r1", "+15559990009", "eve-thread", "Door Request: Eve")
        self.publish()
        self.assertEqual([a["phone"] for a in self.state()["snapshot"]["access_requests"]], ["+15559990009"])
        self.command({"type": "allow_access", "phone": "+15559990009"})
        self.publish()
        self.assertTrue(any(g["phone"] == "+15559990009" for g in self.cloud.s["guests"].values()))
        self.publish()
        self.assertEqual(self.state()["snapshot"]["access_requests"], [])

    # ---- shared chat link: owner creates it, the guest chats in a browser, the owner approves, the answer shows up ----
    def guest_http(self, method, path, body=None, cookie=None):
        h = {"Content-Type": "application/json", "X-Door-Chat": "1"}
        if cookie:
            h["Cookie"] = cookie
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body, h)
        r = c.getresponse(); data = r.read()
        return r.status, r.getheader("Set-Cookie"), data

    def cycle(self):
        from door.service import cycle
        class NoSMS:
            def messages(self, *a): return iter(())
            def send(self, *a): pass
        self.cloud.s.setdefault("started_at", now())
        cycle(self.cloud, NoSMS(), None, self.link, "line")

    def test_chat_link_end_to_end(self):
        st, _, data = self.http("POST", "/api/command", json.dumps({"type": "web_link", "display_name": "Cy", "days": 14}),
                                {"Cookie": self.cookie, "Content-Type": "application/json", "X-Door-Panel": "1"})
        self.assertEqual(st, 200)
        path = json.loads(data)["path"]
        st, setc, page = self.guest_http("GET", path)                       # the guest opens the link
        self.assertEqual(st, 200); self.assertIn(b"Ask anything", page)
        ck = setc.split(";")[0]
        self.assertEqual(self.guest_http("GET", path)[0], 403)              # a second browser is refused
        token = path.split("/")[2]
        self.assertEqual(self.guest_http("POST", "/chat/%s/send" % token, json.dumps({"text": "How do I deploy?"}), ck)[0], 200)
        self.cycle()                                                          # the agent picks it up
        guests = [g for g in self.cloud.s["guests"].values() if g.get("link_id")]
        self.assertEqual([(g["display_name"], g["phone"]) for g in guests], [("Cy", "")])
        req = next(r for r in self.cloud.s["requests"].values() if r["guest_id"] == guests[0]["guest_id"])
        self.assertEqual((req["state"], req["thread_id"].startswith("web:")), ("waitingApproval", True))
        _, _, m = self.guest_http("GET", "/chat/%s/messages" % token, None, ck)
        texts = [(x["role"], x["text"]) for x in json.loads(m)["messages"]]
        self.assertIn(("system", "Received. The owner will approve it before I answer."), texts)
        # the owner sees it in the panel (the next cycle publishes it) and approves it there
        self.cycle()
        q = self.state()["snapshot"]["queue"]
        self.assertEqual((q[0]["guest"], q[0]["text"]), ("Cy", "How do I deploy?"))
        self.command({"type": "approve", "request_id": req["request_id"], "text_hash": q[0]["text_hash"]})
        self.cycle()
        self.assertEqual(self.cloud.s["requests"][req["request_id"]]["state"], "queued")
        # the Mac answers (simulated) and the reply arrives in the guest's chat
        r = self.cloud.s["requests"][req["request_id"]]
        self.cloud._transition(r, "running")
        self.cloud._result(r, {"state": "completed", "reply": {"text": "Use the deploy script.", "held": False}})
        self.cloud._save(); self.cycle()
        _, _, m = self.guest_http("GET", "/chat/%s/messages" % token, None, ck)
        self.assertIn(("agent", "Use the deploy script."), [(x["role"], x["text"]) for x in json.loads(m)["messages"]])
        # the owner turns the link off: access ends and the guest is revoked in the cloud
        lid = self.state()["links"][0]["id"]
        self.command({"type": "revoke_link", "link_id": lid})
        self.cycle()
        self.assertEqual(self.cloud.s["guests"][guests[0]["guest_id"]]["status"], "revoked")
        self.assertEqual(self.guest_http("GET", "/chat/%s/messages" % token, None, ck)[0], 404)

    def test_snapshot_never_leaks_host_secrets(self):
        self.cloud.s["private"] = "PRIVATE-KEY-MARKER"
        self.cloud.s["host_id"] = "HOST-ID-MARKER"
        blob = json.dumps(to_panel_snapshot(self.cloud.snapshot()))
        self.assertNotIn("PRIVATE-KEY-MARKER", blob)
        self.assertNotIn("HOST-ID-MARKER", blob)

    def test_panel_rejects_agent_without_token(self):
        self.assertEqual(self.http("GET", "/agent/commands")[0], 401)
        self.assertEqual(self.http("PUT", "/agent/snapshot", "{}", {"Authorization": "Bearer " + OWNER})[0], 401)

    def test_link_refuses_plain_http_outside_dev(self):
        with self.assertRaises(ValueError):
            DoorLink("http://panel.example", AGENT)


@unittest.skipUnless(BINARY.exists(), "build the panel first")
class MultiTenantBilling(unittest.TestCase):
    """Operator creates a customer, marks the plan active; the customer's agent picks it up and enforces it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.admin = "z" * 40
        env = dict(os.environ, DOOR_PANEL_ADMIN_TOKEN=self.admin, DOOR_PANEL_DATA=str(Path(self.tmp.name) / "tenants.json"),
                   DOOR_PANEL_PORT=str(self.port))
        for k in ("DOOR_PANEL_OWNER_TOKEN", "DOOR_PANEL_AGENT_TOKEN"):
            env.pop(k, None)
        self.proc = subprocess.Popen([str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(5); self.tmp.cleanup()

    def admin_call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Authorization": "Bearer " + self.admin, "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_operator_activates_plan_and_agent_enforces_it(self):
        st, t = self.admin_call("POST", "/admin/tenants", {"name": "Acme"})
        self.assertEqual(st, 200)
        cloud = Cloud(Path(self.tmp.name) / "c.db", "acme", SUMMARY, "https://panel.example", approval="each")
        link = DoorLink("http://127.0.0.1:%d" % self.port, t["agent_token"], local=True)
        cloud.add_guest("+15551234567", "Ana"); cloud.s.update(owner_phone="+15550000001", owner_thread="o")
        # new customer: plan inactive -> the guest is refused
        from door.service import cycle
        class NoSMS:
            def messages(self, *a): return iter(())
            def send(self, *a): pass
        cloud.s["started_at"] = now()
        cycle(cloud, NoSMS(), None, link, "line")
        self.assertEqual(cloud.s["plan"]["status"], "inactive")
        self.assertIsNone(cloud.receive("m1", "+15551234567", "g", "hello?"))
        # operator marks the plan active (manual billing); next cycle the agent accepts requests
        self.assertEqual(self.admin_call("POST", "/admin/tenants/%s/plan" % t["tenant_id"], {"status": "active", "active_until": now() + 86400 * 30})[0], 200)
        cycle(cloud, NoSMS(), None, link, "line")
        self.assertEqual(cloud.s["plan"]["status"], "active")
        self.assertIsNotNone(cloud.receive("m2", "+15551234567", "g", "hello again?"))
        # operator cancels: agent stops accepting new requests
        self.admin_call("POST", "/admin/tenants/%s/plan" % t["tenant_id"], {"status": "canceled", "active_until": 0})
        cycle(cloud, NoSMS(), None, link, "line")
        self.assertIsNone(cloud.receive("m3", "+15551234567", "g", "one more?"))


if __name__ == "__main__":
    unittest.main()
