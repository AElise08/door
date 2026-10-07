"""Act mode: a trusted guest's task is done by Claude Code on the owner's computer, in a throwaway copy of the project.

Safety, in layers:
  1. The agent works in a git worktree on a new branch (door/...). The owner's real folder is never touched; nothing is pushed or merged.
  2. Reading and editing INSIDE that copy is free. Anything else is decided by judge(): dangerous or secret-touching actions are always
     refused; commands the owner pre-allowed run; everything else waits for the owner (no answer = no).
  3. --restricted removes Bash/WebFetch unless Door names them and makes Claude ignore user/project settings files (hooks, broad permissions).
After the run Door collects evidence itself (diff, the owner's proof commands) so "done" can be checked instead of believed.
"""
import json
import os
import re
import shlex
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .common import ulid

APPROVAL_MCP = Path(__file__).with_name("approval_mcp.py")
SHELL_META = re.compile(r"[;&|<>`$\n\\]|\$\(")
SECRET_PATH = re.compile(r"(^|/)(\.env(\..*)?|id_[a-z0-9]+|[^/]*\.pem|[^/]*\.key|\.netrc|\.npmrc|\.pypirc|credentials[^/]*|\.aws|\.ssh|\.gnupg|\.kube)(/|$)", re.I)
DANGEROUS = re.compile(
    r"(\bsudo\b|\bsu\s+-?\w*|\bssh\b|\bscp\b|\bsftp\b|\bnc\b|\bncat\b|\bgit\s+(push|remote|config|credential)\b|"
    r"(curl|wget)\b[^\n]*\|\s*(sh|bash|zsh)\b|\brm\s+-[a-z]*r[a-z]*\s+(/|~|\$HOME|\.\.)|\bchmod\s+-R\b|\bchown\b|\bdd\s+if=|\bmkfs\b|"
    r":\(\)\s*\{|\bcrontab\b|\blaunchctl\b|\bdocker\b|\bnpm\s+(publish|login|token)\b|\btwine\b|\bsecurity\s+(find|dump)|\bkill(all)?\b|\bpkill\b|"
    r"\bosascript\b|\bdefaults\s+write\b)", re.I)
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _inside(path, root: Path) -> bool:
    try:
        p = Path(os.path.expanduser(str(path)))
        p = (root / p) if not p.is_absolute() else p
        p = p.resolve()
        return p == root or root in p.parents
    except (OSError, ValueError):
        return False


def _paths_in(inp: dict):
    return [v for k, v in (inp or {}).items() if k in ("file_path", "path", "notebook_path", "directory") and isinstance(v, str)]


def judge(tool: str, inp: dict, worktree: Path, allow_commands, bash: str):
    """-> ("allow" | "deny" | "ask", reason). Called for every action Claude was not already allowed or forbidden to do."""
    root = worktree.resolve()
    paths = _paths_in(inp)
    if any(SECRET_PATH.search(str(p)) for p in paths):
        return "deny", "That file may hold secrets."
    if tool in READ_TOOLS:
        return ("allow", "") if all(_inside(p, root) for p in paths) else ("ask", "Read outside the project copy")
    if tool in WRITE_TOOLS:
        if not paths or not all(_inside(p, root) for p in paths):
            return "deny", "Files outside the project copy can never be changed."
        if any(".git" in Path(os.path.expanduser(p)).parts for p in paths):
            return "deny", "The repository's own data cannot be edited."
        return "allow", ""
    if tool == "Bash":
        cmd = str((inp or {}).get("command", ""))
        if bash == "off":
            return "deny", "Running commands is not enabled."
        if DANGEROUS.search(cmd):
            return "deny", "That command is too risky to run."
        if not SHELL_META.search(cmd) and any(cmd == c or cmd.startswith(c + " ") for c in allow_commands):
            return "allow", ""
        return "ask", "Run: " + " ".join(cmd.split())[:200]
    return "ask", "%s %s" % (tool, json.dumps(inp or {}, ensure_ascii=False)[:160])


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            req = json.loads(self.rfile.readline(1 << 20))
            out = self.server.runner.permission(req)
        except Exception:
            out = {"behavior": "deny", "message": "Door could not decide, so this was not allowed."}
        self.wfile.write((json.dumps(out) + "\n").encode())


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def git(cwd, *args, check=True, timeout=60):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args[0], (r.stderr or r.stdout).strip()[:300]))
    return r


SAFE_ENV = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "TMPDIR", "TZ",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"}


def clean_env():
    """Claude and the proof commands run as the owner, but get only these basics: never Door's keys, a model API key, an ssh agent or
    any other secret that happens to be in the owner's shell. (An allow-list: a new variable is blocked until someone adds it here.)"""
    return {k: v for k, v in os.environ.items() if k in SAFE_ENV}


