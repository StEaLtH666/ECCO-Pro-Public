# ECCO Energy Flow Card

**Status: live-tested and visually approved.** Deployed as the ECCO Pro
Overview's primary Energy Flow card (dashboard v7.15.0). It is written to
be portable to any Home Assistant solar/battery installation - nothing in
this directory is specific to ECCO except the example file
`examples/ecco-example.yaml`.

A Lovelace card showing a live energy flow diagram - solar, battery, home
and grid arranged around the **inverter as a first-class centre node** -
plus a daily energy-totals strip and an optional secondary panel for
inverter diagnostics (temperature, frequency, grid-connected state, mode).

## Why

Most solar/energy Lovelace cards treat the inverter as an invisible
junction point between solar/battery/grid/home. This card doesn't - the
inverter's own live power, operating state, and (optionally) temperature/
frequency/mode are first-class, visually prominent information, not
buried in an entity's attributes.

## Install (once published)

This is not yet published anywhere. Once split into its own repository:

1. Add it as a HACS custom repository (category: "Frontend" / "Dashboard").
2. Home Assistant Settings -> Dashboards -> Resources -> confirm
   `/hacsfiles/ecco-energy-flow-card/ecco-energy-flow-card.js` was added
   automatically by HACS.
3. Add a card of type `custom:ecco-energy-flow-card` to a dashboard.

For now (prototype review), the built file is at
`dist/ecco-energy-flow-card.js` in this directory - copy it to
`/config/www/` and add it as a manual dashboard resource
(`/local/ecco-energy-flow-card.js`, type: JavaScript Module) to try it.

## Configuration

Every section below is independently optional except that `nodes:` must
contain at least one entry - the card needs *something* to draw.

```yaml
type: custom:ecco-energy-flow-card
title: Energy Flow            # optional

nodes:
  # Single combined solar source:
  solar:
    power: sensor.solar_power
  # OR one entry per independent array/string/MPPT - 1..N, not just two:
  # solar:
  #   - label: Array 1
  #     power: sensor.array_1_power
  #   - label: Array 2
  #     power: sensor.array_2_power
  # Optional either way. With 2+ sources, a small "Solar Total" combiner
  # node is rendered between the array row and the inverter (never required):
  # solar_total: sensor.solar_power_total

  inverter:
    power: sensor.inverter_power     # the one entity that makes the centre node meaningful
    state: sensor.inverter_state     # optional short operating-state text (e.g. "Normal")
    status: sensor.inverter_status   # optional, distinct free-text status

  home:
    power: sensor.home_power

  battery:
    power: sensor.battery_power
    soc: sensor.battery_soc
    power_sign: charge_positive      # or discharge_positive - see "Sign conventions" below

  grid:
    power: sensor.grid_power
    power_sign: import_positive      # or export_positive - see "Sign conventions" below

  generator:                          # entirely optional node - omit the whole block if you don't have one
    power: sensor.generator_power

today:
  solar: sensor.solar_energy_today
  load: sensor.load_energy_today
  import: sensor.grid_import_today
  export: sensor.grid_export_today
  battery_charge: sensor.battery_charge_today
  battery_discharge: sensor.battery_discharge_today

inverter_details:                     # shown in a collapsible "Inverter details" panel, never in the live diagram
  temperature: sensor.inverter_temperature
  ac_temperature: sensor.inverter_ac_temperature   # also shown in the compact strip below the diagram, see below
  dc_temperature: sensor.inverter_dc_temperature   # also shown in the compact strip below the diagram
  grid_voltage: sensor.grid_voltage                # also shown in the compact strip below the diagram
  grid_connected: binary_sensor.inverter_grid_connected
  frequency: sensor.grid_frequency
  mode: sensor.inverter_operating_mode

features:
  self_sufficiency: true    # badge computed from today.import / today.load - see caveat below
  solar_contribution: true  # badge computed from today.solar / today.load
  animate_flow: true        # default true; auto-disabled if the OS/browser requests reduced motion
  compact_today: false      # true = single-row strip instead of a 2-3 column grid
  show_details_panel: true  # default true; false hides the collapsible "Inverter details"
                             # panel - only useful once every field it can show is already
                             # covered by the always-visible quick-metrics strip below

format:
  precision: 2               # decimal places for kW values
  energy_precision: 1        # decimal places for kWh totals
  power_unit: auto           # auto | w | kw
```

See [`examples/generic-example.yaml`](examples/generic-example.yaml) for
every field with inline comments, and
[`examples/ecco-example.yaml`](examples/ecco-example.yaml) for a real
configuration against the ECCO installation this repository maintains.

## Multiple solar arrays

`nodes.solar` accepts either a single object (one combined source) or an
array of objects (one entry per independent array/string/MPPT) - any
count, 1..N, nothing assumes exactly one or exactly two. Each source gets
its own node in the diagram, its own live power figure, and its own
animated line. `label`/`icon` are optional per source; if omitted with 2+
sources, nodes are auto-labelled "Solar 1", "Solar 2", etc.

