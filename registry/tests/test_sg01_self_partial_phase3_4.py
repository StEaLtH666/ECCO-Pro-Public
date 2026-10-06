#!/usr/bin/env python3
"""SG-01 Phase 3 + Phase 4 - the Free Power SELF_PARTIAL classifier and its
routing through the EXISTING restore write branch.

Phase 3: registry/free_power_self_partial.py is the pure Python model; the
firmware classifier lives in restore_free_power_snapshot_dispatch (the 256x24
fresh-read handler computes whole-vector block legs, the "SG-01 Phase 3 -
SELF_PARTIAL classifier" lambda applies rules 0-10 and sets
free_power_live_self_partial).

Phase 4: the dispatcher's existing restore write gate admits
`(matches_intended || live_self_partial)` and its NEITHER/operator-lockout gate
excludes live_self_partial. Nothing else in the restore path changed: same
ORIGINAL snapshot values, same B1 -> B4 -> readback -> reg244 -> B3 -> B2
order, both reg244 context gates, retry/backoff, verify-mismatch lockout and
the final verify of all 20 registers before any marker change.

How the REAL firmware is executed (no ESPHome/C++ toolchain, no hardware):
  * Equivalence (section [3]) runs the dispatch's real action tree up to the
    write gate through registry/tests/_free_power_action_sim.py: the real
    fresh-read handlers in its STRICT grammar (anything it cannot interpret
    raises), and the real journal-aware classifier lambda through
    registry/tests/_dump_sim.py's strict transpiler (the action simulator's
    journal guard refuses to skip it). The real gate conditions are then
    evaluated on the resulting state.
  * Behaviour (sections [4]-[14]) runs whole scripts - the real on_boot Free
    Power block, start_free_power_override, restore_free_power_snapshot and
    its dispatch - through _dump_sim with an in-memory NVS and register bank,
    including power cuts at every durable/Modbus event.

Sections:
  [1]  Python model API
  [2]  A  pure classifier truth table (model vs an independent oracle)
  [3]  B  firmware/Python equivalence over the full enumeration (+ rule 0)
  [4]  C/D ORIGINAL and INTENDED (BOTH degeneracies; INTENDED without journal)
  [5]  E  every reachable interrupted START row (power cut at every START
          event + reboot), and the START fault sweep (same boot)
  [6]  E2 interrupted SELF_PARTIAL restore (power cut at every restore event)
  [7]  F/G/H illegal mixed states; internal B3/B4 partials -> NEITHER
  [8]  I  attempt-bit proof
  [9]  J  START_VERIFIED v1-narrow
  [10] K  marker stale-RAM protection
  [11] L  SELF_PARTIAL restore order and reg244 gates
  [12] M  restore failure sweep + fresh reclassification
  [13] N  operator lockout is never bypassed
  [14] O/P no START resume; marker clears only after verified ORIGINAL
  [15] Q/R/S Force, Accept, Review, arbitration and containment unchanged
  [16] T  write/read/durable surface
  [17] U  mutation sensitivity
"""

from __future__ import annotations

import hashlib
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_durable_snapshot.h"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "registry"))
import _dump_sim as ds  # noqa: E402
import _free_power_action_sim as fpsim  # noqa: E402
import _sg01_journal_model as jm  # noqa: E402
import free_power_recovery_evidence as fpre  # noqa: E402
import free_power_self_partial as fsp  # noqa: E402
import _sg06_scope as sg06  # noqa: E402
import _mtou1_scope as mtou1  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402 - Dump V2's own later edits, reverted before the pins below
import _scope_chain as chain  # noqa: E402 - FB-T0: the change-scope pins in [15]/[16] are evaluated as of chain entry "dump_v2"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


for required in (FIRMWARE_PATH, HEADER_PATH):
    if not required.is_file():
        print(f"  FAIL  required file not found: {required}")
        sys.exit(1)

FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
HEADER = HEADER_PATH.read_text(encoding="utf-8")
D = ds.Durable

JKEY, DATA_KEY = D.FREE_POWER_START_JOURNAL_TAG, D.FREE_POWER_DATA_TAG
VALID_KEY, RETRY_KEY = D.FREE_POWER_VALID_TAG, D.FREE_POWER_RETRY_TAG
RR, CLEAR, PENDING = D.MARKER_RESTORE_REQUIRED, D.MARKER_CLEAR, D.MARKER_RESTORE_VERIFIED_PENDING_CLEAR
START, WRAPPER, DISPATCH = "start_free_power_override", "restore_free_power_snapshot", "restore_free_power_snapshot_dispatch"
OWNED = fpre.OWNED_REGISTER_ORDER
B1, B2, B3, B4 = fsp.BLOCKS
O, I, BOTH, X = fsp.O_ONLY, fsp.I_ONLY, fsp.BOTH, fsp.X
BITS = fsp.BLOCK_ATTEMPT_BIT
VERIFIED = jm.JOURNAL_FLAG_START_VERIFIED
COMMS, ORIGINAL, INTENDED, SELF_PARTIAL, NEITHER = (fsp.COMMS, fsp.ORIGINAL, fsp.INTENDED, fsp.SELF_PARTIAL,
                                                     fsp.NEITHER)
ROW_LETTER = {O: "O", I: "I", BOTH: "B", X: "X"}
READ_FAILS = ("error", "not_sent", "no_response", "timeout")
WRITE_FAILS = ("error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed", "timeout_lost",
               "ack_not_applied")
END_EPOCH = 1_790_003_600
LEASE = 1


def raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001 - a DIFFERENT exception is not the one under test
        return False
    return False


# ===========================================================================
# Scenario construction
# ===========================================================================
# Per block: a snapshot whose INTENDED differs from ORIGINAL (O_ONLY / I_ONLY
# / X are then representable) or one where they coincide (BOTH).
B3_SOC = {False: (20, 20, 30, 10, 20, 50), True: (100,) * 6}
B3_FLAGS = {False: (0x0000, 0x0004, 0x0008, 0x0010, 0x0021, 0x0106), True: (0x0001, 0x0005, 0x0009, 0x0011, 0x0021, 0x0101)}
B4_POWERS = {False: (1000, 1200, 800, 1000, 100, 3000), True: (3000,) * 6}
X_SINGLE = {B1: 0x0030, B2: 77}


def make_snapshot(both: dict | None = None) -> dict:
    """A FreePowerSnapshotData-shaped dict. `both[b]` True makes block b's
    ORIGINAL equal its INTENDED."""
    both = both or {}
    snap = {"end_epoch": END_EPOCH, "active_persisted": 0, "restore_requested": 0,
            "reg244_lease_context_plus1": LEASE + 1, "reg_tou_power_intended": 3000}
    snap["reg232"] = 0x0011 if both.get(B1) else 0x0010
    snap["reg230"], snap["reg230_intended"] = (50, 50) if both.get(B2) else (120, 58)
    for i in range(6):
        snap[f"reg{268 + i}"] = B3_SOC[bool(both.get(B3))][i]
        snap[f"reg{274 + i}"] = B3_FLAGS[bool(both.get(B3))][i]
        snap[f"reg{256 + i}"] = B4_POWERS[bool(both.get(B4))][i]
    return snap


def originals_of(snap: dict) -> dict:
    return {r: snap[f"reg{r}"] for r in OWNED}


def intended_of(snap: dict) -> dict:
    return fpre.derive_intended(originals=originals_of(snap), reg230_intended=snap["reg230_intended"],
                                reg_tou_power_intended=snap["reg_tou_power_intended"])


def x_vector(block: str, orig: dict, intd: dict) -> dict:
    regs = fsp.BLOCK_REGISTERS[block]
    if len(regs) == 1:
        return {regs[0]: X_SINGLE[block]}
    vec = {r: orig[r] for r in regs}
    vec[regs[0]] = intd[regs[0]]  # an internal mixture: first register INTENDED, the rest ORIGINAL
    return vec


def live_for(states: dict, snap: dict) -> dict:
    orig, intd = originals_of(snap), intended_of(snap)
    live: dict = {}
    for b in fsp.BLOCKS:
        regs = fsp.BLOCK_REGISTERS[b]
        if states[b] in (O, BOTH):
            live.update({r: orig[r] for r in regs})
        elif states[b] == I:
            live.update({r: intd[r] for r in regs})
        else:
            live.update(x_vector(b, orig, intd))
    return live


def scenario(states: dict) -> tuple[dict, dict]:
    snap = make_snapshot({b: s == BOTH for b, s in states.items()})
    return snap, live_for(states, snap)


def make_bank(live: dict, reg244: int = LEASE) -> dict:
    return {**live, 231: 0, **{a: 0 for a in range(262, 268)}, 244: reg244, **{a: 0 for a in range(245, 256)}}


ALL_COMBOS = [dict(zip(fsp.BLOCKS, c)) for c in itertools.product(fsp.BLOCK_STATES, repeat=4)]


def row_of(states: dict) -> str:
    return "".join(ROW_LETTER[states[b]] for b in fsp.BLOCKS)


def states_of_row(row: str) -> dict:
    inv = {v: k for k, v in ROW_LETTER.items()}
    return {b: inv[c] for b, c in zip(fsp.BLOCKS, row)}


def evidence(snap: dict, *, marker=RR, snapshot_valid=True, corrupt=False, journal=None) -> fsp.RecoveryEvidence:
    valid, mask, flags, bound = journal if journal else (False, 0, 0, False)
    return fsp.RecoveryEvidence(marker_restore_required=marker == RR, snapshot_valid=snapshot_valid,
                                metadata_corrupt=corrupt, journal_valid=valid, journal_mask=mask,
                                journal_flags=flags, journal_bound=bound)


def model(snap: dict, live: dict, ev: fsp.RecoveryEvidence, read_ok: bool = True) -> str:
    return fsp.classify_live(originals=originals_of(snap), reg230_intended=snap["reg230_intended"],
                             reg_tou_power_intended=snap["reg_tou_power_intended"], live=live, evidence=ev,
                             read_ok=read_ok)


# ===========================================================================
print("[1] Python model API - registry/free_power_self_partial.py")
# ===========================================================================
check("four blocks in START write order: B1=232, B2=230, B3=268-279 (12), B4=256-261 (6)",
      fsp.BLOCKS == ("B1", "B2", "B3", "B4")
      and fsp.BLOCK_REGISTERS == {B1: (232,), B2: (230,), B3: tuple(range(268, 280)), B4: tuple(range(256, 262))})
check("attempt bits are the per-stage increments of the Phase 1 prefix masks (bit0 B1 .. bit3 B4)",
      [BITS[b] for b in fsp.BLOCKS] == [jm.JOURNAL_MASK_B1, jm.JOURNAL_MASK_B2 & ~jm.JOURNAL_MASK_B1,
                                        jm.JOURNAL_MASK_B3 & ~jm.JOURNAL_MASK_B2, jm.JOURNAL_MASK_B4 & ~jm.JOURNAL_MASK_B3]
      == [1, 2, 4, 8])
check("journal constants mirror the Phase 1 schema (valid masks, START_VERIFIED, known flags)",
      fsp.VALID_START_ATTEMPTED_MASKS == jm.JOURNAL_VALID_START_ATTEMPTED_MASKS
      and fsp.FLAG_START_VERIFIED == jm.JOURNAL_FLAG_START_VERIFIED and fsp.KNOWN_FLAGS == jm.JOURNAL_KNOWN_FLAGS)
check("INTENDED derivation is REUSED, not re-implemented (free_power_recovery_evidence.derive_intended)",
      fsp.derive_intended is fpre.derive_intended)
check("block_state truth table: O&I=BOTH, O=O_ONLY, I=I_ONLY, neither=X",
      [fsp.block_state(a, b) for a, b in ((True, True), (True, False), (False, True), (False, False))]
      == [BOTH, O, I, X])
