"""FB-C2 (Failback Shadow EVALUATOR) change scope: exactly what FB-C2 changes in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fbb3_scope.py / _fbb2_scope.py: the verbatim edits are held HERE as the single source of truth, as exact
(before, after) pairs, and a reverter raises unless every edit is present exactly once. The chain entry `fbc2`
(registry/tests/_scope_chain.py) carries `pre_fbc2_firmware`: the current firmware text with exactly these edits removed, which
reproduces the FB-B3 / S3-wrapper firmware byte-for-byte (BASE_FW_SHA = the chain's fbb3 checkpoint). The older suites are anchored
at their own entries and revert fbc2 FIRST; none of them was re-hashed.

FB-C2 edits the firmware in fourteen places and adds NO script, button, switch, number, select, api action, interval, sensor or
text sensor, and no Modbus operation:

  substitution   ecco_failback_shadow_cache_max_age_ms (FB-C1 left cache_max_age to FB-C2: FINAL 6.3)
  includes       include/ecco_failback_shadow.h (the pure evaluator header)
  globals        the FB-C2 RAM state (every one `restore_value: no`): the episode kind / frozen edge plan / bound profile identity,
                 the would-latched flag, the live latch, the shadow's own 1 s write fence, the owner-orphan timers, activity
                 evidence, the verdict-change and profile-change counters and the soak accumulators
  text sensors   comment only (Verdict and Inputs are real now)
  interval       lambda 0: the cache-age static asserts; lambda 1 (the tick): the evaluator block, the kind / edge-plan freeze at the
                 LOST edge, the close outcome and would-latched flag, verdict-change counting, the State / Verdict / Inputs /
                 Episode / Soak publication

Nothing in the deployment manifest, the Home Assistant packages or the firmware's other YAML files changes.

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# main FB-C2 is based on: FB-B3 (+ the S3 hardware variant), the chain's fbb3 checkpoint.
BASE_COMMIT = "bb2e771cbad0f34c3271070ce2bbbdb209340970"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML at BASE_COMMIT: what pre_fbc2_firmware() must reproduce;
# equal to the chain's fbb3 checkpoint.
BASE_FW_SHA = "645a297a009403fcf4092d930f8735f627294642c2934dcdde5caa756e37d65f"

_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")

ADDED_FILES = frozenset({
    "docs/architecture/fallback/FB_C2_IMPLEMENTATION_NOTES.md",
    "firmware/include/ecco_failback_shadow.h",
    "registry/failback_shadow.py",
    "registry/tests/_fbc2_cxx.py",
    "registry/tests/_fbc2_fixtures.py",
    "registry/tests/_fbc2_harness.py",
    "registry/tests/_fbc2_rows.py",
    "registry/tests/_fbc2_rows_check.py",
    "registry/tests/_fbc2_scope.py",
    "registry/tests/test_failback_shadow_evaluator.py",
    "registry/tests/test_failback_shadow_tick.py",
})

HEADER_REL = "firmware/include/ecco_failback_shadow.h"
INCLUDE_ENTRY = "include/ecco_failback_shadow.h"
SUBSTITUTION = ("ecco_failback_shadow_cache_max_age_ms", "180000")

# The FB-C2 RAM globals, in declaration order (single source of truth for the suites).
NEW_GLOBAL_SPECS = (
    # id, type, initial
    ("failback_shadow_would_latched", "bool", "false"),
    ("failback_shadow_ep_kind", "uint8_t", "0"),
    ("failback_shadow_ep_v0", "uint8_t", "255"),
    ("failback_shadow_ep_vu", "uint8_t", "255"),
    ("failback_shadow_ep_f0", "uint8_t", "255"),
    ("failback_shadow_ep_dm0", "uint8_t", "255"),
    ("failback_shadow_ep_pre0", "uint8_t", "0"),
    ("failback_shadow_ep_blk0", "uint8_t", "0"),
    ("failback_shadow_ep_d0", "uint8_t", "255"),
    ("failback_shadow_ep_pclass", "uint8_t", "0"),
    ("failback_shadow_ep_pgen", "uint32_t", "0"),
    ("failback_shadow_ep_pbind", "uint64_t", "0"),
    ("failback_shadow_ep_verdict_changes", "uint16_t", "0"),
    ("failback_shadow_last_verdict", "uint8_t", "255"),
    ("failback_shadow_seen_pgen", "uint32_t", "0"),
    ("failback_shadow_seen_pclass", "uint8_t", "255"),
    ("failback_shadow_wr_prof", "uint16_t", "0"),
    ("failback_shadow_seen_active_fp", "bool", "false"),
    ("failback_shadow_seen_active_dump", "bool", "false"),
    ("failback_shadow_seen_active_r244", "bool", "false"),
    ("failback_shadow_fp_orphan_since_ms", "uint32_t", "0"),
    ("failback_shadow_dump_orphan_since_ms", "uint32_t", "0"),
    ("failback_shadow_r244_orphan_since_ms", "uint32_t", "0"),
    ("failback_shadow_mwip_orphan_since_ms", "uint32_t", "0"),
    ("failback_shadow_live_regs", "std::array<uint16_t, 31>", None),
    ("failback_shadow_live_seq", "uint32_t", "0"),
    ("failback_shadow_live_dispatch_seq", "uint32_t", "0"),
    ("failback_shadow_fence_seq", "uint32_t", "0"),
    ("failback_shadow_fence_edge_seq", "uint32_t", "0"),
    ("failback_shadow_fence_writes_fp", "uint32_t", "0"),
    ("failback_shadow_fence_flags", "uint8_t", "0"),
    ("failback_shadow_last_tick_ms", "uint32_t", "0"),
    ("failback_shadow_ca_f_ms", "uint32_t", "0"),
    ("failback_shadow_ca_p_ms", "uint32_t", "0"),
    ("failback_shadow_ca_o_ms", "uint32_t", "0"),
    ("failback_shadow_exh_yes_ms", "uint32_t", "0"),
    ("failback_shadow_exh_unk_ms", "uint32_t", "0"),
    ("failback_shadow_last_pub_verdict_ms", "uint32_t", "0"),
    ("failback_shadow_last_pub_inputs_ms", "uint32_t", "0"),
)
NEW_GLOBAL_IDS = tuple(s[0] for s in NEW_GLOBAL_SPECS)


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _globals_block() -> str:
    out = [
        "  # ---------------------------------------------------------------------\n"
        "  # Failback Shadow EVALUATOR (FB-C2) - more RAM-only state of the same zero-authority\n"
        "  # observer. Every global below is restore_value: no and is written ONLY by the Failback\n"
        "  # Shadow 1s interval; nothing else reads or writes it. None is a durable record and none\n"
        "  # is a write basis.\n"
        "  #   ep_kind .. ep_d0     the episode kind (1 N / 2 L) and the FROZEN edge plan (255 = none)\n"
        "  #   ep_pclass/pgen/pbind the profile identity bound at the LOST edge\n"
        "  #   would_latched        the modelled FB-F latch (cleared only by a reboot)\n"
        "  #   live_*               the torn-snapshot latch of the 31 cached configuration words\n"
        "  #   fence_*              the shadow's OWN 1 s write fence (the same shared fence_tick as\n"
        "  #                        the Live Match; the trust rule also honours the Live Match fence)\n"
        "  #   *_orphan_since_ms    an operation flag with no running owner script (0 = not orphaned)\n"
        "  #   ca_*_ms / exh_*_ms   soak accumulators: time per cache state / export-hazard state (exh_*\n"
        "  #                        only while an export-relevant lease obligation is open)\n"
        "  # ---------------------------------------------------------------------\n"
    ]
    for gid, gtype, init in NEW_GLOBAL_SPECS:
        out.append(f"  - id: {gid}\n    type: {gtype}\n    restore_value: no\n")
        if init is not None:
            out.append(f"    initial_value: '{init}'\n")
    return "".join(out)


GLOBALS_BLOCK = _globals_block()

SUBSTITUTION_BLOCK = _blk(r"""
  # FB-C2: the age beyond which the cached Block B response is no longer "current" for a shadow
  # verdict. It is the FB-B3 live-cache rule's constant (ecco_fbcap::LIVE_CACHE_MAX_AGE_MS, two 60 s
  # polls plus margin); lambda 0 pins the two equal and inside the architecture's 125-300 s window.
  ecco_failback_shadow_cache_max_age_ms: "180000"
