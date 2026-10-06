"""FB-B2 durable matrix, part 2: INVALIDATE rows, ANTI-ROLLBACK / generation / witness rows and the long operation SEQUENCES.
(Row machinery and oracles: _fbb2_durable_lib.py; the other families: _fbb2_durable_fam.py.)

Every expectation below is derived from the locked documents (master 3.9 / 4.5 / 4.6 / 4.8 / 5, S2 final 2 / 5.4 / 6, FB_B2_IMPLEMENTATION_NOTES.md section 6)
or from the isolated FB-B0 model (`L.fdo`) over the raw stored bytes, never from what the YAML printed.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fbb2_durable_lib as L  # noqa: E402
from _fbb2_durable_fam import dry, reg  # noqa: E402,F401
from _fbb2_durable_lib import (Cell, D, Flash, H, Rep, fd, fdo, fp, pb, prof, wit)  # noqa: E402

E = fdo
MAXG = 0xFFFFFFFF
G7, B7 = L.G7, L.B7


# ===========================================================================
# INVALIDATE (master 4.8, 5.3): power cuts, faults, the W-INV golden
# ===========================================================================
def inv_intended(fl: Flash):
    """The pair a clean INVALIDATE of the stored VALID profile must write: payload verbatim, generation + 1, flag bit0, re-sealed; the
    witness {hw = g + 1, prior = g / b, op INVALIDATE} (master 4.8)."""
    p_new = fdo.invalidate_profile_cxx(fl.p)
    w_new = fdo.make_provision(p_new["generation"], p_new["binding"], fl.g, fl.b, L.K_P, fp.PROFILE_SCHEMA, L.OP_INV)
    return p_new, w_new


def doc_inv_b9(dt: "L.DocTxn", g_prior: int) -> str:
    """INVALIDATE outcome texts (S2B 4.4 with the master literals; header contract section 5)."""
    if dt.txn == "COMMITTED":
        return (f"INVALIDATED - profile generation {g_prior} is no longer usable (now INVALIDATED g{g_prior + 1}); payload kept for "
                "reference; save a new profile to re-enable")
    if dt.txn == "NOT_COMMITTED":
        if dt.adv:
            return f"INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g{g_prior} is now STALE (unusable)"
        return f"INVALIDATE NOT COMMITTED - storage refused the write ({L.e_txt(dt.w.err)}); profile still VALID g{g_prior}"
    k = dt.w if dt.w.out == "UNKNOWN" else dt.p
    return (f"INVALIDATE OUTCOME UNKNOWN - {L.e_txt(k.err)}/{L.RB_NAMES[k.rb]}; treat the profile as unusable; reboot to re-verify "
            "(Fallback Profile writes locked until reboot)")


def inv_row(wcell=None, pcell=None, *, label: str, expect_boot=None) -> Rep:
    rep = Rep(label)
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    seen0 = L.seen_at_boot(fl0)
    p_new, w_new = inv_intended(fl0)
    cand = d.candidate()
    onvs = L.clone_nvs(nv)
    wcell, pcell = (L.resolve_cell(c, fl0) for c in (wcell, pcell))
    for c in (wcell, pcell):
        if c is not None:
            d.fault_write(L.NAME[c.key], **c.kwargs())
            onvs.faults.setdefault(L.KEY[c.key], []).append(c.fault())
    dt = L.doc_txn(fl0, wcell, pcell)
    orc = L.oracle_commit(onvs, p_new, w_new)
    st = d.invalidate()
    rep.eq(L.TXN_NAMES[orc.outcome], dt.txn, "FB-B0 oracle vs the master 4.3 table")
    sets = [(L.FB_DEC.get(fd.decimal_key(k), k), bytes(b), r) for k, b, r in st.since.nvs_set_log]
    osets = [(L.FB_DEC.get(fd.decimal_key(k), k), bytes(b), r) for k, b, r in orc.nvs.sets]
    L.note_sets(st.since.nvs_set_log)
    rep.eq(sets, osets, "NVS sets vs the oracle")
    rep.eq([s[0] for s in sets], ["FBW", "FBP"][:dt.nsets], "set order / count")
    rep.eq(st.since.violations_fb(tuple(s[0] for s in sets)), [], "write audit")
    rep.eq((st.since.writes, st.since.reads), ([], []), "INVALIDATE issues no Modbus operation at all (master 4.8)")
    rep.eq(d.b9, doc_inv_b9(dt, fl0.g), "B9")
    unknown = dt.txn == "UNKNOWN"
    rep.eq((bool(d.g["fallback_profile_save_unconfirmed"]), d.write_latched), (unknown, unknown), "overlay / latch")
    if unknown:
        rep.eq((d.g["fallback_profile_save_unconfirmed_op"], d.g["fallback_profile_save_unconfirmed_gen"]), (L.OP_INV, fl0.g + 1),
               "unconfirmed op / generation")
    exp_b1 = ("SAVE_UNCONFIRMED" if unknown else "INVALIDATED" if dt.txn == "COMMITTED" else
              "PROFILE_STALE" if dt.adv else "VALID")
    rep.eq(d.b1, exp_b1, "B1")
    rep.eq(L.parse_b2(d.b2)["werr"], L.e_txt(L.doc_werr(dt)), "B2 werr")
    rep.eq(D.idle_invariants(d), [], "idle invariants")
    rep.eq(D.text_invariants(d), [], "text invariants")
    rep.eq(L.image(nv), L.image(orc.nvs), "flash vs the oracle")
    rep.eq((d.g["manual_write_in_progress"], d.g["fallback_profile_op_in_progress"]), (False, False), "INVALIDATE never holds the lock")
    # the RAM mirror: readbacks (COMMITTED) / the pre-transaction values (UNKNOWN) / prior profile + new witness (witness advanced) - PO5
    mir_p, mir_w = bytes(d.arr("fallback_profile_bytes")), bytes(d.arr("fallback_witness_bytes"))
    if dt.txn == "COMMITTED":
        rep.eq((mir_p, mir_w), (fp.pack_profile(p_new), fdo.pack_provision(w_new)), "mirror after COMMITTED")
    elif unknown:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fl0.w_bytes), "mirror after UNKNOWN == the unchanged pre-transaction bytes (PO5)")
    elif dt.adv:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fdo.pack_provision(w_new)), "mirror after NOT_COMMITTED (witness advanced)")
    else:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fl0.w_bytes), "mirror after NOT_COMMITTED")
    seen_inv = max(seen0, fl0.g + 1) if dt.txn == "COMMITTED" or dt.adv else seen0
    rep.eq(d.g["fallback_profile_seen_hw_gen"], seen_inv, "seen_hw_gen after INVALIDATE")
    ofl = L.boot_flash(orc.nvs)
    if expect_boot is not None:
        rep.eq(ofl.cls_why, expect_boot, "next boot: oracle vs the locked table")
    if unknown:
        L.unknown_battery(d, rep, cand=cand, quick=True)
        ofl = L.boot_flash(nv)
    d.reboot()
    L.boot_invariants(d, rep)
    L.check_booted(d, rep, ofl, table=expect_boot, what="plain reboot")
    return rep


def inv_cut_row(point: int) -> Rep:
    ds = _INV_DRY
    n, iw, ip = ds
    stage = "before" if point <= 2 * iw else ("w_only" if point <= 2 * ip else "both")
    table = {"before": ("VALID", "-"), "w_only": ("PROFILE_STALE", "INT"), "both": ("INVALIDATED", "-")}[stage]
    rep = Rep(f"invalidate@nvs-point-{point}")
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    p_new, w_new = inv_intended(fl0)
    nv.events = 0
    nv.cut_at = point
    m = d.mark()
    st = d.invalidate(catch_cut=True)
    rep.eq(st.cut is not None, point < 2 * n, "the power cut fired as expected")
    want = {"before": [], "w_only": ["FBW"], "both": ["FBW", "FBP"]}[stage]
    sets = [(L.FB_DEC.get(fd.decimal_key(k), k), bytes(b)) for k, b, _r in st.since.nvs_set_log]
    L.note_sets(st.since.nvs_set_log)
    intended = {"FBW": fdo.pack_provision(w_new), "FBP": fp.pack_profile(p_new)}
    rep.eq(sets, [(n_, intended[n_]) for n_ in want], "the bytes written are the intended pair")
    rep.eq(st.since.violations_fb(tuple(want), bytes_=intended), [], "write audit")
    rep.eq((st.since.writes, st.since.reads), ([], []), "no Modbus operation")
    ofl = L.boot_flash(nv)
    d.reboot()
    L.boot_invariants(d, rep)
    L.check_booted(d, rep, ofl, table=table, what="reboot")
    # the operator action of the table
    if stage == "before":      # re-issue
        stt = d.invalidate()
        rep.ok(d.b9.startswith("INVALIDATED - "), f"re-issued INVALIDATE: {d.b9}")
        rep.eq(stt.since.violations_fb(("FBW", "FBP")), [], "re-issue audit")
    elif stage == "w_only":    # unusable already (intent honoured): Save a new profile to re-enable
        L.follow_up_save(d, rep, ofl, expect_gen=9, what="Save a new profile")
    else:
        L.follow_up_save(d, rep, ofl, expect_gen=9, what="Save a new profile over INVALIDATED g8")
    return rep


def _inv_dry():
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    nv.events = 0
    n0 = len(nv.ops)
    d.invalidate()
    ops = nv.ops[n0:]
    iw = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == fd.decimal_key(L.K_W))
    ip = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == fd.decimal_key(L.K_P))
    return nv.events, iw, ip


_INV_DRY = _inv_dry()
for _p in range(0, 2 * _INV_DRY[0] + 2):
    reg("invalidate", f"inv:cut:{_p}", lambda p=_p: inv_cut_row(p))
reg("invalidate", "inv:clean", lambda: inv_row(label="inv:clean", expect_boot=("INVALIDATED", "-")))
reg("invalidate", "inv:F1", lambda: inv_row(Cell("W", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD), label="inv:F1", expect_boot=("VALID", "-")))
reg("invalidate", "inv:F2", lambda: inv_row(Cell("W", E.IDF_ERR_NVS_NOT_ENOUGH_SPACE, H.VIS_OLD, H.BOOT_OLD), label="inv:F2",
                                             expect_boot=("VALID", "-")))
reg("invalidate", "inv:F2-new", lambda: inv_row(Cell("W", E.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_NEW), label="inv:F2-new",
                                                 expect_boot=("PROFILE_STALE", "INT")))
reg("invalidate", "inv:F4", lambda: inv_row(None, Cell("P", E.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD), label="inv:F4",
                                             expect_boot=("PROFILE_STALE", "INT")))
reg("invalidate", "inv:F5", lambda: inv_row(None, Cell("P", E.IDF_ERR_TIMEOUT, H.VIS_NEW, H.BOOT_ASIS), label="inv:F5",
                                             expect_boot=("INVALIDATED", "-")))
reg("invalidate", "inv:F6", lambda: inv_row(None, Cell("P", E.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_NEW), label="inv:F6",
                                             expect_boot=("INVALIDATED", "-")))
reg("invalidate", "inv:F9", lambda: inv_row(None, Cell("P", E.IDF_OK, H.VIS_NEW, H.BOOT_OLD), label="inv:F9",
                                             expect_boot=("PROFILE_STALE", "INT")))
reg("invalidate", "inv:FH2", lambda: inv_row(Cell("W", E.IDF_OK, H.VIS_NEW, healthy=False), label="inv:FH2",
                                              expect_boot=("PROFILE_STALE", "INT")))


def row_inv_golden() -> Rep:
    """The W-INV golden vector reproduced by the real INVALIDATE lambda over the golden g7 profile."""
    rep = Rep("W-INV golden")
    d = L.make_driver("valid")
    d.invalidate()
    w, p = d.stored("FBW"), d.stored("FBP")
    rep.eq((w["hw_generation"], w["prior_generation"], w["last_op"], w["hw_tag_key"], w["hw_record_schema"], w["flags"]),
           (8, 7, L.OP_INV, L.K_P, 1, 0), "witness fields (master 4.5 / 4.8)")
    rep.eq((w["hw_binding"], w["prior_binding"], w["binding"]), (0xF49A36C9C9720301, 0xD852A4FA2DF7DBA3, 0x9E8AEC8F7D7DF2D7),
           "W-INV golden binding / hw_binding / prior_binding (master 4.5)")
    rep.eq((p["generation"], p["flags"], p["captured_epoch"], p["reserved0"], p["reserved1"]), (8, 1, L.D.EPOCH0, 0, 0), "FBP fields")
    rep.eq(fp.pack_profile(p)[16 + 2:88], fp.pack_profile(G7)[16 + 2:88], "payload bytes 18..88 verbatim")
    return rep


reg("invalidate", "inv:golden-W-INV", row_inv_golden)


# ===========================================================================
# witness fields: exactly as the locked table, and the W-FIRST golden
# ===========================================================================
def row_witness_fields(prior_name: str) -> Rep:
    pr = L.PRIORS[prior_name]
    rep = Rep(f"witness-fields:{prior_name}")
    d = L.make_driver(pr.seed)
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    d.save(replace_corrupt=pr.rc)
    w, p = d.stored("FBW"), d.stored("FBP")
    rep.ok(w is not None and p is not None, "both records are stored and readable")
    if w is None or p is None:
        return rep
    want = dict(magic=fdo.PROVISION_MAGIC, schema=1, size=48, hw_generation=pr.save_gen, prior_generation=pr.w_prior[0],
                hw_binding=p["binding"], prior_binding=pr.w_prior[1], hw_tag_key=L.K_P, hw_record_schema=fp.PROFILE_SCHEMA,
                last_op=pr.w_op, flags=0)
    for k, v in want.items():
        rep.eq(w[k], v, f"witness {k} (locked table, FB_B2_IMPLEMENTATION_NOTES.md section 6)")
    rep.eq(w["binding"], fdo.provision_binding(w), "the witness is sealed")
    rep.eq(fdo.classify_witness(fp.LOAD_OK, w), fdo.W_VALID, "the witness classifies VALID")
    rep.eq((p["generation"], p["flags"], p["reserved0"], p["reserved1"], p["captured_epoch"]), (pr.save_gen, 0, 0, 0, L.D.EPOCH0),
           "profile fields")
    rep.eq(p["binding"], fp.profile_binding(p), "the profile is sealed")
    rep.eq(fp.classify_profile(fp.LOAD_OK, p), fp.PROFILE_VALID, "the profile classifies VALID")
    ref = prof(pr.save_gen)
    rep.eq(fp.pack_profile(p), fp.pack_profile(ref), "the stored profile is the golden words at that generation, byte for byte")
    rep.eq(fdo.compose_profile_class(fp.LOAD_OK, p, fp.LOAD_OK, w, 0)[:2], (fdo.EPC_VALID, fdo.WHY_NONE), "composes VALID / NONE")
    if prior_name == "first":
        rep.eq((w["binding"], w["hw_binding"]), (0xA8B8788B4C915BB6, 0xB74CE0FA6297474D), "W-FIRST golden (master 4.5)")
    return rep


for _pn in list(L.PRIORS):
    reg("antirollback", f"ar:witness-fields:{_pn}", lambda pn=_pn: row_witness_fields(pn))


# ===========================================================================
# stale-profile resurrection / stale witness / foreign witness / mismatch
# ===========================================================================
def row_resurrect(kind: str) -> Rep:
    rep = Rep(f"resurrect:{kind}")
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    old_p, old_w = bytes(nv.blobs[L.K_P].data), bytes(nv.blobs[L.K_W].data)
    d.save()
    rep.ok(d.b9.startswith("SAVED - "), "the SAVE before the resurrection")
    # power off; the old record re-appears (stale index / rollback)
    if kind == "old-prior":
        nv.put(L.K_P, old_p)
        table, nxt = ("PROFILE_STALE", "INT"), 9
    elif kind == "older-g5":
        nv.put(L.K_P, pb(prof(5)))
        table, nxt = ("PROFILE_STALE", "RBK"), 9
    elif kind == "old-witness":
        nv.put(L.K_W, old_w)
        table, nxt = ("VALID", "LAG"), 9
    elif kind == "old-both":      # NOTE: a full rollback of BOTH records is the one thing no witness can see: it is a consistent old pair
        nv.put(L.K_P, old_p)
        nv.put(L.K_W, old_w)
        table, nxt = ("VALID", "-"), 8
    ofl = L.boot_flash(nv)
    d.reboot()
    L.boot_invariants(d, rep)
    L.check_booted(d, rep, ofl, table=table, what=f"boot with the {kind} record back")
    fl2 = L.follow_up_save(d, rep, ofl, expect_gen=nxt, what="Review + Save", reboot=True)
    if kind != "old-both" and fl2 is not None:
        rep.ok(fl2.g not in (7, 8), f"the new generation {fl2.g} reuses a generation an earlier record already carried")
    return rep


for _k in ("old-prior", "older-g5", "old-witness", "old-both"):
    reg("antirollback", f"ar:resurrect:{_k}", lambda k=_k: row_resurrect(k))


# ===========================================================================
# the same-boot regression guard (R-D4): FBP / FBW vanishing or changing within a boot -> UNREADABLE, Save refused until reboot
# ===========================================================================
TAMPER = {
    "fbp-vanish": lambda d: d.sim.nvs_direct.blobs.pop(L.K_P),
    "fbw-vanish": lambda d: d.sim.nvs_direct.blobs.pop(L.K_W),
    "fbp-older": lambda d: d.sim.nvs_direct.put(L.K_P, pb(prof(5))),
    "fbp-newer": lambda d: d.sim.nvs_direct.put(L.K_P, pb(prof(9))),
    "fbw-changed": lambda d: d.sim.nvs_direct.put(L.K_W, wit(9, 0x9999, 8)),
    "fbp-crc": lambda d: d.sim.nvs_direct.put(L.K_P, bytes(d.sim.nvs_direct.blobs[L.K_P].data), crc_ok=False),
    "fbw-crc": lambda d: d.sim.nvs_direct.put(L.K_W, bytes(d.sim.nvs_direct.blobs[L.K_W].data), crc_ok=False),
    "unhealthy": lambda d: setattr(d.sim.nvs_direct, "healthy", False),
}
GUARD_TEXT_SAVE = "SAVE REFUSED - stored profile read anomaly this boot; reboot to re-derive it first"
GUARD_TEXT_INV = "INVALIDATE REFUSED - stored profile read anomaly this boot; reboot to re-derive first"  # FB-B2 SEM-5: S2 Part B 4.2 wording (SAVE G9a keeps "re-derive it first")


def row_guard(tamper: str, when: str) -> Rep:
    """when = 'before-review': the key changes between boot and Review; 'between': between Review and Save (candidate ready)."""
    rep = Rep(f"guard:{tamper}:{when}")
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    cand = d.candidate()
    TAMPER[tamper](d)
    if when == "before-review":
        d.review()
        rep.ok(d.b3.startswith("st=CANDIDATE_NOT_SAVEABLE"), f"Review after the change must not be saveable: {d.b3}")
        rep.eq(d.b1, "UNREADABLE", "B1 after the change")
        rep.ok(d.b4 == "-", "no candidate ID")
    else:
        st = d.save()
        rep.eq(d.b9, "SAVE REFUSED - stored profile changed since Review; profile unchanged",
               "SAVE after the change: the fresh prior no longer equals the reviewed one (S1 8.5 step 8)")
        rep.eq(st.since.nvs_set_log, [], "SAVE wrote after the key changed under it")
        rep.eq(d.b1, "UNREADABLE", "B1 after the refused SAVE (the latest authoritative read wins)")
        rep.eq(d.g["fallback_profile_op_in_progress"], False, "released")
    rep.ok(d.g["fallback_profile_read_anomaly"] != 0, "the read-anomaly latch is set")
    exp_why = Flash.of(nv).compose(anomaly=d.g["fallback_profile_read_anomaly"])
    rep.eq((CN(exp_why[0]), L.WHY_NAME[exp_why[1]]), ("UNREADABLE", L.parse_b2(d.b2)["why"]), "the class / why the oracle composes under the latch")
    # every further SAVE / INVALIDATE is refused until the reboot, writing and reading nothing
    idh = L.HEX(cand["id"])
    L.forge_candidate(d, cand)
    reads0 = d.reads_seen
    st = d.save(target_id=idh, confirmation="SAVE " + idh)
    rep.eq(d.b9, GUARD_TEXT_SAVE, "G9a text")
    rep.eq((st.since.nvs_set_log, len(st.since.nvs_ops), d.reads_seen - reads0), ([], 0, 0), "G9a refused before anything was read or written")
    st = d.invalidate(target_id=L.HEX(Flash.of(nv).b) if Flash.of(nv).p_load == fp.LOAD_OK else "1" * 16)
    rep.eq(d.b9, GUARD_TEXT_INV, "I6 text")
    rep.eq((st.since.nvs_set_log, len(st.since.nvs_ops)), ([], 0), "I6 refused before anything was read or written")
    # only a reboot re-derives
    ofl = L.boot_flash(nv)
    d.reboot()
    L.boot_invariants(d, rep)
    L.check_booted(d, rep, ofl, what="reboot re-derives")
    if ofl.cls_why[0] != "UNREADABLE":
        L.follow_up_save(d, rep, ofl, what="Review + Save after the reboot")
    return rep


def CN(n):
    return L.CLS_NAME[n]


for _t in TAMPER:
    for _w in ("before-review", "between"):
        reg("antirollback", f"ar:guard:{_t}:{_w}", lambda t=_t, w=_w: row_guard(t, w))


def row_guard_readerr_then_absent() -> Rep:
    """T-CAP-20: boot VALID g7; runtime FBP READ_ERROR (CRC) then, after the read erased the chunk, ABSENT -> UNREADABLE (ANOM) both times,
    SAVE refused both times; after the reboot PROFILE_LOST -> g8."""
    rep = Rep("guard:runtime-read-error-then-absent")
    d = L.make_driver("valid")
    nv = d.sim.nvs_direct
    nv.put(L.K_P, bytes(nv.blobs[L.K_P].data), crc_ok=False)
    for i in range(3):         # read 1: CRC error (chunk erased by the read); read 2: probe ok, data ESP_FAIL (index erased); read 3: ABSENT
        d.review()
        rep.ok(d.b3.startswith("st=CANDIDATE_NOT_SAVEABLE") and d.b1 == "UNREADABLE", f"Review #{i + 1}: {d.b1} {d.b3}")
        st = d.save()
        rep.eq(st.since.nvs_set_log, [], f"SAVE #{i + 1} wrote")
    rep.eq(L.parse_b2(d.b2)["ld"] in ("ABS", "RERR"), True, "the same boot saw the key disappear")
    ofl = L.boot_flash(nv)
    d.reboot()
    L.check_booted(d, rep, ofl, table=("PROFILE_LOST", "-"), what="reboot after the CRC self-heal")
    L.follow_up_save(d, rep, ofl, expect_gen=8, what="Review + Save")
    return rep


reg("antirollback", "ar:guard:runtime-read-error-then-absent", row_guard_readerr_then_absent)


# ===========================================================================
# seen_hw_gen floor and the high-water / wrap boundaries
# ===========================================================================
def inject_seen(d, v):
    d.set_g("fallback_profile_seen_hw_gen", v)


def row_seen_save(seen: int, want_gen: int) -> Rep:
    """MB34: a same-boot SAVE must not reuse a generation <= the boot's high-water mark (seen_hw_gen), even above the stored g and hw."""
    rep = Rep(f"seen-floor:save:{seen}")
    d = L.make_driver("valid")
    inject_seen(d, seen)
    d.review()
    st = d.save()
    rep.eq(d.b9, f"SAVED - known-good profile generation {want_gen} saved (verified this boot)", "B9")
    w, p = d.stored("FBW"), d.stored("FBP")
    rep.eq((p["generation"], w["hw_generation"], w["prior_generation"], w["prior_binding"], w["hw_binding"]), (want_gen, want_gen, 7, B7, p["binding"]),
           "stored pair")
    rep.eq(st.since.violations_fb(("FBW", "FBP")), [], "audit")
    L.note_sets(st.since.nvs_set_log)
    ofl = L.boot_flash(d.sim.nvs_direct)
    d.reboot()
    L.check_booted(d, rep, ofl, table=("VALID", "-"), what="reboot")
    L.follow_up_save(d, rep, ofl, expect_gen=want_gen + 1, what="next SAVE")
    return rep


