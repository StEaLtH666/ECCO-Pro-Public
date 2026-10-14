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

**The windowed mean (added after the independent audit).** A sustained overshoot that sits mostly UNDER the backstop got past
the k-of-8 rules. The audit's case ran 800 s at a 6000 W command: 3 samples in 8 at backstop + 900 W and the rest just under it,
a mean discharge 1323 W above the command.

Each valid sample's excess over the **expected** draw, the command × (1 + the profile's DC allowance), is now clipped to
[−`ecco_dump_runaway_mean_margin_w`, one backstop margin]. Once 8 valid samples exist, a mean above `ecco_dump_runaway_mean_margin_w`
(300 W) ends the lease: `SUSTAINED POWER EXCESS (windowed mean)`.

Because of the clip, a single glitch adds at most one margin. The audit's case trips at its 8th sample. None of these trips:

- the pessimistic loss model (12 % + 100 W) at any level from 500 W to 8000 W;
- the recorded leases;
- two isolated gross spikes.

**Documented tolerances.** These do not trip:

- one sample in four, less than one margin above the backstop, with the rest at the expected draw;
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

**The fix (as reworked after the independent audit).** Before writing anything, inside the same critical section, the restore
reads 244-261 once (an 18-register read) and classifies each register:

| Register | ORIGINAL (the snapshot) | ECCO's own value | Anything else |
|---|---|---|---|
| 244 | left alone | 0, Allow Export (what START writes): restored FIRST and verified | FOREIGN, never written |
| 256-261, each slot | left alone | the verified ceiling, the possibly-landed pending ceiling (the Dump V2 evidence) or the containment value min(original, 500 W) | FOREIGN, never written |

**Then 256-261, per slot:**

- **244 proven out of ECCO's Allow Export** (ORIGINAL, FOREIGN, or restored and verified): ECCO's own slots go back to their
  ORIGINAL values.
  - With nothing FOREIGN this is the single 6-register write (the pre-fcp2 write).
  - Otherwise it is one register at a time, so **a FOREIGN slot is never written**.
- **244 NOT proven** (its write errored, timed out, or was acknowledged but not applied): the step **CONTAINS** instead. Every
  non-FOREIGN slot goes to min(original, the 500 W controller floor), so the discharge ECCO's OWN settings allow under an export
  ECCO cannot switch off is bounded. The attempt still fails and keeps its retries and its obligation; restoring the originals
  there would raise the ceiling under a live Allow Export.
- **A FOREIGN slot cannot be contained** (final rework, independent re-audit C1). ECCO never writes a value someone else set, so
  while 244 is not proven an external value above 500 W stays exactly as it is: the 500 W bound covers ECCO's own slots only. This
  needs two faults at once (an external TOU change and a 244 the inverter refuses). Every containment status and the `CRITICAL`
  alarm then **name the uncontained settings**, for example
  `...; 244 NOT proven off - NOT CONTAINED (external): 258=7777W 260=6500W; ECCO's own at 500 W`. The texts stay within Home
  Assistant's 255 characters even with all six slots external.
- **Every slot written is read back and verified.**

**The outcome:**

- **Success** only when everything ECCO attempted was written AND verified and nothing is FOREIGN.
- **The FOREIGN lockout** only in that same case (independent audit B1). It sets the existing durable operator-needed record and
  publishes `OPERATOR DECISION REQUIRED - ECCO's own settings were restored and verified, but an external change was found and NOT
  overwritten (...)`. The operator chooses **Force Restore Original** or **Accept Current State**.
- **A failed step** takes the mismatch path (one retry, then the operator) or the comms-backoff path (unbounded retries), never the
  FOREIGN lockout.
- **No status ever implies export is off when it isn't proven.** While 244 is not proven, every status names it, names the
  containment when that was verified, and names every FOREIGN slot that is NOT contained.
- **Every command's completion flag is reset before the command.** The `d9f11ea` restore did not do this before its 244 write, so
  on the real (asynchronous) Modbus hub each later wait was satisfied by the previous command's reply. A 256-261 write that was
  acknowledged but not applied was then declared RESTORED OK. An asynchronous-hub model and a static check now cover this.
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

Rework (independent audit F3), corrected by the final rework (independent re-audit RF1):

