# Battery time to reserve (FE-1)

An estimate of how long the batteries can keep discharging, at recent usage, before they reach the configured reserve. It is
shown on the Energy Flow card's battery node and in the Overview's battery estimate card.

**Status: STAGED / NOT LIVE-PROVEN.** Offline template tests only
(`home-assistant/tests/test_ecco_battery_runtime.py`). It becomes trustworthy only after it has been observed against real
discharges on the reference installation.

**It is an estimate, not a guarantee, and not a control.** Nothing in ECCO enforces the reserve (see [SAFETY.md](../SAFETY.md)),
and nothing acts on this estimate. The package contains no service call, script, automation or action.

## Where it lives

| Part | File |
|---|---|
| Estimate (Home Assistant, read only) | [`home-assistant/packages/ecco_battery_runtime.yaml`](../home-assistant/packages/ecco_battery_runtime.yaml) |
| Display (Energy Flow card, FE-0 hook `nodes.battery.time_to_reserve`) | [`frontend/ecco-energy-flow-card/`](../frontend/ecco-energy-flow-card/README.md) |
| Dashboard wiring (Overview) | `home-assistant/dashboards/ecco_pro.yaml` v7.21.0 |
| Offline proofs | `home-assistant/tests/test_ecco_battery_runtime.py`, `frontend/ecco-energy-flow-card/test/reserveRuntime.test.ts` |

Two entities:

- `sensor.ecco_battery_runtime_model` is the model. Its state is the time it was last evaluated. Its `model` attribute holds the
  smoothing and learning state, plus the estimate.
- `sensor.ecco_battery_time_to_reserve` is what dashboards read.
  - Its state is the estimate in minutes. It is a number only while discharging (or 0 at the reserve), and unknown otherwise.
  - Its attributes are `status`, `reason`, `summary`, `minutes_low` / `minutes_high` (the likely range), `beyond_horizon`,
    `reserve_soc`, `discharge_w`, `energy_above_reserve_kwh`, `capacity_basis`, `capacity_kwh`, `solar_assisted`,
    `history_minutes` and `estimate_note`.

## Inputs (authoritative entities)

