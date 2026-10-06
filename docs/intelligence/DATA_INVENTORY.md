# ECCO Intelligence V1 — data and architecture inventory

Status: **local review draft.** Entity ids below follow the repository's own conventions (`home-assistant/packages/`,
`firmware/`); per-installation ids (integration account fragments, tariff meter ids) are written as `<placeholders>` and belong in a
private local profile, never in the repository. Nothing here was or is written to Home Assistant.

## 1. What ECCO can already measure (entity ids)

Two parallel measurement paths exist and are numerically identical over their overlap (see the data-quality method note):
the **ECCO ESP dongle** (`sensor.<dongle>_ecco_*`, the newer path with the shorter history) and an optional **legacy inverter
integration** (`sensor.<legacy>_*`, a longer history that may still be updating). ECCO also publishes
stable canonical aliases (`home-assistant/packages/ecco_canonical_telemetry.yaml`).

| Need | Entity (dongle unless noted) | Unit / notes |
|---|---|---|
| House load (instantaneous) | `…_ecco_load_power` (alias `sensor.ecco_house_power`) | W, ~10 s |
| House load (cumulative) | `…_ecco_total_load_energy`, `…_ecco_day_load_energy` | kWh, 0.1 kWh resolution, published ~10 min |
| Grid power | `…_ecco_grid_power_ct_clamp` (alias `sensor.ecco_grid_power`; + import / − export). Inverter's own reading: `…_ecco_grid_load` | W |
| Grid energy | `…_ecco_total_grid_import`, `…_total_grid_export`, `…_day_grid_import`, `…_day_grid_export` | kWh |
| PV power / energy | `…_ecco_pv_power` (alias `sensor.ecco_pv_power`), `…_pv1..4_power`, `…_total_pv_energy`, `…_day_pv_energy` | W / kWh |
| Battery SOC | `…_ecco_battery_soc` (alias `sensor.ecco_battery_soc`) | %, integer steps |
| Battery power / energy | `…_ecco_battery_output_power` (+ discharge), `…_total_battery_charge/discharge`, `…_day_battery_*` | W / kWh |
| Battery facts | `…_battery_voltage`, `…_battery_temperature`, `…_battery_capacity_ah`, `…_battery_shutdown`, `…_battery_restart`, `…_battery_low_warning` | |
| Inverter status | `…_ecco_inverter_system_state`, `…_inverter_fault`, `…_inverter_warning`, `…_ecco_battery_control_mode` | strings |
| RTC / clock | `…_clock_difference`, `…_last_correction`, `…_last_correction_result`, `…_rtc_*` counters, `…_inverter_time`, `…_ntp_time` | RTC drift evidence |
| TOU schedule | `sensor.ecco_tou_slot_1..6` (+ `_start_minute`), `…_ecco_timezoneN_{time,soc,power}` | six programmable time-of-use slots |
| Tariff (import) | `sensor.ecco_import_rate`, `…_next_import_rate`, `…_today_cheap_import_rate`, `…_today_peak_import_rate`, `sensor.ecco_tariff_band`, `binary_sensor.ecco_next_day_tariff_ready`, `event.<octopus_import>_current_day_rates` / `_next_day_rates` | a time-of-use import tariff with a cheap overnight window (the default config uses 00:30–05:30 local) |
| Tariff (export) | `sensor.ecco_export_rate`, `event.<octopus_export>_current_day_rates` | export tariff |
| Saving Sessions | `binary_sensor.<octopus_saving_sessions>` (+ next/current joined-event attributes), `event.<octopus_saving_session_events>` | reward unit semantics: see open decisions |
| PV forecast | `sensor.<forecast_solar>_today/_remaining/_tomorrow`, `sensor.<solcast>_forecast_today/_remaining_today/_tomorrow`, `sensor.ecco_solar_forecast_today/_remaining/_tomorrow` (ECCO blend), `sensor.ecco_forecast_snapshot_*`, `sensor.ecco_forecast_*_mae` | kWh |
| Weather | `weather.forecast_home` (no history consumed yet) | candidate feature |
| Free Power / Dump state | `switch.<dongle>_free_power_write_enable`, `button.…_start_free_power_charge_now`, `input_boolean.ecco_free_power_schedule_armed`, `input_boolean.ecco_dump_to_grid_schedule_armed`, `sensor.ecco_dump_to_grid_schedule_status`, dongle Dump/Free Power state sensors | **control surfaces — Intelligence never touches them** |
| System health | `sensor.ecco_health_{communications,runtime_configuration,manual_write_system,rtc,configuration,inverter_telemetry,supervision}`, `sensor.ecco_supervision_status`, `binary_sensor.ecco_runtime_configuration_ready` | |
| ECCO policy helpers | `input_number.ecco_minimum_reserve_soc`, `…_ecco_battery_model_capacity`, `…_round_trip_efficiency`, `input_select.ecco_automation_mode`, `input_boolean.ecco_automatic_setting_writes_enabled`, `binary_sensor.ecco_automatic_writes_armed` | see finding F1 |

