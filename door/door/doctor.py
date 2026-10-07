"""`door-host doctor`: checks every link a working Door needs on this computer and says what to do about each one that is missing.
It never prints a key. Each check returns (level, name, detail): level is ok, warn (works, but look) or fail (will not work)."""
import os
import shlex
import shutil
import socket
import stat
import subprocess
from pathlib import Path

from .credentials import load_credential
from .policy import PolicyError, load

OK, WARN, FAIL = "ok", "warn", "fail"


def _tcp(host, port=443, timeout=5):
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False


def run(policy_path, state_dir, runtime=None, probe=_tcp):
    out = []
    add = lambda level, name, detail="": out.append((level, name, detail))
    # 1. the policy file
    try:
        pol = load(Path(policy_path), Path(state_dir))
    except PolicyError as e:
        add(FAIL, "Policy file", "%s (fix %s)" % (e, policy_path)); return out
    eg = pol["egress"]
    add(OK, "Policy file", "%d agent(s): %s" % (len(pol["agents"]), ", ".join("%s on %s" % (a["alias"], a["backend"]) for a in pol["agents"])))
    # 2. containers
    if runtime is None:
        from .sandbox import ContainerRuntime
        runtime = ContainerRuntime(pol["sandbox"].get("runtime", "docker"), pol["sandbox"]["image"])
    if not runtime.available():
        add(FAIL, "Docker", "not running. Start Docker Desktop (or your container engine) and run this again.")
    else:
        add(OK, "Docker", "running")
        r = subprocess.run([runtime.binary, "image", "inspect", pol["sandbox"]["image"]], capture_output=True)
        add(OK if r.returncode == 0 else FAIL, "Runner image %s" % pol["sandbox"]["image"],
            "present" if r.returncode == 0 else "missing. Build it: docker build -t %s runner/" % pol["sandbox"]["image"])
    # 3. how the model is paid for / signed in
    if eg.get("mode") == "login":
        for backend in sorted({a["backend"] for a in pol["agents"]}):
            try:
                ok, text = runtime.login_status(backend)
            except Exception:
                ok, text = False, "could not check"
            add(OK if ok else FAIL, "Sign-in for %s" % backend, "signed in" if ok else "not signed in. Run: door-host login %s" % backend)
    else:
        key = load_credential(eg)
        src = "OpenCode's saved key" if eg.get("credential_source") == "opencode-auth" else "variable %s" % eg["credential_env"]
        add(OK if key else FAIL, "Model API key (%s)" % eg["provider"], ("found in %s" % src) if key else
            ("missing. Set %s to a dedicated key with a spend limit%s" % (eg["credential_env"], "" if eg.get("credential_source") != "opencode-auth" else
                                                                      ", or sign in to the provider in OpenCode first")))
        host = eg["allow_hosts"][0]
        add(OK if probe(host) else WARN, "Reach %s" % host, "reachable" if probe(host) else "cannot connect from here (offline or blocked?)")
    # 4. tasks
    for a in pol["agents"]:
        act = a.get("act")
        if not act:
            continue
        name = "Tasks for %s" % a["alias"]
        problems = []
        if not shutil.which(act["claude_bin"]):
            problems.append("Claude Code (%s) is not installed on this computer" % act["claude_bin"])
        top = subprocess.run(["git", "-C", act["project"], "rev-parse", "--verify", "HEAD"], capture_output=True)
        if top.returncode != 0:
            problems.append("the project has no commits yet")
        for cmd in act["proof"]["commands"]:
            if not shutil.which(shlex.split(cmd)[0]):
                problems.append("check command not found: %s" % shlex.split(cmd)[0])
        if not act["proof"]["commands"]:
            add(WARN, name + ": checks", "no proof commands configured, so a finished task can never be called more than 'unverified'")
        add(FAIL if problems else OK, name, "; ".join(problems) if problems else "ready (works on a copy of the project; risky steps ask you)")
    # 5. this computer's own state
    sd = Path(state_dir)
    if sd.exists():
        mode = stat.S_IMODE(sd.stat().st_mode)
        add(OK if mode & 0o077 == 0 else FAIL, "State folder privacy", "private" if mode & 0o077 == 0 else "others can read %s: run chmod 700 on it" % sd)
        add(OK if (sd / "host.json").exists() else WARN, "Pairing", "paired with the cloud" if (sd / "host.json").exists()
            else "not paired yet. Run: door-host pair, then text the code to your Door number")
    else:
        add(WARN, "State folder", "does not exist yet (created when door-host first starts)")
    if shutil.which("git") is None:
        add(FAIL, "git", "not found; Door needs it to copy your project")
    return out


def render(results):
    mark = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}
    lines = ["%s  %s%s" % (mark[l], n, (": " + d) if d else "") for l, n, d in results]
    bad = sum(1 for l, _, _ in results if l == FAIL)
    lines.append("")
    lines.append("Everything needed is in place." if not bad else "%d thing(s) to fix before this will work." % bad)
    return "\n".join(lines), bad
