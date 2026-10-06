"""FB-B2 t-gates: SAVE gate refusal scenarios, part 1 - the gates G0..G16 that decide at the instant of the call (registered into
_fbb2_gates_lib.SCENARIOS).

Every refusal row checks the locked one-shot / zero-authority consequences (check_refusal): the exact locked text, the arm turned off, the
candidate consumed, zero NVS writes, zero Modbus reads beyond the Review, zero storage operations (the gate reads no storage), nothing held,
the context empty, no SAVE_UNCONFIRMED, only the one-shot globals changed.
"""

from __future__ import annotations

from _fbb2_gates_lib import *  # noqa: F401,F403
from _fbb2_gates_lib import (D, E, H, K_P, K_W, EPOCH0, READS4, TXT, Exp, GATE_REFUSAL_GLOBALS, EXEC_COPIES, check_refusal, check_saved,
                             candidate_consumed, check_refusal, execute_call, fc, fd, fp, gate_case, nothing_held, ready, scenario,
                             t_bus, t_lock_stuck, t_phrase, t_slot, t_unsupported, t_saved, SAVE_PFX, all_driver_violations)

# ---------------------------------------------------------------------------
# G0: the action token
# ---------------------------------------------------------------------------
TOKEN_ROWS = [
    ("RESTORE (reserved)", "RESTORE", TXT["RESTORE"]),
    ("ACKNOWLEDGE (reserved)", "ACKNOWLEDGE", TXT["ACKNOWLEDGE"]),
    ("retired token CAPTURE", "CAPTURE", t_unsupported("CAPTURE")),
    ("retired token APPLY", "APPLY", t_unsupported("APPLY")),
    ("retired token RETRY_APPLY", "RETRY_APPLY", t_unsupported("RETRY_APPLY")),
    ("retired token ACCEPT_LIVE", "ACCEPT_LIVE", t_unsupported("ACCEPT_LIVE")),
    ("retired token PROVISION", "PROVISION", t_unsupported("PROVISION")),
    ("lower-case save", "save", t_unsupported("save")),
    ("capitalised Save", "Save", t_unsupported("Save")),
    ("padded 'SAVE ' (sanitised)", "SAVE ", t_unsupported("SAVE?")),
    ("padded ' SAVE' (sanitised)", " SAVE", t_unsupported("?SAVE")),
    ("trailing newline (sanitised)", "SAVE\n", t_unsupported("SAVE?")),
    ("'RESTORE ' is not the reserved token", "RESTORE ", t_unsupported("RESTORE?")),
    ("lower-case restore", "restore", t_unsupported("restore")),
    ("lower-case invalidate is routed to the SAVE gate and unsupported", "invalidate", t_unsupported("invalidate")),
    ("empty token", "", t_unsupported("")),
    ("30-char token is cut to 24", "A" * 30, t_unsupported("A" * 24)),
    ("exactly 24 chars kept", "B" * 24, t_unsupported("B" * 24)),
    ("25 chars cut to 24", "C" * 25, t_unsupported("C" * 24)),
    ("punctuation sanitised", "a b;c'd\"e", t_unsupported("a?b?c?d?e")),
    ("SAVE;RESTORE sanitised", "SAVE;RESTORE", t_unsupported("SAVE?RESTORE")),
    ("embedded NUL sanitised", "SAVE\x00X", t_unsupported("SAVE?X")),
    ("underscore and digits kept", "x_9", t_unsupported("x_9")),
]


@scenario("rf_tokens", "G0: RESTORE / ACKNOWLEDGE reserved, every other token unsupported with a sanitised echo; each consumes arm + candidate")
def rf_tokens(mk, ex: Exp):
    for label, tok, want in TOKEN_ROWS:
        gate_case(ex, mk, f"token {label}", want, call={"action": tok, "confirmation": "SAVE x"}, setup=None)


# ---------------------------------------------------------------------------
# G2: the arm
# ---------------------------------------------------------------------------
@scenario("rf_arm", "G2: the arm never turned on / turned on then off by the operator; the call consumes the candidate")
def rf_arm(mk, ex: Exp):
    gate_case(ex, mk, "arm never turned on", TXT["G2"], call={"arm": False})

    def operator_changes_mind(d):
        d.arm_on()
        d.arm_off()
        return {"arm": False}
    gate_case(ex, mk, "arm on, then off by the operator before the call", TXT["G2"], setup=operator_changes_mind)

    def arm_then_review(d):
        d.arm_on()
        d.review(expect="CANDIDATE_READY")   # a Review press turns the arm off again (so the order is Review -> Arm -> Save)
        return {"arm": False}
    gate_case(ex, mk, "arm on BEFORE a fresh Review: the Review turned it off", TXT["G2"], setup=arm_then_review)


