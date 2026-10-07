"""Settings changed from the cloud panel: the Mac checks them again, the risky ones wait for the owner's YES by text,
and the cloud never learns a folder path."""
import base64
import json
import unittest

from door.common import ulid
from door.door_link import to_cloud_command, to_panel_snapshot
from door.service import cycle, panel_command
from tests.test_act_cloud import SUMMARY, Base as CloudBase
from tests.test_local_ui import Base as MacBase

OWNER, THREAD = "+15550000001", "ot"


class OnTheMac(MacBase):
    def test_the_summary_that_leaves_the_mac_has_names_and_no_paths(self):
        s = self.host.summary()["summary"]["settings"]
        self.assertEqual([p["name"] for p in s["projects"]], ["p"])
        self.assertNotIn(str(self.root), json.dumps(self.host.summary()))

    def test_a_change_is_applied_checked_audited_and_refused_with_a_reason(self):
        out = self.host.change_settings({"op": "budget.set", "monthly": 17})
        self.assertEqual((out["ok"], out["applied"], out["settings"]["budget"]), (True, True, 17.0))
        self.assertEqual(self.host.holder.policy["limits"]["monthly_budget"], 17.0)
        out = self.host.change_settings({"op": "project.add", "path": str(self.root)})
        self.assertEqual((out["applied"], "git repository" in out["error"]), (False, True))
        self.assertEqual(self.host.change_settings("nope")["reason"], "bad_payload")
        events = [e for e in self.host.audit.rows() if e["event"] == "settings_changed"]
        self.assertEqual([e["detail"]["applied"] for e in events], [True, False])

    def test_tasks_can_be_chosen_by_project_name_and_a_new_model_restarts_door(self):
        self.assertFalse(self.host.change_settings({"op": "tasks.set", "enabled": True, "project_name": "nope"})["applied"])
        out = self.host.change_settings({"op": "tasks.set", "enabled": True, "project_name": "p", "bash": "off", "open_on_mac": "allow"})
        self.assertTrue(out["applied"]); self.assertEqual(out["settings"]["tasks"]["project_name"], "p")
        self.assertNotIn(str(self.root), json.dumps(out))
        import threading
        fired = threading.Event(); self.host.restart_hook = fired.set
        self.assertTrue(self.host.change_settings({"op": "model.set", "access": "anthropic"})["restarting"])
        self.assertTrue(fired.wait(4))
        fired.clear(); self.host.change_settings({"op": "budget.set", "monthly": 20}); self.assertFalse(fired.wait(2))      # other changes do not restart it


