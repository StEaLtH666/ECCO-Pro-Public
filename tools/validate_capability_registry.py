#!/usr/bin/env python3
"""Validator for registry/inverter_capabilities.yaml (schema_version 2).

Static checks only - does not connect to Home Assistant, ESPHome,
InfluxDB, or the inverter. See docs/INVERTER_CAPABILITY_REGISTRY.md for
the format this validates against.

Importable: `validate(path) -> list[str]` returns a list of human-
readable error strings (empty if the registry is valid), used both by
this script's own CLI and by tools/validate_repo.py's integration call.

Schema v2 (Task 005A) replaces schema v1's `safety_class`/`read_write`
with a two-axis model (`write_policy` / `current_access`, see section 3
of Task 005A) and replaces free-text `modbus.registers` strings with a
structured, machine-checkable register/bit-range/sharing declaration
(section 2) - the free-text escape hatch from schema v1 no longer
validates.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "registry" / "inverter_capabilities.yaml"

REQUIRED_SCHEMA_VERSION = 2

VALID_WRITE_POLICIES = {"R0", "W1", "W2", "W3", "WX"}
WRITE_CANDIDATE_POLICIES = {"W1", "W2", "W3"}
ACTIVE_WRITE_POLICIES = {"W1", "W2"}  # policies that REQUIRE current_access=read_write
MACHINE_CHECKABLE_ONLY_POLICIES = {"W1", "W2"}  # policies for which bounds_note alone is NOT sufficient
VALID_CURRENT_ACCESS = {"read_only", "read_write", "write_only"}
VALID_EVIDENCE_LEVELS = {
    "unknown",
    "repository_inferred_read_only",
    "inferred_do_not_write",
    "documented_not_live_proven",
    "live_proven_read",
    "live_proven_write",
}
INFERRED_OR_UNKNOWN_EVIDENCE = {
    "unknown",
    "repository_inferred_read_only",
    "inferred_do_not_write",
}
VALID_EFFECTIVE_RULES = {
    "min(hardware, operating)",
    "hardware_only",
    "operating_only",
    "not_applicable",
}
# recovery_implementation_status (Phase 0b repo hardening) distinguishes the
# SAFETY REQUIREMENT (snapshot_required: true/false) from the IMPLEMENTATION
# STATUS of the recovery mechanism itself - a capability can correctly require
# snapshot/rollback while the durable mechanism for it does not exist yet, is
# only partially delivered, or is deployed but not yet live-proven. See
# docs/INVERTER_CAPABILITY_REGISTRY.md "Recovery implementation status".
VALID_RECOVERY_IMPLEMENTATION_STATUSES = {
    "not_required",
    "required_not_implemented",
    "partial",
    "implemented_not_live_proven",
    "live_proven",
}
VALID_CATEGORIES = {
    "rtc",
    "tou_schedule",
    "grid_charge",
    "free_power",
    "battery",
    "pv",
    "grid",
    "load",
    "inverter_output",
    "generator",
    "aux",
    "energy_management",
    "energy",
    "status",
    "diagnostic",
}
# Required on every capability record (Task 005B section 2). 'id' is
# validated separately (snake_case format + uniqueness); 'write_policy',
# 'current_access', 'live_proof_status' and 'safety_impact' are also
# validated for their own semantics further down, but must first be
# PRESENT - a missing field is not the same as an invalid one and both
# are reported.
REQUIRED_STRING_FIELDS = (
    "name",
    "category",
    "current_access",
    "write_policy",
    "live_proof_status",
    "implementation_status",
    "safety_impact",
    "recovery_implementation_status",
)

_ENTITY_ID_RE = re.compile(
    r"^(sensor|binary_sensor|number|select|switch|button|text_sensor|input_number|input_boolean|input_select)\."
    r"[a-z0-9_]+$"
)
_BITS_RE = re.compile(r"^\d{1,2}(-\d{1,2})?$")
_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MIN_ADDRESS, _MAX_ADDRESS = 0, 65535
_MIN_BIT, _MAX_BIT = 0, 15


def _entity_ids_from(value) -> list[str]:
    """entity_ha_raw/entity_ha_canonical/dependencies.entities may be a
    list, a single string, or contain free-text annotations like
    '(derived, ...)' - extract just the leading dotted-entity-id
    token(s), since this registry intentionally allows explanatory
    suffixes."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    ids = []
    for item in items:
        if not isinstance(item, str):
            continue
        token = item.split(" ")[0].strip()
        if "." in token:
            ids.append(token)
    return ids


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_field_bounds(field_bounds, loc: str, errors: list[str]) -> bool:
    """`field_bounds` is a machine-checkable-bound mechanism for a
    multi-field packed write (e.g. RTC's packed date/time, where no
    single safe_min/safe_max pair makes sense) - a list of
    {field, min, max} entries, each numerically bounded. Returns True
    if `field_bounds` is present and valid (i.e. counts as a real
    machine-checkable bound); False if absent. Malformed-but-present
    field_bounds is reported as an error rather than silently treated
    as absent."""
    if field_bounds is None:
        return False
    if not isinstance(field_bounds, list) or not field_bounds:
        errors.append(f"{loc}: 'field_bounds' must be a non-empty list of {{field, min, max}} entries")
        return False
    ok = True
    for i, entry in enumerate(field_bounds):
        entry_loc = f"{loc}: field_bounds[{i}]"
        if not isinstance(entry, dict) or not entry.get("field"):
            errors.append(f"{entry_loc}: must be a mapping with a non-empty 'field' name")
            ok = False
            continue
        lo, hi = entry.get("min"), entry.get("max")
        if not _is_number(lo) or not _is_number(hi):
            errors.append(f"{entry_loc}: 'min'/'max' must both be numeric (field {entry.get('field')!r})")
            ok = False
        elif lo > hi:
            errors.append(f"{entry_loc}: 'min' ({lo}) is greater than 'max' ({hi}) for field {entry.get('field')!r}")
            ok = False
    return ok


