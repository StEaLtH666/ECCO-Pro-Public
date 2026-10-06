[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha'
)

$ErrorActionPreference = 'Stop'

$remoteScript = @'
if [ -z "$SUPERVISOR_TOKEN" ]; then
  echo __ECCO_NO_SUPERVISOR_TOKEN__
  exit 42
fi

curl -fsS \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  http://supervisor/core/api/states
'@

# Windows PowerShell can translate pipeline newlines to CRLF before native SSH.
# Encode the remote shell script as base64 so /bin/sh receives exact LF text and
# the Authorization header never crosses the Windows command-line parser.
$remoteText = $remoteScript.Replace("`r", '')
$remoteBytes = [System.Text.Encoding]::UTF8.GetBytes($remoteText)
$remoteBase64 = [Convert]::ToBase64String($remoteBytes)
$remoteCommand = "printf %s $remoteBase64 | base64 -d | sh"

$response = @(& ssh -o BatchMode=yes $SshHost $remoteCommand 2>&1)
$code = $LASTEXITCODE

if ($code -eq 42 -or ($response -join "`n") -match '__ECCO_NO_SUPERVISOR_TOKEN__') {
    throw 'The SSH add-on did not expose a Supervisor token. ecco-snapshot.ps1 needs a different read-only HA API path on this installation.'
}
if ($code -ne 0) {
    $response | ForEach-Object { Write-Host $_ }
    throw "Unable to query Home Assistant states through the Supervisor API (exit $code)."
}

$json = $response -join "`n"
try {
    $decoded = $json | ConvertFrom-Json
} catch {
    throw 'Home Assistant state response was not valid JSON.'
}

# Supervisor proxy responses may wrap Home Assistant API data as
# {"result":"ok","data":[...]}. Direct Core API responses are a bare array.
if ($null -ne $decoded.PSObject.Properties['data']) {
    $states = @($decoded.data)
} else {
    $states = @($decoded)
}

$states = @($states | Where-Object {
    $null -ne $_ -and
    $null -ne $_.PSObject.Properties['entity_id'] -and
    -not [string]::IsNullOrWhiteSpace([string]$_.entity_id)
})

if ($states.Count -eq 0) {
    $topLevel = @($decoded.PSObject.Properties.Name) -join ', '
    throw "Home Assistant API returned no state objects. Top-level fields: $topLevel"
}

$stateIndex = @{}
foreach ($state in $states) {
    $stateIndex[[string]$state.entity_id] = $state
}

$wanted = @(
    @{ Label = 'Telemetry'; Entity = 'binary_sensor.ecco_clock_dongle_telemetry_online' },
    @{ Label = 'Configuration'; Entity = 'binary_sensor.ecco_clock_dongle_configuration_online' },
    @{ Label = 'Runtime config'; Entity = 'binary_sensor.ecco_runtime_configuration_ready' },
    @{ Label = 'Grid connected'; Entity = 'binary_sensor.ecco_clock_dongle_ecco_grid_connected' },
    @{ Label = 'Battery SOC (raw)'; Entity = 'sensor.ecco_clock_dongle_ecco_battery_soc' },
    @{ Label = 'Battery SOC (canonical)'; Entity = 'sensor.ecco_battery_soc' },
    @{ Label = 'PV power (raw)'; Entity = 'sensor.ecco_clock_dongle_ecco_pv_power' },
    @{ Label = 'PV power (canonical)'; Entity = 'sensor.ecco_pv_power' },
    @{ Label = 'House load (raw)'; Entity = 'sensor.ecco_clock_dongle_ecco_load_power' },
    @{ Label = 'House power (canonical)'; Entity = 'sensor.ecco_house_power' },
    @{ Label = 'Grid CT power (raw)'; Entity = 'sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp' },
    @{ Label = 'Grid power (canonical)'; Entity = 'sensor.ecco_grid_power' },
    @{ Label = 'Grid import today'; Entity = 'sensor.ecco_clock_dongle_ecco_day_grid_import' },
    @{ Label = 'Grid export today'; Entity = 'sensor.ecco_clock_dongle_ecco_day_grid_export' },
    @{ Label = 'PV today'; Entity = 'sensor.ecco_clock_dongle_ecco_day_pv_energy' },
    @{ Label = 'Charge start'; Entity = 'sensor.ecco_config_charge_start_time' },
    @{ Label = 'Battery model'; Entity = 'sensor.ecco_config_battery_capacity' },
    @{ Label = 'Round-trip efficiency'; Entity = 'sensor.ecco_config_round_trip_efficiency' },
    @{ Label = 'TOU power ceiling'; Entity = 'sensor.ecco_config_inverter_tou_power_ceiling' },
    @{ Label = 'Grid charge op limit'; Entity = 'sensor.ecco_config_grid_charge_operating_limit' },
    @{ Label = 'Effective charge limit'; Entity = 'sensor.ecco_config_maximum_grid_charge_power' }
)

$rows = foreach ($item in $wanted) {
    $state = $stateIndex[$item.Entity]
    if ($null -eq $state) {
        [pscustomobject]@{
            Item = $item.Label
            State = 'MISSING'
            Unit = ''
        }
        continue
    }

    $unit = ''
    if ($null -ne $state.attributes -and $null -ne $state.attributes.unit_of_measurement) {
        $unit = [string]$state.attributes.unit_of_measurement
    }

    [pscustomobject]@{
        Item = $item.Label
        State = [string]$state.state
        Unit = $unit
    }
}

Write-Host 'ECCO SNAPSHOT'
Write-Host '-------------'
$rows | Format-Table -AutoSize

$missing = @($rows | Where-Object { $_.State -eq 'MISSING' })
if ($missing.Count -gt 0) {
    $candidates = @(
        $states |
            Where-Object { [string]$_.entity_id -match '(?i)ecco|clock_dongle|deye' } |
            Select-Object -ExpandProperty entity_id |
            Sort-Object -Unique
    )

    if ($candidates.Count -gt 0) {
        Write-Host ''
        Write-Host 'Relevant live entity IDs (for resolving any MISSING rows)'
        Write-Host '---------------------------------------------------------'
        $candidates | ForEach-Object { Write-Host $_ }
    }
}
