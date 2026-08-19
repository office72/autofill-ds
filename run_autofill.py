"""
Core autofill bot for the "happy path" DS-11 first-time-applicant flow on
pptform.state.gov, driven by applicant columns marked Status=Ready in a
per-client Google Sheet (a copy of the AUTOFILL_תבנית template living in
that client's Drive folder - see sheets_backend.py).

Confirmed constraints from live testing (see notes.md / project memory):
  - MUST run headed (headless=False) - headless gets Cloudflare-blocked outright.
  - MUST pace like a human - rapid repeated actions tripped a 403 mid-session
    even in a headed browser. Delays below are intentionally generous.
  - Sequential only - never run more than one applicant/browser at a time.

Uses Selenium via undetected-chromedriver (not Playwright, and not plain
Selenium/ChromeDriver) - requires a real Google Chrome install on the machine.
Plain ChromeDriver gets 403-blocked by Cloudflare on the wizard's AJAX
postback even when headed; undetected-chromedriver patches around that. See
build_driver() and project memory for details.

Passport Scenario (from the sheet) drives branching in step_most_recent_passport:
  - "First-time (None)": always DS-11, straight to Parent & Spouse Info.
  - "Have Book" / "Book Damaged" / "Book Lost" / "Book Stolen": renewal path
    (prints DS-82 or DS-5504 depending on answers - see below), with the
    Data-Correct/Name-Changed/Limited-Validity sub-questions in
    step_most_recent_passport_continued_if_present. Whether the site then
    upgrades to DS-11 (Parent & Spouse Info step appears) is decided
    server-side (incorrect data / unproven name change / book 15+ years old /
    book issued before the applicant turned 16) - step_parent_spouse detects
    this adaptively rather than predicting it. Renewals that DON'T reach
    DS-11 are NOT necessarily DS-82: confirmed live 2026-08-09 that Limited
    Validity=Yes prints a DS-5504 ("...AND LIMITED PASSPORT REPLACEMENT")
    instead - we don't distinguish DS-82 vs DS-5504 in code since both skip
    the same sheet fields (Parent & Spouse), only the printed form differs.
  - Business rule: Passport Card is never offered to clients - only Book or
    First-time are implemented; anything else raises NotImplementedError.

Usage:
    python run_autofill.py --sheet <google-sheet-url-or-id>            # all Status=Ready columns
    python run_autofill.py --sheet <google-sheet-url-or-id> --column B # one column, any status (testing)
"""

import argparse
import datetime
import random
import re
import sys
import time
from pathlib import Path

import sheets_backend
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException as SeleniumTimeout,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

WIZARD_URL = "https://pptform.state.gov/PassportWizardMain.aspx"
DOWNLOAD_DIR = Path(__file__).parent / "downloaded_pdfs"  # local staging only - uploaded to Drive after each run
# Dedicated, isolated Chrome profile for the bot - never the staff member's
# own real Chrome profile. Confirmed live 2026-08-12: without an explicit
# --user-data-dir, uc.Chrome() launched into the real shared Chrome profile
# store on a multi-profile staff machine, triggering the "Continue as
# <name>?" profile picker and first-run onboarding screens on every run -
# both blocked the bot waiting on a dialog no one was there to click. A
# fixed, separate profile directory has exactly one identity (no picker)
# and persists between runs (no repeat first-run screens after the first).
CHROME_PROFILE_DIR = Path(__file__).parent / "chrome_profile"

NEXT_BUTTON = "#PassportWizard_StepNavigationTemplateContainerID_StartNextPreviousButton"
# The Fees step is the wizard's last step - ASP.NET Wizard controls swap in a
# different navigation template there, so its forward button has a different
# id than every other step's NEXT_BUTTON.
FINISH_BUTTON = "#PassportWizard_FinishNavigationTemplateContainerID_FinishButton"

DEFAULT_WAIT = 20  # seconds - the site is often slow even before pacing delays

# Title/body substrings seen on Cloudflare (or similar WAF) interstitial and
# block pages - see notes.md / project memory on pptform.state.gov's anti-bot
# behavior. Checked case-insensitively.
BLOCK_TITLE_SIGNATURES = (
    "just a moment",
    "attention required",
    "access denied",
    "403 forbidden",
    "please wait",
)
BLOCK_BODY_SIGNATURES = (
    "cf-browser-verification",
    "checking your browser before accessing",
    "cf-error-details",
    "ray id",
    "unusual traffic",
    "sorry, you have been blocked",
)


class BotBlockedError(Exception):
    """Raised when the site appears to have detected/blocked the automation,
    as opposed to a plain Selenium timeout from a missing/renamed selector."""


class FieldValidationError(Exception):
    """Raised when the site's own client-side validation alert fires (e.g.
    "There is an error on the following field(s): Zip Code") - a data/sheet
    problem, not a bot-detection or Selenium issue."""


# --- pacing: deliberately generous, see notes.md for why ---
def pause_between_fields():
    time.sleep(random.uniform(1.5, 3.5))


def pause_between_steps():
    time.sleep(random.uniform(7, 15))


def pause_between_applicants():
    """Discovered live on 2026-08-09: pacing within one applicant's session
    (fields/steps) isn't enough on its own - launching a brand new browser
    session immediately after the previous applicant's finished (zero gap
    between separate sessions) tripped anti-bot blocking on 5 of 6 back-to-
    back runs. Much longer gap between applicants than between steps."""
    delay = random.uniform(90, 180)
    log(f"Pausing {delay:.0f}s before the next applicant (separate-session pacing)...")
    time.sleep(delay)


