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
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found - downloading and installing (per-user, no admin needed)..."
    $pyInstaller = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $pyInstaller
    Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
    Remove-Item $pyInstaller -ErrorAction SilentlyContinue
    # refresh PATH for the rest of this script without needing a new shell
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python install finished but 'python' still isn't on PATH - open a new terminal and re-run this installer."
    }
} else {
    Write-Host "Python found: $($python.Source)"
}

# --- 2. Python packages ---
Write-Host "Installing required Python packages (this can take a few minutes the first time)..."
python -m pip install --upgrade pip --quiet
python -m pip install -r "$ScriptDir\requirements.txt" --quiet

# --- 3. Copy the shell files (launcher.py, launcher_url.py, register_protocol.py,
#         service_account.json) into the install directory ---
$FilesToInstall = @("launcher.py", "launcher_url.py", "register_protocol.py", "service_account.json")
foreach ($f in $FilesToInstall) {
    Copy-Item -Path "$ScriptDir\$f" -Destination "$InstallDir\$f" -Force
}

# --- 4. Register passportbot:// ---
Write-Host "Registering passportbot:// link handler..."
python "$InstallDir\register_protocol.py"

Write-Host ""
Write-Host "Done. passportbot:// links (from the AUTOFILL button inside a client's Sheet) will now open this app."
