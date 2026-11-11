# Energy Plan UI: feasibility matrix (phase 1, offline design)

**Status: DESIGN ONLY.** Nothing in this document is implemented, installed or authorised. It records what the existing
source can and cannot do for each capability the owner asked for, so that later phases start from facts. Every claim cites
the source tree this branch was cut from (`c6e5a58`). Where the public record has no evidence, the entry says **UNKNOWN**
rather than guessing. Proof levels use the project's own vocabulary (`SUPPORTED_HARDWARE.md`:13-14): *hardware tested* is
not *production proven*.

## How to read the citations

| Alias | File |
|---|---|
| FW | `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` |
| RTC | `firmware/include/ecco_rtc_policy.h` |
| FPS | `home-assistant/packages/ecco_free_power_schedule.yaml` |
| DGS | `home-assistant/packages/ecco_dump_to_grid_schedule.yaml` |
| TSE | `home-assistant/packages/ecco_tou_target_soc_edit.yaml` (ACS1C + ACS1X guarded slot editor) |
| TOU | `home-assistant/packages/ecco_tou_schedule.yaml` |
| SMR | `home-assistant/packages/ecco_schedule_manual_restore.yaml` |
| RCF | `home-assistant/packages/ecco_runtime_config.yaml` |
| TSC | `frontend/ecco-tou-settings-card/src/model.ts` |
| EAC | `frontend/ecco-energy-actions-card/src/` |
| IC | `frontend/ecco-intelligence-card/ecco-intelligence-card.js` |
| INT | `intelligence/` |
| SAFETY | `SAFETY.md` |
| HW | `SUPPORTED_HARDWARE.md` |

`FW:9093-9097` means lines 9093 to 9097 of FW.

Three columns of feasibility are used throughout:

- **Today**: what the existing firmware and Home Assistant entities already implement, unchanged, with their proof level.
- **New protected HA scripting**: Home Assistant work that adds no new inverter write path. It may read, plan, explain, and
  (only in a later, separately authorised phase) stage values into the existing firmware transactions or the existing
  guarded slot editor, which keep every one of their gates.
- **Firmware + live evidence**: anything that changes what the controller writes, when, or how it restores, or that relies
  on inverter behaviour the public record has not measured. These need a firmware change, offline proofs, a supervised
  hardware proof and a separate owner commissioning.

## 1. Summary

| # | Capability | Today | New protected HA scripting | Firmware + live evidence | Earliest phase |
|---|---|---|---|---|---|
| 1 | Gentle overnight charging with an editable finish-before-end buffer | Partly: one **fixed** grid-charge slot power and target SOC can be set by hand with the guarded editor (offline source; the acs1x review re-check is pending; no live proof of a power edit in the public record) | Planner (read-only) that computes the lowest fixed rate that finishes `buffer` minutes early; later an owner-reviewed proposal of at most two single-field slot edits | Live characterisation of the inverter's grid-charge response to low slot power; any rate change *within* the night is row 2 | Shadow planning, then Assisted |
| 2 | Variable charge rate during a lease | **No**: Free Power fixes its rate at START and verifies against it | Chains of short leases: possible but **not recommended** | A Free Power rate controller (pattern: the Dump V1.1 controller), durable intended-value updates, write budget, live proof | After Assisted proves row 1 |
| 3 | Smart Export to a target SOC by a deadline, keeping the >=10 % floor | **Implemented in firmware for a fixed net export rate chosen at START** (tracks net export, stops at Stop SOC or the duration). Manual Dump is hardware tested in two scenarios at 3000 W; the **scheduled Dump package is not live-proven**; other paths offline only | Planner (read-only) that computes start, rate, duration, ETA and feasibility; later stages them into the scheduled Dump once that path is live-proven | Re-targeting during a lease; ceilings above the hardware-tested 3000 W | Shadow planning, then Assisted |
| 4 | Export finishing before the next charge window, with a handover gap | Partly: firmware and HA refuse a Dump whose window, end minute included, overlaps a charge slot; no gap concept | Derive the end from the next grid-charge start minus the gap; refuse a short gap; alert if a restore is still owed near the charge start | An end-side guard re-checked during the lease; DST-aware slot arithmetic; measured restore durations | Shadow planning, then Assisted |
| 5 | Deterministic schedule compiler / arbiter into the six native TOU slots | Read-only slot adapter; guarded edits of **one setting of one slot**, no durable rollback | Pure, offline-tested compiler that emits zero or a few single-field edits (each its own Review / confirm / Apply) or an explicit refusal | Atomic multi-field slot writes with a durable snapshot would be new firmware (not proposed) | Shadow (compiler output only), then Assisted |
| 6 | Single-writer / transaction-ownership invariant | Enforced pairwise in firmware and at the HA gates | One plan executor and one derived "owner" sensor; every planned action goes through it | Optional: a firmware-published owner entity | Before any Assisted action |
| 7 | Summer Solar Priority with confidence gating | Ingredients exist in Intelligence (PV correction, learned useful-PV start, reserve-aware Dump advice), advice only | New SHADOW advice item with confidence gating, replay and backtest; execution would reuse row 3 | Rates above 3000 W; nothing new for Shadow | Shadow (advice), Assisted much later |
| 8 | Intelligence as planner over the two cards | SHADOW advice entity, advice only, no write path | A versioned "proposed plan" entity in the same schema as the owner's plan; adoption is an owner action | None | Shadow, then Assisted |