check("SELF_PARTIAL routes to the SAME restore write route as INTENDED; NEITHER to operator lockout",
      fsp.restore_route(SELF_PARTIAL) == fsp.restore_route(INTENDED) == fsp.ROUTE_RESTORE
      and fsp.restore_route(NEITHER) == fsp.ROUTE_OPERATOR_LOCKOUT and fsp.restore_route(ORIGINAL) == fsp.ROUTE_SKIP_WRITE
      and fsp.restore_route(COMMS) == fsp.ROUTE_COMMS_BACKOFF)
check("classify_blocks refuses a live map missing an owned register (never guesses)",
      raises(ValueError, lambda: fsp.classify_blocks(originals={r: 0 for r in OWNED}, intended={r: 0 for r in OWNED},
                                                    live={r: 0 for r in OWNED if r != 279})))
check("classification_rule refuses an incomplete block map",
      raises(ValueError, lambda: fsp.classify_recovery({B1: O}, fsp.RecoveryEvidence())))
check("journal_schema_ok: prefix masks only, no unknown flags, START_VERIFIED only with mask 15",
      [m for m in range(256) if fsp.journal_schema_ok(m, 0)] == [0, 1, 3, 7, 15]
      and [m for m in range(256) if fsp.journal_schema_ok(m, VERIFIED)] == [15]
      and not fsp.journal_schema_ok(15, 0x02))

# ===========================================================================
print("")
print("[2] A: pure classifier truth table (model vs an independent oracle)")
# ===========================================================================


def oracle(blocks: dict, ev: fsp.RecoveryEvidence) -> str:
    """Independent restatement of the locked SG-01 rules (set arithmetic,
    not the model's rule walk)."""
    s = set(blocks.values())
    if s <= {O, BOTH}:
        return ORIGINAL
    if s <= {I, BOTH}:
        return INTENDED
    if X in s:
        return NEITHER
    permitted = (ev.marker_restore_required and ev.snapshot_valid and not ev.metadata_corrupt and ev.journal_valid
                 and ev.journal_bound and ev.journal_mask in (0, 1, 3, 7, 15) and ev.journal_flags == 0)
    needed = sum(BITS[b] for b, st in blocks.items() if st == I)
    coupling_violation = blocks[B4] == I and blocks[B3] == O
    return SELF_PARTIAL if permitted and needed & ~ev.journal_mask == 0 and not coupling_violation else NEITHER


JOURNALS_A = ([None] + [(v, m, f, bd) for v in (True, False) for m in (0, 1, 3, 7, 15, 5, 9, 2, 14)
                        for f in (0, VERIFIED, 0x02) for bd in (True, False)])
EVIDENCE_A = [evidence({}, marker=mk, snapshot_valid=sv, corrupt=co, journal=j)
              for mk in (RR, CLEAR) for sv, co in ((True, False), (True, True), (False, False)) for j in JOURNALS_A]
n_a = n_bad = 0
bad_a: list = []
for combo in ALL_COMBOS:
    for ev in EVIDENCE_A:
        n_a += 1
        got, want = fsp.classify_recovery(combo, ev), oracle(combo, ev)
        if got != want:
            n_bad += 1
            bad_a.append((row_of(combo), ev, got, want))
check(f"model == oracle over all {n_a} (256 block states x marker x trust x journal valid/mask/flags/binding) cases",
      n_bad == 0 and n_a == 256 * 2 * 3 * len(JOURNALS_A), f"{n_bad} divergences, first {bad_a[:2]}")
check("model rule 0: any read failure is COMMS, whatever the blocks/evidence",
      all(fsp.classify_recovery(c, ev, read_ok=False) == COMMS for c in ALL_COMBOS for ev in EVIDENCE_A[:5]))

GOOD = lambda mask: fsp.RecoveryEvidence(journal_valid=True, journal_mask=mask, journal_bound=True)  # noqa: E731
PINNED_ROWS = [
    # (row, evidence, expected, why)
    ("OOOO", fsp.RecoveryEvidence(), ORIGINAL, "all ORIGINAL"),
    ("BBBB", fsp.RecoveryEvidence(), ORIGINAL, "all BOTH: ORIGINAL wins the tie"),
    ("BOBO", fsp.RecoveryEvidence(), ORIGINAL, "BOTH/O_ONLY mix is ORIGINAL"),
    ("IIII", fsp.RecoveryEvidence(), INTENDED, "all INTENDED without any journal (pre-SG-01 obligation)"),
    ("IBIB", fsp.RecoveryEvidence(), INTENDED, "BOTH/I_ONLY mix is INTENDED without journal"),
    ("IIII", fsp.RecoveryEvidence(journal_valid=True, journal_mask=15, journal_flags=VERIFIED, journal_bound=True),
     INTENDED, "all INTENDED + START_VERIFIED stays INTENDED (rule 2 precedes rule 7)"),
    ("IOOO", GOOD(1), SELF_PARTIAL, "blueprint: B1 written, mask 1"),
    ("IIOO", GOOD(3), SELF_PARTIAL, "blueprint: B1+B2 written, mask 3"),
    ("IIIO", GOOD(7), SELF_PARTIAL, "blueprint: B1-B3 written, mask 7"),
    ("OIIO", GOOD(7), SELF_PARTIAL, "restore interrupted after B1 (mask 7)"),
    ("OIOO", GOOD(15), SELF_PARTIAL, "restore interrupted after B3 (mask 15)"),
    ("OIII", GOOD(15), SELF_PARTIAL, "restore interrupted after B1 of a non-verified all-I state"),
    ("IOOO", GOOD(3), SELF_PARTIAL, "power cut between the B2 commit and the B2 write"),
    ("BIOB", GOOD(3), SELF_PARTIAL, "BOTH blocks are always legal"),
    ("IIOO", GOOD(1), NEITHER, "B2 INTENDED-looking without its attempt bit"),
    ("OOIO", GOOD(3), NEITHER, "B3 INTENDED-looking without its attempt bit"),
    ("IIOI", GOOD(15), NEITHER, "B4 ceiling INTENDED over B3 floors ORIGINAL"),
    ("OOOI", GOOD(15), NEITHER, "B4 ceiling INTENDED over B3 floors ORIGINAL"),
    ("OIIO", fsp.RecoveryEvidence(journal_valid=True, journal_mask=15, journal_flags=VERIFIED, journal_bound=True),
     NEITHER, "START_VERIFIED mixed state is operator recovery in v1"),
    ("IOOO", fsp.RecoveryEvidence(), NEITHER, "no journal never grants SELF_PARTIAL"),
    ("IOOO", fsp.RecoveryEvidence(journal_valid=True, journal_mask=1, journal_bound=False), NEITHER, "unbound journal"),
    ("IOOO", fsp.RecoveryEvidence(journal_valid=True, journal_mask=5, journal_bound=True), NEITHER, "illegal mask 5"),
    ("IOOO", fsp.RecoveryEvidence(journal_valid=True, journal_mask=9, journal_bound=True), NEITHER, "illegal mask 9"),
    ("IOOO", fsp.RecoveryEvidence(journal_valid=False, journal_mask=15, journal_bound=True), NEITHER,
     "RAM valid flag false (fields otherwise good)"),
    ("IIIO", fsp.RecoveryEvidence(marker_restore_required=False, journal_valid=True, journal_mask=7, journal_bound=True),
     NEITHER, "marker not RESTORE_REQUIRED (stale journal RAM)"),
    ("IIIO", fsp.RecoveryEvidence(metadata_corrupt=True, journal_valid=True, journal_mask=7, journal_bound=True),
     NEITHER, "metadata corrupt"),
    ("IIIO", fsp.RecoveryEvidence(snapshot_valid=False, journal_valid=True, journal_mask=7, journal_bound=True),
     NEITHER, "snapshot not valid"),
    ("XOOO", GOOD(15), NEITHER, "X block"),
    ("IIXO", GOOD(15), NEITHER, "internal B3 mixture"),
    ("IIIX", GOOD(15), NEITHER, "internal B4 mixture"),
]
pin_bad = [(r, why, fsp.classify_recovery(states_of_row(r), ev), exp) for r, ev, exp, why in PINNED_ROWS
           if fsp.classify_recovery(states_of_row(r), ev) != exp]
check(f"all {len(PINNED_ROWS)} pinned blueprint/illegal rows classify exactly", not pin_bad, str(pin_bad))
check("rule precedence is observable: X before marker, marker before journal, journal before VERIFIED, "
      "VERIFIED before attempt bits, attempt bits before coupling",
      fsp.classification_rule(states_of_row("XIOO"), fsp.RecoveryEvidence(marker_restore_required=False)) == fsp.RULE_X_BLOCK
      and fsp.classification_rule(states_of_row("IOOO"), fsp.RecoveryEvidence(marker_restore_required=False, metadata_corrupt=True))
      == fsp.RULE_MARKER_NOT_RESTORE_REQUIRED
      and fsp.classification_rule(states_of_row("IOOO"), fsp.RecoveryEvidence(metadata_corrupt=True)) == fsp.RULE_SNAPSHOT_UNTRUSTED
      and fsp.classification_rule(states_of_row("IOOO"), fsp.RecoveryEvidence(journal_valid=True, journal_mask=15, journal_flags=VERIFIED))
      == fsp.RULE_JOURNAL_INVALID
      and fsp.classification_rule(states_of_row("IIOO"), fsp.RecoveryEvidence(journal_valid=True, journal_mask=15, journal_flags=VERIFIED, journal_bound=True))
      == fsp.RULE_START_VERIFIED
      and fsp.classification_rule(states_of_row("IIOI"), GOOD(3)) == fsp.RULE_ATTEMPT_BIT_MISSING
      and fsp.classification_rule(states_of_row("IIOI"), GOOD(15)) == fsp.RULE_CEILING_OVER_ORIGINAL_FLOORS)
check("SELF_PARTIAL legality helper: O_ONLY/BOTH always legal, I_ONLY needs its bit, X never, B4-I over B3-O never",
      fsp.self_partial_legal_blocks(states_of_row("OBOB"), 0) and fsp.self_partial_legal_blocks(states_of_row("IIIO"), 7)
      and not fsp.self_partial_legal_blocks(states_of_row("IIIO"), 3)
      and not fsp.self_partial_legal_blocks(states_of_row("XOOO"), 15)
      and not fsp.self_partial_legal_blocks(states_of_row("OOOI"), 15))
check("with a good journal the number of SELF_PARTIAL block states grows with the prefix mask "
      "(mask 0 admits only BOTH/O mixes, which are ORIGINAL - so none)",
      [sum(fsp.classify_recovery(c, GOOD(m)) == SELF_PARTIAL for c in ALL_COMBOS) for m in (0, 1, 3, 7, 15)]
      == sorted(sum(fsp.classify_recovery(c, GOOD(m)) == SELF_PARTIAL for c in ALL_COMBOS) for m in (0, 1, 3, 7, 15))
      and sum(fsp.classify_recovery(c, GOOD(0)) == SELF_PARTIAL for c in ALL_COMBOS) == 0)


# ===========================================================================
# Firmware execution contexts (real firmware, or a mutant in [17])
# ===========================================================================
class FwCtx:
    def __init__(self, text: str):
        self.text = text
        self.fw = ds.load_firmware_text(text)
        self.scripts = {s["id"]: s for s in self.fw["script"]}
        actions = self.scripts[DISPATCH]["then"]
        gates = [i for i, a in enumerate(actions)
                 if "if" in a and "free_power_live_matches_intended" in fpsim._cond_text(a["if"])]
        self.prefix = actions[:gates[0]]
        self.write_cond = actions[gates[0]]["if"]["condition"]["lambda"]
        self.drift_cond = actions[gates[1]]["if"]["condition"]["lambda"]
        self.js = ds.Sim(self.fw)
        self.base_g = dict(self.js.g)


