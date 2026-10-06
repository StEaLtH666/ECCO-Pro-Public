#!/usr/bin/env python3
"""Offline structural/behavioural tests for the 2026-09-23 Free Power TOU
Power (registers 256-261) ownership promotion (branch
`feature/free-power-tou-power-ownership`).

Background: registers 256-261 (TOU Power) were deliberately WITNESSED ONLY
by Free Power as of the 2026-09-22 hardening pass (see
registry/tests/test_free_power_hardening_2026_09_22.py section [4], now
superseded) - read and logged, never written or gated on, specifically so a
legitimate third-party TOU Power change during an override would not cause
a false RESTORE VERIFY FAILED. A subsequent post-reboot live
characterisation (CURRENT_STATE.md "Post-reboot inverter characterization")
proved TOU Power is actually the inverter's native battery charge/discharge
power CEILING in both Zero Export and Allow Export Load Limit modes, not a
cosmetic display field - so witness-only meant Free Power's requested
override power could be silently capped by whatever TOU Power ceiling
happened to be active in the current slot. This pass promotes 256-261 to
full Free Power durable transaction ownership: overlaid on all six slots at
activation (so a lease surviving a TOU slot boundary keeps the same
ceiling), exactly restored afterward, and fully participating in activation
verification, restore verification, and the reboot-survivable recovery
classifier - the same treatment every other owned register already gets.

No I/O, no hardware, no ESPHome/C++ toolchain. Most checks are
text/structure checks against the real firmware source, the durable-snapshot
header, and the registry/transaction_state_machine.py reference model, in
the same style as registry/tests/test_free_power_hardening_2026_09_22.py and
registry/tests/test_write_surface_invariants.py. The write-ORDER and
ceiling/floor-invariant checks ([3/4/11], [6/9/12], [8], [20]) instead parse
the firmware YAML into its real ESPHome action tree and, in [20], execute
that tree's writes/gates/handlers under exhaustive fault injection. These
prove the source says what it should, not that the compiled firmware behaves
this way on hardware.
"""

from __future__ import annotations

import copy
import itertools
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"

sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import transaction_state_machine as tsm  # noqa: E402
from analyze_write_surface import DEFAULT_FIRMWARE, analyze  # noqa: E402
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


for p in (FIRMWARE_PATH, HEADER_PATH):
    if not p.is_file():
        print(f"  FAIL  required file not found: {p}")
        sys.exit(1)

fw = FIRMWARE_PATH.read_text(encoding="utf-8")
header = HEADER_PATH.read_text(encoding="utf-8")