The rest of this document gives the evidence for each row.

## 2. Row by row

### 2.1 Gentle overnight charging with an editable finish-before-end buffer

**What exists today**

- The six-slot table is readable without writes: TOU:1-8 describes the read-only adapter and its per-slot sensors start at
  TOU:17; the Dump arm check reads each slot's `_time` and `_charge` sensors (DGS:603-605).
- A native TOU slot's power register is the battery charge / discharge ceiling (FW:9725-9735, comment on the post-reboot
  characterisation); slot target SOC, charge source and mode are registers 268-279 (SAFETY:17). How the inverter stops at
  a slot's target SOC is inverter-native behaviour, not ECCO code.
- The guarded slot editor can change **one** of target SOC, power (500-8000 W, multiple of 100), start time or charge source
  of **one** slot per request (TSE:12-28), through Review, typed confirmation, Apply and verified readback (TSE:36-51).
  **Proof level in the public record:** the editor and its acs1c / acs1x corrections are documented as offline source, not
  installed and not live-proven (`CHANGELOG.md`:60-61, 73-74, 101-102; `docs/dev/acs1c-cyclic-tou.md`:3;
  `docs/dev/acs1x-crossing-hold.md`:3). The public record has no live proof of a slot power edit.
- So a gentler **fixed** overnight rate is only a manual, per-slot edit. Nothing computes the rate, and nothing knows about a
  finish-before-end buffer: that is an ECCO planning idea with no inverter register.

**What needs new protected HA scripting**

- One canonical set of plan preferences (target SOC, buffer minutes, maximum charge power, strategy). A maximum grid-charge
  power helper already exists (`input_number.ecco_max_grid_charge_power`, `home-assistant/packages/ecco_pro.yaml`:76) and
  should be reused rather than duplicated; there is no helper for the buffer or the strategy.
- A read-only planner sensor: the grid-charge window from the slot table, `finish_by = window end - buffer`, the energy
  needed from the expected start SOC and the usable capacity, and the **lowest fixed rate** that finishes by `finish_by`
  (rounded up to the editor's 100 W step, never below the editor's 500 W minimum, TSE:14-15). The rate is capped by the
  smallest of: the owner's maximum; the inverter's configured battery maximum charge current times the battery voltage
  (`ECCO Battery Max Charge`, FW:8313-8319); the grid-charge current setting times the battery voltage
  (`ECCO Grid Charge Current`, FW:8387); and the existing `sensor.ecco_config_maximum_grid_charge_power` (RCF:80-84, used by
  FPS at its start gate). It publishes the predicted finish time, the time the battery would then sit at the target, and
  an honest infeasible state when the capped rate cannot reach the target.
