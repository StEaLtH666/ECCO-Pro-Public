"""FB-B2 t-gates: SAVE race / change scenarios (registered into _fbb2_gates_lib.SCENARIOS).

The inverter changing under the SAVE, the candidate / call arguments clobbered mid-dispatch, a temporary operation appearing before the
commit, the clock lost, the stored profile changed behind the SAVE, the heartbeat snapshot, the arm lifetime / one-shot rules. The
universal invariant of every row: either the reviewed bytes are committed (witness first) or NOTHING is written - never different bytes.
"""

from __future__ import annotations

import re

from _fbb2_gates_lib import *  # noqa: F401,F403
from _fbb2_gates_lib import (D, E, H, K_P, K_W, EPOCH0, READS4, TXT, Exp, GATE_REFUSAL_GLOBALS, EXEC_COPIES, check_refusal, check_saved,
                             candidate_consumed, execute_call, exp_profile, exp_witness, fc, fd, fp, gate_case, nothing_held, ready,
                             scenario, t_bus, t_during_read, t_since_review, t_slot, t_saved, SAVE_PFX, all_driver_violations, live_text,
                             pair_bytes, word_index)


def nth_deliver(n: int, addr: int | None = None):
    """Event predicate: the n-th Modbus reply delivered to the firmware from now on (optionally only for `addr`)."""
    cnt = [0]

    def pred(ev):
        if ev[0] == "deliver" and ev[1] == "fw" and (addr is None or ev[2] == addr):
            cnt[0] += 1
            return cnt[0] == n
        return False
    return pred


def committed_words_ok(ex: Exp, d, reviewed_words, label: str):
    """The universal invariant: nothing written, or exactly FBW then FBP whose payload is the reviewed words."""
    sets = d.nvs_set_history()
    if not sets:
        return "refused"
    names = [x[1] for x in sets]
    ex.eq(names, ["FBW", "FBP"], f"{label}: when anything is written it is witness first, then profile")
    fbp = d.stored("FBP")
    ex.ok(fbp is not None and list(fc.words_of(fbp)) == list(reviewed_words), f"{label}: the committed FBP payload is the REVIEWED words")
    return "saved"


# ---------------------------------------------------------------------------
# each of the 31 words changing between Review and SAVE
# ---------------------------------------------------------------------------
@scenario("rc_word_changed_since_review", "each of the 31 words changed between Review and SAVE: 'changed since Review (register <r>...)', nothing written")
def rc_word_changed_since_review(mk, ex: Exp):
    for i, reg in enumerate(fc.REGS):
        label = f"register {reg} (word {i})"
        ex.row(label)
        d = ready(mk)
        old = d.words[i]
        new = (old + 1) & 0xFFFF
        d.poke(reg, new)
        st = d.save()
        check_refusal(ex, d, st, t_since_review(reg, old, new), reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
        ex.eq(d.stored("FBP"), None, f"{label}: nothing stored")
    ex.row("a different kind of change per word class (bit flip of the top bit)")
    for i, reg in enumerate(fc.REGS):
        d = ready(mk)
        old = d.words[i]
        new = old ^ 0x8000
        d.poke(reg, new)
        st = d.save()
        check_refusal(ex, d, st, t_since_review(reg, old, new), reads=READS4, nvs_ops=0, label=f"register {reg} top bit", snap=None, accepted=True)
    ex.row("two registers changed: the FIRST differing register (REGS order) is named")
    d = ready(mk)
    d.poke(279, d.words[word_index(279)] ^ 1)
    d.poke(256, d.words[word_index(256)] ^ 1)
    st = d.save()
    check_refusal(ex, d, st, t_since_review(256, d.words[word_index(256)], d.words[word_index(256)] ^ 1), reads=READS4, nvs_ops=0,
                  label="two changes", snap=None, accepted=True)
    ex.row("control: changed and changed back before the SAVE = accepted")
    d = ready(mk)
    d.poke(256, 1234)
    d.poke(256, d.words[word_index(256)])
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="changed and restored", reboot=False)


@scenario("rc_word_differs_between_passes", "each of the 31 words differing between the two passes of the SAVE re-read: 'changed during the read'")
def rc_word_differs_between_passes(mk, ex: Exp):
    for i, reg in enumerate(fc.REGS):
        for k in ((3,) if reg in (230, 232) else (3, 4)):
            label = f"register {reg}: changed before read {k}"
            ex.row(label)
            d = ready(mk)
            old = d.words[i]
            new = (old + 1) & 0xFFFF
            d.change_word_before_read(k, i, new)
            st = d.save()
            check_refusal(ex, d, st, t_during_read(reg, old, new), reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
    ex.row("flapped: changed before R1, restored before R3 (pass 1 differs, pass 2 equals the reviewed words)")
    for i, reg in enumerate(fc.REGS):
        d = ready(mk)
        old = d.words[i]
        new = (old + 7) & 0xFFFF
        d.change_word_before_read(1, i, new)
        d.change_word_before_read(3, i, old)
        st = d.save()
        check_refusal(ex, d, st, t_during_read(reg, new, old), reads=READS4, nvs_ops=0, label=f"register {reg} flapped", snap=None, accepted=True)


def _read_times(d, since_ms):
    """virtual times (relative to since_ms) at which the SAVE's four reads took their snapshot of the bank."""
    return [w.t_start - since_ms for w in d.sim.wire_log if w.kind == "read" and w.origin == "fw" and w.t_start >= since_ms]


@scenario("rc_deferred_bank_sweep", "a word changing at every instant around the four reads of a deferred SAVE: refused with the right text, or the reviewed bytes committed")
def rc_deferred_bank_sweep(mk, ex: Exp):
    ex.row("calibration: the snapshot instants of the four reads")
    d = ready(mk, mode=("deferred", 120))
    t0 = d.sim.now_ms
    d.save()
    ts = _read_times(d, t0)
    ex.eq(len(ts), 4, "four reads on the wire")
    ex.ok(ts == sorted(ts) and ts[1] - ts[0] == 120, f"snapshots are a frame latency (120 ms) apart: {ts}")
    base = ts[0]
    offsets = sorted({0, 1, ts[0] - 1, ts[0], ts[0] + 1} | {t + dd for t in ts for dd in (-1, 0, 1)} | {ts[-1] + 200, ts[-1] + 3_000})
    offsets = [o for o in offsets if o >= 0]
    for reg in (230, 244, 247):
        i = word_index(reg)
        block230 = reg in (230, 232)
        reads_of = (0, 2) if block230 else (1, 3)       # indexes of the two reads that carry this register
        for off in offsets:
            label = f"register {reg} changes {off} ms after the call"
            ex.row(label)
            d = ready(mk, mode=("deferred", 120))
            t0 = d.sim.now_ms
            old = d.words[i]
            new = (old + 1) & 0xFFFF
            d.bank_at(off, {reg: new})
            st = d.save()
            snaps = _read_times(d, t0)
            seen = [off <= snaps[j] for j in reads_of]     # an injected change at the same ms is applied before the frame goes on the wire
            outcome = committed_words_ok(ex, d, D.GWORDS, label)
            if seen[0] and seen[1]:
                ex.eq(d.b9, t_since_review(reg, old, new), f"{label}: both passes saw the change -> changed since Review")
                ex.eq(outcome, "refused", f"{label}: refused")
            elif seen[1] and not seen[0]:
                ex.eq(d.b9, t_during_read(reg, old, new), f"{label}: only pass 2 saw it -> changed during the read")
                ex.eq(outcome, "refused", f"{label}: refused")
            elif seen[0] and not seen[1]:
                # pass 1 saw it, pass 2 did not (it changed back? cannot be: a register that changed stays changed) -> impossible
                ex.ok(False, f"{label}: impossible observation order {seen}")
            else:
                ex.eq(d.b9, t_saved(1), f"{label}: no pass saw the change: the reviewed bytes are committed")
                ex.eq(outcome, "saved", f"{label}: saved")
            ex.eq(st.violations_fb(("FBW", "FBP") if outcome == "saved" else ()), [], f"{label}: audit")
            ex.eq(nothing_held(d), [], f"{label}: released")


# ---------------------------------------------------------------------------
# the candidate / call arguments clobbered while the dispatch runs
# ---------------------------------------------------------------------------
CLOBBER = [
    ("cand_words all +1", lambda d: d.set_g("fallback_profile_cand_words", [(w + 1) & 0xFFFF for w in d.arr("fallback_profile_cand_words")])),
    ("cand_words zeroed", lambda d: d.set_g("fallback_profile_cand_words", [0] * 31)),
    ("cand_id other", lambda d: d.set_g("fallback_profile_cand_id", 0x0123456789ABCDEF)),
    ("cand_valid forced true again", lambda d: d.set_g("fallback_profile_cand_valid", True)),
    ("cand_saveable forced true", lambda d: d.set_g("fallback_profile_cand_saveable", True)),
    ("cand_prior_class CORRUPT", lambda d: d.set_g("fallback_profile_cand_prior_class", 2)),
    ("cand_prior_gen 99", lambda d: d.set_g("fallback_profile_cand_prior_gen", 99)),
    ("cand_prior_binding other", lambda d: d.set_g("fallback_profile_cand_prior_binding", 0xDEADBEEF)),
    ("cand_ms moved", lambda d: d.set_g("fallback_profile_cand_ms", 5)),
    ("cand_writes_fp moved", lambda d: d.set_g("fallback_profile_cand_writes_fp", 12345)),
    ("exec_action other", lambda d: d.set_g("fallback_profile_exec_action", "RESTORE")),
    ("exec_target_id other", lambda d: d.set_g("fallback_profile_exec_target_id", "0000000000000000")),
    ("exec_confirmation other", lambda d: d.set_g("fallback_profile_exec_confirmation", "nope")),
    ("exec_hb_ok false (the heartbeat snapshot)", lambda d: d.set_g("fallback_profile_exec_hb_ok", False)),
    ("arm_on_ms zero", lambda d: d.set_g("fallback_profile_arm_on_ms", 0)),
]


def _all_clobbers(d):
    for _n, fn in CLOBBER:
        fn(d)


@scenario("rc_clobbered_candidate_and_call", "the candidate globals / the call's argument copies clobbered mid-dispatch: the REVIEWED bytes are committed (the gate's copies are used)")
def rc_clobbered_candidate_and_call(mk, ex: Exp):
    rows = list(CLOBBER) + [("EVERYTHING above at once", _all_clobbers)]
    for name, fn in rows:
        for at in (1, 4):
            label = f"{name} after reply {at}"
            ex.row(label)
            d = ready(mk, mode=("deferred", 120))
            d.when(nth_deliver(at), lambda sim, fn=fn, d=d: fn(d))
            d.arm_on()
            st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
            check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=label, reboot=False,
                        consumed=not any(k in name for k in ("cand_valid", "cand_saveable", "EVERYTHING")))