def script_body(script_id: str) -> str:
    """Extract one `- id: <script_id>` script's body - see the identical
    helper in the sibling hardening test files."""
    marker = f"\n  - id: {script_id}\n"
    start = fw.index(marker)
    rest = fw[start + 1 :]
    m = re.search(r"\n  - id: (?!" + re.escape(script_id) + r"\b)\w+\n|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


start_body = script_body("start_free_power_override")
dispatch_body = script_body("restore_free_power_snapshot_dispatch")

write_surface_result = analyze(DEFAULT_FIRMWARE)
write_paths = {p.name: p for p in write_surface_result["paths"] if p.kind == "script"}


# ---------------------------------------------------------------------------
# Structural extraction + restricted lambda interpreter: see
# registry/tests/_free_power_action_sim.py (factored out there 2026-09-24,
# independent-review fix round R2, so registry/tests/test_free_power_reg244_context_v4.py
# can reuse the SAME proven machinery for the register-244 context-gate
# behavioural tests, and so this file's own exhaustive ceiling/floor sweep
# can walk THROUGH the real register-244 context gates PR-A added instead
# of stripping them out before simulation - the R2 finding).
# ---------------------------------------------------------------------------
_, SCRIPTS = _sim.load_scripts(FIRMWARE_PATH)
WRITE = _sim.WRITE
READ = _sim.READ
_single = _sim._single
flatten = _sim.flatten
find_if = _sim.find_if
UnsupportedLambda = _sim.UnsupportedLambda

# SG-01 Phase 2: the activation sequence now contains the B2/B3/B4 START
# journal commits; they are EXECUTED (never skipped) against this real
# durable store - see _free_power_action_sim.simulate(journal_sim=...). Every
# journal commit succeeds here; journal-commit failure is swept in
# registry/tests/test_sg01_journal_phase1_2.py.
JOURNAL_SIM = _ds.Sim(_ds.load_firmware(FIRMWARE_PATH))


def _norm(code: str) -> str:
    return " ".join(str(code).split())


def _cond_text(if_body: dict) -> str:
    cond = if_body.get("condition")
    if isinstance(cond, dict) and "lambda" in cond:
        return _norm(cond["lambda"])
    return _norm(repr(cond))


def _single(action: dict) -> tuple[str, object]:
    if not isinstance(action, dict) or len(action) != 1:
        raise AssertionError(f"not a single-key ESPHome action: {action!r}")
    return next(iter(action.items()))


def flatten(actions, gates=()):
    """Document-order list of (kind, gates, body). `gates` is the tuple of
    (normalised condition lambda, 'then'|'else') of every enclosing `if:`."""
    out = []
    for action in actions or []:
        kind, body = _single(action)
        out.append((kind, gates, body))
        if kind == "if":
            cond = _cond_text(body)
            out.extend(flatten(body.get("then"), gates + ((cond, "then"),)))
            out.extend(flatten(body.get("else"), gates + ((cond, "else"),)))
    return out


def find_if(actions, predicate):
    """First `if:` body (depth-first, document order) whose condition text
    satisfies `predicate`."""
    for action in actions or []:
        kind, body = _single(action)
        if kind == "if":
            if predicate(_cond_text(body)):
                return body
            for branch in ("then", "else"):
                hit = find_if(body.get(branch), predicate)
                if hit is not None:
                    return hit
    return None


def writes_in(flat):
    return [(i, body["start_address"], gates) for i, (kind, gates, body) in enumerate(flat) if kind == WRITE]


GATE_NO_WRITE_FAILED = "return !id(free_power_write_failed);"
GATE_NO_TOU_RESTORE_FAILED = "return !id(free_power_tou_restore_failed);"
# The two positive-readback safety gates (2026-09-23 final hardening).
GATE_OVERLAY = "return !id(free_power_write_failed) && id(free_power_pre_power_overlay_confirmed);"
GATE_RESTORE_PROTECTED = "return !id(free_power_tou_restore_failed) && id(free_power_tou_restore_confirmed);"
# 2026-09-24 (PR-A, independent-review fix round R2): the pre-write AND
# pre-floor register-244 context gates share this EXACT condition text (see
# restore_free_power_snapshot_dispatch) - both check `!free_power_write_failed`
# among other things, which now ALSO independently blocks 268-279/230 on
# every readback outcome that would have failed GATE_RESTORE_PROTECTED's own
# tou_restore_confirmed check (a mismatch/failure always sets write_failed
# too - see the readback handler). This is genuine ADDED redundant
# protection, not a regression - but it means the pre-existing "remove
# GATE_RESTORE_PROTECTED alone" sensitivity mutant below needs to ALSO strip
# this gate to reproduce the true no-protection-at-all baseline; stripping
# it is harmless for this file's own combinations either way, since context
# is always forced to match here (see base_state()).
GATE_PREWRITE_OR_PREFLOOR_CONTEXT = (
    "return !id(free_power_write_failed) && id(free_power_restore_context_read_ok) && "
    "id(free_power_lease_context_reg244) >= 0 && "
    "id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);"
)


# ---------------------------------------------------------------------------
# The restricted lambda interpreter (exec_lambda/eval_condition/
# eval_write_values/UnsupportedLambda) now lives in
# registry/tests/_free_power_action_sim.py - imported as `_sim` above -
# so it can be shared with registry/tests/test_free_power_reg244_context_v4.py
# rather than duplicated (2026-09-24, independent-review fix round R2).
# ---------------------------------------------------------------------------
exec_lambda = _sim.exec_lambda
eval_condition = _sim.eval_condition
eval_write_values = _sim.eval_write_values
_cond_text = _sim._cond_text
# ---------------------------------------------------------------------------
# Fault-injection simulator over a CONCRETE register bank. Executes a real
# extracted action list: writes (their real `values:` lambdas evaluated
# against the snapshot/target globals, with an injected outcome each),
# reads (returning the bank's actual contents, with an injected outcome),
# every real on_* handler lambda, every real bounded-wait timeout lambda and
# every real `if:` gate. Nothing about what a write writes, or what a
# readback accepts, is supplied by the test - both come from the firmware.
#
# Scenario (the final audit's): original TOU Power ~1000 W per slot (varied
# per slot), Free Power target 8000 W, original SOC floors 10-50 %, and
# 274-279 raw words with varied mode / undecoded high bits so a readback
# that ignored preserved bits would be caught.
# ---------------------------------------------------------------------------
TARGET_POWER = 8000
ORIGINAL = {
    230: 120, 232: 0x0010,
    **dict(zip(range(256, 262), (1000, 1200, 800, 1000, 100, 3000))),
    **{a: 0 for a in range(262, 268)},
    **dict(zip(range(268, 274), (20, 20, 30, 10, 20, 50))),
    **dict(zip(range(274, 280), (0x0000, 0x0004, 0x0008, 0x0010, 0x0021, 0x0106))),
}
TARGET_AMPS = 50
INTENDED_FLAGS = {a: (ORIGINAL[a] & 0xFFFC) | 0x0001 for a in range(274, 280)}
FREE_POWER = {
    **ORIGINAL, 230: TARGET_AMPS, 232: ORIGINAL[232] | 0x0001,
    **{a: TARGET_POWER for a in range(256, 262)},
    **{a: 100 for a in range(268, 274)},
    **INTENDED_FLAGS,
}


CONTEXT_LEASE = 1  # arbitrary fixed "Essentials" - only its self-consistency matters here


def base_state() -> dict:
    state = {
        "free_power_write_failed": False,
        "free_power_op_terminal": False,
        "free_power_operation_in_progress": True,
        "free_power_tou_restore_failed": False,
        "free_power_pre_power_overlay_confirmed": False,
        "free_power_tou_restore_confirmed": False,
        "free_power_target_tou_power": TARGET_POWER,
        "free_power_target_reg230": TARGET_AMPS,
        # 2026-09-24 (PR-A): this file's exhaustive ceiling/floor sweep is
        # not about the register-244 context gates (see
        # registry/tests/test_free_power_reg244_context_v4.py Section D/E
        # for that) - seed a self-consistent, always-matching lease context
        # so the two real gates PR-A added are genuinely EXECUTED (not
        # stripped) but always take their "context matches" branch,
        # exercising the exact same owned-register write sequence this
        # sweep covered before PR-A existed. See `simulate()` below for how
        # the two register-244 reads are pinned to always return this same
        # value.
        "free_power_context_hold": False,
        "free_power_restore_context_read_ok": False,
        "free_power_restore_live_reg244": -1,
        "free_power_lease_context_reg244": CONTEXT_LEASE,
    }
    for addr in (230, 232, *range(256, 262), *range(268, 280)):
        state[f"free_power_snapshot_reg{addr}"] = ORIGINAL[addr]
    # SG-01: the journal RAM mirror as START's (unsimulated) B1 commit leaves it.
    state.update(_jm.ram_after_b1(0x0123456789ABCDEF))
    return state


WRITE_OUTCOMES = _sim.WRITE_OUTCOMES
READ_OUTCOMES = _sim.READ_OUTCOMES


def invariant_violation(bank: dict) -> str | None:
    """THE ceiling/floor invariant: no TOU Power slot may be above its
    original value unless all six SOC floors are 100."""
    raised = [a for a in range(256, 262) if bank[a] > ORIGINAL[a]]
    floors = [bank[a] for a in range(268, 274)]
    if raised and any(f != 100 for f in floors):
        return f"ceilings raised at {raised} while SOC floors = {floors}"
    return None


# 2026-09-24 (PR-A, independent-review fix round R2): both register-244
# context-gate reads restore_free_power_snapshot_dispatch performs are
# pinned to always succeed and always return CONTEXT_LEASE (base_state()'s
# free_power_lease_context_reg244) - i.e. the gates are executed FOR REAL
# (not stripped - see the module-level comment above SCRIPTS) but always
# take their "context matches" branch, so this file's exhaustive sweep
# keeps exercising exactly the owned-register write sequence it covered
# before PR-A existed. start_free_power_override has no register-244 read
# at all (Part 5 deliberately omitted a second one there), so this is a
# no-op for activation_seq.
_CONTEXT_READ_OVERRIDES = {
    (244, 12): [CONTEXT_LEASE] * 12,
    (244, 1): [CONTEXT_LEASE],
}
_CONTEXT_READ_OUTCOMES_OK = {(244, 12): "ok", (244, 1): "ok"}


def simulate(actions, write_outcomes: dict, read_outcomes: dict, start_bank: dict):
    """Thin, shape-preserving wrapper around
    _free_power_action_sim.simulate for this file's own exhaustive
    ceiling/floor sweep - returns (bank, attempted[(kind,addr,bank)],
    violation), this file's ORIGINAL 3-tuple shape, so none of its many
    existing call sites/unpacking below needed to change. `read_outcomes`
    is keyed by (address, count) - see ACTIVATION_READ/RESTORE_READ below."""
    JOURNAL_SIM.reset_durable()
    bank, _state, attempted, violation, _skipped = _sim.simulate(
        actions,
        write_outcomes,
        {**read_outcomes, **_CONTEXT_READ_OUTCOMES_OK},
        start_bank,
        base_state(),
        read_value_overrides=_CONTEXT_READ_OVERRIDES,
        invariant_fn=invariant_violation,
        journal_sim=JOURNAL_SIM,
    )
    attempted3 = [(kind, addr, b) for kind, addr, _count, b in attempted]
    return bank, attempted3, violation


start_actions = SCRIPTS["start_free_power_override"]["then"]
dispatch_actions = SCRIPTS["restore_free_power_snapshot_dispatch"]["then"]
start_flat = flatten(start_actions)
dispatch_flat = flatten(dispatch_actions)

# ===========================================================================
# 1/2. Durable schema: six-slot TOU Power snapshot already exists (reg256..
#      reg261, added in an earlier pass); this pass adds the INTENDED value
#      needed to classify recovery, under a NEW versioned tag (schema rule
#      1 - never reuse a tag across an incompatible layout change).
# ===========================================================================
print("[1/2] Durable snapshot already carries the original 256-261; this pass adds the INTENDED value under a new tag")
check(
    "FreePowerSnapshotData already carries the six ORIGINAL TOU Power registers (pre-existing)",
    all(f"uint16_t reg{addr};" in header for addr in range(256, 262)),
)
check(
    "FreePowerSnapshotData grew reg_tou_power_intended - the one piece of INTENDED TOU Power state "
    "not deterministically derivable from the original snapshot fields alone",
    "uint16_t reg_tou_power_intended;" in header,
)
check(
    # 2026-09-24 (PR-A): the alias has since moved on to V4 (a later, later
    # pass - see test_free_power_reg244_context_v4.py); this check now pins
    # only that THIS pass's own V3 tag string was actually minted, not that
    # it is still the current alias.
    "the struct change used a NEW versioned tag (schema rule 1), not a same-tag layout change",
    'FREE_POWER_DATA_TAG_V3 = "ecco_free_power_snapshot_data_v3"' in header,
)
check(
    "the retired v1 AND v2 tag constants are kept, unused, as documented historical records - "
    "never repurposed, never referenced by the running firmware",
    'FREE_POWER_DATA_TAG_V1 = "ecco_free_power_snapshot_data_v1"' in header
    and 'FREE_POWER_DATA_TAG_V2 = "ecco_free_power_snapshot_data_v2"' in header
    and fw.count("ecco_durable::FREE_POWER_DATA_TAG_V1") == 0
    and fw.count("ecco_durable::FREE_POWER_DATA_TAG_V2") == 0,
)
check(
    "on_boot restores the persisted intended TOU Power target into the RAM working copy for a "
    "RESTORE_REQUIRED marker",
    "id(free_power_target_tou_power) = data.reg_tou_power_intended;" in fw,
)
check(
    "every site that rebuilds a FreePowerSnapshotData record from a zero-initialised struct also sets "
    "reg_tou_power_intended (start, activation-verify re-commit, END-request re-commit) - otherwise it "
    "would silently zero the field on that write, exactly the same class of bug reg230_intended's own "
    "corrective pass fixed",
    fw.count("data.reg_tou_power_intended = ") >= 3,
    f"found {fw.count('data.reg_tou_power_intended = ')} occurrences",
)

# ===========================================================================
# 3/4/11. Free Power overlays ALL SIX TOU Power registers with the requested/
#         effective wattage at activation - not just whichever slot is
#         currently active - so a lease surviving a TOU slot boundary keeps
#         the same ceiling in every slot.
# ===========================================================================
print("")
print("[3/4/11] Activation overlays all six TOU Power registers with the requested/effective wattage")
check(
    "the requested/effective wattage is computed once as tou_power_w",
    "uint16_t tou_power_w = (uint16_t) lroundf(watts);" in start_body,
)
check(
    "...and persisted as the durable INTENDED TOU Power target before any override write",
    "data.reg_tou_power_intended = tou_power_w;" in start_body,
)
tou_write_m = re.search(
    r"start_address: 256\s*\n\s*values: !lambda \|-\s*\n\s*uint16_t p = id\(free_power_target_tou_power\);\s*\n\s*"
    r"return std::vector<uint16_t>\{p, p, p, p, p, p\};",
    start_body,
)
check(
    "start_free_power_override writes registers 256-261 as ONE call, all six values equal to the "
    "target wattage (not just the currently-active slot) - this is what keeps the ceiling correct "
    "across a TOU slot boundary crossing mid-lease",
    tou_write_m is not None,
)
# Structural (parsed action tree, not text offsets): the ceiling/floor
# invariant's ordering half. The previous regex-over-text version of this
# check was vacuous - it matched the snapshot READS and still passed with the
# 256-261 write deleted or moved.
start_writes = writes_in(start_flat)
start_write_addrs = [addr for _, addr, _ in start_writes]
check(
    "start_free_power_override issues exactly one write each to 232, 230, 268 and 256 "
    "(parsed Modbus WRITE actions, reads excluded)",
    sorted(start_write_addrs) == [230, 232, 256, 268],
    f"writes in document order: {start_write_addrs}",
)
if sorted(start_write_addrs) == [230, 232, 256, 268]:
    idx = {addr: i for i, addr, _ in start_writes}
    gates_256 = next(g for _, a, g in start_writes if a == 256)
    check(
        "activation write ORDER is 232 -> 230 -> 268-279 -> 256-261: the TOU Power ceiling write is the "
        "LAST write, strictly after the 268-279 SOC-floor/source write",
        idx[232] < idx[230] < idx[268] < idx[256],
        f"document order: {start_write_addrs}",
    )
    check(
        "the 256-261 activation write sits in the THEN branch of the overlay gate "
        "`!free_power_write_failed && free_power_pre_power_overlay_confirmed` - never attempted after an "
        "earlier failure, and never without the positive 268-279 readback confirmation",
        (GATE_OVERLAY, "then") in gates_256,
        f"enclosing gates: {gates_256}",
    )
    gates_268 = next(g for _, a, g in start_writes if a == 268)
    check(
        "...and that gate is specific to 256-261: the 268-279 write itself is not inside it (the sibling "
        "writes keep their existing sequencing)",
        (GATE_OVERLAY, "then") not in gates_268,
        f"268 gates: {gates_268}",
    )
    # The activation safety boundary: a fresh READ of 268-279 sits strictly
    # between the 268-279 WRITE and the 256-261 WRITE, and is the ONLY thing
    # that can set the overlay's confirmation flag.
    boundary_reads = [
        (i, gates, body) for i, (kind, gates, body) in enumerate(start_flat)
        if kind == READ and body["start_address"] == 268 and body.get("count") == 12
    ]
    check(
        "activation: exactly one fresh READ of 268-279 (count 12) exists, positioned AFTER the 268-279 WRITE "
        "and BEFORE the 256-261 WRITE",
        len(boundary_reads) == 1 and idx[268] < boundary_reads[0][0] < idx[256],
        f"{[(i, b['start_address']) for i, _, b in boundary_reads]} vs writes {idx}",
    )
    if len(boundary_reads) == 1:
        check(
            "...skipped when an earlier write already failed (it sits in the THEN branch of "
            "`if: !free_power_write_failed`)",
            (GATE_NO_WRITE_FAILED, "then") in boundary_reads[0][1],
            f"{boundary_reads[0][1]}",
        )
        setters = [
            body for kind, _, body in start_flat
            if kind == "lambda" and any(v != "false" for v in re.findall(r"id\(free_power_pre_power_overlay_confirmed\)\s*=\s*(\w+)", body))
        ]
        read_setters = [
            h["lambda"] for h in boundary_reads[0][2]["on_response"]["then"]
            if re.search(r"id\(free_power_pre_power_overlay_confirmed\)\s*=\s*confirmed;", h["lambda"])
        ]
        check(
            "free_power_pre_power_overlay_confirmed is only ever set to a non-false value by that readback's "
            "own on_response (from its value comparison) - no step lambda, write handler or terminal flag "
            "can set it",
            setters == [] and len(read_setters) == 1,
            f"step-lambda setters: {len(setters)}; readback setters: {len(read_setters)}",
        )
    verify_reads = [
        body["start_address"]
        for i, (kind, _, body) in enumerate(start_flat)
        if kind == READ and i > idx[256]
    ]
    check(
        "activation verification (fresh reads of 230-232 AND 256-279) happens only AFTER the final "
        "ownership write",
        230 in verify_reads and 256 in verify_reads,
        f"reads after the 256 write: {verify_reads}",
    )
check(
    "write_surface: start_free_power_override's actual written-register set now includes 256-261",
    "start_free_power_override" in write_paths
    and set(range(256, 262)) <= write_paths["start_free_power_override"].written_addresses,
    sorted(write_paths.get("start_free_power_override").written_addresses) if "start_free_power_override" in write_paths else "script not found",
)

# ===========================================================================
# 5. Activation verification treats 256-261 as OWNED - a mismatch now fails
#    activation, not merely logged as a diagnostic.
# ===========================================================================
print("")
print("[5] Activation verification treats registers 256-261 as OWNED (gates success)")
activation_ok_m = re.search(r"bool ok = [^\n]+;", start_body)
check("found start_free_power_override's activation verify `ok` gate", activation_ok_m is not None)
if activation_ok_m:
    check(
        "powers_ok (the 256-261 comparison) IS part of the activation `ok` gate",
        "powers_ok" in activation_ok_m.group(0),
        activation_ok_m.group(0),
    )
check(
    "the expected values compared against are the INTENDED target (free_power_target_tou_power), "
    "not merely 'unchanged from before'",
    bool(re.search(
        r"uint16_t expected_powers\[6\] = \{\s*\n\s*id\(free_power_target_tou_power\), id\(free_power_target_tou_power\), id\(free_power_target_tou_power\),\s*\n\s*"
        r"id\(free_power_target_tou_power\), id\(free_power_target_tou_power\), id\(free_power_target_tou_power\)\s*\n\s*\};",
        start_body,
    )),
)
check(
    "a 256-261 mismatch during activation logs at ERROR (fails the transaction), not WARN "
    "(diagnostic-only, the retired 2026-09-22 behaviour)",
    'ESP_LOGE("free_power", "Activation verify FAILED: registers 256-261' in start_body,
)

# ===========================================================================
# 6/9/12. Exact restore of the original six TOU Power values - no
#         approximation, no default - and it is folded into the SAME
#         partial-apply / reboot recovery model every other owned register
#         already uses (the fail-closed drift classifier), not a bespoke
#         mechanism only for 256-261.
# ===========================================================================
print("")
print("[6/9/12] Restore writes back the EXACT original six TOU Power values, inside the existing recovery model")
restore_write_m = re.search(
    r"start_address: 256\s*\n\s*values: !lambda \|-\s*\n\s*return std::vector<uint16_t>\{\s*\n\s*"
    r"id\(free_power_snapshot_reg256\), id\(free_power_snapshot_reg257\), id\(free_power_snapshot_reg258\),\s*\n\s*"
    r"id\(free_power_snapshot_reg259\), id\(free_power_snapshot_reg260\), id\(free_power_snapshot_reg261\)\s*\n\s*\};",
    dispatch_body,
)
check(
    "restore_free_power_snapshot_dispatch writes back the exact ORIGINAL snapshotted 256-261 values "
    "(no defaults, no approximation) as one call",
    restore_write_m is not None,
)
# Structural: the ceiling/floor invariant's restore half.
dispatch_writes = writes_in(dispatch_flat)
dispatch_write_addrs = [addr for _, addr, _ in dispatch_writes]
check(
    "restore_free_power_snapshot_dispatch issues exactly one write each to 232, 256, 268 and 230",
    sorted(dispatch_write_addrs) == [230, 232, 256, 268],
    f"writes in document order: {dispatch_write_addrs}",
)
if sorted(dispatch_write_addrs) == [230, 232, 256, 268]:
    ridx = {addr: i for i, addr, _ in dispatch_writes}
    rgates = {addr: g for _, addr, g in dispatch_writes}
    check(
        "restore write ORDER is 232 -> 256-261 -> 268-279 -> 230: the exact-original TOU Power ceilings "
        "are restored BEFORE the writes that release the protective SOC=100 envelope (268-279) and the "
        "grid-charge current (230)",
        ridx[232] < ridx[256] < ridx[268] < ridx[230],
        f"document order: {dispatch_write_addrs}",
    )
    check(
        "the 268-279 and 230 restore writes are both inside the THEN branch of the protected-restore gate "
        "`!free_power_tou_restore_failed && free_power_tou_restore_confirmed`",
        all((GATE_RESTORE_PROTECTED, "then") in rgates[a] for a in (268, 230)),
        f"268 gates: {rgates[268]}; 230 gates: {rgates[230]}",
    )
    check(
        "...while the 232 and 256-261 restore writes are NOT behind that gate (restoring the ceiling is "
        "always attempted; 232 does not touch the SOC floors)",
        all((GATE_RESTORE_PROTECTED, "then") not in rgates[a] for a in (232, 256)),
        f"232 gates: {rgates[232]}; 256 gates: {rgates[256]}",
    )
    # The restore safety boundary: a fresh READ of 256-261 (count 6 - the
    # pre-restore classifier read and the final verify read are count 24)
    # sits strictly between the 256-261 WRITE and the 268-279 WRITE.
    rboundary = [
        (i, gates, body) for i, (kind, gates, body) in enumerate(dispatch_flat)
        if kind == READ and body["start_address"] == 256 and body.get("count") == 6
    ]
    check(
        "restore: exactly one fresh READ of 256-261 (count 6) exists, positioned AFTER the 256-261 WRITE and "
        "BEFORE the 268-279 WRITE",
        len(rboundary) == 1 and ridx[256] < rboundary[0][0] < ridx[268],
        f"{[i for i, _, _ in rboundary]} vs writes {ridx}",
    )
    if len(rboundary) == 1:
        check(
            "...skipped when the 256-261 write already failed (THEN branch of "
            "`if: !free_power_tou_restore_failed`)",
            (GATE_NO_TOU_RESTORE_FAILED, "then") in rboundary[0][1],
            f"{rboundary[0][1]}",
        )
        rsetters = [
            body for kind, _, body in dispatch_flat
            if kind == "lambda" and any(v != "false" for v in re.findall(r"id\(free_power_tou_restore_confirmed\)\s*=\s*(\w+)", body))
        ]
        rread_setters = [
            h["lambda"] for h in rboundary[0][2]["on_response"]["then"]
            if re.search(r"id\(free_power_tou_restore_confirmed\)\s*=\s*confirmed;", h["lambda"])
        ]
        check(
            "free_power_tou_restore_confirmed is only ever set to a non-false value by that readback's own "
            "on_response (from its value comparison)",
            rsetters == [] and len(rread_setters) == 1,
            f"step-lambda setters: {len(rsetters)}; readback setters: {len(rread_setters)}",
        )
    final_verify = [
        i for i, (kind, _, body) in enumerate(dispatch_flat)
        if kind == READ and body["start_address"] == 256 and body.get("count") == 24 and i > ridx[230]
    ]
    check(
        "restore: the final full verification read (256-279, count 24) still follows the last restore write - "
        "the intermediate readback does not replace it",
        len(final_verify) == 1,
        f"{final_verify}",
    )
    all_gates_256 = rgates[256]
    check(
        "all four restore writes remain inside the existing classifier write gate (live matches ECCO's "
        "INTENDED state and not already the original) - the new gate is nested inside it, not a bypass",
        all(
            any("id(free_power_live_matches_intended)" in c and b == "then" for c, b in rgates[a])
            for a in (232, 256, 268, 230)
        ),
    )
    # The flag the gate reads is reset immediately before the 256-261 write.
    reset_before_256 = any(
        kind == "lambda" and re.search(r"id\(free_power_tou_restore_failed\)\s*=\s*false", body)
        for kind, _, body in dispatch_flat[ridx[256] - 1: ridx[256]]
    )
    check(
        "free_power_tou_restore_failed is reset to false in the step immediately preceding the 256-261 "
        "restore write (a fresh verdict per attempt)",
        reset_before_256,
    )
check(
    "restore_free_power_snapshot_dispatch's actual written-register set now includes 256-261",
    "restore_free_power_snapshot_dispatch" in write_paths
    and set(range(256, 262)) <= write_paths["restore_free_power_snapshot_dispatch"].written_addresses,
)
# Partial-apply / reboot recovery: 256-261 must participate in BOTH legs of
# the existing minimal recovery classifier (matches-original / matches-
# intended), not a third, separate mechanism - this is what makes a partial
# apply (crashed after writing 230/232/256-261 but before 268-279, or any
# other interleaving) correctly fall through to the SAME fail-closed
# "matches neither -> operator decision" branch every other partial owned-
# register write already uses.
check(
    "the pre-restore fresh read computes powers_matches_original (256-261 vs the ORIGINAL snapshot)",
    bool(re.search(
        r"uint16_t original_powers\[6\] = \{\s*\n\s*id\(free_power_snapshot_reg256\), id\(free_power_snapshot_reg257\), id\(free_power_snapshot_reg258\),\s*\n\s*"
        r"id\(free_power_snapshot_reg259\), id\(free_power_snapshot_reg260\), id\(free_power_snapshot_reg261\)\s*\n\s*\};\s*\n\s*"
        r"bool powers_matches_original = true;",
        dispatch_body,
    )),
)
check(
    "...and folds it into free_power_live_owned_matches (the 'already restored, skip write' gate) - "
    "256-261 is now REQUIRED to match, not merely witnessed",
    # SG-01 Phase 3: 268-279 is now its own whole-vector leg (b3_original), folded in the same expression.
    "bool owned_matches = id(free_power_live_230_ok) && id(free_power_live_232_ok) && powers_matches_original && b3_original;" in dispatch_body,
)
check(
    "the pre-restore fresh read ALSO computes powers_matches_intended (256-261 vs the INTENDED target)",
    bool(re.search(
        r"uint16_t intended_powers\[6\] = \{\s*\n\s*id\(free_power_target_tou_power\), id\(free_power_target_tou_power\), id\(free_power_target_tou_power\),\s*\n\s*"
        r"id\(free_power_target_tou_power\), id\(free_power_target_tou_power\), id\(free_power_target_tou_power\)\s*\n\s*\};\s*\n\s*"
        r"bool powers_matches_intended = true;",
        dispatch_body,
    )),
)
check(
    "...and folds it into free_power_live_matches_intended (the 'write is permitted' gate)",
    "bool intended_matches = id(free_power_live_230_ok_intended) && id(free_power_live_232_ok_intended) && powers_matches_intended && b3_intended;" in dispatch_body,
)
check(
    "consequently: a partial apply that leaves 256-261 written to the target but 268-279 still original "
    "(or vice versa) matches NEITHER leg (230/232/256-261 vs 268-279 disagree either way) and correctly "
    "falls through to the existing case-3 unexplained-drift/operator-decision lockout - no new mechanism "
    "was needed because 256-261 now participates in the SAME two-leg classifier as every other owned "
    "register (SG-01 Phase 4: unless the START journal proves an interrupted START - SELF_PARTIAL - and "
    "256-261 INTENDED over 268-279 ORIGINAL is never SELF_PARTIAL)",
    "id(free_power_restore_unexplained_drift) = true;" in dispatch_body,
)

# ===========================================================================
# 7. Restore verification treats 256-261 as OWNED - a mismatch now fails
#    restore verification, not merely logged.
# ===========================================================================
print("")
print("[7] Restore verification treats registers 256-261 as OWNED (gates completion)")
restore_ok_m = re.search(r"bool ok = [^\n]+;", dispatch_body)
check("found restore_free_power_snapshot_dispatch's verify `ok` gate", restore_ok_m is not None)
if restore_ok_m:
    check(
        "powers_restored_ok (the 256-261 comparison) IS part of the restore verify `ok` gate",
        "powers_restored_ok" in restore_ok_m.group(0),
        restore_ok_m.group(0),
    )
check(
    "a 256-261 mismatch after restore logs at ERROR (fails restore verification), not WARN",
    'ESP_LOGE("free_power", "Restore verify FAILED: registers 256-261' in dispatch_body,
)

# ===========================================================================
# 8. Partial-apply failure handling: the new 256-261 write step follows the
#    exact same bounded, completion-driven, fail-safe pattern as every other
#    write in these two scripts - a timeout/error still reaches a terminal
#    state and is picked up by the shared write_failed gate. Checked on the
#    parsed WRITE action itself, by EXECUTING its real handler lambdas and
#    the real bounded-wait timeout lambda that follows it.
# ===========================================================================
print("")
print("[8] The new 256-261 write steps use the same bounded, completion-driven failure handling as every other write")


def _fresh_flags(**overrides):
    flags = base_state()
    flags.update(overrides)
    return flags


for name, flat, extra_flag in (
    ("start_free_power_override", start_flat, None),
    ("restore_free_power_snapshot_dispatch", dispatch_flat, "free_power_tou_restore_failed"),
):
    hits = [i for i, (kind, _, body) in enumerate(flat) if kind == WRITE and body["start_address"] == 256]
    check(f"{name}: exactly one parsed 256-261 WRITE action (reads excluded)", len(hits) == 1, f"{hits}")
    if len(hits) != 1:
        continue
    i = hits[0]
    write_body = flat[i][2]
    for handler in ("on_error", "on_no_response", "on_not_sent"):
        flags = _fresh_flags()
        for handler_action in write_body[handler]["then"]:
            exec_lambda(_single(handler_action)[1], flags)
        expected = flags["free_power_write_failed"] and flags["free_power_op_terminal"]
        if extra_flag:
            expected = expected and flags[extra_flag]
        check(
            f"{name}: executing the 256-261 write's {handler} handler marks it terminal and sets "
            f"free_power_write_failed" + (f" AND {extra_flag}" if extra_flag else ""),
            expected,
            f"{flags}",
        )
    flags = _fresh_flags(free_power_tou_restore_failed=True)
    for handler_action in write_body["on_response"]["then"]:
        exec_lambda(_single(handler_action)[1], flags)
    check(
        f"{name}: the on_response handler only marks the step terminal - it never sets write_failed and "
        f"can never CLEAR a failure verdict (a late response cannot re-authorise later writes)",
        flags["free_power_op_terminal"] and not flags["free_power_write_failed"]
        and flags["free_power_tou_restore_failed"],
        f"{flags}",
    )
    check(
        f"{name}: the 256-261 write is immediately followed by a wait_until on the terminal flag (no fixed delay)",
        i + 2 < len(flat) and flat[i + 1][0] == "wait_until"
        and "free_power_op_terminal" in str(flat[i + 1][2]) and flat[i + 2][0] == "lambda",
    )
    if i + 2 < len(flat) and flat[i + 2][0] == "lambda":
        flags = _fresh_flags()  # op_terminal still false: the bounded wait expired
        exec_lambda(flat[i + 2][2], flags)
        expected = flags["free_power_write_failed"] and (flags[extra_flag] if extra_flag else True)
        check(
            f"{name}: executing the timeout lambda after that wait (terminal flag never set) sets "
            f"free_power_write_failed" + (f" AND {extra_flag}" if extra_flag else ""),
            expected,
            f"{flags}",
        )

# ===========================================================================
# 10. Reboot/recovery classification: live == original / live == intended /
#     neither (mixed/unexplained). Covered structurally by [6/9/12] above
#     (the classifier folds 256-261 into both legs); this section proves
#     the THIRD outcome (matches neither) is still reachable and still
#     durably locks out automatic writes, unchanged in mechanism.
# ===========================================================================
print("")
print("[10] The three-way reboot/recovery classification (original / intended / neither) still holds with 256-261 folded in")
write_gate_m = re.search(
    r"return !id\(free_power_write_failed\) && id\(free_power_live_read_ok\) && "
    r"!id\(free_power_live_owned_matches\) && \(id\(free_power_live_matches_intended\) \|\| id\(free_power_live_self_partial\)\);",
    dispatch_body,
)
drift_gate_m = re.search(
    r"return !id\(free_power_write_failed\) && id\(free_power_live_read_ok\) && "
    r"!id\(free_power_live_owned_matches\) && !id\(free_power_live_matches_intended\) && !id\(free_power_live_self_partial\);",
    dispatch_body,
)
check("case 2 (matches ECCO's own intended state, now including 256-261 - or, since SG-01 Phase 4, a journal-proven "
      "SELF_PARTIAL state) is the only case that may write", write_gate_m is not None)
check("case 3 (matches NEITHER original nor intended, now including 256-261) is a distinct non-writing branch", drift_gate_m is not None)
check(
    "case 3 durably requires an operator decision via the existing FreePowerRetryState lockout - no "
    "separate lockout mechanism was invented for TOU Power",
    bool(re.search(
        r"id\(free_power_restore_unexplained_drift\) = true;\s*\n\s*id\(free_power_failures\)\+\+;\s*\n\s*"
        r"ecco_durable::FreePowerRetryState retry\{\};\s*\n\s*retry\.operator_needed = 1;",
        dispatch_body,
    )),
)

# ===========================================================================
# 12/13/17. Absolutely no Free Power writes outside its now-slightly-larger
#           owned set - 250-255 (TOU slot times), 244/245/248/243/247
#           (Load/Export policy, export ceiling, TOU master enable, and
#           their neighbours) remain completely untouched.
# ===========================================================================
print("")
print("[12/13/17] Free Power never writes 250-255, 244/245/248/243/247 - write surface proves it structurally")
FORBIDDEN = {243, 244, 245, 247, 248} | set(range(250, 256))
for name in ("start_free_power_override", "restore_free_power_snapshot_dispatch"):
    actual = write_paths[name].written_addresses
    overlap = actual & FORBIDDEN
    check(
        f"{name}: writes NONE of {{243,244,245,247,248,250-255}}",
        not overlap,
        f"unexpectedly written: {sorted(overlap)}",
    )
check(
    "the reference model (ECCO_CONFLICT_DECLARATIONS) agrees: free_power_transaction's owned "
    "registers still exclude 244/245/248/243/247/250-255",
    not (tsm.ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][0] & FORBIDDEN),
    sorted(tsm.ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][0]),
)
check(
    "the reference model's free_power_transaction owned registers now include exactly 230, 232, "
    "256-261, 268-279 (256-261 added, nothing else changed)",
    tsm.ECCO_CONFLICT_DECLARATIONS["free_power_transaction"][0]
    == frozenset({230, 232}) | frozenset(range(256, 262)) | frozenset(range(268, 280)),
)
check(
    "register 245 (Export Limit / Dump to Grid) still has no write path anywhere in the firmware - "
    "Dump to Grid remains unimplemented and locked",
    not re.search(r"modbus_client\.write_multiple_registers:.{1,400}?start_address:\s*245\b", fw, re.S),
)
check(
    "the automatic optimiser TOU master enable (register 248) still has no write path anywhere in "
    "the firmware",
    not re.search(r"modbus_client\.write_multiple_registers:.{1,400}?start_address:\s*248\b", fw, re.S),
)