def log(msg):
    print(f"[autofill] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Data loading - see sheets_backend.py (load_all_applicants, ready_columns)
# ---------------------------------------------------------------------------

def is_yes(value) -> bool:
    return str(value).strip().lower() == "yes"


def country_is_usa(country: str) -> bool:
    if not country:
        return False
    c = country.strip().upper()
    return c in ("USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA")


# ---------------------------------------------------------------------------
# Selenium helpers
# ---------------------------------------------------------------------------

def _accept_stray_alert(driver):
    """Selenium (unlike Playwright) blocks the next command if a JS dialog is
    open instead of firing an event - any interaction below can raise this,
    so we accept it and retry once. But if it's the site's own client-side
    validation alert ("There is an error on the following field(s): ..."),
    that's a real data problem, not a stray dialog to swallow and retry -
    raise it clearly instead."""
    try:
        alert = driver.switch_to.alert
        text = alert.text
        log(f"DIALOG: {text}")
        alert.accept()
        if "error on the following field" in text.lower():
            raise FieldValidationError(text)
        return True
    except NoAlertPresentException:
        return False


def _collect_visible_validation_errors(driver) -> list:
    """Site-wide pattern confirmed live 2026-08-14: every field on this
    site has its own <span class="invalid_icon"> validation message,
    hidden (display:none) until that specific field's validation actually
    fires - e.g. "Incorrect email address. See help tip." next to Email
    Address. Scanning for the ones actually visible turns an opaque
    Selenium/native-stacktrace failure into the same plain-English message
    a human looking at the browser would see - genuinely different from
    _accept_stray_alert's dialog-box case above (no dialog fires for this
    kind), so this is a separate check, not a duplicate."""
    try:
        spans = driver.find_elements(By.CSS_SELECTOR, "span.invalid_icon")
    except Exception:
        return []
    seen = set()
    messages = []
    for span in spans:
        try:
            text = span.text.strip()
            if text and span.is_displayed() and text not in seen:
                seen.add(text)
                messages.append(text)
        except Exception:
            continue
    return messages


def find(driver, selector, condition=EC.presence_of_element_located, timeout=DEFAULT_WAIT):
    locator = (By.CSS_SELECTOR, selector)
    try:
        return WebDriverWait(driver, timeout).until(condition(locator))
    except UnexpectedAlertPresentException:
        _accept_stray_alert(driver)
        return WebDriverWait(driver, timeout).until(condition(locator))


def count(driver, selector):
    return len(driver.find_elements(By.CSS_SELECTOR, selector))


def is_visible(driver, selector) -> bool:
    """Some panels (e.g. BookExpiredPanel) stay in the DOM at all times,
    just hidden via CSS until a JS handler reveals them - count() alone
    would find them and check() would then time out trying to click
    something invisible. Check actual visibility, not just DOM presence."""
    els = driver.find_elements(By.CSS_SELECTOR, selector)
    return bool(els) and els[0].is_displayed()


def check_for_block(driver, context: str = ""):
    """Looks for known anti-bot interstitial/block signatures on the current
    page and raises BotBlockedError if found, instead of letting the run fall
    through to a generic (and much less informative) Selenium timeout later."""
    try:
        title = (driver.title or "").lower()
    except UnexpectedAlertPresentException:
        _accept_stray_alert(driver)
        title = (driver.title or "").lower()
    for sig in BLOCK_TITLE_SIGNATURES:
        if sig in title:
            raise BotBlockedError(f"[{context}] page title looks like a block/challenge page: {driver.title!r}")

    body = driver.page_source.lower()
    for sig in BLOCK_BODY_SIGNATURES:
        if sig in body:
            raise BotBlockedError(f"[{context}] page body contains block signature {sig!r}")


def click(driver, selector):
    el = find(driver, selector, EC.element_to_be_clickable)
    try:
        el.click()
    except UnexpectedAlertPresentException:
        _accept_stray_alert(driver)
        find(driver, selector, EC.element_to_be_clickable).click()
    except ElementClickInterceptedException:
        # On very long pages (e.g. the DS-11 review screen) Selenium's
        # computed click point can land on a different overlapping element -
        # scroll the target fully into view and fall back to a JS-dispatched
        # click, which fires directly on the element regardless of what's
        # visually on top of it at that screen coordinate.
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        driver.execute_script("arguments[0].click();", el)


# ---------------------------------------------------------------------------
# Step fillers
# ---------------------------------------------------------------------------

def format_value(value):
    """Excel stores a typed date (e.g. 14/05/1990, however the user's locale writes it)
    as a real date object - convert it to the MM/DD/YYYY string the site expects,
    regardless of how it was typed or displayed in Excel."""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%m/%d/%Y")
    text = str(value)
    # Staff sometimes type dates directly as text (e.g. "01.01.2027") instead
    # of a real Excel date cell, in DD.MM.YYYY (Israeli convention) - the
    # site's date fields require MM/DD/YYYY and reject non-digit/slash
    # characters outright, so normalize here rather than let it fail on-site.
    m = re.fullmatch(r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})", text.strip())
    if m:
        day, month, year = m.groups()
        return f"{int(month):02d}/{int(day):02d}/{year}"
    return text


def digits_only(value):
    """The site's phone field is literally labeled 'Telephone Number (no
    dashes)' - digits only, client-side onkeypress filter rejects anything
    else, so strip symbols on our side rather than rely on that filter.

    Root cause of the "1233645" EC Phone corruption chased through several
    wrong theories on 2026-08-10 (CDP timing, symbol filtering, country-code
    length) turned out to be upstream of all of them: a phone number typed
    with a leading "+" (e.g. "+972-50-1234567") gets silently evaluated by
    Google Sheets itself as an arithmetic expression (972-50-1234567 =
    -1233645) UNLESS the cell is formatted as plain text - the real fix is
    forcing plain-text format on phone-like columns in the template (see
    build_google_sheet_template.py), not reshaping the digits here. This
    function stays simple on purpose."""
    if value is None or str(value).strip() == "":
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def us_zip_prefix(value):
    """The site's Zip Code fields only accept xxxxx or xxxxx-xxxx (US format).
    For a required US-format field tied to a non-US address (e.g. a 7-digit
    Israeli postal code), business decision: use the first 5 digits as a
    placeholder - not a real US zip, just satisfies the site's validation."""
    if value is None or str(value).strip() == "":
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:5] or None