@scenario("rc_context_integrity", "the SAVE context invalid / purpose changed / ids zeroed mid-dispatch: an integrity refusal or no write at all")
def rc_context_integrity(mk, ex: Exp):
    for label, fn in (("ctx_valid cleared", lambda d: d.set_g("fallback_profile_save_ctx_valid", False)),
                      ("ctx_id zeroed", lambda d: d.set_g("fallback_profile_save_ctx_id", 0))):
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(2), lambda sim, fn=fn, d=d: fn(d))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, TXT["internal_ctx"], reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
    ex.row("ctx words zeroed: pass 2 no longer equals them -> changed since Review, nothing written")
    d = ready(mk, mode=("deferred", 120))
    d.when(nth_deliver(2), lambda sim: d.set_g("fallback_profile_save_ctx_words", [0] * 31))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    ex.starts(d.b9, SAVE_PFX + "live configuration changed since Review (register 244: reviewed 0, now 2)", "pass2 != ctx words")
    ex.eq(st.violations_fb((), reads=READS4), [], "nothing written")
    ex.row("purpose switched to REVIEW mid-dispatch (T-CAP-24): no SAVE_FINAL write, no durable write of any kind")
    d = ready(mk, mode=("deferred", 120))
    d.when(nth_deliver(2), lambda sim: d.set_g("fallback_profile_op_purpose", 1))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    ex.eq(st.violations_fb((), reads=READS4), [], "zero NVS writes, zero Modbus writes")
    ex.eq(nothing_held(d), [], "released")
    ex.eq(d.stored("FBP"), None, "nothing stored")


# ---------------------------------------------------------------------------
# a temporary operation appearing during the dispatch
# ---------------------------------------------------------------------------
MID_LEASES = [("fp_active", "fp", "active"), ("fp_restore_required", "fp", "rr"), ("fp_pending_clear", "fp", "pc"),
              ("fp_operator_needed", "fp", "on"), ("fp_metadata_corrupt", "fp", "mc"), ("dump_active", "dump", "active"),
              ("dump_restore_required", "dump", "rr"), ("dump_operator_needed", "dump", "on"), ("r244_operator_needed", "r244", "on"),
              ("r244_pending_clear", "r244", "pc"), ("r244_metadata_corrupt", "r244", "mc")]


@scenario("rc_temporary_operation_mid_dispatch", "a Free Power / Dump / R244 lease, a write arm, an FBS record, a bus owner appearing during the dispatch: refused, nothing written")
def rc_temporary_operation_mid_dispatch(mk, ex: Exp):
    for name, dom, kind in MID_LEASES:
        for at in (1, 4):
            label = f"{name} appears after reply {at}"
            ex.row(label)
            d = ready(mk, mode=("deferred", 120))
            d.when(nth_deliver(at), lambda sim, n=name, d=d: d.lease(n))
            d.arm_on()
            st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
            check_refusal(ex, d, st, t_slot(kind, dom), reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
            # FB-B2 (final review F5 / N14): the vector of the FINAL re-check is what B3 shows after the refusal
            ex.has(d.b3_field("obl"), D.LEASE_RAM[name][1], f"{label}: B3 obl= carries the refusing slot ({D.LEASE_RAM[name][1]})")
    for at in (1, 4):
        label = f"a write arm turned on after reply {at}"
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(at), lambda sim, d=d: d.write_arm("free_power_write_enable", True))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, TXT["G12"], reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
        label = f"an FBS episode record appears after reply {at}"
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(at), lambda sim, d=d: d.set_g("fallback_profile_fbs_slot", 3))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, TXT["G15_episode"], reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
    for flag, owner in (("correction_in_progress", "clock correction"), ("free_power_operation_in_progress", "Free Power"),
                        ("reg244_apply_in_progress", "Register 244 test"), ("dump_operation_in_progress", "Dump to Grid"),
                        ("verification_pending", "clock verification"), ("verification_read_active", "clock verification"),
                        ("free_power_recovery_force_in_progress", "Free Power")):
        label = f"{flag} set during the dispatch"
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(2), lambda sim, f=flag, d=d: d.set_g(f, True))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, t_bus(owner), reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
        ex.has(d.b3_field("obl"), "BUS:BY", f"{label}: B3 obl= shows the BUS slot busy (the vector of the FINAL re-check)")
    ex.row("the write mutex taken away (cleared) during the dispatch: not quiet at commit, after the fresh read, nothing written")
    d = ready(mk, mode=("deferred", 120))
    d.when(nth_deliver(2), lambda sim: d.set_g("manual_write_in_progress", False))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_refusal(ex, d, st, TXT["bus_quiet"], reads=READS4, nvs_ops=None, label="mutex cleared", snap=None, accepted=True)
    ex.eq(d.g["manual_write_in_progress"], False, "mutex released")
    ex.row("an RTC correction started right after the last reply: refused by the part-1 obligation vector (BUS slot), not by the commit's own "
           "correction term - that one is a defence in depth behind it which no yield can reach (the two final lambdas run back to back)")
    d = ready(mk, mode=("deferred", 120))
    d.when(nth_deliver(4), lambda sim: d.set_g("correction_in_progress", True))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_refusal(ex, d, st, t_bus("clock correction"), reads=READS4, nvs_ops=0, label="correction at R4", snap=None, accepted=True)
    ex.has(d.b3_field("obl"), "BUS:BY", "correction at R4: B3 obl= shows the BUS slot busy (refused by the part-1 vector)")
    ex.row("the writes counter moving mid-dispatch is NOT a refusal by itself (G13 is a UX gate; pass2 == candidate is the safety gate)")
    d = ready(mk, mode=("deferred", 120))
    d.when(nth_deliver(2), lambda sim: d.set_g("manual_write_attempts", d.g["manual_write_attempts"] + 1))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="counter bump mid-dispatch", reboot=False)


@scenario("rc_obligation_lazy_probe_ordering", "the lease marker probes of the final lambda only happen after the RAM legs and only once; a RAM refusal reads no marker")
def rc_obligation_lazy_probe_ordering(mk, ex: Exp):
    ex.row("a Dump lease appearing mid-dispatch with an FP ghost marker: refused by the RAM leg, zero storage operations")
    d = ready(mk, mode=("deferred", 120))
    d.sim.seed_marker(D.MARKER_TAGS["fp"], 1, legacy=False)
    d.when(nth_deliver(1), lambda sim: d.lease("dump_active"))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_refusal(ex, d, st, t_slot("active", "dump"), reads=READS4, nvs_ops=0, label="RAM leg first", snap=None, accepted=True)
    ex.eq(d.g["fallback_profile_probe_latch"], 0, "no latch: the ghost marker was never probed")


# ---------------------------------------------------------------------------
# the heartbeat snapshot, the clock
# ---------------------------------------------------------------------------
def _first_nvs_stats(ev):
    """Event predicate: the first direct-NVS get_stats after the hook is installed. In SAVE_FINAL part 2 that is the health check that
    ends the FRESH prior read, i.e. the last storage event before the commit-time heartbeat re-check (the commit's own stats come later)."""
    return ev[0] == "nvs" and ev[1] == "stats"


