#!/usr/bin/env python3
"""Free Power write-sequencing hardening (SG-01 design-review defects A/B).

The SG-01 design review found two sequencing defects in the Stage 3.4 Free
Power firmware (firmware/ecco_clock_dongle_stage3_4_free_power.yaml):

  DEFECT A - start_free_power_override issues four mutation writes after the
  durable snapshot commit:
      B1 = reg232, B2 = reg230, B3 = regs268-279, B4 = regs256-261.
  Only B4 was gated on earlier success (and on the positive 268-279
  readback). B2 and B3 were still issued after an earlier write had
  already failed.
  Required invariant: once any START write or required verification fails,
  START issues no further mutation write, and falls through to the existing
  failure -> restore route with the durable obligation intact.

  DEFECT B - restore_free_power_snapshot_dispatch (ordinary restore) wrote
  B2/reg230 straight after the B3/268-279 restore write, with no re-check
  in between, so a failed B3 write still let B2 be written.
  free_power_recovery_force_restore_dispatch already gated 230 on the
  268-279 write's success; the ordinary restore now does the same.

No I/O, no hardware, no ESPHome/C++ toolchain. Everything below runs on
the REAL extracted firmware action tree via registry/tests/_free_power_action_sim.py:
the real writes and their value lambdas, reads, on_* handler lambdas,
bounded-wait timeout lambdas and `if:` gates, with injected per-operation
outcomes over a concrete register bank. The only test instrumentation is
the durable marker-clear/re-commit block inside each final-verify handler,
excised exactly as registry/tests/test_free_power_reg244_context_v4.py
section [P] does (see _verify_harness) - that block contains no Modbus
action and is covered by registry/tests/test_recovery_marker_state_machine.py.

Sections:
  [A] START: B1/B2/B3 failures and B3 readback failures stop every later write
  [B] START: exhaustive fault sweep - writes attempted are exactly the
      prefix up to the first failing step; every failure routes to restore
      with the snapshot/marker untouched
  [C] START: successful sequence unchanged
  [D] RESTORE: B3 failure stops B2/reg230; success still reaches B2
  [E] RESTORE: exhaustive fault sweep + marker-clear reachability
  [F] Force Restore parity: ordinary restore's 230 gate now has the same
      shape as Force Restore's
  [G] Mutation: removing the new gates must be detected
"""

from __future__ import annotations

import copy
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as _ds  # noqa: E402
import _free_power_action_sim as _sim  # noqa: E402
import _sg01_journal_model as _jm  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not FIRMWARE_PATH.is_file():
    print(f"  FAIL  required file not found: {FIRMWARE_PATH}")
    sys.exit(1)

fw_text, SCRIPTS = _sim.load_scripts(FIRMWARE_PATH)
WRITE, READ = _sim.WRITE, _sim.READ
_single, _cond_text = _sim._single, _sim._cond_text

GATE_NO_WRITE_FAILED = "return !id(free_power_write_failed);"
FORCE_GATE_NO_WRITE_FAILED = "return !id(free_power_recovery_force_write_failed);"
GATE_START_COMMIT = (
    "return !id(free_power_write_failed) && id(free_power_snapshot_230_ok) && id(free_power_snapshot_232_ok) "
    "&& id(free_power_snapshot_tou_ok) && id(free_power_snapshot_context_ok);"
)

# Write outcomes that are NOT a positive terminal success. "ok" and
# "ack_not_applied" both reach on_response (an FC16 acknowledgement), which
# is the only per-write success signal the firmware has.
FAILING_WRITE = ("error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed", "timeout_lost")
ACKED_WRITE = ("ok", "ack_not_applied")
FAILING_READ = ("ok_changed", "error", "not_sent", "no_response", "timeout")

MARKER_SENTINEL = "RESTORE_REQUIRED"  # never assigned by anything simulated here

