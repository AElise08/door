"""Adapters do contrato público Plow baixado em 2026-10-06.

Só respostas da API autenticada definem identidade e roster. Tokens Plow ficam
no processo de nuvem; não são tokens do host nem do modelo.
"""
import hashlib
import os
import json
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError


class PlowAPI:
    def __init__(self, token, base="https://api.plow.co", opener=urlopen, cloud=False, local=False):
        """cloud=True: this process IS a Plow cloud agent. Its conversations come from /v1/agents/cloud/me, and the token is the
        "proxied" placeholder that Plow's proxy replaces with the real one, so nothing secret is configured here.
        local=True allows plain http to a loopback address (development and tests only)."""
        self.token, self.base, self.opener, self.cloud = token, base.rstrip("/"), opener, cloud
        loopback = local and self.base.startswith(("http://127.0.0.1", "http://localhost"))
        if not self.base.startswith("https://") and not loopback:
            raise ValueError("Plow API requires HTTPS")
        self.local = local

    def request(self, method, path, body=None, headers=None, url=None):
        hdr = {"Authorization": "Bearer " + self.token, "Accept": "application/json", **(headers or {})}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            hdr["Content-Type"] = "application/json"
        if url is not None and not (url.startswith("https://") or (self.local and url.startswith(("http://127.0.0.1", "http://localhost")))):
            raise ValueError("relay address must be HTTPS")
        try:
            with self.opener(Request(url or self.base + path, data=data, headers=hdr, method=method), timeout=25) as response:
                raw = response.read(8 * 1024 * 1024)
                if "text/event-stream" in response.headers.get("content-type", ""):
                    events = [json.loads(line[5:]) for line in raw.decode().splitlines() if line.startswith("data:")]
                    result = next((e for e in reversed(events) if "result" in e or "error" in e), {})
                else:
                    result = json.loads(raw) if raw else {}
                return result, response.headers
        except HTTPError as e:
            if e.code in {401, 403, 404}:
                raise PermissionError("Plow credential, scope or device refused") from e
            raise OSError("Plow unavailable") from e
        except (URLError, ValueError) as e:
            raise OSError("Plow response unavailable or invalid") from e

    def get(self, path):
        return self.request("GET", path)[0]

    def send(self, thread, text):
        if not thread.startswith("cht_"):
            raise ValueError("invalid chat_uid")
        return self.request("POST", "/v1/chats/" + quote(thread, safe="") + "/messages",
                            {"body": text, "format": "none"})[0]

    @staticmethod
    def normalize(chat, msg, line_uid):
        roster = chat.get("participants", [])
        if line_uid is None:        # a cloud agent has exactly one line, and every chat it is in is on that line
            own = [p for p in roster if p.get("type") == "agent" and p.get("relationship") == "self"]
        else:
            own = [p for p in roster if p.get("type") == "agent" and p.get("relationship") == "self"
                   and p.get("line", {}).get("uid") == line_uid and p["line"].get("provider_type") == "imessage"]
        people = [p for p in roster if p.get("type") == "member"]
        sender = msg.get("sender", {})
        if not own or msg.get("direction") != "inbound" or sender.get("type") != "member":
            return None
        # Conservador: roster incompleto/ambíguo não pode aprovar nem criar pedidos.
        single = len(roster) == 2 and len(people) == 1 and people[0].get("uid") == sender.get("uid") \
                 and people[0].get("provider_key") == sender.get("provider_key")
        keys = [x.get("provider_key") for x in people]
        members = keys if keys and all(isinstance(k, str) and k for k in keys) else None   # None: roster incomplete, treat as unsafe
        return {"message_id": msg["uid"], "phone": sender.get("provider_key", ""), "thread": chat["uid"],
                "text": msg.get("body", ""), "is_group": not single, "members": members}

    def cloud_me(self):
        return self.get("/v1/agents/cloud/me")

    def _chats(self):
        """The conversations to read. For a cloud agent: the live list from /me (a group the line joins later is a new chat), each with its
        roster (taken from /me when it carries one, otherwise from the chat itself). A chat with no roster is skipped: without it
        we cannot tell a 1:1 from a group, and guessing would let a group read answers meant for one person."""
        if not self.cloud:
            return self.get("/v1/chats").get("data", [])
        out = []
        for c in self.cloud_me().get("chats") or []:
            if not c.get("uid"):
                continue
            if not c.get("participants"):
                try:
                    c = dict(c, **{k: v for k, v in self.get("/v1/chats/" + quote(c["uid"], safe="")).items() if k == "participants"})
                except (OSError, PermissionError):
                    continue
            if c.get("participants"):
                out.append(c)
        return out

    def messages(self, line_uid, since):
        for chat in self._chats():
            cursor = None
            pending = []
            while True:
                query = {"limit": 100, "format": "text_decorations"}
                if cursor:
                    query["starting_after"] = cursor
                page = self.get("/v1/chats/" + quote(chat["uid"], safe="") + "/messages?" + urlencode(query))
                data = page if isinstance(page, list) else page.get("data", [])
                page = {} if isinstance(page, list) else page
                stop = False
                for msg in data:
                    try:
                        timestamp = datetime.fromisoformat(msg["created_at"].replace("Z", "+00:00")).timestamp()
                    except (KeyError, ValueError):
                        continue
                    if timestamp < since:
                        stop = True
                        continue
                    normalized = self.normalize(chat, msg, line_uid)
                    if normalized:
                        pending.append(normalized)
                if stop or not page.get("has_more") or not data:
                    break
                cursor = data[-1]["uid"]
            yield from reversed(pending)


