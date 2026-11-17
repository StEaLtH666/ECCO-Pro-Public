# ecco-plan-core

The pure, tested core behind ECCO's two master energy-control cards (Charge Battery and Export to Grid). Plain TypeScript, no
dependencies, no bundler, no DOM, no Home Assistant, no I/O. **It returns data only and cannot issue a write.** The Energy
Actions card imports it (stage 2: read-only views; stage 3: guarded override controls) and a Home Assistant package applies the same
rules on the server (stage 3, below). Offline and unreleased: nothing is installed and nothing was written live.

## Modules (`src/`, one concern each)

| File | What it does |
|---|---|
| `time.ts` | minute-of-day helpers, 5-minute grid, clock-change days (23 h and 25 h), elapsed-minute arithmetic |
| `settings.ts` | canonical `PlanSettings` for both actions; source precedence (owner > Intelligence proposal > native observed); durable `revision`; per-field `PROPOSED / ARMED / EXECUTING / APPLIED_VERIFIED / MISMATCH`; the reducer that returns the dependent preview updates; validation (Stop SOC 10-90 is refused, never clamped) |
| `tou.ts` | deterministic compiler from the two actions' schedules plus the owner's native baseline into the six native slots, with feasibility reasons, midnight wrap, DST, merging, an unchanged-native fallback, manual-edit conflict detection, single-writer and lock refusal, per-slot intended-versus-verified state |
| `overrides.ts` | Hold battery, Skip tonight, Prepare for power cut: expiry-bound, raise-only reserve, scheduling only, running lease passed through untouched; the stable refusal codes (`RefusalCode`) |
| `overridePolicy.ts` | the owner's expiry durations, caps and power-cut reserve validated into the `OverridePolicy` (fails closed), hard ceilings, "until local time" expiry choices (clock-change aware), starting under a valid policy, and the owner's accepted limits as data (see "Stage 3") |
| `chargePlanner.ts` | gentle overnight charge: lowest 100 W step that finishes by window end minus the buffer, stress-tested; "buffer too small" is reported, the target is never lowered; labelled "simulated, not measured" |
| `tomorrow.ts` | Tomorrow's Plan model; every number comes from the inputs, a missing one is an explicit "unknown" |
| `guards.ts` | safety checks as functions (Stop SOC, export start under a lock, honest applied claims, compile invariants) |

## Rules the code enforces (each has tests)

- A field reads `APPLIED_VERIFIED` only when a read-back equals it. An unreadable read-back withdraws the claim.
- An external native change is held beside the intended value and must be resolved by the owner; it is never clobbered and never adopted silently. An Intelligence proposal never becomes a value without an owner adoption.
- A compiled plan never has more than six slots. When it cannot fit, or anything is refused or in conflict, the intended table is the owner's native baseline, unchanged, with a stated reason and no edits proposed.
- Single writer: a transaction owner refuses the compile. `controlLocked` (grid-loss design) refuses every export start; anything other than an explicit `false` counts as locked.
- Overrides never lower a reserve or the export floor and never enable anything. Their expiry, caps and the power-cut reserve are passed in as an `OverridePolicy`; this package hard-codes none of them.
- The static tests prove the sources import only each other and contain no DOM, Home Assistant, network, storage, clock, randomness or class/async code.

## Run the tests

Node 24 runs the TypeScript by type stripping (relative imports carry `.ts`). From this directory:

    node --test "test/*.test.ts"

