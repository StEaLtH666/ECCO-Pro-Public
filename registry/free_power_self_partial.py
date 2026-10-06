#!/usr/bin/env python3
"""SG-01 Phase 3 - pure Python model of the Free Power restore classifier,
including the v1-narrow SELF_PARTIAL rule.

The firmware implementation lives in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml
(restore_free_power_snapshot_dispatch: the 256x24 fresh-read handler computes
the per-block legs, the "SG-01 Phase 3 - SELF_PARTIAL classifier" lambda
applies the rules below). registry/tests/test_sg01_self_partial_phase3_4.py
runs the REAL firmware code over an exhaustive enumeration and requires it to
agree with this model exactly. Nothing here performs Modbus I/O or touches a
durable record.

Block model - the four logical Free Power START write stages, each compared
as a WHOLE vector:

    B1 = [232]            B2 = [230]
    B3 = [268..279] (12)  B4 = [256..261] (6)

    O = every register of the block equals ORIGINAL (the durable snapshot)
    I = every register of the block equals INTENDED (derive_intended())

    BOTH = O and I   O_ONLY = O and not I   I_ONLY = I and not O   X = neither

An internal mixture inside B3 or B4 (some registers ORIGINAL, others
INTENDED or anything else) is X.

Classification - the first matching rule wins:

     0. a fresh read failed / timed out           -> COMMS
     1. every block O_ONLY or BOTH                -> ORIGINAL
     2. every block I_ONLY or BOTH                -> INTENDED (no journal
                                                     needed: pre-SG-01
                                                     obligations are unchanged)
     3. any block X                               -> NEITHER
     4. recovery marker is not RESTORE_REQUIRED   -> NEITHER
     5. snapshot not trusted / metadata corrupt   -> NEITHER
     6. journal missing / invalid / unbound       -> NEITHER
     7. START_VERIFIED set (v1-narrow)            -> NEITHER
     8. an I_ONLY block whose attempt bit is clear -> NEITHER
     9. B4 I_ONLY while B3 O_ONLY                 -> NEITHER
    10. otherwise                                 -> SELF_PARTIAL

ORIGINAL wins the all-BOTH tie (the restore classifier's existing
"already restored, skip the write" leg is evaluated first). Matching INTENDED
values never prove ownership on their own: an I_ONLY block is legal only with
its own journal attempt bit. Rules 4-6 exist because the firmware's journal
RAM mirror is NOT cleared when a restore clears the recovery marker - journal
validity alone never grants SELF_PARTIAL.

Journal attempt bits (a PREFIX mask - valid values 0, 1, 3, 7, 15):
bit0 B1 (232), bit1 B2 (230), bit2 B3 (268-279), bit3 B4 (256-261).
"""

from __future__ import annotations

from dataclasses import dataclass

from free_power_recovery_evidence import OWNED_REGISTER_ORDER, derive_intended

# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------
B1, B2, B3, B4 = "B1", "B2", "B3", "B4"
BLOCKS: tuple[str, ...] = (B1, B2, B3, B4)  # START write order
BLOCK_REGISTERS: dict[str, tuple[int, ...]] = {
    B1: (232,),
    B2: (230,),
    B3: tuple(range(268, 280)),
    B4: tuple(range(256, 262)),
}
BLOCK_ATTEMPT_BIT: dict[str, int] = {B1: 0x01, B2: 0x02, B3: 0x04, B4: 0x08}

assert sorted(r for regs in BLOCK_REGISTERS.values() for r in regs) == sorted(OWNED_REGISTER_ORDER)

O_ONLY, I_ONLY, BOTH, X = "O_ONLY", "I_ONLY", "BOTH", "X"
BLOCK_STATES: tuple[str, ...] = (O_ONLY, I_ONLY, BOTH, X)

# ---------------------------------------------------------------------------
# Journal constants (mirror firmware/include/ecco_durable_snapshot.h)
# ---------------------------------------------------------------------------
VALID_START_ATTEMPTED_MASKS: tuple[int, ...] = (0, 1, 3, 7, 15)
MASK_ALL_BLOCKS = 0x0F
FLAG_START_VERIFIED = 0x01
KNOWN_FLAGS = FLAG_START_VERIFIED