def _type_text(driver, el, text):
    """element.send_keys() maps each character through Windows' ACTIVE keyboard
    layout via virtual-key codes - on this machine (Hebrew layout installed)
    that corrupted punctuation like '.' into Hebrew letters (confirmed live:
    an email's '.' became 'ץ'). Dispatch real per-character key events via CDP
    instead: type "char" inserts the exact Unicode text directly, independent
    of OS layout, while still firing the site's onkeypress/onkeyup handlers
    like real typing does (unlike setting .value directly via JS)."""
    el.click()
    for ch in text:
        driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "char", "text": ch})
        # Small per-character delay, cheap insurance against outrunning a
        # field's onkeypress JS validator. NOTE this did NOT fix the one
        # corruption case we've actually seen (EC Phone -> "1233645",
        # confirmed live 2026-08-10 with and without this delay, and with or
        # without symbol characters in the source text) - that bug is still
        # unexplained, see notes.md. Keeping the delay anyway since it's
        # harmless and may still help other fields we haven't hit yet.
        time.sleep(random.uniform(0.02, 0.06))


def _retry_on_stale(action, retries=2):
    """Confirmed live 2026-08-10: an AJAX postback from a preceding radio
    click (e.g. Preferred Communication) can still be settling when the next
    field is located, so the freshly-found element goes stale before we
    finish acting on it. Re-locating from scratch (action() calls find()
    itself) and retrying is the fix - a stale handle can never become valid
    again, only a fresh find() can."""
    for attempt in range(retries + 1):
        try:
            return action()
        except StaleElementReferenceException:
            if attempt == retries:
                raise
            time.sleep(0.5)


def fill_text(driver, selector, value):
    if value is None or str(value).strip() == "":
        return

    def _do():
        el = find(driver, selector)
        el.clear()
        _type_text(driver, el, format_value(value))

    _retry_on_stale(_do)
    pause_between_fields()


def select_option(driver, selector, value):
    if value is None or str(value).strip() == "":
        return
    el = find(driver, selector)
    sel = Select(el)
    target = str(value).strip().lower()
    for option in sel.options:
        text = option.text.strip().lower()
        val = (option.get_attribute("value") or "").strip().lower()
        if target in (text, val):
            sel.select_by_visible_text(option.text)
            pause_between_fields()
            return
    raise NoSuchElementException(
        f"No option matching {value!r} (case-insensitive, checked both visible text "
        f"and value attribute) in {selector} - the sheet's spelling may not match "
        f"the site's dropdown exactly."
    )


def check(driver, selector):
    """Ensures a checkbox/radio ends up checked - mirrors Playwright's .check(),
    which is a no-op if it's already checked."""
    def _do():
        el = find(driver, selector, EC.element_to_be_clickable)
        if not el.is_selected():
            el.click()

    _retry_on_stale(_do)
    pause_between_fields()


def step_about_you(driver, d):
    log("Step 1: About You")
    p = "#PassportWizard_aboutYouStep_"
    fill_text(driver, p + "firstNameTextBox", d.get("First Name"))
    fill_text(driver, p + "middleNameTextBox", d.get("Middle Name"))
    fill_text(driver, p + "lastNameTextBox", d.get("Last Name"))
    fill_text(driver, p + "suffixNameTextBox", d.get("Suffix"))
    fill_text(driver, p + "dobTextBox", d.get("Date of Birth"))
    fill_text(driver, p + "pobCityTextBox", d.get("City of Birth"))

    country = d.get("Country of Birth")
    select_option(driver, p + "pobCountryList", country)
    if country_is_usa(country):
        state = d.get("State of Birth (USA only)")
        select_option(driver, p + "pobStateList", state)

    ssn = d.get("SSN") or "000000000"
    fill_text(driver, p + "ssnTextBox", ssn)
    fill_text(driver, p + "uscisANumberTextBox", d.get("USCIS A-Number"))

    select_option(driver, p + "sexList", d.get("Sex"))
    select_option(driver, p + "heightFootList", d.get("Height Feet"))
    select_option(driver, p + "heightInchList", d.get("Height Inches"))
    select_option(driver, p + "hairList", d.get("Hair Color"))
    select_option(driver, p + "eyeList", d.get("Eye Color"))

    fill_text(driver, p + "occupationTextBox", d.get("Occupation"))
    fill_text(driver, p + "employerTextBox", d.get("Employer"))

    click_next(driver)


def step_address(driver, d):
    log("Step 2: Address")
    p = "#PassportWizard_addressStep_"
    fill_text(driver, p + "mailStreetTextBox", d.get("Mail Street"))
    fill_text(driver, p + "mailCityTextBox", d.get("Mail City"))
    mail_country = d.get("Mail Country")
    select_option(driver, p + "mailCountryList", mail_country)
    if country_is_usa(mail_country):
        select_option(driver, p + "mailStateList", d.get("Mail State (USA only)"))
        fill_text(driver, p + "mailZipTextBox", d.get("Mail Zip"))  # site validates xxxxx/xxxxx-xxxx only - US-only field
    fill_text(driver, p + "mailCareOfTextBox", d.get("In Care Of"))

    same_as_permanent = d.get("Same As Permanent Address?")
    if is_yes(same_as_permanent):
        check(driver, p + "permanentAddressList_0")
    else:
        check(driver, p + "permanentAddressList_1")
        fill_text(driver, p + "permanentStreetTextBox", d.get("Permanent Street"))
        fill_text(driver, p + "permanentApartmentTextBox", d.get("Permanent Apartment"))
        fill_text(driver, p + "permanentCityTextBox", d.get("Permanent City"))
        perm_country = d.get("Permanent Country")
        select_option(driver, p + "permanentCountryList", perm_country)
        if country_is_usa(perm_country):
            select_option(driver, p + "permanentStateList", d.get("Permanent State (USA only)"))
            fill_text(driver, p + "permanentZipTextBox", d.get("Permanent Zip"))  # US-only field, see mailZipTextBox note

    comm = str(d.get("Preferred Communication") or "Mail").strip().lower()
    if comm == "email":
        check(driver, p + "CommunicateEmail")
    elif comm == "both":
        check(driver, p + "CommunicateBoth")
    else:
        check(driver, p + "CommunicateMail")

    fill_text(driver, p + "emailTextBox", d.get("Email"))
    fill_text(driver, p + "confirmEmailTextBox", d.get("Confirm Email"))

    click_next(driver)


