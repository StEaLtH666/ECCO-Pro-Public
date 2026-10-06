<#
Pure, offline-testable helper functions for tools/ecco-flight-recorder.ps1.

Split out of the recorder script itself so they can be exercised by
tools/tests/Test-EccoFlightRecorder.ps1 without any SSH/Home Assistant
dependency - same "module + offline test" pattern already used by
EccoDeploy.psm1 / Test-EccoDeploy.ps1.

Every function here is a pure computation over strings/numbers/hashtables
already read from Home Assistant elsewhere. Nothing in this file performs
network I/O, and nothing here can write to Home Assistant or the inverter -
there is no Invoke-RestMethod/Invoke-WebRequest/ssh call anywhere in this
module.
#>

Set-StrictMode -Version Latest

# Home Assistant/recorder failure markers that must NOT be parsed as 0 or
# otherwise silently coerced into a number - each means "no reading", not
# "zero".
$script:NonNumericMarkers = @(
    'missing', 'unknown', 'unavailable', 'ssh_error', 'none', 'nan', ''
)

function ConvertTo-EccoNullableFloat {
    <#
    Parses a raw Home Assistant state string into a [double], or $null when
    the value is missing/unavailable/not-a-number. Never throws - a value
    this function cannot parse is treated as "no reading", exactly like the
    CSV's own existing MISSING/ssh_error convention for raw columns.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [AllowEmptyString()]
        [string]$Value
    )
    if ($null -eq $Value) { return $null }
    $trimmed = $Value.Trim()
    if ($script:NonNumericMarkers -contains $trimmed.ToLowerInvariant()) {
        return $null
    }
    $parsed = 0.0
    if ([double]::TryParse(
            $trimmed,
            [System.Globalization.NumberStyles]::Float,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function Get-EccoBatteryViComputed {
    <#
    Battery power computed as voltage * current, from the SAME telemetry
    poll as register 190 (battery_power_w) - see the "SAME-SOURCE, NOT
    INDEPENDENT" note in ecco-flight-recorder.ps1. Sign convention: this
    multiplies the two raw signed readings as published by HA with no sign
    correction of any kind; whether register 191's sign matches register
    190's documented +discharge/-charge convention is NOT independently
    confirmed by this repository (see docs/DUMP_TO_GRID_CEILING_RESIDUAL_INVESTIGATION.md
    section 2) - this column exists so that assumption can be checked
    against the raw battery_power_w column later, not to assert it is
    correct.
    #>
    param(
        [AllowNull()] $VoltageV,
        [AllowNull()] $CurrentA
    )
    if ($null -eq $VoltageV -or $null -eq $CurrentA) { return $null }
    return ([double]$VoltageV) * ([double]$CurrentA)
}

function Get-EccoDerivedHouseLoad {
    <#
    "Trusted" house load estimate, matching the exact formula the Dump-to-
    Grid V1.2 target-feasibility check already uses (docs/DUMP_TO_GRID_V1.md
    "Target feasibility"): max(0, inverter_output_power + grid_ct_power).
    Deliberately NOT the inverter's own native house-load register (ECCO
    Load Power / sensor.*_ecco_load_power, aliased by the canonical
    telemetry adapter as sensor.ecco_house_power) - that register is
    documented to read 0W while exporting and is not trustworthy during a
    lease.
    #>
    param(
        [AllowNull()] $InverterOutputW,
        [AllowNull()] $GridCtW
    )
    if ($null -eq $InverterOutputW -or $null -eq $GridCtW) { return $null }
    $sum = ([double]$InverterOutputW) + ([double]$GridCtW)
    if ($sum -lt 0) { return 0.0 }
    return $sum
}

function Get-EccoFeasibilityClassification {
    <#
    Classifies the Dump to Grid Controller State string into one of:
      INFEASIBLE_LOW  - "TARGET INFEASIBLE LOW..." (PV surplus alone exceeds target)
      INFEASIBLE_HIGH - "TARGET INFEASIBLE HIGH..." (required discharge exceeds the controller ceiling)
      NOT_FLAGGED_INFEASIBLE - any other real controller state (TRACKING, SETTLING,
        SATURATED LOW/HIGH, WAITING FOR FRESH GRID, NO RESPONSE..., IDLE, etc.)
      UNKNOWN - no reading (missing/unavailable/ssh error)

    Deliberately named NOT_FLAGGED_INFEASIBLE rather than "FEASIBLE" for the
    third bucket - per docs/DUMP_TO_GRID_V1.md "Target feasibility", the
    feasibility check does not even run during WAITING FOR FRESH GRID/NO
    RESPONSE/etc., so "not flagged infeasible" is the honest claim; it is
    not proof the target is actually achievable in those states.
    #>
    param(
        [AllowNull()]
        [AllowEmptyString()]
        [string]$ControllerState
    )
    if ([string]::IsNullOrWhiteSpace($ControllerState)) { return 'UNKNOWN' }
    $normalized = $ControllerState.Trim().ToLowerInvariant()
    if ($script:NonNumericMarkers -contains $normalized) { return 'UNKNOWN' }
    if ($ControllerState -match '^\s*TARGET INFEASIBLE LOW') { return 'INFEASIBLE_LOW' }
    if ($ControllerState -match '^\s*TARGET INFEASIBLE HIGH') { return 'INFEASIBLE_HIGH' }
    return 'NOT_FLAGGED_INFEASIBLE'
}

function Update-EccoCeilingDwell {
    <#
    Pure dwell-time tracker for the commanded battery ceiling. Call once per
    sample with the PREVIOUS state (or $null on the very first sample) and
    the raw ceiling reading for THIS sample; returns a hashtable with the
    NEW state to keep for next time, plus this sample's dwell seconds and
    whether this sample is itself the change.

    Deliberately driven entirely off the raw string read from Home
    Assistant (e.g. "1000.0" or "unknown"/"nan" while no lease is active) -
    no firmware change and no new entity is required. The caller is
    responsible for NOT calling this on a transient SSH read failure (pass
    the previous State through unchanged instead), so a temporary ssh_error
    blip is never mistaken for a real ceiling change - see
    ecco-flight-recorder.ps1's main loop.
    #>
    param(
        [AllowNull()] [hashtable]$State,
        [Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$CurrentRawValue,
        [Parameter(Mandatory = $true)] [datetime]$NowTime
    )

    if ($null -eq $State -or $State.LastRawValue -ne $CurrentRawValue) {
        $newState = @{ LastRawValue = $CurrentRawValue; LastChangeTime = $NowTime }
        return @{
            State          = $newState
            DwellSeconds   = 0.0
            Changed        = $true
            LastChangeTime = $NowTime
        }
    }

    $dwell = ($NowTime - $State.LastChangeTime).TotalSeconds
    return @{
        State          = $State
        DwellSeconds   = $dwell
        Changed         = $false
        LastChangeTime = $State.LastChangeTime
    }
}

Export-ModuleMember -Function `
    ConvertTo-EccoNullableFloat, `
    Get-EccoBatteryViComputed, `
    Get-EccoDerivedHouseLoad, `
    Get-EccoFeasibilityClassification, `
    Update-EccoCeilingDwell
