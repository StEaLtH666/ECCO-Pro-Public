"""FB-B2 t-gates: SAVE refusal scenarios, part 2 - the in-flight refusals, the dispatch (bus unavailable, read failures), the lazy lease
marker probes of the SAVE final lambda, storage health (registered into _fbb2_gates_lib.SCENARIOS).

Refusals decided INSIDE the dispatch happen after the reads that already took place: their expected read list is the prefix of the four
dispatch reads, never more, and they write nothing.
"""

from __future__ import annotations

from _fbb2_gates_lib import *  # noqa: F401,F403
from _fbb2_gates_lib import (D, E, H, K_P, K_W, EPOCH0, READS4, TXT, Exp, GATE_REFUSAL_GLOBALS, EXEC_COPIES, check_refusal, check_saved,
                             candidate_consumed, execute_call, fc, fd, fp, gate_case, nothing_held, ready, scenario, t_bus, t_phrase,
                             t_read, t_saved, t_slot, SAVE_PFX, all_driver_violations)

INFLIGHT_PUBLISHERS = {"fallback_profile_last_result_text", "fallback_profile_arm"}


def check_inflight(ex: Exp, d, st, snap, label: str, *, text=None):
    """A refusal at G1: the arm and the result text, NOTHING else (the candidate, the dispatch state, B3..B6 stay as they are)."""
    want = text or TXT["G1"]
    ex.eq(d.b9, want, f"{label}: B9")
    ex.eq(d.arm_state, False, f"{label}: arm turned off")
    diff = d.diff(snap)
    ex.eq(sorted(set(diff["globals"]) - EXEC_COPIES), [], f"{label}: only the call's own argument copies / the arm stamp changed")
    ex.eq(sorted(set(diff["published"]) - INFLIGHT_PUBLISHERS), [], f"{label}: only the arm and B9 were published")
    ex.eq(diff["published"].get("fallback_profile_last_result_text"), [want], f"{label}: B9 published once")
    ex.eq(st.violations_fb((), reads=[]), [], f"{label}: no read, no write")
    ex.eq(len(st.since.nvs_ops), 0, f"{label}: no storage access")


