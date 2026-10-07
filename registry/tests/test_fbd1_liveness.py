#!/usr/bin/env python3
"""FB-D1 (RTC / polling / liveness hardening) - the behaviour suite: the REAL firmware lambdas of the RTC correction, the
telemetry / configuration polls, the configuration catch-up and the B10 fence, run on the strict FB-B simulator through
registry/tests/_fbd1_harness.py (wall clock, inverter RTC device model, deferred FC16 writes, per-path authority audit, the policy
oracle). Every scenario runs on the live firmware; the key ones also run on the pre-FB-D1 firmware (== main, the exact reverter
_fbd1_scope.pre_fbd1_firmware) where they must FAIL, and in-memory mutants of the FB-D1 firmware must each be killed by a named
detector.

  [1] RTC transaction  success; write error / no_response x2 -> FAILED + cooldown honoured; write not_sent / custom_response and a
                       lost write callback -> released within a bound (retry path / the 90 s quiet-bus deadline breaker); a late
                       acknowledgement after the release revives nothing; verification read invalid / error / no_response /
                       not_sent (marker) / custom_response / lost; the inverter ignoring writes; the NTP-abort branch; the write-mutex
                       deferral; Automatic Clock Sync off in every phase; the manual Sync path (idle, cooldown, during an automatic
                       transaction, auto off, lost callback); the breaker on a busy bus in every RTC state (releases between frames -
                       S1 / S3 / S5 - holds while a write or verification read may be outstanding - S2 / S4), releases only RTC
                       state, never trips a slow healthy transaction; HA presses during a correction; NTP never synced at boot;
                       millis() wrap; the quiet-bus write dispatch; stray progress flags without the lock; a seeded outcome fuzz
                       (I1 / I6 / liveness)
  [2] policy wiring    the firmware's decision == registry/rtc_policy.decide() on independently collected inputs for EVERY regular
                       read (the oracle), plus behaviour: a single stale read, a frozen image, quiet windows (half hour, TOU zone
                       start), energy transactions vs large errors, precision corrections before a TOU zone start (once per
                       boundary; a large error there still needs two reads), the zone-cross hold (a positive error that would step
                       the inverter back across a boundary it already passed), boot alignment, the background gap, DST, a night of
                       stale / freezing reads and a drifting PV day.
                       Every number (thresholds, window edges, gap, large error) is DERIVED from rtc_policy itself - nothing here
                       re-implements or hard-codes the policy
  [3] polls            an owner (write mutex, RTC lock, a real Sync) taking the write path during a poll delay gets no later poll
                       frame; Block A / B / C not_sent / custom_response follow the invalidation rule and stamp nothing; the
                       dispatch stamp counts exactly the Block B reads; the catch-up (after a yield; two polls after every RTC
                       release; an owner phase-locked to the 60 s poll never starves Block B); a randomised owner / outcome run
  [4] fence            after a correction B10 is never MATCH while the lock is held, needs two post-fence Block B dispatches, and
                       with the catch-up returns to MATCH within seconds; a diverted Block B leaves MATCH at the next tick; the B10
                       MATCH share over a high-PV stretch (the availability KPI; main is far below it)
  [5] static           five terminal handlers on every RTC / poll Modbus action; every lock site stamps the deadline clock; the
                       breaker's scope and quiet-bus terms; no FB-D1 global in the fence / B10 / FB-C inputs; the literal 22-24
                       write; every delayed poll read inside an owner-free re-check; the catch-up / dispatch / verification shapes
  [6] pre-FB-D1        the "fails on main" scenarios FAIL on pre_fbd1_firmware(live)
  [7] mutants          each FB-D1 element dropped in memory is killed by a named detector

Offline only: no device, no Home Assistant, no network. Deterministic (seeded). This proves the firmware lambdas' behaviour under
the simulator's model of ESPHome / the Modbus hub / the inverter clock - not the compiled binary or the real inverter.
"""

from __future__ import annotations

import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbd1_harness as X  # noqa: E402
import _fbd1_scope as scope  # noqa: E402
import rtc_policy as rp  # noqa: E402

FAILURES: list[str] = []
N_CHECKS = [0]
LIVE = X.live_text()
# PEX0: FB-D1's historical baseline is read AS OF fbd1 through the tree's chain (every later entry's declared firmware edits undone
# exactly), so a later declared firmware entry never moves it; the liveness behaviour below keeps running on the live firmware.
import _scope_chain as _chain  # noqa: E402
LIVE_FBD1 = _chain.CHAIN.as_of(_chain.FIRMWARE, "fbd1", LIVE)
PRE = X.pre_text(LIVE_FBD1)


def check(name: str, condition: bool, detail: str = "") -> None:
    N_CHECKS[0] += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class R:
    """One scenario's criteria: (key, description, ok, detail). Reported as checks on the live firmware; on the pre-FB-D1 firmware /
    a mutant the failing keys are the evidence."""

    def __init__(self, sid: str, sim=None):
        self.sid, self.sim, self.items = sid, sim, []

    def crit(self, key, desc, ok, detail="") -> bool:
        self.items.append((key, desc, bool(ok), str(detail)[:400]))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(i[2] for i in self.items)

    def failed(self) -> list:
        return [i[0] for i in self.items if not i[2]]


def report(r: R) -> R:
    for _key, desc, ok, detail in r.items:
        check(f"{r.sid}: {desc}", ok, detail)
    return r


def inv(r: R, s, *, i2: bool = True) -> R:
    bad = []
    if s.i1_violations:
        bad.append(f"I1 {s.i1_violations[:1]}")
    if i2 and s.i2_violations:
        bad.append(f"I2 {s.i2_violations[:1]}")
    if s.i3_violations:
        bad.append(f"I3 {s.i3_violations[:1]}")
    bs = [x for x in s.successes if not x[1]]
    if bs:
        bad.append(f"I6 {bs[:1]}")
    for name, v in (("audit", s.audit_violations()), ("state", s.state_violations()), ("wire", s.wire_violations()),
                    ("nvs", s.nvs_violations())):
        if v:
            bad.append(f"{name} {v[:3]}")
    if s.oracle_on and s.oracle_mismatches:
        bad.append(f"oracle {s.oracle_mismatches[:2]}")
    extra = f"; policy oracle == firmware on {len(s.oracle_reads)} regular reads" if s.oracle_on else ""
    r.crit("inv", "invariants: I1 after every 1 s tick, I3, I6, RTC / poll authority audit + state diff, wire, no NVS" + extra, not bad,
           "; ".join(bad))
    return r


D = rp.kTxnDeadlineMs
COOLDOWN_MS = 300_000  # the firmware's literal `millis() + 300000` (unchanged by FB-D1)


def local_of(tod: int, day=(2026, 10, 4)) -> tuple:
    return (day[0], day[1], day[2], tod // 3600, (tod // 60) % 60, tod % 60)


def t_of(s, tod: int) -> int:
    """The virtual ms at which the local clock next reads `tod` (seconds of day)."""
    cur = s.clock.local_ms() % 86_400_000
    d = tod * 1000 - cur
    return s.now_ms + (d if d >= 0 else d + 86_400_000)


def queues(s, after: int = -1) -> list:
    return [t for t, v in s.cip_edges if v and t >= after]


def oracle_at(s, t: int):
    for rd in s.oracle_reads:
        if rd["t"] == t:
            return rd
    return None


def spec(outcome: str, latency: int) -> E.FrameSpec:
    return E.FrameSpec(outcome=outcome, latency_ms=latency)


# ============================================================================================================================
# the policy numbers, DERIVED from registry/rtc_policy.py (decide() scans + constants) - never hard-coded here
# ============================================================================================================================
P = 20
DAY0 = X.days_from_civil(2026, 10, 4)
T_FREE = X.hms(10, 15)  # verified below to be outside every window of GOLD_TOU
TOU_1635 = (0, 530, 1000, 1635, 2100, 2330)
TOU_DAY = (700, 800, 1000, 1200, 1500, 1700)  # no TOU zone start between 18:00 and 06:58


def pin(tod, err, prev=None, *, aligned=True, tou=X.GOLD_TOU, lease=False, served=0) -> rp.Inputs:
    i = rp.Inputs()
    i.auto_sync, i.lock_held, i.cooldown_active, i.lease_active = True, False, False, lease
    i.boot_aligned = aligned
    i.err_s = int(err)
    i.prev_valid = prev is not None
    i.prev_err_s = int(prev) if prev is not None else 0
    i.ntp_elapsed_s, i.inv_elapsed_s = 60, 60
    i.tod_s, i.day, i.threshold_s = int(tod) % 86400, DAY0, P
    i.precision_served = served
    i.tou_raw = list(tou)
    return i


def _first_correcting(tod, **kw) -> int:
    for e in range(1, 3000):
        if rp.decide(pin(tod, -e, -e, **kw)).action == rp.ACT_CORRECT:
            return e
    raise AssertionError(f"no error corrects at tod {tod}")


class _Numbers:
    def __init__(self):
        self.LARGE = rp.kLargeErrorS
        self.GAP = rp.kMinGapMs
        self.BG = _first_correcting(T_FREE)
        self.BOOT = _first_correcting(T_FREE, aligned=False)
        self.free_ok = rp.decide(pin(T_FREE, -(self.BG + 20), -(self.BG + 20))).reason == rp.R_BACKGROUND
        self.QW_HH = self.quiet_window(X.hms(10, 30), X.GOLD_TOU)
        self.QW_TOU = self.quiet_window(X.hms(16, 35), TOU_1635)
        self.PW_16 = self.precision_window(X.hms(16, 0), X.GOLD_TOU)
        self.QW_16 = self.quiet_window(X.hms(16, 0), X.GOLD_TOU)
        self.PT = _first_correcting((self.PW_16[0] + self.PW_16[1]) // 2)

    def quiet(self, tod, tou) -> bool:
        return rp.decide(pin(tod, -(self.BG + 20), -(self.BG + 20), tou=tou)).reason == rp.R_QUIET

    def precise(self, tod, tou) -> bool:
        return rp.decide(pin(tod, -(self.BG - 1), -(self.BG - 1), tou=tou)).reason == rp.R_PRECISION

    def _run(self, b, pred, lo, hi):
        ts = [t for t in range(b - lo, b + hi) if pred(t)]
        if not ts:
            raise AssertionError(f"no window near {b}")
        # the maximal contiguous run nearest to b
        runs, cur = [], [ts[0]]
        for t in ts[1:]:
            if t == cur[-1] + 1:
                cur.append(t)
            else:
                runs.append(cur)
                cur = [t]
        runs.append(cur)
        best = min(runs, key=lambda r_: 0 if r_[0] <= b <= r_[-1] else min(abs(r_[0] - b), abs(r_[-1] - b)))
        return best[0], best[-1] + 1

    def quiet_window(self, b, tou):
        return self._run(b, lambda t: self.quiet(t, tou), 900, 900)

    def precision_window(self, b, tou):
        return self._run(b, lambda t: self.precise(t, tou), 1200, 0)


N = _Numbers()


# ============================================================================================================================
# [1] RTC transaction
# ============================================================================================================================
def sc_success(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    t0 = s.now_ms
    s.run_for(200_000)
    r = R("R01 success", s)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    end = rel if rel is not None else s.now_ms
    w = [x for x in s.rtc_write_attempts() if q is not None and q <= x.t <= end]
    v = [x for x in s.rtc_wire("read") if q is not None and q < x.t_queued <= end]
    res = s.results(q) if q is not None else []
    r.crit("queue", "the first over-threshold regular read does not queue a correction, the second (confirming) read does",
           q is not None and q - t0 >= 60_000, f"queue at +{(q - t0) if q else None} ms")
    r.crit("verified", "released by a verified readback ('Verified OK'): corrections_since_boot 1, failed_corrections 0",
           rel is not None and bool(res) and res[-1].startswith("Verified OK") and s.g["corrections_since_boot"] == 1
           and s.g["failed_corrections"] == 0, res)
    r.crit("frames", "exactly one FC16 22-24 and one verification FC03 22/3 inside the transaction", len(w) == 1 and len(v) == 1,
           f"writes {len(w)} reads {len(v)}")
    r.crit("released", "every RTC flag released; last_correction published once",
           s.released() and len(s.ent("last_correction").published) == 1, s.flags())
    r.crit("stamp", "rtc_txn_since_ms was stamped with millis() at the queue",
           q is not None and s.g.get("rtc_txn_since_ms") == (q & 0xFFFFFFFF), s.g.get("rtc_txn_since_ms"))
    r.crit("owed", "the lock release owes exactly two configuration polls (cfg_poll_owed = 2)", s.g.get("cfg_poll_owed") == 2,
           s.g.get("cfg_poll_owed"))
    r.crit("clock", "the inverter clock ends within 2 s of NTP", abs(s.rtc.offset_s()) <= 2.0, s.rtc.offset_s())
    return inv(r, s)


def sc_write_fail_twice(text, outcome) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write=[outcome, outcome, "ok"]))
    s.run_for(620_000)
    r = R(f"R02 write {outcome} x2", s)
    q = X.queue_time(s)
    f = s.first_result_time("FAILED after communication errors", q or 0)
    att = s.rtc_write_attempts()
    txn = [a for a in att if q is not None and f is not None and q <= a.t <= f]
    later = [a for a in att if f is not None and a.t > f]
    r.crit("failed", "one retry (attempt 2), then 'FAILED after communication errors' + cooldown, within 5 s of the queue",
           q is not None and f is not None and f - q <= 5000 and len(txn) == 2 and s.g["failed_corrections"] == 1,
           f"q={q} f={f} attempts={len(txn)}")
    r.crit("cooldown", "no FC16 22-24 is queued for 300 s after FAILED (the cooldown is honoured)",
           f is not None and all(a.t >= f + COOLDOWN_MS for a in later), [a.t - (f or 0) for a in later])
    if outcome in X.WRITE_LANDED:
        r.crit("nosuccess", "a write that landed without an acknowledgement is never counted as a success (no verification read)",
               s.g["corrections_since_boot"] == 0 and abs(s.rtc.offset_s()) <= 3.0, s.flags())
    else:
        r.crit("again", "after the cooldown the next confirmed regular read corrects again (verified)",
               bool(later) and later[0].t <= f + COOLDOWN_MS + 125_000 and s.g["corrections_since_boot"] == 1, s.flags())
    return inv(r, s)


def sc_write_refused(text, outcome) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write=outcome))
    s.run_for(300_000)
    r = R(f"R04 write {outcome}", s)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    att = [a for a in s.rtc_write_attempts() if q is not None and q <= a.t <= (rel or s.now_ms)]
    r.crit("bounded", "released within 5 s of the queue through the bounded retry path (two attempts, then FAILED + cooldown)",
           q is not None and rel is not None and rel - q <= 5000 and len(att) == 2
           and any(x.startswith("FAILED after communication errors") for x in s.results(q)), f"q={q} rel={rel} {s.flags()}")
    r.crit("count", "failed_corrections 1, no success, cooldown armed, no flag left set",
           s.g["failed_corrections"] == 1 and s.g["corrections_since_boot"] == 0 and s.g["cooldown_until_ms"] != 0 and s.released(),
           s.flags())
    return inv(r, s)


