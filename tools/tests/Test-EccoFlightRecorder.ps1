<#
    Offline/static tests for tools/EccoFlightRecorderHelpers.psm1 - the
    pure computation helpers added 2026-09-27 to
    tools/ecco-flight-recorder.ps1 (V*I sanity check, derived house load,
    feasibility classification, commanded-ceiling dwell tracker).

    Same philosophy as tools/tests/Test-EccoDeploy.ps1: no network access,
    no SSH, no live Home Assistant. Every function under test is pure -
    given the same inputs it always returns the same output - so this
    proves the computation logic without needing hardware.

    Windows PowerShell 5.1 compatible. No external module dependencies
    (no Pester) - this is a small self-contained pass/fail runner.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$toolsDir = Join-Path $repoRoot 'tools'

Import-Module (Join-Path $toolsDir 'EccoFlightRecorderHelpers.psm1') -Force

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

function Assert-AlmostEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowNull()]$Actual,
        [Parameter(Mandatory = $true)][double]$Expected,
        [double]$Tolerance = 0.001
    )
    $ok = ($null -ne $Actual) -and ([math]::Abs([double]$Actual - $Expected) -le $Tolerance)
    Assert-True -Name $Name -Condition $ok -Detail "expected $Expected, got $Actual"
}

function Assert-Null {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()]$Actual
    )
    Assert-True -Name $Name -Condition ($null -eq $Actual) -Detail "expected `$null, got $Actual"
}

Write-Host 'ECCO flight recorder helpers - offline tests'
Write-Host ''

# ---------------------------------------------------------------------
# 1. ConvertTo-EccoNullableFloat
# ---------------------------------------------------------------------
Write-Host '[1] ConvertTo-EccoNullableFloat'
Assert-AlmostEqual -Name 'parses a plain integer' -Actual (ConvertTo-EccoNullableFloat '1000') -Expected 1000.0
Assert-AlmostEqual -Name 'parses a negative decimal' -Actual (ConvertTo-EccoNullableFloat '-51.23') -Expected -51.23
Assert-AlmostEqual -Name 'tolerates surrounding whitespace' -Actual (ConvertTo-EccoNullableFloat '  42.5 ') -Expected 42.5
foreach ($marker in @('MISSING', 'unknown', 'unavailable', 'ssh_error', 'none', 'nan', '', 'Unavailable', 'NaN')) {
    Assert-Null -Name "'$marker' -> `$null" -Actual (ConvertTo-EccoNullableFloat $marker)
}
Assert-Null -Name 'non-numeric garbage -> $null' -Actual (ConvertTo-EccoNullableFloat 'garbled#text')

# ---------------------------------------------------------------------
# 2. Get-EccoBatteryViComputed
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[2] Get-EccoBatteryViComputed (same-source V*I sanity check)'
Assert-AlmostEqual -Name 'positive volts * positive amps' `
    -Actual (Get-EccoBatteryViComputed -VoltageV 51.2 -CurrentA 23.4) -Expected 1198.08 -Tolerance 0.01
Assert-AlmostEqual -Name 'sign is preserved, not corrected (negative current)' `
    -Actual (Get-EccoBatteryViComputed -VoltageV 51.2 -CurrentA -10.0) -Expected -512.0 -Tolerance 0.01
Assert-Null -Name 'missing voltage -> $null (never a false 0)' -Actual (Get-EccoBatteryViComputed -VoltageV $null -CurrentA 10.0)
Assert-Null -Name 'missing current -> $null (never a false 0)' -Actual (Get-EccoBatteryViComputed -VoltageV 51.2 -CurrentA $null)
Assert-Null -Name 'both missing -> $null' -Actual (Get-EccoBatteryViComputed -VoltageV $null -CurrentA $null)

# ---------------------------------------------------------------------
# 3. Get-EccoDerivedHouseLoad
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[3] Get-EccoDerivedHouseLoad (max(0, inverter_output + grid_ct))'
Assert-AlmostEqual -Name 'ordinary import case sums directly' `
    -Actual (Get-EccoDerivedHouseLoad -InverterOutputW 1200 -GridCtW 2849) -Expected 4049.0
Assert-AlmostEqual -Name 'net-export case clamps to 0, not negative' `
    -Actual (Get-EccoDerivedHouseLoad -InverterOutputW 0 -GridCtW -1800) -Expected 0.0
