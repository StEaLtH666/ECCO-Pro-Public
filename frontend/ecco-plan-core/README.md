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
- Override expiry defaults, caps and the power-cut reserve (the design documents give examples: Hold cap 48 h, Prepare cap
  72 h, reserve 80 %) are owner choices supplied through `OverridePolicy`.
- Baseline slots a derived interval does not cover stay exactly as the owner set them (for example a longer native grid-charge
  slot is not shortened to a shorter derived window); that can cost an extra slot and is then reported as infeasible.

## Stage 2 (not part of this change)

Wire read-only views into the existing cards behind a default-off configuration flag: Tomorrow's Plan, the shared-settings
preview and the override chips, reading the entities the cards already read. No write path changes. Stage 3 (separately
authorised, with the reserve and grid-loss gates proven) would route plan actions through the existing guarded editors.
