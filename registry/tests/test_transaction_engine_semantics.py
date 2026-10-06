#!/usr/bin/env python3
"""Offline tests for the 2026-09-21 audit extensions to
registry/transaction_state_machine.py.

No I/O, no hardware, no network. These cover the six things the audit
(docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md) found the original
model could not express, each traced to the live implementation that
motivated it:

  * transaction kind (permanent change vs temporary override lease)
  * write-outcome uncertainty, and what a drift guard may claim
  * snapshot durability, and the write that must not precede it
  * ownership over register SETS rather than capability names
  * SEMANTIC conflict domains - conflicts that register sets cannot see,
    which is the case a register-only model gets dangerously wrong
  * bounded restore retries, and restart recovery as a total function

The last section is a GENERATED sweep rather than hand-written cases: it
cuts power at every step of a modelled transaction and asserts a safety
predicate at each cut, so adding a step to the model automatically adds
coverage instead of silently leaving a gap.

As with every offline test here: this proves the MODEL's rules are
consistent and enforced. It does not prove the ESPHome firmware behaves
this way - the firmware does not use this module. See the audit document
for the per-path comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transaction_state_machine import (  # noqa: E402
    ECCO_CONFLICT_DECLARATIONS,
    ConflictDomain,
    OwnershipConflict,
    PersistedTransactionState,
    RecoveryAction,
    Transaction,
    TransactionError,
    TransactionKind,
    TransactionPolicy,
    TransactionRegistry,
    TransactionState,
    WriteOutcome,
    classify_recovery,
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


def _strict(
    reg: TransactionRegistry,
    cap: str,
    kind: TransactionKind,
    regs: set[int],
    domains: set[ConflictDomain] | None = None,
):
    """Start a strict transaction. Domains must be explicit - passing an
    empty set is a declaration of 'no semantic domain', which is different
    from omitting it (an undeclared claim, which fails closed)."""
    return reg.start_transaction(
        cap,
        kind=kind,
        registers=regs,
        domains=frozenset(domains or ()),
        policy=TransactionPolicy.strict(),
    )


def _declared(reg: TransactionRegistry, cap: str, kind: TransactionKind, key: str):
    """Start a strict transaction using ECCO's own recorded declaration."""
    regs, domains = ECCO_CONFLICT_DECLARATIONS[key]
    return reg.start_transaction(
        cap, kind=kind, registers=regs, domains=domains, policy=TransactionPolicy.strict()
    )


def _drive_to_lease(txn, snapshot: dict[int, int], applied: dict[int, int]):
    """Take a transaction all the way to a verified, outstanding lease."""
    _durable_snapshot(txn, snapshot)
    txn.stage("x")
    txn.arm()
    txn.begin_write()
    txn.writes_accepted()
    txn.verified(applied)
    return txn


def _durable_snapshot(txn, registers: dict[int, int], now: float | None = None):
    txn.snapshot_ok(registers, now=now)
    txn.snapshot.mark_durable()
    return txn


# ===========================================================================
print("[1] Snapshot durability: a write may not precede the snapshot reaching flash")
# ===========================================================================
reg = TransactionRegistry()
txn = _strict(reg, "grid_export_policy", TransactionKind.TEMPORARY_OVERRIDE, {244})
txn.snapshot_ok({244: 2})
txn.stage(0)
txn.arm()
check("snapshot is not durable immediately after a successful read", txn.snapshot.durable is False)
expect_raises(
    TransactionError,
    lambda: txn.begin_write(),
    "begin_write() against a non-durable snapshot is rejected",
)
check("the rejected write left the transaction armed, not writing", txn.state is TransactionState.ARMED)
txn.snapshot.mark_durable()
txn.begin_write()
check("begin_write() succeeds once the snapshot is durable", txn.state is TransactionState.WRITING)

print("")
print("[2] Write-outcome uncertainty is recorded BEFORE the write, not after a failure")
check(
    "entering 'writing' immediately marks the outcome UNCERTAIN",
    txn.outcome is WriteOutcome.UNCERTAIN,
)
check("and clears any previous last-applied record", txn.last_applied == {})
check(
    "so no drift guard is available while the outcome is unknown",
    txn.drift_guard_available() is False,
)
check(
    "detect_drift() returns empty when no guard is available, rather than a false 'no drift'",
    txn.detect_drift({244: 99}) == {},
)

