"""Checks that a challenge is waited out and a block is not.

The run this exists for (2026-10-07): a run was abandoned on a Cloudflare
challenge that had already cleared by the next line of code - the error quoted
"Passport Application System", the real site's own title, as the thing that
looked like a block page, because the title was read once to match and a
second time to write the message. Two different responses were being given to
one response: give up.

A challenge is Cloudflare deciding; it clears by itself and waiting is the
whole point of undetected-chromedriver. A block is the door shut, and more
patience there only makes the next attempt worse.

Run: python check_block_detection.py
"""
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


class FakePage:
    """Shows `pages` in order, one per read, the last one repeating."""

    def __init__(self, pages):
        self.pages = pages
        self.reads = 0

    def _current(self):
        page = self.pages[min(self.reads, len(self.pages) - 1)]
        self.reads += 1
        return page

    @property
    def title(self):
        self._read = self._current()
        return self._read[0]

    @property
    def page_source(self):
        return self._read[1]


SITE = ("Passport Application System", "<html>the wizard</html>")
CHALLENGE = ("Just a moment...", "<html>Enable JavaScript and cookies to continue</html>")
BLOCKED = ("Attention Required! | Cloudflare", "<html>Sorry, you have been blocked</html>")

run_autofill.log = lambda *a, **k: None
run_autofill._record_block = lambda context, detail: recorded.append((context, detail))
recorded = []
run_autofill.CHALLENGE_WAIT_SECONDS = 9
original_sleep = time.sleep
time.sleep = lambda s: None          # the waiting itself is not what is being tested

# A normal page is simply not a block.
run_autofill.check_for_block(FakePage([SITE]), context="t")
check("the site itself passes", recorded, [])

# The real case: a challenge that clears.
page = FakePage([CHALLENGE, CHALLENGE, SITE])
run_autofill.check_for_block(page, context="initial page load")
check("a challenge that clears is waited out, not raised", recorded, [])

# A challenge that never clears has to end the run eventually.
recorded.clear()
try:
    run_autofill.check_for_block(FakePage([CHALLENGE]), context="t")
    check("a challenge that never clears is raised", "no error", "BotBlockedError")
except run_autofill.BotBlockedError as e:
    check("a challenge that never clears is raised", "did not clear" in str(e), True)
    check("and it is counted", len(recorded), 1)
    check("and the message says which knob to turn",
          "AUTOFILL_CHALLENGE_WAIT" in str(e), True)

# A hard block must not be waited on at all.
recorded.clear()
start = len(recorded)
try:
    run_autofill.check_for_block(FakePage([BLOCKED]), context="t")
    check("a hard block is raised at once", "no error", "BotBlockedError")
except run_autofill.BotBlockedError as e:
    check("a hard block is raised at once", "Waiting will not help" in str(e), True)
    check("and it is counted", len(recorded), 1)

# A challenge that turns into a block stops being waited on.
recorded.clear()
try:
    run_autofill.check_for_block(FakePage([CHALLENGE, BLOCKED]), context="t")
    check("a challenge that becomes a block stops", "no error", "BotBlockedError")
except run_autofill.BotBlockedError as e:
    check("a challenge that becomes a block stops", "became a block" in str(e), True)

# The site's own wording must not be mistaken for Cloudflare's. "ray id"
# appears on challenge pages and block pages alike, so on its own it decides
# nothing.
recorded.clear()
run_autofill.check_for_block(FakePage([("Passport Application System",
                                        "<html>Ray ID: 9a2b3c</html>")]), context="t")
check("a ray id alone is not a block", recorded, [])


# --- a challenge mid-run gets the box ticked, not just waited on ---------
# This is the rescue a person performed by hand on Contabo (2026-10-08): the
# challenge appeared in the middle of a run, the box was ticked, and the run
# carried on. It should not depend on somebody watching the screen.
ticked = []
run_autofill.click_not_a_robot_if_present = lambda driver: ticked.append(1) or True
recorded.clear()
run_autofill.check_for_block(FakePage([CHALLENGE, CHALLENGE, SITE]), context="mid-run")
check("a mid-run challenge gets the box ticked", len(ticked), 1)
check("and the run still carries on when it clears", recorded, [])

ticked.clear()
run_autofill.click_not_a_robot_if_present = lambda driver: False
run_autofill.check_for_block(FakePage([SITE]), context="t")
check("no challenge, no clicking", ticked, [])

time.sleep = original_sleep
print()
print("FAILED" if failures else "all checks passed")
sys.exit(1 if failures else 0)
