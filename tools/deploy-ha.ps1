[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Source,

    [string]$Destination,

    [string]$SshHost = 'ecco-ha',

    [switch]$Restart,

    [switch]$SkipValidation,

    # Deliberately named so an uncommitted deployment can never happen by
    # accident. Normal deployments must come from a clean git working tree
    # so the file on Home Assistant always matches a committed revision.
    [switch]$AllowDirtyWorkingTree
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Import-Module (Join-Path $PSScriptRoot 'EccoDeploy.psm1') -Force

$sourceCandidate = if ([System.IO.Path]::IsPathRooted($Source)) {
    $Source
} else {
    Join-Path $repoRoot $Source
}

$sourceFull = (Resolve-Path $sourceCandidate).Path
$repoPrefix = $repoRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
if (-not $sourceFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Source must be a file inside the ECCO-Pro repository.'
}

$relative = $sourceFull.Substring($repoPrefix.Length).Replace('\', '/')

# A committed frontend dist asset - e.g.
# frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js -
# defaults to /config/www/ecco/<filename>, served back to the browser as
# /local/ecco/<filename> once the resource is registered (manually - see
# the printed reminder below). Matches ANY card directory under frontend/,
# not just the two that exist today.
$isFrontendAsset = $relative -match '(?i)^frontend/[^/]+/dist/[^/]+$'

if (-not $Destination) {
    if ($relative.StartsWith('home-assistant/packages/', [System.StringComparison]::OrdinalIgnoreCase)) {
        $Destination = '/config/packages/' + [System.IO.Path]::GetFileName($sourceFull)
    } elseif ($relative.StartsWith('home-assistant/dashboards/', [System.StringComparison]::OrdinalIgnoreCase)) {
        $Destination = '/config/ecco/dashboards/' + [System.IO.Path]::GetFileName($sourceFull)
    } elseif ($isFrontendAsset) {
        $Destination = '/config/www/ecco/' + [System.IO.Path]::GetFileName($sourceFull)
    } else {
        throw 'Destination is required for files outside home-assistant/packages, home-assistant/dashboards, or frontend/<card>/dist.'
    }
}

$Destination = Test-EccoDeploymentDestination -Destination $Destination

if ($AllowDirtyWorkingTree) {
    Write-Warning 'Deploying with -AllowDirtyWorkingTree: the working tree may not match any committed revision.'
} else {
    Assert-EccoCleanWorkingTree -RepoRoot $repoRoot
}

if (-not $SkipValidation) {
    Write-Host 'Running repository validation before deployment...'
    & (Join-Path $PSScriptRoot 'validate-ecco.ps1')
}

Write-Host "Testing SSH connection to '$SshHost'..."
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & ssh -o BatchMode=yes $SshHost 'true'
    $sshProbeCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($sshProbeCode -ne 0) {
    throw "SSH connection to '$SshHost' failed."
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$lastSlash = $Destination.LastIndexOf('/')
if ($lastSlash -lt 1) {
    throw "Invalid remote destination: $Destination"
}
$remoteDir = $Destination.Substring(0, $lastSlash)
$backupDir = "/config/ecco-backups/$stamp"
$backupName = ($Destination.TrimStart('/') -replace '/', '__')
$backupPath = "$backupDir/$backupName"
$tempPath = "$Destination.ecco-upload-$stamp.tmp"

$probe = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -f '$Destination' ]; then printf yes; else printf no; fi" -Capture
if ($probe.ExitCode -ne 0) {
    throw 'Unable to inspect existing remote file.'
}
$probeText = ($probe.Output -join '').Trim()
$hadOriginal = $probeText.EndsWith('yes')

Invoke-EccoRemoteCommand -SshHost $SshHost -Command "mkdir -p '$remoteDir' '$backupDir'"
if ($hadOriginal) {
    Write-Host "Backing up current file to $backupPath"
    Invoke-EccoRemoteCommand -SshHost $SshHost -Command "cp -p '$Destination' '$backupPath'"
} else {
    Write-Host 'No existing remote file; rollback will remove the new file if validation fails.'
}

Write-Host "Uploading $relative -> $Destination"
$remoteSpec = '{0}:{1}' -f $SshHost, $tempPath
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & scp -q $sourceFull $remoteSpec
    $scpCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($scpCode -ne 0) {
    Invoke-EccoRemoteCommandBestEffort -SshHost $SshHost -Command "rm -f '$tempPath'"
    throw 'SCP upload failed.'
}

$localHash = (Get-FileHash -Algorithm SHA256 -Path $sourceFull).Hash.ToLowerInvariant()
$hashResult = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$tempPath' | cut -d ' ' -f 1" -Capture
if ($hashResult.ExitCode -ne 0 -or $hashResult.Output.Count -eq 0) {
    Invoke-EccoRemoteCommandBestEffort -SshHost $SshHost -Command "rm -f '$tempPath'"
    throw 'Unable to calculate remote SHA256.'
}
$remoteHash = ($hashResult.Output[-1]).Trim().ToLowerInvariant()

if ($localHash -ne $remoteHash) {
    Invoke-EccoRemoteCommandBestEffort -SshHost $SshHost -Command "rm -f '$tempPath'"
    throw "SHA256 mismatch. Local=$localHash Remote=$remoteHash"
}
Write-Host "Upload SHA256 verified: $localHash"

# A failure here is ambiguous: SSH could have dropped after the remote
# `mv` already completed, so $Destination may already contain the new
# file even though this command reports failure. Never treat that as
# "nothing happened" - clean up the temp path best-effort, then always
# run it through the same rollback path used for a failed post-install
# hash or a failed `ha core check`, so it can never reach either of
# those or a restart while the destination's real state is unknown.
try {
    Invoke-EccoRemoteCommand -SshHost $SshHost -Command "mv -f '$tempPath' '$Destination'"
}
catch {
    $moveFailureMessage = $_.Exception.Message
    Invoke-EccoRemoteCommandBestEffort -SshHost $SshHost -Command "rm -f '$tempPath'"
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Reason "The move into place failed, or its result could not be confirmed because of a possible SSH/transport failure - the destination may already have been modified. Original error: $moveFailureMessage"
}

# Post-install verification: hash the file that actually landed at
# $Destination, immediately after the move and before anything else runs.
# A failure here must never proceed to `ha core check` or a restart - it
# goes straight through the same rollback path as a failed config check.
$postHashResult = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$Destination' | cut -d ' ' -f 1" -Capture
$postInstallHash = $null
if ($postHashResult.ExitCode -eq 0 -and $postHashResult.Output.Count -gt 0) {
    $postInstallHash = ($postHashResult.Output[-1]).Trim().ToLowerInvariant()
}

if (-not $postInstallHash -or $postInstallHash -ne $localHash) {
    $reason = if (-not $postInstallHash) {
        'Unable to calculate the post-install SHA256 of the deployed file.'
    } else {
        "Post-install SHA256 mismatch. Local=$localHash Installed=$postInstallHash"
    }
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Reason $reason
}
Write-Host "Post-install SHA256 verified: $postInstallHash"

Write-Host 'Running Home Assistant configuration check...'
$check = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core check' -Capture
$check.Output | ForEach-Object { Write-Host $_ }

if ($check.ExitCode -ne 0) {
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Reason 'Home Assistant configuration check failed after deployment.'
}

if ($Restart) {
    Write-Host 'Configuration check passed. Restart requested explicitly.'
    Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core restart'
} else {
    Write-Host 'Configuration check passed. Home Assistant was NOT restarted.'
}

Write-Host ''
Write-Host 'ECCO DEPLOYMENT PASSED'
Write-Host "Source      : $relative"
Write-Host "Destination : $Destination"
Write-Host "Backup      : $(if ($hadOriginal) { $backupPath } else { 'none (new file)' })"
Write-Host "Restart     : $(if ($Restart) { 'requested' } else { 'no' })"

if ($isFrontendAsset) {
    $resourceUrl = '/local/ecco/' + [System.IO.Path]::GetFileName($sourceFull)
    Write-Host ''
    Write-Host "Resource URL: $resourceUrl"
    Write-Host 'Resource registration is manual: Settings -> Dashboards -> Resources.'
    Write-Host 'This script never edits Home Assistant .storage - no resource was registered automatically.'
}
