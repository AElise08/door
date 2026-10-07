"""Answering without the owner approving every message (the default), with per-person overrides."""
import tempfile
import unittest
from pathlib import Path

from door.cloud import Cloud
from door.common import now, ulid, sha256_text
from door.door_link import to_cloud_command, to_panel_snapshot

OWNER, ANA, BOB = "+15550000001", "+15551110001", "+15551110002"
SUMMARY = {"alias": "desk", "description": "", "max_capability": "ask",
           "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 3,
                      "guest_daily_tokens": 400000, "monthly_budget": 50.0, "currency": "USD"}}


class Auto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = now()
        self.c = Cloud(Path(self.tmp.name) / "c.db", "o", SUMMARY, "https://p.example", clock=lambda: self.t)   # default: auto
        self.c.set_plan("active", self.t + 86400 * 30)
        self.c.s.update(owner_phone=OWNER, owner_thread="owner-thread")
        self.ana = self.c.add_guest(ANA, "Ana"); self.bob = self.c.add_guest(BOB, "Bob")

    def tearDown(self): self.tmp.cleanup()
    def ask(self, phone, text="How does login work?", finish=True):
        rid = self.c.receive(ulid(), phone, "t-" + phone, text)
        if rid and finish and self.c.s["requests"][rid]["state"] == "queued":
            self.c.s["requests"][rid]["state"] = "completed"       # the Mac answered; otherwise the 2-open-requests limit applies
        return rid
    def texts(self, thread): return [x["text"] for x in self.c.pending_sms() if x["thread"] == thread]

    def test_default_is_auto_and_the_question_is_queued_at_once(self):
        rid = self.ask(ANA, finish=False)
        r = self.c.s["requests"][rid]
        self.assertEqual(r["state"], "queued")
        self.assertEqual((r["approval"]["decided_by"], r["approval"]["decision"], r["approval"]["text_hash"]), ("auto:policy", "approve", sha256_text(r["text"])))
        self.assertEqual(self.texts("t-" + ANA), ["Got it. Working on it."])
        self.assertEqual(self.texts("owner-thread"), [])                       # no text message to the owner per question

    def test_limits_still_apply_without_approval(self):
        for _ in range(3): self.assertIsNotNone(self.ask(ANA))
        self.assertIsNone(self.ask(ANA))                                        # 4th question of the day
        self.assertTrue(any("limit" in s for s in self.texts("t-" + ANA)))

    def test_suspended_expired_and_inactive_plan_are_still_refused(self):
        self.c.set_guest_status(self.bob, "suspended")
        self.assertIsNone(self.ask(BOB))
        self.c.set_plan("canceled", 0)
        self.assertIsNone(self.ask(ANA))

    def test_per_person_override_asks_the_owner(self):
        self.c.set_guest_approval(self.bob, "each")
        rid = self.ask(BOB, "delete everything?", finish=False)
        self.assertEqual(self.c.s["requests"][rid]["state"], "waitingApproval")
        self.assertTrue(any("Bob asks" in s for s in self.texts("owner-thread")))
        self.assertEqual(self.c.s["requests"][self.ask(ANA, finish=False)]["state"], "queued")  # Ana is unaffected

    def test_global_switch_and_reset(self):
        self.c.set_approval("each")
        r1 = self.ask(ANA, finish=False)
        self.assertEqual(self.c.s["requests"][r1]["state"], "waitingApproval")
        self.c.s["requests"][r1]["state"] = "canceled"
        self.c.set_guest_approval(self.ana, "auto")                              # explicit override beats the default
        r2 = self.ask(ANA, finish=False)
        self.assertEqual(self.c.s["requests"][r2]["state"], "queued")
        self.c.s["requests"][r2]["state"] = "completed"
        self.c.set_guest_approval(self.ana, None)
        r3 = self.ask(ANA, finish=False)
        self.assertEqual(self.c.s["requests"][r3]["state"], "waitingApproval")
        with self.assertRaises(ValueError): self.c.set_approval("whenever")
        with self.assertRaises(ValueError): self.c.set_guest_approval(self.ana, "maybe")

    def test_web_chat_guests_are_auto_too(self):
        rid = self.c.receive_web("l_abc", 1, "hello?", "Cy", 14)
        self.assertEqual(self.c.s["requests"][rid]["state"], "queued")
        self.assertEqual(self.texts("web:l_abc"), ["Got it. Working on it."])

    def test_old_databases_keep_asking(self):
        path = Path(self.tmp.name) / "old.db"
        c1 = Cloud(path, "o", SUMMARY, clock=lambda: self.t)
        del c1.s["settings"]; c1._save(); c1.db.close()
        c2 = Cloud(path, "o", SUMMARY, clock=lambda: self.t)
        self.assertEqual(c2.s["settings"]["approval"], "each")

    def test_panel_commands_map_and_snapshot_exposes_the_setting(self):
        self.assertEqual(to_cloud_command({"id": "c1", "type": "set_approval", "mode": "each"})["op"], "settings.approval")
        m = to_cloud_command({"id": "c2", "type": "guest_approval", "guest_id": self.ana, "mode": "auto"})
        self.assertEqual((m["op"], m["mode"]), ("guest.approval", "auto"))
        self.assertIsNone(to_cloud_command({"id": "c3", "type": "guest_approval", "guest_id": self.ana, "mode": "default"})["mode"])
        snap = to_panel_snapshot(self.c.snapshot())
        self.assertEqual(snap["approval"], "auto")
        self.assertEqual({g["name"]: g["approval"] for g in snap["guests"]}, {"Ana": "", "Bob": ""})


if __name__ == "__main__":
    unittest.main()
