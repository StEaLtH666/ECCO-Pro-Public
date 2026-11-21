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
| `gentleController.ts` | read-only controller MODEL for dynamic gentle charging: a recommended charge-power setpoint per tick, capped by the safe ceiling and, with household inputs, by the grid headroom; safe fallbacks, a slew limit, parameter provenance (see "Gentle charge controller model"); never guarantees the target and never actuates |
| `tomorrow.ts` | Tomorrow's Plan model; every number comes from the inputs, a missing one is an explicit "unknown" |
| `guards.ts` | safety checks as functions (Stop SOC, export start under a lock, honest applied claims, compile invariants) |

## Rules the code enforces (each has tests)

- A field reads `APPLIED_VERIFIED` only when a read-back equals it. An unreadable read-back withdraws the claim.
- An external native change is held beside the intended value and must be resolved by the owner; it is never clobbered and never adopted silently. An Intelligence proposal never becomes a value without an owner adoption.
- A compiled plan never has more than six slots. When it cannot fit, or anything is refused or in conflict, the intended table is the owner's native baseline, unchanged, with a stated reason and no edits proposed.
- Single writer: a transaction owner refuses the compile. `controlLocked` (grid-loss design) refuses every export start; anything other than an explicit `false` counts as locked.
- Overrides never lower a reserve or the export floor and never enable anything. Their expiry, caps and the power-cut reserve are passed in as an `OverridePolicy`; this package hard-codes none of them.
- The static tests prove the sources import only each other and contain no DOM, Home Assistant, network, storage, clock, randomness or class/async code.

## Gentle charge controller model (read only, offline, unreleased)

`planGentle(input)` (`src/gentleController.ts`) turns the state at one tick into a recommended charge-power setpoint, as data labelled
`model, not a command`. It lowers the charge power while there is time and raises it when the deadline needs it, so the battery is
planned to reach the chosen target (100 % included) by the deadline (window end minus the finish-early buffer, in real minutes across a clock
change). The setpoint is the **lowest 100 W step** whose forward simulation (pessimistic capacity: the larger of nominal and learned, plus the
band; an assumed BMS taper; a hold at a 100 % target) reaches the target by the deadline, followed by hysteresis, dwell, a slew limit and a
changes budget.

**It does not guarantee the target.** Every decision carries `guarantee: 'NONE'` and the note `NO_GUARANTEE_NOTE`: the target is NOT guaranteed,
100 percent cannot be reached at a fixed rate because the BMS tapers the charge near full and handles the top of charge itself, and the model is
read-only. Nothing actuates: `actuationSupported` is `false` everywhere.

- Never lowers the target, never exceeds the smallest KNOWN safe ceiling (owner maximum, battery maximum charge current x voltage, grid-charge
  current x voltage, configured maximum grid-charge power) or the grid-headroom cap below; none known = `NO_SAFE_CEILING`, no default is
  guessed; unknown or stale SOC = `NO_DATA`.
- Statuses: `OK`, `NOTHING_TO_CHARGE`, `TARGET_AT_RISK` (the highest safe setpoint finishes late, inside the buffer), `TARGET_UNREACHABLE` (not even
  that reaches it before the window ends), `NO_DATA`, `NO_SAFE_CEILING`, `DEADLINE_PASSED`, `INVALID`. At risk and unreachable recommend the highest
  safe setpoint, project the late finish, report the smallest buffer that would absorb it (`suggestedBufferMin`) and say "Buffer too small"
  and "The target is NOT guaranteed"; the target stays.
- A decrease needs the dwell, a saving of at least the hysteresis and a slack to the deadline, and goes down by at most the slew limit per change; an
  increase needed for the deadline is never held back by dwell or hysteresis (a jump over the slew limit is flagged `JUMP_FOR_DEADLINE` and counted).
  A safety decrease (the setpoint in force is above a limit that fell) is never held back by anything. The START is free; every other change draws
  on the per-window changes budget (the write budget a real actuator would need).

### Parameters: value, kind, and what would replace it

One table for every parameter and owner input. Kinds: **PROVISIONAL** = a generic, conservative engineering default, not measured, to be confirmed
by the owner or by measurement; **OWNER_SET** = comes from the owner's settings; **MEASURED_REQUIRED** = the real value is unknown today and must be
measured (the BMS taper curve, the real demand profile). `PARAM_PROVENANCE` carries the same table as data and every decision lists the
provisional ones it used in `provisionalInUse`.

| Parameter | Default | Kind | Meaning | What would replace it |
|---|---|---|---|---|
| `stepW` | 100 W | OWNER_SET | setpoint granularity | the editor's step |
| `minW` | 500 W | OWNER_SET | lowest recommendable setpoint | the editor's minimum |
| `hardMaxW` | 8000 W | OWNER_SET | the editor's maximum; an upper bound, never a stand-in for an unknown ceiling | the editor's maximum |
| `hysteresisW` | 500 W | PROVISIONAL | a decrease must save at least this; a recovering safe limit must rise at least this | the owner's confirmation after watching real nights |
| `dwellMin` | 30 min | PROVISIONAL | minimum real minutes between changes (a deadline increase ignores it) | the owner's confirmation and the actuator's settle time |
| `decreaseSlackMin` | 15 min | PROVISIONAL | a decrease must leave this much slack to the deadline | the owner's confirmation |
| `replanMin` | 10 min | PROVISIONAL | re-plan interval, 5 to 15 | the owner's confirmation and the actuator's cadence |
| `maxChanges` | 6 | PROVISIONAL | setpoint changes per window after the START | the write budget of a proven actuator |
| `maxSocAgeMin` | 15 min | PROVISIONAL | older SOC readings are stale | the real update rate of the SOC sensor |
| `socResolutionPct` | 1 | PROVISIONAL | SOC resolution; the plan starts half of it below the reading | the real sensor resolution |
| `chargeEff` | 0.95 | PROVISIONAL | grid side to battery side (as the static planner) | the measured grid-to-battery energy ratio |
| `taperStartSocPct` | 90 | MEASURED_REQUIRED | BMS taper starts here (full ceiling below) | the BMS taper curve measured over several full charges |
| `taperEndFraction` | 0.15 | MEASURED_REQUIRED | acceptance at 100 % SOC as a fraction of the ceiling, linear from the start | the BMS taper curve measured over several full charges |
| `topHoldMin` | 20 min | MEASURED_REQUIRED | extra minutes reserved after reaching a 100 % target (final taper tail, hold) | the measured time the BMS needs to finish the top of charge |
| `demandMarginPct` | 20 | PROVISIONAL | percent added to the household demand peak | the measured spread of real demand against its forecast |
| `assumedDemandW` | 2000 W | MEASURED_REQUIRED | floor of the demand peak when demand over the window is not covered and the policy is ASSUME_PROVISIONAL (`ASSUMED_DEMAND`) | the measured overnight household demand profile (unknown today) |
| `maxHouseholdAgeMin` | 15 min | PROVISIONAL | demand and solar readings older than this are treated as unknown | the real update rate of those sensors |
| `maxDecreaseStepW` | 8000 W | PROVISIONAL | slew limit per decrease; 8000 W never binds, which keeps the v1 behaviour; the recommended gentle value is 1000 W (`GENTLE_RECOMMENDED_PARAMS`) | the owner's confirmation |
| `fallbackPolicy` | KEEP_CURRENT | PROVISIONAL | what to hold when the plan cannot run: `KEEP_CURRENT`, `USE_STATIC_PLAN` or `NONE` | the owner's choice |
| `unknownDemandPolicy` | ASSUME_PROVISIONAL | PROVISIONAL | unknown demand with a known grid limit: `ASSUME_PROVISIONAL` or `FALLBACK` | the owner's choice |
| `targetSocPct` | owner setting | OWNER_SET | the charge target, 10-100; never lowered by the model | the owner's setting |
| `bufferMin` | 60 min | OWNER_SET | finish-early buffer, 0-120 in 5-minute steps (`GENTLE_DEFAULT_BUFFER_MIN` is the default helpers and tests use) | the owner's setting |
| `gridImportLimitW` | owner setting or unknown | OWNER_SET | the KNOWN safe grid import limit; unknown means no headroom constraint | the owner's or installer's figure |