Assert-Null -Name 'missing inverter output -> $null' -Actual (Get-EccoDerivedHouseLoad -InverterOutputW $null -GridCtW 100)
Assert-Null -Name 'missing grid CT -> $null' -Actual (Get-EccoDerivedHouseLoad -InverterOutputW 100 -GridCtW $null)

# ---------------------------------------------------------------------
# 4. Get-EccoFeasibilityClassification
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[4] Get-EccoFeasibilityClassification'
Assert-True -Name 'TARGET INFEASIBLE LOW text -> INFEASIBLE_LOW' `
    -Condition ((Get-EccoFeasibilityClassification 'TARGET INFEASIBLE LOW - natural PV surplus already exceeds the target by ~1326W') -eq 'INFEASIBLE_LOW')
Assert-True -Name 'TARGET INFEASIBLE HIGH text -> INFEASIBLE_HIGH' `
    -Condition ((Get-EccoFeasibilityClassification 'TARGET INFEASIBLE HIGH - battery ceiling 3000W (required discharge ~3383W exceeds the 3000W controller ceiling)') -eq 'INFEASIBLE_HIGH')
foreach ($state in @('TRACKING', 'SETTLING', 'SATURATED LOW', 'SATURATED HIGH', 'IDLE', 'WAITING FOR FRESH GRID', 'NO RESPONSE')) {
    Assert-True -Name "'$state' -> NOT_FLAGGED_INFEASIBLE" `
        -Condition ((Get-EccoFeasibilityClassification $state) -eq 'NOT_FLAGGED_INFEASIBLE')
}
foreach ($marker in @('MISSING', 'ssh_error', 'unavailable', 'unknown', '', $null)) {
    Assert-True -Name "'$marker' -> UNKNOWN" `
        -Condition ((Get-EccoFeasibilityClassification $marker) -eq 'UNKNOWN')
}

# ---------------------------------------------------------------------
# 5. Update-EccoCeilingDwell
# ---------------------------------------------------------------------
Write-Host ''
Write-Host '[5] Update-EccoCeilingDwell (commanded-ceiling dwell tracker)'
$t0 = Get-Date '2026-09-28T00:00:00'
$r0 = Update-EccoCeilingDwell -State $null -CurrentRawValue 'unknown' -NowTime $t0
Assert-True -Name 'first-ever sample is treated as a change' -Condition ($r0.Changed -eq $true)
Assert-AlmostEqual -Name 'first-ever sample has zero dwell' -Actual $r0.DwellSeconds -Expected 0.0

$t1 = $t0.AddSeconds(15)
$r1 = Update-EccoCeilingDwell -State $r0.State -CurrentRawValue '1000.0' -NowTime $t1
Assert-True -Name 'ceiling changing from unknown to 1000.0 is a change' -Condition ($r1.Changed -eq $true)
Assert-AlmostEqual -Name 'dwell resets to zero on change' -Actual $r1.DwellSeconds -Expected 0.0

$t2 = $t1.AddSeconds(45)
$r2 = Update-EccoCeilingDwell -State $r1.State -CurrentRawValue '1000.0' -NowTime $t2
Assert-True -Name 'same value again is NOT a change' -Condition ($r2.Changed -eq $false)
Assert-AlmostEqual -Name 'dwell accumulates elapsed seconds while held' -Actual $r2.DwellSeconds -Expected 45.0 -Tolerance 0.01

$t3 = $t2.AddSeconds(5)
$r3 = Update-EccoCeilingDwell -State $r2.State -CurrentRawValue '1400.0' -NowTime $t3
Assert-True -Name 'a genuine ceiling step is a change' -Condition ($r3.Changed -eq $true)
Assert-AlmostEqual -Name 'dwell resets again on the step' -Actual $r3.DwellSeconds -Expected 0.0
Assert-True -Name 'LastChangeTime advances to the step time' -Condition ($r3.LastChangeTime -eq $t3)

Write-Host ''
Write-Host "Results: $script:pass passed, $script:fail failed"
if ($script:fail -gt 0) {
    exit 1
}
exit 0
