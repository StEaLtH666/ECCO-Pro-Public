#!/usr/bin/env python3
"""Offline tests for FB-C2 - the Failback Shadow EVALUATOR (shadow-only, zero authority).

FB-C2 adds ONE pure evaluator header (firmware/include/ecco_failback_shadow.h, Python mirror registry/failback_shadow.py) that the
existing FB-C 1 s shadow tick calls ONCE per tick in MODE_IF_LOST (the readiness plan: "what would happen if HA were lost now"; it is
the Verdict, and inside an episode it equals the ACTUAL continuation plan - FINAL 8.5, S3 9.2 / 11.4, S5 2.3), and the Verdict /
Inputs / Episode / Soak publication that carries its plan. It adds no Modbus operation, no NVS access, no script / control / API
action / interval / entity, and nothing may read the shadow. It re-implements none of the FB-B1 / FB-B3 comparison, trust or
classification code: it calls the same shared helpers the Live Match (B10) uses.

  [1] model     the 81-row S4 section 9 decision table as goldens (registry/tests/_fbc2_rows.py, written independently from the
                table text), the FINAL-document extras, enum / name / FB-A pins, plan -> FB-A legality under the FB-A invariants,
                fail-closed zero input, determinism, a seeded random sweep of the "positively clear" contract and of the
                agreement with the B10 Live Match
  [2] host C++  a real C++ compiler evaluates the header over the 81 rows + extra pairs + a seeded random sweep as static_asserts and
                requires C++ == Python on every output field and on the Inputs text (gnu++17 and gnu++20, -Wall -Wextra -Werror),
                exact text goldens, and a mutant matrix over the header
  [3] lambda    the tick lambdas compile against the REAL header under a real compiler (stub ESPHome types, printf-checked logs)
  [4] static    pins Z1-Z8 for FB-C2 (write surface unchanged, placement, token ban over the tick AND the header, assignment /
                read allowlists, the full-scope live-firmware fbc_raw_* allowlist (Z4b) with negative controls, non-authority,
                RAM-only, durable surface unchanged, no new entity / control), the single-evaluation / readiness-Verdict pins, the
                Z11 proof that the card's `^BLOCKED` regex cannot consume the shadow (with negative controls) and the measured
                authority counts before / after
  [5] scope     the exact reverter and the FB-T0 chain entry fbc2

Behaviour of the real tick lambda is proven by registry/tests/test_failback_shadow_tick.py. No hardware, no network.
"""

from __future__ import annotations

import copy
import dataclasses
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(ROOT / "tools"))
import _fbc2_cxx as cx  # noqa: E402
import _fbc2_fixtures as fx  # noqa: E402
import _fbc2_rows as rows_mod  # noqa: E402
import _fbc2_scope as scope  # noqa: E402
import _scope_chain as chain  # noqa: E402
import failback_shadow as sh  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fpm  # noqa: E402

FAILURES: list[str] = []
FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_failback_shadow.h"
CARD_SRC = ROOT / "frontend" / "ecco-energy-actions-card" / "src"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


LIVE_TEXT = FW_PATH.read_text(encoding="utf-8")
HEADER_TEXT = HEADER_PATH.read_text(encoding="utf-8")
FW = chain.load_fw(LIVE_TEXT)
# FB-D1: FB-C2's own scope (its 14 edits, its appended include, its chain entry) is checked on the firmware AS OF fbc2 - the
# chain undoes every later entry exactly (FB-D1 appends include/ecco_rtc_policy.h and edits the RTC / poll code). Everything
# else in this suite keeps reading the LIVE firmware.
FBC2_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "fbc2", LIVE_TEXT)


# ===========================================================================
# Random scenario generator (seeded; every profile class, domain state, cache state and lock shows up)
# ===========================================================================
def _steps():
    prof = [fx.profile_invalidated, fx.profile_corrupt, fx.profile_corrupt_domain, fx.profile_unreadable,
            fx.profile_save_unconfirmed, fx.profile_lost, lambda i: fx.profile_not_captured(i, True),
            lambda i: fx.profile_not_captured(i, False),
            lambda i: fx.set_profile(i, fd.EPC_PROFILE_STALE, why=fd.WHY_ROLLBACK),
            lambda i: setattr(i, "profile_why", fd.WHY_WIT_LAGGING), lambda i: setattr(i, "profile_why", fd.WHY_WIT_MISSING)]
    dom = [fx.fp_active, fx.fp_starting, fx.fp_rr, lambda i: fx.fp_rr(i, backoff=True), fx.fp_pc, fx.fp_on, fx.fp_ending,
           fx.fp_mc, lambda i: fx.fp_mc(i, unreadable=True), lambda i: fx.fp_oip_orphan(i, 4000),
           lambda i: fx.fp_oip_orphan(i, 15000), fx.dump_active, fx.dump_rr, lambda i: fx.dump_rr(i, backoff=True), fx.dump_on,
           fx.dump_ending, fx.dump_mc, lambda i: fx.dump_mc(i, k=4), lambda i: fx.dump_mc(i, unreadable=True),
           fx.dump_force_bypass, fx.r244_held, fx.r244_pc, fx.r244_restore_running, fx.r244_mc,
           lambda i: fx.cabs(i, "dump"), lambda i: fx.cabs(i, "fp"), lambda i: fx.cabs(i, "dump", "fp", "r244"),
           lambda i: fx.probe_latch(i, cap.DOM_FP, cap.LATCH_GHOST_RR), lambda i: fx.probe_latch(i, cap.DOM_DUMP, cap.LATCH_UNREADABLE),
           lambda i: fx.probe_latch(i, cap.DOM_R244, cap.LATCH_MALFORMED)]
    bus = [lambda i: fx.mwip_orphan(i, 4000), lambda i: fx.mwip_orphan(i, 15000), lambda i: fx.cip_held(i, 5000),
           lambda i: fx.cip_held(i, 70000), fx.mtou_running]
    cache = [fx.cache_stale, fx.cache_polling_off, fx.cache_pre_fence, fx.cache_no_block_b_since_boot, fx.cache_unlatched]
    live = [lambda i: fx.set_live(i, 244, 0), lambda i: fx.set_live(i, 244, 1), lambda i: fx.set_live(i, 256, 3000),
            lambda i: fx.set_live(i, 256, 300), lambda i: fx.set_live(i, 268, 55), lambda i: fx.set_live(i, 274, 5),
            lambda i: fx.set_live(i, 254, 1234), lambda i: fx.set_live(i, 232, 0x0100), lambda i: fx.set_live(i, 243, 7),
            lambda i: fx.set_live(i, 230, 99), lambda i: fx.set_live(i, 248, 0)]
    return prof, dom, bus, cache, live


def random_case(rng: random.Random) -> "sh.ShadowInputs":
    prof, dom, bus, cache, live = _steps()
    i = fx.base()
    i.mode = rng.choice((sh.MODE_ACTUAL, sh.MODE_IF_LOST))
    fx.sup_state(i, rng.choice((0, 1, 1, 2, 3, 3, 3)), stable=rng.random() < 0.4, episode=rng.random() < 0.25)
    for group, p in ((prof, 0.3), (dom, 0.5), (bus, 0.2), (cache, 0.25), (live, 0.35)):
        if rng.random() < p:
            group[rng.randrange(len(group))](i)
        if group is dom and rng.random() < 0.15:
            group[rng.randrange(len(group))](i)
    if i.sup.episode_open and rng.random() < 0.5:
        pp = i.lm.p if i.lm.p is not None else fpm.blank_profile()
        i.ep = sh.EpProf(bound=True, cls=rng.choice((fd.EPC_VALID, fd.EPC_NOT_CAPTURED, fd.EPC_INVALIDATED)),
                         gen=rng.choice((pp["generation"], pp["generation"] + 1, 0)), binding=pp["binding"])
    if rng.random() < 0.08:
        i.lm.cls = rng.choice((9, 12, 200))          # E0: an out-of-range enum
    if rng.random() < 0.03:
        fx.boot_not_loaded(i)
    return i


def random_cases(n: int, seed: int = 20261003) -> list:
    rng = random.Random(seed)
    return [random_case(rng) for _ in range(n)]


