# ECCO 3D Energy Flow card

**Status: V2 (perspective-aware routing and card layout, 2026-10-26; animated card connectors and the house feed to the wall light, 2026-10-27; pulsing card links), merged (bundle sha256 `9bf045c2…`) and owner-accepted on the ECCO 3D Preview dashboard. Dashboard 7.23.0 (post-export entry `ovw3`, staged, not live-proven) shows it on the production Overview in place of the 2D Energy Flow card; see [INSTALL_PREVIEW.md](INSTALL_PREVIEW.md) section 6 for upgrading the preview and section 7 for the production placement.** A read-only
Home Assistant Lovelace card that shows the ECCO installation as a premium
fixed-perspective house scene (the owner-approved V4 scene pack: ten
weather and season variants of one house, battery cabinet, wall inverter,
EV charger and pylon) with the live figures and the animated power routes
drawn on top as SVG overlays. Four routes meet at the wall inverter: solar
(yellow, one route per PV array), battery (green, reversing for charge and
discharge), grid (blue, reversing for import and export) and home (cyan).
Pulse speed, density and line thickness follow the live watts; idle,
unknown and stale routes never move. Below the scene sits a compact ECCO
status grid (TOU slot, charge source, target SOC, FE-1 battery runtime,
Free Power, Dump to Grid, health, solar forecast) and a collapsible
diagnostics panel.

The scene variant follows the date (Christmas plates from 1 December to
3 January inclusive), `sun.sun` and the weather entity's condition, using
the pack's own rules (`src/core/scenes.ts`), and changes with a crossfade.
It is ambience only: no value on the card depends on the picture, and the
plates carry no lines, labels or figures. Without a pack the card falls
back to its built-in vector scene. The layout, typography and status panel
follow the approved mockup; the power model is the installed Energy Flow
card's, unchanged.

## Scene pack

```yaml
scene:
  pack: /local/ecco/scenes/     # the ten V4 PNGs (1448 x 1086), a local resource, never a CDN
  crossfade_ms: 900             # optional
  # links: pulse                # optional: card links pulse (default) | particles | "off"
  # force: clear_night          # optional: pin one scene (demos)
  # scenes: { clear_night: night-alt.png }   # optional per-scene override
ecco:
  sun: sun.sun
  weather: weather.forecast_home
```

Overlay geometry is **data** in [`src/scene/routing-v4.ts`](src/scene/routing-v4.ts):
the plate's perspective model, the hardware anchors, the inverter's underside,
the five physical power routes (straight-segment vertex lists) and their
buried stretches, the card placements (desktop and phone), the information
connectors, the bend radius
and the debug-only traces, obstacles, equipment boxes and node names.
`src/scene/iso.ts` turns that data into card boxes and SVG paths;
`src/scene/scene.ts` draws it; the telemetry, motion and status layers never
read it. A Lovelace configuration may override any of it under
`scene.routing` (lists replace, points, placements and links merge per key;
malformed entries are ignored), so the geometry can be revised without a
rebuild and without touching telemetry, animation or control logic:

```yaml
scene:
  pack: /local/ecco/scenes/
  routing:
    cards:
      home: { at: { x: 1060, y: 930 } }          # move one card (its align corner is pinned there)
    info:
      homeInfo: { port: { side: top, at: 0.5 } } # move one connector's port (or pin it: { side: top, x: 1150 })
    power:
      home: [{ x: 978.5, y: 630 }, { x: 978.5, y: 684 }, { x: 968.9, y: 680.3 }] # replace a route (here: a short feed down C1)
    buried:
      battery: []                                # draw the battery whole (default: hidden behind the beds and planters)
    bend: { grid: 4 }
```

A replaced route is drawn whole unless the override also gives its `buried`
stretches; `buried: { battery: [] }` draws the default battery route whole.

