"""Door as a Plow cloud agent: the process the one-click install runs inside Plow's VM.

Nothing secret is configured. Plow sets PLOW_API_BASE and its proxy swaps the placeholder token for the real one; the conversations and
the relay to the owner's Mac (Plow Latch) both come from GET /v1/agents/cloud/me. The only things this process needs are the address of
the Door panel that runs next to it and the panel's agent token, which the container's entrypoint generates.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from .cloud import Cloud
from .common import now
from .door_link import DoorLink
from .plow import McpUrlRelay, PlowAPI
from .service import cycle

DEFAULT_SUMMARY = {"alias": "desk", "description": "", "max_capability": "ask", "boss": False, "agents": [{"alias": "desk", "description": ""}],
                   "act_agent": None, "guardrails": {"blocked_patterns": [], "block_prompt_injection": True,
                                                     "refusal": "I can only help with questions about this project."},
                   "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10, "guest_daily_tokens": 400000,
                              "monthly_budget": 50.0, "currency": "USD"}}


def log(msg):
    print("door:", msg, flush=True)           # never message bodies, tokens or phone numbers


def build(env=os.environ):
    base = env.get("PLOW_API_BASE") or "https://api.plow.co"
    local = env.get("DOOR_ALLOW_LOCAL") == "1"
    api = PlowAPI(env.get("PLOW_AGENT_TOKEN") or "proxied", base, cloud=True, local=local)
    state = Path(env.get("DOOR_STATE") or "/var/lib/door")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    public = (env.get("DOOR_PUBLIC_URL") or "").rstrip("/")
    cloud = Cloud(state / "cloud.db", env.get("DOOR_OWNER_ID") or "owner", dict(DEFAULT_SUMMARY), public)
    cloud.s.setdefault("started_at", now()); cloud.s.setdefault("relay_pending", {})
    if env.get("DOOR_BILLING") != "1" and cloud.s["plan"]["status"] != "active":
        cloud.set_plan("active", now() + 10 * 365 * 86400)      # your own install is not billed; the operator turns billing on with DOOR_BILLING=1
    cloud._save()
    hub = DoorLink(env.get("DOOR_PANEL_API") or "http://127.0.0.1:9630", env["DOOR_PANEL_AGENT_TOKEN"], local=True)
    return api, cloud, hub


def relay_for(api, cloud, max_age=30):
    """Asked again every half minute: the owner can connect or remove a Mac at any time, and a lookup costs a second every pass."""
    seen = getattr(api, "_me_seen", None)                 # remembered on the API object, so every client keeps its own
    if seen is None or time.time() - seen[0] > max_age:
        seen = api._me_seen = (time.time(), (api.cloud_me() or {}).get("mcp_url"))
    mcp = seen[1]
    return McpUrlRelay(api, mcp, cloud.s["relay_pending"], cloud._save) if mcp else None


def check(env=os.environ):
    """Is this install wired correctly? Prints what it finds, never a secret. Exit 0 only if everything needed is there."""
    problems = []
    try:
        api, cloud, hub = build(env)
    except (KeyError, ValueError) as e:
        print("not ready: %s" % e); return 1
    try:
        me = api.cloud_me()
        chats = me.get("chats") or []
        print("Plow: reachable; %d conversation(s) on this line" % len(chats))
        print("Mac relay (Latch): %s" % ("connected" if me.get("mcp_url") else "NOT connected: install Plow Latch on the owner's Mac"))
        if not me.get("mcp_url"):
            problems.append("no Mac relay")
    except (OSError, PermissionError, ValueError) as e:
        print("Plow: NOT reachable (%s)" % type(e).__name__); problems.append("plow")
    try:
        hub._req("GET", "/agent/commands"); print("Door panel: reachable")
    except OSError as e:
        print("Door panel: NOT reachable (%s)" % type(e).__name__); problems.append("panel")
    print("Owner: %s" % ("activated" if cloud.s["owner_phone"] else "not activated yet (text: Door Activate: <code>)"))
    print("Mac: %s" % ("paired" if cloud.s.get("host_id") else "not paired yet"))
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="door-plow-agent")
    ap.add_argument("--check", action="store_true", help="verify the wiring and exit")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit (tests)")
    ns = ap.parse_args(argv)
    if ns.check:
        return check()
    api, cloud, hub = build()
    log("started")
    shown = None
    while True:
        try:
            code = cloud.ensure_activation()
            if code and code != shown:
                shown = code
                log("owner activation: text this to your Door number -> Door Activate: %s" % code)
            relay = relay_for(api, cloud)
            cycle(cloud, api, relay, hub, None)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            log("cycle pending: %s" % type(exc).__name__)
        if ns.once:
            return 0
        busy = any(r["state"] in ("queued", "running", "waitingApproval") for r in cloud.s["requests"].values()) or cloud.s["panel_jobs"]
        time.sleep(1 if busy else 5)             # someone is waiting for an answer: check again quickly


if __name__ == "__main__":
    sys.exit(main())
