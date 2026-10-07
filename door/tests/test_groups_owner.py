"""Groups, the way the owner wants them: she is still the owner there, Door introduces itself, and she can trust people from the group
(always confirmed in her private thread)."""
import unittest

from tests.test_join import ANA, BOB, EVE, OWNER, Base

G = [OWNER, ANA, BOB]


class OwnerInGroups(Base):
    def setUp(self):
        super().setUp()
        self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="door")
        self.c.s["settings"]["approval"] = "auto"

    def test_allow_introduces_door_in_the_owners_language(self):
        self.send(OWNER, "oi gente, vou ligar o assistente aqui", "g", True, G)
        self.send(OWNER, "Door Allow", "g", True, G)
        intro = self.sms("g")[-1]
        self.assertIn("Eu sou o Door", intro); self.assertIn("projeto door", intro); self.assertIn("passos arriscados", intro); self.assertNotIn("de a dona", intro)

    def test_the_owner_can_ask_and_give_tasks_inside_an_open_group(self):
        self.send(OWNER, "Door Allow", "g", True, G)
        self.send(OWNER, "Door, como funciona o deploy?", "g", True, G)
        self.send(OWNER, "Door, cria um arquivo NOTAS.md", "g", True, G)
        caps = [(r["capability"], r["thread_id"]) for r in self.c.s["requests"].values()]
        self.assertEqual(caps, [("ask", "g"), ("act", "g")])           # answered in the group, not in private

    def test_the_owner_talking_in_a_group_that_is_not_open_does_nothing(self):
        self.send(OWNER, "Door, cria um arquivo", "g", True, G)
        self.assertEqual(self.c.s["requests"], {})

    def test_trust_needs_the_private_yes_and_then_the_person_can_have_things_done(self):
        self.send(OWNER, "Door Allow", "g", True, G)
        self.send(OWNER, "Door Trust", "g", True, G)
        self.assertEqual({g["phone"]: g.get("level", "ask") for g in self.c.s["guests"].values() if not g.get("owner")}, {ANA: "ask", BOB: "ask"})
        ask = self.sms("owner-thread")[-1]; code = ask.split("YES ")[1][:4]
        self.assertIn(ANA, ask); self.assertIn(BOB, ask)
        self.send(ANA, "YES " + code, "g", True, G)                            # a guest cannot confirm it, in the group or anywhere
        self.send(ANA, "YES " + code)
        self.assertEqual(self.guest(ANA).get("level", "ask"), "ask")
        self.send(OWNER, "YES " + code, "owner-thread")
        self.assertEqual((self.guest(ANA)["level"], self.guest(BOB)["level"]), ("act", "act"))
        self.assertIn("can now ask me to do things", self.sms("g")[-1])
        self.send(ANA, "Door, add a footer to index.html", "g", True, G)               # plain words from a guest are still a question...
        self.send(ANA, "Door, do: add a footer to index.html", "g", True, G)          # ...and "Do:" makes it a task, now allowed
        self.assertEqual([r["capability"] for r in self.c.s["requests"].values() if r["guest_id"] == self.guest(ANA)["guest_id"]], ["act", "act"])

    def test_trust_one_person_by_number_and_refuse_strangers(self):
        self.send(OWNER, "Door Allow", "g", True, G)
        self.send(OWNER, "Door Trust " + EVE, "g", True, G)                     # not in this group
        self.assertIn("is not in that group", self.sms("owner-thread")[-1])
        self.send(OWNER, "Door Trust " + BOB.replace("+1", "+1 "), "g", True, G)
        code = self.sms("owner-thread")[-1].split("YES ")[1][:4]
        self.send(OWNER, "YES " + code, "owner-thread")
        self.assertEqual((self.guest(ANA).get("level", "ask"), self.guest(BOB)["level"]), ("ask", "act"))

    def test_a_trust_code_expires_and_no_cancels(self):
        self.send(OWNER, "Door Allow", "g", True, G); self.send(OWNER, "Door Trust", "g", True, G)
        code = self.sms("owner-thread")[-1].split("YES ")[1][:4]
        self.t += 601; self.send(OWNER, "YES " + code, "owner-thread")
        self.assertEqual(self.guest(ANA).get("level", "ask"), "ask")
        self.send(OWNER, "Door Trust", "g", True, G); code = self.sms("owner-thread")[-1].split("YES ")[1][:4]
        self.send(OWNER, "NO " + code, "owner-thread"); self.assertEqual(self.guest(ANA).get("level", "ask"), "ask")

    def test_guests_cannot_trust_anyone(self):
        self.send(OWNER, "Door Allow", "g", True, G)
        self.send(ANA, "Door Trust", "g", True, G); self.send(ANA, "Door Trust " + BOB, "g", True, G)
        self.assertEqual(self.c.s.get("trust_pending", {}), {})