REAL = FwCtx(FW_TEXT)
FW = REAL.fw


def ram_state(ctx: FwCtx, snap: dict, *, marker=RR, snapshot_valid=True, corrupt=False, journal=None) -> dict:
    st = dict(ctx.base_g)
    st.update({
        "free_power_snapshot_valid": snapshot_valid, "free_power_recovery_metadata_corrupt": corrupt,
        "free_power_marker_state": marker, "free_power_end_epoch": snap["end_epoch"],
        "free_power_target_reg230": snap["reg230_intended"], "free_power_target_tou_power": snap["reg_tou_power_intended"],
        "free_power_lease_context_reg244": snap["reg244_lease_context_plus1"] - 1,
        **{f"free_power_snapshot_reg{r}": snap[f"reg{r}"] for r in OWNED},
        # what restore_free_power_snapshot sets before executing the dispatch
        "free_power_operation_in_progress": True, "manual_write_in_progress": True,
        "free_power_write_failed": False, "free_power_op_terminal": False,
    })
    valid, mask, flags, bound = journal if journal else (False, 0, 0, False)
    binding = jm.journal_binding(snap)
    st.update({"free_power_start_journal_valid": valid, "free_power_start_journal_mask": mask,
               "free_power_start_journal_flags": flags,
               "free_power_start_journal_binding": binding if bound else binding ^ 0xA5A5A5A5})
    return st


def fw_probe(ctx: FwCtx, snap: dict, live: dict, *, reads=None, **kw) -> tuple[dict, bool, bool]:
    """Runs the real dispatch prefix (reset, both fresh reads + their real
    handlers, bounded waits, the real SELF_PARTIAL classifier) and evaluates
    the real write/NEITHER gate conditions on the resulting state."""
    ctx.js.reset_durable()
    _bank, st, _att, _v, _sk = fpsim.simulate(
        ctx.prefix, {}, {(230, 3): "ok", (256, 24): "ok", **(reads or {})}, make_bank(live), ram_state(ctx, snap, **kw),
        journal_sim=ctx.js)
    ctx.js.g = st
    return st, bool(ctx.js.run_lambda(ctx.write_cond)), bool(ctx.js.run_lambda(ctx.drift_cond))


def fw_class(st: dict) -> str:
    if st["free_power_write_failed"] or not st["free_power_live_read_ok"]:
        return COMMS
    if st["free_power_live_owned_matches"]:
        return ORIGINAL
    if st["free_power_live_matches_intended"]:
        return INTENDED
    return SELF_PARTIAL if st["free_power_live_self_partial"] else NEITHER


def dev_class(g: dict) -> str:
    """The dispatch's own classification of its last attempt, read from the
    per-attempt flags only (a LATER write failure in the same attempt sets
    free_power_write_failed but does not change what was classified)."""
    if not g["free_power_live_read_ok"]:
        return COMMS
    if g["free_power_live_owned_matches"]:
        return ORIGINAL
    if g["free_power_live_matches_intended"]:
        return INTENDED
    return SELF_PARTIAL if g["free_power_live_self_partial"] else NEITHER


def fw_route(st: dict, write_gate: bool, drift_gate: bool) -> str:
    if write_gate and drift_gate:
        return "BOTH-GATES"
    if write_gate:
        return fsp.ROUTE_RESTORE
    if drift_gate:
        return fsp.ROUTE_OPERATOR_LOCKOUT
    if st["free_power_write_failed"] or not st["free_power_live_read_ok"]:
        return fsp.ROUTE_COMMS_BACKOFF
    return fsp.ROUTE_SKIP_WRITE


def fw_blocks(st: dict) -> dict:
    return {B1: fsp.block_state(st["free_power_live_232_ok"], st["free_power_live_232_ok_intended"]),
            B2: fsp.block_state(st["free_power_live_230_ok"], st["free_power_live_230_ok_intended"]),
            B3: fsp.block_state(st["free_power_live_b3_original"], st["free_power_live_b3_intended"]),
            B4: fsp.block_state(st["free_power_live_b4_original"], st["free_power_live_b4_intended"])}


JOURNALS_B = ([("absent", None)]
              + [("RAM valid=false, fields otherwise good", (False, 15, 0, True))]
              + [(f"mask {m}", (True, m, 0, True)) for m in (0, 1, 3, 7, 15)]
              + [(f"mask {m} + START_VERIFIED", (True, m, VERIFIED, True)) for m in (0, 1, 3, 7, 15)]
              + [(f"illegal mask {m}", (True, m, 0, True)) for m in (5, 9, 2, 14)]
              + [("unknown flag 0x02", (True, 15, 0x02, True))])
JOURNALS_B = JOURNALS_B + [(label + " / UNBOUND", (j[0], j[1], j[2], False)) for label, j in JOURNALS_B if j]
CONTEXTS_B = ([dict(marker=RR)]
              + [dict(marker=mk, snapshot_valid=sv, corrupt=co) for mk, sv, co in
                 ((CLEAR, True, False), (PENDING, True, False), (RR, True, True), (RR, False, False), (CLEAR, True, True))])


def equivalence(ctx: FwCtx, combos, journals, contexts, *, stop_at_first=False) -> tuple[int, list]:
    n, bad = 0, []
    for combo in combos:
        snap, live = scenario(combo)
        for ckw in contexts:
            for label, j in journals:
                n += 1
                st, wg, ng = fw_probe(ctx, snap, live, journal=j, **ckw)
                ev = evidence(snap, journal=j, **ckw)
                want = model(snap, live, ev)
                got = fw_class(st)
                if (got != want or fw_route(st, wg, ng) != fsp.restore_route(want) or fw_blocks(st) != combo
                        or st["free_power_live_self_partial"] != (want == SELF_PARTIAL)):
                    bad.append((row_of(combo), label, ckw, got, want, fw_route(st, wg, ng)))
                    if stop_at_first:
                        return n, bad
    return n, bad


# ===========================================================================
print("")
print("[3] B: firmware/Python equivalence (real handlers in the STRICT grammar + real classifier lambda)")
# ===========================================================================
check("the dispatch prefix (reset -> 230x3 -> 256x24 -> bounded waits -> SELF_PARTIAL classifier) contains "
      "exactly two reads, no write, and exactly one journal-aware lambda",
      [(k, b.get("start_address"), b.get("count")) for k, _g, b in fpsim.flatten(REAL.prefix) if k in (fpsim.READ, fpsim.WRITE)]
      == [(fpsim.READ, 230, 3), (fpsim.READ, 256, 24)]
      and sum(1 for k, _g, b in fpsim.flatten(REAL.prefix) if k == "lambda" and fpsim.mentions_journal(b)) == 1)
_handlers = [a[fpsim.READ]["on_response"]["then"][0]["lambda"] for a in REAL.prefix if fpsim.READ in a]
check("both fresh-read on_response handlers parse in the action simulator's STRICT grammar (nothing skipped)",
      len(_handlers) == 2 and not any(raises(Exception, lambda h=h: fpsim._ops_for(h)) for h in _handlers))
check("the real write gate and NEITHER gate parse in the action simulator's condition grammar",
      all(fpsim.eval_condition(fpsim._norm(c), {**REAL.base_g}) in (True, False) for c in (REAL.write_cond, REAL.drift_cond)))

n_b, bad_b = equivalence(REAL, ALL_COMBOS, JOURNALS_B, CONTEXTS_B[:1])
check(f"marker RESTORE_REQUIRED, trusted snapshot: firmware == model for all {n_b} cases "
      "(256 block states x journal absent/invalid/masks 0,1,3,7,15/START_VERIFIED/illegal masks 5,9,2,14/"
      "unknown flag, each bound and unbound) - classification, route, block states and the RAM flag",
      not bad_b and n_b == 256 * len(JOURNALS_B), f"{len(bad_b)} divergences, first {bad_b[:3]}")
n_b2, bad_b2 = equivalence(REAL, ALL_COMBOS, [("mask 15", (True, 15, 0, True)), ("mask 7", (True, 7, 0, True))],
                           CONTEXTS_B[1:])
check(f"marker CLEAR / PENDING_CLEAR, metadata corrupt, snapshot invalid: firmware == model for all {n_b2} cases",
      not bad_b2 and n_b2 == 256 * 2 * 5, f"{len(bad_b2)} divergences, first {bad_b2[:3]}")

# fpsim's own condition evaluator agrees with the transpiler on every real-firmware gate outcome.
_agree = True
for combo in ALL_COMBOS[::7]:
    snap, live = scenario(combo)
    st, wg, ng = fw_probe(REAL, snap, live, journal=(True, 15, 0, True))
    _agree &= (fpsim.eval_condition(fpsim._norm(REAL.write_cond), st) == wg
               and fpsim.eval_condition(fpsim._norm(REAL.drift_cond), st) == ng)
check("the action simulator's condition grammar and the transpiler agree on both gates", _agree)

# Rule 0 - any fresh read failure/timeout: COMMS, never a write or a lockout.
n0, bad0 = 0, []
for combo in ALL_COMBOS:
    snap, live = scenario(combo)
    for key in ((230, 3), (256, 24)):
        for outcome in READ_FAILS:
            n0 += 1
            st, wg, ng = fw_probe(REAL, snap, live, journal=(True, 15, 0, True), reads={key: outcome})
            if fw_class(st) != COMMS or wg or ng or st["free_power_live_self_partial"]:
                bad0.append((row_of(combo), key, outcome))
check(f"rule 0: every fresh-read failure (230x3 / 256x24 x error/not_sent/no_response/timeout) over all 256 block "
      f"states is COMMS - no write gate, no lockout, SELF_PARTIAL false ({n0} cases)", not bad0 and n0 == 256 * 8,
      str(bad0[:3]))

# ===========================================================================
# Whole-device harness (_dump_sim): boot from NVS, run the real restore.
# ===========================================================================
FP_BOOT_START = "// Durable recovery snapshots (Free Power, Register 244) now live in"
FP_BOOT_END = "// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/"
MAX_POWER_W, BATTERY_V = 3000, 52.0
START_ORIGINAL = {
    230: 120, 231: 0, 232: 0x0010,
    **dict(zip(range(256, 262), (1000, 1200, 800, 1000, 100, 3000))),
    **{a: 0 for a in range(262, 268)},
    **dict(zip(range(268, 274), (20, 20, 30, 10, 20, 50))),
    **dict(zip(range(274, 280), (0x0000, 0x0004, 0x0008, 0x0010, 0x0021, 0x0106))),
    244: LEASE, **{a: 0 for a in range(245, 256)},
}
SNAP = make_snapshot()  # identical ORIGINAL values to START_ORIGINAL, intended 58 A / 3000 W
assert all(SNAP[f"reg{r}"] == START_ORIGINAL[r] for r in OWNED)
SNAP_ORIG, SNAP_INT = originals_of(SNAP), intended_of(SNAP)


def fp_boot_block(fw) -> str:
    boot = fw["esphome"]["on_boot"]["then"][0]["lambda"]
    return boot[boot.index(FP_BOOT_START):boot.index(FP_BOOT_END)]


def _env(sim) -> None:
    sim.scripts = dict(sim.scripts)
    sim.scripts["poll_inverter_configuration"] = {"then": []}
    sim.ent("free_power_write_enable").state = True
    sim.ent("configuration_online").state = True
    sim.g["ntp_synced"] = True
    sim.ent("ecco_battery_voltage").set(BATTERY_V)
    sim.ent("free_power_duration_minutes").set(60)
    sim.ent("free_power_max_power").set(MAX_POWER_W)
    real_execute = sim.execute

    def execute(script_id, params=None):
        # The register-244 reads' on_error handlers log ESPHome's
        # `exception_code` parameter; supply it like the real component does.
        if script_id == DISPATCH:
            params = {"exception_code": 0x02, **(params or {})}
        return real_execute(script_id, params)

    sim.execute = execute


