"""Area 3: B10 (ECCO Fallback Profile Live Match) availability, time-weighted.

The B10 text is `m=<MODE>;dx=..;cx=..;...` (firmware/include/ecco_fallback_capture.h b10_text), published only when it
changes. Each Home Assistant row holds until the next one. Categories:
  MATCH       m=MATCH
  NOT_MATCH   m=DRIFT | CONTEXT | EXPORT | OUT_OF_DOMAIN       (compared, and the live inverter differs from the profile)
  BLOCKED     m=PAUSED | PAUSED_IO | NO_PROFILE                (no comparison possible: lease, bus busy, no valid profile)
  UNKNOWN     m=UNKNOWN, Home Assistant unknown / unavailable, or an unreadable state
  NO_EVIDENCE no row in force yet, or the time falls inside an evidence gap (Home Assistant recorded nothing at all)
Missing history is never MATCH.
"""

from __future__ import annotations

import re
import statistics
from datetime import timedelta

from .evidence import as_bool, is_missing
from .model import (CONFIRMED, FAIL, INFERRED, INSUFFICIENT, NONE, PASS, WARNING, Criterion, Ctx, merge_intervals, overlap_s, pct)
from .timeutil import fmt_duration, stamp

MODE = re.compile(r"(?:^|;)m=([A-Z_]+)")
CATEGORY = {"MATCH": "MATCH", "DRIFT": "NOT_MATCH", "CONTEXT": "NOT_MATCH", "EXPORT": "NOT_MATCH", "OUT_OF_DOMAIN": "NOT_MATCH",
            "PAUSED": "BLOCKED", "PAUSED_IO": "BLOCKED", "NO_PROFILE": "BLOCKED", "UNKNOWN": "UNKNOWN"}
CATS = ("MATCH", "NOT_MATCH", "BLOCKED", "UNKNOWN", "NO_EVIDENCE")


def mode_of(raw: str | None) -> str:
    if raw is None:
        return "NO_EVIDENCE"
    if is_missing(raw):
        return "UNKNOWN"
    s = raw.strip()
    m = MODE.search(s)
    mode = m.group(1) if m else s
    return mode if mode in CATEGORY else "UNREADABLE"


def category(mode: str) -> str:
    if mode == "NO_EVIDENCE":
        return "NO_EVIDENCE"
    return CATEGORY.get(mode, "UNKNOWN")


def _subtract(a, b, holes):
    """[a, b) minus the hole intervals -> list of pieces."""
    pieces = [(a, b)]
    for x, y in holes:
        nxt = []
        for p, q in pieces:
            if y <= p or x >= q:
                nxt.append((p, q))
                continue
            if x > p:
                nxt.append((p, x))
            if y < q:
                nxt.append((y, q))
        pieces = nxt
    return pieces


def timeline(ctx: Ctx) -> list:
    """[(start, end, category, mode, ref)] covering the window."""
    s = ctx.ev.get("b10")
    out = []
    if not s:
        return [(ctx.start, ctx.end, "NO_EVIDENCE", "NO_EVIDENCE", "")]
    holes = merge_intervals(ctx.gaps)
    for a, b, smp in s.segments(ctx.start, ctx.end):
        mode = mode_of(smp.raw if smp else None)
        cat = category(mode)
        ref = smp.ref if smp else ""
        if cat == "NO_EVIDENCE":
            out.append((a, b, cat, mode, ref))
            continue
        cur = a
        for p, q in _subtract(a, b, holes):
            if p > cur:
                out.append((cur, p, "NO_EVIDENCE", "GAP", ref))
            out.append((p, q, cat, mode, ref))
            cur = q
        if cur < b:
            out.append((cur, b, "NO_EVIDENCE", "GAP", ref))
    return out


