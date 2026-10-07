"""Estado autoritativo na nuvem; SMS e relay são adapters, nunca um LLM roteador.

SQLite serializado com transações e outbox persistente. Não guarda a chave do
Mac nem credencial de modelo. Tempo/contadores usam UTC.
"""
import copy
import json
import os
import re
import secrets
import sqlite3
import threading
from pathlib import Path

from . import replytext
from .common import ULID_RE, day_key, month_key, now, norm_text, sha256_text, ulid, is_e164, is_handle, norm_handle, iso
from .envelope import generate, encode

TERMINAL = {"completed", "failed", "canceled"}
UNKNOWN = "This number is not authorized. Ask the owner for an invite code, then text: Door Join: <code>"
JOIN_RE = re.compile(r"Door Join:?\s*([A-Za-z0-9-]{4,20})", re.I)
REQUEST_RE = re.compile(r"Door Request:?\s*(.{1,60})", re.I | re.S)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"      # no 0/O/1/I/L: easy to read out loud
MAX_INVITES, MAX_ACCESS_REQUESTS, JOIN_FAILS_PER_HOUR = 50, 20, 5
# Phrases that only appear when someone is trying to take over the agent. Mild on purpose: a normal question never matches.
INJECTION_PATTERNS = [
    r"ignore (all |any |the |your )?(previous|prior|above|earlier|preceding) (instructions|rules|prompts?|messages?)",
    r"disregard (all |any |the |your )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"(reveal|show|print|repeat|output|leak) (me )?(your|the) (system|hidden|initial|secret) (prompt|instructions|rules)",
    r"you are now (in )?(debug|developer|dan|jailbreak|god) ?mode",
    r"\bjailbreak\b", r"\bdeveloper mode\b",
]
DEFAULT_REFUSAL = "I can only help with questions about this project."
# Conversation memory: kept per guest (never shared between guests), handed to the agent as untrusted context.
CONVO_KEEP, CONVO_WINDOW_S, CONVO_CHARS, CONVO_ITEMS = 40, 7 * 86400, 6000, 12
NEW_CHAT = {"NEW", "RESET", "NEW CHAT", "START OVER", "CLEAR"}
OWNER_NAME_CMD = re.compile(r"(?is)door\s+(invite|link|revoke)(?:\s+(.{1,60}))?")
QUESTION_START = re.compile(r"(?is)^(what|how|why|where|who|when|which|can|could|does|do you|is|are|will|should|qual|quais|como|por ?que|onde|quem|quando|o que|pode|existe|tem)\b")
TASK_RE = re.compile(r"(?is)^\s*(?:do|task)\s*:\s*(.+)$")
LEVELS = ("ask", "act")
MAX_JOBS = 200
GROUP_ALLOW_RE = re.compile(r"Door Allow\s*", re.I)
GROUP_STOP_RE = re.compile(r"Door Stop\s*", re.I)
GROUP_TRUST_RE = re.compile(r"Door Trust(?:\s+(.+))?\s*", re.I)
GROUP_INTRO = {
    "en": "Hi! I'm Door, the assistant for the {project} project. Ask me anything about it here and I'll answer from the project itself. "
          "Only people {owner} trusts can ask me to change things, and risky steps always need approval. Say \"new chat\" to start over.",
    "pt": "Oi! Eu sou o Door, o assistente do projeto {project}. Podem me perguntar qualquer coisa sobre ele aqui; eu respondo a partir do "
          "próprio projeto. Só quem {owner} autorizar pode me pedir para mudar coisas, e passos arriscados sempre precisam de aprovação. "
          "Digam \"new chat\" para recomeçar a conversa.",
}
TRUSTED_TEXT = {
    "en": "{who} can now ask me to do things on {project}. I work on a copy, and risky steps still need approval.",
    "pt": "{who} agora pode me pedir para fazer coisas no {project}. Eu trabalho numa cópia, e passos arriscados ainda precisam de aprovação.",
}
MAX_GROUP_MEMBERS = 25
TRANSITIONS = {"waitingApproval": {"queued", "canceled"}, "queued": {"running", "canceled"},
               "running": {"completed", "failed", "canceled"}}


