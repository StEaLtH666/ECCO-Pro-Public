# Dynamic energy control: actuator paths, ranked, and the live-proof ladder

Status: **offline architecture review, 25 Nov 2026** (Opus). Nothing here is implemented, flashed, installed or live-proven; no
rung of the ladder in section 10 has been run, and each needs the owner's own separate authorisation. The facts and evidence
grades used below are in [CONTROL_AUTHORITY.md](CONTROL_AUTHORITY.md) (cited as CA section n); the requirements in
[REQUIREMENTS.md](REQUIREMENTS.md). File references are to public main `04e088e` unless a branch is named.

## 1. The answer in brief

| Mode | Safest available path now | Safest adaptive path (after proofs) | What stays unproven |
|---|---|---|---|
| **Gentle Smart Charging** | **One planned fixed rate a night**: the owner's guarded TOU editor writes the charge slot's power in the evening and back in the morning (candidate C0). No new firmware. Only after rungs R3 and R4 | **The active charge slot's power only (one register) under a firmware lease** with an exact restore: the guarded charge-rate controller (GRC) design on `dev/gentle-rate-controller` | whether the slot power limits a charge at all below 8000 W (H1/H2/H3, CA 4.2); its off-grid effect; the response at low rates |
| **Charge Battery / Free Power** | **The existing Free Power lease, its rate chosen at START from measured headroom, ended early** at the target SOC or on an import breach. No in-lease rate change | **In-lease rate steps owned by the Free Power transaction itself** (register 230, the lever that bound in the 11 Oct event), with the intended value committed durably before each write, Dump-controller discipline. A firmware change | 230's factor at other currents; the import limit's value; whether the slot power could replace 230 |
| **Export to Grid / Dump to Grid** | **The existing Dump to Grid V1.1 closed loop** (net grid export target, the six slot powers as the battery ceiling, 244 only at the ends), verified live from 500 to 8000 W of ceiling | the same, with the shared framework adding an export energy objective, reserve-aware feasibility, a raise-only Stop SOC during the lease and a firmware gate on the dongle's Start button | the cause of the 22 Sept 2026 runaway; sustained operation above 3000 W; the scope of 245; the native floor if the dongle dies mid-export |

The native limits stay **hard ceilings in every mode**, never targets: 245 (read-only), 210 and 211, 217-219, the compile-time TOU
bound, the dongle's Dump Power Ceiling and Max Grid Export, the Dump Stop SOC and the effective reserve, and a grid import limit that
ECCO must enforce itself because the inverter did not (CA headline 4).

## 2. Criteria

From the owner's preferences (message C): **P1** TOU determines the window and the planned SOC (the controller never moves slot
times, target SOC or charge source); **P2** the dynamic controller adjusts power within the window; **P3** import/export limits,
battery limits and the reserve remain enforced constraints; **P4** one authoritative controller; **P5** manual mode restores
predictable owner-controlled settings; **P6** no repeated rewrite of the whole TOU configuration when a safer individual setpoint
exists. From safety (message B): **S1** the failure state after a restart, a lost connection or a dead controller is bounded and
stated; **S2** exact reversibility (the pre-session values, never a computed value); **S3** a bounded write surface and write rate;
**S4** arbitration with the existing firmware controllers and Home Assistant scripts; **S5** proven, or provable by a bounded,
read-only-first rung.

## 3. Who owns what today

| Registers | Firmware writers (`tools/analyze_write_surface.py`) | Authority | Note |
|---|---|---|---|
| 22-24 | `write_inverter_rtc` | automatic clock policy, about 2 writes an hour | outside the shared write mutex; has its own lock that every other writer checks |
| 230 | Free Power start, restore, force restore | Free Power write enable (one shot); operator recovery | only Free Power ever changes it |
| 232 | Free Power (3 scripts); `apply_manual_slot1`-`6` (rewritten unchanged) | Free Power enable; manual configuration write enable | |
| 244 | reg 244 harness apply/restore; Dump start/restore; `dump_lockout_containment` | manual arm; Dump enable; containment is automatic and bounded per boot | |
| 250-255 | `apply_manual_slotN` only | manual configuration write enable, typed Apply in Home Assistant | |
| 256-261 | `apply_manual_slotN` (one each); Free Power (all six); Dump start/restore (all six); **`dump_controller_tick` (all six, automatic during a Dump lease, no arm)** | as above | the one register family a closed loop already moves |
| 268-279 | `apply_manual_slotN`; Free Power (3 scripts) | as above | |

