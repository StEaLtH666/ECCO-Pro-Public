# Derived house load (hd1)

**Status:** offline-validated. Not live-proven until the deployment acceptance test below has been run.

## The problem

The inverter's native load reading (register 178, `sensor.<slug>_ecco_load_power`) reads **0 W** in some inverter states,
notably while the system exports to the grid, although the house is still drawing power. One measured example:
- native load 1350 W before a Dump to Grid lease, and 0.0 W from 14 s into it until the end;
- over the same samples the inverter supplied 2000-3000 W while 667-1773 W went to the grid, so the house drew about
  1.2-1.3 kW.

Two parts of ECCO already resolve this:
- the Energy Flow card's `resolveHomeW()` (`frontend/ecco-energy-flow-card/src/config.ts`);
- the firmware's Dump to Grid feed-forward and feasibility.

Home Assistant did not. `sensor.ecco_house_power` passed the native value straight through, and so did the dashboard
consumers, the House Load Snapshot and the Battery Outlook learning, which therefore learnt 0 W for every exporting interval.

## The rule

The same rule the card and the firmware use, applied to one canonical sensor:

| Native load | Inverter + grid CT | `sensor.ecco_house_power` | `source` |
|---|---|---|---|
| a credible non-zero reading | any | the native reading (never negative) | `native` |
| exactly 0 W | more than 150 W | inverter + grid | `derived` |
| exactly 0 W | 150 W or less | 0 W (confirmed) | `native` |
| exactly 0 W | unavailable | **unavailable** | `none` |
| unavailable / garbage / out of range | available | inverter + grid | `derived` |
| unavailable | unavailable | **unavailable** | `none` |

- **Inverter + grid CT:** the inverter's AC output (register 175; positive while it supplies AC, negative while it charges
  from AC) plus the grid CT (register 172; positive = import), clamped at 0. It is the house load while exporting and while
  charging from the grid alike, so battery and PV need no term of their own. Measured while charging from the grid: grid
  +8149 W and inverter -6785 W gave 1364 W.
- **The one deliberate difference from the card:** a native 0 W that inverter + grid cannot confirm is shown by the card as
  0 W but is **unavailable** here. A canonical sensor that feeds statistics and learning never records an unconfirmed zero.
- **Freshness:** the value is shown only while the telemetry is fresh:
  - the dongle reports telemetry online;
  - the dongle's per-poll text (`sensor.<slug>_last_telemetry_update`, published only after a complete poll) has changed,
    as seen by Home Assistant, within the last 60 s. This is checked every 10 s, so the sensor becomes unavailable 60-70 s
    after the last complete poll.
  - A reconnect that replays an old text does not count.
  - Before the dongle has NTP time that text is not published, so the newest report of the three readings is used instead.
    Readings that stay unchanged for more than 60 s then make it unavailable.
- **Consistency:** the value is recomputed only when a complete poll has landed. A half-published poll (the inverter already
  new, the grid not yet) never mixes two polls; the previous value is held until the poll completes.
- **Unavailable, never 0 W:** stale, unconfirmable or missing data makes the sensor unavailable. Statistics show a gap, the
  dashboard shows the value as not reporting, and the Battery Outlook learning gets no sample.

## The entities

**`sensor.ecco_house_power_model` (new).**
- A trigger-based template sensor in `ecco_canonical_telemetry.yaml`. Its state is the time of the last evaluation.
- Its `model` attribute holds the resolution: value, source, reason, native / inverter / grid / derived W, freshness,
  telemetry age, and the poll text and when it was seen.
- It is always available, so this memory survives a template reload and a restart.
- **It updates every 10 s; consider excluding it from the recorder.**

**`sensor.ecco_house_power` (changed).**
- Same entity, `unique_id`, unit (W), device class (power) and state class (measurement), so long-term statistics continue.
- It now presents the model. It is unavailable unless the model is fresh and updating.
- Attributes: `source`, `reason`, `native_w`, `inverter_w`, `grid_w`, `derived_w`, `telemetry_age_s`, `refreshed_at`,
  `source_entity` (the model), `note`, `sign_convention`.
- Before hd1 it was a plain alias of the native load.

## Consumers changed

| Consumer | Before | After |
|---|---|---|
| `sensor.ecco_house_load_snapshot` (`ecco_pro.yaml`) | native load | `sensor.ecco_house_power` |
| `binary_sensor.ecco_model_inputs_ready` (`ecco_pro.yaml`, the learning gate) | native load available | `sensor.ecco_house_power` available |
| Dashboard: ECCO Today status and runtime blend (Overview, Intelligence) | native load | canonical |
| Dashboard: Rest of Today runtime blend (Intelligence) | native load | canonical |
| Dashboard: Smart Charge Strategy live load (Intelligence, Tariffs, Control, Recommended) | native load | canonical |
| Dashboard: "not reporting" notices, House (Overview, Intelligence, System) | native load | canonical |
| Dashboard: the three House chart series (Overview, Intelligence, System) | native load | canonical |
| Dashboard: Live Energy Flow `essential_power` (System) | native load | canonical |
| Battery Outlook learning (`influxdb/tasks/ecco_battery_outlook_5m.flux`) | 5-minute samples of 0 W included | 0 W samples excluded |

That is 16 dashboard reads in all.

**Unchanged:**
- **The Inverter / Advanced register table** keeps showing register 178 itself (Load Power L1 / L2 / Total).
- **The Energy Flow card** already read `sensor.ecco_house_power` and resolves its home node with `resolveHomeW()`. It now
  receives the derived value directly.
- **FE-1 (battery time to reserve)** reads battery power, not house load, so it is unaffected.
- **The firmware, every inverter write path and the write surface** are unchanged.

## History

- **No historical record is rewritten.** The 30-day Battery Outlook history still holds the 0 W samples of past exports.
  The learning task now only excludes 5-minute samples of 0 W or less when it reads them; the bucket is untouched.
- **Recorder history and long-term statistics** of `sensor.ecco_house_power` before hd1 keep the old native values,
  including the 0 W exports.
- **The other diagnostics** (`influxdb/diagnostics/*.flux`, including the shadow preview) still read the history as stored.
  The canonical-vs-raw comparisons there will now show the derived exports as differences. That is expected.

## Limitations

- **Partial-depression bias.** A 5-minute window that was only partly an export before hd1 was averaged with the 0 W
  readings and is not excluded. Its bias leaves the 30-day learning window within 30 days of deployment.
- **The time-zone dependency.** The Battery Outlook task assumes the same time zone as before; hd1 adds none.
- **The 150 W margin.** It is the card's and the firmware's. A real house load of 150 W or less during a native 0 W is
  shown as 0 W, as in the card.
- **One installation.** This relies on the inverter AC output and grid CT documented for the ECO 8000 (registers 175 and 172).
  An installation with AC-coupled generation outside the inverter would need a further term.

## Deployment and acceptance

The deployment kit (backup, the two packages, the dashboard, the Influx task, rollback and the live acceptance test) is
prepared outside this repository. Acceptance, read-only:
1. `sensor.ecco_house_power_model` exists, updates every 10 s, and its `fresh` is true while telemetry is online.
2. With native load reporting a credible value: `source` = `native`, and the state equals the native load.
3. During an export with the native load at 0 W: `source` = `derived`, and the state equals inverter + grid within a few W.
4. With the dongle offline: `sensor.ecco_house_power` is unavailable within about 70 s.
5. The dashboard's House chart, Today and Smart Charge blocks show the canonical value. The register table still shows the
   native load.
6. The next Battery Outlook task run completes. Its training-day count drops by the excluded 0 W windows.
