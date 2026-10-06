// ECCO Pro - Battery Outlook 5m shadow preview (READ-ONLY)
//
// Manual/ad-hoc diagnostic - NOT an `option task` (never scheduled),
// contains no `to()` call (writes nothing, ever). Mirrors the SOC and
// house-load reads that influxdb/tasks/ecco_battery_outlook_5m.flux
// uses today, but through the compatibility layer
// (influxdb/lib/ecco_telemetry_compat.flux, inlined below - see that
// file for why it can't be a real import yet) instead of the hardcoded
// raw measurement filters: most-recent-wins for current SOC, per-5-
// minute-window canonical-preferred/legacy-fallback for load history.
//
// Purpose: this is the concrete "run old and new queries side-by-side"
// / "compare outputs" tool for Battery Outlook's actual model inputs
// (per docs/CANONICAL_TELEMETRY_MIGRATION.md's staged rollout). Run
// this, then compare current_soc_* and training_days_* against the most
// recent point the real production task actually wrote to
// ecco_5m/ecco_battery_outlook. They should match (or be extremely
// close - see the field's `_ecco_source` for which series answered).
//
// IMPORTANT: history_canonical_window_count and
// history_legacy_window_count expose exactly how many 5-minute windows
// each source actually contributed. If history_canonical_window_count
// is 0, this result is ENTIRELY legacy data flowing through unchanged -
// that proves the compatibility layer's fallback path works, but it is
// NOT evidence that canonical history is usable yet. Do not treat a
// 100%-legacy result as proof the canonical migration works; check
// ecco_canonical_5m_history_check.flux first to see whether canonical
// house-power history exists in ecco_5m at all.
//
// This does NOT replicate the full Battery Outlook prediction
// (load-profile learning, expected-load-to-target, predicted SOC) -
// only the two telemetry-sourced inputs that are actually candidates
// for this migration (current SOC, house-load history/training days).
// Everything else in the real task (capacity/efficiency/target-minute
// config reads, the prediction arithmetic itself) is unchanged by this
// migration and is intentionally not duplicated here.
//
// NOT LIVE-RUN by Claude. No InfluxDB access in this environment.

import "array"
import "date"

// --- inlined from influxdb/lib/ecco_telemetry_compat.flux ---
// Keep byte-for-byte identical to that file. See
// influxdb/diagnostics/test_telemetry_selection_logic.py for the static
// check that enforces this.

readEccoTelemetryLatest = (bucket, canonicalMeasurement, legacyMeasurement, field, rangeStart, rangeStop=now()) => {
  canonicalLast =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == canonicalMeasurement and r._field == field)
      |> group()
      |> last()
      |> map(fn: (r) => ({ r with _ecco_source: "canonical" }))
      |> findRecord(fn: (key) => true, idx: 0)

  legacyLast =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == legacyMeasurement and r._field == field)
      |> group()
      |> last()
      |> map(fn: (r) => ({ r with _ecco_source: "legacy" }))
      |> findRecord(fn: (key) => true, idx: 0)

  hasCanonical = exists canonicalLast._time
  hasLegacy = exists legacyLast._time

  chosen =
    if hasCanonical and hasLegacy then
      (if canonicalLast._time >= legacyLast._time then canonicalLast else legacyLast)
    else if hasCanonical then
      canonicalLast
    else
      legacyLast

  return array.from(rows: [chosen])
}