@scenario("rf_arm_ttl", "the arm lifetime: 120 s applied by the 10 s tick; the boundary on a tick; a SAVE after the lifetime is refused at G2")
def rf_arm_ttl(mk, ex: Exp):
    ex.row("TTL boundary exactly on a tick (arm on at the tick instant)")
    d = ready(mk)
    d.arm_on()
    t_on = d.arm_on_ms
    d.advance(119_999)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (119_999, True), "119999 ms after turn-on the arm is still on")
    d.advance(1)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (120_000, False), "120000 ms after turn-on the tick turned the arm off")
    ex.row("TTL one ms off the tick: the tick lag (up to ~130 s)")
    d = ready(mk)
    d.advance(1)
    d.arm_on()
    t_on = d.arm_on_ms
    d.advance(119_999)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (119_999, True), "119999 ms: on")
    d.advance(1)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (120_000, True), "120000 ms but the tick saw 119999 ms: still on (granularity)")
    d.advance(9_998)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (129_998, True), "129998 ms: still on")
    d.advance(1)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (129_999, False), "129999 ms: the tick of 130000 ms after the first tick turned it off")
    ex.row("a SAVE after the arm lifetime is refused at G2 (arm off, not 'no candidate')")
    d = ready(mk)
    d.arm_on()
    d.advance(130_000)
    ex.eq(d.arm_state, False, "the arm is off before the call")
    snap = d.snapshot()
    st = d.execute("SAVE", "0123456789ABCDEF", "SAVE 0123456789ABCDEF")
    check_refusal(ex, d, st, TXT["G2"], label="SAVE after the arm lifetime", snap=snap)
    ex.row("a SAVE at 119999 ms with the housekeeping running is accepted (both lifetimes are exact)")
    d = ready(mk)
    d.advance(119_999)
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SAVE at 119999 ms", reboot=False)
    ex.row("the arm lifetime across the 2^32 wrap of millis()")
    d = mk(seed="none")
    d.sim.rebase_clock(2 ** 32 - 60_000)
    d.review(expect="CANDIDATE_READY")
    d.arm_on()
    t_on = d.sim.now_ms
    d.advance(119_999)
    ex.eq((d.sim.now_ms - t_on, d.arm_state, d.sim.now_ms >= 2 ** 32), (119_999, True, True), "wrapped, 119999 ms: still on")
    d.advance(1)
    ex.eq((d.sim.now_ms - t_on, d.arm_state), (120_000, False), "wrapped, 120000 ms: the tick turned it off (wrap-safe)")
    ex.row("firmware never extends the arm lifetime by itself (re-arm is the operator's)")
    d = ready(mk)
    d.arm_on()
    d.advance(60_000)
    ex.eq(d.arm_state, True, "still on at 60 s (not turned off by candidate-related ticks)")
    ex.ok(d.candidate()["valid"], "the candidate is still valid at 60 s")


# ---------------------------------------------------------------------------
# G3: the candidate
# ---------------------------------------------------------------------------
@scenario("rf_candidate", "G3: no candidate / consumed by an earlier call / NOT-SAVEABLE preview with the id 0000000000000000 / saveable flag with id 0")
def rf_candidate(mk, ex: Exp):
    gate_case(ex, mk, "no Review was pressed", TXT["G3"], review=False, call={"target_id": "0123456789ABCDEF"})

    def second_call(d):
        cid = d.b4
        d.save(confirmation="wrong")       # the first call: refused at G7, consumes the candidate
        return {"target_id": cid, "confirmation": f"SAVE {cid}"}
    gate_case(ex, mk, "the candidate was consumed by an earlier refused call", TXT["G3"], setup=second_call)

    wzero = list(D.GWORDS)
    wzero[fc.REGS.index(244)] = 0
    ex.row("NOT-SAVEABLE preview (244 = 0): the id is 0000000000000000")
    d = mk(seed="none", words=wzero)
    d.review()
    ex.eq(d.b3_field("st"), "CANDIDATE_NOT_SAVEABLE", "the Review produced a NOT-SAVEABLE preview")
    ex.eq((d.candidate()["valid"], d.candidate()["saveable"], d.candidate()["id"], d.b4), (True, False, 0, "-"), "preview kept: valid, not saveable, id 0, B4 '-'")
    snap = d.snapshot()
    st = d.save(target_id="0000000000000000", confirmation="SAVE 0000000000000000")
    check_refusal(ex, d, st, TXT["G3"], label="preview + id 0 + matching phrase", snap=snap)
    ex.eq(d.stored("FBP"), None, "nothing was stored")
    ex.row("NOT-SAVEABLE preview with other ids")
    for tid, phrase in (("0000000000000000", "SAVE 0000000000000000"), ("0000000000000001", "SAVE 0000000000000001"), ("", "SAVE ")):
        d = mk(seed="none", words=wzero)
        d.review()
        st = d.save(target_id=tid, confirmation=phrase)
        check_refusal(ex, d, st, TXT["G3"], label=f"preview, target {tid!r}")

    def forced_zero_id(d):
        d.set_g("fallback_profile_cand_id", 0)      # a saveable flag with id 0 (cannot arise from a Review): still refused
        return {"target_id": "0000000000000000", "confirmation": "SAVE 0000000000000000"}
    gate_case(ex, mk, "saveable flag with id 0 (the id != 0 clause)", TXT["G3"], setup=forced_zero_id)

    def only_valid(d):
        d.set_g("fallback_profile_cand_saveable", False)   # valid but not saveable, with a real id
        return None
    gate_case(ex, mk, "valid but not saveable, real id and phrase", TXT["G3"], setup=only_valid)


