"""How a reply reads on a phone: plain text (SMS shows Markdown as raw symbols), line breaks kept, cut at a sentence instead of mid-word,
and Door's own status line in the language the person wrote in."""
import re

PT_HINTS = re.compile(r"[ãõçáéíóúâêô]|\b(não|nao|você|voce|uma?|projeto|arquivo|verifica|acessa|cria|faz|faça|que|para|com|isso|está|esta|oi|gente|vou|aqui|tudo|esse|essa|meu|minha|de|da|das|dos|na|em|eu|ele|ela|obrigad\w*|tambem|também|pra|tá|ta|entao|então|amanha|amanhã|tu|teste|finaliza|finalizar|desligar|pro|mas|mais|seu|sua|bom|boa|agora|hoje|ontem|favor|arquivo|cria|crie)\b", re.I)


def lang(text):
    return "pt" if len(PT_HINTS.findall(text or "")) >= 2 else "en"


def plain(text):
    t = (text or "").replace("\r\n", "\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", t)                    # code fences
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=re.M)            # headings
    t = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", t)  # links keep their address
    t = re.sub(r"^\s*[-*+]\s+", "• ", t, flags=re.M)               # bullets that read well in a text message
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def clip(text, limit):
    """At most `limit` characters, ending at a paragraph, a sentence or at least a whole word, with an ellipsis when something was cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    for stop in ("\n\n", "\n", ". ", "! ", "? "):
        i = cut.rfind(stop)
        if i >= limit * 0.5:
            return cut[:i + (1 if stop.strip() else 0)].rstrip() + " …"
    i = cut.rfind(" ")
    return (cut[:i] if i > 0 else cut).rstrip() + " …"


STATUS = {
    "en": {"verified": "Door checked it: changed {files}; {checks}. Saved on branch {branch} for the owner.",
           "checks_passed": "Door's checks passed ({checks}): changed {files}. Saved on branch {branch} for the owner.",
           "failed_checks": "Door's checks did NOT pass ({checks}). The owner will look at branch {branch}.",
           "unverified": "Door could not confirm this does what you asked{reason}. The owner will look at branch {branch}.",
           "no_changes": "(Door: nothing in the project was changed.)",
           "opened": "(Door confirmed it: a window of {apps} appeared on your screen. Nothing in the project was changed.)",
           "open_unconfirmed": "(Door asked your Mac to open {opened}, but could not confirm that a window appeared. Nothing in the project was changed.)",
           "error": "Door: the task did not finish{reason}.",
           "checks_ok": "checks passed: {checks}", "independent": "an independent check agreed"},
    "pt": {"verified": "Door conferiu: mudou {files}; {checks}. Está na branch {branch} esperando o dono.",
           "checks_passed": "As verificações do Door passaram ({checks}): mudou {files}. Está na branch {branch} esperando o dono.",
           "failed_checks": "As verificações do Door NÃO passaram ({checks}). O dono vai olhar a branch {branch}.",
           "unverified": "O Door não conseguiu confirmar que isso faz o que você pediu{reason}. O dono vai olhar a branch {branch}.",
           "no_changes": "(Door: nada no projeto foi alterado.)",
           "opened": "(O Door confirmou: apareceu uma janela de {apps} na sua tela. Nada no projeto foi alterado.)",
           "open_unconfirmed": "(O Door pediu ao Mac para abrir {opened}, mas não conseguiu confirmar que uma janela apareceu. Nada no projeto foi alterado.)",
           "error": "Door: a tarefa não terminou{reason}.",
           "checks_ok": "verificações passaram: {checks}", "independent": "uma checagem independente confirmou"},
}


OWNER_UNVERIFIED = {"en": "Door could not confirm this does what you asked{reason}. Take a look at branch {branch}.",
                    "pt": "O Door não conseguiu confirmar que isso faz o que você pediu{reason}. Dá uma olhada na branch {branch}."}
OWNER_FAILED = {"en": "Door's checks did NOT pass ({checks}). Take a look at branch {branch}.",
                "pt": "As verificações do Door NÃO passaram ({checks}). Dá uma olhada na branch {branch}."}


LIMIT_RE = re.compile(r"(?is)(session limit|usage limit|rate limit|limite de uso|limit reached)")
RESETS_RE = re.compile(r"(?is)resets?\s+(?:at\s+)?([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?(?:\s*\([^)]*\))?)")


def friendly_error(error, lg):
    """The one case people hit often: the Claude account's own usage limit. Said once, plainly, with when it comes back."""
    if not error or not LIMIT_RE.search(error):
        return None
    when = RESETS_RE.search(error)
    when = when.group(1).strip() if when else None
    if lg == "pt":
        return "O limite de uso do Claude da sua conta foi atingido" + (", volta às %s" % when if when else "") + ". A tarefa vai funcionar de novo depois disso."
    return "The usage limit of your Claude account was reached" + (", it resets at %s" % when if when else "") + ". Tasks will work again after that."


def task_reply(request_text, run, verdict, reason, limit, to_owner=False):
    """The agent's own words first, then one short line of what Door itself established. The status line follows the language of what the
    agent wrote (that is what the person is reading), else of the request; the owner is spoken to directly."""
    summary_lang = lang(run.get("summary") or "") if len((run.get("summary") or "").split()) >= 6 else None
    lg = summary_lang or lang(request_text)
    L = dict(STATUS[lg])
    if to_owner:
        L = dict(L, unverified=OWNER_UNVERIFIED[lg], failed_checks=OWNER_FAILED[lg])
        for k in ("verified", "checks_passed"):
            L[k] = L[k].replace("esperando o dono", "esperando você").replace("for the owner", "for you")
    files = ", ".join(run["changed_files"][:6]) + (" …" if len(run["changed_files"]) > 6 else "")
    checks = "; ".join("%s %s" % (p["cmd"], "ok" if p["rc"] == 0 else "FAILED") for p in run["proof"])
    reason = (reason or "").strip().rstrip(".")
    fill = {"apps": ", ".join(run.get("opened_apps") or []) or "-", "opened": ", ".join(run.get("opened") or []) or "-", "files": files or "-", "branch": run.get("work_branch") or run.get("branch") or "-", "reason": (": " + reason) if reason else "",
            "checks": L["checks_ok"].format(checks=checks) if checks else L["independent"]}
    if verdict in ("failed_checks", "checks_passed"):
        fill["checks"] = checks or "-"
    key = verdict if verdict in L else "error"
    nice = friendly_error(run.get("error") or run.get("summary"), lang(request_text)) if key == "error" else None      # the error text itself is English: use the person's language
    if nice:
        return nice                                                    # the whole message: no repeated copy of the same error
    if key == "error":
        fill["reason"] = (": " + run["error"]) if run.get("error") else ""
        if run.get("error") and run["error"].strip() in (run.get("summary") or ""):
            run = dict(run, summary="")                                # the agent's text IS the error: do not say it twice
    status = L[key].format(**fill)
    body = clip(plain(run.get("summary") or ""), max(200, limit - len(status) - 2))
    return (body + "\n\n" + status).strip() if body else status
