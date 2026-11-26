"""Named adversarial scenarios, the invariants every run must keep and the table row of each result.

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. Not wired to Home Assistant, the dongle, the inverter or any register; stdlib
only; deterministic. A scenario is a bench.Scenario (what the world does) plus a Spec (what must hold). The invariants are judged
with the REAL kernel's constants (module KR below), never with the constants of a mutated copy that is being tested.

Invariants (every run; each is True, False or None = does not apply to this kind of run):
  RESERVE_FLOOR          an export never discharges below max(Stop SOC, the effective reserve in force one reaction time earlier)
  IMPORT_CEILING         with an import ceiling configured, no breach caused by the charger lasts longer than the reaction bound
  POWER_CEILING          every setpoint written is inside [500 W, ceiling] and, for a lease, never above the pre-session value
  BUDGETS                dwell, change count, write count (charge) and settle, write count (export) are never exceeded
  REACHES_OR_REPORTS     the target is reached by the deadline, or 'unreachable' was reported at least 15 min before it
  NEVER_WORSE_THAN_TODAY a night that today's fixed rate would have won (target reached 25 minutes before the window end) is not lost (Gentle)
  NO_UNTRUSTED_ACTUATION no start, change or loop write while the clock it depends on is untrusted
  ONE_WRITER             at most one lease at a time and every write belongs to the lease that is open
  EXPLAINED              every decision has a reason from the closed list, a detail from its list and a non-empty sentence
  RESTORED_OR_ALERTED    at the end no lowered or overriding value is left silently: the owner's values are back, or an alert was raised
  PHYSICAL               the battery stays between 0 and 100 percent and every number is finite

A scenario passes when every applicable invariant holds (a KNOWN GAP must fail exactly as documented, with its backstop shown) and
every expectation of the spec holds.
"""

import math
from collections import Counter
from dataclasses import dataclass, replace

import kernel as KR
import plant as P
import bench as B
from bench import Scenario

TICK = P.DT_S
INVARIANTS = ("RESERVE_FLOOR", "IMPORT_CEILING", "POWER_CEILING", "BUDGETS", "REACHES_OR_REPORTS", "NEVER_WORSE_THAN_TODAY", "NO_UNTRUSTED_ACTUATION",
              "ONE_WRITER", "EXPLAINED", "RESTORED_OR_ALERTED", "PHYSICAL")
SETPOINT_REGS = ("slot_power_w", "fp_rate_w", "dump_ceiling_w")
REPORT_LEAD_S = 900.0     # an unreachable target must be reported at least this long before the deadline
TARGET_TOL = 0.5          # the reading is whole percent: a true SOC within half a point of the target reads as the target


# ---------------------------------------------------------------------------------------------------------------------------
# small helpers over a Run
# ---------------------------------------------------------------------------------------------------------------------------
def row_at(run, t):
    i = min(len(run.rows) - 1, max(0, int(round(t / TICK)) - 1))
    return run.rows[i]


def deadline_s(sc):
    return sc.window[1] - sc.buffer_s


def saw(run, who, reason, detail=None):
    return any(r.who == who and r.reason == reason and (detail is None or r.detail == detail) for r in run.recs)


def first(run, who, reason, detail=None):
    for r in run.recs:
        if r.who == who and r.reason == reason and (detail is None or r.detail == detail):
            return r
    return None


def lease_reasons(run):
    return [l["reason"] for l in run.leases]


def writes(run, kind=None, ok=True):
    return [w for w in run.writes if (kind is None or w.kind == kind) and (w.ok or not ok)]


def reserve_at(sc, t):
    v = sc.reserve_pct
    for (t0, name, a) in sorted(sc.events, key=lambda e: e[0]):
        if name == "reserve" and t0 <= t:
            v = a["pct"]
    return v


def power_ceiling_at(sc, t):
    v = sc.power_ceiling_w
    for (t0, name, a) in sorted(sc.events, key=lambda e: e[0]):
        if name == "power_ceiling" and t0 <= t:
            v = a["w"]
    return v


def codes_of(run):
    c = Counter()
    for r in run.recs:
        c[r.reason + "/" + r.detail] += 1
    return c


# ---------------------------------------------------------------------------------------------------------------------------
# invariants: (ok or None, detail)
# ---------------------------------------------------------------------------------------------------------------------------
def inv_reserve_floor(run):
    sc = run.sc
    if sc.kind != "export":
        return None, "n/a (not an export)"
    worst = None
    for r in run.rows:
        if r.mode == "export" and r.batt > 0:
            floor = max(sc.stop_soc_pct, reserve_at(sc, r.t - sc.react_s))
            gap = r.soc - floor
            if worst is None or gap < worst[0]:
                worst = (gap, r.t, floor)
    if worst is None:
        return True, "no discharge happened"
    return worst[0] >= 0.0, "lowest margin over the floor %.2f points at t=%d s (floor %.1f)" % (worst[0], worst[1], worst[2])


def inv_import_ceiling(run):
    sc = run.sc
    if sc.kind == "export":
        return None, "n/a (not a charge)"
    ceilings = [r.imp_ceiling for r in run.rows if r.imp_ceiling is not None]
    if not ceilings:
        return None, "no import ceiling configured (the plan says so)"
    longest, cur, peak = 0, 0, 0.0
    # ECCO answers for the charge only while it holds (or is about to take) the session; after the last session has ended the owner's own
    # table is charging at the owner's own rate, which the owner chose (the plan says so)
    ends = [l["end_t"] for l in run.leases]
    last_end = float("inf") if (not ends or any(e is None for e in ends)) else max(ends)
    for r in run.rows:
        breach = (r.t <= last_end and r.imp_ceiling is not None and r.grid > r.imp_ceiling and r.ac_in > 0.0 and r.house < r.imp_ceiling)
        if breach:
            cur += 1
            peak = max(peak, r.grid)
        else:
            cur = 0
        longest = max(longest, cur)
    bound = sc.react_s + TICK
    return longest * TICK <= bound, "longest charger-caused breach %d s (bound %d s), peak import %.0f W" % (longest * TICK, bound, peak)


def inv_power_ceiling(run):
    sc = run.sc
    bad = []
    n = 0
    for w in run.writes:
        if not w.ok or w.kind not in ("start", "change", "forced", "loop") or w.reg not in SETPOINT_REGS:
            continue
        n += 1
        if sc.kind == "export":
            lo, hi = KR.EXPORT_MIN_CEILING_W, sc.lease_ceiling_w
        elif sc.kind == "gentle":
            lo, hi = KR.CHARGE_MIN_W, min(power_ceiling_at(sc, w.t), sc.original_w)
        else:
            lo, hi = KR.CHARGE_MIN_W, power_ceiling_at(sc, w.t)
        if w.value < lo - 1e-9 or w.value > hi + 1e-9:
            bad.append((w.t, w.kind, w.value, lo, hi))
    if n == 0:
        return True, "no setpoint written"
    return not bad, ("%d writes checked" % n) if not bad else "out of range: %s" % (bad[:3],)


def inv_budgets(run):
    sc = run.sc
    problems = []
    for l in run.leases:
        mine = [w for w in run.writes if w.lease_id == l["id"] and w.ok]
        if l["kind"] == "gentle":
            ch = [w.t for w in mine if w.kind == "change"]
            if len(ch) > KR.CHARGE_MAX_CHANGES:
                problems.append("lease %d: %d changes" % (l["id"], len(ch)))
            for a, b in zip(ch, ch[1:]):
                if b - a < KR.CHARGE_DWELL_S - 1e-9:
                    problems.append("lease %d: changes %d s apart" % (l["id"], b - a))
            if len(mine) > KR.CHARGE_NIGHT_WRITES:
                problems.append("lease %d: %d writes in the night" % (l["id"], len(mine)))
            for w in mine:
                if w.kind == "forced" and w.value < 0:
                    problems.append("negative forced write")
        elif l["kind"] == "export":
            lp = [w.t for w in mine if w.kind == "loop"]
            if len(lp) > KR.EXPORT_MAX_WRITES:
                problems.append("lease %d: %d loop writes" % (l["id"], len(lp)))
            st = [w.t for w in mine if w.kind == "start"]
            pts = sorted(st[:1] + lp)
            for a, b in zip(pts, pts[1:]):
                if b - a < KR.EXPORT_SETTLE_S - 1e-9:
                    problems.append("lease %d: writes %d s apart" % (l["id"], b - a))
        else:
            if len([w for w in mine if w.kind in ("start", "change", "loop", "forced")]) > 1:
                problems.append("lease %d: a fixed-rate session wrote more than once" % l["id"])
    budget_refusals = [r for r in run.refusals if "budget" in r[2] or "dwell" in r[2]]
    if budget_refusals:
        problems.append("the dongle refused %d requests for the budget" % len(budget_refusals))
    return not problems, "; ".join(problems[:3]) if problems else "all budgets kept"