""")

TEXT_SENSOR_COMMENT_OLD = _blk(r"""
  # Failback Shadow (FB-C1) - five read-only diagnostic strings, published only
  # by the Failback Shadow interval (update_interval: never). Verdict and
  # Inputs are NOT_EVALUATED until the evaluator (FB-C2) exists.
""")
TEXT_SENSOR_COMMENT_NEW = _blk(r"""
  # Failback Shadow (FB-C1 / FB-C2) - five read-only diagnostic strings, published only
  # by the Failback Shadow interval (update_interval: never). Verdict and Inputs carry
  # the evaluator's deterministic plan (FB-C2); the plan is NEVER acted on.
""")

LAMBDA0_OLD = _blk(r"""
          static_assert(${ecco_failback_shadow_publish_min_ms}UL <= 30000UL,
                        "failback shadow: publish debounce must be at most one heartbeat period");
""")
LAMBDA0_NEW = LAMBDA0_OLD + _blk(r"""
          static_assert(${ecco_failback_shadow_cache_max_age_ms}UL >= 125000UL && ${ecco_failback_shadow_cache_max_age_ms}UL <= 300000UL,
                        "failback shadow: cache max age must lie in 125..300 s (two polls plus margin, below the stale-cache window)");
          static_assert(${ecco_failback_shadow_cache_max_age_ms}UL == ecco_fbcap::LIVE_CACHE_MAX_AGE_MS,
                        "failback shadow: the cache max age must equal the shared live-cache rule's constant");
""")

FIRST_OLD = _blk(r"""
            id(failback_shadow_noclient_since_ms) = 0;
            ESP_LOGI("failback_shadow", "boot %08X shadow ready", (unsigned) id(supervision_boot_nonce));
""")
FIRST_NEW = _blk(r"""
            id(failback_shadow_noclient_since_ms) = 0;
            id(failback_shadow_last_tick_ms) = now;
            ESP_LOGI("failback_shadow", "boot %08X shadow ready", (unsigned) id(supervision_boot_nonce));
""")

# ---- 4b. the evaluator block -------------------------------------------------------------------------------------------------
EVAL_ANCHOR_OLD = _blk(r"""
          id(failback_shadow_busy_fp) = busy_fp;
          id(failback_shadow_busy_dump) = busy_dump;
          id(failback_shadow_busy_r244) = busy_r244;

          // 5. Episode machine: NONE -> OPEN -> HA_BACK -> CLOSED. Edges come
