"""The same six functions as sheets_backend, against FormBridge instead.

The bot reads and writes its case through exactly six functions. This module
provides all six, with the same names and the same shapes, over HTTP to the
platform:

    resolve_to_spreadsheet_id · load_all_applicants · ready_columns
    set_status · upload_run_output · upload_debug_artifacts

Nothing in run_autofill.py changes. The wizard - every selector, every pause,
every fix learned the hard way against pptform.state.gov - never touched
Google in the first place, and it does not touch HTTP now either. It calls six
functions, and the launcher decides which module answers them.

**sheets_backend.py is not modified.** The flow American Docs runs today is
byte-identical, and a bug here cannot reach it. A job arriving as a sheet id
goes the old way; a job arriving as a case token comes here.

Where the "column letter" went: the sheet identified an applicant by its
column, and the wizard only ever passes that identifier back when reporting.
Here it is the applicant's id, as a string. Opaque either way.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

# Set by the launcher from the environment, so a worker machine holds its
# secret in one place and no case token is ever written to disk.
BASE_URL = os.environ.get("FORMBRIDGE_URL", "").rstrip("/")
WORKER_SECRET = os.environ.get("FORMBRIDGE_WORKER_SECRET", "")
TIMEOUT_SECONDS = 60

# The statuses the bot already uses, kept identical to sheets_backend's so
# run_autofill needs no translation layer.
READY_STATUS = "Ready"
RUNNING_STATUS = "Running"
DONE_STATUS = "Done"
ERROR_STATUS = "Error"
STATUS_ROW_LABEL = "Status"
NOTES_ROW_LABEL = "Notes"

CASE_TOKEN_PREFIX = "case:"


def is_case_handle(arg: str) -> bool:
    """A case token is handed to the bot with a prefix, so nothing has to guess
    from a string's shape whether it is a spreadsheet id or a case."""
    return str(arg or "").startswith(CASE_TOKEN_PREFIX)


def _token(handle: str) -> str:
    return str(handle)[len(CASE_TOKEN_PREFIX):] if is_case_handle(handle) else str(handle)


def _require_config():
    if not BASE_URL:
        raise RuntimeError("FORMBRIDGE_URL is not set on this machine")
    if not WORKER_SECRET:
        raise RuntimeError("FORMBRIDGE_WORKER_SECRET is not set on this machine")


def _request(method: str, path: str, body=None, files=None):
    _require_config()
    url = f"{BASE_URL}{path}"
    headers = {"X-Worker-Secret": WORKER_SECRET}
    data = None
    if files is not None:
        boundary = "----formbridge-boundary-7d91f2"
        parts = []
        for name, value in (body or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        for path_obj in files:
            path_obj = Path(path_obj)
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
                f"filename=\"{path_obj.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
                + path_obj.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"FormBridge {method} {path} -> {e.code}: {detail}") from None


# --- the six -------------------------------------------------------------

def resolve_to_spreadsheet_id(url_or_id: str) -> str:
    """Nothing to resolve: the case token *is* the handle. Kept so the caller
    does not have to know which backend it is talking to."""
    return str(url_or_id)


def load_all_applicants(handle: str) -> dict:
    case = _request("GET", f"/api/worker/cases/{_token(handle)}")
    out = {}
    for applicant_id, applicant in (case.get("applicants") or {}).items():
        fields = dict(applicant.get("data") or {})
        # The wizard reads status and notes out of the same dict it reads
        # fields from, because that is how the sheet presented them.
        fields[STATUS_ROW_LABEL] = {"ready": READY_STATUS, "running": RUNNING_STATUS,
                                    "done": DONE_STATUS, "error": ERROR_STATUS,
                                    }.get(applicant.get("status"), "Needs Review")
        fields.setdefault(NOTES_ROW_LABEL, "")
        out[applicant_id] = fields
    return out


def ready_columns(handle: str) -> list:
    case = _request("GET", f"/api/worker/cases/{_token(handle)}")
    return list(case.get("ready") or [])


def set_status(handle: str, column_letter: str, status: str, note: str = None):
    body = {"status": status}
    if note is not None:
        body["note"] = note
    _request("POST",
             f"/api/worker/cases/{_token(handle)}/applicants/{column_letter}/status",
             body=body)


def upload_run_output(handle: str, local_pdf_path, run_label: str) -> str:
    result = _request("POST", f"/api/worker/cases/{_token(handle)}/documents",
                      body={"label": f"DS form - {run_label}"},
                      files=[local_pdf_path])
    return f"formbridge:document:{result['stored'][0]['id']}"


def record_block(machine: str, context: str, detail: str, spreadsheet_id: str = "") -> None:
    """Counts an anti-bot block. There is no endpoint for it on the platform
    yet, so it is printed rather than pretended about - the sheet-backed runs
    are where the volume is today, and those do record it."""
    print(f"[api_backend] anti-bot block on {machine} ({context}): {str(detail)[:120]}")


def upload_debug_artifacts(handle: str, files, run_label: str) -> str:
    """A failed run's screenshot and page source. Uploaded to the case itself,
    so the evidence sits next to the applicant it belongs to instead of in a
    Drive folder someone has to go find."""
    files = [f for f in files if f and Path(f).is_file()]
    if not files:
        return ""
    result = _request("POST", f"/api/worker/cases/{_token(handle)}/documents",
                      body={"label": f"debug - {run_label}"}, files=files)
    return f"formbridge:debug:{len(result['stored'])} files"
