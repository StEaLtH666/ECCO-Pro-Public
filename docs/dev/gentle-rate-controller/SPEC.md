# Guarded charge-rate controller (GRC): specification, revision 1

Status: **offline design only.** The decision core exists as an executable reference model (`reference_model.py`) and
as a dependency-free firmware header (`firmware/proposed/ecco_gentle_rate_core.h`) proven equal to it. Nothing is wired
into the firmware YAML or any Home Assistant package, nothing has been flashed, nothing has touched an inverter. No
live proof exists; section 13 lists the ones that must come first, in order, each with its own owner authorisation.

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
- **Subtractive by construction.** The core never asks for more than the value the slot held before the lease
  (`original`), never less than 500 W, always a multiple of 100 W. A slot power is the battery charge/discharge
  ceiling of that slot (firmware comment on the post-reboot characterisation), so lowering it can only reduce the
  flow through the battery in that slot, whatever the slot's floor; nothing here ever raises it above the pre-lease
  value (Free Power's "ceilings only with every floor at 100" invariant exists because Free Power RAISES ceilings).
  Every failure path ends at `original`, which is exactly today's behaviour.
- **Exact restore of everything it touched:** one value, held in a durable record before the first write.
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
- Home Assistant never writes the register. It hands over a **plan** (section 4); the firmware decides every write.
  Intelligence stays SHADOW and is never a plan source.

## 3. What it writes and reads

| | Register | Use |
|---|---|---|
| Writes | `256 + slot - 1` (one value per write) | the slot power, 500 W to `min(original, owner ceiling, 8000 W)` rounded down to 100 W; the restore writes `original` exactly |
| Reads (existing polls) | 184 SOC, 190 battery power (charge positive here), the 10 s telemetry frame sequence | SOC, realised power, freshness |
| Reads (existing 60 s configuration block 241-293) | 250-261 times and powers, 268-279 targets and flags, 232 bit 0 | slot coverage, grid charge, the slot's own target, the live slot power (ownership) |
| Reads (fresh, inside each operation) | the one slot power register | ownership before a write, readback after it, the restore classifier |

## 4. Inputs (In, every watchdog tick and every telemetry frame)

| Input | Meaning |
|---|---|
| `now_ms` | uptime, wrap safe |
| `epoch`, `local_min`, `night_id`, `clock_change_night` | wall clock (0 = not valid), local minute of day, the night, a DST night (refused) |
| `inv_skew_s` | abs(inverter clock - wall clock), -1 unknown; the TOU editor's 120 s bound |
| `rtc_busy`, `mutex_busy` | an RTC correction in progress; the shared write mutex or the bus not free |
| `other` | bitmask: Free Power lease or restore owed (1), Dump to Grid (2), TOU editor in flight or acknowledge-locked (4), register 244 transaction (8), fallback profile write (16), grid-loss interlock lock (32) |
| `fault` | inverter fault or BMS cut-off flags |
| `arm`, `start`, `end`, `ack` | the one-shot enable and the owner's pulses |
| `op` | result of the previous action: OK, OK_NOWRITE (restore found the original), FAIL, FOREIGN |
| `soc`, `batt_w`, `tel_ok`, `tel_age_ms`, `sample_seq` | one telemetry frame: SOC in tenths, realised battery power, validity, age, frame number |
| `cfg_age_ms`, `live_sp`, `slot_start_min`, `slot_end_min`, `slot_grid`, `slot_target` | the last configuration read of the plan's slot |
| `plan` | the hand-over: `valid`, `age_ms` (since receipt), `slot`, `target` (must equal the slot's own target), `deadline` (window end minus the owner's buffer), `window_end`, `ceiling_w` (owner limit, setpoint units), `capacity_wh` (pessimistic), `taper` (knee, %), up to 8 points `t[] p[]`: wanted realised power from each time on |

A plan is valid only with slot 1-6, target 10-100, ceiling 500-8000 in 100 W steps, capacity 1-100 kWh, taper 50-100,
deadline before window end, 1-8 points with strictly increasing times and powers 0-10000 W. Home Assistant re-sends it
at least every 5 minutes; **20 minutes without a hand-over is a lost plan**.

## 5. Configuration (defaults; `config_ok` checks structure, the integration static_asserts the values)

| Constant | Default | Why |
|---|---|---|
| `floor_w`, `round_w`, `fw_bound_w` | 500, 100, 8000 | the Dump B2 floor, the editor grid, `ecco_inverter_tou_power_ceiling_w` |
| `max_step_w`, `hyst_w`, `reversal_extra_w` | 2000, 300, 300 | rate-of-change cap per write; no change under 300 W; against the last direction 600 W |
| `dwell_ms`, `settle_ms`, `judge_samples` | 30 min, 45 s, 4 | the Gentle cadence; the Dump settle; four frames averaged |
| `max_changes`, `max_restore_attempts`, `night_write_ceiling` | 6, 3, 9 | every write counted at emission; 3 restores always reserved (flash wear NOT ESTABLISHED) |
| `plan_max_age_ms`, `telemetry_stale_ms`, `config_stale_ms`, `rtc_busy_max_ms` | 20 min, 90 s, 180 s, 5 min | Home Assistant lost; the Dump staleness bounds |
| `clock_skew_max_s`, `end_margin_s`, `min_lease_s`, `arm_window_ms` | 120, 600, 3600, 12 h | |
| `charging_min_w`, `gain_min_pct`, `gain_max_pct` | 1000, 50, 150 | START needs a running charge the slot power plausibly limits |
| `response_min_pct`, `wrong_dir_w`, `max_ineffective` | 30, 300, 2 | |
| `runaway_pct`, `runaway_margin_w`, `runaway_samples` | 115, 500, 3 | above `p0 * 1.15 + 500` (p0 = realised before the lease) for 3 frames |
| `stop_w`, `stop_samples`, `stop_soc_gap` | 100, 3, 2.0 % | the charge stopped below the target and the taper |
| `soc_jump_max`, `soc_drop_max` | 5.0 %, 2.0 % | SOC inconsistent |
| `guard_margin_s`, `guard_derate_pct`, `guard_tail_pct` | 900, 85, 25 | target guard (section 9) |
| `op_timeout_ms`, `restore_backoff_ms`, `watchdog_extra_ms` | 15 s, 30 s, 10 min | |

## 6. State machine

| State | Meaning | Leaves to |
|---|---|---|
| IDLE | nothing owed | ARMED (arm on, not latched) |
| ARMED | one-shot enable on | IDLE (arm off, 12 h expiry, or START refused); LEASED / ADJUSTING (START accepted) |
| LEASED | lease open, holding `v` | ADJUSTING (a change); RESTORING (a guard); FAULT (foreign value) |
| ADJUSTING | one write in flight (ownership read, commit, write, readback) | SETTLING (OK); RESTORING (FAIL, OK_NOWRITE, 15 s timeout); FAULT (FOREIGN) |
| SETTLING | 45 s settle, then 4 fresh frames judge the response | LEASED; RESTORING (guard or response) |
| RESTORING | restore owed; RESTORE emitted when due and the bus is free | IDLE (OK, OK_NOWRITE); FAULT (FOREIGN, 3 failures, night ceiling) |
| FAULT | latched, no write of any kind | IDLE only on the owner's ACK with a configuration read under 180 s old (accept the current state) |

Guards are not evaluated while a write is in flight (END is latched). A boot with an open lease in the record goes
straight to RESTORING (reason BOOT_RECOVERY); a corrupt record boots into FAULT (RECORD_CORRUPT), never into a write.

## 7. START refusals (in this order; each consumes the arm and leaves IDLE)

Clock or night unknown; the night already had a lease; a clock-change night; inverter clock unknown or over 120 s
off; an RTC correction; any other lease, write, restore owed or a busy mutex; inverter or BMS fault; telemetry
invalid or over 90 s old; SOC unknown or out of range; plan invalid; plan over 20 min old; configuration read over
180 s old; the slot not a grid-charge slot, its target not the plan's target, or now outside it; the lease
(`min(deadline, window end - 10 min)`) would outlast the slot; the slot power under 800 W or over 8000 W; SOC already
at the target; no charge running (under 1000 W); realised power over slot power outside 50-150 %; under 60 min of
lease left; the target guard already trips; fewer than one change left in the night's write ceiling.

## 8. Change policy

`desired = clamp_floor_ceiling(round_100(clamp_step(v * plan_power(now) / p_ref)))`:
`plan_power` is the last plan point at or before now; `p_ref` the realised power at `v` (the settled mean, then a
running mean `(3 p_ref + sample) / 4`); `clamp_step` keeps within `v +- 2000`; the ceiling is
`min(original, owner ceiling, 8000)` rounded down to 100 W (a pre-lease value off the grid is only ever written back by
the restore); an owner ceiling under `v - 2000` is applied at once (a larger step, downward only). With `p_ref` under
500 W there is no change. A change is written only when: 30 min since the last verified change (the START write is
immediate), fewer than 6 changes this lease, the night's ceiling minus 3 restores not reached, no RTC correction or
busy mutex, `|desired - v| >= 300`, and against the previous direction `>= 600`. Every write is counted when it is
emitted, before it reaches the bus.

## 9. Lease guards and fail-safe (each tick, in this order)

END; wall clock lost; clock-change night; inverter clock; **deadline** (`epoch >= lease end`; a new plan may move the
lease end earlier, never later); **uptime watchdog** (lease length + 10 min of uptime, whatever the wall clock does);
another lease or write; inverter fault; telemetry stale; SOC invalid, a jump over 5 % or a fall over 2 % below the
lease maximum; plan invalid, **lost** (20 min) or changing slot or target; configuration stale; the slot changed
(grid flag, target, coverage); **foreign value** (a configuration read newer than the last verified change shows
neither `v` nor `p`) -> FAULT, nothing written; **target reached** (the inverter's own target ends the charge);
**target guard**; runaway; charge stopped; RTC correction over 5 min.

Every guard but the foreign value ends the lease through RESTORING: `original` is written back, verified, the record
cleared, and the night continues at today's fixed rate. The target guard is the "never worse than today" rule: it
gives the charge back to the pre-lease rate as soon as finishing at that rate would no longer leave 15 min before the
window end minus 10 min, pessimistically: SOC up to the plan's taper knee at 85 % of the pre-lease realised power,
above the knee at 25 % of it (the real taper is NOT ESTABLISHED; a measured knee tightens this, section 13).
Holding a lowered value is never the fault reaction: the only state that keeps a lowered value is FAULT after a
foreign value or three failed restores, where any further write could fight another writer or a broken bus.

## 10. Response judgement (after every verified change)

After 45 s, four fresh frames give `pa`. With `dsp = v - prev_v` and `expected = gain * |dsp|`: the power moving the
other way by over 300 W ends the lease (WRONG_DIRECTION); moving the right way by at least 30 % of expected is a
response (the gain is re-measured as `pa / v` and must stay 50-150 %, else IMPLAUSIBLE_GAIN); otherwise, at or above
the taper knee the BMS is limiting (hold for the rest of the lease, no more changes), below it the response is weak and
the second weak response ends the lease (NO_RESPONSE).

## 11. Durable record and restore

28 bytes, little endian, CRC-32 (zlib) over bytes 0-23: magic 0x5247, version 1, flags (ACTIVE, FAULT, NIGHT_USED),
slot, last reason, `original`, `v` (last verified), `p` (pending), `night_id`, writes this night, changes, restore
attempts, lease end. It is committed **before** every write and restore (save before write: from then on every value
the lease can have left is in `{original, v, p}`), at the lease start, at the close and at a fault. Decode fails
closed: wrong size, CRC, magic, version, unknown flag bits, a non-zero reserved byte, an implausible value, or lease
fields in an inactive record.

Restore classifier on a fresh read: the original -> nothing to write (OK_NOWRITE); `v` or `p` -> write `original`,
read back; anything else -> FOREIGN, write nothing, FAULT. The write ceiling and the restore attempts are persisted, so
a boot loop cannot multiply writes.

## 12. Interaction rules (mutual exclusion)

A GRC lease (or an owed GRC restore) holds a new ownership flag, `grc_operation_in_progress` for each operation and
`grc_lease_open` for the lease. Free Power START, Dump to Grid START, the TOU editor's Apply, the register 244 apply
and the fallback profile writer **refuse while `grc_lease_open`**, and GRC START refuses while any of theirs is held
or owed (`other`). Every GRC operation takes `manual_write_in_progress` like the Dump controller (bus free, RTC not
correcting) and defers, never fails, when it cannot. An RTC correction defers GRC writes; over 5 min it ends the lease.

## 13. Required live proofs (in order; none may be run now; each needs the owner's own authorisation for that step)

| # | Proof | Bounded safe test | Undone by | Read |
|---|---|---|---|---|
| L0 | Taper knee and tail at today's rate | read-only pull of the saved SOC and battery power history of 18-21 Nov (live read authorisation) | nothing written | SOC at the drop, tail length |
| L1 | Setpoint meaning at one lower fixed rate | the evening before, the existing editor sets the charge slot to 6000 W (typed Apply); no change inside the window; owner present at 00:30-01:00 | the morning Apply back to the previous value (typed), verified | battery-side and grid-side power against 6000 W for 1 h, plateau stability, finish time, any BMS cut or readback mismatch (the only in-window change allowed: the abort, the owner's Undo Apply back to the previous value) |
| L2 | Response at low and middle rates | L1 repeated on separate nights at 4000 W and 2000 W, each reviewed before the next | as L1 | the ratio realised / setpoint at each rate (is it constant?), efficiency |
| L3 | Firmware with GRC integrated but never armed | owner-authorised flash of the reviewed build with the previous image kept for rollback; at least 3 nights soak, GRC enable never on | flash the previous image | boot with an empty record, no new write in the write-surface log, analyzers and equivalence report, all existing leases unchanged |
| L4 | First armed lease, tight bounds | owner present; configuration for this night only: floor 4000 W, 2 changes, plan deadline 01:35 (lease about 1 h), SOC 30-60 %, target 90 % | END at any time; otherwise the deadline restore; the editor as backstop | every write read back, realised power follows within the settle, the restore verified, the record cleared, counters |
| L5 | Restart in the middle | during an L4-type lease the owner power-cycles the dongle once | the boot restore | `original` back within one tick of boot plus the restore, record cleared |
| L6 | Home Assistant outage | during an L4-type lease the plan hand-over automation is disabled | the PLAN_LOST restore within 21 min | the restore and its timing |
| L7 | One full gentle night | normal limits, target 90 %, owner-set buffer 60 min | automatic | finish time against the plan, peak and mean power, writes used; then shadow review over nights the owner sets |

L1 and L2 use only the existing editor and need no new code. L3 onwards need the integration (INTEGRATION_PROPOSAL.md)
reviewed by someone other than its author. The dongle Start-button bypass remains a separate open blocker.

## 14. Not established

The setpoint unit; the inverter's response below 8000 W; whether register 230 or the slot power limits a low-power
charge; the BMS's live limits and derating; the taper knee and tail (the guard's 25 % tail and the plan's knee are
guesses); flash wear of the settings (hence the 9-write ceiling); the grid import limit; whether the plateau above the
setpoint is partly a sensor scale effect; the inverter's behaviour when a slot power changes while it is charging (no
live observation of a mid-charge change exists).
