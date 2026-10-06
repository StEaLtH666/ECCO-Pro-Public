"""SG-06 change scope: the exact edits SG-06 made to the on_boot lambda and
to firmware/include/ecco_durable_snapshot.h, as (before, after) text pairs.

Earlier suites pin the on_boot lambda and the durable header byte-for-byte
as change-scope proofs (SG-01 Phase 3/4/5: "nothing outside the SG-01 change
sites moved"). SG-06 necessarily edits both. Rather than re-pinning those
suites to new hashes - which would silently widen what they accept - they
hash `pre_sg06_boot()` / `pre_sg06_header()` instead: the current text with
exactly these edits reverted. Every `after` must occur exactly once (else
AssertionError), so any OTHER change to either text still breaks those pins,
and registry/tests/test_sg06_boot_durable_read_fail_closed.py pins that the
revert reproduces main @ 049c37e (the SG-06 base) exactly.

Generated from the real diff against 049c37e and verified by round trip; the
on_boot pairs are in the parsed (YAML-dedented) lambda form. No I/O.
"""

from __future__ import annotations

import hashlib

# sha256 of the on_boot lambda (parsed) and of the durable header on main @
# 049c37e - what pre_sg06_boot() / pre_sg06_header() must reproduce.
BASE_BOOT_SHA = "6a474d1304f7ed3a6a5c3cf0023827fb5c6d9fa1b33392bf844e0939b809111d"
BASE_HEADER_SHA = "85df3dc7f371c8488935ca958d3fe2943478e7952a9886b1caf57846a39a2f8d"