# ---------------------------------------------------------------------------
# Scenario registers (same shape as test_free_power_tou_power_ownership_2026_09_23.py).
# 231 and 262-267 are read (230x3 / 256x24 spans) but not owned: placeholders.
# ---------------------------------------------------------------------------
OWNED = (230, 232, *range(256, 262), *range(268, 280))
TARGET_POWER = 8000
TARGET_AMPS = 50
ORIGINAL = {
    230: 120, 231: 0, 232: 0x0010,
    **dict(zip(range(256, 262), (1000, 1200, 800, 1000, 100, 3000))),
    **{a: 0 for a in range(262, 268)},
    **dict(zip(range(268, 274), (20, 20, 30, 10, 20, 50))),
    **dict(zip(range(274, 280), (0x0000, 0x0004, 0x0008, 0x0010, 0x0021, 0x0106))),
}
FREE_POWER = {
    **ORIGINAL, 230: TARGET_AMPS, 232: ORIGINAL[232] | 0x0001,
    **{a: TARGET_POWER for a in range(256, 262)},
    **{a: 100 for a in range(268, 274)},
    **{a: (ORIGINAL[a] & 0xFFFC) | 0x0001 for a in range(274, 280)},
}
LEASE_CONTEXT = 1


def _snapshot_globals() -> dict:
    return {f"free_power_snapshot_reg{a}": ORIGINAL[a] for a in OWNED}


def _verify_harness(action_list: list, scratch: str) -> list:
    """Deep copy of `action_list` whose (single) 256x24 final-verify read has
    its real on_response handler's `if (ok) { ... } else { ... }` durable
    re-commit / marker-clear block excised, and `id(<scratch>) = ok;`
    appended so the test can read the REAL computed verify result."""
    mut = copy.deepcopy(action_list)
    hits = []

    def walk(actions):
        for action in actions or []:
            kind, body = _single(action)
            if kind == READ and body.get("start_address") == 256 and body.get("count") == 24:
                hits.append(body)
            elif kind == "if":
                walk(body.get("then"))
                walk(body.get("else"))

    walk(mut)
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one 256x24 verify read, found {len(hits)}")
    real = hits[0]["on_response"]["then"][0]["lambda"]
    hits[0]["on_response"]["then"][0]["lambda"] = _sim.excise_statement(real, "if (ok) {") + f"\nid({scratch}) = ok;\n"
    return mut


def _writes(attempted) -> list[int]:
    return [addr for kind, addr, _count, _bank in attempted if kind == "write"]


def _reads(attempted) -> list[tuple[int, int]]:
    return [(addr, count) for kind, addr, count, _bank in attempted if kind == "read"]


def _find_gate_holding_write(actions, cond: str, addr: int):
    """The `if:` body with condition `cond` whose then-branch DIRECTLY
    contains the write to `addr` (depth-first), or None."""
    for action in actions or []:
        kind, body = _single(action)
        if kind != "if":
            continue
        if _cond_text(body) == cond and any(
            _single(a)[0] == WRITE and _single(a)[1]["start_address"] == addr for a in body.get("then") or []
        ):
            return body
        for branch in ("then", "else"):
            hit = _find_gate_holding_write(body.get(branch), cond, addr)
            if hit is not None:
                return hit
    return None


def _unwrap_gate_holding_write(actions, cond: str, addr: int):
    """Mutant: replace the `if:` found by _find_gate_holding_write with its
    then-branch, inline - i.e. make that write unconditional again."""
    out = []
    for action in copy.deepcopy(actions or []):
        kind, body = _single(action)
        if kind == "if":
            if _cond_text(body) == cond and any(
                _single(a)[0] == WRITE and _single(a)[1]["start_address"] == addr for a in body.get("then") or []
            ):
                out.extend(body["then"])
                continue
            for branch in ("then", "else"):
                if branch in body:
                    body[branch] = _unwrap_gate_holding_write(body[branch], cond, addr)
        out.append(action)
    return out


