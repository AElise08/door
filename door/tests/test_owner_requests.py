"""The owner can simply write to their own agent: questions get answers, things to do get done. No command list in the way."""
import unittest

from door.common import ulid
from tests.test_act_cloud import ANA, Base

OWNER, THREAD = "+15550000001", "ot"


class OwnerRequests(Base):
    def owner(self, text): return self.c.receive(ulid(), OWNER, THREAD, text)
    def requests(self): return list(self.c.s["requests"].values())

    def test_a_plain_instruction_becomes_a_task_with_a_card_and_no_self_approval(self):
        self.owner("add a footer to index.html")
        (r,) = self.requests()
        self.assertEqual((r["capability"], r["agent_alias"]), ("act", "dev"))
        self.assertTrue(self.c.s["guests"][r["guest_id"]]["owner"])
        from door.common import ULID_RE
        self.assertTrue(ULID_RE.fullmatch(r["guest_id"]), "the Mac rejects any other id")
        self.assertNotEqual(r["state"], "waitingApproval")                                    # the owner does not approve their own request
        self.assertEqual(len(self.jobs("card.add")), 1)
        self.assertEqual(self.jobs("card.add")[0]["owner"], "owner")              # shown as "You" on the board, not as a guest
        self.assertFalse([t for t in self.texts(THREAD) if "Commands:" in t])

    def test_a_question_is_a_question_in_english_or_portuguese(self):
        for t in ("How does pairing work?", "como funciona o pareamento", "what files are there", "is there a README?"):
            self.owner(t)
        self.assertEqual({r["capability"] for r in self.requests()}, {"ask"})
        self.assertEqual(self.jobs("card.add"), [])

    def test_do_prefix_is_always_a_task(self):
        self.owner("Do: what is wrong with the footer? fix it")
        self.assertEqual(self.requests()[0]["capability"], "act")

    def test_without_a_task_agent_it_says_how_instead_of_listing_commands(self):
        self.c.s["summary"]["act_agent"] = None
        self.owner("check the project")
        self.assertEqual(self.requests(), [])
        last = self.texts(THREAD)[-1]
        self.assertIn("answer questions", last); self.assertNotIn("Commands:", last)

    def test_commands_and_help_still_work(self):
        self.owner("DOOR GUESTS"); self.assertIn("Ana", self.texts(THREAD)[-1])
        self.owner("help"); self.assertIn("Just write to me", self.texts(THREAD)[-1])
        self.assertEqual(self.requests(), [])

    def test_the_owner_is_not_a_guest_in_lists_the_panel_or_by_name(self):
        self.owner("add a footer")
        self.assertEqual([g for g in self.c.snapshot()["guests"] if g.get("owner")], [])
        self.owner("DOOR GUESTS"); self.assertNotIn("You", self.texts(THREAD)[-1])
        self.owner("Door Revoke You"); self.assertEqual(self.c._owner_guest()["status"], "active")

    def test_a_guest_does_not_inherit_owner_powers(self):
        self.say(ANA, "add a footer to index.html")          # plain text from a guest is only ever a question
        self.say(ANA, "Do: add a footer")                     # and tasks need the act level
        self.assertEqual({r["capability"] for r in self.requests() if r["guest_id"] == self.ana}, {"ask"})
        self.assertEqual(self.c.s["guests"][self.ana].get("level", "ask"), "ask")


if __name__ == "__main__":
    unittest.main()


class Upgrade(Base):
    def test_an_owner_record_from_the_earlier_build_is_replaced_not_reused(self):
        self.c.s["guests"]["owner"] = dict(guest_id="owner", phone=OWNER, display_name="You", status="active", owner=True, expires_at=2 ** 40,
                                           level="act", approval="auto", limits={"daily_requests": 500, "daily_tokens": 4000000, "max_open_requests": 3})
        self.c.receive(ulid(), OWNER, THREAD, "add a footer")
        from door.common import ULID_RE
        (r,) = self.c.s["requests"].values()
        self.assertTrue(ULID_RE.fullmatch(r["guest_id"]))
        self.assertNotIn("owner", self.c.s["guests"])


class HostRejections(Base):
    def test_a_blocked_export_tells_the_guest_why_and_the_owner_what_to_do(self):
        rid = self.say(ANA, "What does the README say?")
        r = self.c.s["requests"][rid]
        if r["state"] == "waitingApproval": self.c._decide(r, "approve", "test", r["text_hash"])
        class Blocked:
            def ask(self, *a): return {"ok": False, "state": "rejected", "reason": "export_secrets"}
            def status(self, rid): return {"ok": True}
            def command(self, argv): return {"ok": True}
        self.c.dispatch(Blocked())
        self.assertEqual(self.c.s["requests"][rid]["state"], "canceled")
        self.assertIn("safety check", self.texts("t-" + ANA)[-1])
        self.assertIn("door-host audit", self.texts("ot")[-1])
        before = len(self.texts("ot")); self.say(ANA, "And the license?"); self.c.dispatch(Blocked())
        self.assertEqual(len(self.texts("ot")), before)          # the owner is told once a day, not once per question


class OwnerStepMessages(Base):
    def test_the_owner_is_asked_in_the_second_person_and_not_told_they_are_being_waited_for(self):
        self.owner = lambda text: self.c.receive(ulid(), OWNER, THREAD, text)
        self.owner("create a notes file")
        (r,) = self.c.s["requests"].values()
        self.c._note_actions(r, [{"id": "a1", "tool": "Bash", "summary": "Write the file NOTES.md (3 lines)", "at": 0}])
        out = self.texts(THREAD)
        step = [t for t in out if "wants to" in t][0]
        self.assertIn("Your task wants to: Write the file NOTES.md", step); self.assertNotIn("You's", step); self.assertNotIn("127.0.0.1", step)
        self.assertFalse([t for t in out if "Waiting for the owner" in t])
        self.assertFalse([t for t in self.texts(r["thread_id"]) if "Waiting for the owner" in t])