def row_seen_invalidate(seen: int, permitted: bool) -> Rep:
    """INVALIDATE needs g + 1 > max(hw, seen_hw_gen) (master 3.9 / 4.8): refused at the gate (nothing read) when it does not hold."""
    rep = Rep(f"seen-floor:invalidate:{seen}")
    d = L.make_driver("valid")
    inject_seen(d, seen)
    st = d.invalidate()
    if permitted:
        rep.ok(d.b9.startswith("INVALIDATED - "), f"INVALIDATE with seen {seen}: {d.b9}")
        rep.eq(st.since.violations_fb(("FBW", "FBP")), [], "audit")
    else:
        rep.eq(d.b9, "INVALIDATE REFUSED - profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
               "I10 text (header contract section 5)")
        rep.eq((st.since.nvs_set_log, len(st.since.nvs_ops)), ([], 0), "refused at the gate: nothing read, nothing written")
    return rep


for _seen, _want in ((0, 8), (7, 8), (8, 9), (50, 51), (0xFFFFFFFD, 0xFFFFFFFE)):
    reg("antirollback", f"ar:seen-floor:save:{_seen:x}", lambda s=_seen, w=_want: row_seen_save(s, w))
for _seen, _perm in ((0, True), (7, True), (8, False), (50, False), (0xFFFFFFFF, False)):
    reg("antirollback", f"ar:seen-floor:invalidate:{_seen:x}", lambda s=_seen, p=_perm: row_seen_invalidate(s, p))

