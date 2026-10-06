[CmdletBinding()]
param(
    [ValidateRange(10, 2000)]
    [int]$Lines = 150,
    [string]$Pattern,
    [string]$SshHost = 'ecco-ha'
)

$ErrorActionPreference = 'Stop'
$remoteCommand = "ha core logs | tail -n $Lines"
$logs = @(& ssh -o BatchMode=yes $SshHost $remoteCommand 2>&1)
$code = $LASTEXITCODE

if ($code -ne 0) {
    $logs | ForEach-Object { Write-Host $_ }
    throw "Unable to read Home Assistant logs (exit $code)."
}

if ($Pattern) {
    $matches = @($logs | Select-String -SimpleMatch -Pattern $Pattern)
    if ($matches.Count -eq 0) {
        Write-Host "No matches for '$Pattern' in the last $Lines log lines."
    } else {
        $matches | ForEach-Object { Write-Host $_.Line }
    }
} else {
    $logs | ForEach-Object { Write-Host $_ }
}
