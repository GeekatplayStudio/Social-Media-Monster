<#
.SYNOPSIS
    Installs SocialMediaMonster: creates a virtual environment, installs dependencies,
    and initializes the SQLite database.

.DESCRIPTION
    Safe to re-run. Existing data is never deleted; the database is created only if
    missing and is upgraded in place otherwise.

.PARAMETER Force
    Recreate the virtual environment from scratch.

.EXAMPLE
    .\scripts\install.ps1
    .\scripts\install.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Magenta
Write-Host " SOCIAL MEDIA MONSTER - INSTALL" -ForegroundColor Magenta
Write-Host "=================================================================" -ForegroundColor Magenta

# Not Set-Location: changing the caller's directory breaks the next ".\install.ps1" or
# ".\start.ps1" typed from scripts\. All paths below are absolute.

# --------------------------------------------------------------- 1. Python check
Write-Step "Checking Python interpreter"

$pythonCmd = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $verOutput = & $candidate --version 2>&1
        if ($verOutput -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 10) {
                $pythonCmd = $candidate
                Write-Ok "Found $verOutput ($($found.Source))"
                break
            }
            Write-Warn "$candidate is $verOutput - need Python 3.10 or newer"
        }
    }
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Python 3.10+ was not found on PATH." -ForegroundColor Red
    Write-Host "       Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
    exit 1
}

# --------------------------------------------------------------- 2. Virtual environment
Write-Step "Preparing virtual environment (.venv)"

if ($Force -and (Test-Path $VenvPath)) {
    Write-Warn "-Force specified, removing existing .venv"
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPython)) {
    & $pythonCmd -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: venv creation failed." -ForegroundColor Red; exit 1 }
    Write-Ok "Created $VenvPath"
} else {
    Write-Ok "Reusing existing virtual environment"
}

# --------------------------------------------------------------- 3. Dependencies
Write-Step "Installing dependencies from requirements.txt"

& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: dependency installation failed." -ForegroundColor Red
    exit 1
}
Write-Ok "Dependencies installed"

# Record what was installed so start.ps1 can detect a stale environment.
$reqHashFile = Join-Path $ProjectRoot '.venv\.requirements.sha256'
(Get-FileHash (Join-Path $ProjectRoot 'requirements.txt') -Algorithm SHA256).Hash |
    Set-Content -Path $reqHashFile -Encoding utf8

# --------------------------------------------------------------- 4. Database
Write-Step "Initializing SQLite database"
& $VenvPython -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from src.core.db import init_db; init_db(); print('    database ready')"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: database init failed." -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- 5. Encryption key
Write-Step "Checking credential encryption key"
$secretFile = Join-Path $ProjectRoot '.env.secret'
if (Test-Path $secretFile) {
    Write-Ok "Existing .env.secret found (keep this file safe and out of git)"
} else {
    & $VenvPython -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from src.core.security import SecurityManager; SecurityManager()"
    Write-Ok "Generated a new .env.secret master key"
}

# --------------------------------------------------------------- 6. Summary
Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host " INSTALL COMPLETE" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Start the engine :  .\scripts\start.ps1"
Write-Host " Stop the engine  :  .\scripts\stop.ps1"
Write-Host " Run the tests    :  .\.venv\Scripts\python.exe -m pytest tests\ -q"
Write-Host ""
Write-Host " Tavily is OPTIONAL. Without a key the ResearchAgent uses Google News RSS."
Write-Host " To enable it, open the dashboard -> Provider Config -> Tavily Research API Key."
Write-Host ""