EXH_SAVE = "SAVE REFUSED - profile generation counter exhausted; profile unchanged"
EXH_INV = "INVALIDATE REFUSED - generation counter exhausted"


def row_wrap_boundary() -> Rep:
    """g = 0xFFFFFFFE: SAVE -> 0xFFFFFFFF (ok). Then g = 0xFFFFFFFF: SAVE refused 'exhausted', INVALIDATE refused (documented dead end)."""
    rep = Rep("wrap:FFFFFFFE-then-FFFFFFFF")
    p = prof(0xFFFFFFFE)
    d = L.make_driver({"fbp": p, "fbw": wit(0xFFFFFFFE, p["binding"], 0xFFFFFFFD)})
    d.save()
    rep.eq(d.b9, "SAVED - known-good profile generation 4294967295 saved (verified this boot)", "SAVE at 0xFFFFFFFE")
    w = d.stored("FBW")
    rep.eq((w["hw_generation"], w["prior_generation"], w["last_op"]), (MAXG, 0xFFFFFFFE, L.OP_SAVE), "witness at the maximum")
    ofl = L.boot_flash(d.sim.nvs_direct)
    d.reboot()
    L.check_booted(d, rep, ofl, table=("VALID", "-"), what="reboot at g = 0xFFFFFFFF")
    rep.eq(L.parse_b2(d.b2)["g"], str(MAXG), "B2 g")
    d.review()
    st = d.save()
    rep.eq(d.b9, EXH_SAVE, "SAVE at g = 0xFFFFFFFF")
    rep.eq(st.since.nvs_set_log, [], "SAVE wrote at the maximum generation")
    st = d.invalidate()
    rep.eq(d.b9, EXH_INV, "INVALIDATE at g = 0xFFFFFFFF")
    rep.eq((st.since.nvs_set_log, len(st.since.nvs_ops)), ([], 0), "INVALIDATE refused at the gate")
    return rep