def step_travel_plans(driver, d):
    """Not in notes.md's original mapping - discovered live on 2026-08-05.
    The site itself says it's optional: "If you do not have travel plans, you
    do not need to enter information on this page." Left blank unless the
    sheet grows these columns later."""
    log("Step: Travel Plans (undocumented in notes.md - filling if present, else skipping)")
    p = "#PassportWizard_travelPlans_"
    fill_text(driver, p + "TripDateTextBox", d.get("Trip Date"))
    fill_text(driver, p + "TripDateReturnTextBox", d.get("Trip Return Date"))
    fill_text(driver, p + "CountriesTextBox", d.get("Countries To Be Visited"))

    click_next(driver)


def step_emergency_contact(driver, d):
    log("Step 3: Emergency Contact")
    p = "#PassportWizard_emergencyContacts_"
    fill_text(driver, p + "ecNameTextBox", d.get("EC Name"))
    fill_text(driver, p + "ecAddressTextBox", d.get("EC Address"))
    fill_text(driver, p + "ecApartmentTextBox", d.get("EC Apartment"))
    fill_text(driver, p + "ecCityTextBox", d.get("EC City"))
    ec_country = d.get("EC Country")
    select_option(driver, p + "ecCountryList", ec_country)
    ec_zip = d.get("EC Zip")
    if country_is_usa(ec_country):
        select_option(driver, p + "ecStateList", d.get("EC State (USA only)"))
    else:
        ec_zip = us_zip_prefix(ec_zip)  # required field, US-format only - see us_zip_prefix()
    fill_text(driver, p + "ZipCodeTextBox", ec_zip)
    fill_text(driver, p + "ecPhoneTextBox", digits_only(d.get("EC Phone")))
    fill_text(driver, p + "ecEmailTextBox", d.get("EC Email"))
    fill_text(driver, p + "ecRelationshipTextBox", d.get("EC Relationship"))

    click_next(driver)


BOOK_POSSESSION_IDS = {
    "Have Book": "BookYes",
    "Book Damaged": "BookDamaged",
    "Book Lost": "BookLost",
    "Book Stolen": "BookStolen",
}


def step_most_recent_passport(driver, d):
    log("Step 4: Most Recent Passport")
    scenario = str(d.get("Passport Scenario") or "First-time (None)").strip()
    p = "#PassportWizard_mostRecentPassport_"

    if scenario.startswith("First-time"):
        check(driver, p + "CurrentHaveNone")
        click_next(driver)
        return

    if scenario not in BOOK_POSSESSION_IDS:
        raise NotImplementedError(
            f"Passport scenario {scenario!r} is not implemented - business rule is Book or "
            "First-time only, never Card (see notes.md)."
        )

    check(driver, p + "CurrentHaveBook")

    # Confirmed live 2026-08-10: "Have a passport book..." is its own
    # product-selection question - the Book/Damaged/Lost/Stolen follow-up
    # (+ Book Issue Date/Name-on-Book/Book-Number) lives on a SEPARATE page
    # that only appears after Next, unlike most other radio-triggered
    # postbacks in this wizard which inject new content in-page via AJAX.
    # Adaptive either way: only click Next if the follow-up isn't already here.
    if count(driver, p + BOOK_POSSESSION_IDS[scenario]) == 0:
        click_next(driver)

    check(driver, p + BOOK_POSSESSION_IDS[scenario])

    lost_or_stolen = scenario in ("Book Lost", "Book Stolen")
    if lost_or_stolen:
        reported = d.get("Reported Lost or Stolen?")
        check(driver, p + "ReportLostBookYesRadioButton" if is_yes(reported) else p + "ReportLostBookNoRadioButton")

    book_issue_date = d.get("Book Issue Date")
    fill_text(driver, p + "BookIssueDate", book_issue_date)

    # "Was your lost or stolen passport book issued more than 15 years ago?" -
    # not in notes.md's original mapping, discovered live on 2026-08-05. It's
    # always in the DOM but hidden until the site's own JS reveals it on the
    # BookIssueDate field's blur event - fill_text() doesn't blur, so trigger
    # it explicitly, then check actual visibility (not just DOM presence).
    # Only asked for Lost/Stolen. Computed from the date itself rather than
    # adding another sheet column.
    if lost_or_stolen:
        driver.execute_script("arguments[0].blur();", find(driver, p + "BookIssueDate"))
        pause_between_fields()
    if lost_or_stolen and is_visible(driver, p + "BookExpiredYesRadioButton"):
        is_expired = False
        if isinstance(book_issue_date, (datetime.datetime, datetime.date)):
            issue_d = book_issue_date.date() if isinstance(book_issue_date, datetime.datetime) else book_issue_date
            cutoff = datetime.date.today().replace(year=datetime.date.today().year - 15)
            is_expired = issue_d < cutoff
        check(driver, p + "BookExpiredYesRadioButton" if is_expired else p + "BookExpiredNoRadioButton")

    fill_text(driver, p + "firstNameOnBook", d.get("Name On Book - First"))
    fill_text(driver, p + "lastNameOnBook", d.get("Name On Book - Last"))
    fill_text(driver, p + "ExistingBookNumber", d.get("Book Number"))

    click_next(driver)


INCORRECT_FIELD_IDS = {
    "last name": "IncorrectLastName",
    "first name": "IncorrectFirstName",
    "middle name": "IncorrectMiddleName",
    "place of birth": "IncorrectPlaceOfBirth",
    "date of birth": "IncorrectDateOfBirth",
    "sex": "IncorrectSex",
}


