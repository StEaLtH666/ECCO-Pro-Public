# GRC integration: patch proposal (NOT applied)

Nothing in this file is applied. It states exactly what a real integration of `proposed/ecco_gentle_rate_core.h`
(SPEC revision 3) would change, so the change can be reviewed, sized and authorised before anyone writes it. Every item
below touches a pinned or production artefact and therefore needs its own PR, its own review by someone other than its
author, and the owner's authorisation for any flash or live step (SPEC section 13: L4 onwards).

## 1. Firmware (`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, both targets)

**Substitutions** (one per `Config` field, the SPEC section 5 defaults), with two SITE substitutions that have **no
default in the base YAML** (an undefined substitution fails the build, so a site cannot forget them):
`grc_capacity_floor_wh` (the guard's capacity floor) and `ecco_battery_usable_capacity_wh` (the site's usable capacity;
on the reference installation the owner's capacity helper holds it, recorded in the private Gentle limits report, never
in this repository). The `Config` is built with `ecco_grc::site_config(${grc_capacity_floor_wh})`, and an `on_boot`
compile-time block checks:
`static_assert(ecco_grc::config_ok(grc_config()))`,
`static_assert(${grc_capacity_floor_wh} >= ${ecco_battery_usable_capacity_wh})` (the floor at least the usable
capacity; the report recommends the usable capacity plus its 6 % band),
`static_assert(${grc_rtc_busy_max_ms} > ecco_rtc::kTxnDeadlineMs)` (the GRC's RTC bound above the breaker's),
`static_assert(${grc_restore_stall_ms} > ${ecco_write_lock_stuck_ms})` (the stuck-lock restart comes first), and the
production bounds (dwell 15-120 min, max changes <= 6, night ceiling <= 10, floor >= 500, `fw_bound_w ==
${ecco_inverter_tou_power_ceiling_w}`, `script_step_ms` equal to the `wait_until` bound actually used in
`grc_execute`). The header's own `static_assert(op_timeout_ms > script_steps * script_step_ms + script_queue_ms)` keeps a
timed-out operation over before its result could arrive; its `static_assert(!config_ok(Config{}))` proves the default
cannot be used by accident.

**The header moves into the build**: `git mv docs/dev/gentle-rate-controller/proposed/ecco_gentle_rate_core.h
firmware/include/` (byte identical) and `esphome: includes:` gains `include/ecco_gentle_rate_core.h` (after
`ecco_rtc_policy.h`). The header waits outside `firmware/` in this offline stage because two suites pin what git tracks
there: `registry/tests/test_failback_shadow_ha_contract.py` hashes every tracked `.h` / `.yaml` / `.md` under
`firmware/` (the FB-C3 tree pin: any new file there fails it) and `registry/tests/test_fallback_save_scope.py` pins the
set of headers in `firmware/include/` ("a later PR declares its own in added_files"): the move is legal only together
with the chain entry `grc1` below, which declares the header in `added_files`.

**Globals**: `grc_core` (an `ecco_grc::Core`, not restored: rebuilt at boot from the record), `grc_last_op` (the
result to report: `op`, `op_seq`, `op_kind`, `op_value`), `grc_rx_ms` (the `millis()` of the last answered Modbus read;
**initialised to "never" at boot**, so `rx_age_ms` is NEVER until the inverter answers), `grc_lease_open`,
`grc_record_active` and `grc_operation_in_progress` (ownership flags), `grc_plan` (the last valid hand-over, with its
receipt time), `grc_night_id` (the local day number of the window start, rolling at local noon).

**Hooks** (the core decides, the YAML only executes):