# ---------------------------------------------------------------------------
# G4: expiry
# ---------------------------------------------------------------------------
@scenario("rf_expiry", "G4: 119999 ms accepted, 120000 ms refused, independent of the 10 s tick; wrap-safe near 2^32; the tick-consumed case is G3")
def rf_expiry(mk, ex: Exp):
    ex.row("housekeeping stopped: the gate's own re-check")
    d = ready(mk)
    d.stop_housekeeping()
    d.advance(119_999)
    ex.ok(d.candidate()["valid"], "119999 ms: still valid (nothing consumed it)")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="119999 ms accepted", reboot=False)
    d = ready(mk)
    d.stop_housekeeping()
    d.advance(120_000)
    ex.ok(d.candidate()["valid"], "120000 ms: the candidate is still flagged valid (no tick ran): the gate must decide")
    snap = d.snapshot()
    st = d.save()
    check_refusal(ex, d, st, TXT["G4"], label="120000 ms refused", snap=snap)
    ex.row("housekeeping RUNNING, tick lag: age 120000 ms with the next tick up to 10 s away")
    d = mk(seed="none")
    d.advance(1)
    d.review(expect="CANDIDATE_READY")
    d.advance(120_000)    # now = tick + 120001: the tick at +120000 saw age 119999, the next is 10 s away
    ex.ok(d.candidate()["valid"], "the tick has not consumed the candidate yet")
    snap = d.snapshot()
    st = d.save()
    check_refusal(ex, d, st, TXT["G4"], label="tick lag: G4 decides by itself at 120000 ms", snap=snap)
    ex.row("housekeeping running, tick consumed it first: G3")
    d = ready(mk)
    d.advance(130_000)
    ex.ok(not d.candidate()["valid"], "the tick consumed the expired candidate")
    ex.starts(d.b9, "REVIEW EXPIRED", "the tick published its own REVIEW EXPIRED line")
    snap = d.snapshot()
    st = d.save(target_id="0123456789ABCDEF")
    check_refusal(ex, d, st, TXT["G3"], label="tick-consumed candidate", snap=snap)
    ex.row("millis() wrap: Review 60 s before 2^32")
    for adv, ok in ((119_999, True), (120_000, False), (60_000, True), (59_999, True), (200_000, False)):
        d = mk(seed="none")
        d.stop_housekeeping()
        d.sim.rebase_clock(2 ** 32 - 60_000)
        d.review(expect="CANDIDATE_READY")
        d.advance(adv)
        wrapped = d.sim.now_ms >= 2 ** 32
        snap = d.snapshot()
        st = d.save()
        if ok:
            check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"wrap: {adv} ms accepted (clock wrapped: {wrapped})", reboot=False)
        else:
            check_refusal(ex, d, st, TXT["G4"], label=f"wrap: {adv} ms refused (clock wrapped: {wrapped})", snap=snap)
    ex.row("exact boundary near the wrap")
    for adv, ok in ((119_999, True), (120_000, False)):
        d = mk(seed="none")
        d.stop_housekeeping()
        d.sim.rebase_clock(2 ** 32 - 119_999)     # 119999 ms later the 32-bit clock reads exactly 0
        d.review(expect="CANDIDATE_READY")
        d.advance(adv)
        st = d.save()
        if ok:
            check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"wrap to zero: {adv} ms accepted", reboot=False)
        else:
            check_refusal(ex, d, st, TXT["G4"], label=f"wrap to zero: {adv} ms refused")


# ---------------------------------------------------------------------------
# G5 / G6: the candidate id
# ---------------------------------------------------------------------------
@scenario("rf_ids", "G5 / G6: id format (empty, 15, 17, lower-case, whitespace, non-hex) and mismatch (flipped, zeros, an older Review's id)")
def rf_ids(mk, ex: Exp):
    d0 = ready(mk)
    cid = d0.b4
    bad_format = [("empty", ""), ("short", "ABC"), ("15 chars", cid[:-1]), ("17 chars", cid + "0"), ("lower-case", cid.lower()),
                  ("trailing newline", cid + "\n"), ("leading space", " " + cid), ("trailing space", cid + " "),
                  ("non-hex G", cid[:-1] + "G"), ("0x prefix", "0x" + cid[:14]), ("dash", "-"), ("with a NUL", cid[:8] + "\x00" + cid[9:])]
    for label, tid in bad_format:
        gate_case(ex, mk, f"G5 {label}", TXT["G5"], call={"target_id": tid, "confirmation": f"SAVE {cid}"})
    flipped = cid[:-1] + ("0" if cid[-1] != "0" else "1")
    for label, tid in (("last nibble flipped", flipped), ("first nibble flipped", ("0" if cid[0] != "0" else "1") + cid[1:]),
                       ("all zeros", "0000000000000000"), ("all F", "FFFFFFFFFFFFFFFF"), ("the byte-swapped id", "".join(reversed([cid[i:i + 2] for i in range(0, 16, 2)])))):
        gate_case(ex, mk, f"G6 {label}", TXT["G6"], call={"target_id": tid, "confirmation": f"SAVE {tid}"})

    ex.row("G6 the id of an OLDER Review after a newer one")
    d = ready(mk)
    old = d.b4
    d.review(expect="CANDIDATE_READY")
    new = d.b4
    ex.ok(old != new, f"the two Reviews have different ids ({old} / {new})")
    snap = d.snapshot()
    st = d.save(target_id=old, confirmation=f"SAVE {old}")
    check_refusal(ex, d, st, TXT["G6"], label="older id", snap=snap)
    ex.row("G5 beats the phrase: a right phrase does not rescue a malformed id")
    gate_case(ex, mk, "G5 with a correct phrase", TXT["G5"], call={"target_id": cid.lower(), "confirmation": f"SAVE {cid}"})


