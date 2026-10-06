[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha'
)

$ErrorActionPreference = 'Stop'
Write-Host "Checking Home Assistant via SSH alias '$SshHost'..."

$output = @(& ssh -o BatchMode=yes $SshHost 'ha core check' 2>&1)
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }

if ($code -ne 0) {
    throw "Home Assistant configuration check failed (exit $code)."
}

Write-Host 'Home Assistant configuration check PASSED'
