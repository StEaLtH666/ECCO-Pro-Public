<#
    Offline/static tests for the ECCO Home Assistant SSH deployment
    tooling. No network access, no SSH, no live Home Assistant - these
    prove the parts of the tooling that can be proven without hardware.

    This intentionally does NOT simulate a successful SSH/SCP round trip.
    A green result here is proof that destination validation, the
    clean-working-tree gate, and PowerShell syntax are correct. It is
    NOT proof that a live deployment against real Home Assistant works -
    see the "STILL REQUIRES LIVE HA VERIFICATION" section printed at the
    end, and docs/HA_SSH_DEPLOYMENT.md.

    Windows PowerShell 5.1 compatible. No external module dependencies
    (no Pester) - this is a small self-contained pass/fail runner.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$toolsDir = Join-Path $repoRoot 'tools'

Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force

$script:pass = 0
$script:fail = 0

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Condition,
        [string]$Detail
    )
    if ($Condition) {
        $script:pass++
        Write-Host "  PASS  $Name"
    } else {
        $script:fail++
        Write-Host "  FAIL  $Name$(if ($Detail) { " - $Detail" })"
    }
}

function Test-DestinationAccepted {
    param([string]$Destination)
    try {
        Test-EccoDeploymentDestination -Destination $Destination | Out-Null
        return $true
    } catch {
        return $false
    }
}

Write-Host 'ECCO deployment tooling - offline tests'
Write-Host ''

# ---------------------------------------------------------------------
# 1. Destination validation: allowed destinations must be accepted.
# ---------------------------------------------------------------------
Write-Host '[1] Allowed destinations are accepted'
$allowed = @(
    '/config/packages/ecco_pro.yaml',
    '/config/packages/ecco_canonical_telemetry.yaml',
    '/config/ecco/dashboards/ecco_pro.yaml',
    '/config/ecco/anything.yaml',
    '/config/www/ecco/ecco-energy-actions-card.js'
)
foreach ($d in $allowed) {
    Assert-True -Name "accept: $d" -Condition (Test-DestinationAccepted $d)
}

# ---------------------------------------------------------------------
# 2. Path traversal, in several shapes, must be rejected.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[2] Path traversal is rejected'
$traversal = @(
    '/config/packages/../../etc/passwd',
    '/config/packages/..',
    '..',
    '../etc/passwd',
    '/config/packages/foo/../../../etc/passwd',
    '/config/ecco/..',
    '/config/www/ecco/../file.js'
)
foreach ($d in $traversal) {
    Assert-True -Name "reject traversal: $d" -Condition (-not (Test-DestinationAccepted $d))
}

# ---------------------------------------------------------------------
# 3. Destinations outside the allowlist must be rejected - including
#    sibling directories that merely share a text prefix, and case
#    variants (the remote filesystem is case-sensitive; matching must
#    stay ordinal so this never silently succeeds against the wrong
#    directory).
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[3] Non-allowlisted destinations are rejected'
$disallowed = @(
    '/etc/passwd',
    '/config/secrets.yaml',
    '/config/packages-evil/x.yaml',
    '/config/eccoX/x.yaml',
    '/CONFIG/packages/x.yaml',
    '/config/Packages/x.yaml',
    'config/packages/x.yaml',
    'relative/path.yaml',
    # /config/www/ is NOT itself allowed - only the /config/www/ecco/
    # subdirectory is. A file directly under /config/www/, a sibling
    # directory that merely shares the "ecco" prefix text, and any other
    # arbitrary subdirectory must all still be rejected.
    '/config/www/ecco-energy-actions-card.js',
    '/config/www/ecco-x/file.js',
    '/config/www/anything/file.js',
    '/config/www/',
    '/config/www/ecco'
)
foreach ($d in $disallowed) {
    Assert-True -Name "reject outside allowlist: $d" -Condition (-not (Test-DestinationAccepted $d))
}

# ---------------------------------------------------------------------
# 4. Shell-injection-shaped and malformed inputs must be rejected.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[4] Quote/whitespace/control-character/malformed inputs are rejected'
$malformed = @(
    "/config/packages/x'; rm -rf /",
    "/config/packages/x'`$(rm -rf /)",
    ' /config/packages/x.yaml',
    '/config/packages/x.yaml ',
    '/config/packages//x.yaml',
    '/config/packages/./x.yaml',
    '/config/packages/.',
    ''
)
foreach ($d in $malformed) {
    Assert-True -Name "reject malformed: [$d]" -Condition (-not (Test-DestinationAccepted $d))
}
Assert-True -Name 'reject control character (tab)' -Condition (-not (Test-DestinationAccepted "/config/packages/x`ty.yaml"))

