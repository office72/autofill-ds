"""
The "thin shell" - this is the part that gets installed once per staff
computer and almost never changes. Every time it runs, it re-downloads the
current run_autofill.py + sheets_backend.py from the AUTOFILL_קוד_מערכת
Drive folder into bot_runtime/ and runs that fresh copy - so a code fix
(published via publish_code.py) reaches every computer on its next run,
with no reinstall anywhere.

Usage:
    python launcher.py --sheet <google-sheet-url-or-id> [--column B]

This is also the entry point the passportbot:// protocol handler will call
once that's wired up (Phase 5) - for now, run it directly.
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

# When bundled by PyInstaller, sys.executable is this launcher's own .exe
# (not a python.exe) and __file__ points into a temp extraction dir - resolve
# everything relative to the .exe's real installed location instead, and use
# the interpreter embedded in this frozen process to run the freshly-fetched
# code in-process rather than spawning an external python.exe that won't
# exist on a staff computer with no separate Python install.
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent

SERVICE_ACCOUNT_FILE = str(BASE_DIR / "service_account.json")
CODE_FOLDER_ID = "1A1w0epVQmT9C1mBIe_F1-8PuJDtWIyG4"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

RUNTIME_DIR = BASE_DIR / "bot_runtime"
FILES_TO_FETCH = ["run_autofill.py", "sheets_backend.py"]


def fetch_latest_code():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)

    RUNTIME_DIR.mkdir(exist_ok=True)
    listing = drive.files().list(
        q=f"'{CODE_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    by_name = {f["name"]: f["id"] for f in listing}

    for filename in FILES_TO_FETCH:
        if filename not in by_name:
            raise RuntimeError(f"{filename} not found in the AUTOFILL_קוד_מערכת Drive folder - has it been published?")
        content = drive.files().get_media(fileId=by_name[filename]).execute()
        (RUNTIME_DIR / filename).write_bytes(content)
    print(f"[launcher] Fetched latest code into {RUNTIME_DIR}")


def run_with_sheet(sheet_arg: str, column: str = None) -> int:
    """Fetches the latest code, then runs it against the given sheet/folder
    link. Returns an exit code - shared by the CLI entry point below and
    launcher_url.py (the passportbot:// click handler)."""
    fetch_latest_code()

    if FROZEN:
        # No separate python.exe on a staff computer with no Python install -
        # dynamically load and run the freshly-fetched code inside this
        # already-running (bundled) interpreter instead of spawning one.
        os.environ["AUTOFILL_SERVICE_ACCOUNT"] = SERVICE_ACCOUNT_FILE
        spec = importlib.util.spec_from_file_location("run_autofill", str(RUNTIME_DIR / "run_autofill.py"))
        run_autofill = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(RUNTIME_DIR))
        try:
            spec.loader.exec_module(run_autofill)
            spreadsheet_id = run_autofill.sheets_backend.resolve_to_spreadsheet_id(sheet_arg)
            run_autofill.run_all(spreadsheet_id, only_column=column)
            return 0
        except Exception as e:
            print(f"[launcher] Run failed: {e}")
            return 1
    else:
        cmd = [sys.executable, str(RUNTIME_DIR / "run_autofill.py"), "--sheet", sheet_arg]
        if column:
            cmd += ["--column", column]
        env = {**os.environ, "AUTOFILL_SERVICE_ACCOUNT": SERVICE_ACCOUNT_FILE}
        result = subprocess.run(cmd, cwd=str(RUNTIME_DIR), env=env)
        return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True, help="Client's Google Sheet URL or spreadsheet ID")
    parser.add_argument("--column", required=False, help="Process only this column (testing)")
    args = parser.parse_args()
    sys.exit(run_with_sheet(args.sheet, args.column))


if __name__ == "__main__":
    main()