**Arbitration today** is a set of pairwise START refusals: Dump refuses while Free Power, the reg 244 harness, a manual write or an RTC
correction holds; Free Power, the reg 244 harness and every slot Apply refuse during a Dump lease or snapshot
(`registry/inverter_capabilities.yaml:2650-2657`). The analyzer still lists ownership blind spots (for example the Dump tick does not
consult Free Power's operation flag; it relies on the START exclusion). **The active power setpoint today belongs to**: the Dump
controller during a Dump lease; the Free Power lease (fixed) during Free Power; otherwise the owner's table.

**Home Assistant** never writes a register (`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md:30`). It arms one-shot enables and
presses the dongle's START buttons: the Charge Battery and Export to Grid schedule packages (with R9: no missed run is started after a
restart), the energy-plan stage 3 overrides and guarded start (branch `dev/stage3-on-r9`, not on main at `04e088e`), smr1 (puts the
owner's request numbers back after a scheduled start), the TOU editor scripts (Review, typed Apply), the fallback profile actions
(Save, Invalidate; no inverter write). Intelligence is SHADOW with no write path.

**Bypass.** The dongle's own Start buttons, write enables and request numbers are ordinary Home Assistant entities: any user or
automation can arm and press them, past every Home Assistant guard (the stage 3 limitation, release gate RG-ST3); the firmware's own
START gates still apply. A read-only start-bypass detector exists as separate work; it detects, it does not prevent. Third parties
(the inverter's own app or logger, its front panel, another Modbus master) can change any register; Free Power's restore
classifier, Dump's drift check and the fallback profile's Live Match detect it, nothing prevents it.

## 4. The authority model proposed (P4)

1. **The authoritative controller is the firmware's lease arbiter on the dongle.** The firmware is the only Modbus writer and the
   only part that keeps acting when Home Assistant is gone. One persisted **setpoint owner** replaces the pairwise refusals:
   `NONE` (manual: the owner's table) or exactly one of `FREE_POWER`, `DUMP`, `CHARGE_RATE` (the GRC-type lease). Every writer of
   230, 244 and 256-261 consults it before its first write (this closes the analyzer's blind spots); a restore owed counts as owned.
2. **Home Assistant is the plan source, never a writer.** One coordinator package chooses the mode and hands the firmware a plan
   (mode, the window and target taken from the owner's TOU table, deadline = window end minus the buffer, an export energy objective,
   the owner's ceilings, the grid import limit), re-sent at least every 5 minutes; a plan older than 20 minutes is lost and the
   lease restores (the GRC rule). It starts a lease only through the guarded path. Intelligence stays SHADOW and is not a plan
   source until that is separately authorised.
3. **The closed loop runs in the firmware lease** (measured feedback, settle, deadband, bounded step, write budget, exact restore):
   the Dump V1.1 pattern already proven live. Home Assistant may lower a ceiling during a lease, never raise one (the fcp1 rule).
4. **Guard order, common to every mode** (REQ-B21): grid lost; the owner's END or manual mode; inverter or BMS fault; telemetry or
   configuration stale or implausible; the reserve or Stop SOC floor; the hard ceilings (grid import limit, Max Grid Export, battery
   current, Power Ceiling); measured-power runaway, wrong direction, no response; a foreign value; the write budget; deadline, plan
   lost, window end; only then the optimisation.
5. **Manual mode** is setpoint owner `NONE`, every schedule disarmed and every enable off, and the owner's own table in force,
   checked (section 9).

## 5. The candidate paths

| Path | Write surface | Reversible | Restart / lost connection / dead controller | Arbitration | Side effects | Proof |
|---|---|---|---|---|---|---|
| **A. Active slot power only, firmware lease** (GRC) | one of 256-261 | exact: `original` held in a 48-byte CRC record before the first write, Home Assistant's own copy, after-window check | boot restores an open lease; plan lost restores in 20 min; a dead dongle leaves the lowered value every night (Home Assistant alerts; the boot warns for every slot below the owner's saved profile) | a new owner flag every 256-261 writer consults (GRC section 12) | the same register caps the slot's discharge: off grid it may cap the battery (unknown); subtractive only (never above `original`) | offline only (186 vectors, 166 mutants, header equal to the model); no live proof |
| **B. All six slot powers, firmware lease** (Dump method; Free Power overlay) | 256-261 | exact (durable snapshot) | boot ends and restores; a dead dongle leaves the override in force | Dump and Free Power refuse each other | overrides every slot's ceiling, also slots outside the window; six registers per step | **VERIFIED_LIVE for export** (500-8000 W ceilings); for charging only as Free Power's fixed overlay |
| **C. One planned fixed slot power through the editor** (C0) | the charge slot (the editor rewrites six registers of that slot) | the owner's typed Apply back; no durable snapshot, no automatic rollback | nothing is in flight; a forgotten morning Apply leaves the lower rate in force every night | the editor refuses during any lease | open loop: no reaction inside the window | the editor path is live-proven for SOC; a slot power edit by it is not; the charge response below 8000 W is not |
| **D. Slot target SOC pacing** | 268-273 | yes | as A | as A | charges at full power in bursts; moves where the charge ends (breaks P1) | rejected (GRC section 1) |
| **E. Grid charge current 230 outside Free Power** | 230 | yes | global: affects any grid charge | collides with Free Power's ownership and restore classifier | amps at a rising voltage; global | rejected as a general path; kept as the contingency of A if the slot power does not limit charging (H2/H3), as a GRC-type lease on 230 |
| **F. Free Power at a START-computed rate, ended early** | the existing 20-register lease | exact (V4 snapshot) | never resumes at boot; a dead dongle leaves grid charging to 100 % in every slot | existing | overrides the owner's table for its duration (breaks P1 for that window, by design) | **VERIFIED_LIVE** (normal start and restore; 8000 W operational on 11 Oct) |
| **G. Free Power with in-lease rate steps** (230, owned by the Free Power transaction) | 230 inside the lease | exact; each new intended value committed durably before its write, so the restore classifier knows it | as F | one owner (Free Power itself) | as F | design only; needs a firmware change and rungs R5, R7-R9 |
| **H. Re-staging Free Power leases** (end and start again at a new rate) | 20 registers per change | yes | as F | as F | about 40 register writes per change, a restore and a start each time | rejected |
| **I. Dump V1.1 closed loop** | 244, 256-261 | exact (durable snapshot, 244 restored first) | boot ends and restores; a dead dongle keeps exporting with no ECCO Stop SOC until it returns | existing | the native load reads 0 W while exporting; the 22 Sept runaway | **VERIFIED_LIVE** (A8, A9, 26 Sept; two hardware-tested scenarios at 3000 W in the public record) |
| **J. Export limit 245 as an actuator** | 245 | n/a | n/a | n/a | global; semantics disputed | rejected: no write path, and a limit is not a target (REQ-B16) |
| **K. Toggling 244** | 244 | yes | as I | as I | all-or-nothing export | rejected as a rate actuator; it stays the lease's mode switch |
| **L. Battery current limits 210 / 211** | 210, 211 | n/a | n/a | n/a | battery protection | rejected: no write path, owner-locked |
| **M. Grid peak shaving** | 280 bits, 293 | n/a | native: survives a dead dongle | n/a | unknown behaviour | not an actuator; a candidate **native import ceiling** after rung R0 and its own characterisation |
| **N. Rewriting the TOU table** (stepped profiles, repeated full rewrites) | 250-279 | yes | a half-written table | everything | moves windows (breaks P1, P6) | rejected |

## 6. Ranking per mode, and the response to loads, PV, SOC and deadlines

### 6.1 Gentle Smart Charging

| Rank | Path | Why |
|---|---|---|
| 1 now | **C** (one planned rate a night) | no firmware; the gentlest safe start; it is also rung R4, the measurement that decides whether path A can work. The GRC simulator finds it nearly as gentle as A on normal nights (0.64 against 0.61 of today's power) |
| 1 adaptive | **A** (the GRC) | P1 (times, target and source untouched; the inverter's own target still ends the charge), P2, P6 (one register), S2 (exact restore of one value), subtractive while the grid is up; its added value over C is robustness when the plan is wrong in several ways at once |
| contingency | **E as a lease** | only if rung R4 shows the slot power does not limit a charge (H2 or H3): the same lease design on 230, unit-agnostic relative steps |
| rejected | B, D, H, L, N | B overrides every slot for no gain; D bursts at full power; the others above |

Response (path A; the planner `frontend/ecco-plan-core/src/gentleNight.ts` on `dev/gentle-on-card-fixes` already models it):

- **Heavy household load:** progress is unaffected at a fixed setpoint (the grid carries the house, CA headline 4), so the rate is
  held. Only when grid import would exceed the import limit is the setpoint reduced (a safety action, ahead of the deadline), with
  TARGET_AT_RISK reported; when the load ends the rate returns after the 30 minute dwell and 300 W hysteresis. Short loads (a kettle,
  an oven cycle) are filtered by averaging over the dwell; only the import limit reacts at once.
- **Sudden load removal:** nothing changes (the charge did not change when the load came).
- **PV:** none in the overnight window; by day, measured PV only, never a forecast.
- **SOC:** re-planned from the measured SOC each dwell; the cliff at 98-99 % is the BMS (no more changes at or above the knee);
  a jump over 5 % or a fall over 2 % ends the lease.
- **High or low start SOC, efficiency changes:** the plan's measured gain (realised power over setpoint) is re-measured after every
  change; ahead of schedule the rate is reduced, behind it raised in steps of at most 2000 W up to the owner's value.
- **Deadline:** deadline = window end minus the buffer (default 60 minutes); the target guard hands the charge back to the
  pre-lease rate as soon as finishing at that rate would no longer leave its margin before the slot's own end ("never worse than
  today"); the lease ends at least 10 minutes before the slot's own end, more than the inverter clock error.

### 6.2 Charge Battery / Free Power

| Rank | Path | Why |
|---|---|---|
| 1 now | **F** at a START-computed rate, ended early | proven; the rate is chosen from measured headroom (`min(owner request, (import limit - p95 house - margin) / measured factor)`), the duration from the permitted window (the schedule, R9 rules); the in-lease adaptation is the proven END: at the target SOC, on a grid import breach, at the window end. Honest: "start rate plus stop" |
| 1 adaptive | **G** | one owner (the Free Power transaction), the lever that bound in the 11 Oct event (230, CA 4.7), its recovery path kept intact by committing every intended value durably before writing it; Dump-tick discipline (45 s settle, bounded steps, never above the pre-lease 230, budget) |
| alternative | **A** | when Charge Battery is expressed as a TOU charge slot in the owner's table (a planned window and target), the Gentle lease with a top-rate policy, P1 satisfied |
| rejected | E (outside Free Power), H, D, L | E breaks Free Power's restore classifier; H rewrites 20 registers per change |

Response: **heavy load** raises grid import one to one (11 Oct: 12.46 kW): the first protection is the START rate's headroom; the
second an import guard that ends the lease (today from Home Assistant through the proven END, depending on Home Assistant being
alive; in firmware with path G); with G the rate steps down instead. **PV** in a current-limited charge lowers grid import (the
battery current is held), so PV is headroom, never a reason to raise the request. **SOC:** the lease ends at the target (Free Power
forces 100 % in every slot, so a lower target is the coordinator's END). **Deadline:** the permitted window's end; feasibility is
reported at START (energy needed against rate times time with the pessimistic taper).

### 6.3 Export to Grid / Dump to Grid

| Rank | Path | Why |
|---|---|---|
| 1 now and adaptive | **I** (Dump V1.1) | the only closed loop proven live; the target is the net grid export (an operational setpoint), the battery ceiling the actuator, the Power Ceiling and Max Grid Export hard limits, Stop SOC a floor, measured-power runaway, frozen-telemetry and cross-check guards, a write budget; P6 is met in spirit (one column of the table, the power, never times, targets or sources; 244 only at the ends) |
| later refinement | A for export (one slot) | a sixth of the register writes per step; needs slot-boundary handling and a firmware change; worth it only if write wear proves to matter |
| rejected | J, K, L, N | J: no write path and a limit is not a target; K: all-or-nothing; L: owner-locked |

What the shared framework adds to I (offline first, then Home Assistant, then firmware only where needed): an export **energy
objective** and its feasibility from the battery energy above `max(Stop SOC, effective reserve)` (measured SOC, pessimistic
capacity and discharge efficiency, PV credited only as measured); the Stop SOC staged at least the effective reserve (stage 3 does
this for ECCO's own starts); a firmware rule that the Stop SOC may be **raised** during a lease (never lowered) so a reserve that
rises mid-lease is honoured; and the firmware gate that makes the dongle's Start button go through the coordinator (REQ-D8).

Response: **heavy load** lowers the export at a fixed ceiling; the controller raises the ceiling (at most 1000 W per 45 s) up to the
Power Ceiling and reports TARGET INFEASIBLE HIGH when even that cannot reach the target; it never imports to export. **Load removal**
raises the export at once (the AC output is fixed): the controller steps down and the export guard ends the lease within about a
second on one sample far over (or two over) the Max Grid Export, so the Max Grid Export needs headroom over the target (START
refuses less than `max(100 W, 3 %)`). **PV** adds to the export: the controller lowers the battery ceiling, down to the 500 W floor
(TARGET INFEASIBLE LOW when PV alone exceeds the target; it never charges to absorb PV). **SOC:** Stop SOC every 15 s, failing closed
on stale SOC; frozen SOC against integrated discharge ends the lease. **Deadline:** the lease duration and the energy objective.

## 7. Restore after a restart, a lost connection or a controller failure (S1, S2, Q6)

| Event | A (charge slot lease) | F / G (Free Power) | I (Dump) |
|---|---|---|---|
| Dongle restart | the boot finds the open record and restores `original` once the inverter answers (BOOT_RECOVERY) | ended and restored at boot, never resumed | ended and restored at boot, never resumed |
| Home Assistant restart or loss | no plan for 20 min: restore; after about 15 min without an API client ESPHome restarts the dongle first, which restores at boot | continues to its end time; the 15 s watchdog restores | continues to its end, Stop SOC enforced by the firmware |
| Dongle dead | the lowered value applies every night until fixed: Home Assistant's after-window check and the boot warning against the saved profile alert the owner | grid charge to 100 % in every slot continues | **export continues with no ECCO Stop SOC**: only the inverter's shutdown SOC remains (gap) |
| Inverter restart | settings are the inverter's own (inferred); the lease's ownership check sees any difference | the restore classifier sees any difference | drift check |
| Grid failure | the lease ends and restores first (the lowered value may cap the battery off grid) | export and grid charge stop by physics; no ECCO interlock | export impossible; no ECCO interlock |
| A foreign write | FAULT, nothing written, alert; the editor stays free | classifier "neither": automatic restore blocked; Review, Force Restore Original or Accept Current State | drift ends the lease through the common restore |

Existing mechanisms reused: the durable two-phase snapshots (Free Power 20 registers, Dump 7), the boot rule "never resume", the GRC
record (`original`, `v`, `p`, `q`, CRC-32), Home Assistant's own copy of the original and its restart-proof 15 minute timer, the
fallback profile (the owner's saved known-good table in the dongle's NVS) and its Live Match, smr1 for the request numbers, R9 for
missed runs. **Gaps:** the fallback profile cannot be restored by the firmware (Restore and automatic failback are not implemented;
`SUPPORTED_HARDWARE.md:43`); a dead dongle during an export leaves the override in force (mitigations: short leases sized to the
objective, a Home Assistant alert when the dongle is unavailable during a lease, rung R6 to learn whether a slot SOC target can act
as a native floor, and the supervision/failback roadmap); the Stop SOC is latched for the lease; the Start bypass.

## 8. Effects on the existing controllers and scripts (S4)

- Path A adds one owner flag and makes every 256-261 writer refuse while it holds (GRC section 12 lists all seven script families
  and the fallback profile operations); the editor stays free in FAULT as the owner's backstop.
- Path G changes the Free Power transaction itself: a new durable schema tag (the codebase's rule for any schema change), the
  classifier's INTENDED set fed from the durable record, and the OTA rule that no flash happens while a recovery marker is set.
- Path I is unchanged in firmware for now; the coordinator only stages and starts it through the guarded path.
- The Stage 3 overrides (Hold battery, Skip tonight, Prepare for power cut) become plan inputs of the coordinator; the R9 and smr1
  packages are kept; the schedule packages become the coordinator's triggers rather than independent starters.

## 9. Manual mode (P5)

Manual mode means no controller owns a setpoint: setpoint owner `NONE`, every schedule disarmed, every one-shot enable off, and the
inverter running the owner's own table. Entering it:

1. ends the active lease through its own proven restore, which writes the exact pre-session values (never a computed value);
2. checks the result: the restored registers against the lease's snapshot (each lease already verifies by readback), then the slot
   table against the saved fallback profile (Live Match `MATCH`) and against Home Assistant's own copy of the pre-session values;
3. if anything differs that the lease did not write, **does not overwrite it**: it reports it and waits for the owner (the GRC's
   FAULT, Free Power's "neither", Dump's drift) - the owner's change wins;
4. leaves the owner's editor as the only writer.

Predictable means: after manual mode the table is exactly what the owner last saved or set, and anything else is shown, not guessed.

## 10. The live-proof ladder (read-only first; each rung bounded; none is run now)

Each rung needs the owner's own authorisation for that rung, the owner's presence where marked, written abort criteria, and a
recorded result reviewed before the next. Rungs R3, R4, R5 and R7 to R10 are the GRC ladder's L1 to L8 applied to all modes.

| Rung | What | Bounded test | Undone by | Decides | Needs first |
|---|---|---|---|---|---|
| R0 | Configuration census (read only) | read the current 210, 211, 230, 245, 243, 247, 248, the peak-shaving bits and powers (280, 292, 293), 217-219 and the slot table from the dongle's existing entities | nothing written | the native ceilings in force; whether grid peak shaving is on | nothing |
| R1 | History pulls (read only) | battery voltage, inverter AC power, grid CT, house, PV and SOC for the 18-21 Nov nights and the 10-11 Oct night (slot target 40 %) | nothing written | constant AC power or constant current at the top rate; whether the inverter stopped at a 40 % target | nothing |
| R2 | Shadow run (no write) | the coordinator and the mode policies compute their decisions on live data for several nights and sessions, writing nothing | nothing written | decision quality, change counts against the budgets, explanations | the offline suites |
| R3 | Off-grid effect of a lowered slot power (GRC L1) | at night outside the charge window, or by day with PV isolated; owner and installer present; the editor lowers the present slot to 1000 W with a known house load of 2-3 kW; the grid isolator opened for a few minutes | close the isolator; the typed Apply back | whether a lowered slot power caps the battery's supply to the house off grid, and what the grid-connected register does | nothing actuates before it |
| R4 | Charge semantics at one lower fixed rate (GRC L2, path C) | the evening before, the editor sets the charge slot to 6000 W; no change inside the window; the grid-loss abort from R3 | the morning typed Apply back | H1 (AC input about 6.74 kW), H2 or H3 (unchanged 8.98 kW) | R3 |
| R5 | Response at other rates (GRC L3) and Free Power's lever | 4000 W, then 2000 W, on separate nights; one supervised short Free Power at a moderate request (for example 4000 W) | as R4; Free Power's own END | linearity of the gain; 230's factor at a second current | R4 |
| R6 | Slot target SOC as a native floor | supervised, short, Zero Export, normal house load: the editor sets the present non-charging slot's target SOC a few points below the present SOC | the typed Apply back | whether the battery stops supplying the house at the slot target (a native reserve floor that survives a dead dongle) | R0 |
| R7 | Firmware integrated, never armed (GRC L4, L5a) | an owner-authorised flash of the reviewed build with the previous image kept; at least 3 nights soak | flash the previous image | no new write in the write-surface log; all existing leases unchanged | an independent review of the integration |
| R8 | First armed session per mode, tight bounds (GRC L5) | owner present for the whole session; low ceilings, short window | END; the deadline restore; Restore original | every write read back, the response within the settle, the restore verified | R0-R7 |
| R9 | Restart, Home Assistant outage, manual mode (GRC L6, L7) | one dongle power cycle and one plan hand-over outage during an R8-type session; then manual mode | the boot restore; PLAN_LOST | exact restore and timing; manual mode's checks | R8 |
| R10 | One full normal session per mode, then a shadow review (GRC L8) | normal limits; the measured knee, tail and gains in the build | automatic | finish time against the plan, writes used | R9 |

## 11. What remains unproven, per mode

- **Gentle:** the setpoint's meaning below 8000 W (R4, R5), its off-grid effect (R3), the response at low rates, the taper below the
  top rate, the usable capacity band, flash wear, the grid import limit's value; the GRC integration does not exist.
- **Charge Battery / Free Power:** 230's factor at other currents (R5), the import limit's value, an import guard in firmware, path
  G's design and review; Free Power's operator recovery paths are offline only.
- **Export:** sustained operation above 3000 W (A9 was 45 s per level), the cause of the 22 Sept runaway, the scope of 245, the
  shutdown SOC's behaviour during a forced export, a native floor if the dongle dies (R6), the Start-button gate.
- **All:** write endurance; the grid-loss interlock; the inverter's behaviour across a full power loss; whether the inverter rounds
  or clamps values it is sent.
