# Guarded charge-rate controller (GRC): specification, revision 3

Status: **offline design only.** The decision core exists as an executable reference model (`reference_model.py`) and
as a dependency-free firmware header (`proposed/ecco_gentle_rate_core.h` in this folder) proven equal to it. Nothing is
wired into the firmware YAML or any Home Assistant package, nothing has been flashed, nothing has touched an inverter.
No live proof exists; section 13 lists the ones that must come first, in order, each with its own owner authorisation.

Revision 2 answered an independent review (one BLOCKER, five MAJOR; section 15). Revision 3 answers the confirmation
review of revision 2 (four MAJOR and the minors it found or found still open; section 16).

## 1. The decision

The missing actuator: a way to change the grid-charge power **during** the cheap window, safely, so the charge
reaches a target SOC about an hour before the window ends at the lowest rate that still makes it.

| Candidate | What it would write | Verdict |
|---|---|---|
| 0. **One evening write of a planned fixed slot power** through the existing, live-proven slot editor (typed Apply), the morning Apply back to the previous value | the charge slot's power, twice a night, outside the window | **Kept as the baseline and the fallback** (it is what proofs L2 and L3 do). It needs no new firmware. Measured in the simulator (README, REPORT): on the normal nights it is nearly as gentle as the GRC (mean charge power 0.64 of today's against 0.61) and never worse than today; it is open loop, so when the planner is wrong in more than one way (a lower setpoint gain, an understated capacity, an SOC estimate error at the evening write) it misses the target where today's rate would not (25 of 100 stress nights with no margin, 4 with a 25 % margin; the GRC 0 of 100). **The GRC's added value over C0 is robustness, not gentleness** |
| 1. A Free Power-style lease re-staged during the lease | grid charge current (230, amps) and all six slot powers (256-261), plus the lease's SOC/flag overlay (268-279, 232) | **Rejected.** About twenty registers per change; register 230 is amps derived from a battery voltage that rises through the charge, so one value means different powers over the night; 230 is global (every slot); Free Power's restore classifier reads any value it did not write as "neither" and blocks its automatic restore, so a second writer on its registers breaks the one recovery path that exists; its lease also overrides the owner's slot table for its duration |
| 2. **The active charge slot's power only (one register), under its own lease, adjusted in the window** | **one** of 256-261: the slot whose window holds the charge | **Chosen** (below) |
| 3a. Grid charge current (230) alone | 230 | Rejected: amps at an unknown, changing voltage; global; owned by the Free Power transaction; no proof it limits a low-power charge |
| 3b. A stepped profile across several TOU slots, written before the window | slot times, powers, targets | Rejected as the adaptive path: open loop (cannot react to the measured SOC), spends slot partitions and start-time edits (the card keeps them locked), a large write surface. Usable as a fixed layout, never nightly |
| 3c. Pacing by the slot SOC target (raise it in steps) | 268-273 | Rejected: still charges at the full rate in bursts; changes where the charge ends |
| 3d. Battery maximum charge current | (108-family) | Rejected: no ECCO write path; locked until BMS evidence, a design and a hardware proof exist |

Why candidate 2 is the safest **adaptive** one (and why C0 stays the safer non-adaptive start):

- **Smallest write surface.** One register that the existing writers (section 12) already write and verify, the same
  FC16 form, read back exactly. The slot's times, target SOC, source flags and register 230 are never touched, so the
  inverter's own "stop at the slot target" still ends the charge.
- **Subtractive while the grid is up.** The core never asks for more than the value the slot held before the lease
  (`original`), never less than 500 W, always a multiple of 100 W. The registry records a slot power as the battery's
  native charge **and discharge** ceiling of that slot (firmware comment on the post-reboot characterisation). With the
  grid up and the slot charging, lowering it can only reduce the charge. **Off grid it may also cap the battery's
  discharge to the house** (NOT ESTABLISHED, section 14): that is why a lost grid ends the lease at once and restores
  `original` first (section 9), and why the off-grid effect is the FIRST live proof, before any lowered slot is kept for
  a night (L1, section 13).
- **Exact restore of everything it touched:** one value, held in a durable record before the first write.
- **Every failure path ends at `original` or in an alerted FAULT.** Each guard restores `original`; a restore the
  inverter does not answer, or that the integration cannot run, is retried without spending an attempt, but only
  `restore_free_max` (10) times a night and only for `restore_stall_ms` (10 min) of restore-owed time while the inverter
  answers; a Modbus outage of any length costs at most one attempt and does not count against the time bound. The only
  states that keep a lowered value are the FAULTs of section 11 (a foreign value, three ANSWERED restore failures, a
  stalled restore, a corrupt record, the night ceiling); each publishes `original`, raises a Home Assistant alert and
  leaves the owner two ways back: **Restore original** (one classified restore; one write of every night is reserved for
  it) and the slot editor, which no FAULT blocks. Home Assistant keeps its own copy of `original`, checks the slot after
  the window, and alerts when a restore stays owed for 15 min (the firmware cannot act on an inverter that never
  answers).
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
- One lease per night (`night_id`, the local DAY NUMBER of the window start, rolling at local noon), persisted across
  restarts; a night number that goes backwards refuses START.
