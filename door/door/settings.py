"""Settings the owner changes from "Door on this computer": which projects, tasks and their permissions, the model, the budget.

Only the Mac itself can change these (the cloud never can): the folder the agent may touch is the most sensitive setting there is.
Every change is checked by the same rules the daemon uses (policy.load) before it is written; the previous file is kept as door.json.bak."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .policy import PROVIDERS, PolicyError, load

# How the agent pays for the model, in the owner's words -> what the policy needs.
ACCESS = {
    "opencode":     {"label": "The key OpenCode keeps on this Mac (OpenCode Go)", "backend": "opencode", "model": "deepseek-v4.1-flash",
                     "egress": {"provider": "opencode-go", "credential_source": "opencode-auth", "pricing": {"input_per_mtok": 0.15, "output_per_mtok": 0.6}}},
    "claude-login": {"label": "My Claude account (sign in)", "backend": "claude", "model": "claude-sonnet-5-5", "egress": {"mode": "login"}},
    "anthropic":    {"label": "An Anthropic API key", "backend": "claude", "model": "claude-sonnet-5-5", "egress": {"provider": "anthropic"}},
    "openai":       {"label": "An OpenAI API key", "backend": "opencode", "model": "gpt-5.1-mini", "egress": {"provider": "openai"}},
    "openrouter":   {"label": "An OpenRouter API key", "backend": "opencode", "model": "deepseek/deepseek-v4.1", "egress": {"provider": "openrouter"}},
    "deepseek":     {"label": "A DeepSeek API key", "backend": "opencode", "model": "deepseek-v4.1-flash", "egress": {"provider": "deepseek"}},
}
KEYCHAIN = {"anthropic": "door-anthropic-api-key", "openai": "door-openai-api-key", "openrouter": "door-openrouter-api-key",
            "deepseek": "door-deepseek-api-key"}


class SettingsError(ValueError):
    pass


def _agent(raw):
    if "agents" in raw:
        return raw["agents"][0]
    return raw["agent"]


def _access_of(raw):
    eg = raw.get("egress") or {}
    if eg.get("mode") == "login":
        return "claude-login"
    if eg.get("credential_source") == "opencode-auth":
        return "opencode"
    return eg.get("provider", "anthropic")


def view(policy_path, state_dir, redact=False):
    """What the settings are. `redact=True` is what leaves this Mac for the cloud panel: project NAMES only, never folder paths."""
    raw = json.loads(Path(policy_path).read_text())
    a = _agent(raw)
    act = a.get("act") or {}
    access = _access_of(raw)
    by_path = {str(Path(os.path.expanduser(e["repo"])).resolve()): e.get("name") for e in a.get("exports", [])}
    task_path = str(Path(os.path.expanduser(act["project"])).resolve()) if act.get("project") else None
    out = {
        "agent": a.get("alias", "desk"),
        "projects": [({"name": e.get("name")} if redact else {"name": e.get("name"), "path": e.get("repo")}) for e in a.get("exports", [])],
        "tasks": {"enabled": bool(act), "project": by_path.get(task_path) if redact else act.get("project"), "project_name": by_path.get(task_path),
                  "bash": act.get("bash", "ask"), "open_on_mac": act.get("open_on_mac", "ask"), "owner_steps": act.get("owner_steps", "auto"),
                  "allow_commands": act.get("allow_commands", []), "checks": (act.get("proof") or {}).get("commands", [])},
        "model": {"access": access, "model": a.get("model", ""), "choices": [{"id": k, "label": v["label"], "model": v["model"]} for k, v in ACCESS.items()],
                  "keychain_item": KEYCHAIN.get(access)},
        "budget": (raw.get("limits") or {}).get("monthly_budget", 50.0),
        "changes_go_to": "a new branch named door/<id> inside the task project; your working folder is never changed",
    }
    return out


def _git_project(path):
    p = Path(os.path.expanduser(str(path or "").strip())).resolve()
    if not p.is_dir():
        raise SettingsError("That folder does not exist: %s" % p)
    if not (p / ".git").exists():
        raise SettingsError("%s is not a git repository. Door shares and changes only committed files, so it needs git." % p)
    if subprocess.run(["git", "-C", str(p), "rev-parse", "--verify", "HEAD"], capture_output=True).returncode != 0:
        raise SettingsError("%s has no commits yet. Commit something first." % p)
    home = Path.home().resolve()
    if p == home or p == Path("/") or p in (home / "Library", home / "Desktop", home / "Documents"):
        raise SettingsError("Choose the project folder itself, not a whole personal folder.")
    return p


def _clean_cmds(cmds, limit, what):
    from .act import SHELL_META
    out = [" ".join(str(c).split()) for c in (cmds or []) if str(c).strip()]
    if len(out) > limit or any(SHELL_META.search(c) or len(c) > 200 for c in out):
        raise SettingsError("%s: up to %d plain commands, no ; | & < > $ or backticks" % (what, limit))
    return out


def apply(policy_path, state_dir, change):
    """change = {"op": ..., ...}. Returns the new view. Raises SettingsError with a sentence the owner can act on."""
    policy_path, state_dir = Path(policy_path), Path(state_dir)
    raw = json.loads(policy_path.read_text())
    a = _agent(raw)
    op = change.get("op")
    restart = False
    if op == "project.add":
        p = _git_project(change.get("path"))
        names = {e.get("name") for e in a["exports"]}
        if any(Path(os.path.expanduser(e["repo"])).resolve() == p for e in a["exports"]):
            raise SettingsError("That project is already shared.")
        if len(a["exports"]) >= 10:
            raise SettingsError("Up to 10 projects.")
        name, n = p.name, 2
        while name in names:
            name, n = "%s-%d" % (p.name, n), n + 1
        a["exports"].append({"name": name, "repo": str(p), "ref": "HEAD", "exclude": ["**/.env*", "**/*.pem", "**/*.key", "**/secrets/**"]})
        if len(a["exports"]) == 1 or a.get("description", "").startswith("Answers questions about"):
            a["description"] = "Answers questions about %s." % ", ".join(e["name"] for e in a["exports"])
    elif op == "project.remove":
        keep = [e for e in a["exports"] if e.get("name") != change.get("name")]
        if len(keep) == len(a["exports"]):
            raise SettingsError("No project with that name.")
        if not keep:
            raise SettingsError("Keep at least one project: people need something to ask about.")
        gone = next(e for e in a["exports"] if e.get("name") == change.get("name"))
        if a.get("act") and Path(os.path.expanduser(a["act"]["project"])).resolve() == Path(os.path.expanduser(gone["repo"])).resolve():
            raise SettingsError("Tasks work on this project. Choose another project for tasks first, or turn tasks off.")
        a["exports"] = keep
        if a.get("description", "").startswith("Answers questions about"):
            a["description"] = "Answers questions about %s." % ", ".join(e["name"] for e in keep)
    elif op == "tasks.set":
        if not change.get("enabled"):
            a.pop("act", None)
        else:
            if change.get("project_name"):                       # the cloud panel only knows names: resolve one of the shared projects
                match = [e for e in a["exports"] if e.get("name") == change["project_name"]]
                if not match:
                    raise SettingsError("No shared project has that name.")
                change = dict(change, project=match[0]["repo"])
            proj = _git_project(change.get("project"))
            if not any(Path(os.path.expanduser(e["repo"])).resolve() == proj for e in a["exports"]):
                raise SettingsError("Tasks can only work on one of the shared projects. Add it under Projects first.")
            act = dict(a.get("act") or {"model": "sonnet", "timeout_s": 900, "max_turns": 20, "approval_timeout_s": 300})
            act["project"] = str(proj)
            if change.get("bash") is not None:
                act["bash"] = change["bash"]
            if change.get("open_on_mac") is not None:
                act["open_on_mac"] = change["open_on_mac"]
            if change.get("owner_steps") is not None:
                act["owner_steps"] = change["owner_steps"]
            if change.get("allow_commands") is not None:
                act["allow_commands"] = _clean_cmds(change["allow_commands"], 20, "Commands that run without asking")
            if change.get("checks") is not None:
                act["proof"] = dict(act.get("proof") or {"timeout_s": 300}, commands=_clean_cmds(change["checks"], 10, "Checks"))
            act.setdefault("proof", {"commands": ["git status --short"], "timeout_s": 120})
            a["act"] = act
    elif op == "model.set":
        access = change.get("access")
        if access not in ACCESS:
            raise SettingsError("Unknown choice.")
        preset = ACCESS[access]
        model = str(change.get("model") or preset["model"]).strip()
        if not model or len(model) > 80 or any(ch.isspace() for ch in model):
            raise SettingsError("Write the model name without spaces, for example %s." % preset["model"])
        a["backend"], a["model"] = preset["backend"], model
        raw["egress"] = json.loads(json.dumps(preset["egress"]))
        restart = True
    elif op == "budget.set":
        try:
            b = float(change.get("monthly"))
        except (TypeError, ValueError):
            raise SettingsError("Write the monthly budget as a number, in US dollars.")
        if not 1 <= b <= 10000:
            raise SettingsError("The monthly budget must be between 1 and 10000 US dollars.")
        raw.setdefault("limits", {})["monthly_budget"] = round(b, 2)
    else:
        raise SettingsError("Unknown change.")
    _write_checked(policy_path, state_dir, raw)
    out = view(policy_path, state_dir)
    out["restart_needed"] = restart
    return out


def _write_checked(policy_path, state_dir, raw):
    """Validate with the daemon's own rules on a copy, then replace the file atomically (0600) and keep the previous one."""
    fd, tmp = tempfile.mkstemp(dir=str(policy_path.parent), prefix=".door-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(raw, f, indent=2)
        os.chmod(tmp, 0o600)
        try:
            load(Path(tmp), state_dir)
        except PolicyError as e:
            raise SettingsError(str(e))
        if policy_path.exists():
            shutil.copy2(policy_path, str(policy_path) + ".bak")
            os.chmod(str(policy_path) + ".bak", 0o600)
        os.replace(tmp, policy_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def folders(path):
    """Sub-folders of `path` for the folder picker. Only inside the owner's home folder, no hidden folders, and each says whether it is a git project."""
    home = Path.home().resolve()
    try:
        p = Path(os.path.expanduser(str(path or "~"))).resolve()
    except (OSError, RuntimeError):
        p = home
    if p != home and home not in p.parents or not p.is_dir():
        p = home
    dirs = []
    try:
        for d in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if d.name.startswith(".") or d.name in ("Library", "node_modules") or not d.is_dir():
                continue
            dirs.append({"name": d.name, "git": (d / ".git").exists()})
            if len(dirs) >= 300:
                break
    except OSError:
        pass
    return {"path": str(p), "home": str(home), "parent": str(p.parent) if p != home else None, "git": (p / ".git").exists(), "dirs": dirs}


def terminal_script(kind, policy_path, state_dir, door_host):
    """The one command a button may open in Terminal (a fixed list: signing in, or storing a key). Returns (file name, script text)."""
    import shlex
    if kind == "login:claude":
        cmd = "%s --policy %s --state %s login claude" % (shlex.quote(str(door_host)), shlex.quote(str(policy_path)), shlex.quote(str(state_dir)))
        title = "Sign in to Claude for Door"
    elif kind.startswith("keychain:") and kind[9:] in KEYCHAIN.values():
        cmd = 'security add-generic-password -U -a "$USER" -s %s -w' % shlex.quote(kind[9:])
        title = "Store the key in the macOS Keychain (it asks for the key without showing it)"
    else:
        raise SettingsError("Unknown action.")
    return ("door-" + kind.replace(":", "-") + ".command",
            "#!/bin/bash\nclear\necho %s\necho\n%s\necho\nread -r -p 'Done. Press Enter to close this window.' _\n" % (shlex.quote(title), cmd))