@scenario("rc_heartbeat_rechecked_before_commit", "FB-B2 hardening: the heartbeat is positively RE-CHECKED immediately before the durable commit - stable throughout: SAVED; lost during the reread, or lost / unknown right before the commit: refused, nothing written, no latch, no retry")
def rc_heartbeat_rechecked_before_commit(mk, ex: Exp):
    ex.row("stable at execute and throughout the whole dispatch: SAVED (control)")
    d = ready(mk, mode=("deferred", 120))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="stable throughout", reboot=False)

    for n in (1, 2, 3, 4):
        label = f"stable at execute, LOST during the reread (after reply {n})"
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(n), lambda sim, d=d: d.supervise(False))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, TXT["G10"], reads=READS4, nvs_ops=None, label=label, snap=None, accepted=True)
        ex.eq(d.nvs_set_history(), [], f"{label}: no durable write at all")
        ex.eq(d.stored("FBP"), None, f"{label}: no profile stored")
        ex.eq(d.stored("FBW"), None, f"{label}: no witness stored")

    ex.row("LOST immediately after the call, before the first read")
    d = ready(mk, mode=("deferred", 120))
    d.arm_on()
    d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)
    d.supervise(False)
    d.idle()
    ex.eq(d.b9, TXT["G10"], "refused for the heartbeat once the dispatch reaches the commit")
    ex.eq(d.nvs_set_history(), [], "nothing written")

    cases = (
        ("LOST (state 3) with the Stable flag still set, right before the commit", dict(ok=True, state=3, stable=True)),
        ("SUSPECT (state 2) with the Stable flag still set, right before the commit", dict(ok=True, state=2, stable=True)),
        ("SUPERVISED but the Stable flag cleared, right before the commit", dict(ok=True, state=1, stable=False)),
        ("STARTUP (state 0), right before the commit", dict(ok=False)),
        ("UNKNOWN state value 255 with the Stable flag set, right before the commit", dict(ok=True, state=255, stable=True)),
        ("UNKNOWN: state and flag both cleared, right before the commit", dict(ok=False, state=255, stable=False)),
    )
    for label, kw in cases:
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        fired = []
        d.when(_first_nvs_stats, lambda sim, d=d, kw=kw, fired=fired: (fired.append(1), d.supervise(**kw)))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        ex.eq(len(fired), 1, f"{label}: the world changed at the fresh-read health check (the last storage event before the commit)")
        check_refusal(ex, d, st, TXT["G10"], reads=READS4, nvs_ops=None, label=label, snap=None, accepted=True)
        ex.eq(d.nvs_set_history(), [], f"{label}: the durable transition was NOT started (no witness write, no profile write)")
        ex.eq(d.stored("FBW"), None, f"{label}: no witness")
        ex.eq(d.stored("FBP"), None, f"{label}: no profile")
        ex.eq(d.g["fallback_profile_save_unconfirmed"], False, f"{label}: a refusal before the writer is not an UNKNOWN outcome (no overlay)")
        ex.eq(d.g["fallback_durable_last_err"], 0, f"{label}: no storage error recorded")
        ex.eq(d.b1, "NOT_CAPTURED", f"{label}: B1 unchanged")
        # no silent retry: the heartbeat recovering afterwards does not resurrect the refused save.
        d.supervise(True)
        d.advance(30_000)
        ex.eq(d.nvs_set_history(), [], f"{label}: no retry after the heartbeat recovers")
        ex.eq(d.b9, TXT["G10"], f"{label}: B9 unchanged by the recovery")

    ex.row("a refusal stays a refusal at the gate (execute-time check unchanged)")
    d = ready(mk)
    d.supervise(False)
    d.save()
    ex.eq(d.b9, TXT["G10"], "refused for the heartbeat at the gate")


@scenario("rc_clock_lost_before_commit", "the clock lost / epoch zero before the commit: refused, nothing written, captured_epoch never 0")
def rc_clock_lost_before_commit(mk, ex: Exp):
    for label, fn in (("ntp_synced false", lambda d: d.g.__setitem__("ntp_synced", False)),
                      ("clock invalid", lambda d: setattr(d.sim, "ntp_valid", False)),
                      ("both lost (untrusted_time)", lambda d: d.untrusted_time()),
                      ("valid and synced but the epoch is 0", lambda d: setattr(d.sim, "epoch", 0))):
        for n in (1, 4):
            lab = f"{label} after reply {n}"
            ex.row(lab)
            d = ready(mk, mode=("deferred", 120))
            d.when(nth_deliver(n), lambda sim, fn=fn, d=d: fn(d))
            d.arm_on()
            st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
            check_refusal(ex, d, st, TXT["G11"], reads=READS4, nvs_ops=None, label=lab, snap=None, accepted=True)
            ex.eq(d.stored("FBP"), None, f"{lab}: no profile with a 0 / untrusted epoch")
    ex.row("every committed profile in this suite carries a non-zero captured_epoch (control)")
    d = ready(mk)
    st = d.save()
    ex.ok(d.stored("FBP")["captured_epoch"] != 0, "captured_epoch != 0")


# ---------------------------------------------------------------------------
# the stored profile changed behind the SAVE
# ---------------------------------------------------------------------------
G7_ = D.GOLD
STORED_CHANGES = [
    ("NOT_CAPTURED -> VALID g3 written by someone else", "none",
     lambda d: (d.put("FBP", D.gold_profile(generation=3)), d.put("FBW", D.prov_bytes(3, D.gold_profile(generation=3)["binding"], 2)))),
    ("VALID g7 -> VALID g9", "valid",
     lambda d: (d.put("FBP", D.gold_profile(generation=9)), d.put("FBW", D.prov_bytes(9, D.gold_profile(generation=9)["binding"], 8)))),
    ("VALID g7 -> same generation, other payload (binding differs)", "valid",
     lambda d: (d.put("FBP", D.gold_profile(generation=7, reg245=7777)),
                d.put("FBW", D.prov_bytes(7, D.gold_profile(generation=7, reg245=7777)["binding"], 6)))),
    ("VALID g7 -> FBP erased (PROFILE_LOST)", "valid", lambda d: d.erase("FBP")),
    ("VALID g7 -> FBP replaced by corrupt bytes", "valid", lambda d: d.put("FBP", bytes(range(96)))),
    ("VALID g7 -> witness lagging (hw 6)", "valid", lambda d: d.put("FBW", D.prov_bytes(6, 0x1111, 5))),
    ("VALID g7 -> witness erased", "valid", lambda d: d.erase("FBW")),
    ("VALID g7 -> witness corrupt", "valid", lambda d: d.put("FBW", bytes(range(48)))),
    ("VALID g7 -> INVALIDATED g8", "valid",
     lambda d: (d.put("FBP", fp.invalidate_profile(G7_)), d.put("FBW", D.prov_bytes(8, fp.invalidate_profile(G7_)["binding"], 7, fd.PROV_OP_INVALIDATE)))),
    ("NOT_CAPTURED -> corrupt FBP", "none", lambda d: d.put("FBP", bytes(range(96)))),
    ("NOT_CAPTURED -> witness only (PROFILE_LOST)", "none", lambda d: d.put("FBW", D.prov_bytes(5, 0x2222, 4))),
]


@scenario("rc_stored_profile_changed", "the stored profile changed between Review and SAVE: 'stored profile changed since Review', nothing written, the mirror follows the fresh read, a reboot resolves")
def rc_stored_profile_changed(mk, ex: Exp):
    for label, seed, mod in STORED_CHANGES:
        ex.row(label)
        d = ready(mk, seed=seed)
        mod(d)
        st = d.save()
        check_refusal(ex, d, st, TXT["prior_changed"], reads=READS4, nvs_ops=None, label=label, snap=None, accepted=True)
        ex.eq(d.b1, "UNREADABLE", f"{label}: B1 shows the fresh read (the same-boot divergence is a read anomaly)")
        ex.eq(d.cls, "UNREADABLE", f"{label}: the class mirror global follows the fresh read (the latest authoritative read wins)")
        ex.ok(d.g["fallback_profile_read_anomaly"] != 0, f"{label}: anomaly latched for the boot")
        d.review()
        ex.eq(d.b3_field("st"), "CANDIDATE_NOT_SAVEABLE", f"{label}: the next Review is not saveable")
        want_cls = d.model_class()
        d.reboot()
        ex.eq(d.b1, want_cls[0], f"{label}: after a reboot B1 is the class the NVS image composes to ({want_cls[0]})")
        ex.eq(d.g["fallback_profile_read_anomaly"], 0, f"{label}: the anomaly is per boot")
    ex.row("after an external VALID g9 and a reboot, Review + SAVE writes g10 (no generation is ever reused)")
    d = ready(mk, seed="valid")
    d.put("FBP", D.gold_profile(generation=9))
    d.put("FBW", D.prov_bytes(9, D.gold_profile(generation=9)["binding"], 8))
    d.save()
    d.reboot()
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=10, prior_gen=9, prior_binding=D.gold_profile(generation=9)["binding"], label="g10 after the external g9", reboot=False)


# ---------------------------------------------------------------------------
# the arm: one-shot, Review, lifetime
# ---------------------------------------------------------------------------
@scenario("os_arm_review", "a Review press turns the arm off (also when it is refused later); an arm turned on during READING is cancelled at publication")
def os_arm_review(mk, ex: Exp):
    ex.row("arm on, Review pressed: off at the gate")
    d = ready(mk)
    d.arm_on()
    ex.eq(d.arm_state, True, "arm on")
    d.review(expect="CANDIDATE_READY")
    ex.eq(d.arm_state, False, "the Review turned it off")
    ex.row("arm on during a deferred Review's READING: turned off when the Review starts and cancelled again at publication")
    d = mk(seed="none", mode=("deferred", 120))
    d.arm_on()
    d.press_review(idle=False)
    ex.eq(d.arm_state, False, "turned off by the press (past V1)")
    d.advance(100)
    d.arm_on()
    ex.eq(d.arm_state, True, "the operator turned it on while READING")
    d.idle()
    ex.eq(d.b3_field("st"), "CANDIDATE_READY", "the Review published a candidate")
    ex.eq(d.arm_state, False, "the arm turned on during READING was cancelled at publication")
    snap = d.snapshot()
    st = d.save(arm=False)
    check_refusal(ex, d, st, TXT["G2"], label="SAVE with the cancelled arm", snap=snap)
    ex.row("arm on, Review refused at a later gate (a lease is active): the arm is still turned off (preamble)")
    d = mk(seed="none")
    d.lease("fp_active")
    d.arm_on()
    d.review()
    ex.starts(d.b9, "REVIEW REFUSED - ", "the Review was refused")
    ex.eq(d.arm_state, False, "turned off")
    ex.row("a Review refused at V1 (operation in flight) leaves the arm alone (the turn-off comes after V1)")
    d = ready(mk, mode=("deferred", 120))
    d.arm_on()
    d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)
    d.arm_on()
    d.press_review(idle=False)
    ex.starts(d.b9, "REVIEW REFUSED - ", "refused at V1")
    ex.eq(d.arm_state, True, "the arm turned on during the SAVING is untouched")
    d.arm_off()
    d.idle()
    ex.eq(d.b9, t_saved(1), "the SAVE committed")