ON_BOOT_EDITS = [
    ('// fail-closed lockout as an unreadable data record.\n{\n',
     '// fail-closed lockout as an unreadable data record.\n//\n// SG-06: "genuine absence" means exactly LOAD_ABSENT\n// (ESP_ERR_NVS_NOT_FOUND) - see load_record_status() in\n// ecco_durable_snapshot.h.\n// A marker that cannot be READ (NVS unavailable, or any other read\n// error) is UNKNOWN, not CLEAR: an obligation cannot be ruled out,\n// so it takes the same fail-closed lockout as a malformed marker\n// (no write in this domain, cross-domain START gates see\n// snapshot_valid), without touching the durable record and with\n// no durable write - the next boot simply reads it again. A marker\n// record of the wrong SIZE is something stored that is not a\n// marker - malformed, exactly as rule 3 in ecco_durable_snapshot.h\n// requires.\nbool free_power_marker_unreadable = false;\n{\n'),
    ('  ecco_durable::ValidMarker marker{};\n  bool have_marker = ecco_durable::load_record(\n    ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker);\n',
     '  ecco_durable::ValidMarker marker{};\n  uint8_t marker_load = ecco_durable::load_record_status(\n    ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker);\n'),
    ('    ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker);\n  bool marker_malformed = have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n',
     '    ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker);\n  bool have_marker = marker_load == ecco_durable::LOAD_OK;\n  free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;\n  bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n'),
    ('     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  );\n  if (marker_malformed) {\n    // FAIL CLOSED: a durable marker record exists but its magic\n',
     '     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  ));\n  if (free_power_marker_unreadable) {\n    // FAIL CLOSED (SG-06): recovery obligation UNKNOWN - same\n    // lockout flags as the malformed branch below, for the same\n    // reason. Deliberately no Modbus, no commit, no clear.\n    id(free_power_snapshot_valid) = true;\n    id(free_power_recovery_metadata_corrupt) = true;\n    ESP_LOGE("free_power", "RECOVERY BLOCKED - durable recovery marker could not be read (NVS read failed); obligation UNKNOWN, inverter writes locked");\n  } else if (marker_malformed) {\n    // FAIL CLOSED: a durable marker record exists but its magic\n'),
    ('// no longer recall.\n{\n',
     "// no longer recall.\n//\n// SG-06: an unreadable marker is UNKNOWN, not CLEAR, and a\n// wrong-size one is malformed - see the Free Power block above.\n// UNKNOWN additionally parks SG-02 export containment in its\n// terminal state 8: containment exists for a Dump obligation that\n// is KNOWN to exist, and an unreadable store is no evidence that a\n// Dump lease (or its Allow Export) was ever ECCO's - so no inverter\n// write may follow from storage being unreadable.\nbool dump_marker_unreadable = false;\n{\n"),
    ('  ecco_durable::ValidMarker marker{};\n  bool have_marker = ecco_durable::load_record(\n    ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);\n',
     '  ecco_durable::ValidMarker marker{};\n  uint8_t marker_load = ecco_durable::load_record_status(\n    ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);\n'),
    ('    ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);\n  bool marker_malformed = have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n',
     '    ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);\n  bool have_marker = marker_load == ecco_durable::LOAD_OK;\n  dump_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;\n  bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n'),
    ('     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  );\n  if (marker_malformed) {\n    id(dump_snapshot_valid) = true;\n',
     '     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  ));\n  if (dump_marker_unreadable) {\n    id(dump_snapshot_valid) = true;\n    id(dump_recovery_metadata_corrupt) = true;\n    id(dump_containment_state) = 8;\n    ESP_LOGE("dump_to_grid", "RECOVERY BLOCKED - durable recovery marker could not be read (NVS read failed); obligation UNKNOWN, inverter writes locked, export containment NOT armed");\n  } else if (marker_malformed) {\n    id(dump_snapshot_valid) = true;\n'),
    ('if (id(dump_recovery_metadata_corrupt)) {\n  id(dump_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted; deliberate recovery required");\n} else if (id(dump_operator_needed)) {\n',
     'if (id(dump_recovery_metadata_corrupt)) {\n  if (dump_marker_unreadable) {\n    id(dump_status).publish_state("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; writes locked, export containment not armed - reboot to re-read");\n  } else {\n    id(dump_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted; deliberate recovery required");\n  }\n} else if (id(dump_operator_needed)) {\n'),
    ('}\n{\n',
     '}\n// SG-06: unreadable = UNKNOWN, wrong size = malformed - see the\n// Free Power block above.\nbool reg244_marker_unreadable = false;\n{\n'),
    ('  ecco_durable::ValidMarker marker{};\n  bool have_marker = ecco_durable::load_record(\n    ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), marker);\n',
     '  ecco_durable::ValidMarker marker{};\n  uint8_t marker_load = ecco_durable::load_record_status(\n    ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), marker);\n'),
    ('    ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), marker);\n  bool marker_malformed = have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n',
     '    ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), marker);\n  bool have_marker = marker_load == ecco_durable::LOAD_OK;\n  reg244_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;\n  bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && (\n    marker.magic != ecco_durable::VALID_MARKER_MAGIC ||\n'),
    ('     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  );\n  if (marker_malformed) {\n    // FAIL CLOSED - see the Free Power branch above.\n',
     '     marker.state != ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR)\n  ));\n  if (reg244_marker_unreadable) {\n    id(reg244_snapshot_valid) = true;\n    id(reg244_recovery_metadata_corrupt) = true;\n    ESP_LOGE("reg244_proof", "RECOVERY BLOCKED - durable recovery marker could not be read (NVS read failed); obligation UNKNOWN, inverter writes locked");\n  } else if (marker_malformed) {\n    // FAIL CLOSED - see the Free Power branch above.\n'),
    ('// Modbus; containment itself runs from the Dump 15s watchdog.\nif (id(dump_snapshot_valid) && id(dump_recovery_metadata_corrupt)) {\n  id(dump_containment_state) = 1;\n',
     '// Modbus; containment itself runs from the Dump 15s watchdog.\n// SG-06: state 8 (set by the Dump marker load above when the\n// marker could not be read) is terminal for this boot - the\n// watchdog only arms containment from state 0, and only runs it\n// in state 1/5.\nif (id(dump_containment_state) == 8) {\n  id(dump_containment_state_sensor).publish_state("NOT_ARMED_OBLIGATION_UNKNOWN - Dump durable marker could not be read at boot; no evidence of a Dump lease, so register 244 is NOT written because storage is unreadable");\n} else if (id(dump_snapshot_valid) && id(dump_recovery_metadata_corrupt)) {\n  id(dump_containment_state) = 1;\n'),
    ('if (id(free_power_recovery_metadata_corrupt)) {\n  // 2026-09-24 (PR-A follow-up, independent review R4): this flag\n  // is also set when the durable record loaded fine but ONE\n  // field within it is invalid (e.g. reg244_lease_context_plus1\n  // > 3) - "snapshot data is unreadable" was not accurate for\n  // that case (the data WAS read; a value in it is corrupt).\n  id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked");\n} else if (id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR) {\n',
     'if (id(free_power_recovery_metadata_corrupt)) {\n  if (free_power_marker_unreadable) {\n    // SG-06: the same lockout, but the marker itself could not be\n    // read - do not claim that a marker exists.\n    id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - reboot to re-read");\n  } else {\n    // 2026-09-24 (PR-A follow-up, independent review R4): this flag\n    // is also set when the durable record loaded fine but ONE\n    // field within it is invalid (e.g. reg244_lease_context_plus1\n    // > 3) - "snapshot data is unreadable" was not accurate for\n    // that case (the data WAS read; a value in it is corrupt).\n    id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked");\n  }\n} else if (id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR) {\n'),
    ('  id(reg244_snapshot_display).publish_state("—");\n  id(reg244_last_result).publish_state(\n    "RECOVERY BLOCKED - durable recovery marker exists but snapshot data is unreadable; inverter writes locked"\n  );\n} else if (id(reg244_marker_state) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR) {\n',
     '  id(reg244_snapshot_display).publish_state("—");\n  if (reg244_marker_unreadable) {\n    id(reg244_last_result).publish_state(\n      "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); inverter writes locked - reboot to re-read"\n    );\n  } else {\n    id(reg244_last_result).publish_state(\n      "RECOVERY BLOCKED - durable recovery marker exists but snapshot data is unreadable; inverter writes locked"\n    );\n  }\n} else if (id(reg244_marker_state) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR) {\n'),
]

