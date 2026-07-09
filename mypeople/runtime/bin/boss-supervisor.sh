#!/usr/bin/env bash
# Boss supervisor (§5.3): always exactly one Boss. Keys off the tmux window (source of truth),
# not the queue. Idempotent — only spawns when mc-main:Boss is genuinely absent.
set -u
source "${MYPEOPLE_CONFIG_PATH:-$HOME/.config/mypeople/queue.env}" 2>/dev/null || true
export PATH="$HOME/.local/bin:${INSTALL_DIR:-$HOME/mypeople}/bin:$PATH"
HOST="${HOST_ID:-$(hostname -s)}"
export TMUX=
while true; do
  if tmux list-windows -t mc-main -F '#{window_name}' 2>/dev/null | grep -qx Boss; then
    :
  else
    echo "$(date -u +%FT%TZ) boss absent -> respawning" >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log"
    mp spawn "$HOST/main:Boss" --master >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log" 2>&1 || \
      echo "$(date -u +%FT%TZ) ERROR: boss respawn failed" >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log"
  fi
  sleep 15
done
