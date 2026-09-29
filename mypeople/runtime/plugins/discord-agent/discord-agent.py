#!/usr/bin/env python3
"""Discord agent plugin: builders ask questions in the owner's Discord and the agent this plugin
owns answers them there, on its own. Never through the Boss.

Same shape as instagram-comments: plugin on means its agent is up -- its own tmux session on this
Mac, on the Mac's Claude login -- and every message is pasted into that agent's tab as

    [DISCORD] msg=<id> channel=<id> from=<name>: <text>

The agent decides whether it is a question it can answer (see agent/CLAUDE.md) and writes its
answer as a file in the outbox: <msg>.txt (the answer) or <msg>.escalate (the question, for a
human). A file, not a shell command: answer text with a $ or a backtick is not shell to anyone. It never holds the bot token: this plugin posts for it, and only after the
guards below, because anyone in the channel can try to steer it.

Guards (here, in code, not in the prompt):
  - only to a message this plugin delivered, only in a listed channel, and once per message;
  - at most DISCORD_MAX_PER_HOUR posts, and DISCORD_MIN_GAP seconds apart;
  - nothing that looks like a token, a local path or a private repo; no @pings; under 1500 chars;
  - an escalation posts one fixed line and hands the question to the Boss (it is his to answer).
The agent itself is locked by Claude's dontAsk mode + an allow-list (write files into the outbox, read its
public knowledge): the lock holds because everything else is refused, not because the agent behaves.
Kill switch: touch $STATE_DIR/OFF -- nothing is delivered or posted until it is removed.

Unattended, so every way it can go quiet reaches the Boss as a "[discord escalation]" line (each kind
at most once an hour): the plugin cannot start (e.g. a dead bot token), passes keep failing (401s,
network, a post Discord refuses), the agent stops taking messages or keeps restarting, the hourly cap
is hit, or the agent tries to post something the guards block.

Config (env, or the file MYPEOPLE_CONFIG_PATH names, default ~/.config/mypeople/queue.env):

    DISCORD_AGENT=1
    DISCORD_BOT_TOKEN=...              # bot in the server, Message Content intent on
    DISCORD_CHANNEL_IDS=123,456        # channels or threads it reads and answers in
    DISCORD_AGENT_MODEL=claude-opus-5-5   # optional

    discord-agent.py serve     read, deliver, post forever (what systemd runs)
    discord-agent.py status    cursor per channel, outbox, whether the agent is up
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

INSTALL = Path(os.environ.get("INSTALL_DIR") or os.environ.get("MYPEOPLE_HOME")
               or Path.home() / ".local/share/mypeople")
STATE_DIR = Path(os.environ.get("DISCORD_AGENT_STATE_DIR") or INSTALL / "state" / "discord-agent")
STATE = STATE_DIR / "state.json"       # {"cursor": {channel: id}, "delivered": {msg: channel}, "answered": [...], "posts": [ts]}
OUTBOX = STATE_DIR / "outbox"          # the only thing the agent can hand us
PENDING = STATE_DIR / "pending"        # claimed from the outbox; the agent cannot write here
OFF = STATE_DIR / "OFF"
API = "https://discord.com/api/v10"
AGENT_DIR = Path(__file__).resolve().parent / "agent"
MP_BIN = os.environ.get("MP_BIN") or str(INSTALL / "bin" / "mp")
BOSS = os.environ.get("BOSS_AGENT") or "%s/main:Boss" % (os.environ.get("HOST_ID") or os.uname().nodename.split(".")[0])
POLL = 5
# What the agent may say, fetched fresh at every build: public pages only.
KNOWLEDGE = {
    "publish-page.txt": "https://aiworthusing.com/agent-index/publish",
    "plow-agents-README.md": "https://raw.githubusercontent.com/plow-pbc/plow-agents/main/README.md",
    "agent-index-client-README.md": "https://raw.githubusercontent.com/plow-pbc/agent-index-client/main/README.md",
}
ESCALATED = "Good question. A human from the team will answer this one here."
# Built from pieces so this file does not trip the check it implements.
PRIVATE_REPO = "plow-pbc/" + "plow"
SECRETISH = re.compile(r"[A-Za-z0-9_\-.]{40,}|(^|\s)(/Users/|/home/|~/)|" + re.escape(PRIVATE_REPO) + r"(?![\w-])"
                       r"|github\.com/delattre1/", re.I)


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%S ") + "[discord-agent] " + msg, flush=True)


def cfg(key, default=""):
    if os.environ.get(key):
        return os.environ[key]
    path = Path(os.environ.get("MYPEOPLE_CONFIG_PATH") or Path.home() / ".config/mypeople/queue.env")
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?%s=(.*)" % re.escape(key), line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def channels():
    return [c.strip() for c in cfg("DISCORD_CHANNEL_IDS").split(",") if c.strip()]


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(st):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, STATE)


def api(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Bot " + cfg("DISCORD_BOT_TOKEN"))
    req.add_header("User-Agent", "DiscordBot (https://github.com/delattre1/mypeople, 1)")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"null")


# ---------------------------------------------------------------- the agent this plugin owns
AGENT = STATE_DIR / "agent"            # its whole world: rules and public knowledge
SESSION = "discord-agent"              # its own tmux session, outside the fleet's
STARTS = []


def tmux(*args, stdin=None):
    return subprocess.run(["tmux", *args], input=stdin, capture_output=True, text=True)


def prepare_agent():
    """Write the agent's directory fresh: rules, today's public pages, and the allow-list that is
    the lock. Claude runs in dontAsk mode, so anything not listed here is refused -- no shell but
    writing into the outbox, no reads outside knowledge/, no MCP servers (the owner's Mac tools stay out)."""
    (AGENT / "knowledge").mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    PENDING.mkdir(parents=True, exist_ok=True)
    for name, url in KNOWLEDGE.items():
        raw = urllib.request.urlopen(url, timeout=30).read().decode("utf-8", "replace")
        if name.endswith(".txt"):   # the page is HTML; keep its words
            raw = re.sub(r"\s+", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", raw, flags=re.S))
        # The page's own address is part of the answer ("where do I publish?").
        (AGENT / "knowledge" / name).write_text("Source (public, safe to link): %s\n\n%s" % (url, raw))
    text = (AGENT_DIR / "CLAUDE.md").read_text().replace("{{AGENT}}", str(AGENT)).replace("{{OUTBOX}}", str(OUTBOX))
    (AGENT / "CLAUDE.md").write_text(text)
    # File writes are Edit rules, and an absolute path takes a leading "//" (a single "/" is
    # relative to this settings file) -- get either wrong and every answer is refused.
    (AGENT / "settings.json").write_text(json.dumps({"permissions": {"allow": [
        "Edit(/%s/**)" % OUTBOX, "Read(/%s/knowledge/**)" % AGENT]}}))
    (AGENT / "mcp.json").write_text('{"mcpServers": {}}')


def ensure_agent():
    """Plugin on means its agent is up. True once the Claude session takes input."""
    if tmux("has-session", "-t", SESSION).returncode:
        log("starting agent")
        STARTS.append(time.time())
        if len([s for s in STARTS if s > time.time() - 3600]) > 3:
            alert("agent-restarting", "its agent has had to be restarted more than 3 times this hour")
        prepare_agent()
        cmd = ("claude --permission-mode dontAsk --settings {a}/settings.json --strict-mcp-config "
               "--mcp-config {a}/mcp.json --append-system-prompt-file {a}/CLAUDE.md --model {m}").format(
                   a=shlex.quote(str(AGENT)), m=shlex.quote(cfg("DISCORD_AGENT_MODEL", "claude-opus-5-5")))
        tmux("new-session", "-d", "-s", SESSION, "-n", "agent", "-c", str(AGENT), "-x", "200", "-y", "50",
             "while true; do %s; sleep 2; done" % cmd)
        return False
    pane = tmux("capture-pane", "-p", "-t", SESSION + ":agent").stdout
    return "\u276f" in pane or "? for shortcuts" in pane


def deliver(text):
    if not ensure_agent():
        return False
    tmux("load-buffer", "-b", "dc", "-", stdin=text)
    tmux("paste-buffer", "-d", "-b", "dc", "-t", SESSION + ":agent")
    time.sleep(0.5)   # let the paste land before Enter, or Claude takes it as a newline
    tmux("send-keys", "-t", SESSION + ":agent", "Enter")
    return True


# ---------------------------------------------------------------- inbound
def poll_channel(ch, st, me):
    """Deliver new human messages in one channel. First sight of a channel records its newest
    message and delivers nothing, so turning this on never answers the backlog."""
    cur = st.setdefault("cursor", {})
    if ch not in cur:
        newest = api("GET", "/channels/%s/messages?limit=1" % ch) or []
        cur[ch] = newest[0]["id"] if newest else "0"
        return
    msgs = sorted(api("GET", "/channels/%s/messages?after=%s&limit=50" % (ch, cur[ch])) or [],
                  key=lambda m: int(m["id"]))
    for m in msgs:
        a = m.get("author") or {}
        text = (m.get("content") or "").strip()
        if text and not a.get("bot") and a.get("id") != me:
            who = a.get("global_name") or a.get("username") or "someone"
            line = "[DISCORD] msg=%s channel=%s from=%s: %s" % (m["id"], ch, who, text.replace("\n", " "))
            if not deliver(line):
                # cursor stays: this message is retried on the next pass
                since = st.setdefault("undelivered_since", time.time())
                if time.time() - since > 300:
                    alert("agent-down", "its agent has not taken a message for 5 minutes")
                return
            st.pop("undelivered_since", None)
            st.setdefault("delivered", {})[m["id"]] = ch
        cur[ch] = m["id"]


# ---------------------------------------------------------------- outbound, guarded
def alert(kind, text, now=None):
    """Tell the Boss this public-facing agent is failing; at most once an hour per kind."""
    now = now or time.time()
    path = STATE_DIR / "alerts.json"
    try:
        sent = json.loads(path.read_text())
    except (OSError, ValueError):
        sent = {}
    if kind in sent and now - sent[kind] < 3600:
        return
    sent[kind] = now
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sent))
    log("alerting the Boss: %s: %s" % (kind, text))
    subprocess.run([sys.executable, MP_BIN, "send", BOSS,
                    "[discord escalation] the Discord agent needs a look (%s): %s. Off switch: touch %s"
                    % (kind, text, OFF)], capture_output=True, timeout=60)


