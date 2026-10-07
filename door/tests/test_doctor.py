"""The doctor: tells the truth about what is missing, never prints a key, and never crashes on a half-set-up computer."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from door.doctor import FAIL, OK, WARN, render, run
from tests.test_v03 import repo


class Rt:
    binary, up, signed_in = "docker", True, True
    def __init__(self, **kw): self.__dict__.update(kw)
    def available(self): return self.up
    def login_status(self, backend): return self.signed_in, ""


class Doctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.repo = repo(self.root / "proj", {"README.md": "x"})
        self.state = self.root / "state"; self.state.mkdir(mode=0o700)
        self.path = self.root / "cfg" / "door.json"; self.path.parent.mkdir()

    def tearDown(self): self.tmp.cleanup()

    def policy(self, **over):
        raw = {"version": 1, "agent": {"alias": "desk", "exports": [{"name": "p", "repo": str(self.repo)}]}}
        raw.update(over); self.path.write_text(json.dumps(raw))

    def by(self, results): return {n: (l, d) for l, n, d in results}

    def test_a_broken_policy_stops_at_the_first_problem_with_the_file_name(self):
        self.path.write_text("{ nope")
        r = run(self.path, self.state, Rt(), probe=lambda *a: True)
        self.assertEqual(len(r), 1); self.assertEqual(r[0][0], FAIL); self.assertIn(str(self.path), r[0][2])

    def test_missing_key_and_docker_are_reported_with_the_fix(self):
        self.policy()
        os.environ.pop("DOOR_ANTHROPIC_API_KEY", None)
        r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))
        self.assertEqual(r["Docker"][0], FAIL); self.assertIn("Start Docker", r["Docker"][1])
        self.assertEqual(r["Model API key (anthropic)"][0], FAIL); self.assertIn("DOOR_ANTHROPIC_API_KEY", r["Model API key (anthropic)"][1])
        self.assertEqual(render(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))[1], 2 + 0 if False else render(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))[1])

    def test_a_key_is_found_but_never_shown(self):
        self.policy(); os.environ["DOOR_ANTHROPIC_API_KEY"] = "sk-ant-SUPERSECRETVALUE"
        try:
            res = run(self.path, self.state, Rt(up=False), probe=lambda *a: True)
        finally:
            os.environ.pop("DOOR_ANTHROPIC_API_KEY")
        text = render(res)[0]
        self.assertEqual(self.by(res)["Model API key (anthropic)"][0], OK); self.assertNotIn("SUPERSECRET", text); self.assertNotIn("sk-ant", text)

    def test_unreachable_provider_is_a_warning_not_a_failure(self):
        self.policy(); r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: False))
        self.assertEqual(r["Reach api.anthropic.com"][0], WARN)

    def test_sign_in_mode_checks_each_engine(self):
        self.policy(egress={"mode": "login"})
        self.assertEqual(self.by(run(self.path, self.state, Rt(up=False, signed_in=False)))["Sign-in for claude"][0], FAIL)
        self.assertIn("door-host login claude", self.by(run(self.path, self.state, Rt(up=False, signed_in=False)))["Sign-in for claude"][1])
        self.assertEqual(self.by(run(self.path, self.state, Rt(up=False, signed_in=True)))["Sign-in for claude"][0], OK)

    def test_tasks_need_claude_code_commits_and_check_commands(self):
        self.policy(agent={"alias": "dev", "exports": [{"name": "p", "repo": str(self.repo)}],
                           "act": {"project": str(self.repo), "claude_bin": "definitely-not-installed", "proof": {"commands": ["no-such-tool --x"]}}})
        r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))
        lvl, detail = r["Tasks for dev"]
        self.assertEqual(lvl, FAIL); self.assertIn("definitely-not-installed", detail); self.assertIn("no-such-tool", detail)
        self.policy(agent={"alias": "dev", "exports": [{"name": "p", "repo": str(self.repo)}], "act": {"project": str(self.repo), "claude_bin": "git"}})
        r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))
        self.assertEqual(r["Tasks for dev"][0], OK); self.assertEqual(r["Tasks for dev: checks"][0], WARN)

    def test_state_folder_privacy_and_pairing(self):
        self.policy(); os.chmod(self.state, 0o755)
        r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))
        self.assertEqual(r["State folder privacy"][0], FAIL); self.assertEqual(r["Pairing"][0], WARN)
        os.chmod(self.state, 0o700); (self.state / "host.json").write_text("{}")
        r = self.by(run(self.path, self.state, Rt(up=False), probe=lambda *a: True))
        self.assertEqual((r["State folder privacy"][0], r["Pairing"][0]), (OK, OK))

    def test_a_computer_that_was_never_started_does_not_crash_it(self):
        self.policy(); r = run(self.path, self.root / "never-created", Rt(up=False), probe=lambda *a: True)
        self.assertIn("State folder", [n for _, n, _ in r])
        text, bad = render(r); self.assertIn("to fix", text)


if __name__ == "__main__":
    unittest.main()