# ---------------------------------------------------------------------------
# G7: the confirmation phrase
# ---------------------------------------------------------------------------
@scenario("rf_phrase", "G7: the exact phrase (case, whitespace, missing id, REPLACE CORRUPT only for a CORRUPT prior); the echo is the EXPECTED phrase")
def rf_phrase(mk, ex: Exp):
    d0 = ready(mk)
    cid = d0.b4
    variants = [("lower-case save", f"save {cid}"), ("trailing space", f"SAVE {cid} "), ("trailing newline", f"SAVE {cid}\n"),
                ("leading space", f" SAVE {cid}"), ("double space", f"SAVE  {cid}"), ("tab", f"SAVE\t{cid}"),
                ("no id", "SAVE"), ("no id, trailing space", "SAVE "), ("lower-case id", f"SAVE {cid.lower()}"),
                ("a different id", "SAVE 0000000000000000"), ("INVALIDATE phrase", f"INVALIDATE {cid}"), ("empty", ""),
                ("REPLACE CORRUPT when the prior is not CORRUPT", f"SAVE {cid} REPLACE CORRUPT"),
                ("id glued to REPLACE", f"SAVE {cid}REPLACE"), ("just the id", cid), ("SAVE twice", f"SAVE SAVE {cid}"),
                ("the id then SAVE", f"{cid} SAVE"), ("a NUL after the phrase", f"SAVE {cid}" + chr(0)),
                ("a NUL inside the phrase", f"SAVE" + chr(0) + f"{cid}"), ("a NUL then more text", f"SAVE {cid}" + chr(0) + "x")]
    for label, phrase in variants:
        gate_case(ex, mk, f"G7 {label}", t_phrase(cid), call={"confirmation": phrase})
    # CORRUPT prior: the expected phrase carries REPLACE CORRUPT
    dc = mk(seed="corrupt")
    dc.review(expect="CANDIDATE_READY")
    ccid = dc.b4
    ex.row("CORRUPT prior setup")
    ex.eq(dc.b3_field("prior"), "CORRUPT", "the candidate is bound to prior CORRUPT")
    cvariants = [("plain SAVE (MB36: REPLACE CORRUPT accepted without the phrase)", f"SAVE {ccid}"),
                 ("trailing space", f"SAVE {ccid} REPLACE CORRUPT "), ("lower-case replace corrupt", f"SAVE {ccid} replace corrupt"),
                 ("double space", f"SAVE {ccid} REPLACE  CORRUPT"), ("REPLACE only", f"SAVE {ccid} REPLACE"),
                 ("trailing newline", f"SAVE {ccid} REPLACE CORRUPT\n"), ("REPLACE CORRUPT first", f"REPLACE CORRUPT SAVE {ccid}"),
                 ("lower-case save", f"save {ccid} REPLACE CORRUPT"), ("empty", "")]
    for label, phrase in cvariants:
        gate_case(ex, mk, f"G7 CORRUPT prior: {label}", t_phrase(ccid, True), seed="corrupt", call={"confirmation": phrase})


# ---------------------------------------------------------------------------
# G10: the heartbeat snapshot
# ---------------------------------------------------------------------------
@scenario("rf_hb", "G10: heartbeat not SUPERVISED / not Stable / both; the snapshot is the api action's; no re-check afterwards")
def rf_hb(mk, ex: Exp):
    for label, kw in (("startup, not stable (supervise(False))", dict(ok=False)),
                      ("SUPERVISED but not Stable", dict(state=1, stable=False)),
                      ("state 0, stable true", dict(state=0, stable=True)),
                      ("state 2 (not supervised), not stable", dict(state=2, stable=False)),
                      ("state 2, stable true", dict(state=2, stable=True)),
                      ("state 3, not stable", dict(state=3, stable=False)),
                      ("state 255", dict(state=255, stable=True))):
        gate_case(ex, mk, f"G10 {label}", TXT["G10"], setup=lambda d, kw=kw: d.supervise(**kw))
    ex.row("control: SUPERVISED and Stable is accepted")
    d = ready(mk)
    d.supervise(state=1, stable=True)
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SUPERVISED + Stable", reboot=False)
    ex.row("the snapshot is taken from the live state at EVERY call (a recovered heartbeat is accepted next time)")
    d = ready(mk)
    d.supervise(False)
    snap = d.snapshot()
    st = d.save()
    check_refusal(ex, d, st, TXT["G10"], label="first call (no heartbeat)", snap=snap)
    d.supervise(True)
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="after the heartbeat recovered", reboot=False)
    ex.row("the REAL heartbeat action (three beats) makes it stable")
    d = mk(seed="none", env="bare")
    ex.eq((d.g["supervision_state"], d.g["supervision_stable"]), (0, False), "a bare boot is not supervised")
    d.set_time(ntp=True)
    d.review(expect="CANDIDATE_READY")
    snap = d.snapshot()
    st = d.save()
    check_refusal(ex, d, st, TXT["G10"], label="bare boot: refused", snap=snap)
    d.establish_supervision()
    d.set_time(ntp=True)
    ex.eq((d.g["supervision_state"], d.g["supervision_stable"]), (1, True), "three real beats: SUPERVISED and Stable")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="after three real beats", reboot=False)


# ---------------------------------------------------------------------------
# G11: trusted time
# ---------------------------------------------------------------------------
@scenario("rf_time", "G11: ntp_synced false / the clock not valid / both; the capture time would be untrusted")
def rf_time(mk, ex: Exp):
    def synced_false(d):
        d.g["ntp_synced"] = False
    def clock_invalid(d):
        d.sim.ntp_valid = False
    def both(d):
        d.untrusted_time()
    for label, fn in (("ntp_synced false, clock valid", synced_false), ("ntp_synced true, now() invalid", clock_invalid),
                      ("neither", both)):
        gate_case(ex, mk, f"G11 {label}", TXT["G11"], setup=fn)
    ex.row("a bare boot (no NTP yet): the Review still works, the SAVE is refused")
    d = mk(seed="none", env="bare")
    d.supervise(True)
    d.review(expect="CANDIDATE_READY")
    snap = d.snapshot()
    st = d.save()
    check_refusal(ex, d, st, TXT["G11"], label="bare boot", snap=snap)


