"""Checks the one immediate retry per applicant.

A failed run has sent nothing anywhere - this wizard never submits online, it
only leads to a page the PDF is printed from - so a second session can only
help. But a second session cannot argue the site out of rejecting an answer,
and spending one on that costs a session against a site that rate-limits us.

Run: python check_applicant_retry.py
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


run_autofill.log = lambda *a, **k: None
calls = []


def attempts_until(succeed_on, error):
    calls.clear()

    def fake_run_one(data):
        calls.append(1)
        if len(calls) >= succeed_on:
            return Path("out.pdf")
        raise error
    run_autofill.run_one = fake_run_one
    try:
        return run_autofill._run_one_with_retry({}, "B"), None
    except Exception as e:
        return None, e


out, err = attempts_until(1, RuntimeError("boom"))
check("a run that works is run once", (len(calls), err), (1, None))

out, err = attempts_until(2, run_autofill.SeleniumTimeout("stalled"))
check("a stall gets a second session, and it counts", (len(calls), err), (2, None))

out, err = attempts_until(99, run_autofill.SeleniumTimeout("stalled"))
check("and only a second one", len(calls), 2)
check("the failure still reaches the caller", isinstance(err, run_autofill.SeleniumTimeout), True)

out, err = attempts_until(99, run_autofill.FieldValidationError("האתר סימן שדה שגוי"))
check("a rejected answer is not retried", len(calls), 1)
check("and is reported as itself", type(err).__name__, "FieldValidationError")

out, err = attempts_until(99, RuntimeError("Passport Scenario 'X' is not implemented"))
check("an unimplemented scenario is not retried", len(calls), 1)

out, err = attempts_until(99, run_autofill.BotBlockedError("Just a moment..."))
check("a block does get the second session", len(calls), 2)

print()
print("FAILED" if failures else "all checks passed")
sys.exit(1 if failures else 0)
