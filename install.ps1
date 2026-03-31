# install.ps1 - One-time setup script for autodash (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$VenvDir      = ".venv"
$Requirements = "requirements.txt"
$HashFile     = "$VenvDir\.requirements-hash"

Write-Host ""
Write-Host "========================================="
Write-Host " autodash - Setup"
Write-Host "========================================="
Write-Host ""

# -- Visual C++ Redistributable (required by Playwright / greenlet) --------
$VcKey = "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64"
$VcInstalled = (Test-Path $VcKey) -and ((Get-ItemProperty $VcKey -ErrorAction SilentlyContinue).Installed -eq 1)
if (-not $VcInstalled) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "[..] Installing Visual C++ Redistributable ..."
        winget install --id Microsoft.VCRedist.2015+.x64 -e --silent
        Write-Host "[OK] Visual C++ Redistributable installed."
    } else {
        Write-Host "[WARN] Visual C++ Redistributable not found."
        Write-Host "       Install manually: https://aka.ms/vs/17/release/vc_redist.x64.exe"
    }
}

# -- Python ----------------------------------------------------------------
$PythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $PythonCmd = $cmd
        break
    }
}
if (-not $PythonCmd) {
    Write-Host "[ERROR] Python not found."
    Write-Host "        Download and install from https://www.python.org/"
    Write-Host "        Ensure 'Add Python to PATH' is checked during install."
    exit 1
}
$PyVersion = & $PythonCmd --version 2>&1
Write-Host "[OK] $PyVersion"

# -- Virtual environment ---------------------------------------------------
if (-not (Test-Path "$VenvDir\Scripts\Activate.ps1")) {
    Write-Host "[..] Creating virtual environment ..."
    & $PythonCmd -m venv $VenvDir
    Write-Host "[OK] Virtual environment created."
}
. "$VenvDir\Scripts\Activate.ps1"

# -- Python dependencies (skip when requirements.txt is unchanged) ---------
$CurrentHash = ""
if (Test-Path $Requirements) {
    $CurrentHash = (Get-FileHash $Requirements -Algorithm SHA256).Hash
}
$StoredHash = ""
if (Test-Path $HashFile) {
    $StoredHash = (Get-Content $HashFile -Raw).Trim()
}

$DepsUpdated = $false
if ($CurrentHash -ne $StoredHash) {
    Write-Host "[..] Installing Python dependencies ..."
    pip install --upgrade pip --quiet
    if (Test-Path $Requirements) {
        pip install -r $Requirements --quiet
    } else {
        pip install playwright --quiet
    }
    $CurrentHash | Out-File -FilePath $HashFile -NoNewline -Encoding ascii
    Write-Host "[OK] Dependencies installed."
    $DepsUpdated = $true
}

# -- Playwright Chromium (skip when already installed and deps unchanged) --
$ChromiumDir = "$env:LOCALAPPDATA\ms-playwright"
$ChromiumInstalled = $false
if (Test-Path $ChromiumDir) {
    $ChromiumInstalled = [bool](Get-ChildItem "$ChromiumDir\chromium-*" -Directory -ErrorAction SilentlyContinue)
}

if ($DepsUpdated -or -not $ChromiumInstalled) {
    Write-Host "[..] Installing Chromium browser ..."
    playwright install chromium
    Write-Host "[OK] Chromium ready."
}

# -- Scheduled task (run monitor.py at logon) ------------------------------
$TaskName = "autodash"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existing) {
    $answer = Read-Host "A scheduled task already exists. Update it? [Y/n]"
} else {
    $answer = Read-Host "Create a scheduled task to start autodash at logon? [Y/n]"
}

if ($answer -eq "" -or $answer -match "^[Yy]") {
    $PythonExe  = (Resolve-Path "$VenvDir\Scripts\python.exe").Path
    $ScriptPath = (Resolve-Path "monitor.py").Path
    $action   = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $PSScriptRoot
    $trigger  = New-ScheduledTaskTrigger -AtLogon
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0
    if ($existing) {
        Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
        Write-Host "[OK] Scheduled task updated."
    } else {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
        Write-Host "[OK] Scheduled task created - autodash will start at next logon."
    }
} else {
    Write-Host "[--] Scheduled task skipped."
}

Write-Host ""
Write-Host "========================================="
Write-Host " Setup complete."
Write-Host " To start the monitor, run:"
Write-Host "   $VenvDir\Scripts\python monitor.py"
Write-Host "========================================="
Write-Host ""
