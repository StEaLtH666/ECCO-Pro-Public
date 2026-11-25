# GRC integration: patch proposal (NOT applied)

Nothing in this file is applied. It states exactly what a real integration of `firmware/proposed/ecco_gentle_rate_core.h`
would change, so the change can be reviewed, sized and authorised before anyone writes it. Every item below touches a
pinned or production artefact and therefore needs its own PR, its own review by someone other than its author, and the
owner's authorisation for any flash or live step (SPEC section 13: L3 onwards).

## 1. Firmware (`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, both targets)

**Substitutions** (one per `Config` field, the SPEC section 5 defaults), and an `on_boot` compile-time check:
`static_assert(ecco_grc::config_ok(grc_config()))` plus the production bounds (dwell 15-120 min, max changes <= 6,
night ceiling <= 9, floor >= 500, `fw_bound_w == ${ecco_inverter_tou_power_ceiling_w}`).

**The header moves into the build**: `git mv firmware/proposed/ecco_gentle_rate_core.h firmware/include/` (byte
identical) and `esphome: includes:` gains `include/ecco_gentle_rate_core.h` (after `ecco_rtc_policy.h`). The header
waits in `firmware/proposed/` in this offline stage because `registry/tests/test_fallback_save_scope.py` pins the set of
headers in `firmware/include/` ("a later PR declares its own in added_files"): the move is legal only together with
the chain entry below.

**Globals**: `grc_core` (an `ecco_grc::Core`, not restored: rebuilt at boot from the record), `grc_last_op`
(the `OpResult` reported on the next tick), `grc_lease_open` and `grc_operation_in_progress` (ownership flags),
`grc_plan` (the last valid hand-over, with its receipt time), `grc_night_id`.

**Hooks** (the core decides, the YAML only executes):

