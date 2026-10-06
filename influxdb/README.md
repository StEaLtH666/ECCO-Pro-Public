# InfluxDB

ECCO InfluxDB retention, aggregation and task definitions live here.

Current intended retention:
- `ecco_raw`: 30 days
- `ecco_5m`: 730 days
- `ecco_daily`: indefinite

Keep task definitions and schema notes here so long-term learning remains reproducible.

## Learned Battery Outlook

`tasks/ecco_battery_outlook_5m.flux` is the first load-learning Battery Outlook task.

It runs every 5 minutes with a 2-minute offset, learns a 5-minute time-of-day house-load profile from up to 30 days of `ecco_5m`, reads the latest real battery SOC from `ecco_raw`, and writes derived values back to `ecco_5m` under measurement `ecco_battery_outlook`.

Current fields:
- `predicted_soc_0035`
- `expected_load_kwh_0035`
- `training_days_equivalent`
- `model_capacity_kwh`
- `discharge_efficiency`

Current model tag: `load_only_v1`.

This first model intentionally does not subtract future PV. It is the proven load-learning foundation for the later full SOC trajectory / smart-charge model.
