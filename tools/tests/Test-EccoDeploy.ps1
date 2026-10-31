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
    prove the restored file gets a new modification time. They need a Python with PyYAML,
    the same requirement deploy-ha.ps1 has; pass -Python <path to
    python.exe> when the python on PATH has no PyYAML.

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
$firstWrite = @($deployHaText.IndexOf("mkdir -p '"), $deployHaText.IndexOf("cp -p '`$Destination'"), $deployHaText.IndexOf('& scp -q $sourceFull')) | Where-Object { $_ -ge 0 } | Sort-Object | Select-Object -First 1
Assert-True -Name 'deploy-ha.ps1 runs the gate before its first remote write (mkdir, backup, upload)' -Condition ($gateAt -gt 0 -and $null -ne $firstWrite -and $gateAt -lt $firstWrite)

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
#     harness would see a write.
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[14] deploy-ha.ps1 against a stubbed host: a BLOCKED gate sends nothing but its reads'
$distDir = Join-Path $repoRoot 'dist'
$distExisted = Test-Path -LiteralPath $distDir
$stubName = 'ecco-gate-test-' + [guid]::NewGuid().ToString('N')
$stubRepoDir = Join-Path $distDir $stubName
$stubHostDir = Join-Path ([System.IO.Path]::GetTempPath()) $stubName
New-Item -ItemType Directory -Path $stubRepoDir -Force | Out-Null
New-Item -ItemType Directory -Path $stubHostDir | Out-Null
$global:EccoTestRemoteLog = New-Object System.Collections.Generic.List[string]
try {
    $stubLive = Join-Path $stubHostDir 'live.yaml'
    $stubResources = Join-Path $stubHostDir 'lovelace_resources'
    [System.IO.File]::WriteAllText($stubLive, ($liveText -join "`n"))
    [System.IO.File]::WriteAllText($stubResources, '{"version": 1, "key": "lovelace_resources", "data": {"items": []}}')
    [System.IO.File]::WriteAllText((Join-Path $stubRepoDir 'generic.yaml'), ($genericText -join "`n"))
    [System.IO.File]::WriteAllText((Join-Path $stubRepoDir 'same.yaml'), ($liveText -join "`n"))
    $global:EccoTestHost = @{ $destination = $stubLive; $resourcesRemote = $stubResources }

    function global:ssh {
        $command = [string]$args[$args.Count - 1]
        $global:EccoTestRemoteLog.Add('ssh ' + $command)
        $global:LASTEXITCODE = 0
        if ($command -ceq 'true') { return }
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

    $deployHa = Join-Path $toolsDir 'deploy-ha.ps1'
    $gateReads = { param($entry) ($entry -ceq 'ssh true') -or $entry.StartsWith("ssh if [ -L '") -or ($entry -cmatch '^scp -q fictional-host:/') }

    $global:EccoTestRemoteLog.Clear()
    $blockedMessage = ''
    try {
        & $deployHa -Source "dist/$stubName/generic.yaml" -Destination $destination -SshHost 'fictional-host' -SkipValidation -AllowDirtyWorkingTree -Python $Python 6>$null 3>$null | Out-Null
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
        & $deployHa -Source "dist/$stubName/same.yaml" -Destination $destination -SshHost 'fictional-host' -SkipValidation -AllowDirtyWorkingTree -Python $Python 6>$null 3>$null | Out-Null
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
            & $deployHa -Source "dist/$stubName/$File" -Destination $destination -SshHost 'fictional-host' -SkipValidation -AllowDirtyWorkingTree -Python $Python @Extra 3>&1 6>$null |
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
    $pinPath = Get-EccoDashboardGatePinPath -RepoRoot $repoRoot
    if (-not (Test-Path -LiteralPath $pinPath)) {
        try {
            [System.IO.File]::WriteAllText($pinPath, "EXAMPLE_PRESERVE_GATE`n")
            $ErrorActionPreference = 'Continue'
            & git -C $repoRoot check-ignore -q -- $pinPath 2>&1 | Out-Null
            $pinIgnored = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = 'Stop'
            Assert-True -Name 'the local pin file is git-ignored' -Condition $pinIgnored
            $run = Invoke-StubDeploy -File 'same.yaml'
            Assert-True -Name 'deploy-ha.ps1 reads the local pin file when -ExpectedSiteGate is not given: the same deployment is BLOCKED, naming the pin file' -Condition (
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
    } else {
        Write-Host '  SKIP  the local pin file runs (this checkout has its own ecco_dashboard_gate.local.txt; it was left untouched)'
    }

    # Drift recovery through deploy-ha.ps1: the host's live file drifted from its policy; the candidate is the policy's layer.
    $stubPolicy = Join-Path $stubHostDir 'policy.json'
    $stubDrifted = Join-Path $stubHostDir 'drifted.yaml'
    $ErrorActionPreference = 'Continue'
    & $Python -I -B -X utf8 $guard make-policy --gate EXAMPLE_PRESERVE_GATE --destination $destination --base (Join-Path $stubRepoDir 'generic.yaml') --live $stubLive --pointer /views/0/sections/0/cards/0 --out $stubPolicy 2>&1 | Out-Null
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
    Remove-Item -LiteralPath $stubRepoDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stubHostDir -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $distExisted -and (Test-Path -LiteralPath $distDir) -and @(Get-ChildItem -LiteralPath $distDir -Force).Count -eq 0) {
        Remove-Item -LiteralPath $distDir -Force -ErrorAction SilentlyContinue
    }
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
Assert-True -Name 'deploy-ha.ps1 passes -Dashboard (the gate applied) to every rollback' -Condition (
    ([regex]::Matches($deployHaText, 'Invoke-EccoDeploymentRollback ')).Count -eq 4 -and
    ([regex]::Matches($deployHaText, [regex]::Escape('-HadOriginal $hadOriginal -Dashboard:($dashboardGate.Applies) -Reason '))).Count -eq 4)

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
Write-Host ''

if ($script:fail -gt 0) {
    throw "$script:fail offline test(s) failed."
}

Write-Host 'ECCO deployment tooling offline tests PASSED'
