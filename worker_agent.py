"""
PROOF OF CONCEPT - remote-trigger worker agent.

Goal being tested: can the browser-automation bot be launched on a machine
(e.g. the Contabo RDP box) WITHOUT anyone remoting in and clicking anything,
and WITHOUT touching anything in the existing production flow
(launcher.py / launcher_url.py / passportbot://)?

Mechanism: this script polls a small "Job Queue" Google Sheet every
POLL_INTERVAL_SECONDS. When it finds a row with status="pending", it marks
it "running", calls launcher.run_with_sheet() - the EXACT SAME function the
passportbot:// click handler already uses - and writes back "done"/"error"
when finished. Nothing about run_autofill.py, launcher.py, or the existing
click-to-run flow is touched; this is a second, independent way to trigger
the same unmodified code.

Why polling FROM the worker machine, not a command pushed TO it: no inbound
network/firewall exposure needed on the worker box, and - critically - this
keeps everything running inside a real, already-logged-in interactive
desktop session (Startup folder, not a Windows Service/WinRM/Task Scheduler
"run whether user is logged on or not"). A Service/WinRM-launched process
runs in Session 0, which does not give Chrome a real visible desktop - that
would very plausibly break the exact headed-browser behavior that lets this
site's Cloudflare check pass today (see feedback_anti_bot_pacing).

Usage:
    python worker_agent.py

Stop with Ctrl+C. Runs forever, checking the queue on an interval.
"""

import os
import socket
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import launcher  # noqa: E402 - reused unmodified: same run_with_sheet() the passportbot:// handler calls
from extract_client_intake import get_sheets_service  # noqa: E402 - reused unmodified credential/service helper

QUEUE_SPREADSHEET_ID = "11Aj96yzN8TZpDJ92flJju3Bp4lyvKhrU4EeSBwgHZjo"
QUEUE_SHEET_NAME = "Queue"
POLL_INTERVAL_SECONDS = 20

# A job stuck on "running" past this many minutes almost certainly means the
# machine that claimed it died or hung mid-run (power loss, RDP session
# logged off, etc.) - no other machine would ever pick it up otherwise,
# since only "pending" rows are eligible. No machine needs to know whether
# another one is still alive - the row's own timestamp is enough evidence.
STALE_JOB_TIMEOUT_MINUTES = 45

COLUMNS = ["job_id", "sheet_id", "status", "requested_at", "started_at", "finished_at", "error"]

# A failed run is retried automatically, but only when the failure looks
# transient (anti-bot block, a slow postback, a browser/session crash). A
# failure caused by the applicant's own data in the Sheet, or by the
# government site refusing the answers themselves, would fail again exactly
# the same way, so retrying it just burns runs against a site that already
# rate-limits us. Retry markers are matched against the Notes text the bot
# itself wrote into the applicant's column.
RETRY_DELAY_SECONDS = 300
MAX_ATTEMPTS = 2
NO_RETRY_NOTE_MARKERS = (
    "error on the following field",   # FieldValidationError - the site rejected a value
    "negative number",                # _validate_applicant_data - broken Sheet cell
    "is not implemented",             # unsupported Passport Scenario
)

WORKERS_SHEET_NAME = "Workers"
WORKER_COLUMNS = ["worker_id", "last_seen", "status", "current_job_id"]
# Hostname, not something hand-configured per machine - Contabo and this
# local test box already have different hostnames, so every worker gets a
# distinct identity for free with zero setup.
WORKER_ID = socket.gethostname()
# A control panel reading this tab treats a worker as offline once last_seen
# is older than this - comfortably more than one poll interval so a single
# slow cycle doesn't look like an outage.
WORKER_OFFLINE_AFTER_MINUTES = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _find_pending_job(sheets):
    values = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=QUEUE_SPREADSHEET_ID, range=f"{QUEUE_SHEET_NAME}!A2:G")
        .execute()
        .get("values", [])
    )
    for i, row in enumerate(values):
        row = row + [""] * (len(COLUMNS) - len(row))
        job = dict(zip(COLUMNS, row))
        if job["status"] == "pending":
            return i + 2, job  # +2: 1-indexed sheet rows, plus the header row
    return None, None


