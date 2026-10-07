"""Loads and validates door.json (spec section 5), including several agent profiles and the Boss."""
import json
import os
import math
import re
from pathlib import Path

from .common import ALIAS

DEFAULTS = {
    "sandbox": {"kind": "container", "image": "door-runner:0.3", "cpus": 2, "memory_mb": 2048, "timeout_s": 600, "runtime": "docker"},
    "egress": {"allow_hosts": ["api.anthropic.com"], "credential_env": "DOOR_ANTHROPIC_API_KEY", "upstream_scheme": "https",
               "pricing": {"input_per_mtok": 3.0, "output_per_mtok": 15.0, "cache_read_per_mtok": .3,
                           "cache_write_per_mtok": 6.0}},
    "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10,
               "guest_daily_tokens": 400000, "monthly_budget": 50.0, "currency": "USD"},
    "outbound": {"max_reply_chars": 1500, "hold_threshold": 1},
}


class PolicyError(Exception):
    pass


# Where the model API lives. The proxy only ever talks to the one host chosen here.
# style: which wire format the sandboxed agent speaks (claude -> anthropic; opencode and codex -> openai).
PROVIDERS = {
    "anthropic":   {"style": "anthropic", "host": "api.anthropic.com", "path_prefix": "",          "credential_env": "DOOR_ANTHROPIC_API_KEY"},
    "opencode-go": {"style": "openai",    "host": "opencode.ai",       "path_prefix": "/zen/go",   "credential_env": "OPENCODE_API_KEY"},
    "openai":      {"style": "openai",    "host": "api.openai.com",    "path_prefix": "",          "credential_env": "OPENAI_API_KEY"},
    "openrouter":  {"style": "openai",    "host": "openrouter.ai",     "path_prefix": "/api",      "credential_env": "OPENROUTER_API_KEY"},
    "deepseek":    {"style": "openai",    "host": "api.deepseek.com",  "path_prefix": "",          "credential_env": "DEEPSEEK_API_KEY"},
}
BACKENDS = {"claude": "anthropic", "opencode": "openai", "codex": "openai"}
# Login mode: each engine talks to its own provider with its own login, through a tunnel limited to these hosts.
LOGIN_HOSTS = {
    "claude":   ["api.anthropic.com", "console.anthropic.com", "platform.claude.com", "claude.ai"],
    "codex":    ["chatgpt.com", "auth.openai.com", "api.openai.com"],
    "opencode": ["opencode.ai", "api.openai.com", "chatgpt.com", "auth.openai.com", "api.anthropic.com"],
}
HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def default_path() -> Path:
    return Path(os.environ.get("DOOR_POLICY") or "~/.config/door/door.json").expanduser()


def default_state_dir() -> Path:
    return Path(os.environ.get("DOOR_STATE") or "~/.local/state/door").expanduser()


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


RESERVED_ALIASES = {"auto", "boss"}
MAX_AGENTS = 8


ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")


