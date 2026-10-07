"""The owner hands out access by texting the agent; only question-level access can be created that way."""
import tempfile
import unittest
from pathlib import Path

from door.cloud import Cloud
from door.common import now, ulid
from door.service import cycle

OWNER = "+15550000001"
SUMMARY = {"alias": "dev", "description": "", "max_capability": "ask", "act_agent": "dev",
           "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 100, "guest_daily_tokens": 10**7, "monthly_budget": 50.0, "currency": "USD"}}


class Hub:
    def __init__(self): self.calls = []
    def rpc(self, *a, **k): return {}
    def inbox(self): return []
    def ack_inbox(self, ids): pass
    def chat(self, *a): pass
    def card(self, job): self.calls.append(("card", job["op"]))
    def create_link(self, job): self.calls.append(("link", job["name"], job["days"], job["ttl_days"])); return "/c/" + "ab" * 24
    def signin(self): self.calls.append(("signin",)); return "/signin/" + "cd" * 24


class SMS:
    def messages(self, *a): return iter(())
    def send(self, *a): pass


class Owner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = now()
        self.c = Cloud(Path(self.tmp.name) / "c.db", "o", dict(SUMMARY), "https://door.example", clock=lambda: self.t)
        self.c.set_plan("active", self.t + 86400 * 30); self.c.s.update(owner_phone=OWNER, owner_thread="ot", started_at=self.t)
        self.hub = Hub()

    def tearDown(self): self.tmp.cleanup()
    def owner(self, text, phone=OWNER, thread="ot"): self.c.receive(ulid(), phone, thread, text)
    def last(self): return sorted((x for x in self.c.s["outbox"].values() if x["thread"] == "ot"), key=lambda x: x["created_at"])[-1]["text"]
    def cycle(self): cycle(self.c, SMS(), None, self.hub, "line")

    def test_invite_by_text_gives_a_code_that_works(self):
        self.owner("Door Invite Ana")
        code = self.c.s["invites"][next(iter(self.c.s["invites"]))]["code"]
        self.assertIn(code, self.last()); self.assertIn("Door Join: " + code, self.last()); self.assertEqual(next(iter(self.c.s["invites"].values()))["name"], "Ana")
        self.c.receive(ulid(), "+15551110001", "t1", "Door Join: " + code)
        g = [g for g in self.c.s["guests"].values()][0]
        self.assertEqual((g["display_name"], g.get("level", "ask")), ("Ana", "ask"))                    # question-level only
        self.owner("door invite")                                                                      # a name is optional; used codes are cleaned up
        self.assertEqual([i["name"] for i in self.c.s["invites"].values()], [""])

    def test_link_by_text_goes_through_the_panel_and_the_url_comes_back_by_text(self):
        self.owner("Door Link Ana")
        self.assertEqual(self.c.s["panel_jobs"][0]["op"], "link.create")
        self.cycle()
        self.assertEqual(self.hub.calls, [("link", "Ana", 30, 7)]); self.assertEqual(self.c.s["panel_jobs"], [])
        msg = self.last(); self.assertIn("https://door.example/c/" + "ab" * 24, msg); self.assertIn("Link for Ana", msg)

    def test_panel_sign_in_link_by_text(self):
        self.owner("Door Panel"); self.cycle()
        self.assertIn("https://door.example/signin/" + "cd" * 24, self.last()); self.assertIn("10 minutes", self.last())

    def test_list_and_revoke(self):
        self.c.add_guest("+15551110001", "Ana"); self.c.add_guest("+15551110002", "Bob")
        self.owner("Door Guests"); self.assertIn("Ana (active)", self.last()); self.assertIn("Bob (active)", self.last())
        self.owner("Door Revoke ana")
        self.assertEqual([g["status"] for g in self.c.s["guests"].values() if g["display_name"] == "Ana"], ["revoked"])
        self.assertIn("no longer has access", self.last())
        self.owner("Door Revoke Nobody"); self.assertIn("found 0 guests", self.last())
        self.c.add_guest("+15551110003", "Bob"); self.owner("Door Revoke Bob"); self.assertIn("found 2 guests", self.last())      # ambiguous: do nothing
        self.assertEqual(sorted(g["status"] for g in self.c.s["guests"].values() if g["display_name"] == "Bob"), ["active", "active"])
        self.owner("Door Revoke"); self.assertIn("Say who", self.last())

    def test_only_the_owner_in_their_own_chat_can_do_any_of_it(self):
        for who, thread in (("+15559990000", "x"), ("+15551110001", "g"), (OWNER, "some-group")):
            self.owner("Door Link Eve", phone=who, thread=thread); self.owner("Door Invite Eve", phone=who, thread=thread); self.owner("Door Panel", phone=who, thread=thread)
        self.assertEqual((self.c.s["panel_jobs"], self.c.s["invites"]), ([], {}))

    def test_tasks_cannot_be_granted_by_text(self):
        gid = self.c.add_guest("+15551110001", "Ana")
        for text in ("Door Level Ana act", "Door Allow tasks Ana", "Door Task Ana", "Door Trust Ana"):
            self.owner(text)
            self.assertIn("Letting someone run tasks is only done in the panel", self.last(), text)
        self.owner("Door Invite Ana act")                                                              # just an invite for a person called "Ana act"
        self.assertEqual(self.c.s["guests"][gid].get("level", "ask"), "ask")
        for g in self.c.s["guests"].values(): self.assertEqual(g.get("level", "ask"), "ask")

    def test_invite_name_is_data_not_a_command(self):
        self.owner("Door Invite <script>alert(1)</script>")
        self.owner("Door Link " + "x" * 61); self.assertEqual(self.c.s["panel_jobs"], [])               # names are capped at 60
        self.owner("Door Link a\nDoor Pause"); self.assertFalse(self.c.s["paused"])


if __name__ == "__main__":
    unittest.main()
