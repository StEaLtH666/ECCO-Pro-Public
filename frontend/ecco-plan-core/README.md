# ecco-plan-core

The pure, tested core behind ECCO's two master energy-control cards (Charge Battery and Export to Grid). Plain TypeScript, no
dependencies, no bundler, no DOM, no Home Assistant, no I/O. **It returns data only and cannot issue a write.** Nothing in
the repository imports it yet (wiring is stage 2, below). Offline and unreleased: no card, dashboard, package or firmware
file was changed to add it.

## Modules (`src/`, one concern each)

| File | What it does |
|---|---|
| `time.ts` | minute-of-day helpers, 5-minute grid, clock-change days (23 h and 25 h), elapsed-minute arithmetic |
| `settings.ts` | canonical `PlanSettings` for both actions; source precedence (owner > Intelligence proposal > native observed); durable `revision`; per-field `PROPOSED / ARMED / EXECUTING / APPLIED_VERIFIED / MISMATCH`; the reducer that returns the dependent preview updates; validation (Stop SOC 10-90 is refused, never clamped) |
| `tou.ts` | deterministic compiler from the two actions' schedules plus the owner's native baseline into the six native slots, with feasibility reasons, midnight wrap, DST, merging, an unchanged-native fallback, manual-edit conflict detection, single-writer and lock refusal, per-slot intended-versus-verified state |
| `overrides.ts` | Hold battery, Skip tonight, Prepare for power cut: expiry-bound, raise-only reserve, scheduling only, running lease passed through untouched |
| `overridePolicy.ts` | the owner's expiry durations, caps and power-cut reserve validated into the `OverridePolicy` (fails closed), hard ceilings, "until local time" expiry choices (clock-change aware), starting under a valid policy, and the PROPOSED defaults as data (see "Stage 3 preparation") |
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

No install step: there is no `package.json` dependency, so no lockfile. `tsconfig.json` is provided for `tsc --noEmit` once a
TypeScript compiler is available (none was installed when this was written, so the sources are not yet type-checked by `tsc`).
Property tests use a seeded generator, so a failure reproduces.

## Assumptions to confirm (owner decisions)

- Export to Grid is a firmware session today, not a TOU slot. The compiler models it as a no-grid-charge slot whose target
  SOC is the Stop SOC and whose power is the export power, to make its six-slot cost visible. Whether a plan may ever write
  that into the table is a stage-3 question; stage 1 and 2 only display it.
- The export power ceiling is the hardware-tested 3000 W (`LIMITS.exportPowerMax`); raising it needs separate evidence.
- Override expiry defaults, caps and the power-cut reserve are owner choices supplied through `OverridePolicy`. A proposal with
  reasons is in "Stage 3 preparation" below; nothing applies it, the owner decides.
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

What stage 3 (overrides and writes, separately authorised) still needs is listed at the end of "Stage 3 preparation".

## Stage 3 preparation: override policy and the shared plan helper (offline, unreleased, nothing installed)

Done offline and read only. The pieces: `src/overridePolicy.ts` (policy), `proposals/ecco_plan_helpers.proposal.yaml` (the
proposed helper entities, loaded by nothing), `frontend/ecco-energy-actions-card/src/plan/helpers.ts` (reads them when they exist).

### Policy: configurable, bounded, fail closed

- The owner's numbers (minutes, a minute of day, a percent) come from helpers and are validated: finite, whole, on their step, inside
  `HELPER_BOUNDS`. Those bounds are the proposed helpers' own `min` / `max` / `step`, so a helper cannot hold a value the validator
  refuses (a Python test compares them).
- **Hard ceilings** (`EXPIRY_CEILING_MIN`): no value of any helper lifts a cap above them, so no override is open-ended or longer.
  Hold battery 72 h (it only withholds export starts and discretionary rate edits; past three days the forecast it was held
  against is stale). Skip tonight 36 h (a one-night action; covers the next morning on a 25 h clock-change day). Prepare for power
  cut 7 days (a raised reserve costs only forgone export, so it may last longest, but never open-ended). The shortest allowed
  override is above zero (5 to 60 min).
