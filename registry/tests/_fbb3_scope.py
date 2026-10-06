"""FB-B3 Slice A (Live Match foundation: RAW_CACHE_EXT, the live write fence, B10) change scope: exactly what Slice A adds
to firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fbb2_scope.py (verbatim blocks held HERE as the single source of truth, exact (left, old, new, right)
hunks, a reverter that raises unless every hunk is present exactly once at its anchor). The chain entry `fbb3`
(registry/tests/_scope_chain.py) carries `pre_fbb3_firmware`: the current firmware text with exactly these edits removed, which
reproduces the FB-B2 firmware byte-for-byte (BASE_FW_SHA = the chain's fbb2 checkpoint). The older suites are anchored at their
own entry and revert fbb3 FIRST; none of them was re-hashed.

Slice A is seven PURE INSERTIONS and no replacement - not one pre-existing firmware line is modified:

  poll caches (RAW_CACHE_EXT, assigned ONLY inside the existing config poll response handlers; zero new Modbus operation)
    block_a        Block A on_response: `id(fbc_raw_230) = values[30];` next to the reg 232 cache line
    block_b        Block B on_response: fbc_raw_243 / 245 / 247 / 248 = values[2] / [4] / [6] / [7] next to the reg 279 cache line
    filled         Block B on_response: fbc_raw_filled, right after manual_config_raw_cache_valid
  declarations
    globals        10 RAM-only globals (six RAW_CACHE_EXT + the four fence scalars), every one `restore_value: no`
    text_sensor    the template text sensor `ECCO Fallback Profile Live Match` (B10), update_interval: never
  publication (RAM only, no Modbus, no NVS)
    boot_seed      the boot lambda publishes the B10 seed (UNKNOWN, ca=B)
    tick3          the third, appended lambda of the existing FB-B 10 s housekeeping interval: the write fence tick, then
                   live_match() over the profile mirror, the poll caches and the RAM legs, published only when the text changes

Nothing in the deployment manifest, the Home Assistant packages or the firmware's other YAML files changes.

Later slices of FB-B3 (HA package / dashboard) edit no firmware; if one ever does, this module's blocks and the chain checkpoint
are updated together (test_fallback_live_match.py proves every literal against the firmware).

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import _fbb3_ha_scope as ha

# main FB-B3 is based on (FB-B2 merged as PR #60).
BASE_COMMIT = "87e6151fa04a2cada568ef6c36a871a8ffcc7303"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML on main @ BASE_COMMIT: what pre_fbb3_firmware() must
# reproduce; equal to the chain's fbb2 checkpoint.
BASE_FW_SHA = "dd062d02310f3d28e0d5cfb1eb9dc398dd63cafee8b50669ea76f7bd48125f68"

_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")

# Every NEW repo file this slice adds (the chain entry's `added_files`; exact POSIX paths, no glob). Existing files it modifies
# (the firmware YAML, ecco_fallback_capture.h, fallback_capture.py, _scope_chain.py ...) are not declared anywhere.
ADDED_FILES = frozenset({
    "docs/architecture/fallback/FB_B3_HA_SLICE_NOTES.md",
    "docs/architecture/fallback/FB_B3_IMPLEMENTATION_NOTES.md",
    "home-assistant/packages/ecco_fallback_profile_actions.yaml",
    "home-assistant/packages/ecco_fallback_status.yaml",
    "home-assistant/tests/test_ecco_fallback_packages.py",
    "influxdb/ecco_influxdb_options_v1_3.yaml",
    "registry/tests/_fbb3_ha_scope.py",
    "registry/tests/_fbb3_scope.py",
    "registry/tests/test_fallback_ha_contract.py",
    "registry/tests/test_fallback_live_match.py",
})

# The ONLY files under home-assistant/ and deployment/ allowed to carry the FB-A reserved token `ecco_fallback` (frontend/ carries none;
# FALLBACK_PROFILE, FAILBACK_STATE and ecco_failback stay banned everywhere there). Exact paths, no directory exemption. The dashboard
# is already declared by the FB-B1 entry; the two HA suites carry the entity ids they assert on.
BANNED_FILES = frozenset({
    "deployment/ha-manifest.yaml",
    "home-assistant/dashboards/ecco_pro.yaml",
    "home-assistant/packages/ecco_fallback_profile_actions.yaml",
    "home-assistant/packages/ecco_fallback_status.yaml",
    "home-assistant/packages/ecco_system_health.yaml",
    "home-assistant/tests/test_ecco_fallback_packages.py",
    "home-assistant/tests/test_ecco_system_health_package.py",
})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# The deployment manifest is a chain-pinned artifact: its FB-B3 edits (exactly two package entries, the InfluxDB reference, the
# firmware-first note, the release stamp) are undone by the generated exact-match reverter of _fbb3_ha_scope.py.
pre_fbb3_manifest = ha.pre_fbb3_manifest
MANIFEST_BASE_SHA = ha.MANIFEST_BASE_SHA
MANIFEST_AFTER_SHA = ha.MANIFEST_AFTER_SHA


# ---------------------------------------------------------------------------
# Names (single source of truth for the suites)
# ---------------------------------------------------------------------------
RAW_CACHE_EXT_IDS = ("fbc_raw_230", "fbc_raw_243", "fbc_raw_245", "fbc_raw_247", "fbc_raw_248", "fbc_raw_filled")
FENCE_IDS = ("fallback_profile_live_fence_seq", "fallback_profile_live_edge_seq", "fallback_profile_live_writes_fp",
             "fallback_profile_live_fence_flags")
NEW_GLOBAL_IDS = RAW_CACHE_EXT_IDS + FENCE_IDS
LIVE_SCRIPT_ID = "fallback_profile_live_refresh"
TEXT_SENSOR_NAME = "ECCO Fallback Profile Live Match"
TEXT_SENSOR_ID = "fallback_profile_live_match_text"
# register -> (the poll handler, the index into that handler's `values`). Block A reads 200..240, Block B reads 241..293.
RAW_CACHE_EXT_SOURCES = {
    "fbc_raw_230": ("A", 230 - 200),
    "fbc_raw_243": ("B", 243 - 241),
    "fbc_raw_245": ("B", 245 - 241),
    "fbc_raw_247": ("B", 247 - 241),
    "fbc_raw_248": ("B", 248 - 241),
}


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


# ---------------------------------------------------------------------------
# The inserted blocks (raw firmware text, LF newlines)
# ---------------------------------------------------------------------------
GLOBALS_BLOCK = _blk(r"""
  # ---------------------------------------------------------------------
  # Fallback Profile LIVE MATCH (FB-B3 Slice A) - RAM-only state. Every
  # global below is restore_value: no and has a scalar type. Nothing here is a
  # durable record and nothing here is a write basis.
  #   fbc_raw_230/243/245/247/248  RAW_CACHE_EXT: the words of the existing
  #                       configuration poll that the manual_cfg_*_raw family
  #                       does not cache. Assigned ONLY by the Block A / Block B
  #                       response handlers; read ONLY by the Live Match tick
  #                       (and later by the Failback Shadow). They are kept
  #                       OUTSIDE the manual_cfg_*_raw family on purpose: that
  #                       family is read by writers.
  #   fbc_raw_filled      true once a poll in which Block A and Block B both
  #                       succeeded has filled them
  #   live_fence_seq      the write fence: the lowest cfg_block_b_response_
  #                       dispatch_seq whose cached data may be trusted after a
  #                       write / lease transition (dispatch_seq + 2 at the
  #                       moment of the transition)
  #   live_edge_seq       the lease subset of the fence (PAUSED, not UNKNOWN)
  #   live_writes_fp      the write-attempt fingerprint of the previous tick
  #   live_fence_flags    bit0 seeded, bit1 a lease domain was not clear
  # ---------------------------------------------------------------------
  - id: fbc_raw_230
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fbc_raw_243
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fbc_raw_245
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fbc_raw_247
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fbc_raw_248
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fbc_raw_filled
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_live_fence_seq
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_live_edge_seq
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_live_writes_fp
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_live_fence_flags
    type: uint8_t
    restore_value: no
    initial_value: '0'
