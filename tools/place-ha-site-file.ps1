<#
    ECCO Pro - places the owner's Intelligence site file on Home Assistant
    (PR-5).

    .\tools\place-ha-site-file.ps1 -SiteFile <path outside every repository> -ExpectedSha256 <its sha256, recorded offline>
        -SshHost <alias> -Target Test|Production [-ReplaceExistingSha256 <the live file's sha256>] [-Plan]
        [-ExpectedSiteGate <GATE>] [-SshConfigFile <file> (Test only)] [-Python <python.exe>] [-Stamp S]

    The one destination is /config/ecco/intelligence/site.local.json (the
    integration only reads it). The single-file route (deploy-ha.ps1)
    refuses everything under /config/ecco/intelligence/; this command is the
    only way the file reaches the host, and it never names the runtime state
    folder.

    Local checks before any ssh call: the file is a regular file outside every
    git working tree, at most 256 KiB, UTF-8 without a byte-order mark, a JSON
    object in strict JSON (no NaN, Infinity or -Infinity, review P1; no number
    beyond the double range, JSON order, at most 100 deep, review DRD-2: every
    file the runtime refuses is refused), and its sha256 equals
    -ExpectedSha256. Host steps:
    the /config root (amendment A26: a real folder, or a symlink that cd -P
    resolves to an existing real folder; printed, and checked unchanged
    immediately before the first write), the -Target guard, the dashboard preservation
    gate (classify) and gate pin, a symlink test of every segment below
    /config; /config/ecco/intelligence is created (one level) only when
    absent. An existing file is replaced only with
    -ReplaceExistingSha256 equal to its live sha256, after a verified backup
    to /config/ecco-backups/<stamp>/. The upload goes to a temporary file in
    the same folder, is hashed on the host, renamed into place, and read back
    by its sha256. An upload that does not arrive intact is moved into the
    backup folder (never deleted) by one command with markers, and the
    STOPPED message names only what the marker shows: moved aside (once seen
    there), absent, something else left in place, the upload left in place
    because the move's own guards refused it (review DR4R-1), or both places
    it may be when the answer is lost or the move fails (review DR3-1). A
    failure at or after the rename, a connection lost before the read-back
    included, restores the backup (or moves a first placement into the
    backup folder); the message says when that could NOT be confirmed. A
    rename that never ran leaves the upload in its temporary file, which the
    message names as left in place (never deleted); a first placement then
    reports that nothing was placed (review DR-4). The backup folder is
    created on every run, for that rollback; after a first placement that
    passes it is kept, empty, and the PLACED block says so (review L3W-6).
    Nothing is deleted, Home Assistant is not restarted or reloaded, and the
    output never shows the file's content: sizes and hashes only. -Plan sends
    read-only commands.

    Windows PowerShell 5.1 compatible. See docs/user/intelligence-deploy.md.
#>

[CmdletBinding()]
param(
    [string]$SiteFile,

    [string]$ExpectedSha256,

    [string]$SshHost,

    [ValidateSet('Test', 'Production')]
    [string]$Target,

    [string]$ReplaceExistingSha256,

    [switch]$Plan,

    [ValidatePattern('(?-i)^[A-Z][A-Z0-9_]{2,63}\z')]
    [string]$ExpectedSiteGate,

    [string]$SshConfigFile,

    [string]$Python = 'python',

    [ValidatePattern('^[0-9]{8}-[0-9]{6}\z')]
    [string]$Stamp
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Import-Module (Join-Path $PSScriptRoot 'EccoDeploy.psm1') -Force

$guardPath = Join-Path $PSScriptRoot 'ecco_dashboard_guard.py'
$intelligenceDir = '/config/ecco/intelligence'
$destination = '/config/ecco/intelligence/site.local.json'
$placeName = 'SITE_FILE'

function Stop-Placement {
    param(
        [string]$Reason,
        [ValidateSet('NothingSent', 'NothingWritten')]
        [string]$Stage = 'NothingWritten'
    )
    throw (Format-EccoKitBlockedMessage -Name $placeName -Stage $Stage -Reason $Reason)
}

function Test-Marker {
    param([object]$Result, [string]$Marker)
    return ($Result.ExitCode -eq 0) -and (@($Result.Output | Where-Object { ([string]$_).Trim() -ceq $Marker }).Count -eq 1)
}

# ---------------------------------------------------------------------------
# 1. Local checks, before any ssh call.
# ---------------------------------------------------------------------------
$Target = Assert-EccoDeployTargetParameters -SshHost $SshHost -Target $Target -SshConfigFile $SshConfigFile -RequireTarget
Set-EccoSshConfigFile -Path $SshConfigFile
$sshConfigArgs = @(Get-EccoSshConfigArguments)
if (-not $SiteFile -or -not $ExpectedSha256) {
    Stop-Placement -Stage NothingSent -Reason '-SiteFile <path> and -ExpectedSha256 <its sha256, recorded offline> are required.'
}
if ($ReplaceExistingSha256 -and $ReplaceExistingSha256 -cnotmatch '^[0-9a-f]{64}\z') {
    Stop-Placement -Stage NothingSent -Reason '-ReplaceExistingSha256 must be 64 lower-case hex digits (the sha256 of the site file now on the host).'
}

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

Assert-EccoCleanWorkingTree -RepoRoot $repoRoot
try {
    $site = Test-EccoSiteFile -Path $SiteFile -ExpectedSha256 $ExpectedSha256 -RepoRoot $repoRoot
}
catch {
    Stop-Placement -Stage NothingSent -Reason "the site file is refused: $($_.Exception.Message)"
}
Write-Host "Site file   : $($site.Size) bytes, sha256 $($site.Sha256) (its content is never printed)"

$runStamp = if ($Stamp) { $Stamp } else { (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') }
$backupDir = "/config/ecco-backups/$runStamp"
$backupPath = "$backupDir/config__ecco__intelligence__site.local.json"
$tempPath = "$destination.ecco-upload-$runStamp.tmp"

# ---------------------------------------------------------------------------
# 2. Read-only host checks.
# ---------------------------------------------------------------------------
Write-Host "Testing SSH connection to '$SshHost'..."
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & ssh -o BatchMode=yes @sshConfigArgs $SshHost 'true'
    $sshProbeCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($sshProbeCode -ne 0) {
    Stop-Placement -Reason "the SSH connection to '$SshHost' failed."
}

# /config itself, before anything else is read under it (amendment A26).
$configRoot = Get-EccoRemoteConfigRoot -SshHost $SshHost -Name $placeName
Write-Host $configRoot.Line

$targetLine = Assert-EccoDeployTarget -SshHost $SshHost -Target $Target
Write-Host $targetLine

Write-Host 'Running the dashboard preservation gate (read-only, classify)...'
$gate = Invoke-EccoNonDashboardGate -SshHost $SshHost -Destination $destination -GuardPath $guardPath -Python $Python -ExpectedGate $gatePin -PinSource $gatePinSource -RefusePolicyPrefix '/config/ecco/intelligence/' -Route 'the site-file placement'
$gateLine = "Gate        : not a dashboard destination (site policy $($gate.PolicyState))"
Write-Host $gateLine
if ($gate.PinLine) {
    Write-Host $gate.PinLine
}

# Every segment below /config (A15); /config itself is the resolved root above (A26).
$paths = @('/config/ecco', $intelligenceDir, $destination, $tempPath, '/config/ecco-backups', $backupDir)
try {
    $states = Get-EccoRemotePathStates -SshHost $SshHost -Paths $paths
}
catch {
    Stop-Placement -Reason $_.Exception.Message
}
$allowed = @{
    '/config/ecco'         = @('dir')
    '/config/ecco-backups' = @('dir', 'absent')
}
$allowed[$intelligenceDir] = @('dir', 'absent')
$allowed[$destination] = @('file', 'absent')
$allowed[$tempPath] = @('absent')
$allowed[$backupDir] = @('absent')
foreach ($p in $paths) {
    if ($allowed[$p] -notcontains $states[$p]) {
        Stop-Placement -Reason "$p is $($states[$p]) on the host (expected $($allowed[$p] -join ' or ')): no symlinked segment, and the site file must be a regular file."
    }
}

$hadOriginal = $states[$destination] -eq 'file'
$liveSha = $null
if ($hadOriginal) {
    $liveSha = Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $destination
    if (-not $liveSha) {
        Stop-Placement -Reason 'the site file on the host could not be hashed.'
    }
    if (-not $ReplaceExistingSha256) {
        Stop-Placement -Reason "a site file is already on the host (sha256 $($liveSha.Substring(0, 12))...): to replace it, pass -ReplaceExistingSha256 with its full sha256."
    }
    if ($ReplaceExistingSha256 -cne $liveSha) {
        Stop-Placement -Reason "-ReplaceExistingSha256 does not match the site file on the host (live sha256 $($liveSha.Substring(0, 12))...): it changed, or the wrong value was given."
    }
    if ($liveSha -ceq $site.Sha256) {
        Stop-Placement -Reason 'NO CHANGE: the host already holds exactly this site file; nothing to do.'
    }
} elseif ($ReplaceExistingSha256) {
    Stop-Placement -Reason '-ReplaceExistingSha256 was given, but no site file is on the host.'
}

if ($Plan) {
    Write-Host ''
    Write-Host 'ECCO SITE FILE PLAN (read-only: nothing was written)'
    Write-Host "Host        : $SshHost (-Target $Target)"
    Write-Host $targetLine
    Write-Host $configRoot.Line
    Write-Host $gateLine
    Write-Host $(if ($gate.PinLine) { $gate.PinLine } else { 'Gate pin    : none' })
    Write-Host "New file    : $($site.Size) bytes, sha256 $($site.Sha256)"
    Write-Host "On the host : $(if ($hadOriginal) { "a site file, sha256 $liveSha (replaced after a verified backup to $backupPath)" } else { 'no site file (first placement)' })"
    Write-Host "Backup      : $(if ($hadOriginal) { "$backupPath (a verified copy of the file on the host)" } else { "none (first placement); $backupDir is created for a rollback and kept, empty when the placement passes" })"
    Write-Host "Folder      : $intelligenceDir $(if ($states[$intelligenceDir] -eq 'absent') { '(created, one level)' } else { '(exists)' })"
    Write-Host "Upload      : $tempPath, hashed on the host, then renamed to $destination and read back"
    Write-Host 'Never named : the runtime state folder /config/ecco/intelligence/state/'
    Write-Host 'Takes effect: only at a config-entry reload or a restart, each separately gated; neither is performed'
    return
}

# ---------------------------------------------------------------------------
# 3. Writes.
# ---------------------------------------------------------------------------
# The /config root is unchanged since the read-only checks (A26), and the
# folder-creating command tests it again itself.
Assert-EccoRemoteConfigRootUnchanged -SshHost $SshHost -ConfigRoot $configRoot.Resolved -Name $placeName
$mkdir = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoSafeMkdirCommand -ConfigRoot $configRoot.Resolved -MustExist @('/config/ecco') -MayCreate @($intelligenceDir, '/config/ecco-backups') -MustCreate @($backupDir)) -Capture
if (-not (Test-Marker -Result $mkdir -Marker 'ECCO_MKDIR_OK')) {
    throw "SITE_FILE: STOPPED - the folders could not be created safely (/config no longer resolving to $($configRoot.Resolved), a symlinked segment, a stamp already used, or no permission; ssh exit code $($mkdir.ExitCode)). The site file on the host was not changed."
}

if ($hadOriginal) {
    $copy = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -f '$destination' ] && [ ! -L '$destination' ] && [ ! -e '$backupPath' ] && cp -p '$destination' '$backupPath' && echo ECCO_SITE_BACKED_UP" -Capture
    if (-not (Test-Marker -Result $copy -Marker 'ECCO_SITE_BACKED_UP') -or (Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $backupPath) -cne $liveSha) {
        throw "SITE_FILE: STOPPED - the backup to $backupPath could not be made or verified. The site file on the host was not changed."
    }
    Write-Host "Backup verified: $backupPath (sha256 $($liveSha.Substring(0, 12))...)"
}

Write-Host "Uploading the site file to $tempPath..."
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & scp -q @sshConfigArgs $site.FullPath ('{0}:{1}' -f $SshHost, $tempPath)
    $scpCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
$uploadedSha = if ($scpCode -eq 0) { Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $tempPath } else { $null }
if ($uploadedSha -cne $site.Sha256) {
    # The rejected upload is moved into the backup folder, never deleted, by one command with markers; the message names
    # only what the marker shows (review DR3-1, amendment A40).
    $uploadLine = Move-EccoRejectedSiteUpload -SshHost $SshHost -TempPath $tempPath -BackupDir $backupDir
    throw "SITE_FILE: STOPPED - the upload did not arrive intact (scp exit code $scpCode; sha256 on the host $(if ($uploadedSha) { $uploadedSha.Substring(0, 12) } else { 'unknown' })). The site file on the host was not changed.`n$uploadLine"
}

$move = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -f '$tempPath' ] && [ ! -L '$tempPath' ] && [ ! -L '$destination' ] && [ ! -d '$destination' ] && mv -f '$tempPath' '$destination' && echo ECCO_SITE_PLACED" -Capture
if (-not (Test-Marker -Result $move -Marker 'ECCO_SITE_PLACED')) {
    Invoke-EccoSiteFileRollback -SshHost $SshHost -HadOriginal $hadOriginal -OriginalSha256 $liveSha -BackupDir $backupDir -TempPath $tempPath -Reason "the rename into place failed, or its result could not be confirmed (ssh exit code $($move.ExitCode))."
}
# The read-back. A transport failure here (ssh dropped right after the
# rename) leaves the host state unknown: the new file may already be in
# place. It goes through the same rollback as a mismatch, whose message
# says "was rolled back" only when the restore was verified.
$readBackProblem = $null
try {
    $after = Get-EccoRemotePathStates -SshHost $SshHost -Paths @($destination)
    $readBack = Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $destination
}
catch {
    $readBackProblem = $_.Exception.Message
}
if ($readBackProblem) {
    Invoke-EccoSiteFileRollback -SshHost $SshHost -HadOriginal $hadOriginal -OriginalSha256 $liveSha -BackupDir $backupDir -TempPath $tempPath -Reason "the read-back after the rename failed: $readBackProblem This may be an ssh/transport failure: the host may already hold the new site file, which was never read back."
}
if ($after[$destination] -ne 'file' -or $readBack -cne $site.Sha256) {
    $mismatch = if ($after[$destination] -ne 'file') {
        "the placed site file is $($after[$destination]) on the host after the rename, not a regular file."
    } elseif (-not $readBack) {
        'the placed site file could not be hashed on the host: a possible ssh/transport failure, so the host may already hold the new site file, which was never read back.'
    } else {
        'the read-back of the placed site file does not match its sha256.'
    }
    Invoke-EccoSiteFileRollback -SshHost $SshHost -HadOriginal $hadOriginal -OriginalSha256 $liveSha -BackupDir $backupDir -TempPath $tempPath -Reason $mismatch
}

Write-Host ''
Write-Host 'ECCO SITE FILE PLACED'
Write-Host "Host        : $SshHost (-Target $Target)"
Write-Host $targetLine
Write-Host $configRoot.Line
Write-Host "Destination : $destination"
Write-Host "Read back   : sha256 $readBack ($($site.Size) bytes) - matches -ExpectedSha256"
# A first placement backs nothing up, but this run created its backup folder (for a rollback): it is named as kept and
# empty, never left unmentioned beside "none" (review L3W-6, amendment A49).
Write-Host "Backup      : $(if ($hadOriginal) { "$backupPath (the previous file, sha256 $liveSha)" } else { "none (first placement); $backupDir was created for a rollback and is kept, empty" })"
Write-Host $gateLine
if ($gate.PinLine) {
    Write-Host $gate.PinLine
}
Write-Host 'Takes effect: only at a config-entry reload or a restart, each separately gated; neither was performed.'