# ===========================================================================
# START: extract the post-commit tail of start_free_power_override
# ===========================================================================
start_actions = SCRIPTS["start_free_power_override"]["then"]
commit_gate = _sim.find_if(start_actions, lambda c: c == GATE_START_COMMIT)
check("START: found the durable-commit gate of start_free_power_override", commit_gate is not None)
start_tail = None
if commit_gate is not None:
    first_kind, first_body = _single(commit_gate["then"][0])
    check(
        "START: the commit gate's first action is the durable commit lambda (the only action before B1 in this branch)",
        first_kind == "lambda" and "ecco_durable::commit_record(" in first_body and "MARKER_RESTORE_REQUIRED" in first_body,
    )
    # Everything AFTER the durable two-phase commit: the write sequence,
    # the activation verify, and the failure -> restore routing.
    start_tail = _verify_harness(commit_gate["then"][1:], "free_power_test_activation_ok_scratch")

START_WRITES = (232, 230, 268, 256)

# SG-01 Phase 2: the START tail now contains the B2/B3/B4 START journal
# commits. They are EXECUTED (never skipped) against this real durable store
# - see _free_power_action_sim.simulate(journal_sim=...). Every commit here
# succeeds; journal commit FAILURE is swept in
# registry/tests/test_sg01_journal_phase1_2.py.
JOURNAL_SIM = _ds.Sim(_ds.load_firmware(FIRMWARE_PATH))
JOURNAL_BINDING = 0x0123456789ABCDEF  # the tail only carries it forward; any value


def start_state() -> dict:
    """State immediately after a SUCCESSFUL durable commit (the commit
    lambda itself - snapshot, marker, retry reset and the B1 START journal -
    is not simulated; it only runs before any write)."""
    return {
        "free_power_write_failed": False,
        "free_power_op_terminal": False,
        "free_power_operation_in_progress": True,
        "manual_write_in_progress": True,
        "free_power_snapshot_valid": True,
        "free_power_marker_state": MARKER_SENTINEL,
        "free_power_active_persisted": False,
        "free_power_restore_requested": False,
        "free_power_target_reg230": TARGET_AMPS,
        "free_power_target_tou_power": TARGET_POWER,
        "free_power_pre_power_overlay_confirmed": False,
        "free_power_verify_230_ok": False,
        "free_power_verify_232_ok": False,
        "free_power_failures": 0,
        "free_power_start_successes": 0,
        "free_power_test_activation_ok_scratch": None,
        **_snapshot_globals(),
        **_jm.ram_after_b1(JOURNAL_BINDING),
    }


def run_start(write_outcomes: dict, readback: str = "ok", actions=None):
    reads = {(268, 12): readback, (230, 3): "ok", (256, 24): "ok"}
    executed: list = []
    JOURNAL_SIM.reset_durable()
    bank, state, attempted, _v, skipped = _sim.simulate(
        actions if actions is not None else start_tail,
        {a: write_outcomes.get(a, "ok") for a in START_WRITES},
        reads, ORIGINAL, start_state(), executed_scripts=executed, journal_sim=JOURNAL_SIM,
    )
    return bank, state, attempted, executed


def _start_obligation_preserved(state, executed) -> list[str]:
    """Why a FAILED start did not end in the safe failure state (empty = OK)."""
    problems = []
    if executed != ["restore_free_power_snapshot"]:
        problems.append(f"executed={executed} (expected exactly the restore script)")
    if state["free_power_snapshot_valid"] is not True:
        problems.append("snapshot_valid cleared")
    if state["free_power_marker_state"] != MARKER_SENTINEL:
        problems.append(f"marker changed to {state['free_power_marker_state']!r}")
    if state["free_power_active_persisted"]:
        problems.append("active_persisted set")
    if not state["free_power_write_failed"]:
        problems.append("write_failed not set")
    if state["free_power_operation_in_progress"] or state["manual_write_in_progress"]:
        problems.append("ownership locks not released before handing to restore")
    if state["free_power_start_successes"] != 0:
        problems.append("start_successes incremented")
    if state["free_power_failures"] != 1:
        problems.append(f"failures={state['free_power_failures']} (expected exactly 1)")
    return problems


