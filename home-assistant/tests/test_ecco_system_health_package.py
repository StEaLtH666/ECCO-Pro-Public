#!/usr/bin/env python3
"""Offline static checks for home-assistant/packages/ecco_system_health.yaml
(Task 006 Phase 1/2, Task 007 Phase 3 additions).

No I/O beyond reading local repository files - does not connect to Home
Assistant, ESPHome or InfluxDB, and does NOT prove the Jinja templates
evaluate correctly on a live instance (that requires `ha core check` and a
running Home Assistant, neither of which this script can do). This only
proves:

  - the file is valid YAML
  - the reserved final control-readiness gate (unique_id `ecco_manual_control_ready`,
    exact match, distinct from `ecco_manual_control_ready_reference`) is absent
  - no service call / script / automation / restart / write-capable construct
    exists anywhere in the file
  - every Phase 2 (and related) live-proven entity id this task depends on is
    referenced at least once
  - every reason_code string literal referenced in the file exists in
    registry/health_reason_codes.yaml
  - the Task 007 Phase 3 unique_ids exist alongside the pre-existing Phase 1
    unique_ids (a regression guard - Phase 1 must not have been removed)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = ROOT / "home-assistant" / "packages" / "ecco_system_health.yaml"
REASON_CODES_PATH = ROOT / "registry" / "health_reason_codes.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class TaggedSafeLoader(yaml.SafeLoader):
    """Tolerates Home Assistant/ESPHome custom !tags, matching tools/validate_repo.py."""


def _construct_unknown(loader: TaggedSafeLoader, tag_suffix: str, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


TaggedSafeLoader.add_multi_constructor("!", _construct_unknown)

text = PACKAGE_PATH.read_text(encoding="utf-8")

print("[1] File is valid YAML")
try:
    data = yaml.load(text, Loader=TaggedSafeLoader)
    check("home-assistant/packages/ecco_system_health.yaml parses as YAML", True)
except Exception as exc:  # noqa: BLE001
    data = None
    check("home-assistant/packages/ecco_system_health.yaml parses as YAML", False, str(exc))

print("")
print("[2] The final, reserved control-readiness gate is absent")
# Exact match only - `ecco_manual_control_ready_reference` (the Phase 1
# partial reference entity) must NOT be mistaken for a match here.
final_gate_pattern = re.compile(r"unique_id:\s*ecco_manual_control_ready\s*$", re.MULTILINE)
check(
    "no 'unique_id: ecco_manual_control_ready' (exact) anywhere in the file",
    final_gate_pattern.search(text) is None,
)
check(
    "the Phase 1 partial reference entity (ecco_manual_control_ready_reference) is still present",
    "unique_id: ecco_manual_control_ready_reference" in text,
)

print("")
print("[3] No service calls, scripts, automations, restarts or write-capable constructs")
# `#`-comment lines (including the file's own header, which documents these
# prohibitions in prose) are excluded first, matching the same
# comment-stripping approach influxdb/tests/test_diagnostics_read_only.py
# uses for Flux `//` comments - otherwise the header's own explanation of
# what must NOT appear would trip these checks on itself.
code_lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
code_text = "\n".join(code_lines)
FORBIDDEN_SUBSTRINGS = [
    "service:",
    "action:",
    "shell_command:",
    "command_line:",
    "automation:",
    "homeassistant.restart",
    "homeassistant.reload_config_entry",
    "modbus_client",
    "esphome.",
    "button.press",
]
for token in FORBIDDEN_SUBSTRINGS:
    check(f"does not contain {token!r} outside a comment", token not in code_text)

print("")
print("[4] Every live-proven/related entity id this task depends on is referenced")
REQUIRED_ENTITY_IDS = [
    # Phase 2, live-proven 2026-09-18
    "binary_sensor.ecco_clock_dongle_manual_write_in_progress",
    "binary_sensor.ecco_clock_dongle_rtc_correction_in_progress",
    "binary_sensor.ecco_clock_dongle_free_power_operation_in_progress",
    "binary_sensor.ecco_clock_dongle_free_power_snapshot_valid",
    "binary_sensor.ecco_clock_dongle_manual_configuration_raw_cache_valid",
    # Existing related signals used by Phase 3
    "binary_sensor.ecco_clock_dongle_rtc_stall_detected",
    "binary_sensor.ecco_clock_dongle_ntp_synced",
    "sensor.ecco_clock_dongle_clock_difference",
    "sensor.ecco_clock_dongle_ecco_inverter_system_state",
    "sensor.ecco_clock_dongle_ecco_inverter_warning",
    "sensor.ecco_clock_dongle_ecco_inverter_fault",
    "binary_sensor.ecco_clock_dongle_free_power_active",
    "binary_sensor.ecco_clock_dongle_ecco_grid_connected",
]
for entity_id in REQUIRED_ENTITY_IDS:
    check(f"references {entity_id}", entity_id in text)

print("")
print("[5] Every reason_code string literal in the file exists in registry/health_reason_codes.yaml")
reason_codes_data = yaml.safe_load(REASON_CODES_PATH.read_text(encoding="utf-8")) or {}
known_codes = {rc["code"] for rc in reason_codes_data.get("reason_codes", [])}
check("registry/health_reason_codes.yaml loaded with at least one code", len(known_codes) > 0)

# Every real reason-code reference in this file is written as a
# single-quoted Jinja string literal (e.g. 'MANUAL_WRITE_ACTIVE'), inside a
# `codes = codes + [...]` list or a literal `[...]` return - never bare and
# never in a comment/doc-path. Restricting to single-quoted tokens avoids
# false positives from doc filenames like SYSTEM_HEALTH_ARCHITECTURE.md
# appearing unquoted in comments.
candidate_codes = set(re.findall(r"'([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)'", text))
unknown_codes = sorted(c for c in candidate_codes if c not in known_codes)
check(
    "every ALL_CAPS reason-code-shaped token in the file is a real registry reason code",
    len(unknown_codes) == 0,
    f"unrecognised token(s): {unknown_codes}" if unknown_codes else "",
)

print("")
print("[6] Task 007 Phase 3 unique_ids are present")
PHASE3_UNIQUE_IDS = [
    "ecco_health_manual_write_system",
    "ecco_health_rtc",
    "ecco_health_free_power",
    "ecco_health_configuration",
    "ecco_health_inverter_telemetry",
]
for uid in PHASE3_UNIQUE_IDS:
    check(f"unique_id: {uid} present", f"unique_id: {uid}" in text)

print("")
print("[7] Task 006/006A Phase 1 unique_ids are still present (regression guard)")
PHASE1_UNIQUE_IDS = [
    "ecco_manual_control_ready_reference",
    "ecco_health_communications",
    "ecco_health_runtime_configuration",
]
for uid in PHASE1_UNIQUE_IDS:
    check(f"unique_id: {uid} present", f"unique_id: {uid}" in text)

print("")
print("[8] Every Phase 3 represented check id exists in registry/system_health_checks.yaml")
checks_path = ROOT / "registry" / "system_health_checks.yaml"
checks_data = yaml.safe_load(checks_path.read_text(encoding="utf-8")) or {}
known_check_ids = {c["id"] for c in checks_data.get("checks", [])}
phase3_check_ids = {
    "manual_write_duration",
    "rtc_correction_duration",
    "rtc_stall_detected",
    "rtc_ntp_synced",
    "free_power_operation_duration",
    "free_power_active_state",
    "free_power_snapshot_recovery",
    "config_cache_valid",
    "inverter_alarm_fault",
    "inverter_grid_connected",
}
check(
    "every Phase 3 represented check id exists in registry/system_health_checks.yaml",
    phase3_check_ids <= known_check_ids,
    f"missing registry check id(s): {sorted(phase3_check_ids - known_check_ids)}",
)
for check_id in sorted(phase3_check_ids):
    check(f"package references represented check {check_id}", check_id in text)

print("")
print("[8a] FB-B3 Phase 4 additions (supervision / fallback; display layer in ecco_fallback_status.yaml)")
PHASE4_UNIQUE_IDS = ["ecco_health_supervision", "ecco_health_fallback"]
for uid in PHASE4_UNIQUE_IDS:
    check(f"unique_id: {uid} present", f"unique_id: {uid}" in text)
for entity_id in ["sensor.ecco_supervision_status", "sensor.ecco_fallback_status_code"]:
    check(f"references {entity_id}", entity_id in text)
phase4_check_ids = {
    "supervision_status_available", "supervision_startup", "supervision_not_stable", "supervision_suspect",
    "supervision_lost", "fallback_status_available", "fallback_live_unknown", "fallback_not_captured",
    "fallback_invalidated", "fallback_drifted", "fallback_context_changed", "fallback_export_enabled",
    "fallback_unusable", "fallback_save_unconfirmed", "fallback_profile_regressed",
    "fallback_live_out_of_domain", "fallback_blocked_by_lease",
}
check(
    "every Phase 4 represented check id exists in registry/system_health_checks.yaml",
    phase4_check_ids <= {c["id"] for c in (yaml.safe_load((ROOT / "registry" / "system_health_checks.yaml").read_text(encoding="utf-8")) or {}).get("checks", [])},
)
for check_id in sorted(phase4_check_ids):
    check(f"package references represented check {check_id}", check_id in text)
check(
    "no reason-code-shaped literal contains the banned FB substrings",
    not any(("FALLBACK" + "_PROFILE") in c or ("FAILBACK" + "_STATE") in c for c in candidate_codes),
)

print("")
print("[8b] Template-sensor diagnostic list attributes use template strings, not literal YAML lists")
template_blocks = (data or {}).get("template", []) if isinstance(data, dict) else []
literal_list_attribute_paths = []
for block_index, block in enumerate(template_blocks):
    if not isinstance(block, dict):
        continue
    for platform in ("sensor", "binary_sensor"):
        entities = block.get(platform, [])
        if not isinstance(entities, list):
            continue
        for entity_index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            attrs = entity.get("attributes", {})
            if not isinstance(attrs, dict):
                continue
            for attr_name, attr_value in attrs.items():
                if isinstance(attr_value, list):
                    literal_list_attribute_paths.append(
                        f"template[{block_index}].{platform}[{entity_index}].attributes.{attr_name}"
                    )
check(
    "no template sensor attribute value is a literal YAML list",
    not literal_list_attribute_paths,
    f"literal list attribute(s): {literal_list_attribute_paths}",
)

print("")
print("[9] Duration-based trigger-template sensors have an explicit time refresh")
for uid in [
    "ecco_health_manual_write_system",
    "ecco_health_rtc",
    "ecco_health_free_power",
]:
    uid_pos = text.find(f"unique_id: {uid}")
    check(f"{uid} exists for cadence inspection", uid_pos >= 0)
    if uid_pos >= 0:
        block_start = text.rfind("  - triggers:", 0, uid_pos)
        next_block = text.find("\n  - triggers:", uid_pos)
        block_end = len(text) if next_block < 0 else next_block
        block = text[block_start:block_end]
        check(
            f"{uid} has time_pattern refresh trigger",
            "trigger: time_pattern" in block and 'minutes: "/1"' in block,
            "duration thresholds cannot advance on a state-only trigger",
        )

print("")
print("[10] Fail-closed required-source reporting is retained")
check(
    "RTC blocks_manual_control does not exempt unknown correction state",
    "{{ states('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress') != 'off' }}" in text,
)
check(
    "Free Power blocks_manual_control fails closed unless all three safety states are off",
    "{{ s1 != 'off' or s2 != 'off' or s3 != 'off' }}" in text,
)
check(
    "inverter telemetry represents the live grid-connected registry check",
    "inverter_grid_connected" in text
    and "binary_sensor.ecco_clock_dongle_ecco_grid_connected" in text,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All ecco_system_health.yaml Phase 3 static checks PASSED.")
    print("NOTE: this does not prove the Jinja templates are valid or correct on a")
    print("live Home Assistant instance - only `ha core check` plus live observation")
    print("can prove that. This file remains STAGED / NOT LIVE-PROVEN.")

if FAILURES:
    sys.exit(1)
