<#
.SYNOPSIS
    Stops the running SocialMediaMonster server.

.DESCRIPTION
    Sends an in-app emergency stop first so any running agent cycle halts cleanly, then
    terminates the server process recorded in .run\app.pid. If the PID file is missing or
    stale, falls back to whatever process is listening on the port.

.PARAMETER Port
    Port the server is bound to. Defaults to the value recorded by start.ps1, else 8000.

.PARAMETER Force
    Skip the graceful agent stop and terminate immediately.

.EXAMPLE
    .\scripts\stop.ps1
    .\scripts\stop.ps1 -Port 8080 -Force
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $ProjectRoot '.run'
$PidFile = Join-Path $RunDir 'app.pid'
$PortFile = Join-Path $RunDir 'app.port'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Magenta
Write-Host " SOCIAL MEDIA MONSTER - STOP" -ForegroundColor Magenta
Write-Host "=================================================================" -ForegroundColor Magenta

# Resolve the port: explicit parameter, then the file written by start.ps1, then default.
if ($Port -eq 0) {
    if (Test-Path $PortFile) {
        $Port = [int](Get-Content $PortFile -Raw).Trim()
    } else {
        $Port = 8000
    }
}

# --------------------------------------------------------------- Graceful agent halt
if (-not $Force) {
    Write-Step "Requesting emergency stop of background agents"
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/stop" -Method Post -TimeoutSec 5 -ErrorAction Stop | Out-Null
        Write-Ok "Agents halted"
        Start-Sleep -Milliseconds 700
    } catch {
        Write-Warn "Server did not answer on port $Port (it may already be down)"
    }
}

# --------------------------------------------------------------- Resolve target PID
$targetPid = $null

if (Test-Path $PidFile) {
    $recorded = (Get-Content $PidFile -Raw).Trim()
    if ($recorded -and (Get-Process -Id $recorded -ErrorAction SilentlyContinue)) {
        $targetPid = [int]$recorded
        Write-Ok "Found running server from PID file: $targetPid"
    } else {
        Write-Warn "PID file is stale, cleaning up"
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not $targetPid) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $targetPid = $conn[0].OwningProcess
        Write-Ok "Found process listening on port ${Port}: PID $targetPid"
    }
}

if (-not $targetPid) {
    Write-Host ""
    Write-Warn "Nothing to stop - no server running on port $Port."
    Write-Host ""
    exit 0
}

# --------------------------------------------------------------- Terminate
Write-Step "Stopping process $targetPid"
try {
    Stop-Process -Id $targetPid -Force -ErrorAction Stop
} catch {
    Write-Host "ERROR: could not stop PID ${targetPid}: $_" -ForegroundColor Red
    exit 1
}

# Confirm it is actually gone rather than assuming.
$stopped = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) { $stopped = $true; break }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Remove-Item $PortFile -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($stopped) {
    Write-Host "=================================================================" -ForegroundColor Green
    Write-Host " STOPPED" -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Green
} else {
    Write-Host "WARNING: process $targetPid may still be terminating." -ForegroundColor Yellow
}
Write-Host ""
