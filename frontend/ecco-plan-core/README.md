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
| `gentleAdvice.ts` | read-only, stateless gentle RATE ADVICE over the model: the lowest rate that still reaches the target by the deadline, one reason code, an outcome, the practical minimum and the safe maximum, no advice (and why) on missing or stale data (see "Gentle rate advice"); NOT exported by the package index; never actuates |
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

**It does not guarantee the target.** Every decision carries `guarantee: 'NONE'` and the note `NO_GUARANTEE_NOTE`: the target is NOT guaranteed;
a 100 percent target is the most at risk, because the BMS is expected to taper the charge near full and to handle the top of charge itself (assumed here,
not measured), so a fixed rate is unlikely to finish a full charge on time; and the model is read-only. Nothing actuates: `actuationSupported` is `false`
everywhere.

- Never lowers the target and never recommends a setpoint above the smallest KNOWN safe ceiling (owner maximum, battery maximum charge current x
  voltage, grid-charge current x voltage, configured maximum grid-charge power) or the grid-headroom cap below, AS ITS INPUTS AND ASSUMPTIONS STATE
  THEM: that is a model estimate, not a measurement, and the real limits may be lower. None known = `NO_SAFE_CEILING`, no default is guessed; unknown
  or stale SOC = `NO_DATA`.
- Statuses: `OK`, `DEGRADED` (a plan that rests on an assumed demand, asked for explicitly), `NOTHING_TO_CHARGE`, `TARGET_AT_RISK` (the highest safe
  setpoint finishes late, inside the buffer; it is also the status when the setpoint that STAYS in force would finish after the deadline because a higher
  one is held back by the changes budget, or by a recovering grid cap waiting for its hysteresis and dwell), `TARGET_UNREACHABLE` (not even that reaches it
  before the window ends), `NO_DATA`, `NO_SAFE_CEILING`, `DEADLINE_PASSED`, `INVALID`. At risk and unreachable recommend the highest safe setpoint,
  project the late finish, report the smallest buffer that would absorb it (`suggestedBufferMin`) and say "Buffer too small" and "The target is NOT
  guaranteed"; the target stays.
