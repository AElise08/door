"""Hostile and clumsy network traffic against the real panel: it must keep answering real users afterwards."""
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "panel" / ".build" / "debug" / "door-panel"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@unittest.skipUnless(BINARY.exists(), "build the panel first")
class Abuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ, DOOR_PANEL_OWNER_TOKEN="o" * 32, DOOR_PANEL_AGENT_TOKEN="a" * 32, DOOR_PANEL_PORT=str(cls.port))
        cls.proc = subprocess.Popen([str(BINARY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try: socket.create_connection(("127.0.0.1", cls.port), 0.2).close(); break
            except OSError: time.sleep(0.1)

    @classmethod
    def tearDownClass(cls): cls.proc.terminate(); cls.proc.wait(5)

    def alive(self):
        return urllib.request.urlopen("http://127.0.0.1:%d/healthz" % self.port, timeout=5).read() == b"ok"

    def raw(self, data, read=True, wait=0.0):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            try:
                s.sendall(data)
            except (BrokenPipeError, ConnectionResetError):          # the panel hung up early on something it refuses to read: correct
                return b""
            if wait: time.sleep(wait)
            if not read: return b""
            s.settimeout(3)
            try: return s.recv(65536)
            except (socket.timeout, ConnectionError): return b""
        finally:
            s.close()

    def status(self, resp): return int(resp.split(b" ", 2)[1]) if resp.startswith(b"HTTP/") else 0

    def test_malformed_requests_get_an_error_not_a_crash(self):
        cases = {
            "garbage": b"\x00\xff\xfe\x01binary junk\r\n\r\n", "no version": b"GET /\r\n\r\n", "bad version": b"GET / SPDY/9\r\n\r\n",
            "header without colon": b"GET / HTTP/1.1\r\nbroken header\r\n\r\n", "negative length": b"POST /login HTTP/1.1\r\nContent-Length: -5\r\n\r\n",
            "text length": b"POST /login HTTP/1.1\r\nContent-Length: abc\r\n\r\n", "chunked": b"POST /login HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
            "huge header": b"GET / HTTP/1.1\r\nX: " + b"a" * 40000 + b"\r\n\r\n", "huge length": b"POST /login HTTP/1.1\r\nContent-Length: 99999999999\r\n\r\n",
            "huge body": b"POST /login HTTP/1.1\r\nContent-Length: 3000000\r\n\r\n" + b"x" * 3000000,
        }
        for name, data in cases.items():
            code = self.status(self.raw(data))
            self.assertIn(code, (0, 400, 413), name)
            self.assertTrue(self.alive(), "panel died after: " + name)

    def test_odd_paths_never_serve_anything_private(self):
        for path in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/c/..%2f..%2fetc%2fpasswd", "/chat//messages", "/admin", "/admin/", "/admin/tenants",
                     "/api/state", "/agent/commands", "/static/../x", "/\x00", "/" + "a" * 5000, "/signin/", "/c/", "/chat/", "/chat/x/y/z/w"):
            code = self.status(self.raw(("GET %s HTTP/1.1\r\nHost: x\r\n\r\n" % path).encode("latin-1", "replace")))
            self.assertIn(code, (0, 400, 401, 403, 404, 429), path)
        self.assertTrue(self.alive())

    def test_connections_that_stall_or_vanish_do_not_hold_the_panel_hostage(self):
        for _ in range(60):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=2); s.sendall(b"GET /heal")      # half a request, then gone
            s.close()
        socks = [socket.create_connection(("127.0.0.1", self.port), timeout=2) for _ in range(300)]          # many idle connections
        t0 = time.time()
        self.assertTrue(self.alive()); self.assertLess(time.time() - t0, 3)                                     # a real user is still served at once
        for s in socks: s.close()

    def test_parallel_real_requests(self):
        results = []
        def hit():
            try: results.append(self.alive())
            except Exception as e: results.append(e)
        ts = [threading.Thread(target=hit) for _ in range(80)]
        [t.start() for t in ts]; [t.join(15) for t in ts]
        self.assertEqual(results.count(True), 80)

    def test_login_guessing_is_throttled_and_the_page_still_loads(self):
        codes = []
        for i in range(8):
            r = self.raw(("POST /login HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: 12\r\n\r\ntoken=guess%02d" % i).encode())
            codes.append(self.status(r))
        self.assertEqual(codes[:5], [401] * 5); self.assertEqual(set(codes[5:]), {429})
        self.assertTrue(self.alive())

    def test_methods_and_oversized_json_to_the_agent_api(self):
        for method in ("DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT"):
            self.assertIn(self.status(self.raw(("%s /api/state HTTP/1.1\r\nHost: x\r\n\r\n" % method).encode())), (0, 400, 401, 403, 404, 405))
        big = b'{"a":"' + b"x" * 1_500_000 + b'"}'
        self.assertIn(self.status(self.raw(b"PUT /agent/snapshot HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + b"a" * 32 +
                                           b"\r\nContent-Length: %d\r\n\r\n" % len(big) + big)), (0, 413))
        self.assertTrue(self.alive())


if __name__ == "__main__":
    unittest.main()
