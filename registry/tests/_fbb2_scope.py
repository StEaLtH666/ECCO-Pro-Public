"""FB-B2 (Fallback Profile SAVE / REPLACE CORRUPT / INVALIDATE) change scope: exactly what FB-B2 adds to, and changes in,
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fbb1_scope.py (verbatim blocks held HERE as the single source of truth, exact (left, old, new, right)
hunks, a reverter that raises unless every hunk is present exactly once at its anchor). Earlier suites pin the firmware
YAML's globals, scripts, switches, api actions, intervals, includes and the FB-B1 blocks through the FB-T0 scope chain. FB-B2
necessarily edits those regions, so the chain entry `fbb2` (registry/tests/_scope_chain.py) carries `pre_fbb2_firmware`: the
current firmware text with exactly FB-B2's twenty-one edits removed, which reproduces the FB-B1 firmware byte-for-byte
(BASE_FW_SHA = the chain's fbb1 checkpoint). The older suites are anchored at their own entry and revert fbb2 FIRST; none of
them was re-hashed.

FB-B2 edits the firmware in twenty-one places (HUNKS, in file order): fourteen PURE INSERTIONS and seven one-line
REPLACEMENTS. Seven of the insertions sit at the boundary of an FB-B1 block, fourteen of the twenty-one hunks sit INSIDE
FB-B1's own text (so the fbb1 reverter, which runs after this one, finds its anchors again only once this one has run):

  at a block boundary (pure insertions)
    include            the `esphome: includes:` entry for the SAVE header, appended LAST (after the capture header)
    api_action         the `fallback_profile_execute` api action, appended AFTER ha_supervision_heartbeat
    globals            18 RAM-only globals (every one `restore_value: no`; no header-defined type)
    switch_arm         the template switch `ECCO Fallback Profile Arm` (ALWAYS_OFF; turn_on_action stamps the TTL time)
    save_final         the two SAVE_FINAL lambdas (verify, then commit) between REVIEW_FINAL and RELEASE of the capture dispatch
    scripts            the two scripts `fallback_profile_save` (gate) and `fallback_profile_invalidate` (synchronous gate + commit)
    tick2              the second, appended lambda of the 10 s housekeeping interval (arm lifetime, IE8)
  inside FB-B1 text (seven insertions, seven one-line replacements)
    boot_b2            the boot B2 text publishes the retained last write error / time (was 0, 0)
    review_arm_off     REVIEW press past V1 turns the arm off
    dispatch_drain     SAVE only: the pre-commit poller drain (bounded wait_until) before REVIEW_FINAL
    final_guard        REVIEW_FINAL returns when the purpose is SAVE
    final_overlay      REVIEW_FINAL derives eff_cls (the SAVE_UNCONFIRMED overlay of the composed class)
    final_state_name, final_ri_cls, final_prior_class, final_b3, final_not_saveable
                       five one-line replacements `e.cls` -> `eff_cls` (the overlay reaches B1, the review inputs, the candidate's
                       prior class, B3 and the not-saveable text)
    final_b2           REVIEW_FINAL's B2 publishes the retained last write error / time (was 0, 0)
    final_arm_off      REVIEW_FINAL turns the arm off before publishing a candidate
    release_ctx        the RELEASE lambda clears the SAVE context
    breaker_ctx        the housekeeping breaker clears the SAVE context (it still never assigns the write mutex)

The seven replaced lines are the ONLY pre-existing firmware lines FB-B2 modifies; every other pre-existing line is
byte-identical. Nothing in the deployment manifest, the Home Assistant packages or the firmware's other YAML files changes.

FB-T0 REGISTRATION: `pre_fbb2_firmware` is the reverter of chain entry `fbb2` (appended after fbb1). The chain records the
post-FB-B2 checkpoint and FB-B2's exact declarations. This module imports no other scope module and not _scope_chain (the
chain imports it).

Regeneration: the block literals below are the verbatim text of the firmware. After ANY change to the firmware YAML update the
affected literal here and re-pin the chain checkpoint in _scope_chain.py. test_fallback_save_scope.py proves every literal
against the firmware.

No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# main FB-B2 is based on (FB-B1 merged as PR #59).
BASE_COMMIT = "65e4be5c2077d65e8ba5979a8925e473ab6689e3"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML on main @ BASE_COMMIT: what pre_fbb2_firmware() must
# reproduce; equal to the chain's fbb1 checkpoint.
BASE_FW_SHA = "aa0d9f5286f8613d20957af1b561134007bfc69d8b50f0528295548b6e0d24de"

# The FB-A reserved tokens (restated: this module must not import the chain, where the same pattern lives as BANNED).
_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")
_INCLUDE_LINE = "    - {}\n"

# Every NEW repo file FB-B2 adds (the chain entry's `added_files`; exact POSIX paths, no glob). Existing files it modifies
# (the firmware YAML, ecco_fallback_capture.h, fallback_capture.py, the card, the dashboard, _fbb_harness.py, _fbb1_*.py, _scope_chain.py,
# older suites ...) are not declared anywhere. test_fallback_save_scope.py pins that this set is exactly what is on disk
# under the FB-B2 file names.
ADDED_FILES = frozenset({
    "firmware/include/ecco_fallback_save.h",
    "registry/fallback_save.py",
    "registry/tests/_fbb2_drive.py",
    "registry/tests/_fbb2_durable_ar.py",
    "registry/tests/_fbb2_durable_fam.py",
    "registry/tests/_fbb2_durable_lib.py",
    "registry/tests/_fbb2_durable_mut.py",
    "registry/tests/_fbb2_gates_lib.py",
    "registry/tests/_fbb2_gates_mutants.py",
    "registry/tests/_fbb2_gates_races.py",
    "registry/tests/_fbb2_gates_refusals.py",
    "registry/tests/_fbb2_gates_refusals2.py",
    "registry/tests/_fbb2_gates_static.py",
    "registry/tests/_fbb2_gates_success.py",
    "registry/tests/_fbb2_invalidate_kit.py",
    "registry/tests/_fbb2_invalidate_mut.py",
    "registry/tests/_fbb2_invalidate_scn.py",
    "registry/tests/_fbb2_save_double.py",
    "registry/tests/_fbb2_scope.py",
    "registry/tests/_fbb2_static_lib.py",
    "registry/tests/_fbb2_static_pins.py",
    "registry/tests/_fbb2_synth.py",
    "registry/tests/test_fallback_invalidate.py",
    "registry/tests/test_fallback_save_durable.py",
    "registry/tests/test_fallback_save_gates.py",
    "registry/tests/test_fallback_save_harness.py",
    "registry/tests/test_fallback_save_host_compile.py",
    "registry/tests/test_fallback_save_model.py",
    "registry/tests/test_fallback_save_scope.py",
    "registry/tests/test_fallback_save_static_pins.py",
})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Names (single source of truth for the suites; test_fallback_save_scope.py cross-checks them against the parsed firmware
# and the inserted blocks). Typed from the locked design (FB_B2_IMPLEMENTATION_NOTES.md section 8.2, D3/D4/D5/D10/D11/D13), not read back from the YAML.
# ---------------------------------------------------------------------------
# (id, C type, initial_value or None). Order is the order in the firmware. Every one is `restore_value: no`.
GLOBALS = [
    ('fallback_profile_exec_action', 'std::string', '""'),
    ('fallback_profile_exec_target_id', 'std::string', '""'),
    ('fallback_profile_exec_confirmation', 'std::string', '""'),
    ('fallback_profile_exec_hb_ok', 'bool', 'false'),
    ('fallback_profile_arm_on_ms', 'uint32_t', '0'),
    ('fallback_profile_save_unconfirmed', 'bool', 'false'),
    ('fallback_profile_save_unconfirmed_op', 'uint8_t', '0'),
    ('fallback_profile_save_unconfirmed_gen', 'uint32_t', '0'),
    ('fallback_durable_last_err', 'uint32_t', '0'),
    ('fallback_durable_last_us', 'uint32_t', '0'),
    ('fallback_profile_save_ctx_valid', 'bool', 'false'),
    ('fallback_profile_save_verified', 'bool', 'false'),
    ('fallback_profile_save_ctx_words', 'std::array<uint16_t, 31>', None),
    ('fallback_profile_save_ctx_id', 'uint64_t', '0'),
    ('fallback_profile_save_ctx_prior_class', 'uint8_t', '0'),
    ('fallback_profile_save_ctx_prior_gen', 'uint32_t', '0'),
    ('fallback_profile_save_ctx_prior_binding', 'uint64_t', '0'),
    ('fallback_profile_save_ctx_replace_corrupt', 'bool', 'false'),
]
NEW_GLOBAL_IDS = tuple(g[0] for g in GLOBALS)

SCRIPT_IDS = ('fallback_profile_save', 'fallback_profile_invalidate')
API_ACTION = 'fallback_profile_execute'
API_VARIABLES = {'action': 'string', 'target_id': 'string', 'confirmation': 'string'}
SWITCH_NAME = 'ECCO Fallback Profile Arm'
SWITCH_ID = 'fallback_profile_arm'
SWITCH_ICON = 'mdi:shield-key-outline'
HA_PREFIX = "ecco_clock_dongle_"


def ha_entity_id(domain: str, name: str) -> str:
    """Home Assistant entity id of a firmware entity: `<domain>.ecco_clock_dongle_<slug(name)>`, slug = lower-case,
    every run of non-alphanumerics -> `_`."""
    return f"{domain}.{HA_PREFIX}{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"


SWITCH_HA_ID = ha_entity_id("switch", SWITCH_NAME)

# ---------------------------------------------------------------------------
# The inserted blocks (raw firmware text, LF newlines)
# ---------------------------------------------------------------------------
def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


# Include list: the line is generated from ADDED_INCLUDES (never spelled out), like _fbb1_scope.py.
ADDED_INCLUDES = ("include/ecco_fallback_save.h",)
INCLUDE_BLOCK = "".join(_INCLUDE_LINE.format(i) for i in ADDED_INCLUDES)

# The api action fallback_profile_execute (appended after ha_supervision_heartbeat). (33 lines)
API_ACTION_BLOCK = _blk(r"""
    # Fallback Profile SAVE / INVALIDATE (FB-B2). The ONLY caller of
    # fallback_profile_save and fallback_profile_invalidate: reachable only
    # through the ESPHome API (this action), never from a firmware button, a
    # Home Assistant automation or any automatic trigger. It performs no Modbus
    # I/O, no storage access and no precondition check of its own: it copies its
    # three arguments (esphome::StringRef: valid for this call only, never NUL
    # terminated) into RAM at once, takes the one heartbeat snapshot the SAVE
    # gate needs (this is the ONLY Fallback Profile code that reads the HA
    # heartbeat state), and routes by the action token: INVALIDATE goes to its
    # own script, every other token goes to the SAVE gate, which refuses an
    # unsupported or reserved token. No api.respond: the outcome is the B9 text.
    # Appended AFTER the existing heartbeat action so that actions[0] stays
    # free_power_recovery_execute.
    - action: fallback_profile_execute
      variables:
        action: string
        target_id: string
        confirmation: string
      then:
        - lambda: |-
            id(fallback_profile_exec_action) = action.str();
            id(fallback_profile_exec_target_id) = target_id.str();
            id(fallback_profile_exec_confirmation) = confirmation.str();
            id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);
        - if:
            condition:
              lambda: 'return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size());'
            then:
              - script.execute:
                  id: fallback_profile_invalidate
            else:
              - script.execute:
                  id: fallback_profile_save