if __name__ == "__main__":
    unittest.main()


class AppleIdMembers(Base):
    """iMessage people who use an email Apple ID instead of a phone number (found in the first real group test)."""
    def test_an_email_member_is_let_in_heard_and_can_be_trusted(self):
        self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="door"); self.c.s["settings"]["approval"] = "auto"
        ME = "Pablo.Friend@iCloud.com"; G2 = [OWNER, ME]
        self.send(OWNER, "Door Allow", "g", True, G2)
        self.assertEqual([g["phone"] for g in self.c.s["guests"].values()], ["pablo.friend@icloud.com"])
        rid = self.send(ME, "Door, what does this project do?", "g", True, G2)
        self.assertIsNotNone(rid)
        self.send(OWNER, "Door Trust pablo.friend@icloud.com", "g", True, G2)
        code = self.sms("owner-thread")[-1].split("YES ")[1][:4]
        self.send(OWNER, "YES " + code, "owner-thread")
        self.assertEqual(self.guest("pablo.friend@icloud.com")["level"], "act")

    def test_things_that_are_not_people_are_still_ignored(self):
        for who in ("not-an-address", "a@b", "@x.com", "x@@y.com"):
            self.assertIsNone(self.send(who, "hello"))
        self.assertEqual(self.c.s["guests"], {})


class QuietUnlessAddressed(Base):
    """In a group people talk to each other; Door answers only when it is spoken to."""
    def setUp(self):
        super().setUp(); self.c.s["settings"]["approval"] = "auto"; self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="door")
        self.send(OWNER, "Door Allow", "g", True, G)

    def n(self): return len(self.c.s["requests"])

    def test_chatting_among_people_gets_no_answer_and_no_cost(self):
        for who, text in ((ANA, "did you see the game?"), (BOB, "yes! how do I deploy this btw"), (OWNER, "I'll send the file tonight"),
                          (ANA, "I think the door is open"), (BOB, "doors are nice"), (ANA, "Door")):
            self.assertIsNone(self.send(who, text, "g", True, G))
        self.assertEqual(self.n(), 0)
        self.assertEqual([t for t in self.sms("g") if "Working" in t or "Got it" in t], [])

    def test_addressing_door_works_in_both_languages_and_with_at(self):
        for who, text in ((ANA, "Door, how do I deploy?"), (BOB, "@door where is the config?"), (ANA, "hey door: what is this project"),
                          (BOB, "oi Door, como instalo?"), (OWNER, "Door, summarize the README")):
            self.send(who, text, "g", True, G)
        self.assertEqual(self.n(), 5)

    def test_the_prefix_is_not_part_of_the_question(self):
        self.send(ANA, "Door, how do I deploy?", "g", True, G)
        self.assertEqual(next(iter(self.c.s["requests"].values()))["text"], "how do I deploy?")

    def test_owner_only_commands_from_a_guest_are_ignored_not_answered(self):
        for text in ("Door Allow", "Door Stop", "Door Trust"):
            self.assertIsNone(self.send(ANA, text, "g", True, G))
        self.assertEqual((self.n(), self.c.s.get("trust_pending", {})), (0, {}))
        self.assertIn("g", self.c.s["open_groups"])

    def test_the_intro_tells_people_how_to_talk_to_door_in_both_languages(self):
        self.assertIn('Start a message with "Door,"', self.sms("g")[-1])
        self.send(OWNER, "oi gente, vou ligar o assistente aqui", "g2", True, G); self.send(OWNER, "Door Allow", "g2", True, G)     # the group writes Portuguese
        self.assertIn('Comecem a mensagem com "Door,"', self.sms("g2")[-1])