FIRMWARE_ARM_USES = re.compile(r"fallback_profile_arm\b[^\n]*")


NL = chr(10)


@scenario("os_arm_never_on_by_firmware", "the arm cannot be turned on by firmware: no turn_on / toggle / publish / control in any FB code (grep) and every ON in a long mixed run is an operator's")
def os_arm_never_on_by_firmware(mk, ex: Exp):
    ex.row("grep over the whole firmware YAML")
    text = live_text()
    members = {}
    bare = []
    for m in re.finditer(r"(?<![\w])(id\()?fallback_profile_arm(?!_on_ms)\)?(\.(\w+))?", text):
        if m.group(3):
            members[m.group(3)] = members.get(m.group(3), 0) + 1
        else:
            line = text[text.rfind(NL, 0, m.start()) + 1: text.find(NL, m.end())].strip()
            bare.append(line)
    ex.eq(sorted(members), ["state", "turn_off"], "the only members the firmware ever uses on the arm: state (read) and turn_off()")
    ex.eq(bare, ["id: fallback_profile_arm"], "the only other mention is the switch declaration")
    ex.eq(len(re.findall(r"fallback_profile_arm\)\s*\.\s*(turn_on|toggle|publish_state|control|write_state)", text)), 0,
          "no turn_on / toggle / publish_state / control / write_state on the arm")
    ex.eq(len(re.findall(r"fallback_profile_arm[^\n]*(switch\.turn_on|switch\.toggle|turn_on:)", text)), 0, "no switch.turn_on / toggle action names the arm")
    ex.ok("switch.turn_on" not in "".join(ln for ln in text.splitlines() if "fallback_profile_arm" in ln), "no switch.turn_on line mentions the arm")
    n_off = len(re.findall(r"id\(fallback_profile_arm\)\.turn_off\(\);", text))
    ex.ok(n_off >= 6, f"the firmware only ever calls turn_off() ({n_off} sites)")
    ex.row("behavioural: a long mixed run - every arm ON event is directly preceded by the operator's switch call")
    d = mk(seed="valid", mode=("deferred", 120))
    for rnd in range(4):
        d.review(expect="CANDIDATE_READY")
        d.advance(25_000)
        d.arm_on()
        d.execute("SAVE", d.b4, "SAVE " + d.b4)                       # accepted
        d.review()
        d.execute("SAVE", d.b4, "SAVE nope")                           # refused (no operator arm: not turned on)
        d.arm_on()
        d.execute("RESTORE", "x", "y")
        d.advance(130_000)                                              # ticks, the TTL
        d.press_review()
        d.advance(10_000)
    ev1 = list(d.sim.events)
    d.reboot()
    d.advance(300_000)
    ex.eq(d.arm_state, False, "after the reboot and 300 s of ticks the arm is off")
    for tag, ev in (("before the reboot", ev1), ("after the reboot", list(d.sim.events))):
        on_writes = [i for i, e in enumerate(ev) if e[0] == "switch" and e[1] == "fallback_profile_arm" and e[2] == "write" and e[3] is True]
        operator_on = [e for e in ev if e[:4] == ("api", "switch", "fallback_profile_arm", True)]
        ok_prev = [i > 0 and ev[i - 1][:4] == ("api", "switch", "fallback_profile_arm", True) for i in on_writes]
        ex.ok(all(ok_prev) and len(on_writes) == len(operator_on),
              f"{tag}: {len(on_writes)} arm ON writes == {len(operator_on)} operator calls, each directly preceded by its call")
        if tag == "before the reboot":
            ex.ok(len(on_writes) >= 8, f"the mixed run exercised the arm {len(on_writes)} times")


@scenario("os_candidate_copy_before_ie2", "the candidate is copied to lambda locals BEFORE IE2 consumes it (text order) and the copy is what the gate and the context use")
def os_candidate_copy_before_ie2(mk, ex: Exp):
    ex.row("text order inside the SAVE gate script")
    import _fbb2_gates_lib as L
    a, b = L.script_span(live_text(), "fallback_profile_save")
    body = live_text()[a:b]
    copy_pos = [body.find(x) for x in ("const bool c_valid = id(fallback_profile_cand_valid);", "const uint64_t c_id = id(fallback_profile_cand_id);",
                                      "const std::array<uint16_t, 31> c_words = id(fallback_profile_cand_words);")]
    ie2 = body.find("id(fallback_profile_invalidate_candidate).execute();")
    g1 = body.find("save_in_flight_gate(")
    armed = body.find("const bool armed = id(fallback_profile_arm).state;")
    ex.ok(all(p >= 0 for p in copy_pos) and ie2 >= 0, "the copy statements and IE2 are present")
    ex.ok(g1 < armed < min(copy_pos) < ie2, "order: G1 in-flight check, then the arm read, then the candidate copy, then IE2")
    ex.eq(body.count("id(fallback_profile_invalidate_candidate).execute();"), 1, "IE2 once")
    g1_block = body[g1: body.find("}\n          // One-shot preamble")]
    ex.ok("id(fallback_profile_arm).turn_off();" in g1_block and "id(fallback_profile_cand_" not in g1_block
          and "invalidate_candidate" not in g1_block, "the G1 refusal branch only turns the arm off and publishes")
    ex.row("behavioural: the gate decides on the COPY (a consumed candidate still saves)")
    d = ready(mk)
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SAVE through the copied candidate", reboot=False)


# ---------------------------------------------------------------------------
# long holds: the housekeeping tick and the breaker
# ---------------------------------------------------------------------------
@scenario("rc_tick_during_saving", "the 10 s housekeeping ticks running while a long SAVE is in flight do not disturb it (no breaker, no candidate expiry, no arm side effect)")
def rc_tick_during_saving(mk, ex: Exp):
    ex.row("SAVE accepted just before a tick, the bus busy 6 s (two ticks fire while SAVING)")
    d = ready(mk, mode=("deferred", 120))
    next_tick = list(d.sim._intervals.values())[0].next
    d.advance(next_tick - d.sim.now_ms - 50)
    d.hold_bus(6_000)
    t0 = d.sim.now_ms
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    ticks = [t for t, idx in d.sim.interval_log if t > t0]
    ex.ok(len(ticks) >= 1, f"{len(ticks)} housekeeping tick(s) fired while the SAVE was in flight")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="SAVE across ticks", reboot=False,
                b9_seq=[TXT["progress"], t_saved(1)])
    ex.row("a leaked SAVE (no dispatch running, op flag + purpose + context set): the breaker clears ONLY the FB state, never the mutex")
    d = mk(seed="none")
    d.run("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_purpose) = 2; id(fallback_profile_op_started_ms) = millis(); "
          "id(manual_write_in_progress) = true; id(fallback_profile_save_ctx_valid) = true; id(fallback_profile_save_ctx_id) = 77; "
          "id(fallback_profile_capture_state) = 4;")
    d.advance(25_000)
    ex.eq(d.g["fallback_profile_op_in_progress"], True, "not yet reset at 25 s (breaker is 30 s)")
    d.advance(15_000)
    g = d.g
    ex.eq((g["fallback_profile_op_in_progress"], g["fallback_profile_op_purpose"], g["fallback_profile_save_ctx_valid"],
           g["fallback_profile_save_ctx_id"], g["fallback_profile_step"]), (False, 0, False, 0, 0), "the breaker cleared the operation state and the context")
    ex.eq(g["manual_write_in_progress"], True, "the shared write mutex is NOT assigned by the breaker")
    ex.starts(d.b9, "INTERNAL - Fallback Profile operation state reset by watchdog; write lock ", "B9 breaker text")
    ex.has(d.b9, "still held", "B9 says the lock is still held")
    d2 = mk(seed="none")
    d2.run("id(fallback_profile_op_in_progress) = true; id(fallback_profile_op_purpose) = 2; id(fallback_profile_op_started_ms) = millis(); "
           "id(fallback_profile_save_ctx_valid) = true; id(fallback_profile_save_ctx_id) = 77;")
    d2.advance(40_000)
    ex.eq((d2.g["fallback_profile_op_in_progress"], d2.g["fallback_profile_save_ctx_valid"], d2.g["manual_write_in_progress"]), (False, False, False),
          "free mutex case: cleared, mutex stays free")
    ex.has(d2.b9, "free", "B9 says the lock is free")
    ex.row("worst-case hold: bus busy 6.9 s, four 2.9 s frames, bus busy 2.9 s after the last reply = ~21 s, inside the locked ~24 s bound, no breaker")
    d = ready(mk, mode=("deferred", 2_900))
    d.hold_bus(6_900)
    pred, fn = (lambda ev, n=[0]: (ev[0] == "deliver" and ev[1] == "fw" and (n.__setitem__(0, n[0] + 1) or n[0] == 4)),
                lambda sim: sim.hold_bus(2_900))
    d.when(pred, fn)
    t0 = d.sim.now_ms
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    held = d.sim.now_ms - t0
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="worst-case SAVE", reboot=False)
    ex.ok(18_000 <= held < 24_000, f"the SAVE held the write mutex for {held} ms (< the locked ~24 s bound, < the 30 s breaker)")
    ex.row("a genuine long SAVE (bus busy 6.9 s + reads) never trips the breaker")
    d = ready(mk, mode=("deferred", 120))
    d.hold_bus(6_900)
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    ex.eq(d.b9, t_saved(1), "SAVED, not a watchdog reset")


