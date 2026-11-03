#!/usr/bin/env python3
"""Harness self-tests of the assurance lab RTC tier (_lab_rtc: D1Sim / make_rig wrappers for the 2026-10-25 fall-back and the
2027-03-28 spring-forward nights, the real Free Power START + lease watchdog on the same D1Sim, lock-window extraction, the
correction / lease timelines, the test_fbd1_liveness invariants, the replay tier 'rtc') with the harness negative controls.
Offline assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing; the determinism re-run uses a
child Python process with bytecode writing disabled).
The firmware RTC lambdas run with ecco_rtc:: resolved onto the Python mirror registry/rtc_policy.py; C++ parity is proven only by
registry/tests/test_rtc_policy.py [4] with a compiler.
Quick mode: one scenario per property plus a 4-value lease-length sweep per night.
ECCO_LAB_EXTENDED=1 (or --extended): lease lengths 5..60 min in 5-min steps on both nights and a 0..14 s watchdog-phase sweep.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # worktree root
for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
FAILURES: list[str] = []
PASSES: list[str] = []          # held checks, excluding finding pins (LAB-SUMMARY 'pass')
PINS: list[str] = []            # held 'finding-reproduces:' checks (none in a self-test; LAB-SUMMARY 'finding_pins')
COUNTED: list[str] = []         # counted findings (a self-test reproduces none)
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (a self-test prints none)
BLOCKED: list[str] = []         # blocked scenarios (no scenario runs here)
# Phase-sensitivity registry (B4 change 7; HL-10): check-name prefix -> why that check's verdict depends on the lab's
# scheduler phase. The lab runs every firmware interval first at its startup_delay (else one period) after power-on with
# zero offset and reschedules it at due+T; the coupled tier samples the polled template sensors on the uptime grid and
# the RTC rig starts its intervals at the rig boot with a fixed phase. ESPHome 2026.8.2 runs each interval first at
# setup + startup_delay + a random offset in [0, min(T/2, 5 s)) and reschedules it at now+T (scheduler.cpp:105-110,
# 181-184, 540; interval.h; component.cpp:381-391). The tags were found by running every suite under an in-memory
# ESPHome-like phase patch (scratch only, not shipped; quick mode: 8 seeds of the full patch and 3 seeds of each of 3
# narrower variants; extended mode: 3 seeds) plus the audit's list of timing-bound checks. LAB-SUMMARY 'phase_sensitive'
# counts the EXECUTED checks (held or failed) whose name starts with a registered prefix (detected per run, never a
# literal); check_phase_registry() FAILS on a stale prefix (no executed check matches it), a prefix without a reason, or
# an unregistered PHASE_SENSITIVE_EXTENDED_ONLY entry (the prefixes whose checks run only in extended mode: they are
# required to match only there).
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "fall: reproduces the Phase-A VERIFIED trace": (
        "RTC-rig model self-test: the read instants (+45 s quiet, +105 s large) are the rig's rtc_read phase (60 s, "
        "30 s startup_delay, fixed phase) - fails under the phase patch with the RTC-rig part"),
    "spring: reproduces the Phase-A VERIFIED trace": (
        "RTC-rig model self-test: the read instants are the rig's rtc_read phase - fails under the phase patch with "
        "the RTC-rig part"),
    "record() fills the trace digest, the live source digest and the live anchor line": (
        "its draft expects the lock window [+105.12, +117.12) of one RTC read phase, so record() refuses at other "
        "phases (fails under the phase patch with the RTC-rig part); since the V0.1 review the replay round trip and "
        "the five phase-independent replay-engine controls after it then run on the same draft recorded without that "
        "lock_windows expectation"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (PINS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + PINS + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import copy  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbd1_harness as X  # noqa: E402
import rtc_policy as rp  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_rtc as L  # noqa: E402

FALL, SPRING = C.DST_FALL_2026_UTC, C.DST_SPRING_2027_UTC
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")


def raises(exc_type, fn, *args, **kwargs) -> tuple[bool, str]:
    """(fn raised exc_type, its message). Any other exception propagates: a crash is a FAIL, never a pass."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return True, str(exc)
    return False, "no exception"


def start_utc(kind: str) -> int:
    return X.utc_of_local(*L.DEFAULT_START_LOCAL[kind])


def all_empty(inv: dict) -> bool:
    return all(not v for v in inv.values())


def nonempty(inv: dict) -> dict:
    return {k: v[:2] for k, v in inv.items() if v}