# ---------------------------------------------------------------------------
# G12 / G13: write arms, writes fingerprint
# ---------------------------------------------------------------------------
@scenario("rf_write_arms", "G12: each of the three write arms on refuses; the FB arm itself is not one of them")
def rf_write_arms(mk, ex: Exp):
    for name in D.WRITE_ARMS:
        gate_case(ex, mk, f"G12 {name} on", TXT["G12"], setup=lambda d, n=name: d.write_arm(n, True))
    gate_case(ex, mk, "G12 all three on", TXT["G12"], setup=lambda d: [d.write_arm(n, True) for n in D.WRITE_ARMS] and None)
    ex.row("an armed FB arm is not a write arm (control: accepted)")
    d = ready(mk)
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="only the FB arm on", reboot=False)


WRITE_COUNTERS = ("manual_write_attempts", "reg244_apply_attempts", "reg244_restore_attempts", "free_power_start_attempts", "dump_start_attempts")


@scenario("rf_writes_fingerprint", "G13: another ECCO inverter write started since the Review (each of the five attempt counters)")
def rf_writes_fingerprint(mk, ex: Exp):
    for name in WRITE_COUNTERS:
        gate_case(ex, mk, f"G13 {name} + 1", TXT["G13"], setup=lambda d, n=name: d.set_g(n, d.g[n] + 1))
    gate_case(ex, mk, "G13 two counters", TXT["G13"], setup=lambda d: (d.set_g("manual_write_attempts", d.g["manual_write_attempts"] + 2),
                                                                         d.set_g("dump_start_attempts", d.g["dump_start_attempts"] + 1)) and None)


# ---------------------------------------------------------------------------
# G14: the bus slot
# ---------------------------------------------------------------------------
BUS_FLAGS = [
    ("manual_write_in_progress", "manual write"),
    ("correction_in_progress", "clock correction"),
    ("verification_pending", "clock verification"),
    ("verification_read_active", "clock verification"),
    ("free_power_operation_in_progress", "Free Power"),
    ("free_power_recovery_force_in_progress", "Free Power"),
    ("free_power_recovery_accept_in_progress", "Free Power"),
    ("reg244_apply_in_progress", "Register 244 test"),
    ("dump_operation_in_progress", "Dump to Grid"),
]


@scenario("rf_bus", "G14: each bus-owning flag (manual write / RTC correction / verification / Free Power / Dump / R244) names its owner; the 300 s stuck lock")
def rf_bus(mk, ex: Exp):
    for flag, owner in BUS_FLAGS:
        gate_case(ex, mk, f"G14 {flag}", t_bus(owner), setup=lambda d, f=flag: d.set_g(f, True), locked=(flag == "manual_write_in_progress"))

    def stuck(age_ms):
        def setup(d):
            d.set_g("manual_write_in_progress", True)
            d.set_g("diag_write_lock_held", True)
            d.set_g("diag_write_lock_since_ms", (d.sim.now_ms - age_ms) & 0xFFFFFFFF)
        return setup
    gate_case(ex, mk, "G14 lock held 299.999 s: still 'busy'", t_bus("manual write"), setup=stuck(299_999), locked=True)
    gate_case(ex, mk, "G14 lock held exactly 300 s: stuck", t_lock_stuck(300), setup=stuck(300_000), locked=True)
    gate_case(ex, mk, "G14 lock held 301 s: stuck", t_lock_stuck(301), setup=stuck(301_000), locked=True)
    gate_case(ex, mk, "G14 lock held 3600 s: stuck", t_lock_stuck(3600), setup=stuck(3_600_000), locked=True)

    def stuck_wrap(d):
        d.set_g("manual_write_in_progress", True)
        d.set_g("diag_write_lock_held", True)
        d.set_g("diag_write_lock_since_ms", (d.sim.now_ms + 2 ** 32 - 400_000) & 0xFFFFFFFF)
    gate_case(ex, mk, "G14 lock age across the 2^32 wrap (400 s)", t_lock_stuck(400), setup=stuck_wrap, locked=True)
    gate_case(ex, mk, "G14 diagnostic says 'not held' even if the mutex is: busy, not stuck", t_bus("manual write"),
              setup=lambda d: (d.set_g("manual_write_in_progress", True), d.set_g("diag_write_lock_held", False),
                               d.set_g("diag_write_lock_since_ms", (d.sim.now_ms - 900_000) & 0xFFFFFFFF)) and None, locked=True)
    ex.row("the Manual TOU transaction IS the mutex: it surfaces as BUS (the MTOU placeholder never says clear while the bus is busy)")
    d = ready(mk)
    d.mutex(True)
    st = d.save()
    ex.has(d.b3_field("obl"), "MT:NP", "obl shows MT not clear / not probed")
    ex.has(d.b3_field("obl"), "BUS:BY", "obl shows the BUS busy")


