#!/usr/bin/env python3
"""Shared Claude/Codex/Grok lifecycle handler for SessionStart, UserPromptSubmit, and Stop."""
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
BACKEND = os.environ.get("MYPEOPLE_BACKEND", "claude")
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
    cur["backend"] = BACKEND
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


def grok_transcript(tp, sid):
    """Grok's transcriptPath points at updates.jsonl (chunked JSON-RPC); the clean
    one-line-per-message log is chat_history.jsonl beside it."""
    if tp:
        cand = os.path.join(os.path.dirname(tp), "chat_history.jsonl")
        if os.path.exists(cand):
            return cand
    if sid:
        root = os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok")
        for f in glob.glob(os.path.join(root, "sessions", "**", sid, "chat_history.jsonl"),
                           recursive=True):
            return f
    return None


def find_transcript():
    tp = DATA.get("transcript_path")
    sid = DATA.get("session_id")
    if BACKEND == "grok":
        return grok_transcript(tp, sid)
    if tp and os.path.exists(tp):
        return tp
    if sid and BACKEND == "claude":
        for f in glob.glob(os.path.expanduser("~/.claude/projects/**/%s.jsonl" % sid), recursive=True):
            return f
    if sid and BACKEND == "codex":
        for f in glob.glob(os.path.expanduser("~/.codex/sessions/**/*%s.jsonl" % sid), recursive=True):
            return f
    return None


def content_text(content):
    """Last text out of a content field: a bare string (grok) or a block list (claude)."""
    if isinstance(content, str):
        return content
    text = ""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "") or text
    return text


def _flatten(text):
    """One line, whole thing. The 280-char cap that used to be here cut the summary
    mid-sentence -- eng-550 received a completion notice ending "...would report their
    sibling" (271 chars of a 280 cap) and had to ask for the rest (card 5676f76673).

    Newlines are still collapsed to spaces, deliberately: the notification is consumed
    line-wise (verify.sh greps "AGENT NOTIFICATION.*<agent>" on one captured line), so a
    multi-line summary would break that grep. Flattening loses no content; the cap did.
    """
    return " ".join(text.strip().split())


def last_assistant_summary():
    """Read the transcript, return the last assistant text (retry ~4x/0.5s for the flush race)."""
    last = DATA.get("last_assistant_message")
    if isinstance(last, str) and last.strip():
        return _flatten(last)
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
                            # claude nests blocks under .message.content[]; grok puts the
                            # reply text (or blocks) directly in .content
                            msg = ev.get("message", {})
                            text = (content_text(msg.get("content"))
                                    or content_text(ev.get("content")) or text)
                        elif ev.get("role") == "assistant" and isinstance(ev.get("content"), str):
                            text = ev["content"] or text
                if text:
                    return _flatten(text)
            except Exception:
                pass
        time.sleep(0.5)
    return ""


def notify_completion(summary):
    if not (QUEUE_URL and SECRET and C):
        return
    target = C.claim_notification_route(AGENT_ID) or BOSS_ID
    if not target:
        return
    msg = "[AGENT NOTIFICATION] %s finished: %s" % (AGENT_ID, summary or "(no summary)")
    C.http_json("POST", QUEUE_URL + "/task/submit",
                {"type": "send", "target_agent": target, "payload": {"message": msg}},
                {"X-Queue-Secret": SECRET}, timeout=6)


def normalize(d):
    """Grok emits camelCase payload keys; map them onto the snake_case names read here."""
    for cam, snake in (("sessionId", "session_id"), ("transcriptPath", "transcript_path")):
        if cam in d and snake not in d:
            d[snake] = d[cam]
    return d


def main():
    global DATA
    raw = sys.stdin.read()
    try:
        DATA = json.loads(raw) if raw.strip() else {}
    except Exception:
        DATA = {}
    if isinstance(DATA, dict):
        normalize(DATA)
    else:
        DATA = {}
    event = sys.argv[1] if len(sys.argv) > 1 else DATA.get("hook_event_name", "")

    if event == "SessionStart":
        # Persist session_id always. Do NOT force status back to "starting" when the agent
        # is already working/idle/blocked: Claude Code re-fires SessionStart after turns
        # (observed 2026-07-14 on card 157dcb7c75), which used to clobber healthy state and
        # make the fleet look stuck at "starting" forever until the next UserPromptSubmit.
        cur = read_status(AGENT_ID)
        prev = cur.get("status") or ""
        if prev in ("working", "idle", "blocked"):
            set_status(AGENT_ID, prev)
        else:
            set_status(AGENT_ID, "starting")
    elif event == "UserPromptSubmit":
        set_status(AGENT_ID, "working")   # status-file only; NOTHING to stdout
    elif event == "Stop":
        summary = last_assistant_summary()
        set_status(AGENT_ID, "idle", summary=summary)
        notify_completion(summary)


DATA = {}
if __name__ == "__main__":
    main()
