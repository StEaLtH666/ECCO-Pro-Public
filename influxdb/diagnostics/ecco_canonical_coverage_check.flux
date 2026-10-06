// ECCO Pro - canonical telemetry coverage check (READ-ONLY)
//
// Manual/ad-hoc diagnostic. Paste into the InfluxDB Data Explorer /
// Script Editor and run by hand - this is deliberately NOT an
// `option task`, so it will never be scheduled or run automatically,
// and it contains no `to()` call, so it cannot write anything.
//
// Proves, for each of the four canonical telemetry entities:
//   - whether any canonical/legacy points exist at all in the lookback window
//   - the earliest and latest timestamp seen for each series
//   - whether the two series' time ranges actually overlap
//
// Adjust `lookback` if 30 days is not enough to find the earliest
// canonical point (canonical telemetry is new - if it was only enabled
// recently, 30 days is generous; widen it if this returns no rows for a
// field that should have data).
//
// overlap_appears_present is a real interval-overlap test, not merely
// "both series have some data somewhere in the lookback window":
// [earliest_legacy, latest_legacy] and [earliest_canonical,
// latest_canonical] overlap exactly when
// earliest_canonical <= latest_legacy AND earliest_legacy <= latest_canonical.
// An earlier version of this script used `hasCanonical and hasLegacy`,
// which only proved both series exist somewhere in the window, not that
// their time ranges actually intersect - a canonical series that only
// existed in the last hour and a legacy series that only existed a
// month ago would both be "present" without ever overlapping in time.
//
// Expected interpretation:
//   - has_canonical_data = false for a field: canonical adapter sensor
//     exists in Home Assistant but no point has landed in InfluxDB yet
//     within the lookback window. Check the HA entity's state and the
//     InfluxDB export config (sensor.ecco_* glob) before assuming
//     something is broken.
//   - overlap_appears_present = true: the two series' time ranges
//     genuinely intersect (legacy is expected to keep recording
//     regardless - nothing in this migration stops the raw dongle
//     entities from exporting).
//   - This script does NOT prove the two series agree in value - see
//     ecco_canonical_vs_raw_agreement.flux for that.
//
// NOT LIVE-RUN by Claude. No InfluxDB access in this environment.

import "array"

lookback = -30d
bucket = "ecco_raw"

fields = [
  {label: "battery_soc", canonical: "sensor.ecco_battery_soc", legacy: "sensor.ecco_clock_dongle_ecco_battery_soc"},
  {label: "house_power", canonical: "sensor.ecco_house_power", legacy: "sensor.ecco_clock_dongle_ecco_load_power"},
  {label: "pv_power", canonical: "sensor.ecco_pv_power", legacy: "sensor.ecco_clock_dongle_ecco_pv_power"},
  {label: "grid_power", canonical: "sensor.ecco_grid_power", legacy: "sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp"},
]

coverageForField = (f) => {
  canonicalStream =
    from(bucket: bucket)
      |> range(start: lookback)
      |> filter(fn: (r) => r._measurement == f.canonical and r._field == "value")

  legacyStream =
    from(bucket: bucket)
      |> range(start: lookback)
      |> filter(fn: (r) => r._measurement == f.legacy and r._field == "value")

  earliestCanonical =
    canonicalStream |> group() |> first() |> findRecord(fn: (key) => true, idx: 0)
  latestCanonical =
    canonicalStream |> group() |> last() |> findRecord(fn: (key) => true, idx: 0)
  earliestLegacy =
    legacyStream |> group() |> first() |> findRecord(fn: (key) => true, idx: 0)
  latestLegacy =
    legacyStream |> group() |> last() |> findRecord(fn: (key) => true, idx: 0)

  hasCanonical = exists earliestCanonical._time
  hasLegacy = exists latestLegacy._time

  // Proper interval-overlap test - see header comment. Only meaningful
  // once both series are known to have at least one point each.
  overlap =
    if hasCanonical and hasLegacy then
      earliestCanonical._time <= latestLegacy._time and earliestLegacy._time <= latestCanonical._time
    else
      false

  return array.from(rows: [{
    field: f.label,
    canonical_measurement: f.canonical,
    legacy_measurement: f.legacy,
    has_canonical_data: hasCanonical,
    has_legacy_data: hasLegacy,
    earliest_canonical_time: if hasCanonical then string(v: earliestCanonical._time) else "none",
    latest_canonical_time: if exists latestCanonical._time then string(v: latestCanonical._time) else "none",
    earliest_legacy_time: if hasLegacy then string(v: earliestLegacy._time) else "none",
    latest_legacy_time: if hasLegacy then string(v: latestLegacy._time) else "none",
    overlap_appears_present: overlap,
  }])
}

union(tables: [
  coverageForField(f: fields[0]),
  coverageForField(f: fields[1]),
  coverageForField(f: fields[2]),
  coverageForField(f: fields[3]),
])