# =============================================================================================================================
# [0] contract: registration, constants, anchors
# =============================================================================================================================
def section_contract() -> None:
    print("\n[0] contract")
    reg = T.registered("rtc")
    check("tier 'rtc' is registered with the factory, every action and every observer",
          reg == {"factory": True, "actions": sorted(L.ACTIONS), "observers": sorted(L.OBSERVERS)}, str(reg))
    for kind, day in (("fall", (2026, 10, 25)), ("spring", (2027, 3, 28))):
        ch = L.CHANGE_UTC[kind]
        check(f"CHANGE_UTC[{kind}] == _lab_clock constant == _fbd1_harness days_from_civil * 86400 + 3600",
              ch == (FALL if kind == "fall" else SPRING) == X.days_from_civil(*day) * 86400 + 3600, str(ch))
        flip = (X.london_offset_s(ch - 1), X.london_offset_s(ch))
        check(f"{kind}: the _fbd1_harness London offset flips exactly at CHANGE_UTC", flip == ((3600, 0) if kind == "fall"
                                                                                             else (0, 3600)), str(flip))
        check(f"{kind}: DEFAULT_START_LOCAL is the sc_dst start of test_fbd1_liveness (text anchor)",
              any(str(L.DEFAULT_START_LOCAL[kind]) in text for _p, text, _l in L.SOURCE_ANCHORS
                  if _p == "registry/tests/test_fbd1_liveness.py"), str(L.DEFAULT_START_LOCAL[kind]))
    check("WRITE_OUTCOMES == the spec write allow-list (aliases excluded)", set(L.WRITE_OUTCOMES) == {
        "ok", "ack_not_applied", "error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed",
        "timeout_lost", "custom_response"} and not set(X.WRITE_ALIASES) & set(L.WRITE_OUTCOMES), str(L.WRITE_OUTCOMES))
    check("READ_OUTCOMES == the spec read allow-list",
          set(L.READ_OUTCOMES) == {"ok", "error", "not_sent", "no_response", "custom_response", "timeout"}, str(L.READ_OUTCOMES))
    check("REASON_NAMES names every rtc_policy reason ('large' for R_LARGE, 'quiet' for R_QUIET)",
          set(L.REASON_NAMES) == set(rp.CORRECT_REASONS) | set(rp.HOLD_REASONS)
          and L.REASON_NAMES[rp.R_LARGE] == "large" and L.REASON_NAMES[rp.R_QUIET] == "quiet", str(L.REASON_NAMES))
    for path, text, line in L.SOURCE_ANCHORS:
        n, at = T.anchor_count(path, text)
        check(f"source anchor occurs exactly once: {path}:{line} {text[:60]!r}", n == 1, f"found {n} time(s)")
        if n == 1 and at != line:
            print(f"  info  anchor moved: {path} {text[:50]!r} recorded :{line}, now :{at}")
    fw = X.load(X.live_text())
    wd = L.fp_watchdog_index(fw)
    then = repr(fw["interval"][wd]["then"])
    check("fp_watchdog_index finds the 15 s interval holding the watchdog's lock skip and epoch end (anchors)",
          str(fw["interval"][wd]["interval"]) == "15s" and L.SOURCE_ANCHORS[0][1] in then and L.SOURCE_ANCHORS[1][1] in then,
          f"index {wd}")
    doc = L.__doc__ or ""
    check("module docstring has PUBLIC API, MODEL ASSUMPTIONS, NOT MODELLED and the Python-mirror statement",
          all(h in doc for h in ("PUBLIC API", "MODEL ASSUMPTIONS", "NOT MODELLED", "SOURCE ANCHORS", "PYTHON MIRROR")))
    check("the synthetic bank holds the spec 2.3 SITE values for every Free Power owned register",
          [L.SYNTHETIC_ORIGINAL[a] for a in L.FP_OWNED] == [120, 0, 8000, 8000, 7000, 8000, 8000, 5000] + [20] * 6
          + [1, 0, 0, 0, 0, 0])