class TrustedPeopleJustAsk(Base):
    """What happened in the first real group: a trusted friend wrote "DOOR: create a file test.md" and was told Door only answers questions."""
    def setUp(self):
        super().setUp(); self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="door"); self.c.s["settings"]["approval"] = "auto"
        self.send(OWNER, "Door Allow", "g", True, G)
        for g in self.c.s["guests"].values(): g["limits"]["max_open_requests"] = 10

    def kinds(self, who):
        return [r["capability"] for r in self.c.s["requests"].values() if r["guest_id"] == self.guest(who)["guest_id"]]

    def trust(self, who):
        self.guest(who)["level"] = "act"

    def test_a_trusted_guest_asking_for_a_change_gets_a_task_without_do(self):
        self.trust(ANA)
        for text in ("DOOR: create a file test.md", "Door, add a footer to index.html", "door, cria um arquivo NOTAS.md", "Door, please fix the login bug"):
            self.send(ANA, text, "g", True, G)
        self.assertEqual(self.kinds(ANA), ["act"] * 4)

    def test_questions_and_chat_from_a_trusted_guest_stay_questions(self):
        self.trust(ANA)
        for text in ("Door, how do I create a file?", "Door, where is the footer added?", "Door, thanks!", "Door, what changed?"):
            self.send(ANA, text, "g", True, G)
        self.assertEqual(self.kinds(ANA), ["ask"] * 4)

    def test_a_guest_without_tasks_is_never_given_one(self):
        self.send(BOB, "Door, create a file test.md", "g", True, G)
        self.assertEqual(self.kinds(BOB), ["ask"])

    def test_every_door_allow_introduces_door_again(self):
        first = [t for t in self.sms("g") if "Door" in t]
        self.send(OWNER, "Door Stop", "g", True, G); self.send(OWNER, "Door Allow", "g", True, G)
        self.assertTrue([t for t in self.sms("g") if "I'm Door" in t])


class GroupLanguage(Base):
    """What happened in the real group: the owner had written Portuguese in her private chat, so a group of English speakers got a Portuguese
    introduction after "Door Allow" and "Door Trust"."""
    def setUp(self):
        super().setUp(); self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="door")

    def test_a_group_is_english_until_people_write_something_else_in_it(self):
        self.c.s["owner_lang"] = "pt"                                              # the owner's private chat is Portuguese
        self.send(OWNER, "Door Allow", "g", True, G)
        self.assertIn("Hi! I'm Door", self.sms("g")[-1])
        self.send(OWNER, "Door Trust", "g", True, G); code = self.sms("owner-thread")[-1].split("YES ")[1][:4]
        self.send(OWNER, "YES " + code, "owner-thread")
        self.assertIn("can now ask me to do things", self.sms("g")[-1])           # the announcement in the group is English too

    def test_the_group_follows_what_is_written_in_it_not_what_the_owner_wrote_elsewhere(self):
        self.send(ANA, "DOOR: create a file test.md", "g", True, G)               # English, from a friend
        self.c.s["owner_lang"] = "pt"
        self.send(OWNER, "Door Allow", "g", True, G); self.assertIn("Hi! I'm Door", self.sms("g")[-1])
        self.send(BOB, "pessoal, alguém viu o relatório de ontem?", "g", True, G)  # now Portuguese
        self.send(OWNER, "Door Stop", "g", True, G); self.send(OWNER, "Door Allow", "g", True, G)
        self.assertIn("Oi! Eu sou o Door", self.sms("g")[-1])

    def test_commands_and_short_messages_do_not_change_the_language(self):
        self.send(OWNER, "Door Allow", "g", True, G); self.send(ANA, "ok!", "g", True, G); self.send(OWNER, "Door Trust", "g", True, G)
        self.assertEqual(self.c.s.get("group_lang", {}), {})

    def test_two_groups_keep_their_own_language(self):
        self.send(ANA, "pessoal, alguém viu o relatório de ontem?", "g", True, G); self.send(OWNER, "Door Allow", "g", True, G)
        self.send(ANA, "did anyone see yesterday's report yet?", "g9", True, G); self.send(OWNER, "Door Allow", "g9", True, G)
        self.assertIn("Oi! Eu sou o Door", self.sms("g")[-1]); self.assertIn("Hi! I'm Door", self.sms("g9")[-1])