def inv_reaches_or_reports(run):
    sc = run.sc
    if sc.kind == "export":
        return None, "n/a (not a charge)"
    dl = deadline_s(sc)
    r = row_at(run, dl)
    best = max(x.read for x in run.rows if x.t <= dl)
    reached = best >= sc.target_soc_pct - 1e-9
    if reached:
        return True, "the SOC reading reached %.0f by the deadline (target %.0f)" % (best, sc.target_soc_pct)
    t = run.first_unreachable_t
    if t is not None and t <= dl - REPORT_LEAD_S:
        return True, "target missed (SOC %.1f) but reported %s at t=%d s, %d min before the deadline" % (r.soc, run.first_unreachable_detail, t, (dl - t) / 60)
    return False, "SOC %.1f at the deadline (target %.0f) and no timely report (first report %s)" % (r.soc, sc.target_soc_pct, t)


def inv_never_worse(run):
    """REQ-A12: the same night without ECCO (today's fixed rate in force all night) is run beside it; whenever that reaches the target at
    least END_MARGIN_S + GUARD_MARGIN_S before the window end, the Gentle night must reach it by the window end."""
    sc = run.sc
    if sc.kind != "gentle":
        return None, "n/a (not a Gentle night)"
    base = getattr(run, "baseline", None)
    if base is None:
        return None, "no baseline run"
    we = sc.window[1]
    today = max(x.read for x in base.rows if x.t <= we - KR.END_MARGIN_S - KR.GUARD_MARGIN_S) >= sc.target_soc_pct - 1e-9
    ours = max(x.read for x in run.rows if x.t <= we) >= sc.target_soc_pct - 1e-9
    if not today:
        return True, "today's rate would not have made it either (nothing to compare)"
    return ours, "today's rate reaches the target in good time and so does the session" if ours else "today's rate would have reached the target and the session did not"


def inv_no_untrusted(run):
    bad = []
    for w in run.writes:
        if w.ok and w.kind in ("start", "change", "loop") and not row_at(run, w.t).time_ok:
            bad.append((w.t, w.kind))
    return not bad, "no start/change/loop write under untrusted time" if not bad else "wrote under untrusted time: %s" % (bad[:3],)


def inv_one_writer(run):
    problems = []
    ls = sorted(run.leases, key=lambda l: l["start_t"])
    for a, b in zip(ls, ls[1:]):
        if a["end_t"] is None or a["end_t"] > b["start_t"] + 1e-9:
            problems.append("lease %d overlaps lease %d" % (a["id"], b["id"]))
    byid = {l["id"]: l for l in run.leases}
    for w in run.writes:
        l = byid.get(w.lease_id)
        if l is None:
            problems.append("write by unknown lease %s" % w.lease_id)
        elif w.t < l["start_t"] - 1e-9 or (l["end_t"] is not None and w.t > l["end_t"] + 1e-9):
            problems.append("write at %d outside lease %d" % (w.t, l["id"]))
        elif w.owner != l["owner"]:
            problems.append("write by %s inside the lease of %s" % (w.owner, l["owner"]))
    return not problems, "; ".join(problems[:3]) if problems else "%d lease(s), one owner each, no overlap" % len(ls)


def inv_explained(run):
    problems = []
    for r in run.recs:
        if r.reason not in KR.REASONS or r.detail not in KR.DETAILS.get(r.reason, ()):
            problems.append("%s/%s not in the closed list" % (r.reason, r.detail))
        elif not r.explanation.strip() or "?" in r.explanation or "No explanation" in r.explanation:
            problems.append("bad explanation for %s/%s: %r" % (r.reason, r.detail, r.explanation[:60]))
    for w in run.writes:
        if w.ok and w.kind in ("start", "change", "forced", "loop") and w.reg in SETPOINT_REGS:
            if not any(r.write == w.value and r.t <= w.t + 1e-9 for r in run.recs):
                problems.append("write %s=%s at %d has no decision" % (w.reg, w.value, w.t))
    for l in run.leases:
        if l["end_t"] is not None and not any(r.end and l["start_t"] - 1e-9 <= r.t <= l["end_t"] + 1e-9 for r in run.recs):
            problems.append("lease %d ended (%s) with no stopping decision" % (l["id"], l["reason"]))
    return not problems, "; ".join(problems[:3]) if problems else "%d decisions, all with a closed-list reason and a sentence" % len(run.recs)


def inv_restored_or_alerted(run):
    sc = run.sc
    last = run.rows[-1]
    running = [l for l in run.leases if l["end_t"] is None]
    if running and all(l["planned_end"] > sc.duration_s for l in running):
        return True, "a session is still running and its planned end is after this run"
    lowered = last.fp_w > 0 or last.dump_w > 0 or (sc.kind == "gentle" and abs(last.slot_w - sc.original_w) > 1e-9)
    if not (running or lowered):
        return True, "the owner's values are back and no session is open"
    return bool(run.alerts), ("a value is still overridden at the end; alerts: %s" % ([a[1][:50] for a in run.alerts][:2],)) if run.alerts else         "a value is still overridden at the end and NOBODY WAS ALERTED"


def inv_physical(run):
    for r in run.rows:
        vals = (r.soc, r.batt, r.grid, r.house, r.pv, r.inv)
        if any(math.isnan(v) or math.isinf(v) for v in vals) or r.soc < -1e-6 or r.soc > 100.0 + 1e-6:
            return False, "non-physical value at t=%d" % r.t
    return True, "SOC %.1f to %.1f" % (min(r.soc for r in run.rows), max(r.soc for r in run.rows))


CHECKS = {"RESERVE_FLOOR": inv_reserve_floor, "IMPORT_CEILING": inv_import_ceiling, "POWER_CEILING": inv_power_ceiling, "BUDGETS": inv_budgets,
          "REACHES_OR_REPORTS": inv_reaches_or_reports, "NEVER_WORSE_THAN_TODAY": inv_never_worse, "NO_UNTRUSTED_ACTUATION": inv_no_untrusted, "ONE_WRITER": inv_one_writer,
          "EXPLAINED": inv_explained, "RESTORED_OR_ALERTED": inv_restored_or_alerted, "PHYSICAL": inv_physical}


def check_invariants(run, skip=()):
    return {name: CHECKS[name](run) for name in INVARIANTS if name not in skip}


# ---------------------------------------------------------------------------------------------------------------------------
# specs and results
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    sc: Scenario
    expect: tuple = ()                 # ((name, fn(run) -> (ok, detail)), ...)
    known_gap: tuple = ()              # ((invariant, why it fails and what backstop applies), ...): the invariant MUST fail
    skip: tuple = ()                   # invariants this scenario does not claim (with the reason in the summary)
    backstop: str = ""                 # what protects the owner when no firmware guard can run (shown in the table)
    covers: tuple = ()                 # requirement ids this scenario exercises (REQUIREMENTS.md)


@dataclass
class Result:
    name: str
    outcome: str
    inv: dict
    expect: dict
    writes: int
    final_soc: float
    codes: tuple
    failures: list
    ok: bool
    backstop: str = ""


