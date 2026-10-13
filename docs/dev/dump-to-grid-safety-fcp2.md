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

## 4. Frozen telemetry and the restore backoff (SG-15, SG-43, SG-39)

**The gap.** "Fresh" used to mean "published recently". A grid CT, battery-power or SOC reading that kept arriving on time but never
changed was trusted. A stuck CT could hold the controller at its ceiling for the whole lease, a frozen SOC disabled Stop SOC, and
frozen battery power blinded the runaway guard.

**Already covered: a read that stops.** The CT (register 172), SOC (184) and battery power (190) are decoded from ONE telemetry
read. So when that read stops, all three stop together:

- Stop SOC's freshness check ends the lease after 90 s;
- the controller never decides on a grid sample older than its last write.

**New: readings that keep arriving but never change.** During a settled lease, the lease ends through the common restore path in
any of these cases:

| Signal | Ends the lease when | Default |
|---|---|---|
| Battery power | it repeats exactly for `ecco_dump_frozen_samples` valid reads. The recorded leases never repeat a reading twice in a row. | 6 |
| Grid CT, fast | it repeats exactly for `ecco_dump_frozen_samples` reads while the battery power moved by more than `ecco_dump_frozen_cross_w`. The plant changed and the meter did not. | 6 reads, 150 W |
| Grid CT, slow | it repeats exactly for `ecco_dump_frozen_ct_long_samples` reads, whatever the battery did. This catches a CT stuck while the controller sits at its ceiling. | 30 reads (5 minutes) |
| SOC | the battery discharges more than `ecco_dump_soc_frozen_wh` of DC energy (integrated from register 190) with no SOC change. | 1500 Wh |

The SOC default is about 5 % of the reference installation's ~30 kWh battery, and it is **site-dependent**: a smaller battery needs
a smaller value.

**The restore backoff (SG-39).** A restore attempt that failed while the link itself was down (no telemetry read for
`ecco_dump_link_down_ms`, 25 s) is retried as soon as a telemetry read succeeds again. Before, it waited out the rest of a backoff
of up to 300 s with nothing supervising the lease. A failure while telemetry was still flowing means the inverter refused the
write, not that the link failed, so it keeps the ordinary backoff and the inverter is not hammered.

## 5. Restart protection, build identity and safe to flash (SG-36, SG-07, SG-16)

**Restart.** The raw ESPHome reboot button is now internal, so nothing outside the firmware can press it. The `Restart` entity is a
gated template button.

**The safety census.** `ecco_safety_census` reads RAM only (no Modbus, no durable access). It runs every 5 s and immediately before
a restart, and finds the first thing a restart or a flash would interrupt.

- **A transaction in flight:**
  - Dump to Grid or Free Power, including Force or Accept;
  - a register 244 change;
  - any inverter write;
  - an RTC correction;
  - a fallback profile operation.
- **Or an obligation:**
  - a Dump to Grid or Free Power lease or restore owed (snapshot or marker not CLEAR);
  - a recovery decision outstanding (operator-needed or corrupt metadata);
  - a register 244 restore owed.

**What Restart does with that:**

- **Nothing found:** it restarts.
- **A transaction in flight:** it is refused, and **never overridable**.
- **An owed obligation:** it is refused unless `Restart Override Arm` is on. The arm allows one press within 60 s and is consumed
  by that press. An override is acceptable here because the boot path re-opens every durable obligation and runs the
  ownership-checked restore.
- **The reason is published** in `Restart Status`.

**Flashing.** Over-the-air updates cannot be refused by firmware.

- `ECCO Safe To Flash` is true only when the census finds nothing.
- `ECCO Flash Readiness` names the reason when it is not safe.
- Before the first census after boot, the device does not claim to be safe.

**Build identity.** `ECCO Build Identity` publishes:

- the build tag (`ecco_build_tag`, set at build time to the source tree or commit);
- the capability profile;
- the ESPHome version;
- the configuration hash.