@scenario("rf_inflight", "G1: another Fallback operation in flight touches only the arm and B9 (second execute while SAVING, INVALIDATE, Review press, forced flags)")
def rf_inflight(mk, ex: Exp):
    # --- second execute while SAVING (the real dispatch, deferred bus)
    ex.row("second SAVE while SAVING")
    d = ready(mk, mode=("deferred", 120))
    cid = d.b4
    d.arm_on()
    d.execute("SAVE", cid, f"SAVE {cid}", idle=False)
    d.advance(100)
    ex.eq(d.b3_field("st"), "SAVING", "the first SAVE is SAVING")
    snap = d.snapshot()
    held_before = (d.g["fallback_profile_op_in_progress"], d.g["manual_write_in_progress"], d.g["fallback_profile_op_purpose"])
    d.arm_on()
    st2 = d.execute("SAVE", cid, f"SAVE {cid}", idle=False)
    check_inflight(ex, d, st2, snap, "second SAVE")
    ex.eq((d.g["fallback_profile_op_in_progress"], d.g["manual_write_in_progress"], d.g["fallback_profile_op_purpose"]), held_before,
          "the first SAVE's flags are untouched")
    ex.eq(d.b3_field("st"), "SAVING", "B3 still SAVING")
    ex.eq(d.g["fallback_profile_save_ctx_valid"], True, "the save context is untouched")
    ex.row("second INVALIDATE while SAVING")
    snap = d.snapshot()
    d.arm_on()
    st3 = d.execute("INVALIDATE", "0123456789ABCDEF", "INVALIDATE 0123456789ABCDEF", idle=False)
    check_inflight(ex, d, st3, snap, "INVALIDATE during SAVING", text="INVALIDATE REFUSED - another Fallback Profile operation is in progress")
    ex.row("an unsupported token while SAVING is also a G1 refusal (J19)")
    snap = d.snapshot()
    d.arm_on()
    st4 = d.execute("RESTORE", cid, f"SAVE {cid}", idle=False)
    check_inflight(ex, d, st4, snap, "RESTORE during SAVING")
    ex.row("a Review press during SAVING is refused and changes nothing")
    snap = d.snapshot()
    d.arm_on()
    pre_arm = d.arm_state
    stp = d.press_review(idle=False)
    ex.eq(d.b9, "REVIEW REFUSED - another Fallback Profile operation is in progress", "Review refused at V1")
    ex.eq(sorted(set(d.diff(snap)["globals"]) - {"fallback_profile_arm_on_ms"}), [], "the refused Review changed no global")
    ex.eq(d.arm_state, True, "a Review refused at V1 does not touch the arm (the turn-off comes after V1)")
    d.arm_off()
    ex.row("the first SAVE still commits the reviewed bytes")
    d.idle()
    ex.eq(d.b9, t_saved(1), "B9 SAVED")
    ex.eq(d.stored("FBP"), exp_profile_g1(), "stored FBP is the golden generation-1 profile")
    ex.eq(d.model_class()[:2], ("VALID", "-"), "oracle: VALID")
    ex.eq(nothing_held(d), [], "released")
    ex.eq(all_driver_violations(d), [], "no Modbus write, no third key")
    ex.eq(d.modbus_reads(), READS4 + READS4, "exactly the Review's four reads and the one SAVE's four reads")
    ex.eq([n for _b, n, _x, _r in d.nvs_set_history()], ["FBW", "FBP"], "exactly one witness-first pair")

    # --- forced flags with a valid candidate: the candidate must survive
    def forced(label, setup):
        ex.row(label)
        d = ready(mk)
        d.stop_housekeeping()
        cand = d.candidate()
        snap = None
        setup(d)
        snap = d.snapshot()
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)
        check_inflight(ex, d, st, snap, label)
        c2 = d.candidate()
        ex.eq((c2["valid"], c2["saveable"], c2["id"], c2["words"]), (cand["valid"], cand["saveable"], cand["id"], cand["words"]),
              f"{label}: the candidate is untouched")
        ex.eq(d.b3_field("st"), "CANDIDATE_READY", f"{label}: B3 still shows the candidate")
        ex.ok(d.b4 != "-", f"{label}: B4 still shows the id")
    forced("op flag set (no dispatch)", lambda d: d.set_g("fallback_profile_op_in_progress", True))

    def hold_dispatch(d):
        d.sim.hold_script_running("fallback_profile_capture_dispatch", 60_000)
        d.advance(0)
    forced("dispatch running while the op flag is clear (the is_running() term)", hold_dispatch)

    # --- a Review READING when the SAVE call arrives
    ex.row("SAVE call while a Review is READING")
    d = mk(seed="none", mode=("deferred", 120))
    d.press_review(idle=False)
    d.advance(100)
    ex.eq(d.b3_field("st"), "READING", "the Review is reading")
    d.arm_on()
    snap = d.snapshot()
    st = d.execute("SAVE", "0123456789ABCDEF", "SAVE 0123456789ABCDEF", idle=False)
    check_inflight(ex, d, st, snap, "SAVE during a Review's READING")
    d.idle()
    ex.eq(d.b3_field("st"), "CANDIDATE_READY", "the Review finished with a candidate")
    ex.eq(d.arm_state, False, "the arm stayed off")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SAVE after the interrupted Review", reads=READS4, reboot=False)


def exp_profile_g1():
    return D.gold_profile(generation=1, captured_epoch=EPOCH0)


