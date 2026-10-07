#!/usr/bin/env python3
"""A stand-in for the `claude` CLI: same flags in, stream-json out, and it asks the --permission-prompt-tool MCP server like the real one.
Behavior comes from the FAKE_CLAUDE environment variable (JSON): {"steps": [...], "final": "text", "exit": 0}
steps: {"write": [path, content]} | {"ask": [tool, input]} (call the approval tool; on allow, do the write if given) | {"sleep": s}
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


def mcp_client(cfg):
    spec = cfg["mcpServers"]["door"]
    p = subprocess.Popen([spec["command"]] + spec["args"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(method, params=None, mid=1, note=False):
        msg = {"jsonrpc": "2.0", "method": method, **({} if note else {"id": mid}), **({"params": params} if params is not None else {})}
        p.stdin.write(json.dumps(msg) + "\n"); p.stdin.flush()
        return None if note else json.loads(p.stdout.readline())
    rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "fake-claude", "version": "0"}})
    rpc("notifications/initialized", note=True)
    return p, rpc


def main(argv):
    args = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            args[argv[i]] = argv[i + 1]; i += 2
        else:
            args[argv[i]] = True; i += 1
    script = json.load(open(os.environ["FAKE_CLAUDE_FILE"])) if os.environ.get("FAKE_CLAUDE_FILE") else json.loads(os.environ.get("FAKE_CLAUDE", "{}"))
    with open(os.environ.get("FAKE_CLAUDE_LOG", os.devnull), "a") as log:
        log.write(json.dumps({"argv": argv[1:], "cwd": os.getcwd(), "env_keys": sorted(k for k in os.environ if "KEY" in k or "TOKEN" in k or k.startswith("DOOR"))}) + "\n")
    emit({"type": "system", "subtype": "init"})
    proc = rpc = None
    if "--mcp-config" in args and "--permission-prompt-tool" in args:
        proc, rpc = mcp_client(json.loads(args["--mcp-config"]))
    for n, step in enumerate(script.get("steps", [])):
        if "sleep" in step:
            time.sleep(step["sleep"])
        if "ask" in step:
            tool, inp = step["ask"]
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": tool, "input": inp}]}})
            reply = rpc("tools/call", {"name": "approve", "arguments": {"tool_name": tool, "input": inp, "tool_use_id": "t%d" % n}}, mid=10 + n)
            decision = json.loads(reply["result"]["content"][0]["text"])
            emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": decision.get("message", "ok")}]}})
            if decision["behavior"] != "allow":
                continue
        if "write" in step:
            path, content = step["write"]
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": path, "content": content}}]}})
            Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(content)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": script.get("final", "Done.")}]}})
    emit({"type": "result", "subtype": "success", "is_error": bool(script.get("error")), "result": script.get("final", "Done.")})
    if proc:
        proc.stdin.close(); proc.wait(5)
    sys.exit(script.get("exit", 0))


if __name__ == "__main__":
    main(sys.argv)
