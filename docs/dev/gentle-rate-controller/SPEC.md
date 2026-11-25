# Guarded charge-rate controller (GRC): specification, revision 2

Status: **offline design only.** The decision core exists as an executable reference model (`reference_model.py`) and
as a dependency-free firmware header (`firmware/proposed/ecco_gentle_rate_core.h`) proven equal to it. Nothing is wired
into the firmware YAML or any Home Assistant package, nothing has been flashed, nothing has touched an inverter. No
live proof exists; section 13 lists the ones that must come first, in order, each with its own owner authorisation.

Revision 2 answers an independent review (one BLOCKER, five MAJOR); section 15 maps each finding to its change.

## 1. The decision

The missing actuator: a way to change the grid-charge power **during** the cheap window, safely, so the charge
reaches a target SOC about an hour before the window ends at the lowest rate that still makes it.

| Candidate | What it would write mid-window | Verdict |
|---|---|---|
| 1. A Free Power-style lease re-staged during the lease | grid charge current (230, amps) and all six slot powers (256-261), plus the lease's SOC/flag overlay (268-279, 232) | **Rejected.** About twenty registers per change; register 230 is amps derived from a battery voltage that rises through the charge, so one value means different powers over the night; 230 is global (every slot); Free Power's restore classifier reads any value it did not write as "neither" and blocks its automatic restore, so a second writer on its registers breaks the one recovery path that exists; its lease also overrides the owner's slot table for its duration |
| 2. **The active charge slot's power only (one register), under its own lease** | **one** of 256-261: the slot whose window holds the charge | **Chosen** (below) |
| 3a. Grid charge current (230) alone | 230 | Rejected: amps at an unknown, changing voltage; global; owned by the Free Power transaction; no proof it limits a low-power charge |
| 3b. A stepped profile across several TOU slots, written before the window | slot times, powers, targets | Rejected as the adaptive path: open loop (cannot react to the measured SOC), spends slot partitions and start-time edits (the card keeps them locked), a large write surface. Usable as a fixed layout, never nightly |
| 3c. Pacing by the slot SOC target (raise it in steps) | 268-273 | Rejected: still charges at the full rate in bursts; changes where the charge ends |
| 3d. Battery maximum charge current | (108-family) | Rejected: no ECCO write path; locked until BMS evidence, a design and a hardware proof exist |

Why candidate 2 is the safest:

- **Smallest write surface.** One register that three existing writers (the slot editor, Free Power, Dump to Grid)
  already write and verify, the same FC16 form, read back exactly. The slot's times, target SOC, source flags and
  register 230 are never touched, so the inverter's own "stop at the slot target" still ends the charge.
- **Subtractive while the grid is up.** The core never asks for more than the value the slot held before the lease
  (`original`), never less than 500 W, always a multiple of 100 W. The registry records a slot power as the battery's
  native charge **and discharge** ceiling of that slot (firmware comment on the post-reboot characterisation). With the
  grid up and the slot charging, lowering it can only reduce the charge. **Off grid it may also cap the battery's
  discharge to the house** (NOT ESTABLISHED, section 14): that is why a lost grid ends the lease at once and restores
  `original` first (section 9), and why the off-grid effect is a required proof before the first armed lease (L3a).
- **Exact restore of everything it touched:** one value, held in a durable record before the first write.
- **Every failure path ends at `original` or in an alerted FAULT.** Each guard restores `original`; a restore the
  inverter does not answer is retried, without spending an attempt, until it is answered (a Modbus outage of any
  length costs at most one attempt). The only states that keep a lowered value are the FAULTs of section 11 (a foreign
  value, three ANSWERED restore failures, a corrupt record, the night ceiling); each publishes `original`, raises a
  Home Assistant alert and leaves the owner two ways back: **Restore original** (one classified restore) and the slot
  editor, which no FAULT blocks. Home Assistant keeps its own copy of `original` and checks the slot after the window.