def sc_write_lost(text, outcome="timeout_lost") -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write=outcome))
    s.run_for(300_000)
    r = R(f"R06 write callback lost ({outcome})", s)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    r.crit("breaker", f"released by the deadline breaker {D / 1000:.0f}-{D / 1000 + 1:.0f} s after the lock was taken (quiet bus)",
           q is not None and rel is not None and D <= rel - q <= D + 1000
           and any(x.startswith("ABORTED - correction exceeded its deadline") for x in s.results(q)),
           f"held {(rel - q) if (q and rel) else None} ms {s.flags()}")
    r.crit("count", "failed_corrections 1, cooldown armed, no success, one write attempt, no verification read",
           s.g["failed_corrections"] == 1 and s.g["cooldown_until_ms"] != 0 and s.g["corrections_since_boot"] == 0
           and len(s.rtc_write_attempts()) == 1 and s.released(), s.flags())
    return inv(r, s)


def sc_late_ack(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write="timeout_lost"))
    r = R("R06b late acknowledgement after the release", s)
    ok = X.run_until(s, lambda sm: sm.first_result_time("ABORTED") is not None, 300_000)
    r.crit("pre", "precondition: a lost FC16 callback was released by the breaker", ok)
    n_w, n_ok, n_fail = len(s.rtc_write_attempts()), s.g["corrections_since_boot"], s.g["failed_corrections"]
    s._handler(s._rtc_write_body, "on_response", {})  # the late acknowledgement of that write, delivered after the release
    stray = bool(s.g["verification_pending"]) and not s.g["correction_in_progress"]
    s.run_for(1_100)
    r.crit("stray", "the late acknowledgement left verification_pending set without the lock ...", stray)
    r.crit("cleared", "... and the next 1 s tick cleared it (invariant gate)", not s.g["verification_pending"], s.flags())
    reads0 = len(s.rtc_wire("read"))
    s.run_for(60_000)
    r.crit("inert", "it revived nothing: no verification read, no write, no success, no failure count",
           len(s.rtc_write_attempts()) == n_w and s.g["corrections_since_boot"] == n_ok and s.g["failed_corrections"] == n_fail
           and len(s.rtc_wire("read")) - reads0 <= 1 and s.released(), s.flags())
    return inv(r, s)


def sc_verify(text, outcome) -> R:
    s = X.make_rig(text, oracle=True)
    if outcome == "invalid":
        s.inner_read_override = lambda a, c, v: [0xFFFF, 0xFFFF, 0xFFFF] if (a == 22 and s.g["verification_read_active"]) else v
    else:
        X.bind_outcomes(s, X.outcomes(verify=outcome))
    s.run_for(300_000)
    r = R(f"R07 verification read {outcome}", s)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    if outcome == "timeout":
        r.crit("breaker", f"a lost verification read is released by the deadline breaker {D / 1000:.0f}-{D / 1000 + 1:.0f} s after "
               "the lock was taken", q is not None and rel is not None and D <= rel - q <= D + 1000, f"{s.flags()}")
    else:
        r.crit("bounded", "released within 30 s through the retry path (two writes, then FAILED + cooldown)",
               q is not None and rel is not None and rel - q <= 30_000 and len(s.rtc_write_attempts()) == 2
               and any(x.startswith("FAILED after communication errors") for x in s.results(q)), f"q={q} rel={rel} {s.flags()}")
    r.crit("count", "failed_corrections 1, no success, no flag left set",
           s.g["failed_corrections"] == 1 and s.g["corrections_since_boot"] == 0 and s.released(), s.flags())
    return inv(r, s)


def sc_not_applied(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write="ack_not_applied"))
    s.run_for(300_000)
    r = R("R12 the inverter acknowledges but ignores the write", s)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    res = s.results(q or 0)
    r.crit("failed", "two writes, two verification reads, 'FAILED after retries' + cooldown within 30 s - never 'Verified'",
           q is not None and rel is not None and rel - q <= 30_000 and len(s.rtc_write_attempts()) == 2
           and len([w for w in s.rtc_wire("read") if w.t_queued > q]) >= 2 and any(x.startswith("FAILED after retries") for x in res)
           and not any(x.startswith("Verified") for x in res) and s.g["corrections_since_boot"] == 0, res)
    return inv(r, s)


def sc_ntp_abort(text=None) -> R:
    s = X.make_rig(text, intervals=("rtc_tick",))
    s.run_for(10_000)
    s.poke("correction_in_progress", True)
    s.poke("correction_attempt", 1)
    if "rtc_txn_since_ms" in s.g:
        s.poke("rtc_txn_since_ms", s.millis())
    s.ntp_valid = False
    s.start_script("write_inverter_rtc")
    r = R("R13 NTP-abort branch of write_inverter_rtc", s)
    r.crit("released", "write_inverter_rtc with the lock taken and NTP not confirmed releases at once (cip / asp / vp / vra / cfp false)",
           s.released(), s.flags())
    r.crit("text", "result 'Correction cancelled - confirmed NTP time unavailable'",
           str(s.ent("last_correction_result").state) == "Correction cancelled - confirmed NTP time unavailable",
           s.ent("last_correction_result").state)
    r.crit("nocount", "no failure count, no cooldown, nothing written", s.g["failed_corrections"] == 0 and s.g["cooldown_until_ms"] == 0
           and not s.rtc_write_attempts(), s.flags())
    s.run_for(120_000)
    r.crit("stays", "still released 120 s later (no wedge)", s.released(), s.flags())
    return inv(r, s)


