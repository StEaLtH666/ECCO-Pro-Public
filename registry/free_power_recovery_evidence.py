#!/usr/bin/env python3
"""Independent Python re-implementation of the Free Power recovery review's
64-bit FNV-1a evidence fingerprint (PR 1 of 3 - READ-ONLY recovery
infrastructure; see firmware/include/ecco_recovery_evidence.h and
firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
free_power_recovery_review script).

Why a second implementation exists
-----------------------------------
Nothing here executes against hardware, ESPHome, or Home Assistant. Its only
job is to let registry/tests/test_free_power_recovery_evidence.py pin
deterministic fingerprint test vectors and the canonical field order OFFLINE,
without an ESPHome/C++ toolchain. The canonical field order and byte
encoding below MUST stay byte-for-byte identical to
firmware/include/ecco_recovery_evidence.h and the fingerprint-building
lambda in free_power_recovery_review - see that script's own comments,
which point back here.

This module does not read or write any durable record, does not perform
Modbus I/O, and has no relationship to registry/transaction_state_machine.py
beyond documenting the same register addresses.
"""

from __future__ import annotations

# 64-bit FNV-1a constants (standard).
FNV64_OFFSET_BASIS = 0xCBF29CE484222325
FNV64_PRIME = 0x100000001B3
_MASK64 = (1 << 64) - 1

# The first thing hashed, always - see ecco_recovery_evidence.h.
FINGERPRINT_DOMAIN_TAG = "ECCO-FP-RECOVERY-EVIDENCE-v1"

# Canonical owned-register order - pinned. Mirrors
# firmware/include/ecco_durable_snapshot.h's FreePowerSnapshotData field
# order (end_epoch, then the 20 owned registers, then the two *_intended
# fields) and registry/transaction_state_machine.py's
# ECCO_CONFLICT_DECLARATIONS["free_power_transaction"] register set.
OWNED_REGISTER_ORDER: tuple[int, ...] = (
    230, 232,
    256, 257, 258, 259, 260, 261,
    268, 269, 270, 271, 272, 273,
    274, 275, 276, 277, 278, 279,
)

# Canonical context-register order - pinned. Registers 246, 247, 249 are
# deliberately excluded even though a single physical read of 244-255
# (count 12) returns them - see the firmware script's header comment.
CONTEXT_REGISTER_ORDER: tuple[int, ...] = (244, 245, 248, 250, 251, 252, 253, 254, 255)

assert len(OWNED_REGISTER_ORDER) == 20
assert len(CONTEXT_REGISTER_ORDER) == 9


def fnv1a64(data: bytes, hash_: int = FNV64_OFFSET_BASIS) -> int:
    """Update a running 64-bit FNV-1a hash with `data`. Pure function."""
    h = hash_
    for byte in data:
        h ^= byte
        h = (h * FNV64_PRIME) & _MASK64
    return h


def _u16le(v: int) -> bytes:
    if not (0 <= v <= 0xFFFF):
        raise ValueError(f"u16 value out of range: {v}")
    return v.to_bytes(2, "little")


def _u32le(v: int) -> bytes:
    if not (0 <= v <= 0xFFFFFFFF):
        raise ValueError(f"u32 value out of range: {v}")
    return v.to_bytes(4, "little")