No install step: there is no `package.json` dependency, so no lockfile. `tsconfig.json` type-checks this package alone; `tsconfig.card.json`
type-checks it together with the Energy Actions card (`tsc --noEmit -p tsconfig.card.json`, strict, using the card's TypeScript).
Property tests use a seeded generator, so a failure reproduces. `test/parity/override_parity_cases.json` is the one table the validator
(`test/overrideParity.test.ts`) and the Home Assistant guarded script (`home-assistant/tests/test_ecco_plan_helpers_package.py`) must both
answer the same way. The Home Assistant side has three more suites: `test_ecco_plan_helper_proposal.py`,
`test_ecco_plan_helpers_package.py` and `test_ecco_plan_enforcement.py`.

## Assumptions to confirm (owner decisions)

- Export to Grid is a firmware session today, not a TOU slot. The compiler models it as a no-grid-charge slot whose target
  SOC is the Stop SOC and whose power is the export power, to make its six-slot cost visible. Whether a plan may ever write
  that into the table is a stage-3 question; stage 1 and 2 only display it.
- The export power ceiling is the hardware-tested 3000 W (`LIMITS.exportPowerMax`); raising it needs separate evidence.
- Override expiry defaults, caps and the power-cut reserve are owner choices supplied through `OverridePolicy`. The owner accepted the
  starting limits on 17 Nov 2026 (see "Stage 3"); each stays the owner's to change.
- Baseline slots a derived interval does not cover stay exactly as the owner set them (for example a longer native grid-charge
  slot is not shortened to a shorter derived window); that can cost an extra slot and is then reported as infeasible.

## Stage 2: read-only views in the Energy Actions card (done, offline, unreleased)

The Energy Actions card (`frontend/ecco-energy-actions-card/src/plan/`) imports this package and shows Tomorrow's Plan and the
six-slot TOU timeline behind `show_plan: true` (default off; flag-off render proven identical to the pre-plan card). It only
reads: `adapter.ts` maps the entities the card and the TOU Settings card already read onto `createSettings` /
`compileTou` / `buildTomorrowPlan`; no write, no service call.

What the adapter fed in, and what it could not:

- Charge Battery = the card's Free Power helpers (schedule start, duration, power); Export to Grid = the Dump to Grid helpers.
  Armed schedule -> ARMED; an active session -> EXECUTING; the firmware's latched export power / Stop SOC equal -> APPLIED_VERIFIED,
  different -> MISMATCH. The grid-charge target is read from the single native grid-charge slot. Nothing else is ever verified.
- No entity exists for the charge buffer, the planning reserve, a charge finish time or an override; those are explicit unknowns
  (overrides: an empty list). The backup reserve helper has no read-back, so it stays PROPOSED.
- Tomorrow's Plan comes from the Intelligence advice entities (import = its planned overnight grid charge, export = the export
  event, solar = PV tomorrow, confidence, why); paused, stale or not-OK advice withholds every figure with the reason.
- The grid-loss lock is passed fail-safe (only an explicit "off" on a configured entity is unlocked), so with no lock entity an
  armed export is not placed in the table.
- Live data on the Export-as-slot assumption: the card's Dump to Grid is a firmware session with its own snapshot, restore and
  latched export power and Stop SOC, and the TOU editor treats it as owning the inverter; it is not a table slot. The data
  therefore contradicts "export occupies a slot", so the timeline shows the derived slot as a conservative cost estimate only.

Stage 3 (guarded overrides and their enforcement) is described next.

## Stage 3: guarded overrides and their enforcement (offline, unreleased, NOTHING INSTALLED)

Authorised by the owner on 17 Nov 2026 as offline implementation only: no install, no live write. What exists now:

| Piece | File | Role |
|---|---|---|
| validator | `src/overridePolicy.ts`, `src/overrides.ts` | the rules and the stable refusal codes (`RefusalCode`) |
| helper package | `home-assistant/packages/ecco_plan_helpers.yaml` | the limits, the revision, the override records, the last answer; the two guarded scripts; the first-run seed; two read-only sensors |
| scheduled start | `home-assistant/packages/ecco_dump_to_grid_schedule.yaml` | refuses while an override holds export; raises the Stop SOC to the effective reserve |
| guarded manual start | `home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml` | the card's Start for Dump to Grid, behind the same two checks |
| card | `frontend/ecco-energy-actions-card/src/plan/` | start and cancel controls that can call only those scripts |
| deployment | `deployment/ha-manifest.yaml` | entries for the two new packages (nothing installed, nothing planned) |
| proof | `test/parity/override_parity_cases.json` and the suites below | one table, run against the validator AND the script |

### What is enforced where