def step_most_recent_passport_continued_if_present(driver, d):
    """This step (data-correct / name-changed / limited-validity questions)
    only appears for Book/Damaged/Lost/Stolen scenarios, not First-time.

    Confirmed live 2026-08-10: the Data-Incorrect and Name-Changed
    sub-questions are INDEPENDENTLY present - a run with Name Changed=Yes
    showed only the name-change question, no Data-Incorrect panel at all.
    Gating the whole step's presence on DataIncorrectButtonsPanel alone (the
    original assumption) skipped the entire step - including the required,
    still-unanswered Name-Changed radio buttons - which then silently stuck
    the wizard on this page while later step functions ran blind against a
    page they weren't actually on. Check each sub-question independently."""
    has_data_incorrect_q = count(driver, "#PassportWizard_mostRecentPassportContinued_DataIncorrectButtonsPanel") > 0
    has_name_changed_q = count(driver, "#PassportWizard_mostRecentPassportContinued_NameChangedButtonsPanel") > 0
    if not has_data_incorrect_q and not has_name_changed_q:
        log("Step 6 (Most Recent Passport Continued) did not appear - skipping, as expected for first-time applicants")
        return

    log("Step 6: Most Recent Passport Continued")
    p = "#PassportWizard_mostRecentPassportContinued_"

    # NOTE: site's own ids are misleading - "dataIncorrectBook" is the "Yes,
    # incorrect" choice and "dataIncorrectNone" is "No, printed correctly".
    if has_data_incorrect_q:
        if is_yes(d.get("Data Printed Correctly?")):
            check(driver, p + "dataIncorrectNone")
        else:
            check(driver, p + "dataIncorrectBook")
            incorrect_fields = str(d.get("Incorrect Fields") or "")
            for name in incorrect_fields.split(","):
                key = name.strip().lower()
                if key in INCORRECT_FIELD_IDS:
                    check(driver, p + INCORRECT_FIELD_IDS[key])

    # Same misleading-id pattern: "nameChangeBook" = Yes, "nameChangeNone" = No.
    name_changed = False
    if has_name_changed_q:
        name_changed = is_yes(d.get("Name Changed?"))
        check(driver, p + "nameChangeBook" if name_changed else p + "nameChangeNone")

    # Name Change sub-panel (reason/date/place/certified-docs) - mirrors DS-82
    # Application Page 1, Item 11 "Name Change Information". IDs confirmed
    # live 2026-08-10 (first real test of this branch - the earlier guessed
    # IDs were wrong and are corrected here): the "Reason" and "Certified"
    # questions are RadioBtnsInline tables with _0/_1 child radios (value
    # "M"/"C" for reason), not checkboxes as originally guessed.
    if name_changed:
        change_type = str(d.get("Name Change Type") or "").strip().lower()
        if change_type == "marriage":
            check(driver, p + "NameChangeReason_0")
        elif change_type == "court order":
            check(driver, p + "NameChangeReason_1")
        fill_text(driver, p + "NameChangeDate", d.get("Name Change Date"))
        fill_text(driver, p + "NameChangePlace", d.get("Name Change Place"))
        certified = d.get("Name Change Certified Docs?")
        if count(driver, p + "NameChangeCertified_0") > 0:
            check(driver, p + "NameChangeCertified_0" if is_yes(certified) else p + "NameChangeCertified_1")

    # Limited-validity sub-branch - only appears when the previous book was
    # issued within the last 2 years (site-computed; not always present).
    if count(driver, p + "LimitedIssueBook_0") > 0:
        limited = d.get("Limited Validity Under 2 Years?")
        check(driver, p + "LimitedIssueBook_0" if is_yes(limited) else p + "LimitedIssueBook_1")
        if is_yes(limited) and count(driver, p + "paidForCard_0") > 0:
            paid = d.get("Paid For Card Before?")
            check(driver, p + "paidForCard_0" if is_yes(paid) else p + "paidForCard_1")

    click_next(driver)


def _fill_parent(driver, d, n: int):
    p = f"#PassportWizard_moreAboutYouStep_parent{n}"
    unknown = d.get(f"Parent {n} Unknown?")
    if is_yes(unknown):
        check(driver, f"#PassportWizard_moreAboutYouStep_unknownParent{n}CheckBox")
        return  # assumption: rest of this parent's fields are not needed when Unknown - verify on first real run

    fill_text(driver, p + "FirstNameTextBox", d.get(f"Parent {n} First & Middle Name"))
    fill_text(driver, p + "LastNameTextBox", d.get(f"Parent {n} Last Name"))
    fill_text(driver, p + "BirthDateTextBox", d.get(f"Parent {n} Date of Birth"))
    fill_text(driver, p + "BirthPlaceTextBox", d.get(f"Parent {n} Place of Birth"))

    sex = str(d.get(f"Parent {n} Sex") or "").strip().lower()
    if sex == "female":
        check(driver, p + "SexList_1")
    elif sex == "male":
        check(driver, p + "SexList_0")

    citizen = d.get(f"Parent {n} US Citizen?")
    check(driver, p + "CitizenList_0" if is_yes(citizen) else p + "CitizenList_1")


def step_parent_spouse(driver, d):
    """DS-11 only - appears whenever there's no valid prior passport to renew
    (every First-time applicant), OR when the site silently upgrades a
    renewal to DS-11 (incorrect data / unproven name change / book 15+ years
    old / previous book issued before age 16 - decided server-side, not
    something we predict). Skip silently if absent - that does NOT
    necessarily mean plain DS-82: confirmed live 2026-08-09 that a Limited
    Validity renewal with no parent step still printed a DS-5504, not a
    DS-82 - don't assume which non-DS-11 form resulted, we only know it's
    not the DS-11/parent-info path."""
    if count(driver, "#PassportWizard_moreAboutYouStep_unknownParent1CheckBox") == 0:
        log("Parent & Spouse Info step did not appear - not the DS-11 path (could be DS-82 or DS-5504)")
        return

    log("Step 10: Parent & Spouse Info (DS-11)")

    _fill_parent(driver, d, 1)
    _fill_parent(driver, d, 2)

    married = d.get("Ever Married?")
    p = "#PassportWizard_moreAboutYouStep_"
    if is_yes(married):
        check(driver, p + "marriedList_0")
        fill_text(driver, p + "spouseNameTextBox", d.get("Spouse First & Middle Name"))
        fill_text(driver, p + "spouseLastNameTextBox", d.get("Spouse Last Name"))
        fill_text(driver, p + "spouseBirthDateTextBox", d.get("Spouse Date of Birth"))
        fill_text(driver, p + "spouseBirthplaceTextBox", d.get("Spouse Place of Birth"))
        spouse_citizen = d.get("Spouse US Citizen?")
        check(driver, p + "spouseCitizenList_0" if is_yes(spouse_citizen) else p + "spouseCitizenList_1")
        fill_text(driver, p + "marriedDateTextBox", d.get("Marriage Date"))

        divorced = d.get("Ever Divorced or Widowed?")
        # NOTE: divorcedList_0/_1 ids follow the site's consistent Yes/No radio
        # naming pattern but were not directly confirmed in notes.md - verify on first run.
        if is_yes(divorced):
            check(driver, p + "divorcedList_0")
            fill_text(driver, p + "divorcedDateTextBox", d.get("Divorce Date"))
        else:
            check(driver, p + "divorcedList_1")
    else:
        check(driver, p + "marriedList_1")

    click_next(driver)


