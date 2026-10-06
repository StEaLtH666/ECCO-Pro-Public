#!/usr/bin/env python3
"""Offline tests for registry/transaction_state_machine.py.

No I/O, no hardware, no network - pure state-machine logic. Covers the
synthetic scenarios requested for Task 005 section 13 that relate to
the transaction lifecycle: write without arm, expired arm, verification
mismatch, partial multi-register write (modelled as write_failed),
restoration failure, concurrent transaction attempt, and stale
snapshot.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transaction_state_machine import (  # noqa: E402
    IllegalTransition,
    TransactionError,
    TransactionRegistry,
    TransactionState,
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


print("[1] Happy path: idle -> ... -> completed -> idle (no restore needed)")
reg = TransactionRegistry()
txn = reg.start("tou_slot_1_power")
check("begin() reaches snapshotting", txn.state is TransactionState.SNAPSHOTTING)
txn.snapshot_ok({256: 8000})
check("snapshot_ok() reaches staged", txn.state is TransactionState.STAGED)
txn.stage(4000)
txn.arm()
check("arm() reaches armed", txn.state is TransactionState.ARMED)
txn.begin_write()
check("begin_write() reaches writing", txn.state is TransactionState.WRITING)
txn.writes_accepted()
check("writes_accepted() reaches verifying", txn.state is TransactionState.VERIFYING)
txn.verified()
check("verified() reaches completed", txn.state is TransactionState.COMPLETED)
txn.no_restore_needed()
check("no_restore_needed() returns to idle", txn.state is TransactionState.IDLE)
check("registry has no active transaction once idle", reg.active is None)

print("")
print("[2] Write without arm -> rejected")
txn2 = reg.start("tou_slot_1_power")
txn2.snapshot_ok({256: 8000})
# Still 'staged', never armed: begin_write() must refuse. It raises
# TransactionError specifically (a more informative "no arm token"
# message) rather than the generic IllegalTransition, since the guard
# checks for a missing arm token before even consulting the transition
# table - both are "rejected", but the exact exception type is part of
# the contract this test pins down.
expect_raises(TransactionError, lambda: txn2.begin_write(), "begin_write() before arm() is rejected with TransactionError (no arm token)")
check("state is unchanged (still 'staged') after the rejected write attempt", txn2.state is TransactionState.STAGED)

print("")
print("[3] Expired arm -> write is rejected and state returns to staged")
txn3 = TransactionRegistry().start("free_power_transaction")
txn3.snapshot_ok({230: 38})
txn3.stage(4000)
t0 = time.time()
txn3.arm(now=t0)
expired_now = t0 + 999  # far beyond the default 20s expiry
expect_raises(TransactionError, lambda: txn3.begin_write(now=expired_now), "begin_write() after arm expiry raises")
check("expired arm returns the transaction to 'staged', not left 'armed'", txn3.state is TransactionState.STAGED)

print("")
print("[4] Verification mismatch is a real failure, not success")
txn4 = TransactionRegistry().start("tou_slot_1_power")
txn4.snapshot_ok({256: 8000})
txn4.stage(4000)
txn4.arm()
txn4.begin_write()
txn4.writes_accepted()
txn4.verify_mismatch("expected 4000, read 8000")
check("verify_mismatch() reaches failed, not completed", txn4.state is TransactionState.FAILED)
check("failed transaction is disarmed", txn4.arm_token is None)

print("")
print("[5] Partial multi-register write (write_failed) -> failed, not completed")
txn5 = TransactionRegistry().start("free_power_transaction")
txn5.snapshot_ok({230: 38, 232: 1})
txn5.stage({"reg230": 20})
txn5.arm()
txn5.begin_write()
txn5.write_failed("register 268-279 write timed out after 230/232 succeeded")
check("write_failed() reaches failed (never partially 'completed')", txn5.state is TransactionState.FAILED)
check("write_failed disarms", txn5.arm_token is None)

print("")
print("[6] Restoration failure is visible as restore_failed, never claims success")
txn6 = TransactionRegistry().start("free_power_transaction")
txn6.snapshot_ok({230: 38, 232: 1})
txn6.stage({"reg230": 20})
txn6.arm()
txn6.begin_write()
txn6.write_failed("timeout")
txn6.restore_attempt()
check("restore_attempt() from failed reaches restoring", txn6.state is TransactionState.RESTORING)
txn6.restore_failed("restore write itself timed out")
check("restore_failed() reaches restore_failed, not idle", txn6.state is TransactionState.RESTORE_FAILED)
check("restore_failed is not silently treated as idle/success", txn6.state is not TransactionState.IDLE)
# A further explicit retry is legal:
txn6.restore_attempt()
check("a further explicit restore_attempt from restore_failed is legal", txn6.state is TransactionState.RESTORING)
txn6.restore_verified()
check("restore_verified() from a retried restore reaches idle", txn6.state is TransactionState.IDLE)

print("")
print("[7] Concurrent transaction attempt is rejected")
reg7 = TransactionRegistry()
t7a = reg7.start("tou_slot_1_power")
check("first start() succeeds", t7a.state is TransactionState.SNAPSHOTTING)
expect_raises(TransactionError, lambda: reg7.start("tou_slot_2_power"), "a second start() while the first is active is rejected")
check("registry still reports the first transaction as active", reg7.active is t7a)
# Once the first completes and returns to idle, a new one is allowed:
t7a.snapshot_ok({1: 1})
t7a.stage(1)
t7a.arm()
t7a.begin_write()
t7a.writes_accepted()
t7a.verified()
t7a.no_restore_needed()
t7b = reg7.start("tou_slot_2_power")
check("a new transaction is allowed once the previous one returned to idle", t7b.state is TransactionState.SNAPSHOTTING)

print("")
print("[8] Stale snapshot -> cannot arm")
txn8 = TransactionRegistry().start("tou_slot_1_power")
old_time = time.time() - 999  # far beyond the default 30s max_age
txn8.snapshot_ok({256: 8000}, now=old_time)
txn8.stage(4000)
expect_raises(TransactionError, lambda: txn8.arm(), "arm() against a stale snapshot raises")
check("still in 'staged' after the rejected arm attempt", txn8.state is TransactionState.STAGED)

print("")
print("[9] Restart-safety: mid_transaction() correctly flags every non-terminal state")
mid_states_seen = []
txn9 = TransactionRegistry().start("tou_slot_1_power")
mid_states_seen.append((txn9.state, txn9.mid_transaction()))
txn9.snapshot_ok({256: 8000})
mid_states_seen.append((txn9.state, txn9.mid_transaction()))
txn9.stage(4000)
txn9.arm()
mid_states_seen.append((txn9.state, txn9.mid_transaction()))
txn9.begin_write()
mid_states_seen.append((txn9.state, txn9.mid_transaction()))
txn9.writes_accepted()
mid_states_seen.append((txn9.state, txn9.mid_transaction()))
check(
    "every state from snapshotting through verifying is mid_transaction() == True",
    all(is_mid for (_s, is_mid) in mid_states_seen),
    f"{mid_states_seen}",
)
txn9.verified()
check("completed is NOT mid_transaction (safe to have been left there across a restart)", txn9.mid_transaction() is False)
txn9.no_restore_needed()
check("idle is NOT mid_transaction", txn9.mid_transaction() is False)

print("")
print("[10] Illegal transitions generally are rejected (not just the named scenarios above)")
txn10 = TransactionRegistry().start("tou_slot_1_power")
expect_raises(IllegalTransition, lambda: txn10.verified(), "verified() is illegal directly from snapshotting")
# restore_attempt() needs a snapshot to even reach the state-transition
# check (see [2]'s note on guard ordering) - snapshot first so this
# actually exercises "illegal from a state other than failed/
# restore_failed", not the separate "no snapshot at all" guard.
txn10.snapshot_ok({1: 1})
check("txn10 is now 'staged', with a snapshot recorded", txn10.state is TransactionState.STAGED)
expect_raises(IllegalTransition, lambda: txn10.restore_attempt(), "restore_attempt() is illegal from 'staged' even with a snapshot present (only legal from failed/restore_failed)")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All state-machine offline tests PASSED.")

print("")
print("This proves the STATE MACHINE's rules are internally consistent and enforced.")
print("It does NOT prove any real ESPHome/HA implementation follows these rules -")
print("no such implementation exists yet. See docs/SAFE_WRITE_TRANSACTION_ARCHITECTURE.md.")

if FAILURES:
    sys.exit(1)