# ===========================================================================
# 15. The write-surface change is EXPLICIT and INTENTIONAL - pinned by the
#     repository's own write-surface invariant test, not merely an
#     incidental side effect this test suite alone happens to notice.
# ===========================================================================
print("")
print("[15] The write-surface change to 256-261 is explicit, pinned, and intentional (not an accident)")
invariants_text = (ROOT / "registry" / "tests" / "test_write_surface_invariants.py").read_text(encoding="utf-8")
check(
    "registry/tests/test_write_surface_invariants.py's shared-register check[9] still covers "
    "256-261 and 268-279 (as two separately-checked ranges since Manual Dump-to-Grid V1, "
    "2026-09-26, gave them different contention counts - see that file) - the repository's own "
    "pinned write-surface test was updated for this change, not left stale",
    "for addr in range(256, 262):" in invariants_text and "for addr in range(268, 280):" in invariants_text,
)
check(
    "the EXPECTED_WRITTEN_REGISTERS constant does not need to change - 256-261 (via TOU slot writers) "
    "was already part of the documented full write surface before this pass; only WHICH scripts write "
    "it grew, not the surface itself",
    "set(range(250, 262))" in invariants_text,
)

# ===========================================================================
# 16/18. Existing manual six-slot TOU controls and the scheduled Free Power
#        HA wrapper are not regressed - the six apply_manual_slotN scripts
#        and the HA-side scheduling package are untouched by this change.
# ===========================================================================
print("")
print("[16/18] Existing manual six-slot TOU controls and scheduled Free Power are not regressed")
for n in range(1, 7):
    name = f"apply_manual_slot{n}"
    check(
        f"{name}: still exists as its own independent write path (unmodified by this change)",
        name in write_paths,
    )
