#!/usr/bin/env python3
"""Offline tests for the FB-C2 Failback Shadow EVALUATOR as it runs INSIDE the 1 s shadow tick (the collector, the frozen edge
plan, the would-latched model, the profile-change evidence, the soak accumulators and the publication of Verdict / Inputs /
Episode / Soak). Architecture: docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md sections 6 / 8, design/S3_fbc_core_final.md
sections 3.8 / 9.2 / 11.4 / 11.5 / 17.1 and design/S4_domains_decisions_final.md.

The pure evaluator (firmware/include/ecco_failback_shadow.h, mirror registry/failback_shadow.py) is covered by its own suite. THIS
suite proves the part the evaluator suite cannot: that the REAL firmware lambda gathers the right world into ShadowInputs, drives the
episode machine with it, and publishes the result - by running the live lambdas (PR-A heartbeat / tick / init + the FB-C tick with
step 4b) on the strict FB-B simulator (registry/tests/_fbc2_harness.py) and comparing every tick with an INDEPENDENT Python oracle
collector written from S3 11.4 / 11.5 (not copied from the lambda).

  [T-C20] enumeration: every supervision state x every domain / bus class x every profile class x every cache state, each case
          carried through a full episode (edge, continuation, return, close, latched verdict, second edge): Verdict / Inputs /
          State / frozen edge plan / would_latched equal the oracle on EVERY tick, and coverage is asserted; the Verdict is the
          readiness (MODE_IF_LOST) plan or 50 on every tick, never NO_ACTION / WOULD_REFUSE_STARTS (FINAL 8.5, S3 9.2, S5 2.3)
  [T-VR]  REGRESSION: healthy stable (and unstable) supervision with a non-trivial readiness plan publishes that plan as the Verdict
  [XH]    soak xh counts export-hazard time only while an export-relevant lease obligation is open (FINAL 8.2)
  [T-C21] cache states I/O/S/P/M/F exactly; locks; the shadow's own 1 s fence AND the Live Match fence; the live latch (never two
          polls mixed); the overlay rule
  [T-C24/25] would-latched model: A / P outcomes, State, Verdict, wr after a latched close, k=L episodes, reboot clears
  [T-C26] projected frames; 230 / 245 / 247 differences change only `in`
  [T-C27] profile change since LOST (SAVE, class change, INVALIDATE) and the wr 4th field
  [T-C28] CLEAR basis M / A / R and the absence rule R3
  [T-C29] with ca != F the codes 26 / 27 / 40 / 41 are never emitted
  [E]     the C1 episode machine on the new lambda (open / HA_BACK / close, flapping, reboot loop, P_STABLE age re-check, tick
          order and random phases, publish de-duplication and rate, worst-case string lengths, card regexes)
  [S]     soak telemetry: wr p, xh, cs; saturation; the honest fence cost
  [Z9]    authority: every FB-C tick of every scenario is audited (only failback_shadow_* globals change; zero Modbus, zero NVS,
          zero durable events, zero scripts, only the five text sensors published, only allow-listed entities read)
  [M]     mutation / negative controls: deliberately broken in-memory copies of the lambda are each caught

Proves nothing about ESPHome timing or the compiled binary: only `esphome compile` and a live soak can.
"""

from __future__ import annotations

import itertools
import random
import re
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(ROOT / "tools"))
import _fbc2_harness as X  # noqa: E402
import _scope_chain as chain  # noqa: E402
import failback_shadow as sh  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
CARD_SRC = ROOT / "frontend" / "ecco-energy-actions-card" / "src"

FAILURES: list[str] = []
T0 = time.time()


CHECKS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append(name)
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


KNOWN_DEFECTS: list[str] = []
STRICT = "--strict" in sys.argv  # treat the documented lambda defects as failures


def known_defect(name: str, condition: bool, detail: str = "") -> None:
    """A check of the CORRECT behaviour that the shipped lambda does not (yet) have: reported loudly, never silently passed. It
    fails the run under --strict and passes itself the day the lambda is fixed."""
    if condition:
        print(f"  PASS  {name}")
    else:
        KNOWN_DEFECTS.append(name)
        print(f"  KNOWN-DEFECT  {name}" + (f" - {detail}" if detail else ""))
        if STRICT:
            FAILURES.append(name)


FW_TEXT = FW_PATH.read_text(encoding="utf-8")
FW = chain.load_fw(FW_TEXT)
SUBS = FW["_substitutions"]
LOST_MS = int(SUBS["ecco_supervision_lost_ms"])
CLOSE_MS = int(SUBS["ecco_failback_shadow_episode_close_ms"])
PUB_MS = int(SUBS["ecco_failback_shadow_publish_min_ms"])
SOAK_PUB_MS = int(SUBS["ecco_failback_shadow_soak_publish_min_ms"])
MAX_GAP_MS = int(SUBS["ecco_supervision_stable_max_gap_ms"])
CACHE_MAX_AGE_MS = cap.LIVE_CACHE_MAX_AGE_MS

STATE, EPS, SOAK, VERDICT, INPUTS = X.FBC_TEXT_IDS
FAR_EPOCH = 1_800_000_000  # the simulator's wall clock reads 1_790_000_000

# Harnesses built for the LIVE firmware (aggregated by the Z9 / string checks); mutant runs use a scratch sink.
ALL_H: list = []
_SINK = [ALL_H]


def mk(fw=None, *, oracle: bool = True, **kw) -> X.Harness:
    kw.setdefault("fbc_offset_ms", 250)
    kw.setdefault("pra_offset_ms", 750)
    h = X.Harness(fw or FW, oracle=oracle, **kw)
    _SINK[0].append(h)
    return h


ASSERTS = [0]  # every Exp assertion of the live-firmware run (mutant runs are counted too: they are detectors working)


class Exp:
    """Accumulates the failed expectations of one scenario."""

    def __init__(self):
        self.fails: list[str] = []
        self._n = 0

    @property
    def n(self) -> int:
        return self._n

    @n.setter
    def n(self, v: int) -> None:
        ASSERTS[0] += v - self._n
        self._n = v

    def ok(self, cond, msg: str):
        self.n += 1
        if not cond:
            self.fails.append(msg)

    def eq(self, got, want, msg: str):
        self.n += 1
        if got != want:
            self.fails.append(f"{msg}: got {got!r}, want {want!r}")

    def near(self, got, want, tol, msg: str):
        self.n += 1
        if abs(got - want) > tol:
            self.fails.append(f"{msg}: got {got!r}, want {want!r} +/- {tol}")

    def clean(self, *hs):
        """Z9 and the oracle: nothing violated, every tick equal to the independent collector."""
        for h in hs:
            self.n += 2
            if h.violations:
                self.fails.append(f"Z9 violation(s): {h.violations[:3]}")
            if h.oracle is not None and h.oracle_errors:
                self.fails.append(f"oracle mismatch(es) ({len(h.oracle_errors)}): {h.oracle_errors[:3]}")


# ===========================================================================
# Scenario scaffolding (PR-A + FB-C ticks, polls)
# ===========================================================================
FBC_OFF, PRA_OFF = 250, 750
WRAP = 1 << 32


def tick_at_or_after(t: int, off: int = FBC_OFF) -> int:
    k = max(0, -(-(t - off) // 1000))
    return off + k * 1000


def prime(h, words=None):
    """Make the cache trustworthy THROUGH the dynamics: the shadow's own fence seeds on the first FB-C tick (target = dispatch + 2),
    then three complete polls pass it."""
    h.set_words(words or X.GW)
    h.run_until(h.now + 1_200)  # at least one FB-C tick (the seed)
    for _ in range(3):
        h.poll()


def run_polled(h, t_end: int, every: int = 60_000):
    """run_until with a configuration poll every `every` ms (words unchanged)."""
    while h.now < t_end:
        nxt = min(h.now + every, t_end)
        h.run_until(nxt)
        h.poll()


def outage(h, *, last_beat=130_000, first_beat=10_000, cadence=30_000, drop_after=2_000, run_to=None, polled=True):
    """Healthy beats until `last_beat`, then HA stops (the API client drops `drop_after` later)."""
    h.set_client(True)
    h.schedule_beats_every(first_beat, cadence, last_beat)
    if polled:
        prime(h)
        run_polled(h, last_beat + drop_after)
    else:
        h.run_until(last_beat + drop_after)
    h.set_client(False)
    if run_to is not None:
        (run_polled if polled else lambda hh, t: hh.run_until(t))(h, run_to)
    return h


def return_beats(h, r, until, cadence=30_000):
    h.schedule_beats_every(r, cadence, until)


def kv(h, ent) -> dict:
    return h.parse_kv(ent)


def now_inputs(h) -> dict:
    """The Inputs of the LAST tick as the oracle computed them (the published text may lag by the 10 s rate gate; the oracle has
    already checked that the publication equals it whenever the gate permitted)."""
    return dict(p.split("=", 1) for p in h.oracle.last["want_inputs"].split(";"))


# ===========================================================================
# T-C20 / T-C21 / T-C26 / T-C29: the enumeration
# ===========================================================================
SUP_CASES = (  # label, supervision_state, PR-A stable flag, heartbeat age (ms)
    ("U", 0, False, 1000), ("O+", 1, True, 1000), ("O-", 1, False, 1000), ("O-aged", 1, True, 50_000),
    ("S", 2, False, 1000), ("L", 3, False, 1000),
)
SUP_BY_LABEL = {s[0]: s for s in SUP_CASES}
# live words relative to the golden profile (REGS numbers -> value): what the cached poll says
LIVE_VARIANTS = {
    "match": {}, "ctx-243": {243: 0}, "ctx-232b0": {232: X.P232 ^ 1}, "ctx-slot-time": {252: 1234}, "ctx-multiple": {243: 0, 248: 0},
    "ood-244": {244: 1}, "ood-power": {257: 100}, "ood-soc": {268: 101}, "ood-source": {274: 2}, "ood-multiple": {244: 1, 258: 90},
    "apply-244": {244: 0}, "apply-power-down": {256: 7000}, "apply-power-up": {256: 8000, 257: 600, 258: 4001},
    "apply-soc": {268: 90, 272: 10}, "apply-source": {275: 1}, "apply-all": {244: 0, 256: 7000, 257: 700, 268: 55, 274: 0},
    "info-230": {230: 1}, "info-232-bits": {232: X.P232 ^ 0x0100}, "cx-and-apply": {243: 0, 256: 7000},
}
CACHE_LABELS = ("F", "I", "I2", "I3", "O", "S", "P", "M", "B")
CACHE_LETTER = {"F": "F", "I": "I", "I2": "I", "I3": "I", "O": "O", "S": "S", "P": "P", "M": "M", "B": "B"}


def _inv_rec():
    return fp.invalidate_profile(X.GOLD)


def _bad_binding():
    b = bytearray(X.profile_bytes(X.GOLD))
    b[40] ^= 0x01  # a payload bit: the binding no longer matches
    return bytes(b)


def _domain_rec():
    return fp.seal_profile({**X.GOLD, "reg244": 5})  # an out-of-domain 244 value, sealed


def _site_rec():
    return X.make_profile(7, reg256_261=[9000, 500, 4000, 3000, 2000, 1000])


def _ceiling_w() -> int:
    return int(SUBS["ecco_inverter_tou_power_ceiling_w"])


PROFILES = (  # label, setter(h)
    ("VALID", lambda h: h.set_profile(X.GOLD)),
    ("VALID-not-writer-usable", lambda h: h.set_profile(X.GOLD, why=fd.WHY_WIT_LAGGING)),
    ("VALID-record-bad", lambda h: h.set_profile(_bad_binding(), load=fp.LOAD_OK, cls=fd.EPC_VALID, why=fd.WHY_NONE)),
    ("NOT_CAPTURED", lambda h: h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_NOT_CAPTURED)),
    ("INVALIDATED", lambda h: h.set_profile(_inv_rec(), cls=fd.EPC_INVALIDATED)),
    ("CORRUPT", lambda h: h.set_profile(_bad_binding(), cls=fd.EPC_CORRUPT)),
    ("CORRUPT_DOMAIN", lambda h: h.set_profile(_domain_rec(), cls=fd.EPC_CORRUPT_DOMAIN)),
    ("UNREADABLE", lambda h: h.set_profile(None, load=fp.LOAD_READ_ERROR, cls=fd.EPC_UNREADABLE, why=fd.WHY_PROFILE_READ)),
    ("PROFILE_LOST", lambda h: h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_PROFILE_LOST)),
    ("PROFILE_STALE", lambda h: h.set_profile(X.GOLD, cls=fd.EPC_PROFILE_STALE, why=fd.WHY_SUPERSEDED)),
    ("SAVE_UNCONFIRMED", lambda h: h.set_profile(X.GOLD, save_unconfirmed=True)),
    ("READ_ANOMALY", lambda h: h.set_profile(X.GOLD, read_anomaly=1)),
    ("VALID-site-ceiling", lambda h: h.set_profile(_site_rec())),
)
PROFILE_BY_LABEL = dict(PROFILES)


def _now(h) -> int:
    return h.sim.millis()


# --- domain / bus classes: (label, setup(h)) -----------------------------------------------------------------------------------
def _fp_active(h):
    h.free_power(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=FAR_EPOCH)


def _fp_due(h):
    h.free_power(snapshot_valid=True, marker_state=1, restore_requested=True)


FP_CASES = (
    ("fp:M", lambda h: None),
    ("fp:A", lambda h: h.set_g(free_power_marker_boot_load=1)),
    ("fp:R", lambda h: (h.set_g(free_power_marker_boot_load=1), h.mark_used("fp"))),
    ("fp:active", _fp_active),
    ("fp:active-expired", lambda h: h.free_power(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=1_700_000_000)),
    ("fp:due", _fp_due),
    ("fp:backoff", lambda h: (_fp_due(h), h.free_power(restore_next_attempt_ms=(_now(h) + 50_000_000) & 0xFFFFFFFF))),
    ("fp:pending-clear", lambda h: h.free_power(snapshot_valid=True, marker_state=2)),
    ("fp:operator-needed", lambda h: h.free_power(snapshot_valid=True, marker_state=1, operator_needed=True)),
    ("fp:starting", lambda h: h.set_running("start_free_power_override")),
    ("fp:starting-committed", lambda h: (h.set_running("start_free_power_override"), h.free_power(snapshot_valid=True))),
    ("fp:restore-running", lambda h: (_fp_due(h), h.set_running("restore_free_power_snapshot"))),
    ("fp:operator-running", lambda h: (_fp_due(h), h.set_running("free_power_recovery_review"))),
    ("fp:force-in-progress", lambda h: h.free_power(recovery_force_in_progress=True)),
    ("fp:opflag-orphan", lambda h: h.free_power(operation_in_progress=True)),
    ("fp:opflag-owned", lambda h: (h.free_power(operation_in_progress=True), h.set_running("start_free_power_override"))),
    ("fp:meta-corrupt", lambda h: h.free_power(recovery_metadata_corrupt=True)),
    ("fp:meta-unreadable", lambda h: (h.free_power(recovery_metadata_corrupt=True), h.set_g(free_power_marker_boot_load=3))),
    ("fp:wrong-size", lambda h: h.set_g(free_power_marker_boot_load=2)),
    ("fp:not-loaded", lambda h: h.set_g(free_power_marker_boot_load=255)),
    ("fp:diverged", lambda h: h.free_power(marker_state=1)),
    ("fp:marker-lost", lambda h: (h.set_g(free_power_marker_boot_load=1), h.free_power(operator_needed=True))),
    ("fp:stale-operator-needed", lambda h: h.free_power(operator_needed=True)),
    ("fp:latch-ghost", lambda h: h.set_g(fallback_profile_probe_latch=3)),
    ("fp:latch-unreadable", lambda h: h.set_g(fallback_profile_probe_latch=1)),
    ("fp:ctx-unknown", lambda h: (_fp_due(h), h.free_power(lease_context_reg244=-1))),
)
DUMP_CASES = (
    ("dp:M", lambda h: None),
    ("dp:A", lambda h: h.set_g(dump_marker_boot_load=1)),
    ("dp:R", lambda h: (h.set_g(dump_marker_boot_load=1), h.mark_used("dump"))),
    ("dp:active", lambda h: h.dump(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=FAR_EPOCH)),
    ("dp:due", lambda h: h.dump(snapshot_valid=True, marker_state=1, restore_requested=True)),
    ("dp:backoff", lambda h: h.dump(snapshot_valid=True, marker_state=1, restore_requested=True,
                                    restore_next_attempt_ms=(_now(h) + 50_000_000) & 0xFFFFFFFF)),
    ("dp:pending-clear", lambda h: h.dump(snapshot_valid=True, marker_state=2)),
    ("dp:operator-needed", lambda h: h.dump(snapshot_valid=True, marker_state=1, operator_needed=True)),
    ("dp:force-bypass", lambda h: h.dump(snapshot_valid=True, marker_state=1, operator_needed=True, force_restore_bypass=True)),
    ("dp:starting", lambda h: h.set_running("start_dump_to_grid_override")),
    ("dp:restore-running", lambda h: (h.dump(snapshot_valid=True, marker_state=1), h.set_running("restore_dump_to_grid_snapshot"))),
    ("dp:opflag-orphan", lambda h: h.dump(operation_in_progress=True)),
    ("dp:meta-corrupt", lambda h: h.dump(recovery_metadata_corrupt=True)),
    ("dp:meta-unreadable", lambda h: (h.dump(recovery_metadata_corrupt=True), h.set_g(dump_marker_boot_load=3))),
    ("dp:containment", lambda h: h.dump(containment_state=4)),
    ("dp:not-loaded", lambda h: h.set_g(dump_marker_boot_load=255)),
    ("dp:diverged", lambda h: h.dump(marker_state=1)),
    ("dp:original-exempt", lambda h: (h.dump(snapshot_data_loaded=True, snapshot_reg244=0),
                                       [h.set_g(**{f"dump_snapshot_reg{n}": X.GW[1 + k]}) for k, n in enumerate(range(256, 262))],
                                       h.dump(snapshot_valid=True, marker_state=1, operator_needed=True))),
    ("dp:latch-malformed", lambda h: h.set_g(fallback_profile_probe_latch=0x0020)),
)
R244_CASES = (
    ("r4:M", lambda h: None),
    ("r4:A", lambda h: h.set_g(reg244_marker_boot_load=1)),
    ("r4:R", lambda h: (h.set_g(reg244_marker_boot_load=1), h.mark_used("r244"))),
    ("r4:held", lambda h: h.r244(snapshot_valid=True, marker_state=1)),
    ("r4:held-drift", lambda h: h.r244(snapshot_valid=True, marker_state=1, last_applied_valid=True, last_applied_value=2)),
    ("r4:pending-clear", lambda h: h.r244(snapshot_valid=True, marker_state=2)),
    ("r4:apply-running", lambda h: h.set_running("apply_reg244_settings")),
    ("r4:apply-committed", lambda h: (h.set_running("apply_reg244_settings"), h.r244(snapshot_valid=True))),
    ("r4:restore-running", lambda h: (h.r244(snapshot_valid=True, marker_state=1), h.set_running("restore_reg244_snapshot"))),
    ("r4:opflag-orphan", lambda h: h.r244(apply_in_progress=True)),
    ("r4:meta-corrupt", lambda h: h.r244(recovery_metadata_corrupt=True)),
    ("r4:not-loaded", lambda h: h.set_g(reg244_marker_boot_load=255)),
    ("r4:diverged", lambda h: h.r244(marker_state=1)),
    ("r4:lav-absent", lambda h: (h.set_g(reg244_marker_boot_load=1), h.r244(last_applied_valid=True, last_applied_value=2))),
)
BUS_CASES = (
    ("bus:idle", lambda h: None),
    ("bus:mwip-owner", lambda h: (h.bus(manual_write_in_progress=True), h.set_running("apply_manual_slot1"))),
    ("bus:mwip-orphan", lambda h: h.bus(manual_write_in_progress=True)),
    ("bus:correction", lambda h: h.bus(correction_in_progress=True)),
    ("bus:correction-held", lambda h: h.bus(correction_in_progress=True, diag_correction_lock_held=True,
                                           diag_correction_lock_since_ms=(_now(h) - 120_000) & 0xFFFFFFFF)),
    ("bus:verification", lambda h: h.bus(verification_pending=True)),
    ("bus:verification-read", lambda h: h.bus(verification_read_active=True)),
    ("bus:lock-stuck", lambda h: h.bus(manual_write_in_progress=True, diag_write_lock_held=True,
                                      diag_write_lock_since_ms=(_now(h) - 400_000) & 0xFFFFFFFF)),
    ("bus:capture-running", lambda h: h.set_running("fallback_profile_capture_dispatch")),
    ("bus:profile-op", lambda h: h.bus(fallback_profile_op_in_progress=True)),
    ("bus:mtou-running", lambda h: h.set_running("apply_manual_slot3")),
    ("bus:mwip-capture", lambda h: (h.bus(manual_write_in_progress=True), h.set_running("fallback_profile_capture_dispatch"))),
)
ALL_DOMAIN_CASES = FP_CASES + DUMP_CASES + R244_CASES + BUS_CASES
DOMAIN_BY_LABEL = dict(ALL_DOMAIN_CASES)