# ---------------------------------------------------------------------------
# immediate bus: a word changing between the individual reads
# ---------------------------------------------------------------------------
@scenario("rc_immediate_change_between_reads", "immediate bus: a word changing before each of the four reads (and after the last one): the right text, or the reviewed bytes committed")
def rc_immediate_change_between_reads(mk, ex: Exp):
    for reg in (230, 232, 244, 256, 279, 247):
        i = word_index(reg)
        reads_of = (1, 3) if reg in (230, 232) else (2, 4)         # 1-based indexes of the two reads that carry this register
        for k in (1, 2, 3, 4, 5):
            label = f"register {reg} changes {'before read ' + str(k) if k <= 4 else 'after the last read (before the commit)'}"
            ex.row(label)
            d = ready(mk)
            old = d.words[i]
            new = (old + 1) & 0xFFFF
            if k <= 4:
                d.change_word_before_read(k, i, new)
            else:
                cnt = [0]

                def pred(ev, cnt=cnt):
                    if ev[0] == "read":
                        cnt[0] += 1
                        return cnt[0] == 4
                    return False
                d.when(pred, lambda sim, reg=reg, new=new: sim.bank.__setitem__(reg, new))
            st = d.save()
            seen = [k <= j for j in reads_of]                         # read j (1-based) takes its snapshot after the change iff j >= k
            outcome = committed_words_ok(ex, d, D.GWORDS, label)
            if seen[0] and seen[1]:
                ex.eq(d.b9, t_since_review(reg, old, new), f"{label}: both passes saw it -> changed since Review")
                ex.eq(outcome, "refused", f"{label}: nothing written")
            elif seen[1]:
                ex.eq(d.b9, t_during_read(reg, old, new), f"{label}: only pass 2 saw it -> changed during the read")
                ex.eq(outcome, "refused", f"{label}: nothing written")
            else:
                ex.eq(d.b9, t_saved(1), f"{label}: no read saw it -> the REVIEWED bytes are committed")
                ex.eq(outcome, "saved", f"{label}: saved")
            ex.eq(st.violations_fb(("FBW", "FBP") if outcome == "saved" else ()), [], f"{label}: audit")


@scenario("rc_marker_appears_mid_dispatch", "a ghost / unreadable lease marker appearing in storage during the dispatch is found by the final lambda's probe: refused, latched, nothing written")
def rc_marker_appears_mid_dispatch(mk, ex: Exp):
    import _fbb2_gates_refusals2 as R2
    for dom, (short, shift) in R2.DOMS.items():
        for name, spec, code, kind in R2.PROBE_CASES[:3] + R2.PROBE_CASES[5:6]:
            label = f"{dom}: {name} appears after reply 2"
            ex.row(label)
            d = ready(mk, mode=("deferred", 120))
            d.when(nth_deliver(2), lambda sim, dom=dom, spec=spec, d=d: R2._seed_probe(d, dom, spec))
            d.arm_on()
            st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
            check_refusal(ex, d, st, t_slot(kind, dom), reads=READS4, nvs_ops=None, label=label, snap=None, accepted=True)
            ex.eq(d.g["fallback_profile_probe_latch"], code << shift, f"{label}: latched")
            ex.eq(d.stored("FBP"), None, f"{label}: nothing stored")


# ---------------------------------------------------------------------------
# no stale state after a refusal: the next Review + SAVE works
# ---------------------------------------------------------------------------
@scenario("rc_recovery_after_refusal", "after every kind of refusal inside the dispatch a fresh Review + SAVE commits (no stale read / step / context state)")
def rc_recovery_after_refusal(mk, ex: Exp):
    import _fbb2_gates_refusals2 as R2

    def run(label, setup, expect_text, **kw):
        ex.row(label)
        d = ready(mk, **kw)
        undo = setup(d)
        st = d.save()
        ex.eq(d.b9, expect_text, f"{label}: the refusal")
        ex.eq(st.violations_fb((), reads=None), [], f"{label}: nothing written")
        if callable(undo):
            undo(d)
        d.review(expect="CANDIDATE_READY")
        st2 = d.save()
        check_saved(ex, d, st2, gen=1, prior_gen=0, prior_binding=0, label=f"{label}: the retry", reboot=False)
        return d

    for k in (1, 2, 3, 4):
        for name, spec in (("no_response", "no_response"), ("exception", {"outcome": "error", "exception_code": 2}), ("short", {"outcome": "ok", "values": [1]}),
                           ("bounded", "timeout")):
            kind = "exception" if name == "exception" else name
            run(f"read {k} {name}", lambda d, k=k, spec=spec: d.sim.queue_frames(*(["ok"] * (k - 1) + [spec])), t_read(kind, R2.BLK[k - 1]))
    run("hub busy 7.5 s", lambda d: d.hold_bus(7_500), TXT["idle7"])
    run("a word changed since Review (then restored)", lambda d: (d.poke(245, 1234), lambda d2: d2.poke(245, D.GWORDS[word_index(245)]))[1], t_since_review(245, 8000, 1234))
    run("clock lost then regained", lambda d: (d.untrusted_time(), lambda d2: d2.set_time(ntp=True))[1], TXT["G11"])
    run("heartbeat lost then regained", lambda d: (d.supervise(False), lambda d2: d2.supervise(True))[1], TXT["G10"])
    run("a write arm on, then off", lambda d: (d.write_arm("dump_write_enable", True), lambda d2: d2.write_arm("dump_write_enable", False))[1], TXT["G12"])
    run("the mutex held, then released", lambda d: (d.mutex(True), lambda d2: d2.mutex(False))[1], t_bus("manual write"))
    run("a lease active, then cleared", lambda d: (d.lease("fp_active"), lambda d2: d2.run("id(free_power_snapshot_valid) = false; id(free_power_marker_state) = 0; id(free_power_active_persisted) = false;"))[1],
        t_slot("active", "fp"))
    ex.row("after a refused commit (storage unhealthy at the commit) the writer is not latched: the retry commits")
    d = ready(mk)
    cnt = [0]

    def hook(op, key):
        if op == "stats":
            cnt[0] += 1
            if cnt[0] == 2:
                d.sim.nvs_direct.healthy = False
    d.sim.nvs_direct.before_op = hook
    d.save()
    ex.eq(d.b9, TXT["storage_unhealthy"], "refused at the commit")
    d.sim.nvs_direct.before_op = None
    d.sim.nvs_direct.healthy = True
    d.review(expect="CANDIDATE_READY")
    st = d.save()
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="retry after a refused commit", reboot=False)


# ---------------------------------------------------------------------------
# a differential test against an independent operator-state oracle
# ---------------------------------------------------------------------------
class OperatorOracle:
    """The locked operator-visible rules of the SAVE flow as a tiny independent state machine (no firmware code): a Review creates the
    candidate (id / words / birth) and turns the arm off; the arm turned on by the operator lives 120 s (tick granularity is avoided by
    advancing time in whole ticks from a tick-aligned start); a candidate lives 120 s; EVERY execute call consumes the arm and the
    candidate; a SAVE is accepted iff the token, the arm, the candidate, its age, the id, the phrase, the heartbeat and the clock are all
    right, and it COMMITS iff additionally the live words still equal the reviewed ones; a commit advances the generation by one."""

    TTL = 120_000

    def __init__(self, gen):
        self.gen = gen
        self.reset_runtime()

    def reset_runtime(self):
        self.t = 0
        self.cand = None            # {"id": str, "born": ms, "words": [..]}
        self.arm_at = None
        self.hb = True
        self.ntp = True

    def advance(self, ms):
        self.t += ms
        if self.arm_at is not None and self.t - self.arm_at >= self.TTL:
            self.arm_at = None
        if self.cand is not None and self.t - self.cand["born"] >= self.TTL:
            self.cand = None

    def review(self, cid, words):
        self.arm_at = None
        self.cand = {"id": cid, "born": self.t, "words": list(words)}

    def predict(self, action, tid, phrase, live_words):
        """-> (accepted_by_gates, commits)"""
        armed = self.arm_at is not None
        ok = (action == "SAVE" and armed and self.cand is not None and self.t - self.cand["born"] < self.TTL
              and len(tid) == 16 and all(c in "0123456789ABCDEF" for c in tid) and tid == self.cand["id"]
              and phrase == f"SAVE {tid}" and self.hb and self.ntp)
        commits = ok and list(live_words) == self.cand["words"]
        return ok, commits

    def consume(self):
        self.arm_at = None
        self.cand = None


