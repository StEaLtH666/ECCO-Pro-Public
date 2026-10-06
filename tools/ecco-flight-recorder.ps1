<#
Read-only Home Assistant state sampler for observing SmartDeye's own export
automation. Every ~2 seconds it performs a single GET against the Home
Assistant Supervisor API (states endpoint) and appends one timestamped row
to a CSV file. It never writes to Home Assistant, never calls a Home
Assistant service, and never talks to the inverter directly.

Uses the same read-only SSH + Supervisor-token mechanism as
tools/ecco-snapshot.ps1 (see that script for the original single-shot
version of this pattern) - no new HA REST credentials or config are
introduced here.

Usage (foreground, same terminal):
  pwsh tools/ecco-flight-recorder.ps1
  pwsh tools/ecco-flight-recorder.ps1 -SshHost ecco-ha -IntervalSeconds 2

Stop with Ctrl+C. The CSV is flushed after every row, so interrupting the
script loses at most the in-flight sample.

For a recording that must survive the launching shell exiting (e.g. a live
proof spanning multiple separate tool invocations), use the detached
Start/Stop wrapper instead of running this file directly:
  pwsh tools/ecco-flight-recorder-start.ps1
  pwsh tools/ecco-flight-recorder-stop.ps1
See those scripts for the PID-file/process-ownership mechanism this relies
on. -CsvPath below exists so the start wrapper can pin the exact output path
it records in its lock file - pass -OutputDirectory instead for normal use.

--- READ-ONLY GUARANTEE (structural, not just a comment) ---------------
The only network operation this script performs is $remoteScript below: one
hard-coded `curl -fsS ... http://supervisor/core/api/states` GET, executed
identically every sample. There is no second remote command anywhere in
this file, no `-X POST`/`-X PUT`/`-X PATCH` flag, no `/services/` path, no
`service:` YAML call, and nothing that ARMs/STARTs/ENDs a Dump-to-Grid or
Free Power lease or writes any Home Assistant entity or inverter register.
Every value below is read straight out of the JSON this one GET returns.

--- 2026-09-27 additions (docs/DUMP_TO_GRID_CEILING_RESIDUAL_INVESTIGATION.md) ---
Added columns to capture the evidence that investigation's "Recommended
evidence-collection template" (section 14) asked for, ahead of a later
live characterization of the commanded-ceiling vs measured-battery-power
residual: battery current (register 191, previously omitted - it IS
exposed to HA today, see the note below), a same-source V*I sanity
computation, the dynamic Dump-to-Grid commanded battery ceiling and
controller state, inverter AC output power, a derived "trusted" house load
(same formula as the V1.2 target-feasibility check), a feasibility
classification, and a dwell-time tracker for the commanded ceiling. All
pure computation lives in tools/EccoFlightRecorderHelpers.psm1 so it can be
tested offline (tools/tests/Test-EccoFlightRecorder.ps1) - this script only
adds the new entity reads and wires the helpers into the existing loop.
Nothing about the read-only GET above changed.
#>

[CmdletBinding()]
param(
    [string]$SshHost = 'ecco-ha',
    [double]$IntervalSeconds = 2.0,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'flight-recordings'),
    [int]$HeartbeatEverySamples = 5,
    [string]$CsvPath = ''
)

$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'EccoFlightRecorderHelpers.psm1') -Force