- Assisted (a later phase): the planner proposes at most two single-field edits (the grid-charge slot's power and, if it
  differs, its target SOC), each through the existing guarded editor with its own Review and confirmation. Because the
  start SOC differs every night, a hysteresis band (proposal: no new proposal unless the rate changes by 500 W or more) keeps
  edits rare. That respects the owner's "minimal repetitive decisions".

**What needs firmware or live evidence**

- **UNKNOWN in the public record:** how closely the inverter's grid-charge power follows a low slot power, and how it
  interacts with the grid-charge current setting. The only low-power observation cited in source is for Dump discharge
  (500 W lowest observed, 0 W never characterised, FW:304-314). A supervised, read-back test at two or three fixed slot
  powers is needed before any rate proposal is trusted.
- Battery limits: the inverter's **configured** battery maximum charge / discharge currents and shutdown SOC are published
  read-only (FW:8313-8330). The battery's **live, dynamic BMS limits** (for example temperature derating) are not published:
  **UNKNOWN** to ECCO. Battery temperature is published (FW:7644) but no policy uses it. Slower is not automatically
  healthier or cheaper; the planner must not claim it.
- Usable capacity: Intelligence has a configured nominal capacity (INT `config.py`:67) and a learned one
  (INT `site_decisions.py`:342) whose re-render cadence is still unresolved (INT `site_decisions.py`:955-957). For a
  finish-by **charge** plan, use the **larger** of the two, so that the rate is not too low and the plan does not finish
  late; show the difference.

### 2.2 Variable charge rate during a lease

**What exists today: no variable rate.**

- Free Power's power and duration numbers are staging values (FW:5299-5322); at START the firmware converts the staged
  watts once into a grid-charge current, `amps = W / V`, capped at the original register 230 value (FW:9093-9097), and
  overlays that wattage on all six slot powers (FW:9098-9108).
- The durable record stores the original values and these **intended** values (FW:9110-9142); activation succeeds only if
  every owned register equals its intended value, all six slot SOCs read 100 and the grid flag is set (FW:9736-9760).
- The restore classifier compares the live registers with "original" and "intended" and, on "neither", writes nothing and
  requires an operator decision (FW:2568-2573, FW:11071-11108). A rate change made from outside during a lease would
  therefore block automatic restore. Changing the staging number during a lease changes nothing on the inverter.
- The scheduled Free Power package stages one fixed power and one duration and presses START (FPS:193-205, FPS:231).
- Free Power has **no stop at a target SOC**: it charges toward the SOC = 100 envelope for its duration (FW:9746). A daytime
  "reach X % by T" goal needs either an HA step that presses the existing END FREE POWER control when the target is reached
  (FW:23202-23210; no new write path, but a new unattended decision) or a firmware stop. Both need their own design review
  and live proof.

**New protected HA scripting: possible only as a chain of short leases, not recommended.** Each lease is a full snapshot,
write, verify and restore of about twenty registers; chaining them multiplies writes and restore windows, and the shared
request numbers would interact with SMR1's restore of the owner's manual values (SMR:3-12).

**Firmware + live evidence (the right home).** A Free Power rate controller modelled on the existing Dump V1.1 export
controller, whose limits are the template for a safe cadence:

| Dump V1.1 control rule | Value | Source |
|---|---|---|
| deadband | 150 W | FW:221 |
| proportional gain | 0.5 | FW:226 |
| maximum change per step | 1000 W | FW:230 |
| minimum time between controller writes (settle) | 45 s | FW:286-296 |
| rounding | 100 W | FW:303 |
| lowest commanded ceiling | 500 W | FW:304-314 |
| START-only feed-forward limit | 2000 W | FW:315-326 |
| write budget per lease | 120 | FW:345-355 |
| evaluation cadence | about 15 s (watchdog) | FW:385-386 |

A gentle charge needs much less: a re-plan every 5-15 minutes with a hysteresis of a few hundred watts is enough. The
controller must update the durable intended value **before** each write (the Dump controller's save-before-write commit,
FW:3864, FW:19297), keep the SOC = 100 envelope rules (FW:9746) and be live-proven for charge-power response time, BMS
current limiting and temperature derating. Until then, the UI may show a variable rate only as a **simulation**.

