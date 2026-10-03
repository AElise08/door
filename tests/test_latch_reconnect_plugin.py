"""The Latch reconnect watcher gives agents their Latch tools back after Latch restarts.

Claude Code stops retrying a dropped MCP server after ~31s, and a Latch update leaves Latch off
until something reopens it, so agents silently ran without Latch for days (card a7fe145019).
These tests drive the watcher with tmux, the relay and the status files stubbed: it must type
only into idle agents, never mid-turn or over a half-typed message.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "mypeople" / "runtime" / "plugins" / "latch-reconnect" / "latch-reconnect.py"
IDLE_PANE = "● done.\n✻ Worked for 2s\n────\n❯ \n────\n  ⏵⏵ bypass permissions on\n"


def load(install):
    with mock.patch.dict(os.environ, {"INSTALL_DIR": install, "HOST_ID": "node"}):
        loader = importlib.machinery.SourceFileLoader("latch_reconnect_%d" % id(install), str(PLUGIN))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod


class FakeTmux:
    """Panes by target: text on screen and copy mode. Records every send-keys call."""

    def __init__(self):
        self.panes, self.sent = {}, []

    def __call__(self, *args):
        r = mock.Mock(returncode=0, stdout="", stderr="")
        tgt = args[args.index("-t") + 1]
        if tgt not in self.panes:
            r.returncode = 1
            return r
        if args[0] == "display-message":
            r.stdout = "1\n" if self.panes[tgt].get("mode") else "0\n"
        elif args[0] == "capture-pane":
            r.stdout = self.panes[tgt]["text"]
        elif args[0] == "send-keys":
            self.sent.append(args)
            self.panes[tgt]["text"] += "  ⎿  Reconnected 1 of 1 MCP servers\n"
        return r


class LatchReconnectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = load(self.tmp.name)
        self.m.time.sleep = lambda s: None
        self.tmux = FakeTmux()
        self.m.tmux = self.tmux

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, tab, status="idle", age=60, pane=IDLE_PANE, mode=False, backend="claude"):
        d = Path(self.tmp.name) / "status" / "mc-main"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tab}.json").write_text(json.dumps({
            "status": status, "timestamp": str(time.time() - age), "backend": backend, "state": "alive"}))
        if pane is not None:
            self.tmux.panes[f"mc-main:{tab}"] = {"text": pane, "mode": mode}
        return f"node/main:{tab}"

    def typed_into(self):
        return [a[a.index("-t") + 1] for a in self.tmux.sent]

    def test_idle_only(self):
        ok = self.agent("ok")
        self.assertIsNone(self.m.why_busy(ok))
        self.assertEqual(self.m.why_busy(self.agent("w", status="working")), "status working")
        self.assertEqual(self.m.why_busy(self.agent("new", age=3)), "idle too recently")
        self.assertEqual(self.m.why_busy(self.agent("scroll", mode=True)), "pane in copy mode")
        spinner = IDLE_PANE.replace("✻ Worked for 2s", "✻ Thinking… (3s · esc to interrupt)")
        self.assertEqual(self.m.why_busy(self.agent("spin", pane=spinner)), "turn in flight")
        typing = IDLE_PANE.replace("❯ \n", "❯ half a message\n")
        self.assertEqual(self.m.why_busy(self.agent("typing", pane=typing)), "composer not empty")
        menu = IDLE_PANE.replace("❯ \n", "❯ 1. Yes\n  2. No\n")
        self.assertEqual(self.m.why_busy(self.agent("menu", pane=menu)), "composer not empty")
        self.assertEqual(self.m.why_busy(self.agent("nopane", pane=None)), "no pane")

    def test_text_and_enter_go_in_one_tmux_call(self):
        self.assertTrue(self.m.reconnect(self.agent("ok")))
        (call,) = self.tmux.sent
        self.assertEqual(call, ("send-keys", "-t", "mc-main:ok", "-l", "/mcp reconnect all", ";",
                                "send-keys", "-t", "mc-main:ok", "Enter"))

    def test_latch_back_after_outage_reconnects_idle_now_busy_later(self):
        idle, busy = self.agent("idle"), self.agent("busy", status="working")
        self.agent("codex", backend="codex")
        s = {"started": True, "pid": 100}
        s = self.m.tick(s, up=True, pid=100, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), [], "steady state: nobody is owed anything")
        s = self.m.tick(s, up=False, pid=None, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), [], "nothing is typed while Latch is down")
        s = self.m.tick(s, up=True, pid=200, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), ["mc-main:idle"])
        self.assertEqual(s["owed"], [busy], "the busy agent waits, the codex one is never owed")
        self.agent("busy")  # its turn ended
        s = self.m.tick(s, up=True, pid=200, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), ["mc-main:idle", "mc-main:busy"])
        self.assertEqual(s["owed"], [])
        self.assertIsNotNone(idle)

    def test_fast_restart_between_polls_is_caught_by_the_new_pid(self):
        self.agent("a")
        s = self.m.tick({"started": True, "pid": 100}, up=True, pid=101, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), ["mc-main:a"])
        self.assertEqual(s["owed"], [])

    def test_watcher_start_heals_sessions_that_lost_latch_while_it_was_off(self):
        self.agent("a")
        self.m.tick({"started": False}, up=True, pid=100, agents=self.m.claude_agents())
        self.assertEqual(self.typed_into(), ["mc-main:a"])

    def test_dead_agent_is_dropped_not_retried_forever(self):
        # A status file outlives its agent, frozen at "working": the missing pane must win.
        ghosts = [self.agent("ghost", pane=None), self.agent("ghost2", status="working", pane=None)]
        s = self.m.tick({"started": True, "pid": 1, "owed": ghosts}, up=True, pid=1,
                        agents=self.m.claude_agents())
        self.assertEqual(s["owed"], [])

    def test_relay_servers_read_from_claude_json_without_logging_the_key(self):
        cj = Path(self.tmp.name) / "claude.json"
        relay = {"type": "http", "url": "https://api.plow.co/v1/relay/devices/abc/mcp",
                 "headers": {"Authorization": "Bearer plow_secret"}}
        cj.write_text(json.dumps({"mcpServers": {"x": {"type": "stdio", "command": "y"}},
                                  "projects": {"/p": {"mcpServers": {"plow": relay}},
                                               "/q": {"mcpServers": {"plow": relay}}}}))
        self.m.CLAUDE_JSON = cj
        self.assertEqual(self.m.relay_servers(), [(relay["url"], "Bearer plow_secret")])


if __name__ == "__main__":
    unittest.main()