def sc_deferral(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    r = R("R14 write-mutex deferral", s)
    ok = X.run_until(s, lambda sm: sm.g["correction_in_progress"], 200_000, 20)
    q = s.now_ms
    s.poke("manual_write_in_progress", True)  # another owner took the write mutex between the queue and the dispatch tick
    s.run_for(5_000)
    r.crit("deferred", "the dispatch defers: released without a write, 'Deferred - inverter write path busy; will retry'",
           ok and s.released() and not s.rtc_write_attempts()
           and str(s.ent("last_correction_result").state).startswith("Deferred - inverter write path busy"), s.flags())
    s.poke("manual_write_in_progress", False)
    s.run_for(420_000)
    q2 = queues(s, q + 1)
    r.crit("requeued", "later re-queued only by the policy (a fresh confirming regular read) and then verified",
           bool(q2) and s.g["corrections_since_boot"] == 1 and (not s.oracle_on or (oracle_at(s, q2[0]) or {}).get("action") == rp.ACT_CORRECT),
           f"{q2} {s.flags()}")
    return inv(r, s)


def sc_auto_off(text, phase) -> R:
    s = X.make_rig(text, oracle=True)
    if phase == "write":
        X.bind_outcomes(s, X.outcomes(write=spec("ok", 2000)))
    elif phase == "vra":
        X.bind_outcomes(s, X.outcomes(verify=spec("ok", 1500)))
    elif phase == "cfp":
        X.bind_outcomes(s, X.outcomes(write=["error", "ok"]))
    preds = {"asp": lambda sm: sm.g["auto_sync_pending"],
             "write": lambda sm: isinstance(sm.hub.in_flight_frame, X.WriteFrame),
             "vp": lambda sm: sm.g["verification_pending"],
             "vra": lambda sm: sm.g["verification_read_active"] and sm.hub.in_flight_frame is not None,
             "cfp": lambda sm: sm.g["comm_failure_pending"]}
    r = R(f"R15 Automatic Clock Sync off ({phase})", s)
    reached = X.run_until(s, preds[phase], 200_000, 20)
    t_off = s.now_ms
    n_w = len(s.rtc_write_attempts())
    s.operator_switch("automatic_clock_sync", False)
    s.run_for(40_000)
    rel = X.release_time(s, t_off - 30_000)
    expect = {"asp": "Correction cancelled", "cfp": "FAILED after communication errors"}.get(phase, "Verified OK")
    r.crit("reached", f"precondition: the correction reached phase {phase}", reached)
    r.crit("released", f"released within 30 s ('{expect}'), no further FC16 22-24 after the switch turned off",
           s.released() and rel is not None and rel - t_off <= 30_000 and len(s.rtc_write_attempts()) == n_w
           and str(s.ent("last_correction_result").state).startswith(expect), f"{s.flags()} writes {n_w}->{len(s.rtc_write_attempts())}")
    if phase == "asp":
        s.operator_switch("automatic_clock_sync", True)
        s.run_for(420_000)
        r.crit("again", "switched on again, the policy corrects normally", s.g["corrections_since_boot"] == 1, s.flags())
    return inv(r, s)


def sc_manual(text, variant) -> R:
    r = R(f"R16 manual Sync ({variant})")
    if variant == "idle":
        s = X.make_rig(text, oracle=True)
        s.run_for(40_000)
        t = s.millis()
        s.press_button("sync_inverter_clock")
        manual = bool(s.g["correction_is_manual"]) and bool(s.g["correction_in_progress"])
        s.run_for(30_000)
        r.crit("runs", "Sync while idle takes the lock (manual), writes at once, verifies and releases",
               manual and s.g["corrections_since_boot"] == 1 and len(s.rtc_write_attempts()) == 1 and s.released()
               and not s.g["correction_is_manual"], s.flags())
        r.crit("stamp", "the Sync press stamped rtc_txn_since_ms = millis() of the press", s.g.get("rtc_txn_since_ms") == t,
               s.g.get("rtc_txn_since_ms"))
    elif variant == "cooldown":
        s = X.make_rig(text, oracle=True)
        X.bind_outcomes(s, X.outcomes(write=["error", "error", "ok"]))
        X.run_until(s, lambda sm: sm.first_result_time("FAILED") is not None, 200_000)
        armed = s.g["cooldown_until_ms"] != 0
        s.press_button("sync_inverter_clock")
        cleared = s.g["cooldown_until_ms"] == 0
        s.run_for(30_000)
        r.crit("runs", "Sync during the cooldown clears it and corrects (verified)", armed and cleared and s.g["corrections_since_boot"] == 1,
               s.flags())
    elif variant == "during_auto":
        s = X.make_rig(text, oracle=True)
        X.run_until(s, lambda sm: sm.g["verification_pending"], 200_000, 20)
        s.press_button("sync_inverter_clock")
        refused = not s.g["correction_is_manual"]
        s.run_for(30_000)
        r.crit("refused", "Sync during an automatic transaction is refused: no second write, the automatic one completes",
               refused and len(s.rtc_write_attempts()) == 1 and s.g["corrections_since_boot"] == 1, s.flags())
    elif variant == "auto_off":
        s = X.make_rig(text, oracle=True, auto_sync=False)
        X.bind_outcomes(s, X.outcomes(write=["ack_not_applied", "ok"]))
        s.run_for(40_000)
        s.press_button("sync_inverter_clock")
        s.run_for(60_000)
        r.crit("retry", "with Automatic Clock Sync off a manual correction still retries once (2 writes) and verifies",
               len(s.rtc_write_attempts()) == 2 and s.g["corrections_since_boot"] == 1, s.flags())
    else:  # lost callback
        s = X.make_rig(text, oracle=True)
        X.bind_outcomes(s, X.outcomes(write="timeout_lost"))
        s.run_for(40_000)
        t = s.now_ms
        s.press_button("sync_inverter_clock")
        s.run_for(150_000)
        rel = X.release_time(s, t)
        r.crit("breaker", f"a manual correction with a lost callback is released by the breaker {D / 1000:.0f}-{D / 1000 + 1:.0f} s "
               "after the Sync press (rtc_txn_since_ms stamped there)", rel is not None and D <= rel - t <= D + 1000, s.flags())
    r.sim = s
    return inv(r, s)


BREAKER_STATES = {
    "S1": "a queued write waiting for a quiet bus (auto_sync_pending)",
    "S2": "an FC16 frame that may still be outstanding (lost write callback)",
    "S3": "a write acknowledged, its verification not yet due (verification_pending)",
    "S4": "a verification read that may still be outstanding (verification_read_active, lost read callback)",
    "S5": "a failure terminal not yet consumed by the 1 s tick (comm_failure_pending)",
}


def sc_breaker_state(text, state) -> R:
    """The deadline breaker on a BUSY bus, per RTC state. Between frames (S1 / S3 / S5) no RTC callback can arrive, so it releases at
    the deadline even while another master holds the bus; with a frame possibly outstanding (S2 / S4) it holds until the bus is quiet
    and then releases at the first tick. Every window below is placed relative to the lock time q (ticks at q + 880 + k * 1000)."""
    s = X.make_rig(text, oracle=True)
    if state == "S2":
        X.bind_outcomes(s, X.outcomes(write="timeout_lost"))
    elif state == "S4":
        X.bind_outcomes(s, X.outcomes(verify="timeout"))
    elif state == "S5":
        X.bind_outcomes(s, X.outcomes(write=[spec("error", 1500), "ok"]))
    X.run_until(s, lambda sm: sm.g["correction_in_progress"], 200_000, 20)
    q = X.queue_time(s)
    deadline_tick = q + 880 + 1000 * ((D - 880 + 999) // 1000)
    holds = {"S1": [(q + 50, 150_000)],
             "S2": [(q + 80_000, 60_000)],
             "S3": [(q + 50, 80_450), (q + 81_500, 60_000)],
             "S4": [(q + 80_000, 60_000)],
             "S5": [(q + 50, 87_450), (q + 90_500, 30_000)]}[state]
    for a, d in holds:
        s.hold_bus(d, at=a)
    s.run_until(q + 160_000)
    rel = X.release_time(s, q)
    a_last, d_last = holds[-1]
    busy_at_rel = rel is not None and a_last <= rel < a_last + d_last
    r = R(f"R18 breaker on a busy bus, {state}: {BREAKER_STATES[state]}", s)
    if state in ("S1", "S3", "S5"):
        r.crit("releases", f"between frames no RTC callback can arrive: released at the deadline tick ({D / 1000:.0f}-"
               f"{D / 1000 + 1:.0f} s) although the bus is busy", rel is not None and rel == deadline_tick and busy_at_rel,
               f"held {(rel - q) if rel else None} ms, busy {busy_at_rel}")
    else:
        r.crit("holds", "with an RTC frame possibly outstanding it holds while the bus is busy, then releases at the first tick on a "
               "quiet bus", rel is not None and a_last + d_last <= rel <= a_last + d_last + 1_000,
               f"held {(rel - q) if rel else None} ms, bus busy until {(a_last + d_last - q)} ms")
    r.crit("count", "ABORTED, failed_corrections 1, 5 min cooldown, every RTC flag released",
           s.first_result_time("ABORTED", q) is not None and s.g["failed_corrections"] == 1 and s.g["cooldown_until_ms"] != 0
           and s.released(), s.flags())
    return inv(r, s)


def sc_breaker_scope(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(write="timeout_lost"))
    r = R("R18 breaker scope", s)
    X.run_until(s, lambda sm: sm.g["correction_in_progress"], 200_000, 20)
    q = s.now_ms
    s.run_for(30_000)
    others = ("manual_write_in_progress", "free_power_operation_in_progress", "dump_operation_in_progress", "reg244_apply_in_progress",
              "fallback_profile_op_in_progress")
    for f in others:
        s.poke(f, True)
    snap = dict(s.g)
    s.run_for(D)
    rel = X.release_time(s, q)
    changed = sorted(k for k in s.g if s.g[k] != snap[k])
    r.crit("released", "the breaker released the RTC lock (ABORTED, failed_corrections 1, 5 min cooldown)",
           rel is not None and s.g["failed_corrections"] == 1 and s.g["cooldown_until_ms"] != 0, s.flags())
    r.crit("scope", "it left the write mutex and every other domain's flag set (they are not RTC state)", all(s.g[f] for f in others))
    r.crit("only", "every global that changed is RTC state", set(changed) <= X.RTC_ALLOWED, sorted(set(changed) - X.RTC_ALLOWED))
    return inv(r, s)


def sc_breaker_slow(text=None) -> R:
    rnd = random.Random(17)
    s = X.make_rig(text, intervals=("rtc_read", "rtc_tick", "telemetry", "config", "catchup"), oracle=True)
    s.hub.turnaround_ms = 600  # ESPHome's default turnaround: tx_blocked() stays true 600 ms after every frame
    slow = spec("ok", 2000)
    poll_slow = (lambda sim: spec(rnd.choice(("ok", "no_response")), 2000))  # 2 s = send_wait_time: every poll frame at its worst
    X.bind_outcomes(s, X.outcomes(write=[spec("no_response_lost", 2000), spec("ack_not_applied", 2000), slow], verify=slow,
                                  regular=slow, poll={a: poll_slow for a in (59, 150, 200, 241, 330)}))
    for _k in range(12):
        s.at(s.now_ms + rnd.randint(0, 600_000), lambda sim: sim.press_button("read_inverter_clock"))
    s.run_for(700_000)
    r = R("R18 slow healthy transactions (2 s frames, 600 ms turnaround, both polls, HA presses)", s)
    holds = [(b - a) for a, b in s.lock_periods() if b is not None]
    r.crit("healthy", "the slow transactions end by their own terminals (verified, or FAILED + cooldown after the retry) - never by "
           "the deadline", bool(holds) and not any(x.startswith("ABORTED") for x in s.results()) and s.released(), s.results()[-3:])
    r.crit("margin", f"the worst legitimate lock hold stays far inside the {D / 1000:.0f} s deadline (< {(D - 45_000) / 1000:.0f} s)",
           bool(holds) and max(holds) < D - 45_000, holds)
    return inv(r, s, i2=False)


def sc_ha_refused(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    X.bind_outcomes(s, X.outcomes(verify=spec("ok", 1500)))
    r = R("R19 HA press refused during the verification read", s)
    reached = X.run_until(s, lambda sm: sm.g["verification_read_active"] and sm.hub.in_flight_frame is not None, 200_000, 20)
    pre = s.flags()
    s.queue_frames("not_sent")  # the next read - the HA press - is refused at the door (on_not_sent, synchronous)
    s.press_button("read_inverter_clock")
    post = s.flags()
    r.crit("untouched", "an HA press of Read Inverter Clock refused at the door (no verification marker) leaves the running "
           "correction untouched", reached and post["vra"] and not post["cfp"] and post["att"] == pre["att"], f"{pre} -> {post}")
    s.run_for(30_000)
    r.crit("completes", "the correction completes Verified OK with exactly one write",
           s.g["corrections_since_boot"] == 1 and len(s.rtc_write_attempts()) == 1, s.flags())
    return inv(r, s, i2=False)


def sc_ha_during_vp(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    r = R("R19 HA read while the correction waits for its verification", s)
    X.run_until(s, lambda sm: sm.g["verification_pending"], 200_000, 20)
    t = s.now_ms
    s.press_button("read_inverter_clock")
    s.run_for(30_000)
    rd = [x for x in s.oracle_reads if x["t"] >= t]
    r.crit("busy", "the HA read is a regular read the policy holds (busy): nothing is queued twice",
           (not s.oracle_on or (bool(rd) and rd[0]["reason"] == rp.R_BUSY)) and len(s.rtc_write_attempts()) == 1, rd[:1])
    r.crit("completes", "the correction completes Verified OK", s.g["corrections_since_boot"] == 1 and s.released(), s.flags())
    return inv(r, s, i2=False)


def sc_boot_no_ntp(text=None) -> R:
    s = X.make_rig(text, ntp=False, oracle=True)
    r = R("R21 boot without NTP", s)
    s.run_for(200_000)
    r.crit("nowrite", "while NTP has never synchronised there is no lock and no write (reads wait for NTP)",
           not s.cip_edges and not s.rtc_write_attempts() and s.released(), s.flags())
    s.ntp_sync()
    s.run_for(150_000)
    r.crit("after", "after the first NTP synchronisation the policy corrects normally", s.g["corrections_since_boot"] == 1, s.flags())
    return inv(r, s)


def sc_wrap(text, kind) -> R:
    s = X.make_rig(text, oracle=True)
    if kind == "breaker":
        X.bind_outcomes(s, X.outcomes(write="timeout_lost"))
    elif kind == "cooldown":
        X.bind_outcomes(s, X.outcomes(write=["error", "error", "ok"]))
    s.run_for(40_000)
    # millis() wraps 3 s after the queue (read 2 is due 50 s after this point, its response 120 ms later)
    s.rebase_clock((1 << 32) - 3_000 - 50_120)
    s.run_for(100_000 if kind == "success" else (150_000 if kind == "breaker" else 520_000))
    r = R(f"R22 millis() wrap mid-transaction ({kind})", s)
    q = X.queue_time(s)
    wrapped = q is not None and (q & 0xFFFFFFFF) > 0xFFFF0000 and (s.millis() < 0x10000000)
    r.crit("wrap", "precondition: the lock was taken just before millis() wrapped", wrapped, f"q={q}")
    rel = X.release_time(s, q or 0)
    if kind == "success":
        acks = [a for a in s.write_acks if q is not None and a >= q]
        vread = [w for w in s.rtc_wire("read") if acks and w.t_queued > acks[0]]
        r.crit("verified", "the verification read is due 10 s after the acknowledgement across the wrap, and verifies",
               s.g["corrections_since_boot"] == 1 and bool(vread) and 10_000 <= vread[0].t_queued - acks[0] <= 11_100, s.flags())
    elif kind == "breaker":
        r.crit("breaker", f"the breaker fires {D / 1000:.0f}-{D / 1000 + 1:.0f} s after the lock across the wrap (not at once, not never)",
               rel is not None and D <= rel - q <= D + 1000, f"held {(rel - q) if (q and rel) else None}")
    else:
        f = s.first_result_time("FAILED", q or 0)
        later = [a.t for a in s.rtc_write_attempts() if f is not None and a.t > f]
        r.crit("cooldown", "the 5 min cooldown armed across the wrap is honoured, then corrections resume",
               f is not None and bool(later) and later[0] >= f + COOLDOWN_MS and s.g["corrections_since_boot"] == 1, later)
    return inv(r, s)


def sc_quiet_dispatch(text=None) -> R:
    s = X.make_rig(text, oracle=True)
    r = R("R23 the queued write waits for a quiet bus", s)
    X.run_until(s, lambda sm: sm.g["correction_in_progress"], 200_000, 20)
    t = s.now_ms
    s.inject_foreign_frame(9002, 1, latency_ms=3000)  # another master's frame is on the wire for 3 s
    s.run_for(30_000)
    w = s.rtc_write_attempts()
    r.crit("waits", "the FC16 frame is queued only once the bus is quiet (never behind / during another frame)",
           bool(w) and not w[0].hub_busy and w[0].t >= t + 3000, [(x.t - t, x.hub_busy) for x in w])
    r.crit("completes", "and the correction completes Verified OK", s.g["corrections_since_boot"] == 1, s.flags())
    return inv(r, s)


def sc_inject(text, flag) -> R:
    s = X.make_rig(text, offset_s=-2.0, oracle=True)
    s.run_for(45_000)
    s.poke(flag, True)
    if flag == "verification_pending":
        s.poke("verification_due_ms", s.millis())
    s.run_for(1_100)
    cleared = not s.g[flag]
    s.run_for(120_000)
    r = R(f"I1 stray {flag} without the lock", s)
    r.crit("cleared", f"a stray {flag} with correction_in_progress false is cleared by the next 1 s tick", cleared)
    r.crit("inert", "it causes no write, no verification and no success",
           not s.rtc_write_attempts() and s.g["corrections_since_boot"] == 0 and s.released(), s.flags())
    return inv(r, s)


W_OUT = (("ok", 40), ("ack_not_applied", 8), ("error", 8), ("no_response_landed", 6), ("no_response_lost", 6),
         ("custom_response", 8), ("not_sent", 8), ("timeout_landed", 3), ("timeout_lost", 3))
V_OUT = (("ok", 55), ("error", 8), ("no_response", 8), ("not_sent", 8), ("custom_response", 8), ("timeout", 4))
G_OUT = (("ok", 85), ("error", 4), ("no_response", 4), ("not_sent", 3), ("custom_response", 3), ("timeout", 1))


def _wpick(rnd, table):
    x = rnd.uniform(0, sum(w for _o, w in table))
    for o, w in table:
        x -= w
        if x <= 0:
            return o
    return table[-1][0]


def fuzz_one(seed: int):
    rnd = random.Random(seed)
    off = rnd.choice((-1, 1)) * rnd.randint(61, 250)
    s = X.make_rig(None, offset_s=off, rate=rnd.choice((0.0, -7 / 60, 3 / 60)), image_period_ms=rnd.choice((0, 10_000)),
                   image_phase_ms=rnd.randint(0, 9_999), oracle=True, seed=seed)
    lost = []

    def gen(table, kind):
        def f(sim):
            o = _wpick(rnd, table)
            if o.startswith("timeout"):
                lost.append((sim.now_ms, kind))
            return spec(o, rnd.randint(40, 1_900))
        return f
    X.bind_outcomes(s, X.outcomes(write=gen(W_OUT, "write"), verify=gen(V_OUT, "verify"), regular=gen(G_OUT, "regular")))
    t0 = s.now_ms
    end = t0 + 420_000
    t = t0
    while True:
        t += int(rnd.expovariate(1 / 70_000))
        if t >= end - 30_000:
            break
        s.at(t, lambda sim: sim.press_button("read_inverter_clock"))
    held = 0
    if rnd.random() < 0.3:
        a, d = rnd.randint(t0 + 60_000, end - 120_000), rnd.randint(3_000, 20_000)
        held += d
        s.hold_bus(d, at=a)
    if rnd.random() < 0.25:
        a, d = rnd.randint(t0 + 60_000, end - 150_000), rnd.randint(2_000, 60_000)
        s.at(a, lambda sim: sim.operator_switch("automatic_clock_sync", False))
        s.at(a + d, lambda sim: sim.operator_switch("automatic_clock_sync", True))
    if rnd.random() < 0.2:
        a, d = rnd.randint(t0 + 60_000, end - 150_000), rnd.randint(1_000, 15_000)
        s.at(a, lambda sim: sim.poke("manual_write_in_progress", True))
        s.at(a + d, lambda sim: sim.poke("manual_write_in_progress", False))
    s.run_until(end)
    return s, held, lost, end


def sc_fuzz(runs: int = 300) -> R:
    r = R(f"R20 seeded outcome fuzz ({runs} runs x 7 min)")
    bad_live, bad_writes, bad_inv, bad_abort, n_locks, n_ok, n_fail, n_reads = [], [], [], [], 0, 0, 0, 0
    for seed in range(runs):
        s, held, lost, end = fuzz_one(1000 + seed)
        bound = D + held + 3_000
        for a, b in s.lock_periods():
            n_locks += 1
            if (b is None and a < end - bound) or (b is not None and b - a > bound):
                bad_live.append((seed, a, b))
            hi = b if b is not None else end
            if len([w for w in s.rtc_write_attempts() if a <= w.t <= hi]) > 2:
                bad_writes.append((seed, a))
        x = R("tmp")
        inv(x, s, i2=False)
        if not x.ok:
            bad_inv.append((seed, x.items[-1][3][:160]))
        if any(v.startswith("ABORTED") for v in s.results()) and not lost and not held:
            bad_abort.append(seed)
        n_ok += s.g["corrections_since_boot"]
        n_fail += s.g["failed_corrections"]
        n_reads += len(s.oracle_reads)
    r.crit("live", f"liveness: every one of {n_locks} lock periods ended within the deadline + held-bus time + one frame",
           not bad_live, bad_live[:3])
    r.crit("writes", "at most two FC16 22-24 attempts per correction (one retry)", not bad_writes, bad_writes[:3])
    r.crit("inv", f"I1 / I3 / I6 / audit / wire / NVS / policy oracle hold in every run ({n_ok} verified successes, {n_fail} failures, "
           f"{n_reads} oracle-checked regular reads)", not bad_inv, bad_inv[:2])
    r.crit("abort", "the breaker fired only in runs with a lost callback or a held bus", not bad_abort, bad_abort[:5])
    return r


# ============================================================================================================================
# [2] policy wiring (the oracle on every regular read + behaviour; numbers derived from rtc_policy)
# ============================================================================================================================
def sc_spike(text=None) -> R:
    s = X.make_rig(text, offset_s=-2.0, oracle=True)
    t_read = s.now_ms + 90_000  # the second periodic read
    e = N.BG + 24
    s.at(t_read - 500, lambda sm: sm.rtc.override_words.append(X.pack_rtc(sm.clock.local_s(t_read) - e - 2)))
    s.run_for(300_000)
    r = R("PW1 one stale read", s)
    rd = oracle_at(s, t_read + 120)
    r.crit("none", f"one stale read showing about -{e} s (above the {N.BG} s background threshold) never queues a correction",
           not queues(s) and not s.rtc_write_attempts(), queues(s))
    if s.oracle_on:
        r.crit("reason", "the policy held it: the previous read does not confirm it", rd is not None and rd["reason"] == rp.R_UNCONFIRMED, rd)
    return inv(r, s)


def sc_frozen(text=None) -> R:
    s = X.make_rig(text, offset_s=-2.0, oracle=True)
    s.run_for(45_000)
    s.rtc.freeze(s.now_ms, s.now_ms + 200_000)  # the register image repeats the same words for 200 s
    s.run_for(400_000)
    r = R("PW3 frozen register image", s)
    frozen_reads = [x for x in s.oracle_reads if x["prev_valid"] and abs(x["err"]) >= N.BG and abs(x["prev_err"]) >= N.BG
                    and x["reason"] == rp.R_UNCONFIRMED]
    r.crit("none", "a frozen image (identical words on consecutive reads, error growing 60 s per read) never confirms: no correction",
           not queues(s) and not s.rtc_write_attempts(), queues(s))
    if s.oracle_on:
        r.crit("reason", "two over-threshold reads of the frozen image were held as unconfirmed (inverter did not advance)",
               bool(frozen_reads), len(frozen_reads))
    return inv(r, s)


def sc_quiet(text, which) -> R:
    tou, (qa, qb) = (X.GOLD_TOU, N.QW_HH) if which == "half-hour" else (TOU_1635, N.QW_TOU)
    s = X.make_rig(text, local=local_of(qa - 600 - 30 + 15), offset_s=-2.0, tou=tou, oracle=True)
    s.at(t_of(s, qa + 5), lambda sm: sm.rtc.set_offset(-(N.BG + 30)))
    s.run_until(t_of(s, qb + 150))
    r = R(f"PW4 quiet window ({which}, [{qa // 3600:02d}:{qa // 60 % 60:02d}:{qa % 60:02d}, {qb // 3600:02d}:{qb // 60 % 60:02d}:"
          f"{qb % 60:02d}) from rtc_policy)", s)
    tq = [s.clock.tod(t) for t in queues(s)]
    r.crit("hold", f"a confirmed -{N.BG + 30} s error appearing inside the quiet window is not corrected inside it",
           not any(qa <= x < qb for x in tq), tq)
    r.crit("follows", "it is corrected at the first confirming regular read after the window", bool(tq) and qb <= tq[0] < qb + 61, tq)
    if s.oracle_on:
        r.crit("reason", "the policy reported quiet-window holds inside it",
               any(x["reason"] == rp.R_QUIET for x in s.oracle_reads if qa <= x["tod"] < qb))
    return inv(r, s)


def sc_lease(text=None) -> R:
    s = X.make_rig(text, offset_s=-2.0, oracle=True)
    s.run_for(45_000)
    s.poke("free_power_active_persisted", True)
    s.rtc.set_offset(-(N.BG + 30))
    s.run_for(300_000)
    r = R("PW5 energy transaction", s)
    r.crit("hold", f"an active energy transaction holds a confirmed -{N.BG + 30} s error (no correction)", not queues(s), queues(s))
    if s.oracle_on:
        r.crit("reason", "the policy reported the energy-transaction hold", any(x["reason"] == rp.R_LEASE for x in s.oracle_reads))
    t = s.now_ms
    s.rtc.set_offset(-(N.LARGE + 100))
    s.run_for(200_000)
    q = queues(s, t)
    rd = oracle_at(s, q[0]) if q else None
    r.crit("large", f"an error >= {N.LARGE} s (confirmed) is corrected even during the transaction (reason large)",
           bool(q) and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_LARGE)), rd)
    return inv(r, s)


def sc_precision(text, served=False) -> R:
    pa, pb = N.PW_16
    s = X.make_rig(text, local=local_of(pa - 600 - 30 + 15), offset_s=-2.0, oracle=True)
    ep = (N.PT + N.BG) // 2
    t_step = t_of(s, pa - 300)
    s.at(t_step, lambda sm: sm.rtc.set_offset(-ep))
    key = rp.decide(pin(pa + 15, -ep, -ep)).precision_key
    if served and "rtc_precision_served" in s.g:
        s.poke("rtc_precision_served", key)
    s.run_until(t_of(s, X.hms(16, 1, 30)))
    r = R(f"PW6 precision window before the 16:00 TOU zone start ([{pa // 3600:02d}:{pa // 60 % 60:02d}:{pa % 60:02d}, "
          f"{pb // 3600:02d}:{pb // 60 % 60:02d}:{pb % 60:02d}) from rtc_policy){' already served' if served else ''}", s)
    qs = [(t, s.clock.tod(t)) for t in queues(s)]
    if served:
        r.crit("once", "with that boundary already served no precision correction is made (once per boundary)", not qs, qs)
        if s.oracle_on:
            rd = [x for x in s.oracle_reads if pa <= x["tod"] < pb]
            r.crit("reason", "the policy judged the read in the window against the background threshold (within)",
                   bool(rd) and all(x["reason"] == rp.R_WITHIN for x in rd), rd)
        return inv(r, s)
    before = [x for t, x in qs if t >= t_step and x < pa]
    inside = [(t, x) for t, x in qs if pa <= x < pb]
    r.crit("outside", f"a -{ep} s error (below the {N.BG} s background threshold) is not corrected before the precision window",
           not before, before)
    rd = oracle_at(s, inside[0][0]) if inside else None
    r.crit("inside", "it is corrected inside the precision window (reason precision)",
           len(inside) == 1 and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_PRECISION)), f"{inside} {rd}")
    if s.oracle_on:
        r.crit("served", "rtc_precision_served records that boundary (the oracle's precision key)",
               s.g["rtc_precision_served"] == key and rd is not None and rd["pkey"] == key, (s.g["rtc_precision_served"], key))
    w = [a for a in s.rtc_write_attempts() if inside and a.t >= inside[0][0]]
    r.crit("lands", "the write lands before the TOU zone start", bool(w) and s.clock.tod(w[0].t) < X.hms(16, 0), [s.clock.tod(a.t) for a in w])
    return inv(r, s)


