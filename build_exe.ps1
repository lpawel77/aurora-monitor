<#
    build_exe.ps1
    ---------------
    Buduje aurora-monitor.exe - jeden plik, ktory mozna uruchomic
    na dowolnym komputerze z Windows, bez instalowania Pythona.

    Uzycie (w PowerShell, w tym folderze):
        .\build_exe.ps1
#>

$ErrorActionPreference = "Stop"

function Fail($msg) {
    Write-Host ""
    Write-Host "BLAD: $msg" -ForegroundColor Red
    Read-Host "Wcisnij Enter, aby zamknac"
    exit 1
}

Write-Host "=== Budowanie aurora-monitor.exe ===" -ForegroundColor Cyan

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Fail "Nie znaleziono Pythona. Zainstaluj Python 3.10+ z https://www.python.org/downloads/ (zaznacz 'Add python.exe to PATH') i uruchom ten skrypt ponownie."
}

Write-Host "Uzywam: $($python.Source)"

Write-Host "Tworze srodowisko do budowania (.build-venv)..."
python -m venv "$PSScriptRoot\.build-venv"
$venvPython = "$PSScriptRoot\.build-venv\Scripts\python.exe"

Write-Host "Instaluje zaleznosci + pyinstaller..."
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install requests matplotlib numpy pyinstaller -q
if ($LASTEXITCODE -ne 0) { Fail "Instalacja zaleznosci nie powiodla sie." }

Write-Host "Buduje jeden plik .exe (PyInstaller)..."
Push-Location $PSScriptRoot
& $venvPython -m PyInstaller `
    --onefile `
    --windowed `
    --name aurora-monitor `
    aurora_gui.py
$buildOk = ($LASTEXITCODE -eq 0)
Pop-Location

if (-not $buildOk) { Fail "PyInstaller zwrocil blad - zobacz log powyzej." }

$exePath = "$PSScriptRoot\dist\aurora-monitor.exe"
if (-not (Test-Path $exePath)) { Fail "Nie znaleziono wynikowego pliku .exe w dist\." }

Write-Host ""
Write-Host "Gotowe: $exePath" -ForegroundColor Green
Write-Host "Skopiuj ten plik na dowolny komputer z Windows - nie potrzeba tam Pythona."
Read-Host "Wcisnij Enter, aby zamknac"
