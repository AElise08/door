import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from mypeople import firstrun


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "mypeople" / "runtime" / "bin"
HANDLER = ROOT / "mypeople" / "runtime" / "plugins" / "tmux-boss-hooks" / "hook-handler.py"


def load_mp(home):
    config = Path(home) / "queue.env"
    config.write_text(
        'export INSTALL_DIR="%s"\n'
        'export HOST_ID="test-node"\n'
        'export QUEUE_URL="http://127.0.0.1:9900"\n'
        'export QUEUE_SECRET="secret"\n'
        'export TTYD_PORT="7681"\n'
        'export DEFAULT_BACKEND="claude"\n'
        'export DEFAULT_ENG_MODEL="claude-opus-4-8"\n'
        'export DEFAULT_CLAUDE_MODEL="claude-opus-4-8"\n'
        'export DEFAULT_CODEX_MODEL=""\n' % (Path(home) / "state"),
        encoding="utf-8",
    )
    with mock.patch.dict(os.environ, {
        "HOME": str(home),
        "MYPEOPLE_CONFIG_PATH": str(config),
        "MYPEOPLE_HOME": str(Path(home) / "state"),
    }, clear=False):
        sys.modules.pop("mpcommon", None)
        sys.path.insert(0, str(BIN))
        try:
            name = "mypeople_test_mp_%s" % id(home)
            loader = importlib.machinery.SourceFileLoader(name, str(BIN / "mp"))
            spec = importlib.util.spec_from_loader(name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(BIN))


class HookConfigTests(unittest.TestCase):
    def test_config_upgrade_preserves_secret_and_explicit_models(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "queue.env"
            path.write_text(
                'export QUEUE_SECRET="keep-me"\n'
                'export DEFAULT_BACKEND="claude"\n'
                'export DEFAULT_CLAUDE_MODEL="claude-custom"\n'
                'export DEFAULT_CODEX_MODEL="codex-custom"\n',
                encoding="utf-8",
            )
            with mock.patch.object(firstrun, "CONFIG_PATH", str(path)), \
                 mock.patch.object(firstrun, "CONFIG_DIR", td), \
                 mock.patch.dict(os.environ, {}, clear=True):
                firstrun.write_queue_env(str(Path(td) / "state"), "codex")
            values = {}
            for line in path.read_text().splitlines():
                key, value = line.removeprefix("export ").split("=", 1)
                values[key] = value.strip('"')
            self.assertEqual("keep-me", values["QUEUE_SECRET"])
            self.assertEqual("codex", values["DEFAULT_BACKEND"])
            self.assertEqual("claude-custom", values["DEFAULT_CLAUDE_MODEL"])
            self.assertEqual("codex-custom", values["DEFAULT_CODEX_MODEL"])

    def test_retired_hooks_are_removed_and_unrelated_hooks_survive(self):
        old = "/old/plugins/tmux-boss-hooks/emit-event.sh"
        hooks = {
            "PreToolUse": [{"matcher": "AskUserQuestion", "hooks": [
                {"type": "command", "command": old + " PreToolUse"}
            ]}],
            "SessionEnd": [{"hooks": [
                {"type": "command", "command": old + " SessionEnd"}
            ]}],
            "Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/custom-stop"}]}],
        }
        current = "/new/plugins/tmux-boss-hooks/emit-event.sh"
        result = firstrun._replace_mypeople_hooks(hooks, current)

        self.assertNotIn("PreToolUse", result)
        self.assertNotIn("SessionEnd", result)
        self.assertEqual(2, len(result["Stop"]))
        self.assertEqual(
            {"SessionStart", "UserPromptSubmit", "Stop"},
            {event for event, groups in result.items()
             if any(firstrun._mypeople_hook_group(group) for group in groups)},
        )

    def test_claude_and_codex_receive_the_same_three_hooks(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            (home / ".claude").mkdir()
            stale = "/old/plugins/tmux-boss-hooks/emit-event.sh"
            (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
                "SessionEnd": [{"hooks": [{"type": "command", "command": stale + " SessionEnd"}]}]
            }}))
            (home / ".codex").mkdir()
            (home / ".codex" / "hooks.json").write_text(json.dumps({"hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": stale + " PreToolUse"}]}]
            }}))

            firstrun.write_claude_config("/tmp/mypeople")
            firstrun.write_codex_config("/tmp/mypeople")

            claude = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
            codex = json.loads((home / ".codex" / "hooks.json").read_text())["hooks"]
            self.assertEqual(set(firstrun.LIFECYCLE_EVENTS), set(claude))
            self.assertEqual(set(firstrun.LIFECYCLE_EVENTS), set(codex))