def rec(kind: str, **fields) -> "ds.Record":
    r = ds.Record(kind)
    for k, v in fields.items():
        setattr(r, k, v)
    return r


def nvs_image(snap: dict = SNAP, *, marker=RR, journal=None, operator_needed=0, binding=None) -> dict:
    """`journal` = (mask, flags) committed exactly like START does, bound to
    `snap` unless `binding` overrides it."""
    nvs = {DATA_KEY: rec("FreePowerSnapshotData", **{k: snap[k] for k in ds._RECORD_FIELDS["FreePowerSnapshotData"]}),
           VALID_KEY: rec("ValidMarker", magic=D.VALID_MARKER_MAGIC, state=marker),
           RETRY_KEY: rec("FreePowerRetryState", operator_needed=operator_needed)}
    if journal is not None:
        mask, flags = journal
        nvs[JKEY] = rec(jm.JOURNAL_KIND, magic=jm.JOURNAL_MAGIC, start_attempted=mask, flags=flags, reserved=0,
                        binding=jm.journal_binding(snap) if binding is None else binding)
    return nvs


def boot_device(nvs: dict, bank: dict, ctx: FwCtx = REAL) -> "ds.Sim":
    sim = ds.Sim(ctx.fw)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.run_lambda(fp_boot_block(ctx.fw))
    _env(sim)
    sim.bank = dict(bank)
    return sim


def bank_for_row(row: str, snap: dict = SNAP) -> dict:
    return make_bank(live_for(states_of_row(row), snap))


class Run:
    """One call of the real restore_free_power_snapshot and what it did."""

    def __init__(self, sim, ops, dispatched, violations):
        self.sim, self.ops, self.dispatched, self.violations = sim, ops, dispatched, violations

    @property
    def writes(self):
        return [a for k, a, _v, _o in self.ops if k == "write"]

    @property
    def op_seq(self):
        return [(k, a) if k == "write" else (k, a, len(v)) for k, a, v, _o in self.ops]

    @property
    def cls(self):
        return dev_class(self.sim.g) if self.dispatched else None


def restore(sim, *, fail=None, read_override=None, hook=None) -> Run:
    """Runs the real restore_free_power_snapshot once. `fail` maps a 0-based
    Modbus-op index (within this call) to an outcome. Audits the run: every
    write carries the snapshot ORIGINAL values, the ceiling never rises over
    lowered floors, no START execution / data or journal commit, no
    active_persisted set, and any marker clear happens only with every owned
    register ORIGINAL."""
    g = sim.g
    snap_vals = {r: g[f"free_power_snapshot_reg{r}"] for r in OWNED}
    ap_before = g["free_power_active_persisted"]
    marker_before = g["free_power_marker_state"]
    log0, ex0, ev0 = len(sim.modbus_log), len(sim.executed), len(sim.events)
    n = [0]
    violations: list = []

    def outcome(kind, addr, count):
        i = n[0]
        n[0] += 1
        return (fail or {}).get(i, "ok")

    def audit(event):
        if event[0] == "write":
            bank = sim.bank
            ceiling_raised = any(bank.get(256 + i, 0) > snap_vals[256 + i] for i in range(6))
            floors_released = not all(bank.get(268 + i, 0) == 100 for i in range(6))
            if ceiling_raised and floors_released:
                violations.append(f"TOU ceiling above original with SOC floors released after write {event[1]}")
        if event[0] == "commit" and event[1] == VALID_KEY and event[3] and event[2].state != RR:
            if marker_before == RR and any(sim.bank.get(r) != snap_vals[r] for r in OWNED):
                violations.append("marker left RESTORE_REQUIRED while owned registers are not all ORIGINAL")
            if marker_before != RR and len(sim.modbus_log) != log0:
                violations.append("deferred (PENDING_CLEAR) marker clear performed Modbus I/O")
        if event[0] == "commit" and event[1] in (DATA_KEY, JKEY):
            violations.append(f"restore committed {event[1]}")
        if hook:
            hook(event)

    sim.outcome_fn = outcome
    sim.read_override_fn = read_override
    sim.event_hook = audit
    sim.execute(WRAPPER)
    sim.event_hook = None
    sim.read_override_fn = None
    ops = sim.modbus_log[log0:]
    for k, a, vals, _o in ops:
        if k == "write" and list(vals) != [snap_vals[a + i] for i in range(len(vals))]:
            violations.append(f"write {a} carried {vals}, not the snapshot ORIGINAL")
    executed = [s for s, _p in sim.executed[ex0:]]
    if START in executed:
        violations.append("start_free_power_override executed during restore")
    if g["free_power_active_persisted"] and not ap_before:
        violations.append("active_persisted set by restore")
    return Run(sim, ops, DISPATCH in executed, violations)


ALL_VIOLATIONS: list = []


def track(run: Run, label: str) -> Run:
    ALL_VIOLATIONS.extend(f"{label}: {v}" for v in run.violations)
    return run


def nvs_marker(sim) -> int | None:
    m = sim.nvs.get(VALID_KEY)
    return None if m is None else m.state


def nvs_operator_needed(sim) -> int:
    r = sim.nvs.get(RETRY_KEY)
    return 0 if r is None else r.operator_needed


def all_original(sim, orig=SNAP_ORIG) -> bool:
    return all(sim.bank[r] == orig[r] for r in OWNED)


RESTORE_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 244, 12), ("write", 232), ("write", 256),
               ("read", 256, 6), ("read", 244, 1), ("write", 268), ("write", 230), ("read", 230, 3), ("read", 256, 24)]
SKIP_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 230, 3), ("read", 256, 24)]


def completed(run: Run, orig=SNAP_ORIG) -> bool:
    s = run.sim
    return (all_original(s, orig) and s.g["free_power_marker_state"] == CLEAR and nvs_marker(s) == CLEAR
            and not s.g["free_power_snapshot_valid"] and not s.g["free_power_operator_needed"]
            and nvs_operator_needed(s) == 0 and not s.g["free_power_operation_in_progress"]
            and not s.g["manual_write_in_progress"])


def locked_out_neither(run: Run, bank_before: dict) -> bool:
    s = run.sim
    return (run.dispatched and run.writes == [] and s.g["free_power_restore_unexplained_drift"]
            and s.g["free_power_operator_needed"] and nvs_operator_needed(s) == 1
            and s.g["free_power_marker_state"] == RR and nvs_marker(s) == RR and s.g["free_power_snapshot_valid"]
            and s.bank == bank_before and not s.g["free_power_operation_in_progress"]
            and "matches neither" in str(s.ent("free_power_status").state))


def run_row(row: str, journal, *, snap=SNAP, ctx=REAL, fail=None, read_override=None, operator_needed=0,
            bank=None, label="", tracked=True) -> Run:
    dev = boot_device(nvs_image(snap, journal=journal, operator_needed=operator_needed),
                      bank if bank is not None else bank_for_row(row, snap), ctx)
    run = restore(dev, fail=fail, read_override=read_override)
    return track(run, label or f"{row} {journal}") if tracked else run


# ===========================================================================
print("")
print("[4] C/D: ORIGINAL and INTENDED - existing behaviour, BOTH degeneracies, INTENDED without a journal")
# ===========================================================================
for label, row, snap, journal in (
    ("ALL ORIGINAL, no journal", "OOOO", SNAP, None),
    ("ALL ORIGINAL, journal mask 15", "OOOO", SNAP, (15, 0)),
    ("ALL BOTH (ORIGINAL == INTENDED everywhere)", "BBBB", make_snapshot({b: True for b in fsp.BLOCKS}), (15, 0)),
    ("BOTH/O_ONLY mix", "BOBO", make_snapshot({B1: True, B3: True}), (15, 0)),
):
    run = run_row(row, journal, snap=snap, label=label)
    check(f"[C] {label}: classified ORIGINAL, zero restore writes, only the classification + final verify reads, "
          "marker cleared, no lockout",
          run.cls == ORIGINAL and run.writes == [] and run.op_seq == SKIP_OPS and completed(run, originals_of(snap)),
          f"cls={run.cls} ops={run.op_seq}")
for label, row, snap, journal in (
    ("ALL INTENDED, NO journal (pre-SG-01 obligation)", "IIII", SNAP, None),
    ("ALL INTENDED, journal mask 15", "IIII", SNAP, (15, 0)),
    ("ALL INTENDED, journal START_VERIFIED", "IIII", SNAP, (15, VERIFIED)),
    ("ALL INTENDED, journal bound to ANOTHER snapshot", "IIII", SNAP, "unbound"),
    ("ALL INTENDED, journal mask 1 (INTENDED needs no attempt bits)", "IIII", SNAP, (1, 0)),
    ("BOTH/I_ONLY mix, no journal", "BIBI", make_snapshot({B1: True, B3: True}), None),
):
    if journal == "unbound":
        dev = boot_device(nvs_image(snap, journal=(15, 0), binding=jm.journal_binding(snap) ^ 1), bank_for_row(row, snap))
        run = track(restore(dev), label)
    else:
        run = run_row(row, journal, snap=snap, label=label)
    check(f"[D] {label}: classified INTENDED and restored normally (exact restore op order), verified ORIGINAL, "
          "marker cleared", run.cls == INTENDED and run.op_seq == RESTORE_OPS and completed(run, originals_of(snap)),
          f"cls={run.cls} ops={run.op_seq}")

# ===========================================================================
print("")
print("[5] E: every reachable interrupted START row - real START, power cut after every event, reboot, restore")
# ===========================================================================


def start_device(ctx: FwCtx = REAL, *, start_writes=None, start_reads=None, stub_restore=False):
    sim = ds.Sim(ctx.fw)
    _env(sim)
    sim.bank = dict(START_ORIGINAL)
    if stub_restore:
        sim.scripts["restore_free_power_snapshot"] = {"then": []}
    sw, sr = start_writes or {}, start_reads or {}
    seen: dict = {}

    def outcome(kind, addr, count):
        # START's own operations only - a restore it triggers always gets "ok".
        # Reads are keyed ((addr, count), occurrence): START reads 230x3 and
        # 256x24 twice (snapshot, then activation verify).
        if DISPATCH in sim.running:
            return "ok"
        if kind == "write":
            return sw.get(addr, "ok")
        seen[(addr, count)] = seen.get((addr, count), 0) + 1
        return sr.get(((addr, count), seen[(addr, count)]), "ok")

    sim.outcome_fn = outcome
    return sim


def snap_from_nvs(nvs: dict) -> dict | None:
    data = nvs.get(DATA_KEY)
    return None if data is None else {k: getattr(data, k) for k in ds._RECORD_FIELDS["FreePowerSnapshotData"]}


def journal_of(nvs: dict):
    j = nvs.get(JKEY)
    return None if j is None else (j.start_attempted, j.flags)


cap_sim = start_device(stub_restore=True)
captures: list = []
cap_sim.event_hook = lambda e: captures.append((e, {k: v.copy() for k, v in cap_sim.nvs.items()}, dict(cap_sim.bank)))
cap_sim.execute(START)
check("the uninterrupted START completes verified (journal ends at mask 15 + START_VERIFIED)",
      journal_of(cap_sim.nvs) == (15, VERIFIED) and cap_sim.g["free_power_active_persisted"], str(journal_of(cap_sim.nvs)))
START_SNAP = snap_from_nvs(cap_sim.nvs)
START_ORIG, START_INT = originals_of(START_SNAP), intended_of(START_SNAP)

