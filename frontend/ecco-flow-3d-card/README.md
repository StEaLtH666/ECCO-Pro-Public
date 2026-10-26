# ECCO 3D Energy Flow card

**Status: offline prototype (v1), not installed.** A read-only Home Assistant
Lovelace card that draws the ECCO installation as an isometric night/day
scene: a house with rooftop PV, the ECCO battery cabinet, the grid pylon and
the inverter as the junction every power path meets, with glowing energy
pulses whose speed, density and thickness follow the live watts. Below the
scene sits a compact ECCO status grid (TOU slot, charge source, target SOC,
FE-1 battery runtime, Free Power, Dump to Grid, health, solar forecast) and a
collapsible diagnostics panel.

The visual direction follows the approved reference mockup
(`design-reference/ECCO_3D_Energy_Flow_Mockup.png`, kept outside this
repository). The power model is the installed Energy Flow card's, unchanged.

## What it reuses

| Concern | Source of truth |
|---|---|
| Battery / grid sign conventions, Home load resolution (`resolveHomeW`), PV aggregation | `frontend/ecco-energy-flow-card` (`src/core/power.ts` mirrors it; `test/parity.test.ts` compares both implementations) |
| Motion curve, idle threshold, pulse-count bands, timing constants | the same card's tuned constants (`src/core/motion.ts`, pinned by the parity test) |
| FE-1 time to reserve (status, range, horizon, summary) | `home-assistant/packages/ecco_battery_runtime.yaml` |
| Free Power / Dump to Grid state, end time, export power, stop SOC | the dongle's own text/binary sensors and the HA schedule status sensors |
| TOU slot table | `ecco_tou_schedule.yaml` start-minute sensors plus the dongle's per-slot SOC / charge / power sensors |
| Solar forecast | `sensor.ecco_solar_forecast_today` / `_remaining` / `_tomorrow` (blend) |
| Health | the ten `sensor.ecco_health_*` subsystem sensors and `binary_sensor.ecco_dump_limits_attention` |

The card is **read-only**: it reads states and dispatches Home Assistant's own
`hass-more-info` event when a pill, tile or row is tapped. It calls no service,
writes nothing, loads nothing from the network and registers no action.
`test/safety.test.ts` enforces this on the source and the bundle.

## Honesty rules

- An unknown or unavailable reading is shown as `--` with a grey dashed path;
  never as 0 W, 0 % or "Idle".
- Idle (below 5 W) is a dim static path; only a known non-idle flow moves.
- When the dongle's telemetry-online sensor is off, or no power reading has
  updated for `stale_after_s` (default 180 s), a strip says so, every path
  stops and the chip turns amber/red. The last values stay visible but are
  labelled as not live.
- Session time left is derived only from the dongle's own "Ends At" time. If
  that reads "end time unavailable", the tile says exactly that.
- The current TOU slot is the one containing the browser's local time in the
  six start-minute sensors (the same slot table the dashboard shows). An
  incomplete table or an invalid schedule gives no slot.
- Battery time to charge target has no ECCO entity; the details panel says
  "Not available" unless `nodes.battery.time_to_target` is configured.
- Day/night is ambience only (from `sun.sun` when configured), never data.

## Configuration

See [`examples/ecco-example.yaml`](examples/ecco-example.yaml) for the full
ECCO configuration. Every entity id in it exists elsewhere in this repository
(`test/sensorMapping.test.ts` checks that). Minimal shape:

```yaml
type: custom:ecco-flow-3d-card
title: Energy Flow
subtitle: Live power overview
nodes:
  solar:
    - { label: Array 1, power: sensor.ecco_clock_dongle_ecco_pv1_power }
    - { label: Array 2, power: sensor.ecco_clock_dongle_ecco_pv2_power }
  solar_total: sensor.ecco_pv_power          # authoritative; arrays shown alongside, never summed on top
  inverter: { power: sensor.ecco_clock_dongle_ecco_inverter_output_power }
  home: { power: sensor.ecco_house_power }
  battery:
    power: sensor.ecco_clock_dongle_ecco_battery_output_power
    soc: sensor.ecco_battery_soc
    power_sign: discharge_positive
    time_to_reserve: sensor.ecco_battery_time_to_reserve
  grid:
    power: sensor.ecco_grid_power
    power_sign: import_positive
    connected: binary_sensor.ecco_clock_dongle_ecco_grid_connected
ecco:
  telemetry_online: binary_sensor.ecco_clock_dongle_telemetry_online
  sun: sun.sun
  # free_power / dump_to_grid / tou / forecast / health: see the example
features:
  animate_flow: true        # off automatically under prefers-reduced-motion (static chevrons show direction)
  show_status_panel: true
  show_details_panel: true
  stale_after_s: 180
```

## Layout

Mobile-first: the scene (400 x 470 viewBox) fills the card width; the status
grid uses two columns below 460 px of card width and three above. From 760 px
the status grid and the details panel move to a right-hand column beside the
scene (container queries, so it follows the card's width, not the window's).

## Build, test, preview

```
npm ci
npm run typecheck
npm run build        # dist/ecco-flow-3d-card.js (deterministic; committed)
npm test             # node:test, 51 tests
npm run preview      # http://127.0.0.1:8765/preview/index.html?s=day-export
```

Preview scenarios (`?s=`): `day-export`, `night-discharge`,
`night-import-charge` (Free Power active), `dump-active`, `idle`, `unknown`,
`stale`, `attention`. `?w=390|430|600|900|1200` sets the frame width;
`&chrome=0` hides the scenario bar. `preview/capture.ps1` drives a headless
Chrome/Edge through every scenario at phone and desktop sizes and writes PNGs
(outside the repository by default).

The preview loads the real `dist/` bundle and parses `examples/ecco-example.yaml`
itself, so it exercises the same file a user would paste. All mock values are
demonstration data.

## Tests

| File | Covers |
|---|---|
| `parity.test.ts` | sign normalisation, `resolveHomeW`, solar-source handling and motion constants agree with the installed Energy Flow card |
| `flow.test.ts` | direction reversal, idle vs unknown, PV total without double counting |
| `motion.test.ts` | speed/density/thickness rise monotonically with watts; idle, unknown and stale never move |
| `status.test.ts` | TOU slot (including the midnight wrap), sessions and end-time honesty, FE-1 wording, health roll-up, freshness, daylight |
| `sensorMapping.test.ts` | every example entity exists in the repository; the preview mock covers them |
| `safety.test.ts` | no service/websocket/API calls, no network resources, no action config, no fabricated defaults |
| `geometry.test.ts` | pills inside the viewBox and non-overlapping; paths end exactly at their ports |
| `build.test.ts` | byte-identical rebuilds; committed `dist/` matches the sources |

Rendering, animation and interaction are checked in a real browser through
the preview harness (headless capture plus a manual pass), not in node.

## Installing later (not part of this prototype)

The card is a standard single-file Lovelace resource. An eventual install
would follow the same staged route as the other ECCO cards: copy
`dist/ecco-flow-3d-card.js` to `/config/www/ecco/` under its content hash,
add it as a JavaScript-module resource, and add a card from the example to a
dashboard, each step under the owner's separate authorisation and the
deploy-verify-resource read-back gate. Nothing in this directory touches a
live system.

## Licence

GPL-3.0-or-later, like the other ECCO cards. The bundle embeds Lit
(BSD-3-Clause; see `frontend/LIT-LICENSE.txt`).
