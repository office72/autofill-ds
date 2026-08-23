"""
Reads a new client's uploaded documents (Fillout submission export, passport
photo/scan, Israeli bilingual birth-certificate photo/scan, and/or US
citizenship-evidence documents - Certificate of Citizenship/Naturalization,
CRBA, US birth certificate) from their Drive folder and fills the
"Applicants" tab of their existing AUTOFILL Sheet copy, ready for staff
review (Status=Needs Review -> staff checks against the original documents
-> Status=Ready -> run_autofill.py can run).

Deliberately, completely separate from run_autofill.py - the only thing the
two scripts share is the Sheet itself, via the Status column. No imports
between them, no shared code.

Manual trigger only, per client - never automatic (matches the rest of this
project and the sibling document-analyzer project).
"""

import argparse
import base64
import html
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

# Windows consoles default to a codepage (cp1252 etc.) that can't encode
# Hebrew - and client filenames/folder names are routinely Hebrew. Without
# this, printing progress ("<file>: PASSPORT") crashes the whole run.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-5"
OPUS_MODEL = "claude-opus-5"
# Opus, not Sonnet/Haiku, for the passport/birth-certificate vision reads -
# these are the fields that go straight onto a legal US government form
# with no independent second check, so accuracy matters more than the
# (negligible, see project memory) cost difference here.
# Sonnet, not Haiku, for text extraction/transliteration - confirmed live
# 2026-08-13: Haiku produced a different, wrong Israeli city name on 3
# identical re-runs of the same input ("Rishon LeZion" -> "Raanana Lezion"
# -> "Ramat Hasharon") instead of reliably transcribing what was actually
# written. Cost difference is negligible either way (see project memory).


def _get_credentials():
    """Local runs (staff terminal) authenticate with the key file sitting
    next to this script. A Cloud Run deployment has no key file at all -
    it authenticates as its attached service account automatically via
    Application Default Credentials instead, which needs no secret to be
    mounted/managed for this at all. Same underlying service account
    either way, so behavior is identical - just no local file in the
    cloud."""
    if SERVICE_ACCOUNT_FILE.exists():
        return service_account.Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    import google.auth
    creds, _ = google.auth.default(scopes=SCOPES)
    return creds


def get_drive_service():
    return build("drive", "v3", credentials=_get_credentials())


def get_sheets_service():
    return build("sheets", "v4", credentials=_get_credentials())


def fetch_doc_text(drive, doc_id: str) -> str:
    """Google Docs export as plain text - works for the Fillout submission
    summary doc without needing the Docs API (which isn't enabled on this
    project; Drive's export endpoint is enough and already-enabled)."""
    content = drive.files().export(fileId=doc_id, mimeType="text/plain").execute()
    return content.decode("utf-8") if isinstance(content, bytes) else content