schedule_pkg = ROOT / "home-assistant" / "packages" / "ecco_free_power_schedule.yaml"
check(
    "the HA-side scheduled Free Power wrapper package still exists and still drives the SAME firmware "
    "entry points this pass modified (write_enable arm, start button) - it has no register-level "
    "knowledge of 256-261 to regress, since it only calls the existing firmware script/service surface",
    schedule_pkg.is_file()
    and "free_power_write_enable" in schedule_pkg.read_text(encoding="utf-8")
    and "start_free_power_charge_now" in schedule_pkg.read_text(encoding="utf-8"),
)

# ===========================================================================
# 19. Durable schema OTA/recovery compatibility: an old V2 Free Power data
#     record (pre-reg_tou_power_intended) left behind by prior firmware must
#     NOT be silently accepted by the new V3-expecting firmware, and a CLEAR
#     marker must never let stale V2 bytes reconstruct a recovery obligation.
#
#     registry/tests/test_recovery_marker_state_machine.py section [D]
#     already proves the GENERAL structural property ("RESTORE_REQUIRED +
#     unreadable snapshot data -> fail-closed lockout, never restores with
#     default values") for the free_power domain. What is added here is the
#     MECHANISM-level proof specific to this pass's v2->v3 bump: that an old
#     V2 record is *actually* unreadable under the new V3 tag (not merely
#     assumed to be), by replaying ecco_durable::key_for()'s exact algorithm
#     (esphome/core/helpers.cpp's fnv1_hash - FNV-1, not FNV-1a: offset basis
#     2166136261, prime 16777619, `hash = hash*prime; hash ^= byte` per byte)
#     in Python against the real tag strings pulled from the header, and
#     confirming the CLEAR branch's own code never even attempts to load
#     Free Power data.
# ===========================================================================
print("")
print("[19] Durable schema OTA/recovery compatibility: an old V2 record is genuinely unreadable under the new V3 tag")