def analyse(ctx: Ctx) -> dict:
    r = ctx.rules
    tl = timeline(ctx)
    have = ctx.ev.has("b10")
    tot = {c: 0.0 for c in CATS}
    modes = {}
    for a, b, cat, mode, _ in tl:
        d = (b - a).total_seconds()
        tot[cat] += d
        modes[mode] = modes.get(mode, 0.0) + d
    W = ctx.window_s or 1.0
    observed = W - tot["NO_EVIDENCE"]
    coverage = observed / W
    match_obs = tot["MATCH"] / observed if observed > 0 else None
    match_win = tot["MATCH"] / W

    # interruptions: maximal runs of non-MATCH
    runs, cur = [], None
    for a, b, cat, mode, ref in tl:
        if cat == "MATCH":
            if cur:
                runs.append(cur)
                cur = None
            continue
        if cur and cur["end"] == a:
            cur["end"] = b
            cur["cats"].add(cat)
            cur["modes"].add(mode)
            if cat != "NO_EVIDENCE":
                cur["evidenced_s"] += (b - a).total_seconds()
        else:
            if cur:
                runs.append(cur)
            cur = {"start": a, "end": b, "cats": {cat}, "modes": {mode}, "ref": ref,
                   "evidenced_s": (b - a).total_seconds() if cat != "NO_EVIDENCE" else 0.0}
    if cur:
        runs.append(cur)
    corr = [(e.t_start or e.t, (e.t_end or e.t) + timedelta(seconds=60)) for e in ctx.episodes if e.t is not None]
    for run in runs:
        causes = []
        if any(a <= run["end"] and b >= run["start"] for a, b in corr):
            causes.append("rtc-correction")
        if overlap_s(run["start"], run["end"], ctx.lease_intervals) > 0:
            causes.append("lease")
        if overlap_s(run["start"], run["end"], ctx.config_offline) > 0:
            causes.append("configuration-offline")
        if overlap_s(run["start"], run["end"], ctx.unavailable) > 0:
            causes.append("device-unavailable")
        if "NO_EVIDENCE" in run["cats"]:
            causes.append("no-evidence")
        run["causes"] = causes or ["unexplained"]
    longest = max(runs, key=lambda x: (x["end"] - x["start"]), default=None)
    longest_ev = max(runs, key=lambda x: x["evidenced_s"], default=None)

    # recovery after RTC corrections
    rec = []
    for e in ctx.episodes:
        if e.t_start is None or e.outcome not in ("verified", "failed", "aborted"):
            continue
        rel = e.t_end or e.t_start
        left = any(cat != "MATCH" and a < rel + timedelta(seconds=1) and b > e.t_start for a, b, cat, _, _ in tl)
        back = next((max(a, rel) for a, b, cat, _, _ in tl if cat == "MATCH" and b > rel), None)  # max: MATCH already in force
        r_s = (back - rel).total_seconds() if back is not None else None
        rec.append({"episode": e.idx, "release": stamp(rel), "left_match": left,
                    "match_after_s": None if r_s is None else round(r_s, 1)})
        if r_s is not None and r_s > r.b10_recovery_warn_s:
            ctx.event(rel, "b10", "WARNING", "slow-b10-recovery",
                      f"B10 back to MATCH {fmt_duration(r_s)} after correction #{e.idx} released", CONFIRMED)
    rec_vals = [x["match_after_s"] for x in rec if x["match_after_s"] is not None]

    # invariant: never MATCH while the RTC lock is held
    lock_iv = []
    s = ctx.ev.get("rtc_correction_in_progress")
    if s:
        on = None
        for x in s.samples:
            b = as_bool(x.raw)
            if b and on is None:
                on = x.t
            elif b is False and on is not None:
                lock_iv.append((on, x.t))
                on = None
    match_iv = [(a, b) for a, b, cat, _, _ in tl if cat == "MATCH"]
    overlaps = []
    for a, b in lock_iv:
        o = overlap_s(a, b, match_iv)
        if o > 2.0:
            overlaps.append((a, b, o))
            sev = "FAIL" if o > r.b10_lock_overlap_fail_s else "WARNING"
            ctx.event(a, "b10", sev, "match-while-rtc-lock",
                      f"B10 MATCH for {o:.0f} s while RTC Correction In Progress was on", CONFIRMED)

    for run in runs:
        if run["cats"] & {"NOT_MATCH"}:
            ctx.event(run["start"], "b10", "WARNING", "b10-not-match",
                      f"B10 {'/'.join(sorted(run['modes'] - {'GAP'}))} for {fmt_duration((run['end'] - run['start']).total_seconds())}"
                      " (live inverter differs from the stored profile)", CONFIRMED, [run["ref"]])
        if "NO_PROFILE" in run["modes"]:
            ctx.event(run["start"], "b10", "WARNING", "b10-no-profile", "B10 NO_PROFILE: the stored fallback profile was not "
                      "usable", CONFIRMED, [run["ref"]])

    daily = []
    for d in ctx.days:
        dt = {c: 0.0 for c in CATS}
        for a, b, cat, _, _ in tl:
            lo, hi = max(a, d.start), min(b, d.end)
            if hi > lo:
                dt[cat] += (hi - lo).total_seconds()
        obs = d.seconds - dt["NO_EVIDENCE"]
        daily.append({"day": d.label, "match_pct_of_day": pct(dt["MATCH"] / d.seconds),
                      "match_pct_of_observed": pct(dt["MATCH"] / obs) if obs > 0 else None,
                      "coverage_pct": pct(obs / d.seconds), **{f"{c.lower()}_s": round(dt[c], 1) for c in CATS}})

    crit = []
    reasons = [f"MATCH {pct(match_obs)} % of observed time, {pct(match_win)} % of the window; coverage {pct(coverage)} %"]
    if not have:
        v, basis = INSUFFICIENT, NONE
        reasons = ["no B10 (ECCO Fallback Profile Live Match) rows in the evidence"]
    elif coverage < r.b10_coverage_min:
        v, basis = INSUFFICIENT, CONFIRMED
        reasons.append(f"B10 evidence covers less than {pct(r.b10_coverage_min)} % of the window")
    else:
        basis = CONFIRMED
        if match_obs < r.b10_match_fail:
            v = FAIL
        elif match_obs < r.b10_match_pass:
            v = WARNING
        else:
            v = PASS
        if tot["NOT_MATCH"] > 0 and v == PASS:
            v = WARNING
            reasons.append(f"NOT MATCH for {fmt_duration(tot['NOT_MATCH'])} in total")
        low = [x["day"] for x in daily if x["match_pct_of_observed"] is not None and x["match_pct_of_observed"] < 100 * r.b10_match_fail]
        if low and v == PASS:
            v = WARNING
        if low:
            reasons.append(f"day(s) under {pct(r.b10_match_fail)} % MATCH: {', '.join(low)}")
    if overlaps and any(o > r.b10_lock_overlap_fail_s for _, _, o in overlaps):
        v = FAIL
        reasons.append(f"{len(overlaps)} RTC lock interval(s) with B10 MATCH (the firmware must never show MATCH under the lock)")
    crit.append(Criterion("C-B10-1", "b10", "B10 Live Match availability", v, basis,
                          f"MATCH {pct(match_obs)} % of observed time" if have else "no B10 evidence", True, reasons,
                          {"match_pct_observed": pct(match_obs), "match_pct_window": pct(match_win), "coverage_pct": pct(coverage),
                           **{f"{c.lower()}_s": round(tot[c], 1) for c in CATS}}))
    reasons = []
    if not rec:
        if ctx.episodes and have:
            v, basis = INSUFFICIENT, NONE
            reasons.append("corrections are known only by counter: their release times are not in the evidence")
        elif have:
            v, basis = PASS, CONFIRMED
            reasons.append("no RTC correction in the window, so no recovery to measure")
        else:
            v, basis = INSUFFICIENT, NONE
            reasons.append("no B10 evidence")
    else:
        basis = CONFIRMED
        slow = [x for x in rec if x["match_after_s"] is not None and x["match_after_s"] > r.b10_recovery_warn_s]
        never = [x for x in rec if x["match_after_s"] is None]
        v = WARNING if (slow or never) else PASS
        reasons.append(f"{len(rec)} correction(s): median {statistics.median(rec_vals) if rec_vals else 'n/a'} s, max "
                       f"{max(rec_vals) if rec_vals else 'n/a'} s from release to MATCH (warn > {r.b10_recovery_warn_s:.0f} s)")
        if never:
            reasons.append(f"{len(never)} correction(s) never followed by MATCH in the evidence")
    crit.append(Criterion("C-B10-2", "b10", "B10 recovers after RTC corrections", v, basis,
                          f"{len(rec)} recovery measurement(s)", False, reasons,
                          {"median_s": statistics.median(rec_vals) if rec_vals else None, "max_s": max(rec_vals, default=None)}))
    return {
        "criteria": crit,
        "area": {
            "time_s": {c: round(tot[c], 1) for c in CATS},
            "time_by_mode_s": {k: round(v_, 1) for k, v_ in sorted(modes.items())},
            "match_pct_observed": pct(match_obs), "match_pct_window": pct(match_win), "coverage_pct": pct(coverage),
            "interruptions": len(runs),
            "longest_interruption": None if longest is None else {
                "from": stamp(longest["start"]), "to": stamp(longest["end"]),
                "seconds": round((longest["end"] - longest["start"]).total_seconds(), 1), "modes": sorted(longest["modes"]),
                "causes": longest["causes"]},
            "longest_evidenced_interruption_s": None if longest_ev is None else round(longest_ev["evidenced_s"], 1),
            "interruption_causes": _count_causes(runs),
            "recovery_after_corrections": rec,
            "lock_overlaps": [{"from": stamp(a), "to": stamp(b), "match_s": round(o, 1)} for a, b, o in overlaps],
            "daily": daily,
            "basis": INFERRED if not have else CONFIRMED,
        },
    }


def _count_causes(runs) -> dict:
    out = {}
    for run in runs:
        for c in run["causes"]:
            out[c] = out.get(c, 0) + 1
    return out


__all__ = ["analyse", "mode_of", "category", "timeline"]