| Hook | Where | What |
|---|---|---|
| H1 boot | `on_boot`, after the durable layer is ready and before the first watchdog tick | load the GRC record (new durable key, tag `ecco_gentle_rate_v1`), `decode_record`, `grc_core.boot(status, rec, millis())`; publish state |
| H2 tick | a new `interval: 15s` block (startup delay 15 s) and the end of `poll_inverter_telemetry` | build `ecco_grc::In` from the published entities (SOC 184, battery power 190 sign-adjusted so charge is positive, the frame sequence, the configuration block's slot fields and its age, the clock and skew, `rtc` correction, the ownership flags of the other writers as `other`, the arm switch, the END / ACK buttons, `grc_last_op`), call `step`, clear `grc_last_op`, then: `commit` -> persist `record()` FIRST (a failed commit before a WRITE reports `OP_FAIL` next tick and issues nothing); `A_WRITE` / `A_RESTORE` -> `script.execute: grc_execute` |
| H3 execute | new script `grc_execute` (`mode: single`) | only when `!manual_write_in_progress && !correction_in_progress && tx_buffer_empty() && !tx_blocked()` (else report nothing: the core times the operation out); take `manual_write_in_progress` and `grc_operation_in_progress`; re-read register `256 + slot - 1`; WRITE: `ownership_ok_for_write(live, v)` else `OP_FOREIGN`; RESTORE: `classify_restore(live, original, v, p)` (ALREADY -> `OP_OK_NOWRITE`, FOREIGN -> `OP_FOREIGN`); `write_multiple_registers` start 256 + slot - 1, count 1; read back; `OP_OK` only on an exact match; every Modbus step bounded by the existing 3 s `wait_until`; release both flags |
| H4 plan hand-over | a new `api: actions:` entry `grc_set_plan` (slot, target, deadline, window_end, ceiling_w, capacity_wh, taper, n, t0..t7, p0..p7) | validate with `plan_ok`, store with the receipt `millis()`; an invalid hand-over is stored as invalid (a running lease then ends with PLAN_INVALID) |
| H5 controls | `switch` "Gentle Rate Write Enable" (`restore_mode: ALWAYS_OFF`, turned off by the firmware on `disarm`), `button` "Gentle Rate START", "Gentle Rate END", "Gentle Rate Accept Current State" (ACK) | |
| H6 status | text sensors (state, last reason, commanded slot power), sensors (writes tonight, changes, gain, realised reference power) | read-only |
| H7 exclusion | the START gates of `start_free_power_override`, `start_dump_to_grid_override`, `apply_manual_slot1`-`6`, `apply_reg244_settings` and the fallback writer | each refuses while `grc_lease_open` or `grc_operation_in_progress` ("REJECTED - gentle rate lease active") |
| H8 stuck lock | the existing `ecco_write_lock_stuck_ms` supervision | add `grc_operation_in_progress` to the watched flags |

Nothing else in the YAML changes. Register 230, the slot times, targets and flags are never written by the GRC.

## 2. Static analyzers, registry, authority, pins

- `tools/analyze_write_surface.py`: `OWNERSHIP_FLAGS` gains `grc_operation_in_progress`; the new write path
  `grc_execute` is classified (its single FC16 with a dynamic start address 256-261 and count 1 must be declared with
  its bounded extent: the analyzer currently treats a non-literal start address as unknown extent, so it needs a
  declared-extent annotation or a six-way literal dispatch, one `write_multiple_registers` per slot).
- `ecco_core/authority.py`: a new `WriteAuthority("gentle_rate", "control.grid_charge_rate", {"grc_execute"},
  _r(256, 261), {"grc_operation_in_progress", "manual_write_in_progress"}, "grc_write_enable",
  {"grc_lease_open"}, RESTORE_DURABLE, "the one slot power read back after each write",
  open_obligation_flags={"grc_lease_open"})`; `ecco_core/tests/test_core_authority.py` follows.
- `registry/inverter_capabilities.yaml`: the six `tou_slot_N_power` records list the GRC as a writer, recovery
  status `implemented_not_live_proven`; `docs/INVERTER_CAPABILITY_REGISTRY.md` "Full write surface" names
  `grc_execute` beside `dump_controller_tick`.
- Durable keys: the tag `ecco_gentle_rate_v1` joins the tag inventories (`registry/tests/_tag_inventory.py` users,
  `test_fallback_nvs_keyhash.py` key-collision universe, `test_fallback_profile_schema.py` counts) in the same PR.
- The change-scope chain (`registry/tests/_scope_chain.py`): a new entry `grc1` with exact-match reverters for every
  YAML edit above and `added_files` naming the header, so the older byte-for-byte pins keep proving "nothing else
  moved"; no existing pin is re-hashed.
- `tools/check_firmware_equivalence.py` on the PR: L0/L1 differ by exactly the entries above, L2 shows exactly one new
  write path; L3 (`--generate`) for both targets.
- `registry/tests/test_gentle_rate_core_host.py` follows the header's move (its `HEADER` path) and gains the
  integration's own checks (the YAML lambdas call exactly the documented hooks, nothing else writes register 256+).
- `firmware/include/ecco_fallback_version_pins.h` and the ESPHome version gates are untouched.

## 3. Build and flash (owner-authorised, L3)

Compile both targets with the reviewed tree; record the build identity; keep the running image for rollback; flash
only under the owner's authorisation for that step; soak at least 3 nights with the GRC enable never on; then L4.

## 4. Home Assistant (proposal only, not installed)

- **Plan source**: the Gentle model (`frontend/ecco-plan-core`, `planGentle`) already computes the gentlest rate; a
  backend twin (Python, in the trusted HA side, not the card) produces the plan points as wanted realised power from
  the measured SOC, the deadline (window end minus the owner's buffer, default 60 min), the pessimistic capacity, the
  owner's maximum (`input_number.ecco_max_grid_charge_power`) and the taper knee. Intelligence stays SHADOW and is not
  an input.
- **Hand-over automation**: every 5 min while armed or leased, `esphome.<node>_grc_set_plan` with the latest plan
  (re-plan every 15 min, re-send unchanged otherwise); never during a clock-change night.
- **Guarded start script** `script.ecco_gentle_rate_start`: refuses unless the owner armed tonight (an
  `input_boolean.ecco_gentle_tonight` the owner sets in the evening; it turns itself off at 06:00), a fresh plan exists,
  no other lease is active, it is not a clock-change night; turns the firmware enable on, presses START five minutes
  after the window start (the charge must be running), turns the enable off whatever the outcome; retries at most 10
  min, never a missed run after a restart (the R9 rule).
- **Gates**: the start script and the automation are owner-armed only; no schedule arms the firmware enable on its own
  without the owner's nightly or standing decision; the card shows the GRC state, the commanded and realised power, the
  writes used and the last reason, and offers END and Accept Current State behind the existing confirmation pattern.
- **Card**: the Energy Actions card gains a read-only "Gentle charge" panel and the END button; no new exposed entity
  without the owner's decision.

## 5. What stays unknown until the live proofs

See SPEC section 14. In particular the defaults for the taper knee, the tail share and the night write ceiling are
deliberately conservative guesses and must be replaced by measured values (SPEC L0-L2) before a normal night (L7).
