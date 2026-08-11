"""
Google Sheets/Drive backend for the autofill bot - replaces the local
Applications.xlsx (openpyxl) data source with a live per-client Google Sheet
(a copy of the AUTOFILL_תבנית template, living in that client's Drive folder).

Uses the same service account as the document-analyzer project (already
has Sheets + Drive API enabled) - see notes.md / project memory for why.
"""

import datetime
import os
import re
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def _find_service_account_file() -> str:
    """Every staff computer has its own copy of service_account.json at a
    different path (different Windows username) - never hardcode one machine's
    path. Resolution order: explicit env var (set by launcher.py, which knows
    where it and its sibling service_account.json are actually installed),
    then a copy sitting next to this file, then this dev machine's original
    location as a last-resort fallback for running sheets_backend.py directly."""
    env_path = os.environ.get("AUTOFILL_SERVICE_ACCOUNT")
    if env_path and Path(env_path).exists():
        return env_path
    local_copy = Path(__file__).parent / "service_account.json"
    if local_copy.exists():
        return str(local_copy)
    return r"C:\Users\office_americandocs\document-analyzer\service_account.json"


SERVICE_ACCOUNT_FILE = _find_service_account_file()
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]

APPLICANTS_SHEET_NAME = "Applicants"
READY_STATUS = "Ready"
RUNNING_STATUS = "Running"
DONE_STATUS = "Done"
ERROR_STATUS = "Error"

