[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha'
)

$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$local = Join-Path $env:TEMP "ecco-ssh-smoke-$stamp.txt"
$remote = "/config/ecco-ssh-smoke-$stamp.txt"
$payload = "ECCO SSH deployment smoke test $stamp"

try {
    Set-Content -Path $local -Value $payload -Encoding ascii -NoNewline

    Write-Host "[1/4] SSH: $SshHost"
    & ssh -o BatchMode=yes $SshHost 'ha core info >/dev/null'
    if ($LASTEXITCODE -ne 0) {
        throw 'SSH/HA CLI check failed.'
    }

    Write-Host '[2/4] SCP/SFTP upload'
    & scp -q $local ("{0}:{1}" -f $SshHost, $remote)
    if ($LASTEXITCODE -ne 0) {
        throw 'SCP/SFTP upload failed.'
    }

    Write-Host '[3/4] SHA256 verification'
    $localHash = (Get-FileHash -Algorithm SHA256 -Path $local).Hash.ToLowerInvariant()
    $remoteHashLines = @(& ssh -o BatchMode=yes $SshHost "sha256sum '$remote' | cut -d ' ' -f 1" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $remoteHashLines.Count -eq 0) {
        throw 'Remote SHA256 check failed.'
    }
    $remoteHash = ($remoteHashLines[-1]).Trim().ToLowerInvariant()
    if ($localHash -ne $remoteHash) {
        throw "SHA256 mismatch. Local=$localHash Remote=$remoteHash"
    }

    Write-Host '[4/4] Remove remote test file'
    & ssh -o BatchMode=yes $SshHost "rm -f '$remote'"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to remove remote smoke-test file: $remote"
    }

    Write-Host 'ECCO SSH/SFTP smoke test PASSED'
}
finally {
    Remove-Item -Path $local -Force -ErrorAction SilentlyContinue
}