def outcome_of(run):
    sc = run.sc
    ls = run.leases
    if sc.kind == "export":
        if not ls:
            return "NO_START"
        why = ls[-1]["reason"]
        if why is None:
            return "RUNNING AT END"
        return {"lease_end": "EXPORTED TO END", "floor_reached": "STOPPED AT FLOOR", "reserve_rose": "STOPPED AT NEW RESERVE"}.get(why, "STOPPED (%s)" % why)
    dl = deadline_s(sc)
    r = row_at(run, dl)
    reached = max(x.read for x in run.rows if x.t <= dl) >= sc.target_soc_pct - 1e-9
    if not run.writes:
        return "NO_START, TARGET REACHED" if reached else ("NO_START, REPORTED" if run.first_unreachable_t is not None else "NO_START")
    if reached:
        return "REACHED" + ("" if not ls or ls[-1]["reason"] in (None, "target_reached") else " (lease ended: %s)" % ls[-1]["reason"])
    return "REPORTED EARLY" if run.first_unreachable_t is not None else "MISSED"


def evaluate(spec, run):
    inv = check_invariants(run, spec.skip)
    gaps = dict(spec.known_gap)
    failures = []
    for name, (ok, detail) in inv.items():
        if name in gaps:
            if ok:
                failures.append("%s was expected to FAIL as a documented gap but held" % name)
        elif ok is False:
            failures.append("%s: %s" % (name, detail))
    exp = {}
    for name, fn in spec.expect:
        ok, detail = fn(run)
        exp[name] = (ok, detail)
        if not ok:
            failures.append("expect %s: %s" % (name, detail))
    last = run.rows[-1]
    backstop = "; ".join(["%s: %s" % (k, v) for k, v in gaps.items()] + ([spec.backstop] if spec.backstop else []))
    return Result(name=spec.sc.name, outcome=outcome_of(run) if not gaps else "KNOWN GAP (documented)", inv=inv, expect=exp, writes=len(run.writes),
                  final_soc=last.soc, codes=tuple(sorted(codes_of(run))), failures=failures, ok=not failures, backstop=backstop)


def run_spec(spec, K):
    run = B.run_scenario(spec.sc, K)
    if spec.sc.kind == "gentle":
        # the same night with no ECCO at all: Home Assistant never plans, so today's fixed rate stays in force
        run.baseline = B.run_scenario(replace(spec.sc, events=spec.sc.events + ((0.0, "plan_stop", {}),)), K)
    return run, evaluate(spec, run)


# ---------------------------------------------------------------------------------------------------------------------------
# expectations: small predicates over a run, each returns (ok, detail)
# ---------------------------------------------------------------------------------------------------------------------------
def X_reached():
    def f(run):
        best = max(x.read for x in run.rows if x.t <= deadline_s(run.sc))
        return best >= run.sc.target_soc_pct - 1e-9, "highest SOC reading by the deadline %.0f (target %.0f)" % (best, run.sc.target_soc_pct)
    return ("target reached by the deadline", f)


def X_reached_by_window_end():
    def f(run):
        r = run.rows[-1]
        return r.soc >= run.sc.target_soc_pct - TARGET_TOL, "SOC %.1f at the end (target %.0f)" % (r.soc, run.sc.target_soc_pct)
    return ("target reached by the window end (never worse than today)", f)


def X_saw(who, reason, detail=None, present=True):
    label = "%s %s/%s %s" % (who, reason, detail or "*", "seen" if present else "NOT seen")

    def f(run):
        got = saw(run, who, reason, detail)
        return got == present, "yes" if got else "no"
    return (label, f)


def X_lease_ended(reason):
    def f(run):
        got = lease_reasons(run)
        return reason in got, "lease reasons %s" % (got,)
    return ("a lease ended with reason %s" % reason, f)


def X_lease_ended_any(reasons):
    def f(run):
        got = lease_reasons(run)
        return any(r in reasons for r in got), "lease reasons %s" % (got,)
    return ("a lease ended with one of %s" % (reasons,), f)


def X_no_writes():
    return ("nothing was written", lambda run: (not run.writes, "%d writes" % len(run.writes)))


def X_writes_at_most(n, kind=None):
    def f(run):
        c = len(writes(run, kind))
        return c <= n, "%d writes" % c
    return ("at most %d %s writes" % (n, kind or "register"), f)


def X_first_write_after(t):
    def f(run):
        ws = writes(run)
        return bool(ws) and ws[0].t >= t, "first write at %s" % (ws[0].t if ws else None)
    return ("the first write is not before t=%d s" % t, f)


def X_alert(sub, by_s=None):
    def f(run):
        hit = [a for a in run.alerts if sub in a[1]]
        return bool(hit) and (by_s is None or hit[0][0] <= by_s), "alerts %s" % ([(a[0], a[1][:40]) for a in run.alerts][:2],)
    return ("the owner was alerted (%s)%s" % (sub, "" if by_s is None else " by t=%d s" % by_s), f)


def X_refused(sub):
    def f(run):
        hit = [r for r in run.refusals if sub in r[2]]
        return bool(hit), "refusals %s" % ([(r[0], r[2][:40]) for r in run.refusals][:3],)
    return ("a start was refused (%s)" % sub, f)


def X_lease_ends_within(event_t, within_s):
    def f(run):
        ends = [l["end_t"] for l in run.leases if l["end_t"] is not None and l["end_t"] >= event_t - 1e-9]
        return bool(ends) and min(ends) - event_t <= within_s, "ended %s s after the event" % (None if not ends else min(ends) - event_t)
    return ("the session ended within %d s of the event" % within_s, f)


def X_slot_restored_after(t):
    def f(run):
        r = row_at(run, t)
        return abs(r.slot_w - run.sc.original_w) < 1e-9, "slot power %.0f W at t=%d s" % (r.slot_w, t)
    return ("the owner's slot power is back by t=%d s" % t, f)


def X_mean_setpoint_below(frac):
    def f(run):
        v = [r.slot_w for r in run.rows if r.lease]
        m = sum(v) / len(v) if v else run.sc.original_w
        return m < frac * run.sc.original_w, "mean setpoint in the lease %.0f W (%.0f %% of today's)" % (m, 100 * m / run.sc.original_w)
    return ("gentler than today: mean setpoint below %.0f %% of the original" % (100 * frac), f)


def X_changes_at_most(n):
    def f(run):
        c = len(writes(run, "change"))
        return c <= n, "%d changes" % c
    return ("at most %d ordinary changes" % n, f)


def X_no_write_between(t0, t1, kinds=("start", "change", "loop")):
    def f(run):
        bad = [(w.t, w.kind) for w in run.writes if w.ok and w.kind in kinds and t0 <= w.t < t1]
        return not bad, "writes %s" % (bad[:3],)
    return ("no %s write between t=%d and %d s" % ("/".join(kinds), t0, t1), f)


def X_export_tracks(t0, band_w):
    def f(run):
        rows = [r for r in run.rows if r.t >= t0 and r.lease and r.mode == "export"]
        if not rows:
            return False, "no export rows"
        m = sum(-r.grid for r in rows) / len(rows)
        return abs(m - run.sc.target_export_w) <= band_w, "mean net export %.0f W against the %.0f W target" % (m, run.sc.target_export_w)
    return ("the mean net export is within %d W of the target after t=%d s" % (band_w, t0), f)


def X_never_charges_from_export():
    def f(run):
        rows = [r for r in run.rows if r.lease and r.mode == "export"]
        worst = min([r.batt for r in rows] or [0.0])
        return worst >= -1.0, "lowest battery power in the session %.0f W (negative = charging)" % worst
    return ("the battery is never charged to absorb solar", f)


def X_min_soc_at_least(x):
    def f(run):
        rows = [r for r in run.rows if r.lease]
        m = min([r.soc for r in rows] or [100.0])
        return m >= x, "lowest SOC while a session was open %.1f" % m
    return ("the SOC never falls below %.0f while a session is open" % x, f)


