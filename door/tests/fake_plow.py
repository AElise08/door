"""A pretend Plow, speaking the cloud-agent contract that MyPlow's working bridge uses:
GET /v1/agents/cloud/me, GET/POST /v1/chats/<uid>/messages, and an MCP relay that reaches the owner's Mac (here: a Host in this process)."""
import base64
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakePlow:
    def __init__(self, host, with_latch=True):
        self.host, self.with_latch = host, with_latch
        self.chats, self.outbound, self.auth_seen, self.n = {}, [], set(), 0
        plow = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _json(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
                self.send_header("Mcp-Session-Id", "s1"); self.end_headers(); self.wfile.write(data)

            def do_GET(self):
                plow.auth_seen.add(self.headers.get("authorization"))
                if self.path == "/v1/agents/cloud/me":
                    return self._json({"chats": [{"uid": u, "participants": c["participants"]} for u, c in plow.chats.items()],
                                       "mcp_url": ("http://127.0.0.1:%d/mcp" % plow.port) if plow.with_latch else None})
                if self.path.startswith("/v1/chats/") and "/messages" in self.path:
                    uid = self.path.split("/")[3]
                    return self._json({"data": list(plow.chats[uid]["messages"]), "has_more": False})
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                plow.auth_seen.add(self.headers.get("authorization"))
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if self.path.startswith("/v1/chats/") and self.path.endswith("/messages"):
                    plow.outbound.append((self.path.split("/")[3], body["body"]))
                    return self._json({"uid": "out_%d" % len(plow.outbound)})
                if self.path == "/mcp":
                    return self._json(plow.mcp(body))
                self._json({"error": "not found"}, 404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()

    # ---- the conversations ----
    def chat(self, uid, *phones):
        members = [{"type": "member", "uid": "u_" + p[-4:], "provider_key": p} for p in phones]
        self.chats[uid] = {"participants": [{"type": "agent", "relationship": "self", "line": {"uid": "ln_1", "provider_type": "imessage"}}] + members, "messages": []}

    def say(self, uid, phone, text):
        self.n += 1
        self.chats[uid]["messages"].insert(0, {"uid": "msg_%d" % self.n, "direction": "inbound", "body": text,
                                              "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                              "sender": {"type": "member", "uid": "u_" + phone[-4:], "provider_key": phone}})

    def texts_to(self, uid): return [t for u, t in self.outbound if u == uid]

    # ---- the MCP relay to the Mac ----
    def mcp(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake-plow"}}}
        if method == "tools/call" and msg["params"]["name"] == "plow_run_command":
            argv = msg["params"]["arguments"]["argv"]
            out = self.run(argv)
            return {"jsonrpc": "2.0", "id": mid, "result": {"structuredContent": {"status": "ready", "result": {"status": "completed", "running": False,
                                                                                                                 "output": json.dumps(out)}}}}
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "no"}}

    def run(self, argv):
        a = dict(zip(argv[2::2], argv[3::2]))
        cmd = argv[1]
        if cmd == "ask": return self.host.ask(a["--payload"], a["--sig"])
        if cmd == "status": return self.host.status(a["--request"])
        if cmd == "summary": return self.host.summary()
        if cmd == "pair-confirm": return self.host.pair_confirm(a["--code"], a["--public-key"])
        if cmd == "decide": return self.host.decide_action(a["--request"], a["--action"], a["--decision"])
        if cmd == "cancel": return self.host.cancel(a["--request"], a["--reason"])
        return {"ok": False, "reason": "unknown"}