def sc_large_precision(text, variant) -> R:
    """M1: a large error (>= kLargeErrorS) is never a precision correction - it needs two confirming reads even inside a precision
    window (and even under an energy transaction, which a large error is exempt from)."""
    pa, pb = N.PW_16
    qa, qb = N.QW_16
    s = X.make_rig(text, local=local_of(pa - 600 - 30 + 15), offset_s=-2.0, oracle=True)  # reads at pa + 15 + 60 k
    e = N.LARGE + 100
    t_step = t_of(s, pa - (90 if variant == "two" else 30))
    s.at(t_step, lambda sm: sm.rtc.set_offset(-e))
    if variant == "lease":
        s.poke("free_power_active_persisted", True)
    s.run_until(t_of(s, qb + 150))
    q = queues(s, t_step)
    tq = [s.clock.tod(t) for t in q]
    rd = oracle_at(s, q[0]) if q else None
    r = R(f"PW12 a -{e} s error inside the precision window ({variant})", s)
    if variant == "two":
        r.crit("large", "two large reads (the second inside the precision window) correct with reason large, not precision",
               bool(tq) and pa <= tq[0] < pb and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_LARGE)), f"{tq} {rd}")
    else:
        single = [x for x in s.oracle_reads if pa <= x["tod"] < pb]
        r.crit("single", "ONE large read inside the precision window does not correct" + (" (the energy transaction does not matter)"
               if variant == "lease" else ""), not any(pa <= x < pb for x in tq)
               and (not s.oracle_on or (bool(single) and all(x["reason"] == rp.R_UNCONFIRMED for x in single))), f"{tq} {single[:1]}")
        r.crit("confirmed", "the second large read (after the boundary's quiet window) corrects it, reason large",
               bool(tq) and qb <= tq[0] < qb + 61 and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_LARGE)), f"{tq} {rd}")
    return inv(r, s)


def sc_zone_cross(text, which, sign) -> R:
    """L3: a positive error below kLargeErrorS that would step the inverter back across a boundary it has already passed (a half hour
    or a TOU zone start in (t, t + err]) is held; it is corrected after the boundary. A negative error there is not held."""
    b, tou = (X.hms(10, 30), X.GOLD_TOU) if which == "half-hour" else (X.hms(16, 35), TOU_1635)
    qa, qb = N.quiet_window(b, tou)
    e = sign * (N.BG + 60)
    s = X.make_rig(text, local=local_of(b - 645), offset_s=-2.0, tou=tou, oracle=True)  # reads at b - 15 - 60 k
    # the first read (within 4.5 min of b) at which rtc_policy says a +|e| error would step back across a boundary
    held_tod = next(t for t in range(b - 255, b, 60) if rp.would_step_back_across(pin(t, abs(e), abs(e), tou=tou)))
    t_step = t_of(s, held_tod - 115)
    s.at(t_step, lambda sm: sm.rtc.set_offset(e))
    s.run_until(t_of(s, qb + 150))
    q = queues(s, t_step)
    tq = [s.clock.tod(t) for t in q]
    rd = oracle_at(s, q[0]) if q else None
    at_held = [x for x in s.oracle_reads if x["tod"] == held_tod]
    r = R(f"PW13 zone cross at the {'10:30 half hour' if which == 'half-hour' else '16:35 TOU zone start'}, error {e:+d} s", s)
    if sign > 0:
        r.crit("held", f"the +{e} s error is held at the {held_tod // 3600:02d}:{held_tod // 60 % 60:02d}:{held_tod % 60:02d} read "
               "(the boundary lies within the error: reason zone-cross) and nothing is corrected before the boundary",
               not any(x < b for x in tq) and (not s.oracle_on or (bool(at_held) and at_held[0]["reason"] == rp.R_ZONE_CROSS)),
               f"{tq} {at_held[:1]}")
        r.crit("after", "it is corrected at the first confirming read after the boundary's quiet window",
               bool(tq) and qb <= tq[0] < qb + 61 and (not s.oracle_on or (rd is not None and rd["action"] == rp.ACT_CORRECT)), tq)
    else:
        r.crit("notheld", f"a {e} s error at the same read is not held: it is corrected there, before the boundary",
               bool(tq) and tq[0] == held_tod and (not s.oracle_on or (rd is not None and rd["reason"] != rp.R_ZONE_CROSS)), f"{tq} {rd}")
    return inv(r, s)


def sc_boot(text, variant) -> R:
    if variant == "A":
        s = X.make_rig(text, offset_s=-(N.BOOT + 5), oracle=True)
        t0 = s.now_ms
        s.run_for(200_000)
        r = R(f"PW7 boot alignment (-{N.BOOT + 5} s at boot)", s)
        q = queues(s)
        rd = oracle_at(s, q[0]) if q else None
        r.crit("two", f"at boot an error >= the {N.BOOT} s threshold is corrected by the alignment after two confirming reads, not one",
               bool(q) and 90_000 <= q[0] - t0 < 91_000 and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_BOOT)),
               f"{[x - t0 for x in q]} {rd}")
        if s.oracle_on:
            r.crit("aligned", "rtc_boot_aligned is set", bool(s.g["rtc_boot_aligned"]))
        return inv(r, s)
    s = X.make_rig(text, offset_s=-(N.BOOT - 5), oracle=True)
    s.run_for(45_000)
    r = R(f"PW7 boot alignment (-{N.BOOT - 5} s at boot)", s)
    aligned = not queues(s) and (not s.oracle_on or bool(s.g["rtc_boot_aligned"]))
    e = (N.BOOT + N.BG) // 2
    s.rtc.set_offset(-e)
    s.run_for(600_000)
    r.crit("aligned", "below the threshold the first evaluation settles the boot alignment without a write", aligned)
    r.crit("floor", f"afterwards a -{e} s error (above the {N.BOOT} s threshold, below the {N.BG} s background floor) is never corrected "
           "outside a precision window", not queues(s), queues(s))
    return inv(r, s)


def sc_min_gap(text=None) -> R:
    s = X.make_rig(text, offset_s=75.0, rate=0.5, oracle=True)  # a fast inverter (+30 s/min): never classified as frozen
    s.run_for(720_000)
    r = R("PW8 background gap", s)
    q = queues(s)
    bad = []
    for a, b in zip(q, q[1:]):
        rd = oracle_at(s, b)
        background = rd is None or rd["reason"] == rp.R_BACKGROUND
        if background and b - a < N.GAP:
            bad.append((a, b, b - a))
    r.crit("gap", f"every background correction comes at least {N.GAP / 1000:.0f} s after the previous automatic one",
           len(q) >= 2 and not bad, f"{[b - a for a, b in zip(q, q[1:])]}")
    if s.oracle_on:
        r.crit("held", "the policy reported min-gap holds in between", any(x["reason"] == rp.R_MIN_GAP for x in s.oracle_reads))
    return inv(r, s)


def _freezes(s, rnd, start, end):
    t = start
    while True:
        t += rnd.randint(600_000, 960_000)
        if t >= end:
            return
        s.rtc.freeze(t, t + rnd.randint(20_000, 60_000))


def sc_night(text, tou=TOU_DAY, hours=8, start=(2026, 10, 4, 21, 0, 0), label="no TOU zone start in the night") -> R:
    rnd = random.Random(4242)
    s = X.make_rig(text, local=start, offset_s=-2.0, image_period_ms=10_000, image_phase_ms=rnd.randint(0, 9_999), tou=tou,
                   oracle=True)
    _freezes(s, rnd, s.now_ms, s.now_ms + hours * 3_600_000)
    s.run_for(hours * 3_600_000)
    r = R(f"PW9 night: zero drift, 0-10 s stale image, 20-60 s freezes, {hours} h ({label})", s)
    q = queues(s)
    if tou == TOU_DAY:
        r.crit("zero", "stale and frozen reads produce ZERO writes", not s.rtc_write_attempts(), f"{len(s.rtc_write_attempts())} writes")
    else:
        rds = [oracle_at(s, t) for t in q]
        keys = [x["pkey"] for x in rds if x]
        r.crit("precision", "the only corrections are precision corrections before TOU zone starts, at most one per boundary",
               all(x is not None and x["reason"] == rp.R_PRECISION for x in rds) and len(keys) == len(set(keys)),
               [(x or {}).get("reason") for x in rds])
    return inv(r, s)


