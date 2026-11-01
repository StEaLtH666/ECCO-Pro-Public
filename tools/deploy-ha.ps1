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
    [switch]$AllowDirtyWorkingTree,

    # Dashboard preservation gate, generic layer only: custom card types
    # (custom:<name>) the live dashboard uses that this deployment may
    # deliberately drop. It never waives the site policy's protected
    # layers or required resources.
    [ValidatePattern('^custom:[A-Za-z0-9][A-Za-z0-9._-]*\z')]
    [string[]]$AcceptRemovedCardType = @(),

    # Dashboard preservation gate, drift recovery: the live file differs
    # from the site policy at a protected pointer, and this candidate
    # restores the policy's protected layer exactly. Without this switch
    # that is BLOCKED (live may hold newer site values than the policy);
    # with it the gate passes with a loud warning. A candidate that does
    # not carry the protected layer is never passed.
    [switch]$AllowDriftRecovery,

    # Optional pin of the site's gate name (the site policy's "gate"): a
    # dashboard destination must then pass under exactly this gate, so a
    # host policy that was moved aside or no longer names the destination
    # cannot fall back to DASHBOARD_PRESERVE_GATE without a word. Default:
    # the git-ignored file ecco_dashboard_gate.local.txt at the repository
    # root, when it exists. DASHBOARD_PRESERVE_GATE states that this
    # deployment deliberately targets a dashboard the policy does not protect.
    [ValidatePattern('(?-i)^[A-Z][A-Z0-9_]{2,63}\z')]
    [string]$ExpectedSiteGate,

    # The Python that runs tools/ecco_dashboard_guard.py (with -I, so
    # PyYAML must be installed in that interpreter itself, not only in a
    # user site-packages folder). Default: the python on PATH.
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Import-Module (Join-Path $PSScriptRoot 'EccoDeploy.psm1') -Force

# Home Assistant's persisted Lovelace resource list. This script only ever
# READS it: the preservation gate copies it from the host, the backup copies
# it into the backup folder, and the reminder below cats it.
$lovelaceResourcesPath = '/config/.storage/lovelace_resources'
$guardPath = Join-Path $PSScriptRoot 'ecco_dashboard_guard.py'

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

# The optional gate pin: the parameter, else the local pin file. A pin file
# that exists but cannot be read stops the deployment here (never "no pin").
if ($ExpectedSiteGate) {
    $gatePin = $ExpectedSiteGate
    $gatePinSource = '-ExpectedSiteGate'
} else {
    $gatePinFile = Get-EccoDashboardGatePinPath -RepoRoot $repoRoot
    $gatePin = Get-EccoDashboardGatePin -Path $gatePinFile
    $gatePinSource = 'the local pin file ' + [System.IO.Path]::GetFileName($gatePinFile)
}
if ($gatePin) {
    Write-Host "Expected site gate: $gatePin (from $gatePinSource)"
}

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

# Dashboard preservation gate: BEFORE the first remote write (mkdir, backup,
# upload). Read-only on the host. A dashboard destination (under
# /config/ecco/dashboards/, .yaml/.yml, or named by the site policy at
# /config/ecco/site-local/dashboard-protection.json) is checked by
# tools/ecco_dashboard_guard.py: the candidate may not drop a protected
# site layer, a required resource or (unless -AcceptRemovedCardType) a
# custom card type the live dashboard uses. Anything but PASS throws here,
# so nothing on the host has changed. With a gate pin, a dashboard
# destination must have passed under the pinned gate (also a throw here).
Write-Host 'Running the dashboard preservation gate (read-only)...'
$dashboardGate = Invoke-EccoDashboardPreservationGate -SshHost $SshHost -Destination $Destination -CandidatePath $sourceFull -GuardPath $guardPath -ResourcesPath $lovelaceResourcesPath -AcceptRemovedCardType $AcceptRemovedCardType -Python $Python -AllowDriftRecovery:$AllowDriftRecovery
Write-Host $dashboardGate.GateLine
$gatePinLine = Assert-EccoDashboardGatePin -GateResult $dashboardGate -ExpectedGate $gatePin -PinSource $gatePinSource
if ($gatePinLine) {
    Write-Host $gatePinLine
}
foreach ($gateWarning in @($dashboardGate.Warnings)) {
    Write-Warning "Dashboard preservation gate: $gateWarning"
}
# The gate's only WARNING lines are a drift recovery's: the live file (and so
# the backup below) differs from the site policy at a protected pointer.
$driftRecovery = @($dashboardGate.Warnings).Count -gt 0

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
if ($dashboardGate.Applies -and (($dashboardGate.LiveState -eq 'present') -ne $hadOriginal)) {
    throw 'The destination appeared or disappeared on the host after the dashboard preservation gate read it. Nothing was written; re-run the deployment.'
}

# The source must still be the file the gate checked (the documented
# sources under dist/ are git-ignored, so the clean-tree check does not
# cover them): a re-render in between stops the deployment here, before
# anything is written. The uploaded copy is tied to the same hash below.
if ($dashboardGate.Applies) {
    $checkedSourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceFull).Hash.ToLowerInvariant()
    if (-not $dashboardGate.CandidateSha256 -or $checkedSourceHash -ne $dashboardGate.CandidateSha256) {
        throw "The source changed after the dashboard preservation gate checked it (gate $($dashboardGate.CandidateSha256), now $checkedSourceHash). Nothing was written; re-run the deployment."
    }
}