STATUS_ROW_LABEL = "Status"
NOTES_ROW_LABEL = "Notes"

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_FOLDER_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Accepts either a full Google Sheets URL or a bare spreadsheet ID."""
    m = _SPREADSHEET_ID_RE.search(url_or_id)
    return m.group(1) if m else url_or_id.strip()


def _credentials():
    return service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)


def get_sheets_service():
    return build("sheets", "v4", credentials=_credentials())


def get_drive_service():
    return build("drive", "v3", credentials=_credentials())


def find_sheet_in_folder(drive, folder_id: str) -> str:
    """Looks inside a client's Drive folder for the (one) Google Sheet copied
    in from the AUTOFILL_תבנית template, and returns its spreadsheet ID.
    Raises a clear error if there's none or more than one - staff should
    only ever have a single autofill Sheet per client folder."""
    results = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false and mimeType='{SPREADSHEET_MIME}'",
        fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if not results:
        raise ValueError(
            f"No Google Sheet found in folder {folder_id} - copy the AUTOFILL_תבנית "
            "template into this client's folder first."
        )
    if len(results) > 1:
        names = ", ".join(f["name"] for f in results)
        raise ValueError(
            f"Found {len(results)} Google Sheets in folder {folder_id} ({names}) - "
            "not clear which one is the autofill form. Remove/rename the extra one."
        )
    return results[0]["id"]


def resolve_to_spreadsheet_id(url_or_id: str) -> str:
    """Accepts a Google Sheet link/ID OR a Drive folder link/ID (the client's
    folder) and returns the actual spreadsheet ID either way - if given a
    folder, auto-discovers the Sheet copied into it."""
    m = _SPREADSHEET_ID_RE.search(url_or_id)
    if m:
        return m.group(1)

    drive = get_drive_service()
    m = _FOLDER_ID_RE.search(url_or_id)
    if m:
        return find_sheet_in_folder(drive, m.group(1))

    # bare ID, ambiguous - ask Drive what it actually is
    bare_id = url_or_id.strip()
    meta = drive.files().get(fileId=bare_id, fields="mimeType", supportsAllDrives=True).execute()
    if meta["mimeType"] == FOLDER_MIME:
        return find_sheet_in_folder(drive, bare_id)
    return bare_id


def _serial_to_date(serial: float) -> datetime.datetime:
    """Sheets (like Excel) stores dates as a day-count serial number from
    1899-12-30 - convert back to a real datetime, matching what openpyxl
    used to hand us directly for typed Excel date cells."""
    return datetime.datetime(1899, 12, 30) + datetime.timedelta(days=serial)


def _read_grid(sheets_service, spreadsheet_id: str):
    """Fetches the full Applicants sheet with enough metadata to reconstruct
    typed values (numbers vs dates vs text) the same way openpyxl did."""
    resp = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=[f"{APPLICANTS_SHEET_NAME}"],
        fields="sheets.data.rowData.values(formattedValue,effectiveValue,userEnteredFormat.numberFormat.type)",
    ).execute()
    return resp["sheets"][0]["data"][0].get("rowData", [])


def _cell_value(cell: dict):
    """Reconstructs a Python value (str/float/datetime/None) from one Sheets
    API cell entry, the way openpyxl exposed typed Excel cells."""
    if not cell:
        return None
    effective = cell.get("effectiveValue")
    if effective is None:
        return None
    number_format_type = cell.get("userEnteredFormat", {}).get("numberFormat", {}).get("type")
    if "numberValue" in effective:
        if number_format_type in ("DATE", "DATE_TIME"):
            return _serial_to_date(effective["numberValue"])
        # plain number (zip, book number, etc.) - keep the formatted text if
        # it round-trips cleanly as an int, else the raw float, matching the
        # ad-hoc int-like values openpyxl used to hand back.
        num = effective["numberValue"]
        return int(num) if num == int(num) else num
    if "stringValue" in effective:
        return effective["stringValue"]
    if "boolValue" in effective:
        return effective["boolValue"]
    return cell.get("formattedValue")


def load_all_applicants(spreadsheet_id: str) -> dict:
    """Returns {column_letter: {label: value}} for every applicant column
    that has any data at all (not just "Ready" ones - callers filter)."""
    sheets_service = get_sheets_service()
    rows = _read_grid(sheets_service, spreadsheet_id)

    # row 0 is the "Applicant N" header row - discover how many columns exist
    header_cells = rows[0].get("values", []) if rows else []
    num_cols = max(0, len(header_cells) - 1)  # column 0 is the label column

    applicants = {chr(ord("B") + i): {} for i in range(num_cols)}
    for row in rows[1:]:
        cells = row.get("values", [])
        if not cells:
            continue
        label = _cell_value(cells[0])
        if not label or not isinstance(label, str):
            continue
        label = label.strip()
        for i in range(num_cols):
            col_letter = chr(ord("B") + i)
            value = _cell_value(cells[i + 1]) if i + 1 < len(cells) else None
            applicants[col_letter][label] = value
    return applicants


def ready_columns(spreadsheet_id: str) -> list:
    """Column letters (e.g. ['B', 'D']) whose Status == 'Ready', in order."""
    applicants = load_all_applicants(spreadsheet_id)
    return [
        col for col, data in applicants.items()
        if str(data.get(STATUS_ROW_LABEL) or "").strip() == READY_STATUS
    ]


def _label_to_row_index(sheets_service, spreadsheet_id: str, label: str) -> int:
    rows = _read_grid(sheets_service, spreadsheet_id)
    for idx, row in enumerate(rows):
        cells = row.get("values", [])
        if cells and _cell_value(cells[0]) == label:
            return idx
    raise ValueError(f"Row labeled {label!r} not found in {APPLICANTS_SHEET_NAME}")


def set_status(spreadsheet_id: str, column_letter: str, status: str, note: str = None):
    sheets_service = get_sheets_service()
    status_row = _label_to_row_index(sheets_service, spreadsheet_id, STATUS_ROW_LABEL)
    updates = [{"range": f"{APPLICANTS_SHEET_NAME}!{column_letter}{status_row + 1}",
                "values": [[status]]}]
    if note is not None:
        notes_row = _label_to_row_index(sheets_service, spreadsheet_id, NOTES_ROW_LABEL)
        updates.append({"range": f"{APPLICANTS_SHEET_NAME}!{column_letter}{notes_row + 1}",
                         "values": [[note]]})
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()


def get_parent_folder_id(spreadsheet_id: str) -> str:
    drive = get_drive_service()
    meta = drive.files().get(fileId=spreadsheet_id, fields="parents", supportsAllDrives=True).execute()
    parents = meta.get("parents") or []
    if not parents:
        raise ValueError(f"Spreadsheet {spreadsheet_id} has no parent folder")
    return parents[0]


def _find_or_create_subfolder(drive, parent_folder_id: str, name: str) -> str:
    existing = drive.files().list(
        q=f"'{parent_folder_id}' in parents and name='{name}' and trashed=false "
          f"and mimeType='application/vnd.google-apps.folder'",
        fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if existing:
        return existing[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_folder_id]}
    return drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()["id"]


def _run_folder_id(drive, spreadsheet_id: str, run_label: str) -> str:
    client_folder_id = get_parent_folder_id(spreadsheet_id)
    runs_folder_id = _find_or_create_subfolder(drive, client_folder_id, "runs")
    return _find_or_create_subfolder(drive, runs_folder_id, run_label)


def upload_run_output(spreadsheet_id: str, local_pdf_path: Path, run_label: str) -> str:
    """Uploads the finished PDF into <client folder>/runs/<run_label>/ (Drive
    API, not a local copy) - never overwrites a previous run's output since
    each run gets its own timestamped subfolder. Returns the file's web link."""
    drive = get_drive_service()
    run_folder_id = _run_folder_id(drive, spreadsheet_id, run_label)

    media = MediaFileUpload(str(local_pdf_path), mimetype="application/pdf", resumable=True)
    file_meta = {"name": local_pdf_path.name, "parents": [run_folder_id]}
    created = drive.files().create(
        body=file_meta, media_body=media, fields="id,webViewLink", supportsAllDrives=True
    ).execute()
    return created.get("webViewLink", f"https://drive.google.com/file/d/{created['id']}/view")


def upload_debug_artifacts(spreadsheet_id: str, files, run_label: str) -> str:
    """Uploads failure evidence (screenshot + page HTML) into <client folder>/
    runs/<run_label>/ - debug/ on the machine that ran it is local-only and
    staff could be on any computer, so this is what makes 'come tell me what
    happened' actually work regardless of which PC hit the error. Returns a
    link to the run folder (not individual files - there are several)."""
    drive = get_drive_service()
    run_folder_id = _run_folder_id(drive, spreadsheet_id, run_label)

    mimetypes = {".png": "image/png", ".html": "text/html"}
    for local_path in files:
        local_path = Path(local_path)
        media = MediaFileUpload(str(local_path), mimetype=mimetypes.get(local_path.suffix, "application/octet-stream"))
        file_meta = {"name": local_path.name, "parents": [run_folder_id]}
        drive.files().create(body=file_meta, media_body=media, fields="id", supportsAllDrives=True).execute()

    folder_meta = drive.files().get(fileId=run_folder_id, fields="webViewLink", supportsAllDrives=True).execute()
    return folder_meta.get("webViewLink", f"https://drive.google.com/drive/folders/{run_folder_id}")