class BackendCommandTests(unittest.TestCase):
    def test_builds_backend_specific_launch_and_resume_commands(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            claude = mp.build_launch("n/main:e", td, "n/main:Boss", False,
                                     "claude-model", "claude", "claude-session")
            codex = mp.build_launch("n/main:e", td, "n/main:Boss", False,
                                    "codex-model", "codex", "codex-session")

            self.assertIn("MYPEOPLE_BACKEND=claude", claude)
            self.assertIn("claude --dangerously-skip-permissions", claude)
            self.assertIn("--resume claude-session", claude)
            self.assertIn("MYPEOPLE_BACKEND=codex", codex)
            self.assertIn("codex --dangerously-bypass-approvals-and-sandbox", codex)
            self.assertIn("--dangerously-bypass-hook-trust", codex)
            self.assertIn("resume codex-session", codex)

    def test_finds_backend_specific_session_transcripts(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            home = Path(td)
            claude = home / ".claude" / "projects" / "p" / "claude-id.jsonl"
            codex = home / ".codex" / "sessions" / "2026" / "07" / "rollout-codex-id.jsonl"
            claude.parent.mkdir(parents=True)
            codex.parent.mkdir(parents=True)
            claude.touch()
            codex.touch()
            with mock.patch.dict(os.environ, {"HOME": td}):
                self.assertEqual([str(claude)], mp.session_files("claude", "claude-id"))
                self.assertEqual([str(codex)], mp.session_files("codex", "codex-id"))

    def test_send_routes_next_stop_to_the_calling_agent(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            target = "test-node/main:peer"
            parent = "test-node/main:parent"
            with mock.patch.dict(os.environ, {"AGENT_ID": parent}), \
                 mock.patch.object(mp.C, "tmux_send_message", return_value=True):
                self.assertEqual(0, mp.do_send([target, "do work"]))
            self.assertEqual(parent, mp.C.claim_notification_route(target))
            self.assertEqual("", mp.C.claim_notification_route(target))

    def test_failed_send_cancels_its_notification_route(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            target = "test-node/main:missing"
            with mock.patch.dict(os.environ, {"AGENT_ID": "test-node/main:parent"}), \
                 mock.patch.object(mp.C, "tmux_send_message", return_value=False):
                self.assertEqual(1, mp.do_send([target, "do work"]))
            self.assertEqual("", mp.C.claim_notification_route(target))

    def test_remote_send_carries_reply_to(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            with mock.patch.dict(os.environ, {"AGENT_ID": "test-node/main:parent"}), \
                 mock.patch.object(mp, "remote_task", return_value=(True, "sent")) as remote:
                self.assertEqual(0, mp.do_send(["other-node/main:peer", "do work"]))
            remote.assert_called_once_with(
                "send", "other-node/main:peer",
                {"message": "do work", "reply_to": "test-node/main:parent"}, timeout=30,
            )


class NotificationRouteTests(unittest.TestCase):
    def test_routes_are_fifo_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as td:
            mp = load_mp(td)
            target = "test-node/main:worker"
            first = mp.C.enqueue_notification_route(target, "test-node/main:first")
            second = mp.C.enqueue_notification_route(target, "test-node/main:second")

            self.assertTrue(first)
            self.assertTrue(second)
            self.assertTrue(mp.C.cancel_notification_route(target, first))
            self.assertEqual("test-node/main:second", mp.C.claim_notification_route(target))
            self.assertEqual("", mp.C.claim_notification_route(target))


class HookHandlerTests(unittest.TestCase):
    def test_codex_stop_uses_last_assistant_message(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.update({
                "INSTALL_DIR": td,
                "AGENT_ID": "node/main:eng",
                "MYPEOPLE_BACKEND": "codex",
                "BOSS_ID": "",
            })
            payload = {
                "hook_event_name": "Stop",
                "session_id": "codex-session",
                "last_assistant_message": "Finished from Codex",
            }
            subprocess.run(
                [sys.executable, str(HANDLER), "Stop"],
                input=json.dumps(payload), text=True, env=env, check=True,
            )
            status = json.loads((Path(td) / "status" / "mc-main" / "eng.json").read_text())
            self.assertEqual("codex", status["backend"])
            self.assertEqual("idle", status["status"])
            self.assertEqual("codex-session", status["session_id"])
            self.assertEqual("Finished from Codex", status["summary"])


if __name__ == "__main__":
    unittest.main()