def X_unserved_at_most(s):
    def f(run):
        n = sum(1 for r in run.rows if r.unserved > 1.0) * TICK
        return n <= s, "%d s with house load unserved" % n
    return ("the house is unserved for at most %d s" % s, f)


def X_gain_measured_near(g, tol=0.02):
    def f(run):
        w = [x for x in run.writes if x.kind == "start"]
        if not w:
            return False, "no start"
        # the first setpoint divided by the plan: not observable here; use the plant's measured ratio after the start
        rows = [r for r in run.rows if r.lease and r.ac_in > 0 and r.slot_w > 0 and r.t > w[0].t + 120]
        if not rows:
            return False, "no rows"
        r = rows[0]
        return abs(r.ac_in / r.slot_w - g) <= tol * g + 0.02, "realised AC / setpoint %.3f (expected %.3f)" % (r.ac_in / r.slot_w, g)
    return ("the realised AC power over the setpoint is about %.3f" % g, f)


def X_reported_by(t_s):
    def f(run):
        t = run.first_unreachable_t
        return t is not None and t <= t_s, "first unreachable report at %s" % t
    return ("unreachable reported by t=%d s" % t_s, f)


def X_report_between(t0, t1):
    def f(run):
        t = run.first_unreachable_t
        return t is not None and t0 <= t <= t1, "first unreachable report at %s" % t
    return ("the first unreachable report is between t=%d and %d s" % (t0, t1), f)


def X_leases_count(n):
    def f(run):
        return len(run.leases) == n, "%d lease(s)" % len(run.leases)
    return ("exactly %d lease(s) in the night" % n, f)


def X_never_worse_binding():
    """The never-worse comparison is not vacuous on this night: today's fixed rate (the same night with no ECCO) reaches the target at least
    END_MARGIN_S + GUARD_MARGIN_S before the window end, so the session MUST reach it too (REQ-A12)."""
    def f(run):
        base = getattr(run, "baseline", None)
        if base is None:
            return False, "no baseline run"
        we = run.sc.window[1]
        got = max(x.read for x in base.rows if x.t <= we - KR.END_MARGIN_S - KR.GUARD_MARGIN_S)
        return got >= run.sc.target_soc_pct - 1e-9, "today's rate reads %.0f %d s before the window end (target %.0f)" % (got, KR.END_MARGIN_S + KR.GUARD_MARGIN_S, run.sc.target_soc_pct)
    return ("today's fixed rate reaches the target in good time (the never-worse comparison binds)", f)


def X_min_decisions(n):
    return ("at least %d decisions were explained" % n, lambda run: (len(run.recs) >= n, "%d decisions" % len(run.recs)))


# ---------------------------------------------------------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------------------------------------------------------
def S(name, kind, summary, **kw):
    return Scenario(name=name, kind=kind, summary=summary, **kw)


def gentle(name, summary, **kw):
    return S(name, "gentle", summary, **kw)


def fixed(name, summary, **kw):
    kw.setdefault("table_charges", False)
    return S(name, "charge_fixed", summary, **kw)


def export(name, summary, **kw):
    base = dict(window=None, duration_s=9000.0, soc0_pct=80.0, plan_s=120.0, react_s=200.0, house=P.Series([(0.0, 1000.0)]))
    base.update(kw)
    base.setdefault("export_len_s", base["duration_s"] - 900.0)
    return S(name, "export", summary, **base)


def Hs(*pts):
    return P.Series(list(pts))


GENTLE_PAYLOAD = {"kind": "gentle", "owner": "gentle", "first_w": 5000.0, "gain": 1.1225,
                  "obj": KR.ChargeObjective(90.0, 14400.0, 18000.0, 35.0), "lim": KR.Limits()}
EXPORT_PAYLOAD = {"kind": "export", "owner": "export", "first_w": 2000.0, "stop_soc": 26.0,
                  "obj": KR.ExportObjective(2000.0, 25.0, 30000.0, 35.0, 3000.0), "lim": KR.Limits()}

SPECS = []


def add(sc, *expect, covers=(), known_gap=(), skip=(), backstop=""):
    SPECS.append(Spec(sc=sc, expect=tuple(expect), known_gap=tuple(known_gap), skip=tuple(skip), covers=tuple(covers), backstop=backstop))


# ----- Gentle: the closed loop on a charge window 00:30-05:30 (300 min), deadline = window end - 60 min -----------------------
add(gentle("g01_nominal", "Nominal night: 25 to 90 percent, light house load; the lowest practical rate, re-planned from the measured SOC."),
    X_reached(), X_mean_setpoint_below(0.9), X_changes_at_most(5), X_saw("ha", "increase", "start"), X_saw("dongle", "stop", "target_reached"),
    X_min_decisions(10),
    covers=("REQ-A1", "REQ-A2", "REQ-A5", "REQ-A8", "REQ-A12", "REQ-B4", "REQ-B7", "REQ-B8", "REQ-B10", "REQ-B11", "REQ-C9"))
add(gentle("g02_heavy_overnight_load", "A heavy overnight house load (4.5 kW for 90 minutes) with no import ceiling: the grid carries it, progress is unaffected, so the rate is held.",
           house=Hs((0, 800), (5400, 4500), (10800, 800))),
    X_reached(), X_saw("ha", "increase", "behind_plan", present=False),
    covers=("REQ-A3", "REQ-A10", "REQ-B5"))
add(gentle("g03_heavy_load_import_ceiling", "The same load with an 11 kW import ceiling: import would pass it, so the setpoint is lowered at once and the target reported at risk.",
           house=Hs((0, 800), (3600, 5000), (9000, 800)), import_ceiling_w=11000.0),
    X_saw("dongle", "reduce", "import_ceiling"), X_reported_by(14400 - REPORT_LEAD_S),
    covers=("REQ-A4", "REQ-A7", "REQ-A9", "REQ-B5", "REQ-C10", "REQ-D2"))
add(gentle("g04_load_removal", "A heavy load for 30 minutes then sudden removal, with an import ceiling: the forced reduction is undone only after the dwell and hysteresis.",
           house=Hs((0, 800), (3600, 5000), (5400, 800)), import_ceiling_w=11000.0),
    X_saw("dongle", "reduce", "import_ceiling"), X_changes_at_most(5),
    covers=("REQ-A6", "REQ-A10"))
add(gentle("g05_kettle_spikes", "Kettle-sized bursts (3 kW for 3 minutes every 25 minutes) with a roomy import ceiling: no rate change follows a burst.",
           house=P.Series([(0.0, 800.0)], spikes=[(900.0 + 1500.0 * i, 180.0, 3000.0) for i in range(9)]), import_ceiling_w=16000.0),
    X_reached(), X_saw("dongle", "reduce", "import_ceiling", present=False), X_changes_at_most(4),
    covers=("REQ-A6",))
add(gentle("g06_high_start_soc", "High starting SOC: 80 to 95 percent, so the plan is gentle and short.", soc0_pct=80.0, target_soc_pct=95.0),
    X_reached(),
    covers=("REQ-A5", "REQ-A10"))
add(gentle("g07_low_start_soc_tight", "Low starting SOC and a short window: 8 to 100 percent in four hours cannot make a 60 minute buffer; 'unreachable' is said at the first plan tick.",
           soc0_pct=8.0, target_soc_pct=100.0, window=(0.0, 14400.0), duration_s=14400.0),
    X_reported_by(600), X_no_writes(),
    covers=("REQ-A9", "REQ-A10", "REQ-B8"))
add(gentle("g08_efficiency_drop", "Charging efficiency falls from 0.945 to 0.70 after 30 minutes: the SOC lags the pessimistic projection, the progress tracker flags it and the rate is raised in bounded steps; any shortfall is reported.",
           soc0_pct=25.0, events=((1800.0, "plant", {"charge_eff": 0.70}),)),
    X_saw("ha", "increase", "behind_plan"),
    covers=("REQ-A3", "REQ-A4", "REQ-A10"))