# ---------------------------------------------------------------------------
# G15 / G16: failback record and the lease domains
# ---------------------------------------------------------------------------
@scenario("rf_fbs", "G15: a failback episode record / corrupt / unreadable (the RAM slot read once at boot); never a runtime probe")
def rf_fbs(mk, ex: Exp):
    gate_case(ex, mk, "G15 episode record", TXT["G15_episode"], setup=lambda d: d.set_g("fallback_profile_fbs_slot", fbs_slot("episode")))
    gate_case(ex, mk, "G15 corrupt record", SAVE_PFX + "Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; "
              "do not erase NVS", setup=lambda d: d.set_g("fallback_profile_fbs_slot", fbs_slot("corrupt")))
    gate_case(ex, mk, "G15 unreadable record", SAVE_PFX + "Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; "
              "Fallback never proceeds past it", setup=lambda d: d.set_g("fallback_profile_fbs_slot", fbs_slot("unreadable")))
    ex.row("an FBS record seeded for the BOOT refuses the Review itself (no candidate): the SAVE then sees none")
    for kind in ("episode", "corrupt", "unreadable"):
        d = mk(seed="none", fbs=kind)
        d.review()
        ex.eq(d.b3_field("st"), "IDLE", f"{kind}: the Review is refused, no candidate")
        snap = d.snapshot()
        st = d.save(target_id="0123456789ABCDEF")
        check_refusal(ex, d, st, TXT["G3"], label=f"FBS {kind} at boot: SAVE sees no candidate", snap=snap)
    ex.row("FBS clear / absent are accepted (control)")
    for kind in (None, "clear"):
        d = mk(seed="none", fbs=kind)
        d.review(expect="CANDIDATE_READY")
        st = d.save()
        check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"FBS {kind}", reboot=False)


def fbs_slot(name):
    return {"unreadable": 0, "clear_absent": 1, "clear_valid": 2, "episode": 3, "corrupt": 4}[name]


LEASE_TEXT = {
    "fp_active": ("active", "fp"), "fp_restore_required": ("rr", "fp"), "fp_pending_clear": ("pc", "fp"), "fp_operator_needed": ("on", "fp"),
    "fp_metadata_corrupt": ("mc", "fp"), "dump_active": ("active", "dump"), "dump_restore_required": ("rr", "dump"),
    "dump_operator_needed": ("on", "dump"), "r244_operator_needed": ("on", "r244"), "r244_pending_clear": ("pc", "r244"),
    "r244_metadata_corrupt": ("mc", "r244"),
}


@scenario("rf_leases", "G16: every Free Power / Dump / R244 RAM leg (active, restore required, pending clear, operator needed, metadata corrupt)")
def rf_leases(mk, ex: Exp):
    for name, (kind, dom) in LEASE_TEXT.items():
        want = t_slot(kind, dom)
        if name == "dump_metadata_corrupt":
            want += "; containment K=3"
        gate_case(ex, mk, f"G16 {name}", want, setup=lambda d, n=name: d.lease(n))
    want = t_slot("mc", "dump") + "; containment K=3"
    gate_case(ex, mk, "G16 dump_metadata_corrupt (containment K=3)", want, setup=lambda d: d.lease("dump_metadata_corrupt"))


RUN_SCRIPTS = [
    ("start_free_power_override", "fp", "start", "a Free Power start is in progress; live settings are about to become a temporary overlay"),
    ("restore_free_power_snapshot", "fp", "end", None),
    ("restore_free_power_snapshot_dispatch", "fp", "end", None),
    ("free_power_recovery_review", "fp", "end", None),
    ("free_power_recovery_review_dispatch", "fp", "end", None),
    ("free_power_recovery_force_restore", "fp", "end", None),
    ("free_power_recovery_force_restore_dispatch", "fp", "end", None),
    ("free_power_recovery_accept_current_state", "fp", "end", None),
    ("free_power_recovery_accept_current_state_dispatch", "fp", "end", None),
    ("start_dump_to_grid_override", "dump", "start", None),
    ("restore_dump_to_grid_snapshot", "dump", "end", None),
    ("apply_reg244_settings", "r244", "start", None),
    ("restore_reg244_snapshot", "r244", "end", None),
]


@scenario("rf_running_scripts", "G16: a running Free Power / Dump / R244 operation script (start / restore / recovery review) refuses with its own wording")
def rf_running_scripts(mk, ex: Exp):
    for sid, dom, kind, _txt in RUN_SCRIPTS:
        want = t_slot(kind, dom)

        def setup(d, sid=sid):
            d.stop_housekeeping()       # the 10 s tick would consume the candidate itself (IE: a lease domain turned non-clear)
            d.sim.hold_script_running(sid, 60_000)
            d.advance(0)
        gate_case(ex, mk, f"G16 {sid} running", want, setup=setup)


@scenario("rf_boot_status", "G16: the boot-load status pairs (READ_ERROR + corrupt flag = unknown, flag alone = corrupt, WRONG_SIZE / READ_ERROR alone = inconsistent)")
def rf_boot_status(mk, ex: Exp):
    names = {"fp": "free_power", "dump": "dump", "r244": "reg244"}
    for dom, pre in names.items():
        for load, cor, kind in ((3, True, "unk_boot"), (2, True, "mc"), (3, False, "ram"), (2, False, "ram")):
            gate_case(ex, mk, f"G16 {dom} boot_load={load} corrupt={cor}", t_slot(kind, dom),
                      setup=lambda d, pre=pre, load=load, cor=cor: (d.set_g(f"{pre}_marker_boot_load", load),
                                                                       d.set_g(f"{pre}_recovery_metadata_corrupt", cor)) and None)
        gate_case(ex, mk, f"G16 {dom} boot_load never assigned (255)", TXT["G8"],
                  setup=lambda d, pre=pre: d.set_g(f"{pre}_marker_boot_load", 255))


LATCH_ROWS = [("unreadable at runtime", 1, "unr_runtime"), ("malformed", 2, "malformed"), ("ghost RESTORE_REQUIRED", 3, "ghost_rr"),
              ("ghost PENDING_CLEAR", 4, "ghost_pc")]