""")

BLOCK_A_BLOCK = _blk(r"""
                        // FB-B3 RAW_CACHE_EXT: register 230 (values[30], the grid-charge current word published above) - RAM
                        // only, read by nothing but the Live Match tick. No new Modbus read.
                        id(fbc_raw_230) = values[30];
""")

BLOCK_B_BLOCK = _blk(r"""
                        // FB-B3 RAW_CACHE_EXT: registers 243 / 245 / 247 / 248 (values[2] / [4] / [6] / [7], already decoded
                        // below) - RAM only, read by nothing but the Live Match tick. No new Modbus read.
                        id(fbc_raw_243) = values[2];
                        id(fbc_raw_245) = values[4];
                        id(fbc_raw_247) = values[6];
                        id(fbc_raw_248) = values[7];
""")

FILLED_BLOCK = _blk(r"""
                        // FB-B3: RAW_CACHE_EXT is usable only after a poll in which Block A and Block B both succeeded.
                        id(fbc_raw_filled) = id(fbc_raw_filled) || id(configuration_block1_ok);
""")

TEXT_SENSOR_BLOCK = _blk(r"""
  # Fallback Profile LIVE MATCH (FB-B3 Slice A) - one read-only string (B10),
  # published only by the boot lambda (the UNKNOWN seed) and the Fallback
  # Profile 10 s housekeeping interval, and only when the text changes
  # (update_interval: never; no lambda, no filter).
  - platform: template
    name: "ECCO Fallback Profile Live Match"
    id: fallback_profile_live_match_text
    entity_category: diagnostic
    icon: "mdi:compare-horizontal"
    update_interval: never