A native alternative, a stepped profile across two or three TOU slots, uses slot partitions (six in total), start-time
edits (the card keeps them locked, TSC:83-84) and the midnight-crossing hold (TSE:22-24). It is a possible long-lived
layout, never a nightly adjustment.

### 2.3 Smart Export to a target SOC by a deadline, keeping the >=10 % floor

**What exists today: a fixed-rate goal is implemented in the firmware; its proof is partial.**

- **Proof level:** Dump to Grid is "hardware tested for two scenarios, at the default 3000 W command ceiling; offline only
  for every other path" (HW:41). The scheduled package is marked NOT LIVE-PROVEN (DGS:10). The command ceiling is 3000 W by
  default and only 3000 W is hardware tested (SAFETY:30; FW:246-256); higher values need the supervised steps in
  `docs/dev/dump-to-grid-ceiling.md`.
- "Dump to Grid Export Power" is a **target net grid export**; the controller derives the battery ceiling from measured grid
  power (FW:5324-5337). Net export is not battery discharge: the house load and PV sit between them, and the battery's DC
  power exceeds the AC command by about 7-12 % on the reference system (FW:40-49).
- The target export and the Stop SOC are **latched at START for the lease** (FW:18153-18167); the lease's ceiling is latched
  too (FW:18168-18171). The in-lease monitor ends the lease when SOC reaches the latched Stop SOC (FW:24458-24467). After
  END, while a restore is still owed, the configured Stop SOC number is read again and a **higher** value also applies
  (FW:24178-24182; SMR:10-11); a planner must not write the Dump request numbers while a Dump snapshot is pending
  (SMR:10-12).
- The lease also ends at the duration (1-240 min, FW:5523-5533, FW:18914, end reason FW:24248), on the manual End button
  (FW:24009-24015), and early, failing closed, on: a net-export guard trip, frozen or stale telemetry, configuration drift,
  stale configuration readback, the runaway guard or an exhausted write budget (for example FW:24340-24349,
  FW:24420-24424, FW:24450-24457).
- START refuses a Stop SOC outside 10-90 % (FW:5350-5366, FW:18913; DGS:61-64, DGS:118-125), a SOC already at or below the
  Stop SOC (FW:18911), a request within max(100 W, 3 %) of the configured maximum grid export (FW:18915-18918), and a grid
  meter already exporting above that maximum (FW:18919). **5 % is refused.** Dump does not use the battery reserve
  (SAFETY:112-116).
- The scheduled package takes one start date-time, a duration, a power and a Stop SOC (DGS:39-64), stages them into the
  firmware (DGS:200-215, DGS:245-248) and retries a refused start for up to 10 minutes, shortening the staged duration so
  that the session still ends by the window end (DGS:26-29).

So "export down to X % by T" maps onto: a start; Stop SOC = X; duration = T - start (<= 240 min); and a **fixed** net export
rate computed from the energy above X, the expected house load and the time available. The firmware stops at X if it gets
there first; otherwise it stops at T with a higher SOC, or earlier on any protective end.

**New protected HA scripting**

- A read-only Smart Export planner. Its floor is **max(10 %, the live inverter shutdown SOC)** (`ECCO Battery Shutdown`,
  FW:8329-8330), and it refuses to plan when the shutdown SOC is unreadable, as the slot editor does for target SOC
  (TSE:241); it warns, without refusing, below the reserve helper `input_number.ecco_minimum_reserve_soc`, in line with
  SAFETY:123-124. It computes the energy above the target, the required average battery power, the net export rate that
  implies, capped at the configured maximum export minus max(100 W, 3 %) and at the hardware-tested battery ceiling minus
  the house load; the ETA, allowing for a late scheduled start and early protective ends; the end SOC if a cap binds; and a
  clear refusal below the floor. It never presents Intelligence's advisory 40 % planning reserve (INT `config.py`:10-14)
  as a hard floor, nor the 10 % floor as a statement of battery safety (SAFETY:112-116).
- Assisted (later, after the scheduled Dump path is live-proven): the planner fills the existing scheduled Dump fields; the
  owner reviews and arms. No new write path.

**Firmware + live evidence**