# ---------------------------------------------------------------------
# 5. Windows-style backslashes are normalised, not treated as an escape
#    hatch around the allowlist or traversal checks.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[5] Backslash destinations normalise safely'
Assert-True -Name 'backslash form of an allowed destination is accepted' -Condition (Test-DestinationAccepted '\config\packages\ecco_pro.yaml')
Assert-True -Name 'backslash form of traversal is still rejected' -Condition (-not (Test-DestinationAccepted '\config\packages\..\..\etc\passwd'))

# ---------------------------------------------------------------------
# 6. Clean working tree gate, exercised against a real scratch git repo
#    (no SSH involved - this is purely local git state).
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[6] Clean working tree gate'
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) "ecco-clean-tree-test-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $scratch | Out-Null
try {
    Push-Location $scratch
    try {
        & git init -q .
        & git config user.email 'test@example.invalid'
        & git config user.name 'ECCO Test'
        Set-Content -Path (Join-Path $scratch 'a.txt') -Value 'a'
        & git add a.txt
        & git commit -q -m 'initial'
    }
    finally {
        Pop-Location
    }

    $cleanOk = $true
    try {
        Assert-EccoCleanWorkingTree -RepoRoot $scratch
    } catch {
        $cleanOk = $false
    }
    Assert-True -Name 'clean scratch repo is accepted' -Condition $cleanOk

    Set-Content -Path (Join-Path $scratch 'b.txt') -Value 'b'
    $dirtyRejected = $false
    try {
        Assert-EccoCleanWorkingTree -RepoRoot $scratch
    } catch {
        $dirtyRejected = $true
    }
    Assert-True -Name 'dirty scratch repo (untracked file) is rejected' -Condition $dirtyRejected
}
finally {
    Remove-Item -Path $scratch -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------
# 7. Rollback result message wording, given synthetic outcomes. This is
#    pure string formatting - no SSH call, no simulated disconnect - and
#    exists specifically to prove the wording never asserts a confirmed
#    successful rollback ("was rolled back") when the restore could not
#    actually be verified, and says so plainly when SSH/the remote host
#    looks to be the more likely cause than a genuine HA config problem.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[7] Rollback result message wording (synthetic outcomes, no SSH)'

$confirmedMsg = Format-EccoRollbackResultMessage `
    -Reason 'test reason' `
    -BackupDescription '/config/ecco-backups/x/y' `
    -RestoreVerified $true `
    -RestoreProblem $null `
    -RollbackCheckRan $true `
    -RollbackCheckExitCode 0
Assert-True -Name 'confirmed rollback says "was rolled back"' -Condition ($confirmedMsg -match 'was rolled back')
Assert-True -Name 'confirmed rollback does not warn about SSH unavailability' -Condition ($confirmedMsg -notmatch 'may be unavailable')

$ambiguousMoveMsg = Format-EccoRollbackResultMessage `
    -Reason 'move result unknown' `
    -BackupDescription '/config/ecco-backups/x/y' `
    -RestoreVerified $false `
    -RestoreProblem 'Rollback restore/remove step itself failed: Remote command failed: cp -p ...' `
    -RollbackCheckRan $false `
    -RollbackCheckExitCode $null
Assert-True -Name 'unconfirmed rollback does NOT say "was rolled back"' -Condition ($ambiguousMoveMsg -notmatch 'was rolled back')
Assert-True -Name 'unconfirmed rollback says it could not be confirmed' -Condition ($ambiguousMoveMsg -match 'could NOT be confirmed successful')
Assert-True -Name 'unconfirmed rollback + no check run warns about SSH/remote host availability' -Condition ($ambiguousMoveMsg -match 'SSH or the remote host itself is unavailable')
Assert-True -Name 'unconfirmed rollback still reports the backup path' -Condition ($ambiguousMoveMsg -match [regex]::Escape('/config/ecco-backups/x/y'))

$verifiedRestoreButCheckFailedMsg = Format-EccoRollbackResultMessage `
    -Reason 'ha core check failed' `
    -BackupDescription 'none (new file)' `
    -RestoreVerified $true `
    -RestoreProblem $null `
    -RollbackCheckRan $true `
    -RollbackCheckExitCode 1
Assert-True -Name 'verified restore + failed recheck still says "was rolled back"' -Condition ($verifiedRestoreButCheckFailedMsg -match 'was rolled back')
Assert-True -Name 'verified restore + failed recheck does not claim the check passed' -Condition ($verifiedRestoreButCheckFailedMsg -notmatch 'check: passed')
Assert-True -Name 'verified restore + failed recheck does not warn about SSH (only restore failure triggers that note)' -Condition ($verifiedRestoreButCheckFailedMsg -notmatch 'may be unavailable')

# ---------------------------------------------------------------------
# 8. PowerShell syntax for every deployment-tooling script, including
#    the new shared module and this test script's own directory.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[8] PowerShell syntax'
$psFiles = @(Get-ChildItem -Path $toolsDir -Include '*.ps1', '*.psm1' -File -Recurse)
foreach ($file in $psFiles) {
    $tokens = $null
    $parseIssues = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseIssues) | Out-Null
    Assert-True -Name "parses: $($file.FullName.Substring($repoRoot.Length + 1))" -Condition (-not ($parseIssues -and $parseIssues.Count -gt 0)) -Detail ($(if ($parseIssues) { ($parseIssues | Select-Object -First 1).Message }))
}