seen_sp, e_bad, e_rows = set(), [], []
for idx, (event, nvs, bank) in enumerate(captures):
    dev = boot_device(nvs, bank)
    blocks = fsp.classify_blocks(originals=START_ORIG, intended=START_INT, live=bank)
    row = row_of(blocks)
    run = track(restore(dev), f"START cut after event {idx} {event[:2]}")
    j = journal_of(nvs)
    e_rows.append((idx, row, j, run.cls))
    if run.cls == SELF_PARTIAL:
        seen_sp.add((row, j[0]))
    ok = all_original(dev, START_ORIG) and not dev.g["free_power_operator_needed"] and nvs_marker(dev) in (None, CLEAR)
    mixed = set(blocks.values()) - {O, BOTH} and set(blocks.values()) - {I, BOTH}
    if not ok or (mixed and run.cls != SELF_PARTIAL):
        e_bad.append((idx, event[:2], row, j, run.cls))
check(f"power cut after EVERY one of START's {len(captures)} durable/Modbus events, then reboot + restore: the "
      "inverter always ends wholly ORIGINAL, no operator lockout, no durable obligation left - and every mixed "
      "row is recovered as SELF_PARTIAL (before SG-01 Phase 4 these were NEITHER lockouts)",
      not e_bad and len(captures) > 15, f"{e_bad[:4]}")
check("the SELF_PARTIAL rows START can leave behind are exactly: I O O O (mask 1, and mask 3 before the B2 write), "
      "I I O O (mask 3, and mask 7 before the B3 write), I I I O (mask 7, and mask 15 before the B4 write)",
      seen_sp == {("IOOO", 1), ("IOOO", 3), ("IIOO", 3), ("IIOO", 7), ("IIIO", 7), ("IIIO", 15)}, str(sorted(seen_sp)))
check("rows after the B4 write are INTENDED (restored normally), rows before the B1 write are ORIGINAL",
      {c for _i, r, _j, c in e_rows if r == "IIII"} == {INTENDED}
      and {c for _i, r, _j, c in e_rows if r == "OOOO"} <= {ORIGINAL, None})

# Same boot: START's own failure route runs the restore immediately.
sweep_bad, sweep_n, sweep_cls = [], 0, {}
for kw in ([dict(start_writes={addr: o}) for addr in (232, 230, 268, 256) for o in WRITE_FAILS]
           + [dict(start_reads={(key, occ): o}) for key, occ in (((268, 12), 1), ((230, 3), 2), ((256, 24), 2))
              for o in READ_FAILS]):
    stub = start_device(stub_restore=True, **kw)
    stub.execute(START)
    j = journal_of(stub.nvs)
    ev = fsp.RecoveryEvidence(journal_valid=j is not None, journal_mask=j[0] if j else 0,
                              journal_flags=j[1] if j else 0, journal_bound=True)
    expected = fsp.classify_recovery(fsp.classify_blocks(originals=START_ORIG, intended=START_INT, live=stub.bank), ev)
    sim = start_device(**kw)
    ex0 = len(sim.executed)
    sim.execute(START)
    sweep_n += 1
    got = dev_class(sim.g) if DISPATCH in [s for s, _p in sim.executed[ex0:]] else None
    sweep_cls[got] = sweep_cls.get(got, 0) + 1
    if not (got == expected and all_original(sim, START_ORIG) and nvs_marker(sim) == CLEAR
            and not sim.g["free_power_operator_needed"] and not sim.g["free_power_active_persisted"]):
        sweep_bad.append((kw, expected, got, nvs_marker(sim), sim.g["free_power_operator_needed"]))
check(f"START fault sweep, same boot ({sweep_n} runs: every START write x 7 failure outcomes; the B3 readback and "
      "both activation-verify reads x 4 failure outcomes): START's own failure route runs the restore, the "
      "firmware classifies the post-START state exactly as the model does, restores it to ORIGINAL and clears "
      "the obligation - never an operator lockout", not sweep_bad and sweep_n == 4 * 7 + 3 * 4, f"{sweep_bad[:3]}")
check("...the sweep genuinely exercises SELF_PARTIAL, ORIGINAL and INTENDED recoveries (and no NEITHER)",
      sweep_cls.get(SELF_PARTIAL, 0) > 0 and sweep_cls.get(ORIGINAL, 0) > 0 and sweep_cls.get(INTENDED, 0) > 0
      and NEITHER not in sweep_cls, str(sweep_cls))

# ===========================================================================
print("")
print("[6] E2: interrupted SELF_PARTIAL restore - power cut after every restore event, reboot, restore again")
# ===========================================================================


def nested(nvs: dict, bank: dict, orig: dict, intd: dict, label: str):
    first = boot_device(nvs, bank)
    caps: list = []
    track(restore(first, hook=lambda e: caps.append((e, {k: v.copy() for k, v in first.nvs.items()},
                                                     dict(first.bank)))), label)
    results = []
    for idx, (event, nvs2, bank2) in enumerate(caps):
        dev = boot_device(nvs2, bank2)
        row = row_of(fsp.classify_blocks(originals=orig, intended=intd, live=bank2))
        run = track(restore(dev), f"{label} / cut {idx}")
        results.append((idx, event[:2], row, journal_of(nvs2), run, dev))
    return first, results


cut_after_b3 = next((nvs, bank) for (e, nvs, bank) in captures if e[0] == "write" and e[1] == 268)
first, results = nested(*cut_after_b3, START_ORIG, START_INT, "restore of I I I O mask 7")
check("the restore of I I I O (mask 7) itself completes", all_original(first, START_ORIG) and nvs_marker(first) == CLEAR)
bad_e2 = [(i, e, r, j, run.cls) for i, e, r, j, run, dev in results
          if not (all_original(dev, START_ORIG) and nvs_marker(dev) in (None, CLEAR) and not dev.g["free_power_operator_needed"])]
rows_e2 = {(r, j[0] if j else None, run.cls) for _i, _e, r, j, run, _d in results}
check(f"power cut after every one of that restore's {len(results)} events, reboot, restore again: always ends "
      "ORIGINAL with the obligation cleared and no lockout", not bad_e2 and len(results) >= 10, str(bad_e2[:3]))
check("the partially restored rows O I I O and O I O O (mask 7, not verified) are SELF_PARTIAL on the next attempt",
      ("OIIO", 7, SELF_PARTIAL) in rows_e2 and ("OIOO", 7, SELF_PARTIAL) in rows_e2, str(sorted(rows_e2, key=str)))

# All-INTENDED but NOT verified (activation verify failed): its interrupted restore is SELF_PARTIAL too.
vf = start_device(stub_restore=True, start_reads={((256, 24), 2): "error"})
vf.execute(START)
first, results = nested(dict(vf.nvs), dict(vf.bank), START_ORIG, START_INT, "restore of unverified I I I I mask 15")
rows_vf = {(r, run.cls) for _i, _e, r, _j, run, _d in results}
check("activation verify failed -> journal mask 15 WITHOUT START_VERIFIED; its interrupted restore rows "
      "(O I I I, O I I O, O I O O) are SELF_PARTIAL and always complete",
      journal_of(vf.nvs) == (15, 0) and {("OIII", SELF_PARTIAL), ("OIIO", SELF_PARTIAL), ("OIOO", SELF_PARTIAL)} <= rows_vf
      and all(all_original(d, START_ORIG) and nvs_marker(d) in (None, CLEAR) for *_x, d in results), str(sorted(rows_vf, key=str)))

# ===========================================================================
print("")
print("[7] F/G/H: illegal mixed states and internal B3/B4 partials -> NEITHER / existing operator lockout")
# ===========================================================================
F_CASES = [
    ("third party set B2 INTENDED-looking without its bit (mask 1)", "IIOO", (1, 0), {}),
    ("third party set B3 INTENDED-looking without its bit (mask 3)", "IIIO", (3, 0), {}),
    ("B4 INTENDED while B3 ORIGINAL (mask 15)", "IIOI", (15, 0), {}),
    ("B4 INTENDED while B3 ORIGINAL, B1/B2 ORIGINAL (mask 15)", "OOOI", (15, 0), {}),
    ("illegal journal mask 5 in NVS (boot rejects it)", "IOOO", (5, 0), {}),
    ("illegal journal mask 9 in NVS (boot rejects it)", "IOOO", (9, 0), {}),
    ("journal bound to a different snapshot", "IOOO", (1, 0), {"binding": "other"}),
    ("no journal (pre-SG-01 obligation)", "IOOO", None, {}),
    ("START_VERIFIED mixed restore state", "OIIO", (15, VERIFIED), {}),
    ("START_VERIFIED mixed restore state", "OIII", (15, VERIFIED), {}),
    ("X block B1", "XIOO", (15, 0), {}),
    ("X block B2", "IXOO", (15, 0), {}),
    ("internal B3 mixture", "IIXO", (15, 0), {}),
    ("internal B4 mixture", "IIIX", (15, 0), {}),
]
for label, row, journal, extra in F_CASES:
    nvs = nvs_image(SNAP, journal=journal,
                    binding=(jm.journal_binding(SNAP) ^ 0xFFFF) if extra.get("binding") == "other" else None)
    bank = bank_for_row(row)
    run = track(restore(boot_device(nvs, bank)), label)
    check(f"[F] {label} ({row}, journal {journal}): NEITHER -> zero writes, durable operator lockout, obligation "
          "retained", run.cls == NEITHER and locked_out_neither(run, bank), f"cls={run.cls} writes={run.writes}")

# RAM-level evidence the device cannot reach through NVS (fed straight into the real classifier).
for label, kw in (("marker CLEAR with snapshot still valid", dict(marker=CLEAR)),
                  ("marker RESTORE_VERIFIED_PENDING_CLEAR", dict(marker=PENDING)),
                  ("metadata corrupt", dict(corrupt=True)),
                  ("snapshot not valid", dict(snapshot_valid=False)),
                  ("journal RAM valid=false but mask/flags/binding good", dict(journal=(False, 7, 0, True))),
                  ("journal RAM with illegal mask 5", dict(journal=(True, 5, 0, True))),
                  ("journal RAM with illegal mask 9", dict(journal=(True, 9, 0, True))),
                  ("journal RAM unbound", dict(journal=(True, 7, 0, False)))):
    kw.setdefault("journal", (True, 7, 0, True))
    st, wg, ng = fw_probe(REAL, SNAP, live_for(states_of_row("IIIO"), SNAP), **kw)
    check(f"[F] {label}: the real classifier refuses SELF_PARTIAL for I I I O (NEITHER gate, no write gate)",
          fw_class(st) == NEITHER and ng and not wg and not st["free_power_live_self_partial"])

# G/H - every position of B3 and B4, three kinds of internal mixture, under the best possible journal.
gh_n, gh_bad = 0, []
for block, base_row in ((B3, "IIIO"), (B4, "IIII")):
    regs = fsp.BLOCK_REGISTERS[block]
    for pos, reg in enumerate(regs):
        for kind in ("original_with_one_foreign", "intended_with_one_original", "original_with_one_intended"):
            live = live_for(states_of_row(base_row), SNAP)
            vec = {r: (SNAP_INT[r] if kind == "intended_with_one_original" else SNAP_ORIG[r]) for r in regs}
            if kind == "original_with_one_foreign":
                vec[reg] = 0x7E7E
            elif kind == "intended_with_one_original":
                vec[reg] = SNAP_ORIG[reg] if SNAP_ORIG[reg] != SNAP_INT[reg] else 0x7E7E
            else:
                vec[reg] = SNAP_INT[reg] if SNAP_INT[reg] != SNAP_ORIG[reg] else 0x7E7E
            live.update(vec)
            gh_n += 1
            st, wg, ng = fw_probe(REAL, SNAP, live, journal=(True, 15, 0, True))
            blocks = fsp.classify_blocks(originals=SNAP_ORIG, intended=SNAP_INT, live=live)
            if not (blocks[block] == X and fw_blocks(st)[block] == X and fw_class(st) == NEITHER and ng and not wg
                    and model(SNAP, live, evidence(SNAP, journal=(True, 15, 0, True))) == NEITHER):
                gh_bad.append((block, reg, kind))
