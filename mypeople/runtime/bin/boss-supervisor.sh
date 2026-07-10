#!/usr/bin/env bash
# Boss supervisor (§5.3): always exactly one Boss. Keys off the tmux window (source of truth),
# not the queue. A known Boss is strictly resumed; only a node with no Boss record may spawn one.
set -u
source "${MYPEOPLE_CONFIG_PATH:-$HOME/.config/mypeople/queue.env}" 2>/dev/null || true
export PATH="$HOME/.local/bin:${INSTALL_DIR:-$HOME/mypeople}/bin:$PATH"
HOST="${HOST_ID:-$(hostname -s)}"
export TMUX=
while true; do
  if tmux list-windows -t mc-main -F '#{window_name}' 2>/dev/null | grep -qx Boss; then
    :
  else
    echo "$(date -u +%FT%TZ) boss absent -> ensuring persisted session" >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log"
    mp ensure-boss "$HOST/main:Boss" >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log" 2>&1 || \
      echo "$(date -u +%FT%TZ) ERROR: boss session recovery failed" >> "${INSTALL_DIR:-$HOME/mypeople}/logs/boss-supervisor.log"
  fi
  sleep 15
done
