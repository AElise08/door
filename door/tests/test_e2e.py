"""The whole product in one test: guest page -> panel -> cloud agent -> host -> task on a branch -> owner approves a step ->
Door checks the delivery -> card moves to Done with proof. Real: Swift panel, cloud, host, git, the approval protocol.
Simulated: the model (a fake `claude`), the independent checker, and the Plow line and Latch relay."""
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
from door.door_link import DoorLink
from door.host import Host
from door.sandbox import RunResult
from door.service import cycle
from tests.test_v03 import repo

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "panel" / ".build" / "debug" / "door-panel"
FAKE = str(ROOT / "tests" / "fake_claude.py")
OWNER, AGENT = "o" * 32, "a" * 32


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Runtime:
    verifier = "VERIFIED: the new file is what was asked for"
    def available(self): return True
    def cleanup_stale(self): pass
    def kill(self, n): pass
    def run(self, spec, timeout):
        if spec["name"].startswith("door-verify-") and self.verifier:
            (Path(spec["outbox_dir"]) / "answer.md").write_text(self.verifier); return RunResult(0)
        return RunResult(1)


class LoopbackRelay:
    """Plays the Plow/Latch relay: calls the host's local socket handler directly."""
    def __init__(self, host): self.host = host
    def ask(self, rid, payload, sig): return self.host.ask(payload, sig)
    def status(self, rid): return self.host.status(rid)
    def command(self, argv):
        if argv[1] == "summary": return self.host.summary()
        if argv[1] == "decide":
            a = dict(zip(argv[2::2], argv[3::2]))
            return self.host.decide_action(a["--request"], a["--action"], a["--decision"])
        if argv[1] == "cancel":
            a = dict(zip(argv[2::2], argv[3::2])); return self.host.cancel(a["--request"], a["--reason"])
        return {"ok": False}


class NoSMS:
    def messages(self, *a): return iter(())
    def send(self, *a): pass


