#!/usr/bin/env bash
# Door for your Mac: one command installs Plow Latch (if missing), the Door daemon and the isolated runner, asks three questions, and checks everything.
#
#   curl -fsSL https://YOUR-HOST/door/install.sh | bash
#
# Nothing here opens a port: the Mac only makes outbound connections. Keys are never written to a file (macOS Keychain or your own sign-in only).
# Flags (all optional; without them it asks):
#   --repo PATH          the git project people may ask about
#   --access WAY         opencode (the key OpenCode already keeps here) | claude-login (your own Claude account) | api-key (an Anthropic key)
#   --tasks              also allow trusted people to have things done (needs Claude Code installed; every risky step asks you)
#   --alias NAME         the agent's name (default: desk)
#   --release-url URL    where the Door package is (default: $DOOR_RELEASE_URL, or the address below)
#   --skip-latch  --skip-image  --no-start  --yes  --dry-run
#   --uninstall          stop and remove Door from this Mac (keeps your policy file and Keychain items)
set -euo pipefail

RELEASE_URL_DEFAULT="https://github.com/AElise08/door/releases/latest/download/door-mac.tar.gz"
LATCH_URL="https://plow.co/download/latch"

REPO=""; ALIAS="desk"; ACCESS=""; TASKS=""; RELEASE_URL="${DOOR_RELEASE_URL:-$RELEASE_URL_DEFAULT}"
SKIP_LATCH=0; SKIP_IMAGE=0; NO_START=0; YES=0; DRY=0; UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;       --alias) ALIAS="$2"; shift 2;;
    --access) ACCESS="$2"; shift 2;;   --tasks) TASKS=1; shift;;
    --release-url) RELEASE_URL="$2"; shift 2;;
    --skip-latch) SKIP_LATCH=1; shift;; --skip-image) SKIP_IMAGE=1; shift;; --no-start) NO_START=1; shift;;
    --yes|-y) YES=1; shift;;           --dry-run) DRY=1; shift;;     --uninstall) UNINSTALL=1; shift;;
    -h|--help) sed -n 2,16p "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

HOME_DIR="$HOME/.local/share/door"; CONF="$HOME/.config/door/door.json"; STATE="$HOME/.local/state/door"
PLIST="$HOME/Library/LaunchAgents/co.door.host.plist"; LABEL="co.door.host"
say()  { printf '\n==> %s\n' "$*"; }
fail() { echo "error: $*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }
# Questions are read from the terminal even when this script arrives through a pipe (curl | bash).
ask()  { local prompt="$1" default="${2:-}" reply=""
         if [ "$YES" = 1 ] || [ ! -r /dev/tty ]; then echo "$default"; return; fi
         read -r -p "$prompt" reply < /dev/tty || true; echo "${reply:-$default}"; }

[ "$(uname -s)" = "Darwin" ] || fail "this installer is for macOS"

if [ "$UNINSTALL" = 1 ]; then
  say "Removing Door from this Mac"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; rm -rf "$HOME_DIR"
  docker rmi door-runner:0.3 >/dev/null 2>&1 || true
  echo "Removed the program, the service and the runner image."
  echo "Kept: $CONF and $STATE (your settings, history and pairing) and your Keychain items. Delete them by hand if you want a clean slate."
  exit 0
fi

say "Checking this computer"
PY=""; for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || fail "Python 3.12 or newer is needed. Install it with:  brew install python@3.12   (https://brew.sh)  and run this again."
command -v git >/dev/null || fail "git is needed. Run:  xcode-select --install   and then this again."
command -v docker >/dev/null || fail "Docker Desktop is needed: https://www.docker.com/products/docker-desktop/  Install it, open it once, and run this again."
[ "$DRY" = 1 ] || docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Open Docker Desktop, wait until it says it is running, and run this again."
echo "ok: python $("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])'), git, docker"

