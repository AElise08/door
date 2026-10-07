#!/usr/bin/env python3
"""Local end-to-end try-out of Door: no SMS, no server. One question through the REAL container and a REAL model.

  DOOR_ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python scripts/try-it.py --repo ~/code/myproject "How does login work?"
  # OpenCode Go with the key OpenCode already keeps on this computer (no new key needed):
  .venv/bin/python scripts/try-it.py --provider opencode-go --backend opencode --model deepseek-v4.1-flash \\
      --pricing 0.15,0.6 --credential-source opencode-auth --repo ~/code/myproject "How does login work?"
  (two or more --repo: each becomes an agent and the Boss picks one)

It signs the request the way the cloud agent does, so the Mac side (re-check, export, container, proxy, filter) runs for real.
Uses a throwaway state folder and removes it afterwards. The key never enters the container.
"""
import argparse, json, os, shutil, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from door.common import now, sha256_text, ulid          # noqa: E402
from door.envelope import generate, encode              # noqa: E402
from door.host import Host                              # noqa: E402
from door.policy import load                            # noqa: E402
from door.sandbox import ContainerRuntime               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--repo", action="append", required=True, help="git repo to export (repeat for several agents)")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001", help="cheaper by default; e.g. claude-sonnet-5-5")
    ap.add_argument("--provider", default="anthropic", help="anthropic, opencode-go, openai, openrouter, deepseek")
    ap.add_argument("--backend", default="claude", help="claude, opencode or codex (must match the provider's format)")
    ap.add_argument("--pricing", help="input,output US$ per million tokens (required for non-Anthropic providers)")
    ap.add_argument("--login", action="store_true", help="use the engine's own sign-in (door-host login <engine>) instead of an API key")
    ap.add_argument("--history", help='earlier turns as JSON, e.g. \'[{"role":"guest","text":"..."},{"role":"agent","text":"..."}]\'')
    ap.add_argument("--scope", default="", help="topics the agent may answer about (it declines everything else)")
    ap.add_argument("--credential-source", default="env", choices=["env", "opencode-auth"])
    ap.add_argument("--budget", type=float, default=1.0, help="hard USD cap for this try-out")
    ap.add_argument("--dry", action="store_true", help="only validate the setup, no model call")
    a = ap.parse_args()
    egress = {"mode": "login"} if a.login else {"provider": a.provider, "credential_source": a.credential_source}
    if a.pricing:
        i, o = (float(x) for x in a.pricing.split(","))
        egress["pricing"] = {"input_per_mtok": i, "output_per_mtok": o}
    from door.credentials import load_credential
    from door.policy import PROVIDERS
    env_name = PROVIDERS.get(a.provider, {}).get("credential_env", "DOOR_API_KEY")
    key = "" if a.login else load_credential({"provider": a.provider, "credential_source": a.credential_source, "credential_env": env_name})
    if not key and not a.dry and not a.login:
        sys.exit("No API key found. Set %s (a dedicated key with a spend limit), or use --credential-source opencode-auth.\n"
                 "A subscription login is not an API key and is not used here." % env_name)
    tmp = Path(tempfile.mkdtemp(prefix="door-try-"))
    rt = ContainerRuntime("docker", "door-runner:0.3")
    host = None
    try:
        agents = []
        for p in a.repo:
            p = Path(p).expanduser().resolve()
            if not (p / ".git").exists():
                sys.exit("%s is not a git repository (Door exports committed files only)" % p)
            alias = "".join(c if c.isalnum() else "-" for c in p.name.lower())[:32] or "repo"
            agents.append({"alias": alias, "description": "Files of %s" % p.name, "model": a.model, "backend": a.backend, "scope": a.scope,
                           "exports": [{"name": alias, "repo": str(p)}]})
        pol_path = tmp / "cfg" / "door.json"; pol_path.parent.mkdir()
        pol_path.write_text(json.dumps({"version": 1, "agents": agents, "egress": egress,
                                        "limits": {"monthly_budget": a.budget, "max_turn_tokens": 150000, "guest_daily_tokens": 400000,
                                                   "guest_daily_requests": 10, "max_output_tokens": 1500, "currency": "USD"}}))
        load(pol_path, tmp / "state")
        print("policy ok: %d agent(s)%s" % (len(agents), ", Boss on" if len(agents) > 1 else ""))
        if not rt.available():
            sys.exit("Docker is not running.")
        rt.pin_image()
        if a.dry:
            print("dry run ok: Docker up, image present, policy valid. No model call made."); return
        host = Host(pol_path, tmp / "state", rt, key)
        host.proxy.start()
        rt.setup_network(host.proxy.port)
        private, public = generate()
        assert host.pair_confirm(host.pair_start()["code"], public)["ok"]
        rid, text = ulid(), a.question
        req = {"request_id": rid, "guest_id": ulid(), "agent_alias": "auto" if len(agents) > 1 else agents[0]["alias"], "capability": "ask",
               "text": text, "text_hash": sha256_text(text), "deadline_at": now() + 600,
               "history": json.loads(a.history) if a.history else [],
               "approval": {"request_id": rid, "text_hash": sha256_text(text), "decision": "approve", "decided_by": "try-it"}}
        out = host.ask(*encode(private, req))
        if not out.get("ok"):
            sys.exit("Mac refused: %s" % out)
        print("question sent, waiting for the container...")
        res = host.wait(rid, 600)
        print("\nstate: %s %s   agent: %s" % (res.get("state"), res.get("reason", ""), res.get("agent")))
        if res.get("reply"):
            r = res["reply"]
            print("held by filter:", r["held"])
            print("----- what the guest would receive -----\n%s\n----------------------------------------" % r["text"])
            if r["held"]:
                print("(held text, owner only):", r.get("held_text"))
        u = res.get("usage") or {}
        print("tokens: %s   cost: US$ %.4f   (cap US$ %.2f)" % (u.get("tokens"), u.get("cost", 0), a.budget))
    finally:
        if host:
            host.proxy.stop()
        os.system("docker rm -f door-relay >/dev/null 2>&1")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
