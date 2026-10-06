<#
Stops a flight recorder previously started with
tools/ecco-flight-recorder-start.ps1, using its PID lock file
(<OutputDirectory>/.recorder.lock.json).

Safety: this NEVER does a blind Stop-Process by name (which could kill an
unrelated powershell.exe belonging to the user or to this session). It only
stops the exact PID recorded in the lock file, and only after confirming
that process's command line still names ecco-flight-recorder.ps1 - Windows
reuses PIDs, so the lock file's PID alone is not sufficient proof of
identity.

Usage:
  pwsh tools/ecco-flight-recorder-stop.ps1
#>

[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'flight-recordings')
)

$ErrorActionPreference = 'Stop'
$lockPath = Join-Path $OutputDirectory '.recorder.lock.json'

if (-not (Test-Path -LiteralPath $lockPath)) {
    throw "No recorder lock file at $lockPath - nothing to stop (it may already have been stopped, or was never started with ecco-flight-recorder-start.ps1)."
}

$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json

$proc = Get-Process -Id $lock.Pid -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Warning "Recorder PID $($lock.Pid) is not running (already stopped or crashed). Removing stale lock file."
    Remove-Item -LiteralPath $lockPath -Force
    Write-Host "Last known CSV: $($lock.CsvPath)"
    return
}

$cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($lock.Pid)" -ErrorAction SilentlyContinue).CommandLine
if ($cmdLine -notmatch 'ecco-flight-recorder\.ps1') {
    throw "Refusing to stop PID $($lock.Pid): its command line does not look like the ECCO flight recorder (got: '$cmdLine'). The lock file may be stale, or this PID was reused by an unrelated process. Nothing was stopped - investigate manually."
}

Stop-Process -Id $lock.Pid -Force
Start-Sleep -Milliseconds 500
$stillAlive = Get-Process -Id $lock.Pid -ErrorAction SilentlyContinue
if ($stillAlive) {
    throw "PID $($lock.Pid) did not stop."
}

Remove-Item -LiteralPath $lockPath -Force

$lineCount = 0
if (Test-Path -LiteralPath $lock.CsvPath) {
    $lineCount = (Get-Content -LiteralPath $lock.CsvPath | Measure-Object -Line).Lines
}

Write-Host 'ECCO flight recorder stopped.'
Write-Host "  PID     : $($lock.Pid)"
Write-Host "  CSV     : $($lock.CsvPath)"
Write-Host "  Lines   : $lineCount (including header; samples = lines - 1)"
