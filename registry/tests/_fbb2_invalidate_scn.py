"""FB-B2 INVALIDATE scenarios (t-invalidate): the scenario functions and tables behind registry/tests/test_fallback_invalidate.py.

Every scenario takes a driver FACTORY `mk(**driver_kwargs) -> _fbb2_drive.Driver` (the live firmware, or a mutant of it) and returns a list
of violation strings (empty = the firmware behaved as the locked design says). The suite runs each scenario on the live firmware (must
be clean) and the mutant matrix runs the same scenarios on mutated copies (must report a violation). Expectations are derived from the
locked design (master 4.8 / 5, S2B 4.2-4.4, the FB-B2 brief) or from the independent FB-B0 model oracle (see _fbb2_invalidate_kit.py),
never from the output of the firmware under test.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import _fbb1_engine as E  # noqa: E402
import _fbb2_drive as D  # noqa: E402
import _fbb2_invalidate_kit as K  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
from _fbb2_invalidate_kit import Errs, GlobalWatch, K_P, K_W  # noqa: E402

PREFIX = "INVALIDATE REFUSED - "
# Locked refusal bodies of the INVALIDATE gate table (S2 final 4.2: I5 / I6); the header says exactly these.
T_NOT_LOADED = "durable state not loaded yet (starting up)"
T_ANOMALY = "stored profile read anomaly this boot; reboot to re-derive first"
GOLD = D.GOLD
GOLD_ID = f"{GOLD['binding']:016X}"                    # the stored VALID profile's full 16-hex binding (B2 id=)
GOLD_G = GOLD["generation"]                            # 7
EXPECTED_SET_ORDER = ["FBW", "FBP"]
GOLD_INVALIDATED_ID = f"{fp.invalidate_profile(GOLD)['binding']:016X}"   # F49A36C9C9720301
GOLD_W_INV_BINDING = 0x9E8AEC8F7D7DF2D7                # golden W-INV (master 5 / brief C): hw=8 prior=7 op INVALIDATE for GOLD
CLASS_NUM = {v: k for k, v in D.CLASS.items()}
GOLD_FBP = fp.pack_profile(GOLD)

# --- what an INVALIDATE may assign (design: the api action's copies, IE2 candidate consumption, the mirror refresh after a fresh
# read, and the post-commit state). Anything else (above all manual_write_in_progress / op_in_progress / op_purpose / step /
# gate_accepted / the SAVE context) is a violation.
ASSIGN_GATE = frozenset({"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation",
                         "fallback_profile_exec_hb_ok", "fallback_profile_arm_on_ms", "fallback_profile_cand_valid",
                         "fallback_profile_cand_saveable", "fallback_profile_capture_state", "fallback_profile_invalidate_reason"})
ASSIGN_FRESH = ASSIGN_GATE | frozenset({"fallback_profile_bytes", "fallback_profile_load", "fallback_witness_bytes",
                                        "fallback_witness_load", "fallback_profile_class", "fallback_profile_why",
                                        "fallback_profile_present_seen", "fallback_profile_read_anomaly",
                                        "fallback_profile_seen_hw_gen"})
ASSIGN_COMMIT = ASSIGN_FRESH | frozenset({"fallback_durable_last_err", "fallback_durable_last_us", "fallback_profile_save_unconfirmed",
                                          "fallback_profile_save_unconfirmed_op", "fallback_profile_save_unconfirmed_gen"})
MIRROR_GLOBALS = ("fallback_profile_bytes", "fallback_profile_load", "fallback_witness_bytes", "fallback_witness_load",
                  "fallback_profile_class", "fallback_profile_why", "fallback_profile_present_seen", "fallback_profile_read_anomaly",
                  "fallback_profile_seen_hw_gen", "fallback_durable_last_err", "fallback_durable_last_us",
                  "fallback_profile_save_unconfirmed")
FLAG_GLOBALS = ("manual_write_in_progress", "fallback_profile_op_in_progress", "fallback_profile_op_purpose", "fallback_profile_step",
                "fallback_profile_gate_accepted")


def mirror_state(d) -> dict:
    out = {}
    for g in MIRROR_GLOBALS:
        v = d.g[g]
        out[g] = list(v) if hasattr(v, "__len__") and not isinstance(v, (str, bytes)) else v
    return out


def b7_after(b7_before: str, new_gen: int, new_binding: int) -> str:
    """B7 of an INVALIDATED profile: the payload is kept verbatim, so it is the old B7 with the new generation and short binding."""
    s = re.sub(r"\bg=\d+", f"g={new_gen}", b7_before, count=1)
    return re.sub(r"\bb=[0-9A-F]{8}$", f"b={new_binding:016X}"[:10], s)


def b8_after(b8_before: str, new_binding: int) -> str:
    return re.sub(r"\bb=[0-9A-F]{8}$", f"b={new_binding:016X}"[:10], b8_before)


def publishes(st, key: str = "B9") -> list:
    return list(st.published.get(key, []))


def new_drv(mk, **kw):
    d = mk(**kw)
    return d, GlobalWatch(d)


# ---------------------------------------------------------------------------
# 1. CLEAN INVALIDATE
# ---------------------------------------------------------------------------
SEEDS_CLEAN = {
    "VALID/B10 witness consistent": "valid",
    "VALID/B8 witness lagging": "lag",
    "VALID/B14 witness missing": {"fbp": GOLD, "fbw": None},
    "VALID/B15 witness corrupt": "witness_corrupt",
}


def scn_clean(mk, seed="valid", *, pre=None, env_check=None, candidate=False, tail_save=False, reboot=True, drv_kw=None,
              arm_wait=None, tail=None) -> Errs:
    """The complete clean INVALIDATE: exact records, texts, mirror, class, zero Modbus, no wait, no mutex, reboot, (re-)Save."""
    e = Errs()
    d, w = new_drv(mk, seed=seed, **(drv_kw or {}))
    if candidate:
        d.review(expect="CANDIDATE_READY")
    if pre is not None:
        pre(d)
    blobs0 = K.copy_blobs(d)
    v = K.oracle_invalidate(blobs0)
    p0, pn, wn = v.p_prior, v.p_new, v.w_new
    g = p0["generation"]
    e.eq(v.outcome, fd.TXN_COMMITTED, "oracle verdict")
    b1_0, b7_0, b8_0 = d.b1, d.b7, d.b8
    cand_before = d.candidate()["valid"]
    wm, nm = w.mark(), K.nvs_mark(d)
    b9_before = d.b9
    if arm_wait is not None:
        d.arm_on()
        d.advance(arm_wait)
        st = d.invalidate(arm=False)
    elif tail is not None:
        st = d.invalidate(tail=tail)
    else:
        st = d.invalidate()
    # --- the outcome text, exactly one B9 publication
    e.eq(st.b9, K.b9_invalidated(g), "B9")
    e.eq(publishes(st), [K.b9_invalidated(g)], "B9 publications during the call (no candidate-consumption line)")
    # --- the durable records: exactly FBW then FBP, exactly the locked bytes, no Modbus read or write at all
    e.eq(st.violations_fb(("FBW", "FBP"), bytes_={"FBW": fd.pack_provision(wn), "FBP": fp.pack_profile(pn)}, reads=[]), [],
         "write audit (FBW then FBP, exact bytes, zero Modbus)")
    e.eq(st.fb_set_order, EXPECTED_SET_ORDER, "FB write order")
    e.eq([r for _n, _b, r in st.fb_sets], [0, 0], "ESP_OK results")
    img = K.blobs_of(d)
    e.eq(img.get(K_P), (fp.pack_profile(pn), True, True), "flash FBP")
    e.eq(img.get(K_W), (fd.pack_provision(wn), True, True), "flash FBW")
    # field-level (the payload is verbatim; only generation, flags, binding change)
    new_p = fp.unpack_profile(img[K_P][0])
    for f_name, _fmt, _n in fp.PROFILE_LAYOUT:
        if f_name in ("generation", "flags", "binding"):
            continue
        e.eq(new_p[f_name], p0[f_name], f"FBP.{f_name} kept verbatim")
    e.eq(new_p["generation"], g + 1, "FBP.generation = g+1")
    e.eq(new_p["flags"], p0["flags"] | 1, "FBP.flags bit0 set")
    e.eq(new_p["captured_epoch"], p0["captured_epoch"], "FBP.captured_epoch kept")
    e.eq(new_p["binding"], fp.seal_profile(dict(new_p))["binding"], "FBP re-sealed")
    e.ok(new_p["binding"] != p0["binding"], "FBP binding changed")
    e.eq(fp.classify_profile(fp.LOAD_OK, new_p), fp.PROFILE_INVALIDATED, "FB-A classifies the new record INVALIDATED")
    new_w = fd.unpack_provision(img[K_W][0])
    e.eq((new_w["hw_generation"], new_w["hw_binding"], new_w["prior_generation"], new_w["prior_binding"], new_w["last_op"]),
         (g + 1, new_p["binding"], g, p0["binding"], fd.PROV_OP_INVALIDATE), "FBW hw / prior / op")
    e.eq((new_w["hw_tag_key"], new_w["hw_record_schema"], new_w["flags"], new_w["magic"], new_w["schema"], new_w["size"]),
         (fd.FALLBACK_PROFILE_KEY, fp.PROFILE_SCHEMA, 0, fd.PROVISION_MAGIC, 1, 48), "FBW fixed fields")
    e.eq(fd.classify_witness(fd.LOAD_OK, new_w), fd.W_VALID, "the new witness is W_VALID")
    if p0["binding"] == GOLD["binding"] and g == GOLD_G:
        e.eq(new_w["binding"], GOLD_W_INV_BINDING, "golden W-INV witness binding")
    # --- the NVS event order: fresh read FBP then FBW, ONE health check; then the writer: health, FBW(+readback+health), FBP(+readback+health)
    kinds = [(o[0], o[1]) for o in K.nvs_events_since(d, nm)]
    fbp_k, fbw_k = fd.decimal_key(K_P), fd.decimal_key(K_W)
    w_present = K_W in blobs0                         # a two-step read of an absent key is the size probe only
    e.eq(kinds, [("get", fbp_k), ("read", fbp_k), ("get", fbw_k)] + ([("read", fbw_k)] if w_present else []) +
         [("stats", None), ("stats", None), ("set", fbw_k), ("get", fbw_k), ("read", fbw_k), ("stats", None),
          ("set", fbp_k), ("get", fbp_k), ("read", fbp_k), ("stats", None)], "NVS event order (witness first, readback + health per key)")
    # --- the mirror, class, texts
    e.eq(d.b1, "INVALIDATED", "B1")
    exp = K.expected_b2(fp.pack_profile(pn), fp.LOAD_OK, fd.pack_provision(wn), fd.LOAD_OK, fd.WHY_NONE, 0,
                        v.r.w.us + v.r.p.us)
    e.eq(K.parse_kv(d.b2), exp, "B2 fields")
    e.eq(d.b7, b7_after(b7_0, g + 1, new_p["binding"]), "B7 (payload kept, new g and b)")
    e.eq(d.b8, b8_after(b8_0, new_p["binding"]), "B8")
    e.eq((d.g["fallback_profile_class"], d.g["fallback_profile_why"]), (CLASS_NUM["INVALIDATED"], fd.WHY_NONE), "class / why")
    e.eq(d.arr("fallback_profile_bytes"), list(fp.pack_profile(pn)), "profile mirror = the readback")
    e.eq(d.arr("fallback_witness_bytes"), list(fd.pack_provision(wn)), "witness mirror = the readback")
    e.eq((d.g["fallback_profile_load"], d.g["fallback_witness_load"]), (fp.LOAD_OK, fp.LOAD_OK), "mirror loads")
    e.eq(d.g["fallback_profile_seen_hw_gen"], g + 1, "seen_hw_gen raised to the committed generation")
    e.eq(d.g["fallback_profile_present_seen"], 3, "present_seen: both keys")
    e.eq(d.g["fallback_profile_read_anomaly"], 0, "no read anomaly")
    e.eq((d.g["fallback_durable_last_err"], d.g["fallback_durable_last_us"]), (0, v.r.w.us + v.r.p.us), "B2 werr / us sources")
    e.ok(not d.g["fallback_profile_save_unconfirmed"] and not d.write_latched, "no SAVE_UNCONFIRMED overlay, no latch")
    e.ok(not fd.profile_writer_usable(d.g["fallback_profile_class"], d.g["fallback_profile_why"]),
         "an INVALIDATED profile is never writer-usable")
    # --- one-shot arm, candidate, B3..B6 idle, synchronous
    e.ok(not d.arm_state, "arm turned off")
    e.eq(list(d.sim.ent(d.arm_id).published), [True, False], "arm publications (on by the operator, off by the firmware, once)")
    e.eq((d.candidate()["valid"], d.candidate()["saveable"]), (False, False), "no candidate")
    e.ok(d.b3.startswith("st=IDLE;") and d.b3.endswith("sv=-"), f"B3 idle {d.b3!r}")
    e.eq((d.b4, d.b5[:6], d.b6[:6]), ("-", "v=NONE", "v=NONE"), "B4 / B5 / B6 idle")
    e.eq(st.elapsed_ms, 0, "no wait: zero virtual milliseconds")
    e.eq(D.idle_invariants(d), [], "idle invariants (no op flag, no mutex, no script running)")
    e.eq(D.text_invariants(d), [], "text invariants (<= 200, no hazard word, locked B9 prefixes)")
    extra = w.names(wm) - ASSIGN_COMMIT
    e.eq(sorted(extra), [], "globals assigned beyond the INVALIDATE set")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "manual_write_in_progress / op_in_progress / purpose / step never assigned")
    e.eq(d.modbus_writes(), [], "no Modbus write in the whole run")
    if candidate:
        e.ok(cand_before, "set-up: a candidate was pending")
        e.eq(b9_before.startswith("CANDIDATE READY"), True, "set-up: B9 showed the candidate")
    if env_check is not None:
        env_check(d, st, e)
    # --- reboot: INVALIDATED g+1, same bytes, class agrees with the oracle
    if reboot:
        flash = K.blobs_of(d)
        d.reboot()
        w.attach()
        e.eq(d.b1, "INVALIDATED", "after reboot B1")
        e.eq(K.blobs_of(d), flash, "boot wrote nothing")
        e.eq(d.model_class()[0], "INVALIDATED", "model oracle after reboot")
        e.eq(K.parse_kv(d.b2)["g"], str(g + 1), "after reboot g")
        e.eq(K.parse_kv(d.b2)["id"], f"{new_p['binding']:016X}", "after reboot id")
        e.eq((d.g["fallback_profile_class"], d.g["fallback_profile_why"]), (CLASS_NUM["INVALIDATED"], 0), "after reboot class / why")
        e.eq(d.g["fallback_profile_seen_hw_gen"], g + 1, "after reboot seen_hw_gen")
        e.ok(not fd.profile_writer_usable(d.g["fallback_profile_class"], d.g["fallback_profile_why"]), "after reboot not writer-usable")
    if tail_save:
        # a new Review + Save afterwards gets g+2 (base = max(g+1, hw = g+1, seen))
        d.review(expect="CANDIDATE_READY")
        e.ok(d.b3_field("prior") == "INVALIDATED", f"Review sees prior INVALIDATED ({d.b3_field('prior')})")
        e.eq((K.parse_kv(d.b2)["werr"], K.parse_kv(d.b2)["us"]), ("-", "-" if reboot else str(v.r.w.us + v.r.p.us)),
             "a later Review publishes the retained B2 werr / us of the INVALIDATE (RAM: gone after a reboot)")
        st2 = d.save()
        e.eq(st2.b9, f"SAVED - known-good profile generation {g + 2} saved (verified this boot)", "Save after INVALIDATE: B9")
        wv = fd.unpack_provision(K.blobs_of(d)[K_W][0])
        pv = fp.unpack_profile(K.blobs_of(d)[K_P][0])
        e.eq((pv["generation"], pv["flags"]), (g + 2, 0), "Save after INVALIDATE: FBP g+2, not invalidated")
        e.eq((wv["hw_generation"], wv["prior_generation"], wv["prior_binding"], wv["last_op"]),
             (g + 2, g + 1, new_p["binding"], fd.PROV_OP_SAVE), "Save after INVALIDATE: FBW")
        e.eq(d.b1, "VALID", "Save after INVALIDATE: B1")
        d.reboot()
        e.eq((d.b1, K.parse_kv(d.b2)["g"]), ("VALID", str(g + 2)), "Save after INVALIDATE: reboot VALID g+2")
    return e


# --- clean under every condition the design says is irrelevant (no supervision / NTP / arms / obligations / candidate)
def cond_bare(d):
    d.apply_env("bare")


def cond_write_arms(d):
    for name in D.WRITE_ARMS:
        d.write_arm(name, True)


def cond_all_leases(d):
    for name in ("fp_active", "dump_active"):
        d.lease(name)


def cond_lease(name):
    def f(d):
        d.lease(name)
    return f


CLEAN_CONDITIONS = {
    "no supervision, no NTP (fresh boot)": dict(pre=cond_bare),
    "all three write arms on": dict(pre=cond_write_arms),
    "active Free Power + Dump leases": dict(pre=cond_all_leases),
    "a pending candidate (consumed, no line of its own)": dict(candidate=True),
}
CLEAN_CONDITIONS["FBS record present and CLEAR"] = dict(drv_kw=dict(fbs="clear"))
CLEAN_CONDITIONS["housekeeping stopped (nothing else running)"] = dict(pre=lambda d: d.stop_housekeeping())
CLEAN_CONDITIONS["arm on for 119 s (inside the TTL)"] = dict(pre=None, arm_wait=119_000)
for _name in sorted(D.LEASE_RAM):
    CLEAN_CONDITIONS[f"lease RAM leg {_name}"] = dict(pre=cond_lease(_name))


def scn_clean_deferred_bus(mk) -> Errs:
    """INVALIDATE on the real (deferred) bus: no frame is queued, nothing is waited for, FBP / FBW only, even with a poller frame in
    flight AFTER the call (the call never enters the bus)."""
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    wm = w.mark()
    st = d.invalidate()
    e.ok(st.b9.startswith("INVALIDATED - "), f"INVALIDATED on a deferred bus: {st.b9[:40]!r}")
    e.eq(st.elapsed_ms, 0, "zero virtual ms on a deferred bus")
    e.eq((st.reads, st.writes), ([], []), "no frame queued")
    e.eq(d.sim.hub.frames, [], "no hub frame")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "flags never assigned")
    return e


# ---------------------------------------------------------------------------
# 2. REFUSALS
# ---------------------------------------------------------------------------
@dataclass
class Row:
    name: str
    text: str                                   # the FULL expected B9 text
    seed: object = "valid"
    pre: object = None                          # fn(d) before the call
    target_id: object = None                    # None = the stored profile's id (B2 id=)
    confirmation: object = None
    arm: bool = True
    candidate: bool = False                     # a REVIEW candidate is pending before the call
    fbs: object = None
    env: str = "trusted"
    stage: str = "gate"                         # "gate" (no NVS event at all) | "fresh" (fresh read happened, nothing written)
    mirror: str = "same"                        # "same" (B1/class unchanged) | "fresh" (the mirror was refreshed by the fresh read)
    drv: dict = field(default_factory=dict)
    locked: bool = False                        # the scenario itself holds the write mutex at the end (idle invariant)
    arm_consumed: bool = True
    fresh_reads: str = "both"                   # fresh stage: "both" (two keys read) | "none" (the handle is gone: no read reaches the NVS)
    flash_same: bool = True                     # False: a CRC-bad chunk is erased by the very read that finds it
    post: object = None                         # fn(d, st, e)
    flags_held: tuple = ()                      # globals the scenario set true that the firmware must leave true
    note: str = ""


def mutex_on(d):
    d.mutex(True)


def set_true(*names):
    def f(d):
        for n in names:
            d.sim.run_lambda(f"id({n}) = true;")
    return f


def seeded(**over):
    """A seed dict: the golden profile with fields overridden + a consistent witness."""
    p = D.gold_profile(**over)
    return {"fbp": p, "fbw": D.prov_bytes(p["generation"], p["binding"], max(p["generation"] - 1, 0))}


EXHAUSTED = seeded(generation=0xFFFFFFFF)
EXH_ID = f"{D.gold_profile(generation=0xFFFFFFFF)['binding']:016X}"
G_MAX_M1 = seeded(generation=0xFFFFFFFE)
G_MAX_M1_ID = f"{D.gold_profile(generation=0xFFFFFFFE)['binding']:016X}"
STALE_MIS = {"fbp": GOLD, "fbw": D.prov_bytes(7, 0x7777, 6)}     # FBW hw == g but another binding: B11 STALE (MISMATCH)
OTHER_ID = "0123456789ABCDEF"


def _row(name, text, **kw):
    return Row(name, PREFIX + text, **kw)


def _id_format_rows():
    rows = []
    for label, tid in (("lowercase hex", GOLD_ID.lower()), ("short 8-hex id (display id)", GOLD_ID[:8]),
                       ("15 characters", GOLD_ID[:15]), ("17 characters", GOLD_ID + "0"), ("empty", ""),
                       ("non-hex digit", "G" + GOLD_ID[1:]), ("trailing newline", GOLD_ID + "\n"),
                       ("leading space", " " + GOLD_ID[:15]), ("0x prefix", "0x" + GOLD_ID[:14]), ("the B2 placeholder '-'", "-"),
                       ("embedded space", GOLD_ID[:8] + " " + GOLD_ID[9:]), ("mixed case", GOLD_ID[:8].lower() + GOLD_ID[8:])):
        rows.append(_row(f"id format: {label}", "profile ID must be 16 hex characters", target_id=tid,
                         confirmation=f"INVALIDATE {tid}"))
    return rows


def _phrase_rows():
    rows = []
    t = GOLD_ID
    exp = f"confirmation phrase mismatch (expected 'INVALIDATE {t}')"
    for label, conf in (("lowercase", f"invalidate {t}"), ("trailing space", f"INVALIDATE {t} "), ("trailing newline", f"INVALIDATE {t}\n"),
                        ("SAVE phrase", f"SAVE {t}"), ("the id of another profile", f"INVALIDATE {OTHER_ID}"),
                        ("double space", f"INVALIDATE  {t}"), ("no space", f"INVALIDATE{t}"),
                        ("REPLACE CORRUPT suffix", f"INVALIDATE {t} REPLACE CORRUPT"), ("empty", ""), ("keyword only", "INVALIDATE "),
                        ("id only", t), ("lowercase id", f"INVALIDATE {t.lower()}"), ("short id", f"INVALIDATE {t[:8]}"),
                        ("leading space", f" INVALIDATE {t}"), ("tab separator", f"INVALIDATE\t{t}")):
        rows.append(_row(f"phrase: {label}", exp, target_id=t, confirmation=conf))
    return rows


def _wrong_id_rows():
    out = []
    for label, tid in (("last digit flipped", GOLD_ID[:-1] + "4"), ("first digit flipped", "E" + GOLD_ID[1:]),
                       ("the id the profile would have after INVALIDATE", GOLD_INVALIDATED_ID), ("all zero", "0" * 16),
                       ("the witness's prior binding", f"{0x6666:016X}"), ("all F", "F" * 16),
                       ("only the first 8 digits right", GOLD_ID[:8] + "0" * 8), ("only the last 8 digits right", "0" * 8 + GOLD_ID[8:])):
        out.append(_row(f"wrong id: {label}", "profile ID does not match the stored VALID profile", target_id=tid,
                        confirmation=f"INVALIDATE {tid}"))
    return out


def _class_rows():
    cases = (("NOT_CAPTURED (nothing stored)", "none", "NOT_CAPTURED"), ("INVALIDATED (repeat)", "invalidated", "INVALIDATED"),
             ("CORRUPT (garbage record)", "corrupt", "CORRUPT"), ("CORRUPT (wrong-size record)", "wsize", "CORRUPT"),
             ("CORRUPT_DOMAIN", "corrupt_domain", "CORRUPT_DOMAIN"), ("PROFILE_LOST (profile gone, witness remains)", "lost", "PROFILE_LOST"),
             ("PROFILE_STALE", "stale", "PROFILE_STALE"), ("PROFILE_STALE (witness binding mismatch)", STALE_MIS, "PROFILE_STALE"),
             ("PROFILE_LOST FIRST_SAVE_UNCONFIRMED (hw 1, no prior)", {"fbp": None, "fbw": D.prov_bytes(1, 0x1234, 0)}, "PROFILE_LOST"),
             ("CORRUPT profile + valid witness", {"fbp": bytes(range(96)), "fbw": D.prov_bytes(9, 0x1234, 8)}, "CORRUPT"),
             ("PROFILE_STALE (rolled back: witness ahead)", {"fbp": D.gold_profile(generation=5), "fbw": D.prov_bytes(9, 0x1234, 8)},
              "PROFILE_STALE"))
    rows = []
    for label, seed, cname in cases:
        rows.append(_row(f"class {label}", f"profile is {cname}; only a VALID profile can be invalidated", seed=seed, target_id=GOLD_ID,
                         confirmation=f"INVALIDATE {GOLD_ID}"))
    # the id of the CURRENT stored record of an INVALIDATED profile (a repeated INVALIDATE with the id the card would show)
    rows.append(_row("class INVALIDATED (repeat) with the invalidated record's own id",
                     "profile is INVALIDATED; only a VALID profile can be invalidated", seed="invalidated",
                     target_id=GOLD_INVALIDATED_ID, confirmation=f"INVALIDATE {GOLD_INVALIDATED_ID}"))
    # injected classes the boot cannot produce with a clear anomaly (defence in depth of I8)
    for cname in ("UNREADABLE", "SAVE_UNCONFIRMED"):
        rows.append(_row(f"class {cname} (RAM class injected, no anomaly)", f"profile is {cname}; only a VALID profile can be invalidated",
                         pre=(lambda d, c=cname: d.set_g("fallback_profile_class", CLASS_NUM[c])), target_id=GOLD_ID,
                         confirmation=f"INVALIDATE {GOLD_ID}"))
    return rows


def _anomaly_row_flow(d):
    d.erase("FBP")
    d.review()                                   # a fresh read: FBP vanished after being seen -> same-boot anomaly


def _unknown_flow(d):
    d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
    d.invalidate()                                # UNKNOWN: SAVE_UNCONFIRMED overlay + write latch


def _inj_seen(v):
    def f(d):
        d.set_g("fallback_profile_seen_hw_gen", v)
    return f


def _bus_rows():
    rows = []
    flags = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
             "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
             "reg244_apply_in_progress", "dump_operation_in_progress")
    for f in flags:
        rows.append(_row(f"bus busy: {f}", "inverter busy; try again", pre=set_true(f), flags_held=(f,), locked=(f == "manual_write_in_progress")))
    rows.append(_row("bus busy: the write mutex held >= 300 s (possible leak)", "inverter busy; try again",
                     pre=lambda d: (d.sim.run_lambda("id(manual_write_in_progress) = true; id(diag_write_lock_held) = true; "
                                                     "id(diag_write_lock_since_ms) = 1;"), d.advance(400_000)),
                     flags_held=("manual_write_in_progress",), locked=True, note="the SAVE LOCK_STUCK wording is not used by INVALIDATE (M 4.8 literal)"))
    rows.append(_row("bus busy: tx buffer not empty", "inverter busy; try again", pre=lambda d: setattr(d.sim.hub, "queued", 1)))
    rows.append(_row("bus busy: tx blocked (a frame is on the wire)", "inverter busy; try again", pre=lambda d: d.hold_bus(5000)))
    return rows


def refusal_rows() -> list:
    rows = [
        _row("arm not on", "ECCO Fallback Profile Arm is not on", arm=False, arm_consumed=False),
        _row("arm turned on then off by the operator", "ECCO Fallback Profile Arm is not on", arm=False, arm_consumed=False,
             pre=lambda d: (d.arm_on(), d.arm_off())),
        _row("arm expired (130 s, housekeeping TTL)", "ECCO Fallback Profile Arm is not on", arm=False, arm_consumed=False,
             pre=lambda d: (d.arm_on(), d.advance(130_000))),
        _row("arm not on + wrong id + wrong phrase: the arm refusal comes first", "ECCO Fallback Profile Arm is not on", arm=False,
             arm_consumed=False, target_id="zz", confirmation="nope"),
        _row("bad id + wrong phrase: the id format comes first", "profile ID must be 16 hex characters", target_id="zz",
             confirmation="nope"),
        _row("not loaded + wrong class: not loaded comes after the phrase and before everything else", T_NOT_LOADED,
             seed="none", drv=dict(boot=False), target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("boot never ran (durable state not loaded yet)", T_NOT_LOADED, drv=dict(boot=False), target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("not loaded flag cleared on a loaded profile", T_NOT_LOADED,
             pre=lambda d: d.set_g("fallback_profile_boot_loaded", False)),
        _row("read anomaly: FBP vanished after being seen (real flow: erase + Review)",
             T_ANOMALY, pre=_anomaly_row_flow, target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID}", mirror="same", note="the Review refreshed the mirror to UNREADABLE"),
        _row("read anomaly: boot read of FBP failed (unreadable seed)", T_ANOMALY,
             seed="unreadable", target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("read anomaly bit 1 injected", T_ANOMALY,
             pre=lambda d: d.set_g("fallback_profile_read_anomaly", 1)),
        _row("read anomaly bit 4 (unhealthy) injected", T_ANOMALY,
             pre=lambda d: d.set_g("fallback_profile_read_anomaly", 4)),
        _row("anomaly comes before the class check", T_ANOMALY, seed="stale",
             pre=lambda d: d.set_g("fallback_profile_read_anomaly", 2), target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("SAVE_UNCONFIRMED: a previous write outcome is unknown (real flow)",
             "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", pre=_unknown_flow, flags_held=(),
             post=lambda d, st, e: e.ok(d.b1 == "SAVE_UNCONFIRMED", "B1 stays SAVE_UNCONFIRMED")),
        _row("SAVE_UNCONFIRMED injected", "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first",
             pre=lambda d: d.set_g("fallback_profile_save_unconfirmed", True)),
        _row("unconfirmed comes before the class check", "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first",
             seed="stale", pre=lambda d: d.set_g("fallback_profile_save_unconfirmed", True), target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("generation exhausted (g = 0xFFFFFFFF)", "generation counter exhausted", seed=EXHAUSTED, target_id=EXH_ID,
             confirmation=f"INVALIDATE {EXH_ID}"),
        _row("g+1 == seen_hw_gen (injected 8)", "profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
             pre=_inj_seen(8)),
        _row("g+1 < seen_hw_gen (injected 9)", "profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
             pre=_inj_seen(9)),
        _row("seen_hw_gen = 0xFFFFFFFF", "profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
             pre=_inj_seen(0xFFFFFFFF)),
        _row("FBS record: a failback episode exists", "a failback episode record exists; only the firmware that created it can resolve it",
             fbs="episode"),
        _row("FBS record: corrupt", "Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds "
                                   "past it; do not erase NVS", fbs="corrupt"),
        _row("FBS record: unreadable at boot", "Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot "
                                              "be ruled out; Fallback never proceeds past it", fbs="unreadable"),
        _row("bus busy comes before the FBS check", "inverter busy; try again", fbs="episode", pre=mutex_on, flags_held=("manual_write_in_progress",),
             locked=True),
        _row("class check comes before the bus check", "profile is PROFILE_STALE; only a VALID profile can be invalidated", seed="stale",
             pre=mutex_on, target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}", flags_held=("manual_write_in_progress",), locked=True),
        _row("class forced VALID over an absent profile: the id 0000000000000000 never matches an ABSENT record",
             "profile ID does not match the stored VALID profile", seed="none",
             pre=lambda d: d.set_g("fallback_profile_class", CLASS_NUM["VALID"]), target_id="0" * 16, confirmation="INVALIDATE " + "0" * 16),
        _row("id mismatch comes before the generation check", "profile ID does not match the stored VALID profile", pre=_inj_seen(9),
             target_id=OTHER_ID, confirmation=f"INVALIDATE {OTHER_ID}"),
        _row("generation check comes before the bus check", "generation counter exhausted", seed=EXHAUSTED, pre=mutex_on, target_id=EXH_ID,
             confirmation=f"INVALIDATE {EXH_ID}", flags_held=("manual_write_in_progress",), locked=True),
    ]
    rows += [
        _row("arm turned on, then the dongle rebooted (ALWAYS_OFF)", "ECCO Fallback Profile Arm is not on", arm=False, arm_consumed=False,
             pre=lambda d: (d.arm_on(), d.reboot())),
        _row("id with an embedded NUL after the 16 digits", "profile ID must be 16 hex characters", target_id=GOLD_ID + "\x00",
             confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("phrase with an embedded NUL after the id", f"confirmation phrase mismatch (expected 'INVALIDATE {GOLD_ID}')",
             target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}\x00"),
        _row("phrase truncated at a NUL", f"confirmation phrase mismatch (expected 'INVALIDATE {GOLD_ID}')", target_id=GOLD_ID,
             confirmation="INVALIDATE\x00" + GOLD_ID),
    ]
    rows += [
        _row("phrase: REPLACE CORRUPT suffix on a CORRUPT profile (INVALIDATE has no such phrase)",
             f"confirmation phrase mismatch (expected 'INVALIDATE {GOLD_ID}')", seed="corrupt", target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID} REPLACE CORRUPT"),
        _row("phrase: the SAVE REPLACE CORRUPT phrase on a CORRUPT profile", f"confirmation phrase mismatch (expected 'INVALIDATE {GOLD_ID}')",
             seed="corrupt", target_id=GOLD_ID, confirmation=f"SAVE {GOLD_ID} REPLACE CORRUPT"),
    ]
    rows += _id_format_rows() + _phrase_rows() + _wrong_id_rows() + _class_rows() + _bus_rows()
    # a pending candidate is consumed by every refusal that passed the in-flight check
    rows += [
        _row("with a pending candidate: arm off", "ECCO Fallback Profile Arm is not on", arm=False, candidate=True, arm_consumed=False),
        _row("with a pending candidate: wrong phrase", f"confirmation phrase mismatch (expected 'INVALIDATE {GOLD_ID}')", candidate=True,
             confirmation="INVALIDATE"),
        _row("with a pending candidate: busy", "inverter busy; try again", candidate=True, pre=mutex_on, flags_held=("manual_write_in_progress",),
             locked=True),
        _row("with a pending candidate: class INVALIDATED", "profile is INVALIDATED; only a VALID profile can be invalidated", seed="invalidated",
             candidate=True, target_id=GOLD_ID, confirmation=f"INVALIDATE {GOLD_ID}"),
    ]
    # the fresh-read stage (the gate passed over the RAM mirror; the storage changed behind the mirror)
    anomaly = T_ANOMALY
    rows += [
        _row("fresh read: FBP replaced by another valid record behind the mirror -> same-boot divergence", anomaly, stage="fresh",
             mirror="fresh", pre=lambda d: d.put("FBP", D.gold_profile(reg245=7000))),
        _row("fresh read: FBP erased behind the mirror", anomaly, stage="fresh", mirror="fresh", pre=lambda d: d.erase("FBP")),
        _row("fresh read: FBW erased behind the mirror", anomaly, stage="fresh", mirror="fresh", pre=lambda d: d.erase("FBW")),
        _row("fresh read: FBW replaced behind the mirror", anomaly, stage="fresh", mirror="fresh",
             pre=lambda d: d.put("FBW", D.prov_bytes(9, 0x1234, 8))),
        _row("fresh read: FBP read error", anomaly, stage="fresh", mirror="fresh", pre=lambda d: d.fault_read("FBP", fd.IDF_FAIL)),
        _row("fresh read: FBW read error", anomaly, stage="fresh", mirror="fresh", pre=lambda d: d.fault_read("FBW", fd.IDF_FAIL)),
        _row("fresh read: storage unhealthy (INVALID page) -> F-H1, nothing written", anomaly, stage="fresh", mirror="fresh",
             pre=lambda d: d.unhealthy()),
        _row("fresh read: NVS handle gone -> every read unavailable", anomaly, stage="fresh", mirror="fresh", fresh_reads="none",
             pre=lambda d: setattr(d.sim.nvs_direct, "handle_value", 0)),
        _row("fresh read: NVS partition unavailable (NOT_INITIALIZED)", anomaly, stage="fresh", mirror="fresh",
             pre=lambda d: setattr(d.sim.nvs_direct, "unavailable", True)),
        _row("fresh read: profile CRC-bad behind the mirror (the read erases the bad chunk)", anomaly, stage="fresh", mirror="fresh",
             flash_same=False, pre=lambda d: d.put("FBP", GOLD_FBP, crc_ok=False)),
        _row("fresh read: the class the fresh read composes is not VALID (RAM class forced VALID over a B11 mismatch pair)",
             "profile is now PROFILE_STALE; nothing written", seed=STALE_MIS, stage="fresh", mirror="fresh",
             pre=lambda d: d.set_g("fallback_profile_class", CLASS_NUM["VALID"]), target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID}"),
        _row("fresh read: foreign witness tag (B9 SUPERSEDED), RAM class forced VALID", "profile is now PROFILE_STALE; nothing written",
             seed={"fbp": GOLD, "fbw": fd.pack_provision(fd.make_provision(7, GOLD["binding"], 6, 0x6666, 0x12345678, 1, fd.PROV_OP_SAVE))},
             stage="fresh", mirror="fresh", pre=lambda d: d.set_g("fallback_profile_class", CLASS_NUM["VALID"]), target_id=GOLD_ID,
             confirmation=f"INVALIDATE {GOLD_ID}"),
    ]
    return rows


def scn_refusal(mk, row: Row) -> Errs:
    """One refusal row: exact text, nothing written, zero Modbus, arm / candidate consumed, no storage access for a gate refusal,
    mirror untouched (or refreshed from the fresh read), the held flags untouched, only legal globals assigned."""
    e = Errs()
    d, w = new_drv(mk, seed=row.seed, fbs=row.fbs, env=row.env, **row.drv)
    if row.candidate:
        d.review(expect=None if row.candidate == "any" else "CANDIDATE_READY")
    if row.pre is not None:
        row.pre(d)
        w.attach()                               # a pre-step may have rebooted the dongle (new sim)
    b1_0, mirror_0 = d.b1, mirror_state(d)
    flash0 = K.blobs_of(d)
    b9_0 = d.b9
    cand_pending_0 = d.candidate()["valid"]
    e.pending = bool(cand_pending_0)             # the suite counts how many rows really had a candidate pending
    wm, nm = w.mark(), K.nvs_mark(d)
    kw = {}
    if row.target_id is not None:
        kw["target_id"] = row.target_id
    if row.confirmation is not None:
        kw["confirmation"] = row.confirmation
    st = d.invalidate(arm=row.arm, **kw)
    e.eq(d.b9, row.text, "B9")
    pubs = publishes(st)
    e.ok(pubs == [row.text] or (pubs == [] and b9_0 == row.text), f"exactly one B9 publication (or the identical text already shown): {pubs}")
    e.eq(st.violations_fb((), reads=[]), [], "nothing written, zero Modbus reads and writes")
    e.eq(st.fb_sets, [], "no FB set")
    e.eq(st.nvs_sets, [], "no NVS set at all")
    if row.flash_same:
        e.eq(K.blobs_of(d), flash0, "flash image untouched")
    e.ok(not d.arm_state, "arm off after the call")
    if row.arm:
        e.eq(list(d.sim.ent(d.arm_id).published)[-1:], [False], "the firmware turned the arm off (one-shot)")
    if row.stage == "gate":
        e.eq(K.nvs_events_since(d, nm), [], "a gate refusal costs no storage access at all (cheap checks first)")
    else:
        kinds = [(o[0], o[1]) for o in K.nvs_events_since(d, nm)]
        fbp_k, fbw_k = fd.decimal_key(K_P), fd.decimal_key(K_W)
        e.ok(all(k[0] != "set" for k in kinds), "no NVS set in a fresh-read refusal")
        if row.fresh_reads == "both":
            e.ok(("get", fbp_k) in kinds and ("get", fbw_k) in kinds, f"the fresh read touched both keys {kinds[:6]}")
        else:
            e.ok(all(k[0] == "stats" for k in kinds) and len(kinds) == 1, f"only the health check reached the NVS: {kinds}")
        e.eq([k for k in kinds if k[0] == "stats"].__len__(), 1, "exactly one health check (the writer never started)")
    # the candidate
    if cand_pending_0:
        e.eq((d.candidate()["valid"], d.candidate()["saveable"]), (False, False), "the pending candidate is consumed")
        e.ok(d.b3.startswith("st=IDLE;"), f"B3 idle after consumption: {d.b3[:30]!r}")
        e.eq((d.b4, d.b5[:6], d.b6[:6]), ("-", "v=NONE", "v=NONE"), "B4 / B5 / B6 idle after consumption")
    # the mirror
    if row.mirror == "same":
        e.eq(d.b1, b1_0, "B1 unchanged")
        e.eq(mirror_state(d), mirror_0, "mirror globals unchanged")
        allowed = ASSIGN_GATE
    else:
        allowed = ASSIGN_FRESH
    extra = w.names(wm) - allowed
    e.eq(sorted(extra), [], "globals assigned beyond the allowed set")
    e.eq(sorted((w.names(wm) & set(FLAG_GLOBALS)) | (w.names(wm) & {"fallback_profile_save_unconfirmed"})), [],
         "flags / overlay never assigned by a refusal")
    for f in row.flags_held:
        e.ok(d.g[f] is True, f"{f} left exactly as the scenario set it (the firmware neither took nor released it)")
    e.eq(st.elapsed_ms, 0, "refusal is immediate (no wait)")
    e.eq(D.idle_invariants(d, locked=row.locked or bool(row.flags_held)), [], "idle invariants")
    e.eq(D.text_invariants(d), [], "text invariants")
    if row.post is not None:
        row.post(d, st, e)
    return e


def scn_refusal_with_candidate(mk, row: Row) -> Errs:
    """The same refusal row, but a REVIEW candidate (whatever its kind: saveable or not) is pending when the call arrives: every refusal
    that passed the in-flight check consumes it (IE2: master 4.8 'invalidate any candidate'), with no B9 line of its own."""
    import dataclasses
    return scn_refusal(mk, dataclasses.replace(row, candidate="any", name=row.name + " [candidate pending]"))


def scn_refusal_then_retry(mk, row: Row, retry_pre) -> Errs:
    """A refusal consumed the arm and the candidate and nothing else: once the cause is gone a fresh arm + the same call succeeds."""
    e = Errs()
    d, w = new_drv(mk)
    row.pre(d)
    st = d.invalidate(arm=row.arm)
    e.eq(d.b9, row.text, "refused first")
    retry_pre(d)
    st2 = d.invalidate()
    e.eq(st2.b9, K.b9_invalidated(GOLD_G), "retry after the cause is gone: INVALIDATED")
    e.eq(st2.violations_fb(("FBW", "FBP"), reads=[]), [], "retry writes exactly FBW then FBP")
    return e


def scn_arm_is_one_shot(mk) -> Errs:
    """One arm, one call: a second call (arm not re-armed) is refused with the arm text even though the first succeeded."""
    e = Errs()
    d, w = new_drv(mk)
    st = d.invalidate()
    e.ok(st.b9.startswith("INVALIDATED - "), "first call succeeds")
    st2 = d.invalidate(arm=False, target_id=GOLD_INVALIDATED_ID)
    e.eq(st2.b9, PREFIX + "ECCO Fallback Profile Arm is not on", "second call without a fresh arm")
    e.eq(st2.fb_sets, [], "nothing written by the second call")
    st3 = d.invalidate(target_id=GOLD_INVALIDATED_ID)
    e.eq(st3.b9, PREFIX + "profile is INVALIDATED; only a VALID profile can be invalidated", "repeated INVALIDATE refused (class INVALIDATED)")
    e.eq(st3.fb_sets, [], "nothing written by the repeated INVALIDATE")
    e.ok(not d.arm_state, "arm off")
    return e


def scn_arm_survives_candidate_expiry(mk) -> Errs:
    """The arm is NOT turned off by candidate expiry (120 s), only by its own TTL / the next execute / a Review: an INVALIDATE armed 50 s
    after a Review still works after the candidate expired at 120 s."""
    e = Errs()
    d, w = new_drv(mk)
    d.review(expect="CANDIDATE_READY")
    d.advance(50_000)
    d.arm_on()
    d.advance(75_000)                              # t = 125 s after the Review: candidate expired, arm on for 75 s
    e.ok(d.b3.startswith("st=IDLE;"), f"candidate expired: {d.b3[:20]!r}")
    e.ok(d.arm_state, "arm still on after the candidate expired")
    st = d.invalidate(arm=False)
    e.ok(st.b9.startswith("INVALIDATED - "), f"INVALIDATE after candidate expiry: {st.b9[:40]!r}")
    return e


def scn_wrong_tokens(mk) -> Errs:
    """Only the exact token INVALIDATE reaches the INVALIDATE script: every other spelling (with the INVALIDATE id and phrase that WOULD
    invalidate) goes to the SAVE gate, which refuses it; nothing is written, the arm is consumed, the profile stays VALID g7."""
    e = Errs()
    for tok in ("invalidate", "INVALIDATE ", " INVALIDATE", "Invalidate", "INVALIDATEX", "INVALID", "CAPTURE", "PROVISION", "RESTORE",
                "ACKNOWLEDGE", "", "INVALIDATE\n", "SAVE"):
        d, w = new_drv(mk)
        if tok == "SAVE":
            d.review(expect="CANDIDATE_READY")
        d.arm_on()
        st = d.execute(tok, GOLD_ID, f"INVALIDATE {GOLD_ID}")
        e.eq(st.violations_fb((), reads=[]), [], f"token {tok!r}: nothing written")
        e.ok(not d.arm_state, f"token {tok!r}: arm consumed")
        if tok == "RESTORE":
            e.eq(d.b9, "RESTORE REFUSED - not implemented in this firmware", "RESTORE reserved")
        elif tok == "ACKNOWLEDGE":
            e.eq(d.b9, "ACKNOWLEDGE REFUSED - not implemented in this firmware", "ACKNOWLEDGE reserved")
        elif tok == "SAVE":
            e.ok(d.b9.startswith("SAVE REFUSED - "), f"token SAVE with an INVALIDATE id / phrase is refused by the SAVE gate: {d.b9[:60]!r}")
        else:
            e.ok(d.b9.startswith("REFUSED - unsupported action '"), f"token {tok!r}: B9 {d.b9[:50]!r}")
        e.eq(d.b1, "VALID", f"token {tok!r}: profile untouched")
        e.eq(d.stored("FBP")["generation"], GOLD_G, f"token {tok!r}: stored profile still g7")
    return e


# ---------------------------------------------------------------------------
# 3. IN-FLIGHT / BUS / RACES
# ---------------------------------------------------------------------------
def scn_inflight_save(mk) -> Errs:
    """A second execute (INVALIDATE) while a SAVE is in flight: the in-flight refusal changes NOTHING but the arm and B9; the SAVE
    then commits exactly the reviewed bytes."""
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    d.review(expect="CANDIDATE_READY")
    st1 = d.save(idle=False)
    e.ok(d.g["fallback_profile_op_in_progress"] and d.g["fallback_profile_op_purpose"] == 2, "set-up: SAVE in flight (op_in_progress, purpose SAVE)")
    e.ok(d.b3.startswith("st=SAVING;"), f"set-up: B3 {d.b3[:20]!r}")
    d.arm_on()
    snap = d.snapshot()
    wm, nm = w.mark(), K.nvs_mark(d)
    st2 = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
    e.eq(d.b9, PREFIX + "another Fallback Profile operation is in progress", "in-flight refusal text")
    e.ok(not d.arm_state, "arm turned off")
    e.eq(st2.fb_sets, [], "no write by the refused call")
    e.eq(K.nvs_events_since(d, nm), [], "no storage access by the refused call")
    diff = d.diff(snap)
    exec_names = {"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation",
                  "fallback_profile_exec_hb_ok"}
    e.eq(sorted(set(diff["globals"]) - exec_names), [], "globals changed by the in-flight refusal (only the api action's own copies)")
    e.ok("fallback_profile_last_result_text" in diff["published"] and set(diff["published"]) <= {"fallback_profile_arm", "fallback_profile_last_result_text"},
         f"entities published by the in-flight refusal: only the arm and B9 ({sorted(diff['published'])})")
    e.eq(sorted(w.names(wm) - exec_names), [], "assigned names by the in-flight refusal")
    e.ok(d.g["fallback_profile_op_in_progress"] and d.g["manual_write_in_progress"], "the SAVE still holds its flags")
    d.idle()
    e.ok(d.b9.startswith("SAVED - "), f"the SAVE still completes: {d.b9[:40]!r}")
    pn = fp.unpack_profile(K.blobs_of(d)[K_P][0])
    e.eq(pn["generation"], GOLD_G + 1, "the SAVE committed g8")
    e.eq(D.idle_invariants(d), [], "idle invariants after the SAVE")
    return e


def scn_inflight_review(mk) -> Errs:
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    d.press_review(idle=False)
    e.ok(d.g["fallback_profile_op_in_progress"], "set-up: REVIEW in flight")
    d.arm_on()
    wm = w.mark()
    st = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
    e.eq(d.b9, PREFIX + "another Fallback Profile operation is in progress", "in-flight refusal while a REVIEW runs")
    e.ok(not d.arm_state, "arm off")
    e.eq(st.fb_sets, [], "nothing written")
    d.idle()
    e.ok(d.b3.startswith("st=CANDIDATE_READY;"), f"the REVIEW completes: {d.b3[:30]!r}")
    return e


def scn_inflight_save_every_phase(mk) -> Errs:
    """FB-B2 serialisation proof: an INVALIDATE attempted at EVERY phase of an in-flight SAVE (accept, idle wait, each of the four reads,
    the pre-commit drain, between the two final lambdas' publication points) is refused with the in-flight text, touches no storage, writes
    nothing, leaves the SAVE's flags alone, and the SAVE still commits the reviewed bytes; right after the release an INVALIDATE works."""
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    d.review(expect="CANDIDATE_READY")
    d.save(idle=False)
    phases, attempts = set(), 0
    for i in range(120):
        if not d.g["fallback_profile_op_in_progress"]:
            break
        phases.add((d.g["fallback_profile_step"], d.g["fallback_profile_capture_state"]))
        d.arm_on()
        nm, wr0, wm = K.nvs_mark(d), len(d.modbus_writes()), w.mark()
        st = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
        attempts += 1
        e.eq(d.b9, PREFIX + "another Fallback Profile operation is in progress", f"attempt {i}: in-flight refusal text")
        e.ok(not d.arm_state, f"attempt {i}: arm off")
        e.eq(st.fb_sets, [], f"attempt {i}: nothing written")
        e.eq(K.nvs_events_since(d, nm), [], f"attempt {i}: no storage access")
        e.eq(len(d.modbus_writes()), wr0, f"attempt {i}: no Modbus write")
        e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], f"attempt {i}: the INVALIDATE never assigned a bus flag")
        e.ok(d.g["fallback_profile_op_in_progress"] and d.g["manual_write_in_progress"] and d.g["fallback_profile_op_purpose"] == 2,
             f"attempt {i}: the SAVE still holds its flags")
        d.advance(45)
    else:
        e.ok(False, "the SAVE never finished within the attempt budget")
    e.ok(attempts >= 8, f"at least 8 distinct instants of the SAVE were attacked ({attempts})")
    e.eq(sorted(phases), [(1, 4), (2, 4), (3, 4), (4, 4)],
         "the attempts covered every phase a SAVE can be in between loop iterations: the four read steps (SAVING); the pre-commit drain and the "
         "two final lambdas run synchronously in one pass, so no call can land between them")
    d.idle()
    e.ok(d.b9.startswith("SAVED - "), f"the SAVE completed: {d.b9[:40]!r}")
    pn = fp.unpack_profile(K.blobs_of(d)[K_P][0])
    e.eq(pn["generation"], GOLD_G + 1, "the SAVE committed g8 (its reviewed bytes)")
    e.eq(D.idle_invariants(d), [], "idle invariants after the SAVE")
    st2 = d.invalidate()
    e.ok(st2.b9.startswith("INVALIDATED - "), f"right after the SAVE released the bus the INVALIDATE works: {st2.b9[:36]!r}")
    pn2 = fp.unpack_profile(K.blobs_of(d)[K_P][0])
    e.eq(pn2["generation"], GOLD_G + 2, "INVALIDATED g9")
    e.eq([n for n, _b, _r in st2.fb_sets], ["FBW", "FBP"], "the INVALIDATE wrote the witness first, then the profile")
    return e


