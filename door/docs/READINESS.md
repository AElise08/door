# Is Door ready to sell? An honest status

Last full test pass: **303 Python tests (3 skipped), 33 Swift checks on macOS and on Linux (inside Docker)**.
"Verified" below means a test or a real run showed it. Anything that needs an account, a person or a paid service we do not have is listed
separately as **not verified**; those are the real distance to a paying customer.

## Verified by tests and real runs on this computer
| Area | What was shown |
|---|---|
| Container isolation | Real Docker: no `~/.ssh`/`.env`, read-only root, no direct internet, no real key in the environment. A scripted *hostile* model could not run commands, read outside the project, reach the web or write outside its folder (OpenCode). |
| Real model, questions | DeepSeek V4.1 through OpenCode Go: correct answers, follow-up questions that need memory, refusal of a prompt-injection attempt, refusal of off-topic questions with the owner's own words. |
| Cost control | Exact token metering at the proxy, per-question / per-guest / monthly caps, hard stop. A call whose usage is not reported stops the run. |
| Tasks ("act") | Fake Claude speaking the real `--permission-prompt-tool` protocol: work on a throwaway branch, refusals, owner approval of steps (by panel, text or local screen), no-answer = no, timeout, cancel, minimal environment (no keys), proof commands run by Door, independent check, verdict matrix. The owner's real folder stayed untouched in every test. |
| Whole flow | Real Swift panel + real cloud agent + real host + real git: a guest's card becomes a task, a step waits for the owner, Door checks the delivery, the card moves to Done with proof (or to Review with the reason). A failed check never reaches Done. |
| Panel | Login, throttled guessing (per client, so a stranger cannot lock the owner out), sessions, CSRF protections, single-device chat links, kanban and priority matrix, tenants isolated from each other, hashed tokens, persistence across restarts. **Built and tested on Linux too.** |
| Hostile traffic | Malformed requests, oversized bodies, slow/idle connections (capped), odd paths, many parallel users: the panel kept serving real users. |
| Plow cloud agent | Against a pretend Plow that speaks the contract MyPlow's working bridge uses: activation by text, pairing the Mac through the relay URL, link and invite by text, a person joining by link and another by code, answers to the right chat only, groups answering only when everyone in them is trusted, "no Mac connected" handled. |
| Packaging | The Mac installer ran for real in a throwaway home (private folders, valid launch service, keys read from the Keychain only if present, no leftovers). The cloud image builds, boots two processes as a normal user, keeps secrets out of logs, and stops if the panel dies (so Plow restarts it). |
| Diagnostics | `door-host doctor` and `door-plow-agent --check` report every missing link and never print a key. |

## Verified on the real Plow, with the owner's account (October 2026)
- The Door image deployed on a Plow line with `plow-agents deploy --local`; activation (`Door Activate`) and pairing (`Door Pair`) by text.
- The cloud agent reaching the Mac through Plow's relay to Plow Latch (`plow_run_command`), and answers coming back by text and chat link.
- A real question answered by DeepSeek V4.1 (OpenCode Go) through the isolated container, with the files it used checked: about 20 seconds.
- A group chat: `Door Allow`, Door introducing itself, and a second person (an iMessage Apple ID) asking and getting an answer.
- A task done by the real Claude Code on a throwaway branch, with Door's own checks and an independent check.
- Door running as a macOS background service, and the Settings page (projects, tasks and permissions, model, budget) applied live.
- Bugs these real tests found and fixed: the cloud's plan started inactive; the owner's id was rejected by the Mac; Latch's sandbox needed
  network access for the local socket; replies were cut mid-word and full of Markdown; Apple ID members were ignored; the relay container
  could disappear (it is now recreated before each run); the panel signed people out on every restart.

## NOT verified yet
1. **Publishing on the Plow agent index** (a public image, amd64 build, and Plow admitting it). Tested only with a locally run image.
2. **Someone else's Mac.** The one-line installer was tested in a throwaway home folder, not yet on a second computer.
3. **Sign-in mode** (an own subscription instead of an API key): the plumbing is tested; nobody has signed in yet. Whether a personal
   subscription may serve other people is a question for each provider's terms.
4. **Codex** inside a container needs the owner's decision to turn off its own inner sandbox.
5. **Load at scale.** One panel process; fine for tens of customers, not thousands.
6. **Door's own messages in Portuguese.** The guest chat page and group introduction speak Portuguese; most text messages are still English.
7. **People and paper.** Terms, privacy policy, data-processing agreement (`docs/LEGAL-CHECKLIST.md`), a licence, support, pricing.

## Known limits (by design, written down so nobody is surprised)
- Answers are checked against files only when the agent cites them (`verification` setting). Task delivery is checked by evidence, not by trust.
- One thing runs at a time per computer.
- In task mode the agent runs on the owner's computer outside a container. The throwaway branch, the refusal rules, the approvals and the minimal
  environment are what contain it; a person you trust is still part of the safety model.
- Sign-in mode has no per-token cost control.

## What is left to finish
The full list, with what needs a decision and what needs work, is in the README ("What is left to finish" / "O que falta finalizar").
In order: a public address for the links, publishing the image to the Plow agent index, Door's own messages in both languages,
choosing which project a conversation is about, then the first customer's Mac with the one-line installer.