say "Plow Latch (the link between Plow and this Mac)"
if [ -d "/Applications/Plow Latch.app" ]; then echo "already installed"
elif [ "$SKIP_LATCH" = 1 ]; then echo "skipped (--skip-latch)"
else
  TMP="$(mktemp -d)"; trap 'hdiutil detach "$TMP/mnt" -quiet 2>/dev/null || true; rm -rf "$TMP"' EXIT
  echo "downloading Plow Latch (about 450 MB)..."
  run curl -fL --progress-bar -o "$TMP/Plow.dmg" "$LATCH_URL"
  run mkdir -p "$TMP/mnt"; run hdiutil attach "$TMP/Plow.dmg" -nobrowse -quiet -mountpoint "$TMP/mnt"
  APP="$(ls -d "$TMP/mnt"/*.app 2>/dev/null | head -1 || true)"
  [ "$DRY" = 1 ] || [ -n "$APP" ] || fail "the Latch disk image had no app inside"
  run cp -R "$APP" /Applications/
  run hdiutil detach "$TMP/mnt" -quiet
  echo "installed. Open it from Applications and sign in to your Plow account (it asks for the usual macOS approval the first time)."
fi

say "The Door program"
run mkdir -p "$HOME_DIR" "$(dirname "$CONF")" "$STATE" "$HOME/Library/LaunchAgents"
run chmod 700 "$HOME_DIR" "$(dirname "$CONF")" "$STATE"
SELF_DIR=""; [ -f "${BASH_SOURCE[0]:-}" ] && SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # only when run as a file, never when piped
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/../pyproject.toml" ] && [ -d "$SELF_DIR/../door" ]; then
  SRC="$(cd "$SELF_DIR/.." && pwd)"; echo "using the copy next to this script: $SRC"
else
  SRC="$HOME_DIR/src"; echo "downloading $RELEASE_URL"
  run rm -rf "$SRC"; run mkdir -p "$SRC"
  if [ "$DRY" = 1 ]; then echo "[dry-run] download and unpack into $SRC"; else
    case "$RELEASE_URL" in file://*) cp "${RELEASE_URL#file://}" "$HOME_DIR/door.tar.gz";; *) curl -fsSL "$RELEASE_URL" -o "$HOME_DIR/door.tar.gz" || fail "could not download $RELEASE_URL";; esac
    tar -xzf "$HOME_DIR/door.tar.gz" -C "$SRC" --strip-components=1 || fail "the Door package is damaged"
    rm -f "$HOME_DIR/door.tar.gz"
  fi