def _bits_to_set(bits) -> set[int] | None:
    """Returns the set of bit indices a 'bits' declaration covers, or
    None if `bits` is absent/null (meaning: the whole 16-bit register).
    Assumes `bits` has already passed `_validate_bits` - out-of-range
    values are reported there, not silently swallowed here."""
    if bits is None:
        return None
    if not isinstance(bits, str) or not _BITS_RE.match(bits):
        return set()  # malformed - caller reports this separately
    if "-" in bits:
        lo, hi = (int(x) for x in bits.split("-"))
        if lo > hi:
            return set()
        return set(range(lo, hi + 1))
    return {int(bits)}


def _validate_bits(bits_raw: str, entry_loc: str, errors: list[str]) -> bool:
    """Validates a 'bits' string against the physical bounds of a 16-bit
    Modbus register (0-15). Returns True if valid. Assumes `bits_raw`
    already matched `_BITS_RE`'s syntax (digits and an optional '-')."""
    if "-" in bits_raw:
        lo, hi = (int(x) for x in bits_raw.split("-"))
        if not (_MIN_BIT <= lo <= _MAX_BIT) or not (_MIN_BIT <= hi <= _MAX_BIT):
            errors.append(
                f"{entry_loc}: 'bits' range {bits_raw!r} is out of the physical 16-bit register "
                f"bounds ({_MIN_BIT}-{_MAX_BIT})"
            )
            return False
        if lo > hi:
            errors.append(f"{entry_loc}: 'bits' range {bits_raw!r} has start > end")
            return False
        return True
    n = int(bits_raw)
    if not (_MIN_BIT <= n <= _MAX_BIT):
        errors.append(f"{entry_loc}: 'bits' value {bits_raw!r} is out of the physical 16-bit register bounds ({_MIN_BIT}-{_MAX_BIT})")
        return False
    return True


class _RegisterClaim:
    __slots__ = ("cap_id", "bits", "bits_raw", "shared_with")

    def __init__(self, cap_id, bits, bits_raw, shared_with):
        self.cap_id = cap_id
        self.bits = bits  # set[int] or None (whole register)
        self.bits_raw = bits_raw
        self.shared_with = shared_with


