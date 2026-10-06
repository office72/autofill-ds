"""Checks that one run refuses to start on top of another.

Why this exists: every run begins by killing any Chrome that uses this bot's
profile, to clear leftovers from a crash - and that kill cannot tell a leftover
from a browser that is working right now. A second Run click while the first
run is going therefore destroyed the first one's session. It happened to a
live client (בלידן, 2026-10-06): three applicants, three "invalid session id",
three Status=Error, and nothing in the message pointing at the second click.

The other half matters just as much: a lock left behind by a run that crashed
must not wedge the machine forever.

Run: python check_run_lock.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import run_autofill  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}\n     got  {got}\n     want {want}")
        failures.append(name)


lock = run_autofill.RUN_LOCK_FILE
lock.parent.mkdir(parents=True, exist_ok=True)
lock.unlink(missing_ok=True)

# --- taking it, and giving it back ---------------------------------------
run_autofill._take_run_lock("sheet-123")
check("the lock file is created", lock.exists(), True)
owner = json.loads(lock.read_text(encoding="utf-8"))
check("it names this process", owner["pid"], os.getpid())
check("and the sheet it is for", owner["handle"], "sheet-123")

run_autofill._release_run_lock()
check("releasing removes it", lock.exists(), False)
run_autofill._release_run_lock()
check("releasing twice is harmless", lock.exists(), False)

# --- a live owner blocks a second run ------------------------------------
# A real process that will outlive the check, so the liveness test has
# something true to find.
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
try:
    lock.write_text(json.dumps({"pid": sleeper.pid, "handle": "other-sheet",
                                "started": "2026-10-06T10:53:00"}), encoding="utf-8")
    try:
        run_autofill._take_run_lock("my-sheet")
        check("a live run blocks a second one", "started anyway", "refused")
    except run_autofill.AnotherRunInProgress as e:
        message = str(e)
        check("a live run blocks a second one", True, True)
        check("the message says what to do", "Wait for it to finish" in message, True)
        check("and explains the damage it prevents", "kill the first" in message, True)
        check("and names the other run", "10:53" in message, True)
    check("the other run's lock is left alone",
          json.loads(lock.read_text(encoding="utf-8"))["pid"], sleeper.pid)
finally:
    sleeper.kill()
    sleeper.wait(timeout=10)

# --- a lock from a crashed run must not wedge the machine ----------------
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait(timeout=10)
time.sleep(0.5)
lock.write_text(json.dumps({"pid": dead.pid, "handle": "crashed-sheet",
                            "started": "2026-10-06T09:00:00"}), encoding="utf-8")
run_autofill._take_run_lock("my-sheet")
check("a stale lock is taken over", json.loads(lock.read_text(encoding="utf-8"))["pid"], os.getpid())
run_autofill._release_run_lock()

# --- and a corrupt lock must not be worse than no lock -------------------
lock.write_text("{not json at all", encoding="utf-8")
run_autofill._take_run_lock("my-sheet")
check("an unreadable lock is replaced", json.loads(lock.read_text(encoding="utf-8"))["pid"], os.getpid())
run_autofill._release_run_lock()

print()
print("FAILED" if failures else "all checks passed")
sys.exit(1 if failures else 0)