- **Idle battery, only when the grid agrees.** Battery power within `ecco_dump_frozen_idle_w` (50 W) of zero is idle, never
  "frozen", **only when independent evidence explains it**: a grid CT reading from the same telemetry frame, itself not frozen,
  showing no export beyond PV. Otherwise a repeated 0 W is a repeat like any other: register 190 may be stuck.
  - `5178e0f` exempted every reading near 0 W. With register 190 stuck at 0 W and the SOC stuck, a 6000 W lease exporting ~5.5 kW
    was never ended (the frozen-SOC count integrated only the stuck reading). It now ends at 45 s.
- **Toggling SOC:** the frozen-SOC energy count restarts only when the SOC drops below its lowest value since the last restart, so
  a SOC toggling between two values cannot defeat it.
- **New lease:** the count starts from the SOC at START.

**The battery-vs-grid cross-check (final rework, RF1).** Battery power and SOC can both be stuck, so neither may vouch for the
other. The grid CT (register 172) and the PV strings are decoded from the same telemetry frame just before register 190, and on a
single-inverter site net export can only come from PV or the battery:

    battery discharge >= net export - PV      (house load and conversion losses only add to the discharge)

| Rule | Default |
|---|---|
| A battery reading more than max(`ecco_dump_xcheck_min_w`, `ecco_dump_xcheck_pct` of the bound) BELOW the bound is CONTRADICTED | 300 W, 10 % |
| `ecco_dump_xcheck_window_k` contradicted readings among the last 8 of a settled lease LATCH the decision; the watchdog ends the lease (`BATTERY POWER CONTRADICTED BY GRID`) | 4 of 8 |
| The CT reading must be at most `ecco_dump_xcheck_ct_age_ms` old (one frame), in range and not frozen - otherwise there is no evidence, and no idle exemption | 5 s |
| PV that is missing, negative or frozen (the same reading of at least 50 W for 30 frames) counts as 0 W: it can never excuse export | - |
| The frozen-SOC energy count integrates the LARGER of the battery reading and the bound, so a stuck SOC is caught even when register 190 under-reads | - |

- **Evidence.** In every in-lease sample of the four recorded leases (reference installation), battery discharge exceeded net export
  by at least 1.4 kW (the house load). The bound never came near.
- **No nuisance:** a battery genuinely idle at 0 W (the house importing, or PV covering the export), a healthy discharge, and a
  daytime discharge with PV, each for 30-60 minutes, never trip it.
- **Also caught:** a stale CT (no idle exemption, so the stuck reading counts as frozen), a CT also frozen, PV stuck high, a battery
  reading jittering near 0 W, and a battery under-reading (a gain fault).
- **Site assumption:** no other generation (for example AC-coupled PV) behind ECCO's CT. On such a site this check ends leases
  (fail closed) and must be re-validated before use.

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

**The restart waits for a quiet bus (rework).** It happens only when no Modbus frame is queued or awaiting a reply, re-checked every
5 s, so it can never cut an exchange in half.

**Residual risk.** If a code path leaks the lock again after every boot, the device restarts at most once per bound (each boot then
completes the owed restore). The cycle is logged and visible in `Restart Status`. There is no persistent restart counter. Bounding
the loop further is an owner decision, together with the reboot policy.

## 7. Export safety (independent audit R2)

**ECCO's export guard is a SECONDARY, lease-ending protection.** It acts on ECCO's own grid CT reading at the telemetry cadence
(one read every 10 s). It is not a DNO-compliant export limitation scheme. That is the inverter's own export limit, register 245,
which ECCO never writes.

- **The guard has no start grace.** It counts from the moment the lease is ACTIVE.
- **When it trips:**
  - ONE reading more than max(`ecco_dump_export_far_min_w` = 500 W, 25 %) over the limit;
  - or TWO of the last THREE readings over limit + max(100 W, 3 %) (final rework R2b: it was two CONSECUTIVE, which readings
    alternating just over and just under the threshold escaped - 3850 / 3600 W against 3680 W never tripped);
  - or the MEAN of the last four readings above the limit itself (R2b; exact for any alternation of two values, so 3780 / 3640 W
    trips, 3700 / 3650 W - a mean of 3675 W - does not).
- **How fast:** the decision is latched, and a 1 s interval ends the lease, so the response is one meter reading plus at most 1 s
  for a gross excess, and two readings plus at most 1 s for a marginal one. The audit's case (7000 W against 3680 W) ends at 10 s
  after START; it was 60 s.
- **After an End, while a restore is owed and 244 is not proven** out of Allow Export, the guard keeps sampling. With Stop SOC, a
  trip makes the owed restore retry at once (its containment included), never after a backoff. Under the operator lockout it
  raises a `CRITICAL` recovery state, which names any FOREIGN setting that is not contained.