def _reclaim_stale_jobs(sheets):
    values = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=QUEUE_SPREADSHEET_ID, range=f"{QUEUE_SHEET_NAME}!A2:G")
        .execute()
        .get("values", [])
    )
    now = datetime.now(timezone.utc)
    for i, row in enumerate(values):
        row = row + [""] * (len(COLUMNS) - len(row))
        job = dict(zip(COLUMNS, row))
        if job["status"] != "running" or not job["started_at"]:
            continue
        age_minutes = (now - datetime.fromisoformat(job["started_at"])).total_seconds() / 60
        if age_minutes > STALE_JOB_TIMEOUT_MINUTES:
            print(f"[worker_agent] Job '{job['job_id']}' stuck on 'running' for {age_minutes:.0f}m - reclaiming as pending.")
            _update_row(
                sheets, i + 2,
                {"status": "pending", "error": f"reclaimed - previous attempt (started {job['started_at']}) never finished"},
            )


def _load_sheets_backend():
    """sheets_backend.py is NOT part of the installed shell on a worker
    machine - launcher.fetch_latest_code() downloads it from Drive into
    bot_runtime/ on every run, and run_autofill.py imports it there as a
    subprocess whose cwd is that directory. This process has no such cwd, so
    importing it by name fails with ModuleNotFoundError on every machine
    except a dev box that happens to have a copy of the repo.

    That is exactly what broke every Contabo job from 2026-09-22 on: the
    import sat at the top of _run_with_retries(), so it raised one second
    after the job was claimed - before the browser was ever launched - and
    the queue recorded "No module named 'sheets_backend'" instead of running
    the job at all.
    """
    runtime_dir = str(launcher.RUNTIME_DIR)
    if runtime_dir not in sys.path:
        sys.path.append(runtime_dir)
    # launcher.py hands this to the bot subprocess but not to this process,
    # and sheets_backend resolves its credentials at import time - so without
    # it the retry check fails on a machine where the file is sitting right
    # there next to the launcher.
    os.environ.setdefault("AUTOFILL_SERVICE_ACCOUNT", launcher.SERVICE_ACCOUNT_FILE)
    import sheets_backend
    return sheets_backend


def _failed_columns(spreadsheet_id: str) -> list:
    """Every applicant left on Status=Error, whatever the reason."""
    try:
        sheets_backend = _load_sheets_backend()
        applicants = sheets_backend.load_all_applicants(spreadsheet_id)
    except Exception as e:
        print(f"[worker_agent] Could not read back the applicants' status: {e}")
        return []
    return [column for column, data in applicants.items()
            if str(data.get(sheets_backend.STATUS_ROW_LABEL) or "").strip() == "Error"]


def _retryable_failed_columns(spreadsheet_id: str) -> list:
    """Applicant columns whose Status is Error and whose Notes do NOT look
    like a data problem - i.e. the ones worth running again in a few
    minutes. Requested by the user (2026-09-15) after a Cloudflare block hit
    the very last step (the PDF download) of an otherwise perfect run: an
    immediate manual re-run went through, so the work was lost for no reason
    other than timing."""
    sheets_backend = _load_sheets_backend()

    applicants = sheets_backend.load_all_applicants(spreadsheet_id)
    retryable = []
    for column, data in applicants.items():
        if str(data.get(sheets_backend.STATUS_ROW_LABEL) or "").strip() != "Error":
            continue
        note = str(data.get(sheets_backend.NOTES_ROW_LABEL) or "").lower()
        if any(marker.lower() in note for marker in NO_RETRY_NOTE_MARKERS):
            print(f"[worker_agent] Column {column} failed on a data/answer problem - not retrying.")
            continue
        retryable.append(column)
    return retryable