# ---------------------------------------------------------------------------
# the dispatch: bus unavailable
# ---------------------------------------------------------------------------
@scenario("rf_dispatch_bus", "bus unavailable: the 7 s idle wait (hold / pollers / frames), the 3 s pre-commit drain; refusals read nothing and write nothing")
def rf_dispatch_bus(mk, ex: Exp):
    ex.row("hub busy for the whole 7 s idle wait")
    for hold in (7_100, 7_500, 30_000):
        d = ready(mk)
        d.hold_bus(hold)
        snap = d.snapshot()
        st = d.save()
        check_refusal(ex, d, st, TXT["idle7"], reads=[], label=f"hub busy {hold} ms", snap=None, accepted=True)
        ex.eq(st.elapsed_ms, 7_000, f"hub busy {hold} ms: the wait is bounded at 7000 ms")
        ex.eq(d.b3_field("st"), "IDLE", f"hub busy {hold} ms: B3 left the SAVING state")
    ex.row("the bus frees before 7 s: the SAVE proceeds and commits")
    for hold in (500, 3_000, 6_900):
        d = ready(mk)
        d.hold_bus(hold)
        st = d.save()
        check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"hub busy {hold} ms then free", reboot=False)
        ex.eq(st.elapsed_ms, hold, f"hub busy {hold} ms: the reads started when the bus freed")
    ex.row("each of the four idle terms alone delays and, when it never frees, refuses")
    for term in ("poll_inverter_configuration_dispatch", "poll_inverter_telemetry"):
        d = ready(mk)
        d.sim.hold_script_running(term, 5_000)
        d.advance(0)
        st = d.save()
        check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"{term} running 5 s", reboot=False)
        ex.eq(st.elapsed_ms, 5_000, f"{term}: the SAVE waited for the poller")
        d = ready(mk)
        d.sim.hold_script_running(term, 9_000)
        d.advance(0)
        st = d.save()
        check_refusal(ex, d, st, TXT["idle7"], reads=[], label=f"{term} running 9 s", accepted=True)
    # a frame queued on the hub (a foreign master / the poller's own frame): tx buffer not empty
    d = ready(mk, mode=("deferred", 120))
    d.sim.inject_foreign_frame(230, 3, latency_ms=2_000)
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="a foreign frame on the wire for 2 s", reboot=False)

    ex.row("the pre-commit drain (SAVE only): the bus busy right after the last read")

    def after_r4(duration, kind="hold"):
        n = [0]

        def pred(ev):
            if ev[0] == "deliver" and ev[1] == "fw" and ev[2] == 241:
                n[0] += 1
                return n[0] == 2          # R2 is the first 241/53 delivery of the SAVE, R4 the second
            return False

        def fn(sim):
            if kind == "hold":
                sim.hold_bus(duration)
            else:
                sim.hold_script_running(kind, duration)
        return pred, fn
    for dur, ok in ((2_000, True), (2_900, True), (3_100, False), (6_000, False)):
        d = ready(mk, mode=("deferred", 120))
        pred, fn = after_r4(dur)
        d.when(pred, fn)
        t0 = d.sim.now_ms
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        if ok:
            check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"bus busy {dur} ms after R4: the drain waits", reboot=False)
        else:
            # the drain timed out after 3 s; the commit lambda's own bus-quiet check refuses (tx blocked): reads happened, nothing written
            check_refusal(ex, d, st, TXT["bus_quiet"], reads=READS4, nvs_ops=None, label=f"bus busy {dur} ms after R4: not quiet at commit", accepted=True)
            ex.eq(d.stored("FBP"), None, f"bus busy {dur} ms: nothing stored")
            ex.eq(d.stored("FBW"), None, f"bus busy {dur} ms: nothing stored (witness)")
    # FB-B2 (final review F6): the commit's own tx_buffer_empty term. A frame queued on the hub after the last read that never leaves it
    # (tx buffer NOT empty, bus NOT blocked): the 3 s drain times out and the commit-time bus-quiet predicate refuses.
    ex.row("a frame queued on the hub after R4 and never sent (tx buffer not empty, bus not blocked): the 3 s drain times out and the commit's own tx_buffer_empty term refuses")
    d = ready(mk, mode=("deferred", 120))
    pred, _fn = after_r4(0)
    d.when(pred, lambda sim: setattr(sim.hub, "queued", 1))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_refusal(ex, d, st, TXT["bus_quiet"], reads=READS4, nvs_ops=None, label="a frame queued after R4 and never sent", accepted=True)
    ex.ok(3_000 <= st.elapsed_ms < 7_000, f"the drain waited its 3 s before the commit refused ({st.elapsed_ms} ms)")
    ex.eq(d.stored("FBP"), None, "a queued frame: nothing stored")
    ex.eq(d.stored("FBW"), None, "a queued frame: nothing stored (witness)")
    # a poller still running when the drain times out does NOT refuse by itself: commit_bus_quiet has no poller term
    d = ready(mk, mode=("deferred", 120))
    pred, fn = after_r4(4_000, "poll_inverter_telemetry")
    d.when(pred, fn)
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="a poller running 4 s after R4: the drain times out silently, the commit stands",
                reboot=False)