class Stats:
    """What the enumeration covered (read back by the coverage assertions)."""

    def __init__(self):
        self.cases = 0
        self.ticks = 0
        self.plans_rd, self.plans_ac, self.verdicts, self.ca_letters, self.effs = set(), set(), set(), set(), set()
        self.sups, self.dom_letters, self.kinds, self.fbf, self.reasons = set(), set(), set(), set(), set()
        self.bad_ca_plans: list = []  # (ca letter, plan) where an E1 / CTX plan was emitted without ca=F
        self.max_inputs = self.max_episode = 0
        self.inputs_texts: set = set()
        self.e1_states = set()
        self.cx_states = set()
        self.latched_verdict_ticks = 0
        self.l_episodes = 0
        self.frozen_edges = 0
        self.ep_open_ticks = 0


def _h(*key) -> int:
    """A process-independent hash for the deterministic quick-mode subsampling."""
    return zlib.crc32(repr(key).encode())


STATS = Stats()
E1CTX_PLANS = (sh.PLAN_BLOCKED_CONTEXT_MISMATCH, sh.PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN, sh.PLAN_WOULD_ALREADY_MATCH,
               sh.PLAN_WOULD_APPLY_PROFILE)


def collect(h, stats: Stats):
    o = h.oracle
    if o is None or o.last is None:
        return
    L = o.last
    rd, ac = L["rd"], L["ac"]
    stats.ticks += 1
    stats.plans_rd.add(rd.plan)
    stats.plans_ac.add(ac.plan)
    stats.verdicts.add(L["verdict"])
    stats.reasons.add(rd.reason)
    letter = cap.cq_char(rd.ca)
    stats.ca_letters.add(letter)
    stats.effs.add(cap.live_effective_class(L["inputs"].lm.cls, L["inputs"].lm.write_outcome_unknown, L["inputs"].lm.read_anomaly))
    stats.sups.add(sh.sup_char(L["inputs"].sup.state))
    for d in (rd.dom[sh.DS_FP], rd.dom[sh.DS_DUMP], rd.dom[sh.DS_R244]):
        stats.dom_letters.add(sh.put_dom(d))
    stats.e1_states.add(rd.e1_state)
    stats.cx_states.add(rd.cx_state)
    if rd.ca != cap.CQ_FRESH and (rd.plan in E1CTX_PLANS or L["verdict"] in E1CTX_PLANS):
        stats.bad_ca_plans.append((letter, rd.plan, L["verdict"]))
    stats.max_inputs = max(stats.max_inputs, len(L["want_inputs"]))
    stats.inputs_texts.add(L["want_inputs"])
    if L["latched_before"]:
        stats.latched_verdict_ticks += 1
    if L["inputs"].sup.episode_open:
        stats.ep_open_ticks += 1


def _tick(h, stats, dt=11_000, sup=None, poll=False, edge=False, lost_events=None):
    """One audited FB-C tick `dt` after the last, with the supervision globals injected directly."""
    if poll:
        h.poll()
    if sup is not None:
        h.sup(*sup)
    if lost_events is not None:
        h.set_g(supervision_lost_events=lost_events)
    h.sim.now_ms += dt
    if sup is not None:  # the heartbeat age is relative to THIS tick
        h.sup(sup[0], sup[1], sup[2] if len(sup) > 2 else 5, sup[3] if len(sup) > 3 else 1000)
        if lost_events is not None:
            h.set_g(supervision_lost_events=lost_events)
    h.fbc_tick()
    collect(h, stats)


def cache_setup(h, label: str, stats: Stats, words=None):
    """Bring the cache to the named state THROUGH the dynamics (seed tick, polls, one more tick). Returns the dt of the final tick."""
    h.set_words(words or X.GW)
    if label == "B":
        h.profile_boot(False)
    sup = (1, True, 5, 1000)
    _tick(h, stats, 11_000, sup=sup)  # the first tick: seeds the shadow's own fence
    if label in ("B", "I"):
        return 11_000
    n_polls = 1 if label == "P" else 3
    for _ in range(n_polls):
        h.poll()
    if label == "I2":
        h.set_g(manual_config_raw_cache_valid=False)
    elif label == "I3":
        h.config_online(False)
    elif label == "O":
        h.config_polling(False)
    elif label == "M":
        h.set_g(fbc_raw_filled=False)
    return 181_000 if label == "S" else 11_000


def run_case(h, stats: Stats, sup_label: str, prof_label: str, cache_label: str, dom_labels=(), *, episode: bool = True,
             words=None):
    """One enumeration case: the world, the cache state, an evaluation tick, then a whole episode (edge, continuation, return,
    close, latched verdict, second edge) - the oracle compares EVERY tick."""
    h.reset_world()
    PROFILE_BY_LABEL[prof_label](h)
    for d in dom_labels:
        DOMAIN_BY_LABEL[d](h)
    dt_final = cache_setup(h, cache_label, stats, words)
    _, st, stable, age = SUP_BY_LABEL[sup_label]
    keep_fresh = cache_label in ("F", "P")
    _tick(h, stats, dt_final, sup=(st, stable, 5, age))  # the evaluation tick
    stats.cases += 1
    if not episode:
        return
    # E1: the LOST edge (PR-A counters: lost_events 0 -> 1, trigger H)
    _tick(h, stats, 11_000, sup=(3, False, 5, 1000), lost_events=1, poll=keep_fresh)
    _tick(h, stats, 11_000, sup=(3, False, 5, 1000), lost_events=1, poll=keep_fresh)  # continuation inside the open episode
    # E2: HA returns after the edge (a new beat; the last beat must be after the reconstructed edge)
    _tick(h, stats, 301_000, sup=(1, True, 6, 1000), lost_events=1, poll=keep_fresh)
    _tick(h, stats, 301_000, sup=(1, True, 6, 1000), lost_events=1, poll=keep_fresh)  # stable for >= 300 s: the close
    _tick(h, stats, 11_000, sup=(1, True, 6, 1000), lost_events=1, poll=keep_fresh)  # CLOSED (latched verdict if A)
    stats.fbf.add(h.g("failback_shadow_ep_fbf"))
    # a second LOST edge: kind L when the close latched, else kind N
    _tick(h, stats, 11_000, sup=(3, False, 6, 1000), lost_events=2, poll=keep_fresh)
    _tick(h, stats, 11_000, sup=(3, False, 6, 1000), lost_events=2, poll=keep_fresh)
    if h.g("failback_shadow_ep_kind") == sh.EPK_L:
        stats.l_episodes += 1
    stats.kinds.add(h.g("failback_shadow_ep_kind"))


def enumeration(fw=None, *, scale: int = 1, seed: int = 20261003, stats: Stats | None = None, quick: bool = False):
    """T-C20 / T-C21 / T-C26 / T-C29 over three cross products. Returns (failures list, stats)."""
    stats = stats or STATS
    h = mk(fw, oracle=True, enforce_z9=True)
    fails: list[str] = []

    def done(label):
        if h.oracle_errors:
            fails.append(f"{label}: {h.oracle_errors[:2]}")
            h.oracle.errors.clear()
        if h.violations:
            fails.append(f"{label}: Z9 {h.violations[:2]}")
            h.violations.clear()

    # (1) every supervision state x every profile class x every cache state, domains clear
    for s, (p, _), c in itertools.product([x[0] for x in SUP_CASES], PROFILES, CACHE_LABELS):
        if quick and (_h(s, p, c) % 5):
            continue
        run_case(h, stats, s, p, c, episode=True)
        done(f"1:{s}/{p}/{c}")
    # (2) every domain / bus class x supervision {stable, LOST, startup} x profile {VALID, NOT_CAPTURED} x cache {F, I}
    for d, s, p, c in itertools.product([x[0] for x in ALL_DOMAIN_CASES], ("O+", "L", "U"), ("VALID", "NOT_CAPTURED"), ("F", "I")):
        if quick and (_h(d, s, p, c) % 4):
            continue
        run_case(h, stats, s, p, c, (d,))
        done(f"2:{d}/{s}/{p}/{c}")
    # (3) seeded random cross product (every profile class, cache state and supervision state again, with 1-3 domain classes)
    rnd = random.Random(seed)
    n_rand = (90 if quick else 450) * scale
    for k in range(n_rand):
        s = rnd.choice([x[0] for x in SUP_CASES])
        p = rnd.choice([x[0] for x in PROFILES])
        c = rnd.choice(CACHE_LABELS)
        doms = tuple(rnd.sample([x[0] for x in ALL_DOMAIN_CASES], rnd.choice((1, 1, 2, 3))))
        run_case(h, stats, s, p, c, doms)
        done(f"3:{k}:{s}/{p}/{c}/{'+'.join(doms)}")
    # (4) live words that differ from the profile (context mismatch, out of domain, would-apply, info-only) x supervision x a few domains
    for (vl, ch), s, d in itertools.product(LIVE_VARIANTS.items(), [x[0] for x in SUP_CASES], ("none", "fp:marker-lost", "fp:A", "r4:R")):
        if quick and (_h(vl, s, d) % 3):
            continue
        run_case(h, stats, s, "VALID", "F", () if d == "none" else (d,), words=_words_with(ch))
        done(f"4:{vl}/{s}/{d}")
    return fails, stats


# ---- T-C26: projected frames, 230 / 245 / 247 -------------------------------------------------------------------------------------
def _words_with(changes: dict) -> list:
    w = list(X.GW)
    for reg, v in changes.items():
        w[cap.REGS.index(reg)] = v
    return w


def tc26(fw=None):
    e = Exp()
    h = mk(fw, oracle=True)
    stats = Stats()

    def evaluate(words):
        h.reset_world()
        cache_setup(h, "F", stats, words)
        _tick(h, stats, 11_000, sup=(1, True, 5, 1000))
        return h.inputs(), h.oracle.last["rd"]

    base, base_rd = evaluate(list(X.GW))
    e.eq((base["pl"], base["d"], base["in"], base["blk"]), ("40", "0", "M", "0"), "T-C26 base: WOULD_ALREADY_MATCH, d=0")
    # 230 / 245 / 247 (and 232 bits 1-15 / 248 bits 1-15) change ONLY `in`
    info_cases = [{230: 186}, {245: 7000}, {247: 0}, {230: 1, 245: 1, 247: 1}, {232: X.P232 ^ 0x0100}, {248: X.P248 ^ 0x0100},
                  {230: 190, 232: X.P232 ^ 0x0002, 248: X.P248 ^ 0x0400}]
    for ch in info_cases:
        got, rd = evaluate(_words_with(ch))
        diff = sorted(k for k in set(base) | set(got) if base.get(k) != got.get(k))
        e.eq(diff, ["in"], f"T-C26 {ch}: only `in` changes")
        e.eq((got["in"], got["pl"], got["blk"], got["d"]), ("D", "40", "0", "0"), f"T-C26 {ch}: in=D, still WOULD_ALREADY_MATCH, no frame")
        e.eq(rd.projected_frames, 0, f"T-C26 {ch}: no projected frame")
    # enumerated live vectors: every blk bit comes from an E1 register class, never from 230/245/247/CTX
    rnd = random.Random(26)
    frames_seen = set()
    n_plan41 = 0

    def pick(reg: int) -> int:
        """A domain-valid value for the register (an out-of-domain one only rarely, to reach plan 27 too)."""
        ood = rnd.random() < 0.03
        if reg == 244:
            return 1 if ood else rnd.choice((0, 2))
        if 256 <= reg <= 261:
            return 100 if ood else rnd.randint(500, 8000)
        if 268 <= reg <= 273:
            return 101 if ood else rnd.randint(0, 100)
        if 274 <= reg <= 279:
            return 2 if ood else rnd.choice((0, 1))
        return rnd.choice((0, 1, 2, 3, X.GW[cap.REGS.index(reg)] ^ 1, 0xFFFF))

    groups = {"244": [244], "p256": list(range(256, 262)), "s268": list(range(268, 274)), "s274": list(range(274, 280)),
              "ctx": [232, 243, 248, 250, 251, 252, 253, 254, 255], "info": [230, 245, 247]}
    n_vec = 320 if fw is None else 140
    for k in range(n_vec):
        ch = {}
        for g_, regs in groups.items():
            if rnd.random() < (0.55 if g_ != "ctx" else 0.07):
                for reg in rnd.sample(regs, rnd.randint(1, len(regs))):
                    ch[reg] = pick(reg)
        got, rd = evaluate(_words_with(ch))
        blk = int(got["blk"], 16)
        e.ok(blk & ~0xF == 0, f"T-C26 vec {k}: blk subset of the four E1 frames ({got['blk']})")
        e.ok(blk == 0 or got["pl"] == "41", f"T-C26 vec {k}: a frame only with WOULD_APPLY_PROFILE (pl={got['pl']} blk={got['blk']})")
        e.eq(blk, rd.projected_frames, f"T-C26 vec {k}: blk is the evaluator's projected_frames")
        touched = set(ch)
        if got["pl"] == "41":
            n_plan41 += 1
            frames_seen.add(blk)
            e.ok(blk & 1 == 0 or 244 in touched, f"T-C26 vec {k}: F244 only after a 244 difference")
            e.ok(blk & 4 == 0 or touched & set(range(268, 280)), f"T-C26 vec {k}: F268_279 only after a 268-279 difference")
            e.ok(not (blk & 10) or touched & set(range(256, 262)), f"T-C26 vec {k}: F256 frames only after a 256-261 difference")
            e.ok(not (touched & {232, 243, 248, 250, 251, 252, 253, 254, 255}), f"T-C26 vec {k}: no CTX register changed in a WOULD_APPLY plan")
        if got["pl"] in ("40", "41"):
            e.eq(got["cx"], "M", f"T-C26 vec {k}: a would-apply / match plan has matching CTX")
        if touched <= {230, 245, 247}:
            e.eq(got["pl"], "40", f"T-C26 vec {k}: info-only differences never change the plan")
    e.ok(n_plan41 >= 40 and len(frames_seen) >= 6, f"T-C26 coverage: {n_plan41} WOULD_APPLY_PROFILE vectors, frames seen {sorted(frames_seen)}")
    e.clean(h)
    return e.fails


