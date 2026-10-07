"""Checks the step-advance guard, with a stand-in for the browser.

The bug this exists for: on 2026-10-05 the bot clicked Next on the Review page,
the site silently did not advance, and the bot then looked for fee controls on
what was still the Review page. It reported "None of the passport book options
exist on this Fees page" - which reads as "the site renamed something" and sent
the investigation to the wrong place for an hour.

It happened again on 2026-10-07, one step earlier: About You -> Address, two
applicants of a live client, same silent non-advance, same misleading timeout
naming a field. So the guard is general now - advance_to() takes whichever
step is expected - and this checks the decision rather than any one page.

No browser here. A fake driver is enough, because what has to be right is the
decision: notice the page did not arrive, click again, and if it still has not,
say *that* rather than blaming the controls that were never on screen.

Run: python check_fees_guard.py
"""
import sys
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


class FakeDriver:
    """Shows the Review page until `arrives_after` Next clicks have happened."""

    def __init__(self, arrives_after):
        self.arrives_after = arrives_after
        self.next_clicks = 0
        self.title = "Passport Application System"
        self.page_source = "<html>review</html>"

    @property
    def on_fees(self):
        return self.next_clicks >= self.arrives_after


def install_fakes(driver):
    """Replaces exactly the four things the guard touches."""
    run_autofill.is_visible = lambda d, selector: d.on_fees
    run_autofill.check_for_block = lambda d, context="": None
    run_autofill.pause_between_steps = lambda: None

    def click_next(d):
        d.next_clicks += 1
    run_autofill.click_next = click_next
    run_autofill.log = lambda *a, **k: None


original = (run_autofill.is_visible, run_autofill.check_for_block,
            run_autofill.pause_between_steps, run_autofill.click_next, run_autofill.log)

# Already there: no clicking at all.
driver = FakeDriver(arrives_after=0)
install_fakes(driver)
run_autofill.advance_to(driver, ["#fee"], "the Fees page")
check("already on Fees - does not touch anything", driver.next_clicks, 0)

# The real case: one more Next and it appears.
driver = FakeDriver(arrives_after=1)
run_autofill.advance_to(driver, ["#fee"], "the Fees page")
check("a stalled page is clicked again and arrives", driver.next_clicks, 1)

# Still nothing after every attempt: the error must name the real problem.
driver = FakeDriver(arrives_after=99)
try:
    run_autofill.advance_to(driver, ["#fee"], "the Fees page", attempts=3)
    check("gives up with a clear error", "no error raised", "SeleniumTimeout")
except run_autofill.SeleniumTimeout as e:
    message = str(e)
    check("gives up after the attempts", driver.next_clicks, 3)
    check("and says the page never arrived", "never reached the Fees page" in message, True)
    check("and names what is on screen instead",
          "Passport Application System" in message, True)
    check("and does not blame the fee controls",
          "passport book options" in message.lower(), False)

# A block while waiting must surface as a block, not as "no fee options".
driver = FakeDriver(arrives_after=99)


def blocked(d, context=""):
    raise run_autofill.BotBlockedError("Just a moment...")


run_autofill.check_for_block = blocked
try:
    run_autofill.advance_to(driver, ["#fee"], "the Fees page")
    check("a block while waiting is raised as a block", "no error", "BotBlockedError")
except run_autofill.BotBlockedError:
    check("a block while waiting is raised as a block", True, True)


# --- the guard must be able to re-click whatever moves *this* step on ------
# The transition into the Next Steps page is driven by Finish, not Next, and
# clicking the wrong button there would do nothing at all.
finishes = []


def click_finish(d):
    finishes.append(1)
    d.next_clicks += 1


driver = FakeDriver(arrives_after=1)
run_autofill.is_visible = lambda d, selector: d.on_fees
run_autofill.check_for_block = lambda d, context="": None
run_autofill.pause_between_steps = lambda: None
run_autofill.log = lambda *a, **k: None
run_autofill.advance_to(driver, ["#confirm"], "the Next Steps page", click=click_finish)
check("it clicks Finish when told to", (len(finishes), driver.next_clicks), (1, 1))

(run_autofill.is_visible, run_autofill.check_for_block, run_autofill.pause_between_steps,
 run_autofill.click_next, run_autofill.log) = original

print()
print("FAILED" if failures else "all checks passed")
sys.exit(1 if failures else 0)