txn.writes_accepted()
txn.verified({244: 0})
check("a verified write marks the outcome CONFIRMED", txn.outcome is WriteOutcome.CONFIRMED)
check("and records exactly what was applied", txn.last_applied == {244: 0})
check("a drift guard is available only now", txn.drift_guard_available() is True)
check("no drift when the live value matches", txn.detect_drift({244: 0}) == {})
check(
    "drift detected when a third party changed the register",
    txn.detect_drift({244: 2}) == {244: (0, 2)},
)

print("")
print("[3] A Modbus timeout is UNCERTAIN, not 'the write failed'")
reg3 = TransactionRegistry()
t3 = _strict(reg3, "grid_export_policy", TransactionKind.TEMPORARY_OVERRIDE, {244})
_durable_snapshot(t3, {244: 2})
t3.stage(0)
t3.arm()
t3.begin_write()
t3.write_failed("no response")
check("write_failed() reaches 'failed'", t3.state is TransactionState.FAILED)
check(
    "but the outcome stays UNCERTAIN - the inverter may still have accepted it",
    t3.outcome is WriteOutcome.UNCERTAIN,
)
check("and no drift guard is invented from it", t3.drift_guard_available() is False)

print("")
print("[4] A verification mismatch does not license a drift comparison either")
reg4 = TransactionRegistry()
t4 = _strict(reg4, "tou_slot_1_power", TransactionKind.PERMANENT, {256})
_durable_snapshot(t4, {256: 8000})
t4.stage(4000)
t4.arm()
t4.begin_write()
t4.writes_accepted()
t4.verify_mismatch("read 8000, expected 4000")
check("verify_mismatch() reaches 'failed'", t4.state is TransactionState.FAILED)
check("outcome is UNCERTAIN, not CONFIRMED", t4.outcome is WriteOutcome.UNCERTAIN)
check("last_applied is cleared", t4.last_applied == {})

print("")
print("[5] A temporary override cannot exit by declaring no restore is needed")
reg5 = TransactionRegistry()
t5 = _strict(reg5, "free_power_transaction", TransactionKind.TEMPORARY_OVERRIDE, {230, 232, 268})
_durable_snapshot(t5, {230: 185, 232: 0, 268: 80})
t5.stage({"reg230": 40})
t5.arm()
t5.begin_write()
t5.writes_accepted()
t5.verified({230: 40, 232: 1, 268: 100})
check("a verified temporary override is 'completed'", t5.state is TransactionState.COMPLETED)
check("and owes a restore", t5.owes_restore() is True)
expect_raises(
    TransactionError,
    lambda: t5.no_restore_needed(),
    "no_restore_needed() on a temporary override is rejected",
)
check("it is still completed, still owing a restore", t5.state is TransactionState.COMPLETED)

print("")
print("[6] A permanent change owes nothing and may exit cleanly")
reg6 = TransactionRegistry()
t6 = _strict(reg6, "tou_slot_1_power", TransactionKind.PERMANENT, {256})
_durable_snapshot(t6, {256: 8000})
t6.stage(4000)
t6.arm()
t6.begin_write()
t6.writes_accepted()
t6.verified({256: 4000})
check("a permanent change never owes a restore", t6.owes_restore() is False)
t6.no_restore_needed()
check("and may return to idle", t6.state is TransactionState.IDLE)

print("")
print("[7] Ownership is over REGISTERS, not capability names")
reg7 = TransactionRegistry()
fp = _drive_to_lease(
    _strict(
        reg7,
        "free_power_transaction",
        TransactionKind.TEMPORARY_OVERRIDE,
        {230, 232, 268, 274},
        {ConflictDomain.TOU_SCHEDULE, ConflictDomain.GRID_CHARGE},
    ),
    {230: 185, 232: 0, 268: 80, 274: 1},
    {230: 40, 232: 1, 268: 100, 274: 1},
)
check("Free Power now holds an outstanding obligation", len(reg7.outstanding_obligations()) == 1)
# A differently-NAMED capability that shares register 268 must still be
# blocked, on register overlap alone.
expect_raises(
    OwnershipConflict,
    lambda: _strict(
        reg7, "tou_slot_1_target_soc", TransactionKind.PERMANENT, {268}, {ConflictDomain.TOU_SCHEDULE}
    ),
    "a different capability sharing register 268 is blocked by the outstanding lease",
)
check(
    "blocking_obligation() names the actual blocker for an overlapping register set",
    reg7.blocking_obligation({274}, frozenset()) is fp,
)
check(
    "and reports no blocker for a claim disjoint on BOTH dimensions",
    reg7.blocking_obligation({22, 23, 24}, {ConflictDomain.INVERTER_CLOCK}) is None,
)
# Register overlap must block even when the semantic domains are disjoint -
# proving the two dimensions are genuinely independent, not one dressed up
# as two.
check(
    "register overlap blocks even with an explicitly empty domain declaration",
    reg7.blocking_obligation({232}, frozenset()) is fp,
)

