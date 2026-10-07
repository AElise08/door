"""door-host: fronteira de política no Mac (Seções 8.4, 9, 16.4)."""
import base64
import hashlib
import json
import re
import os
import secrets
import shutil
import socket
import socketserver
import stat
import threading
from pathlib import Path

from . import act, exporter, outfilter, sandbox
from . import replytext
from . import verify as answer_check
from .audit import Audit
from .common import now, sha256_text, ulid, ULID_RE
from .envelope import verify
from .policy import PolicyHolder, cloud_summary
from .proxy import Ctx, EgressProxy

MAX_TEXT = 1600
HELD_MSG = "The owner is reviewing this reply."
PAIR_TTL = 600


class Host:
    def __init__(self, policy_path, state_dir, runtime, credential, proxy_scheme=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        for d in ("requests", "exports", "outboxes"):
            (self.state_dir / d).mkdir(exist_ok=True, mode=0o700)
        self.audit = Audit(self.state_dir / "audit.jsonl")
        self.holder = PolicyHolder(policy_path, self.state_dir,
                                   on_event=lambda ev, d: self.audit.write(ev, detail=d))
        if self.holder.policy is None:
            raise RuntimeError("invalid policy: %s" % self.holder.error)
        pol = self.holder.policy
        eg = pol["egress"]
        self.runtime = runtime
        self.proxy = EgressProxy(eg["allow_hosts"], credential, eg["pricing"], scheme=proxy_scheme or eg["upstream_scheme"],
                                 on_usage=self._on_usage, style=eg["style"], path_prefix=eg["path_prefix"],
                                 login_hosts=eg["allow_hosts"] if eg.get("mode") == "login" else None)
        self._slot = threading.Lock()
        self._running = {}  # request_id -> {"name", "cancel_reason"}
        self._guard = threading.Lock()
        self._ask_guard = threading.Lock()
        self._acts = {}
        self._recover()

    # ---------- estado em disco ----------
    def _rf(self, rid):
        if not isinstance(rid, str) or not ULID_RE.fullmatch(rid):
            raise ValueError("invalid request_id")
        return self.state_dir / "requests" / (rid + ".json")

    def _save(self, rid, data):
        tmp = self._rf(rid).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(self._rf(rid))

    def _load(self, rid):
        try:
            return json.loads(self._rf(rid).read_text())
        except (OSError, ValueError):
            return None

    def _kv(self, name, default=None):
        try:
            return json.loads((self.state_dir / name).read_text())
        except (OSError, ValueError):
            return default

    def _set_kv(self, name, value):
        p = self.state_dir / name
        p.write_text(json.dumps(value))
        os.chmod(p, 0o600)

    def _recover(self):
        """9.5: reinício destrói sandbox/exportação/outbox de qualquer pedido que ficou pelo caminho."""
        for f in (self.state_dir / "requests").glob("*.json"):
            r = self._load(f.stem)
            if r and r.get("state") == "running":
                r.update(state="failed", reason="sandbox_error", detail="host_restart")
                self._save(f.stem, r)
        for d in ("exports", "outboxes"):
            for p in (self.state_dir / d).iterdir():
                shutil.rmtree(p, ignore_errors=True)
        try:
            self.runtime.cleanup_stale()
        except Exception:
            pass

    # ---------- pareamento (6.1) ----------
    def pair_start(self):
        code = secrets.token_urlsafe(6).upper().replace("-", "A").replace("_", "B")
        self._set_kv("pair.json", {"code_hash": hashlib.sha256(code.encode()).hexdigest(), "expires": now() + PAIR_TTL})
        return {"code": code, "expires_in": PAIR_TTL}

    def pair_confirm(self, code, public_key):
        try:
            if len(bytes.fromhex(public_key)) != 32:
                raise ValueError()
        except (ValueError, TypeError):
            return {"ok": False, "reason": "invalid_public_key"}
        p = self._kv("pair.json")
        if not p or now() > p["expires"] or not secrets.compare_digest(
                p["code_hash"], hashlib.sha256((code or "").strip().upper().encode()).hexdigest()):
            return {"ok": False, "reason": "invalid_code"}
        (self.state_dir / "pair.json").unlink(missing_ok=True)  # uso único
        host = {"host_id": ulid(), "public_key": public_key}
        self._set_kv("host.json", host)
        self.audit.write("policy_reloaded", detail={"paired": host["host_id"]})
        return {"ok": True, "host_id": host["host_id"], "summary": cloud_summary(self.holder.policy)}

    def summary(self):
        self.holder.refresh()
        return {"ok": True, "summary": cloud_summary(self.holder.policy), "paused": self.paused(), "online": True}

    # ---------- pausa ----------
    def paused(self):
        return (self.state_dir / "paused").exists()

    def set_paused(self, v):
        p = self.state_dir / "paused"
        p.touch() if v else p.unlink(missing_ok=True)
        self.audit.write("paused", detail={"paused": bool(v)})
        return {"ok": True, "paused": bool(v)}

    # ---------- recheque (8.4) ----------
    def _recheck(self, req, pol):
        if not isinstance(req, dict) or not isinstance(req.get("text"), str) or not isinstance(req.get("approval"), dict) \
           or not ULID_RE.fullmatch(str(req.get("guest_id", ""))):
            return {"ok": False, "reason": "bad_payload"}
        lim = pol["limits"]
        aliases = {x["alias"] for x in pol["agents"]} | ({"auto"} if pol["boss"]["enabled"] else set())
        text = req.get("text") or ""
        ap = req.get("approval") or {}
        checks = [
            (req.get("agent_alias") in aliases, "alias"),
            (req.get("capability", "ask") == "ask" or self._act_allowed(req, pol), "capability"),
            (0 < len(text.strip()) and len(text) <= MAX_TEXT, "text_size"),
            (sha256_text(text) == req.get("text_hash"), "text_hash"),
            (ap.get("request_id") == req.get("request_id") and ap.get("text_hash") == req.get("text_hash")
             and ap.get("decision") == "approve", "approval"),
            (isinstance(req.get("deadline_at"), (int, float)) and now() <= req["deadline_at"], "expired"),
            (not self.paused(), "paused"),
            (self.audit.guest_requests_today(req["guest_id"]) < lim["guest_daily_requests"], "guest_daily_requests"),
            (self.audit.guest_tokens_today(req["guest_id"]) < lim["guest_daily_tokens"], "guest_daily_tokens"),
            (self.audit.month_spend() < lim["monthly_budget"], "monthly_budget"),
        ]
        for ok, name in checks:
            if not ok:
                return {"ok": False, "reason": name}
        if not self.runtime.available():
            return {"ok": False, "reason": "sandbox_unavailable"}
        try:
            if hasattr(self.runtime, "ensure_network") and self.proxy.port:
                self.runtime.ensure_network(self.proxy.port)
        except (RuntimeError, OSError):
            return {"ok": False, "reason": "sandbox_unavailable"}
        return {"ok": True}

    @staticmethod
    def _act_allowed(req, pol):
        """Tasks need: the owner's act block on that agent, and the cloud saying this guest is a trusted (act-level) guest."""
        prof = next((x for x in pol["agents"] if x["alias"] == req.get("agent_alias")), None)
        return req.get("capability") == "act" and req.get("guest_level") == "act" and bool(prof and prof.get("act"))

    # ---------- ask ----------
    def ask(self, payload_b64, sig):
        with self._ask_guard:
            return self._ask(payload_b64, sig)

    def _ask(self, payload_b64, sig):
        host = self._kv("host.json")
        if not host:
            return {"ok": False, "reason": "not_paired"}
        try:
            raw = base64.b64decode(payload_b64, validate=True)
            req = json.loads(raw)
            rid, gid = str(req["request_id"]), str(req["guest_id"])
            self._rf(rid)
        except (ValueError, KeyError, TypeError):
            return {"ok": False, "reason": "bad_payload"}
        if not verify(host["public_key"], raw, sig):
            return {"ok": False, "reason": "bad_signature"}
        existing = self._load(rid)
        if existing:  # idempotência (6.2)
            return self._public(existing)
        pol = self.holder.refresh()
        self.audit.write("request_received", rid, gid, req.get("agent_alias", ""), {"text": req.get("text"), "text_hash": req.get("text_hash")})
        d = self._recheck(req, pol)
        if d["ok"] and not self._slot.acquire(blocking=False):
            d = {"ok": False, "reason": "busy"}
        self.audit.write("recheck", rid, gid, req.get("agent_alias", ""), d)
        if not d["ok"]:
            return {"ok": False, "state": "rejected", "reason": d["reason"], "retry": d["reason"] == "busy"}
        if req.get("capability") == "act":
            profile = next(x for x in pol["agents"] if x["alias"] == req["agent_alias"])
            self._save(rid, {"state": "running", "request_id": rid, "guest_id": gid, "started": now()})
            with self._guard:
                self._running[rid] = {"name": "door-act-" + rid.lower(), "cancel_reason": None}
            self.audit.write("act_started", rid, gid, profile["alias"], {"project_set": True})
            threading.Thread(target=self._work_act, args=(req, pol, profile), daemon=True).start()
            return {"ok": True, "state": "running", "request_id": rid}
        auto = req.get("agent_alias") == "auto"
        profile = None if auto else next(x for x in pol["agents"] if x["alias"] == req["agent_alias"])
        alias = "auto" if auto else profile["alias"]
        exp = self.state_dir / "exports" / rid
        try:
            findings = [] if auto else exporter.build_export(profile["exports"], exp)
            if findings:
                shutil.rmtree(exp, ignore_errors=True)
                self.audit.write("export_built", rid, gid, alias, {"ok": False, "findings": findings})
                self._slot.release()
                return {"ok": False, "state": "rejected", "reason": "export_secrets"}
        except Exception as e:
            self._slot.release()
            self.audit.write("export_built", rid, gid, alias, {"ok": False, "error": str(e)})
            return {"ok": False, "state": "rejected", "reason": "export_failed"}
        if not auto:
            self.audit.write("export_built", rid, gid, alias, {"ok": True})
        outbox = self.state_dir / "outboxes" / rid
        outbox.mkdir(mode=0o777)
        os.chmod(outbox, 0o777)
        st = {"state": "running", "request_id": rid, "guest_id": gid, "started": now()}
        self._save(rid, st)
        with self._guard:
            self._running[rid] = {"name": "door-run-" + rid.lower(), "cancel_reason": None}
        self.audit.write("sandbox_started", rid, gid, alias)
        threading.Thread(target=self._work, args=(req, pol, exp, outbox, profile), daemon=True).start()
        return {"ok": True, "state": "running", "request_id": rid}

    @staticmethod
    def _clean_history(raw, items=12, chars=6000):
        """The cloud's history is untrusted data: keep only well-formed turns, bounded in count and size, newest turns first."""
        if not isinstance(raw, list):
            return []
        good = [{"role": x["role"], "text": x["text"][:1500]} for x in raw
                if isinstance(x, dict) and x.get("role") in ("guest", "agent") and isinstance(x.get("text"), str) and x["text"].strip()]
        out, size = [], 0
        for x in reversed(good[-items:]):
            size += len(x["text"])
            if size > chars:
                break
            out.append(x)
        return list(reversed(out))

    def _work_act(self, req, pol, profile):
        rid, gid, alias = req["request_id"], req["guest_id"], profile["alias"]
        cfg = profile["act"]
        runner = act.ActRunner(rid, cfg, self.state_dir, cfg["claude_bin"], cfg["approval_timeout_s"])
        runner.on_event = lambda ev, d: self.audit.write(ev, rid, gid, alias, d)
        with self._guard:
            self._acts[rid] = runner
            info = self._running[rid]
        result = {"state": "failed", "reason": "sandbox_error", "request_id": rid}
        run, usage = None, {"tokens": 0, "cost": 0.0, "samples": []}
        try:
            if info["cancel_reason"]:
                result = {"state": "canceled", "reason": info["cancel_reason"]}
                return
            task = req["text"]
            run = runner.run(sandbox.build_task_prompt(profile["instructions"], task, self._clean_history(req.get("history"))),
                             " ".join(task.split())[:70])
            if info["cancel_reason"] or run["cancelled"]:
                result = {"state": "canceled", "reason": info["cancel_reason"] or "owner_canceled"}
            elif run["timed_out"]:
                result = {"state": "failed", "reason": "timeout"}
            else:
                verifier, reason = None, ""
                if run["changed_files"] and not run["error"]:
                    verifier, reason, usage = self._verify_delivery(req, pol, run)
                v = act.verdict(run, verifier)
                text = replytext.task_reply(req["text"], run, v, reason, pol["outbound"]["max_reply_chars"], to_owner=bool(req.get("to_owner")))
                f = outfilter.filter_reply(text, pol["outbound"]["max_reply_chars"], [socket.gethostname()])
                held = f["redactions"] >= pol["outbound"]["hold_threshold"]
                result = {"state": "completed", "verdict": v, "reply": {
                    "text": HELD_MSG if held else f["text"], "held": held, "redactions": f["redactions"],
                    "held_text": f["text"] if held else None, "owner_text": text,
                    "act": {"verdict": v, "branch": run["branch"], "files": run["changed_files"][:50], "diffstat": run["diffstat"],
                            "proof": run["proof"], "verifier": {"verdict": verifier, "reason": reason},
                            "commands_run": run["commands_run"][:30], "summary": " ".join(run["summary"].split())[:600]}}}
                self.audit.write("act_finished", rid, gid, alias, {"verdict": v, "files": len(run["changed_files"]), "branch": run["branch"],
                                                                   "proof": [(p["cmd"], p["rc"]) for p in run["proof"]]})
        except Exception as e:
            result = {"state": "failed", "reason": "sandbox_error", "detail": type(e).__name__}
        finally:
            with self._guard:
                self._acts.pop(rid, None)
                self._running.pop(rid, None)
            result.update(request_id=rid, agent=alias, usage=usage)
            self._save(rid, result)
            self._slot.release()

    def _verify_delivery(self, req, pol, run):
        """The independent check: a read-only model call that sees Door's evidence (diff, checks) and says VERIFIED or NOT_VERIFIED.
        Any failure to get an answer returns None, which can never make a task look verified."""
        rid, gid = req["request_id"], req["guest_id"]
        usage = {"tokens": 0, "cost": 0.0, "samples": []}
        boss, sb, lim = pol["boss"], pol["sandbox"], pol["limits"]
        empty, outbox = self.state_dir / "exports" / (rid + "-verify"), self.state_dir / "outboxes" / (rid + "-verify")
        ctx = Ctx(rid, gid, min(lim["max_turn_tokens"], lim["guest_daily_tokens"] - self.audit.guest_tokens_today(gid)),
                  lim["max_output_tokens"], max(0.0, lim["monthly_budget"] - self.audit.month_spend()), boss["model"])
        token = None
        try:
            empty.mkdir(mode=0o755); outbox.mkdir(mode=0o777); os.chmod(outbox, 0o777)
            token = self.proxy.bind(ctx)
            evidence = {"files": run["changed_files"], "diffstat": run["diffstat"], "diff": run["diff"], "proof": run["proof"]}
            spec = {"name": "door-verify-" + rid.lower(), "export_dir": str(empty), "outbox_dir": str(outbox), "boss": True, "backend": boss["backend"],
                    "provider": pol["egress"]["provider"], "login": pol["egress"].get("mode") == "login", "placeholder_key": token,
                    "model": boss["model"], "cpus": sb["cpus"], "memory_mb": sb["memory_mb"],
                    "prompt": sandbox.build_verify_prompt(req["text"], run["summary"], evidence, boss["backend"])}
            rr = self.runtime.run(spec, 150)
            ans = self._read_answer(outbox) if rr.exit_code == 0 and not rr.timed_out else None
        except Exception:
            ans = None
        finally:
            if token:
                self.proxy.unbind(token)
            shutil.rmtree(empty, ignore_errors=True); shutil.rmtree(outbox, ignore_errors=True)
            usage = {"tokens": ctx.tokens, "cost": round(ctx.cost, 6), "samples": ctx.samples}
        m = re.match(r"\s*\W*(VERIFIED|NOT_VERIFIED)\b\W*(.*)", ans or "", re.I | re.S)
        if not m:
            return None, "", usage
        return m.group(1).upper(), " ".join(m.group(2).split())[:300], usage

    def _route(self, req, pol, outbox, ctx, info, name, token):
        """The Boss: picks which configured agent answers. No files, no tools but writing its choice, fixed list of outputs."""
        rid, gid = req["request_id"], req["guest_id"]
        sb, boss = pol["sandbox"], pol["boss"]
        empty = self.state_dir / "exports" / (rid + "-boss")
        empty.mkdir(mode=0o755)
        ctx.model = boss["model"]
        info["name"] = name + "-boss"
        try:
            spec = {"name": name + "-boss", "export_dir": str(empty), "outbox_dir": str(outbox), "boss": True, "backend": boss["backend"], "provider": pol["egress"]["provider"],
                    "login": pol["egress"].get("mode") == "login",
                    "placeholder_key": token, "model": boss["model"], "cpus": sb["cpus"], "memory_mb": sb["memory_mb"],
                    "prompt": sandbox.build_route_prompt(pol["agents"], boss["instructions"], req["text"], boss["backend"])}
            rr = self.runtime.run(spec, min(sb["timeout_s"], 120))
            choice = self._read_answer(outbox) if rr.exit_code == 0 and not rr.timed_out else None
            (outbox / "answer.md").unlink(missing_ok=True)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        aliases = {x["alias"]: x for x in pol["agents"]}
        word = (choice or "").strip().split()[0].strip("`*.,:;\"'").lower() if (choice or "").strip() else ""
        picked = aliases.get(word)
        self.audit.write("routed", rid, gid, picked["alias"] if picked else pol["agent"]["alias"],
                         {"fallback": picked is None, "tokens": ctx.tokens})
        return picked or pol["agent"]

    def _work(self, req, pol, exp, outbox, profile=None):
        rid, gid = req["request_id"], req["guest_id"]
        alias = profile["alias"] if profile else "auto"
        sb, lim = pol["sandbox"], pol["limits"]
        name = "door-run-" + rid.lower()
        left = max(0.0, lim["monthly_budget"] - self.audit.month_spend())
        ctx = Ctx(rid, gid, min(lim["max_turn_tokens"], lim["guest_daily_tokens"] - self.audit.guest_tokens_today(gid)),
                  lim["max_output_tokens"], left, (profile or pol["agent"])["model"])
        token = self.proxy.bind(ctx)
        with self._guard:
            info = self._running[rid]
        result = {"state": "failed", "reason": "sandbox_error", "request_id": rid}
        try:
            if profile is None:                      # "auto": the Boss chooses, then the chosen agent's export is built
                profile = self._route(req, pol, outbox, ctx, info, name, token)
                alias = profile["alias"]
                if info["cancel_reason"]:
                    result = {"state": "canceled", "reason": info["cancel_reason"]}
                    return
                if ctx.budget_hit:
                    result = {"state": "failed", "reason": "budget"}
                    return
                findings = exporter.build_export(profile["exports"], exp)
                self.audit.write("export_built", rid, gid, alias, {"ok": not findings, "findings": findings} if findings else {"ok": True})
                if findings:
                    result = {"state": "failed", "reason": "sandbox_error", "detail": "export_secrets"}
                    return
                self.audit.write("sandbox_started", rid, gid, alias)
                ctx.model = profile["model"]
            info["name"] = name
            spec = {"name": name, "export_dir": str(exp), "outbox_dir": str(outbox), "placeholder_key": token, "backend": profile["backend"], "provider": pol["egress"]["provider"],
                    "login": pol["egress"].get("mode") == "login",
                    "prompt": sandbox.build_prompt(profile["instructions"], req["text"], profile["backend"], profile.get("scope", ""), self._clean_history(req.get("history"))), "model": profile["model"],
                    "cpus": sb["cpus"], "memory_mb": sb["memory_mb"]}
            if info["cancel_reason"]:
                result = {"state": "canceled", "reason": info["cancel_reason"]}
                return
            rr = self.runtime.run(spec, sb["timeout_s"])
            self.audit.write("sandbox_exited", rid, gid, alias,
                             {"exit": rr.exit_code, "timeout": rr.timed_out, "tokens": ctx.tokens})
            if info["cancel_reason"]:
                result = {"state": "canceled", "reason": info["cancel_reason"]}
            elif ctx.budget_hit:
                result = {"state": "failed", "reason": "budget"}
            elif rr.timed_out:
                result = {"state": "failed", "reason": "timeout"}
            elif rr.exit_code != 0:
                result = {"state": "failed", "reason": "sandbox_error"}
            else:
                ans = self._read_answer(outbox)
                if ans is None:
                    result = {"state": "failed", "reason": "sandbox_error"}
                elif ans.strip().upper().startswith(sandbox.OUT_OF_SCOPE):
                    # The agent decided not to answer: the guest gets the owner's fixed refusal, never the agent's own words.
                    refusal = pol["guardrails"]["refusal"]
                    self.audit.write("reply_filtered", rid, gid, alias, {"text": ans, "refused": True, "redactions": 0, "kinds": [], "truncated": False})
                    self.audit.write("reply_sent", rid, gid, alias, {"chars": len(refusal), "refused": True})
                    result = {"state": "completed", "reply": {"text": refusal, "held": False, "redactions": 0, "held_text": None,
                                                              "owner_text": ans, "refused": True}}
                else:
                    vmode = pol["verification"]["mode"]
                    body, sources = answer_check.split_sources(ans)
                    vres = answer_check.verify(sources, exp) if vmode != "off" else {"checked": 0, "verified": 0, "files": [], "failed": []}
                    room = pol["outbound"]["max_reply_chars"] - (0 if vmode == "off" else 200)       # keep room for the "checked in" line
                    body = replytext.clip(replytext.plain(body), max(100, room))             # phone-friendly: no Markdown, cut at a sentence
                    f = outfilter.filter_reply(body, max(100, room), [socket.gethostname()])
                    text, vstatus = answer_check.compose(f["text"], vres, vmode, bool(sources))
                    held = f["redactions"] >= pol["outbound"]["hold_threshold"]
                    self.audit.write("reply_filtered", rid, gid, alias,
                                     {"text": ans, "redactions": f["redactions"], "kinds": f["kinds"], "truncated": f["truncated"],
                                      "verification": vstatus, "sources_checked": vres["checked"], "sources_verified": vres["verified"]})
                    self.audit.write("reply_held" if held else "reply_sent", rid, gid, alias, {"chars": len(text)})
                    result = {"state": "completed", "reply": {
                        "text": HELD_MSG if held else text, "held": held, "redactions": f["redactions"],
                        "held_text": text if held else None, "owner_text": ans,
                        "verification": dict(vres, status=vstatus)}}
        except Exception as e:
            result = {"state": "failed", "reason": "sandbox_error", "detail": type(e).__name__}
        finally:
            self.proxy.unbind(token)
            with self._guard:
                self._running.pop(rid, None)
            shutil.rmtree(exp, ignore_errors=True)
            shutil.rmtree(outbox, ignore_errors=True)
            result.update(request_id=rid, agent=alias, usage={"tokens": ctx.tokens, "cost": round(ctx.cost, 6), "samples": ctx.samples})
            self._save(rid, result)
            self._slot.release()

    @staticmethod
    def _read_answer(outbox: Path, limit=65536):
        """O outbox é gravável pelo sandbox: nunca seguir symlink nem ler algo que não seja arquivo regular."""
        p = outbox / "answer.md"
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            data = os.read(fd, limit)
        finally:
            os.close(fd)
        text = data.decode("utf-8", errors="replace").strip()
        return text or None

    def _on_usage(self, ctx, s):
        self.audit.write("usage", ctx.request_id, ctx.guest_id, getattr(ctx, "alias", "") or self.holder.policy["agent"]["alias"], s)

    # ---------- status / cancel ----------
    @staticmethod
    def _public(r):
        out = {"ok": True, "state": r.get("state"), "request_id": r.get("request_id")}
        for k in ("reason", "reply", "usage", "agent"):
            if k in r:
                out[k] = r[k]
        return out

    def status(self, rid):
        r = self._load(rid)
        if not r:
            return {"ok": False, "reason": "unknown_request"}
        out = self._public(r)
        runner = self._acts.get(rid)
        if runner and r.get("state") == "running":
            out["pending_actions"] = runner.pending_actions()          # things the task is waiting for the owner to allow
        return out

    def decide_action(self, rid, action_id, decision):
        runner = self._acts.get(rid)
        ok = bool(runner and decision in ("allow", "deny") and runner.decide(action_id, decision))
        if ok:
            self.audit.write("act_decision", rid, "", "", {"action": action_id, "decision": decision})
        return {"ok": ok, "reason": None if ok else "no_such_pending_action"}

    def cancel(self, rid, reason="owner_canceled"):
        if reason not in ("owner_canceled", "guest_canceled"):
            reason = "owner_canceled"
        with self._guard:
            info = self._running.get(rid)
        if not info:
            return self.status(rid)
        info["cancel_reason"] = reason
        self.audit.write("canceled", rid, "", "", {"reason": reason})
        runner = self._acts.get(rid)
        if runner:
            runner.cancel()
        else:
            self.runtime.kill(info["name"])
        return {"ok": True, "state": "canceled", "request_id": rid}

    def wait(self, rid, timeout=30):
        """Auxiliar para testes e CLI síncrona."""
        end = now() + timeout
        while now() < end:
            r = self._load(rid)
            if r and r.get("state") != "running":
                return self._public(r)
            threading.Event().wait(0.05)
        return self.status(rid)

    # ---------- socket ----------
    def dispatch(self, msg):
        op = msg.get("op")
        if op == "ask":
            return self.ask(msg.get("payload", ""), msg.get("sig", ""))
        if op == "status":
            return self.status(msg.get("request", ""))
        if op == "cancel":
            return self.cancel(msg.get("request", ""), msg.get("reason", "owner_canceled"))
        if op == "decide":
            return self.decide_action(msg.get("request", ""), msg.get("action", ""), msg.get("decision", ""))
        if op == "pair_confirm":
            return self.pair_confirm(msg.get("code", ""), msg.get("public_key", ""))
        if op == "pair_start":
            return self.pair_start()
        if op == "summary":
            return self.summary()
        if op in ("pause", "resume"):
            return self.set_paused(op == "pause")
        return {"ok": False, "reason": "unknown_op"}

    def serve(self, sock_path=None):
        path = Path(sock_path or self.state_dir / "door.sock")
        path.unlink(missing_ok=True)
        host = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    msg = json.loads(self.rfile.readline(1 << 20))
                    out = host.dispatch(msg)
                except Exception as e:
                    out = {"ok": False, "reason": "internal", "detail": type(e).__name__}
                self.wfile.write((json.dumps(out, ensure_ascii=False) + "\n").encode())

        class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        old = os.umask(0o177)
        try:
            srv = S(str(path), H)
        finally:
            os.umask(old)
        os.chmod(path, 0o600)
        return srv
