"""The installer's policy writer: every choice produces a file the daemon accepts, nothing secret is written, existing files are kept."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from door.policy import PolicyError, load
from door.setup import SetupError, build_policy, write_policy
from tests.test_v03 import repo


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.repo = repo(self.root / "my-app", {"README.md": "x"}); self.cfg = self.root / "cfg" / "door.json"; self.state = self.root / "st"; self.state.mkdir()

    def tearDown(self): self.tmp.cleanup()

    def accepted(self, **kw):
        pol = build_policy(self.repo, **kw); write_policy(self.cfg, pol, force=True); return load(self.cfg, self.state)

    def test_each_way_of_paying_for_the_model_gives_a_valid_policy(self):
        p = self.accepted(access="opencode"); self.assertEqual((p["agents"][0]["backend"], p["egress"]["provider"]), ("opencode", "opencode-go"))
        p = self.accepted(access="claude-login"); self.assertEqual(p["egress"]["mode"], "login")
        p = self.accepted(access="api-key"); self.assertEqual(p["egress"]["provider"], "anthropic")

    def test_tasks_are_off_unless_asked_and_point_at_the_same_project(self):
        self.assertIsNone(self.accepted()["agents"][0].get("act"))
        act = self.accepted(tasks=True)["agents"][0]["act"]; self.assertEqual(Path(act["project"]).resolve(), self.repo.resolve())

    def test_the_description_is_about_the_chosen_project_not_a_leftover(self):
        self.assertIn("my-app", build_policy(self.repo)["agent"]["description"])

    def test_file_is_private_holds_no_key_and_an_existing_one_is_kept(self):
        os.environ["OPENCODE_API_KEY"] = "sk-SHOULD-NEVER-APPEAR"
        try: self.accepted(access="opencode")
        finally: os.environ.pop("OPENCODE_API_KEY")
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600); self.assertNotIn("SHOULD-NEVER", self.cfg.read_text())
        self.cfg.write_text("{}"); self.assertFalse(write_policy(self.cfg, build_policy(self.repo))); self.assertEqual(self.cfg.read_text(), "{}")

    def test_bad_input_is_explained_not_written(self):
        for kw, word in (({"repo": self.root}, "not a git"), ({"repo": self.repo, "alias": "bad name!"}, "letters"), ({"repo": self.repo, "access": "x"}, "access")):
            with self.assertRaises(SetupError) as cm: build_policy(**{"repo": self.repo, **kw})
            self.assertIn(word, str(cm.exception))
        empty = self.root / "empty"; empty.mkdir(); subprocess.run(["git", "init", "-q", str(empty)], check=True)
        with self.assertRaises(SetupError) as cm: build_policy(empty)
        self.assertIn("no commits", str(cm.exception))

    def test_the_cli_command_works_and_fails_cleanly(self):
        from door.cli import host_main
        import io, contextlib
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = host_main(["--policy", str(self.cfg), "--state", str(self.state), "init", "--repo", str(self.repo), "--access", "opencode"])
        self.assertEqual(code, 0, err.getvalue()); self.assertIn("wrote", out.getvalue())
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = host_main(["--policy", str(self.cfg), "--state", str(self.state), "init", "--repo", str(self.root)])
        self.assertEqual(code, 1); self.assertIn("not a git repository", err.getvalue())


if __name__ == "__main__":
    unittest.main()