print("")
print("[7a] SEMANTIC conflict blocks even when the register sets are disjoint")
# THE case register-set ownership alone gets wrong, and which the live
# firmware already enforces by hand. A register 244 lease writes only
# register 244. Manual TOU writes 232/250-261/268-279. Free Power writes
# 230/232/268-279. Neither intersects {244} - yet the production firmware
# deliberately refuses both while a 244 snapshot is pending, because
# register 244 decides whether TOU Power means an export cap or a battery
# discharge cap.
reg7a = TransactionRegistry()
r244 = _drive_to_lease(
    _declared(reg7a, "grid_export_policy", TransactionKind.TEMPORARY_OVERRIDE, "grid_export_policy"),
    {244: 2},
    {244: 0},
)
tou_regs, tou_domains = ECCO_CONFLICT_DECLARATIONS["tou_slot_1"]
fp_regs, fp_domains = ECCO_CONFLICT_DECLARATIONS["free_power_transaction"]
check(
    "precondition: the register 244 lease does NOT overlap the TOU slot register set",
    not (r244.owned_registers & tou_regs),
    f"244 owns {sorted(r244.owned_registers)}, TOU owns {sorted(tou_regs)}",
)
check(
    "precondition: the register 244 lease does NOT overlap Free Power's register set",
    not (r244.owned_registers & fp_regs),
)
expect_raises(
    OwnershipConflict,
    lambda: _declared(reg7a, "tou_slot_1", TransactionKind.PERMANENT, "tou_slot_1"),
    "an outstanding register 244 lease BLOCKS a manual TOU write despite disjoint registers",
)
expect_raises(
    OwnershipConflict,
    lambda: _declared(
        reg7a, "free_power_transaction", TransactionKind.TEMPORARY_OVERRIDE, "free_power_transaction"
    ),
    "an outstanding register 244 lease BLOCKS Free Power despite disjoint registers",
)
blocker, reason = reg7a.blocking_obligation(tou_regs, tou_domains, explain=True)
check("the blocker is named", blocker is r244)
check(
    "and the reason cites the semantic domain, not a register",
    "semantic conflict" in reason and "tou_schedule" in reason,
    reason,
)

print("")
print("[7b] A disjoint domain is still allowed while a long-lived lease merely exists")
# RTC shares neither registers nor semantics with the power path. With
# nothing mid-flight on the bus, it must remain permitted - otherwise a
# lease would become a system-wide freeze.
rtc = _declared(reg7a, "rtc_clock", TransactionKind.PERMANENT, "rtc_clock")
check(
    "RTC (22-24 / inverter_clock) proceeds while a register 244 lease is outstanding",
    rtc.state is TransactionState.SNAPSHOTTING,
)
check("the register 244 lease is still outstanding afterwards", r244.owes_restore() is True)
check(
    "RTC is not blocked by a Free Power lease either",
    reg7.blocking_obligation(*ECCO_CONFLICT_DECLARATIONS["rtc_clock"]) is None,
)

print("")
print("[7c] Undeclared claims fail closed; explicitly-empty declarations do not")
check(
    "an UNDECLARED register set conflicts with every outstanding lease",
    reg7.blocking_obligation(None, frozenset()) is fp,
)
check(
    "an UNDECLARED domain set conflicts with every outstanding lease",
    reg7.blocking_obligation({22, 23, 24}, None) is fp,
)
check(
    "an EXPLICITLY EMPTY domain set is a declaration, not silence - no semantic conflict",
    reg7.blocking_obligation({22, 23, 24}, frozenset()) is None,
)
check(
    "with no outstanding lease, even an undeclared claim is unblocked (the legacy path)",
    TransactionRegistry().blocking_obligation(None, None) is None,
)
expect_raises(
    TransactionError,
    lambda: TransactionRegistry().start_transaction(
        "unsafe", registers={244}, policy=TransactionPolicy.strict()
    ),
    "a strict transaction that omits its conflict domains is refused outright",
)
expect_raises(
    TransactionError,
    lambda: TransactionRegistry().start_transaction(
        "typo",
        registers={244},
        domains={"inverter_power_policy"},
        policy=TransactionPolicy.strict(),
    ),
    "an unrecognised conflict-domain name is refused rather than silently ignored",
)

