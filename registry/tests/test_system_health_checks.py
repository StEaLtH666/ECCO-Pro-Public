#!/usr/bin/env python3
"""Offline tests for tools/validate_system_health_checks.py (Task 006
section 16).

Exercises the validator against small, synthetic check/reason-code
records (not the real registries, so each scenario is isolated), then
runs it once against the real registry/system_health_checks.yaml and
registry/health_reason_codes.yaml as an end-to-end smoke test.

No I/O beyond reading local YAML/Python files.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import yaml  # noqa: E402

from validate_system_health_checks import (  # noqa: E402
    DEFAULT_CHECKS_PATH,
    DEFAULT_REASON_CODES_PATH,
    validate,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def run(checks: list[dict], reason_codes: list[dict]) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        checks_path = Path(tmp) / "checks.yaml"
        reason_codes_path = Path(tmp) / "reason_codes.yaml"
        checks_path.write_text(yaml.safe_dump({"schema_version": 1, "checks": checks}), encoding="utf-8")
        reason_codes_path.write_text(yaml.safe_dump({"schema_version": 1, "reason_codes": reason_codes}), encoding="utf-8")
        return validate(checks_path, reason_codes_path)


BASE_REASON_CODE = {
    "code": "EXAMPLE_CODE",
    "subsystem": "communications",
    "severity": "WARNING",
    "meaning": "An example condition.",
    "source_signal": "example_signal",
    "likely_cause": "Example cause.",
    "safe_diagnostic_step": "Check the example signal.",
    "blocks_manual_control": False,
    "affects_forecast": False,
}

BASE_CHECK = {
    "id": "example_check",
    "subsystem": "communications",
    "description": "An example check.",
    "source": {"entity": "example entity", "type": "esphome_sensor"},
    "expected_datatype": "bool",
    "check_type": "boolean_expected",
    "parameters": {"expected_value": True},
    "applicability_condition": None,
    "outcomes": [{"reason_code": "EXAMPLE_CODE", "condition": "Value is false."}],
    "dependencies": [],
    "evidence": "firmware/example.yaml:1",
    "implementation_status": "designed",
    "live_proof_status": "unknown",
}


print("[1] Valid check + reason code")
errors = run([dict(BASE_CHECK)], [dict(BASE_REASON_CODE)])
check("a well-formed check/reason-code pair produces no errors", errors == [], f"{errors}")

print("")
print("[2] Duplicate check IDs")
errors = run([dict(BASE_CHECK), {**BASE_CHECK}], [dict(BASE_REASON_CODE)])
check("two checks sharing an id are rejected", any("duplicate check id" in e for e in errors), f"{errors}")

print("")
print("[3] Invalid subsystem")
errors = run([{**BASE_CHECK, "subsystem": "not_a_real_subsystem"}], [dict(BASE_REASON_CODE)])
check("an invalid check subsystem is rejected", any("invalid subsystem" in e for e in errors), f"{errors}")
errors = run([dict(BASE_CHECK)], [{**BASE_REASON_CODE, "subsystem": "not_a_real_subsystem"}])
check("an invalid reason-code subsystem is rejected", any("invalid subsystem" in e for e in errors), f"{errors}")

print("")
print("[4] Invalid health state/severity")
errors = run([dict(BASE_CHECK)], [{**BASE_REASON_CODE, "severity": "CATASTROPHIC"}])
check("an invalid severity value is rejected", any("invalid severity" in e for e in errors), f"{errors}")

print("")
print("[5] Unknown check type")
errors = run([{**BASE_CHECK, "check_type": "psychic_prediction"}], [dict(BASE_REASON_CODE)])
check("an unknown check_type is rejected", any("unknown check_type" in e for e in errors), f"{errors}")

print("")
print("[6] Missing evidence/source")
bad = {k: v for k, v in BASE_CHECK.items() if k != "evidence"}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("a check with no evidence is rejected", any("missing required field 'evidence'" in e for e in errors), f"{errors}")
bad2 = {k: v for k, v in BASE_CHECK.items() if k != "source"}
errors = run([bad2], [dict(BASE_REASON_CODE)])
check("a check with no source is rejected", any("missing required field 'source'" in e for e in errors), f"{errors}")

print("")
print("[7] Freshness check with no thresholds")
bad = {
    **BASE_CHECK,
    "check_type": "freshness",
    "parameters": {"expected_interval_seconds": 10},
    "outcomes": [{"reason_code": "EXAMPLE_CODE", "condition": "Stale."}],
}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("a freshness check with neither threshold set is rejected", any("neither" in e for e in errors), f"{errors}")
ok = {**bad, "parameters": {"expected_interval_seconds": 10, "thresholds_unresolved": True}}
errors = run([ok], [dict(BASE_REASON_CODE)])
check("thresholds_unresolved: true is an accepted escape hatch", errors == [], f"{errors}")

print("")
print("[8] Failure threshold <= warning threshold where age increases severity")
bad = {
    **BASE_CHECK,
    "check_type": "freshness",
    "parameters": {"warning_threshold_seconds": 180, "failure_threshold_seconds": 60},
    "outcomes": [
        {"reason_code": "EXAMPLE_CODE", "condition": "Degraded."},
        {"reason_code": "EXAMPLE_CODE_2", "condition": "Failed."},
    ],
}
errors = run([bad], [dict(BASE_REASON_CODE), {**BASE_REASON_CODE, "code": "EXAMPLE_CODE_2", "severity": "FAILED"}])
check("failure_threshold_seconds <= warning_threshold_seconds is rejected", any("must be strictly greater than" in e for e in errors), f"{errors}")

print("")
print("[9] Single-outcome check with both threshold tiers set (ambiguous)")
bad = {
    **BASE_CHECK,
    "check_type": "freshness",
    "parameters": {"warning_threshold_seconds": 60, "failure_threshold_seconds": 180},
    "outcomes": [{"reason_code": "EXAMPLE_CODE", "condition": "Stale."}],
}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("a single-outcome check declaring both threshold tiers is rejected", any("only has 1 outcome" in e for e in errors), f"{errors}")

print("")
print("[10] Multi-outcome check with only one threshold tier set (ambiguous)")
bad = {
    **BASE_CHECK,
    "check_type": "freshness",
    "parameters": {"warning_threshold_seconds": 60},
    "outcomes": [
        {"reason_code": "EXAMPLE_CODE", "condition": "Degraded."},
        {"reason_code": "EXAMPLE_CODE_2", "condition": "Failed."},
    ],
}
errors = run([bad], [dict(BASE_REASON_CODE), {**BASE_REASON_CODE, "code": "EXAMPLE_CODE_2", "severity": "FAILED"}])
check("a 2-outcome check declaring only one threshold tier is rejected", any("only one of" in e for e in errors), f"{errors}")

print("")
print("[11] Invalid dependencies")
bad = {**BASE_CHECK, "dependencies": ["does_not_exist"]}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("a dependency referencing a non-existent check id is rejected", any("references unknown check id" in e for e in errors), f"{errors}")
bad2 = {**BASE_CHECK, "dependencies": ["example_check"]}
errors = run([bad2], [dict(BASE_REASON_CODE)])
check("a check depending on itself is rejected", any("references itself" in e for e in errors), f"{errors}")

print("")
print("[12] Circular check dependencies")
a = {**BASE_CHECK, "id": "check_a", "dependencies": ["check_b"]}
b = {**BASE_CHECK, "id": "check_b", "dependencies": ["check_a"]}
errors = run([a, b], [dict(BASE_REASON_CODE)])
check("a two-check circular dependency is detected", any("circular dependency detected" in e for e in errors), f"{errors}")
a3 = {**BASE_CHECK, "id": "check_x", "dependencies": ["check_y"]}
b3 = {**BASE_CHECK, "id": "check_y", "dependencies": ["check_z"]}
c3 = {**BASE_CHECK, "id": "check_z", "dependencies": ["check_x"]}
errors = run([a3, b3, c3], [dict(BASE_REASON_CODE)])
check("a three-check circular dependency is detected", any("circular dependency detected" in e for e in errors), f"{errors}")
ok_chain = [{**BASE_CHECK, "id": "chain_a", "dependencies": []}, {**BASE_CHECK, "id": "chain_b", "dependencies": ["chain_a"]}]
errors = run(ok_chain, [dict(BASE_REASON_CODE)])
check("a legitimate non-circular dependency chain validates cleanly", errors == [], f"{errors}")

print("")
print("[13] Manual-control-blocking check has a reason-code rationale")
blocking_rc = {**BASE_REASON_CODE, "blocks_manual_control": True}
errors = run([dict(BASE_CHECK)], [blocking_rc])
check(
    "a check whose reason_code blocks manual control validates cleanly when the reason code has full rationale fields",
    errors == [],
    f"{errors}",
)
bad_blocking_rc = {k: v for k, v in blocking_rc.items() if k != "safe_diagnostic_step"}
errors = run([dict(BASE_CHECK)], [bad_blocking_rc])
check("a blocking reason code missing safe_diagnostic_step is rejected", any("missing required field 'safe_diagnostic_step'" in e for e in errors), f"{errors}")

print("")
print("[14] Impossible configuration (numeric_range min >= max)")
bad = {**BASE_CHECK, "check_type": "numeric_range", "parameters": {"min": 10, "max": 5}}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("numeric_range min >= max is rejected", any("must be strictly less than" in e for e in errors), f"{errors}")

print("")
print("[15] Duplicate reason codes")
errors = run([dict(BASE_CHECK)], [dict(BASE_REASON_CODE), dict(BASE_REASON_CODE)])
check("two reason codes sharing a code value are rejected", any("duplicate reason code" in e for e in errors), f"{errors}")

print("")
print("[16] Orphaned reason codes")
errors = run([dict(BASE_CHECK)], [dict(BASE_REASON_CODE), {**BASE_REASON_CODE, "code": "NEVER_USED"}])
check("a reason code defined but never referenced by any check is flagged", any("is defined but not referenced" in e for e in errors), f"{errors}")

print("")
print("[17] Outcome reason_code must belong to the check's own subsystem")
mismatched_rc = {**BASE_REASON_CODE, "subsystem": "rtc_time"}
errors = run([dict(BASE_CHECK)], [mismatched_rc])
check(
    "a check referencing a reason code from a different subsystem is rejected",
    any("may only produce reason codes from its own subsystem" in e for e in errors),
    f"{errors}",
)

print("")
print("[18] check_type-specific parameter validation")
bad = {**BASE_CHECK, "check_type": "failure_counter_delta", "parameters": {"warning_delta": 1}}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("failure_counter_delta with no window_seconds is rejected", any("requires a numeric 'window_seconds'" in e for e in errors), f"{errors}")
bad = {**BASE_CHECK, "check_type": "text_state", "parameters": {}}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("text_state with no failure_values is rejected", any("requires a non-empty 'failure_values'" in e for e in errors), f"{errors}")
bad = {**BASE_CHECK, "check_type": "cross_source_agreement", "parameters": {}}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("cross_source_agreement with neither tolerance set is rejected", any("requires at least one of" in e for e in errors), f"{errors}")
bad = {**BASE_CHECK, "check_type": "history_depth", "parameters": {}}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("history_depth with no minimum_value is rejected", any("requires a numeric 'minimum_value'" in e for e in errors), f"{errors}")

print("")
print("[19] rollup_participation / suppressed_is_safe_for_control fields (Task 006A)")
bad = {**BASE_CHECK, "rollup_participation": "sometimes"}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("an invalid rollup_participation value is rejected", any("invalid rollup_participation" in e for e in errors), f"{errors}")
for valid_value in ("automatic", "diagnostic_only", "manual_only"):
    ok = {**BASE_CHECK, "rollup_participation": valid_value}
    errors = run([ok], [dict(BASE_REASON_CODE)])
    check(f"rollup_participation: {valid_value} validates cleanly", errors == [], f"{errors}")
bad = {**BASE_CHECK, "suppressed_is_safe_for_control": "yes"}
errors = run([bad], [dict(BASE_REASON_CODE)])
check("a non-boolean suppressed_is_safe_for_control is rejected", any("must be a boolean" in e for e in errors), f"{errors}")
ok = {**BASE_CHECK, "suppressed_is_safe_for_control": True}
errors = run([ok], [dict(BASE_REASON_CODE)])
check("suppressed_is_safe_for_control: true validates cleanly", errors == [], f"{errors}")

print("")
print("[19b] FB-B3 supervision / fallback subsystems are valid, with no orphan codes or checks")
for sub in ("supervision", "fallback"):
    errors = run([{**BASE_CHECK, "subsystem": sub}], [{**BASE_REASON_CODE, "subsystem": sub}])
    check(f"subsystem {sub!r} is accepted by the validator", errors == [], f"{errors}")
_real_codes = yaml.safe_load(DEFAULT_REASON_CODES_PATH.read_text(encoding="utf-8"))["reason_codes"]
_real_checks = yaml.safe_load(DEFAULT_CHECKS_PATH.read_text(encoding="utf-8"))["checks"]
_fb_codes = {c["code"] for c in _real_codes if c["subsystem"] in ("supervision", "fallback")}
_fb_check_codes = {o["reason_code"] for c in _real_checks if c["subsystem"] in ("supervision", "fallback") for o in c["outcomes"]}
# FB-C3: 17 FB-B3 codes + FAILBACK_SHADOW_EPISODE = 18, each still referenced by exactly one check.
check("18 supervision/fallback reason codes (17 FB-B3 + FB-C3 FAILBACK_SHADOW_EPISODE), each referenced by a check (no orphan code or check)",
      len(_fb_codes) == 18 and _fb_codes == _fb_check_codes and "FAILBACK_SHADOW_EPISODE" in _fb_codes, f"{sorted(_fb_codes ^ _fb_check_codes)}")
check("no registered reason code contains FALLBACK_PROFILE or FAILBACK_STATE (banned under home-assistant/)",
      not any(("FALLBACK" + "_PROFILE") in c["code"] or ("FAILBACK" + "_STATE") in c["code"] for c in _real_codes))
check("FB-C3: FAILBACK_SHADOW_EPISODE is the only FAILBACK_ code registered; FB-E/F codes are not registered early; FALLBACK_SHADOW_BLOCKED never exists",
      sorted(c["code"] for c in _real_codes if c["code"].startswith("FAILBACK_")) == ["FAILBACK_SHADOW_EPISODE"]
      and not any(c["code"] == "FALLBACK_SHADOW_BLOCKED" for c in _real_codes))

print("")
print("[20] End-to-end smoke test against the real registries")
real_errors = validate(DEFAULT_CHECKS_PATH, DEFAULT_REASON_CODES_PATH)
check("the real system_health_checks.yaml + health_reason_codes.yaml validate with zero errors", real_errors == [], f"{real_errors}")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All system health check registry validator offline tests PASSED.")

if FAILURES:
    sys.exit(1)