- Each default sits between the minimum and its maximum; a maximum never undercuts the minimum. The power-cut reserve is inside
  `LIMITS.reserveMin..reserveMax` and never below the current backup reserve (equal is allowed: the effect is raise-only anyway).
  Starting Prepare for power cut also needs the current reserve to be known, else it is refused.
- **Fails closed.** A missing, unconfirmed or invalid configuration returns every reason and no configuration, and every start is
  refused with those reasons. The proposed defaults are data for the owner to review (`proposedOverrideConfig()` returns them
  unconfirmed); nothing substitutes them, and the confirmation switch (`ecco_plan_overrides_enabled`, off until the owner turns it
  on) must be on.
- Skip tonight's default is "until its end time" (the next occurrence, strictly later), worked out with the clock-change aware
  elapsed-minute helpers: an hour shorter than the wall clock on a spring day, an hour longer on an autumn day. The end time may not
  be between 00:00 and 03:00 (clock changes happen there). If "until" is beyond the cap (07:05 on a 25 h day) or under the minimum
  (06:50), there is no default and an explicit expiry is needed.
- Expiry chips for the UI (`expiryChoices`): short durations between the minimum and the cap, the owner's default and cap, and for
  Hold battery and Skip tonight "until HH:MM" when within bounds.

### PROPOSED defaults (the owner decides; nothing applies them)

| Setting | Key | Proposed | Why | Trade-off |
|---|---|---|---|---|
| Shortest allowed override | `minExpiryMin` | 15 min | under a quarter hour is almost certainly a mis-tap | a deliberate 10 min hold is refused |
| Hold battery default | `holdDefaultMin` | 240 min (4 h) | covers an evening of extra use without outliving it | a long evening needs a second start |
| Hold battery maximum | `holdCapMin` | 1440 min (24 h) | a forgotten hold costs at most one night of export; the design example is 48 h | two days needs a restart (ceiling 72 h) |
| Skip tonight ends at | `skipUntilMin` | 420 (07:00) | skips tonight's export and the overnight charge, planning resumes before the morning sun | align it to your own morning |
| Skip tonight maximum | `skipCapMin` | 1440 min (24 h) | a one-night action | none worth stating (ceiling 36 h) |
| Prepare for power cut default | `cutDefaultMin` | 1440 min (24 h) | most warnings and outages are shorter than a day | a long outage needs an extension |
| Prepare for power cut maximum | `cutCapMin` | 4320 min (72 h) | the design example; a raised reserve only costs forgone export | forgetting it costs up to 3 days of export (ceiling 7 days) |
| Power-cut reserve | `cutReservePct` | 80 % | hours of essential load while leaving room for solar; the design example | below the current reserve it is refused, so raise it with the base reserve |

### Shared plan helper (PROPOSED, not installed): `proposals/ecco_plan_helpers.proposal.yaml`

Helper entities only (`input_boolean`, `input_number`, `input_datetime`); no script, automation or service call; no `initial:`.
There is still one canonical plan: no `PlanSettings` value is copied here, the helpers hold only policy, a counter and records.

| Entity | Holds | Maps to |
|---|---|---|
| `ecco_plan_overrides_enabled` | the owner's "limits reviewed" switch | gate of `validateOverrideConfig` (`confirmed`) |
| `ecco_plan_policy_min_expiry` | shortest override, 5 to 60 min | `OverridePolicy.minExpiryMin` |
| `ecco_plan_policy_hold_default`, `ecco_plan_policy_hold_cap` | Hold battery default and maximum | `defaultExpiryMin` / `maxExpiryMin.hold_battery` |
| `ecco_plan_policy_skip_until`, `ecco_plan_policy_skip_cap` | Skip tonight end time (time only) and maximum | its dynamic default / `maxExpiryMin.skip_tonight` |
| `ecco_plan_policy_cut_default`, `ecco_plan_policy_cut_cap`, `ecco_plan_policy_cut_reserve` | Prepare for power cut default, maximum, reserve | `defaultExpiryMin` / `maxExpiryMin.prepare_power_cut`, `powerCutReservePct` |
| `ecco_plan_revision` | the durable plan revision counter (0 = none yet) | `PlanSettings.revision` (a counter only) |
| `ecco_plan_override_hold_battery_start`, `ecco_plan_override_hold_battery_expires` | the one Hold battery record | `ActiveOverride` `startedAtMin` / `expiresAtMin` |
| `ecco_plan_override_skip_tonight_start`, `ecco_plan_override_skip_tonight_expires` | the one Skip tonight record | `ActiveOverride` |
| `ecco_plan_override_prepare_power_cut_start`, `ecco_plan_override_prepare_power_cut_expires`, `ecco_plan_override_prepare_power_cut_reserve` | the one power-cut record and the reserve it raises to | `ActiveOverride` with `reservePct` |

