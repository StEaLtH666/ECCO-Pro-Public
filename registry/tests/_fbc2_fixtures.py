"""FB-C2 golden fixtures: a fully trusted ShadowInputs plus small declarative mutators.

This module is an INDEPENDENT test-data module for the 81-row decision table (S4 section 9). It builds
registry/failback_shadow.py ShadowInputs from plain values and never calls evaluate().

`base()` returns a fresh ShadowInputs whose evaluation in MODE_IF_LOST is WOULD_ALREADY_MATCH:
  - a VALID, writer-usable profile (profile_why == WHY_NONE, FINAL 4.6 rule B10) whose 31 words equal the live words;
  - every lease domain (Dump / FP / R244) RAM-clear AND clear *by marker* (boot load OK, "-" in the table, not "Cabs");
  - the bus idle, no Manual TOU apply running;
  - a fresh live cache: Block B 1 s old, polling on, valid + online + filled, write fence passed;
  - boot_loaded True; supervision SUPERVISED (state 1) and stable; no episode.

Mutators are plain functions `f(i, ...)` that edit the ShadowInputs in place; `apply(i, *steps)` chains them, a step is
either a callable or a tuple `(callable, arg, ...)`.

Supervision numbering (firmware supervision_state, FW:1130/1351/22569): 0 STARTUP, 1 SUPERVISED, 2 SUSPECT, 3 LOST.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import failback_shadow as sh  # noqa: E402

# --- supervision states -----------------------------------------------------------------------------------------------
SUP_STARTUP, SUP_SUPERVISED, SUP_SUSPECT, SUP_LOST = 0, 1, 2, 3

# --- the golden profile (VALID, generation 7) -------------------------------------------------------------------------
P244 = 2
P256 = [8000, 500, 4000, 3000, 2000, 1000]
P268 = [100, 20, 0, 50, 100, 30]
P274 = [1, 0, 1, 0, 0, 1]
P232, P243, P248 = 0x0011, 1, 1
P250 = [0, 530, 1000, 1600, 2100, 2330]
P230, P245, P247 = 185, 8000, 1


def make_profile(generation: int = 7, **over) -> dict:
    """A sealed V1 profile record (binding computed). Overrides replace payload fields before sealing."""
    rec = fp.blank_profile(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=generation, captured_epoch=1790000000,
                           flags=0, reg244=P244, reg256_261=list(P256), reg268_273=list(P268), reg274_279=list(P274),
                           reg232=P232, reg243=P243, reg248=P248, reg250_255=list(P250), reg230=P230, reg245=P245,
                           reg247=P247)
    rec.update(over)
    return fp.seal_profile(rec)


GOLD = make_profile(7)


def live_words_of(p: dict) -> list:
    """The 31 live words in REGS order (244, 256-261, 268-273, 274-279, 232, 243, 248, 250-255, 230, 245, 247)."""
    return list(cap.words_of(p))


# --- construction -----------------------------------------------------------------------------------------------------
def base() -> "sh.ShadowInputs":
    g = cap.GateInputs(boot_loaded=True, fbs_slot=fd.FBS_CLEAR_ABSENT)
    # '-' in the table = CLEAR with MARKER evidence = boot load OK (not ABSENT, which is "Cabs")
    g.fp.free_power_marker_boot_load = cap.BOOT_LOAD_OK
    g.dump.dump_marker_boot_load = cap.BOOT_LOAD_OK
    g.r244.reg244_marker_boot_load = cap.BOOT_LOAD_OK
    lm = cap.LiveMatchInputs(
        g=g, mtou_running=False, cls=fd.EPC_VALID, write_outcome_unknown=False, read_anomaly=0, p_load=fp.LOAD_OK,
        p=copy.deepcopy(GOLD),
        cache=cap.LiveCache(cache_valid=True, online=True, polling=True, filled=True, block_b_seq=5, block_b_ok_ms=1000,
                            now_ms=2000, response_dispatch_seq=7, fence_seq=7),
        edge_fence_seq=0, live=live_words_of(GOLD), dump_data_loaded=False, dump_snapshot_reg244=0xFFFF,
        dump_snapshot_reg256_261=[0] * 6, ceiling_w=8000)
    return sh.ShadowInputs(mode=sh.MODE_ACTUAL, sup=sh.SupIn(state=SUP_SUPERVISED, p_stable=True, episode_open=False),
                           lm=lm, profile_why=fd.WHY_NONE, not_captured_proven=False)


def apply(i, *steps):
    """Apply mutators in order. A step is `f` or `(f, arg, ...)`. Returns i."""
    for st in steps:
        if isinstance(st, tuple):
            st[0](i, *st[1:])
        else:
            st(i)
    return i


# --- supervision ------------------------------------------------------------------------------------------------------
def lost(i):
    """supervision LOST (state 3); never stable."""
    i.sup.state, i.sup.p_stable = SUP_LOST, False


def sup_state(i, state, stable=False, episode=False):
    i.sup.state, i.sup.p_stable, i.sup.episode_open = state, stable, episode


def episode_bound_to_current(i):
    """An open episode whose binding was recorded against the CURRENT effective class / generation / binding (S4 6.2)."""
    eff = cap.live_effective_class(i.lm.cls, i.lm.write_outcome_unknown, i.lm.read_anomaly)
    meaningful = eff in (fd.EPC_VALID, fd.EPC_INVALIDATED, fd.EPC_CORRUPT_DOMAIN)
    p = i.lm.p
    i.sup.episode_open = True
    i.ep = sh.EpProf(bound=True, cls=eff, gen=p["generation"] if meaningful else 0, binding=p["binding"] if meaningful else 0)


# --- live words / cache -----------------------------------------------------------------------------------------------
def set_live(i, reg: int, value: int):
    """Set the live word of register `reg` (244, 256-261, 268-279, 232, 243, 248, 250-255, 230, 245, 247)."""
    i.lm.live[cap.REGS.index(reg)] = value


def set_live_many(i, regs, values):
    for r, v in zip(regs, values):
        set_live(i, r, v)


def cache_stale(i):
    """Block B older than 180 s (S4 7.6 term 'cache_state != S')."""
    i.lm.cache.now_ms = i.lm.cache.block_b_ok_ms + cap.LIVE_CACHE_MAX_AGE_MS + 1


def cache_polling_off(i):
    i.lm.cache.polling = False


def cache_pre_fence(i):
    """No poll since the write fence: the latched dispatch seq (7) is below the fence (9)."""
    i.lm.cache.fence_seq = i.lm.cache.response_dispatch_seq + 2


def cache_no_block_b_since_boot(i):
    """No Block B has arrived since boot: no cache, seq 0, nothing latched."""
    c = i.lm.cache
    c.cache_valid, c.block_b_seq, c.filled = False, 0, False


def cache_unlatched(i):
    """Block B is fine but FB-C2 has not latched a snapshot yet (the 'filled' term of the shared live_trust)."""
    i.lm.cache.filled = False


# --- profile ----------------------------------------------------------------------------------------------------------
def set_profile(i, cls, p_load=fp.LOAD_OK, record=None, why=fd.WHY_NONE, sync_live=False):
    """Replace the profile mirror. `record` None leaves lm.p None (only for ABSENT / unreadable classes)."""
    i.lm.cls, i.lm.p_load, i.lm.p, i.profile_why = cls, p_load, record, why
    if sync_live and record is not None:
        i.lm.live = live_words_of(record)


def profile_not_captured(i, proven: bool):
    set_profile(i, fd.EPC_NOT_CAPTURED, fp.LOAD_ABSENT, None)
    i.not_captured_proven = proven


def profile_invalidated(i):
    set_profile(i, fd.EPC_INVALIDATED, fp.LOAD_OK, fp.invalidate_profile(GOLD))


def profile_corrupt(i):
    set_profile(i, fd.EPC_CORRUPT, fp.LOAD_WRONG_SIZE, None)


def profile_corrupt_domain(i):
    """An authentic record whose E1 payload is outside the V1 domain (244 = 1)."""
    rec = make_profile(7, reg244=1)
    assert fp.classify_profile(fp.LOAD_OK, rec) == fp.PROFILE_CORRUPT_DOMAIN
    set_profile(i, fd.EPC_CORRUPT_DOMAIN, fp.LOAD_OK, rec)


def profile_unreadable(i):
    set_profile(i, fd.EPC_UNREADABLE, fp.LOAD_READ_ERROR, None)


def profile_save_unconfirmed(i):
    """Prior VALID mirror kept in RAM, but the FB-B durable outcome is UNKNOWN this boot (write_outcome_unknown)."""
    i.lm.write_outcome_unknown = True


def profile_lost(i):
    set_profile(i, fd.EPC_PROFILE_LOST, fp.LOAD_ABSENT, None)


def site_ceiling(i, watts):
    i.lm.ceiling_w = watts


# --- Free Power domain ------------------------------------------------------------------------------------------------
def _bus_owner_running(i):
    """The lease script that owns the write lock is running: MWIP held with a known owner."""
    i.lm.g.bus.manual_write_in_progress = True
    i.bus.any_owner_running = True


def fp_active(i):
    """ACTIVE lease: SV, marker RR, AP, no restore requested, not expired."""
    d = i.lm.g.fp
    d.free_power_snapshot_valid, d.free_power_marker_state = True, cap.MARKER_STATE_RESTORE_REQUIRED
    d.free_power_active_persisted, d.free_power_restore_requested, d.expired = True, False, False


def fp_starting(i):
    """START running (OIP + START script + lock held by it)."""
    i.lm.g.fp.run_start = True
    i.lm.g.bus.free_power_operation_in_progress = True
    _bus_owner_running(i)


def fp_rr(i, backoff=False):
    """RESTORE_REQUIRED, restore due (boot AP->RQ, lease expired); `backoff` = comms backoff pending (NA in the future)."""
    d = i.lm.g.fp
    d.free_power_snapshot_valid, d.free_power_marker_state = True, cap.MARKER_STATE_RESTORE_REQUIRED
    d.free_power_active_persisted, d.free_power_restore_requested, d.expired = False, True, True
    i.fp.backoff = backoff


def fp_pc(i):
    d = i.lm.g.fp
    d.free_power_snapshot_valid, d.free_power_marker_state = True, cap.MARKER_STATE_PENDING_CLEAR


def fp_on(i):
    """OPERATOR_NEEDED: SV, RR, ON."""
    fp_rr(i)
    i.lm.g.fp.free_power_operator_needed = True


def fp_ending(i):
    """A trusted restore is running (RESTORE script, OIP, lock held by the owner)."""
    fp_rr(i)
    i.lm.g.fp.run_restore = True
    i.lm.g.bus.free_power_operation_in_progress = True
    _bus_owner_running(i)


def fp_mc(i, unreadable=False):
    """Latched hard lockout. unreadable=True = boot marker READ_ERROR (UK), else malformed marker (MC)."""
    d = i.lm.g.fp
    d.free_power_recovery_metadata_corrupt = True
    d.free_power_marker_boot_load = cap.BOOT_LOAD_READ_ERROR if unreadable else cap.BOOT_LOAD_OK


def fp_oip_orphan(i, age_ms):
    """free_power_operation_in_progress set, no FP script running, flag orphaned for age_ms."""
    i.lm.g.bus.free_power_operation_in_progress = True
    i.fp.orphan_ms = age_ms


def fp_snapshot_equals_profile(i):
    """The FP snapshot (pre-lease ORIGINAL) equals the profile words: after the lease clears the live words are ORIGINAL."""
    p = i.lm.p
    i.fp_snap = sh.FpSnapshot(valid=True, r232=p["reg232"], r256=list(p["reg256_261"]), r268=list(p["reg268_273"]),
                              r274=list(p["reg274_279"]))


def fp_lease_overlay(i):
    """The cached live words while an FP lease is applied: 232 changed, 256-261 -> lease power, 268-273 / 274-279 forced."""
    set_live(i, 232, P232 | 0x0002)
    set_live_many(i, range(256, 262), [3000] * 6)
    set_live_many(i, range(268, 274), [100] * 6)
    set_live_many(i, range(274, 280), [1] * 6)


# --- Dump domain ------------------------------------------------------------------------------------------------------
def dump_active(i):
    d = i.lm.g.dump
    d.dump_snapshot_valid, d.dump_marker_state = True, cap.MARKER_STATE_RESTORE_REQUIRED
    d.dump_active_persisted, d.dump_restore_requested, d.expired = True, False, False


def dump_rr(i, backoff=False):
    """RESTORE_REQUIRED (restore requested), `backoff` = comms backoff pending."""
    d = i.lm.g.dump
    d.dump_snapshot_valid, d.dump_marker_state = True, cap.MARKER_STATE_RESTORE_REQUIRED
    d.dump_active_persisted, d.dump_restore_requested, d.expired = False, True, True
    i.dump.backoff = backoff


def dump_on(i):
    """OPERATOR_NEEDED: SV, RR, N."""
    dump_rr(i)
    i.lm.g.dump.dump_operator_needed = True


def dump_ending(i):
    """Restore running: RESTORE script, O flag, lock held by the owner."""
    dump_rr(i)
    i.lm.g.dump.run_restore = True
    i.lm.g.bus.dump_operation_in_progress = True
    _bus_owner_running(i)


def dump_mc(i, k=0, unreadable=False):
    """Latched lockout with containment state K (unreadable=True: boot marker READ_ERROR, K 8)."""
    d = i.lm.g.dump
    d.dump_recovery_metadata_corrupt = True
    d.dump_marker_boot_load = cap.BOOT_LOAD_READ_ERROR if unreadable else cap.BOOT_LOAD_OK
    d.dump_containment_state = k


def dump_force_bypass(i):
    i.dump.force_bypass = True


# --- R244 domain ------------------------------------------------------------------------------------------------------
def r244_held(i):
    """OPERATOR_NEEDED: snapshot valid, marker RR (a held harness test)."""
    d = i.lm.g.r244
    d.reg244_snapshot_valid, d.reg244_marker_state = True, cap.MARKER_STATE_RESTORE_REQUIRED


def r244_drift_guard(i, last_applied):
    """LAV true with LA != live 244 (the restore would be refused by the drift guard)."""
    i.r244x.lav, i.r244x.la = True, last_applied


def r244_pc(i):
    d = i.lm.g.r244
    d.reg244_snapshot_valid, d.reg244_marker_state = True, cap.MARKER_STATE_PENDING_CLEAR


def r244_restore_running(i):
    r244_held(i)
    i.lm.g.r244.run_restore = True
    i.lm.g.bus.reg244_apply_in_progress = True
    _bus_owner_running(i)


def r244_mc(i):
    d = i.lm.g.r244
    d.reg244_recovery_metadata_corrupt = True
    d.reg244_marker_boot_load = cap.BOOT_LOAD_OK


# --- evidence by absence / retry records ------------------------------------------------------------------------------
def cabs(i, *doms):
    """'Cabs': boot marker load ABSENT and never used since boot (clear by absence)."""
    for dom in doms:
        if dom == "dump":
            i.lm.g.dump.dump_marker_boot_load = cap.BOOT_LOAD_ABSENT
        elif dom == "fp":
            i.lm.g.fp.free_power_marker_boot_load = cap.BOOT_LOAD_ABSENT
        elif dom == "r244":
            i.lm.g.r244.reg244_marker_boot_load = cap.BOOT_LOAD_ABSENT
        else:
            raise ValueError(dom)


def probe_latch(i, dom: int, code: int):
    """FB-B per-boot probe latch (set-only nibble): dom cap.DOM_FP/DOM_DUMP/DOM_R244, code cap.LATCH_*."""
    i.lm.g.probe_latch = cap.latch_set(i.lm.g.probe_latch, dom, code)


# --- bus --------------------------------------------------------------------------------------------------------------
def mwip_orphan(i, age_ms):
    """manual_write_in_progress held, no owner script running, for age_ms."""
    i.lm.g.bus.manual_write_in_progress = True
    i.bus.any_owner_running, i.bus.mwip_orphan_ms = False, age_ms


def cip_held(i, age_ms):
    """correction_in_progress (RTC write) held for age_ms."""
    i.lm.g.bus.correction_in_progress = True
    i.bus.cip_held_ms = age_ms


def mtou_running(i):
    i.lm.mtou_running = True


def boot_not_loaded(i):
    """boot_loaded 0; the marker boot loads are 'not assigned' (0xFF)."""
    i.lm.g.boot_loaded = False
    i.lm.g.fp.free_power_marker_boot_load = cap.BOOT_LOAD_NOT_LOADED
    i.lm.g.dump.dump_marker_boot_load = cap.BOOT_LOAD_NOT_LOADED
    i.lm.g.r244.reg244_marker_boot_load = cap.BOOT_LOAD_NOT_LOADED