@scenario("rf_probe_latch", "G16: a sticky runtime probe latch (unreadable / malformed / ghost RR / ghost PC) refuses at the gate with zero storage access")
def rf_probe_latch(mk, ex: Exp):
    shifts = {"fp": 0, "dump": 4, "r244": 8}
    for dom, sh in shifts.items():
        for label, code, kind in LATCH_ROWS:
            gate_case(ex, mk, f"G16 latch {dom}: {label}", t_slot(kind, dom),
                      setup=lambda d, sh=sh, code=code: d.set_g("fallback_profile_probe_latch", code << sh))


# ---------------------------------------------------------------------------
# G8 / G9 / G9a: durable state flags
# ---------------------------------------------------------------------------
@scenario("rf_state_flags", "G8 boot not loaded; G9 a previous write outcome is unknown; G9a a stored-profile read anomaly this boot")
def rf_state_flags(mk, ex: Exp):
    gate_case(ex, mk, "G8 boot not loaded", TXT["G8"], setup=lambda d: d.set_g("fallback_profile_boot_loaded", False))
    gate_case(ex, mk, "G9 SAVE_UNCONFIRMED overlay set", TXT["G9"], setup=lambda d: d.set_g("fallback_profile_save_unconfirmed", True),
              unconfirmed=True)
    for bits in (1, 2, 4, 8, 0x80):
        gate_case(ex, mk, f"G9a read_anomaly = {bits:#x}", TXT["G9a"], setup=lambda d, b=bits: d.set_g("fallback_profile_read_anomaly", b))


# ---------------------------------------------------------------------------
# the ORDER: first failure wins (S1 8.5)
# ---------------------------------------------------------------------------
def _flip(cid):
    return cid[:-1] + ("0" if cid[-1] != "0" else "1")


def build_conditions():
    """gate -> (apply(d, call), expected text builder). Applied EARLIEST-GATE LAST so an earlier gate's argument overrides a later one."""
    def g1(d, call):
        d.set_g("fallback_profile_op_in_progress", True)

    def g0(d, call):
        call["action"] = "RESTORE"

    def g2(d, call):
        call["arm"] = False

    def g3(d, call):
        d.run("id(fallback_profile_invalidate_reason) = ecco_fbcap::REASON_SUPERSEDED; id(fallback_profile_invalidate_candidate).execute();")

    def g4(d, call):
        d.stop_housekeeping()
        d.advance(120_000)

    def g5(d, call):
        call["target_id"] = "XYZ"

    def g6(d, call):
        call["target_id"] = _flip(d.b4)

    def g7(d, call):
        call["confirmation"] = "nope"

    def g8(d, call):
        d.set_g("fallback_profile_boot_loaded", False)

    def g9(d, call):
        d.set_g("fallback_profile_save_unconfirmed", True)

    def g9a(d, call):
        d.set_g("fallback_profile_read_anomaly", 1)

    def g10(d, call):
        d.supervise(False)

    def g11(d, call):
        d.untrusted_time()

    def g12(d, call):
        d.write_arm("manual_config_write_enable", True)

    def g13(d, call):
        d.set_g("manual_write_attempts", d.g["manual_write_attempts"] + 1)

    def g14(d, call):
        d.set_g("manual_write_in_progress", True)

    def g15(d, call):
        d.set_g("fallback_profile_fbs_slot", 3)

    def g16fp(d, call):
        d.lease("fp_active")

    def g16dump(d, call):
        d.lease("dump_active")

    def g16r244(d, call):
        d.lease("r244_operator_needed")
    return {"G1": g1, "G0": g0, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6, "G7": g7, "G8": g8, "G9": g9, "G9a": g9a,
            "G10": g10, "G11": g11, "G12": g12, "G13": g13, "G14": g14, "G15": g15, "G16fp": g16fp, "G16dump": g16dump,
            "G16r244": g16r244}


def expected_text(first: str, active: set, cid: str, call: dict) -> str:
    """The locked text of the gate `first` (the earliest of the active ones), derived from the locked tables."""
    if first == "G1":
        return TXT["G1"]
    if first == "G0":
        return TXT["RESTORE"]
    if first in ("G2", "G3", "G4", "G5", "G6", "G8", "G9", "G9a", "G10", "G11", "G12", "G13"):
        return TXT[first]
    if first == "G7":
        return t_phrase(cid)
    if first == "G14":
        # the owner named for a mutex-only holder: Free Power / Dump to Grid when that lease slot says ACTIVE (FB-B1 rule, N1 8.x)
        owner = "Free Power" if "G16fp" in active else ("Dump to Grid" if "G16dump" in active else "manual write")
        return t_bus(owner)
    if first == "G15":
        return TXT["G15_episode"]
    if first == "G16fp":
        return t_slot("active", "fp")
    if first == "G16dump":
        return t_slot("active", "dump")
    if first == "G16r244":
        return t_slot("on", "r244")
    raise AssertionError(first)