| Input | Entity | Why this one |
|---|---|---|
| Battery power | `sensor.<slug>_ecco_battery_output_power` | Register 190, published every 10 s. **Positive = discharge**, the documented ECCO convention (firmware, registry, `ecco_core`, the flow card's `discharge_positive`). |
| Battery SOC | `sensor.<slug>_ecco_battery_soc` | Register 184, integer %. Used raw: the canonical `sensor.ecco_battery_soc` renders an unreadable value as 0. |
| Liveness | `binary_sensor.<slug>_telemetry_online`, plus the age of the battery power report (`last_reported`, else `last_updated`) | A failed or skipped poll keeps the old values, so they look live. The online flag and the report age are the real liveness signals. |
| Reserve | `input_number.ecco_minimum_reserve_soc` | The only configurable reserve in Home Assistant, and the one the dashboard already shows. Whatever value it holds is used; nothing is built in. |
| Capacity | `input_number.ecco_battery_model_capacity` | The site's configured capacity. It is used only until the energy per SOC percent has been measured (see below). |
| Solar | `sensor.<slug>_ecco_pv_power` | Labelling only (`solar_assisted`). |

No BMS value, battery-current sign, inverter rated power or register-204 capacity is used. The firmware publishes no BMS value
and no rated power, and the sign of register 191 is not documented.

## How the estimate is made

Every minute, while telemetry is fresh, the model takes one sample of battery power.

**Discharge estimate = level + spike allowance.**

- **Level.** First, a median of the last 9 one-minute samples, so a load shorter than about 4 minutes (a kettle, a pump start)
  does not move it. Then an exponential average with a 10-minute time constant, which follows a sustained change (an oven, a
  heat pump): about 63 % within 15 minutes and 90 % within about 30.
- **Spike allowance.** A 3-hour average of how far each minute was above (or below) the median. A median on its own would
  ignore the energy of frequent short loads and be optimistic. In the offline test with kettle-size spikes in 5 % of minutes it
  would be about 17 % low. The allowance counts that energy at its real average, while a single 3-minute kettle moves the
  estimate by less than 10 %.
- **Spread.** The spread of the median around the level gives the likely range.

**Energy per SOC percent.**

- While the battery discharges, the energy it delivers (power × time) is added up between SOC steps. Every 5 SOC points gives
  one measurement.
- After 3 measurements (15 points of real discharge), the measured value replaces the configured capacity
  (`capacity_basis: measured`).
- A measurement outside half to one and a half times the configured value is rejected.
- Charging, or a gap, restarts the current measurement. What has been learned is kept, including across restarts (trigger-based
  template entities restore their attributes).

**Minutes.**

- minutes = (SOC − reserve) × energy per percent ÷ discharge estimate.
- They are rounded so they do not look more precise than they are: to 1 minute below 10, to 5 minutes below 2 hours, and to
  10 minutes above that. They are capped at 72 hours (`beyond_horizon`).
- The likely range assumes one SOC point less (integer SOC) at the discharge estimate plus its spread, and the full SOC at the
  estimate minus its spread.

## States

| Status | When | Display |
|---|---|---|
| `stale` | Telemetry offline, battery power unavailable, or the last report older than 180 s (the telemetry health limit) | Telemetry stale |
| `insufficient_data` | SOC missing or out of range; SOC 0 % while discharging over 300 W (suspect); reserve or capacity unavailable; or fewer than 10 minutes of contiguous history (after a start, a gap over 5 minutes, or an SOC jump over 5 points in a minute) | Insufficient data |
| `charging` | Discharge estimate at or below −50 W | Charging |
| `at_reserve` | SOC at or below the reserve while not charging (0 minutes) | At reserve |
| `holding` | Discharge estimate between −50 W and +50 W (zero or insufficient discharge) | Holding |
| `discharging` | Otherwise | ≈5h 20m to reserve (Over 3 days when capped) |

The presentation sensor reports `insufficient_data` (reason `model_not_updating`) if the model has not been evaluated for more
than 180 s. It never shows the last value as current.

## Display

The Energy Flow card adds one small, static line under the battery's status, using the entity's own value and status. For
example "≈5h 20m to reserve", "Charging", "Holding", "At reserve", "Insufficient data" or "Telemetry stale"; missing and stale
data are visibly subdued.

The tooltip says "Approximately …", gives the likely range, flags a solar-assisted discharge, and ends with "an estimate, not a
guarantee".

The card computes nothing. It never reads SOC, power or capacity for this line, and it never derives a status. The flow
animation, line routing and battery colours are unchanged.

## Known limitations

- **Recent usage, not a forecast.** The estimate assumes the recent discharge continues. It does not know about solar going
  down, a scheduled grid charge, an appliance about to start or a tariff window. A solar-assisted estimate is flagged because it
  will shorten as solar falls.
- **Inverter limits.** Battery power is measured, so a load above the inverter's or the BMS's discharge limit (with the rest
  from the grid) is already reflected. A future load above that limit is not modelled.
- **SOC resolution.** SOC is an integer. The model learns energy per percent from 5-point steps and brackets the range with one
  point. Until 15 points of discharge have been observed, the configured capacity is the basis, and it may be the nominal
  capacity rather than the usable one.
- **The configured reserve.** The value is read from `input_number.ecco_minimum_reserve_soc`. This repository's defaults
  automation initialises that helper to 15 % once (`ecco_pro.yaml`). The 40 % default of the Intelligence engine lives only in
  its Python configuration, and the inverter's own shutdown SOC (register 217) is not consulted. Several Overview planning
  scripts still assume their own reserve; they are unchanged.
- **Warm-up.** After a Home Assistant restart longer than 5 minutes, the history restarts: "Insufficient data" for 10 minutes.
- **Recorder.** The model's attributes change every minute. They stay under 2 kB (pinned by the tests), but they are recorded
  and exported by the `sensor.ecco_*` InfluxDB globs.
- **Not live-proven.** HA's `last_reported` is used when present, else `last_updated`. With `last_updated` only, an unchanged
  power value can read as stale after 180 s.