def step_other_names(driver, d):
    p = "#PassportWizard_otherNameStep_"
    # Adaptive: the DS-11 branch re-visits this step a second time later in
    # the flow (after a late Parent & Spouse Info trigger, e.g. from the
    # Lost/Stolen report) per notes.md's documented step order (6->10->7) -
    # but this function also gets called from a spot that may not actually
    # be on this step at all in that case, so check presence first rather
    # than blindly clicking Next wherever we happen to be.
    if count(driver, p + "addOtherFirstTextBox") == 0:
        return
    log("Step 7: Other Names")
    # First-time applicants: leave blank unless data provided for "Other Name 1..3"
    for i in (1, 2, 3):
        first = d.get(f"Other Name {i} - First")
        last = d.get(f"Other Name {i} - Last")
        if first or last:
            fill_text(driver, p + "addOtherFirstTextBox", first)
            fill_text(driver, p + "addOtherLastTextBox", last)
            click(driver, p + "addButton")
            pause_between_fields()

    click_next(driver)


def step_review(driver, d):
    # Adaptive: DS-11's step order re-visits Review a second time after a
    # late Parent & Spouse Info trigger (e.g. from the Lost/Stolen report) -
    # see step_other_names() for the same pattern.
    if count(driver, "#PassportWizard_reviewStep_Label2") == 0:
        return
    log("Step 8: Review")
    click_next(driver)


def step_fees(driver, d):
    log("Step 9: Fees (business rule: Book / Routine / Standard, always)")
    p = "#PassportWizard_feesStep_"
    check(driver, p + "bookFee")
    # bookType52 (Large Book) intentionally left unchecked - business rule
    check(driver, p + "routineService")
    check(driver, p + "bookPriorityMail")  # Standard Delivery

    click_finish(driver)


def step_esignature_if_present(driver, d):
    """Not in notes.md's original mapping - discovered live on 2026-08-05.
    Appears after Fees, before the final Print Form step, only for the
    Lost/Stolen Report branch: "How would you like to send your statement
    regarding a Valid Lost or Stolen U.S. Passport?" - Sign and Send Online
    vs Print, Sign and Mail. Business rule (confirmed with the client): the
    answer here is always Print, Sign and Mail - this business never submits
    online, always prints for the client to sign and send themselves."""
    if count(driver, "#PassportWizard_esignatureStep_lostOrStolenDelivery_1") == 0:
        return
    log("Step: Electronic Signature (DS-64) - Print, Sign and Mail")
    check(driver, "#PassportWizard_esignatureStep_lostOrStolenDelivery_1")
    click_next(driver)


def step_lost_stolen_report_if_present(driver, d):
    """Not in notes.md's original mapping - discovered live on 2026-08-05.
    Appears right after Review, BEFORE Fees (initially misread as after Fees,
    since step_fees()'s own log line had already printed by the time this
    was reached - the timeout was actually step_fees() finding itself on the
    wrong page). Only when the passport scenario is Lost/Stolen and "Reported
    Lost or Stolen?" was answered No - the site walks the applicant through
    filing/documenting the loss right there instead of assuming it was
    already reported to police."""
    if count(driver, "#PassportWizard_lostStolenStep_reporterPanel") == 0:
        log("Lost/Stolen Report step did not appear - skipping")
        return

    log("Step: Valid Lost or Stolen Passport Report")
    p = "#PassportWizard_lostStolenStep_"

    check(driver, p + "reporterYesRadioButton" if is_yes(d.get("Reporting Own Passport?")) else p + "reporterNoRadioButton")
    check(driver, p + "policeReportYesRadioButton1" if is_yes(d.get("Filed Police Report?")) else p + "policeReportNoRadioButton1")

    # 115-char limit enforced by the site's own JS counter - truncate rather
    # than let the site's validator silently reject an over-length value.
    fill_text(driver, p + "bookLostHowTextBox", str(d.get("Lost/Stolen Explanation") or "")[:115] or None)
    fill_text(driver, p + "bookLostWhereTextBox", str(d.get("Lost/Stolen Location") or "")[:115] or None)
    fill_text(driver, p + "bookLostDateTextBox", d.get("Lost/Stolen Date"))

    check(driver, p + "lostPrevYesRadioButton" if is_yes(d.get("Other Passports Lost/Stolen?")) else p + "lostPrevNoRadioButton")

    click_next(driver)