# ===========================================================================
# T-C21: cache states, fences, latch, overlay
# ===========================================================================
def tc21(fw=None):
    e = Exp()
    h = mk(fw, oracle=True)
    st = Stats()
    # (a) each cache state, exactly
    for label in CACHE_LABELS:
        h.reset_world()
        dt = cache_setup(h, label, st)
        _tick(h, st, dt, sup=(1, True, 5, 1000))
        ca = h.inputs()["ca"]
        e.eq(ca, CACHE_LETTER[label], f"T-C21 cache state {label}: ca letter")
        want_plan = {"F": "40", "B": "0"}.get(label, "15")
        if label not in ("B",):
            e.eq(h.inputs()["pl"], want_plan, f"T-C21 {label}: plan (E1/CTX plans only with ca=F, else WAIT_LIVE_DATA)")
        if label == "F":
            e.eq((h.inputs()["e1"], h.inputs()["cx"], h.inputs()["in"]), ("M", "M", "M"), "T-C21 F: masks evaluated")
        else:
            e.eq((h.inputs()["e1"], h.inputs()["cx"], h.inputs()["in"]), ("N", "N", "N"), f"T-C21 {label}: masks not evaluable")
        e.eq(h.oracle.last["rd"].ca, [k for k in range(7) if cap.cq_char(k) == CACHE_LETTER[label]][0], f"T-C21 {label}: ca code")
    # the order of the terms (first failing term): invalid beats polling-off beats stale, ...
    h.reset_world()
    cache_setup(h, "F", st)
    h.config_polling(False)
    h.set_g(manual_config_raw_cache_valid=False)
    _tick(h, st, 181_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "I", "T-C21 term order: I before O and S")
    h.set_g(manual_config_raw_cache_valid=True)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "O", "T-C21 term order: O before S")
    h.config_polling(True)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "S", "T-C21 term order: S (cache 3+ min old)")
    h.poll()
    h.poll()
    h.poll()
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "F", "T-C21 recovers to F after fresh polls (fence already passed)")
    # the age boundary: exactly 180 s is still fresh, 180 s + 1 ms is stale
    for extra, want in ((0, "F"), (1, "S")):
        h.reset_world()
        cache_setup(h, "F", st)
        age = CACHE_MAX_AGE_MS + extra
        ok_ms = h.g("cfg_block_b_ok_ms")
        h.sim.now_ms = ok_ms + age - 1_000
        h.sup(1, True, 5, 1000)
        h.sim.now_ms += 1_000
        h.sup(1, True, 5, 1000)
        h.fbc_tick()
        e.eq(h.inputs()["ca"], want, f"T-C21 age {age} ms -> ca {want} (180000 ms rule)")
    # (b) lk and the overlay: every lock / non-CLEAR domain makes the fence hot, so ca is P and e1 / cx are not evaluable
    nonclear = [("lk=1 manual write", lambda hh: (hh.bus(manual_write_in_progress=True), hh.set_running("apply_manual_slot1")), 1),
                ("lk=2 rtc correction", lambda hh: hh.bus(correction_in_progress=True), 2),
                ("lk=3 both", lambda hh: (hh.bus(manual_write_in_progress=True, correction_in_progress=True),
                                          hh.set_running("apply_manual_slot2")), 3),
                ("fp active", _fp_active, 0), ("fp restore due", _fp_due, 0),
                ("dump active", DOMAIN_BY_LABEL["dp:active"], 0), ("dump due", DOMAIN_BY_LABEL["dp:due"], 0),
                ("r244 held", DOMAIN_BY_LABEL["r4:held"], 0), ("r244 apply running", DOMAIN_BY_LABEL["r4:apply-running"], 0)]
    for label, setup, lk in nonclear:
        h.reset_world()
        cache_setup(h, "F", st)
        setup(h)
        for _ in range(3):
            h.poll()
            _tick(h, st, 11_000, sup=(1, True, 5, 1000))
        inp = h.inputs()
        e.eq(int(inp["lk"]), lk, f"T-C21 {label}: lk")
        e.eq(inp["ca"], "P", f"T-C21 {label}: a non-CLEAR domain / held lock keeps the shared fence open (ca=P)")
        e.eq((inp["e1"], inp["cx"]), ("N", "N"), f"T-C21 {label}: e1 / cx not evaluable under ca=P (the overlay 'O' is never reached)")
    # the overlay 'O' IS reachable where the domain is RAM-clear (fence stays closed-free) but not CLEAR_PROVEN: FP marker lost
    h.reset_world()
    h.set_g(free_power_marker_boot_load=1)
    h.free_power(operator_needed=True)
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    inp = h.inputs()
    e.eq((inp["ca"], inp["e1"], inp["cx"], inp["fp"]), ("F", "O", "O", "U20"), "T-C21 overlay: FP marker-lost is the one non-CLEAR state with ca=F -> e1=cx=O")
    e.eq(inp["in"], "M", "T-C21 overlay: `in` has no overlay (never blocking)")
    # (c) the shadow's OWN fence: a routine write re-opens it; two further polls pass it
    h.reset_world()
    cache_setup(h, "F", st)
    h.bump_write_attempts("manual_write_attempts")
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "P", "T-C21 own fence: a write-attempt counter change re-opens the fence")
    h.poll()
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "P", "T-C21 own fence: one poll is not enough (target = dispatch + 2)")
    h.poll()
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "F", "T-C21 own fence: two polls pass it")
    for which in ("reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts"):
        h.bump_write_attempts(which)
        _tick(h, st, 11_000, sup=(1, True, 5, 1000))
        e.eq(h.inputs()["ca"], "P", f"T-C21 own fence: {which} re-opens it")
        h.poll()
        h.poll()
        _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    # (d) the Live Match fence: the larger of the two decides; never weaker than B10
    h.reset_world()
    cache_setup(h, "F", st)
    resp = h.g("cfg_block_b_response_dispatch_seq")
    h.set_g(fallback_profile_live_fence_seq=resp + 2)  # the Live Match saw a write: it needs two more polls
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "P", "T-C21 Live Match fence: B10's fence alone holds the shadow at ca=P (never weaker than B10)")
    h.poll()
    h.poll()
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "F", "T-C21 Live Match fence: passed after two polls")
    h.bump_write_attempts()  # own fence jumps to dispatch+2; the Live Match fence is lower
    h.set_g(fallback_profile_live_fence_seq=0)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["ca"], "P", "T-C21 own fence alone also holds when the Live Match fence is lower (the larger decides)")
    # (e) the live latch: a tick between Block A and Block B of one poll never mixes two polls
    h.reset_world()
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    latched0 = list(h.g("failback_shadow_live_regs"))
    e.eq(latched0, list(X.GW), "T-C21 latch: the evaluated words are the poll's words")
    e.eq(h.inputs()["d"], "0", "T-C21 latch: d=0")
    new_a = {232: X.P232 ^ 0x0001, 230: 99}  # Block A of the NEXT poll lands first (232, 230)
    for reg, v in new_a.items():
        h.set_g(**{X.word_global(reg): v})
    h.set_g(**{X.word_global(256): 7000, X.word_global(244): 0})  # and part of Block B's words before its seq advance
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(list(h.g("failback_shadow_live_regs")), latched0, "T-C21 latch: mid-poll cache changes are NOT evaluated (no seq advance)")
    e.eq((h.inputs()["d"], h.inputs()["cx"], h.inputs()["in"]), ("0", "M", "M"), "T-C21 latch: Inputs still the previous poll's")
    h.block_b_success()  # Block B success: seq++ -> the next tick latches ALL 31 words of the new poll together
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    now_words = [h.g(n) for n in X.WORD_GLOBALS]
    e.eq(list(h.g("failback_shadow_live_regs")), now_words, "T-C21 latch: after seq advance all 31 words are the new poll's")
    e.eq(h.g("failback_shadow_live_seq"), h.g("cfg_block_b_seq"), "T-C21 latch: live_seq follows cfg_block_b_seq")
    e.ok(h.inputs()["d"] != "0" and h.inputs()["cx"] == "D", f"T-C21 latch: new words now differ ({h.inputs()['d']}, cx={h.inputs()['cx']})")
    e.clean(h)
    return e.fails


# ===========================================================================
# Episode scenarios (PR-A + FB-C on the new lambda)
# ===========================================================================
def _close_tick(r: int) -> int:
    return tick_at_or_after(r + 60_000 + CLOSE_MS)


def _settle_close(h, r, extra=15_000):
    run_polled(h, _close_tick(r) + extra)


def tc24(fw=None):
    e = Exp()
    h = mk(fw)
    h.set_profile(_inv_rec(), cls=fd.EPC_INVALIDATED)  # plan at the edge: BLOCKED_PROFILE_INVALIDATED (a "no profile" plan)
    last, r = 130_000, 500_000
    edge = last + LOST_MS
    outage(h, last_beat=last, run_to=edge + 2_000)
    k = kv(h, EPS)
    e.eq((k["ph"], k["k"], k["v0"], k["vu"], k["f0"], k["dm"], k["pre"], k["blk"], k["d"], k["fbf"]),
         ("O", "N", str(sh.PLAN_BLOCKED_PROFILE_INVALIDATED), "-", str(sh.FAILBACK_RESULT_PREEMPTED_NO_PROFILE),
          str(sh.BD_FBP), "0", "0", "-", "-"), f"T-C24 episode 1 edge freeze (kind N, invalidated): {h.text(EPS)}")
    e.eq(h.verdict(), "BLOCKED_PROFILE_INVALIDATED", "T-C24 Verdict during the episode")
    e.eq(h.g("failback_shadow_would_latched"), False, "T-C24 not latched while the episode is open")
    # a START while the episode is open counts (wr_fp) - and again later while latched
    return_beats(h, r, r + 1_800_000)
    run_polled(h, r + 5_000)
    e.eq(h.text(STATE), "SHADOW_EPISODE_HA_BACK", "T-C24 HA_BACK")
    run_polled(h, _close_tick(r) - 2_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C24 still HA_BACK just before the close")
    ct = _close_tick(r)
    h.run_until(ct)  # the close tick
    verdict_at_close = h.verdict()
    e.eq(h.text(STATE), "SHADOW_WOULD_AWAIT_ACK", "T-C24 State flips to SHADOW_WOULD_AWAIT_ACK on the close tick itself")
    e.ok(verdict_at_close in ("BLOCKED_PROFILE_INVALIDATED", "WOULD_REMAIN_LATCHED"),
         f"T-C24 on the close tick the Verdict is still the plan or already latched ({verdict_at_close})")
    h.run_until(ct + 1_500)
    e.eq(h.verdict(), "WOULD_REMAIN_LATCHED", "T-C24 the Verdict follows the latch on the very next tick (one-tick lag at most)")
    k = kv(h, EPS)
    e.eq((k["ph"], k["fbf"], k["k"]), ("C", "A", "N"), f"T-C24 closes fbf=A: {h.text(EPS)}")
    e.eq(h.g("failback_shadow_would_latched"), True, "T-C24 would_latched true after an A close")
    e.eq(h.text(STATE), "SHADOW_WOULD_AWAIT_ACK", "T-C24 State SHADOW_WOULD_AWAIT_ACK")
    run_polled(h, _close_tick(r) + 15_000)
    e.eq(h.verdict(), "WOULD_REMAIN_LATCHED", "T-C24 Verdict WOULD_REMAIN_LATCHED (within one 10 s window of the close)")
    inp = h.inputs()
    e.eq(inp["pl"], str(sh.PLAN_BLOCKED_PROFILE_INVALIDATED), "T-C24 Inputs pl keeps the underlying plan while latched")
    wr0 = h.soak_wr()
    # an FP START afterwards counts (P_WOULD_REFUSE includes the latch)
    h.set_g(free_power_operation_in_progress=True)
    h.set_running("start_free_power_override")
    h.run(2_000)
    h.set_g(free_power_operation_in_progress=False)
    h.set_running("start_free_power_override", False)
    h.run(2_000)
    e.eq(h.soak_wr()[0], wr0[0] + 1, "T-C24 an FP START after the close counts in wr (latched, stable)")
    # the next LOST edge opens kind L: v0=50, f0 / dm / d '-', vu = the underlying readiness plan
    last2 = h.now // 1000 * 1000 + 40_000
    h.schedule_beats_every(h.now + 1_000, 30_000, last2)  # keep beating, then stop
    # (the return beats already scheduled run to r + 1800 s; drop the rest by rebooting the beat list)
    h._beat_times = [t for t in h._beat_times if t <= last2]
    run_polled(h, last2 + 2_000)
    run_polled(h, last2 + LOST_MS + 2_000)
    k = kv(h, EPS)
    e.eq(k["id"].split("-")[1], "2", "T-C24 a second episode")
    e.eq((k["ph"], k["k"], k["v0"], k["f0"], k["dm"], k["pre"], k["blk"], k["d"], k["vu"]),
         ("O", "L", "50", "-", "-", "0", "0", "-", str(sh.PLAN_BLOCKED_PROFILE_INVALIDATED)), f"T-C24 episode 2 is kind L: {h.text(EPS)}")
    e.eq(h.text(STATE), "SHADOW_EPISODE", "T-C24 State SHADOW_EPISODE during the L episode")
    e.eq(h.verdict(), "WOULD_REMAIN_LATCHED", "T-C24 Verdict stays latched inside the L episode")
    r2 = h.now + 10_000
    return_beats(h, r2, r2 + 1_800_000)
    run_polled(h, _close_tick(r2) + 15_000)
    k = kv(h, EPS)
    e.eq((k["ph"], k["k"], k["fbf"]), ("C", "L", "A"), f"T-C24 the L episode closes fbf=A (never P): {h.text(EPS)}")
    e.eq(h.g("failback_shadow_would_latched"), True, "T-C24 still latched")
    e.clean(h)
    return e.fails


def tc25(fw=None):
    e = Exp()
    h = mk(fw)
    last, r = 130_000, 500_000
    edge = last + LOST_MS
    outage(h, last_beat=last, run_to=edge + 2_000)
    k = kv(h, EPS)
    e.eq((k["k"], k["v0"], k["f0"], k["dm"], k["pre"], k["blk"], k["d"]),
         ("N", "40", str(sh.FAILBACK_RESULT_ALREADY_AT_PROFILE), "0", "0", "0", "0"), f"T-C25 edge plan WOULD_ALREADY_MATCH, all domains clear: {h.text(EPS)}")
    e.eq(kv(h, INPUTS)["ca"], "F", "T-C25 the edge saw a trusted cache")
    return_beats(h, r, r + 1_800_000)
    run_polled(h, _close_tick(r) + 15_000)
    k = kv(h, EPS)
    e.eq((k["ph"], k["fbf"], k["k"]), ("C", "P", "N"), f"T-C25 closes fbf=P: {h.text(EPS)}")
    e.eq(h.g("failback_shadow_would_latched"), False, "T-C25 would_latched stays false")
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C25 State SHADOW_IDLE (stable, not latched)")
    e.eq((h.verdict(), now_inputs(h)["pl"]), ("WOULD_ALREADY_MATCH", "40"),
         "T-C25 Verdict = the readiness plan WOULD_ALREADY_MATCH (= Inputs pl), never NO_ACTION, with stable supervision")
    wr0 = h.soak_wr()
    h.set_g(free_power_operation_in_progress=True)
    h.run(3_000)
    h.set_g(free_power_operation_in_progress=False)
    h.run(2_000)
    e.eq(h.soak_wr(), wr0, "T-C25 an FP START after a P close is not counted (not latched, stable)")
    last2 = h.now // 1000 * 1000 + 40_000
    h._beat_times = [t for t in h._beat_times if t <= last2]
    run_polled(h, last2 + LOST_MS + 2_000)
    k = kv(h, EPS)
    e.eq((k["id"].split("-")[1], k["ph"], k["k"], k["v0"]), ("2", "O", "N", "40"), f"T-C25 the next LOST opens kind N: {h.text(EPS)}")
    # a reboot never carries the latch: clear it from an A close, reboot, next LOST is N
    e.clean(h)
    return e.fails


def tc24_reboot(fw=None):
    """would_latched is cleared only by a reboot."""
    e = Exp()
    h = mk(fw)
    h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_NOT_CAPTURED)  # NOT_CAPTURED: plan BLOCKED_PROFILE_UNAVAILABLE (absence is no proof)
    last, r = 130_000, 500_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    e.eq(kv(h, EPS)["v0"], str(sh.PLAN_BLOCKED_PROFILE_UNAVAILABLE), "T-C24b NOT_CAPTURED edge plan (absence is not proof)")
    return_beats(h, r, r + 1_800_000)
    run_polled(h, _close_tick(r) + 15_000)
    e.eq((kv(h, EPS)["fbf"], h.g("failback_shadow_would_latched")), ("A", True), "T-C24b latched")
    # the latch survives everything but a reboot: a long idle stretch, a profile SAVE, a NOT_CAPTURED -> VALID class change
    h.save_profile(X.make_profile(1))
    run_polled(h, h.now + 120_000)
    e.eq(h.g("failback_shadow_would_latched"), True, "T-C24b latch survives a profile SAVE and two minutes")
    e.eq(h.soak_wr()[3], 1, "T-C24b a SAVE while latched counts in wr p (the latch keeps P_WOULD_REFUSE true)")
    e.eq(h.verdict(), "WOULD_REMAIN_LATCHED", "T-C24b Verdict still latched")
    h.reboot()
    e.eq(h.g("failback_shadow_would_latched"), False, "T-C24b a reboot clears the latch")
    h.set_words(X.GW)
    e.eq(h.text(STATE) in ("", "SHADOW_WATCH"), True, "T-C24b fresh boot State")
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 130_000)
    prime(h)
    run_polled(h, 130_000 + LOST_MS + 2_000)
    e.eq(kv(h, EPS)["k"], "N", "T-C24b after the reboot the next LOST is kind N")
    e.clean(h)
    return e.fails


