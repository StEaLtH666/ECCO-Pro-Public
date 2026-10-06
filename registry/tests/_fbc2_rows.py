"""FB-C2 golden rows: the 81-row shadow decision table of S4 section 9 as data.

INDEPENDENCE. Every expectation below is transcribed from the table text (docs/architecture/fallback/design/
S4_domains_decisions_final.md section 9, lines ~955-1037) and, where the table is silent, from S4 8.3 / 3.4 and the FINAL
document sections 6-8. NONE of it was obtained by running registry/failback_shadow.py. The evaluator is only used as the
source of the numeric RS_* / BD_* / PLAN_* / ROW_* names (which equal the S4 8.1 / 8.3 / 3.4 numbers).

Row object (dict):
    n, title, mode (MODE_ACTUAL = the table's 'Plan' column, supervision aware), build() -> ShadowInputs,
    expect: {
      plan, reason, blocking_domain, row (S4 3.4 precedence row, ROW_*),
      fba: (state, result) | None (RAM-only), fba_a: Policy-A result (None = RAM-only),
      pre: 'FP' | 'DUMP' | None, app: 0|1, frames: set of 'F244' 'F256_DOWN' 'F268_279' 'F256_UP',
      hazard: EH_* | None (None = not stated by the table, not checked), alt: plan | None,
      projected_after: plan | None, flags: {ShadowPlan bool flag: value}, masks: {mask name: value},
      dump_detail: K<<4 (S4 8.4) when the table states K, would_write_244: bool (row 10)
    },
    note: how the row was represented where the table cannot be represented 1:1,
    readiness_plan: (rows 1-3) expectation evaluated with MODE_IF_LOST,
    extra: [ {label, build, mode, expect} ] additional evaluations tied to the row's notes.

FB-A column translation (S4 section 9 legend): PREEMPT/0 = (1, 0), LATCHED/n = (3, n), BLOCKED/n = (4, n), RAM = None.
Policy A (legend): every row whose plan comes from L12-L26 -> fba_a = 1 (PREEMPTED_ONLY); every other row equals FB-A col.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import failback_shadow as sh  # noqa: E402
import _fbc2_fixtures as fx  # noqa: E402
from _fbc2_fixtures import apply  # noqa: E402

ACT, LOSTM = sh.MODE_ACTUAL, sh.MODE_IF_LOST
RS = sh.RS
EH_NO, EH_YES, EH_UNK = cap.EH_NO, cap.EH_YES, cap.EH_UNKNOWN

# plan codes (S4 8.1)
NOT_EVAL, NO_ACTION, REFUSE = 0, 1, 2
PRE_DUMP, PRE_FP, W_DUMP, W_FP, W_FLIGHT, W_LIVE = 10, 11, 12, 13, 14, 15
B_META, B_DUR, B_OP, B_PCORR, B_PUNAV, B_SITE, B_CTX, B_OOD, B_NOPROF, B_INVAL = 20, 21, 22, 23, 24, 25, 26, 27, 30, 31
MATCH, APPLY = 40, 41

PREEMPT0 = (1, 0)


def LAT(n):
    return (3, n)


def BLK(n):
    return (4, n)


# precedence row names (S4 3.4)
R = {k: getattr(sh, "ROW_" + k) for k in ("E0", "E1", "S1", "S2", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
                                          "L10", "L12", "L13", "L14", "L15", "L16", "L17", "L18", "L19", "L20", "L21",
                                          "L22", "L23", "L24", "L25", "L26")}


def row(n, title, build, plan, reason, bd, fba, rw, *, pre=None, app=0, frames=(), hazard=None, alt=None,
        projected_after=None, flags=None, masks=None, dump_detail=None, would_write_244=None, pa=False, note="",
        readiness=None, extra=None, mode=ACT):
    """One table row. `pa` = the plan comes from L12-L26 (Policy A result 1)."""
    fba_a = 1 if pa else (None if fba is None else fba[1])
    exp = dict(plan=plan, reason=RS[reason] if isinstance(reason, str) else reason, blocking_domain=bd, row=R[rw], fba=fba,
               fba_a=fba_a, pre=pre, app=app, frames=set(frames), hazard=hazard, alt=alt, projected_after=projected_after,
               flags=flags or {}, masks=masks or {}, dump_detail=dump_detail, would_write_244=would_write_244)
    r = dict(n=n, title=title, mode=mode, build=build, expect=exp, note=note, extra=extra or [])
    if readiness is not None:
        if isinstance(readiness.get("reason"), str):
            readiness = dict(readiness, reason=RS[readiness["reason"]])
        r["readiness_plan"] = readiness
    return r


def ex(label, build, mode, **expect):
    """Extra evaluation attached to a row; only the listed expect keys are checked."""
    if isinstance(expect.get("reason"), str):
        expect["reason"] = RS[expect["reason"]]
    if "row" in expect:
        expect["row"] = R[expect["row"]]
    return dict(label=label, build=build, mode=mode, expect=expect)


def B(*steps):
    """Build function: base() + mutators."""
    return lambda: apply(fx.base(), *steps)


L = fx.lost
BD_NONE, BD_SUP, BD_BOOT, BD_DUMP, BD_FP, BD_R244, BD_BUS, BD_MTOU, BD_FBP, BD_SITE, BD_LIVE = (
    sh.BD_NONE, sh.BD_SUPERVISION, sh.BD_BOOT, sh.BD_DUMP, sh.BD_FP, sh.BD_R244, sh.BD_BUS, sh.BD_MTOU, sh.BD_FBP,
    sh.BD_SITE, sh.BD_LIVE)

# -------------------------------------------------------------------------------------------------------------------
# Shared pieces
# -------------------------------------------------------------------------------------------------------------------
FP_OVERLAY_STEPS = (fx.fp_active, fx.fp_lease_overlay, fx.fp_snapshot_equals_profile)


def dump_lease_overlay(i):
    """Dump lease applied: live 244 = 0 (Allow Export) and 256-261 = the controller ceiling."""
    fx.set_live(i, 244, 0)
    fx.set_live_many(i, range(256, 262), [2000] * 6)


def dump_residue(i, live244):
    fx.set_live(i, 244, live244)
    fx.set_live_many(i, range(256, 262), [2000] * 6)


def bus_busy_owner(i):
    i.lm.g.bus.manual_write_in_progress = True
    i.bus.any_owner_running = True


ROWS = [
    # ------------------------------------------------------------------------------------------------------ 1-7 sup
    row(1, "SUP+ all clear, VALID, match", B(), NO_ACTION, "SUP_STABLE", BD_NONE, None, "S1",
        readiness=dict(plan=MATCH, reason="MATCH_E1_AND_CTX", blocking_domain=BD_NONE, row=R["L25"]),
        note="Readiness (IF_LOST) = WOULD_ALREADY_MATCH is the readiness_plan."),
    row(2, "SUP+ FP active, VALID, overlay", B(*FP_OVERLAY_STEPS), NO_ACTION, "SUP_STABLE", BD_NONE, None, "S1",
        readiness=dict(plan=PRE_FP, reason="FP_ACTIVE", blocking_domain=BD_FP, row=R["L2"], projected_after=MATCH),
        note="Readiness = WOULD_PREEMPT_FREE_POWER; projected_after 'from the FP snapshot' (S4 3.5): the snapshot is "
             "built equal to the profile, so the one-level re-run says WOULD_ALREADY_MATCH (value derived from 3.5, "
             "the table does not state it)."),
    row(3, "SUP+ NOT_CAPTURED", B((fx.profile_not_captured, False)), NO_ACTION, "SUP_STABLE", BD_NONE, None, "S1",
        readiness=dict(plan=B_PUNAV, reason="PROFILE_ABSENT_UNPROVEN", blocking_domain=BD_FBP, row=R["L18"]),
        note="readiness_plan is the unproven variant; the proven variant (BLOCKED_NO_PROFILE) is the extra check.",
        extra=[ex("readiness, NOT_CAPTURED proven", B((fx.profile_not_captured, True)), LOSTM, plan=B_NOPROF,
                  reason="PROFILE_NOT_CAPTURED", blocking_domain=BD_FBP, row="L19")]),
    row(4, "STARTUP (<300 s), FP RR (boot AP->RQ)", B((fx.sup_state, fx.SUP_STARTUP), fx.fp_rr), REFUSE, "SUP_STARTUP",
        BD_SUP, None, "S2"),
    row(5, "SUP- (supervised, not stable)", B((fx.sup_state, fx.SUP_SUPERVISED, False)), REFUSE, "SUP_UNSTABLE", BD_SUP,
        None, "S2"),
    row(6, "SUSPECT", B((fx.sup_state, fx.SUP_SUSPECT)), REFUSE, "SUP_SUSPECT", BD_SUP, None, "S2"),
    row(7, "SUSPECT, FP active, overlay", B((fx.sup_state, fx.SUP_SUSPECT), *FP_OVERLAY_STEPS), REFUSE, "SUP_SUSPECT",
        BD_SUP, None, "S2"),

    # ------------------------------------------------------------------------------------------------ 8-20 live vs VALID
    row(8, "LOST, VALID, match", B(L), MATCH, "MATCH_E1_AND_CTX", BD_NONE, LAT(3), "L25", pa=True,
        flags=dict(durable_leg_projected=True)),
    row(9, "LOST, 256 = 3000 vs 8000", B(L, (fx.set_live, 256, 3000)), APPLY, "E1_DELTA", BD_NONE, LAT(4), "L26", app=1,
        frames={"F256_UP"}, pa=True, masks=dict(e1_delta_mask=1 << 1, ctx_mismatch_mask=0, out_of_domain_mask=0)),
    row(10, "LOST, 244 = 0, rest match", B(L, (fx.set_live, 244, 0)), APPLY, "E1_DELTA", BD_NONE, LAT(4), "L26", app=1,
        frames={"F244"}, hazard=EH_NO, pa=True, would_write_244=True, masks=dict(e1_delta_mask=1 << 0)),
    row(11, "LOST, 268/274 differ", B(L, (fx.set_live, 268, 50), (fx.set_live, 274, 0)), APPLY, "E1_DELTA", BD_NONE,
        LAT(4), "L26", app=1, frames={"F268_279"}, pa=True, masks=dict(e1_delta_mask=(1 << 7) | (1 << 13))),
    row(12, "LOST, 244 = 1", B(L, (fx.set_live, 244, 1)), B_OOD, "LIVE_244_ESSENTIALS", BD_LIVE, BLK(9), "L24", pa=True,
        masks=dict(out_of_domain_mask=1)),
    row(13, "LOST, 274 = 0x0005 (mode General)", B(L, (fx.set_live, 274, 0x0005)), B_OOD, "LIVE_SOURCE_WORD_UNSUPPORTED",
        BD_LIVE, BLK(9), "L24", pa=True, masks=dict(out_of_domain_mask=1 << 13)),
    row(14, "LOST, 256 = 300 W", B(L, (fx.set_live, 256, 300)), B_OOD, "LIVE_POWER_OUT_OF_RANGE", BD_LIVE, BLK(9), "L24",
        pa=True, masks=dict(out_of_domain_mask=1 << 1)),
    row(15, "LOST, 254 slot time edited", B(L, (fx.set_live, 254, 1830), (fx.set_live, 257, 600)), B_CTX, "CTX_SLOT_TIMES",
        BD_LIVE, BLK(8), "L23", pa=True,
        masks=dict(ctx_mismatch_mask=1 << 7, e1_delta_mask=1 << 2),
        note="'E1 delta also reported': a Manual TOU slot edit also changes a power word, so 257 is changed too and the "
             "e1_delta_mask (bit 2) must be non-empty while the plan is the CTX block."),
    row(16, "LOST, 232 bit0 toggled", B(L, (fx.set_live, 232, fx.P232 ^ 1)), B_CTX, "CTX_232_BIT0", BD_LIVE, BLK(8), "L23",
        pa=True, masks=dict(ctx_mismatch_mask=1)),
    row(17, "LOST, 232 bits 1-15 differ only", B(L, (fx.set_live, 232, fx.P232 | 0x0020)), MATCH, "MATCH_E1_AND_CTX",
        BD_NONE, LAT(3), "L25", pa=True, masks=dict(info_mismatch_mask=8, ctx_mismatch_mask=0, e1_delta_mask=0)),
    row(18, "LOST, 243 differs", B(L, (fx.set_live, 243, 0)), B_CTX, "CTX_243", BD_LIVE, BLK(8), "L23", pa=True,
        masks=dict(ctx_mismatch_mask=2)),
    row(19, "LOST, 248 bit0 = 0", B(L, (fx.set_live, 248, 0)), B_CTX, "CTX_248_BIT0", BD_LIVE, BLK(8), "L23", pa=True,
        masks=dict(ctx_mismatch_mask=4)),
    row(20, "LOST, only 230/245/247 differ",
        B(L, (fx.set_live, 230, 190), (fx.set_live, 245, 6000), (fx.set_live, 247, 0)), MATCH, "MATCH_E1_AND_CTX",
        BD_NONE, LAT(3), "L25", pa=True, masks=dict(info_mismatch_mask=7, e1_delta_mask=0, ctx_mismatch_mask=0)),

    # ------------------------------------------------------------------------------------------------ 21-24 live trust
    row(21, "LOST, Block B not updated > 180 s", B(L, fx.cache_stale), W_LIVE, "LIVE_CACHE_STALE", BD_LIVE, PREEMPT0, "L22",
        pa=True),
    row(22, "LOST, polling switched off", B(L, fx.cache_polling_off), W_LIVE, "LIVE_POLLING_OFF", BD_LIVE, PREEMPT0, "L22",
        pa=True),
    row(23, "LOST, FP just cleared, no poll since fence",
        B(L, (lambda i: setattr(i.fp, "used_since_boot", True)), fx.cache_pre_fence), W_LIVE, "LIVE_CACHE_PRE_FENCE",
        BD_LIVE, PREEMPT0, "L22", pa=True,
        note="FP 'just cleared' = clear by marker with used_since_boot (MARKER_CLEAR_RUNTIME); fence 9 > latched dispatch 7."),
    row(24, "LOST, no Block B since boot", B(L, fx.cache_no_block_b_since_boot), W_LIVE, "LIVE_CACHE_INVALID", BD_LIVE,
        PREEMPT0, "L22", pa=True,
        note="Literal: no Block B since boot = cache_valid False, block_b_seq 0, nothing latched. S4 7.6 lists the latch "
             "term FIRST (LIVE_NOT_LATCHED); the shared live_trust (S3 11.5 order) tests cache_valid/block_b_seq first "
             "and says INVALID. The extra check below is the 'latch missing but Block B fine' variant ('also after "
             "FB-C2's first ready tick').",
        extra=[ex("Block B fine, latch missing", B(L, fx.cache_unlatched), ACT, plan=W_LIVE, reason="LIVE_NOT_LATCHED",
                  blocking_domain=BD_LIVE, row="L22")]),

    # ------------------------------------------------------------------------------------------------ 25-32 profile
    row(25, "LOST, NOT_CAPTURED proven (witness hw=0)", B(L, (fx.profile_not_captured, True)), B_NOPROF,
        "PROFILE_NOT_CAPTURED", BD_FBP, LAT(2), "L19", pa=True),
    row(26, "LOST, NOT_CAPTURED unproven", B(L, (fx.profile_not_captured, False)), B_PUNAV, "PROFILE_ABSENT_UNPROVEN",
        BD_FBP, BLK(7), "L18", pa=True),
    row(27, "LOST, INVALIDATED", B(L, fx.profile_invalidated), B_INVAL, "PROFILE_INVALIDATED", BD_FBP, LAT(2), "L20",
        pa=True),
    row(28, "LOST, CORRUPT", B(L, fx.profile_corrupt), B_PCORR, "PROFILE_CORRUPT", BD_FBP, BLK(7), "L16", pa=True),
    row(29, "LOST, CORRUPT_DOMAIN", B(L, fx.profile_corrupt_domain), B_PCORR, "PROFILE_CORRUPT_DOMAIN", BD_FBP, BLK(7),
        "L17", pa=True),
    row(30, "LOST, UNREADABLE", B(L, fx.profile_unreadable), B_PUNAV, "PROFILE_UNREADABLE", BD_FBP, BLK(7), "L14", pa=True),
    row(31, "LOST, SAVE_UNCONFIRMED (prior VALID), match", B(L, fx.profile_save_unconfirmed), B_PUNAV,
        "PROFILE_SAVE_UNCONFIRMED", BD_FBP, BLK(7), "L13", pa=True,
        note="class VALID in the mirror + write_outcome_unknown = the FB-B RAM overlay SAVE_UNCONFIRMED; live == prior profile."),
    row(32, "LOST, PROFILE_LOST", B(L, fx.profile_lost), B_PUNAV, "PROFILE_LOST", BD_FBP, BLK(7), "L15", pa=True),

    # ------------------------------------------------------------------------------------------------ 33-43 FP
    row(33, "LOST, FP active, VALID, overlay", B(L, *FP_OVERLAY_STEPS), PRE_FP, "FP_ACTIVE", BD_FP, PREEMPT0, "L2",
        pre="FP", projected_after=MATCH,
        note="projected_after 'from the FP snapshot vs profile': snapshot == profile, so the re-run is WOULD_ALREADY_MATCH "
             "(derived from S4 3.5; the table does not state the value)."),
    row(34, "LOST, FP active, NOT_CAPTURED unproven, overlay",
        B(L, fx.fp_active, fx.fp_lease_overlay, fx.fp_snapshot_equals_profile, (fx.profile_not_captured, False)), PRE_FP,
        "FP_ACTIVE", BD_FP, PREEMPT0, "L2", pre="FP", projected_after=B_PUNAV,
        note="fp_snapshot built from the golden profile before the NOT_CAPTURED swap; the profile class decides the re-run."),
    row(35, "LOST, FP starting, bus in flight", B(L, fx.fp_starting), PRE_FP, "FP_STARTING", BD_FP, PREEMPT0, "L2", pre="FP"),
    row(36, "LOST, FP RR (expired)", B(L, fx.fp_rr), W_FP, "FP_RESTORE_DUE", BD_FP, PREEMPT0, "L9"),
    row(37, "LOST, FP backoff", B(L, (fx.fp_rr, True)), W_FP, "FP_RESTORE_BACKOFF", BD_FP, PREEMPT0, "L9"),
    row(38, "LOST, FP pending clear", B(L, fx.fp_pc), W_FP, "FP_CLEAR_PENDING", BD_FP, PREEMPT0, "L9"),
    row(39, "LOST, FP operator needed", B(L, fx.fp_on), B_OP, "FP_OPERATOR_NEEDED", BD_FP, BLK(5), "L5"),
    row(40, "LOST, FP MC (cause MALFORMED)", B(L, fx.fp_mc), B_META, "FP_METADATA_CORRUPT", BD_FP, BLK(5), "L3",
        note="'detail cause=2' is not an evaluator input (the cause is not carried), so only the plan/reason are checked."),
    row(41, "LOST, FP UK (cause MARKER_UNREADABLE)", B(L, (fx.fp_mc, True)), B_META, "FP_MARKER_UNREADABLE", BD_FP, BLK(5),
        "L3"),
    row(42, "LOST, FP OIP set, no script, 4 s", B(L, (fx.fp_oip_orphan, 4000)), W_FLIGHT, "FP_OP_FLAG_SETTLING", BD_FP,
        PREEMPT0, "L10"),
    row(43, "LOST, FP OIP set, no script, 15 s", B(L, (fx.fp_oip_orphan, 15000)), W_FLIGHT, "FP_OP_FLAG_STUCK", BD_FP,
        PREEMPT0, "L7"),

    # ------------------------------------------------------------------------------------------------ 44-55 Dump
    row(44, "LOST, Dump active, live 244 = 0, overlay", B(L, fx.dump_active, dump_lease_overlay), PRE_DUMP, "DUMP_ACTIVE",
        BD_DUMP, PREEMPT0, "L1", pre="DUMP", hazard=EH_NO),
    row(45, "LOST, Dump ending, live 244 = 0, bus in flight", B(L, fx.dump_ending, (fx.set_live, 244, 0)), W_DUMP,
        "DUMP_RESTORE_RUNNING", BD_DUMP, PREEMPT0, "L8", hazard=EH_YES,
        extra=[ex("same, after the fence (pre-fence live)", B(L, fx.dump_ending, (fx.set_live, 244, 0), fx.cache_pre_fence),
                  ACT, plan=W_DUMP, reason="DUMP_RESTORE_RUNNING", hazard=EH_UNK)]),
    row(46, "LOST, Dump RR in backoff, live 244 = 0", B(L, (fx.dump_rr, True), (fx.set_live, 244, 0)), W_DUMP,
        "DUMP_RESTORE_BACKOFF", BD_DUMP, PREEMPT0, "L8", hazard=EH_YES),
    row(47, "LOST, Dump ON, live 244 = 0", B(L, fx.dump_on, (fx.set_live, 244, 0)), B_OP,
        "DUMP_OPERATOR_NEEDED_EXPORT_LIVE", BD_DUMP, BLK(5), "L5", hazard=EH_YES),
    row(48, "LOST, Dump ON, live 244 = 2 (256-261 residue)", B(L, fx.dump_on, (dump_residue, 2)), B_OP,
        "DUMP_OPERATOR_NEEDED", BD_DUMP, BLK(5), "L5", hazard=EH_NO),
    row(49, "LOST, Dump ON, live pre-fence", B(L, fx.dump_on, (fx.set_live, 244, 0), fx.cache_pre_fence), B_OP,
        "DUMP_OPERATOR_NEEDED", BD_DUMP, BLK(5), "L5", hazard=EH_UNK),
    row(50, "LOST, Dump ON + Force bypass armed", B(L, fx.dump_on, fx.dump_force_bypass), W_DUMP, "DUMP_FORCE_QUEUED",
        BD_DUMP, PREEMPT0, "L8", flags=dict(dump_force_bypass_armed=True)),
    row(51, "LOST after ESP reboot, Dump RR (lockout not durable), live 244 = 0", B(L, fx.dump_rr, (fx.set_live, 244, 0)),
        W_DUMP, "DUMP_RESTORE_DUE", BD_DUMP, PREEMPT0, "L8", hazard=EH_YES,
        note="'after an ESP reboot' is just a fresh LOST with the stated domain state (RAM-only evaluator, N false)."),
    row(52, "LOST, Dump MC K=4, live 244 = 2", B(L, (fx.dump_mc, 4), (fx.set_live, 244, 2)), B_META,
        "DUMP_METADATA_CORRUPT", BD_DUMP, BLK(5), "L3", hazard=EH_NO, dump_detail=4 << 4),
    row(53, "LOST, Dump MC K=4, live 244 = 0", B(L, (fx.dump_mc, 4), (fx.set_live, 244, 0)), B_META,
        "DUMP_METADATA_CORRUPT", BD_DUMP, BLK(5), "L3", hazard=EH_YES, dump_detail=4 << 4),
    row(54, "LOST, Dump MC K=3, bus in flight", B(L, (fx.dump_mc, 3), (lambda i: (
        setattr(i.lm.g.bus, "dump_operation_in_progress", True), bus_busy_owner(i)))), B_META, "DUMP_METADATA_CORRUPT",
        BD_DUMP, BLK(5), "L3", dump_detail=3 << 4, note="P0 containment running holds O + the lock; the lockout outranks the wait."),
    row(55, "LOST, Dump UK K=8, live 244 = 0", B(L, (fx.dump_mc, 8, True), (fx.set_live, 244, 0)), B_META,
        "DUMP_MARKER_UNREADABLE", BD_DUMP, BLK(5), "L3", hazard=EH_YES, dump_detail=8 << 4),

    # ------------------------------------------------------------------------------------------------ 56-60 R244
    row(56, "LOST, R244 ON (held after a 2->0 test), live 244 = 0", B(L, fx.r244_held, (fx.set_live, 244, 0)), B_OP,
        "R244_HELD", BD_R244, BLK(5), "L5", hazard=EH_YES),
    row(57, "LOST, R244 ON + drift guard", B(L, fx.r244_held, (fx.r244_drift_guard, 0)), B_OP, "R244_HELD_DRIFT_GUARD",
        BD_R244, BLK(5), "L5", note="LAV true, LA = 0, live 244 = 2 (!= LA): the restore would be refused (FW:14511)."),
    row(58, "LOST, R244 pending clear", B(L, fx.r244_pc), B_OP, "R244_CLEAR_PENDING_OPERATOR", BD_R244, BLK(5), "L5"),
    row(59, "LOST, R244 ending, bus in flight", B(L, fx.r244_restore_running), W_FLIGHT, "R244_RESTORE_RUNNING", BD_R244,
        PREEMPT0, "L10"),
    row(60, "LOST, R244 MC", B(L, fx.r244_mc), B_META, "R244_METADATA_CORRUPT", BD_R244, BLK(5), "L3"),

    # ------------------------------------------------------------------------------------------------ 61-68 durable leg
    row(61, "LOST, Dump RAM clear, NVS ghost RR, no FB-B probe this boot, match", B(L), MATCH, "MATCH_E1_AND_CTX",
        BD_NONE, LAT(3), "L25", pa=True, flags=dict(durable_leg_projected=True),
        note="DOCUMENTED BLIND SPOT (S4 2.10): a ghost RR in NVS is invisible to a RAM-only evaluator, so the fixture is "
             "identical to row 8; the table's own expectation is WOULD_ALREADY_MATCH. FB-F's precheck probe (BLOCKED/6) is out of scope."),
    row(62, "LOST, Dump RAM clear, FB-B probe latched ghost RR", B(L, (fx.probe_latch, cap.DOM_DUMP, cap.LATCH_GHOST_RR)),
        B_DUR, "DUMP_MARKER_DIVERGED", BD_DUMP, BLK(6), "L4"),
    row(63, "LOST, FP RAM clear, FB-B probe latched UNREADABLE", B(L, (fx.probe_latch, cap.DOM_FP, cap.LATCH_UNREADABLE)),
        B_DUR, "FP_PROBE_UNREADABLE", BD_FP, BLK(6), "L4"),
    row(64, "LOST, FP: probe 1 CLEAR (latch P), probe 2 ABSENT", B(L, (fx.cabs, "fp")), B_DUR,
        "FP_MARKER_ABSENT_UNPROVEN", BD_FP, BLK(6), "L6",
        note="RECORDED DEVIATION (expectation = what FB-C2 can emit): the table expects FP_MARKER_EVIDENCE_VANISHED. NOT REPRESENTABLE with the shipped inputs: FB-C performs no probe and the shared probe latch "
             "(fallback_capture LATCH_*) has no PRESENT_SEEN (P) bit, so 'probe 1 CLEAR then ABSENT' cannot be encoded. "
             "The closest fixture is FP clear-by-absence (boot ABSENT, unused); the table expects the vanish reason."),
    row(65, "LOST, Dump/FP/R244 all Cabs, match", B(L, (fx.cabs, "dump", "fp", "r244")), B_DUR,
        "DUMP_MARKER_ABSENT_UNPROVEN", BD_DUMP, BLK(6), "L6", alt=MATCH, flags=dict(absence_relied=True)),
    row(66, "LOST, FP stale ON, marker CLEAR at boot",
        B(L, (lambda i: (setattr(i.fp, "retry_on_raw", True), setattr(i.lm.g.fp, "free_power_operator_needed", True)))),
        MATCH, "MATCH_E1_AND_CTX", BD_NONE, LAT(3), "L25", pa=True, flags=dict(fp_stale_operator_needed=True)),
    row(67, "LOST, FP ON, marker ABSENT at boot",
        B(L, (fx.cabs, "fp"), (lambda i: (setattr(i.fp, "retry_on_raw", True),
                                          setattr(i.lm.g.fp, "free_power_operator_needed", True)))),
        B_DUR, "FP_MARKER_LOST", BD_FP, BLK(6), "L4"),
    row(68, "LOST, Dump retry ON raw, marker ABSENT at boot",
        B(L, (fx.cabs, "dump"), (lambda i: setattr(i.dump, "retry_on_raw", True))), B_DUR, "DUMP_MARKER_LOST", BD_DUMP,
        BLK(6), "L4"),

    # ------------------------------------------------------------------------------------------------ 69-72 bus/mtou/site
    row(69, "LOST, MTOU apply in flight", B(L, fx.mtou_running), W_FLIGHT, "MTOU_APPLY_RUNNING", BD_MTOU, PREEMPT0, "L10",
        note="Bus kept idle: the BUS finding precedes MTOU in the tie-break (DUMP->FP->R244->BUS->MTOU), so a real apply "
             "that also holds MWIP would report the lock reason instead; the table row names MTOU."),
    row(70, "LOST, MWIP held, no owner >= 10 s", B(L, (fx.mwip_orphan, 10000)), W_FLIGHT, "LOCK_HELD_NO_KNOWN_OWNER", BD_BUS,
        PREEMPT0, "L7"),
    row(71, "LOST, FP RR, CIP >= 60 s", B(L, fx.fp_rr, (fx.cip_held, 60000)), W_FLIGHT, "RTC_LOCK_STUCK", BD_BUS,
        PREEMPT0, "L7"),
    row(72, "LOST, VALID 256 = 8000, site ceiling 6000 [synthetic]", B(L, (fx.site_ceiling, 6000)), B_SITE,
        "SITE_CEILING_BELOW_PROFILE", BD_SITE, BLK(10), "L21", pa=True),

    # ------------------------------------------------------------------------------------------------ 73-76 episode
    row(73, "SUP- + EP, 256 differs", B((fx.sup_state, fx.SUP_SUPERVISED, False, True), fx.episode_bound_to_current,
                                         (fx.set_live, 256, 3000)), APPLY, "E1_DELTA", BD_NONE, LAT(4), "L26", app=1,
        frames={"F256_UP"}, pa=True, flags=dict(sup_returned_episode_open=True),
        note="reason is E1_DELTA; '+SUP_RETURNED_EPISODE_OPEN' is the sup_returned_episode_open flag (S4 3.4)."),
    row(74, "SUP+ + EP, VALID g4 re-captured after LOST (bound g3), match",
        B((fx.sup_state, fx.SUP_SUPERVISED, True, True),
          (lambda i: (fx.set_profile(i, fd.EPC_VALID, fp.LOAD_OK, fx.make_profile(4), sync_live=True),
                      setattr(i, "ep", sh.EpProf(True, fd.EPC_VALID, 3, fx.make_profile(3)["binding"]))))),
        B_PUNAV, "PROFILE_CHANGED_SINCE_LOST", BD_FBP, BLK(7), "L12", pa=True,
        flags=dict(profile_changed_since_lost=True, sup_returned_episode_open=True)),
    row(75, "SUP+ + EP, VALID captured after an episode that opened NOT_CAPTURED, match",
        B((fx.sup_state, fx.SUP_SUPERVISED, True, True), (lambda i: setattr(i, "ep", sh.EpProf(True, 1, 0, 0)))),
        B_PUNAV, "PROFILE_CHANGED_SINCE_LOST", BD_FBP, BLK(7), "L12", pa=True,
        flags=dict(profile_changed_since_lost=True), note="bound class 1 != current class 5; a 0-sentinel binding would say APPLY."),
    row(76, "LOST after ESP reboot (new episode), FP RR (lease ended at boot)", B(L, fx.fp_rr, fx.episode_bound_to_current),
        W_FP, "FP_RESTORE_DUE", BD_FP, PREEMPT0, "L9", flags=dict(sup_returned_episode_open=False),
        note="'after an ESP reboot' = a fresh LOST + a freshly bound episode (binding re-recorded to the current "
             "profile) with FP RR; state LOST so SUP_RETURNED is not set."),
    row(77, "boot_loaded = 0 (any other state)", B(L, fx.fp_active, fx.boot_not_loaded), NOT_EVAL, "BOOT_NOT_LOADED",
        BD_BOOT, None, "E1", note="FP made ACTIVE only to show that E1 wins over every domain/profile row."),

    # ------------------------------------------------------------------------------------------------ 78-81 combinations
    row(78, "LOST, Dump RR + FP RR", B(L, fx.dump_rr, fx.fp_rr), W_DUMP, "DUMP_RESTORE_DUE", BD_DUMP, PREEMPT0, "L8",
        note="Unreachable on MAIN (dual RR becomes corrupt at boot); pins the DUMP -> FP tie-break."),
    row(79, "LOST, FP RR + R244 ON", B(L, fx.fp_rr, fx.r244_held), B_OP, "R244_HELD", BD_R244, BLK(5), "L5"),
    row(80, "LOST, Dump MC (malformed) + R244 ON (trusted)", B(L, fx.dump_mc, fx.r244_held), B_META, "DUMP_METADATA_CORRUPT",
        BD_DUMP, BLK(5), "L3"),
    row(81, "LOST, Dump MC (malformed) + FP ending (trusted restore running), bus in flight",
        B(L, fx.dump_mc, fx.fp_ending), B_META, "DUMP_METADATA_CORRUPT", BD_DUMP, BLK(5), "L3"),
]

# row 15 helper: the L-name above is "L23" -> "L23" (kept literal for readability of the table transcription)

assert [r["n"] for r in ROWS] == list(range(1, 82)), "ROWS must be exactly rows 1..81"


# -------------------------------------------------------------------------------------------------------------------
# FINAL-document additions (FINAL 4.6 / 8.1 / 8.3), evaluated in addition to the 81 rows. NOT counted in the 81.
# -------------------------------------------------------------------------------------------------------------------
def _not_usable(why):
    def f(i):
        i.profile_why = why
    return f


FINAL_EXTRAS = [
    dict(label="FINAL 8.3: VALID but witness lagging -> BLOCKED_PROFILE_UNAVAILABLE", mode=ACT,
         build=B(L, _not_usable(fd.WHY_WIT_LAGGING)),
         expect=dict(plan=B_PUNAV, reason=RS["PROFILE_NOT_WRITER_USABLE"], blocking_domain=BD_FBP, fba=BLK(7))),
    dict(label="FINAL 8.3: VALID but witness missing -> BLOCKED_PROFILE_UNAVAILABLE", mode=ACT,
         build=B(L, _not_usable(fd.WHY_WIT_MISSING)),
         expect=dict(plan=B_PUNAV, reason=RS["PROFILE_NOT_WRITER_USABLE"], blocking_domain=BD_FBP, fba=BLK(7))),
    dict(label="FINAL 4.6/8.3: PROFILE_STALE -> BLOCKED_PROFILE_UNAVAILABLE (PROFILE_STALE 511)", mode=ACT,
         build=B(L, (lambda i: fx.set_profile(i, fd.EPC_PROFILE_STALE, fp.LOAD_OK, fx.make_profile(7), fd.WHY_MISMATCH))),
         expect=dict(plan=B_PUNAV, reason=RS["PROFILE_STALE"], blocking_domain=BD_FBP, fba=BLK(7))),
]


# -------------------------------------------------------------------------------------------------------------------
# OBSERVATIONS: further expectations taken from S4 sections 2-4 / 7 / 3.4 rationale that no table row pins directly.
# Reported by the runner, NOT part of the 81 and NOT gating the exit code.
# -------------------------------------------------------------------------------------------------------------------
def _set(path, value):
    def f(i):
        o = i
        parts = path.split(".")
        for p in parts[:-1]:
            o = getattr(o, p)
        setattr(o, parts[-1], value)
    return f


def _many(*fs):
    def f(i):
        for g in fs:
            g(i)
    return f


def obs(label, build, expect, mode=ACT, src=""):
    if isinstance(expect.get("reason"), str):
        expect["reason"] = RS[expect["reason"]]
    if "row" in expect:
        expect["row"] = R[expect["row"]]
    return dict(label=label + (f"  [{src}]" if src else ""), build=build, mode=mode, expect=expect)


OBSERVATIONS = [
    obs("polling off AND cache invalid -> LIVE_POLLING_OFF (term order O before I)",
        B(L, fx.cache_polling_off, _set("lm.cache.cache_valid", False)),
        dict(plan=W_LIVE, reason="LIVE_POLLING_OFF"), src="S4 7.6 term order: latch, O, I, S, fence"),
    obs("R244 Apply running: WAIT_WRITE_IN_FLIGHT + projected_after BLOCKED_OPERATOR_NEEDED",
        B(L, _set("lm.g.r244.run_apply", True), _set("lm.g.bus.reg244_apply_in_progress", True), bus_busy_owner),
        dict(plan=W_FLIGHT, reason="R244_APPLY_RUNNING", blocking_domain=BD_R244, row="L10", projected_after=B_OP),
        src="S4 2.6 G2 'projected_after = BLOCKED_OPERATOR_NEEDED' vs S4 3.5 (only L1/L2/L8/L9 re-run)"),
    obs("Dump retry ON raw with marker CLEAR -> dump_stale_operator_needed, non-blocking",
        B(L, _set("dump.retry_on_raw", True)),
        dict(plan=MATCH, flags=dict(dump_stale_operator_needed=True)), src="S4 2.5 D12 (F11.j sets the flag)"),
    obs("FP RR with lease ctx unknown -> fp_ctx_unknown flag", B(L, fx.fp_rr, _set("fp_lease_ctx_unknown", True)),
        dict(plan=W_FP, flags=dict(fp_ctx_unknown=True)), src="S4 2.4 F7"),
    obs("R244 LAV with marker ABSENT -> r244_lav_marker_absent, L6 absence block",
        B(L, (fx.cabs, "r244"), _set("r244x.lav", True)),
        dict(plan=B_DUR, reason="R244_MARKER_ABSENT_UNPROVEN", blocking_domain=BD_R244,
             flags=dict(r244_lav_marker_absent=True, absence_relied=True)), src="S4 2.6 G8"),
    obs("E0: dump_containment_state 9 -> INPUT_INVALID", B(L, _set("lm.g.dump.dump_containment_state", 9)),
        dict(plan=NOT_EVAL, reason="INPUT_INVALID", blocking_domain=BD_BOOT, row="E0", fba=None), src="S4 3.4 E0"),
    obs("Dump O flag, no script, 4 s -> DUMP_OP_FLAG_SETTLING",
        B(L, _set("lm.g.bus.dump_operation_in_progress", True), _set("dump.orphan_ms", 4000)),
        dict(plan=W_FLIGHT, reason="DUMP_OP_FLAG_SETTLING", blocking_domain=BD_DUMP, row="L10"), src="S4 2.5 D5a"),
    obs("Dump O flag, no script, 15 s -> DUMP_OP_FLAG_STUCK (L7)",
        B(L, _set("lm.g.bus.dump_operation_in_progress", True), _set("dump.orphan_ms", 15000)),
        dict(plan=W_FLIGHT, reason="DUMP_OP_FLAG_STUCK", blocking_domain=BD_DUMP, row="L7"), src="S4 2.5 D5b"),
    obs("R244 rAIP flag, no script, 4 s -> R244_OP_FLAG_SETTLING",
        B(L, _set("lm.g.bus.reg244_apply_in_progress", True), _set("r244.orphan_ms", 4000)),
        dict(plan=W_FLIGHT, reason="R244_OP_FLAG_SETTLING", blocking_domain=BD_R244, row="L10"), src="S4 2.6 G4a"),
    obs("R244 rAIP flag, no script, 15 s -> R244_OP_FLAG_STUCK (L7)",
        B(L, _set("lm.g.bus.reg244_apply_in_progress", True), _set("r244.orphan_ms", 15000)),
        dict(plan=W_FLIGHT, reason="R244_OP_FLAG_STUCK", blocking_domain=BD_R244, row="L7"), src="S4 2.6 G4b"),
    obs("FB-B capture holds the lock -> FBB_CAPTURE_RUNNING",
        B(L, _set("lm.g.bus.fallback_profile_capture_dispatch_running", True), bus_busy_owner),
        dict(plan=W_FLIGHT, reason="FBB_CAPTURE_RUNNING", blocking_domain=BD_BUS, row="L10"), src="S4 2.9 B3"),
    obs("RTC correction running (CIP < 60 s) -> RTC_CORRECTION_RUNNING", B(L, (fx.cip_held, 1000)),
        dict(plan=W_FLIGHT, reason="RTC_CORRECTION_RUNNING", blocking_domain=BD_BUS, row="L10"), src="S4 2.9 B4"),
    obs("MWIP with a running owner -> LOCK_HELD_OWNER_RUNNING", B(L, bus_busy_owner),
        dict(plan=W_FLIGHT, reason="LOCK_HELD_OWNER_RUNNING", blocking_domain=BD_BUS, row="L10"), src="S4 2.9 B3"),
    obs("MWIP no owner, 3 s -> LOCK_HELD_SETTLING", B(L, (fx.mwip_orphan, 3000)),
        dict(plan=W_FLIGHT, reason="LOCK_HELD_SETTLING", blocking_domain=BD_BUS, row="L10"), src="S4 2.9 B3"),
    obs("MWIP no owner, 9999 ms still settling (grace is >= 10 s)", B(L, (fx.mwip_orphan, 9999)),
        dict(plan=W_FLIGHT, reason="LOCK_HELD_SETTLING", row="L10"), src="S4 3.7 kOwnerGraceMs"),
    obs("CIP held 59999 ms still running (stuck at 60000)", B(L, (fx.cip_held, 59999)),
        dict(plan=W_FLIGHT, reason="RTC_CORRECTION_RUNNING", row="L10"), src="S4 3.7 kCipStuckMs"),
    obs("live 244 = 3 -> LIVE_244_UNRECOGNISED", B(L, (fx.set_live, 244, 3)),
        dict(plan=B_OOD, reason="LIVE_244_UNRECOGNISED", blocking_domain=BD_LIVE), src="S4 7.4"),
    obs("live 268 = 150 -> LIVE_SOC_OUT_OF_RANGE", B(L, (fx.set_live, 268, 150)),
        dict(plan=B_OOD, reason="LIVE_SOC_OUT_OF_RANGE"), src="S4 7.4"),
    obs("live 244 = 1 and 256 = 300 -> LIVE_MULTIPLE_OUT_OF_DOMAIN", B(L, (fx.set_live, 244, 1), (fx.set_live, 256, 300)),
        dict(plan=B_OOD, reason="LIVE_MULTIPLE_OUT_OF_DOMAIN"), src="S4 7.4"),
    obs("232 bit0 and 243 both differ -> CTX_MULTIPLE", B(L, (fx.set_live, 232, fx.P232 ^ 1), (fx.set_live, 243, 0)),
        dict(plan=B_CTX, reason="CTX_MULTIPLE"), src="S4 7.2"),
    obs("CTX mismatch outranks out-of-domain (L23 before L24)", B(L, (fx.set_live, 243, 0), (fx.set_live, 244, 1)),
        dict(plan=B_CTX, reason="CTX_243", row="L23"), src="S4 3.4 rationale"),
    obs("probe latch ghost PC on FP -> FP_MARKER_DIVERGED", B(L, (fx.probe_latch, cap.DOM_FP, cap.LATCH_GHOST_PC)),
        dict(plan=B_DUR, reason="FP_MARKER_DIVERGED", blocking_domain=BD_FP), src="S4 2.2 / F11.a"),
    obs("probe latch MALFORMED on Dump -> DUMP_PROBE_MALFORMED", B(L, (fx.probe_latch, cap.DOM_DUMP, cap.LATCH_MALFORMED)),
        dict(plan=B_DUR, reason="DUMP_PROBE_MALFORMED", blocking_domain=BD_DUMP), src="S4 2.2 / D12 + F11.c"),
    obs("FP marker boot load WRONG_SIZE without the MC flag -> FP_RAM_INCONSISTENT",
        B(L, _set("lm.g.fp.free_power_marker_boot_load", cap.BOOT_LOAD_WRONG_SIZE)),
        dict(plan=B_DUR, reason="FP_RAM_INCONSISTENT", blocking_domain=BD_FP), src="S4 2.4 F11.0"),
    obs("boot ABSENT but used since boot -> CLEAR (runtime), no R3 block", B(L, (fx.cabs, "fp"), _set("fp.used_since_boot", True)),
        dict(plan=MATCH, flags=dict(absence_relied=False)), src="S4 2.4 F11.i/j"),
    obs("absence_witness true lifts the R3 block", B(L, (fx.cabs, "dump", "fp", "r244"), _set("absence_witness", True)),
        dict(plan=MATCH), src="S4 2.10 R3"),
    obs("only FP Cabs -> FP_MARKER_ABSENT_UNPROVEN", B(L, (fx.cabs, "fp")),
        dict(plan=B_DUR, reason="FP_MARKER_ABSENT_UNPROVEN", blocking_domain=BD_FP, row="L6", alt=MATCH), src="S4 3.4 L6"),
    obs("Dump + R244 Cabs: tie-break DUMP first", B(L, (fx.cabs, "dump", "r244")),
        dict(plan=B_DUR, reason="DUMP_MARKER_ABSENT_UNPROVEN", blocking_domain=BD_DUMP), src="S4 1.5 tie-break"),
    obs("Dump ON, loaded Dump original allowed export, 256-261 unchanged -> EXH NO (D5 exemption)",
        B(L, fx.dump_on, (fx.set_live, 244, 0), _many(
            _set("lm.dump_data_loaded", True), _set("lm.dump_snapshot_reg244", 0),
            _set("lm.dump_snapshot_reg256_261", [3000] * 6),
            lambda i: fx.set_live_many(i, range(256, 262), [3000] * 6))),
        dict(plan=B_OP, reason="DUMP_OPERATOR_NEEDED", blocking_domain=BD_DUMP, hazard=EH_NO), src="S4 4.2 exemption"),
    obs("site ceiling needs no live data (L21 before L22)", B(L, (fx.site_ceiling, 6000), fx.cache_stale),
        dict(plan=B_SITE, reason="SITE_CEILING_BELOW_PROFILE", row="L21"), src="S4 3.4 rationale"),
    obs("L12 CHANGED_SINCE_LOST before L13 SAVE_UNCONFIRMED",
        B(L, fx.profile_save_unconfirmed, _set("sup.episode_open", True),
          _set("ep", sh.EpProf(True, fd.EPC_VALID, 7, fx.GOLD["binding"]))),
        dict(plan=B_PUNAV, reason="PROFILE_CHANGED_SINCE_LOST", row="L12"), src="S4 3.4 rationale"),
    obs("stuck lock precedes the Dump restore wait (L7 before L8)", B(L, fx.dump_rr, (fx.mwip_orphan, 10000)),
        dict(plan=W_FLIGHT, reason="LOCK_HELD_NO_KNOWN_OWNER", blocking_domain=BD_BUS, row="L7"), src="S4 3.4 rationale"),
    obs("operator-needed precedes absence (L5 before L6)", B(L, fx.r244_held, (fx.cabs, "fp")),
        dict(plan=B_OP, reason="R244_HELD", row="L5"), src="S4 3.4 rationale"),
    obs("Dump ACTIVE precedes an FP lockout (L1 before L3)", B(L, fx.dump_active, fx.fp_mc),
        dict(plan=PRE_DUMP, reason="DUMP_ACTIVE", row="L1"), src="S4 3.4 rationale"),
    obs("Dump ACTIVE and FP ACTIVE: DUMP first", B(L, fx.dump_active, fx.fp_active),
        dict(plan=PRE_DUMP, reason="DUMP_ACTIVE", blocking_domain=BD_DUMP), src="S4 1.5 tie-break"),
    obs("FP lockout (L3) precedes a Dump ghost latch (L4)", B(L, fx.fp_mc, (fx.probe_latch, cap.DOM_DUMP, cap.LATCH_GHOST_RR)),
        dict(plan=B_META, reason="FP_METADATA_CORRUPT", blocking_domain=BD_FP, row="L3"), src="S4 3.4 rationale"),
    obs("IF_LOST mode ignores supervision (SUSPECT + all clear -> readiness match)", B((fx.sup_state, fx.SUP_SUSPECT)),
        dict(plan=MATCH, flags=dict(would_refuse_starts=True)), mode=LOSTM, src="S4 3.4 S0"),
    obs("stable supervision outside an episode: would_refuse_starts False", B(),
        dict(plan=NO_ACTION, flags=dict(would_refuse_starts=False)), src="S4 3.4 S0"),
]
