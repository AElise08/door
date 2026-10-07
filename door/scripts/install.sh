#!/usr/bin/env bash
# Door for your Mac: one command installs Plow Latch (if missing), the Door daemon and the isolated runner, asks three questions,
# pairs this Mac with your Door number and checks everything. Nothing to install first: no Homebrew, no Python.
#
#   curl -fsSL https://raw.githubusercontent.com/AElise08/myplow-mel-s-version-/main/door/scripts/install.sh | bash
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

RELEASE_URL_DEFAULT="https://codeload.github.com/AElise08/myplow-mel-s-version-/tar.gz/refs/heads/main"   # the Door folder inside the repo
INSTALL_URL="https://raw.githubusercontent.com/AElise08/myplow-mel-s-version-/main/door/scripts/install.sh"
STARTED_AT=$(date +%s)
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
  [ -f "$PLIST" ] && launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true      # only the service this home folder installed
  rm -f "$PLIST" "$HOME/.local/bin/door"; rm -rf "$HOME_DIR"
  docker rmi door-runner:0.3 >/dev/null 2>&1 || true
  echo "Removed the program, the service and the runner image."
  echo "Kept: $CONF and $STATE (your settings, history and pairing) and your Keychain items. Delete them by hand if you want a clean slate."
  exit 0
fi

say "Checking this computer"
if ! git --version >/dev/null 2>&1; then
  xcode-select --install 2>/dev/null || true
  fail "git is needed. A macOS window just offered to install the developer tools: accept it, wait until it finishes, and run this again."
fi
# Docker runs the isolated runner. If it is installed but closed, open it and wait instead of giving up.
if [ "$SKIP_IMAGE" != 1 ] && [ "$DRY" != 1 ]; then
  if ! command -v docker >/dev/null && [ ! -d /Applications/Docker.app ]; then
    open "https://www.docker.com/products/docker-desktop/" 2>/dev/null || true
    fail "Docker Desktop is needed (it keeps people's questions away from the rest of this Mac). Its download page just opened: install it, open it once, and run this again."
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "starting Docker Desktop..."; open -a Docker 2>/dev/null || true
    for i in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
    docker info >/dev/null 2>&1 || fail "Docker did not start. Open Docker Desktop, accept its first-run questions, and run this again."
  fi
fi
# Python 3.12+: use one already here, otherwise fetch a private copy just for Door (it does not touch the system Python).
PY=""; for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ] && [ "$DRY" != 1 ]; then
  echo "this Mac has no Python 3.12 yet: getting a private copy for Door (about 20 MB, once)..."
  mkdir -p "$HOME_DIR/uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME_DIR/uv" UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || fail "could not download the Python helper (uv). Check the internet connection and run this again."
  export UV_PYTHON_INSTALL_DIR="$HOME_DIR/python"
  "$HOME_DIR/uv/uv" python install 3.12 >/dev/null 2>&1 || fail "could not download Python 3.12. Check the internet connection and run this again."
  PY="$("$HOME_DIR/uv/uv" python find 3.12)"
fi
[ -n "$PY" ] || PY=python3
echo "ok: python $("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?'), git$([ "$SKIP_IMAGE" = 1 ] || echo ', docker')"

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
  echo "installed."
fi
if [ "$SKIP_LATCH" != 1 ] && [ "$DRY" != 1 ] && ! pgrep -f "Plow Latch.app/Contents/MacOS" >/dev/null; then
  open -a "Plow Latch" 2>/dev/null || true
  ask "Plow Latch is opening: sign in to your Plow account there (macOS may ask for approval the first time), then press Enter here. " "" >/dev/null
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
    if [ ! -f "$SRC/pyproject.toml" ] && [ -f "$SRC/door/pyproject.toml" ]; then      # the whole repository: keep only the Door folder
      mv "$SRC/door" "$HOME_DIR/src.door" && rm -rf "$SRC" && mv "$HOME_DIR/src.door" "$SRC"
    fi
    [ -f "$SRC/pyproject.toml" ] || fail "the download did not contain Door"
  fi