HEADER_EDITS = [
    ('#include "esphome/core/helpers.h"\n\n',
     '#include "esphome/core/helpers.h"\n\n// SG-06: load_record_status() below asks NVS directly why a load failed.\n#include <nvs.h>\n\n'),
    ('// (first boot) or the stored size does not match T (schema change) - either\n// way `record` must be treated as not present.\ntemplate<typename T> inline bool load_record(uint32_t key, T &record) {\n',
     '// (first boot) or the stored size does not match T (schema change) - either\n// way `record` must be treated as not present. It ALSO returns false when\n// NVS could not be read at all (see SG-06 below): a caller for which absence\n// means "no recovery obligation" must use load_record_status() instead.\ntemplate<typename T> inline bool load_record(uint32_t key, T &record) {\n'),
    ('  return pref.load(&record);\n}\n',
     '  return pref.load(&record);\n}\n\n// SG-06 (boot-time durable-read fail-closed). load_record() returns a bare\n// bool because ESP32PreferenceBackend::load() (esphome/components/esp32/\n// preferences.cpp, vendored ESPHome 2026.8.2, not part of this repo) does:\n// ESP_ERR_NVS_NOT_FOUND (key genuinely never written), a stored-length\n// mismatch, ESP_ERR_NVS_INVALID_HANDLE (ESP32Preferences::open() left\n// nvs_handle 0 after its erase-and-retry nvs_open also failed) and any other\n// nvs_get_blob() error all come back as the same `false`. For a validity\n// marker, whose ABSENCE is the only evidence that no recovery obligation\n// exists, that turns "could not establish whether an obligation exists" into\n// "there is no obligation".\n//\n// load_record_status() is the same load through the same cached preference\n// object (so the S2 cache and ESPHome\'s pending-save lookup behave exactly\n// as in load_record(): LOAD_OK iff load_record() would have returned true).\n// Only on failure does it ask NVS WHY - one read-only nvs_get_blob() length\n// probe on ESPHome\'s own handle, with the same decimal key string ESPHome\n// itself uses. No allocation, no write, no erase, no retry.\n//   LOAD_ABSENT      ESP_ERR_NVS_NOT_FOUND: nothing was ever stored under\n//                    this key. The ONLY result that is evidence of absence.\n//   LOAD_WRONG_SIZE  something IS stored under this key, but not sizeof(T)\n//                    bytes - it cannot be this record.\n//   LOAD_READ_ERROR  anything else: NVS unavailable (handle 0), any other\n//                    nvs_get_blob() error, or the length matched but the\n//                    data read itself failed. Existence is UNKNOWN.\nenum LoadStatus : uint8_t {\n  LOAD_OK = 0,\n  LOAD_ABSENT = 1,\n  LOAD_WRONG_SIZE = 2,\n  LOAD_READ_ERROR = 3,\n};\n\ninline LoadStatus classify_load_failure(uint32_t key, size_t expected_len) {\n  auto *prefs = esphome::global_preferences;\n  if (prefs == nullptr || prefs->nvs_handle == 0)\n    return LOAD_READ_ERROR;\n  char key_str[esphome::UINT32_MAX_STR_SIZE];\n  esphome::uint32_to_str(key_str, key);\n  size_t stored_len = 0;\n  esp_err_t err = nvs_get_blob(prefs->nvs_handle, key_str, nullptr, &stored_len);\n  if (err == ESP_ERR_NVS_NOT_FOUND)\n    return LOAD_ABSENT;\n  if (err != ESP_OK)\n    return LOAD_READ_ERROR;\n  if (stored_len != expected_len)\n    return LOAD_WRONG_SIZE;\n  return LOAD_READ_ERROR;\n}\n\ntemplate<typename T> inline LoadStatus load_record_status(uint32_t key, T &record) {\n  auto &pref = preference_for<T>(key);\n  if (pref.load(&record))\n    return LOAD_OK;\n  return classify_load_failure(key, sizeof(T));\n}\n'),
    ('// is safe only because it governs pacing, never the underlying obligation.\nstruct FreePowerRetryState {\n',
     '// is safe only because it governs pacing, never the underlying obligation.\n// SG-06 leaves it unchanged, NVS read errors included (the retry records\n// still load through load_record()): an unreadable retry record never\n// hides an obligation - the marker/data load decides that - and failing\n// it closed would also block the corrective automatic restore.\nstruct FreePowerRetryState {\n'),
]


def _revert(text: str, edits, what: str) -> str:
    for before, after in edits:
        found = text.count(after)
        if found != 1:
            raise AssertionError(f"SG-06 {what} edit found {found}x (expected exactly once): {after[:70]!r}")
        text = text.replace(after, before)
    return text


def pre_sg06_boot(boot_lambda: str) -> str:
    """The on_boot lambda with exactly SG-06's edits reverted."""
    return _revert(boot_lambda, ON_BOOT_EDITS, "on_boot")


def pre_sg06_header(header: str) -> str:
    """The durable header with exactly SG-06's edits reverted."""
    return _revert(header, HEADER_EDITS, "header")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
