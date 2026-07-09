#!/usr/bin/env python3
"""mypeople hook handler. Reads the hook JSON on stdin, writes the agent's status file
(atomic, PID-unique temp), and on Stop routes an [AGENT NOTIFICATION] to the boss via
POST /task/submit {type:"send", ...}. Never prints to stdout (UserPromptSubmit stdout is
injected into the agent's context)."""
import os, sys, json, time, glob

INSTALL_DIR = os.environ.get("INSTALL_DIR", os.path.expanduser("~/mypeople"))
sys.path.insert(0, os.path.join(INSTALL_DIR, "bin"))
try:
    import mpcommon as C
except Exception:
    C = None

AGENT_ID = os.environ.get("AGENT_ID", "")
BOSS_ID = os.environ.get("BOSS_ID", "")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
SECRET = os.environ.get("QUEUE_SECRET", "")
STATUS_DIR = os.path.join(INSTALL_DIR, "status")
KEYWORDS = ["plan", "approve", "queue", "mp", "autonomous", "verify", "fire-and-forget"]


def parse_aid(aid):
    host = sess = tab = ""
    if "/" in aid:
        host, rest = aid.split("/", 1)
    else:
        rest = aid
    if ":" in rest:
        sess, tab = rest.split(":", 1)
    else:
        sess = rest
    return host, sess, tab


def status_path(aid):
    _, sess, tab = parse_aid(aid)
    return os.path.join(STATUS_DIR, "mc-%s" % sess, "%s.json" % tab)


def atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), int(time.time() * 1000))
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_status(aid):
    p = status_path(aid)
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def set_status(aid, status, summary=None):
    cur = read_status(aid)
    cur["status"] = status
    cur["timestamp"] = time.time()
    cur.setdefault("backend", "claude")
    cur["state"] = "alive"
    if "session_id" in DATA:
        cur["session_id"] = DATA.get("session_id")
    cur["boss_id"] = BOSS_ID
    if summary is not None:
        # a locked (doctrine) summary is NEVER clobbered by the Stop hook — it is keyword-bearing
        # by construction (§8, J2c/J39). Only unlocked summaries get updated from the transcript.
        if cur.get("summary_locked"):
            summary = cur.get("summary", summary)
        cur["summary"] = summary
    atomic_write(status_path(aid), cur)
    sid = DATA.get("session_id")
    if sid and C:
        roster_path = os.path.join(INSTALL_DIR, "run", "roster.json")
        roster = C.read_json(roster_path, {}) or {}
        if aid in roster and roster[aid].get("session_id") != sid:
            roster[aid]["session_id"] = sid
            C.write_json(roster_path, roster)


def find_transcript():
    tp = DATA.get("transcript_path")
    if tp and os.path.exists(tp):
        return tp
    sid = DATA.get("session_id")
    if sid:
        for f in glob.glob(os.path.expanduser("~/.claude/projects/**/%s.jsonl" % sid), recursive=True):
            return f
    return None


def last_assistant_summary():
    """Read the transcript, return the last assistant text (retry ~4x/0.5s for the flush race)."""
    for _ in range(4):
        tp = find_transcript()
        if tp:
            try:
                text = ""
                with open(tp) as f:
                    for line in f:
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if ev.get("type") == "assistant":
                            msg = ev.get("message", {})
                            for block in msg.get("content", []):
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "") or text
                        elif ev.get("role") == "assistant" and isinstance(ev.get("content"), str):
                            text = ev["content"] or text
                if text:
                    return text.strip().replace("\n", " ")[:280]
            except Exception:
                pass
        time.sleep(0.5)
    return ""


def notify_boss(summary):
    if not (BOSS_ID and QUEUE_URL and SECRET and C):
        return
    msg = "[AGENT NOTIFICATION] %s finished: %s" % (AGENT_ID, summary or "(no summary)")
    C.http_json("POST", QUEUE_URL + "/task/submit",
                {"type": "send", "target_agent": BOSS_ID, "payload": {"message": msg}},
                {"X-Queue-Secret": SECRET}, timeout=6)


def main():
    global DATA
    raw = sys.stdin.read()
    try:
        DATA = json.loads(raw) if raw.strip() else {}
    except Exception:
        DATA = {}
    event = sys.argv[1] if len(sys.argv) > 1 else DATA.get("hook_event_name", "")

    if event == "SessionStart":
        set_status(AGENT_ID, "starting")
    elif event == "UserPromptSubmit":
        set_status(AGENT_ID, "working")   # status-file only; NOTHING to stdout
    elif event == "PreToolUse":
        set_status(AGENT_ID, "blocked")
    elif event == "Stop":
        summary = last_assistant_summary()
        set_status(AGENT_ID, "idle", summary=summary)
        notify_boss(summary)
    elif event == "SessionEnd":
        set_status(AGENT_ID, "idle")


DATA = {}
if __name__ == "__main__":
    main()