def extract_docx_text(file_bytes: bytes) -> str:
    """A .docx is a zip archive with the real text inside
    word/document.xml - reading it directly (stdlib zipfile + a regex strip
    of XML tags) avoids adding python-docx as a dependency just for this.
    Needed because a Fillout submission doesn't always end up in the
    client's folder as a native Google Doc - confirmed live 2026-08-19: a
    real client's Fillout export had been saved/uploaded as an actual
    .docx file, which this pipeline silently never looked at at all before
    this, dropping everything in it (address, height, emergency contact)."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    text = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(text)


# ---------------------------------------------------------------------------
# Country-of-Birth sanity check - confirmed live 2026-08-23: a passport
# vision extraction hallucinated "Outagamie" (a WISCONSIN COUNTY, not a
# country at all) into "Country of Birth" for a passport whose bio page
# only prints "WISCONSIN, U.S.A." with no county/city shown anywhere - a
# real Opus hallucination, not a code bug, and not reproducible on retry.
# Because that value happened to not match the site's dropdown, the run
# crashed loudly and got caught - but a hallucinated value that DID happen
# to look like a real country would have gone completely unnoticed straight
# into a real government form. This is a defensive backstop, not a fix for
# the hallucination itself (which can't be prevented with certainty) - it
# just refuses to let a "Country of Birth" value survive if it isn't
# actually a country, dropping it (safe - a human reviews the blank field)
# rather than passing through - the same "missing is safe, wrong isn't"
# principle used everywhere else in this file.
# ---------------------------------------------------------------------------

_COUNTRY_NAMES = {
    "AFGHANISTAN", "ALBANIA", "ALGERIA", "ANDORRA", "ANGOLA", "ANTIGUA AND BARBUDA",
    "ARGENTINA", "ARMENIA", "AUSTRALIA", "AUSTRIA", "AZERBAIJAN", "BAHAMAS", "BAHRAIN",
    "BANGLADESH", "BARBADOS", "BELARUS", "BELGIUM", "BELIZE", "BENIN", "BHUTAN",
    "BOLIVIA", "BOSNIA AND HERZEGOVINA", "BOTSWANA", "BRAZIL", "BRUNEI", "BULGARIA",
    "BURKINA FASO", "BURUNDI", "CABO VERDE", "CAMBODIA", "CAMEROON", "CANADA",
    "CENTRAL AFRICAN REPUBLIC", "CHAD", "CHILE", "CHINA", "COLOMBIA", "COMOROS",
    "CONGO", "COSTA RICA", "CROATIA", "CUBA", "CYPRUS", "CZECHIA", "CZECH REPUBLIC",
    "DENMARK", "DJIBOUTI", "DOMINICA", "DOMINICAN REPUBLIC", "ECUADOR", "EGYPT",
    "EL SALVADOR", "EQUATORIAL GUINEA", "ERITREA", "ESTONIA", "ESWATINI", "ETHIOPIA",
    "FIJI", "FINLAND", "FRANCE", "GABON", "GAMBIA", "GEORGIA", "GERMANY", "GHANA",
    "GREECE", "GRENADA", "GUATEMALA", "GUINEA", "GUINEA-BISSAU", "GUYANA", "HAITI",
    "HONDURAS", "HUNGARY", "ICELAND", "INDIA", "INDONESIA", "IRAN", "IRAQ", "IRELAND",
    "ISRAEL", "ITALY", "IVORY COAST", "JAMAICA", "JAPAN", "JORDAN", "KAZAKHSTAN",
    "KENYA", "KIRIBATI", "KOSOVO", "KUWAIT", "KYRGYZSTAN", "LAOS", "LATVIA", "LEBANON",
    "LESOTHO", "LIBERIA", "LIBYA", "LIECHTENSTEIN", "LITHUANIA", "LUXEMBOURG",
    "MADAGASCAR", "MALAWI", "MALAYSIA", "MALDIVES", "MALI", "MALTA",
    "MARSHALL ISLANDS", "MAURITANIA", "MAURITIUS", "MEXICO", "MICRONESIA", "MOLDOVA",
    "MONACO", "MONGOLIA", "MONTENEGRO", "MOROCCO", "MOZAMBIQUE", "MYANMAR", "NAMIBIA",
    "NAURU", "NEPAL", "NETHERLANDS", "NEW ZEALAND", "NICARAGUA", "NIGER", "NIGERIA",
    "NORTH KOREA", "NORTH MACEDONIA", "NORWAY", "OMAN", "PAKISTAN", "PALAU",
    "PALESTINE", "PANAMA", "PAPUA NEW GUINEA", "PARAGUAY", "PERU", "PHILIPPINES",
    "POLAND", "PORTUGAL", "QATAR", "ROMANIA", "RUSSIA", "RWANDA",
    "SAINT KITTS AND NEVIS", "SAINT LUCIA", "SAINT VINCENT AND THE GRENADINES",
    "SAMOA", "SAN MARINO", "SAO TOME AND PRINCIPE", "SAUDI ARABIA", "SENEGAL",
    "SERBIA", "SEYCHELLES", "SIERRA LEONE", "SINGAPORE", "SLOVAKIA", "SLOVENIA",
    "SOLOMON ISLANDS", "SOMALIA", "SOUTH AFRICA", "SOUTH KOREA", "SOUTH SUDAN",
    "SPAIN", "SRI LANKA", "SUDAN", "SURINAME", "SWEDEN", "SWITZERLAND", "SYRIA",
    "TAIWAN", "TAJIKISTAN", "TANZANIA", "THAILAND", "TIMOR-LESTE", "TOGO", "TONGA",
    "TRINIDAD AND TOBAGO", "TUNISIA", "TURKEY", "TURKMENISTAN", "TUVALU", "UGANDA",
    "UKRAINE", "UNITED ARAB EMIRATES", "UNITED KINGDOM", "URUGUAY", "UZBEKISTAN",
    "VANUATU", "VATICAN CITY", "VENEZUELA", "VIETNAM", "YEMEN", "ZAMBIA", "ZIMBABWE",
    # Common aliases/variants seen in real extractions
    "USA", "UNITED STATES", "UNITED STATES OF AMERICA", "U.S.A.", "U.S.",
    "UK", "U.K.", "GREAT BRITAIN", "ENGLAND", "SCOTLAND", "WALES",
    "IVORY COAST", "COTE D'IVOIRE", "CÔTE D'IVOIRE",
}


def _validate_country_of_birth(data: dict, source_label: str) -> dict:
    country = data.get("Country of Birth")
    if country and country.strip().upper() not in _COUNTRY_NAMES:
        print(f"  WARNING: dropping implausible Country of Birth {country!r} from {source_label} - not a recognized country name")
        data.pop("Country of Birth")
    return data


# ---------------------------------------------------------------------------
# Fillout extraction - one Haiku call, structured output.
#
# Fillout's export is the SAME fixed form every time (question -> answer
# text blocks), so the *structure* is reliable - but several answers arrive
# jumbled (the question's own sub-labels bleed into the answer text, e.g.
# "פרטי, משפחה דוד, בן סימון" for a first/last name pair) in a way that's
# risky to regex reliably. One batched Haiku call (cheap - short text, no
# vision) both untangles those and transliterates Hebrew values into the
# English the government form needs - safer than hardcoded per-field regex,
# and cheaper than doing it per-field. Fields the Fillout form doesn't give
# reliable signal for (Passport Scenario, Book fields, Name Change fields,
# Lost/Stolen report, Parent-Unknown flags, Spouse fields) are deliberately
# NOT asked for here - left for staff to fill after reviewing documents,
# per the "don't guess, flag for review" pattern already established in the
# sibling document-analyzer project.
# ---------------------------------------------------------------------------

FILLOUT_TARGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "First Name": {"type": ["string", "null"]},
        "Middle Name": {"type": ["string", "null"]},
        "Last Name": {"type": ["string", "null"]},
        "City of Birth": {"type": ["string", "null"]},
        # Deliberately no "Country of Birth" or "Sex" here - this Fillout
        # form doesn't ask either one, so any value for them would have to
        # be an inference (from a city name, from a first name) rather than
        # a real answer. Per the user (2026-08-13): both will come from the
        # passport-photo/birth-certificate vision step instead, which
        # actually shows them - the right fix is to not ask a source that
        # can't answer, not to keep tightening a "don't guess" instruction.
        "Hair Color": {"type": "string", "enum": ["BLACK", "BLONDE", "BROWN", "RED", "GRAY", "BALD", "OTHER"]},
        "Eye Color": {"type": "string", "enum": ["AMBER", "BLACK", "BLUE", "BROWN", "GRAY", "GREEN", "HAZEL"]},
        "Occupation": {"type": ["string", "null"]},
        "Employer": {"type": ["string", "null"]},
        "SSN": {
            "type": ["string", "null"],
            "description": "Digits only, no dashes. Leave null if the form's answer is an obvious placeholder rather than a real number (all zeros, all the same digit, or fewer than 9 digits) - a scanned SSN card is a better source when one exists, and a fake-looking number in the Sheet is worse than a blank one.",
        },
        "height_feet_decimal": {
            "type": ["number", "null"],
            "description": "Raw decimal-feet height value as given in the form (e.g. 5.64), if present. Do not convert - a later step does the feet/inches math.",
        },
        "Ever Married?": {"type": "string", "enum": ["Yes", "No"]},
        "Parent 1 First & Middle Name": {"type": ["string", "null"]},
        "Parent 1 Last Name": {"type": ["string", "null"]},
        "Parent 1 Date of Birth": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Parent 1 Place of Birth": {"type": ["string", "null"], "description": "City, Country - English"},
        "Parent 1 US Citizen?": {"type": "string", "enum": ["Yes", "No"]},
        "Parent 2 First & Middle Name": {"type": ["string", "null"]},
        "Parent 2 Last Name": {"type": ["string", "null"]},
        "Parent 2 Date of Birth": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Parent 2 Place of Birth": {"type": ["string", "null"], "description": "City, Country - English"},
        "Parent 2 US Citizen?": {"type": "string", "enum": ["Yes", "No"]},
        "Mail Street": {"type": ["string", "null"]},
        "Mail City": {"type": ["string", "null"]},
        "Mail Country": {"type": ["string", "null"], "description": "English, e.g. 'Israel'"},
        "Mail Zip": {"type": ["string", "null"]},
        "Email": {"type": ["string", "null"]},
        "Phone": {
            "type": ["string", "null"],
            "description": "The applicant's own primary contact phone (mobile/cell), digits only no leading +. This is the person's own number - not the emergency contact's, which is a separate EC Phone field.",
        },
        "Trip Date": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Trip Return Date": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Countries To Be Visited": {"type": ["string", "null"]},
        "EC Name": {"type": ["string", "null"], "description": "Emergency contact full name - English"},
        "EC Relationship": {"type": ["string", "null"], "description": "English, e.g. 'Mother'"},
        "EC Phone": {"type": ["string", "null"], "description": "Digits only, no leading +"},
        "EC Address": {"type": ["string", "null"], "description": "Street + house number - English"},
        "EC City": {"type": ["string", "null"]},
        "EC Country": {"type": ["string", "null"]},
        "EC Zip": {"type": ["string", "null"]},
        "EC Email": {
            "type": ["string", "null"],
            "description": "Emergency contact's email address - required by the actual government site even though it's easy to overlook (confirmed live: the site rejects an empty value with 'Incorrect email address', not a 'required field' message)",
        },
    },
}

FILLOUT_SYSTEM_PROMPT = """\
You are extracting data from a Fillout web-form submission (Israeli client
applying for a US passport) into English fields for a US government form.

The raw text below is question-then-answer pairs exported from the form.
Some answers arrived jumbled - the form's own sub-question labels bled into
the answer text (e.g. a name field's answer might look like
"פרטי, משפחה דוד, בן סימון" where "פרטי, משפחה" = "first name, last name"
are the labels and "דוד" / "בן סימון" are the actual values - First="David",
Last="Ben Simon"). Untangle these the same way.

CRITICAL RULES:
- Transliterate Hebrew names/places into English using standard passport-
  style phonetic transliteration (not translation) - e.g. "חולון"->"Holon",
  "תל אביב"->"Tel Aviv", "בן סימון"->"Ben Simon". Keep already-English/
  numeric answers exactly as given (emails, digit phone numbers, dates,
  zip codes).
- If a field's value is unclear, contradictory, or simply not present in
  the text, leave it null. Never guess or invent a value - a human reviews
  every field against the original documents afterward, so a missing field
  is safe and a wrong one is not.
- This also means: never INFER a fact that was not explicitly stated, even
  if it seems obvious. Confirmed live mistake: the form asked only for
  "city of birth" (answer: "Hollywood") with no separate country-of-birth
  question anywhere in the form, and a country was still filled in as
  "United States" - purely from assuming what country that city is in.
  That is exactly the failure mode to avoid: a city name is NOT evidence
  of a country unless the country is also written somewhere in the text.
  Only fill a field from information that is actually written in the
  submission - never from your own world knowledge about a place, name, or
  fact mentioned in it.
- Dates: output as MM/DD/YYYY. The source data is usually already
  YYYY-MM-DD (ISO) - convert the order, don't just relabel it.
- Phone numbers: digits only, no "+", no dashes, no spaces.
- Do not compute height feet/inches - just copy the raw decimal number
  (e.g. "5.64") into height_feet_decimal.
