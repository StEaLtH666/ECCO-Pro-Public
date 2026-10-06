// ECCO Pro - system health diagnostic (Task 006, corrected in Task 006A,
// hardened for empty-history safety in Task 006B)
//
// READ-ONLY / MANUAL / AD-HOC. No `option task`, no `to()`, no
// scheduling. Run by hand - never executed automatically. See
// docs/SYSTEM_HEALTH_ARCHITECTURE.md section 9/10.
//
// TASK 006A CORRECTION: this script previously counted distinct
// calendar days containing `ecco_battery_outlook` / `predicted_soc_0035`
// points - that measures OUTPUT history (whether the production task
// ran on a given day), not the house-load INPUT history the model
// actually trains on. It now measures the same underlying measurement
// the production task itself reads (confirmed against
// influxdb/tasks/ecco_battery_outlook_5m.flux:100-106's own
// `loadHistory` query: bucket "ecco_5m", measurement
// "sensor.ecco_clock_dongle_ecco_load_power", field "value").
//
// Deliberately kept a SEPARATE, independent measurement from the
// model's own self-reported `training_days_equivalent` field (read
// back into Home Assistant as sensor.ecco_load_model_training_days,
// tracked under the battery_outlook_history check) - the two should
// agree in a healthy system, but this diagnostic does not assume they
// do, and is not described as measuring "the same thing".
//
// TASK 006B HARDENING - empty-history safety: the exact condition this
// diagnostic exists to detect ("there is little/no training history")
// includes the extreme case of ZERO points in the last 30 days. The
// previous version called `first()`/`last()` (SELECTOR functions,
// which - per documented Flux/InfluxDB behaviour - emit NO output row
// at all when their input is empty) and then immediately dereferenced
// `._time` on the result via `findRecord`, which is unsafe if the
// selector produced nothing. This version guards on `pointCount`,
// computed via `count()` - an AGGREGATE function, which (per documented
// Flux/InfluxDB behaviour, unlike a selector) reliably emits a row even
// for empty input, with value 0. `has_data` is then used to choose
// between the real computation and an explicit "no data" result via
// Flux's `if/else` conditional expression, so no field is ever
// dereferenced from a row that might not exist.
//
// REMAINING LIVE-VALIDATION QUESTION (not resolved offline, do not
// treat as proven): if `from() |> range() |> filter()` matches NOTHING
// at all (the measurement has never existed, not merely "existed but
// had no points in the last 30 days"), it is InfluxDB/Flux's own
// implementation detail whether that yields zero TABLES (in which case
// even `count()` downstream may itself produce no row, since there is
// no table for it to operate on) versus one empty table (in which case
// `count()` reliably yields a 0-value row, which is the case this
// script's guard is built on and is confident about). This distinction
// was NOT executed against a live InfluxDB instance in this task. If
// the true-zero-tables case occurs live and `count()` itself produces
// no row, `pointCount._value` would fail to exist and this script would
// still error - see docs/SYSTEM_HEALTH_HA_DESIGN.md's live validation
// checklist for this exact open item. No production Flux changes.
//
// Kept deliberately cheap/read-only: a single range query over the
// existing 30-day training window (matching the production task's own
// range), not an expensive full-bucket scan or gap-by-gap analysis.
// Reports:
//   - has_data: false if zero points were found in the last 30 days
//   - point_count: total points observed
//   - earliest_point / latest_point: the observed span's bounds, or an
//     explicit "no data" string if has_data is false
//   - distinct_days_with_data: calendar days with at least one point
//   - effective_span_days: latest - earliest, for a coarse
//     "is there a big gap" signal without computing every individual gap

import "array"
import "date"

loadHistory =
  from(bucket: "ecco_5m")
    |> range(start: -30d)
    |> filter(fn: (r) => r._measurement == "sensor.ecco_clock_dongle_ecco_load_power")
    |> filter(fn: (r) => r._field == "value")
    |> group()

pointCount =
  loadHistory
    |> count(column: "_value")
    |> findRecord(fn: (key) => true, idx: 0)

hasData = exists pointCount._value and pointCount._value > 0

earliestRecord =
  if hasData then
    loadHistory |> first() |> findRecord(fn: (key) => true, idx: 0)
  else
    ({_time: time(v: 0), _value: 0.0})

latestRecord =
  if hasData then
    loadHistory |> last() |> findRecord(fn: (key) => true, idx: 0)
  else
    ({_time: time(v: 0), _value: 0.0})

distinctDaysRecord =
  if hasData then
    (
      loadHistory
        |> map(fn: (r) => ({r with _day: date.truncate(t: r._time, unit: 1d)}))
        |> group(columns: ["_day"])
        |> count()
        |> group()
        |> count(column: "_day")
        |> findRecord(fn: (key) => true, idx: 0)
    )
  else
    ({_day: 0})

array.from(rows: [
  {
    has_data: hasData,
    point_count: if hasData then pointCount._value else 0,
    earliest_point: if hasData then string(v: earliestRecord._time) else "no data in the last 30 days",
    latest_point: if hasData then string(v: latestRecord._time) else "no data in the last 30 days",
    distinct_days_with_data: distinctDaysRecord._day,
    effective_span_days:
      if hasData then
        float(v: int(v: latestRecord._time) - int(v: earliestRecord._time)) / 86400000000000.0
      else
        0.0,
  },
])