# --- entity list ------------------------------------------------------
# Column name -> Home Assistant entity_id. Canonical (sensor.ecco_*) aliases
# are used where the repo defines one (see home-assistant/packages/
# ecco_canonical_telemetry.yaml); otherwise the raw ESPHome-device entity is
# used directly.
#
# Entity IDs marked "NOT YET LIVE-VERIFIED" below are derived from the
# firmware's `name:` field using the exact same HA object_id slugging
# convention already confirmed live for every neighbouring entity in this
# list (e.g. "ECCO Battery Voltage" -> ecco_battery_voltage, matching
# battery_voltage_v just below) - they have not themselves been individually
# checked against Developer Tools > States. If a slug is wrong the column
# simply reads MISSING (harmless, exactly like the existing reg244/raw-flag
# columns' own such caveats).
$wanted = [ordered]@{
    # NOTE: HA derives entity_id from the ESPHome entity's friendly `name:`,
    # not its internal `id:`. Register 244's friendly name is "ECCO Load
    # Limit Exp Ess Non-Ess" (not "ECCO Load Limit") - verify this slug
    # against Developer Tools > States before relying on it tonight; if it
    # doesn't match, this column will simply read MISSING (harmless).
    # CORRECTED 2026-09-22 post-OTA live verification: Home Assistant has no
    # "text_sensor" domain - ESPHome text_sensor: platform entities surface
    # under the plain "sensor." domain in HA. Confirmed live for this device
    # (zero text_sensor.* entities exist for it; sensor.*_load_limit_... and
    # sensor.*_inverter_system_state both resolve).
    reg244_load_export_mode = 'sensor.ecco_clock_dongle_ecco_load_limit_exp_ess_non_ess'
    reg245_export_limit_w   = 'sensor.ecco_clock_dongle_ecco_export_limit'
    reg248_tou_enabled      = 'binary_sensor.ecco_clock_dongle_ecco_time_of_use_enabled'

    # Dump-to-Grid V1 (2026-09-26) - entity IDs confirmed live against
    # Developer Tools > States after the Stage 0-2 OTA. Read-only: these are
    # the same status entities the dashboard card and the Stage 0-3 proof
    # checklists already use.
    dump_active              = 'binary_sensor.ecco_clock_dongle_dump_to_grid_active'
    dump_snapshot_valid      = 'binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid'
    dump_operation_in_progress = 'binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress'
    dump_status               = 'sensor.ecco_clock_dongle_dump_to_grid_status'
    dump_last_end_reason      = 'sensor.ecco_clock_dongle_dump_to_grid_last_end_reason'
    # No dedicated runaway-sample-counter entity is exposed to HA (it is
    # RAM-only firmware state) - a POWER RUNAWAY event surfaces here via the
    # literal text in dump_status / dump_last_end_reason, cross-referenced
    # against the battery_power_w column below.
    dump_recovery_state       = 'sensor.ecco_clock_dongle_dump_to_grid_recovery_state'

    # 2026-09-27 additions - residual-evidence characterization. Both derived
    # from firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
    # `name: "Dump to Grid Commanded Battery Ceiling"` /
    # `name: "Dump to Grid Controller State"` template sensors. NOT YET
    # LIVE-VERIFIED (see note above) - same convention as dump_status/
    # dump_last_end_reason/dump_recovery_state directly above, which are.
    # dump_controller_state is also the ONLY place "TARGET INFEASIBLE
    # LOW"/"TARGET INFEASIBLE HIGH" (Dump-to-Grid V1.2 target feasibility,
    # docs/DUMP_TO_GRID_V1.md) ever appears - see feasibility_classification
    # below, derived from this same raw column.
    dump_commanded_ceiling_w = 'sensor.ecco_clock_dongle_dump_to_grid_commanded_battery_ceiling'
    dump_controller_state    = 'sensor.ecco_clock_dongle_dump_to_grid_controller_state'

    # Freshness/health of the two read paths Dump-to-Grid (and Free Power)
    # depend on - both are HA-facing switches/sensors, not internal state.
    telemetry_online            = 'binary_sensor.ecco_clock_dongle_telemetry_online'
    configuration_online        = 'binary_sensor.ecco_clock_dongle_configuration_online'
    live_inverter_telemetry_on  = 'switch.ecco_clock_dongle_live_inverter_telemetry'
    config_polling_on           = 'switch.ecco_clock_dongle_read_only_configuration_polling'
    last_telemetry_update       = 'sensor.ecco_clock_dongle_last_telemetry_update'
    last_configuration_update   = 'sensor.ecco_clock_dongle_last_configuration_update'

    tou1_power_w = 'sensor.ecco_clock_dongle_ecco_timezone1_power'
    tou2_power_w = 'sensor.ecco_clock_dongle_ecco_timezone2_power'
    tou3_power_w = 'sensor.ecco_clock_dongle_ecco_timezone3_power'
    tou4_power_w = 'sensor.ecco_clock_dongle_ecco_timezone4_power'
    tou5_power_w = 'sensor.ecco_clock_dongle_ecco_timezone5_power'
    tou6_power_w = 'sensor.ecco_clock_dongle_ecco_timezone6_power'

    tou1_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone1_soc'
    tou2_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone2_soc'
    tou3_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone3_soc'
    tou4_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone4_soc'
    tou5_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone5_soc'
    tou6_soc_pct = 'sensor.ecco_clock_dongle_ecco_timezone6_soc'

    tou1_charge = 'sensor.ecco_clock_dongle_ecco_timezone1_charge'
    tou2_charge = 'sensor.ecco_clock_dongle_ecco_timezone2_charge'
    tou3_charge = 'sensor.ecco_clock_dongle_ecco_timezone3_charge'
    tou4_charge = 'sensor.ecco_clock_dongle_ecco_timezone4_charge'
    tou5_charge = 'sensor.ecco_clock_dongle_ecco_timezone5_charge'
    tou6_charge = 'sensor.ecco_clock_dongle_ecco_timezone6_charge'

    tou1_mode = 'sensor.ecco_clock_dongle_ecco_timezone1_mode'
    tou2_mode = 'sensor.ecco_clock_dongle_ecco_timezone2_mode'
    tou3_mode = 'sensor.ecco_clock_dongle_ecco_timezone3_mode'
    tou4_mode = 'sensor.ecco_clock_dongle_ecco_timezone4_mode'
    tou5_mode = 'sensor.ecco_clock_dongle_ecco_timezone5_mode'
    tou6_mode = 'sensor.ecco_clock_dongle_ecco_timezone6_mode'

    # New diagnostic raw flag words (registers 274-279) - requires the
    # firmware change in firmware/ecco_clock_dongle_stage3_4_free_power.yaml
    # to be deployed first. Until then these columns will read MISSING,
    # which this script handles gracefully.
    tou1_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone1_raw_flags'
    tou2_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone2_raw_flags'
    tou3_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone3_raw_flags'
    tou4_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone4_raw_flags'
    tou5_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone5_raw_flags'
    tou6_raw_flags = 'sensor.ecco_clock_dongle_ecco_timezone6_raw_flags'

    battery_power_w   = 'sensor.ecco_clock_dongle_ecco_battery_output_power'
    battery_soc_pct   = 'sensor.ecco_battery_soc'
    battery_voltage_v = 'sensor.ecco_clock_dongle_ecco_battery_voltage'
    # 2026-09-27 addition: register 191, raw signed amps. NOT YET
    # LIVE-VERIFIED entity id (see note above) - was previously omitted from
    # this recorder on the (stale) assumption that it had no HA entity at
    # all; firmware/ecco_clock_dongle_stage3_4_free_power.yaml actually
    # defines `name: "ECCO Battery Output Current"` as a live template
    # sensor. Its sign convention relative to battery_power_w's documented
    # +discharge/-charge is NOT independently confirmed by this repository -
    # see battery_power_vi_computed_w below, and
    # docs/DUMP_TO_GRID_CEILING_RESIDUAL_INVESTIGATION.md section 2.
    battery_current_a = 'sensor.ecco_clock_dongle_ecco_battery_output_current'

    # grid_power_w is the CT-clamp path (ecco_canonical_telemetry.yaml aliases
    # sensor.ecco_grid_power from sensor.*_ecco_grid_power_ct_clamp, register
    # 172) - this IS the "trusted grid CT" signal the Dump-to-Grid V1.2
    # target-feasibility check and house_load_derived_w below both use, not
    # the inverter's separate native grid-power register.
    grid_power_w = 'sensor.ecco_grid_power'
    # house_power_w (sensor.ecco_house_power) aliases the inverter's OWN
    # native house-load register (ECCO Load Power, register 178) - per
    # docs/DUMP_TO_GRID_V1.md "Target feasibility", this reads 0W while a
    # Dump/Free Power lease exports and is NOT trustworthy in that state.
    # Kept for continuity/comparison; house_load_derived_w below is the
    # trustworthy derived quantity to actually use.
    house_power_w = 'sensor.ecco_house_power'
    pv_power_w    = 'sensor.ecco_pv_power'
    # 2026-09-27 addition: register 175, inverter AC output power. NOT YET
    # LIVE-VERIFIED entity id (see note above). Feeds house_load_derived_w
    # below together with the trusted grid_power_w CT-clamp column.
    inverter_output_power_w = 'sensor.ecco_clock_dongle_ecco_inverter_output_power'

    inverter_state = 'sensor.ecco_clock_dongle_ecco_inverter_system_state'
}

