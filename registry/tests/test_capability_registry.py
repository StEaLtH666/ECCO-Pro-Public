#!/usr/bin/env python3
"""Offline tests for tools/validate_capability_registry.py (schema v2).

Exercises the validator against small, synthetic capability records
(not the real registry, so each scenario is isolated and its expected
result is unambiguous), then runs it once against the real
registry/inverter_capabilities.yaml as an end-to-end smoke test.

No I/O beyond reading local YAML/Python files - no hardware, no
network, nothing that could touch a real inverter or InfluxDB.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import yaml  # noqa: E402

from validate_capability_registry import DEFAULT_REGISTRY_PATH, validate  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def validate_capabilities(caps: list[dict]) -> list[str]:
    """Writes `caps` to a temp registry file and runs the real validator
    against it - exercises the actual file-reading code path, not just
    the in-memory logic."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump({"schema_version": 2, "capabilities": caps}, f)
        path = Path(f.name)
    try:
        return validate(path)
    finally:
        path.unlink(missing_ok=True)


def register(address, bits=None, shared_with=None):
    d = {"address": address}
    if bits is not None:
        d["bits"] = bits
    if shared_with:
        d["shared_with"] = shared_with
    return d


BASE_R0 = {
    "id": "example_r0",
    "name": "Example R0",
    "category": "status",
    "current_access": "read_only",
    "write_policy": "R0",
    "live_proof_status": "live_proven_read",
    "implementation_status": "implemented",
    "firmware_evidence": "firmware/example.yaml:1",
    "safety_impact": "none",
    "modbus": {"registers": [register(100)], "datatype": "uint16"},
    "snapshot_required": False,
    "recovery_implementation_status": "not_required",
}

BASE_W1 = {
    "id": "example_w1",
    "name": "Example W1",
    "category": "grid_charge",
    "current_access": "read_write",
    "write_policy": "W1",
    "write_policy_reason": "known register, bounded, exact verify",
    "live_proof_status": "live_proven_write",
    "implementation_status": "implemented",
    "firmware_evidence": "firmware/example.yaml:2",
    "safety_impact": "changes a setpoint",
    "modbus": {"registers": [register(101)], "datatype": "uint16"},
    "safe_min": 0,
    "safe_max": 100,
    "exact_reread_verification_possible": True,
    "verification_tolerance": "exact",
    "snapshot_required": True,
    "restoration_possible": "yes_via_cached_raw_registers",
    "recovery_implementation_status": "partial",
}

BASE_W2 = {
    **BASE_W1,
    "id": "example_w2",
    "name": "Example W2",
    "write_policy": "W2",
    "write_policy_reason": "coordinated multi-register write with snapshot/restore",
    "modbus": {"registers": [register(102), register(103)], "datatype": "uint16"},
}

BASE_W3 = {
    "id": "example_w3",
    "name": "Example W3",
    "category": "battery",
    "current_access": "read_only",
    "write_policy": "W3",
    "write_policy_reason": "known high-impact configuration candidate, no write path exists yet",
    "live_proof_status": "live_proven_read",
    "implementation_status": "implemented",
    "firmware_evidence": "firmware/example.yaml:5",
    "safety_impact": "would affect battery charge curve if ever writable",
    "modbus": {"registers": [register(105)], "datatype": "uint16"},
    "bounds_note": "no live-calibrated safe write bounds established",
    "snapshot_required": False,
    "recovery_implementation_status": "not_required",
}

BASE_WX = {
    "id": "example_wx",
    "name": "Example WX",
    "category": "status",
    "current_access": "read_only",
    "write_policy": "WX",
    "live_proof_status": "unknown",
    "implementation_status": "implemented (read, undecoded)",
    "firmware_evidence": "firmware/example.yaml:3",
    "safety_impact": "unknown",
    "modbus": {"registers": [register(104)], "datatype": "unknown"},
    "snapshot_required": False,
    "recovery_implementation_status": "not_required",
}


print("[1] Valid R0 telemetry capability")
errors = validate_capabilities([dict(BASE_R0)])
check("a well-formed R0 record produces no errors", errors == [], f"{errors}")

print("")
print("[2] Valid W1 capability")
errors = validate_capabilities([dict(BASE_W1)])
check("a well-formed W1 record produces no errors", errors == [], f"{errors}")

print("")
print("[3] Valid W2 coordinated-transaction capability")
errors = validate_capabilities([dict(BASE_W2)])
check("a well-formed W2 record produces no errors", errors == [], f"{errors}")