def scn_inflight_review_every_phase(mk) -> Errs:
    """The same attack against an in-flight REVIEW (it holds the shared mutex while it reads): every attempt is refused, nothing is written,
    the REVIEW completes with its candidate."""
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    d.press_review(idle=False)
    n = 0
    for i in range(120):
        if not d.g["fallback_profile_op_in_progress"]:
            break
        d.arm_on()
        nm, wr0 = K.nvs_mark(d), len(d.modbus_writes())
        st = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
        n += 1
        e.eq(d.b9, PREFIX + "another Fallback Profile operation is in progress", f"attempt {i}: in-flight refusal while the REVIEW reads")
        e.eq(st.fb_sets, [], f"attempt {i}: nothing written")
        e.eq(K.nvs_events_since(d, nm), [], f"attempt {i}: no storage access")
        e.eq(len(d.modbus_writes()), wr0, f"attempt {i}: no Modbus write")
        e.ok(d.g["fallback_profile_op_in_progress"] and d.g["manual_write_in_progress"], f"attempt {i}: the REVIEW still holds its flags")
        d.advance(45)
    e.ok(n >= 6, f"at least 6 instants of the REVIEW were attacked ({n})")
    d.idle()
    e.ok(d.b3.startswith("st=CANDIDATE_READY;"), f"the REVIEW completed with its candidate: {d.b3[:30]!r}")
    return e