print("")
print("[7d] Dump-to-Grid's declaration matches its actual implemented write surface")
# Manual Dump-to-Grid V1 (2026-09-26) superseded the old
# "battery_export_NOT_IMPLEMENTED" shape-only placeholder that declared
# {244, 245} - register 245 turned out not to be needed. See
# docs/DUMP_TO_GRID_V1.md and registry/tests/test_write_surface_invariants.py,
# which pins this same {244, 256-261} set against the real firmware.
be_regs, be_domains = ECCO_CONFLICT_DECLARATIONS["dump_to_grid_transaction"]
check(
    "Dump-to-Grid's declaration names register 244 and 256-261, and NOT 245",
    be_regs == (frozenset({244}) | frozenset(range(256, 262))),
)
check(
    "and the power-policy plus TOU semantic domains",
    be_domains == frozenset({ConflictDomain.INVERTER_POWER_POLICY, ConflictDomain.TOU_SCHEDULE}),
)
check(
    "so it would be blocked by an outstanding register 244 lease, as it must be",
    reg7a.blocking_obligation(be_regs, be_domains) is r244,
)
check(
    "and it would block a manual TOU write, on BOTH registers (256-261) AND semantics",
    bool(be_regs & tou_regs) and bool(be_domains & tou_domains),
)

print("")
print("[8] The restore path stays reachable when normal writes are blocked")
check(
    "restore_path_for() finds the outstanding obligation even while it blocks new writes",
    reg7.restore_path_for("free_power_transaction") is fp,
)
check(
    "restore_path_for() returns None for a capability that owes nothing",
    reg7.restore_path_for("tou_slot_1_power") is None,
)
check(
    "a register 244 lease's own restore stays reachable despite its broad semantic claim",
    reg7a.restore_path_for("grid_export_policy") is r244,
)

print("")
print("[8a] Two incompatible obligations cannot be acquired; if corrupted persisted")
print("     state ever presents them anyway, restore selection fails closed")
reg8 = TransactionRegistry()
lease_a = _drive_to_lease(
    _declared(reg8, "grid_export_policy", TransactionKind.TEMPORARY_OVERRIDE, "grid_export_policy"),
    {244: 2},
    {244: 0},
)
check("no obligation conflicts in normal operation", reg8.obligation_conflicts() == [])
expect_raises(
    OwnershipConflict,
    lambda: _declared(
        reg8, "free_power_transaction", TransactionKind.TEMPORARY_OVERRIDE, "free_power_transaction"
    ),
    "a second, incompatible lease cannot be acquired through the normal path",
)
# Simulate corrupted / externally reconstructed persisted state by injecting
# an incompatible obligation directly, bypassing admission control.
rogue = Transaction(
    capability_id="free_power_transaction",
    kind=TransactionKind.TEMPORARY_OVERRIDE,
    owned_registers=ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][0],
    conflict_domains=ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][1],
    policy=TransactionPolicy.strict(),
)
rogue.begin()
_drive_to_lease(rogue, {230: 185}, {230: 40})
reg8._obligations.append(rogue)  # noqa: SLF001 - deliberately simulating corrupt state
conflicts = reg8.obligation_conflicts()
check("the incompatible pair is detected", len(conflicts) == 1, f"{conflicts}")
check(
    "and it is detected on SEMANTICS, since their register sets are disjoint",
    bool(conflicts) and "semantic conflict" in conflicts[0][2],
    f"{conflicts[0][2] if conflicts else ''}",
)
expect_raises(
    OwnershipConflict,
    lambda: reg8.restore_path_for("grid_export_policy"),
    "restore selection fails closed rather than guessing which obligation to honour",
)