- **Robust to the unknown setpoint unit** (AC grid side, DC battery side, or amps at some voltage: NOT ESTABLISHED).
  The core never converts watts to a setpoint by assumption. The plan asks for a **realised** battery power; each
  change is a **relative** step `v * wanted / realised` from the present value, with `realised` measured after the
  settle; the measured ratio (`gain_pct`) must stay within 50-150 % or the lease ends; a step whose response is too
  weak or goes the wrong way ends the lease (section 10). If the slot power is not what limits the charge (another
  limit binds), START refuses (gain below 50 %) or the first weak responses end the lease. Monotonicity of the
  response is the one assumption, and it is checked at every change.

## 2. Authority

- Nothing starts a lease but **START with the one-shot GRC write enable on**. The enable is armed by the owner for one
  night, or by an owner-armed schedule; it is consumed by START whether START is accepted or refused, expires after
  12 h, and after a refusal, a lease or a restart it must be seen OFF before it arms again (firmware switch
  `restore_mode: ALWAYS_OFF`).
- One lease per night (`night_id`, the local date of the window start), persisted across restarts.
- END (the owner's stop) ends a lease at once; latched while a write is in flight and acted on after it.
- In FAULT only the owner acts: ACK (accept the current state) or **Restore original** (one classified restore of
  `original`, behind a fresh ownership read, bounded by the night's write ceiling; a failure leaves the FAULT).
- Home Assistant never writes the register. It hands over a **plan** (section 4); the firmware decides every write and
  checks the plan against its own bounds (sections 7-9). Intelligence stays SHADOW and is never a plan source.

## 3. What it writes and reads

| | Register | Use |
|---|---|---|
| Writes | `256 + slot - 1` (one value per write) | the slot power, 500 W to `min(original, 8000 W)` rounded down to 100 W and at most one 2000 W step towards the owner ceiling per change; the restore writes `original` exactly |
| Reads (existing polls) | 184 SOC, 190 battery power (charge positive here), the 10 s telemetry frame sequence; 194 grid connected, 79 grid frequency | SOC, realised power, freshness, `rx_age_ms`, `grid_ok` |
| Reads (existing 60 s configuration block 241-293) | 250-261 times and powers, 268-279 targets and flags, 232 bit 0 | slot coverage and its own end, grid charge, the slot's own target, the live slot power (ownership) |
| Reads (fresh, inside each operation) | the one slot power register | ownership before a write, readback after it, the restore classifier |

## 4. Inputs (In, every watchdog tick and every telemetry frame)

| Input | Meaning |
|---|---|
| `now_ms` | uptime, wrap safe |
| `epoch`, `local_min`, `night_id`, `clock_change_night` | wall clock (0 = not valid), local minute of day, the night, a DST night (refused) |
| `inv_skew_s` | abs(inverter clock - wall clock), -1 unknown; the TOU editor's 120 s bound |
| `rtc_busy`, `mutex_busy` | an RTC correction in progress; the shared write mutex, the bus, **or the GRC's own `grc_execute` still running** |
| `other` | bitmask: Free Power lease or restore owed (1), Dump to Grid (2), TOU editor in flight or acknowledge-locked (4), register 244 transaction (8), fallback profile write (16), reserved for a future grid-loss interlock (32; no such interlock exists in the base firmware, section 12) |
| `fault` | inverter fault or BMS cut-off flags |
| `grid_ok` | the inverter reports the grid connected (194) and the grid frequency (79) is in band; false = grid lost |
| `arm`, `start`, `end`, `ack`, `restore_req` | the one-shot enable and the owner's pulses (Restore original works only in FAULT) |
| `op`, `op_seq`, `op_kind`, `op_value` | the result of an operation, the sequence number and kind of the action it answers (`Out.seq`, `Out.action`), and the value it read last (the readback; -1 none). OK, OK_NOWRITE (the restore found the original), FAIL (the inverter answered and it did not work), FOREIGN, NO_ANSWER (the fresh read before the write went unanswered; nothing written), DEFERRED (not run: bus not free or the previous run still executing; nothing written) |
| `rx_age_ms` | since the inverter last answered any read; NEVER (0xFFFFFFFF) = not since this boot |
| `soc`, `batt_w`, `tel_ok`, `tel_age_ms`, `sample_seq` | one telemetry frame: SOC in tenths, realised battery power, validity, age, frame number |
| `cfg_age_ms`, `live_sp`, `slot_start_min`, `slot_end_min`, `slot_grid`, `slot_target` | the last configuration read of the plan's slot |
| `plan` | the hand-over: `valid`, `age_ms` (since receipt), `slot`, `target` (must equal the slot's own target), `deadline` (window end minus the owner's buffer), `window_end`, `ceiling_w` (owner limit, setpoint units), `capacity_wh` (pessimistic), `taper` (knee, %), up to 8 points `t[] p[]`: wanted realised power from each time on |

A plan is valid only with slot 1-6, target 10-100, ceiling 500-8000 in 100 W steps, capacity 1-100 kWh, taper 50-100,
deadline before window end, 1-8 points with strictly increasing times and powers 0-10000 W. Home Assistant re-sends it
at least every 5 minutes; **20 minutes without a hand-over is a lost plan**. The firmware trusts the plan only inside
its own bounds: the window end must lie within 2 min of the slot's own end (taken from the configured slot end and the
dongle clock), the guard's capacity is `max(plan, capacity_floor_wh)` and may only rise during a lease, the guard's
taper knee is at most 95 %, and the owner ceiling is approached by at most one step per change.

## 5. Configuration (defaults; `config_ok` checks structure, the integration static_asserts the values)

| Constant | Default | Why |
|---|---|---|
| `floor_w`, `round_w`, `fw_bound_w` | 500, 100, 8000 | the Dump B2 floor, the editor grid, `ecco_inverter_tou_power_ceiling_w` |
| `max_step_w`, `hyst_w`, `reversal_extra_w` | 2000, 300, 300 | rate-of-change cap per write (the owner ceiling included); no change under 300 W; against the last direction 600 W |
| `dwell_ms`, `settle_ms`, `judge_samples` | 30 min, 45 s, 4 | the Gentle cadence; the Dump settle; four frames averaged |
| `max_changes`, `max_restore_attempts`, `night_write_ceiling` | 6, 3, 9 | every write counted at emission; 3 restores always reserved (flash wear NOT ESTABLISHED); attempts = ANSWERED failures |
| `plan_max_age_ms`, `telemetry_stale_ms`, `config_stale_ms`, `rtc_busy_max_ms` | 20 min, 90 s, 180 s, 5 min | Home Assistant lost; the Dump staleness bounds |
| `clock_skew_max_s`, `end_margin_s`, `min_lease_s`, `arm_window_ms` | 120, 600, 3600, 12 h | `end_margin_s > clock_skew_max_s + 60`: the lease ends before the inverter's own slot end whatever the skew |
| `charging_min_w`, `gain_min_pct`, `gain_max_pct` | 1000, 50, 150 | START needs a running charge the slot power plausibly limits |
| `response_min_pct`, `wrong_dir_w`, `max_ineffective` | 30, 300, 2 | |
| `runaway_pct`, `runaway_margin_w`, `runaway_samples` | 115, 500, 3 | above `p0 * 1.15 + 500` (p0 = realised before the lease) for 3 frames |
| `stop_w`, `stop_samples`, `stop_soc_gap` | 100, 3, 2.0 % | the charge stopped below the target and the taper |
| `soc_jump_max`, `soc_drop_max` | 5.0 %, 2.0 % | SOC inconsistent |
| `guard_margin_s`, `guard_derate_pct`, `guard_tail_pct` | 900, 85, 25 | target guard (section 9) |
| `capacity_floor_wh`, `taper_max_pct`, `window_match_s` | 20 kWh, 95, 120 | the firmware's own plan bounds; the site file sets `capacity_floor_wh` to its usable capacity (no site value in this repository) |
| `op_timeout_ms`, `restore_backoff_ms`, `watchdog_extra_ms`, `rx_fresh_ms` | 15 s, 30 s, 10 min, 30 s | a restore is emitted only when the inverter answered within `rx_fresh_ms` |
| `script_steps`, `script_step_ms`, `script_queue_ms` | 3, 3 s, 3 s | `grc_execute`'s bounded worst case (read, write, readback at the 3 s `wait_until`, behind the queue); `op_timeout_ms` must exceed it (`static_assert`), so a timed-out operation is over and any later result is stale |

## 6. State machine

| State | Meaning | Leaves to |
|---|---|---|
| IDLE | nothing owed | ARMED (arm on, not latched) |
| ARMED | one-shot enable on | IDLE (arm off, 12 h expiry, or START refused); LEASED / ADJUSTING (START accepted) |
| LEASED | lease open, holding `v` | ADJUSTING (a change); RESTORING (a guard); FAULT (foreign value) |
| ADJUSTING | one write in flight (ownership read, commit, write, readback) | SETTLING (OK); RESTORING (OK with the grid lost meanwhile, FAIL, OK_NOWRITE, NO_ANSWER, DEFERRED, 15 s timeout); FAULT (FOREIGN) |
| SETTLING | 45 s settle, then 4 fresh frames judge the response | LEASED; RESTORING (guard or response) |
| RESTORING | restore owed; RESTORE emitted when due, the bus is free and the inverter answered within 30 s | IDLE (OK, OK_NOWRITE); RESTORING again (NO_ANSWER or DEFERRED: no attempt spent; FAIL or timeout: one attempt); FAULT (FOREIGN, 3 answered failures, night ceiling) |
| FAULT | latched, no automatic write | IDLE on the owner's ACK with a configuration read under 180 s old (accept the current state), or on the owner's Restore original answered OK / OK_NOWRITE |

Guards are not evaluated while a write is in flight (END and a grid loss are latched). A result counts only for the
outstanding operation's sequence number and kind; any other (a late result of a timed-out operation, a duplicate) is
stale and ignored. A boot with an open lease in the record goes straight to RESTORING (reason BOOT_RECOVERY) and emits
the restore once the inverter has answered a read since this boot; a corrupt record boots into FAULT
(RECORD_CORRUPT), never into a write.

## 7. START refusals (in this order; each consumes the arm and leaves IDLE)

Clock or night unknown; the night already had a lease; a clock-change night; inverter clock unknown or over 120 s
off; an RTC correction; any other lease, write, restore owed or a busy mutex; inverter or BMS fault; **the grid not
connected**; telemetry invalid or over 90 s old; SOC unknown or out of range; plan invalid; plan over 20 min old;
configuration read over 180 s old; the slot not a grid-charge slot, its target not the plan's target, now outside it,
or **the plan's window end more than 2 min from the slot's own end**; the slot power under 800 W or over 8000 W; SOC
already at the target; no charge running (under 1000 W); realised power over slot power outside 50-150 %; under 60 min
of lease left; the target guard already trips (with the firmware capacity floor); fewer than one change left in the
night's write ceiling. The lease end is `min(deadline, slot's own end - 10 min)`.

## 8. Change policy

`desired = clamp_floor_ceiling(round_100(clamp_step(v * plan_power(now) / p_ref)))`:
`plan_power` is the last plan point at or before now; `p_ref` the realised power at `v` (the settled mean, then a
running mean `(3 p_ref + sample) / 4`); `clamp_step` keeps within `v +- 2000`; the ceiling is
`min(original, 8000)` rounded down to 100 W (a pre-lease value off the grid is only ever written back by the restore)
and `max(owner ceiling, v - 2000 rounded up to 100 W)`: an owner ceiling far below `v` is reached in steps of 2000 W,
one per change, never at once. With `p_ref` under 500 W there is no change. A change is written only when: 30 min since
the last verified change (the START write is immediate), fewer than 6 changes this lease, the night's ceiling minus 3
restores not reached, no RTC correction or busy mutex, `|desired - v| >= 300`, and against the previous direction
`>= 600`. Every write is counted when it is emitted, before it reaches the bus.

## 9. Lease guards and fail-safe (each tick, in this order)

**Grid lost** (first; also latched while a write is in flight and acted on at its result, the restore emitted in the
same tick); END; wall clock lost; clock-change night; inverter clock; **deadline** (`epoch >= lease end`; a new plan
or the slot's own end may move the lease end earlier, never later); **uptime watchdog** (lease length + 10 min of
uptime, whatever the wall clock does); another lease or write; inverter fault; telemetry stale; SOC invalid, a jump
over 5 % or a fall over 2 % below the lease maximum; plan invalid, **lost** (20 min) or changing slot or target;
configuration stale; the slot changed (grid flag, target, coverage); **the plan's window end more than 2 min from the
slot's own end**; **foreign value** (a configuration read newer than the last verified change shows neither `v` nor
`p`) -> FAULT, nothing written; **target reached** (the inverter's own target ends the charge); **target guard**;
runaway; charge stopped; RTC correction over 5 min.

Every guard but the foreign value ends the lease through RESTORING: `original` is written back, verified, the record
cleared, and the night continues at today's fixed rate. The target guard is the "never worse than today" rule: it
gives the charge back to the pre-lease rate as soon as finishing at that rate would no longer leave 15 min before the
**slot's own end** (from the configured slot end and the dongle clock, never the plan's word) minus 10 min,
pessimistically: SOC up to the taper knee (the plan's, at most 95 %) at 85 % of the pre-lease realised power, above it
at 25 % of it, with the capacity at least the firmware floor (the real taper is NOT ESTABLISHED; a measured knee
tightens this, section 13). Holding a lowered value is never the fault reaction: the only states that keep one are
the FAULTs of section 11, where any further automatic write could fight another writer or a broken bus, and each of
them alerts the owner.

## 10. Response judgement (after every verified change)

After 45 s, four fresh frames give `pa`. With `dsp = v - prev_v` and `expected = gain * |dsp|`: the power moving the
other way by over 300 W ends the lease (WRONG_DIRECTION); moving the right way by at least 30 % of expected is a
response (the gain is re-measured as `pa / v` and must stay 50-150 %, else IMPLAUSIBLE_GAIN); otherwise, at or above
the taper knee the BMS is limiting (hold for the rest of the lease, no more changes), below it the response is weak and
the second weak response ends the lease (NO_RESPONSE).

## 11. Durable record and restore

32 bytes (version 2), little endian, CRC-32 (zlib) over bytes 0-27: magic 0x5247, version 2, flags (ACTIVE, FAULT,
NIGHT_USED, READBACK), slot, last reason, `original`, `v` (last verified), `p` (pending), `night_id`, writes this
night, changes, restore attempts, lease end, `q` (the owned readback, with READBACK). It is committed **before** every
write and restore (save before write: from then on every value the lease can have left is in `{original, v, p, q}`),
at the lease start, at the close, at a fault and when an unanswered operation gives its counts back. Decode fails
closed: wrong size, CRC, magic, version, unknown flag bits, a non-zero reserved byte, an implausible value, `q`
without READBACK, or lease fields in an inactive record.

Restore classifier on a fresh read: the original -> nothing to write (OK_NOWRITE); `v`, `p` or `q` -> write
`original`, read back; anything else -> FOREIGN, write nothing, FAULT. A readback taken under the GRC's own lock right
after its own write that differs from the value written (the inverter clamped or rounded it) is **owned**: it becomes
`q`, is committed, and the restore writes `original` over it (READBACK_MISMATCH), never a FOREIGN fault. The write
ceiling and the restore attempts are persisted, so a boot loop cannot multiply writes. **An attempt is counted only
when the inverter answered** (an exception or a readback that differs); NO_ANSWER and DEFERRED give the attempt and the
write back and the restore is retried after the backoff for as long as it takes, and no restore is emitted at all
until the inverter has answered a read within 30 s (at a boot: since that boot).

The paths that can leave a lowered value, and what covers each: three answered restore failures (FAULT RESTORE_FAILED),
a foreign value (FAULT FOREIGN), a corrupt record (FAULT RECORD_CORRUPT: `original` unknown to the firmware), the night
ceiling (FAULT NIGHT_CEILING), and a **lost record** (an NVS erase or serial flash, a durable key-hash change, a
rollback to an image without GRC code: the boot sees no record and goes to IDLE). Covers: the HA alert on FAULT;
Restore original; the editor (never blocked in FAULT); Home Assistant's own copy of `original` and slot, taken at
lease start; Home Assistant's check after the window that the slot power equals the owner's table value; at a boot
with no record, `lost_lease_slots(live, table)` warns for every slot whose live power is below the editor's stored
value; and from L4 on every rollback runbook first requires the record inactive and the slot power read back equal to
the owner's value.

## 12. Interaction rules (mutual exclusion)

A GRC lease (or an owed GRC restore) holds a new ownership flag, `grc_operation_in_progress` for each operation and
`grc_lease_open` for LEASED, ADJUSTING, SETTLING and RESTORING (never FAULT). Free Power START, Dump to Grid START, the
TOU editor's Apply, the register 244 apply and the fallback profile writer **refuse while `grc_lease_open`**, and GRC
START refuses while any of theirs is held or owed (`other`). In FAULT nothing is blocked: the editor is the owner's
backstop. Every GRC operation takes `manual_write_in_progress` like the Dump controller (bus free, RTC not correcting)
and, when it cannot run, reports DEFERRED (never silence). `mutex_busy` includes the GRC's own running `grc_execute`,
so no second operation starts while a timed-out one is still on the bus. An RTC correction defers GRC writes; over
5 min it ends the lease. No grid-loss interlock exists in the base firmware (`other` bit 32 is reserved); a future one
must let the GRC restore of `original` through (it only returns the slot to its pre-lease value) and must never hold
the shared mutex for an outage while a GRC restore is owed.

## 13. Required live proofs (in order; none may be run now; each needs the owner's own authorisation for that step)

| # | Proof | Bounded safe test | Undone by | Read |
|---|---|---|---|---|
| L0 | Taper knee and tail at today's rate | read-only pull of the saved SOC and battery power history of 18-21 Nov (live read authorisation) | nothing written | SOC at the drop, tail length |
| L1 | Setpoint meaning at one lower fixed rate | the evening before, the existing editor sets the charge slot to 6000 W (typed Apply); no change inside the window; owner present at 00:30-01:00 | the morning Apply back to the previous value (typed), verified | battery-side and grid-side power against 6000 W for 1 h, plateau stability, finish time, any BMS cut or readback mismatch (the only in-window change allowed: the abort, the owner's Undo Apply back to the previous value) |
| L2 | Response at low and middle rates | L1 repeated on separate nights at 4000 W and 2000 W, each reviewed before the next | as L1 | the ratio realised / setpoint at each rate (is it constant?), efficiency, whether the inverter stores each value exactly or clamps / rounds it |
| L3 | Firmware with GRC integrated but never armed | owner-authorised flash of the reviewed build with the previous image kept for rollback; at least 3 nights soak, GRC enable never on | flash the previous image (no lease ever ran, so the record is empty) | boot with an empty record, no new write in the write-surface log, analyzers and equivalence report, all existing leases unchanged, `grid_ok` and `rx_age_ms` as published |
| L3a | Off-grid effect of a lowered slot power | daytime, no charge window, owner and installer present: the editor sets the present slot to a lower power (typed Apply), the owner opens the grid isolator for a few minutes with a known house load | close the isolator; the typed Apply back to the previous value, verified | whether battery discharge to the house is capped near the slot power off grid; the grid-connected register and frequency during the outage; this decides whether L4 may proceed at all |
| L4 | First armed lease, tight bounds | owner present; configuration for this night only: floor 4000 W, 2 changes, plan deadline 01:35 (lease about 1 h), SOC 30-60 %, target 90 % | END at any time; otherwise the deadline restore; Restore original and the editor as backstops | every write read back, realised power follows within the settle, the restore verified, the record cleared, counters |
| L5 | Restart in the middle | during an L4-type lease the owner power-cycles the dongle once | the boot restore (after the inverter's first answer) | `original` back within one tick of the first answered read plus the restore, record cleared |
| L6 | Home Assistant outage | during an L4-type lease the plan hand-over automation is disabled | the PLAN_LOST restore within 21 min | the restore and its timing |
| L7 | One full gentle night | normal limits, target 90 %, owner-set buffer 60 min | automatic | finish time against the plan, peak and mean power, writes used; then shadow review over nights the owner sets |

L1, L2 and L3a use only the existing editor and need no new code. L3 onwards need the integration
(INTEGRATION_PROPOSAL.md) reviewed by someone other than its author. **From L4 on, every rollback runbook (a flash of
an earlier image, an NVS erase, a durable-key change) starts with a precondition: the GRC record reads inactive and
the slot power reads back equal to the owner's table value; otherwise restore first.** The dongle Start-button bypass
remains a separate open blocker.

## 14. Not established

The setpoint unit; the inverter's response below 8000 W; whether it stores every value it is sent or clamps / rounds
some (only 8000 W is observed; the design restores over a clamp, but the clamp rule is unknown); **the off-grid effect
of a lowered slot power** (whether it caps the battery's discharge to the house during a grid outage; L3a); the
grid-connected register's behaviour during a real outage (it is proven only as a read in normal operation); whether
register 230 or the slot power limits a low-power charge; the BMS's live limits and derating; the taper knee and tail
(the guard's 25 % tail, its 95 % maximum knee and the plan's knee are guesses); flash wear of the settings (hence the
9-write ceiling); the grid import limit; whether the plateau above the setpoint is partly a sensor scale effect; the
inverter's behaviour when a slot power changes while it is charging (no live observation of a mid-charge change exists).

## 15. Revision 2: the review findings and their changes

| Finding | Change | Proof |
|---|---|---|
| B1 the restore budget spent on unanswered attempts; a clamped readback read as FOREIGN; FAULT blocks the editor; ACK forgets `original` | attempts = answered failures; NO_ANSWER / DEFERRED give the attempt and the write back; no restore before the inverter answers (at a boot: since that boot); the owned readback `q`; Restore original in FAULT; the editor never blocked in FAULT; HA alert and HA copy of `original` | V120-V133; nights modbus_down_{2,5,10}min_{guard,boot}, inverter_rounds, inverter_clamps |
| M2 results carry no sequence or kind | `Out.seq` echoed with `op_seq` / `op_kind`; a result for anything else is stale; DEFERRED instead of silence; `static_assert(op_timeout_ms > grc_execute worst case)`; `mutex_busy` includes the GRC's own run | V140-V144 |
| M3 the plan trusted beyond the firmware's bounds | the guard's window and the lease end from the slot's own end; the plan's window end must match it within 2 min (START and every tick); capacity `max(plan, floor)`, only rising; knee at most 95 %; owner ceiling one step per change (V56 now expects the stricter 6000; the old behaviour is a killed mutant) | V56, V150-V159 |
| M4 no grid-status input; the slot power also caps discharge | `grid_ok` ends the lease first and restores in the same tick, latched over an in-flight write; START refuses without the grid; the interlock rule; L3a and section 14 | V160-V163; night grid_outage |
| M5 the restore timeout and midnight untested | a restore with no result (timeout, retry, FAULT); a 23:30-05:30 slot through START, the guards and the slot's own end; both kept as model and header mutants | V170-V172 |
| M6 the record is the only copy of `original` | the HA copy and the after-window check; the rollback precondition; `lost_lease_slots` at a boot with no record | units `lost_lease`; INTEGRATION H1, H6, section 4 |