""")

BOOT_SEED_BLOCK = _blk(r"""
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b10_seed_text();
            if (id(fallback_profile_live_match_text).state != t.c_str()) id(fallback_profile_live_match_text).publish_state(t.c_str());
          }
""")

TICK3_BLOCK = _blk(r"""
      - lambda: |-
          // FB-B3: the write fence and Live Match (B10) refresh - one synchronous RAM-only script, see its comment.
          id(fallback_profile_live_refresh).execute();
""")

LIVE_SCRIPT_BLOCK = _blk(r"""

  # Fallback Profile LIVE MATCH refresh (FB-B3) - ONE synchronous, lambda-only script (no wait, no delay, no Modbus, no
  # storage, no authority). It samples the write fence and recomputes + publishes B10 from the CURRENT effective state. It
  # is executed (a) by the 10 s housekeeping interval and (b) by every runtime path that publishes B1, immediately after
  # that publish, so B10 never lags the class B1 shows (S5 Part A A.3 item 9). Every other script and lambda is untouched.
  - id: fallback_profile_live_refresh
    mode: single
    then:
      - lambda: |-
          // FB-B3: (1) the live write fence, (2) Live Match (B10). RAM only: the only globals assigned are the four fence
          // scalars; the only entity published is the B10 text, and only when it changes.
          const uint32_t now = millis();
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
          gi.bus.fallback_profile_capture_dispatch_running = id(fallback_profile_capture_dispatch).is_running();
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
          gi.fp.run_start = id(start_free_power_override).is_running();
          gi.fp.run_restore = id(restore_free_power_snapshot).is_running() ||
                              id(restore_free_power_snapshot_dispatch).is_running();
          gi.fp.run_operator = id(free_power_recovery_review).is_running() ||
                               id(free_power_recovery_review_dispatch).is_running() ||
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
          // (1) the write fence
          ecco_fbcap::FenceState fs{};
          fs.seq = id(fallback_profile_live_fence_seq);
          fs.edge_seq = id(fallback_profile_live_edge_seq);
          fs.writes_fp = id(fallback_profile_live_writes_fp);
          fs.flags = id(fallback_profile_live_fence_flags);
          ecco_fbcap::FenceSample sample{};
          sample.bus_hot = ecco_fbcap::bus_busy(gi.bus);
          sample.lease_nonclear = ecco_fbcap::lease_domain_nonclear(gi) != ecco_fbcap::SLOT_NONE;
          sample.writes_fp = ecco_fbcap::writes_fingerprint((uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts),
                                                            (uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts),
                                                            (uint32_t) id(dump_start_attempts));
          sample.dispatch_seq = id(cfg_block_b_dispatch_seq);
          fs = ecco_fbcap::fence_tick(fs, sample);
          id(fallback_profile_live_fence_seq) = fs.seq;
          id(fallback_profile_live_edge_seq) = fs.edge_seq;
          id(fallback_profile_live_writes_fp) = fs.writes_fp;
          id(fallback_profile_live_fence_flags) = fs.flags;
          // (2) Live Match
          ecco_fbcap::LiveMatchInputs in{};
          in.g = gi;
          in.mtou_running = id(apply_manual_slot1).is_running() || id(apply_manual_slot2).is_running() ||
                            id(apply_manual_slot3).is_running() || id(apply_manual_slot4).is_running() ||
                            id(apply_manual_slot5).is_running() || id(apply_manual_slot6).is_running();
          in.cls = id(fallback_profile_class);
          in.write_outcome_unknown = id(fallback_profile_save_unconfirmed);
          in.read_anomaly = id(fallback_profile_read_anomaly);
          in.p_load = id(fallback_profile_load);
          in.p = ecco_fallback::decode_profile(id(fallback_profile_bytes));
          in.cache.cache_valid = id(manual_config_raw_cache_valid);
          in.cache.online = id(configuration_online).state;
          in.cache.polling = id(configuration_polling).state;
          in.cache.filled = id(fbc_raw_filled);
          in.cache.block_b_seq = id(cfg_block_b_seq);
          in.cache.block_b_ok_ms = id(cfg_block_b_ok_ms);
          in.cache.now_ms = now;
          in.cache.response_dispatch_seq = id(cfg_block_b_response_dispatch_seq);
          in.cache.fence_seq = fs.seq;
          in.edge_fence_seq = fs.edge_seq;
          in.live[0] = id(manual_cfg_reg244_raw);
          in.live[1] = id(manual_cfg_reg256_raw);
          in.live[2] = id(manual_cfg_reg257_raw);
          in.live[3] = id(manual_cfg_reg258_raw);
          in.live[4] = id(manual_cfg_reg259_raw);
          in.live[5] = id(manual_cfg_reg260_raw);
          in.live[6] = id(manual_cfg_reg261_raw);
          in.live[7] = id(manual_cfg_reg268_raw);
          in.live[8] = id(manual_cfg_reg269_raw);
          in.live[9] = id(manual_cfg_reg270_raw);
          in.live[10] = id(manual_cfg_reg271_raw);
          in.live[11] = id(manual_cfg_reg272_raw);
          in.live[12] = id(manual_cfg_reg273_raw);
          in.live[13] = id(manual_cfg_reg274_raw);
          in.live[14] = id(manual_cfg_reg275_raw);
          in.live[15] = id(manual_cfg_reg276_raw);
          in.live[16] = id(manual_cfg_reg277_raw);
          in.live[17] = id(manual_cfg_reg278_raw);
          in.live[18] = id(manual_cfg_reg279_raw);
          in.live[19] = id(manual_cfg_reg232_raw);
          in.live[20] = id(fbc_raw_243);
          in.live[21] = id(fbc_raw_248);
          in.live[22] = id(manual_cfg_reg250_raw);
          in.live[23] = id(manual_cfg_reg251_raw);
          in.live[24] = id(manual_cfg_reg252_raw);
          in.live[25] = id(manual_cfg_reg253_raw);
          in.live[26] = id(manual_cfg_reg254_raw);
          in.live[27] = id(manual_cfg_reg255_raw);
          in.live[28] = id(fbc_raw_230);
          in.live[29] = id(fbc_raw_245);
          in.live[30] = id(fbc_raw_247);
          in.dump_data_loaded = id(dump_snapshot_data_loaded);
          in.dump_snapshot_reg244 = id(dump_snapshot_reg244);
          in.dump_snapshot_reg256_261[0] = id(dump_snapshot_reg256);
          in.dump_snapshot_reg256_261[1] = id(dump_snapshot_reg257);
          in.dump_snapshot_reg256_261[2] = id(dump_snapshot_reg258);
          in.dump_snapshot_reg256_261[3] = id(dump_snapshot_reg259);
          in.dump_snapshot_reg256_261[4] = id(dump_snapshot_reg260);
          in.dump_snapshot_reg256_261[5] = id(dump_snapshot_reg261);
          in.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};
          const ecco_fbcap::LiveMatchResult lm = ecco_fbcap::live_match(in);
          // Torn-snapshot guard: Block A and Block B of one poll are 2.5 s apart, so while the configuration poll runs the
          // cached pair may mix two polls. Only a COMPARED verdict (MATCH / DRIFT / CONTEXT / EXPORT / OUT_OF_DOMAIN) depends on
          // that pair; it is held back for one tick. Every verdict that does not compare (NO_PROFILE, PAUSED, PAUSED_IO,
          // UNKNOWN) is published at once, so a class change can never leave a stale MATCH behind.
          if (lm.compared && id(poll_inverter_configuration_dispatch).is_running()) return;
          const ecco_fbcap::TextBuf t = ecco_fbcap::b10_text(lm);
          if (id(fallback_profile_live_match_text).state != t.c_str()) id(fallback_profile_live_match_text).publish_state(t.c_str());
