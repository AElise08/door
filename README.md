# Door

**English** · [Português](#português)

Door lets other people talk to the AI agent that works on your code: **by text message, in a group chat, or through a chat link**.
They ask questions and get answers from the project itself. People you trust can also ask for things to be done, and Door proves the
work was really done before it calls it finished. Your computer never opens a port, and nobody gets a shell, your files or your keys.

### What Door is made of
Door joins two things:
- **MyPeople** (the runtime of [MyPlow](MYPLOW.md)): agent teams on your own machine with a Boss that routes work, a priorities board,
  and "proof" that work was really done. Door brings these ideas to people *outside* your machine: the board where requests become cards,
  the Boss that picks which agent answers, and delivery checked by evidence instead of by trust.
- **[Plow](https://plow.co)**: a phone line for the agent (SMS and iMessage, including group chats), a place to run the cloud part as a
  Plow cloud agent, and **Plow Latch**, the app on your Mac that connects it to Plow by an outbound connection only.

```
 Someone texts your Door number / writes in a chat link / talks in a group
        │   (Plow carries the text messages)
        ▼
 Door cloud agent: rules, limits, who may do what, your panel, the board
        │   Plow relay ──► Plow Latch on your Mac (your Mac only dials out)
        ▼
 door-host on your Mac: checks every request again (signed by the cloud)
        ├─ questions: an isolated container reads a clean copy of the project; the model key never enters it
        └─ tasks: Claude Code works on a throwaway git branch; risky steps wait for you; Door runs YOUR checks
        ▼
 The answer (or the result and its proof) goes back the same way
```

### Door and MyPeople: what is shared and what is not
Door is its own program: **it does not import or run any MyPeople code, and it does not need MyPeople installed.** It is built from
MyPeople's ideas and follows the way MyPeople talks to Plow. Door's own code is in [`door/`](door/); the MyPeople runtime it is modelled on
stays in this repository.

| In MyPeople (this repository) | What Door takes from it |
|---|---|
| `mypeople/runtime/plugins/plow-chat` (the Plow Chat bridge) | How an agent talks to Plow: the cloud-agent contract (`/v1/agents/cloud/me`), chats and groups, answering in the thread that asked. Door's [`door/door/plow.py`](door/door/plow.py) and [`door/door/plow_agent.py`](door/door/plow_agent.py) follow the same pattern. |
| `cloud/` (MyPeople's cloud image) | How an agent image boots on a Plow line with no secrets inside (for example, clearing the entrypoint because Plow boots the image's own command). Door's [`door/cloud/Dockerfile`](door/cloud/Dockerfile) takes the same approach. |
| The Boss and the engineers (`mypeople/runtime/mp-boss-doctrine.md`) | One agent that decides who works on what. Door's "Boss" picks which agent answers a question; tasks go to a separate task agent. |
| The priorities board | Door's board: each request becomes a card that moves from To do to Done, with a priority view. |
| `mypeople/runtime/verify/` and the idea of "proof" | Door's rule that work is Done only with evidence: real changes, the owner's own checks, and an independent check. |
| Plow Latch | MyPeople already uses Latch to reach a Mac; Door reaches the owner's Mac through the same Latch. |

What stays in this repository for MyPeople itself: the runtime (`mypeople/`), the desktop app (`desktop/`), the cloud image (`cloud/`),
`install.sh`, the Docker files and `docs/HOW-IT-WORKS.md`. The original MyPlow README is [`MYPLOW.md`](MYPLOW.md). Door's own code is in `door/`.

### What people can do
- **Ask** anything about the project. Answers say which files they come from, and Door checks those files exist. They are answered right
  away, within daily limits and your monthly budget (or you approve each one, if you prefer).
- **Have things done**, only if you trust them: the work happens on a copy, on a new branch, never in your real folder. A card follows it
  and moves to **Done** only when something really changed, your checks passed and an independent check agrees.
- **You**, the owner, just write to your agent: a question gets an answer, anything else becomes a task.

### How people get in
`Door Link Ana` (a chat link that opens on one device and expires) · `Door Invite Ana` (a code to text) · in a group, `Door Allow`
(Door introduces itself) and `Door Trust` (lets them have things done, after you confirm in your private chat).

### What you control
- **The panel**: a board with a priority view, guests and links, history, cost.
- **Door on this computer** (a page that only opens on your Mac): what ran and what it cost, steps waiting for your OK, and **Settings**:
  which project folders are shared, which one tasks work on, whether the agent may run commands or open files and links on your screen,
  which model and provider pay for it, and the monthly budget. The cloud can show these, never change them.

### Set it up
1. On your Mac: `curl -fsSL <where you host it>/install.sh | bash`. It installs Plow Latch if missing, Door and its isolated runner, and asks
   three questions (project, model, tasks). `door-host doctor` tells you anything still missing.
2. In the cloud: run the Door image on one of your Plow lines (`plow-agents deploy --local --line ln_xxx`, or publish it on Plow).
3. Text the line `Door Activate: <code>`, then `Door Pair: <code>`. Done.

### Status
Tested for real on the owner's own Plow account (October 2026): activation and pairing by text, the image running on a Plow line, the Latch
relay to the Mac, questions answered by a real model in about 20 to 30 seconds, a group chat with a second person, a task done by the real
Claude Code, and the settings page. What is not verified yet: [`door/docs/READINESS.md`](door/docs/READINESS.md).

### What is left to finish
Working today: everything above, tested on a real Plow account. To call it finished and hand it to a customer:

**Needs a decision or an account (not code)**
1. **A public address for the links.** Today links open only on the owner's Mac. Put the cloud part on a server with a domain and HTTPS (or use a tunnel for a demo).
2. **Publish the image** publicly (amd64) and ask Plow to admit it to the agent index, so a customer can install it in one click.
3. **Terms, privacy policy, licence and pricing**; billing is manual for now.

**Needs more work**
4. **Door's text messages in both languages.** Each person should get Door's own messages (limits, confirmations, errors) in the language they write; the catalog is written (`door/door/i18n.py`) but not wired in yet.
5. **Choose which project a conversation is about.** Several projects can be shared, but a person cannot yet pick one ("talk about the website") or be limited to one.
6. **Improve "Door on this computer"**: a nicer layout, folder picker, guided model sign-in.
7. **The owner panel in Portuguese**, not only the guest chat.
8. **Faster answers.** Typically 20 to 30 seconds; the model's slowest call and the trips through Plow are the cost.

**Still to test for real**
9. The installer on a **second Mac** (the first customer's), including downloading Plow Latch.
10. `Door Trust` in a real group, and a task that changes files with the approval coming by text, end to end on Plow.
11. **Own-subscription sign-in** and **Codex** (needs the owner's decision on its inner sandbox).
12. **Load**: one panel process is fine for tens of customers, not thousands.

**[Full Door reference — how it works, the engines, the board, the tests →](door/README.md)**
**[The MyPeople runtime in this repository (what Door is modelled on) →](MYPLOW.md)**

---

## Português

O Door deixa outras pessoas conversarem com o agente de IA que trabalha no seu código: **por SMS, num grupo, ou por um link de chat**.
Elas fazem perguntas e recebem respostas tiradas do próprio projeto. Quem você confia também pode pedir para coisas serem feitas, e o Door
prova que o trabalho foi feito de verdade antes de dizer que terminou. Seu computador nunca abre uma porta, e ninguém recebe acesso ao
terminal, aos seus arquivos ou às suas chaves.

### Do que o Door é feito
O Door junta duas coisas:
- **MyPeople** (o motor do [MyPlow](MYPLOW.md)): times de agentes na sua máquina, com um Boss que distribui o trabalho, um quadro de
  prioridades e a "prova" de que o trabalho foi feito. O Door leva essas ideias para pessoas *de fora* da sua máquina: o quadro onde os
  pedidos viram cartões, o Boss que escolhe qual agente responde, e a entrega conferida por evidência, não por confiança.
- **[Plow](https://plow.co)**: uma linha de telefone para o agente (SMS e iMessage, inclusive grupos), um lugar para rodar a parte na nuvem
  como agente do Plow, e o **Plow Latch**, o app no seu Mac que o liga ao Plow só por conexão de saída.

```
 Alguém manda SMS para o número do Door / escreve num link de chat / fala num grupo
        │   (o Plow carrega as mensagens)
        ▼
 Agente do Door na nuvem: regras, limites, quem pode o quê, o seu painel, o quadro
        │   relay do Plow ──► Plow Latch no seu Mac (o Mac só disca para fora)
        ▼
 door-host no seu Mac: confere cada pedido de novo (assinado pela nuvem)
        ├─ perguntas: um contêiner isolado lê uma cópia limpa do projeto; a chave do modelo nunca entra nele
        └─ tarefas: o Claude Code trabalha numa branch git descartável; passos de risco esperam você; o Door roda AS SUAS checagens
        ▼
 A resposta (ou o resultado e a prova) volta pelo mesmo caminho
```

### Door e MyPeople: o que é compartilhado e o que não é
O Door é um programa próprio: **ele não importa nem executa código do MyPeople, e não precisa do MyPeople instalado.** Ele nasce das ideias
do MyPeople e segue o jeito como o MyPeople conversa com o Plow. O código do Door fica em [`door/`](door/); o motor MyPeople em que ele se
baseia fica neste repositório.

| No MyPeople (este repositório) | O que o Door aproveita |
|---|---|
| `mypeople/runtime/plugins/plow-chat` (a ponte do Plow Chat) | Como um agente fala com o Plow: o contrato de agente na nuvem (`/v1/agents/cloud/me`), chats e grupos, responder na conversa de onde veio a pergunta. O [`door/door/plow.py`](door/door/plow.py) e o [`door/door/plow_agent.py`](door/door/plow_agent.py) do Door seguem o mesmo padrão. |
| `cloud/` (a imagem da nuvem do MyPeople) | Como a imagem de um agente sobe numa linha do Plow sem nenhum segredo dentro (por exemplo, limpar o entrypoint porque o Plow executa o comando da própria imagem). O [`door/cloud/Dockerfile`](door/cloud/Dockerfile) do Door segue a mesma abordagem. |
| O Boss e os engenheiros (`mypeople/runtime/mp-boss-doctrine.md`) | Um agente que decide quem trabalha em quê. O "Boss" do Door escolhe qual agente responde uma pergunta; as tarefas vão para um agente de tarefas separado. |
| O quadro de prioridades | O quadro do Door: cada pedido vira um cartão que anda de To do até Done, com visão de prioridade. |
| `mypeople/runtime/verify/` e a ideia de "prova" | A regra do Door de que o trabalho só está Done com evidência: mudanças reais, as verificações da dona e uma checagem independente. |
| Plow Latch | O MyPeople já usa o Latch para chegar a um Mac; o Door chega ao Mac da dona pelo mesmo Latch. |

O que fica neste repositório por causa do próprio MyPeople: o motor (`mypeople/`), o app de desktop (`desktop/`), a imagem da nuvem (`cloud/`),
o `install.sh`, os arquivos Docker e o `docs/HOW-IT-WORKS.md`. O README original do MyPlow é o [`MYPLOW.md`](MYPLOW.md). O código do Door fica em `door/`.

### O que as pessoas podem fazer
- **Perguntar** qualquer coisa sobre o projeto. A resposta diz de quais arquivos veio, e o Door confere que eles existem. Respostas na hora,
  dentro dos limites diários e do orçamento do mês (ou você aprova cada uma, se preferir).
- **Pedir que algo seja feito**, só se você confiar na pessoa: o trabalho acontece numa cópia, numa branch nova, nunca na sua pasta. Um
  cartão acompanha o pedido e só vai para **Done** quando algo mudou de verdade, as suas verificações passaram e uma checagem independente concorda.
- **Você**, a dona, só escreve para o seu agente: pergunta vira resposta, o resto vira tarefa.

### Como as pessoas entram
`Door Link Ana` (link de chat, abre em um aparelho e vence) · `Door Invite Ana` (código para mandar por SMS) · num grupo, `Door Allow`
(o Door se apresenta) e `Door Trust` (libera tarefas, depois que você confirma no seu privado).

### O que você controla
- **O painel**: quadro com visão de prioridade, convidados e links, histórico, custo.
- **Door on this computer** (uma página que só abre no seu Mac): o que rodou e quanto custou, passos esperando o seu OK, e **Settings**:
  quais pastas são compartilhadas, em qual delas as tarefas trabalham, se o agente pode rodar comandos ou abrir arquivos e links na sua
  tela, qual modelo e provedor pagam por isso, e o orçamento do mês. A nuvem pode mostrar essas escolhas, nunca mudar.

### Como instalar
1. No Mac: `curl -fsSL <onde estiver hospedado>/install.sh | bash`. Instala o Plow Latch se faltar, o Door e o ambiente isolado, e faz três
   perguntas (projeto, modelo, tarefas). `door-host doctor` diz o que ainda falta.
2. Na nuvem: rode a imagem do Door numa linha do Plow (`plow-agents deploy --local --line ln_xxx`, ou publicando no Plow).
3. Mande para a linha `Door Activate: <código>` e depois `Door Pair: <código>`. Pronto.

### Situação
Testado de verdade na conta Plow da dona (outubro de 2026): ativação e pareamento por SMS, a imagem rodando numa linha do Plow, a ponte do
Latch até o Mac, perguntas respondidas por um modelo real em 20 a 30 segundos, um grupo com uma segunda pessoa, uma tarefa feita pelo Claude
Code de verdade, e a página de configurações. O que ainda não foi verificado: [`door/docs/READINESS.md`](door/docs/READINESS.md).

### O que falta finalizar
Funcionando hoje: tudo o que está acima, testado numa conta Plow de verdade. Para considerar pronto e entregar a um cliente:

**Precisa de decisão ou de conta (não é código)**
1. **Um endereço público para os links.** Hoje os links só abrem no Mac da dona. Colocar a parte da nuvem num servidor com domínio e HTTPS (ou usar um túnel para uma demonstração).
2. **Publicar a imagem** (amd64) e pedir ao Plow para admiti-la no índice de agentes, para o cliente instalar com um clique.
3. **Termos, política de privacidade, licença e preço**; a cobrança é manual por enquanto.

**Falta trabalho**
4. **As mensagens do próprio Door nos dois idiomas.** Cada pessoa deve receber as mensagens do Door (limites, confirmações, erros) no idioma em que escreve; o catálogo está escrito (`door/door/i18n.py`), mas ainda não está ligado.
5. **Escolher sobre qual projeto é a conversa.** Dá para compartilhar vários projetos, mas ainda não dá para a pessoa escolher um ("fala do site") nem limitá-la a um só.
6. **Melhorar o "Door on this computer"**: visual melhor, seletor de pasta, login guiado do modelo.
7. **O painel da dona em português**, não só o chat do convidado.
8. **Respostas mais rápidas.** Normalmente 20 a 30 segundos; o custo está na chamada mais lenta do modelo e nas idas e vindas pelo Plow.

**Ainda falta testar de verdade**
9. O instalador num **segundo Mac** (o do primeiro cliente), inclusive baixando o Plow Latch.
10. `Door Trust` num grupo real, e uma tarefa que altera arquivos com a aprovação chegando por SMS, de ponta a ponta no Plow.
11. **Login com a própria assinatura** e **Codex** (precisa da decisão da dona sobre o isolamento interno dele).
12. **Carga**: um processo de painel serve dezenas de clientes, não milhares.

**[Referência completa do Door — como funciona, os motores, o quadro, os testes →](door/README.md#português)**
**[O motor MyPeople neste repositório (em que o Door se baseia) →](MYPLOW.md)**