- END (the owner's stop) ends a lease at once; latched while a write is in flight and acted on after it.
- In FAULT only the owner acts: ACK (accept the current state; the night's counts are kept) or **Restore original** (one
  classified restore of `original`, behind a fresh ownership read, bounded by the night's write ceiling, of which one
  write is reserved for it; a failure leaves the FAULT; a new night restores the owner's budget).
- Home Assistant never writes the register. It hands over a **plan** (section 4); the firmware decides every write and
  checks the plan against its own bounds (sections 7-9). Intelligence stays SHADOW and is never a plan source.

## 3. What it writes and reads

| | Register | Use |
|---|---|---|
| Writes | `256 + Out.slot - 1` (one value per write; every action names its slot) | the slot power, 500 W to `min(original, 8000 W)` rounded down to 100 W and at most one 2000 W step from the present value per change (the owner ceiling included, an off-grid original included); the restore writes `original` exactly |
| Reads (existing polls) | 184 SOC, 190 battery power (charge positive here), the 10 s telemetry frame sequence; 194 grid connected, 79 grid frequency | SOC, realised power, freshness, `rx_age_ms`, `grid_ok` |
| Reads (existing 60 s configuration block 241-293) | 250-261 times and powers, 268-279 targets and flags, 232 bit 0 | slot coverage and its own end, grid charge, the slot's own target, the live slot power (ownership), always for `core.slot` while a lease or a restore is owed |
| Reads (fresh, inside each operation) | the one slot power register `256 + Out.slot - 1` | ownership before a write, readback after it, the restore classifier |

## 4. Inputs (In, every watchdog tick and every telemetry frame)

| Input | Meaning |
|---|---|
| `now_ms` | uptime; compared only as elapsed intervals (wrap safe for any interval below 2^32 ms) |
| `epoch`, `local_min`, `night_id`, `clock_change_night` | wall clock (0 = not valid), local minute of day, the night (a day number that rolls at local noon; 0 = unknown), a DST night (refused) |
| `inv_skew_s` | abs(inverter clock - wall clock), -1 unknown; the TOU editor's 120 s bound |
| `rtc_busy`, `mutex_busy` | an RTC correction in progress; the shared write mutex, the bus, **or the GRC's own `grc_execute` still running**. The tick that H3 runs at the end of `grc_execute` therefore sees `mutex_busy`: the core takes the result, commits whatever it learnt (an owned readback, a fault, a give-back) and emits nothing; the next tick (at most 15 s later) emits |
| `other` | bitmask: Free Power lease or restore owed (1), Dump to Grid (2), TOU editor in flight or acknowledge-locked (4), register 244 transaction (8), fallback profile operation in flight (16), reserved for a future grid-loss interlock (32; no such interlock exists in the base firmware, section 12) |
| `fault` | inverter fault or BMS cut-off flags |
| `grid_ok` | the inverter reports the grid connected (194) and the grid frequency (79) is in band; false = grid lost |
| `arm`, `start`, `end`, `ack`, `restore_req` | the one-shot enable and the owner's pulses (Restore original works only in FAULT) |
| `op`, `op_seq`, `op_kind`, `op_value` | the result of an operation, the sequence number and kind of the action it answers (`Out.seq`, `Out.action`), and the value it read last (the readback; -1 none). OK, OK_NOWRITE (the restore found the original), FAIL (the inverter answered and it did not work: **an exception reply to the fresh read or to the write is FAIL**, as is a readback that differs or a write whose readback went unanswered), FOREIGN, NO_ANSWER (the fresh read before the write got **no reply at all**; nothing written), DEFERRED (not run: bus not free or the previous run still executing; nothing written) |
| `rx_age_ms` | since the inverter last answered any read; NEVER (0xFFFFFFFF) = not since this boot |
| `soc`, `batt_w`, `tel_ok`, `tel_age_ms`, `sample_seq` | one telemetry frame: SOC in tenths, realised battery power, validity, age, frame number |
| `cfg_age_ms`, `cfg_slot`, `live_sp`, `slot_start_min`, `slot_end_min`, `slot_grid`, `slot_target` | the last configuration read, and the slot it describes (`cfg_slot`): the plan's slot at START, **`core.slot` while a lease or restore is owed** (a mismatch refuses START or ends the lease, never classifies another slot's register) |
| `plan` | the hand-over: `valid`, `age_ms` (since receipt), `slot`, `target` (must equal the slot's own target), `deadline` (window end minus the owner's buffer), `window_end`, `ceiling_w` (owner limit, setpoint units), `capacity_wh` (pessimistic), `taper` (knee, %), up to 8 points `t[] p[]`: wanted realised power from each time on |

A plan is valid only with slot 1-6, target 10-100, ceiling 500-8000 in 100 W steps, capacity 1-100 kWh, taper 50-100,
deadline before window end, 1-8 points with strictly increasing times and powers 0-10000 W. Home Assistant re-sends it
at least every 5 minutes; **20 minutes without a hand-over is a lost plan**. The firmware trusts the plan only inside
its own bounds: the window end must lie within 2 min of the slot's own end (taken from the configured slot end and the
dongle clock), the guard's capacity is `max(plan, capacity_floor_wh)` and may only rise during a lease, the guard's
taper knee is at most 95 %, and the owner ceiling is approached by at most one step per change.

Every output that carries an action names its slot (`Out.slot`, 1-6); the integration operates only on register
`256 + Out.slot - 1`.

## 5. Configuration (defaults; `config_ok` checks structure, the integration static_asserts the values)

