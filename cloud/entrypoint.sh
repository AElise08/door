#!/bin/bash
# PID 1 of a MyPlow cloud agent. Plow sets PLOW_API_BASE (and AGENT_ID on a 1-click deploy);
# everything else is derived here, at run time, never at build time.
set -u
# exe.dev writes the tenant environment here; normally it is also in ours, so this only fills gaps.
if [ -z "${PLOW_API_BASE:-}" ] && [ -r /exe.dev/etc/env ]; then set -a; . /exe.dev/etc/env; set +a; fi
# Booted as root (exe.dev): own the state, then become mypeople. Claude Code refuses to skip
# permission prompts as root, so the fleet must never run as root.
if [ "$(id -u)" = 0 ]; then
  chown -R mypeople:mypeople /var/lib/mypeople /home/mypeople
  exec setpriv --reuid=mypeople --regid=mypeople --init-groups env HOME=/home/mypeople "$0" "$@"
fi
export PLOW_API_BASE="${PLOW_API_BASE:-https://api.plow.co}"
# On a Plow VM the proxy replaces Authorization with the agent's real token, so a placeholder
# fills an absent one; a local run passes the real token and it is used as is.
export PLOW_AGENT_TOKEN="${PLOW_AGENT_TOKEN:-proxied}"
LOG="${MYPEOPLE_HOME:-/var/lib/mypeople}/logs"
mkdir -p "$LOG"

# AGENT_ID means "which Index listing" to Plow and "which agent am I" to every mypeople process.
# Hand Plow's to the reporter and keep it out of the fleet's environment.
INDEX_AGENT_ID="${AGENT_ID:-}"
unset AGENT_ID

# Claude Code skips its first-run screens only when told they are done.
python3 - <<'EOF'
import json, os
p = os.path.expanduser("~/.claude.json")
try:
    cfg = json.load(open(p))
except (OSError, ValueError):
    cfg = {}
cfg.update(hasCompletedOnboarding=True, bypassPermissionsModeAccepted=True)
json.dump(cfg, open(p, "w"))
EOF

# The owner's Claude login, fetched once from the owner's login server. Without it there is no Boss:
# the installer has been texted why (not the owner's account, expired, server down), and this PID 1
# blocks instead of starting a fleet that cannot answer. A restart checks again.
if ! CLAUDE_CODE_OAUTH_TOKEN="$(/opt/myplow/claude-login.sh fetch 2>>"$LOG/claude-login.log")"; then
  echo "no Claude login; see the text sent to the installer" >>"$LOG/claude-login.log"
  exec python3 -c "import signal; signal.pause()"
fi
export CLAUDE_CODE_OAUTH_TOKEN
/opt/myplow/agent-index.sh "$INDEX_AGENT_ID" >>"$LOG/agent-index.log" 2>&1 &

exec mypeople up --both
