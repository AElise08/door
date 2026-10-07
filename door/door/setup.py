"""`door-host init`: writes the policy file for a new install from a few answers, so an installer never has to edit JSON by hand."""
import json
import os
import subprocess
from pathlib import Path

ACCESS = ("opencode", "claude-login", "api-key")


class SetupError(ValueError):
    pass


def build_policy(repo, alias="desk", access="opencode", tasks=False, description=None):
    repo = Path(repo).expanduser().resolve()
    if access not in ACCESS:
        raise SetupError("access must be one of: " + ", ".join(ACCESS))
    if not (repo / ".git").exists():
        raise SetupError("%s is not a git repository (Door shares committed files only)" % repo)
    if subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"], capture_output=True).returncode != 0:
        raise SetupError("%s has no commits yet: commit something first" % repo)
    if not alias.replace("-", "").isalnum() or len(alias) > 32:
        raise SetupError("the agent name must be letters, digits and dashes (32 at most)")
    agent = {"alias": alias, "description": description or "Answers questions about %s." % repo.name, "max_capability": "ask",
             "instructions": "You are answering a guest of the owner, not the owner. Answer only from the files you can read. If the answer is not in them, say so.",
             "exports": [{"name": repo.name or alias, "repo": str(repo), "ref": "HEAD",
                          "exclude": ["**/.env*", "**/*.pem", "**/*.key", "**/secrets/**"]}]}
    policy = {"version": 1, "agent": agent,
              "sandbox": {"kind": "container", "image": "door-runner:0.3", "cpus": 2, "memory_mb": 2048, "timeout_s": 600},
              "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10, "guest_daily_tokens": 400000,
                         "monthly_budget": 50.0, "currency": "USD"},
              "outbound": {"max_reply_chars": 1500, "hold_threshold": 1}}
    if access == "opencode":
        agent.update(backend="opencode", model="deepseek-v4.1-flash")
        policy["egress"] = {"provider": "opencode-go", "credential_source": "opencode-auth",
                            "pricing": {"input_per_mtok": 0.15, "output_per_mtok": 0.6}}
    elif access == "claude-login":
        agent.update(backend="claude", model="claude-sonnet-5-5")
        policy["egress"] = {"mode": "login"}
    else:
        agent.update(backend="claude", model="claude-sonnet-5-5")
        policy["egress"] = {"provider": "anthropic"}
    if tasks:
        agent["act"] = {"project": str(repo), "model": "sonnet", "bash": "ask", "timeout_s": 900, "max_turns": 20, "approval_timeout_s": 300,
                        "proof": {"commands": ["git status --short"], "timeout_s": 120}}
    return policy


def write_policy(path, policy, force=False):
    """Returns False (and touches nothing) when the file already exists: an install never overwrites the owner's settings."""
    path = Path(path)
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(policy, f, indent=2)
    os.replace(tmp, path)
    return True
