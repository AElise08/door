"""The pages the panel serves must be valid JavaScript. (A duplicate `let` once blanked the whole dashboard and no Swift test noticed.)"""
import os, re, shutil, socket, subprocess, tempfile, time, unittest, urllib.parse, urllib.request, http.cookiejar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "panel" / ".build" / "debug" / "door-panel"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@unittest.skipUnless(BINARY.exists() and shutil.which("node"), "needs the built panel and node")
class PagesAreValidJs(unittest.TestCase):
    def test_every_inline_script_parses_and_csp_allows_the_layout(self):
        port, tok = free_port(), "o" * 32
        proc = subprocess.Popen([str(BINARY)], env=dict(os.environ, DOOR_PANEL_OWNER_TOKEN=tok, DOOR_PANEL_AGENT_TOKEN="a" * 32, DOOR_PANEL_PORT=str(port)),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try: socket.create_connection(("127.0.0.1", port), 0.2).close(); break
                except OSError: time.sleep(0.1)
            class NoRedir(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k): return None
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedir)
            try: op.open(urllib.request.Request("http://127.0.0.1:%d/login" % port, urllib.parse.urlencode({"token": tok}).encode()))
            except urllib.error.HTTPError: pass
            r = op.open("http://127.0.0.1:%d/" % port); html = r.read().decode(); csp = r.headers["Content-Security-Policy"]
            self.assertIn("style-src-attr 'unsafe-inline'", csp)         # the page lays itself out with style="" attributes
            scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
            self.assertTrue(scripts, "no script found in the dashboard")
            for i, js in enumerate(scripts):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f: f.write(js)
                out = subprocess.run(["node", "--check", f.name], capture_output=True, text=True); os.unlink(f.name)
                self.assertEqual(out.returncode, 0, "script %d: %s" % (i, out.stderr[:400]))
        finally:
            proc.terminate(); proc.wait(5)



@unittest.skipUnless(shutil.which("node"), "needs node")
class LocalPageIsValidJs(unittest.TestCase):
    def test_the_local_page_script_parses(self):
        from door.local_ui import PAGE
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", PAGE, re.S)
        self.assertTrue(scripts)
        for js in scripts:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f: f.write(js)
            out = subprocess.run(["node", "--check", f.name], capture_output=True, text=True); os.unlink(f.name)
            self.assertEqual(out.returncode, 0, out.stderr[:400])


if __name__ == "__main__":
    unittest.main()