Invoke-EccoRemoteCommand -SshHost $SshHost -Command "mkdir -p '$remoteDir' '$backupDir'"
if ($hadOriginal) {
    Write-Host "Backing up current file to $backupPath"
    Invoke-EccoRemoteCommand -SshHost $SshHost -Command "cp -p '$Destination' '$backupPath'"
} else {
    Write-Host 'No existing remote file; rollback will remove the new file if validation fails.'
}

# The persisted Lovelace resource list goes into the same backup folder (a
# read of .storage; the copy is written only under $backupDir).
$resourcesBackupPath = "$backupDir/" + ($lovelaceResourcesPath.TrimStart('/') -replace '/', '__')
Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -f '$lovelaceResourcesPath' ]; then cp -p '$lovelaceResourcesPath' '$resourcesBackupPath'; fi"

# The file that was backed up must be the file the gate checked: a change on
# the host in between stops the deployment before the upload.
if ($dashboardGate.Applies -and $hadOriginal -and $dashboardGate.LiveSha256) {
    $backupHashResult = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$backupPath' | cut -d ' ' -f 1" -Capture
    $backupHash = $null
    if ($backupHashResult.ExitCode -eq 0 -and $backupHashResult.Output.Count -gt 0) {
        $backupHash = ($backupHashResult.Output[-1]).Trim().ToLowerInvariant()
    }
    if ($backupHash -ne $dashboardGate.LiveSha256) {
        throw "The live dashboard changed on the host after the dashboard preservation gate checked it (gate $($dashboardGate.LiveSha256), backup $backupHash). Nothing was uploaded; backup folder: $backupDir."
    }
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
# The uploaded bytes must be the bytes the preservation gate checked, not
# merely the local file as it is now.
if ($dashboardGate.Applies -and $remoteHash -ne $dashboardGate.CandidateSha256) {
    Invoke-EccoRemoteCommandBestEffort -SshHost $SshHost -Command "rm -f '$tempPath'"
    throw "The uploaded file is not the file the dashboard preservation gate checked (gate $($dashboardGate.CandidateSha256), uploaded $remoteHash). Nothing was installed; the backup folder is $backupDir."
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
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -DriftRecovery:$driftRecovery -Reason "The move into place failed, or its result could not be confirmed because of a possible SSH/transport failure - the destination may already have been modified. Original error: $moveFailureMessage"
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
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -DriftRecovery:$driftRecovery -Reason $reason
}
Write-Host "Post-install SHA256 verified: $postInstallHash"

# Post-install preservation check: when the site policy protects this
# destination, re-read the installed file and prove it still carries every
# protected layer (guard verify-live). A failure goes through the same
# rollback path as a failed hash or `ha core check`.
$liveVerificationLine = $null
if ($dashboardGate.PolicyNamesDestination) {
    Write-Host 'Re-reading the installed dashboard for the post-install preservation check...'
    $liveVerification = Invoke-EccoDashboardLiveVerification -SshHost $SshHost -Destination $Destination -GuardPath $guardPath -Python $Python -ExpectedGate $dashboardGate.Gate
    $liveVerification.Output | ForEach-Object { Write-Host $_ }
    if (-not $liveVerification.Passed) {
        Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -DriftRecovery:$driftRecovery -Reason 'The post-install dashboard preservation check (verify-live) did not pass: the installed file does not carry the protected site layer, or it could not be re-read.'
    }
    $liveVerificationLine = $liveVerification.GateLine
}

Write-Host 'Running Home Assistant configuration check...'
$check = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core check' -Capture
$check.Output | ForEach-Object { Write-Host $_ }

if ($check.ExitCode -ne 0) {
    Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -DriftRecovery:$driftRecovery -Reason 'Home Assistant configuration check failed after deployment.'
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
Write-Host "Dashboard   : $($dashboardGate.GateLine)"
if ($gatePinLine) {
    Write-Host $gatePinLine
}
if ($driftRecovery) {
    Write-Host "Drift       : RECOVERED - live differed from the site policy at a protected pointer and now carries the policy's layer; the drifted file is the backup $backupPath"
}
if ($liveVerificationLine) {
    Write-Host "Post-install: $liveVerificationLine (verify-live)"
}

# Every file under /config/www/ecco/ is a Lovelace resource candidate,
# whatever the source path (the documented content-addressed deploy copies
# dist/deploy/stage/<card>.<sha8>.js, which never matched $isFrontendAsset).
# Copying it changes nothing a dashboard loads until its resource points
# at it, so name the card's persisted resource from one read-only read.
# Best effort: the deployment has already passed and a failed read only
# makes the reminder say the live state is unknown. Never written.
if (Get-EccoLovelaceResourceUrl -Destination $Destination) {
    $persistedResources = $null
    $resourceReadProblem = $null
    try {
        $resourceRead = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'cat /config/.storage/lovelace_resources' -Capture
        if ($resourceRead.ExitCode -ne 0) {
            $resourceReadProblem = "ssh exit code $($resourceRead.ExitCode)"
        } else {
            $persistedResources = ConvertFrom-EccoLovelaceResources -Json ($resourceRead.Output -join "`n")
        }
    }
    catch {
        $resourceReadProblem = $_.Exception.Message
    }
    Write-Host ''
    Format-EccoResourceReminder -Destination $Destination -Resources $persistedResources -ReadProblem $resourceReadProblem | ForEach-Object { Write-Host $_ }
}