PV_DAY = ((0, 0, 0.0), (7, 0, 2 / 60), (9, 0, 3 / 60), (11, 0, -7 / 60), (16, 0, 3 / 60), (18, 0, 1 / 60), (19, 0, 0.0))


def sc_day(text=None) -> R:
    rnd = random.Random(777)
    s = X.make_rig(text, local=(2026, 10, 4, 0, 0, 0), offset_s=-2.0, image_period_ms=10_000, image_phase_ms=rnd.randint(0, 9_999),
                   oracle=True)
    t0 = s.now_ms
    for h, m, rate in PV_DAY[1:]:
        s.at(t_of(s, X.hms(h, m)), lambda sm, rt=rate: sm.rtc.set_rate(rt))
    _freezes(s, rnd, t0, t0 + 86_400_000)
    worst = 0.0
    for _ in range(1440):
        s.run_for(60_000)
        worst = max(worst, abs(s.rtc.offset_s()))
    r = R("PW10 a PV day (0 / +2 / +3 / -7 / +3 / +1 s/min, stale + freezing image, 24 h)", s)
    q = queues(s)
    tq = [s.clock.tod(t) for t in q]
    rds = [oracle_at(s, t) for t in q]
    quiet_q = [x for x in tq if N.quiet(x, X.GOLD_TOU)]
    night = [(x, (rd or {}).get("reason")) for x, rd in zip(tq, rds) if (x < X.hms(7, 0) or x >= X.hms(20, 0))
             and (rd is None or rd["reason"] != rp.R_PRECISION)]
    bg_bad = [(a, b) for a, b, rd in zip(q, q[1:], rds[1:]) if (rd is None or rd["reason"] == rp.R_BACKGROUND) and b - a < N.GAP]
    pkeys = [rd["pkey"] for rd in rds if rd and rd["reason"] == rp.R_PRECISION]
    r.crit("quiet", "no correction was decided inside a quiet window (half hours, TOU zone starts)", not quiet_q, quiet_q[:5])
    r.crit("night", "no background correction at night (stale / frozen reads never confirm)", not night, night[:5])
    r.crit("gap", f"background corrections at least {N.GAP / 1000:.0f} s apart", not bg_bad, bg_bad[:3])
    r.crit("precision", "at most one precision correction per TOU zone start", len(pkeys) == len(set(pkeys)), pkeys)
    r.crit("verified", "every correction verified; no failure, no deadline abort",
           bool(q) and s.g["corrections_since_boot"] == len(q) and s.g["failed_corrections"] == 0
           and not any(x.startswith("ABORTED") for x in s.results()), f"{len(q)} queued, {s.flags()}")
    r.crit("bounded", f"the true inverter clock error stays bounded over the day (worst minute sample {worst:.0f} s <= 150 s)",
           worst <= 150.0, worst)
    return inv(r, s)


def sc_dst(text, which) -> R:
    """Europe/London DST change: the inverter keeps the old local time, so right after 01:00 UTC its error is about +-3600 s."""
    if which == "fall-back":
        day, local = (2026, 10, 25), (2026, 10, 25, 1, 50, 15)  # 01:50:15 BST; 02:00 BST -> 01:00 GMT
    else:
        day, local = (2027, 3, 28), (2027, 3, 28, 0, 50, 15)  # 00:50:15 GMT; 01:00 GMT -> 02:00 BST
    s = X.make_rig(text, local=local, offset_s=-2.0, oracle=True)
    t_change = s.now_ms + (X.days_from_civil(*day) * 86400 + 3600) * 1000 - s.clock.utc_ms()
    s.run_for(25 * 60_000)
    q = queues(s)
    rd = oracle_at(s, q[0]) if q else None
    r = R(f"PW11 DST {which} ({day[0]}-{day[1]:02d}-{day[2]:02d} 01:00 UTC)", s)
    r.crit("one", "exactly one correction after the change, decided outside every quiet window, verified (no oscillation in the "
           "repeated / skipped hour)", len(q) == 1 and q[0] > t_change and not N.quiet(s.clock.tod(q[0]), X.GOLD_TOU)
           and s.g["corrections_since_boot"] == 1, f"{[(t - t_change, s.clock.tod(t)) for t in q]}")
    r.crit("soon", "it comes within 3 minutes of the change, as a large error confirmed by two reads",
           bool(q) and q[0] - t_change <= 180_000 and (not s.oracle_on or (rd is not None and rd["reason"] == rp.R_LARGE)), rd)
    r.crit("clock", "afterwards the inverter reads the new local time (within 2 s)", abs(s.rtc.offset_s()) <= 2.0, s.rtc.offset_s())
    return inv(r, s)


# ============================================================================================================================
# [3] polls
# ============================================================================================================================
def _owner(kind):
    if kind == "mwip":
        return lambda sim: sim.poke("manual_write_in_progress", True)
    if kind == "cip":
        return lambda sim: sim.poke("correction_in_progress", True)
    return lambda sim: sim.press_button("sync_inverter_clock")  # a real writer: the manual RTC correction


def sc_tlm_owner(text, owner, dt) -> R:
    s = X.make_rig(text, intervals=("rtc_tick",) if owner == "sync" else ())
    t0 = s.now_ms
    s.start_script("poll_inverter_telemetry")
    s.at(t0 + dt, _owner(owner))
    s.run_for(6_000)
    r = R(f"P01 telemetry: {owner} takes the write path at +{dt} ms", s)
    t2 = s.frames(150, 47)
    task = s.task_of("poll_inverter_telemetry")
    if dt <= 2500:
        r.crit("no150", "no block 150/47 frame once the write path is owned during the 2.5 s delay", not t2,
               [(w.t_queued - t0) for w in t2])
        r.crit("ends", "the poll ends at its re-check (within 2.6 s of the owner taking the lock)",
               task.done and task.finished_ms - (t0 + dt) <= 2600, task.finished_ms)
    else:
        r.crit("sent", "control: an owner arriving after the re-check does not recall the frame already queued", len(t2) == 1)
    return inv(r, s)


def sc_tlm_handlers(text, block, outcome) -> R:
    s = X.make_rig(text, intervals=())
    s.start_script("poll_inverter_telemetry")
    s.run_until_idle()
    f0, online0 = s.g["telemetry_failures"], s.ent("telemetry_online").state
    X.bind_outcomes(s, X.outcomes(poll={block: outcome}))
    s.start_script("poll_inverter_telemetry")
    s.run_until_idle()
    r = R(f"P02 telemetry block {block} {outcome}", s)
    r.crit("failures", "telemetry_failures +1", s.g["telemetry_failures"] == f0 + 1, (f0, s.g["telemetry_failures"]))
    if block == 150:
        r.crit("offline", "telemetry_online published false", online0 is True and s.ent("telemetry_online").state is False)
    return inv(r, s)


def _cfg_snapshot(s):
    g = s.g
    return {"valid": bool(g["manual_config_raw_cache_valid"]), "online": s.ent("configuration_online").state,
            "seq": g["cfg_block_b_seq"], "okms": g["cfg_block_b_ok_ms"], "rds": g["cfg_block_b_response_dispatch_seq"],
            "ds": g["cfg_block_b_dispatch_seq"], "filled": bool(g["fbc_raw_filled"]), "fails": g["configuration_failures"]}


def sc_cfg_yield1(text, owner) -> R:
    s = X.make_rig(text, intervals=("rtc_tick",) if owner == "sync" else ())
    s.start_script("poll_inverter_configuration")
    s.run_until_idle()  # one complete poll: a valid, fresh cache
    s.run_for(10_000)
    before = _cfg_snapshot(s)
    t0 = s.now_ms
    s.start_script("poll_inverter_configuration")
    s.at(t0 + 1_000, _owner(owner))
    s.run_for(8_000)
    after = _cfg_snapshot(s)
    task = s.task_of("poll_inverter_configuration_dispatch")
    r = R(f"P03 configuration poll: {owner} takes the write path during delay 1", s)
    r.crit("noB", "no Block B (241/53) and no Block C (330/1) frame inside the owner's transaction",
           not s.frames(241, 53, since_ms=t0) and not s.frames(330, 1, since_ms=t0))
    r.crit("nostamp", "the yield stamps nothing: cfg_block_b_dispatch_seq unchanged",
           after["ds"] == before["ds"], (before["ds"], after["ds"]))
    r.crit("flags", "the yield changes no cache flag (valid / online / seq / ok_ms / response seq / filled kept)",
           all(after[k] == before[k] for k in ("valid", "online", "seq", "okms", "rds", "filled")), f"{before} -> {after}")
    r.crit("owed", "a catch-up poll is owed (cfg_poll_owed >= 1)", (s.g.get("cfg_poll_owed") or 0) >= 1, s.g.get("cfg_poll_owed"))
    r.crit("ends", "the poll ends at its re-check (within 2.6 s of the owner taking the lock: FB-B's drain is not held up)",
           task.done and task.finished_ms - (t0 + 1_000) <= 2600, task.finished_ms - t0)
    return inv(r, s)


def sc_cfg_yield2(text, owner="mwip") -> R:
    s = X.make_rig(text, intervals=())
    t0 = s.now_ms
    s.start_script("poll_inverter_configuration")
    s.at(t0 + 3_000, _owner(owner))
    s.run_for(8_000)
    task = s.task_of("poll_inverter_configuration_dispatch")
    r = R(f"P04 configuration poll: {owner} takes the write path during delay 2", s)
    r.crit("noC", "no Block C (330/1) frame inside the owner's transaction", not s.frames(330, 1, since_ms=t0))
    r.crit("kept", "Block B's results are kept (cache valid, seq / response seq stamped by its response)",
           s.g["manual_config_raw_cache_valid"] and s.g["cfg_block_b_seq"] == 1
           and s.g["cfg_block_b_response_dispatch_seq"] == s.g["cfg_block_b_dispatch_seq"] == 1, _cfg_snapshot(s))
    r.crit("ends", "the poll ends at its re-check", task.done and task.finished_ms - (t0 + 3_000) <= 2600, task.finished_ms - t0)
    return inv(r, s)


def sc_cfg_handler(text, block, outcome) -> R:
    s = X.make_rig(text, intervals=())
    s.start_script("poll_inverter_configuration")
    s.run_until_idle()
    s.run_for(30_000)
    b = _cfg_snapshot(s)
    X.bind_outcomes(s, X.outcomes(poll={block: outcome}))
    s.start_script("poll_inverter_configuration")
    s.run_until_idle()
    a = _cfg_snapshot(s)
    r = R(f"P07 configuration Block {'A' if block == 200 else 'B' if block == 241 else 'C'} {outcome}", s)
    r.crit("failures", "configuration_failures +1", a["fails"] == b["fails"] + 1, (b["fails"], a["fails"]))
    if block == 200:
        r.crit("rule", "Block A rule: block1_ok false -> the cache is invalid and offline after the poll",
               not s.g["configuration_block1_ok"] and not a["valid"] and a["online"] is False, a)
    elif block == 241:
        r.crit("rule", "Block B rule: cache invalid, offline, and nothing stamped (seq / ok_ms / response seq unchanged)",
               not a["valid"] and a["online"] is False and (a["seq"], a["okms"], a["rds"]) == (b["seq"], b["okms"], b["rds"])
               and a["ds"] == b["ds"] + 1, f"{b} -> {a}")
    else:
        r.crit("rule", "Block C rule (display-only register 330): only counted - configuration_online and the Block A / B cache are "
               "unchanged", a["online"] is True and a["valid"] and (a["seq"], a["rds"]) == (b["seq"] + 1, b["rds"] + 1), f"{b} -> {a}")
    return inv(r, s)


def sc_poll_random(text=None, seed=11, n_windows=40) -> R:
    rnd = random.Random(seed)
    s = X.make_rig(text, intervals=("telemetry", "config", "catchup"), offset_s=0.0)
    t0 = s.now_ms
    wins, t = [], t0 + 25_000
    while len(wins) < n_windows:
        t += rnd.randint(4_000, 50_000)
        d = rnd.randint(1_500, 20_000)
        k = rnd.choice(("manual_write_in_progress", "correction_in_progress"))
        wins.append((t, t + d, k))
        t += d
    for a, b, k in wins:
        s.at(a, lambda sim, k=k: sim.poke(k, True))
        s.at(b, lambda sim, k=k: sim.poke(k, False))
    outs = ("ok",) * 17 + ("error", "no_response", "not_sent", "custom_response", "timeout")
    pick = (lambda sim: rnd.choice(outs))
    X.bind_outcomes(s, X.outcomes(poll={a: pick for a in (59, 150, 200, 241, 330)}))
    s.run_until(wins[-1][1] + 150_000)
    frames = [w for w in s.wire_log if (w.kind, w.addr, w.count) in X.POLL_FRAMES]
    inside = [(w.addr, w.t_queued) for w in frames if any(a <= w.t_queued < b for a, b, _k in wins)]
    r = R(f"P11 randomised owners / outcomes ({n_windows} owner windows, {len(frames)} poll frames)", s)
    r.crit("inside", "no poll frame is queued inside an owner's window (write mutex or RTC lock)", not inside, inside[:4])
    r.crit("stamp", "cfg_block_b_dispatch_seq == the number of Block B reads attempted (each stamp is a real Block B queue)",
           s.g["cfg_block_b_dispatch_seq"] == s.read_attempts(241), (s.g["cfg_block_b_dispatch_seq"], s.read_attempts(241)))
    r.crit("owed", "every owed catch-up was paid once the owners stopped (cfg_poll_owed back to 0)", s.g.get("cfg_poll_owed") == 0,
           s.g.get("cfg_poll_owed"))
    return inv(r, s)


def sc_catchup_yield(text=None) -> R:
    s = X.make_rig(text, intervals=("config", "catchup"), offset_s=0.0)
    t0 = s.now_ms
    s.at(t0 + 21_000, lambda sim: sim.poke("manual_write_in_progress", True))
    s.at(t0 + 46_000, lambda sim: sim.poke("manual_write_in_progress", False))
    s.hold_bus(6_000, at=t0 + 46_000)
    s.run_until(t0 + 45_000)
    owed_mid, ds_mid = s.g.get("cfg_poll_owed"), s.g["cfg_block_b_dispatch_seq"]
    s.run_until(t0 + 75_000)
    bb = s.frames(241, 53)
    r = R("C1 catch-up after a yield", s)
    r.crit("yield", "the 60 s poll yielded Block B to the owner: one poll owed, nothing stamped, no catch-up while the owner holds",
           owed_mid == 1 and ds_mid == 0 and not [w for w in bb if w.t_queued < t0 + 46_000], (owed_mid, ds_mid))
    r.crit("runs", "the catch-up runs the poll once the owner released AND the bus is quiet; the debt is paid",
           len(bb) == 1 and t0 + 52_000 <= bb[0].t_queued <= t0 + 57_000 and s.g.get("cfg_poll_owed") == 0
           and s.g["cfg_block_b_dispatch_seq"] == 1, [w.t_queued - t0 for w in bb])
    return inv(r, s)