def tc_edge_same_tick(fw=None):
    """The frozen edge plan is the READINESS plan (rd, MODE_IF_LOST), not the supervision-aware ACTUAL plan (the oracle's reference
    `ac`): when the LOST edge and the return beat fall in ONE tick the ACTUAL plan sees supervision back at SUPERVISED, the readiness
    plan does not."""
    e = Exp()
    last = 130_000
    edge = last + LOST_MS
    h = mk(fw)
    outage(h, last_beat=last, run_to=edge - 1_000)
    e.eq(h.g("failback_shadow_phase"), 0, "T-C06b' setup: no episode yet")
    h.sim.now_ms = edge + 750
    h.poll()
    h.pra_tick()  # PR-A raises LOST
    e.eq(h.g("supervision_state"), 3, "T-C06b' PR-A raised LOST")
    h.sim.now_ms = edge + 800
    h.beat()  # returns to SUPERVISED before FB-C samples the state
    e.eq(h.g("supervision_state"), 1, "T-C06b' SUPERVISED again at the FB-C tick")
    h.sim.now_ms = edge + 900
    h.fbc_tick()
    o = h.oracle.last
    e.eq(h.g("failback_shadow_phase"), 2, "T-C06b' E1 and E2 in one tick")
    e.ok(o["ac"].plan != o["rd"].plan, f"T-C06b' setup: ac ({o['ac'].plan}) differs from rd ({o['rd'].plan}) in this tick")
    e.eq(h.g("failback_shadow_ep_v0"), o["rd"].plan, "T-C06b' the frozen edge plan v0 is the READINESS plan (rd), not the verdict")
    e.eq(h.g("failback_shadow_ep_v0"), sh.PLAN_WOULD_ALREADY_MATCH, "T-C06b' v0 = WOULD_ALREADY_MATCH")
    e.clean(h)
    return e.fails


# ---- T-C27 -------------------------------------------------------------------------------------------------------------------------
def _episode_up(h, *, last=130_000, return_at=500_000):
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    return_beats(h, return_at, return_at + 1_800_000)
    run_polled(h, return_at + 20_000)


def tc27(fw=None):
    e = Exp()
    # (a) SAVE during HA_BACK: a new generation of a VALID profile
    h = mk(fw)
    _episode_up(h)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C27 setup: HA_BACK")
    e.eq(h.soak_wr()[3], 0, "T-C27 wr p starts at 0")
    e.eq(h.g("failback_shadow_ep_pgen"), 7, "T-C27 the edge froze generation 7")
    h.save_profile(X.make_profile(8, reg256_261=[7000, 500, 4000, 3000, 2000, 1000]))
    h.run(1_500)
    run_polled(h, h.now + 20_000)
    inp = h.inputs()
    e.eq((inp["rs"], inp["pl"]), (str(sh.RS_PROFILE_CHANGED_SINCE_LOST), str(sh.PLAN_BLOCKED_PROFILE_UNAVAILABLE)),
         f"T-C27 SAVE during HA_BACK -> PROFILE_CHANGED_SINCE_LOST via the frozen identity: {h.text(INPUTS)}")
    e.eq(h.verdict(), "BLOCKED_PROFILE_UNAVAILABLE", "T-C27 Verdict")
    e.eq(h.soak_wr()[3], 1, "T-C27 wr 4th field +1 for the SAVE inside the episode")
    e.eq(h.oracle.last["rd"].profile_changed_since_lost, True, "T-C27 profile_changed_since_lost")
    e.clean(h)
    # (b) a class change inside the episode (NOT_CAPTURED at the edge, VALID after a SAVE)
    h = mk(fw)
    h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_NOT_CAPTURED)
    _episode_up(h)
    e.eq((h.g("failback_shadow_ep_pclass"), h.g("failback_shadow_ep_pgen")), (fd.EPC_NOT_CAPTURED, 0), "T-C27b frozen identity: NOT_CAPTURED, no generation")
    e.eq(kv(h, INPUTS)["rs"], str(sh.RS_PROFILE_ABSENT_UNPROVEN), "T-C27b before the SAVE: absence is not proof (509)")
    h.save_profile(X.make_profile(1))
    run_polled(h, h.now + 20_000)
    e.eq(kv(h, INPUTS)["rs"], str(sh.RS_PROFILE_CHANGED_SINCE_LOST), "T-C27b NOT_CAPTURED -> VALID gives PROFILE_CHANGED_SINCE_LOST")
    e.eq(h.soak_wr()[3], 1, "T-C27b wr p +1")
    e.clean(h)
    # (c) INVALIDATE: counted only while an episode was open
    h = mk(fw)
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 400_000)
    prime(h)
    run_polled(h, 200_000)
    h.invalidate_profile()
    run_polled(h, 215_000)
    e.eq(h.soak_wr()[3], 0, "T-C27c INVALIDATE while idle and stable is not counted")
    h2 = mk(fw)
    _episode_up(h2)
    h2.invalidate_profile()
    run_polled(h2, h2.now + 15_000)
    e.eq(h2.soak_wr()[3], 1, "T-C27c INVALIDATE while an episode is open is counted")
    e.eq(kv(h2, INPUTS)["rs"], str(sh.RS_PROFILE_CHANGED_SINCE_LOST), "T-C27c and shows PROFILE_CHANGED_SINCE_LOST")
    e.clean(h, h2)
    # (d) a SAVE while stable and idle is not counted; while WATCH (unstable) it is
    h = mk(fw)
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 400_000)
    prime(h)
    run_polled(h, 15_000)
    e.eq(h.text(STATE), "SHADOW_WATCH", "T-C27d setup: WATCH (not yet stable)")
    h.save_profile(X.make_profile(8))
    run_polled(h, 20_000)
    e.eq(h.soak_wr()[3], 1, "T-C27d a SAVE while WATCH counts (a SAVE would be refused outside CLEAR+stable)")
    run_polled(h, 150_000)
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C27d setup: IDLE")
    h.save_profile(X.make_profile(9))
    run_polled(h, 165_000)
    e.eq(h.soak_wr()[3], 1, "T-C27d a SAVE while stable and idle is not counted")
    e.clean(h)
    return e.fails


def tc27_overlay_clear(fw=None):
    """A read-anomaly / SAVE_UNCONFIRMED overlay that clears again without any generation change is NOT a profile change."""
    e = Exp()
    h = mk(fw)
    h.set_client(True)
    prime(h)
    run_polled(h, 5_000)
    e.eq(h.text(STATE), "SHADOW_WATCH", "T-C27e setup: WATCH (P_WOULD_REFUSE true)")
    w0 = h.soak_wr()
    h.set_g(fallback_profile_save_unconfirmed=True)
    run_polled(h, 8_000)
    h.set_g(fallback_profile_save_unconfirmed=False)  # the overlay clears: same record, same generation
    run_polled(h, 12_000)
    e.eq(h.soak_wr(), w0, "T-C27e an overlay that clears with the same generation counts nothing in wr")
    e.clean(h)
    return e.fails


# ---- T-C28 -------------------------------------------------------------------------------------------------------------------------
def tc28(fw=None):
    e = Exp()
    h = mk(fw)
    h.set_g(free_power_marker_boot_load=1)  # FP marker ABSENT at boot; Dump and R244 loaded OK
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 1_000_000)
    prime(h)
    run_polled(h, 160_000)
    inp = h.inputs()
    e.eq((inp["fp"], inp["dp"], inp["r4"]), ("CA", "CM", "CM"), f"T-C28 bases: FP absent (A), Dump / R244 marker-clear (M): {h.text(INPUTS)}")
    e.eq((inp["pl"], inp["rs"]), (str(sh.PLAN_BLOCKED_DURABLE_UNKNOWN), str(sh.RS_FP_MARKER_ABSENT_UNPROVEN)),
         "T-C28 R3: absence blocks the would-be plan (BLOCKED_DURABLE_UNKNOWN / FP_MARKER_ABSENT_UNPROVEN)")
    o = h.oracle.last["rd"]
    e.ok(o.absence_relied and o.alt_plan_absence_accepted != o.plan,
         f"T-C28 alt_plan_absence_accepted ({o.alt_plan_absence_accepted}) differs from the plan ({o.plan})")
    e.eq(o.alt_plan_absence_accepted, sh.PLAN_WOULD_ALREADY_MATCH, "T-C28 accepting absence would have matched")
    # the same rule for Dump (117) and R244 (315)
    for dom, key, rs, setter in (("dump", "dp", sh.RS_DUMP_MARKER_ABSENT_UNPROVEN, {"dump_marker_boot_load": 1}),
                                 ("r244", "r4", sh.RS_R244_MARKER_ABSENT_UNPROVEN, {"reg244_marker_boot_load": 1})):
        h2 = mk(fw)
        h2.set_g(**setter)
        h2.set_client(True)
        h2.schedule_beats_every(10_000, 30_000, 400_000)
        prime(h2)
        run_polled(h2, 160_000)
        e.eq((h2.inputs()[key], h2.inputs()["rs"], h2.inputs()["pl"]), ("CA", str(rs), str(sh.PLAN_BLOCKED_DURABLE_UNKNOWN)),
             f"T-C28 R3 for {dom}: {h2.text(INPUTS)}")
        e.clean(h2)
    # an FP START and a verified restore: A -> R
    h.set_g(free_power_operation_in_progress=True)
    h.set_running("start_free_power_override")
    run_polled(h, 165_000)
    h.free_power(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=FAR_EPOCH)
    h.set_running("start_free_power_override", False)
    h.set_g(free_power_operation_in_progress=False)
    run_polled(h, 175_000)
    e.eq(h.g("failback_shadow_seen_active_fp"), True, "T-C28 FB-C saw the FP domain busy")
    # restore (verified): the lease ends, flags clear
    h.free_power(active_persisted=False, restore_requested=True)
    h.set_running("restore_free_power_snapshot")
    run_polled(h, 185_000)
    h.set_running("restore_free_power_snapshot", False)
    h.free_power(snapshot_valid=False, marker_state=0, restore_requested=False)
    h.run(3_000)
    e.eq(h.oracle.last["rd"].ca, cap.CQ_PRE_FENCE, "T-C28 the lease ending re-opens the shared write fence (ca=P until two polls)")
    for _ in range(3):
        run_polled(h, h.now + 60_000)
    inp = h.inputs()
    e.eq(inp["fp"], "CR", "T-C28 after the START + restore the FP basis is R (runtime), no longer A")
    e.eq(inp["dp"], "CM", "T-C28 the LOAD_OK domain stays M")
    e.eq((inp["pl"], inp["rs"]), (str(sh.PLAN_WOULD_ALREADY_MATCH), str(sh.RS_MATCH_E1_AND_CTX)),
         f"T-C28 with basis R the absence rule no longer blocks: {h.text(INPUTS)}")
    e.eq(h.oracle.last["rd"].absence_relied, False, "T-C28 absence no longer relied on")
    e.clean(h)
    return e.fails