def _act(raw, policy_path: Path, state_dir: Path):
    """The optional "act" block of an agent: lets trusted guests have tasks done in a throwaway copy of one project."""
    if raw is None or raw is False:
        return None
    if not isinstance(raw, dict):
        raise PolicyError("agent.act must be an object")
    if not raw.get("enabled", True):
        return None
    project = raw.get("project")
    if not isinstance(project, str) or not project:
        raise PolicyError("agent.act.project is required")
    proj = Path(project).expanduser()
    if not (proj / ".git").exists():
        raise PolicyError("agent.act.project must be a git repository")
    for protected in (policy_path, policy_path.parent, state_dir):
        if _inside(protected, proj):
            raise PolicyError("policy/state must not be inside agent.act.project")
    from .act import SHELL_META
    cmds = raw.get("allow_commands", [])
    if not isinstance(cmds, list) or len(cmds) > 20 or any(not isinstance(c, str) or not 1 <= len(c) <= 100 or SHELL_META.search(c) for c in cmds):
        raise PolicyError("agent.act.allow_commands must be up to 20 plain commands (no ; | & < > $ ` or newlines)")
    proof = raw.get("proof", {})
    if not isinstance(proof, dict):
        raise PolicyError("agent.act.proof must be an object")
    pcmds = proof.get("commands", [])
    if not isinstance(pcmds, list) or len(pcmds) > 10 or any(not isinstance(c, str) or not 1 <= len(c) <= 200 for c in pcmds):
        raise PolicyError("agent.act.proof.commands must be up to 10 commands")
    env = raw.get("env", {})
    if not isinstance(env, dict) or len(env) > 20 or any(not ENV_NAME.match(str(k)) or re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", str(k)) or
                                                            not isinstance(v, str) or len(v) > 200 for k, v in env.items()):
        raise PolicyError("agent.act.env must be plain settings (names with KEY/TOKEN/SECRET/PASSWORD are not allowed)")
    def num(key, default, lo, hi, src=raw):
        v = src.get(key, default)
        if type(v) is not int or not lo <= v <= hi:
            raise PolicyError("agent.act.%s must be a whole number from %d to %d" % (key, lo, hi))
        return v
    bash = raw.get("bash", "ask")
    if bash not in ("ask", "off"):
        raise PolicyError("agent.act.bash must be ask or off")
    open_on_mac = raw.get("open_on_mac", "ask")
    if open_on_mac not in ("off", "ask", "allow"):
        raise PolicyError("agent.act.open_on_mac must be off, ask or allow")
    owner_steps = raw.get("owner_steps", "auto")
    if owner_steps not in ("auto", "ask"):
        raise PolicyError("agent.act.owner_steps must be auto or ask")
    return {"project": str(proj), "model": str(raw.get("model", "sonnet")), "allow_commands": list(cmds), "bash": bash, "env": dict(env),
            "open_on_mac": open_on_mac, "owner_steps": owner_steps,
            "timeout_s": num("timeout_s", 900, 30, 3600), "max_turns": num("max_turns", 30, 1, 100),
            "approval_timeout_s": num("approval_timeout_s", 600, 10, 3600), "claude_bin": str(raw.get("claude_bin", "claude")),
            "proof": {"commands": list(pcmds), "timeout_s": num("timeout_s", 300, 10, 1800, proof)}}


def _profile(agent, policy_path: Path, state_dir: Path) -> dict:
    if not isinstance(agent, dict):
        raise PolicyError("agent must be an object")
    if not ALIAS.match(str(agent.get("alias", ""))) or agent["alias"] in RESERVED_ALIASES:
        raise PolicyError("invalid agent.alias")
    if agent.get("max_capability", "ask") != "ask":
        raise PolicyError("v0 only implements max_capability=ask")
    if agent.get("backend", "claude") not in BACKENDS:
        raise PolicyError("backend must be one of: " + ", ".join(sorted(BACKENDS)))
    exports = agent.get("exports")
    if not exports or not isinstance(exports, list):
        raise PolicyError("agent.exports must be a non-empty list")
    names = set()
    for e in exports:
        if not isinstance(e, dict) or not isinstance(e.get("name"), str) or not isinstance(e.get("repo"), str):
            raise PolicyError("each export needs a name and a repo")
        if e["name"] in names or not ALIAS.fullmatch(e["name"]):
            raise PolicyError("invalid or duplicate export name: %s" % e["name"])
        names.add(e["name"])
        if not isinstance(e.get("ref", "HEAD"), str) or e.get("ref", "HEAD").startswith("-"):
            raise PolicyError("invalid ref")
        for key in ("exclude", "accepted_findings"):
            if not isinstance(e.get(key, []), list) or any(not isinstance(s, str) for s in e.get(key, [])):
                raise PolicyError(key + " must be a list of strings")
        repo = Path(e["repo"]).expanduser()
        for protected in (policy_path, policy_path.parent, state_dir):
            if _inside(protected, repo):
                raise PolicyError("policy/state must not be inside exports (%s)" % repo)
    model = agent.get("model", "claude-sonnet-5-5")
    if not isinstance(model, str) or not model:
        raise PolicyError("model is required")
    act = _act(agent.get("act"), policy_path, state_dir)
    scope = agent.get("scope", "")
    if not isinstance(scope, str) or len(scope) > 600:
        raise PolicyError("agent.scope must be text of at most 600 characters")
    return dict(agent, max_capability="ask", backend=agent.get("backend", "claude"), model=model, scope=scope, act=act,
                description=str(agent.get("description", ""))[:300], instructions=agent.get("instructions", ""))