Unmeasured values are never presented as facts: the decision's `assumptionsLabel` says `assumed, not measured`.

### Household demand, solar and grid headroom (optional)

An optional `household` input group, with `policy` and `staticPlanRateW`. Without it every v1 output is **bit-identical** (a golden-master digest
over 400 closed-loop runs and 4000 random inputs proves it). The setpoint S is grid-side watts, as in v1; the battery receives `chargeEff x S`.
Demand is the household load EXCLUDING the charger (the caller subtracts the present charge draw from a meter reading).

- Grid import = `chargeW / chargeEff + demand - solarUsed` (`gridImportW`), which is `S + demand - solarUsed`.
- The battery-side charge power the grid allows = `chargeEff x (gridLimit - demand + solarUsed)`, never below zero (`batteryHeadroomW`); in setpoint
  units that is `gridLimit - demand + solarUsed`.
- Pessimism: demand = the PEAK of the fresh reading and the forecast profile over the remaining window, plus `demandMarginPct`; solarUsed per
  minute = `min(fresh reading, forecast x confidence)`, and 0 when the reading is unknown or stale, there is no forecast, or no confidence.
  A reading or forecast older than `maxHouseholdAgeMin` is unknown.
- The cap on the setpoint is the least headroom over the remaining minutes, rounded down to a step (`headroomCapW`); the setpoint is at most
  `min(ceiling, cap)` and the decision reports `limitedBy` and the pessimistic `projectedImportW` (never above the limit). The forward projection
  uses the delivered power per minute, `min(setpoint, ceiling x taper acceptance, headroom at that minute)`, not a constant. (For a setpoint inside the cap the headroom is never the smaller term, because the cap is its least value over the window; the term makes the projection honest for any setpoint outside the cap and is covered by its own tests.)
- Unknown grid limit: no headroom constraint is applied, the reason says so (`NO_GRID_LIMIT`), the limit is never guessed. A limit that is not a
  number is `NO_DATA` (`HOUSEHOLD_INVALID`).
- Unknown demand with a known limit (no forecast from now and no fresh reading): `ASSUME_PROVISIONAL` uses `assumedDemandW` as the floor of the
  peak (`ASSUMED_DEMAND`, labelled `assumed, not measured`); `FALLBACK` returns `NO_DATA` (`HOUSEHOLD_UNUSABLE`) and applies the fallback policy.
- Anti-flapping, only in this mode: a highest-safe-setpoint recovery (the cap rises again while the target is already at risk) waits for the
  hysteresis and the dwell like a saving; an increase the deadline can wait for (a raise to the maximum after the dwell still makes it with the
  decrease slack) waits out the dwell (`HELD_DWELL`); an increase that cannot wait, and a fall of the cap (`ABOVE_HEADROOM`), are immediate.

### Fallbacks

When the plan cannot run (SOC unknown or stale, ceiling unknown or below the minimum, household input unusable, no setpoint is safe), the status is
`NO_DATA` or `NO_SAFE_CEILING` as before and `setpointW` stays null: a fallback is never a normal `OK`. `fallback` = `{ applied, policy, setpointW, reason }`:
`KEEP_CURRENT` holds the setpoint in force only while it is within the ceiling AND the grid cap; `USE_STATIC_PLAN` uses the fixed rate the static planner chose
(`staticPlanRateW`), lowered to the ceiling and the cap, never raised; `NONE` recommends nothing. A limit that cannot be checked (unknown ceiling, unusable
household input) means no recommendation, whatever the policy.

**Not supported, and not claimed.** There is no dynamic inverter write. Today's firmware fixes the Free Power rate at START and verifies against it;
a rate change from outside during a lease would block the automatic restore; chains of short leases are possible but not recommended. Applying a
recommended change would need a Free Power rate controller on the Dump V1.1 controller pattern (durable intended-value updates before each write, a write
budget, live proof of the inverter's response, the BMS's live limits and temperature derating, none of which is published). That is out of scope and
unauthorised; the model only says what such a controller would do, and the controller stays READ-ONLY until a protected actuator is designed, reviewed
and proven on hardware. The taper, the efficiency, the demand assumption and the capacity band are assumptions, not measurements.

