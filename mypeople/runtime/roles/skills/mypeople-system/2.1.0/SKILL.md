---
name: mypeople-system
description: Mandatory MyPeople board, messaging, agent-state, and owner-lifecycle operating contract.
metadata:
  version: 2.1.0
  load: startup
  required: true
---

# Operating MyPeople

This skill is mandatory startup knowledge. The TODO card is the human-visible source of truth; a
terminal-only report is not a report.

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

Attach durable proof with `mp proof <task_id> <url> [note]`. Do not mark a card done unless the
delegation grants that authority and its done condition is actually proven.

## Supported agent operations

- `mp board [--compact]` — read the whole board (JSON).
- `mp card <task_id> [--compact]` — read one card.
- `mp comment <task_id> <body…>` — post a card comment as yourself (body from args or stdin).
- `mp proof <task_id> <url> [note]` — attach durable proof.
- `mp status` — query agents and nodes.
- `mp send <agent_id> <message>` — deliver a message through MyPeople.
- `mp peek <agent_id>` — inspect the live pane through the supported interface.
- `mp spawn <agent_id> ...` — create an agent only when delegated and with the required role/lifecycle
  flags.
- `mp answer <agent_id> <N>` — answer a pending choice.
- `mp kill <agent_id> --reason <text>` — retire only an agent you are authorized to retire.
- `mp revive <agent_id>` — resume the recorded backend session and locked role.

Never bypass these operations with ad-hoc raw tmux delivery or hand-rolled `curl` to the board. A
role may teach an operation while its policy still limits whether and where you can perform it.

## Owner lifecycle

One open TODO card has one lifetime owner. An owner is spawned with `--owner-task <card_id>` and
remains responsible across every CEO follow-up and every completed turn until the CEO closes the
card. Do not spawn a replacement for a follow-up. `--temporary` agents cannot own cards. Closing a
card retires its owner; reopening requires a fresh explicit owner assignment.

When blocked, post the concrete blocker and the smallest decision or external change needed. When
finished, post commands, results, file/commit references, and limitations on the card; then wait for
follow-ups while remaining owner.
