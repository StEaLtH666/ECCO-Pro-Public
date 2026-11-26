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

    Sections 10-14 exercise the dashboard preservation gate offline: a
    fictional host (local files behind an injected reader, no SSH) and
    the real tools/ecco_dashboard_guard.py; section 13 runs the host
    probe under a local POSIX sh (Git for Windows) on a fictional temp
    tree; section 14 runs deploy-ha.ps1 itself with ssh and scp replaced
    in-process by stubs (no network), including the gate pin
    (-ExpectedSiteGate and the local pin file) and drift recovery;
    section 15 runs the rollback against a stubbed ssh that executes its
    commands under the local POSIX sh on a fictional /config tree, to
    prove the restored file gets a new modification time; section 16 runs
    deploy-ha.ps1 end to end on such a tree (a drift recovery, its PASSED
    block and its rollback). Sections 14 and 16 run deploy-ha.ps1 from a
    copy of the tooling under a temporary repository root, so a pin file in
    this checkout never changes a run and nothing is written into the
    checkout. They need a Python with PyYAML,
    the same requirement deploy-ha.ps1 has; pass -Python <path to
    python.exe> when the python on PATH has no PyYAML.

    Sections 17-22 cover the Intelligence kit route (PR-5):
    deploy-ha-kit.ps1, place-ha-site-file.ps1, deploy-ha.ps1 -Action
    Retire and the -Target Test|Production guard. They use fictional kits
    built by a fictional stand-in for tools/build_ha_integration.py in
    throwaway git repositories, and a fictional /config tree driven by
    stubbed ssh and scp under the local POSIX sh. Junctions (mklink /J)
    stand in for symlinks. The sections cover the refusals, the kit and
    SHA256SUMS checks, kit equivalence and the rebuild (17), the target
    guard (18), every read-only BLOCK case, Uninstall with an unreadable
    config-entry store included (19), install, upgrade, both rollbacks and
    uninstall end to end (20), the site-file placement with its target
    guard in both directions, a connection lost after the rename and the
    rename command itself lost (21), and Plan, Retire (the same two, and the
    Target line in its PASSED block) and the static checks (22). Sections 23-24 cover
    amendment A26 (the SSH add-on's /config is itself a symlink): every
    route through a /config junction to a real folder, the refused shapes
    (dangling, to a file, a loop, a plain file), a symlinked segment below
    /config, and the root re-pointed between the read-only checks and the
    first write (23); the probe, its reading and the root test as pure
    logic (24); section 13 runs the single-file route's host probe through
    the same shapes. Amendment A49 (after the first L3 run): the site file's
    strict JSON check against the runtime's own rule (25; the placement
    cases in 21), validate-ecco.ps1 honouring the route's -Python (26), and
    the backup-folder and move-aside wording (16, 20, 21). Amendment A52:
    the site file's check refuses every file the runtime refuses (25, 21),
    Uninstall's wording (20) and a relative -Python (26). Section 27 reads
    the route's public text (amendments A41, A45, A52): no dated owner
    decision, decision item number, date, live-read evidence label or word
    amendment A41 lists. The ssh/scp stubs are global: run this suite
    serially.

    Run: powershell -NoProfile -ExecutionPolicy Bypass -File tools\tests\Test-EccoDeploy.ps1 [-Python <python.exe>] [-Sh <sh.exe>]
    (CI only parses tools/*.ps1; this runner is a required local
    pre-push step for changes to the deploy tooling or the guard.)
#>

[CmdletBinding()]
param(
    [string]$Python = 'python',

    # A POSIX sh for section 13 (default: Git for Windows' sh.exe when present).
    [string]$Sh = ''
)

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

$dashboardRollbackMsg = Format-EccoRollbackResultMessage `
    -Reason 'ha core check failed' `
    -BackupDescription '/config/ecco-backups/x/y' `
    -RestoreVerified $true `
    -RestoreProblem $null `
    -RollbackCheckRan $true `
    -RollbackCheckExitCode 0 `
    -Dashboard $true
Assert-True -Name 'a dashboard rollback message asks for a lovelace/config read-back of what Home Assistant serves' -Condition (
    $dashboardRollbackMsg -match 'DASHBOARD READ-BACK REQUIRED' -and $dashboardRollbackMsg -match 'websocket lovelace/config' -and $dashboardRollbackMsg -match 'was rolled back')
Assert-True -Name 'a rollback message for any other file has no dashboard read-back line' -Condition ($confirmedMsg -notmatch 'READ-BACK' -and $verifiedRestoreButCheckFailedMsg -notmatch 'lovelace/config')
$driftRollbackMsg = Format-EccoRollbackResultMessage `
    -Reason 'ha core check failed' `
    -BackupDescription '/config/ecco-backups/x/y' `
    -RestoreVerified $true `
    -RestoreProblem $null `
    -RollbackCheckRan $true `
    -RollbackCheckExitCode 0 `
    -Dashboard $true `
    -DriftRecovery $true
Assert-True -Name 'the rollback of a drift recovery says that the restored backup is the drifted file, without the site policy''s protected layer' -Condition (
    $driftRollbackMsg -match 'DRIFT RECOVERY ROLLED BACK' -and $driftRollbackMsg -match 'backup is the drifted live file' -and
    $driftRollbackMsg -match 'does not carry the policy''s protected layer' -and $driftRollbackMsg -match 'DASHBOARD READ-BACK REQUIRED') -Detail $driftRollbackMsg
Assert-True -Name 'any other rollback has no drift line' -Condition ($dashboardRollbackMsg -notmatch 'DRIFT' -and $confirmedMsg -notmatch 'DRIFT')

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
# 10. The site-local area holds the dashboard protection policy: no
#     destination under it is ever accepted, in any spelling the
#     validator normalises; a sibling that merely shares the prefix text
#     is still an ordinary /config/ecco/ destination.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[10] /config/ecco/site-local/ is never a deployment destination'
foreach ($d in @('/config/ecco/site-local/dashboard-protection.json', '/config/ecco/site-local/x.yaml', '/config/ecco/site-local',
                 '\config\ecco\site-local\dashboard-protection.json', '/config/ecco/site-local/sub/x.yaml')) {
    Assert-True -Name "reject site-local: $d" -Condition (-not (Test-DestinationAccepted $d))
}
$siteLocalMessage = ''
try { Test-EccoDeploymentDestination -Destination '/config/ecco/site-local/dashboard-protection.json' | Out-Null } catch { $siteLocalMessage = $_.Exception.Message }
Assert-True -Name 'the refusal names the site-local policy' -Condition ($siteLocalMessage -match 'site-local dashboard protection policy')
Assert-True -Name 'a sibling sharing the prefix text is still accepted: /config/ecco/site-localx/a.yaml' -Condition (Test-DestinationAccepted '/config/ecco/site-localx/a.yaml')

# ---------------------------------------------------------------------
# 11. Which destinations are dashboard destinations by their path.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[11] Dashboard destinations by path'
foreach ($d in @('/config/ecco/dashboards/ecco_pro.yaml', '/config/ecco/dashboards/a.yml', '/config/ecco/dashboards/sub/b.YAML')) {
    Assert-True -Name "dashboard path: $d" -Condition (Test-EccoDashboardDestinationPath -Destination $d)
}
foreach ($d in @('/config/packages/ecco_pro.yaml', '/config/ecco/dashboards/', '/config/ecco/dashboards/x.json', '/config/www/ecco/a.js',
                 '/config/ecco/dashboards-x/a.yaml', '/config/ecco/other.yaml')) {
    Assert-True -Name "not a dashboard path: $d" -Condition (-not (Test-EccoDashboardDestinationPath -Destination $d))
}

# ---------------------------------------------------------------------
# 12. The gate itself against a fictional host: local files behind an
#     injected reader (no SSH) and the real guard. Fictional data only.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host "[12] Dashboard preservation gate on a fictional host (guard run with '$Python')"
$guard = Join-Path $toolsDir 'ecco_dashboard_guard.py'
$hasYaml = $false
try {
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python -I -c 'import yaml' 2>&1 | Out-Null
    $hasYaml = ($LASTEXITCODE -eq 0)
} catch {
    $hasYaml = $false
} finally {
    $ErrorActionPreference = $previousEap
}
Assert-True -Name "the test Python has PyYAML (deploy-ha.ps1 needs it too; pass -Python <python.exe> otherwise)" -Condition $hasYaml

$destination = '/config/ecco/dashboards/ecco_pro.yaml'
$policyRemote = '/config/ecco/site-local/dashboard-protection.json'
$resourcesRemote = '/config/.storage/lovelace_resources'
$tempRoot = [System.IO.Path]::GetTempPath()
# The gate's own temp folders: ecco-dashboard-guard-<32 hex> / ecco-dashboard-verify-<32 hex> (a GUID in 'N' format).
$gateFolderPattern = '^ecco-dashboard-(guard|verify)-[0-9a-f]{32}$'
$gateFoldersBefore = @(Get-ChildItem -LiteralPath $tempRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $gateFolderPattern }).Count
$fixtures = Join-Path $tempRoot "ecco-gate-test-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $fixtures | Out-Null
$script:fakeHost = @{}
$fakeReader = {
    param($RemotePath, $LocalPath)
    $entry = $script:fakeHost[$RemotePath]
    if ($null -eq $entry) { return 'absent' }
    if ($entry -eq 'UNREADABLE') { throw "fictional host: $RemotePath is not readable" }
    Copy-Item -LiteralPath $entry -Destination $LocalPath
    return 'present'
}

function Invoke-TestGate {
    param([string]$Candidate, [string[]]$Accept = @(), [string]$Dest = $destination, [string]$UsePython = $Python, [string]$GuardFile = $guard, [switch]$Drift)
    try {
        $r = Invoke-EccoDashboardPreservationGate -SshHost 'fictional-host' -Destination $Dest -CandidatePath $Candidate -GuardPath $GuardFile -ResourcesPath $resourcesRemote -AcceptRemovedCardType $Accept -Python $UsePython -AllowDriftRecovery:$Drift -RemoteFileReader $fakeReader 6>$null
        return [pscustomobject]@{ Threw = $false; Message = ''; Result = $r }
    } catch {
        return [pscustomobject]@{ Threw = $true; Message = $_.Exception.Message; Result = $null }
    }
}

try {
    $live = Join-Path $fixtures 'live.yaml'
    $generic = Join-Path $fixtures 'generic.yaml'
    $resources = Join-Path $fixtures 'lovelace_resources'
    $badPolicy = Join-Path $fixtures 'bad-policy.json'
    $policy = Join-Path $fixtures 'policy.json'
    $liveText = @(
        'title: Example',
        'views:',
        '  - title: Overview',
        '    sections:',
        '      - type: grid',
        '        cards:',
        '          - type: custom:example-site-card',
        '            title: Flow',
        '            scene:',
        '              pack: media-source://media_source/local/example/scene',
        '              crossfade_ms: 900',
        '              variant: example-variant',
        '          - type: custom:example-other-card',
        '')
    $genericText = @(
        'title: Example',
        'views:',
        '  - title: Overview',
        '    sections:',
        '      - type: grid',
        '        cards:',
        '          - type: custom:example-flow-card',
        '            title: Flow',
        '            scene:',
        '              pack: /local/example/scenes/',
        '              crossfade_ms: 900',
        '          - type: custom:example-other-card',
        '')
    [System.IO.File]::WriteAllText($live, ($liveText -join "`n"))
    [System.IO.File]::WriteAllText($generic, ($genericText -join "`n"))
    [System.IO.File]::WriteAllText($resources, '{"version": 1, "key": "lovelace_resources", "data": {"items": [{"id": "1", "type": "module", "url": "/local/example/example-site-card.js"}]}}')
    [System.IO.File]::WriteAllText($badPolicy, '{"schema": "ecco-dashboard-protection/1", "gate": "EXAMPLE_PRESERVE_GATE", "dashboards": [')

    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $destination --base $generic --live $live --pointer /views/0/sections/0/cards/0 --require-resource /local/example/example-site-card.js --out $policy 2>&1 | Out-Null
    $makeCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    Assert-True -Name 'make-policy builds the fictional policy from the generic render and the customised live file' -Condition ($makeCode -eq 0 -and (Test-Path -LiteralPath $policy))

    # No site policy: the generic layer only.
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources }
    $r = Invoke-TestGate -Candidate $generic
    Assert-True -Name 'no policy: a candidate that drops a custom card type the live dashboard uses is BLOCKED before any write' -Condition (
        $r.Threw -and $r.Message -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'R4' -and $r.Message -match 'Nothing was written to the host') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Accept @('custom:example-site-card')
    Assert-True -Name 'no policy: -AcceptRemovedCardType waives that generic-layer block' -Condition (
        -not $r.Threw -and $r.Result.Applies -and $r.Result.GateLine -eq 'DASHBOARD_PRESERVE_GATE: PASS' -and -not $r.Result.PolicyNamesDestination) -Detail $r.Message
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'no policy: the live file itself passes, with the live and resource sha256 recorded' -Condition (
        -not $r.Threw -and $r.Result.GateLine -eq 'DASHBOARD_PRESERVE_GATE: PASS' -and $r.Result.LiveSha256 -match '^[0-9a-f]{64}$' -and $r.Result.ResourcesSha256 -match '^[0-9a-f]{64}$') -Detail $r.Message
    $script:fakeHost = @{ $resourcesRemote = $resources }
    $r = Invoke-TestGate -Candidate $generic
    Assert-True -Name 'no policy, no live file: a new file has nothing to protect (PASS)' -Condition (
        -not $r.Threw -and $r.Result.Applies -and $r.Result.LiveState -eq 'absent' -and $r.Result.GateLine -match 'PASS \(new file') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Dest '/config/packages/example.yaml'
    Assert-True -Name 'no policy: a package destination is not a dashboard destination (the gate does not apply)' -Condition (-not $r.Threw -and -not $r.Result.Applies) -Detail $r.Message

    # The site policy names the destination.
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $generic
    Assert-True -Name 'policy: the generic render over the customised live file is BLOCKED under the policy gate name (R2 and R4)' -Condition (
        $r.Threw -and $r.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED - the dashboard preservation gate refused this deployment \(guard exit code 3\)' -and $r.Message -match 'R2: candidate removes or replaces a protected layer' -and $r.Message -match 'R4') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Accept @('custom:example-site-card')
    Assert-True -Name 'policy: -AcceptRemovedCardType never waives the protected layer (still BLOCKED by R2)' -Condition (
        $r.Threw -and $r.Message -match 'EXAMPLE_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'R2') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'policy: the live file passes, and the gate reports that the policy names the destination' -Condition (
        -not $r.Threw -and $r.Result.GateLine -eq 'EXAMPLE_PRESERVE_GATE: PASS' -and $r.Result.PolicyNamesDestination) -Detail $r.Message
    $script:fakeHost = @{ $destination = $live; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'policy: a required resource with no resource list on the host is BLOCKED (R3)' -Condition ($r.Threw -and $r.Message -match 'R3') -Detail $r.Message
    $script:fakeHost = @{ $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'policy: a protected destination that is missing on the host is BLOCKED' -Condition (
        $r.Threw -and $r.Message -match 'EXAMPLE_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'does not exist on the host') -Detail $r.Message
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = 'UNREADABLE' }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'a policy that exists but cannot be read is BLOCKED, never "no policy"' -Condition ($r.Threw -and $r.Message -match 'BLOCKED' -and $r.Message -match 'could not be read') -Detail $r.Message
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $badPolicy }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'a malformed policy is BLOCKED, never "no policy" (also for a non-dashboard destination)' -Condition (
        $r.Threw -and $r.Message -match 'BLOCKED' -and $r.Message -match 'not valid') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $live -Dest '/config/packages/example.yaml'
    Assert-True -Name 'a malformed policy also blocks a package deployment (the policy is read for every destination)' -Condition ($r.Threw -and $r.Message -match 'BLOCKED') -Detail $r.Message
    $script:fakeHost = @{ $destination = 'UNREADABLE'; $resourcesRemote = $resources }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'a live dashboard that cannot be read is BLOCKED' -Condition ($r.Threw -and $r.Message -match 'could not be read') -Detail $r.Message
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources }
    $r = Invoke-TestGate -Candidate $live -UsePython 'ecco-no-such-python-for-tests'
    Assert-True -Name 'a guard that cannot be started (no python) is BLOCKED, never a pass' -Condition ($r.Threw -and $r.Message -match 'BLOCKED') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $live -Accept @('not-a-custom-type')
    Assert-True -Name '-AcceptRemovedCardType refuses a value that is not custom:<name>' -Condition ($r.Threw -and $r.Message -match 'BLOCKED') -Detail $r.Message

    # Review fixes. F1: a crafted -AcceptRemovedCardType value never reaches the guard.
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $crafted = 'custom:example-site-card" --destination /config/ecco/dashboards/other.yaml --accept-removed-type custom:example-site-card'
    $r = Invoke-TestGate -Candidate $generic -Accept @($crafted)
    Assert-True -Name 'a crafted -AcceptRemovedCardType value (a double quote and spaces, which 5.1 would split into guard options) is BLOCKED before the guard runs' -Condition (
        $r.Threw -and $r.Message -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'takes custom card types only') -Detail $r.Message
    foreach ($bad in @('custom:example-site-card --destination', 'custom:', 'custom:a/b', "custom:example-site-card`n")) {
        $r = Invoke-TestGate -Candidate $generic -Accept @($bad)
        Assert-True -Name "-AcceptRemovedCardType refuses '$($bad.Replace("`n", '<LF>'))' (strict custom:<name>)" -Condition ($r.Threw -and $r.Message -match 'takes custom card types only') -Detail $r.Message
    }
    $direct = Invoke-EccoDashboardGuard -Python $Python -GuardPath $guard -Arguments @('classify', '--destination', '/config/ecco/dashboards/a"b.yaml')
    Assert-True -Name 'the guard runner refuses an argument with a double quote (exit 2, BLOCKED) whatever its source' -Condition (
        $direct.ExitCode -eq 2 -and $direct.Output[0] -eq 'DASHBOARD_PRESERVE_GATE: BLOCKED' -and ($direct.Output -join ' ') -match 'double quote') -Detail ($direct.Output -join ' | ')
    $direct = Invoke-EccoDashboardGuard -Python $Python -GuardPath $guard -Arguments @('check', '--candidate', 'C:\folder with space\')
    Assert-True -Name 'the guard runner refuses an argument with a trailing backslash (exit 2)' -Condition ($direct.ExitCode -eq 2) -Detail ($direct.Output -join ' | ')

    # F1: the PASS line must name the gate classify determined.
    $wrapper = Join-Path $fixtures 'wrong-gate-guard.py'
    [System.IO.File]::WriteAllText($wrapper, (@(
        'import runpy, sys',
        ('GUARD = r''' + $guard + ''''),
        'if sys.argv[1:2] == ["check"]:',
        '    print("DASHBOARD_PRESERVE_GATE: PASS")',
        '    sys.exit(0)',
        'sys.argv = [GUARD] + sys.argv[1:]',
        'runpy.run_path(GUARD, run_name="__main__")',
        '') -join "`n"))
    $r = Invoke-TestGate -Candidate $generic -Guard $wrapper
    Assert-True -Name 'a guard that passes under another gate than the policy''s (DASHBOARD_PRESERVE_GATE for a policy-named destination) is BLOCKED' -Condition (
        $r.Threw -and $r.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $r.Message -match "without the expected line 'EXAMPLE_PRESERVE_GATE: PASS'") -Detail $r.Message

    # F2 / C1: classify must answer completely; a guard that crashes (Python exits 1) or answers half is BLOCKED.
    $viewsDestination = '/config/ecco/views/overview.yaml'
    $viewsPolicy = Join-Path $fixtures 'views-policy.json'
    $ErrorActionPreference = 'Continue'
    & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $viewsDestination --base $generic --live $live --pointer /views/0/sections/0/cards/0 --out $viewsPolicy 2>&1 | Out-Null
    $ErrorActionPreference = $previousEap
    $crashPython = Join-Path $fixtures 'crash-python.cmd'
    [System.IO.File]::WriteAllText($crashPython, "@echo Traceback (most recent call last):`r`n@exit /b 1`r`n")
    $halfPython = Join-Path $fixtures 'half-python.cmd'
    [System.IO.File]::WriteAllText($halfPython, "@echo gate: DASHBOARD_PRESERVE_GATE`r`n@exit /b 4`r`n")
    $script:fakeHost = @{ $viewsDestination = $live; $resourcesRemote = $resources; $policyRemote = $viewsPolicy }
    $r = Invoke-TestGate -Candidate $generic -Dest $viewsDestination
    Assert-True -Name 'a policy-named destination outside /config/ecco/dashboards/ is gated (the generic render is BLOCKED by R2)' -Condition (
        $r.Threw -and $r.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'R2') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Dest $viewsDestination -UsePython $crashPython
    Assert-True -Name 'a guard that crashes during classify (Python exit 1) is BLOCKED, never "not a dashboard destination"' -Condition (
        $r.Threw -and $r.Message -match 'BLOCKED' -and $r.Message -match 'could not run') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Dest '/config/packages/example.yaml' -UsePython $crashPython
    Assert-True -Name '... also for a package destination while a site policy is present' -Condition ($r.Threw -and $r.Message -match 'could not run') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Dest '/config/packages/example.yaml' -UsePython $halfPython
    Assert-True -Name 'a classify answer with exit 4 but without the "dashboard destination: no" line and the policy list is BLOCKED' -Condition ($r.Threw -and $r.Message -match 'BLOCKED') -Detail $r.Message

    # F3: every destination the policy names must exist on the host.
    $typoPolicy = Join-Path $fixtures 'typo-policy.json'
    $ErrorActionPreference = 'Continue'
    & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination /config/ecco/dashboards/ecco_pro.yml --base $generic --live $live --pointer /views/0/sections/0/cards/0 --out $typoPolicy 2>&1 | Out-Null
    $ErrorActionPreference = $previousEap
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $typoPolicy }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'a policy whose destination is mistyped (.yml for .yaml) is BLOCKED: the named file does not exist on the host' -Condition (
        $r.Threw -and $r.Message -match 'ecco_pro\.yml, but that file does not exist on the host') -Detail $r.Message
    $otherDestination = '/config/ecco/dashboards/other.yaml'
    $script:fakeHost = @{ $otherDestination = $live; $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live -Dest $otherDestination
    Assert-True -Name 'another dashboard while the policy''s destination exists: generic layer, default gate, the policy list read' -Condition (
        -not $r.Threw -and $r.Result.GateLine -eq 'DASHBOARD_PRESERVE_GATE: PASS' -and -not $r.Result.PolicyNamesDestination -and @($r.Result.PolicyDestinations) -contains $destination) -Detail $r.Message
    $script:fakeHost = @{ $otherDestination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live -Dest $otherDestination
    Assert-True -Name '... and BLOCKED when the policy''s own destination is missing on the host' -Condition ($r.Threw -and $r.Message -match 'does not exist on the host') -Detail $r.Message

    # F4: the guard checks a private copy and the gate returns its sha256.
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live
    $liveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $live).Hash.ToLowerInvariant()
    Assert-True -Name 'the gate returns the sha256 of the candidate bytes it checked (deploy-ha.ps1 installs only that hash)' -Condition (
        -not $r.Threw -and $r.Result.CandidateSha256 -eq $liveHash -and ($r.Result.Output -join ' ') -match ('candidate \(sha256 ' + $liveHash.Substring(0, 12) + '\)')) -Detail $r.Message

    # TQ-1: the waiver covers the named type only.
    $genericNoOther = Join-Path $fixtures 'generic-no-other.yaml'
    [System.IO.File]::WriteAllText($genericNoOther, (($genericText -join "`n").Replace('custom:example-other-card', 'entities')))
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources }
    $r = Invoke-TestGate -Candidate $genericNoOther -Accept @('custom:example-site-card')
    Assert-True -Name 'no policy: accepting one dropped custom type leaves a second dropped type BLOCKED by R4' -Condition (
        $r.Threw -and $r.Message -match 'R4: the candidate drops' -and $r.Message -match '/views/0/sections/0/cards/1/type') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Accept @('custom:example-unrelated-card')
    Assert-True -Name 'no policy: accepting a type the candidate does not drop waives nothing (still BLOCKED by R4)' -Condition ($r.Threw -and $r.Message -match 'R4') -Detail $r.Message

    # Drift recovery: live drifted from the policy; the candidate (the policy's layer) restores it only with -AllowDriftRecovery.
    $drifted = Join-Path $fixtures 'live-drifted.yaml'
    [System.IO.File]::WriteAllText($drifted, (($liveText -join "`n").Replace('crossfade_ms: 900', 'crossfade_ms: 1200')))
    $script:fakeHost = @{ $destination = $drifted; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live
    Assert-True -Name 'drift: live differs from the policy, the candidate restores the policy''s layer, no -AllowDriftRecovery: BLOCKED, naming the switch' -Condition (
        $r.Threw -and $r.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $r.Message -match 'R2: live protected layer differs from the site policy' -and $r.Message -match '-AllowDriftRecovery') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $live -Drift
    Assert-True -Name 'drift recovery: with -AllowDriftRecovery the same candidate passes under the policy gate and the gate returns the WARNING lines' -Condition (
        -not $r.Threw -and $r.Result.GateLine -eq 'EXAMPLE_PRESERVE_GATE: PASS' -and @($r.Result.Warnings).Count -eq 2 -and
        @($r.Result.Warnings)[0] -match '^WARNING R2 drift: live protected layer differs from the site policy' -and @($r.Result.Warnings)[1] -match '^WARNING drift recovery') -Detail ($r.Message + ' | ' + (@($r.Result.Output) -join ' | '))
    $r = Invoke-TestGate -Candidate $drifted -Drift
    Assert-True -Name 'drift recovery never passes a candidate without the protected layer (the drifted live file itself is BLOCKED)' -Condition (
        $r.Threw -and $r.Message -match 'R2: candidate removes or replaces a protected layer') -Detail $r.Message
    $r = Invoke-TestGate -Candidate $generic -Drift -Accept @('custom:example-site-card')
    Assert-True -Name 'drift recovery with every waiver still BLOCKS the generic render (R2)' -Condition ($r.Threw -and $r.Message -match 'R2: candidate removes') -Detail $r.Message
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $r = Invoke-TestGate -Candidate $live -Drift
    Assert-True -Name '-AllowDriftRecovery without drift: PASS with no warning' -Condition (-not $r.Threw -and @($r.Result.Warnings).Count -eq 0) -Detail $r.Message

    # Gate pin: Get-EccoDashboardGatePin reads the local pin file strictly.
    $pinFile = Join-Path $fixtures 'pin.txt'
    Assert-True -Name 'gate pin: no pin file means no pin ($null)' -Condition ($null -eq (Get-EccoDashboardGatePin -Path $pinFile))
    [System.IO.File]::WriteAllText($pinFile, "# fictional site gate`r`n`r`nEXAMPLE_PRESERVE_GATE`r`n")
    Assert-True -Name 'gate pin: one gate name, comment and blank lines ignored' -Condition ((Get-EccoDashboardGatePin -Path $pinFile) -ceq 'EXAMPLE_PRESERVE_GATE')
    foreach ($badPin in @("EXAMPLE_PRESERVE_GATE`nOTHER_GATE`n", "example_preserve_gate`n", "# only a comment`n", '', "EXAMPLE PRESERVE GATE`n")) {
        [System.IO.File]::WriteAllText($pinFile, $badPin)
        $threw = $false
        try { Get-EccoDashboardGatePin -Path $pinFile | Out-Null } catch { $threw = $true }
        Assert-True -Name "gate pin: a pin file that is not exactly one gate name is refused, never 'no pin': [$($badPin.Replace("`n", '<LF>'))]" -Condition $threw
    }
    $threw = $false
    try { Get-EccoDashboardGatePin -Path $fixtures | Out-Null } catch { $threw = $true }
    Assert-True -Name 'gate pin: a folder at the pin path is refused' -Condition $threw

    # Gate pin: Assert-EccoDashboardGatePin on real gate results (fictional host).
    function Test-PinRefused {
        param([object]$GateResult, [string]$Pin)
        try {
            Assert-EccoDashboardGatePin -GateResult $GateResult -ExpectedGate $Pin -PinSource 'the test pin' | Out-Null
            return ''
        } catch {
            return $_.Exception.Message
        }
    }
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $protected = (Invoke-TestGate -Candidate $live).Result
    Assert-True -Name 'gate pin: the policy-protected destination passes under the pinned gate' -Condition (
        (Test-PinRefused $protected 'EXAMPLE_PRESERVE_GATE') -eq '' -and (Assert-EccoDashboardGatePin -GateResult $protected -ExpectedGate 'EXAMPLE_PRESERVE_GATE') -match 'matched')
    $m = Test-PinRefused $protected 'OTHER_PRESERVE_GATE'
    Assert-True -Name 'gate pin: a different pinned gate is BLOCKED' -Condition ($m -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $m -match 'OTHER_PRESERVE_GATE') -Detail $m
    Assert-True -Name 'gate pin: no pin checks nothing' -Condition ($null -eq (Assert-EccoDashboardGatePin -GateResult $protected -ExpectedGate ''))
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources }
    $movedAside = (Invoke-TestGate -Candidate $live).Result
    $m = Test-PinRefused $movedAside 'EXAMPLE_PRESERVE_GATE'
    Assert-True -Name 'gate pin: the host policy moved aside - the dashboard passes only under DASHBOARD_PRESERVE_GATE, and the pin BLOCKS it' -Condition (
        $movedAside.GateLine -eq 'DASHBOARD_PRESERVE_GATE: PASS' -and $m -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $m -match 'expects this dashboard destination to pass under EXAMPLE_PRESERVE_GATE' -and $m -match 'Nothing was written') -Detail $m
    $script:fakeHost = @{ $resourcesRemote = $resources }
    $newFile = (Invoke-TestGate -Candidate $live).Result
    Assert-True -Name 'gate pin: ... also for a new file (PASS (new file ...) under the default gate)' -Condition ((Test-PinRefused $newFile 'EXAMPLE_PRESERVE_GATE') -match 'BLOCKED')
    $script:fakeHost = @{ $otherDestination = $live; $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $unprotected = (Invoke-TestGate -Candidate $live -Dest $otherDestination).Result
    Assert-True -Name 'gate pin: a dashboard the policy does not protect is BLOCKED by the site pin, and passes with the pin DASHBOARD_PRESERVE_GATE' -Condition (
        (Test-PinRefused $unprotected 'EXAMPLE_PRESERVE_GATE') -match 'BLOCKED' -and (Test-PinRefused $unprotected 'DASHBOARD_PRESERVE_GATE') -eq '')
    Assert-True -Name 'gate pin: DASHBOARD_PRESERVE_GATE as the pin BLOCKS the policy-protected destination' -Condition ((Test-PinRefused $protected 'DASHBOARD_PRESERVE_GATE') -match 'BLOCKED')
    $script:fakeHost = @{ $resourcesRemote = $resources }
    $packageNoPolicy = (Invoke-TestGate -Candidate $live -Dest '/config/packages/example.yaml').Result
    $m = Test-PinRefused $packageNoPolicy 'EXAMPLE_PRESERVE_GATE'
    Assert-True -Name 'gate pin: any other destination needs the site policy on the host while a site gate is pinned' -Condition (
        -not $packageNoPolicy.Applies -and $m -match 'no site policy on the host' -and (Test-PinRefused $packageNoPolicy 'DASHBOARD_PRESERVE_GATE') -eq '') -Detail $m
    Assert-True -Name '... and the refusal names the one-run override (-ExpectedSiteGate DASHBOARD_PRESERVE_GATE for this deployment) and says to keep the pin, never to remove it' -Condition (
        $m -match '-ExpectedSiteGate DASHBOARD_PRESERVE_GATE for this deployment only' -and $m -match 'keep the pin' -and $m -notmatch 'remove the pin') -Detail $m
    $script:fakeHost = @{ $destination = $live; $resourcesRemote = $resources; $policyRemote = $policy }
    $packageWithPolicy = (Invoke-TestGate -Candidate $live -Dest '/config/packages/example.yaml').Result
    Assert-True -Name 'gate pin: ... and passes when the policy is present' -Condition ((Test-PinRefused $packageWithPolicy 'EXAMPLE_PRESERVE_GATE') -eq '')
    Assert-True -Name 'gate pin: a malformed pin value is BLOCKED' -Condition ((Test-PinRefused $protected 'example_preserve_gate') -match 'not a gate name')

    # Post-install verify-live.
    $script:fakeHost = @{ $destination = $live; $policyRemote = $policy }
    $v = Invoke-EccoDashboardLiveVerification -SshHost 'fictional-host' -Destination $destination -GuardPath $guard -Python $Python -RemoteFileReader $fakeReader
    Assert-True -Name 'verify-live passes when the installed file carries the protected layer' -Condition ($v.Passed -and $v.GateLine -eq 'EXAMPLE_PRESERVE_GATE: PASS') -Detail ($v.Output -join ' | ')
    $script:fakeHost = @{ $destination = $generic; $policyRemote = $policy }
    $v = Invoke-EccoDashboardLiveVerification -SshHost 'fictional-host' -Destination $destination -GuardPath $guard -Python $Python -RemoteFileReader $fakeReader
    Assert-True -Name 'verify-live fails when the installed file lost the protected layer' -Condition (-not $v.Passed) -Detail ($v.Output -join ' | ')
    $script:fakeHost = @{ $destination = $live }
    $v = Invoke-EccoDashboardLiveVerification -SshHost 'fictional-host' -Destination $destination -GuardPath $guard -Python $Python -RemoteFileReader $fakeReader
    Assert-True -Name 'verify-live fails when the policy is no longer on the host' -Condition (-not $v.Passed) -Detail ($v.Output -join ' | ')

    $gateFoldersAfter = @(Get-ChildItem -LiteralPath $tempRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $gateFolderPattern }).Count
    Assert-True -Name 'every gate run deleted its temporary folder (the copies may hold site values)' -Condition ($gateFoldersAfter -eq $gateFoldersBefore) -Detail "before $gateFoldersBefore, after $gateFoldersAfter"
}
finally {
    Remove-Item -LiteralPath $fixtures -Recurse -Force -ErrorAction SilentlyContinue
}

$deployHaText = Get-Content -Raw -Path (Join-Path $toolsDir 'deploy-ha.ps1')
$gateAt = $deployHaText.IndexOf('Invoke-EccoDashboardPreservationGate')
$writeMarkers = @("mkdir -p '", "cp -p '`$Destination'", '& scp -q $sourceFull')
$writeAt = @($writeMarkers | ForEach-Object { $deployHaText.IndexOf($_) })
$firstWrite = $writeAt | Sort-Object | Select-Object -First 1
Assert-True -Name 'deploy-ha.ps1 runs the gate before its first remote write (mkdir, backup, upload; each marker found)' -Condition ($gateAt -gt 0 -and @($writeAt | Where-Object { $_ -lt 0 }).Count -eq 0 -and $gateAt -lt $firstWrite) -Detail ($writeAt -join ',')

# ---------------------------------------------------------------------
# 13. The read-only host probe (Get-EccoGateProbeCommand): only a path
#     proven absent is "absent"; a directory, a file used as a folder or
#     a symlink is "unreadable". Run under a local POSIX sh (Git for
#     Windows) on a fictional tree in the temp folder; no host involved.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[13] The read-only host probe of the gate'
$probeCommand = Get-EccoGateProbeCommand -RemotePath '/config/ecco/site-local/dashboard-protection.json'
Assert-True -Name 'the probe is built from single-quoted words only: no double quote (5.1 would split it on the ssh command line)' -Condition (-not $probeCommand.Contains('"'))
Assert-True -Name 'the probe tests the path for a symlink first and spells out every ancestor up to /' -Condition (
    $probeCommand.StartsWith("if [ -L '/config/ecco/site-local/dashboard-protection.json' ]; then printf unreadable;") -and
    $probeCommand.Contains("[ -x '/config/ecco/site-local' ]") -and $probeCommand.Contains("[ -x '/config/ecco' ]") -and
    $probeCommand.Contains("[ -x '/config' ]") -and $probeCommand.Contains("[ -x '/' ]"))
$probeRefused = $false
try { Get-EccoGateProbeCommand -RemotePath "/config/ecco/a'b.yaml" | Out-Null } catch { $probeRefused = $true }
Assert-True -Name 'the probe refuses a path with a single quote' -Condition $probeRefused
if (-not $Sh) {
    $gitSh = 'C:\Program Files\Git\bin\sh.exe'
    if (Test-Path -LiteralPath $gitSh) { $Sh = $gitSh }
}
if ($Sh -and (Test-Path -LiteralPath $Sh)) {
    $probeRoot = '/tmp/ecco-probe-test-' + [guid]::NewGuid().ToString('N')
    $ErrorActionPreference = 'Continue'
    try {
        & $Sh -c "mkdir -p '$probeRoot/dir/sub' && printf x > '$probeRoot/dir/file'" 2>&1 | Out-Null
        $probeCases = @(
            @("$probeRoot/dir/file", 'present', 'a readable regular file'),
            @("$probeRoot/dir/missing.json", 'absent', 'nothing there, the folder is searchable'),
            @("$probeRoot/nodir/deeper/missing.json", 'absent', 'nothing there, the nearest existing ancestor is searchable'),
            @("$probeRoot/dir/sub", 'unreadable', 'a directory'),
            @("$probeRoot/dir/file/below.json", 'unreadable', 'a file used as a folder'))
        foreach ($case in $probeCases) {
            $got = (@(& $Sh -c (Get-EccoGateProbeCommand -RemotePath $case[0]) 2>&1) -join '').Trim()
            Assert-True -Name "probe: $($case[2]) -> $($case[1])" -Condition ($got -ceq $case[1]) -Detail $got
        }
        & $Sh -c "MSYS=winsymlinks:nativestrict ln -s '$probeRoot/nowhere' '$probeRoot/dir/dangling'" 2>&1 | Out-Null
        $isLink = (@(& $Sh -c "if [ -L '$probeRoot/dir/dangling' ]; then printf yes; else printf no; fi" 2>&1) -join '').Trim()
        if ($isLink -eq 'yes') {
            $got = (@(& $Sh -c (Get-EccoGateProbeCommand -RemotePath "$probeRoot/dir/dangling") 2>&1) -join '').Trim()
            Assert-True -Name 'probe: a dangling symlink -> unreadable (never absent)' -Condition ($got -ceq 'unreadable') -Detail $got
        } else {
            Write-Host '  SKIP  probe: a dangling symlink (this sh cannot create symlinks here; the case rests on the [ -L ] test checked above)'
        }

        # Amendment A26: the single-file route's checks (this probe reads the test-instance marker and the site policy)
        # read through a /config that is a symlink to a real folder, and never report "absent" below a /config that is
        # dangling, points to a file or loops. Junctions (mklink /J) stand in for symlinks.
        $a26ProbeWin = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-probe-a26-' + [guid]::NewGuid().ToString('N'))
        $a26ProbeLinks = New-Object System.Collections.Generic.List[string]
        try {
            New-Item -ItemType Directory -Path (Join-Path $a26ProbeWin 'store\real\ecco\site-local') -Force | Out-Null
            foreach ($shape in @('dangling', 'loop', 'file')) { New-Item -ItemType Directory -Path (Join-Path $a26ProbeWin $shape) -Force | Out-Null }
            [System.IO.File]::WriteAllText((Join-Path $a26ProbeWin 'store\real\ecco\site-local\dashboard-protection.json'), "{}`n")
            [System.IO.File]::WriteAllText((Join-Path $a26ProbeWin 'file\target'), "fictional`n")
            foreach ($pair in @(@('store\config', 'store\real'), @('dangling\config', 'dangling\gone'), @('loop\config', 'loop\back'), @('loop\back', 'loop\config'), @('file\config', 'file\target'))) {
                & cmd /c mklink /J (Join-Path $a26ProbeWin $pair[0]) (Join-Path $a26ProbeWin $pair[1]) 2>&1 | Out-Null
                $a26ProbeLinks.Add((Join-Path $a26ProbeWin $pair[0]))
            }
            $a26ProbeSh = (@(& $Sh -c "cygpath -u '$a26ProbeWin'" 2>&1) -join '').Trim()
            $a26IsLink = (@(& $Sh -c "if [ -L '$a26ProbeSh/store/config' ]; then printf yes; else printf no; fi" 2>&1) -join '').Trim()
            if ($a26IsLink -ne 'yes') {
                Write-Host '  SKIP  probe through a symlinked /config (mklink /J could not create a junction here, or this sh does not see it as a symlink)'
            } else {
                foreach ($case in @(
                        @("$a26ProbeSh/store/config/.ecco_l3_test_instance", 'absent', 'the marker below a /config symlinked to a real folder'),
                        @("$a26ProbeSh/store/config/ecco/site-local/dashboard-protection.json", 'present', 'the site policy below a /config symlinked to a real folder'),
                        @("$a26ProbeSh/dangling/config/.ecco_l3_test_instance", 'unreadable', 'the marker below a dangling /config'),
                        @("$a26ProbeSh/loop/config/.ecco_l3_test_instance", 'unreadable', 'the marker below a /config symlink loop'),
                        @("$a26ProbeSh/file/config/.ecco_l3_test_instance", 'unreadable', 'the marker below a /config symlinked to a file'))) {
                    $got = (@(& $Sh -c (Get-EccoGateProbeCommand -RemotePath $case[0]) 2>&1) -join '').Trim()
                    Assert-True -Name "A26 probe (the single-file route's checks): $($case[2]) -> $($case[1])" -Condition ($got -ceq $case[1]) -Detail $got
                }
            }
        }
        finally {
            foreach ($j in $a26ProbeLinks) { & cmd /c rmdir $j 2>&1 | Out-Null }
            Remove-Item -LiteralPath $a26ProbeWin -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    finally {
        & $Sh -c "rm -rf '$probeRoot'" 2>&1 | Out-Null
        $ErrorActionPreference = 'Stop'
    }
} else {
    Write-Host '  SKIP  probe runs under a POSIX sh (no Git for Windows sh found; pass -Sh <sh.exe>)'
}

# ---------------------------------------------------------------------
# 14. deploy-ha.ps1 itself against a stubbed host: ssh and scp are
#     replaced in-process by functions that serve fictional files to the
#     gate's reads and refuse every other command. A BLOCKED gate must
#     stop the script with nothing but those reads sent; a PASS lets it
#     reach its next host command (which the stub refuses), proving the
#     harness would see a write. deploy-ha.ps1 runs from a copy of the
#     tooling under its own temporary repository root (New-StubRepo), so
#     an owner's pin file in this checkout never changes a run and no run
#     writes into the checkout.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[14] deploy-ha.ps1 against a stubbed host: a BLOCKED gate sends nothing but its reads'

# A copy of deploy-ha.ps1, EccoDeploy.psm1 and the guard (this checkout's
# bytes) under a temporary repository root with an empty dist\stub folder for
# the sources. deploy-ha.ps1 finds its repository root, and so the local pin
# file ecco_dashboard_gate.local.txt, from its own folder.
function New-StubRepo {
    param([string]$Root)
    New-Item -ItemType Directory -Path (Join-Path $Root 'tools') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root 'dist\stub') -Force | Out-Null
    foreach ($file in @('deploy-ha.ps1', 'EccoDeploy.psm1', 'ecco_dashboard_guard.py')) {
        Copy-Item -LiteralPath (Join-Path $toolsDir $file) -Destination (Join-Path $Root 'tools')
    }
    return (Resolve-Path -LiteralPath $Root).Path
}

# The copy runs this checkout's code, from outside the checkout.
function Test-StubRepo {
    param([string]$Root)
    $same = $true
    foreach ($file in @('deploy-ha.ps1', 'EccoDeploy.psm1', 'ecco_dashboard_guard.py')) {
        $a = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $toolsDir $file)).Hash
        $b = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path (Join-Path $Root 'tools') $file)).Hash
        $same = $same -and ($a -eq $b)
    }
    $inside = ($Root.TrimEnd('\') + '\').StartsWith($repoRoot.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)
    return ($same -and -not $inside)
}

$stubBase = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-gate-test-' + [guid]::NewGuid().ToString('N'))
$stubHostDir = Join-Path $stubBase 'host'
$stubRepo = New-StubRepo -Root (Join-Path $stubBase 'repo')
New-Item -ItemType Directory -Path $stubHostDir | Out-Null
$global:EccoTestRemoteLog = New-Object System.Collections.Generic.List[string]
try {
    $stubLive = Join-Path $stubHostDir 'live.yaml'
    $stubResources = Join-Path $stubHostDir 'lovelace_resources'
    $stubSources = Join-Path $stubRepo 'dist\stub'
    [System.IO.File]::WriteAllText($stubLive, ($liveText -join "`n"))
    [System.IO.File]::WriteAllText($stubResources, '{"version": 1, "key": "lovelace_resources", "data": {"items": []}}')
    [System.IO.File]::WriteAllText((Join-Path $stubSources 'generic.yaml'), ($genericText -join "`n"))
    [System.IO.File]::WriteAllText((Join-Path $stubSources 'same.yaml'), ($liveText -join "`n"))
    $global:EccoTestHost = @{ $destination = $stubLive; $resourcesRemote = $stubResources }
    $realPinPath = Get-EccoDashboardGatePinPath -RepoRoot $repoRoot
    Assert-True -Name 'the stub runs use a copy of deploy-ha.ps1, EccoDeploy.psm1 and the guard (this checkout''s bytes) under their own repository root outside the checkout, so this checkout''s pin file is never read' -Condition (
        Test-StubRepo -Root $stubRepo)
    if (Test-Path -LiteralPath $realPinPath) {
        Write-Host '  info  this checkout has its own ecco_dashboard_gate.local.txt: the stub runs never read it, and it is left untouched'
    }

    function global:ssh {
        $command = [string]$args[$args.Count - 1]
        $global:LASTEXITCODE = 0
        if ($args -ccontains '-G') {
            # ssh -G (the -Target guard's loopback check): configuration only.
            $global:EccoTestRemoteLog.Add('ssh -G ' + $command)
            return 'hostname fictional.example.invalid'
        }
        $global:EccoTestRemoteLog.Add('ssh ' + $command)
        if ($command -ceq 'true') { return }
        if ($command -ceq 'ha core info --raw-json') { return '{"result": "ok", "data": {"machine": "example-machine"}}' }
        if ($command -cmatch "^if \[ -L '([^']+)' \]; then printf unreadable;") {
            if ($global:EccoTestHost.ContainsKey($Matches[1])) { return 'present' }
            return 'absent'
        }
        $global:LASTEXITCODE = 1
        return 'stubbed host: command refused'
    }
    function global:scp {
        $global:EccoTestRemoteLog.Add('scp ' + ($args -join ' '))
        $from = [string]$args[$args.Count - 2]
        $to = [string]$args[$args.Count - 1]
        if ($from -cmatch '^fictional-host:(/.+)$' -and $global:EccoTestHost.ContainsKey($Matches[1])) {
            Copy-Item -LiteralPath $global:EccoTestHost[$Matches[1]] -Destination $to
            $global:LASTEXITCODE = 0
            return
        }
        $global:LASTEXITCODE = 1
    }

    $deployHa = Join-Path $stubRepo 'tools\deploy-ha.ps1'
    # The gate's reads, plus the -Target guard's: ssh -G (local configuration only), the marker probe (an "if [ -L" probe) and
    # ha core info --raw-json.
    $gateReads ={ param($entry) ($entry -ceq 'ssh true') -or $entry.StartsWith("ssh if [ -L '") -or ($entry -cmatch '^scp -q fictional-host:/') -or
        ($entry -ceq 'ssh -G fictional-host') -or ($entry -ceq 'ssh ha core info --raw-json') }

    $global:EccoTestRemoteLog.Clear()
    $blockedMessage = ''
    try {
        & $deployHa -Source "dist/stub/generic.yaml" -Destination $destination -SshHost 'fictional-host' -Target Production -SkipValidation -AllowDirtyWorkingTree -Python $Python 6>$null 3>$null | Out-Null
    } catch {
        $blockedMessage = $_.Exception.Message
    }
    $sent = @($global:EccoTestRemoteLog)
    $notReads = @($sent | Where-Object { -not (& $gateReads $_) })
    Assert-True -Name 'deploy-ha.ps1 with a generic render over a customised live file stops with the gate''s BLOCKED message' -Condition (
        $blockedMessage -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $blockedMessage -match 'R4') -Detail $blockedMessage
    Assert-True -Name '... having sent the host only the SSH probe and the gate''s read-only probes and copies (no mkdir, backup, upload or move)' -Condition (
        $sent.Count -ge 3 -and $notReads.Count -eq 0) -Detail ($notReads -join ' | ')

    $global:EccoTestRemoteLog.Clear()
    $passMessage = ''
    try {
        & $deployHa -Source "dist/stub/same.yaml" -Destination $destination -SshHost 'fictional-host' -Target Production -SkipValidation -AllowDirtyWorkingTree -Python $Python 6>$null 3>$null | Out-Null
    } catch {
        $passMessage = $_.Exception.Message
    }
    $sent = @($global:EccoTestRemoteLog)
    Assert-True -Name 'control: a candidate the gate passes reaches deploy-ha.ps1''s next host command (refused by the stub), so the harness sees writes' -Condition (
        $passMessage -match 'Unable to inspect existing remote file' -and @($sent | Where-Object { $_.StartsWith("ssh if [ -f '") }).Count -eq 1) -Detail ($passMessage + ' | ' + ($sent -join ' | '))

    # One deploy-ha.ps1 run: the terminating message and every host command sent (the warning stream is collected too).
    function Invoke-StubDeploy {
        param([string]$File, [hashtable]$Extra = @{})
        $global:EccoTestRemoteLog.Clear()
        $global:EccoTestWarnings = New-Object System.Collections.Generic.List[string]
        $message = ''
        try {
            & $deployHa -Source "dist/stub/$File" -Destination $destination -SshHost 'fictional-host' -Target Production -SkipValidation -AllowDirtyWorkingTree -Python $Python @Extra 3>&1 6>$null |
                ForEach-Object { if ($_ -is [System.Management.Automation.WarningRecord]) { $global:EccoTestWarnings.Add($_.Message) } }
        } catch {
            $message = $_.Exception.Message
        }
        $sent = @($global:EccoTestRemoteLog)
        return [pscustomobject]@{ Message = $message; Sent = $sent; NotReads = @($sent | Where-Object { -not (& $gateReads $_) }); Warnings = @($global:EccoTestWarnings) }
    }

    # Gate pin: the host has no site policy (moved aside), so the dashboard passes only under DASHBOARD_PRESERVE_GATE.
    $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE' }
    Assert-True -Name 'deploy-ha.ps1 -ExpectedSiteGate: a dashboard that passes only under DASHBOARD_PRESERVE_GATE (host policy moved aside) is BLOCKED by the pin' -Condition (
        $run.Message -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $run.Message -match '-ExpectedSiteGate expects this dashboard destination to pass under EXAMPLE_PRESERVE_GATE') -Detail $run.Message
    Assert-True -Name '... having sent the host nothing but the gate''s reads (no mkdir, backup, upload or move)' -Condition ($run.Sent.Count -ge 3 -and $run.NotReads.Count -eq 0) -Detail ($run.NotReads -join ' | ')
    $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'DASHBOARD_PRESERVE_GATE' }
    Assert-True -Name 'control: -ExpectedSiteGate DASHBOARD_PRESERVE_GATE (a deliberately unprotected dashboard) reaches the next host command' -Condition (
        $run.Message -match 'Unable to inspect existing remote file') -Detail $run.Message
    $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'example_preserve_gate' }
    Assert-True -Name 'deploy-ha.ps1 -ExpectedSiteGate takes an upper-case gate name only (case-sensitive validation), before anything is sent' -Condition (
        $run.Message -match 'ExpectedSiteGate' -and $run.Sent.Count -eq 0) -Detail $run.Message
    # The local pin file: checked by name against this checkout's .gitignore (nothing is written here), and run at the copied
    # tree's root, which is the root deploy-ha.ps1 reads it from.
    $ErrorActionPreference = 'Continue'
    & git -C $repoRoot check-ignore -q -- ([System.IO.Path]::GetFileName($realPinPath)) 2>&1 | Out-Null
    $pinIgnored = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    Assert-True -Name 'the local pin file is git-ignored in this checkout (checked by name)' -Condition $pinIgnored
    $pinPath = Get-EccoDashboardGatePinPath -RepoRoot $stubRepo
    try {
        [System.IO.File]::WriteAllText($pinPath, "EXAMPLE_PRESERVE_GATE`n")
        $run = Invoke-StubDeploy -File 'same.yaml'
        Assert-True -Name 'deploy-ha.ps1 reads the local pin file at its repository root when -ExpectedSiteGate is not given: the same deployment is BLOCKED, naming the pin file' -Condition (
            $run.Message -match '^DASHBOARD_PRESERVE_GATE: BLOCKED' -and $run.Message -match 'the local pin file ecco_dashboard_gate\.local\.txt expects' -and $run.NotReads.Count -eq 0) -Detail $run.Message
        $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'DASHBOARD_PRESERVE_GATE' }
        Assert-True -Name '... and -ExpectedSiteGate takes precedence over the pin file' -Condition ($run.Message -match 'Unable to inspect existing remote file') -Detail $run.Message
        [System.IO.File]::WriteAllText($pinPath, "not a gate`n")
        $run = Invoke-StubDeploy -File 'same.yaml'
        Assert-True -Name 'a malformed local pin file stops deploy-ha.ps1 before it contacts the host' -Condition (
            $run.Message -match 'must hold exactly one gate name' -and $run.Sent.Count -eq 0) -Detail ($run.Message + ' | ' + ($run.Sent -join ' | '))
    }
    finally {
        Remove-Item -LiteralPath $pinPath -Force -ErrorAction SilentlyContinue
    }

    # Drift recovery through deploy-ha.ps1: the host's live file drifted from its policy; the candidate is the policy's layer.
    $stubPolicy = Join-Path $stubHostDir 'policy.json'
    $stubDrifted = Join-Path $stubHostDir 'drifted.yaml'
    $ErrorActionPreference = 'Continue'
    & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $destination --base (Join-Path $stubSources 'generic.yaml') --live $stubLive --pointer /views/0/sections/0/cards/0 --out $stubPolicy 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
    [System.IO.File]::WriteAllText($stubDrifted, (($liveText -join "`n").Replace('crossfade_ms: 900', 'crossfade_ms: 1200')))
    $global:EccoTestHost = @{ $destination = $stubDrifted; $resourcesRemote = $stubResources; $policyRemote = $stubPolicy }
    $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE' }
    Assert-True -Name 'deploy-ha.ps1, live drifted from the policy: the candidate that restores the policy''s layer is BLOCKED without -AllowDriftRecovery (nothing but reads sent)' -Condition (
        $run.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $run.Message -match 'live protected layer differs' -and $run.NotReads.Count -eq 0) -Detail $run.Message
    $run = Invoke-StubDeploy -File 'same.yaml' -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE'; AllowDriftRecovery = $true }
    Assert-True -Name 'deploy-ha.ps1 -AllowDriftRecovery: the gate passes (the pinned gate matches) and the run goes on to its next host command' -Condition (
        $run.Message -match 'Unable to inspect existing remote file') -Detail $run.Message
    Assert-True -Name '... printing the drift as PowerShell warnings' -Condition (
        @($run.Warnings | Where-Object { $_ -match '^Dashboard preservation gate: WARNING R2 drift' }).Count -eq 1 -and
        @($run.Warnings | Where-Object { $_ -match '^Dashboard preservation gate: WARNING drift recovery' }).Count -eq 1) -Detail ($run.Warnings -join ' | ')
    $run = Invoke-StubDeploy -File 'generic.yaml' -Extra @{ AllowDriftRecovery = $true; AcceptRemovedCardType = @('custom:example-site-card') }
    Assert-True -Name 'deploy-ha.ps1 -AllowDriftRecovery never passes the generic render over the drifted live file (R2, nothing but reads sent)' -Condition (
        $run.Message -match '^EXAMPLE_PRESERVE_GATE: BLOCKED' -and $run.Message -match 'candidate removes or replaces a protected layer' -and $run.NotReads.Count -eq 0) -Detail $run.Message
}
finally {
    Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath function:global:scp -ErrorAction SilentlyContinue
    Remove-Variable -Name EccoTestRemoteLog, EccoTestHost -Scope Global -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stubBase -Recurse -Force -ErrorAction SilentlyContinue
    # deploy-ha.ps1 re-imported the module from the copy: use the checkout's own again.
    Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force
}

# ---------------------------------------------------------------------
# 15. Invoke-EccoDeploymentRollback against a stubbed host: every
#     command is recorded, and (with a local POSIX sh) run on a fictional
#     /config tree in the temp folder. Home Assistant keeps serving its
#     cached YAML dashboard while the file is not newer than that cache, so
#     the restored file must get a new modification time (no cp -p), and a
#     dashboard rollback must ask for a lovelace/config read-back.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[15] Rollback: the restored file is newer than the cache, and a dashboard rollback asks for a read-back'
$global:EccoTestRemoteLog = New-Object System.Collections.Generic.List[string]
$global:EccoTestSh = $Sh
$global:EccoTestShRoot = $null
if ($Sh -and (Test-Path -LiteralPath $Sh)) {
    $global:EccoTestShRoot = '/tmp/ecco-rollback-test-' + [guid]::NewGuid().ToString('N')
}
try {
    function global:ssh {
        $command = [string]$args[$args.Count - 1]
        $global:EccoTestRemoteLog.Add($command)
        $global:LASTEXITCODE = 0
        if ($command -ceq 'ha core check') { return 'Command completed successfully.' }
        if (-not $global:EccoTestShRoot) { return }
        # Every path the rollback names is absolute under /config: run it on the fictional tree.
        $local = $command.Replace("'/config/", "'" + $global:EccoTestShRoot + '/config/')
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $out = @(& $global:EccoTestSh -c $local 2>&1 | ForEach-Object { [string]$_ })
        } finally {
            $ErrorActionPreference = $previousEap
        }
        return $out
    }

    $rbDest = '/config/ecco/dashboards/example.yaml'
    $rbBackup = '/config/ecco-backups/20010101-000000/config__ecco__dashboards__example.yaml'
    $rbRoot = $global:EccoTestShRoot
    $cacheTime = $null
    if ($rbRoot) {
        $ErrorActionPreference = 'Continue'
        & $Sh -c "mkdir -p '$rbRoot/config/ecco/dashboards' '$rbRoot/config/ecco-backups/20010101-000000' && printf 'title: before\n' > '$rbRoot$rbBackup' && touch -d '2001-01-01 00:00:00' '$rbRoot$rbBackup' && printf 'title: failed deployment\n' > '$rbRoot$rbDest'" 2>&1 | Out-Null
        # The moment Home Assistant cached the failed deployment's dashboard (after the install, before the rollback).
        $cacheTime = [long]((@(& $Sh -c 'date +%s' 2>&1) -join '').Trim())
        $ErrorActionPreference = 'Stop'
    }

    $rbMessage = ''
    try {
        Invoke-EccoDeploymentRollback -SshHost 'fictional-host' -Destination $rbDest -BackupPath $rbBackup -HadOriginal $true -Reason 'test: ha core check failed' 3>$null 6>$null | Out-Null
    } catch {
        $rbMessage = $_.Exception.Message
    }
    $restore = @($global:EccoTestRemoteLog | Where-Object { $_.StartsWith('cp ') })
    Assert-True -Name 'the rollback restores with a plain cp followed by touch, never cp -p (which would bring back the backup''s old modification time)' -Condition (
        $restore.Count -eq 1 -and $restore[0] -ceq "cp '$rbBackup' '$rbDest' && touch '$rbDest'" -and
        @($global:EccoTestRemoteLog | Where-Object { $_ -match 'cp -p|cp -a|--preserve' }).Count -eq 0) -Detail ($global:EccoTestRemoteLog -join ' | ')
    Assert-True -Name 'a dashboard rollback (by its path) ends with the lovelace/config read-back reminder' -Condition (
        $rbMessage -match 'DASHBOARD READ-BACK REQUIRED' -and $rbMessage -match 'websocket lovelace/config') -Detail $rbMessage
    if ($rbRoot) {
        $ErrorActionPreference = 'Continue'
        $restoredText = (@(& $Sh -c "cat '$rbRoot$rbDest'" 2>&1) -join '').Trim()
        $restoredTime = [long]((@(& $Sh -c "stat -c %Y '$rbRoot$rbDest'" 2>&1) -join '').Trim())
        $ErrorActionPreference = 'Stop'
        Assert-True -Name 'on a fictional tree (POSIX sh): the rollback restored the backup''s bytes and confirmed it ("was rolled back")' -Condition (
            $restoredText -ceq 'title: before' -and $rbMessage -match 'was rolled back') -Detail "$restoredText | $rbMessage"
        Assert-True -Name '... and the restored dashboard is not older than Home Assistant''s cache of the failed deployment, so it is served again (not the 2001 time of the backup)' -Condition (
            $restoredTime -ge $cacheTime) -Detail "restored mtime $restoredTime, cache time $cacheTime"
    } else {
        Write-Host '  SKIP  the rollback on a fictional tree runs under a POSIX sh (no Git for Windows sh found; pass -Sh <sh.exe>)'
    }

    $global:EccoTestRemoteLog.Clear()
    $rbMessage = ''
    try {
        Invoke-EccoDeploymentRollback -SshHost 'fictional-host' -Destination '/config/packages/example.yaml' -BackupPath '' -HadOriginal $false -Reason 'test: new package file' 3>$null 6>$null | Out-Null
    } catch {
        $rbMessage = $_.Exception.Message
    }
    Assert-True -Name 'a package rollback has no dashboard read-back line' -Condition ($rbMessage -match 'Deployment failed' -and $rbMessage -notmatch 'READ-BACK') -Detail $rbMessage
    $rbMessage = ''
    try {
        Invoke-EccoDeploymentRollback -SshHost 'fictional-host' -Destination '/config/ecco/views/overview.yaml' -BackupPath '' -HadOriginal $false -Dashboard -Reason 'test: policy-named dashboard' 3>$null 6>$null | Out-Null
    } catch {
        $rbMessage = $_.Exception.Message
    }
    Assert-True -Name 'a dashboard outside /config/ecco/dashboards/ (-Dashboard, as deploy-ha.ps1 passes when the gate applied) gets the read-back line' -Condition ($rbMessage -match 'DASHBOARD READ-BACK REQUIRED') -Detail $rbMessage
    $rbMessage = ''
    try {
        Invoke-EccoDeploymentRollback -SshHost 'fictional-host' -Destination $rbDest -BackupPath $rbBackup -HadOriginal $true -DriftRecovery -Reason 'test: drift recovery' 3>$null 6>$null | Out-Null
    } catch {
        $rbMessage = $_.Exception.Message
    }
    Assert-True -Name 'Invoke-EccoDeploymentRollback -DriftRecovery adds the DRIFT RECOVERY ROLLED BACK line (the restored backup is the drifted file)' -Condition (
        $rbMessage -match 'DRIFT RECOVERY ROLLED BACK' -and $rbMessage -match 'DASHBOARD READ-BACK REQUIRED') -Detail $rbMessage
}
finally {
    Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
    if ($global:EccoTestShRoot) {
        $ErrorActionPreference = 'Continue'
        & $Sh -c "rm -rf '$($global:EccoTestShRoot)'" 2>&1 | Out-Null
        $ErrorActionPreference = 'Stop'
    }
    Remove-Variable -Name EccoTestRemoteLog, EccoTestSh, EccoTestShRoot -Scope Global -ErrorAction SilentlyContinue
}
$deployHaText = Get-Content -Raw -Path (Join-Path $toolsDir 'deploy-ha.ps1')
Assert-True -Name 'deploy-ha.ps1 passes -Dashboard (the gate applied) and -DriftRecovery (the gate passed a drift recovery) to every rollback' -Condition (
    ([regex]::Matches($deployHaText, 'Invoke-EccoDeploymentRollback ')).Count -eq 4 -and
    ([regex]::Matches($deployHaText, [regex]::Escape('-HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -DriftRecovery:$driftRecovery -Reason '))).Count -eq 4)
Assert-True -Name 'L3W-6: deploy-ha.ps1 passes the backup folder''s note (-NewFileBackupNote) to every rollback, so a new file''s rollback never says a bare "Backup: none (new file)"' -Condition (
    ([regex]::Matches($deployHaText, [regex]::Escape('-BackupPath $backupPath -NewFileBackupNote $newFileBackupNote -HadOriginal $hadOriginal -Dashboard:'))).Count -eq 4)

# ---------------------------------------------------------------------
# 16. deploy-ha.ps1 end to end on a fictional /config tree: the stubbed
#     ssh runs each command under the local POSIX sh with /config mapped
#     to a temp folder, the stubbed scp copies to and from that folder,
#     and `ha core check` is stubbed (pass, or fail once). deploy-ha.ps1
#     runs from a copied tools tree (New-StubRepo). A drift recovery
#     reaches the ECCO DEPLOYMENT PASSED block with its Drift line; when
#     the check fails, the rollback restores the drifted file and says so.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[16] deploy-ha.ps1 end to end on a fictional /config tree: drift recovery, its PASSED block and its rollback'
$e2eBase = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-deploy-e2e-' + [guid]::NewGuid().ToString('N'))
$e2eTreeSh = $null
if ($Sh -and (Test-Path -LiteralPath $Sh)) {
    New-Item -ItemType Directory -Path $e2eBase | Out-Null
    $e2eBase = (Resolve-Path -LiteralPath $e2eBase).Path
    $ErrorActionPreference = 'Continue'
    $e2eTreeSh = (@(& $Sh -c "cygpath -u '$e2eBase\host'" 2>&1) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $e2eTreeSh.StartsWith('/') -or $e2eTreeSh.Contains("'")) { $e2eTreeSh = $null }
    $ErrorActionPreference = 'Stop'
}
if ($e2eTreeSh) {
    $global:EccoTestSh = $Sh
    $global:EccoTestTreeWin = Join-Path $e2eBase 'host'
    $global:EccoTestTreeSh = $e2eTreeSh
    $global:EccoTestCheckFailures = 0
    try {
        function global:ssh {
            $command = [string]$args[$args.Count - 1]
            if ($args -ccontains '-G') {
                $global:LASTEXITCODE = 0
                return 'hostname fictional.example.invalid'
            }
            if ($command -ceq 'ha core info --raw-json') {
                $global:LASTEXITCODE = 0
                return '{"result": "ok", "data": {"machine": "example-machine"}}'
            }
            if ($command -ceq 'ha core check') {
                if ($global:EccoTestCheckFailures -gt 0) {
                    $global:EccoTestCheckFailures--
                    $global:LASTEXITCODE = 1
                    return 'fictional host: configuration check failed'
                }
                $global:LASTEXITCODE = 0
                return 'Command completed successfully.'
            }
            # Every path deploy-ha.ps1 and the gate name is absolute under /config (the probe also names /config itself).
            $local = [regex]::Replace($command, "'/config(?=[/'])", "'" + $global:EccoTestTreeSh + '/config')
            $previousEap = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                $out = @(& $global:EccoTestSh -c $local 2>&1 | ForEach-Object { [string]$_ })
                $code = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $previousEap
            }
            $global:LASTEXITCODE = $code
            return $out
        }
        function global:scp {
            $from = [string]$args[$args.Count - 2]
            $to = [string]$args[$args.Count - 1]
            $global:LASTEXITCODE = 1
            try {
                if ($from -cmatch '^fictional-host:/(config/.+)$') {
                    Copy-Item -LiteralPath (Join-Path $global:EccoTestTreeWin $Matches[1].Replace('/', '\')) -Destination $to -ErrorAction Stop
                    $global:LASTEXITCODE = 0
                } elseif ($to -cmatch '^fictional-host:/(config/.+)$') {
                    Copy-Item -LiteralPath $from -Destination (Join-Path $global:EccoTestTreeWin $Matches[1].Replace('/', '\')) -ErrorAction Stop
                    $global:LASTEXITCODE = 0
                }
            } catch {
                $global:LASTEXITCODE = 1
            }
        }

        $e2eRepo = New-StubRepo -Root (Join-Path $e2eBase 'repo')
        $e2eDeployHa = Join-Path $e2eRepo 'tools\deploy-ha.ps1'
        $layerText = $liveText -join "`n"
        $driftedText = $layerText.Replace('crossfade_ms: 900', 'crossfade_ms: 1200')
        [System.IO.File]::WriteAllText((Join-Path $e2eRepo 'dist\stub\same.yaml'), $layerText)
        $e2eGeneric = Join-Path $e2eBase 'generic.yaml'
        $e2eLayer = Join-Path $e2eBase 'layer.yaml'
        $e2ePolicy = Join-Path $e2eBase 'policy.json'
        [System.IO.File]::WriteAllText($e2eGeneric, ($genericText -join "`n"))
        [System.IO.File]::WriteAllText($e2eLayer, $layerText)
        $ErrorActionPreference = 'Continue'
        & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $destination --base $e2eGeneric --live $e2eLayer --pointer /views/0/sections/0/cards/0 --out $e2ePolicy 2>&1 | Out-Null
        $ErrorActionPreference = 'Stop'
        $e2eLive = Join-Path $global:EccoTestTreeWin ($destination.Substring(1).Replace('/', '\'))

        # A fresh fictional host: the live dashboard, the site policy and an empty resource list.
        function Reset-E2eHost {
            param([string]$LiveText)
            Remove-Item -LiteralPath $global:EccoTestTreeWin -Recurse -Force -ErrorAction SilentlyContinue
            foreach ($dir in @('config\ecco\dashboards', 'config\ecco\site-local', 'config\.storage')) {
                New-Item -ItemType Directory -Path (Join-Path $global:EccoTestTreeWin $dir) -Force | Out-Null
            }
            [System.IO.File]::WriteAllText($e2eLive, $LiveText)
            Copy-Item -LiteralPath $e2ePolicy -Destination (Join-Path $global:EccoTestTreeWin 'config\ecco\site-local\dashboard-protection.json')
            [System.IO.File]::WriteAllText((Join-Path $global:EccoTestTreeWin 'config\.storage\lovelace_resources'), '{"version": 1, "key": "lovelace_resources", "data": {"items": []}}')
        }
        # One deploy-ha.ps1 run of the policy's layer under the pinned site gate: every output line, the terminating message, the installed bytes.
        function Invoke-E2eDeploy {
            param([string]$LiveText, [int]$CheckFailures = 0, [hashtable]$Extra = @{})
            Reset-E2eHost -LiveText $LiveText
            $global:EccoTestCheckFailures = $CheckFailures
            $lines = New-Object System.Collections.Generic.List[string]
            $message = ''
            try {
                & $e2eDeployHa -Source 'dist/stub/same.yaml' -Destination $destination -SshHost 'fictional-host' -Target Production -SkipValidation -AllowDirtyWorkingTree -Python $Python -ExpectedSiteGate EXAMPLE_PRESERVE_GATE @Extra *>&1 |
                    ForEach-Object { $lines.Add([string]$_) }
            } catch {
                $message = $_.Exception.Message
            }
            return [pscustomobject]@{ Message = $message; Lines = @($lines); Installed = [System.IO.File]::ReadAllText($e2eLive) }
        }

        Assert-True -Name 'the end-to-end runs use a copy of the tooling outside this checkout, and the fictional policy was made' -Condition (
            (Test-StubRepo -Root $e2eRepo) -and (Test-Path -LiteralPath $e2ePolicy))

        $run = Invoke-E2eDeploy -LiveText $driftedText -Extra @{ AllowDriftRecovery = $true }
        $driftLines = @($run.Lines | Where-Object { $_.StartsWith('Drift       : RECOVERED - ') })
        $backupText = $null
        if ($driftLines.Count -eq 1 -and $driftLines[0] -cmatch 'the drifted file is the backup /(config/ecco-backups/\S+)$') {
            $backupFile = Join-Path $global:EccoTestTreeWin $Matches[1].Replace('/', '\')
            if (Test-Path -LiteralPath $backupFile) { $backupText = [System.IO.File]::ReadAllText($backupFile) }
        }
        Assert-True -Name 'deploy-ha.ps1 -AllowDriftRecovery over a drifted live file: ECCO DEPLOYMENT PASSED, the policy''s layer installed, verify-live and the pin matched' -Condition (
            $run.Message -eq '' -and @($run.Lines | Where-Object { $_ -ceq 'ECCO DEPLOYMENT PASSED' }).Count -eq 1 -and $run.Installed -ceq $layerText -and
            @($run.Lines | Where-Object { $_ -ceq 'Post-install: EXAMPLE_PRESERVE_GATE: PASS (verify-live)' }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -ceq 'Gate pin    : EXAMPLE_PRESERVE_GATE (-ExpectedSiteGate) - matched' }).Count -eq 2) -Detail ($run.Message + ' | ' + ($run.Lines -join ' | '))
        Assert-True -Name '... and its PASSED block has the line "Drift       : RECOVERED - ...", naming the backup that holds the drifted file' -Condition (
            $driftLines.Count -eq 1 -and $backupText -ceq $driftedText) -Detail ($driftLines -join ' | ')

        $run = Invoke-E2eDeploy -LiveText $layerText -Extra @{ AllowDriftRecovery = $true }
        Assert-True -Name 'deploy-ha.ps1 -AllowDriftRecovery without drift: PASSED, and no Drift line (the switch alone recovers nothing)' -Condition (
            $run.Message -eq '' -and @($run.Lines | Where-Object { $_ -ceq 'ECCO DEPLOYMENT PASSED' }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_.StartsWith('Drift') }).Count -eq 0) -Detail ($run.Message + ' | ' + ($run.Lines -join ' | '))

        $run = Invoke-E2eDeploy -LiveText $driftedText -CheckFailures 1 -Extra @{ AllowDriftRecovery = $true }
        Assert-True -Name 'a drift recovery whose ha core check fails is rolled back to the drifted file, and the message says it lacks the policy''s layer (DRIFT RECOVERY ROLLED BACK)' -Condition (
            $run.Message -match 'was rolled back' -and $run.Message -match 'DRIFT RECOVERY ROLLED BACK' -and $run.Message -match 'DASHBOARD READ-BACK REQUIRED' -and
            $run.Installed -ceq $driftedText -and @($run.Lines | Where-Object { $_ -ceq 'ECCO DEPLOYMENT PASSED' }).Count -eq 0) -Detail $run.Message

        $run = Invoke-E2eDeploy -LiveText $layerText -CheckFailures 1
        Assert-True -Name 'any other dashboard deployment whose ha core check fails is rolled back without the drift line' -Condition (
            $run.Message -match 'was rolled back' -and $run.Message -match 'DASHBOARD READ-BACK REQUIRED' -and $run.Message -notmatch 'DRIFT' -and
            $run.Installed -ceq $layerText) -Detail $run.Message

        # Review L3W-6 (amendment A49): a new file has no backup, but the run created its backup folder (and copies the
        # Lovelace resource list into it when the host has one). "Backup: none (new file)" never stands alone beside that
        # folder: the PASSED block and the rollback message name it as kept and say what this run put in it.
        $newDest = '/config/packages/example_new_package.yaml'
        $newDestWin = Join-Path $global:EccoTestTreeWin ($newDest.Substring(1).Replace('/', '\'))
        function Invoke-E2eNewFile {
            param([switch]$NoResources, [int]$CheckFailures = 0)
            Reset-E2eHost -LiveText $layerText
            if ($NoResources) {
                Remove-Item -LiteralPath (Join-Path $global:EccoTestTreeWin 'config\.storage\lovelace_resources') -Force
            }
            $global:EccoTestCheckFailures = $CheckFailures
            $lines = New-Object System.Collections.Generic.List[string]
            $message = ''
            try {
                & $e2eDeployHa -Source 'dist/stub/same.yaml' -Destination $newDest -SshHost 'fictional-host' -Target Production -SkipValidation -AllowDirtyWorkingTree -Python $Python *>&1 |
                    ForEach-Object { $lines.Add([string]$_) }
            } catch {
                $message = $_.Exception.Message
            }
            $folders = @(Get-ChildItem -LiteralPath (Join-Path $global:EccoTestTreeWin 'config\ecco-backups') -Directory -ErrorAction SilentlyContinue)
            $stamp = if ($folders.Count -eq 1) { $folders[0].Name } else { '' }
            $held = if ($stamp) { @(Get-ChildItem -LiteralPath $folders[0].FullName -Force | ForEach-Object { $_.Name }) } else { @() }
            return [pscustomobject]@{ Message = $message; Lines = @($lines); Stamp = $stamp; Held = $held; Placed = (Test-Path -LiteralPath $newDestWin) }
        }
        $run = Invoke-E2eNewFile
        Assert-True -Name 'L3W-6: deploy-ha.ps1, a new file on a host with a Lovelace resource list: PASSED, and the Backup line names the kept backup folder holding only that list''s copy (never a bare "none (new file)")' -Condition (
            $run.Message -eq '' -and $run.Placed -and $run.Stamp -and @($run.Held).Count -eq 1 -and @($run.Held)[0] -ceq 'config__.storage__lovelace_resources' -and
            @($run.Lines | Where-Object { $_ -ceq "Backup      : none (new file); the backup folder /config/ecco-backups/$($run.Stamp) is kept; this run copied only the Lovelace resource list into it" }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -ceq 'Backup      : none (new file)' }).Count -eq 0) -Detail ($run.Message + ' | ' + (@($run.Lines | Where-Object { $_.StartsWith('Backup') }) -join ' | ') + ' | held: ' + (@($run.Held) -join ','))
        $run = Invoke-E2eNewFile -NoResources
        Assert-True -Name 'L3W-6: deploy-ha.ps1, a new file on a host without a Lovelace resource list: PASSED, the backup folder kept and empty, and the Backup line says this run copied nothing into it' -Condition (
            $run.Message -eq '' -and $run.Placed -and $run.Stamp -and @($run.Held).Count -eq 0 -and
            @($run.Lines | Where-Object { $_ -ceq "Backup      : none (new file); the backup folder /config/ecco-backups/$($run.Stamp) is kept; this run copied nothing into it (no Lovelace resource list on the host)" }).Count -eq 1) -Detail ($run.Message + ' | ' + (@($run.Lines | Where-Object { $_.StartsWith('Backup') }) -join ' | '))
        $run = Invoke-E2eNewFile -NoResources -CheckFailures 1
        Assert-True -Name 'L3W-6: deploy-ha.ps1, a new file whose ha core check fails: "was rolled back", the new file gone, and the rollback''s Backup line names the kept, empty backup folder' -Condition (
            $run.Message -match 'was rolled back' -and -not $run.Placed -and $run.Stamp -and @($run.Held).Count -eq 0 -and
            $run.Message.Contains("Backup: none (new file); the backup folder /config/ecco-backups/$($run.Stamp) is kept; this run copied nothing into it (no Lovelace resource list on the host)")) -Detail $run.Message
        $run = Invoke-E2eDeploy -LiveText $layerText
        $replaceBackup = @($run.Lines | Where-Object { $_.StartsWith('Backup      : ') })
        Assert-True -Name 'L3W-6 control: deploy-ha.ps1 over an existing file: PASSED, and the Backup line is the backup file itself (no new-file wording)' -Condition (
            $run.Message -eq '' -and $replaceBackup.Count -eq 1 -and
            $replaceBackup[0] -cmatch ('^Backup      : /config/ecco-backups/[0-9]{8}-[0-9]{6}/' + [regex]::Escape($destination.TrimStart('/').Replace('/', '__')) + '$')) -Detail ($run.Message + ' | ' + ($replaceBackup -join ' | '))
    }
    finally {
        Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath function:global:scp -ErrorAction SilentlyContinue
        Remove-Variable -Name EccoTestSh, EccoTestTreeWin, EccoTestTreeSh, EccoTestCheckFailures -Scope Global -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $e2eBase -Recurse -Force -ErrorAction SilentlyContinue
        Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force
    }
} else {
    Remove-Item -LiteralPath $e2eBase -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '  SKIP  the end-to-end runs need a POSIX sh with cygpath (Git for Windows; pass -Sh <sh.exe>)'
}

# =====================================================================
# Sections 17-22: the Intelligence kit route (PR-5). Fictional kits are
# built by a fictional stand-in for tools/build_ha_integration.py (same
# command line and output layout) inside throwaway git repositories under
# the temp folder; the host is a fictional /config tree driven through
# stubbed ssh and scp (sections 19-23 run each command under the local
# POSIX sh). Junctions (mklink /J, no admin rights needed) stand in for
# symlinks: the sh sees them as symlinks. Fictional data only.
# =====================================================================
$kitBase = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-kit-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $kitBase | Out-Null
$kitBase = (Resolve-Path -LiteralPath $kitBase).Path
$script:kitJunctions = New-Object System.Collections.Generic.List[string]
$script:kitStampN = 0

$fictionalBuilder = @'
"""Fictional stand-in for tools/build_ha_integration.py (Test-EccoDeploy.ps1 only): the same command line and kit layout."""
import argparse, hashlib, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "kit-src"
PKG = "custom_components/ecco_intelligence"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--git-sha", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        print("REFUSED: --out is not empty", file=sys.stderr)
        return 1
    files = {}
    for p in sorted(SRC.rglob("*")):
        if p.is_file():
            files[PKG + "/" + p.relative_to(SRC).as_posix()] = p.read_bytes().replace(b"\r\n", b"\n")
    modules = [{"module": r, "output_sha256": sha(b)} for r, b in sorted(files.items()) if "/_vendor/" in r]
    manifest = {"schema": "ecco-intel-vendor-manifest/1", "package": PKG, "git_sha": a.git_sha, "modules": modules,
                "note": "fictional test kit"}
    blob = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files[PKG + "/VENDOR_MANIFEST.json"] = blob
    files["VENDOR_MANIFEST.json"] = blob
    for rel, b in files.items():
        q = out.joinpath(*rel.split("/"))
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b)
    sums = "".join(sha(files[r]) + "  " + r + "\n" for r in sorted(files))
    (out / "SHA256SUMS").write_bytes(sums.encode())
    print("built", sha(sums.encode()))
    return 0


raise SystemExit(main())
'@

function New-KitSource {
    param([string]$Root, [string]$Engine = "def run():`n    return 1`n")
    $files = [ordered]@{
        '__init__.py'                          = "`"`"`"Fictional ECCO Intelligence test integration (test data only).`"`"`"`n"
        'manifest.json'                        = "{`"domain`": `"ecco_intelligence`", `"name`": `"Example`", `"version`": `"0.0.1`"}`n"
        'const.py'                             = "VALUE = 1`n"
        '_vendor/__init__.py'                  = "`n"
        '_vendor/intelligence/__init__.py'     = "`n"
        '_vendor/intelligence/example_engine.py' = $Engine
        'runtime/__init__.py'                  = "`n"
        'translations/en.json'                 = "{`"title`": `"Example`"}`n"
    }
    foreach ($rel in $files.Keys) {
        $path = Join-Path $Root ($rel.Replace('/', '\'))
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [System.IO.File]::WriteAllText($path, $files[$rel])
    }
}

function Invoke-KitGit {
    param([string]$Repo, [string[]]$GitArgs)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& git -C $Repo -c core.autocrlf=false -c user.email=test@example.invalid -c user.name='ECCO Test' @GitArgs 2>&1 | ForEach-Object { [string]$_ })
    } finally {
        $ErrorActionPreference = $previousEap
    }
    return $out
}

# A throwaway git repository with a copy of this checkout's kit tooling, the fictional builder and a fictional kit source.
function New-KitStubRepo {
    param([string]$Root)
    New-Item -ItemType Directory -Path (Join-Path $Root 'tools') -Force | Out-Null
    foreach ($file in @('deploy-ha.ps1', 'deploy-ha-kit.ps1', 'place-ha-site-file.ps1', 'EccoDeploy.psm1', 'ecco_dashboard_guard.py')) {
        Copy-Item -LiteralPath (Join-Path $toolsDir $file) -Destination (Join-Path $Root 'tools')
    }
    [System.IO.File]::WriteAllText((Join-Path $Root 'tools\build_ha_integration.py'), $fictionalBuilder.Replace("`r`n", "`n"))
    New-KitSource -Root (Join-Path $Root 'kit-src')
    [System.IO.File]::WriteAllText((Join-Path $Root '.gitignore'), "ecco_dashboard_gate.local.txt`nsite.local.json`n")
    Invoke-KitGit -Repo $Root -GitArgs @('init', '-q') | Out-Null
    Invoke-KitGit -Repo $Root -GitArgs @('add', '-A') | Out-Null
    Invoke-KitGit -Repo $Root -GitArgs @('commit', '-q', '-m', 'fictional kit source') | Out-Null
    return (Resolve-Path -LiteralPath $Root).Path
}

function Get-KitRepoHead {
    param([string]$Repo)
    return ((Invoke-KitGit -Repo $Repo -GitArgs @('rev-parse', 'HEAD')) -join '').Trim()
}

function Invoke-FictionalBuild {
    param([string]$Repo, [string]$Out, [string]$GitSha)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($GitSha) {
            & $Python -I -B -X utf8 (Join-Path $Repo 'tools\build_ha_integration.py') --out $Out --git-sha $GitSha 2>&1 | Out-Null
        } else {
            & $Python -I -B -X utf8 (Join-Path $Repo 'tools\build_ha_integration.py') --out $Out 2>&1 | Out-Null
        }
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

function Get-KitSumsSha {
    param([string]$KitDir)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $KitDir 'SHA256SUMS')).Hash.ToLowerInvariant()
}

# Re-hashes every file a kit's SHA256SUMS lists (the list itself unchanged), so a deliberate defect is the only one.
function Update-KitSums {
    param([string]$KitDir)
    $lines = [System.IO.File]::ReadAllText((Join-Path $KitDir 'SHA256SUMS')).TrimEnd("`n").Split("`n")
    $text = -join ($lines | ForEach-Object {
        $rel = $_.Substring(66)
        "$((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $KitDir ($rel.Replace('/', '\')))).Hash.ToLowerInvariant())  $rel`n"
    })
    [System.IO.File]::WriteAllBytes((Join-Path $KitDir 'SHA256SUMS'), [System.Text.Encoding]::ASCII.GetBytes($text))
    return (Get-KitSumsSha -KitDir $KitDir)
}

function Copy-KitDir {
    param([string]$From, [string]$To)
    Copy-Item -LiteralPath $From -Destination $To -Recurse
    return $To
}

function New-KitJunction {
    param([string]$Link, [string]$Target)
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & cmd /c mklink /J $Link $Target 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $previousEap
    }
    $ok = (Test-Path -LiteralPath $Link) -and (((Get-Item -LiteralPath $Link -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
    if ($ok) { $script:kitJunctions.Add($Link) }
    return $ok
}

# A junction to -Target exactly as given (amendment A26 cases): the target is not created, so it can be missing (dangling),
# a file, or another junction that points back (a loop). The sh sees each as a symlink.
function New-RawJunction {
    param([string]$Link, [string]$Target)
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & cmd /c mklink /J $Link $Target 2>&1 | Out-Null
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEap
    }
    $ok = ($code -eq 0) -and ($null -ne (Get-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue))
    if ($ok) { $script:kitJunctions.Add($Link) }
    return $ok
}

# Junctions are removed by themselves (cmd rmdir removes the link only, and never a folder that is not empty) before any
# recursive delete - tried for every recorded junction, also one that is dangling or loops.
function Remove-KitJunctions {
    foreach ($j in @($script:kitJunctions)) {
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & cmd /c rmdir $j 2>&1 | Out-Null } finally { $ErrorActionPreference = $previousEap }
    }
    $script:kitJunctions.Clear()
}

function Get-RefusalMessage {
    param([scriptblock]$Block)
    try {
        & $Block | Out-Null
        return ''
    } catch {
        return $_.Exception.Message
    }
}

function Get-NextKitStamp {
    $script:kitStampN++
    return ('20300101-{0:D6}' -f $script:kitStampN)
}

try {
# ---------------------------------------------------------------------
# 17. The single-file route refuses the Intelligence areas; the kit
#     manifest check (Test-EccoKitManifest) on fictional kits; kit
#     equivalence (amendment A3); git_sha = HEAD and the rebuild check.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[17] Single-file refusals, the kit manifest check, kit equivalence and the rebuild check'
foreach ($d in @('/config/ecco/intelligence/site.local.json', '/config/ecco/intelligence/state/x.json', '/config/ecco/intelligence',
                 '\config\ecco\intelligence\site.local.json', '/config/ecco/staging/20300101-000000/new/ecco_intelligence/manifest.json',
                 '/config/ecco/staging')) {
    Assert-True -Name "single-file route refuses: $d" -Condition (-not (Test-DestinationAccepted $d))
}
$m = Get-RefusalMessage { Test-EccoDeploymentDestination -Destination '/config/ecco/intelligence/site.local.json' }
Assert-True -Name 'the site-file refusal names the placement command' -Condition ($m -match 'place-ha-site-file\.ps1') -Detail $m
$m = Get-RefusalMessage { Test-EccoDeploymentDestination -Destination '/config/ecco/staging/x.yaml' }
Assert-True -Name 'the staging refusal names the kit command' -Condition ($m -match 'deploy-ha-kit\.ps1') -Detail $m
foreach ($d in @('/config/ecco/intelligence-x/a.yaml', '/config/ecco/stagingx/a.yaml', '/config/ecco/dashboards/ecco_intelligence.yaml')) {
    Assert-True -Name "a sibling sharing the prefix text is still accepted: $d" -Condition (Test-DestinationAccepted $d)
}

$k17 = Join-Path $kitBase 'k17'
$repo17 = New-KitStubRepo -Root (Join-Path $k17 'repo')
$head17 = Get-KitRepoHead -Repo $repo17
$kitA = Join-Path $k17 'kit-a'
$built = Invoke-FictionalBuild -Repo $repo17 -Out $kitA -GitSha $head17
Assert-True -Name 'the fictional builder writes a kit (SHA256SUMS, both manifests, the package) from the stub repository' -Condition (
    $built -and (Test-Path -LiteralPath (Join-Path $kitA 'SHA256SUMS')) -and (Test-Path -LiteralPath (Join-Path $kitA 'custom_components\ecco_intelligence\VENDOR_MANIFEST.json')))
$shaA = Get-KitSumsSha -KitDir $kitA
$infoA = $null
$m = Get-RefusalMessage { $script:infoA = Test-EccoKitManifest -Kit $kitA -ExpectedSumsSha256 $shaA }
$infoA = $script:infoA
Assert-True -Name 'control: the fictional kit verifies (9 package files incl. VENDOR_MANIFEST.json, 4 folders, git_sha, domain)' -Condition (
    $m -eq '' -and @($infoA.PackageFiles.Keys).Count -eq 9 -and @($infoA.PackageDirs).Count -eq 4 -and $infoA.GitSha -ceq $head17 -and $infoA.Version -ceq '0.0.1') -Detail $m
Assert-True -Name 'the allowlist is the package files only (10 SHA256SUMS lines: the 9 package files and the root VENDOR_MANIFEST.json, which is never uploaded)' -Condition (
    @($infoA.Entries).Count -eq 10 -and @($infoA.PackageFiles.Keys | Where-Object { $null -ne (Test-EccoKitPackagePath -Path $_) }).Count -eq 0 -and
    $infoA.PackageFiles.ContainsKey('VENDOR_MANIFEST.json') -and -not $infoA.PackageFiles.ContainsKey('custom_components/ecco_intelligence/const.py'))

# Directory defects (each kit is a copy of the control with one defect; the expected sums sha is recomputed so the defect is the only one).
$n = 0
function Test-KitDefect {
    param([string]$Name, [scriptblock]$Break, [string]$Pattern, [switch]$KeepSums)
    $script:n++
    $dir = Copy-KitDir -From $kitA -To (Join-Path $k17 ("defect-{0:D2}" -f $script:n))
    & $Break $dir
    $expected = if ($KeepSums) { Get-KitSumsSha -KitDir $dir } else { Update-KitSums -KitDir $dir }
    $msg = Get-RefusalMessage { Test-EccoKitManifest -Kit $dir -ExpectedSumsSha256 $expected }
    Assert-True -Name "kit refused: $Name" -Condition ($msg -ne '' -and $msg -match $Pattern) -Detail $msg
}
Test-KitDefect -Name 'an extra file the SHA256SUMS does not list' -Break { param($d) [System.IO.File]::WriteAllText((Join-Path $d 'custom_components\ecco_intelligence\extra.py'), "x = 1`n") } -Pattern 'does not list' -KeepSums
Test-KitDefect -Name 'a listed file missing' -Break { param($d) Remove-Item -LiteralPath (Join-Path $d 'custom_components\ecco_intelligence\const.py') } -Pattern 'missing a file' -KeepSums
Test-KitDefect -Name 'a file with a wrong hash' -Break { param($d) [System.IO.File]::WriteAllText((Join-Path $d 'custom_components\ecco_intelligence\const.py'), "VALUE = 2`n") } -Pattern 'does not match its SHA256SUMS line' -KeepSums
Test-KitDefect -Name 'an extra empty folder' -Break { param($d) New-Item -ItemType Directory -Path (Join-Path $d 'custom_components\ecco_intelligence\empty') | Out-Null } -Pattern 'folder no listed file needs' -KeepSums
Test-KitDefect -Name 'unequal VENDOR_MANIFEST.json copies' -Break { param($d) [System.IO.File]::AppendAllText((Join-Path $d 'VENDOR_MANIFEST.json'), ' ') } -Pattern 'copies of the kit differ'
Test-KitDefect -Name 'a null git_sha' -Break { param($d)
    foreach ($f in @('VENDOR_MANIFEST.json', 'custom_components\ecco_intelligence\VENDOR_MANIFEST.json')) {
        $p = Join-Path $d $f; [System.IO.File]::WriteAllText($p, ([System.IO.File]::ReadAllText($p) -replace '"git_sha": "[0-9a-f]+"', '"git_sha": null')) } } -Pattern 'no git_sha'
Test-KitDefect -Name 'a wrong domain in manifest.json' -Break { param($d)
    [System.IO.File]::WriteAllText((Join-Path $d 'custom_components\ecco_intelligence\manifest.json'), "{`"domain`": `"ecco_intelligence_x`", `"version`": `"0.0.1`"}`n") } -Pattern "names the domain 'ecco_intelligence_x'"
Test-KitDefect -Name 'a manifest with another schema' -Break { param($d)
    foreach ($f in @('VENDOR_MANIFEST.json', 'custom_components\ecco_intelligence\VENDOR_MANIFEST.json')) {
        $p = Join-Path $d $f; [System.IO.File]::WriteAllText($p, ([System.IO.File]::ReadAllText($p).Replace('ecco-intel-vendor-manifest/1', 'example/9'))) } } -Pattern 'not an ecco-intel-vendor-manifest/1 manifest'
$msg = Get-RefusalMessage { Test-EccoKitManifest -Kit $kitA -ExpectedSumsSha256 ('0' * 64) }
Assert-True -Name 'kit refused: the SHA256SUMS sha256 is not the expected one' -Condition ($msg -match 'not the expected') -Detail $msg
$msg = Get-RefusalMessage { Test-EccoKitManifest -Kit $kitA -ExpectedSumsSha256 $shaA.ToUpperInvariant() }
Assert-True -Name 'kit refused: -ExpectedSumsSha256 must be lower-case hex' -Condition ($msg -match 'lower-case hex') -Detail $msg
$junctionKit = Copy-KitDir -From $kitA -To (Join-Path $k17 'defect-junction')
if (New-KitJunction -Link (Join-Path $junctionKit 'custom_components\ecco_intelligence\linked') -Target (Join-Path $k17 'junction-target')) {
    $msg = Get-RefusalMessage { Test-EccoKitManifest -Kit $junctionKit -ExpectedSumsSha256 $shaA }
    Assert-True -Name 'kit refused: a junction inside the kit (never followed)' -Condition ($msg -match 'reparse point') -Detail $msg
} else {
    Write-Host '  SKIP  kit refused: a junction inside the kit (mklink /J could not create one here)'
}

# SHA256SUMS text defects (ConvertFrom-EccoSumsText on crafted bytes).
$h = 'a' * 64
$okLine = "$h  custom_components/ecco_intelligence/const.py`n"
function Test-SumsRefused {
    param([string]$Name, [string]$Text, [string]$Pattern, [switch]$PackageRelative)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $msg = Get-RefusalMessage { ConvertFrom-EccoSumsText -Bytes $bytes -Label 'SHA256SUMS' -PackageRelative:$PackageRelative }
    Assert-True -Name "SHA256SUMS refused: $Name" -Condition ($msg -ne '' -and $msg -match $Pattern) -Detail $msg
}
Assert-True -Name 'control: a well-formed SHA256SUMS line parses' -Condition (@(ConvertFrom-EccoSumsText -Bytes ([System.Text.Encoding]::ASCII.GetBytes($okLine)) -Label 'x').Count -eq 1)
Test-SumsRefused -Name '../ traversal' -Text "$h  custom_components/ecco_intelligence/../secrets.py`n" -Pattern "'\.\.' segment"
Test-SumsRefused -Name 'an absolute path' -Text "$h  /config/custom_components/ecco_intelligence/a.py`n" -Pattern 'outside custom_components'
Test-SumsRefused -Name 'a backslash' -Text "$h  custom_components/ecco_intelligence/runtime\a.py`n" -Pattern 'backslash'
Test-SumsRefused -Name 'a ./ segment' -Text "$h  custom_components/ecco_intelligence/./a.py`n" -Pattern "'\.' segment"
Test-SumsRefused -Name 'a duplicate path' -Text ($okLine + $okLine) -Pattern 'duplicate'
Test-SumsRefused -Name 'two paths that differ only by letter case' -Text ($okLine + "$h  custom_components/ecco_intelligence/Const.py`n") -Pattern 'letter case'
Test-SumsRefused -Name 'ecco_intelligence_x/ (a sibling folder)' -Text "$h  custom_components/ecco_intelligence_x/a.py`n" -Pattern 'outside custom_components'
Test-SumsRefused -Name 'Custom_Components/ (case-sensitive)' -Text "$h  Custom_Components/ecco_intelligence/a.py`n" -Pattern 'outside custom_components'
foreach ($ext in @('pyc', 'so', 'sh', 'yaml')) {
    Test-SumsRefused -Name ".$ext file" -Text "$h  custom_components/ecco_intelligence/a.$ext`n" -Pattern 'only \.py and \.json'
}
Test-SumsRefused -Name 'a dot-folder' -Text "$h  custom_components/ecco_intelligence/.hidden/a.py`n" -Pattern 'folder name'
Test-SumsRefused -Name 'an upper-case folder' -Text "$h  custom_components/ecco_intelligence/Runtime/a.py`n" -Pattern 'folder name'
Test-SumsRefused -Name 'a __pycache__ folder' -Text "$h  custom_components/ecco_intelligence/__pycache__/a.py`n" -Pattern '__pycache__'
Test-SumsRefused -Name 'more than 4 levels' -Text "$h  custom_components/ecco_intelligence/a/b/c/d/e.py`n" -Pattern 'more than 4 levels'
Test-SumsRefused -Name 'CRLF line endings' -Text $okLine.Replace("`n", "`r`n") -Pattern 'carriage return'
Test-SumsRefused -Name 'no final newline' -Text $okLine.TrimEnd("`n") -Pattern 'newline'
Test-SumsRefused -Name 'an upper-case hash' -Text $okLine.Replace($h, $h.ToUpperInvariant()) -Pattern 'not .<sha256>  <path>.'
Test-SumsRefused -Name 'one space between hash and path' -Text $okLine.Replace("$h  ", "$h ") -Pattern 'not .<sha256>  <path>.'
Test-SumsRefused -Name 'a path with a space' -Text "$h  custom_components/ecco_intelligence/a b.py`n" -Pattern 'not .<sha256>  <path>.'
Test-SumsRefused -Name 'a non-ASCII byte' -Text "$h  custom_components/ecco_intelligence/caf$([char]0xE9).py`n" -Pattern 'printable ASCII'
Test-SumsRefused -Name 'BACKUP_SHA256SUMS (package-relative): a path that leaves the package' -Text "$h  ../manifest.json`n" -Pattern "'\.\.' segment" -PackageRelative
Assert-True -Name 'control: a package-relative BACKUP_SHA256SUMS line parses' -Condition (@(ConvertFrom-EccoSumsText -Bytes ([System.Text.Encoding]::ASCII.GetBytes("$h  runtime/a.py`n")) -Label 'x' -PackageRelative).Count -eq 1)
# The folder list is always an array (PowerShell would otherwise unroll an empty or one-element result to $null or a string).
$flatFiles = New-Object 'System.Collections.Generic.SortedDictionary[string,string]' ([System.StringComparer]::Ordinal)
$flatFiles['manifest.json'] = $h
$flatTree = [pscustomobject]@{ State = 'dir'; Root = '/config/example'; Dirs = [string[]]@(); Files = $flatFiles; Pycache = [string[]]@(); Others = [string[]]@() }
$noDirs = Get-EccoParentDirs -Paths @('a.py')
$oneDir = Get-EccoParentDirs -Paths @('runtime/a.py')
$m = Get-RefusalMessage { if ($null -ne (Compare-EccoKitTree -Tree $flatTree -ExpectedFiles $flatFiles)) { throw 'the flat tree was reported as different' } }
Assert-True -Name 'the folder list of a package with no sub-folder, or one, is still an array, and a flat tree compares equal' -Condition (
    $m -eq '' -and $noDirs -is [string[]] -and $noDirs.Count -eq 0 -and $oneDir -is [string[]] -and $oneDir.Count -eq 1 -and $oneDir[0] -ceq 'runtime') -Detail $m

# Kit equivalence (amendment A3; critique test 6).
$kitB = Join-Path $k17 'kit-b'
Invoke-FictionalBuild -Repo $repo17 -Out $kitB -GitSha ('b' * 40) | Out-Null
$infoB = Test-EccoKitManifest -Kit $kitB -ExpectedSumsSha256 (Get-KitSumsSha -KitDir $kitB)
$eq = $null
$msg = Get-RefusalMessage { $script:eq = Test-EccoKitEquivalence -KitInfo $infoB -ReferenceKit $kitA -ReferenceSumsSha256 $shaA }
Assert-True -Name 'equivalence: two kits that differ only in git_sha are EQUIVALENT' -Condition ($msg -eq '' -and $script:eq.Result -ceq 'EQUIVALENT' -and $script:eq.Line -match 'only git_sha differs') -Detail $msg
$msg = Get-RefusalMessage { $script:eq = Test-EccoKitEquivalence -KitInfo $infoA -ReferenceKit $kitA -ReferenceSumsSha256 $shaA }
Assert-True -Name 'equivalence: the same kit is IDENTICAL' -Condition ($msg -eq '' -and $script:eq.Result -ceq 'IDENTICAL') -Detail $msg
$refOnly = Join-Path $k17 'reference-two-files'
New-Item -ItemType Directory -Path $refOnly | Out-Null
Copy-Item -LiteralPath (Join-Path $kitA 'SHA256SUMS') -Destination $refOnly
Copy-Item -LiteralPath (Join-Path $kitA 'VENDOR_MANIFEST.json') -Destination $refOnly
$msg = Get-RefusalMessage { $script:eq = Test-EccoKitEquivalence -KitInfo $infoB -ReferenceKit $refOnly -ReferenceSumsSha256 $shaA }
Assert-True -Name 'equivalence: the reference needs only its SHA256SUMS and VENDOR_MANIFEST.json' -Condition ($msg -eq '' -and $script:eq.Result -ceq 'EQUIVALENT') -Detail $msg
$src2 = Join-Path $k17 'repo-changed'
$repoC = New-KitStubRepo -Root $src2
[System.IO.File]::WriteAllText((Join-Path $repoC 'kit-src\_vendor\intelligence\example_engine.py'), "def run():`n    return 2`n")
$kitC = Join-Path $k17 'kit-c'
Invoke-FictionalBuild -Repo $repoC -Out $kitC -GitSha ('c' * 40) | Out-Null
$infoC = Test-EccoKitManifest -Kit $kitC -ExpectedSumsSha256 (Get-KitSumsSha -KitDir $kitC)
$msg = Get-RefusalMessage { Test-EccoKitEquivalence -KitInfo $infoC -ReferenceKit $kitA -ReferenceSumsSha256 $shaA }
Assert-True -Name 'equivalence: one changed .py byte makes the kits NOT EQUIVALENT' -Condition ($msg -match 'NOT EQUIVALENT' -and $msg -match 'example_engine\.py differs') -Detail $msg
$msg = Get-RefusalMessage { Test-EccoKitEquivalence -KitInfo $infoB -ReferenceKit $kitA -ReferenceSumsSha256 ('0' * 64) }
Assert-True -Name 'equivalence: a reference whose SHA256SUMS is not the recorded one is refused' -Condition ($msg -match 'not the recorded') -Detail $msg
$refBadManifest = Copy-KitDir -From $refOnly -To (Join-Path $k17 'reference-bad-manifest')
[System.IO.File]::AppendAllText((Join-Path $refBadManifest 'VENDOR_MANIFEST.json'), ' ')
$msg = Get-RefusalMessage { Test-EccoKitEquivalence -KitInfo $infoB -ReferenceKit $refBadManifest -ReferenceSumsSha256 $shaA }
Assert-True -Name 'equivalence: a reference VENDOR_MANIFEST.json that does not match its SHA256SUMS line is refused' -Condition ($msg -match 'does not match its SHA256SUMS line') -Detail $msg
# A crafted reference: the same file lines, but its manifest lists other modules (its two manifest lines rewritten to match).
$refModules = Copy-KitDir -From $refOnly -To (Join-Path $k17 'reference-other-modules')
$rmPath = Join-Path $refModules 'VENDOR_MANIFEST.json'
[System.IO.File]::WriteAllText($rmPath, ([System.IO.File]::ReadAllText($rmPath).Replace('example_engine.py', 'example_other.py')))
$rmSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $rmPath).Hash.ToLowerInvariant()
$rmSums = [System.IO.File]::ReadAllText((Join-Path $refModules 'SHA256SUMS')) -replace '(?m)^[0-9a-f]{64}(  (custom_components/ecco_intelligence/)?VENDOR_MANIFEST\.json)$', ($rmSha + '$1')
[System.IO.File]::WriteAllBytes((Join-Path $refModules 'SHA256SUMS'), [System.Text.Encoding]::ASCII.GetBytes($rmSums))
$msg = Get-RefusalMessage { Test-EccoKitEquivalence -KitInfo $infoB -ReferenceKit $refModules -ReferenceSumsSha256 (Get-KitSumsSha -KitDir $refModules) }
Assert-True -Name 'equivalence: identical file lines but a different modules list is NOT EQUIVALENT' -Condition ($msg -match "modules lists differ") -Detail $msg

# git_sha = HEAD and the byte-identical rebuild.
$m = Get-RefusalMessage { Assert-EccoKitGitSha -KitInfo $infoA -RepoRoot $repo17 }
Assert-True -Name 'git_sha: a kit built with --git-sha HEAD matches this checkout' -Condition ($m -eq '') -Detail $m
$m = Get-RefusalMessage { Assert-EccoKitGitSha -KitInfo $infoB -RepoRoot $repo17 }
Assert-True -Name 'git_sha: a kit built from another commit is refused' -Condition ($m -match 'not from this checkout') -Detail $m
$rebuild = ''
$m = Get-RefusalMessage { $script:rebuild = Invoke-EccoKitRebuildCheck -RepoRoot $repo17 -Python $Python -KitInfo $infoA }
Assert-True -Name 'rebuild: a rebuild of the checkout gives identical SHA256SUMS bytes' -Condition ($m -eq '' -and $script:rebuild -match 'identical') -Detail $m
$kitT = Copy-KitDir -From $kitA -To (Join-Path $k17 'kit-tampered-consistent')
[System.IO.File]::WriteAllText((Join-Path $kitT 'custom_components\ecco_intelligence\const.py'), "VALUE = 3`n")
$infoT = Test-EccoKitManifest -Kit $kitT -ExpectedSumsSha256 (Update-KitSums -KitDir $kitT)
$m = Get-RefusalMessage { Invoke-EccoKitRebuildCheck -RepoRoot $repo17 -Python $Python -KitInfo $infoT }
Assert-True -Name 'rebuild: a self-consistent kit whose file is not this tree''s is refused (the rebuild differs)' -Condition ($m -match 'the kit is not this tree') -Detail $m
$noBuilder = Join-Path $k17 'no-builder'
New-Item -ItemType Directory -Path (Join-Path $noBuilder 'tools') -Force | Out-Null
$m = Get-RefusalMessage { Invoke-EccoKitRebuildCheck -RepoRoot $noBuilder -Python $Python -KitInfo $infoA }
Assert-True -Name 'rebuild: a checkout without tools/build_ha_integration.py cannot prove the kit (BLOCKED)' -Condition ($m -match 'not in this checkout') -Detail $m
$rebuildFolders = @(Get-ChildItem -LiteralPath ([System.IO.Path]::GetTempPath()) -Directory -Filter 'ecco-kit-rebuild-*' -ErrorAction SilentlyContinue).Count
Assert-True -Name 'rebuild: every rebuild deleted its temporary folder' -Condition ($rebuildFolders -eq 0) -Detail "$rebuildFolders left"

# ---------------------------------------------------------------------
# 18. The -Target Test|Production guard (amendment A10; critique test 7;
#     test-HA T3) on deploy-ha.ps1 and the kit commands, against an
#     in-process stub host whose answers (ssh -G host name, test-instance
#     marker, machine) each case sets. Every refusal comes before the first
#     write; the local ones before any ssh call.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[18] The -Target guard: deploy-ha.ps1 and the kit commands'
foreach ($hn in @('127.0.0.1', '127.1.2.3', 'localhost', 'LOCALHOST', '::1', '[::1]')) {
    Assert-True -Name "loopback: $hn" -Condition (Test-EccoLoopbackHostName -HostName $hn)
}
foreach ($hn in @('fictional.example.invalid', '128.0.0.1', 'localhost.example.invalid', '198.51.100.7')) {
    Assert-True -Name "not loopback: $hn" -Condition (-not (Test-EccoLoopbackHostName -HostName $hn))
}
$tgtRepo = New-StubRepo -Root (Join-Path $kitBase 'tgt-repo')
[System.IO.File]::WriteAllText((Join-Path $tgtRepo 'dist\stub\example.yaml'), "# fictional package`n")
$tgtDeployHa = Join-Path $tgtRepo 'tools\deploy-ha.ps1'
$kitRepo = New-KitStubRepo -Root (Join-Path $kitBase 'kit-repo')
$kitV1 = Join-Path $kitBase 'kit-v1'
Invoke-FictionalBuild -Repo $kitRepo -Out $kitV1 -GitSha (Get-KitRepoHead -Repo $kitRepo) | Out-Null
$kitV1Sha = Get-KitSumsSha -KitDir $kitV1
$sshConfigFile = Join-Path $kitBase 'fictional-ssh-config'
[System.IO.File]::WriteAllText($sshConfigFile, "Host ecco-ha-test`n    HostName 127.0.0.1`n")
$goodMarker = 'ECCO-L3-TEST 0e5c1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b'
$global:EccoTgtLog = New-Object System.Collections.Generic.List[string]
$global:EccoTgt = @{ Resolved = '127.0.0.1'; Marker = $null; Machine = 'ecco-l3-test' }
try {
    function global:ssh {
        $tag = if ($args -ccontains '-F') { ' [-F]' } else { '' }
        $command = [string]$args[$args.Count - 1]
        $global:LASTEXITCODE = 0
        if ($args -ccontains '-G') {
            $global:EccoTgtLog.Add("ssh -G $command$tag")
            return "hostname $($global:EccoTgt.Resolved)"
        }
        $global:EccoTgtLog.Add("ssh $command$tag")
        if ($command -ceq 'true') { return }
        if ($command -ceq 'ha core info --raw-json') { return ('{"result": "ok", "data": {"machine": "' + $global:EccoTgt.Machine + '"}}') }
        if ($command -ceq "head -c 200 '/config/.ecco_l3_test_instance'") { return $global:EccoTgt.Marker }
        if ($command -cmatch "^if \[ -L '([^']+)' \]; then printf unreadable;") {
            if ($Matches[1] -ceq '/config/.ecco_l3_test_instance' -and $null -ne $global:EccoTgt.Marker) { return 'present' }
            return 'absent'
        }
        $global:LASTEXITCODE = 1
        return 'stubbed host: command refused'
    }
    function global:scp {
        $tag = if ($args -ccontains '-F') { ' [-F]' } else { '' }
        $global:EccoTgtLog.Add('scp ' + ($args[$args.Count - 2]) + ' ' + ($args[$args.Count - 1]) + $tag)
        $global:LASTEXITCODE = 1
    }
    # The guard's reads only: ssh -G (configuration), the ssh probe, the marker probe and read, ha core info.
    $tgtReads = { param($e) $e -cmatch "^ssh (-G \S+|true|ha core info --raw-json|head -c 200 '/config/\.ecco_l3_test_instance'|if \[ -L '/config/\.ecco_l3_test_instance' \].*)( \[-F\])?$" }
    function Invoke-TgtDeploy {
        param([string]$HostAlias = 'ecco-ha-test', [hashtable]$Extra = @{}, [hashtable]$Facts = @{})
        $global:EccoTgt = @{ Resolved = '127.0.0.1'; Marker = $null; Machine = 'ecco-l3-test' }
        foreach ($k in $Facts.Keys) { $global:EccoTgt[$k] = $Facts[$k] }
        $global:EccoTgtLog.Clear()
        $message = ''
        try {
            & $tgtDeployHa -Source 'dist/stub/example.yaml' -Destination '/config/packages/example.yaml' -SshHost $HostAlias -SkipValidation -AllowDirtyWorkingTree -Python $Python @Extra 6>$null 3>$null | Out-Null
        } catch {
            $message = $_.Exception.Message
        }
        $sent = @($global:EccoTgtLog)
        return [pscustomobject]@{ Message = $message; Sent = $sent; NotGuardReads = @($sent | Where-Object { -not (& $tgtReads $_) }) }
    }

    $run = Invoke-TgtDeploy
    Assert-True -Name 'critique test 7: deploy-ha.ps1 -SshHost ecco-ha-test with no -Target is refused before any ssh call' -Condition (
        $run.Message -match '^DEPLOY_TARGET: BLOCKED' -and $run.Message -match '-Target Test\|Production is required' -and $run.Sent.Count -eq 0) -Detail ($run.Message + ' | ' + ($run.Sent -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Production' } -Facts @{ Resolved = 'fictional.example.invalid'; Marker = $goodMarker; Machine = 'example-machine' }
    Assert-True -Name 'critique test 7: -Target Production with the test-instance marker present is refused, having sent only the guard''s reads' -Condition (
        $run.Message -match '^DEPLOY_TARGET: BLOCKED' -and $run.Message -match 'marker .* is present' -and $run.NotGuardReads.Count -eq 0) -Detail ($run.Message + ' | ' + ($run.NotGuardReads -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test' } -Facts @{ Marker = $null }
    Assert-True -Name 'test-HA T3: -Target Test with no marker is refused (reads only)' -Condition (
        $run.Message -match 'marker .* is absent' -and $run.NotGuardReads.Count -eq 0) -Detail ($run.Message + ' | ' + ($run.NotGuardReads -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test' } -Facts @{ Resolved = 'fictional.example.invalid'; Marker = $goodMarker }
    Assert-True -Name 'test-HA T3: -Target Test with a host that is not loopback is refused before the marker is even probed' -Condition (
        $run.Message -match 'does not resolve to a loopback address' -and @($run.Sent | Where-Object { $_ -match 'ecco_l3_test_instance' }).Count -eq 0) -Detail ($run.Message + ' | ' + ($run.Sent -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test' } -Facts @{ Marker = $goodMarker; Machine = 'example-machine' }
    Assert-True -Name 'test-HA T3: -Target Test on another machine is refused (reads only)' -Condition (
        $run.Message -match "reports the machine 'example-machine'" -and $run.NotGuardReads.Count -eq 0) -Detail ($run.Message + ' | ' + ($run.NotGuardReads -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test' } -Facts @{ Marker = 'ECCO-L3-TEST not-a-uuid' }
    Assert-True -Name '-Target Test with a marker that does not hold ECCO-L3-TEST <uuid> is refused' -Condition ($run.Message -match "does not hold exactly 'ECCO-L3-TEST <uuid>'") -Detail $run.Message
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Production' } -Facts @{ Resolved = '127.0.0.1'; Machine = 'example-machine' }
    Assert-True -Name '-Target Production with a loopback host is refused before the marker is probed' -Condition (
        $run.Message -match 'resolves to a loopback address' -and @($run.Sent | Where-Object { $_ -match 'ecco_l3_test_instance' }).Count -eq 0) -Detail $run.Message
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Production' } -Facts @{ Resolved = 'fictional.example.invalid'; Machine = 'ecco-l3-test' }
    Assert-True -Name '-Target Production on the test machine is refused' -Condition ($run.Message -match "reports the test machine 'ecco-l3-test'") -Detail $run.Message
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Production' } -Facts @{ Resolved = 'fictional.example.invalid'; Machine = 'example-machine' }
    Assert-True -Name 'control: -Target Production on a production-like host passes the guard and reaches the next host command' -Condition (
        $run.Message -match 'Unable to inspect existing remote file' -and @($run.Sent | Where-Object { $_ -ceq 'ssh ha core info --raw-json' }).Count -eq 1 -and
        @($run.Sent | Where-Object { $_ -match "^ssh if \[ -L '/config/\.ecco_l3_test_instance'" }).Count -eq 1) -Detail ($run.Message + ' | ' + ($run.Sent -join ' | '))
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test' } -Facts @{ Marker = $goodMarker }
    Assert-True -Name 'control: -Target Test on the marked loopback test machine passes the guard' -Condition ($run.Message -match 'Unable to inspect existing remote file') -Detail $run.Message
    $run = Invoke-TgtDeploy -HostAlias 'ecco-ha' -Facts @{ Resolved = 'fictional.example.invalid'; Marker = $goodMarker; Machine = 'example-machine' }
    Assert-True -Name 'the production alias with no -Target means Production: the marker check runs and refuses a marked host' -Condition (
        $run.Message -match '-Target Production, but the test-instance marker') -Detail $run.Message
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Production'; SshConfigFile = $sshConfigFile } -Facts @{ Resolved = 'fictional.example.invalid'; Machine = 'example-machine' }
    Assert-True -Name '-SshConfigFile with -Target Production is refused before any ssh call' -Condition (
        $run.Message -match 'accepted with -Target Test only' -and $run.Sent.Count -eq 0) -Detail $run.Message
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test'; SshConfigFile = $sshConfigFile } -Facts @{ Marker = $goodMarker }
    Assert-True -Name '-SshConfigFile with -Target Test: every ssh call (ssh -G included) carries -F <file>' -Condition (
        $run.Message -match 'Unable to inspect existing remote file' -and $run.Sent.Count -ge 5 -and @($run.Sent | Where-Object { -not $_.EndsWith(' [-F]') }).Count -eq 0) -Detail ($run.Sent -join ' | ')
    $run = Invoke-TgtDeploy -Extra @{ Target = 'Test'; SshConfigFile = (Join-Path $kitBase 'no-such-config') } -Facts @{ Marker = $goodMarker }
    Assert-True -Name '-SshConfigFile that does not exist is refused before any ssh call' -Condition ($run.Message -match 'not an existing file' -and $run.Sent.Count -eq 0) -Detail $run.Message
    $run = Invoke-TgtDeploy -HostAlias '-oProxyCommand=example' -Extra @{ Target = 'Test' }
    Assert-True -Name 'an -SshHost that would be read as an ssh option is refused before any ssh call' -Condition ($run.Message -match 'not a plain ssh host alias' -and $run.Sent.Count -eq 0) -Detail $run.Message

    # The kit commands: -Target always required, refused before any ssh call.
    $global:EccoTgtLog.Clear()
    $m = Get-RefusalMessage { & (Join-Path $kitRepo 'tools\deploy-ha-kit.ps1') -Action Plan -SshHost 'ecco-ha' -ExpectedHaVersion '2030.1.0' -Kit $kitV1 -ExpectedSumsSha256 $kitV1Sha -SkipValidation -Python $Python 6>$null }
    Assert-True -Name 'deploy-ha-kit.ps1 with no -Target is refused before any ssh call, even for the production alias' -Condition (
        $m -match '^DEPLOY_TARGET: BLOCKED' -and $m -match 'Nothing was sent' -and $global:EccoTgtLog.Count -eq 0) -Detail $m
    $m = Get-RefusalMessage { & (Join-Path $kitRepo 'tools\place-ha-site-file.ps1') -SiteFile (Join-Path $kitBase 'none.json') -ExpectedSha256 ('0' * 64) -SshHost 'ecco-ha-test' 6>$null }
    Assert-True -Name 'place-ha-site-file.ps1 with no -Target is refused before any ssh call' -Condition ($m -match '^DEPLOY_TARGET: BLOCKED' -and $global:EccoTgtLog.Count -eq 0) -Detail $m
    $m = Get-RefusalMessage { & (Join-Path $kitRepo 'tools\deploy-ha-kit.ps1') -Action Install -SshHost 'ecco-ha' -Target Production -ExpectedHaVersion '2030.1.0' -Kit $kitV1 -ExpectedSumsSha256 $kitV1Sha -SkipValidation -Python $Python 6>$null }
    Assert-True -Name 'deploy-ha-kit.ps1 -Target Production without -ReferenceKit (the L3-tested kit) is refused before any ssh call' -Condition (
        $m -match 'needs -ReferenceKit' -and $global:EccoTgtLog.Count -eq 0) -Detail $m
    $m = Get-RefusalMessage { & (Join-Path $kitRepo 'tools\deploy-ha-kit.ps1') -Action Install -SshHost 'ecco-ha-test' -Target Test -ExpectedHaVersion '2030.1.0' -Kit $kitV1 -ExpectedSumsSha256 ('0' * 64) -SkipValidation -Python $Python 6>$null }
    Assert-True -Name 'deploy-ha-kit.ps1 with a kit that does not verify is refused before any ssh call' -Condition (
        $m -match 'the kit does not verify' -and $global:EccoTgtLog.Count -eq 0) -Detail $m
}
finally {
    Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath function:global:scp -ErrorAction SilentlyContinue
    Remove-Variable -Name EccoTgtLog, EccoTgt -Scope Global -ErrorAction SilentlyContinue
    Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force
}

# ---------------------------------------------------------------------
# Sections 19-23 share a fictional /config tree: the stubbed ssh runs each
# command under the local POSIX sh with /config mapped to the tree (and
# the tree's path mapped back in the output), answers ssh -G and the two
# ha commands itself, and records every command; the stubbed scp copies
# into and out of the tree. A hook can change one command (a race, a lost
# connection) and the scp stub can flip one byte of an upload.
# ---------------------------------------------------------------------
$kitHostWin = Join-Path $kitBase 'host'
$kitHostSh = $null
if ($Sh -and (Test-Path -LiteralPath $Sh)) {
    New-Item -ItemType Directory -Path $kitHostWin | Out-Null
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $kitHostSh = (@(& $Sh -c "cygpath -u '$kitHostWin'" 2>&1) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $kitHostSh.StartsWith('/') -or $kitHostSh.Contains("'")) { $kitHostSh = $null }
    if ($kitHostSh) {
        # The physical form (cd -P, pwd -P), as the /config probe prints it (amendment A26), so it maps back in the output.
        $kitHostSh = (@(& $Sh -c "cd -P '$kitHostSh' && pwd -P" 2>&1) -join '').Trim()
        if ($LASTEXITCODE -ne 0 -or -not $kitHostSh.StartsWith('/') -or $kitHostSh.Contains("'")) { $kitHostSh = $null }
    }
    $ErrorActionPreference = $previousEap
}
if ($kitHostSh) {
    $global:EccoKitSh = $Sh
    $global:EccoKitTreeWin = $kitHostWin
    $global:EccoKitTreeSh = $kitHostSh
    $global:EccoKitLog = New-Object System.Collections.Generic.List[string]
    $global:EccoKitTagged = New-Object System.Collections.Generic.List[bool]
    $global:EccoKitAll = New-Object System.Collections.Generic.List[string]
    $global:EccoKitResolved = 'fictional.example.invalid'
    $global:EccoKitMachine = 'example-machine'
    $global:EccoKitCheckFailures = 0
    $global:EccoKitHook = $null
    $global:EccoKitScpCorrupt = ''
    $global:EccoKitScpFail = ''
    try {
        function global:ssh {
            $tagged = $args -ccontains '-F'
            $command = [string]$args[$args.Count - 1]
            if ($args -ccontains '-G') {
                $global:EccoKitLog.Add('ssh -G ' + $command)
                $global:EccoKitTagged.Add($tagged)
                $global:LASTEXITCODE = 0
                return "hostname $($global:EccoKitResolved)"
            }
            $global:EccoKitLog.Add($command)
            $global:EccoKitAll.Add($command)
            $global:EccoKitTagged.Add($tagged)
            if ($command -ceq 'ha core check') {
                if ($global:EccoKitCheckFailures -gt 0) {
                    $global:EccoKitCheckFailures--
                    $global:LASTEXITCODE = 1
                    return 'fictional host: configuration check failed'
                }
                $global:LASTEXITCODE = 0
                return 'Command completed successfully.'
            }
            if ($command -ceq 'ha core info --raw-json') {
                $global:LASTEXITCODE = 0
                return ('{"result": "ok", "data": {"machine": "' + $global:EccoKitMachine + '"}}')
            }
            if ($command.StartsWith('ha ')) {
                $global:LASTEXITCODE = 64
                return 'fictional ha stub: refused'
            }
            $override = $null
            if ($global:EccoKitHook) { $override = & $global:EccoKitHook $command }
            $run = $command
            if ($override -and $override.ContainsKey('Command')) { $run = $override.Command }
            $out = @()
            $code = 0
            if (-not ($override -and $override.ContainsKey('Skip'))) {
                # /config and the real folders a symlinked /config resolves to (section 23) map into the tree; the tree's
                # path maps back to / in the output.
                $local = [regex]::Replace($run, "'/(config|example_config_real|example_config_moved)(?=[/'])", "'" + $global:EccoKitTreeSh + '/$1')
                $previousEap = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    $out = @(& $global:EccoKitSh -c $local 2>&1 | ForEach-Object { ([string]$_).Replace($global:EccoKitTreeSh + '/', '/') })
                    $code = $LASTEXITCODE
                } finally {
                    $ErrorActionPreference = $previousEap
                }
            }
            if ($override -and $override.ContainsKey('After')) { & $override.After }
            if ($override -and $override.ContainsKey('ExitCode')) { $code = $override.ExitCode }
            if ($override -and $override.ContainsKey('Output')) { $out = @($override.Output) }
            $global:LASTEXITCODE = $code
            return $out
        }
        function global:scp {
            $list = New-Object System.Collections.Generic.List[string]
            $tagged = $false
            $i = 0
            while ($i -lt $args.Count) {
                $a = [string]$args[$i]
                if ($a -ceq '-q') { $i++; continue }
                if ($a -ceq '-F') { $tagged = $true; $i += 2; continue }
                $list.Add($a)
                $i++
            }
            $global:EccoKitTagged.Add($tagged)
            $target = $list[$list.Count - 1]
            $global:LASTEXITCODE = 1
            try {
                if ($target -cmatch '^fictional-host:(/config/.*)$') {
                    $remote = $Matches[1]
                    $global:EccoKitLog.Add('scp-up ' + $remote)
                    $global:EccoKitAll.Add('scp-up ' + $remote)
                    $base = Join-Path $global:EccoKitTreeWin ($remote.TrimEnd('/').Substring(1).Replace('/', '\'))
                    for ($j = 0; $j -lt $list.Count - 1; $j++) {
                        $leaf = Split-Path -Path $list[$j] -Leaf
                        $dest = if ($remote.EndsWith('/')) { Join-Path $base $leaf } else { $base }
                        # A failed upload that creates no file on the host (scp exits 1).
                        if ($global:EccoKitScpFail -and $leaf -ceq $global:EccoKitScpFail) { throw 'fictional scp failure' }
                        Copy-Item -LiteralPath $list[$j] -Destination $dest -ErrorAction Stop
                        if ($global:EccoKitScpCorrupt -and ($leaf -ceq $global:EccoKitScpCorrupt -or (Split-Path -Path $dest -Leaf) -ceq $global:EccoKitScpCorrupt)) {
                            $b = [System.IO.File]::ReadAllBytes($dest)
                            $b[0] = $b[0] -bxor 1
                            [System.IO.File]::WriteAllBytes($dest, $b)
                        }
                    }
                    $global:LASTEXITCODE = 0
                } elseif ($list.Count -eq 2 -and $list[0] -cmatch '^fictional-host:(/config/.*)$') {
                    $global:EccoKitLog.Add('scp-down ' + $Matches[1])
                    Copy-Item -LiteralPath (Join-Path $global:EccoKitTreeWin ($Matches[1].Substring(1).Replace('/', '\'))) -Destination $target -ErrorAction Stop
                    $global:LASTEXITCODE = 0
                }
            } catch {
                $global:LASTEXITCODE = 1
            }
        }

        $siteOld = "{`"_note`": `"fictional test data`", `"sentinel`": `"ECCO-FICTIONAL-SENTINEL-OLD-4d2c`"}`n"
        function Get-HostPath {
            param([string]$Remote)
            return (Join-Path $global:EccoKitTreeWin ($Remote.Substring(1).Replace('/', '\')))
        }
        # A fresh fictional host: custom_components with another integration, ecco/ (dashboards, the site file and its state),
        # packages, www/ecco, .storage with a config-entry store, .HA_VERSION 2030.1.0. -InstallKit copies a kit's package into place.
        function Reset-KitHost {
            param([string]$InstallKit = '')
            Remove-KitJunctions
            if (Test-Path -LiteralPath $global:EccoKitTreeWin) { Remove-Item -LiteralPath $global:EccoKitTreeWin -Recurse -Force }
            foreach ($dir in @('config\custom_components\other_integration', 'config\ecco\intelligence\state', 'config\ecco\dashboards', 'config\.storage', 'config\packages', 'config\www\ecco')) {
                New-Item -ItemType Directory -Path (Join-Path $global:EccoKitTreeWin $dir) -Force | Out-Null
            }
            [System.IO.File]::WriteAllText((Get-HostPath '/config/.HA_VERSION'), "2030.1.0`n")
            [System.IO.File]::WriteAllText((Get-HostPath '/config/ecco/intelligence/site.local.json'), $siteOld)
            [System.IO.File]::WriteAllText((Get-HostPath '/config/ecco/intelligence/state/history.json'), "{}`n")
            [System.IO.File]::WriteAllText((Get-HostPath '/config/.storage/core.config_entries'), "{`n  `"data`": {`n    `"entries`": [`n      {`n        `"domain`": `"example_other`"`n      }`n    ]`n  }`n}`n")
            [System.IO.File]::WriteAllText((Get-HostPath '/config/custom_components/other_integration/manifest.json'), "{`"domain`": `"other_integration`"}`n")
            if ($InstallKit) {
                Copy-Item -LiteralPath (Join-Path $InstallKit 'custom_components\ecco_intelligence') -Destination (Get-HostPath '/config/custom_components') -Recurse
            }
        }
        function Add-HostPycache {
            foreach ($rel in @('__pycache__\__init__.cpython-313.pyc', 'runtime\__pycache__\__init__.cpython-313.pyc')) {
                $p = Join-Path (Get-HostPath '/config/custom_components/ecco_intelligence') $rel
                New-Item -ItemType Directory -Path (Split-Path $p -Parent) -Force | Out-Null
                [System.IO.File]::WriteAllBytes($p, [byte[]](1, 2, 3, 4))
            }
        }
        # rel -> sha256 of every file under a local folder ('/' separators); __pycache__ left out with -IgnorePycache.
        function Get-LocalFileMap {
            param([string]$Root, [switch]$IgnorePycache)
            $map = @{}
            if (-not (Test-Path -LiteralPath $Root)) { return $null }
            $prefix = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\') + '\'
            foreach ($f in @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force)) {
                $rel = $f.FullName.Substring($prefix.Length).Replace('\', '/')
                if ($IgnorePycache -and ($rel -match '(^|/)__pycache__/')) { continue }
                $map[$rel] = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash.ToLowerInvariant()
            }
            return $map
        }
        function Test-SameMap {
            param([object]$A, [object]$B)
            if ($null -eq $A -or $null -eq $B -or $A.Count -ne $B.Count) { return $false }
            foreach ($k in $A.Keys) { if (-not $B.ContainsKey($k) -or $B[$k] -ne $A[$k]) { return $false } }
            return $true
        }
        function Get-OrdinalSorted {
            param([string[]]$Items)
            $a = [string[]]@($Items)
            [Array]::Sort($a, [System.StringComparer]::Ordinal)
            return $a
        }
        function Get-StateInode {
            $previousEap = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try { return ((@(& $Sh -c "stat -c '%d:%i' '$kitHostSh/config/ecco/intelligence/state'" 2>&1) -join '').Trim()) } finally { $ErrorActionPreference = $previousEap }
        }
        # A command that only reads: the probes and listings ("if [ -L"), the ssh probe, the marker read, ha core info, .HA_VERSION,
        # stat/df, sha256sum, ssh -G and scp from the host. Anything with mkdir, mv, cp, rm, ha core check or a redirection writes.
        function Test-KitReadOnly {
            param([string]$Entry)
            if ($Entry.StartsWith('scp-up ')) { return $false }
            if ($Entry.StartsWith('scp-down ') -or $Entry.StartsWith('ssh -G ')) { return $true }
            if ($Entry -match 'mkdir|\bmv\b|\bcp\b|\brm\b|ha core check|restart|>') { return $false }
            return ($Entry -cmatch "^(if \[ -L '|true$|head -c 200 '|ha core info --raw-json$|cat '/config/\.HA_VERSION'$|stat -c '%d %n' |sha256sum ')")
        }
        function Invoke-KitRun {
            param([string]$Script = 'deploy-ha-kit.ps1', [hashtable]$Params)
            $global:EccoKitLog.Clear()
            $global:EccoKitTagged.Clear()
            $lines = New-Object System.Collections.Generic.List[string]
            $message = ''
            try {
                & (Join-Path $kitRepo "tools\$Script") @Params *>&1 | ForEach-Object { $lines.Add([string]$_) }
            } catch {
                $message = $_.Exception.Message
            }
            $sent = @($global:EccoKitLog)
            return [pscustomobject]@{ Message = $message; Lines = @($lines); Text = (@($lines) -join "`n"); Sent = $sent; Writes = @($sent | Where-Object { -not (Test-KitReadOnly $_) }); Tagged = @($global:EccoKitTagged) }
        }
        function Get-KitParams {
            param([string]$Action, [string]$KitDir = '', [hashtable]$Extra = @{})
            $p = @{ Action = $Action; SshHost = 'fictional-host'; Target = 'Production'; ExpectedHaVersion = '2030.1.0'; SkipValidation = $true; Python = $Python; Stamp = (Get-NextKitStamp) }
            if ($KitDir) {
                $s = Get-KitSumsSha -KitDir $KitDir
                $p.Kit = $KitDir
                $p.ExpectedSumsSha256 = $s
                $p.ReferenceKit = $KitDir
                $p.ReferenceSumsSha256 = $s
            }
            foreach ($k in $Extra.Keys) { $p[$k] = $Extra[$k] }
            return $p
        }
        function Assert-KitBlocked {
            param([string]$Name, [object]$Run, [string]$Pattern)
            Assert-True -Name $Name -Condition ($Run.Message -match $Pattern -and $Run.Sent.Count -gt 0 -and $Run.Writes.Count -eq 0) -Detail ($Run.Message + ' || writes: ' + ($Run.Writes -join ' | '))
        }
        function Get-HostState {
            # The fictional host's whole file set (rel -> sha256), to prove a BLOCK changed nothing.
            return (Get-LocalFileMap -Root (Join-Path $global:EccoKitTreeWin 'config'))
        }
        $kitV1Map = Get-LocalFileMap -Root (Join-Path $kitV1 'custom_components\ecco_intelligence')
        $installedRoot = Get-HostPath '/config/custom_components/ecco_intelligence'
        $policyGeneric = Join-Path $kitBase 'policy-generic.yaml'
        $policyLive = Join-Path $kitBase 'policy-live.yaml'
        [System.IO.File]::WriteAllText($policyGeneric, ($genericText -join "`n"))
        [System.IO.File]::WriteAllText($policyLive, ($liveText -join "`n"))
        function New-KitPolicy {
            # A fictional site policy (the guard's make-policy) that protects -Destination; the live file is written on the host too.
            param([string]$Destination)
            $out = Join-Path $kitBase ('policy-' + [guid]::NewGuid().ToString('N') + '.json')
            $previousEap = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $Destination --base $policyGeneric --live $policyLive --pointer /views/0/sections/0/cards/0 --out $out 2>&1 | Out-Null
            $ErrorActionPreference = $previousEap
            New-Item -ItemType Directory -Path (Get-HostPath '/config/ecco/site-local') -Force | Out-Null
            Copy-Item -LiteralPath $out -Destination (Get-HostPath '/config/ecco/site-local/dashboard-protection.json') -Force
            New-Item -ItemType Directory -Path (Split-Path (Get-HostPath $Destination) -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $policyLive -Destination (Get-HostPath $Destination) -Force
        }

        # -------------------------------------------------------------
        # 19. Read-only BLOCK cases (design T3; critique test 8).
        # -------------------------------------------------------------
        Write-Host ''
        Write-Host '[19] The kit route against a fictional host: every BLOCK sends read-only commands and changes nothing'
        Reset-KitHost
        $before = Get-HostState
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV1)
        Assert-True -Name 'control: Plan on a fresh fictional host passes with read-only commands only, and says Install' -Condition (
            $run.Message -eq '' -and $run.Writes.Count -eq 0 -and $run.Text -match 'ECCO INTELLIGENCE KIT PLAN' -and $run.Text -match 'Action      : Install' -and
            (Test-SameMap (Get-HostState) $before)) -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))

        Reset-KitHost
        New-Item -ItemType Directory -Path (Get-HostPath '/config/ecco/site-local') -Force | Out-Null
        [System.IO.File]::WriteAllText((Get-HostPath '/config/ecco/site-local/dashboard-protection.json'), '{"schema": "ecco-dashboard-protection/1", "gate": "EXAMPLE_PRESERVE_GATE", "dashboards": [')
        $before = Get-HostState
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
        Assert-KitBlocked -Name 'a malformed site policy BLOCKS the kit route (the policy is read for every destination)' -Run $run -Pattern 'BLOCKED - the site policy .* is not valid'
        Assert-True -Name '... and the host is unchanged' -Condition (Test-SameMap (Get-HostState) $before)

        Reset-KitHost
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1 -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE' })
        Assert-KitBlocked -Name 'a pinned site gate with the host policy moved aside BLOCKS the kit route' -Run $run -Pattern 'no site policy on the host'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV1 -Extra @{ ExpectedSiteGate = 'DASHBOARD_PRESERVE_GATE' })
        Assert-True -Name '... and the one-run override -ExpectedSiteGate DASHBOARD_PRESERVE_GATE lets it through (Plan, reads only)' -Condition (
            $run.Message -eq '' -and $run.Writes.Count -eq 0 -and $run.Text -match 'Gate pin    : DASHBOARD_PRESERVE_GATE') -Detail $run.Message
        $kitPin = Get-EccoDashboardGatePinPath -RepoRoot $kitRepo
        try {
            [System.IO.File]::WriteAllText($kitPin, "EXAMPLE_PRESERVE_GATE`n")
            $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
            Assert-KitBlocked -Name 'the local pin file (git-ignored) is read by the kit route too: the same BLOCK, naming the pin file' -Run $run -Pattern 'the local pin file ecco_dashboard_gate\.local\.txt expects the site gate'
        } finally {
            Remove-Item -LiteralPath $kitPin -Force -ErrorAction SilentlyContinue
        }
        Reset-KitHost
        New-KitPolicy -Destination '/config/ecco/dashboards/ecco_pro.yaml'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV1 -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE' })
        Assert-True -Name 'control: with the site policy on the host and the site gate pinned, the kit route passes the gate (not a dashboard destination)' -Condition (
            $run.Message -eq '' -and $run.Text -match 'Gate        : not a dashboard destination \(site policy present\)' -and
            $run.Text -match 'Gate pin    : EXAMPLE_PRESERVE_GATE \(-ExpectedSiteGate\) - not a dashboard destination; site policy present: True') -Detail $run.Message
        Reset-KitHost
        New-KitPolicy -Destination '/config/custom_components/other_integration/panel.yaml'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
        Assert-KitBlocked -Name 'a site policy that names a file under /config/custom_components/ BLOCKS the kit route' -Run $run -Pattern 'names /config/custom_components/other_integration/panel\.yaml'

        Reset-KitHost
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1 -Extra @{ ExpectedHaVersion = '2030.2.0' })
        Assert-KitBlocked -Name 'a Home Assistant version other than -ExpectedHaVersion BLOCKS' -Run $run -Pattern "not the expected '2030\.2\.0'"

        $junctionCases = @(
            @{ Name = 'a symlinked /config/custom_components'; Link = '/config/custom_components'; Pattern = '/config/custom_components is link on the host'; Install = '' },
            @{ Name = 'critique test 8: a symlinked /config/ecco/staging BLOCKS before any write'; Link = '/config/ecco/staging'; Pattern = '/config/ecco/staging is link on the host'; Install = '' },
            @{ Name = 'a symlinked /config/ecco-backups'; Link = '/config/ecco-backups'; Pattern = '/config/ecco-backups is link on the host'; Install = '' },
            @{ Name = 'a symlink inside the installed integration'; Link = '/config/custom_components/ecco_intelligence/linked'; Pattern = 'not a folder or a regular file'; Install = $kitV1 })
        foreach ($case in $junctionCases) {
            Reset-KitHost -InstallKit $case.Install
            $linkPath = Get-HostPath $case.Link
            if (Test-Path -LiteralPath $linkPath) { Remove-Item -LiteralPath $linkPath -Recurse -Force }
            $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
            if (-not (New-KitJunction -Link $linkPath -Target $elsewhere)) {
                Write-Host "  SKIP  $($case.Name) (mklink /J could not create a junction here)"
                continue
            }
            $action = if ($case.Install) { 'Upgrade' } else { 'Install' }
            $run = Invoke-KitRun -Params (Get-KitParams -Action $action -KitDir $kitV1)
            Assert-KitBlocked -Name $case.Name -Run $run -Pattern $case.Pattern
            Assert-True -Name '... and nothing was created behind the symlink' -Condition (@(Get-ChildItem -LiteralPath $elsewhere -Force).Count -eq 0)
        }

        # The folder-creating command refuses a symlinked segment by itself too (behind the path-state probe).
        foreach ($case in @(
                @{ Name = 'a symlinked /config/ecco/staging'; Link = '/config/ecco/staging' },
                @{ Name = 'a symlinked /config/ecco'; Link = '/config/ecco' })) {
            Reset-KitHost
            $linkPath = Get-HostPath $case.Link
            if (Test-Path -LiteralPath $linkPath) { Remove-Item -LiteralPath $linkPath -Recurse -Force }
            $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
            if (-not (New-KitJunction -Link $linkPath -Target $elsewhere)) {
                Write-Host "  SKIP  the mkdir command alone refuses $($case.Name) (mklink /J could not create a junction here)"
                continue
            }
            $mk = Get-EccoSafeMkdirCommand -ConfigRoot '/config' -MustExist @('/config/ecco') -MayCreate @('/config/ecco/staging') -MustCreate @('/config/ecco/staging/20300101-999999', '/config/ecco/staging/20300101-999999/new')
            $r = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mk -Capture
            Assert-True -Name "the folder-creating command alone refuses $($case.Name): no ECCO_MKDIR_OK, nothing created behind it, and no recursive mkdir" -Condition (
                @($r.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 0 -and @(Get-ChildItem -LiteralPath $elsewhere -Force).Count -eq 0 -and
                $mk -notmatch 'mkdir -p') -Detail (($r.Output -join ' | ') + ' || ' + $mk)
        }
        Reset-KitHost
        $mk = Get-EccoSafeMkdirCommand -ConfigRoot '/config' -MustExist @('/config/ecco') -MayCreate @('/config/ecco/staging') -MustCreate @('/config/ecco/staging/20300101-999999', '/config/ecco/staging/20300101-999999/new')
        $r = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mk -Capture
        $r2 = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mk -Capture
        Assert-True -Name 'control: on real folders it creates the staging folder one level at a time, and a stamp that exists is refused the second time' -Condition (
            @($r.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 1 -and (Test-Path -LiteralPath (Get-HostPath '/config/ecco/staging/20300101-999999/new')) -and
            @($r2.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 0) -Detail ($r.Output -join ' | ')

        Reset-KitHost
        $global:EccoKitHook = { param($c) if ($c.StartsWith("stat -c '%d %n'")) { return @{ Skip = $true; ExitCode = 0; Output = @('11 /config/custom_components', '12 /config/ecco', 'Filesystem 1024-blocks Used Available Capacity Mounted on', 'example 9000000 1000 8999000 1% /config', 'ECCO_FS_END') } }; return $null }
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
        Assert-KitBlocked -Name 'custom_components and ecco/ on different devices BLOCK (the swap would not be an atomic rename)' -Run $run -Pattern 'different devices'
        $global:EccoKitHook = { param($c) if ($c.StartsWith("stat -c '%d %n'")) { return @{ Skip = $true; ExitCode = 0; Output = @('11 /config/custom_components', '11 /config/ecco', 'Filesystem 1024-blocks Used Available Capacity Mounted on', 'example 9000000 8999900 100 99% /config', 'ECCO_FS_END') } }; return $null }
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
        Assert-KitBlocked -Name 'too little free space under /config BLOCKS' -Run $run -Pattern 'KiB are free'
        $global:EccoKitHook = $null

        Reset-KitHost -InstallKit $kitV1
        [System.IO.File]::WriteAllText((Join-Path $installedRoot 'bad name.py'), "x = 1`n")
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV1)
        Assert-KitBlocked -Name 'an installed name that is not safe to quote (a space) BLOCKS' -Run $run -Pattern 'not safe to handle'
        Reset-KitHost -InstallKit $kitV1
        [System.IO.File]::WriteAllText((Join-Path $installedRoot 'notes.txt'), "x`n")
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV1)
        Assert-KitBlocked -Name 'an installed file no kit could have written BLOCKS' -Run $run -Pattern 'which no kit could have written'

        Reset-KitHost -InstallKit $kitV1
        $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV1)
        Assert-KitBlocked -Name '-Action Install over an installed integration BLOCKS (use Upgrade)' -Run $run -Pattern 'use -Action Upgrade'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV1)
        Assert-KitBlocked -Name '-Action Upgrade to the installed kit itself BLOCKS (NO CHANGE)' -Run $run -Pattern 'NO CHANGE'
        Reset-KitHost
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV1)
        Assert-KitBlocked -Name '-Action Upgrade with nothing installed BLOCKS (use Install)' -Run $run -Pattern 'use -Action Install'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
        Assert-KitBlocked -Name '-Action Uninstall with nothing installed BLOCKS' -Run $run -Pattern 'needs an installed integration'

        Reset-KitHost -InstallKit $kitV1
        [System.IO.File]::WriteAllText((Get-HostPath '/config/.storage/core.config_entries'), "{`n  `"data`": {`n    `"entries`": [`n      {`n        `"domain`": `"ecco_intelligence`"`n      }`n    ]`n  }`n}`n")
        $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
        Assert-KitBlocked -Name '-Action Uninstall while a config entry names ecco_intelligence BLOCKS (only the count leaves the host)' -Run $run -Pattern 'delete the integration''s entry'

        # Review DR-3: Uninstall while the config-entry store cannot be read - absent, a symlink (a junction), or a grep that
        # fails (with an error message, silently, or printing a partial count after a read error), or a lost connection -
        # BLOCKS with nothing written: the count is unknown, never taken as 0.
        $entriesPath = Get-HostPath '/config/.storage/core.config_entries'
        $dr3Pattern = 'INTELLIGENCE_KIT: BLOCKED - the count of config-entry lines naming ecco_intelligence cannot be read'
        Reset-KitHost -InstallKit $kitV1
        Remove-Item -LiteralPath $entriesPath -Force
        $before = Get-HostState
        $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
        Assert-KitBlocked -Name 'DR-3: -Action Uninstall with no config-entry store BLOCKS (the count cannot be read), nothing written' -Run $run -Pattern $dr3Pattern
        Assert-True -Name '... the host is unchanged and the integration still installed' -Condition (
            (Test-SameMap (Get-HostState) $before) -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map))
        Reset-KitHost -InstallKit $kitV1
        Remove-Item -LiteralPath $entriesPath -Force
        $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
        if (New-KitJunction -Link $entriesPath -Target $elsewhere) {
            $before = Get-HostState
            $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
            Assert-KitBlocked -Name 'DR-3: -Action Uninstall with the config-entry store a symlink BLOCKS (the count cannot be read), nothing written' -Run $run -Pattern $dr3Pattern
            Assert-True -Name '... the host is unchanged, nothing created behind the symlink, and the integration still installed' -Condition (
                (Test-SameMap (Get-HostState) $before) -and @(Get-ChildItem -LiteralPath $elsewhere -Force).Count -eq 0 -and (Test-Path -LiteralPath (Join-Path $installedRoot 'manifest.json')))
        } else {
            Write-Host '  SKIP  DR-3: Uninstall with the config-entry store a symlink (mklink /J could not create a junction here)'
        }
        $entriesGrep = "grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'"
        foreach ($case in @(
                @{ Name = 'a grep that fails with an error message'; Hook = { param($c) if ($c.Contains("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'")) { return @{ Command = $c.Replace("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'", "grep -c 'ecco_intelligence' '/config/.storage/core.config_entries/example_missing'") } }; return $null } },
                @{ Name = 'a grep that fails silently'; Hook = { param($c) if ($c.Contains("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'")) { return @{ Command = $c.Replace("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'", 'false') } }; return $null } },
                @{ Name = 'a grep that prints a partial count after a read error'; Hook = { param($c) if ($c.Contains("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'")) { return @{ Skip = $true; ExitCode = 0; Output = @('grep: /config/.storage/core.config_entries: Input/output error', '0', 'ECCO_ENTRIES_END') } }; return $null } },
                @{ Name = 'a lost connection (ssh exit 255)'; Hook = { param($c) if ($c.Contains("grep -c 'ecco_intelligence' '/config/.storage/core.config_entries'")) { return @{ Skip = $true; ExitCode = 255; Output = @('ssh: connection lost (fictional)') } }; return $null } })) {
            Reset-KitHost -InstallKit $kitV1
            $before = Get-HostState
            $global:EccoKitHook = $case.Hook
            try {
                $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
            } finally {
                $global:EccoKitHook = $null
            }
            Assert-KitBlocked -Name "DR-3: -Action Uninstall with $($case.Name) on the config-entry store BLOCKS (the count cannot be read), nothing written" -Run $run -Pattern $dr3Pattern
            Assert-True -Name '... the count command was sent, and the host is unchanged' -Condition (
                @($run.Sent | Where-Object { $_.Contains($entriesGrep) }).Count -eq 1 -and (Test-SameMap (Get-HostState) $before)) -Detail ($run.Sent -join ' | ')
        }
        # Control: the same store, readable and naming no ecco_intelligence entry, reads as 0 (Plan prints the count).
        Reset-KitHost -InstallKit $kitV1
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV1)
        Assert-True -Name 'DR-3 control: a readable config-entry store with no ecco_intelligence line reads as 0' -Condition (
            $run.Message -eq '' -and $run.Text -match 'Config entry: 0 line\(s\) naming ecco_intelligence') -Detail $run.Message

        Reset-KitHost -InstallKit $kitV1
        $bk = Get-HostPath '/config/ecco-backups/20291231-000000'
        New-Item -ItemType Directory -Path $bk -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $kitV1 'custom_components\ecco_intelligence') -Destination (Join-Path $bk 'custom_components__ecco_intelligence') -Recurse
        $bkText = -join (@(Get-OrdinalSorted -Items @($kitV1Map.Keys)) | ForEach-Object { "$($kitV1Map[$_])  $_`n" })
        [System.IO.File]::WriteAllBytes((Join-Path $bk 'BACKUP_SHA256SUMS'), [System.Text.Encoding]::ASCII.GetBytes($bkText))
        [System.IO.File]::WriteAllText((Join-Path $bk 'custom_components__ecco_intelligence\const.py'), "VALUE = 9`n")
        $run = Invoke-KitRun -Params (Get-KitParams -Action Rollback -Extra @{ BackupStamp = '20291231-000000' })
        Assert-KitBlocked -Name '-Action Rollback from a backup that does not match its BACKUP_SHA256SUMS BLOCKS' -Run $run -Pattern 'does not match its BACKUP_SHA256SUMS: .*const\.py does not have the expected sha256'

        # -------------------------------------------------------------
        # 20. End to end (design T4, test-HA T5).
        # -------------------------------------------------------------
        Write-Host ''
        Write-Host '[20] The kit route end to end on a fictional /config: install, upgrade, rollbacks, uninstall; nothing deleted'
        $global:EccoKitAll.Clear()
        Reset-KitHost
        $siteBytes = [System.IO.File]::ReadAllBytes((Get-HostPath '/config/ecco/intelligence/site.local.json'))
        $inodeBefore = Get-StateInode
        $p = Get-KitParams -Action Install -KitDir $kitV1
        $run = Invoke-KitRun -Params $p
        $stampInstall = $p.Stamp
        Assert-True -Name 'Install: ECCO INTELLIGENCE KIT INSTALL PASSED and the installed tree equals the kit, file for file' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO INTELLIGENCE KIT INSTALL PASSED' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail ($run.Message + ' || ' + ($run.Lines | Select-Object -Last 5) -join ' | ')
        Assert-True -Name 'Install: the site file bytes and the state folder (device:inode) are unchanged' -Condition (
            ([System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes((Get-HostPath '/config/ecco/intelligence/site.local.json'))) -ceq [System.Convert]::ToBase64String($siteBytes)) -and
            (Get-StateInode) -ceq $inodeBefore -and $inodeBefore -match '^[0-9]+:[0-9]+$')
        Assert-True -Name 'Install: every upload went to the staging folder outside custom_components, never into place directly' -Condition (
            @($run.Sent | Where-Object { $_.StartsWith('scp-up ') }).Count -ge 4 -and
            @($run.Sent | Where-Object { $_.StartsWith('scp-up ') -and -not $_.StartsWith("scp-up /config/ecco/staging/$stampInstall/new/ecco_intelligence") }).Count -eq 0) -Detail ($run.Sent -join ' | ')
        Assert-True -Name 'Install: the PASSED block says RESTART REQUIRED (not performed), to keep the pause helper ON, and how to undo' -Condition (
            $run.Text -match 'RESTART REQUIRED - separately gated, not performed' -and $run.Text -match 'Keep input_boolean\.ecco_intel_paused ON' -and
            $run.Text -match 'To undo     : \.\\tools\\deploy-ha-kit\.ps1 -Action Uninstall') -Detail $run.Text
        Assert-True -Name 'Install with -Target Production and no -SshConfigFile: the To undo line names no -SshConfigFile' -Condition (
            $run.Text.Contains('To undo     : .\tools\deploy-ha-kit.ps1 -Action Uninstall -SshHost fictional-host -Target Production -ExpectedHaVersion 2030.1.0 (refused while a config entry exists)') -and
            $run.Text -notmatch 'SshConfigFile') -Detail $run.Text
        Assert-True -Name 'Install: the staging copy was moved into place (the staging folder is kept, nothing deleted)' -Condition (
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$stampInstall/new")) -and -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$stampInstall/new/ecco_intelligence")))

        # Kit v2: one engine file changes; a new commit; Home Assistant has written __pycache__ into the v1 tree.
        [System.IO.File]::WriteAllText((Join-Path $kitRepo 'kit-src\_vendor\intelligence\example_engine.py'), "def run():`n    return 2`n")
        Invoke-KitGit -Repo $kitRepo -GitArgs @('commit', '-q', '-a', '-m', 'fictional kit source v2') | Out-Null
        $kitV2 = Join-Path $kitBase 'kit-v2'
        Invoke-FictionalBuild -Repo $kitRepo -Out $kitV2 -GitSha (Get-KitRepoHead -Repo $kitRepo) | Out-Null
        $kitV2Map = Get-LocalFileMap -Root (Join-Path $kitV2 'custom_components\ecco_intelligence')
        Add-HostPycache

        $global:EccoKitCheckFailures = 1
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $run = Invoke-KitRun -Params $p
        $global:EccoKitCheckFailures = 0
        Assert-True -Name 'Upgrade whose ha core check fails: "was rolled back", the v1 tree is back in place, and the v2 tree moved to staging/<stamp>/failed (not deleted)' -Condition (
            $run.Message -match 'was rolled back' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot -IgnorePycache) $kitV1Map) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco/staging/$($p.Stamp)/failed/ecco_intelligence")) $kitV2Map) -and
            (Test-Path -LiteralPath (Join-Path $installedRoot '__pycache__\__init__.cpython-313.pyc'))) -Detail $run.Message

        $global:EccoKitScpCorrupt = 'example_engine.py'
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $run = Invoke-KitRun -Params $p
        $global:EccoKitScpCorrupt = ''
        Assert-True -Name 'Upgrade whose upload corrupts one byte: STOPPED before the swap, no swap sent, v1 still installed' -Condition (
            $run.Message -match 'STOPPED before the swap' -and $run.Message -match 'staged copy does not verify' -and
            @($run.Sent | Where-Object { $_ -match 'ECCO_SWAP' }).Count -eq 0 -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot -IgnorePycache) $kitV1Map)) -Detail $run.Message
        # Review DR3-2 (amendment A40), the control: once the folder-creating command reported success, a later stop keeps
        # this run's staging and backup stamp folders for inspection, and names exactly those two, which exist.
        Assert-True -Name 'DR3-2: ... after the folders were created, the message lists this run''s staging and backup stamp folders as kept for inspection, and both exist' -Condition (
            $run.Message.Contains("Kept for inspection (nothing is deleted): /config/ecco/staging/$($p.Stamp), /config/ecco-backups/$($p.Stamp)") -and
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$($p.Stamp)") -PathType Container) -and
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)") -PathType Container)) -Detail $run.Message

        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SWAP_DONE')) { return @{ ExitCode = 255; Output = @() } }; return $null }
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV2)
        $global:EccoKitHook = $null
        Assert-True -Name 'Upgrade whose swap ran but whose ssh reported exit 255: the rollback works out the state, "was rolled back", v1 in place' -Condition (
            $run.Message -match 'was rolled back' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot -IgnorePycache) $kitV1Map)) -Detail $run.Message
        Assert-True -Name 'L3W-6 control: ... an Upgrade''s step is still named the swap (message and rollback warning)' -Condition (
            $run.Message -match 'the swap did not complete, or its result could not be confirmed \(ssh exit code 255\)' -and
            @($run.Lines | Where-Object { $_.StartsWith('Rolling back the Intelligence kit swap: the swap did not complete') }).Count -eq 1) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))

        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SWAP_MOVED && ')) { return @{ Command = $c.Replace('echo ECCO_SWAP_MOVED && ', "echo ECCO_SWAP_MOVED && mkdir '/config/custom_components/ecco_intelligence' && ") } }; return $null }
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $run = Invoke-KitRun -Params $p
        $global:EccoKitHook = $null
        Assert-True -Name 'Upgrade where the folder reappears between the two renames: no nested ecco_intelligence/ecco_intelligence, and the rollback says it could NOT be confirmed (nothing touched)' -Condition (
            -not (Test-Path -LiteralPath (Join-Path $installedRoot 'ecco_intelligence')) -and $run.Message -match 'could NOT be confirmed' -and $run.Message -notmatch 'was rolled back' -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco/staging/$($p.Stamp)/previous/ecco_intelligence") -IgnorePycache) $kitV1Map) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco/staging/$($p.Stamp)/new/ecco_intelligence")) $kitV2Map)) -Detail $run.Message

        Reset-KitHost -InstallKit $kitV1
        Add-HostPycache
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $run = Invoke-KitRun -Params $p
        $stampUpgrade = $p.Stamp
        $backupCopy = Get-HostPath "/config/ecco-backups/$stampUpgrade/custom_components__ecco_intelligence"
        $expectedBackupSums = -join (@(Get-OrdinalSorted -Items @($kitV1Map.Keys)) | ForEach-Object { "$($kitV1Map[$_])  $_`n" })
        $actualBackupSums = if (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$stampUpgrade/BACKUP_SHA256SUMS")) { [System.IO.File]::ReadAllText((Get-HostPath "/config/ecco-backups/$stampUpgrade/BACKUP_SHA256SUMS")) } else { '' }
        Assert-True -Name 'Upgrade over a tree holding __pycache__: PASSED, v2 in place, and the backup verifies (its files and BACKUP_SHA256SUMS list v1, __pycache__ left out of the list)' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO INTELLIGENCE KIT UPGRADE PASSED' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV2Map) -and
            (Test-SameMap (Get-LocalFileMap -Root $backupCopy -IgnorePycache) $kitV1Map) -and $actualBackupSums -ceq $expectedBackupSums) -Detail ($run.Message + ' || ' + $actualBackupSums)
        Assert-True -Name '... the replaced tree (with its __pycache__) was moved to staging/<stamp>/previous, not deleted, and the PASSED block names Rollback -BackupStamp' -Condition (
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$stampUpgrade/previous/ecco_intelligence/__pycache__/__init__.cpython-313.pyc")) -and
            $run.Text -match "To undo     : \.\\tools\\deploy-ha-kit\.ps1 -Action Rollback -BackupStamp $stampUpgrade") -Detail $run.Text

        $p = Get-KitParams -Action Rollback -Extra @{ BackupStamp = $stampUpgrade }
        $run = Invoke-KitRun -Params $p
        Assert-True -Name 'Rollback -BackupStamp: PASSED, v1 restored from the verified backup, the v2 tree backed up and moved aside (nothing deleted)' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO INTELLIGENCE KIT ROLLBACK PASSED' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco-backups/$($p.Stamp)/custom_components__ecco_intelligence")) $kitV2Map) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco/staging/$($p.Stamp)/previous/ecco_intelligence")) $kitV2Map) -and
            (Test-SameMap (Get-LocalFileMap -Root $backupCopy -IgnorePycache) $kitV1Map)) -Detail $run.Message
        Assert-True -Name 'L3W-6 control: a swap (Rollback -BackupStamp) still prints "Swap done" and "Verified in place", and no move-aside line' -Condition (
            @($run.Lines | Where-Object { $_ -ceq 'Swap done: /config/custom_components/ecco_intelligence' }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -ceq 'Verified in place (every sha256; __pycache__ ignored).' }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_.StartsWith('Moved aside') }).Count -eq 0) -Detail ($run.Lines -join ' | ')

        Add-HostPycache
        $p = Get-KitParams -Action Uninstall
        $run = Invoke-KitRun -Params $p
        Assert-True -Name 'Uninstall (no config entry): PASSED, nothing installed, the tree and its __pycache__ moved to staging/<stamp>/uninstalled, a verified backup made' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO INTELLIGENCE KIT UNINSTALL PASSED' -and -not (Test-Path -LiteralPath $installedRoot) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco/staging/$($p.Stamp)/uninstalled/ecco_intelligence") -IgnorePycache) $kitV1Map) -and
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$($p.Stamp)/uninstalled/ecco_intelligence/runtime/__pycache__/__init__.cpython-313.pyc")) -and
            (Test-SameMap (Get-LocalFileMap -Root (Get-HostPath "/config/ecco-backups/$($p.Stamp)/custom_components__ecco_intelligence") -IgnorePycache) $kitV1Map)) -Detail $run.Message
        # Review L3W-6 (amendment A49): Uninstall's move aside is reported as a move aside, and its verification as the folder
        # absent with the moved tree verified - never "Swap done" or "Verified in place".
        Assert-True -Name 'L3W-6: Uninstall prints "Moved aside (not deleted): <install path> -> <staging>/uninstalled/..." and the verification at the moved-to path, never "Swap done" or "Verified in place"' -Condition (
            @($run.Lines | Where-Object { $_ -ceq "Moved aside (not deleted): /config/custom_components/ecco_intelligence -> /config/ecco/staging/$($p.Stamp)/uninstalled/ecco_intelligence" }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -ceq "Verified: /config/custom_components/ecco_intelligence is absent, and the moved tree at /config/ecco/staging/$($p.Stamp)/uninstalled/ecco_intelligence matches the installed one (every sha256; __pycache__ ignored)." }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_.StartsWith('Swap done') -or $_.StartsWith('Verified in place') }).Count -eq 0) -Detail ($run.Lines -join ' | ')

        # L3W-6: an Uninstall whose move aside ran but whose ssh reported exit 255: the rollback names the move aside (not a
        # swap), works out the state and renames the tree back.
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SWAP_DONE')) { return @{ ExitCode = 255; Output = @() } }; return $null }
        $p = Get-KitParams -Action Uninstall
        $run = Invoke-KitRun -Params $p
        $global:EccoKitHook = $null
        Assert-True -Name 'L3W-6: Uninstall whose move aside ran but whose ssh reported exit 255: the message names the move aside (never the swap), "was rolled back", the tree back in place' -Condition (
            $run.Message -match 'the move aside did not complete, or its result could not be confirmed \(ssh exit code 255\)' -and $run.Message -notmatch 'swap' -and
            $run.Message -match 'was rolled back' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map) -and
            @($run.Lines | Where-Object { $_.StartsWith('Rolling back the Intelligence kit move aside: the move aside did not complete') }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_.StartsWith('Moved aside') -or $_.StartsWith('Swap done') -or $_.StartsWith('Rolling back the Intelligence kit swap') }).Count -eq 0) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))

        # Review DRD-5 (amendment A52): an Uninstall whose ha core check fails after the move aside is rolled back as a
        # failure after the move aside, and an Uninstall stopped before it says "STOPPED before the move aside": never "swap".
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitCheckFailures = 1
        $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall)
        $global:EccoKitCheckFailures = 0
        Assert-True -Name 'DRD-5: Uninstall whose ha core check fails: the rollback reason is "failed after the move aside" (never the swap), "was rolled back", the tree back in place' -Condition (
            $run.Message.Contains('Home Assistant configuration check failed after the move aside.') -and $run.Message -notmatch 'swap' -and
            $run.Message -match 'was rolled back' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map) -and
            @($run.Lines | Where-Object { $_.StartsWith('Rolling back the Intelligence kit move aside: Home Assistant configuration check failed after the move aside.') }).Count -eq 1) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))
        Reset-KitHost -InstallKit $kitV1
        $p = Get-KitParams -Action Uninstall
        $global:EccoKitHookPath = Get-HostPath "/config/ecco-backups/$($p.Stamp)/custom_components__ecco_intelligence/const.py"
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_BACKUP_COPIED')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHookPath, ' ') } } }; return $null }
        $run = Invoke-KitRun -Params $p
        $global:EccoKitHook = $null
        Assert-True -Name 'DRD-5: Uninstall stopped by a backup copy that does not verify: "STOPPED before the move aside" (never the swap), nothing moved, v1 still installed' -Condition (
            $run.Message.Contains('INTELLIGENCE_KIT: STOPPED before the move aside - ') -and $run.Message -match 'the backup does not verify' -and
            $run.Message -notmatch 'swap' -and @($run.Sent | Where-Object { $_ -match 'ECCO_SWAP' }).Count -eq 0 -and
            (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail $run.Message
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_MKDIR_OK')) { return @{ Command = $c.Replace("grep -Fqx '/config'", "grep -Fqx '/example_moved_root'") } }; return $null }
        try { $run = Invoke-KitRun -Params (Get-KitParams -Action Uninstall) } finally { $global:EccoKitHook = $null }
        Assert-True -Name 'DRD-5: Uninstall whose folder-creating command fails: "STOPPED before the move aside - the staging and backup folders could not be created safely" (never the swap), v1 still installed' -Condition (
            $run.Message.StartsWith('INTELLIGENCE_KIT: STOPPED before the move aside - the staging and backup folders could not be created safely (') -and
            $run.Message -notmatch 'swap' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail $run.Message

        # Each verification layer on its own: a corrupted backup copy, a corrupted BACKUP_SHA256SUMS upload, a file changed in place
        # right after the swap, and the protected site file changed during the write.
        Reset-KitHost -InstallKit $kitV1
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $global:EccoKitHookPath = Get-HostPath "/config/ecco-backups/$($p.Stamp)/custom_components__ecco_intelligence/const.py"
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_BACKUP_COPIED')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHookPath, ' ') } } }; return $null }
        $run = Invoke-KitRun -Params $p
        $global:EccoKitHook = $null
        Assert-True -Name 'a backup copy that does not verify: STOPPED before the swap, v1 still installed' -Condition (
            $run.Message -match 'STOPPED before the swap' -and $run.Message -match 'the backup does not verify' -and
            @($run.Sent | Where-Object { $_ -match 'ECCO_SWAP' }).Count -eq 0 -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail $run.Message
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitScpCorrupt = 'BACKUP_SHA256SUMS'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV2)
        $global:EccoKitScpCorrupt = ''
        Assert-True -Name 'a BACKUP_SHA256SUMS upload that does not verify: STOPPED before the swap, v1 still installed' -Condition (
            $run.Message -match 'STOPPED before the swap' -and $run.Message -match 'BACKUP_SHA256SUMS does not verify' -and
            (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail $run.Message
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitHookPath = Join-Path $installedRoot 'const.py'
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SWAP_DONE')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHookPath, ' ') } } }; return $null }
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV2)
        $global:EccoKitHook = $null
        Assert-True -Name 'a file changed in place right after the swap: the in-place check fails, and the rollback touches nothing it cannot identify (NOT confirmed)' -Condition (
            $run.Message -match 'does not verify in place' -and $run.Message -match 'could NOT be confirmed' -and $run.Text -notmatch 'UPGRADE PASSED') -Detail $run.Message
        Reset-KitHost -InstallKit $kitV1
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SWAP_DONE')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHostSite, ' ') } } }; return $null }
        $global:EccoKitHostSite = Get-HostPath '/config/ecco/intelligence/site.local.json'
        $run = Invoke-KitRun -Params (Get-KitParams -Action Upgrade -KitDir $kitV2)
        $global:EccoKitHook = $null
        Assert-True -Name 'the protected site file changed during the write: rolled back to v1 ("was rolled back"), naming the protected snapshot' -Condition (
            $run.Message -match 'protected site file or state folder changed' -and $run.Message -match 'was rolled back' -and
            (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail $run.Message

        # Review DR3-2 (amendment A40): the folder-creating command does not report success. The stamp folders are never
        # listed as kept (this run may not have created them, and a used stamp's folder is an earlier run's); the message
        # says they may not have been created, that nothing installed changed and that nothing was deleted.
        $dr3MkdirStopped = 'INTELLIGENCE_KIT: STOPPED before the swap - the staging and backup folders could not be created safely'
        $dr3NothingInstalled = 'Nothing installed was changed: /config/custom_components/ecco_intelligence is as it was.'
        function Get-Dr3MkdirLine {
            param([string]$Stamp, [string]$Folders = 'staging and backup folders')
            return "The folder-creating command did not report success, so this run's $Folders (stamp $Stamp) may not have been created, or only in part, and no folder is listed as kept. Nothing was deleted."
        }
        function Test-Dr3NamesNoStampFolder {
            param([object]$Run, [string]$Stamp)
            return (-not $Run.Message.Contains('Kept for inspection') -and -not $Run.Message.Contains("/config/ecco/staging/$Stamp") -and -not $Run.Message.Contains("/config/ecco-backups/$Stamp"))
        }
        # The folder-creating command's own root test fails (it names another root), so it creates nothing.
        Reset-KitHost -InstallKit $kitV1
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_MKDIR_OK')) { return @{ Command = $c.Replace("grep -Fqx '/config'", "grep -Fqx '/example_moved_root'") } }; return $null }
        try { $run = Invoke-KitRun -Params $p } finally { $global:EccoKitHook = $null }
        Assert-True -Name 'DR3-2: Upgrade whose folder-creating command fails: STOPPED before the swap, nothing installed changed, the folders may not have been created and nothing was deleted; no folder listed as kept' -Condition (
            $run.Message.StartsWith($dr3MkdirStopped) -and $run.Message.Contains($dr3NothingInstalled) -and $run.Message.Contains((Get-Dr3MkdirLine -Stamp $p.Stamp)) -and
            (Test-Dr3NamesNoStampFolder -Run $run -Stamp $p.Stamp)) -Detail $run.Message
        Assert-True -Name '... neither stamp folder exists, v1 is still installed, and the folder-creating command was the only write (no upload)' -Condition (
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$($p.Stamp)")) -and -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)")) -and
            (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map) -and @($run.Writes).Count -eq 1 -and @($run.Writes)[0] -match '\bmkdir\b') -Detail ($run.Writes -join ' | ')
        # A stamp already used: its staging folder belongs to an earlier run and is never named as this run's.
        Reset-KitHost -InstallKit $kitV1
        $p = Get-KitParams -Action Upgrade -KitDir $kitV2
        $earlier = Get-HostPath "/config/ecco/staging/$($p.Stamp)"
        New-Item -ItemType Directory -Path $earlier -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $earlier 'example-earlier-run.txt'), "fictional`n")
        $run = Invoke-KitRun -Params $p
        Assert-True -Name 'DR3-2: Upgrade with a stamp already used: STOPPED before the swap with the same message; the earlier run''s staging folder is not listed as kept' -Condition (
            $run.Message.StartsWith($dr3MkdirStopped) -and $run.Message.Contains($dr3NothingInstalled) -and $run.Message.Contains((Get-Dr3MkdirLine -Stamp $p.Stamp)) -and
            (Test-Dr3NamesNoStampFolder -Run $run -Stamp $p.Stamp)) -Detail $run.Message
        Assert-True -Name '... the earlier folder holds only its own file, no backup stamp folder was made, and v1 is still installed' -Condition (
            ((@(Get-ChildItem -LiteralPath $earlier -Force | ForEach-Object { $_.Name })) -join ',') -ceq 'example-earlier-run.txt' -and
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)")) -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV1Map)) -Detail ((@(Get-ChildItem -LiteralPath $earlier -Force | ForEach-Object { $_.Name })) -join ',')
        # Review DR4R-2 (amendment A43): an Install creates no backup folder, so neither line of its mkdir-failure message
        # names one; the Reason is built from the folders this run tried to create.
        Reset-KitHost
        $p = Get-KitParams -Action Install -KitDir $kitV2
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_MKDIR_OK')) { return @{ Command = $c.Replace("grep -Fqx '/config'", "grep -Fqx '/example_moved_root'") } }; return $null }
        try { $run = Invoke-KitRun -Params $p } finally { $global:EccoKitHook = $null }
        Assert-True -Name 'DR4R-2: Install whose folder-creating command fails: the Reason names only the staging folder ("the staging folder could not be created safely"), the second line too, and no line names a backup folder' -Condition (
            $run.Message.StartsWith('INTELLIGENCE_KIT: STOPPED before the swap - the staging folder could not be created safely (') -and
            $run.Message.Contains($dr3NothingInstalled) -and $run.Message.Contains((Get-Dr3MkdirLine -Stamp $p.Stamp -Folders 'staging folder')) -and
            -not $run.Message.Contains('backup') -and (Test-Dr3NamesNoStampFolder -Run $run -Stamp $p.Stamp)) -Detail $run.Message
        Assert-True -Name '... no stamp folder exists, nothing is installed, and the folder-creating command was the only write' -Condition (
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco/staging/$($p.Stamp)")) -and -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)")) -and
            -not (Test-Path -LiteralPath $installedRoot) -and @($run.Writes).Count -eq 1 -and @($run.Writes)[0] -match '\bmkdir\b') -Detail ($run.Writes -join ' | ')

        # The isolated test instance: -Target Test through a harness-owned ssh configuration.
        Reset-KitHost
        $global:EccoKitResolved = '127.0.0.1'
        $global:EccoKitMachine = 'ecco-l3-test'
        [System.IO.File]::WriteAllText((Get-HostPath '/config/.ecco_l3_test_instance'), "$goodMarker`n")
        $p = Get-KitParams -Action Install -KitDir $kitV2 -Extra @{ Target = 'Test'; SshConfigFile = $sshConfigFile; ReferenceKit = $null; ReferenceSumsSha256 = $null }
        $run = Invoke-KitRun -Params $p
        $global:EccoKitResolved = 'fictional.example.invalid'
        $global:EccoKitMachine = 'example-machine'
        Assert-True -Name '-Target Test on the marked loopback test instance with -SshConfigFile: Install PASSED, and every ssh and scp call carried -F <file>' -Condition (
            $run.Message -eq '' -and $run.Text -match 'INSTALL PASSED' -and (Test-SameMap (Get-LocalFileMap -Root $installedRoot) $kitV2Map) -and
            @($run.Tagged).Count -ge 10 -and @($run.Tagged | Where-Object { -not $_ }).Count -eq 0) -Detail ($run.Message + ' || untagged: ' + @($run.Tagged | Where-Object { -not $_ }).Count)
        $undoConfig = (Resolve-Path -LiteralPath $sshConfigFile).Path
        Assert-True -Name '... and its To undo line carries the same -SshConfigFile, so the undo reaches the same test instance' -Condition (
            $run.Text.Contains("To undo     : .\tools\deploy-ha-kit.ps1 -Action Uninstall -SshHost fictional-host -Target Test -ExpectedHaVersion 2030.1.0 -SshConfigFile '$undoConfig' (refused while a config entry exists)")) -Detail (@($run.Lines | Where-Object { $_.StartsWith('To undo') }) -join ' | ')
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV2)
        Assert-KitBlocked -Name '... and -Target Production on that marked host is refused (DEPLOY_TARGET)' -Run $run -Pattern '-Target Production, but .*loopback|-Target Production, but the test-instance marker'

        $all = @($global:EccoKitAll)
        Assert-True -Name 'across every end-to-end run: no rm, no recursive mkdir, no restart was ever sent' -Condition (
            $all.Count -gt 50 -and @($all | Where-Object { $_ -match '(^|[;&|] *)rm |\brm -|mkdir -p|restart' }).Count -eq 0) -Detail (@($all | Where-Object { $_ -match '\brm\b|mkdir -p|restart' }) -join ' | ')
        Assert-True -Name '... every Home Assistant CLI call was its own ssh command (exactly ha core check or ha core info --raw-json, never compounded)' -Condition (
            @($all | Where-Object { $_ -match '\bha core\b' -and $_ -cne 'ha core check' -and $_ -cne 'ha core info --raw-json' }).Count -eq 0)
        Assert-True -Name '... no remote command held a double quote or a dollar sign (single-quoted words only)' -Condition (
            @($all | Where-Object { $_.Contains('"') -or $_.Contains('$') }).Count -eq 0) -Detail (@($all | Where-Object { $_.Contains('"') -or $_.Contains('$') }) | Select-Object -First 1)
        Assert-True -Name '... only the read-only snapshot probe named the site file or the state folder' -Condition (
            @($all | Where-Object { $_ -match '/config/ecco/intelligence' -and -not $_.StartsWith("if [ -L '/config/ecco/intelligence/site.local.json' ]; then echo 'site link'") }).Count -eq 0)
        Assert-True -Name '... and nothing was ever written under custom_components but the ecco_intelligence folder' -Condition (
            @(Get-ChildItem -LiteralPath (Get-HostPath '/config/custom_components') -Force | ForEach-Object { $_.Name } | Where-Object { $_ -ne 'ecco_intelligence' -and $_ -ne 'other_integration' }).Count -eq 0)

        # -------------------------------------------------------------
        # 21. place-ha-site-file.ps1 (design T5).
        # -------------------------------------------------------------
        Write-Host ''
        Write-Host '[21] The site-file placement'
        $ownerDir = Join-Path $kitBase 'owner-files'
        New-Item -ItemType Directory -Path $ownerDir | Out-Null
        $newSiteText = "{`"_note`": `"fictional test data`", `"sentinel`": `"ECCO-FICTIONAL-SENTINEL-NEW-91b2`"}`n"
        $newSite = Join-Path $ownerDir 'site.local.json'
        [System.IO.File]::WriteAllText($newSite, $newSiteText)
        $newSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $newSite).Hash.ToLowerInvariant()
        $oldSha = (Get-EccoBytesSha256 -Bytes ([System.Text.Encoding]::ASCII.GetBytes($siteOld)))
        $hostSite = Get-HostPath '/config/ecco/intelligence/site.local.json'
        # The hooks run inside the global ssh stub, where only global variables are visible.
        $global:EccoKitHostSite = $hostSite
        function Get-PlaceParams {
            param([string]$File = $newSite, [string]$Sha = $newSha, [hashtable]$Extra = @{})
            $p = @{ SiteFile = $File; ExpectedSha256 = $Sha; SshHost = 'fictional-host'; Target = 'Production'; Python = $Python; Stamp = (Get-NextKitStamp) }
            foreach ($k in $Extra.Keys) { $p[$k] = $Extra[$k] }
            return $p
        }
        function Test-NoSentinel {
            param([object]$Run)
            return (-not ($Run.Text + $Run.Message).Contains('SENTINEL'))
        }

        Reset-KitHost
        Remove-Item -LiteralPath (Get-HostPath '/config/ecco/intelligence') -Recurse -Force
        $p = Get-PlaceParams
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $p
        Assert-True -Name 'first placement: the missing /config/ecco/intelligence is created (one level) and the file placed and read back by its sha256' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO SITE FILE PLACED' -and (Test-Path -LiteralPath $hostSite) -and
            [System.IO.File]::ReadAllText($hostSite) -ceq $newSiteText -and $run.Text -match "Read back   : sha256 $newSha") -Detail $run.Message
        # Review L3W-6 (amendment A49): the run created its backup folder for a rollback; the PLACED block names it as kept
        # and empty instead of a bare "Backup: none", and the folder is there and empty.
        $firstBackupWin = Get-HostPath "/config/ecco-backups/$($p.Stamp)"
        Assert-True -Name 'L3W-6: first placement: the PLACED block names the backup folder this run created as kept and empty (never a bare "none (first placement)"), and it is there, empty' -Condition (
            @($run.Lines | Where-Object { $_ -ceq "Backup      : none (first placement); /config/ecco-backups/$($p.Stamp) was created for a rollback and is kept, empty" }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -ceq 'Backup      : none (first placement)' }).Count -eq 0 -and
            (Test-Path -LiteralPath $firstBackupWin -PathType Container) -and @(Get-ChildItem -LiteralPath $firstBackupWin -Force).Count -eq 0) -Detail (@($run.Lines | Where-Object { $_.StartsWith('Backup') }) -join ' | ')
        Assert-True -Name '... its output never shows the file''s content (the fictional sentinel), only sizes and hashes' -Condition (Test-NoSentinel $run)
        Assert-True -Name '... no command named the state folder, and no temporary upload is left' -Condition (
            @($run.Sent | Where-Object { $_ -match '/config/ecco/intelligence/state' }).Count -eq 0 -and
            @(Get-ChildItem -LiteralPath (Get-HostPath '/config/ecco/intelligence') -Force | Where-Object { $_.Name -match 'ecco-upload' }).Count -eq 0)

        Reset-KitHost
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams)
        Assert-KitBlocked -Name 'an existing site file and no -ReplaceExistingSha256: BLOCKED before any write' -Run $run -Pattern 'already on the host'
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = ('e' * 64) })
        Assert-KitBlocked -Name 'an existing site file and the wrong -ReplaceExistingSha256: BLOCKED before any write' -Run $run -Pattern 'does not match the site file on the host'
        Assert-True -Name '... and the host file is unchanged' -Condition ([System.IO.File]::ReadAllText($hostSite) -ceq $siteOld)
        $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $p
        $siteBackup = Get-HostPath "/config/ecco-backups/$($p.Stamp)/config__ecco__intelligence__site.local.json"
        Assert-True -Name 'replacement with the right -ReplaceExistingSha256: PASSED, the previous file in a verified backup, the new one read back' -Condition (
            $run.Message -eq '' -and [System.IO.File]::ReadAllText($hostSite) -ceq $newSiteText -and (Test-Path -LiteralPath $siteBackup) -and
            [System.IO.File]::ReadAllText($siteBackup) -ceq $siteOld -and (Test-NoSentinel $run)) -Detail $run.Message
        Assert-True -Name 'L3W-6 control: ... and its PLACED block names that backup file with the previous sha256 (no first-placement wording)' -Condition (
            @($run.Lines | Where-Object { $_ -ceq "Backup      : /config/ecco-backups/$($p.Stamp)/config__ecco__intelligence__site.local.json (the previous file, sha256 $oldSha)" }).Count -eq 1 -and
            $run.Text -notmatch 'first placement') -Detail (@($run.Lines | Where-Object { $_.StartsWith('Backup') }) -join ' | ')

        Reset-KitHost
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SITE_PLACED')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHostSite, ' ') } } }; return $null }
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha })
        $global:EccoKitHook = $null
        Assert-True -Name 'a read-back that does not match: the previous file is restored from the backup ("was rolled back")' -Condition (
            $run.Message -match 'was rolled back' -and [System.IO.File]::ReadAllText($hostSite) -ceq $siteOld -and (Test-NoSentinel $run)) -Detail $run.Message
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $global:EccoKitHook = { param($c) if ($c.Contains('echo ECCO_SITE_PLACED')) { return @{ After = { [System.IO.File]::AppendAllText($global:EccoKitHostSite, ' ') } } }; return $null }
        $p = Get-PlaceParams
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $p
        $global:EccoKitHook = $null
        Assert-True -Name '... and a failed first placement is moved into the backup folder, never deleted' -Condition (
            $run.Message -match 'was rolled back' -and -not (Test-Path -LiteralPath $hostSite) -and
            (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)/site.local.json.failed-placement"))) -Detail $run.Message
        Reset-KitHost
        $global:EccoKitScpCorrupt = 'site.local.json'
        $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $p
        $global:EccoKitScpCorrupt = ''
        Assert-True -Name 'an upload that does not arrive intact: STOPPED, the host file unchanged, the rejected upload moved aside (not deleted)' -Condition (
            $run.Message -match 'did not arrive intact' -and [System.IO.File]::ReadAllText($hostSite) -ceq $siteOld -and
            @($run.Sent | Where-Object { $_ -match '\brm\b' }).Count -eq 0) -Detail $run.Message
        # Review DR3-1 (amendment A40): the move answers its marker, and the moved file is named only where the host holds it.
        $corruptBytes = [System.Text.Encoding]::ASCII.GetBytes($newSiteText)
        $corruptBytes[0] = $corruptBytes[0] -bxor 1
        $rejectedWin = Get-HostPath "/config/ecco-backups/$($p.Stamp)/site.local.json.upload-rejected"
        Assert-True -Name 'DR3-1: ... the message names the rejected upload as moved aside to the backup folder, where the host holds it (the corrupted bytes), and the temporary upload is gone' -Condition (
            $run.Message.Contains("The site file on the host was not changed.`nThe rejected upload was moved aside (not deleted): it is now /config/ecco-backups/$($p.Stamp)/site.local.json.upload-rejected.") -and
            (Test-Path -LiteralPath $rejectedWin -PathType Leaf) -and
            [System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes($rejectedWin)) -ceq [System.Convert]::ToBase64String($corruptBytes) -and
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco/intelligence/site.local.json.ecco-upload-$($p.Stamp).tmp"))) -Detail $run.Message

        $big = Join-Path $ownerDir 'big.json'
        [System.IO.File]::WriteAllText($big, '{"x": "' + ('a' * 270000) + '"}')
        $notObject = Join-Path $ownerDir 'array.json'
        [System.IO.File]::WriteAllText($notObject, "[1, 2]`n")
        $notJson = Join-Path $ownerDir 'broken.json'
        [System.IO.File]::WriteAllText($notJson, "{`"x`": `n")
        $bom = Join-Path $ownerDir 'bom.json'
        [System.IO.File]::WriteAllBytes($bom, [byte[]](0xEF, 0xBB, 0xBF) + [System.Text.Encoding]::ASCII.GetBytes("{}`n"))
        $otherRepo = Join-Path $kitBase 'other-repo'
        New-Item -ItemType Directory -Path $otherRepo | Out-Null
        Invoke-KitGit -Repo $otherRepo -GitArgs @('init', '-q') | Out-Null
        $inOther = Join-Path $otherRepo 'site.local.json'
        [System.IO.File]::WriteAllText($inOther, "{}`n")
        # Review P1 (amendment A49): the runtime's json.loads refuses NaN, Infinity and -Infinity (and every other form that is
        # not strict JSON), which Windows PowerShell's ConvertFrom-Json reads; the placement refuses them before any ssh call.
        $p1Cases = @(
            @{ Name = 'NaN as a value (the M3 "nan" variant)'; Text = "{`"site`": {`"pv_array_kwp`": NaN}}`n"; Pattern = 'holds NaN, Infinity or -Infinity, which is not JSON: the runtime refuses it' },
            @{ Name = 'Infinity as a value'; Text = "{`"site`": {`"pv_array_kwp`": Infinity}}`n"; Pattern = 'holds NaN, Infinity or -Infinity, which is not JSON: the runtime refuses it' },
            @{ Name = '-Infinity in an array'; Text = "{`"x`": [1, -Infinity]}`n"; Pattern = 'holds NaN, Infinity or -Infinity, which is not JSON: the runtime refuses it' },
            @{ Name = 'an unquoted key (read by ConvertFrom-Json, refused by the runtime)'; Text = "{site: {}}`n"; Pattern = 'not strict JSON .*: the runtime refuses it' },
            @{ Name = 'a single-quoted string (read by ConvertFrom-Json, refused by the runtime)'; Text = "{'site': {}}`n"; Pattern = 'not strict JSON .*: the runtime refuses it' },
            @{ Name = 'a number with a leading plus (read by ConvertFrom-Json, refused by the runtime)'; Text = "{`"x`": +1}`n"; Pattern = 'not strict JSON .*: the runtime refuses it' },
            @{ Name = 'a raw tab inside a string (read by ConvertFrom-Json, refused by the runtime)'; Text = "{`"x`": `"a`tb`"}`n"; Pattern = 'not strict JSON .*: the runtime refuses it' },
            # Review DRD-2 (amendment A52): what the runtime refuses, whatever ConvertFrom-Json reads.
            @{ Name = 'a number beyond the double range that ConvertFrom-Json rounds to the largest double'; Text = "{`"site`": {`"pv_array_kwp`": 1.797693134862315808e308}}`n"; Pattern = 'beyond the double range .*: the runtime reads it as non-finite and refuses it' },
            @{ Name = 'an integer too large for a double'; Text = ("{`"site`": {`"pv_array_kwp`": 1797693134862315808" + ('0' * 290) + "}}`n"); Pattern = 'beyond the double range .*: the runtime reads it as non-finite and refuses it' },
            @{ Name = 'a trailing comma'; Text = "{`"site`": {`"pv_array_kwp`": 4.5,}}`n"; Pattern = 'not valid JSON \(.*\): the runtime refuses it' },
            @{ Name = 'nesting 101 deep'; Text = ("{`"x`": " + ('[' * 100) + (']' * 100) + "}`n"); Pattern = 'nests arrays and objects more than 100 deep' })
        $n = 0
        foreach ($c in $p1Cases) {
            $n++
            $f = Join-Path $ownerDir "p1-$n.json"
            [System.IO.File]::WriteAllText($f, $c.Text)
            $c.File = $f
        }
        foreach ($case in @(
                @{ Name = 'a file over 256 KiB'; File = $big; Pattern = 'must be 1 to 262144 bytes' },
                @{ Name = 'a JSON array, not an object'; File = $notObject; Pattern = 'not a JSON object' },
                @{ Name = 'invalid JSON'; File = $notJson; Pattern = 'not valid JSON' },
                @{ Name = 'a byte-order mark'; File = $bom; Pattern = 'byte-order mark' },
                @{ Name = 'a file inside another git working tree'; File = $inOther; Pattern = 'inside a git working tree' }) + $p1Cases) {
            $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $case.File).Hash.ToLowerInvariant()
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -File $case.File -Sha $sha)
            Assert-True -Name "placement refused before any ssh call: $($case.Name)" -Condition ($run.Message -match $case.Pattern -and $run.Sent.Count -eq 0) -Detail $run.Message
        }
        # P1 control: NaN, Infinity and -Infinity inside strings (as keys and values), escapes and exponent numbers are
        # strict JSON, so such a file is placed (a first placement), byte for byte. So are \u escapes (review DRD-4; the
        # backslash and the accented letter are built from character codes), the largest double, a number that underflows
        # to zero and a nesting 100 deep (review DRD-2).
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $bsChar = [string][char]92
        $p1OkText = "{`"_note`": `"fictional test data: NaN, Infinity and -Infinity in strings only`", `"NaN`": `"Infinity`", `"x`": [`"-Infinity`", -0.5e-3, 1E+5, 0, true, false, null], `"esc`": `"\`" \\ \/ \b \f \n \r \t $([char]0xE9)`", " +
            "`"u`": `"$($bsChar)u00e9 $($bsChar)u00C9 $($bsChar)uD83D$($bsChar)uDE00`", `"edge`": [1.7976931348623157e308, -1.7976931348623157e308, 1e-999], `"deep`": $('[' * 99)$(']' * 99)}`n"
        $p1Ok = Join-Path $ownerDir 'p1-ok.json'
        [System.IO.File]::WriteAllText($p1Ok, $p1OkText)
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -File $p1Ok -Sha ((Get-FileHash -Algorithm SHA256 -LiteralPath $p1Ok).Hash.ToLowerInvariant()))
        Assert-True -Name 'P1 control: a site file with NaN, Infinity and -Infinity only inside strings (keys and values), every escape, \u escapes, exponent numbers, the largest double, 1e-999 and a nesting 100 deep is placed and read back' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO SITE FILE PLACED' -and (Test-Path -LiteralPath $hostSite) -and [System.IO.File]::ReadAllText($hostSite) -ceq $p1OkText) -Detail $run.Message
        $inRepo = Join-Path $kitRepo 'site.local.json'
        [System.IO.File]::WriteAllText($inRepo, "{}`n")
        try {
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -File $inRepo -Sha ((Get-FileHash -Algorithm SHA256 -LiteralPath $inRepo).Hash.ToLowerInvariant()))
            Assert-True -Name 'placement refused before any ssh call: a file inside this repository (even when git-ignored)' -Condition ($run.Message -match 'inside this repository' -and $run.Sent.Count -eq 0) -Detail $run.Message
        } finally {
            Remove-Item -LiteralPath $inRepo -Force -ErrorAction SilentlyContinue
        }
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Sha ('d' * 64))
        Assert-True -Name 'placement refused before any ssh call: a sha256 other than -ExpectedSha256' -Condition ($run.Message -match 'not the expected' -and $run.Sent.Count -eq 0) -Detail $run.Message

        Reset-KitHost
        Remove-Item -LiteralPath (Get-HostPath '/config/ecco/intelligence') -Recurse -Force
        $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
        if (New-KitJunction -Link (Get-HostPath '/config/ecco/intelligence') -Target $elsewhere) {
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams)
            Assert-KitBlocked -Name 'a symlinked /config/ecco/intelligence: BLOCKED before any write, nothing placed behind it' -Run $run -Pattern '/config/ecco/intelligence is link on the host'
            Assert-True -Name '... nothing was created behind the symlink' -Condition (@(Get-ChildItem -LiteralPath $elsewhere -Force).Count -eq 0)
        } else {
            Write-Host '  SKIP  a symlinked /config/ecco/intelligence (mklink /J could not create a junction here)'
        }
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        New-Item -ItemType Directory -Path $hostSite | Out-Null
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams)
        Assert-KitBlocked -Name 'a folder where the site file belongs: BLOCKED before any write' -Run $run -Pattern 'site\.local\.json is dir on the host'
        Reset-KitHost
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha; Plan = $true })
        Assert-True -Name 'placement -Plan: read-only commands only, the plan printed, the host file unchanged' -Condition (
            $run.Message -eq '' -and $run.Writes.Count -eq 0 -and $run.Text -match 'ECCO SITE FILE PLAN' -and [System.IO.File]::ReadAllText($hostSite) -ceq $siteOld -and (Test-NoSentinel $run)) -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams -Extra @{ Plan = $true }
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $p
        Assert-True -Name 'L3W-6: placement -Plan for a first placement says the backup folder is created for a rollback and kept, empty when the placement passes (read-only, nothing created)' -Condition (
            $run.Message -eq '' -and $run.Writes.Count -eq 0 -and
            @($run.Lines | Where-Object { $_ -ceq "Backup      : none (first placement); /config/ecco-backups/$($p.Stamp) is created for a rollback and kept, empty when the placement passes" }).Count -eq 1 -and
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)"))) -Detail (@($run.Lines | Where-Object { $_.StartsWith('Backup') }) -join ' | ')

        # Review DR-1: the -Target guard (amendment A10) of the placement, both directions; deploy-ha.ps1 -Action Retire
        # follows in section 22. The marked loopback test instance is the marker file, the alias resolving to 127.0.0.1 and
        # the machine ecco-l3-test; the default fictional host is production-like (none of the three). A BLOCK sends only
        # the ssh probe, the /config probe and the guard's reads, and changes nothing.
        # A host file's text, or $null when it is not there, so a condition reports FAIL instead of throwing.
        function Get-HostText {
            param([string]$Path)
            if (Test-Path -LiteralPath $Path -PathType Leaf) { return [System.IO.File]::ReadAllText($Path) }
            return $null
        }
        function Set-KitHostTestInstance {
            param([switch]$Off)
            if ($Off) {
                $global:EccoKitResolved = 'fictional.example.invalid'
                $global:EccoKitMachine = 'example-machine'
                return
            }
            [System.IO.File]::WriteAllText((Get-HostPath '/config/.ecco_l3_test_instance'), "$goodMarker`n")
            $global:EccoKitResolved = '127.0.0.1'
            $global:EccoKitMachine = 'ecco-l3-test'
        }
        $guardRootProbe = Get-EccoConfigRootProbeCommand
        function Test-GuardReadsOnly {
            param([object]$Run)
            $other = @($Run.Sent | Where-Object {
                    -not ($_ -ceq 'true' -or $_ -ceq $guardRootProbe -or $_ -ceq 'ssh -G fictional-host' -or $_ -ceq 'ha core info --raw-json' -or
                        $_ -ceq "head -c 200 '/config/.ecco_l3_test_instance'" -or $_.StartsWith("if [ -L '/config/.ecco_l3_test_instance' ]; then printf unreadable;")) })
            return (@($Run.Sent).Count -ge 3 -and $other.Count -eq 0 -and @($Run.Sent | Where-Object { $_ -ceq 'ssh -G fictional-host' }).Count -eq 1)
        }
        # True when a run printed -Line exactly twice: once right after the guard, and once inside the block that starts with -Header.
        function Test-LineInBlock {
            param([object]$Run, [string]$Header, [string]$Line)
            $lines = [string[]]@($Run.Lines)
            $at = [Array]::IndexOf($lines, $Header)
            $all = @($lines | Where-Object { $_ -ceq $Line }).Count
            $inBlock = if ($at -ge 0) { @($lines | Select-Object -Skip $at | Where-Object { $_ -ceq $Line }).Count } else { 0 }
            return ($all -eq 2 -and $inBlock -eq 1)
        }
        $prodTargetLine = 'Target      : Production - not loopback, no test-instance marker, machine example-machine'
        $testTargetLine = 'Target      : Test - loopback host, marker 0e5c1a2b..., machine ecco-l3-test'

        Reset-KitHost
        Set-KitHostTestInstance
        try {
            $before = Get-HostState
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha })
        } finally {
            Set-KitHostTestInstance -Off
        }
        Assert-KitBlocked -Name 'DR-1: placement -Target Production on the marked loopback test instance: DEPLOY_TARGET BLOCKED before any write' -Run $run -Pattern '^DEPLOY_TARGET: BLOCKED - -Target Production, but ''fictional-host'' resolves to a loopback address'
        Assert-True -Name '... only the ssh probe, the /config probe and the guard''s reads were sent; the host and its site file are unchanged' -Condition (
            (Test-GuardReadsOnly $run) -and (Test-SameMap (Get-HostState) $before) -and (Get-HostText $hostSite) -ceq $siteOld) -Detail ($run.Sent -join ' | ')
        Reset-KitHost
        $before = Get-HostState
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ Target = 'Test'; ReplaceExistingSha256 = $oldSha })
        Assert-KitBlocked -Name 'DR-1: placement -Target Test on an unmarked host that is not loopback: DEPLOY_TARGET BLOCKED before any write' -Run $run -Pattern '^DEPLOY_TARGET: BLOCKED - -Target Test, but ''fictional-host'' does not resolve to a loopback address'
        Assert-True -Name '... only the ssh probe, the /config probe and the guard''s reads were sent; the host and its site file are unchanged' -Condition (
            (Test-GuardReadsOnly $run) -and (Test-SameMap (Get-HostState) $before) -and (Get-HostText $hostSite) -ceq $siteOld) -Detail ($run.Sent -join ' | ')

        # The guard's Target line inside the placement's Plan and PLACED blocks, both directions (the passing controls).
        Reset-KitHost
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha; Plan = $true })
        Assert-True -Name 'DR-1: placement -Plan, -Target Production: the guard''s Target line is printed inside the Plan block' -Condition (
            $run.Message -eq '' -and (Test-LineInBlock -Run $run -Header 'ECCO SITE FILE PLAN (read-only: nothing was written)' -Line $prodTargetLine)) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))
        $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha })
        Assert-True -Name '... and placing it, inside the PLACED block' -Condition (
            $run.Message -eq '' -and (Test-LineInBlock -Run $run -Header 'ECCO SITE FILE PLACED' -Line $prodTargetLine) -and (Get-HostText $hostSite) -ceq $newSiteText) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))
        Reset-KitHost
        Set-KitHostTestInstance
        try {
            $runPlan = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ Target = 'Test'; ReplaceExistingSha256 = $oldSha; Plan = $true })
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ Target = 'Test'; ReplaceExistingSha256 = $oldSha })
        } finally {
            Set-KitHostTestInstance -Off
        }
        Assert-True -Name 'DR-1 control: placement -Target Test on the marked loopback test instance passes the guard: its Target line inside the Plan and PLACED blocks, the file placed' -Condition (
            $runPlan.Message -eq '' -and $runPlan.Writes.Count -eq 0 -and (Test-LineInBlock -Run $runPlan -Header 'ECCO SITE FILE PLAN (read-only: nothing was written)' -Line $testTargetLine) -and
            $run.Message -eq '' -and (Test-LineInBlock -Run $run -Header 'ECCO SITE FILE PLACED' -Line $testTargetLine) -and (Get-HostText $hostSite) -ceq $newSiteText -and
            (Test-NoSentinel $run)) -Detail ($runPlan.Message + ' || ' + $run.Message + ' || ' + (@($run.Lines | Where-Object { $_.StartsWith('Target') }) -join ' | '))

        # Review DR-2: the connection lost right after the rename. A hook lets the move run and then answers ssh exit 255 -
        # for the read-back probe only (probe), or for every command after the move (all). The placement goes to its
        # rollback: with the connection back it restores the previous file, or moves a first placement aside ("was rolled
        # back"); with the connection still lost it says the rollback could NOT be confirmed and that the host may already
        # hold the new file.
        $dr2Hook = {
            param($c)
            if ($c.Contains($global:EccoKitMoveMarker)) {
                $global:EccoKitAfterMove = $true
                return $null
            }
            if ($global:EccoKitAfterMove) {
                $lose = ($global:EccoKitLossMode -eq 'all') -or ($global:EccoKitLossMode -eq 'probe' -and -not $global:EccoKitProbeLost -and $c.StartsWith($global:EccoKitProbeStart))
                if ($lose) {
                    if ($c.StartsWith($global:EccoKitProbeStart)) { $global:EccoKitProbeLost = $true }
                    return @{ Skip = $true; ExitCode = 255; Output = @('ssh: connection lost (fictional)') }
                }
            }
            return $null
        }
        function Invoke-Dr2Run {
            param([string]$Script, [hashtable]$Params, [string]$MoveMarker, [string]$ProbeStart, [ValidateSet('probe', 'all')][string]$Mode)
            $global:EccoKitMoveMarker = $MoveMarker
            $global:EccoKitProbeStart = $ProbeStart
            $global:EccoKitLossMode = $Mode
            $global:EccoKitAfterMove = $false
            $global:EccoKitProbeLost = $false
            $global:EccoKitHook = $dr2Hook
            try { return (Invoke-KitRun -Script $Script -Params $Params) } finally { $global:EccoKitHook = $null }
        }
        $sitePlaced = 'echo ECCO_SITE_PLACED'
        $siteProbe = "if [ -L '/config/ecco/intelligence/site.local.json' ]; then echo 'link"
        $dr2Lost = 'the read-back after the rename failed: The host paths could not be inspected \(ssh exit code 255\)\. This may be an ssh/transport failure: the host may already hold the new site file'

        Reset-KitHost
        $run = Invoke-Dr2Run -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }) -MoveMarker $sitePlaced -ProbeStart $siteProbe -Mode probe
        Assert-True -Name 'DR-2: placement, connection lost right after the rename (the read-back probe gets ssh exit 255): the previous file restored ("was rolled back"), naming the lost read-back' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'Site file placement failed and was rolled back' -and $run.Message -match $dr2Lost -and
            (Get-HostText $hostSite) -ceq $siteOld -and $run.Text -notmatch 'ECCO SITE FILE PLACED' -and (Test-NoSentinel $run)) -Detail $run.Message
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr2Run -Script 'place-ha-site-file.ps1' -Params $p -MoveMarker $sitePlaced -ProbeStart $siteProbe -Mode probe
        Assert-True -Name '... a first placement whose read-back is lost is moved into the backup folder ("was rolled back"), never deleted' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'was rolled back' -and $run.Message -match $dr2Lost -and -not (Test-Path -LiteralPath $hostSite) -and
            (Get-HostText (Get-HostPath "/config/ecco-backups/$($p.Stamp)/site.local.json.failed-placement")) -ceq $newSiteText) -Detail $run.Message
        Reset-KitHost
        $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
        $run = Invoke-Dr2Run -Script 'place-ha-site-file.ps1' -Params $p -MoveMarker $sitePlaced -ProbeStart $siteProbe -Mode all
        Assert-True -Name '... and with the connection still lost: the rollback could NOT be confirmed (never "was rolled back"), the host may hold the new file, the backup folder named' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'rollback could NOT be confirmed successful' -and $run.Message -notmatch 'was rolled back' -and $run.Message -match $dr2Lost -and
            $run.Message -match [regex]::Escape("Backup folder: /config/ecco-backups/$($p.Stamp)") -and (Get-HostText $hostSite) -ceq $newSiteText -and
            $run.Text -notmatch 'ECCO SITE FILE PLACED' -and (Test-NoSentinel $run)) -Detail $run.Message
        # The connection lost at the read-back's hash command instead (the state probe answered): the same rollback, and the
        # reason says the file could not be hashed (never "does not match").
        Reset-KitHost
        $run = Invoke-Dr2Run -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }) -MoveMarker $sitePlaced -ProbeStart "sha256sum '/config/ecco/intelligence/site.local.json' |" -Mode probe
        Assert-True -Name 'DR-2: placement, connection lost at the read-back''s hash: the previous file restored ("was rolled back"), the reason says it could not be hashed' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'was rolled back: the placed site file could not be hashed on the host: a possible ssh/transport failure' -and
            $run.Message -notmatch 'does not match' -and (Get-HostText $hostSite) -ceq $siteOld -and (Test-NoSentinel $run)) -Detail $run.Message

        # Review DR-4 (amendment A37): the rename command itself lost (ssh exit 255). NotRun - the mv never runs; Ran - it
        # runs and its answer is lost; NotRunStaysLost - the mv never runs and every later command is lost too (sshd killed).
        # The rollback names the upload's temporary file as left in place (nothing deleted) while the host still holds it,
        # and never names it once it is gone; a first placement whose rename never ran says nothing was placed and names no
        # moved-aside file; a moved-aside file is named only once it is seen on the host (-Elsewhere: a move aside that
        # answers its marker but leaves no file at that path).
        $dr4Hook = {
            param($c)
            $lost = @{ Skip = $true; ExitCode = 255; Output = @('ssh: connection lost (fictional)') }
            if ($c.Contains('echo ECCO_SITE_PLACED')) {
                $global:EccoKitRenameLost = $true
                if ($global:EccoKitDr4Mode -eq 'Ran') { return @{ ExitCode = 255; Output = @('ssh: connection lost (fictional)') } }
                return $lost
            }
            if ($global:EccoKitRenameLost -and $global:EccoKitDr4Mode -eq 'NotRunStaysLost') { return $lost }
            if ($global:EccoKitDr4Elsewhere -and $c.Contains('echo ECCO_SITE_MOVED_ASIDE')) {
                return @{ Command = $c.Replace('site.local.json.failed-placement', 'example-elsewhere') }
            }
            return $null
        }
        function Invoke-Dr4Run {
            param([hashtable]$Params, [ValidateSet('NotRun', 'Ran', 'NotRunStaysLost')][string]$Mode, [switch]$Elsewhere)
            $global:EccoKitDr4Mode = $Mode
            $global:EccoKitDr4Elsewhere = [bool]$Elsewhere
            $global:EccoKitRenameLost = $false
            $global:EccoKitHook = $dr4Hook
            try { return (Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $Params) } finally { $global:EccoKitHook = $null; $global:EccoKitDr4Elsewhere = $false }
        }
        function Get-UploadPath {
            param([string]$Stamp)
            return "/config/ecco/intelligence/site.local.json.ecco-upload-$Stamp.tmp"
        }
        function Get-LeftInPlaceLine {
            param([string]$Stamp)
            return "Left in place (nothing deleted): the upload $(Get-UploadPath $Stamp), the new site file verified on upload, was never renamed into place."
        }
        # The host's site-file area (the integration folder's site files and the backups), for a FAIL's detail.
        function Get-PlacementFiles {
            $root = Get-HostPath '/config'
            return (@(Get-ChildItem -LiteralPath $root -Recurse -File -Force | Where-Object { $_.FullName -match 'intelligence\\site|ecco-backups' } |
                        ForEach-Object { $_.FullName.Substring($root.Length).Replace('\', '/') }) -join ', ')
        }
        function Test-NoRmSent {
            param([object]$Run)
            return (@($Run.Sent | Where-Object { $_ -match '\brm\b' }).Count -eq 0)
        }
        $dr4Lost = 'Site file placement failed and was rolled back: the rename into place failed, or its result could not be confirmed \(ssh exit code 255\)\.'
        $dr4NothingPlaced = 'Nothing placed: no site file is at /config/ecco/intelligence/site.local.json, as before the run, so nothing was moved aside.'

        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr4Run -Params $p -Mode NotRun
        Assert-True -Name 'DR-4: first placement, the rename command lost before it ran (ssh exit 255): "was rolled back", nothing placed, the upload .tmp named as left in place (nothing deleted), no moved-aside file named' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match $dr4Lost -and $run.Message.Contains($dr4NothingPlaced) -and $run.Message.Contains((Get-LeftInPlaceLine $p.Stamp)) -and
            -not $run.Message.Contains('failed-placement') -and -not $run.Message.Contains('Moved aside') -and $run.Text -notmatch 'ECCO SITE FILE PLACED' -and (Test-NoSentinel $run)) -Detail $run.Message
        Assert-True -Name '... the host holds that upload .tmp with the new file''s bytes, no site file and no moved-aside file; no rm was sent' -Condition (
            (Get-HostText (Get-HostPath (Get-UploadPath $p.Stamp))) -ceq $newSiteText -and -not (Test-Path -LiteralPath $hostSite) -and
            -not (Test-Path -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)/site.local.json.failed-placement")) -and (Test-NoRmSent $run)) -Detail (Get-PlacementFiles)

        Reset-KitHost
        $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
        $run = Invoke-Dr4Run -Params $p -Mode NotRun
        Assert-True -Name 'DR-4: replacement, the rename command lost before it ran: the previous file restored ("was rolled back"), the same upload .tmp named as left in place (nothing deleted)' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match $dr4Lost -and
            $run.Message.Contains("Restored: the previous site file (sha256 $($oldSha.Substring(0, 12))) from /config/ecco-backups/$($p.Stamp)/config__ecco__intelligence__site.local.json") -and
            $run.Message.Contains((Get-LeftInPlaceLine $p.Stamp)) -and -not $run.Message.Contains('failed-placement') -and (Test-NoSentinel $run)) -Detail $run.Message
        Assert-True -Name '... the host holds the previous site file, its backup and the upload .tmp with the new bytes; no rm was sent' -Condition (
            (Get-HostText $hostSite) -ceq $siteOld -and (Get-HostText (Get-HostPath "/config/ecco-backups/$($p.Stamp)/config__ecco__intelligence__site.local.json")) -ceq $siteOld -and
            (Get-HostText (Get-HostPath (Get-UploadPath $p.Stamp))) -ceq $newSiteText -and (Test-NoRmSent $run)) -Detail (Get-PlacementFiles)

        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr4Run -Params $p -Mode Ran
        $dr4Failed = "/config/ecco-backups/$($p.Stamp)/site.local.json.failed-placement"
        Assert-True -Name 'DR-4: first placement, the rename ran and its answer was lost: the placed file moved aside and named ("was rolled back"); the upload .tmp, gone, is never named' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match $dr4Lost -and $run.Message.Contains("Moved aside (not deleted): the placed file is now $dr4Failed") -and
            -not $run.Message.Contains('ecco-upload') -and -not $run.Message.Contains('Nothing placed') -and (Get-HostText (Get-HostPath $dr4Failed)) -ceq $newSiteText -and
            -not (Test-Path -LiteralPath $hostSite) -and -not (Test-Path -LiteralPath (Get-HostPath (Get-UploadPath $p.Stamp))) -and (Test-NoSentinel $run)) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        Reset-KitHost
        $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
        $run = Invoke-Dr4Run -Params $p -Mode Ran
        Assert-True -Name 'DR-4: replacement, the rename ran and its answer was lost: the previous file restored ("was rolled back"); the upload .tmp, gone, is never named' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match $dr4Lost -and $run.Message.Contains('Restored: the previous site file') -and -not $run.Message.Contains('ecco-upload') -and
            (Get-HostText $hostSite) -ceq $siteOld -and -not (Test-Path -LiteralPath (Get-HostPath (Get-UploadPath $p.Stamp))) -and (Test-NoSentinel $run)) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr4Run -Params $p -Mode Ran -Elsewhere
        $dr4Failed = "/config/ecco-backups/$($p.Stamp)/site.local.json.failed-placement"
        Assert-True -Name 'DR-4: a move aside that answers its marker but leaves no file at the moved-aside path: rollback NOT confirmed (never "was rolled back"), that path never named as holding the placed file' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match 'rollback could NOT be confirmed successful: the rename into place failed' -and $run.Message -notmatch 'was rolled back' -and
            $run.Message.Contains("Rollback verification: FAILED - the moved-aside file $dr4Failed is absent on the host, not a regular file") -and -not $run.Message.Contains('Moved aside (not deleted)') -and
            (Get-HostText (Get-HostPath "/config/ecco-backups/$($p.Stamp)/example-elsewhere")) -ceq $newSiteText) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr4Run -Params $p -Mode NotRunStaysLost
        Assert-True -Name 'DR-4: first placement, the rename command lost and the connection stays lost: NOT confirmed, the upload .tmp named with its state unknown (nothing deleted), no moved-aside file named' -Condition (
            $global:EccoKitRenameLost -and $run.Message -match 'rollback could NOT be confirmed successful: the rename into place failed' -and $run.Message -notmatch 'was rolled back' -and
            $run.Message.Contains("Upload: the state of $(Get-UploadPath $p.Stamp) could not be read; if the rename did not run, the new site file is still there (nothing was deleted).") -and
            -not $run.Message.Contains('Moved aside (not deleted)') -and $run.Message.Contains("Backup folder: /config/ecco-backups/$($p.Stamp)") -and
            (Get-HostText (Get-HostPath (Get-UploadPath $p.Stamp))) -ceq $newSiteText -and -not (Test-Path -LiteralPath $hostSite) -and (Test-NoRmSent $run) -and (Test-NoSentinel $run)) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        # Review DR3-1 (amendment A40): an upload that does not arrive intact is moved into the backup folder by one captured
        # command with markers (moved aside / something else present / absent), never deleted, and the STOPPED message names
        # only what the marker shows: a moved file only once the host holds it at its new path, and both places the upload may
        # be when there is no single marker. Each case is a first placement (no site file on the host).
        function Get-RejectedPath {
            param([string]$Stamp)
            return "/config/ecco-backups/$Stamp/site.local.json.upload-rejected"
        }
        function Get-Dr3Unconfirmed {
            param([string]$Stamp, [string]$Detail)
            return "The rejected upload's move aside could not be confirmed ($Detail). Nothing was deleted: an upload that reached the host is still $(Get-UploadPath $Stamp), or $(Get-RejectedPath $Stamp) if the move ran."
        }
        $dr3NoAnswer = 'no single answer from the host (a lost connection or a failed move); ssh exit code'
        # Review DR4R-1 (amendment A43): a move refused by its own guards answers ECCO_UPLOAD_KEPT, and the message says the
        # upload was left in place and not moved aside; it never names the rejected-upload path as a place the upload may be.
        function Get-Dr3Kept {
            param([string]$Stamp)
            return "Left in place (nothing deleted): $(Get-UploadPath $Stamp); this run's backup folder /config/ecco-backups/$Stamp is missing or not a real folder, or something is already at $(Get-RejectedPath $Stamp), so it was not moved aside."
        }
        function Test-Dr3KeptOnly {
            param([object]$Run, [string]$Stamp)
            return ($Run.Message.Contains((Get-Dr3Kept -Stamp $Stamp)) -and -not $Run.Message.Contains('could not be confirmed') -and -not $Run.Message.Contains('if the move ran') -and
                -not $Run.Message.Contains('no single answer'))
        }
        function Test-Dr3Stopped {
            # STOPPED for the upload, the site file unchanged (none on the host), never a claim that the upload was moved aside.
            param([object]$Run, [string]$Scp = 'scp exit code 0; sha256 on the host [0-9a-f]{12}')
            return ($Run.Message -match "^SITE_FILE: STOPPED - the upload did not arrive intact \($Scp\)\. The site file on the host was not changed\.`n" -and
                -not $Run.Message.Contains('moved aside (not deleted)') -and -not (Test-Path -LiteralPath $hostSite) -and (Test-NoRmSent $Run) -and (Test-NoSentinel $Run))
        }
        $dr3CorruptBytes = [System.Text.Encoding]::ASCII.GetBytes($newSiteText)
        $dr3CorruptBytes[0] = $dr3CorruptBytes[0] -bxor 1
        $dr3Corrupt = [System.Convert]::ToBase64String($dr3CorruptBytes)
        function Get-HostBase64 {
            param([string]$Remote)
            $w = Get-HostPath $Remote
            if (Test-Path -LiteralPath $w -PathType Leaf) { return [System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes($w)) }
            return $null
        }
        function Invoke-Dr3Run {
            # A first placement whose upload arrives corrupted (or, with -ScpFails, never arrives), with $Hook on every ssh command.
            param([hashtable]$Params, [scriptblock]$Hook = $null, [switch]$ScpFails)
            if ($ScpFails) { $global:EccoKitScpFail = 'site.local.json' } else { $global:EccoKitScpCorrupt = 'site.local.json' }
            $global:EccoKitHook = $Hook
            try { return (Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params $Params) } finally { $global:EccoKitHook = $null; $global:EccoKitScpCorrupt = ''; $global:EccoKitScpFail = '' }
        }

        # The move command lost before it ran (ssh exit 255): no single marker, so both places are named; the .tmp stays.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { return @{ Skip = $true; ExitCode = 255; Output = @('ssh: connection lost (fictional)') } }; return $null }
        Assert-True -Name 'DR3-1: corrupted upload, the move command lost before it ran (ssh exit 255): STOPPED, the move NOT confirmed, both places named, nothing deleted; never "moved"' -Condition (
            (Test-Dr3Stopped $run) -and $run.Message.Contains((Get-Dr3Unconfirmed -Stamp $p.Stamp -Detail "$dr3NoAnswer 255"))) -Detail $run.Message
        Assert-True -Name '... the host still holds the corrupted upload .tmp, and nothing at the rejected-upload path' -Condition (
            (Get-HostBase64 (Get-UploadPath $p.Stamp)) -ceq $dr3Corrupt -and -not (Test-Path -LiteralPath (Get-HostPath (Get-RejectedPath $p.Stamp)))) -Detail (Get-PlacementFiles)

        # scp fails and creates no file: the marker says absent, so no upload is named as moved.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr3Run -Params $p -ScpFails
        Assert-True -Name 'DR3-1: scp fails and creates no file: STOPPED, the message says no upload is on the host, so nothing was moved aside' -Condition (
            (Test-Dr3Stopped $run -Scp 'scp exit code 1; sha256 on the host unknown') -and
            $run.Message.Contains("No upload is on the host: $(Get-UploadPath $p.Stamp) is absent, so nothing was moved aside.") -and -not $run.Message.Contains('could not be confirmed')) -Detail $run.Message
        Assert-True -Name '... no .tmp and no rejected upload on the host; the backup folder is empty' -Condition (
            -not (Test-Path -LiteralPath (Get-HostPath (Get-UploadPath $p.Stamp))) -and -not (Test-Path -LiteralPath (Get-HostPath (Get-RejectedPath $p.Stamp))) -and
            @(Get-ChildItem -LiteralPath (Get-HostPath "/config/ecco-backups/$($p.Stamp)") -Force).Count -eq 0) -Detail (Get-PlacementFiles)

        # A folder, not a regular file, at the upload path when the move runs: something else present, left as it is.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $global:EccoKitDr3Upload = Get-UploadPath $p.Stamp
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { $u = $global:EccoKitDr3Upload; return @{ Command = "mv '$u' '$u.example-aside' && mkdir '$u' && $c" } }; return $null }
        Assert-True -Name 'DR3-1: something other than a regular file at the upload path: STOPPED, named as left in place (nothing deleted), not moved' -Condition (
            (Test-Dr3Stopped $run) -and $run.Message.Contains("Left in place (nothing deleted): $(Get-UploadPath $p.Stamp) is on the host but is not a regular file, so it was not moved aside.")) -Detail $run.Message
        Assert-True -Name '... the host still holds that folder at the upload path, and nothing at the rejected-upload path' -Condition (
            (Test-Path -LiteralPath (Get-HostPath (Get-UploadPath $p.Stamp)) -PathType Container) -and -not (Test-Path -LiteralPath (Get-HostPath (Get-RejectedPath $p.Stamp)))) -Detail (Get-PlacementFiles)

        # A move that answers its marker but leaves no file at the rejected-upload path: never named as moved there.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { return @{ Command = $c.Replace('site.local.json.upload-rejected', 'example-elsewhere') } }; return $null }
        Assert-True -Name 'DR3-1: a move that answers its marker but leaves no file at the rejected-upload path: NOT confirmed, that path never named as holding the upload' -Condition (
            (Test-Dr3Stopped $run) -and
            $run.Message.Contains((Get-Dr3Unconfirmed -Stamp $p.Stamp -Detail "the move answered, but $(Get-RejectedPath $p.Stamp) is absent on the host, not a regular file")) -and
            (Get-HostBase64 "/config/ecco-backups/$($p.Stamp)/example-elsewhere") -ceq $dr3Corrupt) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        # The move ran and printed its marker, but ssh reported exit 255: no confirmed answer, so both places are named.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { return @{ ExitCode = 255 } }; return $null }
        Assert-True -Name 'DR3-1: the move ran and printed its marker but ssh reported exit 255: NOT confirmed (both places named), never "moved"' -Condition (
            (Test-Dr3Stopped $run) -and $run.Message.Contains((Get-Dr3Unconfirmed -Stamp $p.Stamp -Detail "$dr3NoAnswer 255")) -and
            (Get-HostBase64 (Get-RejectedPath $p.Stamp)) -ceq $dr3Corrupt) -Detail ($run.Message + ' || ' + (Get-PlacementFiles))

        # Review DR4R-1: the guards pass but the mv itself fails (exit 1, no marker): a failed move keeps the two-place hedge,
        # never the guards' "left in place" line.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { return @{ Command = "mv() { echo 'mv: example failure' >&2; return 1; }; $c" } }; return $null }
        Assert-True -Name 'DR4R-1: the guards pass but the mv fails (exit 1, no marker): NOT confirmed, both places named (a failed move), never "left in place" by the guards' -Condition (
            (Test-Dr3Stopped $run) -and $run.Message.Contains((Get-Dr3Unconfirmed -Stamp $p.Stamp -Detail "$dr3NoAnswer 1")) -and -not $run.Message.Contains('so it was not moved aside')) -Detail $run.Message
        Assert-True -Name '... the corrupted upload .tmp is still in place, nothing at the rejected-upload path' -Condition (
            (Get-HostBase64 (Get-UploadPath $p.Stamp)) -ceq $dr3Corrupt -and -not (Test-Path -LiteralPath (Get-HostPath (Get-RejectedPath $p.Stamp)))) -Detail (Get-PlacementFiles)

        # Review DR4R-1: the run's backup folder gone before the move (the reviewer's Q3): the guards refuse the move and
        # answer their own marker, so the upload is named as left in place, not as possibly at the rejected-upload path.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $global:EccoKitDr3BackupWin = Get-HostPath "/config/ecco-backups/$($p.Stamp)"
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { Remove-Item -LiteralPath $global:EccoKitDr3BackupWin -Recurse -Force }; return $null }
        Assert-True -Name 'DR4R-1: the backup folder gone when the move runs: STOPPED, the guards refuse the move, the upload named as left in place and not moved aside (no two-place hedge, no "no single answer")' -Condition (
            (Test-Dr3Stopped $run) -and (Test-Dr3KeptOnly -Run $run -Stamp $p.Stamp)) -Detail $run.Message
        Assert-True -Name '... the corrupted upload .tmp is still in place, and no backup folder or rejected upload was made' -Condition (
            (Get-HostBase64 (Get-UploadPath $p.Stamp)) -ceq $dr3Corrupt -and -not (Test-Path -LiteralPath $global:EccoKitDr3BackupWin)) -Detail (Get-PlacementFiles)

        # Something already at the rejected-upload path (a folder): the move never runs into it, so nothing nests.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $global:EccoKitDr3Rejected = Get-RejectedPath $p.Stamp
        $run = Invoke-Dr3Run -Params $p -Hook { param($c) if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) { return @{ Command = "mkdir '$($global:EccoKitDr3Rejected)' && $c" } }; return $null }
        Assert-True -Name 'DR3-1 / DR4R-1: a folder already at the rejected-upload path: the guards refuse the move, the upload named as left in place and not moved aside' -Condition (
            (Test-Dr3Stopped $run) -and (Test-Dr3KeptOnly -Run $run -Stamp $p.Stamp)) -Detail $run.Message
        Assert-True -Name '... the corrupted upload .tmp is still in place and that folder is empty (nothing nested into it)' -Condition (
            (Get-HostBase64 (Get-UploadPath $p.Stamp)) -ceq $dr3Corrupt -and @(Get-ChildItem -LiteralPath (Get-HostPath (Get-RejectedPath $p.Stamp)) -Force).Count -eq 0) -Detail (Get-PlacementFiles)

        # The backup folder replaced by a symlink (a junction) to a folder elsewhere before the move: the move never follows it.
        Reset-KitHost
        Remove-Item -LiteralPath $hostSite -Force
        $p = Get-PlaceParams
        $global:EccoKitDr3BackupWin = Get-HostPath "/config/ecco-backups/$($p.Stamp)"
        $global:EccoKitDr3Elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $global:EccoKitDr3Elsewhere | Out-Null
        $run = Invoke-Dr3Run -Params $p -Hook {
            param($c)
            if ($c.Contains('echo ECCO_UPLOAD_MOVED_ASIDE')) {
                Rename-Item -LiteralPath $global:EccoKitDr3BackupWin -NewName ((Split-Path -Path $global:EccoKitDr3BackupWin -Leaf) + '-example-real')
                $previousEap = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try { & cmd /c mklink /J $global:EccoKitDr3BackupWin $global:EccoKitDr3Elsewhere 2>&1 | Out-Null } finally { $ErrorActionPreference = $previousEap }
            }
            return $null
        }
        $dr3Junction = ((Test-Path -LiteralPath $global:EccoKitDr3BackupWin) -and (((Get-Item -LiteralPath $global:EccoKitDr3BackupWin -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0))
        if ($dr3Junction) {
            $script:kitJunctions.Add($global:EccoKitDr3BackupWin)
            Assert-True -Name 'DR3-1 / DR4R-1: the backup folder a symlink when the move runs: the guards refuse it, the upload named as left in place and not moved aside' -Condition (
                (Test-Dr3Stopped $run) -and (Test-Dr3KeptOnly -Run $run -Stamp $p.Stamp)) -Detail $run.Message
            Assert-True -Name '... the corrupted upload .tmp is still in place, and nothing was written through the symlink' -Condition (
                (Get-HostBase64 (Get-UploadPath $p.Stamp)) -ceq $dr3Corrupt -and @(Get-ChildItem -LiteralPath $global:EccoKitDr3Elsewhere -Force).Count -eq 0) -Detail (Get-PlacementFiles)
        } else {
            Write-Host '  SKIP  DR3-1: the backup folder a symlink when the move runs (mklink /J could not create a junction here)'
        }
        Reset-KitHost

        # -------------------------------------------------------------
        # 22. Plan, deploy-ha.ps1 -Action Retire, and static checks (T6).
        # -------------------------------------------------------------
        Write-Host ''
        Write-Host '[22] Kit Plan, deploy-ha.ps1 -Action Retire, and static checks'
        Reset-KitHost -InstallKit $kitV1
        Add-HostPycache
        $before = Get-HostState
        $p = Get-KitParams -Action Plan -KitDir $kitV2
        $run = Invoke-KitRun -Params $p
        Assert-True -Name 'Plan over an installed v1: read-only commands only, the host unchanged, Action Upgrade' -Condition (
            $run.Message -eq '' -and $run.Writes.Count -eq 0 -and (Test-SameMap (Get-HostState) $before) -and $run.Text -match 'Action      : Upgrade') -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))
        Assert-True -Name 'Plan lists every destination with the first 8 hex digits of its sha256, the staging and backup paths, the swap command and the restart line' -Condition (
            @($kitV2Map.Keys | Where-Object { $run.Text -notmatch [regex]::Escape("/config/custom_components/ecco_intelligence/$_  $($kitV2Map[$_].Substring(0, 8))") }).Count -eq 0 -and
            $run.Text -match [regex]::Escape("Staging     : /config/ecco/staging/$($p.Stamp)/new/ecco_intelligence") -and
            $run.Text -match [regex]::Escape("Backup      : /config/ecco-backups/$($p.Stamp)/custom_components__ecco_intelligence") -and
            $run.Text -match "Swap        : \[ -d '/config/ecco/staging/$($p.Stamp)/previous'" -and $run.Text -match 'RESTART REQUIRED' -and
            $run.Text -match 'Never touched: /config/ecco/intelligence/site\.local\.json' -and $run.Text -match 'Equivalence : IDENTICAL') -Detail $run.Text
        # The owner's preconditions, in generic terms (amendment A41: no private-process wording in public text).
        Assert-True -Name 'Plan prints the owner''s preconditions line exactly: a protected backup, the pause ON, no other live change in progress' -Condition (
            @($run.Lines | Where-Object { $_ -like 'Preconditions*' }).Count -eq 1 -and
            @($run.Lines | Where-Object { $_ -like 'Preconditions*' })[0] -ceq 'Preconditions (owner): a protected Home Assistant backup taken; input_boolean.ecco_intel_paused ON; no other live change in progress') -Detail (@($run.Lines | Where-Object { $_ -like 'Preconditions*' }) -join ' | ')
        Reset-KitHost -InstallKit $kitV2
        $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV2)
        Assert-True -Name 'Plan with the kit already installed says NO CHANGE (reads only)' -Condition ($run.Message -eq '' -and $run.Writes.Count -eq 0 -and $run.Text -match 'Action      : NO CHANGE') -Detail $run.Message

        function Get-RetireParams {
            param([string]$Destination, [hashtable]$Extra = @{})
            $r = @{ Action = 'Retire'; Destination = $Destination; SshHost = 'fictional-host'; Target = 'Production'; SkipValidation = $true; Python = $Python }
            foreach ($k in $Extra.Keys) { $r[$k] = $Extra[$k] }
            return $r
        }
        $pkgText = "# fictional Intelligence package`nexample: true`n"
        Reset-KitHost
        [System.IO.File]::WriteAllText((Get-HostPath '/config/packages/ecco_intelligence.yaml'), $pkgText)
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
        $retiredCopy = @(Get-ChildItem -LiteralPath (Get-HostPath '/config/ecco-backups') -Recurse -File -Filter 'config__packages__ecco_intelligence.yaml' -ErrorAction SilentlyContinue)
        Assert-True -Name 'Retire: ECCO RETIRE PASSED, the file moved (not deleted) into /config/ecco-backups/<stamp>/ with its bytes, nothing left at the destination' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO RETIRE PASSED' -and -not (Test-Path -LiteralPath (Get-HostPath '/config/packages/ecco_intelligence.yaml')) -and
            $retiredCopy.Count -eq 1 -and [System.IO.File]::ReadAllText($retiredCopy[0].FullName) -ceq $pkgText -and
            @($run.Sent | Where-Object { $_ -match '\brm\b|mkdir -p|restart' }).Count -eq 0) -Detail ($run.Message + ' || ' + ($run.Lines | Select-Object -Last 4) -join ' | ')
        Assert-True -Name '... and its PASSED block prints the guard''s Target line (amendment A37), -Target Production' -Condition (
            $run.Message -eq '' -and (Test-LineInBlock -Run $run -Header 'ECCO RETIRE PASSED' -Line $prodTargetLine)) -Detail ($run.Message + ' || ' + ($run.Lines -join ' | '))
        Reset-KitHost
        [System.IO.File]::WriteAllText((Get-HostPath '/config/packages/ecco_intelligence.yaml'), $pkgText)
        $global:EccoKitCheckFailures = 1
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
        $global:EccoKitCheckFailures = 0
        Assert-True -Name 'Retire whose ha core check fails: the file is copied back ("was rolled back") and the backup copy stays' -Condition (
            $run.Message -match 'was rolled back' -and [System.IO.File]::ReadAllText((Get-HostPath '/config/packages/ecco_intelligence.yaml')) -ceq $pkgText -and
            @(Get-ChildItem -LiteralPath (Get-HostPath '/config/ecco-backups') -Recurse -File -Filter 'config__packages__ecco_intelligence.yaml').Count -eq 1) -Detail $run.Message

        # Review DR-1: the -Target guard of deploy-ha.ps1 -Action Retire, both directions (the placement's is in section 21).
        $pkgHost = Get-HostPath '/config/packages/ecco_intelligence.yaml'
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        Set-KitHostTestInstance
        try {
            $before = Get-HostState
            $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
        } finally {
            Set-KitHostTestInstance -Off
        }
        Assert-KitBlocked -Name 'DR-1: Retire -Target Production on the marked loopback test instance: DEPLOY_TARGET BLOCKED before any write' -Run $run -Pattern '^DEPLOY_TARGET: BLOCKED - -Target Production, but ''fictional-host'' resolves to a loopback address'
        Assert-True -Name '... only the ssh probe, the /config probe and the guard''s reads were sent; the file is still in place and the host unchanged' -Condition (
            (Test-GuardReadsOnly $run) -and (Test-SameMap (Get-HostState) $before) -and (Test-Path -LiteralPath $pkgHost)) -Detail ($run.Sent -join ' | ')
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        $before = Get-HostState
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml' -Extra @{ Target = 'Test' })
        Assert-KitBlocked -Name 'DR-1: Retire -Target Test on an unmarked host that is not loopback: DEPLOY_TARGET BLOCKED before any write' -Run $run -Pattern '^DEPLOY_TARGET: BLOCKED - -Target Test, but ''fictional-host'' does not resolve to a loopback address'
        Assert-True -Name '... only the ssh probe, the /config probe and the guard''s reads were sent; the file is still in place and the host unchanged' -Condition (
            (Test-GuardReadsOnly $run) -and (Test-SameMap (Get-HostState) $before) -and (Test-Path -LiteralPath $pkgHost)) -Detail ($run.Sent -join ' | ')
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        Set-KitHostTestInstance
        try {
            $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml' -Extra @{ Target = 'Test' })
        } finally {
            Set-KitHostTestInstance -Off
        }
        Assert-True -Name 'DR-1 control: Retire -Target Test on the marked loopback test instance passes the guard (its Target line printed after the guard and inside the PASSED block) and retires the file' -Condition (
            $run.Message -eq '' -and $run.Text -match 'ECCO RETIRE PASSED' -and (Test-LineInBlock -Run $run -Header 'ECCO RETIRE PASSED' -Line $testTargetLine) -and
            -not (Test-Path -LiteralPath $pkgHost)) -Detail ($run.Message + ' || ' + (@($run.Lines | Where-Object { $_.StartsWith('Target') }) -join ' | '))

        # Review DR-2: the connection lost right after Retire's move (the read-back probe gets ssh exit 255): the existing
        # rollback copies the file back ("was rolled back") and the message says the configuration check after the move was
        # not run; only the rollback's own ha core check was sent. With the connection still lost: NOT confirmed.
        $retireMoved = 'echo ECCO_RETIRE_MOVED'
        $retireProbe = "if [ -L '/config/packages/ecco_intelligence.yaml' ]; then echo 'link"
        $dr2RetireLost = 'The read-back after the move into the backup folder failed: The host paths could not be inspected \(ssh exit code 255\)\. This may be an ssh/transport failure: the file may already have moved\. The Home Assistant configuration check after the move was not run\.'
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        $run = Invoke-Dr2Run -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml') -MoveMarker $retireMoved -ProbeStart $retireProbe -Mode probe
        Assert-True -Name 'DR-2: Retire, connection lost right after the move: the file copied back ("was rolled back"), the configuration check after the move reported as not run, the backup copy kept' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'Deployment failed and was rolled back' -and $run.Message -match $dr2RetireLost -and
            $run.Text -notmatch 'ECCO RETIRE PASSED' -and (Test-Path -LiteralPath $pkgHost) -and (Get-HostText $pkgHost) -ceq $pkgText -and
            @(Get-ChildItem -LiteralPath (Get-HostPath '/config/ecco-backups') -Recurse -File -Filter 'config__packages__ecco_intelligence.yaml').Count -eq 1 -and
            @($run.Sent | Where-Object { $_ -ceq 'ha core check' }).Count -eq 1) -Detail ($run.Message + ' || ha core check sent: ' + @($run.Sent | Where-Object { $_ -ceq 'ha core check' }).Count)
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        $global:EccoKitCheckFailures = 1
        try {
            $run = Invoke-Dr2Run -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml') -MoveMarker $retireMoved -ProbeStart $retireProbe -Mode all
        } finally {
            $global:EccoKitCheckFailures = 0
        }
        Assert-True -Name '... and with the connection still lost: the rollback could NOT be confirmed (never "was rolled back"), the check after the move not run, the file in the backup folder' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'rollback could NOT be confirmed successful' -and $run.Message -notmatch 'was rolled back' -and $run.Message -match $dr2RetireLost -and
            $run.Text -notmatch 'ECCO RETIRE PASSED' -and -not (Test-Path -LiteralPath $pkgHost) -and
            @(Get-ChildItem -LiteralPath (Get-HostPath '/config/ecco-backups') -Recurse -File -Filter 'config__packages__ecco_intelligence.yaml').Count -eq 1) -Detail $run.Message
        # The connection lost at the backup copy's hash command instead: the same rollback, and the reason says the sha256
        # could not be read and that the configuration check after the move was not run.
        Reset-KitHost
        [System.IO.File]::WriteAllText($pkgHost, $pkgText)
        $run = Invoke-Dr2Run -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml') -MoveMarker $retireMoved -ProbeStart "sha256sum '/config/ecco-backups/" -Mode probe
        Assert-True -Name 'DR-2: Retire, connection lost at the backup copy''s hash: copied back ("was rolled back"), its sha256 reported as not read, the check after the move not run' -Condition (
            $global:EccoKitProbeLost -and $run.Message -match 'was rolled back' -and
            $run.Message -match 'its sha256 could not be read \(a possible ssh/transport failure: the file may already have moved\)\)\. The Home Assistant configuration check after the move was not run\.' -and
            (Get-HostText $pkgHost) -ceq $pkgText -and $run.Text -notmatch 'ECCO RETIRE PASSED') -Detail $run.Message
        foreach ($d in @('/config/packages/ecco_pro.yaml', '/config/ecco/dashboards/ecco_pro.yaml', '/config/www/ecco/ecco-energy-flow-card.js', '/config/packages/ecco_intelligence.yml', '/config/ecco/intelligence/site.local.json')) {
            $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination $d)
            Assert-True -Name "Retire refuses a file that is not a PR-6 Intelligence file, before any ssh call: $d" -Condition ($run.Message -ne '' -and $run.Sent.Count -eq 0) -Detail $run.Message
        }
        Reset-KitHost
        [System.IO.File]::WriteAllText((Get-HostPath '/config/www/ecco/ecco-intelligence-card.js'), "// fictional card`n")
        [System.IO.File]::WriteAllText((Get-HostPath '/config/.storage/lovelace_resources'), '{"version": 1, "key": "lovelace_resources", "data": {"items": [{"id": "1", "type": "module", "url": "/local/ecco/ecco-intelligence-card.js?v=0.1.0"}]}}')
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/www/ecco/ecco-intelligence-card.js')
        Assert-KitBlocked -Name 'Retire of a card a Lovelace resource still loads: BLOCKED before any write' -Run $run -Pattern 'a Lovelace resource still loads /local/ecco/ecco-intelligence-card\.js'
        [System.IO.File]::WriteAllText((Get-HostPath '/config/.storage/lovelace_resources'), '{"version": 1, "key": "lovelace_resources", "data": {"items": []}}')
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/www/ecco/ecco-intelligence-card.js')
        Assert-True -Name '... and once no resource loads it, the card file is retired' -Condition ($run.Message -eq '' -and -not (Test-Path -LiteralPath (Get-HostPath '/config/www/ecco/ecco-intelligence-card.js'))) -Detail $run.Message
        Reset-KitHost
        New-KitPolicy -Destination '/config/ecco/dashboards/ecco_intelligence.yaml'
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/ecco/dashboards/ecco_intelligence.yaml')
        Assert-KitBlocked -Name 'Retire of a file the site policy protects: BLOCKED (a protected file is never retired)' -Run $run -Pattern 'a protected file is never retired'
        Reset-KitHost
        New-KitPolicy -Destination '/config/ecco/dashboards/ecco_pro.yaml'
        [System.IO.File]::WriteAllText((Get-HostPath '/config/ecco/dashboards/ecco_intelligence.yaml'), "title: Example`n")
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/ecco/dashboards/ecco_intelligence.yaml' -Extra @{ ExpectedSiteGate = 'EXAMPLE_PRESERVE_GATE' })
        Assert-KitBlocked -Name 'Retire of an unprotected dashboard under a pinned site gate: BLOCKED, naming the one-run override' -Run $run -Pattern '-ExpectedSiteGate DASHBOARD_PRESERVE_GATE'
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/ecco/dashboards/ecco_intelligence.yaml' -Extra @{ ExpectedSiteGate = 'DASHBOARD_PRESERVE_GATE' })
        Assert-True -Name '... and with -ExpectedSiteGate DASHBOARD_PRESERVE_GATE it is retired; the site policy and the dashboard it protects are untouched' -Condition (
            $run.Message -eq '' -and -not (Test-Path -LiteralPath (Get-HostPath '/config/ecco/dashboards/ecco_intelligence.yaml')) -and
            (Test-Path -LiteralPath (Get-HostPath '/config/ecco/dashboards/ecco_pro.yaml')) -and (Test-Path -LiteralPath (Get-HostPath '/config/ecco/site-local/dashboard-protection.json'))) -Detail $run.Message
        Reset-KitHost
        [System.IO.File]::WriteAllText((Get-HostPath '/config/packages/ecco_intelligence.yaml'), $pkgText)
        $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath (Get-HostPath '/config/packages') -Destination $elsewhere
        if (New-KitJunction -Link (Get-HostPath '/config/packages') -Target $elsewhere) {
            $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
            Assert-KitBlocked -Name 'Retire through a symlinked segment (/config/packages): BLOCKED before any write' -Run $run -Pattern '/config/packages is link on the host'
        } else {
            Write-Host '  SKIP  Retire through a symlinked segment (mklink /J could not create a junction here)'
        }
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml' -Extra @{ Restart = $true })
        Assert-True -Name 'Retire never restarts: -Action Retire -Restart is refused by parameter binding, before any ssh call' -Condition ($run.Message -match 'Parameter set cannot be resolved' -and $run.Sent.Count -eq 0) -Detail $run.Message
        $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params @{ Action = 'Retire'; Destination = '/config/packages/ecco_intelligence.yaml'; Source = 'dist/stub/x.yaml'; SshHost = 'fictional-host'; Target = 'Production' }
        Assert-True -Name '... and -Action Retire with a -Source is refused the same way' -Condition ($run.Message -match 'Parameter set cannot be resolved' -and $run.Sent.Count -eq 0) -Detail $run.Message

        # -------------------------------------------------------------
        # 23. Amendment A26: the SSH add-on's /config is itself a symlink.
        #     The fictional tree's config folder moves to
        #     example_config_real and config becomes a junction (the sh
        #     sees a symlink). Every route accepts a /config that resolves
        #     to a real folder, prints the resolved root and writes through
        #     it; a dangling /config, one to a file, a loop and a plain file
        #     BLOCK before any write; a symlinked segment below /config
        #     still BLOCKS; and the root re-pointed between the read-only
        #     checks and the first write is refused by the re-check, or -
        #     re-pointed right after that - by the folder-creating command.
        # -------------------------------------------------------------
        Write-Host ''
        Write-Host '[23] Amendment A26: a symlinked /config is accepted through its resolved root; dangling, to-a-file, loop and a changed root are refused'
        $global:EccoKitConfigLink = Join-Path $global:EccoKitTreeWin 'config'
        $global:EccoKitMovedRoot = Join-Path $global:EccoKitTreeWin 'example_config_moved'
        $a26RealWin = Join-Path $global:EccoKitTreeWin 'example_config_real'
        $a26RootLine = 'Config root : /config -> /example_config_real (a symlink to a real folder'
        $a26Unresolved = 'is a symlink that does not resolve to an existing folder'
        # True when a run printed the resolved root exactly twice: once right after the /config probe, and once inside the
        # block that starts with -Header (the Plan or the PASSED block).
        function Test-A26RootLines {
            param([object]$Run, [string]$Header)
            $lines = [string[]]@($Run.Lines)
            $at = [Array]::IndexOf($lines, $Header)
            $all = @($lines | Where-Object { $_.StartsWith($a26RootLine) }).Count
            $inBlock = if ($at -ge 0) { @($lines | Select-Object -Skip $at | Where-Object { $_.StartsWith($a26RootLine) }).Count } else { 0 }
            return ($all -eq 2 -and $inBlock -eq 1)
        }
        # On a fresh fictional host: Store - config becomes a junction to the real folder that now holds the tree; Dangling -
        # to a folder that does not exist; Loop - to a junction that points back at config; File - to a regular file; Plain -
        # config is a regular file. The tree itself always moves to example_config_real.
        function Set-KitHostConfigRoot {
            param([ValidateSet('Store', 'Dangling', 'Loop', 'File', 'Plain')][string]$Mode)
            Move-Item -LiteralPath $global:EccoKitConfigLink -Destination $a26RealWin
            if ($Mode -eq 'Plain') {
                [System.IO.File]::WriteAllText($global:EccoKitConfigLink, "fictional`n")
                return $true
            }
            $target = switch ($Mode) {
                'Store' { $a26RealWin }
                'Dangling' { Join-Path $global:EccoKitTreeWin 'example_config_gone' }
                'Loop' { Join-Path $global:EccoKitTreeWin 'example_config_loop' }
                'File' { Join-Path $global:EccoKitTreeWin 'example_config_file' }
            }
            if ($Mode -eq 'File') { [System.IO.File]::WriteAllText($target, "fictional`n") }
            $ok = New-RawJunction -Link $global:EccoKitConfigLink -Target $target
            if ($ok -and $Mode -eq 'Loop') { $ok = New-RawJunction -Link $target -Target $global:EccoKitConfigLink }
            return $ok
        }
        # Re-points config to example_config_moved (a full copy of the real folder) right after the N-th /config probe a run
        # sends: 1 = after the read-only probe, so the re-check before the first write sees the change; 2 = after that
        # re-check, so only the folder-creating command's own root test is left to see it.
        $global:EccoKitRootProbes = 0
        $global:EccoKitRepointAt = 0
        $a26Hook = {
            param($c)
            if ($c.StartsWith("if [ -L '/config' ]; then echo 'root link'")) {
                $global:EccoKitRootProbes++
                if ($global:EccoKitRootProbes -eq $global:EccoKitRepointAt) {
                    return @{ After = {
                        $previousEap = $ErrorActionPreference
                        $ErrorActionPreference = 'Continue'
                        try {
                            & cmd /c rmdir $global:EccoKitConfigLink 2>&1 | Out-Null
                            & cmd /c mklink /J $global:EccoKitConfigLink $global:EccoKitMovedRoot 2>&1 | Out-Null
                        } finally {
                            $ErrorActionPreference = $previousEap
                        }
                    } }
                }
            }
            return $null
        }
        function Invoke-A26Repoint {
            param([int]$At, [string]$Script = 'deploy-ha-kit.ps1', [hashtable]$Params)
            $global:EccoKitRootProbes = 0
            $global:EccoKitRepointAt = $At
            $global:EccoKitHook = $a26Hook
            try { return (Invoke-KitRun -Script $Script -Params $Params) } finally { $global:EccoKitHook = $null }
        }
        function Reset-A26Moved {
            param([switch]$Package)
            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            if ($Package) { [System.IO.File]::WriteAllText((Join-Path $a26RealWin 'packages\ecco_intelligence.yaml'), $pkgText) }
            Copy-Item -LiteralPath $a26RealWin -Destination $global:EccoKitMovedRoot -Recurse
        }

        Reset-KitHost
        if (-not (Set-KitHostConfigRoot -Mode Store)) {
            Write-Host '  SKIP  section 23 needs junctions (mklink /J could not create one here)'
        } else {
            $realBefore = Get-LocalFileMap -Root $a26RealWin
            $run = Invoke-KitRun -Params (Get-KitParams -Action Plan -KitDir $kitV2)
            $probeAt = [Array]::IndexOf([string[]]@($run.Sent), (Get-EccoConfigRootProbeCommand))
            $targetAt = [Array]::IndexOf([string[]]@($run.Sent), 'ssh -G fictional-host')
            Assert-True -Name 'A26: kit Plan through a symlinked /config: read-only, the real folder unchanged, and the Plan prints the resolved root' -Condition (
                $run.Message -eq '' -and $run.Writes.Count -eq 0 -and (Test-A26RootLines -Run $run -Header 'ECCO INTELLIGENCE KIT PLAN (read-only: nothing was written)') -and $run.Text -match 'Action      : Install' -and
                (Test-SameMap (Get-LocalFileMap -Root $a26RealWin) $realBefore)) -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))
            Assert-True -Name '... /config is probed right after the ssh probe, before the target guard and any other read under /config' -Condition (
                $probeAt -eq 1 -and $targetAt -gt $probeAt) -Detail "probe at $probeAt, target guard at $targetAt"

            $p = Get-KitParams -Action Install -KitDir $kitV2
            $run = Invoke-KitRun -Params $p
            $realInstalled = Join-Path $a26RealWin 'custom_components\ecco_intelligence'
            $mkdirs = @($run.Sent | Where-Object { $_ -match '\bmkdir\b' })
            Assert-True -Name 'A26: kit Install through a symlinked /config: PASSED, the kit is in the real folder, and the run and its PASSED block print the resolved root' -Condition (
                $run.Message -eq '' -and (Test-A26RootLines -Run $run -Header 'ECCO INTELLIGENCE KIT INSTALL PASSED') -and
                (Test-SameMap (Get-LocalFileMap -Root $realInstalled) $kitV2Map)) -Detail ($run.Message + ' || ' + (($run.Lines | Select-Object -Last 6) -join ' | '))
            Assert-True -Name '... every folder-creating command first tested that /config still resolves to /example_config_real' -Condition (
                $mkdirs.Count -ge 1 -and @($mkdirs | Where-Object { -not $_.StartsWith("( cd -P '/config' && pwd -P ) | grep -Fqx '/example_config_real' && ") }).Count -eq 0) -Detail ($mkdirs -join ' | ')
            Reset-KitHost -InstallKit $kitV1
            [void](Set-KitHostConfigRoot -Mode Store)
            Add-HostPycache
            $p = Get-KitParams -Action Upgrade -KitDir $kitV2
            $run = Invoke-KitRun -Params $p
            Assert-True -Name 'A26: kit Upgrade through a symlinked /config: PASSED, v2 in the real folder, and the v1 backup verified there' -Condition (
                $run.Message -eq '' -and $run.Text -match 'ECCO INTELLIGENCE KIT UPGRADE PASSED' -and (Test-SameMap (Get-LocalFileMap -Root $realInstalled) $kitV2Map) -and
                (Test-SameMap (Get-LocalFileMap -Root (Join-Path $a26RealWin "ecco-backups\$($p.Stamp)\custom_components__ecco_intelligence") -IgnorePycache) $kitV1Map)) -Detail $run.Message

            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            $realSite = Join-Path $a26RealWin 'ecco\intelligence\site.local.json'
            Remove-Item -LiteralPath $realSite -Force
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ Plan = $true })
            Assert-True -Name 'A26: placement -Plan through a symlinked /config: read-only, and it prints the resolved root' -Condition (
                $run.Message -eq '' -and $run.Writes.Count -eq 0 -and (Test-A26RootLines -Run $run -Header 'ECCO SITE FILE PLAN (read-only: nothing was written)') -and -not (Test-Path -LiteralPath $realSite)) -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))
            $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams)
            Assert-True -Name 'A26: placement through a symlinked /config: PLACED in the real folder and read back, the resolved root printed' -Condition (
                $run.Message -eq '' -and (Test-A26RootLines -Run $run -Header 'ECCO SITE FILE PLACED') -and (Test-Path -LiteralPath $realSite) -and
                [System.IO.File]::ReadAllText($realSite) -ceq $newSiteText) -Detail $run.Message

            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            [System.IO.File]::WriteAllText((Join-Path $a26RealWin 'packages\ecco_intelligence.yaml'), $pkgText)
            $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
            $retiredCopy = @(Get-ChildItem -LiteralPath (Join-Path $a26RealWin 'ecco-backups') -Recurse -File -Filter 'config__packages__ecco_intelligence.yaml' -ErrorAction SilentlyContinue)
            Assert-True -Name 'A26: Retire through a symlinked /config: PASSED, the file moved into the real folder''s ecco-backups, the resolved root printed' -Condition (
                $run.Message -eq '' -and (Test-A26RootLines -Run $run -Header 'ECCO RETIRE PASSED') -and -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'packages\ecco_intelligence.yaml')) -and
                $retiredCopy.Count -eq 1 -and [System.IO.File]::ReadAllText($retiredCopy[0].FullName) -ceq $pkgText) -Detail $run.Message

            # Refused shapes: the kit route stops after the ssh probe and the /config probe; the placement and Retire too.
            foreach ($case in @(
                    @{ Mode = 'Dangling'; Pattern = $a26Unresolved },
                    @{ Mode = 'File'; Pattern = $a26Unresolved },
                    @{ Mode = 'Loop'; Pattern = $a26Unresolved },
                    @{ Mode = 'Plain'; Pattern = 'is neither a folder nor a symlink' })) {
                Reset-KitHost
                if (-not (Set-KitHostConfigRoot -Mode $case.Mode)) {
                    Write-Host "  SKIP  A26: a /config of shape $($case.Mode) (mklink /J could not create it here)"
                    continue
                }
                $realBefore = Get-LocalFileMap -Root $a26RealWin
                $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV2)
                Assert-KitBlocked -Name "A26: kit Install with a /config of shape $($case.Mode): BLOCKED before any write, naming /config" -Run $run -Pattern ('INTELLIGENCE_KIT: BLOCKED - /config ' + $case.Pattern)
                Assert-True -Name '... only the ssh probe and the /config probe were sent, and the real folder is unchanged' -Condition (
                    $run.Sent.Count -eq 2 -and (Test-SameMap (Get-LocalFileMap -Root $a26RealWin) $realBefore)) -Detail ($run.Sent -join ' | ')
            }
            Reset-KitHost
            if (Set-KitHostConfigRoot -Mode Dangling) {
                $run = Invoke-KitRun -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha })
                Assert-KitBlocked -Name 'A26: placement with a dangling /config: BLOCKED before any write' -Run $run -Pattern ('SITE_FILE: BLOCKED - /config ' + $a26Unresolved)
            }
            Reset-KitHost
            if (Set-KitHostConfigRoot -Mode Loop) {
                $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
                Assert-KitBlocked -Name 'A26: Retire with a /config symlink loop: BLOCKED before any write' -Run $run -Pattern ('RETIRE: BLOCKED - /config ' + $a26Unresolved)
            }

            # A symlinked segment below a symlinked /config is still refused (A15 unchanged), by the probe and by the folder-creating command.
            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
            if (New-KitJunction -Link (Join-Path $a26RealWin 'ecco\staging') -Target $elsewhere) {
                $run = Invoke-KitRun -Params (Get-KitParams -Action Install -KitDir $kitV2)
                Assert-KitBlocked -Name 'A26: with /config a symlink to a real folder, a symlinked segment below it (/config/ecco/staging) still BLOCKS' -Run $run -Pattern '/config/ecco/staging is link on the host'
                $mk = Get-EccoSafeMkdirCommand -ConfigRoot '/example_config_real' -MustExist @('/config/ecco') -MayCreate @('/config/ecco/staging') -MustCreate @('/config/ecco/staging/20300101-999998')
                $r = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mk -Capture
                Assert-True -Name '... the folder-creating command alone refuses it too (the right root, a symlinked segment below), and nothing was created behind it' -Condition (
                    @($r.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 0 -and @(Get-ChildItem -LiteralPath $elsewhere -Force).Count -eq 0) -Detail ($r.Output -join ' | ')
            } else {
                Write-Host '  SKIP  A26: a symlinked segment below a symlinked /config (mklink /J could not create a junction here)'
            }
            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            $mkRight = Get-EccoSafeMkdirCommand -ConfigRoot '/example_config_real' -MustExist @('/config/ecco') -MayCreate @('/config/ecco/staging') -MustCreate @('/config/ecco/staging/20300101-999997')
            $mkWrong = Get-EccoSafeMkdirCommand -ConfigRoot '/example_config_moved' -MustExist @('/config/ecco') -MayCreate @('/config/ecco/staging') -MustCreate @('/config/ecco/staging/20300101-999996')
            $rWrong = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mkWrong -Capture
            $rRight = Invoke-EccoRemoteCommand -SshHost 'fictional-host' -Command $mkRight -Capture
            Assert-True -Name 'A26: the folder-creating command creates nothing when /config resolves to another root than the one it names, and works for the right root' -Condition (
                @($rWrong.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 0 -and -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco\staging\20300101-999996')) -and
                @($rRight.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -eq 1 -and (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco\staging\20300101-999997'))) -Detail (($rWrong.Output -join ' | ') + ' || ' + ($rRight.Output -join ' | '))
            Reset-KitHost
            [void](Set-KitHostConfigRoot -Mode Store)
            [System.IO.File]::WriteAllText((Join-Path $a26RealWin 'packages\ecco_intelligence.yaml'), $pkgText)
            $elsewhere = Join-Path $kitBase ('elsewhere-' + [guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath (Join-Path $a26RealWin 'packages') -Destination $elsewhere
            if (New-KitJunction -Link (Join-Path $a26RealWin 'packages') -Target $elsewhere) {
                $run = Invoke-KitRun -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
                Assert-KitBlocked -Name 'A26: Retire through a symlinked segment below a symlinked /config (/config/packages): BLOCKED before any write' -Run $run -Pattern '/config/packages is link on the host'
            }

            # The root re-pointed between the read-only (Plan) checks and the first write.
            Reset-A26Moved
            $realBefore = Get-LocalFileMap -Root $a26RealWin
            $movedBefore = Get-LocalFileMap -Root $global:EccoKitMovedRoot
            $run = Invoke-A26Repoint -At 1 -Params (Get-KitParams -Action Install -KitDir $kitV2)
            Assert-KitBlocked -Name 'A26: the /config root re-pointed between the Plan checks and the first write: kit Install BLOCKED by the re-check, nothing written' -Run $run -Pattern 'INTELLIGENCE_KIT: BLOCKED - the /config root changed between the read-only checks and the first write: it resolved to /example_config_real, now /example_config_moved'
            Assert-True -Name '... neither folder changed, and no staging folder was made' -Condition (
                (Test-SameMap (Get-LocalFileMap -Root $a26RealWin) $realBefore) -and (Test-SameMap (Get-LocalFileMap -Root $global:EccoKitMovedRoot) $movedBefore) -and
                -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco\staging')) -and -not (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'ecco\staging')))
            Reset-A26Moved
            $realBefore = Get-LocalFileMap -Root $a26RealWin
            $movedBefore = Get-LocalFileMap -Root $global:EccoKitMovedRoot
            $p = Get-KitParams -Action Install -KitDir $kitV2
            $run = Invoke-A26Repoint -At 2 -Params $p
            Assert-True -Name 'A26: the root re-pointed right after that re-check: the folder-creating command refuses it itself (STOPPED before the swap), no upload, no folder made in either place' -Condition (
                $run.Message -match 'INTELLIGENCE_KIT: STOPPED before the swap' -and $run.Message -match 'no longer resolving to /example_config_real' -and
                @($run.Sent | Where-Object { $_.StartsWith('scp-up ') }).Count -eq 0 -and @($run.Writes).Count -eq 1 -and
                (Test-SameMap (Get-LocalFileMap -Root $a26RealWin) $realBefore) -and (Test-SameMap (Get-LocalFileMap -Root $global:EccoKitMovedRoot) $movedBefore) -and
                -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco\staging')) -and -not (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'ecco\staging'))) -Detail ($run.Message + ' || ' + ($run.Writes -join ' | '))
            Assert-True -Name 'DR3-2: ... the message lists no folder as kept (none exists) and says this run''s staging folder may not have been created and nothing was deleted' -Condition (
                $run.Message.Contains((Get-Dr3MkdirLine -Stamp $p.Stamp -Folders 'staging folder')) -and (Test-Dr3NamesNoStampFolder -Run $run -Stamp $p.Stamp)) -Detail $run.Message
            Reset-A26Moved
            $run = Invoke-A26Repoint -At 1 -Script 'place-ha-site-file.ps1' -Params (Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha })
            Assert-KitBlocked -Name 'A26: placement with the root re-pointed before the first write: BLOCKED by the re-check' -Run $run -Pattern 'SITE_FILE: BLOCKED - the /config root changed .* now /example_config_moved'
            Assert-True -Name '... the site file is unchanged in both folders' -Condition (
                [System.IO.File]::ReadAllText((Join-Path $a26RealWin 'ecco\intelligence\site.local.json')) -ceq $siteOld -and
                [System.IO.File]::ReadAllText((Join-Path $global:EccoKitMovedRoot 'ecco\intelligence\site.local.json')) -ceq $siteOld)
            Reset-A26Moved
            $p = Get-PlaceParams -Extra @{ ReplaceExistingSha256 = $oldSha }
            $run = Invoke-A26Repoint -At 2 -Script 'place-ha-site-file.ps1' -Params $p
            Assert-True -Name '... and re-pointed right after the re-check: the folder-creating command refuses it (STOPPED), no backup folder, no upload' -Condition (
                $run.Message -match 'SITE_FILE: STOPPED' -and $run.Message -match 'no longer resolving to /example_config_real' -and
                @($run.Sent | Where-Object { $_.StartsWith('scp-up ') }).Count -eq 0 -and
                -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco-backups')) -and -not (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'ecco-backups'))) -Detail $run.Message
            Reset-A26Moved -Package
            $run = Invoke-A26Repoint -At 1 -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
            Assert-KitBlocked -Name 'A26: Retire with the root re-pointed before the first write: BLOCKED by the re-check, the file not moved' -Run $run -Pattern 'RETIRE: BLOCKED - the /config root changed .* now /example_config_moved'
            Assert-True -Name '... the package file is still in place in both folders' -Condition (
                (Test-Path -LiteralPath (Join-Path $a26RealWin 'packages\ecco_intelligence.yaml')) -and (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'packages\ecco_intelligence.yaml')))
            Reset-A26Moved -Package
            $run = Invoke-A26Repoint -At 2 -Script 'deploy-ha.ps1' -Params (Get-RetireParams -Destination '/config/packages/ecco_intelligence.yaml')
            Assert-True -Name '... and re-pointed right after the re-check: the folder-creating command refuses it (STOPPED), the file not moved' -Condition (
                $run.Message -match 'RETIRE: STOPPED' -and $run.Message -match 'no longer resolving to /example_config_real' -and
                (Test-Path -LiteralPath (Join-Path $a26RealWin 'packages\ecco_intelligence.yaml')) -and (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'packages\ecco_intelligence.yaml')) -and
                -not (Test-Path -LiteralPath (Join-Path $a26RealWin 'ecco-backups')) -and -not (Test-Path -LiteralPath (Join-Path $global:EccoKitMovedRoot 'ecco-backups'))) -Detail $run.Message
        }
        Reset-KitHost
    }
    finally {
        Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath function:global:scp -ErrorAction SilentlyContinue
        Remove-Variable -Name EccoKitSh, EccoKitTreeWin, EccoKitTreeSh, EccoKitLog, EccoKitTagged, EccoKitAll, EccoKitResolved, EccoKitMachine, EccoKitCheckFailures, EccoKitHook, EccoKitScpCorrupt, EccoKitHostSite, EccoKitHookPath, EccoKitConfigLink, EccoKitMovedRoot, EccoKitRootProbes, EccoKitRepointAt, EccoKitMoveMarker, EccoKitProbeStart, EccoKitLossMode, EccoKitAfterMove, EccoKitProbeLost, EccoKitDr4Mode, EccoKitDr4Elsewhere, EccoKitRenameLost, EccoKitScpFail, EccoKitDr3Upload, EccoKitDr3Rejected, EccoKitDr3BackupWin, EccoKitDr3Elsewhere -Scope Global -ErrorAction SilentlyContinue
        Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force
    }
} else {
    Write-Host '  SKIP  sections 19-23 run the kit route on a fictional /config under a POSIX sh with cygpath (Git for Windows; pass -Sh <sh.exe>)'
}

# Static checks (design T6): the kit commands have no restart and no delete; every ha call is its own command.
$kitText = Get-Content -Raw -Path (Join-Path $toolsDir 'deploy-ha-kit.ps1')
$placeText = Get-Content -Raw -Path (Join-Path $toolsDir 'place-ha-site-file.ps1')
$moduleText = Get-Content -Raw -Path (Join-Path $toolsDir 'EccoDeploy.psm1')
$regionAt = $moduleText.IndexOf('# region Intelligence kit route')
$regionEnd = $moduleText.IndexOf('# endregion Intelligence kit route')
$regionText = if ($regionAt -ge 0 -and $regionEnd -gt $regionAt) { $moduleText.Substring($regionAt, $regionEnd - $regionAt) } else { '' }
foreach ($pair in @(@('deploy-ha-kit.ps1', $kitText), @('place-ha-site-file.ps1', $placeText))) {
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($pair[1], [ref]$null, [ref]$null)
    $paramNames = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
    Assert-True -Name "static: $($pair[0]) has no -Restart and no -AllowDirtyWorkingTree parameter" -Condition ($paramNames.Count -gt 5 -and $paramNames -notcontains 'Restart' -and $paramNames -notcontains 'AllowDirtyWorkingTree') -Detail ($paramNames -join ',')
}
Assert-True -Name 'static: the kit-route region of the module was found' -Condition ($regionText.Length -gt 10000)
foreach ($pair in @(@('deploy-ha-kit.ps1', $kitText), @('place-ha-site-file.ps1', $placeText), @('the kit-route region of EccoDeploy.psm1', $regionText))) {
    $code = (@($pair[1].Split("`n") | Where-Object { $_.TrimStart() -notmatch '^#' }) -join "`n")
    Assert-True -Name "static: $($pair[0]) sends no ha core restart, no rm and no recursive mkdir" -Condition (
        $code -notmatch 'ha core restart' -and $code -notmatch "(^|[`"'; &|])rm\s" -and $code -notmatch 'mkdir -p')
    $haLiterals = @([regex]::Matches($pair[1], "'ha [^']*'") | ForEach-Object { $_.Value })
    Assert-True -Name "static: every ha command in $($pair[0]) is exactly 'ha core check' or 'ha core info --raw-json' (never compounded)" -Condition (
        @($haLiterals | Where-Object { $_ -cne "'ha core check'" -and $_ -cne "'ha core info --raw-json'" }).Count -eq 0) -Detail ($haLiterals -join ' ')
}

# ---------------------------------------------------------------------
# 24. Amendment A26, pure logic (no sh needed): the /config probe and its
#     reading, the root test every folder-creating command starts with,
#     and /config never tested per segment. A refusing ssh stub records
#     any call; nothing reaches a host.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[24] Amendment A26: the /config probe and its reading, the root test, and /config never tested per segment'
$rootProbe = Get-EccoConfigRootProbeCommand
Assert-True -Name 'A26 probe: single-quoted words only (no double quote, no dollar sign), [ -L ] before [ -d ], resolved with cd -P and pwd -P, never readlink' -Condition (
    -not $rootProbe.Contains('"') -and -not $rootProbe.Contains('$') -and $rootProbe.StartsWith("if [ -L '/config' ]; then echo 'root link'; elif [ -d '/config' ]; then echo 'root dir';") -and
    $rootProbe.Contains("( cd -P '/config' && printf 'resolved ' && pwd -P )") -and $rootProbe.EndsWith('; echo ECCO_ROOT_END') -and $rootProbe -notmatch 'readlink') -Detail $rootProbe
$rootCases = @(
    @{ Name = 'a real folder'; Out = @('root dir', 'resolved /config', 'ECCO_ROOT_END'); Resolved = '/config' },
    @{ Name = 'a symlink to a real folder'; Out = @('root link', 'resolved /example/real_config', 'ECCO_ROOT_END'); Resolved = '/example/real_config' },
    @{ Name = 'a symlink to a real folder, with a stray stderr line'; Out = @('sh: example warning', 'root link', 'resolved /example_real', 'ECCO_ROOT_END'); Resolved = '/example_real' },
    @{ Name = 'a symlink cd -P cannot enter (dangling, to a file, a loop)'; Out = @('root link', 'sh: cd: /config: No such file or directory', 'ECCO_ROOT_END'); Problem = 'is a symlink that does not resolve to an existing folder' },
    @{ Name = 'a folder the ssh user cannot enter'; Out = @('root dir', 'ECCO_ROOT_END'); Problem = 'cannot enter' },
    @{ Name = 'a regular file'; Out = @('root other', 'ECCO_ROOT_END'); Problem = 'neither a folder nor a symlink' },
    @{ Name = 'an absent /config'; Out = @('root absent', 'ECCO_ROOT_END'); Problem = 'does not exist' },
    @{ Name = 'a real folder whose physical path is not /config'; Out = @('root dir', 'resolved /elsewhere', 'ECCO_ROOT_END'); Problem = 'not understood' },
    @{ Name = 'a symlink resolving to /'; Out = @('root link', 'resolved /', 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a resolved path with a space'; Out = @('root link', 'resolved /example real', 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a resolved path with a single quote'; Out = @('root link', "resolved /example'x", 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a relative resolved path'; Out = @('root link', 'resolved example', 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a resolved path with a dot segment'; Out = @('root link', 'resolved /example/../x', 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a resolved path of 201 characters'; Out = @('root link', ('resolved /' + ('a' * 200)), 'ECCO_ROOT_END'); Problem = 'not a plain absolute path' },
    @{ Name = 'a cut-off answer (no end marker)'; Out = @('root link', 'resolved /example_real'); Problem = 'incomplete' },
    @{ Name = 'two root lines'; Out = @('root dir', 'root link', 'resolved /config', 'ECCO_ROOT_END'); Problem = 'incomplete' },
    @{ Name = 'two resolved lines'; Out = @('root link', 'resolved /example_a', 'resolved /example_b', 'ECCO_ROOT_END'); Problem = 'incomplete' },
    @{ Name = 'no answer'; Out = @(); Problem = 'incomplete' })
foreach ($case in $rootCases) {
    $parsed = ConvertFrom-EccoConfigRootProbe -Output $case.Out
    if ($case.ContainsKey('Problem')) {
        Assert-True -Name "A26 probe reading refuses $($case.Name)" -Condition (
            $null -eq $parsed.Resolved -and $parsed.Problem -match $case.Problem -and $parsed.Line.StartsWith('Config root : REFUSED - ')) -Detail "$($parsed.Problem) | $($parsed.Line)"
    } else {
        Assert-True -Name "A26 probe reading accepts $($case.Name) as $($case.Resolved)" -Condition (
            $parsed.Resolved -ceq $case.Resolved -and $null -eq $parsed.Problem -and $parsed.Line.Contains($case.Resolved)) -Detail "$($parsed.Problem) | $($parsed.Line)"
    }
}
$rootGuard = Get-EccoConfigRootGuardCommand -ConfigRoot '/example_real'
Assert-True -Name 'A26 root test: one pipeline of single-quoted words - cd -P and pwd -P, then a whole-line literal comparison with the resolved root' -Condition (
    $rootGuard -ceq "( cd -P '/config' && pwd -P ) | grep -Fqx '/example_real'") -Detail $rootGuard
foreach ($bad in @('', '/', 'example', "/example'x", '/example real', '/example/../x', '/example/.', ('/' + ('a' * 200)))) {
    $m = Get-RefusalMessage { Get-EccoConfigRootGuardCommand -ConfigRoot $bad }
    Assert-True -Name "A26 root test refuses the root '$(if ($bad.Length -gt 24) { $bad.Substring(0, 24) + '...' } else { $bad })'" -Condition ($m -match 'a plain absolute path') -Detail $m
}
$mk = Get-EccoSafeMkdirCommand -ConfigRoot '/example_real' -MustExist @('/config/ecco') -MustCreate @('/config/ecco/staging')
Assert-True -Name 'A26: the folder-creating command starts with the root test, before any segment test or mkdir' -Condition (
    $mk.StartsWith("( cd -P '/config' && pwd -P ) | grep -Fqx '/example_real' && [ -d '/config/ecco' ] && [ ! -L '/config/ecco' ] && ")) -Detail $mk
foreach ($list in @('MustExist', 'MayCreate', 'MustCreate')) {
    $splat = @{ ConfigRoot = '/example_real' }
    $splat[$list] = @('/config/ecco', '/config')
    $m = Get-RefusalMessage { Get-EccoSafeMkdirCommand @splat }
    Assert-True -Name "A26: the folder-creating command refuses /config itself in -$list (it is never tested per segment)" -Condition ($m -match 'resolved once by Get-EccoRemoteConfigRoot') -Detail $m
}
$m = Get-RefusalMessage { Get-EccoSafeMkdirCommand -ConfigRoot '' -MustExist @('/config/ecco') }
Assert-True -Name 'A26: the folder-creating command refuses to run without a resolved root' -Condition ($m -match 'a plain absolute path') -Detail $m
$global:EccoA26SshCalls = 0
$global:EccoA26Answer = $null
function global:ssh {
    $global:EccoA26SshCalls++
    if ($null -ne $global:EccoA26Answer) {
        $global:LASTEXITCODE = 0
        return $global:EccoA26Answer
    }
    $global:LASTEXITCODE = 255
    return 'fictional: connection refused'
}
try {
    $m = Get-RefusalMessage { Get-EccoRemotePathStates -SshHost 'fictional-host' -Paths @('/config/ecco', '/config') }
    Assert-True -Name 'A26: the shared per-segment probe refuses /config itself, before any ssh call' -Condition (
        $m -match 'resolved once by Get-EccoRemoteConfigRoot' -and $global:EccoA26SshCalls -eq 0) -Detail "$m (ssh calls: $global:EccoA26SshCalls)"
    $m = Get-RefusalMessage { Get-EccoRemoteConfigRoot -SshHost 'fictional-host' -Name 'EXAMPLE' }
    Assert-True -Name 'A26: a /config probe that cannot run (ssh exit 255) BLOCKS' -Condition ($m -match 'EXAMPLE: BLOCKED - /config could not be inspected \(ssh exit code 255\)') -Detail $m
    $m = Get-RefusalMessage { Assert-EccoRemoteConfigRootUnchanged -SshHost 'fictional-host' -ConfigRoot '/example_real' -Name 'EXAMPLE' }
    Assert-True -Name 'A26: a re-check that cannot run BLOCKS too (never taken as unchanged)' -Condition ($m -match 'EXAMPLE: BLOCKED - the /config root changed .* now unknown \(ssh exit code 255\)') -Detail $m
    $global:EccoA26Answer = @('root link', 'resolved /example_other', 'ECCO_ROOT_END')
    $m = Get-RefusalMessage { Assert-EccoRemoteConfigRootUnchanged -SshHost 'fictional-host' -ConfigRoot '/example_real' -Name 'EXAMPLE' }
    Assert-True -Name 'A26: a re-check that resolves to another root BLOCKS, naming both' -Condition ($m -match 'it resolved to /example_real, now /example_other') -Detail $m
    $global:EccoA26Answer = @('root link', 'ECCO_ROOT_END')
    $m = Get-RefusalMessage { Assert-EccoRemoteConfigRootUnchanged -SshHost 'fictional-host' -ConfigRoot '/example_real' -Name 'EXAMPLE' }
    Assert-True -Name 'A26: a re-check that finds /config no longer resolving BLOCKS' -Condition ($m -match 'now refused \(/config is a symlink that does not resolve') -Detail $m
    $global:EccoA26Answer = @('root link', 'resolved /example_real', 'ECCO_ROOT_END')
    $m = Get-RefusalMessage { Assert-EccoRemoteConfigRootUnchanged -SshHost 'fictional-host' -ConfigRoot '/example_real' -Name 'EXAMPLE' }
    $root = Get-EccoRemoteConfigRoot -SshHost 'fictional-host' -Name 'EXAMPLE'
    Assert-True -Name 'control: an unchanged root passes the re-check, and the probe returns it with its line' -Condition (
        $m -eq '' -and $root.Resolved -ceq '/example_real' -and $root.Kind -ceq 'link' -and $root.Line -ceq 'Config root : /config -> /example_real (a symlink to a real folder, resolved with cd -P; checked unchanged before the first write)') -Detail "$m | $($root.Line)"
} finally {
    Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
    Remove-Variable -Name EccoA26SshCalls, EccoA26Answer -Scope Global -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------
# 25. Reviews P1 and DRD-2 (amendments A49, A52), pure logic: the site
#     file's JSON check refuses every file the runtime's SITE_FILE check
#     refuses, never fewer. The runtime's rule (custom_components/
#     ecco_intelligence/runtime/gates.py, _site_json): a file that starts
#     with a UTF-8 byte-order mark is refused (letter B); the bytes are
#     decoded as UTF-8 and read by json.loads, whose parse_constant refuses
#     NaN, Infinity and -Infinity and whose parse_float and parse_int refuse
#     a number beyond the double range (1e999, an integer too large for a
#     double or past Python's integer digit limit) as a non-finite number
#     (N); a syntax error, a byte that is not UTF-8 or a nesting too deep
#     to read is not valid JSON (J); a JSON value that is not an object is
#     refused (O); the rest is read (P). Every corpus case states the
#     runtime's letter (Rt), the code Get-EccoStrictJsonProblem returns
#     (Check; text cases only) and the message Test-EccoSiteFile gives
#     (Place, by default the Check code). runtime_rule.py below is that
#     rule, run by the test Python: its letters must equal the stated ones,
#     and the placement must refuse every case the runtime refuses. It
#     refuses a case the runtime reads only where the case says so
#     (Stricter: ConvertFrom-Json's own refusals, and a nesting deeper than
#     the placement reads). When this checkout holds the runtime itself, its
#     own _site_json judges the corpus as well and must agree with the
#     model. The non-ASCII and escape characters are built from character
#     codes, so no editor or code page changes what is tested (review DRD-4).
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[25] Reviews P1 and DRD-2: the site file''s JSON check refuses every file the runtime refuses (NaN, Infinity, a number beyond the double range, not JSON, too deep, a byte-order mark)'
$tab = [string][char]9
$bs = [string][char]92
$eAcute = [string][char]0xE9
$smiley = [string][char]0xD83D + [string][char]0xDE00
Add-Type -AssemblyName System.Numerics
# 2^1024 - 2^970: the least magnitude Python's float() reads as an infinity and float(int) refuses.
$dblBound = [System.Numerics.BigInteger]::Pow(2, 1024) - [System.Numerics.BigInteger]::Pow(2, 970)
$dblDigits = $dblBound.ToString()
$deepOpen = '[' * 100000
$deepClose = ']' * 100000
$p1Corpus = @(
    @{ Name = 'an empty object'; T = '{}'; Check = $null; Rt = 'P' },
    @{ Name = 'a plain object'; T = '{"a": 1}'; Check = $null; Rt = 'P' },
    @{ Name = 'numbers (minus, fraction, exponent, 0, -0) and the three literals'; T = '{"a": -0.5e-3, "b": [true, false, null], "c": 1E+5, "d": 0, "e": -0, "f": 10.25, "g": 2e-7}'; Check = $null; Rt = 'P' },
    @{ Name = 'NaN, Infinity and -Infinity inside strings, as keys and values'; T = '{"NaN": "Infinity", "x": ["-Infinity", "NaN"]}'; Check = $null; Rt = 'P' },
    @{ Name = 'every two-character JSON escape, and raw non-ASCII text (an accented letter and a surrogate pair)'; T = ('{"e": "\" \\ \/ \b \f \n \r \t ' + $eAcute + ' ' + $smiley + ' caf' + $eAcute + '"}'); Check = $null; Rt = 'P' },
    @{ Name = 'valid \u escapes: lower-case and upper-case hex, a surrogate pair escape, in a key and a value'; T = ('{"k' + $bs + 'u00e9": "' + $bs + 'u00e9 ' + $bs + 'u00C9 ' + $bs + 'uD83D' + $bs + 'uDE00 ' + $bs + 'u0041' + $bs + 'uabcd"}'); Check = $null; Rt = 'P' },
    @{ Name = 'a lone surrogate \u escape (Python reads it)'; T = ('{"a": "' + $bs + 'ud800"}'); Check = $null; Rt = 'P' },
    @{ Name = 'tab, LF, CR and spaces between tokens'; T = "{`n$tab`"a`" :`r`n [ 1 , 2 ] }"; Check = $null; Rt = 'P' },
    @{ Name = 'an escaped backslash then an escaped quote, NaN still inside the string'; T = '{"q": "a \\\" NaN"}'; Check = $null; Rt = 'P' },
    @{ Name = 'a key repeated exactly (Python keeps the last)'; T = '{"a": 1, "a": 2}'; Check = $null; Rt = 'P' },
    @{ Name = 'NaN as a value'; T = '{"a": NaN}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = 'Infinity as a value'; T = '{"a": Infinity}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = '-Infinity as a value'; T = '{"a": -Infinity}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = 'NaN in an array'; T = '{"a": [1, NaN]}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = 'NaN as the value of a key "NaN"'; T = '{"NaN": NaN}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = '-Infinity in a nested object'; T = '{"a": {"b": -Infinity}}'; Check = 'NonFinite'; Rt = 'N' },
    @{ Name = '-NaN (not JSON for Python either)'; T = '{"a": -NaN}'; Check = 'NonFinite'; Rt = 'J' },
    @{ Name = '1e999'; T = '{"site": {"pv_array_kwp": 1e999}}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = '-1e999'; T = '{"site": {"pv_array_kwp": -1e999}}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = '1E400 in an array'; T = '{"a": [1, 1E400]}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = '1.797693134862315808e308 (rounded to the largest double by ConvertFrom-Json)'; T = '{"site": {"pv_array_kwp": 1.797693134862315808e308}}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = '-1.797693134862315808e308'; T = '{"site": {"pv_array_kwp": -1.797693134862315808e308}}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'the integer 1797693134862315808 followed by 290 zeros'; T = ('{"site": {"pv_array_kwp": 1797693134862315808' + ('0' * 290) + '}}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'its negative'; T = ('{"site": {"pv_array_kwp": -1797693134862315808' + ('0' * 290) + '}}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = '0.0000001797693134862315808e315 (leading zeros, a large exponent)'; T = '{"site": {"pv_array_kwp": 0.0000001797693134862315808e315}}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'the integer 2^1024 - 2^970 (the least the runtime refuses)'; T = ('{"a": ' + $dblDigits + '}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'the integer 2^1024 - 2^970 - 1 (the greatest it reads)'; T = ('{"a": ' + ($dblBound - 1).ToString() + '}'); Check = $null; Rt = 'P' },
    @{ Name = 'an integer of 400 digits'; T = ('{"site": {"pv_array_kwp": 1' + ('0' * 399) + '}}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'an integer of 4301 digits (past Python''s integer digit limit)'; T = ('{"_pad": 1' + ('0' * 4300) + '}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'an integer of 5001 digits'; T = ('{"_pad": 1' + ('0' * 5000) + '}'); Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'an exponent of twenty digits'; T = '{"a": 1e99999999999999999999}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'a sentinel key with 1e999 (never echoed)'; T = '{"ECCO-FICTIONAL-SENTINEL-P1": 1e999}'; Check = 'OutOfRange'; Rt = 'N' },
    @{ Name = 'the largest double, 1.7976931348623157e308'; T = '{"a": 1.7976931348623157e308}'; Check = $null; Rt = 'P' },
    @{ Name = '1.797693134862315807e308 (above the largest double, below the bound: Python reads the largest double)'; T = '{"a": 1.797693134862315807e308}'; Check = $null; Rt = 'P' },
    @{ Name = '1e308'; T = '{"site": {"pv_array_kwp": 1e308}}'; Check = $null; Rt = 'P' },
    @{ Name = '1e-999 (a finite zero)'; T = '{"a": 1e-999}'; Check = $null; Rt = 'P' },
    @{ Name = 'a negative exponent of twenty digits (a finite zero)'; T = '{"a": 1e-99999999999999999999}'; Check = $null; Rt = 'P' },
    @{ Name = 'zero with a large exponent'; T = '{"a": [0e999999999999, -0.0E+400]}'; Check = $null; Rt = 'P' },
    @{ Name = 'a 20-digit integer'; T = '{"_pad": 12345678901234567890}'; Check = $null; Rt = 'P' },
    @{ Name = 'an unquoted key'; T = '{a: 1}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'single quotes'; T = "{'a': 1}"; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a line comment'; T = '{"a": 1} // c'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a block comment'; T = '{"a": /* c */ 1}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = '+1'; T = '{"a": +1}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = '.5'; T = '{"a": .5}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = '01'; T = '{"a": 01}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = '1.'; T = '{"a": 1.}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = '1e'; T = '{"a": 1e}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a lone minus'; T = '{"a": -}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'lower-case nan'; T = '{"a": nan}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'True'; T = '{"a": True}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'undefined'; T = '{"a": undefined}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a raw tab inside a string'; T = ('{"a": "x' + $tab + 'y"}'); Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a raw line feed inside a string'; T = "{`"a`": `"x`ny`"}"; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'an unknown escape \x'; T = '{"a": "\x41"}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a short \u escape'; T = '{"a": "\u12"}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a \u escape with a letter that is not hex'; T = ('{"a": "' + $bs + 'u00g0"}'); Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a no-break space between tokens'; T = ('{"a":' + [char]0xA0 + '1}'); Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a vertical tab between tokens'; T = ('{"a": 1' + [char]0x0B + '}'); Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a byte-order mark character after a leading space'; T = (' ' + [char]0xFEFF + '{}'); Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'text after the object'; T = '{"a": 1}x'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a number key'; T = '{1: 2}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'a sentinel key with +1 (never echoed)'; T = '{"ECCO-FICTIONAL-SENTINEL-P1": +1}'; Check = 'NotStrict'; Rt = 'J' },
    @{ Name = 'two members without a comma'; T = '{"a": 1 "b": 2}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a member without its colon'; T = '{"a" 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'two array values without a comma'; T = '{"a": [1 2]}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a trailing comma in an object'; T = '{"a": 1,}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a trailing comma in an array'; T = '{"a": [1,]}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a leading comma in an object'; T = '{,"a": 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a leading comma in an array'; T = '{"a": [,1]}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'two commas'; T = '{"a": 1,, "b": 2}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a member without its value'; T = '{"a":}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'two colons'; T = '{"a":: 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a comma for the colon'; T = '{"a", 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a key without a value inside a nested object'; T = '{"a": {"b"}}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a chained colon'; T = '{"a": "b": "c"}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an array as a key'; T = '{[1]: 2}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a literal as a key'; T = '{true : 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'a number as a key, spaced'; T = '{"a": 1, 2 : 3}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an object as a key after a comma'; T = '{"a": 1, {}: 2}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an extra closing brace'; T = '{"a": 1}}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an extra closing bracket'; T = '{"a": []]}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an unclosed object'; T = '{"a": {"b": 1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an array closed by a brace'; T = '{"a": [1}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an object closed by a bracket'; T = '{"a": {]}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'crossed brackets'; T = '{"a": [1}]'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'two objects'; T = '{"a": 1}{"b": 2}'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'an object then an array'; T = "{} []`n"; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'only an opening brace'; T = '{'; Check = 'NotJson'; Rt = 'J' },
    @{ Name = 'nesting 100 deep (the deepest the placement reads)'; T = ('{"a": ' + ('[' * 99) + (']' * 99) + '}'); Check = $null; Rt = 'P' },
    @{ Name = 'nesting 101 deep (the runtime reads it; the placement does not)'; T = ('{"a": ' + ('[' * 100) + (']' * 100) + '}'); Check = 'TooDeep'; Rt = 'P'; Stricter = $true },
    @{ Name = 'nesting 100001 deep, closed (too deep for the runtime to read)'; T = ('{"a": ' + $deepOpen + $deepClose + '}'); Check = 'TooDeep'; Rt = 'J' },
    @{ Name = 'a JSON array, not an object'; T = '[1, 2]'; Check = $null; Rt = 'O'; Place = 'NotObject' },
    @{ Name = 'a JSON string, not an object'; T = '"site"'; Check = $null; Rt = 'O'; Place = 'NotObject' },
    @{ Name = 'JSON null, not an object'; T = 'null'; Check = $null; Rt = 'O'; Place = 'NotObject' },
    @{ Name = 'a JSON number, not an object'; T = '4.5'; Check = $null; Rt = 'O'; Place = 'NotObject' },
    @{ Name = 'JSON true, not an object'; T = 'true'; Check = $null; Rt = 'O'; Place = 'NotObject' },
    @{ Name = 'an array with NaN (refused as not an object first)'; T = '[1, NaN]'; Check = 'NonFinite'; Rt = 'N'; Place = 'NotObject' },
    @{ Name = '200000 unclosed brackets (too deep for the runtime to read)'; T = ('[' * 200000); Check = 'TooDeep'; Rt = 'J'; Place = 'NotObject' },
    @{ Name = 'only whitespace'; T = "  `n"; Check = 'NotJson'; Rt = 'J'; Place = 'NotObject' },
    @{ Name = 'two keys that differ only in case (the runtime reads them)'; T = '{"a": 1, "A": 2}'; Check = $null; Rt = 'P'; Place = 'Cfj'; Stricter = $true },
    @{ Name = 'an empty key (the runtime reads it)'; T = '{"": 1}'; Check = $null; Rt = 'P'; Place = 'Cfj'; Stricter = $true },
    @{ Name = 'a UTF-8 byte-order mark before an object'; B = ([byte[]](0xEF, 0xBB, 0xBF) + [System.Text.Encoding]::UTF8.GetBytes('{"site": {}}')); Rt = 'B'; Place = 'Bom' },
    @{ Name = 'a UTF-8 byte-order mark before broken JSON'; B = ([byte[]](0xEF, 0xBB, 0xBF) + [System.Text.Encoding]::UTF8.GetBytes('{not json')); Rt = 'B'; Place = 'Bom' },
    @{ Name = 'bytes that are not UTF-8'; B = ([byte[]](0xFF, 0xFE) + [System.Text.Encoding]::UTF8.GetBytes('{}')); Rt = 'J'; Place = 'NotUtf8' },
    @{ Name = 'a UTF-8 encoded surrogate (not UTF-8 for either reader)'; B = ([System.Text.Encoding]::UTF8.GetBytes('{"a": "') + [byte[]](0xED, 0xA0, 0x80) + [System.Text.Encoding]::UTF8.GetBytes('"}')); Rt = 'J'; Place = 'NotUtf8' },
    @{ Name = 'an empty file'; B = [byte[]]@(); Rt = 'J'; Place = 'Empty' })
$p1Dir = Join-Path $kitBase 'p1-corpus'
New-Item -ItemType Directory -Path $p1Dir -Force | Out-Null
$p1Messages = @{
    NonFinite  = 'The site file holds NaN, Infinity or -Infinity, which is not JSON: the runtime refuses it (SITE_FILE FAIL).'
    OutOfRange = 'The site file holds a number beyond the double range (such as 1e999, or an integer too large for a double): the runtime reads it as non-finite and refuses it (SITE_FILE FAIL).'
    TooDeep    = 'The site file nests arrays and objects more than 100 deep: the placement reads no deeper (the runtime reads deeper, but a site file nests about five deep).'
    NotJson    = 'The site file is not valid JSON (a missing or extra comma or colon, a key that is not a string, a bracket not closed or not matched, or nothing or more than one value at the top): the runtime refuses it (SITE_FILE FAIL).'
    NotObject  = 'The site file is not a JSON object.'
    Bom        = 'The site file starts with a byte-order mark.'
    NotUtf8    = 'The site file is not valid UTF-8.'
    Cfj        = 'The site file is strict JSON, but Windows PowerShell''s ConvertFrom-Json cannot read it (for example two keys that differ only in case, or an empty key): the placement refuses it.'
    Empty      = 'The site file is 0 bytes: it must be 1 to 262144 bytes (the runtime''s safety cap).'
}
$notStrictPrefix = 'The site file is not strict JSON ('
$i = 0
foreach ($c in $p1Corpus) {
    $i++
    if ($c.ContainsKey('T')) {
        $c.Bytes = [System.Text.Encoding]::UTF8.GetBytes($c.T)
        $got = Get-EccoStrictJsonProblem -Text $c.T
        Assert-True -Name "P1 check: $($c.Name) -> $(if ($c.Check) { $c.Check } else { 'strict JSON' })" -Condition ($got -ceq $c.Check) -Detail "got '$got'"
    } else {
        $c.Bytes = $c.B
    }
    $file = Join-Path $p1Dir "$i.json"
    [System.IO.File]::WriteAllBytes($file, $c.Bytes)
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant()
    $m = Get-RefusalMessage { Test-EccoSiteFile -Path $file -ExpectedSha256 $sha -RepoRoot $repoRoot }
    $c.Message = $m
    $place = if ($c.Place) { $c.Place } elseif ($c.Check) { $c.Check } else { 'ok' }
    $ok = if ($place -ceq 'ok') { $m -eq '' } elseif ($place -ceq 'NotStrict') { $m.StartsWith($notStrictPrefix) -and $m.EndsWith('): the runtime refuses it (SITE_FILE FAIL).') } else { $m -ceq $p1Messages[$place] }
    Assert-True -Name "P1 Test-EccoSiteFile: $($c.Name) -> $(if ($place -ceq 'ok') { 'accepted' } else { 'refused, ' + $place })" -Condition ($ok -and -not $m.Contains('SENTINEL')) -Detail $m
}
# The runtime's own rule: _site_json as custom_components/ecco_intelligence/runtime/gates.py has it (the BOM test, the UTF-8
# decode, json.loads with the three hooks, the refusals it catches, an object). One letter per case; with a second argument
# (a checkout that holds that file) the real _site_json judges the corpus too, its letters after a space.
$p1Py = Join-Path $p1Dir 'runtime_rule.py'
[System.IO.File]::WriteAllText($p1Py, (@(
    '"""The runtime''s site-file JSON rule, for Test-EccoDeploy.ps1 only (fictional corpus): one letter per case.',
    '',
    'P read (a JSON object), O JSON but not an object, N a non-finite number, J not valid JSON, B a UTF-8 byte-order mark."""',
    'import base64, json, math, sys',
    '',
    '_UTF8_BOM = b"\xef\xbb\xbf"',
    '',
    '',
    'class _NonFinite(ValueError):',
    '    pass',
    '',
    '',
    'def _reject_constant(_name):',
    '    raise _NonFinite()',
    '',
    '',
    'def _finite_float(text):',
    '    v = float(text)',
    '    if not math.isfinite(v):',
    '        raise _NonFinite()',
    '    return v',
    '',
    '',
    'def _finite_int(text):',
    '    try:',
    '        v = int(text)',
    '        float(v)',
    '    except (ValueError, OverflowError):',
    '        raise _NonFinite() from None',
    '    return v',
    '',
    '',
    'def model(raw):',
    '    if raw.startswith(_UTF8_BOM):',
    '        return "B"',
    '    try:',
    '        loaded = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, parse_float=_finite_float,',
    '                            parse_int=_finite_int)',
    '    except _NonFinite:',
    '        return "N"',
    '    except (UnicodeDecodeError, ValueError, RecursionError):',
    '        return "J"',
    '    return "P" if isinstance(loaded, dict) else "O"',
    '',
    '',
    'def real(root):',
    '    """The runtime''s own _site_json, imported without the integration''s __init__ (which needs Home Assistant)."""',
    '    import importlib, pathlib, types',
    '    sys.path.insert(0, root)',
    '    base = pathlib.Path(root, "custom_components")',
    '    for name, path in (("custom_components", base), ("custom_components.ecco_intelligence", base / "ecco_intelligence")):',
    '        module = types.ModuleType(name)',
    '        module.__path__ = [str(path)]',
    '        sys.modules[name] = module',
    '    gates = importlib.import_module("custom_components.ecco_intelligence.runtime.gates")',
    '    texts = (("starts with a UTF-8 byte-order mark", "B"), ("holds a non-finite number", "N"), ("is not valid JSON", "J"),',
    '             ("is JSON but not a JSON object", "O"))',
    '',
    '    def judge(raw):',
    '        loaded, text = gates._site_json(raw)',
    '        if loaded is not None:',
    '            return "P"',
    '        return next(letter for part, letter in texts if part in text)',
    '    return judge',
    '',
    '',
    'cases = [base64.b64decode(item) for item in json.load(open(sys.argv[1], encoding="ascii"))]',
    'out = "".join(model(raw) for raw in cases)',
    'if len(sys.argv) > 2:',
    '    judge = real(sys.argv[2])',
    '    out += " " + "".join(judge(raw) for raw in cases)',
    'print(out)') -join "`n") + "`n")
function Invoke-P1RuntimeRule {
    param([object[]]$Cases, [string]$Name, [string]$RuntimeRoot = '')
    $list = Join-Path $p1Dir "$Name.json"
    [System.IO.File]::WriteAllText($list, ('[' + ((@($Cases | ForEach-Object { '"' + [System.Convert]::ToBase64String($_.Bytes) + '"' })) -join ', ') + ']'))
    $pyArgs = @('-I', '-B', $p1Py, $list)
    if ($RuntimeRoot) { $pyArgs += $RuntimeRoot }
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = ((@(& $Python @pyArgs 2>&1) | ForEach-Object { [string]$_ }) -join "`n").Trim()
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEap
    }
    return [pscustomobject]@{ Code = $code; Out = $out }
}
$wantLetters = -join (@($p1Corpus | ForEach-Object { $_.Rt }))
$runtimeGates = Join-Path $repoRoot 'custom_components\ecco_intelligence\runtime\gates.py'
$hasRuntime = Test-Path -LiteralPath $runtimeGates -PathType Leaf
$rule = Invoke-P1RuntimeRule -Cases $p1Corpus -Name 'corpus' -RuntimeRoot $(if ($hasRuntime) { $repoRoot } else { '' })
$ruleParts = @($rule.Out -split ' ')
Assert-True -Name 'DRD-2: the runtime''s rule (runtime_rule.py, run by the test Python) gives every corpus case the letter the case states (P read, N non-finite, J not valid JSON, O not an object, B byte-order mark)' -Condition (
    $rule.Code -eq 0 -and $ruleParts[0] -ceq $wantLetters) -Detail "python exit $($rule.Code), rule $($ruleParts[0]), stated $wantLetters"
$placedLetters = -join (@($p1Corpus | ForEach-Object { if ($_.Message -eq '') { '1' } else { '0' } }))
$placeWanted = -join (@($p1Corpus | ForEach-Object { if ($_.Rt -ceq 'P' -and -not $_.Stricter) { '1' } else { '0' } }))
$neverFewer = @(for ($j = 0; $j -lt $p1Corpus.Count; $j++) { if ($p1Corpus[$j].Rt -cne 'P' -and $p1Corpus[$j].Message -eq '') { $p1Corpus[$j].Name } })
Assert-True -Name 'DRD-2: the placement refuses every corpus case the runtime refuses (never fewer), and places every case the runtime reads except those marked stricter' -Condition (
    $neverFewer.Count -eq 0 -and $placedLetters -ceq $placeWanted) -Detail ("placed but refused by the runtime: " + ($neverFewer -join ' | ') + "; placed $placedLetters, wanted $placeWanted")
Assert-True -Name 'DRD-2 control: the corpus holds every runtime letter (P, N, J, O, B) and the stricter cases are only the ones it names (101 deep, two keys differing in case, an empty key)' -Condition (
    @('P', 'N', 'J', 'O', 'B' | Where-Object { -not $wantLetters.Contains($_) }).Count -eq 0 -and @($p1Corpus | Where-Object { $_.Stricter }).Count -eq 3)
if ($hasRuntime) {
    Assert-True -Name 'DRD-2: this checkout holds the runtime; its own _site_json gives every corpus case the model''s letter' -Condition (
        $rule.Code -eq 0 -and $ruleParts.Count -eq 2 -and $ruleParts[1] -ceq $ruleParts[0]) -Detail "python exit $($rule.Code): $($rule.Out)"
} else {
    Write-Host '  SKIP  DRD-2: the runtime''s own _site_json is not in this checkout (custom_components/ecco_intelligence/runtime/gates.py); the model above states its rule'
}

# The bound itself: the module's digits are 2^1024 - 2^970, and around it (and around the shorter numbers that straddle it)
# the check refuses exactly the numbers the runtime's rule refuses, in every JSON number form.
$moduleDigits = & ((Get-Command Get-EccoStrictJsonProblem).Module) { $script:EccoDoubleOverflowDigits }
Assert-True -Name 'DRD-2: the module''s overflow bound is the 309 digits of 2^1024 - 2^970 (System.Numerics)' -Condition ($moduleDigits -ceq $dblDigits) -Detail $moduleDigits
$p1Numbers = New-Object System.Collections.Generic.List[string]
foreach ($n in @(1, 2, 3, 5, 8, 13, 16, 17, 18, 19, 20, 21, 40, 100, 200, 300, 308, 309)) {
    $floor = [System.Numerics.BigInteger]::Parse($dblDigits.Substring(0, $n))
    foreach ($v in @(($floor - 1), $floor, ($floor + 1))) {
        $s = $v.ToString()
        $e = 309 - $n
        foreach ($form in @(($s + 'e' + $e), ('0.' + $s + 'e' + ($e + $s.Length)), ('0.000' + $s + 'E+' + ($e + $s.Length + 3)), ($s.Substring(0, 1) + '.' + $s.Substring(1) + '0e' + ($e + $s.Length - 1)))) {
            $p1Numbers.Add($form)
            $p1Numbers.Add('-' + $form)
        }
        if ($n -eq 309) {
            $p1Numbers.Add($s)
            $p1Numbers.Add($s + '.0')
            $p1Numbers.Add($s + '.999')
        }
    }
}
foreach ($extra in @('0', '-0', '0.0', '1e308', '1e309', '2e308', '1E400', '1e999', '-1e999', '1.7976931348623157e308', '1.7976931348623158e308',
        '1e-999', '0e999999999999', '1e99999999999999999999', '1e-99999999999999999999', '1e000000000000000000308', '1e000000000000000000309',
        ('9' * 308), ('9' * 309), ('1' + ('0' * 299)), ('1' + ('0' * 300)), ('1' + ('0' * 4300)), ('1' + ('0' * 5000)), '5e-324', '123.456e-7')) {
    $p1Numbers.Add($extra)
}
$numberCases = @($p1Numbers | ForEach-Object { [pscustomobject]@{ Bytes = [System.Text.Encoding]::ASCII.GetBytes('{"a": ' + $_ + '}') } })
$numberRule = Invoke-P1RuntimeRule -Cases $numberCases -Name 'numbers'
$numberChecks = -join (@($p1Numbers | ForEach-Object { $r = Get-EccoStrictJsonProblem -Text ('{"a": ' + $_ + '}'); if ($null -eq $r) { 'P' } elseif ($r -ceq 'OutOfRange') { 'N' } else { '?' } }))
Assert-True -Name "DRD-2: on $($p1Numbers.Count) numbers around the bound (integers, fractions, exponents, leading zeros, both signs) the check refuses exactly the numbers the runtime's rule refuses" -Condition (
    $numberRule.Code -eq 0 -and $numberRule.Out -ceq $numberChecks -and $numberChecks.Contains('P') -and $numberChecks.Contains('N')) -Detail "python exit $($numberRule.Code), rule $($numberRule.Out), check $numberChecks"

# ---------------------------------------------------------------------
# 26. Review L3W-5 (amendment A49): validate-ecco.ps1 runs the -Python it
#     is given, and deploy-ha.ps1 and deploy-ha-kit.ps1 pass theirs, so a
#     route never falls back to the python on PATH without a word. A
#     throwaway git repository holds copies of the tools and a fictional
#     tools/validate_repo.py that records which interpreter ran it; a
#     fictional python.cmd first on PATH records itself; ssh and scp are
#     stubbed to record (every run stops at the validator, before ssh).
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[26] Review L3W-5: validate-ecco.ps1 runs the route''s -Python, never the python on PATH instead'
$realPython = @(Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
if ($realPython.Count -eq 0) {
    Write-Host "  SKIP  the -Python cases need the test Python as an application ($Python)"
} else {
    $realPythonPath = $realPython[0].Source
    $v26 = Join-Path $kitBase 'l3w5'
    $v26Repo = Join-Path $v26 'repo'
    $v26Fake = Join-Path $v26 'fake-path'
    foreach ($d in @((Join-Path $v26Repo 'tools'), (Join-Path $v26Repo 'home-assistant\packages'), $v26Fake)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
    foreach ($file in @('validate-ecco.ps1', 'deploy-ha.ps1', 'deploy-ha-kit.ps1', 'EccoDeploy.psm1', 'ecco_dashboard_guard.py')) {
        Copy-Item -LiteralPath (Join-Path $toolsDir $file) -Destination (Join-Path $v26Repo 'tools')
    }
    [System.IO.File]::WriteAllText((Join-Path $v26Repo 'tools\validate_repo.py'), (@(
        '"""Fictional stand-in for tools/validate_repo.py (Test-EccoDeploy.ps1 only): records which interpreter ran it."""',
        'import os, sys',
        '',
        'with open(os.environ["ECCO_TEST_VALIDATOR_RECORD"], "a", encoding="utf-8") as f:',
        '    f.write("RAN " + sys.executable + "\n")',
        'raise SystemExit(int(os.environ.get("ECCO_TEST_VALIDATOR_EXIT", "0")))') -join "`n") + "`n")
    [System.IO.File]::WriteAllText((Join-Path $v26Repo 'home-assistant\packages\example_package.yaml'), "# fictional test package`n")
    [System.IO.File]::WriteAllText((Join-Path $v26Repo '.gitignore'), "ecco_dashboard_gate.local.txt`n")
    Invoke-KitGit -Repo $v26Repo -GitArgs @('init', '-q') | Out-Null
    Invoke-KitGit -Repo $v26Repo -GitArgs @('add', '-A') | Out-Null
    Invoke-KitGit -Repo $v26Repo -GitArgs @('commit', '-q', '-m', 'fictional validate repo') | Out-Null
    $v26Record = Join-Path $v26 'record.txt'
    $v26FakePython = Join-Path $v26Fake 'python.cmd'
    [System.IO.File]::WriteAllText($v26FakePython, "@echo off`r`necho PATH-PYTHON>>`"%ECCO_TEST_VALIDATOR_RECORD%`"`r`nexit /b 7`r`n")
    $global:EccoV26Sent = New-Object System.Collections.Generic.List[string]
    function global:ssh { $global:EccoV26Sent.Add('ssh ' + ($args -join ' ')); $global:LASTEXITCODE = 255 }
    function global:scp { $global:EccoV26Sent.Add('scp ' + ($args -join ' ')); $global:LASTEXITCODE = 1 }
    $savedPath = $env:PATH
    $savedRecord = $env:ECCO_TEST_VALIDATOR_RECORD
    $savedExit = $env:ECCO_TEST_VALIDATOR_EXIT
    function Invoke-V26 {
        param([scriptblock]$Block, [string]$ValidatorExit = '0')
        [System.IO.File]::WriteAllText($v26Record, '')
        $env:ECCO_TEST_VALIDATOR_EXIT = $ValidatorExit
        $global:EccoV26Sent.Clear()
        $lines = New-Object System.Collections.Generic.List[string]
        $message = ''
        try {
            & $Block *>&1 | ForEach-Object { $lines.Add([string]$_) }
        } catch {
            $message = $_.Exception.Message
        }
        $ran = @([System.IO.File]::ReadAllLines($v26Record) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        return [pscustomobject]@{ Message = $message; Lines = @($lines); Ran = $ran; Sent = @($global:EccoV26Sent) }
    }
    function Test-RanReal {
        param([object]$Run)
        return (@($Run.Ran).Count -eq 1 -and @($Run.Ran)[0] -eq "RAN $realPythonPath" -and @($Run.Lines | Where-Object { $_ -ceq "Python: $realPythonPath (-Python)" }).Count -eq 1)
    }
    try {
        $env:PATH = $v26Fake + ';' + $savedPath
        $env:ECCO_TEST_VALIDATOR_RECORD = $v26Record
        $validate26 = Join-Path $v26Repo 'tools\validate-ecco.ps1'

        $run = Invoke-V26 { & $validate26 }
        Assert-True -Name 'L3W-5 control: validate-ecco.ps1 with no -Python runs the python on PATH (here the fictional python.cmd first on PATH) and says so' -Condition (
            @($run.Ran).Count -eq 1 -and @($run.Ran)[0] -ceq 'PATH-PYTHON' -and $run.Message -eq 'Repository static validation failed.' -and
            @($run.Lines | Where-Object { $_ -ceq "Python: $v26FakePython (the python on PATH; no -Python given)" }).Count -eq 1) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ',') + ' | ' + (@($run.Lines | Where-Object { $_.StartsWith('Python') }) -join ' | '))
        $run = Invoke-V26 { & $validate26 -Python $realPythonPath }
        Assert-True -Name 'L3W-5: validate-ecco.ps1 -Python <interpreter> runs exactly that interpreter (never the python on PATH), prints it and passes' -Condition (
            (Test-RanReal $run) -and $run.Message -eq '' -and @($run.Lines | Where-Object { $_ -ceq 'ECCO validation PASSED' }).Count -eq 1) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ',') + ' | ' + (@($run.Lines | Where-Object { $_.StartsWith('Python') }) -join ' | '))
        $run = Invoke-V26 { & $validate26 -Python 'example-no-such-python-3f1c' }
        Assert-True -Name 'L3W-5: validate-ecco.ps1 -Python naming no interpreter stops, and nothing runs instead (not the python on PATH)' -Condition (
            $run.Message -ceq 'The Python given with -Python was not found: example-no-such-python-3f1c' -and @($run.Ran).Count -eq 0) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ','))

        # Review DRD-6 (amendment A52): a relative -Python is resolved in the caller's directory, before validate-ecco.ps1
        # moves to the repository root, as the route's own `& $Python` calls resolve it: the caller's file runs, never a file
        # at the same relative path under the repository root.
        $v26Caller = Join-Path $v26 'caller'
        foreach ($d in @((Join-Path $v26Caller 'pyrel'), (Join-Path $v26Repo 'pyrel'))) {
            New-Item -ItemType Directory -Path $d -Force | Out-Null
        }
        $v26CallerPython = Join-Path $v26Caller 'pyrel\python.cmd'
        [System.IO.File]::WriteAllText($v26CallerPython, "@echo off`r`necho CALLER-PYREL>>`"%ECCO_TEST_VALIDATOR_RECORD%`"`r`n`"$realPythonPath`" %*`r`nexit /b %ERRORLEVEL%`r`n")
        [System.IO.File]::WriteAllText((Join-Path $v26Repo 'pyrel\python.cmd'), "@echo off`r`necho REPO-PYREL>>`"%ECCO_TEST_VALIDATOR_RECORD%`"`r`nexit /b 7`r`n")
        Push-Location -LiteralPath $v26Caller
        try {
            $run = Invoke-V26 { & $validate26 -Python '.\pyrel\python.cmd' }
        } finally {
            Pop-Location
        }
        Assert-True -Name 'DRD-6: validate-ecco.ps1 -Python <a relative path> runs the file under the caller''s directory, never the same relative path under the repository root, and prints its full path' -Condition (
            $run.Message -eq '' -and @($run.Ran).Count -eq 2 -and @($run.Ran)[0] -ceq 'CALLER-PYREL' -and @($run.Ran)[1] -eq "RAN $realPythonPath" -and
            @($run.Lines | Where-Object { $_ -eq "Python: $v26CallerPython (-Python)" }).Count -eq 1) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ',') + ' | ' + (@($run.Lines | Where-Object { $_.StartsWith('Python') }) -join ' | '))
        # The throwaway repository is clean again for the route cases below.
        Remove-Item -LiteralPath (Join-Path $v26Repo 'pyrel') -Recurse -Force

        $deploy26 = Join-Path $v26Repo 'tools\deploy-ha.ps1'
        $run = Invoke-V26 -ValidatorExit '3' { & $deploy26 -Source 'home-assistant/packages/example_package.yaml' -SshHost 'fictional-host' -Target Production -Python $realPythonPath }
        Assert-True -Name 'L3W-5: deploy-ha.ps1 -Python <interpreter> (no -SkipValidation): the repository validator runs under that interpreter, never the python on PATH; its failure stops the run before any ssh call' -Condition (
            (Test-RanReal $run) -and $run.Message -eq 'Repository static validation failed.' -and @($run.Sent).Count -eq 0) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ',') + ' | sent: ' + (@($run.Sent) -join ' | '))

        $kit26 = Join-Path $v26Repo 'tools\deploy-ha-kit.ps1'
        $noKit = Join-Path $v26 'no-kit'
        $run = Invoke-V26 -ValidatorExit '3' { & $kit26 -Action Plan -SshHost 'fictional-host' -Target Production -ExpectedHaVersion '2030.1.0' -Kit $noKit -ExpectedSumsSha256 ('0' * 64) -ReferenceKit $noKit -ReferenceSumsSha256 ('0' * 64) -Python $realPythonPath -Stamp '20300101-000901' }
        Assert-True -Name 'L3W-5: deploy-ha-kit.ps1 -Python <interpreter> (no -SkipValidation): the repository validator runs under that interpreter, never the python on PATH; its failure stops the run before any ssh call' -Condition (
            (Test-RanReal $run) -and $run.Message -eq 'Repository static validation failed.' -and @($run.Sent).Count -eq 0) -Detail ($run.Message + ' | ran: ' + (@($run.Ran) -join ',') + ' | sent: ' + (@($run.Sent) -join ' | '))
    } finally {
        $env:PATH = $savedPath
        $env:ECCO_TEST_VALIDATOR_RECORD = $savedRecord
        $env:ECCO_TEST_VALIDATOR_EXIT = $savedExit
        Remove-Item -LiteralPath function:global:ssh -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath function:global:scp -ErrorAction SilentlyContinue
        Remove-Variable -Name EccoV26Sent -Scope Global -ErrorAction SilentlyContinue
        # deploy-ha.ps1 and deploy-ha-kit.ps1 re-imported the module from the copy: use the checkout's own again.
        Import-Module (Join-Path $toolsDir 'EccoDeploy.psm1') -Force
    }
}
}
finally {
    Remove-KitJunctions
    Remove-Item -LiteralPath $kitBase -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------
# 27. Reviews DRD-1, DRD2-2 and DRD2-4 (amendments A41, A45, A52; A47
#     keeps the engineering labels): the deploy route's public text
#     carries no dated owner decision or approval, no decision item number,
#     no date of the 2020s (written out, ISO, a day and month, a month and
#     year), no live-read evidence label and no word amendment A41 lists.
#     Every file of the route's path set is read as it is in this checkout,
#     whole, so a phrase broken across lines is still found. Amendment and review ids (A49, L3W-6) and
#     opaque decision ids may stay. Negative controls: each pattern flags a
#     fictional sample, and the samples are built from pieces so that this
#     file never matches its own patterns.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[27] Reviews DRD-1 and DRD2-4: the route''s public text carries no dated owner decision, item number, date, live-read evidence label or word amendment A41 lists'
$textFiles = @('.gitignore', 'docs/user/intelligence-deploy.md', 'tools/EccoDeploy.psm1', 'tools/deploy-ha-kit.ps1', 'tools/deploy-ha.ps1',
    'tools/ecco_deploy_preflight.py', 'tools/place-ha-site-file.ps1', 'tools/tests/Test-EccoDeploy.ps1',
    'tools/tests/test_ecco_deploy_preflight.py', 'tools/validate-ecco.ps1')
$textPatterns = [ordered]@{
    'a dated owner decision, answer or approval' = '(?i)\bowner(?:''s)?[\s-]+(?:decisions?|answers?|approvals?)\s+(?:of|on|dated|from)\s'
    'an approval or decision credited to the owner with a date' = '(?i)\b(?:approved|decided|answered)\s+by\s+the\s+owner\s+(?:on|in)\s'
    'a decision item number' = '(?i)\bdecisions?\b[^.]{0,40}?\bitems?\s+\d'
    'a written-out date of the 2020s' = '(?i)\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+202\d\b'
    'an ISO date of the 2020s' = '\b202\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b'
    'a day and month' = '\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\b'
    'a month and year of the 2020s' = '(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+202\d\b'
    'a live-read evidence label' = '(?i)\blive\s+read(?:-only)?\s+(?:facts|evidence|records?)\b'
    'a word amendment A41 lists' = ('(?i)\b(?:release\s+bo' + 'ard|live\s+lo' + 'ck|supervised\s+(?:live\s+)?st' + 'eps?|chat' + 'gpt|bri' + 'dge|pack' +
        'ets?|close-?' + 'outs?)\b')
}
function Get-EccoPublicTextHits {
    param([string]$Text, [string]$Pattern)
    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($m in [regex]::Matches($Text, $Pattern)) {
        $hits.Add("line $(1 + [regex]::Matches($Text.Substring(0, $m.Index), "`n").Count)")
    }
    return @($hits)
}
$textRead = @{}
foreach ($rel in $textFiles) {
    $textPath = Join-Path $repoRoot ($rel -replace '/', '\')
    if (Test-Path -LiteralPath $textPath -PathType Leaf) {
        $textRead[$rel] = [System.IO.File]::ReadAllText($textPath, [System.Text.Encoding]::UTF8)
    }
}
Assert-True -Name "DRD-1: every file of the route's path set was read ($($textFiles.Count) files), so the scan is never empty" -Condition (
    $textRead.Count -eq $textFiles.Count -and @($textRead.Values | Where-Object { $_.Length -eq 0 }).Count -eq 0) -Detail (@($textFiles | Where-Object { -not $textRead.ContainsKey($_) }) -join ', ')
foreach ($desc in $textPatterns.Keys) {
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($rel in $textFiles) {
        if (-not $textRead.ContainsKey($rel)) { continue }
        foreach ($hit in @(Get-EccoPublicTextHits -Text $textRead[$rel] -Pattern $textPatterns[$desc])) { $found.Add("$rel $hit") }
    }
    Assert-True -Name "DRD-1: no file of the route's path set carries $desc" -Condition ($found.Count -eq 0) -Detail ($found -join ' | ')
}
# Fictional samples, built from pieces (the year 2029, the item number and the evidence step are fictional).
$textSamples = @(
    @('a dated owner decision, answer or approval', ('(PR-5, owner ' + 'decision of' + "`n" + '# 1 J' + 'an 20' + '29, it' + 'em 7)'), 'a doc phrase broken across a comment line'),
    @('a dated owner decision, answer or approval', ('the owner' + "'s answ" + 'er of 2 F' + 'eb'), 'the possessive form'),
    @('an approval or decision credited to the owner with a date', ('approved by the ow' + 'ner on 3 M' + 'ar'), 'the approved-by-the-owner form'),
    @('a decision item number', ('(the example decis' + 'ion, it' + 'em 7)'), 'a decision and its item number'),
    @('a written-out date of the 2020s', ('decided on 4 A' + 'pr. 20' + '29'), 'a date with an abbreviated month'),
    @('a written-out date of the 2020s', ('on 5 N' + 'ovember, 20' + '29'), 'a date with the full month and a comma'),
    @('an ISO date of the 2020s', ('(decided 20' + '29-01-31)'), 'an ISO date'),
    @('a day and month', ('read on 6 D' + 'ec'), 'a day and an abbreviated month without the year'),
    @('a day and month', ('on the 7th J' + 'uly'), 'an ordinal day and the full month'),
    @('a month and year of the 2020s', ('in S' + 'ept. 20' + '29'), 'a month and year without the day'),
    @('a live-read evidence label', ('checked against the live re' + 'ad evidence'), 'a live-read evidence noun'),
    @('a live-read evidence label', ('the live read-' + 'only records'), 'the read-only form'),
    @('a word amendment A41 lists', ('release b' + 'oard'), 'listed word 1'),
    @('a word amendment A41 lists', ('live l' + 'ock'), 'listed word 2'),
    @('a word amendment A41 lists', ('supervised s' + 'tep'), 'listed word 3'),
    @('a word amendment A41 lists', ('b' + 'ridge'), 'listed word 4'),
    @('a word amendment A41 lists', ('Chat' + 'GPT'), 'listed word 5'),
    @('a word amendment A41 lists', ('p' + 'acket'), 'listed word 6'),
    @('a word amendment A41 lists', ('close' + '-out'), 'listed word 7'))
foreach ($sample in $textSamples) {
    Assert-True -Name "DRD-1 negative control: the scan for $($sample[0]) flags a fictional sample ($($sample[2]))" -Condition (
        @(Get-EccoPublicTextHits -Text $sample[1] -Pattern $textPatterns[$sample[0]]).Count -eq 1)
}
$keptLabels = '(review L3W-6, amendment A49; the example decision DP-9; Home Assistant 2030.1.0; stamp 20300101-000901; fixture day 2030-01-01; liveness; the live state; no live read: refused; step 2 may stop; the boarding check; retry 3 Decimal places, 2 Octal digits, 1 Junction point, 5 Mayday)'
$keptHits = @($textPatterns.Keys | Where-Object { @(Get-EccoPublicTextHits -Text $keptLabels -Pattern $textPatterns[$_]).Count -gt 0 })
Assert-True -Name 'DRD-1 control: engineering labels, an opaque decision id, a version, a stamp, a 2030 fixture date, plain "live" and "may" wording and a number before a word that begins like a month are not flagged' -Condition (
    $keptHits.Count -eq 0) -Detail ($keptHits -join ', ')

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
Write-Host '  - The dashboard preservation gate''s real ssh/scp reads (site policy, live dashboard, lovelace_resources) and verify-live on a real host'
Write-Host '  - The Intelligence kit route on the isolated test instance (L3): the SSH add-on''s BusyBox or coreutils find/stat/df/cp/mv, a real ha core check, the -Target guard against the real marker and ha core info, and a restart that loads the integration'
Write-Host ''

if ($script:fail -gt 0) {
    throw "$script:fail offline test(s) failed."
}

Write-Host 'ECCO deployment tooling offline tests PASSED'