def sc_catchup_rtc(text=None) -> R:
    s = X.make_rig(text, intervals=("rtc_read", "rtc_tick", "catchup"))
    s.run_for(330_000)
    q = X.queue_time(s)
    rel = X.release_time(s, q) if q is not None else None
    bb = s.frames(241, 53, since_ms=rel or 0)
    r = R("C2 catch-up after an RTC lock release", s)
    r.crit("two", "after the RTC lock release exactly two catch-up configuration polls run (dispatch seq +2), then nothing more",
           rel is not None and s.g["cfg_block_b_dispatch_seq"] == 2 and len(bb) == 2 and s.g.get("cfg_poll_owed") == 0,
           f"rel={rel} ds={s.g['cfg_block_b_dispatch_seq']} frames={[w.t_queued - (rel or 0) for w in bb]}")
    r.crit("soon", "both within 20 s of the release", len(bb) == 2 and bb[-1].t_queued - rel <= 20_000)
    return inv(r, s)


def sc_phase_locked(text=None, minutes=10) -> R:
    s = X.make_rig(text, intervals=("config", "catchup"), offset_s=0.0)
    t0 = s.now_ms
    wins = [(t0 + 21_000 + 60_000 * k, t0 + 31_000 + 60_000 * k) for k in range(minutes)]
    for a, b in wins:
        s.at(a, lambda sim: sim.poke("manual_write_in_progress", True))
        s.at(b, lambda sim: sim.poke("manual_write_in_progress", False))
    s.run_until(t0 + 40_000)
    worst = 0
    while s.now_ms < wins[-1][1] + 30_000:
        s.run_for(1_000)
        age = (s.millis() - s.g["cfg_block_b_ok_ms"]) & 0xFFFFFFFF if s.g["cfg_block_b_seq"] else s.now_ms - t0
        worst = max(worst, age)
    late = [(w.addr, w.t_queued) for w in s.wire_log if w.addr in (241, 330) and any(a <= w.t_queued < b for a, b in wins)]
    r = R(f"C3 an owner phase-locked into every 60 s poll's first delay for {minutes} min", s)
    r.crit("fresh", f"Block B is never older than 180 s: the catch-up prevents starvation (worst age {worst / 1000:.1f} s)",
           worst <= 180_000, worst)
    r.crit("inside", "no Block B / Block C frame inside an owner window", not late, late[:3])
    return inv(r, s)


# ============================================================================================================================
# [4] fence (B10 Live Match + the unchanged write fence)
# ============================================================================================================================
def sc_fence(text=None) -> R:
    s = X.make_fence_rig(text)
    s.run_for(240_000)
    primed = s.b10_m() == "MATCH"
    t_step = s.now_ms
    s.rtc.step(-(N.BG + 45))
    s.run_for(420_000)
    q = X.queue_time(s, t_step)
    rel = X.release_time(s, q) if q is not None else None
    log = [x for x in s.fence_log if x[0] >= t_step]
    first = next((x for x in log if rel is not None and x[0] > rel and x[1] == "MATCH"), None)
    # cfg_block_b_dispatch_seq at the release instant = the Block B reads queued before it (each queue is one stamp)
    ds_rel = len([w for w in s.frames(241, 53) if w.t_queued <= rel]) if rel is not None else None
    r = R("F1 B10 after an RTC correction", s)
    r.crit("primed", "precondition: B10 compared MATCH before the correction", primed, s.b10())
    r.crit("ran", "an automatic correction ran and was released", q is not None and rel is not None)
    r.crit("paused", "B10 left MATCH while the correction held the lock (PAUSED_IO)",
           any(x[1] == "PAUSED_IO" for x in log if q is not None and rel is not None and q <= x[0] <= rel))
    r.crit("never", "B10 is never MATCH while the RTC lock / verification is held, nor from a Block B dispatched before the fence",
           not s.fence_violations, s.fence_violations[:2])
    r.crit("two", "MATCH returns only from the response to the second Block B dispatched after the release",
           first is not None and ds_rel is not None and first[4] - ds_rel >= 2, f"{first} ds@release={ds_rel}")
    r.crit("fast", "with the catch-up, MATCH returns within 30 s of the release (no longer two 60 s periods)",
           first is not None and first[0] - rel <= 30_000, f"{(first[0] - rel) if (first and rel) else None} ms")
    return inv(r, s)


def sc_fence_share(text=None, hours=6) -> R:
    """F08: B10 MATCH availability over a high-PV stretch (-7 s/min, stale 10 s image) with the polls, the catch-up and B10."""
    s = X.make_fence_rig(text, local=(2026, 10, 4, 10, 55, 0))
    s.rtc.image_period_ms = 10_000
    s.rtc.set_rate(-7 / 60)
    s.run_for(hours * 3_600_000)
    share = sum(1 for x in s.fence_log if x[1] == "MATCH") / max(1, len(s.fence_log))
    r = R(f"F3 B10 availability over {hours} h of -7 s/min drift", s)
    r.crit("share", f"B10 compares MATCH on >= 80 % of its 10 s ticks (measured {share:.1%}, {len(s.rtc_write_attempts())} corrections)",
           share >= 0.80, f"{share:.3f}")
    r.crit("never", "and never MATCH while the RTC lock / verification is held, nor before the fence passed", not s.fence_violations,
           s.fence_violations[:2])
    return inv(r, s)


def sc_fence_divert(text=None) -> R:
    s = X.make_fence_rig(text, intervals=("config", "housekeeping"))
    s.run_for(240_000)
    primed = s.b10_m() == "MATCH"
    t = s.now_ms
    X.bind_outcomes(s, X.outcomes(poll={241: "custom_response"}))
    s.run_for(90_000)
    bb = [w for w in s.frames(241, 53, since_ms=t)]
    tb = bb[0].t_end if bb else None
    nxt = next((x for x in s.fence_log if tb is not None and x[0] > tb), None)
    r = R("F2 a diverted Block B", s)
    r.crit("primed", "precondition: B10 compared MATCH", primed, s.b10())
    r.crit("leaves", "a diverted Block B (custom_response) takes B10 out of MATCH at the next 10 s tick (ca=I), not after 180 s",
           nxt is not None and nxt[1] != "MATCH" and "ca=I" in s.b10() and nxt[0] - tb <= 10_500, f"{nxt} {s.b10()}")
    return inv(r, s)


# ============================================================================================================================
# [5] static
# ============================================================================================================================
OWNER_FREE = scope.OWNER_FREE


def _node(fw, kind, pid):
    return X._find_script(fw, pid) if kind == "script" else X._find_button(fw, pid)


def st_handlers(fw):
    n, missing = 0, []
    for kind, pid in (("script", "write_inverter_rtc"), ("button", "read_inverter_clock"), ("script", "poll_inverter_telemetry"),
                      ("script", "poll_inverter_configuration_dispatch")):
        for _k, body in X.modbus_actions(_node(fw, kind, pid)):
            n += 1
            miss = [h for h in X.TERMINAL_HANDLERS if h not in body]
            if miss:
                missing.append(f"{pid}@{body['start_address']}: {miss}")
    return n, missing


def _all_lambdas(fw):
    out = []
    X._lambdas({k: v for k, v in fw.items() if not k.startswith("_")}, out)
    return out


def st_stamps(fw):
    sites, bad = 0, []
    for c in _all_lambdas(fw):
        for m in re.finditer(r"id\(correction_in_progress\) = true;", c):
            sites += 1
            win = c[m.end():m.end() + 900]
            cut = win.find("id(correction_in_progress) = false;")
            win = win if cut < 0 else win[:cut]
            if "id(rtc_txn_since_ms) = millis();" not in win:
                bad.append(c[:70])
    return sites, bad


def st_guarded(fw):
    bad, reads = [], [0]

    def walk(actions, cond, delayed_before):
        local_delay = False
        for a in actions or []:
            (k, b), = a.items()
            if k in ("delay", "wait_until"):
                local_delay = delayed_before = True
            elif k == ds.READ:
                reads[0] += 1
                if delayed_before and (cond is None or cond.strip() != OWNER_FREE or local_delay):
                    bad.append(f"read {b['start_address']} after a delay without an owner-free re-check in the same pass")
            elif k == "if":
                c = b["condition"]["lambda"]
                d1 = walk(b.get("then"), c, delayed_before)
                d2 = walk(b.get("else"), "!" + c, delayed_before)
                if d1 or d2:
                    local_delay = delayed_before = True
        return local_delay
    for pid in ("poll_inverter_telemetry", "poll_inverter_configuration_dispatch"):
        walk(X._find_script(fw, pid)["then"], None, False)
    return reads[0], bad


QUIET_BUS = "id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked()"


def _call_args(text: str, start: int) -> list | None:
    """The top-level, whitespace-normalised arguments of the call whose '(' is at text[start] (None if unbalanced)."""
    depth, args, cur = 0, [], []
    for ch in text[start:]:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(cur))
                return [re.sub(r"\s+", " ", a).strip() for a in args]
        elif ch == "," and depth == 1:
            args.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    return None


def _breaker_cond(fw) -> str:
    """The breaker's `else if (...)` condition text of the 1 s RTC tick's first lambda ('' if absent)."""
    first = fw["interval"][X.interval_ids(fw)["rtc_tick"]]["then"][0].get("lambda", "")
    i = first.find("} else if (ecco_rtc::breaker_due(")
    if i < 0:
        return ""
    k = first.index("(", i)
    args = _call_args(first, k)
    return "" if args is None else args[0]


def _breaker_terms_ok(cond: str) -> bool:
    i = cond.find("ecco_rtc::breaker_due(")
    if i < 0:
        return False
    outer = _call_args(cond, cond.index("(", i))
    if not outer or len(outer) != 3 or outer[:2] != ["millis()", "id(rtc_txn_since_ms)"]:
        return False
    j = outer[2].find("ecco_rtc::no_rtc_frame_outstanding(")
    inner = _call_args(outer[2], outer[2].index("(", j)) if j == 0 else None
    return inner == [QUIET_BUS, "id(auto_sync_pending)", "id(verification_pending)", "id(comm_failure_pending)"] \
        and "verification_read_active" not in cond