check(f"[G/H] every one of the 12 B3 and 6 B4 positions x 3 internal-mixture kinds ({gh_n} vectors) is X -> "
      "NEITHER in firmware and model, even with a perfect journal (mask 15, bound, not verified)",
      not gh_bad and gh_n == 18 * 3, str(gh_bad[:4]))
for block, row in ((B3, "IIXO"), (B4, "IIIX")):
    for pos in (0, len(fsp.BLOCK_REGISTERS[block]) - 1):
        live = live_for(states_of_row(row.replace("X", "I" if block == B4 else "O")), SNAP)
        reg = fsp.BLOCK_REGISTERS[block][pos]
        live[reg] = 0x7E7E
        bank = make_bank(live)
        run = track(restore(boot_device(nvs_image(SNAP, journal=(15, 0)), bank)), f"internal {block} pos {pos}")
        check(f"[G/H] device: internal {block} mixture at register {reg} -> operator lockout, zero writes",
              run.cls == NEITHER and locked_out_neither(run, bank))

# ===========================================================================
print("")
print("[8] I: attempt-bit proof - every I_ONLY block needs its own bit")
# ===========================================================================
i_n, i_bad = 0, []
for combo in ALL_COMBOS:
    snap, live = scenario(combo)
    if model(snap, live, evidence(snap, journal=(True, 15, 0, True))) != SELF_PARTIAL:
        continue
    for b in [b for b in fsp.BLOCKS if combo[b] == I]:
        for mask in sorted({m for m in (0, 1, 3, 7, 15) if not m & BITS[b]} | {15 & ~BITS[b]}):
            i_n += 1
            ev = evidence(snap, journal=(True, mask, 0, True))
            rule = fsp.classification_rule(combo, ev)
            st, wg, ng = fw_probe(REAL, snap, live, journal=(True, mask, 0, True))
            want_rule = fsp.RULE_ATTEMPT_BIT_MISSING if mask in (0, 1, 3, 7, 15) else fsp.RULE_JOURNAL_INVALID
            if rule != want_rule or fw_class(st) != NEITHER or not ng or wg:
                i_bad.append((row_of(combo), b, mask, rule))
check(f"for every SELF_PARTIAL block state, dropping the bit of ANY I_ONLY block (every valid prefix mask without "
      f"it -> rule 8; mask 15 minus the bit -> non-prefix, rule 6) is refused by model and firmware ({i_n} cases)",
      not i_bad and i_n > 50, str(i_bad[:4]))

# ===========================================================================
print("")
print("[9] J: START_VERIFIED (v1-narrow)")
# ===========================================================================
for row in ("OIII", "OIIO", "OIOO", "IIIO", "IOOO", "OOIO"):
    bank = bank_for_row(row)
    run = track(restore(boot_device(nvs_image(SNAP, journal=(15, VERIFIED)), bank)), f"verified {row}")
    check(f"[J] mask 15 + START_VERIFIED, mixed row {row}: NEITHER -> operator lockout (operator recovery in v1)",
          run.cls == NEITHER and locked_out_neither(run, bank))
run = run_row("IIII", (15, VERIFIED), label="verified IIII")
check("[J] ALL INTENDED + START_VERIFIED is still INTENDED and restores normally (rule 2 precedes the journal rules)",
      run.cls == INTENDED and completed(run))
# A normal verified lease-end restore that is interrupted leaves a VERIFIED mixed state -> lockout (unchanged v1).
lease_end_nvs, lease_end_bank = captures[-1][1], captures[-1][2]
first, results = nested(lease_end_nvs, lease_end_bank, START_ORIG, START_INT, "verified lease-end restore")
mixed_results = [(r, run) for _i, _e, r, _j, run, _d in results if r not in ("IIII", "OOOO")]
check("[J] an interrupted restore of a VERIFIED lease leaves mixed rows that are NEITHER on the next attempt "
      "(operator lockout with the obligation retained - v1-narrow, unchanged from before SG-01)",
      bool(mixed_results) and all(run.cls == NEITHER and run.writes == [] and nvs_operator_needed(run.sim) == 1
                            and nvs_marker(run.sim) == RR for _r, run in mixed_results),
      str([(r, run.cls) for r, run in mixed_results]))

# ===========================================================================
print("")
print("[10] K: marker stale-RAM - journal RAM stays valid after a restore clears the marker; it grants nothing")
# ===========================================================================
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
run = track(restore(dev), "K: SELF_PARTIAL restore")
check("[K] the SELF_PARTIAL restore completes and clears the marker",
      run.cls == SELF_PARTIAL and completed(run))
check("[K] ...and (Phase 1/2 handoff) the journal RAM mirror is STILL valid afterwards - it is never cleared",
      dev.g["free_power_start_journal_valid"] and dev.g["free_power_start_journal_mask"] == 7)
dev.bank = bank_for_row("IIIO")
before_ops = len(dev.modbus_log)
run = track(restore(dev), "K: wrapper after clear")
check("[K] with the obligation cleared the restore wrapper performs no Modbus at all", run.ops == [] and not run.dispatched)
# Force the stale-RAM hazard: an obligation that looks active in every other respect, marker not RESTORE_REQUIRED.
for marker in (CLEAR, PENDING):
    dev.g.update({"free_power_snapshot_valid": True, "free_power_end_epoch": SNAP["end_epoch"],
                  "free_power_marker_state": marker, "free_power_write_failed": False,
                  "free_power_operation_in_progress": False, "manual_write_in_progress": False,
                  "free_power_operator_needed": False})
    bank = dict(dev.bank)
    ex0 = len(dev.modbus_log)
    dev.execute(DISPATCH)
    writes = [a for k, a, _v, _o in dev.modbus_log[ex0:] if k == "write"]
    check(f"[K] stale valid+bound journal RAM, marker {marker}: the real classifier refuses SELF_PARTIAL - "
          "zero writes, NEITHER lockout", not dev.g["free_power_live_self_partial"] and writes == []
          and dev.g["free_power_restore_unexplained_drift"] and dev.bank == bank)

# ===========================================================================
print("")
print("[11] L: SELF_PARTIAL uses the existing restore order and never skips a reg244 gate")
# ===========================================================================
for row, journal in (("IOOO", (1, 0)), ("IIOO", (3, 0)), ("IIIO", (7, 0)), ("IIIO", (15, 0)), ("OIIO", (7, 0)),
                     ("OIOO", (15, 0)), ("BIOB", (3, 0))):
    snap = make_snapshot({B1: True, B4: True}) if "B" in row else SNAP
    run = run_row(row, journal, snap=snap, label=f"L {row}")
    check(f"[L] {row} journal {journal}: SELF_PARTIAL, ops exactly 230x3, 256x24, 244x12, W232, W256, 256x6 readback, "
          "244x1, W268, W230, 230x3, 256x24 - then verified ORIGINAL and cleared",
          run.cls == SELF_PARTIAL and run.op_seq == RESTORE_OPS and completed(run, originals_of(snap)),
          f"cls={run.cls} ops={run.op_seq}")
run = run_row("IIIO", (7, 0), bank=make_bank(live_for(states_of_row("IIIO"), SNAP), reg244=2), label="L 244 mismatch")
check("[L] SELF_PARTIAL + live register 244 != lease context at the pre-write gate: context hold, ZERO writes, "
      "durable lockout, obligation retained",
      run.cls == SELF_PARTIAL and run.writes == [] and run.sim.g["free_power_context_hold"]
      and nvs_operator_needed(run.sim) == 1 and nvs_marker(run.sim) == RR)
run = run_row("IIIO", (7, 0), read_override=lambda a, c, v: [2] if (a, c) == (244, 1) else v, label="L pre-floor")
check("[L] SELF_PARTIAL + register 244 changed before the floors: only 232 and 256-261 written, 268-279/230 "
      "withheld (SOC=100 envelope kept), context hold",
      run.writes == [232, 256] and run.sim.g["free_power_context_hold"] and all(run.sim.bank[268 + i] == 100 for i in range(6))
      and nvs_marker(run.sim) == RR)
unknown = dict(SNAP, reg244_lease_context_plus1=0)
run = run_row("IIIO", (7, 0), snap=unknown, label="L unknown lease")
check("[L] SELF_PARTIAL with an UNKNOWN lease context (plus-one 0, journal bound to it): context hold, zero writes",
      run.cls == SELF_PARTIAL and run.writes == [] and run.sim.g["free_power_context_hold"])

# ===========================================================================
print("")
print("[12] M: restore failure sweep from SELF_PARTIAL - COMMS/backoff, no premature Phase C/D, fresh reclassify")
# ===========================================================================
M_ROWS = [("IOOO", (1, 0)), ("IIOO", (3, 0)), ("IIIO", (7, 0)), ("IIIO", (15, 0)), ("OIIO", (7, 0)), ("OIII", (15, 0))]
m_n, m_bad, m_outcomes = 0, [], {}
for row, journal in M_ROWS:
    for idx, op in enumerate(RESTORE_OPS):
        for outcome in (READ_FAILS if op[0] == "read" else WRITE_FAILS):
            m_n += 1
            dev = boot_device(nvs_image(SNAP, journal=journal), bank_for_row(row))
            r1 = track(restore(dev, fail={idx: outcome}), f"M {row} op{idx} {outcome}")
            g = dev.g
            problems = []
            if r1.cls != (COMMS if idx < 2 else SELF_PARTIAL):
                problems.append(f"attempt 1 classified {r1.cls}")
            if g["free_power_operation_in_progress"] or g["manual_write_in_progress"] or g["free_power_operator_needed"]:
                problems.append("locks held or lockout set")
            if completed(r1):
                # The injected fault was harmless (e.g. an unapplied write of a
                # value that was already ORIGINAL): the final verify of all 20
                # registers passed - the only way the marker may clear.
                if r1.ops[-1][:2] != ("read", 256) or r1.ops[-1][3] != "ok":
                    problems.append("marker cleared without a successful final verify")
                m_outcomes["verified in attempt 1"] = m_outcomes.get("verified in attempt 1", 0) + 1
            else:
                if nvs_marker(dev) != RR or g["free_power_marker_state"] != RR or not g["free_power_snapshot_valid"]:
                    problems.append("marker/obligation changed by a failed attempt")
                comms = g["free_power_comms_restore_attempts"] == 1 and g["free_power_restore_next_attempt_ms"] != 0
                mism = g["free_power_verify_mismatch_count"] == 1 and g["free_power_comms_restore_attempts"] == 0
                if comms == mism:
                    problems.append("neither (or both) of COMMS backoff / verify-mismatch accounting")
                kind = "COMMS backoff" if comms else "verify mismatch"
                m_outcomes[kind] = m_outcomes.get(kind, 0) + 1
                dev.advance(400_000)
                r2 = track(restore(dev), f"M {row} op{idx} {outcome} retry")
                if r2.op_seq[:2] != [("read", 230, 3), ("read", 256, 24)]:
                    problems.append("retry did not start from fresh reads")
                if r2.cls not in (SELF_PARTIAL, ORIGINAL, INTENDED) or not completed(r2):
                    problems.append(f"retry classified {r2.cls} / did not complete")
            if problems:
                m_bad.append((row, idx, op, outcome, problems))
check(f"every single failure at every restore step ({len(RESTORE_OPS)} ops x their failure outcomes) from "
      f"{len(M_ROWS)} SELF_PARTIAL rows ({m_n} runs): attempt 1 keeps the obligation, takes COMMS backoff (or the "
      "verify-mismatch path for an unapplied write), releases its locks; the retry re-reads fresh, reclassifies "
      "and completes", not m_bad and m_n == 6 * (7 * 4 + 4 * 7), f"{len(m_bad)} bad, first {m_bad[:2]}")