def row_wrap_seed(name: str, seed, why: str) -> Rep:
    rep = Rep(f"wrap:{name}")
    d = L.make_driver(seed)
    st = d.save()
    rep.eq(d.b9, EXH_SAVE, f"SAVE refused ({why})")
    rep.eq(st.since.nvs_set_log, [], "SAVE wrote")
    st = d.invalidate(target_id=L.HEX(Flash.of(d.sim.nvs_direct).b) if Flash.of(d.sim.nvs_direct).p_load == fp.LOAD_OK else "1" * 16)
    rep.ok(d.b9.startswith("INVALIDATE REFUSED - "), f"INVALIDATE refused: {d.b9}")
    rep.eq(st.since.nvs_set_log, [], "INVALIDATE wrote")
    return rep


reg("antirollback", "ar:wrap:FFFFFFFE-then-FFFFFFFF", row_wrap_boundary)
_pmax = prof(MAXG)
reg("antirollback", "ar:wrap:g-max", lambda: row_wrap_seed("g-max", {"fbp": _pmax, "fbw": wit(MAXG, _pmax["binding"], 0xFFFFFFFE)}, "g = 0xFFFFFFFF"))
reg("antirollback", "ar:wrap:hw-max-profile-below",
    lambda: row_wrap_seed("hw-max", {"fbp": G7, "fbw": wit(MAXG, 0x1234, 0xFFFFFFFE)}, "hw = 0xFFFFFFFF"))