print("[A] START: a failed write or required verification stops every later mutation write")
if start_tail is not None:
    for cause in FAILING_WRITE:
        _b, st, att, ex = run_start({232: cause})
        check(f"[B1 {cause}] only B1 (232) is written - B2/B3/B4 are not", _writes(att) == [232], f"{_writes(att)}")
        check(f"[B1 {cause}] durable RESTORE_REQUIRED/snapshot preserved and routed to restore",
              not _start_obligation_preserved(st, ex), f"{_start_obligation_preserved(st, ex)}")

        _b, st, att, ex = run_start({230: cause})
        check(f"[B2 {cause}] only B1, B2 are written - B3/B4 are not", _writes(att) == [232, 230], f"{_writes(att)}")
        check(f"[B2 {cause}] durable RESTORE_REQUIRED/snapshot preserved and routed to restore",
              not _start_obligation_preserved(st, ex), f"{_start_obligation_preserved(st, ex)}")

        _b, st, att, ex = run_start({268: cause})
        check(f"[B3 {cause}] only B1, B2, B3 are written - B4 is not, and the B3 readback is skipped",
              _writes(att) == [232, 230, 268] and (268, 12) not in _reads(att), f"{_writes(att)} {_reads(att)}")
        check(f"[B3 {cause}] durable RESTORE_REQUIRED/snapshot preserved and routed to restore",
              not _start_obligation_preserved(st, ex), f"{_start_obligation_preserved(st, ex)}")

    for rb in FAILING_READ:
        bank, st, att, ex = run_start({}, readback=rb)
        check(f"[B3 readback {rb}] B4 (256-261) is not written; TOU Power keeps its originals",
              _writes(att) == [232, 230, 268] and all(bank[a] == ORIGINAL[a] for a in range(256, 262)),
              f"{_writes(att)}")
        check(f"[B3 readback {rb}] durable RESTORE_REQUIRED/snapshot preserved and routed to restore",
              not _start_obligation_preserved(st, ex), f"{_start_obligation_preserved(st, ex)}")

    bank, st, att, ex = run_start({268: "ack_not_applied"})
    check("[B3 acknowledged but not applied] the positive readback catches it: B4 is not written",
          _writes(att) == [232, 230, 268], f"{_writes(att)}")
    check("[B3 acknowledged but not applied] durable RESTORE_REQUIRED/snapshot preserved and routed to restore",
          not _start_obligation_preserved(st, ex), f"{_start_obligation_preserved(st, ex)}")

    for cause in FAILING_WRITE:
        _b, st, att, ex = run_start({256: cause})
        check(f"[B4 {cause}] no activation verify read runs after a failed B4; routed to restore with obligation intact",
              (230, 3) not in _reads(att) and (256, 24) not in _reads(att) and not _start_obligation_preserved(st, ex),
              f"{_reads(att)} {_start_obligation_preserved(st, ex)}")

