"""FB-B2 t-gates: SAVE SUCCESS scenarios (registered into _fbb2_gates_lib.SCENARIOS).

Every expectation is built independently (see _fbb2_gates_lib): expected FBP / FBW bytes from the FB-A / FB-B0 mirrors over the named
golden fields, the locked golden vectors as literals, the next-boot class from the FB-B0 model oracle, texts as locked literals.
"""

from __future__ import annotations

from _fbb2_gates_lib import *  # noqa: F401,F403
from _fbb2_gates_lib import (D, E, H, K_P, K_W, EPOCH0, FIRST_PROFILE_BINDING, READS4, W_FIRST_BINDING, TXT, Exp, check_saved,
                             candidate_consumed, exp_profile, exp_witness, fc, fd, fp, nothing_held, pair_bytes, ready, scenario,
                             strip_us, t_saved, all_driver_violations)


@scenario("ss_first_save", "SAVE success from NOT_CAPTURED: exact FBW then FBP bytes, golden vectors, texts, reads, locks, reboot")
def ss_first_save(mk, ex: Exp):
    d = mk(seed="none")
    ex.row("setup guard")
    ex.eq(d.b1, "NOT_CAPTURED", "boot class (independent oracle agrees: " + d.model_class()[0] + ")")
    ex.eq(d.model_class()[0], "NOT_CAPTURED", "the NVS image is NOT_CAPTURED per the FB-B0 oracle")
    rv = d.review()
    ex.row("Review")
    ex.eq(d.b3_field("st"), "CANDIDATE_READY", "the Review produced a saveable candidate")
    ex.eq(rv.reads, READS4, "the Review issued exactly the four dispatch reads")
    ex.eq(rv.violations_fb((), reads=READS4), [], "the Review wrote nothing")
    ex.starts(d.b9, "CANDIDATE READY - ", "the Review's own B9 is the candidate line (no stray INTERNAL / refusal text after a Review)")
    ex.eq(d.published("B9")[-2:], ["review in progress (read-only)", d.b9], "B9 sequence of a Review: in-progress, then the candidate line")
    cid = d.b4
    ex.ok(len(cid) == 16 and all(c in "0123456789ABCDEF" for c in cid), f"B4 is the 16-hex id ({cid})")
    ex.row("SAVE")
    ex.eq(d.arm_state, False, "arm is off before the operator turns it on (the Review turned it off)")
    d.arm_on()
    ex.eq(d.arm_state, True, "the operator turned the arm on")
    st = d.execute("SAVE", cid, f"SAVE {cid}")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="first SAVE g1")
    ex.row("storage protocol of the SAVE (locked order: markers, fresh two-key read, health, witness write + readback + health, profile write + readback + health)")
    nm = {fd.decimal_key(K_P): "FBP", fd.decimal_key(K_W): "FBW", fd.decimal_key(D.K_S): "FBS"}
    ops = [(o[0], nm.get(o[1], "marker" if o[1] is not None else None)) for o in st.since.nvs_ops]
    ex.eq(ops[:3], [("get", "marker")] * 3, "the three lease markers are probed first, once each (step 5)")
    ex.eq(ops[3:7], [("get", "FBP"), ("get", "FBW"), ("stats", None), ("stats", None)],
          "then the fresh FBP + FBW reads, ONE health check, and the writer's own pre-write health check")
    ex.eq(ops[7:], [("set", "FBW"), ("get", "FBW"), ("read", "FBW"), ("stats", None), ("set", "FBP"), ("get", "FBP"), ("read", "FBP"), ("stats", None)],
          "witness write, witness readback (size probe + data read), health re-check, THEN the profile write, its readback, health re-check")
    ex.ok(all(o[1] != "FBS" for o in ops), "the failback-state key is never touched by a SAVE")
    # the locked golden vectors, as literals (after the reboot check_saved did, d holds the rebooted device: the NVS is the same)
    ex.row("golden vectors")
    fbw, fbp = d.stored("FBW"), d.stored("FBP")
    ex.eq(fbw["binding"], W_FIRST_BINDING, "FBW binding == locked golden vector W-FIRST 0xA8B8788B4C915BB6")
    ex.eq(fbw["hw_binding"], FIRST_PROFILE_BINDING, "FBW hw_binding == the first profile binding 0xB74CE0FA6297474D")
    ex.eq(fbp["binding"], FIRST_PROFILE_BINDING, "FBP binding == 0xB74CE0FA6297474D")
    ex.eq((fbw["hw_generation"], fbw["prior_generation"], fbw["prior_binding"], fbw["last_op"], fbw["flags"]),
          (1, 0, 0, fd.PROV_OP_SAVE, 0), "FBW hw=1, prior 0/0, op SAVE, flags 0")
    ex.eq((fbw["magic"], fbw["schema"], fbw["size"], fbw["hw_tag_key"], fbw["hw_record_schema"]),
          (0x45434657, 1, 48, 0x5FEE6196, 1), "FBW magic / schema / size / hw_tag_key / hw_record_schema")
    ex.eq((fbp["generation"], fbp["captured_epoch"], fbp["flags"], fbp["reserved0"], fbp["reserved1"], fbp["size"], fbp["schema"]),
          (1, EPOCH0, 0, 0, 0, 96, 1), "FBP generation 1, captured_epoch = the trusted wall clock, flags / reserved 0")
    ex.eq(list(fc.words_of(fbp)), list(d.words), "FBP payload == the live words the Review saw")
    ex.eq(all_driver_violations(d), [], "no Modbus write and no third key over every boot")


