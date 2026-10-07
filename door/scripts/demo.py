#!/usr/bin/env python3
"""Demo agent: plays the cloud agent against a running panel, with canned answers (no Mac, no model, no SMS).

  DOOR_AGENT_TOKEN=<panel agent token> .venv/bin/python scripts/demo.py http://127.0.0.1:9630

Create a chat link in the panel, open it, write a question, approve it in the panel, and the canned answer appears.
"""
import os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from door.cloud import Cloud                    # noqa: E402
from door.common import now                     # noqa: E402
from door.door_link import DoorLink             # noqa: E402
from door.service import cycle                  # noqa: E402

SUMMARY = {"alias": "desk", "description": "demo", "max_capability": "ask", "boss": False,
           "agents": [{"alias": "desk", "description": "demo"}],
           "limits": {"max_output_tokens": 4000, "max_turn_tokens": 200000, "guest_daily_requests": 10,
                      "guest_daily_tokens": 400000, "monthly_budget": 50.0, "currency": "USD"}}


class NoSMS:
    def messages(self, *a): return iter(())
    def send(self, *a): pass


def main():
    url, token = sys.argv[1], os.environ["DOOR_AGENT_TOKEN"]
    tmp = tempfile.mkdtemp(prefix="door-demo-")
    cloud = Cloud(Path(tmp) / "demo.db", "demo", SUMMARY, url)
    cloud.set_plan("active", now() + 86400 * 30)
    cloud.s["started_at"] = now()
    link = DoorLink(url, token, local=url.startswith("http://127.0.0.1"))
    pending = {}
    for title, col, u, i in (("Write the onboarding guide", "todo", False, True), ("Fix the signup bug", "doing", True, True), ("Rename the settings page", "review", True, False), ("Add a footer", "done", False, False)):
        try:
            link.card({"op": "card.add", "owner": "owner", "title": title, "column": col, "request_id": None})
        except OSError:
            pass
    print("demo agent running; Ctrl+C to stop")
    while True:
        try:
            cycle(cloud, NoSMS(), None, link, "line")
            for r in cloud.s["requests"].values():
                if r["state"] == "queued":
                    cloud._transition(r, "running"); pending[r["request_id"]] = time.time()
                elif r["state"] == "running" and time.time() - pending.get(r["request_id"], 0) > 2:
                    cloud._result(r, {"state": "completed", "reply": {"held": False, "text":
                        "(demo) In a real setup an isolated agent would read your project and answer here. You asked: " + r["text"][:200]}})
            cloud._save()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("cycle:", type(e).__name__)
        time.sleep(1)


if __name__ == "__main__":
    main()
