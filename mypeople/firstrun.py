"""First-run entrypoint — REPLACES seed hydration with configuration only (never code-gen).

ensure() is idempotent: safe on every `up` / container restart. It materializes a writable
INSTALL_DIR from the packaged runtime, resolves the recipient's Claude auth, writes the single
config file (~/.config/mypeople/queue.env, fresh QUEUE_SECRET per install), wires Claude-Code
trust + the Boss lifecycle hook, and installs the functional tmux.conf. Starting daemons +
spawning the Boss is the CLI's job (see cli.up)."""
import os, sys, json, shutil, secrets, socket, subprocess

def _config_path():
    explicit = os.environ.get("MYPEOPLE_CONFIG_PATH")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    home = os.environ.get("MYPEOPLE_HOME")
    if home:
        return os.path.join(os.path.abspath(os.path.expanduser(home)), "config", "queue.env")
    return os.path.expanduser("~/.config/mypeople/queue.env")


CONFIG_PATH = _config_path()
CONFIG_DIR = os.path.dirname(CONFIG_PATH)


def runtime_dir():
    """Absolute path to the packaged runtime tree (bin/, plugins/, verify/, ...)."""
    try:
        from importlib.resources import files
        return str(files("mypeople") / "runtime")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")


def install_dir():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("MYPEOPLE_HOME") or "~/.local/share/mypeople"))


def _echo(msg):
    sys.stderr.write(msg + "\n")


# ---------------------------------------------------------------- step 1: materialize
def materialize(install):
    """Copy the packaged runtime into a WRITABLE INSTALL_DIR. Idempotent: never overwrite
    existing daemon code differently, and NEVER clobber live state (board/roster/logs)."""
    rt = runtime_dir()
    os.makedirs(install, exist_ok=True)
    # code trees: refresh from the package so upgrades take effect (state dirs excluded below).
    for sub in ("bin", "plugins", "plans", "verify", "config"):
        src = os.path.join(rt, sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(install, sub), dirs_exist_ok=True)
    # Boss doctrine file
    bc = os.path.join(rt, "boss-CLAUDE.md")
    if os.path.exists(bc):
        shutil.copy2(bc, os.path.join(install, "boss-CLAUDE.md"))
    # writable state skeletons — create empty, never overwrite existing board/roster/logs
    for sub in ("todos", "run", "status", "logs"):
        os.makedirs(os.path.join(install, sub), exist_ok=True)
    # make scripts executable (package-data can lose the bit on some backends)
    bindir = os.path.join(install, "bin")
    for f in os.listdir(bindir):
        p = os.path.join(bindir, f)
        if f.endswith((".py", ".sh")) or f in ("mp", "board-restore"):
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
    for f in ("emit-event.sh",):
        p = os.path.join(install, "plugins", "tmux-boss-hooks", f)
        if os.path.exists(p):
            os.chmod(p, 0o755)
    vs = os.path.join(install, "verify", "verify.sh")
    if os.path.exists(vs):
        os.chmod(vs, 0o755)


# ---------------------------------------------------------------- step 2: auth
def resolve_auth():
    """Require this node's own completed Claude device login.

    Authentication is an operator step. MyPeople never copies, mounts, mints, or reuses a Claude
    credential/token from another node.
    """
    if shutil.which("claude"):
        try:
            r = subprocess.run(["claude", "auth", "status"], capture_output=True,
                               text=True, timeout=15)
            logged_in = False
            try:
                logged_in = bool(json.loads(r.stdout).get("loggedIn"))
            except Exception:
                normalized = "".join(ch for ch in (r.stdout + r.stderr).lower() if ch.isalnum())
                logged_in = "loggedintrue" in normalized or "loginmethod" in normalized
            if r.returncode == 0 and logged_in:
                return True, "claude-login", "this node's claude auth status: logged in"
        except Exception:
            pass
    return (False, "none",
            "This node is not authenticated. Run `claude auth login` inside THIS node, then "
            "re-run MyPeople. Never copy or mount a credential/token from another node.")