add(gentle("g09_efficiency_gain", "Efficiency better than assumed (0.97) and a smaller battery (30 kWh): ahead of the plan, the rate is lowered.",
           plant=P.PlantParams(charge_eff=0.97, capacity_kwh=30.0)),
    X_reached(), X_saw("ha", "reduce", "ahead_of_plan"),
    covers=("REQ-A5", "REQ-A10"))
add(gentle("g10_taper_cliff_98", "Charge to 100 percent through the measured plateau, the cliff at 98 percent and the trickle: the planner's pessimistic knee (90) says 'at risk' where the real knee (98) lets the night reach, so the plan is conservative and never optimistic.",
           soc0_pct=40.0, target_soc_pct=100.0, slot_target_pct=100.0),
    X_reached(), X_min_decisions(10),
    covers=("REQ-A7", "REQ-A12", "REQ-B6"))
add(gentle("g11_unit_ac_watts", "Unit alternative: the setpoint is AC grid watts (scale 1.0). The plan measures the gain; it never assumes it.",
           plant=P.PlantParams(unit_scale=1.0)),
    X_reached(), X_gain_measured_near(1.0),
    covers=("REQ-A7", "REQ-B18"))
add(gentle("g12_unit_dc_watts", "Unit alternative: the setpoint is DC battery watts (scale 1/0.945).",
           plant=P.PlantParams(unit_scale=1.0 / 0.945)),
    X_reached(), X_gain_measured_near(1.0 / 0.945),
    covers=("REQ-A7", "REQ-B18"))
add(gentle("g13_unit_wrong_x10", "Unit wrong by 10x (every setpoint above 800 W hits the AC cap): the first lowered setpoint changes nothing, the gain is implausible, the lease ends and the original rate stands.",
           plant=P.PlantParams(unit_scale=11.225), soc0_pct=60.0, target_soc_pct=85.0),
    X_lease_ended_any(("implausible_gain", "no_response", "runaway")), X_reached(),
    covers=("REQ-B18", "REQ-D3"))
add(gentle("g14_unit_wrong_div10", "Unit wrong by 10x the other way (the charge at the original setpoint is under 1 kW): nothing is started, the owner is told no charge is running.",
           plant=P.PlantParams(unit_scale=0.11225), duration_s=3600.0),
    X_saw("ha", "blocked", "no_charge_running"), X_no_writes(),
    skip=("REACHES_OR_REPORTS",), covers=("REQ-B18",))
add(gentle("g15_unbound_response", "H2/H3: the slot power does not bind the charge. The first change shows no response, the lease ends, today's rate stands.",
           plant=P.PlantParams(charge_response="unbound"), soc0_pct=60.0, target_soc_pct=85.0),
    X_lease_ended_any(("implausible_gain", "no_response", "runaway")), X_reached(),
    covers=("REQ-A7", "REQ-B17", "REQ-B18", "REQ-D3"))
add(gentle("g15b_charge_floor_weak_response", "The charger cannot throttle below 8.7 kW: a lowered setpoint moves the power by less than a third of what it should; the measured gain leaves its band at the next change, the lease ends and today's rate stands.",
           plant=P.PlantParams(charge_min_ac_w=8700.0)),
    X_lease_ended_any(("no_response", "implausible_gain")), X_reached(),
    covers=("REQ-A7", "REQ-B17", "REQ-B18", "REQ-D3"))
add(gentle("g16_target_already_reached", "The battery is already above the target: nothing is started and the plan says why.", soc0_pct=92.0, duration_s=3600.0),
    X_no_writes(), X_saw("ha", "stop", "target_reached"),
    covers=("REQ-A10", "REQ-B4"))
add(gentle("g17_delayed_commands", "Every command takes 90 seconds to reach the dongle: budgets and dwell still hold.", cmd_delay_s=90.0, react_s=300.0),
    X_reached(),
    covers=("REQ-B22", "REQ-C5"))
add(gentle("g18_start_command_lost", "The first command (the start) is lost in transit: Home Assistant sees no lease and sends it again.", cmd_loss=frozenset({0})),
    X_first_write_after(600), X_reached(),
    covers=("REQ-B22", "REQ-C12"))
add(gentle("g19_inverter_ignores_write", "From 10 minutes in the inverter takes no new value: the next change fails its readback, the restore fails three times and the owner is alerted (FAULT).",
           events=((600.0, "ignore_writes", {"on": True}),)),
    X_alert("FAULT"),
    covers=("REQ-C7", "REQ-C12", "REQ-D5"))
add(gentle("g20_telemetry_short_gap", "A 60 second telemetry gap (under the 90 second bound): nothing stops, nothing is raised on stale data.", tel_gaps=((3600.0, 3660.0),)),
    X_reached(), X_lease_ended("target_reached"),
    covers=("REQ-B3",))
add(gentle("g21_telemetry_long_gap", "A 5 minute telemetry gap: beyond the bound the lease ends and today's rate takes over.", tel_gaps=((3600.0, 3900.0),)),
    X_lease_ended("stale_telemetry"), X_reached(), X_no_write_between(3600, 3900),
    covers=("REQ-B3", "REQ-B9"))
add(gentle("g22_soc_unavailable_at_start", "No telemetry for the first 12 minutes: nothing is started on missing data.", tel_gaps=((0.0, 700.0),)),
    X_first_write_after(700), X_saw("ha", "blocked", "stale_telemetry"), X_reached(),
    covers=("REQ-B3",))
add(gentle("g23_restart_in_lease", "The dongle restarts in the middle of the lease: the snapshot is restored at boot and the lease is never resumed.",
           events=((6000.0, "dongle_restart", {"boot_s": 60.0}),)),
    X_lease_ended("restart"), X_reached(), X_slot_restored_after(6300), X_changes_at_most(2),
    covers=("REQ-B9", "REQ-B22", "REQ-C7", "REQ-C12"))
add(gentle("g24_dead_dongle_charge", "The dongle dies for good during the lease: no guard runs, the lowered value stays; the owner is alerted. (The backstop is the alert and the after-window check.)",
           events=((6000.0, "dongle_dead", {}),)),
    X_alert("dongle unavailable", by_s=6000 + 600),
    backstop="no firmware guard runs and the lowered slot power stays every night; only the Home Assistant alert remains (the after-window check of the GRC design is not modelled)",
    covers=("REQ-D4",))
add(gentle("g25_ha_outage", "Home Assistant is gone for an hour: after 15 minutes without an API client the dongle restarts, which restores the lease.",
           events=((6000.0, "ha_down", {"dur": 3600.0}),)),
    X_lease_ended("restart"), X_reached(),
    covers=("REQ-B9", "REQ-C7", "REQ-D4"))
add(gentle("g26_plan_lost", "Home Assistant stays connected but stops handing over plans: after 20 minutes the lease ends (plan lost).",
           events=((6000.0, "plan_stop", {}),)),
    X_lease_ended("plan_lost"), X_reached(),
    covers=("REQ-B9", "REQ-C7"))
add(gentle("g27_rtc_untrusted_mid_lease", "The inverter clock becomes untrusted mid-lease: time-dependent actuation fails safe, the lease ends, nothing is raised.",
           trust=((7000.0, 9000.0, "inverter"),)),
    X_lease_ended("time_untrusted"), X_no_write_between(7000, 9000), X_reached(),
    covers=("REQ-D1", "REQ-B21"))
add(gentle("g27b_stale_and_untrusted_together", "The telemetry goes stale and the inverter clock becomes untrusted on the same tick: the guard order decides, and time comes before staleness.",
           tel_gaps=((6915.0, 7500.0),), trust=((7005.0, 9000.0, "inverter"),)),
    X_lease_ended("time_untrusted"), X_reached(),
    covers=("REQ-B21", "REQ-D1"))
add(gentle("g28_rtc_untrusted_at_start", "The inverter clock is untrusted for the first 15 minutes: no start until it is trusted.", trust=((0.0, 900.0, "inverter"),)),
    X_first_write_after(900), X_saw("ha", "blocked", "time_untrusted"), X_reached(),
    covers=("REQ-D1", "REQ-B21"))