def _fnv1_hash(s: str) -> int:
    """Python replica of esphome/core/helpers.cpp's fnv1_hash(const char*) -
    classic FNV-1 (multiply-then-xor), NOT FNV-1a. Used only to prove two
    tag strings hash to different ecco_durable::key_for() NVS keys - never
    to simulate ESPHome's preferences backend itself."""
    h = 0x811C9DC5  # FNV1_OFFSET_BASIS = 2166136261
    for byte in s.encode("utf-8"):
        h = (h * 0x01000193) & 0xFFFFFFFF  # FNV1_PRIME = 16777619
        h ^= byte
        h &= 0xFFFFFFFF
    return h


tag_v1_m = re.search(r'FREE_POWER_DATA_TAG_V1 = "([^"]+)"', header)
tag_v2_m = re.search(r'FREE_POWER_DATA_TAG_V2 = "([^"]+)"', header)
tag_v3_m = re.search(r'FREE_POWER_DATA_TAG_V3 = "([^"]+)"', header)
check(
    "the header declares distinct literal tag strings for v1, v2 and v3 (schema rule 1: a new tag string per layout change)",
    None not in (tag_v1_m, tag_v2_m, tag_v3_m)
    and len({tag_v1_m.group(1), tag_v2_m.group(1), tag_v3_m.group(1)}) == 3,
)
if tag_v2_m and tag_v3_m:
    key_v2 = _fnv1_hash(tag_v2_m.group(1))
    key_v3 = _fnv1_hash(tag_v3_m.group(1))
    check(
        "ecco_durable::key_for() (FNV-1 of the tag string) produces a DIFFERENT NVS key for the v2 tag "
        "than for the v3 tag - an old V2 record physically cannot be found under the new V3 key, "
        "so ecco_durable::load_record(key_for(FREE_POWER_DATA_TAG), data) genuinely returns false "
        "for it, exactly like 'no record at all' - it is never reinterpreted as a V3 record",
        key_v2 != key_v3,
        f"key_for(v2)=0x{key_v2:08x} key_for(v3)=0x{key_v3:08x}",
    )