def scn_inflight_real_writer(mk, script: str) -> Errs:
    """A REAL Free Power / Dump / Manual TOU writer script (not an injected flag) parked mid-flight while holding the shared write mutex: the
    INVALIDATE is refused ('inverter busy; try again'), writes and reads nothing, never touches the writer's flags; once the writer's own
    flags are released the same call, re-armed, succeeds."""
    import _fbb2_gates_races as GR
    e = Errs()
    d, w = new_drv(mk, mode=("deferred", 120))
    row = [x for x in GR.WRITERS if x[0] == script][0]
    d.sim.safety_exempt = True            # the admitted writer writes the inverter by design (it is the writer under test)
    row[2](d.sim)
    GR._start_writer(d.sim, script)
    e.eq(d.g[row[1]], 1, f"set-up: the real {script} was admitted ({row[1]} == 1)")
    e.ok(d.g["manual_write_in_progress"] is True, "set-up: the writer holds the shared write mutex")
    held = {k: d.g[k] for k in FLAG_GLOBALS}
    d.arm_on()
    nm, wr0, wm = K.nvs_mark(d), len(d.modbus_writes()), w.mark()
    st = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
    e.eq(d.b9, PREFIX + "inverter busy; try again", f"{script} in flight: busy refusal")
    e.eq(st.fb_sets, [], "nothing written")
    e.eq(K.nvs_events_since(d, nm), [], "no storage access (the mirror-level gate refused first)")
    e.eq(len(d.modbus_writes()), wr0, "the refused call issued no Modbus operation")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "the INVALIDATE never assigned a bus flag")
    e.eq({k: d.g[k] for k in FLAG_GLOBALS}, held, "every bus flag is exactly as the writer left it")
    e.ok(not d.arm_state, "arm turned off by the refused call (one-shot)")
    # release the writer's own flags (the harness does not model every later lambda of the writer): the same call then succeeds
    d.sim.run_lambda("id(manual_write_in_progress) = false; id(free_power_operation_in_progress) = false; id(dump_operation_in_progress) = false;")
    blocked = bool(d.sim.hub.tx_blocked())
    d.arm_on()
    d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}", idle=False)
    if blocked:
        e.eq(d.b9, PREFIX + "inverter busy; try again", "flags released but the writer's frame is still in flight (tx blocked): still busy, the bus guard is independent of the flags")
        d.advance(2000)
        d.arm_on()
        d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}")
    e.ok(d.b9.startswith("INVALIDATED - "), f"once the writer released the flags and its frame completed the re-armed call succeeds: {d.b9[:44]!r}")
    return e