# ---------------------------------------------------------------------------
# the dispatch: Modbus read failures on each of the four reads
# ---------------------------------------------------------------------------
BLK = ["230/3", "241/53", "230/3", "241/53"]
READ_FAILS = [
    ("no_response", "no_response", {}),
    ("exception", {"outcome": "error", "exception_code": 2}, {"code": 2}),
    ("exception 0x0B", {"outcome": "error", "exception_code": 11}, {"code": 11, "kind": "exception"}),
    ("nonstandard", "custom_response", {}),
    ("not_sent", "not_sent", {}),
    ("short", {"outcome": "ok", "values": [1]}, {}),
    ("bounded", "timeout", {}),
]


@scenario("rf_read_failures", "each of the four dispatch reads failing (no response / exception / short / non-standard / not queued / 3 s wait): fail-fast, nothing written")
def rf_read_failures(mk, ex: Exp):
    for k in (1, 2, 3, 4):
        for name, spec, extra in READ_FAILS:
            kind = extra.get("kind", name if name != "exception 0x0B" else "exception")
            code = extra.get("code", 2)
            label = f"read {k} ({BLK[k - 1]}): {name}"
            ex.row(label)
            d = ready(mk)
            d.sim.queue_frames(*(["ok"] * (k - 1) + [spec]))
            snap = d.snapshot()
            st = d.save()
            check_refusal(ex, d, st, t_read(kind, BLK[k - 1], code), reads=READS4[:k], label=label, snap=None, accepted=True)
            ex.eq(st.elapsed_ms, 3_000 if name == "bounded" else 0, f"{label}: elapsed")
            ex.eq(d.b3_field("st"), "IDLE", f"{label}: B3 left SAVING")
            ex.eq(d.g["fallback_profile_op_in_progress"], False, f"{label}: op flag released")
    for k in (1, 2, 3, 4):
        for name in ("no_response", "exception"):
            spec = "no_response" if name == "no_response" else {"outcome": "error", "exception_code": 2}
            label = f"deferred bus, read {k}: {name}"
            ex.row(label)
            d = ready(mk, mode=("deferred", 120))
            d.sim.queue_frames(*(["ok"] * (k - 1) + [spec]))
            st = d.save()
            check_refusal(ex, d, st, t_read(name, BLK[k - 1]), reads=READS4[:k], label=label, snap=None, accepted=True)


