"""FB-B1 (Review Current Configuration) change scope: exactly what FB-B1 adds to, and changes in,
firmware/ecco_clock_dongle_stage3_4_free_power.yaml and deployment/ha-manifest.yaml, and its exact inverse.

Same techniques as _fbc_scope.py (pure insertion blocks at unique anchors, the blocks held HERE as the single source of
truth) and _fbb_scope.py / _dump_v2_scope.py (exact (before, after) text pairs). Earlier suites pin the firmware YAML's
intervals, globals, text sensors, scripts, includes and on_boot lambda byte-for-byte as change-scope proofs. FB-B1
necessarily adds to those regions. Rather than re-pinning those suites to new hashes - which would silently widen what
they accept - they hash `pre_fbb1_firmware()` instead: the current firmware text with exactly FB-B1's edits removed.

FB-B1 edits the firmware in thirteen places (HUNKS, in file order). Ten are PURE INSERTIONS of one contiguous block each,
at a unique anchor:

  1. include            the `esphome: includes:` entry for the capture header (appended LAST)
  2. retention_fp       BLK-11: `id(free_power_marker_boot_load) = marker_load;` as the LAST statement of the Free Power
  3. retention_dump     marker block / the Dump marker block / the Reg244 marker block of on_boot lambda[0] (read-only
  4. retention_r244     retention of the boot load status; nothing above it depends on it)
  5. boot_lambda        the appended FOURTH on_boot item: the READ-ONLY boot load of the saved profile views
  6. globals            the RAM-only globals (every one `restore_value: no`; no header-defined type)
  7. text_sensors       the nine read-only strings B1-B9
  8. scripts            the three scripts (review gate, capture dispatch, RAM-only invalidate)
  9. button             the "Review Current Configuration" button
 10. interval           the 10 s RAM-only housekeeping interval, between the FP evidence-expiry interval and FB-C1's

and THREE are in-place REPLACEMENTS: the operator text published at boot when a recovery marker could not be read from
NVS (Dump, Free Power, Reg244) loses its advice to reboot (`REBOOT_TEXT_EDITS`; a reboot may make an unreadable record
read as absent). Those three lines are the ONLY pre-existing firmware lines FB-B1 modifies; every other pre-existing line
is byte-identical. The three texts sit inside SG-06's own edit strings, so test_sg06_boot_durable_read_fail_closed.py
reverts FB-B1 first (design decision D14); the retention lines never touch an SG-06 / Dump V2 `after` string.

registry/tests/test_fallback_capture_scope.py pins that the revert reproduces the FB-B1 base (BASE_FW_SHA = the chain's
fbb0 checkpoint) byte-for-byte, that every hunk occurs exactly once at its anchor, that the round trip is exact, and
checks the firmware against the tables below. Every step raises AssertionError unless a hunk is present exactly once at its
anchor, so any OTHER change still breaks the pins that hash this module's output.

The deployment manifest gets ONE `frontend_assets` stanza (`pre_fbb1_manifest`); nothing is deployed.

FB-T0 REGISTRATION: `pre_fbb1_firmware` / `pre_fbb1_manifest` are the reverters of chain entry `fbb1` in
registry/tests/_scope_chain.py (appended after fbb0). The chain records the post-FB-B1 checkpoints and FB-B1's exact
declarations, and the older suites - anchored at their own entries - revert it without being edited. This module imports
no other scope module and not _scope_chain (the chain imports it).

Regeneration: the block literals below are the verbatim text of the firmware. After ANY change to the firmware YAML or
the manifest stanza, update the affected literal here and re-pin the two chain checkpoints in _scope_chain.py.

No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# main FB-B1 is based on (FB-T0 #56, FB-C1 #57, FB-B0 #58 merged).
BASE_COMMIT = "4649465710bd19d88c9ec275cb59bb5aa626d61d"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
MANIFEST_REL = "deployment/ha-manifest.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML on main @ BASE_COMMIT: what pre_fbb1_firmware() must
# reproduce; equal to the chain's fbb0 checkpoint. Likewise the manifest, equal to the chain's root manifest hash.
BASE_FW_SHA = "a61709c3fe42a8da60e16652891888988d96254be9f37e844ab665543d8c5881"
BASE_MANIFEST_SHA = "d582beb6b3873109365c9d901f3c9dfe6c26033e7c11551814179c953412815f"

# The FB-A reserved tokens (restated: this module must not import the chain, where the same pattern lives as BANNED).
_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")
_INCLUDE_LINE = "    - {}\n"

# Every NEW repo file FB-B1 adds (the chain entry's `added_files`; exact POSIX paths, no glob). Existing files it modifies
# (firmware YAML, ha-manifest.yaml, ecco_pro.yaml, _dump_sim.py, _fbb_harness.py, _scope_chain.py, four older suites, ...)
# are not declared anywhere. test_fallback_capture_scope.py pins that this set is exactly what is on disk.
FRONTEND_CARD_FILES = (
    "frontend/ecco-fallback-recovery-card/README.md",
    "frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js",
    "frontend/ecco-fallback-recovery-card/hacs.json",
    "frontend/ecco-fallback-recovery-card/package.json",
    "frontend/ecco-fallback-recovery-card/preview/index.html",
    "frontend/ecco-fallback-recovery-card/test/check-b9.mjs",
    "frontend/ecco-fallback-recovery-card/test/check-obl.mjs",
    "frontend/ecco-fallback-recovery-card/test/core.test.mjs",
    "frontend/ecco-fallback-recovery-card/test/dom.test.mjs",
    "frontend/ecco-fallback-recovery-card/test/dump-strings.mjs",
    "frontend/ecco-fallback-recovery-card/test/element.test.mjs",
    "frontend/ecco-fallback-recovery-card/test/fixtures/scenario_meta.json",
    "frontend/ecco-fallback-recovery-card/test/fixtures/scenarios.json",
    "frontend/ecco-fallback-recovery-card/test/helpers.mjs",
    "frontend/ecco-fallback-recovery-card/test/minidom.mjs",
    "frontend/ecco-fallback-recovery-card/test/render.test.mjs",
)
ADDED_FILES = frozenset({
    "firmware/include/ecco_fallback_capture.h",
    "registry/fallback_capture.py",
    "registry/tests/_fbb1_engine.py",
    "registry/tests/_fbb1_fbcap.py",
    "registry/tests/_fbb1_fbcap_double.py",
    "registry/tests/_fbb1_lambda_compile.py",
    "registry/tests/_fbb1_scope.py",
    "registry/tests/_fbb1_types.py",
    "registry/tests/_fbb1_xpile.py",
    "registry/tests/test_fallback_capture_model.py",
    "registry/tests/test_fallback_capture_host_compile.py",
    "registry/tests/test_fallback_capture_harness.py",
    "registry/tests/test_fallback_capture_scope.py",
    "registry/tests/test_fallback_profile_capture.py",
    "registry/tests/test_fallback_recovery_dashboard.py",
    *FRONTEND_CARD_FILES,
})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Names (single source of truth for the suites; test_fallback_capture_scope.py cross-checks them against the
# parsed firmware and the inserted blocks)
# ---------------------------------------------------------------------------
# (id, C type, initial_value or None). Order is the order in the firmware: the three retention globals first (they
# are assigned inside on_boot lambda[0]), then the FB-B1 review state. Every one is `restore_value: no`.
GLOBALS = [
    ('free_power_marker_boot_load', 'uint8_t', '255'),
    ('dump_marker_boot_load', 'uint8_t', '255'),
    ('reg244_marker_boot_load', 'uint8_t', '255'),
    ('fallback_profile_boot_loaded', 'bool', 'false'),
    ('fallback_profile_boot_salt', 'uint32_t', '0'),
    ('fallback_profile_fbs_slot', 'uint8_t', '0'),
    ('fallback_profile_bytes', 'std::array<uint8_t, 96>', None),
    ('fallback_profile_load', 'uint8_t', '4'),
    ('fallback_profile_class', 'uint8_t', '0'),
    ('fallback_profile_why', 'uint8_t', '0'),
    ('fallback_witness_bytes', 'std::array<uint8_t, 48>', None),
    ('fallback_witness_load', 'uint8_t', '4'),
    ('fallback_profile_present_seen', 'uint8_t', '0'),
    ('fallback_profile_read_anomaly', 'uint8_t', '0'),
    ('fallback_profile_seen_hw_gen', 'uint32_t', '0'),
    ('fallback_profile_op_in_progress', 'bool', 'false'),
    ('fallback_profile_op_purpose', 'uint8_t', '0'),
    ('fallback_profile_op_started_ms', 'uint32_t', '0'),
    ('fallback_profile_capture_state', 'uint8_t', '0'),
    ('fallback_profile_gate_accepted', 'bool', 'false'),
    ('fallback_profile_step', 'uint8_t', '0'),
    ('fallback_profile_step_terminal', 'bool', 'false'),
    ('fallback_profile_read_failed', 'bool', 'false'),
    ('fallback_profile_read_fail_code', 'uint8_t', '0'),
    ('fallback_profile_read_exception_code', 'uint8_t', '0'),
    ('fallback_profile_pass1', 'std::array<uint16_t, 31>', None),
    ('fallback_profile_pass2', 'std::array<uint16_t, 31>', None),
    ('fallback_profile_probe_latch', 'uint16_t', '0'),
    ('fallback_profile_obl_text', 'std::string', '"-"'),
    ('fallback_profile_invalidate_reason', 'std::string', '""'),
    ('fallback_profile_cand_valid', 'bool', 'false'),
    ('fallback_profile_cand_saveable', 'bool', 'false'),
    ('fallback_profile_cand_words', 'std::array<uint16_t, 31>', None),
    ('fallback_profile_cand_id', 'uint64_t', '0'),
    ('fallback_profile_cand_ms', 'uint32_t', '0'),
    ('fallback_profile_cand_seq', 'uint32_t', '0'),
    ('fallback_profile_cand_prior_class', 'uint8_t', '0'),
    ('fallback_profile_cand_prior_gen', 'uint32_t', '0'),
    ('fallback_profile_cand_prior_binding', 'uint64_t', '0'),
    ('fallback_profile_cand_warnings', 'uint16_t', '0'),
    ('fallback_profile_cand_writes_fp', 'uint32_t', '0'),
    ('fallback_profile_cand_sv', 'std::string', '""'),
    ('fallback_profile_cand_dx', 'uint32_t', '0'),
    ('fallback_profile_cand_dc', 'uint16_t', '0'),
    ('fallback_profile_cand_di', 'uint8_t', '0'),
    ('fallback_profile_cand_has_stored', 'bool', 'false'),
]
NEW_GLOBAL_IDS = tuple(g[0] for g in GLOBALS)
RETENTION_GLOBAL_IDS = ("free_power_marker_boot_load", "dump_marker_boot_load", "reg244_marker_boot_load")

# (name, id, entity_category == diagnostic). All `platform: template`, `update_interval: never`, no lambda, no filter.
TEXT_SENSORS = [
    ('ECCO Fallback Profile State', 'fallback_profile_state_text', False),
    ('ECCO Fallback Profile Summary', 'fallback_profile_summary_text', True),
    ('ECCO Fallback Profile Review', 'fallback_profile_review_text', False),
    ('ECCO Fallback Profile Review ID', 'fallback_profile_review_id_text', False),
    ('ECCO Fallback Profile Review Slots', 'fallback_profile_review_slots_text', False),
    ('ECCO Fallback Profile Review Context', 'fallback_profile_review_context_text', False),
    ('ECCO Fallback Profile Slots', 'fallback_profile_slots_text', False),
    ('ECCO Fallback Profile Context', 'fallback_profile_context_text', False),
    ('ECCO Fallback Profile Last Action-Result', 'fallback_profile_last_result_text', False),
]
TEXT_IDS = tuple(t[1] for t in TEXT_SENSORS)

SCRIPT_IDS = ('fallback_profile_review', 'fallback_profile_capture_dispatch', 'fallback_profile_invalidate_candidate')
BUTTON_NAME = 'ECCO Fallback Profile: Review Current Configuration'
BUTTON_ID = 'fallback_profile_review_button'
BUTTON_ICON = 'mdi:file-search-outline'
# firmware id -> entity name for B1-B9 and B11 (the contract's table).
ENTITY_NAMES = {**{tid: name for name, tid, _d in TEXT_SENSORS}, BUTTON_ID: BUTTON_NAME}
HA_PREFIX = "ecco_clock_dongle_"


def ha_entity_id(domain: str, name: str) -> str:
    """Home Assistant entity id of a firmware entity: `<domain>.ecco_clock_dongle_<slug(name)>`, slug = lower-case,
    every run of non-alphanumerics -> `_` (text sensors are `sensor.`)."""
    return f"{domain}.{HA_PREFIX}{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"


HA_ENTITY_IDS = {**{tid: ha_entity_id("sensor", name) for name, tid, _d in TEXT_SENSORS},
                 BUTTON_ID: ha_entity_id("button", BUTTON_NAME)}

# ---------------------------------------------------------------------------
# The inserted blocks (raw firmware text, LF newlines)
# ---------------------------------------------------------------------------
def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


# Include list: the line is generated from ADDED_INCLUDES (never spelled out), like _fbb_scope.py.
ADDED_INCLUDES = ("include/ecco_fallback_capture.h",)
INCLUDE_BLOCK = "".join(_INCLUDE_LINE.format(i) for i in ADDED_INCLUDES)

# BLK-11 retention: ONE assignment per marker block, appended as the LAST statement of that block inside on_boot
# lambda[0]. `marker_load` is the block's own `uint8_t` local - the `ecco_durable::load_record_status()` result SG-06 added
# (0 OK, 1 ABSENT, 2 WRONG_SIZE, 3 READ_ERROR), already computed and used above; nothing above depends on the new line.
RETENTION_TEMPLATE = (
    '            // Review gate input: keep the boot load status of this marker (0 OK, 1 ABSENT,\n'
    '            // 2 WRONG_SIZE, 3 READ_ERROR). Read-only; nothing above depends on it.\n'
    '            id({var}) = marker_load;\n'
)
RETENTION_BLOCKS = tuple(RETENTION_TEMPLATE.format(var=v) for v in RETENTION_GLOBAL_IDS)

BOOT_BLOCK = _blk(r"""
      # Fallback Profile REVIEW (FB-B1): READ-ONLY boot load of the stored profile,
      # its witness and the failback state record, published as the saved view. Its
      # own lambda, appended after the HA heartbeat items on purpose: it has no
      # random seed and no compile-time check of its own. No Modbus, no write of
      # any kind, no retry of a read (a read may already have erased a damaged
      # entry). The LAST statement marks the load complete: the Review gate refuses
      # until then.
      - lambda: |-
          ecco_fbdurable::EspNvs nvs;
          ecco_fallback::FallbackProfileV1 p{};
          ecco_fbdurable::FailbackProvisionV1 w{};
          ecco_fallback::FailbackStateV1 s{};
          ecco_fbdurable::ReadDiag dp{};
          ecco_fbdurable::ReadDiag dw{};
          ecco_fbdurable::ReadDiag dfs{};
          const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);
          const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);
          const bool healthy = ecco_fbdurable::nvs_healthy();
          ecco_fbcap::ReadInputs in{};
          in.p_load = lp;
          in.p = p;
          in.w_load = lw;
          in.w = w;
          in.healthy = healthy;
          ecco_fbcap::ReadEval e = ecco_fbcap::evaluate_read(in);
          const uint8_t ls = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_STATE_KEY, s, dfs);
          id(fallback_profile_fbs_slot) = ecco_fbdurable::fbs_slot(ls, s);
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
            const char *cls_name = ecco_fbcap::epc_name(e.cls);
            if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);
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
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0, "-", 0, "-");
            if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b4_text(false, 0);
            if (id(fallback_profile_review_id_text).state != t.c_str()) id(fallback_profile_review_id_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b5_text(false, id(fallback_profile_cand_words), false, 0);
            if (id(fallback_profile_review_slots_text).state != t.c_str()) id(fallback_profile_review_slots_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b6_text(false, id(fallback_profile_cand_words), false, 0, 0);
            if (id(fallback_profile_review_context_text).state != t.c_str()) id(fallback_profile_review_context_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b9_seed_text();
            if (id(fallback_profile_last_result_text).state != t.c_str()) id(fallback_profile_last_result_text).publish_state(t.c_str());
          }
          ESP_LOGI("fbcap", "boot load: profile ld=%u witness ld=%u state ld=%u class=%u why=%u", (unsigned) lp, (unsigned) lw,
                   (unsigned) ls, (unsigned) e.cls, (unsigned) e.why);
          id(fallback_profile_boot_loaded) = true;
""")

GLOBALS_BLOCK = _blk(r"""
  # ---------------------------------------------------------------------
  # Fallback Profile REVIEW (FB-B1) - RAM-only state of the read-only
  # "Review Current Configuration" flow
  # (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md section 9).
  # Every global below is restore_value: no. None has a header-defined
  # type: esphome: includes: headers are emitted AFTER all globals, so the
  # state is scalars, std::string and std::array only, and the header's
  # POD structs are lambda locals. Nothing here is a durable record: the
  # profile / witness mirror is a read-only copy of what the boot read and
  # the last Review read saw; the three *_marker_boot_load values retain
  # the boot-time marker load status (0 OK, 1 ABSENT, 2 WRONG_SIZE,
  # 3 READ_ERROR; 255 = not loaded) assigned inside on_boot lambda[0].
  # ---------------------------------------------------------------------
  - id: free_power_marker_boot_load
    type: uint8_t
    restore_value: no
    initial_value: '255'
  - id: dump_marker_boot_load
    type: uint8_t
    restore_value: no
    initial_value: '255'
  - id: reg244_marker_boot_load
    type: uint8_t
    restore_value: no
    initial_value: '255'
  - id: fallback_profile_boot_loaded
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_boot_salt
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_fbs_slot
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_bytes
    type: std::array<uint8_t, 96>
    restore_value: no
  - id: fallback_profile_load
    type: uint8_t
    restore_value: no
    initial_value: '4'
  - id: fallback_profile_class
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_why
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_witness_bytes
    type: std::array<uint8_t, 48>
    restore_value: no
  - id: fallback_witness_load
    type: uint8_t
    restore_value: no
    initial_value: '4'
  - id: fallback_profile_present_seen
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_read_anomaly
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_seen_hw_gen
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_op_in_progress
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_op_purpose
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_op_started_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_capture_state
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_gate_accepted
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_step
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_step_terminal
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_read_failed
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_read_fail_code
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_read_exception_code
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_pass1
    type: std::array<uint16_t, 31>
    restore_value: no
  - id: fallback_profile_pass2
    type: std::array<uint16_t, 31>
    restore_value: no
  - id: fallback_profile_probe_latch
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_obl_text
    type: std::string
    restore_value: no
    initial_value: '"-"'
  - id: fallback_profile_invalidate_reason
    type: std::string
    restore_value: no
    initial_value: '""'
  - id: fallback_profile_cand_valid
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_cand_saveable
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: fallback_profile_cand_words
    type: std::array<uint16_t, 31>
    restore_value: no
  - id: fallback_profile_cand_id
    type: uint64_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_seq
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_prior_class
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_prior_gen
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_prior_binding
    type: uint64_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_warnings
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_writes_fp
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_sv
    type: std::string
    restore_value: no
    initial_value: '""'
  - id: fallback_profile_cand_dx
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_dc
    type: uint16_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_di
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: fallback_profile_cand_has_stored
    type: bool
    restore_value: no
    initial_value: 'false'
""")

TEXT_SENSORS_BLOCK = _blk(r"""
  # Fallback Profile REVIEW (FB-B1) - nine read-only strings, published only by
  # the Fallback Profile boot load, the Review scripts and the Review
  # housekeeping interval (update_interval: never; no lambda, no filter).
  # Home Assistant shows `unknown` until the boot lambda publishes them.
  - platform: template
    name: "ECCO Fallback Profile State"
    id: fallback_profile_state_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Summary"
    id: fallback_profile_summary_text
    entity_category: diagnostic
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Review"
    id: fallback_profile_review_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Review ID"
    id: fallback_profile_review_id_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Review Slots"
    id: fallback_profile_review_slots_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Review Context"
    id: fallback_profile_review_context_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Slots"
    id: fallback_profile_slots_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Context"
    id: fallback_profile_context_text
    update_interval: never
  - platform: template
    name: "ECCO Fallback Profile Last Action-Result"
    id: fallback_profile_last_result_text
    update_interval: never
""")

SCRIPTS_BLOCK = _blk(r"""
  # =====================================================================
  # Fallback Profile REVIEW (FB-B1) - read-only "Review Current Configuration"
  # (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md section 9,
  # design/S1_fbb_capture_final.md). Three scripts:
  #   fallback_profile_review                 synchronous gate (refusals take no lock)
  #   fallback_profile_capture_dispatch       idle wait, four distinct FC03 reads
  #                                           (230/3, 241/53, 230/3, 241/53), final
  #                                           step, ONE release lambda
  #   fallback_profile_invalidate_candidate   RAM-only candidate reset
  # NOTHING here writes the inverter or durable storage: zero Modbus writes, zero
  # NVS writes (the only durable access is read-only: direct reads of the
  # stored profile / witness and the three recovery markers).
  # =====================================================================
  # Gate. One synchronous lambda decides (V1 in flight, V2 booted, V3 write arms,
  # V4 bus, V5 failback record, V6 recovery domains, V7 marker probes); on accept it
  # takes the lock flags in that same lambda and then starts the dispatch.
  - id: fallback_profile_review
    mode: single
    then:
      - lambda: |-
          // Fallback Profile REVIEW gate (FB-B1). ONE synchronous lambda decides; a
          // refusal takes no lock and writes nothing but the RAM state and texts below.
          // V1: another Fallback Profile operation is in flight - touch nothing but the result text.
          if (id(fallback_profile_op_in_progress) || id(fallback_profile_capture_dispatch).is_running()) {
            ecco_fbcap::TextBuf busy = ecco_fbcap::refused_in_flight_text();
            if (id(fallback_profile_last_result_text).state != busy.c_str()) id(fallback_profile_last_result_text).publish_state(busy.c_str());
            return;
          }
          // IE3: a new Review supersedes any earlier candidate (its own outcome is not published).
          if (id(fallback_profile_cand_valid)) {
            id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED;
            id(fallback_profile_invalidate_candidate).execute();
          }
          // Per-boot salt of the candidate id, seeded lazily (never in on_boot).
          if (id(fallback_profile_boot_salt) == 0) id(fallback_profile_boot_salt) = random_uint32() | 1u;
          // Gather the RAM inputs of V2..V6 (no NVS access here).
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
          ecco_fbcap::GateResult r = ecco_fbcap::gate_decide(gi, pr);
          if (r.code == ecco_fbcap::GATE_NEED_PROBE) {
            // V7: every other slot is clear - read each flagged lease marker ONCE (direct,
            // read-only, never retried). A bad marker is latched by the second decision and
            // is never probed again in this boot.
            ecco_fbdurable::EspNvs nvs;
            if (r.probe_fp) {
              ecco_durable::ValidMarker m{};
              ecco_fbdurable::ReadDiag d{};
              const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), m, d);
              pr.fp = ecco_fbcap::probe_result(ld, m.magic, m.state);
            }
            if (r.probe_dump) {
              ecco_durable::ValidMarker m{};
              ecco_fbdurable::ReadDiag d{};
              const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), m, d);
              pr.dump = ecco_fbcap::probe_result(ld, m.magic, m.state);
            }
            if (r.probe_r244) {
              ecco_durable::ValidMarker m{};
              ecco_fbdurable::ReadDiag d{};
              const uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), m, d);
              pr.r244 = ecco_fbcap::probe_result(ld, m.magic, m.state);
            }
            r = ecco_fbcap::gate_decide(gi, pr);
          }
          id(fallback_profile_probe_latch) = r.latch;
          id(fallback_profile_obl_text) = r.obl.c_str();
          if (r.code == ecco_fbcap::GATE_ACCEPT) {
            // Accept: the lock flags are taken in THIS lambda, before the dispatch is started.
            id(fallback_profile_op_in_progress) = true;
            id(manual_write_in_progress) = true;
            id(fallback_profile_op_purpose) = ecco_fbcap::PURPOSE_REVIEW;
            id(fallback_profile_op_started_ms) = millis();
            id(fallback_profile_step) = 0;
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_READING;
            id(fallback_profile_gate_accepted) = true;
            ESP_LOGI("fbcap", "review accepted: bus idle wait, then four read passes");
          } else {
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
            ESP_LOGI("fbcap", "review refused: code=%u slot=%u", (unsigned) r.code, (unsigned) r.slot);
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), false, 0, 0, 0,
                                                        id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
            if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::review_in_progress_text();
            if (r.code != ecco_fbcap::GATE_ACCEPT) t = r.text;
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

  # Dispatch. Holds the shared write mutex taken by the gate. Waits (bounded) for the
  # poll scripts and the bus to go idle, then issues FOUR distinct read nodes in
  # order, each nested in `if: !read_failed` (fail fast), each with all five reply
  # outcomes handled and a 3 s bounded wait; then the final step; then ONE release.
  - id: fallback_profile_capture_dispatch
    mode: single
    then:
      - lambda: |-
          id(fallback_profile_step) = 0;
          id(fallback_profile_step_terminal) = false;
          id(fallback_profile_read_failed) = false;
          id(fallback_profile_read_fail_code) = 0;
          id(fallback_profile_read_exception_code) = 0;
          id(fallback_profile_pass1) = std::array<uint16_t, 31>{};
          id(fallback_profile_pass2) = std::array<uint16_t, 31>{};
      - wait_until:
          condition:
            lambda: 'return !id(poll_inverter_configuration_dispatch).is_running() && !id(poll_inverter_telemetry).is_running() && id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();'
          timeout: 7000ms
      - lambda: |-
          if (id(poll_inverter_configuration_dispatch).is_running() || id(poll_inverter_telemetry).is_running() ||
              !id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked()) {
            id(fallback_profile_read_failed) = true;
            id(fallback_profile_read_fail_code) = ecco_fbcap::READ_IDLE_TIMEOUT;
          }
      - if:
          condition:
            lambda: 'return !id(fallback_profile_read_failed);'
          then:
            - lambda: |-
                id(fallback_profile_step) = 1;
                id(fallback_profile_step_terminal) = false;
            - modbus_client.read_holding_registers:
                modbus_id: inverter_modbus
                address: 0x01
                start_address: 230
                count: 3
                on_response:
                  then:
                    - lambda: |-
                        if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;
                        id(fallback_profile_step_terminal) = true;
                        if (!ecco_fbcap::store_block_230(id(fallback_profile_pass1), values)) {
                          id(fallback_profile_read_failed) = true;
                          id(fallback_profile_read_fail_code) = ecco_fbcap::READ_SHORT;
                        }
                on_error:
                  then:
                    - lambda: |-
                        if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;
                        id(fallback_profile_step_terminal) = true;
                        id(fallback_profile_read_failed) = true;
                        id(fallback_profile_read_fail_code) = ecco_fbcap::READ_EXCEPTION;
                        id(fallback_profile_read_exception_code) = (uint8_t) exception_code;
                on_no_response:
                  then:
                    - lambda: |-
                        if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;
                        id(fallback_profile_step_terminal) = true;
                        id(fallback_profile_read_failed) = true;
                        id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;
                on_not_sent:
                  then:
                    - lambda: |-
                        if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;
                        id(fallback_profile_step_terminal) = true;
                        id(fallback_profile_read_failed) = true;
                        id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NOT_SENT;
                on_custom_response:
                  then:
                    - lambda: |-
                        if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 1) return;
                        id(fallback_profile_step_terminal) = true;
                        id(fallback_profile_read_failed) = true;
                        id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NONSTANDARD;
            - wait_until:
                condition:
                  lambda: 'return id(fallback_profile_step_terminal);'
                timeout: 3000ms
            - lambda: |-
                if (!id(fallback_profile_step_terminal)) {
                  id(fallback_profile_read_failed) = true;
                  id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT;
                }
            - if:
                condition:
                  lambda: 'return !id(fallback_profile_read_failed);'
                then:
                  - lambda: |-
                      id(fallback_profile_step) = 2;
                      id(fallback_profile_step_terminal) = false;
                  - modbus_client.read_holding_registers:
                      modbus_id: inverter_modbus
                      address: 0x01
                      start_address: 241
                      count: 53
                      on_response:
                        then:
                          - lambda: |-
                              if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 2) return;
                              id(fallback_profile_step_terminal) = true;
                              if (!ecco_fbcap::store_block_241(id(fallback_profile_pass1), values)) {
                                id(fallback_profile_read_failed) = true;
                                id(fallback_profile_read_fail_code) = ecco_fbcap::READ_SHORT;
                              }
                      on_error:
                        then:
                          - lambda: |-
                              if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 2) return;
                              id(fallback_profile_step_terminal) = true;
                              id(fallback_profile_read_failed) = true;
                              id(fallback_profile_read_fail_code) = ecco_fbcap::READ_EXCEPTION;
                              id(fallback_profile_read_exception_code) = (uint8_t) exception_code;
                      on_no_response:
                        then:
                          - lambda: |-
                              if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 2) return;
                              id(fallback_profile_step_terminal) = true;
                              id(fallback_profile_read_failed) = true;
                              id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;
                      on_not_sent:
                        then:
                          - lambda: |-
                              if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 2) return;
                              id(fallback_profile_step_terminal) = true;
                              id(fallback_profile_read_failed) = true;
                              id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NOT_SENT;
                      on_custom_response:
                        then:
                          - lambda: |-
                              if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 2) return;
                              id(fallback_profile_step_terminal) = true;
                              id(fallback_profile_read_failed) = true;
                              id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NONSTANDARD;
                  - wait_until:
                      condition:
                        lambda: 'return id(fallback_profile_step_terminal);'
                      timeout: 3000ms
                  - lambda: |-
                      if (!id(fallback_profile_step_terminal)) {
                        id(fallback_profile_read_failed) = true;
                        id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT;
                      }
                  - if:
                      condition:
                        lambda: 'return !id(fallback_profile_read_failed);'
                      then:
                        - lambda: |-
                            id(fallback_profile_step) = 3;
                            id(fallback_profile_step_terminal) = false;
                        - modbus_client.read_holding_registers:
                            modbus_id: inverter_modbus
                            address: 0x01
                            start_address: 230
                            count: 3
                            on_response:
                              then:
                                - lambda: |-
                                    if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 3) return;
                                    id(fallback_profile_step_terminal) = true;
                                    if (!ecco_fbcap::store_block_230(id(fallback_profile_pass2), values)) {
                                      id(fallback_profile_read_failed) = true;
                                      id(fallback_profile_read_fail_code) = ecco_fbcap::READ_SHORT;
                                    }
                            on_error:
                              then:
                                - lambda: |-
                                    if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 3) return;
                                    id(fallback_profile_step_terminal) = true;
                                    id(fallback_profile_read_failed) = true;
                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_EXCEPTION;
                                    id(fallback_profile_read_exception_code) = (uint8_t) exception_code;
                            on_no_response:
                              then:
                                - lambda: |-
                                    if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 3) return;
                                    id(fallback_profile_step_terminal) = true;
                                    id(fallback_profile_read_failed) = true;
                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;
                            on_not_sent:
                              then:
                                - lambda: |-
                                    if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 3) return;
                                    id(fallback_profile_step_terminal) = true;
                                    id(fallback_profile_read_failed) = true;
                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NOT_SENT;
                            on_custom_response:
                              then:
                                - lambda: |-
                                    if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 3) return;
                                    id(fallback_profile_step_terminal) = true;
                                    id(fallback_profile_read_failed) = true;
                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NONSTANDARD;
                        - wait_until:
                            condition:
                              lambda: 'return id(fallback_profile_step_terminal);'
                            timeout: 3000ms
                        - lambda: |-
                            if (!id(fallback_profile_step_terminal)) {
                              id(fallback_profile_read_failed) = true;
                              id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT;
                            }
                        - if:
                            condition:
                              lambda: 'return !id(fallback_profile_read_failed);'
                            then:
                              - lambda: |-
                                  id(fallback_profile_step) = 4;
                                  id(fallback_profile_step_terminal) = false;
                              - modbus_client.read_holding_registers:
                                  modbus_id: inverter_modbus
                                  address: 0x01
                                  start_address: 241
                                  count: 53
                                  on_response:
                                    then:
                                      - lambda: |-
                                          if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 4) return;
                                          id(fallback_profile_step_terminal) = true;
                                          if (!ecco_fbcap::store_block_241(id(fallback_profile_pass2), values)) {
                                            id(fallback_profile_read_failed) = true;
                                            id(fallback_profile_read_fail_code) = ecco_fbcap::READ_SHORT;
                                          }
                                  on_error:
                                    then:
                                      - lambda: |-
                                          if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 4) return;
                                          id(fallback_profile_step_terminal) = true;
                                          id(fallback_profile_read_failed) = true;
                                          id(fallback_profile_read_fail_code) = ecco_fbcap::READ_EXCEPTION;
                                          id(fallback_profile_read_exception_code) = (uint8_t) exception_code;
                                  on_no_response:
                                    then:
                                      - lambda: |-
                                          if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 4) return;
                                          id(fallback_profile_step_terminal) = true;
                                          id(fallback_profile_read_failed) = true;
                                          id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NO_RESPONSE;
                                  on_not_sent:
                                    then:
                                      - lambda: |-
                                          if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 4) return;
                                          id(fallback_profile_step_terminal) = true;
                                          id(fallback_profile_read_failed) = true;
                                          id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NOT_SENT;
                                  on_custom_response:
                                    then:
                                      - lambda: |-
                                          if (!id(fallback_profile_op_in_progress) || id(fallback_profile_step) != 4) return;
                                          id(fallback_profile_step_terminal) = true;
                                          id(fallback_profile_read_failed) = true;
                                          id(fallback_profile_read_fail_code) = ecco_fbcap::READ_NONSTANDARD;
                              - wait_until:
                                  condition:
                                    lambda: 'return id(fallback_profile_step_terminal);'
                                  timeout: 3000ms
                              - lambda: |-
                                  if (!id(fallback_profile_step_terminal)) {
                                    id(fallback_profile_read_failed) = true;
                                    id(fallback_profile_read_fail_code) = ecco_fbcap::READ_BOUNDED_WAIT;
                                  }
      - lambda: |-
          // REVIEW final step: integrity check first, then the read-failure / pass-compare
          // outcomes, then (both passes agree on all 31 words) a fresh read-only look at
          // the stored profile + witness and a RAM-only candidate. No write of any kind.
          if (!ecco_fbcap::review_integrity_ok(id(fallback_profile_op_in_progress), id(fallback_profile_op_purpose))) {
            ecco_fbcap::TextBuf bad = ecco_fbcap::internal_context_text();
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
            {
              ecco_fbcap::TextBuf idle0 = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,
                                                              id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
              if (id(fallback_profile_review_text).state != idle0.c_str()) id(fallback_profile_review_text).publish_state(idle0.c_str());
            }
            if (id(fallback_profile_last_result_text).state != bad.c_str()) id(fallback_profile_last_result_text).publish_state(bad.c_str());
            return;
          }
          ecco_fbcap::TextBuf res{};
          bool built = false;
          if (id(fallback_profile_read_failed)) {
            res = ecco_fbcap::read_fail_text(id(fallback_profile_read_fail_code), id(fallback_profile_step),
                                             id(fallback_profile_read_exception_code));
          } else if (ecco_fbcap::first_diff(id(fallback_profile_pass1), id(fallback_profile_pass2)) >= 0) {
            res = ecco_fbcap::pass_mismatch_text(id(fallback_profile_pass1), id(fallback_profile_pass2));
          } else {
            // Fresh FBP + FBW read: two direct reads, ONE health check, then the latch notes,
            // the same-boot divergence rule against the RAM mirror and the RE-composed class.
            ecco_fbdurable::EspNvs nvs;
            ecco_fallback::FallbackProfileV1 p{};
            ecco_fbdurable::FailbackProvisionV1 w{};
            ecco_fbdurable::ReadDiag dp{};
            ecco_fbdurable::ReadDiag dw{};
            const uint8_t lp = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);
            const uint8_t lw = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);
            const bool healthy = ecco_fbdurable::nvs_healthy();
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
            ecco_fbcap::ReadEval e = ecco_fbcap::evaluate_read(in);
            // Latest authoritative read wins: mirror first, publishes after.
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
              const char *cls_name = ecco_fbcap::epc_name(e.cls);
              if (id(fallback_profile_state_text).state != cls_name) id(fallback_profile_state_text).publish_state(cls_name);
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);
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
            // Verdict on pass 2: L2 refusals + warnings, eligibility, prior fingerprint, masks, candidate id.
            ecco_fbcap::ReviewInputs ri{};
            ri.words = id(fallback_profile_pass2);
            ri.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};
            ri.cls = e.cls;
            ri.read_anomaly = e.latch.read_anomaly;
            ri.p_load = lp;
            ri.p = p;
            ri.p_stored_len = dp.stored_len;
            ri.salt = id(fallback_profile_boot_salt);
            ri.seq_next = id(fallback_profile_cand_seq) + 1;
            ecco_fbcap::ReviewVerdict v = ecco_fbcap::review_evaluate(ri);
            id(fallback_profile_cand_words) = id(fallback_profile_pass2);
            id(fallback_profile_cand_id) = v.id;
            id(fallback_profile_cand_prior_class) = e.cls;
            id(fallback_profile_cand_prior_gen) = v.prior_generation;
            id(fallback_profile_cand_prior_binding) = v.prior_binding;
            id(fallback_profile_cand_warnings) = v.warnings;
            id(fallback_profile_cand_sv) = v.sv.c_str();
            id(fallback_profile_cand_dx) = v.dx;
            id(fallback_profile_cand_dc) = v.dc;
            id(fallback_profile_cand_di) = v.di;
            id(fallback_profile_cand_has_stored) = v.has_stored;
            id(fallback_profile_cand_saveable) = v.eligible;
            id(fallback_profile_cand_ms) = millis();
            id(fallback_profile_cand_writes_fp) = ecco_fbcap::writes_fingerprint(
                (uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts),
                (uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts),
                (uint32_t) id(dump_start_attempts));
            if (v.eligible) id(fallback_profile_cand_seq) = ri.seq_next;
            id(fallback_profile_cand_valid) = true;
            id(fallback_profile_capture_state) = v.eligible ? ecco_fbcap::CAPTURE_CANDIDATE_READY
                                                             : ecco_fbcap::CAPTURE_CANDIDATE_NOT_SAVEABLE;
            built = true;
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, e.cls,
                                                          ecco_fbcap::exp_seconds(millis(), id(fallback_profile_cand_ms)), v.warnings,
                                                          id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch),
                                                          v.sv.c_str());
              if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b4_text(v.eligible, v.id);
              if (id(fallback_profile_review_id_text).state != t.c_str()) id(fallback_profile_review_id_text).publish_state(t.c_str());
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b5_text(true, id(fallback_profile_pass2), v.has_stored, v.dx);
              if (id(fallback_profile_review_slots_text).state != t.c_str()) id(fallback_profile_review_slots_text).publish_state(t.c_str());
            }
            {
              ecco_fbcap::TextBuf t = ecco_fbcap::b6_text(true, id(fallback_profile_pass2), v.has_stored, v.dc, v.di);
              if (id(fallback_profile_review_context_text).state != t.c_str()) id(fallback_profile_review_context_text).publish_state(t.c_str());
            }
            if (v.eligible) {
              res = ecco_fbcap::candidate_ready_text();
            } else {
              res = ecco_fbcap::not_saveable_text(v.refusals, id(fallback_profile_pass2), e.cls, e.latch.read_anomaly);
            }
          }
          if (!built) {
            // No candidate: leave the READING state and show the idle form (vector and latch persist).
            id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
            {
              ecco_fbcap::TextBuf idle1 = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,
                                                              id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
              if (id(fallback_profile_review_text).state != idle1.c_str()) id(fallback_profile_review_text).publish_state(idle1.c_str());
            }
            ESP_LOGI("fbcap", "review not completed: read-fail code=%u step=%u after %u ms", (unsigned) id(fallback_profile_read_fail_code),
                     (unsigned) id(fallback_profile_step), (unsigned) (uint32_t) (millis() - id(fallback_profile_op_started_ms)));
          }
          if (id(fallback_profile_last_result_text).state != res.c_str()) id(fallback_profile_last_result_text).publish_state(res.c_str());
          ESP_LOGI("fbcap", "review done: eligible=%u built=%u in %u ms", (unsigned) (built && id(fallback_profile_cand_saveable)),
                   (unsigned) built, (unsigned) (uint32_t) (millis() - id(fallback_profile_op_started_ms)));
      - lambda: |-
          // The single release point, reached on every path of this script.
          id(fallback_profile_op_in_progress) = false;
          id(manual_write_in_progress) = false;
          id(fallback_profile_step) = 0;
          id(fallback_profile_op_purpose) = 0;

  # Candidate reset (RAM only). Callers set fallback_profile_invalidate_reason first;
  # it holds the finished outcome text, and only a non-empty reason that is not a
  # "superseded" one is published. Never touches anything while a Review is running.
  - id: fallback_profile_invalidate_candidate
    mode: single
    then:
      - lambda: |-
          if (id(fallback_profile_op_in_progress)) return;
          id(fallback_profile_cand_valid) = false;
          id(fallback_profile_cand_saveable) = false;
          id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_IDLE;
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(ecco_fbcap::CAPTURE_IDLE, false, 0, 0, 0,
                                                        id(fallback_profile_obl_text).c_str(), id(fallback_profile_probe_latch), "-");
            if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b4_text(false, 0);
            if (id(fallback_profile_review_id_text).state != t.c_str()) id(fallback_profile_review_id_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b5_text(false, id(fallback_profile_cand_words), false, 0);
            if (id(fallback_profile_review_slots_text).state != t.c_str()) id(fallback_profile_review_slots_text).publish_state(t.c_str());
          }
          {
            ecco_fbcap::TextBuf t = ecco_fbcap::b6_text(false, id(fallback_profile_cand_words), false, 0, 0);
            if (id(fallback_profile_review_context_text).state != t.c_str()) id(fallback_profile_review_context_text).publish_state(t.c_str());
          }
          if (ecco_fbcap::invalidate_reason_publishes(id(fallback_profile_invalidate_reason).c_str())) {
            if (id(fallback_profile_last_result_text).state != id(fallback_profile_invalidate_reason))
              id(fallback_profile_last_result_text).publish_state(id(fallback_profile_invalidate_reason));
          }
          id(fallback_profile_invalidate_reason) = "";

