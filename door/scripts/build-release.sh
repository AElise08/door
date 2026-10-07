#!/usr/bin/env bash
# Builds dist/door-mac.tar.gz: what the Mac installer downloads. Upload it (and scripts/install.sh) wherever the one-line command points.
# Contains only what a customer's Mac needs: the daemon, the runner image recipe, docs. Not the cloud panel, tests or your own settings.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"(.*)".*/\1/')"
mkdir -p dist; OUT="dist/door-mac.tar.gz"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
NAME="door-$VERSION"; mkdir -p "$STAGE/$NAME"
cp -R door runner plugin pyproject.toml README.md door.example*.json "$STAGE/$NAME/"
mkdir -p "$STAGE/$NAME/scripts" && cp scripts/install.sh "$STAGE/$NAME/scripts/"
find "$STAGE" \( -name __pycache__ -o -name '*.egg-info' -o -name '.DS_Store' -o -name '*.pyc' \) -prune -exec rm -rf {} +
# refuse to ship anything that looks like a secret
if grep -rIE "AKIA[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----" "$STAGE" >/dev/null; then echo "error: a secret-looking string is in the package" >&2; exit 1; fi
tar -czf "$OUT" -C "$STAGE" "$NAME"
echo "built $OUT ($(du -h "$OUT" | cut -f1)), version $VERSION"
shasum -a 256 "$OUT"
