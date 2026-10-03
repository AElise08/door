"""run.sh's boot block gives every cloud agent its two browsers, and re-running it never piles up.

It writes ~/.claude.json mcpServers (the release's headless browser, and the owner's Mac through
Plow Latch only while Plow hands out a relay URL) and one marker block in ~/.claude/CLAUDE.md.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = (ROOT / "cloud/run.sh").read_text()
BLOCK = re.search(r'python3 - "\$R/claude-settings.json" "\$R" "\$LATCH_URL" <<\'EOF\'\n(.*?)\nEOF\n', RUN, re.S).group(1)


class CloudTools(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.rel = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, ".claude"))
        for f in ("claude-settings.json", "cloud-tools.md"):
            (Path(self.rel) / f).write_text((ROOT / "cloud" / f).read_text())
        Path(self.home, ".claude/CLAUDE.md").write_text("owner's own notes\n")

    def boot(self, latch):
        env = dict(os.environ, HOME=self.home)
        subprocess.run([sys.executable, "-", os.path.join(self.rel, "claude-settings.json"), self.rel, latch],
                       input=BLOCK, text=True, env=env, check=True)
        return (json.load(open(os.path.join(self.home, ".claude.json"))).get("mcpServers", {}),
                Path(self.home, ".claude/CLAUDE.md").read_text())

    def test_latch_follows_plow_and_the_note_appears_once(self):
        url = "https://plow-x.int.exe.xyz/v1/relay/devices/owner/mcp"
        servers, md = self.boot(url)
        self.assertEqual(servers["plow-latch"], {"type": "http", "url": url})
        servers, md = self.boot(url)
        self.assertEqual(md.count("<!-- myplow-cloud-tools -->"), 1)
        self.assertIn("owner's own notes", md)
        servers, md = self.boot("")
        self.assertNotIn("plow-latch", servers)

    def test_browser_points_at_this_release_when_chromium_exists(self):
        servers, _ = self.boot("")
        if not Path("/ms-playwright").exists():
            self.assertNotIn("browser", servers)
            return
        self.assertTrue(servers["browser"]["command"].startswith(self.rel))


if __name__ == "__main__":
    unittest.main()
