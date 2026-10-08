"""Checks the "I am not a robot" handling, with stand-ins for the browser.

Nothing on this site shows such a box today - the refusals are 403s on the
postback with no widget at all - so this is for the case where that changes.
Which makes the important property not "does it solve a captcha" but "does it
stay completely out of the way when there is nothing to solve", and "does it
only ever click inside a challenge widget, never on the government form".

Run: python check_not_a_robot.py
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


class FakeElement:
    def __init__(self, src="", displayed=True):
        self._src = src
        self._displayed = displayed
        self.clicked = False
        self.rect = {"x": 100, "y": 200, "width": 30, "height": 30}

    def get_attribute(self, name):
        return self._src if name == "src" else None

    def is_displayed(self):
        return self._displayed

    def click(self):
        self.clicked = True


class FakeSwitch:
    def __init__(self):
        self.frames = []

    def frame(self, f):
        self.frames.append(f)

    def default_content(self):
        self.frames.append(None)


class FakeDriver:
    def __init__(self, iframes, boxes):
        self._iframes = iframes
        self._boxes = boxes
        self.switch_to = FakeSwitch()

    def find_elements(self, how, what):
        if what == "iframe":
            return self._iframes
        return self._boxes if self.switch_to.frames and self.switch_to.frames[-1] else []

    def execute_script(self, *a, **k):
        return 80

    def get_window_position(self):
        return {"x": 0, "y": 0}


run_autofill.log = lambda *a, **k: None
os_clicks = []
run_autofill._os_click = lambda driver, element: os_clicks.append(element) or True

# Nothing on the page: it must not touch anything.
driver = FakeDriver(iframes=[], boxes=[])
check("no widget, no action", run_autofill.click_not_a_robot_if_present(driver), False)
check("and nothing was clicked for real", os_clicks, [])

# An ordinary iframe on the real site is not a challenge.
site_frame = FakeElement(src="https://pptform.state.gov/help.aspx")
driver = FakeDriver(iframes=[site_frame], boxes=[FakeElement()])
check("an ordinary iframe is left alone",
      run_autofill.click_not_a_robot_if_present(driver), False)
check("really left alone", (site_frame.clicked, os_clicks), (False, []))

# A Turnstile frame: the box inside is clicked, and so is the frame for real.
box = FakeElement()
turnstile = FakeElement(src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x")
driver = FakeDriver(iframes=[turnstile], boxes=[box])
check("a Turnstile widget is answered",
      run_autofill.click_not_a_robot_if_present(driver), True)
check("the box was clicked in the browser", box.clicked, True)
check("and a real mouse click went to the widget", os_clicks, [turnstile])

# reCAPTCHA's anchor frame counts too.
os_clicks.clear()
box = FakeElement()
recaptcha = FakeElement(src="https://www.google.com/recaptcha/api2/anchor?k=x")
driver = FakeDriver(iframes=[recaptcha], boxes=[box])
check("a reCAPTCHA checkbox is answered",
      run_autofill.click_not_a_robot_if_present(driver), True)

# And the frame is always left, so the rest of the run is not stuck inside it.
check("it returns to the page afterwards", driver.switch_to.frames[-1], None)

print()
print("FAILED" if failures else "all checks passed")
sys.exit(1 if failures else 0)
