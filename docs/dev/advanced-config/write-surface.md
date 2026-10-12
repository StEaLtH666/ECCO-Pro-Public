# ECCO firmware Modbus write surface (read-only audit)

- Worktree: `(private scratch path removed)` @ public main `fbe03aa`
- Firmware: `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` (23 631 lines). `FW:n` = line in this file.
- Offline tool: `python tools/analyze_write_surface.py` ran OK (exit 0). Raw output: `analyzer.txt` / `analyzer.json` in this directory.
- Nothing modified, no network, no HA/dongle contact.

All inverter writes use `modbus_client.write_multiple_registers` (FC16), slave `0x01`, bus `inverter_modbus` (FW:1477-1480, 9600 8N1).
There is no `write_single_register`, no raw `uart.write`, no `modbus_controller`. The analyzer's coverage walk found no write outside a `script:`.
Every Modbus op in the file, with its line number, is tabulated at the end (Appendix A).

---

## 1. Write paths (16 scripts, 5 register groups)

Written registers: **22-24, 230, 232, 244, 250-261, 268-279** (30 registers). This set is pinned by
`registry/tests/test_write_surface_invariants.py:129-135` (`EXPECTED_WRITTEN_REGISTERS`), and the path list is pinned at `:72-127`.

### Arm switches (FW:5041-5153). All are `optimistic`, `restore_mode: ALWAYS_OFF`, and turning one on writes nothing.
| Switch (HA entity) | id | Disarm behaviour |
|---|---|---|
| Manual Configuration Write Enable (`switch.ecco_clock_dongle_manual_configuration_write_enable`) | `manual_config_write_enable` FW:5067 | turned off at every Apply/Restore outcome (accepted, refused, failed or verified; ~70 `turn_off()` sites FW:12874-16860, 21581-22174). **No lifetime timer**: it stays armed until the next Apply or Restore attempt or a reboot (unlike the Fallback arm's 120 s) |
| Free Power Write Enable | `free_power_write_enable` FW:5085 | off as soon as START is accepted (FW:7769) and on refusal |
| Dump to Grid Write Enable | `dump_write_enable` FW:5113 | off at START accept (FW:16999) and on refusal |
| Free Power Recovery Arm / Dump to Grid Recovery Arm | FW:5100 / FW:5129 | one-shot, used by the recovery actions |
| Automatic Clock Sync | `automatic_clock_sync` FW:5043 | a standing enable for RTC, not a per-write arm |

### Path table
| # | Script (FW line) | Trigger | Registers (FC16 extents) | Value source | Arm | Snapshot / durable | Verify | Sequencing |
|---|---|---|---|---|---|---|---|---|
| 1 | `write_inverter_rtc` (7578) | Sync button FW:21345 (manual), 1 s RTC tick via `ecco_rtc::decide()` FW:21216-21260 (auto) | 22-24 (one write) | computed from NTP `now()` (YY<<8\|MM, DD<<8\|hh, mm<<8\|ss) | none (auto sync is a standing enable) | none (the analyzer's "durable_commits=1" counts the comment at FW:7716 - an artefact) | separate verify read 10 s later via the 1 s tick (`verification_pending`), plus one retry, then FAILED + cooldown | callbacks; deadline breaker 90 s (`ecco_rtc_policy.h:54`) |
| 2-7 | `apply_manual_slot1..6` (12570, 13061, 13451, 13841, 14231, 14621) | Apply Manual Slot N button (FW:21567...22003) | 232; start/end pair; power; SOC; flags (see 2.1) | staged number/select/switch entities, plus preserved bits from the raw cache | Manual Configuration Write Enable | **none**: no snapshot, no durable record, RAM only | read-back: 232 bit0 only; time/power/SOC/flags exact | fixed `delay:` 700/1200/900 ms, no `wait_until` |
| 8 | `apply_reg244_settings` (15908) | Apply Staged Reg244 button FW:22139 | 244 | staged select `manual_reg244_staged_target` (0/1/2) | Manual Configuration Write Enable | fresh read, then two-phase `commit_record` (REG244 data + RESTORE_REQUIRED marker) before the write | exact reread of 244 | `wait_until` on `reg244_op_terminal`, 3000 ms each |
| 9 | `restore_reg244_snapshot` (16392) | Restore Original Reg244 button FW:22160 | 244 | durable snapshot value | Manual Configuration Write Enable | Phase C PENDING_CLEAR, then Phase D CLEAR | exact reread; drift guard against the last verified applied value | `wait_until` 3000 ms |
| 10 | `start_free_power_override` (7722) | START FREE POWER button FW:21372 (HA schedule presses it) | 232 (bit0 set), 230, 268-279 (SOC=100, flags source bits=Grid), 256-261 (=target W) | computed (amps from W/live V; power) + snapshot | Free Power Write Enable | 3 fresh reads (230-232, 256-279, 244-255), then two-phase durable commit (all 20 regs, intended targets, 244 lease context) + journal | exact on every owned register (FW:8640-8670) | `wait_until` x10 |
| 11 | `restore_free_power_snapshot_dispatch` (9082), via wrapper `restore_free_power_snapshot` (8863) | END button FW:21380, 15 s watchdog FW:22224, schedule end | 232, 256-261, 268-279, 230 | durable snapshot | none (restore = safe direction) | Phase C/D marker; retry/backoff record | exact; classifier original/intended/self-partial | `wait_until` x11 |
| 12 | `free_power_recovery_force_restore_dispatch` (11072), via `free_power_recovery_force_restore` (10935) | API action `free_power_recovery_execute` (FW:1306) only | same as #11 | durable snapshot | Recovery Arm + fresh evidence ID + phrase `FORCE RESTORE ORIGINAL <id>` | as #11 | exact | `wait_until` |
| 13 | `start_dump_to_grid_override` (16895) | START DUMP button FW:22178 | 256-261 first (verified), then 244=0 last | computed ceiling; literal 0 | Dump to Grid Write Enable | two-phase durable commit before the first write | exact | `wait_until` x7 |
| 14 | `dump_controller_tick` (17786) | 15 s Dump watchdog while ACTIVE (FW:22474) | 256-261 | computed closed-loop ceiling | none (lease-driven) | durable evidence commit before every write (FW:18120-18145) | exact reread of 256-261 | `wait_until` |
| 15 | `restore_dump_to_grid_snapshot` (18531) | END button (`request_dump_end`), watchdog FW:22281, Force Restore FW:19015 | 244 then 256-261 | durable snapshot | none | Phase C/D | exact | `wait_until` |
| 16 | `dump_lockout_containment` (19194) | Dump watchdog, last step (FW:22511) | 244 := **2** (Zero Export) only | literal | none (fail-safe) | none | reread | `wait_until` x4 |

Paths that take the shared mutex but **write nothing to the inverter**: FP review (10517), Accept Current State (12049/12104), Fallback Profile review/capture (19580) and save (20731). Their reads still take the mutex.

### 1.1 Common gate vocabulary (copied from the hardened paths)
- `!manual_write_in_progress` (the shared mutex), `!correction_in_progress` (the RTC lock)
- lease/obligation flags: `free_power_{active_persisted,snapshot_valid,operation_in_progress}`, `dump_{active_persisted,snapshot_valid,operation_in_progress,recovery_metadata_corrupt}`, `reg244_{snapshot_valid,apply_in_progress}`, `*_recovery_metadata_corrupt`
- bus quiescence: `id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked()`
- `configuration_online.state`; NTP `ntp_synced && ntp_time.now().is_valid()` (FP and Dump only; **manual TOU and reg244 do not require NTP**)
- FP and Dump also check battery voltage 40-65 V; Dump also checks SOC, CT, cfg freshness and the TOU conflict scan (FW:16898-16940)

---

## 2. MANUAL CONFIGURATION write paths (the precedent for an edit feature)

### 2.1 TOU slots: `apply_manual_slotN`
**Registers per slot** (FC16; a slot's END is the next slot's START):
| Slot | 232 | start | end | power | SOC | flags |
|---|---|---|---|---|---|---|
| 1 | bit0 | 250 | 251 (2-reg write 250-251) | 256 | 268 | 274 |
| 2 | bit0 | 251 | 252 (251-252) | 257 | 269 | 275 |
| 3 | bit0 | 252 | 253 | 258 | 270 | 276 |
| 4 | bit0 | 253 | 254 | 259 | 271 | 277 |
| 5 | bit0 | 254 | 255 | 260 | 272 | 278 |
| 6 | bit0 | 255 | **250** (wraps; 2 separate 1-reg writes FW:14743, 14772) | 261 | 273 | 279 |

Note: changing slot N's End also moves slot N+1's Start, and slot 6's End is slot 1's Start. Register 232 bit0 is the **global** grid-charge enable, and every slot Apply rewrites it from `manual_stage_grid_charge_enabled`.

**Script gate (slot 1: FW:12573-12636; slots 2-6 are the same)**:
`manual_config_write_enable.state && manual_slotN_staging_loaded && manual_config_raw_cache_valid && configuration_online.state && !correction_in_progress && !manual_write_in_progress && !reg244_snapshot_valid && !free_power_recovery_metadata_corrupt && !reg244_recovery_metadata_corrupt && !FP{AP,SV,OIP} && !DUMP{AP,SV,OIP,corrupt} && !reg244_apply_in_progress && tx_buffer_empty && !tx_blocked`, plus value checks:
- HHMM 0-2359, hh<=23, mm<=59, **mm%5==0**, start!=end
- power 0..`${ecco_inverter_tou_power_ceiling_w}`=8000
- SOC 0-100
- existing flags register mode bits (&0x001C) must be one of 0x00/0x04/0x08/0x10

**Button gate** (FW:21567-21582) duplicates the FP/Dump checks. On refusal it disarms and publishes "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings".

**Value composition** (FW:12638-12673):
- 232 = cache & 0xFFFE | stage bit
- times, power and SOC come straight from the staged numbers
- flags = cache & 0xFFE0 | source(0-3) | mode(0x04/0x08/0x10). Reserved bits are preserved.

**Acquire** (FW:12666-12671): `manual_write_failed=false`, `manual_verify_reg232_ok=false`, `manual_write_in_progress=true`, `staging_loaded=false` (staging is consumed), `manual_write_attempts++`. It publishes "Writing Slot1 HHMM-HHMM, W, %, src/mode, grid charge ON|OFF".

**Sequence**:
1. write 232
2. 700 ms, then write start/end
3. 700 ms, then write power
4. 700 ms, then write SOC
5. 700 ms, then write flags

Each write after the first is skipped once `manual_write_failed` is set (fail fast). Every callback (`on_error`, `on_no_response`, `on_not_sent`, `on_custom_response`) sets `manual_write_failed`. After 1200 ms:
- On failure: `manual_write_failures++`, mutex released, disarm, "FAILED - one or more write transactions failed; no automatic retry". There is **no rollback**, so a partial write is possible.
- Otherwise verify:
  - read 232 x1: **bit0 compare only** (FW:12880-12887)
  - 700 ms, then read 250 x25 (slot 1) or x30 (slots 2-6): exact compare of start, end, power, SOC and flags (FW:12925-12933)
  - "VERIFIED OK - manual Slot 1 settings match inverter readback" with `manual_write_successes++`, or "VERIFY FAILED read T1/T2/P/SOC/FLAG=... expected=..." with `manual_write_failures++`
  - the cache is refreshed from the read-back, the mutex is released and the arm is disarmed
  - the read's error/timeout/not_sent/custom callbacks give "VERIFY FAILED - Slot 1 verification Modbus error | timed out | read could not be queued | returned a non-standard reply"
  - then 900 ms, then `poll_inverter_configuration`

The verify read has no bounded `wait_until`: the mutex is released only inside the read callbacks. This is the lock-leak case that the diag lock-age sensor watches for.

**Refusal texts** (`manual_config_last_result`, FW:12976-13007), in priority order:
1. "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings"
2. "REJECTED - Register 244 proof transaction in progress"
3. "REJECTED - Modbus bus busy with another transaction; try again shortly"
4. "REJECTED - no fresh configuration raw cache; refresh configuration first"
5. "REJECTED - inverter configuration is offline"
6. "REJECTED - RTC correction currently active"
7. "REJECTED - manual configuration write already active"
8. "REJECTED - Register 244 proof transaction awaiting restoration"
9. "REJECTED - arm Manual Configuration Write Enable first"
10. "REJECTED - load current Slot 1 values into staging first"
11. "REJECTED - staged Slot 1 values failed safety validation"

Every refusal disarms.

**Load (staging) buttons** (FW:21490-21564; Load All FW:22021-22074).
- Gate: cache valid, !MWIP, no FP/Dump/R244 ownership or corrupt, `!manual_tou_owner_seen`, and `cfg_block_b_response_dispatch_seq >= manual_tou_staging_min_cfg_seq`.
- Effect: publishes the cached raw values into the staging numbers and selects, and sets `staging_loaded`.
- Refusal texts: "REJECTED - cannot load Slot N staging while Free Power or Dump to Grid owns TOU settings (live values may be a temporary overlay)", "...while the register 244 proof transaction owns inverter settings", "Cannot load Slot N staging yet - waiting for a configuration refresh read after ...", "Cannot load staging - refresh configuration first".

**Staging invalidation interval** (1 s, FW:23601-23631). Whenever FP or Dump owns or may own the TOU registers, it:
- clears all six `staging_loaded`
- sets `manual_tou_owner_seen`
- fences Load until a configuration poll that started after the release (`cfg_block_b_dispatch_seq + 2`)
- publishes "Manual TOU staging CLEARED ..." or "... invalidated ..."

**Staging entities** (number section FW:4665+). All are `restore_value: false`:
- `manual_slotN_start_hhmm` / `_end_hhmm` (0-2359, step 5)
- `_power` (0-8000, step 100)
- `_soc` (0-100, step 1)
- selects `manual_slotN_charge_source` (None/Grid/Generator/Grid + Generator) and `manual_slotN_mode` (None/General/Backup/Charge)
- switch `manual_stage_grid_charge_enabled`

**HA invocation sequence** (entities found in `home-assistant/`):
1. `button.ecco_clock_dongle_load_current_slot_N_to_manual_staging` (or `..._load_all_current_tou_slots_to_manual_staging`)
2. set `number.ecco_clock_dongle_manual_slot_N_{start_hhmm,end_hhmm,power,target_soc}`, `select.ecco_clock_dongle_manual_slot_N_{charge_source,mode}`, `switch.ecco_clock_dongle_manual_stage_grid_charge_enabled`
3. `switch.turn_on` `switch.ecco_clock_dongle_manual_configuration_write_enable`
4. `button.press` `button.ecco_clock_dongle_apply_manual_slot_N_settings`
5. read `sensor.ecco_clock_dongle_manual_configuration_last_result` (VERIFIED OK / VERIFY FAILED / REJECTED / FAILED), plus `sensor.ecco_clock_dongle_manual_write_in_progress` (diagnostic)

There is no API action. Everything goes through buttons, numbers, selects and switches.

**Live status**:
- Stage 3.3 hardware test 2026-09-15 (private `ECCO-Pro/docs/stage3_3-six-slot-hardware-test.md`):
  - no-change Apply of slots 2-6 VERIFIED OK
  - a reversible 8000->6000->8000 W power change
  - a reversible slot-6 start (reg 255) boundary change seen on the inverter screen
- `registry/inverter_capabilities.yaml` marks every `tou_slot_N_*` field `live_proof_status: live_proven_write`, `recovery_implementation_status: partial` (volatile cache only, e.g. :261, :313).
- Owner use on 2026-10-10 (Live Match B10 DRIFT dx=00080 = reg 268; recorded in session memory `fbd1-soak-analyser-status.md:93-95`, not in repo docs):
  - 09:34 BST slot 1 SOC 100->40
  - 09:38 BST 40->100
  - 22:32 BST 100->40
  - all verified and attributed
- The public repo contains no LP- record for these, only the private archive.

### 2.2 Register 244 proof transaction (`apply_reg244_settings` / `restore_reg244_snapshot`)

**Apply**. Gate (FW:15914-15957):
- arm, `reg244_staging_loaded`, `configuration_online`, !correction, !MWIP, !reg244_apply_in_progress, !reg244_snapshot_valid (one transaction at a time), !reg244 corrupt, !FP{AP,SV}, !DUMP{AP,SV}, bus quiet
- target in {0 Allow Export, 1 Essentials, 2 Zero Export}

Sequence:
1. acquire `reg244_apply_in_progress` and `manual_write_in_progress`; `reg244_apply_attempts++`
2. **dedicated fresh read** of 244 (not the cache); raw>2 means REJECT
3. two-phase durable commit (`REG244_DATA_TAG`, then `REG244_VALID_TAG` = RESTORE_REQUIRED); set `reg244_snapshot_valid`; invalidate `reg244_last_applied_valid` **before** the write
4. write 244
5. exact reread

Every callback is guarded with `if (!reg244_apply_in_progress) return;` (a stale-callback guard). Each step has a 3000 ms bounded `wait_until`. Any uncertain outcome **keeps the snapshot**.

Result texts (`reg244_last_result` = `sensor.ecco_clock_dongle_reg244_test_last_result`):
- "VERIFIED OK - register 244 now X (...); original Y (...) saved - RESTORE AVAILABLE when ready"
- "UNCERTAIN - write to register 244 failed or timed out; the inverter MAY have accepted it regardless. Original snapshot RETAINED ..."
- "VERIFY FAILED - read X, expected Y; original snapshot RETAINED for recovery"
- "FAILED - could not durably commit the recovery snapshot; nothing written"
- REJECTED family (FW:16298-16340): RECOVERY BLOCKED / snapshot already pending restore / FP owns / Dump owns / offline / RTC active / another manual write / arm first / load staging first / bus busy / staged option failed validation

**Restore**. Gate: arm, snapshot_valid, !corrupt, value<=2 or PENDING_CLEAR, online, !correction, !MWIP, !apply, !FP/Dump, bus quiet.
- If the marker is PENDING_CLEAR: clear-only, no Modbus.
- Otherwise:
  1. fresh read
  2. **drift guard**: if live != last verified applied value, "REJECTED - live register 244 (X) no longer matches what ECCO last verified writing (Y); something else changed it - refusing to overwrite"
  3. write the snapshot
  4. exact reread
  5. Phase C (VERIFIED_PENDING_CLEAR), then Phase D (CLEAR)
- Results: "RESTORED OK - register 244 confirmed back at X", "... durable recovery-marker clear pending, will retry", or "RESTORE VERIFY FAILED ...".

**Live status**: the write was live-proven 2026-09-21 (PR #12), and the durability round trip (snapshot->write->verify->restore->clear) was live-proven 2026-09-22 (`docs/INVERTER_CAPABILITY_REGISTRY.md:165-170`; private `CURRENT_STATE.md:171-174`). It is the only `recovery_implementation_status: live_proven` capability.

**HA invocation**:
1. `button.ecco_clock_dongle_load_current_reg244_to_staging`
2. `select.ecco_clock_dongle_manual_reg244_staged_load_export_mode`
3. arm the switch
4. `button.ecco_clock_dongle_apply_staged_reg244_settings`
5. later re-arm, then `button.ecco_clock_dongle_restore_original_reg244`

Read `sensor.ecco_clock_dongle_reg244_test_last_result` / `..._reg244_original_snapshot`.

**This is the best template for a safe edit**: dedicated pre-read, durable snapshot, bounded waits, stale-callback guards, exact verify, and a restore with a drift guard.

---

## 3. Mutex, leases, obligation codes, RTC hold

### 3.1 The shared write mutex = `manual_write_in_progress` (FW:1757)
- RAM only.
- Acquired at FW: 7772 (FP start), 8917/9087 (FP restore), 10517 (FP review), 11036/11077 (force), 12049/12104 (accept), 12675/13141/13531/13921/14311/14701 (slots), 15964 (r244 apply), 16424 (r244 restore), 17027 (dump start), 18110 (dump ctrl), 18571 (dump restore), 19216 (containment), 19580 (fallback review/capture), 20731 (fallback save).
- The polls skip while it is held: telemetry 10 s (FW:22524), config 60 s (FW:22538), owed-poll 2 s (FW:22554, which also requires bus quiet and no dispatch running), clock read 60 s (FW:22513), and the Refresh buttons (FW:22076-22100).
- **Diagnostics** (observation only, FW:3946-3961, sampled by the 1 s tick FW:23559-23570): `diag_write_lock_held/since_ms/max_ms`, exposed as sensors "ECCO Modbus Write Lock Age" (FW:6081, 20 s) and "ECCO Modbus Write Lock Max Age Since Boot" (FW:6092). The same exists for the RTC correction lock.
- Fallback `lock_stuck` = MWIP && held >= 300 s, giving `BUS:LK` (`ecco_fallback_capture.h:1338-1342`).

### 3.2 Obligation vector (`ecco_fallback_capture.h`)
- `bus_busy()` (h:1331-1337) is the OR of 11 flags: MWIP, correction, verification_pending, verification_read_active, FP OIP, FP force, FP accept, reg244_apply, dump OIP, fallback op, and capture-dispatch running.
- `classify_bus`: LK > BY > OK (h:1388-1394).
- Code alphabet `obl_code` (h:1410-1446): CM, CA, CN, OK, UR, AC, ST, RR, PC, EN, ON, MC, BL, DV, LK, NP, BY.
- B3 (review) `obl=FP:xx,DP:xx,R4:xx,MT:xx,FS:xx,BUS:xx` (h:1449).
- B10 Live Match (`fallback_profile_live_match_text`, FW:5973; computed in `fallback_profile_live_refresh` FW:20444-20589) `obl=FP,DP,R4,BUS`, where a lease domain that is clear by its RAM legs reads **CR** (h:2496-2498). So `obl=FP:CR,DP:CR,R4:CR,BUS:BY` means no lease outstanding but the bus is busy.
- **MT (Manual TOU) has no durable state**: `MTOU_JOURNAL_NOT_IMPLEMENTED`. MT is clear iff BUS is clear (h:1400-1408, code CN).
- The FP/Dump controller ticks hold only MWIP. `bus_owner_text_with_leases` names them (h:1365-1376).
- **Write fence** (FW:20497-20511): `writes_fingerprint(manual_write_attempts, reg244_apply_attempts, reg244_restore_attempts, free_power_start_attempts, dump_start_attempts)` + bus_hot + lease_nonclear + cfg dispatch seq. Live Match's `mtou_running` lists `apply_manual_slot1..6` (FW:20518-20521).

### 3.3 RTC
- The RTC lock is `correction_in_progress`. `write_inverter_rtc` **defers** if MWIP is set at its dispatch point (FW:7592-7605) and refuses without NTP (FW:7700-7714).
- Every other writer refuses while `correction_in_progress` is set.
- **Lease hold**: `ecco_rtc::decide()` `lease_active` = FP{AP,restore_requested,OIP} || Dump{AP,restore_requested,OIP} || reg244_apply_in_progress (FW:21227-21230). This gives reason R_LEASE, so automatic corrections are held during energy transactions unless the error is >= 300 s (`ecco_rtc_policy.h:46,75,265`).
- Manual TOU is not in `lease_active` (it is covered only by the MWIP deferral).
- Deadline breaker: 90 s, releases RTC state only (FW:22576-22610).
- RTC writes stay outside the mutex. This is pinned as the known deviation `KNOWN_UNGUARDED` (test :285-289).

### 3.4 What a NEW write path must do to integrate
1. **Claim**: one synchronous lambda gate. It must require the arm, `!manual_write_in_progress`, `!correction_in_progress`, every FP/Dump/R244 lease and corrupt flag (copy apply_manual_slot's list), `configuration_online` and bus quiet. Then, in the same `then:` lambda, set `manual_write_in_progress=true` (plus an own `*_in_progress` flag if it is a multi-step transaction).
   - Tests [5] and [5b] enforce: acquire before the first write, check free before take.
   - Test [6] enforces release on every exit.
2. **`mode: single`**. Disarm on every outcome. Add the script to `EXPECTED_WRITE_PATHS` and widen `EXPECTED_WRITTEN_REGISTERS` only if a new register is written. The test pins both, deliberately, so a reviewer has to acknowledge the change.
3. **Sequencing**: copy the reg244 pattern, not the TOU `delay:` pattern:
   - a `*_op_terminal` flag set in every callback (`on_response`, `on_error`, `on_no_response`, `on_not_sent`; ideally also `on_custom_response`)
   - `wait_until` with a 3000 ms timeout (hub `send_wait_time` is 2000 ms)
   - a stale-callback guard `if (!own_in_progress) return;` in each callback
   - test [11] classifies paths as completion-driven or delay-paced
4. **Snapshot**: a dedicated fresh pre-write read, plus `ecco_durable::commit_record` data+marker before the write, if restore must survive a reboot (test [10] pattern). If the path only uses the RAM cache like the TOU slots, it is restore-less and `partial`.
5. **Verify**: exact reread of every written word, then a cache refresh. Note that the TOU 232 check is bit0 only.
6. **Fences**:
   - increment `manual_write_attempts` (or add a counter to `writes_fingerprint`) so a Fallback Review candidate and the Live Match fence see the write
   - add the script to `mtou_running` / `run_*` if it touches TOU or 244
   - if it is a lease, add it to the RTC `lease_active` and to the staging-invalidation `owned` predicate (FW:23604-23607)
7. Do not depend on an NTP gate unless time matters. The TOU and reg244 paths do not use one.

---

## 4. Read-only in practice (polled, never written)
| Block (start, count) | Script / FW | Written subset |
|---|---|---|
| 59-116 (59, 58) | poll_inverter_telemetry FW:15041 | none |
| 150-196 (150, 47) | telemetry FW:15200 (Dump feed-forward also reads 172-189, FW:17191) | none |
| 200-240 (200, 41), config Block A | poll_inverter_configuration_dispatch FW:15358 (fallback capture 230-232 FW:19642) | **230, 232** only; 200-229, 231, 233-240 never written |
| 241-293 (241, 53), config Block B | FW:15513 (fallback 241-293 FW:19701) | **244, 250-261, 268-279**; never written: 241-243, 245-249, 262-267 (slot voltages), 280-293 |
| 330 (1) | FW:15797 | none |
| 22-24 (3) | Read Inverter Clock button FW:20991 | written by RTC |

Other dedicated reads: 244 x1, 244-255 x12 (FP lease context), 256-261 x6, 256-279 x24, 268-279 x12, 230-232 x3.

Never written by any path: everything except {22-24, 230, 232, 244, 250-261, 268-279}. Examples:
- the battery settings in the capability registry (control/operation mode, voltages, capacity, max charge/discharge current, shutdown/restart/low SOC)
- generator settings
- 243, 245 (paired with 244 in the safe-transaction audit), 247 and 248, which are read only for fallback capture (`fbc_raw_243/245/247/248`)
- slot voltages 262-267

---

## Appendix A: every Modbus op (FW line, R/W, start, count)
Writes:
- 7615 W 22-24
- 8161 W232
- 8245 W230
- 8315 W268 x12
- 8519 W256 x6
- 9512 W232
- 9595 W256 x6
- 9795 W268 x12
- 9858 W230
- 11352 W232
- 11400 W256
- 11593 W268
- 11660 W230
- slot 1: 12691 W232, 12729 W250 x2, 12766 W256, 12800 W268, 12834 W274
- slots 2-6: same pattern (13149..14860)
- 16135 / 16594 W244
- 17435 W256 x6
- 17525 W244=0
- 18245 W256 x6
- 18578 W244
- 18666 W256 x6
- 19323 W244=2

Reads: listed in the analyzer.txt companion. Key reads: 7802 R230x3, 7851 R256x24, 7933 R244x12, 15041 R59x58, 15200 R150x47, 15358 R200x41, 15513 R241x53, 15797 R330x1, 17191 R172x18, 20991 R22x3.