# =============================================================================================================================
# [1] / [2] DST nights without faults
# =============================================================================================================================
def section_night(kind: str) -> None:
    sign = 1 if kind == "fall" else -1
    print(f"\n[{1 if kind == 'fall' else 2}] {kind} night, no faults (the PW11 scenario through the wrapper)")
    t0 = start_utc(kind)
    w = L.dst_night_rig(kind)
    check(f"{kind}: the world starts at the sc_dst start ({C.iso_utc(t0)}) with an empty firmware log",
          w.t_utc == t0 and [e["kind"] for e in w.log] == ["rtc.rig"], f"{w.t_utc} {[e['kind'] for e in w.log]}")
    w.advance_to(t0 + 25 * 60)
    check(f"{kind}: advance_to lands exactly on the UTC instant", w.t_utc == t0 + 1500, str(w.t_utc))
    after, before = w.corrections(after_change=True), w.corrections(after_change=False)
    c = after[0] if after else {}
    check(f"{kind}: exactly one correction after 01:00 UTC and none before", len(after) == 1 and not before,
          f"after {after} before {before}")
    check(f"{kind}: it is a 'large' correction queued within 3 min of the change",
          c.get("reason") == "large" and 0 < c.get("rel_change_s", -1) <= 180, str(c))
    check(f"{kind}: decided on an error of {sign * 3600} - 2 s (the inverter keeps the old local time)",
          c.get("decided_err_s") == sign * 3600 - 2 and abs(c.get("err_before_s", 0) - (sign * 3600 - 2)) < 1, str(c))
    check(f"{kind}: verified ('Verified OK'), one FC16 write, the inverter within 2 s afterwards",
          c.get("verified") is True and c.get("writes") == ["ok"] and abs(c.get("err_after_s", 99)) <= 2.0
          and abs(w.rtc_offset_s()) <= 2.0, str(c))
    dec = w.decisions(after_change=True)
    check(f"{kind}: reproduces the Phase-A VERIFIED trace (quiet at +45 s, large at +105 s, lock held 12 s)",
          [(d["reason"], d["rel_change_s"]) for d in dec[:2]] == [("quiet", 45.12), ("large", 105.12)]
          and c.get("held_s") == 12.0, str(dec[:3]))
    inv = w.invariants()
    check(f"{kind}: liveness invariants hold (I1, I2, I3, I6, audit, state, wire, NVS, oracle) - the idle FP watchdog "
          f"changes nothing", all_empty(inv) and len(w.sim.oracle_reads) >= 20, str(nonempty(inv)))
    locks = [(e["t_utc"], e["data"]["held"]) for e in w.log.events(kind="rtc.lock")]
    check(f"{kind}: the event log is UTC-monotonic and its rtc.lock events are the lock windows",
          not w.log.utc_regressions() and [x for a, b in w.lock_windows() for x in ((a, True), (b, False))] == locks,
          f"{locks} vs {w.lock_windows()}")
    bare = X.make_rig(local=L.DEFAULT_START_LOCAL[kind], offset_s=-2.0, oracle=True)
    bare.run_for(25 * 60_000)
    check(f"{kind}: identical lock windows and corrections to a bare make_rig run (test_fbd1_liveness.sc_dst pattern)",
          L.lock_windows(bare) == w.lock_windows() and L.corrections(bare) == L.corrections(w.sim),
          f"{L.lock_windows(bare)} vs {w.lock_windows()}")
    w.close()


# =============================================================================================================================
# [3] lock windows vs cip_edges
# =============================================================================================================================
def in_windows(t: float, wins: list) -> bool:
    return any(a <= t and (b is None or t < b) for a, b in wins)


def section_lock_windows() -> None:
    print("\n[3] lock windows extracted from cip_edges (lost write callback just before the fall-back)")
    w = L.dst_night_rig("fall", write_outcomes=["timeout_lost", "ok"])
    w.advance_to(FALL - 180)
    w.rtc_offset(-60)                      # the inverter drifts to -60 s: a background correction before the change
    samples = []
    while w.t_utc < FALL + 420:
        w.run_for(0.5)
        samples.append((w.t_utc, bool(w.sim.g["correction_in_progress"])))
    wins = w.lock_windows()
    edges = w.sim.cip_edges
    check("lock_windows == sim.lock_periods() converted to UTC", wins == [(L._utc(w.sim, a), None if b is None else
                                                                           L._utc(w.sim, b)) for a, b in w.sim.lock_periods()],
          str(wins))
    check("cip_edges alternate held / released, starting with held",
          [bool(v) for _t, v in edges] == [i % 2 == 0 for i in range(len(edges))], str(edges))
    bad = [(t, held) for t, held in samples if held != in_windows(t, wins)]
    check(f"correction_in_progress sampled every 0.5 s ({len(samples)} samples) is true exactly inside the windows", not bad,
          str(bad[:3]))
    cs = w.corrections()
    check("two transactions: the lost-callback correction and the DST correction", len(cs) == 2, str(cs))
    if len(cs) == 2:
        a, b = cs
        check("the first is released by the 90 s deadline breaker ('ABORTED', no write acknowledged)",
              a["held_s"] >= rp.kTxnDeadlineMs / 1000 and a["result"].startswith("ABORTED") and a["writes"] == ["timeout_lost"]
              and a["reason"] == "background", str(a))
        check("the 300 s cooldown holds the DST error: the large correction is queued >= 300 s after the abort",
              b["reason"] == "large" and b["queued_utc"] >= a["released_utc"] + 300 and b["verified"], str(b))
        held = [d["reason"] for d in w.decisions() if a["released_utc"] < d["utc"] < b["queued_utc"]]
        check("every regular read between the abort and the large correction was held by 'cooldown'",
              bool(held) and set(held) == {"cooldown"}, str(held))
    check("failed_corrections == 1", w.sim.g["failed_corrections"] == 1, str(w.sim.g["failed_corrections"]))
    check("liveness invariants hold through the abort", all_empty(w.invariants()), str(nonempty(w.invariants())))
    fake = types.SimpleNamespace(cip_edges=[(1, True), (2, True)], clock=w.sim.clock)
    ok, msg = raises(L.RtcLabError, L.lock_windows, fake)
    check("negative control: non-alternating cip_edges raise RtcLabError (never a silent window)", ok, msg)
    fake.cip_edges = [(1, False)]
    check("negative control: a release edge first raises RtcLabError", raises(L.RtcLabError, L.lock_windows, fake)[0])
    w.close()