class InTheCloud(CloudBase):
    def setUp(self):
        super().setUp(); self.c.s["summary"]["settings"] = {"projects": [{"name": "app"}]}
    def owner(self, text): return self.c.receive(ulid(), OWNER, THREAD, text)
    def cmds(self): return [v for v in self.c.s["commands"].values() if v["op"] == "settings"]

    def test_low_risk_goes_straight_to_the_mac_and_risky_waits_for_yes(self):
        self.c.request_settings({"op": "budget.set", "monthly": 30})
        self.assertEqual(len(self.cmds()), 1); self.assertEqual(self.c.s["settings_result"]["state"], "sending")
        self.c.request_settings({"op": "project.add", "path": "/Users/you/code/site"})
        self.assertEqual(len(self.cmds()), 1)                                                           # not yet
        ask = self.texts(THREAD)[-1]; code = ask.split("YES ")[1][:4]
        self.assertIn("share the folder /Users/you/code/site", ask)
        snap = self.c.snapshot(); self.assertEqual(snap["settings_result"]["state"], "waiting"); self.assertNotIn(code, json.dumps(snap["settings_pending"]))
        self.owner("YES " + code)
        self.assertEqual(len(self.cmds()), 2); self.assertEqual(self.cmds()[1]["change"]["op"], "project.add")
        self.assertIsNone(self.c.snapshot()["settings_pending"])

    def test_no_and_wrong_codes_and_expiry_change_nothing(self):
        self.c.request_settings({"op": "tasks.set", "enabled": False}); code = self.texts(THREAD)[-1].split("YES ")[1][:4]
        self.owner("YES 0000" if code != "0000" else "YES 1111"); self.assertEqual(self.cmds(), [])
        self.owner("NO " + code); self.assertEqual((self.cmds(), self.c.s["settings_result"]["state"]), ([], "canceled"))
        self.c.request_settings({"op": "tasks.set", "enabled": False}); code = self.texts(THREAD)[-1].split("YES ")[1][:4]
        self.t += 601; self.owner("YES " + code); self.assertEqual((self.cmds(), self.c.s["settings_result"]["state"]), ([], "expired"))

    def test_a_guest_cannot_confirm_and_unknown_changes_are_refused(self):
        self.c.request_settings({"op": "project.remove", "name": "app"}); code = self.texts(THREAD)[-1].split("YES ")[1][:4]
        self.say("+15551110001", "YES " + code); self.assertEqual(self.cmds(), [])
        for bad in ({"op": "sudo"}, "x", None, {}):
            with self.assertRaises(ValueError): self.c.request_settings(bad)

    def test_the_owner_hears_it_in_portuguese_when_she_writes_in_portuguese(self):
        self.c.s["owner_lang"] = "pt"; self.c.request_settings({"op": "tasks.set", "enabled": True, "project_name": "app", "bash": "ask"})
        t = self.texts(THREAD)[-1]; self.assertIn("alguém no painel quer ligar tarefas no projeto app", t); self.assertIn("Responda YES", t)

    def test_the_command_is_forwarded_to_the_mac_and_the_answer_is_shown(self):
        class Relay:
            def __init__(s, out): s.out, s.argv = out, []
            def command(s, argv):
                s.argv.append(argv)
                return {"ok": True, "summary": dict(SUMMARY, settings={"projects": [{"name": "app"}]})} if "summary" in argv else s.out
            def ask(s, *a): return {"ok": True}
            def status(s, rid): return {"ok": True}
        class Hub:
            def rpc(self, *a): return {}
        class S:
            def messages(self, *a): return iter(())
            def send(self, *a): pass
        self.c.s["host_id"] = "h"; self.c.s["started_at"] = self.t
        self.c.request_settings({"op": "budget.set", "monthly": 30})
        ok = {"ok": True, "applied": True, "settings": {"projects": [{"name": "app"}], "budget": 30.0}}
        relay = Relay(ok); cycle(self.c, S(), relay, Hub(), None)
        argv = next(a for a in relay.argv if "settings" in a)
        self.assertEqual(json.loads(base64.b64decode(argv[argv.index("--payload") + 1])), {"op": "budget.set", "monthly": 30})
        self.assertEqual(self.c.s["settings_result"]["state"], "applied"); self.assertIn("projects", self.c.s["summary"]["settings"])
        self.assertEqual(self.cmds()[0]["done"], True)
        self.c.request_settings({"op": "budget.set", "monthly": 99})
        cycle(self.c, S(), Relay({"ok": True, "applied": False, "error": "The monthly budget must be between 1 and 10000 US dollars."}), Hub(), None)
        self.assertEqual(self.c.s["settings_result"]["state"], "refused"); self.assertIn("must be between", self.c.s["settings_result"]["error"])
        self.c.request_settings({"op": "budget.set", "monthly": 5})
        cycle(self.c, S(), Relay({"ok": False, "reason": "unknown_op"}), Hub(), None)               # an old Mac: refused once, not retried forever
        self.assertEqual((self.c.s["settings_result"]["state"], self.cmds()[-1]["done"]), ("refused", True))
        self.c.request_settings({"op": "budget.set", "monthly": 6})
        cycle(self.c, S(), Relay({"ok": False, "reason": "host_offline"}), Hub(), None)             # the daemon is down: it stays queued
        self.assertFalse(self.cmds()[-1]["done"])

    def test_the_panel_command_and_snapshot_carry_it(self):
        cmd = to_cloud_command({"id": "c1", "type": "settings", "change": {"op": "budget.set", "monthly": 12}})
        self.assertEqual((cmd["op"], cmd["change"]["monthly"]), ("settings.change", 12))
        panel_command(self.c, dict(cmd, request_id=None)); self.assertEqual(len(self.cmds()), 1)
        snap = to_panel_snapshot(self.c.snapshot())
        self.assertEqual(snap["settings_view"], {"projects": [{"name": "app"}]}); self.assertEqual(snap["settings_result"]["state"], "sending")


if __name__ == "__main__":
    unittest.main()