@unittest.skipUnless(BINARY.exists(), "build the panel first: (cd panel && swift build)")
class WholeProduct(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.port = free_port()
        env = dict(os.environ, DOOR_PANEL_OWNER_TOKEN=OWNER, DOOR_PANEL_AGENT_TOKEN=AGENT, DOOR_PANEL_PORT=str(self.port))
        self.proc = subprocess.Popen([str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try: socket.create_connection(("127.0.0.1", self.port), 0.2).close(); break
            except OSError: time.sleep(0.1)
        self.repo = repo(self.root / "proj", {"README.md": "# demo\n"})
        script = self.root / "script.json"
        script.write_text(json.dumps({"steps": [{"ask": ["Bash", {"command": "npm install eslint"}], "write": ["NOTES.md", "# Notes\n"]}], "final": "I added NOTES.md."}))
        self.policy = self.root / "cfg" / "door.json"; self.policy.parent.mkdir()
        self.policy.write_text(json.dumps({"version": 1, "verification": {"mode": "off"}, "agents": [
            {"alias": "dev", "exports": [{"name": "p", "repo": str(self.repo)}], "act": {
                "project": str(self.repo), "claude_bin": FAKE, "timeout_s": 60, "approval_timeout_s": 60, "env": {"FAKE_CLAUDE_FILE": str(script)},
                "proof": {"commands": ["test -f NOTES.md"], "timeout_s": 30}}}]}))
        self.rt = Runtime()
        self.host = Host(self.policy, self.root / "state", self.rt, "K"); self.host.proxy.start()
        self.cloud = Cloud(self.root / "cloud.db", "owner", {"alias": "dev", "description": "", "max_capability": "ask", "limits": {
            "max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 50, "guest_daily_tokens": 10**7, "monthly_budget": 50.0, "currency": "USD"}},
            f"http://127.0.0.1:{self.port}", approval="auto")
        self.cloud.set_plan("active", now() + 86400 * 30); self.cloud.s["started_at"] = now(); self.cloud.s["host_id"] = "h_test"
        self.host.pair_confirm(self.host.pair_start()["code"], self.cloud.public_key())
        self.link = DoorLink(f"http://127.0.0.1:{self.port}", AGENT, local=True)
        self.relay = LoopbackRelay(self.host)
        # the owner logs into the panel
        st, ck, _ = self.http("POST", "/login", "token=" + OWNER, {"Content-Type": "application/x-www-form-urlencoded"})
        self.owner_cookie = ck.split(";")[0]

    def tearDown(self):
        for rid in list(self.host._running): self.host.cancel(rid); self.host.wait(rid, 10)
        self.host.proxy.stop(); self.proc.terminate(); self.proc.wait(5); self.tmp.cleanup()

    def http(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5); c.request(method, path, body, headers or {})
        r = c.getresponse(); return r.status, r.getheader("Set-Cookie"), r.read()

    def owner(self, cmd):
        return self.http("POST", "/api/command", json.dumps(cmd), {"Cookie": self.owner_cookie, "Content-Type": "application/json", "X-Door-Panel": "1"})

    def owner_state(self): return json.loads(self.http("GET", "/api/state", headers={"Cookie": self.owner_cookie})[2])

    def guest(self, method, path, ck, body=None):
        s, _, d = self.http(method, path, json.dumps(body) if body is not None else None, {"Cookie": ck, "Content-Type": "application/json", "X-Door-Chat": "1"})
        return s, json.loads(d or b"{}")

    def tick(self, n=1):
        for _ in range(n):
            cycle(self.cloud, NoSMS(), self.relay, self.link, "line"); time.sleep(0.15)

    def until(self, cond, what, tries=120):
        for _ in range(tries):
            self.tick()
            if cond(): return
        self.fail("never happened: " + what)

    def test_the_owner_just_writes_and_it_gets_done_on_the_real_mac(self):
        """What the owner does by text, all the way through the real daemon's checks (signature, ids, recheck), not just the cloud."""
        self.cloud.s.update(owner_phone="+15550000001", owner_thread="ot")
        self.cloud.s["guests"]["owner"] = dict(guest_id="owner", phone="+15550000001", display_name="You", status="active", owner=True,
                                               expires_at=2 ** 40, level="act", approval="auto",
                                               limits={"daily_requests": 500, "daily_tokens": 4000000, "max_open_requests": 3})   # left by an earlier build
        self.tick(1)                                                              # learn from the Mac that tasks exist
        self.assertTrue(self.cloud.s["summary"].get("act_agent"))
        self.cloud.receive("m1", "+15550000001", "ot", "create a notes file")    # no "Do:", no command words
        # what the owner asked for herself is not put to her again: the risky step (npm install) runs without a question
        self.until(lambda: any(r["state"] in ("completed", "failed", "canceled") for r in self.cloud.s["requests"].values()), "the task to finish")
        self.assertEqual((self.owner_state()["snapshot"] or {}).get("actions", []), [])
        (r,) = self.cloud.s["requests"].values()
        self.assertEqual((r["state"], r["terminal_reason"]), ("completed", None))
        reply = (r.get("reply") or {}).get("text", "")
        self.assertIn("NOTES.md", reply); self.assertNotIn("canceled", reply.lower())
        card = [c for c in self.owner_state()["cards"] if c["title"] == "create a notes file"][0]
        self.assertEqual((card["column"], card["verdict"]), ("done", "verified"))

    def test_a_card_becomes_a_verified_delivery(self):
        # 1. the owner shares a link and trusts that person with tasks
        st, _, d = self.owner({"type": "web_link", "display_name": "Ana", "days": 30}); path = json.loads(d)["path"]
        token = path.split("/")[2]
        st, setc, _ = self.http("GET", path); ck = setc.split(";")[0]
        # 2. Ana writes on her board and presses "ask the agent to do this"
        s, added = self.guest("POST", f"/chat/{token}/card", ck, {"op": "add", "title": "Add a notes file", "note": "NOTES.md at the top level", "important": True})
        self.assertEqual(s, 200)
        # Ana's chat link becomes a guest only when she first writes; until then there is nobody to grant a level to
        self.assertEqual(self.guest("POST", f"/chat/{token}/card", ck, {"op": "run", "card_id": added["card_id"]})[0], 200)
        self.tick(2)
        guests = [g for g in self.cloud.s["guests"].values() if g.get("link_id")]
        self.assertEqual(len(guests), 1)
        # she is not trusted with tasks yet: she gets told so, and nothing runs
        _, msgs = self.guest("GET", f"/chat/{token}/messages", ck)
        self.assertTrue(any("running tasks is not enabled for you" in m["text"] for m in msgs["messages"]))
        self.assertEqual(self.host._acts, {})
        # 3. the owner trusts her with tasks, and she asks again
        self.cloud.set_guest_level(guests[0]["guest_id"], "act")
        self.assertEqual(self.guest("POST", f"/chat/{token}/card", ck, {"op": "run", "card_id": added["card_id"]})[0], 200)
        self.until(lambda: self.owner_state()["snapshot"] and self.owner_state()["snapshot"].get("actions"), "a step waiting for the owner")
        # 4. the owner sees the step in the panel and allows it
        act = self.owner_state()["snapshot"]["actions"][0]
        self.assertIn("npm install eslint", act["summary"]); self.assertEqual(act["guest"], "Ana")
        card = [c for c in self.owner_state()["cards"] if c["title"] == "Add a notes file"][0]
        self.assertEqual(card["column"], "doing")                                                  # the card shows it is being worked on
        self.assertEqual(self.owner({"type": "action_allow", "request_id": act["request_id"], "action_id": act["action_id"]})[0], 200)
        # 5. the task finishes; Door checks the delivery; the card moves to Done with proof
        self.until(lambda: [c for c in self.owner_state()["cards"] if c["title"] == "Add a notes file"][0]["column"] in ("done", "review"), "the card to be finished")
        final = [c for c in self.owner_state()["cards"] if c["title"] == "Add a notes file"][0]
        self.assertEqual((final["column"], final["verdict"]), ("done", "verified"))
        self.assertIn("Changed: NOTES.md", final["proof"]); self.assertIn("Check test -f NOTES.md: passed", final["proof"]); self.assertIn("Branch: door/", final["proof"])
        # 6. Ana sees it on her own board and in the chat; the owner's real folder is untouched
        _, board = self.guest("GET", f"/chat/{token}/board", ck)
        self.assertEqual((board["cards"][0]["column"], board["cards"][0]["verdict"]), ("done", "verified"))
        _, msgs = self.guest("GET", f"/chat/{token}/messages", ck)
        texts = [m["text"] for m in msgs["messages"] if m["role"] == "agent"]
        self.assertTrue(any("Door checked it" in t for t in texts), texts)
        self.assertFalse((self.repo / "NOTES.md").exists())
        self.assertIn("door/", subprocess.run(["git", "-C", str(self.repo), "branch"], capture_output=True, text=True).stdout)
        self.assertEqual(self.owner_state()["links"][0]["name"], "Ana")

    def test_a_failed_check_never_reaches_done(self):
        st, _, d = self.owner({"type": "web_link", "display_name": "Ana", "days": 30}); token = json.loads(d)["path"].split("/")[2]
        ck = self.http("GET", "/c/" + token)[1].split(";")[0]
        self.guest("POST", f"/chat/{token}/send", ck, {"text": "hello"}); self.tick(2)
        gid = [g for g in self.cloud.s["guests"] if self.cloud.s["guests"][g].get("link_id")][0]; self.cloud.set_guest_level(gid, "act")
        # the agent writes the wrong file, so the owner's check (test -f NOTES.md) fails
        Path(self.host.holder.policy["agents"][0]["act"]["env"]["FAKE_CLAUDE_FILE"]).write_text(json.dumps({"steps": [{"write": ["WRONG.md", "x"]}], "final": "done!"}))
        self.guest("POST", f"/chat/{token}/send", ck, {"text": "Do: add NOTES.md"})
        self.until(lambda: any(c["column"] in ("done", "review") for c in self.owner_state()["cards"]), "the card to be finished")
        c = self.owner_state()["cards"][0]
        self.assertEqual((c["column"], c["verdict"]), ("review", "failed_checks")); self.assertIn("FAILED", c["proof"])
        _, msgs = self.guest("GET", f"/chat/{token}/messages", ck)
        self.assertTrue(any("checks did NOT pass" in m["text"] for m in msgs["messages"]), [m["text"] for m in msgs["messages"]])

    def test_pausing_the_agent_stops_new_tasks(self):
        st, _, d = self.owner({"type": "web_link", "display_name": "Ana", "days": 30}); token = json.loads(d)["path"].split("/")[2]
        ck = self.http("GET", "/c/" + token)[1].split(";")[0]
        self.guest("POST", f"/chat/{token}/send", ck, {"text": "hello"}); self.tick(2)
        gid = [g for g in self.cloud.s["guests"] if self.cloud.s["guests"][g].get("link_id")][0]; self.cloud.set_guest_level(gid, "act")
        self.owner({"type": "pause"}); self.tick(2)
        self.guest("POST", f"/chat/{token}/send", ck, {"text": "Do: add NOTES.md"}); self.tick(3)
        _, msgs = self.guest("GET", f"/chat/{token}/messages", ck)
        self.assertTrue(any("paused" in m["text"] for m in msgs["messages"]))
        self.assertEqual(self.host._acts, {}); self.assertEqual(self.owner_state()["cards"], [])


if __name__ == "__main__":
    unittest.main()