@scenario("ss_saving_state_deferred_bus", "SAVING is visible on a deferred bus; the hold is bounded; second execute / Review do not disturb it")
def ss_saving_state_deferred_bus(mk, ex: Exp):
    d = mk(seed="none", mode=("deferred", 120))
    rv = d.review(expect="CANDIDATE_READY")
    ex.row("Review on a deferred bus")
    ex.eq(rv.reads, READS4, "four reads")
    cid = d.b4
    d.arm_on()
    t0 = d.sim.now_ms
    st = d.execute("SAVE", cid, f"SAVE {cid}", idle=False)
    ex.row("accepted: SAVING")
    ex.starts(d.b3, "st=SAVING;prior=-;exp=-;warn=-;obl=", "B3 st=SAVING with the idle-form fields")
    ex.has(d.b3, ";latch=-;sv=-", "B3 tail")
    ex.eq(d.b9, TXT["progress"], "B9 is the in-progress line")
    ex.eq(d.b4, "-", "B4 '-' (the candidate is consumed while SAVING)")
    ex.ok(candidate_consumed(d), "candidate consumed at acceptance")
    ex.eq(d.arm_state, False, "arm off at acceptance")
    g = d.g
    ex.eq((g["fallback_profile_op_in_progress"], g["manual_write_in_progress"], g["fallback_profile_op_purpose"], g["fallback_profile_capture_state"]),
          (True, True, 2, fc.CAPTURE_SAVING), "op flag + write mutex held, purpose SAVE (2), capture state SAVING (4)")
    ex.eq(sorted(d.sim.running), ["fallback_profile_capture_dispatch"], "the existing dispatch is the only FB script running")
    ex.eq(st.violations_fb((), reads=[]), [], "no read, no write yet (the idle wait started)")
    ex.eq(g["fallback_profile_save_ctx_valid"], True, "the save context was taken")
    ex.row("hold")
    d.advance(130)
    d.idle()
    held = d.sim.now_ms - t0
    ex.ok(held < 24_000, f"the whole SAVE held the bus for {held} ms (< the locked ~24 s bound)")
    ex.ok(480 <= held <= 1_200, f"4 reads x 120 ms + the pre-commit drain ~= {held} ms")
    ex.eq(d.b9, t_saved(1), "B9 after the SAVE")
    ex.eq(d.published("B9")[-2:], [TXT["progress"], t_saved(1)], "B9 sequence ends: in-progress, SAVED")
    ex.eq(nothing_held(d), [], "released")
    ex.eq(d.modbus_reads()[-4:], READS4, "the SAVE's own four reads are the last four")
    ex.eq(d.modbus_reads().__len__(), 8, "exactly 8 reads over the Review + the SAVE")
    ex.eq(all_driver_violations(d), [], "no Modbus write, no third key")


