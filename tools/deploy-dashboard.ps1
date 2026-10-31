[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha',
    [switch]$Restart,

    # Passed straight through to deploy-ha.ps1. Deliberately named so a
    # one-line uncommitted dashboard tweak can be tested without silently
    # accepting a dirty working tree by default.
    [switch]$AllowDirtyWorkingTree,

    # Passed straight through to deploy-ha.ps1: custom card types the live
    # dashboard uses that this deployment may deliberately drop (the
    # preservation gate's generic layer only; a site policy's protected
    # layers are never waived).
    [ValidatePattern('^custom:[A-Za-z0-9][A-Za-z0-9._-]*\z')]
    [string[]]$AcceptRemovedCardType = @(),

    # Passed straight through to deploy-ha.ps1: the Python (with PyYAML)
    # that runs the dashboard preservation gate.
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$source = 'home-assistant/dashboards/ecco_pro.yaml'
$deployParams = @{
    Source = $source
    Destination = '/config/ecco/dashboards/ecco_pro.yaml'
    SshHost = $SshHost
}
if ($Restart) {
    $deployParams.Restart = $true
}
if ($AllowDirtyWorkingTree) {
    $deployParams.AllowDirtyWorkingTree = $true
}
if ($AcceptRemovedCardType.Count -gt 0) {
    $deployParams.AcceptRemovedCardType = $AcceptRemovedCardType
}
if ($Python) {
    $deployParams.Python = $Python
}

& (Join-Path $PSScriptRoot 'deploy-ha.ps1') @deployParams

Write-Host ''
Write-Host 'Dashboard YAML copied to /config/ecco/dashboards/ecco_pro.yaml.'
Write-Warning 'This does not register or switch Home Assistant to YAML dashboard mode. Registration remains a deliberate one-time HA configuration step.'
