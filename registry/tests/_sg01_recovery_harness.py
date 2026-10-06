"""SG-01 Phase 5 - shared whole-device harness for the Free Power recovery
paths: the automatic restore (SELF_PARTIAL / ORIGINAL / INTENDED / NEITHER),
Review, Force Restore Original and Accept Current State.

Everything here EXECUTES the real firmware source through
registry/tests/_dump_sim.py (parsed ESPHome action trees + a strict
C++-subset transpiler that raises on anything it cannot interpret), against
an in-memory NVS store and inverter register bank. Nothing here performs
real Modbus I/O, touches hardware or needs the ESPHome toolchain.

The scenario/probe helpers are the same shapes
registry/tests/test_sg01_self_partial_phase3_4.py uses (that file is left
unchanged; this module is its reusable counterpart for Phase 5).
"""

from __future__ import annotations

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

FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
HEADER = HEADER_PATH.read_text(encoding="utf-8")
D = ds.Durable

JKEY, DATA_KEY = D.FREE_POWER_START_JOURNAL_TAG, D.FREE_POWER_DATA_TAG
VALID_KEY, RETRY_KEY = D.FREE_POWER_VALID_TAG, D.FREE_POWER_RETRY_TAG
DUMP_DATA_KEY, DUMP_VALID_KEY, DUMP_RETRY_KEY = D.DUMP_TO_GRID_DATA_TAG, D.DUMP_TO_GRID_VALID_TAG, D.DUMP_TO_GRID_RETRY_TAG
RR, CLEAR, PENDING = D.MARKER_RESTORE_REQUIRED, D.MARKER_CLEAR, D.MARKER_RESTORE_VERIFIED_PENDING_CLEAR
START, WRAPPER, DISPATCH = "start_free_power_override", "restore_free_power_snapshot", "restore_free_power_snapshot_dispatch"
REVIEW = "free_power_recovery_review"
FORCE, FORCE_DISPATCH = "free_power_recovery_force_restore", "free_power_recovery_force_restore_dispatch"
ACCEPT, ACCEPT_DISPATCH = "free_power_recovery_accept_current_state", "free_power_recovery_accept_current_state_dispatch"
OWNED = fpre.OWNED_REGISTER_ORDER
B1, B2, B3, B4 = fsp.BLOCKS
O, I, BOTH, X = fsp.O_ONLY, fsp.I_ONLY, fsp.BOTH, fsp.X
BITS = fsp.BLOCK_ATTEMPT_BIT
VERIFIED = jm.JOURNAL_FLAG_START_VERIFIED
COMMS, ORIGINAL, INTENDED, SELF_PARTIAL, NEITHER = fsp.COMMS, fsp.ORIGINAL, fsp.INTENDED, fsp.SELF_PARTIAL, fsp.NEITHER
ROW_LETTER = {O: "O", I: "I", BOTH: "B", X: "X"}
READ_FAILS = ("error", "not_sent", "no_response", "timeout")
WRITE_FAILS = ("error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed", "timeout_lost",
               "ack_not_applied")
END_EPOCH = 1_790_003_600
LEASE = 1
MAX_POWER_W, BATTERY_V = 3000, 52.0

# ---------------------------------------------------------------------------
# Scenario construction (identical shapes to the Phase 3/4 suite)
# ---------------------------------------------------------------------------
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


def self_partial_cases(masks=(1, 3, 7, 15)) -> list[tuple[dict, int]]:
    """Every (block-state combination, journal mask) the model admits as
    SELF_PARTIAL under a valid, bound, non-verified journal."""
    out = []
    for combo in ALL_COMBOS:
        snap, live = scenario(combo)
        for mask in masks:
            if model(snap, live, evidence(snap, journal=(True, mask, 0, True))) == SELF_PARTIAL:
                out.append((combo, mask))
    return out