fi
run "$PY" -m venv "$HOME_DIR/venv"
PRE_BUILD=0; [ -e "$SRC/build" ] && PRE_BUILD=1
run "$HOME_DIR/venv/bin/pip" install --quiet "$SRC"
if [ "$DRY" != 1 ]; then rm -rf "$SRC"/*.egg-info; [ "$PRE_BUILD" = 0 ] && rm -rf "$SRC/build" || true; fi
DOOR="$HOME_DIR/venv/bin/door-host"

say "The isolated runner (where answers are produced, with no access to the rest of this Mac)"
if [ "$SKIP_IMAGE" = 1 ]; then echo "skipped (--skip-image)"; else run docker build -q -t door-runner:0.3 "$SRC/runner" >/dev/null; echo "built door-runner:0.3"; fi

say "Three questions"
if [ -z "$REPO" ]; then
  REPO="$(ask "1/3  Which project may people ask about? Path to a git repository: " "")"
fi
REPO="${REPO/#\~/$HOME}"
[ -n "$REPO" ] || fail "no project given. Run again with --repo /path/to/your/project"
if [ -z "$ACCESS" ]; then
  HAS_OC=""; [ -f "$HOME/.local/share/opencode/auth.json" ] && HAS_OC=" (found on this Mac)"
  echo "2/3  How should the agent pay for the AI model?"
  echo "       1) the key OpenCode already keeps here$HAS_OC   2) my own Claude account (sign in)   3) an Anthropic API key"
  case "$(ask "     Choose 1, 2 or 3 [1]: " "1")" in 2) ACCESS="claude-login";; 3) ACCESS="api-key";; *) ACCESS="opencode";; esac
fi
if [ -z "$TASKS" ]; then
  case "$(ask "3/3  Let trusted people also have things DONE on the project (on a throwaway copy; risky steps ask you)? [y/N]: " "n")" in y|Y|yes) TASKS=1;; esac
fi
ARGS=(--repo "$REPO" --alias "$ALIAS" --access "$ACCESS"); [ -n "$TASKS" ] && ARGS+=(--tasks)
run "$DOOR" --policy "$CONF" --state "$STATE" init "${ARGS[@]}"

say "How the agent signs in to the AI model"
case "$ACCESS" in
  opencode)     [ -f "$HOME/.local/share/opencode/auth.json" ] || echo "OpenCode has no saved key on this Mac yet: open OpenCode, run /connect, and pick OpenCode Go.";;
  claude-login) echo "A browser window will ask you to sign in to your Claude account (inside Door's own sandbox; nothing is copied from elsewhere)."
                [ "$YES" = 1 ] || [ "$DRY" = 1 ] || "$DOOR" --policy "$CONF" --state "$STATE" login claude || echo "You can do this later with:  $DOOR login claude";;
  api-key)      echo "Create a key with a spend limit at console.anthropic.com. It will be kept in the macOS Keychain, never in a file."
                if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then security add-generic-password -U -a "$USER" -s door-anthropic-api-key -w || echo "You can do this later with:  security add-generic-password -U -a \"\$USER\" -s door-anthropic-api-key -w"; fi;;
esac

say "Starting it, and keeping it running"
WRAP="$HOME_DIR/door-host-run"
if [ "$DRY" != 1 ]; then
cat > "$WRAP" <<'WRAPEOF'
#!/bin/bash
# Keys live in the macOS Keychain, never in a file. Only the ones you stored are read.
get() { security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null || true; }
for pair in door-anthropic-api-key:DOOR_ANTHROPIC_API_KEY door-opencode-api-key:OPENCODE_API_KEY door-openai-api-key:OPENAI_API_KEY \
            door-openrouter-api-key:OPENROUTER_API_KEY door-deepseek-api-key:DEEPSEEK_API_KEY; do
  v=$(get "${pair%%:*}"); [ -n "$v" ] && export "${pair##*:}=$v"
done
exec "$HOME/.local/share/door/venv/bin/door-host" --policy "$HOME/.config/door/door.json" --state "$HOME/.local/state/door" serve
WRAPEOF
chmod 700 "$WRAP"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$WRAP</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$STATE/host.log</string><key>StandardErrorPath</key><string>$STATE/host.log</string>
</dict></plist>
PLISTEOF
else echo "[dry-run] write $WRAP and $PLIST"; fi
if [ "$NO_START" = 1 ] || [ "$DRY" = 1 ]; then echo "not started (--no-start / --dry-run). Start later with:  launchctl bootstrap gui/$(id -u) $PLIST"
else
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "running in the background; it starts again by itself after a restart"
fi

say "Checking everything"
if [ "$DRY" = 1 ]; then echo "[dry-run] door-host doctor"; else "$DOOR" --policy "$CONF" --state "$STATE" doctor || true; fi

say "Last step: connect this Mac to your Door agent"
cat <<NEXT
1. Open Plow Latch from Applications and make sure you are signed in to your Plow account.
2. Text your Door number:  Door Activate: <the code your Door agent shows>   (this makes you the owner)
3. Here, run:   $DOOR --policy $CONF --state $STATE pair
   and text the code it prints to your Door number as:  Door Pair: <code>
4. Then just write to your Door number: ask a question, or tell it something to do.
   Door Link <name> makes a chat link for someone else.

Anything wrong?  $DOOR --policy $CONF --state $STATE doctor
Remove it:       curl -fsSL <this script's address> | bash -s -- --uninstall
NEXT