**Versus the static planner.** `chargePlanner.ts` picks ONE fixed rate and stress-tests it (that is what today's firmware can do). The controller model
re-plans from the measured SOC, so it follows the real taper and capacity instead of a margin chosen in advance. `test/support/batterySim.ts` is the
closed-loop simulator (a true battery that differs from the model, rounded and noisy SOC readings, dips, 23 and 25 hour days; for the household mode also true
demand and solar that differ from the forecast and a physical grid limit that clips the delivered charge) and `test/gentleController.test.ts` prints the
comparison with the static planner and the miss rate when the true demand exceeds the forecast; everything is simulated, not measured. The controller
stops at the **reported** target, so the simulation counts the target as reached within half the reading step plus the noise (the strict count is printed too).

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
| helper package | `home-assistant/packages/ecco_plan_helpers.yaml` | the limits, the revision, the override records (each expiry also as an absolute epoch record), the last answer; the two guarded scripts; the first-run seed; two read-only sensors |
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
| No scheduled Dump to Grid start while Hold battery, Skip tonight or Prepare for power cut is active; none while the records or the reserve cannot be read (fail closed, also when the plan package is missing); none when the reserve is not a finite number from 0 to 100 (`RESERVE_INVALID`: nan, infinity or above 100; `RESERVE_UNKNOWN` when it cannot be read or is below 0); none when the reserve leaves no room under 90 % (`RESERVE_TOO_HIGH`). The hold and the reserve are read at the start AND again immediately before the press, because a run can wait up to 10 minutes for the dongle (offline, or another write in progress): an override started, a record or the reserve becoming unreadable, or a reserve raised above the Stop SOC staged for that run, while it waits, ends that run as BLOCKED with the same codes (`RESERVE_TOO_HIGH` for the staged Stop SOC), nothing pressed, never retried. An override started in the instant between that second read and the press is not seen. Known limitation 20 (fixed on 19 Nov 2026) states that a press-time BLOCKED result is no longer overwritten with STARTED OK when Dump to Grid is active, nor (owner decision r15) a STARTING, FAILED or CANCELLED one, nor does the startup recovery after a Home Assistant restart write STARTED OK over a result this schedule did not verify, and limitation 21 what a momentarily unreadable sensor costs | `script.ecco_dump_to_grid_start_scheduled` (BLOCKED result; the script's own end-of-run alert raises the notification) |
| The scheduled session's Stop SOC is never below the effective reserve (rounded up; never lowered) | the same script |
| Each override's expiry is held twice and read raise-only (owner decision r14, 19 Nov 2026): as the date-and-time record (its `timestamp` attribute) and as an absolute epoch record, an input_number holding the same number of seconds (written first by the start script, and with the cancel instant by the cancel script). The later valid instant wins, so the hold never ends early and is never extended; a kind with either source unreadable is unreadable (the hold reads unknown, which refuses, unless another record holds; the power-cut reserve stays raised); a cancel is refused as NOT_ACTIVE only when every source is readable and none is in the future | `sensor.ecco_plan_export_hold`, `sensor.ecco_plan_effective_reserve`, `script.ecco_plan_override_cancel`; modelled offline, not live-proven (known limitations 11, 17, 19 and 23) |
| The card's manual Start: same hold check, same reserve check, then the SAME button press; a staged Stop SOC below the reserve is refused, not changed; a reserve that is not a finite number from 0 to 100 is refused (`RESERVE_INVALID`) and so is a staged Stop SOC read back as anything but a finite number from 0 to 100 (`STOP_SOC_UNREADABLE`) | `script.ecco_dump_to_grid_start_guarded`, called by the card when `dump_to_grid.guarded_start` is set |
| Effective reserve = the larger of the owner's own reserve and a running Prepare for power cut reserve, each rounded UP to a whole percent (62.4 is published as 63, so with the owner's reserve readable it is never below it); an unreadable input is skipped (the other value stands), except that the power-cut reserve is also kept while ITS EXPIRY cannot be read (fail closed since owner decision r14, 19 Nov 2026: it counts until a cancel or a readable record reconciles it, when its stored value is a number from 10 to 100); none known = unknown. It is the reserve ECCO's own plan uses, not an inverter setting | `sensor.ecco_plan_effective_reserve` |
| Prepare for power cut sets the reserve ECCO's plan uses (the row above) and NEVER charges: neither script calls a charge, discharge, TOU, inverter or dongle service. It does not change the inverter's own reserve or any inverter setting and does not stop the house using the battery; a battery below that reserve stays where it is and the answer says so | static allow-list + a trap test; the card and the plan view show the same sentence |
| What the card offers (default, chips inside the limits, "until 07:00") and that it calls only the guarded scripts | the card (convenience; the server decides again) |

**What an override does, and does not do.** Hold battery, Skip tonight and Prepare for power cut gate ECCO's own scheduled Dump to Grid start
and the card's guarded manual start, and nothing else. Prepare for power cut also sets the reserve ECCO's plan uses
(`sensor.ecco_plan_effective_reserve`: the larger of the owner's reserve and a running power-cut reserve, each rounded up). The trusted
backend (a) refuses the scheduled start and the guarded start when that reserve cannot be read or is not a finite number from 0 to 100, and
when it is too high for the Stop SOC (the scheduled start: no room under its Stop SOC limit; the guarded start: the Stop SOC staged on the
dongle is below it), and (b) raises the Stop SOC the scheduled start stages to at least that reserve. An override does NOT change the
inverter's own reserve or any inverter setting, does NOT stop the house using the battery, does NOT stop the battery charging or
discharging, does NOT charge the battery, and does NOT bind the dongle's own Start button (the known unresolved limitation, RG-ST3, below). What else is known and not fixed is under
"Known limitations (stated, not fixed in this change)" below.

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
| `ecco_plan_override_hold_battery_expires_epoch`, `ecco_plan_override_skip_tonight_expires_epoch`, `ecco_plan_override_prepare_power_cut_expires_epoch` | the ABSOLUTE expiry record of each kind (owner decision r14): the same expiry as epoch seconds (an input_number, min 0, max 4102444800, step 1, box, no `initial`), written only by the two guarded scripts, read together with the date-and-time expiry (the later valid instant wins). The card reads them too (owner decision r15): see known limitation 23 |
| `ecco_plan_last_result` | the last answer of a guarded action (`STARTED ...`, `CANCELLED ...`, `REFUSED CODE - reason`), shown by the card |

One start/expiry pair per kind means at most one active override per kind. A record is active while its expiry is in the future (in either of its two
sources: the date-and-time expiry or the absolute epoch record, the later valid instant winning); a never-started record is the 1970 default and a fresh
epoch record is 0, hence expired.

The card reads these entities (`src/plan/helpers.ts`, pure and read only): it shows the limits, the revision, each running override's
expiry and countdown, and reports a malformed record (start not before expiry, longer than the hard ceiling, a power-cut record without a
reserve inside 10-100 %) instead of showing it as active. With none of the entities present the card behaves exactly as before. Since owner decision r15 it reads the absolute
epoch records too and mirrors the backend's read rule (known limitation 23, fixed on 19 Nov 2026 by owner decision r15): a running override is placed on the later valid instant, a kind whose record
cannot be read is shown as held by Home Assistant, both with the guarded Cancel, and a cancel is read back (revision and both records) before it is called confirmed.

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

**Stated limitation.** Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).

1. **The dongle's own Start button entity can still be pressed** from the Home Assistant UI, another card or an assistant, and that press is
   bound by no override. Binding it needs a firmware gate: a flash, a separate approval. The scheduled start and the card's guarded start are bound.
2. The helpers are plain helpers: anyone with Home Assistant administrator access (or an assistant holding it) can write them. The overrides
   protect against ECCO's own starts and the dashboard, not against an administrator.
3. The Free Power start, the card's other start paths and a manual Home Assistant service call are not touched by an override (no override starts or stops a charge).
4. An override never stops a running session: it applies from the next start.
5. The guarded TOU editor's target-SOC floor still reads the owner's own reserve, not the effective one (changing that package needs a new transform layer of its Stage 1 suite).
6. Modelled, not live-proven: the Home Assistant template functions `today_at`, `timedelta` and `as_timestamp`, the helpers' `timestamp` attribute, an input_number restoring an exact epoch after a restart, and the template sensors' once-a-minute refresh. The suites model them (a real zone with clock changes); a supervised check on the owner's version is part of the install.
7. The browser's own zone only decides which choices are OFFERED; the script decides on Home Assistant's clock.
8. The card's own `npm run typecheck` (`tsconfig.json`) cannot cover the plan code, which imports this package outside its `rootDir`; use `tsc --noEmit -p tsconfig.card.json` in this folder. (Changing the card's `tsconfig.json` would need an owner decision to enrol it in the pin chain.)