@scenario("rc_model_based_sequences", "200 random operator sequences (Review / arm / wait / heartbeat / clock / bank / SAVE with good and bad arguments / reboot) against an independent operator-state oracle")
def rc_model_based_sequences(mk, ex: Exp):
    import random
    rng = random.Random(0xFB2)
    bank_values = [8000, 7000, 7500, 6000]
    stats = {"commits": 0, "accepted_but_changed": 0, "refused": 0, "calls": 0}
    for s in range(200):
        seed = rng.choice(["none", "valid"])
        d = mk(seed=seed)
        o = OperatorOracle(0 if seed == "none" else 7)
        ex.row(f"sequence {s} (seed {seed})")
        history = []
        live = list(D.GWORDS)
        for step in range(14):
            if o.cand is not None and o.arm_at is None and rng.random() < 0.6:
                act = "arm_on"                                  # guide the walk toward the flows that can commit
            elif o.cand is not None and o.arm_at is not None and rng.random() < 0.6:
                act = rng.choice(["save_good", "save_good", "save_good", "save_bad", "bank"])
            elif (not o.hb or not o.ntp) and rng.random() < 0.5:
                act = "heal"
            else:
                act = rng.choice(["review", "review", "review", "arm_on", "wait", "wait", "hb", "ntp", "bank", "save_good", "save_bad",
                                  "reboot_rare"])
            if act == "reboot_rare" and rng.random() > 0.35:
                act = "wait"
            history.append(act)
            tag = f"seq {s} step {step} {act} (history {history[-6:]})"
            if act == "review":
                st = d.review()
                ex.eq(d.b3_field("st"), "CANDIDATE_READY", f"{tag}: the Review produced a candidate")
                o.review(d.b4, live)
            elif act == "arm_on":
                d.arm_on()
                o.arm_at = o.t
            elif act == "wait":
                adv = rng.choice([10_000, 30_000, 60_000, 110_000, 120_000, 130_000])
                d.advance(adv)
                o.advance(adv)
                ex.eq(d.arm_state, o.arm_at is not None, f"{tag}: arm state after {adv} ms")
                ex.eq(bool(d.candidate()["valid"]), o.cand is not None, f"{tag}: candidate valid after {adv} ms")
            elif act == "heal":
                o.hb = o.ntp = True
                d.supervise(True)
                d.set_time(ntp=True)
            elif act == "hb":
                o.hb = not o.hb
                d.supervise(o.hb)
            elif act == "ntp":
                o.ntp = not o.ntp
                d.set_time(ntp=o.ntp)
            elif act == "bank":
                v = rng.choice(bank_values)
                live = list(live)
                live[word_index(245)] = v
                d.set_words(live)
                # a Review that already happened keeps its own copy of the words
            elif act == "reboot_rare":
                d.reboot()
                o.reset_runtime()
                live = list(d.bank_words())
            else:
                good = act == "save_good"
                cid = o.cand["id"] if o.cand is not None else "0123456789ABCDEF"
                action, tid, phrase = "SAVE", cid, f"SAVE {cid}"
                if not good:
                    k = rng.randrange(5)
                    if k == 0:
                        action = rng.choice(["RESTORE", "save", "APPLY"])
                    elif k == 1:
                        tid = cid[:-1] + ("0" if cid[-1] != "0" else "1"); phrase = f"SAVE {tid}"
                    elif k == 2:
                        phrase = f"SAVE {cid} "
                    elif k == 3:
                        tid = cid.lower() if cid.lower() != cid else cid + "0"; phrase = f"SAVE {tid}"
                    else:
                        phrase = "SAVE " + "0" * 16
                accepted, commits = o.predict(action, tid, phrase, live)
                n0 = len(d.nvs_set_history())
                st = d.execute(action, tid, phrase)
                n1 = len(d.nvs_set_history())
                stats["calls"] += 1
                stats["commits"] += bool(commits)
                stats["accepted_but_changed"] += bool(accepted and not commits)
                stats["refused"] += not accepted
                if commits:
                    o.gen += 1
                ex.eq(n1 - n0, 2 if commits else 0, f"{tag}: durable sets (predicted commit={commits}, accepted={accepted}); B9 {d.b9[:70]!r}")
                ex.eq(d.b9.startswith("SAVED - ") , commits, f"{tag}: B9 says SAVED iff the oracle commits: {d.b9[:70]!r}")
                # a call the gate refuses reads nothing; a call the gate accepts re-reads the four register banks (once each)
                ex.eq(list(st.reads), READS4 if accepted else [], f"{tag}: Modbus reads (gate refusal reads nothing, an accepted SAVE reads exactly the four banks)")
                ex.eq(d.arm_state, False, f"{tag}: the call turned the arm off")
                ex.ok(candidate_consumed(d), f"{tag}: the call consumed the candidate")
                ex.eq(st.violations_fb(("FBW", "FBP") if commits else ()), [], f"{tag}: audit (no Modbus write, FBW then FBP only when committing)")
                ex.eq(nothing_held(d), [], f"{tag}: nothing held")
                if commits:
                    fbp = d.stored("FBP")
                    ex.eq(fbp["generation"], o.gen, f"{tag}: the committed generation is previous + 1")
                    ex.eq(list(fc.words_of(fbp)), o.cand["words"], f"{tag}: the committed words are the REVIEWED words")
                o.consume()
        ex.eq(all_driver_violations(d), [], f"seq {s}: no Modbus write, no third key over the whole sequence")
    ex.row(f"the sweep is not vacuous: {stats}")
    ex.ok(stats["commits"] >= 60 and stats["accepted_but_changed"] >= 10 and stats["refused"] >= 150,
          f"the random sequences exercised commits / changed-since-Review refusals / gate refusals: {stats}")


# ===========================================================================
# FB-B2 final review (gates-extra): F3 requirement 9 through the real YAML, F4 T-CAP-17 SAVE leg, F5 every obligation input of the
# final re-check, F7 the profile never updates itself.
# ===========================================================================
DISPATCH = "fallback_profile_capture_dispatch"
FORGED_ID = 0x1122334455667788


def _w(**by_reg) -> dict:
    """{word index: value} from {register: value} pairs written as _w(r243=5, r256=60000)."""
    return {word_index(int(k[1:])): v for k, v in by_reg.items()}


# (label, words changed (by register), the exact reason text between 'SAVE REFUSED - ' and '; profile unchanged')
L2_ROWS = [
    ("243 = 5 (not an energy-management mode)", _w(r243=5), "243=5 is not a recognised energy-management mode (0 or 1)"),
    ("244 = 0 (Allow Export)", _w(r244=0), "244=0 Allow Export - V1 can only save a Zero Export profile"),
    ("244 = 1 (Essentials)", _w(r244=1), "244=1 Essentials - unsupported in V1"),
    ("244 = 9", _w(r244=9), "244=9 unrecognised"),
    ("slot 1 power 60000 W (power too high)", _w(r256=60000), "slot 1 power 60000 W > 8000 W"),
    ("slot 3 power 499 W (below the V1 minimum)", _w(r258=499), "slot 3 power 499 W < 500 W (V1 minimum)"),
    ("slot 6 power 0 W", _w(r261=0), "slot 6 power 0 W < 500 W (V1 minimum)"),
    ("slot 2 SOC 101 % (SOC too high)", _w(r269=101), "slot 2 SOC 101 % > 100"),
    ("slot 4 source word 2 (Generator)", _w(r277=2), "slot 4 source Generator / Grid+Generator unsupported in V1"),
    ("slot 4 source word 3 (Grid + Generator)", _w(r277=3), "slot 4 source Generator / Grid+Generator unsupported in V1"),
    ("slot 1 source word 4 (mode bits: outside {0, 1})", _w(r274=4), "slot 1 mode General/Backup/Charge unsupported in V1"),
    ("slot 2 source word 0x20 (an undecoded bit: outside {0, 1})", _w(r275=0x20), "slot 2 undecoded bits 0x0020 set"),
    ("slot 1 start 65535 (not an HHMM time)", _w(r250=0xFFFF), "slot 1 start 65535 is not a valid HHMM time"),
    ("slot 4 start 2460 (minutes > 59)", _w(r253=2460), "slot 4 start 2460 is not a valid HHMM time"),
    ("three violations: the first two are named, the rest counted", _w(r256=60000, r257=100, r269=101),
     "slot 1 power 60000 W > 8000 W; slot 2 power 100 W < 500 W (V1 minimum); +1 more"),
    ("five violations", _w(r256=60000, r257=100, r269=101, r250=2400, r243=5),
     "slot 1 power 60000 W > 8000 W; slot 2 power 100 W < 500 W (V1 minimum); +3 more"),
]
# The violations the BUILT-RECORD validation ALSO catches (the profile record itself does not validate): the 244 / power / SOC / source
# rows. That validation is plan_save's PO14 pre-validation and, behind it, the FB-B0 writer's own transition validation (same text, no NVS
# operation). 243 and the HHMM start times are NOT among them: the capture-check re-run (L2) is the only guard of those registers once the
# record is built (with the L2 re-run removed those two words would be committed), so L2 is not redundant.
PO14_ROWS = [(lab, ch) for lab, ch, _t in L2_ROWS[1:12]]


