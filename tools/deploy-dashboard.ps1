[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha',
    [switch]$Restart,

    # Passed straight through to deploy-ha.ps1. Deliberately named so a
    # one-line uncommitted dashboard tweak can be tested without silently
    # accepting a dirty working tree by default.
    [switch]$AllowDirtyWorkingTree
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

& (Join-Path $PSScriptRoot 'deploy-ha.ps1') @deployParams

Write-Host ''
Write-Host 'Dashboard YAML copied to /config/ecco/dashboards/ecco_pro.yaml.'
Write-Warning 'This does not register or switch Home Assistant to YAML dashboard mode. Registration remains a deliberate one-time HA configuration step.'