One start/expiry pair per kind means at most one active override per kind. A record is active while its expiry is in the future;
never started = the 1970 default = expired. The reader takes the instant from each helper's `timestamp` attribute (to be verified
on the owner's Home Assistant version before any install; if absent the record is reported unreadable, never guessed).

Proposed routing (not built): start and cancel go through ONE new guarded script, never straight at the helpers. It refuses unless the
switch is on and the stored limits pass the same bounds as `validateOverrideConfig` (a template mirrors `HELPER_BOUNDS`, pinned by a
test when it is written), checks the expected `ecco_plan_revision` (compare and set), writes only that kind's start, expiry (and
reserve) records and bumps the revision. Cancel sets the expiry to now. An override can only withhold a start or raise ECCO's own
reserve floor (Stop SOC check, planning reserve); it never writes the native TOU table, never stops a running session and never
lowers a reserve.

Existing files that would have to change to honour an override (none is edited here; each REQUIRES OWNER AUTHORISATION AND A CHAIN
ENTRY, and the pin suites tell which are frozen):

- `home-assistant/packages/ecco_dump_to_grid_schedule.yaml`: the scheduled start script refuses while an override holds export and
  refuses a Stop SOC below the effective reserve (public-manifest file, frozen).
- `frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts`: the manual Dump to Grid Start is a direct press of the
  dongle's start button, so an override does not bind it today. Binding it needs either a guarded script in that path (this card
  file, PEX-pinned) or a firmware gate (a flash: a separate decision, not assumed). The same file would carry the start/cancel controls.
- `frontend/ecco-energy-actions-card/src/config.ts` (PEX-pinned): only if the owner wants helper ids other than the generic ones.
  The read side needs no config. Both card files already differ from their pins because of stage 2; that chain entry is outstanding.
- `home-assistant/packages/ecco_pro.yaml` (frozen) and wherever Intelligence reads the reserve helper (see
  `home-assistant/tests/test_ecco_reserve_default.py`, group 5): they would read an effective reserve (the larger of the helper and
  the running power-cut reserve) instead of the helper.
- `deployment/ha-manifest.yaml`: to install the new helper package and script (a deployment step, separately authorised).
- No change: `ecco_free_power_schedule.yaml` (overrides never start or stop a charge), the native TOU table and the firmware.

### Read side in the Energy Actions card (done, offline)

`src/plan/helpers.ts` reads the proposed entities when ANY of them exists; with none it behaves exactly as before (proved by a
golden of the pre-change plan section). It reads the policy (through the validator, so an unusable policy shows its reasons and the
proposed values for review, never in use), the stored revision and the active records, and the plan view shows each override's
expiry and countdown. Malformed records (start not before expiry, longer than the hard ceiling, a power-cut record without a reserve
inside 10-100 %) are reported and not shown as active. Reading only: no write, no service call, no button. The view takes the clock
only at its entry point (`renderPlanSection(config, states, nowMs?)`, default the real clock) and the card passes none.

### What is decided and what is the owner's

- Decided by the design (not changeable by a helper): hard ceilings, the 5-minute step, whole numbers, raise-only, scheduling only,
  one record per kind, fail closed, the confirmation switch starting off.
- The owner's: every proposed value above, whether to install the helpers, the guarded script and each file in the list above, a
  manual-start gate (card or firmware), and what an unreadable record means to enforcement (here: reported, not honoured).
- Stage 3 still needs: the guarded start/cancel script and its server-side bounds test, the files above, a grid-loss lock entity and
  read-back entities for the reserve and the charge buffer, the owner decision on whether a plan may ever write an export slot, and
  a deliberate post-export (PEX) chain entry for the card's frozen files.
