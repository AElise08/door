"""Checking quoted evidence in answers (questions mode)."""
import tempfile
import unittest
from pathlib import Path

from door.verify import compose, split_sources, verify

ANSWER = """Run scripts/deploy.sh with DEPLOY_ENV set.

SOURCES:
- README.md | Deploys happen with scripts/deploy.sh, which needs the DEPLOY_ENV variable.
- scripts/deploy.sh | echo deploying to $DEPLOY_ENV
"""


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / "proj" / "scripts").mkdir(parents=True)
        (self.root / "proj" / "README.md").write_text("# Demo\n\nDeploys happen with   scripts/deploy.sh,\nwhich needs the DEPLOY_ENV variable.\n")
        (self.root / "proj" / "scripts" / "deploy.sh").write_text("#!/bin/sh\necho deploying to $DEPLOY_ENV\n")
        (self.root / "secret.txt").write_text("TOP SECRET VALUE 12345")

    def tearDown(self): self.tmp.cleanup()

    def test_split(self):
        body, src = split_sources(ANSWER)
        self.assertEqual(body, "Run scripts/deploy.sh with DEPLOY_ENV set.")
        self.assertEqual([p for p, _ in src], ["README.md", "scripts/deploy.sh"])
        self.assertEqual(split_sources("No block here.")[1], [])
        self.assertEqual(split_sources("A\n**Sources:**\n- a.md | some quote here")[1], [("a.md", "some quote here")])

    def test_real_quotes_pass_even_with_whitespace_differences(self):
        r = verify(split_sources(ANSWER)[1], self.root)
        self.assertEqual((r["checked"], r["verified"], r["failed"]), (2, 2, []))
        self.assertEqual(r["files"], ["README.md", "scripts/deploy.sh"])

    def test_invented_quotes_and_files_fail(self):
        r = verify([("README.md", "Deploys happen with a magic button"), ("missing.md", "anything at all here"),
                    ("scripts/deploy.sh", "x"), ("README.md", "y" * 300)], self.root)
        self.assertEqual(r["verified"], 0)
        self.assertEqual([f["why"] for f in r["failed"]], ["quote not found in that file", "file not found in the project",
                                                            "quote too short or too long", "quote too short or too long"])

    def test_paths_cannot_escape_the_project(self):
        for p in ("../secret.txt", "/etc/passwd", "~/.ssh/id_rsa", "proj/../../secret.txt", "..\\secret.txt", "a/../../secret.txt"):
            r = verify([(p, "TOP SECRET VALUE 12345")], self.root / "proj")
            self.assertEqual(r["verified"], 0, p)
        import os
        os.symlink(self.root / "secret.txt", self.root / "proj" / "link.txt")
        self.assertEqual(verify([("link.txt", "TOP SECRET VALUE 12345")], self.root / "proj")["verified"], 0)   # symlinks are never followed

    def test_the_export_folder_name_may_prefix_the_path(self):
        r = verify([("proj/README.md", "which needs the DEPLOY_ENV variable")], self.root)
        self.assertEqual(r["verified"], 1)

    def test_compose_modes(self):
        good = {"checked": 1, "verified": 1, "files": ["README.md"], "failed": []}
        none = {"checked": 0, "verified": 0, "files": [], "failed": []}
        part = {"checked": 2, "verified": 1, "files": ["README.md"], "failed": [{"path": "x", "why": "no"}]}
        self.assertEqual(compose("Answer.", good, "flag", True), ("Answer.\n\nChecked in: README.md", "verified"))
        self.assertIn("could not confirm", compose("Answer.", part, "flag", True)[0]); self.assertEqual(compose("Answer.", part, "flag", True)[1], "partly")
        self.assertEqual(compose("Answer.", none, "flag", False), ("Answer.\n\nI could not confirm this in the project files.", "unverified"))
        self.assertEqual(compose("Which environment?", none, "flag", False), ("Which environment?", "n/a"))        # a question needs no source
        self.assertEqual(compose("Answer.", none, "off", False), ("Answer.", "off"))
        t, s = compose("A made-up fact.", none, "require", False)
        self.assertEqual(s, "unverified"); self.assertNotIn("made-up", t)


if __name__ == "__main__":
    unittest.main()
