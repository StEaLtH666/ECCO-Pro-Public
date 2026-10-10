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
the old text with a new timestamp does not count. The model checks once a minute and sees a new poll only at its next check, so
staleness is declared about 4 to 5 minutes (240 to 300 s) after the last successful poll.

The dongle publishes this text only while it has NTP time ("Waiting" before that). Until then, or while that diagnostic entity is
disabled, the battery power's report age is the fallback, and a constant reading then reads as stale 180 to 240 s after its
last report.

No BMS value, battery-current sign, inverter rated power or register-204 capacity is used. The firmware publishes no BMS value
and no rated power, and the sign of register 191 is not documented.

## How the estimate is made

Every minute, while telemetry is fresh, the model adds one sample of battery power to a window of the last 30 samples.

**Usage: the winsorized mean of the window.**

- The 4 highest samples are clipped to the 5th highest, and the 4 lowest to the 5th lowest. Clipping is full from 9 samples
  on; before that, the warm-up shows no estimate.
- **Up to 4 one-minute samples of a load are clipped**: a kettle, a pump start or a sun burst does not enter the usage. Their
  energy comes back through the spike allowance (below), over hours.
- **A load present in 5 or more of the window's minutes counts in full**: an oven or hob switching on and off within a few
  minutes, a regular pump.
- So there is a deliberate step between 4 and 5 occurrences. A load that shows up in exactly 4 or fewer minutes of every half
  hour is clipped again and again and enters only through the allowance; until that has learned, the estimate reads long
  (about 1.5x for the first half hour in the offline test, more for a heavier load).
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
- **Spike allowance.** The 3-hour average of exactly the energy the clipping removed from the window, spread over its 30
  minutes (also while the window refills after a gap).
  - It is learned only while discharging and with full history, and it is never negative.
  - It gives back the energy of short loads that the clipping leaves out. In the offline test with kettle-size spikes in 5 % of
    minutes, the usage alone would be about 17 % low; with the allowance it reads about 3 % long while the allowance is still
    learning (4 to 10 hours) and close to unbiased after that.
  - A single 3-minute kettle moves the estimate by less than 10 %.
  - A long load, or its end, neither feeds nor wipes it: in the offline test a 60-minute oven in a kettle household only let it
    decay at its normal 3-hour rate.
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
  - It uses the second-heaviest and second-lightest 5-minute blocks of the **clipped** window, plus the allowance, and one SOC
    point less for the short end. A single kettle therefore does not widen it.
  - It does **not** cover capacity uncertainty. While `capacity_basis` is `configured`, the configured value may be the nominal
    rather than the usable capacity, and the true time can lie outside the range.

**Measured behaviour in the offline tests** (synthetic loads, not a live proof). The estimate errs both ways depending on the
load:

| Load | Result |
|---|---|
| Steady or slowly varying | Within 15 % of the load's mean, 0 to +6 % on average (short side) |
| A switching oven or hob, on for 2 of every 5 minutes, or 4 of every 9 | Within 15 % of the true average after 30 minutes. A new cycling load (+2 kW on a 400 W base in the test) reads **long** until its 5th on-minute, about 3x (the first 9 to 10 minutes here), then 1.4-1.5x at 15 minutes and 1.2-1.3x at 20. On a near-0 W base it shows "Holding" until that 5th on-minute. |
| Random kettle-size spikes (5 % of minutes) | About 3 % long (median) while the allowance learns, over its first 4 to 10 hours, then close to unbiased; within 25 % in 95 % of minutes (9 % in the test). A cluster of 5 or more spikes in 30 minutes counts in full as real recent usage. |
| A random 35 %-duty hob | Unbiased; within two window standard deviations in 93 % of minutes |
| Any load on for 5 minutes or more at a time | Counts at once as real usage, so the estimate reads **short**. A single 5-minute 2.5 kW load on 500 W shows about a sixth of the time at worst, and the estimate is back within 10 % 30 minutes after the load started. A 6-on / 6-off or 20-on / 20-off cycle (+1.5 kW on 400 W) reads 13-18 % short on average and swings between about 0.6x and 1.3x of the true time with the cycle. |
| A load in exactly 4 or fewer minutes of every half hour | Clipped; it enters only through the allowance and reads **long** until that has learned. With +2 kW for 3 or 4 minutes of every 30 on 500 W: about 1.4-1.5x for the first half hour (1.7x at +3 kW), 1.2x after 2 hours, about 1.1x after 4 hours. |

## States

| Status | When | Display |
|---|---|---|
| `stale` | Telemetry offline, battery power unavailable, or no successful poll seen for more than 180 s (declared 240 to 300 s after the last poll) | Telemetry stale |
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
- **Warm-up.** After a start, or a gap of more than 5 minutes, the status is "Insufficient data" for 10 minutes. Just after it,
  the window is short and the clipping takes 4 of only 10 to 15 samples: a cycling load already running at the restart behaves
  like a new one for a few minutes (it reads long, or shows "Holding" on a near-0 W base).
- **Long on-phases.** Any load on for 5 minutes or more at a time counts at once. With a heat pump at 20 minutes on, 20 off,
  or a 6-on / 6-off cycle, the estimate swings with the cycle and reads short on average.
- **The 4-versus-5 step.** A load present in exactly 4 or fewer minutes of every half hour is clipped and enters only through the
  3-hour allowance, so it reads long for hours (see the table).
- **After a cycling load ends.** "Holding" returns 8 minutes after the load's last on-minute while the idle reading stays within
  ±60 W. An idle reading that strays beyond ±60 W (for example ±80 W of noise) prevents a sustained idle run, and a time can
  then still be shown for up to about 20 minutes.
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