# =============================================================================================================================
# [4] a Free Power lease across the change
# =============================================================================================================================
def lease_run(kind: str, minutes: int = 40, **kw):
    w = L.dst_night_rig(kind, fp_lease=True, fp_minutes=minutes, **kw)
    w.run_for(5)
    lease = w.fp_leases()[0]
    w.advance_to(max(lease["end_epoch"] + 60, w.change_utc + 300))
    return w, w.fp_leases()[0]


def lock_overlap_s(wins: list, a: float, b: float) -> float:
    return sum(max(0.0, min(b, wb) - max(a, wa)) for wa, wb in wins if wb is not None)


def section_fp_lease(kind: str) -> None:
    print(f"\n[4] {kind}: a Free Power lease across the change (real START button, real 15 s watchdog)")
    t0 = start_utc(kind)
    w, ls = lease_run(kind, 40)
    check(f"{kind}: START went ACTIVE through the real button / script and the end epoch is START + 40 min in UTC",
          ls["active_utc"] is not None and ls["start_utc"] == t0 and ls["end_epoch"] == t0 + 2400, str(ls))
    check(f"{kind}: the lease crosses the change", ls["start_utc"] < w.change_utc < ls["end_epoch"], str(ls))
    delay = (ls["restore_start_utc"] or 0) - ls["end_epoch"]
    check(f"{kind}: the restore starts on the UTC epoch (within one 15 s watchdog period; not shifted by an hour)",
          ls["restore_start_utc"] is not None and 0 <= delay <= 15, f"delay {delay} s")
    check(f"{kind}: the lease restores and verifies ('{L.FP_RESTORED_TEXT}')",
          ls["restored_text"] == L.FP_RESTORED_TEXT and ls["final_status"] == L.FP_RESTORED_TEXT
          and ls["restored_utc"] - ls["restore_start_utc"] < 10, str(ls["statuses"][-2:]))
    after = w.corrections(after_change=True)
    check(f"{kind}: exactly one verified large correction after the change, queued while the lease was ACTIVE",
          len(after) == 1 and after[0]["reason"] == "large" and after[0]["verified"]
          and ls["active_utc"] < after[0]["queued_utc"] < ls["end_epoch"], str(after))
    check(f"{kind}: the Free Power owned registers are back at the synthetic originals",
          {a: w.sim.bank[a] for a in L.FP_OWNED} == {a: L.SYNTHETIC_ORIGINAL[a] for a in L.FP_OWNED})
    g = w.sim.g
    check(f"{kind}: no lease state is left (active_persisted, snapshot_valid, restore_requested all false)",
          not g["free_power_active_persisted"] and not g["free_power_snapshot_valid"] and not g["free_power_restore_requested"])
    inv, raw = w.invariants(), L.invariant_violations(w.sim, fp=False)
    check(f"{kind}: invariants in Free Power scope hold", all_empty(inv), str(nonempty(inv)))
    check(f"{kind}: control: the plain RTC-only audits DO see the lease (state, wire and NVS non-empty), so the scope is needed",
          bool(raw["state"]) and bool(raw["wire"]) and bool(raw["nvs"]), str({k: len(v) for k, v in raw.items()}))
    commits = w.log.events(kind="nvs.commit")
    check(f"{kind}: the event log records the lease's durable commits with its end epoch",
          any(e["data"].get("end_epoch") == ls["end_epoch"] and e["data"]["ok"] for e in commits), str(commits[:2]))
    if kind == "fall":
        negative_controls_fp_scope(w)
    w.close()


def negative_controls_fp_scope(w) -> None:
    s = w.sim
    t = s.now_ms
    for wire, want in ((E.Wire("fw", "write", 22, 3, "ok", t, t, t, [0, 0, 0], "start_free_power_override"), "FC16 22"),
                       (E.Wire("fw", "write", 244, 1, "ok", t, t, t, [0], "restore_free_power_snapshot_dispatch"),
                        "outside the Free Power write surface"),
                       (E.Wire("fw", "read", 230, 3, "ok", t, t, t, [0, 0, 0], "start_dump_to_grid_override"),
                        "not an RTC, poll or Free Power path"),
                       (E.Wire("fw", "read", 22, 3, "ok", t, t, t, [0, 0, 0], "restore_free_power_snapshot_dispatch"),
                        "touched the RTC registers")):
        s.wire_log.append(wire)
        try:
            v = L.invariant_violations(s, fp=True)["wire"]
        finally:
            s.wire_log.pop()
        check(f"negative control (FP-scope wire): a hand-built {wire.kind} {wire.addr}/{wire.count} from {wire.issuer} is "
              f"caught", any(want in x for x in v), str(v))
    check("after the wire controls the FP-scope wire audit is clean again", not L.invariant_violations(s, fp=True)["wire"])
    s.nvs_commits.append((ds.Durable.DUMP_TO_GRID_VALID_TAG, ds.Record("ValidMarker", ds.Durable.VALID_MARKER_MAGIC, 1)))
    try:
        v = L.invariant_violations(s, fp=True)["nvs"]
    finally:
        s.nvs_commits.pop()
    check("negative control (FP-scope NVS): a Dump durable commit is caught", any("not a Free Power tag" in x for x in v), str(v))
    old = s.g["dump_active_persisted"]
    s.g["dump_active_persisted"] = not old       # an unattributed change (bypasses set_global)
    try:
        v = L.invariant_violations(s, fp=True)["state"]
    finally:
        s.g["dump_active_persisted"] = old
    check("negative control (FP-scope state): an unattributed global change is still caught", "dump_active_persisted" in v,
          str(v))
    check("after the controls every FP-scope invariant holds again", all_empty(L.invariant_violations(s, fp=True)))


