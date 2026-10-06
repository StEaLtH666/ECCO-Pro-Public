// ECCO Pro - canonical house-power history check in ecco_5m (READ-ONLY)
//
// Manual/ad-hoc diagnostic - NOT an `option task` (never scheduled),
// contains no `to()` call (writes nothing, ever).
//
// Why this exists separately from ecco_canonical_coverage_check.flux:
// that script checks the `ecco_raw` bucket, which is what proves
// Home Assistant is exporting sensor.ecco_* into InfluxDB at all. It
// does NOT prove anything about the `ecco_5m` bucket specifically -
// ecco_5m is a separate downsample that this repository does not
// contain the rollup task for (it is configured directly in InfluxDB,
// not version-controlled here), and it is the ONLY bucket Battery
// Outlook's 30-day load-history/training-day calculation actually
// reads from. Proving sensor.ecco_house_power exists in ecco_raw says
// nothing about whether it has ever reached ecco_5m.
//
// Reports, for house power specifically (the one field with a real
// aggregate/history consumer):
//   - raw and canonical point counts in ecco_5m over the lookback window
//   - earliest/latest timestamp for each
//   - per-5-minute-window coverage among windows that actually have
//     data in at least one source: how many are canonical, how many
//     are legacy-only, how many have both (before source preference is
//     applied), and canonical's share of the total - this previews what
//     readEccoTelemetryHistory's per-window canonical-preferred/legacy-
//     fallback selection would actually produce for this data, before
//     wiring it into anything.
//
// Deliberately NOT reported: a "windows covered by neither source"
// count, or any expected-vs-actual window total for the lookback
// period. Computing that correctly would require deciding how partial
// windows at the range start/end boundary count, and this repository
// has no visibility into ecco_5m's own retention/rollup behaviour (no
// rollup task for it is checked in here) to make that call safely.
// Reporting a naive `lookback / windowEvery` figure as "expected
// windows" would silently misrepresent legitimate gaps (retention
// boundaries, sensor downtime, the field simply not existing yet) as
// something this script proved, which it does not. If a true gap
// analysis against a known-good expected calendar is needed later, it
// should be a deliberate follow-up, not implied by this diagnostic.
//
// Expected interpretation:
//   - canonical_5m_count = 0: canonical house power has never reached
//     ecco_5m in the lookback window, regardless of what ecco_raw shows.
//     Do not proceed with any history-based cutover until this is
//     nonzero and canonical_coverage_fraction is meaningful.
//   - windows_in_both > 0: genuine overlap exists at window granularity
//     - canonical_window_count already includes these (canonical always
//     wins a window it has data in); windows_in_both is reported
//     separately so the "before source preference" overlap is visible.
//
// NOT LIVE-RUN by Claude. No InfluxDB access in this environment.

import "array"
import "date"

bucket = "ecco_5m"
lookback = -30d
windowEvery = 5m
canonicalMeasurement = "sensor.ecco_house_power"
legacyMeasurement = "sensor.ecco_clock_dongle_ecco_load_power"

canonicalStream =
  from(bucket: bucket)
    |> range(start: lookback)
    |> filter(fn: (r) => r._measurement == canonicalMeasurement and r._field == "value")

legacyStream =
  from(bucket: bucket)
    |> range(start: lookback)
    |> filter(fn: (r) => r._measurement == legacyMeasurement and r._field == "value")

canonicalCountRecord =
  canonicalStream |> count(column: "_value") |> group() |> sum(column: "_value") |> findRecord(fn: (key) => true, idx: 0)
legacyCountRecord =
  legacyStream |> count(column: "_value") |> group() |> sum(column: "_value") |> findRecord(fn: (key) => true, idx: 0)

earliestCanonical = canonicalStream |> group() |> first() |> findRecord(fn: (key) => true, idx: 0)
latestCanonical = canonicalStream |> group() |> last() |> findRecord(fn: (key) => true, idx: 0)
earliestLegacy = legacyStream |> group() |> first() |> findRecord(fn: (key) => true, idx: 0)
latestLegacy = legacyStream |> group() |> last() |> findRecord(fn: (key) => true, idx: 0)

canonicalCount = if exists canonicalCountRecord._value then int(v: canonicalCountRecord._value) else 0
legacyCount = if exists legacyCountRecord._value then int(v: legacyCountRecord._value) else 0

// Per-5-minute-window coverage preview, same truncation idiom as
// readEccoTelemetryHistory in influxdb/lib/ecco_telemetry_compat.flux.
canonicalWindows =
  canonicalStream
    |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
    |> group(columns: ["_window"])
    |> last()
    |> group()

legacyWindows =
  legacyStream
    |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
    |> group(columns: ["_window"])
    |> last()
    |> group()

canonicalWindowKeys = canonicalWindows |> findColumn(fn: (key) => true, column: "_window")
legacyWindowKeys = legacyWindows |> findColumn(fn: (key) => true, column: "_window")

canonicalWindowCount = length(arr: canonicalWindowKeys)

legacyOnlyWindowCount =
  legacyWindows
    |> filter(fn: (r) => not contains(value: r._window, set: canonicalWindowKeys))
    |> count(column: "_value")
    |> group()
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

legacyOnlyCount = if exists legacyOnlyWindowCount._value then int(v: legacyOnlyWindowCount._value) else 0

// Windows present in BOTH streams before source preference is applied -
// distinct from canonical_window_count, which already reflects
// canonical winning every window it appears in.
windowsInBothRecord =
  legacyWindows
    |> filter(fn: (r) => contains(value: r._window, set: canonicalWindowKeys))
    |> count(column: "_value")
    |> group()
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

windowsInBoth = if exists windowsInBothRecord._value then int(v: windowsInBothRecord._value) else 0

totalCoveredWindowCount = canonicalWindowCount + legacyOnlyCount
canonicalCoverageFraction =
  if totalCoveredWindowCount > 0 then
    float(v: canonicalWindowCount) / float(v: totalCoveredWindowCount)
  else
    0.0

array.from(rows: [{
  bucket: bucket,
  canonical_measurement: canonicalMeasurement,
  legacy_measurement: legacyMeasurement,
  lookback: string(v: lookback),
  canonical_5m_count: canonicalCount,
  legacy_5m_count: legacyCount,
  earliest_canonical_time: if exists earliestCanonical._time then string(v: earliestCanonical._time) else "none",
  latest_canonical_time: if exists latestCanonical._time then string(v: latestCanonical._time) else "none",
  earliest_legacy_time: if exists earliestLegacy._time then string(v: earliestLegacy._time) else "none",
  latest_legacy_time: if exists latestLegacy._time then string(v: latestLegacy._time) else "none",
  canonical_window_count: canonicalWindowCount,
  legacy_only_window_count: legacyOnlyCount,
  windows_in_both: windowsInBoth,
  total_covered_window_count: totalCoveredWindowCount,
  canonical_coverage_fraction: canonicalCoverageFraction,
  note: "canonical_window_count = distinct 5-minute windows canonical covers (canonical always wins a window it appears in). legacy_only_window_count = windows covered by legacy but NOT canonical - what readEccoTelemetryHistory would fall back to. windows_in_both = windows present in both streams before source preference. total_covered_window_count/canonical_coverage_fraction describe only windows actually observed in at least one source - this script does NOT report or estimate windows covered by neither source; see the file header for why.",
}])