""")


# ---------------------------------------------------------------------------
# The hunks. before = left + right (the FB-B2 text), after = left + new + right (the FB-B3 Slice A text).
# ---------------------------------------------------------------------------
ANCHORS = {
    "block_a": (
        "                        id(manual_cfg_reg232_raw) = values[32];\n",
        "\n                        id(ecco_force_generator).publish_state((values[34] & 0x0001) != 0);\n",
    ),
    "block_b": (
        "                        id(manual_cfg_reg279_raw) = values[38];\n",
        "\n                        // Diagnostic-only: publish the complete raw TOU flag words so\n",
    ),
    "filled": (
        "                        id(manual_config_raw_cache_valid) = id(configuration_block1_ok);\n",
        "\n                        // 2026-09-26 (Dump-to-Grid pre-live hardening):\n",
    ),
    "globals": (
        "  - id: fallback_profile_save_ctx_replace_corrupt\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n",
        '\nnumber:\n  - platform: template\n    name: "Clock Correction Threshold"\n',
    ),
    "text_sensor": (
        '  - platform: template\n    name: "ECCO Fallback Profile Last Action-Result"\n    id: fallback_profile_last_result_text\n'
        "    update_interval: never\n",
        "\nsensor:\n  - platform: wifi_signal\n",
    ),
    "boot_seed": (
        "          {\n            ecco_fbcap::TextBuf t = ecco_fbcap::b9_seed_text();\n"
        "            if (id(fallback_profile_last_result_text).state != t.c_str()) id(fallback_profile_last_result_text).publish_state(t.c_str());\n"
        "          }\n",
        '          ESP_LOGI("fbcap", "boot load: profile ld=%u witness ld=%u state ld=%u class=%u why=%u", (unsigned) lp, (unsigned) lw,\n',
    ),
    "tick3": (
        "            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;\n"
        "            id(fallback_profile_invalidate_candidate).execute();\n          }\n",
        "\n  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n",
    ),
    "live_script": (
        '          }\n          id(fallback_profile_invalidate_reason) = "";\n',
        "\n  # =====================================================================\n"
        "  # Fallback Profile SAVE / INVALIDATE (FB-B2) - the operator write flow.\n",
    ),
}


def _b1_refresh_block(indent: int) -> str:
    """The synchronous B10 refresh after a runtime B1 publish (the boot lambda seeds B10 itself)."""
    sp = " " * indent
    return (sp + "// FB-B3: Live Match (B10) follows the effective B1 state in the same lambda (no publication skew).\n"
            + sp + "id(fallback_profile_live_refresh).execute();\n")


def _b1_left(indent: int, expr: str) -> str:
    sp, sp2 = " " * indent, " " * (indent + 2)
    return (f"\n{sp}{{\n{sp2}const char *cls_name = ecco_fbcap::epc_name({expr});\n"
            f"{sp2}if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);\n{sp}}}\n")


def _b1_right(indent: int, args: str) -> str:
    sp, sp2 = " " * indent, " " * (indent + 2)
    return f"{sp}{{\n{sp2}ecco_fbcap::TextBuf t = ecco_fbcap::b2_text({args}"


# The five runtime paths that publish B1 (the effective class). Each executes the refresh script right after that publish, in the
# same lambda. (The boot lambda seeds B10 itself, fail closed, and marks the boot load complete last.)
B1_SITES = (
    # name, region, indent of the `{`, the epc_name argument, the first b2_text arguments of the NEXT block
    ("b1_review_final", "dispatch REVIEW_FINAL (REVIEW): B1 publish", 12, "eff_cls", "lp, p, lw, w, e.why,"),
    ("b1_save_early", "dispatch SAVE_FINAL part 1 (fresh read): B1 publish", 14,
     "ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed))", "lp, p, lw, w, e.why,"),
    ("b1_save_commit", "dispatch SAVE_FINAL part 2 (commit mirror): B1 publish", 16,
     "ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed))", "m.p_load, m.p, m.w_load, m.w, e2.why,"),
    ("b1_inv_fresh", "script fallback_profile_invalidate (fresh read): B1 publish", 12,
     "ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed))", "lp, p, lw, w, e.why,"),
    ("b1_inv_commit", "script fallback_profile_invalidate (commit mirror): B1 publish", 10,
     "ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed))", "m.p_load, m.p, m.w_load, m.w, e2.why,"),
)


@dataclass(frozen=True)
class Hunk:
    name: str
    region: str       # where in the firmware the edit sits
    left: str         # context before the edit (exact, unchanged lines only)
    new: str          # the inserted FB-B3 Slice A text
    right: str        # context after the edit (exact, unchanged lines only)

    @property
    def before(self) -> str:
        return self.left + self.right

    @property
    def after(self) -> str:
        return self.left + self.new + self.right


for _n, _r, _i, _e, _a in B1_SITES:
    ANCHORS[_n] = (_b1_left(_i, _e), _b1_right(_i, _a))


def _ins(name: str, region: str, new: str) -> Hunk:
    left, right = ANCHORS[name]
    return Hunk(name, region, left, new, right)


HUNKS = (
    _ins("block_a", "poll_inverter_configuration_dispatch Block A on_response: fbc_raw_230", BLOCK_A_BLOCK),
    _ins("block_b", "poll_inverter_configuration_dispatch Block B on_response: fbc_raw_243 / 245 / 247 / 248", BLOCK_B_BLOCK),
    _ins("filled", "poll_inverter_configuration_dispatch Block B on_response: fbc_raw_filled", FILLED_BLOCK),
    _ins("globals", "globals (after the FB-B2 SAVE state)", GLOBALS_BLOCK),
    _ins("text_sensor", "text_sensor (appended last, before sensor:)", TEXT_SENSOR_BLOCK),
    _ins("boot_seed", "on_boot[3] (FB-B1 boot lambda): the B10 seed, after the B9 seed", BOOT_SEED_BLOCK),
    _ins("tick3", "interval 10s: third appended housekeeping lambda (executes the refresh script)", TICK3_BLOCK),
    _ins("live_script", "script (after the FB-B1 scripts, before the FB-B2 SAVE / INVALIDATE scripts): fallback_profile_live_refresh (fence tick + Live Match)", LIVE_SCRIPT_BLOCK),
    *(_ins(n, r, _b1_refresh_block(i)) for n, r, i, _e, _a in B1_SITES),
)
HUNK_NAMES = tuple(h.name for h in HUNKS)
assert len(set(HUNK_NAMES)) == len(HUNKS) == 13


def hunk(name: str) -> Hunk:
    return HUNKS[HUNK_NAMES.index(name)]


# The FB-A reserved tokens this slice adds to the firmware YAML, per hunk (chain entry fbb3 declares the total).
BANNED_FW_BY_HUNK = {h.name: len(_BANNED.findall(h.new)) for h in HUNKS}
BANNED_FW_ADDED = sum(BANNED_FW_BY_HUNK.values())


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-B3 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def pre_fbb3_firmware(text: str) -> str:
    """The firmware text with exactly Slice A's seven insertions undone (the exact-match reverter of chain entry fbb3). Every
    hunk must occur exactly once, in place, else AssertionError; after the revert every base anchor must again be unique.
    Reproduces the FB-B2 firmware (main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for h in reversed(HUNKS):
        out = _swap(out, h.after, h.before, f"{h.name} hunk", "present")
    for h in HUNKS:
        n = out.count(h.before)
        if n != 1:
            raise AssertionError(f"FB-B3 scope: the {h.name} anchor must be unique once the hunk is removed, found {n}x")
    return out


def add_fbb3_text(text: str) -> str:
    """Applies Slice A to a firmware text that has none of it (generates the change; the suite's round trip). Every anchor must
    be unique and no hunk may already be present."""
    out = text
    for h in HUNKS:
        if h.after in out:
            raise AssertionError(f"FB-B3 scope: {h.name} hunk already present")
        out = _swap(out, h.before, h.after, f"{h.name} anchor", "found")
    return out