# =============================================================================================================================
# [5] a restore due inside the RTC lock is deferred (composition)
# =============================================================================================================================
def deferral_run(phase_ms: int):
    t0 = start_utc("fall")
    w = L.dst_night_rig("fall", fp_phase_ms=phase_ms)
    w.advance_to(t0 + 25)
    w.fp_start(11, 6000)
    w.advance_to(FALL + 240)
    return w, w.fp_leases()[0]


def section_deferral() -> None:
    print("\n[5] the lease end falls just before the DST correction: the watchdog defers while the lock is held")
    w, ls = deferral_run(5000)
    win = [c for c in w.corrections(after_change=True) if c["reason"] == "large"]
    check("set-up: lease end (+100 s) precedes the large correction's lock (+105.12 .. +117.12 s) and a watchdog tick (+110 s) "
          "falls inside it", ls["end_epoch"] == FALL + 100 and len(win) == 1 and win[0]["queued_utc"] < FALL + 110
          < win[0]["released_utc"], f"{ls['end_epoch'] - FALL} {win}")
    if win:
        rs = ls["restore_start_utc"]
        check("the restore is NOT started inside the lock: it starts at the first watchdog tick after the release",
              rs is not None and win[0]["released_utc"] <= rs < win[0]["released_utc"] + 15 and rs - ls["end_epoch"] > 15,
              f"restore +{(rs or 0) - FALL} s, released +{win[0]['released_utc'] - FALL} s")
    check("the deferred lease still restores and verifies", ls["restored_text"] == L.FP_RESTORED_TEXT, str(ls["final_status"]))
    check("invariants hold", all_empty(w.invariants()), str(nonempty(w.invariants())))
    w.close()


# =============================================================================================================================
# [6] outcome allow-list
# =============================================================================================================================
def section_outcomes() -> None:
    print("\n[6] Modbus outcome allow-list (typos rejected before anything runs)")
    for kw in ({"write_outcomes": "timeout_lsot"}, {"write_outcomes": ["ok", "tiemout_lost"]},
               {"write_outcomes": "timeout"}, {"write_outcomes": "no_response"}, {"write_outcomes": []},
               {"write_outcomes": 1}, {"verify_outcomes": "okay"}, {"regular_outcomes": ["ok", "timeout_lost"]},
               {"verify_outcomes": E.FrameSpec(outcome="no_response_landed", latency_ms=50)}):
        ok, msg = raises(L.RtcLabError, L.dst_night_rig, "fall", **kw)
        check(f"dst_night_rig({kw}) raises RtcLabError", ok, msg)
    ok = True
    for o in L.WRITE_OUTCOMES:
        ok = ok and L._maker(o, None, None) is not None
    for o in L.READ_OUTCOMES:
        ok = ok and L._maker(None, o, [o, "ok"]) is not None
    check("every allow-listed outcome (str, list, FrameSpec) is accepted",
          ok and L._maker(E.FrameSpec(outcome="timeout_lost", latency_ms=30), None, None) is not None)
    w = L.dst_night_rig("fall", write_outcomes=lambda sim: "bogus")
    w.rtc_offset(-60)
    ok, msg = raises(L.RtcLabError, w.run_for, 300)
    check("a callable outcome returning a typo raises RtcLabError when the write happens (never a silent outcome)", ok, msg)
    w2 = L.dst_night_rig("fall")
    for kw in ({"write": "bogus"}, {"verify": "no_response_lost"}, {"regular": ["ok", ""]}):
        ok, msg = raises(L.RtcLabError, w2.set_outcomes, **kw)
        check(f"set_outcomes({kw}) raises RtcLabError", ok, msg)
    w2.set_outcomes(write=["timeout_lost", "ok"])
    check("set_outcomes binds a fresh outcome function to THIS sim", callable(w2.sim.outcome_fn)
          and w2.sim.outcome_fn("write", 22, 3) == "timeout_lost" and w2.sim.outcome_fn("write", 22, 3) == "ok")
    w.close()
    w2.close()


