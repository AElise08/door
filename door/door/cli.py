"""Entradas: `door` (cliente fino do plugin Latch) e `door-host` (daemon)."""
import argparse
import json
import os
import signal
import socket
import sys
from pathlib import Path

from .policy import PolicyError, default_path, default_state_dir, load


def _sock(state_dir=None):
    return Path(os.environ.get("DOOR_SOCKET") or (Path(state_dir or default_state_dir()) / "door.sock"))


def call(msg, state_dir=None, timeout=60):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect(str(_sock(state_dir)))
        s.sendall((json.dumps(msg) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            c = s.recv(65536)
            if not c:
                break
            buf += c
        return json.loads(buf)
    except OSError as e:
        return {"ok": False, "reason": "host_offline", "detail": str(e)}
    finally:
        s.close()


def client_main(argv=None):
    """`door`: só repassa ao door-host e devolve a resposta (6.3). Nenhuma decisão aqui."""
    ap = argparse.ArgumentParser(prog="door")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--request", required=True)
    a.add_argument("--payload", required=True, help="pedido assinado (base64)")
    a.add_argument("--sig", required=True)
    dc = sub.add_parser("decide")
    dc.add_argument("--request", required=True)
    dc.add_argument("--action", required=True)
    dc.add_argument("--decision", required=True, choices=["allow", "deny"])
    for n in ("status", "cancel"):
        p = sub.add_parser(n)
        p.add_argument("--request", required=True)
        if n == "cancel":
            p.add_argument("--reason", default="owner_canceled")
    pc = sub.add_parser("pair-confirm")
    pc.add_argument("--code", required=True)
    pc.add_argument("--public-key", required=True)
    sub.add_parser("summary")
    sub.add_parser("pause")
    sub.add_parser("resume")
    ns = ap.parse_args(argv)
    msg = {"op": ns.cmd.replace("-", "_")}
    if ns.cmd == "ask":
        msg.update(payload=ns.payload, sig=ns.sig, request=ns.request)
    elif ns.cmd == "decide":
        msg.update(request=ns.request, action=ns.action, decision=ns.decision)
    elif ns.cmd in ("status", "cancel"):
        msg["request"] = ns.request
        if ns.cmd == "cancel":
            msg["reason"] = ns.reason
    elif ns.cmd == "pair-confirm":
        msg.update(code=ns.code, public_key=ns.public_key)
    out = call(msg)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


def host_main(argv=None):
    forwarded = list(argv if argv is not None else sys.argv[1:])
    if forwarded and forwarded[0] in ("ask", "status", "cancel", "pair-confirm", "summary"):
        return client_main(forwarded)
    ap = argparse.ArgumentParser(prog="door-host")
    ap.add_argument("--policy", default=str(default_path()))
    ap.add_argument("--state", default=str(default_state_dir()))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("pair")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("check")
    sub.add_parser("setup-network")
    sub.add_parser("selftest")
    sub.add_parser("doctor", help="check every link a working Door needs on this computer")
    ini = sub.add_parser("init", help="write the policy file for a new install")
    ini.add_argument("--repo", required=True); ini.add_argument("--alias", default="desk")
    ini.add_argument("--access", default="opencode", choices=["opencode", "claude-login", "api-key"])
    ini.add_argument("--tasks", action="store_true"); ini.add_argument("--force", action="store_true")
    lg = sub.add_parser("login", help="sign in with your own account (subscription) for an engine, inside Door's own volume")
    lg.add_argument("engine", choices=["claude", "codex", "opencode"])
    lg.add_argument("--status", action="store_true", help="only show whether it is signed in")
    lg.add_argument("--forget", action="store_true", help="delete Door's sign-in for this engine")
    tl = sub.add_parser("audit")
    tl.add_argument("-n", type=int, default=20)
    ns = ap.parse_args(argv)
    state = Path(ns.state)

    if ns.cmd == "check":
        try:
            pol = load(Path(ns.policy), state)
        except PolicyError as e:
            print("invalid policy:", e)
            return 1
        print("ok:", json.dumps({k: pol[k] for k in ("agent", "sandbox", "limits")}, ensure_ascii=False)[:400])
        return 0
    if ns.cmd in ("pair", "pause", "resume"):
        r = call({"op": {"pair": "pair_start"}.get(ns.cmd, ns.cmd)}, state)
        if ns.cmd == "pair" and r.get("code"):
            print("Pairing code (10 min, single use): %s\nOn your phone: Door Pair: %s" % (r["code"], r["code"]))
            return 0
        print(json.dumps(r))
        return 0 if r.get("ok", True) else 1
    if ns.cmd == "audit":
        from .audit import Audit
        rows = list(Audit(state / "audit.jsonl").rows())[-ns.n:]
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return 0

    from .host import Host
    from .sandbox import ContainerRuntime
    if ns.cmd == "init":
        from .setup import SetupError, build_policy, write_policy
        from .policy import load as load_policy
        try:
            pol = build_policy(ns.repo, ns.alias, ns.access, ns.tasks)
            wrote = write_policy(ns.policy, pol, ns.force)
            load_policy(Path(ns.policy), Path(state))                   # what we wrote must be accepted by the same rules the daemon uses
        except (SetupError, PolicyError) as e:
            print("error: %s" % e, file=sys.stderr); return 1
        print(("wrote %s" if wrote else "kept the existing %s") % ns.policy)
        return 0
    if ns.cmd == "doctor":
        from .doctor import render, run
        text, bad = render(run(ns.policy, state))
        print(text)
        return 1 if bad else 0
    if ns.cmd == "login":
        rt0 = ContainerRuntime("docker", "door-runner:0.3")
        if ns.forget:
            rt0.forget_login(ns.engine); print("Door's %s sign-in was deleted." % ns.engine); return 0
        if ns.status:
            ok, text = rt0.login_status(ns.engine); print(("signed in" if ok else "NOT signed in") + "\n" + text); return 0 if ok else 1
        print("Signing in to %s inside Door's own sandbox volume. Follow the instructions below; this is separate from any\n"
              "sign-in already on this computer, and nothing is copied from it." % ns.engine)
        return rt0.login(ns.engine)
    pol = load(Path(ns.policy), state)
    rt = ContainerRuntime(pol["sandbox"].get("runtime", "docker"), pol["sandbox"]["image"])
    from .credentials import load_credential
    cred = load_credential(pol["egress"])
    if ns.cmd == "selftest":
        from .selftest import run as selftest
        return selftest(pol, rt, cred)
    if not cred and pol["egress"].get("mode") != "login":
        print("set %s to the API key dedicated to Door (a subscription login is NOT allowed)" % pol["egress"]["credential_env"])
        return 1
    host = Host(Path(ns.policy), state, rt, cred)
    host.proxy.start()
    if ns.cmd == "setup-network":
        rt.setup_network(host.proxy.port)
        print("internal network and relay ready (proxy on port %d)" % host.proxy.port)
        return 0
    if not rt.available():
        print("warning: container runtime unavailable; requests will be rejected (sandbox_unavailable)")
    else:
        rt.pin_image()
        rt.setup_network(host.proxy.port)
    srv = host.serve()
    if pol["local_ui"]["enabled"]:
        from .local_ui import LocalUI
        try:
            ui = LocalUI(host, pol["local_ui"]["port"]).start()
            print("Door on this computer (open this link in your browser): " + ui.url)
        except OSError as e:
            print("warning: the local screen could not start (%s)" % e)
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    print("door-host ouvindo em", srv.server_address)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for rid in list(host._running):
            host.cancel(rid)
            host.wait(rid, timeout=10)
        srv.server_close()
        host.proxy.stop()
        Path(srv.server_address).unlink(missing_ok=True)
    return 0
