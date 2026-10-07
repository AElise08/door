"""Checking an answer against the files it claims to come from.

The agent must end its answer with a SOURCES block of exact quotes. The host opens each cited file in the (read-only) export and checks
that the quote really is there. Quotes that are not found are reported, never trusted. This catches invented facts and wrong file names;
it cannot prove that the answer is a correct reading of the quote, which is why the owner can always see the sources.
"""
import os
import re
from pathlib import Path

MAX_SOURCES = 6
MAX_FILE_BYTES = 1_000_000
MAX_QUOTE = 240
MIN_QUOTE = 6
SOURCES_RE = re.compile(r"(?im)^\s*\**sources\**\s*:?\s*\**\s*$")
LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])?\s*`?([^|`]+?)`?\s*\|\s*(.+?)\s*$")


def _norm(s: str) -> str:
    """Whitespace and the usual markdown/quote decorations do not count as differences."""
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def split_sources(text: str):
    """(answer_without_sources, [(path, quote)]) using the LAST SOURCES: heading."""
    matches = list(SOURCES_RE.finditer(text or ""))
    if not matches:
        return (text or "").strip(), []
    m = matches[-1]
    body, block = text[:m.start()].rstrip(), text[m.end():]
    found = []
    for line in block.splitlines():
        lm = LINE_RE.match(line)
        if lm:
            quote = lm.group(2).strip().strip('"').strip("'").strip("`").strip()
            found.append((lm.group(1).strip(), quote))
    return body, found[:MAX_SOURCES]


def _resolve(export_root: Path, rel: str):
    """A cited path must be a regular file inside the export. Anything else (absolute, .., symlink) counts as not found."""
    rel = rel.strip().strip("`")
    if not rel or rel.startswith(("/", "~")) or "\\" in rel or "\0" in rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    root = export_root.resolve()
    candidates = [parts] + ([parts[1:]] if len(parts) > 1 else [])                 # the export folder name may be part of the path
    for cand in candidates:
        for base in [root] + [d for d in sorted(root.iterdir()) if d.is_dir() and not d.is_symlink()]:
            p = base.joinpath(*cand)
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                p = p.resolve()
                if root in p.parents and p.stat().st_size <= MAX_FILE_BYTES:
                    return p
            except OSError:
                continue
    return None


def verify(sources, export_root: Path):
    """-> {"checked": n, "verified": m, "files": [...verified paths...], "failed": [{"path", "why"}]}"""
    out = {"checked": 0, "verified": 0, "files": [], "failed": []}
    for path, quote in sources:
        out["checked"] += 1
        q = _norm(quote)
        if len(q) < MIN_QUOTE or len(q) > MAX_QUOTE:
            out["failed"].append({"path": path[:120], "why": "quote too short or too long"}); continue
        f = _resolve(Path(export_root), path)
        if f is None:
            out["failed"].append({"path": path[:120], "why": "file not found in the project"}); continue
        try:
            text = _norm(f.read_text(errors="replace"))
        except OSError:
            out["failed"].append({"path": path[:120], "why": "file unreadable"}); continue
        if q in text:
            out["verified"] += 1
            rel = str(f.relative_to(Path(export_root).resolve()))
            out["files"].append("/".join(rel.split("/")[1:]) if "/" in rel else rel)      # drop the export folder name
        else:
            out["failed"].append({"path": path[:120], "why": "quote not found in that file"})
    out["files"] = sorted(set(out["files"]))
    return out


def looks_like_a_question(body: str) -> bool:
    return len(body) < 300 and body.rstrip().endswith("?")


def compose(body: str, result: dict, mode: str, had_sources: bool):
    """-> (text for the guest, short status for the owner). `mode`: off | flag | require."""
    if mode == "off":
        return body, "off"
    ok, bad = result["verified"], len(result["failed"])
    if ok and not bad:
        return "%s\n\nChecked in: %s" % (body, ", ".join(result["files"][:4])), "verified"
    if ok:
        return "%s\n\nChecked in: %s. Part of this I could not confirm in the files." % (body, ", ".join(result["files"][:4])), "partly"
    if looks_like_a_question(body):
        return body, "n/a"                                                          # a clarifying question has nothing to cite
    if mode == "require":
        return "I could not verify an answer from the project files. Please ask the owner.", "unverified"
    return "%s\n\nI could not confirm this in the project files." % body, "unverified"
