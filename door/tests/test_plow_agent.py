"""Door as a Plow cloud agent, against a pretend Plow that speaks the contract MyPlow's bridge uses. Real: the agent process code, the Swift
panel, the host, the approval and task machinery. Pretend: Plow itself (HTTP) and the model."""
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from door import plow_agent
from door.common import now
from door.host import Host
from door.plow import PlowAPI
from door.sandbox import RunResult
from door.service import cycle
from tests.fake_plow import FakePlow
from tests.test_v03 import repo

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "panel" / ".build" / "debug" / "door-panel"
OWNER_PHONE, ANA, BOB = "+15550000001", "+15551110001", "+15551110002"
AGENT_TOKEN = "a" * 32


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Runtime:
    def available(self): return True
    def cleanup_stale(self): pass
    def kill(self, n): pass
    def run(self, spec, timeout):
        (Path(spec["outbox_dir"]) / "answer.md").write_text("Run scripts/deploy.sh."); return RunResult(0)


@unittest.skipUnless(BINARY.exists(), "build the panel first: (cd panel && swift build)")
class OnPlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.pport = free_port()
        env = dict(os.environ, DOOR_PANEL_OWNER_TOKEN="o" * 32, DOOR_PANEL_AGENT_TOKEN=AGENT_TOKEN, DOOR_PANEL_PORT=str(self.pport))
        self.panel = subprocess.Popen([str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try: socket.create_connection(("127.0.0.1", self.pport), 0.2).close(); break
            except OSError: time.sleep(0.1)
        r = repo(self.root / "proj", {"README.md": "deploy with scripts/deploy.sh"})
        cfg = self.root / "cfg" / "door.json"; cfg.parent.mkdir()
        cfg.write_text(json.dumps({"version": 1, "verification": {"mode": "off"}, "agent": {"alias": "desk", "exports": [{"name": "p", "repo": str(r)}]}}))
        self.host = Host(cfg, self.root / "state", Runtime(), "K"); self.host.proxy.start()
        self.plow = FakePlow(self.host)
        self.plow.chat("cht_owner", OWNER_PHONE)
        self.env = {"PLOW_API_BASE": self.plow.url, "DOOR_ALLOW_LOCAL": "1", "DOOR_STATE": str(self.root / "agent"),
                    "DOOR_PANEL_API": "http://127.0.0.1:%d" % self.pport, "DOOR_PANEL_AGENT_TOKEN": AGENT_TOKEN, "DOOR_PUBLIC_URL": "https://door.example"}
        self.api, self.cloud, self.hub = plow_agent.build(self.env)
        self.cloud.s["started_at"] = now() - 5

    def tearDown(self):
        self.host.proxy.stop(); self.plow.close(); self.panel.terminate(); self.panel.wait(5); self.tmp.cleanup()

    def tick(self, n=1):
        for _ in range(n):
            cycle(self.cloud, self.api, plow_agent.relay_for(self.api, self.cloud), self.hub, None); time.sleep(0.12)

    def until(self, cond, what, tries=60):
        for _ in range(tries):
            self.tick()
            if cond(): return
        self.fail("never happened: %s. Texts to the owner: %s" % (what, self.plow.texts_to("cht_owner")))

    def onboard(self):
        code = self.cloud.ensure_activation()
        self.plow.say("cht_owner", OWNER_PHONE, "Door Activate: " + code)
        self.until(lambda: self.cloud.s["owner_phone"] == OWNER_PHONE, "the owner to be activated")
        pair = self.host.pair_start()["code"]
        self.plow.say("cht_owner", OWNER_PHONE, "Door Pair: " + pair)
        self.until(lambda: self.cloud.s.get("host_id"), "the Mac to be paired")

    def web(self, path, ck=None, method="GET", body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.pport, timeout=5)
        h = {"Cookie": ck} if ck else {}
        if body is not None: h.update({"Content-Type": "application/json", "X-Door-Chat": "1"})
        c.request(method, path, json.dumps(body) if body is not None else None, h); r = c.getresponse(); return r.status, r.getheader("Set-Cookie"), r.read()

    def test_the_agent_uses_plows_placeholder_token_and_needs_no_secret(self):
        self.tick()
        self.assertEqual(self.plow.auth_seen, {"Bearer proxied"})

    def test_owner_onboarding_by_text(self):
        self.onboard()
        texts = self.plow.texts_to("cht_owner")
        self.assertTrue(any("Door is activated" in t for t in texts), texts); self.assertTrue(any("Mac paired" in t for t in texts), texts)
        self.assertEqual(self.cloud.s["summary"]["alias"], "desk")                                   # the Mac told the cloud what it offers

    def test_a_stranger_cannot_become_the_owner_and_a_wrong_code_does_nothing(self):
        self.plow.chat("cht_eve", "+15559990009")
        self.plow.say("cht_eve", "+15559990009", "Door Activate: " + (self.cloud.ensure_activation() + "x"))
        self.plow.say("cht_owner", OWNER_PHONE, "Door Activate: WRONG")
        self.tick(3)
        self.assertIsNone(self.cloud.s["owner_phone"])

    def test_the_owner_texts_for_a_link_and_a_code_and_two_people_get_answers(self):
        self.onboard()
        self.cloud.set_plan("active", now() + 86400 * 30)
        # a link, asked for by text; the URL comes back by text and works on the panel
        self.plow.say("cht_owner", OWNER_PHONE, "Door Link Ana")
        self.until(lambda: any("Link for Ana" in t for t in self.plow.texts_to("cht_owner")), "the link text")
        url = [t for t in self.plow.texts_to("cht_owner") if "Link for Ana" in t][0].split("https://door.example")[1].split(" ")[0]
        st, setc, page = self.web(url); self.assertEqual(st, 200); ck = setc.split(";")[0]; token = url.split("/")[2]
        self.assertEqual(self.web("/chat/%s/send" % token, ck, "POST", {"text": "How do I deploy?"})[0], 200)
        def ana_answer():
            _, _, d = self.web("/chat/%s/messages" % token, ck)
            return [m["text"] for m in json.loads(d)["messages"] if m["role"] == "agent"]
        self.until(lambda: ana_answer(), "Ana's answer in her chat page")
        self.assertEqual(ana_answer(), ["Run scripts/deploy.sh."])
        # a code, asked for by text; Bob joins by text from his own phone and gets his answer by text
        self.plow.say("cht_owner", OWNER_PHONE, "Door Invite Bob")
        self.until(lambda: any("Door Join:" in t for t in self.plow.texts_to("cht_owner")), "the invite text")
        code = [t for t in self.plow.texts_to("cht_owner") if "Door Join:" in t][0].split("Door Join: ")[1].split(" ")[0]
        self.plow.chat("cht_bob", BOB)
        self.plow.say("cht_bob", BOB, "Door Join: " + code)
        self.until(lambda: any("You're in" in t for t in self.plow.texts_to("cht_bob")), "Bob to be let in")
        self.plow.say("cht_bob", BOB, "How do I deploy?")
        self.until(lambda: "Run scripts/deploy.sh." in self.plow.texts_to("cht_bob"), "Bob's answer by text")
        self.assertFalse(any("Run scripts" in t for t in self.plow.texts_to("cht_owner")))               # answers go to the asker only

    def test_a_group_answers_only_when_everyone_in_it_is_trusted(self):
        self.onboard(); self.cloud.set_plan("active", now() + 86400 * 30)
        gid = self.cloud.add_guest(ANA, "Ana")
        self.plow.chat("cht_group", OWNER_PHONE, ANA)
        self.plow.say("cht_group", ANA, "Door, how do I deploy?")
        self.until(lambda: "Run scripts/deploy.sh." in self.plow.texts_to("cht_group"), "the answer in the group")
        self.plow.chat("cht_mixed", OWNER_PHONE, ANA, "+15557770007")
        self.plow.say("cht_mixed", ANA, "Door, how do I deploy?"); self.tick(4)
        self.assertEqual(self.plow.texts_to("cht_mixed"), [])                                          # a stranger is in that group: silence

    def test_without_a_mac_connected_the_owner_is_told_clearly(self):
        self.plow.with_latch = False
        code = self.cloud.ensure_activation()
        self.plow.say("cht_owner", OWNER_PHONE, "Door Activate: " + code); self.tick(3)
        self.plow.say("cht_owner", OWNER_PHONE, "Door Pair: ABCD1234"); self.tick(3)
        self.assertTrue(any("No Mac is connected to this Plow account" in t for t in self.plow.texts_to("cht_owner")))

    def test_a_chat_without_a_roster_is_ignored_rather_than_guessed(self):
        self.plow.chats["cht_odd"] = {"participants": [], "messages": []}
        self.plow.say("cht_odd", ANA, "hello"); self.tick(2)
        self.assertEqual(self.plow.texts_to("cht_odd"), [])

    def test_check_command_describes_the_wiring(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            old = dict(os.environ); os.environ.update(self.env)
            try: rc = plow_agent.check()
            finally: os.environ.clear(); os.environ.update(old)
        out = buf.getvalue()
        self.assertEqual(rc, 0, out); self.assertIn("Plow: reachable", out); self.assertIn("Mac relay (Latch): connected", out); self.assertIn("Door panel: reachable", out)
        self.assertNotIn(AGENT_TOKEN, out)


class Plan(unittest.TestCase):
    def test_a_fresh_install_is_usable_and_billing_is_opt_in(self):
        import os, tempfile
        from door.plow_agent import build
        with tempfile.TemporaryDirectory() as d:
            env = {"DOOR_STATE": d, "DOOR_PANEL_AGENT_TOKEN": "x" * 32, "PLOW_API_BASE": "http://127.0.0.1:9", "DOOR_ALLOW_LOCAL": "1"}
            _, cloud, _ = build(env)
            self.assertEqual(cloud.s["plan"]["status"], "active")
        with tempfile.TemporaryDirectory() as d:
            env = {"DOOR_STATE": d, "DOOR_PANEL_AGENT_TOKEN": "x" * 32, "PLOW_API_BASE": "http://127.0.0.1:9", "DOOR_ALLOW_LOCAL": "1", "DOOR_BILLING": "1"}
            _, cloud, _ = build(env)
            self.assertEqual(cloud.s["plan"]["status"], "inactive")


if __name__ == "__main__":
    unittest.main()