"""


def _extract_first_json_object(text: str) -> dict:
    """Structured outputs (output_config.format) hit a hard 24-optional-
    field limit that this schema exceeds - fall back to plain prompting +
    robust parsing instead, same pattern already proven in the sibling
    document-analyzer project: despite "only JSON" instructions, the model
    sometimes wraps the object in prose - find the first balanced {...} by
    real brace-depth counting (not just first-{-to-last-}), not the whole
    response."""
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in model response: {text!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError(f"Unbalanced JSON in model response: {text!r}")


def _field_hint_lines(schema: dict) -> str:
    """Human-readable field list for the prompt - deliberately NOT a raw
    dump of the JSON Schema types. Confirmed live: showing the model
    {"Sex": ["string", "null"]} as a "this is the shape" hint caused it to
    literally echo the word "string" back as a fake value for fields it had
    no real data for, instead of omitting them - the schema became a
    template it filled in rather than a type description."""
    lines = []
    for key, spec in schema["properties"].items():
        if key == "height_feet_decimal":
            lines.append(f'- "{key}": the raw decimal number, e.g. 5.64 (a number, not text)')
        elif "enum" in spec:
            lines.append(f'- "{key}": one of {spec["enum"]} (exact spelling)')
        else:
            desc = spec.get("description", "free text")
            lines.append(f'- "{key}": {desc}')
    return "\n".join(lines)


def extract_fillout_data(fillout_text: str) -> dict:
    # max_tokens raised from 2000 - root-caused live 2026-08-19: this call
    # was crashing scan_and_build outright (unhandled ValueError, killing
    # the whole scan, not just this one field) with the JSON response cut
    # off mid-value. Direct inspection of the API response showed why:
    # Sonnet was silently spending over 1000 tokens on invisible extended
    # thinking before writing the visible JSON, with no `thinking` param
    # ever requested - thinking tokens count against max_tokens, so a
    # short budget can leave too little room for the actual answer even
    # though the "real" output is small. Same risk applies to every other
    # extractor in this file (all bumped for the same reason) - this
    # wasn't a fillout-specific problem, just the one that happened to get
    # caught first.
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=4000,
        system=(
            FILLOUT_SYSTEM_PROMPT
            + "\n\nRespond with ONLY a JSON object (no other text). Possible keys, "
            + f"and what each one means:\n{_field_hint_lines(FILLOUT_TARGET_SCHEMA)}\n\n"
            + "Include a key ONLY when the text above actually contains a value "
            + "for it (this can be a real answer of \"none\"/\"unemployed\"/etc. "
            + "- that counts as a value). Do not include a key at all if there is "
            + 'no answer for it in the text - never invent a placeholder like '
            + '"string" or "N/A" or "unknown" or your own guess just to fill the '
            + "key in. An omitted key and a wrong value are not equally bad - a "
            + "wrong or fabricated value is far worse, because nothing will flag "
            + "it for the human reviewer to catch."
        ),
        messages=[{"role": "user", "content": fillout_text}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = _extract_first_json_object(text)

    feet_decimal = data.pop("height_feet_decimal", None)
    if feet_decimal is not None:
        feet = int(feet_decimal)
        inches = round((feet_decimal - feet) * 12)
        if inches == 12:
            feet, inches = feet + 1, 0
        data["Height Feet"] = str(feet)
        data["Height Inches"] = str(inches)

    for phone_field in ("Phone", "EC Phone"):
        if data.get(phone_field):
            data[phone_field] = _local_israeli_phone(data[phone_field])

    return {k: v for k, v in data.items() if v not in (None, "")}


def _local_israeli_phone(digits: str) -> str:
    """Per the user (2026-08-23): prefer local Israeli format (leading 0)
    over the international one (972 country code) for readability, but
    ONLY when the number is actually Israeli - there's no equivalent
    "drop the country code, add a 0" convention for other countries, so a
    foreign number is left exactly as extracted (still just digits, no
    "+", which is already safe - see the Sheets-arithmetic bug elsewhere
    in this project). Detection: Israeli mobile/landline numbers are 9
    digits after the "972" country code (e.g. 972 533587247 -> 0533587247).
    Also catches the same number missing its leading 0 with NO country
    code either (confirmed live 2026-08-23: a real Fillout answer for EC
    Phone was typed as bare "544377954", 9 digits starting with the
    Israeli mobile prefix 5x - not something the country-code check above
    catches at all, since there's no "972" to strip)."""
    if digits.startswith("972") and len(digits) == 12:
        return "0" + digits[3:]
    if len(digits) == 9 and digits[0] == "5":
        return "0" + digits
    return digits


# ---------------------------------------------------------------------------
# Passport photo/scan extraction - one Opus vision call.
#
# Deliberately scoped to only the fields an actual passport bio page can
# show. "Country of Birth" and "Sex" live here (not in the Fillout step)
# specifically because this is a real source for them, per the user
# (2026-08-13): the Fillout form never asks either one, so anything filled
# there would be inference, not a read.
#
# The "MOST RECENT PASSPORT" fields (Book Number, Name On Book, Book Issue
# Date) are here too - a passport photo IS the previous book itself when a
# client has one, so it's the natural source for those, not a separate
# document.
# ---------------------------------------------------------------------------

PASSPORT_TARGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "First Name": {"type": ["string", "null"], "description": "Given name(s) exactly as printed"},
        "Middle Name": {"type": ["string", "null"]},
        "Last Name": {"type": ["string", "null"], "description": "Surname exactly as printed, including hyphens"},
        "Sex": {"type": "string", "enum": ["Male", "Female"]},
        "Date of Birth": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Country of Birth": {
            "type": ["string", "null"],
            "description": "English. The passport's place-of-birth line usually reads either 'CITY, COUNTRY' or, for US-born people, just a US STATE name with no country word written - if it's a US state, Country of Birth is 'USA'.",
        },
        "State of Birth (USA only)": {
            "type": ["string", "null"],
            "description": "Only if place of birth shown is a US state (e.g. 'FLORIDA'). Leave null if born outside the US or if a city/country is shown instead.",
        },
        "City of Birth": {
            "type": ["string", "null"],
            "description": "Only fill this if the place-of-birth line actually shows a city (typically true for non-US-born people). US passports usually show only the state for US-born people, with no city at all - leave null in that case, do not guess a city.",
        },
        "Book Number": {"type": ["string", "null"], "description": "This passport's own document/passport number"},
        "Name On Book - First": {"type": ["string", "null"], "description": "Given name(s) exactly as printed on this passport - may differ from First Name if unsure, but normally the same"},
        "Name On Book - Last": {"type": ["string", "null"], "description": "Surname exactly as printed on this passport"},
        "Book Issue Date": {"type": ["string", "null"], "description": "MM/DD/YYYY - the 'Date of issue' field"},
    },
}

PASSPORT_SYSTEM_PROMPT = """\
You are reading the photo/bio page of a US passport belonging to an Israeli
client applying (or renewing) at American Docs. Extract only what is
actually printed on the page image.

CRITICAL RULES:
- Read exactly what is printed - this is an official document, not a form
  answer, so there is no transliteration to do. Keep names, including
  hyphens and spacing, exactly as printed (e.g. "BEN-SIMON" stays
  "BEN-SIMON", not "Ben Simon").
- Never guess or infer a value that is not visibly printed on the page.
  If a field is blurry, cut off, or not present on this document, leave it
  null - a human reviews every field against the original document
  afterward, so a missing field is safe and a wrong or invented one is not.
- The "Place of birth" line on a US passport is written differently
  depending on whether the person was born in the US or abroad: for
  US-born people it typically shows ONLY a state name (e.g. "FLORIDA
  U.S.A." or just "FLORIDA") with no city; for people born abroad it
  typically shows "CITY, COUNTRY". Follow exactly what is printed - do not
  assume a city exists just because a person was born in a specific place.
- Dates: output as MM/DD/YYYY, converting from whatever order is printed.
- If any field's value is genuinely ambiguous between two readings, leave
  it null rather than picking one.
"""


def _content_block(file_bytes: bytes, mime_type: str) -> dict:
    """Claude vision takes PDFs as a "document" block and images as an
    "image" block - same base64 encoding either way."""
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    block_type = "document" if mime_type == "application/pdf" else "image"
    return {"type": block_type, "source": {"type": "base64", "media_type": mime_type, "data": b64}}


