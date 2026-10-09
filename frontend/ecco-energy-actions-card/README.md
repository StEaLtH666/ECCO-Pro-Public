# ECCO Energy Actions Card

A Lovelace card presenting ECCO's live-proven **Energy Actions** as real product
features - not raw entity tiles. Sits directly beneath the sibling
[`ecco-energy-flow-card`](../ecco-energy-flow-card) in the ECCO Pro Overview
dashboard.

Ships with two tiles:

- **Free Power** - fully interactive, with a **NOW / LATER** selector:
  - **NOW** stages Max Charge Power/Duration, arms the existing write-enable
    switch, starts/ends the existing Free Power firmware feature, and shows
    every transient/recovery state the firmware can report (see "Free Power
    states" below).
  - **LATER** presents the existing Scheduled Free Power Home Assistant
    package (arm/edit/cancel a future session) - see "Scheduled Free Power
    (LATER)" below.
- **Dump to Grid** - Manual V1, fully interactive when `dump_to_grid:` is
  configured (ARM/START/END, Export Power/Stop SOC/Duration staging, the same
  status-driven state machine as Free Power). Implemented and locally
  validated as of 2026-09-26; **not yet live-proven** - see "Dump to Grid"
  below and `docs/DUMP_TO_GRID_V1.md`. Falls back to the original locked,
  non-interactive preview shell when left unconfigured.

## Install

1. Build (or use the committed `dist/ecco-energy-actions-card.js`) and copy
   it to Home Assistant. From the repository root:
   ```powershell
   .\tools\deploy-ha.ps1 frontend\ecco-energy-actions-card\dist\ecco-energy-actions-card.js
   ```
   This lands it at `/config/www/ecco/ecco-energy-actions-card.js` (served as
   `/local/ecco/ecco-energy-actions-card.js`) through the same staged/
   SHA256-verified/backed-up/rolled-back sequence every other ECCO deployment
   uses - see `docs/HA_SSH_DEPLOYMENT.md`.
2. Register it as a Lovelace dashboard resource - **Settings -> Dashboards ->
   Resources -> Add Resource**, URL `/local/ecco/ecco-energy-actions-card.js`,
   type **JavaScript Module**. This step is always manual; no tooling in this
   repository edits Home Assistant's `.storage`.
3. Add a card of type `custom:ecco-energy-actions-card` - see Configuration
   below, or pick "ECCO Energy Actions Card" from the card picker (it
   registers itself via `window.customCards`).

## Why a separate card from Energy Flow

Energy Flow is a live telemetry diagram; Energy Actions is a set of
controls with a real safety model (arm/start/confirm, disabled states,
firmware-authoritative recovery text). Mixing the two would blur "what is
happening" with "what you can do about it" into one card with two very
different responsibilities. They're deliberately independent components -
Energy Actions has no dependency on Energy Flow's source and vice versa -
but follow the same visual language (same `--ecco-*` colour/glow/radius
conventions) so they read as one dashboard.

## Configuration

```yaml
type: custom:ecco-energy-actions-card
title: Energy Actions            # optional, default "Energy Actions"

free_power:
  active: binary_sensor.ecco_clock_dongle_free_power_active
  operation_in_progress: binary_sensor.ecco_clock_dongle_free_power_operation_in_progress
  snapshot_valid: binary_sensor.ecco_clock_dongle_free_power_snapshot_valid
  status: sensor.ecco_clock_dongle_free_power_status
  ends_at: sensor.ecco_clock_dongle_free_power_ends_at
  # Diagnostic counters - independently optional, shown as a small chip row
  # only in the Active state:
  failures: sensor.ecco_clock_dongle_free_power_failures_since_boot
  start_attempts: sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
  start_successes: sensor.ecco_clock_dongle_free_power_start_successes_since_boot
  restore_successes: sensor.ecco_clock_dongle_free_power_restore_successes_since_boot
  write_enable: switch.ecco_clock_dongle_free_power_write_enable
  max_charge_power: number.ecco_clock_dongle_free_power_max_charge_power
  duration: number.ecco_clock_dongle_free_power_duration
  start: button.ecco_clock_dongle_start_free_power_charge_now
  end_restore: button.ecco_clock_dongle_end_free_power_restore_now

# Optional - omit entirely to hide the NOW/LATER selector and the schedule
# banner, leaving the manual (NOW-only) experience exactly as before. Maps
# to the existing, unmodified home-assistant/packages/ecco_free_power_schedule.yaml
# package - this card never duplicates its validation/automation logic.
schedule:
  armed: input_boolean.ecco_free_power_schedule_armed
  start: input_datetime.ecco_free_power_schedule_start
  duration: input_number.ecco_free_power_schedule_duration
  power: input_number.ecco_free_power_schedule_power
  last_result: input_text.ecco_free_power_schedule_last_result
  status: sensor.ecco_free_power_schedule_status
  cancel: script.ecco_free_power_cancel_schedule

# Optional - omit entirely to show the static "Coming Soon" preview shell
# instead. See "Dump to Grid" below - implemented and locally validated as
# of 2026-09-26, NOT yet live-proven on real hardware.
dump_to_grid:
  active: binary_sensor.ecco_clock_dongle_dump_to_grid_active
  operation_in_progress: binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress
  snapshot_valid: binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid
  status: sensor.ecco_clock_dongle_dump_to_grid_status
  ends_at: sensor.ecco_clock_dongle_dump_to_grid_ends_at
  battery_soc: sensor.ecco_clock_dongle_ecco_battery_soc
  failures: sensor.ecco_clock_dongle_dump_to_grid_failures_since_boot
  start_attempts: sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
  start_successes: sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot
  restore_successes: sensor.ecco_clock_dongle_dump_to_grid_restore_successes_since_boot
  write_enable: switch.ecco_clock_dongle_dump_to_grid_write_enable
  export_power: number.ecco_clock_dongle_dump_to_grid_export_power
  stop_soc: number.ecco_clock_dongle_dump_to_grid_stop_soc
  duration: number.ecco_clock_dongle_dump_to_grid_duration
  start: button.ecco_clock_dongle_start_dump_to_grid_now
  end_restore: button.ecco_clock_dongle_end_dump_to_grid_restore_now
  active_export_power: sensor.ecco_clock_dongle_dump_to_grid_active_export_power
  active_stop_soc: sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc
  last_end_reason: sensor.ecco_clock_dongle_dump_to_grid_last_end_reason
  recovery_arm: switch.ecco_clock_dongle_dump_to_grid_recovery_arm
  recovery_force_restore: button.ecco_clock_dongle_dump_to_grid_force_restore_original
  recovery_accept: button.ecco_clock_dongle_dump_to_grid_accept_current_state
  recovery_state: sensor.ecco_clock_dongle_dump_to_grid_recovery_state
  # Optional - the NOW/LATER selector for Dump to Grid, driving
  # home-assistant/packages/ecco_dump_to_grid_schedule.yaml's helpers.
  schedule:
    armed: input_boolean.ecco_dump_to_grid_schedule_armed
    start: input_datetime.ecco_dump_to_grid_schedule_start
    duration: input_number.ecco_dump_to_grid_schedule_duration
    power: input_number.ecco_dump_to_grid_schedule_power
    stop_soc: input_number.ecco_dump_to_grid_schedule_stop_soc
    last_result: input_text.ecco_dump_to_grid_schedule_last_result
    status: sensor.ecco_dump_to_grid_schedule_status
    cancel: script.ecco_dump_to_grid_cancel_schedule
```

`free_power:` is required (the card has nothing to draw without it) and every
sub-field maps directly to one existing Home Assistant entity - see
[`examples/ecco-example.yaml`](examples/ecco-example.yaml) for the real ECCO
installation's entity ids. No entity id is ever hard-coded in `src/`.

### Layouts

`layout:` is optional and presentation-only: it changes no entity mapping
and no service call.

```yaml
type: custom:ecco-energy-actions-card
layout: tabbed        # optional - side-by-side (default) | tabbed
```

- **`side-by-side`** (the default, and what any other value falls back to -
  the card does not reject unknown values) renders both tiles in one grid,
  exactly as before this option existed.
- **`tabbed`** (used by the ECCO Pro Overview) shows one mode at a time:
  - The title row carries a **track strip**: one chip per mode (`Free Power
    · Ready`, `Dump to Grid · Scheduled`, ...) in the same state tones as the
    tiles' own pills. Both chips are always visible, and both modes' display
    states are classified on every render exactly as the tiles do (hardware
    state, then the schedule overlay, then the sibling interlock) - the
    hidden mode is never short-circuited.
  - A **Free Power / Dump to Grid** selector (`role="tablist"`, 44 px
    targets, the NOW/LATER selector's look) picks which mode's full tile
    renders beneath it. The tile itself is unchanged: the same NOW/LATER
    panels, staged sliders, ARM / START / END & RESTORE, banners, recovery
    panel and firmware status line as in the side-by-side layout.
  - **Initial tab:** chosen once, on the first render in which at least
    one mode has a real state, by state priority `recovery_attention >
    deferred > busy > active > armed > scheduled > interlocked > ready >
    unavailable`; a tie goes to Free Power. While both modes are
    unavailable (device offline, entities not registered yet) Free Power
    shows provisionally and the choice waits, so a recovery that surfaces
    on reconnect still wins the first tab. After that only a tap on a tab
    changes it - the card never switches tabs by itself, even when the
    hidden mode's state changes (you may be mid-edit).
  - **Cross-mode alert banner** (not dismissible) directly under the
    selector whenever the hidden mode is **active** (accent), **busy** or
    **deferred** (amber) or in **recovery attention** (red): it names the
    mode, its state label and the firmware's literal status text, with a
    **Show** button that switches to that tab. A hidden mode that is armed,
    scheduled, interlocked, ready or unavailable is announced by its chip
    only. The rules live in `src/trackSelection.ts` (pure, no regex
    literal) and are pinned by `test/trackSelection.test.ts`.
  - **Nothing transfers between modes.** ARM toggles only the visible
    mode's own write-enable switch, START / END & RESTORE press only its
    own buttons, NOW/LATER and staged values stay per mode, and switching
    tabs cancels any pending two-tap End & Restore confirmation of *both*
    modes so a stale "tap again" can never apply to the other one. The
    firmware's own mutual-exclusion preconditions apply unchanged.

## The safety model

Two-step, deliberately never collapsible into one click:

1. **ARM** toggles ONLY `free_power.write_enable` (a switch). This never
   writes the inverter by itself - it's the existing durable write-enable
   gate the firmware itself requires before accepting a start.
2. **START** calls ONLY `free_power.start` (a button), and is disabled unless
   the tile is in the plain **Armed** state - not just "write_enable
   happens to be on", but genuinely idle-and-armed (not active, not mid
   transaction, not in a firmware attention state).

**END & RESTORE NOW** calls ONLY `free_power.end_restore`. It never requires
the arm (ending/restoring is the safe direction) and stays available in every
state except mid-transaction ("busy") or fully unavailable - see "Recovery
presentation" below for exactly when the Recovery Attention state shows it,
under what label, and when it's deliberately withheld. It requires two taps
within four seconds ("End & Restore Now" -> "Tap again to End & Restore",
with a visible shrinking progress bar) purely as a front-end mis-tap guard;
the firmware remains the sole safety authority; nothing here recreates or
bypasses its own validation. The confirmation resets immediately if the
Free Power visual state itself changes mid-window (e.g. it flips to ACTIVE
or a fresh Recovery Attention while "tap again" was showing), so a stale
confirmation can never apply to a different situation than the one the user
actually saw.

Staging Max Charge Power/Duration (the two number entities) is always safe -
editing them never touches the inverter, only what a subsequent Start would
use. **Arm Free Power is single-use**: the firmware itself turns
`write_enable` back off the instant a Start attempt either succeeds or is
rejected (see the `id(free_power_write_enable).turn_off()` calls in both
branches of `start_free_power_override` in
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`) - arming again is
always a fresh, conscious action.

## Free Power states

The tile renders exactly one of seven visual states at a time, resolved by
[`src/freePowerState.ts`](src/freePowerState.ts)'s `classifyFreePower()` -
see that file for the full priority order and the firmware status-text
patterns it matches (`test/freePowerState.test.ts` pins the behaviour against
the actual strings the firmware publishes):

- **Unavailable** - any of the three core entities (active/armed/operation
  in progress) is unavailable/unknown.
- **Recovery Attention** - the firmware's status text says `RECOVERY
  REQUIRED`, `OPERATOR DECISION REQUIRED`, `RESTORE BLOCKED`, `RECOVERY
  BLOCKED`, or contains `FAILED`/a verify `ERROR`/`TIMEOUT`/`REFUSED`. Shown
  as a high-attention (red) panel with the literal firmware text always
  visible. No invented corrective action, no automatic retry.
- **Waiting For Inverter (Deferred)** - status text contains `DEFERRED`
  (e.g. the live-proven `END DEFERRED - Modbus bus busy...` case). Neutral/
  amber, explicitly reassuring ("the watchdog will retry automatically"),
  never issues another command.
- **Working (Busy)** - a transaction is genuinely in flight (`operation_in_
  progress`, or status text starting `STARTING`/`RESTORING`/`ACTIVATION
  VERIFY`). Spinner treatment, all controls disabled.
- **Active** - `free_power.active` is on. Strong green glow; a large hero
  countdown ("time remaining") is the primary visual element, with target
  power and Ends At (parsed from the firmware's `YYYY-MM-DD HH:MM:SS`
  local-time string) demoted to one quiet secondary line beneath it, plus
  the snapshot-valid safety indicator. Since-boot diagnostic counters
  (starts/successes/failures) sit behind a collapsed "Details" disclosure -
  present, but never competing with the countdown for attention.
- **Armed** - `write_enable` is on and nothing else is happening. Amber tint;
  Start becomes enabled.
- **Scheduled** - a purely cosmetic upgrade of the plain **Ready** state,
  shown only once a configured `schedule:` is confirmed armed (see
  "Scheduled Free Power (LATER)" below) - never applied over any hardware/
  safety state.
- **Ready** - the plain idle/safe state.

A status text that doesn't match any of the special patterns above (e.g. a
benign `REJECTED - arm Free Power Write Enable first`, or a settled `RESTORED
OK - ...`) never hijacks the tile into an alarming state - it falls through
to whatever the booleans actually say, with the literal text still shown as a
small note. This is deliberate: a REJECTED start attempt means the system is
still perfectly safe and idle, not that it needs recovery attention.

The firmware status line itself is a quiet, single-line, always-tappable
area (opens Home Assistant's more-info dialog for the status sensor) in
every state that shows one - not just Active.

## Recovery presentation

Recovery Attention no longer offers one generic "End & Restore Now" for
every attention-worthy status. [`src/recoveryPresentation.ts`](src/recoveryPresentation.ts)'s
`classifyRecoveryAction()` refines it using nothing but the firmware's own
`snapshot_valid` boolean and its literal status text (`test/recoveryPresentation.test.ts`
pins every rule against the real firmware strings):

| Firmware situation | snapshot_valid | Presentation |
| --- | --- | --- |
| `OPERATOR DECISION REQUIRED ...` naming End Free Power as the retry | `true` | **Retry End & Restore** (primary) |
| `RECOVERY REQUIRED - saved snapshot found` | `true` | **Restore Saved Settings** (primary) |
| A restore verify step failed but the snapshot was retained (`... snapshot retained ...`) | `true` | **End & Restore Now**, but styled as a quiet secondary action, not the dominant CTA |
| `RECOVERY BLOCKED` / "deliberate recovery required" / "inverter writes locked" | any | **No actionable button at all** - a neutral explanation is shown instead; this will not clear on its own |
| `START FAILED` / an activation write/verify failure | `false` | **No actionable button** - there is no snapshot to restore |
| Anything else attention-worthy | any | Falls back to the original plain **End & Restore Now** (primary) |

No rule here invents a corrective action the firmware didn't already name,
and the top-level state classifier (`classifyFreePower()`) itself is
unchanged - this only refines how ONE already-recovery_attention state
presents its action.

## Scheduled Free Power (LATER)

The LATER tab presents - and never duplicates - the existing
`home-assistant/packages/ecco_free_power_schedule.yaml` package. This card
only stages its `input_number`/`input_datetime` entities and arms/cancels
via its own `input_boolean`/`script`; the package's own validation
automation (`ecco_free_power_schedule_arm_validation`) remains the sole
authority on whether an arm attempt is accepted.

- **Arm Schedule** (`input_boolean.turn_on`) is visually and semantically
  distinct from manual **Arm Free Power** - a violet calendar icon/accent
  versus the amber shield, and a completely different entity/service
  (`input_boolean.*_schedule_armed`, never `switch.*_write_enable`). Arming
  a schedule never touches the manual write-enable switch.
- The schedule banner (date/time, power, duration, a live "starts in"
  countdown, and **Cancel**) renders in **both** the NOW and LATER views,
  but **only once `armed` is the confirmed entity state** - never
  optimistically the instant the arm service call is issued, since the
  validation automation can reject it and turn the boolean back off (its
  outcome is always shown verbatim via `last_result`, e.g. `REJECTED -
  scheduled start must be in the future`).
- While a schedule is armed, its start/power/duration fields **lock** in the
  UI - cancel, edit, then re-arm is the only path, so an already-validated
  schedule is never silently mutated out from under the automation that
  validated it.
- The scheduled power slider's max is clamped to
  `sensor.ecco_free_power_schedule_status`'s `effective_power_limit_w`
  attribute when it's lower than the `input_number` entity's own schema max
  - reusing the site's real configured ceiling rather than a static number.
- The scheduled start uses a plain native `<input type="datetime-local">`,
  not an internal/lazily-loaded Home Assistant frontend element.
- **Hardware/safety states always win**: `src/schedule.ts`'s
  `resolveDisplayState()` can only ever upgrade the plain **Ready** state to
  **Scheduled** cosmetically - Unavailable, Recovery Attention, Deferred,
  Busy, Active and manual Armed are never concealed or reinterpreted by
  schedule state (`test/schedule.test.ts` pins this for every one of those
  states).

## Dump to Grid

Manual Dump to Grid V1 (2026-09-26): battery -> grid export, the sibling of
Free Power (grid -> battery charge). Same two-step ARM/START safety model,
same status-text-driven state machine (`src/dumpState.ts`'s `classifyDump()`,
a mirror of `classifyFreePower()` with one addition: it also takes
`snapshot_valid`, so the tile never shows Ready/Armed while the firmware
still holds a restore obligation - see `test/dumpState.test.ts`), same
two-tap End & Restore confirmation. See [`docs/DUMP_TO_GRID_V1.md`](../../docs/DUMP_TO_GRID_V1.md)
in the repository root for the full design/write-surface/recovery writeup.

**V1.1 (2026-09-26): closed-loop export controller.** `export_power` is now
a TARGET NET GRID EXPORT, not a battery ceiling - the firmware's
`dump_controller_tick` dynamically derives the actual battery discharge
ceiling from measured grid power. This card's config schema and tile are
unchanged by V1.1 (see `docs/DUMP_TO_GRID_V1.md` "Closed-loop export
controller (V1.1)" > "Presentation" - correct control semantics came first,
per the task brief). Two new plain sensor entities exist for anyone wiring
a supplementary display (e.g. a generic entities card) while a richer tile
is designed:

- `sensor.*_dump_to_grid_commanded_battery_ceiling` - the live, dynamically
  adjusted battery discharge ceiling.
- The existing `sensor.*_dump_to_grid_active_export_power` (already wired
  as `active_export_power` above) now reports the fixed target rather than
  the ceiling.

Configuring `dump_to_grid:` (see above) replaces the static preview shell
with the real tile. Omitting it keeps the original static "Coming Soon"
preview - no config, no entities, no `hass.callService` reachable from it at
all - so existing dashboards predating this feature render unchanged.

Same NOW/LATER selector as Free Power (2026-09-26 pre-live hardening):
`dump_to_grid.schedule` maps exactly the helpers
`home-assistant/packages/ecco_dump_to_grid_schedule.yaml` defines. LATER only
stages those helpers and arms/cancels via the package's own input_boolean /
script; at the start time the package stages, arms and presses START, and the
firmware re-checks every safety precondition. The package refuses to arm a
window that overlaps an armed Free Power schedule or a TOU slot with a charge
source set.

While ACTIVE the tile shows the Export Power / Stop SOC **latched at START**
(`active_export_power` / `active_stop_soc`, falling back to the firmware status
text) - never the staged numbers, which can still be edited. When the firmware
reports OPERATOR DECISION REQUIRED (or refuses an Accept), and
`recovery_arm` / `recovery_force_restore` / `recovery_accept` are configured, the
attention panel shows the recovery controls; the firmware still requires the
Recovery Arm and re-checks everything.

Deliberate V1 difference from Free Power, documented in `docs/DUMP_TO_GRID_V1.md`:

- **One extra staged value, Stop SOC** (`dump_to_grid.stop_soc`) - the
  minimum battery percentage Dump to Grid must not intentionally export
  below. Enforced entirely in firmware against the existing trusted battery
  SOC sensor; this card only stages and displays it.

The Active body additionally shows the live trusted battery SOC percentage
(`dump_to_grid.battery_soc`) alongside the countdown, since Stop SOC is a
percentage-based safety floor rather than a duration.

## Architecture

Same pattern as the sibling `ecco-energy-flow-card`: a single-file
LitElement custom card (`src/ecco-energy-actions-card.ts`) plus a portable,
entity-id-free config schema (`src/config.ts`), bundled by esbuild into one
dependency-free `dist/ecco-energy-actions-card.js` - the standard HACS
"plugin" shape, no build step required on the end user's side.

Pure, DOM-free logic lives in four small modules, all unit tested without a
DOM (see `test/`):

- `src/freePowerState.ts` - the seven-state hardware classifier.
- `src/recoveryPresentation.ts` - the Recovery Attention action refinement.
- `src/schedule.ts` - schedule banner/lock classification, the
  hardware-always-wins display-state merge, and every schedule service-call
  mapping.
- `src/utils/time.ts` / `src/utils/format.ts` - local-timestamp parsing/
  formatting and HA state coercion. `utils/format.ts` intentionally
  duplicates a few small formatters from the sibling card's own
  `utils/format.ts` rather than importing across packages: each card bundles
  to one standalone file for HACS, and there is no shared workspace between
  them.

Registers itself via `window.customCards` (same pattern as
`ecco-energy-flow-card`) so it appears in Home Assistant's Lovelace card
picker with a name/description, not just as a raw `custom:` type string.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit, strict mode
npm run test         # node's built-in test runner against src/*.ts directly (Node 22.6+/23.6+ strips types natively - no build step for tests)
npm run build         # esbuild -> dist/ecco-energy-actions-card.js (minified)
npm run watch         # esbuild in watch mode, unminified with inline sourcemaps
```

## License

GPL-3.0-or-later, the licence of the ECCO-Pro project (see the repository's `LICENSE` file).

The built file `dist/ecco-energy-actions-card.js` also contains the Lit library (BSD-3-Clause, Copyright 2017
Google LLC). Its licence notices are kept at the end of that file, and the full Lit licence text is in
`frontend/LIT-LICENSE.txt`.