| Constant | Default | Why |
|---|---|---|
| `floor_w`, `round_w`, `fw_bound_w` | 500, 100, 8000 | the Dump B2 floor, the editor grid, `ecco_inverter_tou_power_ceiling_w` |
| `max_step_w`, `hyst_w`, `reversal_extra_w` | 2000, 300, 300 | rate-of-change cap per write (the owner ceiling included; the bounds are on the grid, `ceil(v - 2000)` and `floor(v + 2000)`, so an original off the grid steps at most 2000 W too); no change under 300 W; against the last direction 600 W |
| `dwell_ms`, `settle_ms`, `judge_samples` | 30 min, 45 s, 4 | the Gentle cadence; the Dump settle; four frames averaged |
| `max_changes`, `max_restore_attempts`, `owner_restore_reserve`, `night_write_ceiling` | 6, 3, 1, 10 | every write counted at emission; 3 lease restores and 1 owner restore always reserved (flash wear NOT ESTABLISHED); attempts = ANSWERED failures |
| `week_write_ceiling`, `life_write_ceiling` | 42, 4000 | every write of the last 7 nights and since the record exists (persisted, published); they refuse START and changes with the same reserve, **never a restore**; guesses (flash wear NOT ESTABLISHED) |
| `restore_free_max`, `restore_stall_ms` | 10, 10 min | the bound of RESTORING without spending an answered attempt: unanswered or deferred restores per night (persisted), and restore-owed time while the inverter answered within `rx_fresh_ms` (each tick adds at most 30 s); either latches FAULT RESTORE_STALLED |
| `plan_max_age_ms`, `telemetry_stale_ms`, `config_stale_ms`, `rtc_busy_max_ms` | 20 min, 90 s, 180 s, 5 min | Home Assistant lost; the Dump staleness bounds; `rtc_busy_max_ms` above the firmware's 90 s RTC deadline breaker (section 12) |
| `clock_skew_max_s`, `end_margin_s`, `min_lease_s`, `arm_window_ms` | 120, 600, 3600, 12 h | `end_margin_s > clock_skew_max_s + 60`: the lease ends before the inverter's own slot end whatever the skew |
| `charging_min_w`, `gain_min_pct`, `gain_max_pct` | 1000 (at least `2 * round_w`), 50, 150 | START needs a running charge the slot power plausibly limits; `config_ok` keeps `charging_min_w / 2 >= round_w`, so the relative step never divides by a zero reference power |
| `response_min_pct`, `wrong_dir_w`, `max_ineffective` | 30, 300, 2 | |
| `runaway_pct`, `runaway_margin_w`, `runaway_samples` | 115, 500, 3 | above `p0 * 1.15 + 500` (p0 = realised before the lease) for 3 frames |
| `stop_w`, `stop_samples`, `stop_soc_gap` | 100, 3, 2.0 % | the charge stopped below the target and the taper |
| `soc_jump_max`, `soc_drop_max` | 5.0 %, 2.0 % | SOC inconsistent |
| `guard_margin_s`, `guard_derate_pct`, `guard_tail_pct` | 900, 85, 25 | target guard (section 9) |
| `capacity_floor_wh` | **none: a mandatory site substitution** | the guard's capacity is never below it. The default (0) fails `config_ok`, so a build that forgot it refuses every START (R_REFUSE_CONFIG). The integration has no default for `grc_capacity_floor_wh` (an undefined substitution fails the build) and static_asserts it is at least the site's usable capacity (the substitution `ecco_battery_usable_capacity_wh`, also a site value; neither value is in this repository; the private Gentle limits report records the figure to use, and recommends adding its 6 % band). Section 9 and the README say what happens below the real capacity |
| `taper_max_pct`, `window_match_s` | 95, 120 | the firmware's own plan bounds |
| `op_timeout_ms`, `restore_backoff_ms`, `watchdog_extra_ms`, `rx_fresh_ms` | 15 s, 30 s, 10 min, 30 s | a restore is emitted only when the inverter answered within `rx_fresh_ms` (inclusive) |
| `script_steps`, `script_step_ms`, `script_queue_ms` | 3, 3 s, 3 s | `grc_execute`'s bounded worst case (read, write, readback at the 3 s `wait_until`, behind the queue); `op_timeout_ms` must exceed it (`static_assert`), so a timed-out operation is over and any later result is stale |

## 6. State machine

| State | Meaning | Leaves to |
|---|---|---|
| IDLE | nothing owed | ARMED (arm on, not latched) |
| ARMED | one-shot enable on | IDLE (arm off, 12 h expiry, or START refused); LEASED / ADJUSTING (START accepted) |
| LEASED | lease open, holding `v` | ADJUSTING (a change); RESTORING (a guard); FAULT (foreign value) |
| ADJUSTING | one write in flight (ownership read, commit, write, readback) | SETTLING (OK); RESTORING (OK with the grid lost meanwhile, FAIL, OK_NOWRITE, NO_ANSWER, DEFERRED, 15 s timeout); FAULT (FOREIGN) |
| SETTLING | 45 s settle, then 4 fresh frames judge the response | LEASED; RESTORING (guard or response) |
| RESTORING | restore owed; RESTORE emitted when the backoff is over, the bus is free and the inverter answered within 30 s | IDLE (OK, OK_NOWRITE); RESTORING again (NO_ANSWER or DEFERRED: a free retry, no attempt spent; FAIL or timeout: one attempt); FAULT (FOREIGN, 3 answered failures, **RESTORE_STALLED: the night's 10th free retry or 10 min restore-owed while the inverter answers**, the night ceiling) |
| FAULT | latched, no automatic write | IDLE on the owner's ACK with a configuration read under 180 s old (accept the current state; the night's counts stay), or on the owner's Restore original answered OK / OK_NOWRITE |