# --- derived/computed column names (NOT Home Assistant entities) ------
# These are never read from HA directly - they are calculated in the main
# loop below from columns already listed in $wanted, purely locally.
$derivedColumns = @(
    'battery_power_vi_computed_w',
    'house_load_derived_w',
    'feasibility_classification',
    'dump_ceiling_last_change_iso',
    'dump_ceiling_dwell_s'
)

$columns = @('timestamp_iso', 'elapsed_s', 'sample', 'ssh_status') + @($wanted.Keys) + $derivedColumns

# --- remote read (identical GET-only pattern to tools/ecco-snapshot.ps1) --
$remoteScript = @'
if [ -z "$SUPERVISOR_TOKEN" ]; then
  echo __ECCO_NO_SUPERVISOR_TOKEN__
  exit 42
fi

curl -fsS \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  http://supervisor/core/api/states
'@
$remoteText = $remoteScript.Replace("`r", '')
$remoteBytes = [System.Text.Encoding]::UTF8.GetBytes($remoteText)
$remoteBase64 = [Convert]::ToBase64String($remoteBytes)
$remoteCommand = "printf %s $remoteBase64 | base64 -d | sh"

function Get-EccoStateIndex {
    # Returns a hashtable of entity_id -> state object, or $null on any
    # failure (SSH unreachable, non-zero exit, bad JSON). Read-only: a
    # single GET against the Supervisor's proxied HA Core API.
    $response = @(& ssh -o BatchMode=yes -o ConnectTimeout=5 $SshHost $remoteCommand 2>&1)
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        return $null
    }

    $json = $response -join "`n"
    try {
        $decoded = $json | ConvertFrom-Json
    } catch {
        return $null
    }

    if ($null -ne $decoded.PSObject.Properties['data']) {
        $states = @($decoded.data)
    } else {
        $states = @($decoded)
    }
    $states = @($states | Where-Object {
        $null -ne $_ -and $null -ne $_.PSObject.Properties['entity_id']
    })
    if ($states.Count -eq 0) {
        return $null
    }

    $index = @{}
    foreach ($state in $states) {
        $index[[string]$state.entity_id] = $state
    }
    return $index
}

