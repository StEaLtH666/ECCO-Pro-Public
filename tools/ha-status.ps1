[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha'
)

$ErrorActionPreference = 'Stop'
Write-Host "Home Assistant status via '$SshHost'"

& ssh -o BatchMode=yes $SshHost 'ha core info'
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to read Home Assistant core status.'
}