check(
    # 2026-09-24 (PR-A): a later pass bumped the tag again, to V4 (register-244
    # active-lease context - see ecco_durable_snapshot.h and
    # registry/tests/test_free_power_reg244_context_v4.py). The alias no
    # longer points at V3 itself, but V3 remains defined, distinct from V2,
    # and is what THIS 2026-09-23 pass's own bump actually produced - the
    # property this check exists to pin.
    "FREE_POWER_DATA_TAG_V3 remains its own distinct, defined historical tag - "
    "not V2, and not repurposed by any later bump",
    tag_v2_m is not None and tag_v3_m is not None and tag_v2_m.group(1) != tag_v3_m.group(1),
)
check(
    "FREE_POWER_DATA_TAG (the alias every call site actually uses) does NOT currently point at V2 "
    "(a later 2026-09-24 pass moved it on to V4 - see test_free_power_reg244_context_v4.py)",
    "constexpr const char *FREE_POWER_DATA_TAG = FREE_POWER_DATA_TAG_V2;" not in header,
)

# --- marker = RESTORE_REQUIRED, only a (now-invisible) V2 record exists ----
# From the firmware's point of view this IS the "unreadable snapshot data"
# case test_recovery_marker_state_machine.py section [D] already covers -
# the assertions below confirm that generic guarantee is still true after
# this pass's edits, phrased in terms of THIS scenario, and add the two
# properties [D] does not check: that NO owned-register global (including
# the new free_power_target_tou_power) is ever assigned in the failure
# branch, and that the durable marker itself is left untouched (still
# RESTORE_REQUIRED, never coerced to CLEAR) so a human can still recover it.
restore_required_branch_m = re.search(
    r"\} else \{  // MARKER_RESTORE_REQUIRED\s*\n\s*ecco_durable::FreePowerSnapshotData data\{\};\s*\n\s*"
    r"if \(ecco_durable::load_record\(ecco_durable::key_for\(ecco_durable::FREE_POWER_DATA_TAG\), data\)\) \{"
    r"(.*?)\n\s*\} else \{(.*?)\n              \}\n            \}\n          \}",
    fw,
    re.S,
)
check("found on_boot's MARKER_RESTORE_REQUIRED branch (success + failure halves)", restore_required_branch_m is not None)
if restore_required_branch_m:
    success_half, failure_half = restore_required_branch_m.group(1), restore_required_branch_m.group(2)
    check(
        "the FAILURE half (load_record returned false - exactly what happens for a V2-only record under "
        "the V3 key) sets free_power_recovery_metadata_corrupt = true (fail-closed lockout)",
        "id(free_power_recovery_metadata_corrupt) = true;" in failure_half,
    )
    check(
        "...and still marks a snapshot as valid/outstanding (free_power_snapshot_valid = true) rather "
        "than silently dropping the obligation",
        "id(free_power_snapshot_valid) = true;" in failure_half,
    )
    check(
        "...and does NOT assign free_power_snapshot_reg256..261/230/232/268-279 or "
        "free_power_target_reg230/free_power_target_tou_power from anything - no fabricated/default "
        "snapshot is ever constructed in the failure half",
        not re.search(r"id\(free_power_(snapshot_reg\d+|target_reg230|target_tou_power)\)\s*=", failure_half),
    )
    check(
        "...and does NOT commit a marker transition of any kind (the durable RESTORE_REQUIRED marker is "
        "left exactly as boot found it, never coerced to CLEAR) - only the SUCCESS half ever loads "
        "register fields",
        "ecco_durable::commit_record" not in failure_half,
    )
    check(
        "the SUCCESS half (a genuinely readable V3 record) is the ONLY place that assigns "
        "free_power_target_tou_power from the durable record",
        "id(free_power_target_tou_power) = data.reg_tou_power_intended;" in success_half,
    )
check(
    "new inverter writes in the Free Power domain remain locked while the corruption flag is set - "
    "start_free_power_override's precondition checks !free_power_recovery_metadata_corrupt",
    "!id(free_power_recovery_metadata_corrupt)" in start_body,
)
check(
    "...and so does restore_free_power_snapshot's precondition (the escape hatch itself stays reachable "
    "only through deliberate operator recovery, not an automatic write)",
    "!id(free_power_recovery_metadata_corrupt)" in script_body("restore_free_power_snapshot"),
)

