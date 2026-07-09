#!/usr/bin/env python3
"""mypeople shared helpers: config, auth/session, json io, tmux delivery, http proxy.
Python 3 stdlib only."""
import os, sys, json, hmac, hashlib, base64, time, socket, subprocess, threading, urllib.request, urllib.parse

def config_path():
    explicit = os.environ.get("MYPEOPLE_CONFIG_PATH")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    home = os.environ.get("MYPEOPLE_HOME")
    if home:
        return os.path.join(os.path.abspath(os.path.expanduser(home)), "config", "queue.env")
    return os.path.expanduser("~/.config/mypeople/queue.env")


CONFIG_PATH = config_path()

def load_env():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                    v = v[1:-1]
                cfg[k.strip()] = v
    # Live env overrides the file, including fleet/client-only keys not present in old configs.
    known = set(cfg) | {
        "INSTALL_DIR", "HOST_ID", "HUD_PORT", "TODO_PORT", "TTYD_PORT", "BIND_ADDR",
        "QUEUE_URL", "QUEUE_SECRET", "TTYD_PUBLIC_URL", "DEFAULT_ENG_MODEL",
        "QUEUE_DEAD_AFTER", "HEARTBEAT_INTERVAL", "UPSTREAM_QUEUE_URL",
        "UPSTREAM_QUEUE_SECRET", "NODE_PURPOSE", "NODE_TYPE", "NODE_RECORDING_URL",
    }
    for k in known:
        if os.environ.get(k) is not None:
            cfg[k] = os.environ[k]
    # a few defaults
    cfg.setdefault("INSTALL_DIR", os.path.expanduser("~/mypeople"))
    cfg.setdefault("HOST_ID", socket.gethostname().split(".")[0])
    cfg.setdefault("HUD_PORT", "9900")
    cfg.setdefault("TODO_PORT", "9933")
    cfg.setdefault("TTYD_PORT", "7681")
    cfg.setdefault("BIND_ADDR", "0.0.0.0")
    cfg.setdefault("QUEUE_URL", "http://127.0.0.1:%s" % cfg["HUD_PORT"])
    cfg.setdefault("DEFAULT_ENG_MODEL", "claude-opus-4-8")
    cfg.setdefault("QUEUE_DEAD_AFTER", "45")
    cfg.setdefault("HEARTBEAT_INTERVAL", "10")
    return cfg

CFG = load_env()

# ---------- session cookie (stateless, HMAC-signed; NOT the secret) ----------
def _hmac(msg):
    return hmac.new(CFG.get("QUEUE_SECRET", "").encode(), msg.encode(), hashlib.sha256).hexdigest()[:24]

def mint_session():
    rnd = base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    return "%s.%s" % (rnd, _hmac(rnd))

def valid_session(tok):
    if not tok or "." not in tok:
        return False
    rnd, sig = tok.rsplit(".", 1)
    return hmac.compare_digest(sig, _hmac(rnd))

def parse_cookies(header):
    out = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out

def caller_identity(headers):
    """Returns (authorized:bool, identity:str) where identity in {machine,browser,none}."""
    secret = CFG.get("QUEUE_SECRET", "")
    hs = headers.get("X-Queue-Secret")
    if secret and hs and hmac.compare_digest(hs, secret):
        return True, "machine"
    cookies = parse_cookies(headers.get("Cookie", ""))
    if valid_session(cookies.get("mp_session", "")):
        return True, "browser"
    return False, "none"

# ---------- atomic json io ----------
def atomic_write(path, data_bytes):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), int(time.time() * 1000))
    with open(tmp, "wb") as f:
        f.write(data_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

# ---------- agent_id helpers ----------
def parse_agent_id(aid):
    """<host>/<sess>:<tab> -> (host, sess, tab). Robust to missing pieces."""
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

def tmux_target(aid):
    _, sess, tab = parse_agent_id(aid)
    return "mc-%s:%s" % (sess, tab)

def export_repo_path(cfg=None):
    """PER-INSTANCE git backup repo (§3 boardgit). Path carries an instance discriminator
    (TODO_PORT + sha1($INSTALL_DIR)[:8]) so two installs differing in INSTALL_DIR OR port never
    collide onto one repo. Overridable via EXPORT_REPO."""
    cfg = cfg or CFG
    override = os.environ.get("EXPORT_REPO") or cfg.get("EXPORT_REPO")
    if override:
        return override
    host = cfg.get("HOST_ID", "node")
    port = cfg.get("TODO_PORT", "9933")
    disc = hashlib.sha1(cfg.get("INSTALL_DIR", "").encode()).hexdigest()[:8]
    return os.path.expanduser("~/.mypeople/board-backup/%s-%s-%s" % (host, port, disc))

# ---------- tmux message delivery (bracketed paste + double Enter, with retry) ----------
def tmux_send_message(target, message):
    """Deliver a message into a tmux pane's composer and submit it.
    target = mc-<sess>:<tab>. Returns True on success."""
    env = dict(os.environ)
    env.pop("TMUX", None)  # never target the caller's pane
    ok = False
    for attempt in range(3):
        r = subprocess.run(["tmux", "has-session", "-t", target.split(":")[0]],
                           env=env, capture_output=True)
        if r.returncode != 0:
            time.sleep(0.3)
            continue
        # bracketed paste literal, then Enter, wait, second Enter (5.5b)
        subprocess.run(["tmux", "send-keys", "-t", target, "-l", message], env=env, capture_output=True)
        time.sleep(0.15)
        subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], env=env, capture_output=True)
        time.sleep(0.4)
        subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], env=env, capture_output=True)
        ok = True
        break
    return ok

def tmux_capture(target, lines=200):
    env = dict(os.environ)
    env.pop("TMUX", None)
    r = subprocess.run(["tmux", "capture-pane", "-p", "-t", target, "-S", "-%d" % lines],
                       env=env, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""

# ---------- HTTP client (to central/other daemons) ----------
def http_json(method, url, body=None, headers=None, timeout=8):
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except Exception:
        return 0, None

# ---------- reverse proxy (stream one request to an inner port) ----------
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}

def proxy_request(handler, inner_host, inner_port):
    """Forward handler's current request to inner_host:inner_port, stream response back.
    Preserves Cookie / X-Queue-Secret / Set-Cookie so auth + sessions survive the proxy."""
    path = handler.path
    url = "http://%s:%s%s" % (inner_host, inner_port, path)
    length = int(handler.headers.get("Content-Length", 0) or 0)
    body = handler.rfile.read(length) if length else None
    fwd = {}
    for k, v in handler.headers.items():
        if k.lower() in HOP:
            continue
        fwd[k] = v
    req = urllib.request.Request(url, data=body, headers=fwd, method=handler.command)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        status = resp.status
        raw = resp.read()
        rhdrs = resp.getheaders()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read()
        rhdrs = e.headers.items()
    except Exception as e:
        handler.send_response(502)
        handler.send_header("Content-Type", "text/plain")
        handler.end_headers()
        handler.wfile.write(("proxy error: %s" % e).encode())
        return
    if raw is None:
        raw = b""
    handler.send_response(status)
    for k, v in rhdrs:
        if k.lower() in HOP:
            continue
        handler.send_header(k, v)
    # We stripped the inner Content-Length/Connection (HOP); re-add a correct framing so
    # HTTP/1.1 keep-alive clients (curl, browser fetch) know the body is complete and don't hang.
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Connection", "close")
    handler.close_connection = True
    handler.end_headers()
    if raw:
        handler.wfile.write(raw)