| Hook | Where | What |
|---|---|---|
| H1 boot | `on_boot`, after the durable layer is ready and before the first watchdog tick | load the GRC record (new durable key, tag `ecco_gentle_rate_v3`, 48 bytes), `decode_record`, `grc_core.boot(status, rec, millis())`; publish state. On DEC_ABSENT (or a corrupt record), after the first configuration read call `lost_lease_slots(live[6], table[6])` with the six live slot powers and, as `table`, **the six slot powers of the saved fallback profile (FB-B2, `reg256_261`, durable and owner-saved; -1 each when no profile is saved)**, never the editor's staging numbers (`manual_slotN_power`: `restore_value: false`, initial 8000); publish a non-zero mask as the warning "slot power below the owner's saved value after a boot without a GRC record"; nothing is written on it |
| H2 tick | a new `interval: 15s` block (startup delay 15 s), the end of `poll_inverter_telemetry`, and the end of every `grc_execute` run | build `ecco_grc::In` from the published entities (SOC 184, battery power 190 sign-adjusted so charge is positive, the frame sequence, the configuration block's fields **for `core.slot` while a lease or restore is owed and for the plan's slot otherwise, with `cfg_slot` naming that slot** and its age, the clock and skew, `rtc` = `correction_in_progress`, the ownership flags of the other writers as `other`, `grid_ok` = register 194 grid connected AND grid frequency (79) in band, `rx_age_ms` from `grc_rx_ms`, the arm switch, the END / ACK / Restore original buttons, `grc_last_op`), with `mutex_busy = manual_write_in_progress OR grc_operation_in_progress OR grc_execute is running`; call `step`, clear `grc_last_op`, then: `commit` -> persist `record()` FIRST, **on every tick that sets it, with or without an action** (an owned readback, a fault or a give-back can be learnt in a tick that cannot emit; a failed commit before a WRITE reports `OP_FAIL` for that sequence and issues nothing; before a RESTORE the restore still runs, as returning `original` is the safe action); an action -> if `grc_execute` is still running, set `grc_last_op = DEFERRED` for that sequence and kind at once; else `script.execute: grc_execute` with the sequence, kind, value and `Out.slot` |
| H3 execute | new script `grc_execute(seq, kind, value, slot)` (`mode: single`, never invoked while running: H2 checks) | if `manual_write_in_progress or correction_in_progress or !tx_buffer_empty() or tx_blocked()`: `DEFERRED`, nothing written; take `manual_write_in_progress` and `grc_operation_in_progress`; re-read register `256 + slot - 1` (**no reply at all** within the 3 s `wait_until`: `NO_ANSWER`, nothing written; **an exception reply: `FAIL` with `op_value = -1`**, an answered failure); WRITE: `ownership_ok_for_write(live, v)` else `FOREIGN`; RESTORE: `classify_restore(live, original, v, p, q)` (ALREADY -> `OK_NOWRITE`, FOREIGN -> `FOREIGN`); `write_multiple_registers` start 256 + slot - 1, count 1; read back; `OK` only on an exact match, else `FAIL` with `op_value` = the readback (-1 when the readback went unanswered or answered with an exception); every outcome after the write was sent is `FAIL` or `OK`, never `NO_ANSWER`; release both flags; store `{result, seq, kind, op_value}` in `grc_last_op` and run the H2 tick at once. That tick sees `mutex_busy` (the script is still running): the core takes the result and commits what it learnt (the owned readback is on flash within milliseconds) and emits nothing; the next H2 tick (at most 15 s) emits the restore |
| H4 plan hand-over | a new `api: actions:` entry `grc_set_plan` (slot, target, deadline, window_end, ceiling_w, capacity_wh, taper, n, t0..t7, p0..p7) | validate with `plan_ok`, store with the receipt `millis()`; an invalid hand-over is stored as invalid (a running lease then ends with PLAN_INVALID). The core cross-checks `window_end` against the slot's own end every tick |
| H5 controls | `switch` "Gentle Rate Write Enable" (`restore_mode: ALWAYS_OFF`, turned off by the firmware on `disarm`), `button` "Gentle Rate START", "Gentle Rate END", "Gentle Rate Accept Current State" (ACK), "Gentle Rate Restore Original" (`restore_req`, acts only in FAULT) | |
| H6 status | text sensors (state, last reason, commanded slot power, the record state), sensors (`original`, the lease slot, writes tonight, **writes of the last 7 nights, lifetime writes, free retries tonight, the restore-owed time `stall_ms`**, changes, restore attempts, gain, realised reference power, `q`), the lost-lease mask | read-only; `original` and the slot are published at lease start and kept until the record clears; the 7-day and lifetime counts are kept by HA's long-term statistics (the record's lifetime count restarts with a lost or corrupt record) |
| H7 exclusion | the gates of every writer of 256-261 and of the fallback profile operations (table below) | each refuses while `grc_lease_open` (LEASED, ADJUSTING, SETTLING, RESTORING) or `grc_operation_in_progress` ("REJECTED - gentle rate lease active"); the snapshot-taking STARTs and the fallback profile operations also refuse while `grc_record_active` (a FAULT with `original` known); **the editor is never blocked in FAULT** |
| H8 stuck lock and RTC | the existing `ecco_write_lock_stuck_ms` supervision (`LOCK AGE` lambda and `ecco_lock_escalation`) and the RTC deadline breaker | `grc_operation_in_progress` joins the `held` flags; "an active GRC record that is not a FAULT" (a lease or a restore owed) joins the obligations for which `ecco_lock_escalation` restarts the device (the boot path then restores with fresh locks); the breaker is unchanged: it bounds `rtc_busy` to 90 s whenever no RTC frame is outstanding, and the GRC never starts an operation while `correction_in_progress` |

