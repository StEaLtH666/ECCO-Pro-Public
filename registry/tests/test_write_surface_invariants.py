#!/usr/bin/env python3
"""Offline structural invariants over EVERY firmware write path.

No I/O, no hardware, no ESPHome toolchain. Uses tools/analyze_write_surface.py
to parse the firmware into a structured model once, then asserts
properties over all eleven write paths uniformly instead of grepping for
C++ string literals in two of them.

Relationship to registry/tests/test_reg244_proof_harness_logic.py
-----------------------------------------------------------------
That file proved structural facts CAN be asserted offline, and it remains
the deeper check for register 244 specifically. This file is the
breadth complement: it asserts the properties every write path must have,
and - importantly - it RECORDS the places where the live firmware does
not have them, as explicit expected-deviation entries rather than as
silence. A deviation disappearing is a test failure, so nobody can fix
one of these without the test noticing.

What this cannot prove
----------------------
That the firmware compiles, that ESPHome schedules these actions in the
order the source implies, or that the inverter does anything in
particular. It reports structure. See
docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md for what the structure
means.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_write_surface import (  # noqa: E402
    DEFAULT_FIRMWARE,
    OWNERSHIP_FLAGS,
    analyze,
    conflict_matrix,
    lock_taken_without_check,
    ownership_blind_spots,
    unguarded_write_paths,
    write_surface,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not DEFAULT_FIRMWARE.is_file():
    print(f"  FAIL  firmware not found at {DEFAULT_FIRMWARE}")
    sys.exit(1)

result = analyze(DEFAULT_FIRMWARE)
paths = result["paths"]
writers = sorted((p for p in paths if p.kind == "script" and p.writes), key=lambda p: p.name)
by_name = {p.name: p for p in writers}

# ---------------------------------------------------------------------------
# The eleven write paths this firmware has, as of main @ aa492b9. A new
# write path appearing is a safety-relevant event and must not slip in
# unremarked, so the set is pinned.
# ---------------------------------------------------------------------------
EXPECTED_WRITE_PATHS = {
    "write_inverter_rtc",
    "start_free_power_override",
    # 2026-09-22 Free Power firmware hardening: restore_free_power_snapshot
    # is now a thin public wrapper (retry/backoff gate, target 5; durable
    # END-request commit, target 2) that never issues Modbus itself - the
    # actual write/verify body was factored out into
    # restore_free_power_snapshot_dispatch. See that script's own header
    # comment for why calling it directly instead of through the wrapper
    # is documented as unsupported, and for the redundant mutex
    # re-acquisition it performs anyway as defence in depth.
    "restore_free_power_snapshot_dispatch",
    # PR 2 of 3 - Free Power operator recovery: FORCE RESTORE ORIGINAL.
    # free_power_recovery_force_restore (the public wrapper reachable only
    # from the free_power_recovery_execute API action) issues zero Modbus
    # ops itself - see registry/tests/test_free_power_recovery_force_restore.py -
    # so only its dispatch counterpart appears here, exactly like
    # restore_free_power_snapshot / restore_free_power_snapshot_dispatch
    # above.
    "free_power_recovery_force_restore_dispatch",
    "apply_manual_slot1",
    "apply_manual_slot2",
    "apply_manual_slot3",
    "apply_manual_slot4",
    "apply_manual_slot5",
    "apply_manual_slot6",
    "apply_reg244_settings",
    "restore_reg244_snapshot",
    # Manual Dump-to-Grid V1 (2026-09-26) - see docs/DUMP_TO_GRID_V1.md.
    # restore_dump_to_grid_snapshot is a single script (no separate public
    # wrapper/dispatch split like Free Power's) - request_dump_end is a
    # thin durable-annotation helper that itself issues zero Modbus ops, so
    # only the worker it delegates to appears here.
    "start_dump_to_grid_override",
    "restore_dump_to_grid_snapshot",
    # Dump-to-Grid V1.1 closed-loop export controller (2026-09-26): a THIRD
    # writer of {256-261} (never 244) - see docs/DUMP_TO_GRID_V1.md
    # "Closed-loop export controller (V1.1)". Runs from the 15s watchdog
    # while ACTIVE, adjusting the battery discharge ceiling towards a
    # measured grid-export target using the same write/verify/mutex
    # discipline as start_dump_to_grid_override.
    "dump_controller_tick",
    # SG-02 corrupt-lockout export CONTAINMENT (fix/sg02-dump-lockout-containment):
    # a FOURTH Dump writer, of register 244 ONLY (already in Dump's write
    # surface - the register set below is unchanged). Writes the literal
    # value 2 (Zero Export) only when a fresh read shows 244 = 0 under a
    # corrupt/disputed Dump obligation; never 256-261, never durable state.
    # See registry/tests/test_dump_lockout_containment_sg02.py.
    "dump_lockout_containment",
}

# The complete set of registers this firmware can write. This is the
# claim docs/INVERTER_CAPABILITY_REGISTRY.md's "Full write surface"
# section and registry/inverter_capabilities.yaml's header comment both
# make; pinning it here means a future firmware change that widens the
# write surface fails a test instead of silently invalidating both
# documents.
EXPECTED_WRITTEN_REGISTERS = (
    {22, 23, 24}  # RTC
    | {230, 232}  # grid charge current, grid charge enable bit
    | set(range(244, 245))  # Load/Export Mode
    | set(range(250, 262))  # TOU slot start/end times and powers
    | set(range(268, 280))  # TOU slot target SOC and source/mode flags
)

print("[1] The set of write paths is exactly the fourteen that are documented")
check(
    "no write path has appeared or disappeared",
    set(by_name) == EXPECTED_WRITE_PATHS,
    f"unexpected={sorted(set(by_name) - EXPECTED_WRITE_PATHS)} "
    f"missing={sorted(EXPECTED_WRITE_PATHS - set(by_name))}",
)

print("")
print("[2] The full write surface is exactly the documented register set")
actual_registers = set(write_surface(paths))
check(
    "no register outside the documented write surface is ever written",
    actual_registers == EXPECTED_WRITTEN_REGISTERS,
    f"unexpected={sorted(actual_registers - EXPECTED_WRITTEN_REGISTERS)} "
    f"missing={sorted(EXPECTED_WRITTEN_REGISTERS - actual_registers)}",
)
check(
    "register 245 (Export Limit) is never written - no control path exists for it",
    245 not in actual_registers,
)
print("")
print("[2b] Manual Dump-to-Grid V1's forbidden registers are never written")
# docs/DUMP_TO_GRID_V1.md's explicit write-surface contract: 243, 245, 248
# and 250-255 must never be written by ANY path this feature adds. 250-255
# are already written by the pre-existing TOU slot writers (unrelated to
# Dump), so this checks the GLOBAL write surface for 243/245/248
# specifically (245 also re-checked just above) and separately confirms
# neither Dump script's OWN written-register set includes any of them.
for addr in (243, 245, 248):
    check(f"register {addr} is never written by any path at all", addr not in actual_registers)
p = by_name["dump_lockout_containment"]
check(
    "dump_lockout_containment (SG-02): write surface is exactly {244} - never 256-261",
    p.written_addresses == {244},
    f"actual={sorted(p.written_addresses)}",
)
for name in ("start_dump_to_grid_override", "restore_dump_to_grid_snapshot"):
    p = by_name[name]
    check(
        f"{name}: write surface is exactly {{244, 256-261}}",
        p.written_addresses == {244, 256, 257, 258, 259, 260, 261},
        f"actual={sorted(p.written_addresses)}",
    )
    check(
        f"{name}: touches none of the forbidden registers (243, 245, 248, 250-255)",
        not (p.written_addresses & ({243, 245, 248} | set(range(250, 256)))),
    )

print("")
print("[3] Every write path that writes also reads back")
for p in writers:
    if p.name == "write_inverter_rtc":
        # RTC verifies via a separate scheduled read (button.read_inverter_clock,
        # 10s after the write) rather than inline, so it legitimately has
        # no read of its own. Recorded, not silently skipped.
        check(
            f"{p.name}: verified out-of-band by a scheduled read (known deviation)",
            not p.reads,
        )
        continue
    check(f"{p.name}: performs at least one read", bool(p.reads))

print("")
print("[4] Every write path requires an explicit arm switch")
EXPECTED_UNARMED = {
    # RTC correction is deliberately unattended - `automatic_clock_sync`
    # is a standing enable, not a per-write arm. Documented as an
    # intentional difference in docs/RTC_ARCHITECTURE_AUDIT.md.
    "write_inverter_rtc",
    # Restore is the safe direction and must stay reachable without an
    # arm; the firmware comment states this explicitly. (The public
    # restore_free_power_snapshot wrapper gates on a retry/backoff decision
    # instead of an arm switch - see hardening target 5 - and
    # restore_free_power_snapshot_dispatch, which actually writes, inherits
    # the same "no arm, always reachable" property.)
    "restore_free_power_snapshot_dispatch",
    # PR 2 of 3 - Force Restore Original's arm (free_power_recovery_arm) is
    # checked in the WRAPPER (free_power_recovery_force_restore), not in
    # this dispatch script - and by design cannot ALSO be re-checked here:
    # the wrapper's one-shot semantics deliberately turn the arm back OFF
    # (see free_power_recovery_force_restore's own header comment) BEFORE
    # ever calling this dispatch, so by the time this script runs the arm
    # is always already off. Requiring it to still read ON here would be
    # self-contradictory with that one-shot design, not a gap - the real
    # gate this dispatch depends on is free_power_recovery_force_gate_ok,
    # decided entirely by the wrapper.
    "free_power_recovery_force_restore_dispatch",
    # Manual Dump-to-Grid V1 (2026-09-26): same "restore is always the safe
    # direction, no arm required" reasoning as restore_free_power_snapshot_dispatch
    # above.
    "restore_dump_to_grid_snapshot",
    # Dump-to-Grid V1.1 closed-loop controller (2026-09-26): dump_controller_tick
    # is driven entirely by the ACTIVE lease state (dump_active_persisted) and
    # measured grid error - there is no separate arm switch for a routine
    # in-lease ceiling correction, same "always reachable while the
    # governing state permits it" reasoning as the restore paths above.
    "dump_controller_tick",
    # SG-02 containment: a fail-safe action (turns export OFF, never on),
    # driven entirely by the corrupt-lockout state - same "no arm, always
    # reachable while the governing state permits it" reasoning as the
    # restore paths above.
    "dump_lockout_containment",
}
for p in writers:
    if p.name in EXPECTED_UNARMED:
        check(f"{p.name}: intentionally requires no per-write arm (known deviation)", not p.arms_checked)
    else:
        check(f"{p.name}: checks an arm switch before writing", bool(p.arms_checked))

print("")
print("[5] Every write path acquires the shared write mutex before its first write")
unguarded = {row["script"]: row["reason"] for row in unguarded_write_paths(paths)}
# THE finding. `write_inverter_rtc` writes registers 22-24 without ever
# setting or consulting manual_write_in_progress, so it is outside the
# arbitration every other path participates in. Pinned as a KNOWN,
# documented deviation so that (a) it cannot be forgotten and (b) fixing
# it fails this test, forcing the fix to be acknowledged.
KNOWN_UNGUARDED = {"write_inverter_rtc"}
check(
    "the set of write paths outside the shared mutex is exactly the known one",
    set(unguarded) == KNOWN_UNGUARDED,
    f"actual={sorted(unguarded)} expected={sorted(KNOWN_UNGUARDED)}",
)
for p in writers:
    if p.name in KNOWN_UNGUARDED:
        continue
    acq = p.acquires.get("manual_write_in_progress")
    fw = p.first_write_offset
    check(
        f"{p.name}: sets manual_write_in_progress before its first write",
        acq is not None and fw is not None and acq < fw,
    )

print("")
print("[5b] Every write path that takes the shared mutex first verifies it was free")
# 2026-09-26 adversarial review (M2): unlike check [5] above, this proves
# the script actually GATES on the flag being free before taking it, not
# merely that it sets the flag before its first write - a script could set
# manual_write_in_progress=true unconditionally and still stomp a lock
# another transaction already holds.
lock_without_check = {row["script"]: row["reason"] for row in lock_taken_without_check(paths)}
# Pre-existing, out-of-scope deviations (not part of this review): both
# dispatch scripts are internal workers whose PUBLIC wrapper
# (restore_free_power_snapshot / free_power_recovery_force_restore) already
# gates on !manual_write_in_progress before calling them - the dispatch
# script's own unconditional acquire is documented, deliberate defence in
# depth (see EXPECTED_UNARMED's own comment on
# free_power_recovery_force_restore_dispatch above), not an unreviewed gap.
KNOWN_LOCK_TAKEN_WITHOUT_CHECK = {
    "restore_free_power_snapshot_dispatch",
    "free_power_recovery_force_restore_dispatch",
}
check(
    "the set of scripts that take the mutex without checking it first is exactly the known one",
    set(lock_without_check) == KNOWN_LOCK_TAKEN_WITHOUT_CHECK,
    f"actual={sorted(lock_without_check)} expected={sorted(KNOWN_LOCK_TAKEN_WITHOUT_CHECK)}",
)
check(
    "dump_controller_tick (M2 fix) verifies manual_write_in_progress is free before taking it",
    "dump_controller_tick" not in lock_without_check,
)

print("")
print("[6] Every write path releases every mutex it acquires, on every exit")
for p in writers:
    for flag in sorted(p.acquires):
        check(f"{p.name}: releases {flag}", flag in p.releases)

print("")
print("[7] Ownership blind spots are exactly the ones the audit recorded")
# A write path that never consults an ownership flag cannot defer to the
# transaction holding it. These are the current, real gaps.
blind = {row["script"]: set(row["does_not_check"]) for row in ownership_blind_spots(paths)}
EXPECTED_BLIND = {
    # 2026-09-22 hardening (target 8 / audit finding F1): write_inverter_rtc
    # now re-checks manual_write_in_progress at its own final dispatch
    # point and defers if a hardened transaction owns the bus - see its
    # header comment. It still does not consult
    # correction_in_progress/free_power_operation_in_progress/
    # reg244_apply_in_progress directly (manual_write_in_progress is set by
    # every one of those transactions before their first write, so it is
    # the one flag that actually matters here - see OWNERSHIP_FLAGS'
    # "most-shared first" ordering).
    "write_inverter_rtc": set(OWNERSHIP_FLAGS) - {"manual_write_in_progress"},
    # Free Power never consults the register 244 transaction's own flag, or
    # (2026-09-26) Dump-to-Grid's - in practice both also hold
    # manual_write_in_progress, so the bus is still arbitrated, but the
    # dependency is implicit, not stated.
    "start_free_power_override": {"reg244_apply_in_progress", "dump_operation_in_progress"},
    # restore_free_power_snapshot_dispatch also doesn't re-check
    # correction_in_progress itself (only its public wrapper,
    # restore_free_power_snapshot, does, as part of the same precondition
    # re-check documented on the _dispatch script) - same class of
    # "checked one layer up" gap as reg244_apply_in_progress/
    # dump_operation_in_progress above.
    "restore_free_power_snapshot_dispatch": {"correction_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress"},
    # PR 2 of 3 - same class of "checked one layer up" gap as
    # restore_free_power_snapshot_dispatch immediately above: these two
    # are checked in free_power_recovery_force_restore's own precondition
    # gate, not re-checked in this dispatch script.
    "free_power_recovery_force_restore_dispatch": {"correction_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress"},
    # Manual TOU Phase 1 (2026-09-29): the six apply_manual_slotN scripts
    # used to be listed here (they never consulted Free Power's / Dump's
    # in-progress flags or reg244_apply_in_progress, and Free Power's and
    # Dump's PERSISTED ownership was checked only in the button handler).
    # Each script now checks every OWNERSHIP_FLAGS entry in its own
    # admission gate, so none of them has a blind spot any more - see
    # registry/tests/test_manual_tou_phase1_ownership_gates.py.
    "apply_reg244_settings": {"free_power_operation_in_progress", "dump_operation_in_progress"},
    "restore_reg244_snapshot": {"free_power_operation_in_progress", "dump_operation_in_progress"},
    # Manual Dump-to-Grid V1 (2026-09-26): restore_dump_to_grid_snapshot
    # never consults Free Power's or reg244's own in-progress flags - same
    # "implicit via manual_write_in_progress" class of gap as
    # restore_free_power_snapshot_dispatch above. Unlike every other script
    # here, start_dump_to_grid_override has NO blind spots at all (it
    # explicitly checks every OWNERSHIP_FLAGS entry) and so does not appear
    # in this map.
    "restore_dump_to_grid_snapshot": {"free_power_operation_in_progress", "reg244_apply_in_progress"},
    # Dump-to-Grid V1.1 closed-loop controller (2026-09-26): same class of
    # gap as restore_dump_to_grid_snapshot above (implicit via
    # manual_write_in_progress, which every one of those transactions sets
    # before its own first write) - but this script DOES check
    # correction_in_progress explicitly, since RTC correction is the one
    # transaction that writes the bus without ever setting
    # manual_write_in_progress (see write_inverter_rtc's own KNOWN_UNGUARDED
    # entry above).
    "dump_controller_tick": {"free_power_operation_in_progress", "reg244_apply_in_progress"},
}
check(
    "the ownership blind-spot map matches the audit exactly",
    blind == EXPECTED_BLIND,
    f"actual={ {k: sorted(v) for k, v in sorted(blind.items())} }",
)

print("")
print("[8] Free Power ownership is enforced in the button handlers AND (Manual TOU Phase 1) in the TOU write scripts")
# This is a structural fact with a real consequence, so it gets its own
# check rather than a comment: the guard that stops a TOU write during an
# active Free Power override used to live ONLY in the BUTTON handler, not
# in the script, so a script invoked by any other means was not protected.
buttons = {p.name: p for p in paths if p.kind == "button"}
guarded_buttons = [
    name
    for name, b in buttons.items()
    if "free_power_active_persisted" in b.body and "free_power_snapshot_valid" in b.body
]
check(
    "several button handlers carry the Free Power persisted-ownership guard",
    len(guarded_buttons) >= 8,
    f"found {len(guarded_buttons)}: {sorted(guarded_buttons)}",
)
# Manual TOU Phase 1 (2026-09-29) closed the layering gap this section
# used to pin ("apply_manual_slotN itself does NOT check
# free_power_active_persisted"): the script itself now refuses too, so a
# caller that bypasses the button is still protected. The button guard
# stays as a second layer. The gate's exact shape (first action, pure
# conjunction, every term, mutation-tested) is pinned in
# registry/tests/test_manual_tou_phase1_ownership_gates.py.
for n in list(range(1, 7)):
    script = by_name[f"apply_manual_slot{n}"]
    check(
        f"apply_manual_slot{n} itself checks free_power_active_persisted and dump_active_persisted "
        f"(Manual TOU Phase 1 - the button is no longer the only layer)",
        "free_power_active_persisted" in script.body and "dump_active_persisted" in script.body,
    )

print("")
print("[9] Shared registers are declared, and match the capability registry's view")
conflicts = {row["address"]: set(row["writers"]) for row in conflict_matrix(paths)}
# PR 2 of 3 added a NINTH writer of register 232 (free_power_recovery_force_restore_dispatch,
# Phase 1 of Force Restore Original) - was eight before this PR.
check("register 232 is written by all nine TOU/Free Power/Force Restore paths", len(conflicts.get(232, ())) == 9)
check(
    "register 250 is written by both slot 1 and slot 6 (the TOU boundary wrap)",
    conflicts.get(250) == {"apply_manual_slot1", "apply_manual_slot6"},
)
check(
    "register 244 is contended between reg244's own two paths and the three Dump-to-Grid 244 writers "
    "(start, restore, SG-02 containment)",
    conflicts.get(244) == {
        "apply_reg244_settings",
        "restore_reg244_snapshot",
        "start_dump_to_grid_override",
        "restore_dump_to_grid_snapshot",
        "dump_lockout_containment",
    },
    f"{sorted(conflicts.get(244, ()))}",
)
# 2026-09-23: registers 256-261 (TOU Power) joined 268-279 as Free-Power-owned
# (previously only their own TOU slot writer touched them) - see
# registry/tests/test_free_power_tou_power_ownership_2026_09_23.py for the
# behavioural proof; this is the structural write-surface consequence.
# PR 2 of 3 added a FOURTH writer of these same registers
# (free_power_recovery_force_restore_dispatch) - was three before this PR.
# 2026-09-26: Manual Dump-to-Grid V1 added a FIFTH and SIXTH writer of
# 256-261 specifically (its own start/restore paths) - 268-279 are
# unaffected (Dump-to-Grid deliberately does not touch them, see
# docs/DUMP_TO_GRID_V1.md "Why 268-279 is untouched"), so the two ranges'
# contention counts now genuinely differ.
# 2026-09-26 V1.1: the closed-loop controller (dump_controller_tick) added a
# SEVENTH writer of 256-261 only - 244 and 268-279 are unaffected.
for addr in range(256, 262):
    check(
        f"register {addr} is contended between a TOU slot writer, both Free Power paths, Force Restore, and all three Dump-to-Grid paths",
        len(conflicts.get(addr, ())) == 7,
        f"{sorted(conflicts.get(addr, ()))}",
    )
for addr in range(268, 280):
    check(
        f"register {addr} is contended between a TOU slot writer and both Free Power paths (plus Force Restore) - Dump-to-Grid does not touch it",
        len(conflicts.get(addr, ())) == 4,
        f"{sorted(conflicts.get(addr, ()))}",
    )

print("")
print("[10] Multi-register transactions durably commit a snapshot before writing")
# A path that writes more than one register and cannot be re-derived must
# have somewhere to roll back to. Free Power and Register 244 do. The TOU
# slot writers do NOT - they write five/six registers with no persisted
# pre-write state at all, which is the audit's second-highest finding.
#
# 2026-09-21 durability/sequencing hotfix: "sets the flag, then waits
# >=1000ms" was never a durability proof (a plain global assignment does
# not reach ESPHome's preferences pending-save queue by itself - see
# docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md).
# Both paths now call ecco_durable::commit_record() twice before their
# first write (Phase A: snapshot data: Phase B: a separate valid marker,
# committed only if Phase A's own sync() succeeded) and use its checked
# boolean result to gate the write, with zero fixed `delay:` steps
# anywhere in either script.
PERSISTED_SNAPSHOT_PATHS = {
    "start_free_power_override": "free_power_snapshot_valid",
    "apply_reg244_settings": "reg244_snapshot_valid",
    "start_dump_to_grid_override": "dump_snapshot_valid",
}
for name, flag in PERSISTED_SNAPSHOT_PATHS.items():
    p = by_name[name]
    idx_flag = p.body.find(f"id({flag}) = true")
    fw = p.first_write_offset
    check(f"{name}: sets {flag} before its first write", idx_flag != -1 and fw is not None and idx_flag < fw)
    check(
        f"{name}: commits a durable record at least twice (data + valid marker) before its first write",
        p.durable_commits_before(fw) >= 2,
        f"durable commits before first write: {p.durable_commits_before(fw)}",
    )
    check(
        f"{name}: has NO fixed delay: step anywhere (sequencing is completion-driven, not time-based)",
        not p.delays_ms,
        f"delays found: {p.delays_ms}",
    )
for n in range(1, 7):
    p = by_name[f"apply_manual_slot{n}"]
    check(
        f"apply_manual_slot{n}: writes {len(p.written_addresses)} registers with NO persisted "
        f"snapshot (known gap, see audit finding F2)",
        not any("snapshot" in f for f in p.obligations_set),
    )

print("")
print("[11] Transaction sequencing: time-based (TOU slots) vs completion-based (hotfixed paths)")
# The six TOU slot writers still pace themselves with fixed delays -
# unchanged, out of scope for the 2026-09-21 durability/sequencing
# hotfix (see docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md
# Part 4 for why scope stayed tight). Free Power and Register 244 (both
# Apply/Start and Restore) were hardened: their progression now depends
# on a wait_until awaiting a terminal flag set by the operation's own
# on_response/on_error/on_no_response/on_not_sent callback, never on a
# fixed delay elapsing.
COMPLETION_DRIVEN_PATHS = {
    "start_free_power_override",
    "restore_free_power_snapshot_dispatch",
    "apply_reg244_settings",
    "restore_reg244_snapshot",
    # PR 2 of 3 - Force Restore Original's confirm-read/write/verify
    # sequence is entirely wait_until-driven, with zero fixed delay: steps,
    # exactly like the restore path it reuses the write form from.
    "free_power_recovery_force_restore_dispatch",
    # Manual Dump-to-Grid V1 (2026-09-26) - built on the same wait_until/
    # ecco_durable::commit_record() pattern from the start, never on fixed
    # delays.
    "start_dump_to_grid_override",
    "restore_dump_to_grid_snapshot",
    # Dump-to-Grid V1.1 closed-loop controller (2026-09-26): same
    # wait_until/commit_record discipline, zero fixed delays.
    "dump_controller_tick",
    # SG-02 containment: wait_until-driven read/write/reread, zero delays.
    "dump_lockout_containment",
}
for p in writers:
    if p.name == "write_inverter_rtc":
        continue
    if p.name in COMPLETION_DRIVEN_PATHS:
        check(
            f"{p.name}: sequences with wait_until on a terminal flag, not fixed delays",
            bool(p.wait_until_offsets) and not p.delays_ms,
            f"wait_until={len(p.wait_until_offsets)} delays={p.delays_ms}",
        )
    else:
        check(f"{p.name}: paces its Modbus sequence with fixed delays (known, unchanged)", bool(p.delays_ms))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All write-surface invariant tests PASSED.")

print("")
print("These are STRUCTURAL facts about the firmware source file, pinned so that")
print("a change to the inverter write surface or its ownership model cannot land")
print("unnoticed. They prove nothing about hardware behaviour.")

if FAILURES:
    sys.exit(1)
