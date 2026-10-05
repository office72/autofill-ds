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

# worker_agent.py is published too, but ONLY as a download for the worker
# machines (Contabo) - launcher.py does not fetch it per run the way the two
# above are fetched, because the agent is the process doing the fetching.
# Updating it means downloading it on the machine and restarting the agent.
# launcher.py is published for the same reason worker_agent.py is: not fetched
# per run (it *is* the thing that fetches), but downloadable from the Drive
# folder on a worker machine, which beats copying a file over RDP.
FILES_TO_PUBLISH = ["run_autofill.py", "sheets_backend.py", "api_backend.py",
                    "worker_agent.py", "launcher.py"]


def publish():
    # A publish reaches every machine's next run, so check first that the
    # oldest launcher in the field can still load what we are about to send.
    # See check_before_publish.py for the run this exists because of.
    import check_before_publish
    problems = check_before_publish.check()
    if problems:
        for problem in problems:
            print(f"REFUSING TO PUBLISH: {problem}")
        raise SystemExit(1)

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