class LatchRelay:
    def __init__(self, api, device_uid, state, save, fallback=False):
        self.api, self.device_uid, self.state, self.save = api, device_uid, state, save
        self.fallback = fallback
        self.session = None

    def _rpc(self, method, params):
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        out, hdr = self.api.request("POST", "/v1/relay/devices/" + quote(self.device_uid, safe="") + "/mcp",
                                    {"jsonrpc": "2.0", "id": "door", "method": method, "params": params}, headers)
        self.session = hdr.get("Mcp-Session-Id", self.session)
        if "error" in out:
            raise OSError("MCP relay refused the call")
        return out.get("result", {})

    def _tool(self, name, arguments):
        if not self.session:
            self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "door", "version": "0.3.0"}})
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise PermissionError("Latch refused the operation")
        if "structuredContent" in result:
            return result["structuredContent"]
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except ValueError:
                    continue
        raise OSError("MCP response without a structured result")

    def command(self, argv):
        key = hashlib.sha256(json.dumps(argv).encode()).hexdigest()
        if key in self.state:
            pending = self.state[key]
            result = self._tool(pending["tool"], {"handle": pending["handle"]})
        else:
            result = self._tool("plow_run_command", {"argv": argv, "network": True, "wait_ms": 3000,        # network: Latch's sandbox blocks even the local socket without it
                                                     "goal": "Door: forward an approved request to the isolated daemon"})
        if result.get("status") == "pending":
            self.state[key] = {"tool": "plow_get_result", "handle": result["handle"]}
            self.save()
            return {"ok": False, "retry": True}
        if result.get("status") == "ready":
            result = result["result"]
        if result.get("running"):
            self.state[key] = {"tool": "plow_get_output", "handle": result["handle"]}
            self.save()
            return {"ok": False, "retry": True}
        self.state.pop(key, None)
        self.save()
        if result.get("status") in {"denied", "blocked", "failed", "expired", "unknown"}:
            return {"ok": False, "reason": "latch_denied"}
        output = result.get("output", "")
        try:
            return json.loads(output.strip())
        except (ValueError, AttributeError):
            return {"ok": False, "reason": "invalid_plugin_result"}

    def _bin(self):
        """The client on the Mac. Latch runs commands in a minimal environment, so a cloud agent is given the full path (DOOR_MAC_BIN)."""
        return os.environ.get("DOOR_MAC_BIN") or ("door-host" if self.fallback else "door")

    def ask(self, rid, payload, sig):
        return self.command([self._bin(), "ask", "--request", rid,
                             "--payload", payload, "--sig", sig])

    def status(self, rid):
        return self.command([self._bin(), "status", "--request", rid])


class McpUrlRelay(LatchRelay):
    """The owner's Mac through Plow Latch, for a cloud agent: Plow gives the agent a ready-made relay URL (mcp_url from /me, null when the
    owner has no Latch) and its proxy adds the credential. Same tool calls as LatchRelay; only the address differs."""

    def __init__(self, api, mcp_url, state, save, fallback=False):
        super().__init__(api, "cloud", state, save, fallback)
        self.mcp_url = mcp_url

    def _rpc(self, method, params):
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        out, hdr = self.api.request("POST", "", {"jsonrpc": "2.0", "id": "door", "method": method, "params": params}, headers, url=self.mcp_url)
        self.session = hdr.get("Mcp-Session-Id", self.session)
        if "error" in out:
            raise OSError("MCP relay refused the call")
        return out.get("result", {})