class ActRunner:
    def __init__(self, rid, cfg, state_dir, claude_bin="claude", approval_timeout=600):
        self.rid, self.cfg, self.state_dir = rid, cfg, Path(state_dir)
        self.claude_bin, self.approval_timeout = claude_bin, approval_timeout
        self.repo = Path(os.path.expanduser(cfg["project"]))
        self.worktree = self.state_dir / "worktrees" / rid
        self.branch = "door/" + rid.lower()[-10:]
        self._pending, self._lock, self._proc = {}, threading.Lock(), None
        self.cancelled, self.log = False, []
        self.on_event = lambda *a: None

    def env(self):
        """The basics plus whatever variables the OWNER named in act.env (for example NODE_ENV). Nothing else is inherited."""
        return dict(clean_env(), **{str(k): str(v) for k, v in (self.cfg.get("env") or {}).items()})

    # ---- approvals ----
    def pending_actions(self):
        with self._lock:
            return [{"id": a["id"], "tool": a["tool"], "summary": a["summary"], "at": a["at"]} for a in self._pending.values() if a["decision"] is None]

    def decide(self, action_id, decision):
        with self._lock:
            a = self._pending.get(action_id)
            if not a or a["decision"] is not None:
                return False
            a["decision"] = "allow" if decision == "allow" else "deny"
        a["event"].set()
        return True

    def permission(self, req):
        tool, inp = str(req.get("tool_name", "")), req.get("input") or {}
        verdict, why = judge(tool, inp, self.worktree, self.cfg.get("allow_commands", []), self.cfg.get("bash", "ask"))
        self.on_event("act_permission", {"tool": tool, "verdict": verdict, "why": why})
        if verdict == "allow":
            return {"behavior": "allow"}
        if verdict == "deny":
            return {"behavior": "deny", "message": why}
        a = {"id": "a_" + ulid().lower()[-8:], "tool": tool, "summary": why, "at": time.time(), "decision": None, "event": threading.Event()}
        with self._lock:
            self._pending[a["id"]] = a
        self.on_event("act_waiting", {"action": a["id"], "tool": tool})
        a["event"].wait(self.approval_timeout)
        with self._lock:
            decision = a["decision"] or "deny"
            a["decision"] = decision
        if self.cancelled:
            return {"behavior": "deny", "message": "The task was canceled."}
        return {"behavior": "allow"} if decision == "allow" else {"behavior": "deny", "message": "The owner did not allow this action."}

    def cancel(self):
        self.cancelled = True
        with self._lock:
            for a in self._pending.values():
                if a["decision"] is None:
                    a["decision"] = "deny"
                    a["event"].set()
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except OSError:
                pass

    # ---- the run ----
    def command(self, prompt, sock_path):
        bash = self.cfg.get("bash", "ask")
        tools = ["Read", "Grep", "Glob", "Edit", "Write"] + (["Bash"] if bash != "off" else [])
        allowed = ["Read", "Grep", "Glob", "Edit", "Write"]
        for c in self.cfg.get("allow_commands", []):
            allowed += ["Bash(%s)" % c, "Bash(%s *)" % c]
        denied = ["Read(**/.env*)", "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(**/*.pem)", "Read(**/*.key)", "Edit(**/.env*)", "Write(**/.env*)",
                  "Bash(git push *)", "Bash(sudo *)", "Bash(ssh *)", "Bash(curl *)", "Bash(wget *)", "Bash(rm -rf *)"]
        mcp = {"mcpServers": {"door": {"command": sys.executable, "args": [str(APPROVAL_MCP), sock_path]}}}
        return [self.claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                "--model", self.cfg["model"], "--restricted", "--tools", ",".join(tools), "--permission-mode", "default",
                "--permission-prompt-tool", "mcp__door__approve", "--mcp-config", json.dumps(mcp), "--strict-mcp-config",
                "--allowedTools", ",".join(allowed), "--disallowedTools", ",".join(denied), "--max-turns", str(self.cfg.get("max_turns", 30))]

    def run(self, prompt, title):
        out = {"summary": "", "changed_files": [], "diffstat": "", "diff": "", "branch": None, "commands_run": [], "proof": [],
               "timed_out": False, "cancelled": False, "error": None, "turns": 0}
        sockdir = Path(tempfile.mkdtemp(prefix="door-"))
        os.chmod(sockdir, 0o700)
        sock = str(sockdir / "a.sock")
        server = None
        try:
            git(self.repo, "rev-parse", "--verify", "HEAD")
            self.worktree.parent.mkdir(parents=True, exist_ok=True)
            git(self.repo, "worktree", "add", "-q", "-b", self.branch, str(self.worktree), "HEAD")
            base = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
            server = _Server(sock, _Handler)
            server.runner = self
            threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
            self._proc = subprocess.Popen(self.command(prompt, sock), cwd=self.worktree, env=self.env(), stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, start_new_session=True)
            timer = threading.Timer(self.cfg.get("timeout_s", 900), lambda: (out.__setitem__("timed_out", True), self.cancel()))
            timer.start()
            last_text, result_text = "", None
            for line in self._proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "assistant":
                    for part in (ev.get("message") or {}).get("content", []):
                        if part.get("type") == "text":
                            last_text = part.get("text", "")
                        elif part.get("type") == "tool_use":
                            out["turns"] += 1
                            if part.get("name") == "Bash":
                                out["commands_run"].append(str((part.get("input") or {}).get("command", ""))[:300])
                elif ev.get("type") == "result":
                    result_text = ev.get("result") if isinstance(ev.get("result"), str) else None
                    if ev.get("is_error"):
                        out["error"] = str(ev.get("result") or "the agent reported an error")[:300]
            self._proc.wait()
            self._proc.stdout.close()
            timer.cancel()
            out["summary"] = (result_text if result_text is not None else last_text or "").strip()
            out["cancelled"] = self.cancelled and not out["timed_out"]
            if self._proc.returncode not in (0, None) and not out["summary"] and not out["error"]:
                out["error"] = "the agent stopped with exit code %s" % self._proc.returncode
            # Evidence, collected by Door and not by the agent.
            git(self.worktree, "add", "-A")
            if git(self.worktree, "status", "--porcelain").stdout.strip():
                git(self.worktree, "-c", "user.name=Door", "-c", "user.email=door@localhost", "commit", "-q", "--no-verify", "-m", "door: " + title[:70])
            out["changed_files"] = [f for f in git(self.worktree, "diff", "--name-only", base, "HEAD").stdout.splitlines() if f][:200]
            out["diffstat"] = git(self.worktree, "diff", "--stat", base, "HEAD").stdout.strip()[-1500:]
            out["diff"] = git(self.worktree, "diff", base, "HEAD").stdout[:14000]
            out["branch"] = self.branch if out["changed_files"] else None
            if out["changed_files"] and not out["cancelled"] and not out["timed_out"]:
                out["proof"] = self.proof()
        except Exception as e:
            out["error"] = ("%s: %s" % (type(e).__name__, e))[:300]
        finally:
            if server:
                server.shutdown(); server.server_close()
            shutil.rmtree(sockdir, ignore_errors=True)
            try:
                git(self.repo, "worktree", "remove", "--force", str(self.worktree), check=False)
                if not out["branch"]:
                    git(self.repo, "branch", "-D", self.branch, check=False)
            except Exception:
                pass
            shutil.rmtree(self.worktree, ignore_errors=True)
        return out

    def proof(self):
        """The owner's own checks (tests, linters), run by Door in the changed copy. The model cannot pick, change or skip them."""
        pr = self.cfg.get("proof") or {}
        results = []
        for cmd in pr.get("commands", []):
            try:
                r = subprocess.run(shlex.split(cmd), cwd=self.worktree, env=self.env(), capture_output=True, text=True,
                                   timeout=pr.get("timeout_s", 300), stdin=subprocess.DEVNULL)
                results.append({"cmd": cmd, "rc": r.returncode, "tail": ((r.stdout or "") + (r.stderr or "")).strip()[-1200:]})
            except subprocess.TimeoutExpired:
                results.append({"cmd": cmd, "rc": None, "tail": "timed out"})
            except OSError as e:
                results.append({"cmd": cmd, "rc": None, "tail": "could not run: %s" % type(e).__name__})
        return results


def verdict(run: dict, verifier) -> str:
    """verified | checks_passed | failed_checks | no_changes | unverified | incomplete.
    A task is only "done" when something really changed, the owner's checks passed, and (when it ran) the independent check agrees."""
    if run["timed_out"] or run["cancelled"] or run["error"]:
        return "incomplete"
    if not run["changed_files"]:
        return "no_changes"
    ran = bool(run["proof"])
    if ran and any(p["rc"] != 0 for p in run["proof"]):
        return "failed_checks"
    if verifier == "NOT_VERIFIED":
        return "unverified"
    if verifier == "VERIFIED":
        return "verified"
    return "checks_passed" if ran else "unverified"


DONE_VERDICTS = {"verified", "checks_passed"}
