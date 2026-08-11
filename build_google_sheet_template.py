"""
Creates the live Google Sheets version of the Applications template (cloud
counterpart of build_sheet.py's local Applications.xlsx) inside the
AUTOFILL_תבנית Drive folder. Reuses the same SECTIONS/VALIDATION_LISTS data
model from build_sheet.py so the two stay in sync - edit that file's schema,
then re-run this script to regenerate the Google Sheet template.

Re-running this UPDATES the existing template spreadsheet in place (clears
and rewrites the Applicants/Lists sheets) - it deliberately does NOT create
a new file, so the bound Apps Script (the "AUTOFILL" menu/button added
manually via Extensions > Apps Script) survives across regenerations. A
brand-new spreadsheet would NOT carry that script over.
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build

from build_sheet import SECTIONS, VALIDATION_LISTS, NUM_APPLICANT_COLUMNS

SERVICE_ACCOUNT_FILE = r"C:\Users\office_americandocs\document-analyzer\service_account.json"
TEMPLATE_FOLDER_ID = "1shwqGAVnBaPh5Pa4WKC3iGpgFM6K3jrC"
TEMPLATE_NAME = "AUTOFILL - טופס לקוח (תבנית - להעתיק, לא לערוך כאן)"
# The template's own spreadsheet ID - update THIS file in place rather than
# creating a new one each time, so the bound Apps Script (the "AUTOFILL"
# menu/button added manually via Extensions > Apps Script) survives across
# regenerations - a brand-new spreadsheet would NOT carry it over.
TEMPLATE_SPREADSHEET_ID = "1pfzRirYVqmI0uarzbTFWtTKTbx77wqjsMk5xGVCvVWE"

SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]

# Requirement colors for data cells (columns B..last) - distinct from every
# section band color so they never blend in. "DYN"/None fields are left
# uncolored here; they get per-scenario colors via conditional formatting
# in a follow-up pass (dynamic - depends on that column's own answers).
REQUIRED_COLOR = "F4CCCC"   # soft red - always required
OPTIONAL_COLOR = "CFE2F3"   # soft blue - relevant but optional


def _hex_to_rgb(hex_color):
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    return {"red": r, "green": g, "blue": b}


def _lighten(hex_color, factor=0.55):
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"{r:02X}{g:02X}{b:02X}"


def build_template():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    spreadsheet_id = TEMPLATE_SPREADSHEET_ID

    # Update the existing template file in place (not create+trash) so the
    # bound Apps Script survives. Look up its actual sheet gids and clear/
    # unmerge everything first - old section-band merges at different row
    # numbers would otherwise conflict with the new (reordered) layout.
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_ids_by_title = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    applicants_sheet_id = sheet_ids_by_title["Applicants"]
    lists_sheet_id = sheet_ids_by_title.get("Lists")

    last_col_idx = 1 + NUM_APPLICANT_COLUMNS  # 0 = label column A, 1..6 = applicants

    # Conditional format rules are a separate spreadsheet-level property, not
    # touched by the updateCells formatting wipe below - delete existing ones
    # first (highest index down, since deleting shifts later indices) so
    # reruns don't pile up duplicate DYN-coloring rules.
    applicants_sheet_meta = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == applicants_sheet_id)
    existing_cf_count = len(applicants_sheet_meta.get("conditionalFormats", []))
    clear_requests = [
        {"deleteConditionalFormatRule": {"sheetId": applicants_sheet_id, "index": i}}
        for i in range(existing_cf_count - 1, -1, -1)
    ]
    clear_requests += [
        {"unmergeCells": {"range": {"sheetId": applicants_sheet_id}}},
        {"updateCells": {"range": {"sheetId": applicants_sheet_id}, "fields": "*"}},  # clear all values+formatting
    ]
    if lists_sheet_id is not None:
        clear_requests.append({"updateCells": {"range": {"sheetId": lists_sheet_id}, "fields": "*"}})
    else:
        clear_requests.append({"addSheet": {"properties": {"title": "Lists", "hidden": True}}})
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": clear_requests}).execute()

    if lists_sheet_id is None:
        # addSheet above created it with an auto-assigned id - look it up now
        meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        lists_sheet_id = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}["Lists"]

    APPLICANTS_SHEET_ID = applicants_sheet_id
    LISTS_SHEET_ID = lists_sheet_id

    requests = [
        {"updateSheetProperties": {
            # frozenColumnCount explicitly reset to 0 - a pre-existing frozen
            # column (found on the restored original template, which had it
            # set from before this script ever touched the file) blocks the
            # full-row-width mergeCells requests below with "You can't merge
            # frozen and non-frozen columns".
            "properties": {"sheetId": APPLICANTS_SHEET_ID, "title": "Applicants",
                            "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 0}},
            "fields": "title,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }},
    ]
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()

    # ---- Lists sheet: one validation-source column per key ----
    list_keys = list(VALIDATION_LISTS.keys())
    lists_values = []
    max_len = max(len(v) for v in VALIDATION_LISTS.values())
    header = list_keys
    lists_values.append(header)
    for i in range(max_len):
        row = []
        for key in list_keys:
            values = VALIDATION_LISTS[key]
            row.append(values[i] if i < len(values) else "")
        lists_values.append(row)

    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="Lists!A1",
        valueInputOption="RAW", body={"values": lists_values},
    ).execute()
    list_col_range = {}  # key -> A1 range string, e.g. "Lists!$A$2:$A$3"
    for idx, key in enumerate(list_keys):
        n = len(VALIDATION_LISTS[key])
        col_letter = chr(ord("A") + idx)
        list_col_range[key] = f"Lists!${col_letter}$2:${col_letter}${n + 1}"

    # ---- Applicants sheet: header row + section bands + field rows ----
    requests = []

    # Fields where a value is a digit-string that must NEVER be evaluated as
    # a number/formula. Confirmed live 2026-08-10: a phone number typed with
    # a leading "+" (e.g. "+972-50-1234567") is silently evaluated by
    # Google Sheets as arithmetic (972-50-1234567 = -1233645) on a
    # default-formatted cell, with no error shown - it then got typed into
    # the government site as "-1233645" -> "1233645" after digit-stripping,
    # which looked for hours like a site-side or CDP-side bug before this
    # was traced back to the Sheet cell itself. Forcing plain-text format
    # closes this off regardless of how the value gets typed in (by staff in
    # the browser, or by any script using USER_ENTERED).
    PLAIN_TEXT_FIELDS = {
        "EC Phone", "SSN", "USCIS A-Number", "Book Number",
        "Mail Zip", "Permanent Zip", "EC Zip",
    }

    def cell(value=None, bold=False, italic=False, size=10, color=None, bg=None, align="LEFT", wrap=False,
             plain_text=False):
        fmt = {}
        text_fmt = {"bold": bold, "italic": italic, "fontSize": size}
        if color:
            text_fmt["foregroundColor"] = _hex_to_rgb(color)
        fmt["textFormat"] = text_fmt
        fmt["horizontalAlignment"] = align
        fmt["verticalAlignment"] = "MIDDLE"
        if wrap:
            fmt["wrapStrategy"] = "WRAP"
        if bg:
            fmt["backgroundColor"] = _hex_to_rgb(bg)
        if plain_text:
            fmt["numberFormat"] = {"type": "TEXT"}
        c = {"userEnteredFormat": fmt}
        if value is not None:
            c["userEnteredValue"] = {"stringValue": value}
        return c

    rows = []
    # header row
    header_row = [cell("APPLICANT ->", bold=True, italic=True, size=10, color="808080", align="RIGHT")]
    for i in range(NUM_APPLICANT_COLUMNS):
        header_row.append(cell(f"Applicant {i + 1}", bold=True, size=11, color="FFFFFF", bg="404040", align="CENTER"))
    rows.append(header_row)

    validations = []  # (row_index_0based, validation_key)
    field_row_index = {}  # label -> row_index_0based, used to build DYN conditional-format formulas below
    row_idx = 1  # header already consumed row 0

    for section_title, color_hex, fields in SECTIONS:
        band_row = [cell(section_title, bold=True, size=11, color="FFFFFF", bg=color_hex, align="LEFT")]
        for _ in range(NUM_APPLICANT_COLUMNS):
            band_row.append(cell(bg=color_hex))
        rows.append(band_row)
        requests.append({"mergeCells": {
            "range": {"sheetId": APPLICANTS_SHEET_ID, "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                       "startColumnIndex": 0, "endColumnIndex": last_col_idx},
            "mergeType": "MERGE_ALL",
        }})
        row_idx += 1

        light = _lighten(color_hex)
        for label, validation_key, requirement in fields:
            # Column A (the label) keeps the section's own tint, like before
            # - only the DATA-entry cells (B..last) show the requirement
            # color (red/blue), so the two color systems stay visually
            # separate: "which section" (label) vs "do I need to fill this
            # in" (data cells).
            data_bg = REQUIRED_COLOR if requirement == "R" else OPTIONAL_COLOR if requirement == "O" else None
            plain_text = label in PLAIN_TEXT_FIELDS
            field_row = [cell(label, bold=True, size=10, bg=light, align="LEFT", wrap=True)]
            for _ in range(NUM_APPLICANT_COLUMNS):
                field_row.append(cell(align="CENTER", bg=data_bg, plain_text=plain_text))
            rows.append(field_row)
            field_row_index[label] = row_idx
            if validation_key:
                validations.append((row_idx, validation_key))
            row_idx += 1

    requests.append({"updateCells": {
        "rows": [{"values": r} for r in rows],
        "fields": "userEnteredValue,userEnteredFormat",
        "start": {"sheetId": APPLICANTS_SHEET_ID, "rowIndex": 0, "columnIndex": 0},
    }})

    # small legend, off to the side (column I) so it doesn't interfere with
    # the applicant data columns (B..G)
    legend_rows = [
        [cell("מקרא:", bold=True, size=10)],
        [cell("חובה", bg=REQUIRED_COLOR, align="CENTER")],
        [cell("רלוונטי, לא חובה", bg=OPTIONAL_COLOR, align="CENTER")],
        [cell("לא צבוע = לא רלוונטי כרגע", align="LEFT")],
        [cell("שדות תלויים (למשל פרטי הורים) יצבעו אוטומטית באדום ברגע שהתשובות למעלה (שאלות מפתח) קובעות שהם נדרשים", align="LEFT", wrap=True)],
    ]
    requests.append({"updateCells": {
        "rows": [{"values": r} for r in legend_rows],
        "fields": "userEnteredValue,userEnteredFormat",
        "start": {"sheetId": APPLICANTS_SHEET_ID, "rowIndex": 1, "columnIndex": 8},  # column I, row 2
    }})
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": APPLICANTS_SHEET_ID, "dimension": "COLUMNS", "startIndex": 8, "endIndex": 9},
        "properties": {"pixelSize": 260}, "fields": "pixelSize",
    }})

    # column widths
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": APPLICANTS_SHEET_ID, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 220}, "fields": "pixelSize",
    }})
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": APPLICANTS_SHEET_ID, "dimension": "COLUMNS", "startIndex": 1, "endIndex": last_col_idx},
        "properties": {"pixelSize": 150}, "fields": "pixelSize",
    }})

    # borders around every field-row data cell (col B..last, all field rows)
    requests.append({"updateBorders": {
        "range": {"sheetId": APPLICANTS_SHEET_ID, "startRowIndex": 0, "endRowIndex": row_idx,
                   "startColumnIndex": 0, "endColumnIndex": last_col_idx},
        "top": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
        "bottom": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
        "left": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
        "right": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
        "innerHorizontal": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
        "innerVertical": {"style": "SOLID", "width": 1, "color": _hex_to_rgb("BFBFBF")},
    }})

    # data validations (dropdowns) for columns B..last on each validated row
    for r, key in validations:
        requests.append({"setDataValidation": {
            "range": {"sheetId": APPLICANTS_SHEET_ID, "startRowIndex": r, "endRowIndex": r + 1,
                       "startColumnIndex": 1, "endColumnIndex": last_col_idx},
            "rule": {
                "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": f"={list_col_range[key]}"}]},
                "showCustomUi": True,
                "strict": False,
            },
        }})

    # ---- DYN conditional formatting: color a field red the moment the
    # KEY QUESTIONS panel answers (+ a few same-section answers) mean it's
    # actually required, per the official DS-11/DS-82/DS-5504 eligibility
    # rules (not a guess - read directly off the government form
    # instructions, 2026-08-09):
    #   DS-82 (mail renewal) requires ALL of: book in hand (not damaged/lost/
    #     stolen), issued at age 16+, issued <15 years ago, not limited-
    #     validity-for-cause, name unchanged or provably changed.
    #   DS-5504 (correction/name-change/limited-replacement) covers: data
    #     printed wrong, OR name changed <1yr after a <1yr-old book, OR
    #     limited-validity for a non-fault reason - but only if the book can
    #     still be presented (not damaged/lost/stolen).
    #   DS-11 (in-person, needs Parent & Spouse Info) is required whenever
    #     none of the above apply: first-time, currently under 16, or a
    #     renewal candidate whose book was issued under 16 / is 15+ years
    #     old / was damaged/lost/stolen.
    def r(label):
        return field_row_index[label] + 1  # 1-based row number for A1 formulas

    scenario_cell = f'B${r("Passport Scenario")}'
    dob_cell = f'B${r("Date of Birth")}'
    book_issue_cell = f'B${r("Book Issue Date")}'

    # IFERROR wraps are load-bearing, not defensive fluff: OR()/AND() in
    # Sheets evaluate every argument (no short-circuiting), so DATEDIF on a
    # still-blank date cell throws #NUM! and poisons the entire OR() into an
    # error - which conditional formatting silently treats as FALSE - even
    # though the surrounding AND()'s own "<>\"\"" guard is logically false.
    name_changed_cell = f'B${r("Name Changed?")}'
    name_change_certified_cell = f'B${r("Name Change Certified Docs?")}'
    ds11_required = (
        f'OR('
        f'{scenario_cell}="First-time (None)",'
        f'{scenario_cell}="Book Damaged",'
        f'{scenario_cell}="Book Lost",'
        f'{scenario_cell}="Book Stolen",'
        f'AND({scenario_cell}="Have Book",IFERROR(DATEDIF({dob_cell},{book_issue_cell},"Y"),999)<16),'
        f'AND({scenario_cell}="Have Book",IFERROR(DATEDIF({book_issue_cell},TODAY(),"Y"),-1)>=15),'
        f'IFERROR(DATEDIF({dob_cell},TODAY(),"Y"),999)<16,'
        # Confirmed live 2026-08-10: the site's own Name-Change sub-panel asks
        # "Can you submit certified documentation to reflect the name
        # change?" - answering No is a real DS-82-disqualifying trigger
        # (DS-82 eligibility requires either no name change, or a provable
        # one), not something we were tracking before this test run.
        f'AND({name_changed_cell}="Yes",{name_change_certified_cell}="No")'
        f')'
    )
    not_first_time = f'{scenario_cell}<>"First-time (None)"'
    parent1_unknown_cell = f'B${r("Parent 1 Unknown?")}'
    parent2_unknown_cell = f'B${r("Parent 2 Unknown?")}'
    ever_married_cell = f'B${r("Ever Married?")}'
    ever_divorced_cell = f'B${r("Ever Divorced or Widowed?")}'
    reported_lost_stolen_cell = f'B${r("Reported Lost or Stolen?")}'
    limited_validity_cell = f'B${r("Limited Validity Under 2 Years?")}'
    data_correct_cell = f'B${r("Data Printed Correctly?")}'
    country_of_birth_cell = f'B${r("Country of Birth")}'

    lost_stolen_scenario = f'OR({scenario_cell}="Book Lost",{scenario_cell}="Book Stolen")'

    # (labels, formula) - each applies to every field row listed, colored
    # REQUIRED_COLOR when true. Rows sharing an identical formula are grouped.
    dyn_rules = [
        (["State of Birth (USA only)"], f'REGEXMATCH(UPPER({country_of_birth_cell}),"USA|UNITED STATES|U\\.S\\.A")'),
        (["Reported Lost or Stolen?"], lost_stolen_scenario),
        (["Limited Validity Under 2 Years?", "Name On Book - First", "Name On Book - Last", "Book Number",
          "Data Printed Correctly?", "Name Changed?"], not_first_time),
        (["Paid For Card Before?"], f'{limited_validity_cell}="Yes"'),
        (["Incorrect Fields"], f'{data_correct_cell}="No"'),
        (["Name Change Type", "Name Change Place", "Name Change Date", "Name Change Certified Docs?"],
         f'{name_changed_cell}="Yes"'),
        (["Reporting Own Passport?", "Filed Police Report?", "Lost/Stolen Explanation", "Lost/Stolen Location",
          "Lost/Stolen Date", "Other Passports Lost/Stolen?"],
         f'AND({lost_stolen_scenario},{reported_lost_stolen_cell}="No")'),
        (["Parent 1 Unknown?", "Parent 2 Unknown?", "Ever Married?"], ds11_required),
        (["Parent 1 First & Middle Name", "Parent 1 Last Name", "Parent 1 Date of Birth", "Parent 1 Place of Birth",
          "Parent 1 Sex", "Parent 1 US Citizen?"], f'AND({ds11_required},{parent1_unknown_cell}<>"Yes")'),
        (["Parent 2 First & Middle Name", "Parent 2 Last Name", "Parent 2 Date of Birth", "Parent 2 Place of Birth",
          "Parent 2 Sex", "Parent 2 US Citizen?"], f'AND({ds11_required},{parent2_unknown_cell}<>"Yes")'),
        (["Spouse First & Middle Name", "Spouse Last Name", "Spouse Date of Birth", "Spouse Place of Birth",
          "Spouse US Citizen?", "Marriage Date", "Ever Divorced or Widowed?"],
         f'AND({ds11_required},{ever_married_cell}="Yes")'),
        (["Divorce Date"], f'AND({ds11_required},{ever_married_cell}="Yes",{ever_divorced_cell}="Yes")'),
    ]

    for labels, formula in dyn_rules:
        for label in labels:
            row = field_row_index[label]
            requests.append({"addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": APPLICANTS_SHEET_ID, "startRowIndex": row, "endRowIndex": row + 1,
                                 "startColumnIndex": 1, "endColumnIndex": last_col_idx}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f"={formula}"}]},
                        "format": {"backgroundColor": _hex_to_rgb(REQUIRED_COLOR)},
                    },
                },
            }})

    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()

    print(f"Updated template spreadsheet: {spreadsheet_id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
    return spreadsheet_id


if __name__ == "__main__":
    build_template()
