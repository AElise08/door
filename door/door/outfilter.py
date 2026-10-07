"""Filtro de saída (Seção 10). É alarme, não fronteira."""
import math
import re
import socket
from collections import Counter

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
KEY_PREFIX = re.compile(r"\b(?:sk-ant-|sk-|AKIA|ghp_|gho_|ghs_|github_pat_|xox[abpr]-|AIza|glpat-)[A-Za-z0-9_\-]{8,}")
JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
PRIVKEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
ABSPATH = re.compile(r"(?<![\w:/.])(?:/[A-Za-z0-9_.-]+(?:/[^\s'\"`)]+)*|~/[^\s'\"`)]+|[A-Za-z]:\\[^\s'\"`)]+)")
TOKEN = re.compile(r"[A-Za-z0-9+/_\-=]{32,}")
FULL_NOTICE = "\n[reply truncated; the full version is with the owner]"


def _entropy(s: str) -> float:
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def filter_reply(text: str, max_chars: int = 1500, hostnames=None):
    hosts = set(h for h in (hostnames or [socket.gethostname()]) if h and len(h) >= 3)
    text = CTRL.sub("", ANSI.sub("", text or ""))
    # The project is mounted at /work inside the container: that is not a path on the owner's computer, so it is not a leak.
    text = re.sub(r"(?<![\w/.~-])/work/", "", text)
    text = re.sub(r"(?<![\w/.~-])/work\b", "the project", text)
    hits = []
    for name, rx in (("api_key", KEY_PREFIX), ("jwt", JWT), ("private_key", PRIVKEY), ("abs_path", ABSPATH)):
        for _ in rx.finditer(text):
            hits.append(name)
        text = rx.sub("[removed]", text)

    def tok(m):
        s = m.group(0)
        if len(set(s)) > 10 and _entropy(s) > 4.0:
            hits.append("high_entropy")
            return "[removed]"
        return s

    text = TOKEN.sub(tok, text)
    for h in hosts:
        if re.search(re.escape(h), text, re.I):
            hits.append("hostname")
            text = re.sub(re.escape(h), "[removed]", text, flags=re.I)
    truncated = len(text) > max_chars
    if truncated:
        text = text[: max(0, max_chars - len(FULL_NOTICE))].rstrip() + FULL_NOTICE
    return {"text": text, "redactions": len(hits), "kinds": sorted(set(hits)), "truncated": truncated}