def refuse(item, why):
    log("refused %s: %s" % (item.get("reply_to"), why))
    if why == "hourly cap":
        alert("cap", "it hit its hourly cap, so builders are going unanswered")
    elif "secret" in why:
        alert("blocked-post", "it tried to post something that looked like a secret, path or private "
                              "repo in reply to message %s; the post was blocked" % item.get("reply_to"))
    return why


def post(item, st, now=None):
    """Post one outbox item if every guard passes; return None when posted, else the reason."""
    now = now or time.time()
    msg = str(item.get("reply_to") or "")
    ch = st.get("delivered", {}).get(msg)
    if not ch or ch not in channels():
        return refuse(item, "not a message we delivered in a listed channel")
    if msg in st.setdefault("answered", []):
        return refuse(item, "already answered")
    escalate = bool(item.get("escalate"))
    text = ESCALATED if escalate else str(item.get("text") or "").strip()
    if not text or len(text) > 1500:
        return refuse(item, "empty or too long")
    if SECRETISH.search(text):
        return refuse(item, "looks like a secret, a path or a private repo")
    posts = [t for t in st.setdefault("posts", []) if t > now - 3600]
    if len(posts) >= int(cfg("DISCORD_MAX_PER_HOUR", "20")):
        return refuse(item, "hourly cap")
    if posts and now - posts[-1] < int(cfg("DISCORD_MIN_GAP", "10")):
        return "wait"     # not refused: retried next pass
    api("POST", "/channels/%s/messages" % ch,
        {"content": text, "allowed_mentions": {"parse": []},
         "message_reference": {"message_id": msg, "channel_id": ch, "fail_if_not_exists": False}})
    st["answered"] = (st["answered"] + [msg])[-2000:]
    st["posts"] = posts + [now]
    log("answered %s in %s%s" % (msg, ch, " (escalated)" if escalate else ""))
    if escalate:   # the question is the owner's to answer: hand it to the Boss
        q = str(item.get("question") or "")[:500]
        subprocess.run([sys.executable, MP_BIN, "send", BOSS,
                        "[discord escalation] a builder asked in channel %s (msg %s), the Discord agent "
                        "told them a human will answer: %s" % (ch, msg, q)], capture_output=True, timeout=60)
    return None


