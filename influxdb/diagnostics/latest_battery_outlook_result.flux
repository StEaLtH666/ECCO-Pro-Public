// ECCO Pro - system health diagnostic (Task 006)
//
// READ-ONLY / MANUAL / AD-HOC. No `option task`, no `to()`, no
// scheduling. Run by hand - never executed automatically. See
// docs/SYSTEM_HEALTH_ARCHITECTURE.md section 9/10.
//
// Purpose: shows the most recent Battery Outlook model result plus its
// training_days_equivalent, so a human can distinguish "the model
// hasn't run recently" from "the model has run but has very little
// training history" - two different battery_outlook subsystem
// findings (FORECAST_STALE vs. FORECAST_HISTORY_INSUFFICIENT in
// registry/health_reason_codes.yaml).

from(bucket: "ecco_5m")
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "ecco_battery_outlook")
  |> filter(fn: (r) => r._field == "predicted_soc_0035" or r._field == "training_days_equivalent" or r._field == "model_capacity_kwh" or r._field == "discharge_efficiency")
  |> group(columns: ["_field"])
  |> last()
  |> map(fn: (r) => ({r with age_seconds: (int(v: now()) - int(v: r._time)) / 1000000000}))
  |> keep(columns: ["_field", "_time", "_value", "age_seconds"])