# ===========================================================================
# Episode machine on the new lambda (the C1 behaviours must survive)
# ===========================================================================
def tc_e_open_close(fw=None):
    e = Exp()
    h = mk(fw)
    last, r = 130_000, 500_000
    edge = last + LOST_MS
    outage(h, last_beat=last, run_to=edge + 2_000)
    g = h.g
    e.eq((g("failback_shadow_phase"), g("failback_shadow_ep"), g("failback_shadow_ep_trigger")), (1, 1, 1), "T-C02 OPEN, one episode, trigger H")
    e.eq(g("failback_shadow_ep_edge_ms"), edge, "T-C02 t_edge = last_valid + T_lost")
    e.eq(g("failback_shadow_ep_edge_uptime_s"), edge // 1000, "T-C02 u0")
    e.near(g("failback_shadow_ep_reboot_margin_s"), 600, 3, "T-C02 rb ~ 600")
    e.eq(h.text(STATE), "SHADOW_EPISODE", "T-C02 State")
    return_beats(h, r, r + 1_800_000)
    run_polled(h, r + 5_000)
    e.eq((g("failback_shadow_phase"), h.text(STATE)), (2, "SHADOW_EPISODE_HA_BACK"), "T-C03 HA_BACK")
    e.eq(g("failback_shadow_ep_return_s"), (r - edge) // 1000, "T-C03 ret")
    s3 = r + 60_000
    close_tick = tick_at_or_after(s3 + CLOSE_MS)
    h.run_until(close_tick - 1)
    e.eq(g("failback_shadow_phase"), 2, "T-C03 not closed one ms before the close tick")
    h.run_until(close_tick)
    e.eq(g("failback_shadow_phase"), 3, "T-C03 closed at the first FB-C tick with now >= r + 360 s")
    e.eq(g("failback_shadow_ep_close_s"), (close_tick - edge) // 1000, "T-C03 cl")
    e.eq(kv(h, EPS)["fbf"], "P", "T-C03 fbf=P (readiness match, kind N)")
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C03 State after a P close")
    e.clean(h)
    # T-C06 beat 1 s after the LOST edge (never NONE or CLOSED)
    h = mk(fw)
    outage(h, last_beat=last, run_to=edge + 1_000)
    h.schedule_beats([edge + 1_750])
    seen = []
    for t in range(edge + 1_500, edge + 6_000, 500):
        h.run_until(t)
        seen.append((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")))
    e.ok(all(p in (1, 2) and n == 1 for p, n in seen), f"T-C06 never NONE or CLOSED: {seen}")
    e.eq(seen[-1][0], 2, "T-C06 HA_BACK")
    e.clean(h)
    # T-C06b the after-edge guard
    h = mk(fw)
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    last_edge = h.g("failback_shadow_ep_last_edge_ms")
    h.sim.set_global("supervision_valid_count", h.g("supervision_valid_count") + 1)
    h.sim.set_global("supervision_last_valid_ms", last_edge - 1_000)
    h.sim.now_ms += 1_000
    h.fbc_tick()
    e.eq(h.g("failback_shadow_phase"), 1, "T-C06b a beat older than the edge never returns an OPEN episode")
    e.clean(h)
    return e.fails


def tc_e_flap(fw=None):
    e = Exp()
    last, r1, r2 = 130_000, 500_000, 1_000_000
    h = mk(fw)
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats_every(r1, 30_000, r1 + 120_000)
    h.schedule_beats_every(r2, 30_000, r2 + 400_000)
    seq = []
    for t in range(432_000, 1_100_000, 1_000):
        h.run_until(t)
        if t % 60_000 < 1_000:
            h.poll()
        p = h.g("failback_shadow_phase")
        if not seq or seq[-1] != p:
            seq.append(p)
        if h.g("failback_shadow_ep") != 1:
            e.fails.append(f"T-C07 more than one episode at t={t}")
            break
    e.eq(seq, [1, 2, 1, 2], "T-C07 OPEN -> HA_BACK -> OPEN -> HA_BACK, never NONE or CLOSED")
    e.eq(h.g("failback_shadow_ep_relost"), 1, "T-C07 rl = 1")
    e.eq(kv(h, EPS)["rl"], "1", "T-C07 Episode rl")
    e.eq(kv(h, EPS)["k"], "N", "T-C07 one kind-N episode")
    e.eq(h.g("failback_shadow_ep_v0"), sh.PLAN_WOULD_ALREADY_MATCH, "T-C07 the edge plan is frozen once, at the FIRST edge")
    e.clean(h)
    # T-C12: a 15-minute reboot loop, each boot opens a fresh kind-N episode; HA returns on the last boot
    h = mk(fw)
    nonces = [h.nonce]
    for boot in range(3):
        h.set_words(X.GW)
        prime(h)
        run_polled(h, LOST_MS + 5_000)
        e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep"), h.g("failback_shadow_ep_trigger"), h.g("failback_shadow_ep_kind")),
             (1, 1, 2, sh.EPK_N), f"T-C12 boot {boot}: one trigger-S kind-N episode")
        h.reboot()
        nonces.append(h.nonce)
        e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep"), h.g("failback_shadow_would_latched")), (0, 0, False),
             f"T-C12 boot {boot + 1}: nothing carried across, the latch is gone")
    e.eq(len(set(nonces)), 4, "T-C12 distinct nonces")
    e.clean(h)
    # T-C08: one skipped beat re-latches stable_since
    h = mk(fw)
    r = 500_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats([r + 30_000 * k for k in range(0, 9)])
    h.schedule_beats_every(r + 300_000, 30_000, r + 1_000_000)
    s2 = r + 300_000 + 60_000
    close_tick = tick_at_or_after(s2 + CLOSE_MS)
    phases = []
    for t in range(r + 1_000, close_tick + 3_000, 1_000):
        h.run_until(t)
        if t % 60_000 < 1_000:
            h.poll()
        phases.append((t, h.g("failback_shadow_phase")))
    closed_at = next((t for t, p in phases if p == 3), None)
    e.ok(all(p == 2 for t, p in phases if t < close_tick), "T-C08 never closed before the re-qualified window ends")
    e.ok(closed_at is not None and close_tick <= closed_at <= close_tick + 1_000, f"T-C08 closes 300 s after the re-latched stable_since: {closed_at} vs {close_tick}")
    e.clean(h)
    return e.fails


def tc_e_age_recheck(fw=None):
    """T-C23: FB-C runs before the PR-A tick at age 45.5 s while supervision_stable is still true: P_STABLE false, no close."""
    e = Exp()
    last, r = 130_000, 500_000
    h = mk(fw, tie=X.hx.Harness.TIE_FBC_FIRST, fbc_offset_ms=0, pra_offset_ms=0)
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats([r + 30_000 * k for k in range(0, 10)])
    s = r + 60_000
    b_last = s + 254_700
    h.schedule_beats([b_last])
    t_crit = s + CLOSE_MS
    run_polled(h, t_crit - 1_000)
    e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_stable_since_ms")), (2, s), "T-C23 still HA_BACK, stable_since latched")
    e.ok(h.g("supervision_stable") and h.g("supervision_state") == 1, "T-C23 setup: PR-A's own flag is still true")
    h.run_until(t_crit)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C23 no close: P_STABLE false at age 45.3 s")
    e.eq((h.g("failback_shadow_stable_prev"), h.g("failback_shadow_stable_since_ms")), (False, s), "T-C23 stable false, since unchanged")
    e.eq(h.inputs()["st"], "0", "T-C23 Inputs st=0 (sup.p_stable is P_STABLE, not the raw flag)")
    e.clean(h)
    return e.fails


def tc_e_order(fw=None):
    """T-C04: both tick orders, same / swapped offsets and randomised phases give the same episode records (including the frozen
    plan and the close outcome)."""
    e = Exp()
    last, r = 130_000, 500_000

    def run(**kw):
        h = mk(fw, **kw)
        outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
        return_beats(h, r, r + 1_800_000)
        run_polled(h, r + 430_000)
        return h

    ref = run(tie=X.hx.Harness.TIE_FBC_FIRST)
    ref_kv = kv(ref, EPS)
    e.eq((ref_kv["ph"], ref_kv["fbf"], ref_kv["v0"]), ("C", "P", "40"), f"T-C04 reference run closed: {ref.text(EPS)}")
    skip = ("cl", "rb", "vch")
    variants = [("pra first, same offset", dict(tie=X.hx.Harness.TIE_PRA_FIRST, fbc_offset_ms=300, pra_offset_ms=300)),
                ("fbc first, same offset", dict(tie=X.hx.Harness.TIE_FBC_FIRST, fbc_offset_ms=300, pra_offset_ms=300)),
                ("offsets swapped", dict(fbc_offset_ms=750, pra_offset_ms=250))] + \
               [(f"random seed {s} drift", dict(seed=s, fbc_offset_ms=None, pra_offset_ms=None, drift_ms=30)) for s in range(1, 6)]
    for label, kw in variants:
        h = run(**kw)
        k = kv(h, EPS)
        for f in ref_kv:
            if f in skip:
                continue
            e.eq(k[f], ref_kv[f], f"T-C04 {label}: {f}")
        e.eq(kv(h, SOAK).get("wr"), kv(ref, SOAK).get("wr"), f"T-C04 {label}: wr")
        e.near(int(k["cl"]), int(ref_kv["cl"]), 1, f"T-C04 {label}: cl")
        e.near(int(k["vch"]), int(ref_kv["vch"]), 0, f"T-C04 {label}: vch is order independent")
        e.clean(h)
    e.clean(ref)
    return e.fails


def tc_e_publish(fw=None):
    """T-C16: de-duplication and rate. 1 h steady state: zero publishes after boot; verdict flapping at 1 Hz inside an episode:
    at most 6 Verdict / Inputs publishes per minute and the final value is flushed within 10 s."""
    e = Exp()
    h = mk(fw)
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 3_700_000)
    prime(h)
    run_polled(h, 200_000)
    c0 = h.fbc_publish_counts()
    run_polled(h, 3_700_000)
    c1 = h.fbc_publish_counts()
    for ent in (STATE, EPS, VERDICT, INPUTS):
        e.eq(c1[ent], c0[ent], f"T-C16 {ent}: 0 publishes in 1 h steady state")
    e.ok(c1[SOAK] - c0[SOAK] <= 61, f"T-C16 Soak <= 1/min in steady state ({c1[SOAK] - c0[SOAK]})")
    e.clean(h)
    # flapping: toggle the polling switch every second inside an episode (the plan flips between WAIT_LIVE_DATA and a real plan)
    h = mk(fw)
    last = 130_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    e.eq(h.g("failback_shadow_phase"), 1, "T-C16 setup: OPEN")
    base = h.fbc_publish_counts()
    t0 = h.now
    for k in range(1, 181):
        h.config_polling(k % 2 == 0)
        h.run_until(t0 + k * 1_000)
    cf = h.fbc_publish_counts()
    for ent in (VERDICT, INPUTS):
        e.ok(cf[ent] - base[ent] <= 6 * 3 + 1, f"T-C16 {ent}: <= 6 publishes per minute under 1 Hz flapping ({cf[ent] - base[ent]} in 3 min)")
        e.ok(cf[ent] - base[ent] >= 5, f"T-C16 {ent}: the flapping really publishes ({cf[ent] - base[ent]})")
    vch = h.g("failback_shadow_ep_verdict_changes")
    e.ok(vch >= 150, f"T-C16 vch counts the flapping every tick (vch={vch})")
    h.config_polling(True)
    h.run_until(h.now + 12_000)
    e.eq(h.verdict(), sh.plan_name(h.oracle.last["verdict"]), "T-C16 the final verdict is flushed within 10 s")
    e.eq(h.text(INPUTS), h.oracle.last["want_inputs"], "T-C16 the final Inputs is flushed within 10 s")
    e.clean(h)
    # vch saturates at 65535
    h.set_g(failback_shadow_ep_verdict_changes=65535)
    h.config_polling(False)
    h.run(3_000)
    h.config_polling(True)
    h.run(3_000)
    e.eq(h.g("failback_shadow_ep_verdict_changes"), 65535, "T-C16 vch saturates at 65535")
    return e.fails


def tc_vch(fw=None):
    """vch counts verdict changes while the episode is open; the opening tick does not count; the text follows within 10 s."""
    e = Exp()
    h = mk(fw)
    last = 130_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    e.eq(h.g("failback_shadow_ep_verdict_changes"), 0, "vch: the opening tick does not count")
    h.config_polling(False)
    h.run(3_000)
    e.eq(h.g("failback_shadow_ep_verdict_changes"), 1, "vch +1 as the verdict goes to WAIT_LIVE_DATA")
    h.run(12_000)
    e.eq(h.verdict(), "WAIT_LIVE_DATA", "vch: polling off during the episode -> WAIT_LIVE_DATA (published within the 10 s window)")
    e.eq(kv(h, EPS)["vch"], "1", "vch in the Episode text after the 10 s window")
    h.config_polling(True)
    h.run(3_000)
    e.eq(h.g("failback_shadow_ep_verdict_changes"), 2, "vch +1 again when it goes back")
    h.run(12_000)
    e.eq((kv(h, EPS)["vch"], h.verdict()), ("2", "WOULD_ALREADY_MATCH"), "vch 2 / verdict back")
    e.clean(h)
    # The opening tick never counts, even when the plan changes ON it. Under the readiness Verdict the plan before the edge already
    # is the continuation plan, so only an input that changes on the edge tick itself makes the two differ: here an FP lease that
    # starts between the PR-A tick that declares LOST and the FB-C tick that opens the episode.
    h2 = mk(fw)
    outage(h2, last_beat=last, run_to=last + LOST_MS - 10_000)
    le0, before, opened = h2.g("supervision_lost_events"), None, False
    while not opened and h2.now < last + LOST_MS + 30_000:
        t = tick_at_or_after(h2.now + 1)
        h2.run_until(t - 1)
        if before is None and h2.g("supervision_lost_events") != le0 and h2.g("failback_shadow_phase") == 0:
            before = h2.verdict()
            _fp_active(h2)
        h2.run_until(t + 1)
        opened = h2.g("failback_shadow_phase") == 1
    pre_fp = sh.plan_name(sh.PLAN_WOULD_PREEMPT_FREE_POWER)
    e.eq((before, opened), ("WOULD_ALREADY_MATCH", True), "vch: an FP lease starts between LOST and the opening FB-C tick")
    e.eq((h2.verdict(), h2.g("failback_shadow_ep_v0")), (pre_fp, sh.PLAN_WOULD_PREEMPT_FREE_POWER),
         "vch: the opening tick publishes and freezes the changed plan")
    e.eq(h2.g("failback_shadow_ep_verdict_changes"), 0, "vch: a plan change ON the opening tick does not count")
    e.clean(h2)
    return e.fails


def tc_not_ready(fw=None):
    """T-C18: the tick returns at E0 while supervision_generation == 0: zero changes, including its own globals and every text."""
    e = Exp()
    h = mk(fw)
    h.sim.set_global("supervision_generation", 0)
    g0 = {k: X._frz(v) for k, v in h.sim.g.items()}
    p0 = {k: len(v.published) for k, v in h.sim.entities.items()}
    for _ in range(5):
        h.tick(1_000)
    e.ok({k: X._frz(v) for k, v in h.sim.g.items()} == g0, "T-C18 generation == 0: every global (including the shadow's own) unchanged")
    e.ok({k: len(v.published) for k, v in h.sim.entities.items()} == p0, "T-C18 nothing published")
    e.eq(h.g("failback_shadow_ready"), False, "T-C18 not ready")
    h.sim.set_global("supervision_generation", 1)
    h.tick(1_000)
    e.eq(h.g("failback_shadow_ready"), True, "T-C18 ready once the generation is set")
    e.ok(h.verdict() != "" and h.text(INPUTS) != "", "T-C18 the first ready tick publishes Verdict and Inputs")
    e.clean(h)
    return e.fails


def tc_wr(fw=None):
    """T-C13 on the live lambda: START attempts counted while a future FB-D / FB-F would refuse (WATCH, episode open / HA_BACK)."""
    e = Exp()
    h = mk(fw)

    def wr():
        return h.soak_wr()

    h.run_until(5_000)
    h.set_g(free_power_operation_in_progress=True)
    h.run_until(6_000)
    e.eq(wr(), (1, 0, 0, 0), "T-C13 FP START while WATCH")
    e.eq(h.soak_kv().get("wr"), "1/0/0/0", "T-C13 Soak wr=1/0/0/0 published immediately")
    h.set_g(free_power_operation_in_progress=False)
    h.run_until(12_000)
    h.set_g(free_power_operation_in_progress=True)  # a failed START sets only the op flag
    h.run_until(13_000)
    e.eq(wr(), (2, 0, 0, 0), "T-C13 a failed START (op flag only) counts")
    h.set_g(free_power_operation_in_progress=False)
    h.schedule_beats_every(20_000, 30_000, 200_000)
    h.run_until(150_000)
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C13 stable, no episode")
    h.set_g(free_power_operation_in_progress=True)
    h.run_until(152_000)
    e.eq(wr(), (2, 0, 0, 0), "T-C13 a START while stable and no episode is NOT counted")
    h.set_g(free_power_operation_in_progress=False)
    h.run_until(200_000 + LOST_MS + 3_000)
    e.eq(h.g("failback_shadow_phase"), 1, "T-C13 setup: OPEN")
    h.set_g(reg244_apply_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (2, 0, 1, 0), "T-C13 R244 START while OPEN")
    h.set_g(reg244_apply_in_progress=False)
    r = 600_000
    h.schedule_beats_every(r, 30_000, r + 600_000)
    h.run_until(r + 20_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C13 setup: HA_BACK")
    h.set_g(dump_operation_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (2, 1, 1, 0), "T-C13 Dump START while HA_BACK")
    h.set_g(dump_operation_in_progress=False)
    h.run_until(r + 420_000)
    e.eq(h.g("failback_shadow_phase"), 3, "T-C13 setup: CLOSED (cache never trusted: the edge plan was not 'already at the profile': latched)")
    h.set_g(free_power_operation_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (3, 1, 1, 0), "T-C13 after an A close the latch keeps P_WOULD_REFUSE true: a START counts")
    h.set_g(free_power_operation_in_progress=False)
    e.clean(h)
    # obligations loaded at boot are not STARTs
    h2 = mk(fw)
    h2.set_g(free_power_snapshot_valid=True)
    h2.run_until(5_000)
    e.eq((h2.g("failback_shadow_wr_fp"), h2.g("failback_shadow_busy_fp")), (0, True), "T-C13 a boot-loaded snapshot seeds busy_fp, no count")
    h2.set_g(free_power_snapshot_valid=False)
    h2.run_until(8_000)
    h2.set_g(free_power_operation_in_progress=True)
    h2.run_until(10_000)
    e.eq(h2.g("failback_shadow_wr_fp"), 1, "T-C13 a real START after the seed counts")
    e.clean(h2)
    return e.fails


def tc_harness_selftest(fw=None):
    """[H] The audit and the oracle can fail: every kind of side effect is detected, a clean tick is not, and a tampered shadow state is
    seen by the oracle. (Negative controls of the instruments themselves.)"""
    e = Exp()
    evil = {
        "modbus": ("Modbus", lambda s: s.modbus_log.append(("write", 244, [2], "ok"))),
        "direct NVS read": ("direct NVS", lambda s: s.nvs_direct.get_stats()),
        "tag store": ("tag store", lambda s: s.nvs.__setitem__("zz", 1)),
        "durable commit": ("tag store", lambda s: s.nvs_commits.append(("k", 0))),
        "durable event": ("tag store", lambda s: s.events.append(("x",))),
        "executed script": ("executed a script", lambda s: s.executed.append(("restore_reg244_snapshot", {}))),
        "started script": ("started / stopped", lambda s: s.running.add("dump_controller_tick")),
        "published other entity": ("published", lambda s: s.ent("ecco_tou1_raw_flags").publish_state(1.0)),
        "non-FB global": ("non-FB globals", lambda s: s.set_global("manual_write_attempts", s.g["manual_write_attempts"] + 1)),
        "in-place array write": ("non-FB globals", lambda s: s.g["fallback_profile_bytes"].__setitem__(0, 9)),
        "entity read outside the allow-list": ("accessed entities", lambda s: s.ent("ecco_tou2_raw_flags").state),
        "allowed entity state changed": ("changed entity state", lambda s: s.ent("configuration_online").set(True)),
    }
    for label, (token, side) in evil.items():
        h = mk(fw, oracle=False)
        orig = h.sim.run_lambda

        def run(code, *a, _orig=orig, _h=h, _side=side, **k):
            r = _orig(code, *a, **k)
            if code is _h._fbc1:
                _side(_h.sim)
            return r

        h.sim.run_lambda = run
        h.sim.now_ms += 1_000
        h.fbc_tick()
        e.ok(any(token in v for v in h.violations), f"[H] audit detects: {label} ({h.violations[:2]})")
        h.violations.clear()
        h.sim.run_lambda = orig
        _SINK[0].remove(h)  # these deliberately dirty harnesses must not feed the global Z9 check
    h = mk(fw, oracle=True)
    h.sup(1, True)
    h.tick(1_000)
    h.sup(1, True)
    h.tick(1_000)
    e.ok(not h.violations and not h.oracle_errors, "[H] a clean tick passes the audit and the oracle")
    h.set_g(failback_shadow_would_latched=True)  # a tampered shadow state: the oracle must see it
    h.sup(1, True)
    h.tick(11_000)
    e.ok(any("would_latched" in x for x in h.oracle_errors), f"[H] oracle detects a tampered would_latched ({h.oracle_errors[:1]})")
    h.oracle.errors.clear()
    h.set_g(failback_shadow_would_latched=False)
    # the oracle's world mapping is not the lambda's: a collector that reads a stale word is caught
    h2 = mk(fw, oracle=True)
    h2.set_words(X.GW)
    cache_setup(h2, "F", Stats())
    h2.sup(1, True)
    h2.tick(11_000)
    h2.set_g(failback_shadow_live_seq=h2.g("cfg_block_b_seq") - 1)  # forces a re-latch the oracle did not expect only if the words change
    h2.set_words(_words_with({256: 7000}))
    h2.sup(1, True)
    h2.tick(11_000)
    e.ok(h2.oracle_errors, "[H] oracle detects a lambda that re-latched when it should not have")
    h2.oracle.errors.clear()
    h2.violations.clear()
    h.violations.clear()
    h.oracle.errors.clear()
    return e.fails


# ---- strings -------------------------------------------------------------------------------------------------------------------------
def card_regexes() -> list:
    out, seen = [], set()
    files = sorted(CARD_SRC.glob("*.ts")) + sorted((CARD_SRC / "utils").glob("*.ts"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        pats = [m for m in re.finditer(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", src)]
        pats += [m for m in re.finditer(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", src)]
        for m in pats:
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append((m.group(1), re.I if "i" in m.group(2) else 0, f.name))
    return out


WORST_EP = dict(ep=65535, ep_trigger=2, ep_edge_ms=WRAP - 1, ep_last_edge_ms=WRAP - 1, ep_edge_uptime_s=WRAP - 2,
                ep_edge_epoch=WRAP - 1, ep_client_at_edge=True, ep_reboot_margin_s=2_000_000_000, ep_return_s=WRAP - 2,
                ep_return_gap_ms=WRAP - 2, ep_relost=65535, ep_close_s=WRAP - 2, ep_fbf=1, ep_kind=2, ep_v0=50, ep_vu=41, ep_f0=11,
                ep_dm0=11, ep_pre0=3, ep_blk0=15, ep_d0=19, ep_verdict_changes=65535)
WORST_SOAK = dict(gap_b0=65535, gap_b1=65535, gap_b2=65535, gap_b3=65535, gap_b4=65535, gap_b5=65535, gap_max_ms=WRAP - 2,
                  gap_last_long_ms=WRAP - 2, gaps_missed=65535, nc=65535, ncm_ms=WRAP - 2, wr_fp=65535, wr_dump=65535,
                  wr_r244=65535, wr_prof=65535, exh_yes_ms=WRAP - 1, exh_unk_ms=WRAP - 1, ca_f_ms=WRAP - 1, ca_p_ms=WRAP - 1,
                  ca_o_ms=WRAP - 1)


def worst_case_strings(fw=None):
    """Every field at maximum width; returns (strings, harness)."""
    h = mk(fw, oracle=False)
    out = []
    h.set_profile(X.make_profile(0xFFFFFFFF), cls=fd.EPC_VALID)
    h.beat()
    h.run_until(2_000)
    for phase in (1, 2, 3):
        for k, v in {**WORST_EP, **WORST_SOAK}.items():
            h.sim.set_global("failback_shadow_" + k, v)
        h.sim.set_global("failback_shadow_phase", phase)
        h.sim.set_global("supervision_boot_nonce", 0xFFFFFFFF)
        h.sim.set_global("failback_shadow_last_pub_episode_ms", 0)
        h.sim.set_global("failback_shadow_last_pub_soak_ms", 0)
        h.sim.set_global("failback_shadow_last_pub_verdict_ms", 0)
        h.sim.set_global("failback_shadow_last_pub_inputs_ms", 0)
        h.sim.now_ms += 70_000
        h.sim.set_global("supervision_last_valid_ms", h.sim.millis())
        h.sim.set_global("failback_shadow_seen_svc", h.g("supervision_valid_count"))
        h.sim.set_global("failback_shadow_seen_lost", h.g("supervision_lost_events"))
        h.sim.set_global("failback_shadow_seen_last_valid_ms", h.sim.millis())
        h.fbc_tick()
        out += [h.text(EPS), h.text(SOAK), h.text(VERDICT), h.text(INPUTS)]
    return out, h


def tc_strings(fw=None):
    e = Exp()
    strings, h = worst_case_strings(fw)
    eps = [s for s in strings if s.startswith("id=")]
    soak = [s for s in strings if s.startswith("b=")]
    e.ok(eps and soak and all(len(s) > 0 for s in strings), "strings: worst-case strings were produced")
    e.ok(max(len(s) for s in strings) <= 200, f"strings: worst-case length {max(len(s) for s in strings)} <= 200")
    e.ok(any("ph=C" in s for s in eps) and any("ph=B" in s for s in eps) and any("ph=O" in s for s in eps), "strings: every phase rendered")
    e.ok(any("rl=65535;vch=65535" in s for s in eps) and any("v0=50;vu=41;f0=11;dm=11;pre=3;blk=F;d=19" in s for s in eps),
         "strings: the plan fields are rendered at maximum width")
    e.ok(any("wr=65535/65535/65535/65535" in s for s in soak) and any("xh=999999/999999;cs=999999/999999/999999" in s for s in soak),
         "strings: wr p, xh and cs saturate / render at maximum width")
    e.ok(any("g=4294967295" in s for s in strings), "strings: the largest profile generation is rendered in Inputs")
    names = [sh.plan_name(c) for c in range(256)]
    e.ok(max(len(n) for n in names) <= 48, "strings: every Verdict name <= 48 chars")
    e.ok(max(len(s) for s in ("SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WOULD_AWAIT_ACK", "SHADOW_WATCH", "SHADOW_IDLE")) <= 48,
         "strings: State names")
    e.clean(h)
    return e.fails


# ===========================================================================
# Soak telemetry
# ===========================================================================
def hazard_obligation_spec(rd) -> bool:
    """FINAL 8.2's obligation term, written here from the spec over the published domain views (independent of the evaluator's own
    hazard_obligation flag): a DUMP / FP / R244 domain that is not clear and is neither ACTIVE nor STARTING."""
    if rd.row in (sh.ROW_E0, sh.ROW_E1):
        return False
    return any(d.c0 != sh.C0_CLEAR_PROVEN and d.kind not in (sh.KIND_ACTIVE, sh.KIND_STARTING)
               for d in (rd.dom[sh.DS_DUMP], rd.dom[sh.DS_FP], rd.dom[sh.DS_R244]))


def tc_soak(fw=None):
    e = Exp()
    # cs: seconds per cache state, accumulated per tick from rd.ca; xh: export hazard YES / UNKNOWN, counted ONLY while an
    # export-relevant lease obligation is open (FINAL 8.2)
    h = mk(fw)
    exp_cs = [0, 0, 0]
    exp_xh = [0, 0]

    def acct(dt):
        L = h.oracle.last
        ca = L["rd"].ca
        i = 0 if ca == cap.CQ_FRESH else 1 if ca == cap.CQ_PRE_FENCE else 2
        exp_cs[i] += dt
        if not hazard_obligation_spec(L["rd"]):
            return
        if L["rd"].export_hazard == cap.EH_YES:
            exp_xh[0] += dt
        elif L["rd"].export_hazard == cap.EH_UNKNOWN:
            exp_xh[1] += dt

    def tk():
        h.sup(1, True)
        h.tick(1000)
        acct(1000)

    h.free_power(operator_needed=True)  # with the FP marker ABSENT at boot: marker-lost - a bad domain whose RAM legs are clear
    h.set_g(free_power_marker_boot_load=1)
    h.set_words(_words_with({244: 0}))  # live 244 = 0 so the export hazard can be YES
    h.sup(1, True)
    h.tick(1000)  # the first tick seeds the accumulator clock (dt = 0)
    for _ in range(5):
        tk()
    for _ in range(3):
        h.poll()
    for _ in range(40):
        tk()
    # the honest fence cost: a routine write re-opens the fence (cs P seconds grow), then two polls pass it again
    h.bump_write_attempts("manual_write_attempts")
    for k in range(30):
        if k in (10, 20):
            h.poll()
        tk()
    got_cs = (h.g("failback_shadow_ca_f_ms") // 1000, h.g("failback_shadow_ca_p_ms") // 1000, h.g("failback_shadow_ca_o_ms") // 1000)
    got_xh = (h.g("failback_shadow_exh_yes_ms") // 1000, h.g("failback_shadow_exh_unk_ms") // 1000)
    e.eq(got_cs, tuple(v // 1000 for v in exp_cs), "soak: cs=<F>/<P>/<other> accumulates one second per tick by rd.ca")
    e.eq(got_xh, tuple(v // 1000 for v in exp_xh), "soak: xh=<yes>/<unknown> accumulates by the export-hazard state")
    e.ok(all(v > 0 for v in got_cs), f"soak: all three cs buckets exercised {got_cs}")
    e.ok(all(v > 0 for v in got_xh), f"soak: both xh buckets exercised {got_xh}")
    e.eq(sum(got_cs), 75, "soak: every tick lands in exactly one cs bucket (the seeding tick has dt = 0)")
    h.sup(1, True)
    h.tick(61_000)  # the Soak text is published at most once per minute: it catches up
    kvs = h.soak_kv()
    want_cs = tuple(v // 1000 for v in (h.g("failback_shadow_ca_f_ms"), h.g("failback_shadow_ca_p_ms"), h.g("failback_shadow_ca_o_ms")))
    want_xh = (h.g("failback_shadow_exh_yes_ms") // 1000, h.g("failback_shadow_exh_unk_ms") // 1000)
    e.eq((h.soak_cs(), h.soak_xh()), (want_cs, want_xh), "soak: the published Soak text carries the accumulators (after the minute gate)")
    e.eq(len(kvs["wr"].split("/")), 4, "soak: wr has four fields (f/d/r/p)")
    e.clean(h)
    # saturation: 999999 on the rendered fields, the accumulators stop at 2^32-1 (an open obligation - the FP marker lost - with an
    # untrusted cache makes the hazard UNKNOWN time count)
    h = mk(fw)
    h.free_power(operator_needed=True)
    h.set_g(free_power_marker_boot_load=1)
    h.set_g(failback_shadow_ca_f_ms=0xFFFFFFFF - 500, failback_shadow_exh_unk_ms=0xFFFFFFFF - 500,
            failback_shadow_ca_p_ms=0xFFFFFFFF, failback_shadow_ca_o_ms=0xFFFFFFFF - 10)
    h.sup(1, True)
    h.tick(1000)
    h.sup(1, True)
    h.tick(2000)
    e.eq(h.g("failback_shadow_exh_unk_ms"), 0xFFFFFFFF, "soak: the unknown accumulator saturates at 2^32-1 (no wrap)")
    e.eq(h.g("failback_shadow_ca_o_ms"), 0xFFFFFFFF, "soak: the other-cache accumulator saturates")
    h.sup(1, True)
    h.tick(61_000)
    e.ok("xh=0/999999" in h.text(SOAK) and "cs=999999/999999/999999" in h.text(SOAK), f"soak: rendered saturated at 999999: {h.text(SOAK)}")
    e.clean(h)
    # the pre-fence consequence during an episode: WAIT_LIVE_DATA / LIVE_CACHE_PRE_FENCE, vch counts the flapping
    h = mk(fw)
    last, r = 130_000, 500_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    return_beats(h, r, r + 1_800_000)
    run_polled(h, r + 100_000)
    e.eq(kv(h, INPUTS)["ca"], "F", "soak: setup: HA_BACK with a trusted cache")
    vch0 = h.g("failback_shadow_ep_verdict_changes")
    p0 = h.g("failback_shadow_ca_p_ms")
    h.bump_write_attempts("manual_write_attempts")  # a routine RTC correction / write re-opens the fence
    h.run(12_000)
    e.eq((kv(h, INPUTS)["ca"], kv(h, INPUTS)["rs"], h.verdict()), ("P", str(sh.RS_LIVE_CACHE_PRE_FENCE), "WAIT_LIVE_DATA"),
         f"soak: during the episode the write fence gives WAIT_LIVE_DATA / LIVE_CACHE_PRE_FENCE: {h.text(INPUTS)}")
    h.poll()
    h.run(12_000)
    h.poll()
    h.run(12_000)
    e.eq(kv(h, INPUTS)["ca"], "F", "soak: two polls later the fence is passed")
    e.eq(h.verdict(), "WOULD_ALREADY_MATCH", "soak: ... and the verdict is back")
    e.ok(h.g("failback_shadow_ep_verdict_changes") >= vch0 + 2, "soak: vch counted the verdict going out and back")
    e.ok(h.g("failback_shadow_ca_p_ms") >= p0 + 24_000, f"soak: the pre-fence share grew ({p0} -> {h.g('failback_shadow_ca_p_ms')} ms)")
    # a routine write / RTC correction every minute keeps the cache pre-fence almost all of the time (the honest cost of the shared fence)
    p1 = h.g("failback_shadow_ca_p_ms")
    for _ in range(6):
        h.bump_write_attempts("manual_write_attempts")
        h.run(30_000)
        h.poll()
        h.run(30_000)
    e.ok(h.g("failback_shadow_ca_p_ms") - p1 >= 300_000,
         f"soak: with a write every minute the P bucket dominates ({h.g('failback_shadow_ca_p_ms') - p1} of 360000 ms)")
    e.eq(kv(h, INPUTS)["pl"], str(sh.PLAN_WAIT_LIVE_DATA), "soak: ... and the readiness plan stays WAIT_LIVE_DATA while the writes keep coming")
    e.clean(h)
    return e.fails


def tc_xh(fw=None):
    """Soak `xh` (remediation M5): export-hazard time is counted ONLY while an export-relevant lease obligation is open (FINAL 8.2).
    export_hazard() itself is unchanged and shared with the Live Match; only the soak accounting is gated.
      (a) every lease clear, cache untrusted (hazard UNKNOWN)            -> xh unchanged
      (b) an open obligation (Dump operator-needed, 244 = 0), UNKNOWN    -> xh UNKNOWN grows one second per tick, YES unchanged
      (c) an open obligation (the FP marker lost), trusted cache, YES    -> xh YES grows one second per tick, UNKNOWN unchanged
      (d) normal operation: every lease clear, trusted cache, hazard NO  -> xh unchanged"""
    e = Exp()

    def xh(h):
        return (h.g("failback_shadow_exh_yes_ms"), h.g("failback_shadow_exh_unk_ms"))

    def run_ticks(h, n):
        for _ in range(n):
            h.sup(1, True)
            h.tick(1000)

    def hz(h):
        rd = h.oracle.last["rd"]
        return rd.export_hazard, hazard_obligation_spec(rd)

    # (a)
    h = mk(fw)
    run_ticks(h, 1)  # seeds the accumulator clock
    run_ticks(h, 20)
    e.eq(hz(h), (cap.EH_UNKNOWN, False), "xh (a) setup: hazard UNKNOWN (cache untrusted) and no obligation")
    e.eq(xh(h), (0, 0), "xh (a) untrusted cache + no obligation: xh unchanged")
    e.clean(h)
    # (b)
    h = mk(fw)
    h.dump(snapshot_valid=True, marker_state=1, operator_needed=True)
    h.set_words(_words_with({244: 0}))
    run_ticks(h, 1)
    x0 = xh(h)
    run_ticks(h, 10)
    e.eq(hz(h), (cap.EH_UNKNOWN, True), "xh (b) setup: an open Dump obligation, hazard UNKNOWN (the open lease keeps the fence hot)")
    e.eq((xh(h)[0] - x0[0], xh(h)[1] - x0[1]), (0, 10_000), "xh (b) open obligation + hazard UNKNOWN: UNKNOWN +10 s, YES unchanged")
    e.clean(h)
    # (c)
    h = mk(fw)
    h.free_power(operator_needed=True)  # with the FP marker ABSENT at boot: FP_MARKER_LOST, an obligation whose RAM legs are clear
    h.set_g(free_power_marker_boot_load=1)
    words = _words_with({244: 0})
    h.set_words(words)
    h.cache_fresh_after(lambda: run_ticks(h, 1), words)
    x0 = xh(h)
    run_ticks(h, 10)
    e.eq(hz(h), (cap.EH_YES, True), "xh (c) setup: an open obligation, trusted cache, live 244 = 0: hazard YES")
    e.eq((xh(h)[0] - x0[0], xh(h)[1] - x0[1]), (10_000, 0), "xh (c) open obligation + hazard YES: YES +10 s, UNKNOWN unchanged")
    e.clean(h)
    # (d)
    for label, w in (("live 244 = 2", None), ("live 244 = 0 (an operator's own Allow Export, no lease)", _words_with({244: 0}))):
        h = mk(fw)
        h.cache_fresh_after(lambda: run_ticks(h, 1), w)
        x0 = xh(h)
        run_ticks(h, 10)
        e.eq(hz(h), (cap.EH_NO, False), f"xh (d) setup [{label}]: every lease clear, trusted cache: hazard NO")
        e.eq(xh(h), x0, f"xh (d) normal operation [{label}]: xh unchanged")
        e.clean(h)
    return e.fails


# ===========================================================================
# More collector facts (S3 11.4) worth pinning
# ===========================================================================
def tc_collector(fw=None):
    e = Exp()
    h = mk(fw)
    st = Stats()
    # boot not loaded: E1 BOOT_NOT_LOADED, ca=B
    h.reset_world()
    cache_setup(h, "B", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq((h.inputs()["rs"], h.inputs()["ca"]), (str(sh.RS_BOOT_NOT_LOADED), "B"), "collector: boot not loaded -> reason 10, ca=B")
    # input invalid (a marker boot load out of range) -> E0 reason 11
    h.reset_world()
    h.set_g(dump_marker_boot_load=77)
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["rs"], str(sh.RS_INPUT_INVALID), "collector: an out-of-range input -> INPUT_INVALID (11)")
    # the Dump retry record is not retained: a Dump 'operator needed' with an ABSENT marker is a RAM inconsistency, never marker-lost
    h.reset_world()
    h.set_g(dump_marker_boot_load=1)
    h.dump(operator_needed=True)
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq((h.inputs()["pl"], h.inputs()["rs"]), (str(sh.PLAN_BLOCKED_DURABLE_UNKNOWN), str(sh.RS_DUMP_RAM_INCONSISTENT)),
         "collector: dump retry evidence is not retained (reason 118 RAM_INCONSISTENT, not 116 MARKER_LOST)")
    # the same flag for Free Power IS retained: marker lost (216)
    h.reset_world()
    h.set_g(free_power_marker_boot_load=1)
    h.free_power(operator_needed=True)
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq((h.inputs()["pl"], h.inputs()["rs"]), (str(sh.PLAN_BLOCKED_DURABLE_UNKNOWN), str(sh.RS_FP_MARKER_LOST)),
         "collector: FP operator-needed retained with an absent marker -> FP_MARKER_LOST (216)")
    e.eq(h.inputs()["fp"], "U20", "collector: ... shown as U20 (diverged)")
    # sup.stable is P_STABLE (age re-check), not the raw flag
    h.reset_world()
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 50_000))
    e.eq(h.inputs()["st"], "0", "collector: PR-A flag true at age 50 s -> st=0")
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["st"], "1", "collector: fresh beat -> st=1")
    # orphan timers: an operation flag with no owner is settling for < 10 s, stuck from 10 s
    h.reset_world()
    h.free_power(operation_in_progress=True)
    h.sup(1, True)
    h.tick(1000)  # first tick: the orphan timer starts
    h.sup(1, True)
    h.tick(5_000)  # 5 s orphaned
    e.eq(now_inputs(h)["fp"], "O7", "collector: an owner-less operation flag younger than 10 s is IN_FLIGHT (O7)")
    h.sup(1, True)
    h.tick(4_900)
    e.eq(now_inputs(h)["fp"], "O7", "collector: ... still IN_FLIGHT at 9.9 s")
    h.sup(1, True)
    h.tick(200)
    e.eq(now_inputs(h)["fp"], "U21", "collector: ... STUCK (U21) from 10 s")
    h.set_running("start_free_power_override")
    h.sup(1, True)
    h.tick(1_000)
    e.eq(now_inputs(h)["fp"], "O2", "collector: with the START owner running the flag is STARTING (O2), timer reset")
    h.set_running("start_free_power_override", False)
    h.sup(1, True)
    h.tick(1_000)
    e.eq(now_inputs(h)["fp"], "O7", "collector: owner gone -> the timer restarts (O7), not stuck at once")
    # the same timer for the manual-write mutex: an owner-less manual_write_in_progress is stuck from 10 s
    h.reset_world()
    h.bus(manual_write_in_progress=True)
    h.sup(1, True)
    h.tick(1000)
    h.sup(1, True)
    h.tick(5_000)
    e.eq(now_inputs(h)["pl"], "14", "collector: bus busy -> WAIT_WRITE_IN_FLIGHT")
    e.eq(h.oracle.last["rd"].reason, sh.RS_LOCK_HELD_SETTLING, "collector: owner-less mutex under 10 s is LOCK_HELD_SETTLING")
    h.sup(1, True)
    h.tick(6_000)
    e.eq(h.oracle.last["rd"].reason, sh.RS_LOCK_HELD_NO_KNOWN_OWNER, "collector: owner-less mutex from 10 s is LOCK_HELD_NO_KNOWN_OWNER")
    # RTC correction lock: stuck after 60 s
    h.reset_world()
    h.bus(correction_in_progress=True, diag_correction_lock_held=True, diag_correction_lock_since_ms=h.sim.millis())
    h.sup(1, True)
    h.tick(30_000)
    e.eq(h.oracle.last["rd"].reason, sh.RS_RTC_CORRECTION_RUNNING, "collector: RTC correction under 60 s is RTC_CORRECTION_RUNNING")
    h.sup(1, True)
    h.tick(31_000)
    e.eq(h.oracle.last["rd"].reason, sh.RS_RTC_LOCK_STUCK, "collector: RTC correction lock held >= 60 s is RTC_LOCK_STUCK")
    # FP lease expiry mirrors the watchdog predicate: wall clock when valid, uptime grace when not
    h.reset_world()
    h.free_power(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=FAR_EPOCH)
    cache_setup(h, "F", st)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(h.inputs()["fp"], "O1", "collector: lease not expired (wall clock valid) -> ACTIVE (O1)")
    h.free_power(end_epoch=1_700_000_000)
    _tick(h, st, 11_000, sup=(1, True, 5, 1000))
    e.eq(now_inputs(h)["fp"], "O3", "collector: lease expired -> RESTORE_REQUIRED (O3)")
    h.set_ntp(False)
    h.free_power(end_epoch=FAR_EPOCH)
    grace = int(SUBS["ecco_free_power_invalid_clock_grace_ms"])
    h.sim.now_ms = grace - 20_000
    h.sup(1, True)
    h.fbc_tick()
    e.eq(now_inputs(h)["fp"], "O1", "collector: clock invalid, uptime inside the grace -> not expired (ACTIVE)")
    h.sim.now_ms = grace + 5_000
    h.sup(1, True)
    h.fbc_tick()
    e.eq(now_inputs(h)["fp"], "O3", "collector: clock invalid, uptime past the grace -> expired")
    h.set_ntp(True)
    # restore backoff: the retry time in the future shows RESTORE_BACKOFF (reason 204), in the past RESTORE_DUE (203)
    h.reset_world()
    h.free_power(snapshot_valid=True, marker_state=1, restore_requested=True)
    h.free_power(restore_next_attempt_ms=(h.sim.millis() + 60_000) & 0xFFFFFFFF)
    h.sup(1, True)
    h.tick(1000)
    e.eq(h.oracle.last["rd"].reason, sh.RS_FP_RESTORE_BACKOFF, "collector: future next_attempt_ms -> RESTORE_BACKOFF")
    h.sup(1, True)
    h.tick(61_000)
    e.eq(h.oracle.last["rd"].reason, sh.RS_FP_RESTORE_DUE, "collector: next_attempt_ms in the past -> RESTORE_DUE")
    # R244 held: BLOCKED_OPERATOR_NEEDED
    h.reset_world()
    h.r244(snapshot_valid=True, marker_state=1, last_applied_valid=True, last_applied_value=2)
    h.sup(1, True)
    h.tick(1000)
    e.eq(h.oracle.last["rd"].plan, sh.PLAN_BLOCKED_OPERATOR_NEEDED, "collector: R244 held -> BLOCKED_OPERATOR_NEEDED")
    # the shadow keeps no authority over the Live Match: both write fences are independent state
    e.ok("failback_shadow_fence_seq" in h.sim.g and "fallback_profile_live_fence_seq" in h.sim.g, "collector: own and Live Match fences are distinct globals")
    e.clean(h)
    return e.fails


def tc_inputs_text(fw=None):
    """Inputs / Verdict / State exactly equal the oracle over a steady run, and the Verdict is the readiness (MODE_IF_LOST) plan."""
    e = Exp()
    h = mk(fw)
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 400_000)
    prime(h)
    run_polled(h, 400_000)
    e.eq(h.verdict(), "WOULD_ALREADY_MATCH", "inputs: stable supervision: the Verdict is the readiness plan (never NO_ACTION)")
    e.eq(h.inputs()["pl"], "40", "inputs: ... and Inputs pl carries the same readiness plan (WOULD_ALREADY_MATCH)")
    e.eq((h.inputs()["alt"], h.inputs()["pa"]), ("40", "40"), "inputs: alt / pa (FINAL 8.5 re-runs) are published, equal to pl here")
    e.eq(h.inputs()["sup"], "O", "inputs: sup=O")
    h.set_client(False)
    run_polled(h, 400_000 + LOST_MS + 3_000)
    e.eq((h.verdict(), h.inputs()["sup"]), ("WOULD_ALREADY_MATCH", "L"), "inputs: LOST: the Verdict is the plan if lost (continuation)")
    e.clean(h)
    return e.fails


# ===========================================================================
# REGRESSION (remediation H1): the Verdict contract of FINAL 8.5, S3 9.2 and S5 2.3. Outside an episode the Verdict answers "what
# would happen if HA were lost NOW" - the readiness plan - also while supervision is healthy and stable. The supervision rows
# NO_ACTION / WOULD_REFUSE_STARTS are never published on it (S5 2.3: they are visible as SHADOW_IDLE / SHADOW_WATCH on the State).
# ===========================================================================
READINESS_CASES = (  # label, setup(h), live words, the non-trivial readiness plan the Verdict must carry
    ("an FP lease is active", _fp_active, None, sh.PLAN_WOULD_PREEMPT_FREE_POWER),
    ("a live power word drifted from the profile", lambda h: None, {256: 7000}, sh.PLAN_WOULD_APPLY_PROFILE),
    ("the Dump marker was absent at boot and the domain is unused (R3)", lambda h: h.set_g(dump_marker_boot_load=1), None,
     sh.PLAN_BLOCKED_DURABLE_UNKNOWN),
    ("no profile is captured", lambda h: h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_NOT_CAPTURED), None,
     sh.PLAN_BLOCKED_PROFILE_UNAVAILABLE),
)


def tc_verdict_readiness(fw=None):
    e = Exp()
    for label, setup, changes, want in READINESS_CASES:
        for cadence, state_want in ((30_000, "SHADOW_IDLE"), (60_000, "SHADOW_WATCH")):  # healthy stable / supervised, never stable
            h = mk(fw)
            h.set_client(True)
            h.schedule_beats_every(10_000, cadence, 400_000)
            setup(h)
            prime(h, _words_with(changes) if changes else None)
            run_polled(h, 400_000)
            tag = f"T-VR {label}, {'stable' if cadence == 30_000 else 'not stable'} supervision"
            e.eq((h.g("supervision_state"), h.g("failback_shadow_phase"), h.text(STATE)), (1, 0, state_want),
                 f"{tag}: setup SUPERVISED, no episode, {state_want}")
            e.eq(h.oracle.last["rd"].plan, want, f"{tag}: setup readiness plan")
            e.eq(h.verdict(), sh.plan_name(want), f"{tag}: the Verdict is the readiness plan")
            e.ok(h.verdict() not in ("NO_ACTION", "WOULD_REFUSE_STARTS"), f"{tag}: the Verdict is never a supervision row")
            e.eq(h.inputs()["pl"], str(want), f"{tag}: Inputs pl equals the Verdict")
            e.clean(h)
    return e.fails


# ===========================================================================
# Z9 (authority) and the static constant checks
# ===========================================================================
def z9_global(hs) -> list:
    out = []
    inv = sum(h.fbc_invocations for h in hs)
    for h in hs:
        out += h.violations[:2]
        s = h.sim
        if s.nvs or s.nvs_commits or s.nvs_loads or s.modbus_log or s.executed or s.events:
            out.append("a sim recorded NVS / Modbus / script / event traffic")
        if s.nvs_direct.ops or s.nvs_direct.sets:
            out.append("a sim recorded direct-NVS operations (FB-C2 must perform zero NVS reads)")
    if inv < 20_000:
        out.append(f"too few audited FB-C invocations ({inv})")
    return out


def static_assert_check(text: str) -> list:
    """Lambda 0's static_asserts hold for the substitutions, and the cache max age equals the shared live-cache constant."""
    fwx = chain.load_fw(text)
    subs = fwx["_substitutions"]
    lam0, _ = X.hx.fbc_lambdas(fwx)
    body = re.sub(r"//[^\n]*", "", lam0)
    out = []
    asserts = re.findall(r"static_assert\((.*?),\s*\"(.*?)\"\)\s*;", body, flags=re.S)
    if not any("cache_max_age_ms" in a for a, _ in asserts):
        out.append("no cache-age static_assert")
    for expr, msg in asserts:
        if "ecco_fbcap::LIVE_CACHE_MAX_AGE_MS" in expr:
            expr = expr.replace("ecco_fbcap::LIVE_CACHE_MAX_AGE_MS", str(cap.LIVE_CACHE_MAX_AGE_MS))
        e = re.sub(r"\$\{(\w+)\}", lambda m: subs[m.group(1)], expr)
        e = re.sub(r"(\d+)UL", r"\1", e).replace("&&", " and ").replace("||", " or ")
        try:
            if not bool(eval(e, {"__builtins__": {}}, {})):  # noqa: S307 - a substitution-only arithmetic expression
                out.append(f"static_assert fails: {msg}")
        except Exception as ex:  # noqa: BLE001
            out.append(f"cannot evaluate {expr!r}: {ex}")
    if int(subs["ecco_failback_shadow_cache_max_age_ms"]) != cap.LIVE_CACHE_MAX_AGE_MS:
        out.append("cache max age != the shared live-cache constant")
    return out


def tc_z9_probe(fw=None):
    """A representative run with every kind of activity: the audit passes (positive control; the mutants are the negative ones)."""
    e = Exp()
    h = mk(fw)
    last, r = 130_000, 500_000
    outage(h, last_beat=last, run_to=last + LOST_MS + 2_000)
    return_beats(h, r, r + 900_000)
    h.set_g(free_power_operation_in_progress=True)
    h.set_running("start_free_power_override")
    run_polled(h, r + 100_000)
    h.set_g(free_power_operation_in_progress=False)
    h.set_running("start_free_power_override", False)
    h.save_profile(X.make_profile(8))
    run_polled(h, r + 420_000)
    e.ok(h.fbc_invocations > 400, "Z9 probe: enough invocations")
    e.clean(h)
    return e.fails


# ===========================================================================
# Mutation / negative controls
# ===========================================================================
def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    n = text.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n} times, want {count}: {old[:80]!r}")
    return text.replace(old, new)


def sub1(old: str, new: str):
    return lambda t: mutate(t, old, new)


EVAL_START = "// 4b. FB-C2 evaluator"
EVAL_END = "// 5. Episode machine"


def sub_eval(old: str, new: str):
    """The same exact replacement, but only inside the FB-C tick's step 4b (the same collector lines also occur in the Live Match
    tick and elsewhere; the mutation must hit the shadow's own copy)."""
    def f(text: str) -> str:
        i = text.index(EVAL_START)
        j = text.index(EVAL_END, i)
        return text[:i] + mutate(text[i:j], old, new) + text[j:]
    return f


L_FENCE = "in.lm.cache.fence_seq = ecco_fbcap::seq_max(fs.seq, id(fallback_profile_live_fence_seq));"
M_LATCH_IF = "if (bseq != 0 && bseq != id(failback_shadow_live_seq)) {"

MUTANTS = [
    # id, description, mutation, detectors that must catch it
    ("MC-1", "drop the would_latched assignment at the close",
     sub1("if (ecco_failback_shadow::close_latches(id(failback_shadow_ep_fbf))) id(failback_shadow_would_latched) = true;", ""),
     ["T-C24"]),
    ("MC-2", "make the close outcome always P",
     sub1("id(failback_shadow_ep_fbf) = ecco_failback_shadow::close_outcome(id(failback_shadow_ep_kind), id(failback_shadow_ep_v0));",
          "id(failback_shadow_ep_fbf) = 2;"), ["T-C24"]),
    ("MC-3", "the tick evaluates in MODE_ACTUAL (supervision rows leak into the edge plan and the Verdict)",
     sub1("in.mode = ecco_failback_shadow::MODE_IF_LOST;", "in.mode = ecco_failback_shadow::MODE_ACTUAL;"),
     ["T-C06b2", "T-VR"]),
    ("MC-4", "ignore the Live Match fence (shadow's own fence only)", sub1(L_FENCE, "in.lm.cache.fence_seq = fs.seq;"), ["T-C21"]),
    ("MC-5", "ignore the shadow's own fence (Live Match fence only)",
     sub1(L_FENCE, "in.lm.cache.fence_seq = id(fallback_profile_live_fence_seq);"), ["T-C21"]),
    ("MC-6", "skip the latch (re-copy the live cache every tick)", sub1(M_LATCH_IF, "if (bseq != 0) {"), ["T-C21"]),
    ("MC-7", "drop ph_prev_open from sup.episode_open", sub1("in.sup.episode_open = ph_prev_open;", "in.sup.episode_open = false;"),
     ["T-C27", "T-C20q"]),
    ("MC-8", "drop the bound episode identity (ep.bound false)", sub1("in.ep.bound = ph_prev_open;", "in.ep.bound = false;"), ["T-C27"]),
    ("MC-9", "absence_witness = true", sub1("in.absence_witness = false;      // reserved for FB-D", "in.absence_witness = true;"),
     ["T-C28", "T-C20q"]),
    ("MC-10", "a CLEAR basis that is always M (boot load read as OK)",
     sub_eval("gi.fp.free_power_marker_boot_load = id(free_power_marker_boot_load);", "gi.fp.free_power_marker_boot_load = 0;"),
     ["T-C28", "T-C20q"]),
    ("MC-11", "the CLEAR basis stays A after runtime activity",
     sub1("in.fp.used_since_boot = id(failback_shadow_seen_active_fp);", "in.fp.used_since_boot = false;"), ["T-C28", "T-C20q"]),
    ("MC-12", "accept a stale cache (age never measured)",
     sub1("in.lm.cache.block_b_ok_ms = id(cfg_block_b_ok_ms);", "in.lm.cache.block_b_ok_ms = now;"), ["T-C21"]),
    ("MC-13", "the cache max-age constant widened past the window (180000 -> 400000)",
     sub1('ecco_failback_shadow_cache_max_age_ms: "180000"', 'ecco_failback_shadow_cache_max_age_ms: "400000"'), ["static"]),
    ("MC-14", "Verdict ignores would_latched",
     sub1("const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;",
          "const uint8_t verdict = rd.plan;"), ["T-C24"]),
    ("MC-15", "P_WOULD_REFUSE ignores would_latched",
     sub1("ph == 1 || ph == 2 || id(failback_shadow_would_latched);", "ph == 1 || ph == 2;"), ["T-C24"]),
    ("MC-16", "an episode kind that is always N",
     sub1("id(failback_shadow_ep_kind) = ecco_failback_shadow::kind_for_edge(latched_at_edge);", "id(failback_shadow_ep_kind) = 1;"),
     ["T-C24"]),
    ("MC-17", "R244 obligations not collected (snapshot flag read as false)",
     sub_eval("gi.r244.reg244_snapshot_valid = id(reg244_snapshot_valid);", "gi.r244.reg244_snapshot_valid = false;"), ["T-C20q"]),
    ("MC-18", "sup.p_stable from the raw PR-A flag (no age re-check)", sub1("in.sup.p_stable = stable;", "in.sup.p_stable = id(supervision_stable);"),
     ["T-C20q", "T-C23"]),
    ("MC-19", "the bound profile generation is frozen as 0",
     sub1("id(failback_shadow_ep_pgen) = pgen_now;", "id(failback_shadow_ep_pgen) = 0;"), ["T-C27", "T-C20q"]),
    ("MC-20", "an INVALIDATE counted outside an episode",
     sub1("(eff_cls == ecco_fbdurable::EPC_INVALIDATED && ph_prev_open)", "(eff_cls == ecco_fbdurable::EPC_INVALIDATED)"), ["T-C27"]),
    ("MC-21", "soak: the pre-fence time is accounted as stale",
     sub1("} else if (rd.ca == ecco_fbcap::CQ_PRE_FENCE) {", "} else if (rd.ca == ecco_fbcap::CQ_STALE) {"), ["soak"]),
    ("MC-22", "vch counts the opening tick",
     sub1("if (ph_prev_open && (ph == 1 || ph == 2) && id(failback_shadow_last_verdict) != 255 &&",
          "if ((ph == 1 || ph == 2) && id(failback_shadow_last_verdict) != 255 &&"), ["vch"]),
    ("MC-23", "Verdict published without the 10 s rate gate",
     sub1("(uint32_t) (now - id(failback_shadow_last_pub_verdict_ms)) >= ${ecco_failback_shadow_publish_min_ms}UL)) {", "true)) {"),
     ["T-C16"]),
    ("MC-24", "Z9: the tick reads an entity outside the allow-list",
     sub1("const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;",
          "const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;\n"
          "          const bool zz_probe = id(ecco_tou1_raw_flags).has_state();"), ["Z9"]),
    ("MC-25", "Z9: the tick writes a non-shadow global",
     sub1("const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;",
          "const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;\n"
          "          id(manual_write_attempts) = id(manual_write_attempts);\n          id(dump_start_attempts) = 7;"), ["Z9"]),
    ("MC-26", "Z9: the tick executes a script",
     sub1("const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;",
          "const bool ph_prev_open = id(failback_shadow_phase) == 1 || id(failback_shadow_phase) == 2;\n"
          "          if (first) id(dump_lockout_containment).execute();"), ["Z9"]),
    ("MC-27", "frozen kind-L plan keeps the readiness fields",
     sub1("id(failback_shadow_ep_f0) = latched_at_edge ? (uint8_t) 255 : rd.fba_result;", "id(failback_shadow_ep_f0) = rd.fba_result;"),
     ["T-C24"]),
    ("MC-28", "sticky activity evidence never recorded (basis never becomes R)",
     sub1("if (busy_fp) id(failback_shadow_seen_active_fp) = true;", ""), ["T-C28"]),
    ("MC-29", "the pre-remediation Verdict: the supervision-aware MODE_ACTUAL plan (NO_ACTION / WOULD_REFUSE_STARTS outside an episode)",
     sub1("const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;",
          "in.mode = ecco_failback_shadow::MODE_ACTUAL;\n"
          "          const ecco_failback_shadow::ShadowPlan ac = ecco_failback_shadow::evaluate(in);\n"
          "          in.mode = ecco_failback_shadow::MODE_IF_LOST;\n"
          "          const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : ac.plan;"),
     ["T-VR"]),
    ("MC-30", "soak xh counts hazard time with no open lease obligation (the pre-remediation accounting)",
     sub1("if (rd.hazard_obligation) {", "if (true) {"), ["xh"]),
    ("MC-31", "soak xh counts hazard time only WITHOUT an obligation (inverted gate)",
     sub1("if (rd.hazard_obligation) {", "if (!rd.hazard_obligation) {"), ["xh"]),
]


def d_t_c24(fw):
    return tc24(fw) + tc25(fw)


DETECTORS = {
    "T-C24": d_t_c24,
    "T-C06b2": tc_edge_same_tick,
    "T-C21": tc21,
    "T-C27": tc27,
    "T-C28": tc28,
    "T-C23": tc_e_age_recheck,
    "T-C16": tc_e_publish,
    "Z9": tc_z9_probe,
    "soak": tc_soak,
    "xh": tc_xh,
    "T-VR": tc_verdict_readiness,
    "vch": tc_vch,
    "T-C20q": lambda fw: enumeration(fw, quick=True, stats=Stats())[0],
}


def run_detector(name: str, fwd: dict, text: str):
    saved = _SINK[0]
    _SINK[0] = []
    try:
        if name == "static":
            return "ok", static_assert_check(text)
        return "ok", list(DETECTORS[name](fwd))
    except Exception as ex:  # noqa: BLE001 - any failure of the mutant's run is a detection
        return "ok", [f"{type(ex).__name__}: {str(ex)[:160]}"]
    finally:
        _SINK[0] = saved


# ===========================================================================
# main
# ===========================================================================
def run_scenarios(title, fns):
    for name, fn in fns:
        t = time.time()
        fails = fn(FW)
        check(f"{name}", not fails, "; ".join(fails[:4]))
        sys.stdout.flush()


def main() -> int:
    print("[0] The live firmware carries the FB-C2 evaluator step and the audit's positive controls")
    lam0, lam1 = X.hx.fbc_lambdas(FW)
    check("the FB-C tick calls the pure evaluator exactly ONCE, in MODE_IF_LOST (S3 11.4; the readiness plan is the Verdict)",
          lam1.count("ecco_failback_shadow::evaluate(in)") == 1 and "MODE_IF_LOST;" in lam1 and "MODE_ACTUAL" not in lam1)
    check("lambda 0 static_asserts hold, and the cache max age equals the shared live-cache constant (180000 ms)",
          not static_assert_check(FW_TEXT), str(static_assert_check(FW_TEXT)))
    check("the owner-script allow-list used by the audit exists in the firmware",
          all(s in FW.get("script", [{}]) or any(sc.get("id") == s for sc in FW["script"]) for s in X.OWNER_SCRIPTS))

    print("")
    print("[T-C20/21/26/29] Enumeration: supervision x profile x cache x domains, each case carried through a whole episode")
    t = time.time()
    fails, stats = enumeration()
    print(f"    {stats.cases} cases, {stats.ticks} audited ticks in {time.time() - t:.0f}s")
    check("T-C20: Verdict / Inputs / State / frozen edge plan / would_latched equal the independent oracle on every tick of every case",
          not fails, "; ".join(fails[:3]))
    check("T-C20 coverage: every supervision state (U / O / S / L) was exercised", stats.sups >= {"U", "O", "S", "L"}, str(stats.sups))
    check("T-C20 coverage: every effective profile class 0..8 (incl. PROFILE_STALE / LOST / SAVE_UNCONFIRMED / UNREADABLE / CORRUPT / "
          "NOT_CAPTURED / INVALIDATED / VALID)", stats.effs >= set(range(9)), str(sorted(stats.effs)))
    check("T-C21 coverage: every cache-quality letter B / I / O / S / P / M / F was exercised",
          stats.ca_letters >= set("BIOSPMF"), str(sorted(stats.ca_letters)))
    reached = stats.plans_rd | stats.verdicts
    want = {10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 24, 26, 27, 31, 40, 41, 50}
    check("T-C20 coverage: the plan codes 10-15 / 20-24 / 26 / 27 / 31 / 40 / 41 / 50 all appear as a Verdict or a readiness plan",
          want <= reached, f"missing {sorted(want - reached)}; rd={sorted(stats.plans_rd)} verdicts={sorted(stats.verdicts)}")
    check("T-C20 Verdict contract (FINAL 8.5, S3 9.2, S5 2.3): over every enumerated tick the Verdict is the readiness plan or 50 - "
          "never NO_ACTION (1) or WOULD_REFUSE_STARTS (2), although the enumeration drives every supervision state",
          not ({1, 2} & stats.verdicts) and stats.verdicts - {50} <= stats.plans_rd and {1, 2} <= stats.plans_ac,
          f"verdicts={sorted(stats.verdicts)} rd={sorted(stats.plans_rd)} actual(reference)={sorted(stats.plans_ac)}")
    check("T-C20: 25 (site ceiling) and 30 (no profile) are unreachable through the tick with the shipped constants (ceiling == V1 power "
          "maximum; no 'present with generation 0' witness: absence is never proof)", not ({25, 30} & reached), str(sorted({25, 30} & reached)))
    check("T-C20 coverage: domain classes C-M / C-A / C-R (CLEAR bases) and O* / U* kinds appeared",
          {"CM", "CA", "CR"} <= stats.dom_letters and any(x.startswith("O") for x in stats.dom_letters)
          and any(x.startswith("U") for x in stats.dom_letters), str(sorted(stats.dom_letters)[:20]))
    check("T-C24/25 coverage: both episode kinds N and L, and both close outcomes A (latched) and P (self-clear), occurred",
          {sh.EPK_N, sh.EPK_L} <= stats.kinds and stats.fbf >= {sh.FBF_A, sh.FBF_P}, f"kinds={stats.kinds} fbf={stats.fbf}")
    check("T-C20: the latched-verdict path was exercised (WOULD_REMAIN_LATCHED ticks)", stats.latched_verdict_ticks > 50, str(stats.latched_verdict_ticks))
    check("T-C29: with ca != F the codes 26 / 27 / 40 / 41 are never emitted (readiness or verdict), over every enumerated tick",
          not stats.bad_ca_plans and stats.ticks > 5000, f"{stats.bad_ca_plans[:3]} ticks={stats.ticks}")
    check("T-C29 (positive control): with ca = F those codes ARE emitted", {26, 27, 40, 41} <= stats.plans_rd, str(sorted(stats.plans_rd)))
    check("T-C17: every enumerated Inputs text is <= 200 characters", stats.max_inputs <= 200, str(stats.max_inputs))
    check("T-C21 overlay: e1 / cx reach 'O' only with ca = F, and 'N' elsewhere (the shared fence precedes the overlay)",
          stats.e1_states <= {sh.CMP_N, sh.CMP_M, sh.CMP_D, sh.CMP_O} and sh.CMP_O in stats.e1_states, str(stats.e1_states))

    print("")
    print("[T-C21/26] cache states, fences, latch, overlay; projected frames")
    run_scenarios("c21", [("T-C21 cache states I/O/S/P/M/F exact; locks; own + Live Match fence; live latch; overlay", tc21),
                          ("T-C26 blk subset of the four E1 frames; 230/245/247 differences change only `in`", tc26)])

    print("")
    print("[T-C24/25/27/28] would-latched model, profile change, CLEAR basis")
    run_scenarios("c24", [("T-C24 BLOCKED_NO_PROFILE-like edge: A close, latch, State, Verdict, wr, k=L, A again", tc24),
                          ("T-C25 WOULD_ALREADY_MATCH edge: P close, no latch, next LOST is k=N", tc25),
                          ("T-C24b the latch is cleared only by a reboot", tc24_reboot),
                          ("T-C06b' frozen edge plan = readiness (rd), not the verdict (ac)", tc_edge_same_tick),
                          ("T-C27 SAVE / class change / INVALIDATE and the wr 4th field", tc27),
                          ("T-C28 CLEAR basis M / A / R and R3", tc28)])

    f = tc27_overlay_clear(FW)
    known_defect("T-C27e an overlay (SAVE_UNCONFIRMED / read anomaly) that clears with the SAME generation is not counted as a profile change in wr",
                 not f, "; ".join(f[:2]))

    print("")
    print("[E] The C1 episode machine on the new lambda; publication; strings; soak telemetry")
    run_scenarios("e", [("T-C02/03/06/06b episode open / HA_BACK / close", tc_e_open_close),
                        ("T-C07/08/12 flapping, skipped beat, reboot loop", tc_e_flap),
                        ("T-C23 P_STABLE age re-check", tc_e_age_recheck),
                        ("T-C04 tick order and random phases give the same episode records", tc_e_order),
                        ("T-C16 publish de-duplication, rate and flush", tc_e_publish),
                        ("vch counting", tc_vch),
                        ("T-C18 not ready (generation 0): zero changes", tc_not_ready),
                        ("[H] the audit detects every kind of side effect; the oracle detects tampering", tc_harness_selftest),
                        ("T-C13 wr START evidence on the live lambda", tc_wr),
                        ("collector facts (E0 / E1 inputs, orphan timers, lease expiry, P_STABLE)", tc_collector),
                        ("Inputs / Verdict steady state and LOST continuation", tc_inputs_text),
                        ("T-VR REGRESSION: healthy / unstable supervision + a non-trivial readiness plan -> the Verdict is that plan, "
                         "never NO_ACTION / WOULD_REFUSE_STARTS", tc_verdict_readiness),
                        ("T-C17 worst-case strings", tc_strings),
                        ("soak telemetry: wr p, xh, cs, saturation, the fence cost during an episode", tc_soak),
                        ("soak xh: hazard time only while an export-relevant lease obligation is open (no obligation / UNKNOWN / "
                         "YES / NO)", tc_xh),
                        ("Z9 probe run", tc_z9_probe)])

    print("")
    print("[Z11] every string the suite made FB-C publish: <= 200 chars, no Energy Actions card regex match")
    rx = card_regexes()
    check("the card's regex literals were imported from the TypeScript source (>= 19 distinct, incl. ^FAILED and ^BLOCKED)",
          len(rx) >= 19 and any(p == "^FAILED" for p, _, _ in rx) and any(p == "^BLOCKED" for p, _, _ in rx), str(len(rx)))
    strs = set(STATS.inputs_texts)
    for h in ALL_H:
        for ent in X.FBC_TEXT_IDS:
            strs.update(h.published(ent))
    strs |= {sh.plan_name(c) for c in range(256)} | {"SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WOULD_AWAIT_ACK", "SHADOW_WATCH", "SHADOW_IDLE"}
    strs |= set(worst_case_strings()[0])
    check(f"every string FB-C published ({len(strs)} distinct) is <= 200 chars (worst case {max(map(len, strs))})", all(len(s) <= 200 for s in strs))
    hits = [(s[:60], p, o) for s in strs for p, fl, o in rx if re.search(p, s, fl)]
    names = {sh.plan_name(c) for c in range(256)}
    check("no FB-C string (State, Inputs, Episode, Soak, worst cases) matches any card regex, case-insensitively",
          not [x for x in hits if x[0] not in names], str([x for x in hits if x[0] not in names][:3]))
    verdict_hits = [x for x in hits if x[0] in names]
    check("Verdict plan names match only the card's schedule.ts `^BLOCKED` (the S4 8.1 BLOCKED_* names); S3 Z11 allows exactly that "
          "with the call-site proof, which test_failback_shadow_evaluator.py [4] now makes (the regex is applied only to the two "
          "schedule result helpers, never to a Failback Shadow entity or the HA shadow decoder)",
          bool(verdict_hits) and all(p == "^BLOCKED" and o == "schedule.ts" for _s, p, o in verdict_hits),
          str(sorted({(x[1], x[2]) for x in verdict_hits})))

    print("")
    print("[Z9] Authority across EVERY scenario above")
    z = z9_global(ALL_H)
    nt = sum(h.fbc_invocations for h in ALL_H)
    check(f"{nt} audited FB-C invocations over {len(ALL_H)} harnesses: only failback_shadow_* globals changed, zero Modbus, zero NVS "
          f"(tag store and direct store), zero durable events, zero scripts, only the five text sensors published, only allow-listed "
          f"entities read; zero NVS reads", not z, str(z[:4]))

    print("")
    print("[M] Mutation / negative controls (each broken in-memory copy of the lambda must be caught)")
    kills = []
    for mid, desc, fnm, dets in MUTANTS:
        try:
            text = fnm(FW_TEXT)
        except AssertionError as ex:
            check(f"{mid} {desc}: mutation anchor present", False, str(ex))
            continue
        t = time.time()
        killed_by = []
        try:
            fwd = chain.load_fw(text)
        except Exception as ex:  # noqa: BLE001
            check(f"{mid} {desc}: the mutant loads", False, str(ex))
            continue
        for d in dets:
            _, f = run_detector(d, fwd, text)
            if f:
                killed_by.append((d, f[0][:90]))
                break  # one kill proves the detector can see the mutation
        kills.append((mid, desc, [k[0] for k in killed_by], time.time() - t, killed_by[0][1] if killed_by else ""))
        check(f"{mid} {desc}: caught by {dets}", bool(killed_by), "NOT DETECTED")
        sys.stdout.flush()
    print("")
    print("  mutation kill table (mutant -> detectors that fired):")
    for mid, desc, by, dt, why in kills:
        print(f"    {mid:6s} {'KILLED ' + ','.join(by) if by else 'SURVIVED':22s} {desc}   [{dt:.0f}s]")
        if why:
            print(f"           first detection: {why}")
    print(f"  killed {sum(1 for k in kills if k[2])}/{len(MUTANTS)}")

    print("")
    n_fail = len(FAILURES)
    if KNOWN_DEFECTS:
        print(f"KNOWN DEFECTS in the lambda ({len(KNOWN_DEFECTS)}, reported not edited; --strict makes them failures):")
        for k in KNOWN_DEFECTS:
            print("  *", k)
    n_checks = len(CHECKS)
    print(f"{n_checks - n_fail} of {n_checks} checks passed; {ASSERTS[0]} scenario assertions and {STATS.ticks + sum(h.fbc_invocations for h in ALL_H)} "
          f"audited FB-C ticks compared with the oracle; {len(MUTANTS)} mutants")
    print(f"{'PASS' if not n_fail else 'FAIL'}: {n_fail} failure(s); elapsed {time.time() - T0:.0f}s")
    if FAILURES:
        for f in FAILURES:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
