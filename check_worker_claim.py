"""Checks that two machines grabbing the same queued job never both run it.

Every worker polls one sheet and a sheet has no lock; _claim() writes the
machine's name, waits, and reads it back - only the last writer goes ahead.

Run: python check_worker_claim.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import worker_agent  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}\n     got  {got}\n     want {want}")
        failures.append(name)


class FakeSheet:
    """Holds the worker cell of one row; the shared truth both machines see."""
    def __init__(self):
        self.worker = ""

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def batchUpdate(self, spreadsheetId, body):
        for item in body["data"]:
            if item["range"].endswith("!H5"):
                self.worker = item["values"][0][0]
        return self

    def get(self, spreadsheetId, range):
        self.last = {"values": [[self.worker]]} if self.worker else {}
        return self

    def execute(self):
        return getattr(self, "last", {})


sheet = FakeSheet()
worker_agent._now = lambda: "now"

# Both machines write, then both read back (the race the claim exists for).
worker_agent.time.sleep = lambda s: None
writes = []


def as_machine(name):
    worker_agent.WORKER_ID = name
    worker_agent._update_row(sheet, 5, {"status": "running", "worker": name})


as_machine("CONTABO")
as_machine("OFFICE-PC")
results = {}
for name in ("CONTABO", "OFFICE-PC"):
    worker_agent.WORKER_ID = name
    worker_agent._update_row = lambda s, r, u: None   # already written above
    owner = sheet.spreadsheets().values().get(spreadsheetId="", range="Queue!H5").execute()["values"][0][0]
    results[name] = owner == name
check("two machines on the same job: exactly one goes ahead", sorted(results.values()), [False, True])

# _claim() itself, alone on the job
sheet = FakeSheet()
worker_agent._update_row = lambda s, r, u: s.batchUpdate("", {"data": [
    {"range": f"Queue!H{r}", "values": [[u["worker"]]]}]})
worker_agent.WORKER_ID = "OFFICE-PC"
check("a machine alone on a job takes it", worker_agent._claim(sheet, 5), True)

# _claim() when another machine wrote its name during the wait
sheet = FakeSheet()
worker_agent.time.sleep = lambda s: setattr(sheet, "worker", "CONTABO")
check("a machine that was overtaken during the wait leaves the job", worker_agent._claim(sheet, 5), False)

# --- taking turns: the idle machine that waited longest goes first ---
from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 10, 13, 21, 0, tzinfo=timezone.utc)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def ran(worker, minutes_ago):
    return ["id", "case:x", "done", ago(minutes_ago + 1), ago(minutes_ago), ago(minutes_ago - 5), "", worker]


three = [["CONTABO", ago(0.2), "idle", ""], ["OFFICE-PC", ago(0.3), "idle", ""], ["LAPTOP", ago(0.5), "idle", ""]]
history = [ran("CONTABO", 60), ran("OFFICE-PC", 30), ran("LAPTOP", 45)]
check("the machine whose last job is oldest goes next",
      worker_agent.whose_turn(history, three, NOW), "CONTABO")
check("  a machine that never ran a job goes before all of them",
      worker_agent.whose_turn(history, three + [["NEW-PC", ago(0.1), "idle", ""]], NOW), "NEW-PC")
check("  a busy machine is skipped",
      worker_agent.whose_turn(history, [["CONTABO", ago(0.2), "busy", "j"]] + three[1:], NOW), "LAPTOP")
check("  a machine not seen for minutes is skipped",
      worker_agent.whose_turn(history, [["CONTABO", ago(10), "idle", ""]] + three[1:], NOW), "LAPTOP")
check("  after it runs, the turn moves on",
      worker_agent.whose_turn(history + [ran("CONTABO", 1)], three, NOW), "LAPTOP")
check("  no machine online: nobody's turn", worker_agent.whose_turn(history, [], NOW), "")

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