print("")
print("[9] Restore retries are bounded - an unbounded automatic retry is itself a hazard")
reg9 = TransactionRegistry()
t9 = reg9.start_transaction(
    "free_power_transaction",
    kind=TransactionKind.TEMPORARY_OVERRIDE,
    registers={230},
    domains=frozenset({ConflictDomain.GRID_CHARGE}),
    policy=TransactionPolicy(max_restore_attempts=2),
)
_durable_snapshot(t9, {230: 185})
t9.stage("x")
t9.arm()
t9.begin_write()
t9.write_failed("timeout")
t9.restore_attempt()
t9.restore_failed("restore write timed out")
check("attempt 1 recorded", t9.restore_attempts == 1)
t9.restore_attempt()
t9.restore_failed("restore write timed out again")
check("attempt 2 recorded", t9.restore_attempts == 2)
expect_raises(
    TransactionError,
    lambda: t9.restore_attempt(),
    "a third restore attempt past the cap is refused rather than retried forever",
)
check(
    "the transaction stays visibly in restore_failed, not silently idle",
    t9.state is TransactionState.RESTORE_FAILED,
)

print("")
print("[10] A verified restore records what it put back, and releases the lease")
reg10 = TransactionRegistry()
t10 = _strict(reg10, "grid_export_policy", TransactionKind.TEMPORARY_OVERRIDE, {244})
_durable_snapshot(t10, {244: 2})
t10.stage(0)
t10.arm()
t10.begin_write()
t10.writes_accepted()
t10.verified({244: 0})
check("lease held while the override is active", t10.owes_restore() is True)
t10.restore_requested()
t10.restore_verified()
check("a verified restore returns to idle", t10.state is TransactionState.IDLE)
check("outcome is CONFIRMED again", t10.outcome is WriteOutcome.CONFIRMED)
check("last_applied is the snapshot that was put back", t10.last_applied == {244: 2})
check("the lease is released", t10.owes_restore() is False)
check("and the registry no longer reports an obligation", reg10.outstanding_obligations() == [])

print("")
print("[11] Restart recovery is a TOTAL function of persisted state")

BASE = dict(capability_id="grid_export_policy", owned_registers=frozenset({244}))


def assess(**kw):
    return classify_recovery(PersistedTransactionState(**{**BASE, **kw}))


cases = [
    # (description, persisted kwargs, expected action)
    (
        "no snapshot, nothing attempted",
        dict(kind=TransactionKind.PERMANENT, snapshot=None, outcome=WriteOutcome.UNATTEMPTED),
        RecoveryAction.NONE,
    ),
    (
        "write may have been issued but the snapshot never reached flash",
        dict(kind=TransactionKind.PERMANENT, snapshot=None, outcome=WriteOutcome.UNCERTAIN),
        RecoveryAction.OPERATOR_DECISION_REQUIRED,
    ),
    (
        "snapshot in RAM only when power was cut",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=False,
            outcome=WriteOutcome.UNCERTAIN,
        ),
        RecoveryAction.OPERATOR_DECISION_REQUIRED,
    ),
    (
        "durable snapshot, no write issued",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.UNATTEMPTED,
        ),
        RecoveryAction.VERIFY_AND_CLEAR,
    ),
    (
        "durable snapshot, write outcome unknown",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.UNCERTAIN,
        ),
        RecoveryAction.OPERATOR_DECISION_REQUIRED,
    ),
    (
        "verified permanent change",
        dict(
            kind=TransactionKind.PERMANENT,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.CONFIRMED,
            last_applied={244: 0},
        ),
        RecoveryAction.RESTORE_AVAILABLE,
    ),
    (
        "verified temporary override still within its lease",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.CONFIRMED,
            last_applied={244: 0},
            restore_deadline=None,
        ),
        RecoveryAction.RESTORE_AVAILABLE,
    ),
    (
        "verified temporary override past its deadline",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.CONFIRMED,
            last_applied={244: 0},
            restore_deadline=0.0,
        ),
        RecoveryAction.AUTO_RESTORE_PERMITTED,
    ),
    (
        "restore retries already exhausted",
        dict(
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.CONFIRMED,
            last_applied={244: 0},
            restore_deadline=0.0,
            restore_attempts=3,
            max_restore_attempts=3,
        ),
        RecoveryAction.OPERATOR_DECISION_REQUIRED,
    ),
]
for desc, kw, expected in cases:
    got = assess(**kw)
    check(f"{desc} -> {expected.value}", got.action is expected, f"got {got.action.value}: {got.reason}")