print(f"        attempt-1 outcomes: {m_outcomes}")
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
r = track(restore(dev, fail={3: "error"}), "M pin W232 error")
check("[M] pinned: W232 error -> COMMS backoff (attempt counter 1, deadline set); 256-261 is still restored "
      "(the existing unconditional B4 step), the floors are withheld",
      dev.g["free_power_comms_restore_attempts"] == 1 and dev.g["free_power_restore_next_attempt_ms"] != 0
      and r.writes == [232, 256] and all(dev.bank[268 + i] == 100 for i in range(6)))
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
r = track(restore(dev, fail={5: "error"}), "M pin readback error")
check("[M] pinned: 256-261 readback error -> 268-279/230 NOT written, COMMS backoff",
      r.writes == [232, 256] and dev.g["free_power_comms_restore_attempts"] == 1)
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
r = track(restore(dev, fail={7: "ack_not_applied"}), "M pin 268 unapplied")
check("[M] pinned: 268-279 acknowledged but not applied -> final verify mismatch (count 1), no COMMS, no clear",
      dev.g["free_power_verify_mismatch_count"] == 1 and dev.g["free_power_comms_restore_attempts"] == 0
      and nvs_marker(dev) == RR)
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
restore(dev, fail={7: "ack_not_applied"})
dev.advance(400_000)
dev.bank[270] = 0x7E7E  # a third party touches B3 between attempts
r2 = track(restore(dev, fail={}), "M second mismatch")
check("a verify mismatch followed by third-party drift: the next attempt reclassifies from the fresh read "
      "(internal B3 mixture -> NEITHER lockout), it does not reuse the previous SELF_PARTIAL",
      r2.cls == NEITHER and r2.writes == [] and nvs_operator_needed(dev) == 1)
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
restore(dev, fail={7: "ack_not_applied"})
dev.advance(400_000)
restore(dev, fail={7: "ack_not_applied"})
check("two consecutive verify mismatches from SELF_PARTIAL -> the existing durable operator lockout",
      dev.g["free_power_verify_mismatch_count"] == 2 and nvs_operator_needed(dev) == 1 and nvs_marker(dev) == RR)

# ===========================================================================
print("")
print("[13] N: operator lockout - SELF_PARTIAL never bypasses operator_needed")
# ===========================================================================
for row, journal in (("IIIO", (7, 0)), ("IOOO", (1, 0)), ("OIIO", (15, 0))):
    run = run_row(row, journal, operator_needed=1, label=f"N {row}")
    check(f"[N] durable operator lockout + valid journal + {row}: automatic restore performs ZERO Modbus operations",
          run.ops == [] and not run.dispatched and "OPERATOR DECISION REQUIRED" in str(run.sim.ent("free_power_status").state))
dev = boot_device(nvs_image(SNAP, journal=(7, 0), operator_needed=1), bank_for_row("IIIO"))
restore(dev)
dev.g["free_power_operator_retry_pending"] = True  # End Free Power pressed by a human
run = track(restore(dev), "N explicit retry")
check("[N] only an explicit operator retry (End Free Power) re-authorises the attempt; it then restores via SELF_PARTIAL",
      run.cls == SELF_PARTIAL and completed(run))
dev = boot_device(nvs_image(SNAP, journal=(1, 0)), bank_for_row("IIOO"))
restore(dev)
dev.advance(400_000)
run = restore(dev)
check("[N] after a NEITHER lockout, a later automatic call is blocked before any Modbus operation",
      nvs_operator_needed(dev) == 1 and run.ops == [])

# ===========================================================================
print("")
print("[14] O/P: no START resume, ORIGINAL values only, marker clears only after verified ORIGINAL")
# ===========================================================================
check(f"across every device restore run in this file: every restore write carried the snapshot ORIGINAL values, "
      "the TOU ceiling never rose over lowered floors, restore never executed START, never committed the data "
      "record or the journal, never set active_persisted, and never changed the marker while an owned register "
      "was not ORIGINAL", not ALL_VIOLATIONS, f"{len(ALL_VIOLATIONS)}: {ALL_VIOLATIONS[:3]}")
dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"))
run = restore(dev, fail={8: "ack_not_applied"})
check("[P] B2 (230) acknowledged but not applied: the final verify of all 20 registers fails, the marker stays "
      "RESTORE_REQUIRED (no Phase C/D)", nvs_marker(dev) == RR and dev.g["free_power_snapshot_valid"]
      and dev.bank[230] == SNAP_INT[230] and not any(e[0] == "commit" and e[1] == VALID_KEY for e in dev.events))
dispatch_code = fpsim._strip_code(fpsim.script_body(FW_TEXT, DISPATCH))
check("[P] the dispatch still assigns MARKER_CLEAR / MARKER_RESTORE_VERIFIED_PENDING_CLEAR exactly once each "
      "(inside the final verify's `if (ok)`)",
      dispatch_code.count("id(free_power_marker_state) = ecco_durable::MARKER_CLEAR;") == 1
      and dispatch_code.count("id(free_power_marker_state) = ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR;") == 1)
sp_lambda = next(b for k, _g, b in fpsim.flatten(REAL.prefix) if k == "lambda" and fpsim.mentions_journal(b))
check("[O] the classifier lambda performs no Modbus, no durable commit/load, no script execution, and assigns only "
      "free_power_live_self_partial",
      not re.search(r"modbus|commit_record|load_record|\.execute\(", fpsim._strip_code(sp_lambda))
      and set(re.findall(r"id\((\w+)\)\s*=(?!=)", fpsim._strip_code(sp_lambda))) == {"free_power_live_self_partial"})

# ===========================================================================
print("")
print("[15] Q/R/S: Force Restore, Accept Current State, Review, arbitration and containment unchanged")
# ===========================================================================
# FB-T0: the change-scope pins in [15] and [16] are evaluated on the artifacts AS OF chain entry "dump_v2" (main @
# ca7474e): every LATER chain entry is undone by its exact-match reverter first (registry/tests/_scope_chain.py), so a
# later PR's declared deltas never re-hash these pins and an undeclared edit still breaks them. Today nothing follows
# "dump_v2": these are byte-for-byte the live texts.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_FW = ds.load_firmware_text(SCOPE_FW_TEXT)
SCRIPT_IDS = [s["id"] for s in SCOPE_FW["script"]]
# Manual TOU Phase 1 later edited the six apply_manual_slotN scripts and added
# one RAM-only interval; its exact edits are reverted first, so these pins
# still prove byte-identity everywhere else - see _mtou1_scope.py.
PRE_MTOU1_TEXT = mtou1.pre_mtou1_text(SCOPE_FW_TEXT)
PRE_MTOU1_FW = ds.load_firmware_text(PRE_MTOU1_TEXT)
BODIES = {sid: fpsim.script_body(PRE_MTOU1_TEXT, sid) for sid in SCRIPT_IDS}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Change-scope pins: values measured on main @ 695dc18 (before SG-01 Phase 3/4)
# and unchanged by it. Update deliberately if a later change touches these.
PINNED = {
    "free_power_recovery_force_restore_dispatch": "45d3c66f2c7c1d5583ad79525ae88edc783386b1a35ab22cfce0ddae7ecbbe6c",
    "free_power_recovery_force_restore": "47aa3dbdd589da779d9f16ac39da5f08a147b1778785283de9b63d486bce15fa",
    "free_power_recovery_accept_current_state_dispatch": "7c5806c183db5f5996c0cb2af952c923a9e1f7d042a3f7911a31829e38e96342",
    "free_power_recovery_accept_current_state": "5cdc0b358c2d1b547254a0dfe6fbc62a2d8580a8fac14d14ffd4be562fa6faf2",
    "free_power_recovery_review_dispatch": "9d11477280f15afadc0d39b4d7e21faec050773b499ff832932092d0e842c536",
    "free_power_recovery_review": "a1861ea5f21f1bafd78dc06fe55ce01f29ff45fd5fcc616d0cd7c800019dfb21",
    "restore_free_power_snapshot": "ce0425b5c448822a88e99031782916f5d8b0655fa53c85a39eee6e04c304f343",
    "start_free_power_override": "7b05715713a69b2a24566d0ec524968bb9b6c2c39e858775141bd066a4046501",
}
for sid, digest in PINNED.items():
    check(f"[Q/R/S] {sid} is byte-identical to main @ 695dc18", sha(BODIES[sid]) == digest)
# Dump V2 later edited three Dump scripts; they are hashed with exactly those
# edits reverted (_dump_v2_scope.py).
combined = sha("\n".join(f"== {sid}\n{dv2s.pre_dump_v2_script(sid, BODIES[sid])}" for sid in sorted(BODIES)
                          if sid != DISPATCH))
check(f"[S] every one of the other {len(BODIES) - 1} scripts (Force/Accept/Review, Dump incl. #44/#46 containment, "
      "reg244, RTC, manual slots, watchdog helpers) is byte-identical to main @ 695dc18 - only the restore "
      "dispatch changed", combined == "180b2e2c1fb92f0946e63f70328c8928f048859a0c47fd829f1efe73d1195c6c", combined)
check("[S] every interval (watchdog, PR41/S4 arbitration) is unchanged",
      sha(str(PRE_MTOU1_FW.get("interval"))) == "90cbc7673c5afff7d3fd81a534e360d29c8675de69a8d942249e7f0988a29927")
check("[S] on_boot CODE is unchanged (only an explanatory comment in the journal block was updated; SG-06's "
      "and Dump V2's own later edits are reverted first - see _sg06_scope.py / _dump_v2_scope.py)",
      sha(re.sub(r"\s+", " ", fpsim._strip_code(sg06.pre_sg06_boot(dv2s.pre_dump_v2_boot(
          SCOPE_FW["esphome"]["on_boot"]["then"][0]["lambda"])))))
      == "8d9da7b1662cb9e67089ea1ec3d538102e94ddccc746fb9c963626001112854e")
for sid in ("free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state_dispatch",
            "free_power_recovery_review_dispatch"):
    check(f"[Q/R] {sid} consults neither the journal nor SELF_PARTIAL (no new classifier gate)",
          not fpsim.mentions_journal(BODIES[sid]) and not re.search(r"self_?partial", fpsim._strip_code(BODIES[sid]), re.I))
r_n, r_bad = 0, []
for combo in ALL_COMBOS:
    snap, live = scenario(combo)
    for mask in (1, 3, 7, 15):
        if model(snap, live, evidence(snap, journal=(True, mask, 0, True))) != SELF_PARTIAL:
            continue
        r_n += 1
        orig, intd = originals_of(snap), intended_of(snap)
        if (fpre.classify_live_state(originals=orig, intended=intd, live=live) != "NEITHER"
                or not fpre.free_power_residue_registers(originals=orig, intended=intd, live=live)):
            r_bad.append(row_of(combo))
check(f"[R] Accept Current State refuses every SELF_PARTIAL state ({r_n} block-state/mask cases): each is NEITHER "
      "to Accept's classifier and carries Free Power residue, so its (unchanged) residue scan refuses it",
      not r_bad and r_n > 0, str(r_bad[:4]))
accept_code = fpsim._strip_code(BODIES["free_power_recovery_accept_current_state_dispatch"])
check("[R] Accept's residue predicate is still RESIDUE = live == intended && live != original, refusing on any hit",
      "if (owned_live[i] == owned_intended[i] && owned_live[i] != owned_original[i]) {" in accept_code
      and "if (any_residue) {" in accept_code)

# ===========================================================================
print("")
print("[16] T: write / read / durable surface")
# ===========================================================================


def count_actions(node, key) -> int:
    if isinstance(node, dict):
        return sum((1 if k == key else 0) + count_actions(v, key) for k, v in node.items())
    if isinstance(node, list):
        return sum(count_actions(v, key) for v in node)
    return 0


