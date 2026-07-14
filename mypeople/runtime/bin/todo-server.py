#!/usr/bin/env python3
"""mypeople todo-server (:9933): board API + board->Boss ping.
Serves todos.html at / and /todos, the wall at /wall, reverse-proxies the HUD routes so the
cross-nav works from either front door. Python 3 stdlib only.
MODULE-LEVEL imports of every stdlib a handler uses (§5.3b UnboundLocalError guard)."""
import os, sys, json, time, uuid, threading, shutil, subprocess, glob, re
import urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpcommon as C
import boardstore as BS

CFG = C.CFG
INSTALL_DIR = CFG["INSTALL_DIR"]
HOST_ID = CFG["HOST_ID"]
HUD_PORT = int(CFG["HUD_PORT"])
TODO_PORT = int(CFG["TODO_PORT"])
SECRET = CFG.get("QUEUE_SECRET", "")
BOSS_AGENT = "%s/main:Boss" % HOST_ID
TODOS_DIR = os.path.join(INSTALL_DIR, "todos")
BOARD_PATH = os.path.join(TODOS_DIR, "board.v2.json")
PROOFS_DIR = os.path.join(TODOS_DIR, "proofs")
INBOX_LOG = os.path.join(TODOS_DIR, "boss-inbox.log")
HTML_DIR = os.path.dirname(os.path.abspath(__file__))
TODOS_HTML = os.path.join(HTML_DIR, "todos.html")
WALL_HTML = os.path.join(HTML_DIR, "wall.html")
STATUS_DIR = os.path.join(INSTALL_DIR, "status")

VALID_STATES = {"needs_brainstorm", "working", "review", "done", "blocked", "cancelled", "recurring"}
BOSS_BACKENDS = ("claude", "codex")
LOCK = threading.RLock()
START = time.time()


# ---------------- board store ----------------
BOARD_BACKEND = BS.select_backend(BOARD_PATH, C.CFG.get("BOARD_BACKEND"))


def _sqlite_path():
    return BS.db_path_for(BOARD_PATH)


def default_board():
    return {"version": 2, "order": [], "pinSeq": 0, "tasks": {}}


def load_board():
    if BOARD_BACKEND == "sqlite":
        return BS.load_board(_sqlite_path())
    b = C.read_json(BOARD_PATH, None)
    if not b or not isinstance(b, dict):
        return default_board()
    b.setdefault("order", [])
    b.setdefault("pinSeq", 0)
    b.setdefault("tasks", {})
    return b


def save_board(board):
    """Atomic save + rolling timestamped backup + catastrophic-shrink guard (§3).

    SQLite backend: atomic single-transaction row-per-card write (only changed cards), same
    catastrophic-shrink refusal; durable backups come from the decoupled board-exporter.
    """
    if BOARD_BACKEND == "sqlite":
        os.makedirs(TODOS_DIR, exist_ok=True)
        return BS.save_board(_sqlite_path(), board)
    os.makedirs(TODOS_DIR, exist_ok=True)
    ondisk = C.read_json(BOARD_PATH, None)
    new_n = len(board.get("tasks", {}))
    if ondisk and isinstance(ondisk, dict):
        old_n = len(ondisk.get("tasks", {}))
        if old_n > 5 and new_n < 0.5 * old_n:
            # refuse catastrophic shrink: write SUSPECT, keep the live board intact
            sp = "%s.SUSPECT.%d" % (BOARD_PATH, int(time.time()))
            C.atomic_write(sp, json.dumps(board, ensure_ascii=False).encode())
            sys.stderr.write("SUSPECT shrink refused: %d->%d, wrote %s\n" % (old_n, new_n, sp))
            return False
        # roll a backup of the current on-disk board before replacing
        try:
            bak = "%s.bak.%d" % (BOARD_PATH, int(time.time() * 1000))
            C.atomic_write(bak, json.dumps(ondisk, ensure_ascii=False).encode())
            baks = sorted(glob.glob("%s.bak.*" % BOARD_PATH))
            for old in baks[:-20]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass
    C.atomic_write(BOARD_PATH, json.dumps(board, ensure_ascii=False).encode())
    return True


