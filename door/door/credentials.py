"""Where the model API key comes from. It lives only in the host process; the container never sees it."""
import json
import os
from pathlib import Path

OPENCODE_AUTH = "~/.local/share/opencode/auth.json"


def load_credential(egress: dict) -> str:
    """source "env" (default): the environment variable named by credential_env.
    source "opencode-auth": reuse the key OpenCode already stores on this computer for this provider (explicit opt-in)."""
    if egress.get("credential_source", "env") == "opencode-auth":
        try:
            entry = json.loads(Path(os.path.expanduser(OPENCODE_AUTH)).read_text())[egress["provider"]]
        except (OSError, ValueError, KeyError):
            return ""
        return entry.get("key", "") if entry.get("type") == "api" else ""   # OAuth logins are not API keys and are not reused
    return os.environ.get(egress["credential_env"], "")
