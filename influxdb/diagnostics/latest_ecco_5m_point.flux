// ECCO Pro - system health diagnostic (Task 006, corrected in Task 006A)
//
// READ-ONLY / MANUAL / AD-HOC. No `option task`, no `to()`, no
// scheduling. Run by hand in the InfluxDB Data Explorer or `influx
// query` - never executed automatically. See
// docs/SYSTEM_HEALTH_ARCHITECTURE.md section 9.
//
// TASK 006A CORRECTION: this script previously queried the
// `ecco_battery_outlook` measurement (the Battery Outlook TASK'S
// OUTPUT). That only proves the production task is writing results -
// it does NOT independently prove the underlying `ecco_5m` house-load
// HISTORY the model actually trains on is itself current. This script
// now queries that underlying history directly.
//
// Confirmed by reading influxdb/tasks/ecco_battery_outlook_5m.flux:100-106
// (the task's own `loadHistory` query) on this branch's baseline:
//
//   loadHistory =
//     from(bucket: "ecco_5m")
//       |> range(start: -30d)
//       |> filter(fn: (r) =>
//         r._measurement == "sensor.ecco_clock_dongle_ecco_load_power" and
//         r._field == "value"
//       )
//
// This is the actual training input - not a canonical/Task-004 entity
// (this branch is independent of Task 004) and not the model's output
// measurement (see latest_battery_outlook_result.flux for that,
// tracked separately under the battery_outlook subsystem, not
// influx_5m - see registry/system_health_checks.yaml).
//
// Purpose: shows the most recent load-power history point and its age,
// answering "is the underlying ecco_5m history Battery Outlook trains
// on still receiving new data" independently of whether the Battery
// Outlook task itself is currently running.

from(bucket: "ecco_5m")
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "sensor.ecco_clock_dongle_ecco_load_power")
  |> filter(fn: (r) => r._field == "value")
  |> last()
  |> map(fn: (r) => ({r with age_seconds: (int(v: now()) - int(v: r._time)) / 1000000000}))
  |> keep(columns: ["_measurement", "_time", "_value", "age_seconds"])