def _parse_registers(cap: dict, cap_id, loc: str, errors: list[str]) -> list[dict]:
    """Validates and returns the structured `modbus.registers` list, or
    [] if malformed/absent (errors are appended, not raised)."""
    modbus = cap.get("modbus") or {}
    regs = modbus.get("registers")

    if regs is None:
        return []
    if isinstance(regs, str):
        errors.append(
            f"{loc}: modbus.registers is a free-text string ({regs!r}) - schema v2 requires a "
            f"structured list of {{address, bits?, shared_with?}} entries; free-text is no longer "
            f"a valid escape hatch (see docs/INVERTER_CAPABILITY_REGISTRY.md 'Structured register "
            f"declarations')"
        )
        return []
    if not isinstance(regs, list) or not regs:
        errors.append(f"{loc}: modbus.registers must be a non-empty list of {{address, ...}} entries")
        return []

    parsed = []
    for i, entry in enumerate(regs):
        entry_loc = f"{loc}: modbus.registers[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{entry_loc}: must be a mapping with an 'address' key, got {entry!r}")
            continue
        address = entry.get("address")
        if not isinstance(address, int) or isinstance(address, bool):
            errors.append(f"{entry_loc}: 'address' must be an integer, got {address!r}")
            continue
        if not (_MIN_ADDRESS <= address <= _MAX_ADDRESS):
            errors.append(f"{entry_loc}: 'address' {address} is out of the physical Modbus register bounds ({_MIN_ADDRESS}-{_MAX_ADDRESS})")
            continue
        bits_raw = entry.get("bits")
        if bits_raw is not None:
            if not isinstance(bits_raw, str) or not _BITS_RE.match(bits_raw):
                errors.append(f"{entry_loc}: malformed 'bits' value {bits_raw!r} (expected e.g. '0-1' or '3')")
                continue
            if not _validate_bits(bits_raw, entry_loc, errors):
                continue
        shared_with = entry.get("shared_with") or []
        if not isinstance(shared_with, list) or not all(isinstance(s, str) for s in shared_with):
            errors.append(f"{entry_loc}: 'shared_with' must be a list of capability id strings")
            continue
        if cap_id is not None and cap_id in shared_with:
            errors.append(f"{entry_loc}: 'shared_with' references itself ('{cap_id}') - a capability cannot share a register with itself")
            continue
        if len(shared_with) != len(set(shared_with)):
            dupes = sorted({s for s in shared_with if shared_with.count(s) > 1})
            errors.append(f"{entry_loc}: 'shared_with' lists the same capability id more than once: {dupes}")
            continue
        parsed.append({"address": address, "bits": bits_raw, "shared_with": shared_with})
    return parsed


def _validate_shared_with_references(
    claims_by_address: dict[int, list[_RegisterClaim]], seen_ids: dict[str, int], errors: list[str]
) -> None:
    """Validates the `shared_with` metadata itself (Task 005B section 4),
    independent of whether the pairwise mutual-sharing check below finds
    a matching claim - this catches stale/wrong references even when a
    register has only one real claimant."""
    for address, claims in claims_by_address.items():
        claimant_ids = {c.cap_id for c in claims}
        for claim in claims:
            for target in claim.shared_with:
                if target not in seen_ids:
                    errors.append(
                        f"register {address}: capability '{claim.cap_id}' declares shared_with "
                        f"'{target}', which is not a known capability id in this registry"
                    )
                elif target not in claimant_ids:
                    errors.append(
                        f"register {address}: capability '{claim.cap_id}' declares shared_with "
                        f"'{target}', but '{target}' does not itself claim register {address} - "
                        f"stale or incorrect shared_with metadata"
                    )


