# Energy Plan UI: sequenced roadmap (phase 1, offline design)

**Status: PLAN ONLY. No dates.** Each stage starts only after its listed prerequisites have passed their gates **and** the
owner says go for that stage. A stage may be split or dropped; none is promised. Nothing here authorises a live change.

The evidence behind the stage boundaries is in [FEASIBILITY_MATRIX.md](FEASIBILITY_MATRIX.md); the design is in
[UX_CONCEPT.md](UX_CONCEPT.md).

## Standing rules for every stage

- The live SHADOW acceptance and the protected live dashboard are never disturbed. Dashboard deploys go only through the
  gated deploy tool, with the dashboard preservation gate passing and a rehearsed rollback.
- No stage weakens a safety gate, lowers the 10 % export floor, adds a raw inverter write path, or enables automated
  actions by itself. **A profile or mode switch never enables an automated inverter action**; it changes preferences only.
- Every live step, including installing new helpers or read-only sensors, is its own gated live step with an owner
  authorisation, a kit, a rollback and read-back verification; one live change at a time.
- One independent review per change (more for safety-critical firmware), the private-pattern scan before any push, and one
  CI run per PR. Offline and mock-only work uses local checks; CI runs once, at PR time.

## Stage 0: offline design (this branch)

**Done here:** feasibility matrix, UX concept, interactive offline mock (bannered as a design mock, every widget tagged)
with its own checks, this roadmap.

**Gate to leave:** owner review of the design; owner decision on the open questions below.

## Stage 1: visual-only improvements

**Prerequisites:** the SHADOW acceptance gate has closed; the owner chooses to proceed.

**Scope (presentation only):**

- The Energy Actions card presents *Charge Battery* and *Export to Grid* as two sibling masters with Now / Schedule tabs and
  always-visible state chips. Entity ids, scripts and firmware are unchanged.
- A read-only 24-hour TOU timeline card bound to the existing read-only slot entities (no plan overlay yet).
- Home and Advanced grouping, delivered as **new views**: the protected Overview dashboard is not edited, and nothing the
  SHADOW acceptance reads is changed, unless the owner approves a separate migration and rollback plan.
- **No Smart Target tab** in this stage. Smart features appear only from Stage 2, so nothing that does not work is shown on
  a live dashboard.

**Gate:** public PR with CI and one review; private-pattern scan; dashboard install through the gated tool with the dashboard
preservation gate passing and an exact-bytes rollback; owner's look on a phone.

## Stage 2: shadow planning and simulation

**Prerequisites:** Stage 1 settled.

**Scope (read-only; installing the helpers and sensors is itself a gated live step):**

- One canonical set of plan helpers (target, buffer, mode, maximum power, export target, finish mode, handover gap, profile)
  with no duplicates.
- Read-only planner sensors for Gentle Overnight, Smart Export, the linked export-to-charge cycle and the compiler preview.
  They publish the plan and its refusals; they never stage, arm or press anything.
- **Until Stage 3 has measured them, the gentle rate and the handover gap are labelled "simulated, not yet measured"**, and
  predicted finish times are shown as estimates, never as promises.
- The plan overlay on the TOU timeline, the Review sheet with no Apply at all, and drift detection against readback.
- Intelligence emits a *proposed plan* in the same schema; adopting it creates an inert draft that cannot trigger anything.
- Summer Solar Priority as SHADOW advice with confidence gating, replay and backtest (wrong forecasts, morning shade, low
  generation, clock-change days, stale data).

**Gate:** offline suites and replay results; one review; owner install go; a shadow period in which the predicted plan is
compared with what actually happened (charge finish times, export end SOC, gaps), reported in plain words.

## Stage 3: supervised hardware evidence (no new automation)

**Prerequisites:** the SHADOW acceptance has closed and Stage 1 is settled; never during an acceptance run.

Read-back measurements that later stages depend on. They use **only existing guarded paths** (the guarded slot editor and the
existing Free Power and Dump transactions), add no write path, never touch the 10 % floor, and each is its own owner go: a
supervised session with a kit and an exact-bytes rollback of anything changed.

- Grid-charge response to two or three fixed slot powers below the current value (does the charge rate follow, how fast).
- Restore durations for Dump and Free Power under normal bus load (to size the handover gap). Each run is a real lease and
  starts only with no recovery obligation open.
- **Separate owner decision, not part of a default Stage 3 go:** higher Dump command ceilings, only by the procedure in
  `docs/dev/dump-to-grid-ceiling.md`.

**Gate:** measurements recorded; the planners' constants updated offline from them; review.

## Stage 4: ASSISTED (owner-supervised execution)

**Prerequisites:** Stage 2's shadow period; Stage 3's measurements for every capability that depends on them (the gentle rate
and the handover gap); and, for Smart Export, a supervised live proof of the scheduled Dump to Grid path, which is marked
NOT LIVE-PROVEN today.

**Scope:** a plan executor that turns an owner-approved plan into existing actions only:

- Gentle Overnight: at most one slot power edit and one target edit through the existing guarded editor, with the owner's
  Review and typed confirmation, and hysteresis so that edits are rare.
- Smart Export: the existing scheduled Dump fields, staged by the executor and armed by the owner; capped at the
  hardware-tested command ceiling.
- A manual native TOU edit is refused while the executor holds a pending action; drift always stops the executor.

**Gate:** an independent safety review of the executor covering: one queue with one action in flight; a derived owner
sensor that fails closed on any unknown state; the priority order (stop and restore, active transaction or recovery, owner
manual action or pause, confirmed plan, advice); coordination with SMR1, which shares the request numbers. Then offline
proofs, the private-pattern scan, CI and a separate owner commissioning for each capability with a supervised first run.

## Stage 5: new behaviour that needs its own design (only if still wanted)

Each a separate change with offline proofs, an independent review and a supervised live proof; firmware changes are flashed
only with no recovery obligation open:

- **Smart Charge (daytime goal).** Free Power has no stop at a target SOC today. Stopping at the target, whether by an HA
  step that presses the existing End control automatically or by a firmware stop, is a new unattended decision and is
  designed and reviewed here, not in Stage 4.
- A Free Power rate controller (durable intended-value updates, bounded cadence and step, write budget), after Stage 4 has
  proved fixed-rate gentle charging.
- Bounded Dump re-targeting during a lease.
- An end-side guard before the next charge slot, and DST-aware slot arithmetic.
- Optionally, a firmware-published "who owns the inverter" entity.

## Stage 6: autonomy evaluation

Per capability, and only after that capability has passed its Stage 4 supervised run and any Stage 5 proof it depends on,
has run long enough to judge, has had long-run hardware validation, **and** has an independent safety review of unattended
operation **and** a separate owner commissioning. Unattended mode is never a default, the owner can pause or override at any
time, and the safety order (stop and restore first) never changes.

## Parallel, independent track: energy-flow views

A private house scene as a selectable view beside the public scene and a compact schematic needs, before any public
distribution: the owner's review of the exact asset set, removal of metadata and anything identifying, and explicit
confirmation; and, before any change to the protected live dashboard, a tested migration and rollback plan. It is not part
of this branch.

## Open questions for the owner (to batch with the Stage 0 review)

1. Card names: *Charge Battery* and *Export to Grid* (recommended), or *Sell Power to Grid*.
2. Default finish-before-end buffer (mock default 60 min, editable 0-120 min; not a commitment).
3. Default handover gap before charging (mock default 30 min, minimum 10 min until restore durations are measured; not a
   commitment).
4. Whether to schedule the Stage 3 measurements as soon as the SHADOW acceptance closes, since they gate Stage 4.