""")

BUTTON_BLOCK = _blk(r"""
  # Fallback Profile REVIEW (FB-B1): read-only "Review Current Configuration".
  # The gate script refuses unless the bus and every recovery domain are clear;
  # it never writes the inverter and never writes durable storage.
  - platform: template
    name: "ECCO Fallback Profile: Review Current Configuration"
    id: fallback_profile_review_button
    icon: "mdi:file-search-outline"
    on_press:
      - script.execute:
          id: fallback_profile_review

""")

INTERVAL_BLOCK = _blk(r"""
  # Fallback Profile REVIEW (FB-B1) - RAM-only housekeeping. Runs every 10 s and
  # touches nothing but this feature's own RAM state and texts: no Modbus I/O, no
  # durable (NVS) access of any kind. In order: the leak breaker (clears ONLY the
  # Review's own flag, never the shared write mutex), the 120 s candidate
  # lifetime (so a candidate can outlive its TTL by up to one tick), invalidation
  # when a recovery domain turned non-clear or another ECCO write was admitted
  # since the Review, and the publish-on-change refresh of the remaining-time
  # field. Placed immediately after the Free Power evidence-expiry interval and
  # before the Failback Shadow interval: never the last interval.
  - interval: 10s
    then:
      - lambda: |-
          const uint32_t now = millis();
          // 1. Leak breaker: an operation flag with no running dispatch for more than 30 s.
          //    Clears ONLY this feature's own state; the shared write mutex is read, never assigned.
          if (ecco_fbcap::breaker_fired(id(fallback_profile_op_in_progress), id(fallback_profile_capture_dispatch).is_running(),
                                        now, id(fallback_profile_op_started_ms))) {
            const bool lock_held = id(manual_write_in_progress);
            id(fallback_profile_op_in_progress) = false;
            id(fallback_profile_op_purpose) = 0;
            id(fallback_profile_step) = 0;
            ecco_fbcap::TextBuf brk = ecco_fbcap::breaker_text(lock_held);
            id(fallback_profile_invalidate_reason) = brk.c_str();
            id(fallback_profile_invalidate_candidate).execute();
            ESP_LOGW("fbcap", "Review operation state reset by the housekeeping breaker (write lock held: %d)", (int) lock_held);
          }
          // 2. Candidate lifetime, recovery-domain change, another write admitted, remaining-time refresh.
          if (id(fallback_profile_cand_valid) && !id(fallback_profile_op_in_progress)) {
            if (ecco_fbcap::candidate_expired(now, id(fallback_profile_cand_ms))) {
              ecco_fbcap::TextBuf why = ecco_fbcap::review_expired_text();
              id(fallback_profile_invalidate_reason) = why.c_str();
              id(fallback_profile_invalidate_candidate).execute();
            } else {
              ecco_fbcap::GateInputs gi{};
              gi.boot_loaded = id(fallback_profile_boot_loaded);
              gi.probe_latch = id(fallback_profile_probe_latch);
              // Same sampling as the gate, except that the Free Power Force Restore pair is not
              // named here: a running one is carried by the in-progress flags in gi.bus.
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
              const uint8_t dom = ecco_fbcap::lease_domain_nonclear(gi);
              if (dom != ecco_fbcap::SLOT_NONE) {
                ecco_fbcap::TextBuf why = ecco_fbcap::review_cleared_domain_text(dom);
                id(fallback_profile_invalidate_reason) = why.c_str();
                id(fallback_profile_invalidate_candidate).execute();
              } else if (ecco_fbcap::writes_fingerprint((uint32_t) id(manual_write_attempts), (uint32_t) id(reg244_apply_attempts),
                                                        (uint32_t) id(reg244_restore_attempts), (uint32_t) id(free_power_start_attempts),
                                                        (uint32_t) id(dump_start_attempts)) != id(fallback_profile_cand_writes_fp)) {
                ecco_fbcap::TextBuf why = ecco_fbcap::review_cleared_writes_text();
                id(fallback_profile_invalidate_reason) = why.c_str();
                id(fallback_profile_invalidate_candidate).execute();
              } else {
                ecco_fbcap::TextBuf t = ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, id(fallback_profile_cand_prior_class),
                                                            ecco_fbcap::exp_seconds(now, id(fallback_profile_cand_ms)),
                                                            id(fallback_profile_cand_warnings), id(fallback_profile_obl_text).c_str(),
                                                            id(fallback_profile_probe_latch), id(fallback_profile_cand_sv).c_str());
                if (id(fallback_profile_review_text).state != t.c_str()) id(fallback_profile_review_text).publish_state(t.c_str());
              }
            }
          }

