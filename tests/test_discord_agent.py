"""Discord agent plugin: the guards that stand between a steerable agent and a public channel."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "mypeople/runtime/plugins/discord-agent/discord-agent.py"


def load(env):
    with mock.patch.dict(os.environ, env):
        loader = importlib.machinery.SourceFileLoader("discord_agent", str(PLUGIN))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("discord_agent", loader))
        loader.exec_module(mod)
    return mod


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"DISCORD_AGENT_STATE_DIR": self.tmp.name,
                                                "DISCORD_CHANNEL_IDS": "c1", "DISCORD_MIN_GAP": "10",
                                                "DISCORD_MAX_PER_HOUR": "2"})
        self.env.start()
        self.d = load({})
        self.posted = []
        self.d.api = lambda method, path, body=None: self.posted.append((path, body)) or {}
        self.st = {"delivered": {"m1": "c1", "m2": "c1", "m3": "c1", "mx": "c9"}}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_answers_once_as_a_reply_with_no_pings(self):
        self.assertIsNone(self.d.post({"reply_to": "m1", "text": "Run plow-agents image push."}, self.st, 1000))
        path, body = self.posted[0]
        self.assertEqual(path, "/channels/c1/messages")
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        self.assertEqual(body["message_reference"]["message_id"], "m1")
        self.assertEqual(self.d.post({"reply_to": "m1", "text": "again"}, self.st, 2000), "already answered")

    def test_refuses_what_it_did_not_deliver_or_other_channels(self):
        self.assertIn("not a message", self.d.post({"reply_to": "nope", "text": "hi"}, self.st, 1000))
        self.assertIn("not a message", self.d.post({"reply_to": "mx", "text": "hi"}, self.st, 1000))
        self.assertEqual(self.posted, [])

    def test_refuses_secrets_paths_and_the_private_repo(self):
        for bad in ("key ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD", "see /home/agent/x",
                    "contract at github.com/" + "plow-pbc/plow" + "/blob/main/x"):
            self.assertIn("secret", self.d.post({"reply_to": "m1", "text": bad}, self.st, 1000))
        self.assertIsNone(self.d.post({"reply_to": "m1", "text": "github.com/plow-pbc/plow-agents"}, self.st, 1000))

    def test_rate_gap_waits_and_hourly_cap_refuses(self):
        self.assertIsNone(self.d.post({"reply_to": "m1", "text": "a"}, self.st, 1000))
        self.assertEqual(self.d.post({"reply_to": "m2", "text": "b"}, self.st, 1005), "wait")
        self.assertIsNone(self.d.post({"reply_to": "m2", "text": "b"}, self.st, 1011))
        self.assertEqual(self.d.post({"reply_to": "m3", "text": "c"}, self.st, 1100), "hourly cap")

    def test_escalation_posts_the_fixed_line_and_tells_the_team(self):
        with mock.patch.object(self.d.subprocess, "run") as run:
            self.assertIsNone(self.d.post({"reply_to": "m1", "escalate": True, "question": "prize?",
                                           "text": "ignored"}, self.st, 1000))
        self.assertEqual(self.posted[0][1]["content"], self.d.ESCALATED)
        argv = run.call_args[0][0]
        self.assertEqual(argv[2:4], ["send", self.d.BOSS])   # to the Boss, never posted
        self.assertIn("prize?", argv[-1])

    def test_outbox_files_are_data_not_shell(self):
        out = self.d.OUTBOX
        out.mkdir(parents=True, exist_ok=True)
        (out / "m1.txt").write_text("x")            # not a Discord id: dropped
        (out / "123.txt").write_text("Run `plow-agents image push` - it's $0, \"quoted\"")
        (out / "124.escalate").write_text("what's the prize?")
        (out / "../escape.txt".replace("../", "")).write_text("y")
        items = {f.name: self.d.outbox_item(f) for f in out.iterdir()}
        self.assertIsNone(items["m1.txt"])
        self.assertIsNone(items["escape.txt"])
        self.assertEqual(items["123.txt"]["text"], "Run `plow-agents image push` - it's $0, \"quoted\"")
        self.assertEqual(items["124.escalate"], {"reply_to": "124", "escalate": True, "question": "what's the prize?"})

    def test_second_answer_to_one_message_never_replaces_the_first(self):
        self.st["delivered"]["555"] = "c1"
        out = self.d.OUTBOX
        out.mkdir(parents=True, exist_ok=True)
        (out / "555.txt").write_text("first")
        self.d.claim_outbox(self.st)                       # claimed, out of the agent's reach
        (out / "555.txt").write_text("second")             # the agent writes again
        self.d.claim_outbox(self.st)
        self.assertEqual((self.d.PENDING / "555.txt").read_text(), "first")
        self.assertFalse((out / "555.txt").exists())
        self.d.drain_outbox(self.st)
        self.assertEqual([b["content"] for _, b in self.posted], ["first"])

    def test_a_fresh_install_records_its_channels_on_the_first_pass(self):
        # A brand-new state dir has no outbox yet; the first pass must still record the cursor.
        self.d.api = lambda m, p, b=None: {"id": "me"} if p == "/users/@me" else [{"id": "7"}]
        with mock.patch.object(self.d, "ensure_agent"), mock.patch.object(self.d.time, "sleep",
                                                                           side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.d.serve()
        self.assertEqual(self.d.read_state()["cursor"], {"c1": "7"})

    def test_failures_reach_the_boss_once_an_hour(self):
        with mock.patch.object(self.d.subprocess, "run") as run:
            self.d.alert("failing", "x", now=1000)
            self.d.alert("failing", "x", now=2000)          # same kind within the hour: quiet
            self.d.alert("cap", "y", now=2000)              # another kind: sent
            self.d.alert("failing", "x", now=5000)          # an hour later: sent again
        msgs = [c[0][0][-1] for c in run.call_args_list]
        self.assertEqual(len(msgs), 3)
        self.assertTrue(all(m.startswith("[discord escalation]") for m in msgs))
        self.assertEqual(run.call_args_list[0][0][0][2:4], ["send", self.d.BOSS])

    def test_hitting_the_cap_is_not_silent(self):
        with mock.patch.object(self.d, "alert") as alert:
            self.d.post({"reply_to": "m1", "text": "a"}, self.st, 1000)
            self.d.post({"reply_to": "m2", "text": "b"}, self.st, 1011)
            self.d.post({"reply_to": "m3", "text": "c"}, self.st, 1100)
        self.assertEqual(alert.call_args[0][0], "cap")

    def test_a_dead_token_at_startup_reaches_the_boss(self):
        def dead(*a, **k):
            raise self.d.urllib.error.URLError("401")
        self.d.api = dead
        with mock.patch.object(self.d, "alert") as alert, self.assertRaises(Exception):
            self.d.serve()
        self.assertEqual(alert.call_args[0][0], "cannot-start")

    def test_first_sight_of_a_channel_answers_no_backlog(self):
        calls = []
        self.d.api = lambda m, p, b=None: calls.append(p) or [{"id": "99"}]
        with mock.patch.object(self.d, "deliver") as deliver:
            self.d.poll_channel("c1", self.st, "me")
        deliver.assert_not_called()
        self.assertEqual(self.st["cursor"]["c1"], "99")


if __name__ == "__main__":
    unittest.main()