# --- marker = CLEAR, only stale V2 data exists -----------------------------
clear_branch_m = re.search(
    r"if \(state == ecco_durable::MARKER_CLEAR\) \{(.*?)\n\s*\} else if \(state == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR\)",
    fw,
    re.S,
)
check("found on_boot's MARKER_CLEAR branch", clear_branch_m is not None)
if clear_branch_m:
    clear_branch = clear_branch_m.group(1)
    check(
        "the CLEAR branch never calls ecco_durable::load_record for Free Power data at all - stale V2 "
        "bytes sitting under the (now-unused) v2 key are structurally unreachable from this branch, so "
        "no recovery obligation can be reconstructed merely because old data still exists somewhere",
        "load_record" not in clear_branch and "FREE_POWER_DATA_TAG" not in clear_branch,
    )
    check(
        "...it only ever sets free_power_snapshot_valid = false (no owed obligation)",
        "id(free_power_snapshot_valid) = false;" in clear_branch,
    )

# --- no migration mechanism was built; the operational rule is documented --
check(
    "no code anywhere in the running firmware references the retired v2 data tag directly (every call "
    "site uses only the stable FREE_POWER_DATA_TAG alias, which now resolves to v3 - see above) - "
    "the v2 constant exists only as an unused, documented historical record in the header, confirming "
    "no v2->v3 migration/conversion code was built, per the header's own stated preference for rule 1 "
    "(a new tag) over inventing one",
    "ecco_durable::FREE_POWER_DATA_TAG_V2" not in fw,
)
check(
    "the header documents the OTA operational prerequisite (only OTA when every durable marker reads "
    "CLEAR) - unchanged by this pass, still the load-bearing safety rule for this exact v2->v3 gap",
    "only OTA when every marker this file defines" in header
    and "reads CLEAR on the device being updated" in header,
)

# ===========================================================================
# 20. BEHAVIOURAL: the ceiling/floor SAFETY INVARIANT and the two POSITIVE-
#     READBACK safety boundaries under exhaustive fault injection, executed
#     on the REAL extracted activation and restore sequences (their actual
#     writes and write-value lambdas, readbacks, handler lambdas, timeout
#     lambdas and `if:` gates - see simulate()), over a concrete register
#     bank.
#
#     Invariant: no TOU Power slot (256-261) may be above its original value
#     unless all six SOC floors (268-273) are 100 - checked after EVERY
#     write, so it also holds for a reboot at any point in the sequence.
#     Every write gets every one of 8 outcomes - including "acknowledged but
#     NOT applied", the write-ack-vs-readback concern - and the safety
#     readback every one of 6 outcomes (including a conformant reply whose
#     values differ): 8^4 x 6 = 24576 combinations per sequence.
# ===========================================================================
print("")
print("[20] Ceiling/floor safety invariant + positive-readback boundaries under exhaustive fault injection")

activation_if = find_if(start_actions, lambda c: c == "return id(free_power_write_failed);")
activation_seq = activation_if.get("else") if activation_if else None
restore_if = find_if(
    dispatch_actions,
    lambda c: "!id(free_power_live_owned_matches)" in c and c.endswith("&& (id(free_power_live_matches_intended) || id(free_power_live_self_partial));"),
)
restore_seq = restore_if.get("then") if restore_if else None
check(
    "extracted the activation write sequence (else-branch of the durable-commit failure check) and the "
    "restore write sequence (then-branch of the classifier's write-permitted gate)",
    bool(activation_seq) and bool(restore_seq),
)
# 2026-09-24 (PR-A, independent-review fix round R2): the register-244
# context gates in restore_seq are NO LONGER stripped out before
# simulation - `simulate()` above walks through the REAL gate structure,
# pinning both 244 reads to always match (see _CONTEXT_READ_OVERRIDES) so
# this exhaustive sweep keeps exercising the same owned-register write
# sequence it covered before PR-A existed. Register-244 mismatch/unknown-
# context/read-failure behaviour is covered on its own terms in
# registry/tests/test_free_power_reg244_context_v4.py Section D/E.

# read_outcomes keys are (address, count) tuples, not bare addresses - see
# _free_power_action_sim.simulate's own docstring (more than one read can
# share an address with a different count, e.g. PR-A's two register-244
# context reads).
ACTIVATION_WRITES, ACTIVATION_READ = (232, 230, 268, 256), (268, 12)
RESTORE_WRITES, RESTORE_READ = (232, 256, 268, 230), (256, 6)


def combos(write_addrs, read_key):
    for w in itertools.product(WRITE_OUTCOMES, repeat=len(write_addrs)):
        for r in READ_OUTCOMES:
            yield dict(zip(write_addrs, w)), {read_key: r}


def run_all(seq, write_addrs, read_addr, start_bank):
    return [
        (wo, ro, *simulate(seq, wo, ro, start_bank))
        for wo, ro in combos(write_addrs, read_addr)
    ]


def any_violation(seq, write_addrs, read_addr, start_bank):
    for wo, ro in combos(write_addrs, read_addr):
        _, _, v = simulate(seq, wo, ro, start_bank)
        if v:
            return (wo, ro, v)
    return None


def writes_attempted(attempted):
    return [addr for kind, addr, _ in attempted if kind == "write"]


def bank_before_write(attempted, addr):
    return next((b for kind, a, b in attempted if kind == "write" and a == addr), None)


try:
    activation_results = run_all(activation_seq, ACTIVATION_WRITES, ACTIVATION_READ, ORIGINAL) if activation_seq else []
    restore_results = run_all(restore_seq, RESTORE_WRITES, RESTORE_READ, FREE_POWER) if restore_seq else []
    sim_error = None
except UnsupportedLambda as exc:  # new control flow the simulator refuses to guess about
    activation_results, restore_results, sim_error = [], [], str(exc)
check("the simulator understood every action in both real sequences (no unsupported control flow)", sim_error is None, f"{sim_error}")

if activation_results:
    happy = next(bank for wo, ro, bank, _, _ in activation_results
                 if set(wo.values()) == {"ok"} and ro[ACTIVATION_READ] == "ok")
    check(
        "activation happy path (every write acknowledged and applied, readback confirms): the full Free "
        "Power state lands, INCLUDING the 8000 W overlay on all six slots - the gates do not suppress success",
        happy == FREE_POWER,
    )
    v = next(((wo, ro, viol) for wo, ro, _, _, viol in activation_results if viol), None)
    check(
        f"activation: NONE of the {len(activation_results)} combinations ever leaves any TOU Power slot above "
        "its original while any SOC floor is below 100 - checked after every write",
        v is None,
        f"first violation: {v}",
    )
    overlay_preconditions = [
        bank_before_write(att, 256) for _, _, _, att, _ in activation_results if 256 in writes_attempted(att)
    ]
    intended_block = {a: FREE_POWER[a] for a in range(268, 280)}
    check(
        f"activation: in every one of the {len(overlay_preconditions)} combinations where the 256-261 overlay is "
        "written, 268-279 ACTUALLY held the intended values (SOC 100 and the exact intended raw source/mode "
        "words) at that moment - proven by the bank, not by an acknowledgement",
        overlay_preconditions != []
        and all({a: b[a] for a in range(268, 280)} == intended_block for b in overlay_preconditions),
    )
    _write_failing = {"error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed", "timeout_lost"}
    blocked = [
        (bank, att) for wo, ro, bank, att, _ in activation_results
        if any(wo[a] in _write_failing for a in (232, 230, 268))
        or wo[268] == "ack_not_applied"
        or ro[ACTIVATION_READ] != "ok"
    ]
    check(
        f"activation, failure BEFORE the Power overlay ({len(blocked)} combinations: any failing 232/230/268 "
        "write, a 268-279 write acknowledged but not applied, or a readback that errors / times out / gets no "
        "response / is refused / returns a mismatching value): 256-261 is never written and every TOU Power "
        "slot keeps its original value",
        all(256 not in writes_attempted(att) and all(bank[a] == ORIGINAL[a] for a in range(256, 262))
            for bank, att in blocked),
    )
    readback_blocked = [
        (bank, att) for wo, ro, bank, att, _ in activation_results
        if wo[268] == "ok" and ro[ACTIVATION_READ] in ("ok_changed", "error", "not_sent", "no_response", "timeout")
    ]
    check(
        f"activation, 268-279 write SUCCEEDS but the safety readback mismatches/errors/times out "
        f"({len(readback_blocked)} combinations): still no overlay - the write acknowledgement alone is never "
        "enough to raise TOU Power",
        readback_blocked != [] and all(256 not in writes_attempted(att) for _, att in readback_blocked),
    )