### Known limitations (stated, not fixed in this change)

An independent review on 18 Nov 2026 found the items below, and a second review of the fixes (the same day) added items 19 to 22; the owner decision of 19 Nov 2026 (r14) added
item 23. The fixes for the clock-change
day, the press-time recheck, the rounded-up reserve and the five surviving mutants are in. The items here were NOT fixed, except item 20 (fixed on 19 Nov 2026 by owner
decisions r14 and r15, and kept in the list with what changed) and item 19 (mitigated offline the same day by an absolute epoch record, and kept in the list with what is still unproven), and item 23 (the card; fixed offline on 19 Nov 2026 by owner decision r15,
and kept in the list with what is not claimed). Item 10 was EXAMINED offline on 19 Nov 2026 (owner decision r15) and updated on 20 Nov 2026 (owner decision r30): it is kept in the list with its findings;
two of its proposals, P-A (the refusal of a skipped, repeated or unreadable start label at arm time) and P-B (the arm-time TOU overlap walk on the real instants),
are implemented offline in R9 (not installed), that is not verified on a real Home Assistant, and everything else in it is unchanged. All the items are written down so that nobody
reads more into the overrides than they do. "Fail open" means the override protects less than its name suggests; "fail closed" means a start is refused or held.
None was seen on a live Home Assistant. Unless an item says otherwise it was read from the code and the offline models; items 9, 10 and 19 to 23 say, in their
own text, what was reproduced offline, what was only reasoned or recalled, and what was not examined. Items 13 to 18 are smaller or informational.

1. **An unreadable input falls back to the other value in the effective reserve.** With the owner's reserve unreadable while a power cut runs, the power-cut
   reserve alone stands, which can be lower than the owner's own reserve (never lower than the power cut's own reserve). With the power-cut record unreadable
   while it runs, the power-cut reserve is RETAINED since owner decision r14 (19 Nov 2026; fail closed, until a cancel or a readable record reconciles it, when its
   stored value is a number from 10 to 100); before r14 the owner's reserve was published instead. Direction: fail open for that one number (the owner's reserve unreadable;
   the hold reads held or unknown, so a scheduled or guarded
   Dump to Grid start is still refused); fail closed for the unreadable power-cut record. You would see: a lower number on the effective reserve sensor than you expect, and an outside reader of the sensor
   sees the lower number too.
2. **Raise-only is compared with the owner's reserve only, not with a running power cut.** Starting Prepare for power cut again after the policy was changed
   is accepted if the new power-cut reserve is not below the owner's reserve, and it can lower the running power-cut reserve and shorten the override to the new
   length. "An override never lowers a reserve" is true against the owner's reserve only. Direction: fail open. You would see: the effective reserve sensor
   fall and a new expiry on the running override.
3. **Start and cancel can interleave.** They are two separate scripts, each decides first and then writes in several steps, so a start and a cancel issued at
   the same moment can write interleaved records and both bump the revision (a lost update). A second call of the same script while it runs is dropped with
   only a log warning, and the card's last answer then still shows the earlier answer. Direction: either way (an override can stay active after a cancel, or be
   cancelled after a start). You would see: a record that does not match what you pressed, or a stale last answer; check the card and press again.
4. **The guarded start does not handle a failed press and writes no success text.** It dismisses the blocked notification and then presses; if the press
   fails, the last result keeps its old text and no alert is raised. It does not check that the dongle is idle (the firmware owns that). Direction: fail closed
   (nothing started). You would see: a stale last result and no start.
5. **The card's own Start button is unguarded unless `dump_to_grid.guarded_start` is configured.** Without it the card presses the dongle's Start button
   directly, while the same card shows Hold battery as active. A configured guarded start can be any script id from the dashboard configuration (an
   administrator-controlled setting). Direction: fail open. You would see: Hold battery shown as active and Start still working from the card.
6. **An override's start time is floored to the minute.** It can last up to 59 s less than asked. Direction: fail open by up to 59 s. You would see: an
   override ending a few seconds early.
7. **The first-run seed marker is a plain helper.** Clearing it, or losing its restored state, re-seeds the accepted limits at the next Home Assistant start
   and overwrites your own values (the confirmation switch is never touched). After a package reload without a restart the limits sit at their minimums and the
   policy reads invalid, so every start is refused. Direction: your limits are replaced by the accepted defaults, which may be wider or narrower than yours (the
   invalid case fails closed). You would see: your limits changed back, or refusals saying the policy is invalid until the next restart.
8. **The reserve sensor's `owner_reserve` attribute rounds half to even.** The state is what consumers read, and the state is rounded up. Direction:
   informational (no effect on a start). You would see: an attribute that can read a whole percent lower than the state.
9. **A reserve strictly between 0 and 0.0001 (printed in exponent form): a failure was suspected and was NOT reproduced.** The first version of this item said
   that such a reserve reads as unreadable and starts are refused; that was written from a task text and had not been run. Run now against the current
   packages and simulators: the owner's reserve helper set to 5e-05, 1e-05, 0.00005, 0.0001, 1e-300 or 4.9e-324 is read as a number by the effective reserve
   sensor (`float()` accepts exponent text) and published rounded up as 1; the scheduled start then stages the larger of the asked Stop SOC and 1, and the guarded
   start presses; the same when 5e-05 is forced onto the effective reserve sensor or onto the staged Stop SOC read-back. The `owner_reserve` attribute reads 0
   (item 8). Reasoned, not examined: how real Home Assistant renders and parses a tiny number that a template hands on as text. The effective reserve sensor
   publishes whole numbers only, so a tiny number reaches a script only through a forced test value or a tiny staged Stop SOC on the dongle's own number. Direction:
   unknown until checked in real Home Assistant (no failure was reproduced offline). You would see: nothing, in the model.
