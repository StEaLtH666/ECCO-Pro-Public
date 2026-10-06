#!/usr/bin/env python3
"""Offline tests for the repo-only recovery-classifier v2 design/test
artifact added to registry/transaction_state_machine.py.

This is the first Phase 1 recovery-model specification recommended by the
Fable adversarial review, implemented ONLY as an executable design/test
artifact: no Modbus, no network, no Home Assistant, no ESPHome, no
firmware, no inverter writes, no deployment. It exists so a FUTURE
executor's reasoning after a reboot or an uncertain write can be pinned
down and exhaustively tested BEFORE any live firmware is touched.

Separate from, and does not replace, registry/tests/test_transaction_
engine_semantics.py, which continues to pin `classify_recovery()` (v1)
exactly as the 2026-09-21 audit left it.

No pytest dependency. No network. No hardware. Same standalone
check()/expect_raises() style as every other offline test in this
directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transaction_state_machine import (  # noqa: E402
    CURRENT_OWNER_RECORD_SCHEMA_VERSION,
    DEFAULT_INVALID_CLOCK_GRACE_S,
    DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES,
    ClockContext,
    MarkerState,
    OperatorAction,
    OperatorResolutionRequest,
    OwnerRecord,
    RecordLoadFailure,
    RecoveryActionV2,
    RetryCause,
    RetryDecision,
    SafeDirection,
    TransactionKind,
    WriteOutcome,
    authorizes_unattended_restore,
    capability_safe_direction,
    classify_recovery_v2,
    comms_backoff_seconds,
    lease_should_end,
    resolve_operator_action,
    retry_policy,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def expect_raises(exc_type, fn, name: str) -> None:
    try:
        fn()
    except exc_type:
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, f"raised {type(e).__name__} instead of {exc_type.__name__}: {e}")
    else:
        check(name, False, "did not raise")


NEVER_WRITES = {
    RecoveryActionV2.CLEAR,
    RecoveryActionV2.CLEAR_ONLY,
    RecoveryActionV2.VERIFY_AND_CLEAR,
    RecoveryActionV2.LEASE_ACTIVE,
    RecoveryActionV2.DRIFT,
    RecoveryActionV2.MIXED_OR_DRIFT,
    RecoveryActionV2.HARDWARE_UNREADABLE,
    RecoveryActionV2.LOCKOUT_METADATA,
    RecoveryActionV2.OPERATOR_DECISION,
    # RESTORE_DUE is deliberately excluded: whether it alone authorises an
    # unattended write depends on safe_direction - see
    # authorizes_unattended_restore(), tested explicitly in [7] below.
}


def base_clock(**kw) -> ClockContext:
    defaults = dict(wall_time_valid=True, wall_time_epoch=1000.0, uptime_s=60.0)
    return ClockContext(**{**defaults, **kw})


def owner(**kw) -> OwnerRecord:
    defaults = dict(
        capability_id="free_power_transaction",
        kind=TransactionKind.TEMPORARY_OVERRIDE,
        snapshot={230: 185, 232: 0},
        intended={230: 40, 232: 1},
        outcome=WriteOutcome.UNATTEMPTED,
    )
    return OwnerRecord(**{**defaults, **kw})


# ===========================================================================
print("[1] Persistence tear points: Phase A / Phase B / boot with a stray record")
# ===========================================================================
# Tear before ANY durable commit: marker reads CLEAR (the only route to
# CLEAR per the firmware precedent), regardless of anything in memory.
a1 = classify_recovery_v2(MarkerState.CLEAR, None, {230: 185, 232: 0}, base_clock())
check("tear before durable snapshot: marker CLEAR -> CLEAR, no record consulted", a1.action is RecoveryActionV2.CLEAR)

# Tear after Phase A (data record committed) but before Phase B (marker
# flipped to RESTORE_REQUIRED): the durable MARKER still reads CLEAR, so
# the stray data record is orphaned but harmless.
a2 = classify_recovery_v2(MarkerState.CLEAR, RecordLoadFailure.MISSING, {230: 185, 232: 0}, base_clock())
check("tear after Phase A only: marker still CLEAR -> CLEAR (stray record ignored)", a2.action is RecoveryActionV2.CLEAR)

# Tear after Phase B (marker durably RESTORE_REQUIRED) but before any
# write was issued.
a3 = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, owner(outcome=WriteOutcome.UNATTEMPTED), {230: 185, 232: 0}, base_clock()
)
check("tear after Phase B, no write issued, live == snapshot -> VERIFY_AND_CLEAR", a3.action is RecoveryActionV2.VERIFY_AND_CLEAR)

# Reboot after a write MAY have landed (outcome flipped to UNCERTAIN before
# the write was sent - mirrors reg244_last_applied_valid=false-before-write).
a4 = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED,
    owner(outcome=WriteOutcome.UNCERTAIN, last_verified={}),
    {230: 40, 232: 1},  # live already matches intended - the write landed
    base_clock(),
)
check(
    "reboot after write may have landed, live == intended -> LEASE_ACTIVE or RESTORE_DUE, never CLEAR",
    a4.action in (RecoveryActionV2.LEASE_ACTIVE, RecoveryActionV2.RESTORE_DUE),
)

print("")
print("[2] PENDING_CLEAR never authorises a write, regardless of the record")
for bad_record in (None, RecordLoadFailure.MISSING, RecordLoadFailure.CORRUPT, owner()):
    a = classify_recovery_v2(MarkerState.PENDING_CLEAR, bad_record, {230: 999}, base_clock())
    check(
        f"PENDING_CLEAR with record={bad_record!r} -> CLEAR_ONLY (never a hardware write)",
        a.action is RecoveryActionV2.CLEAR_ONLY,
    )

print("")
print("[3] Malformed marker / corrupt or unsupported record -> LOCKOUT_METADATA, never a write")
check(
    "malformed marker -> LOCKOUT_METADATA",
    classify_recovery_v2(MarkerState.MALFORMED, owner(), {230: 40}, base_clock()).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "malformed marker even with NO record at all -> LOCKOUT_METADATA",
    classify_recovery_v2(MarkerState.MALFORMED, None, None, base_clock()).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "RESTORE_REQUIRED + missing companion record -> LOCKOUT_METADATA",
    classify_recovery_v2(MarkerState.RESTORE_REQUIRED, RecordLoadFailure.MISSING, {230: 40}, base_clock()).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "RESTORE_REQUIRED + no record object at all -> LOCKOUT_METADATA",
    classify_recovery_v2(MarkerState.RESTORE_REQUIRED, None, {230: 40}, base_clock()).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "RESTORE_REQUIRED + short/corrupt record -> LOCKOUT_METADATA",
    classify_recovery_v2(MarkerState.RESTORE_REQUIRED, RecordLoadFailure.CORRUPT, {230: 40}, base_clock()).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "unsupported schema_version -> LOCKOUT_METADATA",
    classify_recovery_v2(
        MarkerState.RESTORE_REQUIRED,
        owner(schema_version=CURRENT_OWNER_RECORD_SCHEMA_VERSION + 1),
        {230: 40},
        base_clock(),
    ).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "unknown capability_id -> LOCKOUT_METADATA (fails closed)",
    classify_recovery_v2(
        MarkerState.RESTORE_REQUIRED,
        owner(capability_id="totally_unrecognised_capability"),
        {230: 40},
        base_clock(),
    ).action
    is RecoveryActionV2.LOCKOUT_METADATA,
)
check(
    "capability_safe_direction() itself fails closed (None, not a guessed default) for an unknown id",
    capability_safe_direction("totally_unrecognised_capability") is None,
)

print("")
print("[4] UNCERTAIN outcome: live == snapshot / == intended / == neither, all mechanically distinct")
rec_uncertain = owner(outcome=WriteOutcome.UNCERTAIN, last_verified={})
r_snapshot = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_uncertain, {230: 185, 232: 0}, base_clock())
r_intended = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_uncertain, {230: 40, 232: 1}, base_clock())
r_neither = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_uncertain, {230: 999, 232: 999}, base_clock())
r_mixed = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_uncertain, {230: 185, 232: 1}, base_clock())
check("UNCERTAIN, live == snapshot -> VERIFY_AND_CLEAR", r_snapshot.action is RecoveryActionV2.VERIFY_AND_CLEAR)
check(
    "UNCERTAIN, live == intended -> LEASE_ACTIVE or RESTORE_DUE",
    r_intended.action in (RecoveryActionV2.LEASE_ACTIVE, RecoveryActionV2.RESTORE_DUE),
)
check("UNCERTAIN, live == neither -> MIXED_OR_DRIFT (never invented certainty)", r_neither.action is RecoveryActionV2.MIXED_OR_DRIFT)
check(
    "UNCERTAIN, live is a MIX of one register from snapshot and one from intended -> MIXED_OR_DRIFT too",
    r_mixed.action is RecoveryActionV2.MIXED_OR_DRIFT,
)
check(
    "the three non-mixed live pictures produced three DIFFERENT concrete dicts (precondition sanity)",
    len({tuple(sorted(d.items())) for d in ({230: 185, 232: 0}, {230: 40, 232: 1}, {230: 999, 232: 999})}) == 3,
)
r_live_unreadable = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_uncertain, None, base_clock())
check("UNCERTAIN, live unreadable -> HARDWARE_UNREADABLE", r_live_unreadable.action is RecoveryActionV2.HARDWARE_UNREADABLE)

print("")
print("[5] UNCERTAIN + safe_direction NONE -> HARDWARE_UNREADABLE (unreadable) or OPERATOR_DECISION (readable), never an unattended restore")
# Hardware-read failure is diagnostically distinct from "no unattended
# restore direction" and must stay visible: HARDWARE_UNREADABLE when live
# cannot be read, OPERATOR_DECISION once it CAN be read (regardless of
# what it shows, since safe_direction is NONE) - both forbid every
# unattended write identically, so this widens no authority.
rec_none_direction = owner(capability_id="grid_export_policy", outcome=WriteOutcome.UNCERTAIN, snapshot={244: 2}, intended={244: 0}, last_verified={})
for live in ({244: 2}, {244: 0}, {244: 99}):
    a = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_none_direction, live, base_clock())
    check(
        f"grid_export_policy (safe_direction NONE), UNCERTAIN, readable live={live!r} -> OPERATOR_DECISION",
        a.action is RecoveryActionV2.OPERATOR_DECISION,
    )
    check(f"  ...and never authorises an unattended restore", not authorizes_unattended_restore(a))
a_none_unreadable = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_none_direction, None, base_clock())
check(
    "grid_export_policy (safe_direction NONE), UNCERTAIN, live=None -> HARDWARE_UNREADABLE (not silently OPERATOR_DECISION)",
    a_none_unreadable.action is RecoveryActionV2.HARDWARE_UNREADABLE,
)
check("  ...and it never authorises an unattended restore either", not authorizes_unattended_restore(a_none_unreadable))

print("")
print("[6] CONFIRMED outcome: live == last_verified (lease-dependent) vs drift")
rec_confirmed_active = owner(
    outcome=WriteOutcome.CONFIRMED, last_verified={230: 40, 232: 1}, lease_end_epoch=5000.0, lease_start_epoch=100.0
)
a_active = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, rec_confirmed_active, {230: 40, 232: 1}, base_clock(wall_time_epoch=1000.0)
)
check("CONFIRMED, live == last_verified, well before lease_end -> LEASE_ACTIVE", a_active.action is RecoveryActionV2.LEASE_ACTIVE)
a_due = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, rec_confirmed_active, {230: 40, 232: 1}, base_clock(wall_time_epoch=5000.0)
)
check("CONFIRMED, live == last_verified, at lease_end exactly -> RESTORE_DUE", a_due.action is RecoveryActionV2.RESTORE_DUE)
a_drift = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, rec_confirmed_active, {230: 999, 232: 1}, base_clock(wall_time_epoch=1000.0)
)
check("CONFIRMED, live != last_verified -> DRIFT", a_drift.action is RecoveryActionV2.DRIFT)
a_confirmed_unreadable = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_confirmed_active, None, base_clock())
check("CONFIRMED, live unreadable -> HARDWARE_UNREADABLE", a_confirmed_unreadable.action is RecoveryActionV2.HARDWARE_UNREADABLE)

print("")
print("[7] authorizes_unattended_restore(): the single point deciding unattended action")
rd_restore = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, rec_confirmed_active, {230: 40, 232: 1}, base_clock(wall_time_epoch=5000.0)
)
check("free_power_transaction (RESTORE direction) RESTORE_DUE -> authorises unattended restore", authorizes_unattended_restore(rd_restore))
rec_none_confirmed = owner(
    capability_id="grid_export_policy",
    outcome=WriteOutcome.CONFIRMED,
    last_verified={244: 0},
    lease_end_epoch=5000.0,
    lease_start_epoch=100.0,
)
rd_none = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, rec_none_confirmed, {244: 0}, base_clock(wall_time_epoch=5000.0)
)
check("grid_export_policy (NONE direction) RESTORE_DUE -> does NOT authorise unattended restore", not authorizes_unattended_restore(rd_none))
check(
    "no non-RESTORE_DUE action ever authorises an unattended restore",
    all(
        not authorizes_unattended_restore(
            type(rd_restore)(action=act, reason="synthetic", safe_direction=SafeDirection.RESTORE)
        )
        for act in NEVER_WRITES
    ),
)

print("")
print("[8] TransactionKind matters: PERMANENT never enters lease semantics")
# A PERMANENT change (a Manual TOU slot, the RTC) is intended to STAY
# changed once verified - it is not a lease and must never be classified
# LEASE_ACTIVE/RESTORE_DUE, which are TEMPORARY_OVERRIDE-only concepts.
tou_snapshot_8 = {232: 0, 250: 800, 251: 1700, 256: 8000, 268: 80, 274: 0}
tou_intended_8 = {232: 1, 250: 600, 251: 1800, 256: 4000, 268: 100, 274: 1}
tou_mixed_8 = {232: 1, 250: 800, 251: 1800, 256: 8000, 268: 100, 274: 0}  # half old, half new


def permanent_tou(**kw) -> OwnerRecord:
    defaults = dict(
        capability_id="tou_slot_1",
        kind=TransactionKind.PERMANENT,
        snapshot=tou_snapshot_8,
        intended=tou_intended_8,
    )
    return owner(**{**defaults, **kw})


# 1. PERMANENT + CONFIRMED + live == last_verified -> VERIFY_AND_CLEAR
a1_confirmed_match = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED,
    permanent_tou(outcome=WriteOutcome.CONFIRMED, last_verified=tou_intended_8),
    tou_intended_8,
    base_clock(),
)
check(
    "1. PERMANENT + CONFIRMED + live == last_verified -> VERIFY_AND_CLEAR, "
    "NEVER a lease (the write succeeded and remains in effect)",
    a1_confirmed_match.action is RecoveryActionV2.VERIFY_AND_CLEAR,
)

# 2. PERMANENT + CONFIRMED + live != last_verified -> DRIFT
a2_confirmed_drift = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED,
    permanent_tou(outcome=WriteOutcome.CONFIRMED, last_verified=tou_intended_8),
    tou_mixed_8,
    base_clock(),
)
check("2. PERMANENT + CONFIRMED + live != last_verified -> DRIFT", a2_confirmed_drift.action is RecoveryActionV2.DRIFT)

# 3-5. PERMANENT + UNCERTAIN is ALWAYS OPERATOR_DECISION once live is
# readable, regardless of which value (if any) live happens to match -
# matching `intended` is NOT proof a permanent write landed.
a3_uncertain_snapshot = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, permanent_tou(outcome=WriteOutcome.UNCERTAIN), tou_snapshot_8, base_clock()
)
check("3. PERMANENT + UNCERTAIN + live == snapshot -> OPERATOR_DECISION", a3_uncertain_snapshot.action is RecoveryActionV2.OPERATOR_DECISION)
a4_uncertain_intended = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, permanent_tou(outcome=WriteOutcome.UNCERTAIN), tou_intended_8, base_clock()
)
check(
    "4. PERMANENT + UNCERTAIN + live == intended -> OPERATOR_DECISION "
    "(matching intended is not proof it landed - never a fake lease)",
    a4_uncertain_intended.action is RecoveryActionV2.OPERATOR_DECISION,
)
a5_uncertain_mixed = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, permanent_tou(outcome=WriteOutcome.UNCERTAIN), tou_mixed_8, base_clock()
)
check("5. PERMANENT + UNCERTAIN + mixed state -> OPERATOR_DECISION", a5_uncertain_mixed.action is RecoveryActionV2.OPERATOR_DECISION)

# 6. PERMANENT + unreadable live -> HARDWARE_UNREADABLE (both UNCERTAIN and CONFIRMED)
a6_uncertain_unreadable = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED, permanent_tou(outcome=WriteOutcome.UNCERTAIN), None, base_clock()
)
check("6a. PERMANENT + UNCERTAIN + unreadable live -> HARDWARE_UNREADABLE", a6_uncertain_unreadable.action is RecoveryActionV2.HARDWARE_UNREADABLE)
a6_confirmed_unreadable = classify_recovery_v2(
    MarkerState.RESTORE_REQUIRED,
    permanent_tou(outcome=WriteOutcome.CONFIRMED, last_verified=tou_intended_8),
    None,
    base_clock(),
)
check("6b. PERMANENT + CONFIRMED + unreadable live -> HARDWARE_UNREADABLE", a6_confirmed_unreadable.action is RecoveryActionV2.HARDWARE_UNREADABLE)

# 7 & 8. Exhaustive: no PERMANENT combination ever yields LEASE_ACTIVE/
# RESTORE_DUE, and none ever satisfies authorizes_unattended_restore().
permanent_violations: list[str] = []
for outcome_p in WriteOutcome:
    for live_p in (None, tou_snapshot_8, tou_intended_8, tou_mixed_8, {}):
        rec_p = permanent_tou(
            outcome=outcome_p,
            last_verified=tou_intended_8 if outcome_p is WriteOutcome.CONFIRMED else {},
        )
        a_p = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_p, live_p, base_clock())
        if a_p.action in (RecoveryActionV2.LEASE_ACTIVE, RecoveryActionV2.RESTORE_DUE):
            permanent_violations.append(f"outcome={outcome_p} live={live_p} -> {a_p.action}")
        if authorizes_unattended_restore(a_p):
            permanent_violations.append(f"authorizes_unattended_restore True for outcome={outcome_p} live={live_p}")
check(
    "7&8. NO PERMANENT combination ever produces LEASE_ACTIVE/RESTORE_DUE or authorises an unattended restore",
    not permanent_violations,
    f"{permanent_violations}",
)

print("")
print("[9] Deterministic partial-landing matrix, multi-register PERMANENT transaction (tou_slot_1)")
# tou_slot_1 owns registers {232, 250, 251, 256, 268, 274} per
# ECCO_CONFLICT_DECLARATIONS. A partially landed PERMANENT transaction
# discovered after reboot must resolve to a human decision (UNCERTAIN) or
# an explicit DRIFT (CONFIRMED) - never an automatic rollback and never a
# fake lease, per [8] above.
tou_snapshot = tou_snapshot_8
tou_last_verified = tou_intended_8
tou_mixed = tou_mixed_8
rec_tou = permanent_tou(outcome=WriteOutcome.CONFIRMED, last_verified=tou_last_verified)
check(
    "precondition: snapshot, last_verified and the mixed picture are three distinct dicts",
    len({tuple(sorted(d.items())) for d in (tou_snapshot, tou_last_verified, tou_mixed)}) == 3,
)
a_tou_matches = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_tou, tou_last_verified, base_clock())
a_tou_stale = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_tou, tou_snapshot, base_clock())
a_tou_mixed = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_tou, tou_mixed, base_clock())
check(
    "CONFIRMED, live == last_verified exactly -> VERIFY_AND_CLEAR (verified success, stays changed, no lease)",
    a_tou_matches.action is RecoveryActionV2.VERIFY_AND_CLEAR,
)
check("CONFIRMED, live == stale ORIGINAL snapshot (nothing landed) -> DRIFT (mismatches last_verified)", a_tou_stale.action is RecoveryActionV2.DRIFT)
check("CONFIRMED, live == a genuine MIX of snapshot/last_verified registers (PARTIAL LANDING) -> DRIFT, an operator must look", a_tou_mixed.action is RecoveryActionV2.DRIFT)
check(
    "the stale-snapshot and mixed pictures are genuinely different inputs that both land on DRIFT "
    "(not one case silently aliasing the other)",
    tou_snapshot != tou_mixed and a_tou_stale.action is a_tou_mixed.action is RecoveryActionV2.DRIFT,
)
# The same partial-landing picture, but caught while still UNCERTAIN
# (write outcome not yet confirmed) rather than CONFIRMED - this is the
# "reboot mid-write, did the partial landing actually happen" case, and
# it must resolve to a human decision, not an inferred rollback.
rec_tou_uncertain = permanent_tou(outcome=WriteOutcome.UNCERTAIN)
a_tou_uncertain_mixed = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec_tou_uncertain, tou_mixed, base_clock())
check(
    "UNCERTAIN, live shows a PARTIAL LANDING (mix of snapshot/intended registers) -> OPERATOR_DECISION, "
    "never an automatic rollback and never a fake lease",
    a_tou_uncertain_mixed.action is RecoveryActionV2.OPERATOR_DECISION,
)

print("")
print("[10] Full generated sweep: RESTORE_REQUIRED never silently downgrades to CLEAR/CLEAR_ONLY, and PERMANENT never leases")
swept = 0
for kind in TransactionKind:
    for outcome in WriteOutcome:
        for cap, direction in (("free_power_transaction", SafeDirection.RESTORE), ("grid_export_policy", SafeDirection.NONE)):
            for live in (None, {230: 1}, {230: 2}, {230: 3}):
                rec = owner(
                    capability_id=cap,
                    kind=kind,
                    snapshot={230: 1},
                    intended={230: 2},
                    outcome=outcome,
                    last_verified={230: 2} if outcome is WriteOutcome.CONFIRMED else {},
                )
                a = classify_recovery_v2(MarkerState.RESTORE_REQUIRED, rec, live, base_clock())
                swept += 1
                if a.action in (RecoveryActionV2.CLEAR, RecoveryActionV2.CLEAR_ONLY):
                    check("RESTORE_REQUIRED never yields CLEAR/CLEAR_ONLY", False, f"{rec} live={live} -> {a.action}")
                if kind is TransactionKind.PERMANENT and a.action in (RecoveryActionV2.LEASE_ACTIVE, RecoveryActionV2.RESTORE_DUE):
                    check("PERMANENT never yields LEASE_ACTIVE/RESTORE_DUE", False, f"{cap} outcome={outcome} live={live} -> {a.action}")
                if kind is TransactionKind.PERMANENT and authorizes_unattended_restore(a):
                    check("PERMANENT never authorises an unattended restore", False, f"{cap} outcome={outcome} live={live} -> {a.action}")
                if kind is TransactionKind.TEMPORARY_OVERRIDE and direction is SafeDirection.NONE and outcome is WriteOutcome.UNCERTAIN:
                    # Hardware-read failure stays visible even for a
                    # NONE-direction override: HARDWARE_UNREADABLE when
                    # live cannot be read, OPERATOR_DECISION once it can.
                    expected_none = RecoveryActionV2.HARDWARE_UNREADABLE if live is None else RecoveryActionV2.OPERATOR_DECISION
                    if a.action is not expected_none:
                        check(
                            "TEMPORARY_OVERRIDE + NONE direction + UNCERTAIN is HARDWARE_UNREADABLE "
                            "when unreadable, else OPERATOR_DECISION",
                            False,
                            f"live={live} -> {a.action}",
                        )
                if kind is TransactionKind.PERMANENT and outcome is WriteOutcome.UNCERTAIN:
                    expected = RecoveryActionV2.HARDWARE_UNREADABLE if live is None else RecoveryActionV2.OPERATOR_DECISION
                    if a.action is not expected:
                        check("PERMANENT + UNCERTAIN is OPERATOR_DECISION when readable, HARDWARE_UNREADABLE otherwise", False, f"{cap} live={live} -> {a.action}")
                if authorizes_unattended_restore(a) and direction is not SafeDirection.RESTORE:
                    check("no unattended restore ever authorised for a non-RESTORE direction", False, f"{cap} {a.action}")
check(f"swept {swept} RESTORE_REQUIRED combinations with no safety violation", True)

print("")
print("[11] Lease-expiry decision rules")
rec_lease = owner(lease_start_epoch=1000.0, lease_end_epoch=2000.0, max_duration_s=None, restore_requested=False)
check(
    "well before lease_end, valid clock -> lease active",
    not lease_should_end(rec_lease, base_clock(wall_time_valid=True, wall_time_epoch=1500.0, uptime_s=10.0)),
)
check(
    "exactly at lease_end -> ends (lease expiry exactly once, not one tick early/late)",
    lease_should_end(rec_lease, base_clock(wall_time_valid=True, wall_time_epoch=2000.0, uptime_s=10.0)),
)
check(
    "one second before lease_end -> still active",
    not lease_should_end(rec_lease, base_clock(wall_time_valid=True, wall_time_epoch=1999.0, uptime_s=10.0)),
)
check(
    "durable restore_requested ends the lease immediately, even mid-lease with a valid clock",
    lease_should_end(
        owner(lease_start_epoch=1000.0, lease_end_epoch=999999.0, restore_requested=True),
        base_clock(wall_time_valid=True, wall_time_epoch=1500.0, uptime_s=10.0),
    ),
)
check(
    "wall clock BACKWARDS relative to lease_start is treated as invalid, not trusted",
    lease_should_end(
        owner(lease_start_epoch=5000.0, lease_end_epoch=6000.0, max_duration_s=None),
        base_clock(wall_time_valid=True, wall_time_epoch=100.0, uptime_s=DEFAULT_INVALID_CLOCK_GRACE_S + 1),
    ),
)
check(
    "invalid wall clock just after reboot (within grace) -> lease stays active",
    not lease_should_end(
        owner(lease_start_epoch=1000.0, lease_end_epoch=2000.0),
        base_clock(wall_time_valid=False, wall_time_epoch=None, uptime_s=DEFAULT_INVALID_CLOCK_GRACE_S - 1),
    ),
)
check(
    "invalid wall clock past the bounded grace period -> lease ends (NTP never locking cannot run forever)",
    lease_should_end(
        owner(lease_start_epoch=1000.0, lease_end_epoch=2000.0),
        base_clock(wall_time_valid=False, wall_time_epoch=None, uptime_s=DEFAULT_INVALID_CLOCK_GRACE_S + 1),
    ),
)
check(
    "max_duration_s ceiling ends the lease via uptime even though the wall clock is invalid and well within grace",
    lease_should_end(
        owner(lease_start_epoch=1000.0, lease_end_epoch=None, max_duration_s=30.0),
        base_clock(wall_time_valid=False, wall_time_epoch=None, uptime_s=31.0),
    ),
)
check(
    "below max_duration_s ceiling and within grace -> lease stays active",
    not lease_should_end(
        owner(lease_start_epoch=1000.0, lease_end_epoch=None, max_duration_s=30.0),
        base_clock(wall_time_valid=False, wall_time_epoch=None, uptime_s=5.0),
    ),
)

print("")
print("[12] Retry policy: cause-aware, and COMMS attempts survive a modelled reboot")
check("COMMS backoff sequence is 15/30/60/120/300, holding at 300", [comms_backoff_seconds(n) for n in range(1, 8)] == [15, 30, 60, 120, 300, 300, 300])
r_comms_first = retry_policy(RetryCause.COMMS, attempts_so_far=0)
check("first COMMS failure permits retry at 15s", r_comms_first.decision is RetryDecision.RETRY_PERMITTED and r_comms_first.next_backoff_s == 15.0)
r_comms_after_reboot = retry_policy(RetryCause.COMMS, attempts_so_far=2)
check(
    "recomputing from a PERSISTED attempt count (as if reconstructed after a reboot) reproduces the exact same backoff",
    retry_policy(RetryCause.COMMS, attempts_so_far=2).next_backoff_s == r_comms_after_reboot.next_backoff_s == 60.0,
)

r_verify_first = retry_policy(RetryCause.VERIFY_MISMATCH, attempts_so_far=0)
check("first verify mismatch permits exactly one automatic retry", r_verify_first.decision is RetryDecision.RETRY_PERMITTED)
r_verify_second = retry_policy(RetryCause.VERIFY_MISMATCH, attempts_so_far=1)
check("a second verify mismatch is exhausted, not retried again", r_verify_second.decision is RetryDecision.RETRY_EXHAUSTED)

r_metadata = retry_policy(RetryCause.METADATA, attempts_so_far=0)
check("METADATA cause authorises zero automatic hardware writes (NO_AUTOMATIC_RETRY)", r_metadata.decision is RetryDecision.NO_AUTOMATIC_RETRY)

r_durable = retry_policy(RetryCause.DURABLE_COMMIT, attempts_so_far=5)
check("DURABLE_COMMIT permits a clear-only retry regardless of prior attempt count", r_durable.decision is RetryDecision.RETRY_PERMITTED)

expect_raises(ValueError, lambda: comms_backoff_seconds(0), "comms_backoff_seconds(0) is rejected (1-based)")
expect_raises(ValueError, lambda: retry_policy(RetryCause.COMMS, attempts_so_far=-1), "retry_policy rejects a negative attempt count")

print("")
print("[13] Operator resolution: refusal without arm, generation mismatch, fresh-read requirements")
rec_op = owner(generation=7)

for action in OperatorAction:
    result = resolve_operator_action(
        OperatorResolutionRequest(action=action, armed=False, live={230: 1}, confirmed_generation=7, shown_evidence=True),
        rec_op,
    )
    check(f"{action.value} refused without an explicit arm", not result.permitted)

r_retry_unreadable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live=None), rec_op
)
check("RETRY_RESTORE refused when live is not freshly readable", not r_retry_unreadable.permitted)
r_retry_ok = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}), rec_op
)
check("RETRY_RESTORE permitted when armed with a fresh live read", r_retry_ok.permitted)
check("RETRY_RESTORE never writes - it returns a marker transition/audit intent only", r_retry_ok.marker_transition is MarkerState.RESTORE_REQUIRED and r_retry_ok.audit_intent is not None)

# Restore actions require a REAL restore target: a trustworthy OwnerRecord
# with a snapshot, for a recognised capability. Armed + a readable live
# read is not enough on its own.
r_retry_missing_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}), RecordLoadFailure.MISSING
)
check("RETRY_RESTORE refused against RecordLoadFailure.MISSING, even with a fresh live read", not r_retry_missing_record.permitted)
r_retry_corrupt_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}), RecordLoadFailure.CORRUPT
)
check("RETRY_RESTORE refused against RecordLoadFailure.CORRUPT, even with a fresh live read", not r_retry_corrupt_record.permitted)
r_retry_no_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}), None
)
check("RETRY_RESTORE refused against record=None, even with a fresh live read", not r_retry_no_record.permitted)
r_retry_no_snapshot = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}),
    owner(generation=7, snapshot=None),
)
check("RETRY_RESTORE refused against a valid OwnerRecord whose snapshot is None - nothing to restore to", not r_retry_no_snapshot.permitted)
r_retry_unknown_cap = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.RETRY_RESTORE, armed=True, live={230: 1}),
    owner(generation=7, capability_id="totally_unrecognised_capability"),
)
check("RETRY_RESTORE refused against an unrecognised capability_id", not r_retry_unknown_cap.permitted)

r_force_missing_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=7, shown_evidence=True),
    RecordLoadFailure.MISSING,
)
check("FORCE_RESTORE refused against RecordLoadFailure.MISSING", not r_force_missing_record.permitted)
r_force_no_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=7, shown_evidence=True),
    None,
)
check("FORCE_RESTORE refused against record=None", not r_force_no_record.permitted)
r_force_no_snapshot = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=7, shown_evidence=True),
    owner(generation=7, snapshot=None),
)
check("FORCE_RESTORE refused against a valid OwnerRecord whose snapshot is None", not r_force_no_snapshot.permitted)

r_force_no_gen = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=1, shown_evidence=True),
    rec_op,
)
check("FORCE_RESTORE refused on a generation mismatch (rec is generation 7, confirmed 1)", not r_force_no_gen.permitted)
r_force_no_evidence = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=7, shown_evidence=False),
    rec_op,
)
check("FORCE_RESTORE refused when the operator was not shown evidence", not r_force_no_evidence.permitted)
r_force_ok = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=7, shown_evidence=True),
    rec_op,
)
check("FORCE_RESTORE permitted once armed + generation confirmed + evidence shown", r_force_ok.permitted)
check("FORCE_RESTORE's audit intent records that this overrides uncertainty, not that it was normal", "FORCED" in (r_force_ok.audit_intent or "") and "uncertain" in r_force_ok.reason)

r_accept_unreadable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.ACCEPT_LIVE_STATE, armed=True, live=None, confirmed_generation=7), rec_op
)
check("ACCEPT_LIVE_STATE refused without a fresh live read", not r_accept_unreadable.permitted)
r_accept_gen_mismatch = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.ACCEPT_LIVE_STATE, armed=True, live={230: 1}, confirmed_generation=1), rec_op
)
check("ACCEPT_LIVE_STATE refused on generation mismatch", not r_accept_gen_mismatch.permitted)
r_accept_ok = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.ACCEPT_LIVE_STATE, armed=True, live={230: 1}, confirmed_generation=7), rec_op
)
check("ACCEPT_LIVE_STATE permitted with a fresh read and matching generation", r_accept_ok.permitted)
check("ACCEPT_LIVE_STATE clears only via PENDING_CLEAR (audit intent must land first)", r_accept_ok.marker_transition is MarkerState.PENDING_CLEAR)

check(
    "DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES is the documented model threshold of 3",
    DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES == 3,
)

r_discard_readable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.DISCARD_UNREADABLE, armed=True, live={230: 1}), rec_op
)
check("DISCARD_UNREADABLE refused when a fresh live read actually succeeds", not r_discard_readable.permitted)

# A bare `record=None` is NOT concrete metadata-failure evidence - it is
# an unresolved/unclassified state, distinct from an explicit
# RecordLoadFailure. It must be refused even when live is also None.
r_discard_none_record = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.DISCARD_UNREADABLE, armed=True, live=None), None
)
check(
    "DISCARD_UNREADABLE refused against record=None even with live=None - unresolved metadata is not evidence",
    not r_discard_none_record.permitted,
)
check(
    "...the refusal reason says the metadata state is unresolved, not that it was classified corrupt/missing",
    "unresolved" in r_discard_none_record.reason,
)

# Against a valid OwnerRecord (metadata is FINE - only hardware reads are
# failing): one or two transient failures must not be enough evidence.
for n in (0, 1, 2):
    r = resolve_operator_action(
        OperatorResolutionRequest(
            action=OperatorAction.DISCARD_UNREADABLE, armed=True, live=None, consecutive_live_read_failures=n
        ),
        rec_op,
    )
    check(f"DISCARD_UNREADABLE refused against a valid record with only {n} consecutive live-read failure(s)", not r.permitted)
r_discard_three = resolve_operator_action(
    OperatorResolutionRequest(
        action=OperatorAction.DISCARD_UNREADABLE, armed=True, live=None, consecutive_live_read_failures=3
    ),
    rec_op,
)
check(
    "DISCARD_UNREADABLE permitted against a valid record once 3 consecutive live-read failures are recorded",
    r_discard_three.permitted,
)
check(
    "...and it is still audited / PENDING_CLEAR-only, never a direct clear or a write",
    r_discard_three.marker_transition is MarkerState.PENDING_CLEAR and r_discard_three.audit_intent is not None,
)
r_discard_live_recovers = resolve_operator_action(
    OperatorResolutionRequest(
        action=OperatorAction.DISCARD_UNREADABLE, armed=True, live={230: 1}, consecutive_live_read_failures=5
    ),
    rec_op,
)
check(
    "DISCARD_UNREADABLE refused even after 5 prior failures if THIS read succeeded - hardware truth always wins",
    not r_discard_live_recovers.permitted,
)

# Against a corrupt/missing durable RECORD, the metadata failure is its
# own concrete evidence - no consecutive-failure count is required.
r_discard_corrupt_unreadable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.DISCARD_UNREADABLE, armed=True, live=None), RecordLoadFailure.CORRUPT
)
check(
    "DISCARD_UNREADABLE permitted against a corrupt record + unreadable live, with ZERO consecutive-failure count needed",
    r_discard_corrupt_unreadable.permitted,
)
r_discard_missing_unreadable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.DISCARD_UNREADABLE, armed=True, live=None), RecordLoadFailure.MISSING
)
check("DISCARD_UNREADABLE permitted against a missing record + unreadable live", r_discard_missing_unreadable.permitted)
r_discard_corrupt_but_readable = resolve_operator_action(
    OperatorResolutionRequest(action=OperatorAction.DISCARD_UNREADABLE, armed=True, live={230: 1}), RecordLoadFailure.CORRUPT
)
check(
    "DISCARD_UNREADABLE refused against a corrupt record if live IS readable - never claim hardware "
    "unreadable when only metadata is unreadable",
    not r_discard_corrupt_but_readable.permitted,
)

print("")
print("[14] No path in this model ever mutates a record or performs I/O (structural self-check)")
before = owner(generation=42)
_ = resolve_operator_action(OperatorResolutionRequest(action=OperatorAction.FORCE_RESTORE, armed=True, live={230: 1}, confirmed_generation=42, shown_evidence=True), before)
check("resolve_operator_action leaves the input OwnerRecord unchanged (frozen dataclass, pure function)", before == owner(generation=42))
check("OwnerRecord is a frozen dataclass (cannot be mutated in place)", OwnerRecord.__dataclass_params__.frozen)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All recovery-classifier v2 tests PASSED.")

print("")
print("This module and this test file are a DESIGN/TEST artifact only. No")
print("Modbus, network, Home Assistant, ESPHome, or firmware code is touched")
print("or imported. Nothing here has run against, or proves anything about,")
print("real hardware.")

if FAILURES:
    sys.exit(1)