# ===========================================================================
# [1] model
# ===========================================================================
def section_model() -> None:
    print("\n[1] model")
    # -- the 81 golden rows (independent transcription of the S4 table)
    p = subprocess.run([sys.executable, str(HERE / "_fbc2_rows_check.py")], capture_output=True, text=True)
    tail = [l for l in p.stdout.splitlines() if l.startswith(("rows:", "FINAL extras:"))]
    check("the 81 S4 section 9 rows + the FINAL extras all pass against the Python mirror", p.returncode == 0 and any(
        "81 PASS / 0 FAIL" in l for l in tail), "\n".join(tail) + p.stderr[-300:])
    check("ROWS holds exactly 81 rows numbered 1..81", [r["n"] for r in rows_mod.ROWS] == list(range(1, 82)))

    # -- numbering is frozen (S4 8.1) and every name is <= 48 characters
    want = {0: "NOT_EVALUATED", 1: "NO_ACTION", 2: "WOULD_REFUSE_STARTS", 10: "WOULD_PREEMPT_DUMP", 11: "WOULD_PREEMPT_FREE_POWER",
            12: "WAIT_DUMP_RESTORE", 13: "WAIT_FREE_POWER_RESTORE", 14: "WAIT_WRITE_IN_FLIGHT", 15: "WAIT_LIVE_DATA",
            16: "WAIT_MANUAL_TOU_RECOVERY", 20: "BLOCKED_RECOVERY_METADATA", 21: "BLOCKED_DURABLE_UNKNOWN",
            22: "BLOCKED_OPERATOR_NEEDED", 23: "BLOCKED_PROFILE_CORRUPT", 24: "BLOCKED_PROFILE_UNAVAILABLE",
            25: "BLOCKED_SITE_CEILING", 26: "BLOCKED_CONTEXT_MISMATCH", 27: "BLOCKED_LIVE_OUT_OF_DOMAIN", 30: "BLOCKED_NO_PROFILE",
            31: "BLOCKED_PROFILE_INVALIDATED", 40: "WOULD_ALREADY_MATCH", 41: "WOULD_APPLY_PROFILE", 50: "WOULD_REMAIN_LATCHED"}
    check("plan codes and names are the frozen S4 8.1 set", sh.PLAN_NAMES == want)
    check("every plan name is <= 48 characters", all(len(v) <= 48 for v in want.values()))
    check("plan_name is total: an unknown value reads NOT_EVALUATED", sh.plan_name(77) == "NOT_EVALUATED" and sh.plan_name(255) == "NOT_EVALUATED")
    check("the S4 8.3 reason numbers are pinned (209 and 306 unused; 510 / 511 are the FB-C2 appendices)",
          sh.RS["DUMP_ACTIVE"] == 101 and sh.RS["FP_OP_FLAG_SETTLING"] == 220 and sh.RS["R244_OP_FLAG_SETTLING"] == 316 and
          sh.RS["MTOU_JOURNAL_OBLIGATION"] == 410 and sh.RS["PROFILE_ABSENT_UNPROVEN"] == 509 and sh.RS["E1_DELTA"] == 702 and
          209 not in sh.RS.values() and 306 not in sh.RS.values() and sh.RS["PROFILE_NOT_WRITER_USABLE"] == 510 and
          sh.RS["PROFILE_STALE"] == 511)

    # -- FB-A: numbers agree with registry/fallback_profile.py and every projected pair is legal under the FB-A invariants
    check("the FB-A state / result numbers restated by the mirror equal registry/fallback_profile.py",
          (sh.FAILBACK_PREEMPT_REQUIRED, sh.FAILBACK_LATCHED_COMPLETE, sh.FAILBACK_BLOCKED) ==
          (fpm.FAILBACK_PREEMPT_REQUIRED, fpm.FAILBACK_LATCHED_COMPLETE, fpm.FAILBACK_BLOCKED) and
          sh.FAILBACK_RESULT_PREEMPTED_NO_PROFILE == 2 and sh.FAILBACK_RESULT_ALREADY_AT_PROFILE == 3 and
          sh.FAILBACK_RESULT_APPLIED_VERIFIED == fpm.FAILBACK_RESULT_APPLIED_VERIFIED and
          all(fpm.FAILBACK_RESULT_NAMES[k] for k in range(12)))
    bad = []
    for plan in sh.EMITTED_PLANS:
        pair = sh.fba_for_plan(plan)
        if pair.state == sh.NONE_U8:
            continue
        committed = pair.result == sh.FAILBACK_RESULT_APPLIED_VERIFIED
        rec = fpm.blank_failback(magic=fpm.FAILBACK_MAGIC, schema=fpm.FAILBACK_SCHEMA, size=fpm.FAILBACK_SIZE, state=pair.state,
                                 reason=1, result=pair.result, flags=(0x02 if committed else 0) | 0x01, event_seq=1,
                                 profile_generation=7, profile_binding=0x1122334455667788,
                                 from_244=2 if committed else 0, from_256_261=[3000] * 6 if committed else [0] * 6,
                                 from_268_279=[50] * 6 + [1] * 6 if committed else [0] * 12)
        if not committed:
            rec["flags"] = 0x01 if pair.state == fpm.FAILBACK_PREEMPT_REQUIRED else 0
        if fpm.failback_defect(fpm.seal_failback(rec)) != 0:
            bad.append((plan, pair.state, pair.result))
    check("every plan that projects to FB-A is a legal FailbackStateV1 under failback_invariants_hold", not bad, str(bad))
    check("RAM-only plans (0, 1, 2, 50) and the reserved 16 emit no FB-A record except 16 (PREEMPT/0, never emitted)",
          all(sh.fba_for_plan(c).state == sh.NONE_U8 for c in (0, 1, 2, 50)) and sh.fba_for_plan(16).state == 1)

    # -- fail-closed zero input, determinism
    z = sh.evaluate(sh.ShadowInputs())
    check("a zero-initialised input evaluates NOT_EVALUATED, RAM-only, export hazard UNKNOWN",
          z.plan == 0 and z.fba_state == sh.NONE_U8 and z.export_hazard == cap.EH_UNKNOWN and z.reason == sh.RS_BOOT_NOT_LOADED)
    cases = random_cases(400)
    check("evaluate() is deterministic: identical inputs give an identical plan", all(
        dataclasses.asdict(sh.evaluate(c)) == dataclasses.asdict(sh.evaluate(copy.deepcopy(c))) for c in cases))
    check("evaluate() never mutates its input", all(
        dataclasses.asdict(c) == dataclasses.asdict((sh.evaluate(c), c)[1]) for c in cases[:50]))

    # -- sweep invariants
    seen = {}
    viol = []
    for c in cases:
        r = sh.evaluate(c)
        seen[r.plan] = seen.get(r.plan, 0) + 1
        if r.plan not in sh.EMITTED_PLANS:
            viol.append(("not an emitted code", r.plan))
        if r.plan in (40, 41):
            g = c.lm.g
            eff = cap.live_effective_class(c.lm.cls, c.lm.write_outcome_unknown, c.lm.read_anomaly)
            clean = (r.ca == cap.CQ_FRESH and eff == fd.EPC_VALID and fd.profile_writer_usable(eff, c.profile_why)
                     and all(d.c0 == sh.C0_CLEAR_PROVEN and d.evidence != sh.EV_MARKER_ABSENT for d in r.dom[:3])
                     and r.dom[sh.DS_BUS].c0 == sh.C0_CLEAR_PROVEN and not c.lm.mtou_running and c.mode in (0, 1)
                     and r.out_of_domain_mask == 0 and r.ctx_mismatch_mask == 0 and not r.profile_changed_since_lost)
            if not clean:
                viol.append(("WOULD_* without the positively-clear contract", r.row, r.reason))
        if r.plan in (26, 27, 40, 41) and r.ca != cap.CQ_FRESH:
            viol.append(("an E1/CTX verdict with a stale cache", r.plan, r.ca))
        if r.would_apply and (r.projected_frames & ~0xF):
            viol.append(("frames outside the four E1 frames", r.projected_frames))
        if r.plan != 41 and (r.projected_frames or r.would_write_244):
            viol.append(("frames without WOULD_APPLY", r.plan))
        if r.export_hazard == cap.EH_YES and r.ca != cap.CQ_FRESH:
            viol.append(("hazard YES without a trusted cache", r.ca))
        if r.plan == 22 and r.would_write_244:
            viol.append(("a write projected over an operator-needed lease",))
        if r.plan == 16 or r.plan == 50:
            viol.append(("a reserved / episode-layer code emitted", r.plan))
    check("sweep invariants hold over 400 seeded cases (emitted codes only; WOULD_* only when positively clear; no E1/CTX verdict "
          "with a stale cache; frames only with WOULD_APPLY; hazard YES needs a trusted cache; 16 / 50 never emitted)", not viol,
          str(viol[:3]))
    need = {1, 2, 10, 11, 12, 13, 14, 15, 20, 21, 22, 24, 26, 27, 40, 41}
    check("the sweep exercises every principal plan code (coverage of the generator)", need <= set(seen), f"missing {sorted(need - set(seen))}")

    # -- B10 agreement: the shadow's masks / trust / verdict agree with the shared Live Match on every comparable case
    disagree = []
    nchk = 0
    for c in cases:
        c2 = copy.deepcopy(c)
        c2.mode = sh.MODE_IF_LOST
        c2.sup.episode_open = False
        r = sh.evaluate(c2)
        lm = cap.live_match(c2.lm)
        if r.row in (sh.ROW_E0, sh.ROW_E1):
            continue
        if r.ca != lm.ca:
            disagree.append(("ca", r.ca, lm.ca))
        if lm.compared and r.masks_valid:
            nchk += 1
            if (r.e1_delta_mask, r.ctx_mismatch_mask, r.out_of_domain_mask, r.info_mismatch_mask) != (lm.dx, lm.cx, lm.ox, lm.ix):
                disagree.append(("masks", r.row))
            clear = all(d.c0 == sh.C0_CLEAR_PROVEN and d.evidence != sh.EV_MARKER_ABSENT for d in r.dom[:3]) and \
                r.dom[sh.DS_BUS].c0 == sh.C0_CLEAR_PROVEN and not c2.lm.mtou_running and r.row in (sh.ROW_L21, sh.ROW_L22, 23, 24, 25, 26)
            if clear and r.row >= 23 and r.row != sh.ROW_L21:
                expect = {cap.LM_OUT_OF_DOMAIN: 27, cap.LM_CONTEXT: 26, cap.LM_MATCH: 40}
                if lm.m in expect and r.plan != expect[lm.m]:
                    disagree.append(("verdict", lm.m, r.plan))
                if lm.m in (cap.LM_DRIFT, cap.LM_EXPORT) and r.plan not in (41, 26, 27):
                    disagree.append(("verdict", lm.m, r.plan))
    check("the shadow agrees with the shared Live Match on ca and on all four masks wherever B10 compared (one comparison model)",
          not disagree and nchk > 20, f"{disagree[:3]} compared={nchk}")

    # -- hand-written behaviours the table cannot say alone
    b = LB()
    r = sh.evaluate(b)
    check("MODE_ACTUAL, LOST, everything clear by marker, live == profile -> WOULD_ALREADY_MATCH LATCHED/3",
          r.plan == 40 and (r.fba_state, r.fba_result) == (3, 3))
    b2 = LB()
    b2.mode = sh.MODE_ACTUAL
    fx.sup_state(b2, 1, stable=True)
    check("supervised and stable outside an episode -> NO_ACTION (RAM-only); the readiness plan is the L-branch plan",
          sh.evaluate(b2).plan == 1 and sh.evaluate(dataclasses.replace(b2, mode=sh.MODE_IF_LOST)).plan == 40)

    # -- the Verdict contract (FINAL 8.5, S3 9.2 / 11.4, S5 2.3): the tick evaluates ONCE, in MODE_IF_LOST, and publishes that
    #    readiness plan as the Verdict. That loses nothing: inside an episode (or while LOST) both modes give the same plan, and
    #    MODE_IF_LOST can never produce the supervision rows NO_ACTION / WOULD_REFUSE_STARTS that S5 2.3 keeps off the Verdict.
    same, diff_ep = 0, []
    for c in cases:
        if not (c.sup.episode_open or c.sup.state == 3):
            continue
        a = dataclasses.asdict(sh.evaluate(dataclasses.replace(copy.deepcopy(c), mode=sh.MODE_IF_LOST)))
        b_ = dataclasses.asdict(sh.evaluate(dataclasses.replace(copy.deepcopy(c), mode=sh.MODE_ACTUAL)))
        a.pop("would_refuse_starts")
        b_.pop("would_refuse_starts")
        same += 1
        if a != b_:
            diff_ep.append((c.sup.state, c.sup.episode_open, a["plan"], b_["plan"]))
    check("inside an episode (or while LOST) MODE_IF_LOST and MODE_ACTUAL give the same plan on every output field but "
          "would_refuse_starts: one IF_LOST evaluation per tick is the ACTUAL continuation plan (S3 11.4, FINAL 8.5)",
          not diff_ep and same > 50, f"{diff_ep[:3]} compared={same}")
    if_lost = {sh.evaluate(dataclasses.replace(copy.deepcopy(c), mode=sh.MODE_IF_LOST)).plan for c in cases}
    check("MODE_IF_LOST never produces NO_ACTION (1) or WOULD_REFUSE_STARTS (2): the Verdict can never show a supervision row "
          "(S5 2.3: those are visible as SHADOW_IDLE / SHADOW_WATCH on the State entity)", not ({1, 2} & if_lost), str(sorted(if_lost)))

    # -- the export-hazard obligation term (FINAL 8.2) the soak `xh` accounting is gated on (export_hazard itself is unchanged)
    hz = []
    for c in cases:
        r = sh.evaluate(c)
        if r.row in (sh.ROW_E0, sh.ROW_E1):
            if r.hazard_obligation:
                hz.append(("an unevaluated plan reports an obligation", r.row))
            continue
        term = any(d.c0 != sh.C0_CLEAR_PROVEN and d.kind not in (sh.KIND_ACTIVE, sh.KIND_STARTING)
                   for d in (r.dom[sh.DS_DUMP], r.dom[sh.DS_FP], r.dom[sh.DS_R244]))
        if r.hazard_obligation != term:
            hz.append(("flag differs from the FINAL 8.2 term over the domain views", r.row, r.reason))
        if r.export_hazard == cap.EH_YES and not r.hazard_obligation:
            hz.append(("hazard YES without an obligation", r.row))
    nobl = sum(1 for c in cases if sh.evaluate(c).hazard_obligation)
    check("hazard_obligation is exactly FINAL 8.2's obligation term (a DUMP / FP / R244 domain view not clear and neither ACTIVE "
          "nor STARTING), false for an unevaluated plan, and every hazard YES carries it", not hz and 20 < nobl < len(cases),
          f"{hz[:3]} obligations={nobl}")
    h0 = LB()
    fx.cache_pre_fence(h0)
    r_h0 = sh.evaluate(h0)
    hd = LB()
    fx.dump_on(hd)
    fx.set_live(hd, 244, 0)
    r_hd = sh.evaluate(hd)
    fx.cache_pre_fence(hd)
    r_hdu = sh.evaluate(hd)
    ha = LB()
    fx.dump_active(ha)
    fx.set_live(ha, 244, 0)
    r_ha = sh.evaluate(ha)
    check("obligation term: every lease clear + untrusted cache -> hazard UNKNOWN but NO obligation (soak counts nothing); Dump "
          "operator-needed + live 244 = 0 -> YES with the obligation, UNKNOWN with it once pre-fence; a guarded ACTIVE Dump -> NO, "
          "no obligation", (r_h0.export_hazard, r_h0.hazard_obligation) == (cap.EH_UNKNOWN, False) and
          (r_hd.export_hazard, r_hd.hazard_obligation) == (cap.EH_YES, True) and
          (r_hdu.export_hazard, r_hdu.hazard_obligation) == (cap.EH_UNKNOWN, True) and
          (r_ha.export_hazard, r_ha.hazard_obligation) == (cap.EH_NO, False))

    # -- FINAL 8.5: the two one-level re-runs are published, appended to the Inputs text (append-only after S3 9.2's keys)
    bc = LB()
    fx.cabs(bc, "dump", "fp", "r244")
    rc_ = sh.evaluate(bc)
    bf = LB()
    for f_ in (fx.fp_active, fx.fp_lease_overlay, fx.fp_snapshot_equals_profile):
        f_(bf)
    rf_ = sh.evaluate(bf)
    rl_ = sh.evaluate(LB())
    keys = [kv.split("=", 1)[0] for kv in str(sh.inputs_text(LB(), rl_)).split(";")]
    check("Inputs carries alt (alt_plan_absence_accepted) and pa (projected_after) as the LAST two keys, after S3 9.2's 18",
          keys == ["sup", "st", "fp", "dp", "r4", "mt", "pc", "g", "pb", "e1", "cx", "in", "ca", "d", "blk", "lk", "pl", "rs", "alt", "pa"],
          str(keys))
    check("Inputs alt / pa values: all-absence -> pl=21 alt=40 (what an absence-accepting engine would do) pa=21; an active FP lease "
          "-> pl=11 alt=11 pa=40 (after the pre-empt, from the FP snapshot); everything clear -> pl=alt=pa=40",
          str(sh.inputs_text(bc, rc_)).endswith(";pl=21;rs=117;alt=40;pa=21") and
          str(sh.inputs_text(bf, rf_)).endswith(";pl=11;rs=201;alt=11;pa=40") and
          str(sh.inputs_text(LB(), rl_)).endswith(";pl=40;rs=701;alt=40;pa=40"))
    b3 = LB()
    b3.lm.live = list(b3.lm.live)
    b3.lm.live[0] = 0
    r3 = sh.evaluate(b3)
    check("live 244 = 0 -> WOULD_APPLY with exactly the F244 frame and would_write_244 (the only permitted 244 write)",
          r3.plan == 41 and r3.projected_frames == sh.FR_F244 and r3.would_write_244 and r3.delta_count == 1)
    b4 = LB()
    fx.set_live(b4, 256, 3000)
    fx.set_live(b4, 257, 8000)
    r4 = sh.evaluate(b4)
    check("one power word below the profile and one above -> both F256_DOWN and F256_UP, never a 230 / CTX frame",
          r4.plan == 41 and r4.projected_frames & sh.FR_F256_UP and r4.projected_frames & sh.FR_F256_DOWN)
    # absence is never proof: R3
    b5 = LB()
    fx.cabs(b5, "dump", "fp", "r244")
    r5 = sh.evaluate(b5)
    check("R3: clear BY ABSENCE blocks every WOULD_* (BLOCKED_DURABLE_UNKNOWN, absence_relied) and alt shows what absence-accepting would do",
          r5.plan == 21 and r5.absence_relied and r5.alt_plan_absence_accepted == 40)
    b6 = copy.deepcopy(b5)
    b6.absence_witness = True
    check("only an absence witness lifts R3 (reserved for FB-D: the shadow always passes false)", sh.evaluate(b6).plan == 40)
    # export hazard tri-state
    b7 = LB()
    fx.dump_on(b7)
    fx.set_live(b7, 244, 0)
    r7 = sh.evaluate(b7)
    check("Dump operator-needed with live 244 = 0 -> BLOCKED_OPERATOR_NEEDED + hazard YES + never a write",
          r7.plan == 22 and r7.reason == sh.RS["DUMP_OPERATOR_NEEDED_EXPORT_LIVE"] and r7.export_hazard == cap.EH_YES and not r7.would_write_244)
    fx.cache_pre_fence(b7)
    r7b = sh.evaluate(b7)
    check("the same state with an untrusted cache -> hazard UNKNOWN, never NO", r7b.export_hazard == cap.EH_UNKNOWN and r7b.plan == 22)

    # -- no-profile semantics: the shadow never proves NOT_CAPTURED (FB-B0's witness has no generation-0 state)
    b8 = LB()
    fx.profile_not_captured(b8, False)
    r8 = sh.evaluate(b8)
    check("NOT_CAPTURED is BLOCKED_PROFILE_UNAVAILABLE / PROFILE_ABSENT_UNPROVEN (BLOCKED/7) while not_captured_proven is false",
          r8.plan == 24 and r8.reason == sh.RS["PROFILE_ABSENT_UNPROVEN"] and (r8.fba_state, r8.fba_result) == (4, 7))
    unavailable = (lambda i: fx.set_profile(i, fd.EPC_PROFILE_STALE, why=fd.WHY_ROLLBACK), fx.profile_lost, fx.profile_save_unconfirmed,
                   fx.profile_unreadable, lambda i: setattr(i, "profile_why", fd.WHY_WIT_LAGGING))
    check("PROFILE_STALE / LOST / SAVE_UNCONFIRMED / UNREADABLE / VALID-but-not-writer-usable are all BLOCKED_PROFILE_UNAVAILABLE",
          all(sh.evaluate(_apply_copy(f)(LB())).plan == 24 for f in unavailable))
    # thresholds
    check("owner grace is 10 s and the RTC-lock stuck threshold 60 s (S4 3.7)", sh.kOwnerGraceMs == 10000 and sh.kCipStuckMs == 60000)
    c10 = LB(); fx.fp_oip_orphan(c10, 9999)
    c11 = LB(); fx.fp_oip_orphan(c11, 10000)
    check("an orphaned FP operation flag is SETTLING (L10) below 10 s and STUCK (L7) at 10 s",
          sh.evaluate(c10).reason == sh.RS["FP_OP_FLAG_SETTLING"] and sh.evaluate(c11).reason == sh.RS["FP_OP_FLAG_STUCK"])
    # latch model
    check("FB-F latch model: only a kind-N episode whose edge plan is ALREADY_MATCH self-clears; every other close latches; a latched edge opens kind L",
          sh.close_outcome(sh.EPK_N, 40) == sh.FBF_P and all(sh.close_outcome(k, p) == sh.FBF_A for k, p in (
              (sh.EPK_L, 40), (sh.EPK_N, 30), (sh.EPK_N, 50), (sh.EPK_N, 24))) and sh.kind_for_edge(True) == sh.EPK_L and
          sh.kind_for_edge(False) == sh.EPK_N)
    check("State names: first match episode -> ha_back -> would-latched -> watch -> idle",
          [sh.state_name(1, True, True), sh.state_name(2, True, True), sh.state_name(3, True, True), sh.state_name(0, False, False),
           sh.state_name(0, False, True)] == ["SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WOULD_AWAIT_ACK", "SHADOW_WATCH", "SHADOW_IDLE"])

    # -- text widths and card regexes
    texts = {sh.plan_name(c) for c in want}
    worst = 0
    for c in cases:
        r = sh.evaluate(c)
        worst = max(worst, len(str(sh.inputs_text(c, r))))
    wc = fx.base()
    wc.lm.p = dict(wc.lm.p, generation=0xFFFFFFFF, binding=0xFFFFFFFFFFFFFFFF)
    wcr = sh.evaluate(wc)
    wcr.delta_count = 19
    wcr.projected_frames = 0xF
    wcr.reason = 635
    wcr.plan = 255
    wcr.alt_plan_absence_accepted = 255
    wcr.projected_after = 255
    wc.lm.g.bus.manual_write_in_progress = True
    wc.lm.g.bus.correction_in_progress = True
    wlen = len(str(sh.inputs_text(wc, wcr)))
    check(f"the Inputs text is <= 200 characters over the sweep and at its widest fields (measured worst {wlen})",
          worst <= 200 and wlen <= 200, f"{worst} {wlen}")
    rxs = card_regexes()
    hits = [(t, pat) for t in texts for pat, fl, _o in rxs if re.search(pat, t, fl)]
    allowed = [h for h in hits if h[0].startswith("BLOCKED_")]
    check("no plan name matches an Energy Actions card regex except the `^BLOCKED` schedule-result pattern (scoped to the schedule's last "
          "result; the Verdict is a diagnostic entity the card never reads)", len(hits) == len(allowed), str([h for h in hits if h not in allowed]))