def extract_passport_data(image_bytes: bytes, mime_type: str) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=3000,  # headroom against invisible thinking tokens - see extract_fillout_data
        system=(
            PASSPORT_SYSTEM_PROMPT
            + "\n\nRespond with ONLY a JSON object (no other text). Possible keys, "
            + f"and what each one means:\n{_field_hint_lines(PASSPORT_TARGET_SCHEMA)}\n\n"
            + "Include a key ONLY when the page actually shows a value for it. "
            + 'Do not include a key at all if there is no visible value for it - '
            + 'never invent a placeholder like "string" or "N/A" or your own '
            + "guess just to fill the key in. An omitted key and a wrong value "
            + "are not equally bad - a wrong or fabricated value is far worse, "
            + "because nothing will flag it for the human reviewer to catch."
        ),
        messages=[
            {
                "role": "user",
                "content": [_content_block(image_bytes, mime_type), {"type": "text", "text": "Extract the fields from this passport page."}],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = _extract_first_json_object(text)
    data = {k: v for k, v in data.items() if v not in (None, "")}
    return _validate_country_of_birth(data, "passport")


def fetch_drive_file_bytes(drive, file_id: str) -> tuple[bytes, str]:
    meta = drive.files().get(fileId=file_id, fields="mimeType,name", supportsAllDrives=True).execute()
    mime_type = meta["mimeType"]
    content = drive.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
    return content, mime_type


# ---------------------------------------------------------------------------
# Bilingual birth-certificate extraction - one Opus vision call.
#
# Israeli Ministry of Interior birth certificates ("תעודת לידה") are issued
# bilingually - Hebrew and an official English translation printed on the
# SAME page, side by side. That official English text is a better source
# for a person's name/place spelling than fresh transliteration, per the
# user's explicit priority rule (2026-08-13): prefer an existing official
# English spelling over transliterating it again. So this step is
# deliberately a plain READ of the document's own printed English column,
# not a translation task.
# ---------------------------------------------------------------------------

BIRTH_CERT_TARGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "First Name": {"type": ["string", "null"], "description": "Child's given name, from the English column"},
        "Last Name": {"type": ["string", "null"], "description": "Child's surname, from the English column"},
        "Sex": {"type": "string", "enum": ["Male", "Female"]},
        "Date of Birth": {
            "type": ["string", "null"],
            "description": "MM/DD/YYYY, converted from the certificate's 'Gregorian date' field. That field is printed DD/MM/YYYY (Israeli convention) - convert the order, don't just relabel it. Ignore the separate Hebrew-calendar date field entirely.",
        },
        "City of Birth": {"type": ["string", "null"], "description": "From the 'Place of birth' English column"},
        "Country of Birth": {
            "type": ["string", "null"],
            "description": "Fill with 'Israel' only if the certificate's own letterhead/header visibly identifies the issuer as the State of Israel (Ministry of Interior / Population and Immigration Authority) - this is reading the document's own header, not inferring a country from the city name. Leave null if you can't see that header clearly.",
        },
        "Parent 1 First & Middle Name": {
            "type": ["string", "null"],
            "description": "Father's given name, from the English column ('Given name of father'). Do not fill in a last name - only what's actually printed as the given name.",
        },
        "Parent 2 First & Middle Name": {
            "type": ["string", "null"],
            "description": "Mother's given name, from the English column ('Given name of mother'). Do not fill in a last name - only what's actually printed as the given name.",
        },
    },
}

BIRTH_CERT_SYSTEM_PROMPT = """\
You are reading an official Israeli Ministry of Interior birth certificate
("תעודת לידה" / BIRTH CERTIFICATE) for an Israeli client applying for a US
passport at American Docs. The document is bilingual - Hebrew text on one
side, an OFFICIAL ENGLISH TRANSLATION already printed by the Israeli
government on the same page.

CRITICAL RULES:
- Always read values from the document's own printed ENGLISH column/text.
  Do not transliterate the Hebrew side yourself - the government has
  already printed an official English spelling right there, and it must be
  used verbatim (including exactly how it's capitalized/spelled), even if
  it looks different from what you might have transliterated on your own.
- Never guess or infer a value that is not visibly printed on the page. A
  human reviews every field against the original document afterward, so a
  missing field is safe and a wrong or invented one is not.
- "Nationality" on this document (לאום) means ethnic/religious nationality
  (e.g. "JEWISH", "ARAB", "DRUZE") - it is NOT a country and is NOT
  relevant to any field you're asked for. Do not confuse it with country of
  birth or citizenship.
- Dates: the certificate has TWO date fields - a Gregorian date and a
  separate Hebrew-calendar date. Only use the Gregorian one. It's printed
  DD/MM/YYYY (Israeli convention, day first) - convert to MM/DD/YYYY,
  don't just relabel the same digit order.
- If any field's value is genuinely ambiguous or not clearly legible, leave
  it null rather than guessing.
"""


def extract_birth_cert_data(file_bytes: bytes, mime_type: str) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=3000,  # headroom against invisible thinking tokens - see extract_fillout_data
        system=(
            BIRTH_CERT_SYSTEM_PROMPT
            + "\n\nRespond with ONLY a JSON object (no other text). Possible keys, "
            + f"and what each one means:\n{_field_hint_lines(BIRTH_CERT_TARGET_SCHEMA)}\n\n"
            + "Include a key ONLY when the page actually shows a value for it. "
            + 'Do not include a key at all if there is no visible value for it - '
            + 'never invent a placeholder like "string" or "N/A" or your own '
            + "guess just to fill the key in. An omitted key and a wrong value "
            + "are not equally bad - a wrong or fabricated value is far worse, "
            + "because nothing will flag it for the human reviewer to catch."
        ),
        messages=[
            {
                "role": "user",
                "content": [_content_block(file_bytes, mime_type), {"type": "text", "text": "Extract the fields from this birth certificate."}],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = _extract_first_json_object(text)
    data = {k: v for k, v in data.items() if v not in (None, "")}
    return _validate_country_of_birth(data, "birth certificate")


# ---------------------------------------------------------------------------
# Citizenship-evidence extraction - a Certificate of Citizenship/
# Naturalization (USCIS-issued), a Consular Report of Birth Abroad (CRBA/
# FS-240, issued by a US embassy/consulate for a child born abroad to a US
# citizen parent), or a US-issued (domestic) birth certificate. Grouped
# into one extractor since all three ultimately just corroborate the same
# identity/birth fields already on the sheet - the Sheet has no field
# unique to any one of these document types except USCIS A-Number, which
# only a Certificate of Citizenship/Naturalization actually has.
# ---------------------------------------------------------------------------

CITIZENSHIP_EVIDENCE_TARGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "First Name": {"type": ["string", "null"], "description": "Given name(s) exactly as printed"},
        "Middle Name": {"type": ["string", "null"]},
        "Last Name": {"type": ["string", "null"], "description": "Surname exactly as printed"},
        "Sex": {"type": "string", "enum": ["Male", "Female"]},
        "Date of Birth": {"type": ["string", "null"], "description": "MM/DD/YYYY"},
        "Country of Birth": {
            "type": ["string", "null"],
            "description": "English. If the document shows a US state as place of birth, this is 'USA'. A CRBA normally shows a foreign country instead (the child was born abroad) - use that country, not USA.",
        },
        "State of Birth (USA only)": {"type": ["string", "null"], "description": "Only if place of birth shown is a US state"},
        "City of Birth": {"type": ["string", "null"], "description": "Only if a city is actually shown"},
        "USCIS A-Number": {
            "type": ["string", "null"],
            "description": "Only present on a Certificate of Citizenship/Naturalization (the 'A-Number'/Registration Number, e.g. A123456789). A CRBA or a plain birth certificate normally has no A-Number at all - leave null rather than guessing one exists.",
        },
        "Parent 1 First & Middle Name": {
            "type": ["string", "null"],
            "description": "The FATHER's given name(s), only if a father/mother table is actually printed on this document (a full CRBA/FS-240 has one; a Certificate of Citizenship or a plain birth certificate usually doesn't) - leave null if there's no such table at all.",
        },
        "Parent 1 Last Name": {"type": ["string", "null"], "description": "Father's surname, from the same table"},
        "Parent 1 Date of Birth": {"type": ["string", "null"], "description": "Father's date of birth, MM/DD/YYYY, from the same table"},
        "Parent 1 Place of Birth": {"type": ["string", "null"], "description": "Father's place of birth (City, Country - English), from the same table"},
        "Parent 1 Sex": {
            "type": "string",
            "enum": ["Male", "Female"],
            "description": "Always 'Male' when a father's row is present at all - this reads the document's own column header ('FATHER'), not a guess",
        },
        "Parent 1 US Citizen?": {
            "type": "string",
            "enum": ["Yes", "No"],
            "description": "From the 'Evidence of U.S. Citizenship' column for the father: 'Yes' if it shows a US passport number, naturalization details, or otherwise documents US citizenship; 'No' if it explicitly states a foreign nationality (e.g. 'Panamanian citizen'). Leave null if that column is blank or unclear - don't assume citizenship just because he's the reason this CRBA exists.",
        },
        "Parent 2 First & Middle Name": {"type": ["string", "null"], "description": "The MOTHER's given name(s), same conditions as Parent 1"},
        "Parent 2 Last Name": {
            "type": ["string", "null"],
            "description": "Mother's surname as currently used (the document may show 'Nee X' for her maiden name separately - use her main/married name here, not the maiden name)",
        },
        "Parent 2 Date of Birth": {"type": ["string", "null"], "description": "Mother's date of birth, MM/DD/YYYY"},
        "Parent 2 Place of Birth": {"type": ["string", "null"], "description": "Mother's place of birth (City, Country - English)"},
        "Parent 2 Sex": {"type": "string", "enum": ["Male", "Female"], "description": "Always 'Female' when a mother's row is present - reads the column header, not a guess"},
        "Parent 2 US Citizen?": {"type": "string", "enum": ["Yes", "No"], "description": "Same logic as Parent 1 US Citizen?, for the mother's row"},
    },
}