# ---------------------------------------------------------------------------
# the SAVE final lambda: the lazy lease marker probes (S1 4.2)
# ---------------------------------------------------------------------------
PROBE_CASES = [
    ("ghost RESTORE_REQUIRED", dict(state=1, kw={"legacy": False}), 3, "ghost_rr"),
    ("ghost PENDING_CLEAR", dict(state=2, kw={"legacy": False}), 4, "ghost_pc"),
    ("crc-bad chunk (read error, then ESP_FAIL, then ABSENT)", dict(state=0, kw={"legacy": False, "crc_ok": False}), 1, "unr_runtime"),
    ("missing chunk (ESP_FAIL, then ABSENT)", dict(state=0, kw={"legacy": False, "chunk_present": False}), 1, "unr_runtime"),
    ("queued ESP_FAIL x2", dict(state=None, kw=None, queue=[fd.IDF_FAIL, fd.IDF_FAIL]), 1, "unr_runtime"),
    ("bad magic", dict(state=0, kw={"legacy": False, "magic": 0x1234}), 2, "malformed"),
    ("wrong size", dict(state=0, kw={"legacy": False, "size": 24}), 2, "malformed"),
]
DOMS = {"fp": ("FP", 0), "dump": ("DP", 4), "r244": ("R4", 8)}
D_LABEL = {"fp": "Free Power", "dump": "Dump to Grid", "r244": "Register 244 test"}
LATCH_FRAGMENT = {"ghost_rr": "stored marker says RESTORE_REQUIRED but memory says clear", "ghost_pc": "stored marker says PENDING_CLEAR but memory says clear",
                  "unr_runtime": "recovery marker became unreadable at runtime", "malformed": "recovery marker is malformed (found at runtime)"}


def _seed_probe(d, dom, spec):
    tag = D.MARKER_TAGS[dom]
    if spec.get("state") is not None:
        d.sim.seed_marker(tag, spec["state"], **spec["kw"])
    if spec.get("queue"):
        d.sim.nvs_direct.read_faults[fp.tag_key_fnv1_32(tag)] = list(spec["queue"])


def marker_keys():
    return {dom: fp.tag_key_fnv1_32(D.MARKER_TAGS[dom]) for dom in D.MARKER_TAGS}


def marker_get_counts(st) -> dict:
    keys = {dec: dom for dom, k in marker_keys().items() for dec in (fd.decimal_key(k),)}
    out = {dom: 0 for dom in D.MARKER_TAGS}
    for op in st.since.nvs_ops:
        if op[0] == "get" and op[1] in keys:
            out[keys[op[1]]] += 1
    return out


@scenario("rf_final_probes", "the lease markers are probed ONCE each by the SAVE final lambda, only when every RAM leg is clear; a bad one is refused and latched for the boot")
def rf_final_probes(mk, ex: Exp):
    for dom, (short, shift) in DOMS.items():
        for name, spec, code, kind in PROBE_CASES:
            label = f"{dom}: {name}"
            ex.row(label)
            d = ready(mk)
            _seed_probe(d, dom, spec)
            st = d.save()
            check_refusal(ex, d, st, t_slot(kind, dom), reads=READS4, nvs_ops=None, label=label, accepted=True)
            ex.eq(marker_get_counts(st), {"fp": 1, "dump": 1, "r244": 1}, f"{label}: each marker probed exactly once")
            ex.eq(d.g["fallback_profile_probe_latch"], code << shift, f"{label}: the latch holds code {code} for {short}")
            ex.eq(d.b3_field("latch"), short, f"{label}: B3 latch= {short}")
            ex.eq(d.stored("FBP"), None, f"{label}: nothing stored")
            # the same boot, a second Review: refused at the gate with zero reads and zero storage access (sticky, never re-probed)
            d.review()
            ex.eq(d.b3_field("st"), "IDLE", f"{label}: the next Review is refused (latched)")
            ex.ok(d.b9.startswith("REVIEW REFUSED - " + D_LABEL[dom] + " ") and LATCH_FRAGMENT[kind] in d.b9,
                  f"{label}: the Review shows the latch text: {d.b9[:120]!r}")
            st2 = d.save(target_id="0123456789ABCDEF")
            check_refusal(ex, d, st2, TXT["G3"], reads=[], nvs_ops=0, label=f"{label}: a SAVE after the latch")
    ex.row("control: a CLEAR marker and an ABSENT marker are accepted, once each")
    for dom in DOMS:
        for state in (0, None):
            d = ready(mk)
            if state is not None:
                d.sim.seed_marker(D.MARKER_TAGS[dom], state)
            st = d.save()
            check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"{dom} marker {'CLEAR' if state == 0 else 'ABSENT'}", reboot=False)
            ex.eq(marker_get_counts(st), {"fp": 1, "dump": 1, "r244": 1}, f"{dom}: each marker probed exactly once on the way to the commit")
    ex.row("the latch survives and is per boot: a reboot clears it (the marker then reads as the boot finds it)")
    d = ready(mk)
    _seed_probe(d, "fp", dict(state=1, kw={"legacy": False}))
    d.save()
    ex.eq(d.g["fallback_profile_probe_latch"], 3, "latched FP ghost RR")
    d.reboot()
    ex.eq(d.g["fallback_profile_probe_latch"], 0, "the latch is RAM only: a reboot clears it")