- **The Stop SOC of that supervision survives a restart** (final rework, independent re-audit C8). The lease's own Stop SOC is RAM
  only, so after a reboot `5178e0f` had none. START now also persists it, bound to the obligation's end time
  (`dump_owed_stop_soc_rec`, flushed by START's own durable commit before anything is written). After a restart the supervision:
  - uses it only when it is bound to THIS obligation's end time and in range (10-90 %);
  - treats it as ALREADY REACHED when it is missing or bound to another obligation (fail closed);
  - also applies a higher configured Stop SOC;
  - treats a SOC reading that is missing or older than 90 s (once 90 s have passed since boot) as reached.
- **START fails closed on export.** It refuses when:
  - the target has no headroom below the limit (at least max(100 W, 3 %));
  - the grid meter ALREADY shows export above the limit;
  - its own fresh feed-forward read shows a natural PV surplus above the limit.

  The surplus is refused before the durable commit, so nothing is written. Under Zero Export the inverter throttles PV, so START
  sees only the surplus it shows; the in-lease guard covers the rest.

## 8. Invalid persisted limits (independent audit R3)

After the limits are INVALID (at boot), **both** the power ceiling and the maximum grid export must be confirmed again, each armed
and idle, before they are VALID. Re-setting one never re-validates the other, unconfirmed stored value.

Until both are confirmed the integrity value is not recomputed, so a reboot stays INVALID too. A stale export allowance can never be
silently reactivated.

**Immediate, checked persistence (final rework F5).** ESPHome queues a `restore_value` global only from its own 1 s poll and flushes
at `flash_write_interval`, so a power cut within about 2 s of a change brought the PREVIOUS, consistent and possibly higher pair
back at boot. Each accepted change now queues the changed values itself, the integrity value LAST, and flushes them synchronously
before anything is reported:

- the ESP32 backend writes its queue in order, one NVS entry at a time, so a flush cut short leaves a stored value that disagrees
  with the integrity value it was saved under - **INVALID at boot, never the old pair**. Each change alters exactly one limit, and
  the integrity value with it (proved for every prefix of the flush, a reduction, a raise and the re-confirmation sequence);
- a cut before the first flash write is a cut before the change was reported, and leaves the previous pair;
- a failed flush leaves the limits **INVALID at once** (START refused) until both are confirmed again, and says so;
- flash wear: an unchanged value is skipped by both layers, so only an owner's accepted change writes, and only the changed value
  and its integrity value.

## 9. Accept Current State (independent audit R4)

Accept refuses while any 256-261 slot still holds ECCO's own ceiling (the verified or the pending one) **above** its original value.
A raised TOU power setting would outlive the obligation. The operator uses Force Restore Original or lets the restore finish.

- FOREIGN values stay acceptable, because ECCO does not own them.
- ECCO residue at or below the original, such as the 500 W containment, only limits discharge and stays acceptable.
- The fresh post-operation readback requirement is unchanged.

## Independent audit: status of every finding

| Finding | Status | Where |
|---|---|---|
| B1 FOREIGN + failed 244 → one-attempt lockout, export live | RESOLVED | §3; tests `[W]` B1/O2 |
| R1 SG-04: block never restored when 244 fails; no supervision | RESOLVED (containment + post-END supervision); export can still remain enabled if the inverter refuses every 244 write, with ECCO's own settings bounded by the 500 W containment and alarmed. A FOREIGN setting is not contained; it is named (re-audit C1) | §3, §7; `[W]` R1/S4, `[X]` C1 |
| R2 export guard grace and cadence; START does not check export | RESOLVED (no grace, 1 s actor, START checks); it remains secondary protection by design | §7; `[W]` R2/D1/D2 |
| R3 one limit re-validates the other after INVALID | RESOLVED | §8; `[W]` R3/L1 |
| R4 Accept retires raised ECCO residue | RESOLVED (per-slot restore + Accept refusal) | §3, §9; `[W]` R4/A1 |
| F1 3-of-8 sustained overshoot escapes | RESOLVED (windowed mean) | §2; `[W]` F1/R3 |
| F2 backstop above physical capability at 8 kW; allowance extrapolated | OUTSTANDING (supervised per-level validation, unchanged plan) | §2 |
| F3 frozen battery at 0 W; SOC toggling | RESOLVED, its idle exemption corrected by RF1; fixed 1500 Wh stays site-dependent (OUTSTANDING: tie to battery capacity) | §4; `[W]` F3 |
| F4 stale `dump_restore_failed_ms` | RESOLVED (cleared on success and at START) | `[W]` F4 |
| F5 limit changes reach flash on a 1 s interval; linear integrity value | RESOLVED (final rework): synchronous flush, integrity value last; a partial flush boots INVALID, never the old pair. The integrity value stays linear: each change alters one limit and the integrity value with it, so no partial state can match | §8; `[X]` F5 |
| F6 OTA not gated; default reboot timeouts; restart loop; build tag default | OUTSTANDING: owner decisions and pre-flight tool (the restart now waits for a quiet bus) | §5, §6 |
| F7 target equal to the limit; one arm for both limits | Target headroom RESOLVED; the shared arm OUTSTANDING (owner decision) | §7 |
| F8 use the pre-read's 245-255 | OUTSTANDING (optional) | - |
| AT1 (Window 4 audit) the completion flag before the restore's 244 write | RESOLVED | §3; `[W]` AT1 |
| **RF1** (re-audit of `5178e0f`, BLOCKER) stuck-zero battery telemetry evades every guard | RESOLVED (final rework): the idle exemption needs grid evidence; the battery-vs-grid cross-check; the frozen-SOC count integrates the grid's bound | §4; `[X]` RF1 |
| C8 (re-audit) Stop SOC supervision lost after a restart | RESOLVED (final rework): persisted, bound to the obligation, fail closed when missing; a stale SOC counts as reached | §7; `[X]` P3 |
| R2b (re-audit) export alternating around the threshold | RESOLVED (final rework): two of the last three, and the mean of four | §7; `[X]` R2b |
| C1 (re-audit) FOREIGN slots uncontained while 244 is unproven; the status said every ECCO-controlled register was held | DOCUMENTED (cannot be contained by design - never written) and NAMED in every status and the CRITICAL alarm | §3; `[X]` C1 |
| DST (re-audit) the next UK change is the fall-back on 25 October 2026 | RECORDED, still deferred (operational restriction below) | "Not in this phase" |

## Not in this phase

**SG-25, the DST-aware TOU charge-slot gate.** The START gate walks the lease window in local minutes from `now`, so on a
clock-change night it checks local times that do not happen and misses ones that happen twice:

- **Fall-back, Sunday 25 October 2026** (the next UK change): 02:00 BST becomes 01:00 GMT, so 01:00-02:00 happens twice. A lease
  started in the first 01:xx is checked against 01:xx-02:xx local, but in fact runs through the REPEATED 01:00-02:00, so a charge
  slot there is not seen by the gate.
- **Spring-forward, Sunday 28 March 2027:** 01:00 GMT becomes 02:00 BST. The gate checks 01:00-02:00 local, which does not
  happen, and a charge slot just after it can be missed.
- **The inverter's own clock** may lag the change until ECCO's RTC correction, so its TOU slots may switch an hour away from what
  the gate assumed.
- **The lease end itself is safe:** it is an epoch (UTC) deadline, unaffected by the change.

**Operational restriction until SG-25 is implemented:** no Dump to Grid lease (manual or scheduled) between 00:00 and 03:00 local on
25 October 2026 or 28 March 2027.

The fix is to walk the window in UTC, converting each minute with `ESPTime::from_epoch_local`, and to refuse when either the
current offset or the DST-corrected offset overlaps a charge slot. The inverter's own clock may lag the change until ECCO's RTC
correction, which is why both offsets are checked.

It needs a simulator whose clock derives its hour and minute from the epoch and the Europe/London rules, which the existing
charge-slot suites do not model. It is therefore left for a separate, focused change.

## Compatibility

- **No new write domain**, and the set of written start addresses is unchanged. Register 245 is never written. The restore's six
  one-register writes (256..261) are new operations on registers Manual TOU already writes one slot at a time.
- **One new read:** the restore's pre-read of 244-261.
- **Every new global is RAM only, except ONE** (final rework): `dump_owed_stop_soc_rec`, the persisted Stop SOC of an owed
  restore. It is a NEW NVS key; no existing key is changed.
  - Firmware without it, including the 4 October rollback firmware, never reads it.
  - A value left over from an older lease never binds to a newer obligation (its end time differs). An obligation created by
    firmware that does not write it finds no bound value, and the supervision fails closed.
- **The power limits keep their keys and their integrity value.** The final rework only flushes them sooner.
- **No durable record schema, tag or header changes.** The one new commit site writes the existing retry record exactly as the
  verify-mismatch lockout already does.
- **The 4 October rollback firmware is unaffected.**
