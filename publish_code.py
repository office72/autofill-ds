"""
Publishes the current run_autofill.py + sheets_backend.py to the
AUTOFILL_קוד_מערכת Drive folder - run this whenever a code fix/update is
ready to go out to every staff computer. No reinstall needed anywhere: each
computer's launcher.py re-downloads these files fresh before every run.
"""

from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SERVICE_ACCOUNT_FILE = r"C:\Users\office_americandocs\document-analyzer\service_account.json"
CODE_FOLDER_ID = "1A1w0epVQmT9C1mBIe_F1-8PuJDtWIyG4"
SCOPES = ["https://www.googleapis.com/auth/drive"]

FILES_TO_PUBLISH = ["run_autofill.py", "sheets_backend.py"]


def publish():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)

    for filename in FILES_TO_PUBLISH:
        local_path = Path(__file__).parent / filename
        media = MediaFileUpload(str(local_path), mimetype="text/x-python", resumable=False)

        existing = drive.files().list(
            q=f"'{CODE_FOLDER_ID}' in parents and name='{filename}' and trashed=false",
            fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute().get("files", [])

        if existing:
            drive.files().update(fileId=existing[0]["id"], media_body=media, supportsAllDrives=True).execute()
            print(f"Updated {filename}")
        else:
            meta = {"name": filename, "parents": [CODE_FOLDER_ID]}
            drive.files().create(body=meta, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"Uploaded {filename} (new)")


if __name__ == "__main__":
    publish()