@scenario("ss_time_flows_epoch", "captured_epoch is the trusted wall clock sampled in the commit lambda (flowing clock)")
def ss_time_flows_epoch(mk, ex: Exp):
    d = mk(seed="none", mode=("deferred", 120), epoch=1_795_000_000)
    d.set_time(epoch=1_795_000_000, ntp=True, flow=True)
    d.review(expect="CANDIDATE_READY")
    d.advance(40_000)   # the candidate is still valid (< 120 s)
    d.arm_on()
    seen = {}

    def first_set(op, key):
        if op == "set" and "t" not in seen:
            seen["t"] = d.sim.now_ms
    d.sim.nvs_direct.before_op = first_set
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    ex.row("flowing clock")
    ex.ok("t" in seen, "a durable write happened")
    t0 = d.sim.ent("ntp_time")._t0
    want_epoch = 1_795_000_000 + (seen["t"] - t0) // 1000
    fbp = d.stored("FBP")
    ex.eq(fbp["captured_epoch"], want_epoch, "captured_epoch == the wall clock at the instant of the commit")
    ex.ok(fbp["captured_epoch"] != 0 and fbp["captured_epoch"] > 1_795_000_000, "captured_epoch is not 0 and moved with the clock")
    ex.eq(d.b9, t_saved(1), "SAVED")
    ex.eq(st.violations_fb(("FBW", "FBP")), [], "FBW then FBP only")


PRIOR_ROWS = []


def _row(name, seed, gen, prior_gen, prior_binding, expected_class, op=0, replace=False, review_expect="CANDIDATE_READY"):
    PRIOR_ROWS.append((name, seed, gen, prior_gen, prior_binding, expected_class, op or fd.PROV_OP_SAVE, replace, review_expect))


def _binding_of(**fields):
    return D.gold_profile(**fields)["binding"]


_GOLD_B = D.GOLD["binding"]
_INV = fp.invalidate_profile(D.GOLD)
_CD = D.gold_profile(reg244=7)
_row("VALID g7 (witness hw 7)", "valid", 8, 7, _GOLD_B, "VALID")
_row("INVALIDATED g8 (witness hw 8)", "invalidated", 9, 8, _INV["binding"], "INVALIDATED")
_row("CORRUPT_DOMAIN g7 (witness hw 7)",
     {"fbp": _CD, "fbw": D.prov_bytes(7, _CD["binding"], 6)}, 8, 7, _CD["binding"], "CORRUPT_DOMAIN")
_row("CORRUPT_DOMAIN g7 (witness missing, B14)", "corrupt_domain", 8, 7, _CD["binding"], "CORRUPT_DOMAIN")
_row("PROFILE_LOST (FBP absent, witness hw 7)", "lost", 8, 0, 0, "PROFILE_LOST")
_row("PROFILE_LOST first save unconfirmed (hw 1, prior 0, op SAVE)",
     {"fbw": D.prov_bytes(1, 0x1234, 0, fd.PROV_OP_SAVE)}, 2, 0, 0, "PROFILE_LOST")
_row("PROFILE_STALE (FBP g5, witness hw 7)", "stale", 8, 5, _binding_of(generation=5), "PROFILE_STALE")
_row("VALID with a LAGGING witness (hw 6)", "lag", 8, 7, _GOLD_B, "VALID")
_row("VALID with a CORRUPT witness", "witness_corrupt", 8, 7, _GOLD_B, "VALID")
_row("CORRUPT + REPLACE CORRUPT (no witness): generation 1, op RC", "corrupt", 1, 0, 0, "CORRUPT", fd.PROV_OP_REPLACE_CORRUPT, True)
_row("CORRUPT + REPLACE CORRUPT (witness hw 9): max(hw, seen) + 1 = 10", {"fbp": bytes(range(96)), "fbw": D.prov_bytes(9, 0xAAAA, 8)},
     10, 0, 0, "CORRUPT", fd.PROV_OP_REPLACE_CORRUPT, True)
_row("WRONG-SIZE FBP + REPLACE CORRUPT", "wsize", 1, 0, 0, "CORRUPT", fd.PROV_OP_REPLACE_CORRUPT, True)