print("")
print("[12] Recovery never offers an unattended write on uncertain or undurable state")
# Exhaustive sweep of every reachable persisted combination.
swept = 0
for kind in TransactionKind:
    for durable in (False, True):
        for outcome in WriteOutcome:
            for deadline in (None, 0.0):
                for attempts in (0, 3):
                    for snap in (None, {244: 2}):
                        p = PersistedTransactionState(
                            capability_id="c",
                            kind=kind,
                            owned_registers=frozenset({244}),
                            snapshot=snap,
                            snapshot_durable=durable,
                            outcome=outcome,
                            last_applied={244: 0} if outcome is WriteOutcome.CONFIRMED else {},
                            restore_deadline=deadline,
                            restore_attempts=attempts,
                        )
                        a = classify_recovery(p)
                        swept += 1
                        if a.action is RecoveryAction.AUTO_RESTORE_PERMITTED:
                            ok = (
                                snap is not None
                                and durable
                                and outcome is WriteOutcome.CONFIRMED
                                and kind is TransactionKind.TEMPORARY_OVERRIDE
                                and deadline is not None
                                and attempts < 3
                            )
                            if not ok:
                                check(
                                    "AUTO_RESTORE_PERMITTED offered on unsafe state",
                                    False,
                                    f"{p}",
                                )
                        if a.drift_guard_available and outcome is not WriteOutcome.CONFIRMED:
                            check("drift guard claimed without a confirmed write", False, f"{p}")
                        if a.action is RecoveryAction.NONE and outcome is not WriteOutcome.UNATTEMPTED:
                            check("recovery offered NONE after a write may have landed", False, f"{p}")
check(f"swept {swept} persisted combinations with no safety violation", True)

print("")
print("[13] Generated power-cut sweep over a full temporary-override transaction")
# Each step is (label, mutation of the persisted record). The sweep cuts
# power immediately AFTER each step and classifies what a restart would
# see. Adding a step here automatically extends coverage.
steps: list[tuple[str, dict]] = [
    ("transaction begun, nothing read yet", dict()),
    ("snapshot read, still in RAM", dict(snapshot={244: 2}, snapshot_durable=False)),
    ("snapshot flushed to flash", dict(snapshot={244: 2}, snapshot_durable=True)),
    (
        "last-applied invalidated, write about to be issued",
        dict(snapshot={244: 2}, snapshot_durable=True, outcome=WriteOutcome.UNCERTAIN),
    ),
    (
        "write issued, no response yet",
        dict(snapshot={244: 2}, snapshot_durable=True, outcome=WriteOutcome.UNCERTAIN),
    ),
    (
        "write acknowledged, reread not yet done",
        dict(snapshot={244: 2}, snapshot_durable=True, outcome=WriteOutcome.UNCERTAIN),
    ),
    (
        "reread verified and persisted",
        dict(
            snapshot={244: 2},
            snapshot_durable=True,
            outcome=WriteOutcome.CONFIRMED,
            last_applied={244: 0},
            restore_deadline=0.0,
        ),
    ),
]
# Every cut point must produce an action, and must never claim NONE once
# a write could have reached the inverter.
unsafe = []
for i, (label, mutation) in enumerate(steps):
    p = PersistedTransactionState(
        capability_id="grid_export_policy",
        kind=TransactionKind.TEMPORARY_OVERRIDE,
        owned_registers=frozenset({244}),
        **mutation,
    )
    a = classify_recovery(p)
    write_possible = p.outcome is not WriteOutcome.UNATTEMPTED
    if write_possible and a.action in (RecoveryAction.NONE, RecoveryAction.VERIFY_AND_CLEAR):
        unsafe.append((i, label, a.action.value))
    print(f"      cut after step {i} ({label}) -> {a.action.value}")
check("no cut point downgrades a possible write to 'nothing happened'", not unsafe, f"{unsafe}")
check(
    "the cut before the snapshot is durable is the only one that loses the original value",
    classify_recovery(
        PersistedTransactionState(
            capability_id="c",
            kind=TransactionKind.TEMPORARY_OVERRIDE,
            snapshot={244: 2},
            snapshot_durable=False,
            outcome=WriteOutcome.UNCERTAIN,
        )
    ).action
    is RecoveryAction.OPERATOR_DECISION_REQUIRED,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All transaction-engine semantics tests PASSED.")

print("")
print("These pin the MODEL proposed by docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md.")
print("The ESPHome firmware does not use this module - see that document's gap")
print("analysis for where the live implementations currently differ.")

if FAILURES:
    sys.exit(1)
