// ECCO Pro - system health diagnostic (Task 006)
//
// READ-ONLY / MANUAL / AD-HOC. No `option task`, no `to()`, no
// scheduling. Paste into the InfluxDB Data Explorer (or `influx query`)
// and run by hand - this is never executed automatically by anything
// in this repository. See docs/SYSTEM_HEALTH_ARCHITECTURE.md section 9.
//
// Purpose: shows the most recent point and its age for a small set of
// representative ECCO raw-telemetry measurements in the `ecco_raw`
// bucket, to answer "is raw export from Home Assistant still landing."
//
// Measurement naming: influxdb/ecco_influxdb_options_v1_2.yaml sets
// `measurement_attr: entity_id`, so each measurement in `ecco_raw` is
// named after the full Home Assistant entity_id that produced it (the
// HA InfluxDB integration's own convention), NOT a custom name chosen
// by this repository. The three entities below are representative
// (telemetry, configuration, diagnostics) - substitute any other
// `sensor.ecco_clock_dongle_*` / `sensor.ecco_*` entity_id to
// check a different one.
//
// KNOWN GAP (documented, not guessed): no task or export config in
// this repository writes to a bucket/measurement named `ecco_daily` -
// CURRENT_STATE.md names `ecco_daily` among the three buckets, but no
// Flux task or HA export configuration in this repository is found to
// write to it. This script therefore does not attempt an `ecco_daily`
// diagnostic; if `ecco_daily` genuinely holds data, that is external
// to what this repository's own files can confirm.

representativeEntities = [
  "sensor.ecco_clock_dongle_ecco_battery_soc",
  "sensor.ecco_clock_dongle_last_telemetry_update",
  "sensor.ecco_clock_dongle_last_configuration_update",
]

from(bucket: "ecco_raw")
  |> range(start: -1d)
  |> filter(fn: (r) => contains(value: r._measurement, set: representativeEntities))
  |> filter(fn: (r) => r._field == "value" or r._field == "state")
  |> group(columns: ["_measurement"])
  |> last()
  |> map(fn: (r) => ({r with age_seconds: (int(v: now()) - int(v: r._time)) / 1000000000}))
  |> keep(columns: ["_measurement", "_time", "_value", "age_seconds"])