""")
EVAL_BLOCK = _blk(r"""

          // 4b. FB-C2 evaluator (RAM only, no Modbus, no storage, no script, no control). Everything is gathered BY VALUE into
          // one ShadowInputs and handed to the pure evaluator ONCE, in MODE_IF_LOST: `rd` is the readiness plan ("what would
          // happen if HA were lost now"), the Verdict and the plan a LOST edge freezes (FINAL 8.5, S3 9.2 / 11.4, S5 2.3: inside
          // an episode it equals the ACTUAL continuation plan; NO_ACTION / WOULD_REFUSE_STARTS are never published). The plan is
          // only ever published.
          // Sticky activity evidence (the CLEAR basis of a lease domain: boot marker M, runtime R, absence A).
          if (busy_fp) id(failback_shadow_seen_active_fp) = true;
          if (busy_dump) id(failback_shadow_seen_active_dump) = true;
          if (busy_r244) id(failback_shadow_seen_active_r244) = true;
          const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;
          // Owner scripts that are running right now (is_running() only reads).
          const bool run_fp_start = id(start_free_power_override).is_running();
          const bool run_fp_restore = id(restore_free_power_snapshot).is_running() ||
                                      id(restore_free_power_snapshot_dispatch).is_running();
          const bool run_fp_operator = id(free_power_recovery_review).is_running() ||
                                       id(free_power_recovery_review_dispatch).is_running() ||
                                       id(free_power_recovery_force_restore).is_running() ||
                                       id(free_power_recovery_force_restore_dispatch).is_running() ||
                                       id(free_power_recovery_accept_current_state).is_running() ||
                                       id(free_power_recovery_accept_current_state_dispatch).is_running();
          const bool run_dump_start = id(start_dump_to_grid_override).is_running();
          const bool run_dump_restore = id(restore_dump_to_grid_snapshot).is_running();
          const bool run_dump_other = id(dump_controller_tick).is_running() || id(dump_lockout_containment).is_running();
          const bool run_r244_apply = id(apply_reg244_settings).is_running();
          const bool run_r244_restore = id(restore_reg244_snapshot).is_running();
          const bool run_mtou = id(apply_manual_slot1).is_running() || id(apply_manual_slot2).is_running() ||
                                id(apply_manual_slot3).is_running() || id(apply_manual_slot4).is_running() ||
                                id(apply_manual_slot5).is_running() || id(apply_manual_slot6).is_running();
          const bool run_capture = id(fallback_profile_capture_dispatch).is_running();
          const bool any_owner = run_fp_start || run_fp_restore || run_fp_operator || run_dump_start || run_dump_restore ||
                                 run_dump_other || run_r244_apply || run_r244_restore || run_mtou || run_capture;
          // Orphan timers: an operation flag that is set while no owner script runs (0 = not orphaned).
          const bool fp_orphan = (id(free_power_operation_in_progress) || id(free_power_recovery_force_in_progress) ||
                                  id(free_power_recovery_accept_in_progress)) && !(run_fp_start || run_fp_restore || run_fp_operator);
          const bool dump_orphan = id(dump_operation_in_progress) && !(run_dump_start || run_dump_restore || run_dump_other);
          const bool r244_orphan = id(reg244_apply_in_progress) && !(run_r244_apply || run_r244_restore);
          const bool mwip_orphan = id(manual_write_in_progress) && !any_owner;
          if (!fp_orphan) id(failback_shadow_fp_orphan_since_ms) = 0;
          else if (id(failback_shadow_fp_orphan_since_ms) == 0) id(failback_shadow_fp_orphan_since_ms) = now;
          if (!dump_orphan) id(failback_shadow_dump_orphan_since_ms) = 0;
          else if (id(failback_shadow_dump_orphan_since_ms) == 0) id(failback_shadow_dump_orphan_since_ms) = now;
          if (!r244_orphan) id(failback_shadow_r244_orphan_since_ms) = 0;
          else if (id(failback_shadow_r244_orphan_since_ms) == 0) id(failback_shadow_r244_orphan_since_ms) = now;
          if (!mwip_orphan) id(failback_shadow_mwip_orphan_since_ms) = 0;
          else if (id(failback_shadow_mwip_orphan_since_ms) == 0) id(failback_shadow_mwip_orphan_since_ms) = now;
          // The wall clock, only to mirror the lease expiry rule of the watchdogs (the same predicate).
          auto now_wall = id(ntp_time).now();
          const bool clock_valid = now_wall.is_valid();
          const uint32_t now_epoch = clock_valid ? (uint32_t) now_wall.timestamp : 0;
          // The shared RAM legs of every lease domain and the bus, exactly as the Live Match gathers them.
          ecco_fbcap::GateInputs gi{};
          gi.boot_loaded = id(fallback_profile_boot_loaded);
          gi.probe_latch = id(fallback_profile_probe_latch);
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
          gi.bus.fallback_profile_capture_dispatch_running = run_capture;
          gi.bus.diag_write_lock_held = id(diag_write_lock_held);
          gi.bus.diag_write_lock_since_ms = id(diag_write_lock_since_ms);
          gi.bus.now_ms = now;
          gi.fp.free_power_marker_boot_load = id(free_power_marker_boot_load);
          gi.fp.free_power_recovery_metadata_corrupt = id(free_power_recovery_metadata_corrupt);
          gi.fp.free_power_snapshot_valid = id(free_power_snapshot_valid);
          gi.fp.free_power_marker_state = id(free_power_marker_state);
          gi.fp.free_power_operator_needed = id(free_power_operator_needed);
          gi.fp.free_power_active_persisted = id(free_power_active_persisted);
          gi.fp.free_power_restore_requested = id(free_power_restore_requested);
          gi.fp.expired = (clock_valid && id(free_power_end_epoch) != 0) ? (now_epoch >= id(free_power_end_epoch))
                                                                         : (now >= ${ecco_free_power_invalid_clock_grace_ms}UL);
          gi.fp.run_start = run_fp_start;
          gi.fp.run_restore = run_fp_restore;
          gi.fp.run_operator = run_fp_operator;
          gi.dump.dump_marker_boot_load = id(dump_marker_boot_load);
          gi.dump.dump_recovery_metadata_corrupt = id(dump_recovery_metadata_corrupt);
          gi.dump.dump_containment_state = id(dump_containment_state);
          gi.dump.dump_snapshot_valid = id(dump_snapshot_valid);
          gi.dump.dump_marker_state = id(dump_marker_state);
          gi.dump.dump_operator_needed = id(dump_operator_needed);
          gi.dump.dump_active_persisted = id(dump_active_persisted);
          gi.dump.dump_restore_requested = id(dump_restore_requested);
          gi.dump.expired = (clock_valid && id(dump_end_epoch) != 0) ? (now_epoch >= id(dump_end_epoch))
                                                                     : (now >= ${ecco_free_power_invalid_clock_grace_ms}UL);
          gi.dump.run_start = run_dump_start;
          gi.dump.run_restore = run_dump_restore;
          gi.r244.reg244_marker_boot_load = id(reg244_marker_boot_load);
          gi.r244.reg244_recovery_metadata_corrupt = id(reg244_recovery_metadata_corrupt);
          gi.r244.reg244_snapshot_valid = id(reg244_snapshot_valid);
          gi.r244.reg244_marker_state = id(reg244_marker_state);
          gi.r244.run_apply = run_r244_apply;
          gi.r244.run_restore = run_r244_restore;
          // The shadow's own 1 s write fence: the SAME shared fence_tick the Live Match uses, sampled every tick.
          ecco_fbcap::FenceState fs{};
          fs.seq = id(failback_shadow_fence_seq);
          fs.edge_seq = id(failback_shadow_fence_edge_seq);
          fs.writes_fp = id(failback_shadow_fence_writes_fp);
          fs.flags = id(failback_shadow_fence_flags);
          ecco_fbcap::FenceSample fsample{};
          fsample.bus_hot = ecco_fbcap::bus_busy(gi.bus);
          fsample.lease_nonclear = ecco_fbcap::lease_domain_nonclear(gi) != ecco_fbcap::SLOT_NONE;
          fsample.writes_fp = ecco_fbcap::writes_fingerprint((uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts),
                                                             (uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts),
                                                             (uint32_t) id(dump_start_attempts));
          fsample.dispatch_seq = id(cfg_block_b_dispatch_seq);
          fs = ecco_fbcap::fence_tick(fs, fsample);
          id(failback_shadow_fence_seq) = fs.seq;
          id(failback_shadow_fence_edge_seq) = fs.edge_seq;
          id(failback_shadow_fence_writes_fp) = fs.writes_fp;
          id(failback_shadow_fence_flags) = fs.flags;
          // The live latch: the 31 cached words are copied on the first tick after a Block B success, so a tick between Block A
          // and Block B of one poll can never pair two polls.
          const uint32_t bseq = id(cfg_block_b_seq);
          if (bseq != 0 && bseq != id(failback_shadow_live_seq)) {
            id(failback_shadow_live_seq) = bseq;
            id(failback_shadow_live_dispatch_seq) = id(cfg_block_b_response_dispatch_seq);
            id(failback_shadow_live_regs)[0] = id(manual_cfg_reg244_raw);
            id(failback_shadow_live_regs)[1] = id(manual_cfg_reg256_raw);
            id(failback_shadow_live_regs)[2] = id(manual_cfg_reg257_raw);
            id(failback_shadow_live_regs)[3] = id(manual_cfg_reg258_raw);
            id(failback_shadow_live_regs)[4] = id(manual_cfg_reg259_raw);
            id(failback_shadow_live_regs)[5] = id(manual_cfg_reg260_raw);
            id(failback_shadow_live_regs)[6] = id(manual_cfg_reg261_raw);
            id(failback_shadow_live_regs)[7] = id(manual_cfg_reg268_raw);
            id(failback_shadow_live_regs)[8] = id(manual_cfg_reg269_raw);
            id(failback_shadow_live_regs)[9] = id(manual_cfg_reg270_raw);
            id(failback_shadow_live_regs)[10] = id(manual_cfg_reg271_raw);
            id(failback_shadow_live_regs)[11] = id(manual_cfg_reg272_raw);
            id(failback_shadow_live_regs)[12] = id(manual_cfg_reg273_raw);
            id(failback_shadow_live_regs)[13] = id(manual_cfg_reg274_raw);
            id(failback_shadow_live_regs)[14] = id(manual_cfg_reg275_raw);
            id(failback_shadow_live_regs)[15] = id(manual_cfg_reg276_raw);
            id(failback_shadow_live_regs)[16] = id(manual_cfg_reg277_raw);
            id(failback_shadow_live_regs)[17] = id(manual_cfg_reg278_raw);
            id(failback_shadow_live_regs)[18] = id(manual_cfg_reg279_raw);
            id(failback_shadow_live_regs)[19] = id(manual_cfg_reg232_raw);
            id(failback_shadow_live_regs)[20] = id(fbc_raw_243);
            id(failback_shadow_live_regs)[21] = id(fbc_raw_248);
            id(failback_shadow_live_regs)[22] = id(manual_cfg_reg250_raw);
            id(failback_shadow_live_regs)[23] = id(manual_cfg_reg251_raw);
            id(failback_shadow_live_regs)[24] = id(manual_cfg_reg252_raw);
            id(failback_shadow_live_regs)[25] = id(manual_cfg_reg253_raw);
            id(failback_shadow_live_regs)[26] = id(manual_cfg_reg254_raw);
            id(failback_shadow_live_regs)[27] = id(manual_cfg_reg255_raw);
            id(failback_shadow_live_regs)[28] = id(fbc_raw_230);
            id(failback_shadow_live_regs)[29] = id(fbc_raw_245);
            id(failback_shadow_live_regs)[30] = id(fbc_raw_247);
          }
          // The profile mirror (read-only copy of what FB-B1 / FB-B2 hold) and its effective class (SAVE_UNCONFIRMED overlay).
          const uint8_t eff_cls = ecco_fbcap::live_effective_class(id(fallback_profile_class), id(fallback_profile_save_unconfirmed),
                                                                    id(fallback_profile_read_anomaly));
          const ecco_fallback::FallbackProfileV1 prof = ecco_fallback::decode_profile(id(fallback_profile_bytes));
          const bool prof_meaningful = ecco_failback_shadow::meaningful_class(eff_cls);
          // Profile-change evidence for the soak counter (a SAVE while FB-D / FB-F would refuse; an INVALIDATE only inside an episode).
          // The generation is tracked from the COMPOSED class (no SAVE_UNCONFIRMED / read-anomaly overlay), so an overlay that
          // clears over the same record is never mistaken for a SAVE.
          const uint32_t pgen_now = prof_meaningful ? (uint32_t) prof.generation : 0;
          const uint32_t pgen_track = ecco_failback_shadow::meaningful_class(id(fallback_profile_class)) ? (uint32_t) prof.generation : 0;
          if (id(failback_shadow_seen_pclass) != 255 && pgen_track != id(failback_shadow_seen_pgen)) {
            if ((eff_cls == ecco_fbdurable::EPC_VALID && wref_prev) ||
                (eff_cls == ecco_fbdurable::EPC_INVALIDATED && ph_prev_open)) {
              if (id(failback_shadow_wr_prof) < 65535) id(failback_shadow_wr_prof) += 1;
              soak_now = true;
              ESP_LOGI("failback_shadow", "profile change observed while FB-D/FB-F would refuse (class %u)", (unsigned) eff_cls);
            }
          }
          id(failback_shadow_seen_pgen) = pgen_track;
          id(failback_shadow_seen_pclass) = eff_cls;
          // One ShadowInputs, by value.
          ecco_failback_shadow::ShadowInputs in{};
          in.sup.state = st;
          in.sup.p_stable = stable;
          in.sup.episode_open = ph_prev_open;
          in.lm.g = gi;
          in.lm.mtou_running = run_mtou;
          in.lm.cls = id(fallback_profile_class);
          in.lm.write_outcome_unknown = id(fallback_profile_save_unconfirmed);
          in.lm.read_anomaly = id(fallback_profile_read_anomaly);
          in.lm.p_load = id(fallback_profile_load);
          in.lm.p = prof;
          in.profile_why = id(fallback_profile_why);
          in.lm.cache.cache_valid = id(manual_config_raw_cache_valid);
          in.lm.cache.online = id(configuration_online).state;
          in.lm.cache.polling = id(configuration_polling).state;
          in.lm.cache.filled = id(fbc_raw_filled);
          in.lm.cache.block_b_seq = bseq;
          in.lm.cache.block_b_ok_ms = id(cfg_block_b_ok_ms);
          in.lm.cache.now_ms = now;
          in.lm.cache.response_dispatch_seq = id(failback_shadow_live_dispatch_seq);
          // Never weaker than the Live Match: the larger of the two write fences decides.
          in.lm.cache.fence_seq = ecco_fbcap::seq_max(fs.seq, id(fallback_profile_live_fence_seq));
          in.lm.edge_fence_seq = ecco_fbcap::seq_max(fs.edge_seq, id(fallback_profile_live_edge_seq));
          for (size_t k = 0; k < 31; k++) in.lm.live[k] = id(failback_shadow_live_regs)[k];
          in.lm.dump_data_loaded = id(dump_snapshot_data_loaded);
          in.lm.dump_snapshot_reg244 = id(dump_snapshot_reg244);
          in.lm.dump_snapshot_reg256_261[0] = id(dump_snapshot_reg256);
          in.lm.dump_snapshot_reg256_261[1] = id(dump_snapshot_reg257);
          in.lm.dump_snapshot_reg256_261[2] = id(dump_snapshot_reg258);
          in.lm.dump_snapshot_reg256_261[3] = id(dump_snapshot_reg259);
          in.lm.dump_snapshot_reg256_261[4] = id(dump_snapshot_reg260);
          in.lm.dump_snapshot_reg256_261[5] = id(dump_snapshot_reg261);
          in.lm.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};
          in.not_captured_proven = false;  // FB-B0's witness has no "present with generation 0" state: absence is never proof
          in.absence_witness = false;      // reserved for FB-D
          in.fp_lease_ctx_unknown = id(free_power_lease_context_reg244) == -1;
          in.fp.backoff = id(free_power_restore_next_attempt_ms) != 0 && (int32_t) (now - id(free_power_restore_next_attempt_ms)) < 0;
          in.fp.orphan_ms = id(failback_shadow_fp_orphan_since_ms) == 0 ? 0 : (uint32_t) (now - id(failback_shadow_fp_orphan_since_ms));
          in.fp.used_since_boot = id(failback_shadow_seen_active_fp);
          in.fp.retry_on_raw = id(free_power_operator_needed);
          in.dump.backoff = id(dump_restore_next_attempt_ms) != 0 && (int32_t) (now - id(dump_restore_next_attempt_ms)) < 0;
          in.dump.orphan_ms = id(failback_shadow_dump_orphan_since_ms) == 0 ? 0 : (uint32_t) (now - id(failback_shadow_dump_orphan_since_ms));
          in.dump.used_since_boot = id(failback_shadow_seen_active_dump);
          in.dump.retry_on_raw = false;  // the Dump retry record is not retained at boot: its marker-lost evidence is unavailable
          in.dump.force_bypass = id(dump_force_restore_bypass);
          in.r244.orphan_ms = id(failback_shadow_r244_orphan_since_ms) == 0 ? 0 : (uint32_t) (now - id(failback_shadow_r244_orphan_since_ms));
          in.r244.used_since_boot = id(failback_shadow_seen_active_r244);
          in.r244x.lav = id(reg244_last_applied_valid);
          in.r244x.la = id(reg244_last_applied_value);
          in.bus.any_owner_running = any_owner;
          in.bus.mwip_orphan_ms = id(failback_shadow_mwip_orphan_since_ms) == 0 ? 0 : (uint32_t) (now - id(failback_shadow_mwip_orphan_since_ms));
          in.bus.cip_held_ms = id(diag_correction_lock_held) ? (uint32_t) (now - id(diag_correction_lock_since_ms)) : 0;
          in.mtou_journal = 0;
          in.ep.bound = ph_prev_open;
          in.ep.cls = id(failback_shadow_ep_pclass);
          in.ep.gen = id(failback_shadow_ep_pgen);
          in.ep.binding = id(failback_shadow_ep_pbind);
          in.fp_snap.valid = id(free_power_snapshot_valid);
          in.fp_snap.r232 = id(free_power_snapshot_reg232);
          in.fp_snap.r256[0] = id(free_power_snapshot_reg256);
          in.fp_snap.r256[1] = id(free_power_snapshot_reg257);
          in.fp_snap.r256[2] = id(free_power_snapshot_reg258);
          in.fp_snap.r256[3] = id(free_power_snapshot_reg259);
          in.fp_snap.r256[4] = id(free_power_snapshot_reg260);
          in.fp_snap.r256[5] = id(free_power_snapshot_reg261);
          in.fp_snap.r268[0] = id(free_power_snapshot_reg268);
          in.fp_snap.r268[1] = id(free_power_snapshot_reg269);
          in.fp_snap.r268[2] = id(free_power_snapshot_reg270);
          in.fp_snap.r268[3] = id(free_power_snapshot_reg271);
          in.fp_snap.r268[4] = id(free_power_snapshot_reg272);
          in.fp_snap.r268[5] = id(free_power_snapshot_reg273);
          in.fp_snap.r274[0] = id(free_power_snapshot_reg274);
          in.fp_snap.r274[1] = id(free_power_snapshot_reg275);
          in.fp_snap.r274[2] = id(free_power_snapshot_reg276);
          in.fp_snap.r274[3] = id(free_power_snapshot_reg277);
          in.fp_snap.r274[4] = id(free_power_snapshot_reg278);
          in.fp_snap.r274[5] = id(free_power_snapshot_reg279);
          in.mode = ecco_failback_shadow::MODE_IF_LOST;
          const ecco_failback_shadow::ShadowPlan rd = ecco_failback_shadow::evaluate(in);
          const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;
          // Soak accumulators: how long the cache was trustworthy / pre-fence / otherwise, and how long the export hazard was
          // YES / UNKNOWN while an export-relevant lease obligation was open (FINAL 8.2: a FP / Dump / R244 domain not clear and
          // neither ACTIVE nor STARTING). With no such obligation the hazard is not counted, so an untrusted cache alone is never
          // hazard time. (The pre-fence share is the honest cost of the shared write fence, which routine RTC corrections reopen.)
          const uint32_t dt = (uint32_t) (now - id(failback_shadow_last_tick_ms));
          id(failback_shadow_last_tick_ms) = now;
          if (rd.ca == ecco_fbcap::CQ_FRESH) {
            id(failback_shadow_ca_f_ms) = (id(failback_shadow_ca_f_ms) > 0xFFFFFFFFUL - dt) ? 0xFFFFFFFFUL : id(failback_shadow_ca_f_ms) + dt;
          } else if (rd.ca == ecco_fbcap::CQ_PRE_FENCE) {
            id(failback_shadow_ca_p_ms) = (id(failback_shadow_ca_p_ms) > 0xFFFFFFFFUL - dt) ? 0xFFFFFFFFUL : id(failback_shadow_ca_p_ms) + dt;
          } else {
            id(failback_shadow_ca_o_ms) = (id(failback_shadow_ca_o_ms) > 0xFFFFFFFFUL - dt) ? 0xFFFFFFFFUL : id(failback_shadow_ca_o_ms) + dt;
          }
          if (rd.hazard_obligation) {
            if (rd.export_hazard == ecco_fbcap::EH_YES) {
              id(failback_shadow_exh_yes_ms) = (id(failback_shadow_exh_yes_ms) > 0xFFFFFFFFUL - dt) ? 0xFFFFFFFFUL : id(failback_shadow_exh_yes_ms) + dt;
            } else if (rd.export_hazard == ecco_fbcap::EH_UNKNOWN) {
              id(failback_shadow_exh_unk_ms) = (id(failback_shadow_exh_unk_ms) > 0xFFFFFFFFUL - dt) ? 0xFFFFFFFFUL : id(failback_shadow_exh_unk_ms) + dt;
            }
          }
