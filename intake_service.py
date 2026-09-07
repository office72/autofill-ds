"""
HTTP wrapper around extract_client_intake.py's scan_and_build(), so a Zoho
CRM button can trigger the AI document-intake pipeline directly - no staff
PC needed. Unlike run_autofill.py, this step is pure API calls (Drive,
Sheets, Claude) with no browser and no anti-bot pacing requirement, so it
runs entirely server-side on Cloud Run.

Deployed as its own Cloud Run Service, separate from document-analyzer's
existing trigger-service - needs the `anthropic` package that service
deliberately keeps out of its image.
"""

import hmac
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from extract_client_intake import _extract_drive_id, find_client_sheet, get_drive_service, get_sheets_service, scan_and_build

app = Flask(__name__)

INTAKE_SHARED_SECRET = os.environ.get("INTAKE_SHARED_SECRET")
# Deliberately separate from INTAKE_SHARED_SECRET: this one gets embedded in
# plain text in a HYPERLINK() cell formula inside every client Sheet, so
# anyone with edit access to that Sheet can read it by inspecting the
# formula, not just by clicking the link. Keeping it its own secret means a
# leak from a Sheet can only ever be used to enqueue autofill runs - never
# to call /scan_client_documents.
ENQUEUE_SHARED_SECRET = os.environ.get("ENQUEUE_SHARED_SECRET")

# Same "Job Queue" Sheet worker_agent.py polls on the worker machine(s) -
# see PLATFORM_PLAN.md / the 2026-09 remote-trigger proof of concept. This
# endpoint exists so a client Sheet's "run" link can enqueue a job without
# going through Apps Script or passportbot:// at all - both confirmed
# blocked outright by NetFree on at least one staff computer, unlike a
# plain HYPERLINK() cell opening an ordinary https:// URL.
QUEUE_SPREADSHEET_ID = "11Aj96yzN8TZpDJ92flJju3Bp4lyvKhrU4EeSBwgHZjo"

# Bumped by hand on every deploy - confirmed live 2026-08-19: a real fix
# (marriage-name-change grouping) was built and tested locally, but the
# Cloud Run service kept running the old image for days because nothing
# ever proved a deploy had actually landed. Checking this after every
# `gcloud run deploy` closes that gap - no more trusting that a deploy
# command exiting 0 means the new code is what's actually serving traffic.
SERVICE_VERSION = "2026-09-07-1"


def _get_param(body, name):
    # Zoho Deluge's invokeurl sends form-encoded, not JSON - same real bug
    # already found and fixed in document-analyzer's trigger_service.py.
    return body.get(name) or request.values.get(name)


@app.post("/scan_client_documents")
def scan_client_documents():
    if not INTAKE_SHARED_SECRET:
        return jsonify({"error": "INTAKE_SHARED_SECRET not configured"}), 500

    body = request.get_json(silent=True) or {}
    provided_secret = _get_param(body, "secret") or ""
    if not hmac.compare_digest(provided_secret, INTAKE_SHARED_SECRET):
        return jsonify({"error": "invalid secret"}), 403

    folder_arg = _get_param(body, "folder_id")
    sheet_arg = _get_param(body, "sheet_id")  # optional override - normally auto-discovered
    if not folder_arg:
        return jsonify({"error": "folder_id is required"}), 400

    try:
        drive = get_drive_service()
        folder_id = _extract_drive_id(folder_arg)
        spreadsheet_id = _extract_drive_id(sheet_arg) if sheet_arg else find_client_sheet(drive, folder_id)
        summary, unmatched = scan_and_build(drive, folder_id, spreadsheet_id, rename_files=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    return jsonify(
        {
            "status": "ok",
            "applicants": summary,
            "unmatched_fillout_docs": [name for name, _ in unmatched],
        }
    ), 200


@app.get("/enqueue")
def enqueue():
    """Meant to be opened as a plain link (a HYPERLINK() cell in the client
    Sheet), not called programmatically - a click here is a person, so this
    returns an HTML page, not JSON, and never redirects to run_autofill.py
    itself. It only adds a row to the Job Queue; a worker machine
    (worker_agent.py) picks it up on its own next poll."""
    if not ENQUEUE_SHARED_SECRET:
        return "שגיאה: השירות לא מוגדר (ENQUEUE_SHARED_SECRET חסר).", 500

    provided_secret = request.args.get("secret") or ""
    if not hmac.compare_digest(provided_secret, ENQUEUE_SHARED_SECRET):
        return "שגיאה: קוד לא תקין.", 403

    sheet_arg = request.args.get("sheet")
    if not sheet_arg:
        return "שגיאה: חסר מזהה שיטס (sheet).", 400

    try:
        sheet_id = _extract_drive_id(sheet_arg)
        job_id = str(uuid.uuid4())
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        get_sheets_service().spreadsheets().values().append(
            spreadsheetId=QUEUE_SPREADSHEET_ID,
            range="Queue!A:G",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[job_id, sheet_id, "pending", requested_at, "", "", ""]]},
        ).execute()
    except Exception as e:
        return f"שגיאה בשליחה לתור: {e}", 502

    return (
        '<html dir="rtl" lang="he"><body style="font-family:sans-serif;text-align:center;padding:60px">'
        "<h2>נשלח להרצה</h2>"
        "<p>אפשר לסגור את החלון - התוצאה תתעדכן בעמודת Status בשיטס בעוד כמה דקות.</p>"
        "</body></html>"
    ), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/version")
def version():
    return jsonify({"version": SERVICE_VERSION}), 200