@scenario("rf_final_lazy_order", "no marker is probed before the RAM legs are decided: a RAM leg turning non-clear during the dispatch refuses with ZERO marker reads")
def rf_final_lazy_order(mk, ex: Exp):
    for ram_lease, dom_ram, kind in (("dump_active", "dump", "active"), ("fp_active", "fp", "active"), ("r244_operator_needed", "r244", "on")):
        label = f"{ram_lease} appears during the reads, a ghost marker is waiting"
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        ghost_dom = "fp" if dom_ram != "fp" else "dump"
        _seed_probe(d, ghost_dom, dict(state=1, kw={"legacy": False}))
        n = [0]
        d.when(lambda ev: ev[0] == "deliver" and ev[1] == "fw" and ev[2] == 241 and (n.__setitem__(0, n[0] + 1) or n[0] == 1),
               lambda sim: d.lease(ram_lease))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, t_slot(kind, dom_ram), reads=READS4, nvs_ops=0, label=label, accepted=True)
        ex.eq(d.g["fallback_profile_probe_latch"], 0, f"{label}: no latch (nothing was probed)")


# ---------------------------------------------------------------------------
# storage health
# ---------------------------------------------------------------------------
@scenario("rf_storage_health", "storage not healthy at the SAVE final lambda / between the fresh read and the commit: nothing written")
def rf_storage_health(mk, ex: Exp):
    ex.row("nvs unhealthy before the SAVE (the fresh read classes the profile UNREADABLE: the stored profile is not the reviewed one)")
    d = ready(mk)
    d.unhealthy()
    st = d.save()
    check_refusal(ex, d, st, TXT["prior_changed"], reads=READS4, nvs_ops=None, label="unhealthy at the fresh read", accepted=True)
    ex.eq(d.b1, "UNREADABLE", "B1 shows the fresh read (UNREADABLE), the latest authoritative read wins")
    ex.ok(d.g["fallback_profile_read_anomaly"] != 0, "the read anomaly latch is set for the rest of the boot")
    d.sim.nvs_direct.healthy = True
    d.review()
    ex.eq(d.b3_field("st"), "CANDIDATE_NOT_SAVEABLE", "the next Review is not saveable (anomaly latched until reboot)")
    st2 = d.save(target_id="0123456789ABCDEF")
    check_refusal(ex, d, st2, TXT["G3"], reads=[], nvs_ops=0, label="a SAVE after the anomaly: no saveable candidate")
    d.reboot()
    ex.eq(d.b1, "NOT_CAPTURED", "a reboot re-derives the class")
    ex.row("health flips between the fresh read and the commit: the writer refuses (REFUSED_LATCHED / STORAGE_UNHEALTHY)")
    d = ready(mk)
    cnt = [0]

    def hook(op, key):
        if op == "stats":
            cnt[0] += 1
            if cnt[0] == 2:
                d.sim.nvs_direct.healthy = False
    d.sim.nvs_direct.before_op = hook
    st = d.save()
    check_refusal(ex, d, st, TXT["storage_unhealthy"], reads=READS4, nvs_ops=None, label="healthy at the fresh read, not at the commit", accepted=True)
    ex.eq(d.b1, "NOT_CAPTURED", "the mirror is unchanged (a refusal writes nothing)")
    ex.eq(d.stored("FBP"), None, "no FBP")
    ex.eq(d.stored("FBW"), None, "no FBW")
    ex.eq(d.write_latched, False, "a REFUSED commit does not latch the writer")
    ex.row("NVS unavailable (handle 0) after the boot: the lease markers cannot be probed; refused, latched, nothing written")
    d = ready(mk)
    d.sim.nvs_direct.handle_value = 0
    st = d.save()
    check_refusal(ex, d, st, t_slot("unr_runtime", "fp"), reads=READS4, nvs_ops=None, label="handle 0", accepted=True)
    ex.eq(d.stored("FBP"), None, "nothing stored")