if restore_results:
    happy = next(bank for wo, ro, bank, _, _ in restore_results
                 if set(wo.values()) == {"ok"} and ro[RESTORE_READ] == "ok")
    check(
        "restore happy path (every write acknowledged and applied, readback confirms): every register returns "
        "to its exact original",
        happy == ORIGINAL,
    )
    v = next(((wo, ro, viol) for wo, ro, _, _, viol in restore_results if viol), None)
    check(
        f"restore: NONE of the {len(restore_results)} combinations ever lowers an SOC floor while any TOU Power "
        "slot is still above its original - checked after every write",
        v is None,
        f"first violation: {v}",
    )
    floor_preconditions = [
        bank_before_write(att, 268) for _, _, _, att, _ in restore_results if 268 in writes_attempted(att)
    ]
    check(
        f"restore: in every one of the {len(floor_preconditions)} combinations where 268-279 is restored, "
        "256-261 ACTUALLY held their exact original values at that moment - proven by the bank, not by an "
        "acknowledgement",
        floor_preconditions != []
        and all(all(b[a] == ORIGINAL[a] for a in range(256, 262)) for b in floor_preconditions),
    )
    power_not_confirmed = [
        (bank, att) for wo, ro, bank, att, _ in restore_results
        if wo[256] != "ok" or ro[RESTORE_READ] != "ok"
    ]
    check(
        f"restore, TOU Power restore not positively confirmed ({len(power_not_confirmed)} combinations: the "
        "256-261 write fails in any way or is acknowledged but not applied, or the readback errors / times out "
        "/ gets no response / is refused / mismatches): 268-279 and 230 are NOT attempted in that attempt, all "
        "six SOC floors stay 100 and 230 keeps the Free Power current",
        all(
            268 not in writes_attempted(att) and 230 not in writes_attempted(att)
            and all(bank[a] == 100 for a in range(268, 274)) and bank[230] == TARGET_AMPS
            for bank, att in power_not_confirmed
        ),
    )


# Sensitivity / mutation checks: the invariant checker must actually DETECT
# unsafe layouts, including the ack-only design this readback replaced -
# otherwise the checks above could pass vacuously.
def _mutate(seq, fn):
    """Deep-copy `seq` and apply fn(action_list) -> new_action_list at every level."""
    def walk(actions):
        out = []
        for action in fn(copy.deepcopy(actions)):
            kind, body = _single(action)
            if kind == "if":
                for branch in ("then", "else"):
                    if branch in body:
                        body[branch] = walk(body[branch])
            out.append(action)
        return out
    return walk(seq)


def _retarget_gate(old, new):
    def fn(actions):
        for action in actions:
            kind, body = _single(action)
            if kind == "if" and _cond_text(body) == old:
                body["condition"]["lambda"] = new
        return actions
    return fn


def _no_compare(flag):
    """The readback still runs and still assigns its flag, but its value
    comparison loop is deleted - `confirmed` stays true whatever the
    inverter actually returned."""
    def fn(actions):
        for action in actions:
            kind, body = _single(action)
            if kind == READ:
                for handler_action in body["on_response"]["then"]:
                    code = handler_action["lambda"]
                    if f"id({flag}) = confirmed;" in code:
                        handler_action["lambda"] = re.sub(r"for \(int i=0;i<\d+;i\+\+\) confirmed = [^;]+;", "", code)
        return actions
    return fn


def _drop_readback(read_addr):
    """Remove the whole positive-readback step (the `if:` whose then-branch
    holds the boundary READ) - i.e. back to the acknowledgement-only design."""
    def fn(actions):
        out = []
        for action in actions:
            kind, body = _single(action)
            if kind == "if" and any(
                _single(a)[0] == READ and _single(a)[1]["start_address"] == read_addr for a in body.get("then", [])
            ):
                continue
            out.append(action)
        return out
    return fn


def _compose(*fns):
    def fn(actions):
        for f in fns:
            actions = f(actions)
        return actions
    return fn


def _unwrap_gate(cond):
    def fn(actions):
        out = []
        for action in actions:
            kind, body = _single(action)
            if kind == "if" and _cond_text(body) == cond:
                out.extend(body.get("then", []))
            else:
                out.append(action)
        return out
    return fn


def _pre_fix_activation(seq):
    """The originally audited layout: overlay unconditional, BEFORE 268-279."""
    overlay_idx = next(i for i, a in enumerate(seq) if _single(a)[0] == "if" and _cond_text(_single(a)[1]) == GATE_OVERLAY)
    overlay_then = _single(seq[overlay_idx])[1]["then"]
    rest = seq[:overlay_idx] + seq[overlay_idx + 1:]
    # 2026-09-28 (SG-01 defect A): the 268-279 write (with its own
    # op_terminal reset lambda) now sits inside its own `!write_failed`
    # gate, so insert the overlay before that top-level gate - i.e. still
    # immediately before the 268-279 step, exactly as audited.
    def _holds_w268(action):
        kind, body = _single(action)
        return kind == "if" and any(
            _single(a)[0] == WRITE and _single(a)[1]["start_address"] == 268 for a in body.get("then") or []
        )
    w268_step = next(i for i, a in enumerate(rest) if _holds_w268(a))
    return rest[:w268_step] + overlay_then + rest[w268_step:]


if activation_seq and restore_seq and sim_error is None:
    mutants = [
        ("the audited PRE-FIX activation layout (256-261 unconditional, before 268-279)",
         _pre_fix_activation(activation_seq), ACTIVATION_WRITES, ACTIVATION_READ, ORIGINAL),
        ("the previous ACK-ONLY activation design (no 268-279 readback; overlay gated on !write_failed only)",
         _mutate(activation_seq, _compose(_drop_readback(268), _retarget_gate(GATE_OVERLAY, GATE_NO_WRITE_FAILED))),
         ACTIVATION_WRITES, ACTIVATION_READ, ORIGINAL),
        ("an activation readback whose value comparison is removed (confirms whatever it reads)",
         _mutate(activation_seq, _no_compare("free_power_pre_power_overlay_confirmed")),
         ACTIVATION_WRITES, ACTIVATION_READ, ORIGINAL),
        ("the PRE-FIX restore layout (268-279/230 continue after the 256-261 restore, AND the PR-A "
         "context gates' own !write_failed check removed too - see GATE_PREWRITE_OR_PREFLOOR_CONTEXT's "
         "own comment for why both must be stripped to reproduce the true pre-2026-09-23 baseline)",
         # Order matters, and THREE passes are needed: the pre-write context
         # gate is unwrapped first (hoisting GATE_RESTORE_PROTECTED to a
         # level _unwrap_gate can see WITHIN this same pass); then
         # GATE_RESTORE_PROTECTED is unwrapped (hoisting the pre-floor
         # context gate - the SAME condition text as the pre-write one -
         # up in turn); then a second pass for that shared condition text
         # unwraps the now-hoisted pre-floor gate too. See
         # _compose/_mutate's own single-pass-per-level behaviour.
         _mutate(restore_seq, _compose(
             _unwrap_gate(GATE_PREWRITE_OR_PREFLOOR_CONTEXT),
             _unwrap_gate(GATE_RESTORE_PROTECTED),
             _unwrap_gate(GATE_PREWRITE_OR_PREFLOOR_CONTEXT),
         )),
         RESTORE_WRITES, RESTORE_READ, FREE_POWER),
        ("the previous ACK-ONLY restore design (no 256-261 readback; protected writes gated on !tou_restore_failed only)",
         _mutate(restore_seq, _compose(_drop_readback(256), _retarget_gate(GATE_RESTORE_PROTECTED, GATE_NO_TOU_RESTORE_FAILED))),
         RESTORE_WRITES, RESTORE_READ, FREE_POWER),
        ("a restore readback whose value comparison is removed (confirms whatever it reads)",
         _mutate(restore_seq, _no_compare("free_power_tou_restore_confirmed")),
         RESTORE_WRITES, RESTORE_READ, FREE_POWER),
    ]
    for label, seq, waddrs, raddr, bank in mutants:
        found = any_violation(seq, waddrs, raddr, bank)
        check(f"sensitivity: {label} IS detected as violating the invariant", found is not None, f"{found}")


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All 2026-09-23 Free Power TOU Power ownership offline tests PASSED.")

print("")
print("These are STRUCTURAL/source-text and pure-Python-model facts. They prove the")
print("source and the reference model agree with each other and with the stated")
print("design - they do NOT prove the compiled firmware behaves this way against")
print("real hardware. No live Free Power event, OTA, or inverter write has been")
print("performed as part of this change.")

if FAILURES:
    sys.exit(1)