# ---------------------------------------------------------------------
# 9. The manual-resource reminder deploy-ha.ps1 prints after a copy.
#    Every destination under /config/www/ecco/ gets it, whatever the
#    source path (the content-addressed deploy copies
#    dist/deploy/stage/<card>.<sha8>.js, which the old frontend/<card>/dist
#    gate never matched). Synthetic resource lists only, no SSH.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[9] Manual-resource reminder (synthetic resource lists, no SSH)'
$newDest = '/config/www/ecco/ecco-weather-solar-card.88cd2d8a.js'
$newUrl = '/local/ecco/ecco-weather-solar-card.88cd2d8a.js'
$oldUrl = '/local/ecco/ecco-weather-solar-card.0123abcd.js'
Assert-True -Name 'a /config/www/ecco/ destination maps to its /local/ecco/ URL' -Condition ((Get-EccoLovelaceResourceUrl -Destination $newDest) -eq $newUrl)
Assert-True -Name 'package, dashboard and bare www/ecco destinations get no resource URL' -Condition (
    ($null -eq (Get-EccoLovelaceResourceUrl -Destination '/config/packages/ecco_pro.yaml')) -and
    ($null -eq (Get-EccoLovelaceResourceUrl -Destination '/config/ecco/dashboards/ecco_pro.yaml')) -and
    ($null -eq (Get-EccoLovelaceResourceUrl -Destination '/config/www/ecco/')))
Assert-True -Name 'no reminder for a destination outside /config/www/ecco/' -Condition (@(Format-EccoResourceReminder -Destination '/config/packages/ecco_pro.yaml' -Resources @()).Count -eq 0)

$storage = '{"version": 1, "key": "lovelace_resources", "data": {"items": [' +
    '{"id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "type": "module", "url": "/hacsfiles/button-card/button-card.js"},' +
    '{"id": "c0ffee00111111111111111111111111", "type": "module", "url": "' + $oldUrl + '"}]}}'
$items = ConvertFrom-EccoLovelaceResources -Json $storage
Assert-True -Name 'the lovelace_resources storage file parses into its items' -Condition ($items.Count -eq 2 -and $items[1].url -eq $oldUrl)
$emptyItems = ConvertFrom-EccoLovelaceResources -Json '{"data": {"items": []}}'
Assert-True -Name 'an empty resource list parses as empty, not as "unknown"' -Condition (($null -ne $emptyItems) -and $emptyItems.Count -eq 0)
foreach ($bad in @('{"data": {"items": [', '{"version": 1}', '[]')) {
    $threw = $false
    try { ConvertFrom-EccoLovelaceResources -Json $bad | Out-Null } catch { $threw = $true }
    Assert-True -Name "a wrong or truncated read is an error, never 'no resources': $bad" -Condition $threw
}

$notSwitched = @(Format-EccoResourceReminder -Destination $newDest -Resources $items) -join "`n"
Assert-True -Name 'resource still on the old file: NOT SWITCHED, names the old URL and id, says the copy is NOT LIVE' -Condition (
    $notSwitched -match [regex]::Escape("RESOURCE NOT SWITCHED ecco-weather-solar-card: the dashboards still load $oldUrl (id c0ffee00)") -and
    $notSwitched -match 'NOT LIVE')