- Re-targeting during a lease (the owner's "auto adjust speed") needs a firmware change, because the target is latched
  (FW:18153-18165). A bounded re-target at no more than the controller's settle cadence, only toward lower export, re-checked
  against the maximum export, is the shape to evaluate.
- There is no modulation lever today. A **reduction** of the persisted Dump Power Ceiling lowers the lease's ceiling at once
  (FW:5368-5376, FW:5425; stepped down at the next controller tick, FW:18973-18985), but the value is persisted
  (FW:3514-3517) and raising it again needs the separate arm and an idle Dump. Lowering Max Grid Export during a lease is
  accepted (FW:5463-5474), but the export guard reads the live value (FW:7907-7915), so it ends the lease rather than slowing
  it.
- Rates above 3000 W need their own supervised proof (FW:246-256).

### 2.4 Export finishing before the next charge window, with a handover gap

**What exists today**

- The firmware refuses a Dump START when any minute of `now .. now + duration`, **the end minute included**, falls in a
  slot whose charge source is set (FW:18006-18046, loop `k <= dur` at FW:18033; refusal text FW:18905-18910). The scheduled
  package refuses to arm the same overlap, also end-inclusive (DGS:600-640). A lease ending exactly at the charge slot's
  start is refused, but the margin left can be under a minute.
- Armed Free Power and Dump schedules may not overlap, with a 2-minute buffer (FPS:546-572, DGS:571-590).
- Free Power refuses to start while a Dump lease or snapshot is owed (FW:9932); a manual TOU Apply is refused while either
  owns the TOU settings (FW:14115 and its sibling copies).
- There is **no handover gap** concept beyond that.

**Things the gap has to cover**

- **Restore time.** The restore is firmware-owned and retried (SAFETY:85-90). The public record has no distribution of
  restore durations: **UNKNOWN**. While a Dump restore is owed, ECCO keeps its TOU power registers contained at the floor
  (FW:24168-24173), so a charge slot starting then would run on Dump-owned values.
- **Clock tolerance.** The inverter acts on its own clock, which runs at a PV-dependent rate and whose register image can be
  stale (RTC:12-15); the RTC policy holds corrections around zone starts and during transactions, except corrections of
  300 s or more, which are never deferred (RTC:17-23, RTC:46).
- **The inverter starts its own grid-charge slot regardless of ECCO.** If a Dump restore were still owed at that moment,
  ECCO could not hold the slot back. A plan can only finish early enough; it cannot "wait for restore" at the charge start.
- **Clock-change nights.** The firmware's overlap check uses minutes of local time modulo 1440 (FW:18030-18041), which is
  not DST-aware across a clock change.

**New protected HA scripting**: derive `export end = next grid-charge start - gap` from the read-only table; refuse a gap
below a minimum (proposal: 10 min, to be set from measured restore times plus a clock margin); refuse a duration above
240 min by starting later instead; refuse an export whose finish falls after the next charge start; an alert, with no write,
if a Dump restore is still owed shortly before the charge start.

**Firmware + live evidence**: an end-side guard that re-reads the slot table during the lease and ends it a configured
margin before the next charge-source slot; DST-aware slot arithmetic; measured restore durations.

### 2.5 Deterministic schedule compiler / arbiter into the six native TOU slots

**What exists today**

- Read-only slot adapter (TOU:1-8, sensors from TOU:17) and the guarded editor: one setting of one slot per request (TSE:1,
  TSE:12-28), with the proof level stated in 2.1.
- Rules a compiler must obey, all enforced by the editor's gate:
  - for every setting: no edit while Free Power or Dump owns the slots (TSE:260-263) or another write or fallback operation
    is in progress (TSE:264); the fallback live match must be MATCH, DRIFT or CONTEXT with no open obligation
    (TSE:270-273); no edit while a scheduled start script runs or an armed schedule starts within 15 minutes (TSE:285-287);
    no edit on clock-change nights 00:00-03:00 (TSE:29, TSE:256); no edit while an earlier outcome awaits the owner's review
    (TSE:236);
  - target SOC: at least the greater of the inverter shutdown SOC and the ECCO reserve (TSE:241);
  - start time only: the 5-minute grid; one 24-hour cycle in slot order with exactly one wrap past midnight and every slot at
    least 5 minutes (TSE:16-21, TSE:212, TSE:243-249); the midnight-crossing hold (TSE:22-24, refusal TSE:252); no edit
    within 15 minutes of the old or new boundary (TSE:220) or while the inverter clock is more than 120 s from Home
    Assistant's (TSE:255).
- The firmware path rewrites the whole slot from staging, verifies by readback and has **no durable snapshot and no
  rollback** (TSE:30-34; SAFETY:96). Anything unexpected locks further edits until the owner acknowledges; it is never
  retried and there is no compensating write (TSE:50-51).
- The 5-minute spacing between Applies is the TOU card's provisional rule (TSC:57-58), not an editor or firmware gate; an
  executor that calls the editor scripts directly must enforce it itself. The card also blocks an edit when a scheduled
  session starts within 15 minutes (TSC:596) and keeps start-time edits locked (TSC:83-84).

**New protected HA scripting (the compiler)**: a pure function, tested offline, from the canonical plan and the read-only
slot table to one of:

1. **No native change** (preferred). Short sessions use the existing Free Power / Dump transactions, which take their own
   snapshot and restore, instead of rewriting the permanent table.
2. **A short ordered list of single-field edits**, each a separate guarded Review / confirm / Apply, at least 5 minutes
   apart, with the pre-edit readback saved in the plan revision and the reverse edits listed as a **compensation plan**.
   The compensation plan is never executed automatically: it is offered only after the owner has acknowledged the uncertain
   result, and each step is again a guarded edit. Nothing here is atomic.
3. **An explicit refusal**: more than six partitions needed, a start-time edit that would move the midnight crossing, a slot
   under 5 minutes, a clock-change night, an active lease, a pending owner review, stale readback, or any other editor gate
   above.

**Firmware**: an atomic multi-field slot write with durable snapshot and rollback does not exist (TSE:30-34) and is **not
proposed** for the next phases; the compiler works within single-field edits.

### 2.6 Single-writer / transaction-ownership invariant

**Enforced today**

- Firmware, pairwise: Dump refuses while Free Power owns (FW:18890) or a register 244 transaction is owed (FW:18891); Free
  Power refuses during another write, an RTC correction, a register 244 transaction and a Dump lease or snapshot
  (FW:9929-9932); manual TOU Apply refuses while either lease owns the slots (FW:14115); the RTC policy holds smaller
  corrections during transactions (RTC:21-23).
- Home Assistant: the slot editor refuses during leases and other writes or fallback operations (TSE:260-264); the schedules
  wait for other writes (FPS:181, DGS:188) and refuse overlapping armed windows (FPS:546-572, DGS:571-590); each script is
  `mode: single` (FPS:70, DGS:81).
- Display: the Energy Actions card derives "sibling owns the inverter" from each feature's own state because there is no
  owner entity (EAC `interlock.ts`:12-17); it never blocks or allows anything itself (EAC `interlock.ts`:1-10).

**Gaps a planner would open**

- No single serialiser across HA scripts: two `mode: single` scripts can still run at once.
- The manual and scheduled sessions share one set of request numbers (SMR:3-12); a planner that stages values must be
  coordinated with SMR1 or it will be mistaken for an owner edit, and must never stage while a Dump snapshot is pending.
- A plan change during an active session must never touch that session's saved baseline (the firmware already keeps the
  snapshot; the planner must only recompute the future).