**Safe mode.** The `safe_mode:` block is now explicit, with ESPHome's defaults: 10 attempts, 5 min, boot is good after 1 min. Safe
mode runs none of this firmware's components, so no supervision or restore happens there. Every obligation is durable and is
re-opened on the next normal boot.

**Communication loss.** The API's default 15-minute no-client reboot is unchanged. It is safe because:

- a reboot ends any lease;
- the boot path re-opens the obligation from the durable markers;
- the restore that follows is ownership-checked (section 3): ECCO's own values are restored and anything changed meanwhile is kept
  for the operator.

Proposed for a later decision, not implemented: a firmware supervisor that disables the API reboot and reboots only once the census
is clear.

## 6. Lock and recovery safety (SG-14, SG-42)

**Rule:** a timeout never simply releases a lock that protects an unresolved inverter transaction.

**Audit of the existing timeouts.**

| Timeout | Behaviour | Compliant |
|---|---|---|
| Each Modbus step's 3 s wait | the step and its transaction are FAILED, never treated as success. The durable obligation is kept (snapshot or marker retained, restore owed) and retried with backoff and a fresh classification. No new transaction can start while a frame is outstanding, because every writer has its own bus-quiet gate. | yes |
| The FB-D1 RTC deadline breaker | fires only on its 90 s deadline **and** proof that no RTC frame is outstanding. It releases only RTC-owned state, never the shared write lock, and ends ABORTED with a 5 min cooldown and an invalidated baseline. Unchanged by fcp2. | yes |
| The fallback Review leak breaker | fires only when its dispatch is not running, clears only that feature's own flag, and involves no inverter transaction. | yes |

**The gap: a leaked lock.** Nothing watched a lock that a code path failed to release, for example the shared write mutex. Such a
lock silently blocks every restore and the controller until a reboot. During a lease, export would carry on with no way to end it.

**The fix.** A lock-age monitor in the 5 s interval measures how long any inverter transaction lock has been held continuously:

- the shared write mutex;
- the Dump to Grid or Free Power operation flag;
- the register 244 apply flag.

Every transaction step is bounded by a 3 s wait, so no transaction can hold a lock for `ecco_write_lock_stuck_ms` (180 s). Past
that bound the lock is STUCK. **It is never released.** Instead, once per episode:

1. **An active Dump lease is ended durably.** `request_dump_end` commits `restore_requested` without the bus, with the reason
   `WRITE LOCK STUCK`. Its restore stays deferred behind the lock.
2. **While any lease or restore is owed in any domain, the device restarts** through the internal primitive. The boot path is the
   designed recovery path: it re-opens every durable obligation and runs the ownership-checked restore with fresh RAM.
3. **With nothing owed it reports only.** `Restart Status` reads `STUCK LOCK - ...`, and inverter writes stay blocked until a
   restart.

The census reports a STUCK lock as overridable, because it is not a transaction in flight, so `Restart Override Arm` plus
`Restart` is the operator's recovery.

**Residual risk.** If a code path leaks the lock again after every boot, the device restarts at most once per bound (each boot then
completes the owed restore). The cycle is logged and visible in `Restart Status`.

## Not in this phase

**SG-25, the DST-aware TOU charge-slot gate.** The START gate walks the lease window in local minutes from `now`, so on the
spring-forward night a charge slot just after 01:00 can be missed.

The fix is to walk the window in UTC, converting each minute with `ESPTime::from_epoch_local`, and to refuse when either the
current offset or the DST-corrected offset overlaps a charge slot. The inverter's own clock may lag the change until ECCO's RTC
correction, which is why both offsets are checked.

It needs a simulator whose clock derives its hour and minute from the epoch and the Europe/London rules, which the existing
charge-slot suites do not model. It is therefore left for a separate, focused change.

## Compatibility

- **No new write operation**, and no new write domain. Register 245 is never written.
- **One new read:** the restore's pre-read of 244-261.
- **Every new global is RAM only.** No NVS key is added or changed.
- **No durable record schema, tag or header changes.** The one new commit site writes the existing retry record exactly as the
  verify-mismatch lockout already does.
- **The 4 October rollback firmware is unaffected.**
