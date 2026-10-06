"""FB-B2 durable matrix: the MUTANTS (a kill matrix). Each mutant is a deliberately broken copy of the thing under test - the real
firmware YAML text, the Python mirror of ecco_fallback_save.h / ecco_fallback_capture.h used by the harness, or the FB-B0 durable model
the harness executes - and each is KILLED by named rows of the durable matrix (the same rows the families run, see _fbb2_durable_fam.py /
_fbb2_durable_ar.py): the mutant is active while those rows run and at least one of them must report a violation.

A mutant that no row can tell from the original is an EQUIVALENT mutant (a redundant defence layer) and is not in this table; the report
lists the layers that are redundant by design (e.g. the generation base's `hw` term is also folded into seen_hw_gen by every read).

Never edits a file: YAML edits act on an in-memory copy of the text, mirror edits on an in-memory module, model edits patch attributes of
the shared `fallback_durable` module for the duration of the mutant (restored in a finally).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fbb2_durable_lib as L  # noqa: E402
import _fbb2_durable_fam as F  # noqa: E402
import _fbb2_durable_ar as A  # noqa: E402,F401
from _fbb2_durable_lib import D, fd, fdo, fp  # noqa: E402


# ---------------------------------------------------------------------------
# model patches (functions installed over fd.<name>)
# ---------------------------------------------------------------------------
def _fresh_result():
    r = fd.TxnResult()
    r.w.outcome = fd.KEY_NOT_ATTEMPTED
    r.p.outcome = fd.KEY_NOT_ATTEMPTED
    return r


def make_commit(variant: str):
    """A copy of fd.commit_transition with ONE flaw."""
    def commit(nvs, latch, w_new, w_prior, w_pd, p_new, p_prior, p_pd):
        r = _fresh_result()
        if variant != "ignore_latch" and latch.write_latched:
            r.refusal = fd.REFUSAL_LATCHED
            return fd.TXN_REFUSED_LATCHED, r
        if not fd.validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd):
            r.refusal = fd.REFUSAL_INVALID_TRANSITION
            return fd.TXN_REFUSED_LATCHED, r
        if variant != "ignore_handle" and nvs.handle() == 0:
            r.refusal = fd.REFUSAL_STORAGE_UNAVAILABLE
            return fd.TXN_REFUSED_LATCHED, r
        if variant != "ignore_health" and not fd.storage_healthy(nvs):
            r.refusal = fd.REFUSAL_STORAGE_UNHEALTHY
            return fd.TXN_REFUSED_LATCHED, r
        r.refusal = fd.REFUSAL_NONE
        if variant == "fbp_first":                       # MB22: the profile is written BEFORE the witness
            op, r.p_rb = fd.write_one(nvs, latch, fd.FALLBACK_PROFILE_KEY, fd._pbytes(p_new), fd._pbytes(p_prior), p_pd[0], p_pd[1], r.p)
            if op != fd.KEY_COMMITTED:
                return (fd.TXN_NOT_COMMITTED if op == fd.KEY_NOT_COMMITTED else fd.TXN_UNKNOWN_REBOOT), r
            ow, r.w_rb = fd.write_one(nvs, latch, fd.FAILBACK_PROVISION_KEY, fd._wbytes(w_new), fd._wbytes(w_prior), w_pd[0], w_pd[1], r.w)
            return (fd.TXN_COMMITTED if ow == fd.KEY_COMMITTED else fd.TXN_UNKNOWN_REBOOT), r
        ow, r.w_rb = fd.write_one(nvs, latch, fd.FAILBACK_PROVISION_KEY, fd._wbytes(w_new), fd._wbytes(w_prior), w_pd[0], w_pd[1], r.w)
        if ow == fd.KEY_NOT_COMMITTED and variant != "fbp_after_w_not_committed":
            return fd.TXN_NOT_COMMITTED, r
        if ow == fd.KEY_UNKNOWN_REBOOT and variant == "fbp_after_w_unknown":
            pass
        elif ow != fd.KEY_COMMITTED and ow != fd.KEY_NOT_COMMITTED:
            return fd.TXN_UNKNOWN_REBOOT, r
        op, r.p_rb = fd.write_one(nvs, latch, fd.FALLBACK_PROFILE_KEY, fd._pbytes(p_new), fd._pbytes(p_prior), p_pd[0], p_pd[1], r.p)
        if op == fd.KEY_COMMITTED:
            return fd.TXN_COMMITTED, r
        if op == fd.KEY_NOT_COMMITTED:
            r.witness_advanced = True
            return fd.TXN_NOT_COMMITTED, r
        return fd.TXN_UNKNOWN_REBOOT, r
    return commit


def make_write_one(variant: str):
    """A copy of fd.write_one with ONE flaw."""
    def write_one(nvs, latch, key, intended, prior_bytes, prior_load, prior_len, rep):
        if key not in fd.WRITE_TARGETS or len(intended) != fd.WRITE_TARGETS[key]:
            raise ValueError("write_one may target only FBW and FBP (exclusivity pin X2)")
        t0 = nvs.now_us()
        err = fd.IDF_ERR_NVS_INVALID_HANDLE if nvs.handle() == 0 else nvs.set_blob(key, bytes(intended))
        rep.err = err
        rep.rb_load, readback, rep.rb_diag = fd.read_direct(nvs, key, len(intended))
        rc = fd.readback_class(rep.rb_load, rep.rb_diag.stored_len, readback == bytes(intended), prior_load, prior_len,
                               readback == bytes(prior_bytes))
        healthy = True if variant == "ignore_health" else fd.storage_healthy(nvs)
        o = fd.classify_key_outcome(fd.classify_write_err(err), rc, healthy)
        if o == fd.KEY_UNKNOWN_REBOOT and variant == "retry_once":          # a silent retry
            err = nvs.set_blob(key, bytes(intended))
            rep.rb_load, readback, rep.rb_diag = fd.read_direct(nvs, key, len(intended))
        if o == fd.KEY_UNKNOWN_REBOOT and variant != "no_latch":
            latch.write_latched = True
        rep.rb_class, rep.healthy_after, rep.outcome = rc, healthy, o
        rep.us = (nvs.now_us() - t0) & 0xFFFFFFFF
        return o, readback
    return write_one


_ORIG = {n: getattr(fdo, n) for n in ("classify_write_err", "classify_key_outcome", "mirror_after", "compose_profile_class",
                                      "save_generation_base", "save_generation_available", "invalidate_generation_permitted",
                                      "next_seen_hw_gen", "note_read", "read_direct")}


def p_classify_write_err(kind):
    def f(e):
        if kind == "timeout_prewrite" and e == fdo.IDF_ERR_TIMEOUT:
            return fdo.WERR_PRE_WRITE
        if kind == "nomem_prewrite" and e == fdo.IDF_ERR_NO_MEM:
            return fdo.WERR_PRE_WRITE
        return _ORIG["classify_write_err"](e)
    return f


def p_classify_key_outcome(kind):
    def f(e, r, healthy_after):
        if kind == "other_intended_committed" and e == fdo.WERR_OTHER and r == fdo.RB_INTENDED and healthy_after:
            return fdo.KEY_COMMITTED
        if kind == "ok_any_readback_committed" and e == fdo.WERR_OK and healthy_after:
            return fdo.KEY_COMMITTED
        if kind == "prewrite_trusted" and e == fdo.WERR_PRE_WRITE and healthy_after:
            return fdo.KEY_NOT_COMMITTED
        if kind == "ignore_health":
            return _ORIG["classify_key_outcome"](e, r, True)
        return _ORIG["classify_key_outcome"](e, r, healthy_after)
    return f


def p_mirror_after(kind):
    def f(o, r, p_prior, p_prior_load, w_prior, w_prior_load):
        if kind == "unknown_from_readback" and o == fdo.TXN_UNKNOWN_REBOOT:
            return r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load
        if kind == "adv_prior_witness" and o == fdo.TXN_NOT_COMMITTED and r.p.outcome != fdo.KEY_NOT_ATTEMPTED:
            return r.p_rb, bytes(w_prior), r.p.rb_load, w_prior_load
        return _ORIG["mirror_after"](o, r, p_prior, p_prior_load, w_prior, w_prior_load)
    return f


def p_compose(kind):
    def f(p_load, p, w_load, w, anomaly_bits):
        cls, why, rule = _ORIG["compose_profile_class"](p_load, p, w_load, w, anomaly_bits)
        if kind == "rollback_valid" and rule == 13:
            return fdo.EPC_VALID, fdo.WHY_NONE, 10
        if kind == "lost_not_captured" and rule in (5, 6, 7):
            return fdo.EPC_NOT_CAPTURED, fdo.WHY_NONE, 4
        if kind == "interrupted_rollback" and rule == 12:
            return fdo.EPC_PROFILE_STALE, fdo.WHY_ROLLBACK, 13
        if kind == "wit_missing_clean" and rule in (14, 15):
            return fdo.EPC_VALID, fdo.WHY_NONE, 10
        if kind == "b5_any_hw" and rule == 6:
            wd = fdo._as_provision(w)
            if wd["prior_generation"] == 0 and wd["last_op"] == fdo.PROV_OP_SAVE:
                return fdo.EPC_PROFILE_LOST, fdo.WHY_FIRST_SAVE_UNCONFIRMED, 5
        return cls, why, rule
    return f


def p_base(kind):
    """save_generation_base without a term; used together with the matching next_seen_hw_gen patch."""
    def f(c, g, wc, hw, seen):
        if kind == "no_hw":
            return _ORIG["save_generation_base"](c, g, wc, 0, seen)
        if kind == "no_g":
            return _ORIG["save_generation_base"](fdo.fp.PROFILE_NOT_CAPTURED, 0, wc, hw, seen)
        return _ORIG["save_generation_base"](c, g, wc, hw, seen)
    return f


def p_next_seen(kind):
    def f(seen, c, g, wc, hw):
        if kind == "no_hw":
            return _ORIG["next_seen_hw_gen"](seen, c, g, wc, 0)
        if kind == "no_g":
            return _ORIG["next_seen_hw_gen"](seen, fdo.fp.PROFILE_NOT_CAPTURED, 0, wc, hw)
        return _ORIG["next_seen_hw_gen"](seen, c, g, wc, hw)
    return f


def p_save_class_permitted(without):
    def f(cls):
        return _ORIG_SCP(cls) and cls != without
    return f


_ORIG_SCP = fdo.save_class_permitted


def p_note_read_forgiving(present_seen, read_anomaly, key_bit, load, healthy_after):
    """note_read WITHOUT the 'ABSENT after the key was seen present' anomaly (and without READ_ERROR memory of it)."""
    if load == fp.LOAD_ABSENT:
        return present_seen, read_anomaly if healthy_after else read_anomaly | fdo.ANOMALY_BIT_UNHEALTHY
    return _ORIG["note_read"](present_seen, read_anomaly, key_bit, load, healthy_after)


def p_read_direct_single_step(nvs, key, size):
    """MB29: a single-step direct read (no size probe): a wrong-size blob is just a failed read."""
    d = fdo.ReadDiag()
    zero = bytes(size)
    if nvs.handle() == 0:
        d.probe_err = fdo.IDF_ERR_NVS_INVALID_HANDLE
        return fp.LOAD_STORAGE_UNAVAILABLE, zero, d
    e, got, data = nvs.get_blob(key, size)
    d.data_err = e
    if e == fdo.IDF_ERR_NVS_NOT_FOUND:
        return fp.LOAD_ABSENT, zero, d
    if e != fdo.IDF_OK or got != size or data is None:
        return fp.LOAD_READ_ERROR, zero, d
    d.stored_len = got
    return fp.LOAD_OK, bytes(data), d


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------
@dataclass
class Mutant:
    mid: str
    desc: str
    kw: dict = field(default_factory=dict)          # arguments of L.mutated(...)
    rows: tuple = ()                                # the named rows that must kill it
    patches: dict = field(default_factory=dict)


N = "\n"
SAVE_I, INV_I = " " * 16, " " * 10     # the indentation of the SAVE_FINAL part 2 / INVALIDATE statement blocks


def Y(old, new, count=1):
    return {"yaml_edits": [(old, new, count)]}


def S(old, new, count=1):
    return {"save_edits": [(old, new, count)]}


MUTANTS: list = [
    # ---- firmware YAML text
    Mutant("Y01", "SAVE plan: seen_hw_gen dropped from the generation base (MB34)", Y("pi.seen_hw_gen = e.seen_hw_gen;", "pi.seen_hw_gen = 0;"),
           ("ar:seen-floor:save:32",)),
    Mutant("Y02", "INVALIDATE gate: seen_hw_gen dropped from the I10 check", Y("ii.seen_hw_gen = id(fallback_profile_seen_hw_gen);",
                                                                                 "ii.seen_hw_gen = 0;"), ("ar:seen-floor:invalidate:32",)),
    Mutant("Y03", "SAVE: an UNKNOWN outcome does not set the SAVE_UNCONFIRMED overlay (ignore UNKNOWN)",
           Y(N + " " * 18 + "id(fallback_profile_save_unconfirmed) = true;", N + " " * 18 + "id(fallback_profile_save_unconfirmed_op) = 0;"),
           ("doc:F2:TIMEOUT:old",)),
    Mutant("Y04", "INVALIDATE: an UNKNOWN outcome does not set the overlay",
           Y(N + " " * 12 + "id(fallback_profile_save_unconfirmed) = true;", N + " " * 12 + "id(fallback_profile_save_unconfirmed_op) = 0;"),
           ("inv:F2",)),
    Mutant("Y05", "REVIEW_FINAL: the overlay is not applied (B1 / candidate class come from the fresh read)",
           Y("const uint8_t eff_cls = ecco_fbsave::overlay_class(e.cls, id(fallback_profile_save_unconfirmed));",
             "const uint8_t eff_cls = e.cls;"), ("doc:F2:TIMEOUT:old",)),
    Mutant("Y06", "REVIEW_FINAL: eligibility ignores the overlay (a saveable candidate after UNKNOWN)", Y("ri.cls = eff_cls;", "ri.cls = e.cls;"),
           ("doc:F2:TIMEOUT:old",)),
    Mutant("Y07", "SAVE: the RAM mirror (profile) is taken from the INTENDED bytes (MB26)",
           Y(N + SAVE_I + "id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);",
             N + SAVE_I + "id(fallback_profile_bytes) = ecco_fallback::encode_profile(plan.p_new);"), ("doc:F6:ASIS",)),
    Mutant("Y08", "SAVE: the RAM mirror (witness) is taken from the INTENDED bytes",
           Y(N + SAVE_I + "id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(m.w);",
             N + SAVE_I + "id(fallback_witness_bytes) = ecco_fbdurable::encode_provision(plan.w_new);"), ("doc:F6:ASIS",)),
    Mutant("Y09", "SAVE: B2 us is not reported", Y(N + SAVE_I + "id(fallback_durable_last_us) = ecco_fbsave::total_us(r.w.us, r.p.us);",
                                                    N + SAVE_I + "id(fallback_durable_last_us) = 0;"), ("doc:F1",)),
    Mutant("Y10", "SAVE: B2 werr is not reported", Y(N + SAVE_I + "id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);",
                                                      N + SAVE_I + "id(fallback_durable_last_err) = 0;"), ("doc:F1",)),
    Mutant("Y11", "SAVE: B1 after the outcome ignores the overlay",
           Y(N + " " * 18 + "const char *cls_name = ecco_fbcap::epc_name(ecco_fbsave::overlay_class(e2.cls, id(fallback_profile_save_unconfirmed)));",
             N + " " * 18 + "const char *cls_name = ecco_fbcap::epc_name(e2.cls);"), ("doc:F2:TIMEOUT:old",)),
    Mutant("Y12", "SAVE: seen_hw_gen is not raised by the committed generation",
           Y(N + " " * 16 + "id(fallback_profile_seen_hw_gen) = ecco_fbdurable::next_seen_hw_gen(",
             N + " " * 16 + "id(fallback_profile_seen_hw_gen) = id(fallback_profile_seen_hw_gen) + 0 * ecco_fbdurable::next_seen_hw_gen("),
           ("prior:valid:clean",)),
    Mutant("Y13", "SAVE: the REPLACE CORRUPT context is lost (op chosen from the wrong side, MB36 wiring)",
           Y("pi.replace_corrupt = id(fallback_profile_save_ctx_replace_corrupt);", "pi.replace_corrupt = false;"), ("prior:corrupt:clean",)),
    Mutant("Y14", "SAVE: nvs_healthy() ignored in the fresh read (skip the health probe, MB25)",
           Y(N + " " * 14 + "in.healthy = healthy;", N + " " * 14 + "in.healthy = true;"), ("doc:F-H1:invalid-page-before-commit",)),
    Mutant("Y15", "the boot lambda writes NVS (MB37)",
           Y("id(fallback_profile_boot_loaded) = true;",
             "{ ecco_fbdurable::EspNvs nvsw; nvsw.set_blob(ecco_fbdurable::FALLBACK_PROFILE_KEY, id(fallback_profile_bytes)); }\n"
             "          id(fallback_profile_boot_loaded) = true;"), ("prior:valid:clean",)),
    Mutant("Y16", "SAVE gate: G9 ignores the SAVE_UNCONFIRMED overlay (the writer latch is the only guard left)",
           Y("si.unconfirmed = id(fallback_profile_save_unconfirmed);", "si.unconfirmed = false;"), ("doc:F13:second-save-after-unknown",)),
    Mutant("Y17", "INVALIDATE: the RAM mirror is taken from the INTENDED bytes",
           Y(N + INV_I + "id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);",
             N + INV_I + "id(fallback_profile_bytes) = ecco_fallback::encode_profile(plan.p_new);"), ("inv:F6",)),
    Mutant("Y18", "INVALIDATE: B2 werr is not reported", Y(N + INV_I + "id(fallback_durable_last_err) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);",
                                                            N + INV_I + "id(fallback_durable_last_err) = 0;"), ("inv:F1",)),
    # ---- the Python mirror of ecco_fallback_save.h
    Mutant("S01", "mirror plan_save: seen_hw_gen not in the generation base",
           S('base = fd.save_generation_base(pc, p["generation"], wc, w["hw_generation"], inp.seen_hw_gen)',
             'base = fd.save_generation_base(pc, p["generation"], wc, w["hw_generation"], 0)'), ("ar:seen-floor:save:32",)),
    Mutant("S02", "mirror plan_save: the new generation is the base (no +1)", S("gen = (base + 1) & U32", "gen = base & U32"), ("prior:valid:clean",)),
    Mutant("S03", "mirror plan_save: the witness op is always SAVE (REPLACE CORRUPT lost)",
           S("op = fd.PROV_OP_REPLACE_CORRUPT if replace_ else fd.PROV_OP_SAVE", "op = fd.PROV_OP_SAVE"), ("prior:corrupt:clean",)),
    Mutant("S04", "mirror plan_save: the witness prior_* come from the candidate's bound fingerprint, not the authentic prior",
           S('wn = fd.make_provision(gen, pn["binding"], p["generation"] if authentic else 0, p["binding"] if authentic else 0,',
             'wn = fd.make_provision(gen, pn["binding"], inp.cand_prior_gen, inp.cand_prior_binding,'), ("prior:corrupt:clean",)),
    Mutant("S05", "mirror txn_outcome_text: the 'witness advanced' outcome reads as a plain NOT_COMMITTED",
           S("if r.witness_advanced:", "if False:"), ("doc:F4",)),
    Mutant("S06", "mirror save_unknown_text: the reboot instruction is dropped",
           S('"; reboot the dongle (when no temporary "', '"; (when no temporary "'), ("doc:F2:TIMEOUT:old",)),
    Mutant("S07", "mirror saved_text: reports generation - 1",
           S('f"SAVED - known-good profile generation {generation & U32} saved (verified this boot)"',
             'f"SAVED - known-good profile generation {(generation - 1) & U32} saved (verified this boot)"'), ("prior:valid:clean",)),
    Mutant("S08", "mirror first_non_ok: B2 werr always '-'", S("return (err_w if err_w != 0 else err_p) & U32", "return 0"), ("doc:F1",)),
    Mutant("S09", "mirror overlay_class: the SAVE_UNCONFIRMED overlay never applies",
           S("return fd.EPC_SAVE_UNCONFIRMED if unconfirmed else cls", "return cls"), ("doc:F2:TIMEOUT:old",)),
    Mutant("S10", "mirror SAVE gate: REPLACE CORRUPT accepted without its phrase (MB36)",
           S("expected = expected_phrase(PHRASE_SAVE_REPLACE_CORRUPT if replace_ else PHRASE_SAVE, inp.cand_id)",
             "expected = expected_phrase(PHRASE_SAVE, inp.cand_id)"), ("ar:replace-phrase:corrupt",)),
    # ---- the FB-B0 durable model the harness executes
    Mutant("P01", "writer: the profile is written BEFORE the witness (MB22)", patches={"commit_transition": make_commit("fbp_first")},
           rows=("doc:F4", "cut:k:valid:FBW:K4")),
    Mutant("P02", "writer: nvs_healthy() after the write is ignored (MB25)", patches={"write_one": make_write_one("ignore_health")},
           rows=("doc:FH2:page-invalid-between-writes",)),
    Mutant("P03", "writer: a raw ESP_ERR_TIMEOUT is a provably pre-write error (MB23)",
           patches={"classify_write_err": p_classify_write_err("timeout_prewrite")}, rows=("grid:valid:W:TIMEOUT:OLD:1",)),
    Mutant("P04", "writer: ESP_ERR_NO_MEM is a provably pre-write error",
           patches={"classify_write_err": p_classify_write_err("nomem_prewrite")}, rows=("grid:valid:W:NO_MEM:OLD:1",)),
    Mutant("P05", "writer: a raw flash error with the intended bytes read back is COMMITTED",
           patches={"classify_key_outcome": p_classify_key_outcome("other_intended_committed")}, rows=("grid:valid:W:TIMEOUT:NEW:1",)),
    Mutant("P06", "writer: ESP_OK with ANY readback is COMMITTED (MB24)",
           patches={"classify_key_outcome": p_classify_key_outcome("ok_any_readback_committed")}, rows=("grid:valid:W:OK:OTHER:1",)),
    Mutant("P07", "writer: an UNKNOWN key does not set the write latch", patches={"write_one": make_write_one("no_latch")},
           rows=("doc:F2:TIMEOUT:old",)),
    Mutant("P08", "writer: the latch is not consulted (a second commit after UNKNOWN, MB27)", patches={"commit_transition": make_commit("ignore_latch")},
           rows=("doc:F13:second-save-after-unknown",)),
    Mutant("P09", "writer mirror: the mirror after UNKNOWN is taken from the readbacks",
           patches={"mirror_after": p_mirror_after("unknown_from_readback")}, rows=("doc:F6:ASIS",)),
    Mutant("P10", "writer mirror: NOT_COMMITTED with the witness advanced keeps the prior witness",
           patches={"mirror_after": p_mirror_after("adv_prior_witness")}, rows=("doc:F4",)),
    Mutant("P11", "writer: the profile is written although the witness write was NOT_COMMITTED",
           patches={"commit_transition": make_commit("fbp_after_w_not_committed")}, rows=("doc:F1",)),
    Mutant("P12", "writer: the profile is written although the witness write was UNKNOWN",
           patches={"commit_transition": make_commit("fbp_after_w_unknown")}, rows=("doc:F2:TIMEOUT:old",)),
    Mutant("P13", "writer: one silent retry of the write after an UNKNOWN key", patches={"write_one": make_write_one("retry_once")},
           rows=("doc:F2:TIMEOUT:old",)),
    Mutant("P14", "writer: the handle == 0 refusal is skipped", patches={"commit_transition": make_commit("ignore_handle")},
           rows=("doc:F12b:handle-zero-at-commit",)),
    Mutant("P15", "writer: the pre-commit health refusal is skipped (F-H1)", patches={"commit_transition": make_commit("ignore_health")},
           rows=("doc:F-H1:invalid-page-before-commit",)),
    Mutant("P16", "model: the generation counter never reports exhausted", patches={"save_generation_available": lambda base: True},
           rows=("ar:wrap:g-max",)),
    Mutant("P17", "model: INVALIDATE ignores the high-water mark (g + 1 > seen_hw_gen not required)",
           patches={"invalidate_generation_permitted": lambda g, wc, hw, seen: g < 0xFFFFFFFF and g + 1 > (hw if wc == fdo.W_VALID else 0)},
           rows=("ar:seen-floor:invalidate:32",)),
    Mutant("P18", "compose: a ROLLBACK (g < hw, an old index re-appearing) reads as VALID (MB31)",
           patches={"compose_profile_class": p_compose("rollback_valid")}, rows=("prior:stale_rbk:clean",)),
    Mutant("P19", "compose: PROFILE_LOST (FBP absent, FBW present) reads as NOT_CAPTURED (MB30)",
           patches={"compose_profile_class": p_compose("lost_not_captured")}, rows=("prior:lost:clean",)),
    Mutant("P20", "compose: first-save-unconfirmed (B5) without the hw == 1 condition",
           patches={"compose_profile_class": p_compose("b5_any_hw")}, rows=("cut:k:lost:FBW:K4",)),
    Mutant("P21", "generation base AND seen_hw_gen ignore the witness high-water (hw)",
           patches={"save_generation_base": p_base("no_hw"), "next_seen_hw_gen": p_next_seen("no_hw")}, rows=("prior:lost:clean",)),
    Mutant("P22", "generation base AND seen_hw_gen ignore the authentic profile generation (g)",
           patches={"save_generation_base": p_base("no_g"), "next_seen_hw_gen": p_next_seen("no_g")}, rows=("prior:lag:clean",)),
    Mutant("P23", "reader: single-step direct read, no size probe (MB29)", patches={"read_direct": p_read_direct_single_step},
           rows=("prior:wsize:clean",)),
    Mutant("P24", "writer: a pre-write code is trusted without checking the readback",
           patches={"classify_key_outcome": p_classify_key_outcome("prewrite_trusted")}, rows=("grid:valid:W:READ_ONLY:OTHER:1",)),
    Mutant("P25", "writer: the post-write health is ignored by the key classifier",
           patches={"classify_key_outcome": p_classify_key_outcome("ignore_health")}, rows=("doc:FH2:page-invalid-between-writes",)),
    Mutant("P26", "same-boot regression guard removed: no 'ABSENT after present' anomaly AND no divergence rule (FBP / FBW vanish)",
           kw={"cap_edits": [("p_div = r.baseline_valid and profile_diverged(r.last_p_load, r.last_p_bytes, r.p_load, fp.pack_profile(p))",
                               "p_div = False", 1),
                              ("w_div = r.baseline_valid and witness_diverged(r.last_w_load, r.last_w_bytes, r.w_load, fd.pack_provision(w))",
                               "w_div = False", 1)]},
           patches={"note_read": p_note_read_forgiving}, rows=("ar:guard:fbp-vanish:before-review", "ar:guard:fbw-vanish:between")),
    Mutant("Y19", "SAVE: the unconfirmed generation is not recorded", Y(N + " " * 18 + "id(fallback_profile_save_unconfirmed_gen) = plan.generation;",
                                                                        N + " " * 18 + "id(fallback_profile_save_unconfirmed_gen) = 0;"),
           ("doc:F2:TIMEOUT:old",)),
    Mutant("S11", "mirror invalidated_text: reports the wrong new generation", S('f"g{generation & U32}); payload kept for reference; save a new profile to re-enable")',
                                                                                  'f"g{(generation + 1) & U32}); payload kept for reference; save a new profile to re-enable")'),
           ("inv:clean",)),
    Mutant("S12", "mirror: the INVALIDATE 'witness advanced' text says the profile is still VALID",
           S("g{prior_generation & U32} is now STALE (unusable)\")", "g{prior_generation & U32} is now VALID\")"), ("inv:F4",)),
    Mutant("S13", "mirror total_us: B2 us carries only the witness time", S("return (w_us + p_us) & U32", "return w_us & U32"), ("prior:valid:clean",)),
    Mutant("S14", "mirror txn_outcome_text: the NOT_COMMITTED text carries the profile error code",
           S("else save_not_committed_text(r.w.err))", "else save_not_committed_text(r.p.err))"), ("doc:F1",)),
    Mutant("S15", "mirror plan_save: the witness high-water is gen - 1",
           S('wn = fd.make_provision(gen, pn["binding"], p["generation"] if authentic else 0, p["binding"] if authentic else 0,',
             'wn = fd.make_provision(gen - 1, pn["binding"], p["generation"] if authentic else 0, p["binding"] if authentic else 0,'),
           ("prior:valid:clean",)),
    Mutant("S16", "mirror plan_save: the prior is not compared with the reviewed one (SAVE over a changed prior, MB35)",
           S("if inp.cls != inp.cand_prior_class or f.generation != inp.cand_prior_gen or f.binding != inp.cand_prior_binding:", "if False:"),
           ("ar:guard:fbp-older:between", "ar:guard:fbw-changed:between")),
    Mutant("P27", "compose: an interrupted save (B12 INTERRUPTED) reads as a ROLLBACK", patches={"compose_profile_class": p_compose("interrupted_rollback")},
           rows=("cut:k:valid:FBW:K4",)),
    Mutant("P28", "compose: a missing / corrupt witness (B14 / B15) is silently trusted (VALID, no repair hint)",
           patches={"compose_profile_class": p_compose("wit_missing_clean")}, rows=("prior:wmiss:clean",)),
    Mutant("P29", "model: SAVE not permitted over PROFILE_STALE", patches={"save_class_permitted": p_save_class_permitted(fdo.EPC_PROFILE_STALE)},
           rows=("prior:stale_int:clean",)),
    Mutant("P30", "model: SAVE not permitted over PROFILE_LOST", patches={"save_class_permitted": p_save_class_permitted(fdo.EPC_PROFILE_LOST)},
           rows=("prior:lost:clean",)),
    Mutant("P31", "model: REPLACE CORRUPT not required over a CORRUPT prior (the class reads as plainly saveable)",
           patches={"save_requires_replace_phrase": lambda cls: False}, rows=("ar:replace-phrase:corrupt",)),
    Mutant("P32", "generation base without the witness high-water (hw) term (the caller-side seen_hw_gen fold cannot hide it)",
           patches={"save_generation_base": p_base("no_hw")}, rows=("ar:model:formula",)),
    Mutant("P33", "generation base without the authentic profile generation (g) term",
           patches={"save_generation_base": p_base("no_g")}, rows=("ar:model:formula",)),
    Mutant("P34", "seen_hw_gen fold without the witness high-water (hw) term (a same-boot floor that forgets the witness)",
           patches={"next_seen_hw_gen": p_next_seen("no_hw")}, rows=("ar:model:formula",)),
    Mutant("S17", "mirror plan_save: the class gate is skipped (SAVE planned over an UNREADABLE / SAVE_UNCONFIRMED class, MB35)",
           S("if not fd.save_class_permitted(cls):", "if False:"), ("ar:mirror:plan_save",)),
    Mutant("S18", "mirror plan_save: a read anomaly does not refuse the plan",
           S("if inp.read_anomaly != 0:" + N + " " * 8 + "return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text())",
             "if False:" + N + " " * 8 + "return plan_refuse(r, PLAN_ANOMALY, save_anomaly_text())"), ("ar:mirror:plan_save",)),
]
for _m in MUTANTS:
    if _m.patches and "patches" not in _m.kw:
        _m.kw = dict(_m.kw, patches=_m.patches)


def run_mutant(mid: str) -> dict:
    """Activate the mutant, run its named rows, return {mid, killed, details, per_row}. A row that raises FbbNotModelled is an ERROR
    (not a kill): the harness must be able to execute the mutant."""
    m = next(x for x in MUTANTS if x.mid == mid)
    per = {}
    with L.mutated(tag=mid.lower(), **m.kw):
        for name in m.rows:
            try:
                fails = F.run_row(name)
                per[name] = ("killed", fails[0][:200]) if fails else ("SURVIVED", "")
            except D.FbbNotModelled as e:
                per[name] = ("ERROR", str(e)[:200])
            except Exception as e:  # noqa: BLE001
                per[name] = ("killed", f"{type(e).__name__}: {str(e)[:160]}")
    killed = all(v[0] == "killed" for v in per.values())
    return {"mid": mid, "desc": m.desc, "killed": killed, "per_row": per}


def run_mutants(ids) -> list:
    """A work item for a process pool: run the mutants `ids` one after the other."""
    return [run_mutant(mid) for mid in ids]


# Mutants that NO row can tell apart from the original: redundant (defence-in-depth) layers. Reported, never failed: a layer that is
# redundant by design shows up here; the report lists them so nobody mistakes "no mutant killed it" for "untested".
EQUIVALENT = [
    ("plan_invalidate seen", "YAML pj.seen_hw_gen := 0 (the INVALIDATE gate I10 refuses first)",
     {"yaml_edits": [("pj.seen_hw_gen = e.seen_hw_gen;", "pj.seen_hw_gen = 0;", 1)]}),
    ("plan_save unconfirmed", "YAML pi.unconfirmed := false (the SAVE gate G9 and the writer latch refuse first)",
     {"yaml_edits": [("pi.unconfirmed = id(fallback_profile_save_unconfirmed);", "pi.unconfirmed = false;", 1)]}),
    ("words from the review copy", "YAML commits the review-time words (SAVE_FINAL already required pass 2 == the candidate)",
     {"yaml_edits": [("pi.words = id(fallback_profile_pass2);", "pi.words = id(fallback_profile_save_ctx_words);", 1)]}),
]
EQ_ROWS = ("prior:valid:clean", "prior:lost:clean", "prior:lag:clean", "prior:stale_int:clean", "prior:corrupt:clean", "ar:seen-floor:save:32",
           "doc:F4", "cut:k:valid:FBW:K4", "ar:resurrect:old-prior", "ar:resurrect:older-g5", "ar:guard:fbp-vanish:between",
           "ar:wrap:g-max", "seq:scripted:stale-then-save", "seq:random:3")


def run_equivalent(i: int) -> dict:
    """Run the representative rows with the i-th redundant-layer mutant active: which (if any) distinguish it."""
    name, desc, kw = EQUIVALENT[i]
    killers = []
    with L.mutated(tag=f"eq{i}", **kw):
        for r in EQ_ROWS:
            try:
                if F.run_row(r):
                    killers.append(r)
            except D.FbbNotModelled:
                killers.append(r + " (harness error)")
    return {"name": name, "desc": desc, "killers": killers}
