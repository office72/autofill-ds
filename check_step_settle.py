"""Checks that the optional steps wait for the wizard to land on a page before
deciding whether they are on it.

The bug (live, 2026-10-13): the parents page loaded slowly, a one-shot check
missed it, the bot decided "not DS-11", skipped the step and clicked Next on
the empty parents page - the site answered "Required".

Run: python check_step_settle.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import run_autofill  # noqa: E402

run_autofill.STEP_ADVANCE_WAIT_SECONDS = 30
run_autofill.check_for_block = lambda driver, context="": None
run_autofill.log = lambda *a, **k: None

failures = []


def check(name, got, want):
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}\n     got  {got}\n     want {want}")
        failures.append(name)


class SlowPage:
    """Shows nothing for `delay` seconds of fake time, then `page`."""
    def __init__(self, page, delay):
        self.page, self.delay, self.now = page, delay, 0.0

    def visible(self, selector):
        return self.now >= self.delay and selector == self.page


clock = {"t": 0.0}
time.time = lambda: clock["t"]
driver = None


def run(page, delay):
    global driver
    driver = SlowPage(page, delay)
    clock["t"] = 0.0

    def sleep(s):
        clock["t"] += s
        driver.now = clock["t"]
    time.sleep = sleep
    run_autofill.is_visible = lambda d, sel: d.visible(sel)
    run_autofill.count = lambda d, sel: 1 if d.visible(sel) else 0
    filled = []
    run_autofill._fill_parent = lambda d, data, n: filled.append(n)
    run_autofill.check = lambda d, sel: None
    run_autofill.fill_text = lambda d, sel, v: None
    run_autofill.click_next = lambda d: filled.append("next")
    run_autofill.step_parent_spouse(driver, {"Ever Married?": "No"})
    return filled


PARENTS = "#PassportWizard_moreAboutYouStep_unknownParent1CheckBox"
check("a parents page that takes 10s is waited for and filled", run(PARENTS, 10), [1, 2, "next"])
check("a parents page already there is filled at once", run(PARENTS, 0), [1, 2, "next"])
check("on the Review page instead, the parents step stands aside",
      run("#PassportWizard_reviewStep_Label2", 5), [])
check("with no known page in time, it gives up waiting and stands aside", run("#nothing", 0), [])

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