def static_section(fw, live: bool = True):
    iv = X.interval_ids(fw)
    n, missing = st_handlers(fw)
    check("S-R1 every modbus_client action of write_inverter_rtc, read_inverter_clock, poll_inverter_telemetry and "
          f"poll_inverter_configuration_dispatch declares all five terminal handlers ({n} actions)", n == 7 and not missing, missing)
    # write_inverter_rtc branches
    wr = X._find_script(fw, "write_inverter_rtc")["then"]
    top = wr[0]["if"]
    defer = "\n".join(a.get("lambda", "") for a in top["then"])
    inner = top["else"][0]["if"]
    abort = "\n".join(a.get("lambda", "") for a in inner.get("else") or [] if "lambda" in a)
    check("S-R2 every branch of write_inverter_rtc releases or writes: the deferral and the NTP-abort branch both release "
          "correction_in_progress and the progress flags; the write branch's failure handlers fail into the retry path",
          "id(correction_in_progress) = false;" in defer and all(f"id({f}) = false;" in abort for f in
                                                                 ("correction_in_progress", "auto_sync_pending", "verification_pending",
                                                                  "verification_read_active", "comm_failure_pending"))
          and not X.modbus_actions(inner.get("else")))
    wbody = next(b for k, b in X.modbus_actions(wr) if k == ds.WRITE)
    fails = {h: "\n".join(a["lambda"] for a in wbody[h]["then"]) for h in ("on_error", "on_no_response", "on_not_sent", "on_custom_response")}
    check("S-R2 every FC16 failure terminal (error / no_response / not_sent / custom_response) clears vp / vra and sets "
          "comm_failure_pending; on_response schedules the verification",
          all("id(comm_failure_pending) = true;" in v and "id(verification_pending) = false;" in v and
              "id(verification_read_active) = false;" in v for v in fails.values())
          and "id(verification_pending) = true;" in "\n".join(a["lambda"] for a in wbody["on_response"]["then"]))
    rb = X._find_button(fw, "read_inverter_clock")["on_press"][0][ds.READ]
    ns = rb["on_not_sent"]["then"][0]["lambda"]
    cr = rb["on_custom_response"]["then"][0]["lambda"]
    check("S-R2 the read's on_not_sent releases only the 1 s tick's own verification press (rtc_verify_dispatching marker); "
          "on_custom_response only an outstanding verification read",
          "if (id(rtc_verify_dispatching) && id(verification_read_active)) {" in ns and "if (id(verification_read_active)) {" in cr
          and "id(comm_failure_pending) = true;" in ns and "id(comm_failure_pending) = true;" in cr)
    sites, bad = st_stamps(fw)
    check(f"S-R3 every `id(correction_in_progress) = true;` site stamps rtc_txn_since_ms = millis() in the same lambda ({sites} sites: "
          "the automatic queue and the Sync button)", sites == 2 and not bad, bad)
    first = fw["interval"][iv["rtc_tick"]]["then"][0].get("lambda", "")
    i = first.find("} else if (ecco_rtc::breaker_due(")
    j = first.find(")) {", i)
    k2 = first.find("\n}\n", j)
    cond, body = first[i:j + 2], first[j:k2]
    assigns = set(re.findall(r"id\((\w+)\)\s*(?:=(?!=)|\+\+|--)", body))
    want = {"failed_corrections", "correction_in_progress", "correction_is_manual", "correction_attempt", "verification_pending",
            "verification_read_active", "auto_sync_pending", "comm_failure_pending", "have_rtc_baseline", "cooldown_until_ms"}
    check("S-R3 the breaker is the FIRST lambda of the 1 s RTC tick, runs on the deadline clock, and assigns exactly the RTC state + "
          "failed_corrections + cooldown (never the write mutex or another domain's flag)",
          i > 0 and "millis(), id(rtc_txn_since_ms)" in cond and assigns == want
          and set(re.findall(r"id\((\w+)\)\.publish_state", body)) == {"last_correction_result"}, f"{sorted(assigns ^ want)}")
    check("S-R3 its 'no RTC frame can be outstanding' term is exactly: the quiet bus (tx_buffer_empty() && !tx_blocked()) OR the "
          "correction between frames (auto_sync_pending / verification_pending / comm_failure_pending) - never "
          "verification_read_active (a read may be outstanding)", _breaker_terms_ok(_breaker_cond(fw)), _breaker_cond(fw)[:300])
    bc = X._find_script(fw, "poll_inverter_configuration_dispatch")
    cbody = next((b for k, b in X.modbus_actions(bc) if b.get("start_address") == 330), {})
    new_c = {h: "\n".join(a.get("lambda", "") for a in (cbody.get(h) or {}).get("then") or []) for h in ("on_not_sent", "on_custom_response")}
    old_c = {h: "\n".join(a.get("lambda", "") for a in (cbody.get(h) or {}).get("then") or []) for h in ("on_error", "on_no_response")}
    check("S-P4 Block C's new on_not_sent / on_custom_response (display-only register 330) only count configuration_failures: no "
          "configuration_online publish, no cache flag; its existing on_error / on_no_response are unchanged",
          all(set(re.findall(r"id\((\w+)\)\s*(?:=(?!=)|\+\+|--)", v)) == {"configuration_failures"} and "publish_state" not in v
              for v in new_c.values())
          and all("id(configuration_online).publish_state(false);" in v for v in old_c.values()), new_c)
    # fence inputs
    lams = []
    X._lambdas(X._find_script(fw, "fallback_profile_live_refresh"), lams)
    if "fbc" in iv:
        X._lambdas(fw["interval"][iv["fbc"]], lams)
    txt = "\n".join(lams)
    hdr = (ROOT / "firmware" / "include" / "ecco_fallback_capture.h").read_text(encoding="utf-8") + \
        (ROOT / "firmware" / "include" / "ecco_failback_shadow.h").read_text(encoding="utf-8")
    hits = [g for g in scope.NEW_GLOBAL_IDS if re.search(rf"\bid\({g}\)", txt) or re.search(rf"\b{g}\b", hdr)]
    check("S-R5 no FB-D1 global appears in the B10 fence sample / bus_busy inputs / writes fingerprint (live refresh script, FB-C "
          "tick, shared headers), and the fence still sees the RTC through correction_in_progress / verification_*",
          not hits and all(f"gi.bus.{f} = id({f});" in txt for f in ("correction_in_progress", "verification_pending",
                                                                     "verification_read_active")), hits)
    vals = str(wbody.get("values", ""))
    writes = [(k, b.get("start_address")) for kind, pid in (("script", "write_inverter_rtc"), ("button", "read_inverter_clock"),
                                                           ("button", "sync_inverter_clock"), ("script", "poll_inverter_telemetry"),
                                                           ("script", "poll_inverter_configuration_dispatch"))
              for k, b in X.modbus_actions(_node(fw, kind, pid)) if k == ds.WRITE]
    check("S-R4 write_inverter_rtc's only write is the literal FC16 at 0x0016 with the 3-element vector {reg22, reg23, reg24}; the "
          "read button, Sync and both polls write nothing",
          writes == [(ds.WRITE, 22)] and vals.rstrip().endswith("return std::vector<uint16_t>{reg22, reg23, reg24};"), writes)
    nreads, bad = st_guarded(fw)
    check(f"S-P1 every delayed poll read is queued inside an owner-free re-check (`{OWNER_FREE}`) in the same loop pass ({nreads} reads)",
          nreads == 5 and not bad, bad)
    cu = fw["interval"][iv["catchup"]] if "catchup" in iv else None
    cond = cu["then"][0]["if"]["condition"]["lambda"] if cu else ""
    check("S-P2 the catch-up interval (2 s) runs only the wrapper, only while owed, polling on, no owner, no dispatch running and the "
          "bus quiet; it follows the 60 s configuration interval and is not the last interval",
          cu is not None and str(cu["interval"]) == "2s" and iv["catchup"] == iv["config"] + 1 and iv["catchup"] < len(fw["interval"]) - 1
          and all(t in cond for t in ("id(cfg_poll_owed) > 0", "id(configuration_polling).state", "!id(manual_write_in_progress)",
                                      "!id(correction_in_progress)", "!id(poll_inverter_configuration_dispatch).is_running()",
                                      "id(inverter_modbus)->tx_buffer_empty()", "!id(inverter_modbus)->tx_blocked()"))
          and cu["then"][0]["if"]["then"] == [{"script.execute": {"id": "poll_inverter_configuration"}}])
    tick = fw["interval"][iv["rtc_tick"]]["then"]
    asp = next(a["if"] for a in tick if "if" in a and "auto_sync_pending" in a["if"]["condition"]["lambda"])
    ver = next(a["if"] for a in tick if "if" in a and "verification_due_ms" in a["if"]["condition"]["lambda"])
    check("S-P3 the queued write is dispatched only on a quiet bus; the verification press requires the lock and is wrapped by "
          "rtc_verify_dispatching = true / false",
          "id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked()" in asp["condition"]["lambda"]
          and "id(correction_in_progress) &&" in ver["condition"]["lambda"]
          and [list(a)[0] for a in ver["then"]] == ["lambda", "button.press", "lambda"]
          and "id(rtc_verify_dispatching) = true;" in ver["then"][0]["lambda"]
          and ver["then"][2]["lambda"].strip() == "id(rtc_verify_dispatching) = false;")
    gl = {g["id"]: g for g in fw["globals"]}
    check("S-G the FB-D1 globals exist exactly as _fbd1_scope.NEW_GLOBAL_SPECS says (type, initial, restore_value: no)",
          all(gid in gl and gl[gid]["type"] == t and str(gl[gid].get("initial_value")) == init and gl[gid].get("restore_value") is False
              for gid, t, init in scope.NEW_GLOBAL_SPECS))
    check("S-scope the pre-FB-D1 firmware used as the baseline is main exactly (sha == _fbd1_scope.BASE_FW_SHA) and round-trips",
          scope.sha(PRE) == scope.BASE_FW_SHA and scope.add_fbd1_text(PRE) == LIVE_FBD1)   # PEX0: the FB-D1 firmware as of fbd1


# ============================================================================================================================
# [7] mutants
# ============================================================================================================================
def _cut(text, start, end_incl):
    i = text.index(start)
    if text.count(start) != 1:
        raise AssertionError(f"cut anchor occurs {text.count(start)} times")
    j = text.index(end_incl, i) + len(end_incl)
    return text[:i] + text[j:]


def _drop_catchup(text):
    i = text.index("  - interval: 2s\n    startup_delay: 30s\n")
    j = text.index("\n  - interval: ", i + 10)
    return text[:i] + text[j + 1:]


OWN = "return !id(manual_write_in_progress) && !id(correction_in_progress);"
MUTANTS = (
    ("M01", "write on_not_sent dropped",
     lambda t: _cut(t, '                      on_not_sent:\n                        then:\n                          - lambda: |-\n'
                       '                              ESP_LOGW("ecco", "RTC write was not queued',
                    'publish_state("Write not sent - processing retry");\n'),
     [("R04 write not_sent", lambda x: sc_write_refused(x, "not_sent"), "bounded")], "S-R1"),
    ("M02", "write on_custom_response dropped",
     lambda t: _cut(t, '                      on_custom_response:\n                        then:\n                          - lambda: |-\n'
                       '                              ESP_LOGW("ecco", "Non-standard reply to RTC write',
                    'publish_state("Non-standard write reply - processing retry");\n'),
     [("R04 write custom_response", lambda x: sc_write_refused(x, "custom_response"), "bounded")], "S-R1"),
    ("M03", "NTP-abort release dropped",
     lambda t: X.mutate(t, '                  - lambda: |-\n                      id(correction_in_progress) = false;\n'
                           '                      id(correction_is_manual) = false;\n                      id(correction_attempt) = 0;\n'
                           '                      id(verification_pending) = false;\n                      id(verification_read_active) = false;\n'
                           '                      id(auto_sync_pending) = false;\n                      id(comm_failure_pending) = false;\n'
                           '                      id(last_correction_result).publish_state("Correction cancelled - confirmed NTP time '
                           'unavailable");\n', ""),
     [("R13 NTP abort", sc_ntp_abort, "released")], "S-R2"),
    ("M04", "deadline breaker neutered",
     lambda t: X.mutate(t, "} else if (ecco_rtc::breaker_due(", "} else if (false && ecco_rtc::breaker_due("),
     [("R06 write callback lost", lambda x: sc_write_lost(x, "timeout_lost"), "breaker")], None),
    ("M05", "invariant gate dropped (stray flags not cleared)",
     lambda t: X.mutate(t, '              ESP_LOGW("ecco", "RTC progress flags set without the correction lock - cleared");\n'
                           '              id(verification_pending) = false;\n              id(verification_read_active) = false;\n'
                           '              id(auto_sync_pending) = false;\n              id(comm_failure_pending) = false;\n',
                        '              ESP_LOGW("ecco", "RTC progress flags set without the correction lock - cleared");\n'),
     [("I1 stray auto_sync_pending", lambda x: sc_inject(x, "auto_sync_pending"), "inert")], None),
    ("M06", "read on_custom_response dropped",
     lambda t: _cut(t, '          on_custom_response:\n            then:\n              - lambda: |-\n'
                       '                  ESP_LOGW("ecco", "Non-standard reply while reading inverter RTC',
                    'publish_state("Verification read got a non-standard reply - processing retry");\n                  }\n'),
     [("R07 verification read custom_response", lambda x: sc_verify(x, "custom_response"), "bounded")], "S-R1"),
    ("M07", "verification marker dropped from the read's on_not_sent",
     lambda t: X.mutate(t, "if (id(rtc_verify_dispatching) && id(verification_read_active)) {", "if (id(verification_read_active)) {"),
     [("R19 HA press refused", sc_ha_refused, "untouched")], "S-R2"),
    ("M08", "quiet-bus term dropped from the write dispatch",
     lambda t: X.mutate(t, "              return id(auto_sync_pending) &&\n                     id(inverter_modbus)->tx_buffer_empty() && "
                           "!id(inverter_modbus)->tx_blocked();\n", "              return id(auto_sync_pending);\n"),
     [("R23 quiet dispatch", sc_quiet_dispatch, "waits")], "S-P3"),
    ("M09", "policy bypassed (old single-read rule)",
     lambda t: X.mutate(t, "if (dec.action == ecco_rtc::ACT_CORRECT) {",
                        "if (dec.action == ecco_rtc::ACT_CORRECT || abs_difference >= threshold) {"),
     [("PW1 one stale read", sc_spike, "none")], None),
    ("M10", "Sync no longer stamps the deadline clock",
     lambda t: X.mutate(t, '                id(correction_attempt) = 1;\n                id(rtc_txn_since_ms) = millis();\n',
                        '                id(correction_attempt) = 1;\n'),
     [("R16 manual Sync (idle)", lambda x: sc_manual(x, "idle"), "runs")], "S-R3"),
    ("M11", "automatic queue no longer stamps the deadline clock",
     lambda t: X.mutate(t, "                    id(rtc_txn_since_ms) = millis();\n                    id(rtc_have_last_auto) = true;\n",
                        "                    id(rtc_have_last_auto) = true;\n"),
     [("R01 success", sc_success, "verified")], "S-R3"),
    ("M12", "telemetry block 150 re-check dropped",
     lambda t: X.mutate(t, "              " + OWN + "\n          then:\n            - modbus_client.read_holding_registers:\n"
                           "                modbus_id: inverter_modbus\n                address: 0x01\n                start_address: 150\n",
                        "              return true;\n          then:\n            - modbus_client.read_holding_registers:\n"
                        "                modbus_id: inverter_modbus\n                address: 0x01\n                start_address: 150\n"),
     [("P01 telemetry", lambda x: sc_tlm_owner(x, "mwip", 1000), "no150")], "S-P1"),
    ("M13", "Block B re-check dropped",
     lambda t: X.mutate(t, "                    " + OWN + "\n                then:\n                  - lambda: |-\n"
                           "                      id(cfg_block_b_dispatch_seq)++;\n",
                        "                    return true;\n                then:\n                  - lambda: |-\n"
                        "                      id(cfg_block_b_dispatch_seq)++;\n"),
     [("P03 configuration yield", lambda x: sc_cfg_yield1(x, "mwip"), "noB")], "S-P1"),
    ("M14", "dispatch stamp moved outside the Block B guard",
     lambda t: X.mutate(t, "            - if:\n                condition:\n                  lambda: |-\n                    " + OWN +
                           "\n                then:\n                  - lambda: |-\n                      id(cfg_block_b_dispatch_seq)++;\n",
                        "            - lambda: 'id(cfg_block_b_dispatch_seq)++;'\n            - if:\n                condition:\n"
                        "                  lambda: |-\n                    " + OWN + "\n                then:\n                  - lambda: |-\n"),
     [("P03 configuration yield", lambda x: sc_cfg_yield1(x, "mwip"), "nostamp")], None),
    ("M15", "Block C re-check dropped",
     lambda t: X.mutate(t, "                          " + OWN + "\n                      then:\n",
                        "                          return true;\n                      then:\n"),
     [("P04 configuration delay 2", lambda x: sc_cfg_yield2(x, "mwip"), "noC")], "S-P1"),
    ("M16", "lock-release edge no longer owes two polls",
     lambda t: X.mutate(t, "id(cfg_poll_owed) = 2;", "id(cfg_poll_owed) = id(cfg_poll_owed);"),
     [("C2 catch-up after an RTC release", sc_catchup_rtc, "two")], None),
    ("M17", "catch-up interval removed",
     _drop_catchup,
     [("C3 phase-locked owner", sc_phase_locked, "fresh")], "S-P2"),
    ("M18", "breaker idle term reduced to the quiet bus (a correction between frames waits for the bus)",
     lambda t: _rx_mutate(t, r"ecco_rtc::no_rtc_frame_outstanding\(\s*(" + re.escape(QUIET_BUS) + r"),\s*id\(auto_sync_pending\), "
                             r"id\(verification_pending\), id\(comm_failure_pending\)\)", r"\1"),
     [("R18 breaker S1 on a busy bus", lambda x: sc_breaker_state(x, "S1"), "releases")], "S-R3b"),
    ("M19", "breaker also releases while a verification read may be outstanding",
     lambda t: X.mutate(t, "id(auto_sync_pending), id(verification_pending), id(comm_failure_pending))",
                        "id(auto_sync_pending), id(verification_pending) || id(verification_read_active), id(comm_failure_pending))"),
     [("R18 breaker S4 on a busy bus", lambda x: sc_breaker_state(x, "S4"), "holds")], "S-R3b"),
    ("M20", "Block C's new handlers flip configuration_online again",
     lambda t: X.mutate(t, 'ESP_LOGW("config", "Configuration register 330 was not sent");',
                        'id(configuration_online).publish_state(false);\n' + ' ' * 36 +
                        'ESP_LOGW("config", "Configuration register 330 was not sent");'),
     [("P07 Block C not_sent", lambda x: sc_cfg_handler(x, 330, "not_sent"), "rule")], "S-P4"),
)


