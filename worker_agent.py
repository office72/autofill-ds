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
                    exit_code = launcher.run_with_sheet(job["sheet_id"])
                    if exit_code == 0:
                        _update_row(sheets, row_number, {"status": "done", "finished_at": _now()})
                    else:
                        _update_row(
                            sheets, row_number,
                            {"status": "error", "finished_at": _now(), "error": f"exit code {exit_code}"},
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