# ---------------------------------------------------------------------------
# Classifications, rules and restore routes
# ---------------------------------------------------------------------------
COMMS, ORIGINAL, INTENDED, SELF_PARTIAL, NEITHER = "COMMS", "ORIGINAL", "INTENDED", "SELF_PARTIAL", "NEITHER"
CLASSIFICATIONS: tuple[str, ...] = (COMMS, ORIGINAL, INTENDED, SELF_PARTIAL, NEITHER)

RULE_READ_FAILED = "0:read_failed"
RULE_ALL_ORIGINAL = "1:all_original"
RULE_ALL_INTENDED = "2:all_intended"
RULE_X_BLOCK = "3:x_block"
RULE_MARKER_NOT_RESTORE_REQUIRED = "4:marker_not_restore_required"
RULE_SNAPSHOT_UNTRUSTED = "5:snapshot_untrusted"
RULE_JOURNAL_INVALID = "6:journal_invalid"
RULE_START_VERIFIED = "7:start_verified"
RULE_ATTEMPT_BIT_MISSING = "8:attempt_bit_missing"
RULE_CEILING_OVER_ORIGINAL_FLOORS = "9:b4_intended_over_b3_original"
RULE_SELF_PARTIAL = "10:self_partial"

RULE_CLASSIFICATION: dict[str, str] = {
    RULE_READ_FAILED: COMMS,
    RULE_ALL_ORIGINAL: ORIGINAL,
    RULE_ALL_INTENDED: INTENDED,
    RULE_X_BLOCK: NEITHER,
    RULE_MARKER_NOT_RESTORE_REQUIRED: NEITHER,
    RULE_SNAPSHOT_UNTRUSTED: NEITHER,
    RULE_JOURNAL_INVALID: NEITHER,
    RULE_START_VERIFIED: NEITHER,
    RULE_ATTEMPT_BIT_MISSING: NEITHER,
    RULE_CEILING_OVER_ORIGINAL_FLOORS: NEITHER,
    RULE_SELF_PARTIAL: SELF_PARTIAL,
}

# What restore_free_power_snapshot_dispatch does with each classification.
ROUTE_COMMS_BACKOFF = "comms_backoff"        # retain obligation, COMMS pacing
ROUTE_SKIP_WRITE = "skip_write_verify"       # no restore write; final verify/clear
ROUTE_RESTORE = "restore_write"              # the ONE existing restore write branch
ROUTE_OPERATOR_LOCKOUT = "operator_lockout"  # NEITHER: durable operator_needed
RESTORE_ROUTE: dict[str, str] = {
    COMMS: ROUTE_COMMS_BACKOFF,
    ORIGINAL: ROUTE_SKIP_WRITE,
    INTENDED: ROUTE_RESTORE,
    SELF_PARTIAL: ROUTE_RESTORE,
    NEITHER: ROUTE_OPERATOR_LOCKOUT,
}


@dataclass(frozen=True)
class RecoveryEvidence:
    """Everything outside the live read that SELF_PARTIAL permission
    depends on, in the firmware's own RAM terms.

    `journal_valid`/`journal_mask`/`journal_flags` are the START journal RAM
    mirror (free_power_start_journal_valid/_mask/_flags). `journal_bound` is
    whether the mirror's binding equals the binding recomputed from the
    CURRENT RAM snapshot. The mask/flags are re-validated here (rule 6) even
    when `journal_valid` is true - exactly like the firmware, which re-runs
    the Phase 1 schema validator over its RAM mirror.
    """

    marker_restore_required: bool = True
    snapshot_valid: bool = True
    metadata_corrupt: bool = False
    journal_valid: bool = False
    journal_mask: int = 0
    journal_flags: int = 0
    journal_bound: bool = False


def journal_schema_ok(mask: int, flags: int) -> bool:
    """The Phase 1 schema rules on (start_attempted, flags): a prefix mask,
    no unknown flag bits, START_VERIFIED only with the full mask."""
    if mask not in VALID_START_ATTEMPTED_MASKS:
        return False
    if flags & ~KNOWN_FLAGS & 0xFF:
        return False
    if flags & FLAG_START_VERIFIED and mask != MASK_ALL_BLOCKS:
        return False
    return True


# ---------------------------------------------------------------------------
# Block classification
# ---------------------------------------------------------------------------
def block_state(matches_original: bool, matches_intended: bool) -> str:
    if matches_original and matches_intended:
        return BOTH
    if matches_original:
        return O_ONLY
    if matches_intended:
        return I_ONLY
    return X