print("")
print("[4] W3 + current_access=read_only -> PASS and remains non-actionable")
errors = validate_capabilities([dict(BASE_W3)])
check("a well-formed W3/read_only record produces no errors", errors == [], f"{errors}")
bad = {**BASE_W3, "current_access": "read_write", "live_proof_status": "unknown"}
errors = validate_capabilities([bad])
check(
    "W3 incorrectly marked live-writable without required proof -> FAIL",
    any("must not claim an existing write path" in e for e in errors),
    f"{errors}",
)

print("")
print("[5] WX read-only -> PASS")
errors = validate_capabilities([dict(BASE_WX)])
check("a well-formed WX/read_only record produces no errors", errors == [], f"{errors}")
bad = {**BASE_WX, "current_access": "read_write"}
errors = validate_capabilities([bad])
check("WX marked read_write (claiming write capability) -> FAIL", any("WX" in e and "read_write" in e for e in errors), f"{errors}")

print("")
print("[6] R0/W1/W2 access-policy consistency")
bad = {**BASE_R0, "current_access": "read_write"}
errors = validate_capabilities([bad])
check("R0 with current_access=read_write is rejected", any("R0 requires current_access=read_only" in e for e in errors), f"{errors}")
bad = {**BASE_W1, "current_access": "read_only"}
errors = validate_capabilities([bad])
check(
    "W1 with current_access=read_only is rejected (active write class needs a real write path)",
    any("an active write class" in e for e in errors),
    f"{errors}",
)

print("")
print("[7] Unknown/inferred evidence incorrectly claiming a write path -> FAIL")
bad = {**BASE_W1, "live_proof_status": "unknown"}
errors = validate_capabilities([bad])
check(
    "W1/read_write with live_proof_status=unknown fails",
    any("must not claim an existing write path" in e for e in errors),
    f"{errors}",
)
bad2 = {**BASE_W1, "live_proof_status": "inferred_do_not_write"}
errors = validate_capabilities([bad2])
check(
    "W1/read_write with live_proof_status=inferred_do_not_write fails",
    any("must not claim an existing write path" in e for e in errors),
    f"{errors}",
)

print("")
print("[8] Static operating limit above hardware ceiling -> FAIL")
bad = {**BASE_W1, "limits": {"hardware": {"value": 8000}, "operating": {"value": 9000}, "effective": {"rule": "min(hardware, operating)"}}}
errors = validate_capabilities([bad])
check(
    "limits.operating.value (9000) > limits.hardware.value (8000) is rejected",
    any("exceeds limits.hardware.value" in e for e in errors),
    f"{errors}",
)

print("")
print("[9] Dynamic operating limit with fixed hardware ceiling -> schema PASS")
ok = {**BASE_W1, "limits": {"hardware": {"value": 8000, "unit": "W", "source": "firmware_substitution"}, "operating": {"source_entity": "input_number.ecco_max_grid_charge_power"}, "effective": {"rule": "min(hardware, operating)"}}}
errors = validate_capabilities([ok])
check(
    "a dynamic (entity-sourced) operating limit against a fixed numeric hardware ceiling validates (no live HA state is assumed)",
    errors == [],
    f"{errors}",
)

print("")
print("[10] Effective limit rule other than min(hardware, operating) where required -> FAIL")
bad = {**BASE_W1, "limits": {"hardware": {"value": 8000}, "operating": {"value": 6000}, "effective": {"rule": "some_other_rule"}}}
errors = validate_capabilities([bad])
check("an invalid limits.effective.rule value is rejected", any("is not one of" in e for e in errors), f"{errors}")
bad2 = {**BASE_W1, "limits": {"hardware": {"source": "firmware constant, no numeric value recorded"}, "operating": {}, "effective": {"rule": "min(hardware, operating)"}}}
errors = validate_capabilities([bad2])
check(
    "rule is min(hardware, operating) but operating records neither a value nor a source_entity -> FAIL",
    any("cannot reference a missing tier" in e for e in errors),
    f"{errors}",
)

print("")
print("[11] Grouped/free-text register escape hatch no longer accepted")
bad = {**BASE_W1, "modbus": {"registers": "200-205 (grouped for brevity)", "datatype": "uint16"}}
errors = validate_capabilities([bad])
check(
    "a free-text modbus.registers string is rejected under schema v2 (no more escape hatch)",
    any("free-text string" in e for e in errors),
    f"{errors}",
)

print("")
print("[12] Malformed structured register/range declaration -> FAIL")
bad = {**BASE_W1, "modbus": {"registers": [{"address": "not-a-number"}], "datatype": "uint16"}}
errors = validate_capabilities([bad])
check("a non-integer register address is rejected", any("'address' must be an integer" in e for e in errors), f"{errors}")
bad2 = {**BASE_W1, "modbus": {"registers": [{"address": 101, "bits": "not-a-range"}], "datatype": "uint16"}}
errors = validate_capabilities([bad2])
check("a malformed 'bits' value is rejected", any("malformed 'bits' value" in e for e in errors), f"{errors}")