def run_order_case(ex: Exp, mk, label: str, active_gates: list, conds):
    first = [g for g in ORDER if g in active_gates][0]
    d = ready(mk)
    cid = d.b4
    call: dict = {}
    # apply in REVERSE gate order so an earlier gate's argument overrides a later one; G4 (time) goes first of all
    for g in sorted(active_gates, key=lambda g: (g != "G4", -ORDER.index(g))):
        conds[g](d, call)
    snap = d.snapshot()
    if first == "G1":
        c = dict(call)
        st = execute_call(d, c)
        ex.eq(d.b9, TXT["G1"], f"{label}: B9")
        ex.eq(d.arm_state, False, f"{label}: arm off")
        ex.eq(st.violations_fb((), reads=[]), [], f"{label}: nothing written, no read")
        ex.eq(d.candidate()["valid"], "G3" not in active_gates, f"{label}: G1 does NOT consume the candidate")
        ex.eq(sorted(set(d.diff(snap)["globals"]) - EXEC_COPIES), [], f"{label}: only the copies / arm stamp changed")
        return
    st = execute_call(d, dict(call))
    want = expected_text(first, set(active_gates), cid, call)
    check_refusal(ex, d, st, want, label=f"{label}", snap=snap, unconfirmed=("G9" in active_gates), locked=("G14" in active_gates))


@scenario("rf_order_pairs", "first failure wins: every PAIR of simultaneous failures shows the earlier gate of S1 8.5 (190 pairs)")
def rf_order_pairs(mk, ex: Exp):
    conds = build_conditions()
    for i, a in enumerate(ORDER):
        for b in ORDER[i + 1:]:
            ex.row(f"pair {a} + {b}")
            run_order_case(ex, mk, f"{a}+{b} -> {a}", [a, b], conds)


@scenario("rf_order_suffixes", "first failure wins: all gates failing at once, then dropping the earliest one by one (20 rows)")
def rf_order_suffixes(mk, ex: Exp):
    conds = build_conditions()
    for i in range(len(ORDER)):
        ex.row(f"all gates from {ORDER[i]} on")
        run_order_case(ex, mk, f"suffix from {ORDER[i]}", ORDER[i:], conds)


@scenario("rf_order_adjacent", "first failure wins: adjacent pairs and a few spread pairs (the fast set the mutants run)")
def rf_order_adjacent(mk, ex: Exp):
    conds = build_conditions()
    pairs = [(ORDER[i], ORDER[i + 1]) for i in range(len(ORDER) - 1)] + [("G0", "G3"), ("G2", "G7"), ("G3", "G10"), ("G7", "G12"),
                                                                           ("G10", "G14"), ("G11", "G16fp"), ("G13", "G15")]
    for a, b in pairs:
        ex.row(f"pair {a} + {b}")
        run_order_case(ex, mk, f"{a}+{b} -> {a}", [a, b], conds)


@scenario("rf_oversize_arguments", "oversize / odd-length call arguments (up to 5000 chars each): every refusal is the exact bounded text, nothing overruns, nothing is written")
def rf_oversize_arguments(mk, ex: Exp):
    d0 = ready(mk)
    cid = d0.b4
    for n in (1, 15, 16, 17, 23, 24, 25, 63, 64, 65, 100, 5000):
        tok = "Q" * n
        gate_case(ex, mk, f"action of {n} chars", t_unsupported("Q" * min(n, 24)), call={"action": tok, "confirmation": f"SAVE {cid}"})
    for n in (1, 15, 17, 63, 64, 65, 5000):
        gate_case(ex, mk, f"target_id of {n} chars", TXT["G5"], call={"target_id": "A" * n, "confirmation": f"SAVE {cid}"})
    for n in (1, 21, 22, 63, 64, 65, 66, 100, 5000):
        gate_case(ex, mk, f"confirmation of {n} chars", t_phrase(cid), call={"confirmation": "S" * n})
    gate_case(ex, mk, "the right phrase followed by 5000 spaces", t_phrase(cid), call={"confirmation": f"SAVE {cid}" + " " * 5000})
    gate_case(ex, mk, "the right phrase with 5000 chars before it", t_phrase(cid), call={"confirmation": "X" * 5000 + f"SAVE {cid}"})


@scenario("rf_tick_invalidation", "the 10 s housekeeping consumes the candidate (a lease turned non-clear / another write admitted / an anomaly / an unknown outcome): the SAVE then sees none (G3)")
def rf_tick_invalidation(mk, ex: Exp):
    def tick_case(label, setup, b9_start):
        ex.row(label)
        d = ready(mk)
        before_b9 = d.b9
        setup(d)
        d.advance(10_000)
        ex.ok(not d.candidate()["valid"], f"{label}: the tick consumed the candidate")
        if b9_start:
            ex.starts(d.b9, b9_start, f"{label}: the tick published its reason")
        else:
            ex.eq(d.b9, before_b9, f"{label}: a silent consumption (the Review's own result stays)")
        snap = d.snapshot()
        st = d.save(target_id="0123456789ABCDEF")
        check_refusal(ex, d, st, TXT["G3"], label=f"{label}: SAVE", snap=snap, unconfirmed=bool(d.g["fallback_profile_save_unconfirmed"]))
    tick_case("a Free Power lease turned active", lambda d: d.lease("fp_active"), "REVIEW CLEARED - a temporary operation started (Free Power)")
    tick_case("a Dump to Grid lease turned active", lambda d: d.lease("dump_active"), "REVIEW CLEARED - a temporary operation started (Dump to Grid)")
    tick_case("a Register 244 test obligation appeared", lambda d: d.lease("r244_operator_needed"),
              "REVIEW CLEARED - a temporary operation started (Register 244 test)")
    tick_case("another ECCO inverter write was admitted", lambda d: d.set_g("manual_write_attempts", d.g["manual_write_attempts"] + 1),
              "REVIEW CLEARED - another ECCO write started since Review")
    tick_case("a read anomaly latched for the boot (IE8)", lambda d: d.set_g("fallback_profile_read_anomaly", 1), None)
    tick_case("an unknown write outcome this boot (IE8)", lambda d: d.set_g("fallback_profile_save_unconfirmed", True), None)
