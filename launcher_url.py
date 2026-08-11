"""
Entry point registered for passportbot:// links (see register_protocol.py).
Windows hands the full clicked URL to this script as argv[1], e.g.:
    passportbot://run?sheet=1AbCdEfGh...
(built by the "▶ הרץ" button inside each client's copy of the AUTOFILL
Sheet template - see the Apps Script in that template.)

Keeps the console window open at the end (unlike launcher.py's plain CLI
use) since a click has no parent terminal for staff to read results in.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import launcher


def main():
    if len(sys.argv) < 2:
        print("[launcher_url] No URL was passed in - this is meant to be invoked via a passportbot:// link.")
        input("\nPress Enter to close...")
        sys.exit(1)

    url = sys.argv[1]
    params = parse_qs(urlparse(url).query)
    sheet = params.get("sheet", [None])[0]

    if not sheet:
        print(f"[launcher_url] Could not find a sheet= parameter in: {url}")
        input("\nPress Enter to close...")
        sys.exit(1)

    print(f"[launcher_url] Running for sheet: {sheet}")
    exit_code = launcher.run_with_sheet(sheet)

    print("\n" + ("Done." if exit_code == 0 else f"Finished with exit code {exit_code} - check the Sheet's Status/Notes column."))
    input("Press Enter to close this window...")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