# ---------------------------------------------------------------------------
# Firmware contexts (the real firmware, or a mutant)
# ---------------------------------------------------------------------------
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
        self.api = {a["action"]: a for a in self.fw["api"]["actions"]}


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
    if not g["free_power_live_read_ok"]:
        return COMMS
    if g["free_power_live_owned_matches"]:
        return ORIGINAL
    if g["free_power_live_matches_intended"]:
        return INTENDED
    return SELF_PARTIAL if g["free_power_live_self_partial"] else NEITHER


# ---------------------------------------------------------------------------
# Whole device: boot from NVS, run the real scripts
# ---------------------------------------------------------------------------
FP_BOOT_START = "// Durable recovery snapshots (Free Power, Register 244) now live in"
FP_BOOT_END = "// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/"


def boot_lambda(fw) -> str:
    return fw["esphome"]["on_boot"]["then"][0]["lambda"]


def fp_boot_block(fw) -> str:
    boot = boot_lambda(fw)
    return boot[boot.index(FP_BOOT_START):boot.index(FP_BOOT_END)]


def env(sim) -> None:
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
        if script_id in (DISPATCH, FORCE_DISPATCH, "free_power_recovery_review_dispatch", ACCEPT_DISPATCH):
            params = {"exception_code": 0x02, **(params or {})}
        return real_execute(script_id, params)

    sim.execute = execute


def rec(kind: str, **fields) -> "ds.Record":
    r = ds.Record(kind)
    for k, v in fields.items():
        setattr(r, k, v)
    return r


SNAP = make_snapshot()
SNAP_ORIG, SNAP_INT = originals_of(SNAP), intended_of(SNAP)


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


def boot_device(nvs: dict, bank: dict, ctx: FwCtx, *, full_boot: bool = False) -> "ds.Sim":
    """`full_boot` runs the WHOLE on_boot lambda (Free Power, reg244, Dump,
    the S4 and Free Power<->Dump arbitration blocks); otherwise only the
    Free Power block (as the Phase 3/4 suite does)."""
    sim = ds.Sim(ctx.fw)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.run_lambda(boot_lambda(ctx.fw) if full_boot else fp_boot_block(ctx.fw))
    env(sim)
    sim.bank = dict(bank)
    return sim


def bank_for_row(row: str, snap: dict = SNAP) -> dict:
    return make_bank(live_for(states_of_row(row), snap))


def nvs_marker(sim) -> int | None:
    m = sim.nvs.get(VALID_KEY)
    return None if m is None else m.state


def nvs_operator_needed(sim) -> int:
    r = sim.nvs.get(RETRY_KEY)
    return 0 if r is None else r.operator_needed


def journal_of(nvs: dict):
    j = nvs.get(JKEY)
    return None if j is None else (j.start_attempted, j.flags)


def all_original(sim, orig) -> bool:
    return all(sim.bank[r] == orig[r] for r in OWNED)


class Run:
    """One call of a real script and what it did."""

    def __init__(self, sim, ops, executed, commits, violations):
        self.sim, self.ops, self.executed, self.commits, self.violations = sim, ops, executed, commits, violations

    @property
    def writes(self):
        return [a for k, a, _v, _o in self.ops if k == "write"]

    @property
    def op_seq(self):
        return [(k, a) if k == "write" else (k, a, len(v)) for k, a, v, _o in self.ops]

    @property
    def dispatched(self):
        return DISPATCH in self.executed

    @property
    def cls(self):
        return dev_class(self.sim.g) if self.dispatched else None


