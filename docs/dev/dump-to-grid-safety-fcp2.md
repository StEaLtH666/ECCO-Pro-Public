# Dump to Grid: phase 2 safety hardening (fcp2)

Status: **offline implementation, simulator-tested only.** Not flashed, not live-proven. It is part of the single planned
full-capability firmware image and builds on fcp1 (the capability profile and the persisted operating limits,
`docs/dev/inverter-capability-profiles.md`).

The firmware is `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`. The tests are `registry/tests/test_dump_safety_fcp2.py`.
The exact change scope, and its exact revert, is `registry/tests/_fcp2_scope.py`, declared as the post-export chain entry `fcp2`.

## 1. No controller write once a lease is ending (SG-40)

**The gap.** The closed-loop controller decides on a new battery ceiling at the start of its tick, then:

1. takes the shared write mutex;
2. commits the Dump V2 evidence;
3. re-reads 256-261 to confirm ownership (R3);
4. writes 256-261.

The R3 read takes real time (the script waits for the reply). An End press, the scheduler, or any other end of the lease could
arrive during that wait. The restore then defers, because the controller holds the mutex. The controller nevertheless went on to
write its new ceiling, which could be a raise, after the lease had been asked to end.

**The fix.** The controller re-checks that the lease is still live at two points:

- once the write mutex is held;
- again in the same synchronous step that issues the write.

"Live" means all of these hold:

- the lease is active;
- no End or restore has been requested;
- no restore is running;
- the recovery metadata is not corrupt;
- the obligation marker is `RESTORE_REQUIRED`.

If any of them fails, the write is **cancelled**:

- it is never issued, verified, recorded or published;
- the mutex is released;
- the controller state reads `WRITE CANCELLED - LEASE ENDING`;
- the lease's restore runs on the next watchdog tick.

This applies to every controller write, including fcp1's mid-lease ceiling reductions. Once a lease is ending, only the restore
writes.

**Not changed.** The save-before-write evidence is committed before the R3 read, so a write cancelled after that commit leaves the
cancelled ceiling in the durable evidence as "possibly landed". That is the Dump V2 over-cover rule: the evidence may name more
than landed, never less. The restore does not depend on it.

**Late replies.** No new code was needed for these. Every controller step after a timeout is gated on the failure flag the timeout
sets, so a reply arriving after its own timeout can no longer lead to a write. Neither the controller nor the restore starts a
transaction while the hub has a command queued or awaiting a reply, so a late reply cannot cross into a new transaction. The tests
deliver such replies late, including inside the restore's own transaction, and show that nothing changes.

## 2. Windowed, efficiency-aware runaway guard (R-1)

**The gaps.**

1. **Consecutive samples only.** Both runaway guards counted consecutive samples, and any sample below the threshold reset them. An
   overshoot that alternated above and below the threshold (50 % duty) never tripped.
2. **NaN resets.** A NaN reading also reset the counters.
3. **Watchdog aliasing.** The 15 s watchdog could miss a run of 2 that completed and reset between two of its ticks.
4. **Fixed margin.** The absolute backstop's fixed 750 W margin sits below the battery's normal DC excess at high power. The TOU
   registers limit the inverter's AC output, while register 190 measures battery DC including the conversion loss. Recorded leases
   show +228..+275 W at 2000 W and +271..+357 W at 3000 W. Scaled up, a healthy lease would trip the fixed margin at 7-8 kW.

**The fix.**

- **The consecutive counters are unchanged.** The guard is never looser than before.
- **An 8-sample history of VALID samples** (published, non-NaN, after the lease-start grace) records each sample against three
  levels:
  - the ordinary threshold;
  - the absolute backstop;
  - a gross level: the backstop plus one more margin.