**Perspective-aware routing (V2).** The plate is an illustration, not an
exact two-point perspective, so each building axis (X along the inverter
wall, Y along the house side wall and the steps, Z vertical, and the two
roof slopes) is a smooth direction field fitted to the plate's measured edges
([`src/scene/perspective.ts`](src/scene/perspective.ts)). Every route segment
follows one axis at its position, so every bend is a real-world right angle
however it looks on screen, with a small fillet. The routes follow the
plate's own edges (array frames, roof and fascia edges, the chimney, building
corners, the corner downpipe, step nosings and plinths), avoid the surveyed
plants, pots, lights, glazing, doors, furniture and the car, and rise
vertically into the inverter's underside up the five cables painted on the
plate, one gland each. The house feed leaves the inverter from C1's gland,
runs up the inverter's left side, along the garage wall into the internal
corner with the house and along the house wall (between the upper window and
the dining glazing) to the wall light, where it ends: the house is visibly
powered. The battery feed is the one exception to "always in
sight": no drawn route gets from the patio to the steps past the porch bed,
the tiered planters and the path lights, so the battery runs straight on and
is hidden only where it passes behind a surveyed obstacle (the lower-left
bed, the raised bed's corner and path light PL6, the front bed and PL7, the
tiered planters), and drawn everywhere in between, the terrace and step paving
included. The hidden stretches are
not drawn and the particles pass unseen there under a mask, while their timing
follows the whole route, so the flow reads as continuous (debug draws the
hidden stretches dashed). The
connection bar on the underside edge is invisible (debug only), and V1's
junction bar and its status glow are gone (staleness still shows on the status
chip, the stale strip and the dimmed routes); a small glint marks each gland
that carries power. Information
cards sit in open sky, on the blurred foreground shrub and on the road, and
each card's fine dotted link drops or rises from the card, makes one
perspective right angle and ends on its equipment (the last dot is always on
it). `scene.links` picks how it behaves:

- `pulse` (default): no moving parts. While a link's flow carries power, its
  dots breathe, slowly and steadily (one 4.5 s sine shared by every card, so
  they stay in step), and the card's border breathes with them whenever one of
  its own links does (the Solar card with either array's link). Idle, unknown
  and stale links rest faint, grey and still, below the bottom of any active
  breath, so a card without power never outshines one with power; reduced
  motion or `features.animate_flow: false` holds active links steady. On day
  plates the Grid card's border is pale, like its link, so it reads on a blue
  sky.
- `particles`: the dotted link with particles running the way the energy
  travels (Solar card to the arrays; Battery card to the cabinet while
  discharging and back while charging; Grid card to the pylon while importing
  and back while exporting; inverter to the Home card; still mode: chevrons).
- `off`: no links; the cards' colours match their routes. In a YAML-mode
  dashboard an unquoted `off` arrives as `false`, which also means off; any
  other unknown value is refused with an error.

Route particles (and, with `links: particles`, link particles) keep one pace
on every route and link, whatever its length, and carry a dark casing on day
plates so they read on sky, walls and paving. `scene.debug_anchors: true` (preview `?debug=1`; `?routes=1` dims the
plate; `?solo=1` gives a 1:1 scene-only capture at `w=1448`) draws the axes'
traces, obstacles, equipment boxes, the underside line, card boxes and ports,
and every route vertex numbered per route (`B1`, `A1.1`, `G1`, ...) with its
name as a tooltip.

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

Mobile-first: the scene fills the card width (the 1448 x 1086 plate, or the
400 x 470 vector scene); the status grid uses two columns while its column is
narrower than 460 px and three above. Below the status grid sit two
always-visible strips:

- **Live diagnostics**: grid voltage, grid frequency, grid status (connected /
  disconnected), AC and DC transformer temperatures, one instrument row (three
  over two on very narrow cards);
- **Today**: solar, home load, grid import and export, battery charged and
  discharged, and **Solar Share**, the production Overview's definition
  (`today.solar / today.load`, clamped to 0-100 %, `--` without a positive load;
  `test/parity.test.ts` compares it with the Overview card's own formatter).

They use the same entities and formatting as the details panel, which then
leaves those rows out (no duplicates); `features.show_diagnostics_strip` /
`show_today_strip: false` turn a strip off and put its rows back in the panel.
From 760 px the status grid and the strips move to a right-hand column beside
the scene and the collapsible details panel sits under the scene (container
queries, so it follows the card's width, not the window's).

## Build, test, preview

```
npm ci
npm run typecheck
npm run build        # dist/ecco-flow-3d-card.js (deterministic; committed)
npm test             # node:test, 86 tests
npm run preview      # http://127.0.0.1:8765/preview/index.html?s=day-export
```

Preview scenarios (`?s=`): `day-export`, `night-discharge`,
`night-import-charge` (Free Power active), `dump-active`, `idle`, `unknown`,
`stale`, `attention`. `?w=390|430|600|900|1200` sets the frame width;
`&chrome=0` hides the scenario bar. With the scene pack mounted
(`node preview/serve.mjs 8765 <pack folder>`, served at `/assets/`), `?scene=<key>`
pins a scene, `?demo=1` cycles through all ten with the card's crossfade, and
`&links=pulse|particles|off` picks the card-link style (the bar carries it along).
`preview/capture.ps1 -Assets <pack folder> -Scenes <keys>` drives a headless
Chrome/Edge through every scene (and `-Scenarios` through the telemetry
scenarios) at phone and desktop sizes and writes PNGs outside the repository.

The preview loads the real `dist/` bundle and parses `examples/ecco-example.yaml`
itself, so it exercises the same file a user would paste. All mock values are
demonstration data.

## Tests

| File | Covers |
|---|---|
| `parity.test.ts` | sign normalisation, `resolveHomeW`, solar-source handling and motion constants agree with the installed Energy Flow card |
| `flow.test.ts` | direction reversal, connector travel (card -> equipment or back, inverter -> Home card), idle vs unknown, PV total without double counting |
| `motion.test.ts` | speed/density/thickness rise monotonically with watts; idle, unknown and stale never move; one particle pace on every route and connector, connector density by pulse band; the card links' slow shared breath |
| `status.test.ts` | TOU slot (including the midnight wrap), sessions and end-time honesty, FE-1 wording, health roll-up, freshness, daylight |
| `sensorMapping.test.ts` | every example entity exists in the repository; the preview mock covers them |
| `safety.test.ts` | no service/websocket/API calls, no network resources, no action config, no fabricated defaults |
| `geometry.test.ts` | vector scene: pills inside the viewBox and non-overlapping; paths end exactly at their ports |
| `artworkLayout.test.ts` | V4 layout: the perspective model against measured plate edges; every power-route segment on a building axis with real bends; every route starts on its equipment and rises vertically into its own gland on the inverter underside; the house feed runs up beside the inverter and along the house wall onto the wall light; no drawn route crosses a surveyed obstacle, and no route loops or crosses another route; a route is hidden only where it passes behind a surveyed obstacle, every stretch in between is drawn, the particles follow the whole centreline and go in and out of sight in a straight line; each connector stays clear of its own flow's routes and of the obstacles (the battery's rises through the foreground planting its card sits on); cards inside the canvas, off the equipment and each other at every scale; connectors leave their card outward, bend at perspective right angles, cross no other card and end on their equipment; every vertex named; routing data isolated and overridable, malformed or hostile overrides ignored |
| `links.test.ts` | card links: pulse by default, particles and off unchanged; a link breathes exactly while its flow moves and a card border exactly while one of its own links does (never on stale data); one array draws one solar link; `scene.links` reading (YAML false = off) and validation; idle never outshines the bottom of an active breath |
| `scenes.test.ts` | scene rules in the pack's order, the Christmas window, golden hour, URLs under the local pack path |
| `build.test.ts` | byte-identical rebuilds; committed `dist/` matches the sources |

Rendering, animation and interaction are checked in a real browser through
the preview harness (headless capture plus a manual pass), not in node. The
repository's offline suite runs `tools/tests/test_flow_3d_card.py` (folder
shape, read-only allowlist on source and bundle, repository-sourced entity
ids, isolated routing data, site render, the Node suite, scope).

## Installing

The card is a standard single-file Lovelace resource, installed by the same
staged route as the other ECCO cards: copy `dist/ecco-flow-3d-card.js` to
`/config/www/ecco/` under its content hash and the ten scene PNGs to
`/config/www/ecco/scenes/`, add the bundle as a JavaScript-module resource,
and add a card from the example to a dashboard, each step under the owner's
separate authorisation and the deploy-verify-resource read-back gate. The
steps are in [INSTALL_PREVIEW.md](INSTALL_PREVIEW.md), sections 2-7: 2-5 for
the preview dashboard, 6 for upgrading the bundle, 7 for the production
Overview (dashboard 7.23.0: it changes only the dashboard file and needs the
bundle, resource and plates of sections 2-3 already installed, on a production
running 7.22.0 with the other ECCO cards installed). Once 7.23.0 is
installed the resource and plates serve both dashboards. Nothing in this
directory touches a live system.

## Licence

GPL-3.0-or-later, like the other ECCO cards. The bundle embeds Lit
(BSD-3-Clause; see `frontend/LIT-LICENSE.txt`).