# =============================================================================================================================
# [7] misuse fails loud
# =============================================================================================================================
def section_misuse() -> None:
    print("\n[7] clock / input misuse fails loud")
    w = L.dst_night_rig("fall")
    w.run_for(10)
    for label, fn, args in (("advance_to the past", w.advance_to, (w.t_utc - 1,)),
                            ("advance_to off the 1 ms grid", w.advance_to, (w.t_utc + 0.0004,)),
                            ("run_for(True)", w.run_for, (True,)), ("run_for(NaN)", w.run_for, (float("nan"),)),
                            ("run_for(-1)", w.run_for, (-1,)), ("run_for('5')", w.run_for, ("5",)),
                            ("poke an unknown global", w.poke, ("no_such_global", True)),
                            ("poke a float", w.poke, ("free_power_restore_requested", 1.5)),
                            ("press a non-RTC button", w.press, ("start_free_power_button",)),
                            ("fp_start(minutes=0)", w.fp_start, (0, 6000)), ("fp_start(minutes=10.5)", w.fp_start, (10.5, 6000)),
                            ("fp_start(power_w=100)", w.fp_start, (40, 100)), ("rtc_rate(None)", w.rtc_rate, (None,))):
        ok, msg = raises(L.RtcLabError, fn, *args)
        check(f"{label} raises RtcLabError", ok, msg)
    check("after the refused calls the clock did not move", w.t_utc == start_utc("fall") + 10, str(w.t_utc))
    for label, kw in (("start_utc in the GMT copy of the repeated hour", {"start_utc": FALL + 1800}),
                      ("a start_local in the spring-forward gap", {"start_local": (2027, 3, 28, 1, 30, 0)}),
                      ("a start more than 24 h from the change", {"start_local": (2026, 10, 20, 12, 0, 0)}),
                      ("start_local and start_utc together", {"start_local": (2026, 10, 25, 0, 30, 0), "start_utc": FALL}),
                      ("a 5-field start_local", {"start_local": (2026, 10, 25, 0, 30)}),
                      ("fp_phase_ms == 15000", {"fp_phase_ms": 15000}), ("a 5-word tou", {"tou": (0, 1, 2, 3, 4)})):
        kind = "spring" if "spring" in label else "fall"
        ok, msg = raises(L.RtcLabError, L.dst_night_rig, kind, **kw)
        check(f"dst_night_rig with {label} raises RtcLabError", ok, msg)
    check("an unknown kind raises RtcLabError", raises(L.RtcLabError, L.dst_night_rig, "winter")[0])
    amb = L.dst_night_rig("fall", (2026, 10, 25, 1, 30, 0))
    check("an ambiguous start_local is read as BST (fold 0: the first copy of the repeated hour, equal to "
          "_lab_clock.utc_of_local(..., fold=0))",
          amb.t_utc == C.utc_of_local(2026, 10, 25, 1, 30, 0, fold=0) == FALL - 1800, str(amb.t_utc))
    amb.close()
    n = len(w.log)
    obs = (w.lock_windows(), w.corrections(), w.decisions(), w.fp_statuses(), w.fp_leases(), w.fp_status(), w.invariants(),
           w.rtc_offset_s(), w.results())
    check("observers are read-only (the log did not grow)", len(w.log) == n and obs is not None)
    w.close()
    check("close() restores the sim's previous event_hook", w.sim.event_hook is None)
    check("after close() the world refuses to run", raises(L.RtcLabError, w.run_for, 1)[0])


# =============================================================================================================================
# [8] determinism
# =============================================================================================================================
BUILD = """
def build(L, offset_s=-2.0):
    w = L.dst_night_rig("fall", fp_lease=True, fp_minutes=20, write_outcomes=["timeout_lost", "ok"], offset_s=offset_s)
    w.advance_to(L.CHANGE_UTC["fall"] - 180)
    w.rtc_offset(-60)
    w.advance_to(L.CHANGE_UTC["fall"] + 600)
    return w
"""


def timeline(w) -> str:
    return T.canonical_json({"locks": w.lock_windows(), "corr": w.corrections(), "dec": w.decisions(), "fp": w.fp_leases(),
                             "inv": w.invariants(), "results": w.results(), "log": w.log.digest()})


def section_determinism() -> None:
    print("\n[8] determinism")
    ns: dict = {}
    exec(BUILD, ns)  # noqa: S102 - the suite's own code string, also run in the child process below
    a, b = ns["build"](L), ns["build"](L)
    check("same configuration => identical extracted timeline and event-log digest (in process)",
          timeline(a) == timeline(b) and a.log.canonical() == b.log.canonical(), a.log.digest())
    check("the timeline is not trivial (two transactions, a lease, > 40 events)",
          len(a.corrections()) == 2 and len(a.fp_leases()) == 1 and len(a.log) > 40, f"{len(a.corrections())} {len(a.log)}")
    c = ns["build"](L, offset_s=-3.0)
    check("control: a different inverter offset changes the digest", c.log.digest() != a.log.digest())
    code = ("import sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, " + repr(str(HERE)) + ")\nimport _lab_rtc as L\n"
            + BUILD + "print(build(L).log.digest())\n")
    outs = []
    for seed in ("7", "11"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True,
                           timeout=300)
        outs.append((r.returncode, r.stdout.strip(), r.stderr.strip()[-300:]))
    check("child processes with PYTHONHASHSEED 7 and 11 reproduce the same digest",
          all(rc == 0 and out == a.log.digest() for rc, out, _e in outs), str(outs))
    for x in (a, b, c):
        x.close()


