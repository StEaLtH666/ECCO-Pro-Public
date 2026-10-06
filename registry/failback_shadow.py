"""Python mirror of the FB-C2 pure shadow evaluator (C++-exact).

firmware/include/ecco_failback_shadow.h (namespace ecco_failback_shadow) is the C++ side. FB-C2 is the SHADOW-ONLY evaluator of
the Failback Shadow: every decision is a pure function of plain values, the 1 s shadow tick only gathers RAM values into the POD
structs below, calls evaluate() and publishes text. There is no authority in this module either: no bus, no storage, no clock, no
entity. This module is the independent mirror the offline suites hold the header to:
  - registry/tests/test_failback_shadow_evaluator.py exercises every function here (the 81-row decision table of S4 section 9
    as goldens, every pair of co-firing precedence rows, plan -> FB-A legality, texts at worst case) and makes a real C++
    compiler evaluate the header over the same scenarios, requiring C++ == Python;
  - registry/tests/_fbb_harness.py adapts this module generically as the namespace `ecco_failback_shadow` when it simulates
    the firmware lambdas.

It re-implements NOTHING FB-B1 / FB-B3 already decide: the per-domain classifiers, the live-cache trust rule, the four comparison
masks, the tri-state export hazard and the effective profile class are the registry/fallback_capture.py functions (the mirror of
the ecco_fbcap:: functions the Live Match B10 uses).

NAMING. Every function, constant and struct field has the SAME snake_case name as the C++ one. Structs are dataclasses; std::array
fields are plain lists; TextBuf is fallback_capture.TextBuf.

Pure: stdlib only, no I/O.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
kOwnerGraceMs = 10000
kCipStuckMs = 60000
NONE_U8 = 0xFF

MODE_ACTUAL, MODE_IF_LOST = 0, 1

PLAN_NOT_EVALUATED = 0
PLAN_NO_ACTION = 1
PLAN_WOULD_REFUSE_STARTS = 2
PLAN_WOULD_PREEMPT_DUMP = 10
PLAN_WOULD_PREEMPT_FREE_POWER = 11
PLAN_WAIT_DUMP_RESTORE = 12
PLAN_WAIT_FREE_POWER_RESTORE = 13
PLAN_WAIT_WRITE_IN_FLIGHT = 14
PLAN_WAIT_LIVE_DATA = 15
PLAN_WAIT_MANUAL_TOU_RECOVERY = 16
PLAN_BLOCKED_RECOVERY_METADATA = 20
PLAN_BLOCKED_DURABLE_UNKNOWN = 21
PLAN_BLOCKED_OPERATOR_NEEDED = 22
PLAN_BLOCKED_PROFILE_CORRUPT = 23
PLAN_BLOCKED_PROFILE_UNAVAILABLE = 24
PLAN_BLOCKED_SITE_CEILING = 25
PLAN_BLOCKED_CONTEXT_MISMATCH = 26
PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN = 27
PLAN_BLOCKED_NO_PROFILE = 30
PLAN_BLOCKED_PROFILE_INVALIDATED = 31
PLAN_WOULD_ALREADY_MATCH = 40
PLAN_WOULD_APPLY_PROFILE = 41
PLAN_WOULD_REMAIN_LATCHED = 50

# Every code evaluate() can emit (16 is reserved, 50 belongs to the episode layer).
EMITTED_PLANS = (0, 1, 2, 10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31, 40, 41)
PLAN_NAMES = {
    0: "NOT_EVALUATED", 1: "NO_ACTION", 2: "WOULD_REFUSE_STARTS", 10: "WOULD_PREEMPT_DUMP", 11: "WOULD_PREEMPT_FREE_POWER",
    12: "WAIT_DUMP_RESTORE", 13: "WAIT_FREE_POWER_RESTORE", 14: "WAIT_WRITE_IN_FLIGHT", 15: "WAIT_LIVE_DATA",
    16: "WAIT_MANUAL_TOU_RECOVERY", 20: "BLOCKED_RECOVERY_METADATA", 21: "BLOCKED_DURABLE_UNKNOWN",
    22: "BLOCKED_OPERATOR_NEEDED", 23: "BLOCKED_PROFILE_CORRUPT", 24: "BLOCKED_PROFILE_UNAVAILABLE",
    25: "BLOCKED_SITE_CEILING", 26: "BLOCKED_CONTEXT_MISMATCH", 27: "BLOCKED_LIVE_OUT_OF_DOMAIN", 30: "BLOCKED_NO_PROFILE",
    31: "BLOCKED_PROFILE_INVALIDATED", 40: "WOULD_ALREADY_MATCH", 41: "WOULD_APPLY_PROFILE", 50: "WOULD_REMAIN_LATCHED",
}

(BD_NONE, BD_SUPERVISION, BD_BOOT, BD_DUMP, BD_FP, BD_R244, BD_BUS, BD_MTOU, BD_MTOU_JOURNAL, BD_FBP, BD_SITE,
 BD_LIVE) = range(12)

C0_UNKNOWN, C0_OBLIGATION, C0_CLEAR_PROVEN = 0, 1, 2
(KIND_NONE, KIND_ACTIVE, KIND_STARTING, KIND_RESTORE_REQUIRED, KIND_ENDING, KIND_PENDING_CLEAR, KIND_OPERATOR_NEEDED,
 KIND_IN_FLIGHT) = range(8)
KIND_DURABLE_UNREADABLE, KIND_METADATA_CORRUPT, KIND_BOOT_NOT_LOADED, KIND_DIVERGED, KIND_BUS_OR_LOCK_STUCK, KIND_PROBE_PENDING = (
    16, 17, 19, 20, 21, 23)
(EV_NONE, EV_MARKER_CLEAR_BOOT, EV_MARKER_CLEAR_RUNTIME, EV_MARKER_CLEAR_PROBE, EV_MARKER_ABSENT, EV_NO_DURABLE_RECORD,
 EV_NOT_IMPLEMENTED, EV_IDLE) = range(8)

DS_DUMP, DS_FP, DS_R244, DS_BUS, DS_MTOU, DS_MTOU_JOURNAL, DS_FBP = range(7)
DOM_COUNT = 7

# Reason codes (S4 8.3 plus the two FB-C2 appendices 510 / 511).
RS = dict(
    NONE=0, SUP_STABLE=1, SUP_STARTUP=2, SUP_SUSPECT=3, SUP_UNSTABLE=4, SUP_LOST=5, SUP_RETURNED_EPISODE_OPEN=6,
    IF_LOST_READINESS=7, BOOT_NOT_LOADED=10, INPUT_INVALID=11,
    DUMP_ACTIVE=101, DUMP_STARTING=102, DUMP_RESTORE_DUE=103, DUMP_RESTORE_BACKOFF=104, DUMP_RESTORE_RUNNING=105,
    DUMP_CLEAR_PENDING=106, DUMP_OPERATOR_NEEDED=107, DUMP_OPERATOR_NEEDED_EXPORT_LIVE=108, DUMP_FORCE_QUEUED=109,
    DUMP_METADATA_CORRUPT=110, DUMP_MARKER_UNREADABLE=111, DUMP_MARKER_DIVERGED=112, DUMP_PROBE_UNREADABLE=113,
    DUMP_PROBE_MALFORMED=114, DUMP_MARKER_EVIDENCE_VANISHED=115, DUMP_MARKER_LOST=116, DUMP_MARKER_ABSENT_UNPROVEN=117,
    DUMP_RAM_INCONSISTENT=118, DUMP_OP_FLAG_STUCK=119, DUMP_OP_FLAG_SETTLING=120,
    FP_ACTIVE=201, FP_STARTING=202, FP_RESTORE_DUE=203, FP_RESTORE_BACKOFF=204, FP_RESTORE_RUNNING=205,
    FP_OPERATOR_ACTION_RUNNING=206, FP_CLEAR_PENDING=207, FP_OPERATOR_NEEDED=208, FP_METADATA_CORRUPT=210,
    FP_MARKER_UNREADABLE=211, FP_MARKER_DIVERGED=212, FP_PROBE_UNREADABLE=213, FP_PROBE_MALFORMED=214,
    FP_MARKER_EVIDENCE_VANISHED=215, FP_MARKER_LOST=216, FP_MARKER_ABSENT_UNPROVEN=217, FP_RAM_INCONSISTENT=218,
    FP_OP_FLAG_STUCK=219, FP_OP_FLAG_SETTLING=220,
    R244_HELD=301, R244_HELD_DRIFT_GUARD=302, R244_CLEAR_PENDING_OPERATOR=303, R244_APPLY_RUNNING=304,
    R244_RESTORE_RUNNING=305, R244_METADATA_CORRUPT=307, R244_MARKER_UNREADABLE=308, R244_MARKER_DIVERGED=309,
    R244_PROBE_UNREADABLE=310, R244_PROBE_MALFORMED=311, R244_MARKER_EVIDENCE_VANISHED=312, R244_RAM_INCONSISTENT=313,
    R244_OP_FLAG_STUCK=314, R244_MARKER_ABSENT_UNPROVEN=315, R244_OP_FLAG_SETTLING=316,
    MTOU_APPLY_RUNNING=401, FBB_CAPTURE_RUNNING=402, RTC_CORRECTION_RUNNING=403, LOCK_HELD_OWNER_RUNNING=404,
    LOCK_HELD_NO_KNOWN_OWNER=405, RTC_LOCK_STUCK=406, LOCK_HELD_SETTLING=407, MTOU_JOURNAL_OBLIGATION=410,
    PROFILE_NOT_CAPTURED=501, PROFILE_INVALIDATED=502, PROFILE_CORRUPT=503, PROFILE_CORRUPT_DOMAIN=504,
    PROFILE_UNREADABLE=505, PROFILE_LOST=506, PROFILE_SAVE_UNCONFIRMED=507, PROFILE_CHANGED_SINCE_LOST=508,
    PROFILE_ABSENT_UNPROVEN=509, PROFILE_NOT_WRITER_USABLE=510, PROFILE_STALE=511,
    SITE_CEILING_BELOW_PROFILE=601,
    LIVE_CACHE_INVALID=610, LIVE_CACHE_STALE=611, LIVE_POLLING_OFF=612, LIVE_CACHE_PRE_FENCE=613, LIVE_NOT_LATCHED=614,
    CTX_SLOT_TIMES=620, CTX_243=621, CTX_232_BIT0=622, CTX_248_BIT0=623, CTX_MULTIPLE=624,
    LIVE_244_ESSENTIALS=630, LIVE_244_UNRECOGNISED=631, LIVE_POWER_OUT_OF_RANGE=632, LIVE_SOC_OUT_OF_RANGE=633,
    LIVE_SOURCE_WORD_UNSUPPORTED=634, LIVE_MULTIPLE_OUT_OF_DOMAIN=635,
    MATCH_E1_AND_CTX=701, E1_DELTA=702,
)
for _k, _v in RS.items():  # RS_<NAME> module constants, the C++ spelling
    globals()["RS_" + _k] = _v
assert len(set(RS.values())) == len(RS)

(ROW_NONE, ROW_L1, ROW_L2, ROW_L3, ROW_L4, ROW_L5, ROW_L6, ROW_L7, ROW_L8, ROW_L9, ROW_L10) = range(11)
(ROW_L12, ROW_L13, ROW_L14, ROW_L15, ROW_L16, ROW_L17, ROW_L18, ROW_L19, ROW_L20, ROW_L21, ROW_L22, ROW_L23, ROW_L24, ROW_L25,
 ROW_L26) = range(12, 27)
ROW_L15_STALE, ROW_L20_NOT_USABLE = 28, 29
ROW_E0, ROW_E1, ROW_S1, ROW_S2 = 90, 91, 92, 93

CMP_N, CMP_M, CMP_D, CMP_O = 0, 1, 2, 3
FR_F244, FR_F256_DOWN, FR_F268_279, FR_F256_UP = 1, 2, 4, 8
FBF_NONE, FBF_A, FBF_P = 0, 1, 2
EPK_NONE, EPK_N, EPK_L = 0, 1, 2

# ecco_fallback::Failback* values (FB-A), restated by number and cross-checked against registry/fallback_profile.py by the suite.
FAILBACK_PREEMPT_REQUIRED, FAILBACK_LATCHED_COMPLETE, FAILBACK_BLOCKED = 1, 3, 4
(FAILBACK_RESULT_NONE, FAILBACK_RESULT_PREEMPTED_ONLY, FAILBACK_RESULT_PREEMPTED_NO_PROFILE, FAILBACK_RESULT_ALREADY_AT_PROFILE,
 FAILBACK_RESULT_APPLIED_VERIFIED, FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED, FAILBACK_RESULT_BLOCKED_MARKER_DIVERGENCE,
 FAILBACK_RESULT_BLOCKED_PROFILE_UNAVAILABLE, FAILBACK_RESULT_BLOCKED_CONTEXT_MISMATCH,
 FAILBACK_RESULT_BLOCKED_LIVE_OUT_OF_DOMAIN, FAILBACK_RESULT_BLOCKED_SITE_CEILING,
 FAILBACK_RESULT_BLOCKED_APPLY_FAILED) = range(12)


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------
@dataclass
class SupIn:
    state: int = 0
    p_stable: bool = False
    episode_open: bool = False


@dataclass
class DomExtra:
    backoff: bool = False
    orphan_ms: int = 0
    used_since_boot: bool = False
    retry_on_raw: bool = False
    force_bypass: bool = False


@dataclass
class R244Extra:
    lav: bool = False
    la: int = 0


@dataclass
class BusExtra:
    any_owner_running: bool = False
    mwip_orphan_ms: int = 0
    cip_held_ms: int = 0


@dataclass
class FpSnapshot:
    valid: bool = False
    r232: int = 0
    r256: list = field(default_factory=lambda: [0] * 6)
    r268: list = field(default_factory=lambda: [0] * 6)
    r274: list = field(default_factory=lambda: [0] * 6)


@dataclass
class EpProf:
    bound: bool = False
    cls: int = 0
    gen: int = 0
    binding: int = 0


@dataclass
class ShadowInputs:
    mode: int = MODE_ACTUAL
    sup: SupIn = field(default_factory=SupIn)
    lm: cap.LiveMatchInputs = field(default_factory=cap.LiveMatchInputs)
    profile_why: int = fd.WHY_PROFILE_READ
    not_captured_proven: bool = False
    absence_witness: bool = False
    fp_lease_ctx_unknown: bool = False
    fp: DomExtra = field(default_factory=DomExtra)
    dump: DomExtra = field(default_factory=DomExtra)
    r244: DomExtra = field(default_factory=DomExtra)
    r244x: R244Extra = field(default_factory=R244Extra)
    bus: BusExtra = field(default_factory=BusExtra)
    mtou_journal: int = 0
    ep: EpProf = field(default_factory=EpProf)
    fp_snap: FpSnapshot = field(default_factory=FpSnapshot)


@dataclass
class DomView:
    c0: int = C0_UNKNOWN
    kind: int = KIND_NONE
    evidence: int = EV_NONE
    detail: int = 0


@dataclass
class ShadowPlan:
    plan: int = PLAN_NOT_EVALUATED
    reason: int = RS_NONE
    blocking_domain: int = BD_NONE
    row: int = ROW_NONE
    fba_state: int = NONE_U8
    fba_result: int = NONE_U8
    fba_result_policy_a: int = NONE_U8
    projected_after: int = PLAN_NOT_EVALUATED
    alt_plan_absence_accepted: int = PLAN_NOT_EVALUATED
    export_hazard: int = cap.EH_UNKNOWN
    # FINAL 8.2's obligation term of export_hazard (a FP / Dump / R244 domain not clear and neither ACTIVE nor STARTING); only an
    # evaluated plan sets it. The soak counts export-hazard time only while it holds.
    hazard_obligation: bool = False
    ca: int = cap.CQ_BOOT
    would_refuse_starts: bool = False
    would_preempt_fp: bool = False
    would_preempt_dump: bool = False
    would_apply: bool = False
    would_write_244: bool = False
    absence_relied: bool = False
    durable_leg_projected: bool = False
    fp_stale_operator_needed: bool = False
    dump_stale_operator_needed: bool = False
    r244_lav_marker_absent: bool = False
    fp_ctx_unknown: bool = False
    profile_changed_since_lost: bool = False
    dump_force_bypass_armed: bool = False
    sup_returned_episode_open: bool = False
    masks_valid: bool = False
    e1_delta_mask: int = 0
    out_of_domain_mask: int = 0
    ctx_mismatch_mask: int = 0
    info_mismatch_mask: int = 0
    delta_count: int = NONE_U8
    e1_state: int = CMP_N
    cx_state: int = CMP_N
    in_state: int = CMP_N
    projected_frames: int = 0
    projected_frame_count: int = 0
    dom: list = field(default_factory=lambda: [DomView() for _ in range(DOM_COUNT)])


# ---------------------------------------------------------------------------
# Names and the FB-F latch model
# ---------------------------------------------------------------------------
def plan_name(plan: int) -> str:
    """The Verdict text. TOTAL: 0 and every unknown value render NOT_EVALUATED (fail-closed)."""
    return PLAN_NAMES.get(plan, "NOT_EVALUATED")


def sup_char(state: int) -> str:
    return "U" if state == 0 else "O" if state == 1 else "S" if state == 2 else "L"


def cmp_char(s: int) -> str:
    return "M" if s == CMP_M else "D" if s == CMP_D else "O" if s == CMP_O else "N"


def state_name(phase: int, would_latched: bool, stable: bool) -> str:
    if phase == 1:
        return "SHADOW_EPISODE"
    if phase == 2:
        return "SHADOW_EPISODE_HA_BACK"
    if would_latched:
        return "SHADOW_WOULD_AWAIT_ACK"
    return "SHADOW_WATCH" if not stable else "SHADOW_IDLE"


def kind_for_edge(would_latched: bool) -> int:
    return EPK_L if would_latched else EPK_N


def close_outcome(ep_kind: int, edge_plan: int) -> int:
    return FBF_P if (ep_kind == EPK_N and edge_plan == PLAN_WOULD_ALREADY_MATCH) else FBF_A


def close_latches(fbf: int) -> bool:
    return fbf == FBF_A


@dataclass
class FbaPair:
    state: int = NONE_U8
    result: int = NONE_U8


def fba_for_plan(plan: int) -> FbaPair:
    """Plan -> FB-A (state, result), Policy B (S4 8.1). 0xFF = RAM-only."""
    if plan in (10, 11, 12, 13, 14, 15, 16):
        return FbaPair(FAILBACK_PREEMPT_REQUIRED, FAILBACK_RESULT_NONE)
    if plan in (20, 22):
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED)
    if plan == 21:
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_MARKER_DIVERGENCE)
    if plan in (23, 24):
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_PROFILE_UNAVAILABLE)
    if plan == 25:
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_SITE_CEILING)
    if plan == 26:
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_CONTEXT_MISMATCH)
    if plan == 27:
        return FbaPair(FAILBACK_BLOCKED, FAILBACK_RESULT_BLOCKED_LIVE_OUT_OF_DOMAIN)
    if plan in (30, 31):
        return FbaPair(FAILBACK_LATCHED_COMPLETE, FAILBACK_RESULT_PREEMPTED_NO_PROFILE)
    if plan == 40:
        return FbaPair(FAILBACK_LATCHED_COMPLETE, FAILBACK_RESULT_ALREADY_AT_PROFILE)
    if plan == 41:
        return FbaPair(FAILBACK_LATCHED_COMPLETE, FAILBACK_RESULT_APPLIED_VERIFIED)
    return FbaPair(NONE_U8, NONE_U8)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
@dataclass
class DomState:
    c0: int = C0_UNKNOWN
    kind: int = KIND_NONE
    evidence: int = EV_NONE
    slot_kind: int = cap.OBL_UNSET
    slot_basis: int = cap.BASIS_NONE
    marker_lost: bool = False
    stale_operator_needed: bool = False


@dataclass
class Finding:
    row: int = ROW_NONE
    plan: int = PLAN_NOT_EVALUATED
    reason: int = RS_NONE
    dom: int = BD_NONE


(RK_ACTIVE, RK_STARTING, RK_DUE, RK_BACKOFF, RK_RESTORE_RUNNING, RK_OP_ACTION_RUNNING, RK_CLEAR_PENDING, RK_OPERATOR_NEEDED,
 RK_OPERATOR_NEEDED_EXPORT_LIVE, RK_FORCE_QUEUED, RK_METADATA_CORRUPT, RK_MARKER_UNREADABLE, RK_DIVERGED,
 RK_PROBE_UNREADABLE, RK_PROBE_MALFORMED, RK_LOST, RK_ABSENT_UNPROVEN, RK_RAM_INCONSISTENT, RK_STUCK, RK_SETTLING, RK_HELD,
 RK_HELD_DRIFT_GUARD, RK_CLEAR_PENDING_OPERATOR, RK_APPLY_RUNNING) = range(24)

_DUMP = {RK_ACTIVE: "DUMP_ACTIVE", RK_STARTING: "DUMP_STARTING", RK_DUE: "DUMP_RESTORE_DUE", RK_BACKOFF: "DUMP_RESTORE_BACKOFF",
         RK_RESTORE_RUNNING: "DUMP_RESTORE_RUNNING", RK_CLEAR_PENDING: "DUMP_CLEAR_PENDING",
         RK_OPERATOR_NEEDED: "DUMP_OPERATOR_NEEDED", RK_OPERATOR_NEEDED_EXPORT_LIVE: "DUMP_OPERATOR_NEEDED_EXPORT_LIVE",
         RK_FORCE_QUEUED: "DUMP_FORCE_QUEUED", RK_METADATA_CORRUPT: "DUMP_METADATA_CORRUPT",
         RK_MARKER_UNREADABLE: "DUMP_MARKER_UNREADABLE", RK_DIVERGED: "DUMP_MARKER_DIVERGED",
         RK_PROBE_UNREADABLE: "DUMP_PROBE_UNREADABLE", RK_PROBE_MALFORMED: "DUMP_PROBE_MALFORMED", RK_LOST: "DUMP_MARKER_LOST",
         RK_ABSENT_UNPROVEN: "DUMP_MARKER_ABSENT_UNPROVEN", RK_STUCK: "DUMP_OP_FLAG_STUCK", RK_SETTLING: "DUMP_OP_FLAG_SETTLING"}
_FP = {RK_ACTIVE: "FP_ACTIVE", RK_STARTING: "FP_STARTING", RK_DUE: "FP_RESTORE_DUE", RK_BACKOFF: "FP_RESTORE_BACKOFF",
       RK_RESTORE_RUNNING: "FP_RESTORE_RUNNING", RK_OP_ACTION_RUNNING: "FP_OPERATOR_ACTION_RUNNING",
       RK_CLEAR_PENDING: "FP_CLEAR_PENDING", RK_OPERATOR_NEEDED: "FP_OPERATOR_NEEDED",
       RK_METADATA_CORRUPT: "FP_METADATA_CORRUPT", RK_MARKER_UNREADABLE: "FP_MARKER_UNREADABLE", RK_DIVERGED: "FP_MARKER_DIVERGED",
       RK_PROBE_UNREADABLE: "FP_PROBE_UNREADABLE", RK_PROBE_MALFORMED: "FP_PROBE_MALFORMED", RK_LOST: "FP_MARKER_LOST",
       RK_ABSENT_UNPROVEN: "FP_MARKER_ABSENT_UNPROVEN", RK_STUCK: "FP_OP_FLAG_STUCK", RK_SETTLING: "FP_OP_FLAG_SETTLING"}
_R244 = {RK_HELD: "R244_HELD", RK_HELD_DRIFT_GUARD: "R244_HELD_DRIFT_GUARD",
         RK_CLEAR_PENDING_OPERATOR: "R244_CLEAR_PENDING_OPERATOR", RK_APPLY_RUNNING: "R244_APPLY_RUNNING",
         RK_RESTORE_RUNNING: "R244_RESTORE_RUNNING", RK_METADATA_CORRUPT: "R244_METADATA_CORRUPT",
         RK_MARKER_UNREADABLE: "R244_MARKER_UNREADABLE", RK_DIVERGED: "R244_MARKER_DIVERGED",
         RK_PROBE_UNREADABLE: "R244_PROBE_UNREADABLE", RK_PROBE_MALFORMED: "R244_PROBE_MALFORMED",
         RK_ABSENT_UNPROVEN: "R244_MARKER_ABSENT_UNPROVEN", RK_STUCK: "R244_OP_FLAG_STUCK", RK_SETTLING: "R244_OP_FLAG_SETTLING"}


def dom_reason(dom: int, k: int) -> int:
    table, default = ((_DUMP, "DUMP_RAM_INCONSISTENT") if dom == BD_DUMP else (_FP, "FP_RAM_INCONSISTENT") if dom == BD_FP
                      else (_R244, "R244_RAM_INCONSISTENT"))
    return RS[table.get(k, default)]


def load_in_range(load: int) -> bool:
    return load <= cap.BOOT_LOAD_READ_ERROR or load == cap.BOOT_LOAD_NOT_LOADED


def inputs_valid(i: ShadowInputs) -> bool:
    g = i.lm.g
    return (i.mode <= MODE_IF_LOST and i.sup.state <= 3 and g.fp.free_power_marker_state <= cap.MARKER_STATE_PENDING_CLEAR
            and g.dump.dump_marker_state <= cap.MARKER_STATE_PENDING_CLEAR
            and g.r244.reg244_marker_state <= cap.MARKER_STATE_PENDING_CLEAR and g.dump.dump_containment_state <= 8
            and i.lm.cls <= fd.EPC_PROFILE_STALE and i.profile_why <= fd.WHY_LOST_WIT_CORRUPT and i.mtou_journal == 0
            and load_in_range(g.fp.free_power_marker_boot_load) and load_in_range(g.dump.dump_marker_boot_load)
            and load_in_range(g.r244.reg244_marker_boot_load))


def popcount32(v: int) -> int:
    return bin(v & 0xFFFFFFFF).count("1")


_KIND_OF_SLOT = {
    cap.OBL_ACTIVE: KIND_ACTIVE, cap.OBL_STARTING: KIND_STARTING, cap.OBL_RESTORE_REQUIRED: KIND_RESTORE_REQUIRED,
    cap.OBL_PENDING_CLEAR: KIND_PENDING_CLEAR, cap.OBL_ENDING: KIND_ENDING, cap.OBL_OPERATOR_NEEDED: KIND_OPERATOR_NEEDED,
    cap.UNK_DURABLE_UNREADABLE: KIND_DURABLE_UNREADABLE, cap.UNK_METADATA_CORRUPT: KIND_METADATA_CORRUPT,
    cap.UNK_BOOT_NOT_LOADED: KIND_BOOT_NOT_LOADED, cap.UNK_DIVERGED: KIND_DIVERGED,
    cap.UNK_BUS_OR_LOCK_STUCK: KIND_BUS_OR_LOCK_STUCK,
}


def kind_of_slot(slot_kind: int) -> int:
    return _KIND_OF_SLOT.get(slot_kind, KIND_NONE)


def domain_state(slot: cap.SlotClass, boot_load: int, x: DomExtra, force_clear: bool) -> DomState:
    s = DomState(slot_kind=slot.kind, slot_basis=slot.basis)
    if force_clear:
        s.c0, s.kind, s.evidence = C0_CLEAR_PROVEN, KIND_NONE, EV_MARKER_CLEAR_RUNTIME
        return s
    if slot.kind == cap.UNK_NOT_PROBED:
        absent_now = boot_load == cap.BOOT_LOAD_ABSENT and not x.used_since_boot
        if absent_now and x.retry_on_raw:
            s.c0, s.kind, s.marker_lost = C0_UNKNOWN, KIND_DIVERGED, True
            return s
        s.c0, s.kind = C0_CLEAR_PROVEN, KIND_NONE
        s.evidence = (EV_MARKER_ABSENT if absent_now else EV_MARKER_CLEAR_BOOT if boot_load == cap.BOOT_LOAD_OK
                      else EV_MARKER_CLEAR_RUNTIME)
        s.stale_operator_needed = bool(x.retry_on_raw and not absent_now)
        return s
    s.kind = kind_of_slot(slot.kind)
    s.c0 = C0_UNKNOWN if s.kind >= KIND_DURABLE_UNREADABLE else C0_OBLIGATION
    if slot.kind == cap.UNK_BUS_OR_LOCK_STUCK and slot.basis == cap.BASIS_OP_FLAG_UNATTRIBUTED:
        s.c0 = C0_OBLIGATION
        s.kind = KIND_BUS_OR_LOCK_STUCK if x.orphan_ms >= kOwnerGraceMs else KIND_IN_FLIGHT
        if s.kind == KIND_BUS_OR_LOCK_STUCK:
            s.c0 = C0_UNKNOWN
    return s


def lease_finding(dom: int, s: DomState, i: ShadowInputs, hazard_yes: bool, r244_drift: bool, skip_l6: bool) -> Finding:
    f = Finding(dom=dom)
    is_dump, is_fp = dom == BD_DUMP, dom == BD_FP
    if s.c0 == C0_CLEAR_PROVEN:
        if s.evidence == EV_MARKER_ABSENT and not i.absence_witness and not skip_l6:
            f.row, f.plan, f.reason = ROW_L6, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_ABSENT_UNPROVEN)
        return f
    if s.marker_lost:
        f.row, f.plan, f.reason = ROW_L4, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_LOST)
        return f
    k = s.kind
    if k in (KIND_ACTIVE, KIND_STARTING):
        if is_dump or is_fp:
            f.row = ROW_L1 if is_dump else ROW_L2
            f.plan = PLAN_WOULD_PREEMPT_DUMP if is_dump else PLAN_WOULD_PREEMPT_FREE_POWER
            f.reason = dom_reason(dom, RK_ACTIVE if k == KIND_ACTIVE else RK_STARTING)
        else:
            f.row, f.plan, f.reason = ROW_L10, PLAN_WAIT_WRITE_IN_FLIGHT, RS_R244_APPLY_RUNNING
    elif k == KIND_ENDING:
        if dom == BD_R244:
            f.row, f.plan, f.reason = ROW_L10, PLAN_WAIT_WRITE_IN_FLIGHT, RS_R244_RESTORE_RUNNING
        else:
            f.row = ROW_L8 if is_dump else ROW_L9
            f.plan = PLAN_WAIT_DUMP_RESTORE if is_dump else PLAN_WAIT_FREE_POWER_RESTORE
            f.reason = dom_reason(dom, RK_OP_ACTION_RUNNING if s.slot_basis == cap.BASIS_OPERATOR_ACTION_RUNNING
                                  else RK_RESTORE_RUNNING)
    elif k == KIND_RESTORE_REQUIRED:
        f.row = ROW_L8 if is_dump else ROW_L9
        f.plan = PLAN_WAIT_DUMP_RESTORE if is_dump else PLAN_WAIT_FREE_POWER_RESTORE
        f.reason = dom_reason(dom, RK_BACKOFF if (i.dump.backoff if is_dump else i.fp.backoff) else RK_DUE)
    elif k == KIND_PENDING_CLEAR:
        if dom == BD_R244:
            f.row, f.plan, f.reason = ROW_L5, PLAN_BLOCKED_OPERATOR_NEEDED, RS_R244_CLEAR_PENDING_OPERATOR
        else:
            f.row = ROW_L8 if is_dump else ROW_L9
            f.plan = PLAN_WAIT_DUMP_RESTORE if is_dump else PLAN_WAIT_FREE_POWER_RESTORE
            f.reason = dom_reason(dom, RK_CLEAR_PENDING)
    elif k == KIND_OPERATOR_NEEDED:
        if is_dump and i.dump.force_bypass:
            f.row, f.plan, f.reason = ROW_L8, PLAN_WAIT_DUMP_RESTORE, RS_DUMP_FORCE_QUEUED
        else:
            f.row, f.plan = ROW_L5, PLAN_BLOCKED_OPERATOR_NEEDED
            if dom == BD_R244:
                f.reason = RS_R244_HELD_DRIFT_GUARD if r244_drift else RS_R244_HELD
            elif is_dump:
                f.reason = RS_DUMP_OPERATOR_NEEDED_EXPORT_LIVE if hazard_yes else RS_DUMP_OPERATOR_NEEDED
            else:
                f.reason = RS_FP_OPERATOR_NEEDED
    elif k == KIND_IN_FLIGHT:
        f.row, f.plan, f.reason = ROW_L10, PLAN_WAIT_WRITE_IN_FLIGHT, dom_reason(dom, RK_SETTLING)
    elif k == KIND_BUS_OR_LOCK_STUCK:
        f.row, f.plan, f.reason = ROW_L7, PLAN_WAIT_WRITE_IN_FLIGHT, dom_reason(dom, RK_STUCK)
    elif k == KIND_DURABLE_UNREADABLE:
        if s.slot_basis == cap.BASIS_BOOT_READ_ERROR:
            f.row, f.plan, f.reason = ROW_L3, PLAN_BLOCKED_RECOVERY_METADATA, dom_reason(dom, RK_MARKER_UNREADABLE)
        else:
            f.row, f.plan, f.reason = ROW_L4, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_PROBE_UNREADABLE)
    elif k == KIND_METADATA_CORRUPT:
        if s.slot_basis == cap.BASIS_BOOT_LOCKOUT:
            f.row, f.plan, f.reason = ROW_L3, PLAN_BLOCKED_RECOVERY_METADATA, dom_reason(dom, RK_METADATA_CORRUPT)
        else:
            f.row, f.plan, f.reason = ROW_L4, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_PROBE_MALFORMED)
    elif k == KIND_DIVERGED:
        ghost = s.slot_basis in (cap.BASIS_GHOST_RR, cap.BASIS_GHOST_PC)
        f.row, f.plan, f.reason = ROW_L4, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_DIVERGED if ghost else RK_RAM_INCONSISTENT)
    else:  # KIND_BOOT_NOT_LOADED with boot_loaded true: the boot-load retention is missing for this domain
        f.row, f.plan, f.reason = ROW_L4, PLAN_BLOCKED_DURABLE_UNKNOWN, dom_reason(dom, RK_RAM_INCONSISTENT)
    return f


def bus_finding(i: ShadowInputs, bus: cap.SlotClass) -> Finding:
    f = Finding(dom=BD_BUS)
    b = i.lm.g.bus
    orphan = bool(b.manual_write_in_progress and not i.bus.any_owner_running and i.bus.mwip_orphan_ms >= kOwnerGraceMs)
    cip_stuck = bool(b.correction_in_progress and i.bus.cip_held_ms >= kCipStuckMs)
    if cip_stuck or orphan or bus.kind == cap.UNK_BUS_OR_LOCK_STUCK:
        f.row, f.plan = ROW_L7, PLAN_WAIT_WRITE_IN_FLIGHT
        f.reason = RS_RTC_LOCK_STUCK if cip_stuck else RS_LOCK_HELD_NO_KNOWN_OWNER
        return f
    if bus.kind == cap.BUS_BUSY:
        f.row, f.plan = ROW_L10, PLAN_WAIT_WRITE_IN_FLIGHT
        if b.fallback_profile_capture_dispatch_running or b.fallback_profile_op_in_progress:
            f.reason = RS_FBB_CAPTURE_RUNNING
        elif b.correction_in_progress:
            f.reason = RS_RTC_CORRECTION_RUNNING
        elif b.manual_write_in_progress and i.bus.any_owner_running:
            f.reason = RS_LOCK_HELD_OWNER_RUNNING
        else:
            f.reason = RS_LOCK_HELD_SETTLING
    return f


def mk(row: int, plan: int, reason: int, dom: int) -> Finding:
    return Finding(row=row, plan=plan, reason=reason, dom=dom)


def ctx_reason(m: int) -> int:
    cats = (1 if m & 0x001 else 0) + (1 if m & 0x002 else 0) + (1 if m & 0x004 else 0) + (1 if m & 0x1F8 else 0)
    if cats > 1:
        return RS_CTX_MULTIPLE
    return RS_CTX_232_BIT0 if m & 0x001 else RS_CTX_243 if m & 0x002 else RS_CTX_248_BIT0 if m & 0x004 else RS_CTX_SLOT_TIMES


def ood_reason(m: int, live244: int) -> int:
    cats = (1 if m & 0x00001 else 0) + (1 if m & 0x0007E else 0) + (1 if m & 0x01F80 else 0) + (1 if m & 0x7E000 else 0)
    if cats > 1:
        return RS_LIVE_MULTIPLE_OUT_OF_DOMAIN
    if m & 0x00001:
        return RS_LIVE_244_ESSENTIALS if live244 == 1 else RS_LIVE_244_UNRECOGNISED
    return RS_LIVE_POWER_OUT_OF_RANGE if m & 0x0007E else RS_LIVE_SOC_OUT_OF_RANGE if m & 0x01F80 else RS_LIVE_SOURCE_WORD_UNSUPPORTED


def meaningful_class(eff: int) -> bool:
    return eff in (fd.EPC_VALID, fd.EPC_INVALIDATED, fd.EPC_CORRUPT_DOMAIN)


def live_reason(ca: int) -> int:
    return (RS_LIVE_CACHE_INVALID if ca == cap.CQ_INVALID else RS_LIVE_POLLING_OFF if ca == cap.CQ_POLL_OFF
            else RS_LIVE_CACHE_STALE if ca == cap.CQ_STALE else RS_LIVE_CACHE_PRE_FENCE if ca == cap.CQ_PRE_FENCE
            else RS_LIVE_NOT_LATCHED)


def pick_row(findings: list, row: int) -> Finding:
    for f in findings:
        if f.row == row:
            return f
    return Finding()


def projected_live(i: ShadowInputs, clear_dom: int, use_snapshot: bool) -> list:
    w = list(i.lm.live)
    if not use_snapshot:
        return w
    if clear_dom == BD_FP:
        w[19] = i.fp_snap.r232
        for k in range(6):
            w[1 + k], w[7 + k], w[13 + k] = i.fp_snap.r256[k], i.fp_snap.r268[k], i.fp_snap.r274[k]
    elif clear_dom == BD_DUMP:
        w[0] = i.lm.dump_snapshot_reg244
        for k in range(6):
            w[1 + k] = i.lm.dump_snapshot_reg256_261[k]
    return w


def _prof(p) -> dict:
    return cap._prof(p) if p is not None else fp.blank_profile()


def eval_core(i: ShadowInputs, skip_l6: bool, clear_dom: int, use_snapshot: bool, depth: int) -> ShadowPlan:
    r = ShadowPlan()
    g = i.lm.g
    r.would_refuse_starts = bool((not i.sup.p_stable) or i.sup.episode_open or i.mode == MODE_IF_LOST)
    r.sup_returned_episode_open = bool(i.sup.episode_open and i.sup.state != 3)
    if not inputs_valid(i):
        r.row, r.reason, r.blocking_domain = ROW_E0, RS_INPUT_INVALID, BD_BOOT
        return r
    if not g.boot_loaded:
        r.row, r.reason, r.blocking_domain = ROW_E1, RS_BOOT_NOT_LOADED, BD_BOOT
        return r

    sl_fp, sl_dump = cap.classify_fp(g, cap.PROBE_NONE), cap.classify_dump(g, cap.PROBE_NONE)
    sl_r244, sl_bus = cap.classify_r244(g, cap.PROBE_NONE), cap.classify_bus(g)
    ds_dump = domain_state(sl_dump, g.dump.dump_marker_boot_load, i.dump, clear_dom == BD_DUMP)
    ds_fp = domain_state(sl_fp, g.fp.free_power_marker_boot_load, i.fp, clear_dom == BD_FP)
    ds_r244 = domain_state(sl_r244, g.r244.reg244_marker_boot_load, i.r244, clear_dom == BD_R244)

    ca = cap.live_trust(i.lm.cache, g.boot_loaded)
    trusted = ca == cap.CQ_FRESH
    r.ca = ca
    eff = cap.live_effective_class(i.lm.cls, i.lm.write_outcome_unknown, i.lm.read_anomaly)
    live = projected_live(i, clear_dom, use_snapshot)
    prof = _prof(i.lm.p)
    prof_valid_rec = fp.classify_profile(i.lm.p_load, prof) == fp.PROFILE_VALID
    r.masks_valid = bool(trusted and eff in (fd.EPC_VALID, fd.EPC_CORRUPT_DOMAIN))
    stored = cap.words_of(prof)
    if r.masks_valid:
        r.e1_delta_mask = cap.e1_delta_mask(live, stored)
        r.ctx_mismatch_mask = cap.ctx_mismatch_mask(live, stored)
        r.out_of_domain_mask = cap.out_of_domain_mask(live)
        r.info_mismatch_mask = cap.info_mismatch_mask(live, stored)
        r.delta_count = popcount32(r.e1_delta_mask)

    def bad(d: DomState) -> bool:
        return d.c0 != C0_CLEAR_PROVEN and d.kind not in (KIND_ACTIVE, KIND_STARTING)

    bad_domain = bad(ds_dump) or bad(ds_fp) or bad(ds_r244)
    snap = list(i.lm.dump_snapshot_reg256_261)
    dump_exempt = bool(i.lm.dump_data_loaded and i.lm.dump_snapshot_reg244 == 0 and live[1:7] == snap)
    r.export_hazard = cap.export_hazard(trusted, live[0], bad_domain, dump_exempt)
    r.hazard_obligation = bool(bad_domain)

    r244_drift = bool(trusted and i.r244x.lav and live[0] != i.r244x.la)
    hazard_yes = r.export_hazard == cap.EH_YES
    fnd = [lease_finding(BD_DUMP, ds_dump, i, hazard_yes, False, skip_l6),
           lease_finding(BD_FP, ds_fp, i, hazard_yes, False, skip_l6),
           lease_finding(BD_R244, ds_r244, i, hazard_yes, r244_drift, skip_l6),
           bus_finding(i, sl_bus), Finding()]
    if i.lm.mtou_running:
        fnd[4] = Finding(row=ROW_L10, plan=PLAN_WAIT_WRITE_IN_FLIGHT, reason=RS_MTOU_APPLY_RUNNING, dom=BD_MTOU)

    r.absence_relied = EV_MARKER_ABSENT in (ds_dump.evidence, ds_fp.evidence, ds_r244.evidence)
    r.durable_leg_projected = any(d.evidence in (EV_MARKER_CLEAR_BOOT, EV_MARKER_CLEAR_RUNTIME) for d in (ds_dump, ds_fp, ds_r244))
    r.fp_stale_operator_needed = ds_fp.stale_operator_needed
    r.dump_stale_operator_needed = ds_dump.stale_operator_needed
    r.r244_lav_marker_absent = bool(i.r244x.lav and ds_r244.evidence == EV_MARKER_ABSENT)
    r.fp_ctx_unknown = bool(i.fp_lease_ctx_unknown and ds_fp.kind == KIND_RESTORE_REQUIRED)
    r.dump_force_bypass_armed = bool(i.dump.force_bypass)

    r.dom[DS_DUMP] = DomView(ds_dump.c0, ds_dump.kind, ds_dump.evidence, (g.dump.dump_containment_state << 4) & 0xFF)
    r.dom[DS_FP] = DomView(ds_fp.c0, ds_fp.kind, ds_fp.evidence, 0)
    r.dom[DS_R244] = DomView(ds_r244.c0, ds_r244.kind, ds_r244.evidence, 0)
    stuck, busy = fnd[3].row == ROW_L7, fnd[3].row == ROW_L10
    r.dom[DS_BUS] = (DomView(C0_UNKNOWN, KIND_BUS_OR_LOCK_STUCK, EV_NONE, 0) if stuck
                     else DomView(C0_OBLIGATION, KIND_IN_FLIGHT, EV_NONE, 0) if busy
                     else DomView(C0_CLEAR_PROVEN, KIND_NONE, EV_IDLE, 0))
    r.dom[DS_MTOU] = (DomView(C0_OBLIGATION, KIND_IN_FLIGHT, EV_NONE, 0) if i.lm.mtou_running
                      else DomView(C0_CLEAR_PROVEN, KIND_NONE, EV_NO_DURABLE_RECORD, 0))
    r.dom[DS_MTOU_JOURNAL] = DomView(C0_CLEAR_PROVEN, KIND_NONE, EV_NOT_IMPLEMENTED, 0)
    r.dom[DS_FBP] = DomView(C0_UNKNOWN, KIND_NONE, EV_NONE, eff)

    overlay = bool(ds_dump.c0 != C0_CLEAR_PROVEN or ds_fp.c0 != C0_CLEAR_PROVEN or ds_r244.c0 != C0_CLEAR_PROVEN
                   or g.bus.manual_write_in_progress or g.bus.correction_in_progress)
    r.e1_state = (CMP_N if not r.masks_valid else CMP_O if overlay else CMP_M if r.e1_delta_mask == 0 else CMP_D)
    r.cx_state = (CMP_N if not r.masks_valid else CMP_O if overlay else CMP_M if r.ctx_mismatch_mask == 0 else CMP_D)
    r.in_state = CMP_N if not r.masks_valid else CMP_M if r.info_mismatch_mask == 0 else CMP_D

    effective_lost = i.mode == MODE_IF_LOST or i.sup.state == 3 or i.sup.episode_open
    w = Finding()
    if not effective_lost:
        if i.sup.p_stable:
            w = Finding(ROW_S1, PLAN_NO_ACTION, RS_SUP_STABLE, BD_NONE)
        else:
            reason = RS_SUP_STARTUP if i.sup.state == 0 else RS_SUP_SUSPECT if i.sup.state == 2 else RS_SUP_UNSTABLE
            w = Finding(ROW_S2, PLAN_WOULD_REFUSE_STARTS, reason, BD_SUPERVISION)
    else:
        for row in (ROW_L1, ROW_L2, ROW_L3, ROW_L4, ROW_L5, ROW_L6, ROW_L7, ROW_L8, ROW_L9, ROW_L10):
            if w.row != ROW_NONE:
                break
            w = pick_row(fnd, row)
        if w.row == ROW_NONE:
            changed = bool(i.sup.episode_open and i.ep.bound and (
                i.ep.cls != eff or (meaningful_class(eff) and (prof["generation"] != i.ep.gen or prof["binding"] != i.ep.binding))))
            r.profile_changed_since_lost = changed
            if changed:
                w = mk(ROW_L12, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_CHANGED_SINCE_LOST, BD_FBP)
            elif eff == fd.EPC_SAVE_UNCONFIRMED:
                w = mk(ROW_L13, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_SAVE_UNCONFIRMED, BD_FBP)
            elif eff == fd.EPC_UNREADABLE:
                w = mk(ROW_L14, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_UNREADABLE, BD_FBP)
            elif eff == fd.EPC_PROFILE_LOST:
                w = mk(ROW_L15, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_LOST, BD_FBP)
            elif eff == fd.EPC_PROFILE_STALE:
                w = mk(ROW_L15_STALE, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_STALE, BD_FBP)
            elif eff == fd.EPC_CORRUPT:
                w = mk(ROW_L16, PLAN_BLOCKED_PROFILE_CORRUPT, RS_PROFILE_CORRUPT, BD_FBP)
            elif eff == fd.EPC_CORRUPT_DOMAIN:
                w = mk(ROW_L17, PLAN_BLOCKED_PROFILE_CORRUPT, RS_PROFILE_CORRUPT_DOMAIN, BD_FBP)
            elif eff == fd.EPC_NOT_CAPTURED and not i.not_captured_proven:
                w = mk(ROW_L18, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_ABSENT_UNPROVEN, BD_FBP)
            elif eff == fd.EPC_NOT_CAPTURED:
                w = mk(ROW_L19, PLAN_BLOCKED_NO_PROFILE, RS_PROFILE_NOT_CAPTURED, BD_FBP)
            elif eff == fd.EPC_INVALIDATED:
                w = mk(ROW_L20, PLAN_BLOCKED_PROFILE_INVALIDATED, RS_PROFILE_INVALIDATED, BD_FBP)
            elif not prof_valid_rec:
                w = mk(ROW_L14, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_UNREADABLE, BD_FBP)
            elif not fd.profile_writer_usable(eff, i.profile_why):
                w = mk(ROW_L20_NOT_USABLE, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_NOT_WRITER_USABLE, BD_FBP)
            else:
                r.dom[DS_FBP].c0 = C0_CLEAR_PROVEN
                above = any(prof["reg256_261"][k] > i.lm.ceiling_w for k in range(6))
                if above:
                    w = mk(ROW_L21, PLAN_BLOCKED_SITE_CEILING, RS_SITE_CEILING_BELOW_PROFILE, BD_SITE)
                elif not trusted:
                    w = mk(ROW_L22, PLAN_WAIT_LIVE_DATA, live_reason(ca), BD_LIVE)
                elif r.ctx_mismatch_mask != 0:
                    w = mk(ROW_L23, PLAN_BLOCKED_CONTEXT_MISMATCH, ctx_reason(r.ctx_mismatch_mask), BD_LIVE)
                elif r.out_of_domain_mask != 0:
                    w = mk(ROW_L24, PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN, ood_reason(r.out_of_domain_mask, live[0]), BD_LIVE)
                elif r.e1_delta_mask == 0:
                    w = mk(ROW_L25, PLAN_WOULD_ALREADY_MATCH, RS_MATCH_E1_AND_CTX, BD_NONE)
                else:
                    w = mk(ROW_L26, PLAN_WOULD_APPLY_PROFILE, RS_E1_DELTA, BD_NONE)
    r.plan, r.reason, r.blocking_domain, r.row = w.plan, w.reason, w.dom, w.row

    r.would_preempt_fp = r.plan == PLAN_WOULD_PREEMPT_FREE_POWER
    r.would_preempt_dump = r.plan == PLAN_WOULD_PREEMPT_DUMP
    r.would_apply = r.plan == PLAN_WOULD_APPLY_PROFILE
    if r.would_apply:
        fr = 0
        if live[0] == 0 and (r.e1_delta_mask & 1) != 0:
            fr |= FR_F244
        for k in range(6):
            if stored[1 + k] < live[1 + k]:
                fr |= FR_F256_DOWN
            if stored[1 + k] > live[1 + k]:
                fr |= FR_F256_UP
        if (r.e1_delta_mask & 0x7FF80) != 0:
            fr |= FR_F268_279
        r.projected_frames, r.projected_frame_count = fr, popcount32(fr)
        r.would_write_244 = bool(fr & FR_F244)
    fba = fba_for_plan(r.plan)
    r.fba_state, r.fba_result = fba.state, fba.result
    profile_or_live_row = (ROW_L12 <= r.row <= ROW_L26) or r.row in (ROW_L15_STALE, ROW_L20_NOT_USABLE)
    r.fba_result_policy_a = (FAILBACK_RESULT_PREEMPTED_ONLY if (fba.state != NONE_U8 and profile_or_live_row) else fba.result)
    r.projected_after = r.plan
    r.alt_plan_absence_accepted = r.plan

    if depth == 0:
        if r.row == ROW_L6:
            r.alt_plan_absence_accepted = eval_core(i, True, clear_dom, use_snapshot, 1).plan
        if r.row in (ROW_L1, ROW_L2, ROW_L8, ROW_L9):
            dom = r.blocking_domain
            pc = (ds_dump.kind if dom == BD_DUMP else ds_fp.kind) == KIND_PENDING_CLEAR
            snap_ok = pc or (i.fp_snap.valid if dom == BD_FP else bool(i.lm.dump_data_loaded))
            r.projected_after = eval_core(i, skip_l6, dom, not pc, 1).plan if snap_ok else PLAN_WAIT_LIVE_DATA
    return r


def evaluate(i: ShadowInputs) -> ShadowPlan:
    return eval_core(i, False, 0xFF, False, 0)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
def put_dom(d: DomView) -> str:
    if d.c0 == C0_CLEAR_PROVEN:
        return "C" + ("M" if d.evidence == EV_MARKER_CLEAR_BOOT else "R" if d.evidence == EV_MARKER_CLEAR_RUNTIME
                      else "A" if d.evidence == EV_MARKER_ABSENT else "-")
    return ("O" if d.c0 == C0_OBLIGATION else "U") + str(d.kind)


def inputs_text(i: ShadowInputs, plan: ShadowPlan) -> cap.TextBuf:
    eff = cap.live_effective_class(i.lm.cls, i.lm.write_outcome_unknown, i.lm.read_anomaly)
    prof = _prof(i.lm.p)
    mean = meaningful_class(eff)
    lk = (1 if i.lm.g.bus.manual_write_in_progress else 0) | (2 if i.lm.g.bus.correction_in_progress else 0)
    parts = (
        f"sup={sup_char(i.sup.state)}", f"st={'1' if i.sup.p_stable else '0'}", f"fp={put_dom(plan.dom[DS_FP])}",
        f"dp={put_dom(plan.dom[DS_DUMP])}", f"r4={put_dom(plan.dom[DS_R244])}", "mt=-", f"pc={eff}",
        f"g={prof['generation'] if mean else '-'}", f"pb={format(prof['binding'] >> 32, 'X').rjust(8, '0') if mean else '-'}",
        f"e1={cmp_char(plan.e1_state)}", f"cx={cmp_char(plan.cx_state)}", f"in={cmp_char(plan.in_state)}",
        f"ca={cap.cq_char(plan.ca)}", f"d={'-' if plan.delta_count == NONE_U8 else plan.delta_count}",
        f"blk={format(plan.projected_frames, 'X')}", f"lk={lk}", f"pl={plan.plan}", f"rs={plan.reason}",
        # FINAL 8.5, appended after S3 9.2's keys (append-only): the two one-level re-runs
        f"alt={plan.alt_plan_absence_accepted}", f"pa={plan.projected_after}",
    )
    return cap.TextBuf(";".join(parts)[:cap.TEXT_CAP])