add(gentle("g29_grid_loss_in_lease", "Grid lost mid-lease (and a lowered slot may cap the battery off grid): the lease ends first and the original value is restored at once.",
           plant=P.PlantParams(slot_caps_offgrid_discharge=True), house=Hs((0, 800), (6900, 6000), (7700, 800)),
           events=((7000.0, "grid_loss", {"dur": 600.0}),)),
    X_lease_ended("grid_lost"), X_lease_ends_within(7000.0, 30.0), X_unserved_at_most(30),
    covers=("REQ-B21", "REQ-D7"))
add(gentle("g30_import_ceiling_drop", "The owner's import ceiling is applied mid-lease (9 kW) with 2 kW of house load: the forced reduction does not wait for the dwell.",
           house=Hs((0, 2000)), events=((5000.0, "import_ceiling", {"w": 9000.0}),)),
    X_saw("dongle", "reduce", "import_ceiling"),
    covers=("REQ-B21", "REQ-C10", "REQ-D2"))
add(gentle("g31_two_policies", "Another controller tries to start an export while the Gentle lease owns the setpoint: refused, one writer per setting.",
           events=((6000.0, "second_start", EXPORT_PAYLOAD),)),
    X_refused("authority_busy"), X_reached(),
    covers=("REQ-B19", "REQ-B20", "REQ-C11"))
add(gentle("g32_hold_pressed_charge", "The owner presses Hold mid-lease: the session ends, the pre-session values are back, nothing restarts while Hold is on.",
           events=((7000.0, "hold", {"dur": 1800.0}),)),
    X_lease_ended("owner_end"), X_reached(),
    covers=("REQ-C12", "REQ-B21"))
add(gentle("g33_plan_catches_up_alone", "The real battery is far larger than the plan (46 kWh against 35): the plan falls behind, raises the rate itself to today's and reaches the target in good time; the target guard has nothing to do and stays quiet.",
           plant=P.PlantParams(capacity_kwh=46.0), soc0_pct=25.0, target_soc_pct=90.0),
    X_reached(), X_reached_by_window_end(), X_saw("dongle", "stop", "target_guard", present=False), X_saw("ha", "increase", "behind_plan"),
    covers=("REQ-A12",))
add(gentle("g34_target_guard_hands_back", "The never-worse target guard decides the night: the charging efficiency collapses to 0.50 at 90 minutes on a 38 kWh battery; the raises are slower than the collapse, so the guard hands the charge back to today's rate at 9015 s and today's rate reaches the target by the window end (a controller without the guard misses it). The target is reported at risk, never lowered.",
           plant=P.PlantParams(capacity_kwh=38.0), soc0_pct=30.0, buffer_s=1800.0, events=((5400.0, "plant", {"charge_eff": 0.50}),)),
    X_lease_ended("target_guard"), X_reached_by_window_end(), X_never_worse_binding(), X_saw("ha", "unreachable", "at_risk"),
    X_report_between(5400, 9100),
    covers=("REQ-A9", "REQ-A12", "REQ-B21"))
add(gentle("g34b_target_guard_reports_missed_target", "The hand-back that cannot save the night: a 40 kWh battery, efficiency 0.55 from 90 minutes. The guard ends the lease at 8415 s, today's rate does not reach the target either, and the miss is REPORTED (before the end of the lease and again by the watch that goes on after it), never silent.",
           plant=P.PlantParams(capacity_kwh=40.0), soc0_pct=20.0, events=((5400.0, "plant", {"charge_eff": 0.55}),)),
    X_lease_ended("target_guard"), X_report_between(5400, 8500), X_saw("ha", "unreachable", "deadline"), X_leases_count(1),
    covers=("REQ-A9", "REQ-A12"))

add(gentle("g21b_stale_end_then_collapse", "The lease ends on a 5 minute telemetry gap, then the charging efficiency collapses to 0.40: today's rate is back and the plan can no longer write (one lease a night), but it keeps watching and reports that the target will be missed.",
           tel_gaps=((3600.0, 3900.0),), events=((7000.0, "plant", {"charge_eff": 0.40}),)),
    X_lease_ended("stale_telemetry"), X_leases_count(1), X_report_between(7000, 13000), X_saw("ha", "unreachable", "at_risk"),
    covers=("REQ-A9", "REQ-B3", "REQ-B9"))
add(gentle("g23b_restart_then_collapse", "The dongle restarts mid-lease (the lease is restored, never resumed), then the charging efficiency collapses to 0.40: the plan watches the rate in force and reports the miss.",
           events=((6000.0, "dongle_restart", {"boot_s": 60.0}), (7000.0, "plant", {"charge_eff": 0.40}))),
    X_lease_ended("restart"), X_leases_count(1), X_report_between(7000, 13000), X_saw("ha", "unreachable", "at_risk"),
    covers=("REQ-A9", "REQ-B9"))
add(gentle("g26b_plan_lost_then_collapse", "Home Assistant stops handing over plans (the lease ends after 20 minutes) and the charging efficiency collapses to 0.40: the hand-over is stopped, the judging is not, and the miss is still reported.",
           events=((6000.0, "plan_stop", {}), (7000.0, "plant", {"charge_eff": 0.40}))),
    X_lease_ended("plan_lost"), X_leases_count(1), X_report_between(7000, 13000), X_saw("ha", "unreachable", "at_risk"),
    covers=("REQ-A9", "REQ-B9"))

# ----- Charge Fixed (Free Power style): one rate, ended early -----------------------------------------------------------------
add(fixed("f01_fixed_nominal", "Charge Fixed at 8 kW from 30 to 90 percent: one rate, ended at the target (two writes: start and restore).",
          soc0_pct=30.0, owner_rate_w=8000.0, house=Hs((0, 800)), react_s=200.0),
    X_reached(), X_lease_ended("target_reached"), X_writes_at_most(2),
    covers=("REQ-B2", "REQ-B11", "REQ-B12"))
add(fixed("f02_fixed_import_breach", "Charge Fixed with an 11 kW import ceiling and a 4 kW house load: import would pass it, so the session ends at once; a later start uses the headroom rate.",
          soc0_pct=30.0, owner_rate_w=8000.0, import_ceiling_w=11000.0, house=Hs((0, 800), (3600, 4000)), react_s=200.0),
    X_lease_ended("import_ceiling"),
    covers=("REQ-B12", "REQ-C10", "REQ-D2"))
add(fixed("f03_fixed_unreachable", "Charge Fixed at only 2 kW from 10 to 100 percent: the start says at once that this rate cannot make the target.",
          soc0_pct=10.0, target_soc_pct=100.0, owner_rate_w=2000.0),
    X_reported_by(600),
    covers=("REQ-A9", "REQ-B8"))

# ----- Export: the closed loop on the net grid export (the proven Dump loop) ---------------------------------------------------
add(export("e01_nominal", "Nominal export: 2 kW net export from 80 percent, house 1 kW, no solar; the loop settles inside the deadband and the lease ends at its planned end.",
           soc0_pct=80.0),
    X_export_tracks(600.0, 300.0), X_lease_ended("lease_end"), X_saw("ha", "increase", "feed_forward"),
    covers=("REQ-B13", "REQ-B14", "REQ-C9"))
add(export("e02_house_step_up", "House load jumps from 1 to 3.5 kW with a 6 kW ceiling: the ceiling is raised in 1 kW steps at least 45 s apart and the export recovers.",
           lease_ceiling_w=6000.0, house=Hs((0, 1000), (1800, 3500)), duration_s=5400.0),
    X_export_tracks(2700.0, 400.0), X_saw("dongle", "increase", "export_short"),
    covers=("REQ-B5", "REQ-B13", "REQ-B16"))
add(export("e02b_house_step_infeasible", "The same step with the proven 3 kW ceiling: the target is infeasible high, said plainly; the export is never forced by importing.",
           house=Hs((0, 1000), (1800, 3500)), duration_s=5400.0),
    X_saw("dongle", "unreachable", "infeasible_high"),
    covers=("REQ-B13", "REQ-B16"))
