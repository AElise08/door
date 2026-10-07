"""Replies read well on a phone: the exact reply that came out wrong in the first real task test is the fixture."""
import unittest

from door.replytext import clip, lang, plain, task_reply

REAL = ('Dei uma olhada no projeto "door" (o repositório se chama `plow-agents`). Não fiz nenhuma alteração. Também não executei os testes.\n\n'
        '- **O que é:** uma CLI em Python, só com a biblioteca padrão, em `bin/plow-agents`. Ela cobre o ciclo de credenciais (`login`, `lines`, '
        '`mint`, `revoke`) e os comandos de imagem.\n- **Arquivos:** além da CLI, há `compose.example.yml`, o `README.md` com o passo a passo '
        '(login, Dockerfile, build, push, deploy) e o `REVIEW.md` com a política de revisão.\n- **Notas:** ' + "Nada mais a dizer aqui. " * 90)
RUN = {"summary": REAL, "changed_files": [], "proof": [], "branch": "door/x1", "error": None}


class PhoneReplies(unittest.TestCase):
    def test_the_real_reply_that_looked_wrong(self):
        t = task_reply("Acessa o claude e verifica o projeto door", RUN, "no_changes", "", 1500)
        self.assertTrue(t.startswith("Dei uma olhada"))                         # the agent speaks first, not a Door sentence in another language
        self.assertNotIn("I did not change", t)
        self.assertTrue(t.endswith("(Door: nada no projeto foi alterado.)"))     # Door's own line, last, in Portuguese
        for raw in ("**", "`", "- **"): self.assertNotIn(raw, t)                 # no Markdown symbols on a phone
        self.assertIn("\n• O que é:", t)                                          # the list is still a list
        self.assertLessEqual(len(t), 1500)
        body = t.rsplit("\n\n", 1)[0]
        self.assertTrue(body.endswith("…") and not body[:-2].endswith(" N"))      # cut at a sentence, never mid-word

    def test_english_requests_get_english_status_and_verified_lists_proof(self):
        run = dict(RUN, summary="I added **NOTES.md**.", changed_files=["NOTES.md"], proof=[{"cmd": "test -f NOTES.md", "rc": 0}])
        t = task_reply("create a notes file", run, "verified", "", 1500)
        self.assertEqual(t, "I added NOTES.md.\n\nDoor checked it: changed NOTES.md; checks passed: test -f NOTES.md ok. Saved on branch door/x1 for the owner.")
        t = task_reply("create a notes file", dict(run, proof=[{"cmd": "pytest", "rc": 1}]), "failed_checks", "", 1500)
        self.assertIn("did NOT pass (pytest FAILED)", t)

    def test_helpers(self):
        self.assertEqual(lang("what does this do"), "en"); self.assertEqual(lang("o que esse projeto faz"), "pt")
        self.assertEqual(plain("# Title\n**bold** and `code` and [site](https://x.y)"), "Title\nbold and code and site (https://x.y)")
        self.assertEqual(clip("short", 10), "short")
        self.assertEqual(clip("One sentence here. Another sentence that is long.", 30), "One sentence here. …")
        self.assertNotIn("supercalifragil", clip("word " * 5 + "supercalifragilistic", 30))


if __name__ == "__main__":
    unittest.main()


class OwnerMessages(unittest.TestCase):
    def test_the_real_reply_to_the_owner_that_read_badly(self):
        run = {"summary": "Criei o Door.md com uma explicação curta do que o Door é e do que ele faz neste projeto, a partir do README.", "changed_files": ["Door.md"],
               "proof": [], "branch": "door/n4k7", "error": None}
        t = task_reply("Hi, create a file called Door.md and explain u", run, "unverified", "the request is truncated, so the deliverable is unclear.", 1500, to_owner=True)
        self.assertIn("Dá uma olhada na branch door/n4k7", t)            # the language of what the agent wrote, and spoken to the owner
        self.assertNotIn("The owner will", t); self.assertNotIn("..", t)
        t2 = task_reply("create a notes file", {"summary": "I added NOTES.md with the notes.", "changed_files": ["NOTES.md"], "proof": [], "branch": "door/x", "error": None},
                        "unverified", "", 1500, to_owner=True)
        self.assertIn("Take a look at branch door/x", t2)
        g = task_reply("create a notes file", {"summary": "I added NOTES.md with the notes.", "changed_files": ["NOTES.md"], "proof": [], "branch": "door/x", "error": None},
                       "unverified", "", 1500)
        self.assertIn("The owner will look at branch door/x", g)         # a guest is still told the owner will look


class StepMessages(unittest.TestCase):
    def test_a_file_being_written_is_described_not_dumped(self):
        from door.act import _describe_command
        self.assertEqual(_describe_command("cat > Door.md <<'EOF'\n# Door\nline\nmore\nEOF"), "Write the file Door.md (3 lines)")
        self.assertTrue(_describe_command("npm install\nnpm test").startswith("Run: npm install … (1 more lines)"))
        self.assertEqual(_describe_command("git status"), "Run: git status")
        self.assertLessEqual(len(_describe_command("echo " + "x" * 500)), 210)
