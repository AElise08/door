#!/bin/bash
# PID 1 of a MyPlow cloud agent. Plow sets PLOW_API_BASE (and AGENT_ID on a 1-click deploy);
# everything else is derived here, at run time, never at build time.
set -u
export PLOW_API_BASE="${PLOW_API_BASE:-https://api.plow.co}"
# On a Plow VM the proxy replaces Authorization with the agent's real token, so a placeholder
# fills an absent one; a local run passes the real token and it is used as is.
export PLOW_AGENT_TOKEN="${PLOW_AGENT_TOKEN:-proxied}"
export PLOW_LLM_BASE="${PLOW_API_BASE%/}/v1"
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

# Both loops respawn their process; neither is fatal to the agent.
( while :; do litellm --config /opt/myplow/litellm.yaml --host 127.0.0.1 --port 4000
            echo "litellm exited $?, restarting"; sleep 2; done ) >>"$LOG/litellm.log" 2>&1 &
/opt/myplow/agent-index.sh "$INDEX_AGENT_ID" >>"$LOG/agent-index.log" 2>&1 &

exec mypeople up --both
