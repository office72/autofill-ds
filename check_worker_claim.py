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

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