def validate(raw: dict, policy_path: Path, state_dir: Path) -> dict:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise PolicyError("version must be 1")
    if "agents" in raw and "agent" in raw:
        raise PolicyError("use either agent or agents, not both")
    items = raw.get("agents") if "agents" in raw else [raw.get("agent")]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_AGENTS:
        raise PolicyError("agents must be a list of 1 to %d profiles" % MAX_AGENTS)
    agents = [_profile(x, policy_path, state_dir) for x in items]
    if len({x["alias"] for x in agents}) != len(agents):
        raise PolicyError("duplicate agent alias")
    boss_raw = raw.get("boss", {})
    if not isinstance(boss_raw, dict):
        raise PolicyError("boss must be an object")
    boss = {"enabled": bool(boss_raw.get("enabled", len(agents) > 1)), "model": boss_raw.get("model", agents[0]["model"]),
            "backend": boss_raw.get("backend", agents[0]["backend"]), "instructions": boss_raw.get("instructions", "")}
    if boss["backend"] not in BACKENDS:
        raise PolicyError("boss.backend must be one of: " + ", ".join(sorted(BACKENDS)))
    if not isinstance(boss["model"], str) or not boss["model"] or not isinstance(boss["instructions"], str):
        raise PolicyError("invalid boss settings")
    if boss["enabled"] and len(agents) < 2:
        raise PolicyError("the Boss needs at least two agents to coordinate")
    g = raw.get("guardrails", {})
    if not isinstance(g, dict):
        raise PolicyError("guardrails must be an object")
    pats = g.get("blocked_patterns", [])
    if not isinstance(pats, list) or len(pats) > 50 or any(not isinstance(x, str) or not 1 <= len(x) <= 200 for x in pats):
        raise PolicyError("guardrails.blocked_patterns must be up to 50 patterns of 1-200 characters")
    for x in pats:
        try:
            re.compile(x)
        except re.error:
            raise PolicyError("guardrails.blocked_patterns has an invalid regular expression: " + x[:40])
    refusal = g.get("refusal", "I can only help with questions about this project.")
    if not isinstance(refusal, str) or not 1 <= len(refusal) <= 300:
        raise PolicyError("guardrails.refusal must be text of 1-300 characters")
    lu = raw.get("local_ui", {})
    if not isinstance(lu, dict) or type(lu.get("port", 9631)) is not int or not 1024 <= lu.get("port", 9631) <= 65535:
        raise PolicyError("local_ui.port must be a whole number from 1024 to 65535")
    local_ui = {"enabled": bool(lu.get("enabled", True)), "port": lu.get("port", 9631)}
    ver = raw.get("verification", {})
    if not isinstance(ver, dict) or ver.get("mode", "flag") not in ("off", "flag", "require"):
        raise PolicyError("verification.mode must be off, flag or require")
    verification = {"mode": ver.get("mode", "flag")}
    guardrails = {"blocked_patterns": pats, "block_prompt_injection": bool(g.get("block_prompt_injection", True)), "refusal": refusal}
    pol = _merge(DEFAULTS, {k: v for k, v in raw.items() if k in DEFAULTS})
    pol["guardrails"] = guardrails
    pol["verification"] = verification
    pol["local_ui"] = local_ui
    pol["version"] = 1
    pol["agents"] = agents
    pol["agent"] = agents[0]          # default agent (and the only one in single-agent setups)
    pol["boss"] = boss
    if pol["sandbox"]["kind"] != "container":
        raise PolicyError("this implementation only supports the container sandbox")
    if pol["sandbox"]["runtime"] not in ("docker", "podman"):
        raise PolicyError("runtime deve ser docker ou podman")
    eg, raw_eg = pol["egress"], (raw.get("egress") or {})
    mode = eg.get("mode", "api")
    if mode not in ("api", "login"):
        raise PolicyError("egress.mode must be api or login")
    if mode == "login":
        # Sign-in with the owner's own account (subscription). No API key and no per-token metering: the run is bounded by its
        # time limit, the engine's turn cap and the per-guest request limits, and the sign-in lives in a Door-only volume.
        hosts = sorted({h for ag in pol["agents"] + [pol["boss"]] for h in LOGIN_HOSTS[ag["backend"]]})
        eg.update(provider="login", style="login", allow_hosts=hosts, path_prefix="", upstream_scheme="https", credential_env="DOOR_UNUSED")
    else:
        provider = eg.get("provider", "anthropic")
        if provider == "custom":
            from urllib.parse import urlparse
            u = urlparse(str(eg.get("base_url", "")))
            host = (u.hostname or "").lower()
            if u.scheme != "https" or not HOST_RE.match(host) or u.port not in (None, 443) or u.username or u.query:
                raise PolicyError("custom provider needs an https base_url with a public host name")
            preset = {"style": eg.get("style", "openai"), "host": host, "path_prefix": u.path.rstrip("/"),
                      "credential_env": eg.get("credential_env", "DOOR_API_KEY")}
            if preset["style"] not in ("openai", "anthropic"):
                raise PolicyError("style must be openai or anthropic")
        elif provider in PROVIDERS:
            preset = PROVIDERS[provider]
        else:
            raise PolicyError("unknown provider; use one of: " + ", ".join(sorted(PROVIDERS)) + ", custom")
        if provider != "anthropic" and not isinstance(raw_eg.get("pricing"), dict):
            raise PolicyError("egress.pricing (input_per_mtok, output_per_mtok) is required for this provider: cost cannot be guessed")
        if raw_eg.get("credential_env") is None:
            eg["credential_env"] = preset["credential_env"]
        if raw_eg.get("allow_hosts") not in (None, [preset["host"]]) or eg.get("upstream_scheme", "https") != "https":
            raise PolicyError("allow_hosts is set by the provider and the connection must be HTTPS")
        eg.update(provider=provider, style=preset["style"], allow_hosts=[preset["host"]], path_prefix=preset["path_prefix"], upstream_scheme="https")
        if eg.get("credential_source", "env") not in ("env", "opencode-auth"):
            raise PolicyError("credential_source must be env or opencode-auth")
        for ag in pol["agents"] + [pol["boss"]]:
            need = BACKENDS[ag["backend"]] if ag.get("backend") else None
            if need and need != preset["style"]:
                raise PolicyError("backend %s needs a provider with the %s format, but %s speaks %s" % (ag["backend"], need, provider, preset["style"]))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", pol["egress"]["credential_env"]):
            raise PolicyError("invalid credential_env")

    for group, keys in {"sandbox": ("cpus", "memory_mb", "timeout_s"),
                        "limits": tuple(DEFAULTS["limits"].keys() - {"currency"}),
                        "outbound": ("max_reply_chars", "hold_threshold")}.items():
        for key in keys:
            value = pol[group][key]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise PolicyError(group + "." + key + " deve ser positivo e finito")
    if pol["outbound"]["max_reply_chars"] < 100 or pol["outbound"]["max_reply_chars"] > 1500:
        raise PolicyError("max_reply_chars deve estar entre 100 e 1500")
    for rate in pol["egress"]["pricing"].values():
        if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
            raise PolicyError("tarifas devem ser positivas e finitas")
    if pol["limits"]["currency"] != "USD":
        raise PolicyError("a v0 calcula custo em USD")
    return pol