def outbox_item(f):
    """<msg>.txt is an answer, <msg>.escalate a question for a human; anything else is dropped."""
    if not re.fullmatch(r"\d+\.(txt|escalate)", f.name):
        return None
    body = f.read_text(errors="replace").strip()
    if f.suffix == ".escalate":
        return {"reply_to": f.stem, "escalate": True, "question": body}
    return {"reply_to": f.stem, "text": body}


def claim_outbox(st):
    """Move each new answer out of the agent's reach at once. The agent's Write tool replaces a
    file it never read, so a reply left in the outbox could be silently swapped; claimed, a second
    answer to the same message is refused instead (one answer per message)."""
    PENDING.mkdir(parents=True, exist_ok=True)
    for f in sorted(OUTBOX.iterdir(), key=lambda f: f.stat().st_mtime):
        item = outbox_item(f)
        if item and item["reply_to"] not in st.get("answered", []) and not list(PENDING.glob(item["reply_to"] + ".*")):
            os.replace(f, PENDING / f.name)
        else:
            if item:
                refuse(item, "a second answer to the same message")
            f.unlink(missing_ok=True)


def drain_outbox(st):
    claim_outbox(st)
    for f in sorted(PENDING.iterdir(), key=lambda f: f.stat().st_mtime):
        why = post(outbox_item(f), st)
        if why == "wait":
            return
        f.unlink(missing_ok=True)