# ---------------------------------------------------------------------------
print("")
print("[B] START: exhaustive fault sweep over B1..B4 and the B3 readback")
# ---------------------------------------------------------------------------
if start_tail is not None:
    n = 0
    bad_prefix, bad_obligation, bad_success = [], [], []
    for outs in itertools.product(_sim.WRITE_OUTCOMES, repeat=4):
        for rb in _sim.READ_OUTCOMES:
            wo = dict(zip(START_WRITES, outs))
            bank, st, att, ex = run_start(wo, readback=rb)
            n += 1
            # Expected prefix: stop after the first write whose outcome is
            # not an acknowledgement; B4 additionally needs the positive
            # 268-279 readback (acknowledged AND applied, readback "ok").
            expected = []
            stopped = False
            for addr in START_WRITES:
                if addr == 256:
                    if wo[268] != "ok" or rb != "ok":
                        stopped = True
                        break
                expected.append(addr)
                if wo[addr] in FAILING_WRITE:
                    stopped = True
                    break
            if _writes(att) != expected:
                bad_prefix.append((wo, rb, _writes(att), expected))
            if stopped or wo[256] in FAILING_WRITE:
                problems = _start_obligation_preserved(st, ex)
                if problems:
                    bad_obligation.append((wo, rb, problems))
            if st["free_power_test_activation_ok_scratch"] and bank != FREE_POWER:
                bad_success.append((wo, rb))
    check(f"all {n} combinations executed (8^4 write outcomes x 6 readback outcomes)", n == 8 ** 4 * 6)
    check("in every combination the writes attempted are EXACTLY the prefix up to and including the first "
          "failing step - nothing is written after a failed write or a failed/mismatched 268-279 readback",
          not bad_prefix, f"{len(bad_prefix)} bad, first: {bad_prefix[:1]}")
    check("in every combination that fails before or at B4, START hands off to restore with snapshot_valid, "
          "the RESTORE_REQUIRED marker and active_persisted=false untouched",
          not bad_obligation, f"{len(bad_obligation)} bad, first: {bad_obligation[:1]}")
    check("activation verify never reports success unless the bank genuinely holds the full Free Power state",
          not bad_success, f"{bad_success[:1]}")

# ---------------------------------------------------------------------------
print("")
print("[C] START: successful sequence unchanged")
# ---------------------------------------------------------------------------
if start_tail is not None:
    bank, st, att, ex = run_start({})
    check("happy path: writes are exactly B1 232 -> B2 230 -> B3 268-279 -> B4 256-261",
          _writes(att) == [232, 230, 268, 256], f"{_writes(att)}")
    check("happy path: reads are exactly the 268x12 safety readback, then the 230x3 and 256x24 activation verify",
          _reads(att) == [(268, 12), (230, 3), (256, 24)], f"{_reads(att)}")
    check("happy path: the bank ends in exactly the intended Free Power state", bank == FREE_POWER)
    check("happy path: the real activation verify computes ok=true", st["free_power_test_activation_ok_scratch"] is True)
    check("happy path: no restore is triggered (only the config poll), snapshot/marker untouched",
          ex == ["poll_inverter_configuration"] and st["free_power_snapshot_valid"] is True
          and st["free_power_marker_state"] == MARKER_SENTINEL and not st["free_power_write_failed"], f"{ex}")
    # The values each write carries come from the real value lambdas; pin them.
    check("happy path: B1 writes (snapshot232 | 1), B2 writes the intended amps",
          bank[232] == ORIGINAL[232] | 0x0001 and bank[230] == TARGET_AMPS)

# ===========================================================================
# RESTORE: extract restore_free_power_snapshot_dispatch's write tail
# ===========================================================================
dispatch_actions = SCRIPTS["restore_free_power_snapshot_dispatch"]["then"]


def _find_if_action(actions, predicate):
    body = _sim.find_if(actions, predicate)
    return {"if": body} if body is not None else None


intended_action = _find_if_action(
    dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& (id(free_power_live_matches_intended) || id(free_power_live_self_partial));"),
)
neither_action = _find_if_action(
    dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& !id(free_power_live_matches_intended) && !id(free_power_live_self_partial);"),
)
final_action = _find_if_action(
    dispatch_actions, lambda c: "!id(free_power_restore_unexplained_drift) && !id(free_power_context_hold);" in c,
)
check("RESTORE: found the INTENDED write-sequence, NEITHER, and final-verify/comms-backoff `if:` nodes",
      None not in (intended_action, neither_action, final_action))
restore_tail = None
if None not in (intended_action, neither_action, final_action):
    restore_tail = _verify_harness([intended_action, neither_action, final_action], "free_power_test_verify_ok_scratch")
_reset_kind, RESET_LAMBDA = _single(dispatch_actions[0])
check("RESTORE: the dispatch's first action is its per-attempt reset lambda",
      _reset_kind == "lambda" and "id(free_power_context_hold) = false;" in RESET_LAMBDA)

