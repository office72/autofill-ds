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

from flask import Flask, jsonify, request

from extract_client_intake import _extract_drive_id, find_client_sheet, get_drive_service, scan_and_build

app = Flask(__name__)

INTAKE_SHARED_SECRET = os.environ.get("INTAKE_SHARED_SECRET")

# Bumped by hand on every deploy - confirmed live 2026-08-19: a real fix
# (marriage-name-change grouping) was built and tested locally, but the
# Cloud Run service kept running the old image for days because nothing
# ever proved a deploy had actually landed. Checking this after every
# `gcloud run deploy` closes that gap - no more trusting that a deploy
# command exiting 0 means the new code is what's actually serving traffic.
SERVICE_VERSION = "2026-08-24-3"


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


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/version")
def version():
    return jsonify({"version": SERVICE_VERSION}), 200