10. **The schedule packages' start-time reads on the clock-change day: two proposals of the 19 Nov 2026 examination (P-A and P-B) are implemented offline in R9 (owner decision r30, 20 Nov 2026); that is not verified on a real Home Assistant, and the rest is unchanged.**

    Method of the examination (owner decision r15): limitation 10 was EXAMINED offline on 19 Nov 2026 with a zone-aware (Europe/London) harness that ran the packages' own
    template expressions and the repository's simulators on 28 Mar 2027 (spring forward: the local hour 01:00 to 01:59 does not exist), 31 Oct 2027 (fall back: that hour
    happens twice) and the past 25 Oct 2026, each with an ordinary-day control. On 20 Nov 2026 (owner decision r30) R9 was merged into this branch and implements two of the
    proposals of that examination, offline. The parts below are kept apart on purpose: (a) IMPLEMENTED OFFLINE in R9, (b) NOT VERIFIED ON A REAL HOME ASSISTANT, (c) NOT
    CHANGED by R9, (d) what you would see.

    (a) IMPLEMENTED OFFLINE in R9 (owner decision r30, 20 Nov 2026; not installed on any Home Assistant). P-A (refuse a skipped, repeated or unreadable start label at arm
    time) is implemented offline in both schedule packages: arming now refuses a start time that is a skipped local time, a repeated one or one that cannot be read, with
    the text "REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time", BEFORE "must be in the future", so arming in the
    second 01:xx hour for a 01:xx start is still refused (fail closed) but now with that text and no longer with a misleading one. P-B (an epoch-correct TOU walk or a
    refusal when the window spans the change; R9 chose the walk) is implemented offline in the Export to Grid package only: its arm-time TOU overlap check now walks the run
    on the real instants (each minute of the run is converted to its local time of day), so a window that crosses a clock change checks the slots it really covers, and a
    minute whose local time cannot be read refuses the arm (both only when the TOU slot table can be read: see (c)); the Charge Battery (Free Power) package has no such check.
    What the offline proof is, and that it is only that:
    the repository's own simulators run the real package text under the real Europe/London zone; an independent oracle (every real UTC minute of each change day walked,
    counting how often each wall-clock label occurs) is compared with the real arm validation label by label (each of the 1440 wall-clock minute labels of a day is armed once
    and its answer compared with the oracle's count), for both packages and under both readings of a naive local
    string: exactly the 60 skipped or repeated minutes of 28 Mar 2027, 31 Oct 2027 and 25 Oct 2026 are refused with the clock-change text and none on an ordinary day; the
    TOU walk is compared with an independent truth over every quarter hour around those days and two ordinary days; the new checks fail on the unchanged packages
    (failing-first) and mutants of both changes are killed (registry/tests/test_ha_r9_missed_runs.py [5]; with a Hold battery running,
    home-assistant/tests/test_ecco_r9_stage3_composition.py [19]). That is an offline proof of the offline model only, not a test on a real Home Assistant.

    As examined on 19 Nov 2026, before R9, these two were NOT fail closed, as reproduced then: a start time typed as a skipped or repeated local label was read as the first
    reading of that label and was not refused (a skipped 01:30 starts at 02:30 BST (60 minutes later than typed, while the ARMED text still shows 01:30) and a repeated
    01:30 starts once, at its first occurrence), and the TOU overlap check of the Dump to Grid arm validation walked the window as continuous wall-clock minutes, so on the
    spring day a run that spans the gap could miss an overlap with a charging slot after it (a false accept) and on the autumn day a clear window could be refused (a false
    refusal). Arming in the second 01:xx hour for a time inside it was already fail closed but was refused with a misleading text ("must be in the future").

    (b) NOT VERIFIED ON A REAL HOME ASSISTANT (and NOT EXAMINABLE offline): how Home Assistant's template functions read a naive local time (the first occurrence of a
    repeated time, the offset in force before the change for a skipped one) and which time zone they use are recalled, not verified (the offline suite models both readings
    of a repeated time and the check refuses a repeated time on either one); the real Home Assistant time-trigger rule; whether its process time zone equals the configured
    zone for the naive-string read; whether a date-and-time helper accepts a skipped time; its restore after a restart (item 19); and the dongle's timers and TOU gate
    across a clock change. P-F (a supervised read-only template check of the three conversions on the owner's Home Assistant) is still open: until it is done, everything in
    (a) stays not verified on a real Home Assistant.

    (c) NOT CHANGED by R9: the dongle firmware's START gate is not changed (a flash is a separate decision) and, read from its text (reasoned from the code, not run), still
    walks the TOU window the old way, as continuous wall-clock minutes, so it does not follow the real instants: on the spring day the arm-time check of (a) is the only one
    that sees a charge slot after the skipped hour. The checks of (a) run only when the schedule is armed (the arm validation is triggered by the armed switch turning on
    and by nothing else): a start helper edited while the schedule is armed is not checked again. The TOU walk of (a) runs only when the TOU slot table can be read (each of the
    six slots needs a time that reads as hours and minutes and a charge source that is not unknown, unavailable or empty): when it cannot, the package does not walk the window
    at all, this check does not refuse the arm, and the firmware's own START gate is then the only gate for a TOU overlap (it still walks the old way, as said above); the
    offline suite pins that an unreadable slot table does not refuse the arm. Whether an unreadable TOU slot table should fail closed stays an open question for the owner and is
    not decided here. The repeated-time probe shifts the label by a constant one hour: right for
    the UK clock change only, not for a zone that changes by another amount, and only Europe/London was modelled. EXACT (reproduced), unchanged: every window end, retry
    deadline, run length and plan override expiry is epoch arithmetic, so no deadline is silently extended or shortened, nothing starts twice, and restarts around the
    change behave in epoch terms. FAIL CLOSED (reproduced) and unchanged: a Home Assistant start in the second 01:xx hour is never captured for R9 (the dongle's time text
    has no offset), so for that boot the missed-run guard fails closed and the watchdog does not rescue a lost on-time start; Skip tonight pressed 07:00 to 07:59 on the day
    before the autumn change is refused (EXPIRY_ABOVE_CAP, a 25 hour night). An override expiry in the repeated hour is covered by item 19. The Free Power schedule package
    behaves identically in each unchanged finding; it has the same P-A refusal and no TOU overlap check.

    (d) Direction: mixed, as listed. You would see: a start that fires an hour away from the label typed on a change day, or a refused or MISSED run that was in fact fine,
    for as long as R9 is not installed (today); with R9 installed (offline only so far), arming a start time in the skipped or repeated hour refused with the clock-change
    text and the schedule switched off, and a Dump to Grid window that crosses the change checked against the slots it really covers (when the TOU slot table can be read),
    while the firmware's own gate, a start
    helper edited after arming and the unchanged findings above stay as they are. The next clock change is 28 Mar 2027.

11. **The expiry read uses the helper's `timestamp` attribute, which is modelled, not live-proven.** The offline models set it from an aware datetime and treat it
    as the true instant, also in the repeated hour of the autumn clock change; real Home Assistant was not checked (how the attribute is held after a restart is item
    19). A supervised check is needed. Since owner decision r14 (19 Nov 2026) the attribute is only one of two sources: each expiry is also an absolute epoch record (an
    input_number, item 19) and the two are read raise-only, the later valid instant winning, so a missing, wrong or early attribute can no longer release an override that
    the epoch record shows as running, and a missing, reset or unreadable epoch record can no longer release one the attribute shows as running. Direction: unknown until
    checked (a missing or non-numeric attribute is read as an unreadable record: the hold reads
    unknown, which refuses, unless another record holds; that is stricter than the earlier state-string read, which accepted a valid state that had no attribute). You would
    see: with the attribute missing, the hold unknown and starts refused.
12. **The press-time recheck is not atomic.** The scheduled start reads the hold and the reserve a moment before the press (the guarded start one action
    before it); an override started in those milliseconds is not seen. Direction: fail open for those milliseconds. You would see: a start that goes through
    although an override began a moment earlier.
13. **The package accepts a few input shapes the TypeScript validator refuses.** An empty length reads as the default, a numeric string such as `1e3` or
    `15.0` is accepted, and a kind with spaces or capitals is normalised. Every limit still applies and the card sends numbers only. Direction: neutral (shape
    only; no way round a limit). You would see: nothing from the card.
14. **Hold battery's "no discretionary charge-rate edits" binds nothing.** No guarded write path for such an edit exists, so it is a plan-view fact only (stated
    under the table in "What is enforced where"); the card no longer lists it as an effect. Direction: fail open (nothing to bind). You would see: nothing; an
    override never edits a rate.