**F1 — the battery reserve is not represented consistently in HA or the repo.** `input_number.ecco_minimum_reserve_soc`
has a default far below 40 %, the inverter shutdown SOC is a separate setting, and no file defines a default user reserve. Intelligence therefore carries the
reserve as explicit configuration: `SiteConfig.user_reserve_soc_pct` (default 40, a per-installation preference, not a project-wide floor) and a separate
`SiteConfig.technical_min_soc_pct` (a site-specific hardware constraint, default 10 as a placeholder only: set it to the minimum permitted by your inverter / battery
configuration, for example the inverter's battery shutdown SOC). It uses `max(user reserve, technical minimum, HA reserve)`,
and whether HA's helper should become the source of the user reserve is open design decision O-1.

## 2. Historical storage that already exists

| Store | Retention (as configured / observed in a typical install) | What it holds | Used by Intelligence V1 |
|---|---|---|---|
| HA recorder `home-assistant_v2.db` (SQLite; default recorder settings) | **states and 5-minute statistics: about 10 days**; **hourly statistics: indefinite** | everything the recorder tracks | **Primary source:** hourly statistics (read-only SQLite export, `intelligence/tools/export_ha_statistics.py`). States/5-min only for signatures and SOC validation. |
| InfluxDB (`influxdb/`, add-on) | raw / 5-minute / daily buckets with different retentions (see `influxdb/`) | 5-minute history from when the dongle went live | **Not queried** (no token, by design). `influxdb/diagnostics/history_depth_check.flux` gives the real depth. Best future source for 5-minute and 1-minute data. |
| Flux tasks | `influxdb/tasks/ecco_battery_outlook_5m.flux`, `…_score_daily.flux`, `lib/ecco_telemetry_compat.flux` | existing load-learning Battery Outlook | baseline being extended (see section 3) |
| HA statistics sensors / helpers | `sensor.ecco_battery_outlook_*`, `sensor.ecco_forecast_*_mae`, `input_number.ecco_forecast_*` | a short PV forecast scoreboard, daily SOC scorer | superseded by the scorecard for PV; SOC scorer kept |

## 3. Existing architecture relevant to Intelligence

* **Battery Outlook (`load_only_v1`)** — Flux task every 5 min: 30-day 5-minute time-of-day load profile (plain mean), current SOC, capacity, efficiency → *predicted SOC at the next regular grid-charge start* and expected load. Deliberately **ignores PV** (its morning values are therefore a no-solar worst case, not a prediction). Daily scorer compares the 21:30 prediction with the real SOC at charge start; works well in the evening (MAE 1 %) because PV is irrelevant then. Flux is hard to unit-test and cannot express similar-day / quantile logic.
* **PV forecast scorecard (`ecco_pro.yaml`, "Forecast accuracy learning 3")** — snapshots Forecast.Solar, Solcast and their unweighted blend at 23:55, scores at 23:50 next day into `input_number` accumulators (20 days). Reports raw MAE per source and picks "best source" by *raw* error. It never **corrects** a source, and 20 days is too short to see the seasonal drift (see the data-quality method note).
* **Automation mode** — `input_select.ecco_automation_mode` {Observe Only, Advisory, Automatic}; `ecco_automatic_setting_writes_enabled` off; `VERSION.yaml safety:` keeps `automatic_optimizer_control: false`. The "optimiser" is deliberately absent.
* **Recommendation surfaces** — dashboard views *Intelligence* (`ecco-intelligence`) and *Recommended* (`ecco-recommended`) compute advice in dashboard JavaScript only (no entity, no history, no scoring). Feature board R1–R3 (recommendation entity, "why" drawer, ledger) are the planned replacement; this work provides their engine.
* **Action surfaces** — Energy Actions card (Free Power NOW/LATER, Dump-to-Grid locked preview), scheduled Free Power / Dump packages, Fallback Profile arm switch (one-shot, 120 s) — all **operator-driven, interlocked, hardware-proven**. They are the only places a recommendation could ever be applied, and V1 connects to none of them.
* **Panic / suspend / revert concepts** — Free Power Restore + recovery classifier (revert to the saved snapshot), Fallback Profile (known-good profile; *Restore not implemented*), supervision heartbeat (observe-only), one-shot arm switches. For Intelligence the analogue is simply: **the engine can be switched off with no effect on control**, because it has no control path.
* **Export planning** — Dump-to-Grid (register 244/245 work) is "locked preview"; register 245 is read-only until characterised. Intelligence only estimates *how much* could be exported safely.
* **Feature board** (`docs/ECCO_2026_FEATURE_BOARD.md`) lists "generic machine-learning load forecasting" and "full appliance disaggregation" as *not now*. V1 respects that: boring statistics, neutral signature labels, no ML.

## 4. Gaps this work fills

No PV-aware SOC trajectory; no uncertainty on any prediction; no persisted forecast history for anything except the SOC scorer; no PV forecast correction; no anomaly detection; recommendations live only in JavaScript; the 40 % policy is nowhere.