add(export("e03_house_step_down", "House load falls from 3 kW to 0.5 kW: the export jumps, the loop steps the ceiling down by at most 1 kW per 45 s and returns inside the band.",
           lease_ceiling_w=6000.0, house=Hs((0, 3000), (1800, 500)), duration_s=5400.0, max_export_w=5000.0),
    X_export_tracks(2700.0, 400.0), X_saw("dongle", "reduce", "export_over"),
    covers=("REQ-B13",))
add(export("e04_kettle_spikes", "Kettle-sized bursts (3 kW for 2 minutes): settle and deadband keep the number of writes small.",
           house=P.Series([(0.0, 1000.0)], spikes=[(1500.0, 120.0, 3000.0), (3300.0, 120.0, 3000.0), (5100.0, 120.0, 3000.0)]), duration_s=7200.0),
    X_writes_at_most(40),
    covers=("REQ-B7", "REQ-B13"))
add(export("e05_pv_cloud", "Solar drops from 1.5 kW to 0.3 kW for ten minutes: the loop follows the measured grid, never a forecast.",
           pv=Hs((0, 1500), (1500, 300), (2100, 1500)), duration_s=5400.0),
    X_export_tracks(900.0, 400.0), X_writes_at_most(30),
    covers=("REQ-B13", "REQ-B15"))
add(export("e06_pv_evening_drop", "Solar falls away to nothing over 90 minutes: the energy plan credited no solar, the floor (not the duration) is the safety, the SOC stays above it.",
           pv=P.Series([(0.0, 2000.0), (5400.0, 0.0)], mode="linear"), target_export_w=1500.0, duration_s=7200.0),
    X_min_soc_at_least(21.0),
    covers=("REQ-B14", "REQ-B15"))
add(export("e07_infeasible_low", "Solar alone (3.5 kW) already exports more than the 1 kW target: nothing is started, the plan says so, the battery is never charged to absorb it.",
           pv=Hs((0, 3500)), target_export_w=1000.0, duration_s=1800.0),
    X_no_writes(), X_saw("ha", "unreachable", "infeasible_low"),
    covers=("REQ-B13", "REQ-B15", "REQ-B16"))
add(export("e07b_pv_rises_during_export", "Solar rises during a running export: the ceiling falls to the 500 W floor and no further, the export is reported infeasible low, the battery never charges.",
           pv=Hs((0, 0), (1800, 4000)), duration_s=5400.0),
    X_saw("dongle", "unreachable", "infeasible_low"), X_never_charges_from_export(),
    covers=("REQ-B13", "REQ-B15", "REQ-B16"))
add(export("e08_stale_grid_gap", "A 3 minute telemetry gap during the lease: past 90 seconds the lease fails closed and is restored.", tel_gaps=((1800.0, 1980.0),)),
    X_lease_ended("stale_telemetry"), X_lease_ends_within(1800.0, 150.0),
    covers=("REQ-B3", "REQ-B9"))
add(export("e09_stop_soc_reached", "A rising house load drains the battery faster than planned: the Stop SOC (staged above the effective reserve) ends the lease before the reserve.",
           soc0_pct=30.0, house=Hs((0, 500), (600, 3000)), lease_ceiling_w=5000.0, duration_s=9000.0, export_len_s=20000.0),
    X_lease_ended_any(("floor_reached", "lease_end")), X_min_soc_at_least(20.0),
    covers=("REQ-B14",))
add(export("e10_reserve_rises", "The effective reserve rises from 20 to 60 percent during the export: Home Assistant asks for a raise-only Stop SOC and the lease ends above the new reserve.",
           soc0_pct=70.0, events=((1200.0, "reserve", {"pct": 60.0}),), duration_s=9000.0, export_len_s=20000.0, house=Hs((0, 1000))),
    X_lease_ended_any(("floor_reached", "reserve_rose")),
    covers=("REQ-B14", "REQ-B21"))
add(export("e10b_reserve_above_soc", "The reserve jumps above the battery's own SOC: the discharge stops within the declared reaction time.",
           soc0_pct=45.0, events=((900.0, "reserve", {"pct": 55.0}),), duration_s=3600.0),
    X_lease_ends_within(900.0, 300.0),
    covers=("REQ-B14", "REQ-B21"))
add(export("e11_hold_pressed", "The owner presses Hold during the export: Home Assistant ends the session within a plan tick and the pre-session values are restored.",
           events=((1800.0, "hold", {"dur": 1800.0}),), duration_s=5400.0),
    X_lease_ended("owner_end"), X_lease_ends_within(1800.0, 200.0),
    covers=("REQ-B21", "REQ-C12"))
add(export("e11b_hold_end_command_lost", "Hold is pressed and the first End command is lost in transit: Home Assistant sends it again at the next plan tick and the session still ends.",
           events=((1800.0, "hold", {"dur": 1800.0}),), cmd_loss=frozenset({1}), duration_s=5400.0, react_s=300.0),
    X_lease_ended("owner_end"), X_lease_ends_within(1800.0, 300.0),
    covers=("REQ-B22", "REQ-C12"))
add(export("e12_restart_in_lease", "The dongle restarts during the export: the lease is ended and restored at boot, never resumed.",
           events=((1800.0, "dongle_restart", {"boot_s": 60.0}),), duration_s=5400.0),
    X_lease_ended("restart"), X_lease_ends_within(1800.0, 120.0),
    covers=("REQ-B9", "REQ-B22", "REQ-C7"))
add(export("e13_dead_dongle", "The dongle dies mid-export: no firmware guard runs, the last ceiling stays in force, ECCO's reserve is NOT protected. The backstops are the inverter's own shutdown SOC and the owner alert.",
           soc0_pct=40.0, events=((1800.0, "dongle_dead", {}),), duration_s=20000.0, export_len_s=20000.0),
    X_alert("dongle unavailable", by_s=1800 + 400), X_min_soc_at_least(9.0),
    known_gap=(("RESERVE_FLOOR", "no firmware guard runs with a dead dongle: only the inverter's own shutdown SOC and the Home Assistant alert remain"),),
    backstop="the inverter's own shutdown SOC (assumed 10 percent) and the Home Assistant alert",
    covers=("REQ-D4",))
add(export("e14_unit_wrong_x10", "Export unit wrong by 10x with no Max Grid Export set: the measured-power guard ends the lease within a few samples.",
           plant=P.PlantParams(discharge_unit_scale=10.0), max_export_w=None, duration_s=3600.0),
    X_lease_ended("runaway"), X_lease_ends_within(0.0, 200.0),
    covers=("REQ-B18", "REQ-D3"))
add(export("e15_runaway_anomaly", "The 22 Sept 2026 anomaly: the battery ignores its ceiling mid-lease. The runaway guard ends the lease.",
           events=((900.0, "plant", {"ignore_ceiling_w": 8600.0}),), max_export_w=None, duration_s=3600.0),
    X_lease_ended("runaway"), X_lease_ends_within(900.0, 200.0),
    covers=("REQ-D3",))
add(export("e16_export_time_untrusted", "The dongle's NTP time is untrusted for the first 10 minutes: no start until it is trusted.", trust=((0.0, 600.0, "ntp"),), duration_s=3600.0),
    X_first_write_after(600), X_saw("ha", "blocked", "time_untrusted"),
    covers=("REQ-D1", "REQ-B21"))
add(export("e17_grid_loss_export", "Grid lost during the export: the session ends first and the pre-session values are restored.",
           events=((1800.0, "grid_loss", {"dur": 600.0}),), duration_s=3600.0),
    X_lease_ended("grid_lost"), X_lease_ends_within(1800.0, 30.0),
    covers=("REQ-B21",))
add(export("e18_export_over_limit", "The house load falls away under a 2.5 kW Max Grid Export: one sample far over ends the lease at once.",
           lease_ceiling_w=6000.0, house=Hs((0, 2500), (1200, 300)), max_export_w=2500.0, duration_s=3600.0),
    X_lease_ended("export_over_limit"), X_lease_ends_within(1200.0, 45.0),
    covers=("REQ-B21", "REQ-C10"))