""")

BUTTON = BUTTON_BLOCK

# Home Assistant manifest: one `frontend_assets` stanza (the Fallback / Recovery card; nothing is deployed).
MANIFEST_STANZA = _blk(r"""
  # Fallback / Recovery card - FB-B1 (read-only review of the inverter fallback-profile
  # registers). NOT deployed: listed for the deploy tooling only; copying the file and
  # registering the resource stay deliberate manual steps. A single dependency-free ES
  # module (no dist build step).
  - source: frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js
    destination: /config/www/ecco/ecco-fallback-recovery-card.js
    method: ssh_file_copy
    restart_required: false
    resource_registration: manual
    resource_url: /local/ecco/ecco-fallback-recovery-card.js
""")

# ---------------------------------------------------------------------------
# The three operator texts FB-B1 rewords (the ONLY pre-existing firmware lines it modifies): the unreadable-marker
# status published at boot no longer advises a reboot (a reboot may make an unreadable record read as absent).
# Each entry is the COMPLETE original line; the new line is the same line with the tail swapped.
# ---------------------------------------------------------------------------
REBOOT_OLD_TAIL = ' - reboot to re-read'
REBOOT_NEW_TAIL = ' - do NOT reboot: a reboot may make the record read as absent'
REBOOT_TEXT_LINES = (
    '              id(dump_status).publish_state("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; writes locked, export containment not armed - reboot to re-read");',
    '              id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - reboot to re-read");',
    '                "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); inverter writes locked - reboot to re-read"',
)
REBOOT_TEXT_EDITS = tuple((ln, ln.replace(REBOOT_OLD_TAIL, REBOOT_NEW_TAIL)) for ln in REBOOT_TEXT_LINES)


# Context anchors (left, right) of each pure-insertion hunk. left + right must occur exactly once in the firmware
# WITHOUT the block, left + block + right exactly once WITH it (test_fallback_capture_scope.py pins both).
ANCHORS = {
    'include': (
        '    - include/ecco_fallback_durable.h\n',
        '\n  on_boot:\n',
    ),
    'retention_fp': (
        '            }\n',
        '          }\n          {\n            // 2026-09-22 hardening: load the durable verify-mismatch',
    ),
    'retention_dump': (
        '            }\n',
        '          }\n          {\n            ecco_durable::DumpToGridRetryState retry{};',
    ),
    'retention_r244': (
        '            }\n',
        '          }\n\n          // S4 fix (2026-09-27, docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md',
    ),
    'boot_lambda': (
        '          id(supervision_invalid_reason_text).publish_state(id(supervision_last_invalid_reason));\n',
        '\nesp32:\n',
    ),
    'globals': (
        "  - id: failback_shadow_last_pub_soak_ms\n    type: uint32_t\n    restore_value: no\n    initial_value: '0'\n",
        '\nnumber:\n',
    ),
    'text_sensors': (
        '    id: failback_shadow_inputs_text\n    entity_category: diagnostic\n    update_interval: never\n',
        '\nsensor:\n  - platform: wifi_signal\n',
    ),
    'scripts': (
        '\n',
        'button:\n  - platform: restart\n',
    ),
    'button': (
        '          id: dump_accept_current_state\n\n',
        'interval:\n  - interval: 15s\n    startup_delay: 15s\n',
    ),
    'interval': (
        '          ESP_LOGI("free_power_recovery", "Review evidence expired (120s window elapsed)");\n\n',
        '  # Failback Shadow (FB-C1) - RAM-only, zero-authority evaluator. The first\n',
    ),
}

MANIFEST_ANCHORS = (
    '    resource_url: /local/ecco/ecco-energy-actions-card.js\n',
    '\nfirmware:\n',
)


# ---------------------------------------------------------------------------
# The hunks. before = left + old + right (the base text), after = left + new + right (the FB-B1 text).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Hunk:
    name: str
    region: str       # where in the firmware the edit sits
    left: str         # context before the edit (exact)
    old: str          # the base text replaced ("" for a pure insertion)
    new: str          # the FB-B1 text
    right: str        # context after the edit (exact)

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


_REBOOT_NAMES = ("reboot_text_dump", "reboot_text_free_power", "reboot_text_reg244")


def _reboot_hunks() -> list:
    hunks = []
    for name, (old, new) in zip(_REBOOT_NAMES, REBOOT_TEXT_EDITS):
        hunks.append(Hunk(name, "on_boot[0] unreadable-marker status text", "", old, new, ""))
    return hunks


_RB = {h.name: h for h in _reboot_hunks()}
_ON_BOOT_MARKER = "on_boot[0] marker block (last statement)"
HUNKS = (
    _ins("include", "esphome.includes", INCLUDE_BLOCK),
    _ins("retention_fp", _ON_BOOT_MARKER, RETENTION_BLOCKS[0]),
    _ins("retention_dump", _ON_BOOT_MARKER, RETENTION_BLOCKS[1]),
    _RB["reboot_text_dump"],
    _ins("retention_r244", _ON_BOOT_MARKER, RETENTION_BLOCKS[2]),
    _RB["reboot_text_free_power"],
    _RB["reboot_text_reg244"],
    _ins("boot_lambda", "esphome.on_boot (appended 4th item)", BOOT_BLOCK),
    _ins("globals", "globals", GLOBALS_BLOCK),
    _ins("text_sensors", "text_sensor", TEXT_SENSORS_BLOCK),
    _ins("scripts", "script", SCRIPTS_BLOCK),
    _ins("button", "button", BUTTON_BLOCK),
    _ins("interval", "interval (between the FP evidence-expiry and the FB-C1 interval)", INTERVAL_BLOCK),
)
HUNK_NAMES = tuple(h.name for h in HUNKS)
assert len(set(HUNK_NAMES)) == len(HUNKS) == 13


def hunk(name: str) -> Hunk:
    return HUNKS[HUNK_NAMES.index(name)]


# The FB-A reserved tokens FB-B1 adds to the firmware YAML, per hunk (chain entry fbb1 declares the total).
BANNED_FW_BY_HUNK = {h.name: len(_BANNED.findall(h.new)) for h in HUNKS}
BANNED_FW_ADDED = sum(BANNED_FW_BY_HUNK.values()) - sum(len(_BANNED.findall(h.old)) for h in HUNKS)


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"FB-B1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def pre_fbb1_firmware(text: str) -> str:
    """The firmware text with exactly FB-B1's thirteen edits undone (the exact-match reverter of chain entry fbb1). Every hunk
    must occur exactly once, in place, else AssertionError; after the revert every base anchor must again be unique (nothing
    else matches it). Reproduces main @ BASE_COMMIT byte for byte (BASE_FW_SHA)."""
    out = text
    for h in reversed(HUNKS):
        out = _swap(out, h.after, h.before, f"{h.name} hunk", "present")
    for h in HUNKS:
        n = out.count(h.before)
        if n != 1:
            raise AssertionError(f"FB-B1 scope: the {h.name} anchor must be unique once the hunk is removed, found {n}x")
    return out


def add_fbb1_text(text: str) -> str:
    """Applies FB-B1 to a firmware text that has none of it (generates the change; the suite's round trip). Every anchor must be
    unique and no hunk may already be present."""
    out = text
    for h in HUNKS:
        if h.after in out:
            raise AssertionError(f"FB-B1 scope: {h.name} hunk already present")
        out = _swap(out, h.before, h.after, f"{h.name} anchor", "found")
    return out


def pre_fbb1_manifest(text: str) -> str:
    """The ha-manifest text with exactly FB-B1's one frontend_assets stanza removed (reverter of chain entry fbb1 for
    deployment/ha-manifest.yaml): anchored on the preceding resource_url line and the following blank line + `firmware:`."""
    left, right = MANIFEST_ANCHORS
    out = _swap(text, left + MANIFEST_STANZA + right, left + right, "manifest stanza", "present")
    if out.count(left + right) != 1:
        raise AssertionError("FB-B1 scope: the manifest anchor must be unique once the stanza is removed")
    return out


def add_fbb1_manifest(text: str) -> str:
    left, right = MANIFEST_ANCHORS
    if MANIFEST_STANZA in text:
        raise AssertionError("FB-B1 scope: manifest stanza already present")
    return _swap(text, left + right, left + MANIFEST_STANZA + right, "manifest anchor", "found")