def classify_blocks(*, originals: dict[int, int], intended: dict[int, int], live: dict[int, int]) -> dict[str, str]:
    """{block: state} over the 20 owned registers (whole-vector comparison)."""
    for name, d in (("originals", originals), ("intended", intended), ("live", live)):
        missing = set(OWNED_REGISTER_ORDER) - set(d)
        if missing:
            raise ValueError(f"{name} is missing owned registers {sorted(missing)}")
    return {
        b: block_state(all(live[r] == originals[r] for r in regs), all(live[r] == intended[r] for r in regs))
        for b, regs in BLOCK_REGISTERS.items()
    }


# ---------------------------------------------------------------------------
# Recovery classification
# ---------------------------------------------------------------------------
def classification_rule(blocks: dict[str, str], evidence: RecoveryEvidence, *, read_ok: bool = True) -> str:
    """The FIRST rule (RULE_*) that matches - see the module docstring."""
    if set(blocks) != set(BLOCKS) or any(s not in BLOCK_STATES for s in blocks.values()):
        raise ValueError(f"blocks must map exactly {BLOCKS} to one of {BLOCK_STATES}, got {blocks!r}")
    if not read_ok:
        return RULE_READ_FAILED
    states = [blocks[b] for b in BLOCKS]
    if all(s in (O_ONLY, BOTH) for s in states):
        return RULE_ALL_ORIGINAL
    if all(s in (I_ONLY, BOTH) for s in states):
        return RULE_ALL_INTENDED
    if X in states:
        return RULE_X_BLOCK
    if not evidence.marker_restore_required:
        return RULE_MARKER_NOT_RESTORE_REQUIRED
    if not evidence.snapshot_valid or evidence.metadata_corrupt:
        return RULE_SNAPSHOT_UNTRUSTED
    if not (evidence.journal_valid and evidence.journal_bound
            and journal_schema_ok(evidence.journal_mask, evidence.journal_flags)):
        return RULE_JOURNAL_INVALID
    if evidence.journal_flags & FLAG_START_VERIFIED:
        return RULE_START_VERIFIED
    for b in BLOCKS:
        if blocks[b] == I_ONLY and not evidence.journal_mask & BLOCK_ATTEMPT_BIT[b]:
            return RULE_ATTEMPT_BIT_MISSING
    if blocks[B4] == I_ONLY and blocks[B3] == O_ONLY:
        return RULE_CEILING_OVER_ORIGINAL_FLOORS
    return RULE_SELF_PARTIAL


def classify_recovery(blocks: dict[str, str], evidence: RecoveryEvidence, *, read_ok: bool = True) -> str:
    """COMMS / ORIGINAL / INTENDED / SELF_PARTIAL / NEITHER."""
    return RULE_CLASSIFICATION[classification_rule(blocks, evidence, read_ok=read_ok)]


def restore_route(classification: str) -> str:
    return RESTORE_ROUTE[classification]


def classify_live(
    *,
    originals: dict[int, int],
    reg230_intended: int,
    reg_tou_power_intended: int,
    live: dict[int, int],
    evidence: RecoveryEvidence,
    read_ok: bool = True,
) -> str:
    """End-to-end: derive INTENDED exactly like the firmware (shared
    derive_intended()), classify the blocks, then the recovery state."""
    intended = derive_intended(
        originals={r: originals[r] for r in OWNED_REGISTER_ORDER},
        reg230_intended=reg230_intended,
        reg_tou_power_intended=reg_tou_power_intended,
    )
    blocks = classify_blocks(originals=originals, intended=intended, live=live)
    return classify_recovery(blocks, evidence, read_ok=read_ok)


def self_partial_legal_blocks(blocks: dict[str, str], journal_mask: int) -> bool:
    """Block-level legality alone (rules 3, 8, 9): O_ONLY and BOTH always
    legal, I_ONLY only with its attempt bit, X never; plus the B4/B3
    coupling rule. Says nothing about the marker/trust/journal rules."""
    for b in BLOCKS:
        if blocks[b] == X:
            return False
        if blocks[b] == I_ONLY and not journal_mask & BLOCK_ATTEMPT_BIT[b]:
            return False
    return not (blocks[B4] == I_ONLY and blocks[B3] == O_ONLY)