""")

# The 18 RAM-only globals of the operator write flow. (92 lines)
GLOBALS_BLOCK = _blk(r"""
  # ---------------------------------------------------------------------
  # Fallback Profile SAVE / INVALIDATE (FB-B2) - RAM-only state of the
  # operator write flow. Every global below is restore_value: no and has a
  # scalar / std::string / std::array type (a header-defined type cannot be
  # a global type). Nothing here is a durable record.
  #   exec_*              the raw arguments of the execute api action and the
  #                       heartbeat snapshot taken there; read ONLY by the two
  #                       gate lambdas (SAVE and INVALIDATE)
  #   arm_on_ms           stamped by the arm switch's turn_on_action (arm TTL)
  #   save_unconfirmed*   RAM overlay of an UNKNOWN write outcome (SAVE or
  #                       INVALIDATE), never cleared (a reboot resolves it);
  #                       _op / _gen are written on UNKNOWN and reserved: not
  #                       read or published in FB-B2 (the B2 grammar is frozen)
  #   durable_last_*      the B2 werr= / us= of the last write transaction
  #   save_ctx_*          the candidate copy taken when the SAVE gate accepts:
  #                       assigned ONLY there, cleared by the release lambda
  #                       and the breaker, the only candidate data the SAVE
  #                       final lambdas ever read
  #   save_verified       the hand-over from the SAVE verification lambda to the
  #                       SAVE commit lambda (consecutive lambdas, no yield)
  # ---------------------------------------------------------------------
  - id: fallback_profile_exec_action
    type: std::string
    restore_value: no
    initial_value: '""'
  - id: fallback_profile_exec_target_id
    type: std::string
    restore_value: no
    initial_value: '""'
  - id: fallback_profile_exec_confirmation
    type: std::string
    restore_value: no
    initial_value: '""'
  - id: fallback_profile_exec_hb_ok
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_arm_on_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_unconfirmed
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_save_unconfirmed_op
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_unconfirmed_gen
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_durable_last_err
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_durable_last_us
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_ctx_valid
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_save_verified
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_save_ctx_words
    type: std::array<uint16_t, 31>
    restore_value: no
  - id: fallback_profile_save_ctx_id
    type: uint64_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_ctx_prior_class
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_ctx_prior_gen
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_ctx_prior_binding
    type: uint64_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_save_ctx_replace_corrupt
    type: bool
    restore_value: no
    initial_value: 'false'
""")

# The arm switch (template, ALWAYS_OFF, turn_on_action stamps the lifetime start). (18 lines)
SWITCH_ARM_BLOCK = _blk(r"""

  # Fallback Profile arm (FB-B2): the ONE additional deliberate-intent gate of
  # every Fallback Profile operator action (SAVE, REPLACE CORRUPT, INVALIDATE).
  # Turning it ON does nothing by itself. Only a person turns it on (a dashboard
  # tap): no firmware code and no automation ever does. The firmware only turns
  # it OFF: by every execute call (accepted or refused), by every Review press
  # and again when a Review publishes a candidate, by the 120 s arm lifetime
  # (applied by the 10 s housekeeping tick) and by a reboot (ALWAYS_OFF).
  # turn_on_action only stamps the time the lifetime counts from.
  - platform: template
    name: "ECCO Fallback Profile Arm"
    id: fallback_profile_arm
    optimistic: true
    restore_mode: ALWAYS_OFF
    icon: "mdi:shield-key-outline"
    turn_on_action:
      - lambda: |-
          id(fallback_profile_arm_on_ms) = millis();
""")

# REVIEW gate: the arm is turned off after V1 / IE3. (2 lines)
REVIEW_ARM_OFF_BLOCK = _blk(r"""
          // FB-B2: a Review press past V1 turns the one-shot Fallback Profile arm off.
          id(fallback_profile_arm).turn_off();
""")

# Dispatch: the SAVE-only pre-commit poller drain item. (12 lines)
DISPATCH_DRAIN_BLOCK = _blk(r"""
      # FB-B2: SAVE only - the pre-commit poller drain (the same four-term idle predicate as the
      # entry wait). The write mutex is held by this operation throughout; a timeout is not an
      # error here: the SAVE final lambda re-checks that the bus is quiet immediately before
      # the commit and refuses otherwise.
      - if:
          condition:
            lambda: 'return id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE && !id(fallback_profile_read_failed);'
          then:
            - wait_until:
                condition:
                  lambda: 'return !id(poll_inverter_configuration_dispatch).is_running() && !id(poll_inverter_telemetry).is_running() && id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();'
                timeout: 3000ms
""")

# REVIEW_FINAL: a SAVE dispatch returns here. (2 lines)
FINAL_GUARD_BLOCK = _blk(r"""
          // FB-B2: a SAVE dispatch has its own final lambda (below); this one never runs for it.
          if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return;
""")

# REVIEW_FINAL: the SAVE_UNCONFIRMED overlay of the composed class. (2 lines)
FINAL_OVERLAY_BLOCK = _blk(r"""
            // FB-B2: after an UNKNOWN write outcome the class is SAVE_UNCONFIRMED for the rest of the boot.
            const uint8_t eff_cls = ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed));
""")

# REVIEW_FINAL: the arm is turned off before the candidate exists. (2 lines)
FINAL_ARM_OFF_BLOCK = _blk(r"""
            // FB-B2: an arm turned on while this Review was reading is cancelled before the candidate exists.
            id(fallback_profile_arm).turn_off();