def serve():
    try:
        me = api("GET", "/users/@me")["id"]
    except Exception as e:   # a dead token or no network: supervise.sh restarts us, the Boss hears it
        alert("cannot-start", "it cannot reach Discord as its bot (%s)" % e)
        raise
    OUTBOX.mkdir(parents=True, exist_ok=True)   # before the first pass: claiming reads it
    PENDING.mkdir(parents=True, exist_ok=True)
    ensure_agent()                              # plugin on means its agent is up, not on first message
    log("up, reading %s" % ", ".join(channels()))
    failures = 0
    while True:
        try:
            if not OFF.exists():
                st = read_state()
                for ch in channels():
                    poll_channel(ch, st, me)
                drain_outbox(st)
                write_state(st)
            failures = 0
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as e:
            failures += 1
            log("pass failed: %s" % e)
            if failures >= 3:
                alert("failing", "%d passes in a row failed, last: %s" % (failures, e))
        time.sleep(POLL)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "serve":
        serve()
    elif cmd == "status":
        st = read_state()
        print(json.dumps({"off": OFF.exists(), "channels": channels(), "cursor": st.get("cursor"),
                          "answered": len(st.get("answered", [])),
                          "outbox": sorted(f.name for f in OUTBOX.iterdir()) if OUTBOX.exists() else [],
                          "agent": "up" if not tmux("has-session", "-t", SESSION).returncode else "down"},
                         indent=2))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
