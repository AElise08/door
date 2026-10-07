#!/usr/bin/env python3
"""Tiny MCP server (stdio) that Claude Code asks before it does anything not already allowed (--permission-prompt-tool).

It forwards each request to the Door host over a Unix socket and returns the host's decision. If the host cannot be reached, the answer is
always DENY. Standard library only: it runs with the same Python as door-host.
"""
import json
import socket
import sys

TOOL = {"name": "approve", "description": "Ask the Door owner whether this action may run.",
        "inputSchema": {"type": "object", "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                                                         "tool_use_id": {"type": "string"}}, "required": ["tool_name", "input"]}}


def ask_host(sock_path: str, payload: dict) -> dict:
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1800)
        s.connect(sock_path)
        s.sendall((json.dumps(payload) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf)
    except (OSError, ValueError):
        return {"behavior": "deny", "message": "The Door host could not be reached, so this action was not allowed."}


def handle(msg: dict, sock_path: str):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                                                        "capabilities": {"tools": {}}, "serverInfo": {"name": "door-approval", "version": "0.3"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        if p.get("name") != "approve":
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        a = p.get("arguments") or {}
        decision = ask_host(sock_path, {"tool_name": str(a.get("tool_name", "")), "input": a.get("input") or {}, "tool_use_id": str(a.get("tool_use_id", ""))})
        if decision.get("behavior") == "allow":
            body = {"behavior": "allow", "updatedInput": a.get("input") or {}}
        else:
            body = {"behavior": "deny", "message": str(decision.get("message") or "The owner did not allow this action.")}
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(body)}]}}
    if mid is not None:                                          # unknown request: answer with an error; notifications get no answer
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return None


def main(argv):
    sock_path = argv[1]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        out = handle(msg, sock_path)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv)
