# uninstall.ps1 - Remove autodash startup entry and virtual environment
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RegKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RegName = "autodash"
$VenvDir = ".venv"

Write-Host ""
Write-Host "========================================="
Write-Host " autodash - Uninstall"
Write-Host "========================================="
Write-Host ""

# -- Remove startup registry entry -----------------------------------------
$existing = Get-ItemProperty -Path $RegKey -Name $RegName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-ItemProperty -Path $RegKey -Name $RegName
    Write-Host "[OK] Startup entry removed."
} else {
    Write-Host "[--] No startup entry found."
}

# -- Remove virtual environment --------------------------------------------
if (Test-Path $VenvDir) {
    $answer = Read-Host "Remove the .venv virtual environment? [Y/n]"
    if ($answer -eq "" -or $answer -match "^[Yy]") {
        Remove-Item -Recurse -Force $VenvDir
        Write-Host "[OK] Virtual environment removed."
    } else {
        Write-Host "[--] Virtual environment kept."
    }
} else {
    Write-Host "[--] No virtual environment found."
}

Write-Host ""
Write-Host "========================================="
Write-Host " Uninstall complete."
Write-Host "========================================="
Write-Host ""
