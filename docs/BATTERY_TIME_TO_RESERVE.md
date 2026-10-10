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
  - Every value is withheld when the model has not been evaluated for more than 180 s; the status is then
    `insufficient_data` with reason `model_not_updating`.

## Inputs (authoritative entities)

| Input | Entity | Why this one |
|---|---|---|
| Battery power | `sensor.<slug>_ecco_battery_output_power` | Register 190, polled every 10 s. **Positive = discharge**, the documented ECCO convention (firmware, registry, `ecco_core`, the flow card's `discharge_positive`). |
| Battery SOC | `sensor.<slug>_ecco_battery_soc` | Register 184, integer %. Used raw: the canonical `sensor.ecco_battery_soc` renders an unreadable value as 0. |
| Liveness | `binary_sensor.<slug>_telemetry_online` and the age of `sensor.<slug>_last_telemetry_update` | See below. |
| Reserve | `input_number.ecco_minimum_reserve_soc` | The only configurable reserve in Home Assistant, and the one the dashboard already shows. Whatever value it holds is used; nothing is built in. |
| Capacity | `input_number.ecco_battery_model_capacity` | The site's configured capacity. It is used only until the energy per SOC percent has been measured (see below). |
| Solar | `sensor.<slug>_ecco_pv_power` | Labelling only (`solar_assisted`). |

**Liveness.** A failed or skipped poll leaves the old values in place, so they look live. ESPHome also passes on only a
changed value: Home Assistant drops a reading equal to the previous one, so an unchanged battery power (for example 0 W while
idle or held at the reserve) never moves its `last_reported`.

The model therefore takes freshness from the dongle's `last_telemetry_update`. Its text carries the poll time to the second, so
it changes on every successful poll even when every reading is the same.

Telemetry counts as fresh while that text has **changed, as seen by the model, within the last 180 s**. A reconnect that replays
the old text with a new timestamp does not count. The dongle publishes it only while it has NTP time ("Waiting" before that).
Until then, or while that diagnostic entity is disabled, the battery power's report age is the fallback, and a constant reading
then reads as stale after 180 s.

No BMS value, battery-current sign, inverter rated power or register-204 capacity is used. The firmware publishes no BMS value
and no rated power, and the sign of register 191 is not documented.

## How the estimate is made

Every minute, while telemetry is fresh, the model adds one sample of battery power to a window of the last 30 samples.

**Usage: the winsorized mean of the window.**

- The 4 highest samples are clipped to the 5th highest, and the 4 lowest to the 5th lowest (fewer while the window is short).
- A one-off load of up to 4 minutes (a kettle, a pump start, a sun burst) is therefore ignored.
- A load that recurs 5 or more times in the window counts in full, at its real average: an oven or hob switching on and off, a
  regular pump, a heat pump.
- It counts a sustained change from about its 5th minute and in full within about 27 minutes.

**Direction.**

- A **sustained run** decides at once. A run means all of the last 8 samples are on one side: each at or above +60 W
  (discharging), each within −60..+60 W (holding), or each at or below −60 W (charging).
- Otherwise (a cycling or mixed load) the usage decides: charging below −60 W, discharging above +60 W, holding between.
- A state is left only past −40 W / +40 W (hysteresis), so a load hovering near the threshold does not flap.

**Discharge = base + spike allowance.**

- **Base.** The usage, raised (never lowered) to the lower median (the 4th smallest of 8) of a sustained discharging run.
- A sustained rise in load (an oven) shortens the estimate within about 5 to 8 minutes. A fall relaxes it only as the window
  moves on, so the estimate errs on the short side meanwhile.
- **Spike allowance.** The 3-hour average, over discharging minutes only and never below zero, of how far each minute was above
  the base.
  - It gives back the energy of sparse short loads that the clipping leaves out. In the offline test with kettle-size spikes in
    5 % of minutes, the usage alone would be about 17 % low.
  - A single 3-minute kettle moves the estimate by less than 10 %.
  - It does not learn while charging or holding, so solar bursts and cloud dips cannot bend it.
  - It is kept across gaps and solar days, because it describes the household. After a long outage or a solar day it can make
    the estimate short until it re-learns.

**Energy per SOC percent.**

- While the battery discharges, the energy it delivers (power × time) is added up between SOC steps. Every 5 SOC points gives
  one measurement.
- After 3 measurements (15 points of real discharge), the measured value replaces the configured capacity
  (`capacity_basis: measured`).
- A measurement outside half to one and a half times the configured value is rejected.
- A single measurement more than 20 % away from the measured value (for example an SOC recalibration) is held, not acted on.
- Measuring restarts when two consecutive measurements agree with each other but are more than 20 % away from the measured value
  (a module lost or added), or when the configured capacity is changed. The configured value is then the basis again until 3
  measurements.
- A value measured while the capacity helper was unavailable is tied to the capacity when it returns, so a later change still
  restarts the measuring.
- Charging, or a gap, restarts only the current 5-point segment.
- Learned values persist across restarts: trigger-based template entities restore their attributes.

**Minutes.**

- minutes = (SOC − reserve) × energy per percent ÷ discharge.
- They are rounded so they do not look more precise than they are: to 1 minute below 10, to 5 minutes below 2 hours, and to
  10 minutes above that. They are capped at 72 hours (`beyond_horizon`).
- **The likely range covers usage variation and SOC resolution only.**
  - It uses the second-heaviest and second-lightest 5-minute blocks of the window, plus the allowance, and one SOC point less for
    the short end.
  - It does **not** cover capacity uncertainty. While `capacity_basis` is `configured`, the configured value may be the nominal
    rather than the usable capacity, and the true time can lie outside the range.

**Measured behaviour in the offline tests** (synthetic loads, not a live proof):

| Load | Result |
|---|---|
| Steady or slowly varying | Within 15 % of the load's mean, 0 to +6 % on average (short side) |
| Ovens and hobs switching on and off, regular cycling loads | Within 15 % of their true average after 30 to 60 minutes |
| Random kettle-size spikes (5 % of minutes) | Unbiased once the allowance has learned; within 25 % in 95 % of minutes. A cluster of 5 or more spikes in 30 minutes counts in full as real recent usage. |
| A random 35 %-duty hob | Unbiased; within two window standard deviations in 93 % of minutes |

## States

| Status | When | Display |
|---|---|---|
| `stale` | Telemetry offline, battery power unavailable, or no successful poll for more than 180 s | Telemetry stale |
| `insufficient_data` | SOC missing or out of range; SOC 0 % while the usage shows over 300 W of discharge (suspect); reserve or capacity unavailable; fewer than 10 minutes of contiguous history (after a start, a gap over 5 minutes, or an SOC jump over 5 points in a minute); or the model not updating | Insufficient data |
| `charging` | A sustained run at or below −60 W, or the usage below −60 W (left only above −40 W) | Charging |
| `at_reserve` | SOC at or below the reserve while not charging (0 minutes) | At reserve |
| `holding` | A sustained run within −60..+60 W, or the usage between the thresholds (zero or insufficient discharge) | Holding |
| `discharging` | Otherwise | ≈5h 20m to reserve (Over 3 days when capped) |

## Display

The Energy Flow card adds one small, static line under the battery's status, using the entity's own value and status. For
example "≈5h 20m to reserve", "Charging", "Holding", "At reserve", "Insufficient data" or "Telemetry stale"; missing and stale
data are visibly subdued.

The tooltip says "Approximately …", gives the likely range, flags a solar-assisted discharge, and ends with "an estimate, not a
guarantee".

The card computes nothing. It never reads SOC, power or capacity for this line, and it never derives a status. The flow
animation, line routing and battery colours are unchanged.

The card's own status word comes from the live power with a 5 W idle threshold. It can disagree with the runtime line for a
few minutes after a change of direction, and at small powers inside the ±60 W holding band.

## Known limitations

- **Recent usage, not a forecast.** The estimate assumes the recent discharge continues. It does not know about solar going
  down, a scheduled grid charge, an appliance about to start or a tariff window. A solar-assisted estimate is flagged because it
  will shorten as solar falls.
- **Inverter limits.** Battery power is measured, so a load above the inverter's or the BMS's discharge limit (with the rest
  from the grid) is already reflected. A future load above that limit is not modelled.
- **SOC resolution and capacity.** SOC is an integer. Until 15 points of discharge have been observed, the configured capacity is
  the basis, and it may be the nominal capacity rather than the usable one.
- **The configured reserve.** The value is read from `input_number.ecco_minimum_reserve_soc`. This repository's defaults
  automation initialises that helper to 15 % once (`ecco_pro.yaml`). The 40 % default of the Intelligence engine lives only in
  its Python configuration, and the inverter's own shutdown SOC (register 217) is not consulted. Several Overview planning
  scripts still assume their own reserve; they are unchanged.
- **Warm-up.** After a start, or a gap of more than 5 minutes, the status is "Insufficient data" for 10 minutes.
- **Long cycles.** A load cycling slower than the window (a heat pump at 20 minutes on, 20 off) makes the estimate swing with the
  cycle. It errs on the short side on average.
- **Reload.** A template reload that fires a trigger before the entity is added skips the restore. The model then starts again,
  including the learned capacity.
- **Around a restart.** The presentation sensor is restored with its last state until Home Assistant has started and re-renders
  it. The model's restored evaluation time can also pass the 180 s check until the model's first run after start. Both last
  only while Home Assistant is booting.
- **HA's own UI.** A capped value (4320 minutes, `beyond_horizon`) shows as "3 d" in Home Assistant's own entity views, without
  "more than". The Energy Flow card shows "Over 3 days".
- **Fixed entity id.** The presentation sensor reads `sensor.ecco_battery_runtime_model` by its id. If that entity is renamed
  (or registered as `_2`), the estimate stays at "Insufficient data (model not updating)".
- **A template error resets the model.** If the model template ever raised, Home Assistant would drop its `model` attribute and
  the next run would start from scratch, including the learned capacity. All inputs are checked for being numeric and finite
  first.
- **Recorder and InfluxDB.** The model's attributes (under 2 kB, pinned by the tests) change every minute, so the recorder stores
  one attribute row a minute. The `sensor.ecco_*` InfluxDB globs export them. Excluding `sensor.ecco_battery_runtime_model` from
  the recorder and the InfluxDB export is recommended.