def scn_invalidate_then_save_same_instant(mk) -> Errs:
    """Two operator calls back to back (no time between them): INVALIDATE first consumes the candidate and completes atomically; the SAVE
    behind it cannot slip in on the stale Review (no saveable candidate) and writes nothing."""
    e = Errs()
    d, w = new_drv(mk)
    d.review(expect="CANDIDATE_READY")
    cid = d.b4
    d.arm_on()
    st1 = d.invalidate()
    e.ok(st1.b9.startswith("INVALIDATED - "), f"the INVALIDATE completed: {st1.b9[:30]!r}")
    d.arm_on()
    nm = K.nvs_mark(d)
    st2 = d.execute("SAVE", cid, f"SAVE {cid}")
    e.eq(d.b9, "SAVE REFUSED - no saveable candidate - press Review Current Configuration first", "the SAVE behind the INVALIDATE: no candidate")
    e.eq(st2.fb_sets, [], "the SAVE wrote nothing")
    e.eq(K.nvs_events_since(d, nm), [], "the SAVE touched no storage")
    e.eq(d.b1, "INVALIDATED", "B1 INVALIDATED")
    e.eq(D.idle_invariants(d), [], "idle invariants")
    return e


def scn_inflight_injected(mk, how: str) -> Errs:
    """op_in_progress / dispatch running with a candidate pending: arm off only, the candidate is NOT consumed (the in-flight refusal is
    the only call that leaves it alone)."""
    e = Errs()
    d, w = new_drv(mk)
    d.review(expect="CANDIDATE_READY")
    if how == "op_in_progress":
        d.sim.g["fallback_profile_op_in_progress"] = True
    else:
        d.sim.hold_script_running("fallback_profile_capture_dispatch", 60_000)
        d.sim.run_for(1)
    d.arm_on()
    snap = d.snapshot()
    wm, nm = w.mark(), K.nvs_mark(d)
    st = d.execute("INVALIDATE", GOLD_ID, f"INVALIDATE {GOLD_ID}")
    e.eq(d.b9, PREFIX + "another Fallback Profile operation is in progress", f"in-flight refusal ({how})")
    e.ok(not d.arm_state, "arm off")
    e.eq((d.candidate()["valid"], d.candidate()["saveable"]), (True, True), "the candidate is untouched by an in-flight refusal")
    e.ok(d.b3.startswith("st=CANDIDATE_READY;"), "B3 still shows the candidate")
    e.eq(st.fb_sets, [], "nothing written")
    e.eq(K.nvs_events_since(d, nm), [], "no storage access")
    e.eq(st.reads, [], "no Modbus read")
    exec_names = {"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation",
                  "fallback_profile_exec_hb_ok"}
    e.eq(sorted(w.names(wm) - exec_names), [], "assigned names")
    return e


def scn_busy_then_retry(mk, flag: str) -> Errs:
    """A busy refusal neither takes nor releases the bus flag; once the bus is free the same call (re-armed) succeeds."""
    e = Errs()
    d, w = new_drv(mk)
    set_true(flag)(d) if flag != "tx" else setattr(d.sim.hub, "queued", 1)
    wm = w.mark()
    st = d.invalidate()
    e.eq(d.b9, PREFIX + "inverter busy; try again", f"busy refusal ({flag})")
    if flag != "tx":
        e.ok(d.g[flag] is True, f"{flag} still held")
        e.eq(w.values(flag, wm), [], f"{flag} never assigned by the refusal")
        d.sim.run_lambda(f"id({flag}) = false;")
    else:
        d.sim.hub.queued = 0
    st2 = d.invalidate()
    e.ok(st2.b9.startswith("INVALIDATED - "), f"after the bus is free: {st2.b9[:30]!r}")
    return e