def compute_fingerprint(
    *,
    end_epoch: int,
    originals: dict[int, int],
    reg230_intended: int,
    reg_tou_power_intended: int,
    live_owned: dict[int, int],
    live_context: dict[int, int],
) -> int:
    """Compute the 64-bit FNV-1a recovery evidence fingerprint.

    Canonical input order (must match ecco_recovery_evidence.h and the
    firmware lambda exactly):

      A. ASCII domain tag: "ECCO-FP-RECOVERY-EVIDENCE-v1"
      B. Durable obligation identity/targets loaded in RAM:
         end_epoch (u32 LE), then the 20 originals (u16 LE, OWNED_REGISTER_ORDER),
         then reg230_intended, reg_tou_power_intended (u16 LE each).
      C. Live owned values (u16 LE, OWNED_REGISTER_ORDER, same 20 addresses).
      D. Live context values (u16 LE, CONTEXT_REGISTER_ORDER, 9 addresses).

    Explicitly EXCLUDED (never hashed): register 231, 246, 247, 249,
    active_persisted, restore_requested, any classification result, and any
    timestamp/counter.

    `originals` and `live_owned` must each contain exactly the 20 keys in
    OWNED_REGISTER_ORDER; `live_context` must contain exactly the 9 keys in
    CONTEXT_REGISTER_ORDER. Missing/extra keys raise KeyError/ValueError
    rather than silently hashing a wrong or default value - a fingerprint
    computed over the wrong register set must never look "valid".
    """
    if set(originals) != set(OWNED_REGISTER_ORDER):
        raise ValueError(f"originals must contain exactly {OWNED_REGISTER_ORDER}, got {sorted(originals)}")
    if set(live_owned) != set(OWNED_REGISTER_ORDER):
        raise ValueError(f"live_owned must contain exactly {OWNED_REGISTER_ORDER}, got {sorted(live_owned)}")
    if set(live_context) != set(CONTEXT_REGISTER_ORDER):
        raise ValueError(f"live_context must contain exactly {CONTEXT_REGISTER_ORDER}, got {sorted(live_context)}")

    h = FNV64_OFFSET_BASIS
    h = fnv1a64(FINGERPRINT_DOMAIN_TAG.encode("ascii"), h)

    h = fnv1a64(_u32le(end_epoch), h)
    for addr in OWNED_REGISTER_ORDER:
        h = fnv1a64(_u16le(originals[addr]), h)
    h = fnv1a64(_u16le(reg230_intended), h)
    h = fnv1a64(_u16le(reg_tou_power_intended), h)

    for addr in OWNED_REGISTER_ORDER:
        h = fnv1a64(_u16le(live_owned[addr]), h)

    for addr in CONTEXT_REGISTER_ORDER:
        h = fnv1a64(_u16le(live_context[addr]), h)

    return h