reg("antirollback", "ar:wrap:hw-max-profile-lost", lambda: row_wrap_seed("hw-max-lost", {"fbw": wit(MAXG, 0x1234, 0xFFFFFFFE)}, "lost, hw = 0xFFFFFFFF"))


def row_wrap_seen_max() -> Rep:
    rep = Rep("wrap:seen-max")
    d = L.make_driver("valid")
    inject_seen(d, MAXG)
    st = d.save()
    rep.eq((d.b9, st.since.nvs_set_log), (EXH_SAVE, []), "SAVE with base 0xFFFFFFFF from the high-water mark")
    st = d.invalidate()
    rep.eq(st.since.nvs_set_log, [], "INVALIDATE wrote")
    return rep


def row_wrap_invalidate_fffffffe() -> Rep:
    rep = Rep("wrap:invalidate-at-FFFFFFFE")
    p = prof(0xFFFFFFFE)
    d = L.make_driver({"fbp": p, "fbw": wit(0xFFFFFFFE, p["binding"], 0xFFFFFFFD)})
    d.invalidate()
    rep.ok(d.b9.startswith("INVALIDATED - profile generation 4294967294 "), d.b9)
    pp = d.stored("FBP")
    rep.eq((pp["generation"], pp["flags"]), (MAXG, 1), "INVALIDATED g 0xFFFFFFFF")
    return rep


reg("antirollback", "ar:wrap:seen-max", row_wrap_seen_max)
reg("antirollback", "ar:wrap:invalidate-at-FFFFFFFE", row_wrap_invalidate_fffffffe)


# ===========================================================================
# the second extra priors: foreign witness schema, REPLACE CORRUPT phrase discipline
# ===========================================================================
def _extra_priors():
    t = [
        L.Prior("stale_sup_schema", {"fbp": G7, "fbw": wit(7, B7, 6, schema=2)}, ("PROFILE_STALE", "SUP"), 8, L.OP_SAVE, (7, B7),
                ("PROFILE_STALE", "SUP"), ("PROFILE_STALE", "INT"), 9, note="foreign hw_record_schema (B9)"),
    ]
    for p in t:
        L.PRIORS[p.name] = p


