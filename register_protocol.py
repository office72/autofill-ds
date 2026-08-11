"""
One-time, per-computer setup: registers the passportbot:// URL scheme in
Windows so clicking a passportbot://run?sheet=... link (from the button
inside a client's Sheet) launches launcher_url.py with that link.

Writes only to HKEY_CURRENT_USER (no admin rights needed, affects only the
current Windows user account, trivially reversible - see unregister()).
"""

import sys
import winreg
from pathlib import Path

SCHEME = "passportbot"
BASE_DIR = Path(__file__).parent
COMPILED_EXE = BASE_DIR / "AutofillLauncherURL.exe"

# Prefer the packaged exe (production - no Python needed on this machine) if
# it's been built; otherwise fall back to running the script directly via
# this same interpreter (dev machine testing). Either way, keep the console
# window visible (no pythonw.exe) - staff should see progress/errors.
if COMPILED_EXE.exists():
    COMMAND = f'"{COMPILED_EXE}" "%1"'
    ICON_TARGET = str(COMPILED_EXE)
else:
    LAUNCHER_URL_SCRIPT = BASE_DIR / "launcher_url.py"
    COMMAND = f'"{sys.executable}" "{LAUNCHER_URL_SCRIPT}" "%1"'
    ICON_TARGET = sys.executable


def register():
    base = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}")
    winreg.SetValueEx(base, None, 0, winreg.REG_SZ, f"URL:{SCHEME} Protocol")
    winreg.SetValueEx(base, "URL Protocol", 0, winreg.REG_SZ, "")

    icon_key = winreg.CreateKey(base, "DefaultIcon")
    winreg.SetValueEx(icon_key, None, 0, winreg.REG_SZ, ICON_TARGET)

    command_key = winreg.CreateKey(base, r"shell\open\command")
    winreg.SetValueEx(command_key, None, 0, winreg.REG_SZ, COMMAND)

    print(f"Registered {SCHEME}:// -> {COMMAND}")


def unregister():
    def _delete_tree(key, subkey):
        try:
            child = winreg.OpenKey(key, subkey)
            while True:
                try:
                    sub = winreg.EnumKey(child, 0)
                    _delete_tree(child, sub)
                except OSError:
                    break
            winreg.CloseKey(child)
            winreg.DeleteKey(key, subkey)
        except FileNotFoundError:
            pass

    _delete_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}")
    print(f"Unregistered {SCHEME}://")


if __name__ == "__main__":
    if "--unregister" in sys.argv:
        unregister()
    else:
        register()
