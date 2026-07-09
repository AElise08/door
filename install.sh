#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "[mypeople] root access is required to install host packages: $*" >&2
    return 1
  fi
}

install_host_deps() {
  local missing=()
  for cmd in python3 tmux ttyd asciinema git curl; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  [ ${#missing[@]} -eq 0 ] && return
  echo "[mypeople] missing: ${missing[*]}"
  if command -v brew >/dev/null 2>&1; then
    local brew_pkgs=()
    command -v tmux >/dev/null 2>&1 || brew_pkgs+=(tmux)
    command -v ttyd >/dev/null 2>&1 || brew_pkgs+=(ttyd)
    command -v asciinema >/dev/null 2>&1 || brew_pkgs+=(asciinema)
    [ ${#brew_pkgs[@]} -eq 0 ] || brew install "${brew_pkgs[@]}"
  elif command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y python3 tmux git curl asciinema ca-certificates
  fi
  if ! command -v ttyd >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    local arch asset sha
    arch="$(uname -m)"
    case "$arch" in
      x86_64|amd64) asset=x86_64; sha=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;;
      arm64|aarch64) asset=aarch64; sha=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;;
      *) asset="" ;;
    esac
    if [ -n "$asset" ]; then
      local tmp
      tmp="$(mktemp)"
      curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${asset}" -o "$tmp"
      python3 - "$tmp" "$sha" <<'PY'
import hashlib, sys
path, expected = sys.argv[1:]
actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
if actual != expected:
    raise SystemExit("ttyd checksum mismatch: %s" % actual)
PY
      as_root install -m 0755 "$tmp" /usr/local/bin/ttyd
      rm -f "$tmp"
    fi
  fi
  for cmd in python3 tmux ttyd asciinema git curl; do
    command -v "$cmd" >/dev/null 2>&1 || {
      echo "[mypeople] $cmd is still missing; install it and rerun ./install.sh" >&2
      exit 2
    }
  done
}

install_host_deps

if ! command -v claude >/dev/null 2>&1; then
  echo "[mypeople] installing Claude Code"
  curl -fsSL https://claude.ai/install.sh | bash
  export PATH="$HOME/.local/bin:$PATH"
fi

claude auth status >/dev/null 2>&1 || {
  echo "[mypeople] authenticate this machine, then rerun: claude auth login" >&2
  exit 2
}

if ! command -v uv >/dev/null 2>&1; then
  echo "[mypeople] installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

cd "$ROOT"
uv build --wheel --out-dir dist
WHEEL="$(ls -t dist/mypeople-*.whl | head -1)"
uv tool install --force "$WHEEL"
export PATH="$HOME/.local/bin:$PATH"
mypeople up --detach
mypeople status
echo "[mypeople] open http://localhost:${TODO_PORT:-9933}"