def forge_candidate_and_save(d, words):
    """The inverter now holds `words` and a saveable candidate over exactly those words exists (as if a different firmware had accepted
    them at Review): the SAVE call carries its id and phrase. Only what the SAVE itself decides can refuse it."""
    d.set_words(words)
    d.set_g("fallback_profile_cand_words", list(words))
    d.set_g("fallback_profile_cand_valid", True)
    d.set_g("fallback_profile_cand_saveable", True)
    d.set_g("fallback_profile_cand_id", FORGED_ID)
    d.set_g("fallback_profile_cand_ms", d.sim.now_ms & 0xFFFFFFFF)
    return execute_call(d, {"target_id": f"{FORGED_ID:016X}"})


def _gold_with(changes: dict) -> list:
    w = list(D.GWORDS)
    for i, v in changes.items():
        w[i] = v
    return w


def _no_l2_mk(mk):
    """The firmware under test with the SAVE final lambda's capture-check re-run (part 1, step 4) removed: the only way to reach plan_save's
    PO14 pre-validation (PLAN_INTERNAL) through the real YAML. A mutant text is kept (an already removed step stays removed)."""
    from _fbb2_gates_lib import Mk, script_span
    base = mk.text if mk.text is not None else live_text()
    a, b = script_span(base, DISPATCH)
    return Mk("no-L2", text=base[:a] + base[a:b].replace("if (l2.count > 0) {", "if (false) {") + base[b:], fbsave=mk.fbsave, fbcap=mk.fbcap)


@scenario("rc_l2_defence_in_depth", "requirement 9 'all profile values still pass validation' through the real YAML: the SAVE final lambda re-runs the capture checks on the fresh words; the built record is validated again behind it (plan_save PO14, the writer's own check)")
def rc_l2_defence_in_depth(mk, ex: Exp):
    ex.row("control: a forged saveable candidate over the golden words IS saved (the forging is not what refuses the rows below)")
    d = ready(mk)
    st = forge_candidate_and_save(d, list(D.GWORDS))
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="forged candidate over valid words", reboot=False)
    for label, change, reason in L2_ROWS:
        ex.row(f"L2 re-check: {label}")
        d = ready(mk)
        st = forge_candidate_and_save(d, _gold_with(change))
        want = SAVE_PFX + reason + "; profile unchanged"
        check_refusal(ex, d, st, want, reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
        ex.eq(d.stored("FBP"), None, f"{label}: no profile stored")
        ex.eq(d.stored("FBW"), None, f"{label}: no witness stored")
        ex.eq(d.b1, "NOT_CAPTURED", f"{label}: B1 unchanged")
    ex.row("control: valid changed words (slot 1 power 7000 W, reg 245 = 7000) are still saved, exactly as forged")
    d = ready(mk)
    st = forge_candidate_and_save(d, _gold_with(_w(r245=7000, r256=7000)))
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="valid changed words", reboot=False,
                profile_fields=dict(reg245=7000, reg256_261=[7000, 500, 4000, 3000, 2000, 1000]))
    # the built-record validation (plan_save PO14, then the writer's own): reached only with the capture-check re-run out of the way
    nl2 = _no_l2_mk(mk)
    for label, change in PO14_ROWS:
        ex.row(f"built-record validation (L2 re-run removed): {label}")
        d = ready(nl2)
        st = forge_candidate_and_save(d, _gold_with(change))
        check_refusal(ex, d, st, TXT["internal_record"], reads=READS4, nvs_ops=None, label=f"PO14 {label}", snap=None, accepted=True)
        ex.eq(d.stored("FBP"), None, f"PO14 {label}: no profile stored")
        ex.eq(d.stored("FBW"), None, f"PO14 {label}: no witness stored")
        ex.eq([n for n, _b, _r in st.fb_sets], [], f"PO14 {label}: not a single durable set")


