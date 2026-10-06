<#
Launches tools/ecco-flight-recorder.ps1 as a DETACHED background process so
the recording survives the launching shell/session exiting - unlike a
PowerShell Start-Job, which does not survive the parent process ending.

Read-only: this only changes how the existing read-only recorder is
launched. It performs no Home Assistant writes and no Modbus writes itself.

Ownership is tracked with a PID lock file
(<OutputDirectory>/.recorder.lock.json) so a second start attempt fails
clearly instead of racing a second recorder against the first, and so the
paired ecco-flight-recorder-stop.ps1 knows exactly which process to stop.

Usage:
  pwsh tools/ecco-flight-recorder-start.ps1
  pwsh tools/ecco-flight-recorder-start.ps1 -SshHost ecco-ha -IntervalSeconds 2

Stop with tools/ecco-flight-recorder-stop.ps1 (do not use Stop-Process /
Task Manager directly - the stop script verifies it is killing the right
process before doing so).
#>

[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha',
    [double]$IntervalSeconds = 2.0,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'flight-recordings')
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$lockPath = Join-Path $OutputDirectory '.recorder.lock.json'

function Get-EccoRecorderCommandLine([int]$ProcessId) {
    # Used to confirm a PID actually is an ecco-flight-recorder.ps1 process
    # before trusting (or killing) it - PIDs get reused by Windows, so the
    # lock file's PID alone is not sufficient proof of identity.
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $null }
    return [string]$proc.CommandLine
}

if (Test-Path -LiteralPath $lockPath) {
    $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    $existing = Get-Process -Id $lock.Pid -ErrorAction SilentlyContinue
    if ($existing) {
        $cmdLine = Get-EccoRecorderCommandLine -ProcessId $lock.Pid
        if ($cmdLine -match 'ecco-flight-recorder\.ps1') {
            throw "A flight recorder is already running (PID $($lock.Pid), CSV $($lock.CsvPath)). Stop it first with tools\ecco-flight-recorder-stop.ps1, or use a different -OutputDirectory."
        }
    }
    Write-Warning "Stale lock file at $lockPath (PID $($lock.Pid) is not a running recorder). Removing it."
    Remove-Item -LiteralPath $lockPath -Force
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$csvPath = Join-Path $OutputDirectory "ecco-flight-$stamp.csv"
$stdoutLog = Join-Path $OutputDirectory "ecco-flight-$stamp.stdout.log"
$stderrLog = Join-Path $OutputDirectory "ecco-flight-$stamp.stderr.log"
$recorderScript = Join-Path $PSScriptRoot 'ecco-flight-recorder.ps1'

if (-not (Test-Path -LiteralPath $recorderScript)) {
    throw "Recorder script not found: $recorderScript"
}

# A single pre-quoted command-line string, not an array, is passed to
# -ArgumentList: Windows PowerShell 5.1's array-to-ArgumentList conversion
# was observed (2026-09-26) to occasionally drop $PSScriptRoot resolution
# in the child process, which broke this script's own -OutputDirectory
# default. An explicit string sidesteps that.
$intervalArg = $IntervalSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
$argString = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -SshHost "{1}" -IntervalSeconds {2} -CsvPath "{3}" -OutputDirectory "{4}"' -f `
    $recorderScript, $SshHost, $intervalArg, $csvPath, $OutputDirectory

$proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $argString `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

Start-Sleep -Milliseconds 1000
$alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
if (-not $alive) {
    $errText = if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Raw } else { '(no stderr log)' }
    throw "Recorder process (PID $($proc.Id)) exited immediately. stderr:`n$errText"
}

$lockData = [pscustomobject]@{
    Pid             = $proc.Id
    CsvPath         = $csvPath
    StdoutLog       = $stdoutLog
    StderrLog       = $stderrLog
    SshHost         = $SshHost
    IntervalSeconds = $IntervalSeconds
    StartedAt       = (Get-Date).ToString('o')
}
# Set-Content -Encoding utf8 writes a UTF-8 BOM in Windows PowerShell 5.1,
# which tools/validate_repo.py's plain json.load() (no utf-8-sig) rejects.
# Written via .NET directly to avoid the BOM instead.
$lockJson = $lockData | ConvertTo-Json
[System.IO.File]::WriteAllText($lockPath, $lockJson, (New-Object System.Text.UTF8Encoding($false)))

Write-Host 'ECCO flight recorder started (detached - survives this shell exiting).'
Write-Host "  PID         : $($proc.Id)"
Write-Host "  CSV         : $csvPath"
Write-Host "  Lock file   : $lockPath"
Write-Host "  Stdout log  : $stdoutLog"
Write-Host "  Stop with   : tools\ecco-flight-recorder-stop.ps1"
