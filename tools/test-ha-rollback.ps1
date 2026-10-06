[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha',

    # This script deliberately pushes malformed configuration to a live
    # Home Assistant instance to prove the rollback path works, which
    # means Home Assistant's configuration is intentionally broken for the
    # short window before rollback completes. This switch exists so that
    # can never happen from a casual/accidental invocation - it must be
    # supplied explicitly every time.
    [switch]$IUnderstandThisTemporarilyBreaksHomeAssistant
)

$ErrorActionPreference = 'Stop'

if (-not $IUnderstandThisTemporarilyBreaksHomeAssistant) {
    throw @'
This test deliberately deploys malformed configuration to a live Home
Assistant instance to prove that deploy-ha.ps1 rolls it back correctly.
Home Assistant's configuration is intentionally invalid for the short
window before rollback completes.

Re-run with:
  .\tools\test-ha-rollback.ps1 -IUnderstandThisTemporarilyBreaksHomeAssistant
'@
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$localTest = Join-Path $repoRoot ".ecco-rollback-test-$stamp.yaml"
$remoteTest = "/config/packages/ecco_deploy_rollback_test_$stamp.yaml"

# Use deliberately malformed YAML so Home Assistant's YAML loader itself must
# reject the temporary package. An unknown integration/domain can be accepted by
# `ha core check` in some package configurations, so it is not a reliable failure
# trigger for proving rollback.
$payload = @'
sensor:
  - platform: template
    sensors:
      ecco_deliberate_rollback_test:
        value_template: [
'@

try {
    Write-Host 'ECCO deployment rollback test'
    Write-Host ''

    Write-Host '[baseline 1/2] remove stale rollback-test files from earlier attempts'
    # The SSH add-on login shell is zsh, where an unmatched glob is an error.
    # Use find -name instead so cleanup succeeds whether zero, one, or many
    # rollback-test files exist.
    & ssh -o BatchMode=yes $SshHost "find /config/packages -maxdepth 1 -type f -name 'ecco_deploy_rollback_test_*.yaml' -delete"
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to remove stale rollback-test files.'
    }

    Write-Host '[baseline 2/2] confirm Home Assistant config is healthy before test'
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $baseline = @(& ssh -o BatchMode=yes $SshHost 'ha core check' 2>&1)
        $baselineCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $baseline | ForEach-Object { Write-Host $_.ToString() }
    if ($baselineCode -ne 0) {
        throw 'Home Assistant configuration is not healthy before rollback test.'
    }

    Set-Content -Path $localTest -Value $payload -Encoding utf8

    Write-Host ''
    Write-Host "Temporary destination: $remoteTest"
    Write-Host 'Expected result: malformed YAML fails HA validation and deploy-ha.ps1 rolls it back.'
    Write-Host ''

    $rolledBack = $false
    try {
        # -AllowDirtyWorkingTree: $localTest is an untracked file created
        # directly in the repo root for this test, which would otherwise
        # trip deploy-ha.ps1's normal clean-tree requirement. That is
        # expected and deliberate here, not a real uncommitted change.
        & (Join-Path $PSScriptRoot 'deploy-ha.ps1') `
            $localTest `
            -Destination $remoteTest `
            -SshHost $SshHost `
            -SkipValidation `
            -AllowDirtyWorkingTree

        throw 'Rollback test unexpectedly passed Home Assistant validation.'
    }
    catch {
        $message = $_.Exception.Message
        Write-Host ''
        Write-Host "Deployment result: $message"
        if ($message -match 'was rolled back') {
            $rolledBack = $true
        } else {
            throw
        }
    }

    if (-not $rolledBack) {
        throw 'Rollback was not confirmed.'
    }

    Write-Host '[verify 1/2] temporary remote file removed'
    & ssh -o BatchMode=yes $SshHost "test ! -e '$remoteTest'"
    if ($LASTEXITCODE -ne 0) {
        throw "Rollback verification failed: temporary file still exists at $remoteTest"
    }

    Write-Host '[verify 2/2] Home Assistant config healthy after rollback'
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $check = @(& ssh -o BatchMode=yes $SshHost 'ha core check' 2>&1)
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $check | ForEach-Object { Write-Host $_.ToString() }
    if ($code -ne 0) {
        throw 'Home Assistant configuration is not healthy after rollback test.'
    }

    Write-Host ''
    Write-Host 'ECCO ROLLBACK TEST PASSED'
    Write-Host 'Failure path, file removal, and post-rollback HA validation were all proven.'
}
finally {
    Remove-Item -Path $localTest -Force -ErrorAction SilentlyContinue
}