RESTORE_WRITES = (232, 256, 268, 230)


def restore_state() -> dict:
    state = {
        "free_power_restore_unexplained_drift": False,
        "free_power_context_hold": False, "free_power_context_hold_reason": "",
        "free_power_operation_in_progress": True, "manual_write_in_progress": True,
        "free_power_tou_restore_failed": False, "free_power_tou_restore_confirmed": False,
        "free_power_restore_context_read_ok": False, "free_power_restore_live_reg244": -1,
        "free_power_write_failed": False, "free_power_op_terminal": False,
        "free_power_verify_230_ok": False, "free_power_verify_232_ok": False,
        "free_power_failures": 0, "free_power_comms_restore_attempts": 0,
        "free_power_restore_next_attempt_ms": 0, "free_power_verify_mismatch_count": 0,
        "free_power_snapshot_valid": True, "free_power_marker_state": MARKER_SENTINEL,
        "free_power_restore_successes": 0,
        "free_power_test_verify_ok_scratch": None,
        **_snapshot_globals(),
    }
    _sim.exec_lambda(RESET_LAMBDA, state, lenient=True)
    # Classifier output "live matches ECCO's intended state" (what the two
    # classification reads compute for a FREE_POWER bank - exhaustively
    # covered by test_free_power_tou_power_ownership_2026_09_23.py).
    state.update({
        "free_power_live_read_ok": True, "free_power_live_owned_matches": False,
        "free_power_live_matches_intended": True, "free_power_lease_context_reg244": LEASE_CONTEXT,
    })
    return state


def run_restore(write_outcomes: dict, readback: str = "ok", actions=None):
    reads = {(244, 12): "ok", (244, 1): "ok", (256, 6): readback, (230, 3): "ok", (256, 24): "ok"}
    overrides = {(244, 12): [LEASE_CONTEXT] + [900 + i for i in range(1, 12)], (244, 1): [LEASE_CONTEXT]}
    executed: list = []
    bank, state, attempted, _v, skipped = _sim.simulate(
        actions if actions is not None else restore_tail,
        {a: write_outcomes.get(a, "ok") for a in RESTORE_WRITES},
        reads, FREE_POWER, restore_state(), read_value_overrides=overrides, executed_scripts=executed,
    )
    return bank, state, attempted, executed


def _restore_obligation_preserved(state, attempted) -> list[str]:
    problems = []
    if state["free_power_snapshot_valid"] is not True:
        problems.append("snapshot_valid cleared")
    if state["free_power_marker_state"] != MARKER_SENTINEL:
        problems.append("marker changed")
    if (230, 3) in _reads(attempted) or (256, 24) in _reads(attempted):
        problems.append("final verify reached after a failed write")
    if state["free_power_test_verify_ok_scratch"]:
        problems.append("verify reported ok")
    if state["free_power_operation_in_progress"] or state["manual_write_in_progress"]:
        problems.append("ownership locks not released")
    if state["free_power_comms_restore_attempts"] != 1:
        problems.append("comms-backoff branch not taken")
    return problems