With exactly **one** source, its line runs straight to the inverter, same
as always. With **two or more** sources, a small "Solar Total" combiner
node is rendered between the array row and the inverter: every array's
line feeds into the combiner, then exactly one line runs from the
combiner to the inverter - never one line per array all the way to the
inverter, which would double-count the generation visually. The combiner
is deliberately smaller/subtler than the inverter, which stays the
dominant node in the diagram. Its displayed value comes from
`nodes.solar_total` when configured (used authoritatively, as-is); if
that's not configured, the card derives it by summing the configured
array readings itself - always a real sum of real entities, never
fabricated.

### Connector routing

Every connection point (inverter, each solar array, the combiner, battery,
home, grid, generator) renders a real, tiny DOM port marker at its own
actual edge. After every layout-affecting render the card measures each
port's real `getBoundingClientRect()` centre (re-measured automatically via
a `ResizeObserver` whenever the card's size changes) and builds every route
directly from those real, live coordinates - never a calibrated inset or a
guessed offset, so a route always terminates exactly at the node's own
rendered edge, at any card width.

Routes are structured horizontal/vertical runs with rounded corners - one
shared radius across the whole diagram, clamped per corner to at most half
of whichever adjoining leg is shorter, so a short jog naturally renders a
tighter curve than a long elbow without a second hand-tuned number - never
a sweeping curve. Battery and Grid each get a short jog onto their own
dedicated lane before entering the inverter; Solar and Home each get one
rounded elbow (as does a fanned-out 3+ source solar array, or the optional
Generator node), both deliberately offset to different heights so the
diagram reads as a designed composition rather than a mirrored cross (see
"Node placement" below).

Flow is shown two ways at once, both scaling with a connection's own live
power on a **logarithmic, heavily low-end-compressed** curve - equal
*multiples* of power read as equal visual steps, not equal absolute watts,
so a 20W trickle reads calm while a multi-kW flow reads obviously more
energetic instead of both looking similarly "busy":

- A moving dash/packet texture on the line itself - sparse and slow near
  idle, a near-continuous bright stream at high power.
- Small glowing "energy balls" riding the same path (one at low power, up
  to four at 6kW+), on their own dedicated timing range distinct from the
  dash texture's - tuned so a low-power flow reads as an occasional packet
  drifting by, never a busy stream.

Idle lines (below a small fixed wattage threshold) show neither dashes nor
balls, just the dim static line. A bidirectional line's physical route
never changes shape when direction reverses (Battery charging vs.
discharging, Grid importing vs. exporting) - only colour and travel
direction do.

### Node placement

The inverter is the diagram's logical hub but is deliberately NOT its
geometric centre - it sits right of centre. Battery, Grid and Home each
occupy their own distinct height and distance from it rather than
mirroring each other around a literal cross/plus shape; the two Solar
arrays remain the one deliberately mirrored pair, feeding down into a
shared PV bus above the inverter. This asymmetric composition is a
position-only concern - every route is still drawn from each node's real
measured port (see "Connector routing" above), so the layout can keep
evolving without a parallel routing model to keep in sync by hand.

## Sign conventions

Inverters disagree about what a positive battery or grid power reading
means. This card never assumes one:

- **`nodes.battery.power_sign`**: `charge_positive` (default - positive =
  energy flowing into the battery) or `discharge_positive` (positive =
  energy flowing out of the battery).
- **`nodes.grid.power_sign`**: `import_positive` (default - positive =
  energy flowing from the grid) or `export_positive` (positive = energy
  flowing to the grid).

Get this wrong and the flow arrows/animation on that node will point the
wrong way - if your battery or grid arrows look backwards, flip the
corresponding `power_sign`.

## Other diagram details