""")
EVAL_NEW = EVAL_ANCHOR_OLD.replace(
    "\n          // 5. Episode machine", EVAL_BLOCK + "\n          // 5. Episode machine", 1)

# ---- E1: the kind and the frozen edge plan ----------------------------------------------------------------------------------
E1_OLD = _blk(r"""
              id(failback_shadow_ep_fbf) = 0;
              ph = 1;
              ep_event = true;
              ESP_LOGW("failback_shadow", "episode %08X-%u OPEN k=N tr=%s cli=%u rb=%d",
                       (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                       trig_s ? "S" : "H", (unsigned) cli, (int) id(failback_shadow_ep_reboot_margin_s));
""")
E1_NEW = _blk(r"""
              id(failback_shadow_ep_fbf) = 0;
              // FB-C2: the kind (FB-F would open a new episode, or would do nothing new while still latched), the FROZEN edge
              // plan and the profile identity bound to this episode.
              const bool latched_at_edge = id(failback_shadow_would_latched);
              id(failback_shadow_ep_kind) = ecco_failback_shadow::kind_for_edge(latched_at_edge);
              id(failback_shadow_ep_v0) = latched_at_edge ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;
              id(failback_shadow_ep_vu) = latched_at_edge ? rd.plan : (uint8_t) 255;
              id(failback_shadow_ep_f0) = latched_at_edge ? (uint8_t) 255 : rd.fba_result;
              id(failback_shadow_ep_dm0) = latched_at_edge ? (uint8_t) 255 : rd.blocking_domain;
              id(failback_shadow_ep_pre0) = latched_at_edge ? (uint8_t) 0 : (uint8_t) ((rd.would_preempt_fp ? 1 : 0) | (rd.would_preempt_dump ? 2 : 0));
              id(failback_shadow_ep_blk0) = latched_at_edge ? (uint8_t) 0 : rd.projected_frames;
              id(failback_shadow_ep_d0) = latched_at_edge ? (uint8_t) 255 : rd.delta_count;
              id(failback_shadow_ep_pclass) = eff_cls;
              id(failback_shadow_ep_pgen) = pgen_now;
              id(failback_shadow_ep_pbind) = prof_meaningful ? (uint64_t) prof.binding : (uint64_t) 0;
              id(failback_shadow_ep_verdict_changes) = 0;
              ph = 1;
              ep_event = true;
              ESP_LOGW("failback_shadow", "episode %08X-%u OPEN k=%s tr=%s cli=%u rb=%d v0=%s",
                       (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                       latched_at_edge ? "L" : "N", trig_s ? "S" : "H", (unsigned) cli,
                       (int) id(failback_shadow_ep_reboot_margin_s), ecco_failback_shadow::plan_name(id(failback_shadow_ep_v0)));
""")

# ---- E4: the close outcome and the would-latched flag ---------------------------------------------------------------------------
E4_OLD = _blk(r"""
            id(failback_shadow_ep_fbf) = 0;
            ph = 3;
            ep_event = true;
            ESP_LOGI("failback_shadow", "episode %08X-%u CLOSED after %us; no evaluator (FB-C1)",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (unsigned) id(failback_shadow_ep_close_s));
""")
E4_NEW = _blk(r"""
            // FB-C2: would FB-F self-clear (only a kind-N episode whose edge plan was "already at the profile") or stay latched
            // awaiting an acknowledgement? The latch is modelled in RAM and cleared only by a reboot.
            id(failback_shadow_ep_fbf) = ecco_failback_shadow::close_outcome(id(failback_shadow_ep_kind), id(failback_shadow_ep_v0));
            if (ecco_failback_shadow::close_latches(id(failback_shadow_ep_fbf))) id(failback_shadow_would_latched) = true;
            ph = 3;
            ep_event = true;
            ESP_LOGI("failback_shadow", "episode %08X-%u CLOSED after %us stable; FB-F would: %s",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (unsigned) id(failback_shadow_ep_close_s),
                     ecco_failback_shadow::close_latches(id(failback_shadow_ep_fbf)) ? "stay latched (ack)" : "self-clear");
""")

# ---- bookkeeping --------------------------------------------------------------------------------------------------------------
BOOK_OLD = _blk(r"""
          id(failback_shadow_phase) = ph;

          // 6. Bookkeeping for the next tick.
          id(failback_shadow_seen_svc) = svc;
          id(failback_shadow_seen_lost) = le;
          id(failback_shadow_seen_last_valid_ms) = lv;
          id(failback_shadow_prev_would_refuse) = !stable || ph == 1 || ph == 2;
""")
BOOK_NEW = _blk(r"""
          id(failback_shadow_phase) = ph;

          // FB-C2: verdict changes between two ticks that are both inside the open episode (the opening tick does not count).
          if (ph_prev_open && (ph == 1 || ph == 2) && id(failback_shadow_last_verdict) != 255 &&
              verdict != id(failback_shadow_last_verdict) && id(failback_shadow_ep_verdict_changes) < 65535) {
            id(failback_shadow_ep_verdict_changes) += 1;
          }
          id(failback_shadow_last_verdict) = verdict;

          // 6. Bookkeeping for the next tick.
          id(failback_shadow_seen_svc) = svc;
          id(failback_shadow_seen_lost) = le;
          id(failback_shadow_seen_last_valid_ms) = lv;
          id(failback_shadow_prev_would_refuse) = !stable || ph == 1 || ph == 2 || id(failback_shadow_would_latched);
""")

# ---- publication: State / Verdict / Inputs -----------------------------------------------------------------------------------------
PUB_OLD = _blk(r"""
          const char *state_s = (ph == 1) ? "SHADOW_EPISODE"
                                : (ph == 2) ? "SHADOW_EPISODE_HA_BACK"
                                : stable ? "SHADOW_IDLE" : "SHADOW_WATCH";
          if (id(failback_shadow_state_text).state != state_s) {
            id(failback_shadow_state_text).publish_state(state_s);
          }
          if (first) {
            id(failback_shadow_verdict_text).publish_state("NOT_EVALUATED");
            id(failback_shadow_inputs_text).publish_state("NOT_EVALUATED");
          }
""")
PUB_NEW = _blk(r"""
          const char *state_s = ecco_failback_shadow::state_name(ph, id(failback_shadow_would_latched), stable);
          if (id(failback_shadow_state_text).state != state_s) {
            id(failback_shadow_state_text).publish_state(state_s);
          }
          // FB-C2: the Verdict (the plan name; WOULD_REMAIN_LATCHED while the modelled latch is set) and the Inputs behind it.
          const char *verdict_s = ecco_failback_shadow::plan_name(verdict);
          if (id(failback_shadow_verdict_text).state != verdict_s &&
              (first || ep_event ||
               (uint32_t) (now - id(failback_shadow_last_pub_verdict_ms)) >= ${ecco_failback_shadow_publish_min_ms}UL)) {
            ESP_LOGI("failback_shadow", "verdict %s -> %s", id(failback_shadow_verdict_text).state.c_str(), verdict_s);
            id(failback_shadow_verdict_text).publish_state(verdict_s);
            id(failback_shadow_last_pub_verdict_ms) = now;
          }
          const ecco_fbcap::TextBuf inputs_t = ecco_failback_shadow::inputs_text(in, rd);
          if (id(failback_shadow_inputs_text).state != inputs_t.c_str() &&
              (first || ep_event ||
               (uint32_t) (now - id(failback_shadow_last_pub_inputs_ms)) >= ${ecco_failback_shadow_publish_min_ms}UL)) {
            id(failback_shadow_inputs_text).publish_state(inputs_t.c_str());
            id(failback_shadow_last_pub_inputs_ms) = now;
          }
""")

# ---- publication: Episode ---------------------------------------------------------------------------------------------------------------
EP_OLD = _blk(r"""
            char cl_s[12];
            const int32_t rb_v = id(failback_shadow_ep_reboot_margin_s);
""")
EP_NEW = _blk(r"""
            char cl_s[12];
            char v0_s[6];
            char vu_s[6];
            char f0_s[6];
            char dm_s[6];
            char d_s[6];
            if (id(failback_shadow_ep_v0) == 255) {
              snprintf(v0_s, sizeof(v0_s), "-");
            } else {
              snprintf(v0_s, sizeof(v0_s), "%u", (unsigned) id(failback_shadow_ep_v0));
            }
            if (id(failback_shadow_ep_vu) == 255) {
              snprintf(vu_s, sizeof(vu_s), "-");
            } else {
              snprintf(vu_s, sizeof(vu_s), "%u", (unsigned) id(failback_shadow_ep_vu));
            }
            if (id(failback_shadow_ep_f0) == 255) {
              snprintf(f0_s, sizeof(f0_s), "-");
            } else {
              snprintf(f0_s, sizeof(f0_s), "%u", (unsigned) id(failback_shadow_ep_f0));
            }
            if (id(failback_shadow_ep_dm0) == 255) {
              snprintf(dm_s, sizeof(dm_s), "-");
            } else {
              snprintf(dm_s, sizeof(dm_s), "%u", (unsigned) id(failback_shadow_ep_dm0));
            }
            if (id(failback_shadow_ep_d0) == 255) {
              snprintf(d_s, sizeof(d_s), "-");
            } else {
              snprintf(d_s, sizeof(d_s), "%u", (unsigned) id(failback_shadow_ep_d0));
            }
            const int32_t rb_v = id(failback_shadow_ep_reboot_margin_s);
""")
EP2_OLD = _blk(r"""
            snprintf(ep_s, sizeof(ep_s),
                     "id=%08X-%u;ph=%s;k=N;tr=%s;u0=%u;e0=%u;cli=%u;rb=%s;v0=-;vu=-;f0=-;dm=-;pre=-;blk=-;d=-;ret=%s;gap=%s;rl=%u;vch=-;cl=%s;fbf=%s",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (ph == 1) ? "O" : (ph == 2) ? "B" : "C",
                     (id(failback_shadow_ep_trigger) == 2) ? "S" : "H",
                     (unsigned) id(failback_shadow_ep_edge_uptime_s), (unsigned) id(failback_shadow_ep_edge_epoch),
                     (unsigned) id(failback_shadow_ep_client_at_edge), rb_s, ret_s, gap_s,
                     (unsigned) id(failback_shadow_ep_relost), cl_s,
                     (id(failback_shadow_ep_fbf) == 1) ? "A" : (id(failback_shadow_ep_fbf) == 2) ? "P" : "-");
""")
EP2_NEW = _blk(r"""
            snprintf(ep_s, sizeof(ep_s),
                     "id=%08X-%u;ph=%s;k=%s;tr=%s;u0=%u;e0=%u;cli=%u;rb=%s;v0=%s;vu=%s;f0=%s;dm=%s;pre=%u;blk=%X;d=%s;ret=%s;gap=%s;rl=%u;vch=%u;cl=%s;fbf=%s",
                     (unsigned) id(supervision_boot_nonce), (unsigned) id(failback_shadow_ep),
                     (ph == 1) ? "O" : (ph == 2) ? "B" : "C",
                     (id(failback_shadow_ep_kind) == 2) ? "L" : "N",
                     (id(failback_shadow_ep_trigger) == 2) ? "S" : "H",
                     (unsigned) id(failback_shadow_ep_edge_uptime_s), (unsigned) id(failback_shadow_ep_edge_epoch),
                     (unsigned) id(failback_shadow_ep_client_at_edge), rb_s, v0_s, vu_s, f0_s, dm_s,
                     (unsigned) id(failback_shadow_ep_pre0), (unsigned) id(failback_shadow_ep_blk0), d_s, ret_s, gap_s,
                     (unsigned) id(failback_shadow_ep_relost), (unsigned) id(failback_shadow_ep_verdict_changes), cl_s,
                     (id(failback_shadow_ep_fbf) == 1) ? "A" : (id(failback_shadow_ep_fbf) == 2) ? "P" : "-");
""")

# ---- publication: Soak -----------------------------------------------------------------------------------------------------------------------
SOAK_OLD = _blk(r"""
          const uint32_t ncm_v = (uint32_t) id(failback_shadow_ncm_ms) / 1000;
          char soak_s[201];
          snprintf(soak_s, sizeof(soak_s),
                   "b=%08X;h=%u/%u/%u/%u/%u/%u;mx=%s;lg=%s;gm=%u;lx=%u;wr=%u/%u/%u/0;nc=%u;ncm=%u",
                   (unsigned) id(supervision_boot_nonce),
                   (unsigned) id(failback_shadow_gap_b0), (unsigned) id(failback_shadow_gap_b1),
                   (unsigned) id(failback_shadow_gap_b2), (unsigned) id(failback_shadow_gap_b3),
                   (unsigned) id(failback_shadow_gap_b4), (unsigned) id(failback_shadow_gap_b5),
                   mx_s, lg_s, (unsigned) id(failback_shadow_gaps_missed), (unsigned) id(failback_shadow_ep),
                   (unsigned) id(failback_shadow_wr_fp), (unsigned) id(failback_shadow_wr_dump),
                   (unsigned) id(failback_shadow_wr_r244), (unsigned) id(failback_shadow_nc),
                   (unsigned) (ncm_v > 999999UL ? 999999UL : ncm_v));
""")
SOAK_NEW = _blk(r"""
          const uint32_t ncm_v = (uint32_t) id(failback_shadow_ncm_ms) / 1000;
          const uint32_t xh_y = id(failback_shadow_exh_yes_ms) / 1000;
          const uint32_t xh_u = id(failback_shadow_exh_unk_ms) / 1000;
          const uint32_t cs_f = id(failback_shadow_ca_f_ms) / 1000;
          const uint32_t cs_p = id(failback_shadow_ca_p_ms) / 1000;
          const uint32_t cs_o = id(failback_shadow_ca_o_ms) / 1000;
          char soak_s[201];
          snprintf(soak_s, sizeof(soak_s),
                   "b=%08X;h=%u/%u/%u/%u/%u/%u;mx=%s;lg=%s;gm=%u;lx=%u;wr=%u/%u/%u/%u;nc=%u;ncm=%u;xh=%u/%u;cs=%u/%u/%u",
                   (unsigned) id(supervision_boot_nonce),
                   (unsigned) id(failback_shadow_gap_b0), (unsigned) id(failback_shadow_gap_b1),
                   (unsigned) id(failback_shadow_gap_b2), (unsigned) id(failback_shadow_gap_b3),
                   (unsigned) id(failback_shadow_gap_b4), (unsigned) id(failback_shadow_gap_b5),
                   mx_s, lg_s, (unsigned) id(failback_shadow_gaps_missed), (unsigned) id(failback_shadow_ep),
                   (unsigned) id(failback_shadow_wr_fp), (unsigned) id(failback_shadow_wr_dump),
                   (unsigned) id(failback_shadow_wr_r244), (unsigned) id(failback_shadow_wr_prof),
                   (unsigned) id(failback_shadow_nc),
                   (unsigned) (ncm_v > 999999UL ? 999999UL : ncm_v),
                   (unsigned) (xh_y > 999999UL ? 999999UL : xh_y), (unsigned) (xh_u > 999999UL ? 999999UL : xh_u),
                   (unsigned) (cs_f > 999999UL ? 999999UL : cs_f), (unsigned) (cs_p > 999999UL ? 999999UL : cs_p),
                   (unsigned) (cs_o > 999999UL ? 999999UL : cs_o));
""")


# ---------------------------------------------------------------------------
# The edits, in application order: (name, region, before, after). A pair's `after` text must be unique in the changed firmware
# and its `before` text unique in the base firmware.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Edit:
    name: str
    region: str
    before: str
    after: str


def _globals_old() -> str:
    return _blk(r"""
  - id: failback_shadow_last_pub_soak_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  # ---------------------------------------------------------------------
  # Fallback Profile REVIEW (FB-B1) - RAM-only state of the read-only
""")


def _globals_new() -> str:
    old = _globals_old()
    head = old.split("  # ---------------------------------------------------------------------\n  # Fallback Profile REVIEW", 1)[0]
    return head + GLOBALS_BLOCK + "  # ---------------------------------------------------------------------\n  # Fallback Profile REVIEW (FB-B1) - RAM-only state of the read-only\n"


EDITS = (
    Edit("substitution", "substitutions: after ecco_failback_shadow_soak_publish_min_ms",
         '  ecco_failback_shadow_soak_publish_min_ms: "60000"\n\nesphome:\n',
         '  ecco_failback_shadow_soak_publish_min_ms: "60000"\n' + SUBSTITUTION_BLOCK + "\nesphome:\n"),
    Edit("includes", "esphome: includes (appended last)",
         "    - include/ecco_fallback_save.h\n\n  on_boot:\n",
         "    - include/ecco_fallback_save.h\n    - " + INCLUDE_ENTRY + "\n\n  on_boot:\n"),
    Edit("globals", "globals (after the FB-C1 state, before the FB-B1 state)", _globals_old(), _globals_new()),
    Edit("text_comment", "text_sensor: the FB-C1 comment above the five Failback Shadow sensors", TEXT_SENSOR_COMMENT_OLD,
         TEXT_SENSOR_COMMENT_NEW),
    Edit("lambda0", "interval (FB-C) lambda 0: the cache-age static asserts", LAMBDA0_OLD, LAMBDA0_NEW),
    Edit("first_tick", "interval (FB-C) tick: the first ready tick seeds the accumulator clock", FIRST_OLD, FIRST_NEW),
    Edit("evaluator", "interval (FB-C) tick: the FB-C2 evaluator block (step 4b)", EVAL_ANCHOR_OLD, EVAL_NEW),
    Edit("edge_freeze", "interval (FB-C) tick, E1: kind, frozen edge plan, bound profile identity", E1_OLD, E1_NEW),
    Edit("close", "interval (FB-C) tick, E4: close outcome and the would-latched flag", E4_OLD, E4_NEW),
    Edit("bookkeeping", "interval (FB-C) tick: verdict changes, would-refuse includes the latch", BOOK_OLD, BOOK_NEW),
    Edit("publish_state", "interval (FB-C) tick: State, Verdict and Inputs publication", PUB_OLD, PUB_NEW),
    Edit("episode_decl", "interval (FB-C) tick: Episode plan-field buffers", EP_OLD, EP_NEW),
    Edit("episode_fmt", "interval (FB-C) tick: Episode string with the plan fields", EP2_OLD, EP2_NEW),
    Edit("soak", "interval (FB-C) tick: Soak string (wr p, xh, cs)", SOAK_OLD, SOAK_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)
assert len(set(EDIT_NAMES)) == len(EDITS) == 14

# The FB-A reserved tokens this change adds to the firmware YAML (chain entry fbc2 declares the total): the header include entry, the
# substitution key and its uses, and every `ecco_failback_shadow::` / `ecco_fbcap::`-free qualified use.
BANNED_FW_ADDED = sum(len(_BANNED.findall(e.after)) - len(_BANNED.findall(e.before)) for e in EDITS)


def edit(name: str) -> Edit:
    return EDITS[EDIT_NAMES.index(name)]


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-C2 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def add_fbc2_text(text: str) -> str:
    """Applies FB-C2 to a firmware text that has none of it (generates the change; the suite's round trip). Every `before` must be
    unique and no `after` may already be present."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"FB-C2 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out


def pre_fbc2_firmware(text: str) -> str:
    """The firmware text with exactly FB-C2's edits undone (the exact-match reverter of chain entry fbc2). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the FB-B3 / S3
    firmware (main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"FB-C2 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out
