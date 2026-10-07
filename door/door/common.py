"""Utilidades compartilhadas: ULID, hashes, HMAC, tempo, E.164."""
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
ALIAS = re.compile(r"^[a-z0-9-]{1,32}$")
ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def ulid() -> str:
    t = int(time.time() * 1000)
    ts = ""
    for _ in range(10):
        ts = _B32[t & 31] + ts
        t >>= 5
    rnd = int.from_bytes(os.urandom(10), "big")
    r = ""
    for _ in range(16):
        r = _B32[rnd & 31] + r
        rnd >>= 5
    return ts + r


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sign(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify(secret: str, payload: bytes, sig: str) -> bool:
    return hmac.compare_digest(sign(secret, payload), sig or "")


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_key(ts: float | None = None) -> str:
    return iso(ts)[:10]


def month_key(ts: float | None = None) -> str:
    return iso(ts)[:7]


def is_e164(s: str) -> bool:
    return bool(E164.match(s or ""))


EMAIL_HANDLE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$")


def is_handle(s: str) -> bool:
    """Who sent a message: a phone number, or (iMessage) the email address of an Apple ID. Emails are compared in lower case."""
    return is_e164(s) or bool(EMAIL_HANDLE.match(s or ""))


def norm_handle(s):
    return s.strip().lower() if isinstance(s, str) and "@" in s else s


def norm_text(s: str) -> str:
    return " ".join((s or "").strip().upper().split())