# ---------------------------------------------------------------- step 3: queue.env
def write_queue_env(install):
    """Write the single config file if absent. Idempotent — reuse keeps the same
    QUEUE_SECRET/HOST_ID across restarts so board/sessions persist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        return False
    host = os.environ.get("HOST_ID") or socket.gethostname().split(".")[0]
    kv = {
        "INSTALL_DIR": install,
        "HOST_ID": host,
        "QUEUE_SECRET": secrets.token_hex(24),          # FRESH per install; never baked
        "HUD_PORT": os.environ.get("HUD_PORT", "9900"),
        "TODO_PORT": os.environ.get("TODO_PORT", "9933"),
        "TTYD_PORT": os.environ.get("TTYD_PORT", "7681"),
        "BIND_ADDR": os.environ.get("BIND_ADDR", "0.0.0.0"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DEFAULT_ENG_MODEL": os.environ.get("DEFAULT_ENG_MODEL", "claude-opus-4-8"),
        "QUEUE_DEAD_AFTER": "45",
        "HEARTBEAT_INTERVAL": "10",
    }
    kv["QUEUE_URL"] = os.environ.get("QUEUE_URL", "http://127.0.0.1:%s" % kv["HUD_PORT"])
    lines = ["# mypeople runtime config — generated on first run (secrets here; never commit)"]
    lines += ['export %s="%s"' % (k, v) for k, v in kv.items()]
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    return True


# ---------------------------------------------------------------- step 4: claude trust + hook
def write_claude_config(install):
    """Claude-Code onboarding + folder-trust + the Boss lifecycle hook, pointed at THIS
    install's plugin path. Replaces seed Step 3."""
    # ~/.claude.json — onboarding + trust for install dir and the agent cwds
    cj = os.path.expanduser("~/.claude.json")
    d = {}
    if os.path.exists(cj):
        try:
            d = json.load(open(cj)) or {}
        except Exception:
            d = {}
    if not isinstance(d, dict):
        d = {}
    d["hasCompletedOnboarding"] = True
    proj = d.setdefault("projects", {})
    for path in {os.path.expanduser("~"), install, os.path.join(install, "run"),
                 os.path.join(install, "run", "boss"), os.path.join(install, "run", "eng"),
                 os.path.join(install, "bin")}:
        rec = proj.get(path, {})
        rec["hasTrustDialogAccepted"] = True
        proj[path] = rec
    _atomic_json(cj, d)

    # ~/.claude/settings.json — the 5 lifecycle hooks + dangerous-mode precondition
    cs_dir = os.path.expanduser("~/.claude")
    os.makedirs(cs_dir, exist_ok=True)
    hook = os.path.join(install, "plugins", "tmux-boss-hooks", "emit-event.sh")
    def h(evt, matcher=""):
        return {"matcher": matcher, "hooks": [
            {"type": "command", "command": "%s %s" % (hook, evt)}]}
    settings_path = os.path.join(cs_dir, "settings.json")
    settings = {}
    if os.path.exists(settings_path):
        try:
            settings = json.load(open(settings_path)) or {}
        except Exception:
            settings = {}
    if not isinstance(settings, dict):
        settings = {}
    hooks = settings.setdefault("hooks", {})
    required = {
        "SessionStart": h("SessionStart"),
        "UserPromptSubmit": h("UserPromptSubmit"),
        "Stop": h("Stop"),
        "PreToolUse": h("PreToolUse", "AskUserQuestion"),
        "SessionEnd": h("SessionEnd"),
    }
    # Remove stale MyPeople hook paths from older installs before adding this install's hook.
    for event in required:
        kept = []
        for group in hooks.setdefault(event, []):
            commands = [x.get("command", "") for x in group.get("hooks", [])]
            if any("/plugins/tmux-boss-hooks/emit-event.sh" in cmd and hook not in cmd
                   for cmd in commands):
                continue
            kept.append(group)
        hooks[event] = kept
    for event, entry in required.items():
        current = hooks.setdefault(event, [])
        command = entry["hooks"][0]["command"]
        if not any(command == hook.get("command")
                   for group in current for hook in group.get("hooks", [])):
            current.append(entry)
    settings["skipDangerousModePermissionPrompt"] = True
    _atomic_json(settings_path, settings)


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- step 5: tmux.conf
def install_tmux_conf(install):
    """Install MyPeople's tmux settings as an include while preserving the user's config."""
    dst = os.path.expanduser("~/.tmux.conf")
    src = os.path.join(install, "config", "tmux.conf")
    include = os.path.join(CONFIG_DIR, "tmux.runtime.conf")
    if not os.path.exists(src):
        return
    os.makedirs(CONFIG_DIR, exist_ok=True)
    shutil.copy2(src, include)
    directive = "source-file %s" % include
    existing = ""
    if os.path.exists(dst):
        try:
            existing = open(dst).read()
        except Exception:
            existing = ""
    if directive not in existing:
        with open(dst, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n# MyPeople runtime settings\n%s\n" % directive)
    tpm = os.path.expanduser("~/.tmux/plugins/tpm")
    if not os.path.isdir(tpm) and shutil.which("git"):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/tmux-plugins/tpm", tpm],
                       capture_output=True, timeout=60)
    installer = os.path.join(tpm, "bin", "install_plugins")
    if os.path.exists(installer):
        subprocess.run([installer], capture_output=True, timeout=120)
    if shutil.which("tmux"):
        subprocess.run(["tmux", "source-file", dst], capture_output=True)


# ---------------------------------------------------------------- orchestration
def ensure():
    """Idempotent first-run configuration. Returns the resolved (install, host)."""
    install = install_dir()
    materialize(install)
    ok, mode, msg = resolve_auth()
    if not ok:
        _echo("\n[mypeople] " + msg + "\n")
        sys.exit(2)
    _echo("[mypeople] auth: %s" % msg)
    fresh = write_queue_env(install)
    write_claude_config(install)
    install_tmux_conf(install)
    host = os.environ.get("HOST_ID") or _read_env_val("HOST_ID") or socket.gethostname().split(".")[0]
    _echo("[mypeople] install dir: %s  (config: %s%s)" %
          (install, CONFIG_PATH, ", fresh" if fresh else ", reused"))
    return install, host


def _read_env_val(key):
    try:
        for line in open(CONFIG_PATH):
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith(key + "="):
                v = line.split("=", 1)[1].strip()
                return v[1:-1] if v[:1] in "\"'" else v
    except Exception:
        return None
    return None