**New protected HA scripting**: one plan executor (a single queue, one action in flight), a derived owner sensor (`NONE`,
`FREE_POWER`, `DUMP`, `REG244`, `MANUAL_TOU`, `FALLBACK`, `RTC`, `RECOVERY`, `UNKNOWN` = fail closed) and a rule that every
planned action goes through the executor. Priorities, highest first: safety stop and restore, an active firmware transaction
or its recovery, an owner's manual action or a paused plan, a confirmed plan, advisory optimisation.

**Firmware (optional)**: a firmware-published owner entity would make the display authoritative; it is not needed for the
Assisted phase.

### 2.7 Summer Solar Priority with confidence gating

- Today: Intelligence corrects the PV forecast source (INT `README.md`:14), learns a PV hour shape (INT `pv.py`:244-266) and
  the first moment PV becomes useful each day (INT `pv.py`:269-274); it gives reserve-aware Dump advice that is never
  applied (INT `dump_advice.py`:1-14); it has no write path (INT `README.md`:3-5).
- New (offline engine work, SHADOW): a `pre_solar_export` advice item with a lower-bound surplus after house demand, an
  explicit "uncertain forecast" outcome that proposes nothing, a per-event energy cap, a benefit check after losses and
  cycle wear, and the end-before-PV buffer; replay and backtest against wrong forecasts, shade and clock-change days.