add(export("e19_second_policy_export", "A Gentle start is attempted while the export owns the setpoint: refused.",
           events=((1800.0, "second_start", GENTLE_PAYLOAD),), duration_s=3600.0),
    X_refused("authority_busy"),
    covers=("REQ-B19", "REQ-B20", "REQ-C11"))
add(export("e20_delayed_commands_export", "Commands take 90 seconds: a reserve rise is acted on late but inside the declared reaction time.",
           cmd_delay_s=90.0, react_s=360.0, soc0_pct=70.0, events=((1200.0, "reserve", {"pct": 60.0}),), duration_s=9000.0, export_len_s=20000.0),
    X_lease_ended_any(("floor_reached", "reserve_rose")),
    covers=("REQ-B14", "REQ-B22"))

SPEC_BY_NAME = {sp.sc.name: sp for sp in SPECS}


# ---------------------------------------------------------------------------------------------------------------------------
# the property sweep: seeded random plants and inputs, every applicable invariant must hold (no scenario-specific expectation)
# ---------------------------------------------------------------------------------------------------------------------------
def _random_house(rng, horizon_s, calm_after_s, spiky):
    """A random house load: a base, a few steps and (optionally) a few short bursts. Everything exogenous happens before `calm_after_s`
    so that the controller has the time its reaction bound needs; after it the load stays at its last level."""
    base = rng.uniform(300.0, 2200.0)
    pts = [(0.0, base)]
    for _ in range(rng.choice((0, 1, 2, 3))):
        pts.append((rng.uniform(600.0, calm_after_s), rng.uniform(300.0, 4800.0)))
    spikes = []
    if spiky:
        for _ in range(rng.choice((0, 2, 4))):
            spikes.append((rng.uniform(600.0, calm_after_s), rng.uniform(60.0, 300.0), rng.uniform(1500.0, 3500.0)))
    return P.Series(sorted(pts), spikes=spikes)


def random_spec(seed, kind):
    """One random spec of `kind` (gentle, charge_fixed or export). The plant stays inside the declared envelope of the pessimistic world
    (capacity up to 9 % above what the kernel is told is already inside its band, efficiency not below 0.90, the knee at or above 90 %),
    so the guarantee 'reached, or reported early' is claimed only where it can hold."""
    import random
    rng = random.Random(seed)
    cmd_delay = rng.choice((0.0, 0.0, 15.0, 45.0, 90.0))
    noise = rng.choice((0.0, 0.0, 25.0))
    gaps = tuple((t0, t0 + rng.choice((15.0, 45.0, 75.0))) for t0 in sorted(rng.uniform(900.0, 9000.0) for _ in range(rng.choice((0, 0, 1, 2)))))
    if kind in ("gentle", "charge_fixed"):
        trusted = 35.0
        target = rng.choice((60.0, 70.0, 80.0, 90.0, 95.0, 100.0))
        # a sensor error is sampled only when the target is below 100: a BMS reads 100 when it is full, whatever its scale error elsewhere
        plant = P.PlantParams(capacity_kwh=rng.uniform(22.0, 37.5), charge_eff=rng.uniform(0.90, 0.97), knee_soc_pct=rng.uniform(92.0, 99.0),
                              tail_dc_w=rng.uniform(350.0, 800.0), unit_scale=rng.choice((1.0, 1.0 / 0.945, 1.1225)),
                              soc_bias_pct=rng.uniform(-1.0, 1.0) if target < 100.0 else 0.0)
        win_h = rng.choice((4.0, 5.0, 6.0))
        window = (0.0, win_h * 3600.0)
        buffer_s = rng.choice((1800.0, 3600.0, 5400.0))
        deadline = window[1] - buffer_s
        soc0 = rng.uniform(5.0, max(6.0, min(80.0, target - 12.0)))
        house = _random_house(rng, window[1], 0.4 * deadline, spiky=True)
        imp = rng.choice((None, None, 13000.0, 16000.0))
        plan_s = rng.choice((300.0, 600.0))
        sc = Scenario(name="sweep_%s_%d" % (kind, seed), kind=kind, plant=plant, soc0_pct=soc0, house=house, window=window, target_soc_pct=target,
                      buffer_s=buffer_s, trusted_capacity_kwh=trusted, duration_s=window[1], import_ceiling_w=imp, plan_s=plan_s,
                      react_s=plan_s + cmd_delay + 90.0,
                      cmd_delay_s=cmd_delay, noise_w=noise, tel_gaps=gaps, seed=seed, table_charges=kind == "gentle",
                      owner_rate_w=8000.0 if kind == "charge_fixed" else None)
        skip = ()
        return Spec(sc=sc, skip=skip)
    cap = rng.uniform(25.0, 40.0)
    soc0 = rng.uniform(40.0, 90.0)
    reserve = rng.uniform(10.0, 35.0)
    stop = rng.uniform(10.0, 35.0)
    plan_s = rng.choice((60.0, 120.0, 300.0))
    ceiling = rng.choice((3000.0, 5000.0, 8000.0))
    dur = rng.choice((5400.0, 7200.0, 9000.0))
    house = _random_house(rng, dur, 0.6 * dur, spiky=True)
    pv = P.Series([(0.0, rng.uniform(0.0, 2500.0)), (rng.uniform(600.0, 0.6 * dur), rng.uniform(0.0, 2500.0))])
    events = []
    if rng.random() < 0.35:
        events.append((rng.uniform(900.0, 0.5 * dur), "reserve", {"pct": min(80.0, reserve + rng.uniform(5.0, 40.0))}))
    if rng.random() < 0.15:
        events.append((rng.uniform(900.0, 0.5 * dur), "hold", {"dur": 600.0}))
    if rng.random() < 0.15:
        events.append((rng.uniform(900.0, 0.5 * dur), "dongle_restart", {"boot_s": 60.0}))
    if rng.random() < 0.10:
        events.append((rng.uniform(900.0, 0.5 * dur), "grid_loss", {"dur": 300.0}))
    react = plan_s + cmd_delay + 3 * TICK + 60.0 + 120.0
    sc = Scenario(name="sweep_export_%d" % seed, kind="export", plant=P.PlantParams(capacity_kwh=cap), soc0_pct=soc0, window=None, house=house, pv=pv,
                  duration_s=dur, target_export_w=rng.uniform(500.0, 3500.0), stop_soc_pct=stop, reserve_pct=reserve, lease_ceiling_w=ceiling,
                  max_export_w=rng.choice((None, 6000.0)), trusted_capacity_kwh=cap, export_len_s=dur - 900.0, plan_s=plan_s, cmd_delay_s=cmd_delay,
                  noise_w=noise, tel_gaps=gaps, seed=seed, events=tuple(events), react_s=react)
    return Spec(sc=sc)


def sweep(K, n_per_kind, base_seed=20261126, kinds=("gentle", "charge_fixed", "export")):
    """Run n_per_kind random specs of each kind against the kernel module K. Returns the list of (spec name, [failure texts]) that failed."""
    bad = []
    for kind in kinds:
        for i in range(n_per_kind):
            spec = random_spec(base_seed + i * 7919 + {"gentle": 0, "charge_fixed": 1, "export": 2}[kind] * 1000003, kind)
            run, res = run_spec(spec, K)
            if not res.ok:
                bad.append((spec.sc.name, res.failures))
    return bad


# ---------------------------------------------------------------------------------------------------------------------------
# generated tables (SIM_README.md carries them verbatim; test_sim.py compares)
# ---------------------------------------------------------------------------------------------------------------------------
def coverage_table_md():
    lines = ["<!-- covers:begin -->", "| Scenario | Policy | What it does | Requirements (REQUIREMENTS.md) |", "|---|---|---|---|"]
    for sp in SPECS:
        lines.append("| `%s` | %s | %s | %s |" % (sp.sc.name, sp.sc.kind, sp.sc.summary.replace("|", "/"), ", ".join(sp.covers) if sp.covers else "-"))
    lines.append("<!-- covers:end -->")
    return "\n".join(lines)