# =============================================================================================================================
# [9] replay tier 'rtc'
# =============================================================================================================================
def recorded(draft: dict, name: str):
    """T.record(draft); when the recording itself fails (record()'s LabTraceError family: expectations that no longer hold
    after a production behaviour change, an anchor or schema problem) the check `name` FAILS with the error text and None
    is returned, so the suite still reaches its FAILED / LAB-SUMMARY lines instead of crashing. Only those record / replay
    errors are caught; a failure is never turned into a pass."""
    try:
        return T.record(draft)
    except T.LabTraceError as exc:
        check(name, False, f"record() raised {type(exc).__name__}: {exc}")
        return None


# the round trip and the five replay-engine controls of [9] (names unchanged; R3-8 prints each as a FAIL when no
# document could be recorded)
REPLAY_CONTROLS = (
    "replay of the recorded document passes (digest equal, no drift, every expectation holds)",
    "negative control: an altered expectation makes the replay FAIL",
    "negative control: a changed action changes the digest (digest_mismatch, FAIL)",
    "an unknown action raises ReplayDispatchError",
    "a replay starting in the GMT copy of the repeated hour fails loud in the factory",
    "an outcome typo in the world kwargs fails loud in the factory",
)


def section_replay() -> None:
    print("\n[9] replay tier 'rtc' (in memory; nothing written)")
    t0 = start_utc("fall")
    draft = {
        "schema": T.SCHEMA, "id": "RT-00-selftest", "title": "Self-test: fall-back night with a Free Power lease",
        "tier": "rtc", "seed": 0, "utc_start": C.iso_utc(t0), "synthetic": True,
        "ownership": "synthetic Free Power lease started by the self-test; no Dump, no HA",
        "source_anchors": [{"path": L.FW_REL, "text": L.SOURCE_ANCHORS[1][1], "line_at_record": 1}],
        "source_digests": {}, "world": {"kind": "fall"},
        "actions": [{"at_s": 0, "do": "fp_start", "args": {"minutes": 40, "power_w": 6000}},
                    {"at_s": 0, "do": "run_for", "args": {"seconds": 2700}}],
        "expect": [{"observe": "n_corrections", "args": {"after_change": True, "reason": "large", "verified": True},
                    "op": "==", "value": 1},
                   {"observe": "lock_windows", "args": {}, "op": "==", "value": [[FALL + 105.12, FALL + 117.12]]},
                   {"observe": "fp_status", "args": {}, "op": "==", "value": L.FP_RESTORED_TEXT},
                   {"observe": "invariants", "args": {}, "op": "==",
                    "value": {k: 0 for k in ("i1", "i2", "i3", "i6", "audit", "state", "wire", "nvs", "oracle")}},
                   {"observe": "global_value", "args": {"name": "free_power_snapshot_valid"}, "op": "==", "value": False}],
        "classification": "PASS", "invariant": "INV-RTC-DST-ONE-LARGE", "grade": "VERIFIED", "confidence": "high",
        "failure_outcome": "harness self-test only", "smallest_safe_repair_scope": "none (harness self-test)",
        "scenario_priority": "P3", "finding_priority": None,
    }
    name = "record() fills the trace digest, the live source digest and the live anchor line from two identical replays"
    doc = recorded(draft, name)
    if doc is None:
        # V0.1 review (R3-8): the replay round trip and the five replay-engine controls below do not depend on the
        # scheduler phase; when record() fails (the lock_windows expectation is bound to one RTC read phase), they run on
        # the same draft recorded without that expectation, so a failed record() never hides them; if that recording
        # fails too, each prints a FAIL 'not run: record() failed' (never skipped silently)
        alt = copy.deepcopy(draft)
        alt["expect"] = [e for e in alt["expect"] if e["observe"] != "lock_windows"]
        print("  info  record() failed: the replay round trip and the replay-engine controls run on the draft recorded "
              "without its timeline-bound lock_windows expectation")
        doc = recorded(alt, "record() of the same draft without its timeline-bound lock_windows expectation (the base of "
                            "the replay-engine controls after a failed record())")
        if doc is None:
            for ctl in REPLAY_CONTROLS:
                check(ctl, False, "not run: record() failed")
            return
    else:
        # the anchor line is compared with the LIVE line (spec 2.2: line numbers are information only; an unrelated
        # firmware edit above the anchor must not turn this red); SOURCE_ANCHORS[1][2] stays the line at writing,
        # reported as info by [0]
        check(name, len(doc["trace_digest"]) == 64 and doc["source_digests"] == {L.FW_REL: T.source_digest(L.FW_REL)}
              and doc["source_anchors"][0]["line_at_record"] == T.anchor_line(L.FW_REL, L.SOURCE_ANCHORS[1][1]),
              f"{doc['source_anchors']} {doc['source_digests']}")
    r = T.replay(doc)
    check(REPLAY_CONTROLS[0],
          r.ok and not r.drift and r.digest == doc["trace_digest"] and not r.failed_expectations, str(r.failed_expectations))
    bad = copy.deepcopy(doc)
    bad["expect"][0]["value"] = 2
    r2 = T.replay(bad)
    check(REPLAY_CONTROLS[1], not r2.ok and len(r2.failed_expectations) == 1, str(r2.failed_expectations))
    bad = copy.deepcopy(doc)
    bad["actions"][1]["args"]["seconds"] = 2701
    r3 = T.replay(bad)
    check(REPLAY_CONTROLS[2], not r3.ok and r3.digest_mismatch)
    bad = copy.deepcopy(doc)
    bad["actions"][0]["do"] = "reboot"
    check(REPLAY_CONTROLS[3], raises(T.ReplayDispatchError, T.replay, bad)[0])
    bad = copy.deepcopy(doc)
    bad["utc_start"] = C.iso_utc(FALL + 1800)
    ok, msg = raises(L.RtcLabError, T.replay, bad)
    check(REPLAY_CONTROLS[4], ok, msg)
    bad = copy.deepcopy(doc)
    bad["world"] = {"kind": "fall", "write_outcomes": ["ok", "timeout_lots"]}
    check(REPLAY_CONTROLS[5], raises(L.RtcLabError, T.replay, bad)[0])


