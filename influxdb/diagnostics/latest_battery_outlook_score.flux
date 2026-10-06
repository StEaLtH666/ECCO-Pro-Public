// ECCO Pro - system health diagnostic (Task 006)
//
// READ-ONLY / MANUAL / AD-HOC. No `option task`, no `to()`, no
// scheduling. Run by hand - never executed automatically. See
// docs/SYSTEM_HEALTH_ARCHITECTURE.md section 9/10.
//
// Purpose: shows the most recent daily scorer result and its age. The
// scorer task itself runs every 5 minutes (influxdb/tasks/
// ecco_battery_outlook_score_daily.flux, option task = {every: 5m,
// offset: 3m}), but only WRITES a new point once per day near the
// live-TOU-charge-start-derived "lead180_to_target" checkpoint
// (CURRENT_STATE.md). A human reading this script's output must judge
// staleness against "has today's checkpoint passed yet," not a fixed
// clock - this script deliberately does not attempt that judgement
// itself (it has no access to the live charge-start minute), it only
// reports the raw age for a human (or registry/system_health_checks.yaml's
// battery_outlook_scorer_freshness check, fed by a caller who does
// know the checkpoint) to interpret.

from(bucket: "ecco_5m")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "ecco_battery_outlook_score")
  |> filter(fn: (r) => r._field == "predicted_soc_0035" or r._field == "actual_soc_0035" or r._field == "error_soc_points" or r._field == "absolute_error_points")
  |> group(columns: ["_field"])
  |> last()
  |> map(fn: (r) => ({r with age_seconds: (int(v: now()) - int(v: r._time)) / 1000000000}))
  |> keep(columns: ["_field", "_time", "_value", "age_seconds"])
