"""The screen on the owner's own computer: what it shows, and that nobody else (or no web page) can use it."""
import http.client
import json
import os
import re
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from door.common import now, sha256_text, ulid
from door.envelope import encode, generate
from door.host import Host
from door.local_ui import LocalUI, PAGE, usage_report
from door.sandbox import RunResult
from tests.test_v03 import repo


class Runtime:
    answer = "Run scripts/deploy.sh."
    def available(self): return True
    def cleanup_stale(self): pass
    def kill(self, n): pass
    def run(self, spec, timeout):
        (Path(spec["outbox_dir"]) / "answer.md").write_text(self.answer); return RunResult(0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        r = repo(self.root / "p", {"README.md": "x"})
        self.path = self.root / "c" / "door.json"; self.path.parent.mkdir()
        self.path.write_text(json.dumps({"version": 1, "verification": {"mode": "off"}, "agent": {"alias": "desk", "exports": [{"name": "p", "repo": str(r)}]}}))
        self.rt = Runtime()
        self.host = Host(self.path, self.root / "state", self.rt, "K"); self.host.proxy.start()
        self.priv, self.pub = generate(); self.host.pair_confirm(self.host.pair_start()["code"], self.pub)
        self.ui = LocalUI(self.host, 0).start()
        self.token = self.ui.token

    def tearDown(self): self.ui.stop(); self.host.proxy.stop(); self.tmp.cleanup()

    def ask(self, text="How do I deploy?", **kw):
        rid = ulid(); h = sha256_text(text)
        req = {"request_id": rid, "guest_id": ulid(), "agent_alias": "desk", "capability": "ask", "text": text, "text_hash": h, "deadline_at": now() + 100,
               "approval": {"request_id": rid, "text_hash": h, "decision": "approve"}}
        req.update(kw); out = self.host.ask(*encode(self.priv, req))
        if out.get("ok"): self.host.wait(rid, 20)
        return rid, out

    def http(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.ui.port, timeout=5)
        h = dict(headers or {}); h["Host"] = host or "127.0.0.1:%d" % self.ui.port
        c.request(method, path, body, h, )
        r = c.getresponse(); return r.status, r.getheader("Set-Cookie"), r.read()

    def cookie(self):
        st, ck, _ = self.http("GET", "/?t=" + self.token); self.assertEqual(st, 302); return ck.split(";")[0]


class Access(Base):
    def test_nothing_without_the_secret_link(self):
        for path in ("/", "/api/usage"):
            self.assertEqual(self.http("GET", path)[0], 401)
        self.assertEqual(self.http("GET", "/?t=wrong")[0], 401)
        self.assertEqual(self.http("GET", "/api/usage", headers={"Cookie": "door_local=wrong"})[0], 401)
        self.assertEqual(self.http("POST", "/api/pause", "{}", {"X-Door-Local": "1"})[0], 403)

    def test_the_secret_link_starts_a_session_and_the_page_loads(self):
        ck = self.cookie()
        st, _, body = self.http("GET", "/", headers={"Cookie": ck})
        self.assertEqual(st, 200); self.assertIn(b"Door on this computer", body)
        self.assertEqual(self.http("GET", "/api/usage", headers={"Cookie": ck})[0], 200)

    def test_a_web_page_cannot_reach_it_through_a_look_alike_host_name(self):
        ck = self.cookie()
        for host in ("evil.example", "127.0.0.1.evil.example:%d" % self.ui.port, "127.0.0.1"):
            self.assertEqual(self.http("GET", "/api/usage", headers={"Cookie": ck}, host=host)[0], 403, host)
            self.assertEqual(self.http("POST", "/api/pause", '{"paused":true}', {"Cookie": ck, "X-Door-Local": "1"}, host=host)[0], 403, host)
        self.assertFalse(self.host.paused())

    def test_changes_need_the_custom_header(self):
        ck = self.cookie()
        self.assertEqual(self.http("POST", "/api/pause", '{"paused":true}', {"Cookie": ck})[0], 403)
        self.assertFalse(self.host.paused())
        self.assertEqual(self.http("POST", "/api/pause", '{"paused":"yes"}', {"Cookie": ck, "X-Door-Local": "1"})[0], 404)
        self.assertEqual(self.http("POST", "/api/pause", "not json", {"Cookie": ck, "X-Door-Local": "1"})[0], 400)
        self.assertEqual(self.http("POST", "/api/pause", '{"paused":true}', {"Cookie": ck, "X-Door-Local": "1"})[0], 200)
        self.assertTrue(self.host.paused())
        self.assertEqual(self.http("POST", "/api/pause", '{"paused":false}', {"Cookie": ck, "X-Door-Local": "1"})[0], 200)
        self.assertFalse(self.host.paused())

    def test_the_token_is_private_and_stable(self):
        p = self.root / "state" / "local-ui-token"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.ui.stop(); self.ui = LocalUI(self.host, 0).start()
        self.assertEqual(self.ui.token, self.token)                                               # a bookmarked link keeps working after a restart

    def test_binds_to_loopback_only_and_the_page_is_safe(self):
        self.assertEqual(self.ui.httpd.server_address[0], "127.0.0.1")
        self.assertNotIn("innerHTML", PAGE)
        self.assertEqual(re.findall(r"\$\('([a-z]+)'\)", PAGE) and [i for i in set(re.findall(r"\$\('([a-z]+)'\)", PAGE)) if 'id="%s"' % i not in PAGE], [])
        st, _, _ = self.http("GET", "/", headers={"Cookie": self.cookie()})
        self.assertEqual(st, 200)


class Report(Base):
    def test_a_normal_exchange_shows_up_with_question_answer_and_tokens(self):
        rid, out = self.ask("How do I deploy?")
        self.host.audit.write("usage", rid, "", "desk", {"input_tokens": 1200, "output_tokens": 300, "cost": 0.004})
        rep = usage_report(self.host)
        q = rep["recent"][0]
        self.assertEqual((q["id"], q["question"], q["answer"], q["state"], q["tokens"], q["agent"]), (rid, "How do I deploy?", "Run scripts/deploy.sh.", "answered", 1500, "desk"))
        self.assertEqual((rep["totals"]["today_requests"], rep["totals"]["month_tokens"], rep["totals"]["month_cost"]), (1, 1500, 0.004))
        self.assertEqual((rep["status"]["paused"], rep["status"]["paired"], rep["status"]["policy_ok"], rep["status"]["mode"]), (False, True, True, "api"))
        self.assertEqual(rep["status"]["agents"], [{"alias": "desk", "backend": "claude", "tasks": False}])

    def test_refused_and_held_and_declined_are_told_apart(self):
        rid, out = self.ask("tampered", text_hash="0" * 64)
        self.assertEqual(out["reason"], "text_hash")
        self.rt.answer = "OUT_OF_SCOPE"; rid2, _ = self.ask("tell me a joke")
        self.rt.answer = "the key is sk-ant-api03-abcdefghijklmnopqrstuv"; rid3, _ = self.ask("show the key")
        states = {q["id"]: q["state"] for q in usage_report(self.host)["recent"]}
        self.assertEqual(states[rid], "refused: text_hash"); self.assertTrue(states[rid2].startswith("declined")); self.assertEqual(states[rid3], "held for your review")
        t = usage_report(self.host)["totals"]
        self.assertEqual(t["today_requests"], 2)                                                  # a refused request is not usage

    def test_newest_first_capped_and_running_requests_marked(self):
        ids = [self.ask("q%d" % i)[0] for i in range(3)]
        self.assertEqual([q["id"] for q in usage_report(self.host)["recent"]], ids[::-1])
        self.host._running["01RUNNING0000000000000000A"] = {"name": "x", "cancel_reason": None}
        self.host.audit.write("recheck", "01RUNNING0000000000000000A", "", "desk", {"ok": True})
        rep = usage_report(self.host)
        self.assertEqual(rep["status"]["running"], 1); self.assertEqual(rep["recent"][0]["state"], "running now")
        self.host._running.clear()

    def test_pausing_from_the_screen_stops_new_work(self):
        self.http("POST", "/api/pause", '{"paused":true}', {"Cookie": self.cookie(), "X-Door-Local": "1"})
        self.assertEqual(self.ask()[1]["reason"], "paused")
        self.assertTrue(usage_report(self.host)["status"]["paused"])

    def test_the_report_survives_a_broken_policy_file(self):
        self.path.write_text("{ broken"); time.sleep(0.01); self.host.holder.refresh()
        st = usage_report(self.host)["status"]
        self.assertFalse(st["policy_ok"]); self.assertIn("agents", [a for a in ("agents",)] if st["agents"] else [])


if __name__ == "__main__":
    unittest.main()


class SettingsPage(Base):
    def post(self, path, body, ck, local=True):
        h = {"Cookie": ck, "Content-Type": "application/json"}
        if local: h["X-Door-Local"] = "1"
        st, _, b = self.http("POST", path, json.dumps(body), h); return st, json.loads(b or b"{}")

    def test_read_change_refuse_and_the_daemon_picks_it_up(self):
        ck = self.cookie()
        self.assertEqual(self.http("GET", "/api/settings")[0], 401)                                     # never without the secret link
        st, _, b = self.http("GET", "/api/settings", headers={"Cookie": ck}); v = json.loads(b)
        self.assertEqual((st, [p["name"] for p in v["projects"]]), (200, ["p"]))
        self.assertEqual(self.post("/api/settings", {"op": "budget.set", "monthly": 12}, ck, local=False)[0], 403)   # needs the page's header
        st, out = self.post("/api/settings", {"op": "budget.set", "monthly": 12}, ck)
        self.assertEqual((st, out["budget"]), (200, 12.0))
        self.assertEqual(self.host.holder.policy["limits"]["monthly_budget"], 12.0)                     # live, without restarting
        st, out = self.post("/api/settings", {"op": "project.add", "path": str(self.root)}, ck)
        self.assertEqual(st, 400); self.assertIn("not a git repository", out["error"])
        self.assertTrue(any(e["event"] == "settings_changed" for e in self.host.audit.rows()))

    def test_restart_only_when_a_service_will_start_it_again(self):
        ck = self.cookie()
        os.environ.pop("DOOR_SUPERVISED", None)
        st, out = self.post("/api/restart", {}, ck)
        self.assertEqual(st, 400); self.assertIn("restart door-host yourself", out["message"])


class FolderPickerAndTerminal(Base):
    def get(self, path, ck): 
        st, _, b = self.http("GET", path, headers={"Cookie": ck}); return st, json.loads(b or b"{}")

    def post(self, path, body, ck):
        st, _, b = self.http("POST", path, json.dumps(body), {"Cookie": ck, "Content-Type": "application/json", "X-Door-Local": "1"}); return st, json.loads(b or b"{}")

    def test_the_folder_list_stays_in_the_home_folder_and_marks_git_projects(self):
        ck = self.cookie(); home = Path.home().resolve()
        self.assertEqual(self.http("GET", "/api/folders")[0], 401)
        st, d = self.get("/api/folders?path=" + str(home), ck)
        self.assertEqual((st, d["path"], d["parent"]), (200, str(home), None))
        self.assertFalse([x for x in d["dirs"] if x["name"].startswith(".") or x["name"] == "Library"])
        for outside in ("/", "/etc", "/private/var", str(home.parent)):
            st, d = self.get("/api/folders?path=" + outside, ck); self.assertEqual(d["path"], str(home), outside)      # never outside the home folder
        sub = self.root / "p"                                                      # a git project the tests made (under the temp dir, not home): refused too
        st, d = self.get("/api/folders?path=" + str(sub), ck); self.assertEqual(d["path"], str(home))

    def test_a_button_can_open_only_the_listed_terminal_actions(self):
        ck = self.cookie(); opened = []; self.ui.opener = lambda p: opened.append(p); self.ui.door_host = "/x/bin/door-host"
        st, out = self.post("/api/terminal", {"kind": "login:claude"}, ck)
        self.assertEqual(st, 200); script = Path(opened[0]).read_text()
        self.assertIn("/x/bin/door-host", script); self.assertIn("login claude", script); self.assertEqual(oct(Path(opened[0]).stat().st_mode & 0o777), "0o700")
        st, _ = self.post("/api/terminal", {"kind": "keychain:door-anthropic-api-key"}, ck)
        self.assertEqual(st, 200); self.assertIn("security add-generic-password", Path(opened[1]).read_text())
        for bad in ("rm -rf ~", "keychain:anything", "keychain:door-x; rm -rf ~", "login:claude; id", ""):
            st, out = self.post("/api/terminal", {"kind": bad}, ck); self.assertEqual(st, 400, bad)
        self.assertEqual(len(opened), 2)                                                # nothing else was ever opened
        self.assertEqual(self.http("POST", "/api/terminal", json.dumps({"kind": "login:claude"}), {"Cookie": ck, "Content-Type": "application/json"})[0], 403)   # needs the page's header
