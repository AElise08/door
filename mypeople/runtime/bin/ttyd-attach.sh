#!/usr/bin/env bash
# ttyd attach-helper (§5.7). Each connection gets its OWN window selection via a GROUPED session,
# created ATTACHED in ttyd's pty in ONE command (never detached-then-attached).
# ttyd passes the URL args here: -t mc-<sess>:<tab>
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    -t) shift; TARGET="$1" ;;
  esac
  shift
done
if [ -z "$TARGET" ]; then
  # no target: attach to the boss by default
  TARGET="mc-main:Boss"
fi
SESS="${TARGET%%:*}"
TAB="${TARGET#*:}"
UNIQ="$$_${RANDOM}"
export TMUX=
if ! tmux has-session -t "$SESS" 2>/dev/null; then
  echo "session $SESS not found"; sleep 2; exit 1
fi
exec tmux new-session -t "$SESS" -s "_v_${TAB}_${UNIQ}" \; \
     select-window -t "$TAB" \; \
     set-option destroy-unattached on