CITIZENSHIP_EVIDENCE_SYSTEM_PROMPT = """\
You are reading one of three possible US citizenship-evidence documents for
an Israeli-based American Docs client applying for a US passport:
- A Certificate of Citizenship or Certificate of Naturalization (issued by
  USCIS - has an "A-Number"/Registration Number)
- A Consular Report of Birth Abroad (CRBA, Form FS-240, issued by a US
  embassy/consulate for a child born abroad to a US citizen parent)
- A US-issued (domestic) birth certificate

Extract only what is actually printed - this is an official document, not a
form answer, so copy names/places exactly as printed, no transliteration.

CRITICAL RULES:
- Never guess or infer a value that isn't visibly printed. If a field is
  blurry, cut off, or genuinely doesn't appear on this specific document
  (e.g. a CRBA or birth certificate normally has no A-Number at all), leave
  it null - a human reviews every field against the original document
  afterward, so a missing field is safe and a wrong or invented one is not.
- Dates: MM/DD/YYYY, converting from whatever order is printed.
- If the place of birth shown is a US state, Country of Birth is "USA". If
  it's a foreign country (typical for a CRBA, since the whole point of that
  document is a birth abroad), use that country - do not default to USA.
- A full CRBA (Form FS-240) has a father/mother table with each parent's
  name, date/place of birth, and citizenship evidence - extract it when
  present. Shorter documents (a plain Certificate of Citizenship, or an
  older short-form CRBA like Form FS-545) usually have no such table at
  all - leave all Parent fields null rather than guessing they exist.
"""


def extract_citizenship_evidence_data(file_bytes: bytes, mime_type: str) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=3000,  # headroom against invisible thinking tokens - see extract_fillout_data
        system=(
            CITIZENSHIP_EVIDENCE_SYSTEM_PROMPT
            + "\n\nRespond with ONLY a JSON object (no other text). Possible keys, "
            + f"and what each one means:\n{_field_hint_lines(CITIZENSHIP_EVIDENCE_TARGET_SCHEMA)}\n\n"
            + "Include a key ONLY when the page actually shows a value for it. "
            + 'Do not include a key at all if there is no visible value for it - '
            + 'never invent a placeholder like "string" or "N/A" or your own '
            + "guess just to fill the key in. An omitted key and a wrong value "
            + "are not equally bad - a wrong or fabricated value is far worse, "
            + "because nothing will flag it for the human reviewer to catch."
        ),
        messages=[
            {
                "role": "user",
                "content": [_content_block(file_bytes, mime_type), {"type": "text", "text": "Extract the fields from this citizenship-evidence document."}],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = _extract_first_json_object(text)
    data = {k: v for k, v in data.items() if v not in (None, "")}
    return _validate_country_of_birth(data, "citizenship evidence")


# ---------------------------------------------------------------------------
# SSN card extraction - a single field, but a real, common gap: the Fillout
# form's own SSN question is easy for a client to skip or fill with a
# placeholder (confirmed live 2026-08-19: a real submission had "000000000"
# typed in), while a photographed SSN card gives the actual number directly.
# ---------------------------------------------------------------------------

SSN_CARD_TARGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "First Name": {"type": ["string", "null"], "description": "From 'This number has been established for ...' - given name(s) exactly as printed, needed to match this card to the right applicant"},
        "Last Name": {"type": ["string", "null"], "description": "Surname exactly as printed, from the same line"},
        "SSN": {"type": ["string", "null"], "description": "The 9-digit Social Security number printed on the card, digits only, no dashes"},
    },
}

SSN_CARD_SYSTEM_PROMPT = """\
You are reading a US Social Security card. Extract the name it was issued
to ("This number has been established for...") and the 9-digit number
itself, as digits only (no dashes) - the name is needed only to match this
card to the right applicant when a folder has documents for more than one
person, not as a spelling source. If the card is blurry, cut off, or the
number isn't clearly legible, leave it null rather than guessing a digit.
"""