def _validate_register_sharing(claims_by_address: dict[int, list[_RegisterClaim]], errors: list[str]) -> None:
    for address, claims in claims_by_address.items():
        if len(claims) < 2:
            continue
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                a, b = claims[i], claims[j]
                if a.cap_id == b.cap_id:
                    continue  # same capability legitimately touching the register twice (e.g. re-declared)
                mutual = b.cap_id in a.shared_with and a.cap_id in b.shared_with
                if not mutual:
                    errors.append(
                        f"register {address}: claimed by both '{a.cap_id}' and '{b.cap_id}' without "
                        f"mutual 'shared_with' declaration on both sides - if this is intentional "
                        f"register sharing, each record's registers[].shared_with must list the other "
                        f"capability's id; if accidental, fix the duplicate mapping"
                    )
                    continue
                # Declared shared - sanity-check the bit ranges are consistent. Two relationships are
                # valid: (1) IDENTICAL bits (including both None/whole-register) - the same physical
                # field represented by two capability records (e.g. two write mechanisms that both
                # target the same sub-field, or the same whole-register value under two UI-facing
                # labels); (2) DISJOINT bits - genuinely different sub-fields of one register. Any
                # other relationship (one None/one explicit, or a partial-but-not-identical overlap)
                # is contradictory and not a valid shared-bitfield declaration.
                if a.bits == b.bits:
                    continue  # identical (including both None) - same field, multiple records - OK
                if a.bits is None or b.bits is None:
                    errors.append(
                        f"register {address}: '{a.cap_id}' (bits={a.bits_raw!r}) and '{b.cap_id}' "
                        f"(bits={b.bits_raw!r}) declare shared_with each other but one covers the "
                        f"whole register and the other a sub-field - this is contradictory, not a "
                        f"valid shared-bitfield declaration"
                    )
                    continue
                if a.bits & b.bits:
                    errors.append(
                        f"register {address}: '{a.cap_id}' (bits={a.bits_raw!r}) and '{b.cap_id}' "
                        f"(bits={b.bits_raw!r}) declare shared_with each other but their bit ranges "
                        f"partially overlap without being identical ({sorted(a.bits & b.bits)}) - a "
                        f"valid shared-bitfield declaration requires either identical or disjoint bit "
                        f"ranges"
                    )