def format_fingerprint_hex(fingerprint: int) -> str:
    """16 uppercase hex digits - matches the firmware's `%016llX` snprintf."""
    if not (0 <= fingerprint <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError(f"fingerprint out of 64-bit range: {fingerprint}")
    return f"{fingerprint:016X}"


# ---------------------------------------------------------------------------
# PR 3 of 3 - Accept Current State. The canonical INTENDED-value derivation,
# NEITHER classification, and Free Power residue formula, as an independent
# Python re-implementation of the SAME logic
# free_power_recovery_review_dispatch, free_power_recovery_force_restore_dispatch,
# and free_power_recovery_accept_current_state_dispatch all use identically
# in the firmware (see firmware/ecco_clock_dongle_stage3_4_free_power.yaml).
# Exists for the same reason compute_fingerprint() above does: it lets
# registry/tests/test_free_power_recovery_accept_current_state.py pin
# deterministic behavioural test vectors OFFLINE, without an ESPHome/C++
# toolchain. Nothing here performs Modbus I/O or touches any durable record.
# ---------------------------------------------------------------------------


def derive_intended(
    *,
    originals: dict[int, int],
    reg230_intended: int,
    reg_tou_power_intended: int,
) -> dict[int, int]:
    """The INTENDED (Free Power active-override) value for each of the 20
    owned registers, derived PURELY from `originals` plus the two persisted
    *_intended targets - identical derivation to the firmware's Review/
    Force/Accept classifiers:

      230        -> reg230_intended (not derivable from originals alone)
      232        -> originals[232] | 0x0001 (grid-charge bit forced on)
      256-261    -> reg_tou_power_intended (same wattage on all six slots)
      268-273    -> 100 (all six slots forced to 100% SOC)
      274-279    -> (originals[reg] & 0xFFFC) | 0x0001 (source bits forced to Grid)

    If `originals[232]` already has bit 0 set (grid charge already enabled),
    the derived intended value for 232 equals the original - this is
    correct and expected, not a bug: ORIGINAL == INTENDED is not residue
    (see free_power_residue_registers below).
    """
    if set(originals) != set(OWNED_REGISTER_ORDER):
        raise ValueError(f"originals must contain exactly {OWNED_REGISTER_ORDER}, got {sorted(originals)}")
    intended: dict[int, int] = {230: reg230_intended, 232: originals[232] | 0x0001}
    for addr in (256, 257, 258, 259, 260, 261):
        intended[addr] = reg_tou_power_intended
    for addr in (268, 269, 270, 271, 272, 273):
        intended[addr] = 100
    for addr in (274, 275, 276, 277, 278, 279):
        intended[addr] = (originals[addr] & 0xFFFC) | 0x0001
    return intended


def classify_live_state(
    *,
    originals: dict[int, int],
    intended: dict[int, int],
    live: dict[int, int],
) -> str:
    """Classify `live` against `originals`/`intended` over the 20 owned
    registers only (230, 232, 256-261, 268-279 - NEVER context registers).
    Returns one of "ORIGINAL", "INTENDED", "NEITHER".

    Tie-break (identical to the firmware): if `live` matches BOTH `originals`
    and `intended` register-for-register (only possible when originals and
    intended coincide), INTENDED wins.
    """
    for name, d in (("originals", originals), ("intended", intended), ("live", live)):
        if set(d) != set(OWNED_REGISTER_ORDER):
            raise ValueError(f"{name} must contain exactly {OWNED_REGISTER_ORDER}, got {sorted(d)}")
    matches_original = all(live[a] == originals[a] for a in OWNED_REGISTER_ORDER)
    matches_intended = all(live[a] == intended[a] for a in OWNED_REGISTER_ORDER)
    if matches_intended:
        return "INTENDED"
    if matches_original:
        return "ORIGINAL"
    return "NEITHER"


def free_power_residue_registers(
    *,
    originals: dict[int, int],
    intended: dict[int, int],
    live: dict[int, int],
) -> list[int]:
    """The list (ascending, OWNED_REGISTER_ORDER order) of owned registers
    where Free Power residue is present:

        RESIDUE(r) = live[r] == intended[r]  AND  live[r] != originals[r]

    A register whose original already equalled its intended value is NEVER
    residue, regardless of live - this is the deliberate "ORIGINAL ==
    INTENDED is not residue" exemption (e.g. grid charge already enabled
    before Free Power ever started).
    """
    for name, d in (("originals", originals), ("intended", intended), ("live", live)):
        if set(d) != set(OWNED_REGISTER_ORDER):
            raise ValueError(f"{name} must contain exactly {OWNED_REGISTER_ORDER}, got {sorted(d)}")
    return [a for a in OWNED_REGISTER_ORDER if live[a] == intended[a] and live[a] != originals[a]]


# Plausibility domains for Accept - existing established bounds only, no new
# policy invented here. Mirrors free_power_recovery_accept_current_state_dispatch's
# own plausibility scan exactly.
TOU_POWER_REGISTERS: tuple[int, ...] = (256, 257, 258, 259, 260, 261)
SOC_REGISTERS: tuple[int, ...] = (268, 269, 270, 271, 272, 273)
MODE_REGISTERS: tuple[int, ...] = (274, 275, 276, 277, 278, 279)
MODE_FIELD_MASK = 0x001C
KNOWN_MODE_FIELD_VALUES: frozenset[int] = frozenset({0x0000, 0x0004, 0x0008, 0x0010})


def implausible_registers(live: dict[int, int], *, tou_power_ceiling_w: int) -> list[int]:
    """The list (ascending) of owned registers whose live value falls
    outside Accept's established plausibility domain. Registers 230, 232,
    and every context register are deliberately NOT bounds-checked - no
    invented policy limit exists for them (see the firmware script's own
    header comment)."""
    offenders: list[int] = []
    for a in TOU_POWER_REGISTERS:
        if not (0 <= live[a] <= tou_power_ceiling_w):
            offenders.append(a)
    for a in SOC_REGISTERS:
        if not (0 <= live[a] <= 100):
            offenders.append(a)
    for a in MODE_REGISTERS:
        if (live[a] & MODE_FIELD_MASK) not in KNOWN_MODE_FIELD_VALUES:
            offenders.append(a)
    return offenders