def now():
    return time.time()


# ---------------- board->Boss ping ----------------
def mp_path():
    return shutil.which("mp") or os.path.join(INSTALL_DIR, "bin", "mp")


def mp_send(agent, message):
    mp = mp_path()
    try:
        r = subprocess.run([mp, "send", agent, message], capture_output=True, text=True, timeout=25)
        rc = r.returncode
    except Exception as e:
        rc = -1
        r = None
    try:
        with open(INBOX_LOG, "a") as f:
            f.write("MP_SEND -> %s rc=%s :: %s\n" % (agent, rc, message[:160]))
    except Exception:
        pass
    return rc


def ping_boss(message):
    threading.Thread(target=mp_send, args=(BOSS_AGENT, message), daemon=True).start()


def title_of(task):
    return (task.get("text", "") or "")[:60]


def emit_task_event(board, task, reason, by=None):
    """Ping Boss for a non-test add / work-state change. Exempt {test} tasks."""
    if task.get("test"):
        return
    tid = task["id"]
    task["pingsToBoss"] = task.get("pingsToBoss", 0) + 1
    ping_boss('[todo] task %s "%s": %s' % (tid, title_of(task), reason))


def emit_comment_event(board, task, by, bodytext):
    if task.get("test"):
        return
    tid = task["id"]
    # Boss ping: exempt only the Boss's own comment
    if by != BOSS_AGENT:
        task["pingsToBoss"] = task.get("pingsToBoss", 0) + 1
        ping_boss('[todo] comment on %s "%s" by %s: %s' % (tid, title_of(task), by, bodytext[:120]))


# ---------------- proof kind classification ----------------
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
VID_EXT = (".mp4", ".webm", ".mov", ".m4v")


def classify_kind(url=None, filename=None, content_type=None, given=None):
    name = (filename or url or "").lower().split("?")[0]
    ct = (content_type or "").lower()
    if ct.startswith("image/") or name.endswith(IMG_EXT):
        return "image"
    if ct.startswith("video/") or name.endswith(VID_EXT):
        return "video"
    if url and (url.startswith("http://") or url.startswith("https://") or url.startswith("/")):
        return "link" if (given in (None, "", "text", "link")) else given
    if given in ("image", "video", "link"):
        return given
    return "text"


