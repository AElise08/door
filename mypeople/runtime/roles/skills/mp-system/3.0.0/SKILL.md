---
name: mp-system
description: Mandatory MyPeople board, reporting, proof, and owner-obligation contract shared by every role.
metadata:
  version: 3.0.0
  load: startup
  required: true
---

# Operating MyPeople

This skill is mandatory startup knowledge for **every** role. The TODO card is the human-visible
source of truth; a terminal-only report is not a report.

Creating and controlling other agents is **not** part of this skill. Those commands belong to the
Boss and ship in `mp-boss-manager`.

## Identity and environment

- Your author identity is the full `$AGENT_ID` (`<host>/<session>:<tab>`). Never post as `CEO` or as
  another agent.
- The board/queue origin and the machine credential are handled for you by the `mp` CLI — you never
  build URLs, set headers, or pass the secret. Never print, store, or paste the queue secret into an
  artifact, roster, command report, or card comment.
- `$BOSS_ID` is the upstream agent for queue notifications when present.

## Read and report on the card

Read current board state before acting — no curl, no secret, no jq:

```sh
mp board                 # whole board as JSON (add --compact for one line)
mp card <task_id>        # a single card (exact id or unique prefix)
```

Post the understanding handshake, plan, meaningful progress, blockers, and final evidence to the
assigned card under your own identity. `mp comment` posts as `$AGENT_ID` automatically:

```sh
mp comment <task_id> "your message here"     # body as args …
some_command | mp comment <task_id>          # … or piped via stdin
```

Attach durable proof with `mp proof <task_id> <path-or-url> [note]`.

A screenshot or clip you produced lives on your local disk, and the board is served over http —
so a local path must be **uploaded**, not linked. Pass the path and `mp` uploads it; the proof is
then served by the board and renders on the card:

```sh
mp proof <task_id> /path/to/screenshot.png "what this proves"   # uploaded, renders on the card
mp proof <task_id> https://example.com/run/123 "CI run"         # external link proof
```

Never attach a `file://` URL or a bare local path as a link — the browser cannot load it from the
board and the card shows a broken proof. The board rejects those with an explanation.

Proof you attached is only proof once you have **seen it render on the board**. Open the card in a
browser and look at it before you call a done condition met.

Do not mark a card done unless the delegation grants that authority and its done condition is
actually proven.

## Supported operations

- `mp board [--compact]` — read the whole board (JSON).
- `mp card <task_id> [--compact]` — read one card.
- `mp comment <task_id> <body…>` — post a card comment as yourself (body from args or stdin).
- `mp proof <task_id> <path-or-url> [note]` — attach durable proof (local files are uploaded).

Never bypass these operations with ad-hoc raw tmux delivery or hand-rolled `curl` to the board. A
role may teach an operation while its policy still limits whether and where you can perform it.

## Owner obligations

One open TODO card has one lifetime owner. If you are that owner, you remain responsible across
every CEO follow-up and every completed turn until the CEO closes the card — a finished turn does
not end your ownership.

When blocked, post the concrete blocker and the smallest decision or external change needed. When
finished, post commands, results, file/commit references, and limitations on the card; then wait for
follow-ups while remaining owner.
