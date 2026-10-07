#!/usr/bin/env python3
"""One real, small task through the whole Door flow on this computer, with the REAL Claude Code (your own login on this Mac).

  .venv/bin/python scripts/try-task.py            # makes a tiny throwaway project, asks Claude to add a file, checks the delivery

What is real: Claude Code, git, the throwaway branch, the approval protocol, Door's own proof commands, and the independent checker (a real
model call through the container, using the OpenCode key already on this computer). What is not involved: the cloud, Plow, SMS.
Uses a small amount of your Claude usage. Everything it creates is deleted afterwards.
"""
import argparse, json, shutil, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from door.common import now, sha256_text, ulid          # noqa: E402
from door.credentials import load_credential            # noqa: E402
from door.envelope import encode, generate              # noqa: E402
from door.host import Host                              # noqa: E402
from door.sandbox import ContainerRuntime               # noqa: E402


def sh(*a, cwd=None): return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Create a file named HELLO.md in the project root containing exactly one line: Hello from Door")
    ap.add_argument("--model", default="haiku", help="Claude Code model alias (haiku is the cheapest)")
    ap.add_argument("--allow-bash", action="store_true", help="let the task ask to run commands (you will be asked in this terminal)")
    ap.add_argument("--no-checker", action="store_true", help="skip the independent checker (no OpenCode key needed)")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="door-task-"))
    host = None
    try:
        proj = tmp / "project"; proj.mkdir()
        sh("git", "init", "-q", cwd=proj)
        (proj / "README.md").write_text("# Tiny demo project\nA place to try Door.\n"); (proj / "app.py").write_text("print('hello')\n")
        sh("git", "add", "-A", cwd=proj); sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=proj)
        (proj / "my-unsaved-work.txt").write_text("this must still be here, untouched, at the end")
        pol = {"version": 1, "verification": {"mode": "off"}, "local_ui": {"enabled": False},
               "agent": {"alias": "dev", "backend": "opencode", "model": "deepseek-v4.1-flash", "exports": [{"name": "p", "repo": str(proj)}],
                         "act": {"project": str(proj), "model": a.model, "bash": "ask" if a.allow_bash else "off", "timeout_s": 240, "max_turns": 8,
                                 "approval_timeout_s": 120, "proof": {"commands": ["test -f HELLO.md"], "timeout_s": 30}}},
               "egress": {"provider": "opencode-go", "credential_source": "opencode-auth", "pricing": {"input_per_mtok": 0.15, "output_per_mtok": 0.6}}}
        cfg = tmp / "door.json"; cfg.write_text(json.dumps(pol))
        key = "" if a.no_checker else load_credential({"provider": "opencode-go", "credential_source": "opencode-auth", "credential_env": "X"})
        if not key and not a.no_checker:
            sys.exit("No OpenCode key found for the independent checker. Use --no-checker to skip it.")
        rt = ContainerRuntime("docker", "door-runner:0.3")
        if not a.no_checker:
            rt.pin_image(); rt.ensure_internal_network()
        host = Host(cfg, tmp / "state", rt, key); host.proxy.start()
        if not a.no_checker:
            rt.setup_network(host.proxy.port)
        priv, pub = generate(); host.pair_confirm(host.pair_start()["code"], pub)
        rid, text = ulid(), a.task
        req = {"request_id": rid, "guest_id": ulid(), "agent_alias": "dev", "capability": "act", "guest_level": "act", "text": text, "text_hash": sha256_text(text),
               "deadline_at": now() + 600, "approval": {"request_id": rid, "text_hash": sha256_text(text), "decision": "approve"}, "history": []}
        out = host.ask(*encode(priv, req))
        if not out.get("ok"):
            sys.exit("The Mac refused: %s" % out)
        print("Task sent to Claude Code (%s). Waiting; this takes a minute or two...\n" % a.model)
        t0 = time.time(); asked = set()
        while True:
            st = host.status(rid)
            for p in st.get("pending_actions", []):
                if p["id"] not in asked:
                    asked.add(p["id"]); ans = input("Claude wants to: %s\nAllow? [y/N] " % p["summary"]).strip().lower()
                    host.decide_action(rid, p["id"], "allow" if ans == "y" else "deny")
            if st.get("state") not in ("running", None):
                break
            time.sleep(1)
            if time.time() - t0 > 400: sys.exit("took too long")
        res = host.status(rid)
        print("state:", res.get("state"), res.get("reason", ""))
        rep = res.get("reply") or {}
        act = rep.get("act") or {}
        print("\n----- what the person would be told -----\n%s\n-----------------------------------------" % rep.get("text"))
        print("\nverdict:", act.get("verdict"), "| branch:", act.get("branch"), "| files:", act.get("files"))
        print("checks Door ran:", [(p["cmd"], "passed" if p["rc"] == 0 else "FAILED") for p in act.get("proof", [])])
        print("independent checker:", act.get("verifier"))
        print("commands Claude ran:", act.get("commands_run"))
        if act.get("branch"):
            print("\nwhat is on the branch:\n" + sh("git", "show", "--stat", "--format=%s", act["branch"], cwd=proj).strip())
            print("HELLO.md on the branch says:", sh("git", "show", "%s:HELLO.md" % act["branch"], cwd=proj).strip() if "HELLO.md" in (act.get("files") or []) else "(no HELLO.md)")
        print("\nyour real folder: HELLO.md exists there? ->", (proj / "HELLO.md").exists(), "| unsaved work intact? ->", (proj / "my-unsaved-work.txt").read_text().startswith("this must"))
        print("audit events:", sorted({e["event"] for e in host.audit.rows() if e["request_id"] == rid}))
    finally:
        if host:
            host.proxy.stop()
        subprocess.run(["docker", "rm", "-f", "door-relay"], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