- A decrease needs the dwell, a saving of at least the hysteresis and a slack to the deadline, and goes down by at most the slew limit per change; an
  increase needed for the deadline is never held back by dwell or hysteresis (a jump over the slew limit is flagged `JUMP_FOR_DEADLINE` and counted).
  A safety decrease (the setpoint in force is above a limit that fell) is never held back by anything. In the ordinary changes budget
  (`changesUsed`, `changesLeft`) the START and a safety decrease are free and every other change draws on it; `totalChangesUsed` counts EVERY recommended
  write, the START and the safety decreases included, and never blocks one (the count a real actuator's write budget must keep). The exception to
  "an increase is never held back": where the grid headroom BINDS and is recovering after a fall, the rise waits for the hysteresis and the dwell like a
  saving (anti-flapping on noisy household readings); a limit that does not bind never holds a rise toward the ceiling.

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
| `socRegressionTolPct` | 3 | PROVISIONAL | with a `previousSoc`, a reading more than this many points below it is implausible (`SOC_IMPLAUSIBLE`, `NO_DATA`) | the measured noise and update behaviour of the SOC sensor |
| `socJumpPctPerHour` | 60 | PROVISIONAL | with a `previousSoc`, a reading further above it than this rate (plus the resolution and the regression tolerance) allows is implausible | the measured fastest real charge rate of the battery |
| `demandMarginPct` | 20 | PROVISIONAL | percent added to the household demand peak | the measured spread of real demand against its forecast |
| `assumedDemandW` | 2000 W | MEASURED_REQUIRED | floor of the demand peak when demand over the window is not covered and the policy is ASSUME_PROVISIONAL (`ASSUMED_DEMAND`) | the measured overnight household demand profile (unknown today) |
| `solarCreditPct` | 0 | PROVISIONAL | percent (0-100) of the bounded solar credited INSIDE the hard grid limit; 0 = none (the cap is the limit minus the demand peak); above 0 only behind a measured forecast skill gate, which does not exist yet | a measured forecast skill gate |
| `maxHouseholdAgeMin` | 15 min | PROVISIONAL | demand and solar readings older than this are treated as unknown | the real update rate of those sensors |
| `setpointConversionEff` | 0.85 | PROVISIONAL | converts a grid-side limit (the grid headroom, a ceiling labelled `GRID_AC`) to the battery-side watts of a `BATTERY_DC` or `UNSETTLED` setpoint: S <= eff x grid-side limit; pessimistic and UNMEASURED; not the charge-energy `chargeEff` | the measured grid-to-battery power ratio at the settled basis |
| `maxForecastAgeMin` | 120 min | PROVISIONAL | the demand and solar FORECASTS (`demandProfileAgeMin`, `solarProfileAgeMin`) older than this, or with no valid age, are unknown | the real refresh rate of those forecasts |
| `maxCeilingAgeMin` | 60 min | PROVISIONAL | a named ceiling with an age (`ageMin`) older than this is stale: it cannot make a setpoint safe, but a stale value that is lower than every fresh one still caps | the real update rate of the live battery and grid-charge limits |
| `maxGridLimitAgeMin` | 60 min | PROVISIONAL | a grid import limit with an age (`gridImportLimitAgeMin`) older than this is unusable: nothing is recommended | the real update rate of the limit, when it is read from a device |
| `maxDecreaseStepW` | 8000 W | PROVISIONAL | slew limit per decrease; 8000 W never binds, which keeps the v1 behaviour; the recommended gentle value is 1000 W (`GENTLE_RECOMMENDED_PARAMS`) | the owner's confirmation |
| `fallbackPolicy` | KEEP_CURRENT | PROVISIONAL | what to hold when the plan cannot run: `KEEP_CURRENT`, `USE_STATIC_PLAN` or `NONE` | the owner's choice |
| `unknownDemandPolicy` | FALLBACK | PROVISIONAL | unknown demand with a known grid limit: `FALLBACK` (the default: no recommendation, nothing is guessed) or `ASSUME_PROVISIONAL` (an explicit option: plans from `assumedDemandW`, status `DEGRADED`, never `OK`) | the owner's choice |
| `setpointBasis` | UNSETTLED | PROVISIONAL | what the setpoint S means to the actuator: `GRID_AC` (grid-side watts), `BATTERY_DC` (battery-side watts) or `UNSETTLED` (the default: every cap holds under either) | live proof of the actuator's convention |
| `actuatorProfile` | UNCONSTRAINED | PROVISIONAL | the ONE path a recommendation could later be applied through (`FREE_POWER_LEASE`, `TOU_SLOT_EDITOR`, `RATE_CONTROLLER_PROPOSED`); its step, range, dwell and changes per window tighten the parameters, never loosen them; UNCONSTRAINED changes nothing | the owner's decision on which path (none is authorised today) |
| `setpointOvershoot` | 1 | PROVISIONAL | the realised power was ABOVE the commanded setpoint on the saved nights, so every cap converted to setpoint units is divided by this factor; 1 = off; the recommended gentle value is 1.1 (`GENTLE_RECOMMENDED_PARAMS`) | commanded against measured power at several setpoints |
| `targetSocPct` | owner setting | OWNER_SET | the charge target, 10-100; never lowered by the model | the owner's setting |
| `bufferMin` | 60 min | OWNER_SET | finish-early buffer, 0-120 in 5-minute steps (`GENTLE_DEFAULT_BUFFER_MIN` is the default helpers and tests use) | the owner's setting |
| `gridImportLimitW` | owner setting or unknown | OWNER_SET | the KNOWN safe grid import limit; unknown means no headroom constraint | the owner's or installer's figure |

Unmeasured values are never presented as facts: the decision's `assumptionsLabel` says `assumed, not measured`.

### Household demand, solar and grid headroom (optional)

An optional `household` input group, with `policy` and `staticPlanRateW`. Without it every v1 output is **bit-identical** (a golden-master digest
over 400 closed-loop runs and 4000 random inputs proves it). Demand is the household load EXCLUDING the charger (the caller subtracts the present
charge draw from a meter reading).

**What the setpoint S means (`policy.setpointBasis`).** Nothing proves it yet: today's firmware turns watts into amps at the battery voltage when a
lease starts, and the inverter's own AC and DC figures differ by several percent. So the basis is explicit: `GRID_AC` (S is grid-side watts: grid
draw = S), `BATTERY_DC` (S is battery-side watts: grid draw = S / efficiency) or `UNSETTLED` (the default: every cap is the lower of the two readings
and holds under either convention). The efficiency of that conversion is `setpointConversionEff` (default 0.85: pessimistic, UNMEASURED; not the
charge-energy `chargeEff`). The cost of the safe default is
visible: the grid cap is 15 percent lower than a settled grid-side basis would allow. Settle the basis by live proof and measure the ratio to remove it.
Named ceilings may say which side they are measured on (`NamedCeiling.basis`): an unlabelled ceiling is already in setpoint units (an owner limit in the
editor's own unit) and is never converted; a `BATTERY_DC` ceiling is never raised to a grid-side equivalent; a `GRID_AC` ceiling is converted DOWN by
`setpointConversionEff` unless the basis is `GRID_AC`.

**The charge efficiency is a separate, unmeasured assumption.** `chargeEff` (default 0.95) only shapes the state-of-charge projection. The projection
adds `delivered watts x chargeEff` of stored energy for each minute, the same formula in every basis (the delivered watts are in setpoint units: the least
of the setpoint, the ceiling times the taper acceptance and, with household input, the headroom at that minute). Under `GRID_AC` the projection therefore gains the setpoint times 0.95: the default is
on the pessimistic side only if the real grid-to-battery (AC-to-DC) efficiency is at or above 0.95, and if the real figure is below it the projection is
optimistic (the battery gains less than the plan shows). Under `BATTERY_DC` the setpoint is already in battery-side watts and the code still applies the
same factor to them, so there it is a further unmeasured factor between those watts and the stored energy, read the same way; under `UNSETTLED` the same
formula runs on the setpoint as given. The default is not changed here; a measured efficiency is on the list of what is needed before an actuator exists
(item 4 below).

- Grid import = `S / scale + demand - solarUsed` (`gridImportW`), where `scale` is 1 for `GRID_AC` and `setpointConversionEff` otherwise.
- The cap on S = `scale x max(0, gridLimit - demandPeak + solarCredited)` (`batteryHeadroomW` gives the battery-side figure for a grid-side limit at the
  charge efficiency); the reported `projectedImportW` is the draw at the recommended setpoint on the same reading, so it never exceeds the limit.
- Pessimism: demand = the PEAK of the fresh reading and the forecast profile over the remaining window, plus `demandMarginPct`. Solar is NOT
  inside the hard limit: `solarCreditPct` is 0 by default, so the cap is the limit minus the demand peak. The bounded solar (`min(fresh reading, forecast
  x confidence)`, 0 when the reading is unknown or stale, there is no forecast or no confidence) is reported as `solarPotentialMinW`, information only;
  `solarNowW` is GROSS PV output (the household use is already in the demand, so a surplus would count it twice). A reading older than
  `maxHouseholdAgeMin` is unknown.
- The cap on the setpoint is the least headroom over the remaining minutes, rounded down to a step (`headroomCapW`); the setpoint is at most
  `min(ceiling, cap)` and the decision reports `limitedBy` and the pessimistic `projectedImportW` (never above the limit). The forward projection
  uses the delivered power per minute, `min(setpoint, ceiling x taper acceptance, headroom at that minute)`, not a constant. (For a setpoint inside the cap the headroom is never the smaller term, because the cap is its least value over the window; the term makes the projection honest for any setpoint outside the cap and is covered by its own tests.)
- Unknown grid limit: no headroom constraint is applied, the reason says so (`NO_GRID_LIMIT`), the limit is never guessed. A limit that is not a
  number is `NO_DATA` (`HOUSEHOLD_INVALID`).
- Unknown demand with a known limit (no fresh forecast from now and no fresh reading): the default policy `FALLBACK` returns `NO_DATA`
  (`HOUSEHOLD_UNUSABLE`) and applies the fallback policy: no guessed constant stands in for an unknown demand under a known safety limit.
  `ASSUME_PROVISIONAL` is an explicit option: `assumedDemandW` is the floor of the peak (`ASSUMED_DEMAND`, labelled `assumed, not measured`) and
  the status is `DEGRADED`, never `OK` (a worse status such as `TARGET_AT_RISK` is not softened).
- Ages (fail closed). A forecast needs a fresh age: `demandProfileAgeMin` and `solarProfileAgeMin` (real minutes) up to `maxForecastAgeMin`; a
  forecast with no valid age is unknown (`FORECAST_STALE`; a stale solar forecast is ignored, `SOLAR_IGNORED`). A named ceiling may carry an age
  (`NamedCeiling.ageMin`): one with no age is a static, owner-set value taken as current (the v1 behaviour); one that is older than
  `maxCeilingAgeMin` is stale (`CEILING_STALE`): with no fresh known ceiling left the status is `NO_SAFE_CEILING` (no fallback), and a stale value
  that is LOWER than every fresh one still applies (a derated limit that went quiet is not forgotten; a stale value never raises the cap). A grid
  limit may carry an age (`gridImportLimitAgeMin`): none means a static limit; one older than `maxGridLimitAgeMin` makes the household input
  unusable (`GRID_LIMIT_STALE`, `NO_DATA`, no recommendation), not "no limit".
- Anti-flapping, only in this mode: a highest-safe-setpoint recovery (the cap rises again while the target is already at risk) waits for the
  hysteresis and the dwell like a saving; an increase the deadline can wait for (a raise to the maximum after the dwell still makes it with the
  decrease slack) waits out the dwell (`HELD_DWELL`); an increase that cannot wait, and a fall of the cap (`ABOVE_HEADROOM`), are immediate.

### Checks and counters (v3)

- **SOC plausibility.** With `previousSoc` (the previous accepted reading and the real minutes since the window opened) a reading more than
  `socRegressionTolPct` below it, or further above it than `socJumpPctPerHour` allows (plus the resolution and the tolerance), is `SOC_IMPLAUSIBLE` (`NO_DATA`,
  the fallback applies); a `previousSoc` from after the elapsed time is `INVALID` (the clock count went backwards). There is no second SOC source: the
  check cannot catch a reading that is wrong but plausible.
- **Reading at the target.** A reported reading at or above the target counts as reached (`NOTHING_TO_CHARGE`); the pessimistic half-resolution offset applies
  to the plan only. With a setpoint in force the decision says `stopRecommended` (also when the window is over); `change` stays `NONE`: the model has no STOP
  change kind and no actuator has a stop at a SOC.
- **Fractional time.** A finish that lands after a fractional horizon is late, never on time (no rounding up of the horizon).
- **Ambiguous clock-change start.** A window that starts exactly at the change minute, or inside the hour a spring change skips, has an unknown real
  length: `INVALID`, nothing is recommended (`ambiguousClockStart` in `time.ts`, `windowRealMinutes` is `null`). The repeated hour of an autumn change is
  NOT treated as ambiguous: a start inside it is read as the first pass (the model and its simulator share this); which pass the owner means is an open ruling.
- **Hold that waits out the dwell.** The projection assumes the raise the model will actually make afterwards (the lowest step that still makes the
  deadline), so the margin shown is that one, not the larger margin a raise to the ceiling would show.
- **Current limits to power.** `powerFromCurrent(amps, volts, minVolts)` takes the lower of the two voltages, because the actuator turns watts into amps at the
  voltage the pack has when the rate is applied; `ampsFromPower(watts, volts, ampLimit)` never exceeds the current limit.
- A slew step smaller than the hysteresis is refused at validation (`maxDecreaseStepW` below `hysteresisW` with the slew on): it could never save the hysteresis.

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
re-plans from the measured SOC at every tick, so it corrects an error it can OBSERVE (a slower rise than projected) instead of relying on a margin chosen in advance; it does not know the real taper or capacity (assumed, unmeasured), and nothing here shows that it follows them. `test/support/batterySim.ts` is the
closed-loop simulator (a true battery that differs from the model, rounded and noisy SOC readings, dips, 23 and 25 hour days; for the household mode also true
demand and solar that differ from the forecast and a physical grid limit that clips the delivered charge) and `test/gentleController.test.ts` prints the
comparison with the static planner and the miss rate when the true demand exceeds the forecast; everything is simulated, not measured. The controller
stops at the **reported** target, so the simulation counts the target as reached within half the reading step plus the noise (the strict count is printed too).

**Taper shapes the model does not assume.** The simulator's TRUE battery has three taper shapes (`TrueTaper.shape`): `LINEAR`, the shape the model assumes
(acceptance falls linearly from the ceiling to `endFraction` x ceiling at 100 %); `CV_TAIL`, a constant-voltage tail (the acceptance decays exponentially
above the taper start); and `CURRENT_ABSOLUTE`, a current-based limit of the battery itself that is independent of the ceiling the model knows. In the
seeded run (380 in-band scenarios per shape, only those the true battery can make with time to spare) the model's own shape misses none; the other four
variants (two CV tails, two current limits) miss 32 of 1073 (3.0 percent), 29 of the misses are 100 percent targets and all 29 were reported
`TARGET_AT_RISK` or `TARGET_UNREACHABLE` before the deadline; one miss (a 95 percent target with no buffer, so no tick exists after the deadline) was reported
`OK` until the window end. The test prints every row and asserts only what holds. **What this shows:** the closed loop CAN expose a wrong taper
assumption, the misses appear where a harsh taper meets a 100 percent target, and in this seed set a missed 100 percent target was flagged at risk before
the deadline. **What it does not show:** that the assumed taper is right, that a real BMS resembles any of these shapes, that the at-risk report always comes
early enough to act on, or any guarantee. The real taper, the top-of-charge hold and the BMS limits are unmeasured (see the list before an actuator).

### Units

Every power is in W (in SETPOINT units, see `setpointBasis`, unless a field says grid-side or battery-side); every age, elapsed time and window length is in
REAL minutes (a monotonic count since the window opened, not the wall clock; a clock-change night is 23 or 25 hours long); SOC is in percent points;
`solarNowW` is gross PV output and `demandNowW` is the household load without the charger. The model never reads a clock: every age is given to it.

### Before an actuator, and the limits that remain

Nothing in this list is done by this model. Each item needs its own measurement or design, an independent review and the owner's own authorisation.

Before any actuator exists:

1. Firmware support for a variable Free Power rate during a lease (today the rate is fixed at START, and a change from outside blocks the restore).
2. A Free Power rate controller on the Dump V1.1 pattern: the intended value saved before each write, a deadband, a settle time, and a write budget that
   counts EVERY write, the START and the safety decreases included (the model reports `totalChangesUsed` and never blocks a safety decrease).
3. Live proof of the charge-power response at low setpoints and of the BMS current limiting.
4. Settle the setpoint basis (grid-side watts, battery-side watts, or amps at which voltage) and measure the conversion efficiency. Until then
   `setpointBasis` stays `UNSETTLED` and `setpointConversionEff` pessimistic and unmeasured: the safe default costs about 15 percent of the grid cap.
   Measure the charge efficiency (`chargeEff`, default 0.95) too: it is an unmeasured assumption, and the state-of-charge projection is optimistic if the
   real efficiency is below it.
5. Measure the BMS taper, the top-of-charge hold and the live BMS limits or derating; carry the age of every ceiling (`NamedCeiling.ageMin`). Until a caller
   supplies ages, a named ceiling passed without an age is treated as current and trusted, however old the reading behind it is.
6. A stop-at-target mechanism (Free Power has no SOC stop): the model only says `stopRecommended`, it has no STOP change kind.
7. The household side: a KNOWN owner-set grid limit (with an age when it is read from a device); unknown demand stays `FALLBACK`; forecasts carry an age;
   no solar inside the hard limit unless a MEASURED forecast skill gate exists (`solarCreditPct` stays 0; the confidence was 0 in November).
8. Settle the clock-change rulings, an independent review of the actuator design, and the owner's authorisation.

Closed in the model by this change (review of 20 Nov 2026): the recovery flag follows whether the headroom binds; a finish after a fractional horizon is late;
forecasts, ceilings and the grid limit carry ages; the unknown-demand default is `FALLBACK`; no solar inside the hard limit by default; the setpoint basis is
explicit; fallbacks respect the window end; SOC plausibility; an ambiguous clock-change start is unknown. Still open, in the model:

- A reading at or above the target is taken as reached (`NOTHING_TO_CHARGE` compares the raw reading, not the pessimistic plan start); the v1 golden master
  pins it. A reading of 100 when the real SOC is 99.5 is taken as done.
- There is no second SOC source and `elapsedMin` is trusted except against `previousSoc`: a reading that is wrong but plausible is not caught.
- The repeated hour of an autumn change is read as the first pass; which pass the owner means is not settled.
- The taper, the top-of-charge hold, the capacity band and the efficiencies are assumptions. A 100 percent target is the most at risk and is never guaranteed.
- Demand above its forecast beyond the margin can still cross the grid limit (the closed loop prints how often); the margin is provisional.
- Where the grid headroom binds and is recovering, a rise waits for the hysteresis and the dwell (anti-flapping): the at-risk state lasts longer than it
  would without the hold. A stale named ceiling that is lower than every fresh one still caps until it is refreshed.
- The recovery hold also delays a rise toward a BINDING cap in an at-risk state, up to the dwell (30 minutes by default), although the rise never goes above
  the cap. This is a documented trade-off and an owner parameter decision: hold only after a cap-driven decrease, or shorten the hold while the target is at risk.

Settled, kept here because it was once an open question: the Energy Actions card bundle carries the model's default constants as inert dead code (the card
never calls the model). The bundle was rebuilt from these sources and is declared by the pin-chain entry `epc4`, which sits AFTER `ecf1` (the card
corrections) in the chain: the rebuilt bundle, the entry and this paragraph are ONE commit of this stack, so they can only be dropped together, and dropping
them returns to the bundle `ecf1` declares. Measured: with `src/gentleController.ts` alone put back to its text at the card-corrections tip, these sources
build that bundle byte for byte, so the whole bundle difference comes from the model's constants. The card's behaviour and its golden renders are
unchanged, and a headless-browser run of the card with each of the two bundles renders the same DOM and stylesheet text.

