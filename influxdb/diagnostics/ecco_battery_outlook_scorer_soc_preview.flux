// ECCO Pro - Battery Outlook scorer SOC read-only preview
//
// Purpose:
// - reproduce the daily scorer's pre-charge actual-SOC boundary
// - exercise canonical/latest-with-legacy-fallback selection
// - compare the selected value against the scorer's former legacy-only path
//
// READ ONLY: no option task and no to() call.

import "array"
import "date"
import "timezone"

option location = timezone.location(name: "Europe/London")

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

targetRecord =
  from(bucket: "ecco_raw")
    |> range(start: -20m)
    |> filter(fn: (r) =>
      r._measurement == "sensor.ecco_config_charge_start_minute" and
      r._field == "value"
    )
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

targetMinute = int(v: targetRecord._value)
currentMinute = (date.hour(t: now()) * 60) + date.minute(t: now())

minutesPastTarget = (currentMinute - targetMinute + 1440) % 1440

actualStopTime = date.sub(
  d: duration(v: (minutesPastTarget + 1) * 60000000000),
  from: now(),
)

selectedRecord =
  readEccoTelemetryLatest(
    bucket: "ecco_raw",
    canonicalMeasurement: "sensor.ecco_battery_soc",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_battery_soc",
    field: "value",
    rangeStart: -48h,
    rangeStop: actualStopTime,
  )
    |> findRecord(fn: (key) => true, idx: 0)

legacyRecord =
  from(bucket: "ecco_raw")
    |> range(start: -48h, stop: actualStopTime)
    |> filter(fn: (r) =>
      r._measurement == "sensor.ecco_clock_dongle_ecco_battery_soc" and
      r._field == "value"
    )
    |> group()
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

array.from(rows: [
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_scorer_soc_preview",
    _field: "selected_actual_soc",
    _value: float(v: selectedRecord._value),
    selected_source: selectedRecord._ecco_source,
    selected_time: selectedRecord._time,
    legacy_soc: float(v: legacyRecord._value),
    legacy_time: legacyRecord._time,
    difference_vs_legacy: float(v: selectedRecord._value) - float(v: legacyRecord._value),
    actual_stop_time: actualStopTime,
    target_minute: targetMinute,
  },
])
  |> yield(name: "scorer_soc_preview")
