"""Checks the bot's patience and recovery on a page.

- wait_until_settled() waits out a postback and the "Loading..." overlay,
  pressing OK on any dialog on the way.
- click_next() turns a refused Next (validation dialog) into an error, and
  run_page() then fills the same page again - but not a page it has left.
- reveal_by_toggle() answers No and Yes again when Yes did not open the
  follow-up fields (spouse details, live 2026-10-13).

Run: python check_page_recovery.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import run_autofill  # noqa: E402
from selenium.common.exceptions import NoAlertPresentException  # noqa: E402

run_autofill.log = lambda *a, **k: None
run_autofill.pause_between_steps = lambda: None
run_autofill.pause_between_fields = lambda: None
run_autofill.check_for_block = lambda driver, context="": None

clock = {"t": 0.0}
time.time = lambda: clock["t"]
time.sleep = lambda s: clock.__setitem__("t", clock["t"] + s)

failures = []


def check(name, got, want):
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}\n     got  {got}\n     want {want}")
        failures.append(name)


class Alert:
    def __init__(self, page, text):
        self.page, self.text = page, text

    def accept(self):
        self.page.alerts.pop(0)


class SwitchTo:
    def __init__(self, page):
        self.page = page

    @property
    def alert(self):
        if not self.page.alerts:
            raise NoAlertPresentException()
        return Alert(self.page, self.page.alerts[0])


class Page:
    """Busy until `busy_until` (fake seconds); dialogs waiting in `alerts`."""
    def __init__(self, busy_until=0.0, alerts=()):
        self.busy_until, self.alerts = busy_until, list(alerts)
        self.switch_to = SwitchTo(self)

    def execute_script(self, script, *args):
        return clock["t"] >= self.busy_until


# --- settle ----------------------------------------------------------------
clock["t"] = 0.0
page = Page(busy_until=12)
check("waits for a 12s postback to finish", (run_autofill.wait_until_settled(page), clock["t"] >= 12), ([], True))
clock["t"] = 0.0
page = Page(alerts=["There is an error on the following field(s): Spouse Date of Birth"])
check("presses OK on a dialog and reports it",
      run_autofill.wait_until_settled(page), ["There is an error on the following field(s): Spouse Date of Birth"])
check("  the dialog is gone", page.alerts, [])
clock["t"] = 0.0
page = Page(busy_until=10_000)
run_autofill.wait_until_settled(page, timeout=20)
check("  a page that never settles is given up on, not waited on forever", clock["t"] < 30, True)

# --- refused Next -> the same page again -----------------------------------
run_autofill.click = lambda d, sel: None
refusing = Page(alerts=["There is an error on the following field(s): Required"])
try:
    run_autofill.click_next(refusing)
    got = "no error"
except run_autofill.FieldValidationError as e:
    got = str(e)
check("a Next the site refuses is an error, not a silent stay",
      got, "There is an error on the following field(s): Required")
check("  an ordinary Next is not", run_autofill.click_next(Page()), None)

on_page = {"here": True}
run_autofill.is_visible = lambda d, sel: on_page["here"] and sel == "#mine"
calls = []


def flaky_step(driver, d):
    calls.append(1)
    if len(calls) == 1:
        raise run_autofill.FieldValidationError("Required")


run_autofill.run_page(Page(), flaky_step, {}, "#mine")
check("a page that stopped on an error is filled again", len(calls), 2)

calls.clear()


def always_fails(driver, d):
    calls.append(1)
    raise run_autofill.FieldValidationError("Required")


try:
    run_autofill.run_page(Page(), always_fails, {}, "#mine")
    got = "no error"
except run_autofill.FieldValidationError:
    got = "raised"
check("  but not forever", (got, len(calls)), ("raised", run_autofill.PAGE_RETRIES + 1))

calls.clear()
on_page["here"] = False
try:
    run_autofill.run_page(Page(), always_fails, {}, "#mine")
    got = "no error"
except run_autofill.FieldValidationError:
    got = "raised"
check("  and not when the wizard has left the page", (got, len(calls)), ("raised", 1))

# --- spouse fields that did not open ---------------------------------------
clicked = []
opened = {"after": 3}   # the fields open on the third Yes
run_autofill.check = lambda d, sel: clicked.append(sel)
run_autofill.wait_visible = lambda d, sel, timeout=None: clicked.count("yes") >= opened["after"]
run_autofill.reveal_by_toggle(Page(), "yes", "no", "#spouse")
check("spouse fields that did not open: No, then Yes again, until they do",
      clicked, ["yes", "no", "yes", "no", "yes"])
clicked.clear()
opened["after"] = 1
run_autofill.reveal_by_toggle(Page(), "yes", "no", "#spouse")
check("  fields that opened at once: just Yes", clicked, ["yes"])

# --- other names: added once, and again if the list lost it (live, 2026-10-13) ---
class NamesPage(Page):
    def __init__(self, drop_first_add):
        super().__init__()
        self.listed, self.adds, self.drop = [], 0, drop_first_add

    def execute_script(self, script, *args):
        if "innerText" in script:
            return "Other names " + " ".join(self.listed)
        return True


def fake_click(d, sel):
    d.adds += 1
    if not (d.drop and d.adds == 1):
        d.listed.append("MOSHE KATZ")


run_autofill.fill_text = lambda d, sel, v: None
run_autofill.click = fake_click
names = NamesPage(drop_first_add=True)
run_autofill.add_other_name(names, "Moshe", "Katz")
check("a name the list lost is added again", (names.adds, names.listed), (2, ["MOSHE KATZ"]))
run_autofill.add_other_name(names, "Moshe", "Katz")
check("  a name already listed is not added twice (page filled again)", names.adds, 2)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