_extra_priors()
reg("antirollback", "ar:foreign-schema:clean", lambda: L.txn_row("stale_sup_schema", label="ar:foreign-schema:clean", same_boot=True))
reg("antirollback", "ar:foreign-schema:clean-reboot", lambda: L.txn_row("stale_sup_schema", label="ar:foreign-schema:clean-reboot"))


def row_replace_phrase(prior_name: str) -> Rep:
    """REPLACE CORRUPT only with its phrase (MB36): the plain `SAVE <id>` is refused at G7 (expected phrase echoed), zero reads / writes; the
    phrase on a NON-corrupt prior is refused too."""
    rep = Rep(f"replace-phrase:{prior_name}")
    pr = L.PRIORS[prior_name]
    d = L.make_driver(pr.seed)
    idh = d.b4
    st = d.save(confirmation=f"SAVE {idh}")
    rep.eq(d.b9, f"SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE {idh} REPLACE CORRUPT')", "plain phrase over CORRUPT")
    rep.eq((st.since.nvs_set_log, st.since.reads), ([], []), "refused with zero reads / writes")
    # the refusal consumed the candidate: Review again, then the right phrase commits as REPLACE_CORRUPT
    d.review(expect="CANDIDATE_READY")
    st = d.save(replace_corrupt=True)
    rep.ok(d.b9.startswith("SAVED - "), d.b9)
    rep.eq(d.stored("FBW")["last_op"], L.OP_RC, "witness op REPLACE_CORRUPT")
    d2 = L.make_driver("valid")
    idh = d2.b4
    st = d2.save(confirmation=f"SAVE {idh} REPLACE CORRUPT")
    rep.eq(d2.b9, f"SAVE REFUSED - confirmation phrase mismatch (expected 'SAVE {idh}')", "REPLACE CORRUPT phrase over a VALID prior")
    rep.eq(st.since.nvs_set_log, [], "refused with zero writes")
    return rep


for _pn in ("corrupt", "wsize", "corrupt_nw"):
    reg("antirollback", f"ar:replace-phrase:{_pn}", lambda pn=_pn: row_replace_phrase(pn))


# ===========================================================================
# the generation formula and the class permissions TYPED FROM THE DOCUMENTS (master 3.9 / 4.6 / 4.8; FB_B2_IMPLEMENTATION_NOTES.md section 6), judged against
# the shared FB-B0 model the harness executes (so a mutant of it cannot hide behind a redundant caller-side fold) and against the
# Python mirror's plan_save (the planner the YAML calls)
# ===========================================================================
import fallback_save as _fsmod  # noqa: E402

AUTH_CLASSES = (fp.PROFILE_VALID, fp.PROFILE_INVALIDATED, fp.PROFILE_CORRUPT_DOMAIN)       # the three AUTHENTIC FB-A classes
GRID_G = (0, 1, 7, 8, 0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF)
SAVE_PERMITTED = ("NOT_CAPTURED", "VALID", "INVALIDATED", "CORRUPT_DOMAIN", "PROFILE_LOST", "PROFILE_STALE", "CORRUPT")   # M 4.6; UNREADABLE and SAVE_UNCONFIRMED never


def doc_base(auth: bool, g: int, wvalid: bool, hw: int, seen: int) -> int:
    """master 3.9: base = max(authentic ? g : 0, witness VALID ? hw : 0, seen_hw_gen); the new generation is base + 1."""
    return max(g if auth else 0, hw if wvalid else 0, seen)


def doc_invalidate_ok(g: int, wvalid: bool, hw: int, seen: int) -> bool:
    """master 4.8 I10: g < 0xFFFFFFFF and g + 1 > max(hw if the witness is VALID, seen_hw_gen)."""
    return g != MAXG and g + 1 > (hw if wvalid else 0) and g + 1 > seen


class _Tally:
    def __init__(self, rep: Rep, what: str):
        self.rep, self.what, self.n, self.nbad, self.bad = rep, what, 0, 0, []

    def eq(self, got, want, ctx) -> None:
        self.n += 1
        if got != want:
            self.nbad += 1
            if len(self.bad) < 3:
                self.bad.append(f"{ctx}: got {got!r} want {want!r}")

    def done(self) -> None:
        self.rep.asserts += self.n - 1        # (Rep.ok below counts one)
        self.rep.ok(self.nbad == 0, f"{self.what}: {self.nbad} of {self.n} evaluations differ; first: {' | '.join(self.bad)}")


def row_model_formula() -> Rep:
    rep = Rep("model:generation-formula-and-class-permissions")
    t = _Tally(rep, "save_generation_base / next_seen_hw_gen / invalidate_generation_permitted over the 6 FB-A classes x 4 witness classes x 7^3 values")
    for c in range(6):
        auth = c in AUTH_CLASSES
        for wc in (fdo.W_UNREADABLE, fdo.W_ABSENT, fdo.W_CORRUPT, fdo.W_VALID):
            wv = wc == fdo.W_VALID
            for g in GRID_G:
                for hw in GRID_G:
                    for seen in GRID_G:
                        want = doc_base(auth, g, wv, hw, seen)
                        ctx = f"class {c} witness {wc} g {g:#x} hw {hw:#x} seen {seen:#x}"
                        t.eq(fd.save_generation_base(c, g, wc, hw, seen), want, "base " + ctx)
                        t.eq(fdo.save_generation_base(c, g, wc, hw, seen), want, "oracle base " + ctx)
                        t.eq(fd.next_seen_hw_gen(seen, c, g, wc, hw), want, "seen floor " + ctx)
                        t.eq(fd.save_generation_available(want), want != MAXG, "available " + ctx)
                        if c == fp.PROFILE_VALID:
                            t.eq(fd.invalidate_generation_permitted(g, wc, hw, seen), doc_invalidate_ok(g, wv, hw, seen), "I10 " + ctx)
    t.done()
    t = _Tally(rep, "class permissions of the FB-B0 model")
    for epc, name in fdo.EPC_NAMES.items():
        t.eq(fd.save_class_permitted(epc), name in SAVE_PERMITTED, f"save_class_permitted({name})")
        t.eq(fd.save_requires_replace_phrase(epc), name == "CORRUPT", f"save_requires_replace_phrase({name})")
        t.eq(fd.invalidate_class_permitted(epc), name == "VALID", f"invalidate_class_permitted({name})")
    t.done()
    return rep