# ---------------------------------------------------------------------------
# F4: T-CAP-17, the SAVE side - a Free Power / Dump START and a Manual TOU apply arriving while the SAVE holds the shared write mutex
# (the technique of FB-B1's B-COLLIDE, test_fallback_profile_capture.py: the REAL writer scripts, positive controls)
# ---------------------------------------------------------------------------
def prime_manual_slot1(sim):
    """The entity states the REAL apply_manual_slot1 needs to be admitted (the harness models no select, so the two options are set)."""
    sim.ent("manual_config_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    for name, val in (("manual_slot1_start_hhmm", 100), ("manual_slot1_end_hhmm", 500), ("manual_slot1_power", 3000), ("manual_slot1_soc", 50)):
        sim.ent(name).set(val)
    sim.ent("manual_stage_grid_charge_enabled").set(True)
    sim.ent("manual_slot1_charge_source").current_option = lambda: D.ds.CStr("Grid")
    sim.ent("manual_slot1_mode").current_option = lambda: D.ds.CStr("General")
    sim.run_lambda("id(manual_slot1_staging_loaded) = true; id(manual_config_raw_cache_valid) = true; id(manual_cfg_reg274_raw) = 1; "
                   "id(manual_cfg_reg232_raw) = 0x11;")


def prime_free_power(sim):
    sim.ent("free_power_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.ent("free_power_duration_minutes").set(30)
    sim.ent("free_power_max_power").set(3000)
    sim.run_lambda("id(ntp_synced) = true;")


def prime_dump(sim):
    sim.ent("dump_write_enable").set(True)
    sim.ent("configuration_online").set(True)
    sim.ent("configuration_polling").set(True)
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.ent("ecco_battery_soc").set(80.0)
    sim.ent("dump_stop_soc").set(30.0)
    sim.ent("dump_export_power").set(2000.0)
    sim.ent("dump_duration_minutes").set(30)
    sim.ent("ecco_grid_ct_power").set(0.0)
    sim.run_lambda("id(ntp_synced) = true; id(dump_soc_last_update_ms) = millis(); id(cfg_block_b_seq) = 1; id(cfg_block_b_ok_ms) = millis(); "
                   "id(dump_grid_last_update_ms) = millis();")


WRITERS = (  # (script, its attempt counter, the prime function)
    ("apply_manual_slot1", "manual_write_attempts", prime_manual_slot1),
    ("start_free_power_override", "free_power_start_attempts", prime_free_power),
    ("start_dump_to_grid_override", "dump_start_attempts", prime_dump),
)


def _start_writer(sim, script):
    """Start a REAL Free Power / Dump / Manual TOU writer script in `sim`. An ADMITTED writer writes the inverter by design (it is the writer
    under test, not the SAVE): such a simulator is exempt from the suite-wide 'zero Modbus writes' counter via sim.safety_exempt; the
    simulators in which the writer must be REJECTED stay counted (and are checked row by row to have written nothing)."""
    try:
        sim.start_script(script)
    except H.FbbNotModelled:
        pass        # the harness does not model one of the writer's LATER lambdas; its accept branch (which bumps the counter) ran first
    sim.run_for(5)


@scenario("rc_collision_writers_during_save", "T-CAP-17 (SAVE side): a Free Power / Dump START and a Manual TOU apply arriving while the SAVE holds the shared write mutex are REJECTED by their own gates, nothing written, the SAVE is unaffected and commits")
def rc_collision_writers_during_save(mk, ex: Exp):
    ex.row("positive controls: with the mutex FREE the very same primed writer is admitted (so the mutex is the only reason for the rejections below)")
    for script, ctr, prime in WRITERS:
        d = ready(mk)
        d.sim.safety_exempt = True              # the admitted control writer writes the inverter (see _start_writer)
        prime(d.sim)
        _start_writer(d.sim, script)
        ex.eq(d.g[ctr], 1, f"control: {script} is admitted when nothing holds the mutex ({ctr} == 1)")

    def collide(label, writers):
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        cid = d.b4

        def body(d):
            d.arm_on()
            d.sim.call_api(d.api_name, action="SAVE", target_id=cid, confirmation=f"SAVE {cid}")
            d.advance(190)                                    # parked in R2: the SAVE owns the mutex
            g = d.g
            ex.ok(g["manual_write_in_progress"] is True and g["fallback_profile_op_in_progress"] is True and g["fallback_profile_step"] == 2
                  and g["fallback_profile_op_purpose"] == 2 and g["fallback_profile_capture_state"] == 4,
                  f"{label}: the SAVE is parked in R2 holding the shared write mutex (SAVING)")
            for _s, _c, prime in writers:
                prime(d.sim)
            m2 = d.mark()
            for script, ctr, _prime in writers:
                _start_writer(d.sim, script)
                ex.eq(d.g[ctr], 0, f"{label}: {script} arriving during the SAVE is rejected by its own gate ({ctr} untouched)")
            sc = d.since(m2)
            ex.eq([e[0] for e in sc.executed if e[0] in {w[0] for w in WRITERS}], [w[0] for w in writers],
                  f"{label}: every start was really issued (and refused)")
            ex.eq((sc.writes, sc.nvs_ops, sc.commits, sc.fb_sets), ([], [], [], []), f"{label}: the refused starts wrote nothing (no Modbus write, no NVS)")
            ex.ok(not d.g["free_power_operation_in_progress"] and not d.g["dump_operation_in_progress"] and not d.g["free_power_snapshot_valid"]
                  and not d.g["dump_snapshot_valid"], f"{label}: no lease and no operation flag was taken by a refused start")
            ex.ok(d.g["manual_write_in_progress"] is True and d.g["fallback_profile_op_in_progress"] is True and d.g["fallback_profile_step"] == 2,
                  f"{label}: the SAVE and its mutex are undisturbed")
        st = d.step("SAVE with colliding writers", body)
        check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label=f"{label}: the SAVE then", reboot=False)
        ex.eq(d.g["manual_write_in_progress"], False, f"{label}: the mutex is released after the SAVE")

    for w in WRITERS:
        collide(f"{w[0]} arrives while the SAVE holds the mutex", [w])
    collide("all three writers arrive during the same SAVE", list(WRITERS))
    ex.row("after the SAVE the same writers are admitted again (the SAVE released the mutex; one writer per run: an admitted writer owns it)")
    for script, ctr, prime in WRITERS:
        d = ready(mk, mode=("deferred", 120))
        d.save()
        ex.eq(d.g["manual_write_in_progress"], False, f"after the SAVE: the mutex is free ({script})")
        d.sim.safety_exempt = True              # from here on the admitted writer writes the inverter (see _start_writer)
        prime(d.sim)
        _start_writer(d.sim, script)
        ex.eq(d.g[ctr], 1, f"after the SAVE: {script} is admitted ({ctr} == 1)")


# ---------------------------------------------------------------------------
# F5: every obligation input the SAVE final lambda re-samples (part 1, step 5), mid-dispatch
# ---------------------------------------------------------------------------
@scenario("rc_final_revector_inputs", "each obligation input the SAVE final lambda re-samples has its own row: the write arms, the accept-in-progress flag, the restore / metadata / containment legs and every running Free Power / Dump / R244 script, turned on after reply 2")
def rc_final_revector_inputs(mk, ex: Exp):
    import _fbb2_gates_refusals as R1

    def mid(label, setup, want, *, obl=None, at=2):
        ex.row(label)
        d = ready(mk, mode=("deferred", 120))
        d.when(nth_deliver(at), lambda sim: setup(d))
        d.arm_on()
        st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
        check_refusal(ex, d, st, want, reads=READS4, nvs_ops=0, label=label, snap=None, accepted=True)
        ex.eq(d.stored("FBP"), None, f"{label}: nothing stored")
        ex.eq(d.stored("FBW"), None, f"{label}: no witness stored")
        if obl is not None:
            ex.has(d.b3_field("obl"), obl, f"{label}: B3 obl= shows the refusing slot ({obl}): the vector of the FINAL re-check is published")

    for name in ("dump_write_enable", "manual_config_write_enable"):
        mid(f"the {name} arm turned on after reply 2", lambda d, n=name: d.write_arm(n, True), TXT["G12"], obl="MT:CN")
    mid("free_power_recovery_accept_in_progress set after reply 2", lambda d: d.set_g("free_power_recovery_accept_in_progress", True),
        t_bus("Free Power"), obl="BUS:BY")
    mid("free_power_restore_requested alone after reply 2 (the in-memory state is inconsistent)",
        lambda d: d.set_g("free_power_restore_requested", True), t_slot("ram", "fp"), obl="FP:DV")
    mid("Free Power ACTIVE then restore requested after reply 2 (the lease becomes RESTORE REQUIRED)",
        lambda d: (d.lease("fp_active"), d.set_g("free_power_restore_requested", True)), t_slot("rr", "fp"), obl="FP:RR")
    mid("Dump to Grid ACTIVE then restore requested after reply 2 (the lease becomes RESTORE REQUIRED)",
        lambda d: (d.lease("dump_active"), d.set_g("dump_restore_requested", True)), t_slot("rr", "dump"), obl="DP:RR")
    mid("dump_recovery_metadata_corrupt alone after reply 2", lambda d: d.set_g("dump_recovery_metadata_corrupt", True),
        t_slot("mc", "dump"), obl="DP:MC")
    mid("dump_containment_state = 3 alone after reply 2 (the in-memory state is inconsistent)", lambda d: d.set_g("dump_containment_state", 3),
        t_slot("ram", "dump"), obl="DP:DV")
    code = {"fp": "FP", "dump": "DP", "r244": "R4"}
    for sid, dom, kind, _txt in R1.RUN_SCRIPTS:
        mid(f"{sid} running after reply 2", lambda d, sid=sid: d.sim.hold_script_running(sid, 5_000), t_slot(kind, dom),
            obl=f"{code[dom]}:{'ST' if kind == 'start' else 'EN'}")
    ex.row("control: none of these inputs set = the SAVE commits (the rows above refuse because of THEM)")
    d = ready(mk, mode=("deferred", 120))
    d.arm_on()
    st = d.execute("SAVE", d.b4, f"SAVE {d.b4}")
    check_saved(ex, d, st, gen=1, prior_gen=0, prior_binding=0, label="no obligation input set", reboot=False)
    # NOT a row: diag_write_lock_held / diag_write_lock_since_ms are inputs of the final re-check too, but they only matter together with the
    # shared write mutex (lock_stuck = mutex AND held AND age >= 300 s) and the final re-check masks the SAVE's OWN mutex, op flag and
    # dispatch: no behaviour can tell them apart there (an equivalent input by design, FB_B2_IMPLEMENTATION_NOTES.md section 3.3 step 5 "own-hold masking").


# ---------------------------------------------------------------------------
# F7: the profile never updates itself (no boot / interval / FB-C writer)
# ---------------------------------------------------------------------------
MIRROR_GLOBALS = ("fallback_profile_class", "fallback_profile_why", "fallback_profile_load", "fallback_witness_load", "fallback_profile_bytes",
                  "fallback_witness_bytes", "fallback_profile_seen_hw_gen", "fallback_profile_present_seen", "fallback_profile_read_anomaly",
                  "fallback_profile_save_unconfirmed", "fallback_profile_boot_loaded")


def _plain(v):
    try:
        return list(v)
    except TypeError:
        return v


@scenario("os_no_autowrite_idle", "the stored profile never updates itself: 24 h with the housekeeping, FB-C1 shadow and supervision ticks running over heartbeat / NTP / arm / Review traffic - zero NVS operations, unchanged FBP / FBW bytes and RAM mirror, zero Modbus writes")
def os_no_autowrite_idle(mk, ex: Exp):
    HOUR = 3_600_000
    REVIEW_HOURS = (6, 18)               # the Review itself reads the storage: those hours only have to show no durable SET
    for seed, label in (("valid", "boot VALID g7"), ("none", "boot NOT_CAPTURED")):
        ex.row(f"24 h run, {label}")
        d = mk(seed=seed)
        started = d.sim.start_intervals(lambda idx, iv: "supervision_lost_events" in str(iv))       # the FB-C1 shadow tick and the PR-A supervision tick
        ex.eq(len(started), 2, f"{label}: the FB-C1 shadow tick and the supervision tick are started")
        ex.eq(len(d.sim._intervals), 3, f"{label}: housekeeping + FB-C1 + supervision ticks are all running")
        d.establish_supervision()
        d.review(expect="CANDIDATE_READY")
        img0 = d.nvs_image()
        mir0 = {k: _plain(d.g[k]) for k in MIRROR_GLOBALS}
        txt0 = {k: d.text(k) for k in ("B1", "B2", "B7", "B8")}
        sets0 = len(d.nvs_set_history())
        ex.ok(len(img0) == (2 if seed == "valid" else 0), f"{label}: the stored image is {'FBP + FBW' if seed == 'valid' else 'empty'} at the start of the run")

        def traffic(h):
            spent = [0]

            def adv(ms):
                d.advance(ms)
                spent[0] += ms
            if h in REVIEW_HOURS:
                d.review(expect="CANDIDATE_READY")                # a candidate, expiring by itself 120 s later
            if h % 3 == 0:                                          # the REAL heartbeat action every 30 s for 10 minutes, silence after it
                for _ in range(20):
                    d.heartbeat()
                    adv(30_000)
            if h % 4 == 1:                                          # the clock lost, regained, stepping forward
                d.set_time(ntp=False)
                adv(120_000)
                d.set_time(epoch=d.epoch + 3_600 * h, ntp=True)
                adv(60_000)
            if h % 5 == 2:                                          # the operator arms, disarms, arms and walks away (the arm lifetime ends it)
                d.arm_on()
                adv(40_000)
                d.arm_off()
                d.arm_on()
                adv(150_000)
            adv(HOUR - spent[0])

        for h in range(24):
            m = d.mark()
            traffic(h)
            s = d.since(m)
            tag = f"{label}, hour {h}"
            ex.eq(s.nvs_set_log, [], f"{tag}: no direct NVS set")
            ex.eq(s.writes, [], f"{tag}: no Modbus write")
            ex.eq((s.commits, s.legacy_changed), ([], []), f"{tag}: no legacy preference commit")
            if h not in REVIEW_HOURS:
                ex.eq(s.nvs_ops, [], f"{tag}: no NVS operation of any kind")
            ex.ok(d.nvs_image() == img0, f"{tag}: the stored FBP / FBW bytes are unchanged")
            ex.eq({k: _plain(d.g[k]) for k in MIRROR_GLOBALS}, mir0, f"{tag}: the RAM mirror of the stored profile is unchanged")
            ex.eq({k: d.text(k) for k in ("B1", "B2", "B7", "B8")}, txt0, f"{tag}: B1 / B2 / B7 / B8 are unchanged")
            if ex.failed:
                return                                              # a mutant is killed at its first failing hour; the live run never gets here
        ex.eq(len(d.nvs_set_history()), sets0, f"{label}: no direct NVS set over the whole 24 h")
        ex.eq(d.modbus_writes(), [], f"{label}: no Modbus write over the whole 24 h")
        ex.eq(d.arm_state, False, f"{label}: the arm ended off (no firmware path turns it on)")
