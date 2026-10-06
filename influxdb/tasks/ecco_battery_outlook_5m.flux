// ECCO Pro - Learned Battery Outlook v1.2
// Recalculates every 5 minutes, 2 minutes after the 5-minute boundary so the
// ecco_5m downsample has time to land.
//
// Current model scope:
// - predicts SOC at the next regular grid-charge TOU start from current real SOC
// - learns house load by 5-minute time-of-day slot from ecco_5m
// - uses up to 30 days of history (automatically improves as history grows)
// - reads battery capacity, efficiency and charge-start time from ECCO runtime configuration
// - derives one-way discharge efficiency from the configured round-trip efficiency
// - does NOT yet subtract future PV; this is deliberately a load-only model
//
// Required runtime config sensors, refreshed by ecco_runtime_config.yaml:
//   sensor.ecco_config_battery_capacity
//   sensor.ecco_config_round_trip_efficiency
//   sensor.ecco_config_charge_start_minute
//
// Output measurement in ecco_5m: ecco_battery_outlook
// Legacy *_0035 field names are retained temporarily for dashboard compatibility;
// their values now refer to the configured/live charge-start time, not 00:35.

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
  name: "ECCO Battery Outlook 5m",
  every: 5m,
  offset: 2m,
}

// PORTABILITY TODO: move timezone into the installation profile.
option location = timezone.location(name: "Europe/London")

capacityRecord =
  from(bucket: "ecco_raw")
    |> range(start: -20m)
    |> filter(fn: (r) =>
      r._measurement == "sensor.ecco_config_battery_capacity" and
      r._field == "value"
    )
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

efficiencyRecord =
  from(bucket: "ecco_raw")
    |> range(start: -20m)
    |> filter(fn: (r) =>
      r._measurement == "sensor.ecco_config_round_trip_efficiency" and
      r._field == "value"
    )
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

targetRecord =
  from(bucket: "ecco_raw")
    |> range(start: -20m)
    |> filter(fn: (r) =>
      r._measurement == "sensor.ecco_config_charge_start_minute" and
      r._field == "value"
    )
    |> last()
    |> findRecord(fn: (key) => true, idx: 0)

batteryCapacityKWh = float(v: capacityRecord._value)
roundTripEfficiencyRaw = float(v: efficiencyRecord._value) / 100.0
targetMinute = int(v: targetRecord._value)
roundTripEfficiency =
  if roundTripEfficiencyRaw < 0.50 then 0.50
  else if roundTripEfficiencyRaw > 1.0 then 1.0
  else roundTripEfficiencyRaw

// A round-trip figure represents charge * discharge efficiency. Assuming the
// two directions are broadly symmetrical, sqrt(round-trip) is the per-direction
// allowance. 90% round-trip -> 94.87% one-way.
dischargeEfficiency = math.sqrt(x: roundTripEfficiency)

currentMinute =
  (date.hour(t: now()) * 60) +
  date.minute(t: now())

// Latest real battery SOC from raw telemetry.
// Home Assistant/InfluxDB may only write a new point when the value changes.
socRecord =
  readEccoTelemetryLatest(
    bucket: "ecco_raw",
    canonicalMeasurement: "sensor.ecco_battery_soc",
    legacyMeasurement: "sensor.ecco_clock_dongle_ecco_battery_soc",
    field: "value",
    rangeStart: -24h,
  )
    |> findRecord(fn: (key) => true, idx: 0)

currentSOC = float(v: socRecord._value)

// Historical 5-minute total house-load data.
// Canonical data is preferred per 5-minute window, with legacy history used
// only where canonical has no point, preserving training continuity without
// double-counting overlapping history.
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

trainingDays = float(v: trainingRecord._value) / 288.0

// Learn the mean load for each five-minute minute-of-day slot.
profile =
  loadHistory
    |> map(fn: (r) => ({
      r with
      slotMinute:
        (date.hour(t: r._time) * 60) +
        date.minute(t: r._time)
    }))
    |> group(columns: ["slotMinute"])
    |> mean(column: "_value")
    |> group()

// Sum expected house energy from now until the next configured charge-start time.
expectedLoadRecord =
  profile
    |> filter(fn: (r) =>
      if currentMinute < targetMinute then
        r.slotMinute >= currentMinute and r.slotMinute < targetMinute
      else
        r.slotMinute >= currentMinute or r.slotMinute < targetMinute
    )
    |> map(fn: (r) => ({
      r with
      _value: r._value * (5.0 / 60.0) / 1000.0
    }))
    |> sum(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

expectedLoadKWh = float(v: expectedLoadRecord._value)
batteryKWhNeeded = expectedLoadKWh / dischargeEfficiency
socUsed = (batteryKWhNeeded / batteryCapacityKWh) * 100.0
rawPredictedSOC = currentSOC - socUsed
predictedSOC =
  if rawPredictedSOC < 0.0 then 0.0
  else if rawPredictedSOC > 100.0 then 100.0
  else rawPredictedSOC

array.from(rows: [
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "predicted_soc_0035",
    _value: predictedSOC,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "expected_load_kwh_0035",
    _value: expectedLoadKWh,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "training_days_equivalent",
    _value: trainingDays,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "model_capacity_kwh",
    _value: batteryCapacityKWh,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "round_trip_efficiency",
    _value: roundTripEfficiency,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "discharge_efficiency",
    _value: dischargeEfficiency,
    model: "load_only_v1_2",
  },
  {
    _time: now(),
    _measurement: "ecco_battery_outlook",
    _field: "target_minute_of_day",
    _value: float(v: targetMinute),
    model: "load_only_v1_2",
  },
])
  |> to(bucket: "ecco_5m")