Assert-True -Name 'the reminder keeps the manual-registration and never-edits-.storage lines and names verify-resource' -Condition (
    $notSwitched -match [regex]::Escape("Resource URL: $newUrl") -and
    $notSwitched -match 'Resource registration is manual' -and
    $notSwitched -match 'never edits Home Assistant \.storage' -and
    $notSwitched -match 'ecco_deploy_preflight\.py verify-resource')

$switched = ConvertFrom-EccoLovelaceResources -Json ($storage.Replace($oldUrl, $newUrl))
$already = @(Format-EccoResourceReminder -Destination $newDest -Resources $switched) -join "`n"
Assert-True -Name 'resource already on this file: says so and never claims NOT LIVE or VERIFIED' -Condition (
    $already -match 'RESOURCE ALREADY POINTS AT THIS FILE ecco-weather-solar-card' -and $already -notmatch 'NOT LIVE' -and $already -notmatch 'VERIFIED')
$withQuery = ConvertFrom-EccoLovelaceResources -Json ($storage.Replace($oldUrl, '/local/ecco/ecco-fallback-recovery-card.js?v=1234567'))
$query = @(Format-EccoResourceReminder -Destination '/config/www/ecco/ecco-fallback-recovery-card.js' -Resources $withQuery) -join "`n"
Assert-True -Name 'a resource with a ?v= query still matches its file' -Condition ($query -match 'RESOURCE ALREADY POINTS AT THIS FILE ecco-fallback-recovery-card')

$none = @(Format-EccoResourceReminder -Destination $newDest -Resources $emptyItems) -join "`n"
Assert-True -Name 'no resource for the card: NOT REGISTERED, NOT LIVE' -Condition ($none -match 'RESOURCE NOT REGISTERED ecco-weather-solar-card' -and $none -match 'NOT LIVE')
$dupItems = ConvertFrom-EccoLovelaceResources -Json ($storage.Replace('"/hacsfiles/button-card/button-card.js"', '"' + $newUrl + '"'))
$dup = @(Format-EccoResourceReminder -Destination $newDest -Resources $dupItems) -join "`n"
Assert-True -Name 'two resources for the card: a WARNING that exactly one is expected' -Condition ($dup -match 'WARNING: 2 resources load ecco-weather-solar-card')
$unknown = @(Format-EccoResourceReminder -Destination $newDest -Resources $null -ReadProblem 'ssh exit code 255') -join "`n"
Assert-True -Name 'read-back failed: RESOURCE UNKNOWN with the reason, never NOT SWITCHED or ALREADY' -Condition (
    $unknown -match 'RESOURCE UNKNOWN ecco-weather-solar-card' -and $unknown -match 'ssh exit code 255' -and
    $unknown -notmatch 'NOT SWITCHED' -and $unknown -notmatch 'ALREADY POINTS')

$deployText = Get-Content -Raw -Path (Join-Path $toolsDir 'deploy-ha.ps1')
Assert-True -Name 'deploy-ha.ps1 gates the reminder on the destination, not on a frontend/<card>/dist source' -Condition (
    $deployText -match [regex]::Escape('if (Get-EccoLovelaceResourceUrl -Destination $Destination)') -and
    $deployText -notmatch '(?<!else)if \(\$isFrontendAsset\)')

# ---------------------------------------------------------------------
Write-Host ''
Write-Host "Results: $script:pass passed, $script:fail failed"
Write-Host ''
Write-Host 'STILL REQUIRES LIVE HA VERIFICATION (not proven by this script):'
Write-Host '  - Actual SSH/SCP round trip against the ecco-ha alias'
Write-Host '  - Post-install SHA256 verification against a real remote file'
Write-Host '  - Unified rollback restoring a real backup and re-running a real `ha core check`'
Write-Host '  - test-ha-rollback.ps1 end-to-end against live Home Assistant'
Write-Host '  - deploy-dashboard.ps1 end-to-end against live Home Assistant'
Write-Host '  - Behaviour under an actual dropped SSH connection mid-deployment'
Write-Host '  - The ambiguous mv-failure rollback path (deploy-ha.ps1) triggered by a real SSH/transport failure during the move into place'
Write-Host ''

if ($script:fail -gt 0) {
    throw "$script:fail offline test(s) failed."
}

Write-Host 'ECCO deployment tooling offline tests PASSED'