**H7, every writer of registers 256-261** (`python tools/analyze_write_surface.py --json` on the production firmware:
`write_surface` 256-261 lists exactly these seven script families; nothing else writes them):

| Writer | Proposed gate | Why safe |
|---|---|---|
| `apply_manual_slot1`-`6` | refuse while `grc_lease_open` or `grc_operation_in_progress`; allowed in FAULT | the owner's backstop in FAULT; its value is then FOREIGN to the GRC, which writes nothing over it |
| `start_free_power_override` | refuse while `grc_lease_open`, `grc_operation_in_progress` or `grc_record_active` | its snapshot must never take a lowered value as the original it restores |
| `restore_free_power_snapshot_dispatch`, `free_power_recovery_force_restore_dispatch` | none new (they already take the shared mutex) | only run when a Free Power restore is owed, which cannot coexist with a GRC lease (mutual START refusals); if it ever did, the GRC ends its lease (`other` bit 1) and classifies what Free Power restored |
| `start_dump_to_grid_override` | as Free Power START | as Free Power START |
| `dump_controller_tick` | none new | only inside a Dump lease, which cannot start during a GRC lease and refuses in GRC FAULT |
| `restore_dump_to_grid_snapshot` | none new | as the Free Power restores (`other` bit 2) |
| fallback profile review / capture / save (FB-B1, FB-B2; they write NVS, not 256-261) | their recovery-domain check (V6) gains `grc_lease_open` and `grc_record_active`; their bus gate already defers while `manual_write_in_progress` (taken by every GRC operation) | a capture during a lease or a GRC FAULT would save a lowered value as the owner's profile and poison `lost_lease_slots`; GRC START refuses while one is in flight (`other` bit 16) |

`apply_reg244_settings` (244 only) also refuses while `grc_lease_open`, to keep one writer at a time; `write_inverter_rtc`
(22-24 only) is met by the GRC's own `rtc_busy` deferral.

Nothing else in the YAML changes. Register 230, the slot times, targets and flags are never written by the GRC. No
grid-loss interlock exists in the base firmware; `other` bit 32 stays reserved, and any future interlock must let the
GRC restore of `original` through (SPEC section 12).

## 2. Static analyzers, registry, authority, pins

- `tools/analyze_write_surface.py`: `OWNERSHIP_FLAGS` gains `grc_operation_in_progress`; the new write path
  `grc_execute` is classified (its single FC16 with a dynamic start address 256-261 and count 1 must be declared with
  its bounded extent: the analyzer currently treats a non-literal start address as unknown extent, so it needs a
  declared-extent annotation or a six-way literal dispatch, one `write_multiple_registers` per slot).
- `ecco_core/authority.py`: a new `WriteAuthority("gentle_rate", "control.grid_charge_rate", {"grc_execute"},
  _r(256, 261), {"grc_operation_in_progress", "manual_write_in_progress"}, "grc_write_enable",
  {"grc_lease_open"}, RESTORE_DURABLE, "the one slot power read back after each write",
  open_obligation_flags={"grc_lease_open", "grc_record_active"})`; `ecco_core/tests/test_core_authority.py` follows.
- `registry/inverter_capabilities.yaml`: the six `tou_slot_N_power` records list the GRC as a writer, recovery
  status `implemented_not_live_proven`, and their `safety_impact` notes that a lowered value also caps that slot's
  discharge off grid (NOT ESTABLISHED, SPEC L1); `grid_connected_status` gains the GRC as its first consumer; a new
  record `battery_usable_capacity` names the site substitution `ecco_battery_usable_capacity_wh` (its value is a site
  value, never in the repository); `docs/INVERTER_CAPABILITY_REGISTRY.md` "Full write surface" names `grc_execute`
  beside `dump_controller_tick`.
- Durable keys: the tag `ecco_gentle_rate_v3` joins the tag inventories (`registry/tests/_tag_inventory.py` users,
  `test_fallback_nvs_keyhash.py` key-collision universe, `test_fallback_profile_schema.py` counts) in the same PR.
- The change-scope chain (`registry/tests/_scope_chain.py`): a new entry `grc1` with exact-match reverters for every
  YAML edit above and `added_files` naming the header, so the older byte-for-byte pins keep proving "nothing else
  moved"; no existing pin is re-hashed.
- `tools/check_firmware_equivalence.py` on the PR: L0/L1 differ by exactly the entries above, L2 shows exactly one new
  write path; L3 (`--generate`) for both targets.
