"""Every sentence Door itself sends to a person, in English and Portuguese. Each person gets the language they write in (see replytext.lang).
Commands stay the same in both languages (DOOR LINK, YES 1234, Door Join: ...), so instructions never depend on translation."""

LANGS = ("en", "pt")

M = {
    # ---- the owner ----
    "activated": ("Door is activated. Open the panel to add people and pair your Mac. / Door ativado. Abra o painel para adicionar pessoas e parear seu Mac.",) * 2,
    "help": ("Just write to me. A question gets an answer about the project; something to do is done on a copy of it and checked. "
             "Commands: YES/NO <code>; DOOR LINK <name>; DOOR INVITE <name>; DOOR GUESTS; DOOR REVOKE <name>; DOOR PANEL (sign-in link); "
             "DOOR PAUSE/RESUME; DOOR QUEUE; DOOR TODAY. In a group: DOOR ALLOW, DOOR TRUST, DOOR STOP. Letting someone run tasks is only done in the panel "
             "or with DOOR TRUST in a group (you confirm it here).",
             "É só me escrever. Uma pergunta recebe resposta sobre o projeto; um pedido é feito numa cópia dele e conferido. "
             "Comandos: YES/NO <código>; DOOR LINK <nome>; DOOR INVITE <nome>; DOOR GUESTS; DOOR REVOKE <nome>; DOOR PANEL (link de acesso); "
             "DOOR PAUSE/RESUME; DOOR QUEUE; DOOR TODAY. Num grupo: DOOR ALLOW, DOOR TRUST, DOOR STOP. Liberar tarefas para alguém só pelo painel "
             "ou com DOOR TRUST num grupo (você confirma aqui)."),
    "tasks_off_owner": ("I can answer questions about the project. To have me do things (edit files, run checks), turn tasks on for this agent "
                        "in your Door settings, then ask again. Meanwhile, ask it as a question and I will answer from the code.",
                        "Eu posso responder perguntas sobre o projeto. Para eu fazer coisas (editar arquivos, rodar verificações), ligue as tarefas "
                        "para este agente nas configurações do Door e peça de novo. Enquanto isso, pergunte e eu respondo a partir do código."),
    "step_ask": ("Door: {who}'s task wants to: {what}. Reply YES {code} to allow or NO {code} to refuse. {url}",
                 "Door: a tarefa de {who} quer: {what}. Responda YES {code} para permitir ou NO {code} para recusar. {url}"),
    "approve_ask": ('Door: {who} asks {agent}: "{text}" ({count}/{max} today, {tokens} tokens). Reply YES {code} or NO {code}.{more} Full text: {url}',
                    'Door: {who} pergunta ao {agent}: "{text}" ({count}/{max} hoje, {tokens} tokens). Responda YES {code} ou NO {code}.{more} Texto completo: {url}'),
    "approve_long": (" [Longer than 300 characters: read the full text before approving.]", " [Mais de 300 caracteres: leia o texto completo antes de aprovar.]"),
    "code_not_found": ("Code not found or request already decided.", "Código não encontrado ou pedido já decidido."),
    "yes_no_hint": ("Reply YES or NO followed by the request code.", "Responda YES ou NO seguido do código do pedido."),
    "queue_count": ("{n} requests are waiting for approval. {url}", "{n} pedidos esperando aprovação. {url}"),
    "today": ("Today: {n} requests. Spend this month: USD {spend}. {url}", "Hoje: {n} pedidos. Gasto no mês: USD {spend}. {url}"),
    "joined_invite": ("Door: {who} joined with invite {code}.", "Door: {who} entrou com o convite {code}."),
    "access_asked": ("Door: {name} ({phone}) asked for access. Review it in the panel.", "Door: {name} ({phone}) pediu acesso. Veja no painel."),
    "no_guests": ("No guests yet. Text DOOR LINK <name> or DOOR INVITE <name>.", "Ninguém com acesso ainda. Mande DOOR LINK <nome> ou DOOR INVITE <nome>."),
    "guests": ("Guests: {list}", "Pessoas com acesso: {list}"),
    "and_more": (" and more", " e mais"),
    "web_guest": ("web guest", "convidado pela web"),
    "tasks_tag": (", tasks", ", tarefas"),
    "status_active": ("active", "ativo"), "status_suspended": ("suspended", "suspenso"), "status_revoked": ("revoked", "revogado"),
    "invite_fail": ("Could not make an invite: {err}", "Não consegui criar o convite: {err}"),
    "invite_ok": ("Invite{for_}: {code}. Tell them to text this number: Door Join: {code} (valid 7 days, works once).",
                  "Convite{for_}: {code}. Peça para a pessoa mandar para este número: Door Join: {code} (vale 7 dias, uma vez só)."),
    "for_name": (" for {name}", " para {name}"),
    "revoke_who": ("Say who: DOOR REVOKE <name>.", "Diga quem: DOOR REVOKE <nome>."),
    "revoke_many": ("I found {n} guests named {name}. Use the panel to pick the right one.", "Achei {n} pessoas chamadas {name}. Use o painel para escolher a certa."),
    "revoked": ("{name} no longer has access.", "{name} não tem mais acesso."),
    "link_ok": ("Link{for_}: {url} (opens on one device, valid 7 days; you can turn it off in the panel).",
                "Link{for_}: {url} (abre em um aparelho só, vale 7 dias; dá para desligar no painel)."),
    "panel_link": ("Your panel (one-time link, 10 minutes): {url}", "Seu painel (link de uso único, 10 minutos): {url}"),
    "no_mac": ("No Mac is connected to this Plow account yet. Install Plow Latch on your Mac, then try again.",
               "Nenhum Mac está ligado a esta conta Plow ainda. Instale o Plow Latch no seu Mac e tente de novo."),
    "paired": ("Mac paired. You can now write to me, or share DOOR LINK <name> with someone.",
               "Mac pareado. Agora é só me escrever, ou mandar DOOR LINK <nome> para alguém."),
    "unknown_numbers": ("Unknown numbers (no content): {list}", "Números desconhecidos (sem conteúdo): {list}"),
    "sub_expired": ("Subscription expired. You have 7 days to renew.", "A assinatura venceu. Você tem 7 dias para renovar."),
    "budget_used": ("Door: monthly budget used up; new requests are blocked.", "Door: o orçamento do mês acabou; novos pedidos estão bloqueados."),
    "group_stranger": ("Door: a group chat includes someone who is not an authorized guest, so I did not answer there.",
                       "Door: um grupo tem alguém sem autorização, então eu não respondi lá."),
    "group_joined_owner": ("Door: {who} joined an open group and can now ask questions.", "Door: {who} entrou num grupo aberto e agora pode fazer perguntas."),
    "group_opened_owner": ("Door: you opened a group; {n} people were added as guests.", "Door: você abriu um grupo; {n} pessoas ganharam acesso."),
    "not_in_group": ("Door: {who} is not in that group, so I did not trust anyone.", "Door: {who} não está nesse grupo, então não autorizei ninguém."),
    "nobody_to_trust": ("Door: nobody to trust in that group.", "Door: não há ninguém para autorizar nesse grupo."),
    "trust_ask": ("Door: reply YES {code} to let {who} ask me to do things on {project} (valid 10 min).",
                  "Door: responda YES {code} para deixar {who} pedir para eu fazer coisas no {project} (vale 10 min)."),
    "trust_no": ("Door: OK, nobody was given that.", "Door: OK, ninguém recebeu essa permissão."),
    "host_secrets_owner": ("Door: a question was NOT answered because the safety scan found something that looks like a secret in the shared project. "
                           "On your Mac run `door-host audit` to see which file, then remove it or add it to the agent's \"exclude\" list.",
                           "Door: uma pergunta NÃO foi respondida porque a verificação de segurança achou algo parecido com uma senha ou chave no projeto. "
                           "No seu Mac, rode `door-host audit` para ver qual arquivo e remova-o ou coloque na lista \"exclude\" do agente."),
    "host_export_owner": ("Door: the project could not be copied for a question. Check that the repository path in your policy exists and has commits.",
                          "Door: não consegui copiar o projeto para uma pergunta. Confira se o caminho do repositório existe e tem commits."),
    "host_sandbox_owner": ("Door: your Mac could not start the isolated container. Is Docker running? `door-host doctor` shows what is wrong.",
                           "Door: seu Mac não conseguiu iniciar o container isolado. O Docker está aberto? `door-host doctor` mostra o que falta."),
    # ---- groups (the group hears the owner's language) ----
    "group_intro": ("Hi! I'm Door, the assistant for the {project} project. Start a message with \"Door,\" to ask me anything about it, and I'll answer from the project itself. "
                    "I stay quiet while you talk to each other. Only people {owner} trusts can ask me to change things, and risky steps always need approval.",
                    "Oi! Eu sou o Door, o assistente do projeto {project}. Comecem a mensagem com \"Door,\" para me perguntar qualquer coisa sobre ele; eu respondo a partir do "
                    "próprio projeto. Fico quieto enquanto vocês conversam entre si. Só quem {owner} autorizar pode me pedir para mudar coisas, e passos arriscados sempre precisam de aprovação."),
    "owner_word": ("the owner", "a dona"),
    "trusted": ("{who} can now ask me to do things on {project}. I work on a copy, and risky steps still need approval.",
                "{who} agora pode me pedir para fazer coisas no {project}. Eu trabalho numa cópia, e passos arriscados ainda precisam de aprovação."),
    "group_off": ("Door is off for this group. People already let in keep their access; new people are not added.",
                  "O Door foi desligado neste grupo. Quem já tinha acesso continua; pessoas novas não entram."),
    "group_no_members": ("I can't see who is in this group, so I did not let anyone in.", "Não consigo ver quem está neste grupo, então não liberei ninguém."),
    "group_too_big": ("This group has more than {n} people. Add them one by one from the panel instead.",
                      "Este grupo tem mais de {n} pessoas. Adicione uma por uma pelo painel."),
    "tasks_not_on_mac": ("Tasks are not set up on the owner's Mac yet.", "As tarefas ainda não estão ligadas no Mac de quem é dono do projeto."),
    # ---- guests ----
    "unknown": ("This number is not authorized. Ask the owner for an invite code, then text: Door Join: <code>",
                "Este número não tem acesso. Peça um código de convite a quem é dono do projeto e mande: Door Join: <código>"),
    "join_invalid": ("That code is not valid or has expired.", "Esse código não é válido ou já venceu."),
    "join_already": ("You already have access.", "Você já tem acesso."),
    "join_ok": ("You're in{name}. Text your question any time.", "Pronto{name}, você tem acesso. Mande sua pergunta quando quiser."),
    "access_sent": ("Request sent. The owner will review it; you will get a text if you are let in.",
                    "Pedido enviado. Quem é dono do projeto vai analisar; você recebe uma mensagem se for liberado."),
    "only_owner": ("Only the owner can answer that.", "Só quem é dono do projeto pode responder isso."),
    "fresh_chat": ("Starting a fresh conversation.", "Começando uma conversa nova."),
    "tasks_not_enabled": ("I can answer questions about the project, but running tasks is not enabled for you.",
                          "Eu posso responder perguntas sobre o projeto, mas fazer tarefas não está liberado para você."),
    "tasks_not_setup": ("Tasks are not set up yet.", "As tarefas ainda não estão configuradas."),
    "queue_full": ("The queue is full. Try again later.", "A fila está cheia. Tente de novo mais tarde."),
    "got_task": ("Got it. I'll do this and check the result.", "Entendi. Vou fazer isso e conferir o resultado."),
    "got_ask": ("Got it. Working on it.", "Entendi. Já estou vendo."),
    "received_wait": ("Received. The owner will approve it before I answer.", "Recebido. Quem é dono do projeto vai aprovar antes de eu responder."),
    "waiting_step": ("Waiting for the owner to approve a step.", "Esperando a aprovação de um passo."),
    "declined": ("The owner declined this request.", "Esse pedido foi recusado."),
    "canceled": ("Request canceled.", "Pedido cancelado."),
    "mac_offline": ("The Mac is not available yet. Your request is still queued.", "O Mac ainda não está disponível. Seu pedido continua na fila."),
    "failed": ("This request could not be answered. The owner was informed.", "Não consegui responder esse pedido. Quem é dono do projeto foi avisado."),
    "rule_suspended": ("Access is suspended or expired. Ask the owner to review it.", "Seu acesso está suspenso ou venceu. Peça para revisarem."),
    "rule_length": ("Send a question of 1 to 1600 characters.", "Mande uma pergunta de 1 a 1600 caracteres."),
    "rule_paused": ("Door is paused by the owner.", "O Door está pausado."),
    "rule_unavailable": ("Door is unavailable.", "O Door não está disponível."),
    "rule_limit": ("You have reached your request or token limit.", "Você chegou ao seu limite de pedidos por hoje."),
    "rule_budget": ("Door's budget has been reached.", "O orçamento do Door acabou."),
    "host_secrets": ("I can't answer right now: a safety check on the project failed. The owner has been told.",
                     "Não posso responder agora: uma verificação de segurança do projeto falhou. Quem é dono do projeto foi avisado."),
    "host_export": ("I can't answer right now: the project could not be prepared. The owner has been told.",
                    "Não posso responder agora: não consegui preparar o projeto. Quem é dono do projeto foi avisado."),
    "host_sandbox": ("I can't answer right now: the owner's computer isn't ready. The owner has been told.",
                     "Não posso responder agora: o computador de quem é dono do projeto não está pronto. Já avisei."),
    "host_unpaired": ("I can't answer right now: the owner's computer isn't connected.", "Não posso responder agora: o computador de quem é dono do projeto não está conectado."),
    # ---- written on the Mac ----
    "held": ("The owner is reviewing this reply.", "Esta resposta está sendo revisada antes do envio."),
    "checked_in": ("Checked in: {files}", "Conferido em: {files}"),
    "checked_partly": ("Checked in: {files}. Part of this I could not confirm in the files.", "Conferido em: {files}. Parte disso eu não consegui confirmar nos arquivos."),
}


def t(key, lang="en", **kw):
    en, pt = M[key]
    return (pt if lang == "pt" else en).format(**kw)
