<#
    ECCO Pro - the deploy route for the ECCO Intelligence integration kit
    (PR-5).

    .\tools\deploy-ha-kit.ps1 -Action Plan|Install|Upgrade -SshHost <alias> -Target Test|Production
        -Kit <kit folder> -ExpectedSumsSha256 <sha256 of its SHA256SUMS> -ExpectedHaVersion <version>
        [-ReferenceKit <the L3-tested kit> -ReferenceSumsSha256 <its SHA256SUMS sha256>]   (required with Production)
    .\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp <YYYYMMDD-HHMMSS> -SshHost <alias> -Target ... -ExpectedHaVersion ...
    .\tools\deploy-ha-kit.ps1 -Action Uninstall -SshHost <alias> -Target ... -ExpectedHaVersion ...
    Common: [-ExpectedSiteGate <GATE>] [-SshConfigFile <file> (Test only)] [-SkipValidation] [-Python <python.exe>] [-Stamp S]

    The one destination is /config/custom_components/ecco_intelligence. The
    only files ever written there are the exact files of a kit whose
    SHA256SUMS verified locally (or of a verified backup): the allowlist.
    Staging is /config/ecco/staging/<stamp>/ (never inside custom_components),
    backups /config/ecco-backups/<stamp>/. Nothing is ever deleted: a
    replaced, failed or uninstalled tree is moved under the staging folder.
    Home Assistant is never restarted (no -Restart): the restart that loads
    the integration is separately gated. Plan sends read-only commands only.

    Local checks before any ssh call: the -Target guard's local half, a clean
    working tree, validate-ecco with this -Python (unless -SkipValidation),
    and for a kit: Test-EccoKitManifest, git_sha = this checkout's HEAD, a byte-identical
    rebuild with tools/build_ha_integration.py, and kit equivalence to the
    L3-tested kit (amendment A3; required with -Target Production).
    Read-only host checks before the first write: the ssh probe, the
    /config root (amendment A26: a real folder, or a symlink that cd -P
    resolves to an existing real folder; printed, and checked unchanged
    immediately before the first write), the -Target guard (marker,
    loopback, machine), the dashboard preservation gate (classify) and gate
    pin, /config/.HA_VERSION, a symlink test of every path segment below
    /config, one device for custom_components and ecco/, free space, the
    installed tree (no symlink, only safe names), the protected site file
    and state snapshot, and the config-entry count.

    Windows PowerShell 5.1 compatible. See docs/user/intelligence-deploy.md.
#>