print("")
print("[13] Two capabilities accidentally claiming the same whole register -> FAIL")
a = {**BASE_R0, "id": "reg_a", "modbus": {"registers": [register(200)], "datatype": "uint16"}}
b = {**BASE_R0, "id": "reg_b", "modbus": {"registers": [register(200)], "datatype": "uint16"}}
errors = validate_capabilities([a, b])
check(
    "two distinct records claiming the same whole register with no shared_with declaration are rejected",
    any("without mutual 'shared_with' declaration" in e for e in errors),
    f"{errors}",
)

print("")
print("[14] Two capabilities intentionally sharing different declared bit ranges -> PASS")
a = {**BASE_R0, "id": "bits_a", "modbus": {"registers": [register(201, bits="0-1", shared_with=["bits_b"])], "datatype": "bitfield_uint16"}}
b = {**BASE_R0, "id": "bits_b", "modbus": {"registers": [register(201, bits="2-4", shared_with=["bits_a"])], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([a, b])
check("mutually-declared disjoint bit ranges on the same register validate cleanly", errors == [], f"{errors}")

print("")
print("[15] Overlapping declared bit ranges without explicit sharing -> FAIL")
a = {**BASE_R0, "id": "overlap_a", "modbus": {"registers": [register(202, bits="0-2")], "datatype": "bitfield_uint16"}}
b = {**BASE_R0, "id": "overlap_b", "modbus": {"registers": [register(202, bits="1-3")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([a, b])
check(
    "genuinely overlapping bit ranges with no shared_with declaration at all are rejected",
    any("without mutual 'shared_with' declaration" in e for e in errors),
    f"{errors}",
)
a2 = {**BASE_R0, "id": "overlap_a2", "modbus": {"registers": [register(203, bits="0-2", shared_with=["overlap_b2"])], "datatype": "bitfield_uint16"}}
b2 = {**BASE_R0, "id": "overlap_b2", "modbus": {"registers": [register(203, bits="1-3", shared_with=["overlap_a2"])], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([a2, b2])
check(
    "partially-overlapping-but-not-identical bit ranges are rejected even WITH a shared_with declaration (not a valid shared-bitfield relationship)",
    any("partially overlap without being identical" in e for e in errors),
    f"{errors}",
)

print("")
print("[16] Identical bit ranges (same field, multiple capability records) -> PASS")
a = {**BASE_R0, "id": "same_field_a", "modbus": {"registers": [register(204, shared_with=["same_field_b"])], "datatype": "uint16"}}
b = {**BASE_R0, "id": "same_field_b", "modbus": {"registers": [register(204, shared_with=["same_field_a"])], "datatype": "uint16"}}
errors = validate_capabilities([a, b])
check("two whole-register records declared as sharing the identical field validate cleanly", errors == [], f"{errors}")

print("")
print("[17] Dependency references valid capability -> PASS")
a = {**BASE_R0, "id": "dep_target", "modbus": {"registers": [register(210)], "datatype": "uint16"}}
b = {**BASE_R0, "id": "dep_source", "modbus": {"registers": [register(211)], "datatype": "uint16"}, "dependencies": {"capabilities": ["dep_target"]}}
errors = validate_capabilities([a, b])
check("a dependency referencing an existing capability id validates cleanly", errors == [], f"{errors}")

print("")
print("[18] Missing dependency capability -> FAIL")
bad = {**BASE_R0, "dependencies": {"capabilities": ["does_not_exist"]}}
errors = validate_capabilities([bad])
check("a dependency referencing a non-existent capability id is rejected", any("references unknown capability id" in e for e in errors), f"{errors}")

print("")
print("[19] Self dependency -> FAIL unless explicitly allowed")
bad = {**BASE_R0, "dependencies": {"capabilities": ["example_r0"]}}
errors = validate_capabilities([bad])
check("a capability depending on itself is rejected by default", any("references itself" in e for e in errors), f"{errors}")
ok = {**BASE_R0, "dependencies": {"capabilities": ["example_r0"]}, "allow_self_dependency": True}
errors = validate_capabilities([ok])
check("a self-dependency is accepted when allow_self_dependency is explicitly set", errors == [], f"{errors}")

print("")
print("[20] Dependency entities/flags structural checks")
bad = {**BASE_R0, "dependencies": {"entities": ["notadomain.not_a_valid_entity_id"]}}
errors = validate_capabilities([bad])
check("a malformed entity id in dependencies.entities is rejected", any("malformed entity id in dependencies.entities" in e for e in errors), f"{errors}")
ok = {**BASE_R0, "dependencies": {"entities": ["input_boolean.ecco_grid_charging_enabled"], "flags": ["some interlock flag"]}}
errors = validate_capabilities([ok])
check("well-formed dependencies.entities/flags validate cleanly", errors == [], f"{errors}")
bad2 = {**BASE_R0, "dependencies": ["not", "a", "mapping"]}
errors = validate_capabilities([bad2])
check("a non-mapping 'dependencies' value (old schema v1 free-text list) is rejected", any("must be a mapping" in e for e in errors), f"{errors}")

print("")
print("[21] Duplicate capability IDs")
errors = validate_capabilities([dict(BASE_R0), {**BASE_R0, "name": "Duplicate", "modbus": {"registers": [register(999)], "datatype": "uint16"}}])
check("two records sharing an id are rejected", any("duplicate capability id" in e for e in errors), f"{errors}")

print("")
print("[22] Missing/invalid write_policy")
errors = validate_capabilities([{k: v for k, v in BASE_R0.items() if k != "write_policy"}])
check("missing write_policy is rejected", any("missing required field 'write_policy'" in e for e in errors), f"{errors}")
errors = validate_capabilities([{**BASE_R0, "write_policy": "W9"}])
check("invalid write_policy value is rejected", any("invalid write_policy" in e for e in errors), f"{errors}")

print("")
print("[23] Writable capability with no register/address")
bad = {**BASE_W1, "modbus": {"registers": [], "datatype": "uint16"}}
errors = validate_capabilities([bad])
check("W1 with no registers recorded is rejected", any("no structured register/address recorded" in e for e in errors), f"{errors}")

print("")
print("[24] Writable capability with unknown datatype")
bad = {**BASE_W1, "modbus": {"registers": [register(101)], "datatype": "unknown"}}
errors = validate_capabilities([bad])
check("W1 with datatype=unknown is rejected", any("datatype is missing/unknown" in e for e in errors), f"{errors}")

print("")
print("[25] Writable capability with no verified/candidate range")
w1_no_range = {k: v for k, v in BASE_W1.items() if k not in ("safe_min", "safe_max")}
errors = validate_capabilities([w1_no_range])
check(
    "W1 with no safe_min/safe_max/enum_mapping/limits/field_bounds is rejected",
    any("requires a machine-checkable bound" in e for e in errors),
    f"{errors}",
)

print("")
print("[25b] W1/W2 must have a MACHINE-CHECKABLE bound - bounds_note alone is not enough (Task 005B section 5)")
w1_bounds_note_only = {**w1_no_range, "bounds_note": "documented as not yet calibrated"}
errors = validate_capabilities([w1_bounds_note_only])
check(
    "W1 + bounds_note only -> FAIL (bounds_note alone does not satisfy an active write class)",
    any("requires a machine-checkable bound" in e for e in errors),
    f"{errors}",
)
w2_no_range = {k: v for k, v in BASE_W2.items() if k not in ("safe_min", "safe_max")}
w2_bounds_note_only = {**w2_no_range, "bounds_note": "documented as not yet calibrated"}
errors = validate_capabilities([w2_bounds_note_only])
check(
    "W2 + bounds_note only -> FAIL",
    any("requires a machine-checkable bound" in e for e in errors),
    f"{errors}",
)
errors = validate_capabilities([dict(BASE_W3)])  # BASE_W3 is current_access=read_only with only a bounds_note
check("W3/read_only + bounds_note only -> PASS (UNKNOWN is preferable to a guessed number for a disabled class)", errors == [], f"{errors}")

print("")
print("[25c] field_bounds as a machine-checkable bound for multi-field packed writes (e.g. RTC)")
w1_field_bounds = {**w1_no_range, "field_bounds": [
    {"field": "year_offset", "min": 0, "max": 255},
    {"field": "month", "min": 1, "max": 12},
]}
errors = validate_capabilities([w1_field_bounds])
check("a well-formed field_bounds list satisfies the W1 machine-checkable-bound requirement", errors == [], f"{errors}")
malformed = {**w1_no_range, "field_bounds": [{"field": "month", "min": 12, "max": 1}]}
errors = validate_capabilities([malformed])
check("a field_bounds entry with min > max is rejected", any("is greater than 'max'" in e for e in errors), f"{errors}")
empty = {**w1_no_range, "field_bounds": []}
errors = validate_capabilities([empty])
check("an empty field_bounds list is rejected (and does not count as a bound)", any("field_bounds" in e for e in errors), f"{errors}")

print("")
print("[26] Invalid min/max")
bad = {**BASE_W1, "safe_min": 100, "safe_max": 0}
errors = validate_capabilities([bad])
check("safe_min > safe_max is rejected", any("greater than safe_max" in e for e in errors), f"{errors}")

print("")
print("[27] Restoration-required write with no restoration specification")
bad = {k: v for k, v in BASE_W1.items() if k != "restoration_possible"}
bad["snapshot_required"] = True
errors = validate_capabilities([bad])
check("snapshot_required=true with no restoration_possible is rejected", any("'restoration_possible' is missing" in e for e in errors), f"{errors}")

print("")
print("[27b] recovery_implementation_status (Phase 0b): distinguishes the snapshot_required "
      "REQUIREMENT from the recovery mechanism's IMPLEMENTATION STATUS")
bad = {**BASE_W1, "recovery_implementation_status": "not_a_real_status"}
errors = validate_capabilities([bad])
check(
    "an invalid recovery_implementation_status value is rejected",
    any("invalid recovery_implementation_status" in e for e in errors),
    f"{errors}",
)
for status in ("required_not_implemented", "partial", "implemented_not_live_proven", "live_proven"):
    ok = {**BASE_W1, "recovery_implementation_status": status}
    errors = validate_capabilities([ok])
    check(f"snapshot_required=true with recovery_implementation_status={status!r} validates", errors == [], f"{errors}")
bad = {**BASE_W1, "snapshot_required": True, "recovery_implementation_status": "not_required"}
errors = validate_capabilities([bad])
check(
    "snapshot_required=true with recovery_implementation_status='not_required' is rejected "
    "(a capability cannot require snapshot/rollback and also claim none is required)",
    any("cannot also claim no recovery mechanism is required" in e for e in errors),
    f"{errors}",
)
bad = {**BASE_R0, "recovery_implementation_status": "partial"}
errors = validate_capabilities([bad])
check(
    "snapshot_required=false with a non-'not_required' recovery_implementation_status is rejected",
    any("must be 'not_required'" in e for e in errors),
    f"{errors}",
)
ok = {**BASE_R0, "recovery_implementation_status": "not_required"}
errors = validate_capabilities([ok])
check("snapshot_required=false with recovery_implementation_status='not_required' validates", errors == [], f"{errors}")

print("")
print("[28] Exact-verification-required write with no verification rule")
bad = {k: v for k, v in BASE_W1.items() if k != "verification_tolerance"}
bad["exact_reread_verification_possible"] = True
errors = validate_capabilities([bad])
check("exact_reread_verification_possible=true with no verification_tolerance is rejected", any("verification_tolerance" in e for e in errors), f"{errors}")

print("")
print("[29] Malformed entity IDs")
bad = {**BASE_R0, "entity_ha_raw": ["notadomain.not_a_valid_entity_id"]}
errors = validate_capabilities([bad])
check("an entity id with an invalid domain prefix is rejected", any("malformed entity id" in e for e in errors), f"{errors}")
ok = {**BASE_R0, "entity_ha_raw": ["sensor.ecco_clock_dongle_ecco_battery_soc"]}
errors = validate_capabilities([ok])
check("a well-formed entity id is accepted", errors == [], f"{errors}")

print("")
print("[30] Missing source/evidence")
bad = {k: v for k, v in BASE_R0.items() if k not in ("firmware_evidence",)}
errors = validate_capabilities([bad])
check("a record with neither firmware_evidence nor ha_evidence is rejected", any("no firmware_evidence or ha_evidence" in e for e in errors), f"{errors}")

print("")
print("[31] End-to-end smoke test against the real registry")
real_errors = validate(DEFAULT_REGISTRY_PATH)
check("the real registry/inverter_capabilities.yaml validates with zero errors", real_errors == [], f"{real_errors}")

# =========================================================================
# Task 005B: final validator/schema hardening pass
# =========================================================================

print("")
print("[32] schema_version is required and must equal 2")


def validate_raw(doc: dict) -> list[str]:
    """Like validate_capabilities(), but writes the whole document as
    given rather than always injecting schema_version: 2 - needed to
    test the schema_version check itself."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump(doc, f)
        path = Path(f.name)
    try:
        return validate(path)
    finally:
        path.unlink(missing_ok=True)


errors = validate_raw({"capabilities": [dict(BASE_R0)]})
check("missing schema_version is rejected", any("missing top-level 'schema_version'" in e for e in errors), f"{errors}")
errors = validate_raw({"schema_version": 1, "capabilities": [dict(BASE_R0)]})
check("schema_version: 1 (stale schema v1) is rejected", any("schema_version is 1" in e for e in errors), f"{errors}")
errors = validate_raw({"schema_version": 3, "capabilities": [dict(BASE_R0)]})
check("schema_version: 3 (unexpected future value) is rejected", any("schema_version is 3" in e for e in errors), f"{errors}")
errors = validate_raw({"schema_version": 2, "capabilities": [dict(BASE_R0)]})
check("schema_version: 2 validates cleanly", errors == [], f"{errors}")

print("")
print("[33] Core required fields (Task 005B section 2) - each missing field is rejected on its own")
for field_name in ("current_access", "live_proof_status", "write_policy", "category", "implementation_status", "name", "safety_impact", "recovery_implementation_status"):
    bad = {k: v for k, v in BASE_R0.items() if k != field_name}
    errors = validate_capabilities([bad])
    check(f"missing '{field_name}' is rejected", any(f"missing required field '{field_name}'" in e for e in errors), f"{errors}")
# An explicit `null` must not be treated as satisfying a required field.
bad_null = {**BASE_R0, "current_access": None}
errors = validate_capabilities([bad_null])
check("an explicit null for a required field is rejected the same as a missing field", any("missing required field 'current_access'" in e for e in errors), f"{errors}")

print("")
print("[34] category must be one of the documented schema-v2 categories")
bad = {**BASE_R0, "category": "not_a_real_category"}
errors = validate_capabilities([bad])
check("an invalid category is rejected", any("invalid category" in e for e in errors), f"{errors}")

print("")
print("[35] modbus required unless the capability explicitly opts out")
bad = {k: v for k, v in BASE_R0.items() if k != "modbus"}
errors = validate_capabilities([bad])
check("a capability with no 'modbus' and no physical_register: false is rejected", any("'modbus' is missing/null" in e for e in errors), f"{errors}")
ok = {**bad, "physical_register": False}
errors = validate_capabilities([ok])
check("physical_register: false explicitly permits modbus: null (genuine derived/meta capability)", errors == [], f"{errors}")

print("")
print("[36] Physical register/bit bounds (Task 005B section 3)")
bad = {**BASE_R0, "modbus": {"registers": [register(-1)], "datatype": "uint16"}}
errors = validate_capabilities([bad])
check("a negative register address is rejected", any("out of the physical Modbus register bounds" in e for e in errors), f"{errors}")
bad = {**BASE_R0, "modbus": {"registers": [register(70000)], "datatype": "uint16"}}
errors = validate_capabilities([bad])
check("a register address above 65535 is rejected", any("out of the physical Modbus register bounds" in e for e in errors), f"{errors}")
bad = {**BASE_R0, "modbus": {"registers": [register(100, bits="16")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([bad])
check("bits: '16' (out of a 16-bit register's 0-15 range) is rejected", any("out of the physical 16-bit register bounds" in e for e in errors), f"{errors}")
bad = {**BASE_R0, "modbus": {"registers": [register(100, bits="0-16")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([bad])
check("bits: '0-16' is rejected", any("out of the physical 16-bit register bounds" in e for e in errors), f"{errors}")
bad = {**BASE_R0, "modbus": {"registers": [register(100, bits="10-25")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([bad])
check("bits: '10-25' is rejected", any("out of the physical 16-bit register bounds" in e for e in errors), f"{errors}")
bad = {**BASE_R0, "modbus": {"registers": [register(100, bits="7-3")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([bad])
check("bits: '7-3' (start > end) is rejected", any("'bits' range '7-3' has start > end" in e for e in errors), f"{errors}")
ok = {**BASE_R0, "modbus": {"registers": [register(0)], "datatype": "uint16"}}
errors = validate_capabilities([ok])
check("register address 0 (the physical minimum) validates cleanly", errors == [], f"{errors}")
ok = {**BASE_R0, "modbus": {"registers": [register(65535, bits="15")], "datatype": "bitfield_uint16"}}
errors = validate_capabilities([ok])
check("register address 65535 / bit 15 (the physical maximums) validate cleanly", errors == [], f"{errors}")

print("")
print("[37] shared_with metadata self-consistency (Task 005B section 4)")
bad = {**BASE_R0, "modbus": {"registers": [register(230, shared_with=["capability_that_does_not_exist"])], "datatype": "uint16"}}
errors = validate_capabilities([bad])
check(
    "shared_with referencing a capability id that doesn't exist anywhere is rejected",
    any("is not a known capability id" in e for e in errors),
    f"{errors}",
)
a = {**BASE_R0, "id": "reg400_owner", "modbus": {"registers": [register(400)], "datatype": "uint16"}}
b = {**BASE_R0, "id": "unrelated_on_reg500", "modbus": {"registers": [register(500)], "datatype": "uint16"}}
bad = {**BASE_R0, "id": "stale_sharer", "modbus": {"registers": [register(230, shared_with=["unrelated_on_reg500"])], "datatype": "uint16"}}
errors = validate_capabilities([a, b, bad])
check(
    "shared_with referencing a real capability id that does NOT itself claim the same register is rejected (stale metadata)",
    any("does not itself claim register 230" in e for e in errors),
    f"{errors}",
)
bad_self = {**BASE_R0, "modbus": {"registers": [register(230, shared_with=["example_r0"])], "datatype": "uint16"}}
errors = validate_capabilities([bad_self])
check("shared_with referencing itself is rejected", any("references itself" in e for e in errors), f"{errors}")
bad_dupe = {**BASE_R0, "modbus": {"registers": [register(230, shared_with=["some_id", "some_id"])], "datatype": "uint16"}}
errors = validate_capabilities([bad_dupe])
check("shared_with listing the same capability id twice is rejected", any("more than once" in e for e in errors), f"{errors}")

print("")
print("[38] W3 read/write proof consistency (Task 005B section 6)")
for bad_evidence in ("unknown", "inferred_do_not_write", "repository_inferred_read_only", "live_proven_read"):
    bad = {**BASE_W3, "current_access": "read_write", "live_proof_status": bad_evidence}
    errors = validate_capabilities([bad])
    check(
        f"W3 + current_access=read_write + live_proof_status={bad_evidence} is rejected",
        any("may only become actionable" in e for e in errors),
        f"{errors}",
    )
ok = {**BASE_W3, "current_access": "read_write", "live_proof_status": "live_proven_write"}
errors = validate_capabilities([ok])
check("W3 + current_access=read_write + live_proof_status=live_proven_write validates cleanly", errors == [], f"{errors}")

# =========================================================================
# Task 005B section 8: additional static sanity assertions against the
# real registry, read directly (not just "validate() returns []") so a
# regression in the underlying data - not just the validator logic -
# would be caught even if some future validator bug went blind to it.
# =========================================================================

print("")
print("[39] Real-registry sanity assertions (Task 005B section 8)")
_real_data = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
_real_caps = _real_data["capabilities"]
_real_by_id = {c["id"]: c for c in _real_caps if isinstance(c, dict) and c.get("id")}

check("exactly one schema_version, equal to 2", _real_data.get("schema_version") == 2, f"{_real_data.get('schema_version')!r}")

_free_text_registers = [
    c["id"] for c in _real_caps
    if isinstance((c.get("modbus") or {}).get("registers"), str)
]
check("no free-text modbus.registers anywhere in the real registry", _free_text_registers == [], f"{_free_text_registers}")

_bad_bits = []
for c in _real_caps:
    for r in ((c.get("modbus") or {}).get("registers") or []):
        if not isinstance(r, dict):
            continue
        bits = r.get("bits")
        if bits is None:
            continue
        if "-" in bits:
            lo, hi = (int(x) for x in bits.split("-"))
        else:
            lo = hi = int(bits)
        if not (0 <= lo <= 15 and 0 <= hi <= 15 and lo <= hi):
            _bad_bits.append((c["id"], r.get("address"), bits))
check("no out-of-range/malformed bit declarations in the real registry", _bad_bits == [], f"{_bad_bits}")

_stale_shared_with = []
for c in _real_caps:
    for r in ((c.get("modbus") or {}).get("registers") or []):
        if not isinstance(r, dict):
            continue
        for target in (r.get("shared_with") or []):
            target_cap = _real_by_id.get(target)
            if target_cap is None:
                _stale_shared_with.append((c["id"], target, "unknown id"))
                continue
            target_addresses = {
                tr.get("address") for tr in ((target_cap.get("modbus") or {}).get("registers") or []) if isinstance(tr, dict)
            }
            if r.get("address") not in target_addresses:
                _stale_shared_with.append((c["id"], target, f"does not claim register {r.get('address')}"))
check("every shared_with target in the real registry exists and actually claims the shared register", _stale_shared_with == [], f"{_stale_shared_with}")

_w1w2_no_bound = []
for c in _real_caps:
    if c.get("write_policy") not in ("W1", "W2"):
        continue
    has_bound = (
        isinstance(c.get("safe_min"), (int, float)) or isinstance(c.get("safe_max"), (int, float))
        or bool(c.get("enum_mapping"))
        or isinstance(((c.get("limits") or {}).get("hardware") or {}).get("value"), (int, float))
        or bool(c.get("field_bounds"))
    )
    if not has_bound:
        _w1w2_no_bound.append(c["id"])
check("every W1/W2 capability in the real registry has a machine-checkable bound (not bounds_note alone)", _w1w2_no_bound == [], f"{_w1w2_no_bound}")

_actionable_w3_without_proof = [
    c["id"] for c in _real_caps
    if c.get("write_policy") == "W3" and c.get("current_access") == "read_write" and c.get("live_proof_status") != "live_proven_write"
]
check("every W3 capability is non-actionable unless live_proven_write", _actionable_w3_without_proof == [], f"{_actionable_w3_without_proof}")

_reg330 = _real_by_id.get("register_330_reserved_bits")
check(
    "register 330's reserved-bits remainder stays WX (genuinely undecoded, not guessed)",
    _reg330 is not None and _reg330.get("write_policy") == "WX",
    f"{_reg330}",
)

# Pinned per Task 005B section 6 ("Do NOT change the current nine W3 battery
# records to writable") - this list intentionally hardcodes those nine ids so
# an accidental current_access flip in future editing is caught immediately,
# even though the total capability count is deliberately NOT hardcoded below.
_W3_BATTERY_IDS = [
    "battery_equalization_voltage", "battery_absorption_voltage", "battery_float_voltage",
    "battery_capacity_ah", "battery_max_charge_current", "battery_max_discharge_current",
    "battery_shutdown_soc", "battery_restart_soc", "battery_low_warning_soc",
]
_accidentally_writable = [
    cid for cid in _W3_BATTERY_IDS
    if _real_by_id.get(cid, {}).get("current_access") != "read_only"
]
check("none of the nine pinned W3 battery records have accidentally acquired current_access=read_write", _accidentally_writable == [], f"{_accidentally_writable}")
check("all nine pinned W3 battery records still exist in the registry", all(cid in _real_by_id for cid in _W3_BATTERY_IDS), f"{[cid for cid in _W3_BATTERY_IDS if cid not in _real_by_id]}")

print("")
print("[40] recovery_implementation_status (Phase 0b): pinned per-capability status matches the")
print("     evidence recorded in CURRENT_STATE.md / docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md")

_missing_recovery_status = [c["id"] for c in _real_caps if not c.get("recovery_implementation_status")]
check("every real-registry capability declares recovery_implementation_status", _missing_recovery_status == [], f"{_missing_recovery_status}")

_live_proven_recovery = sorted(c["id"] for c in _real_caps if c.get("recovery_implementation_status") == "live_proven")
check(
    "post-hardening live-proven durable recovery is limited to register 244 plus Free Power's "
    "230/232 records, each backed by a recorded live round trip (free_power_transaction itself left "
    "this list on 2026-09-23 - see below)",
    _live_proven_recovery == [
        "grid_charge_current",
        "grid_export_policy",
        "tou_global_grid_charge_enable",
    ],
    f"{_live_proven_recovery}",
)

_free_power_group_status = {
    cid: _real_by_id.get(cid, {}).get("recovery_implementation_status")
    for cid in ("free_power_transaction", "grid_charge_current", "tou_global_grid_charge_enable")
}
check(
    "Free Power's 230/232 records stay live_proven after the 2026-09-22 post-hardening "
    "500 W / 1-minute live start-to-automatic-restore round trip",
    _free_power_group_status["grid_charge_current"] == "live_proven"
    and _free_power_group_status["tou_global_grid_charge_enable"] == "live_proven",
    f"{_free_power_group_status}",
)
check(
    "free_power_transaction is implemented_not_live_proven (2026-09-23): the historical 14-register "
    "mechanism is live-proven, but the 20-register form that also owns/restores TOU Power 256-261 has "
    "had no live round trip yet - it must not claim live_proven (or yes_live_proven restoration) until "
    "one is recorded",
    _free_power_group_status["free_power_transaction"] == "implemented_not_live_proven"
    and _real_by_id.get("free_power_transaction", {}).get("restoration_possible") != "yes_live_proven",
    f"{_free_power_group_status}; restoration_possible="
    f"{_real_by_id.get('free_power_transaction', {}).get('restoration_possible')}",
)

_tou_not_partial = [
    c["id"] for c in _real_caps
    if c["id"].startswith("tou_slot_") and c.get("snapshot_required") is True
    and c.get("recovery_implementation_status") != "partial"
]
check(
    "every snapshot-requiring six-slot TOU field is 'partial' (cache-based restore only, not the "
    "durable transaction rollback mechanism register 244 has - docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md risk R1)",
    _tou_not_partial == [],
    f"{_tou_not_partial}",
)

# Deliberately NOT asserting an exact total capability count here (Task 005B
# section 8) - a legitimate future capability addition should not fail this
# test merely because len(_real_caps) changed. A sanity floor is still useful
# to catch a catastrophic truncation of the file.
check(f"the real registry has a plausible number of records ({len(_real_caps)}, expected >= 150)", len(_real_caps) >= 150, str(len(_real_caps)))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All capability registry validator offline tests PASSED.")

print("")
print("This proves the VALIDATOR's rules are correctly implemented, and that")
print("the real registry file currently satisfies every one of them. It does")
print("NOT prove any register/value/limit recorded in the registry is itself")
print("correct against real hardware beyond what CURRENT_STATE.md/CHANGELOG.md")
print("already documents as live-proven - see docs/INVERTER_CAPABILITY_REGISTRY.md.")

if FAILURES:
    sys.exit(1)
