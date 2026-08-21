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
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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
    # Everything (including the `import launcher` above main() used to sit
    # at module level) is now inside this try/except - confirmed live
    # 2026-08-20: on a machine where pip install had failed partway
    # (missing google-api-python-client, not just selenium - a NetFree
    # content filter blocking PyPI), `import launcher` itself raised
    # ModuleNotFoundError before execution ever reached main()'s own
    # "Press Enter to close" safety nets, so the window flashed the
    # traceback and closed too fast to read. This can never happen again
    # regardless of what fails or at what stage - every path now ends in
    # the same pause.
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import launcher

        main()
    except SystemExit:
        raise
    except Exception:
        print("[launcher_url] Unexpected error:\n")
        traceback.print_exc()
        input("\nPress Enter to close...")
        sys.exit(1)