def audited(sim, fn, *, fail=None, read_override=None, hook=None) -> Run:
    """Runs `fn()` (one or more real scripts) and audits it: every write
    carries the snapshot ORIGINAL values, the TOU ceiling never rises over
    lowered SOC floors, no START execution, no data/journal commit, no
    active_persisted set, and any marker change away from RESTORE_REQUIRED
    happens only with every owned register ORIGINAL (Accept's documented
    zero-write resolution excepted - see `allow_accept_clear`)."""
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
        # Checked at EVERY event, not only at the end: a recovery path that
        # sets active_persisted even transiently (and a later clear resets
        # it) must still be caught.
        if not ap_before and g["free_power_active_persisted"] and "active_persisted set by recovery" not in violations:
            violations.append("active_persisted set by recovery")
        if event[0] == "write":
            bank = sim.bank
            ceiling_raised = any(bank.get(256 + i, 0) > snap_vals[256 + i] for i in range(6))
            floors_released = not all(bank.get(268 + i, 0) == 100 for i in range(6))
            if ceiling_raised and floors_released:
                violations.append(f"TOU ceiling above original with SOC floors released after write {event[1]}")
        if event[0] == "commit" and event[1] == VALID_KEY and event[3] and event[2].state != RR:
            accept_running = ACCEPT_DISPATCH in sim.running
            if marker_before == RR and not accept_running and any(sim.bank.get(r) != snap_vals[r] for r in OWNED):
                violations.append("marker left RESTORE_REQUIRED while owned registers are not all ORIGINAL")
        if event[0] == "commit" and event[1] in (DATA_KEY, JKEY):
            violations.append(f"recovery committed {event[1]}")
        if hook:
            hook(event)

    sim.outcome_fn = outcome
    sim.read_override_fn = read_override
    sim.event_hook = audit
    try:
        fn()
    finally:
        sim.event_hook = None
        sim.read_override_fn = None
        sim.outcome_fn = lambda kind, addr, count: "ok"
    ops = sim.modbus_log[log0:]
    for k, a, vals, _o in ops:
        if k == "write" and list(vals) != [snap_vals[a + i] for i in range(len(vals))]:
            violations.append(f"write {a} carried {vals}, not the snapshot ORIGINAL")
    executed = [s for s, _p in sim.executed[ex0:]]
    if START in executed:
        violations.append("start_free_power_override executed during recovery")
    if g["free_power_active_persisted"] and not ap_before and "active_persisted set by recovery" not in violations:
        violations.append("active_persisted set by recovery")
    commits = [e for e in sim.events[ev0:] if e[0] == "commit"]
    return Run(sim, ops, executed, commits, violations)


def restore(sim, **kw) -> Run:
    """One call of the real restore_free_power_snapshot (the automatic path)."""
    return audited(sim, lambda: sim.execute(WRAPPER), **kw)


def api_execute(sim, ctx: FwCtx, action: str, evidence_id: str, confirmation: str) -> None:
    """The real `free_power_recovery_execute` API action (what Home Assistant
    calls), with its three string arguments."""
    body = ctx.api["free_power_recovery_execute"]
    sim.run_actions(body["then"], {"action": ds.CStr(action), "evidence_id": ds.CStr(evidence_id),
                                   "confirmation": ds.CStr(confirmation)})


def review(sim) -> str | None:
    """Runs the real Review; returns the published evidence ID (16 upper-hex)
    or None when no evidence was captured."""
    sim.execute(REVIEW)
    if not sim.g["free_power_recovery_evidence_valid"]:
        return None
    return "%016X" % sim.g["free_power_recovery_evidence_fingerprint"]


def expected_fingerprint(sim) -> int:
    """The evidence fingerprint recomputed OFFLINE (the Python mirror) from
    the device's own durable RAM snapshot and its current register bank."""
    g = sim.g
    return fpre.compute_fingerprint(
        end_epoch=g["free_power_end_epoch"],
        originals={r: g[f"free_power_snapshot_reg{r}"] for r in OWNED},
        reg230_intended=g["free_power_target_reg230"], reg_tou_power_intended=g["free_power_target_tou_power"],
        live_owned={r: sim.bank.get(r, 0) for r in OWNED},
        live_context={r: sim.bank.get(r, 0) for r in fpre.CONTEXT_REGISTER_ORDER})


