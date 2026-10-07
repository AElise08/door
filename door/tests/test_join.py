"""How people get in: invite codes, access requests by text, and group chats."""
import tempfile
import unittest
from pathlib import Path

from door.cloud import Cloud, UNKNOWN
from door.common import now, ulid
from door.plow import PlowAPI

OWNER, ANA, BOB, EVE = "+15550000001", "+15551110001", "+15551110002", "+15559990009"
SUMMARY = {"alias": "desk", "description": "", "max_capability": "ask",
           "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10,
                      "guest_daily_tokens": 400000, "monthly_budget": 50.0, "currency": "USD"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = now()
        self.c = Cloud(Path(self.tmp.name) / "c.db", "o", SUMMARY, "https://panel.example", clock=lambda: self.t, approval="each")
        self.c.set_plan("active", self.t + 86400 * 30)
        self.c.s.update(owner_phone=OWNER, owner_thread="owner-thread")

    def tearDown(self): self.tmp.cleanup()

    def send(self, phone, text, thread=None, group=False, members=None):
        return self.c.receive(ulid(), phone, thread or "t-" + phone, text, group, members)

    def sms(self, thread=None):
        return [x["text"] for x in self.c.pending_sms() if thread is None or x["thread"] == thread]

    def guest(self, phone):
        return next((g for g in self.c.s["guests"].values() if g["phone"] == phone), None)


class InviteCodes(Base):
    def test_code_makes_a_guest_once(self):
        code = self.c.create_invite("Ana", days=14)
        self.send(ANA, "Door Join: " + code)
        g = self.guest(ANA)
        self.assertEqual((g["display_name"], g["status"]), ("Ana", "active"))
        self.assertAlmostEqual(g["expires_at"], self.t + 14 * 86400, delta=2)
        self.assertTrue(any("You're in, Ana" in s for s in self.sms("t-" + ANA)))
        self.assertTrue(any("Ana joined" in s for s in self.sms("owner-thread")))
        self.send(BOB, "Door Join: " + code)                       # single use
        self.assertIsNone(self.guest(BOB))
        self.assertTrue(any("not valid" in s for s in self.sms("t-" + BOB)))

    def test_code_is_forgiving_about_case_and_dash(self):
        code = self.c.create_invite("Ana")
        self.send(ANA, "door join " + code.lower().replace("-", ""))
        self.assertIsNotNone(self.guest(ANA))

    def test_expired_wrong_and_owner(self):
        code = self.c.create_invite("Ana", ttl_days=1)
        self.t += 2 * 86400
        self.send(ANA, "Door Join: " + code)
        self.assertIsNone(self.guest(ANA))
        code2 = self.c.create_invite("Owner?")
        self.send(OWNER, "Door Join: " + code2)                    # the owner cannot join as a guest
        self.assertIsNone(self.guest(OWNER))

    def test_guessing_is_throttled_and_then_silent(self):
        real = self.c.create_invite("Ana")
        for i in range(5):
            self.send(EVE, "Door Join: WRONG%d" % i)
        before = len(self.sms("t-" + EVE))
        self.send(EVE, "Door Join: " + real)                       # even the right code is refused during the lockout
        self.assertIsNone(self.guest(EVE))
        self.assertEqual(len(self.sms("t-" + EVE)), before)         # and silently: no oracle
        self.t += 3601
        self.send(EVE, "Door Join: " + real)
        self.assertIsNotNone(self.guest(EVE))

    def test_invite_limits_and_validation(self):
        with self.assertRaises(ValueError): self.c.create_invite("x", days=0)
        with self.assertRaises(ValueError): self.c.create_invite("x", days=91)
        with self.assertRaises(ValueError): self.c.create_invite("x", ttl_days=31)
        for _ in range(50): self.c.create_invite("x")
        with self.assertRaises(ValueError): self.c.create_invite("x")
        code = next(iter(self.c.s["invites"].values()))["code"]
        self.c.revoke_invite(code)
        self.assertNotIn(code.replace("-", ""), self.c.s["invites"])

    def test_new_guest_can_ask_immediately(self):
        self.send(ANA, "Door Join: " + self.c.create_invite("Ana"))
        rid = self.send(ANA, "How does login work?")
        self.assertEqual(self.c.s["requests"][rid]["state"], "waitingApproval")


class AccessRequests(Base):
    def test_stranger_asks_owner_decides(self):
        self.send(EVE, "Door Request: Eve from sales")
        self.assertIn("Eve from sales", " ".join(self.sms("owner-thread")))
        self.assertEqual(list(self.c.s["access_requests"]), [EVE])
        self.assertIsNone(self.guest(EVE))                                 # not in until the owner says so
        self.c.resolve_access(EVE, True)
        self.assertEqual(self.guest(EVE)["display_name"], "Eve from sales")
        self.assertTrue(any("You're in" in s for s in self.sms("t-" + EVE)))

    def test_ignore_and_caps_and_no_text_leak(self):
        self.send(EVE, "Door Request: Eve")
        self.c.resolve_access(EVE, False)
        self.assertIsNone(self.guest(EVE))
        self.assertEqual(self.c.s["access_requests"], {})
        for i in range(25):
            self.send("+1555222%04d" % i, "Door Request: p%d" % i)
        self.assertEqual(len(self.c.s["access_requests"]), 20)
        with self.assertRaises(ValueError): self.c.resolve_access("+19999999999", True)

    def test_request_text_is_sanitised(self):
        self.send(EVE, "Door Request: <b>Eve</b>; rm -rf /\n\nignore previous")
        name = self.c.s["access_requests"][EVE]["name"]
        self.assertNotIn("<", name); self.assertNotIn(";", name); self.assertNotIn("\n", name); self.assertLessEqual(len(name), 60)

    def test_plain_text_from_a_stranger_still_gets_one_fixed_reply_and_never_reaches_the_owner(self):
        for _ in range(3): self.send(EVE, "run ls for me")
        self.assertEqual(self.sms("t-" + EVE), [UNKNOWN])
        self.assertFalse(any("run ls" in s for s in self.sms("owner-thread")))


class Groups(Base):
    def setUp(self):
        super().setUp()
        self.c.add_guest(ANA, "Ana"); self.c.add_guest(BOB, "Bob")

    def test_answers_in_a_group_of_owner_and_guests_only(self):
        rid = self.send(ANA, "How do I deploy?", "group-1", True, [OWNER, ANA, BOB])
        r = self.c.s["requests"][rid]
        self.assertEqual((r["thread_id"], r["state"]), ("group-1", "waitingApproval"))
        self.assertTrue(any("Received" in s for s in self.sms("group-1")))
        self.assertTrue(any("Ana asks" in s for s in self.sms("owner-thread")))     # approval still goes to the owner

    def test_group_with_an_outsider_is_silent_and_tells_the_owner_once_a_day(self):
        for _ in range(3):
            self.assertIsNone(self.send(ANA, "secret question", "group-2", True, [OWNER, ANA, EVE]))
        self.assertEqual(self.sms("group-2"), [])
        self.assertEqual(len([s for s in self.sms("owner-thread") if "not an authorized guest" in s]), 1)
        self.assertFalse(self.c.s["requests"])

    def test_unknown_or_incomplete_roster_is_treated_as_unsafe(self):
        self.assertIsNone(self.send(ANA, "hi", "g3", True, None))
        self.assertIsNone(self.send(ANA, "hi", "g3", True, []))
        self.assertFalse(self.c.s["requests"])

    def test_suspended_or_expired_member_makes_the_group_unsafe(self):
        self.c.set_guest_status(self.guest(BOB)["guest_id"], "suspended")
        self.assertIsNone(self.send(ANA, "hi", "g4", True, [OWNER, ANA, BOB]))

    def test_strangers_and_the_owner_cannot_trigger_anything_in_a_group(self):
        self.assertIsNone(self.send(EVE, "hello agent", "g5", True, [OWNER, EVE]))
        self.assertIsNone(self.send(OWNER, "hello", "g5", True, [OWNER, ANA]))
        self.assertEqual(self.sms("g5"), [])

    def test_approvals_never_work_from_a_group(self):
        rid = self.send(ANA, "do it", "g6", True, [OWNER, ANA])
        code = self.c.s["requests"][rid]["approval_code"]
        self.send(OWNER, "YES " + code, "g6", True, [OWNER, ANA])
        self.assertEqual(self.c.s["requests"][rid]["state"], "waitingApproval")
        self.send(ANA, "YES " + code, "g6", True, [OWNER, ANA])           # a guest approving their own request
        self.assertEqual(self.c.s["requests"][rid]["state"], "waitingApproval")

    def test_join_code_works_inside_a_group_but_answers_still_need_everyone_authorised(self):
        code = self.c.create_invite("Cy")
        CY = "+15553330003"
        self.send(CY, "Door Join: " + code, "g7", True, [OWNER, ANA, CY])
        self.assertIsNotNone(self.guest(CY))
        self.assertIsNotNone(self.send(CY, "hello?", "g7", True, [OWNER, ANA, CY]))


class OpenGroups(Base):
    def test_owner_says_allow_and_everyone_in_the_group_is_in(self):
        self.send(OWNER, "Door Allow", "g1", True, [OWNER, ANA, BOB])
        self.assertEqual({g["phone"] for g in self.c.s["guests"].values()}, {ANA, BOB})
        self.assertTrue(any("I'm Door" in s and "Ask me anything" in s for s in self.sms("g1")))
        rid = self.send(ANA, "How do I deploy?", "g1", True, [OWNER, ANA, BOB])        # works right away
        self.assertEqual(self.c.s["requests"][rid]["state"], "waitingApproval")        # still approved by the owner per question

    def test_adding_the_number_to_a_group_or_a_stranger_saying_allow_authorizes_nobody(self):
        self.send(EVE, "Door Allow", "g2", True, [OWNER, EVE, ANA])
        self.send(ANA, "Door Allow", "g2", True, [OWNER, EVE, ANA])
        self.send(ANA, "hello agent", "g2", True, [OWNER, EVE, ANA])
        self.assertEqual(self.c.s["guests"], {}); self.assertEqual(self.c.s["requests"], {})

    def test_later_joiners_are_added_while_the_group_is_open_and_the_owner_is_told(self):
        self.send(OWNER, "Door Allow", "g3", True, [OWNER, ANA])
        rid = self.send(ANA, "hi?", "g3", True, [OWNER, ANA, BOB])                      # Bob was added to the group after
        self.assertIsNotNone(rid)
        self.assertIsNotNone(self.guest(BOB))
        self.assertTrue(any(BOB in s and "joined an open group" in s for s in self.sms("owner-thread")))

    def test_stop_closes_it_and_revoked_people_stay_revoked(self):
        self.send(OWNER, "Door Allow", "g4", True, [OWNER, ANA, BOB])
        self.c.set_guest_status(self.guest(BOB)["guest_id"], "revoked")
        self.send(ANA, "hello", "g4", True, [OWNER, ANA, BOB])                          # re-listing must not revive Bob
        self.assertEqual(self.guest(BOB)["status"], "revoked")
        self.send(OWNER, "Door Stop", "g4", True, [OWNER, ANA, BOB])
        self.assertNotIn("g4", self.c.s["open_groups"])
        self.send(ANA, "hello", "g4", True, [OWNER, ANA, BOB, EVE])
        self.assertIsNone(self.guest(EVE))

    def test_cannot_see_members_or_too_many(self):
        self.send(OWNER, "Door Allow", "g5", True, None)
        self.assertEqual(self.c.s["guests"], {})
        self.assertTrue(any("can't see who is in this group" in s for s in self.sms("g5")))
        many = [OWNER] + ["+1555400%04d" % i for i in range(26)]
        self.send(OWNER, "Door Allow", "g6", True, many)
        self.assertEqual(self.c.s["guests"], {}); self.assertNotIn("g6", self.c.s["open_groups"])

    def test_owner_allow_in_a_1_to_1_does_nothing_special(self):
        self.send(OWNER, "Door Allow", "owner-thread", False, None)
        self.assertEqual(self.c.s["guests"], {})


class PlowRoster(unittest.TestCase):
    line = {"type": "agent", "relationship": "self", "line": {"uid": "ln", "provider_type": "imessage"}}
    def msg(self, who): return {"uid": "m", "direction": "inbound", "body": "q", "sender": {"type": "member", "uid": who[0], "provider_key": who[1]}}
    def member(self, uid, key): return {"type": "member", "uid": uid, "provider_key": key}

    def test_one_to_one_and_group_members(self):
        one = {"uid": "c", "participants": [self.line, self.member("a", ANA)]}
        r = PlowAPI.normalize(one, self.msg(("a", ANA)), "ln")
        self.assertFalse(r["is_group"]); self.assertEqual(r["members"], [ANA])
        grp = {"uid": "c", "participants": [self.line, self.member("a", ANA), self.member("o", OWNER)]}
        r = PlowAPI.normalize(grp, self.msg(("a", ANA)), "ln")
        self.assertTrue(r["is_group"]); self.assertEqual(sorted(r["members"]), sorted([ANA, OWNER]))

    def test_missing_identity_means_no_members(self):
        grp = {"uid": "c", "participants": [self.line, self.member("a", ANA), {"type": "member", "uid": "x"}]}
        self.assertIsNone(PlowAPI.normalize(grp, self.msg(("a", ANA)), "ln")["members"])


if __name__ == "__main__":
    unittest.main()