def extract_ssn_card_data(file_bytes: bytes, mime_type: str) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=1000,  # headroom against invisible thinking tokens - see extract_fillout_data
        system=(
            SSN_CARD_SYSTEM_PROMPT
            + "\n\nRespond with ONLY a JSON object (no other text). Possible keys, "
            + f"and what each one means:\n{_field_hint_lines(SSN_CARD_TARGET_SCHEMA)}\n\n"
            + "Include a key ONLY when the card actually shows a value for it. "
            + 'Do not include a key at all if there is no visible value for it - '
            + 'never invent a placeholder like "string" or "N/A" or your own '
            + "guess just to fill the key in."
        ),
        messages=[
            {
                "role": "user",
                "content": [_content_block(file_bytes, mime_type), {"type": "text", "text": "Extract the SSN from this card."}],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = _extract_first_json_object(text)
    return {k: v for k, v in data.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Document classification - one cheap Haiku vision call per image/PDF file
# found in a client's folder, so the expensive Opus extraction only runs on
# files actually worth it. Also drives the auto-rename the user asked for
# (2026-08-13): once a file's type is known, rename it in Drive so staff can
# see at a glance what's what.
# ---------------------------------------------------------------------------

def classify_document(file_bytes: bytes, mime_type: str, filename: str = "") -> str:
    # Sonnet, not Haiku - confirmed live 2026-08-13: Haiku misclassified a
    # filled-in DS-11 form PDF as PASSPORT on one run out of several
    # identical ones (same file, same folder, same code) - a filled DS-11
    # visually has passport-style photo/data fields, apparently confusing
    # enough for Haiku sometimes. Cost difference is negligible (see
    # project memory) and this gate decides whether an expensive Opus
    # extraction + a real Sheet write happens - worth paying for reliability.
    #
    # The filename is passed in as a hint (not the sole signal) - staff
    # already name these files descriptively in practice ("Guy Certificate
    # of Citizenship.pdf"), so it's cheap extra signal alongside the image.
    #
    # Root cause found live 2026-08-14, TWICE, for two different real
    # documents that were correctly read but still came back as OTHER:
    # max_tokens was too small to fit the label text itself, so the
    # response got silently cut off mid-word (first "CITIZENSHIP_" at
    # max_tokens=10, then "ISRAELI_BIRTH_CERTIFICAT" - missing the final
    # "E" - at max_tokens=20, confirmed via stop_reason="max_tokens" on
    # both), which then failed the `label in text` containment check and
    # fell through to the OTHER default. Not a model-capability issue at
    # all - confirmed Sonnet and Opus both classify these documents
    # correctly once the label is actually allowed to finish generating.
    # Fixed properly this time with real headroom (50, not a number just
    # barely bigger than the last failure) rather than chasing the exact
    # token count of the longest label - the output here is a few words at
    # most, so the cost of being generous is nothing. Kept on Opus anyway
    # (classification gates whether the expensive extraction+write happens
    # at all, so a false negative here is worse than Opus's still-
    # negligible extra cost - see project memory).
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=150,  # headroom against invisible thinking tokens - see extract_fillout_data
        system=(
            "Classify this document image/PDF. The filename may be a useful "
            "hint (staff often name files descriptively) but verify against "
            "the actual image content - don't trust the filename alone. "
            "Reply with EXACTLY one of these labels, nothing else:\n"
            "PASSPORT - a passport photo/bio page\n"
            "ISRAELI_BIRTH_CERTIFICATE - Israeli Ministry of Interior "
            "bilingual birth certificate (Hebrew + English, has a "
            "'תעודת לידה'/'BIRTH CERTIFICATE' header)\n"
            "CITIZENSHIP_EVIDENCE - a Certificate of Citizenship, "
            "Certificate of Naturalization, Consular Report of Birth "
            "Abroad (CRBA / Form FS-240), or a US-issued (not Israeli) "
            "birth certificate. Certificates of Citizenship/Naturalization "
            "are often ornate/decorative documents with cursive script "
            "body text inside a decorative border (they look more like a "
            "diploma/award than a plain bureaucratic form) - don't let that "
            "styling fool you into calling it OTHER. Look for phrasing like "
            "'CERTIFICATE OF CITIZENSHIP', 'Department of Homeland "
            "Security', or 'U.S. Citizenship and Immigration Services'.\n"
            "SSN_CARD - a US Social Security card ('SOCIAL SECURITY' "
            "header, a 9-digit number, 'This number has been established "
            "for...')\n"
            "OTHER - anything else at all (forms, payment receipts, sworn "
            "statements/affidavits, other ID cards, etc.)"
        ),
        messages=[
            {
                "role": "user",
                "content": [_content_block(file_bytes, mime_type), {"type": "text", "text": f"Filename: {filename}\n\nClassify this document."}],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text").strip().upper()
    for label in ("PASSPORT", "ISRAELI_BIRTH_CERTIFICATE", "CITIZENSHIP_EVIDENCE", "SSN_CARD"):
        if label in text:
            return label
    return "OTHER"


DOC_TYPE_LABELS = {
    "PASSPORT": "Passport",
    "ISRAELI_BIRTH_CERTIFICATE": "Birth Certificate",
    "SSN_CARD": "SSN Card",
    "CITIZENSHIP_EVIDENCE": "Citizenship Evidence",
}
EXTRACTORS_BY_TYPE = {
    "PASSPORT": extract_passport_data,
    "ISRAELI_BIRTH_CERTIFICATE": extract_birth_cert_data,
    "CITIZENSHIP_EVIDENCE": extract_citizenship_evidence_data,
    "SSN_CARD": extract_ssn_card_data,
}

# Fields that describe the family, not one specific applicant - siblings
# processed together from the same folder normally share these (same
# parents, same home address, same emergency contact, same trip), so if
# one sibling's own documents/Fillout submission don't mention a field
# here but another sibling's does, it gets copied across rather than left
# blank. Per the user (2026-08-13): "רוב המידע שווה... מה שחסר לקחת משני".
# Deliberately excludes every identity/per-person field (name, DOB, sex,
# height, passport/book fields, other-names, data-correction, lost/stolen)
# - those must never be copied between siblings.
SHARED_FAMILY_FIELDS = {
    "Mail Street", "Mail City", "Mail Country", "Mail State (USA only)", "Mail Zip",
    "In Care Of", "Same As Permanent Address?", "Permanent Street", "Permanent Apartment",
    "Permanent City", "Permanent Country", "Permanent State (USA only)", "Permanent Zip",
    "Preferred Communication", "Email", "Confirm Email",
    "EC Name", "EC Address", "EC Apartment", "EC City", "EC Country", "EC State (USA only)",
    "EC Zip", "EC Phone", "EC Email", "EC Relationship",
    "Parent 1 Unknown?", "Parent 1 First & Middle Name", "Parent 1 Last Name",
    "Parent 1 Date of Birth", "Parent 1 Place of Birth", "Parent 1 Sex", "Parent 1 US Citizen?",
    "Parent 2 Unknown?", "Parent 2 First & Middle Name", "Parent 2 Last Name",
    "Parent 2 Date of Birth", "Parent 2 Place of Birth", "Parent 2 Sex", "Parent 2 US Citizen?",
    "Trip Date", "Trip Return Date", "Countries To Be Visited",
}


def _fill_shared_family_fields(merged_by_key: dict) -> None:
    for field in SHARED_FAMILY_FIELDS:
        fill_value = next((d[field] for d in merged_by_key.values() if d.get(field)), None)
        if fill_value is None:
            continue
        for d in merged_by_key.values():
            d.setdefault(field, fill_value)


def find_client_sheet(drive, folder_id: str) -> str:
    """Every client folder has exactly one AUTOFILL Sheet copy in it - the
    "new client" Zoho button already creates it there. Auto-discovering it
    means the intake pipeline only needs one input, the folder, per the
    user (2026-08-13): "בתוך תיקיית הלקוח יהיה רק שיטס אחד"."""
    results = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.spreadsheet'",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    sheets = results.get("files", [])
    if len(sheets) == 0:
        raise ValueError("No Google Sheet found in this folder - has the client's AUTOFILL Sheet been created yet?")
    if len(sheets) > 1:
        names = ", ".join(f["name"] for f in sheets)
        raise ValueError(f"Found {len(sheets)} Google Sheets in this folder, expected exactly one: {names}")
    return sheets[0]["id"]


def scan_and_build(drive, folder_id: str, spreadsheet_id: str, rename_files: bool = True) -> tuple:
    """Auto-discovers every applicant's documents in a client's Drive
    folder, classifies+extracts each one, groups them by the identity
    (First+Last Name) read off the documents themselves - one group per
    child/applicant, in order of first appearance - fills in family-shared
    fields across siblings, then writes each group into its own Applicant
    column (1, 2, 3, ...) on the Sheet. Returns (per_applicant_summary,
    unmatched_fillout_docs).
    """
    listing = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    applicant_docs = []  # [{"type", "file_id", "name", "data"}]
    fillout_candidates = []  # [(file_id, name, text)]
    other_files = []  # filenames classified OTHER or otherwise not extracted - for the Notes summary

    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for f in listing.get("files", []):
        mime = f["mimeType"]
        if mime == "application/vnd.google-apps.document":
            fillout_candidates.append((f["id"], f["name"], fetch_doc_text(drive, f["id"])))
            continue
        if mime == DOCX_MIME:
            # A Fillout submission doesn't always land here as a native
            # Google Doc - it can be an actual uploaded .docx (confirmed
            # live 2026-08-19). Same question/answer text either way, so
            # it goes through the exact same extraction as a Google Doc.
            docx_bytes, _ = fetch_drive_file_bytes(drive, f["id"])
            fillout_candidates.append((f["id"], f["name"], extract_docx_text(docx_bytes)))
            continue
        if not (mime.startswith("image/") or mime == "application/pdf"):
            continue
        file_bytes, _ = fetch_drive_file_bytes(drive, f["id"])
        doc_type = classify_document(file_bytes, mime, filename=f["name"])
        print(f"  {f['name']}: {doc_type}")
        extractor = EXTRACTORS_BY_TYPE.get(doc_type)
        if extractor:
            applicant_docs.append({"type": doc_type, "file_id": f["id"], "name": f["name"], "data": extractor(file_bytes, mime)})
        else:
            other_files.append(f["name"])

    # Group by identity read off the documents - one group per applicant.
    # A group key ("passport"/"birth_cert"/"citizenship_evidence") is kept
    # per document TYPE, not just the last one seen, since an applicant can
    # have more than one type of evidence at once.
    #
    # Matching is First+Last exact match FIRST, but falls back to First
    # Name + Date of Birth against every existing group before deciding
    # this is a new person - confirmed live 2026-08-16: a real DS-82
    # renewal case (Lior) had an old passport reading "ISAK (KELMAN)" and
    # a newer one reading just "KELMAN" (a marriage-driven name change -
    # the folder also had a marriage certificate + translation), which an
    # exact-match-only key split into two separate phantom applicants.
    # Both documents had the identical Date of Birth, which a real name
    # change never touches - a much more reliable same-person signal than
    # trusting the surname to be spelled identically across documents that
    # literally exist because the surname changed.
    TYPE_TO_GROUP_KEY = {
        "PASSPORT": "passport",
        "ISRAELI_BIRTH_CERTIFICATE": "birth_cert",
        "CITIZENSHIP_EVIDENCE": "citizenship_evidence",
        "SSN_CARD": "ssn_card",
    }
    groups = {}
    order = []

    def _parse_mmddyyyy(date_str: str):
        parts = (date_str or "").split("/")
        if len(parts) != 3:
            return None
        try:
            month, day, year = (int(p) for p in parts)
            return (year, month, day)
        except ValueError:
            return None

    def _more_recent_passport(candidate: dict, current: dict) -> dict:
        """When a person has more than one passport-type document (a real
        DS-82 renewal case can have both the old and new book scanned) -
        confirmed live 2026-08-16 - keep the one with the more recent Book
        Issue Date rather than whichever file Drive's listing happened to
        return last. Falls back to keeping whichever has a parseable date
        at all, and only falls back to "last one wins" (the old behavior)
        when neither date is parseable - never worse than before, often
        better."""
        if current is None:
            return candidate
        c_date = _parse_mmddyyyy(candidate.get("Book Issue Date", ""))
        e_date = _parse_mmddyyyy(current.get("Book Issue Date", ""))
        if c_date and e_date:
            return candidate if c_date >= e_date else current
        if c_date and not e_date:
            return candidate
        if e_date and not c_date:
            return current
        return candidate  # neither parseable - preserve old "last one wins" behavior

    def _prefer_richer(candidate: dict, current: dict):
        """For any non-passport document type, when a person has more than
        one document of the same type (e.g. two citizenship-evidence scans
        - confirmed live 2026-08-19: one was a full FS-240 with a parent
        table, the other an older short-form CRBA without one), keep
        whichever extraction actually has more fields rather than letting
        whichever file Drive listed last blindly win and silently drop
        real data the other one had."""
        if current is None:
            return candidate
        return candidate if len(candidate) >= len(current) else current

    def _matching_group_key(first: str, last: str, dob: str):
        exact_key = (first, last)
        if exact_key in groups:
            return exact_key
        if first and dob:
            for key in order:
                for existing_entry in groups[key]["docs"]:
                    e_first = existing_entry["data"].get("First Name", "").strip().upper()
                    e_dob = existing_entry["data"].get("Date of Birth", "").strip()
                    if e_first == first and e_dob == dob:
                        return key
        return exact_key

    for entry in applicant_docs:
        first = entry["data"].get("First Name", "").strip().upper()
        last = entry["data"].get("Last Name", "").strip().upper()
        dob = entry["data"].get("Date of Birth", "").strip()
        if first == "" and last == "":
            # No name came back at all - either a misclassified non-
            # identity file slipped past classify_document(), or a real
            # document too illegible to read a name off of. Either way
            # there's no safe column to write it into (writing a phantom
            # applicant is worse than dropping it), so skip it entirely.
            print(f"  WARNING: skipping {entry['name']} ({entry['type']}) - no name could be extracted")
            continue
        key = _matching_group_key(first, last, dob)
        if key not in groups:
            groups[key] = {"docs": []}
            order.append(key)
            print(f"  applicant group: {key[0]} {key[1]}")
        elif key != (first, last):
            print(f"  {entry['name']} ({first} {last}, DOB {dob}) matched existing applicant {key[0]} {key[1]} by name+DOB, not exact name")
        groups[key]["docs"].append(entry)
        type_key = TYPE_TO_GROUP_KEY[entry["type"]]
        if type_key == "passport":
            groups[key][type_key] = _more_recent_passport(entry["data"], groups[key].get(type_key))
        else:
            groups[key][type_key] = _prefer_richer(entry["data"], groups[key].get(type_key))

    # Reconciliation pass - the incremental grouping above depends on
    # Drive's (arbitrary, non-deterministic) file listing order: if the
    # very first document seen for someone happens to be an SSN card
    # (which has no Date of Birth on it at all), the DOB fallback above has
    # nothing to compare against yet, and a later document under a
    # different surname gets its own new group instead of matching.
    # Confirmed live 2026-08-19: this actually happened, non-deterministically,
    # across two otherwise-identical runs of the same real folder - the
    # ordering fragility isn't hypothetical. This pass is order-independent:
    # it merges any two groups that share a First Name AND at least one
    # identical Date of Birth somewhere among their own documents,
    # regardless of which document was processed first.
    merged_any = True
    while merged_any:
        merged_any = False
        for i, key_a in enumerate(order):
            for key_b in order[i + 1:]:
                if key_a[0] != key_b[0]:
                    continue
                dobs_a = {e["data"].get("Date of Birth", "").strip() for e in groups[key_a]["docs"] if e["data"].get("Date of Birth")}
                dobs_b = {e["data"].get("Date of Birth", "").strip() for e in groups[key_b]["docs"] if e["data"].get("Date of Birth")}
                if not (dobs_a & dobs_b):
                    continue
                print(f"  reconciling {key_b[0]} {key_b[1]} into {key_a[0]} {key_a[1]} (shared Date of Birth)")
                groups[key_a]["docs"].extend(groups[key_b]["docs"])
                for type_key in ("passport", "birth_cert", "citizenship_evidence", "ssn_card"):
                    if type_key not in groups[key_b]:
                        continue
                    if type_key == "passport":
                        groups[key_a][type_key] = _more_recent_passport(groups[key_b][type_key], groups[key_a].get(type_key))
                    else:
                        groups[key_a][type_key] = _prefer_richer(groups[key_b][type_key], groups[key_a].get(type_key))
                del groups[key_b]
                order.remove(key_b)
                merged_any = True
                break
            if merged_any:
                break

    # Match each Fillout submission to a group. Fillout never extracts
    # Date of Birth (the form doesn't reliably provide one - see
    # FILLOUT_TARGET_SCHEMA), so the name+DOB fallback above doesn't apply
    # here; instead: exact (First, Last) match first, then fall back to
    # First Name alone IF that matches exactly one existing applicant
    # group (handles the same marriage/name-change case - the Fillout
    # submitter typed the name one way, the passport scan read it another
    # way, but within one family two people sharing a first name is rare
    # enough that this is a safe fallback, not a guess), then finally the
    # single-applicant fallback.
    fillout_by_key = {}
    unmatched_fillout = []
    for file_id, name, text in fillout_candidates:
        fillout_data = extract_fillout_data(text)
        f_first = fillout_data.get("First Name", "").strip().upper()
        f_last = fillout_data.get("Last Name", "").strip().upper()
        matched_key = None
        if (f_first, f_last) in groups:
            matched_key = (f_first, f_last)
        elif f_first:
            first_name_matches = [k for k in order if k[0] == f_first]
            if len(first_name_matches) == 1:
                matched_key = first_name_matches[0]
        if matched_key is None and len(order) == 1:
            matched_key = order[0]
        if matched_key is not None:
            fillout_by_key[matched_key] = fillout_data
        else:
            unmatched_fillout.append((name, fillout_data))

    # Merge priority, weakest to strongest (later calls override earlier
    # keys): Fillout is self-reported, weakest. The Israeli birth
    # certificate is the original documentary source but isn't tied to
    # whatever English spelling the US government actually uses.
    # Citizenship-evidence documents (CRBA/Certificate of Citizenship/US
    # birth cert) ARE that authoritative US-government spelling - stronger
    # than the Israeli certificate. The passport wins over everything else
    # identity-wise: it's the closest match to what the State Department
    # already has on file, which matters most for a renewal. The SSN card
    # is applied last of all - it isn't an identity source (the other
    # documents already establish name/DOB/etc.) but it's the single most
    # direct source for the one field it does provide, more reliable than
    # a self-typed Fillout answer (confirmed live 2026-08-19: a real
    # Fillout submission had "000000000" typed in for SSN).
    merged_by_key = {}
    for key in order:
        merged = {}
        merged.update(fillout_by_key.get(key, {}))
        merged.update(groups[key].get("birth_cert", {}))
        merged.update(groups[key].get("citizenship_evidence", {}))
        merged.update(groups[key].get("passport", {}))
        # SSN_CARD's own First/Last Name exist only so this document can be
        # matched to the right applicant (see grouping above) - they are
        # NOT a real data source for those fields and must never overwrite
        # them here. Confirmed live 2026-08-19: an SSN card showing a
        # pre-marriage name (Social Security records aren't always updated
        # after a legal name change) silently overwrote the passport's
        # correct current surname because it happened to merge last.
        ssn_contribution = {k: v for k, v in groups[key].get("ssn_card", {}).items() if k not in ("First Name", "Last Name")}
        merged.update(ssn_contribution)
        merged_by_key[key] = merged

    _fill_shared_family_fields(merged_by_key)

    # A short, human-readable summary in the Sheet itself - so staff can
    # see what happened without needing Cloud Run logs (which they don't
    # have access to). Confirmed live 2026-08-19: the exact question that
    # triggered building this ("is there a log of what happened?") had no
    # good answer before this.
    unmatched_note = ""
    if unmatched_fillout:
        unmatched_note = " שאלון/ים לא שויכו לאף מועמד: " + ", ".join(n for n, _ in unmatched_fillout) + "."
    other_note = f" {len(other_files)} קבצים נוספים בתיקייה לא זוהו כמסמך רלוונטי (תקין אם אלה טפסים/קבלות/תצהירים)." if other_files else ""

    summary = []
    for i, key in enumerate(order, start=1):
        doc_type_counts = {}
        for entry in groups[key]["docs"]:
            label = DOC_TYPE_LABELS[entry["type"]]
            doc_type_counts[label] = doc_type_counts.get(label, 0) + 1
        docs_note = ", ".join(f"{label} x{n}" if n > 1 else label for label, n in doc_type_counts.items())
        fillout_note = "כן" if key in fillout_by_key else "לא נמצא"
        merged_by_key[key]["Notes"] = f"נסרקו אוטומטית: {docs_note}. Fillout: {fillout_note}.{unmatched_note}{other_note}"

        skipped = write_applicant_data(spreadsheet_id, i, merged_by_key[key])
        summary.append({
            "applicant": i,
            "name": f"{key[0]} {key[1]}",
            "fields_written": len(merged_by_key[key]) - len(skipped) + 1,
            "skipped": skipped,
        })
        if rename_files:
            for entry in groups[key]["docs"]:
                label = DOC_TYPE_LABELS[entry["type"]]
                ext = Path(entry["name"]).suffix
                drive.files().update(fileId=entry["file_id"], body={"name": f"{label} - {key[0]} {key[1]}{ext}"}, supportsAllDrives=True).execute()

    return summary, unmatched_fillout


# ---------------------------------------------------------------------------
# Writing into the client's Sheet - "Applicants" tab layout (see
# build_sheet.py, the schema's source of truth): column A holds field-label
# rows grouped into section bands; row 1 holds "Applicant 1"/"Applicant
# 2"/... headers; data for applicant N lives in column (1 + N), i.e.
# column B = Applicant 1, C = Applicant 2, etc. (siblings share one file,
# one column each).
# ---------------------------------------------------------------------------

APPLICANTS_SHEET = "Applicants"


def _column_letter(n: int) -> str:
    """1 -> A, 2 -> B, 27 -> AA, ... (local, so this file doesn't need an
    openpyxl dependency just for this one lookup)."""
    letters = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def _label_to_row_map(sheets, spreadsheet_id: str) -> dict:
    result = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"{APPLICANTS_SHEET}!A:A").execute()
    mapping = {}
    for i, row in enumerate(result.get("values", []), start=1):
        if row and row[0]:
            mapping[row[0]] = i
    return mapping


def write_applicant_data(spreadsheet_id: str, applicant_num: int, data: dict) -> list:
    """Writes extracted field values into one applicant's column and sets
    Status = "Needs Review" so staff know to check it against the source
    documents before run_autofill.py ever touches it.

    Uses RAW input (not USER_ENTERED) deliberately: USER_ENTERED lets
    Sheets "helpfully" reinterpret text as a formula or a locale-dependent
    date, which is exactly what caused two real bugs elsewhere in this
    project - a phone number starting with "+" being evaluated as
    arithmetic, and ambiguous DD/MM-vs-MM/DD text dates being silently
    misread. RAW stores the extracted string exactly as given, same as a
    human typing plain text into an unformatted cell.

    Returns the list of extracted keys that didn't match any row label on
    the sheet (should normally be empty - a non-empty list means the sheet
    schema and this script's field names have drifted apart).
    """
    sheets = get_sheets_service()
    label_to_row = _label_to_row_map(sheets, spreadsheet_id)
    col_letter = _column_letter(1 + applicant_num)

    to_write = dict(data)
    to_write["Status"] = "Needs Review"

    value_ranges = []
    skipped = []
    for label, value in to_write.items():
        row = label_to_row.get(label)
        if row is None:
            skipped.append(label)
            continue
        value_ranges.append({"range": f"{APPLICANTS_SHEET}!{col_letter}{row}", "values": [[value]]})

    if value_ranges:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"valueInputOption": "RAW", "data": value_ranges}
        ).execute()

    return skipped


def _extract_drive_id(arg: str) -> str:
    m = re.search(r"/(?:d|folders)/([a-zA-Z0-9_-]+)", arg)
    return m.group(1) if m else arg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    p_fillout = sub.add_parser("fillout", help="Extract Fillout doc only, print JSON")
    p_fillout.add_argument("doc")

    p_passport = sub.add_parser("passport", help="Extract passport photo/scan only, print JSON")
    p_passport.add_argument("file")

    p_birthcert = sub.add_parser("birthcert", help="Extract Israeli birth certificate only, print JSON")
    p_birthcert.add_argument("file")

    p_citizenship = sub.add_parser("citizenship", help="Extract citizenship-evidence document (Certificate of Citizenship/Naturalization, CRBA, US birth certificate) only, print JSON")
    p_citizenship.add_argument("file")

    p_build = sub.add_parser("build", help="Extract from given sources and write into the client's Sheet")
    p_build.add_argument("--sheet", required=True, help="Client's AUTOFILL Sheet ID or URL")
    p_build.add_argument("--applicant", type=int, required=True, help="Applicant column number (1, 2, 3, ...)")
    p_build.add_argument("--fillout", help="Fillout doc ID or URL")
    p_build.add_argument("--passport", help="Passport photo/scan file ID or URL")
    p_build.add_argument("--birthcert", help="Birth certificate file ID or URL")

    p_scan = sub.add_parser("scan", help="Auto-discover a client's documents in their Drive folder and write every applicant found")
    p_scan.add_argument("--folder", required=True, help="Client's Drive folder ID or URL")
    p_scan.add_argument("--sheet", help="Client's AUTOFILL Sheet ID or URL (auto-discovered in the folder if omitted)")
    p_scan.add_argument("--no-rename", action="store_true", help="Don't rename classified files in Drive")

    args = parser.parse_args()
    drive = get_drive_service()

    if args.mode == "fillout":
        text = fetch_doc_text(drive, _extract_drive_id(args.doc))
        print(f"--- fetched {len(text)} chars from Fillout doc ---\n")
        data = extract_fillout_data(text)
        print("--- extracted fields ---")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.mode == "passport":
        image_bytes, mime_type = fetch_drive_file_bytes(drive, _extract_drive_id(args.file))
        print(f"--- fetched {len(image_bytes)} bytes, {mime_type} ---\n")
        data = extract_passport_data(image_bytes, mime_type)
        print("--- extracted fields ---")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.mode == "birthcert":
        file_bytes, mime_type = fetch_drive_file_bytes(drive, _extract_drive_id(args.file))
        print(f"--- fetched {len(file_bytes)} bytes, {mime_type} ---\n")
        data = extract_birth_cert_data(file_bytes, mime_type)
        print("--- extracted fields ---")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.mode == "citizenship":
        file_bytes, mime_type = fetch_drive_file_bytes(drive, _extract_drive_id(args.file))
        print(f"--- fetched {len(file_bytes)} bytes, {mime_type} ---\n")
        data = extract_citizenship_evidence_data(file_bytes, mime_type)
        print("--- extracted fields ---")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.mode == "scan":
        folder_id = _extract_drive_id(args.folder)
        spreadsheet_id = _extract_drive_id(args.sheet) if args.sheet else find_client_sheet(drive, folder_id)
        summary, unmatched = scan_and_build(drive, folder_id, spreadsheet_id, rename_files=not args.no_rename)
        print("\n--- summary ---")
        print(json.dumps({"applicants": summary, "unmatched_fillout_docs": [name for name, _ in unmatched]}, ensure_ascii=False, indent=2))
    else:
        if not (args.fillout or args.passport or args.birthcert):
            parser.error("build needs at least one of --fillout / --passport / --birthcert")

        merged = {}
        if args.fillout:
            text = fetch_doc_text(drive, _extract_drive_id(args.fillout))
            fillout_data = extract_fillout_data(text)
            print(f"--- Fillout: {len(fillout_data)} fields ---")
            print(json.dumps(fillout_data, ensure_ascii=False, indent=2))
            merged.update(fillout_data)
        if args.birthcert:
            file_bytes, mime_type = fetch_drive_file_bytes(drive, _extract_drive_id(args.birthcert))
            birthcert_data = extract_birth_cert_data(file_bytes, mime_type)
            print(f"--- Birth certificate: {len(birthcert_data)} fields ---")
            print(json.dumps(birthcert_data, ensure_ascii=False, indent=2))
            # Documents override the Fillout self-report on overlapping
            # fields (name spelling, etc.) - a scan of an official document
            # is a better source than a self-typed web form answer.
            merged.update(birthcert_data)
        if args.passport:
            image_bytes, mime_type = fetch_drive_file_bytes(drive, _extract_drive_id(args.passport))
            passport_data = extract_passport_data(image_bytes, mime_type)
            print(f"--- Passport: {len(passport_data)} fields ---")
            print(json.dumps(passport_data, ensure_ascii=False, indent=2))
            # A passport is the strongest identity match to what the State
            # Department already has on file for a renewal - overrides the
            # birth certificate too, when both are given.
            merged.update(passport_data)

        spreadsheet_id = _extract_drive_id(args.sheet)
        skipped = write_applicant_data(spreadsheet_id, args.applicant, merged)

        print(f"\n--- wrote {len(merged) - len(skipped) + 1} fields to Applicant {args.applicant} (+ Status) ---")
        if skipped:
            print(f"--- WARNING: {len(skipped)} extracted field(s) had no matching row on the sheet, not written: {skipped} ---")


if __name__ == "__main__":
    main()