n_w, n_r = count_actions(SCOPE_FW, fpsim.WRITE), count_actions(SCOPE_FW, fpsim.READ)
check("Modbus writes: 52 and reads: 60 - unchanged by Phase 3/4", (n_w, n_r) == (52, 60), f"{n_w}/{n_r}")
check("durable: 55 commit_record, 9 load call sites (6 load_record + SG-06's 3 marker load_record_status), "
      "9 tags - unchanged by Phase 3/4 (Dump V2 later added 2 commits and 1 load - see "
      "test_dump_v2_ownership_evidence.py)",
      (len(re.findall(r"ecco_durable::commit_record\s*\(", SCOPE_FW_TEXT)), len(re.findall(r"ecco_durable::load_record\s*\(", SCOPE_FW_TEXT)),
       len(re.findall(r"ecco_durable::load_record_status\s*\(", SCOPE_FW_TEXT)),
       len(set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", SCOPE_FW_TEXT)))) == (55 + 2, 6 + 1, 3, 9))
dflat = fpsim.flatten(REAL.scripts[DISPATCH]["then"])
check("the dispatch's Modbus actions are unchanged: reads 230x3, 256x24, 244x12, 256x6, 244x1, 230x3, 256x24 and "
      "writes 232, 256, 268, 230 in that order",
      [(k.split(".")[1][:4], b["start_address"], b.get("count")) for k, _g, b in dflat if k in (fpsim.READ, fpsim.WRITE)]
      == [("read", 230, 3), ("read", 256, 24), ("read", 244, 12), ("writ", 232, None), ("writ", 256, None),
          ("read", 256, 6), ("read", 244, 1), ("writ", 268, None), ("writ", 230, None), ("read", 230, 3),
          ("read", 256, 24)])
check("no register-244 writer in the dispatch; its restore write values are the snapshot globals only",
      all(b["start_address"] != 244 for k, _g, b in dflat if k == fpsim.WRITE)
      and all(set(re.findall(r"id\((\w+)\)", b["values"])) <= {f"free_power_snapshot_reg{r}" for r in OWNED}
              for k, _g, b in dflat if k == fpsim.WRITE))
SCOPE_HEADER = chain.CHAIN.as_of(chain.DURABLE_HEADER, "dump_v2", HEADER)
check("header unchanged in schema terms: no SELF_PARTIAL, still exactly 9 current durable tags",
      not re.search(r"self_?partial", SCOPE_HEADER, re.I)
      and len([t for t in re.findall(r"constexpr const char \*([A-Z0-9_]+_TAG) = ", SCOPE_HEADER)]) == 9)

# ===========================================================================
print("")
print("[17] U: mutation sensitivity - each safety rule, broken on purpose, is detected")
# ===========================================================================


def detectors(ctx: FwCtx) -> list[str]:
    """Behavioural checks run against a (possibly mutated) firmware; returns
    the names of the ones that FAIL."""
    failed = []
    _n, bad = equivalence(ctx, ALL_COMBOS[::3] + [states_of_row(r) for r in ("IIIO", "IOOO", "OIIO", "IIOI", "IIII")],
                          [("absent", None), ("valid=false good fields", (False, 15, 0, True)), ("m1", (True, 1, 0, True)),
                           ("m3", (True, 3, 0, True)), ("m7", (True, 7, 0, True)), ("m15", (True, 15, 0, True)),
                           ("m15V", (True, 15, VERIFIED, True)), ("m5", (True, 5, 0, True)),
                           ("m15 unbound", (True, 15, 0, False))],
                          [dict(marker=RR), dict(marker=CLEAR), dict(marker=RR, corrupt=True)], stop_at_first=True)
    if bad:
        failed.append("equivalence")
    for row, j in (("IIIO", (7, 0)), ("IOOO", (1, 0)), ("OIIO", (15, 0))):
        r = run_row(row, j, ctx=ctx, tracked=False)
        if not (r.cls == SELF_PARTIAL and r.op_seq == RESTORE_OPS and completed(r) and not r.violations):
            failed.append(f"legal {row}")
    for row, j in (("IIOO", (1, 0)), ("IIOI", (15, 0)), ("IIXO", (15, 0)), ("OIIO", (15, VERIFIED)), ("IOOO", None)):
        bank = bank_for_row(row)
        r = restore(boot_device(nvs_image(SNAP, journal=j), bank, ctx))
        if not locked_out_neither(r, bank):
            failed.append(f"illegal {row}")
    r = run_row("IIII", None, ctx=ctx, tracked=False)
    if not (r.cls == INTENDED and completed(r)):
        failed.append("all-intended without journal")
    both = make_snapshot({b: True for b in fsp.BLOCKS})
    r = run_row("BBBB", (15, 0), snap=both, ctx=ctx, tracked=False)
    if not (r.writes == [] and completed(r, originals_of(both))):
        failed.append("all-BOTH skip-write")
    r = run_row("IIIO", (7, 0), operator_needed=1, ctx=ctx, tracked=False)
    if r.ops:
        failed.append("operator lockout")
    r = run_row("IIIO", (7, 0), bank=make_bank(live_for(states_of_row("IIIO"), SNAP), reg244=2), ctx=ctx, tracked=False)
    if r.writes:
        failed.append("reg244 pre-write gate")
    r = run_row("IIIO", (7, 0), read_override=lambda a, c, v: [2] if (a, c) == (244, 1) else v, ctx=ctx, tracked=False)
    if r.writes != [232, 256]:
        failed.append("reg244 pre-floor gate")
    for fail in ({5: "error"}, {8: "ack_not_applied"}, {3: "no_response_landed"}):
        dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"), ctx)
        r = restore(dev, fail=fail)
        if nvs_marker(dev) != RR or dev.g["free_power_active_persisted"] or r.violations:
            failed.append(f"failed attempt {fail}")
    dev = boot_device(nvs_image(SNAP, journal=(7, 0)), bank_for_row("IIIO"), ctx)
    restore(dev, fail={3: "error"})
    dev.advance(400_000)
    dev.bank[270] = 0x7E7E
    bank = dict(dev.bank)
    r = restore(dev)
    if r.writes or dev.bank != bank:
        failed.append("stale SELF_PARTIAL flag across attempts")
    return failed


baseline_failed = detectors(REAL)
check("the detector battery passes on the real firmware", baseline_failed == [], str(baseline_failed))


def mutate(text: str, script_id: str | None, edits) -> str:
    """Applies (old, new, expected_count) edits, inside one script's body when
    `script_id` is given. Refuses a no-op mutation."""
    if script_id:
        body = fpsim.script_body(text, script_id)
        start = text.index(body)
        region, pre, post = body, text[:start], text[start + len(body):]
    else:
        region, pre, post = text, "", ""
    for old, new, count in edits:
        found = region.count(old)
        if found != count:
            raise AssertionError(f"mutation anchor {old[:60]!r} found {found}x, expected {count}")
        region = region.replace(old, new)
    return pre + region + post


SP = "          "
MUTANTS = [
    ("remove journal-valid requirement", DISPATCH, [(SP + "if (!id(free_power_start_journal_valid)) return;\n", "", 1)]),
    ("ignore marker RESTORE_REQUIRED requirement", DISPATCH,
     [(SP + "if (id(free_power_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED) return;\n", "", 1)]),
    ("ignore snapshot trust / metadata corruption", DISPATCH,
     [(SP + "if (!id(free_power_snapshot_valid) || id(free_power_recovery_metadata_corrupt)) return;\n", "", 1)]),
    ("remove binding requirement", DISPATCH,
     [("ecco_durable::free_power_start_journal_binding(bound))) return;", "id(free_power_start_journal_binding))) return;", 1)]),
    ("drop attempt-bit test", DISPATCH,
     [(SP + f"if (b{n}_i && !b{n}_o && (attempted & 0x0{bit}) == 0) return;\n", "", 1) for n, bit in ((1, 1), (2, 2), (3, 4), (4, 8))]),
    ("accept X block", DISPATCH,
     [(SP + "if ((!b1_o && !b1_i) || (!b2_o && !b2_i) || (!b3_o && !b3_i) || (!b4_o && !b4_i)) return;\n", "", 1)]),
    ("remove B4->B3 coupling", DISPATCH, [(SP + "if (b4_i && !b4_o && b3_o && !b3_i) return;\n", "", 1)]),
    ("remove START_VERIFIED exclusion", DISPATCH,
     [(SP + "if ((id(free_power_start_journal_flags) & ecco_durable::FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) != 0) return;\n", "", 1)]),
    ("route SELF_PARTIAL to the activation path", DISPATCH,
     [("      # Fail closed if the fresh read itself failed: retain the obligation,",
       "      - if:\n          condition:\n            lambda: 'return id(free_power_live_self_partial);'\n"
       "          then:\n            - script.execute: start_free_power_override\n"
       "      # Fail closed if the fresh read itself failed: retain the obligation,", 1)]),
    ("SELF_PARTIAL restore writes an INTENDED value", DISPATCH,
     [("return std::vector<uint16_t>{id(free_power_snapshot_reg232)};",
       "return std::vector<uint16_t>{(uint16_t)(id(free_power_snapshot_reg232) | 0x0001)};", 1)]),
    ("allow SELF_PARTIAL to set active_persisted", DISPATCH,
     [(SP + "id(free_power_live_self_partial) = true;\n",
       SP + "id(free_power_live_self_partial) = true;\n" + SP + "id(free_power_active_persisted) = true;\n", 1)]),
    ("clear marker before final verify", DISPATCH,
     [(SP + "id(free_power_live_self_partial) = true;\n",
       SP + "id(free_power_live_self_partial) = true;\n" + SP
       + "ecco_durable::ValidMarker early{ecco_durable::VALID_MARKER_MAGIC, ecco_durable::MARKER_CLEAR};\n" + SP
       + "ecco_durable::commit_record(ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), early);\n" + SP
       + "id(free_power_marker_state) = ecco_durable::MARKER_CLEAR;\n", 1)]),
    ("final verify gate always ok", DISPATCH, [("if (ok) {", "if (true) {", 1)]),
    ("allow SELF_PARTIAL to bypass operator_needed", WRAPPER,
     [("if (id(free_power_operator_needed)) {", "if (id(free_power_operator_needed) && !id(free_power_start_journal_valid)) {", 1)]),
    ("bypass reg244 gates", DISPATCH,
     [("id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);",
       "(id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244) || id(free_power_live_self_partial));", 2)]),
    ("ALL INTENDED requires a journal", DISPATCH,
     [("(id(free_power_live_matches_intended) || id(free_power_live_self_partial))",
       "((id(free_power_live_matches_intended) && id(free_power_start_journal_valid)) || id(free_power_live_self_partial))", 1)]),
    ("ORIGINAL precedence lost (write gate ignores the ORIGINAL leg)", DISPATCH,
     [("&& !id(free_power_live_owned_matches) && (id(free_power_live_matches_intended)",
       "&& (id(free_power_live_matches_intended)", 1)]),
    ("NEITHER lockout no longer excludes SELF_PARTIAL", DISPATCH,
     [(" && !id(free_power_live_matches_intended) && !id(free_power_live_self_partial);",
       " && !id(free_power_live_matches_intended);", 1)]),
    ("SELF_PARTIAL flag not reset per attempt", DISPATCH, [(SP + "id(free_power_live_self_partial) = false;\n", "", 2)]),
]
mutation_results = []
for name, sid, edits in MUTANTS:
    try:
        ctx = FwCtx(mutate(FW_TEXT, sid, edits))
        failed = detectors(ctx)
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 - a crash is still a detection, but recorded as such
        failed = [f"crashed: {type(exc).__name__}: {exc}"[:120]]
    mutation_results.append((name, failed))
    check(f"mutant killed: {name}", bool(failed), "survived")
    if failed:
        print(f"        detected by: {', '.join(failed[:4])}")

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All SG-01 Phase 3/4 SELF_PARTIAL checks passed.")
