#!/bin/bash
# The Claude login of this MyPlow's OWNER, fetched at boot from the owner's login server
# (plow-seedlab-seedbed-substrate lease/lease-server.py, POST /token). Nothing is in the image: the
# server hands the login only to agents on the owner's Plow account, so anyone else's install
# boots without one and is told so by text instead of failing silently.
#
#   claude-login.sh fetch   -> prints the token on stdout (exit 0), or texts why not (exit 1)
#
# Checked once, at boot -- no polling. A restart runs the check again, so the way back from any
# failure below is restarting the agent, and its first text after that says what is still wrong.
# ponytail: a login that expires while the agent runs is only noticed at its next boot (it goes
# quiet until then); upgrade path is the chat bridge re-checking when a text gets no answer.
set -u
BANK="${MYPLOW_CLAUDE_BANK:-https://delattre-server.mulley-firefighter.ts.net/claude-bank}"
TOLD="${MYPEOPLE_HOME:-/var/lib/mypeople}/state/claude-login-told"
AUTH=(-H "Authorization: Bearer ${PLOW_AGENT_TOKEN:-proxied}")
beacon(){ (curl -s -m 5 -X POST --data-binary "$(hostname 2>/dev/null) $*" "$BANK/beacon" >/dev/null 2>&1 &); }

# Text whoever deployed this agent, through the chat plugin as the package ships it.
say(){
  local plug
  plug="$(python3 -c 'import mypeople,os;print(os.path.join(os.path.dirname(mypeople.__file__),"runtime","plugins","plow-chat","plow-chat.py"))')"
  PLOW_CHAT_STATE_DIR="${TMPDIR:-/tmp}/claude-login-chat" python3 "$plug" reply "$1" >/dev/null 2>&1 \
    || echo "claude-login: could not text: $1" >&2
}
# Say each problem once per kind, not on every restart.
say_once(){ mkdir -p "$TOLD"; [ -e "$TOLD/$1" ] && return; touch "$TOLD/$1"; say "$2"; }

# The token works if one tiny real request succeeds on it.
works(){ CLAUDE_CODE_OAUTH_TOKEN="$1" timeout 120 claude -p "reply with OK" --model claude-haiku-4-5 >/dev/null 2>&1; }

EXPIRED="My Claude login stopped working, so I can't answer. Most likely it expired: it lasts about a \
year. The owner renews it by running 'claude setup-token' and saving the new login on the login server."

case "${1:-}" in
  fetch)
    # Every network call has a time limit: a call that stalls would otherwise hold the boot forever,
    # and the reasons below are only ever said if the attempt RETURNS.
    a=$(curl -fsS -m 20 "${AUTH[@]}" "$PLOW_API_BASE/v1/auth/index-identity" | python3 -c 'import json,sys;print(json.load(sys.stdin)["assertion"])' 2>/dev/null) || a=""
    beacon "identity $([ -n "$a" ] && echo ok || echo FAILED)"
    if [ -z "$a" ]; then
      # Not "not the owner": Plow didn't say who we are at all (down, slow, or no PLOW_API_BASE).
      say_once plow-unreachable "I couldn't reach Plow when I started, so I can't log in. Restart me and I'll try again."
      exit 1
    fi
    out=$(curl -sS -m 30 -w '\n%{http_code}' -X POST -H "Content-Type: application/json" \
          -H "X-Plow-Index-Assertion: $a" -d '{"holder": "'"$(hostname)"'"}' "$BANK/token")
    code="${out##*$'\n'}"; body="${out%$'\n'*}"
    beacon "token http=${code:-none}"
    case "$code" in
      200)
        tok=$(python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' <<<"$body")
        if works "$tok"; then rm -rf "$TOLD"; printf '%s' "$tok"; exit 0; fi
        say_once expired "$EXPIRED"; exit 1 ;;
      401)
        say_once not-owner "This MyPlow is a prototype that only works for its owner's Plow account. \
It has no Claude login for you, so it can't answer here."; exit 1 ;;
      503)
        say_once no-login "My owner hasn't saved a Claude login on their login server yet, so I can't \
answer. Restart me once they have."; exit 1 ;;
      *)
        say_once unreachable "I couldn't reach my owner's login server when I started (answer: ${code:-none}), \
so I can't answer. Restart me once it's back and I'll log in."; exit 1 ;;
    esac ;;
  skills)
    # The owner's personal skills, from the same server under the same check (lease/sync-skills.py
    # packs them on the owner's Mac). Private to the owner, so never in this public image. Best
    # effort: an agent without them still answers, so nothing here blocks the boot or texts anyone.
    a=$(curl -fsS -m 20 "${AUTH[@]}" "$PLOW_API_BASE/v1/auth/index-identity" | python3 -c 'import json,sys;print(json.load(sys.stdin)["assertion"])' 2>/dev/null) || a=""
    pack="$(mktemp)"
    code=$(curl -sS -m 60 -o "$pack" -w '%{http_code}' -X POST -H "Content-Type: application/json" \
           -H "X-Plow-Index-Assertion: $a" -d '{"holder": "'"$(hostname)"'"}' "$BANK/skills" 2>/dev/null)
    beacon "skills http=${code:-none}"
    [ "$code" = 200 ] && python3 - "$pack" "$HOME/.claude/skills" <<'EOF'
import os, shutil, sys, tarfile, tempfile
pack, dest = sys.argv[1], sys.argv[2]
managed = os.path.join(dest, ".from-owner")   # the skills this pack owns; any other skill is the agent's own
stage = tempfile.mkdtemp()
with tarfile.open(pack) as t:
    members = [m for m in t.getmembers() if (m.isfile() or m.isdir()) and not m.name.startswith(("/", "..")) and "/../" not in m.name]
    t.extractall(stage, members=members, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
new = sorted(os.listdir(stage))
os.makedirs(dest, exist_ok=True)
try:
    old = open(managed).read().split()
except OSError:
    old = []
for name in set(old) | set(new):              # replace each skill whole; drop what the owner dropped
    shutil.rmtree(os.path.join(dest, name), ignore_errors=True)
for name in new:
    shutil.move(os.path.join(stage, name), os.path.join(dest, name))
open(managed, "w").write("\n".join(new) + "\n")
print(len(new))
EOF
    rm -f "$pack" ;;
  *) echo "usage: claude-login.sh fetch|skills" >&2; exit 2 ;;
esac