### Resolved limits and the actuator profiles (24 Nov 2026, offline evidence; still read only)

Full write-up and sources: `docs/reports/gentle-2026-11-24/GENTLE_LIMITS_AND_AUTHORITY.md` in the private project record.

- **One authoritative maximum-charge-power basis** (`MAX_CHARGE_POWER_BASIS`, `maxChargePowerCeiling`): a SETPOINT bound, the smaller of the firmware
  slot-power bound and the owner's operating limit. It is not a measured battery-side power, not the grid import limit, not the inverter's rated power and
  not a BMS limit: on four saved nights the realised battery-side power was above it and the grid import well above it. Those limits stay separate named
  ceilings with their own basis; the `setpointOvershoot` allowance keeps the real power inside them.
- **Actuator profiles** (`GENTLE_ACTUATOR_PROFILES`, `policy.actuatorProfile`): `FREE_POWER_LEASE` fixes the rate at the START (no adjustment, so a later
  change, in practice a safety decrease, is reported as not applicable with a stop recommended, and a shortfall is said to be unrepairable inside the
  window); `TOU_SLOT_EDITOR` allows one coarse adjustment per window with a 60 minute dwell (proposed policy; the owner confirms each write);
  `RATE_CONTROLLER_PROPOSED` is the unbuilt controller (the model's own 6 changes, 30 minute dwell). The decision's `actuator` block says which constraints
  applied. Nothing is authorised: every profile has `automaticApplyAuthorised: false`, and `actuationSupported` stays false.
- **Finish-early deadline**: `bufferMin` may be left out; it is then 60 minutes (`GENTLE_DEFAULT_BUFFER_MIN`); the owner's value 0-120 in steps of 5 wins.
- **Target not reachable**: the best effort is the highest safe rate, the target is never lowered, the status says TARGET_AT_RISK or TARGET_UNREACHABLE.
- Still open (not changed here): the setpoint unit (`setpointBasis` stays UNSETTLED), the BMS taper shape (the saved nights show a flat plateau, then a
  drop within about five minutes to a low tail, not the model's linear taper; no SOC series was available to place the drop), and the response at rates
  below the top one (no data).

## Gentle rate advice (read only, offline, unreleased)

`adviseGentleRate(input)` (`src/gentleAdvice.ts`) is the stateless question over the model above: with nothing in force yet, what is the **gentlest
charge rate that still reaches the chosen target SOC by the deadline**, from the state given? It is a thin layer over `planGentle`, not a second
controller: it calls the model with no setpoint in force (so no hysteresis, dwell, slew or changes budget) and no fallback, and returns
`{ advice, reason, outcome, rateW, rateAmps, neededW, minRateW, safeMaxW, marginMin, margins, summary, codes, decision }` labelled
`model, not a command`. Call it at every re-plan tick with the latest readings; the anti-flapping rules for a rate that is already in force stay in
`planGentle`. It is **not re-exported by `src/index.ts`**: the Energy Actions card bundle is declared by the pin-chain entry `epc4` and any module the
package index exports changes that bundle (measured), so import it from `./gentleAdvice.ts` (a test pins this).

| `advice` | Meaning | `rateW` |
|---|---|---|
| `RATE` | the lowest 100 W step that reaches the target by the deadline (`outcome` `ON_TIME`) | the step, never above the smallest known safe ceiling or the grid cap, never below the practical minimum |
| `BEST_EFFORT` | no safe rate reaches it in time: the highest safe rate, and **the target will be missed** (`LATE` inside the buffer, `MISSED` not before the window ends) | the highest safe rate |
| `NOTHING_TO_CHARGE` | at or above the target | null |
| `NO_ADVICE` | unknown, stale or implausible data, no safe ceiling, an unusable household input, an invalid input, or the window is over: nothing is recommended and `reason` and `explanation` say why | null |

- **One reason per decision** (`reason`, a closed list: `ADVICE_REASONS`): `RATE_GENTLEST`, `RATE_AT_PRACTICAL_MINIMUM` (the minimum already reaches the
  target in time and nothing gentler is offered), `RATE_AT_SAFE_MAXIMUM` (nothing gentler reaches it), `BEST_EFFORT_AT_RISK`, `BEST_EFFORT_UNREACHABLE`,
  `BEST_EFFORT_DEADLINE_PASSED`, `AT_TARGET`, `NO_SOC`, `STALE_SOC`, `SOC_IMPLAUSIBLE`, `NO_SAFE_CEILING`, `CEILING_BELOW_MIN`, `HEADROOM_BELOW_MIN`,
  `HOUSEHOLD_UNUSABLE`, `HOUSEHOLD_INVALID`, `GRID_LIMIT_STALE`, `WINDOW_ENDED`, `INVALID_INPUT` and the fail-closed default `NO_SETPOINT`. The other codes of the
  underlying decision are in `codes`; the full decision is in `decision` for audit.
- **Hard limits** (random sweeps in `test/gentleAdvice.test.ts`): the rate is never above the smallest known safe ceiling, the grid headroom cap or the
  editor's maximum; for a `RATE` it equals the lowest step that makes the deadline (a linear search with the model's own projection agrees, and one step
  lower misses), so it is never above what is needed; it is never below the practical minimum (`minRateW`, rounded up to a step): when no safe rate even
  reaches the minimum (`CEILING_BELOW_MIN`, `HEADROOM_BELOW_MIN`) there is no advice and the outcome is `MISSED`.
- **Margins it already carries** (`margins`): the finish-early buffer, the capacity band, the half-resolution SOC offset, the top-of-charge hold for a 100 %
  target and the assumed taper; `marginMin` is the projected minutes to spare. They are inputs or stated assumptions, none is added on top of the lowest step.
- **Monotone** (seeded sweeps): a higher SOC never raises the rate; a higher target, less time left, a longer buffer, a larger capacity or capacity band
  never lowers it. (Not claimed for the ceiling or the household inputs: a lower ceiling can turn a rate into a best effort at that ceiling.)
- **No advice on bad data**: unknown, stale (older than `maxSocAgeMin`) or implausible SOC; no fresh known ceiling; a known grid limit that is stale or
  has no covering demand forecast (the default policy `FALLBACK`; `ASSUME_PROVISIONAL` is an explicit option and the advice is then `degraded`). No
  fallback rate is ever advised.
- **No memory and no side effects**: the stateful fields of the full model are not inputs (passing them changes nothing), the input is never changed
  (tests run it on frozen input), the same input gives the same advice, and the module has no service call, network, file, clock or randomness (a static
  test pins the banned words and the one import). It changes no published entity, helper, schedule or mode, and says `actuationSupported: false`.
- **A current instead of a rate**: with `battery: { volts, minVolts, maxChargeAmps }` the advice also carries `rateAmps`, the rate at the lowest given
  voltage, never above the current limit; none without a valid voltage.
- **Cautions that ride along** (`warnings`; they never change the rate, the outcome or the reason): `CEILING_AGE_UNKNOWN` (a safe ceiling given with no
  age is taken as current, the open item "a named ceiling passed without an age is trusted" above, now said where the advice is read) and
  `TOP_OF_CHARGE_TAIL` (at a 100 % target the battery may keep charging for a while after the reading reaches 100; the plan only reserves that time before the
  deadline, and stopping at the first reading of 100 would cut it off: `NOTHING_TO_CHARGE` at 100 is a statement about the reading, not a stop order).

What it is not: it does not make the target certain (`guarantee: 'NONE'`), it does not know the real taper, top-of-charge behaviour, efficiency or low-rate
response (assumptions, see the parameter table), and nothing here applies a rate. The offline replay tool `intelligence/tools/gentle_replay.py` runs this
advice against recorded nights and prints what the battery did next to what would have been advised. It reaches the one implementation through
`tools/adviseBatch.ts` (standard input to standard output; outside `src/` because the sources must never touch either; Node 22.18 or newer), so there is no
second copy of the logic in Python. What would have to be proven independently before
any live use is in [`GENTLE_LIVE_ACTUATION_PROOF.md`](GENTLE_LIVE_ACTUATION_PROOF.md).

## Gentle night planner (read only, offline, unreleased)

`planGentleNight(input)` (`src/gentleNight.ts`) is the night-level answer the two layers above could not give: from the readings it returns the **recommended
setpoint for now**, a **planned trajectory** of timed setpoints, the **expected finish**, the **SOC at the deadline as a pessimistic / expected / optimistic
band**, one **status**, **reason codes** and **what would be needed to apply it**, labelled `model, not a command`. It applies nothing (`actuationSupported`
is `false` in every result; a test pins the static source: no service call, write, network, file, clock or randomness). It is **not exported by
`src/index.ts`** (the pinned card bundle would change; a test pins this) and no card calls it. It is the layer a future firmware rate controller would
read (workstream A2 designs that path); today it is advice only. `planGentle` and `adviseGentleRate` above are untouched (a golden-master test pins six
fixed nights of the older model).

| `status` | Meaning |
|---|---|
| `OK` | the pessimistic simulation **with the first rate held** for the rest of the window (`band.pessimisticHeld`) reaches the target by the deadline: no path makes a later change by itself (each needs the owner, or the path does not exist), so OK never relies on one |
| `TARGET_AT_RISK` | the pessimistic world misses the deadline but the expected world makes it, or the pessimistic one finishes inside the buffer, or only a planned later change would make it (`RELIES_ON_LATER_CHANGE`), or the highest safe rate the path can still apply would reach the target inside the window although the rate in force held does not (a rate that only the dwell holds low); with nothing in force the setpoint is the highest safe rate and `bufferThatWouldFitMin` says how long a buffer would still fit |
| `UNREACHABLE` | not before the window ends, even at the highest safe rate the path can still apply (round 3: a rate that only the dwell holds low is `TARGET_AT_RISK`; a path that cannot change the rate, the lease, and a spent change budget cannot raise it, so for them the rate in force held is the answer); the target is never lowered |
| `STOP_RECOMMENDED` | the rate in force is above a known ceiling on a path that cannot change it after the START (`FREE_POWER_LEASE`, `ACTUATOR_FIXED_RATE`), or above a ceiling below the lowest setpoint on any path. It is checked **before every refusal** (NO_NEED, WINDOW_OVER, a clock-change night, unknown or stale data, CEILING_BELOW_MIN, HEADROOM_BELOW_MIN, DEMAND_UNKNOWN, ...) **whenever the rate in force is a finite number above 0 W, whatever the bookkeeping fields (changes used, time of the last change) say**, and also before the refusals for invalid parameters (the valid ones are kept, the invalid ones fall back to their defaults for the comparison) and for an unknown path (taken as one that cannot lower the rate; no profile report), against every KNOWN ceiling: the firmware bound, each named ceiling converted to setpoint units (a stale one still counts), and a known grid limit (with a fresh demand the headroom, without one the limit alone). `now.change` is `STOP`, no setpoint, no trajectory, no expected finish, margin or buffer that fits, `stopRecommended` true; the band, when the inputs give one, is the rate in force held (what happens if nothing is done). A refusal never says "the fallback holds whatever is in force" in that state; on a path that can lower the rate it says the rate must come down (`FORCED_BELOW_CEILING`) |
| `NO_NEED` | the reading is at or above the target (at 100 the `TOP_OF_CHARGE_TAIL` caution says the BMS may go on charging). With the Free Power lease in force the plan says the lease has no stop at a target SOC and keeps charging past the target, and that stopping it is the owner's choice (it used to say nothing is to be applied) |
| `INPUTS_UNUSABLE` | unknown, stale or implausible data, no fresh known ceiling, a known grid limit with no fresh demand, an invalid parameter or buffer, the window over, a rate in force above 0 W but below the minimum or off the step (`IN_FORCE_INVALID`), a last change after now (`INPUT_INVALID`), a call before the window with no drain bound (`PRE_WINDOW_DRAIN_UNKNOWN`), more than 2 minutes since the reading with nothing charging (no rate in force, before the window, or before the rate in force was set when that was after the reading) and no drain bound (`DRAIN_UNKNOWN_AGED_READING`): nothing is recommended and the codes say why |
| `CLOCK_CHANGE_NIGHT_REFUSED` | the window overlaps the hour a clock change skips or repeats (edges included): the real length is not known, so no plan, like the R9 schedule packages |

- **Window and deadline.** The window comes from the slot-table times in wall-clock minutes (`windowFromSlotTable` reads the one run of Grid slots from a
  native table; ambiguous tables give `null`). The deadline is the window end minus the buffer: default 60 minutes, 0 to 120 in steps of 5 (anything else is
  refused, never rounded). Before the window opens (`elapsedMin` negative) the plan starts at the window start. While nothing charges the battery it supplies
  the house, so the plan starts from the reading **less a pessimistic drain bound** (`drainBoundW`, battery-side W; the earlier name `preWindowDrainW` is still
  accepted, and when both are given they must agree), counted in the most points per kWh the bands allow (the smaller of the trusted and learned capacity)
  over the minutes since the reading in which nothing charged: before the window the reading's age plus the time to the window; inside it with no rate in
  force the reading's age (continuous at the window start); with a rate in force the part of the age before the window opened **and, when the rate was set
  after the reading (`inForce.lastChangeAtMin`), the minutes from the reading to it** (round 3 F1: a START made after the reading used to drop that drain; what
  ran before the set time is not known, and counting it idle is always the conservative way for the SOC, so a changed rate is covered too; a time of `null` =
  long ago counts none). Before the window the bound is required (`PRE_WINDOW_DRAIN_UNKNOWN`); inside it, beyond `maxUncountedDrainMin` (2 minutes) of such
  time (`DRAIN_UNKNOWN_AGED_READING`), and up to that the drain is not counted and the plan says so (`DRAIN_NOT_COUNTED`). The same minutes excuse a **fall**
  against `previousSoc` up to the drain bound (round 3 F7: a battery legitimately drains before the window; the tolerance of 3 points alone refused it). `assumptions` reports the start SOC (`socAtPlanStartPct`), those minutes and the
  drain counted.
- **Rate.** The lowest 100 W step, never below 500 W and never above the ceiling = the smaller of the firmware bound (8000 W) and the owner limit (one named
  ceiling, `maxChargePowerCeiling`; an unknown or stale-only ceiling is never guessed), whose **pessimistic** simulation reaches the target by the deadline. A
  battery-side or grid-side limit is converted down by the **setpoint overshoot allowance** (default 1.1, configurable 1.0 to 1.5; an owner decision). A known
  grid import limit caps the rate only with a fresh demand peak (never guessed: no demand gives `INPUTS_UNUSABLE`); an **unknown grid limit applies no cap
  and says so** (`GRID_LIMIT_UNKNOWN_NO_CAP`).
- **Taper: a measured shape, not a slope.** Flat plateau to a knee SOC, a fast fall (within a few minutes) to a low tail, the tail anchored to the plateau power
  **at the knee** (a later raise is never credited; a lower rate after the knee is never planned because it can only slow the tail). The **pessimistic** world
  has the earlier knee (`kneeSocPct`, default 90, configurable), the lower tail (`tailFraction` 1/8) and a one-minute fall; the expected world has the knee
  `kneeSpreadPct` (5) higher, tail 0.2 and a 5-minute fall; the optimistic one twice the spread, tail 0.33. The SOC at the real drop is **not known** (no SOC
  series was saved); with the default 90 a target above 90 is pessimistic by design and a 100 % target is almost always `TARGET_AT_RISK`. Whether the
  battery **may already be past** the knee is decided from the **optimistic estimate of the reading now**: reading + resolution/2 + noise **+ the charge
  possible since the reading** (its age at the rate in force, at the most realised power the bands allow, the overshoot allowance 1.1 x the setpoint, in the
  most points per kWh; nothing charges before the window opens; before a change made after the reading the rate is not known, so the firmware bound;
  `assumptions.chargeSinceReadingPct` and `kneeEstimatePct` report it). With the defaults and 31.7 kWh a reading of age 0 counts from 89 (88.87 when 1
  minute old at 2000 W), a 15 minute old one at 3000 W from 86.15. A rate in force is then held (`HELD_PAST_KNEE`) and the pessimistic world takes the **worse of its two
  consistent starts**: past the knee (at the knee or above, the fall over, the tail anchored at the lower of the rate in force and the rate tried: a raise
  inside the uncertainty is never credited) and not yet past it (on the plateau from the pessimistic start). A START, or a call before the window (nothing
  has charged yet, so a slot power set is not held), starts on the plateau with the knee crossed at the start rate (at the start itself, with the one-minute
  cliff, when the start is already above it): a START is monotone in the SOC, also for targets above the knee. **What the knee was crossed at** (round 3 F2): it is
  the rate in force, UNLESS that rate was set by an ordinary change (the record counts at least one, `changesUsed >= 1`) inside the window (after minute 0, or
  with no time given) while the knee may already have been passed when it was set (the reading plus the charge possible up to the change, optimistic, at or
  past the pessimistic knee of a target above it). An outside raise after the knee was crossed at a lower rate would otherwise be credited at the new rate
  while the battery stays on the old low tail (the review: 2000 W raised to 8000 W, reading 91, target 95: OK, margin 94.5; the truth needs 7.7 hours). The
  earlier rate is not in the record, so the pessimistic tail is anchored at the **lowest setpoint** any path can hold (the worst case; `KNEE_RATE_UNKNOWN`), and
  OK needs the deadline to hold even then. A START (`changesUsed` 0), a change before the window opened, a target at or below the knee and a call before the
  window are not affected. The cost: after any counted change with the reading within about 1.5 points of the knee OK is withheld even when the knee was in
  fact crossed at the new rate (the planner cannot tell its own raise from an outside one); a caller that knows the knee-time rate could be given an input for
  it later (none is built). **The three policy worlds of the band are scenarios, not bounds** (round 3 F4): each re-plans from its own measured SOC, so on an
  adaptive path a world that is behind can raise a rate that a world that is ahead holds, and their finishes can come out of order; with the rate held
  (`pessimisticHeld`, every flat path) pessimistic >= expected >= optimistic holds. The SOC at the deadline is **floored** to a tenth, never above the
  target (a rounded value showed the target for a world that had not reached it); after the deadline it is the SOC now. A world that starts at or above the
  target has finished NOW (no finish lies before now or before the window opens).
- **Inputs and bands.** SOC with its age (15 minutes), the usable capacity (the trusted helper, the larger of it and a learned figure for the charge, the
  smaller for the drain and the charge since the reading, plus a 6 % band), charge
  efficiency 0.95 (band 0.90 to 0.97), the sensor scale error (3 %), the reading resolution and noise (the pessimistic start is the reading minus half the
  resolution minus the noise allowance), the limits and household readings with their ages. Every parameter is a number inside stated bounds or the plan is
  `INPUTS_UNUSABLE` (`PARAMS_INVALID`), never silently defaulted.
- **Profiles (the trajectory honours the selected path).** `FREE_POWER_LEASE`: no change after the start, one flat rate. `TOU_SLOT_EDITOR`: at most one
  coarse change, 60 minutes dwell, each needing the owner's typed confirmation. `RATE_CONTROLLER_PROPOSED` (does not exist): up to 6 changes, 30 minutes
  dwell. `UNCONSTRAINED`: the generic model (6, 30), only when named. **With no path named the most restrictive path that exists, `FREE_POWER_LEASE`, is
  assumed and said** (`PROFILE_DEFAULT_MOST_RESTRICTIVE`). **The plan is genuinely adaptive only under the rate-controller profile and says so**
  (`profile.adaptive`, `adaptiveNote`). The trajectory is the closed-loop **policy** run on the expected world; every point after the first is `conditional`
  (re-computed from the measured SOC at its time), never a commitment.
- **Closed loop.** Call it at every re-plan tick with the measured reading and what is in force (`inForce`: rate, time of the last change, changes used). It
  holds a change that dwell, budget or the path forbids (`HELD_DWELL`, `HELD_BUDGET`, `HELD_PATH_FIXED`), holds the rate once the knee may be passed
  (`HELD_PAST_KNEE`), forces a rate above the ceiling down whatever the budget says (`FORCED_BELOW_CEILING`; on a path that cannot change it after the START
  a `STOP` instead, `ACTUATOR_FIXED_RATE`), plans a decrease only when it saves at least 500 W and keeps 15 minutes of slack, and never lowers the rate when
  the target is at risk. A rate in force of 0 W is "not charging": the answer is a START (`IN_FORCE_ZERO_NOT_CHARGING`). A last change later than now is
  refused. What `needed` says follows the change (on the TOU editor: a START before the window or now, a KEEP with nothing to change, an ordinary change, a
  forced decrease as soon as possible whatever the dwell). The realised power is not an input yet: after the knee the plan holds the rate instead of reading
  the fall (open item for the rate-controller design).
- **Tests.** `test/gentleNight.test.ts` (unit, by-hand arithmetic, seeded property sweeps), `test/gentleNightClosedLoop.test.ts` against an **independent
  truth battery** (`test/support/gentleNightTruth.ts`, imports nothing from `src/`: energy in kWh in half-minute steps, the sensor anchored at full,
  AC or DC setpoint unit drawn at random, random knee, tail and fall, capacity +-6 %, efficiency 0.90 to 0.97, scale +-3 %, reading noise and quantisation,
  shortened windows; a `KNEE_MIDWINDOW` family starts within a few points of the knee with an outside rate in force, half of it in the envelope's worst knee
  corner with a low-reading sensor; a `KNEE_MIDWINDOW_AGED` family gives the first call a reading 10 to 15 minutes old, and in half its nights the outside
  rate crosses the knee AFTER that reading; `drainTo` drains the battery to the house), `test/gentleNightSafety.test.ts` (each finding of the independent
  review of 25 Nov 2026 and of its confirmation review pinned by a by-hand value: one test per refusal path for the STOP, each surviving mutant of the
  confirmation review killed by a behavioural assertion), `test/gentleNightGolden.test.ts` (the older model pinned) and `test/gentleNightMutants.test.ts`
  (186 single-line mutants, each killed against the **committed** golden probe `test/gentleNightProbe.golden.json`, which the real source must also equal;
  regenerate it only for a reviewed change with `node test/support/writeNightProbeGolden.ts`). **Mutation score against the behavioural assertion suites
  alone** (the four suites above, without the probe): 186 of 186 killed, measured by `python -I -B tools/night_mutation_score.py` (one Node process at a
  time, a private copy of the package). The third review's 34 new mutants (H01 to H34): 14 were killed by the suites before the round 3 tests; 30 of them are now in the list (ids
  `R3 H..`), each killed by the suites alone. The other four need no test: H02, H07 and H29 are equivalent (H02: once a world that starts at or above the
  target finishes at once, the clamp it mutates can never act; H07: `pessFinish` returns nothing unless BOTH starts reach by the deadline, and its value is
  only compared with the deadline, so taking the earlier of the two cannot change an answer; H29: a decrease is only made while the knee is surely ahead,
  so the expected and optimistic worlds never start past their own knee at a lowered rate) and H09 is now the code itself. The list also holds the
  mutants of the round 3 fixes themselves (`R3 F1` to `R3 F9`).