| Rule | Enforced by (trusted backend unless noted) |
|---|---|
| Limits confirmed and valid; expiry a whole number of minutes between the shortest and the kind's maximum and under the hard ceiling; no open-ended override; Prepare for power cut refused when the current reserve is unknown or above the power-cut reserve; compare-and-set on the plan revision; refusal = last-answer text + ONE persistent notification + a stable code | `script.ecco_plan_override_start` (its template mirrors the validator; the parity table proves it) |
| Cancel always allowed, ends only its own kind | `script.ecco_plan_override_cancel` |
| No scheduled Dump to Grid start while Hold battery, Skip tonight or Prepare for power cut is active; none while the records or the reserve cannot be read (fail closed, also when the plan package is missing); none when the reserve leaves no room under 90 % | `script.ecco_dump_to_grid_start_scheduled` (BLOCKED result; the script's own end-of-run alert raises the notification) |
| The scheduled session's Stop SOC is never below the effective reserve (rounded up; never lowered) | the same script |
| The card's manual Start: same hold check, same reserve check, then the SAME button press; a staged Stop SOC below the reserve is refused, not changed | `script.ecco_dump_to_grid_start_guarded`, called by the card when `dump_to_grid.guarded_start` is set |
| Effective reserve = the larger of the owner's own reserve and a running Prepare for power cut reserve; raise-only; an unreadable input is skipped, none known = unknown | `sensor.ecco_plan_effective_reserve` |
| Prepare for power cut raises a protected reserve and NEVER charges: neither script calls a charge, discharge, TOU, inverter or dongle service; a battery below the raised reserve stays where it is and the answer says so | static allow-list + a trap test; the card and the plan view show the same sentence |
| What the card offers (default, chips inside the limits, "until 07:00") and that it calls only the guarded scripts | the card (convenience; the server decides again) |

Hold battery also withholds discretionary charge-rate edits. No guarded write path for such an edit exists in the repository (the gentle
planner is pure code that returns proposals; no automation or script writes a charge rate on its own), so there is nothing to bind and
nothing was invented. The rule stays a plan-view fact until such a path exists.

### The owner's accepted limits (the PROPOSED defaults, accepted 17 Nov 2026)

These are the defaults proposed in stage 3 preparation, ACCEPTED by the owner on 17 Nov 2026 ("all configurable within safe limits"). They are
written ONCE, at the first Home Assistant start after the package is installed, by the automation `ecco_plan_seed_accepted_limits` (not
`initial:`, so Home Assistant restores the owner's own values across restarts). Change any of them in its helper, within the helper's own
min / max / step (equal to the validator's bounds). The confirmation switch is NOT seeded: it stays off until the owner turns it on.

| Setting | Key | Helper | Accepted | Why | Trade-off | Hard ceiling |
|---|---|---|---|---|---|---|
| Shortest allowed override | `minExpiryMin` | `ecco_plan_policy_min_expiry` | 15 min | under a quarter hour is almost certainly a mis-tap | a deliberate 10 min hold is refused | |
| Hold battery default | `holdDefaultMin` | `ecco_plan_policy_hold_default` | 240 min (4 h) | covers an evening of extra use without outliving it | a long evening needs a second start | |
| Hold battery maximum | `holdCapMin` | `ecco_plan_policy_hold_cap` | 1440 min (24 h) | a forgotten hold costs at most one night of export | two days needs a restart | 72 h |
| Skip tonight ends at | `skipUntilMin` | `ecco_plan_policy_skip_until` | 420 (07:00 local next morning) | skips tonight's export and the overnight charge, planning resumes before the morning sun | align it to your own morning | |
| Skip tonight maximum | `skipCapMin` | `ecco_plan_policy_skip_cap` | 1440 min (24 h) | a one-night action | none worth stating | 36 h |
| Prepare for power cut default | `cutDefaultMin` | `ecco_plan_policy_cut_default` | 1440 min (24 h) | most warnings and outages are shorter than a day | a long outage needs an extension | |
| Prepare for power cut maximum | `cutCapMin` | `ecco_plan_policy_cut_cap` | 4320 min (72 h) | a raised reserve only costs forgone export | forgetting it costs up to 3 days of export | 7 days |
| Power-cut reserve | `cutReservePct` | `ecco_plan_policy_cut_reserve` | 80 % | hours of essential load while leaving room for solar | below the current reserve it is refused, so raise it with the base reserve | |

### The helpers

One canonical plan: no `PlanSettings` value is copied into a helper. The helpers hold policy, a counter, records and the last answer.

| Entity | Holds |
|---|---|
| `ecco_plan_overrides_enabled` | the owner's "limits reviewed" switch (`confirmed`) |
| `ecco_plan_defaults_seeded` | set by the first-run seed |
| `ecco_plan_policy_*` (eight, above) | the limits |
| `ecco_plan_revision` | the plan revision counter (0 = none yet); written only by the two scripts |
| `ecco_plan_override_hold_battery_start`, `ecco_plan_override_hold_battery_expires` | the one Hold battery record |
| `ecco_plan_override_skip_tonight_start`, `ecco_plan_override_skip_tonight_expires` | the one Skip tonight record |
| `ecco_plan_override_prepare_power_cut_start`, `ecco_plan_override_prepare_power_cut_expires`, `ecco_plan_override_prepare_power_cut_reserve` | the one power-cut record and the reserve it raises to |
| `ecco_plan_last_result` | the last answer of a guarded action (`STARTED ...`, `CANCELLED ...`, `REFUSED CODE - reason`), shown by the card |

One start/expiry pair per kind means at most one active override per kind. A record is active while its expiry is in the future; a
never-started record is the 1970 default, hence expired.

The card reads these entities (`src/plan/helpers.ts`, pure and read only): it shows the limits, the revision, each running override's
expiry and countdown, and reports a malformed record (start not before expiry, longer than the hard ceiling, a power-cut record without a
reserve inside 10-100 %) instead of showing it as active. With none of the entities present the card behaves exactly as before.

### Policy: configurable, bounded, fail closed

- The numbers (minutes, a minute of day, a percent) are validated: finite, whole, on their step, inside `HELPER_BOUNDS`.
- **Hard ceilings** (`EXPIRY_CEILING_MIN`): Hold battery 72 h, Skip tonight 36 h, Prepare for power cut 7 days. No value of any helper lifts a cap above them.
- Each default sits between the minimum and its maximum. Skip tonight's end time may not be between 00:00 and 03:00 (clock changes happen there).
- **Fails closed.** A missing, unconfirmed or invalid configuration returns every reason and no configuration; every start is refused.
- Skip tonight "until 07:00" is the next occurrence, strictly later, in real minutes: an hour shorter on a spring night, an hour longer on an autumn night. The script works it out from Home Assistant's own clock and zone; the card only sends the instruction (`until_local`).
- Stable refusal codes (the validator's and the scripts'): `POLICY_UNCONFIRMED POLICY_INVALID UNKNOWN_KIND EXPIRY_NOT_WHOLE RESERVE_UNKNOWN RESERVE_BELOW_CURRENT EXPIRY_MISSING EXPIRY_BELOW_MIN EXPIRY_ABOVE_CAP EXPIRY_ABOVE_CEILING`, and for the scripts only `UNTIL_NOT_ALLOWED REVISION_UNREADABLE REVISION_CONFLICT NOT_ACTIVE`.

### Intelligence

Intelligence reads a user reserve only through the owner's site mapping `signals.reserve.ha_minimum_soc` (`{entity}`, raise-only). The
effective reserve can be read there WITHOUT changing the eleven-entity contract, the vendor roots or any pinned boundary: map that signal
to `sensor.ecco_plan_effective_reserve` (it carries a `refreshed_at` attribute that moves every minute, so the 600 s freshness limit is met).
That mapping is the owner's own file, so this repository does not change it; it is an owner decision (see below).

### Residuals, stated plainly

1. **The dongle's own Start button entity can still be pressed** from the Home Assistant UI, another card or an assistant, and that press is
   bound by no override. Binding it needs a firmware gate: a flash, a separate approval. The scheduled start and the card's guarded start are bound.
2. The helpers are plain helpers: anyone with Home Assistant administrator access (or an assistant holding it) can write them. The overrides
   protect against ECCO's own starts and the dashboard, not against an administrator.
3. The Free Power start, the card's other start paths and a manual Home Assistant service call are not touched by an override (no override starts or stops a charge).
4. An override never stops a running session: it applies from the next start.
5. The guarded TOU editor's target-SOC floor still reads the owner's own reserve, not the effective one (changing that package needs a new transform layer of its Stage 1 suite).
6. Modelled, not live-proven: the Home Assistant template functions `today_at`, `timedelta` and `as_timestamp`, the helpers' `timestamp` attribute, and the template sensors' once-a-minute refresh. The suites model them (a real zone with clock changes); a supervised check on the owner's version is part of the install.
7. The browser's own zone only decides which choices are OFFERED; the script decides on Home Assistant's clock.
8. The card's own `npm run typecheck` (`tsconfig.json`) cannot cover the plan code, which imports this package outside its `rootDir`; use `tsc --noEmit -p tsconfig.card.json` in this folder. (Changing the card's `tsconfig.json` would need an owner decision to enrol it in the pin chain.)

### Install order for the owner (each step needs its own authorisation; nothing here is installed)

1. Review and merge through the usual route.
2. Install `ecco_plan_helpers.yaml` (restart). The first start seeds the accepted limits; the switch stays off.
3. Look at the eight limits on the helpers page; turn on `ecco_plan_overrides_enabled`.
4. Install `ecco_dump_to_grid_guarded_start.yaml` and the changed `ecco_dump_to_grid_schedule.yaml` (restart). They refuse every start while the plan sensors cannot be read, so step 2 comes first.
5. Copy the rebuilt card bundle (`frontend_assets` entry; resource already registered), clear the browser cache, set `show_plan: true` and `dump_to_grid.guarded_start: script.ecco_dump_to_grid_start_guarded`.
6. Supervised check: start and cancel Hold battery; a scheduled start that must be refused; the manual start refused during an override and accepted after.
7. Optional, after the acceptance run ends: map Intelligence's `reserve.ha_minimum_soc` to `sensor.ecco_plan_effective_reserve` (site check first).

### What is the owner's

Every value above (changeable in the helpers), whether and when to install each step, the Intelligence mapping, a firmware gate for the dongle's
own Start button, and whether to enrol the card's `tsconfig.json` in the pin chain.