""")

# Dispatch: SAVE_FINAL part 1 (verification) and part 2 (commit), two consecutive lambdas (no yield between them). (332 lines)
SAVE_FINAL_BLOCK = _blk(r"""
          // SAVE final step, part 1 of 2 (FB-B2): VERIFICATION. Consecutive lambdas of the same script, no yield
          // between them (no wait, no delay, no script call: the split only keeps each frame small). It re-checks
          // everything against the FRESH read (pass 1 == pass 2 == the reviewed candidate, the capture checks
          // again, the obligation vector again with this operation's own holds masked) and reads the save
          // context taken at the gate, never the candidate or the execute arguments. A refusal publishes its
          // text and writes nothing; success only marks the verification (the commit part follows at once).
          if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return;
          id(fallback_profile_save_verified) = false;
          ecco_fbdurable::EspNvs nvs;
          ecco_fbcap::TextBuf res{};
          bool go = true;
          // 0. integrity: an operation is in flight, its purpose is SAVE and the context was taken.
          if (!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose)) ||
              !id(fallback_profile_save_ctx_valid) || id(fallback_profile_save_ctx_id) == 0) {
            res = ecco_fbcap::internal_context_text();
            go = false;
          }
          // 1. a read step did not deliver its words.
          if (go && id(fallback_profile_read_failed)) {
            res = ecco_fbsave::save_read_fail_text(id(fallback_profile_read_fail_code), id(fallback_profile_step),
                                                   id(fallback_profile_read_exception_code));
            go = false;
          }
          // 2. pass 1 and pass 2 agree on all 31 words.
          if (go && ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {
            res = ecco_fbsave::save_changed_during_read_text(id(fallback_profile_pass1), id(fallback_profile_pass2));
            go = false;
          }
          // 3. pass 2 is exactly the reviewed candidate.
          if (go && ecco_fbcap::first_diff(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2)) >= 0) {
            res = ecco_fbsave::save_changed_since_review_text(id(fallback_profile_save_ctx_words), id(fallback_profile_pass2));
            go = false;
          }
          // 4. the capture checks again on pass 2 (defence in depth).
          if (go) {
            const ecco_fbcap::Refusals l2 = ecco_fbcap::capture_refusals(id(fallback_profile_pass2), ${ecco_inverter_tou_power_ceiling_w});
            if (l2.count > 0) {
              res = ecco_fbsave::save_l2_text(l2, id(fallback_profile_pass2));
              go = false;
            }
          }
          // 5. the obligation vector again: RAM legs first, then the lazy lease-marker probes (each
          //    flagged marker read once, never retried; a bad one is latched for the rest of the boot).
          //    The operation flag, the dispatch and the write mutex held by THIS operation are masked.
          if (go) {
            ecco_fbcap::GateInputs gi{};
            gi.boot_loaded = id(fallback_profile_boot_loaded);
            gi.fbs_slot = id(fallback_profile_fbs_slot);
            gi.probe_latch = id(fallback_profile_probe_latch);
            gi.free_power_write_enable = id(free_power_write_enable).state;
            gi.dump_write_enable = id(dump_write_enable).state;
            gi.manual_config_write_enable = id(manual_config_write_enable).state;
            gi.bus.manual_write_in_progress = id(manual_write_in_progress);
            gi.bus.correction_in_progress = id(correction_in_progress);
            gi.bus.verification_pending = id(verification_pending);
            gi.bus.verification_read_active = id(verification_read_active);
            gi.bus.free_power_operation_in_progress = id(free_power_operation_in_progress);
            gi.bus.free_power_recovery_force_in_progress = id(free_power_recovery_force_in_progress);
            gi.bus.free_power_recovery_accept_in_progress = id(free_power_recovery_accept_in_progress);
            gi.bus.reg244_apply_in_progress = id(reg244_apply_in_progress);
            gi.bus.dump_operation_in_progress = id(dump_operation_in_progress);
            gi.bus.fallback_profile_op_in_progress = id(fallback_profile_op_in_progress);
            gi.bus.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();
            gi.bus.diag_write_lock_held = id(diag_write_lock_held);
            gi.bus.diag_write_lock_since_ms = id(diag_write_lock_since_ms);
            gi.bus.now_ms = millis();
            gi.fp.free_power_marker_boot_load = id(free_power_marker_boot_load);
            gi.fp.free_power_recovery_metadata_corrupt = id(free_power_recovery_metadata_corrupt);
            gi.fp.free_power_snapshot_valid = id(free_power_snapshot_valid);
            gi.fp.free_power_marker_state = id(free_power_marker_state);
            gi.fp.free_power_operator_needed = id(free_power_operator_needed);
            gi.fp.free_power_active_persisted = id(free_power_active_persisted);
            gi.fp.free_power_restore_requested = id(free_power_restore_requested);
            gi.fp.run_start = id(start_free_power_override).is_running();
            gi.fp.run_restore = id(restore_free_power_snapshot).is_running() ||
                                id(restore_free_power_snapshot_dispatch).is_running();
            gi.fp.run_operator = id(free_power_recovery_review).is_running() ||
                                 id(free_power_recovery_review_dispatch).is_running() ||
                                 id(free_power_recovery_force_restore).is_running() ||
                                 id(free_power_recovery_force_restore_dispatch).is_running() ||
                                 id(free_power_recovery_accept_current_state).is_running() ||
                                 id(free_power_recovery_accept_current_state_dispatch).is_running();
            gi.dump.dump_marker_boot_load = id(dump_marker_boot_load);
            gi.dump.dump_recovery_metadata_corrupt = id(dump_recovery_metadata_corrupt);
            gi.dump.dump_containment_state = id(dump_containment_state);
            gi.dump.dump_snapshot_valid = id(dump_snapshot_valid);
            gi.dump.dump_marker_state = id(dump_marker_state);
            gi.dump.dump_operator_needed = id(dump_operator_needed);
            gi.dump.dump_active_persisted = id(dump_active_persisted);
            gi.dump.dump_restore_requested = id(dump_restore_requested);
            gi.dump.run_start = id(start_dump_to_grid_override).is_running();
            gi.dump.run_restore = id(restore_dump_to_grid_snapshot).is_running();
            gi.r244.reg244_marker_boot_load = id(reg244_marker_boot_load);
            gi.r244.reg244_recovery_metadata_corrupt = id(reg244_recovery_metadata_corrupt);
            gi.r244.reg244_snapshot_valid = id(reg244_snapshot_valid);
            gi.r244.reg244_marker_state = id(reg244_marker_state);
            gi.r244.run_apply = id(apply_reg244_settings).is_running();
            gi.r244.run_restore = id(restore_reg244_snapshot).is_running();
            ecco_fbcap::ProbeResults pr{};
            {
              // First decision: which lease markers (if any) still need their one probe.
              const ecco_fbsave::FinalGate f0 = ecco_fbsave::final_gate_decide(gi, pr);
              if (f0.gr.code == ecco_fbcap::GATE_NEED_PROBE) {
                if (f0.gr.probe_fp) {
                  ecco_durable::ValidMarker m{};
                  ecco_fbdurable::ReadDiag d{};
                  const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), m, d);
                  pr.fp = ecco_fbcap::probe_result(ld, m.magic, m.state);
                }
                if (f0.gr.probe_dump) {
                  ecco_durable::ValidMarker m{};
                  ecco_fbdurable::ReadDiag d{};
                  const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), m, d);
                  pr.dump = ecco_fbcap::probe_result(ld, m.magic, m.state);
                }
                if (f0.gr.probe_r244) {
                  ecco_durable::ValidMarker m{};
                  ecco_fbdurable::ReadDiag d{};
                  const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), m, d);
                  pr.r244 = ecco_fbcap::probe_result(ld, m.magic, m.state);
                }
              }
            }
            // The verdict (identical to the first decision when nothing needed a probe).
            const ecco_fbsave::FinalGate fg = ecco_fbsave::final_gate_decide(gi, pr);
            id(fallback_profile_probe_latch) = fg.gr.latch;
            id(fallback_profile_obl_text) = fg.gr.obl.c_str();
            if (fg.gr.code != ecco_fbcap::GATE_ACCEPT) {
              res = fg.text;
              go = false;
            }
          }
          if (go) {
            id(fallback_profile_save_verified) = true;
          } else {
            // Refused: leave the SAVING state, show the idle review form and the one result text.
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,
                                                          id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
              if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
            }
            if (id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());
          }
      - lambda: |-
          // SAVE final step, part 2 of 2 (FB-B2): COMMIT. Runs only after part 1 verified (no yield between the
          // two). The trusted clock is sampled here (never 0), then: fresh stored pair -> mirror -> intended pair
          // built from the pass-2 words ONLY -> bus quiet as the LAST check -> the ONE writer call (witness first,
          // then profile, no retry) -> everything published from that one outcome. Every refusal writes nothing.
          // The release lambda that follows runs on every path.
          if (!id(fallback_profile_save_verified)) return;
          id(fallback_profile_save_verified) = false;
          ecco_fbdurable::EspNvs nvs;
          ecco_fbcap::TextBuf res{};
          bool go = true;
          uint32_t epoch = 0;
          if (!ecco_fbsave::save_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose)) ||
              !id(fallback_profile_save_ctx_valid)) {
            res = ecco_fbcap::internal_context_text();
            go = false;
          }
          // 6. the clock is still trusted: this is where the capture time is sampled (never 0).
          if (go) {
            const bool time_ok = id(ntp_synced) && id(ntp_time).now().is_valid();
            epoch = time_ok ? (uint32_t) id(ntp_time).now().timestamp : 0u;
            if (!ecco_fbsave::clock_trusted_for_save(time_ok, epoch)) {
              res = ecco_fbsave::save_time_text();
              go = false;
            }
          }
          // 7..18. fresh stored pair -> mirror -> intended pair -> bus quiet -> the ONE writer call -> outcome.
          if (go) {
            ecco_fallback::FallbackProfileV1 p{};
            ecco_fbdurable::FailbackProvisionV1 w{};
            ecco_fbdurable::ReadDiag dp{};
            ecco_fbdurable::ReadDiag dw{};
            const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);
            const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);
            const bool healthy = ecco_fbdurable::nvs_healthy();
            // The intended pair: the fresh prior must be the one the candidate was reviewed against, the class
            // must permit a save, the generation is max(authentic prior, valid witness, high-water) + 1.
            ecco_fbsave::SavePlanInputs pi{};
            {
              ecco_fbcap::ReadInputs in{};
              in.p_load = lp;
              in.p = p;
              in.w_load = lw;
              in.w = w;
              in.healthy = healthy;
              in.present_seen = id(fallback_profile_present_seen);
              in.read_anomaly = id(fallback_profile_read_anomaly);
              in.seen_hw_gen = id(fallback_profile_seen_hw_gen);
              in.baseline_valid = id(fallback_profile_boot_loaded);
              in.last_p_load = id(fallback_profile_load);
              in.last_p_bytes = id(fallback_profile_bytes);
              in.last_w_load = id(fallback_witness_load);
              in.last_w_bytes = id(fallback_witness_bytes);
              const ecco_fbcap::ReadEval e = ecco_fbcap::evaluate_read(in);
              // Latest authoritative read wins: mirror first, publishes after (even if the SAVE is then refused).
              id(fallback_profile_present_seen) = e.latch.present_seen;
              id(fallback_profile_read_anomaly) = e.latch.read_anomaly;
              id(fallback_profile_seen_hw_gen) = e.seen_hw_gen;
              id(fallback_profile_class) = e.cls;
              id(fallback_profile_why) = e.why;
              id(fallback_profile_load) = lp;
              id(fallback_witness_load) = lw;
              id(fallback_profile_bytes) = ecco_fallback::encode_profile(p);
              id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(w);
              {
                const char *cls_name = ecco_fbcap::epc_name(ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed)));
                if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
              }
              {
                ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));
                if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());
              }
              {
                ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(lp, p, e.cls);
                if (id(fallback_profile_slots_text).state != t.c_str()) id(fallback_profile_slots_text).publish_state(t.c_str());
              }
              {
                ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(lp, p, e.cls);
                if (id(fallback_profile_context_text).state != t.c_str()) id(fallback_profile_context_text).publish_state(t.c_str());
              }
              pi.cls = e.cls;
              pi.why = e.why;
              pi.read_anomaly = e.latch.read_anomaly;
              pi.seen_hw_gen = e.seen_hw_gen;
            }
            pi.p_load = lp;
            pi.p = p;
            pi.p_stored_len = dp.stored_len;
            pi.w_load = lw;
            pi.w = w;
            pi.w_stored_len = dw.stored_len;
            pi.unconfirmed = id(fallback_profile_save_unconfirmed);
            pi.cand_prior_class = id(fallback_profile_save_ctx_prior_class);
            pi.cand_prior_gen = id(fallback_profile_save_ctx_prior_gen);
            pi.cand_prior_binding = id(fallback_profile_save_ctx_prior_binding);
            pi.replace_corrupt = id(fallback_profile_save_ctx_replace_corrupt);
            pi.words = id(fallback_profile_pass2);
            pi.captured_epoch = epoch;
            const ecco_fbsave::Plan plan = ecco_fbsave::plan_save(pi);
            if (plan.code != ecco_fbsave::PLAN_OK) {
              res = plan.text;
              go = false;
            } else {
              if (plan.op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT) {
                // The discarded CORRUPT record is logged BEFORE it is replaced.
                const ecco_fbcap::TextBuf rc0 = ecco_fbsave::replace_corrupt_log_text(lp, p, dp.stored_len, 0);
                const ecco_fbcap::TextBuf rc1 = ecco_fbsave::replace_corrupt_log_text(lp, p, dp.stored_len, 1);
                if (rc0.size() > 0) ESP_LOGW("fbdurable", "%s", rc0.c_str());
                if (rc1.size() > 0) ESP_LOGW("fbdurable", "%s", rc1.c_str());
              }
              ecco_fbdurable::TxnResult r{};
              // FB-B2 hardening: the heartbeat is positively re-checked here, in the same synchronous lambda and
              // immediately before the commit (no yield between this test and the writer). Not stable or not known:
              // nothing is written, no UNKNOWN latch, no retry.
              if (!((id(supervision_state) == 1) && id(supervision_stable))) {
                res = ecco_fbsave::save_hb_text();
                go = false;
              } else if (!ecco_fbsave::commit_bus_quiet(id(fallback_profile_op_in_progress), id(manual_write_in_progress),
                                                        id(correction_in_progress), id(inverter_modbus)->tx_buffer_empty(),
                                                        id(inverter_modbus)->tx_blocked())) {
                res = ecco_fbsave::save_bus_quiet_text();
                go = false;
              } else {
                const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(
                    nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p,
                    ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);
                // Everything below comes from this one outcome, so the texts and the mirror never skew.
                id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);
                id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);
                if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {
                  id(fallback_profile_save_unconfirmed) = true;
                  id(fallback_profile_save_unconfirmed_op) = plan.op;
                  id(fallback_profile_save_unconfirmed_gen) = plan.generation;
                }
                const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);
                id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);
                id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);
                id(fallback_profile_load) = m.p_load;
                id(fallback_witness_load) = m.w_load;
                {
                  ecco_fbdurable::ReadLatch lat{id(fallback_profile_present_seen), id(fallback_profile_read_anomaly)};
                  if (r.w.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);
                  if (r.p.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_PROFILE);
                  id(fallback_profile_present_seen) = lat.present_seen;
                }
                const ecco_fbdurable::EffectiveProfile e2 =
                    ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly));
                id(fallback_profile_class) = e2.cls;
                id(fallback_profile_why) = e2.why;
                id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(
                    id(fallback_profile_seen_hw_gen), ecco_fallback::classify_profile(m.p_load, m.p), m.p.generation,
                    ecco_fbdurable::classify_witness(m.w_load, m.w), m.w.hw_generation);
                {
                  const char *cls_name = ecco_fbcap::epc_name(ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));
                  if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
                }
                {
                  ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(m.p_load, m.p, m.w_load, m.w, e2.why, id(fallback_durable_last_err), id(fallback_durable_last_us));
                  if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());
                }
                {
                  ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(m.p_load, m.p, e2.cls);
                  if (id(fallback_profile_slots_text).state != t.c_str()) id(fallback_profile_slots_text).publish_state(t.c_str());
                }
                {
                  ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(m.p_load, m.p, e2.cls);
                  if (id(fallback_profile_context_text).state != t.c_str()) id(fallback_profile_context_text).publish_state(t.c_str());
                }
                {
                  ecco_fbcap::TextBuf t = ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation);
                  if (id(fallback_profile_last_result_text).state != t.c_str()) id(fallback_profile_last_result_text).publish_state(t.c_str());
                }
                {
                  const ecco_fbcap::TextBuf lg = ecco_fbsave::txn_log_text(plan.op, o, r, plan.generation);
                  if (o == ecco_fbdurable::TXN_COMMITTED) {
                    ESP_LOGI("fbdurable", "%s", lg.c_str());
                  } else {
                    ESP_LOGW("fbdurable", "%s", lg.c_str());
                  }
                }
              }
            }
          }
          // Leave the SAVING state: the idle review form (the candidate was consumed at the gate and no Review
          // can run while this operation holds the flags), then the refusal text (a finished commit has already
          // published its own outcome text above).
          id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,
                                                        id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
            if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
          }
          if (res.size() > 0 && id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());
      - lambda: |-
