#!/usr/bin/env python3
"""Validator for registry/system_health_checks.yaml and
registry/health_reason_codes.yaml (Task 006).

Static checks only - does not connect to Home Assistant, ESPHome,
InfluxDB, or the inverter. See docs/SYSTEM_HEALTH_ARCHITECTURE.md for
the design this validates against, and the header comment of each
registry file for the exact field schema.

Importable: `validate(checks_path, reason_codes_path) -> list[str]`
returns a list of human-readable error strings (empty if both
registries are valid and mutually consistent), used both by this
script's own CLI and by tools/validate_repo.py's integration call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKS_PATH = ROOT / "registry" / "system_health_checks.yaml"
DEFAULT_REASON_CODES_PATH = ROOT / "registry" / "health_reason_codes.yaml"

VALID_SUBSYSTEMS = {
    "communications",
    "inverter_telemetry",
    "inverter_configuration",
    "rtc_time",
    "home_assistant",
    "canonical_telemetry",
    "influx_raw",
    "influx_5m",
    "battery_outlook",
    "battery_outlook_scorer",
    "manual_write_system",
    "free_power",
    "runtime_configuration",
    "deployment_consistency",
    "supervision",
    "fallback",
}

VALID_STATES = {"HEALTHY", "DEGRADED", "WARNING", "FAILED", "UNKNOWN", "SUPPRESSED"}

VALID_CHECK_TYPES = {
    "entity_available",
    "freshness",
    "boolean_expected",
    "numeric_range",
    "failure_counter_delta",
    "text_state",
    "transaction_state",
    "timestamp_age",
    "cross_source_agreement",
    "history_depth",
    "version_match",
    "conditional_presence",
    "hash_match",
}

VALID_SOURCE_TYPES = {
    "esphome_sensor",
    "ha_binary_sensor",
    "ha_template_sensor",
    "influx_diagnostic",
    "repository_file",
    "derived",
    "cross_source",
}

VALID_IMPLEMENTATION_STATUS = {"designed", "implemented_offline", "not_implemented"}
VALID_LIVE_PROOF_STATUS = {"unknown", "documented_not_live_proven", "live_proven_read"}
VALID_ROLLUP_PARTICIPATION = {"automatic", "diagnostic_only", "manual_only"}

REQUIRED_CHECK_FIELDS = (
    "id",
    "subsystem",
    "description",
    "source",
    "expected_datatype",
    "check_type",
    "outcomes",
    "evidence",
    "implementation_status",
    "live_proof_status",
)

REQUIRED_REASON_CODE_FIELDS = (
    "code",
    "subsystem",
    "severity",
    "meaning",
    "source_signal",
    "likely_cause",
    "safe_diagnostic_step",
    "blocks_manual_control",
    "affects_forecast",
)

_CHECK_ID_RE_SOURCE = r"^[a-z][a-z0-9_]*$"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _snake_case(value) -> bool:
    import re

    return isinstance(value, str) and bool(re.match(_CHECK_ID_RE_SOURCE, value))


def _load_yaml(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, [f"{path}: file does not exist"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path}: YAML parse failed: {exc}"]
    return data, []


def _validate_reason_codes(data: dict, path: Path) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    codes = data.get("reason_codes")
    if not isinstance(codes, list) or not codes:
        return {}, [f"{path}: 'reason_codes' must be a non-empty list"]

    by_code: dict[str, dict] = {}
    for idx, rc in enumerate(codes):
        loc = f"reason_codes[{idx}]"
        if not isinstance(rc, dict):
            errors.append(f"{loc}: not a mapping")
            continue

        code = rc.get("code")
        loc = f"reason code '{code}'" if code else loc

        for field_name in REQUIRED_REASON_CODE_FIELDS:
            if field_name not in rc or rc.get(field_name) in (None, ""):
                errors.append(f"{loc}: missing required field '{field_name}'")

        if not code or not isinstance(code, str) or not code.isupper():
            errors.append(f"{loc}: 'code' must be a non-empty UPPER_SNAKE_CASE string (got {code!r})")
        elif code in by_code:
            errors.append(f"{loc}: duplicate reason code (also defined earlier in the file)")
        else:
            by_code[code] = rc

        subsystem = rc.get("subsystem")
        if subsystem is not None and subsystem not in VALID_SUBSYSTEMS:
            errors.append(f"{loc}: invalid subsystem {subsystem!r} (must be one of {sorted(VALID_SUBSYSTEMS)})")

        severity = rc.get("severity")
        if severity is not None and severity not in VALID_STATES:
            errors.append(f"{loc}: invalid severity {severity!r} (must be one of {sorted(VALID_STATES)})")

        for bool_field in ("blocks_manual_control", "affects_forecast"):
            if bool_field in rc and not isinstance(rc.get(bool_field), bool):
                errors.append(f"{loc}: '{bool_field}' must be a boolean")

    return by_code, errors


def _validate_check_parameters(check: dict, loc: str, errors: list[str]) -> None:
    check_type = check.get("check_type")
    params = check.get("parameters")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errors.append(f"{loc}: 'parameters' must be a mapping")
        return

    outcomes = check.get("outcomes")
    num_outcomes = len(outcomes) if isinstance(outcomes, list) else 0

    def _ordered_threshold_pair(warn_key: str, fail_key: str, numeric_only: bool = True) -> None:
        if params.get("thresholds_unresolved") is True:
            return
        warn_val, fail_val = params.get(warn_key), params.get(fail_key)
        if warn_val is None and fail_val is None:
            errors.append(
                f"{loc}: check_type {check_type!r} has neither '{warn_key}' nor '{fail_key}' set - a "
                f"freshness/duration check requires at least one threshold, or an explicit "
                f"'thresholds_unresolved: true' documenting that no repository evidence supports one"
            )
            return
        if num_outcomes >= 2 and (warn_val is None or fail_val is None):
            errors.append(
                f"{loc}: check_type {check_type!r} declares {num_outcomes} outcomes but only one of "
                f"'{warn_key}'/'{fail_key}' is set - a multi-outcome check must declare both threshold "
                f"tiers so each outcome has an unambiguous trigger point"
            )
        if warn_val is not None and fail_val is not None:
            if numeric_only and (not _is_number(warn_val) or not _is_number(fail_val)):
                errors.append(f"{loc}: '{warn_key}'/'{fail_key}' must both be numeric when both are set")
            elif fail_val <= warn_val:
                errors.append(
                    f"{loc}: '{fail_key}' ({fail_val}) must be strictly greater than '{warn_key}' "
                    f"({warn_val}) - a failure threshold at or below the warning threshold makes the "
                    f"warning tier unreachable as age/duration increases"
                )
            if num_outcomes == 1:
                errors.append(
                    f"{loc}: check_type {check_type!r} declares both '{warn_key}' and '{fail_key}' but "
                    f"only has 1 outcome - a single-outcome check must declare exactly one threshold "
                    f"tier (whichever the outcome represents), since with only one reason code there is "
                    f"no way to distinguish which threshold actually governs it"
                )

    if check_type in ("freshness", "timestamp_age", "transaction_state"):
        _ordered_threshold_pair("warning_threshold_seconds", "failure_threshold_seconds")

    elif check_type == "failure_counter_delta":
        if not _is_number(params.get("window_seconds")):
            errors.append(f"{loc}: check_type 'failure_counter_delta' requires a numeric 'window_seconds'")
        _ordered_threshold_pair("warning_delta", "failure_delta")

    elif check_type == "numeric_range":
        lo, hi = params.get("min"), params.get("max")
        if not _is_number(lo) or not _is_number(hi):
            errors.append(f"{loc}: check_type 'numeric_range' requires numeric 'min' and 'max'")
        elif lo >= hi:
            errors.append(f"{loc}: 'min' ({lo}) must be strictly less than 'max' ({hi})")

    elif check_type == "boolean_expected":
        if not isinstance(params.get("expected_value"), bool):
            errors.append(f"{loc}: check_type 'boolean_expected' requires a boolean 'expected_value'")

    elif check_type == "text_state":
        failure_values = params.get("failure_values")
        if not isinstance(failure_values, list) or not failure_values:
            errors.append(f"{loc}: check_type 'text_state' requires a non-empty 'failure_values' list")

    elif check_type == "cross_source_agreement":
        if params.get("value_tolerance") is None and params.get("timestamp_tolerance_seconds") is None:
            errors.append(
                f"{loc}: check_type 'cross_source_agreement' requires at least one of 'value_tolerance' "
                f"or 'timestamp_tolerance_seconds'"
            )

    elif check_type == "history_depth":
        if not _is_number(params.get("minimum_value")):
            errors.append(f"{loc}: check_type 'history_depth' requires a numeric 'minimum_value'")

    # entity_available / version_match / conditional_presence / hash_match: no required parameters.


def validate(checks_path: Path = DEFAULT_CHECKS_PATH, reason_codes_path: Path = DEFAULT_REASON_CODES_PATH) -> list[str]:
    errors: list[str] = []

    reason_data, load_errors = _load_yaml(reason_codes_path)
    errors.extend(load_errors)
    reason_codes_by_code: dict[str, dict] = {}
    if reason_data is not None:
        reason_codes_by_code, rc_errors = _validate_reason_codes(reason_data, reason_codes_path)
        errors.extend(rc_errors)

    checks_data, load_errors = _load_yaml(checks_path)
    errors.extend(load_errors)
    if checks_data is None:
        return errors

    checks = checks_data.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{checks_path}: 'checks' must be a non-empty list")
        return errors

    seen_ids: dict[str, int] = {}
    dependency_graph: dict[str, list[str]] = {}
    referenced_reason_codes: set[str] = set()
    manual_control_blocking_ids: set[str] = set()

    for idx, chk in enumerate(checks):
        loc = f"checks[{idx}]"
        if not isinstance(chk, dict):
            errors.append(f"{loc}: not a mapping")
            continue

        check_id = chk.get("id")
        loc = f"check '{check_id}'" if check_id else loc

        for field_name in REQUIRED_CHECK_FIELDS:
            if not chk.get(field_name):
                errors.append(f"{loc}: missing required field '{field_name}'")

        if not check_id or not _snake_case(check_id):
            errors.append(f"{loc}: 'id' must be a non-empty snake_case string (got {check_id!r})")
        elif check_id in seen_ids:
            errors.append(f"{loc}: duplicate check id (also used by checks[{seen_ids[check_id]}])")
        else:
            seen_ids[check_id] = idx

        subsystem = chk.get("subsystem")
        if subsystem is not None and subsystem not in VALID_SUBSYSTEMS:
            errors.append(f"{loc}: invalid subsystem {subsystem!r} (must be one of {sorted(VALID_SUBSYSTEMS)})")

        check_type = chk.get("check_type")
        if check_type is not None and check_type not in VALID_CHECK_TYPES:
            errors.append(f"{loc}: unknown check_type {check_type!r} (must be one of {sorted(VALID_CHECK_TYPES)})")
        elif check_type is not None:
            _validate_check_parameters(chk, loc, errors)

        source = chk.get("source")
        if source is not None:
            if not isinstance(source, dict) or not source.get("entity") or not source.get("type"):
                errors.append(f"{loc}: 'source' must be a mapping with non-empty 'entity' and 'type'")
            elif source.get("type") not in VALID_SOURCE_TYPES:
                errors.append(f"{loc}: invalid source.type {source.get('type')!r} (must be one of {sorted(VALID_SOURCE_TYPES)})")

        impl_status = chk.get("implementation_status")
        if impl_status is not None and impl_status not in VALID_IMPLEMENTATION_STATUS:
            errors.append(f"{loc}: invalid implementation_status {impl_status!r} (must be one of {sorted(VALID_IMPLEMENTATION_STATUS)})")

        live_proof = chk.get("live_proof_status")
        if live_proof is not None and live_proof not in VALID_LIVE_PROOF_STATUS:
            errors.append(f"{loc}: invalid live_proof_status {live_proof!r} (must be one of {sorted(VALID_LIVE_PROOF_STATUS)})")

        rollup_participation = chk.get("rollup_participation")
        if rollup_participation is not None and rollup_participation not in VALID_ROLLUP_PARTICIPATION:
            errors.append(f"{loc}: invalid rollup_participation {rollup_participation!r} (must be one of {sorted(VALID_ROLLUP_PARTICIPATION)})")

        suppressed_safe = chk.get("suppressed_is_safe_for_control")
        if suppressed_safe is not None and not isinstance(suppressed_safe, bool):
            errors.append(f"{loc}: 'suppressed_is_safe_for_control' must be a boolean")

        outcomes = chk.get("outcomes")
        if not isinstance(outcomes, list) or not outcomes:
            errors.append(f"{loc}: 'outcomes' must be a non-empty list of {{reason_code, condition}} entries")
        else:
            for oidx, outcome in enumerate(outcomes):
                outcome_loc = f"{loc}: outcomes[{oidx}]"
                if not isinstance(outcome, dict) or not outcome.get("reason_code") or not outcome.get("condition"):
                    errors.append(f"{outcome_loc}: must be a mapping with non-empty 'reason_code' and 'condition'")
                    continue
                rcode = outcome["reason_code"]
                referenced_reason_codes.add(rcode)
                if rcode not in reason_codes_by_code:
                    errors.append(f"{outcome_loc}: reason_code {rcode!r} is not defined in {reason_codes_path.name}")
                    continue
                rc_def = reason_codes_by_code[rcode]
                if subsystem is not None and rc_def.get("subsystem") != subsystem:
                    errors.append(
                        f"{outcome_loc}: reason_code {rcode!r} belongs to subsystem "
                        f"{rc_def.get('subsystem')!r} in {reason_codes_path.name}, but this check is "
                        f"in subsystem {subsystem!r} - a check may only produce reason codes from its "
                        f"own subsystem"
                    )
                if rc_def.get("blocks_manual_control") is True and check_id:
                    manual_control_blocking_ids.add(check_id)

        deps = chk.get("dependencies") or []
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            errors.append(f"{loc}: 'dependencies' must be a list of check id strings")
        else:
            if check_id and check_id in deps:
                errors.append(f"{loc}: dependencies references itself ('{check_id}')")
            if check_id:
                dependency_graph[check_id] = deps

    # --- dependency existence ---------------------------------------------
    for check_id, deps in dependency_graph.items():
        for dep_id in deps:
            if dep_id not in seen_ids:
                errors.append(f"check '{check_id}': dependencies references unknown check id '{dep_id}'")

    # --- circular dependency detection (DFS with recursion-stack tracking) -
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in dependency_graph}

    def _visit(node: str, path: list[str]) -> None:
        color[node] = GRAY
        for dep in dependency_graph.get(node, []):
            if dep not in color:
                continue  # already reported as unknown above
            if color[dep] == GRAY:
                cycle = " -> ".join(path + [dep])
                errors.append(f"circular dependency detected among health checks: {cycle}")
            elif color[dep] == WHITE:
                _visit(dep, path + [dep])
        color[node] = BLACK

    for cid in list(dependency_graph):
        if color.get(cid) == WHITE:
            _visit(cid, [cid])

    # --- orphaned reason codes (defined but never used by any check) ------
    for code in reason_codes_by_code:
        if code not in referenced_reason_codes:
            errors.append(f"{reason_codes_path.name}: reason code '{code}' is defined but not referenced by any check in {checks_path.name}")

    return errors


def main() -> int:
    checks_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHECKS_PATH
    reason_codes_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_REASON_CODES_PATH
    errors = validate(checks_path, reason_codes_path)
    if errors:
        print("System health check registry validation FAILED")
        for error in errors:
            print(f" - {error}")
        return 1
    print("System health check registry validation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