def _run_with_retries(sheets, row_number: int, job: dict) -> tuple:
    """Runs the job, then re-runs just the applicants that failed for a
    transient reason, after a pause. Returns (status, error_text).

    Nothing in the retry machinery may run before the job itself: a retry is
    an extra, and a broken extra must never cost us the run.
    """
    exit_code = launcher.run_with_sheet(job["sheet_id"])
    if exit_code == 0:
        # Exit code 0 only means the queue was worked through. A failure on one
        # applicant is recorded on that applicant and deliberately does not
        # abort the rest - so a row saying "done" while a client sits on
        # Status=Error is exactly how a stuck case stays invisible (seen
        # 2026-10-05). Report what actually happened to the people in it.
        failed = _failed_columns(job["sheet_id"])
        if failed:
            return "error", f"finished, but {len(failed)} applicant(s) failed: {', '.join(failed)}"
        return "done", ""

    attempt = 1
    error = f"exit code {exit_code}"
    while attempt < MAX_ATTEMPTS:
        # Deciding whether to retry must not be able to replace the real
        # failure with its own - that is how the original error got lost.
        try:
            columns = _retryable_failed_columns(job["sheet_id"])
            sheets_backend = _load_sheets_backend()
        except Exception as e:
            print(f"[worker_agent] Could not check for retryable columns: {e}")
            traceback.print_exc()
            return "error", f"{error} (retry check failed: {str(e)[:200]})"
        if not columns:
            return "error", error
        print(f"[worker_agent] Retrying {', '.join(columns)} in {RETRY_DELAY_SECONDS}s "
              f"(attempt {attempt + 1}/{MAX_ATTEMPTS}).")
        _update_row(sheets, row_number, {"error": f"{error} - retrying {','.join(columns)} in "
                                                  f"{RETRY_DELAY_SECONDS // 60}m"})
        time.sleep(RETRY_DELAY_SECONDS)
        for column in columns:
            sheets_backend.set_status(job["sheet_id"], column, sheets_backend.READY_STATUS, "")
        exit_code = launcher.run_with_sheet(job["sheet_id"])
        attempt += 1
        if exit_code == 0:
            return "done", f"succeeded on attempt {attempt}"
        error = f"exit code {exit_code} (attempt {attempt})"
    return "error", error


def _heartbeat(sheets, status: str, current_job_id: str = ""):
    """Writes/updates this machine's own row in the Workers tab - "I'm alive,
    here's what I'm doing right now." A control panel reads this tab to show
    which machines exist and what each one is up to; it never needs to
    contact a machine directly."""
    values = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=QUEUE_SPREADSHEET_ID, range=f"{WORKERS_SHEET_NAME}!A2:D")
        .execute()
        .get("values", [])
    )
    row_number = next((i + 2 for i, row in enumerate(values) if row and row[0] == WORKER_ID), None)
    values_row = [[WORKER_ID, _now(), status, current_job_id]]
    if row_number:
        sheets.spreadsheets().values().update(
            spreadsheetId=QUEUE_SPREADSHEET_ID, range=f"{WORKERS_SHEET_NAME}!A{row_number}:D{row_number}",
            valueInputOption="RAW", body={"values": values_row},
        ).execute()
    else:
        sheets.spreadsheets().values().append(
            spreadsheetId=QUEUE_SPREADSHEET_ID, range=f"{WORKERS_SHEET_NAME}!A:D",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": values_row},
        ).execute()


def _update_row(sheets, row_number: int, updates: dict):
    data = [
        {"range": f"{QUEUE_SHEET_NAME}!{chr(ord('A') + COLUMNS.index(col))}{row_number}", "values": [[value]]}
        for col, value in updates.items()
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=QUEUE_SPREADSHEET_ID, body={"valueInputOption": "RAW", "data": data}
    ).execute()


def main_loop():
    sheets = get_sheets_service()
    print(f"[worker_agent] Watching queue every {POLL_INTERVAL_SECONDS}s - Ctrl+C to stop.")
    print(f"[worker_agent] Worker id: {WORKER_ID}")
    print(f"[worker_agent] Queue sheet: https://docs.google.com/spreadsheets/d/{QUEUE_SPREADSHEET_ID}")

    while True:
        try:
            _heartbeat(sheets, "idle")
            _reclaim_stale_jobs(sheets)
            row_number, job = _find_pending_job(sheets)
            if job:
                print(f"[worker_agent] Picked up job '{job['job_id']}' -> sheet {job['sheet_id']}")
                _update_row(sheets, row_number, {"status": "running", "started_at": _now()})
                _heartbeat(sheets, "busy", job["job_id"])
                try:
                    status, error = _run_with_retries(sheets, row_number, job)
                    _update_row(
                        sheets, row_number,
                        {"status": status, "finished_at": _now(), "error": error},
                    )
                except Exception as e:
                    _update_row(sheets, row_number, {"status": "error", "finished_at": _now(), "error": str(e)[:500]})
                print(f"[worker_agent] Job '{job['job_id']}' finished.")
        except Exception:
            print("[worker_agent] Error while polling - will retry next interval:")
            traceback.print_exc()

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()