def _rx_mutate(text, pattern, repl):
    out, n = re.subn(pattern, repl, text)
    if n != 1:
        raise AssertionError(f"mutation pattern matches {n} times, want 1: {pattern[:80]!r}")
    return out


def _block_c_new_only_counts(fw) -> bool:
    bc = X._find_script(fw, "poll_inverter_configuration_dispatch")
    cbody = next((b for _k, b in X.modbus_actions(bc) if b.get("start_address") == 330), {})
    for h in ("on_not_sent", "on_custom_response"):
        v = "\n".join(a.get("lambda", "") for a in (cbody.get(h) or {}).get("then") or [])
        if set(re.findall(r"id\((\w+)\)\s*(?:=(?!=)|\+\+|--)", v)) != {"configuration_failures"} or "publish_state" in v:
            return False
    return True


def _static_kill(fw, sid) -> bool:
    """True when the static detector `sid` rejects the firmware `fw`."""
    try:
        if sid == "S-R1":
            n, miss = st_handlers(fw)
            return n != 7 or bool(miss)
        if sid == "S-R3":
            sites, bad = st_stamps(fw)
            return sites != 2 or bool(bad)
        if sid == "S-P1":
            n, bad = st_guarded(fw)
            return n != 5 or bool(bad)
        if sid == "S-P2":
            return "catchup" not in X.interval_ids(fw)
        if sid == "S-R3b":
            return not _breaker_terms_ok(_breaker_cond(fw))
        if sid == "S-P4":
            return not _block_c_new_only_counts(fw)
        if sid == "S-P3":
            iv = X.interval_ids(fw)
            asp = next(a["if"] for a in fw["interval"][iv["rtc_tick"]]["then"] if "if" in a and
                       "auto_sync_pending" in a["if"]["condition"]["lambda"])
            return "tx_buffer_empty()" not in asp["condition"]["lambda"]
        if sid == "S-R2":
            wr = X._find_script(fw, "write_inverter_rtc")["then"]
            inner = wr[0]["if"]["else"][0]["if"]
            abort = "\n".join(a.get("lambda", "") for a in inner.get("else") or [] if "lambda" in a)
            rb = X._find_button(fw, "read_inverter_clock")["on_press"][0][ds.READ]
            ns = rb.get("on_not_sent", {}).get("then", [{}])[0].get("lambda", "")
            return "id(correction_in_progress) = false;" not in abort or "id(rtc_verify_dispatching) &&" not in ns
    except (KeyError, IndexError, StopIteration, TypeError):
        return True
    return False


# ============================================================================================================================
# main
# ============================================================================================================================
def section(title):
    print(f"\n{title}")
    return time.perf_counter()


def main() -> int:
    t_all = time.perf_counter()
    timings = {}

    t = section("[0] policy numbers derived from registry/rtc_policy.py (no number below is hard-coded)")
    check(f"derived: background threshold {N.BG} s, boot threshold {N.BOOT} s, precision threshold {N.PT} s, large error {N.LARGE} s, "
          f"background gap {N.GAP / 1000:.0f} s, deadline {D / 1000:.0f} s; quiet window around 10:30 = "
          f"[{N.QW_HH[0] - X.hms(10, 30)} s, +{N.QW_HH[1] - X.hms(10, 30)} s), precision window before 16:00 = "
          f"[{N.PW_16[0] - X.hms(16, 0)} s, {N.PW_16[1] - X.hms(16, 0)} s)",
          N.free_ok and N.BOOT <= N.BG and N.PT < N.BG and N.QW_HH[0] <= X.hms(10, 30) < N.QW_HH[1]
          and N.PW_16[1] <= X.hms(16, 0) and N.BG + 45 < N.LARGE, vars(N))
    timings["[0]"] = time.perf_counter() - t

    t = section("[1] RTC transaction (live firmware, deferred reads + writes, 120 ms frames)")
    rtc = [sc_success(None)]
    rtc += [sc_write_fail_twice(None, o) for o in ("error", "no_response_lost", "no_response_landed")]
    rtc += [sc_write_refused(None, o) for o in ("not_sent", "custom_response")]
    rtc += [sc_write_lost(None, o) for o in ("timeout_lost", "timeout_landed")]
    rtc += [sc_late_ack(None)]
    rtc += [sc_verify(None, o) for o in ("invalid", "error", "no_response", "not_sent", "custom_response", "timeout")]
    rtc += [sc_not_applied(None), sc_ntp_abort(None), sc_deferral(None)]
    rtc += [sc_auto_off(None, p) for p in ("asp", "write", "vp", "vra", "cfp")]
    rtc += [sc_manual(None, v) for v in ("idle", "cooldown", "during_auto", "auto_off", "lost")]
    rtc += [sc_breaker_state(None, st) for st in ("S1", "S2", "S3", "S4", "S5")]
    rtc += [sc_breaker_scope(None), sc_breaker_slow(None), sc_ha_refused(None), sc_ha_during_vp(None),
            sc_boot_no_ntp(None)]
    rtc += [sc_wrap(None, k) for k in ("success", "breaker", "cooldown")]
    rtc += [sc_quiet_dispatch(None)]
    rtc += [sc_inject(None, f) for f in ("verification_pending", "verification_read_active", "auto_sync_pending", "comm_failure_pending")]
    for r in rtc:
        report(r)
    report(sc_fuzz())
    timings["[1]"] = time.perf_counter() - t

    t = section("[2] policy wiring (oracle: firmware == rtc_policy.decide() on every regular read) and behaviour")
    pw = [sc_spike(None), sc_frozen(None), sc_quiet(None, "half-hour"), sc_quiet(None, "tou"), sc_lease(None), sc_precision(None),
          sc_precision(None, served=True), sc_boot(None, "A"), sc_boot(None, "B"), sc_min_gap(None), sc_night(None),
          sc_night(None, tou=X.GOLD_TOU, start=(2026, 10, 4, 22, 0, 0), label="TOU zone starts at 23:30 / 00:00 / 05:30"), sc_day(None),
          sc_dst(None, "fall-back"), sc_dst(None, "spring-forward")]
    pw += [sc_large_precision(None, v) for v in ("single", "lease", "two")]
    pw += [sc_zone_cross(None, w, sg) for w in ("half-hour", "tou") for sg in (1, -1)]
    for r in pw:
        report(r)
    timings["[2]"] = time.perf_counter() - t

    t = section("[3] polls (ownership re-checks, invalidation rule, dispatch stamp, catch-up)")
    pl = []
    for owner, dt in (("mwip", 1000), ("mwip", 2499), ("mwip", 2500), ("cip", 1000), ("sync", 1000), ("mwip", 2501)):
        pl.append(sc_tlm_owner(None, owner, dt))
    pl += [sc_tlm_handlers(None, b, o) for b in (59, 150) for o in ("not_sent", "custom_response")]
    pl += [sc_cfg_yield1(None, o) for o in ("mwip", "cip", "sync")]
    pl += [sc_cfg_yield2(None, "mwip"), sc_cfg_yield2(None, "cip")]
    pl += [sc_cfg_handler(None, b, o) for b in (200, 241, 330) for o in ("not_sent", "custom_response")]
    pl += [sc_poll_random(None), sc_catchup_yield(None), sc_catchup_rtc(None), sc_phase_locked(None)]
    for r in pl:
        report(r)
    timings["[3]"] = time.perf_counter() - t

    t = section("[4] fence (B10 Live Match through the real refresh script and the unchanged write fence)")
    for r in (sc_fence(None), sc_fence_divert(None), sc_fence_share(None)):
        report(r)
    timings["[4]"] = time.perf_counter() - t

    t = section("[5] static (live firmware)")
    static_section(X.load(LIVE))
    timings["[5]"] = time.perf_counter() - t

    t = section("[6] pre-FB-D1 firmware (== main): the 'fails on main' scenarios must FAIL there")
    pre_runs = [
        ("R04 write not_sent", lambda x: sc_write_refused(x, "not_sent")),
        ("R04 write custom_response", lambda x: sc_write_refused(x, "custom_response")),
        ("R06 write callback lost", lambda x: sc_write_lost(x, "timeout_lost")),
        ("R07 verification read not_sent", lambda x: sc_verify(x, "not_sent")),
        ("R07 verification read custom_response", lambda x: sc_verify(x, "custom_response")),
        ("R07 verification read lost", lambda x: sc_verify(x, "timeout")),
        ("R13 NTP-abort branch", sc_ntp_abort),
        ("R16 manual Sync, lost callback", lambda x: sc_manual(x, "lost")),
        ("R18 breaker S1 on a busy bus", lambda x: sc_breaker_state(x, "S1")),
        ("R18 breaker S3 on a busy bus", lambda x: sc_breaker_state(x, "S3")),
        ("R18 breaker S5 on a busy bus", lambda x: sc_breaker_state(x, "S5")),
        ("R23 quiet-bus write dispatch", sc_quiet_dispatch),
        ("I1 stray verification_pending", lambda x: sc_inject(x, "verification_pending")),
        ("I1 stray verification_read_active", lambda x: sc_inject(x, "verification_read_active")),
        ("I1 stray auto_sync_pending", lambda x: sc_inject(x, "auto_sync_pending")),
        ("I1 stray comm_failure_pending", lambda x: sc_inject(x, "comm_failure_pending")),
        ("PW1 one stale read", sc_spike),
        ("PW3 frozen image", sc_frozen),
        ("PW4 quiet window (half hour)", lambda x: sc_quiet(x, "half-hour")),
        ("PW4 quiet window (TOU zone start)", lambda x: sc_quiet(x, "tou")),
        ("PW5 energy transaction", sc_lease),
        ("PW6 precision window", sc_precision),
        ("PW7 boot alignment needs two reads", lambda x: sc_boot(x, "A")),
        ("PW7 background floor after alignment", lambda x: sc_boot(x, "B")),
        ("PW8 background gap", sc_min_gap),
        ("PW9 night of stale / frozen reads", sc_night),
        ("PW10 PV day", sc_day),
        ("PW11 DST fall-back", lambda x: sc_dst(x, "fall-back")),
        ("PW12 one large read inside the precision window", lambda x: sc_large_precision(x, "single")),
        ("PW13 zone cross at a half hour (positive error)", lambda x: sc_zone_cross(x, "half-hour", 1)),
        ("PW13 zone cross at a TOU zone start (positive error)", lambda x: sc_zone_cross(x, "tou", 1)),
        ("P01 telemetry, write mutex at +1000 ms", lambda x: sc_tlm_owner(x, "mwip", 1000)),
        ("P01 telemetry, RTC lock at +2500 ms (same-ms tie)", lambda x: sc_tlm_owner(x, "cip", 2500)),
        ("P01 telemetry, real Sync writer", lambda x: sc_tlm_owner(x, "sync", 1000)),
        ("P03 configuration, write mutex in delay 1", lambda x: sc_cfg_yield1(x, "mwip")),
        ("P03 configuration, real Sync writer in delay 1", lambda x: sc_cfg_yield1(x, "sync")),
        ("P04 configuration, owner in delay 2", lambda x: sc_cfg_yield2(x, "mwip")),
        ("P07 Block B custom_response", lambda x: sc_cfg_handler(x, 241, "custom_response")),
        ("P07 Block B not_sent", lambda x: sc_cfg_handler(x, 241, "not_sent")),
        ("P11 randomised owners", sc_poll_random),
        ("C1 catch-up after a yield", sc_catchup_yield),
        ("C2 catch-up after an RTC release", sc_catchup_rtc),
        ("C3 phase-locked owner", sc_phase_locked),
        ("F1 B10 after a correction", sc_fence),
        ("F2 diverted Block B", sc_fence_divert),
        ("F3 B10 availability", sc_fence_share),
    ]
    pre_failed = []
    for label, fn in pre_runs:
        r = fn(PRE)
        keys = [k for k in r.failed() if k != "inv"]
        pre_failed.append((label, keys))
        check(f"pre-FB-D1 FAILS {label} (failing: {', '.join(keys) or '-'})", bool(keys),
              "the scenario passes on main - it does not prove an FB-D1 change")
    fw_pre = X.load(PRE)
    n, miss = st_handlers(fw_pre)
    check(f"pre-FB-D1 FAILS S-R1 (missing terminal handlers on {len(miss)} of {n} actions)", bool(miss))
    sites, bad = st_stamps(fw_pre)
    check(f"pre-FB-D1 FAILS S-R3 (lock sites without a deadline stamp: {len(bad)} of {sites})", bool(bad))
    nr, badg = st_guarded(fw_pre)
    check(f"pre-FB-D1 FAILS S-P1 (delayed poll reads without a re-check: {len(badg)} of {nr})", bool(badg))
    timings["[6]"] = time.perf_counter() - t

    t = section("[7] mutants of the FB-D1 firmware (each dropped element must be killed by a named detector)")
    for mid, desc, mk, killers, static_id in MUTANTS:
        try:
            mtext = mk(LIVE)
        except (AssertionError, ValueError) as e:
            check(f"mutant {mid} ({desc}) applies to the live firmware exactly once", False, str(e))
            continue
        killed = []
        for label, fn, key in killers:
            r = fn(mtext)
            if key in r.failed():
                killed.append(f"{label} [{key}]")
        if static_id and _static_kill(X.load(mtext), static_id):
            killed.append(f"static {static_id}")
        check(f"mutant {mid} ({desc}) is killed by {killers[0][0]} [{killers[0][2]}]" + (f" and {static_id}" if static_id else ""),
              any(k.startswith(killers[0][0]) for k in killed) and (not static_id or f"static {static_id}" in killed), killed)
    timings["[7]"] = time.perf_counter() - t

    total = time.perf_counter() - t_all
    print("\nsection timings: " + ", ".join(f"{k} {v:.1f} s" for k, v in timings.items()) + f"; total {total:.1f} s")
    print(f"{N_CHECKS[0]} checks, {N_CHECKS[0] - len(FAILURES)} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-D1 liveness checks passed.")
    print("These prove the firmware lambdas' behaviour under the strict simulator's model of ESPHome, the Modbus hub and the inverter "
          "clock - not the compiled binary or the real inverter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