- The inverter's centre figure is captioned **"AC Output"** - it is the
  inverter's own AC throughput specifically, not a total that will sum
  against home/grid/battery figures (those can legitimately not add up to
  it - a real inverter's own losses/behaviour, not a bug in this card).
- The battery node shows three separate lines: label+SOC, live power, and
  Charging/Discharging/Idle status - not squeezed onto one row.
- `features.self_sufficiency` (computed as `1 - today.import/today.load`)
  can be misleading on any installation with a battery, since imported
  energy may have charged the battery rather than covered load directly.
  It remains accurate for a battery-less solar-only installation. Leave it
  off for a battery-equipped site; `solar_contribution` is unaffected by
  this caveat and stays reliable either way.
- `inverter_details.grid_voltage`/`ac_temperature`/`dc_temperature`/
  `grid_connected`/`frequency`, when configured, additionally render as a
  small always-visible compact strip (up to five tiles, wrapping cleanly
  on narrow cards) between the flow diagram and the "Today" totals -
  `grid_connected` gets its own connected/disconnected presentation rather
  than a plain reading. This strip's own five fields render independently
  of `features.show_details_panel` below; the other two fields the
  collapsible panel can show (`temperature`, `mode`, plus `nodes.inverter.status`)
  never appear here, only in that panel.

## State colour and animation

Solar, battery and grid carry restrained, state-aware colour so the
diagram reads at a glance rather than needing the numbers read closely:

- **Solar** (every array plus the Solar Total combiner) uses a warm
  amber/gold accent - a stronger border, a very subtle warm background
  tint, and a soft glow. Near-zero total generation (night, or before
  sunrise) dims it back to a neutral, unlit state automatically, using the
  same idle threshold the flow lines already use.
- **Battery** recolours by live state: green while charging, orange while
  discharging, a subdued neutral grey/blue while idle - applied to the
  line, the node's border, its background tint and its glow. The battery
  card additionally gets a slow (3-4s), gentle animated glow pulse and a
  diagonal shimmer sweep while charging/discharging (direction differs by
  state, suggesting energy flowing in vs. out), plus a matching sheen on
  the thin SOC bar. All of it stops and the card goes fully static while
  idle - no motion without something actually happening.
- **Grid** has five distinct states, driven by the same connectivity
  signal already available via `inverter_details.grid_connected` (never a
  new/invented entity - 0W flow is never itself treated as a fault): cyan/
  blue while **importing**, green/teal while **exporting**, a muted
  steel-blue "**connected, idle**" state at ~0W (still visibly alive, just
  quiet), red for a genuine **disconnected** signal from `grid_connected`
  itself, and neutral grey for **unavailable** (the connectivity signal or
  the power reading itself can't be read - never guessed). The Grid node's
  own pylon graphic gets a smooth breathing glow pulse reinforcing the
  same state (never a hard blink): magnitude-scaled speed while importing/
  exporting, a slow fixed heartbeat while connected-idle, a distinct,
  slightly quicker fixed cadence while disconnected (reads as "alert"
  without ever being frantic), and no pulse at all while unavailable.
- Flow-line **thickness**, the moving dash texture and the energy-ball
  layer (see "Connector routing" above) all scale with live power on the
  same heavily low-end-compressed curve, clamped to a restrained range so
  even the highest end is never frantic.
- Every node with a configured entity is **tappable** - it opens Home
  Assistant's standard more-info dialog for that node's most relevant
  entity (power where available, falling back to state/SOC for the
  inverter/battery). A node with nothing configured for this simply isn't
  interactive.
- All of the above respects `prefers-reduced-motion`: colour/state
  information (including which of Grid's five states is active) is always
  preserved - the dash texture, energy balls and the pylon's breathing
  pulse are all disabled, and the previous static arrowhead reappears in
  their place.

These are implemented as CSS custom properties (`--ecco-line-solar`,
`--ecco-line-home`, `--ecco-line-battery-charge`/`-discharge`/`-idle`,
`--ecco-line-grid-import`/`-export`/`-idle`/`-disconnected`/
`-unavailable`, `--ecco-line-generator`) with sensible built-in defaults,
freely overridable from outside (a theme, or card-mod on this card) -
nothing here assumes an ECCO/Deye installation.
Note for anyone who had already overridden the pre-existing
`--ecco-line-grid`/`--ecco-line-battery-charge`/`--ecco-line-battery-discharge`
variables from an earlier version of this card: `--ecco-line-grid` is now
five variables (`-import`/`-export`/`-idle`/`-disconnected`/
`-unavailable`), and the battery charge/discharge colours themselves
changed meaning (charge is now green, discharge is now orange, matching
the state-colour convention above) rather than being arbitrary
per-direction colours.

## Portability

No entity id anywhere in `src/` is hard-coded. The card only ever reads
whatever entity ids appear in your own YAML configuration under `nodes:`/
`today:`/`inverter_details:`. It works with any inverter/BMS/meter
integration that exposes plain power (W), energy (kWh) and percentage (%)
sensors - Deye/SmartDeye, SolarEdge, Growatt, Victron, or anything else.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit, strict mode
npm run build        # esbuild -> dist/ecco-energy-flow-card.js (minified)
npm run watch         # esbuild in watch mode, unminified with inline sourcemaps
```

## License

GPL-3.0-or-later, the licence of the ECCO-Pro project (see the repository's `LICENSE` file).

The built file `dist/ecco-energy-flow-card.js` also contains the Lit library (BSD-3-Clause, Copyright 2017
Google LLC). Its licence notices are kept at the end of that file, and the full Lit licence text is in
`frontend/LIT-LICENSE.txt`.

Not yet published as a standalone repository - see `DESIGN.md` for the plan to split it out via HACS once the
visual design is approved.