def load(path: Path, state_dir: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise PolicyError("could not read %s: %s" % (path, e))
    return validate(raw, Path(path), Path(state_dir))


def cloud_summary(pol: dict) -> dict:
    """Seção 5.4: só isto sai do Mac. Nunca exports, caminhos, sandbox ou proxy."""
    a = pol["agent"]
    return {"alias": a["alias"], "description": a["description"], "max_capability": a["max_capability"], "limits": pol["limits"],
            "agents": [{"alias": x["alias"], "description": x["description"]} for x in pol["agents"]], "boss": pol["boss"]["enabled"],
            "act_agent": next((x["alias"] for x in pol["agents"] if x.get("act")), None),
            "guardrails": pol["guardrails"],
            # names only (never paths): what the owner sees in the panel; they change it on the Mac
            "projects": [e["name"] for e in a.get("exports", [])], "engine": "%s · %s" % (a["backend"], a["model"])}


class PolicyHolder:
    """Recarrega ao mudar; arquivo inválido mantém a última política válida (5.2)."""

    def __init__(self, path: Path, state_dir: Path, on_event=None):
        self.path, self.state_dir, self.on_event = Path(path), Path(state_dir), on_event or (lambda *a: None)
        self._mtime = None
        self.policy = None
        self.error = None
        self.refresh()

    def refresh(self):
        try:
            m = self.path.stat().st_mtime_ns
        except OSError as e:
            self.error = str(e)
            return self.policy
        if m == self._mtime:
            return self.policy
        self._mtime = m
        try:
            self.policy = load(self.path, self.state_dir)
            self.error = None
            self.on_event("policy_reloaded", {"ok": True})
        except (PolicyError, TypeError, KeyError, AttributeError) as e:
            self.error = str(e)
            self.on_event("policy_reloaded", {"ok": False, "error": str(e)})
        return self.policy
