"""Live-parity fixes that only existed on the CEO's install until 0.4.0.

tmux_send_message was mocked by every other test, so its submit behaviour was never exercised
here -- which is how an unconditional second Enter survived. These tests drive the real function
with tmux stubbed at subprocess level.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "mypeople" / "runtime" / "bin"


def load_mpcommon(home):
    config = Path(home) / "queue.env"
    config.write_text(
        'export INSTALL_DIR="%s"\n'
        'export HOST_ID="test-node"\n'
        'export QUEUE_URL="http://127.0.0.1:9900"\n' % (Path(home) / "state"),
        encoding="utf-8",
    )
    env = {"HOME": str(home), "MYPEOPLE_CONFIG_PATH": str(config),
           "MYPEOPLE_HOME": str(Path(home) / "state"), "HOST_ID": "test-node",
           "QUEUE_URL": "http://127.0.0.1:9900"}
    with mock.patch.dict(os.environ, env, clear=False):
        sys.modules.pop("mpcommon", None)
        sys.path.insert(0, str(BIN))
        try:
            loader = importlib.machinery.SourceFileLoader("mpcommon", str(BIN / "mpcommon.py"))
            spec = importlib.util.spec_from_loader("mpcommon", loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(BIN))


class FakeTmux:
    """Records tmux argv. has-session succeeds; capture-pane returns whatever the test stages."""

    def __init__(self, pane_text=""):
        self.calls = []
        self.pane_text = pane_text

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        rc, out = 0, ""
        if "capture-pane" in argv:
            out = self.pane_text
        return mock.Mock(returncode=rc, stdout=out, stderr="")

    def sent(self):
        return [c for c in self.calls if c[:2] == ["tmux", "send-keys"]]

    def enters(self):
        return [c for c in self.sent() if c[-1] == "Enter"]

    def literals(self):
        return [c[-1] for c in self.sent() if "-l" in c]


class TmuxSendMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.C = load_mpcommon(self.tmp.name)

    def send(self, message, pane_text=""):
        fake = FakeTmux(pane_text)
        with mock.patch.object(self.C.subprocess, "run", fake), \
             mock.patch.object(self.C.time, "sleep"):
            ok = self.C.tmux_send_message("mc-main:eng-1", message)
        return ok, fake

    def test_empty_message_sends_nothing(self):
        """A blank message must never reach the pane: a bare Enter submits whatever the agent
        had half-typed in its composer."""
        for blank in ("", "   ", "\n", None):
            ok, fake = self.send(blank)
            self.assertFalse(ok, "blank %r should report failure" % (blank,))
            self.assertEqual(fake.sent(), [], "blank %r sent keys" % (blank,))

    def test_single_line_submits_exactly_once(self):
        """The regression: an unconditional second Enter submits the composer twice, so the
        agent receives a spurious empty prompt after every single-line message."""
        ok, fake = self.send("status please")
        self.assertTrue(ok)
        self.assertEqual(fake.literals(), ["status please"])
        self.assertEqual(len(fake.enters()), 1)

    def test_multiline_retries_only_when_paste_marker_remains(self):
        ok, fake = self.send("line one\nline two", pane_text="> [Pasted text +2 lines]")
        self.assertTrue(ok)
        self.assertEqual(len(fake.enters()), 2)

    def test_multiline_does_not_retry_when_composer_cleared(self):
        ok, fake = self.send("line one\nline two", pane_text="> ready")
        self.assertTrue(ok)
        self.assertEqual(len(fake.enters()), 1)

    def test_never_targets_the_calling_pane(self):
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-501/default,123,4"}, clear=False):
            fake = FakeTmux()
            with mock.patch.object(self.C.subprocess, "run", fake), \
                 mock.patch.object(self.C.time, "sleep"):
                self.C.tmux_send_message("mc-main:eng-1", "hi")
        self.assertTrue(fake.sent())


class SupervisorScriptTests(unittest.TestCase):
    """These two lines are the difference between a subsystem that runs and one that only exists."""

    def test_boss_supervisor_calls_reconcile(self):
        """mp reconcile is the only periodic caller of the reaper/reconcile subsystem; without it
        the fleet is only ever repaired by hand."""
        text = (BIN / "boss-supervisor.sh").read_text()
        self.assertIn("mp reconcile", text)
        self.assertIn("|| true", text.split("mp reconcile", 1)[1].split("\n", 1)[0],
                      "a failing reconcile must not kill the supervisor loop")

    def test_supervise_raises_descriptor_limit_before_starting_daemons(self):
        text = (BIN / "supervise.sh").read_text()
        self.assertIn("ulimit -n", text)
        self.assertLess(text.index("ulimit -n"), text.index("ensure "),
                        "ulimit must be raised before any daemon is spawned")


class BoardUiTests(unittest.TestCase):
    HTML = (BIN / "todos.html").read_text()

    def test_comments_render_markdown(self):
        for fn in ("renderMarkdown", "markdownInline", "markdownTable", "safeMarkdownHref"):
            self.assertIn(fn, self.HTML)

    def test_markdown_links_are_sanitised(self):
        self.assertIn('rel="noopener noreferrer"', self.HTML.replace("'", '"'))

    def test_board_fetch_is_guarded(self):
        """The board is ~12 MB: overlapping polls stack up, and a late response can clobber a
        just-posted comment."""
        self.assertIn("boardFetchInFlight", self.HTML)
        self.assertIn("boardReq", self.HTML)

    def test_owner_history_is_rendered(self):
        self.assertIn("ownerHistory", self.HTML)

    def test_terminal_graph_is_reachable_from_the_board(self):
        self.assertIn("terminal-graph", self.HTML)

    def test_assignee_is_not_a_free_text_field(self):
        """/todo/owner owns assignment: op=set refuses a supplied assignee, so an editable input
        would silently do nothing."""
        self.assertNotIn('patchTask(task.id,{assignee:', self.HTML.replace(" ", ""))
        self.assertIn("appendAgentLink", self.HTML)


if __name__ == "__main__":
    unittest.main()