15. **A run stopped by the press-time recheck has already staged its numbers.** The staged numbers were written and the write enable is turned off again;
    nothing was pressed, and a STARTING text shows for up to 5 s before the BLOCKED text. Direction: fail closed. You would see: the staged numbers changed on
    the dongle with no start, then a BLOCKED answer and one notification.
16. **The confirmation switch gates only starting an override.** Cancel, the hold sensor and every Dump to Grid start do not read it, so an override already
    running keeps holding exports when the switch is turned off. Direction: fail closed. You would see: the hold still active with the switch off.
17. **Modelled, not live-proven in real Home Assistant:** the time functions the templates use, the round-up filter, whether a service call to set a number
    enforces the helper's step, the default value of a date-and-time helper and how overlapping script calls are handled; and, since owner decision r14, whether an
    input_number restores an exact ten-digit epoch after a restart, whether `input_number.set_value` accepts a value that large, and how the template filters of the
    epoch read (`float(none)`, `reject('none')`, `max`) behave; and, as recalled, a service call that writes a helper that is missing or not loaded is only a logged
    warning in Home Assistant, so a start or cancel script could still write STARTED or CANCELLED while that record stays unreadable (the result text then over-reports;
    the hold stays unknown and the raised reserve stays, fail closed). Direction: unknown until checked.
    You would see: nothing until a supervised check on the owner's version, which is part of the install.
18. **What Intelligence does with the effective reserve depends on the owner's own site mapping.** This repository does not change that file and the review
    did not read it; it matters only if the owner maps the reserve. Direction: not applicable. You would see: nothing unless the mapping is set.