- `registry/tests/test_gentle_rate_core_host.py` follows the header's move (its `HEADER` path) and gains the
  integration's own checks (the YAML lambdas call exactly the documented hooks, `grc_execute` reports a result with
  the sequence and kind on every path including DEFERRED, NO_ANSWER and an exception, every operation uses `Out.slot`,
  every committing tick persists the record before anything else, nothing else writes register 256+ while a GRC lease
  is open).
- `firmware/include/ecco_fallback_version_pins.h` and the ESPHome version gates are untouched.

## 3. Build and flash (owner-authorised, L4, L5a, L8a)

Compile both targets with the reviewed tree; record the build identity; keep the running image for rollback; flash
only under the owner's authorisation for that step; soak at least 3 nights with the GRC enable never on (L4); then the
proof image (L5a: floor 4000 W, 2 changes, night ceiling 6) for L5-L7, and the normal image (L8a) only before L8.
**From L5 on, every rollback (an earlier image, an NVS erase, a durable-key change) first requires the GRC record
inactive and the slot power read back equal to the owner's value; otherwise Restore original (or the editor) first.**

## 4. Home Assistant (proposal only, not installed)

- **Plan source**: the Gentle model (`frontend/ecco-plan-core`, `planGentle`) already computes the gentlest rate; a
  backend twin (Python, in the trusted HA side, not the card) produces the plan points as wanted realised power from
  the measured SOC, the deadline (window end minus the owner's buffer, default 60 min), the slot's real window end,
  the pessimistic capacity, the owner's maximum (`input_number.ecco_max_grid_charge_power`) and the taper knee.
  Intelligence stays SHADOW and is not an input.
- **Hand-over automation**: every 5 min while armed or leased, `esphome.<node>_grc_set_plan` with the latest plan
  (re-plan every 15 min, re-send unchanged otherwise); never during a clock-change night.
- **A copy of `original`**: at lease start an automation stores the published `original` and slot in helpers that
  survive restarts (`input_number.ecco_grc_original`, `input_number.ecco_grc_slot`), clears them only when the firmware
  publishes the restore verified, so neither ACK, a lost record nor a rollback loses the only copy.
- **After-window check**: at the slot's end plus 15 min (and at 06:00), an automation compares the live slot power
  (`text_sensor.<node>_ecco_timezoneN_power`) with HA's stored `original` (and with the saved fallback profile's value
  when one exists); any difference raises a persistent notification naming the slot, both values and the GRC state.
- **Lost record**: when HA's copy says a lease was open and the firmware publishes "no record" after a boot, HA compares
  the live slot power with its stored `original` and alerts on a difference (the firmware's own mask covers the case
  where a fallback profile is saved).
- **Alerts**: the GRC state FAULT (any reason, RESTORE_STALLED included) or the lost-lease mask non-zero raises a
  persistent notification at once with the reason, `original`, the live slot power and the two ways back (Restore
  original, the editor); **the GRC in RESTORING for more than 15 min** raises one too (an inverter that never answers
  stops the firmware from acting at all; HA's own timer covers it).
- **Guarded start script** `script.ecco_gentle_rate_start`: refuses unless the owner armed tonight (an
  `input_boolean.ecco_gentle_tonight` the owner sets in the evening; it turns itself off at 06:00), a fresh plan exists,
  no other lease is active, it is not a clock-change night; turns the firmware enable on, presses START five minutes
  after the window start (the charge must be running), turns the enable off whatever the outcome; retries at most 10
  min, never a missed run after a restart (the R9 rule).
- **Gates**: the start script and the automation are owner-armed only; no schedule arms the firmware enable on its own
  without the owner's nightly or standing decision; the card shows the GRC state, the commanded and realised power, the
  writes used (tonight, 7 days, lifetime), `original` and the last reason, and offers END, Accept Current State and
  Restore original behind the existing confirmation pattern.
- **Card**: the Energy Actions card gains a read-only "Gentle charge" panel and those buttons; no new exposed entity
  without the owner's decision.
- **A grid-loss abort for L2/L3** (only if L1 shows a cap and the owner cannot be present for the whole window): an
  automation that, on `grid_connected` false, applies the slot's previous value through the existing editor; it is a
  new HA change with its own review and authorisation, and it is not needed by the GRC itself (the firmware ends a lease
  on grid loss).

## 5. What stays unknown until the live proofs

See SPEC section 14. In particular the defaults for the taper knee, the tail share, the floor band and the night,
7-day and lifetime write ceilings are deliberately conservative guesses and must be replaced by measured values (SPEC
L0-L3) before a normal night (L8), and the off-grid effect of a lowered slot power (L1, the first step) decides whether
L2/L3 need the owner for the whole window and whether L5 may run at all.