# ---------------------------------------------------------------------------
# after a REAL unknown outcome: SAVE_UNCONFIRMED consequences at the gate
# ---------------------------------------------------------------------------
@scenario("rf_after_unknown", "after a real UNKNOWN write outcome: the overlay refuses every later SAVE (no writes), a reboot is the resolution")
def rf_after_unknown(mk, ex: Exp):
    d = ready(mk, seed="valid")
    d.fault_write("FBW", result=fd.IDF_ERR_NVS_NOT_ENOUGH_SPACE, visible=H.VIS_OLD)
    st = d.save()
    ex.row("the fault")
    ex.starts(d.b9, "SAVE OUTCOME UNKNOWN - ", "B9 reports an unknown outcome")
    ex.eq(d.b1, "SAVE_UNCONFIRMED", "B1 shows the overlay")
    ex.eq((d.g["fallback_profile_save_unconfirmed"], d.write_latched), (True, True), "overlay + writer latch")
    ex.eq(d.arm_state, False, "arm off")
    ex.ok(candidate_consumed(d), "candidate consumed")
    n_sets = len(d.nvs_set_history())
    ex.row("a new Review is not saveable and a SAVE is refused with zero writes")
    d.review()
    ex.eq(d.b3_field("st"), "CANDIDATE_NOT_SAVEABLE", "the Review shows a not-saveable preview")
    ex.eq(d.b1, "SAVE_UNCONFIRMED", "B1 stays the overlay (no recomposed class over it)")
    snap = d.snapshot()
    st2 = d.save(target_id="0123456789ABCDEF")
    ex.eq(d.b9, TXT["G3"], "SAVE refused (no saveable candidate)")
    ex.eq(st2.violations_fb((), reads=[]), [], "no read, no write")
    ex.eq(len(d.nvs_set_history()), n_sets, "no further durable set")
    ex.row("forced candidate + the overlay: G9")
    d.set_g("fallback_profile_cand_valid", True)
    d.set_g("fallback_profile_cand_saveable", True)
    d.set_g("fallback_profile_cand_id", 0x1122334455667788)
    d.set_g("fallback_profile_cand_ms", d.sim.now_ms & 0xFFFFFFFF)
    d.arm_on()
    st3 = d.execute("SAVE", "1122334455667788", "SAVE 1122334455667788")
    ex.eq(d.b9, TXT["G9"], "G9: previous save outcome unknown this boot")
    ex.eq(st3.violations_fb((), reads=[]), [], "no read, no write")
    ex.row("a reboot resolves it")
    d.reboot()
    ex.eq(d.g["fallback_profile_save_unconfirmed"], False, "the overlay is RAM only")
    ex.eq(d.write_latched, False, "the writer latch is per boot")
    ex.eq(d.b1, d.model_class()[0], "B1 is whatever the NVS image composes to (oracle)")