def parse_multipart(handler, ctype):
    """Minimal multipart/form-data parser: returns (fields:dict, file:(filename,ctype,bytes)|None)."""
    m = re.search(r'boundary=("?)([^";]+)\1', ctype)
    if not m:
        return {}, None
    boundary = ("--" + m.group(2)).encode()
    n = int(handler.headers.get("Content-Length", 0) or 0)
    body = handler.rfile.read(n)
    fields = {}
    fileobj = None
    for part in body.split(boundary):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        data = data.rstrip(b"\r\n")
        htxt = head.decode("latin-1", "ignore")
        dm = re.search(r'name="([^"]+)"', htxt)
        fm = re.search(r'filename="([^"]*)"', htxt)
        cm = re.search(r'Content-Type:\s*([^\r\n]+)', htxt, re.I)
        nm = dm.group(1) if dm else "field"
        if fm and fm.group(1):
            fileobj = (fm.group(1), (cm.group(1).strip() if cm else ""), data)
        else:
            fields[nm] = data.decode("utf-8", "ignore")
    return fields, fileobj


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, ctype="application/json", raw=None, extra=None):
        if raw is None:
            raw = json.dumps(obj).encode("utf-8") if obj is not None else b""
        elif isinstance(raw, str):
            raw = raw.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _identity(self):
        return C.caller_identity(self.headers)

    def _page_extra(self):
        return {
            "Set-Cookie": "mp_session=%s; HttpOnly; Path=/; SameSite=Lax" % C.mint_session(),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0",
        }

    def _serve_page(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
            html = html.replace("__TTYD_PORT__", str(CFG["TTYD_BROWSER_PORT"]))
            html = html.replace("__HOST_ID__", HOST_ID)
        except Exception:
            html = "<h1>mypeople</h1>"
        self._send(200, raw=html, ctype="text/html; charset=utf-8", extra=self._page_extra())

    def do_HEAD(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/todos", "/wall"):
            self.send_response(200)
            for k, v in self._page_extra().items():
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if p == "/dashboard" or p.startswith("/dashboard/") or p in ("/agents", "/clients", "/roster"):
            return C.proxy_request(self, "127.0.0.1", HUD_PORT)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- GET ----
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/health":
            build = "0"
            try:
                build = str(int(os.path.getmtime(TODOS_HTML)))
            except Exception:
                pass
            return self._send(200, {"status": "ok", "build": build, "uptime": int(now() - START)})
        if p == "/favicon.ico":
            return self._send(204, raw=b"")
        if p in ("/", "/todos"):
            return self._serve_page(TODOS_HTML)
        if p == "/wall":
            return self._serve_page(WALL_HTML if os.path.exists(WALL_HTML) else TODOS_HTML)
        # HUD routes -> proxy to queue-server (symmetric front doors)
        if p == "/dashboard" or p.startswith("/dashboard/") or p in ("/agents", "/clients", "/roster"):
            return C.proxy_request(self, "127.0.0.1", HUD_PORT)
        # proof file serving (both new flat + legacy nested routes)
        if p.startswith("/todo/proof-file/"):
            ok, _ = self._identity()
            if not ok:
                return self._send(401, {"error": "unauthorized"})
            name = os.path.basename(p.split("/todo/proof-file/", 1)[1])
            fp = os.path.join(PROOFS_DIR, name)
            return self._serve_file(fp)
        if p.startswith("/todo/proof/"):
            ok, _ = self._identity()
            if not ok:
                return self._send(401, {"error": "unauthorized"})
            rest = p.split("/todo/proof/", 1)[1].split("/")
            if len(rest) >= 2:
                tid = os.path.basename(rest[0])
                fn = os.path.basename(rest[1])
                fp = os.path.join(PROOFS_DIR, tid, fn)
                return self._serve_file(fp)
        # gated json
        ok, ident = self._identity()
        if p == "/todo/board":
            if not ok:
                return self._send(401, {"error": "unauthorized"})
            with LOCK:
                return self._send(200, self._board_view())
        if p == "/todo/wall":
            if not ok:
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, self._wall_tiles())
        if p.startswith("/todo/attach"):
            if not ok:
                return self._send(401, {"error": "unauthorized"})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            agent = q.get("agent", [""])[0]
            code, agents = C.http_json("GET", CFG["QUEUE_URL"] + "/agents", None, {"X-Queue-Secret": SECRET})
            base = ""
            target = C.tmux_target(agent)
            for a in (agents or []):
                if a.get("agent_id") == agent:
                    base = a.get("attach_base", "")
                    target = a.get("tmux_target", target)
            return self._send(200, {"ok": True, "target": target, "base": base,
                                    "port": int(CFG["TTYD_BROWSER_PORT"])})
        return self._send(404, {"error": "not_found"})

    def _serve_file(self, fp):
        if not os.path.isfile(fp):
            return self._send(404, {"error": "no_file"})
        import mimetypes
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        with open(fp, "rb") as f:
            data = f.read()
        return self._send(200, raw=data, ctype=ctype)

    # ---- POST ----
    def do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/dashboard" or p in ("/agents", "/clients", "/roster", "/revive") or p.startswith("/task/"):
            return C.proxy_request(self, "127.0.0.1", HUD_PORT)
        ok, ident = self._identity()
        if not ok:
            return self._send(401, {"error": "unauthorized"})

        ctype = self.headers.get("Content-Type", "")
        if p == "/todo/proof" and ctype.startswith("multipart/form-data"):
            return self._proof_multipart()
        body = self._json_body()

        if p == "/todo/update":
            return self._update(body, ident)
        if p == "/todo/comment":
            return self._comment(body, ident)
        if p == "/todo/proof":
            return self._proof_json(body)
        if p == "/todo/status":
            return self._status_op(body, ident)
        if p == "/todo/boss":
            return self._boss_op(body, ident)
        return self._send(404, {"error": "not_found"})

    # ---- Boss lifecycle control (card 0cc0bde980) ----
    def _boss_alive(self):
        """Is the singleton Boss up? Heartbeat-driven, so it can lag reality by one interval; it
        is a UX guard, not the invariant. `mp spawn`'s own window_exists check is the real backstop
        and queue-client dispatches serially, so a stale yes/no here cannot produce two Bosses."""
        code, agents = C.http_json("GET", CFG["QUEUE_URL"] + "/agents", None,
                                   {"X-Queue-Secret": SECRET}, timeout=6)
        for a in (agents or []):
            if a.get("is_master") and a.get("state") == "alive":
                return True, a.get("agent_id", "")
        return False, ""

    def _boss_op(self, body, ident):
        """Kill / spawn / revive the Boss from the board UI.

        Adds NO new execution mechanism: every action rides the queue-server task path that
        queue-client's dispatch() already implements against `mp` (type=kill with --reason,
        type=spawn with --master --backend, type=revive). This endpoint only chooses the
        arguments and enforces the exactly-one-Boss guard.

        spawn vs revive: spawn starts a NEW Boss on a chosen engine; revive restores the SAME
        Boss, resuming its persisted session (its memory). Both require the Boss to be down.
        """
        action = (body.get("action") or "").strip().lower()
        alive, live_id = self._boss_alive()

        if action == "kill":
            if not alive:
                return self._send(409, {"ok": False, "error": "boss_not_alive"})
            # A non-accidental reason is what makes the kill stick: mp records it as durable intent
            # in roster.json and ensure-boss refuses to respawn against it.
            payload = {"reason": "ceo-kill:%d" % int(time.time())}
            target = live_id or BOSS_AGENT
        elif action == "spawn":
            backend = (body.get("backend") or "").strip().lower()
            if backend not in BOSS_BACKENDS:
                return self._send(400, {"ok": False, "error": "bad_backend",
                                        "detail": "choose %s" % ", ".join(BOSS_BACKENDS)})
            if alive:
                return self._send(409, {"ok": False, "error": "boss_already_alive",
                                        "agent_id": live_id,
                                        "detail": "kill the running Boss before spawning another"})
            payload = {"backend": backend, "is_master": True}
            target = BOSS_AGENT
        elif action == "revive":
            if alive:
                return self._send(409, {"ok": False, "error": "boss_already_alive",
                                        "agent_id": live_id,
                                        "detail": "the Boss is already up; nothing to revive"})
            payload = {}
            target = BOSS_AGENT
        else:
            return self._send(400, {"ok": False, "error": "bad_action",
                                    "detail": "choose kill, spawn or revive"})

        code, r = C.http_json("POST", CFG["QUEUE_URL"] + "/task/submit",
                              {"type": action, "target_agent": target, "payload": payload},
                              {"X-Queue-Secret": SECRET}, timeout=10)
        if code != 200 or not isinstance(r, dict) or not r.get("task_id"):
            return self._send(502, {"ok": False, "error": "submit_failed", "detail": str(r)[:200]})
        return self._send(200, {"ok": True, "action": action, "agent_id": target,
                                "task_id": r["task_id"], "by": ident})

    # ---- board view (server-authoritative ordering: pinned first by pinRank, then order) ----
    def _board_view(self):
        board = load_board()
        return board

    def _wall_tiles(self):
        code, agents = C.http_json("GET", CFG["QUEUE_URL"] + "/agents", None, {"X-Queue-Secret": SECRET})
        tiles = []
        for a in (agents or []):
            tiles.append({"agent_id": a["agent_id"], "state": a.get("status", "ready"),
                          "summary": a.get("summary", ""), "attach_url": a.get("attach_url", "")})
        # working-first sort
        order = {"working": 0, "blocked": 1, "ready": 2, "idle": 3}
        tiles.sort(key=lambda t: order.get(t["state"], 5))
        return {"tiles": tiles}

    # ---- update op ----
    def _update(self, body, ident):
        op = body.get("op")
        with LOCK:
            board = load_board()
            if op == "add":
                tid = uuid.uuid4().hex[:10]
                task = {"id": tid, "text": body.get("text", ""), "state": "needs_brainstorm",
                        "assignee": body.get("assignee", ""), "pinned": False, "pinRank": None,
                        "doneCondition": "", "workToDone": "", "done": False, "verified": False,
                        "unread": 0, "pingsToBoss": 0, "comments": [], "proofs": [],
                        "test": bool(body.get("test")), "created": now(), "updated": now(),
                        "lastAction": now()}
                board["tasks"][tid] = task
                board["order"].insert(0, tid)
                save_board(board)
                emit_task_event(board, task, "new task added")
                save_board(board)
                return self._send(200, {"ok": True, "id": tid})
            if op == "del":
                tid = body.get("id")
                if tid in board["tasks"]:
                    for proof in board["tasks"][tid].get("proofs", []):
                        url = proof.get("url", "")
                        if url.startswith("/todo/proof-file/"):
                            fp = os.path.join(PROOFS_DIR, os.path.basename(url))
                            try:
                                os.remove(fp)
                            except OSError:
                                pass
                    del board["tasks"][tid]
                    board["order"] = [x for x in board["order"] if x != tid]
                    save_board(board)
                    return self._send(200, {"ok": True})
                return self._send(200, {"ok": False, "error": "no_task"})
            if op == "set":
                tid = body.get("id")
                t = board["tasks"].get(tid)
                if not t:
                    return self._send(200, {"ok": False, "error": "no_task"})
                # reject removed features (subtasks/deps/hardgate) silently — never persist
                for banned in ("parent", "dependsOn", "hardGate", "brainstorm"):
                    body.pop(banned, None)
                prev_state = t.get("state")
                if "state" in body:
                    st = body["state"]
                    if st not in VALID_STATES:
                        return self._send(400, {"ok": False, "error": "bad_state"})
                    t["state"] = st
                    if st == "done":
                        t["done"] = True
                for f in ("text", "doneCondition", "workToDone", "assignee"):
                    if f in body:
                        t[f] = body[f]
                if body.get("done") is True or body.get("workToDone") is True:
                    t["state"] = "done"
                    t["done"] = True
                if "verified" in body:
                    t["verified"] = bool(body["verified"])
                t["updated"] = now()
                t["lastAction"] = now()
                save_board(board)
                if t.get("state") != prev_state:
                    emit_task_event(board, t, "state -> %s" % t.get("state"))
                    save_board(board)
                return self._send(200, {"ok": True})
            if op == "pin":
                tid = body.get("id")
                t = board["tasks"].get(tid)
                if not t:
                    return self._send(200, {"ok": False, "error": "no_task"})
                if t.get("pinned"):
                    return self._send(200, {"ok": True})
                board["pinSeq"] += 1
                t["pinned"] = True
                t["pinRank"] = board["pinSeq"]
                save_board(board)
                return self._send(200, {"ok": True})
            if op == "unpin":
                tid = body.get("id")
                t = board["tasks"].get(tid)
                if not t:
                    return self._send(200, {"ok": False, "error": "no_task"})
                t["pinned"] = False
                t["pinRank"] = None
                save_board(board)
                return self._send(200, {"ok": True})
            if op == "adset":
                # auto-research-ads tag + settings (additive; composes with any state).
                tid = body.get("id")
                t = board["tasks"].get(tid)
                if not t:
                    return self._send(200, {"ok": False, "error": "no_task"})
                if "on" in body:
                    t["adResearch"] = bool(body.get("on"))
                s = t.get("adSettings") or {"quality": "medium", "batch": 4, "size": "1536x1024"}
                inp = body.get("settings") or {}
                if inp.get("quality") in ("low", "medium", "high"):
                    s["quality"] = inp["quality"]
                if "batch" in inp:
                    try:
                        bn = int(inp["batch"])
                        if 1 <= bn <= 10:
                            s["batch"] = bn
                    except Exception:
                        pass
                if inp.get("size") in ("1536x1024", "1024x1024", "1024x1536"):
                    s["size"] = inp["size"]
                t["adSettings"] = s
                if "adAgent" in body:
                    t["adAgent"] = body.get("adAgent") or ""
                t.setdefault("adGen", 0)
                t.setdefault("adSpend", 0.0)
                t["updated"] = now()
                t["lastAction"] = now()
                save_board(board)
                return self._send(200, {"ok": True, "adResearch": t.get("adResearch", False),
                                        "adSettings": s, "adAgent": t.get("adAgent", "")})
            if op == "adscore":
                # Per-image HIL fitness signal (score/keep/note), persisted ON THE PROOF,
                # keyed by its unique url. Additive; composes with any state; mirrors the
                # adset safe write path. This is the results.tsv-equivalent memory the
                # bound ad-research agent reads to breed the next generation.
                tid = body.get("id")
                t = board["tasks"].get(tid)
                if not t:
                    return self._send(200, {"ok": False, "error": "no_task"})
                url = body.get("proof")
                if not url:
                    return self._send(200, {"ok": False, "error": "no_proof_url"})
                target = None
                for p in t.get("proofs", []):
                    if p.get("url") == url:
                        target = p
                        break
                if target is None:
                    return self._send(200, {"ok": False, "error": "no_proof"})
                if "score" in body:
                    sc = body.get("score")
                    if sc is None:
                        target["score"] = None
                    else:
                        try:
                            sc = int(sc)
                        except Exception:
                            return self._send(400, {"ok": False, "error": "bad_score"})
                        if not (1 <= sc <= 10):
                            return self._send(400, {"ok": False, "error": "bad_score"})
                        target["score"] = sc
                if "keep" in body:
                    kp = body.get("keep")
                    if kp not in (True, False, None):
                        return self._send(400, {"ok": False, "error": "bad_keep"})
                    target["keep"] = kp
                if "note" in body:
                    nt = body.get("note")
                    target["note"] = ("" if nt is None else str(nt))[:500]
                target["scoredBy"] = body.get("by") or "CEO"
                target["scoredTs"] = now()
                t["updated"] = now()
                t["lastAction"] = now()
                save_board(board)
                return self._send(200, {"ok": True, "proof": url,
                                        "score": target.get("score"),
                                        "keep": target.get("keep"),
                                        "note": target.get("note", "")})
            return self._send(400, {"ok": False, "error": "bad_op"})

    # ---- comment ----
    def _comment(self, body, ident):
        with LOCK:
            board = load_board()
            tid = body.get("task_id")
            t = board["tasks"].get(tid)
            if not t:
                return self._send(200, {"ok": False, "error": "no_task"})
            by = body.get("by", "CEO")
            c = {"id": uuid.uuid4().hex[:8], "by": by, "kind": "comment",
                 "body": body.get("body", ""), "ts": now()}
            t["comments"].append(c)
            if by != "CEO":
                t["unread"] = t.get("unread", 0) + 1
            t["updated"] = now()
            t["lastAction"] = now()
            t["idleFired"] = False
            save_board(board)
            emit_comment_event(board, t, by, c["body"])
            save_board(board)
            # Additive ad-research routing: a CEO comment on a tagged card ALSO nudges the bound
            # agent directly. Fire-and-forget (never blocks the response), no-op if unbound. The
            # Boss ping in emit_comment_event above still fires — Boss stays router-of-record.
            if t.get("adResearch") and by == "CEO":
                agent = t.get("adAgent")
                if agent:
                    threading.Thread(target=mp_send,
                                     args=(agent, '[adcard %s] CEO: %s' % (tid, c["body"][:400])),
                                     daemon=True).start()
            return self._send(200, {"ok": True, "id": c["id"]})

    # ---- proof (json) ----
    def _proof_json(self, body):
        with LOCK:
            board = load_board()
            tid = body.get("task_id")
            t = board["tasks"].get(tid)
            if not t:
                return self._send(200, {"ok": False, "error": "no_task"})
            url = body.get("url", "")
            kind = classify_kind(url=url, given=body.get("kind"))
            proof = {"kind": kind, "url": url, "body": body.get("body", ""), "ts": now()}
            t["proofs"].append(proof)
            t["updated"] = now()
            save_board(board)
            return self._send(200, {"ok": True, "proof": proof})

    # ---- proof (multipart upload) ----
    def _proof_multipart(self):
        fields, fileobj = parse_multipart(self, self.headers.get("Content-Type", ""))
        tid = fields.get("task_id", "")
        with LOCK:
            board = load_board()
            t = board["tasks"].get(tid)
            if not t:
                return self._send(200, {"ok": False, "error": "no_task"})
            if fileobj:
                fn, fct, data = fileobj
                os.makedirs(PROOFS_DIR, exist_ok=True)
                safe = "%s-%s" % (uuid.uuid4().hex[:8], os.path.basename(fn))
                with open(os.path.join(PROOFS_DIR, safe), "wb") as f:
                    f.write(data)
                kind = classify_kind(filename=fn, content_type=fct, given=fields.get("kind"))
                url = "/todo/proof-file/%s" % safe
                proof = {"kind": kind, "url": url, "body": fields.get("body", ""), "ts": now()}
            else:
                url = fields.get("url", "")
                proof = {"kind": classify_kind(url=url, given=fields.get("kind")),
                         "url": url, "body": fields.get("body", ""), "ts": now()}
            t["proofs"].append(proof)
            save_board(board)
            return self._send(200, {"ok": True, "proof": proof})

    # ---- status op ----
    def _status_op(self, body, ident):
        with LOCK:
            board = load_board()
            tid = body.get("task_id")
            t = board["tasks"].get(tid)
            if not t:
                return self._send(200, {"ok": False, "error": "no_task"})
            st = body.get("state")
            if st and st not in VALID_STATES:
                return self._send(400, {"ok": False, "error": "bad_state"})
            prev = t.get("state")
            if st:
                t["state"] = st
                t["done"] = (st == "done")
            if "verified" in body:
                t["verified"] = bool(body["verified"])
            t["updated"] = now()
            t["lastAction"] = now()
            t["idleFired"] = False
            save_board(board)
            if st and st != prev:
                emit_task_event(board, t, "state -> %s" % st)
                save_board(board)
            return self._send(200, {"ok": True})


def main():
    os.makedirs(TODOS_DIR, exist_ok=True)
    if not os.path.exists(BOARD_PATH):
        save_board(default_board())
    srv = ThreadingHTTPServer((CFG["BIND_ADDR"], TODO_PORT), Handler)
    srv.daemon_threads = True
    sys.stderr.write("todo-server on %s:%d\n" % (CFG["BIND_ADDR"], TODO_PORT))
    srv.serve_forever()


if __name__ == "__main__":
    main()
