"""Door's work builds up on one branch, door/work: a file one task created is there for the next task (the confusing case in the first real
group: a friend's task created notes.md, the owner's next task could not find it)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from door import act
from door.sandbox import build_prompt, build_task_prompt
from tests.test_v03 import repo


def git(cwd, *a): return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()


class WorkBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.repo = repo(self.root / "p", {"README.md": "hi\n"})

    def tearDown(self): self.tmp.cleanup()

    def task_branch(self, name, files, start="HEAD"):
        wt = self.root / ("wt-" + name.replace("/", "-"))
        git(self.repo, "worktree", "add", "-q", "-b", name, str(wt), start)
        for f, body in files.items(): (wt / f).write_text(body)
        git(wt, "add", "-A"); git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
        git(self.repo, "worktree", "remove", "--force", str(wt))

    def test_a_finished_task_joins_door_work_and_the_next_task_starts_there(self):
        self.task_branch("door/t1", {"notes.md": "# Notes\n"})
        self.assertTrue(act.advance_work_branch(self.repo, "door/t1"))
        self.assertEqual(git(self.repo, "rev-parse", act.WORK_BRANCH), git(self.repo, "rev-parse", "door/t1"))
        runner = act.ActRunner("01ARZ3NDEKTSV4RRFFQ69G5FAZ", {"project": str(self.repo), "bash": "off"}, self.root / "state", claude_bin="true")
        out = runner.run("x", "next task")
        self.assertEqual(out["based_on"], act.WORK_BRANCH)                         # the next task saw notes.md
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "main") if "main" in git(self.repo, "branch") else git(self.repo, "rev-parse", "HEAD"))
        self.assertFalse((self.repo / "notes.md").exists())                        # the owner's real folder is untouched

    def test_it_only_ever_moves_forward(self):
        self.task_branch("door/t1", {"a.md": "a"}); act.advance_work_branch(self.repo, "door/t1")
        self.task_branch("door/t2", {"b.md": "b"}, start=act.WORK_BRANCH)
        self.assertTrue(act.advance_work_branch(self.repo, "door/t2"))
        self.task_branch("door/old", {"c.md": "c"}, start="HEAD")                # started before t1/t2 joined: not a fast-forward
        self.assertFalse(act.advance_work_branch(self.repo, "door/old"))
        self.assertEqual(git(self.repo, "rev-parse", act.WORK_BRANCH), git(self.repo, "rev-parse", "door/t2"))

    def test_without_door_work_a_task_starts_from_the_project(self):
        runner = act.ActRunner("01ARZ3NDEKTSV4RRFFQ69G5FAZ", {"project": str(self.repo), "bash": "off"}, self.root / "state", claude_bin="true")
        self.assertEqual(runner.run("x", "first task")["based_on"], "HEAD")

    def test_what_joins_and_what_does_not(self):
        self.assertEqual(act.KEEP_VERDICTS, {"verified", "checks_passed", "unverified", "opened"})   # failed checks and incomplete work stay out

    def test_the_agent_is_told_to_answer_in_the_request_language(self):
        for p in (build_prompt("", "como funciona o login?"), build_task_prompt("", "open notes.md on my screen")):
            self.assertIn("Always reply in the language", p)
        self.assertIn("already holds the earlier Door tasks", build_task_prompt("", "x"))


if __name__ == "__main__":
    unittest.main()