""")

# RELEASE lambda: the SAVE context and the verification hand-over are cleared. (9 lines)
RELEASE_CTX_BLOCK = _blk(r"""
          // FB-B2: the save context taken at the SAVE gate never outlives the operation.
          id(fallback_profile_save_ctx_valid) = false;
          id(fallback_profile_save_verified) = false;
          id(fallback_profile_save_ctx_words) = std::array<uint16_t, 31>{};
          id(fallback_profile_save_ctx_id) = 0;
          id(fallback_profile_save_ctx_prior_class) = 0;
          id(fallback_profile_save_ctx_prior_gen) = 0;
          id(fallback_profile_save_ctx_prior_binding) = 0;
          id(fallback_profile_save_ctx_replace_corrupt) = false;
""")

# The two scripts: fallback_profile_save (gate; dispatches the existing capture dispatch) and fallback_profile_invalidate. (393 lines)
SCRIPTS_BLOCK = _blk(r"""

  # =====================================================================
  # Fallback Profile SAVE / INVALIDATE (FB-B2) - the operator write flow.
  # (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md sections 3.8,
  # 4.7, 4.8; design/S1_fbb_capture_final.md section 8.) Two scripts, both
  # started only by the fallback_profile_execute api action:
  #   fallback_profile_save         synchronous gate G1..G16; on accept it takes
  #                                 the lock flags in that same lambda, copies the
  #                                 reviewed candidate, and starts the EXISTING
  #                                 fallback_profile_capture_dispatch (the same
  #                                 four read nodes: no new Modbus operation); the
  #                                 dispatch's SAVE final lambda re-checks and
  #                                 commits
  #   fallback_profile_invalidate   ONE synchronous lambda: gate, fresh read and
  #                                 commit; it never waits and never takes the
  #                                 operation flag or the write mutex
  # The only durable writes of this Fallback Profile flow are the two calls of
  # the FB-B0 transaction writer (one in the SAVE final lambda, one in the
  # INVALIDATE lambda); witness first, then profile, no retry. NOTHING here
  # writes the inverter. Every operator-visible text comes from the
  # ecco_fbsave / ecco_fbcap builders.
  # =====================================================================
  # SAVE gate. One synchronous lambda: G1 in flight (arm off, nothing else), the
  # one-shot preamble (arm off, candidate copy, candidate consumed), then G0..G16
  # in one header call. Accept: copy the candidate into the save context, take the
  # lock flags, start the dispatch (the `if:` below).
  - id: fallback_profile_save
    mode: single
    then:
      - lambda: |-
          // G1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.
          {
            const ecco_fbsave::SaveGateResult g1 = ecco_fbsave::save_in_flight_gate(
                id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());
            if (g1.code != ecco_fbsave::SG_UNSET) {
              id(fallback_profile_arm).turn_off();
              if (id(fallback_profile_last_result_text).state != g1.text.c_str()) id(fallback_profile_last_result_text).publish_state(g1.text.c_str());
              return;
            }
          }
          // One-shot preamble (every call that passed G1): read the arm, turn it off, take a local copy of
          // the candidate, then consume the candidate (IE2; its own outcome is not published).
          const bool armed = id(fallback_profile_arm).state;
          id(fallback_profile_arm).turn_off();
          const bool c_valid = id(fallback_profile_cand_valid);
          const bool c_saveable = id(fallback_profile_cand_saveable);
          const uint64_t c_id = id(fallback_profile_cand_id);
          const uint32_t c_ms = id(fallback_profile_cand_ms);
          const uint8_t c_prior_class = id(fallback_profile_cand_prior_class);
          const uint32_t c_prior_gen = id(fallback_profile_cand_prior_gen);
          const uint64_t c_prior_binding = id(fallback_profile_cand_prior_binding);
          const uint32_t c_writes_fp = id(fallback_profile_cand_writes_fp);
          const std::array<uint16_t, 31> c_words = id(fallback_profile_cand_words);
          if (c_valid) {
            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;
            id(fallback_profile_invalidate_candidate).execute();
          }
          // Gather the RAM inputs of G0..G16 (no storage access here).
          ecco_fbsave::SaveGateInputs si{};
          si.arm_was_on = armed;
          si.cand_valid = c_valid;
          si.cand_saveable = c_saveable;
          si.cand_id = c_id;
          si.cand_ms = c_ms;
          si.cand_prior_class = c_prior_class;
          si.cand_writes_fp = c_writes_fp;
          si.now_ms = millis();
          si.writes_fp_now = ecco_fbcap::writes_fingerprint(
              (uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts),
              (uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts),
              (uint32_t) id(dump_start_attempts));
          si.boot_loaded = id(fallback_profile_boot_loaded);
          si.unconfirmed = id(fallback_profile_save_unconfirmed);
          si.read_anomaly = id(fallback_profile_read_anomaly);
          si.hb_ok = id(fallback_profile_exec_hb_ok);
          si.time_trusted = id(ntp_synced) && id(ntp_time).now().is_valid();
          ecco_fbcap::GateInputs gi{};
          gi.boot_loaded = id(fallback_profile_boot_loaded);
          gi.fbs_slot = id(fallback_profile_fbs_slot);
          gi.probe_latch = id(fallback_profile_probe_latch);
          gi.free_power_write_enable = id(free_power_write_enable).state;
          gi.dump_write_enable = id(dump_write_enable).state;
          gi.manual_config_write_enable = id(manual_config_write_enable).state;
          gi.bus.manual_write_in_progress = id(manual_write_in_progress);
          gi.bus.correction_in_progress = id(correction_in_progress);
          gi.bus.verification_pending = id(verification_pending);
          gi.bus.verification_read_active = id(verification_read_active);
          gi.bus.free_power_operation_in_progress = id(free_power_operation_in_progress);
          gi.bus.free_power_recovery_force_in_progress = id(free_power_recovery_force_in_progress);
          gi.bus.free_power_recovery_accept_in_progress = id(free_power_recovery_accept_in_progress);
          gi.bus.reg244_apply_in_progress = id(reg244_apply_in_progress);
          gi.bus.dump_operation_in_progress = id(dump_operation_in_progress);
          gi.bus.fallback_profile_op_in_progress = id(fallback_profile_op_in_progress);
          gi.bus.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();
          gi.bus.diag_write_lock_held = id(diag_write_lock_held);
          gi.bus.diag_write_lock_since_ms = id(diag_write_lock_since_ms);
          gi.bus.now_ms = millis();
          gi.fp.free_power_marker_boot_load = id(free_power_marker_boot_load);
          gi.fp.free_power_recovery_metadata_corrupt = id(free_power_recovery_metadata_corrupt);
          gi.fp.free_power_snapshot_valid = id(free_power_snapshot_valid);
          gi.fp.free_power_marker_state = id(free_power_marker_state);
          gi.fp.free_power_operator_needed = id(free_power_operator_needed);
          gi.fp.free_power_active_persisted = id(free_power_active_persisted);
          gi.fp.free_power_restore_requested = id(free_power_restore_requested);
          gi.fp.run_start = id(start_free_power_override).is_running();
          gi.fp.run_restore = id(restore_free_power_snapshot).is_running() ||
                              id(restore_free_power_snapshot_dispatch).is_running();
          gi.fp.run_operator = id(free_power_recovery_review).is_running() ||
                               id(free_power_recovery_review_dispatch).is_running() ||
                               id(free_power_recovery_force_restore).is_running() ||
                               id(free_power_recovery_force_restore_dispatch).is_running() ||
                               id(free_power_recovery_accept_current_state).is_running() ||
                               id(free_power_recovery_accept_current_state_dispatch).is_running();
          gi.dump.dump_marker_boot_load = id(dump_marker_boot_load);
          gi.dump.dump_recovery_metadata_corrupt = id(dump_recovery_metadata_corrupt);
          gi.dump.dump_containment_state = id(dump_containment_state);
          gi.dump.dump_snapshot_valid = id(dump_snapshot_valid);
          gi.dump.dump_marker_state = id(dump_marker_state);
          gi.dump.dump_operator_needed = id(dump_operator_needed);
          gi.dump.dump_active_persisted = id(dump_active_persisted);
          gi.dump.dump_restore_requested = id(dump_restore_requested);
          gi.dump.run_start = id(start_dump_to_grid_override).is_running();
          gi.dump.run_restore = id(restore_dump_to_grid_snapshot).is_running();
          gi.r244.reg244_marker_boot_load = id(reg244_marker_boot_load);
          gi.r244.reg244_recovery_metadata_corrupt = id(reg244_recovery_metadata_corrupt);
          gi.r244.reg244_snapshot_valid = id(reg244_snapshot_valid);
          gi.r244.reg244_marker_state = id(reg244_marker_state);
          gi.r244.run_apply = id(apply_reg244_settings).is_running();
          gi.r244.run_restore = id(restore_reg244_snapshot).is_running();
          // G0..G16, first failure wins. The gate reads no storage: the lease markers are probed once more,
          // lazily, by the SAVE final lambda.
          const ecco_fbsave::SaveGateResult sr = ecco_fbsave::save_gate_decide(
              si, id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size(),
              id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size(),
              id(fallback_profile_exec_confirmation).c_str(), id(fallback_profile_exec_confirmation).size(), gi);
          if (sr.obl.size() > 0) id(fallback_profile_obl_text) = sr.obl.c_str();
          if (sr.code == ecco_fbsave::SG_ACCEPT) {
            // Accept: the save context and the lock flags are taken in THIS lambda, before the dispatch is started.
            id(fallback_profile_save_ctx_words) = c_words;
            id(fallback_profile_save_ctx_id) = c_id;
            id(fallback_profile_save_ctx_prior_class) = c_prior_class;
            id(fallback_profile_save_ctx_prior_gen) = c_prior_gen;
            id(fallback_profile_save_ctx_prior_binding) = c_prior_binding;
            id(fallback_profile_save_ctx_replace_corrupt) = sr.replace_corrupt;
            id(fallback_profile_save_ctx_valid) = true;
            id(fallback_profile_op_in_progress) = true;
            id(manual_write_in_progress) = true;
            id(fallback_profile_op_purpose) = ecco_fbsave::PURPOSE_SAVE;
            id(fallback_profile_op_started_ms) = millis();
            id(fallback_profile_step) = 0;
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_SAVING;
            id(fallback_profile_gate_accepted) = true;
          } else {
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), false, 0, 0, 0,
                                                        id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
            if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbsave::save_in_progress_text();
            if (sr.code != ecco_fbsave::SG_ACCEPT) t = sr.text;
            if (id(fallback_profile_last_result_text).state != t.c_str()) id(fallback_profile_last_result_text).publish_state(t.c_str());
          }
      - if:
          condition:
            lambda: 'return id(fallback_profile_gate_accepted);'
          then:
            - lambda: |-
                id(fallback_profile_gate_accepted) = false;
            - script.execute:
                id: fallback_profile_capture_dispatch

  # INVALIDATE: ONE synchronous lambda - gate, fresh read, commit. No dispatch, no
  # idle wait, no pre-commit wait, no Modbus read; it never takes the operation
  # flag or the shared write mutex (it REFUSES when the bus is busy, and nothing
  # can interleave between the last bus check and the commit because the lambda
  # runs to completion inside one main-loop iteration). Legal during an active
  # lease: it is the safe direction. Needs the arm, the exact phrase and the
  # 16-hex binding of the stored VALID profile; needs no candidate, no heartbeat,
  # no clock, no clear obligations.
  - id: fallback_profile_invalidate
    mode: single
    then:
      - lambda: |-
          // I1: another Fallback Profile operation is in flight - touch nothing but the arm and the result text.
          {
            const ecco_fbsave::InvalidateGateResult i1 = ecco_fbsave::invalidate_in_flight_gate(
                id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running());
            if (i1.code != ecco_fbsave::IG_UNSET) {
              id(fallback_profile_arm).turn_off();
              if (id(fallback_profile_last_result_text).state != i1.text.c_str()) id(fallback_profile_last_result_text).publish_state(i1.text.c_str());
              return;
            }
          }
          // One-shot preamble (every call that passed I1): read the arm, turn it off, consume any
          // candidate (IE2; its own outcome is not published).
          const bool armed = id(fallback_profile_arm).state;
          id(fallback_profile_arm).turn_off();
          if (id(fallback_profile_cand_valid)) {
            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;
            id(fallback_profile_invalidate_candidate).execute();
          }
          // I2..I12 over the RAM mirror (cheap first: a refusal never costs a storage read).
          {
            ecco_fbsave::InvalidateGateInputs ii{};
            ii.arm_was_on = armed;
            ii.boot_loaded = id(fallback_profile_boot_loaded);
            ii.read_anomaly = id(fallback_profile_read_anomaly);
            ii.unconfirmed = id(fallback_profile_save_unconfirmed);
            ii.cls = id(fallback_profile_class);
            ii.p_load = id(fallback_profile_load);
            ii.p = ecco_fallback::decode_profile(id(fallback_profile_bytes));
            ii.w_load = id(fallback_witness_load);
            ii.w = ecco_fbdurable::decode_provision(id(fallback_witness_bytes));
            ii.seen_hw_gen = id(fallback_profile_seen_hw_gen);
            ii.bus.manual_write_in_progress = id(manual_write_in_progress);
            ii.bus.correction_in_progress = id(correction_in_progress);
            ii.bus.verification_pending = id(verification_pending);
            ii.bus.verification_read_active = id(verification_read_active);
            ii.bus.free_power_operation_in_progress = id(free_power_operation_in_progress);
            ii.bus.free_power_recovery_force_in_progress = id(free_power_recovery_force_in_progress);
            ii.bus.free_power_recovery_accept_in_progress = id(free_power_recovery_accept_in_progress);
            ii.bus.reg244_apply_in_progress = id(reg244_apply_in_progress);
            ii.bus.dump_operation_in_progress = id(dump_operation_in_progress);
            ii.bus.fallback_profile_op_in_progress = id(fallback_profile_op_in_progress);
            ii.bus.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();
            ii.bus.diag_write_lock_held = id(diag_write_lock_held);
            ii.bus.diag_write_lock_since_ms = id(diag_write_lock_since_ms);
            ii.bus.now_ms = millis();
            ii.tx_buffer_empty = id(inverter_modbus)->tx_buffer_empty();
            ii.tx_blocked = id(inverter_modbus)->tx_blocked();
            ii.fbs_slot = id(fallback_profile_fbs_slot);
            const ecco_fbsave::InvalidateGateResult ir = ecco_fbsave::invalidate_gate_decide(
                ii, id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size(),
                id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size(),
                id(fallback_profile_exec_confirmation).c_str(), id(fallback_profile_exec_confirmation).size());
            if (ir.code != ecco_fbsave::IG_ACCEPT) {
              if (id(fallback_profile_last_result_text).state != ir.text.c_str()) id(fallback_profile_last_result_text).publish_state(ir.text.c_str());
              return;
            }
          }
          // Fresh FBP + FBW read: two direct reads, ONE health check, then the latch notes, the same-boot
          // divergence rule against the RAM mirror and the RE-composed class (the latest authoritative read
          // wins: mirror first, publishes after, even if the INVALIDATE is then refused).
          ecco_fbdurable::EspNvs nvs;
          ecco_fallback::FallbackProfileV1 p{};
          ecco_fbdurable::FailbackProvisionV1 w{};
          ecco_fbdurable::ReadDiag dp{};
          ecco_fbdurable::ReadDiag dw{};
          const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);
          const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);
          const bool healthy = ecco_fbdurable::nvs_healthy();
          // The intended pair: the stored profile must be effectively VALID and the one the operator named.
          ecco_fbsave::InvalidatePlanInputs pj{};
          {
            ecco_fbcap::ReadInputs in{};
            in.p_load = lp;
            in.p = p;
            in.w_load = lw;
            in.w = w;
            in.healthy = healthy;
            in.present_seen = id(fallback_profile_present_seen);
            in.read_anomaly = id(fallback_profile_read_anomaly);
            in.seen_hw_gen = id(fallback_profile_seen_hw_gen);
            in.baseline_valid = id(fallback_profile_boot_loaded);
            in.last_p_load = id(fallback_profile_load);
            in.last_p_bytes = id(fallback_profile_bytes);
            in.last_w_load = id(fallback_witness_load);
            in.last_w_bytes = id(fallback_witness_bytes);
            const ecco_fbcap::ReadEval e = ecco_fbcap::evaluate_read(in);
            id(fallback_profile_present_seen) = e.latch.present_seen;
            id(fallback_profile_read_anomaly) = e.latch.read_anomaly;
            id(fallback_profile_seen_hw_gen) = e.seen_hw_gen;
            id(fallback_profile_class) = e.cls;
            id(fallback_profile_why) = e.why;
            id(fallback_profile_load) = lp;
            id(fallback_witness_load) = lw;
            id(fallback_profile_bytes) = ecco_fallback::encode_profile(p);
            id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(w);
            {
              const char *cls_name = ecco_fbcap::epc_name(ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed)));
              if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));
              if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(lp, p, e.cls);
              if (id(fallback_profile_slots_text).state != t.c_str()) id(fallback_profile_slots_text).publish_state(t.c_str());
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(lp, p, e.cls);
              if (id(fallback_profile_context_text).state != t.c_str()) id(fallback_profile_context_text).publish_state(t.c_str());
            }
            pj.cls = e.cls;
            pj.read_anomaly = e.latch.read_anomaly;
            pj.seen_hw_gen = e.seen_hw_gen;
          }
          pj.p_load = lp;
          pj.p = p;
          pj.p_stored_len = dp.stored_len;
          pj.w_load = lw;
          pj.w = w;
          pj.w_stored_len = dw.stored_len;
          pj.unconfirmed = id(fallback_profile_save_unconfirmed);
          pj.target_id = ecco_fbsave::parse_hex16(id(fallback_profile_exec_target_id).c_str(), id(fallback_profile_exec_target_id).size());
          const ecco_fbsave::Plan plan = ecco_fbsave::plan_invalidate(pj);
          if (plan.code != ecco_fbsave::PLAN_OK) {
            if (id(fallback_profile_last_result_text).state != plan.text.c_str()) id(fallback_profile_last_result_text).publish_state(plan.text.c_str());
            return;
          }
          // Bus quiet: refreshed flags, the LAST statement before the writer call.
          ecco_fbcap::BusInputs bn{};
          bn.manual_write_in_progress = id(manual_write_in_progress);
          bn.correction_in_progress = id(correction_in_progress);
          bn.verification_pending = id(verification_pending);
          bn.verification_read_active = id(verification_read_active);
          bn.free_power_operation_in_progress = id(free_power_operation_in_progress);
          bn.free_power_recovery_force_in_progress = id(free_power_recovery_force_in_progress);
          bn.free_power_recovery_accept_in_progress = id(free_power_recovery_accept_in_progress);
          bn.reg244_apply_in_progress = id(reg244_apply_in_progress);
          bn.dump_operation_in_progress = id(dump_operation_in_progress);
          bn.fallback_profile_op_in_progress = id(fallback_profile_op_in_progress);
          bn.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();
          bn.diag_write_lock_held = id(diag_write_lock_held);
          bn.diag_write_lock_since_ms = id(diag_write_lock_since_ms);
          bn.now_ms = millis();
          ecco_fbdurable::TxnResult r{};
          if (!ecco_fbsave::invalidate_bus_idle(bn, id(inverter_modbus)->tx_buffer_empty(), id(inverter_modbus)->tx_blocked())) {
            ecco_fbcap::TextBuf busy = ecco_fbsave::invalidate_busy_text();
            if (id(fallback_profile_last_result_text).state != busy.c_str()) id(fallback_profile_last_result_text).publish_state(busy.c_str());
            return;
          }
          const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(
              nvs, plan.w_new, w, ecco_fbdurable::PriorDesc{lw, dw.stored_len}, plan.p_new, p,
              ecco_fbdurable::PriorDesc{lp, dp.stored_len}, r);
          // Everything below comes from this one outcome, so the texts and the mirror never skew.
          id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);
          id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);
          if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {
            id(fallback_profile_save_unconfirmed) = true;
            id(fallback_profile_save_unconfirmed_op) = plan.op;
            id(fallback_profile_save_unconfirmed_gen) = plan.generation;
          }
          const ecco_fbdurable::MirrorRecords m = ecco_fbdurable::mirror_after(o, r, p, lp, w, lw);
          id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);
          id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);
          id(fallback_profile_load) = m.p_load;
          id(fallback_witness_load) = m.w_load;
          {
            ecco_fbdurable::ReadLatch lat{id(fallback_profile_present_seen), id(fallback_profile_read_anomaly)};
            if (r.w.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_WITNESS);
            if (r.p.outcome == ecco_fbdurable::KEY_COMMITTED) lat = ecco_fbdurable::note_committed(lat, ecco_fbdurable::KEY_BIT_PROFILE);
            id(fallback_profile_present_seen) = lat.present_seen;
          }
          const ecco_fbdurable::EffectiveProfile e2 =
              ecco_fbdurable::compose_profile_class(m.p_load, m.p, m.w_load, m.w, id(fallback_profile_read_anomaly));
          id(fallback_profile_class) = e2.cls;
          id(fallback_profile_why) = e2.why;
          id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(
              id(fallback_profile_seen_hw_gen), ecco_fallback::classify_profile(m.p_load, m.p), m.p.generation,
              ecco_fbdurable::classify_witness(m.w_load, m.w), m.w.hw_generation);
          {
            const char *cls_name = ecco_fbcap::epc_name(ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));
            if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(m.p_load, m.p, m.w_load, m.w, e2.why, id(fallback_durable_last_err), id(fallback_durable_last_us));
            if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(m.p_load, m.p, e2.cls);
            if (id(fallback_profile_slots_text).state != t.c_str()) id(fallback_profile_slots_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(m.p_load, m.p, e2.cls);
            if (id(fallback_profile_context_text).state != t.c_str()) id(fallback_profile_context_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, p.generation);
            if (id(fallback_profile_last_result_text).state != t.c_str()) id(fallback_profile_last_result_text).publish_state(t.c_str());
          }
          {
            const ecco_fbcap::TextBuf lg = ecco_fbsave::txn_log_text(plan.op, o, r, plan.generation);
            if (o == ecco_fbdurable::TXN_COMMITTED) {
              ESP_LOGI("fbdurable", "%s", lg.c_str());
            } else {
              ESP_LOGW("fbdurable", "%s", lg.c_str());
            }
          }