def wait_for_new_download(before: set, timeout: int) -> Path:
    """Selenium has no expect_download() event like Playwright - poll the
    download folder instead, ignoring Chrome's in-progress .crdownload files
    and waiting for the file size to stop changing before treating it as done."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = set(DOWNLOAD_DIR.glob("*"))
        new_files = [f for f in (current - before) if not f.name.endswith(".crdownload")]
        if new_files:
            candidate = new_files[0]
            size1 = candidate.stat().st_size
            time.sleep(1)
            if candidate.exists() and candidate.stat().st_size == size1:
                return candidate
        time.sleep(0.5)
    raise SeleniumTimeout("No PDF appeared in downloaded_pdfs/ within the timeout")


def step_final_print(driver, d, out_path: Path):
    log("Final step: acknowledgment + Print Form")
    check(driver, "#PassportWizard_nextStepsStep_ConfirmationCheckBox")

    before = set(DOWNLOAD_DIR.glob("*"))
    click(driver, "#PassportWizard_nextStepsStep_printFormButton")

    # The site's own confirmPrintForm() JS always shows a blocking "check your
    # printer settings" alert here before the download can start - wait for
    # it and accept it, otherwise the download never begins and we just burn
    # the whole timeout below waiting for a file that can't arrive yet.
    try:
        WebDriverWait(driver, 10).until(lambda drv: _accept_stray_alert(drv))
    except SeleniumTimeout:
        pass  # alert didn't appear this time - proceed anyway

    downloaded = wait_for_new_download(before, timeout=60)
    downloaded.rename(out_path)
    log(f"Saved PDF to {out_path}")


def click_next(driver):
    click(driver, NEXT_BUTTON)
    pause_between_steps()
    check_for_block(driver, context="after click_next")


def click_finish(driver):
    click(driver, FINISH_BUTTON)
    pause_between_steps()
    check_for_block(driver, context="after click_finish")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _detect_chrome_major_version():
    """Reads the installed Chrome's major version directly from chrome.exe's
    file version resource, so the chromedriver pin below never goes stale
    silently again. Real failure, 2026-08-12: version_main was hardcoded to
    150; Chrome auto-updated itself to 151 (as it does, unattended) and
    every run since then crashed instantly with an opaque chromedriver
    native stacktrace (no readable message) - looked like a random crash
    until traced to this exact mismatch.

    Deliberately NOT `chrome.exe --version` via subprocess - tried that
    first, but Chrome frequently keeps a background process alive after all
    windows close, and in that case a new `chrome.exe --version` call just
    hands off to the existing session and prints "Opening in existing
    browser session." instead of a version string (confirmed live on this
    machine). Reading the file's own VS_FIXEDFILEINFO version resource via
    ctypes (stdlib only, no pywin32 dependency) sidesteps that entirely -
    it's a property of the file on disk, independent of whether Chrome
    happens to be running.

    Returns None if chrome.exe isn't found at either standard path or the
    resource can't be read, letting uc.Chrome() fall back to its own (less
    reliable, per the comment this replaces) auto-detection rather than
    hard-failing here."""
    import ctypes
    from ctypes import wintypes

    class _VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD), ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    for path in CHROME_PATHS:
        if not Path(path).exists():
            continue
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
            buf = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf)
            value = ctypes.c_void_p()
            value_len = wintypes.UINT()
            ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(value), ctypes.byref(value_len))
            info = ctypes.cast(value, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
            return info.dwFileVersionMS >> 16
        except Exception:
            continue
    return None


def build_driver():
    # headed on purpose - see module docstring; do NOT add --headless.
    # Plain Selenium/ChromeDriver gets 403-blocked by Cloudflare specifically
    # on the wizard's AJAX/UpdatePanel postback (confirmed via network
    # diagnostics), even after hiding navigator.webdriver via CDP - so this
    # uses undetected-chromedriver, which patches the chromedriver binary
    # itself (removes the $cdc_... automation markers stock chromedriver
    # injects into every page) rather than relying on JS-level patches alone.
    options = uc.ChromeOptions()
    options.add_experimental_option("prefs", {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,  # download PDFs instead of opening Chrome's viewer
    })
    CHROME_PROFILE_DIR.mkdir(exist_ok=True)
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    return uc.Chrome(options=options, version_main=_detect_chrome_major_version())


# Digit-string fields where Google Sheets silently mis-typing the value as a
# number is a real, confirmed risk (see digits_only()'s docstring) - not
# every numeric-looking value here is wrong (e.g. a plain "587474100" phone
# number legitimately reads back as an int too), but a NEGATIVE number is an
# unambiguous tell: nobody's SSN/zip/phone/book number is negative, so it
# can only be Sheets having evaluated a leading "+"/"-" as arithmetic.
NUMERIC_FIELDS_REJECT_NEGATIVE = ("EC Phone", "SSN", "USCIS A-Number", "Book Number", "Mail Zip", "Permanent Zip", "EC Zip")


def _validate_applicant_data(data: dict):
    """Fail fast, before opening a browser, rather than silently typing a
    corrupted value into the government site. Confirmed live 2026-08-10:
    "+972-50-1234567" typed into an EC Phone Sheet cell was evaluated by
    Sheets as 972-50-1234567 = -1233645 and read back as that int - this
    looked like a site/CDP bug for hours before being traced to the Sheet
    cell. Reformatting the cell as plain text does NOT prevent this (Sheets'
    formula-entry trigger on a leading +/= fires regardless of cell format),
    so the only reliable fix is catching the tell (a negative number) here."""
    for label in NUMERIC_FIELDS_REJECT_NEGATIVE:
        value = data.get(label)
        if isinstance(value, (int, float)) and value < 0:
            raise ValueError(
                f"{label!r} = {value} - a negative number for this field can only mean Google Sheets "
                f"evaluated the entered text as an arithmetic formula (e.g. a phone number typed with a "
                f"leading '+' like '+972-50-1234567' becomes 972-50-1234567 = -1233645). Fix the cell in "
                f"the Sheet - re-enter it without a leading +/-/= (e.g. as a plain domestic number or with "
                f"the country code but no '+'), then re-run."
            )


def run_one(data: dict) -> Path:
    """Runs the wizard for one already-loaded applicant dict. Returns the
    local (staging) path of the generated PDF - caller uploads it to Drive."""
    _validate_applicant_data(data)
    first = data.get("First Name") or "unknown"
    last = data.get("Last Name") or "unknown"

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    out_path = DOWNLOAD_DIR / f"{last}_{first}_{int(time.time())}.pdf"

    driver = build_driver()

    try:
        driver.get(WIZARD_URL)
        time.sleep(3)
        check_for_block(driver, context="initial page load")

        click(driver, "#PassportWizard_portalStep_ApplyButton")
        time.sleep(4)
        log(f"URL after 1st Apply click: {driver.current_url}")
        check_for_block(driver, context="after 1st Apply click")

        # With undetected-chromedriver a single click reaches About You directly.
        # Plain ChromeDriver used to need a 2nd click here (see git history) back
        # when Cloudflare was 403-blocking the first postback - kept as a
        # fallback only, in case that resurfaces.
        if count(driver, "#PassportWizard_aboutYouStep_firstNameTextBox") == 0:
            click(driver, "#PassportWizard_portalStep_ApplyButton")
            pause_between_steps()
            log(f"URL after 2nd Apply click: {driver.current_url}, title: {driver.title}")
            check_for_block(driver, context="after 2nd Apply click")

            if count(driver, "#PassportWizard_aboutYouStep_firstNameTextBox") == 0:
                raise BotBlockedError(
                    "Still not on the About You step after two Apply clicks - the postback to "
                    "start the wizard was rejected. Not a Cloudflare interstitial (no block "
                    "signature matched), so this may be form validation or anti-bot rate-limiting "
                    "specific to this session - check debug/ screenshot and notes.md."
                )
        else:
            pause_between_steps()

        step_about_you(driver, data)
        step_address(driver, data)
        step_travel_plans(driver, data)
        step_emergency_contact(driver, data)
        step_most_recent_passport(driver, data)
        step_most_recent_passport_continued_if_present(driver, data)
        step_parent_spouse(driver, data)
        step_other_names(driver, data)
        step_review(driver, data)
        step_lost_stolen_report_if_present(driver, data)
        # Parent & Spouse Info can also get triggered by the Lost/Stolen
        # report itself (not just the earlier reasons - book 15+ years old /
        # incorrect data / name changed) - discovered live on 2026-08-05.
        # step_parent_spouse() is already adaptive/idempotent, so calling it
        # again here is a safe no-op if it was already handled earlier.
        step_parent_spouse(driver, data)
        # DS-11's step order is Parent&Spouse -> Other Names -> Review, so a
        # late Parent&Spouse trigger re-shows both - both are adaptive, safe
        # no-ops if not actually present.
        step_other_names(driver, data)
        step_review(driver, data)
        step_fees(driver, data)
        step_esignature_if_present(driver, data)
        step_final_print(driver, data, out_path)
    except Exception as e:
        try:
            _accept_stray_alert(driver)  # an open alert blocks screenshot/page_source below
        except Exception:
            pass  # best-effort cleanup only - don't let this mask the real failure
        debug_dir = Path(__file__).parent / "debug"
        debug_dir.mkdir(exist_ok=True)
        stamp = int(time.time())
        debug_png = debug_dir / f"fail_{stamp}.png"
        debug_html = debug_dir / f"fail_{stamp}.html"
        driver.save_screenshot(str(debug_png))
        debug_html.write_text(driver.page_source, encoding="utf-8")
        log(f"Failure - saved debug/fail_{stamp}.png and .html")

        # If the site's own inline validation is what actually failed us,
        # surface ITS plain-English message instead of the raw Selenium/
        # native-driver exception - confirmed live 2026-08-14: staff saw an
        # unreadable native stacktrace ("Message: \nStacktrace:\n\t...")
        # for what was, on screen, just "Incorrect email address. See help
        # tip." next to an empty field. The original exception is still
        # logged (not lost) for when *I* need to debug the underlying
        # Selenium/site issue - only what lands in the Sheet's Notes column
        # (a human, not code, reading it) gets replaced.
        validation_errors = _collect_visible_validation_errors(driver)
        if validation_errors:
            log(f"  Visible field-validation error(s) on page: {validation_errors}")
            log(f"  (original exception: {e!r})")
            e = FieldValidationError("האתר סימן שדה שגוי/חסר: " + " | ".join(validation_errors))

        # Attach paths to the exception so run_all() can upload them to Drive
        # too - debug/ is local to whichever computer ran this, but staff
        # could be on any machine, so the failure evidence needs to travel
        # with the applicant's own Sheet/folder, not stay stuck on one PC.
        e.debug_artifacts = (debug_png, debug_html)
        raise e
    finally:
        driver.quit()

    log("Done.")
    return out_path


def run_all(spreadsheet_id: str, only_column: str = None):
    """Processes every Status=Ready applicant column in the sheet, one at a
    time (never parallel - see module docstring on pacing). A failure on one
    applicant is recorded (Status=Error + a Notes summary) and does NOT abort
    the rest of the queue. --column overrides the queue with a single column,
    regardless of its Status, for manual testing."""
    if only_column:
        applicants = sheets_backend.load_all_applicants(spreadsheet_id)
        if only_column not in applicants:
            log(f"Column {only_column} not found in this sheet.")
            return
        targets = [only_column]
    else:
        targets = sheets_backend.ready_columns(spreadsheet_id)
        if not targets:
            log("No applicants marked 'Ready' - nothing to do.")
            return

    log(f"Processing {len(targets)} applicant(s): {', '.join(targets)}")
    for i, column_letter in enumerate(targets):
        if i > 0:
            pause_between_applicants()
        data = sheets_backend.load_all_applicants(spreadsheet_id)[column_letter]
        first = data.get("First Name") or "unknown"
        last = data.get("Last Name") or "unknown"
        log(f"--- Applicant {column_letter}: {first} {last} ---")
        sheets_backend.set_status(spreadsheet_id, column_letter, sheets_backend.RUNNING_STATUS)

        try:
            out_path = run_one(data)
        except Exception as e:
            log(f"Applicant {column_letter} FAILED: {e}")
            note = str(e)[:400]
            debug_artifacts = getattr(e, "debug_artifacts", None)
            if debug_artifacts:
                fail_label = f"{last}_{first}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-FAILED"
                try:
                    debug_link = sheets_backend.upload_debug_artifacts(spreadsheet_id, debug_artifacts, fail_label)
                    note = f"{note}\n\nScreenshot/HTML: {debug_link}"
                except Exception as upload_err:
                    log(f"  (couldn't upload debug artifacts: {upload_err})")
            sheets_backend.set_status(spreadsheet_id, column_letter, sheets_backend.ERROR_STATUS, note=note)
            continue

        run_label = f"{last}_{first}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        try:
            link = sheets_backend.upload_run_output(spreadsheet_id, out_path, run_label)
        except Exception as e:
            log(f"Applicant {column_letter}: PDF created locally but Drive upload failed: {e}")
            sheets_backend.set_status(
                spreadsheet_id, column_letter, sheets_backend.ERROR_STATUS,
                note=f"PDF generated locally ({out_path}) but Drive upload failed: {e}"[:400],
            )
            continue

        sheets_backend.set_status(spreadsheet_id, column_letter, sheets_backend.DONE_STATUS, note=link)
        log(f"Applicant {column_letter} done: {link}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True, help="Client's Google Sheet URL or spreadsheet ID")
    parser.add_argument("--column", required=False,
                         help="Process only this column, regardless of Status (testing). "
                              "Omit to process all Status=Ready columns.")
    args = parser.parse_args()

    spreadsheet_id = sheets_backend.resolve_to_spreadsheet_id(args.sheet)
    run_all(spreadsheet_id, only_column=args.column)