- **What the closed loop shows, and what it does not.** Inside the declared envelope a night that is `OK` at the first call makes the deadline in the truth
  battery in every seeded night: in the worst corner of the envelope, near the knee with an outside rate in force, with a first reading 10 to 15 minutes old
  whose knee was crossed after it (0 misses), and for a START from a 15 minute old reading while the house drains the battery at 3000 W (at -0.5, 0 and
  +0.5 minutes from the window start). Inside the envelope (a realised power at most the overshoot allowance times the setpoint) no raise is recommended once
  the truth is past its knee, for readings up to the age limit, because the charge possible since the reading is counted. Round 3 adds two corners, on the same
  independent truth battery: a lease STARTed AFTER the reading while the house draws the 3000 W bound (OK only when the truth makes the deadline, for rates
  from far below to a little above the planner's own START, at both scale errors, targets 58 and 80, START 1, 7 and 14 minutes in), and an outside raise
  after the knee was crossed at 1000 to 3000 W (the truth tail stays on the old rate): of 193 planned nights the earlier source called 167 OK and 30 of them
  missed, now none is called OK (the truth made 144 of them: the price of the worst case, see the taper paragraph). Still not covered: a START after an earlier
  charge in the same window crossed the knee.
  Outside the envelope (knee from 85, tail from 0, a trickle) only the safety invariants are claimed.
- **Not known, and said so in every plan (`unknowns`):** the setpoint unit (AC grid watts, DC battery watts or amps), the BMS response at rates below the top
  rate (no data), the SOC at the taper drop, the live BMS limit, and the rate at which the knee was crossed when the rate in force was changed inside the window
  while the knee may already have been passed (the tail is then taken at the lowest setpoint). The
  plan treats the setpoint as grid-side watts for the energy, which is the pessimistic reading under either unit. The expected and optimistic worlds of the
  band start from the reading itself: the charge since an aged reading is counted only for the knee, so their finish is late by up to that charge. What
  would be needed to apply a rate is in `needed` (the owner's guarded editor, the Free Power start, or a rate controller that must first pass the proofs in
  [`GENTLE_LIVE_ACTUATION_PROOF.md`](GENTLE_LIVE_ACTUATION_PROOF.md)).

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
3. Before any step that creates entities (R9 adds two helpers; this change adds the plan helpers, three scripts and two sensors): decide how Home Assistant's voice assistants treat new entities and read the exposure list read-only (release gate RG-F3: anything an assistant or the dongle's API key can reach can drive the dongle's arm and Start controls). Nothing created here is meant to be exposed to an assistant.
4. Install `ecco_plan_helpers.yaml`, `ecco_dump_to_grid_guarded_start.yaml` and the changed `ecco_dump_to_grid_schedule.yaml` in the SAME deployment, then ONE full Home Assistant restart. The order of the three copies does not matter: until the plan helpers are installed and Home Assistant has restarted fully, every scheduled start and every guarded start is refused (fail closed). The first start seeds the accepted limits; the confirmation switch stays off.
5. Look at the eight limits on the helpers page; turn on `ecco_plan_overrides_enabled`.
6. Copy the rebuilt card bundle (`frontend_assets` entry; resource already registered), clear the browser cache, set `show_plan: true` and `dump_to_grid.guarded_start: script.ecco_dump_to_grid_start_guarded`. Until `dump_to_grid.guarded_start` is set, the card's own Start button presses the dongle's button directly (known limitation 5), so no override binds it.
7. Supervised check: start and cancel Hold battery; a scheduled start that must be refused; the manual start refused during an override and accepted after.
8. Optional, after the acceptance run ends: map Intelligence's `reserve.ha_minimum_soc` to `sensor.ecco_plan_effective_reserve` (site check first).

### What is the owner's

Every value above (changeable in the helpers), whether and when to install each step, the Intelligence mapping, a firmware gate for the dongle's
own Start button, and whether to enrol the card's `tsconfig.json` in the pin chain.
