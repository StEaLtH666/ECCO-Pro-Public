// ECCO Pro - canonical vs raw telemetry value agreement (READ-ONLY)
//
// Manual/ad-hoc diagnostic. Paste into the InfluxDB Data Explorer /
// Script Editor and run by hand - deliberately NOT an `option task`
// (never scheduled) and contains no `to()` call (cannot write anything).
//
// Proves that the canonical entity and its raw source actually agree in
// value during the period both are recording - coverage_check.flux only
// proves both series exist, not that they say the same thing.
//
// Tolerance handling: canonical and raw entities are two independently
// polled instances of the same underlying firmware sensor (~10s poll
// cadence per firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
// telemetry interval), so their timestamps are not identical even
// though they trace back to the same reading. Comparing point-by-point
// on exact timestamps would show spurious differences from readings
// simply having moved between the two samples, especially for power
// (which can swing quickly). Both series are instead resampled onto a
// common `window` grid (last value per window) before comparing, which
// absorbs that natural timestamp skew. Widen `window` if a field swings
// fast enough that even this shows disagreement that looks like noise
// rather than a real problem.
//
// Grid sign convention: no transform is applied anywhere in this
// script. If canonical and legacy disagree in sign for the grid field,
// that is a real bug to investigate, not something this script hides or
// corrects for.
//
// Join safety: canonical and legacy come from different measurements
// (different `_measurement` values, and InfluxDB may attach different
// tag sets to each), so their group keys differ before any explicit
// grouping. This script does not rely on join() implicitly reconciling
// that - each side is explicitly collapsed with group() and reduced to
// exactly the two columns the join needs (`_time` and its renamed value
// column) via keep() before joining, so the join key is unambiguous
// regardless of what tags either series happens to carry.
//
// Expected interpretation:
//   - mean_abs_diff and max_abs_diff near zero (within the field's own
//     natural sensor noise/resolution): canonical is faithfully
//     tracking its raw source, as expected for a direct alias.
//   - Any large, sustained max_abs_diff: investigate before trusting
//     canonical for this field - do not assume it is just noise.
//   - pair_count = 0: the two series never had data in the same
//     resampled window in the requested range - widen the range or
//     re-run coverage_check.flux first to find where they overlap.
//
// NOT LIVE-RUN by Claude. No InfluxDB access in this environment.

import "array"
import "math"

bucket = "ecco_raw"
window = 30s
rangeStart = -24h

fields = [
  {label: "battery_soc", canonical: "sensor.ecco_battery_soc", legacy: "sensor.ecco_clock_dongle_ecco_battery_soc"},
  {label: "house_power", canonical: "sensor.ecco_house_power", legacy: "sensor.ecco_clock_dongle_ecco_load_power"},
  {label: "pv_power", canonical: "sensor.ecco_pv_power", legacy: "sensor.ecco_clock_dongle_ecco_pv_power"},
  {label: "grid_power", canonical: "sensor.ecco_grid_power", legacy: "sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp"},
]

agreementForField = (f) => {
  canonicalWindowed =
    from(bucket: bucket)
      |> range(start: rangeStart)
      |> filter(fn: (r) => r._measurement == f.canonical and r._field == "value")
      |> aggregateWindow(every: window, fn: last, createEmpty: false)
      |> rename(columns: {_value: "canonical_value"})
      |> group()
      |> keep(columns: ["_time", "canonical_value"])

  legacyWindowed =
    from(bucket: bucket)
      |> range(start: rangeStart)
      |> filter(fn: (r) => r._measurement == f.legacy and r._field == "value")
      |> aggregateWindow(every: window, fn: last, createEmpty: false)
      |> rename(columns: {_value: "legacy_value"})
      |> group()
      |> keep(columns: ["_time", "legacy_value"])

  joined =
    join(tables: {c: canonicalWindowed, l: legacyWindowed}, on: ["_time"])
      |> map(fn: (r) => ({
        r with
        abs_diff: math.abs(x: r.canonical_value - r.legacy_value),
      }))

  summary =
    joined
      |> group()
      |> reduce(
        identity: {count: 0, sum_abs_diff: 0.0, max_abs_diff: 0.0},
        fn: (r, accumulator) => ({
          count: accumulator.count + 1,
          sum_abs_diff: accumulator.sum_abs_diff + r.abs_diff,
          max_abs_diff: if r.abs_diff > accumulator.max_abs_diff then r.abs_diff else accumulator.max_abs_diff,
        }),
      )
      |> findRecord(fn: (key) => true, idx: 0)

  pairCount = if exists summary.count then summary.count else 0
  meanAbsDiff = if pairCount > 0 then summary.sum_abs_diff / float(v: pairCount) else 0.0
  maxAbsDiff = if exists summary.max_abs_diff then summary.max_abs_diff else 0.0

  return array.from(rows: [{
    field: f.label,
    canonical_measurement: f.canonical,
    legacy_measurement: f.legacy,
    window: string(v: window),
    pair_count: pairCount,
    mean_abs_diff: meanAbsDiff,
    max_abs_diff: maxAbsDiff,
  }])
}

union(tables: [
  agreementForField(f: fields[0]),
  agreementForField(f: fields[1]),
  agreementForField(f: fields[2]),
  agreementForField(f: fields[3]),
])
