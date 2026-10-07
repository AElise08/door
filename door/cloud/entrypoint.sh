#!/bin/bash
# Door as a Plow cloud agent. Starts the owner panel and the agent side by side; if either stops, the container stops so Plow restarts it.
set -eu
STATE="${DOOR_STATE:-/var/lib/door}"; export DOOR_STATE="$STATE"
umask 077; mkdir -p "$STATE"

# Tokens for the panel <-> agent link are made once and kept in the state folder. They are never printed and never texted.
for n in owner agent; do
  f="$STATE/panel-$n-token"
  [ -s "$f" ] || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$f"
done
export DOOR_PANEL_OWNER_TOKEN="$(cat "$STATE/panel-owner-token")"
export DOOR_PANEL_AGENT_TOKEN="$(cat "$STATE/panel-agent-token")"
export DOOR_PANEL_DATA="$STATE/panel.json"
export DOOR_PANEL_PORT="${DOOR_PANEL_PORT:-9630}"
export DOOR_PANEL_API="http://127.0.0.1:$DOOR_PANEL_PORT"

# Behind Plow's TLS proxy the panel must listen on all interfaces; otherwise it stays on loopback.
if [ "${DOOR_BEHIND_TLS:-0}" = "1" ]; then
  export DOOR_PANEL_HOST=0.0.0.0 DOOR_PANEL_ALLOW_REMOTE_BIND=1 DOOR_PANEL_SECURE=1
elif [ "${DOOR_LOCAL_PUBLISH:-0}" = "1" ]; then
  # Local testing: the container's port is published only on the host's 127.0.0.1 (see compose), over plain http.
  export DOOR_PANEL_HOST=0.0.0.0 DOOR_PANEL_ALLOW_REMOTE_BIND=1
fi

door-panel &
PANEL=$!
for i in $(seq 1 50); do
  python3 - <<PY && break || sleep 0.2
import socket,sys
try: socket.create_connection(("127.0.0.1", $DOOR_PANEL_PORT), 0.3).close()
except OSError: sys.exit(1)
PY
done

door-plow-agent &
AGENT=$!
trap 'kill $PANEL $AGENT 2>/dev/null' TERM INT
wait -n $PANEL $AGENT
kill $PANEL $AGENT 2>/dev/null || true
exit 1