function ConvertTo-CsvField {
    param([string]$Value)
    if ($null -eq $Value) { $Value = '' }
    if ($Value -match '[",\r\n]') {
        return '"' + ($Value -replace '"', '""') + '"'
    }
    return $Value
}

# --- output file --------------------------------------------------------
# $CsvPath (the -CsvPath parameter) doubles as the resolved path used below -
# PowerShell variable names are case-insensitive, so assigning into it here
# is deliberate, not a second variable shadowing the parameter.
if ([string]::IsNullOrWhiteSpace($CsvPath)) {
    if (-not (Test-Path -LiteralPath $OutputDirectory)) {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $CsvPath = Join-Path $OutputDirectory "ecco-flight-$stamp.csv"
} else {
    $parentDir = Split-Path -Parent $CsvPath
    if ($parentDir -and -not (Test-Path -LiteralPath $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }
}
$csvPath = $CsvPath

Write-Host "ECCO flight recorder (READ-ONLY) starting."
Write-Host "  SSH host        : $SshHost"
Write-Host "  Sample interval : ~${IntervalSeconds}s"
Write-Host "  Output CSV      : $csvPath"
Write-Host "  Stop with Ctrl+C."
Write-Host ''

$writer = New-Object System.IO.StreamWriter($csvPath, $false, [System.Text.Encoding]::UTF8)
$writer.WriteLine(($columns -join ','))
$writer.Flush()

$startTime = Get-Date
$sample = 0
# Persists across loop iterations: the commanded-ceiling dwell tracker's
# own state (see Update-EccoCeilingDwell in EccoFlightRecorderHelpers.psm1).
# $null until the first successful sample.
$ceilingDwellState = $null

try {
    while ($true) {
        $iterStart = Get-Date
        $sample++

        $stateIndex = Get-EccoStateIndex
        $sshStatus = if ($null -eq $stateIndex) { 'error' } else { 'ok' }

        # Named (not just positional) so the derived columns below can look
        # up specific raw readings by name, while still preserving $wanted's
        # declared order for the CSV row.
        $rawByColumn = [ordered]@{}
        foreach ($key in $wanted.Keys) {
            if ($null -eq $stateIndex) {
                $rawByColumn[$key] = 'ssh_error'
                continue
            }
            $state = $stateIndex[$wanted[$key]]
            if ($null -eq $state) {
                $rawByColumn[$key] = 'MISSING'
            } else {
                # HA already reports 'unavailable'/'unknown' as the state
                # string itself when a sensor has no reading - pass through.
                $rawByColumn[$key] = [string]$state.state
            }
        }
        $values = @($rawByColumn.Values)

        # --- derived columns (pure computation, no new HA reads) ---------
        $viComputed = Get-EccoBatteryViComputed `
            -VoltageV (ConvertTo-EccoNullableFloat $rawByColumn['battery_voltage_v']) `
            -CurrentA (ConvertTo-EccoNullableFloat $rawByColumn['battery_current_a'])

        $houseLoadDerived = Get-EccoDerivedHouseLoad `
            -InverterOutputW (ConvertTo-EccoNullableFloat $rawByColumn['inverter_output_power_w']) `
            -GridCtW (ConvertTo-EccoNullableFloat $rawByColumn['grid_power_w'])

        $feasibility = Get-EccoFeasibilityClassification -ControllerState $rawByColumn['dump_controller_state']

        # Dwell tracking is only fed on a successful SSH read - a transient
        # ssh_error blip must never be mistaken for a real ceiling change.
        # On a failed read, dwell keeps accumulating from the last known
        # change time instead of resetting.
        if ($sshStatus -eq 'ok') {
            $dwellResult = Update-EccoCeilingDwell `
                -State $ceilingDwellState `
                -CurrentRawValue $rawByColumn['dump_commanded_ceiling_w'] `
                -NowTime $iterStart
            $ceilingDwellState = $dwellResult.State
            $dwellSeconds = $dwellResult.DwellSeconds
            $lastChangeIso = $dwellResult.LastChangeTime.ToString('yyyy-MM-ddTHH:mm:ss.fffK')
        } elseif ($null -ne $ceilingDwellState) {
            $dwellSeconds = ($iterStart - $ceilingDwellState.LastChangeTime).TotalSeconds
            $lastChangeIso = $ceilingDwellState.LastChangeTime.ToString('yyyy-MM-ddTHH:mm:ss.fffK')
        } else {
            $dwellSeconds = $null
            $lastChangeIso = ''
        }

        $derivedValues = @(
            $(if ($null -ne $viComputed) { [math]::Round($viComputed, 2) } else { '' }),
            $(if ($null -ne $houseLoadDerived) { [math]::Round($houseLoadDerived, 1) } else { '' }),
            $feasibility,
            $lastChangeIso,
            $(if ($null -ne $dwellSeconds) { [math]::Round($dwellSeconds, 1) } else { '' })
        )

        $elapsed = [math]::Round((New-TimeSpan -Start $startTime -End $iterStart).TotalSeconds, 3)
        $row = @(
            $iterStart.ToString('yyyy-MM-ddTHH:mm:ss.fffK'),
            $elapsed,
            $sample,
            $sshStatus
        ) + $values + $derivedValues

        $writer.WriteLine((($row | ForEach-Object { ConvertTo-CsvField ([string]$_) }) -join ','))
        $writer.Flush()

        if (($sample % $HeartbeatEverySamples) -eq 0) {
            $peek = if ($null -ne $stateIndex) {
                $bp = $stateIndex[$wanted['battery_power_w']]
                $bs = $stateIndex[$wanted['battery_soc_pct']]
                $gp = $stateIndex[$wanted['grid_power_w']]
                $lp = $stateIndex[$wanted['house_power_w']]
                $pv = $stateIndex[$wanted['pv_power_w']]
                $mode = $stateIndex[$wanted['reg244_load_export_mode']]
                $ceil = $rawByColumn['dump_commanded_ceiling_w']
                $cstate = $rawByColumn['dump_controller_state']
                "batt=$(if($bp){$bp.state}else{'?'})W soc=$(if($bs){$bs.state}else{'?'})% grid=$(if($gp){$gp.state}else{'?'})W load=$(if($lp){$lp.state}else{'?'})W pv=$(if($pv){$pv.state}else{'?'})W mode=$(if($mode){$mode.state}else{'?'}) ceiling=${ceil}W state=$cstate dwell=$($derivedValues[4])s"
            } else {
                'SSH READ FAILED'
            }
            Write-Host "[$($iterStart.ToString('HH:mm:ss'))] #$sample $peek"
        }

        $elapsedThisSample = ((Get-Date) - $iterStart).TotalSeconds
        $sleepFor = $IntervalSeconds - $elapsedThisSample
        if ($sleepFor -gt 0) {
            Start-Sleep -Seconds $sleepFor
        }
    }
} finally {
    $writer.Flush()
    $writer.Close()
    Write-Host ''
    Write-Host "Flight recorder stopped. $sample sample(s) written to $csvPath"
}
