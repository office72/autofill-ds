# American Docs Autofill Bot - one-time per-computer setup.
# Per-user install (no admin rights needed): everything goes under
# %LOCALAPPDATA%, and the passportbot:// registration is HKEY_CURRENT_USER
# only (see register_protocol.py).

$ErrorActionPreference = "Stop"

$InstallDir = "$env:LOCALAPPDATA\AmericanDocsAutofill"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing to $InstallDir ..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# --- 1. Python ---
# Confirmed live 2026-09: a machine with a pre-existing Python 3.7 (old
# enough to have no wheel for `cryptography` on this platform, forcing a
# from-source build that itself requires Python 3.9+ to bootstrap) made
# `Get-Command python` succeed, so this block used to skip straight past
# installing a working Python - pip then failed partway through
# requirements.txt, silently leaving later packages (googleapiclient,
# anthropic, ...) never installed. Now checks the version too, not just
# whether *a* python exists.
$MinPythonVersion = [version]"3.9.0"
$pythonExe = $null
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $versionOutput = (& python --version) 2>&1
    if ($versionOutput -match '(\d+\.\d+\.\d+)') {
        $foundVersion = [version]$Matches[1]
        if ($foundVersion -ge $MinPythonVersion) {
            $pythonExe = $python.Source
            Write-Host "Python found: $pythonExe"
        } else {
            Write-Host "Found Python $foundVersion at $($python.Source) - too old (need $MinPythonVersion+), installing a current version alongside it."
        }
    }
}
if (-not $pythonExe) {
    Write-Host "Downloading and installing a current Python (per-user, no admin needed)..."
    $pyInstaller = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $pyInstaller
    Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
    # -ErrorAction SilentlyContinue alone isn't enough here - confirmed live
    # 2026-08-16 on a machine whose Windows username has a space in it
    # ("WIN 11"): $env:TEMP resolves to the 8.3 short-path form
    # (...\WIN11~1\...), and Remove-Item's path resolution throws a
    # PSArgumentException on that form before its own -ErrorAction even
    # applies - which $ErrorActionPreference = "Stop" (set at the top of
    # this script) then treats as fatal, aborting the whole install right
    # after Python itself had already finished installing successfully.
    # try/catch is the only thing that reliably swallows it - this is only
    # cleaning up a temp file, never worth failing the install over.
    try { Remove-Item $pyInstaller -ErrorAction Stop } catch {}

    # Don't trust PATH resolution here at all, even after refreshing it -
    # confirmed live 2026-09 that a pre-existing older Python can sit ahead
    # of the freshly-installed one in the combined User+Machine PATH, so
    # `Get-Command python` can keep resolving to the same too-old
    # interpreter that got us into this branch in the first place. This is
    # the well-known install location for python.org's per-user installer
    # (InstallAllUsers=0) - go straight there instead of guessing from PATH.
    $pythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Python install finished but $pythonExe doesn't exist - installer layout may have changed, check manually."
    }
    Write-Host "Installed Python: $pythonExe"
}

# --- 2. Python packages ---
Write-Host "Installing required Python packages (this can take a few minutes the first time)..."
& $pythonExe -m pip install --upgrade pip --quiet
& $pythonExe -m pip install -r "$ScriptDir\requirements.txt" --quiet

# --- 3. Copy the shell files (launcher.py, launcher_url.py, register_protocol.py,
#         service_account.json) into the install directory ---
$FilesToInstall = @("launcher.py", "launcher_url.py", "register_protocol.py", "service_account.json")
foreach ($f in $FilesToInstall) {
    Copy-Item -Path "$ScriptDir\$f" -Destination "$InstallDir\$f" -Force
}

# --- 4. Register passportbot:// ---
Write-Host "Registering passportbot:// link handler..."
& $pythonExe "$InstallDir\register_protocol.py"

Write-Host ""
Write-Host "Done. passportbot:// links (from the AUTOFILL button inside a client's Sheet) will now open this app."