def operator_action(sim, ctx: FwCtx, action: str, *, phrase: str | None = None, arm: bool = True,
                    evidence_id: str | None = None, **kw) -> tuple[Run, str | None]:
    """Review, then the real API action for Force (`FORCE_RESTORE_ORIGINAL`)
    or Accept (`ACCEPT_CURRENT_STATE`) with the exact confirmation phrase -
    everything an operator does. Returns the audited run of the action (the
    Review itself is not part of it) and the reviewed evidence ID."""
    eid = review(sim)
    sim.ent("free_power_recovery_arm").state = arm
    use_id = evidence_id if evidence_id is not None else (eid or "")
    prefix = {"FORCE_RESTORE_ORIGINAL": "FORCE RESTORE ORIGINAL ", "ACCEPT_CURRENT_STATE": "ACCEPT CURRENT STATE "}[action]
    conf = phrase if phrase is not None else prefix + use_id
    run = audited(sim, lambda: api_execute(sim, ctx, action, use_id, conf), **kw)
    return run, eid


# Force Restore's exact Modbus sequence on a successful attempt (confirm reads
# 230x3, 256x24, 244x12; B1, B4, readback, reg244, B3, B2; final verify).
FORCE_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 244, 12), ("write", 232), ("write", 256),
             ("read", 256, 6), ("read", 244, 1), ("write", 268), ("write", 230), ("read", 230, 3), ("read", 256, 24)]
# The automatic restore's exact sequence (SELF_PARTIAL / INTENDED).
RESTORE_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 244, 12), ("write", 232), ("write", 256),
               ("read", 256, 6), ("read", 244, 1), ("write", 268), ("write", 230), ("read", 230, 3), ("read", 256, 24)]
SKIP_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 230, 3), ("read", 256, 24)]
ACCEPT_OPS = [("read", 230, 3), ("read", 256, 24), ("read", 244, 12)]


def trace(run: Run) -> tuple:
    """Everything externally observable about a recovery run: every Modbus
    op with its values/outcome, every durable commit, the final bank and the
    durable/RAM obligation state."""
    s = run.sim
    return (tuple((k, a, tuple(v), o) for k, a, v, o in run.ops),
            tuple((e[1], e[2]._kind, tuple(getattr(e[2], f) for f in ds._RECORD_FIELDS[e[2]._kind]), e[3])
                  for e in run.commits),
            tuple(sorted(s.bank.items())), nvs_marker(s), nvs_operator_needed(s),
            s.g["free_power_marker_state"], s.g["free_power_snapshot_valid"], s.g["free_power_operator_needed"],
            s.g["free_power_active_persisted"], str(s.ent("free_power_status").state))


def count_actions(node, key) -> int:
    if isinstance(node, dict):
        return sum((1 if k == key else 0) + count_actions(v, key) for k, v in node.items())
    if isinstance(node, list):
        return sum(count_actions(v, key) for v in node)
    return 0


def mutate(text: str, script_id: str | None, edits) -> str:
    """Applies (old, new, expected_count[, occurrence]) edits, inside one
    script's body when `script_id` is given. `occurrence` (1-based) replaces
    only that occurrence. Refuses a no-op or ambiguous mutation."""
    if script_id:
        body = fpsim.script_body(text, script_id)
        start = text.index(body)
        region, pre, post = body, text[:start], text[start + len(body):]
    else:
        region, pre, post = text, "", ""
    for edit in edits:
        old, new, count = edit[:3]
        occurrence = edit[3] if len(edit) > 3 else None
        found = region.count(old)
        if found != count:
            raise AssertionError(f"mutation anchor {old[:60]!r} found {found}x, expected {count}")
        if occurrence is None:
            region = region.replace(old, new)
        else:
            idx = -1
            for _ in range(occurrence):
                idx = region.index(old, idx + 1)
            region = region[:idx] + new + region[idx + len(old):]
    return pre + region + post


def strip_code(code: str) -> str:
    return fpsim._strip_code(code)


def classifier_lambda(ctx: FwCtx) -> str:
    return next(b for k, _g, b in fpsim.flatten(ctx.prefix) if k == "lambda" and fpsim.mentions_journal(b))


def classifier_guards(ctx: FwCtx) -> list[str]:
    """The classifier lambda's statements, whitespace-normalised, in order."""
    code = strip_code(classifier_lambda(ctx))
    return [re.sub(r"\s+", " ", s).strip() for s in re.split(r"(?<=;)\s*\n", code) if s.strip()]
