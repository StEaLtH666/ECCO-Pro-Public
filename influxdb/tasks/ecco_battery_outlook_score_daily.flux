// ECCO Pro - Battery Outlook daily prediction scoring v1.3
//
// Purpose:
// - score the Battery Outlook prediction against real SOC at the configured/live
//   regular grid-charge TOU start
// - prediction checkpoint is 180 minutes before that target
// - score is written about 10 minutes after the target
// - uses the exact battery capacity stored with the scored prediction
//
// The task runs every five minutes. The score window is derived from the live
// target time, so no fixed 00:35 / 21:30 assumption remains in the scorer.
// Legacy *_0035 field names are retained temporarily for dashboard compatibility.

import "array"
import "date"
import "math"
import "timezone"

// Canonical/legacy compatibility layer.
// Keep aligned with influxdb/lib/ecco_telemetry_compat.flux.
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

option task = {
  name: "ECCO Battery Outlook Daily Score",
  every: 5m,
  offset: 3m,
}

// PORTABILITY TODO: move timezone into the installation profile.
option location = timezone.location(name: "Europe/London")

predictionLeadMinutes = 180
scoreDelayMinutes = 10

minuteInWindow = (minute, start, width) =>
  if start + width <= 1440 then
    minute >= start and minute < start + width
  else
    minute >= start or minute < ((start + width) % 1440)

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
predictionMinute = (targetMinute + 1440 - predictionLeadMinutes) % 1440
scoreMinute = (targetMinute + scoreDelayMinutes) % 1440
currentMinute = (date.hour(t: now()) * 60) + date.minute(t: now())
scoreWindow = minuteInWindow(minute: currentMinute, start: scoreMinute, width: 5)

// Always score against the last known SOC before the charge-start boundary.
// The task runs after the target, so calculate how far the most recent target
// is behind now(). Subtract one extra minute to guarantee the range stop is
// pre-charge even when the task starts a few seconds late.
minutesPastTarget = (currentMinute - targetMinute + 1440) % 1440
actualStopTime = date.sub(
  d: duration(v: (minutesPastTarget + 1) * 60000000000),
  from: now(),
)

// The Battery Outlook task runs at +2 minutes after each 5-minute boundary.
// Select the latest prediction in the five-minute window beginning at the
// checkpoint minute, e.g. 21:30-21:34 for a 00:30 target.
// group() is deliberate: historical model tags can leave multiple tables in
// the lookup window, so merge them before last() to select the newest record
// overall rather than the last record from an arbitrary older model series.
predictionRecord =
  from(bucket: "ecco_5m")
    |> range(start: -30h)
    |> filter(fn: (r) =>
      r._measurement == "ecco_battery_outlook" and
      r._field == "predicted_soc_0035"
    )
    |> filter(fn: (r) =>
      minuteInWindow(
        minute: (date.hour(t: r._time) * 60) + date.minute(t: r._time),
        start: predictionMinute,
        width: 5
      )
    )
    |> group()
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

trainingRecord =
  from(bucket: "ecco_5m")
    |> range(start: -30h)
    |> filter(fn: (r) =>
      r._measurement == "ecco_battery_outlook" and
      r._field == "training_days_equivalent"
    )
    |> filter(fn: (r) =>
      minuteInWindow(
        minute: (date.hour(t: r._time) * 60) + date.minute(t: r._time),
        start: predictionMinute,
        width: 5
      )
    )
    |> group()
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

capacityRecord =
  from(bucket: "ecco_5m")
    |> range(start: -30h)
    |> filter(fn: (r) =>
      r._measurement == "ecco_battery_outlook" and
      r._field == "model_capacity_kwh"
    )
    |> filter(fn: (r) =>
      minuteInWindow(
        minute: (date.hour(t: r._time) * 60) + date.minute(t: r._time),
        start: predictionMinute,
        width: 5
      )
    )
    |> group()
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

// Take the latest known SOC before the charge-start boundary. The compatibility
// layer chooses the most recent canonical or legacy point before that boundary,
// so scoring remains protected from SOC gained after grid charging begins while
// retaining legacy fallback during any canonical-side gap.
actualRecord =
  readEccoTelemetryLatest(
    bucket: "ecco_raw",
    canonicalMeasurement: "sensor.ecco_battery_soc",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_battery_soc",
    field: "value",
    rangeStart: -48h,
    rangeStop: actualStopTime,
  )
    |> findRecord(fn: (key) => true, idx: 0)

predictedSOC = float(v: predictionRecord._value)
actualSOC = float(v: actualRecord._value)
trainingDays = float(v: trainingRecord._value)
batteryCapacityKWh = float(v: capacityRecord._value)
errorPoints = actualSOC - predictedSOC
absoluteError = math.abs(x: errorPoints)
errorKWh = (errorPoints / 100.0) * batteryCapacityKWh

array.from(rows: [
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "predicted_soc_0035",
    _value: predictedSOC,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "actual_soc_0035",
    _value: actualSOC,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "error_soc_points",
    _value: errorPoints,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "absolute_error_points",
    _value: absoluteError,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "error_kwh_equivalent",
    _value: errorKWh,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "training_days_at_prediction",
    _value: trainingDays,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "model_capacity_kwh",
    _value: batteryCapacityKWh,
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook_score",
    _field: "target_minute_of_day",
    _value: float(v: targetMinute),
    model: "load_only_v1_3",
    checkpoint: "lead180_to_target",
    write_score: scoreWindow,
  },
])
  |> filter(fn: (r) => r.write_score)
  |> drop(columns: ["write_score"])
  |> to(bucket: "ecco_5m")