class FriendExperience(Base):
    """The trusted friend in the real group: knowing what to say, asking politely, being told how to ask for a change."""
    def setUp(self):
        super().setUp(); self.c.s["summary"] = dict(self.c.s["summary"], act_agent="dev", alias="plow-agents"); self.c.s["settings"]["approval"] = "auto"
        self.send(OWNER, "Door Allow", "g", True, G)
        for g in self.c.s["guests"].values(): g["limits"]["max_open_requests"] = 10
        self.guest(ANA)["level"] = "act"

    def kinds(self, who): return [r["capability"] for r in self.c.s["requests"].values() if r["guest_id"] == self.guest(who)["guest_id"]]

    def test_help_says_what_each_person_can_do_and_costs_nothing(self):
        self.send(ANA, "Door, help", "g", True, G); self.assertIn("You can also ask me for changes", self.sms("g")[-1])
        self.send(BOB, "Door, what can you do?", "g", True, G); self.assertIn("the owner has to trust you first", self.sms("g")[-1])
        self.send(ANA, "pessoal, alguém viu o relatório de ontem?", "g", True, G)       # the group turns Portuguese
        self.send(BOB, "Door, ajuda", "g", True, G); self.assertIn("a dona precisa liberar você", self.sms("g")[-1])
        self.assertEqual(self.c.s["requests"], {})                                          # no request, no model call

    def test_asking_politely_is_still_a_task(self):
        for t in ("Door, can you create a file test.md?", "Door, could you please fix the README?", "Door, pode criar um arquivo notas.md?"):
            self.send(ANA, t, "g", True, G)
        self.send(ANA, "Door, can you explain the login?", "g", True, G)
        self.assertEqual(self.kinds(ANA), ["act", "act", "act", "ask"])
        self.send(BOB, "Door, can you create a file test.md?", "g", True, G); self.assertEqual(self.kinds(BOB), ["ask"])   # not trusted: a question

    def test_a_refused_question_tells_a_trusted_person_how_to_ask_for_a_change(self):
        rid = self.send(ANA, "Door, the test file please", "g", True, G)
        r = self.c.s["requests"][rid]; self.c._transition(r, "running")
        self.c._result(r, {"state": "completed", "reply": {"text": "I can only help with questions about this project.", "refused": True, "held": False}})
        self.assertIn('If you meant a change, ask for it like this: "Door, create a file notes.md".', self.sms("g")[-1])

    def test_messages_to_the_group_follow_the_group_language(self):
        self.send(ANA, "pessoal, alguém viu o relatório de ontem?", "g", True, G)
        self.send(ANA, "Door, cria um arquivo notas.md", "g", True, G)
        self.assertIn("Entendi. Vou fazer isso e conferir o resultado.", self.sms("g"))
        (r,) = [x for x in self.c.s["requests"].values()]
        self.c._note_actions(r, [{"id": "a1", "tool": "Bash", "summary": "Run: npm install", "at": 0}])
        self.assertIn("Esperando a aprovação de um passo.", self.sms("g"))
        step = [t for t in self.sms("owner-thread") if "wants to" in t or "quer:" in t][-1]
        self.assertIn(ANA, step)                                                              # the owner sees who is asking