def validate(path: Path = DEFAULT_REGISTRY_PATH) -> list[str]:
    errors: list[str] = []

    if not path.exists():
        return [f"{path}: registry file does not exist"]

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return [f"{path}: YAML parse failed: {exc}"]

    schema_version = data.get("schema_version")
    if schema_version is None:
        errors.append(f"{path}: missing top-level 'schema_version' - this validator requires {REQUIRED_SCHEMA_VERSION}")
    elif schema_version != REQUIRED_SCHEMA_VERSION:
        errors.append(
            f"{path}: schema_version is {schema_version!r}, but this validator only understands "
            f"{REQUIRED_SCHEMA_VERSION} - either the registry is stale (schema v1) or was bumped "
            f"ahead of the validator; update one to match the other rather than validating against "
            f"a version mismatch"
        )
    if errors:
        # A wrong/missing schema_version makes every other check's assumptions unreliable
        # (e.g. schema v1's free-text modbus.registers would otherwise just look malformed
        # record-by-record instead of being flagged as a version problem) - fail fast.
        return errors

    caps = data.get("capabilities")
    if not isinstance(caps, list) or not caps:
        return [f"{path}: 'capabilities' must be a non-empty list"]

    seen_ids: dict[str, int] = {}
    claims_by_address: dict[int, list[_RegisterClaim]] = {}

    for idx, cap in enumerate(caps):
        loc = f"capabilities[{idx}]"
        if not isinstance(cap, dict):
            errors.append(f"{loc}: not a mapping")
            continue

        cap_id = cap.get("id")
        loc = f"capability '{cap_id}'" if cap_id else loc

        # --- id ---------------------------------------------------------
        if not cap_id or not isinstance(cap_id, str):
            errors.append(f"{loc}: missing or non-string 'id'")
        elif not _CAPABILITY_ID_RE.match(cap_id):
            errors.append(f"{loc}: 'id' must be snake_case (got {cap_id!r})")
        else:
            if cap_id in seen_ids:
                errors.append(f"{loc}: duplicate capability id (also used by capabilities[{seen_ids[cap_id]}])")
            seen_ids[cap_id] = idx

        # --- required core fields (Task 005B section 2) -----------------
        # A required classification field left as an explicit `null` in
        # YAML is still missing - None is never accepted as a substitute
        # for a real answer on these fields.
        for field_name in REQUIRED_STRING_FIELDS:
            if not cap.get(field_name):
                errors.append(f"{loc}: missing required field '{field_name}'")

        category = cap.get("category")
        if category is not None and category not in VALID_CATEGORIES:
            errors.append(f"{loc}: invalid category {category!r} (must be one of {sorted(VALID_CATEGORIES)})")

        # --- modbus required unless explicitly a non-register capability ---
        modbus_block = cap.get("modbus")
        if modbus_block is None:
            if cap.get("physical_register") is not False:
                errors.append(
                    f"{loc}: 'modbus' is missing/null - if this capability genuinely has no physical "
                    f"Modbus register (a derived/meta value), set 'physical_register: false' explicitly "
                    f"to document that rather than silently omitting 'modbus'"
                )
        elif not isinstance(modbus_block, dict):
            errors.append(f"{loc}: 'modbus' must be a mapping")

        # --- write_policy / current_access -------------------------------
        write_policy = cap.get("write_policy")
        if write_policy is not None and write_policy not in VALID_WRITE_POLICIES:
            errors.append(f"{loc}: invalid write_policy {write_policy!r} (must be one of {sorted(VALID_WRITE_POLICIES)})")

        current_access = cap.get("current_access")
        if current_access is not None and current_access not in VALID_CURRENT_ACCESS:
            errors.append(f"{loc}: invalid current_access {current_access!r}")

        live_proof = cap.get("live_proof_status")
        if live_proof is not None and live_proof not in VALID_EVIDENCE_LEVELS:
            errors.append(f"{loc}: invalid live_proof_status {live_proof!r}")

        # --- recovery_implementation_status (Phase 0b repo hardening) -------
        # This is deliberately checked on EVERY capability, not only write
        # candidates: snapshot_required/recovery_implementation_status must be
        # in sync everywhere, including R0/WX records where both are trivially
        # "not required".
        snapshot_required = cap.get("snapshot_required")
        recovery_status = cap.get("recovery_implementation_status")
        if recovery_status is not None and recovery_status not in VALID_RECOVERY_IMPLEMENTATION_STATUSES:
            errors.append(
                f"{loc}: invalid recovery_implementation_status {recovery_status!r} "
                f"(must be one of {sorted(VALID_RECOVERY_IMPLEMENTATION_STATUSES)})"
            )
        elif recovery_status is not None:
            if snapshot_required is True and recovery_status == "not_required":
                errors.append(
                    f"{loc}: snapshot_required is true but recovery_implementation_status is "
                    f"'not_required' - a capability that requires snapshot/rollback cannot also "
                    f"claim no recovery mechanism is required"
                )
            if snapshot_required is False and recovery_status != "not_required":
                errors.append(
                    f"{loc}: snapshot_required is false but recovery_implementation_status is "
                    f"{recovery_status!r} - a capability with no snapshot requirement must be "
                    f"'not_required', not a partial/implemented/live-proven recovery status"
                )

        # --- access/policy semantics (Task 005A section 3) ----------------
        if write_policy == "R0" and current_access not in (None, "read_only"):
            errors.append(
                f"{loc}: write_policy is R0 (no ECCO write intended) but current_access is "
                f"{current_access!r} - R0 requires current_access=read_only"
            )
        if write_policy == "WX" and current_access == "read_write":
            errors.append(f"{loc}: write_policy is WX but current_access is 'read_write' - WX must default to non-actionable")
        if write_policy in ACTIVE_WRITE_POLICIES and current_access == "read_only":
            errors.append(
                f"{loc}: write_policy is {write_policy!r} (an active write class) but current_access "
                f"is 'read_only' - W1/W2 require a write path to actually exist; a currently-read-only "
                f"high-impact candidate should be classified W3 instead"
            )
        # write_policy W3 may legitimately be either read_only (disabled pending proof, the
        # normal/default state) or read_write - but a W3 becoming read_write is a high-impact
        # capability becoming genuinely actionable, so it requires the strongest evidence level,
        # not merely "not unknown" (Task 005B section 6). Yaml alone flipping current_access must
        # not be enough to make a battery-voltage-class control actionable.
        if write_policy == "W3" and current_access == "read_write" and live_proof != "live_proven_write":
            errors.append(
                f"{loc}: write_policy is W3 and current_access is 'read_write', but live_proof_status "
                f"is {live_proof!r}, not 'live_proven_write' - a W3 capability may only become "
                f"actionable (current_access: read_write) once its write path has actually been "
                f"exercised and verified against real hardware, not merely inferred, documented, or "
                f"proven for reads only"
            )

        if current_access == "read_write" and live_proof in INFERRED_OR_UNKNOWN_EVIDENCE:
            errors.append(
                f"{loc}: current_access is 'read_write' but live_proof_status is {live_proof!r} - "
                f"an inferred/unknown capability must not claim an existing write path"
            )
        if current_access == "read_only" and live_proof == "live_proven_write":
            errors.append(f"{loc}: current_access is 'read_only' but live_proof_status is 'live_proven_write'")

        if write_policy in WRITE_CANDIDATE_POLICIES and not cap.get("write_policy_reason"):
            errors.append(f"{loc}: write_policy {write_policy!r} requires a non-empty 'write_policy_reason'")

        # --- structured registers ------------------------------------------
        registers = _parse_registers(cap, cap_id, loc, errors)
        modbus = cap.get("modbus") or {}

        if write_policy in WRITE_CANDIDATE_POLICIES:
            if not registers:
                errors.append(f"{loc}: write_policy {write_policy!r} but no structured register/address recorded")

            datatype = modbus.get("datatype")
            if not datatype or datatype == "unknown":
                errors.append(f"{loc}: write_policy {write_policy!r} but datatype is missing/unknown")

            safe_min, safe_max = cap.get("safe_min"), cap.get("safe_max")
            limits = cap.get("limits") or {}
            hw_value = (limits.get("hardware") or {}).get("value")
            field_bounds = cap.get("field_bounds")
            has_machine_checkable_bound = (
                _is_number(safe_min)
                or _is_number(safe_max)
                or bool(cap.get("enum_mapping"))
                or _is_number(hw_value)
                or _validate_field_bounds(field_bounds, loc, errors)
            )
            # W1/W2 mean an ACTIVE write capability - a real, mechanically
            # checkable domain is required (Task 005B section 5). A prose
            # 'bounds_note' alone is not sufficient for these classes, even
            # though it remains an honest and acceptable answer for W3/WX/R0
            # (where UNKNOWN is preferable to a guessed number).
            if write_policy in MACHINE_CHECKABLE_ONLY_POLICIES:
                if not has_machine_checkable_bound:
                    errors.append(
                        f"{loc}: write_policy {write_policy!r} requires a machine-checkable bound "
                        f"(safe_min/safe_max, enum_mapping, limits.hardware.value, or field_bounds) - "
                        f"a free-text 'bounds_note' alone does not satisfy this for an active write class"
                    )
            else:
                has_range = has_machine_checkable_bound or bool(cap.get("bounds_note"))
                if not has_range:
                    errors.append(
                        f"{loc}: write_policy {write_policy!r} but no verified/candidate range (safe_min/"
                        f"safe_max, enum_mapping, limits.hardware.value, field_bounds, or bounds_note) "
                        f"is recorded"
                    )

            if cap.get("exact_reread_verification_possible") is True and not cap.get("verification_tolerance"):
                errors.append(
                    f"{loc}: exact_reread_verification_possible is true but 'verification_tolerance' is missing"
                )
            if cap.get("snapshot_required") is True and not cap.get("restoration_possible"):
                errors.append(f"{loc}: snapshot_required is true but 'restoration_possible' is missing")

        # --- min/max sanity -------------------------------------------------
        safe_min, safe_max = cap.get("safe_min"), cap.get("safe_max")
        if _is_number(safe_min) and _is_number(safe_max) and safe_min > safe_max:
            errors.append(f"{loc}: safe_min ({safe_min}) is greater than safe_max ({safe_max})")

        # --- structured limits (Task 005A section 4) ------------------------
        limits = cap.get("limits")
        if limits is not None:
            if not isinstance(limits, dict):
                errors.append(f"{loc}: 'limits' must be a mapping")
            else:
                hw = limits.get("hardware") or {}
                op = limits.get("operating") or {}
                eff = limits.get("effective") or {}
                hw_value, op_value = hw.get("value"), op.get("value")
                if _is_number(hw_value) and _is_number(op_value) and op_value > hw_value:
                    errors.append(
                        f"{loc}: limits.operating.value ({op_value}) exceeds limits.hardware.value "
                        f"({hw_value}) - violates effective_limit = min(hardware, operating)"
                    )
                rule = eff.get("rule")
                if rule is not None and rule not in VALID_EFFECTIVE_RULES:
                    errors.append(f"{loc}: limits.effective.rule {rule!r} is not one of {sorted(VALID_EFFECTIVE_RULES)}")
                if rule == "min(hardware, operating)":
                    hw_known = _is_number(hw_value) or bool(hw.get("source"))
                    op_known = _is_number(op_value) or bool(op.get("source_entity"))
                    if not hw_known or not op_known:
                        errors.append(
                            f"{loc}: limits.effective.rule is 'min(hardware, operating)' but "
                            f"limits.hardware and limits.operating must each record at least a "
                            f"value or a source/source_entity - a rule cannot reference a missing tier"
                        )

        # --- enum mapping -----------------------------------------------
        enum_mapping = cap.get("enum_mapping")
        if enum_mapping is not None:
            if not isinstance(enum_mapping, dict) or not enum_mapping:
                errors.append(f"{loc}: enum_mapping must be a non-empty mapping")
            else:
                values = list(enum_mapping.values())
                if len(values) != len(set(values)) and not cap.get("_allow_duplicate_enum_values"):
                    errors.append(f"{loc}: enum_mapping has duplicate meanings for different raw values: {enum_mapping}")

        # --- register claims (deferred to a second pass for sharing checks) --
        for reg in registers:
            claim = _RegisterClaim(cap_id, _bits_to_set(reg["bits"]), reg["bits"], reg["shared_with"])
            claims_by_address.setdefault(reg["address"], []).append(claim)

        # --- dependencies (Task 005A section 5) ------------------------------
        deps = cap.get("dependencies")
        if deps is not None:
            if not isinstance(deps, dict):
                errors.append(
                    f"{loc}: 'dependencies' must be a mapping with 'capabilities'/'entities'/'flags' "
                    f"keys (schema v2) - free-text dependency lists are no longer valid"
                )
            else:
                dep_caps = deps.get("capabilities") or []
                if not isinstance(dep_caps, list) or not all(isinstance(d, str) for d in dep_caps):
                    errors.append(f"{loc}: dependencies.capabilities must be a list of capability id strings")
                else:
                    for dep_id in dep_caps:
                        if dep_id == cap_id and not cap.get("allow_self_dependency"):
                            errors.append(f"{loc}: dependencies.capabilities references itself ('{dep_id}') without allow_self_dependency: true")
                        # existence checked in the second pass once all ids are known

                dep_entities = deps.get("entities") or []
                if not isinstance(dep_entities, list) or not all(isinstance(d, str) for d in dep_entities):
                    errors.append(f"{loc}: dependencies.entities must be a list of entity id strings")
                else:
                    for entity_id in _entity_ids_from(dep_entities):
                        if not _ENTITY_ID_RE.match(entity_id):
                            errors.append(f"{loc}: malformed entity id in dependencies.entities: {entity_id!r}")

                dep_flags = deps.get("flags") or []
                if not isinstance(dep_flags, list) or not all(isinstance(d, str) for d in dep_flags):
                    errors.append(f"{loc}: dependencies.flags must be a list of strings")

        # --- missing evidence -------------------------------------------
        if not cap.get("firmware_evidence") and not cap.get("ha_evidence"):
            errors.append(f"{loc}: no firmware_evidence or ha_evidence recorded")

        # --- malformed entity IDs -----------------------------------------
        for field_name in ("entity_ha_raw", "entity_ha_canonical"):
            for entity_id in _entity_ids_from(cap.get(field_name)):
                if not _ENTITY_ID_RE.match(entity_id):
                    errors.append(f"{loc}: malformed entity id in {field_name}: {entity_id!r}")

    # --- second pass: register sharing + dependency existence -------------
    _validate_shared_with_references(claims_by_address, seen_ids, errors)
    _validate_register_sharing(claims_by_address, errors)

    for idx, cap in enumerate(caps):
        if not isinstance(cap, dict):
            continue
        cap_id = cap.get("id")
        loc = f"capability '{cap_id}'" if cap_id else f"capabilities[{idx}]"
        deps = cap.get("dependencies")
        if isinstance(deps, dict):
            for dep_id in deps.get("capabilities") or []:
                if isinstance(dep_id, str) and dep_id not in seen_ids and dep_id != cap_id:
                    errors.append(f"{loc}: dependencies.capabilities references unknown capability id '{dep_id}'")

    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REGISTRY_PATH
    errors = validate(path)
    if errors:
        print("Capability registry validation FAILED")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Capability registry validation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