- **The lease ends when any of these holds:**

  | Rule | Substitution | Default |
  |---|---|---|
  | k of the last 8 samples above the ordinary threshold | `ecco_dump_runaway_window_k` | 4 |
  | k of the last 8 samples above the backstop | `ecco_dump_runaway_window_k` | 4 |
  | the consecutive run, read from the same history | (the existing counters' run lengths) | |
  | g of the last 8 samples above the gross level | `ecco_dump_runaway_gross_k` | 3 |

  These end the lease with `POWER RUNAWAY (windowed)`, `ABSOLUTE POWER RUNAWAY (windowed)` or `GROSS POWER RUNAWAY (windowed)`.
- **Skipped and NaN samples** do not advance the history. They are neither above nor below.
- **The decision is latched** at the sample that completes it and acted on by the next watchdog tick. It is cleared only at the
  next lease START.
- **The backstop's margin grows with power.** Above `ecco_dump_runaway_backstop_floor_w` (3000 W), it grows by the profile's
  `ecco_dump_runaway_dc_allowance_pct` (12 % on the reference profile) of the command above that floor:

  ```
  margin = 750 + max(0, ref - 3000) * pct / 100
  ```

  At or below 3000 W the margin is exactly 750 W, as before. Under a 12 % loss model the headroom is the same at every level.
- **The allowance is a profile value.** It is listed in `registry/inverter_profiles.yaml` and range-checked (0-30 %) at compile
  time.

| Command | Backstop | Worst recorded residual, scaled | fcp1 fixed backstop |
|---|---|---|---|
| 3000 W | 3750 W | 3357 W | 3750 W |
| 5000 W | 5990 W | 5595 W | 5750 W |
| 6000 W | 7110 W | 6714 W | 6750 W |
| 7000 W | 8230 W | 7833 W | 7750 W (would nuisance-trip) |
| 8000 W | 9350 W | 8952 W | 8750 W (would nuisance-trip) |

**Bounds the tests prove** (10 s samples, 15 s watchdog):

| Fault | Detected within |
|---|---|
| a step above the backstop | the first watchdog tick after its 2nd sample (35 s or less) |
| a ramp | 35 s of crossing the backstop |
| a 50 % duty oscillation just above the backstop | 95 s |
| 1-in-3 duty excursions above the gross level | 95 s |

**Documented tolerances.** These do not trip:

- one sample in four, less than one margin above the backstop;
- two isolated gross spikes in 8 samples (a third trips).

**Residual model limits.** The recorded residuals come from 2000-3000 W only. Above 3000 W the proportional model is an
extrapolation until each higher operating level is observed live. Raising the power ceiling is a supervised, per-level step.

## 3. Ownership-checked restore (SG-08, SG-29c)

**The gap.** The restore wrote the durable ORIGINAL snapshot back blind, in two writes:

1. 244, the export enable;
2. 256-261, the TOU power.

That overwrote any change someone else had made in the meantime, for example from the app, the front panel, another Modbus master
or an inverter reset. A verified restore whose durable completion failed was also repeated every 15 s, and each repeat rewrote the
registers again, including over anything the owner had changed since.

**The fix.** Before writing anything, inside the same critical section, the restore reads 244-261 once (an 18-register read) and
classifies what it finds:

| Register | ORIGINAL (the snapshot) | ECCO's own value | Anything else |
|---|---|---|---|
| 244 | left alone | 0, Allow Export (what START writes): restored first and verified | FOREIGN |
| 256-261 | left alone | the verified ceiling, or the possibly-landed pending ceiling (the Dump V2 evidence): the block is written back and verified | FOREIGN |

- **A FOREIGN value is never overwritten.** The 256-261 block is written only when every one of its registers is ORIGINAL or
  ECCO's own.
- **Everything ECCO still owns is restored.** When 244 still reads ECCO's Allow Export, that means export is turned off first.
- **The obligation is kept** and the operator is asked:
  - the existing durable operator-needed record is set;
  - the status reads `OPERATOR DECISION REQUIRED - an external change was found and NOT overwritten (...)`;
  - the operator chooses **Force Restore Original** or **Accept Current State**.
- **A FOREIGN 244 is never Allow Export**, because 0 counts as ECCO's own. So ECCO is not exporting in that state.
- **A repeat run after a verified restore finds ORIGINAL and writes nothing.** It only completes the durable clear.
- **A failed or timed-out pre-read writes nothing.** The existing comms backoff retries it.
- **Force Restore Original stays the operator's deliberate override.** It still needs the read to succeed, then writes the ORIGINAL
  snapshot.
- **The boot path uses the same restore.** That covers a power cut mid-lease, and a value changed while the dongle was down is
  kept.

## Compatibility

- **No new write operation**, and no new write domain. Register 245 is never written.
- **One new read:** the restore's pre-read of 244-261.
- **Every new global is RAM only.** No NVS key is added or changed.
- **No durable record schema, tag or header changes.** The one new commit site writes the existing retry record exactly as the
  verify-mismatch lockout already does.
- **The 4 October rollback firmware is unaffected.**
