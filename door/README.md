# Door

**Let people talk to the AI agent that works on your code: by text message, in a group chat, or through a chat link.**
They ask questions and get answers from the project itself. People you trust can also ask for things to be done, and Door
proves the work was really done before it calls it finished. Your computer never opens a port and nobody gets a shell, your files or your keys.

Built on [Plow](https://plow.co): a Plow phone line is the agent's number, and Plow Latch is the outbound link to your Mac.

## How it works

```
 Someone texts your Door number / writes in a chat link / talks in a group
        │
        ▼
 Door cloud agent (a Plow cloud-agent image: door/cloud.py, panel/)      ← rules, limits, who may do what, your panel
        │  Plow relay ──► Plow Latch on your Mac (outbound connection only)
        ▼
 door-host on your Mac                                                    ← checks every request again, signed by the cloud
        ├─ questions: an isolated container reads a clean copy of the project; the model key never enters it
        └─ tasks: Claude Code works on a throwaway git branch; risky steps wait for you; Door runs YOUR checks
        │
        ▼
 The answer (or the result + proof) goes back the same way
```

**What people can do**
- **Ask** anything about the project. Answers say which files they come from, and Door checks those files exist. By default they are
  answered right away, within daily limits and your monthly budget; you can switch to approving each question.
- **Have things done**, only if you allowed it: the work happens on a copy, on a new branch, never on your real folder. A card on the board
  follows it and moves to **Done** only when something really changed, your checks passed and an independent check agrees.
- **You**, the owner, just write to your agent: a question gets an answer, anything else is treated as a task.

**How people get in**
- `Door Link Ana` (by text): a chat link that opens in the browser, on one device, and expires.
- `Door Invite Ana`: a code they text to the number.
- In a group: `Door Allow` turns Door on for everyone there (it introduces itself); `Door Trust` lets them have things done, after you confirm
  with a code in your private chat.

**What you see**: a panel (board with a priority view, guests and links, history, cost) and, on your Mac, a local page of everything that ran.

## Try it

| Where | Command |
|---|---|
| Your Mac | `curl -fsSL <where you host it>/install.sh \| bash` (installs Plow Latch if missing, Door, the isolated runner; asks 3 questions) |
| Check | `door-host doctor` says exactly what is missing |
| Cloud | `cloud/Dockerfile` is the Plow cloud-agent image; `plow-agents deploy --local --line ln_xxx` runs it on one of your Plow lines |
| Pair | text `Door Activate: <code>` then `Door Pair: <code>` to the line |

Engines: Claude Code, OpenCode or Codex, paid by an API key (kept in the macOS Keychain) or by your own sign-in.
The status of what has been verified for real, and what has not, is in [`docs/READINESS.md`](docs/READINESS.md).

## Parts

| Part | Where | What it does |
|---|---|---|
| `door/cloud.py`, `plow.py`, `plow_agent.py`, `service.py` | cloud | rules, codes, groups, state, messages, the Plow cloud-agent loop |
| `panel/` (Swift, no dependencies) | cloud | the owner panel, chat links (English and Portuguese), operator admin API |
| `door/host.py`, `sandbox.py`, `proxy.py`, `exporter.py`, `outfilter.py`, `act.py` | your Mac | re-check, clean export, container, key-swapping proxy, reply filter, tasks, audit log |
| `scripts/install.sh`, `scripts/build-release.sh` | your Mac | the one-line installer and the package it downloads |
| `deploy/`, `docs/OPERATOR.md` | operator | hosting templates and the onboarding/billing runbook |
| `tests/` | | 290+ tests, including real Docker isolation and an end-to-end run through the real panel |

## Tasks: letting a trusted person have things done (the "act" level)
Everyone starts as **questions only**. In the panel you can mark a person as *can run tasks*, or use `Door Trust` in a group (confirmed in your private chat). They then
write `Do: add a footer to index.html` (or press "Ask the agent to do this" on a board card) and:
1. Claude Code, **on your computer**, works in a **throwaway copy** of the project on a new git branch `door/...`. Your real folder is never touched
   and nothing is pushed.
2. Reading and editing inside that copy is free. Dangerous or secret-touching actions are refused outright; commands you pre-allowed run; anything
   else **waits for your OK** (panel, local screen or `YES 1234` by text). No answer means no.
3. Claude and your check commands run with a minimal environment: no API keys, no ssh agent, nothing else from your shell (`act.env` passes specific
   variables on purpose).
4. **Door then checks the delivery itself**: the real diff, **your** check commands (tests, linters; the model cannot choose or skip them) and an
   independent read-only checker that only sees that evidence. A card moves to **Done** only when something really changed, your checks passed and the
   checker agrees. Otherwise it goes to **Review** with the reason (`failed_checks`, `unverified`, `no_changes`, `incomplete`).

```json
"agents": [{"alias": "dev", "exports": [...], "act": {
  "project": "~/code/app", "allow_commands": ["git status", "git diff"], "bash": "ask",
  "proof": {"commands": ["python -m pytest -q"], "timeout_s": 300}, "timeout_s": 900}}]
```

## The board
A kanban (To do, Doing, Review, Done) with a **priority matrix** view (urgent x important). Each person sees only their own cards on their chat link
and sets their own priority; you see everything. Tasks create and move their own cards.

## Giving access by texting your agent
`Door Link Ana` (a chat link comes back by text), `Door Invite Ana` (a code to forward), `Door Guests`, `Door Revoke Ana`, `Door Panel` (a one-time
sign-in link to the panel). These only create question-level access.

## On your computer
`door-host serve` prints a private link to **Door on this computer**: what ran, the question and answer, tokens and cost, what is waiting for you, and a
pause button. `door-host doctor` checks every link a working setup needs and says what is missing.

## Run it as a Plow cloud agent
`cloud/Dockerfile` builds the one-click image (the panel is compiled for Linux inside it). Nothing secret is configured: Plow sets `PLOW_API_BASE`, its
proxy swaps the placeholder token, and the conversations and the relay to your Mac come from `GET /v1/agents/cloud/me`. `door-plow-agent --check`
verifies the wiring. See `docs/READINESS.md` for what has and has not been verified against the real Plow.

## Engines and providers
Each agent picks an **engine** (`backend`), and the policy picks one model **provider** (`egress.provider`). The engine runs inside the
isolated container; the provider's API key never does (the proxy adds it).

| engine | wire format | works with provider | status |
|---|---|---|---|
| `claude` (Claude Code) | anthropic | `anthropic` | tested with the real CLI and a real model |
| `opencode` | openai chat | `opencode-go`, `openai`, `openrouter`, `deepseek`, `custom` | tested in the real container, with a hostile fake model and with a real model (DeepSeek V4.1 via OpenCode Go) |
| `codex` | openai responses | `openai`, `custom` | built and checked against the real CLI; **blocked on one decision** (see below) |

`credential_source`: `env` (default, the variable named by `credential_env`) or `opencode-auth` (reuse the **API key** OpenCode already
keeps on this computer for that provider; OAuth logins are never reused). Prices are required for every provider except Anthropic, because a
cost cannot be guessed. See `door.example.opencode.json`.

**Codex:** its own sandbox (bubblewrap) cannot start inside an unprivileged container, so its shell, and reading files with it, needs that inner
sandbox turned off, leaving the container as the only boundary. That is the owner's call; until it is made the Codex tests are skipped.

## Sign in with your own account (subscription) instead of an API key
`"egress": {"mode": "login"}` makes each engine use **its own sign-in** (Claude Code, Codex, OpenCode) instead of an API key.

```
door-host login claude          # opens the sign-in inside Door's sandbox; follow the link it prints
door-host login claude --status # signed in or not
door-host login claude --forget # delete Door's sign-in
```
- The sign-in lives in a Door-only Docker volume (`door-login-<engine>`). **Nothing is copied from the sign-in already on your computer.**
- The container reaches its provider only through a tunnel limited to that provider's own hosts, for that run only. The tunnel refuses
  every other host, private and metadata addresses, and any run that is not currently bound.
- **No per-token cost control** in this mode: a run is limited by its time, the engine's step cap and each guest's daily request limit.
  Your subscription's own limits apply.
- The sign-in is inside the container while the agent works, so use this mode for people you trust. Whether a personal subscription may serve
  other people is a question for the provider's terms; Door makes it an explicit, per-installation choice.
- Codex in this mode has the same open decision as in API mode (below).

## Knowing when NOT to answer
Three layers, all optional to tune (`door.example.opencode.json` shows the fields):
1. **Before any model runs** (free): `guardrails.blocked_patterns` (your own regexes) plus a built-in list of takeover phrases such as
   "ignore all previous instructions" (`block_prompt_injection`, on by default). A match gets your `guardrails.refusal` text and costs nothing.
2. **In the agent's instructions**: `agent.scope` (for example "billing and invoices only") plus fixed behavior rules. Outside the scope the agent
   replies `OUT_OF_SCOPE`.
3. **On the answer**: an `OUT_OF_SCOPE` reply is replaced by your refusal text, so the guest never sees the agent's own explanation.
Each question is answered in a fresh container with no memory of other guests or earlier questions.

## How people get in
Three ways, all owner-controlled:
1. **Invite code.** In the panel (Guests → Invite someone) create a one-time code and send it to the person. They text
   `Door Join: ABCD-EFGH` to your Door number, in a 1:1 chat or inside a group. Codes expire (7 days by default), work once, and
   guessing is throttled (5 wrong tries per hour per phone, then silence).
2. **Ask for access.** A stranger texts `Door Request: their name`. You see it in the panel and choose *Let in* or *Ignore*.
   Nothing from a stranger ever reaches the agent.
3. **Group chats.** Add the Door number to a group and text `Door Allow`: everyone there is let in and Door introduces itself. You keep
   being the owner inside the group. The agent answers there **only if every participant is you or an active guest** (otherwise it stays
   silent and tells you once a day). iMessage members who use an Apple ID email instead of a phone number work too. Approvals and
   `Door Trust` confirmations only come from your private chat or the panel.

## Several agents and the Boss
With two or more agents in `door.json` (`door.example.multi.json`) a **Boss** coordinates them. Each approved question goes to the
Boss first; the Boss picks which agent answers. Guests can skip it with `@alias question`.

- The Boss runs in its own throwaway container with an **empty** `/work`, no read tools and no shell. It can only write one word.
- Whatever it writes must match an alias from your list. Anything else (including attempts to inject instructions) falls back to the
  first agent. It cannot invent an agent, pick a path, or reach files.
- The chosen agent then runs exactly like a single agent: only its own export, read-only, no network except the model.
- Boss cost is counted in the same per-question, per-guest and monthly budgets. Everything is in the audit log (`routed` event).

## Run the tests
```
cd panel && swift build && swift run panel-tests && cd ..     # panel (17 checks)
python3.12 -m venv .venv && .venv/bin/pip install -e .       # needs cryptography + websockets
PYTHONPATH=. .venv/bin/python -m unittest tests.test_v03 tests.test_door_link tests.test_boss
docker build -t door-runner:0.3 runner/ && bin/door-host --policy door.json selftest   # real isolation check
```
`tests.test_door_link` starts the real Swift panel and talks to it from the Python agent.

## Run the panel locally
```
DOOR_PANEL_OWNER_TOKEN=<24+ chars> DOOR_PANEL_AGENT_TOKEN=<24+ chars, different> DOOR_PANEL_PORT=9630 panel/.build/debug/door-panel
```
Multi-customer mode: set `DOOR_PANEL_ADMIN_TOKEN` (32+ chars) and `DOOR_PANEL_DATA=/path/tenants.json` instead.

## Status
Tested for real on the owner's own Plow account (October 2026): activation and pairing by text, the Plow cloud-agent image running on a
Plow line, the Latch relay to the Mac, questions answered by a real model through the isolated container (about 20 seconds), a group chat
with a second person answered, and a task done by the real Claude Code on a throwaway branch. Details, open items and known limits are in
[`docs/READINESS.md`](docs/READINESS.md). Billing is manual (see `docs/OPERATOR.md`).