""")

# Housekeeping breaker: the SAVE context is cleared with the operation flags (the write mutex is never assigned). (9 lines)
BREAKER_CTX_BLOCK = _blk(r"""
            // FB-B2: the save context taken at the SAVE gate is cleared here too (the write mutex is not touched).
            id(fallback_profile_save_ctx_valid) = false;
            id(fallback_profile_save_verified) = false;
            id(fallback_profile_save_ctx_words) = std::array<uint16_t, 31>{};
            id(fallback_profile_save_ctx_id) = 0;
            id(fallback_profile_save_ctx_prior_class) = 0;
            id(fallback_profile_save_ctx_prior_gen) = 0;
            id(fallback_profile_save_ctx_prior_binding) = 0;
            id(fallback_profile_save_ctx_replace_corrupt) = false;
""")

# Housekeeping lambda 2: the arm lifetime (120 s) and IE8, appended to the same 10 s interval. (14 lines)
TICK2_BLOCK = _blk(r"""
          }
      - lambda: |-
          // FB-B2, same RAM-only tick: (1) the arm lifetime - the Fallback Profile arm is turned OFF once it
          // has been on for ARM_TTL_MS (the tick granularity makes that up to about 130 s; the candidate
          // lifetime and the one-shot consumption by every execute call are exact and independent);
          // (2) IE8 - an unknown write outcome or a read anomaly this boot clears any candidate (silently:
          // the Review's own not-saveable text stays in the result).
          if (id(fallback_profile_arm).state && ecco_fbsave::arm_expired(millis(), id(fallback_profile_arm_on_ms))) {
            id(fallback_profile_arm).turn_off();
          }
          if (id(fallback_profile_cand_valid) && !id(fallback_profile_op_in_progress) &&
              (id(fallback_profile_save_unconfirmed) || id(fallback_profile_read_anomaly) != 0)) {
            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;
            id(fallback_profile_invalidate_candidate).execute();
""")

# ---------------------------------------------------------------------------
# The seven one-line replacements (the ONLY pre-existing firmware lines FB-B2 modifies): name -> (FB-B1 line, FB-B2 line).
# ---------------------------------------------------------------------------
REPLACEMENTS = {
    'boot_b2': (
        '            ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);\n',
        '            ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));\n',
    ),
    'final_state_name': (
        '              const char *cls_name = ecco_fbcap::epc_name(e.cls);\n',
        '              const char *cls_name = ecco_fbcap::epc_name(eff_cls);\n',
    ),
    'final_b2': (
        '              ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);\n',
        '              ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));\n',
    ),
    'final_ri_cls': (
        '            ri.cls = e.cls;\n',
        '            ri.cls = eff_cls;\n',
    ),
    'final_prior_class': (
        '            id(fallback_profile_cand_prior_class) = e.cls;\n',
        '            id(fallback_profile_cand_prior_class) = eff_cls;\n',
    ),
    'final_b3': (
        '              ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, e.cls,\n',
        '              ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, eff_cls,\n',
    ),
    'final_not_saveable': (
        '              res = ecco_fbcap::not_saveable_text(v.refusals, id(fallback_profile_pass2), e.cls, e.latch.read_anomaly);\n',
        '              res = ecco_fbcap::not_saveable_text(v.refusals, id(fallback_profile_pass2), eff_cls, e.latch.read_anomaly);\n',
    ),
}

# Context anchors (left, right) of every hunk: unchanged lines only. left + old + right must occur exactly once in the FB-B1 text,
# left + new + right exactly once in the FB-B2 text (test_fallback_save_scope.py pins both).
ANCHORS = {
    'include': (
        '    - include/ecco_fallback_durable.h\n    - include/ecco_fallback_capture.h\n',
        '\n  on_boot:\n',
    ),
    'boot_b2': (
        '          }\n          {\n',
        '            if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());\n          }\n',
    ),
    'api_action': (
        '              ESP_LOGI("supervision", "Supervision state -> SUPERVISED (valid heartbeat)");\n            }\n',
        '\nota:\n',
    ),
    'globals': (
        "  - id: fallback_profile_cand_has_stored\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n",
        '\nnumber:\n  - platform: template\n    name: "Clock Correction Threshold"\n',
    ),
    'switch_arm': (
        '    restore_mode: ALWAYS_OFF\n    icon: "mdi:shield-key-outline"\n',
        '\nselect:\n',
    ),
    'review_arm_off': (
        '            id(fallback_profile_invalidate_candidate).execute();\n          }\n',
        '          // Per-boot salt of the candidate id, seeded lazily (never in on_boot).\n          if (id(fallback_profile_boot_salt) == 0) id(fallback_profile_boot_salt) = random_uint32() | 1u;\n',
    ),
    'dispatch_drain': (
        '                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT;\n                                  }\n',
        '      - lambda: |-\n          // REVIEW final step: integrity check first, then the read-failure / pass-compare\n',
    ),
    'final_guard': (
        '          // outcomes, then (both passes agree on all 31 words) a fresh read-only look at\n          // the stored profile + witness and a RAM-only candidate. No write of any kind.\n',
        '          if (!ecco_fbcap::review_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose))) {\n            ecco_fbcap::TextBuf bad = ecco_fbcap::internal_context_text();\n',
    ),
    'final_overlay': (
        '            in.last_w_bytes = id(fallback_witness_bytes);\n            ecco_fbcap::ReadEval e = ecco_fbcap::evaluate_read(in);\n',
        '            // Latest authoritative read wins: mirror first, publishes after.\n            id(fallback_profile_present_seen) = e.latch.present_seen;\n',
    ),
    'final_state_name': (
        '            id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(w);\n            {\n',
        '              if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);\n            }\n',
    ),
    'final_b2': (
        '              if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);\n            }\n            {\n',
        '              if (id(fallback_profile_summary_text).state != t.c_str()) id(fallback_profile_summary_text).publish_state(t.c_str());\n            }\n            {\n              ecco_fbcap::TextBuf t = ecco_fbcap::b7_text(lp, p, e.cls);\n              if (id(fallback_profile_slots_text).state != t.c_str()) id(fallback_profile_slots_text).publish_state(t.c_str());\n            }\n            {\n              ecco_fbcap::TextBuf t = ecco_fbcap::b8_text(lp, p, e.cls);\n              if (id(fallback_profile_context_text).state != t.c_str()) id(fallback_profile_context_text).publish_state(t.c_str());\n            }\n            // Verdict on pass 2: L2 refusals + warnings, eligibility, prior fingerprint, masks, candidate id.\n',
    ),
    'final_ri_cls': (
        '            ri.words = id(fallback_profile_pass2);\n            ri.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};\n',
        '            ri.read_anomaly = e.latch.read_anomaly;\n            ri.p_load = lp;\n',
    ),
    'final_arm_off': (
        '            ri.seq_next = id(fallback_profile_cand_seq) + 1;\n            ecco_fbcap::ReviewVerdict v = ecco_fbcap::review_evaluate(ri);\n',
        '            id(fallback_profile_cand_words) = id(fallback_profile_pass2);\n            id(fallback_profile_cand_id) = v.id;\n',
    ),
    'final_prior_class': (
        '            id(fallback_profile_cand_words) = id(fallback_profile_pass2);\n            id(fallback_profile_cand_id) = v.id;\n',
        '            id(fallback_profile_cand_prior_gen) = v.prior_generation;\n            id(fallback_profile_cand_prior_binding) = v.prior_binding;\n',
    ),
    'final_b3': (
        '            built = true;\n            {\n',
        '                                                          ecco_fbcap::exp_seconds(millis(), id(fallback_profile_cand_ms)), v.warnings,\n                                                          id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch),\n',
    ),
    'final_not_saveable': (
        '              res = ecco_fbcap::candidate_ready_text();\n            } else {\n',
        '            }\n          }\n',
    ),
    'save_final': (
        '                   (unsigned) built, (unsigned) (uint32_t) (millis() - id(fallback_profile_op_started_ms)));\n      - lambda: |-\n',
        '          // The single release point, reached on every path of this script.\n          id(fallback_profile_op_in_progress) = false;\n',
    ),
    'release_ctx': (
        '          id(fallback_profile_step) = 0;\n          id(fallback_profile_op_purpose) = 0;\n',
        '\n  # Candidate reset (RAM only). Callers set fallback_profile_invalidate_reason first;\n',
    ),
    'scripts': (
        '          }\n          id(fallback_profile_invalidate_reason) = "";\n',
        '\nbutton:\n',
    ),
    'breaker_ctx': (
        '            id(fallback_profile_op_purpose) = 0;\n            id(fallback_profile_step) = 0;\n',
        '            ecco_fbcap::TextBuf brk = ecco_fbcap::breaker_text(lock_held);\n            id(fallback_profile_invalidate_reason) = brk.c_str();\n',
    ),
    'tick2': (
        '                if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());\n              }\n            }\n',
        '          }\n\n  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n',
    ),
}


# ---------------------------------------------------------------------------
# The hunks. before = left + old + right (the FB-B1 text), after = left + new + right (the FB-B2 text).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Hunk:
    name: str
    region: str       # where in the firmware the edit sits
    left: str         # context before the edit (exact, unchanged lines only)
    old: str          # the FB-B1 text replaced ("" for a pure insertion)
    new: str          # the FB-B2 text
    right: str        # context after the edit (exact, unchanged lines only)

    @property
    def before(self) -> str:
        return self.left + self.old + self.right

    @property
    def after(self) -> str:
        return self.left + self.new + self.right

    @property
    def insertion(self) -> bool:
        return self.old == ""


def _ins(name: str, region: str, new: str) -> Hunk:
    left, right = ANCHORS[name]
    return Hunk(name, region, left, "", new, right)


def _rep(name: str, region: str) -> Hunk:
    left, right = ANCHORS[name]
    old, new = REPLACEMENTS[name]
    return Hunk(name, region, left, old, new, right)


HUNKS = (
    _ins("include", "esphome.includes (appended LAST, after the capture header)", INCLUDE_BLOCK),
    _rep("boot_b2", "on_boot[3] (FB-B1 boot lambda): B2 publishes the retained last write error / time"),
    _ins("api_action", "api.actions (appended AFTER ha_supervision_heartbeat)", API_ACTION_BLOCK),
    _ins("globals", "globals (after the FB-B1 review state)", GLOBALS_BLOCK),
    _ins("switch_arm", "switch (appended last, before select:)", SWITCH_ARM_BLOCK),
    _ins("review_arm_off", "script fallback_profile_review (gate): arm turned off after V1 / IE3", REVIEW_ARM_OFF_BLOCK),
    _ins("dispatch_drain", "script fallback_profile_capture_dispatch: SAVE-only pre-commit poller drain, before REVIEW_FINAL",
         DISPATCH_DRAIN_BLOCK),
    _ins("final_guard", "dispatch REVIEW_FINAL: purpose guard (a SAVE dispatch is skipped)", FINAL_GUARD_BLOCK),
    _ins("final_overlay", "dispatch REVIEW_FINAL: eff_cls = SAVE_UNCONFIRMED overlay of the composed class", FINAL_OVERLAY_BLOCK),
    _rep("final_state_name", "dispatch REVIEW_FINAL: B1 publishes epc_name(eff_cls)"),
    _rep("final_b2", "dispatch REVIEW_FINAL: B2 publishes the retained last write error / time"),
    _rep("final_ri_cls", "dispatch REVIEW_FINAL: ReviewInputs.cls = eff_cls"),
    _ins("final_arm_off", "dispatch REVIEW_FINAL: arm turned off before the candidate is published", FINAL_ARM_OFF_BLOCK),
    _rep("final_prior_class", "dispatch REVIEW_FINAL: cand_prior_class = eff_cls"),
    _rep("final_b3", "dispatch REVIEW_FINAL: the B3 text carries eff_cls"),
    _rep("final_not_saveable", "dispatch REVIEW_FINAL: the not-saveable text carries eff_cls"),
    _ins("save_final", "script fallback_profile_capture_dispatch: SAVE_FINAL part 1 (verify) and part 2 (commit), between REVIEW_FINAL and RELEASE",
         SAVE_FINAL_BLOCK),
    _ins("release_ctx", "dispatch RELEASE lambda: the SAVE context is cleared", RELEASE_CTX_BLOCK),
    _ins("scripts", "script (appended last, before button:): fallback_profile_save and fallback_profile_invalidate", SCRIPTS_BLOCK),
    _ins("breaker_ctx", "interval 10s housekeeping lambda 1: the breaker block clears the SAVE context", BREAKER_CTX_BLOCK),
    _ins("tick2", "interval 10s: second appended housekeeping lambda (arm lifetime, IE8)", TICK2_BLOCK),
)
HUNK_NAMES = tuple(h.name for h in HUNKS)
assert len(set(HUNK_NAMES)) == len(HUNKS) == 21
assert sum(h.insertion for h in HUNKS) == 14 and sum(not h.insertion for h in HUNKS) == 7

# The seven insertions at the boundary of an FB-B1 block, and the fourteen edits INSIDE FB-B1's own text (the ones that make the
# fbb1 anchors non-contiguous until this reverter has run).
BOUNDARY_HUNKS = ("include", "api_action", "globals", "switch_arm", "save_final", "scripts", "tick2")
INPLACE_FBB1_HUNKS = tuple(n for n in HUNK_NAMES if n not in BOUNDARY_HUNKS)
assert len(BOUNDARY_HUNKS) == 7 and len(INPLACE_FBB1_HUNKS) == 14
# The seven pre-existing lines FB-B2 modifies (name -> (old line, new line)); every other pre-existing line is untouched.
REPLACED_LINES = {name: REPLACEMENTS[name] for name in HUNK_NAMES if name in REPLACEMENTS}
assert len(REPLACED_LINES) == 7 and all(not h.insertion for h in HUNKS if h.name in REPLACED_LINES)


def hunk(name: str) -> Hunk:
    return HUNKS[HUNK_NAMES.index(name)]


# The FB-A reserved tokens FB-B2 adds to the firmware YAML, per hunk (chain entry fbb2 declares the total).
BANNED_FW_BY_HUNK = {h.name: len(_BANNED.findall(h.new)) - len(_BANNED.findall(h.old)) for h in HUNKS}
BANNED_FW_ADDED = sum(BANNED_FW_BY_HUNK.values())


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-B2 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def pre_fbb2_firmware(text: str) -> str:
    """The firmware text with exactly FB-B2's twenty-one edits undone (the exact-match reverter of chain entry fbb2). Every hunk
    must occur exactly once, in place, else AssertionError; after the revert every base anchor must again be unique (nothing
    else matches it). Reproduces the FB-B1 firmware (main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for h in reversed(HUNKS):
        out = _swap(out, h.after, h.before, f"{h.name} hunk", "present")
    for h in HUNKS:
        n = out.count(h.before)
        if n != 1:
            raise AssertionError(f"FB-B2 scope: the {h.name} anchor must be unique once the hunk is removed, found {n}x")
    return out


def add_fbb2_text(text: str) -> str:
    """Applies FB-B2 to a firmware text that has none of it (generates the change; the suite's round trip). Every anchor must be
    unique and no hunk may already be present."""
    out = text
    for h in HUNKS:
        if h.after in out:
            raise AssertionError(f"FB-B2 scope: {h.name} hunk already present")
        out = _swap(out, h.before, h.after, f"{h.name} anchor", "found")
    return out