def LB():
    """A base whose readiness evaluation is MATCH: IF_LOST mode ignores the supervision state (the L branch)."""
    b = fx.base()
    b.mode = sh.MODE_IF_LOST
    return b


def _apply_copy(f):
    def g(i):
        j = copy.deepcopy(i)
        f(j)
        return j
    return g


def card_regexes() -> list[tuple[str, int, str]]:
    out, seen = [], set()
    files = sorted(CARD_SRC.glob("*.ts")) + sorted((CARD_SRC / "utils").glob("*.ts"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        pats = list(re.finditer(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", src))
        pats += list(re.finditer(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", src))
        for m in pats:
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append((m.group(1), re.I if "i" in m.group(2) else 0, f.name))
    return out


# ===========================================================================
# [2] host C++
# ===========================================================================
def scenario_cases() -> list:
    cs = [r["build"]() for r in rows_mod.ROWS]
    # modes the table's 'Plan' column does not exercise: the readiness call of every row
    ready = []
    for r in rows_mod.ROWS[:40]:
        i = r["build"]()
        i.mode = sh.MODE_IF_LOST
        ready.append(i)
    pairs = []
    a = LB(); fx.dump_active(a); fx.fp_active(a); pairs.append(a)
    a = LB(); fx.fp_mc(a); fx.dump_rr(a); pairs.append(a)
    a = LB(); fx.fp_rr(a); fx.r244_held(a); pairs.append(a)
    a = LB(); fx.profile_not_captured(a, True); pairs.append(a)
    a = LB(); fx.set_profile(a, fd.EPC_PROFILE_STALE, why=fd.WHY_ROLLBACK); pairs.append(a)
    a = LB(); fx.fp_active(a); fx.fp_snapshot_equals_profile(a); pairs.append(a)
    a = LB(); fx.dump_active(a); pairs.append(a)
    a = LB(); a.profile_why = fd.WHY_WIT_LAGGING; pairs.append(a)
    a = LB(); fx.set_live(a, 254, 1234); fx.set_live(a, 274, 5); pairs.append(a)
    a = LB(); fx.set_live(a, 244, 0); fx.set_live(a, 256, 3000); fx.set_live(a, 268, 55); pairs.append(a)
    a = LB(); fx.dump_on(a); fx.set_live(a, 244, 0); pairs.append(a)
    a = LB(); fx.cabs(a, "fp"); fx.set_live(a, 245, 9); pairs.append(a)
    return cs + ready + pairs


def cxx_source(cases: list, extra: str = "") -> str:
    return ('#include "ecco_failback_shadow.h"\n' + cx.emit_asserts(cases) + extra + "int main() { return 0; }\n")


TEXT_GOLDENS = (
    ("plan names", "static_assert(str_is(plan_name(40), \"WOULD_ALREADY_MATCH\") && str_is(plan_name(41), \"WOULD_APPLY_PROFILE\") && "
                   "str_is(plan_name(21), \"BLOCKED_DURABLE_UNKNOWN\") && str_is(plan_name(50), \"WOULD_REMAIN_LATCHED\") && "
                   "str_is(plan_name(0), \"NOT_EVALUATED\") && str_is(plan_name(99), \"NOT_EVALUATED\"), \"plan_name\");"),
    ("state names", "static_assert(str_is(state_name(1, true, true), \"SHADOW_EPISODE\") && str_is(state_name(2, false, true), "
                    "\"SHADOW_EPISODE_HA_BACK\") && str_is(state_name(3, true, true), \"SHADOW_WOULD_AWAIT_ACK\") && "
                    "str_is(state_name(0, false, false), \"SHADOW_WATCH\") && str_is(state_name(0, false, true), \"SHADOW_IDLE\"), "
                    "\"state_name\");"),
    ("latch model", "static_assert(close_outcome(EPK_N, 40) == FBF_P && close_outcome(EPK_L, 40) == FBF_A && "
                    "close_outcome(EPK_N, 30) == FBF_A && kind_for_edge(true) == EPK_L && kind_for_edge(false) == EPK_N && "
                    "close_latches(FBF_A) && !close_latches(FBF_P), \"latch model\");"),
    ("fba mapping", "static_assert(fba_for_plan(10).state == 1 && fba_for_plan(21).result == 6 && fba_for_plan(21).state == 4 && "
                    "fba_for_plan(30).state == 3 && fba_for_plan(30).result == 2 && fba_for_plan(41).result == 4 && "
                    "fba_for_plan(2).state == NONE_U8 && fba_for_plan(50).result == NONE_U8, \"fba_for_plan\");"),
)


def text_golden_source() -> str:
    gold = []
    b = fx.base()
    gold.append(("MATCH", b))
    c = fx.base(); fx.fp_active(c); gold.append(("FP active", c))
    lines = []
    for n, (name, i) in enumerate(gold):
        s = str(sh.inputs_text(i, sh.evaluate(i)))
        lines.append(f"static_assert(text_is(\"{s}\", inputs_text(case_{n}(), evaluate(case_{n}()))), \"inputs text: {name}\");")
    cases = [i for _n, i in gold]
    body = "\n".join(cx.emit_case(f"case_{n}", i) for n, i in enumerate(cases))
    use = "using namespace ecco_failback_shadow;\nusing ecco_fbcap::str_is;\nusing ecco_fbcap::text_is;\n"
    return use + body + "\n" + "\n".join(lines) + "\n" + "\n".join(g for _n, g in TEXT_GOLDENS) + "\n"


def compile_both(src: str, ov: dict | None = None) -> list[tuple[str, int, str]]:
    out = []
    for std in ("gnu++17", "gnu++20"):
        rc, o = cx.compile_source(src, std, ov)
        out.append((std, rc, o))
    return out


HEADER_MUTANTS = (
    ("L6 (R3 absence) never fires", "s.evidence == EV_MARKER_ABSENT && !in.absence_witness && !skip_l6", "false"),
    ("export hazard UNKNOWN encoded as trusted", "ecco_fbcap::export_hazard(trusted, live[0], bad_domain, dump_exempt)",
     "ecco_fbcap::export_hazard(true, live[0], bad_domain, dump_exempt)"),
    ("a pre-fence cache counts as trusted", "const bool trusted = ca == ecco_fbcap::CQ_FRESH;",
     "const bool trusted = ca == ecco_fbcap::CQ_FRESH || ca == ecco_fbcap::CQ_PRE_FENCE;"),
    ("a stale cache counts as trusted", "const bool trusted = ca == ecco_fbcap::CQ_FRESH;",
     "const bool trusted = ca == ecco_fbcap::CQ_FRESH || ca == ecco_fbcap::CQ_STALE;"),
    ("writer-usable gate dropped", "!ecco_fbdurable::profile_writer_usable(eff, in.profile_why)", "false"),
    ("profile changed under the episode is not noticed", "const bool changed = in.sup.episode_open && in.ep.bound &&",
     "const bool changed = false && in.sup.episode_open && in.ep.bound &&"),
    ("site ceiling off by one", "in.lm.p.reg256_261[i] > in.lm.ceiling_w", "in.lm.p.reg256_261[i] >= in.lm.ceiling_w"),
    ("Dump and FP pre-emption rows swapped", "{ROW_L1, ROW_L2, ROW_L3", "{ROW_L2, ROW_L1, ROW_L3"),
    ("operator-needed after the waits", "{ROW_L1, ROW_L2, ROW_L3, ROW_L4, ROW_L5, ROW_L6, ROW_L7, ROW_L8, ROW_L9, ROW_L10}",
     "{ROW_L1, ROW_L2, ROW_L3, ROW_L4, ROW_L6, ROW_L7, ROW_L8, ROW_L9, ROW_L5, ROW_L10}"),
    ("owner grace doubled", "constexpr uint32_t kOwnerGraceMs = 10000u;", "constexpr uint32_t kOwnerGraceMs = 20000u;"),
    ("the boot-not-loaded row removed", "if (!g.boot_loaded) {", "if (false) {"),
    ("marker-lost evidence ignored", "if (absent_now && x.retry_on_raw) {", "if (false) {"),
    ("the absence-accepted re-run keeps L6", "r.alt_plan_absence_accepted = eval_core(in, true, clear_dom, use_snapshot, 1).plan;",
     "r.alt_plan_absence_accepted = eval_core(in, false, clear_dom, use_snapshot, 1).plan;"),
    ("BLOCKED_DURABLE_UNKNOWN projects the wrong FB-A result", "FAILBACK_RESULT_BLOCKED_MARKER_DIVERGENCE",
     "FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED"),
    ("policy-A range starts one row late", "(r.row >= ROW_L12 && r.row <= ROW_L26)", "(r.row >= ROW_L13 && r.row <= ROW_L26)"),
    ("CTX mismatch tested after out-of-domain",
     "else if (r.ctx_mismatch_mask != 0)\n          w = mk(ROW_L23, PLAN_BLOCKED_CONTEXT_MISMATCH, ctx_reason(r.ctx_mismatch_mask), BD_LIVE);\n        else if (r.out_of_domain_mask != 0)\n          w = mk(ROW_L24, PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN, ood_reason(r.out_of_domain_mask, live[0]), BD_LIVE);",
     "else if (r.out_of_domain_mask != 0)\n          w = mk(ROW_L24, PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN, ood_reason(r.out_of_domain_mask, live[0]), BD_LIVE);\n        else if (r.ctx_mismatch_mask != 0)\n          w = mk(ROW_L23, PLAN_BLOCKED_CONTEXT_MISMATCH, ctx_reason(r.ctx_mismatch_mask), BD_LIVE);"),
    ("overlay rule ignores the lock", "g.bus.manual_write_in_progress || g.bus.correction_in_progress;", "false;"),
    ("a stable supervised state still emits the L branch", "const bool effective_lost = in.mode == MODE_IF_LOST || in.sup.state == 3 || in.sup.episode_open;",
     "const bool effective_lost = true;"),
    ("a close always self-clears", "return (ep_kind == EPK_N && edge_plan == PLAN_WOULD_ALREADY_MATCH) ? (uint8_t) FBF_P : (uint8_t) FBF_A;",
     "return (uint8_t) FBF_P;"),
    ("the export-hazard obligation flag is never set (the soak would count no hazard time)", "r.hazard_obligation = bad_domain;",
     "r.hazard_obligation = false;"),
    ("Inputs `alt` renders the strict plan instead of the absence-accepted one", "ecco_fbcap::put_u(t, plan.alt_plan_absence_accepted);",
     "ecco_fbcap::put_u(t, plan.plan);"),
)


def section_host() -> None:
    print("\n[2] host C++")
    cxx = cx.find_compiler()
    check("a C++ compiler is available (this check fails rather than skips)", cxx is not None)
    if cxx is None:
        return
    scen = scenario_cases()
    rnd = random_cases(160, seed=7)
    src = cxx_source(scen + rnd, "")
    for std, rc, out in compile_both(src):
        check(f"{std}: the header evaluates the 81 rows + readiness pairs + {len(rnd)} seeded cases to the Python mirror's digest "
              f"(every output field and the Inputs text), -Wall -Wextra -Werror", rc == 0, out[-600:])
    for std, rc, out in compile_both('#include "ecco_failback_shadow.h"\n' + text_golden_source() + "int main() { return 0; }\n"):
        check(f"{std}: exact Inputs-text goldens, plan / state names, FB-A mapping and the FB-F latch model", rc == 0, out[-600:])
    check("the digest is sensitive: flipping one expected digest makes the compile fail",
          compile_both(src.replace("parity case 3", "parity case 3x").replace("0x", "0x1", 1))[0][1] != 0)

    # mutants: each must be a real compile rejection of the same static_asserts
    base_src = cxx_source(scen, "")

    def run_mutant(m):
        name, old, new = m
        n = HEADER_TEXT.count(old)
        if n != 1:
            return name, None, f"anchor found {n}x"
        rc, out = cx.compile_source(base_src, "gnu++17", {"ecco_failback_shadow.h": HEADER_TEXT.replace(old, new)})
        return name, rc, out

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_mutant, HEADER_MUTANTS))
    for name, rc, out in results:
        check(f"header mutant killed: {name}", rc is not None and rc != 0 and rc != 127, out[-200:] if rc is None or rc == 0 else "")
    check(f"all {len(results)} header mutants killed (21 expected), none surviving",
          len(results) == len(HEADER_MUTANTS) == 21 and all(r[1] not in (None, 0) for r in results))


# ===========================================================================
# [3] real compile of the tick lambdas
# ===========================================================================
def tick_lambdas():
    ivs = [iv for iv in FW["interval"] if "failback_shadow_ready" in yaml.dump(iv["then"])]
    assert len(ivs) == 1
    then = ivs[0]["then"]
    return then[0]["lambda"], then[1]["lambda"]


def build_tick_tu(fw: dict, lam0: str, lam1: str) -> str:
    import _fbb1_lambda_compile as lc
    lams = [lc.Lam("fbc_l0", "void", "", lam0), lc.Lam("fbc_l1", "void", "", lam1)]
    src = lc.build_source(fw, lams)
    src = src.replace('#include "ecco_fallback_capture.h"\n', '#include "ecco_fallback_capture.h"\n#include "ecco_failback_shadow.h"\n', 1)
    src = src.replace("static uint32_t millis() { return 12345; }",
                      "static uint32_t millis() { return 12345; }\nstatic uint64_t millis_64() { return 12345; }", 1)
    return src


def compile_tick(src: str, std: str, ov: dict | None = None):
    import _fbb1_lambda_compile as lc
    hdr = {"ecco_failback_shadow.h": HEADER_TEXT}
    hdr.update(ov or {})
    return lc.compile_source(src, std, extra_headers=hdr)


def section_lambda() -> None:
    print("\n[3] lambda compile")
    import _fbb1_lambda_compile as lc
    lam0, lam1 = tick_lambdas()
    try:
        src = build_tick_tu(FW, lam0, lam1)
    except ValueError as e:
        check("the FB-C tick lambdas build into a translation unit with the stub ESPHome types", False, str(e))
        return
    for std in ("gnu++17", "gnu++20"):
        rc, out = compile_tick(src, std)
        check(f"{std}: the REAL FB-C interval lambdas (static asserts + tick) compile against the real headers, -Wall -Wextra -Werror "
              "(log formats are printf-checked)", rc == 0, out[-1200:])
    rc, out = compile_tick(build_tick_tu(FW, lam0, lam1.replace("in.lm.cache.polling", "in.lm.cache.pollingX", 1)), "gnu++17")
    check("negative control: a misspelled ShadowInputs field is a real compile error", rc != 0 and rc != 127)
    rc, out = compile_tick(build_tick_tu(FW, lam0, lam1.replace("ecco_failback_shadow::inputs_text(in, rd)", "ecco_failback_shadow::inputs_text(in)", 1)), "gnu++17")
    check("negative control: a wrong-arity evaluator call is a real compile error", rc != 0 and rc != 127)
    rc, out = compile_tick(build_tick_tu(FW, lam0.replace("== ecco_fbcap::LIVE_CACHE_MAX_AGE_MS", "== 1UL", 1), lam1), "gnu++17")
    check("negative control: the cache-age pin is a REAL static_assert (a value other than the shared constant does not compile)",
          rc != 0 and rc != 127)


# ===========================================================================
# [4] static pins
# ===========================================================================
Z3_TOKENS = (
    "modbus_client", "write_multiple_registers", "read_holding_registers", "inverter_modbus", "inverter_uart", "commit_record",
    "load_record", "nvs_", "make_preference", "global_preferences", ".save(", "sync(", "RTC_NOINIT", "RTC_DATA_ATTR", "esp_attr",
    "script.execute", ".execute(", ".stop(", "request_", "turn_on", "turn_off", "press(", "set_value", "make_call", "perform(",
    "set_option", "set_level", "App.", "safe_reboot", "set_reboot_timeout", "esp_restart", "arch_restart", "esp_reset_reason",
    "global_api_server", "self_partial", "fallback_profile_execute", "free_power_recovery_execute", "delay", "wait_until",
    "supervision_have_valid", "start_journal", "start_free_power_override).execute", "RTC_NOINIT",
)
HEADER_Z3 = ("modbus_client", "write_multiple_registers", "read_holding_registers", "inverter_modbus", "inverter_uart", "commit_record",
             "load_record", "nvs_", "make_preference", "global_preferences", "RTC_NOINIT", ".execute(", "script.", ".press(", "make_call",
             ".perform(", "App.", "reboot", "supervision_have_valid")

READ_ALLOW_RE = re.compile(
    r"^(supervision_(state|stable|valid_count|last_valid_ms|last_gap_ms|first_valid_ms|lost_events|generation|boot_nonce)|"
    r"api_client_connected_sensor|ntp_synced|ntp_time|configuration_(online|polling)|"
    r"free_power_(operation_in_progress|snapshot_valid|snapshot_reg\d+|marker_boot_load|marker_state|recovery_metadata_corrupt|"
    r"operator_needed|active_persisted|restore_requested|recovery_force_in_progress|recovery_accept_in_progress|end_epoch|"
    r"restore_next_attempt_ms|lease_context_reg244|start_attempts)|"
    r"dump_(operation_in_progress|snapshot_valid|marker_boot_load|marker_state|recovery_metadata_corrupt|containment_state|"
    r"operator_needed|active_persisted|restore_requested|end_epoch|restore_next_attempt_ms|force_restore_bypass|snapshot_data_loaded|"
    r"snapshot_reg\d+|start_attempts)|"
    r"reg244_(apply_in_progress|snapshot_valid|marker_boot_load|marker_state|recovery_metadata_corrupt|last_applied_valid|"
    r"last_applied_value|apply_attempts|restore_attempts)|"
    r"manual_(write_in_progress|write_attempts|config_raw_cache_valid)|manual_cfg_reg\d+_raw|fbc_raw_\w+|"
    r"correction_in_progress|verification_pending|verification_read_active|diag_(write|correction)_lock_(held|since_ms)|"
    r"cfg_block_b_(seq|ok_ms|dispatch_seq|response_dispatch_seq)|"
    r"fallback_profile_(boot_loaded|bytes|class|load|why|read_anomaly|save_unconfirmed|probe_latch|op_in_progress|"
    r"live_fence_seq|live_edge_seq))$")
OWNER_SCRIPTS = {"start_free_power_override", "restore_free_power_snapshot", "restore_free_power_snapshot_dispatch",
                 "free_power_recovery_review", "free_power_recovery_review_dispatch", "free_power_recovery_force_restore",
                 "free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state",
                 "free_power_recovery_accept_current_state_dispatch", "start_dump_to_grid_override", "restore_dump_to_grid_snapshot",
                 "dump_controller_tick", "dump_lockout_containment", "apply_reg244_settings", "restore_reg244_snapshot",
                 "fallback_profile_capture_dispatch", *(f"apply_manual_slot{n}" for n in range(1, 7))}
FBC_TEXT_IDS = ("failback_shadow_state_text", "failback_shadow_episode_text", "failback_shadow_soak_text",
                "failback_shadow_verdict_text", "failback_shadow_inputs_text")


def strip_code(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', code)


def lam1_assign_targets(code: str) -> set:
    return {m.group(1) for m in re.finditer(r"\bid\((\w+)\)(?:\[[^\]]*\])?\s*(?:\+\+|--|(?:[+\-*/%&|^]|<<|>>)?=(?!=))", strip_code(code))}


def static_detectors(text: str, fw: dict, header: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    ivs = [iv for iv in fw["interval"] if "failback_shadow_ready" in yaml.dump(iv["then"])]
    iv = ivs[0]
    lam0, lam1 = iv["then"][0]["lambda"], iv["then"][1]["lambda"]
    code1 = strip_code(lam1)
    # Z2: placement and shape
    z2 = []
    pra = [k for k, i in enumerate(fw["interval"]) if "supervision_have_valid" in yaml.dump(i["then"])]
    idx = fw["interval"].index(iv)
    if len(ivs) != 1:
        z2.append("not exactly one FB-C interval")
    if iv.get("interval") != "1s":
        z2.append(f"interval {iv.get('interval')!r}")
    if [list(a) for a in iv["then"]] != [["lambda"], ["lambda"]]:
        z2.append("then is not [lambda(static_asserts), lambda(tick)]")
    if len(pra) != 1 or idx != pra[0] - 1:
        z2.append("FB-C interval is not immediately before the PR-A tick")
    if "static_assert" in lam1 or "static_assert" not in lam0:
        z2.append("static_asserts must live in lambda 0 only")
    out["Z2 placement"] = z2
    # Z3: token ban over the tick and the header
    z3 = [f"token {t!r} in the tick" for t in Z3_TOKENS if t in code1 and t != "delay_ok"]
    if "supervision_have_valid" in yaml.dump(iv):
        z3.append("supervision_have_valid in the interval (code or comment)")
    hdr_code = header
    z3 += [f"token {t!r} in the header" for t in HEADER_Z3 if t in hdr_code]
    hdr_stripped = strip_code(header)
    z3 += [f"discipline token {t!r} in the header code" for t in ("esphome", "millis(", "static ", "inline ") if t in hdr_stripped]
    if re.search(r"\bid\(", hdr_stripped):
        z3.append("id( in the header code")
    out["Z3 token ban"] = z3
    # Z4: assignments / publishes / reads
    own = {g["id"] for g in fw["globals"] if str(g["id"]).startswith("failback_shadow_")}
    z4 = []
    bad = sorted(t for t in lam1_assign_targets(lam1) if t not in own)
    if bad:
        z4.append(f"assigns non-FB-C ids {bad}")
    pub = set(re.findall(r"id\((\w+)\)\.publish_state", code1))
    if not pub <= set(FBC_TEXT_IDS):
        z4.append(f"publishes {sorted(pub - set(FBC_TEXT_IDS))}")
    reads = set(re.findall(r"id\((\w+)\)", code1))
    scripts = {s["id"] for s in fw["script"]}
    for r in sorted(reads):
        if r in own or r in FBC_TEXT_IDS:
            continue
        if r in scripts:
            if r not in OWNER_SCRIPTS:
                z4.append(f"script {r} is referenced")
            if len(re.findall(rf"id\({r}\)(?!\.is_running\(\))", code1)):
                z4.append(f"script {r} is used other than through is_running()")
            continue
        if not READ_ALLOW_RE.match(r):
            z4.append(f"read outside the allowlist: {r}")
    meth = set(re.findall(r"id\(\w+\)\s*(?:->|\.)\s*(?!state\b|publish_state\b|now\b|is_running\b)(\w+)\(", code1))
    if meth:
        z4.append(f"entity method calls {sorted(meth)}")
    out["Z4 assignments / reads"] = z4
    # Z4b at full scope (S3 Z4b): every fbc_raw_* occurrence in the LIVE firmware code is a declaration, a config-poll assignment,
    # a B10 Live Match read or an FB-C tick read - exact count, every YAML node kind covered (not only scripts)
    out["Z4b fbc_raw_* live-firmware allowlist (declarations / poll / B10 / FB-C tick, exact count)"] = fbc_raw_live_pin(fw)
    # Z5: non-authority
    z5 = []
    rest = {}
    for k, v in chain_tree(fw).items():
        if k == "globals":
            rest[k] = [g for g in v if str(g["id"]) not in own]
        elif k == "text_sensor":
            rest[k] = [t for t in v if t.get("id") not in FBC_TEXT_IDS]
        elif k == "interval":
            rest[k] = [i for i in v if "failback_shadow" not in yaml.dump(i)]
        elif k == "substitutions":
            rest[k] = {a: b for a, b in v.items() if not a.startswith("ecco_failback_shadow_")}
        elif k == "_substitutions":
            continue
        elif k == "esphome":
            rest[k] = {a: ([x for x in b if x != scope.INCLUDE_ENTRY] if a == "includes" else b) for a, b in v.items()}
        elif k == "_text":
            continue
        else:
            rest[k] = v
    dumped = yaml.dump(rest)
    if "failback_shadow" in dumped:
        z5.append("failback_shadow referenced by a YAML node other than FB-C's own")
    out["Z5 non-authority"] = z5
    # Z6: RAM only
    z6 = []
    gl = [g for g in fw["globals"] if str(g["id"]).startswith(("failback_shadow_", "fbc_raw_"))]
    bad = [g["id"] for g in gl if g.get("restore_value") not in (False, "no")]
    if bad:
        z6.append(f"restore_value not 'no': {bad}")
    yes = sorted(g["id"] for g in fw["globals"] if g.get("restore_value") in (True, "yes"))
    if yes != ["reg244_last_applied_valid", "reg244_last_applied_value"]:
        z6.append(f"restore_value: yes set changed {yes}")
    missing = [i for i in scope.NEW_GLOBAL_IDS if i not in {g["id"] for g in fw["globals"]}]
    if missing:
        z6.append(f"declared FB-C2 globals missing {missing}")
    out["Z6 RAM only"] = z6
    # Z7: durable surface
    z7 = []
    for pat in (r"ecco_durable::commit_record", r"ecco_durable::load_record", r"nvs_", r"make_preference", r"global_preferences",
                r"RTC_NOINIT", r"\.sync\("):
        if re.search(pat, code1) or re.search(pat, header):
            z7.append(f"durable token {pat} in the shadow code")
    out["Z7 durable surface"] = z7
    return out


def chain_tree(fw: dict) -> dict:
    return {k: v for k, v in fw.items()}


# ===========================================================================
# Z4b at full scope. test_fallback_live_match.py (FB-B3) reads the firmware AS OF fbb3 (chain mechanism, kept), so its
# RAW_CACHE_EXT pins (no stray fbc_raw_* occurrence; exactly 19 tokens) no longer apply to the CURRENT firmware. This restores
# them for the live firmware, with the FB-C2 shadow tick as the one added reader: every fbc_raw_* token in the firmware CODE
# (comments excluded) is one of the six declarations, the six config-poll assignments (plus the filled flag's own right-hand side),
# the six reads of the B10 Live Match refresh script, or the six reads of FB-C lambda 1 - exactly 25 - and any other YAML node
# (script, interval, button, sensor, switch, number, select, API action, on_boot, ...) naming one is an undeclared consumer, i.e.
# a potential write basis (S3 11.5 / Z4b: the caches are kept out of every write basis).
# ===========================================================================
RAW_CACHE_IDS = ("fbc_raw_230", "fbc_raw_243", "fbc_raw_245", "fbc_raw_247", "fbc_raw_248", "fbc_raw_filled")
RAW_POLL_SCRIPT = "poll_inverter_configuration_dispatch"
RAW_B10_SCRIPT = "fallback_profile_live_refresh"
RAW_TOTAL = 6 + 7 + 6 + 6  # declarations + poll (6 assignments + the filled RHS) + B10 reads + FB-C reads (= FB-B3's 19 + 6)


def _strings_of(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                yield k
            yield from _strings_of(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings_of(v)


def _raw_tokens(node) -> list:
    return [t for s in _strings_of(node) for t in re.findall(r"\bfbc_raw_\w+", strip_code(s))]


def _raw_assigns(node) -> list:
    return [t for s in _strings_of(node) for t in re.findall(r"\bid\((fbc_raw_\w+)\)\s*=(?!=)", strip_code(s))]


def fbc_raw_live_pin(fw: dict) -> list[str]:
    bad, total = [], 0
    for section, value in fw.items():
        if section.startswith("_"):
            continue
        items = value if isinstance(value, list) else [value]
        for n, item in enumerate(items):
            toks = _raw_tokens(item)
            if not toks:
                continue
            total += len(toks)
            ident = item.get("id") if isinstance(item, dict) else None
            label = f"{section}[{ident if ident else n}]"
            if section == "globals" and ident in RAW_CACHE_IDS:
                if toks != [ident]:
                    bad.append(f"{label}: the declaration names other fbc_raw_ tokens {toks}")
                continue
            if section == "script" and ident == RAW_POLL_SCRIPT:
                if sorted(_raw_assigns(item)) != sorted(RAW_CACHE_IDS) or len(toks) != 7:
                    bad.append(f"{label}: want exactly the six assignments plus the filled flag's own right-hand side (7 tokens), got "
                               f"{len(toks)} tokens, assignments {sorted(_raw_assigns(item))}")
                continue
            if section == "script" and ident == RAW_B10_SCRIPT:
                if sorted(toks) != sorted(RAW_CACHE_IDS) or _raw_assigns(item):
                    bad.append(f"{label}: want exactly one read of each of the six words and no assignment, got {sorted(toks)}")
                continue
            if section == "interval" and isinstance(item, dict) and "failback_shadow_ready" in yaml.dump(item.get("then")):
                then = item.get("then") or []
                l0 = _raw_tokens(then[0]) if then else []
                l1 = _raw_tokens(then[1]) if len(then) > 1 else []
                if l0 or sorted(l1) != sorted(RAW_CACHE_IDS) or _raw_assigns(item):
                    bad.append(f"{label} (the FB-C tick): want one read of each of the six words in lambda 1 only and no assignment, "
                               f"got lambda 0 {l0}, lambda 1 {sorted(l1)}")
                continue
            bad.append(f"{label} references {sorted(set(toks))}: an undeclared fbc_raw_* consumer")
    if total != RAW_TOTAL:
        bad.append(f"fbc_raw_* occurs {total} times in the firmware code, want exactly {RAW_TOTAL} "
                   "(6 declarations + 7 poll + 6 B10 Live Match + 6 FB-C tick)")
    return bad


def insert_after_line(text: str, anchor: str, code: str) -> str:
    """A negative-control mutation: `code` on a new line right after the line holding the (unique) anchor, same indentation."""
    n = text.count(anchor)
    if n != 1:
        raise AssertionError(f"mutation anchor occurs {n} times, want 1: {anchor[:70]!r}")
    i = text.index(anchor)
    line_start = text.rfind("\n", 0, i) + 1
    indent = text[line_start:i][:len(text[line_start:i]) - len(text[line_start:i].lstrip(" "))]
    line_end = text.index("\n", i)
    return text[:line_end] + "\n" + indent + code + text[line_end:]


FBC_RAW_CONTROLS = (
    # (what the mutant adds, anchor, mutation)
    ("an interval (the PR-A supervision tick) reads fbc_raw_243", "id(supervision_lost_events) += 1;", "if (id(fbc_raw_243) == 0) {}"),
    ("a button (Read Inverter Clock) reads fbc_raw_248", "id(clock_difference_valid) = false;", "if (id(fbc_raw_248) == 0) {}"),
    ("the API action fallback_profile_execute reads fbc_raw_230", "id(fallback_profile_exec_action) = action.str();",
     "if (id(fbc_raw_230) == 0) {}"),
    ("a writer script (start_free_power_override) reads fbc_raw_245", "id(free_power_start_attempts)++;", "if (id(fbc_raw_245) == 0) {}"),
    ("on_boot reads fbc_raw_243", "id(fallback_profile_boot_loaded) = true;", "if (id(fbc_raw_243) == 0) {}"),
    ("a seventh read inside the FB-C tick", "in.lm.cache.filled = id(fbc_raw_filled);", "if (id(fbc_raw_247) == 0) {}"),
    ("an extra read inside the config poll script", "id(manual_cfg_reg232_raw) = values[32];", "if (id(fbc_raw_243) == 0) {}"),
    ("an extra read inside the B10 Live Match refresh script", "in.ceiling_w = ${ecco_inverter_tou_power_ceiling_w};",
     "if (id(fbc_raw_243) == 0) {}"),
)


def fbc_raw_negative_controls() -> list[tuple[str, list[str]]]:
    out = []
    for what, anchor, code in FBC_RAW_CONTROLS:
        try:
            text = insert_after_line(LIVE_TEXT, anchor, code)
        except AssertionError as ex:
            out.append((f"{what} [mutation anchor problem: {ex}]", []))  # an unusable control reads as NOT detected: it fails
            continue
        out.append((what, fbc_raw_live_pin(chain.load_fw(text))))
    # a template binary sensor lambda (an entity, not a script / interval) gains a read
    t = LIVE_TEXT.replace("      return id(free_power_snapshot_valid);\n", "      return id(free_power_snapshot_valid) && id(fbc_raw_filled);\n", 1)
    out.append(("a template sensor lambda reads fbc_raw_filled",
                fbc_raw_live_pin(chain.load_fw(t)) if t != LIVE_TEXT else []))
    return out


# ===========================================================================
# Z11 (S3 section 10 Z11, FINAL 6.8): the Verdict's BLOCKED_* plan names match exactly one Energy Actions card regex,
# `^BLOCKED` in schedule.ts isScheduleBlocked(). S3 allows that only with proof that the regex cannot consume the shadow. The proof
# below reads the card source and the committed Home Assistant configuration (it changes no behaviour) and pins:
#   (i)    the only card regex any plan name matches is that one literal, in that one function, with that exact body;
#   (ii)   the identifier isScheduleBlocked occurs only as its definition, its import, and two direct calls `isScheduleBlocked(lastResult)`
#          (never passed as a callback, re-exported or called with another argument);
#   (iii)  each call sits in _renderLaterPanel / _renderDumpLaterPanel, whose `lastResult` is assigned exactly once as
#          `this._entityState(schedule.last_result)` from the method's typed `schedule` parameter, which is never reassigned;
#   (iv)   _entityState reads nothing but hass.states[<configured entity id>].state;
#   (v)    no card code builds or mutates a `last_result`: its only literal values are the two schedule helpers (stub defaults);
#   (vi)   every committed dashboard's Energy Actions card configures `last_result` only as those two helpers and names no shadow
#          entity or HA shadow decoder;
#   (vii)  the only Home Assistant files that name the two helpers are the two schedule packages (their only writers) and the
#          dashboards, and the schedule packages name no shadow entity or decoder - so no shipped automation can route a shadow
#          string into the helpers;
#   (viii) the card source names no Failback Shadow entity / decoder at all.
# ===========================================================================
SCHEDULE_RESULT_HELPERS = ("input_text.ecco_free_power_schedule_last_result", "input_text.ecco_dump_to_grid_schedule_last_result")
SCHEDULE_PACKAGES = ("home-assistant/packages/ecco_free_power_schedule.yaml", "home-assistant/packages/ecco_dump_to_grid_schedule.yaml")
# the five firmware shadow entities (ids, names, HA entity ids) and the FB-C3 HA shadow decoder (sensor.ecco_shadow_check,
# binary_sensor.ecco_shadow_episode_open) and anything named like them
SHADOW_TOKENS = ("failback_shadow", "failback shadow", "ecco_shadow_", "shadow_check", "shadow_episode", "shadow_verdict")
IS_BLOCKED_DEF = ("export function isScheduleBlocked(lastResult: string | undefined): boolean {\n"
                  "  return !!lastResult && /^BLOCKED/i.test(lastResult.trim());\n}")
ENTITY_STATE_DEF = ("  private _entityState(entityId: string | undefined): string | undefined {\n"
                    "    if (!entityId || !this.hass) return undefined;\n"
                    "    return this.hass.states[entityId]?.state;\n  }")
LAST_RESULT_ASSIGN = "const lastResult = this._entityState(schedule.last_result);"


class _AnyTagLoader(yaml.SafeLoader):
    """Dashboards may carry HA-specific tags (!include, !secret, ...): read them as plain values."""


def _any_tag(loader, _suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_AnyTagLoader.add_multi_constructor("!", _any_tag)


def _walk_dicts(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_dicts(v)


def card_sources() -> dict[str, str]:
    return {f.relative_to(CARD_SRC).as_posix(): f.read_text(encoding="utf-8")
            for f in sorted(CARD_SRC.glob("*.ts")) + sorted((CARD_SRC / "utils").glob("*.ts"))}


def ha_texts() -> dict[str, str]:
    out = {}
    for f in sorted((ROOT / "home-assistant").rglob("*")):
        rel = f.relative_to(ROOT).as_posix()
        if not f.is_file() or rel.startswith("home-assistant/tests/") or "/__pycache__/" in rel or f.suffix not in (".yaml", ".yml"):
            continue
        out[rel] = f.read_text(encoding="utf-8")
    return out


def _regex_literals(src: str) -> list[tuple[str, str]]:
    pats = re.findall(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", src)
    pats += re.findall(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", src)
    return pats


def z11_card_scope(card: dict[str, str], ha: dict[str, str]) -> list[str]:
    bad = []
    names = sorted({sh.plan_name(c) for c in range(256)})
    # (i) the only regex any Verdict name matches, and where it lives
    hits = sorted({(f, p, fl) for f, src in card.items() for p, fl in _regex_literals(src)
                   if any(re.search(p, n, re.I if "i" in fl else 0) for n in names)})
    if hits != [("schedule.ts", "^BLOCKED", "i")]:
        bad.append(f"(i) the card regexes a Verdict name matches are {hits}, want only schedule.ts /^BLOCKED/i")
    lits = [(f, m.start()) for f, src in card.items() for m in re.finditer(r"/\^BLOCKED/", src)]
    if len(lits) != 1 or lits[0][0] != "schedule.ts" or card.get("schedule.ts", "").count(IS_BLOCKED_DEF) != 1:
        bad.append(f"(i) the /^BLOCKED/ literal must occur once, inside the pinned isScheduleBlocked() body: {lits}")
    # (ii) every occurrence of the identifier
    occ = {f: re.findall(r"\bisScheduleBlocked\b[^\n]{0,40}", src) for f, src in card.items()}
    occ = {f: v for f, v in occ.items() if v}
    main = card.get("ecco-energy-actions-card.ts", "")
    calls = re.findall(r"\bisScheduleBlocked\s*\(([^()]*)\)", main)
    imports = re.findall(r"^\s*isScheduleBlocked,\s*$", main, re.M)
    if set(occ) != {"schedule.ts", "ecco-energy-actions-card.ts"} or len(occ["schedule.ts"]) != 1 or \
            len(occ.get("ecco-energy-actions-card.ts", [])) != 3 or calls != ["lastResult", "lastResult"] or len(imports) != 1:
        bad.append(f"(ii) isScheduleBlocked must be defined once and used only as one import + two calls (lastResult): {occ}")
    # (iii) the argument's only source, per call site
    methods = []
    for m in re.finditer(r"\bisScheduleBlocked\s*\(lastResult\)", main):
        head = list(re.finditer(r"\n  private (_render\w*LaterPanel)\(schedule: (ScheduleEntities|DumpScheduleEntities)\): TemplateResult \{",
                                main[:m.start()]))
        if not head:
            bad.append("(iii) a call site outside the two schedule LATER panels")
            continue
        body = main[head[-1].end():m.start()]
        methods.append(head[-1].group(1))
        if "\n  private " in body or "\n  }\n" in body:
            bad.append(f"(iii) call site not inside {head[-1].group(1)}")
        if body.count(LAST_RESULT_ASSIGN) != 1 or len(re.findall(r"\blastResult\s*=(?!=)", body)) != 1:
            bad.append(f"(iii) {head[-1].group(1)}: lastResult must be assigned exactly once as `{LAST_RESULT_ASSIGN}`")
        if re.search(r"\bschedule\s*=(?!=)", body):
            bad.append(f"(iii) {head[-1].group(1)}: the schedule parameter is reassigned")
    if sorted(methods) != ["_renderDumpLaterPanel", "_renderLaterPanel"]:
        bad.append(f"(iii) want one call in each schedule LATER panel, got {methods}")
    # (iv) _entityState reads hass.states[entity].state only
    if main.count(ENTITY_STATE_DEF) != 1:
        bad.append("(iv) _entityState is not the pinned `hass.states[entityId]?.state` reader")
    # (v) no card code builds or mutates a last_result: literals only the two helpers, no assignment
    lr = [v for src in card.values() for v in re.findall(r"\blast_result\s*:\s*\"([^\"]*)\"", src)]
    if sorted(lr) != sorted(SCHEDULE_RESULT_HELPERS) or any(re.search(r"\.last_result\s*=(?!=)", src) for src in card.values()):
        bad.append(f"(v) last_result literals in the card are {lr} (want only the two schedule helpers) or one is assigned at runtime")
    # (viii) the card names no shadow entity / decoder
    for f, src in card.items():
        low = src.lower()
        hit = [t for t in SHADOW_TOKENS if t in low]
        if hit:
            bad.append(f"(viii) {f} names a shadow entity / decoder: {hit}")
    # (vi) every committed dashboard's Energy Actions card
    ncards = 0
    for rel, text in ha.items():
        if "custom:ecco-energy-actions-card" not in text:
            continue
        try:
            doc = yaml.load(text, Loader=_AnyTagLoader)
        except yaml.YAMLError as ex:
            bad.append(f"(vi) {rel} does not parse: {str(ex)[:80]}")
            continue
        for d in _walk_dicts(doc):
            if d.get("type") != "custom:ecco-energy-actions-card":
                continue
            ncards += 1
            vals = [x.get("last_result") for x in _walk_dicts(d) if "last_result" in x]
            if not set(vals) <= set(SCHEDULE_RESULT_HELPERS):
                bad.append(f"(vi) {rel}: an Energy Actions card configures last_result {vals}")
            dumped = yaml.dump(d).lower()
            hit = [t for t in SHADOW_TOKENS if t in dumped]
            if hit:
                bad.append(f"(vi) {rel}: an Energy Actions card names a shadow entity / decoder {hit}")
    if ncards == 0:
        bad.append("(vi) no Energy Actions card config found in home-assistant/ (the scan saw nothing)")
    # (vii) the helpers' writers
    for rel, text in ha.items():
        if not any(hid in text for hid in SCHEDULE_RESULT_HELPERS):
            continue
        if rel in SCHEDULE_PACKAGES:
            low = text.lower()
            hit = [t for t in SHADOW_TOKENS if t in low]
            if hit:
                bad.append(f"(vii) {rel} (a writer of the schedule result helpers) names a shadow entity / decoder {hit}")
        elif not rel.startswith("home-assistant/dashboards/"):
            bad.append(f"(vii) {rel} names a schedule result helper: an undeclared writer / reader")
    if not all(p in ha for p in SCHEDULE_PACKAGES):
        bad.append("(vii) a schedule package is missing from the scan")
    return bad


def z11_negative_controls() -> list[tuple[str, list[str]]]:
    card, ha = card_sources(), ha_texts()
    main = card["ecco-energy-actions-card.ts"]
    shadow = "sensor.ecco_clock_dongle_ecco_failback_shadow_verdict"
    out = []

    def run(what, c=None, h=None):
        out.append((what, z11_card_scope(c if c is not None else card, h if h is not None else ha)))

    run("a call site feeds the regex the shadow Verdict",
        dict(card, **{"ecco-energy-actions-card.ts": main.replace("const blocked = isScheduleBlocked(lastResult);",
                                                                  f"const blocked = isScheduleBlocked(this._entityState(\"{shadow}\"));", 1)}))
    run("a second /^BLOCKED/i literal in another card file",
        dict(card, **{"dumpState.ts": card["dumpState.ts"] + "\nexport const X_BLOCKED = (t: string) => /^BLOCKED/i.test(t);\n"}))
    run("isScheduleBlocked passed as a callback",
        dict(card, **{"ecco-energy-actions-card.ts": main + "\nconst _probe = [\"a\"].filter(isScheduleBlocked);\n"}))
    run("lastResult re-sourced from another entity",
        dict(card, **{"ecco-energy-actions-card.ts": main.replace(LAST_RESULT_ASSIGN, LAST_RESULT_ASSIGN.replace(
            "schedule.last_result", "\"sensor.ecco_shadow_check\""), 1)}))
    run("a third last_result default pointing at a shadow entity",
        dict(card, **{"ecco-energy-actions-card.ts": main.replace(
            'last_result: "input_text.ecco_free_power_schedule_last_result",',
            'last_result: "input_text.ecco_free_power_schedule_last_result",\n        x: { last_result: "' + shadow + '" },', 1)}))
    dash = "home-assistant/dashboards/ecco_pro.yaml"
    run("the dashboard's Energy Actions card reads the shadow Verdict as last_result",
        h=dict(ha, **{dash: ha[dash].replace("last_result: input_text.ecco_free_power_schedule_last_result",
                                             f"last_result: {shadow}", 1)}))
    pkg = SCHEDULE_PACKAGES[0]
    run("a schedule package writes the HA shadow decoder into its result helper",
        h=dict(ha, **{pkg: ha[pkg] + "\n# value: \"{{ states('sensor.ecco_shadow_check') }}\"\n"}))
    run("an undeclared package writes a schedule result helper",
        h=dict(ha, **{"home-assistant/packages/zz_probe.yaml": "script:\n  zz:\n    sequence:\n      - action: input_text.set_value\n"
                                                              "        target:\n          entity_id: " + SCHEDULE_RESULT_HELPERS[0] + "\n"}))
    return out


def section_static() -> None:
    print("\n[4] static pins")
    res = static_detectors(LIVE_TEXT, FW, HEADER_TEXT)
    for name, v in res.items():
        check(f"{name}: clean", not v, "; ".join(v[:4]))
    # header discipline
    code = re.sub(r"//[^\n]*", "", HEADER_TEXT)
    incl = re.findall(r'#include\s+[<"]([^>"]+)[>"]', code)
    check("the header includes only standard headers and the shared FB-B capture header",
          set(incl) <= {"array", "cstddef", "cstdint", "ecco_fallback_capture.h"}, str(incl))
    check("the header declares exactly one namespace and no non-constexpr namespace-scope object",
          len(re.findall(r"^namespace\s+\w+", code, re.M)) == 1 and not re.search(r"^(?:static\s+|inline\s+)", code, re.M))
    check("the header re-implements none of the shared classifiers / masks (it calls ecco_fbcap::)",
          all(f"ecco_fbcap::{n}" in HEADER_TEXT for n in (
              "classify_fp", "classify_dump", "classify_r244", "classify_bus", "live_trust", "e1_delta_mask", "ctx_mismatch_mask",
              "out_of_domain_mask", "info_mismatch_mask", "export_hazard", "live_effective_class")) and
          not re.search(r"constexpr\s+\S+\s+(classify_\w+|live_trust|e1_delta_mask|ctx_mismatch_mask|out_of_domain_mask)\s*\(", code))
    check("the Python mirror carries no token the SG-01 phase-0 harness forbids (self_partial / start_journal)",
          not re.search(r"self_partial|start_journal", (ROOT / "registry" / "failback_shadow.py").read_text(encoding="utf-8")))
    # reconciliation pins (owner request): the MAIN Free Power boot load is NOT touched by FB-C2 (BLK-13 stays FB-D5), and nothing assumes
    # retention globals that do not exist
    check("BLK-13: the MAIN Free Power operator_needed boot load is byte-for-byte unchanged (not gated on SV; FB-C2 absorbs it via the "
          "S4-D07 non-blocking stale flag / FP_MARKER_LOST)",
          LIVE_TEXT.count("id(free_power_operator_needed) = have_retry && retry.operator_needed != 0;") == 1 and
          scope.pre_fbc2_firmware(FBC2_TEXT).count("id(free_power_operator_needed) = have_retry && retry.operator_needed != 0;") == 1)
    ids = {g["id"] for g in FW["globals"]}
    absent = ("fp_lockout_cause", "dump_lockout_cause", "reg244_lockout_cause", "dump_retry_boot_on_raw")
    check("the architecture-described retention values that do not exist (fp / dump / reg244 lockout cause, dump_retry_boot_on_raw) are not "
          "global ids and are not referenced by the tick, the header or the mirror",
          not any(a in ids for a in absent) and not any(f"id({a})" in LIVE_TEXT or a in HEADER_TEXT for a in absent) and
          not any(a in (ROOT / "registry" / "failback_shadow.py").read_text(encoding="utf-8") for a in absent))
    sfp = fx.base()
    sfp.mode = sh.MODE_IF_LOST
    sfp.fp.retry_on_raw = True
    sfp.lm.g.fp.free_power_operator_needed = True
    rs_clear = sh.evaluate(sfp)
    sfp2 = copy.deepcopy(sfp)
    sfp2.lm.g.fp.free_power_marker_boot_load = cap.BOOT_LOAD_ABSENT
    rs_lost = sh.evaluate(sfp2)
    check("stale FP operator_needed (no snapshot): with a present CLEAR marker it is a NON-blocking flag; with an ABSENT marker it is "
          "BLOCKED_DURABLE_UNKNOWN / FP_MARKER_LOST (S4-D07 / row 66-67); never WOULD_APPLY",
          rs_clear.plan == 40 and rs_clear.fp_stale_operator_needed and rs_lost.plan == 21 and rs_lost.reason == sh.RS["FP_MARKER_LOST"])
    # the YAML include and substitution
    check("the header is an esphome include appended LAST (by FB-C2; checked as of fbc2 - FB-D1 appends its own after it)",
          chain.load_fw(FBC2_TEXT)["esphome"]["includes"][-1] == scope.INCLUDE_ENTRY and
          scope.INCLUDE_ENTRY in FW["esphome"]["includes"])
    check("the shadow cache-age substitution is 180000 and nothing else of the substitutions changed shape",
          FW["_substitutions"].get(scope.SUBSTITUTION[0]) == scope.SUBSTITUTION[1])
    # the evaluator is called exactly ONCE in the tick (MODE_IF_LOST) and only from the FB-C interval, and its readiness plan is the
    # Verdict (FINAL 8.5, S3 9.2 / 11.4, S5 2.3)
    ivs = [iv for iv in FW["interval"] if "failback_shadow_ready" in yaml.dump(iv["then"])]
    lam1 = ivs[0]["then"][1]["lambda"]
    code1 = strip_code(lam1)
    check("the tick calls evaluate() exactly ONCE, in MODE_IF_LOST (S3 11.4), and never feeds the plan back into an input",
          len(re.findall(r"ecco_failback_shadow::evaluate\(", code1)) == 1 and "in.mode = ecco_failback_shadow::MODE_IF_LOST;" in code1
          and "MODE_ACTUAL" not in code1 and len(re.findall(r"\bin\.mode\s*=", code1)) == 1)
    check("the Verdict is the readiness plan (`rd.plan`), WOULD_REMAIN_LATCHED (50) while the modelled latch is set - never a "
          "supervision row (FINAL 8.5, S3 9.2, S5 2.3)",
          code1.count("const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) "
                      "ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;") == 1 and "ac.plan" not in code1)
    check("the soak counts export-hazard time only while the evaluator reports an export-relevant lease obligation "
          "(FINAL 8.2 term; export_hazard itself unchanged and shared)",
          code1.count("if (rd.hazard_obligation) {") == 1 and code1.index("if (rd.hazard_obligation) {") <
          code1.index("id(failback_shadow_exh_yes_ms) =") < code1.index("id(failback_shadow_exh_unk_ms) ="))
    # Z4b negative controls: every undeclared fbc_raw_* reader kind is caught by the full-scope live pin
    for what, found in fbc_raw_negative_controls():
        check(f"Z4b negative control caught: {what}", bool(found), "NOT DETECTED")
    # Z11: the card's `^BLOCKED` regex cannot consume the shadow (proof over the card source and the HA configuration)
    z11 = z11_card_scope(card_sources(), ha_texts())
    check("Z11: the only card regex a Verdict name matches is schedule.ts /^BLOCKED/i in isScheduleBlocked(); its only callers are the two "
          "schedule LATER panels with lastResult = this._entityState(schedule.last_result); every configured last_result (card defaults "
          "and every committed dashboard) is one of the two schedule result helpers; their only writers are the two schedule packages; "
          "no card source, card config or writer names a Failback Shadow entity or the HA shadow decoder", not z11, "; ".join(z11[:4]))
    for what, found in z11_negative_controls():
        check(f"Z11 negative control caught: {what}", bool(found), "NOT DETECTED")
    outside = [l for l in LIVE_TEXT.splitlines() if "ecco_failback_shadow::" in l]
    inside = [l for l in yaml.dump(ivs[0]["then"]).splitlines() if "ecco_failback_shadow::" in l]
    check("ecco_failback_shadow:: is referenced only by lines of the FB-C tick lambda (every such YAML line sits inside the interval)",
          bool(outside) and len(outside) >= len(inside) > 0 and all(
              ("ecco_failback_shadow::" in l) for l in outside) and not any(
              "ecco_failback_shadow::" in l for l in scope.pre_fbc2_firmware(FBC2_TEXT).splitlines()))

    # measured authority counts before / after (chain-measured, never typed)
    base_texts = chain.CHAIN.as_of_all("fbb3", {chain.FIRMWARE: LIVE_TEXT})
    live_texts = chain.CHAIN.as_of_all("fbc2", {chain.FIRMWARE: LIVE_TEXT})
    mb, ml = chain.measure(base_texts), chain.measure(live_texts)
    print("    authority counts before -> after (FB-B3 -> FB-C2):")
    for k in ("modbus_reads", "modbus_writes", "commit_record", "load_record", "load_record_status", "scripts", "api_actions", "intervals",
              "sensors", "binary_sensors", "text_sensors", "switches", "buttons", "numbers", "selects", "durable_tag_strings",
              "globals", "includes", "substitutions"):
        print(f"      {k:20s} {mb[k]:6d} -> {ml[k]:6d}")
    zero = ("modbus_reads", "modbus_writes", "commit_record", "load_record", "load_record_status", "scripts", "api_actions", "intervals",
            "sensors", "binary_sensors", "text_sensors", "switches", "buttons", "numbers", "selects", "durable_tag_strings")
    check("authority delta is ZERO: Modbus reads / writes, durable commit / load sites, scripts, api actions, intervals, every entity kind, "
          "durable tags", all(mb[k] == ml[k] for k in zero), str({k: (mb[k], ml[k]) for k in zero if mb[k] != ml[k]}))
    check("Modbus op counts are the pinned 64 reads / 52 writes", (ml["modbus_reads"], ml["modbus_writes"]) == (64, 52))
    ops_b = chain.per_path_ops(base_texts[chain.FIRMWARE], chain._headers_of(base_texts))
    ops_l = chain.per_path_ops(live_texts[chain.FIRMWARE], chain._headers_of(live_texts))
    check("no write-surface path's operation list changed (analyzer, per path)", ops_b == ops_l)
    check("the measured delta is exactly: +39 RAM globals, +1 include, +1 substitution",
          (ml["globals"] - mb["globals"], ml["includes"] - mb["includes"], ml["substitutions"] - mb["substitutions"]) == (
              len(scope.NEW_GLOBAL_IDS), 1, 1))


# ===========================================================================
# [5] scope
# ===========================================================================
def section_scope() -> None:
    print("\n[5] change scope")
    check("the firmware as of fbc2 reverts exactly (14 edits) to the FB-B3 / S3 base checkpoint",
          scope.sha(scope.pre_fbc2_firmware(FBC2_TEXT)) == scope.BASE_FW_SHA == chain.CHAIN.checkpoint(chain.FIRMWARE, "fbb3"))
    check("applying the edits to the base and reverting reproduces the fbc2 text (round trip)",
          scope.add_fbc2_text(scope.pre_fbc2_firmware(FBC2_TEXT)) == FBC2_TEXT)
    check("every edit occurs exactly once and its base anchor is unique", all(FBC2_TEXT.count(e.after) == 1 for e in scope.EDITS))
    e = scope.EDITS[0]
    check("mutation: a reverter on a text with one edit altered raises", _raises(lambda: scope.pre_fbc2_firmware(
        FBC2_TEXT.replace(e.after, e.after.replace("180000", "170000", 1)))))
    check("mutation: a reverter on a text with an edit duplicated raises", _raises(lambda: scope.pre_fbc2_firmware(
        FBC2_TEXT + scope.edit("includes").after)))
    ent = chain.CHAIN.entry("fbc2")
    # FB-C3 / FB-D1: order-independent - later entries (fbc3, fbd1) follow fbc2; its checkpoint is the firmware as of fbc2
    check("chain entry fbc2 exists with its checkpoint (the firmware as of fbc2) and the declared deltas",
          "fbc2" in chain.CHAIN.ids() and ent.checkpoints[chain.FIRMWARE] == scope.sha(FBC2_TEXT) and
          ent.deltas == {"globals": len(scope.NEW_GLOBAL_IDS), "includes": 1, "substitutions": 1} and
          ent.subst_added == {scope.SUBSTITUTION[0]: scope.SUBSTITUTION[1]} and ent.includes_added == (scope.INCLUDE_ENTRY,) and
          ent.op_paths_changed == frozenset())
    rows = [r for r in chain.integrity_report(chain.CHAIN) if not r[1]]
    check("the whole chain integrity report is green (fbc2 and every later entry)", not rows, str(rows[:2]))
    missing = [p for p in scope.ADDED_FILES if not (ROOT / p).is_file()]
    check("every declared added file exists", not missing, str(missing))
    b3 = FBC2_TEXT.count("ecco_failback")
    check("the FB-A banned-token count the entry declares equals the measured count",
          chain.BANNED.findall(FBC2_TEXT).__len__() - chain.BANNED.findall(scope.pre_fbc2_firmware(FBC2_TEXT)).__len__() ==
          scope.BANNED_FW_ADDED == ent.banned_fw_added, str(b3))


def _raises(fn) -> bool:
    try:
        fn()
    except AssertionError:
        return True
    return False


def main() -> int:
    section_model()
    section_host()
    section_lambda()
    section_static()
    section_scope()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("All FB-C2 evaluator checks passed.")
    print("They prove the pure evaluator, its C++ == Python parity, the static authority pins and the change scope; the tick behaviour "
          "is proven by test_failback_shadow_tick.py; nothing here proves anything about hardware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