Guards are not evaluated while a write is in flight (END and a grid loss are latched). A result counts only for the
outstanding operation's sequence number and kind; any other (a late result of a timed-out operation, a duplicate) is
stale and never taken as an outcome; the late result of the one operation this lease abandoned at its timeout still
carries the register's newest value (operations run one at a time, section 12), so a readback it carries is owned and
committed (section 11), once. A boot with an open lease in the record goes straight to RESTORING (reason BOOT_RECOVERY)
and emits the restore once the inverter has answered a read since this boot; a corrupt record boots into FAULT
(RECORD_CORRUPT), never into a write. The night rolls (the closing night joins the 7-day window, the night's counts
restart) at START and in IDLE, ARMED and FAULT; never inside a lease.

## 7. START refusals (in this order; each consumes the arm and leaves IDLE)

The configuration not valid (`config_ok`: in particular no site capacity floor); clock or night unknown, or the night
number lower than the recorded one; the night already had a lease; a clock-change night; inverter clock unknown or over
120 s off; an RTC correction; any other lease, write, restore owed or a busy mutex; inverter or BMS fault; **the grid
not connected**; telemetry invalid or over 90 s old; SOC unknown or out of range; plan invalid; plan over 20 min old;
configuration read over 180 s old; the configuration fields not describing the plan's slot, the slot not a grid-charge
slot, its target not the plan's target, now outside it, or **the plan's window end more than 2 min from the slot's own
end**; the slot power under 800 W or over 8000 W; SOC already at the target; no charge running (under 1000 W); realised
power over slot power outside 50-150 %; under 60 min of lease left; the target guard already trips (with the firmware
capacity floor); the night, 7-day or lifetime write ceiling leaving no change once 3 lease restores and 1 owner restore
are reserved. The lease end is `min(deadline, slot's own end - 10 min)`.

## 8. Change policy

`desired = clamp_floor_ceiling(clamp_step_on_grid(round_100(v * plan_power(now) / p_ref)))`:
`plan_power` is the last plan point at or before now; `p_ref` the realised power at `v` (the settled mean, then a
running mean `(3 p_ref + sample) / 4`); the step bounds are `ceil_100(v - 2000)` and `floor_100(v + 2000)`, applied
after the rounding, so no change exceeds 2000 W even from an original off the 100 W grid; the ceiling is
`min(original, 8000)` rounded down to 100 W (a pre-lease value off the grid is only ever written back by the restore)
and `max(owner ceiling, ceil_100(v - 2000))`: an owner ceiling far below `v` is reached in steps of 2000 W, one per
change, never at once. With `p_ref` under 500 W there is no change. A change is written only when: 30 min since the
last verified change (the START write is immediate), fewer than 6 changes this lease, the night, 7-day and lifetime
ceilings minus the 4 reserved restores not reached, no RTC correction or busy mutex, `|desired - v| >= 300`, and
against the previous direction `>= 600`. Every write is counted when it is emitted, before it reaches the bus.

## 9. Lease guards and fail-safe (each tick, in this order)

