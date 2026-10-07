# Door

**English** · [Português](#português)

**Let people talk to the AI that works on your code.** They text it, add it to a group chat, or open a link. It answers from your project
and, for the people you trust, it does the work and proves it was done.

### What you get
- **Answers from your own project.** Anyone you let in can ask how something works. Door replies from the project's files and says which
  ones it checked.
- **Work done, with proof.** People you trust can ask for changes. They happen on Door's own branch (`door/work`, each task builds on the last), never in your folder; risky steps wait for your OK, and a card
  reaches *Done* only when something really changed, your own checks passed and an independent check agrees.
- **Your computer stays closed.** Nothing connects in. Nobody gets a shell, your files or your keys.
- **You stay in charge.** Limits per person, a monthly budget, a pause button, and a log of everything that ran, kept on your Mac.

### See it
Example data, not a real project (the iMessage conversation is real, with a friend's address replaced by a fictional one).

**In iMessage.** You add the Door number to a group and text `Door Allow`. Door introduces itself; people ask; Door answers from the project
and names the files it checked. `Door Trust` lets someone have things done, once you confirm in your private chat. (The introduction has
since been reworded to explain how to talk to Door: start a message with "Door,".)

<img src="docs/img/imessage-group.png" width="640" alt="An iMessage group chat: Door Allow, Door introduces itself, a question answered, Door Trust">

In a group, people talk to each other and Door stays quiet until it is addressed:

```
 Pablo   did you see the game?                        (Door says nothing)
 Ana     Door, how do I get started?
 Door    Install the dependencies with npm install, copy .env.example to .env and run npm run dev.
         Checked in: README.md, package.json
 Ana     Door, add a license note to the README       (Ana was trusted with tasks, so it is done as a task)
 Ana     Door, help. Door, what changed?              (two requests in one message are answered one by one)
 Door    Got it. I'll do this and check the result.
```

No texting? People can use a **chat link** in the browser instead: no app, no account, one device per link.

**Your panel.** Every request becomes a card. A card moves to *Done* only with proof; "No changes" and failed checks go to *Review*.

<img src="docs/img/panel-board.png" width="760" alt="The board: To do, Doing, Review, Done">

You decide who is in, with limits per person, and you see every request and its result.

<img src="docs/img/panel-guests.png" width="760" alt="Guests: chat links, people with access, allow tasks or ask my OK">

<img src="docs/img/panel-hist.png" width="760" alt="History of requests and results">

**On your own Mac**, a page that only opens there shows what ran and what it cost, and holds the settings: which projects are shared,
what tasks may do, the model and the budget.

<img src="docs/img/local-activity.png" width="760" alt="Door on this computer: activity and usage">

<img src="docs/img/local-settings.png" width="760" alt="Door on this computer: settings">

### How it works
```
 Someone texts your Door number, opens a chat link, or talks in a group
        │   (Plow carries the text messages)
        ▼
 Door cloud agent: rules, limits, who may do what, your panel and board
        │   Plow relay ──► Plow Latch on your Mac (your Mac only ever dials out)
        ▼
 door-host on your Mac: checks every request again
        ├─ questions: an isolated container reads a clean copy of the project; the model key never enters it
        └─ tasks: Claude Code works on a throwaway git branch; risky steps wait for you; Door runs YOUR checks
        ▼
 The answer (or the result and its proof) goes back the same way
```
[Plow](https://plow.co) provides the phone line (SMS and iMessage, including groups) and runs the cloud part; **Plow Latch** is the app on your
Mac that connects it to Plow, by an outbound connection only.

### Who can do what
| | Ask questions | Have things done | Risky steps | Change settings |
|---|---|---|---|---|
| **You** | Yes, in plain words | Yes: anything that is not a question is a task, and it runs without asking you again | Dangerous ones are always refused | Yes |
| **People you trust** | Yes | Yes, on a throwaway copy; "create a file…", "fix…" is enough | Wait for your OK by text | No |
| **Anyone else you let in** | Yes | No | No | No |

Dangerous commands, secret files and anything outside the project copy are refused for everyone. If you ask Door to show you something on
your screen, it checks that a window really appeared before calling it done.

### Getting people in
`Door Link Ana` (a chat link that opens on one device and expires) · `Door Invite Ana` (a code to text) · in a group, `Door Allow` (Door
introduces itself) and `Door Trust` (lets them have things done, after you confirm in your private chat). **In a group Door answers only when
it is addressed**: start a message with "Door," or "@door".

### What you control
- **The panel**: board with a priority view, guests and links, history, cost, and **Settings**.
- **Door on this computer** (a page that only opens on your Mac): what ran and what it cost, steps waiting for your OK, and the same
  settings, plus a folder picker and guided sign-in.
- **Bringing Door's work into your project.** Text `Door Merge` (or press *Merge into main* on the board): Door lists the changes and files, asks for your YES by text, and merges only if your folder has no uncommitted changes and nothing conflicts. Until then everything stays on `door/work`.
- **Settings, from anywhere.** Budget and model apply at once. Adding or removing a project, and what tasks may do, wait for your YES by
  text, and your Mac checks every change again. The cloud only ever sees project names, never folder paths.

### Set it up
1. On your Mac, in Terminal:

   ```
   curl -fsSL https://raw.githubusercontent.com/AElise08/myplow-mel-s-version-/main/door/scripts/install.sh | bash
   ```

   Nothing to install first: if the Mac has no recent Python it gets a private copy for Door, it opens Docker Desktop and Plow Latch
   if they are closed, lets you pick the project folder in a normal macOS window, and can install Claude Code if you want tasks.
   At the end it pairs the Mac and copies the exact `Door Pair: <code>` text for you. `door doctor` tells you anything still missing.
2. In the cloud: run the Door image on one of your Plow lines (`plow-agents deploy --local --line ln_xxx`, or publish it on Plow).
3. Text the line `Door Activate: <code>`; the installer then gives you the `Door Pair` text. Done.

### Built on MyPeople and Plow
Door joins two things. **MyPeople** (the runtime of [MyPlow](../MYPLOW.md)) runs agent teams on your own machine: a Boss that routes work, a
priorities board, and "proof" that work was really done. **Plow** gives an agent a phone line. Door brings the MyPeople ideas to people
*outside* your machine.

Door is its own program: **it does not import or run any MyPeople code and does not need MyPeople installed.** It follows MyPeople's ideas
and the way MyPeople talks to Plow. This repository keeps the MyPeople parts it builds on:

| In MyPeople | What Door takes from it |
|---|---|
| `mypeople/runtime/plugins/plow-chat` (the Plow Chat bridge) | How an agent talks to Plow: the cloud-agent contract (`/v1/agents/cloud/me`), chats and groups, answering in the thread that asked. Door's [`plow.py`](door/plow.py) and [`plow_agent.py`](door/plow_agent.py) follow the same pattern. |
| `cloud/` (the cloud image) | How an agent image boots on a Plow line with no secrets inside. Door's [`cloud/Dockerfile`](cloud/Dockerfile) takes the same approach. |
| The Boss and engineers (`mypeople/runtime/mp-boss-doctrine.md`) | One agent decides who works on what. Door's "Boss" picks which agent answers; tasks go to a separate task agent. |
| The priorities board | Door's board: each request is a card that moves from To do to Done. |
| `mypeople/runtime/verify/` and "proof" | Door's rule that work is Done only with evidence. |
| Plow Latch | MyPeople already uses Latch to reach a Mac; Door reaches your Mac through the same Latch. |

The rest of this repository is MyPeople itself: the runtime (`mypeople/`), the desktop app (`desktop/`), the cloud image (`cloud/`),
`install.sh` and `docs/HOW-IT-WORKS.md`. Its original README is [`MYPLOW.md`](../MYPLOW.md). Door's own code is in `door/`.

### Status
Tested on a real Plow account (October 2026): activation and pairing by text, the image running on a Plow line, the Latch relay to the Mac,
questions answered by a real model in 20 to 30 seconds, a group chat with a second person, tasks done by the real Claude Code, and the
settings. What is not verified yet: [`READINESS.md`](docs/READINESS.md).

### What is left to finish
**Needs a decision or an account (not code)**
1. **A public address for the links.** Today they open only on the owner's Mac. Put the cloud part on a server with a domain and HTTPS.
2. **Publish the image** publicly (amd64) and ask Plow to list it in the agent index, so a customer can install it in one click. Decide the
   product name first: it becomes the public identifier.
3. **Terms, privacy policy, licence and pricing.** Billing is manual for now.

**Needs more work**
4. **Choose which project a conversation is about.** Several projects can be shared, but a person cannot yet pick one or be limited to one.
5. **Door's own text messages in both languages.** The guest chat page and the group introduction speak English and Portuguese; most other
   messages are English (the catalog is written in `door/i18n.py`, not wired in yet).
6. **The owner panel in Portuguese.**
7. **Faster answers.** Typically 20 to 30 seconds, mostly the model's slowest call.

**Still to test for real**
8. The installer on a **second Mac**, including downloading Plow Latch.
9. A trusted guest's task with the approval arriving by text, end to end on Plow.
10. **Own-subscription sign-in** and **Codex** (needs the owner's decision on its inner sandbox).
11. **Load**: one panel process serves tens of customers, not thousands.

---

## Português

**Deixe as pessoas conversarem com a IA que trabalha no seu código.** Elas mandam mensagem, colocam o Door num grupo ou abrem um link. Ele
responde a partir do seu projeto e, para quem você confia, faz o trabalho e prova que foi feito.

### O que você ganha
- **Respostas do seu próprio projeto.** Quem você deixar entrar pode perguntar como algo funciona. O Door responde a partir dos arquivos do
  projeto e diz quais conferiu.
- **Trabalho feito, com prova.** Quem você confia pode pedir mudanças. Elas acontecem na branch do próprio Door (`door/work`, cada tarefa continua da anterior), nunca na sua pasta; passos arriscados esperam o seu
  OK, e um cartão só chega em *Done* quando algo mudou de verdade, as suas verificações passaram e uma checagem independente concorda.
- **Seu computador continua fechado.** Nada se conecta nele. Ninguém recebe terminal, seus arquivos ou suas chaves.
- **Você continua no comando.** Limites por pessoa, orçamento do mês, botão de pausar e um registro de tudo que rodou, guardado no seu Mac.

### Veja funcionando
Dados de exemplo, não um projeto real (a conversa do iMessage é real, com o endereço de um amigo trocado por um fictício).

**No iMessage.** Você coloca o número do Door num grupo e manda `Door Allow`. O Door se apresenta; as pessoas perguntam; o Door responde a
partir do projeto e diz os arquivos que conferiu. `Door Trust` libera alguém para pedir tarefas, depois que você confirma no seu privado. (A
apresentação mudou desde esse print, para explicar como falar com o Door: começar a mensagem com "Door,".)

<img src="docs/img/imessage-group.png" width="640" alt="Grupo no iMessage: Door Allow, o Door se apresenta, uma pergunta respondida, Door Trust">

Num grupo, as pessoas conversam entre si e o Door fica quieto até ser chamado:

```
 Pablo   viu o jogo ontem?                            (o Door não diz nada)
 Ana     Door, como eu começo a usar?
 Door    Instale as dependências com npm install, copie .env.example para .env e rode npm run dev.
         Conferido em: README.md, package.json
 Ana     Door, coloca uma nota de licença no README   (a Ana foi liberada para tarefas, então vira tarefa)
 Ana     Door, help. Door, o que mudou?               (dois pedidos na mesma mensagem são respondidos um por um)
 Door    Entendi. Vou fazer isso e conferir o resultado.
```

Sem SMS? As pessoas podem usar um **link de chat** no navegador: sem app, sem conta, um aparelho por link.

**O seu painel.** Cada pedido vira um cartão. O cartão só vai para *Done* com prova; "No changes" e verificações que falharam vão para *Review*.

<img src="docs/img/panel-board.png" width="760" alt="O quadro: To do, Doing, Review, Done">

Você decide quem entra, com limites por pessoa, e vê cada pedido e o resultado.

<img src="docs/img/panel-guests.png" width="760" alt="Guests: links de chat, pessoas com acesso, liberar tarefas ou pedir meu OK">

<img src="docs/img/panel-hist.png" width="760" alt="Histórico de pedidos e resultados">

**No seu próprio Mac**, uma página que só abre ali mostra o que rodou e quanto custou, e guarda as configurações: quais projetos são
compartilhados, o que as tarefas podem fazer, o modelo e o orçamento.

<img src="docs/img/local-activity.png" width="760" alt="Door on this computer: atividade e uso">

<img src="docs/img/local-settings.png" width="760" alt="Door on this computer: configurações">

### Como funciona
```
 Alguém manda mensagem para o seu número do Door, abre um link de chat ou fala num grupo
        │   (o Plow leva as mensagens de texto)
        ▼
 Agente do Door na nuvem: regras, limites, quem pode o quê, seu painel e quadro
        │   relay do Plow ──► Plow Latch no seu Mac (o seu Mac só faz conexões de saída)
        ▼
 door-host no seu Mac: confere cada pedido de novo
        ├─ perguntas: um contêiner isolado lê uma cópia limpa do projeto; a chave do modelo nunca entra nele
        └─ tarefas: o Claude Code trabalha numa branch git descartável; passos arriscados esperam você; o Door roda as SUAS verificações
        ▼
 A resposta (ou o resultado e a prova) volta pelo mesmo caminho
```
O [Plow](https://plow.co) fornece a linha de telefone (SMS e iMessage, inclusive grupos) e roda a parte na nuvem; o **Plow Latch** é o app no seu
Mac que o liga ao Plow, só por conexão de saída.

### Quem pode o quê
| | Perguntar | Pedir tarefas | Passos arriscados | Mudar configurações |
|---|---|---|---|---|
| **Você** | Sim, em palavras normais | Sim: o que não for pergunta vira tarefa, e roda sem pedir autorização de novo | Os perigosos são sempre recusados | Sim |
| **Quem você confia** | Sim | Sim, numa cópia descartável; "cria um arquivo…", "corrige…" basta | Esperam o seu OK por mensagem | Não |
| **Qualquer outra pessoa que você deixar entrar** | Sim | Não | Não | Não |

Comandos perigosos, arquivos de chaves e qualquer coisa fora da cópia do projeto são recusados para todos. Se você pedir para o Door mostrar
algo na sua tela, ele confere que uma janela realmente apareceu antes de dar como feito.

### Como as pessoas entram
`Door Link Ana` (link de chat que abre em um aparelho e vence) · `Door Invite Ana` (código para mandar por SMS) · num grupo, `Door Allow` (o
Door se apresenta) e `Door Trust` (libera tarefas, depois que você confirma no seu privado). **Num grupo o Door só responde quando é
chamado**: comece a mensagem com "Door," ou "@door".

### O que você controla
- **O painel**: quadro com visão de prioridade, convidados e links, histórico, custo e **Settings**.
- **Door on this computer** (uma página que só abre no seu Mac): o que rodou e quanto custou, passos esperando o seu OK e as mesmas
  configurações, com seletor de pastas e login guiado.
- **Juntar o trabalho do Door no seu projeto.** Mande `Door Merge` (ou aperte *Merge into main* no quadro): o Door lista as mudanças e os arquivos, pede o seu YES por mensagem e só junta se a sua pasta não tiver alterações pendentes e não houver conflito. Até lá, tudo fica na `door/work`.
- **Settings, de qualquer lugar.** Orçamento e modelo valem na hora. Adicionar ou remover um projeto, e o que as tarefas podem fazer, esperam
  o seu YES por mensagem, e o seu Mac confere cada mudança de novo. A nuvem só vê os nomes dos projetos, nunca os caminhos das pastas.

### Como instalar
1. No Mac, no Terminal:

   ```
   curl -fsSL https://raw.githubusercontent.com/AElise08/myplow-mel-s-version-/main/door/scripts/install.sh | bash
   ```

   Não precisa instalar nada antes: se o Mac não tem um Python recente, ele baixa uma cópia só para o Door; abre o Docker Desktop e o
   Plow Latch se estiverem fechados; você escolhe a pasta do projeto numa janela normal do macOS; e ele instala o Claude Code se você
   quiser tarefas. No fim ele pareia o Mac e já copia o texto `Door Pair: <código>`. `door doctor` diz o que ainda falta.
2. Na nuvem: rode a imagem do Door numa linha do Plow (`plow-agents deploy --local --line ln_xxx`, ou publicando no Plow).
3. Mande para a linha `Door Activate: <código>`; o instalador então te dá o texto do `Door Pair`. Pronto.

### Feito sobre o MyPeople e o Plow
O Door junta duas coisas. O **MyPeople** (o motor do [MyPlow](../MYPLOW.md)) roda times de agentes na sua máquina: um Boss que distribui o
trabalho, um quadro de prioridades e a "prova" de que o trabalho foi feito. O **Plow** dá uma linha de telefone a um agente. O Door leva as
ideias do MyPeople para pessoas *de fora* da sua máquina.

O Door é um programa próprio: **ele não importa nem executa código do MyPeople e não precisa do MyPeople instalado.** Ele segue as ideias do
MyPeople e o jeito como o MyPeople conversa com o Plow. Este repositório guarda as partes do MyPeople em que ele se baseia:

| No MyPeople | O que o Door aproveita |
|---|---|
| `mypeople/runtime/plugins/plow-chat` (a ponte do Plow Chat) | Como um agente fala com o Plow: o contrato de agente na nuvem (`/v1/agents/cloud/me`), chats e grupos, responder na conversa de onde veio a pergunta. O [`plow.py`](door/plow.py) e o [`plow_agent.py`](door/plow_agent.py) do Door seguem o mesmo padrão. |
| `cloud/` (a imagem da nuvem) | Como a imagem de um agente sobe numa linha do Plow sem nenhum segredo dentro. O [`cloud/Dockerfile`](cloud/Dockerfile) do Door segue a mesma abordagem. |
| O Boss e os engenheiros (`mypeople/runtime/mp-boss-doctrine.md`) | Um agente decide quem trabalha em quê. O "Boss" do Door escolhe qual agente responde; as tarefas vão para um agente de tarefas separado. |
| O quadro de prioridades | O quadro do Door: cada pedido é um cartão que anda de To do até Done. |
| `mypeople/runtime/verify/` e a "prova" | A regra do Door de que o trabalho só está Done com evidência. |
| Plow Latch | O MyPeople já usa o Latch para chegar a um Mac; o Door chega ao seu Mac pelo mesmo Latch. |

O resto deste repositório é o próprio MyPeople: o motor (`mypeople/`), o app de desktop (`desktop/`), a imagem da nuvem (`cloud/`), o
`install.sh` e o `docs/HOW-IT-WORKS.md`. O README original é o [`MYPLOW.md`](../MYPLOW.md). O código do Door fica em `door/`.

### Situação
Testado numa conta Plow de verdade (outubro de 2026): ativação e pareamento por SMS, a imagem rodando numa linha do Plow, a ponte do Latch até
o Mac, perguntas respondidas por um modelo real em 20 a 30 segundos, um grupo com uma segunda pessoa, tarefas feitas pelo Claude Code de
verdade e as configurações. O que ainda não foi verificado: [`READINESS.md`](docs/READINESS.md).

### O que falta finalizar
**Precisa de decisão ou de conta (não é código)**
1. **Um endereço público para os links.** Hoje só abrem no Mac da dona. Colocar a parte da nuvem num servidor com domínio e HTTPS.
2. **Publicar a imagem** (amd64) e pedir ao Plow para listá-la no índice de agentes, para o cliente instalar com um clique. Decida antes o nome
   do produto: ele vira o identificador público.
3. **Termos, política de privacidade, licença e preço.** A cobrança é manual por enquanto.

**Falta trabalho**
4. **Escolher sobre qual projeto é a conversa.** Dá para compartilhar vários, mas a pessoa ainda não escolhe um nem fica limitada a um só.
5. **As mensagens do próprio Door nos dois idiomas.** A página de chat do convidado e a apresentação do grupo falam inglês e português; a
   maioria das outras mensagens é em inglês (o catálogo está em `door/i18n.py`, ainda não ligado).
6. **O painel da dona em português.**
7. **Respostas mais rápidas.** Normalmente 20 a 30 segundos, principalmente a chamada mais lenta do modelo.

**Ainda falta testar de verdade**
8. O instalador num **segundo Mac**, inclusive baixando o Plow Latch.
9. A tarefa de um convidado de confiança com a aprovação chegando por SMS, de ponta a ponta no Plow.
10. **Login com a própria assinatura** e **Codex** (precisa da decisão da dona sobre o isolamento interno dele).
11. **Carga**: um processo de painel serve dezenas de clientes, não milhares.

---

# Technical reference (English)

| Part | Where | What it does |
|---|---|---|
| `door/cloud.py`, `plow.py`, `plow_agent.py`, `service.py` | cloud | rules, codes, groups, state, messages, the Plow cloud-agent loop |
| `panel/` (Swift, no dependencies) | cloud | the owner panel, chat links (English and Portuguese), operator admin API |
| `door/host.py`, `sandbox.py`, `proxy.py`, `exporter.py`, `outfilter.py`, `act.py` | your Mac | re-check, clean export, container, key-swapping proxy, reply filter, tasks, audit log |
| `door/local_ui.py`, `settings.py` | your Mac | "Door on this computer": activity, approvals and settings |
| `scripts/install.sh`, `scripts/build-release.sh` | your Mac | the one-line installer and the package it downloads |
| `deploy/`, `docs/OPERATOR.md` | operator | hosting templates and the onboarding/billing runbook |
| `tests/` | | 300+ tests, including real Docker isolation and an end-to-end run through the real panel |

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