print("")
print("[D] RESTORE: a failed B3 (268-279) restore write stops B2 (reg230)")
if restore_tail is not None:
    for cause in FAILING_WRITE:
        bank, st, att, _ex = run_restore({268: cause})
        check(f"[B3 {cause}] reg230 is NOT written after the failed 268-279 restore write",
              _writes(att) == [232, 256, 268], f"{_writes(att)}")
        check(f"[B3 {cause}] register 230 keeps the Free Power grid-charge current (never restored out of order)",
              bank[230] == TARGET_AMPS, f"{bank[230]}")
        check(f"[B3 {cause}] obligation preserved: no final verify, no marker/snapshot change, comms backoff taken",
              not _restore_obligation_preserved(st, att), f"{_restore_obligation_preserved(st, att)}")

    bank, st, att, _ex = run_restore({268: "ack_not_applied"})
    check("[B3 acknowledged but not applied] the acknowledgement is the only per-write success signal (as in "
          "Force Restore), so 230 follows - and the final verify then refuses success",
          _writes(att) == [232, 256, 268, 230] and st["free_power_test_verify_ok_scratch"] is False
          and st["free_power_snapshot_valid"] is True and st["free_power_marker_state"] == MARKER_SENTINEL,
          f"{_writes(att)} ok={st['free_power_test_verify_ok_scratch']}")

    bank, st, att, ex = run_restore({})
    check("[success] restore still reaches B2: writes are exactly 232 -> 256-261 -> 268-279 -> 230",
          _writes(att) == [232, 256, 268, 230], f"{_writes(att)}")
    check("[success] reads: 244x12 context, 256x6 readback, 244x1 pre-floor recheck, then 230x3 + 256x24 final verify",
          _reads(att) == [(244, 12), (256, 6), (244, 1), (230, 3), (256, 24)], f"{_reads(att)}")
    check("[success] every owned register returns to its exact original", all(bank[a] == ORIGINAL[a] for a in OWNED))
    check("[success] the real final verify computes ok=true (the only place the marker may be cleared)",
          st["free_power_test_verify_ok_scratch"] is True)

# ---------------------------------------------------------------------------
print("")
print("[E] RESTORE: exhaustive fault sweep + marker-clear reachability")
# ---------------------------------------------------------------------------
if restore_tail is not None:
    n = 0
    bad_230, bad_ok = [], []
    for outs in itertools.product(_sim.WRITE_OUTCOMES, repeat=4):
        for rb in _sim.READ_OUTCOMES:
            wo = dict(zip(RESTORE_WRITES, outs))
            bank, st, att, _ex = run_restore(wo, readback=rb)
            n += 1
            if 230 in _writes(att) and wo[268] not in ACKED_WRITE:
                bad_230.append((wo, rb))
            if st["free_power_test_verify_ok_scratch"] and not all(bank[a] == ORIGINAL[a] for a in OWNED):
                bad_ok.append((wo, rb))
    check(f"all {n} combinations executed", n == 8 ** 4 * 6)
    check("reg230 is written ONLY when the 268-279 restore write reached a positive terminal acknowledgement",
          not bad_230, f"{len(bad_230)} bad, first: {bad_230[:1]}")
    check("the final verify (the only path to Phase C/D marker clear) never reports ok unless every owned "
          "register genuinely equals its original", not bad_ok, f"{bad_ok[:1]}")

dispatch_text = _sim.script_body(fw_text, "restore_free_power_snapshot_dispatch")
clear_sites = [m.start() for m in re.finditer(r"id\(free_power_marker_state\) = ecco_durable::MARKER_CLEAR;", dispatch_text)]
verify_handler = None
if final_action is not None:
    for action in final_action["if"]["then"]:
        kind, body = _single(action)
        if kind == READ and body.get("start_address") == 256 and body.get("count") == 24:
            verify_handler = body["on_response"]["then"][0]["lambda"]
check("RESTORE: MARKER_CLEAR (and snapshot_valid=false) is assigned in exactly one place in the dispatch - "
      "inside the final 256x24 verify handler's `if (ok)` block, reached only on !write_failed",
      len(clear_sites) == 1 and verify_handler is not None
      and "id(free_power_marker_state) = ecco_durable::MARKER_CLEAR;" in verify_handler
      and verify_handler.index("if (ok) {") < verify_handler.index("MARKER_CLEAR;")
      and dispatch_text.count("id(free_power_snapshot_valid) = false;") == 1
      and "id(free_power_snapshot_valid) = false;" in verify_handler,
      f"clear sites={len(clear_sites)}")
check("RESTORE: the final-verify branch is gated on !write_failed (so a failed B3 can never reach MARKER_CLEAR)",
      final_action is not None and _cond_text(final_action["if"]).startswith("return !id(free_power_write_failed) &&"))

