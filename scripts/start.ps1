<#
.SYNOPSIS
    Builds (if needed) and starts the SocialMediaMonster dashboard + MCP server.

.DESCRIPTION
    The build phase is automatic and idempotent: it provisions the virtual environment,
    reinstalls dependencies when requirements.txt has changed, and initializes the
    database. Then it launches the server and waits until it answers /api/health.

    The engine starts HIBERNATING. Nothing is scanned or posted until you press
    "Execute Cycle" in the dashboard.

.PARAMETER Port
    Port to bind. Default 8000.

.PARAMETER BindHost
    Address to bind. Default 127.0.0.1 (local only).

.PARAMETER Foreground
    Run in this console instead of the background. Ctrl+C stops it.

.PARAMETER SkipBuild
    Skip the dependency/database build phase for a faster restart.

.EXAMPLE
    .\scripts\start.ps1
    .\scripts\start.ps1 -Port 8080 -Foreground
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$BindHost = '127.0.0.1',
    [switch]$Foreground,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$RunDir = Join-Path $ProjectRoot '.run'
$PidFile = Join-Path $RunDir 'app.pid'
$PortFile = Join-Path $RunDir 'app.port'
$LogFile = Join-Path $RunDir 'server.log'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Magenta
Write-Host " SOCIAL MEDIA MONSTER - START" -ForegroundColor Magenta
Write-Host "=================================================================" -ForegroundColor Magenta

Set-Location $ProjectRoot
if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir | Out-Null }

# --------------------------------------------------------------- Already running?
if (Test-Path $PidFile) {
    $existingPid = (Get-Content $PidFile -Raw).Trim()
    $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Warn "Already running (PID $existingPid). Stop it first with .\scripts\stop.ps1"
        exit 1
    }
    Remove-Item $PidFile -Force
}

# --------------------------------------------------------------- Build phase
if (-not $SkipBuild) {
    Write-Step "Build phase"

    $needsInstall = $false
    if (-not (Test-Path $VenvPython)) {
        Write-Warn "No virtual environment found"
        $needsInstall = $true
    } else {
        $reqHashFile = Join-Path $ProjectRoot '.venv\.requirements.sha256'
        $currentHash = (Get-FileHash (Join-Path $ProjectRoot 'requirements.txt') -Algorithm SHA256).Hash
        $recordedHash = if (Test-Path $reqHashFile) { (Get-Content $reqHashFile -Raw).Trim() } else { '' }
        if ($currentHash -ne $recordedHash) {
            Write-Warn "requirements.txt changed since last install"
            $needsInstall = $true
        }
    }

    if ($needsInstall) {
        & (Join-Path $PSScriptRoot 'install.ps1')
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: build failed." -ForegroundColor Red; exit 1 }
    } else {
        Write-Ok "Environment up to date"
        & $VenvPython -c "from src.core.db import init_db; init_db()"
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: database init failed." -ForegroundColor Red; exit 1 }
        Write-Ok "Database ready"
    }
} else {
    Write-Warn "Build phase skipped (-SkipBuild)"
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERROR: no .venv found. Run .\scripts\install.ps1 first." -ForegroundColor Red
        exit 1
    }
}

# --------------------------------------------------------------- Port availability
$inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    $holderPid = $inUse[0].OwningProcess
    $holder = Get-Process -Id $holderPid -ErrorAction SilentlyContinue
    $holderCmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $holderPid" -ErrorAction SilentlyContinue).CommandLine

    $isOurs = $false
    if ($holderCmd) {
        $normalized = $holderCmd.Replace('/', '\')
        $isOurs = ($normalized -match 'SocialMediaMonster') -or
                  ($normalized -match '\bmain\.py\b' -and $normalized -notmatch 'backend\.')
    }

    Write-Host ""
    Write-Host "ERROR: port $Port is already in use." -ForegroundColor Red
    Write-Host "  PID     : $holderPid ($($holder.ProcessName))" -ForegroundColor Red
    Write-Host "  Command : $holderCmd" -ForegroundColor Red
    Write-Host ""

    if ($isOurs) {
        Write-Host "  That is another SocialMediaMonster instance. Stop it first:" -ForegroundColor Yellow
        Write-Host "      .\scripts\stop.ps1 -Port $Port" -ForegroundColor Yellow
    } else {
        Write-Host "  That is a DIFFERENT application, so it was left alone." -ForegroundColor Yellow
        # Offer a port that is actually free rather than making the user hunt for one.
        $free = $null
        foreach ($candidate in ($Port + 1)..($Port + 20)) {
            if (-not (Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)) {
                $free = $candidate
                break
            }
        }
        if ($free) {
            Write-Host "  Start on a free port instead:" -ForegroundColor Yellow
            Write-Host "      .\scripts\start.ps1 -Port $free" -ForegroundColor Yellow
        } else {
            Write-Host "  Pick a free port with: .\scripts\start.ps1 -Port <number>" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    exit 1
}

# --------------------------------------------------------------- Launch
$env:SMM_HOST = $BindHost
$env:SMM_PORT = "$Port"
$url = "http://${BindHost}:${Port}"

if ($Foreground) {
    Write-Step "Starting in foreground at $url  (Ctrl+C to stop)"
    Write-Host ""
    & $VenvPython (Join-Path $ProjectRoot 'main.py')
    exit $LASTEXITCODE
}

Write-Step "Starting server at $url"

$proc = Start-Process -FilePath $VenvPython `
    -ArgumentList (Join-Path $ProjectRoot 'main.py') `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError (Join-Path $RunDir 'server.err.log') `
    -WindowStyle Hidden `
    -PassThru

$proc.Id | Set-Content -Path $PidFile -Encoding utf8
"$Port" | Set-Content -Path $PortFile -Encoding utf8

# --------------------------------------------------------------- Readiness probe
Write-Step "Waiting for the server to become ready"
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) {
        Write-Host "ERROR: server exited during startup (code $($proc.ExitCode))." -ForegroundColor Red
        Write-Host "--- last log lines ---" -ForegroundColor Red
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 20 }
        if (Test-Path (Join-Path $RunDir 'server.err.log')) { Get-Content (Join-Path $RunDir 'server.err.log') -Tail 20 }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
    try {
        $resp = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 3 -ErrorAction Stop
        $ready = $true
        break
    } catch { }
}

if (-not $ready) {
    Write-Host "ERROR: server did not answer /api/health within 20 seconds." -ForegroundColor Red
    Write-Host "       Check $LogFile" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host " RUNNING" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard       : $url"
Write-Host "  MCP manifest    : $url/api/mcp/manifest"
Write-Host "  PID             : $($proc.Id)   (log: .run\server.log)"
Write-Host "  Mode            : $($resp.mode)"
Write-Host "  Research engine : $($resp.research_engine)" -NoNewline
if ($resp.research_engine -eq 'rss') {
    Write-Host "  (Tavily key not set - optional)" -ForegroundColor DarkGray
} else {
    Write-Host "  (Tavily enabled)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  The engine is HIBERNATING. Open the dashboard and press" -ForegroundColor Yellow
Write-Host "  'Execute Cycle' to run the pipeline manually." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Stop with: .\scripts\stop.ps1"
Write-Host ""
