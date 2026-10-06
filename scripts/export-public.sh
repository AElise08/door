#!/bin/bash
# Export one MyPlow release from this private working repo to the public github.com/delattre1/myplow.
#
#   scripts/export-public.sh vX.Y.Z
#
# The public repo has its own history: one commit per exported release, authored with the GitHub
# noreply address. This repo's history (personal author emails, internal notes) never leaves it.
# Steps: archive the tag's tree, drop private-only files, make the Claude login server a required
# setting instead of the owner's default, refuse to publish on any hit (personal emails, phone
# numbers, tailnet hosts, gitleaks), then commit and push. The scan runs gitleaks in Docker on
# delattre-server, since the owner's Mac runs no Docker.
set -euo pipefail
TAG="${1:?usage: scripts/export-public.sh vX.Y.Z}"
PUBLIC="${MYPLOW_PUBLIC_REPO:-delattre1/myplow}"
SCAN_HOST="${MYPLOW_SCAN_HOST:-delattre-server}"
ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG^{commit}" >/dev/null || { echo "no tag $TAG"; exit 1; }

gh repo clone "$PUBLIC" "$WORK/public" -- -q 2>/dev/null || git init -q -b main "$WORK/public"
find "$WORK/public" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git -C "$ROOT" archive "$TAG" | tar -x -C "$WORK/public"
rm -f "$WORK/public/scripts/export-public.sh"   # private tooling: it names what it scrubs
rm -rf "$WORK/public/.github"                   # private release pipelines: they sign and publish with the owner's secrets

# The cloud scripts default to the owner's own login server; the public tree requires the setting.
python3 - "$WORK/public" <<'PY'
import re, sys
from pathlib import Path
root, msg = Path(sys.argv[1]), "set MYPLOW_CLAUDE_BANK to your Claude login server URL"
for f in ["cloud/run.sh", "cloud/claude-login.sh", "cloud/entrypoint.sh"]:
    p = root / f; s, n = re.subn(r'BANK="\$\{MYPLOW_CLAUDE_BANK:-[^}]+\}"', f'BANK="${{MYPLOW_CLAUDE_BANK:?{msg}}}"', p.read_text())
    assert n == 1, f; p.write_text(s)
p = root / "cloud/update.py"; s = p.read_text()
s, n = re.subn(r'BANK = os\.environ\.get\("MYPLOW_CLAUDE_BANK", "[^"]+"\)', 'BANK = os.environ.get("MYPLOW_CLAUDE_BANK", "")  # your Claude login server; no beacons without it', s)
s, m = re.subn(r"    if beacon:  #", "    if beacon and BANK:  #", s)
assert n == 1 and m == 1, "cloud/update.py"; p.write_text(s)
PY

# Refuse to publish on any hit.
hits=$(grep -rIn -E 'daniieeldelattre|daniel@plow\.co|daniel@bion42|@bion42\.com|mulley-firefighter|\.ts\.net|delattre-server|daniels-macbook|delattres-mac-mini|\+(55|1)[ (]*[0-9]{2,3}[ )]*[0-9]{3,5}[ .-]?[0-9]{4}' "$WORK/public" --exclude-dir=.git \
  | grep -v -E '\+1 ?\(?555|\+1555' || true)   # 555 numbers are the tests' fictional ones
[ -z "$hits" ] || { echo "REFUSED: personal data in:"; echo "$hits"; exit 1; }
COPYFILE_DISABLE=1 tar --exclude=.git -czf "$WORK/tree.tgz" -C "$WORK/public" .
scp -q "$WORK/tree.tgz" "$SCAN_HOST:/tmp/myplow-export.tgz"
ssh -o BatchMode=yes "$SCAN_HOST" 'd=$(mktemp -d); tar -xzf /tmp/myplow-export.tgz -C $d 2>/dev/null; rm /tmp/myplow-export.tgz; docker run --rm -v $d:/repo zricethezav/gitleaks:latest dir /repo --redact --no-banner >/dev/null 2>&1; rc=$?; rm -rf $d; exit $rc' \
  || { echo "REFUSED: gitleaks found something (or could not run)"; exit 1; }

cd "$WORK/public"
git add -A
git -c user.name=delattre1 -c user.email=55804946+delattre1@users.noreply.github.com \
  commit -q -m "MyPlow ${TAG#v}" -m "Exported from the private working repo at $TAG."
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$PUBLIC.git"
git push -q -u origin main
git tag "$TAG" && git push -q origin "$TAG"
echo "published $TAG to https://github.com/$PUBLIC"