**Grid lost** (first; also latched while a write is in flight and acted on at its result, the restore emitted in the
same tick; it outranks a latched END); END; wall clock lost; clock-change night; inverter clock; **deadline** (`epoch >=
lease end`; a new plan or the slot's own end may move the lease end earlier, never later); **uptime watchdog** (lease
length + 10 min of uptime, whatever the wall clock does); another lease or write; inverter fault; telemetry stale; SOC
invalid, a jump over 5 % or a fall over 2 % below the lease maximum; plan invalid, **lost** (20 min) or changing slot
or target; configuration stale; the slot changed (the configuration fields no longer describing the lease's slot, grid
flag, target, coverage); **the plan's window end more than 2 min either side of the slot's own end**; **foreign value**
(a configuration read newer than the last verified change shows neither `v` nor `p`) -> FAULT, nothing written;
**target reached** (the inverter's own target ends the charge); **target guard**; runaway; charge stopped; RTC
correction over 5 min.

Every guard but the foreign value ends the lease through RESTORING: `original` is written back, verified, the record
cleared, and the night continues at today's fixed rate. The target guard is the "never worse than today" rule: it
gives the charge back to the pre-lease rate as soon as finishing at that rate would no longer leave 15 min before the
**slot's own end** (from the configured slot end and the dongle clock, never the plan's word) minus 10 min,
pessimistically: SOC up to the taper knee (the plan's, at most 95 %) at 85 % of the pre-lease realised power, above it
at 25 % of it, with the capacity at least the firmware floor (the real taper is NOT ESTABLISHED; a measured knee
tightens this, section 13).

**The rule holds only with `capacity_floor_wh` at least the real usable capacity** (measured, README REPORT): with the
floor at the real capacity, 0 of 80 normal nights and 0 of 4 x 40 nights of the stress families (plans that understate
the capacity down to 3 %, the review's bad plan of 1 kWh with a taper of 100, a taper of 100 alone, a plan of 0 W) and
0 of 40 stress nights (lower gain, understated plan) miss a target today's rate reaches; the guard's other pessimism
absorbs a floor down to 0.8 of the real battery (0 of 100), not below (1 at 0.75, 3 at 0.70, 15 at 0.65, 32 at 0.60 of
100 bad-plan nights; the revision 2 default of 20 kWh on a 26-34 kWh battery: 18 of 100). Holding a lowered value is
never the fault reaction: the only states that keep one are the FAULTs of section 11, where any further automatic
write could fight another writer or a broken bus, and each of them alerts the owner.

## 10. Response judgement (after every verified change)

After 45 s, four fresh frames give `pa`. With `dsp = v - prev_v` and `expected = gain * |dsp|`: the power moving the
other way by over 300 W ends the lease (WRONG_DIRECTION); moving the right way by at least 30 % of expected is a
response (the gain is re-measured as `pa / v` and must stay 50-150 %, else IMPLAUSIBLE_GAIN); otherwise, at or above
the taper knee the BMS is limiting (hold for the rest of the lease, no more changes), below it the response is weak and
the second weak response ends the lease (NO_RESPONSE).

## 11. Durable record and restore

48 bytes (version 3), little endian, CRC-32 (zlib) over bytes 0-43: magic 0x5247, version 3, flags (ACTIVE, FAULT,
NIGHT_USED, READBACK, NIGHT_UNKNOWN), slot, last reason, `original`, `v` (last verified), `p` (pending), `night_id`,
writes this night, changes, restore attempts, free retries this night, lease end, `q` (the owned readback, with
READBACK), the writes of the six previous nights, the lifetime writes, 8 reserved zero bytes. **Every tick whose
`Out.commit` is set persists it before anything else**, with or without an action: before every write and restore
(save before write: from then on every value the lease can have left is in `{original, v, p, q}`), at the lease start,
at the close, at a fault, when an unanswered operation gives its counts back, and **whenever the owned readback `q`
changes** (a clamped readback whose tick cannot emit the restore, the restore's own differing readback inside its
backoff, the late readback of an abandoned operation). Decode fails closed: wrong size, CRC, magic, version, unknown
flag bits, a non-zero reserved byte, an implausible value or count, `q` without READBACK, NIGHT_UNKNOWN with a night or
a lease, or lease fields in an inactive record.

Restore classifier on a fresh read: the original -> nothing to write (OK_NOWRITE); `v`, `p` or `q` -> write
`original`, read back; anything else -> FOREIGN, write nothing, FAULT. A readback taken under the GRC's own lock right
after its own write that differs from the value written (the inverter clamped or rounded it, including 0 W) is
**owned**: it becomes `q`, is committed in that tick, and the restore writes `original` over it (READBACK_MISMATCH),
never a FOREIGN fault, also after a restart; a later readback of -1 (unanswered) never erases it. The write ceilings,
the restore attempts and the free retries are persisted, so a boot loop cannot multiply writes. **An attempt is counted
only when the inverter answered** (an exception or a readback that differs); NO_ANSWER and DEFERRED give the attempt
and the write back (a free retry) and the restore is retried after the backoff, at most `restore_free_max` times a
night; no restore is emitted at all until the inverter has answered a read within 30 s (at a boot: since that boot),
and the time the restore is owed while the inverter answers is bounded by `restore_stall_ms`. The backoff is measured
as elapsed time since it was set and latches once over (no absolute-time comparison: a restore blocked for more than
24.8 days is still emitted at the first answered read).

The commits of a night are bounded: one at the lease start, then at most three ticks per operation (its emission, its
result, the late result of an abandoned one), with at most `night_write_ceiling` counted and `restore_free_max` given
back operations, and a few state changes: at most 1 + 3 x (10 + 10) + 4 = 65 (the simulator's fault nights use at most
22; the fuzz checks the bound on every night). Give-back commits are rate limited by the backoff (one per 30 s) and the
free-retry bound (10 a night).

The paths that can leave a lowered value, and what covers each: three answered restore failures (FAULT
RESTORE_FAILED), a stalled restore (FAULT RESTORE_STALLED), a foreign value (FAULT FOREIGN), a corrupt record (FAULT
RECORD_CORRUPT: `original` unknown to the firmware; the boot's night is taken as used and the 7-day window as full, so
ACK cannot open a second lease that night), the night ceiling (FAULT NIGHT_CEILING: unreachable from a lease, which
reserves its restores and the owner's; reachable only from a record a different build wrote), and a **lost record** (an
NVS erase or serial flash, a durable key-hash change, a rollback to an image without GRC code: the boot sees no record
and goes to IDLE). Covers: the HA alert on FAULT and on a restore owed for 15 min; Restore original; the editor (never
blocked in FAULT); Home Assistant's own copy of `original` and slot, taken at lease start, and its check after the
window that the slot power equals that copy; at a boot with no record, `lost_lease_slots(live, table)` warns for every
slot whose live power is below the owner's saved value (`table` = the six slot powers of the saved fallback profile,
FB-B2, a durable owner copy; never the editor's staging numbers `manual_slotN_power`, which do not survive a restart);
and from L5 on every rollback runbook first requires the record inactive and the slot power read back equal to the
owner's value.

## 12. Interaction rules (mutual exclusion)

A GRC lease (or an owed GRC restore) holds a new ownership flag, `grc_operation_in_progress` for each operation and
`grc_lease_open` for LEASED, ADJUSTING, SETTLING and RESTORING (never FAULT). `grc_record_active` (the record's ACTIVE
flag, also in FAULT while `original` is known) blocks every operation that would take the lowered value as a reference.
GRC START refuses while any other writer's lease or restore is held or owed (`other`). Every GRC operation takes
`manual_write_in_progress` like the Dump controller (bus free, RTC not correcting) and, when it cannot run, reports
DEFERRED (never silence). `mutex_busy` includes the GRC's own running `grc_execute`, so no second operation starts while
a timed-out one is still on the bus, and operations run one at a time (a late result always arrives before the next
operation runs).

Every firmware writer of registers 256-261 (`tools/analyze_write_surface.py` on the production firmware, the seven
script families below; nothing else writes them), and how each meets the GRC:

| Writer | Writes | While a GRC lease or restore is owed (`grc_lease_open`) | In GRC FAULT with an active record |
|---|---|---|---|
| `apply_manual_slot1`-`6` (the TOU editor) | one slot's power (with its times, target, flags) | refuses ("REJECTED - gentle rate lease active") | **allowed**: the owner's backstop; the GRC then classifies the owner's value as FOREIGN, correctly |
| `start_free_power_override` | all six slot powers (with 230, 232, 268-279) | refuses | refuses: its snapshot would take the lowered value as the original it later restores |
| `restore_free_power_snapshot_dispatch`, `free_power_recovery_force_restore_dispatch` | all six slot powers (Free Power's own snapshot) | cannot be owed: GRC START refuses while a Free Power lease or restore is owed and Free Power START refuses during a GRC lease; if one ever were, the GRC ends its lease (OTHER_ACTIVITY) and its classifier sees what Free Power restored (ALREADY, or FOREIGN -> alerted FAULT); both take the shared mutex, so they never interleave | allowed (it restores Free Power's own pre-lease values) |
| `start_dump_to_grid_override` | all six slot powers, one Dump power in each (with 244) | refuses | refuses (its snapshot would take the lowered value) |
| `dump_controller_tick` | all six slot powers (the controller's ceiling) on its ticks of a Dump lease | cannot run: there is no Dump lease during a GRC lease (mutual START refusals) | cannot run without a Dump lease, which refuses to start |
| `restore_dump_to_grid_snapshot` | all six slot powers (Dump's snapshot) | cannot be owed (mutual START refusals); as for Free Power, the GRC ends its lease if it ever is | allowed |
| the fallback profile operations (FB-B1 review / capture, FB-B2 save) | **none of 256-261** (they read 250-279 and write the dongle's NVS) | refuse: a capture would store the lowered value as the owner's profile (and poison `lost_lease_slots`); their bus gate already defers while `manual_write_in_progress` is held, which every GRC operation takes, and they gain `grc_lease_open` / `grc_record_active` in their recovery-domain check | refuse (same reason) |
| `write_inverter_rtc` | 22-24 only | the GRC defers every write and restore while `correction_in_progress` (`rtc_busy`) | - |

In FAULT nothing else is blocked: the editor is the owner's backstop. **Stuck lock**: `grc_operation_in_progress` joins
the flags the existing `ecco_write_lock_stuck_ms` (180 s) supervision watches, and an active GRC record that is not a
FAULT (a lease or restore owed) joins the obligations for which the escalation restarts the device, so the boot path
(BOOT_RECOVERY, with fresh locks) completes the restore. **RTC**: the firmware's deadline breaker releases an RTC
correction's lock after 90 s (`ecco_rtc::kTxnDeadlineMs`) whenever no RTC frame is outstanding, then holds a 5 min
cooldown; the GRC's 5 min RTC_STUCK (in a lease) and its 10 min stall bound (in RESTORING) are therefore reached only
when the breaker cannot release (an RTC frame outstanding on a bus that never quiets); the integration static_asserts
`rtc_busy_max_ms > ecco_rtc::kTxnDeadlineMs`. No grid-loss interlock exists in the base firmware (`other` bit 32 is
reserved); a future one must let the GRC restore of `original` through (it only returns the slot to its pre-lease
value) and must never hold the shared mutex for an outage while a GRC restore is owed.

## 13. Required live proofs (in order; none may be run now; each needs the owner's own authorisation for that step)

Revision 3 reorders the ladder: the off-grid effect of a lowered slot power is proven FIRST, before any lowered value is
kept for a night, and every whole-night lowered-slot test carries a grid-loss abort. Each step was re-checked for
actuating before its prerequisite proof (last column).

| # (rev. 2) | Proof | Bounded safe test | Undone by | Read | Needs first |
|---|---|---|---|---|---|
| L0 (L0) | Taper knee and tail at today's rate | read-only pull of the saved SOC and battery power history of 18-21 Nov (live read authorisation) | nothing written | SOC at the drop, tail length | nothing |
| L1 (L3a) | **Off-grid effect of a lowered slot power** | **at night outside the charge window, or by day with the PV isolated** (PV could otherwise carry the house and mask a cap), owner and installer present: the editor sets the slot that covers the present time to a lower power (typed Apply), e.g. 1000 W, with a known house load clearly above it (2-3 kW); the owner opens the grid isolator for a few minutes and closes it at once on any trip or brown-out | close the isolator; the typed Apply back to the previous value, verified | whether battery discharge to the house is capped near the slot power off grid; the grid-connected register (194) and frequency (79) during the outage; **this decides whether L2/L3 need the owner for the whole window and whether L5 may run at all** | L0 not required; nothing else actuates before it |
| L2 (L1) | Setpoint meaning at one lower fixed rate | the evening before, the existing editor sets the charge slot to 6000 W (typed Apply); no change inside the window. **Grid-loss abort**: if L1 showed a cap, the owner is present for the whole window (or an HA automation that restores the slot on grid loss exists, itself reviewed and authorised as a separate HA change); if L1 showed none, the owner is reachable and the after-window check runs | the morning Apply back to the previous value (typed), verified; the abort: the owner's Undo Apply at once | battery-side and grid-side power against 6000 W for 1 h, plateau stability, finish time, any BMS cut or readback mismatch | L1 |
| L3 (L2) | Response at low and middle rates | L2 repeated on separate nights at 4000 W and **only then** 2000 W, each reviewed before the next, each with L2's grid-loss abort | as L2 | the ratio realised / setpoint at each rate (is it constant?), efficiency, whether the inverter stores each value exactly or clamps / rounds it | L1, L2 |
| L4 (L3) | Firmware with GRC integrated but never armed | owner-authorised flash of the reviewed build with the previous image kept for rollback; at least 3 nights soak, GRC enable never on | flash the previous image (no lease ever ran, so the record is empty) | boot with an empty record, no new write in the write-surface log, analyzers and equivalence report, all existing leases unchanged, `grid_ok`, `rx_age_ms`, the 7-day and lifetime counts published | the integration reviewed by someone other than its author; no live actuation needed |
| L5a (new) | The proof image | build the L5 image (the same code, substitutions: floor 4000 W, 2 changes, night ceiling 6, the measured knee from L0) and flash it under the owner's authorisation, previous image kept | flash the L4 image (record inactive and slot power equal to the owner's value first) | build identity, the published configuration | L4 |
| L5 (L4) | First armed lease, tight bounds | owner present for the whole lease; plan deadline 01:35 (lease about 1 h), SOC 30-60 %, target 90 % | END at any time; otherwise the deadline restore; Restore original and the editor as backstops | every write read back, realised power follows within the settle, the restore verified, the record cleared, counters | L0, L1 (a cap -> the grid-loss guard is the first guard, already so), L2, L3, L5a |
| L6 (L5) | Restart in the middle | during an L5-type lease the owner power-cycles the dongle once | the boot restore (after the inverter's first answer) | `original` back within one tick of the first answered read plus the restore, record cleared | L5 |
| L7 (L6) | Home Assistant outage | during an L5-type lease the plan hand-over automation is disabled | the PLAN_LOST restore within 21 min | the restore and its timing. **A real HA outage takes the L6 boot path instead**: the API's default `reboot_timeout` (15 min without a client) restarts the dongle before PLAN_LOST at 20 min; L7 proves PLAN_LOST only for a partial outage (HA up, the automation broken) | L5, L6 |
| L8a (new) | The normal image | flash the reviewed normal build (the configuration with the measured knee and tail and the site's capacity floor) | flash the L5 image (precondition first) | build identity, configuration | L5-L7 |
| L8 (L7) | One full gentle night | normal limits, target 90 %, owner-set buffer 60 min | automatic | finish time against the plan, peak and mean power, writes used; then shadow review over nights the owner sets | L8a; the guessed constants (knee, tail, floor band) replaced by measured ones |

L1, L2 and L3 use only the existing editor and need no new code (L2 and L3 are candidate C0). L4 onwards need the
integration (INTEGRATION_PROPOSAL.md) reviewed by someone other than its author. **From L5 on, every rollback runbook (a
flash of an earlier image, an NVS erase, a durable-key change) starts with a precondition: the GRC record reads
inactive and the slot power reads back equal to the owner's value; otherwise restore first.** The dongle Start-button
bypass remains a separate open blocker.

## 14. Not established

The setpoint unit; the inverter's response below 8000 W; whether it stores every value it is sent or clamps / rounds
some (only 8000 W is observed; the design restores over a clamp, but the clamp rule is unknown); **the off-grid effect
of a lowered slot power** (whether it caps the battery's discharge to the house during a grid outage; L1); the
grid-connected register's behaviour during a real outage (it is proven only as a read in normal operation); whether
register 230 or the slot power limits a low-power charge; the BMS's live limits and derating; the taper knee and tail
(the guard's 25 % tail, its 95 % maximum knee and the plan's knee are guesses); the real usable capacity and its band
(the floor must be at least it, section 9); flash wear of the settings (hence the night, 7-day and lifetime ceilings,
all guesses); the grid import limit; whether the plateau above the setpoint is partly a sensor scale effect; the
inverter's behaviour when a slot power changes while it is charging (no live observation of a mid-charge change
exists); whether the GRC's measured advantage over C0 (robustness when the planner is wrong in several ways at once)
appears on the real system at all.

## 15. Revision 2: the review findings and their changes

| Finding | Change | Proof |
|---|---|---|
| B1 the restore budget spent on unanswered attempts; a clamped readback read as FOREIGN; FAULT blocks the editor; ACK forgets `original` | attempts = answered failures; NO_ANSWER / DEFERRED give the attempt and the write back; no restore before the inverter answers (at a boot: since that boot); the owned readback `q`; Restore original in FAULT; the editor never blocked in FAULT; HA alert and HA copy of `original` | V120-V133; nights modbus_down_{2,5,10}min_{guard,boot}, inverter_rounds, inverter_clamps |
| M2 results carry no sequence or kind | `Out.seq` echoed with `op_seq` / `op_kind`; a result for anything else is stale; DEFERRED instead of silence; `static_assert(op_timeout_ms > grc_execute worst case)`; `mutex_busy` includes the GRC's own run | V140-V144 |
| M3 the plan trusted beyond the firmware's bounds | the guard's window and the lease end from the slot's own end; the plan's window end must match it within 2 min (START and every tick); capacity `max(plan, floor)`, only rising; knee at most 95 %; owner ceiling one step per change (V56 now expects the stricter 6000; the old behaviour is a killed mutant) | V56, V150-V159 |
| M4 no grid-status input; the slot power also caps discharge | `grid_ok` ends the lease first and restores in the same tick, latched over an in-flight write; START refuses without the grid; the interlock rule; the off-grid proof and section 14 | V160-V163; night grid_outage |
| M5 the restore timeout and midnight untested | a restore with no result (timeout, retry, FAULT); a 23:30-05:30 slot through START, the guards and the slot's own end; both kept as model and header mutants | V170-V172 |
| M6 the record is the only copy of `original` | the HA copy and the after-window check; the rollback precondition; `lost_lease_slots` at a boot with no record | units `lost_lease`; INTEGRATION H1, H6, section 4 |

## 16. Revision 3: the confirmation review and its changes

| Finding | Change | Proof (vectors, nights, mutants) |
|---|---|---|
| CI: the proposed header under `firmware/` broke the FB-C3 tree pin (15 files) | the header moved to `docs/dev/gentle-rate-controller/proposed/`; the integration moves it to `firmware/include/` with the chain entry `grc1` | `test_failback_shadow_ha_contract` and every suite that reads `firmware/` or `git ls-files`, run one at a time |
| MAJOR 1: RESTORING had no bound and no owner escape (DEFERRED / NO_ANSWER / RTC / mutex for ever) | at most 10 free retries a night (persisted) and 10 min restore-owed while the inverter answers, then FAULT RESTORE_STALLED (alert, editor, Restore original); a silent inverter adds nothing; the give-back commits rate limited and bounded; an exception on the fresh read is FAIL (an answered attempt); H8: the stuck-lock escalation restarts while a GRC restore is owed, the RTC breaker bounds `rtc_busy`; HA alerts after 15 min RESTORING | V200-V206, V237, V238; nights restore_deferred_always, restore_no_answer_always, restore_exception_always, rtc_stuck_after_end, modbus_down_60min_guard; model and header mutants |
| MAJOR 2: the owned readback was committed only with an action | `Out.commit` whenever `q` changes (READBACK_MISMATCH, the restore's and the owner restore's own readback, the late readback of an abandoned write, once); a -1 never erases it; 0 W is owned | V220-V226; nights clamp_busy_result_reboot, restore_differs_reboot; model and header mutants |
| MAJOR 3: the 20 kWh capacity floor default below the real battery | no usable default: `capacity_floor_wh` is a mandatory site substitution (0 fails `config_ok`, START refuses R_REFUSE_CONFIG; the build static_asserts it against the site's usable capacity); the never-worse check runs the understated, bad-plan, taper-100 and p=0 families and a stress family; the floor's sensitivity is measured and stated (section 9) | V213; battery_sim families; REPORT; model and header mutants |
| MAJOR 4: the proof ladder actuated a whole night before the off-grid proof | L1 is now the off-grid proof (at night or with the PV isolated, house load above the lowered value); L2/L3 carry a grid-loss abort; the 2000 W night only after it; L5a / L8a put the proof-image and normal-image flashes into the ladder; L7 states that a real HA outage takes the boot path | section 13 |
| MINOR: other writers of 256-261 not all named | the seven firmware script families from `analyze_write_surface`, each gated or why safe, and the fallback profile operations' refusal (section 12) | INTEGRATION H7 |
| MINOR: no rolling write cap; ACK after RECORD_CORRUPT reset the night | 7-day (42) and lifetime (4000) ceilings, persisted and published, never refusing a restore; a corrupt record makes the boot's night used and the 7-day window full; ACK keeps every count; a night number going backwards refuses START | V209-V212, V214; model and header mutants |
| MINOR: RTC_STUCK wait unbounded | the stall bound (MAJOR 1) and the RTC breaker (section 12) | V202, V205 |
| MINOR: candidate C0 missing | section 1 row 0 and the simulator's `baseline_fixed` / `c0_setpoint`; measured against the GRC (README REPORT) | REPORT |
| MINOR: input contract gaps | `Out.slot` and `In.cfg_slot`; the exception on a fresh read is FAIL; the tick inside `grc_execute` (section 4) | V233-V236; model and header mutants |
| MINOR: the 24.8-day wrap of the restore backoff | the backoff is an elapsed interval that latches once over; no absolute-time comparison left | V237, V238; the revision 2 comparison is a killed mutant in both suites |
| MINOR: the step cap exceeded from an off-grid original (6949 -> 4900) | the step bounds on the grid, after the rounding (6949 -> 5000); the fuzz property now has no exception; 6949 among the fuzz originals | V233, V239; model and header mutants |
| MINOR: Restore original unavailable in the worst case; NIGHT_CEILING dead | one owner write reserved every night (ceiling 10 = 6 + 3 + 1); the night rolls in FAULT; NIGHT_CEILING tested from a record another build wrote | V207, V208, V133; G15 killed in both suites |
| MINOR: a stale result's readback thrown away | the late readback of the abandoned operation is owned and committed, once | V223 |
| MINOR: `lost_lease_slots` against the staging numbers | against the saved fallback profile's slot powers (durable, owner-saved) and, in HA, against HA's copy of `original` | units `lost_lease`; INTEGRATION H1, section 4 |
| MINOR: survivors of the reviewer's mutants G01, G03, G04, G07, G08, G14, G15, G18, G19, G22 | one vector each; the fuzz now emits FAIL(q) then FAIL(-1), END and grid loss while a write is in flight, grid loss while settling, window offsets of 119-121 s, 2^31 ms gaps, off-grid originals; all 22 model and 12 header twins in the suites | V200-V239 |
| MINOR: `charging_min_w = 1` divided by zero | `config_ok` requires `charging_min_w >= 2 * round_w`; `desired` also tests `p_ref <= 0` (defence in depth, unreachable) | units config_ok |
| MINOR: L4's configuration needed a flash; L6 did not test what a real outage does | L5a / L8a; the L7 note | section 13 |
