"""Providers, engines (claude / opencode / codex), the OpenAI-format proxy and credential loading."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from door.credentials import load_credential
from door.policy import PolicyError, validate
from door.proxy import Ctx, EgressProxy
from door.sandbox import ContainerRuntime, opencode_config

PRICING = {"input_per_mtok": 0.15, "output_per_mtok": 0.6}


def policy(tmp, **over):
    repo = Path(tmp) / "repo"; repo.mkdir(exist_ok=True)
    raw = {"version": 1, "agent": {"alias": "desk", "exports": [{"name": "r", "repo": str(repo)}]}}
    raw.update(over)
    return validate(raw, Path(tmp) / "cfg" / "p.json", Path(tmp) / "state")


class Providers(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name
    def tearDown(self): self.tmp.cleanup()

    def test_default_is_anthropic_with_claude(self):
        p = policy(self.d)
        self.assertEqual((p["egress"]["provider"], p["egress"]["style"], p["egress"]["allow_hosts"]), ("anthropic", "anthropic", ["api.anthropic.com"]))
        self.assertEqual(p["agent"]["backend"], "claude")

    def test_opencode_go_with_opencode_backend(self):
        p = policy(self.d, agent={"alias": "desk", "backend": "opencode", "model": "deepseek-v4.1-flash",
                                  "exports": [{"name": "r", "repo": str(Path(self.d) / "repo")}]},
                   egress={"provider": "opencode-go", "pricing": PRICING})
        e = p["egress"]
        self.assertEqual((e["style"], e["allow_hosts"], e["path_prefix"], e["credential_env"]), ("openai", ["opencode.ai"], "/zen/go", "OPENCODE_API_KEY"))
        self.assertEqual(p["boss"]["backend"], "opencode")

    def test_codex_needs_an_openai_style_provider(self):
        agent = {"alias": "desk", "backend": "codex", "model": "gpt-5", "exports": [{"name": "r", "repo": str(Path(self.d) / "repo")}]}
        policy(self.d, agent=agent, egress={"provider": "openai", "pricing": {"input_per_mtok": 1, "output_per_mtok": 4}})
        with self.assertRaises(PolicyError): policy(self.d, agent=agent)                                    # anthropic format: mismatch

    def test_mismatches_and_missing_prices_fail_closed(self):
        oc = {"alias": "desk", "backend": "opencode", "model": "m", "exports": [{"name": "r", "repo": str(Path(self.d) / "repo")}]}
        with self.assertRaises(PolicyError): policy(self.d, agent=oc)                                       # opencode on anthropic
        with self.assertRaises(PolicyError): policy(self.d, agent=oc, egress={"provider": "opencode-go"})   # no pricing: cost cannot be guessed
        with self.assertRaises(PolicyError): policy(self.d, egress={"provider": "nope", "pricing": PRICING})
        with self.assertRaises(PolicyError): policy(self.d, agent=dict(oc, backend="grok"))
        with self.assertRaises(PolicyError): policy(self.d, egress={"allow_hosts": ["evil.example"]})        # the host comes from the provider
        with self.assertRaises(PolicyError): policy(self.d, egress={"credential_source": "keychain"})

    def test_custom_provider_must_be_a_public_https_host(self):
        agent = {"alias": "desk", "backend": "opencode", "model": "m", "exports": [{"name": "r", "repo": str(Path(self.d) / "repo")}]}
        ok = policy(self.d, agent=agent, egress={"provider": "custom", "base_url": "https://llm.example.com/api/v1", "style": "openai", "pricing": PRICING})
        self.assertEqual((ok["egress"]["allow_hosts"], ok["egress"]["path_prefix"]), (["llm.example.com"], "/api/v1"))
        for bad in ("http://llm.example.com", "https://127.0.0.1", "https://localhost", "https://10.0.0.5/v1", "https://u:p@llm.example.com",
                    "https://llm.example.com:8443", "https://llm.example.com/v1?x=1", "", "ftp://x.example.com"):
            with self.assertRaises(PolicyError, msg=bad):
                policy(self.d, agent=agent, egress={"provider": "custom", "base_url": bad, "style": "openai", "pricing": PRICING})


class Credentials(unittest.TestCase):
    def test_env_and_opencode_auth(self):
        with tempfile.TemporaryDirectory() as home:
            auth = Path(home) / ".local/share/opencode/auth.json"; auth.parent.mkdir(parents=True)
            auth.write_text(json.dumps({"opencode-go": {"type": "api", "key": "KEY-GO"}, "openai": {"type": "oauth", "access": "OAUTH-TOKEN"}}))
            old = os.environ.get("HOME"); os.environ["HOME"] = home
            try:
                self.assertEqual(load_credential({"provider": "opencode-go", "credential_source": "opencode-auth", "credential_env": "X"}), "KEY-GO")
                self.assertEqual(load_credential({"provider": "openai", "credential_source": "opencode-auth", "credential_env": "X"}), "")   # OAuth is never reused
                self.assertEqual(load_credential({"provider": "deepseek", "credential_source": "opencode-auth", "credential_env": "X"}), "")
                os.environ["DOOR_T_KEY"] = "FROM-ENV"
                self.assertEqual(load_credential({"provider": "x", "credential_env": "DOOR_T_KEY"}), "FROM-ENV")
            finally:
                os.environ.pop("DOOR_T_KEY", None)
                if old is None: os.environ.pop("HOME", None)
                else: os.environ["HOME"] = old


class EngineCommands(unittest.TestCase):
    base = {"name": "door-run-x", "export_dir": "/s/e", "outbox_dir": "/s/o", "placeholder_key": "door-PLACEHOLDER", "prompt": "Q",
            "model": "m", "cpus": 1, "memory_mb": 256}

    def cmd(self, **kw): return ContainerRuntime().build_command(dict(self.base, **kw))

    def test_opencode_config_is_locked_down(self):
        c = json.loads(opencode_config("m", "KEY"))
        perm = c["permission"]
        for tool in ("bash", "webfetch", "websearch", "task", "question", "skill", "todowrite", "lsp"):
            self.assertEqual(perm[tool], "deny", tool)
        self.assertEqual(perm["external_directory"]["*"], "deny"); self.assertEqual(perm["external_directory"]["/outbox/*"], "allow")
        self.assertEqual(perm["edit"]["*"], "deny"); self.assertEqual(perm["edit"]["/outbox/answer.md"], "allow")
        self.assertEqual(perm["read"]["*.env"], "deny")
        self.assertEqual((c["mcp"], c["plugin"], c["lsp"], c["share"], c["autoupdate"]), ({}, [], False, "disabled", False))
        self.assertEqual(c["enabled_providers"], ["door"]); self.assertEqual(c["model"], "door/m")
        self.assertEqual(c["provider"]["door"]["options"]["baseURL"], "http://door-relay:8080/v1")
        self.assertTrue(c["agent"]["title"]["disable"])
        boss = json.loads(opencode_config("m", "KEY", boss=True))["permission"]
        self.assertEqual((boss["read"], boss["glob"], boss["grep"], boss["list"]), ("deny",) * 4)       # the Boss cannot even read
        self.assertEqual(json.loads(opencode_config("m", "KEY", provider="opencode-go"))["model"], "opencode-go/m")

    def test_opencode_container_command(self):
        cmd = self.cmd(backend="opencode")
        self.assertIn("opencode", cmd); self.assertIn("--pure", cmd)
        j = " ".join(cmd)
        self.assertIn("OPENCODE_CONFIG_CONTENT=", j); self.assertNotIn("ANTHROPIC_API_KEY", j)
        self.assertNotIn("REAL", j); self.assertIn("--read-only", cmd); self.assertIn("door-internal", cmd)

    def test_codex_container_command(self):
        cmd = self.cmd(backend="codex")
        j = " ".join(cmd)
        for must in ("codex", "exec", "--ephemeral", "--ignore-user-config", "approval_policy=\"never\"", "sandbox_mode=\"read-only\"",
                     "wire_api=\"responses\"", "http://door-relay:8080/v1", "DOOR_API_KEY=door-PLACEHOLDER"):
            self.assertIn(must, j, must)
        self.assertNotIn("--dangerously-bypass", j); self.assertNotIn("ANTHROPIC", j)

    def test_claude_is_unchanged(self):
        cmd = self.cmd(backend="claude")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob,Write,Edit")
        self.assertIn("ANTHROPIC_API_KEY=door-PLACEHOLDER", cmd)


class FakeProvider:
    def __init__(self, stream=False, usage=True, responses=False):
        self.calls, self.stream, self.usage, self.responses = [], stream, usage, responses
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.calls.append({"path": self.path, "auth": self.headers.get("authorization"), "body": body,
                                 "oc": self.headers.get("x-opencode-session"), "xkey": self.headers.get("x-api-key")})
                u = ({"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 40}} if up.responses
                     else {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}})
                if up.stream:
                    if up.responses:
                        ev = ["data: " + json.dumps({"type": "response.output_text.delta", "delta": "hi"}),
                              "data: " + json.dumps({"type": "response.completed", "response": {"model": "m", "usage": u if up.usage else None}})]
                    else:
                        ev = ["data: " + json.dumps({"model": "m", "choices": [{"delta": {"content": "hi"}}]})]
                        if up.usage: ev.append("data: " + json.dumps({"model": "m", "choices": [], "usage": u}))
                        ev.append("data: [DONE]")
                    data = ("\n\n".join(ev) + "\n\n").encode()
                    self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers(); self.wfile.write(data)
                else:
                    data = json.dumps(dict({"model": "m", "choices": []}, **({"usage": u} if up.usage else {}))).encode()
                    self.send_response(200); self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = "127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self): self.httpd.shutdown(); self.httpd.server_close()


def post(port, key, path, body, headers=None):
    h = {"content-type": "application/json", "authorization": "Bearer " + key}; h.update(headers or {})
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class OpenAIProxy(unittest.TestCase):
    def start(self, **kw):
        self.up = FakeProvider(**kw)
        self.px = EgressProxy([self.up.host], "REAL-KEY", PRICING, scheme="http", style="openai", path_prefix="/zen/go").start()
        self.ctx = Ctx("R1", "g1", 100000, 1000, 1.0, "m")
        self.tok = self.px.bind(self.ctx)
        return self

    def tearDown(self):
        self.px.stop(); self.up.close()

    CHAT = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 99999}

    def test_key_swap_prefix_clamp_and_exact_usage(self):
        self.start()
        st, _ = post(self.px.port, self.tok, "/v1/chat/completions", dict(self.CHAT), {"x-opencode-session": "s1", "x-secret": "no"})
        self.assertEqual(st, 200)
        c = self.up.calls[0]
        self.assertEqual((c["path"], c["auth"], c["oc"]), ("/zen/go/v1/chat/completions", "Bearer REAL-KEY", "s1"))
        self.assertEqual(c["body"]["max_tokens"], 1000)                                   # clamped to max_output_tokens
        s = self.ctx.samples[0]
        self.assertEqual((s["uncached_input_tokens"], s["cache_read_tokens"], s["output_tokens"], s["source"]), (60, 40, 20, "exact"))
        self.assertAlmostEqual(s["cost"], (60 * 0.15 + 40 * 0.15 + 20 * 0.6) / 1e6)

    def test_rejections(self):
        self.start()
        P = lambda body, path="/v1/chat/completions", key=None: post(self.px.port, key or self.tok, path, body)[0]
        self.assertEqual(P(dict(self.CHAT, model="expensive")), 403)
        self.assertEqual(P(self.CHAT, key="REAL-KEY"), 401)
        self.assertEqual(P(self.CHAT, path="/v1/models"), 403)
        self.assertEqual(P(self.CHAT, path="/v1/embeddings"), 403)
        self.assertEqual(P(dict(self.CHAT, tools=[{"type": "web_search"}])), 403)
        self.assertEqual(P(dict(self.CHAT, messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x.example/a.png"}}]}])), 403)
        self.assertEqual(self.up.calls, [])                                               # nothing reached the provider
        self.assertEqual(P(dict(self.CHAT, tools=[{"type": "function", "function": {"name": "read"}}])), 200)

    def test_streaming_asks_for_usage_and_counts_it(self):
        self.start(stream=True)
        st, body = post(self.px.port, self.tok, "/v1/chat/completions", dict(self.CHAT, stream=True))
        self.assertEqual(st, 200); self.assertIn(b"[DONE]", body)
        self.assertEqual(self.up.calls[0]["body"]["stream_options"], {"include_usage": True})
        self.assertEqual((self.ctx.samples[0]["output_tokens"], self.ctx.tokens), (20, 120))
        self.assertFalse(self.ctx.budget_hit)

    def test_a_call_without_usage_cannot_be_priced_so_it_stops_the_run(self):
        self.start(usage=False)
        post(self.px.port, self.tok, "/v1/chat/completions", dict(self.CHAT))
        self.assertTrue(self.ctx.budget_hit)
        self.assertEqual(post(self.px.port, self.tok, "/v1/chat/completions", dict(self.CHAT))[0], 429)

    def test_budget_cuts_the_next_call(self):
        self.start()
        self.ctx.budget_left_usd = 0.000001
        self.assertEqual(post(self.px.port, self.tok, "/v1/chat/completions", dict(self.CHAT))[0], 429)
        self.assertEqual(self.up.calls, [])

    def test_responses_api_for_codex(self):
        self.start(stream=True, responses=True)
        body = {"model": "m", "input": [{"role": "user", "content": "hi"}], "max_output_tokens": 99999, "stream": True,
                "tools": [{"type": "function", "name": "shell"}]}
        st, _ = post(self.px.port, self.tok, "/v1/responses", body)
        self.assertEqual(st, 200)
        self.assertEqual(self.up.calls[0]["body"]["max_output_tokens"], 1000)
        self.assertNotIn("stream_options", self.up.calls[0]["body"])
        s = self.ctx.samples[0]
        self.assertEqual((s["uncached_input_tokens"], s["cache_read_tokens"], s["output_tokens"]), (60, 40, 20))
        for tool in ("web_search", "file_search", "code_interpreter", "mcp", "image_generation"):
            self.assertEqual(post(self.px.port, self.tok, "/v1/responses", dict(body, tools=[{"type": tool}]))[0], 403, tool)


if __name__ == "__main__":
    unittest.main()


class LoginTunnel(unittest.TestCase):
    """The CONNECT tunnel used by sign-in mode, driven with raw sockets (no client that might add credentials by itself)."""

    def setUp(self):
        import socket
        self.echo = socket.socket(); self.echo.bind(("127.0.0.1", 0)); self.echo.listen(5)
        self.echo_port = self.echo.getsockname()[1]
        def serve():
            while True:
                try:
                    c, _ = self.echo.accept()
                except OSError:
                    return
                def pipe(c=c):
                    try:
                        while True:
                            d = c.recv(4096)
                            if not d: break
                            c.sendall(b"echo:" + d)
                    finally:
                        c.close()
                threading.Thread(target=pipe, daemon=True).start()
        threading.Thread(target=serve, daemon=True).start()
        self.px = EgressProxy(["localhost"], "", PRICING, style="login", login_hosts=["localhost"], login_ports=(self.echo_port,), allow_private=True).start()
        self.ctx = Ctx("R9", "g", 1000, 100, 1.0, "")
        self.tok = self.px.bind(self.ctx)

    def tearDown(self):
        self.px.stop(); self.echo.close()

    def connect(self, target, auth="token"):
        import base64, socket
        s = socket.create_connection(("127.0.0.1", self.px.port), timeout=5)
        head = "CONNECT %s HTTP/1.1\r\nHost: %s\r\n" % (target, target)
        if auth == "token":
            head += "Proxy-Authorization: Basic %s\r\n" % base64.b64encode(("door:" + self.tok).encode()).decode()
        elif auth:
            head += "Proxy-Authorization: Basic %s\r\n" % base64.b64encode(("door:" + auth).encode()).decode()
        s.sendall((head + "\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = s.recv(4096)
            if not d: break
            buf += d
        return s, int(buf.split(b" ", 2)[1])

    def test_wrong_or_missing_credentials_never_open_a_tunnel(self):
        for auth in ("wrong", "", None):
            _, code = self.connect("localhost:%d" % self.echo_port, auth)
            self.assertEqual(code, 407, repr(auth))
        self.px.unbind(self.tok)
        self.assertEqual(self.connect("localhost:%d" % self.echo_port)[1], 407)               # a finished run's token is dead

    def test_only_allowed_hosts_and_ports(self):
        self.assertEqual(self.connect("example.com:%d" % self.echo_port)[1], 403)
        self.assertEqual(self.connect("localhost:22")[1], 403)
        self.assertEqual(self.connect("localhost:notaport")[1], 400)

    def test_allowed_target_is_piped_both_ways(self):
        s, code = self.connect("localhost:%d" % self.echo_port)
        self.assertEqual(code, 200)
        s.sendall(b"ping"); self.assertEqual(s.recv(100), b"echo:ping")
        s.close()

    def test_private_addresses_are_refused_in_production_settings(self):
        px = EgressProxy(["localhost"], "", PRICING, style="login", login_hosts=["localhost"], login_ports=(self.echo_port,)).start()   # allow_private False
        try:
            tok = px.bind(Ctx("R8", "g", 1000, 100, 1.0, ""))
            import base64, socket
            s = socket.create_connection(("127.0.0.1", px.port), timeout=5)
            s.sendall(("CONNECT localhost:%d HTTP/1.1\r\nProxy-Authorization: Basic %s\r\n\r\n" % (self.echo_port, base64.b64encode(("door:" + tok).encode()).decode())).encode())
            self.assertEqual(int(s.recv(200).split(b" ", 2)[1]), 403)
        finally:
            px.stop()

    def test_plain_api_calls_and_api_mode_do_not_tunnel(self):
        import socket
        s = socket.create_connection(("127.0.0.1", self.px.port), timeout=5)
        body = b"{}"
        s.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + self.tok.encode() + b"\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n" + body)
        self.assertEqual(int(s.recv(200).split(b" ", 2)[1]), 403)
        api = EgressProxy(["api.anthropic.com"], "K", PRICING).start()
        try:
            s2 = socket.create_connection(("127.0.0.1", api.port), timeout=5)
            s2.sendall(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n")
            self.assertEqual(int(s2.recv(200).split(b" ", 2)[1]), 403)
        finally:
            api.stop()


class LoginCommands(unittest.TestCase):
    base = {"name": "door-run-x", "export_dir": "/s/e", "outbox_dir": "/s/o", "placeholder_key": "door-TOK", "prompt": "Q", "model": "sonnet",
            "cpus": 1, "memory_mb": 256, "login": True}

    def cmd(self, **kw): return ContainerRuntime().build_command(dict(self.base, **kw))

    def test_home_is_the_login_volume_not_a_copy_of_this_computers_login(self):
        c = self.cmd(backend="claude"); j = " ".join(c)
        self.assertIn("door-login-claude:/home/agent:rw", j)
        self.assertNotIn("--tmpfs /home/agent", j); self.assertNotIn(str(Path.home()), j)
        self.assertNotIn(".claude:", j)

    def test_claude_login_command_is_still_locked_down(self):
        c = self.cmd(backend="claude")
        self.assertNotIn("--bare", c)                                    # --bare would demand an API key
        self.assertEqual(c[c.index("--tools") + 1], "Read,Grep,Glob,Write,Edit")
        self.assertEqual(c[c.index("--setting-sources") + 1], "user"); self.assertIn("--max-turns", c)
        j = " ".join(c)
        self.assertIn("HTTPS_PROXY=http://door:door-TOK@door-relay:8080", j); self.assertNotIn("ANTHROPIC_API_KEY", j)
        boss = self.cmd(backend="claude", boss=True)
        self.assertEqual(boss[boss.index("--tools") + 1], "Write")

    def test_opencode_and_codex_login_commands(self):
        oc = " ".join(self.cmd(backend="opencode", model="openai/gpt-5"))
        cfg = json.loads(oc.split("OPENCODE_CONFIG_CONTENT=")[1].split(" -e ")[0])
        self.assertNotIn("provider", cfg); self.assertEqual(cfg["model"], "openai/gpt-5"); self.assertEqual(cfg["permission"]["bash"], "deny")
        cx = " ".join(self.cmd(backend="codex"))
        self.assertIn("door-login-codex:/home/agent:rw", cx); self.assertIn('sandbox_mode="read-only"', cx); self.assertNotIn("model_providers", cx)

    def test_policy_login_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = policy(d, egress={"mode": "login"})
            self.assertEqual((p["egress"]["mode"], p["egress"]["style"]), ("login", "login"))
            self.assertIn("api.anthropic.com", p["egress"]["allow_hosts"]); self.assertNotIn("opencode.ai", p["egress"]["allow_hosts"])
            with self.assertRaises(PolicyError): policy(d, egress={"mode": "magic"})


class UpstreamFailures(unittest.TestCase):
    """A failure before anything was sent may be retried safely; a failure after sending must stop the run (it may have been charged)."""

    def run_call(self, upstream_host):
        px = EgressProxy([upstream_host], "REAL-KEY", PRICING, scheme="http", style="openai").start()
        try:
            ctx = Ctx("R7", "g", 100000, 1000, 1.0, "m")
            tok = px.bind(ctx)
            st, _ = post(px.port, tok, "/v1/chat/completions", {"model": "m", "messages": [{"role": "user", "content": "hi"}]})
            return st, ctx
        finally:
            px.stop()

    def test_nothing_listening_is_a_clean_502_that_does_not_poison_the_run(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()           # a port nobody listens on
        st, ctx = self.run_call("127.0.0.1:%d" % port)
        self.assertEqual(st, 502); self.assertFalse(ctx.budget_hit)

    def test_a_server_that_takes_the_request_and_hangs_up_stops_the_run(self):
        import socket
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
        def serve():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                c.recv(65536); c.close()                                                               # read the request, answer nothing
        threading.Thread(target=serve, daemon=True).start()
        try:
            st, ctx = self.run_call("127.0.0.1:%d" % srv.getsockname()[1])
        finally:
            srv.close()
        self.assertEqual(st, 502); self.assertTrue(ctx.budget_hit)
