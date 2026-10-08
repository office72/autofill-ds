"""Prints what this machine's browser looks like from the outside.

Run it on a machine that works and on a machine that gets refused, and
compare. The point is to stop guessing which signal matters: the one that
differs between the two is the one worth money and effort.

It opens the bot's own browser, the same way a run does, so what it reports
is what the government site actually sees - not what a different browser on
the same machine would say.

    python check_browser_fingerprint.py

Nothing is submitted anywhere. It loads a blank page, asks the browser about
itself, prints it and closes.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
# On a worker machine the bot's own code lives in bot_runtime/, fetched from
# Drive at the start of every run - so look there too rather than requiring
# this file to sit in a particular folder.
sys.path.append(str(HERE / "bot_runtime"))

try:
    import run_autofill  # noqa: E402
except ModuleNotFoundError:
    raise SystemExit(
        "run_autofill.py was not found next to this script or in bot_runtime/. "
        "Put this file in the bot folder (the one with launcher.py) and run it "
        "after at least one run has fetched the code.")

PROBE = """
const gl = document.createElement('canvas').getContext('webgl');
const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
return {
  'user agent': navigator.userAgent,
  'platform': navigator.platform,
  'languages': (navigator.languages || []).join(', '),
  'timezone': Intl.DateTimeFormat().resolvedOptions().timeZone,
  'timezone offset (min)': new Date().getTimezoneOffset(),
  'cpu cores': navigator.hardwareConcurrency,
  'device memory (GB)': navigator.deviceMemory,
  'screen': screen.width + 'x' + screen.height + ' @' + window.devicePixelRatio,
  'window': window.innerWidth + 'x' + window.innerHeight,
  'colour depth': screen.colorDepth,
  'touch points': navigator.maxTouchPoints,
  'webdriver flag': navigator.webdriver,
  'pdf viewer': navigator.pdfViewerEnabled,
  'plugins': navigator.plugins.length,
  'webgl vendor': dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : '(none)',
  'webgl renderer': dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : '(none)',
};
"""

# A short list is itself a signal: a bare server install has far fewer of
# these than a desktop anyone actually uses.
FONTS = ["Arial", "Calibri", "Cambria", "Candara", "Comic Sans MS", "Consolas",
         "Constantia", "Corbel", "Courier New", "David", "Ebrima", "Franklin Gothic",
         "Gabriola", "Georgia", "Impact", "Ink Free", "Javanese Text", "Leelawadee UI",
         "Lucida Console", "Malgun Gothic", "Marlett", "Microsoft Himalaya",
         "Narkisim", "Nirmala UI", "Palatino Linotype", "Segoe Print", "Segoe Script",
         "Segoe UI", "SimSun", "Sylfaen", "Tahoma", "Times New Roman", "Trebuchet MS",
         "Verdana", "Wingdings", "Yu Gothic"]

FONT_PROBE = """
const have = [];
for (const f of arguments[0]) { if (document.fonts.check('12px "' + f + '"')) have.push(f); }
return have;
"""


def main():
    print("opening the bot's browser (this is the same browser a run uses)...")
    driver = run_autofill._build_driver_with_retry()
    try:
        driver.get("about:blank")
        facts = driver.execute_script(PROBE)
        fonts = driver.execute_script(FONT_PROBE, FONTS)
    finally:
        driver.quit()
        run_autofill._kill_orphaned_chrome_processes(run_autofill.CHROME_PROFILE_DIR)

    print()
    for key, value in facts.items():
        print(f"   {key:<22} {value}")
    print(f"   {'fonts present':<22} {len(fonts)} of {len(FONTS)} common desktop fonts")
    print(f"   {'':<22} {', '.join(fonts[:12])}{' ...' if len(fonts) > 12 else ''}")
    print()
    print("Copy this whole block for comparison with the other machine.")
    print(json.dumps({**facts, "fonts": len(fonts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