readEccoTelemetryHistory = (bucket, canonicalMeasurement, legacyMeasurement, field, rangeStart, rangeStop=now(), windowEvery=5m) => {
  // One row per window that canonical actually covers, tagged as such.
  // group(columns: ["_window"]) then last() collapses any duplicate
  // points that land in the same window to a single representative
  // value per window, the same defensive "don't pick an arbitrary
  // duplicate" idiom already used elsewhere in this codebase (group()
  // before last()/first()).
  canonicalByWindow =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == canonicalMeasurement and r._field == field)
      |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
      |> group(columns: ["_window"])
      |> last()
      |> group()

  // The set of window keys canonical already covers, so legacy can be
  // excluded from exactly those windows and nowhere else - this is what
  // guarantees no window is ever double-counted, without depending on a
  // single global cutover time.
  canonicalWindowKeys = canonicalByWindow |> findColumn(fn: (key) => true, column: "_window")

  legacyFillIn =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == legacyMeasurement and r._field == field)
      |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
      |> group(columns: ["_window"])
      |> last()
      |> group()
      |> filter(fn: (r) => not contains(value: r._window, set: canonicalWindowKeys))
      |> map(fn: (r) => ({ r with _ecco_source: "legacy" }))

  canonicalTagged =
    canonicalByWindow
      |> map(fn: (r) => ({ r with _ecco_source: "canonical" }))

  // Normalise _time to the window boundary before returning. Without
  // this, the winning row keeps its own original sample time, which can
  // differ between canonical and legacy even within the SAME window
  // (they are two independently-polled ~10s series, not synchronised to
  // the same instant) - Battery Outlook's load-profile learning buckets
  // history by date.hour(t: r._time)/date.minute(t: r._time) to build a
  // 5-minute time-of-day profile, so an unnormalised timestamp could
  // classify what is logically one 5-minute slot into two different
  // minute-of-day buckets depending on which source answered and
  // exactly when within the window it happened to sample. Normalising
  // makes the output's time-of-day classification depend only on the
  // window itself, never on source or exact sample instant, and removes
  // any dependency on ecco_5m's own exact timestamp alignment - which
  // this repository cannot verify, since no rollup task for it is
  // checked in here. The original sample time is preserved in
  // _ecco_original_time for diagnostics.
  return union(tables: [canonicalTagged, legacyFillIn])
    |> map(fn: (r) => ({ r with _ecco_original_time: r._time, _time: r._window }))
}

// --- end inlined compatibility layer ---

// Same current-SOC read as ecco_battery_outlook_5m.flux's socRecord,
// through the compatibility layer instead of a hardcoded raw filter.
socResult =
  readEccoTelemetryLatest(
    bucket: "ecco_raw",
    canonicalMeasurement: "sensor.ecco_battery_soc",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_battery_soc",
    field: "value",
    rangeStart: -24h,
  )
  |> findRecord(fn: (key) => true, idx: 0)

// Same 30-day load history as ecco_battery_outlook_5m.flux's
// loadHistory/trainingRecord, through the compatibility layer's
// per-5-minute-window canonical-preferred/legacy-fallback history
// reader instead of a single raw filter.
loadHistory =
  readEccoTelemetryHistory(
    bucket: "ecco_5m",
    canonicalMeasurement: "sensor.ecco_house_power",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_load_power",
    field: "value",
    rangeStart: -30d,
  )

trainingRecord =
  loadHistory
    |> count(column: "_value")
    |> group()
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

trainingDays = if exists trainingRecord._value then float(v: trainingRecord._value) / 288.0 else 0.0

canonicalWindowCountRecord =
  loadHistory
    |> filter(fn: (r) => r._ecco_source == "canonical")
    |> count(column: "_value")
    |> group()
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

legacyWindowCountRecord =
  loadHistory
    |> filter(fn: (r) => r._ecco_source == "legacy")
    |> count(column: "_value")
    |> group()
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

canonicalWindowCount = if exists canonicalWindowCountRecord._value then int(v: canonicalWindowCountRecord._value) else 0
legacyWindowCount = if exists legacyWindowCountRecord._value then int(v: legacyWindowCountRecord._value) else 0

array.from(rows: [{
  current_soc_value: if exists socResult._value then socResult._value else -1.0,
  current_soc_source: if exists socResult._ecco_source then socResult._ecco_source else "none",
  current_soc_time: if exists socResult._time then string(v: socResult._time) else "none",
  training_days_shadow: trainingDays,
  history_canonical_window_count: canonicalWindowCount,
  history_legacy_window_count: legacyWindowCount,
  history_is_entirely_legacy: canonicalWindowCount == 0,
  note: "Compare training_days_shadow against the real task's last-written training_days_equivalent (measurement ecco_battery_outlook). A meaningful difference (not just rounding) means the compatibility layer's history selection disagrees with production and must be investigated before any cutover. If history_is_entirely_legacy is true, this result proves nothing about canonical history - see ecco_canonical_5m_history_check.flux.",
}])
