"""Door Merge: the owner sees what Door's work would bring into the project, says YES, and only then it is merged, and only if that is safe."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from door import act
from door.common import ulid
from door.door_link import to_cloud_command, to_panel_snapshot
from door.service import cycle, panel_command
from tests.test_act_cloud import SUMMARY, Base as CloudBase
from tests.test_v03 import repo

OWNER, THREAD = "+15550000001", "ot"


def git(cwd, *a): return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()


class OnTheMac(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.repo = repo(self.root / "p", {"README.md": "hello\n"})
        self.main = git(self.repo, "symbolic-ref", "--short", "HEAD")

    def tearDown(self): self.tmp.cleanup()

    def door_task(self, files, name):
        start = act.WORK_BRANCH if subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", "refs/heads/door/work"], capture_output=True).returncode == 0 else "HEAD"
        wt = self.root / ("wt-" + name)
        git(self.repo, "worktree", "add", "-q", "-b", "door/" + name, str(wt), start)
        for f, b in files.items(): (wt / f).write_text(b)
        git(wt, "add", "-A"); git(wt, "-c", "user.name=Door", "-c", "user.email=d@d", "commit", "-qm", "door: " + name)
        git(self.repo, "worktree", "remove", "--force", str(wt)); act.advance_work_branch(self.repo, "door/" + name)

    def test_what_would_be_merged_is_listed_and_a_clean_merge_works(self):
        self.door_task({"notes.md": "# Notes\n"}, "notes"); self.door_task({"Door.md": "# Door\n"}, "doc")
        w = act.work_status(self.repo)
        self.assertEqual((w["count"], w["commits"], sorted(w["files"]), w["target"], w["can_merge"]), (2, ["doc", "notes"], ["Door.md", "notes.md"], self.main, True))
        out = act.merge_work(self.repo, w["head"], w["target"])
        self.assertEqual((out["merged"], out["count"]), (True, 2)); self.assertTrue((self.repo / "notes.md").exists())
        self.assertEqual(act.work_status(self.repo)["count"], 0)                                 # nothing left to merge

    def test_the_project_moved_on_but_without_overlap_a_merge_commit_is_made(self):
        self.door_task({"notes.md": "n"}, "notes")
        (self.repo / "other.md").write_text("mine"); git(self.repo, "add", "-A"); git(self.repo, "-c", "user.name=me", "-c", "user.email=m@m", "commit", "-qm", "mine")
        w = act.work_status(self.repo); self.assertTrue(w["can_merge"]); self.assertFalse(w["fast_forward"])
        self.assertTrue(act.merge_work(self.repo, w["head"], w["target"])["merged"])
        self.assertTrue((self.repo / "notes.md").exists() and (self.repo / "other.md").exists())

    def test_a_conflict_is_refused_and_nothing_changes(self):
        self.door_task({"README.md": "door's version\n"}, "readme")
        (self.repo / "README.md").write_text("my version\n"); git(self.repo, "-c", "user.name=me", "-c", "user.email=m@m", "commit", "-qam", "mine")
        before = git(self.repo, "rev-parse", "HEAD")
        w = act.work_status(self.repo); self.assertFalse(w["can_merge"]); self.assertIn("same lines", w["reason"])
        self.assertFalse(act.merge_work(self.repo, w["head"], w["target"])["merged"])
        self.assertEqual((git(self.repo, "rev-parse", "HEAD"), (self.repo / "README.md").read_text()), (before, "my version\n"))

    def test_uncommitted_changes_or_clashing_untracked_files_stop_it(self):
        self.door_task({"notes.md": "n"}, "notes")
        (self.repo / "README.md").write_text("half-done edit\n")
        self.assertIn("not committed", act.work_status(self.repo)["reason"])
        git(self.repo, "checkout", "--", "README.md"); (self.repo / "notes.md").write_text("my own untracked notes")
        w = act.work_status(self.repo); self.assertFalse(w["can_merge"]); self.assertIn("notes.md", w["reason"])
        self.assertEqual((self.repo / "notes.md").read_text(), "my own untracked notes")

    def test_it_merges_only_what_the_owner_was_shown(self):
        self.door_task({"a.md": "a"}, "a"); shown = act.work_status(self.repo)
        self.door_task({"b.md": "b"}, "b")                                                      # more work arrived after the owner was asked
        out = act.merge_work(self.repo, shown["head"], shown["target"])
        self.assertFalse(out["merged"]); self.assertIn("changed after you were asked", out["reason"])
        self.assertFalse((self.repo / "a.md").exists())
        self.assertFalse(act.merge_work(self.repo, act.work_status(self.repo)["head"], "some-other-branch")["merged"])

    def test_nothing_to_merge(self):
        self.assertFalse(act.work_status(self.repo)["exists"])
        self.door_task({"a.md": "a"}, "a"); w = act.work_status(self.repo); act.merge_work(self.repo, w["head"], w["target"])
        self.assertIn("already in", act.work_status(self.repo)["reason"])


class InTheCloud(CloudBase):
    W = {"exists": True, "target": "main", "head": "abc123", "count": 2, "commits": ["create notes.md", "write Door.md"], "files": ["notes.md", "Door.md"], "can_merge": True}

    def owner(self, text): return self.c.receive(ulid(), OWNER, THREAD, text)
    def sent(self): return [o["text"] for o in self.c.s["outbox"].values() if o["thread"] == THREAD]      # pending or already sent by a cycle
    def cmds(self, op): return [v for v in self.c.s["commands"].values() if v["op"] == op]

    def test_door_merge_shows_what_and_waits_for_yes(self):
        self.owner("Door Merge"); self.assertEqual(len(self.cmds("work")), 1)
        self.c.merge_preview(self.W)
        ask = self.texts(THREAD)[-1]; code = ask.split("YES ")[1][:4]
        self.assertIn("merge Door's work into main? 2 change(s): create notes.md; write Door.md. Files: notes.md, Door.md", ask)
        self.assertEqual(self.cmds("merge"), [])
        self.owner("YES " + code)
        (m,) = self.cmds("merge"); self.assertEqual((m["head"], m["target"]), ("abc123", "main"))
        self.c.merge_done({"merged": True, "count": 2, "target": "main", "files": ["notes.md", "Door.md"]})
        self.assertIn("done, merged 2 change(s) into main", self.texts(THREAD)[-1])

    def test_no_wrong_codes_expiry_and_guests_change_nothing(self):
        self.c.merge_preview(self.W); code = self.texts(THREAD)[-1].split("YES ")[1][:4]
        self.say("+15551110001", "YES " + code); self.assertEqual(self.cmds("merge"), [])
        self.owner("NO " + code); self.assertEqual(self.cmds("merge"), []); self.assertIn("nothing was merged", self.texts(THREAD)[-1])
        self.c.merge_preview(self.W); code = self.texts(THREAD)[-1].split("YES ")[1][:4]
        self.t += 601; self.owner("YES " + code); self.assertEqual(self.cmds("merge"), []); self.assertIn("expired", self.texts(THREAD)[-1])

    def test_when_it_cannot_be_merged_the_owner_hears_why(self):
        self.c.merge_preview(dict(self.W, can_merge=False, reason="Your project folder has changes that are not committed."))
        self.assertIn("not committed", self.texts(THREAD)[-1]); self.assertIsNone(self.c.s.get("merge_pending"))
        self.c.s["owner_lang"] = "pt"; self.c.merge_done({"merged": False, "reason": "git could not merge it"})
        self.assertIn("não juntei nada", self.texts(THREAD)[-1])

    def test_the_panel_button_and_the_mac_round_trip(self):
        cmd = to_cloud_command({"id": "c1", "type": "merge"}); self.assertEqual(cmd["op"], "merge.request")
        panel_command(self.c, dict(cmd, request_id=None)); self.assertEqual(len(self.cmds("work")), 1)
        class Relay:
            def __init__(s): s.argv = []
            def command(s, argv):
                s.argv.append(argv)
                if "summary" in argv: return {"ok": True, "summary": dict(SUMMARY, work=InTheCloud.W)}
                if "work" in argv: return {"ok": True, "work": InTheCloud.W}
                return {"ok": True, "merged": True, "count": 2, "target": "main", "files": ["notes.md"]}
            def ask(s, *a): return {"ok": True}
            def status(s, rid): return {"ok": True}
        class Hub:
            def rpc(self, *a): return {}
        class S:
            def messages(self, *a): return iter(())
            def send(self, *a): pass
        self.c.s["host_id"] = "h"; self.c.s["started_at"] = self.t; relay = Relay()
        cycle(self.c, S(), relay, Hub(), None)
        code = self.sent()[-1].split("YES ")[1][:4]; self.owner("YES " + code)
        cycle(self.c, S(), relay, Hub(), None)
        merge_argv = next(a for a in relay.argv if "merge" in a)
        self.assertEqual(merge_argv[merge_argv.index("--head") + 1], "abc123")
        self.assertIn("done, merged", self.sent()[-1])
        snap = to_panel_snapshot(self.c.snapshot()); self.assertEqual(snap["merge_result"]["state"], "merged"); self.assertEqual(snap["work"]["count"], 2)