# =============================================================================================================================
# [10] the D1Sim reboot hazard
# =============================================================================================================================
def section_reboot_guard() -> None:
    print("\n[10] D1Sim reboot is refused (known hazard; reboot_d1 deliberately not provided)")
    w = L.dst_night_rig("fall")
    ok, msg = raises(L.RtcLabUnsupported, w.sim.reboot)
    check("world.sim.reboot() raises RtcLabUnsupported", ok and "OLD sim" in msg, msg)
    new = type(w.sim).reboot(w.sim)
    check("hazard reproduces with the class method FbbSim.reboot: no WallClock / InverterRtc, read_override_fn bound to the "
          "OLD sim (why the guard exists)",
          new.clock is None and new.rtc is None and not isinstance(new.entities.get("ntp_time"), X.WallClock)
          and getattr(new.read_override_fn, "__self__", None) is w.sim, f"{type(new.entities.get('ntp_time')).__name__}")
    w.close()


# =============================================================================================================================
# sweeps (quick: 4 lease lengths per night; extended: 12 per night + the watchdog-phase sweep)
# =============================================================================================================================
def section_sweeps() -> None:
    minutes = list(range(5, 65, 5)) if EXTENDED else [10, 25, 40, 55]
    print(f"\n[11] lease-length sweep {minutes} min on both nights" + (" + watchdog phase 0..14 s" if EXTENDED else ""))
    bad = []
    for kind in L.KINDS:
        for m in minutes:
            w, ls = lease_run(kind, m)
            wins = w.lock_windows()
            bound = 15 + lock_overlap_s(wins, ls["end_epoch"], ls["end_epoch"] + 15 + 12)
            delay = (ls["restore_start_utc"] or 1e9) - ls["end_epoch"]
            large = [c for c in w.corrections(after_change=True) if c["reason"] == "large" and c["verified"]]
            if not (ls["end_epoch"] == ls["start_utc"] + 60 * m and 0 <= delay <= bound
                    and ls["restored_text"] == L.FP_RESTORED_TEXT and len(large) == 1 and all_empty(w.invariants())):
                bad.append((kind, m, delay, bound, ls["final_status"], len(large), nonempty(w.invariants())))
            w.close()
    check(f"every lease ({len(L.KINDS) * len(minutes)} runs) ends on its UTC epoch (restore within one watchdog period plus "
          "any lock overlap), restores verified, one verified large DST correction, invariants hold", not bad, str(bad[:3]))
    if EXTENDED:
        badp = []
        for ph in range(0, 15000, 1000):
            w, ls = deferral_run(ph)
            rs = ls["restore_start_utc"]
            if rs is None or in_windows(rs, w.lock_windows()) or ls["restored_text"] != L.FP_RESTORED_TEXT \
                    or not all_empty(w.invariants()):
                badp.append((ph, rs, ls["final_status"]))
            w.close()
        check("watchdog phase 0..14 s: no restore ever starts inside an RTC lock window, every lease restores verified",
              not badp, str(badp[:3]))


# =============================================================================================================================
# run
# =============================================================================================================================
section_contract()
section_night("fall")
section_night("spring")
section_lock_windows()
section_fp_lease("fall")
section_fp_lease("spring")
section_deferral()
section_outcomes()
section_misuse()
section_determinism()
section_replay()
section_reboot_guard()
section_sweeps()

RUNTIME_S = time.perf_counter() - T0
print("")
print(f"  info  runtime {RUNTIME_S:.1f} s ({'EXTENDED' if EXTENDED else 'quick'})")
check_phase_registry()
T.finish("test_lab_selftest_rtc", passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=PINS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
