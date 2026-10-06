"""FB-B2 durable matrix: the ROW FAMILIES (see _fbb2_durable_lib.py for the oracles and the shared row machinery).

  cuts-nvs       a power cut BEFORE and AFTER every direct-NVS event of SAVE over every prior class (+ the 'no cut' rows)
  cuts-k         the S2 final 6.1 per-key stage model K0..K6 on each key (K0-K3 resolve to OLD, K4-K6 to NEW) over every prior
  cuts-timeline  a power cut after every Modbus read / delivery / NVS / switch event on a DEFERRED bus (the C0-C2 rows and the dispatch)
  cuts-boot      a nested power cut during the NEXT boot's load (boot only reads: harmless)
  faults-grid-W / faults-grid-P   every master 4.3 cell: 14 write codes x 7 readback states x 2 health on each key
  faults-doc     master 5.5 rows F1-F13, F-H1, F-H2, partition wipe, dedup erase, handle 0 (at boot and at the commit)
  faults-prior   the representative faults over EVERY prior class
  invalidate     INVALIDATE: the power-cut rows (5.3) and the fault rows, UNKNOWN overlay, the W-INV golden
  antirollback   generation / witness / stale / foreign / regression-guard / high-water / wrap rows
  sequences      long scripted and seeded-random operation sequences: generations strictly increase
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fbb2_durable_lib as L  # noqa: E402
from _fbb2_durable_lib import (Acc, Cell, D, Flash, H, Rep, ROWS, fd, fdo, fp, register)  # noqa: E402

FAMILIES: dict = {}


def reg(family: str, name: str, fn) -> None:
    register(name, fn)
    FAMILIES.setdefault(family, []).append(name)


def run_family(family: str, shard: int = 0, nshards: int = 1) -> Acc:
    """Run (a shard of) one family. Shard k takes every nshards-th row, so shards are independent work items for a process pool."""
    acc = Acc(family)
    for name in FAMILIES[family][shard::nshards]:
        try:
            acc.add(ROWS[name]())
        except Exception as e:   # a harness / driver error is a failing row, never a skipped one
            r = Rep(name)
            r.ok(False, f"row raised {type(e).__name__}: {e}")
            acc.add(r)
    acc.extra["keys"] = sorted(L.KEYS_SEEN)
    return acc


def run_row(name: str) -> list:
    """Run one named row; its failure messages ([] = clean). Used by the mutants as 'the named row'."""
    try:
        return list(ROWS[name]().fails)
    except D.FbbNotModelled as e:
        raise
    except Exception as e:
        return [f"[{name}] raised {type(e).__name__}: {e}"]


# ---------------------------------------------------------------------------
# cuts-nvs / cuts-timeline / cuts-k / cuts-boot
# ---------------------------------------------------------------------------
_DRY: dict = {}
CUT_PRIORS = list(L.PRIORS)
DEC_W, DEC_P = fd.decimal_key(L.K_W), fd.decimal_key(L.K_P)


def dry(prior_name: str, mode=None) -> dict:
    """The event structure of one clean SAVE over this prior (cached per process): the number of NVS events, the index of the FBW and
    FBP set events, and (deferred bus) the timeline events of the kinds a power cut can follow."""
    key = (prior_name, mode)
    if key in _DRY:
        return _DRY[key]
    pr = L.PRIORS[prior_name]
    d = L.make_driver(pr.seed, mode=mode)
    nv = d.sim.nvs_direct
    nv.events = 0
    n0, e0 = len(nv.ops), len(d.sim.events)
    d.save(replace_corrupt=pr.rc)
    ops = nv.ops[n0:]
    iw = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == DEC_W)
    ip = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == DEC_P)
    kinds = ("nvs", "read", "deliver", "switch")
    tl = [ev for ev in d.sim.events[e0:] if ev[0] in kinds]
    tw = next(i for i, ev in enumerate(tl) if ev[0] == "nvs" and ev[1] == "set" and ev[2] == DEC_W)
    tp = next(i for i, ev in enumerate(tl) if ev[0] == "nvs" and ev[1] == "set" and ev[2] == DEC_P)
    _DRY[key] = dict(n_events=nv.events, iw=iw, ip=ip, n_timeline=len(tl), tw=tw, tp=tp, kinds=kinds)
    return _DRY[key]


def expected_for_stage(pr: "L.Prior", stage: str):
    """(next-boot class, why) and the generation of the next clean SAVE from that boot, per the locked tables (master 5.1-5.4)."""
    if stage == "before":
        return pr.before, pr.save_gen
    if stage == "w_only":
        return pr.w_only, pr.follow_w_only
    return ("VALID", "-"), pr.save_gen + 1


def cut_check(d: "D.Driver", rep: Rep, pr: "L.Prior", fl0: Flash, st, stage: str, cut_expected: bool, p_new: dict, w_new: dict) -> None:
    """Everything a power-cut row asserts after the cut and BEFORE the reboot."""
    rep.eq(st.cut is not None, cut_expected, "the power cut fired (or ran to completion) as expected")
    want_sets = {"before": [], "w_only": ["FBW"], "both": ["FBW", "FBP"]}[stage]
    sets = [(L.FB_DEC.get(fd.decimal_key(k), k), bytes(b)) for k, b, _r in st.since.nvs_set_log]
    L.note_sets(st.since.nvs_set_log)
    rep.eq([s[0] for s in sets], want_sets, f"FB sets before the cut ({L.STAGE_LABELS[stage]})")
    intended = {"FBW": fdo.pack_provision(w_new), "FBP": fp.pack_profile(p_new)}
    rep.eq(sets, [(n, intended[n]) for n in want_sets], "the bytes written are the intended pair")
    rep.eq(st.since.violations_fb(tuple(want_sets), bytes_=intended), [], "write audit (only FBW then FBP, zero Modbus writes)")
    rep.eq(st.since.writes, [], "Modbus writes before the cut")
    if st.cut is None:
        rep.eq(d.b9, f"SAVED - known-good profile generation {w_new['hw_generation']} saved (verified this boot)", "B9 of the uncut run")


def finish_cut(d: "D.Driver", rep: Rep, pr: "L.Prior", stage: str, fl0: Flash, what: str) -> None:
    """Reboot through the real on_boot and judge the booted state against the locked table AND the oracle, then the operator action."""
    nv = d.sim.nvs_direct
    ofl = L.boot_flash(nv)
    d.reboot()
    L.boot_invariants(d, rep)
    cls_why, nxt = expected_for_stage(pr, stage)
    L.check_booted(d, rep, ofl, table=cls_why, what=what)
    L.follow_up_save(d, rep, ofl, expect_gen=nxt, what=f"{what}: Review + Save from the booted state")


def cut_row_nvs(prior_name: str, point: int) -> Rep:
    pr = L.PRIORS[prior_name]
    ds = dry(prior_name)
    n, iw, ip = ds["n_events"], ds["iw"], ds["ip"]
    stage = "before" if point <= 2 * iw else ("w_only" if point <= 2 * ip else "both")
    rep = Rep(f"{prior_name}@nvs-point-{point} ({'before' if point % 2 == 0 else 'after'} event {point // 2})")
    d = L.make_driver(pr.seed)
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    gen = L.formula_gen(fl0, L.seen_at_boot(fl0))
    p_new, w_new = L.intended_pair(fl0, gen, pr.rc)
    nv.events = 0
    nv.cut_at = point
    st = d.save(replace_corrupt=pr.rc, catch_cut=True)
    cut_check(d, rep, pr, fl0, st, stage, point < 2 * n, p_new, w_new)
    finish_cut(d, rep, pr, stage, fl0, "reboot")
    return rep


def cut_row_timeline(prior_name: str, p: int) -> Rep:
    pr = L.PRIORS[prior_name]
    mode = ("deferred", 120)
    ds = dry(prior_name, mode)
    stage = "before" if p < ds["tw"] else ("w_only" if p < ds["tp"] else "both")
    rep = Rep(f"{prior_name}@timeline-event-{p}")
    d = L.make_driver(pr.seed, mode=mode)
    fl0 = Flash.of(d.sim.nvs_direct)
    gen = L.formula_gen(fl0, L.seen_at_boot(fl0))
    p_new, w_new = L.intended_pair(fl0, gen, pr.rc)
    d.cut_after_event(p, ds["kinds"])
    st = L.save_cut(d, pr.rc)
    cut_check(d, rep, pr, fl0, st, stage, True, p_new, w_new)
    finish_cut(d, rep, pr, stage, fl0, "reboot")
    return rep


def cut_row_k(prior_name: str, key: str, ks: str) -> Rep:
    """K0..K6 on one key (S2 final 6.1): K0 = before nvs_set_blob; K1-K3 = a cut that resolves to OLD at the next init; K4-K6 = NEW."""
    pr = L.PRIORS[prior_name]
    rep = Rep(f"{prior_name}@{L.NAME[key]}-{ks}")
    old_new = dict((k, o) for k, _t, o in L.K_STAGES)[ks]
    d = L.make_driver(pr.seed)
    fl0 = Flash.of(d.sim.nvs_direct)
    gen = L.formula_gen(fl0, L.seen_at_boot(fl0))
    p_new, w_new = L.intended_pair(fl0, gen, pr.rc)
    if ks == "K0":
        d.cut_before_nvs("set", L.NAME[key], 1)
    else:
        d.fault_write(L.NAME[key], result=fdo.IDF_OK, visible=(H.VIS_OLD if old_new == "old" else H.VIS_NEW),
                      boot=(H.BOOT_OLD if old_new == "old" else H.BOOT_NEW))
        d.cut_after_nvs("set", L.NAME[key], 1)
    st = d.save(replace_corrupt=pr.rc, catch_cut=True)
    if key == "W":
        stage = "before" if old_new == "old" else "w_only"
        issued = [] if ks == "K0" else ["FBW"]
    else:
        stage = "w_only" if old_new == "old" else "both"
        issued = ["FBW"] if ks == "K0" else ["FBW", "FBP"]
    rep.ok(st.cut is not None, "the power cut fired")
    sets = [L.FB_DEC.get(fd.decimal_key(k), k) for k, _b, _r in st.since.nvs_set_log]
    L.note_sets(st.since.nvs_set_log)
    rep.eq(sets, issued, "FB sets issued before the cut")
    rep.eq(st.since.violations_fb(tuple(issued)), [], "write audit")
    finish_cut(d, rep, pr, stage, fl0, f"reboot after {L.NAME[key]} {ks}")
    return rep


def cut_row_boot(prior_name: str, point: int) -> Rep:
    """A nested cut during the NEXT boot's load. First leave the storage in the 'FBW indexed, FBP not' state, then power-cycle with a
    cut at NVS point `point` of the boot, then boot cleanly: same class, nothing written by either boot."""
    pr = L.PRIORS[prior_name]
    rep = Rep(f"{prior_name}@boot-cut-{point}")
    d = L.make_driver(pr.seed)
    nv = d.sim.nvs_direct
    d.cut_after_nvs("set", "FBW", 1)
    st = d.save(replace_corrupt=pr.rc, catch_cut=True)
    rep.ok(st.cut is not None, "the first cut fired")
    ofl = L.boot_flash(nv)
    d.reboot(boot=False)
    d.sim.nvs_direct.events = 0
    d.sim.nvs_direct.cut_at = point
    cut = False
    try:
        d.sim.run_boot()
    except D.PowerCut:
        cut = True
    rep.eq(d.sim.nvs_direct.sets, [], "a boot interrupted by a power cut wrote NVS")
    rep.eq(L.boot_flash(d.sim.nvs_direct).cls_why, ofl.cls_why, "the interrupted boot did not change what the next boot reads")
    d.reboot()
    L.boot_invariants(d, rep)
    L.check_booted(d, rep, ofl, table=pr.w_only, what="boot after the nested cut")
    return rep


PUBLISH_ENTITIES = {"B1": "fallback_profile_state_text", "B2": "fallback_profile_summary_text", "B7": "fallback_profile_slots_text",
                    "B8": "fallback_profile_context_text", "B9": "fallback_profile_last_result_text", "B3": "fallback_profile_review_text"}


def cut_row_publish(prior_name: str, which: str) -> Rep:
    """C8 / C9: a power cut during the post-commit mirror / publish (the instant the entity `which` is published with both records
    already written) or right after the release (the dispatch's `done` event): flash holds both new records -> VALID g+1."""
    pr = L.PRIORS[prior_name]
    rep = Rep(f"{prior_name}@publish-{which}")
    d = L.make_driver(pr.seed)
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    gen = L.formula_gen(fl0, L.seen_at_boot(fl0))
    p_new, w_new = L.intended_pair(fl0, gen, pr.rc)
    if which == "release":
        d.cut_when(lambda ev: ev[0] == "task" and ev[1] == "fallback_profile_capture_dispatch" and ev[2] == "done", "cut after the release")
    else:
        ent = d.sim.ent(PUBLISH_ENTITIES[which])
        orig = ent.publish_state

        def wrapper(value, _orig=orig):
            if len(nv.sets) >= 2:
                raise D.PowerCut(f"power cut while publishing {which}")
            return _orig(value)
        ent.publish_state = wrapper
    st = L.save_cut(d, pr.rc)
    # B1 is only published when the class text changes (VALID -> VALID is deduplicated: no publish, no cut point)
    cut_check(d, rep, pr, fl0, st, "both", not (which == "B1" and pr.boot[0] == "VALID"), p_new, w_new)
    finish_cut(d, rep, pr, "both", fl0, f"reboot after the cut at {which}")
    return rep


def boot_events(prior_name: str) -> int:
    """The number of direct-NVS events of the boot that follows the 'FBW indexed, FBP not' power cut over this prior."""
    pr = L.PRIORS[prior_name]
    d = L.make_driver(pr.seed)
    d.cut_after_nvs("set", "FBW", 1)
    d.save(replace_corrupt=pr.rc, catch_cut=True)
    d.reboot(boot=False)
    d.sim.nvs_direct.events = 0
    d.sim.run_boot()
    return d.sim.nvs_direct.events


for _pn in CUT_PRIORS:
    _ds = dry(_pn)
    for _p in range(0, 2 * _ds["n_events"] + 2):
        reg("cuts-nvs", f"cut:nvs:{_pn}:{_p}", lambda pn=_pn, p=_p: cut_row_nvs(pn, p))
_KFULL = ("first", "valid", "lost", "corrupt")
for _pn in CUT_PRIORS:
    for _key in ("W", "P"):
        _ks_list = [k for k, _t, _o in L.K_STAGES] if _pn in _KFULL else ["K0", "K1", "K4", "K6"]
        for _ks in _ks_list:
            reg("cuts-k", f"cut:k:{_pn}:{L.NAME[_key]}:{_ks}", lambda pn=_pn, k=_key, s=_ks: cut_row_k(pn, k, s))
for _pn in ("first", "valid", "lost", "corrupt"):
    _dt = dry(_pn, ("deferred", 120))
    for _p in range(_dt["n_timeline"]):
        reg("cuts-timeline", f"cut:tl:{_pn}:{_p}", lambda pn=_pn, p=_p: cut_row_timeline(pn, p))
for _pn in ("first", "valid", "lost", "corrupt"):
    for _w in (*PUBLISH_ENTITIES, "release"):
        reg("cuts-timeline", f"cut:publish:{_pn}:{_w}", lambda pn=_pn, w=_w: cut_row_publish(pn, w))
for _pn in ("valid", "first", "corrupt"):
    _be = boot_events(_pn)
    for _p in range(0, 2 * _be + 2):
        reg("cuts-boot", f"cut:boot:{_pn}:{_p}", lambda pn=_pn, p=_p: cut_row_boot(pn, p))


# ---------------------------------------------------------------------------
# faults-grid: every master 4.3 cell on each key
# ---------------------------------------------------------------------------
E = fdo
CODES = [("OK", E.IDF_OK), ("INVALID_HANDLE", E.IDF_ERR_NVS_INVALID_HANDLE), ("READ_ONLY", E.IDF_ERR_NVS_READ_ONLY),
         ("NOT_INITIALIZED", E.IDF_ERR_NVS_NOT_INITIALIZED), ("TIMEOUT", E.IDF_ERR_TIMEOUT), ("NOT_FOUND", E.IDF_ERR_NVS_NOT_FOUND),
         ("NO_MEM", E.IDF_ERR_NO_MEM), ("NOT_ENOUGH_SPACE", E.IDF_ERR_NVS_NOT_ENOUGH_SPACE), ("FLASH_OP_FAIL", E.IDF_ERR_FLASH_OP_FAIL),
         ("FAIL", E.IDF_FAIL), ("REMOVE_FAILED", E.IDF_ERR_NVS_REMOVE_FAILED), ("NVS_INVALID_STATE", E.IDF_ERR_NVS_INVALID_STATE),
         ("PAGE_FULL", E.IDF_ERR_NVS_PAGE_FULL), ("INVALID_ARG", E.IDF_ERR_INVALID_ARG)]
VISIBLES = [H.VIS_NEW, H.VIS_OLD, H.VIS_OTHER, H.VIS_ABSENT, H.VIS_WRONGSIZE, H.VIS_CRCBAD, H.VIS_UNAVAILABLE]
CODE_NAME = {c: n for n, c in CODES}


def grid_row(prior_name: str, key: str, code: int, vis: str, healthy: bool, same_boot: bool = False) -> Rep:
    cell = Cell(key, code, vis, H.BOOT_ASIS, healthy)
    wcell, pcell = (cell, None) if key == "W" else (None, cell)
    pr = L.PRIORS[prior_name]
    fl = None
    # the doc outcome decides whether this cell commits or not -> the same-boot follow-up only where the transaction did not latch
    d = L.make_driver(pr.seed, review=False)
    fl = Flash.of(d.sim.nvs_direct)
    dt = L.doc_txn(fl, wcell, pcell)
    return L.txn_row(prior_name, wcell, pcell, label=f"grid:{prior_name}:{L.NAME[key]}:{CODE_NAME[code]}:{vis}:{'h' if healthy else 'UNHEALTHY'}"
                     + (":sb" if same_boot else ""), same_boot=same_boot and dt.txn != "UNKNOWN", battery=True, quick_battery=True)


for _key in ("W", "P"):
    for _cn, _code in CODES:
        for _vis in VISIBLES:
            for _h in (True, False):
                reg(f"faults-grid-{_key}", f"grid:valid:{_key}:{_cn}:{_vis}:{int(_h)}",
                    lambda k=_key, c=_code, v=_vis, h=_h: grid_row("valid", k, c, v, h))
_FLASH_VALID = None


def _valid_flash() -> "Flash":
    global _FLASH_VALID
    if _FLASH_VALID is None:
        _FLASH_VALID = Flash.of(D.Driver(seed="valid", boot=False, housekeeping=False).sim.nvs_direct)
    return _FLASH_VALID


for _key in ("W", "P"):
    for _cn, _code in CODES:
        for _vis in VISIBLES:
            for _h in (True, False):
                _cell = Cell(_key, _code, _vis, H.BOOT_ASIS, _h)
                _dt = L.doc_txn(_valid_flash(), *((_cell, None) if _key == "W" else (None, _cell)))
                if _dt.txn != "UNKNOWN":
                    reg(f"faults-grid-{_key}", f"grid:valid:{_key}:{_cn}:{_vis}:{int(_h)}:sb",
                        lambda k=_key, c=_code, v=_vis, h=_h: grid_row("valid", k, c, v, h, same_boot=True))
# the 'prior is ABSENT' readback class: first capture, FBW / FBP key
for _key in ("W", "P"):
    for _cn, _code in CODES:
        if _code in (E.IDF_OK, *L.PRE_WRITE, E.IDF_ERR_TIMEOUT):
            for _h in (True, False):
                if _key == "P" and not _h:
                    continue
                reg(f"faults-grid-{_key}", f"grid:first:{_key}:{_cn}:ABSENT:{int(_h)}",
                    lambda k=_key, c=_code, h=_h: grid_row("first", k, c, H.VIS_ABSENT, h))


# ---------------------------------------------------------------------------
# faults-doc: master 5.5 rows by name
# ---------------------------------------------------------------------------
def doc_row(name: str, prior: str, w=None, p=None, boot=None, same_boot=False, **kw):
    """A master 5.5 row. same_boot rows are registered twice: once with the plain reboot straight after the outcome and once (':sb')
    with the same-boot Review + SAVE first."""
    reg("faults-doc", f"doc:{name}", lambda: L.txn_row(prior, w, p, label=f"doc:{name}", expect_boot=boot, **kw))
    if same_boot:
        reg("faults-doc", f"doc:{name}:sb", lambda: L.txn_row(prior, w, p, label=f"doc:{name}:sb", expect_boot=boot, same_boot=True, **kw))


PRE_W = E.IDF_ERR_NVS_READ_ONLY
doc_row("F1", "valid", Cell("W", PRE_W, H.VIS_OLD), boot=("VALID", "-"), same_boot=True)
for _c, _cn in ((E.IDF_ERR_TIMEOUT, "TIMEOUT"), (E.IDF_ERR_NVS_NOT_FOUND, "NOT_FOUND"), (E.IDF_ERR_NO_MEM, "NO_MEM"),
                (E.IDF_ERR_NVS_NOT_ENOUGH_SPACE, "NOT_ENOUGH_SPACE")):
    doc_row(f"F2:{_cn}:old", "valid", Cell("W", _c, H.VIS_OLD, H.BOOT_OLD), boot=("VALID", "-"), quick_battery=False)
    doc_row(f"F2:{_cn}:new", "valid", Cell("W", _c, H.VIS_OLD, H.BOOT_NEW), boot=("PROFILE_STALE", "INT"))
    doc_row(f"F2:{_cn}:gone", "valid", Cell("W", _c, H.VIS_ABSENT, H.BOOT_ABSENT), boot=("VALID", "MISS"))
doc_row("F3:ok-other-stale-bytes", "valid", Cell("W", E.IDF_OK, H.VIS_OTHER, other=b"PRIOR"), boot=("VALID", "-"))
doc_row("F3:ok-other-garbage", "valid", Cell("W", E.IDF_OK, H.VIS_OTHER), boot=("VALID", "CORR"))
doc_row("F3:ok-other-then-absent", "valid", Cell("W", E.IDF_OK, H.VIS_OTHER, H.BOOT_ABSENT), boot=("VALID", "MISS"))
doc_row("F4", "valid", None, Cell("P", E.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD), boot=("PROFILE_STALE", "INT"), same_boot=True)
doc_row("F4b:replace-wrong-size", "wsize", None, Cell("P", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), boot=("CORRUPT", "-"), same_boot=True)
doc_row("F4c:replace-corrupt", "corrupt", None, Cell("P", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), boot=("CORRUPT", "-"), same_boot=True)
for _b, _cls in ((H.BOOT_ASIS, ("VALID", "-")), (H.BOOT_OLD, ("PROFILE_STALE", "INT")), (H.BOOT_ABSENT, ("PROFILE_LOST", "-"))):
    doc_row(f"F5:{_b}", "valid", None, Cell("P", E.IDF_ERR_TIMEOUT, H.VIS_NEW, _b), boot=_cls)
for _b, _cls in ((H.BOOT_NEW, ("VALID", "-")), (H.BOOT_ASIS, ("PROFILE_STALE", "INT"))):
    doc_row(f"F6:{_b}", "valid", None, Cell("P", E.IDF_ERR_TIMEOUT, H.VIS_OLD, _b), boot=_cls)
doc_row("F7:n9-old-chunk-erased", "valid", None, Cell("P", E.IDF_ERR_NO_MEM, H.VIS_NOCHUNK_OLD), boot=("PROFILE_LOST", "-"))
doc_row("F8:ok-readback-read-error", "valid", None, Cell("P", E.IDF_OK, H.VIS_CRCBAD), boot=("PROFILE_LOST", "-"))
for _b, _cls in ((H.BOOT_ASIS, ("VALID", "-")), (H.BOOT_OLD, ("PROFILE_STALE", "INT")), (H.BOOT_ABSENT, ("PROFILE_LOST", "-"))):
    doc_row(f"F9:{_b}", "valid", None, Cell("P", E.IDF_OK, H.VIS_NEW, _b), boot=_cls)
doc_row("FH2:page-invalid-between-writes", "valid", Cell("W", E.IDF_OK, H.VIS_NEW, healthy=False), boot=("PROFILE_STALE", "INT"))
doc_row("FH2b:page-invalid-after-fbp", "valid", None, Cell("P", E.IDF_OK, H.VIS_NEW, healthy=False), boot=("VALID", "-"))
doc_row("F-first:fbw-unknown", "first", Cell("W", E.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_NEW), boot=("PROFILE_LOST", "FIRST"))
doc_row("F-first:fbp-prewrite", "first", None, Cell("P", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), boot=("PROFILE_LOST", "FIRST"), same_boot=True)
doc_row("F-lost:fbp-prewrite", "lost", None, Cell("P", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), boot=("PROFILE_LOST", "-"), same_boot=True)


def special_row(name: str, fn):
    reg("faults-doc", f"doc:{name}", fn)


def row_f10_f11_f12() -> Rep:
    """F10 partition wipe, F11 24-bit dedup erase, F12 handle 0 at boot: after a CLEAN committed SAVE, each at the next boot."""
    rep = Rep("F10/F11/F12 next-boot storage events")
    for what, kw, want in (("F10 partition wipe", dict(wipe=True), ("NOT_CAPTURED", "-")),
                           ("F11 dedup erases FBP", dict(absent_keys=("FBP",)), ("PROFILE_LOST", "-")),
                           ("F11 dedup erases FBW", dict(absent_keys=("FBW",)), ("VALID", "MISS")),
                           ("F11 dedup erases both", dict(absent_keys=("FBP", "FBW")), ("NOT_CAPTURED", "-")),
                           ("F12 handle 0 at boot", dict(handle=0), ("UNREADABLE", "PRD"))):
        d = L.make_driver("valid")
        d.save()
        rep.ok(d.b9.startswith("SAVED - "), f"{what}: the SAVE before the event")
        fl_after_save = Flash.of(d.sim.nvs_direct)
        d.reboot(**kw)
        if "handle" not in kw:
            L.boot_invariants(d, rep)
        nv = d.sim.nvs_direct
        if "handle" in kw:
            rep.eq((d.b1, L.parse_b2(d.b2)["why"], L.parse_b2(d.b2)["ld"]), ("UNREADABLE", "PRD", "UNAV"), f"{what}: class")
            rep.eq(nv.sets, [], f"{what}: boot wrote")
            d.review()
            rep.ok(not d.b3.startswith("st=CANDIDATE_READY") and d.b4 == "-", f"{what}: Review must not produce a saveable candidate: {d.b3} / {d.b9}")
            st = d.save()
            rep.eq(st.since.nvs_set_log, [], f"{what}: a SAVE wrote with the storage unavailable")
            st = d.invalidate(target_id="1" * 16)
            rep.eq(st.since.nvs_set_log, [], f"{what}: an INVALIDATE wrote with the storage unavailable")
            rep.ok(d.b9.startswith("INVALIDATE REFUSED - "), f"{what}: {d.b9}")
            d.reboot()                      # the NVS works again: the committed profile reads back
            L.check_booted(d, rep, fl_after_save, table=("VALID", "-"), what=f"{what}: boot after the storage works again")
        else:
            ofl = L.Flash.of(nv)
            L.check_booted(d, rep, ofl, table=want, what=what)
            if want[0] != "UNREADABLE":
                L.follow_up_save(d, rep, ofl, what=f"{what}: operator action")
    return rep


special_row("F10-F12:next-boot-storage-events", row_f10_f11_f12)


def row_f12b() -> Rep:
    """F12b: the handle becomes 0 AFTER the fresh read and BEFORE the commit -> REFUSED (STORAGE_UNAVAILABLE), nothing written, no latch."""
    rep = Rep("F12b handle 0 at the commit")
    d = L.make_driver("valid")
    seen = [0]

    def hook(op, key):
        if op == "stats":
            seen[0] += 1
            if seen[0] == 1:                 # the nvs_healthy() of the fresh read: the handle dies right after it
                d.sim.nvs_direct.handle_value = 0
    d.sim.nvs_direct.before_op = hook
    st = d.save()
    rep.eq(d.b9, "SAVE REFUSED - storage unavailable - nothing saved", "B9")
    rep.eq(st.since.nvs_set_log, [], "a write with the handle at 0")
    rep.eq(st.since.violations_fb(()), [], "audit")
    rep.ok(not d.write_latched and not d.g["fallback_profile_save_unconfirmed"], "a refusal must not latch")
    rep.eq(d.g["fallback_profile_op_in_progress"], False, "released")
    d.sim.nvs_direct.before_op = None
    ofl = L.boot_flash(d.sim.nvs_direct)
    d.reboot()
    L.check_booted(d, rep, ofl, table=("VALID", "-"), what="boot after the refused commit")
    return rep


def row_fh1() -> Rep:
    """F-H1: a page goes INVALID before the commit -> refused, nothing written (both when it is already INVALID at the fresh read and
    when it turns INVALID between the fresh read and the commit); the next boot re-derives the unchanged class."""
    rep = Rep("F-H1 invalid page before the commit")
    # (a) already INVALID when SAVE_FINAL reads: nvs_healthy() false -> the fresh read widens the anomaly latch -> refused
    d = L.make_driver("valid")
    d.unhealthy()
    st = d.save()
    rep.eq(st.since.nvs_set_log, [], "(a) a write with an unhealthy partition")
    rep.ok(d.b9.startswith("SAVE REFUSED - "), f"(a) {d.b9}")
    rep.eq(d.b1, "UNREADABLE", "(a) B1 shows the latch-aware class")
    rep.ok(not d.write_latched and d.g["fallback_profile_op_in_progress"] is False, "(a) a refusal must not latch / hold")
    ofl = L.boot_flash(d.sim.nvs_direct)
    d.reboot()
    L.check_booted(d, rep, ofl, table=("VALID", "-"), what="(a) boot")
    # (b) turns INVALID between the fresh read and the commit: the writer's own health gate refuses
    d = L.make_driver("valid")
    seen = [0]

    def hook(op, key):
        if op == "stats":
            seen[0] += 1
            if seen[0] == 2:                 # the commit's own storage_healthy()
                d.sim.nvs_direct.healthy = False
    d.sim.nvs_direct.before_op = hook
    st = d.save()
    rep.eq(d.b9, "SAVE REFUSED - storage not healthy - nothing saved", "(b) B9")
    rep.eq(st.since.nvs_set_log, [], "(b) a write with an unhealthy partition")
    rep.ok(not d.write_latched, "(b) a refusal must not latch")
    ofl = L.boot_flash(d.sim.nvs_direct)
    d.sim.nvs_direct.before_op = None
    d.reboot()
    L.check_booted(d, rep, ofl, table=("VALID", "-"), what="(b) boot")
    return rep


def row_f13() -> Rep:
    """F13: a second SAVE or INVALIDATE after an UNKNOWN: refused at the gate (overlay) and, with the overlay cleared, by the writer's
    latch; zero writes either way; with the latch cleared but the overlay set, still refused at the gate."""
    rep = Rep("F13 second SAVE / INVALIDATE after an UNKNOWN")
    d = L.make_driver("valid")
    cand = d.candidate()
    d.fault_write("FBW", result=E.IDF_ERR_TIMEOUT, visible=H.VIS_OLD, boot=H.BOOT_OLD)
    d.save()
    rep.eq(d.b1, "SAVE_UNCONFIRMED", "UNKNOWN reached")
    idh = L.HEX(cand["id"])
    # (1) overlay set, latch cleared by hand: the gate alone refuses and nothing is even read
    d.sim.write_latch.write_latched = False
    L.forge_candidate(d, cand)
    reads0 = d.reads_seen
    st = d.save(target_id=idh, confirmation="SAVE " + idh)
    rep.eq(d.b9, L.SAVE_UNKNOWN_TEXT, "(1) gate G9 text")
    rep.eq((d.reads_seen - reads0, st.since.nvs_set_log, len(st.since.nvs_ops)), (0, [], 0), "(1) the gate refused before any read / write")
    # (2) latch set, overlay cleared by hand: the dispatch runs, the writer's own latch refuses (REFUSED_LATCHED), zero sets
    d.sim.write_latch.write_latched = True
    d.set_g("fallback_profile_save_unconfirmed", False)
    L.forge_candidate(d, cand)
    st = d.save(target_id=idh, confirmation="SAVE " + idh)
    rep.eq(d.b9, L.SAVE_UNKNOWN_TEXT, "(2) the writer latch refusal text")
    rep.eq(st.since.nvs_set_log, [], "(2) the writer latch let a second commit through")
    rep.ok(d.write_latched, "(2) the latch stays set")
    # (3) the same for INVALIDATE: latch only
    st = d.invalidate(target_id=L.HEX(Flash.of(d.sim.nvs_direct).b))
    rep.eq(d.b9, L.INV_UNKNOWN_TEXT, "(3) INVALIDATE with the latch only")
    rep.eq(st.since.nvs_set_log, [], "(3) INVALIDATE wrote through the latch")
    # (4) both set (the real state): INVALIDATE refused at I7 with zero NVS operations
    d.set_g("fallback_profile_save_unconfirmed", True)
    st = d.invalidate(target_id=L.HEX(Flash.of(d.sim.nvs_direct).b))
    rep.eq((d.b9, len(st.since.nvs_ops)), (L.INV_UNKNOWN_TEXT, 0), "(4) I7")
    return rep


special_row("F12b:handle-zero-at-commit", row_f12b)
special_row("F-H1:invalid-page-before-commit", row_fh1)
special_row("F13:second-save-after-unknown", row_f13)


# ---------------------------------------------------------------------------
# faults-prior: the representative faults over EVERY prior class
# ---------------------------------------------------------------------------
PRIOR_FAULTS = [
    ("F1", Cell("W", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), None),
    ("F2", Cell("W", E.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_OLD), None),
    ("F2n", Cell("W", E.IDF_ERR_NO_MEM, H.VIS_OLD, H.BOOT_NEW), None),
    ("F4", None, Cell("P", E.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD)),
    ("F6", None, Cell("P", E.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_NEW)),
    ("F9", None, Cell("P", E.IDF_OK, H.VIS_NEW, H.BOOT_OLD)),
]
for _pn in L.PRIORS:
    for _fn, _w, _p in PRIOR_FAULTS:
        reg("faults-prior", f"prior:{_pn}:{_fn}",
            lambda pn=_pn, w=_w, p=_p, fn=_fn: L.txn_row(pn, w, p, label=f"prior:{pn}:{fn}",
                                                         same_boot=(fn in ("F1", "F4", "F9")), battery=True))
for _pn in L.PRIORS:
    reg("faults-prior", f"prior:{_pn}:clean",
        lambda pn=_pn: L.txn_row(pn, None, None, label=f"prior:{pn}:clean", same_boot=True))
# 'reboot after each durable transition': the same outcomes followed by a PLAIN reboot straight away (a COMMITTED outcome for the clean
# run and F9 - the state bit not programmed - and a NOT_COMMITTED outcome for F1 / F4), then the operator action from the booted state
for _pn in L.PRIORS:
    reg("faults-prior", f"prior:{_pn}:clean:plain",
        lambda pn=_pn: L.txn_row(pn, None, None, label=f"prior:{pn}:clean:plain"))
    for _fn, _w, _p in PRIOR_FAULTS:
        if _fn in ("F1", "F4", "F9"):
            reg("faults-prior", f"prior:{_pn}:{_fn}:plain",
                lambda pn=_pn, w=_w, p=_p, fn=_fn: L.txn_row(pn, w, p, label=f"prior:{pn}:{fn}:plain", battery=True))