class Cloud:
    def __init__(self, path, owner_id, summary, panel_url="", clock=now, approval="auto"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.lock = threading.RLock()
        self.defer_save = False
        self.clock, self.panel_url = clock, panel_url.rstrip("/")
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row:
            self.s = json.loads(row[0])
            if self.s["owner_id"] != owner_id:
                raise ValueError("database belongs to another owner")
            for k in ("invites", "access_requests", "join_fail", "open_groups", "convos"):
                self.s.setdefault(k, {})
            self.s.setdefault("panel_jobs", [])
            self.s.setdefault("settings", {"approval": "each"})   # databases from before this setting keep asking
        else:
            private, public = generate()
            self.s = {"owner_id": owner_id, "owner_phone": None, "owner_thread": None,
                      "plan": {"status": "inactive", "active_until": 0}, "summary": summary,
                      "host_id": None, "device_uid": None, "host_online_at": 0, "paused": False,
                      "guests": {}, "requests": {}, "usage": {}, "unknown": {}, "seen": {},
                      "outbox": {}, "commands": {}, "alerts": {}, "private": private, "public": public,
                      "invites": {}, "access_requests": {}, "join_fail": {}, "open_groups": {}, "convos": {}, "panel_jobs": [],
                      "settings": {"approval": approval},
                      "activation": secrets.token_urlsafe(18), "activation_until": self.clock() + 600}
            self.s.update(workspace_id=ulid(), agent_node_id=ulid())
            self._save()

    def _save(self):
        if self.defer_save:
            return
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(self.s, ensure_ascii=False),))

    def ensure_activation(self):
        """A fresh code for the owner to text, whenever there is no owner yet and the last one expired (a cloud agent may sit for days)."""
        with self.lock:
            if not self.s["owner_phone"] and self.clock() > self.s.get("activation_until", 0):
                self.s.update(activation=secrets.token_urlsafe(9), activation_until=self.clock() + 3600)
                self._save()
            return self.s["activation"] if not self.s["owner_phone"] else None

    def public_key(self):
        return self.s["public"]

    def _sms(self, thread, text, key=None):
        if not thread:
            return
        key = key or ulid()
        self.s["outbox"].setdefault(key, {"id": key, "thread": thread, "text": text,
                                         "created_at": self.clock(), "status": "pending"})

    def pending_sms(self):
        with self.lock:
            return copy.deepcopy([v for v in self.s["outbox"].values() if v["status"] == "pending"])

    def sms_sent(self, key):
        with self.lock:
            self.s["outbox"][key]["status"] = "sent"
            self._save()

    def add_guest(self, phone, display_name="", days=30, limits=None):
        phone = norm_handle(phone)
        if not is_handle(phone) or not isinstance(days, int) or not 1 <= days <= 90:
            raise ValueError("phone in E.164 format and validity between 1 and 90 days required")
        lim = {"daily_requests": 10, "daily_tokens": 400000, "max_open_requests": 2}
        lim.update(limits or {})
        if any(type(lim[k]) is not int or lim[k] <= 0 for k in lim):
            raise ValueError("limites devem ser inteiros positivos")
        with self.lock:
            if any(g["phone"] == phone for g in self.s["guests"].values()):
                raise ValueError("number already registered")
            gid = ulid()
            self.s["guests"][gid] = dict(guest_id=gid, phone=phone, display_name=display_name[:100],
                                        status="active", expires_at=self.clock() + days * 86400, limits=lim)
            self._save()
            return gid

    def set_approval(self, mode):
        """Default for everyone: 'auto' answers right away, 'each' waits for the owner's OK on every question."""
        if mode not in ("auto", "each"):
            raise ValueError("mode must be auto or each")
        with self.lock:
            self.s["settings"]["approval"] = mode
            self._save()

    def set_guest_approval(self, gid, mode):
        """Per-person override of the default; None goes back to the default."""
        if mode not in ("auto", "each", None):
            raise ValueError("mode must be auto, each or None")
        with self.lock:
            self.s["guests"][gid]["approval"] = mode
            self._save()

    def set_guest_level(self, gid, level):
        """Owner-only (panel). "act" lets a trusted guest have tasks done on the owner's computer; it cannot be granted by text message."""
        if level not in LEVELS:
            raise ValueError("level must be ask or act")
        with self.lock:
            if level == "act" and not self.s["summary"].get("act_agent"):
                raise ValueError("no agent is set up to do tasks (agent.act in door.json)")
            self.s["guests"][gid]["level"] = level
            self._save()

    @staticmethod
    def _owner_key(guest):
        """Which board a guest's cards live on: their chat link, or the owner's board only for people who use text messages."""
        if guest.get("owner"):
            return "owner"                                   # the owner's own tasks go on the owner's board as "You"
        return guest.get("link_id") or "g_" + guest["guest_id"]

    def _panel_job(self, job):
        jobs = self.s.setdefault("panel_jobs", [])
        jobs.append(dict(job, id=ulid(), tries=0))
        del jobs[:-MAX_JOBS]

    def decide_action(self, rid, action_id, decision, identity="panel:owner"):
        """The owner allows or refuses one step of a running task. Door passes the answer to the Mac."""
        if decision not in ("allow", "deny"):
            raise ValueError("decision must be allow or deny")
        with self.lock:
            a = (self.s["requests"][rid].get("actions") or {}).get(action_id)
            if a is None or a.get("decided"):
                raise ValueError("that step was already decided or no longer exists")
            a.update(decided=decision, decided_by=identity)
            self.s["commands"][ulid()] = {"op": "decide", "request": rid, "action": action_id, "decision": decision, "done": False}
            self._save()

    def _note_actions(self, r, pending):
        """Steps a running task is waiting on. New ones are shown in the panel and texted to the owner once."""
        seen = r.setdefault("actions", {})
        live = {a["id"] for a in pending}
        for a in seen.values():
            if a["id"] not in live and not a.get("decided"):
                a["decided"] = a.get("decided") or "expired"
        used = {x["code"] for q in self.s["requests"].values() for x in (q.get("actions") or {}).values() if not x.get("decided")}
        used |= {q["approval_code"] for q in self.s["requests"].values() if q["state"] == "waitingApproval"}
        guest = self.s["guests"].get(r["guest_id"], {})
        for a in pending:
            if a["id"] in seen:
                continue
            free = [f"{i:04d}" for i in range(10000) if f"{i:04d}" not in used]
            if not free:
                continue
            code = secrets.choice(free); used.add(code)
            seen[a["id"]] = {"id": a["id"], "tool": a["tool"], "summary": str(a["summary"])[:300], "code": code, "at": self.clock(), "decided": None}
            self._sms(self.s["owner_thread"], "Door: %s's task wants to: %s. Reply YES %s to allow or NO %s to refuse. %s" % (
                guest.get("display_name") or "A guest", str(a["summary"])[:200], code, code, self.panel_url), "action:%s:%s" % (r["request_id"], a["id"]))
            self._sms(r["thread_id"], "Waiting for the owner to approve a step.", r["request_id"] + ":waiting")

    def _approval_mode(self, guest):
        return guest.get("approval") or self.s["settings"]["approval"]

    def set_guest_status(self, gid, status):
        if status not in {"active", "suspended", "revoked"}:
            raise ValueError("invalid status")
        with self.lock:
            self.s["guests"][gid]["status"] = status
            self._save()

    def set_plan(self, status, active_until):
        if status not in {"active", "inactive", "canceled"} or not isinstance(active_until, (int, float)):
            raise ValueError("invalid plan")
        with self.lock:
            self.s["plan"] = {"status": status, "active_until": active_until}
            self._save()

    def _counts(self, gid):
        d = day_key(self.clock())
        reqs = [r for r in self.s["requests"].values() if r["guest_id"] == gid]
        count = sum(day_key(r["created_at"]) == d for r in reqs)
        opened = sum(r["state"] not in TERMINAL for r in reqs)
        tokens = sum(u["input_tokens"] + u["output_tokens"] for u in self.s["usage"].values()
                     if u["guest_id"] == gid and day_key(u["recorded_at"]) == d)
        return count, opened, tokens

    def _spend(self):
        m = month_key(self.clock())
        return sum(u["cost"] for u in self.s["usage"].values() if month_key(u["recorded_at"]) == m)

    def _remember(self, guest_id, role, text):
        log = self.s["convos"].setdefault(guest_id, [])
        log.append({"role": role, "text": str(text)[:1500], "at": self.clock()})
        del log[:-CONVO_KEEP]

    def _history_for(self, guest_id, before_request):
        """The recent conversation with THIS guest, oldest first, bounded by age, item count and size. Excludes the current question."""
        t = self.clock()
        items = [e for e in self.s["convos"].get(guest_id, []) if t - e["at"] <= CONVO_WINDOW_S and e["at"] < before_request["created_at"] + 1e-6]
        if items and items[-1]["role"] == "guest" and items[-1]["text"] == before_request["text"]:
            items = items[:-1]                                   # the question being asked now is sent separately
        out, size = [], 0
        for e in reversed(items[-CONVO_ITEMS:]):
            size += len(e["text"])
            if size > CONVO_CHARS:
                break
            out.append({"role": e["role"], "text": e["text"]})
        return list(reversed(out))

    def _guardrail_block(self, text):
        """First layer: obvious takeover attempts and the owner's own blocked patterns never reach a model (and never cost anything)."""
        g = self.s["summary"].get("guardrails") or {}
        pats = list(g.get("blocked_patterns", [])) + (INJECTION_PATTERNS if g.get("block_prompt_injection", True) else [])
        for pat in pats:
            try:
                if re.search(pat, text, re.I):
                    self.s["alerts"]["blocked_" + day_key(self.clock())] = self.s["alerts"].get("blocked_" + day_key(self.clock()), 0) + 1
                    return g.get("refusal") or DEFAULT_REFUSAL
            except re.error:
                continue
        return None

    def _rules(self, guest, text):
        t, lim = self.clock(), self.s["summary"]["limits"]
        if guest["status"] != "active" or guest["expires_at"] <= t:
            return "Access is suspended or expired. Ask the owner to review it."
        if not isinstance(text, str) or not text.strip() or len(text) > 1600:
            return "Send a question of 1 to 1600 characters."
        blocked = self._guardrail_block(text)
        if blocked:
            return blocked
        if self.s["paused"]:
            return "Door is paused by the owner."
        plan = self.s["plan"]
        if plan["status"] != "active" or t > plan["active_until"] + 7 * 86400:
            return "Door is unavailable."
        count, opened, tokens = self._counts(guest["guest_id"])
        gl = guest["limits"]
        if count >= min(gl["daily_requests"], lim["guest_daily_requests"]) or \
           tokens >= min(gl["daily_tokens"], lim["guest_daily_tokens"]) or opened >= gl["max_open_requests"]:
            return "You have reached your request or token limit."
        if self._spend() >= lim["monthly_budget"]:
            return "Door's budget has been reached."

    def receive(self, message_id, phone, thread, text, is_group=False, members=None):
        """Chamado apenas após identidade/roster vindos da API autenticada da Plow."""
        with self.lock:
            if message_id in self.s["seen"]:
                return None
            self.s["seen"][message_id] = self.clock()
            try:
                return self._receive(phone, thread, text, is_group, members)
            finally:
                self._save()

    # ---------- invites and access requests ----------
    @staticmethod
    def _norm_code(code):
        return re.sub(r"[^A-Z0-9]", "", str(code).upper())

    def create_invite(self, display_name="", days=30, ttl_days=7, limits=None):
        """Owner-only (panel). The code is single-use; texting `Door Join: CODE` turns the sender into a guest."""
        if not isinstance(days, int) or not 1 <= days <= 90 or not isinstance(ttl_days, int) or not 1 <= ttl_days <= 30:
            raise ValueError("days must be 1-90 and ttl_days 1-30")
        with self.lock:
            now_ = self.clock()
            self.s["invites"] = {k: v for k, v in self.s["invites"].items() if not v["used"] and v["expires_at"] > now_}
            if len(self.s["invites"]) >= MAX_INVITES:
                raise ValueError("too many open invites")
            raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            self.s["invites"][raw] = {"code": raw[:4] + "-" + raw[4:], "name": str(display_name)[:100], "days": days,
                                      "limits": limits or None, "created_at": now_, "expires_at": now_ + ttl_days * 86400, "used": False}
            self._save()
            return raw[:4] + "-" + raw[4:]

    def revoke_invite(self, code):
        with self.lock:
            self.s["invites"].pop(self._norm_code(code), None)
            self._save()

    def _join(self, phone, thread, code):
        t = self.clock()
        fails = [x for x in self.s["join_fail"].get(phone, []) if t - x < 3600]
        if len(fails) >= JOIN_FAILS_PER_HOUR:
            return                                              # silence: no oracle for guessing codes
        inv = self.s["invites"].get(self._norm_code(code))
        if not inv or inv["used"] or inv["expires_at"] <= t:
            self.s["join_fail"][phone] = fails + [t]
            self._sms(thread, "That code is not valid or has expired.")
            return
        if any(g["phone"] == phone for g in self.s["guests"].values()):
            self._sms(thread, "You already have access.")
            return
        gid = ulid()
        lim = {"daily_requests": 10, "daily_tokens": 400000, "max_open_requests": 2}
        lim.update(inv["limits"] or {})
        self.s["guests"][gid] = dict(guest_id=gid, phone=phone, display_name=inv["name"], status="active",
                                     expires_at=t + inv["days"] * 86400, limits=lim)
        inv["used"] = True
        self.s["join_fail"].pop(phone, None)
        who = inv["name"] or phone
        self._sms(thread, "You're in%s. Text your question any time." % (", " + inv["name"] if inv["name"] else ""),
                  "join:" + gid)
        self._sms(self.s["owner_thread"], "Door: %s joined with invite %s." % (who, inv["code"]), "joined:" + gid)

    def _request_access(self, phone, thread, name):
        pend = self.s["access_requests"]
        if phone in pend or len(pend) >= MAX_ACCESS_REQUESTS:
            self._sms(thread, UNKNOWN)
            return
        clean = " ".join(re.sub(r"[^\w .'-]", "", name, flags=re.U).split())[:60] or phone
        pend[phone] = {"phone": phone, "name": clean, "thread": thread, "at": self.clock()}
        self._sms(thread, "Request sent. The owner will review it; you will get a text if you are let in.")
        self._sms(self.s["owner_thread"], "Door: %s (%s) asked for access. Review it in the panel." % (clean, phone), "access:" + phone)

    def resolve_access(self, phone, allow, days=30):
        with self.lock:
            req = self.s["access_requests"].pop(phone, None)
            if req is None:
                raise ValueError("no such access request")
            if allow:
                self.add_guest(phone, req["name"], days)
                self._sms(req["thread"], "You're in, %s. Text your question any time." % req["name"])
            self._save()

    # ---------- incoming messages ----------
    def _receive(self, phone, thread, text, group, members=None):
        phone = norm_handle(phone)
        members = [norm_handle(m) for m in members] if members else members
        if not is_handle(phone):
            return
        if group:
            return self._receive_group(phone, thread, text, members)
        if not self.s["owner_phone"]:
            m = re.fullmatch(r"Door Activate:\s*(\S+)", text, re.I)
            if m and self.clock() <= self.s["activation_until"] and \
               secrets.compare_digest(m[1], self.s["activation"]):
                self.s.update(owner_phone=phone, owner_thread=thread, activation="", activation_until=0)
                self._sms(thread, "Door is activated. Open the panel to add guests and pair your Mac.")
                return
        if phone == self.s["owner_phone"] and thread == self.s["owner_thread"]:
            return self._owner_command(text)
        guest = next((g for g in self.s["guests"].values() if g["phone"] == phone), None)
        join = JOIN_RE.fullmatch(text.strip())
        if join and phone != self.s["owner_phone"]:
            return self._join(phone, thread, join[1])
        if not guest:
            ask = REQUEST_RE.fullmatch(text.strip())
            if ask and self.s["owner_thread"]:
                return self._request_access(phone, thread, ask[1])
            last = self.s["unknown"].get(phone)
            if last is None or self.clock() - last >= 86400:
                self._sms(thread, UNKNOWN)
                self.s["unknown"][phone] = self.clock()
            return
        return self._guest_message(guest, thread, text)

    def _receive_group(self, phone, thread, text, members):
        """Group chats: the agent answers only when EVERY other participant is the owner or an active guest,
        so nobody outside the list can read an answer. Owner commands never work in a group."""
        if phone == self.s["owner_phone"]:
            # Only the owner's own message can open or close a group: adding the number to a group authorizes nobody.
            self._note_owner_lang(text)
            if GROUP_ALLOW_RE.fullmatch(text.strip()):
                return self._open_group(thread, members)
            if GROUP_STOP_RE.fullmatch(text.strip()):
                if self.s["open_groups"].pop(thread, None) is not None:
                    self._sms(thread, "Door is off for this group. People already let in keep their access; new people are not added.")
                return
            trust = GROUP_TRUST_RE.fullmatch(text.strip())
            if trust:
                return self._trust_request(thread, members, trust[1])
            # Anything else the owner writes in an open group is the owner talking to their agent, answered in the group.
            if thread in self.s["open_groups"] and self._everyone_allowed(members):
                return self._owner_request(thread, text)
            return
        join = JOIN_RE.fullmatch(text.strip())
        if join:
            return self._join(phone, thread, join[1])
        if thread in self.s["open_groups"] and members:
            self._authorize_members(thread, members, announce=True)   # people who joined an open group later
        guest = next((g for g in self.s["guests"].values() if g["phone"] == phone), None)
        if not guest:
            return                                              # strangers in a group get nothing, not even a reply
        t = self.clock()
        if not self._everyone_allowed(members):
            d = day_key(t)
            if self.s["alerts"].get("group") != d:
                self.s["alerts"]["group"] = d
                self._sms(self.s["owner_thread"], "Door: a group chat includes someone who is not an authorized guest, so I did not answer there.")
            return
        return self._guest_message(guest, thread, text)

    # ---------- web chat links (the panel hosts the page; messages come in through door_link) ----------
    def receive_web(self, link_id, msg_id, text, name="", days=30, kind="chat", card_id=None):
        """A message typed in a shared chat link. Same rules, limits and owner approval as a text message."""
        with self.lock:
            key = "web:%s:%s" % (link_id, msg_id)
            if key in self.s["seen"]:
                return None
            self.s["seen"][key] = self.clock()
            try:
                guest = next((g for g in self.s["guests"].values() if g.get("link_id") == link_id), None)
                if guest is None:
                    days = days if isinstance(days, int) and 1 <= days <= 90 else 30
                    gid = ulid()
                    guest = self.s["guests"][gid] = dict(
                        guest_id=gid, phone="", link_id=link_id, display_name=str(name)[:100], status="active",
                        expires_at=self.clock() + days * 86400,
                        limits={"daily_requests": 10, "daily_tokens": 400000, "max_open_requests": 2})
                return self._guest_message(guest, "web:" + link_id, str(text), kind if kind in ("chat", "task") else "chat", card_id)
            finally:
                self._save()

    def set_link_status(self, link_id, status):
        with self.lock:
            for g in self.s["guests"].values():
                if g.get("link_id") == link_id:
                    g["status"] = status
                    for r in list(self.s["requests"].values()):
                        if r["guest_id"] == g["guest_id"] and r["state"] not in TERMINAL and status == "revoked":
                            self._cancel(r, "owner_canceled")
            self._save()

    def _authorize_members(self, thread, members, announce=False, days=30):
        """Make everyone in an open group a guest. A guest the owner suspended or revoked is never re-activated."""
        added = []
        for m in members:
            if m == self.s["owner_phone"] or not is_handle(m):
                continue
            if any(g["phone"] == m for g in self.s["guests"].values()):
                continue
            gid = ulid()
            self.s["guests"][gid] = dict(guest_id=gid, phone=m, display_name="", status="active",
                                         expires_at=self.clock() + days * 86400,
                                         limits={"daily_requests": 10, "daily_tokens": 400000, "max_open_requests": 2})
            added.append(m)
        if announce and added:
            self._sms(self.s["owner_thread"], "Door: %s joined an open group and can now ask questions." % ", ".join(added))
        return added

    def _open_group(self, thread, members):
        if not members:
            self._sms(thread, "I can't see who is in this group, so I did not let anyone in.")
            return
        others = [m for m in members if m != self.s["owner_phone"]]
        if len(others) > MAX_GROUP_MEMBERS:
            self._sms(thread, "This group has more than %d people. Add them one by one from the panel instead." % MAX_GROUP_MEMBERS)
            return
        added = self._authorize_members(thread, members)
        self.s["open_groups"][thread] = {"at": self.clock()}
        self._sms(thread, self._intro(), "group-on:" + thread)
        if added:
            self._sms(self.s["owner_thread"], "Door: you opened a group; %d people were added as guests." % len(added))

    def _everyone_allowed(self, members):
        t = self.clock()
        allowed = {self.s["owner_phone"]} | {g["phone"] for g in self.s["guests"].values() if g["status"] == "active" and g["expires_at"] > t}
        return bool(members) and all(m in allowed for m in members)

    def _note_owner_lang(self, text):
        if len(text or "") >= 12 and not text.strip().upper().startswith(("DOOR ", "YES ", "NO ")):
            self.s["owner_lang"] = replytext.lang(text)

    def _owner_label(self):
        return self.s.get("owner_name") or ("a dona" if self.s.get("owner_lang") == "pt" else "the owner")

    def _project_label(self):
        return self.s["summary"].get("alias") or "this"

    def _intro(self):
        return GROUP_INTRO[self.s.get("owner_lang", "en")].format(owner=self._owner_label(), project=self._project_label())

    def _trust_request(self, thread, members, target):
        """`Door Trust` in a group (everyone in it) or `Door Trust +5511...` (one person). Never immediate: the owner confirms with a code in
        their own private thread, so a misread message or someone else's phone in the group cannot hand out the right to change things."""
        pt = self.s.get("owner_lang") == "pt"
        if not self.s["summary"].get("act_agent"):
            self._sms(thread, "Tarefas ainda não estão ligadas no Mac da dona." if pt else "Tasks are not set up on the owner's Mac yet.")
            return
        others = [m for m in (members or []) if m != self.s["owner_phone"]]
        if target:
            num = target.strip().lower() if "@" in target else "+" + re.sub(r"\D", "", target)
            if not is_handle(num) or num not in others:
                self._sms(self.s["owner_thread"], "Door: %s is not in that group, so I did not trust anyone." % target.strip()[:30])
                return
            others = [num]
        if not others or len(others) > MAX_GROUP_MEMBERS:
            self._sms(self.s["owner_thread"], "Door: nobody to trust in that group.")
            return
        used = {r["approval_code"] for r in self.s["requests"].values() if r["state"] == "waitingApproval"} | set(self.s.setdefault("trust_pending", {}))
        code = secrets.choice([f"{i:04d}" for i in range(10000) if f"{i:04d}" not in used])
        self.s["trust_pending"][code] = {"phones": others, "thread": thread, "until": self.clock() + 600}
        who = ", ".join(others)
        self._sms(self.s["owner_thread"], ("Door: responda YES %s para deixar %s pedir para eu fazer coisas no projeto %s (vale 10 min)."
                                           if pt else "Door: reply YES %s to let %s ask me to do things on %s (valid 10 min).")
                  % (code, who, self._project_label()))

    def _confirm_trust(self, code, yes):
        p = self.s.get("trust_pending", {}).pop(code, None)
        if not p or p["until"] < self.clock():
            return False
        if not yes:
            self._sms(self.s["owner_thread"], "Door: OK, nobody was given that.")
            return True
        self._authorize_members(p["thread"], p["phones"])
        for g in self.s["guests"].values():
            if g["phone"] in p["phones"] and g["status"] == "active":
                g["level"] = "act"
        lang = self.s.get("owner_lang", "en")
        self._sms(p["thread"], TRUSTED_TEXT[lang].format(who=", ".join(p["phones"]), project=self._project_label(), owner=self._owner_label()))
        return True

    def _guest_message(self, guest, thread, text, kind="chat", card_id=None):
        task = TASK_RE.match(text) if kind == "chat" else None
        if task:
            text, kind = task.group(1).strip(), "task"
        if re.fullmatch(r"(YES|NO) \d{4}", norm_text(text)):              # an approval code typed by a guest is not a question for the agent
            self._sms(thread, "Só a dona pode responder isso." if self.s.get("owner_lang") == "pt" else "Only the owner can answer that.")
            return
        if norm_text(text) == "CANCEL":
            for r in list(self.s["requests"].values()):
                if r["guest_id"] == guest["guest_id"] and r["state"] not in TERMINAL:
                    self._cancel(r, "guest_canceled")
            return
        if norm_text(text) in NEW_CHAT:
            self.s["convos"].pop(guest["guest_id"], None)
            self._sms(thread, "Starting a fresh conversation.")
            return
        denial = self._rules(guest, text)
        if denial:
            self._sms(thread, denial)
            return
        if kind == "task":
            if guest.get("level", "ask") != "act":
                self._sms(thread, "I can answer questions about the project, but running tasks is not enabled for you.")
                return
            if not self.s["summary"].get("act_agent"):
                self._sms(thread, "Tasks are not set up yet.")
                return
        used = {r["approval_code"] for r in self.s["requests"].values() if r["state"] == "waitingApproval"}
        choices = [f"{i:04d}" for i in range(10000) if f"{i:04d}" not in used]
        if not choices:
            self._sms(thread, "The queue is full. Try again later.")
            return
        rid, t = ulid(), self.clock()
        summary = self.s["summary"]
        agent = "auto" if summary.get("boss") else summary["alias"]
        m = re.match(r"@([a-z0-9-]{1,32})\s+(.+)", text, re.S)
        if m and m[1] in {a["alias"] for a in summary.get("agents", [])} and kind != "task":
            agent, text = m[1], m[2]                      # the guest chose an agent; the owner sees the text without the tag
        if kind == "task":
            agent = summary["act_agent"]
        r = {"request_id": rid, "guest_id": guest["guest_id"], "agent_alias": agent,
             "thread_id": thread, "text": text, "text_hash": sha256_text(text), "approval_code": secrets.choice(choices),
             "capability": "act" if kind == "task" else "ask", "state": "waitingApproval", "terminal_reason": None,
             "created_at": t, "updated_at": t, "deadline_at": t + 43200, "reply": None,
             "retry_at": 0, "attempts": 0}
        self.s["requests"][rid] = r
        self._remember(guest["guest_id"], "guest", text)
        if kind == "task":                                   # every task has a card on the board that follows it to Done or Review
            r["card_id"] = card_id
            if card_id:                                      # the guest's own card: keep their words, just start it
                self._panel_job({"op": "card.update", "card_id": card_id, "column": "doing", "request_id": rid})
            else:
                self._panel_job({"op": "card.add", "owner": self._owner_key(guest), "title": " ".join(text.split())[:80],
                                 "note": text[:1000], "column": "doing", "request_id": rid})
        count = self._counts(guest["guest_id"])[0]
        if self._approval_mode(guest) == "auto":
            self._sms(thread, "Got it. I'll do this and check the result." if kind == "task" else "Got it. Working on it.", rid + ":received")
            self._decide(r, "approve", "auto:policy", r["text_hash"])   # limits, budget and the sandbox are the guardrails
            return rid
        more = " [Request longer than 300 characters: read the full text before approving.]" if len(text) > 300 else ""
        self._sms(thread, "Received. The owner will approve it before I answer.", rid + ":received")
        self._sms(self.s["owner_thread"], f'Door: {guest["display_name"] or "Guest"} asks {"the Boss" if r["agent_alias"] == "auto" else r["agent_alias"]}: '
                  f'"{text[:300]}" ({count}/{guest["limits"]["daily_requests"]} today, '
                  f'{self._counts(guest["guest_id"])[2]} tokens). Reply YES {r["approval_code"]} or '
                  f'NO {r["approval_code"]}.{more} Full text: {self.panel_url}/#{rid}', rid + ":approval")
        return rid

    def _owner_command(self, text):
        self._note_owner_lang(text)
        command = norm_text(text)
        match = re.fullmatch(r"(YES|NO) (\d{4})", command)
        thread = self.s["owner_thread"]
        if match:
            r = next((r for r in self.s["requests"].values() if r["state"] == "waitingApproval"
                      and r["approval_code"] == match[2]), None)
            if r is None and self._confirm_trust(match[2], match[1] == "YES"):
                return
            if r is None:
                for q in self.s["requests"].values():                 # not a question waiting: maybe a step of a running task
                    for a in (q.get("actions") or {}).values():
                        if a["code"] == match[2] and not a.get("decided"):
                            self.decide_action(q["request_id"], a["id"], "allow" if match[1] == "YES" else "deny", "sms:" + self.s["owner_phone"])
                            return
                self._sms(thread, "Code not found or request already decided.")
                return
            self._decide(r, "approve" if match[1] == "YES" else "deny", "sms:" + self.s["owner_phone"], r["text_hash"])
        elif command.startswith(("YES", "NO", "OK")):
            self._sms(thread, "Reply YES or NO followed by the request code.")
        elif command in {"DOOR PAUSE", "DOOR RESUME"}:
            self._pause(command == "DOOR PAUSE")
        elif command == "DOOR QUEUE":
            n = sum(r["state"] == "waitingApproval" for r in self.s["requests"].values())
            self._sms(thread, f"{n} requests are waiting for approval. {self.panel_url}")
        elif command == "DOOR TODAY":
            n = sum(day_key(r["created_at"]) == day_key(self.clock()) for r in self.s["requests"].values())
            self._sms(thread, f"Today: {n} requests. Spend this month: USD {self._spend():.4f}. {self.panel_url}")
        elif command.startswith("DOOR PAIR:"):
            self.s["commands"][ulid()] = {"op": "pair-confirm", "code": text.split(":", 1)[1].strip(), "done": False}
        elif command == "DOOR PANEL":
            self._panel_job({"op": "signin", "thread": thread})
        elif command == "DOOR GUESTS":
            self._list_guests(thread)
        elif OWNER_NAME_CMD.fullmatch(text.strip()):
            m = OWNER_NAME_CMD.fullmatch(text.strip())
            self._owner_name_command(thread, m[1].lower(), (m[2] or "").strip())
        elif command in {"HELP", "COMMANDS", "?", "DOOR HELP"} or command.startswith("DOOR "):
            self._sms(thread, "Just write to me. A question gets an answer about the project; something to do (\"Do: add a footer\") is done on a copy of it "
                              "and checked. Commands: YES/NO <code>; DOOR LINK <name>; DOOR INVITE <name>; DOOR GUESTS; DOOR REVOKE <name>; "
                              "DOOR PANEL (sign-in link); DOOR PAUSE/RESUME; DOOR QUEUE; DOOR TODAY. "
                              "Letting someone run tasks is only done in the panel.")
        else:
            self._owner_request(thread, text)

    def _owner_guest(self):
        """The owner talks to their own agent like anyone else, but with no daily cap, no approval to give themselves and tasks always allowed
        (every risky step of a task still waits for the owner). Stored like a guest (with a real ULID, which the Mac insists on) so history,
        limits, cards and proof work unchanged; hidden from every list of guests."""
        for key in [k for k, v in self.s["guests"].items() if v.get("owner") and not ULID_RE.fullmatch(k)]:
            self.s["guests"].pop(key)                            # an earlier build used the id "owner", which the Mac rejects
        g = next((g for g in self.s["guests"].values() if g.get("owner")), None)
        if g is None:
            gid = ulid()
            g = self.s["guests"][gid] = dict(guest_id=gid, phone=self.s["owner_phone"], display_name="You", status="active", owner=True,
                                             expires_at=2 ** 40, level="act", approval="auto",
                                             limits={"daily_requests": 500, "daily_tokens": 4000000, "max_open_requests": 3})
        g["phone"] = self.s["owner_phone"]
        return g

    def _looks_like_a_task(self, text):
        t = text.strip().lower()
        if t.endswith("?") or QUESTION_START.match(t):
            return False
        return True

    def _owner_request(self, thread, text):
        guest = self._owner_guest()
        kind = "chat"
        if not TASK_RE.match(text) and self._looks_like_a_task(text):
            if self.s["summary"].get("act_agent"):
                kind = "task"
            else:
                self._sms(thread, "I can answer questions about the project. To have me do things (edit files, run checks), turn tasks on for this "
                                  "agent in your Door settings, then ask again. Meanwhile, ask it as a question and I will answer from the code.")
                return
        self._guest_message(guest, thread, text, kind)

    def _list_guests(self, thread):
        gs = sorted((g for g in self.s["guests"].values() if not g.get("owner")), key=lambda g: g.get("display_name") or g["phone"] or "")
        if not gs:
            self._sms(thread, "No guests yet. Text DOOR LINK <name> or DOOR INVITE <name>.")
            return
        lines = ["%s (%s%s)" % (g.get("display_name") or g["phone"] or "web guest", g["status"], ", tasks" if g.get("level") == "act" else "") for g in gs[:12]]
        self._sms(thread, "Guests: " + "; ".join(lines) + (" and more" if len(gs) > 12 else ""))

    def _owner_name_command(self, thread, verb, name):
        """Owner-only text commands that let the owner hand out access through the agent itself. They can only create question-level
        access (a one-time code or a link that opens on one device); tasks are granted in the panel."""
        if verb == "invite":
            try:
                code = self.create_invite(name)
            except ValueError as e:
                self._sms(thread, "Could not make an invite: %s" % e)
                return
            self._sms(thread, "Invite%s: %s. Tell them to text this number: Door Join: %s (valid 7 days, works once)." % (
                (" for " + name) if name else "", code, code))
        elif verb == "link":
            self._panel_job({"op": "link.create", "thread": thread, "name": name, "days": 30, "ttl_days": 7})
        elif verb == "revoke":
            if not name:
                self._sms(thread, "Say who: DOOR REVOKE <name>.")
                return
            hits = [g for g in self.s["guests"].values() if not g.get("owner") and (g.get("display_name") or "").lower() == name.lower() and g["status"] != "revoked"]
            if len(hits) != 1:
                self._sms(thread, "I found %d guests named %s. Use the panel to pick the right one." % (len(hits), name))
                return
            self.set_guest_status(hits[0]["guest_id"], "revoked")
            if hits[0].get("link_id"):
                for r in list(self.s["requests"].values()):
                    if r["guest_id"] == hits[0]["guest_id"] and r["state"] not in TERMINAL:
                        self._cancel(r, "owner_canceled")
            self._sms(thread, "%s no longer has access." % hits[0]["display_name"])

    def _transition(self, r, state, reason=None):
        if state not in TRANSITIONS.get(r["state"], set()):
            raise ValueError("invalid transition")
        r.update(state=state, updated_at=self.clock(), terminal_reason=reason)

    def _decide(self, r, decision, identity, text_hash):
        if r["state"] != "waitingApproval" or self.clock() > r["deadline_at"]:
            raise ValueError("request already decided or expired")
        if sha256_text(r["text"]) != r["text_hash"] or text_hash != r["text_hash"]:
            raise ValueError("text was changed")
        if decision not in {"approve", "deny"}:
            raise ValueError("invalid decision")
        r["approval"] = dict(request_id=r["request_id"], text_hash=text_hash, decided_by=identity,
                             decision=decision, at=self.clock())
        self._transition(r, "queued" if decision == "approve" else "canceled",
                         None if decision == "approve" else "denied_owner")
        if decision == "deny":
            self._sms(r["thread_id"], "The owner declined this request.", r["request_id"] + ":final")

    def decide(self, rid, decision, session, text_hash):
        with self.lock:
            self._decide(self.s["requests"][rid], decision, "panel:" + session, text_hash)
            self._save()

    def _pause(self, paused):
        self.s["paused"] = bool(paused)
        self.s["commands"][ulid()] = {"op": "pause" if paused else "resume", "done": False}

    def pause(self, paused):
        with self.lock:
            self._pause(paused)
            self._save()

    HOST_REJECTIONS = {
        "export_secrets": ("I can't answer right now: a safety check on the project failed. The owner has been told.",
                           "Door: a question was NOT answered because the safety scan found something that looks like a secret in the shared project. "
                           "On your Mac run `door-host audit` to see which file, then remove it or add it to the agent's \"exclude\" list."),
        "export_failed": ("I can't answer right now: the project could not be prepared. The owner has been told.",
                          "Door: the project could not be copied for a question. Check that the repository path in your policy exists and has commits."),
        "sandbox_unavailable": ("I can't answer right now: the owner's computer isn't ready. The owner has been told.",
                                "Door: your Mac could not start the isolated container. Is Docker running? `door-host doctor` shows what is wrong."),
        "not_paired": ("I can't answer right now: the owner's computer isn't connected.", None),
    }

    def _rejection_text(self, r, why):
        guest_text, owner_text = self.HOST_REJECTIONS.get(why, (None, None))
        if owner_text and not self.s["alerts"].get("host:" + str(why)) == day_key(self.clock()):
            self.s["alerts"]["host:" + str(why)] = day_key(self.clock())
            self._sms(self.s["owner_thread"], owner_text, "hostfail:" + str(why) + ":" + day_key(self.clock()))
        return guest_text

    def _cancel(self, r, reason, guest_text=None):
        if r["state"] == "running":
            self.s["commands"][ulid()] = {"op": "cancel", "request": r["request_id"], "reason": reason, "done": False}
        self._transition(r, "canceled", reason)
        if r.get("capability") == "act":
            self._panel_job({"op": "card.update", "request_id": r["request_id"], "column": "review", "verdict": "canceled",
                             "proof": "Stopped: %s" % reason})
        self._sms(r["thread_id"], guest_text or "Request canceled.", r["request_id"] + ":final")

    def cancel(self, rid):
        with self.lock:
            r = self.s["requests"][rid]
            if r["state"] not in TERMINAL:
                self._cancel(r, "owner_canceled")
                self._save()

    def tick(self):
        with self.lock:
            t = self.clock()
            for r in self.s["requests"].values():
                if r["state"] in {"waitingApproval", "queued"} and t > r["deadline_at"]:
                    self._cancel(r, "expired")
                elif r["state"] == "queued" and t - r["updated_at"] > 600:
                    self._sms(r["thread_id"], "The Mac is not available yet. Your request is still queued.",
                              r["request_id"] + ":offline")
                if r["state"] in TERMINAL and t - r["updated_at"] > 30 * 86400:
                    r.pop("text", None)
                    if r.get("reply"):
                        r["reply"] = {"held": r["reply"].get("held", False)}
            for gid in list(self.s["convos"]):
                self.s["convos"][gid] = [e for e in self.s["convos"][gid] if t - e["at"] <= 30 * 86400]
                if not self.s["convos"][gid]:
                    del self.s["convos"][gid]
            d = day_key(t)
            if self.s["unknown"] and self.s["alerts"].get("unknown") != d:
                self._sms(self.s["owner_thread"], "Unknown numbers (no content): " + ", ".join(self.s["unknown"]))
                self.s["alerts"]["unknown"] = d
            self.s["unknown"] = {p: at for p, at in self.s["unknown"].items() if t - at < 86400}
            plan = self.s["plan"]
            if plan["status"] == "active" and t > plan["active_until"] and self.s["alerts"].get("plan") != d:
                self._sms(self.s["owner_thread"], "Subscription expired. You have 7 days to renew.")
                self.s["alerts"]["plan"] = d
            if self._spend() >= self.s["summary"]["limits"]["monthly_budget"]:
                m = month_key(t)
                if self.s["alerts"].get("budget") != m:
                    self._sms(self.s["owner_thread"], "Door: monthly budget used up; new requests are blocked.")
                    self.s["alerts"]["budget"] = m
            self._save()

    def guest_limits(self, gid, limits, expires_at=None):
        if set(limits) != {"daily_requests", "daily_tokens", "max_open_requests"} or any(type(v) is not int or v <= 0 for v in limits.values()):
            raise ValueError("invalid limits")
        if expires_at is not None and not self.clock() < expires_at <= self.clock() + 90 * 86400:
            raise ValueError("validity must be at most 90 days")
        with self.lock:
            self.s["guests"][gid]["limits"] = limits
            if expires_at is not None:
                self.s["guests"][gid]["expires_at"] = expires_at
            self._save()

    def dispatch(self, relay):
        """Relay executa fora do lock. Em perda de resposta, ask é repetido com o mesmo ID."""
        with self.lock:
            if self.s["paused"] or any(r["state"] == "running" for r in self.s["requests"].values()):
                return
            queued = sorted((r for r in self.s["requests"].values() if r["state"] == "queued"
                             and r["retry_at"] <= self.clock()), key=lambda r: r["created_at"])
            if not queued:
                return
            r = queued[0]
            if self.clock() > r["deadline_at"]:
                self._cancel(r, "expired")
                self._save()
                return
            if self._spend() >= self.s["summary"]["limits"]["monthly_budget"]:
                self._cancel(r, "budget")
                self._save()
                return
            if sha256_text(r["text"]) != r["text_hash"] or r.get("approval", {}).get("text_hash") != r["text_hash"]:
                self._cancel(r, "rejected_host")
                self._save()
                return
            # Não envia telefone nem thread ao sandbox/host.
            req = {k: r[k] for k in ("request_id", "guest_id", "agent_alias", "text", "text_hash",
                                    "capability", "approval", "deadline_at")}
            guest = self.s["guests"][r["guest_id"]]
            if guest["status"] != "active" or guest["expires_at"] <= self.clock():
                self._cancel(r, "denied_rules")
                self._save()
                return
            req["guest_limits"] = guest["limits"]
            req["guest_level"] = guest.get("level", "ask")
            req["history"] = self._history_for(r["guest_id"], r)
            payload, sig = encode(self.s["private"], req)
            rid = r["request_id"]
        try:
            out = relay.ask(rid, payload, sig)
        except (OSError, TimeoutError):
            out = {"retry": True}
        with self.lock:
            r = self.s["requests"][rid]
            if r["state"] != "queued":
                if out.get("ok"):
                    self.s["commands"][ulid()] = {"op": "cancel", "request": rid, "reason": "owner_canceled", "done": False}
            elif out.get("ok"):
                self._transition(r, "running")
                r["started_at"] = self.clock()
                self.s["host_online_at"] = self.clock()
                if out.get("state") in TERMINAL:
                    self._result(r, out)
            elif out.get("retry"):
                r["attempts"] += 1
                r["retry_at"] = self.clock() + min(300, 2 ** min(r["attempts"], 8))
            else:
                self._cancel(r, "rejected_host", self._rejection_text(r, out.get("reason")))
            self._save()

    def _finish_card(self, r, out):
        """Move the task's card to Done only when the delivery was verified; everything else goes to Review with the reason."""
        from .act import DONE_VERDICTS
        act = (out.get("reply") or {}).get("act") or {}
        verdict = act.get("verdict") or ("incomplete" if out["state"] != "completed" else "")
        done = out["state"] == "completed" and verdict in DONE_VERDICTS
        lines = []
        if act.get("branch"):
            lines.append("Branch: %s" % act["branch"])
        if act.get("files"):
            lines.append("Changed: %s" % ", ".join(act["files"][:8]))
        for p in act.get("proof") or []:
            lines.append("Check %s: %s" % (p["cmd"], "passed" if p["rc"] == 0 else "FAILED (exit %s)" % p["rc"]))
        if (act.get("verifier") or {}).get("verdict"):
            lines.append("Independent check: %s %s" % (act["verifier"]["verdict"], act["verifier"].get("reason", "")))
        if out["state"] != "completed":
            lines.append("Stopped: %s" % out.get("reason", out["state"]))
        self._panel_job({"op": "card.update", "request_id": r["request_id"], "column": "done" if done else "review",
                         "verdict": verdict or out["state"], "proof": "\n".join(lines)[:1500]})

    def _result(self, r, out):
        for u in out.get("usage", {}).get("samples", []):
            self.s["usage"].setdefault(u["id"], dict(u, guest_id=r["guest_id"], recorded_at=u.get("recorded_at", self.clock())))
        state = out["state"]
        if out.get("agent"):
            r["answered_by"] = out["agent"]
        if (out.get("reply") or {}).get("refused"):
            r["refused"] = True
        act = (out.get("reply") or {}).get("act")
        if act:
            r["act"] = {k: act.get(k) for k in ("verdict", "branch", "files", "diffstat", "proof", "verifier", "summary")}
        if r.get("capability") == "act" and r.get("card_id") is not False:
            self._finish_card(r, out)
        if (out.get("reply") or {}).get("verification"):
            r["verification"] = {k: out["reply"]["verification"].get(k) for k in ("status", "checked", "verified", "files")}
        if state == "completed":
            r["reply"] = out["reply"]
            if not out["reply"].get("held") and not out["reply"].get("refused"):
                self._remember(r["guest_id"], "agent", out["reply"]["text"])
            self._transition(r, state)
            self._sms(r["thread_id"], r["reply"]["text"], r["request_id"] + ":final")
        elif state in {"failed", "canceled"}:
            reason = out.get("reason", "sandbox_error")
            if reason not in {"budget", "timeout", "sandbox_error", "guest_canceled", "owner_canceled"}:
                reason = "sandbox_error"
            self._transition(r, state, reason)
            self._sms(r["thread_id"], "This request could not be answered. The owner was informed.", r["request_id"] + ":final")

    def poll(self, relay):
        with self.lock:
            ids = [r["request_id"] for r in self.s["requests"].values() if r["state"] == "running"]
        for rid in ids:
            try:
                out = relay.status(rid)
            except (OSError, TimeoutError):
                continue
            with self.lock:
                if out.get("ok"):
                    self.s["host_online_at"] = self.clock()
                r = self.s["requests"][rid]
                if out.get("ok") and r["state"] == "running" and "pending_actions" in out:
                    self._note_actions(r, out["pending_actions"])
                if r["state"] == "running" and out.get("state") in TERMINAL:
                    self._result(r, out)
                elif r["state"] == "running" and not out.get("ok") and out.get("reason") == "unknown_request":
                    self._result(r, {"state": "failed", "reason": "sandbox_error"})
                self._save()

    def held(self, rid, release):
        with self.lock:
            r = self.s["requests"][rid]
            reply = r.get("reply") or {}
            if not reply.get("held") or reply.get("reviewed"):
                raise ValueError("reply is not pending review")
            reply["reviewed"] = "released" if release else "discarded"
            if release:
                self._sms(r["thread_id"], reply["held_text"], rid + ":released")
            reply.pop("held_text", None)
            self._save()

    def snapshot(self):
        with self.lock:
            spent = self._spend()
            limit = self.s["summary"]["limits"]["monthly_budget"]
            percent = spent / limit if limit else 1
            usage = list(self.s["usage"].values())
            total_tokens = sum(u["input_tokens"] + u["output_tokens"] for u in usage)
            guest_usage = {}
            for gid in self.s["guests"]:
                samples = [u for u in usage if u["guest_id"] == gid]
                count, _, daily = self._counts(gid)
                guest_usage[gid] = {"tokens": sum(u["input_tokens"] + u["output_tokens"] for u in samples),
                                    "cost": sum(u["cost"] for u in samples), "daily_requests": count, "daily_tokens": daily}
            active_seconds = sum(max(0, r["updated_at"] - r.get("started_at", r["updated_at"]))
                                 for r in self.s["requests"].values())
            return copy.deepcopy({"owner_id": self.s["owner_id"], "agent": self.s["summary"],
                                  "requests": list(self.s["requests"].values()), "guests": [g for g in self.s["guests"].values() if not g.get("owner")],
                                  "owner_ids": [g["guest_id"] for g in self.s["guests"].values() if g.get("owner")],
                                  "plan": self.s["plan"], "paused": self.s["paused"], "guest_usage": guest_usage,
                                  "settings": self.s["settings"],
                                  "setup": {"activated": bool(self.s["owner_phone"]), "paired": bool(self.s.get("host_id")),
                                            "activation_code": None if self.s["owner_phone"] else self.s.get("activation")},
                                  "actions": [dict(a, request_id=q["request_id"], guest_id=q["guest_id"]) for q in self.s["requests"].values()
                                              for a in (q.get("actions") or {}).values() if not a.get("decided")],
                                  "invites": [v for v in self.s["invites"].values() if not v["used"] and v["expires_at"] > self.clock()],
                                  "access_requests": list(self.s["access_requests"].values()),
                                  "command_results": self.s.get("panel_seen", {}),
                                  "host_online": self.clock() - self.s["host_online_at"] < 120,
                                  "telemetry": {"workspace_id": self.s["workspace_id"], "generated_at": iso(self.clock()),
                                                "source": "exact", "total_cost": spent, "currency": "USD",
                                                "total_tokens": total_tokens, "known_tokens": total_tokens,
                                                "burn_per_minute": spent / (active_seconds / 60) if active_seconds else 0,
                                                "active_seconds": active_seconds, "sample_count": len(usage), "unavailable_samples": 0,
                                                "agents": [{"node_id": self.s["agent_node_id"], "agent_name": self.s["summary"]["alias"],
                                                            "adapter": "claude", "source": "exact", "currency": "USD",
                                                            "total_tokens": total_tokens, "estimated_cost": spent,
                                                            "active_seconds": active_seconds, "sample_count": len(usage), "unavailable_samples": 0}],
                                                "budget": {"workspace_id": self.s["workspace_id"], "limit": limit, "currency": "USD",
                                                           "warning_thresholds": [.5, .8, 1], "updated_at": iso(self.clock())},
                                                "budget_percent": percent, "alerts": [f"budget_{int(n*100)}" for n in [.5, .8, 1] if percent >= n]}})