# ---------------------------------------------------------------------------
# the generation counter
# ---------------------------------------------------------------------------
@scenario("rf_generation_exhausted", "generation arithmetic at the top of the range: 0xFFFFFFFE saves as 0xFFFFFFFF, 0xFFFFFFFF refuses (never wraps to 0)")
def rf_generation_exhausted(mk, ex: Exp):
    top = 0xFFFFFFFF
    prof_e = D.gold_profile(generation=top - 1)
    ex.row("VALID g = 0xFFFFFFFE: the SAVE commits generation 0xFFFFFFFF")
    d = mk(seed={"fbp": prof_e, "fbw": D.prov_bytes(top - 1, prof_e["binding"], top - 2)})
    ex.eq(d.model_class()[0], "VALID", "the seeded image is VALID (oracle)")
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=top, prior_gen=top - 1, prior_binding=prof_e["binding"], label="SAVE over g=0xFFFFFFFE")
    ex.row("at 0xFFFFFFFF: refused with the exact text, nothing written, no wrap")
    prof_t = D.gold_profile(generation=top)
    for label, seed in (("a profile committed at 0xFFFFFFFF this boot", None),
                        ("booted at 0xFFFFFFFF", {"fbp": prof_t, "fbw": D.prov_bytes(top, prof_t["binding"], top - 1)})):
        d = mk(seed=seed) if seed is not None else None
        if d is None:
            d = mk(seed={"fbp": prof_e, "fbw": D.prov_bytes(top - 1, prof_e["binding"], top - 2)})
            d.review(expect="CANDIDATE_READY")
            d.save()
        d.review(expect="CANDIDATE_READY")
        before = d.stored("FBP")
        st = d.save()
        check_refusal(ex, d, st, SAVE_PFX + "profile generation counter exhausted; profile unchanged", reads=READS4, nvs_ops=None, label=label, snap=None,
                      accepted=True)
        ex.eq(d.stored("FBP"), before, f"{label}: the stored profile is untouched")
        ex.eq(d.stored("FBP")["generation"], top, f"{label}: still generation 0xFFFFFFFF (no wrap to 0)")


# ---------------------------------------------------------------------------
# a late reply
# ---------------------------------------------------------------------------
@scenario("rf_late_reply", "a reply arriving AFTER the 3 s bounded wait has refused the SAVE is ignored (it cannot write stale words into the next operation)")
def rf_late_reply(mk, ex: Exp):
    ex.row("the late first reply after the refusal")
    d = ready(mk, mode=("deferred", 120))
    d.sim.queue_frames({"outcome": "ok", "latency_ms": 3_100})
    d.arm_on()
    t0 = d.sim.now_ms
    d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)
    d.advance(3_050)
    ex.eq(d.b9, t_read("bounded", "230/3"), "refused at the 3 s bounded wait")
    ex.eq(nothing_held(d), [], "released")
    ex.eq(d.arr("fallback_profile_pass1")[:3], [0, 0, 0], "no words stored yet")
    d.advance(100)
    ex.eq(d.arr("fallback_profile_pass1")[:3], [0, 0, 0], "the late reply (delivered at 3.1 s) was ignored by the guarded handler")
    ex.eq(d.b9, t_read("bounded", "230/3"), "B9 unchanged by the late reply")
    ex.eq(d.stored("FBP"), None, "nothing stored")
    ex.row("a Review pressed before the late reply arrives is not polluted by it")
    d = ready(mk, mode=("deferred", 120))
    d.sim.queue_frames({"outcome": "ok", "latency_ms": 3_100})
    d.arm_on()
    d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)
    d.advance(3_050)
    d.press_review(idle=False)
    d.idle()
    ex.eq(d.b3_field("st"), "CANDIDATE_READY", "the Review completed")
    ex.eq(d.candidate()["words"], list(D.GWORDS), "its candidate words are the inverter's (the late reply wrote nothing into it)")
    ex.eq(d.modbus_writes(), [], "no Modbus write")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SAVE after the late-reply episode", reboot=False)