def _race_hook(d, how):
    """At the fresh read's health check (the 5th event of the lambda, after the gate said idle) make the bus busy."""
    n = [0]

    def hook(op, key):
        if op == "stats":
            n[0] += 1
            if n[0] == 1:
                if how == "dispatch_running":
                    d.sim.running.add("fallback_profile_capture_dispatch")
                elif how == "tx_blocked":
                    d.sim.hub.in_flight_until = d.sim.now_ms + 5000
                elif how == "tx_nonempty":
                    d.sim.hub.queued = 1
                else:
                    d.sim.g[how] = True
    d.sim.nvs_direct.before_op = hook


RACES = ("manual_write_in_progress", "correction_in_progress", "verification_pending", "verification_read_active",
         "free_power_operation_in_progress", "free_power_recovery_force_in_progress", "free_power_recovery_accept_in_progress",
         "reg244_apply_in_progress", "dump_operation_in_progress", "fallback_profile_op_in_progress", "dispatch_running", "tx_blocked",
         "tx_nonempty")


def scn_bus_race(mk, how: str) -> Errs:
    """The bus turns busy AFTER the gate and the fresh read but before the commit: the last-statement bus check refuses with the busy
    text, nothing is written, the foreign flag is left alone."""
    e = Errs()
    d, w = new_drv(mk)
    _race_hook(d, how)
    wm, nm = w.mark(), K.nvs_mark(d)
    st = d.invalidate()
    e.eq(d.b9, PREFIX + "inverter busy; try again", f"busy at the commit ({how})")
    e.eq(st.fb_sets, [], "nothing written")
    kinds = [(o[0], o[1]) for o in K.nvs_events_since(d, nm)]
    fbp_k, fbw_k = fd.decimal_key(K_P), fd.decimal_key(K_W)
    e.eq(kinds, [("get", fbp_k), ("read", fbp_k), ("get", fbw_k), ("read", fbw_k), ("stats", None)],
         "the lambda stopped after the fresh read (no writer health check, no set)")
    e.eq(d.b1, "VALID", "B1 still VALID")
    e.ok(not d.write_latched and not d.g["fallback_profile_save_unconfirmed"], "no latch / overlay")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "the firmware never assigned a bus flag")
    return e


def scn_gate_mirror_vs_commit_time(mk) -> Errs:
    """The bus flags are re-read for the final check: a flag that was busy at the gate and idle at the commit does not matter (the
    gate refused), and one that is idle at the gate and busy at the commit refuses (scn_bus_race). Here: busy at the gate -> refused with
    NO storage access, flag cleared by the scenario right after -> a re-armed call succeeds."""
    return scn_busy_then_retry(mk, "manual_write_in_progress")


# ---------------------------------------------------------------------------
# 4. WRITER-STAGE REFUSALS (nothing written, no latch)
# ---------------------------------------------------------------------------
def scn_writer_refusal(mk, kind: str) -> Errs:
    e = Errs()
    d, w = new_drv(mk)
    n = [0]
    if kind == "handle":
        def hook(op, key):
            if op == "stats":
                n[0] += 1
                if n[0] == 1:
                    d.sim.nvs_direct.handle_value = 0
        want = PREFIX + "storage unavailable - nothing written"
    else:
        def hook(op, key):
            if op == "stats":
                n[0] += 1
                if n[0] == 2:
                    d.sim.nvs_direct.healthy = False
        want = PREFIX + "storage not healthy - nothing written"
    d.sim.nvs_direct.before_op = hook
    mirror_0 = mirror_state(d)
    wm = w.mark()
    st = d.invalidate()
    e.eq(d.b9, want, f"writer refusal ({kind})")
    e.eq(st.fb_sets, [], "nothing written")
    e.eq(d.b1, "VALID", "B1 unchanged")
    e.ok(not d.write_latched and not d.g["fallback_profile_save_unconfirmed"], "a refusal sets neither the latch nor the overlay")
    m1 = mirror_state(d)
    for k in ("fallback_profile_bytes", "fallback_witness_bytes", "fallback_profile_class", "fallback_profile_why"):
        e.eq(m1[k], mirror_0[k], f"mirror {k} unchanged")
    e.eq(d.g["fallback_profile_seen_hw_gen"], GOLD_G, "seen_hw_gen unchanged")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "flags never assigned")
    return e


# ---------------------------------------------------------------------------
# 5. POWER CUTS
# ---------------------------------------------------------------------------
CUT_SEEDS = dict(SEEDS_CLEAN)


def cut_expectation(points_landed: tuple) -> tuple:
    """Hand table (master 5.3 INVALIDATE of VALID gN): which writes landed -> the class the next boot derives."""
    w_landed, p_landed = points_landed
    if not w_landed and not p_landed:
        return "VALID", GOLD_G
    if w_landed and not p_landed:
        return "PROFILE_STALE", GOLD_G
    return "INVALIDATED", GOLD_G + 1


def scn_cut_sweep(mk, seed) -> tuple:
    """A power cut BEFORE and AFTER every direct-NVS event of one INVALIDATE; then the REAL on_boot. Returns (errs, rows)."""
    e = Errs()
    e.classes = []
    make = lambda: mk(seed=seed)          # noqa: E731
    probe = make()
    probe.sim.nvs_direct.events = 0
    nm0 = K.nvs_mark(probe)
    probe.invalidate()
    ops = K.nvs_events_since(probe, nm0)
    i_w = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == fd.decimal_key(K_W))
    i_p = next(i for i, o in enumerate(ops) if o[0] == "set" and o[1] == fd.decimal_key(K_P))
    n_events = len(ops)
    n_pre = i_w - 1                      # events before the writer's own first event (its health check sits right before the FBW set)
    e.eq((n_events - n_pre, i_w < i_p), (9, True), "the writer is 9 NVS events (health, FBW set + readback + health, FBP set + readback + health), FBW first")
    e.eq([o[0] for o in ops[:n_pre]], ["get", "read", "get", "read", "stats"][:n_pre] if n_pre == 5 else ["get", "read", "get", "stats"],
         "the fresh read is FBP, FBW, one health check")
    rows = D.sweep_nvs_cuts(make, lambda x: x.invalidate())
    e.eq(len(rows), 2 * n_events + 2, "sweep rows (a cut before and after every event + the two no-cut rows)")
    for row in rows:
        pnt = row.point
        landed = (pnt >= 2 * i_w + 1, pnt >= 2 * i_p + 1)
        want_cls, want_g = cut_expectation(landed)
        d = row.drv
        lab = row.label
        e.eq(row.error, None, f"{lab}: no unexpected exception")
        e.eq(row.cut, pnt < 2 * n_events, f"{lab}: a power cut was raised iff the point is inside the operation")
        e.eq([n for n, _b, _r in row.sets_before_cut], ["FBW", "FBP"][:sum(landed)], f"{lab}: sets issued before the cut")
        e.eq(d.b1, want_cls, f"{lab}: class after reboot (locked table)")
        e.classes.append(d.b1)
        e.eq(d.model_class()[0], want_cls, f"{lab}: class after reboot (independent model oracle)")
        # the oracle replays the same cut on the model
        rel = pnt - 2 * n_pre                  # the writer's first event follows the fresh read
        if pnt < 2 * n_events:
            blobs = K.copy_blobs(make())
            if rel >= 0:
                v = K.oracle_invalidate(blobs, cut_point=rel)
                e.eq(K.class_after_boot(v.nvs_after)[0], want_cls, f"{lab}: class after reboot (writer model replayed with the cut)")
        e.eq(K.parse_kv(d.b2)["g"], str(want_g), f"{lab}: B2 g after reboot")
        e.eq(D.idle_invariants(d), [], f"{lab}: nothing left held after reboot")
        e.ok(not d.g["fallback_profile_save_unconfirmed"] and not d.write_latched, f"{lab}: SAVE_UNCONFIRMED never survives a reboot")
        e.eq(d.g["fallback_profile_read_anomaly"], 0, f"{lab}: no read anomaly after boot")
        e.eq([x for x in d.nvs_set_history() if x[0] == d.boots], [], f"{lab}: the boot itself wrote nothing")
        if want_cls == "PROFILE_STALE":
            e.eq(K.parse_kv(d.b2)["why"], "INT", f"{lab}: STALE reason INTERRUPTED")
        # the intent of a half-landed INVALIDATE is honoured: STALE is unusable; and a Review + Save recovers with g+2
        if want_cls == "PROFILE_STALE":
            d.review(expect="CANDIDATE_READY")
            st = d.save()
            e.eq(st.b9, f"SAVED - known-good profile generation {GOLD_G + 2} saved (verified this boot)", f"{lab}: Save after a half-landed INVALIDATE = g+2")
    return e, rows