19. **A restart inside the repeated hour of the autumn clock change may restore an override's date-and-time expiry an hour early (recalled, not verified): MITIGATED offline 19 Nov 2026 by owner decision r14.**
    As recalled from Home Assistant core (not verified here), a restart restores a date-and-time helper from its state string, which is local wall-clock time without an
    offset, and a time in the repeated hour (01:00 to 01:59 on the fall-back day, in Europe/London) then reads as the first of the two. If that is how it behaves, a restart
    while an override is running whose expiry falls in the repeated hour restores that expiry 60 minutes early, and the hold and the effective reserve would have released
    up to 60 minutes early (only an override whose expiry falls in the repeated hour of that one night a year is affected, but ANY restart while it is running is
    enough, including one days earlier for a long power cut). The owner decided (r14, 19 Nov 2026) not to accept that: prefer absolute timestamps;
    if an expiry instant cannot be established reliably, fail closed and keep the safety-related override until its state can be reconciled; do not blindly extend every
    override by an hour or silently alter the owner's configured deadline. What changed: each expiry is now also held as an absolute epoch record, an input_number per kind
    holding the same number of seconds the start script already computes (so the owner's deadline is exactly preserved and nothing is extended); the start script writes it
    before the date-and-time expiry and the cancel script writes the cancel instant into both. Every read (the hold sensor's state and `held_by`, the effective reserve and
    the cancel script) takes the later of the two valid instants: an override is active while either is in the future. If either source is not a valid reading the record
    is unreadable: the hold reads unknown (which refuses) unless another record holds, the power-cut reserve stays raised, and a cancel is always allowed on it and
    reconciles it. A cancel is refused as not active only when every source is readable and none is in the future. So a restart that restores the attribute early cannot
    release the override (the epoch record is a number and is restored as it was), and an epoch record that is missing, reset to 0 or unreadable cannot release one the
    attribute still shows as running. Proved offline, against a restart model that restores the attribute as the recalled behaviour would and with the abnormal restores of
    the epoch record listed, by `test_ecco_plan_helpers_package.py` [14] (33 mutants) and `test_ecco_plan_enforcement.py` [13]. What is still modelled only: the recalled
    restore itself (the attribute is NOT said to be preserved across a restart, one way or the other), that an input_number restores an exact epoch, and the template
    filters (items 11 and 17); a supervised check on the owner's Home Assistant version that includes a restart with an override running remains an item for the install.
    What it costs: a record that cannot be read now keeps the hold unknown and the raised reserve in place until a cancel or a readable record reconciles it (a power cut
    that had finished is raised again if its record then becomes unreadable), and an attribute that is LATE (a partial write that left a later date-and-time expiry) holds
    until that instant passes or the owner cancels. The card now reads both records and offers the guarded Cancel (item 23, owner decision r15). Direction: fail closed (the override never ends earlier than the later source and an
    unreadable record is retained). You would see: after such a restart the override still reads as running until its true expiry; with a record unreadable, the hold
    unknown and the raised reserve kept, until a cancel clears it. The card shows such an override as running, or as held by Home Assistant when a record cannot be read, with the guarded Cancel (item 23); a cancel writes both
    sources and reconciles the record. If the card is not at hand, call `script.ecco_plan_override_cancel` yourself (Developer tools, Actions: the kind, and the
    revision if you want the compare-and-set check).
20. **A press-time BLOCKED result was overwritten with STARTED OK when Dump to Grid is found active as the loop ends: FIXED on 19 Nov 2026 (owner decision r14); so was a STARTING, FAILED or CANCELLED result: FIXED the same day (owner decision r15), the startup recovery after a Home Assistant restart included.**
    The BLOCKED text of the press-time recheck is written inside the scheduled start's retry loop, so, unlike the start-time BLOCKED results, the steps after the
    loop still run. Before the fixes, if Dump to Grid was active when the loop ended (started from the dongle's own Start button, which no override binds (RG-ST3), or
    by a manual start), the step after the loop overwrote the result with "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own
    ...", the end-of-run alert was skipped and the schedule notifications were dismissed. It did so for EVERY result but STARTED, not only BLOCKED: a start refused at the
    gate (nothing written), a press nobody answered (outcome unconfirmed), a run the owner cancelled and a run still retrying were all reported as a success whenever the
    dongle was active for any reason. What changed, r14: a result that starts with BLOCKED is never overwritten, so the text stays exactly as the recheck wrote it, the
    end-of-run alert is raised as for any BLOCKED result, the schedule notifications are not dismissed and the write enable still ends off. What changed, r15: the steps
    after the loop write no success text at all. A FAILED or CANCELLED result is final too and stays exactly as written; a result that is still STARTING when Dump to Grid is found
    active has no verified start of its own run and becomes CANCELLED if the owner cancelled the schedule, else a FAILED TO START text that says the retries ended, repeats the last
    dongle status and says that Dump to Grid is active now and that this run did not confirm that it started it (within the 255 characters of the helper), so the alert fires and
    the notifications stay. STARTED OK is still written inside the loop only, after this run's own press, a start transaction that began and Dump to Grid active; that path is
    unchanged in every shape (immediate, a slow transaction, after a retry, after a wait, a stalled view after the start began). A result another writer left (ARMED, REJECTED,
    MISSED) is left alone. With Dump to Grid not active nothing changed (compared run for run with the previous package). The alert's message carries ONE sentence, only while
    Dump to Grid is active at that moment: for a BLOCKED result Dump to Grid is active now, this run did not start it (nothing was pressed); for a FAILED result it is active now and
    this run did not confirm that it started it, because an unconfirmed outcome can be a late start of this run's own press; check it and the plan overrides before assuming it is
    held (the same alert, so it also appears on the alert of a start-time BLOCKED result when Dump to Grid is active). Proved offline by `test_ecco_plan_enforcement.py` [12] (BLOCKED,
    13 and then 15 mutants, the old overwrite among them; it replaces the pin of the old behaviour that stood in [11]) and [14] (every result class x Dump to Grid active or not x armed,
    run through the package's own steps and compared with the previous package; end-to-end runs; 22 mutants, the old overwrite restored for each class among them). What changed, r15, the last path: the startup recovery after a Home Assistant restart, the other writer of STARTED OK in the
    scheduled Dump to Grid package, wrote "STARTED OK - running (Home Assistant restarted during the session)" whenever the schedule was armed, now was inside the window and Dump to Grid was
    active, whatever the last result was, so a refused, failed, cancelled or restart-killed STARTING run read as a success when the dongle's own Start button, a manual start or another path had
    started Dump to Grid. It cannot tell who started Dump to Grid, so it now trusts only the record: a last result that already starts with STARTED (this schedule's own verified start, recorded
    before the restart) keeps that text and the disarm, byte for byte; a result that starts with FAILED, BLOCKED or CANCELLED is final and stays exactly as written (the schedule is still disarmed
    and no alert is added: the text, and for FAILED or BLOCKED the status FAILED once Dump to Grid is not active, stay visible); every other result (STARTING, ARMED, empty, REJECTED, MISSED,
    foreign text) becomes an UNCONFIRMED text of at most 255 characters that says Dump to Grid is active after a Home Assistant restart and that this schedule did not confirm that it started it.
    The recovery presses and starts nothing, and every other branch of it and every case with Dump to Grid not active is unchanged. Proved offline by `test_ecco_plan_enforcement.py` [15] (the real
    recovery automation for 25 result texts x Dump to Grid active or not x armed x where now is relative to the window, compared with the previous package; end-to-end runs through the real start
    script, a restart and the recovery; 23 mutants, the old unconditional write among them) and `registry/tests/test_ha_r9_missed_runs.py`. What is still
    true: this script presses nothing after the loop; the dongle's own Start button is still not bound by any override (RG-ST3), and this change reports an active Dump to Grid, it
    does not stop it; a FAILED text can be a false negative: if the dongle starts late after a start transaction that began (the press was unanswered, the view stalled, the
    outcome is unconfirmed), the run still ends as FAILED TO START, because a FAILED result is final, and the alert says Dump to Grid is active now and that this run did not
    confirm that it started it; a CANCELLED result is never alerted and, with Dump to Grid active, still dismisses the schedule notifications as before (a start-time "Dump to Grid already
    active" refusal does the same); a FAILED text that the startup recovery leaves in place can be a false negative as well (it cannot tell who started Dump to Grid, so it
    does not turn it into a success); the Free Power schedule package still has its own old fallback and its own startup recovery, unchanged and outside this task. Not examined: how real Home Assistant renders the notice. Direction: fail closed for the start (nothing is pressed by the script) and, since the fixes, for the
    record as well. You would see: the BLOCKED or FAILED TO START text in the last result (never STARTED OK unless this run's own start was verified, after a Home Assistant restart too: there, with Dump to Grid active and the start not verified, the UNCONFIRMED text), the "did NOT start" notification
    with the active-now sentence and, when the dongle's own button or a manual start made Dump to Grid active, the schedule status ACTIVE.
21. **A momentary unknown or unavailable hold or reserve sensor at press time costs that night's scheduled export.** The press-time recheck fails closed: if the
    hold sensor or the effective reserve sensor reads unknown, unavailable, empty or junk when it is read just before the press (a template reload or a Home
    Assistant start may do this for a moment), the run ends as BLOCKED with `OVERRIDE_UNREADABLE` or `RESERVE_UNKNOWN`, the alert is raised and the schedule is
    disarmed. That night's scheduled export is lost until the owner arms the schedule again; it is not refused for good, because the next armed run reads the sensors
    afresh. The recheck runs on every attempt, the first included, so a momentary unreadable sensor during the staging (up to about six seconds) has the same effect,
    and a BLOCKED text that says "while this run was waiting" can come from that staging. Reproduced offline by forcing each state during the wait (`test_ecco_plan_enforcement.py`
    [11], `test_ecco_r9_stage3_composition.py` [17]); not examined: whether and for how long a real template reload makes these sensors unavailable. Direction: fail
    closed. You would see: a BLOCKED alert at the start time naming the unreadable plan, a disarmed schedule and no start.
22. **Leftover staging after a run that the press-time recheck stopped.** The three staged numbers of that run (export power, Stop SOC and duration) stay on the
    dongle and the write enable is turned off; the script has no step that restores the earlier values (by reading it; item 15 describes the same run from the
    other side). Reproduced offline: the dongle model keeps the staged numbers and the write enable ends off. Reasoned from the package header and the dongle model's
    start gate, not examined on a dongle: nothing starts without arming again and pressing, the same as after any other failed attempt of the scheduled start.
    Direction: fail closed (nothing starts). You would see: the staged numbers on the dongle's own controls changed to the stopped run's values, with no start.
23. **The card used to read an override's expiry from the date-and-time helper's `timestamp` attribute only, so it could not place or cancel an override that only the absolute epoch record held, or whose record it could not read: FIXED offline on 19 Nov 2026 (owner decision r15; modelled and tested offline, not seen in a browser or on a real Home Assistant).**
    What it was: the Energy Actions card placed each override on the helper's `timestamp` attribute only (`src/plan/helpers.ts`; the displayed time text comes from the state string, which a
    restart does not change) and built its Cancel button from that row alone, so after a restart that restores the attribute early (item 19), when only the epoch record holds the override, or when a record
    cannot be read, the card showed the override as ended, or not at all, with no Cancel, while the backend still held it (the owner then had to call `script.ecco_plan_override_cancel` by hand).
    What the card does now (owner decision r15): it reads the three epoch records too (`HELPER_IDS`) and mirrors the backend's read rule, in pure TypeScript with no clock and no write. Per kind it takes the later of the two valid instants
    (the date-and-time record's `timestamp` attribute, the absolute epoch record) and shows the kind as running, with the same Cancel, while either is in the future; an instant that only the epoch record gives is shown in UTC, with a note that
    the absolute epoch record holds it. When a record cannot be read and the other does not hold, the kind is not shown as ended: it is shown as "Held by Home Assistant", with a plain-words note (the record cannot be read here; Home Assistant keeps
    the hold, and any raised reserve, until a cancel settles it) and the same Cancel, because the backend allows a cancel on an unreadable or disagreeing record; a malformed record that is still in the future is shown the same way. The kind is shown as
    ended, and the Cancel withdrawn, only when both records are readable and neither is in the future. An older package without the epoch records is judged by the date-and-time record only, and the card says so. On a NEW package in which one or more epoch helper entities are missing (not installed, renamed or removed), the backend reads that kind as unknown (the hold reads unknown, which refuses; item 19) while the card judges the missing record as absent and may show the kind as cleared without a Cancel; the card lists the problem line, the cancel script still works (for example through Developer tools, Actions, `script.ecco_plan_override_cancel`), and the owner must repair the helper (a note of the independent review of 19 Nov 2026, from the sources and the offline tests, not seen in a browser). The card is never more lenient than the
    backend (a reading it cannot place counts as unreadable) and judges to the minute, on the browser's clock, as it does for every countdown. A record that ends inside a minute can therefore make the card offer Cancel for up to 59 seconds after the backend has cleared it (fail-safe: the answer is then NOT_ACTIVE and the readback says Cancel NOT confirmed).
    The Cancel is the existing guarded call and nothing else: `script.turn_on` on `script.ecco_plan_override_cancel` with the stored revision as compare-and-set, behind the same controls as every other row; there is no new service, no second control route
    and no direct helper write, and the card's allow-list is unchanged. After the call the card does not assume success. On the next states update it reads back the plan revision and BOTH records and says plainly "Cancel confirmed" only when the revision
    moved by the cancel's own step and both records read as ended, "Cancel sent" (still pending) until Home Assistant has answered, and "Cancel NOT confirmed" while a record is still in the future or cannot be read, or when the script refused (its own answer is quoted, and also stays in
    "Last answer"). If another writer moved the revision as well, or the answer is not a cancel's, it makes no claim. The card remembers the click in the page only (a reload forgets it, and the readback then says nothing).
    What is NOT claimed: this is modelled and tested offline only (`frontend/ecco-energy-actions-card/test/planEpochCancel.test.ts`, with mutants), not seen in a browser or on a real Home Assistant, and the backend, not the card, still decides: the hold, the held-by list, the effective reserve,
    the scheduled start, the guarded start and the cancel script all follow the later of the two sources whatever the card shows. A browser with a stale copy of the card keeps the old behaviour until its cache is cleared. The supervised check of item 19 should include a restart with
    an override running and a Cancel from the card. The dongle's own Start button is still not bound by any override (RG-ST3). Direction: fail closed (a record the card cannot read is shown as held, with a Cancel, never as ended).
    You would see: after a restart in the repeated hour (or any state that leaves a record early or unreadable), the override still shown as running, or as held by Home Assistant, with a Cancel, until its true expiry or a confirmed cancel.

### Install order for the owner (each step needs its own authorisation; nothing here is installed)

1. Review and merge through the usual route.
2. R9 first: its two schedule packages (`ecco_free_power_schedule.yaml` and `ecco_dump_to_grid_schedule.yaml`) with a FULL Home Assistant restart, as R9's own installation notes say. The changed `ecco_dump_to_grid_schedule.yaml` of this change contains R9's text, so R9's packages go in before this change or in the same deployment, never after it: R9's own copy of that file, installed over this one, would undo this change.
3. Before any step that creates entities (R9 adds two helpers; this change adds the plan helpers, three scripts and two sensors): decide how Home Assistant's voice assistants treat new entities (release gate RG-F3) and read the exposure list read-only. Nothing created here is meant to be exposed to an assistant.
4. Install `ecco_plan_helpers.yaml`, `ecco_dump_to_grid_guarded_start.yaml` and the changed `ecco_dump_to_grid_schedule.yaml` in the SAME deployment, then ONE full Home Assistant restart. The order of the three copies does not matter: until the plan helpers are installed and Home Assistant has restarted fully, every scheduled start and every guarded start is refused (fail closed). The first start seeds the accepted limits; the confirmation switch stays off.
5. Look at the eight limits on the helpers page; turn on `ecco_plan_overrides_enabled`.
6. Copy the rebuilt card bundle (`frontend_assets` entry; resource already registered), clear the browser cache, set `show_plan: true` and `dump_to_grid.guarded_start: script.ecco_dump_to_grid_start_guarded`. Until `dump_to_grid.guarded_start` is set, the card's own Start button presses the dongle's button directly (known limitation 5), so no override binds it.
7. Supervised check: start and cancel Hold battery; a scheduled start that must be refused; the manual start refused during an override and accepted after.
8. Optional, after the acceptance run ends: map Intelligence's `reserve.ha_minimum_soc` to `sensor.ecco_plan_effective_reserve` (site check first).

### What is the owner's

Every value above (changeable in the helpers), whether and when to install each step, the Intelligence mapping, a firmware gate for the dongle's
own Start button, and whether to enrol the card's `tsconfig.json` in the pin chain.