# ---------------------------------------------------------------------------
print("")
print("[F] Force Restore parity: 230 gated on the 268-279 write, in both restore paths")
# ---------------------------------------------------------------------------
def _write_gates(actions):
    return {addr: gates for _i, addr, gates in _sim.writes_in(_sim.flatten(actions))}


ordinary = _write_gates(dispatch_actions)
force = _write_gates(SCRIPTS["free_power_recovery_force_restore_dispatch"]["then"])
check("Force Restore (unchanged): 230's gates are exactly 268-279's gates plus one nested !write_failed re-check",
      force.get(230) == force.get(268, ()) + ((FORCE_GATE_NO_WRITE_FAILED, "then"),), f"{force}")
check("ordinary restore: 230's gates are now exactly 268-279's gates plus one nested !write_failed re-check "
      "(the same shape as Force Restore)",
      ordinary.get(230) == ordinary.get(268, ()) + ((GATE_NO_WRITE_FAILED, "then"),),
      f"268={ordinary.get(268)} 230={ordinary.get(230)}")
check("ordinary restore still writes exactly 232, 256, 268, 230 (write surface unchanged)",
      [a for _i, a, _g in _sim.writes_in(_sim.flatten(dispatch_actions))] == [232, 256, 268, 230])
start_writes = [a for _i, a, _g in _sim.writes_in(_sim.flatten(start_actions))]
check("START still writes exactly 232, 230, 268, 256 (write surface unchanged)", start_writes == [232, 230, 268, 256],
      f"{start_writes}")

# ---------------------------------------------------------------------------
print("")
print("[G] Mutation: re-introducing an unconditional downstream write must be detected")
# ---------------------------------------------------------------------------
if start_tail is not None:
    for addr in (230, 268):
        gate = _find_gate_holding_write(start_tail, GATE_NO_WRITE_FAILED, addr)
        check(f"START: the {addr} write sits directly inside its own !write_failed gate", gate is not None)
    mutants = {
        "B2 unconditional": _unwrap_gate_holding_write(start_tail, GATE_NO_WRITE_FAILED, 230),
        "B3 unconditional": _unwrap_gate_holding_write(start_tail, GATE_NO_WRITE_FAILED, 268),
    }
    mutants["B2+B3 unconditional (pre-fix layout)"] = _unwrap_gate_holding_write(
        mutants["B2 unconditional"], GATE_NO_WRITE_FAILED, 268)
    for name, mutant in mutants.items():
        leaked = []
        for addr in (232, 230):
            _b, _s, att, _e = run_start({addr: "error"}, actions=mutant)
            later = [a for a in _writes(att) if START_WRITES.index(a) > START_WRITES.index(addr)]
            if later:
                leaked.append((addr, later))
        check(f"mutant [{name}] is detected: a failed earlier START write is followed by a later write", bool(leaked),
              f"{leaked}")
        _b, _s, att, _e = run_start({}, actions=mutant)
        check(f"mutant [{name}] still has the unchanged happy path (so only the failure invariant catches it)",
              _writes(att) == [232, 230, 268, 256])

if restore_tail is not None:
    gate = _find_gate_holding_write(restore_tail, GATE_NO_WRITE_FAILED, 230)
    check("RESTORE: the 230 write sits directly inside its own !write_failed gate", gate is not None)
    mutant = _unwrap_gate_holding_write(restore_tail, GATE_NO_WRITE_FAILED, 230)
    _b, _s, att, _e = run_restore({268: "error"}, actions=mutant)
    check("mutant [B3 -> B2 dependency removed] is detected: 230 is written after a failed 268-279 write",
          230 in _writes(att), f"{_writes(att)}")
    _b, _s, att, _e = run_restore({}, actions=mutant)
    check("mutant [B3 -> B2 dependency removed] still has the unchanged happy path",
          _writes(att) == [232, 256, 268, 230])

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Free Power write-sequencing hardening checks passed.")