fi
run "$PY" -m venv "$HOME_DIR/venv"
PRE_BUILD=0; [ -e "$SRC/build" ] && PRE_BUILD=1
run "$HOME_DIR/venv/bin/pip" install --quiet "$SRC"
if [ "$DRY" != 1 ]; then rm -rf "$SRC"/*.egg-info; [ "$PRE_BUILD" = 0 ] && rm -rf "$SRC/build" || true; fi
DOOR="$HOME_DIR/venv/bin/door-host"
# A short command for the owner:  door pair, door doctor, door pause ... (the long paths are filled in).
if [ "$DRY" != 1 ]; then
  mkdir -p "$HOME/.local/bin"
  printf '#!/bin/bash\nexec "%s" --policy "%s" --state "%s" "$@"\n' "$DOOR" "$CONF" "$STATE" > "$HOME/.local/bin/door"; chmod 755 "$HOME/.local/bin/door"
fi
SHORT="door"; case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) SHORT="$HOME/.local/bin/door";; esac

say "The isolated runner (where answers are produced, with no access to the rest of this Mac)"
if [ "$SKIP_IMAGE" = 1 ]; then echo "skipped (--skip-image)"; else run docker build -q -t door-runner:0.3 "$SRC/runner" >/dev/null; echo "built door-runner:0.3"; fi

say "Three questions"
if [ -z "$REPO" ] && [ "$YES" != 1 ]; then
  echo "1/3  Which project may people ask about? A window is opening to pick its folder."
  REPO="$(osascript -e 'POSIX path of (choose folder with prompt "Door: choose the project people may ask about (a git folder)")' 2>/dev/null || true)"
  REPO="${REPO%/}"
  [ -n "$REPO" ] || REPO="$(ask "     (no folder picked) Type the path to the project: " "")"
fi
REPO="${REPO/#\~/$HOME}"
[ -n "$REPO" ] || fail "no project given. Run again with --repo /path/to/your/project"
[ -d "$REPO/.git" ] || fail "$REPO is not a git project. Door shares only what is committed, so it needs git: inside that folder run  git init && git add -A && git commit -m start  and run this again."
git -C "$REPO" rev-parse --verify HEAD >/dev/null 2>&1 || fail "$REPO has no commits yet. Commit something first:  git -C \"$REPO\" add -A && git -C \"$REPO\" commit -m start"
echo "     project: $REPO"
if [ -z "$ACCESS" ]; then
  HAS_OC=""; [ -f "$HOME/.local/share/opencode/auth.json" ] && HAS_OC=" (found on this Mac)"
  echo "2/3  How should the agent pay for the AI model?"
  echo "       1) the key OpenCode already keeps here$HAS_OC   2) my own Claude account (sign in)   3) an Anthropic API key"
  case "$(ask "     Choose 1, 2 or 3 [1]: " "1")" in 2) ACCESS="claude-login";; 3) ACCESS="api-key";; *) ACCESS="opencode";; esac
fi
if [ -z "$TASKS" ]; then
  case "$(ask "3/3  Let trusted people also have things DONE on the project (on a throwaway copy; risky steps ask you)? [y/N]: " "n")" in y|Y|yes) TASKS=1;; esac
fi
if [ -n "$TASKS" ] && ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ]; then
  case "$(ask "     Tasks are done by Claude Code, which is not on this Mac. Install it now? [Y/n]: " "y")" in
    n|N|no) TASKS=""; echo "     tasks left off. Turn them on later in Door's Settings after installing Claude Code.";;
    *) [ "$DRY" = 1 ] || curl -fsSL https://claude.ai/install.sh | bash || { TASKS=""; echo "     could not install Claude Code: tasks left off for now."; };;
  esac
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
# A background service starts with a bare PATH. Remember where this Mac keeps the tools Door needs (docker, claude, opencode, git).
SVC_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PATH="$HOME/.local/bin:$PATH"
for tool in docker claude opencode codex git; do d="$(dirname "$(command -v "$tool" 2>/dev/null || echo /x/none)")"; [ -d "$d" ] && case ":$SVC_PATH:" in *":$d:"*) ;; *) SVC_PATH="$d:$SVC_PATH";; esac; done
if [ "$DRY" != 1 ]; then
cat > "$WRAP" <<'WRAPEOF'
#!/bin/bash
# Keys live in the macOS Keychain, never in a file. Only the ones you stored are read.
get() { security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null || true; }
for pair in door-anthropic-api-key:DOOR_ANTHROPIC_API_KEY door-opencode-api-key:OPENCODE_API_KEY door-openai-api-key:OPENAI_API_KEY \
            door-openrouter-api-key:OPENROUTER_API_KEY door-deepseek-api-key:DEEPSEEK_API_KEY; do
  v=$(get "${pair%%:*}"); [ -n "$v" ] && export "${pair##*:}=$v"
done
export PATH="__SVC_PATH__"
export PYTHONUNBUFFERED=1
export DOOR_SUPERVISED=1      # the background service restarts door-host when it exits (used by "Restart Door" in Settings)
exec "$HOME/.local/share/door/venv/bin/door-host" --policy "$HOME/.config/door/door.json" --state "$HOME/.local/state/door" serve
WRAPEOF
sed -i '' "s|__SVC_PATH__|$SVC_PATH|" "$WRAP"
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

say "Last step: connect this Mac to your Door number"
MINS=$(( ($(date +%s) - STARTED_AT + 59) / 60 ))
if [ "$NO_START" = 1 ] || [ "$DRY" = 1 ] || [ "$YES" = 1 ] || [ ! -r /dev/tty ]; then
  echo "1. In Plow, text your Door number:  Door Activate: <the code your Door agent shows>   (this makes you the owner)"
  echo "2. Then run:  $SHORT pair   and text what it prints to your Door number."
else
  echo "1. On your phone, text your Door number:  Door Activate: <the code your Door agent shows>   (this makes you the owner)"
  ask "   Press Enter when Door answered that you are the owner. " "" >/dev/null
  CODE=""
  for i in $(seq 1 15); do
    CODE="$("$DOOR" --policy "$CONF" --state "$STATE" pair 2>/dev/null | sed -n 's/^Pairing code[^:]*: *//p')"; [ -n "$CODE" ] && break; sleep 2
  done
  if [ -n "$CODE" ]; then
    printf 'Door Pair: %s' "$CODE" | pbcopy 2>/dev/null || true
    echo "2. Now text this to your Door number (it is already copied; valid 10 minutes):"
    echo
    echo "       Door Pair: $CODE"
    echo
    echo "   Door answers \"This Mac is paired\". Then just write to it: ask a question, or tell it something to do."
  else
    echo "2. Door is still starting. In a minute run:  $SHORT pair   and text what it prints."
  fi
fi
cat <<NEXT

Installed in about $MINS min. Door Link <name> (texted to your Door number) makes a chat link for someone else.
Settings on this Mac:  http://127.0.0.1:9631
Anything wrong?        $SHORT doctor
Remove it:             curl -fsSL $INSTALL_URL | bash -s -- --uninstall
NEXT
