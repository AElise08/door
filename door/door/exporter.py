"""Exportação limpa (Seção 9.2): git archive, exclusões e varredura de segredos."""
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

BUILTIN_EXCLUDES = [".env*", "**/.env*", "*.pem", "**/*.pem", "*.key", "**/*.key", "*.p12", "**/*.p12", "id_*", "**/id_*",
                    ".npmrc", "**/.npmrc", ".pypirc", "**/.pypirc", ".netrc", "**/.netrc", "**/credentials*", "credentials*",
                    ".git", "**/.git", ".git/**", "**/.git/**",
                    # Agent configuration inside a repo could add hooks, MCP servers or permissions to the agent that reads it.
                    ".claude", "**/.claude", ".mcp.json", "**/.mcp.json", ".codex", "**/.codex", ".opencode", "**/.opencode",
                    "opencode.json", "**/opencode.json", "opencode.jsonc", "**/opencode.jsonc", ".cursor", "**/.cursor", ".cursorrules"]

SECRET_RULES = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    "generic_assignment": re.compile(r"""(?i)\b(?:api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*['"][A-Za-z0-9/+_\-]{20,}['"]"""),
}


class ExportError(Exception):
    pass


def glob_to_re(pat: str):
    i, out = 0, ""
    while i < len(pat):
        c = pat[i]
        if pat[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pat[i:i + 2] == "**":
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile("^" + out + "$")


def _matches(rel: str, regs) -> bool:
    parts = rel.split("/")
    # casa o caminho inteiro e também cada prefixo de diretório (excluir um dir exclui o conteúdo)
    return any(r.match("/".join(parts[:i])) for r in regs for i in range(1, len(parts) + 1))


def scan_secrets(root: Path, accepted=()):
    acc = set(accepted or [])
    found = []
    for dp, _, files in os.walk(root):
        for f in files:
            p = Path(dp) / f
            rel = str(p.relative_to(root))
            try:
                if p.stat().st_size > 2_000_000:
                    found.append("%s:too_large_to_scan" % rel)
                    continue
                data = p.read_text(errors="ignore")
            except OSError:
                continue
            for name, rx in SECRET_RULES.items():
                if rx.search(data) and ("%s:%s" % (rel, name)) not in acc:
                    found.append("%s:%s" % (rel, name))
    return found


def _archive(repo: Path, ref: str, dest: Path):
    if not (repo / ".git").exists() and not (repo / "HEAD").exists():
        raise ExportError("not a git repository: %s" % repo)
    ar = subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    total = 0
    try:
        with tarfile.open(fileobj=ar.stdout, mode="r|") as archive:
            for member in archive:
                parts = Path(member.name).parts
                if member.name.startswith("/") or any(p in ("..", ".git") for p in parts):
                    raise ExportError("caminho inseguro no archive")
                p = dest.joinpath(*parts)
                if member.isdir():
                    p.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    total += member.size
                    if total > 128 * 1024 * 1024:
                        raise ExportError("export exceeds 128 MiB")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as src, p.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
                # symlinks, hardlinks, devices e sockets não entram na cópia.
        ar.stdout.close()
        err = ar.stderr.read().decode(errors="ignore")
        if ar.wait() != 0:
            raise ExportError("git archive failed: " + err.strip())
    except Exception:
        ar.kill()
        ar.wait()
        raise
    finally:
        ar.stdout.close()
        ar.stderr.close()


def build_export(exports, base_dir: Path):
    """Cria base_dir/<nome> para cada export. Retorna lista de achados de segredo (já filtrados pelo aceite)."""
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    findings = []
    try:
        for e in exports:
            dest = base_dir / e["name"]
            dest.mkdir()
            _archive(Path(e["repo"]).expanduser(), e.get("ref", "HEAD"), dest)
            regs = [glob_to_re(p) for p in BUILTIN_EXCLUDES + list(e.get("exclude", []))]
            for dp, dns, fns in os.walk(dest, topdown=True):
                for n in list(dns) + list(fns):
                    p = Path(dp) / n
                    rel = str(p.relative_to(dest))
                    if p.is_symlink() or _matches(rel, regs):
                        if p.is_dir() and not p.is_symlink():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)
                dns[:] = [d for d in dns if (Path(dp) / d).exists()]
            for f in scan_secrets(dest, e.get("accepted_findings")):
                findings.append("%s/%s" % (e["name"], f))
            for dp, _, fns in os.walk(dest):
                os.chmod(dp, 0o755)
                for f in fns:
                    os.chmod(Path(dp) / f, 0o644)
    except Exception:
        shutil.rmtree(base_dir, ignore_errors=True)
        raise
    return findings
