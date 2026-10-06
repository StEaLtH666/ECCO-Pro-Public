"""FB-C2 (Failback Shadow EVALUATOR) test harness.

Runs the REAL firmware lambdas - PR-A's ha_supervision_heartbeat action, PR-A's 1 s supervision tick, PR-A's on_boot
initialisation and the FB-C interval's 1 s tick lambda INCLUDING its step 4b evaluator block - on the strict FB-B simulator
(registry/tests/_fbb_harness.py FbbSim: C++-exact ecco_fbcap:: / ecco_fallback:: / ecco_fbdurable:: / ecco_failback_shadow::
namespaces, std::array globals, is_running(), record globals) instead of the plain _dump_sim.Sim the FB-C1 harness used.

It COMPOSES registry/tests/_fbc_harness.Harness (two independently scheduled 1 s intervals with random phase / drift, explicit
tie order, heartbeats, api client model, NTP model, millis_64) and swaps the simulator class and the per-invocation audit:

  * TrackingFbbSim             FbbSim that records every entity accessed (like _fbc_harness.TrackingSim).
  * Z9 audit of EVERY FB-C tick: only `failback_shadow_*` globals may change (scalars, std::array and record globals are
                               compared by value, so an in-place array write is caught too); zero Modbus; zero NVS (neither the
                               tag-keyed ecco_durable store nor the direct FB store: no read, no write, no stats probe); zero
                               durable events; zero executed scripts; no entity state changed other than the five FB-C text
                               sensors; ONLY the five FB-C text sensors published; only an allow-listed set of entities read
                               (below). A mutant that touches anything else FAILS the audit.
  * world helpers              the FB-C2 inputs: the fallback profile mirror (boot_loaded, bytes / load / class / why /
                               save_unconfirmed / read_anomaly), the three marker boot loads, the Free Power / Dump / R244 RAM
                               flags, set_running(script_id, bool) for is_running(), the configuration-poll cache (31 words,
                               seq / ok_ms / dispatch_seq / response_dispatch_seq, valid / filled / online / polling), the B10
                               fence scalars and the write-attempt counters, the bus locks, direct supervision injection.
  * ShadowOracle               an INDEPENDENT Python collector, written from S3 11.4 / 11.5 (not copied from the lambda): it keeps
                               its own sticky activity evidence, owner-orphan timers, shared 1 s write fence (the shared pure
                               ecco_fbcap model), live latch, would-latched flag and frozen episode edge plan, builds a
                               registry/failback_shadow.ShadowInputs from the WORLD STATE every tick and predicts the Verdict,
                               Inputs, frozen ep_* globals and State. Every FB-C tick of a harness built with oracle=True is
                               compared (publication de-duplication included).

The harness proves nothing about ESPHome timing or the compiled binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(ROOT / "tools"))

import _fbb_harness as H  # noqa: E402
import _fbc_harness as hx  # noqa: E402
import failback_shadow as sh  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FBC_TEXT_IDS = hx.FBC_TEXT_IDS
STATE_T, EPISODE_T, SOAK_T, VERDICT_T, INPUTS_T = FBC_TEXT_IDS

# Scripts whose is_running() the evaluator reads (S3 11.3 / S4 2.9). Written out independently of the lambda.
OWNER_SCRIPTS = (
    "start_free_power_override", "restore_free_power_snapshot", "restore_free_power_snapshot_dispatch",
    "free_power_recovery_review", "free_power_recovery_review_dispatch", "free_power_recovery_force_restore",
    "free_power_recovery_force_restore_dispatch", "free_power_recovery_accept_current_state",
    "free_power_recovery_accept_current_state_dispatch", "start_dump_to_grid_override", "restore_dump_to_grid_snapshot",
    "dump_controller_tick", "dump_lockout_containment", "apply_reg244_settings", "restore_reg244_snapshot",
    "apply_manual_slot1", "apply_manual_slot2", "apply_manual_slot3", "apply_manual_slot4", "apply_manual_slot5",
    "apply_manual_slot6", "fallback_profile_capture_dispatch",
)
# Entities the FB-C2 tick may touch: its five text sensors, the API client sensor and the clock (FB-C1), the two configuration
# entities the cache-quality term reads (S3 11.5: configuration_online / configuration_polling .state), and the owner scripts
# (is_running() only reads).
FBC2_ACCESSIBLE = frozenset(FBC_TEXT_IDS) | {"api_client_connected_sensor", "ntp_time", "configuration_online",
                                             "configuration_polling"} | frozenset(OWNER_SCRIPTS)

# REGS order -> the cached global each word is read from (S3 11.5 RAW_CACHE_EXT): written from the register numbers.
RAW_CACHE_EXT_REGS = (230, 243, 245, 247, 248)


def word_global(reg: int) -> str:
    return f"fbc_raw_{reg}" if reg in RAW_CACHE_EXT_REGS else f"manual_cfg_reg{reg}_raw"


WORD_GLOBALS = tuple(word_global(r) for r in cap.REGS)
assert len(WORD_GLOBALS) == 31

# --- the golden profile (VALID, generation 7), written out here (not imported from a sibling test) -----------------------------
P244 = 2
P256 = [8000, 500, 4000, 3000, 2000, 1000]
P268 = [100, 20, 0, 50, 100, 30]
P274 = [1, 0, 1, 0, 0, 1]
P232, P243, P248 = 0x0011, 1, 1
P250 = [0, 530, 1000, 1600, 2100, 2330]
P230, P245, P247 = 185, 8000, 1


def make_profile(generation: int = 7, **over) -> dict:
    rec = fp.blank_profile(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=generation, captured_epoch=1790000000,
                           flags=0, reg244=P244, reg256_261=list(P256), reg268_273=list(P268), reg274_279=list(P274),
                           reg232=P232, reg243=P243, reg248=P248, reg250_255=list(P250), reg230=P230, reg245=P245,
                           reg247=P247)
    rec.update(over)
    return fp.seal_profile(rec)


GOLD = make_profile(7)
GW = list(cap.words_of(GOLD))


def profile_bytes(rec: dict) -> bytes:
    return fp.pack_profile(rec)


def blank_bytes() -> bytes:
    return bytes(fp.PROFILE_SIZE)


# ---------------------------------------------------------------------------
# Simulator with entity-access tracking
# ---------------------------------------------------------------------------
class TrackingFbbSim(H.FbbSim):
    accessed: set = set()
    track = False

    def __init__(self, firmware: dict, **kw):
        super().__init__(firmware, **kw)
        self.accessed = set()
        self.track = False

    def ent(self, name):
        if self.track:
            self.accessed.add(name)
        return super().ent(name)


def _frz(v):
    """A by-value freeze of one global, for the Z9 comparison (std::array / record globals compare by content)."""
    if isinstance(v, H.FbArray):
        return tuple(v)
    if isinstance(v, H.FbRecord):
        return bytes(v.to_bytes())
    if isinstance(v, list):
        return tuple(v)
    return str(v) if isinstance(v, str) else v


def non_fb_globals(sim) -> dict:
    return {k: _frz(v) for k, v in sim.g.items() if not k.startswith("failback_shadow_")}


def initial_value_of(g: dict):
    """The firmware initial_value of a global, as the simulator holds it (bool / int / float)."""
    init = g.get("initial_value")
    t = g["type"]
    if t == "bool":
        return str(init).strip("'\"").lower() == "true"
    if init is None or init == "":
        return 0
    if t in ("float", "double"):
        return float(str(init).strip("'\""))
    return int(str(init).strip("'\""), 0)


# ---------------------------------------------------------------------------
# The oracle: an independent collector (S3 11.4 / 11.5), written from the spec
# ---------------------------------------------------------------------------
class ShadowOracle:
    """Predicts, from the WORLD STATE alone, what the FB-C2 tick must compute and publish.

    Called once per FB-C tick by Harness.fbc_tick (after the lambda ran; the tick changes no non-FB global, so the world seen
    after the tick is the world the tick saw). It keeps only state a reader of the spec would keep: the sticky activity evidence of
    the three lease domains (S3 11.5 CLEAR basis), the four owner-orphan timers (S4 2.9), the shared 1 s write fence (the pure
    ecco_fbcap::fence_tick the Live Match uses), the live latch of the 31 cached words (S3 11.5 / FB-B3), the would-latched flag and
    the frozen episode edge plan. The episode PHASE itself is observed (before / after the tick) - the phase machine is covered by
    the scenario assertions, not re-implemented here.
    """

    def __init__(self, h):
        self.h = h
        self.errors: list[str] = []
        self.ticks = 0
        self.reset()

    def reset(self):
        self.seen_active = {"fp": False, "dump": False, "r244": False}
        self.orph = {"fp": 0, "dump": 0, "r244": 0, "mwip": 0}
        self.fence = cap.FenceState()
        self.live = [0] * 31
        self.live_seq = 0
        self.live_dispatch = 0
        self.latched = False
        self.ep = None  # frozen episode record while one is bound
        self.first = True
        self.last_pub = {VERDICT_T: 0, INPUTS_T: 0}
        self.last = None  # the last tick's expectation (dict)
        self.prev_pgen = 0
        self.prev_pclass = None
        self.wr_prof = 0

    # -- helpers ---------------------------------------------------------------------------------------------------------
    @property
    def sim(self):
        return self.h.sim

    def g(self, name):
        return self.sim.g[name]

    def sub(self, key) -> int:
        return int(self.h.fw["_substitutions"][key])

    def running(self, sid) -> bool:
        return sid in self.sim.running

    def inject_episode(self, cls: int, gen: int, binding: int):
        """Synthetic setups: bind the oracle's episode identity (the caller sets the same ep_* globals)."""
        self.ep = {"cls": cls, "gen": gen, "binding": binding}

    # -- the collector -------------------------------------------------------------------------------------------------------
    def build(self, now: int, phase_before: int, st: int, stable: bool) -> "sh.ShadowInputs":
        g, S = self.g, self.sub
        open_before = phase_before in (1, 2)
        # sticky activity evidence (busy = operation flag OR snapshot flag)
        for key, flags in (("fp", ("free_power_operation_in_progress", "free_power_snapshot_valid")),
                           ("dump", ("dump_operation_in_progress", "dump_snapshot_valid")),
                           ("r244", ("reg244_apply_in_progress", "reg244_snapshot_valid"))):
            if any(g(f) for f in flags):
                self.seen_active[key] = True
        r = self.running
        run_fp_start = r("start_free_power_override")
        run_fp_restore = r("restore_free_power_snapshot") or r("restore_free_power_snapshot_dispatch")
        run_fp_operator = any(r(s) for s in ("free_power_recovery_review", "free_power_recovery_review_dispatch",
                                             "free_power_recovery_force_restore", "free_power_recovery_force_restore_dispatch",
                                             "free_power_recovery_accept_current_state",
                                             "free_power_recovery_accept_current_state_dispatch"))
        run_dump_start = r("start_dump_to_grid_override")
        run_dump_restore = r("restore_dump_to_grid_snapshot")
        run_dump_other = r("dump_controller_tick") or r("dump_lockout_containment")
        run_r244_apply, run_r244_restore = r("apply_reg244_settings"), r("restore_reg244_snapshot")
        run_mtou = any(r(f"apply_manual_slot{k}") for k in range(1, 7))
        run_capture = r("fallback_profile_capture_dispatch")
        any_owner = any((run_fp_start, run_fp_restore, run_fp_operator, run_dump_start, run_dump_restore, run_dump_other,
                         run_r244_apply, run_r244_restore, run_mtou, run_capture))

        def orphan(key, flag_set, owners):
            if flag_set and not owners:
                if self.orph[key] == 0:
                    self.orph[key] = now
            else:
                self.orph[key] = 0

        orphan("fp", bool(g("free_power_operation_in_progress") or g("free_power_recovery_force_in_progress")
                          or g("free_power_recovery_accept_in_progress")),
               run_fp_start or run_fp_restore or run_fp_operator)
        orphan("dump", bool(g("dump_operation_in_progress")), run_dump_start or run_dump_restore or run_dump_other)
        orphan("r244", bool(g("reg244_apply_in_progress")), run_r244_apply or run_r244_restore)
        orphan("mwip", bool(g("manual_write_in_progress")), any_owner)

        def age(since):
            return 0 if since == 0 else (now - since) & 0xFFFFFFFF

        sim = self.sim
        clock_valid = bool(sim.ntp_valid)
        epoch = int(sim.epoch) if clock_valid else 0
        grace = S("ecco_free_power_invalid_clock_grace_ms")

        def expired(end_epoch):
            return (epoch >= end_epoch) if (clock_valid and end_epoch != 0) else (now >= grace)

        gi = cap.GateInputs(boot_loaded=bool(g("fallback_profile_boot_loaded")), probe_latch=g("fallback_profile_probe_latch"))
        b = gi.bus
        b.manual_write_in_progress = bool(g("manual_write_in_progress"))
        b.correction_in_progress = bool(g("correction_in_progress"))
        b.verification_pending = bool(g("verification_pending"))
        b.verification_read_active = bool(g("verification_read_active"))
        b.free_power_operation_in_progress = bool(g("free_power_operation_in_progress"))
        b.free_power_recovery_force_in_progress = bool(g("free_power_recovery_force_in_progress"))
        b.free_power_recovery_accept_in_progress = bool(g("free_power_recovery_accept_in_progress"))
        b.reg244_apply_in_progress = bool(g("reg244_apply_in_progress"))
        b.dump_operation_in_progress = bool(g("dump_operation_in_progress"))
        b.fallback_profile_op_in_progress = bool(g("fallback_profile_op_in_progress"))
        b.fallback_profile_capture_dispatch_running = run_capture
        b.diag_write_lock_held = bool(g("diag_write_lock_held"))
        b.diag_write_lock_since_ms = g("diag_write_lock_since_ms")
        b.now_ms = now
        f = gi.fp
        f.free_power_marker_boot_load = g("free_power_marker_boot_load")
        f.free_power_recovery_metadata_corrupt = bool(g("free_power_recovery_metadata_corrupt"))
        f.free_power_snapshot_valid = bool(g("free_power_snapshot_valid"))
        f.free_power_marker_state = g("free_power_marker_state")
        f.free_power_operator_needed = bool(g("free_power_operator_needed"))
        f.free_power_active_persisted = bool(g("free_power_active_persisted"))
        f.free_power_restore_requested = bool(g("free_power_restore_requested"))
        f.expired = expired(g("free_power_end_epoch"))
        f.run_start, f.run_restore, f.run_operator = run_fp_start, run_fp_restore, run_fp_operator
        d = gi.dump
        d.dump_marker_boot_load = g("dump_marker_boot_load")
        d.dump_recovery_metadata_corrupt = bool(g("dump_recovery_metadata_corrupt"))
        d.dump_containment_state = g("dump_containment_state")
        d.dump_snapshot_valid = bool(g("dump_snapshot_valid"))
        d.dump_marker_state = g("dump_marker_state")
        d.dump_operator_needed = bool(g("dump_operator_needed"))
        d.dump_active_persisted = bool(g("dump_active_persisted"))
        d.dump_restore_requested = bool(g("dump_restore_requested"))
        d.expired = expired(g("dump_end_epoch"))
        d.run_start, d.run_restore = run_dump_start, run_dump_restore
        x = gi.r244
        x.reg244_marker_boot_load = g("reg244_marker_boot_load")
        x.reg244_recovery_metadata_corrupt = bool(g("reg244_recovery_metadata_corrupt"))
        x.reg244_snapshot_valid = bool(g("reg244_snapshot_valid"))
        x.reg244_marker_state = g("reg244_marker_state")
        x.run_apply, x.run_restore = run_r244_apply, run_r244_restore

        # the shared 1 s write fence, sampled every tick
        sample = cap.FenceSample(
            bus_hot=cap.bus_busy(b), lease_nonclear=cap.lease_domain_nonclear(gi) != cap.SLOT_NONE,
            writes_fp=cap.writes_fingerprint(g("manual_write_attempts"), g("reg244_apply_attempts"), g("reg244_restore_attempts"),
                                             g("free_power_start_attempts"), g("dump_start_attempts")),
            dispatch_seq=g("cfg_block_b_dispatch_seq"))
        self.fence = cap.fence_tick(self.fence, sample)

        # the live latch: the 31 words are copied on the first tick after a Block B success
        bseq = g("cfg_block_b_seq")
        if bseq != 0 and bseq != self.live_seq:
            self.live_seq = bseq
            self.live_dispatch = g("cfg_block_b_response_dispatch_seq")
            self.live = [int(g(n)) for n in WORD_GLOBALS]

        cls_raw = g("fallback_profile_class")
        save_unc = bool(g("fallback_profile_save_unconfirmed"))
        anomaly = g("fallback_profile_read_anomaly")
        eff = cap.live_effective_class(cls_raw, save_unc, anomaly)
        prof = fp.unpack_profile(bytes(g("fallback_profile_bytes")))
        meaningful = sh.meaningful_class(eff)
        pgen_now = prof["generation"] if meaningful else 0
        self._pgen_now, self._eff, self._prof = pgen_now, eff, prof

        in_ = sh.ShadowInputs()
        in_.sup = sh.SupIn(state=st, p_stable=stable, episode_open=open_before)
        lm = in_.lm
        lm.g = gi
        lm.mtou_running = run_mtou
        lm.cls, lm.write_outcome_unknown, lm.read_anomaly = cls_raw, save_unc, anomaly
        lm.p_load = g("fallback_profile_load")
        lm.p = prof
        in_.profile_why = g("fallback_profile_why")
        lm.cache = cap.LiveCache(
            cache_valid=bool(g("manual_config_raw_cache_valid")), online=bool(self.sim.ent("configuration_online").state),
            polling=bool(self.sim.ent("configuration_polling").state), filled=bool(g("fbc_raw_filled")), block_b_seq=bseq,
            block_b_ok_ms=g("cfg_block_b_ok_ms"), now_ms=now, response_dispatch_seq=self.live_dispatch,
            fence_seq=cap.seq_max(self.fence.seq, g("fallback_profile_live_fence_seq")))
        lm.edge_fence_seq = cap.seq_max(self.fence.edge_seq, g("fallback_profile_live_edge_seq"))
        lm.live = list(self.live)
        lm.dump_data_loaded = bool(g("dump_snapshot_data_loaded"))
        lm.dump_snapshot_reg244 = g("dump_snapshot_reg244")
        lm.dump_snapshot_reg256_261 = [g(f"dump_snapshot_reg{n}") for n in range(256, 262)]
        lm.ceiling_w = S("ecco_inverter_tou_power_ceiling_w")
        in_.not_captured_proven = False
        in_.absence_witness = False
        in_.fp_lease_ctx_unknown = g("free_power_lease_context_reg244") == -1

        def backoff(next_ms):
            return next_ms != 0 and ((now - next_ms) & 0xFFFFFFFF) >= 0x80000000

        in_.fp = sh.DomExtra(backoff=backoff(g("free_power_restore_next_attempt_ms")), orphan_ms=age(self.orph["fp"]),
                             used_since_boot=self.seen_active["fp"], retry_on_raw=bool(g("free_power_operator_needed")))
        in_.dump = sh.DomExtra(backoff=backoff(g("dump_restore_next_attempt_ms")), orphan_ms=age(self.orph["dump"]),
                               used_since_boot=self.seen_active["dump"], retry_on_raw=False,
                               force_bypass=bool(g("dump_force_restore_bypass")))
        in_.r244 = sh.DomExtra(orphan_ms=age(self.orph["r244"]), used_since_boot=self.seen_active["r244"])
        in_.r244x = sh.R244Extra(lav=bool(g("reg244_last_applied_valid")), la=g("reg244_last_applied_value"))
        in_.bus = sh.BusExtra(any_owner_running=any_owner, mwip_orphan_ms=age(self.orph["mwip"]),
                              cip_held_ms=((now - g("diag_correction_lock_since_ms")) & 0xFFFFFFFF)
                              if g("diag_correction_lock_held") else 0)
        in_.mtou_journal = 0
        if open_before and self.ep is not None:
            in_.ep = sh.EpProf(bound=True, cls=self.ep["cls"], gen=self.ep["gen"], binding=self.ep["binding"])
        else:
            in_.ep = sh.EpProf(bound=open_before)
        in_.fp_snap = sh.FpSnapshot(
            valid=bool(g("free_power_snapshot_valid")), r232=g("free_power_snapshot_reg232"),
            r256=[g(f"free_power_snapshot_reg{n}") for n in range(256, 262)],
            r268=[g(f"free_power_snapshot_reg{n}") for n in range(268, 274)],
            r274=[g(f"free_power_snapshot_reg{n}") for n in range(274, 280)])
        return in_

    def after_tick(self, now: int, pre: dict):
        """pre: what the harness saw BEFORE the lambda: phase, ep, relost, ready, states of the two published texts."""
        h = self.h
        g = self.g
        if g("supervision_generation") == 0:
            return  # the tick returned at E0
        first = not pre["ready"]
        phase_before, phase_after = pre["phase"], g("failback_shadow_phase")
        st = g("supervision_state")
        svc, lv = g("supervision_valid_count"), g("supervision_last_valid_ms")
        age = ((now - lv) & 0xFFFFFFFF) if svc > 0 else 0xFFFFFFFF
        stable = bool(st == 1 and g("supervision_stable") and svc > 0 and age <= self.sub("ecco_supervision_stable_max_gap_ms"))
        in_ = self.build(now, phase_before, st, stable)
        in_.mode = sh.MODE_IF_LOST
        rd = sh.evaluate(in_)
        # reference only: the supervision-aware MODE_ACTUAL plan. The spec never publishes it on the Verdict (FINAL 8.5, S3 9.2,
        # S5 2.3: outside an episode the Verdict is "what would happen if HA were lost now"; inside an episode both modes agree)
        in_.mode = sh.MODE_ACTUAL
        ac = sh.evaluate(in_)
        in_.mode = sh.MODE_IF_LOST
        latched_before = self.latched
        verdict = sh.PLAN_WOULD_REMAIN_LATCHED if latched_before else rd.plan
        want_verdict = sh.plan_name(verdict)
        want_inputs = str(sh.inputs_text(in_, rd))

        # episode edges, observed from the phase transition: the frozen edge plan
        opened = phase_before in (0, 3) and phase_after in (1, 2)
        if opened:
            if latched_before:
                self.ep = dict(kind=sh.EPK_L, v0=sh.PLAN_WOULD_REMAIN_LATCHED, vu=rd.plan, f0=0xFF, dm=0xFF, pre=0, blk=0,
                               d=0xFF)
            else:
                self.ep = dict(kind=sh.EPK_N, v0=rd.plan, vu=0xFF, f0=rd.fba_result, dm=rd.blocking_domain,
                               pre=(1 if rd.would_preempt_fp else 0) | (2 if rd.would_preempt_dump else 0),
                               blk=rd.projected_frames, d=rd.delta_count)
            self.ep.update(cls=self._eff, gen=self._pgen_now,
                           binding=self._prof["binding"] if sh.meaningful_class(self._eff) else 0)
            for key, gname in (("kind", "ep_kind"), ("v0", "ep_v0"), ("vu", "ep_vu"), ("f0", "ep_f0"), ("dm", "ep_dm0"),
                               ("pre", "ep_pre0"), ("blk", "ep_blk0"), ("d", "ep_d0"), ("cls", "ep_pclass"),
                               ("gen", "ep_pgen"), ("binding", "ep_pbind")):
                if g("failback_shadow_" + gname) != self.ep[key]:
                    self.errors.append(f"t={now}: edge freeze {gname}: got {g('failback_shadow_' + gname)}, want {self.ep[key]}")
        if phase_before == 2 and phase_after == 3 and self.ep is not None:
            fbf = sh.close_outcome(self.ep["kind"], self.ep["v0"])
            if g("failback_shadow_ep_fbf") != fbf:
                self.errors.append(f"t={now}: close outcome fbf {g('failback_shadow_ep_fbf')} want {fbf}")
            if sh.close_latches(fbf):
                self.latched = True
        if bool(g("failback_shadow_would_latched")) != self.latched:
            self.errors.append(f"t={now}: would_latched {g('failback_shadow_would_latched')} want {self.latched}")

        # published text: exact, with the de-duplication rule of S3 9.3 (changed AND (first | episode edge | >= 10 s))
        ep_event = (phase_before != phase_after or g("failback_shadow_ep") != pre["ep"]
                    or g("failback_shadow_ep_relost") != pre["relost"])
        pub_ms = self.sub("ecco_failback_shadow_publish_min_ms")
        for ent, want in ((VERDICT_T, want_verdict), (INPUTS_T, want_inputs)):
            before = pre["texts"][ent]
            after = str(self.sim.ent(ent).state)
            permit = first or ep_event or ((now - self.last_pub[ent]) & 0xFFFFFFFF) >= pub_ms
            if want != before and permit:
                if after != want:
                    self.errors.append(f"t={now}: {ent} published {after!r}, want {want!r}")
                self.last_pub[ent] = now
            elif want != before and not permit:
                if after != before:
                    self.errors.append(f"t={now}: {ent} changed inside the 10 s window: {before!r} -> {after!r}")
            else:  # equal: nothing to publish
                if after != want:
                    self.errors.append(f"t={now}: {ent} is {after!r}, want {want!r}")
        want_state = sh.state_name(phase_after, bool(g("failback_shadow_would_latched")), stable)
        if str(self.sim.ent(STATE_T).state) != want_state:
            self.errors.append(f"t={now}: State {str(self.sim.ent(STATE_T).state)!r}, want {want_state!r}")
        self.last = dict(rd=rd, ac=ac, verdict=verdict, inputs=in_, want_verdict=want_verdict, want_inputs=want_inputs,
                         stable=stable, first=first, latched_before=latched_before)
        self.ticks += 1


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class Harness(hx.Harness):
    """_fbc_harness.Harness on a FbbSim, with the FB-C2 world helpers, the strict Z9 audit and the optional oracle."""

    def __init__(self, fw: dict, *, oracle: bool = False, **kw):
        self.want_oracle = oracle
        self.oracle: ShadowOracle | None = None
        self.nonfb_changed_log: list = []
        super().__init__(fw, **kw)

    # -- boot ------------------------------------------------------------------------------------------------------------
    def _boot(self, nonce: int, boot_ms: int = 0):
        self.nonce = nonce
        self.sim = TrackingFbbSim(self.fw)
        self.sim.now_ms = boot_ms
        self.boot_ms = boot_ms
        self.sim.ent("api_client_connected_sensor").set(False)
        self.sim.run_lambda(self._init.replace("random_uint32()", f"{nonce}u"))
        lo_f = self._fbc_off if self._fbc_off is not None else self.rng.randrange(0, 500)
        lo_p = self._pra_off if self._pra_off is not None else self.rng.randrange(0, 500)
        self.fbc_next = boot_ms + lo_f
        self.pra_next = boot_ms + lo_p
        self._beat_times = []
        self.apply_world_defaults()
        if self.want_oracle:
            self.oracle = ShadowOracle(self)
        # the strict audit's allow-list never changes between boots

    def boot(self, nonce: int | None = None, boot_ms: int = 0):
        """A fresh boot (new sim, PR-A init, independent random interval phases): same as reboot()."""
        self._fbc_off = self._pra_off = None
        self._boot(nonce if nonce is not None else self.nonce, boot_ms)

    # -- plain world setters -----------------------------------------------------------------------------------------------
    def set_g(self, **kw):
        for k, v in kw.items():
            self.sim.set_global(k, v)

    def set_array(self, name: str, values):
        self.sim.set_global(name, list(values))

    def free_power(self, **kw):
        """free_power_<name> flags (snapshot_valid, marker_state, operator_needed, active_persisted, restore_requested,
        recovery_metadata_corrupt, operation_in_progress, recovery_force_in_progress, recovery_accept_in_progress,
        restore_next_attempt_ms, end_epoch, marker_boot_load, lease_context_reg244, snapshot_reg232 ...)."""
        self.set_g(**{"free_power_" + k: v for k, v in kw.items()})

    def dump(self, **kw):
        """dump_<name>: snapshot_valid, marker_state, operator_needed, active_persisted, restore_requested,
        recovery_metadata_corrupt, operation_in_progress, containment_state, force_restore_bypass, restore_next_attempt_ms,
        end_epoch, marker_boot_load, snapshot_data_loaded, snapshot_reg244 ..."""
        self.set_g(**{"dump_" + k: v for k, v in kw.items()})

    def r244(self, **kw):
        """reg244_<name>: snapshot_valid, marker_state, apply_in_progress, recovery_metadata_corrupt, marker_boot_load,
        last_applied_valid, last_applied_value ..."""
        self.set_g(**{"reg244_" + k: v for k, v in kw.items()})

    def bus(self, **kw):
        """manual_write_in_progress, correction_in_progress, verification_pending, verification_read_active,
        diag_write_lock_held / _since_ms, diag_correction_lock_held / _since_ms, fallback_profile_op_in_progress."""
        self.set_g(**kw)

    def markers(self, fp_load=fp.LOAD_OK, dump_load=fp.LOAD_OK, r244_load=fp.LOAD_OK):
        """The three marker boot loads (ecco_durable::LoadStatus: 0 OK, 1 ABSENT, 2 WRONG_SIZE, 3 READ_ERROR, 255 not loaded)."""
        self.set_g(free_power_marker_boot_load=fp_load, dump_marker_boot_load=dump_load, reg244_marker_boot_load=r244_load)

    def write_attempts(self, manual=None, reg244_apply=None, reg244_restore=None, fp_start=None, dump_start=None):
        for name, v in (("manual_write_attempts", manual), ("reg244_apply_attempts", reg244_apply),
                        ("reg244_restore_attempts", reg244_restore), ("free_power_start_attempts", fp_start),
                        ("dump_start_attempts", dump_start)):
            if v is not None:
                self.set_g(**{name: v})

    def bump_write_attempts(self, which: str = "manual_write_attempts", n: int = 1):
        self.set_g(**{which: self.g(which) + n})

    def set_running(self, script_id: str, running: bool = True):
        if script_id not in self.sim.scripts:
            raise AssertionError(f"{script_id} is not a script of this firmware")
        if running:
            self.sim.running.add(script_id)
        else:
            self.sim.running.discard(script_id)

    def mark_used(self, dom: str, used: bool = True):
        """Sticky 'busy since boot' evidence (dom: fp | dump | r244) for the CLEAR basis: the shadow's global and the oracle's."""
        self.set_g(**{f"failback_shadow_seen_active_{dom}": used})
        if self.oracle is not None:
            self.oracle.seen_active[dom] = used

    def clear_running(self):
        self.sim.running.clear()

    # -- the fallback profile mirror ---------------------------------------------------------------------------------------
    def profile_boot(self, loaded: bool = True):
        self.set_g(fallback_profile_boot_loaded=loaded)

    def set_profile(self, rec: dict | bytes | None, *, load: int = fp.LOAD_OK, cls: int = fd.EPC_VALID,
                    why: int = fd.WHY_NONE, save_unconfirmed: bool = False, read_anomaly: int = 0):
        """The mirror exactly as FB-B1 / FB-B2 hold it: stored record bytes, their load result, the composed class and why."""
        if rec is None:
            raw = blank_bytes()
        elif isinstance(rec, (bytes, bytearray)):
            raw = bytes(rec)
        else:
            raw = profile_bytes(rec)
        self.set_array("fallback_profile_bytes", list(raw))
        self.set_g(fallback_profile_load=load, fallback_profile_class=cls, fallback_profile_why=why,
                   fallback_profile_save_unconfirmed=save_unconfirmed, fallback_profile_read_anomaly=read_anomaly)

    def save_profile(self, rec: dict):
        """A SAVE commits a new VALID record (what FB-B2 does to the mirror): bytes, class VALID, why NONE, anomaly clear."""
        self.set_profile(rec, load=fp.LOAD_OK, cls=fd.EPC_VALID, why=fd.WHY_NONE)

    def invalidate_profile(self):
        rec = fp.invalidate_profile(fp.unpack_profile(bytes(self.g("fallback_profile_bytes"))))
        self.set_profile(rec, load=fp.LOAD_OK, cls=fd.EPC_INVALIDATED, why=fd.WHY_NONE)

    # -- the configuration-poll cache -----------------------------------------------------------------------------------------
    def set_words(self, words):
        """Write the 31 cached configuration words (REGS order) - the live values - without a poll event."""
        assert len(words) == 31
        for gname, v in zip(WORD_GLOBALS, words):
            self.set_g(**{gname: int(v)})

    def words(self) -> list:
        return [self.g(n) for n in WORD_GLOBALS]

    def config_online(self, on: bool):
        self.sim.ent("configuration_online").set(bool(on))

    def config_polling(self, on: bool):
        self.sim.ent("configuration_polling").set(bool(on))

    def dispatch(self):
        """A Block B dispatch (the poll script bumps cfg_block_b_dispatch_seq before the read)."""
        self.set_g(cfg_block_b_dispatch_seq=self.g("cfg_block_b_dispatch_seq") + 1)

    def block_b_success(self, words=None, *, ok: bool = True):
        """Block B on_response: the words, validity, filled, seq++, ok_ms = now, response_dispatch_seq = dispatch_seq."""
        if words is not None:
            self.set_words(words)
        self.set_g(manual_config_raw_cache_valid=ok, fbc_raw_filled=bool(self.g("fbc_raw_filled")) or ok,
                   cfg_block_b_seq=self.g("cfg_block_b_seq") + 1, cfg_block_b_ok_ms=self.sim.millis(),
                   cfg_block_b_response_dispatch_seq=self.g("cfg_block_b_dispatch_seq"))
        self.config_online(ok)

    def poll(self, words=None, *, ok: bool = True):
        """One complete configuration poll: dispatch, then a Block B success."""
        self.dispatch()
        self.block_b_success(words, ok=ok)

    def poll_error(self):
        """Block B on_error: the raw cache is invalidated and the controller goes offline (seq / ok_ms untouched)."""
        self.set_g(manual_config_raw_cache_valid=False)
        self.config_online(False)

    def cache_fresh_after(self, ticks_fn, words=None, polls: int = 3):
        """Make the cache trustworthy THROUGH the real dynamics: the shadow's own fence seeds on its first tick (target =
        dispatch_seq + 2), so run one tick, then complete `polls` polls, then tick again."""
        ticks_fn()
        for _ in range(polls):
            self.poll(words)
        ticks_fn()

    # -- direct supervision injection (enumerations) ------------------------------------------------------------------------
    def sup(self, state: int, stable: bool = True, valid_count: int = 5, beat_age_ms: int = 1000):
        """Set the PR-A supervision globals directly (no PR-A tick, no episode edge): last beat `beat_age_ms` ago."""
        self.set_g(supervision_state=state, supervision_stable=stable, supervision_valid_count=valid_count,
                   supervision_last_valid_ms=(self.sim.millis() - beat_age_ms) & 0xFFFFFFFF, supervision_lost_events=0)

    # -- defaults / resets ----------------------------------------------------------------------------------------------------
    def apply_world_defaults(self):
        """A healthy world: boot-loaded mirror holding the VALID golden profile, every marker loaded OK, every domain idle, no
        cache yet (ca=I)."""
        self.profile_boot(True)
        self.set_profile(GOLD)
        self.markers()
        self.config_polling(True)
        self.config_online(False)

    def reset_shadow(self):
        """Back to the state right after boot for every failback_shadow_* global (the next tick is the `first` tick)."""
        for g in self.fw["globals"]:
            gid = g["id"]
            if not gid.startswith("failback_shadow_"):
                continue
            if gid in self.sim.array_globals:
                self.sim.set_global(gid, [0] * self.sim.array_globals[gid][1])
            else:
                self.sim.set_global(gid, initial_value_of(g))
        if self.oracle is not None:
            self.oracle.reset()

    def reset_world(self):
        """Everything the evaluator reads back to its boot value (non-FB globals from the firmware initial_value), the running
        set cleared, shadow state reset. The simulated clock is NOT touched."""
        for g in self.fw["globals"]:
            gid = g["id"]
            if gid.startswith("failback_shadow_") or gid.startswith("supervision_"):
                continue
            if g["type"] not in H.KNOWN_SCALAR_CTYPES:
                continue  # arrays and records: only the ones this harness sets are reset below
            if g["type"] == "std::string":
                continue
            self.sim.set_global(gid, initial_value_of(g))
        self.clear_running()
        self.apply_world_defaults()
        self.reset_shadow()

    # -- one FB-C tick, audited ---------------------------------------------------------------------------------------------------
    def fbc_tick(self):
        s = self.sim
        pre = None
        if self.oracle is not None:
            pre = dict(ready=s.g["failback_shadow_ready"], phase=s.g["failback_shadow_phase"], ep=s.g["failback_shadow_ep"],
                       relost=s.g["failback_shadow_ep_relost"],
                       texts={e: str(s.ent(e).state) for e in (VERDICT_T, INPUTS_T)})
        if self.enforce_z9:
            gbefore = non_fb_globals(s)
            m0, c0, l0, e0, x0 = len(s.modbus_log), len(s.nvs_commits), len(s.nvs_loads), len(s.events), len(s.executed)
            n0 = {k: repr(v) for k, v in s.nvs.items()}
            d_ops, d_sets, d_blobs = len(s.nvs_direct.ops), len(s.nvs_direct.sets), dict(s.nvs_direct.blobs)
            run0 = set(s.running)
            ent0 = {k: (repr(v.state), len(v.published)) for k, v in s.entities.items() if k not in FBC_TEXT_IDS}
            pub0 = {k: len(v.published) for k, v in s.entities.items()}
            s.accessed = set()
            s.track = True
        s.run_lambda(self._fbc1)
        if self.enforce_z9:
            s.track = False
            gafter = non_fb_globals(s)
            changed = sorted(k for k in gafter if gafter[k] != gbefore.get(k))
            t = s.now_ms
            if changed:
                self.violations.append(f"t={t}: FB-C changed non-FB globals {changed}")
            if len(s.modbus_log) != m0:
                self.violations.append(f"t={t}: FB-C touched the Modbus log")
            if (len(s.nvs_commits), len(s.nvs_loads), len(s.events)) != (c0, l0, e0) or \
                    {k: repr(v) for k, v in s.nvs.items()} != n0:
                self.violations.append(f"t={t}: FB-C touched the tag store / the durable event timeline")
            if len(s.nvs_direct.ops) != d_ops or len(s.nvs_direct.sets) != d_sets or dict(s.nvs_direct.blobs) != d_blobs:
                self.violations.append(f"t={t}: FB-C touched the direct NVS (read, probe or write)")
            if len(s.executed) != x0:
                self.violations.append(f"t={t}: FB-C executed a script")
            if set(s.running) != run0:
                self.violations.append(f"t={t}: FB-C started / stopped a script")
            pubbed = sorted(k for k, v in s.entities.items() if len(v.published) != pub0.get(k, 0))
            if not set(pubbed) <= set(FBC_TEXT_IDS):
                self.violations.append(f"t={t}: FB-C published {pubbed}")
            ent1 = {k: (repr(v.state), len(v.published)) for k, v in s.entities.items() if k not in FBC_TEXT_IDS}
            diff = sorted(k for k in set(ent0) | set(ent1) if ent0.get(k) != ent1.get(k) and k in ent0)
            if diff:
                self.violations.append(f"t={t}: FB-C changed entity state of {diff}")
            bad = sorted(s.accessed - FBC2_ACCESSIBLE)
            if bad:
                self.violations.append(f"t={t}: FB-C accessed entities {bad}")
        self.fbc_invocations += 1
        if self.trace:
            self.log.append((s.now_ms, "fbc"))
        if self.oracle is not None:
            self.oracle.after_tick(s.now_ms, pre)

    @property
    def oracle_errors(self) -> list:
        return self.oracle.errors if self.oracle is not None else []

    def tick(self, dt_ms: int = 1000, n: int = 1):
        """Advance the clock and run ONLY the FB-C tick, n times (no PR-A tick, no heartbeat scheduler): for enumerations and
        directly injected supervision."""
        for _ in range(n):
            self.sim.now_ms += dt_ms
            self.fbc_tick()

    # -- convenience readers -----------------------------------------------------------------------------------------------------
    def verdict(self) -> str:
        return self.text(VERDICT_T)

    def inputs(self) -> dict:
        return self.parse_kv(INPUTS_T)

    def episode_kv(self) -> dict:
        return self.parse_kv(EPISODE_T)

    def soak_kv(self) -> dict:
        return self.parse_kv(SOAK_T)

    def soak_wr(self) -> tuple:
        return tuple(int(x) for x in self.soak_kv()["wr"].split("/"))

    def soak_cs(self) -> tuple:
        return tuple(int(x) for x in self.soak_kv()["cs"].split("/"))

    def soak_xh(self) -> tuple:
        return tuple(int(x) for x in self.soak_kv()["xh"].split("/"))