def row_mirror_plan_save() -> Rep:
    """The Python mirror's plan_save (the planner the YAML calls) judged gate by gate against the document: every refusal reason, the
    class permission, the generation formula and the witness fields of the pair it builds."""
    rep = Rep("mirror:plan_save-gates-and-formula")
    fs = L._ENV["fbsave"] or _fsmod
    words = list(L.make_driver("valid").candidate()["words"])
    base = dict(p_load=fp.LOAD_OK, p=G7, p_stored_len=fp.PROFILE_SIZE, w_load=fp.LOAD_OK, w=wit(7, B7, 6), w_stored_len=fdo.PROVISION_SIZE,
                cls=fdo.EPC_VALID, why=0, read_anomaly=0, unconfirmed=False, seen_hw_gen=7, cand_prior_class=fdo.EPC_VALID, cand_prior_gen=7,
                cand_prior_binding=B7, replace_corrupt=False, words=words, captured_epoch=L.D.EPOCH0)

    def plan(**ov):
        return fs.plan_save(fs.SavePlanInputs(**{**base, **ov}))
    r = plan()
    rep.eq((r.code, r.generation, r.op), (fs.PLAN_OK, 8, L.OP_SAVE), "the clean plan over VALID g7 / hw 7")
    rep.eq((r.w_new["hw_generation"], r.w_new["prior_generation"], r.w_new["prior_binding"], r.w_new["hw_binding"], r.w_new["last_op"]),
           (8, 7, B7, r.p_new["binding"], L.OP_SAVE), "the planned witness (locked table: hw g+1, prior = the replaced profile)")
    rep.eq((r.p_new["generation"], r.p_new["flags"], r.p_new["captured_epoch"]), (8, 0, L.D.EPOCH0), "the planned profile")
    for what, ov, code in (
            ("the SAVE_UNCONFIRMED overlay", dict(unconfirmed=True), fs.PLAN_UNCONFIRMED),
            ("a read anomaly", dict(read_anomaly=1), fs.PLAN_ANOMALY),
            ("no trusted clock", dict(captured_epoch=0), fs.PLAN_CLOCK),
            ("a changed prior (generation)", dict(cand_prior_gen=6), fs.PLAN_PRIOR_CHANGED),
            ("a changed prior (binding)", dict(cand_prior_binding=B7 ^ 1), fs.PLAN_PRIOR_CHANGED),
            ("a changed prior (class)", dict(cand_prior_class=fdo.EPC_INVALIDATED), fs.PLAN_PRIOR_CHANGED),
            ("REPLACE CORRUPT over a VALID prior", dict(replace_corrupt=True), fs.PLAN_CONTEXT),
            ("the generation counter exhausted (seen_hw_gen 0xFFFFFFFF)", dict(seen_hw_gen=MAXG), fs.PLAN_GENERATION)):
        rep.eq(plan(**ov).code, code, f"plan_save refuses {what}")
    for epc, name in fdo.EPC_NAMES.items():
        code = plan(cls=epc, cand_prior_class=epc).code
        if name in ("UNREADABLE", "SAVE_UNCONFIRMED"):
            rep.eq(code, fs.PLAN_CLASS, f"plan_save over the never-saveable class {name}")
        else:
            rep.ok(code != fs.PLAN_CLASS, f"plan_save refuses the permitted class {name} as a class error")
    for seen, wit_hw in ((0, 7), (7, 7), (9, 7), (0, 12), (0xFFFFFFFD, 7)):
        r = plan(seen_hw_gen=seen, w=wit(wit_hw, 0x1234, 6))
        want = doc_base(True, 7, True, wit_hw, seen) + 1
        rep.eq((r.code, r.generation), (fs.PLAN_OK, want), f"plan_save generation with seen {seen:#x} / witness hw {wit_hw}")
    return rep


reg("antirollback", "ar:model:formula", row_model_formula)
reg("antirollback", "ar:mirror:plan_save", row_mirror_plan_save)


# ===========================================================================
# sequences: generations strictly increase over long operation sequences
# ===========================================================================
SEQ_STEPS = ("save", "invalidate", "reboot", "lose", "rollback", "wcorrupt", "wgone", "pcorrupt", "pwrong", "wipe", "witness-lag")


