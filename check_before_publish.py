"""Refuses to let a publish break a machine that has not been updated.

publish_code.py is a deployment: the files it uploads are fetched by every
worker machine at the start of its next run. A machine's launcher.py decides
*which* files it fetches, and older launchers fetch only two of them - so code
that assumes a third file exists takes that machine down.

That happened for real. On 2026-10-03 run_autofill.py was published with a
plain `import api_backend`, a module an un-updated launcher never fetches. Six
queued jobs for a live client failed with exit code 1 the next morning, before
the bot could write Status=Running - so the sheet said "Ready", the Notes were
empty, no debug artifacts were uploaded, and the queue only said "exit code 1".
Nothing anywhere named the missing module.

So this checks the thing that failed: that the published bot still loads with
nothing but itself and sheets_backend beside it.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
# What the oldest launcher in the field fetches, and nothing more.
MINIMUM_FILES = ["run_autofill.py", "sheets_backend.py"]


def check() -> list:
    problems = []
    # The guard around the Review -> Fees stall, which only matters when a run
    # is already going wrong.
    for script in ("check_step_advance.py", "check_run_lock.py", "check_block_detection.py", "check_applicant_retry.py"):
        guard = subprocess.run([sys.executable, str(HERE / script)],
                               capture_output=True, text=True, cwd=HERE)
        if guard.returncode != 0:
            problems.append(f"{script} failed: "
                            + (guard.stdout or guard.stderr).strip().splitlines()[-1])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in MINIMUM_FILES:
            shutil.copy(HERE / name, tmp / name)
        # service_account.json is read at import time by sheets_backend; its
        # absence is a different failure and not what this is testing.
        account = HERE / "service_account.json"
        if account.exists():
            shutil.copy(account, tmp / "service_account.json")
        result = subprocess.run(
            [sys.executable, "-c",
             "import run_autofill as r; "
             "assert r._select_backend('1AbC').__name__ == 'sheets_backend'"],
            cwd=tmp, capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:]
            problems.append("run_autofill.py does not load with only "
                            f"{', '.join(MINIMUM_FILES)} present: {' '.join(tail)}")
    return problems


if __name__ == "__main__":
    found = check()
    for problem in found:
        print(f"REFUSING TO PUBLISH: {problem}")
    print("ok - an un-updated machine can still run the sheet flow" if not found else "")
    sys.exit(1 if found else 0)