# ---------------------------------------------------------------------------
# 6. NVS WRITE FAULTS
# ---------------------------------------------------------------------------
HAND_TABLE = (
    # (label, faults {key: WriteFault}, TxnOutcome, witness_advanced, FBP set attempted, mirror class, B1, next-boot class (None: bytes dependent))
    ("clean", {}, fd.TXN_COMMITTED, False, True, "INVALIDATED", "INVALIDATED", "INVALIDATED"),
    ("F1 FBW pre-write code, readback == prior", {"FBW": K.make_fault("FBW", fd.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD)},
     fd.TXN_NOT_COMMITTED, False, False, "VALID", "VALID", "VALID"),
    ("F1b FBW READ_ONLY, readback == prior", {"FBW": K.make_fault("FBW", fd.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD)},
     fd.TXN_NOT_COMMITTED, False, False, "VALID", "VALID", "VALID"),
    ("F2 FBW NO_MEM (raw), landed nowhere", {"FBW": K.make_fault("FBW", fd.IDF_ERR_NO_MEM, H.VIS_OLD)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", "VALID"),
    ("F2b FBW NOT_ENOUGH_SPACE (raw)", {"FBW": K.make_fault("FBW", fd.IDF_ERR_NVS_NOT_ENOUGH_SPACE, H.VIS_OLD)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", "VALID"),
    ("F2c FBW flash error, FBW did land", {"FBW": K.make_fault("FBW", fd.IDF_ERR_FLASH_OP_FAIL, H.VIS_NEW)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", "PROFILE_STALE"),
    ("F3 FBW OK but another record reads back", {"FBW": K.make_fault("FBW", fd.IDF_OK, H.VIS_OTHER)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", None),
    ("F3b FBW OK, readback absent", {"FBW": K.make_fault("FBW", fd.IDF_OK, H.VIS_ABSENT)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", None),
    ("F4 FBW committed, FBP pre-write code", {"FBP": K.make_fault("FBP", fd.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD)},
     fd.TXN_NOT_COMMITTED, True, True, "PROFILE_STALE", "PROFILE_STALE", "PROFILE_STALE"),
    ("F4b FBW committed, FBP not initialised", {"FBP": K.make_fault("FBP", fd.IDF_ERR_NVS_NOT_INITIALIZED, H.VIS_OLD)},
     fd.TXN_NOT_COMMITTED, True, True, "PROFILE_STALE", "PROFILE_STALE", "PROFILE_STALE"),
    ("F5 FBP raw error, readback == intended", {"FBP": K.make_fault("FBP", fd.IDF_ERR_FLASH_OP_FAIL, H.VIS_NEW)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", "INVALIDATED"),
    ("F6 FBP raw error, readback == prior (may land later)", {"FBP": K.make_fault("FBP", fd.IDF_ERR_FLASH_OP_FAIL, H.VIS_OLD)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", "PROFILE_STALE"),
    ("F8 FBP OK, readback read error", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_CRCBAD)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", None),
    ("F8b FBP OK, readback absent", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_ABSENT)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", None),
    ("F8c FBP OK, another record reads back", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_OTHER)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", None),
    ("F8d FBP OK, wrong-size readback", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_WRONGSIZE)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", None),
    ("F8e FBP OK, storage unavailable after the write", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_UNAVAILABLE)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", "INVALIDATED"),
    ("F-H2 an INVALID page appears after the FBW write", {"FBW": K.make_fault("FBW", fd.IDF_OK, H.VIS_NEW, healthy_after=False)},
     fd.TXN_UNKNOWN_REBOOT, False, False, "VALID", "SAVE_UNCONFIRMED", "PROFILE_STALE"),
    ("F-H2b an INVALID page appears after the FBP write", {"FBP": K.make_fault("FBP", fd.IDF_OK, H.VIS_NEW, healthy_after=False)},
     fd.TXN_UNKNOWN_REBOOT, False, True, "VALID", "SAVE_UNCONFIRMED", "INVALIDATED"),
)


def _fault_install(d, faults):
    for key, f in faults.items():
        d.sim.nvs_direct.faults.setdefault(K_W if key == "FBW" else K_P, []).append(K.clone_write_fault(f))


def _by_key(faults) -> dict:
    return {(K_W if k == "FBW" else K_P): [f] for k, f in faults.items()}


def scn_fault_row(mk, seed, faults: dict, label: str, *, aftermath: bool = True, boot_check: bool = True, hand=None) -> Errs:
    """One NVS-fault row through the REAL YAML, checked against the independent FB-B0 model run on a copy of the same flash image with
    the same faults (verdict, bytes on flash, set sequence, mirror, class), the locked texts, the overlay, and the reboot."""
    e = Errs()
    d, w = new_drv(mk, seed=seed)
    blobs0 = K.copy_blobs(d)
    v = K.oracle_invalidate(blobs0, faults=_by_key(faults))
    e.verdict = v
    _fault_install(d, faults)
    mirror_0 = mirror_state(d)
    b7_0, b8_0 = d.b7, d.b8
    ps0 = d.g["fallback_profile_present_seen"]
    wm, nm = w.mark(), K.nvs_mark(d)
    st = d.invalidate()
    g = v.p_prior["generation"]
    exp_cls, exp_why, overlay = K.expected_mirror(v)
    # 1. the verdict and its text
    e.eq(st.b9, K.expected_b9(v), "B9 (locked text for the model's verdict)")
    e.eq(publishes(st), [K.expected_b9(v)], "one B9 publication")
    if hand is not None:
        h_out, h_adv, h_fbp, h_mcls, h_b1, h_next = hand
        e.eq(v.outcome, h_out, "locked table: TxnOutcome (model)")
        e.eq(bool(v.r.witness_advanced), h_adv, "locked table: witness_advanced (model)")
        e.eq(len(v.sets) == 2, h_fbp, "locked table: FBP set attempted (model)")
        e.eq(exp_cls, h_mcls, "locked table: mirror class (model)")
        e.eq("SAVE_UNCONFIRMED" if overlay else exp_cls, h_b1, "locked table: B1 (model)")
        if h_next is not None:
            e.eq(K.class_after_boot(v.nvs_after)[0], h_next, "locked table: next-boot class (model)")
    # 2. what was written: the same sets, the same flash
    e.eq([(n, r) for n, _b, r in st.fb_sets], [(E.FB_KEY_NAMES[k], r) for k, r in v.sets], "FB sets and their ESP results = the model's")
    e.eq(K.image_now(d.sim.nvs_direct), K.image_now(v.nvs_after), "flash image after the call = the model's")
    e.eq(st.writes, [], "no Modbus write")
    e.eq(st.reads, [], "no Modbus read")
    e.ok(st.fb_set_order[:1] in ([], ["FBW"]), "FBW is always the first set")
    if "FBP" in st.fb_set_order:
        e.ok(st.fb_set_order == ["FBW", "FBP"] and v.r.w.outcome == fd.KEY_COMMITTED, "FBP only after a COMMITTED FBW")
    # 3. the mirror and the overlay
    e.eq(D.CLASS[d.g["fallback_profile_class"]], exp_cls, "composed class global")
    e.eq(d.g["fallback_profile_why"], [k for k, n in fd.WHY_NAMES.items() if n == exp_why][0], "why global")
    e.eq(d.b1, "SAVE_UNCONFIRMED" if overlay else exp_cls, "B1")
    if v.outcome != fd.TXN_COMMITTED:
        e.eq((d.b7, d.b8), (b7_0, b8_0), "B7 / B8 still show the prior profile (the mirror keeps the prior bytes)")
    mp, mw, mpl, mwl = fd.mirror_after(v.outcome, v.r, v.p_bytes, v.p_load, v.w_bytes, v.w_load)
    e.eq(d.arr("fallback_profile_bytes"), list(mp), "profile mirror from the readbacks / the prior (never the intended bytes)")
    e.eq(d.arr("fallback_witness_bytes"), list(mw), "witness mirror")
    e.eq((d.g["fallback_profile_load"], d.g["fallback_witness_load"]), (mpl, mwl), "mirror loads")
    werr, us = K.first_nonzero(v.r.w.err, v.r.p.err), v.r.w.us + v.r.p.us
    e.eq((d.g["fallback_durable_last_err"], d.g["fallback_durable_last_us"]), (werr, us), "B2 werr / us sources")
    why_code = d.g["fallback_profile_why"]
    e.eq(K.parse_kv(d.b2), K.expected_b2(mp, mpl, mw, mwl, why_code, werr, us), "B2")
    e.eq(d.g["fallback_profile_save_unconfirmed"], overlay, "SAVE_UNCONFIRMED overlay iff UNKNOWN")
    e.eq(d.write_latched, overlay, "write latch iff UNKNOWN")
    if overlay:
        e.eq((d.g["fallback_profile_save_unconfirmed_op"], d.g["fallback_profile_save_unconfirmed_gen"]), (fd.PROV_OP_INVALIDATE, g + 1),
             "unconfirmed op / generation")
    e.eq(d.g["fallback_profile_seen_hw_gen"], fd.next_seen_hw_gen(GOLD_G, fp.classify_profile(mpl, fp.unpack_profile(mp)),
                                                                    fp.unpack_profile(mp)["generation"],
                                                                    fd.classify_witness(mwl, fd.unpack_provision(mw)),
                                                                    fd.unpack_provision(mw)["hw_generation"]), "seen_hw_gen")
    ps = ps0 | (2 if v.r.w.outcome == fd.KEY_COMMITTED else 0) | (1 if v.r.p.outcome == fd.KEY_COMMITTED else 0)
    e.eq(d.g["fallback_profile_present_seen"], ps, "present_seen")
    # never claims INVALIDATED unless committed + verified
    if v.outcome != fd.TXN_COMMITTED:
        e.ok(d.b1 != "INVALIDATED" and not d.b9.startswith("INVALIDATED"), "never claims INVALIDATED unless the commit was verified")
    e.eq(sorted(w.names(wm) - ASSIGN_COMMIT), [], "assigned names")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "flags never assigned")
    e.eq(D.text_invariants(d), [], "text invariants")
    e.eq(D.idle_invariants(d), [], "idle invariants")
    e.ok(not d.arm_state, "arm off")
    # 4. aftermath
    sets_after_call = len(d.sim.nvs_direct.sets)
    if aftermath and overlay:
        # UNKNOWN: no retry, zero further writes, later Review / Save / Invalidate refused until reboot
        st2 = d.invalidate(target_id=GOLD_ID)
        unk_text = PREFIX + "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first"
        anomaly_text = PREFIX + T_ANOMALY
        e.ok(d.b9 in (unk_text, anomaly_text), f"INVALIDATE after UNKNOWN is refused: {d.b9[:70]!r}")
        e.eq(st2.fb_sets, [], "no write after UNKNOWN (no retry)")
        d.review()
        e.eq(d.candidate()["saveable"], False, f"Review after UNKNOWN is never saveable: {d.b3[:60]!r}")
        if d.b3.startswith("st=CANDIDATE_NOT_SAVEABLE;"):
            e.ok("previous save outcome unknown" in d.b9, f"the not-saveable reason names the unknown outcome: {d.b9[:70]!r}")
        e.eq(d.b1, "SAVE_UNCONFIRMED", "the overlay wins over a fresh Review")
        e.eq((K.parse_kv(d.b2)["werr"], K.parse_kv(d.b2)["us"]), (K.err_text(werr), "-" if us == 0 else str(us)),
             "the Review keeps publishing the retained B2 werr / us")
        st3 = d.save()
        e.ok(d.b9.startswith("SAVE REFUSED - "), f"Save after UNKNOWN is refused: {d.b9[:60]!r}")
        e.eq(st3.fb_sets, [], "no write by the refused Save")
        e.eq(len(d.sim.nvs_direct.sets), sets_after_call, "zero NVS sets after the UNKNOWN call, whatever was attempted")
        e.ok(d.write_latched, "latch still set")
    if aftermath and v.outcome == fd.TXN_NOT_COMMITTED and not v.r.witness_advanced:
        # nothing changed, no latch: a fresh operator call (new arm) goes through, with the model's next verdict
        d.sim.nvs_direct.faults.clear()
        st2 = d.invalidate()
        e.eq(st2.b9, K.b9_invalidated(g), "a new operator INVALIDATE after NOT_COMMITTED succeeds")
        e.eq(st2.violations_fb(("FBW", "FBP"), reads=[]), [], "...and writes exactly FBW then FBP")
    if aftermath and v.outcome == fd.TXN_NOT_COMMITTED and v.r.witness_advanced:
        st2 = d.invalidate(target_id=GOLD_ID)
        e.eq(st2.b9, PREFIX + "profile is PROFILE_STALE; only a VALID profile can be invalidated", "STALE is unusable and not invalidatable")
        d.review(expect="CANDIDATE_READY")
        st3 = d.save()
        e.eq(st3.b9, f"SAVED - known-good profile generation {g + 2} saved (verified this boot)", "Save after the half-landed INVALIDATE = g+2")
        e.eq(d.b1, "VALID", "VALID again")
    # 5. reboot: the class the model derives from the resolved flash
    if boot_check:
        if aftermath and v.outcome == fd.TXN_NOT_COMMITTED:
            return e                                          # the image moved on (a second transaction); the sweep rows cover the boot
        flash_resolved = K.image_after_boot(v.nvs_after)
        want_next = K.class_after_boot(v.nvs_after)
        d.reboot()
        w.attach()
        e.eq(d.b1, want_next[0], "class after reboot = the model's")
        e.eq(D.CLASS[d.g["fallback_profile_class"]], want_next[0], "class global after reboot")
        e.eq(d.model_class()[0], want_next[0], "FB-B0 oracle over the real image after reboot")
        e.eq(K.blobs_of(d), flash_resolved, "flash after reboot = the model's resolution (the boot writes nothing)")
        e.ok(not d.g["fallback_profile_save_unconfirmed"] and not d.write_latched, "overlay and latch cleared by the reboot")
        if want_next[0] == "VALID" and overlay:
            e.ok(K.parse_kv(d.b2)["g"] == str(g), "a profile that is VALID after an UNKNOWN INVALIDATE is reported VALID only after the reboot")
    return e


def scn_unknown_residual_valid_reboot(mk) -> Errs:
    """UNKNOWN where nothing landed: before the reboot B1 says SAVE_UNCONFIRMED (never VALID, never INVALIDATED); only the reboot reports
    VALID gN again (the residual)."""
    e = Errs()
    d, w = new_drv(mk)
    d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
    d.invalidate()
    e.eq(d.b1, "SAVE_UNCONFIRMED", "UNKNOWN: B1 is the overlay")
    e.ok(d.b9.startswith("INVALIDATE OUTCOME UNKNOWN - "), "UNKNOWN: B9")
    e.eq(d.stored("FBP")["generation"], GOLD_G, "flash still holds the VALID profile")
    d.reboot()
    e.eq((d.b1, K.parse_kv(d.b2)["g"]), ("VALID", "7"), "after the reboot: VALID g7 (re-issue possible)")
    st = d.invalidate()
    e.ok(st.b9.startswith("INVALIDATED - profile generation 7"), f"re-issued INVALIDATE works after the reboot: {st.b9[:40]!r}")
    return e


# ---------------------------------------------------------------------------
# 7. SEQUENCES
# ---------------------------------------------------------------------------
def scn_seq_inv_save_inv(mk) -> Errs:
    """VALID g7 -> INVALIDATE g8 -> Review+SAVE g9 -> INVALIDATE g10 -> Review+SAVE g11: strictly increasing, witness chain intact,
    reboot in the middle."""
    e = Errs()
    d, w = new_drv(mk)
    gens = [GOLD_G]
    hist = []

    def snap(label):
        p = fp.unpack_profile(K.blobs_of(d)[K_P][0])
        wv = fd.unpack_provision(K.blobs_of(d)[K_W][0])
        hist.append((label, p["generation"], p["flags"] & 1, wv["hw_generation"], wv["prior_generation"], wv["last_op"], p["binding"]))
        gens.append(p["generation"])

    st = d.invalidate()
    e.ok(st.b9.startswith("INVALIDATED - profile generation 7"), "g7 -> INVALIDATED g8")
    snap("inv1")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.eq(st.b9, "SAVED - known-good profile generation 9 saved (verified this boot)", "SAVE after INVALIDATE: g9")
    snap("save")
    d.reboot()
    e.eq(d.b1, "VALID", "VALID g9 after reboot")
    st = d.invalidate()
    e.eq(st.b9, K.b9_invalidated(9), "INVALIDATE g9 -> g10")
    snap("inv2")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.eq(st.b9, "SAVED - known-good profile generation 11 saved (verified this boot)", "SAVE: g11")
    snap("save2")
    e.eq(gens, [7, 8, 9, 10, 11], "generations strictly increasing 7,8,9,10,11")
    e.eq([(h[1], h[2], h[3], h[4], h[5]) for h in hist],
         [(8, 1, 8, 7, 2), (9, 0, 9, 8, 1), (10, 1, 10, 9, 2), (11, 0, 11, 10, 1)], "(g, invalidated flag, hw, prior, op) per transaction")
    e.eq(d.g["fallback_profile_seen_hw_gen"], 11, "seen_hw_gen follows")
    return e


def scn_seq_replace_corrupt_then_invalidate(mk, seed_name: str) -> Errs:
    """REPLACE CORRUPT of a CORRUPT profile (FBW hw 9) -> VALID g10 (op REPLACE_CORRUPT); then INVALIDATE works -> g11; reboot; Save g12."""
    e = Errs()
    seeds = {"garbage": {"fbp": bytes(range(96)), "fbw": D.prov_bytes(9, 0x1234, 8)},
             "wrong size": {"fbp": bytes(40), "fbw": D.prov_bytes(9, 0x1234, 8)}}
    d, w = new_drv(mk, seed=seeds[seed_name])
    e.eq(d.b1, "CORRUPT", "boot CORRUPT")
    st = d.invalidate(target_id=GOLD_ID)
    e.eq(st.b9, PREFIX + "profile is CORRUPT; only a VALID profile can be invalidated", "INVALIDATE of a CORRUPT profile refused")
    e.eq(st.fb_sets, [], "nothing written")
    d.review(expect="CANDIDATE_READY")
    e.eq(d.b3_field("prior"), "CORRUPT", "Review sees prior CORRUPT")
    st = d.save(replace_corrupt=True)
    e.eq(st.b9, "SAVED - known-good profile generation 10 saved (verified this boot)", "REPLACE CORRUPT: g10 = max(hw 9, seen) + 1")
    e.eq(d.b1, "VALID", "VALID")
    wv = fd.unpack_provision(K.blobs_of(d)[K_W][0])
    e.eq((wv["hw_generation"], wv["prior_generation"], wv["prior_binding"], wv["last_op"]), (10, 0, 0, fd.PROV_OP_REPLACE_CORRUPT),
         "FBW of the REPLACE CORRUPT: prior 0/0, op REPLACE_CORRUPT")
    st = d.invalidate()
    e.eq(st.b9, K.b9_invalidated(10), "INVALIDATE after REPLACE CORRUPT: g10 -> g11")
    e.eq(st.violations_fb(("FBW", "FBP"), reads=[]), [], "exactly FBW then FBP")
    wv = fd.unpack_provision(K.blobs_of(d)[K_W][0])
    e.eq((wv["hw_generation"], wv["prior_generation"], wv["last_op"]), (11, 10, fd.PROV_OP_INVALIDATE), "FBW of the INVALIDATE")
    d.reboot()
    e.eq((d.b1, K.parse_kv(d.b2)["g"]), ("INVALIDATED", "11"), "reboot: INVALIDATED g11")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.eq(st.b9, "SAVED - known-good profile generation 12 saved (verified this boot)", "Save: g12")
    return e


def scn_seq_stale_save_then_invalidate(mk) -> Errs:
    """A STALE profile is refused; a plain Save makes it VALID (g = hw+1); then INVALIDATE works."""
    e = Errs()
    d, w = new_drv(mk, seed="stale")
    st = d.invalidate(target_id=GOLD_ID)
    e.eq(d.b9, PREFIX + "profile is PROFILE_STALE; only a VALID profile can be invalidated", "STALE refused")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.ok(st.b9.startswith("SAVED - known-good profile generation 8 "), f"Save over STALE: g8 ({st.b9[:60]!r})")
    st = d.invalidate()
    e.eq(st.b9, K.b9_invalidated(8), "INVALIDATE g8 -> g9")
    return e


def scn_boundary_generation(mk) -> Errs:
    """g = 0xFFFFFFFE: INVALIDATE is permitted (g+1 = 0xFFFFFFFF) and the dead end afterwards is explicit: the Save is refused 'counter
    exhausted', a second INVALIDATE too."""
    e = Errs()
    d, w = new_drv(mk, seed=G_MAX_M1)
    e.eq(d.b1, "VALID", "boot VALID at g = 0xFFFFFFFE")
    st = d.invalidate(target_id=G_MAX_M1_ID)
    e.eq(st.b9, K.b9_invalidated(0xFFFFFFFE), "INVALIDATE g 0xFFFFFFFE -> 0xFFFFFFFF")
    e.eq(st.violations_fb(("FBW", "FBP"), reads=[]), [], "FBW then FBP")
    e.eq(fp.unpack_profile(K.blobs_of(d)[K_P][0])["generation"], 0xFFFFFFFF, "stored generation 0xFFFFFFFF")
    e.eq(d.b1, "INVALIDATED", "B1")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.eq(st.b9, "SAVE REFUSED - profile generation counter exhausted; profile unchanged", "Save: counter exhausted")
    e.eq(st.fb_sets, [], "nothing written")
    return e


def scn_seen_floor_boundary(mk) -> Errs:
    """seen_hw_gen == g (7): g+1 > seen -> allowed (boundary), the commit raises seen_hw_gen to 8."""
    e = Errs()
    d, w = new_drv(mk)
    d.set_g("fallback_profile_seen_hw_gen", GOLD_G)
    st = d.invalidate()
    e.eq(st.b9, K.b9_invalidated(GOLD_G), "seen == g: allowed")
    e.eq(d.g["fallback_profile_seen_hw_gen"], 8, "seen raised")
    return e


def scn_writer_usable(mk) -> Errs:
    """profile_writer_usable is true ONLY for VALID with no witness trouble: B10 yes; B8 / B14 / B15 (VALID but lagging / missing /
    corrupt witness) no; after an INVALIDATE no - published and derived (B1 + class + why)."""
    e = Errs()
    for label, seed, usable in (("B10", "valid", True), ("B8", "lag", False), ("B14", {"fbp": GOLD, "fbw": None}, False),
                                ("B15", "witness_corrupt", False)):
        d, w = new_drv(mk, seed=seed)
        e.eq(d.b1, "VALID", f"{label}: B1 VALID")
        e.eq(fd.profile_writer_usable(d.g["fallback_profile_class"], d.g["fallback_profile_why"]), usable, f"{label}: writer usable")
        d.invalidate()
        e.ok(not fd.profile_writer_usable(d.g["fallback_profile_class"], d.g["fallback_profile_why"]), f"{label}: INVALIDATED is not writer-usable")
        e.eq(d.b1, "INVALIDATED", f"{label}: B1 INVALIDATED")
    return e


# ---------------------------------------------------------------------------
# 8. STATIC PINS of the INVALIDATE script (text of the firmware under test)
# ---------------------------------------------------------------------------
def static_inv(text: str) -> Errs:
    """Static properties of the fallback_profile_invalidate script text (master 4.8 / MB33 / PO15 / BLK-51 / D1 / D2)."""
    e = Errs()
    a, b = K.inv_region(text)
    blk = text[a:b]
    then = blk.split("    then:\n", 1)[1]
    items = re.findall(r"^      - (\S+?):", then, flags=re.M)
    e.eq(items, ["lambda"], "the script is ONE lambda (no wait_until / delay / script.execute / if action)")
    for tok in ("wait_until", "delay:", "script.execute", "modbus_client", "supervision", "esp_restart", "arch_restart", "App.reboot",
                "nvs_set", "nvs_erase", "preference_for", "commit_record", "load_record", "random_uint32", "yield"):
        e.ok(tok not in blk, f"no `{tok}` in the INVALIDATE script")
    e.ok(not re.search(r"\bntp_", blk), "no ntp_ in the INVALIDATE script")
    for g in ("manual_write_in_progress", "fallback_profile_op_in_progress", "fallback_profile_op_purpose", "fallback_profile_step",
              "fallback_profile_gate_accepted", "fallback_profile_capture_state"):
        e.ok(not re.search(rf"id\({g}\)\s*(=[^=]|\+\+|--|\+=|-=)", blk), f"`{g}` is never assigned in the INVALIDATE script")
    assigned = set(re.findall(r"id\((\w+)\)\s*=[^=]", blk))
    e.eq(sorted(assigned - ASSIGN_COMMIT), [], "globals assigned in the INVALIDATE script beyond the design's set")
    e.eq(blk.count("ecco_fbdurable::commit_transition_t("), 1, "exactly one commit_transition_t call")
    e.eq(blk.count("invalidate_profile("), 0, "invalidate_profile( only through the guarded plan_invalidate")
    e.eq(blk.count("ecco_fbsave::plan_invalidate("), 1, "plan_invalidate (the guarded builder) is used")
    e.eq(blk.count("ecco_fbdurable::EspNvs nvs;"), 1, "one EspNvs local")
    # the in-flight check is the first statement; its branch contains only arm.turn_off(), the text publish and return
    def ordered(*needles) -> bool:
        """The needles occur in this order (each searched after the previous one)."""
        at = -1
        for n in needles:
            at = blk.find(n, at + 1)
            if at < 0:
                return False
        return True

    first = blk.find("invalidate_in_flight_gate(")
    e.ok(ordered("invalidate_in_flight_gate(", "const bool armed"), "the in-flight check comes before the one-shot preamble")
    branch = blk[first:blk.find("return;", first)] if first >= 0 and blk.find("return;", first) >= 0 else ""
    e.ok("id(fallback_profile_arm).turn_off();" in branch and "cand" not in branch,
         "the in-flight branch turns the arm off, publishes B9 and returns (it never touches the candidate)")
    e.ok(ordered("invalidate_in_flight_gate(", "id(fallback_profile_arm).turn_off();", "const bool armed = id(fallback_profile_arm).state;",
                 "id(fallback_profile_arm).turn_off();", "invalidate_gate_decide("),
         "in-flight branch (arm off) first; then the one-shot preamble: armed is read, THEN the arm is turned off, before the gate decision")
    e.eq(blk.count("id(fallback_profile_arm).turn_off();"), 2, "the arm is turned off in exactly two places (in-flight branch, preamble)")
    e.ok(ordered("id(fallback_profile_arm).turn_off();", "id(fallback_profile_invalidate_candidate).execute();"),
         "the candidate is consumed (IE2) after the arm is turned off")
    # the bus-idle check is the LAST statement before the writer call
    m = re.search(r"if \(!ecco_fbsave::invalidate_bus_idle\(bn,[^\n]*\n(?:[^\n]*\n){1,4}?\s*return;\n\s*\}\n(?P<next>[^\n]*\n[^\n]*)", blk)
    e.ok(bool(m) and "commit_transition_t(" in m.group("next"), "invalidate_bus_idle is the last statement before commit_transition_t")
    e.ok(ordered("invalidate_gate_decide(", "read_direct_t(", "plan_invalidate(", "invalidate_bus_idle(", "commit_transition_t("),
         "order: gate, fresh read, plan, bus idle, commit")
    e.ok(ordered("IG_ACCEPT", "ecco_fbdurable::EspNvs nvs;", "read_direct_t("), "no storage object or read before the gate accepted (cheap checks first)")
    e.ok("if (o == ecco_fbdurable::TXN_UNKNOWN_REBOOT) {" in blk and "fallback_profile_save_unconfirmed) = true;" in blk,
         "UNKNOWN sets the SAVE_UNCONFIRMED overlay")
    e.ok("mirror_after(o, r, p, lp, w, lw)" in blk, "the mirror comes from mirror_after (readbacks), never from the intended records")
    e.ok("txn_outcome_text(plan.op, o, r, plan.generation, p.generation)" in blk, "the outcome text is keyed on the writer's own verdict")
    e.eq(blk.count("ESP_LOGI(\"fbdurable\", \"%s\", lg.c_str());"), 1, "one INFO log line (the verified commit)")
    e.eq(blk.count("ESP_LOGW(\"fbdurable\", \"%s\", lg.c_str());"), 1, "one WARN log line (every other outcome)")
    e.eq(len(re.findall(r"\bretry|\bwhile\s*\(|\bfor\s*\(|\bgoto\b", blk)), 0, "no retry loop")
    return e


# ---------------------------------------------------------------------------
# 9. FOLLOW-UPS: fresh-read refusals leave a coherent mirror; idle stability; SAVE UNKNOWN blocks INVALIDATE; StringRef tail
# ---------------------------------------------------------------------------
def scn_fresh_followup(mk, row: Row) -> Errs:
    """After a fresh-read refusal the mirror is the LATEST authoritative read (R-D5): class global == compose over the mirror it
    publishes with the read-anomaly latch, B1 is that class (no overlay), every later INVALIDATE is refused at the gate with no storage
    access, nothing is ever written; a reboot re-derives the class the FB-B0 model derives from the flash."""
    e = Errs()
    d, w = new_drv(mk, seed=row.seed, fbs=row.fbs, env=row.env, **row.drv)
    row.pre(d)
    kw = {}
    if row.target_id is not None:
        kw["target_id"] = row.target_id
    if row.confirmation is not None:
        kw["confirmation"] = row.confirmation
    d.invalidate(**kw)
    p_b, w_b = d.arr("fallback_profile_bytes"), d.arr("fallback_witness_bytes")
    cls, why, _rule = fd.compose_profile_class(d.g["fallback_profile_load"], bytes(p_b), d.g["fallback_witness_load"], bytes(w_b),
                                                d.g["fallback_profile_read_anomaly"])
    e.eq((d.g["fallback_profile_class"], d.g["fallback_profile_why"]), (cls, why), "class / why = compose over the published mirror")
    e.eq(d.b1, D.CLASS[cls], "B1 = that class (no overlay: nothing was written)")
    b2 = K.parse_kv(d.b2)
    p_l, w_l = d.g["fallback_profile_load"], d.g["fallback_witness_load"]
    e.eq(b2["ld"], {0: "OK", 1: "ABS", 2: "WSZ", 3: "RERR", 4: "UNAV"}[p_l], "B2 ld shows the fresh read")
    if row.mirror == "fresh" and d.g["fallback_profile_read_anomaly"]:
        nm = K.nvs_mark(d)
        st2 = d.invalidate(target_id=GOLD_ID)
        e.eq(d.b9, PREFIX + T_ANOMALY, "a later INVALIDATE is refused at the gate")
        e.eq(K.nvs_events_since(d, nm), [], "...with no storage access")
        e.eq(st2.fb_sets, [], "...and nothing written")
    e.eq([x for x in d.nvs_set_history()], [], "no NVS set in the whole scenario")
    return e


def scn_idle_stability(mk, how: str) -> Errs:
    """After an INVALIDATE (clean / UNKNOWN / NOT_COMMITTED) the 10 s housekeeping never touches storage, the bus or the texts: 15 minutes
    of ticks change nothing (the overlay, the class and every B-text stay as the call left them)."""
    e = Errs()
    d, w = new_drv(mk)
    if how == "unknown":
        d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
    elif how == "witness_advanced":
        d.fault_write("FBP", result=fd.IDF_ERR_NVS_READ_ONLY, visible=H.VIS_OLD)
    d.invalidate()
    snap, nm, m = d.snapshot(), K.nvs_mark(d), d.mark()
    texts = d.texts()
    d.advance(900_000)
    e.eq(d.texts(), texts, "every B-text unchanged after 15 minutes of ticks")
    e.eq(d.diff(snap), {"globals": [], "published": {}}, "no global changed, nothing published")
    e.eq(K.nvs_events_since(d, nm), [], "no storage access")
    e.eq((d.since(m).reads, d.since(m).writes), ([], []), "no Modbus traffic")
    return e


def scn_save_unknown_blocks_invalidate(mk) -> Errs:
    """A SAVE whose outcome is UNKNOWN locks every later Fallback Profile write for the boot, INVALIDATE included; the reboot resolves."""
    e = Errs()
    d, w = new_drv(mk)
    d.review(expect="CANDIDATE_READY")
    d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
    st = d.save()
    e.ok(st.b9.startswith("SAVE OUTCOME UNKNOWN - "), f"set-up: SAVE UNKNOWN: {st.b9[:40]!r}")
    e.eq(d.b1, "SAVE_UNCONFIRMED", "set-up: overlay")
    sets0 = len(d.sim.nvs_direct.sets)
    nm = K.nvs_mark(d)
    st = d.invalidate(target_id=GOLD_ID)
    e.eq(d.b9, PREFIX + "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first", "INVALIDATE refused after a SAVE UNKNOWN")
    e.eq(K.nvs_events_since(d, nm), [], "no storage access")
    e.eq(len(d.sim.nvs_direct.sets), sets0, "no write")
    d.reboot()
    e.eq(d.b1, "VALID", "after the reboot VALID g7 (the SAVE never landed)")
    st = d.invalidate()
    e.ok(st.b9.startswith("INVALIDATED - "), "INVALIDATE works after the reboot")
    return e


def scn_tail_garbage(mk) -> Errs:
    """The api StringRef c_str() is not NUL-terminated: bytes after each string (here a NUL and then text) never leak into the id,
    the phrase or the action."""
    return scn_clean(mk, "valid", tail="\x00garbage-after-the-string", reboot=False)


# ---------------------------------------------------------------------------
# 10. THE WRITE-FAULT MATRIX (key x raw result x readback x health, and the boot resolution)
# ---------------------------------------------------------------------------
def fault_matrix_valid() -> list:
    """[(label, faults)] for the VALID/B10 seed: every (key, raw result, readback, health) cell; FBP cells have a clean FBW before."""
    rows = []
    for key in ("FBW", "FBP"):
        for rname, res in K.RAW_RESULTS.items():
            for vis in K.VISIBLES:
                for healthy in (True, False):
                    rows.append((K.fault_label(key, rname, vis, healthy, H.BOOT_ASIS), {key: K.make_fault(key, res, vis, healthy)}))
    return rows


def fault_matrix_boot() -> list:
    """The boot resolution of a written key (BOOT_NEW / OLD / ABSENT) for the cells that can be UNKNOWN."""
    rows = []
    for key in ("FBW", "FBP"):
        for rname in ("OK", "NO_MEM", "PRE_INVALID_HANDLE"):
            for vis in K.VISIBLES:
                for boot in (H.BOOT_NEW, H.BOOT_OLD, H.BOOT_ABSENT):
                    rows.append((K.fault_label(key, rname, vis, True, boot),
                                 {key: K.make_fault(key, K.RAW_RESULTS[rname], vis, True, boot)}))
    return rows


def fault_matrix_seed(seed) -> list:
    """The hand-table cells for the other witness situations (B8 lagging / B14 missing / B15 corrupt)."""
    return [(label, faults) for label, faults, *_h in HAND_TABLE]


def scn_router_save(mk) -> Errs:
    """The router still sends SAVE to the SAVE gate (only INVALIDATE goes to the INVALIDATE script)."""
    e = Errs()
    d, w = new_drv(mk)
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    e.eq(st.b9, f"SAVED - known-good profile generation {GOLD_G + 1} saved (verified this boot)", "SAVE token reaches the SAVE gate")
    e.eq(st.violations_fb(("FBW", "FBP"), reads=[(230, 3), (241, 53), (230, 3), (241, 53)]), [], "SAVE: FBW then FBP, the dispatch's four reads")
    return e


# ---------------------------------------------------------------------------
# 11. RANDOMISED OPERATION SEQUENCES (model-checked invariants)
# ---------------------------------------------------------------------------
RANDOM_OPS = ("review", "inv", "inv", "inv", "save", "save", "save_rc", "advance", "fault_w", "fault_p", "reboot", "bad_inv", "arm_only",
              "lease", "mutex", "unmutex", "hold_bus", "unhealthy", "expire", "wrong_phrase", "candidate_inv")
RANDOM_SEEDS = ("valid", "valid", "valid", "lag", "none", "invalidated", "corrupt", "wsize", "stale", "lost", "witness_corrupt", "corrupt_domain",
                {"fbp": GOLD, "fbw": None})


def _flash_floor(d) -> int:
    """The highest generation the flash proves was used: the authentic profile's generation or a W_VALID witness's hw."""
    f = 0
    pl, pb = d._peek("FBP")
    wl, wb = d._peek("FBW")
    p, w = fp.unpack_profile(pb), fd.unpack_provision(wb)
    if fd.fba_authentic(fp.classify_profile(pl, p)):
        f = max(f, p["generation"])
    if fd.classify_witness(wl, w) == fd.W_VALID:
        f = max(f, w["hw_generation"])
    return f


def scn_random_sequence(mk, seed: int, nops: int = 16) -> Errs:
    """A deterministic random sequence of operator / world operations (Review, INVALIDATE, SAVE, REPLACE CORRUPT, faults, leases, a held
    mutex or bus, an INVALID page, arm TTL, reboot) over a random seed image. After EVERY operation: no Modbus write ever, only FBW then
    FBP sets (never FBS, never a foreign key), a refusal wrote nothing, nothing was written after an UNKNOWN until the reboot, texts clean,
    nothing left half-held, B1 shows the overlay after an UNKNOWN, a committed generation is strictly above everything the flash proved
    before it, and after every reboot B1 equals the FB-B0 model's class of the flash image."""
    import random
    rnd = random.Random(seed)
    e = Errs()
    sd = rnd.choice(RANDOM_SEEDS)
    d = mk(seed=sd, fbs=rnd.choice([None, None, None, "clear"]))
    latched = False
    for step in range(nops):
        op = rnd.choice(RANDOM_OPS)
        n_sets0 = len(d.sim.nvs_direct.sets)
        n_mod0 = len(d.modbus_writes())
        floor0, b9_0, latched_before = _flash_floor(d), d.b9, latched
        try:
            if op == "review":
                d.review()
            elif op in ("inv", "candidate_inv", "wrong_phrase", "bad_inv"):
                if op == "candidate_inv":
                    d.review()
                tid = d.b2_id()
                tid = "0123456789ABCDEF" if tid == "-" else tid
                if op == "bad_inv":
                    d.invalidate(target_id="0123456789ABCDEF")
                elif op == "wrong_phrase":
                    d.invalidate(target_id=tid, confirmation="INVALIDATE " + "0" * 16)
                else:
                    d.invalidate(target_id=tid)
            elif op == "save":
                if not d.candidate()["valid"]:
                    d.review()
                if d.candidate()["valid"]:
                    d.save()
            elif op == "save_rc":
                d.review()
                if d.candidate()["valid"]:
                    d.save(replace_corrupt=True)
            elif op == "advance":
                d.advance(rnd.choice([1000, 60000, 130000, 400000]))
            elif op == "fault_w":
                d.fault_write("FBW", result=rnd.choice([0, fd.IDF_ERR_NVS_READ_ONLY, fd.IDF_ERR_NO_MEM]),
                              visible=rnd.choice([H.VIS_NEW, H.VIS_OLD, H.VIS_OTHER, H.VIS_ABSENT]), other=bytes([7]) * 48)
            elif op == "fault_p":
                d.fault_write("FBP", result=rnd.choice([0, fd.IDF_ERR_NVS_READ_ONLY, fd.IDF_ERR_FLASH_OP_FAIL]),
                              visible=rnd.choice([H.VIS_NEW, H.VIS_OLD, H.VIS_CRCBAD]))
            elif op == "reboot":
                d.reboot()
                latched = False
            elif op == "arm_only":
                d.arm_on()
            elif op == "lease":
                d.lease(rnd.choice(sorted(D.LEASE_RAM)))
            elif op == "mutex":
                d.mutex(True)
            elif op == "unmutex":
                d.mutex(False)
            elif op == "hold_bus":
                d.hold_bus(rnd.choice([100, 5000]))
            elif op == "unhealthy":
                d.unhealthy()
            elif op == "expire":
                d.advance(125000)
        except D.DriverError:
            continue
        tag = f"seed {seed} step {step} ({op})"
        new = d.nvs_set_history()[-(len(d.sim.nvs_direct.sets) - n_sets0):] if len(d.sim.nvs_direct.sets) > n_sets0 else []
        names = [n for _b, n, _d, _r in new]
        e.eq(len(d.modbus_writes()), n_mod0, f"{tag}: no Modbus write")
        e.ok(all(k in (K_P, K_W) for k, _b, _r in d.sim.nvs_direct.sets), f"{tag}: only FBP / FBW are ever set")
        e.ok(names in ([], ["FBW"], ["FBW", "FBP"]), f"{tag}: set sequence {names}")
        if d.b9 != b9_0 and "REFUSED" in d.b9:
            e.eq(names, [], f"{tag}: a refusal wrote nothing ({d.b9[:50]!r})")
        if d.g["fallback_profile_save_unconfirmed"]:
            latched = True
        if latched_before and op != "reboot":
            e.eq(names, [], f"{tag}: nothing written after an UNKNOWN until the reboot")
        e.eq(D.text_invariants(d), [], f"{tag}: text invariants")
        e.eq(D.idle_invariants(d, locked=True), [], f"{tag}: nothing half-held")
        if d.g["fallback_profile_save_unconfirmed"]:
            e.eq(d.b1, "SAVE_UNCONFIRMED", f"{tag}: the overlay is shown")
        if op == "reboot":
            e.eq(d.b1, d.model_class()[0], f"{tag}: B1 after reboot = the model's class of the flash")
        if d.b9 != b9_0:
            m1 = re.match(r"SAVED - known-good profile generation (\d+) saved", d.b9)
            m2 = re.match(r"INVALIDATED - profile generation (\d+) .* \(now INVALIDATED g(\d+)\)", d.b9)
            gnew = int(m1.group(1)) if m1 else (int(m2.group(2)) if m2 else None)
            if gnew is not None:
                e.ok(gnew > floor0, f"{tag}: committed generation {gnew} is above the flash floor {floor0}")
        if e:
            break
    return e


def scn_inconsistent_class_over_invalidated(mk) -> Errs:
    """Defence in depth of I10: the RAM class says VALID over a mirror that holds an INVALIDATED record (a state no boot produces).
    profile_invalidate_permitted refuses it with the generation text, nothing is written, and the call never reaches the fresh read's
    class check ('profile is now INVALIDATED')."""
    e = Errs()
    d, w = new_drv(mk, seed="invalidated")
    d.set_g("fallback_profile_class", CLASS_NUM["VALID"])
    nm = K.nvs_mark(d)
    st = d.invalidate(target_id=GOLD_INVALIDATED_ID)
    allowed = (PREFIX + "profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
               PREFIX + "generation counter exhausted")
    e.ok(d.b9 in allowed, f"refused at I10: {d.b9[:80]!r}")
    e.eq(st.fb_sets, [], "nothing written")
    e.eq(K.nvs_events_since(d, nm), [], "refused over the RAM mirror (no storage access)")
    return e


def scn_replace_corrupt_half_landed(mk) -> Errs:
    """REPLACE CORRUPT whose FBP write is refused after the witness advanced: the profile is still CORRUPT (INVALIDATE refuses it), the
    witness shows hw 10, the next REPLACE CORRUPT gets g11 (the record's own generation is untrusted), then INVALIDATE works (g12)."""
    e = Errs()
    d, w = new_drv(mk, seed={"fbp": bytes(range(96)), "fbw": D.prov_bytes(9, 0x1234, 8)})
    d.review(expect="CANDIDATE_READY")
    d.sim.nvs_direct.faults.setdefault(K_P, []).append(H.WriteFault(result=fd.IDF_ERR_NVS_READ_ONLY, visible=H.VIS_OLD))
    st = d.save(replace_corrupt=True)
    e.eq(st.b9, "SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again",
         "REPLACE CORRUPT, witness advanced")
    e.eq(st.fb_set_order, ["FBW", "FBP"], "FBW then the refused FBP")
    e.eq(d.b1, "CORRUPT", "the profile is still CORRUPT")
    st = d.invalidate(target_id=GOLD_ID)
    e.eq(st.b9, PREFIX + "profile is CORRUPT; only a VALID profile can be invalidated", "INVALIDATE refused while CORRUPT")
    e.eq(st.fb_sets, [], "nothing written")
    d.review(expect="CANDIDATE_READY")
    st = d.save(replace_corrupt=True)
    e.eq(st.b9, "SAVED - known-good profile generation 11 saved (verified this boot)", "second REPLACE CORRUPT: g = hw 10 + 1")
    st = d.invalidate()
    e.eq(st.b9, K.b9_invalidated(11), "INVALIDATE g11 -> g12")
    d.reboot()
    e.eq((d.b1, K.parse_kv(d.b2)["g"]), ("INVALIDATED", "12"), "reboot: INVALIDATED g12")
    return e


# ---------------------------------------------------------------------------
# 12. PLAN-STAGE DEFENCE IN DEPTH: the storage / RAM changes AFTER the gate accepted, DURING the fresh read
#     (the lambda is atomic on the real main loop; these are the two cheap independent layers master 4.8 asks for: the gate over the
#     RAM mirror, then plan_invalidate over the FRESH read. Each layer must refuse on its own: a mutant that disables one of them is
#     only visible when the other layer cannot catch the case first, i.e. when the change happens in between.)
# ---------------------------------------------------------------------------
OTHER_PROFILE = D.gold_profile(reg245=7000)                       # a second VALID g7 profile with another binding
OTHER_ID = f"{OTHER_PROFILE['binding']:016X}"
OTHER_FBP = fp.pack_profile(OTHER_PROFILE)
OTHER_FBW = D.prov_bytes(7, OTHER_PROFILE["binding"], 6)
PLAN_TEXT = {
    "binding_changed": PREFIX + "stored profile changed; nothing written",
    "seen_raised": PREFIX + "profile generation is not ahead of this boot's generation high-water mark; reboot to re-verify",
    "unconfirmed_raised": PREFIX + "previous Fallback Profile write outcome unknown this boot - reboot to re-verify first",
}
PLAN_KINDS = tuple(PLAN_TEXT)


def _plan_hook(d, kind):
    """Fires once, before the FIRST direct-NVS event of the fresh read (the gate has accepted over the RAM mirror by then)."""
    done = [False]

    def hook(op, key):
        if done[0]:
            return
        done[0] = True
        if kind == "binding_changed":
            # another VALID profile (consistent witness) is now in flash AND in the mirror: no same-boot divergence, class VALID, but
            # the binding is no longer the one the operator typed
            d.sim.nvs_direct.put(K_P, OTHER_FBP)
            d.sim.nvs_direct.put(K_W, OTHER_FBW)
            d.sim.g["fallback_profile_bytes"].assign_from(list(OTHER_FBP))
            d.sim.g["fallback_witness_bytes"].assign_from(list(OTHER_FBW))
        elif kind == "seen_raised":
            d.sim.g["fallback_profile_seen_hw_gen"] = 9
        elif kind == "unconfirmed_raised":
            d.sim.g["fallback_profile_save_unconfirmed"] = True
        else:
            raise D.DriverError(f"unknown plan-stage injection {kind!r}")
    d.sim.nvs_direct.before_op = hook


def scn_plan_stage(mk, kind: str) -> Errs:
    """One injection between the gate and the plan: the call refuses with the locked text of the PLAN layer, after exactly the fresh
    read (no writer health check, no set), nothing written, no latch, the mirror is the latest authoritative read; what follows is
    coherent (a re-armed call on the new profile / after the reboot behaves as the design says)."""
    e = Errs()
    d, w = new_drv(mk)
    _plan_hook(d, kind)
    flash0 = K.copy_blobs(d)
    wm, nm = w.mark(), K.nvs_mark(d)
    st = d.invalidate()
    want = PLAN_TEXT[kind]
    e.eq(d.b9, want, f"B9 ({kind})")
    e.eq(publishes(st), [want], "one B9 publication")
    e.eq(st.violations_fb((), reads=[]), [], "nothing written, zero Modbus")
    e.eq(st.fb_sets, [], "no FB set")
    e.eq(st.nvs_sets, [], "no NVS set")
    fbp_k, fbw_k = fd.decimal_key(K_P), fd.decimal_key(K_W)
    e.eq([(o[0], o[1]) for o in K.nvs_events_since(d, nm)], [("get", fbp_k), ("read", fbp_k), ("get", fbw_k), ("read", fbw_k), ("stats", None)],
         "exactly the fresh read (FBP, FBW, one health check): the plan refused before the writer started")
    e.ok(not d.arm_state, "arm off")
    e.ok(not d.write_latched, "a refusal does not latch the writer")
    e.eq(sorted(w.names(wm) & set(FLAG_GLOBALS)), [], "no bus flag assigned")
    e.eq(sorted(w.names(wm) - ASSIGN_FRESH), [], "globals assigned beyond the fresh-refresh set")
    e.eq(D.idle_invariants(d), [], "idle invariants")
    e.eq(D.text_invariants(d), [], "text invariants")
    if kind == "binding_changed":
        e.eq(K.image_now(d.sim.nvs_direct), {K_P: (OTHER_FBP, True, True), K_W: (OTHER_FBW, True, True)}, "flash is the OTHER pair, untouched")
        e.eq((d.b1, K.parse_kv(d.b2)["id"], K.parse_kv(d.b2)["g"]), ("VALID", OTHER_ID, "7"), "B1 / B2 show the profile found by the fresh read")
        e.eq(d.arr("fallback_profile_bytes"), list(OTHER_FBP), "mirror = the fresh read")
        e.eq((d.g["fallback_profile_class"], d.g["fallback_profile_why"]), (CLASS_NUM["VALID"], fd.WHY_NONE), "class VALID / why NONE")
        # the operator's confirmation named the OLD profile: it is NOT silently applied to the new one; a fresh arm + the new id works
        st2 = d.invalidate(target_id=OTHER_ID)
        e.eq(st2.b9, K.b9_invalidated(7), "the new profile is invalidated only with ITS id")
        e.eq(K.blobs_of(d)[K_P][0], fp.pack_profile(fp.invalidate_profile(OTHER_PROFILE)), "FBP = the OTHER profile invalidated (the old id's profile is not in flash)")
        e.eq(st2.violations_fb(("FBW", "FBP"), reads=[]), [], "FBW then FBP")
    elif kind == "seen_raised":
        e.eq(K.image_now(d.sim.nvs_direct), {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in flash0.items()}, "flash untouched")
        e.eq(d.g["fallback_profile_seen_hw_gen"], 9, "seen_hw_gen is the raised value (never lowered by the fresh read)")
        e.eq(d.b1, "VALID", "B1 VALID (nothing was written)")
        nm2 = K.nvs_mark(d)
        st2 = d.invalidate(target_id=GOLD_ID)
        e.eq(d.b9, want, "the next call is refused at the GATE with the same text")
        e.eq(K.nvs_events_since(d, nm2), [], "...with no storage access")
        e.eq(st2.fb_sets, [], "...and nothing written")
        d.reboot()
        e.eq(d.g["fallback_profile_seen_hw_gen"], GOLD_G, "reboot re-derives seen_hw_gen from the flash")
        st3 = d.invalidate()
        e.eq(st3.b9, K.b9_invalidated(GOLD_G), "after the reboot the INVALIDATE works")
    else:
        e.eq(K.image_now(d.sim.nvs_direct), {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in flash0.items()}, "flash untouched")
        e.eq(d.b1, "SAVE_UNCONFIRMED", "B1 shows the overlay (the fresh refresh publishes through overlay_class)")
        e.ok(d.g["fallback_profile_save_unconfirmed"], "the overlay is left as found (a refusal never clears it)")
        d.reboot()
        e.eq(d.b1, "VALID", "only the reboot clears the overlay")
    return e
