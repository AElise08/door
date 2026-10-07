"""A scripted OpenAI-compatible server that plays a hostile or well-behaved model, to test the sandbox with real CLIs
without spending anything. Handles /v1/chat/completions (OpenCode) streaming with tool calls and usage."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOpenAI:
    def __init__(self, script):
        """script(turn_index, request_body) -> ('tool', [(name, args_dict), ...]) | ('text', str)"""
        self.script, self.requests, self.keys = script, [], []
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.requests.append((self.path, body)); up.keys.append(self.headers.get("authorization"))
                system = " ".join(str(m.get("content")) for m in body.get("messages", []) if m.get("role") == "system")
                if "title generator" in system:                  # OpenCode's side call; not part of the scripted conversation
                    kind, payload = "text", "Title"
                else:
                    up.turns = getattr(up, "turns", -1) + 1
                    kind, payload = up.script(up.turns, body)
                chunks = []
                base = {"id": "c1", "object": "chat.completion.chunk", "model": body["model"]}
                if kind == "tool":
                    calls = [{"index": i, "id": "call_%d_%d" % (len(up.requests), i), "type": "function",
                              "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(payload)]
                    chunks.append(dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "tool_calls": calls}, "finish_reason": None}]))
                    chunks.append(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]))
                else:
                    chunks.append(dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": payload}, "finish_reason": None}]))
                    chunks.append(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]))
                chunks.append(dict(base, choices=[], usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}))
                data = "".join("data: %s\n\n" % json.dumps(c) for c in chunks) + "data: [DONE]\n\n"
                self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
                self.wfile.write(data.encode())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = "127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


class FakeResponses:
    """Same idea for the OpenAI Responses API that Codex speaks (/v1/responses, SSE events)."""

    def __init__(self, script):
        self.script, self.requests, self.keys, self.turns = script, [], [], -1
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                up.requests.append((self.path, body)); up.keys.append(self.headers.get("authorization"))
                up.turns += 1
                kind, payload = up.script(up.turns, body)
                events = [{"type": "response.created", "response": {"id": "resp_%d" % up.turns}}]
                if kind == "tool":
                    for i, (name, args) in enumerate(payload):
                        events.append({"type": "response.output_item.done", "output_index": i, "item": {
                            "type": "function_call", "id": "fc_%d_%d" % (up.turns, i), "call_id": "call_%d_%d" % (up.turns, i),
                            "name": name, "arguments": json.dumps(args)}})
                else:
                    events.append({"type": "response.output_item.done", "output_index": 0, "item": {
                        "type": "message", "role": "assistant", "id": "m_%d" % up.turns, "content": [{"type": "output_text", "text": payload}]}})
                events.append({"type": "response.completed", "response": {"id": "resp_%d" % up.turns, "model": body.get("model"), "usage": {
                    "input_tokens": 120, "output_tokens": 30, "total_tokens": 150, "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0}}}})
                data = "".join("event: %s\ndata: %s\n\n" % (e["type"], json.dumps(e)) for e in events).encode()
                self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = "127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()
