"""Log append-only em JSONL (Seção 12.1) e contadores derivados dele."""
import json
import os
import threading
from pathlib import Path

from .common import day_key, iso, month_key, now

EVENTS = {"request_received", "recheck", "export_built", "sandbox_started", "usage", "sandbox_exited",
          "reply_filtered", "reply_sent", "reply_held", "canceled", "paused", "policy_reloaded", "routed", "act_started", "act_permission", "act_waiting", "act_decision", "act_finished", "settings_changed", "work_merged"}


class Audit:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event, request_id="", guest_id="", agent_alias="", detail=None):
        assert event in EVENTS, event
        line = json.dumps({"at": iso(), "ts": now(), "event": event, "request_id": request_id, "guest_id": guest_id,
                           "agent_alias": agent_alias, "detail": detail or {}}, ensure_ascii=False)
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (line + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)

    def rows(self):
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for ln in f:
                try:
                    yield json.loads(ln)
                except ValueError:
                    continue

    def accepted(self, request_id) -> bool:
        return any(r["event"] == "recheck" and r["request_id"] == request_id and r["detail"].get("ok") for r in self.rows())

    def guest_requests_today(self, guest_id) -> int:
        d = day_key()
        return sum(1 for r in self.rows() if r["event"] == "recheck" and r["guest_id"] == guest_id
                   and r["detail"].get("ok") and r["at"][:10] == d)

    def guest_tokens_today(self, guest_id) -> int:
        d = day_key()
        return sum(r["detail"].get("input_tokens", 0) + r["detail"].get("output_tokens", 0) for r in self.rows()
                   if r["event"] == "usage" and r["guest_id"] == guest_id and r["at"][:10] == d)

    def month_spend(self) -> float:
        m = month_key()
        return sum(r["detail"].get("cost", 0.0) for r in self.rows() if r["event"] == "usage" and r["at"][:7] == m)