@scenario("ss_recapture_over_priors", "recapture over VALID / INVALIDATED / CORRUPT_DOMAIN / LOST / STALE / lag / CORRUPT priors: generation = max(...)+1")
def ss_recapture_over_priors(mk, ex: Exp):
    for name, seed, gen, pgen, pbind, cls, op, replace, rexp in PRIOR_ROWS:
        ex.row(name)
        d = mk(seed=seed)
        ex.eq(d.model_class()[0], cls, f"{name}: the seeded image is {cls} per the FB-B0 oracle")
        ex.eq(d.b1, cls, f"{name}: the boot published {cls}")
        d.review(expect=rexp)
        ex.eq(d.b3_field("prior"), cls, f"{name}: the candidate is bound to prior class {cls}")
        cid = d.b4
        st = d.save(replace_corrupt=replace)
        check_saved(ex, d, st, gen=gen, prior_gen=pgen, prior_binding=pbind, op=op, label=name)
        ex.eq(all_driver_violations(d), [], f"{name}: no Modbus write, no third key")


@scenario("ss_second_save_same_boot", "ABSENT/ABSENT SAVE g1, then the second SAVE of the same boot is g2, the third g3 (the seen_hw_gen floor)")
def ss_second_save_same_boot(mk, ex: Exp):
    d = mk(seed="none")
    d.review(expect="CANDIDATE_READY")
    st1 = d.save()
    prof1 = exp_profile(1)
    check_saved(ex, d, st1, gen=1, prior_gen=0, prior_binding=0, label="save 1", reboot=False)
    d.review(expect="CANDIDATE_READY")
    ex.row("Review over the saved profile")
    ex.eq(d.b3_field("prior"), "VALID", "the second candidate is bound to prior VALID")
    st2 = d.save()
    check_saved(ex, d, st2, gen=2, prior_gen=1, prior_binding=prof1["binding"], label="save 2", reboot=False)
    prof2 = exp_profile(2)
    d.review(expect="CANDIDATE_READY")
    st3 = d.save()
    check_saved(ex, d, st3, gen=3, prior_gen=2, prior_binding=prof2["binding"], label="save 3", reboot=True)
    ex.row("history")
    ex.eq([h[1] for h in d.nvs_set_history()], ["FBW", "FBP"] * 3, "six durable sets in witness-first pairs")
    ex.eq(all_driver_violations(d), [], "no Modbus write, no third key")


@scenario("ss_candidate_words_changed_value", "a SAVE of a changed (but valid) configuration saves exactly the reviewed words")
def ss_candidate_words_changed_value(mk, ex: Exp):
    fields = dict(reg245=7000, reg256_261=[7000, 600, 4100, 3100, 2100, 1100])
    w = words_of_fields(fields)
    d = mk(seed="valid", words=w)
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=8, prior_gen=7, prior_binding=D.GOLD["binding"], label="changed words over VALID g7",
                profile_fields=fields)
    ex.row("payload")
    ex.eq(list(fc.words_of(d.stored("FBP"))), w, "the stored words are the reviewed words")


def words_of_fields(fields):
    return list(fc.words_of(D.gold_profile(**fields)))


def tap_b9(d) -> list:
    """Record the other FB texts at the instant every B9 value is published: [(value, {B1, B2, B7, B8})]."""
    ent = d.sim.ent(D.B_IDS["B9"])
    log: list = []
    orig = ent.publish_state

    def pub(v):
        log.append((str(v), {k: d.text(k) for k in ("B1", "B2", "B7", "B8")}))
        orig(v)
    ent.publish_state = pub
    return log


@scenario("ss_publish_order", "the outcome text is published only AFTER the mirror update: B1 / B2 / B7 / B8 already show the new profile when B9 says SAVED")
def ss_publish_order(mk, ex: Exp):
    for seed, gen, label in (("none", 1, "first SAVE"), ("valid", 8, "recapture over VALID g7")):
        ex.row(label)
        d = mk(seed=seed)
        d.review(expect="CANDIDATE_READY")
        log = tap_b9(d)
        d.save()
        saved = [e for e in log if e[0].startswith("SAVED - ")]
        ex.eq(len(saved), 1, f"{label}: SAVED published once")
        if saved:
            txts = saved[0][1]
            ex.eq(txts["B1"], "VALID", f"{label}: B1 is VALID when B9 says SAVED")
            ex.ok(txts["B2"].startswith(f"g={gen};"), f"{label}: B2 shows generation {gen} when B9 says SAVED: {txts['B2'][:40]!r}")
            ex.ok(txts["B7"].startswith(f"v=SAVED;g={gen};") and txts["B8"].startswith("v=SAVED;"), f"{label}: B7 / B8 show the new profile when B9 says SAVED")
