"""Builds the installer ZIP for a staff computer, from the current files.

There was a ZIP built by hand in August. By October its launcher.py and its
install.ps1 were both months behind - and install.ps1 in particular had since
grown three fixes learned on real machines (a pre-existing too-old Python that
made the version check pass, a temp path with a space in it that aborted the
install after Python had already been installed, and a stale PATH that kept
resolving to the wrong interpreter). A staff computer installed from that ZIP
would have hit all three again.

So the package is built from the repository, by script, and can be rebuilt in
one command whenever the shell files change.

    python build_installer.py

Note what travels in it: service_account.json. Hand it over on a USB stick or
through a remote-desktop session. Not email, not Drive, not chat.
"""
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "AmericanDocsAutofill_Installer.zip"

# The shell: installed once per computer, almost never changes. Everything
# else - the bot's actual logic - is fetched from Drive at the start of every
# run, which is why a fix does not need any of this to be redistributed.
FILES = [
    "install.bat",
    "install.ps1",
    "launcher.py",
    "launcher_url.py",
    "register_protocol.py",
    "requirements.txt",
    "service_account.json",
]

README = """American Docs - Autofill Bot - Installation
=============================================

One time per computer:

1. Copy this whole folder to the computer (USB stick or remote desktop).
2. Double-click install.bat
3. Wait. If the computer has no suitable Python it installs one first, which
   takes a few minutes. A window shows the progress; press a key to close it
   when it says Done.

From then on, the Run button inside any client's AUTOFILL Sheet opens the bot
on that computer.

Future fixes need no reinstall anywhere: the bot downloads its own logic from
Drive before every run. This package only has to be handed out again if the
installer itself changes.

Optional, only for a machine that will run FormBridge cases (not the Sheet
flow), in PowerShell on that machine:

    setx FORMBRIDGE_URL "<the FormBridge address>"
    setx FORMBRIDGE_WORKER_SECRET "<the worker secret>"

Pacing, if a machine starts being blocked by the government site - minimum and
maximum seconds to wait between two applicants, no reinstall needed:

    setx AUTOFILL_APPLICANT_PAUSE "300,600"

Uninstall:
    python register_protocol.py --unregister
    then delete %LOCALAPPDATA%\\AmericanDocsAutofill

service_account.json inside this package is a credential. Do not email it, do
not put it on Drive, do not paste it anywhere.
"""


def build() -> Path:
    missing = [name for name in FILES if not (HERE / name).is_file()]
    if missing:
        raise SystemExit(f"missing from the repository: {', '.join(missing)}")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES:
            zf.write(HERE / name, arcname=name)
        zf.writestr("README.txt", README)
    return OUT


if __name__ == "__main__":
    path = build()
    with zipfile.ZipFile(path) as zf:
        print(f"{path.name}  ({path.stat().st_size // 1024} KB)")
        for info in zf.infolist():
            print(f"   {info.filename:<26} {info.file_size:>6} bytes")
