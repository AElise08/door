"""Proxy de saída (Seção 9.4).

Reverse proxy local: o sandbox recebe ANTHROPIC_BASE_URL apontando para cá e uma credencial de mentira
(por pedido). O proxy troca pela credencial real, só fala com egress.allow_hosts[0], reescreve max_tokens,
mede o uso exato e aplica max_turn_tokens e o orçamento mensal restante.
"""
import base64
import os
import sys
import time
import http.client
import ipaddress
import json
import select
import socket
import ssl
import threading
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .common import ulid, now


def _in(u):
    """Entrada conta também tokens de cache (conservador: custo nunca subestimado)."""
    return u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)


class Ctx:
    """Estado de um pedido dentro do proxy."""

    def __init__(self, request_id, guest_id, max_turn_tokens, max_output_tokens, budget_left_usd, model=""):
        self.request_id, self.guest_id = request_id, guest_id
        self.max_turn_tokens, self.max_output_tokens = max_turn_tokens, max_output_tokens
        self.budget_left_usd = budget_left_usd
        self.tokens = 0
        self.cost = 0.0
        self.samples = []
        self.budget_hit = False
        self.lock = threading.Lock()
        self.call_lock = threading.Lock()
        self.model = model


class EgressProxy:
    def __init__(self, allow_hosts, credential, pricing, scheme="https", on_usage=None, port=0, bind="127.0.0.1",
                 style="anthropic", path_prefix="", login_hosts=None, login_ports=(443,), allow_private=False):
        self.style, self.path_prefix = style, path_prefix.rstrip("/")
        # Login mode: the agent CLI talks to its provider with its own login, so the proxy can only tunnel (CONNECT) to these hosts.
        self.login_hosts = {x.lower() for x in (login_hosts or [])}
        self.login_ports, self.allow_private = set(login_ports), allow_private
        self.upstream = allow_hosts[0]
        self.allow_hosts = list(allow_hosts)
        self.credential, self.pricing, self.scheme = credential, pricing, scheme
        self.on_usage = on_usage or (lambda ctx, sample: None)
        self.ctxs = {}
        self._reg = threading.Lock()
        proxy = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # fim do corpo = fechar conexão; serve para SSE

            def log_message(self, *a):
                pass

            def _deny(self, code, msg):
                body = json.dumps({"type": "error", "error": {"type": "door_error", "message": msg}}).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self):
                proxy._handle(self)

            do_POST = do_GET = _handle

            def do_CONNECT(self):
                proxy._connect(self)

        self.httpd = ThreadingHTTPServer((bind, port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = None

    # ---- ciclo de vida ----
    def start(self):
        self._thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def bind(self, ctx: Ctx) -> str:
        """Registra o pedido e devolve a credencial de mentira que o sandbox usará."""
        token = "door-%s-%s" % (ctx.request_id, ulid()[-8:])
        with self._reg:
            self.ctxs[token] = ctx
        return token

    def unbind(self, token):
        with self._reg:
            return self.ctxs.pop(token, None)

    # ---- custo ----
    def _cost(self, inp, out, cache_read=0, cache_write=0):
        return (inp * self.pricing["input_per_mtok"] + out * self.pricing["output_per_mtok"]
                + cache_read * self.pricing.get("cache_read_per_mtok", self.pricing["input_per_mtok"])
                + cache_write * self.pricing.get("cache_write_per_mtok", 2 * self.pricing["input_per_mtok"])) / 1_000_000

    def _record(self, ctx: Ctx, model, inp, out, cache_read=0, cache_write=0):
        with ctx.lock:
            cost = self._cost(inp, out, cache_read, cache_write)
            ctx.tokens += inp + out + cache_read + cache_write
            ctx.cost += cost
            s = {"id": ulid(), "recorded_at": now(), "request_id": ctx.request_id, "guest_id": ctx.guest_id,
                 "model": model, "input_tokens": inp + cache_read + cache_write,
                 "uncached_input_tokens": inp, "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
                 "output_tokens": out, "cost": cost, "source": "exact"}
            ctx.samples.append(s)
            if ctx.tokens >= ctx.max_turn_tokens or ctx.cost >= ctx.budget_left_usd:
                ctx.budget_hit = True
        self.on_usage(ctx, s)

    # ---- requisição ----
    def _handle(self, h):
        key = h.headers.get("x-api-key") or (h.headers.get("authorization") or "").replace("Bearer ", "")
        with self._reg:
            ctx = self.ctxs.get(key)
        if ctx is None:
            return h._deny(401, "invalid credential")
        if self.style == "login":                  # sign-in mode only tunnels (CONNECT); no plain API calls go through here
            return h._deny(403, "route not allowed")
        routes = ("/v1/chat/completions", "/v1/responses") if self.style == "openai" else ("/v1/messages", "/v1/messages?beta=true")
        if h.command != "POST" or h.path not in routes:
            return h._deny(403, "route not allowed")
        with ctx.call_lock:
            return self._call(h, ctx)

    def _connection(self):
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.upstream, timeout=60, context=ssl.create_default_context())
        return http.client.HTTPConnection(self.upstream, timeout=60)

    def _call(self, h, ctx):
        if self.style == "openai":
            return self._call_openai(h, ctx)
        return self._call_anthropic(h, ctx)

    # ---- OpenAI-compatible providers (OpenCode Go, OpenRouter, DeepSeek, ...) ----
    @staticmethod
    def _has_remote_openai(value):
        """Remote files, images by URL and audio could open another way out; plain text and local tool calls only."""
        if isinstance(value, dict):
            return any(k in ("image_url", "file", "input_audio", "video_url", "file_url", "file_id") for k in value) or any(
                EgressProxy._has_remote_openai(v) for v in value.values())
        return isinstance(value, list) and any(EgressProxy._has_remote_openai(v) for v in value)

    def _call_openai(self, h, ctx):
        with ctx.lock:
            over = ctx.budget_hit or ctx.tokens >= ctx.max_turn_tokens or ctx.cost >= ctx.budget_left_usd
        if over:
            ctx.budget_hit = True
            return h._deny(429, "budget exhausted")
        try:
            n = int(h.headers.get("content-length") or 0)
        except ValueError:
            return h._deny(400, "invalid size")
        if n <= 0 or n > 8 * 1024 * 1024 or h.headers.get("transfer-encoding"):
            return h._deny(413, "invalid or oversized body")
        raw = h.rfile.read(n)
        if "json" not in (h.headers.get("content-type") or ""):
            return h._deny(400, "JSON required")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or (ctx.model and body.get("model") != ctx.model):
                return h._deny(403, "model not allowed")
            responses = h.path == "/v1/responses"
            provider_side = {"web_search", "web_search_preview", "file_search", "code_interpreter", "computer_use_preview", "image_generation", "mcp"}
            for tool in body.get("tools") or []:
                kind = tool.get("type", "function") if isinstance(tool, dict) else None
                if kind is None or (kind in provider_side if responses else kind != "function"):
                    return h._deny(403, "server tool not allowed")       # tools the provider would run itself open another way out
            if self._has_remote_openai(body.get("messages")) or self._has_remote_openai(body.get("input")):   # tool schemas may name such fields
                return h._deny(403, "remote content not allowed")
            # No token-count endpoint here, so the input is over-estimated (2 bytes per token) and the budget is reserved on that.
            est_in = len(raw) // 2 + 1
            price_in, price_out = self.pricing["input_per_mtok"], self.pricing["output_per_mtok"]
            with ctx.lock:
                money = ctx.budget_left_usd - ctx.cost - est_in * price_in / 1_000_000
                room = ctx.max_turn_tokens - ctx.tokens - est_in
            cap = min(ctx.max_output_tokens, room, math.floor(money * 1_000_000 / price_out))
            if cap <= 0:
                ctx.budget_hit = True
                return h._deny(429, "insufficient budget for this call")
            field = "max_output_tokens" if responses else "max_tokens"
            asked = body.pop("max_completion_tokens", None) or body.get(field)
            body[field] = min(asked, cap) if isinstance(asked, int) and asked > 0 else cap
            stream = bool(body.get("stream"))
            if stream and not responses:
                body["stream_options"] = {"include_usage": True}      # otherwise streamed chat calls report no usage at all
            raw = json.dumps(body).encode()
        except (ValueError, TypeError):
            return h._deny(400, "invalid body")
        # x-opencode-* are the routing/session labels the OpenCode CLI adds for its own provider; they carry no secrets.
        hdr = {k: v for k, v in h.headers.items() if k.lower() in ("content-type", "accept") or k.lower().startswith("x-opencode-")}
        hdr["authorization"] = "Bearer " + self.credential
        hdr["content-length"] = str(len(raw))
        conn = None
        for attempt in range(3):                                       # failing to CONNECT means nothing was sent: retrying cannot double-charge
            try:
                conn = self._connection()
                conn.connect()
                break
            except OSError as e:
                if os.environ.get("DOOR_PROXY_DEBUG"):
                    print("proxy: connect attempt %d failed (%s)" % (attempt + 1, type(e).__name__), file=sys.stderr, flush=True)
                conn = None
                time.sleep(0.4 * (attempt + 1))
        if conn is None:
            return h._deny(502, "upstream unavailable")
        try:
            conn.request("POST", self.path_prefix + h.path, body=raw, headers=hdr)
            resp = conn.getresponse()
        except OSError as e:
            if os.environ.get("DOOR_PROXY_DEBUG"):
                print("proxy: failed after sending (%s)" % type(e).__name__, file=sys.stderr, flush=True)
            ctx.budget_hit = True                                      # sent but no answer: whether the provider charged is unknown, so stop
            return h._deny(502, "upstream unavailable")
        if os.environ.get("DOOR_PROXY_DEBUG"):       # status codes only: never bodies, headers or keys
            print("proxy: upstream status=%s stream=%s type=%s" % (resp.status, stream, resp.getheader("content-type")), file=sys.stderr, flush=True)
        h.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("content-type", "x-request-id"):
                h.send_header(k, v)
        h.end_headers()
        if stream or "text/event-stream" in (resp.getheader("content-type") or ""):
            self._relay_sse_openai(h, resp, ctx)
        else:
            data = resp.read()
            h.wfile.write(data)
            try:
                j = json.loads(data)
                u = j.get("usage") or {}
                if u:
                    self._record_openai(ctx, j.get("model", ""), u)
                elif resp.status == 200:
                    ctx.budget_hit = True
            except ValueError:
                if resp.status == 200:
                    ctx.budget_hit = True
        conn.close()

    def _record_openai(self, ctx, model, u):
        prompt, out = int(u.get("prompt_tokens", u.get("input_tokens", 0)) or 0), int(u.get("completion_tokens", u.get("output_tokens", 0)) or 0)
        details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
        cached = min(prompt, int(details.get("cached_tokens", 0) or 0))
        self._record(ctx, model, prompt - cached, out, cached, 0)

    def _relay_sse_openai(self, h, resp, ctx):
        model, usage, buf, seen = "", None, b"", 0
        while True:
            chunk = resp.read1(8192) if hasattr(resp, "read1") else resp.read(8192)
            if not chunk:
                break
            try:
                h.wfile.write(chunk)
                h.wfile.flush()
            except OSError:
                pass                                                    # the client left; upstream use is still counted
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]":
                    continue
                try:
                    ev = json.loads(line[5:])
                except ValueError:
                    continue
                seen += 1
                inner = ev.get("response") if isinstance(ev.get("response"), dict) else {}      # Responses API: usage rides on response.completed
                model = ev.get("model") or inner.get("model") or model
                u = ev.get("usage") if isinstance(ev.get("usage"), dict) else inner.get("usage")
                if isinstance(u, dict):
                    usage = u
        if usage:
            self._record_openai(ctx, model, usage)
        else:
            if os.environ.get("DOOR_PROXY_DEBUG"):
                print("proxy: stream ended WITHOUT a usage report (events seen: %d)" % seen, file=sys.stderr, flush=True)
            ctx.budget_hit = True                                       # a call with no usage report cannot be priced

    def _call_anthropic(self, h, ctx):
        with ctx.lock:
            over_turn = ctx.tokens >= ctx.max_turn_tokens
            over_budget = ctx.cost >= ctx.budget_left_usd
        if over_turn or over_budget:
            ctx.budget_hit = True
            return h._deny(429, "budget exhausted")
        try:
            n = int(h.headers.get("content-length") or 0)
        except ValueError:
            return h._deny(400, "invalid size")
        if n <= 0 or n > 8 * 1024 * 1024 or h.headers.get("transfer-encoding"):
            return h._deny(413, "invalid or oversized body")
        raw = h.rfile.read(n) if n else b""
        stream = False
        if raw and "json" in (h.headers.get("content-type") or ""):
            try:
                body = json.loads(raw)
                if not isinstance(body, dict) or (ctx.model and body.get("model") != ctx.model):
                    return h._deny(403, "model not allowed")
                if not isinstance(body.get("max_tokens"), int) or body["max_tokens"] <= 0:
                    return h._deny(400, "invalid max_tokens")
                # Só chamadas de texto/ferramentas locais. URLs, arquivos remotos e
                # ferramentas executadas pelo provedor poderiam abrir outra saída.
                for tool in body.get("tools", []):
                    if tool.get("type", "custom") != "custom":
                        return h._deny(403, "server tool not allowed")
                def has_remote(value):
                    if isinstance(value, dict):
                        return value.get("type") in {"url", "file", "container_upload"} or any(has_remote(v) for v in value.values())
                    return isinstance(value, list) and any(has_remote(v) for v in value)
                if has_remote(body):
                    return h._deny(403, "remote content not allowed")
                count_body = {k: body[k] for k in ("model", "messages", "system", "tools", "tool_choice", "thinking") if k in body}
                counter = self._connection()
                try:
                    counter.request("POST", "/v1/messages/count_tokens", json.dumps(count_body).encode(),
                                    {"x-api-key": self.credential, "anthropic-version": "2023-06-01", "content-type": "application/json"})
                    counted = counter.getresponse()
                    data = counted.read()
                    if counted.status != 200:
                        return h._deny(502, "token pre-count unavailable; call blocked")
                    input_count = json.loads(data)["input_tokens"]
                    if type(input_count) is not int or input_count < 0:
                        raise ValueError("invalid count")
                except (OSError, ValueError, KeyError):
                    return h._deny(502, "token pre-count unavailable; call blocked")
                finally:
                    counter.close()
                with ctx.lock:
                    # Reserva conservadora: cache write de 1h custa até 2x entrada.
                    reserve = max(self.pricing["input_per_mtok"], self.pricing.get("cache_write_per_mtok", 2 * self.pricing["input_per_mtok"]))
                    money = ctx.budget_left_usd - ctx.cost - input_count * reserve / 1_000_000
                    room = ctx.max_turn_tokens - ctx.tokens - input_count
                price_out = self.pricing["output_per_mtok"]
                cap = min(ctx.max_output_tokens, room, math.floor(money * 1_000_000 / price_out))
                if cap <= 0:
                    ctx.budget_hit = True
                    return h._deny(429, "insufficient budget for this call")
                body["max_tokens"] = min(int(body.get("max_tokens") or cap), cap)
                stream = bool(body.get("stream"))
                raw = json.dumps(body).encode()
            except (ValueError, TypeError):
                return h._deny(400, "invalid body")
        else:
            return h._deny(400, "JSON required")
        hdr = {k: v for k, v in h.headers.items() if k.lower() in ("content-type", "accept", "anthropic-version", "anthropic-beta")}
        hdr["x-api-key"] = self.credential
        hdr["content-length"] = str(len(raw))
        try:
            conn = self._connection()
            conn.request(h.command, h.path, body=raw or None, headers=hdr)
            resp = conn.getresponse()
        except OSError:
            # Aceite pelo provedor incerto: não permitir gastar de novo às cegas.
            ctx.budget_hit = True
            return h._deny(502, "upstream unavailable")
        h.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("content-type", "request-id", "anthropic-ratelimit-requests-remaining"):
                h.send_header(k, v)
        h.end_headers()
        if stream or "text/event-stream" in (resp.getheader("content-type") or ""):
            self._relay_sse(h, resp, ctx)
        else:
            data = resp.read()
            h.wfile.write(data)
            try:
                j = json.loads(data)
                u = j.get("usage") or {}
                if u:
                    self._record(ctx, j.get("model", ""), u.get("input_tokens", 0), u.get("output_tokens", 0),
                                 u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0))
                elif resp.status == 200:
                    ctx.budget_hit = True
            except ValueError:
                pass
        conn.close()

    def _relay_sse(self, h, resp, ctx):
        model, inp, out, cache_read, cache_write = "", 0, 0, 0, 0
        buf = b""
        while True:
            chunk = resp.read1(8192) if hasattr(resp, "read1") else resp.read(8192)
            if not chunk:
                break
            # Mesmo se o cliente fechar, consumo upstream continua sendo contabilizado.
            try:
                h.wfile.write(chunk)
                h.wfile.flush()
            except OSError:
                pass
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                try:
                    ev = json.loads(line[5:])
                except ValueError:
                    continue
                if ev.get("type") == "message_start":
                    m = ev.get("message", {})
                    model = m.get("model", model)
                    inp = (m.get("usage") or {}).get("input_tokens", 0)
                    cache_read = (m.get("usage") or {}).get("cache_read_input_tokens", 0)
                    cache_write = (m.get("usage") or {}).get("cache_creation_input_tokens", 0)
                    out = (m.get("usage") or {}).get("output_tokens", out)
                elif ev.get("type") == "message_delta":
                    u = ev.get("usage") or {}
                    out = u.get("output_tokens", out)
                    inp = u.get("input_tokens", inp)
                    cache_read = u.get("cache_read_input_tokens", cache_read)
                    cache_write = u.get("cache_creation_input_tokens", cache_write)
        if inp or out:
            self._record(ctx, model, inp, out, cache_read, cache_write)


    # ---- login mode: allow-listed HTTPS tunnel ----
    TUNNEL_MAX_BYTES = 400 * 1024 * 1024
    TUNNEL_IDLE_S = 300

    def _connect(self, h):
        """CONNECT host:443 for a bound run, only to the provider's own hosts. The proxy sees no tokens or cost in this mode: the
        bound limits are the run's wall-clock timeout, the engine's own turn cap and the per-guest request limits."""
        if not self.login_hosts:
            return h._deny(403, "tunnels are not enabled")
        try:
            kind, _, cred = (h.headers.get("proxy-authorization") or "").partition(" ")
            token = base64.b64decode(cred).decode().split(":", 1)[1] if kind.lower() == "basic" else ""
        except (ValueError, IndexError, UnicodeDecodeError):
            token = ""
        with self._reg:
            ctx = self.ctxs.get(token)
        if ctx is None:
            h.send_response(407); h.send_header("Proxy-Authenticate", 'Basic realm="door"'); h.send_header("content-length", "0"); h.end_headers()
            return
        host, _, port = h.path.rpartition(":")
        try:
            port = int(port)
        except ValueError:
            return h._deny(400, "bad target")
        if host.lower() not in self.login_hosts or port not in self.login_ports:
            return h._deny(403, "host not allowed")
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not self.allow_private and any(not ipaddress.ip_address(i[4][0]).is_global for i in infos):
                return h._deny(403, "host not allowed")
            upstream = None
            for info in infos:                       # connect to the addresses that were just checked, never to a fresh lookup
                try:
                    upstream = socket.create_connection(info[4][:2], timeout=15)
                    break
                except OSError:
                    continue
            if upstream is None:
                raise OSError("no address reachable")
        except OSError:
            return h._deny(502, "upstream unavailable")
        try:
            h.send_response(200, "Connection Established")
            h.end_headers()
            h.wfile.flush()
            client, total = h.connection, 0
            socks = [client, upstream]
            while total < self.TUNNEL_MAX_BYTES:
                ready, _, _ = select.select(socks, [], [], self.TUNNEL_IDLE_S)
                if not ready:
                    break
                done = False
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        done = True
                        break
                    total += len(data)
                    (upstream if s is client else client).sendall(data)
                if done:
                    break
        except OSError:
            pass
        finally:
            upstream.close()