- Execution would reuse row 2.3. The owner's example (20 kWh in 3 hours) needs about 6.7 kW of average net export. The
  hardware-tested 3000 W is a battery AC ceiling, so before solar the net export is about 3000 W minus the house load: the
  upper bound in 3 hours is below 9 kWh by the house load, before losses and ramps. The planner must show the smaller
  feasible amount or none.
- A profile switch changes planning preferences only; it never enables an automated inverter action.

### 2.8 Intelligence as planner over the two cards

- Today: the card renders advice only for the SHADOW contract with `applies_nothing` (IC:16-20, IC:50-56); the advice items
  are `charge_target`, `overnight_demand`, `export_event` and `dump_to_grid` (IC:80); an item can be `BLOCKED` or `WITHHELD`
  (IC:79; WITHHELD means not computed because of the system status, INT `advisory_contract.py`:117). The engine **blocks**
  charge-window items when the inverter clock offset is unknown or large (INT `quality.py`:767-775).
- New: a versioned **proposed plan** entity in the same schema as the owner's plan, shown in each master card as
  "Suggested", with its reasons, confidence and expected benefit. Adopting it is an owner action that creates a new plan
  revision; Intelligence never writes, stages or presses anything.

## 3. Inputs the planners need, and their state

| Input | Source today | State |
|---|---|---|
| Six-slot table (start, charge source, power, SOC) | TOU:17 onwards; DGS:603-605 | available, read-only |
| Battery SOC, voltage | FW Dump start checks (FW:18894-18896) | available |
| Battery temperature | `ECCO Battery Temperature` (FW:7644) | available, no policy uses it yet |
| Configured battery max charge / discharge current, shutdown SOC | `ECCO Battery Max Charge` / `Max Discharge` / `Battery Shutdown` (FW:8313-8330) | available, read-only |
| Grid-charge current setting; maximum grid-charge power | `ECCO Grid Charge Current` (FW:8387); `sensor.ecco_config_maximum_grid_charge_power` (RCF:80-84) | available, read-only |
| Live, dynamic BMS limits | not published | **UNKNOWN** |
| Usable capacity | INT `config.py`:67 (configured); INT `site_decisions.py`:342 (learned) | available; charge planner uses the larger |
| Charge / discharge efficiency | DC-over-AC residual noted for Dump (FW:40-49) | partial; charging **UNKNOWN** |
| Maximum grid export (permission) | Dump Max Grid Export (FW:5451-5460) | available; owner-confirmed value, never assumed |
| Hardware-tested Dump command ceiling | HW:41; SAFETY:30; FW:246-256 | 3000 W, hardware tested in two scenarios |
| Restore duration distribution | not recorded | **UNKNOWN** |
| PV forecast confidence | INT `pv.py`, scorecard | learning; must be shown as uncertain |

## 4. What this means for the UI

- Everything the owner sees in a "Smart" mode is **shadow planning** until its row reaches Assisted.
- "Charge Battery" and "Export to Grid" keep today's NOW / LATER behaviour unchanged underneath (EAC
  `ecco-energy-actions-card.ts`:100), with today's proof levels (the scheduled Dump is not live-proven); the new names are
  presentation only, and entity ids do not change.
- The 24-hour TOU timeline is **derived and read-only**; native slot edits stay in Advanced through the guarded editor.
- No value below max(10 %, the inverter shutdown SOC) is ever offered as an executable Stop SOC.