[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Install', 'Upgrade', 'Rollback', 'Uninstall')]
    [string]$Action,

    # No default: the host is always named.
    [string]$SshHost,

    # Which Home Assistant this run is for; always required here.
    [ValidateSet('Test', 'Production')]
    [string]$Target,

    # The content of /config/.HA_VERSION the run expects (a wrong host stops).
    [string]$ExpectedHaVersion,

    [string]$Kit,

    [string]$ExpectedSumsSha256,

    # The L3-tested kit (its SHA256SUMS and VENDOR_MANIFEST.json suffice) and
    # the sha256 of its SHA256SUMS recorded from the L3 run.
    [string]$ReferenceKit,

    [string]$ReferenceSumsSha256,

    # Rollback: the stamp of a verified kit backup under /config/ecco-backups/.
    [string]$BackupStamp,

    # The optional gate pin, as in deploy-ha.ps1 (default: the git-ignored
    # ecco_dashboard_gate.local.txt at the repository root). With a site gate
    # pinned and the host policy moved aside, pass DASHBOARD_PRESERVE_GATE for
    # this run only.
    [ValidatePattern('(?-i)^[A-Z][A-Z0-9_]{2,63}\z')]
    [string]$ExpectedSiteGate,

    # A harness-owned ssh configuration (ssh -F), -Target Test only.
    [string]$SshConfigFile,

    [switch]$SkipValidation,

    # The Python for the gate's guard (PyYAML), the kit rebuild and the
    # repository validator (validate-ecco.ps1 -Python).
    [string]$Python = 'python',

    # The run's stamp (UTC YYYYMMDD-HHMMSS); default: now.
    [ValidatePattern('^[0-9]{8}-[0-9]{6}\z')]
    [string]$Stamp
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Import-Module (Join-Path $PSScriptRoot 'EccoDeploy.psm1') -Force

$guardPath = Join-Path $PSScriptRoot 'ecco_dashboard_guard.py'
$installPath = '/config/custom_components/ecco_intelligence'
# Home Assistant's config-entry store: only the count of lines naming ecco_intelligence is read (Uninstall needs 0).
$configEntriesPath = '/config/.storage/core.config_entries'
$kitName = 'INTELLIGENCE_KIT'

function Stop-KitRun {
    param(
        [string]$Reason,
        [ValidateSet('NothingSent', 'NothingWritten')]
        [string]$Stage = 'NothingWritten'
    )
    throw (Format-EccoKitBlockedMessage -Name $kitName -Stage $Stage -Reason $Reason)
}

# ---------------------------------------------------------------------------
# 1. Local checks, before any ssh call.
# ---------------------------------------------------------------------------
if (-not $Action) {
    Stop-KitRun -Stage NothingSent -Reason '-Action Plan|Install|Upgrade|Rollback|Uninstall is required.'
}
$Target = Assert-EccoDeployTargetParameters -SshHost $SshHost -Target $Target -SshConfigFile $SshConfigFile -RequireTarget
Set-EccoSshConfigFile -Path $SshConfigFile
$sshConfigArgs = @(Get-EccoSshConfigArguments)
if ($ExpectedHaVersion -cnotmatch '^[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,3}[A-Za-z0-9.]*\z') {
    Stop-KitRun -Stage NothingSent -Reason '-ExpectedHaVersion <version> is required (the content of /config/.HA_VERSION, for example 2030.1.0).'
}
$usesKit = @('Plan', 'Install', 'Upgrade') -contains $Action
if ($usesKit) {
    if (-not $Kit -or -not $ExpectedSumsSha256) {
        Stop-KitRun -Stage NothingSent -Reason "-Action $Action needs -Kit <kit folder> and -ExpectedSumsSha256 <the sha256 of its SHA256SUMS, recorded offline>."
    }
    if ($BackupStamp) {
        Stop-KitRun -Stage NothingSent -Reason '-BackupStamp belongs to -Action Rollback only.'
    }
    if ([bool]$ReferenceKit -ne [bool]$ReferenceSumsSha256) {
        Stop-KitRun -Stage NothingSent -Reason '-ReferenceKit and -ReferenceSumsSha256 go together.'
    }
    if ($Target -eq 'Production' -and -not $ReferenceKit) {
        Stop-KitRun -Stage NothingSent -Reason '-Target Production needs -ReferenceKit <the L3-tested kit> and -ReferenceSumsSha256 <its recorded SHA256SUMS sha256>: production gets only a kit equivalent to the one that passed L3 (amendment A3).'
    }
} else {
    if ($Kit -or $ExpectedSumsSha256 -or $ReferenceKit -or $ReferenceSumsSha256) {
        Stop-KitRun -Stage NothingSent -Reason "-Action $Action takes no kit."
    }
    if ($Action -eq 'Rollback' -and $BackupStamp -cnotmatch '^[0-9]{8}-[0-9]{6}\z') {
        Stop-KitRun -Stage NothingSent -Reason '-Action Rollback needs -BackupStamp YYYYMMDD-HHMMSS: a folder under /config/ecco-backups/ that holds a verified kit backup (printed by Upgrade).'
    }
    if ($Action -eq 'Uninstall' -and $BackupStamp) {
        Stop-KitRun -Stage NothingSent -Reason '-BackupStamp belongs to -Action Rollback only.'
    }
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
if (-not $SkipValidation) {
    Write-Host 'Running repository validation before deployment...'
    # The same -Python as the guard and the rebuild, never a silent fall back to the python on PATH (review L3W-5).
    & (Join-Path $PSScriptRoot 'validate-ecco.ps1') -Python $Python
}

$kitInfo = $null
$equivalenceLine = 'Equivalence : not checked (no -ReferenceKit; required only with -Target Production)'
$rebuildLine = ''
if ($usesKit) {
    try {
        $kitInfo = Test-EccoKitManifest -Kit $Kit -ExpectedSumsSha256 $ExpectedSumsSha256
        $head = Assert-EccoKitGitSha -KitInfo $kitInfo -RepoRoot $repoRoot
        $rebuildLine = Invoke-EccoKitRebuildCheck -RepoRoot $repoRoot -Python $Python -KitInfo $kitInfo
        if ($ReferenceKit) {
            $equivalenceLine = (Test-EccoKitEquivalence -KitInfo $kitInfo -ReferenceKit $ReferenceKit -ReferenceSumsSha256 $ReferenceSumsSha256).Line
        }
    }
    catch {
        Stop-KitRun -Stage NothingSent -Reason "the kit does not verify: $($_.Exception.Message)"
    }
    Write-Host "Kit verified: SHA256SUMS $($kitInfo.SumsSha256), $(@($kitInfo.PackageFiles.Keys).Count) files, git_sha $head = HEAD, $rebuildLine"
    Write-Host $equivalenceLine
}

$runStamp = if ($Stamp) { $Stamp } else { (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') }
if ($Action -eq 'Rollback' -and $BackupStamp -ceq $runStamp) {
    Stop-KitRun -Stage NothingSent -Reason "the run stamp $runStamp equals -BackupStamp: use another -Stamp."
}

# ---------------------------------------------------------------------------
# 2. Read-only host checks, before the first remote write.
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
    Stop-KitRun -Reason "the SSH connection to '$SshHost' failed."
}

# /config itself, before anything else is read under it (amendment A26).
$configRoot = Get-EccoRemoteConfigRoot -SshHost $SshHost -Name $kitName
Write-Host $configRoot.Line

$targetLine = Assert-EccoDeployTarget -SshHost $SshHost -Target $Target
Write-Host $targetLine

Write-Host 'Running the dashboard preservation gate (read-only, classify)...'
$gate = Invoke-EccoNonDashboardGate -SshHost $SshHost -Destination "$installPath/manifest.json" -GuardPath $guardPath -Python $Python -ExpectedGate $gatePin -PinSource $gatePinSource -RefusePolicyPrefix '/config/custom_components/' -Route 'the Intelligence kit route'
$gateLine = "Gate        : not a dashboard destination (site policy $($gate.PolicyState))"
Write-Host $gateLine
if ($gate.PinLine) {
    Write-Host $gate.PinLine
}

$versionRead = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "cat '/config/.HA_VERSION'" -Capture
$haVersion = if ($versionRead.ExitCode -eq 0) { ((@($versionRead.Output) -join '').Trim()) } else { '' }
if ($haVersion -cne $ExpectedHaVersion) {
    Stop-KitRun -Reason "the host runs Home Assistant '$haVersion' (/config/.HA_VERSION), not the expected '$ExpectedHaVersion'."
}

# Every segment below /config (A15); /config itself is the resolved root above (A26).
$paths = @('/config/custom_components', $installPath, '/config/ecco', '/config/ecco/staging', '/config/ecco-backups')
$backupRoot = ''
if ($Action -eq 'Rollback') {
    $backupRoot = "/config/ecco-backups/$BackupStamp"
    $paths += @($backupRoot, "$backupRoot/custom_components__ecco_intelligence", "$backupRoot/BACKUP_SHA256SUMS")
}
try {
    $states = Get-EccoRemotePathStates -SshHost $SshHost -Paths $paths
}
catch {
    Stop-KitRun -Reason $_.Exception.Message
}
$allowed = @{
    '/config/custom_components' = @('dir')
    '/config/ecco'              = @('dir')
    '/config/ecco/staging'      = @('dir', 'absent')
    '/config/ecco-backups'      = @('dir', 'absent')
}
$allowed[$installPath] = @('dir', 'absent')
if ($backupRoot) {
    $allowed[$backupRoot] = @('dir')
    $allowed["$backupRoot/custom_components__ecco_intelligence"] = @('dir')
    $allowed["$backupRoot/BACKUP_SHA256SUMS"] = @('file')
}
foreach ($p in $paths) {
    if ($allowed[$p] -notcontains $states[$p]) {
        Stop-KitRun -Reason "$p is $($states[$p]) on the host (expected $($allowed[$p] -join ' or ')): every segment the route writes below must be a real folder, never a symlink."
    }
}

try {
    $fs = Get-EccoRemoteFsFacts -SshHost $SshHost
}
catch {
    Stop-KitRun -Reason $_.Exception.Message
}
if (-not $fs.SameDevice) {
    Stop-KitRun -Reason '/config/custom_components and /config/ecco are on different devices: the swap would not be an atomic rename.'
}
$kitBytes = if ($kitInfo) { $kitInfo.Bytes } else { 0 }
$needKiB = [long][Math]::Ceiling(4 * $kitBytes / 1024) + 16384
if ($fs.AvailableKiB -lt $needKiB) {
    Stop-KitRun -Reason "only $($fs.AvailableKiB) KiB are free under /config; the run needs at least $needKiB KiB."
}

try {
    $installed = Get-EccoKitRemoteTree -SshHost $SshHost -Root $installPath
}
catch {
    Stop-KitRun -Reason "the installed integration cannot be handled safely: $($_.Exception.Message)"
}
if ($installed.State -eq 'dir' -and @($installed.Others).Count -gt 0) {
    Stop-KitRun -Reason "the installed integration holds something that is not a folder or a regular file (a symlink?): $(@($installed.Others)[0])"
}
if ($installed.State -ne 'dir' -and $installed.State -ne 'absent') {
    Stop-KitRun -Reason "$installPath is $($installed.State) on the host."
}
foreach ($rel in @($installed.Files.Keys)) {
    $why = Test-EccoKitPackagePath -Path $rel
    if ($why) {
        Stop-KitRun -Reason "the installed integration holds $rel, which no kit could have written ($why)."
    }
}

try {
    $snapshot = Get-EccoProtectedSnapshot -SshHost $SshHost
}
catch {
    Stop-KitRun -Reason $_.Exception.Message
}
$entryCount = Get-EccoConfigEntryCount -SshHost $SshHost -Path $configEntriesPath

$restoreFiles = $null
if ($Action -eq 'Rollback') {
    try {
        $sumsBytes = Read-EccoRemoteTextFile -SshHost $SshHost -Path "$backupRoot/BACKUP_SHA256SUMS"
        $restoreFiles = (New-Object 'System.Collections.Generic.SortedDictionary[string,string]' ([System.StringComparer]::Ordinal))
        foreach ($e in (ConvertFrom-EccoSumsText -Bytes $sumsBytes -Label 'BACKUP_SHA256SUMS' -PackageRelative)) {
            $restoreFiles[$e.Path] = $e.Sha256
        }
        if (-not $restoreFiles.ContainsKey('manifest.json')) {
            throw 'BACKUP_SHA256SUMS does not list manifest.json'
        }
        $backupTree = Get-EccoKitRemoteTree -SshHost $SshHost -Root "$backupRoot/custom_components__ecco_intelligence"
        $diff = Compare-EccoKitTree -Tree $backupTree -ExpectedFiles $restoreFiles
        if ($diff) {
            throw "the backup does not match its BACKUP_SHA256SUMS: $diff"
        }
    }
    catch {
        Stop-KitRun -Reason "the backup $backupRoot does not verify: $($_.Exception.Message)"
    }
    Write-Host "Backup verified: $backupRoot ($(@($restoreFiles.Keys).Count) files, BACKUP_SHA256SUMS)"
}

# What the run would do, from the installed state.
$noChange = $false
if ($kitInfo -and $installed.State -eq 'dir') {
    $noChange = $null -eq (Compare-EccoKitTree -Tree $installed -ExpectedFiles $kitInfo.PackageFiles)
}
if ($restoreFiles -and $installed.State -eq 'dir') {
    $noChange = $null -eq (Compare-EccoKitTree -Tree $installed -ExpectedFiles $restoreFiles)
}
switch ($Action) {
    'Install' {
        if ($installed.State -ne 'absent') {
            Stop-KitRun -Reason "-Action Install needs $installPath absent, but $(@($installed.Files.Keys).Count) files are installed: use -Action Upgrade."
        }
    }
    'Upgrade' {
        if ($installed.State -ne 'dir') {
            Stop-KitRun -Reason "-Action Upgrade needs an installed integration, but $installPath is absent: use -Action Install."
        }
        if ($noChange) {
            Stop-KitRun -Reason 'NO CHANGE: the installed integration already equals this kit; nothing to do.'
        }
    }
    'Rollback' {
        if ($noChange) {
            Stop-KitRun -Reason 'NO CHANGE: the installed integration already equals that backup; nothing to do.'
        }
    }
    'Uninstall' {
        if ($installed.State -ne 'dir') {
            Stop-KitRun -Reason "-Action Uninstall needs an installed integration, but $installPath is absent."
        }
        if ($entryCount -ne 0) {
            $countText = if ($entryCount -lt 0) { 'cannot be read' } else { "is $entryCount" }
            Stop-KitRun -Reason "the count of config-entry lines naming ecco_intelligence ${countText}: delete the integration's entry in Home Assistant first (Settings -> Devices and services), then uninstall."
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Plan: print what Install or Upgrade would do, and stop (read-only).
# ---------------------------------------------------------------------------
$staging = "/config/ecco/staging/$runStamp"
$backupDir = "/config/ecco-backups/$runStamp"
if ($Action -eq 'Plan') {
    $mode = if ($installed.State -eq 'absent') { 'Install' } elseif ($noChange) { 'NO CHANGE (the installed tree equals the kit: nothing to do)' } else { 'Upgrade' }
    $newRoot = "$staging/new/ecco_intelligence"
    $previous = if ($installed.State -eq 'dir') { "$staging/previous/ecco_intelligence" } else { '' }
    $installedText = if ($installed.State -eq 'absent') { 'absent' } else { "$(@($installed.Files.Keys).Count) files (+$(@($installed.Pycache).Count) __pycache__ entries)" }
    $siteText = if ($snapshot.Site -cmatch '^[0-9a-f]{64}\z') { "present, sha256 $($snapshot.Site.Substring(0, 8))..." } else { $snapshot.Site }
    $countText = if ($entryCount -lt 0) { 'unknown' } else { [string]$entryCount }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('')
    $lines.Add('ECCO INTELLIGENCE KIT PLAN (read-only: nothing was written)')
    $lines.Add("Host        : $SshHost (-Target $Target)")
    $lines.Add($targetLine)
    $lines.Add($configRoot.Line)
    $lines.Add("HA version  : $haVersion (expected $ExpectedHaVersion) - match")
    $lines.Add($gateLine)
    $lines.Add($(if ($gate.PinLine) { $gate.PinLine } else { 'Gate pin    : none' }))
    $lines.Add("Kit         : SHA256SUMS $($kitInfo.SumsSha256) (expected - match); version $($kitInfo.Version); git_sha $($kitInfo.GitSha) = HEAD; $rebuildLine")
    $lines.Add($equivalenceLine)
    $lines.Add("Kit content : $(@($kitInfo.PackageFiles.Keys).Count) files in $(@($kitInfo.PackageDirs).Count + 1) folders, $($kitInfo.Bytes) bytes")
    $lines.Add("Installed   : $installedText")
    $lines.Add("Action      : $mode")
    $lines.Add("Same device : custom_components and ecco/ on device $($fs.Device) (atomic rename)")
    $lines.Add("Free space  : $($fs.AvailableKiB) KiB under /config (needs $needKiB KiB)")
    $lines.Add("Site file   : $siteText (never read or written by this route)")
    $lines.Add("State folder: $(if ($snapshot.State -cmatch '^[0-9]+:[0-9]+\z') { 'present' } else { $snapshot.State }) (never touched)")
    $lines.Add("Config entry: $countText line(s) naming ecco_intelligence (Uninstall needs 0)")
    $lines.Add('Destinations (the allowlist; first 8 hex digits of each sha256):')
    foreach ($rel in @($kitInfo.PackageFiles.Keys)) {
        $lines.Add("  $installPath/$rel  $($kitInfo.PackageFiles[$rel].Substring(0, 8))")
    }
    $lines.Add("Staging     : $newRoot (one folder level at a time; one scp per folder)")
    $lines.Add("Backup      : $(if ($previous) { "$backupDir/custom_components__ecco_intelligence (verified, BACKUP_SHA256SUMS)" } else { 'none (nothing installed)' })")
    $lines.Add("Swap        : $(Get-EccoKitSwapCommand -NewRoot $newRoot -PreviousPath $previous)")
    $lines.Add('Never touched: /config/ecco/intelligence/site.local.json, /config/ecco/intelligence/state/, the site policy, every path outside the allowlist')
    $lines.Add('Restart     : RESTART REQUIRED after an install or upgrade - separately gated, never performed by this tool')
    $lines.Add("Rollback    : automatic on any failure once the swap starts; afterwards $(if ($previous) { ".\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp $runStamp ..." } else { '.\tools\deploy-ha-kit.ps1 -Action Uninstall ... (refused while a config entry exists)' })")
    $lines.Add('Preconditions (owner): a protected Home Assistant backup taken; input_boolean.ecco_intel_paused ON; no other live change in progress')
    $lines | ForEach-Object { Write-Host $_ }
    return
}

# ---------------------------------------------------------------------------
# 4. Write: staging, verified backup, swap, verification, ha core check.
# ---------------------------------------------------------------------------
$mode = switch ($Action) { 'Install' { 'Install' } 'Upgrade' { 'Upgrade' } 'Rollback' { 'Restore' } 'Uninstall' { 'Uninstall' } }
$writeArgs = @{
    SshHost   = $SshHost
    Mode      = $mode
    Stamp     = $runStamp
    Installed  = $installed
    Snapshot   = $snapshot
    ConfigRoot = $configRoot.Resolved
}
if ($kitInfo) {
    $writeArgs.KitInfo = $kitInfo
}
if ($restoreFiles) {
    $writeArgs.RestoreFiles = $restoreFiles
    $writeArgs.RestoreFrom = "$backupRoot/custom_components__ecco_intelligence"
}
$result = Invoke-EccoKitWrite @writeArgs

$common = "-SshHost $SshHost -Target $Target -ExpectedHaVersion $ExpectedHaVersion"
if ($sshConfigArgs.Count -gt 0) {
    # The undo reaches the same test instance through the same harness-owned ssh configuration.
    $common += " -SshConfigFile '" + ([string]$sshConfigArgs[1]).Replace("'", "''") + "'"
}
Write-Host ''
Write-Host "ECCO INTELLIGENCE KIT $($Action.ToUpperInvariant()) PASSED"
Write-Host "Host        : $SshHost (-Target $Target)"
Write-Host $configRoot.Line
if ($kitInfo) {
    Write-Host "Kit         : SHA256SUMS $($kitInfo.SumsSha256) (version $($kitInfo.Version), git_sha $($kitInfo.GitSha))"
    Write-Host $equivalenceLine
}
if ($restoreFiles) {
    Write-Host "Restored    : $(@($restoreFiles.Keys).Count) files from $backupRoot/custom_components__ecco_intelligence"
}
if ($Action -eq 'Uninstall') {
    Write-Host "Installed   : none - the integration was moved (not deleted) to $($result.PreviousPath)"
} else {
    Write-Host "Installed   : $installPath (verified in place)"
}
Write-Host "Staging     : $($result.StagingDir) (kept; nothing is deleted)"
Write-Host "Backup      : $(if ($result.BackupDir) { $result.BackupDir } else { 'none (nothing was installed before)' })"
Write-Host $gateLine
if ($gate.PinLine) {
    Write-Host $gate.PinLine
}
Write-Host 'HA check    : passed'
Write-Host 'RESTART REQUIRED - separately gated, not performed: Home Assistant loads (or forgets) custom integration code only at a restart.'
if ($Action -ne 'Uninstall') {
    Write-Host 'Keep input_boolean.ecco_intel_paused ON until after the restart.'
}
if ($result.BackupDir) {
    Write-Host "To undo     : .\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp $runStamp $common"
} elseif ($Action -ne 'Uninstall') {
    Write-Host "To undo     : .\tools\deploy-ha-kit.ps1 -Action Uninstall $common (refused while a config entry exists)"
}