def run_sequence(label: str, seed, steps: list) -> Rep:
    rep = Rep(label)
    d = L.make_driver(seed, review=False)
    nv = d.sim.nvs_direct
    fl = Flash.of(nv)
    high = max(fl.g if fl.authentic else 0, fl.hw)        # the highest generation / high-water anything ever carried in this lineage
    seen = L.seen_at_boot(fl)
    images: list = []
    if K_P_in(nv):
        images.append(bytes(nv.blobs[L.K_P].data))
    committed: list = []

    def anchored(f: Flash) -> bool:
        return f.authentic or f.hw > 0

    for i, step in enumerate(steps):
        tag = f"step {i} {step}"
        fl = Flash.of(nv)
        cls = fl.cls_why[0]
        if step == "save":
            if cls in ("UNREADABLE",):
                continue
            rc = cls == "CORRUPT"
            gen = L.formula_gen(fl, seen)
            d.review()
            if not rep.ok(d.b3.startswith("st=CANDIDATE_READY"), f"{tag}: no saveable candidate in class {cls}: {d.b3} / {d.b9}"):
                return rep
            st = d.save(replace_corrupt=rc)
            if not rep.eq(d.b9, f"SAVED - known-good profile generation {gen} saved (verified this boot)", f"{tag}: B9"):
                return rep
            L.note_sets(st.since.nvs_set_log)
            p_i, w_i = L.intended_pair(fl, gen, rc)
            rep.eq(st.since.violations_fb(("FBW", "FBP"), bytes_={"FBW": fdo.pack_provision(w_i), "FBP": fp.pack_profile(p_i)}), [],
                   f"{tag}: audit + the exact intended pair (witness prior_* / op per the locked table)")
            if anchored(fl):
                rep.ok(gen > high, f"{tag}: generation {gen} does not exceed everything the lineage already carried ({high})")
            high = max(high, gen) if anchored(fl) else gen
            seen = max(seen, gen)
            f2 = Flash.of(nv)
            rep.eq((f2.g, f2.hw, f2.cls_why), (gen, gen, ("VALID", "-")), f"{tag}: stored pair")
            images.append(bytes(nv.blobs[L.K_P].data))
            committed.append(gen)
        elif step == "invalidate":
            if cls != "VALID":
                continue
            gen = fl.g + 1
            st = d.invalidate()
            if gen > max(fl.hw, seen):
                rep.ok(d.b9.startswith("INVALIDATED - "), f"{tag}: {d.b9}")
                L.note_sets(st.since.nvs_set_log)
                p_i, w_i = inv_intended(fl)
                rep.eq(st.since.violations_fb(("FBW", "FBP"), bytes_={"FBW": fdo.pack_provision(w_i), "FBP": fp.pack_profile(p_i)}), [],
                       f"{tag}: audit + the exact intended INVALIDATE pair")
                rep.ok(gen > high, f"{tag}: invalidated generation {gen} does not exceed {high}")
                high = max(high, gen)
                seen = max(seen, gen)
                f2 = Flash.of(nv)
                rep.eq((f2.g, f2.hw, f2.cls_why), (gen, gen, ("INVALIDATED", "-")), f"{tag}: stored pair")
                images.append(bytes(nv.blobs[L.K_P].data))
                committed.append(gen)
            else:
                rep.eq(st.since.nvs_set_log, [], f"{tag}: refused INVALIDATE wrote")
        else:
            # power is off: tamper with the stored records, then boot
            if step == "reboot":
                pass
            elif step == "lose":
                nv.blobs.pop(L.K_P, None)
            elif step == "rollback":
                older = [im for im in images if im != bytes(nv.blobs[L.K_P].data)] if L.K_P in nv.blobs else []
                if older:
                    nv.put(L.K_P, older[0])
            elif step == "wcorrupt":
                nv.put(L.K_W, bytes(range(48)))
            elif step == "wgone":
                nv.blobs.pop(L.K_W, None)
            elif step == "pcorrupt":
                nv.put(L.K_P, bytes(range(96)))
            elif step == "pwrong":
                nv.put(L.K_P, bytes(40))
            elif step == "witness-lag":
                if L.K_W in nv.blobs and Flash.of(nv).authentic and Flash.of(nv).g > 1:
                    nv.put(L.K_W, wit(Flash.of(nv).g - 1, 0x4242, 0 if Flash.of(nv).g == 2 else Flash.of(nv).g - 2, 0x4343))
            elif step == "wipe":
                pass
            before = Flash.of(nv)
            ofl = L.boot_flash(nv)
            if step == "wipe":
                d.reboot(wipe=True)
                nv = d.sim.nvs_direct
                high, seen, images = 0, 0, []
                ofl = Flash.of(nv)
            else:
                d.reboot()
                nv = d.sim.nvs_direct
            L.boot_invariants(d, rep)
            L.check_booted(d, rep, ofl, what=f"{tag}: boot")
            fl2 = Flash.of(nv)
            seen = L.seen_at_boot(fl2)
            cur_high = max(fl2.g if fl2.authentic else 0, fl2.hw)
            # The scheme's guarantee: while AT LEAST ONE stored record still carries the highest generation, no generation is reused.
            # (Two independent faults that destroy both records - e.g. witness gone AND profile rolled back - leave no evidence at all;
            # that is the documented partition-wipe class, master 4.11 / F10: HA-side detection only.)
            if cur_high < high and step != "wipe":
                rep.ok(False, f"{tag}: the highest generation {high} left no evidence in either record (only {cur_high}): the sequence "
                              "applied two faults between commits (a test-generator bug, not a firmware result)")
                high = cur_high
    return rep


def K_P_in(nv) -> bool:
    return L.K_P in nv.blobs


SCRIPTED = {
    "save-invalidate-save-reboot": ("first", ["save", "invalidate", "save", "reboot", "save", "reboot", "save"]),
    "loss-then-save": ("valid", ["save", "lose", "save", "save", "reboot", "save"]),
    "stale-then-save": ("valid", ["save", "rollback", "save", "rollback", "save", "reboot", "save"]),
    "replace-corrupt-chain": ("valid", ["save", "pcorrupt", "save", "save", "pwrong", "save", "invalidate", "save"]),
    "witness-trouble": ("valid", ["save", "wgone", "save", "wcorrupt", "save", "witness-lag", "save", "invalidate", "save"]),
    "recapture-loss-save": ("valid", ["save", "invalidate", "save", "reboot", "save", "lose", "save", "lose", "save", "wgone", "save"]),
    "wipe-restarts-the-count": ("valid", ["save", "save", "wipe", "save", "save", "invalidate", "save"]),
    "interrupted-resurrect": ("lost", ["save", "rollback", "save", "rollback", "rollback", "save", "invalidate", "save", "lose", "save"]),
}
for _n, (_seed, _steps) in SCRIPTED.items():
    reg("sequences", f"seq:scripted:{_n}", lambda n=_n, s=_seed, st=_steps: run_sequence(f"seq:{n}", L.PRIORS[s].seed, st))


TAMPERS = ("lose", "rollback", "wcorrupt", "wgone", "pcorrupt", "pwrong", "witness-lag")


def random_steps(seed: int, n: int = 14) -> list:
    """A seeded random operation sequence. It starts with a SAVE (so both records carry the lineage's highest generation) and never applies
    two storage faults between two commits (single-fault model: the witness protects against ONE lost / rolled-back record)."""
    rng = random.Random(seed)
    weights = [("save", 34), ("invalidate", 9), ("reboot", 10), ("lose", 8), ("rollback", 9), ("wcorrupt", 5), ("wgone", 5), ("pcorrupt", 5),
               ("pwrong", 3), ("witness-lag", 5), ("wipe", 2)]
    pool = [s for s, w in weights for _ in range(w)]
    steps = ["save"]
    tampered = False
    while len(steps) < n:
        s = rng.choice(pool)
        if s in TAMPERS:
            if tampered:
                s = "save"
            tampered = True if s in TAMPERS else tampered
        if s in ("save", "wipe"):          # (an INVALIDATE is skipped when the class is not VALID: it is not a guaranteed commit)
            tampered = False
        steps.append(s)
    return steps


RANDOM_SEEDS = list(range(1, 25))
RANDOM_PRIORS = ["valid", "first", "lost", "stale_int", "lag", "invalidated"]
for _s in RANDOM_SEEDS:
    _pn = RANDOM_PRIORS[_s % len(RANDOM_PRIORS)]
    reg("sequences", f"seq:random:{_s}", lambda s=_s, pn=_pn: run_sequence(f"seq:random:{s}:{pn}", L.PRIORS[pn].seed, random_steps(s)))
