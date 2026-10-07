#!/usr/bin/env bash
# Door installer for the customer's Mac. Installs the local daemon (door-host) and the isolated runner image.
# Nothing here opens a port: the Mac only makes outbound connections.
#
# Usage: scripts/install-mac.sh --repo /path/to/your/repo [--alias desk] [--dry-run] [--skip-image]
set -euo pipefail

REPO=""; ALIAS="desk"; DRY=0; SKIP_IMAGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --alias) ALIAS="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    --skip-image) SKIP_IMAGE=1; shift;;
    -h|--help) sed -n 2,6p "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

SRC="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME/.local/share/door"; CONF_DIR="$HOME/.config/door"; STATE_DIR="$HOME/.local/state/door"
PLIST="$HOME/Library/LaunchAgents/co.door.host.plist"

run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else eval "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
fail() { echo "error: $*" >&2; exit 1; }

say "Checking requirements"
[ "$(uname -s)" = "Darwin" ] || fail "this installer is for macOS"
[ -n "$REPO" ] || fail "pass --repo /path/to/the/repo you want guests to ask about"
[ -d "$REPO/.git" ] || fail "$REPO is not a git repository (Door exports committed files only)"
PY="$(command -v python3.12 || command -v python3 || true)"; [ -n "$PY" ] || fail "Python 3.12+ not found"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' || fail "Python 3.12+ required"
command -v docker >/dev/null || fail "Docker Desktop not found (https://www.docker.com/products/docker-desktop/)"
[ "$DRY" = 1 ] || docker info >/dev/null 2>&1 || fail "Docker is installed but not running"
command -v git >/dev/null || fail "git not found"

say "Installing the Door daemon into $HOME_DIR"
run "mkdir -p '$HOME_DIR' '$CONF_DIR' '$STATE_DIR' '$HOME/Library/LaunchAgents'"
run "chmod 700 '$HOME_DIR' '$CONF_DIR' '$STATE_DIR'"      # keys, audit log and questions live here: nobody else on this computer may read them
run "'$PY' -m venv '$HOME_DIR/venv'"
PRE_BUILD=0; [ -e "$SRC/build" ] && PRE_BUILD=1
run "'$HOME_DIR/venv/bin/pip' install --quiet '$SRC'"
if [ "$DRY" != 1 ]; then rm -rf "$SRC"/*.egg-info; [ "$PRE_BUILD" = 0 ] && rm -rf "$SRC/build"; fi   # pip leaves build leftovers in the source folder

say "Building the isolated runner image (door-runner:0.3)"
if [ "$SKIP_IMAGE" = 1 ]; then echo "skipped (--skip-image)"; else run "docker build -t door-runner:0.3 '$SRC/runner'"; fi

say "Writing the policy file $CONF_DIR/door.json"
if [ -f "$CONF_DIR/door.json" ]; then
  echo "kept existing $CONF_DIR/door.json"
else
  run "'$HOME_DIR/venv/bin/python' - <<PYEOF
import json
j = json.load(open('$SRC/door.example.json'))
j['agent']['alias'] = '$ALIAS'
j['agent']['exports'][0]['repo'] = '$REPO'
j['agent']['exports'][0]['name'] = '$ALIAS'
json.dump(j, open('$CONF_DIR/door.json', 'w'), indent=2)
PYEOF"
  run "chmod 600 '$CONF_DIR/door.json'"
fi

say "Starting script (reads your API key from the macOS Keychain, never from a file)"
WRAP="$HOME_DIR/door-host-run"
run "cat > '$WRAP' <<'WRAPEOF'
#!/bin/bash
# Keys live in the macOS Keychain, never in a file. Only the ones you stored are read; door-host says clearly if one it needs is missing.
get() { security find-generic-password -a \"\$USER\" -s \"\$1\" -w 2>/dev/null || true; }
for pair in door-anthropic-api-key:DOOR_ANTHROPIC_API_KEY door-opencode-api-key:OPENCODE_API_KEY door-openai-api-key:OPENAI_API_KEY \\
            door-openrouter-api-key:OPENROUTER_API_KEY door-deepseek-api-key:DEEPSEEK_API_KEY; do
  v=\$(get \"\${pair%%:*}\"); [ -n \"\$v\" ] && export \"\${pair##*:}=\$v\"
done
exec \"\$HOME/.local/share/door/venv/bin/door-host\" --policy \"\$HOME/.config/door/door.json\" --state \"\$HOME/.local/state/door\" serve
WRAPEOF"
run "chmod 700 '$WRAP'"

say "Registering the background service"
run "cat > '$PLIST' <<PLISTEOF
<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>co.door.host</string>
  <key>ProgramArguments</key><array><string>$WRAP</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$STATE_DIR/host.log</string><key>StandardErrorPath</key><string>$STATE_DIR/host.log</string>
</dict></plist>
PLISTEOF"

say "Done. Next steps"
cat <<NEXT
1. Choose how the agent pays for the model (see README, "Engines and providers"):
   a) a dedicated API key with a spend limit, stored in the Keychain:
        security add-generic-password -a "\$USER" -s door-anthropic-api-key -w        (or door-opencode-api-key, door-openai-api-key ...)
   b) the key OpenCode already keeps on this computer: set "credential_source": "opencode-auth" in the policy file, or
   c) your own account sign-in: set "egress": {"mode": "login"} and run:  door-host login claude
2. Check every link in one go (tells you exactly what is still missing):
     $HOME_DIR/venv/bin/door-host --policy $CONF_DIR/door.json --state $STATE_DIR doctor
3. Check the isolation of the container (must print four "ok" lines):
     DOOR_ANTHROPIC_API_KEY=x $HOME_DIR/venv/bin/door-host --policy $CONF_DIR/door.json --state $STATE_DIR selftest
4. Start the service:   launchctl load $PLIST
   Then open the link it prints in $STATE_DIR/host.log: that is the screen that shows how Door is being used on this computer.
5. Pair this Mac with your Door account:   $HOME_DIR/venv/bin/door-host --policy $CONF_DIR/door.json --state $STATE_DIR pair
NEXT
