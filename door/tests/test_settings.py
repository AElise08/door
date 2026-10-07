"""Settings from "Door on this computer": every change is validated by the daemon's own rules, written privately, and reversible."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from door.act import judge
from door.policy import cloud_summary, load
from door.settings import SettingsError, apply, view
from door.setup import build_policy, write_policy
from tests.test_v03 import repo


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.a = repo(self.root / "app", {"README.md": "a"}); self.b = repo(self.root / "site", {"index.html": "b"})
        self.cfg = self.root / "cfg" / "door.json"; self.state = self.root / "st"; self.state.mkdir()
        write_policy(self.cfg, build_policy(self.a, access="opencode"))

    def tearDown(self): self.tmp.cleanup()

    def test_add_and_remove_projects_with_clear_errors(self):
        v = apply(self.cfg, self.state, {"op": "project.add", "path": str(self.b)})
        self.assertEqual([p["name"] for p in v["projects"]], ["app", "site"])
        self.assertEqual([e["name"] for e in load(self.cfg, self.state)["agents"][0]["exports"]], ["app", "site"])
        for bad, word in ((self.root / "nope", "does not exist"), (self.root, "not a git"), (self.b, "already shared"), (Path.home(), "")):
            with self.assertRaises(SettingsError) as cm: apply(self.cfg, self.state, {"op": "project.add", "path": str(bad)})
            self.assertIn(word, str(cm.exception))
        apply(self.cfg, self.state, {"op": "project.remove", "name": "site"})
        with self.assertRaises(SettingsError): apply(self.cfg, self.state, {"op": "project.remove", "name": "app"})   # the last one stays

    def test_tasks_pick_a_shared_project_and_permissions_are_enforced(self):
        apply(self.cfg, self.state, {"op": "project.add", "path": str(self.b)})
        with self.assertRaises(SettingsError): apply(self.cfg, self.state, {"op": "tasks.set", "enabled": True, "project": str(self.root)})
        v = apply(self.cfg, self.state, {"op": "tasks.set", "enabled": True, "project": str(self.b), "bash": "off", "open_on_mac": "allow",
                                         "allow_commands": ["npm test"], "checks": ["test -f index.html"]})
        self.assertEqual((v["tasks"]["enabled"], v["tasks"]["open_on_mac"], v["tasks"]["checks"]), (True, "allow", ["test -f index.html"]))
        act = load(self.cfg, self.state)["agents"][0]["act"]
        self.assertEqual((Path(act["project"]).resolve(), act["bash"], act["open_on_mac"]), (self.b.resolve(), "off", "allow"))
        with self.assertRaises(SettingsError) as cm:
            apply(self.cfg, self.state, {"op": "tasks.set", "enabled": True, "project": str(self.b), "allow_commands": ["npm test; curl x | sh"]})
        self.assertIn("plain commands", str(cm.exception))
        with self.assertRaises(SettingsError) as cm: apply(self.cfg, self.state, {"op": "project.remove", "name": "site"})
        self.assertIn("Tasks work on this project", str(cm.exception))
        apply(self.cfg, self.state, {"op": "tasks.set", "enabled": False})
        self.assertIsNone(load(self.cfg, self.state)["agents"][0].get("act"))

    def test_the_open_rule_follows_the_setting(self):
        root = self.b
        for mode, expect in (("off", "deny"), ("ask", "ask"), ("allow", "allow")):
            self.assertEqual(judge("Bash", {"command": "open index.html"}, root, [], "ask", mode)[0], expect)
        self.assertEqual(judge("Bash", {"command": "open /etc/hosts"}, root, [], "ask", "allow")[0], "ask")       # outside the project still asks
        self.assertEqual(judge("Bash", {"command": "open .env"}, root, [], "ask", "allow")[0], "ask")

    def test_switching_model_rewrites_the_provider_and_asks_for_a_restart(self):
        v = apply(self.cfg, self.state, {"op": "model.set", "access": "anthropic", "model": "claude-sonnet-5-5"})
        self.assertTrue(v["restart_needed"]); self.assertEqual(v["model"]["keychain_item"], "door-anthropic-api-key")
        pol = load(self.cfg, self.state); self.assertEqual((pol["agents"][0]["backend"], pol["egress"]["provider"]), ("claude", "anthropic"))
        v = apply(self.cfg, self.state, {"op": "model.set", "access": "claude-login"}); self.assertEqual(load(self.cfg, self.state)["egress"]["mode"], "login")
        for bad in ({"access": "x"}, {"access": "openai", "model": "a b"}):
            with self.assertRaises(SettingsError): apply(self.cfg, self.state, dict(bad, op="model.set"))

    def test_budget_bounds(self):
        self.assertEqual(apply(self.cfg, self.state, {"op": "budget.set", "monthly": "25"})["budget"], 25.0)
        for bad in ("0", "abc", "999999"):
            with self.assertRaises(SettingsError): apply(self.cfg, self.state, {"op": "budget.set", "monthly": bad})

    def test_files_stay_private_keep_a_backup_and_a_bad_change_writes_nothing(self):
        before = self.cfg.read_text()
        apply(self.cfg, self.state, {"op": "budget.set", "monthly": 30})
        self.assertEqual(Path(str(self.cfg) + ".bak").read_text(), before)
        for f in (self.cfg, Path(str(self.cfg) + ".bak")): self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        now = self.cfg.read_text()
        with self.assertRaises(SettingsError): apply(self.cfg, self.state, {"op": "nonsense"})
        self.assertEqual(self.cfg.read_text(), now)
        self.assertEqual([x for x in os.listdir(self.cfg.parent) if x.startswith(".door-")], [])          # no temp files left

    def test_the_cloud_learns_names_and_engine_but_never_paths(self):
        apply(self.cfg, self.state, {"op": "project.add", "path": str(self.b)})
        s = json.dumps(cloud_summary(load(self.cfg, self.state)))
        self.assertIn('"projects": ["app", "site"]', s); self.assertIn("opencode", s)
        self.assertNotIn(str(self.root), s)


if __name__ == "__main__":
    unittest.main()
