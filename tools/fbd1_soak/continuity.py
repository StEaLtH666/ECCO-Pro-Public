"""Area 5 (part 1): boot continuity, unexpected restarts, evidence gaps, device-unavailable periods and clock integrity.

Restart signals (each is CONFIRMED evidence of a boot, never inferred from silence):
  nonce      the 8-hex boot nonce in `ECCO Supervision Challenge` (`<nonce>-<generation>`) changes; the firmware draws a new
             random nonce on every boot
  counter    any "since boot" counter or "maximum since boot" value decreases
  boot text  a since-boot text returns to its boot value after showing something else: Last Correction Result -> "None since
             boot", Last Correction -> "Never", Last Telemetry / Configuration Update -> "Waiting", Supervision State -> STARTUP
  log        `boot <nonce> shadow ready` / `boot load: ...` firmware log lines
Signals within Rules.restart_cluster_s are one restart. A restart no later than start + boot_grace_s is the soak's own boot.

Continuity is PROVEN only by a witness that cannot survive a reboot unchanged: the same boot nonce from the start of the
window to its end, or the valid-heartbeat counter (reset to 0 by a boot) spanning the window with no decrease. A gap in the
evidence does not hide a restart from these witnesses, but a window with neither witness is INSUFFICIENT, never PASS.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import catalogue
from .evidence import counter_delta, is_missing
from .model import (CONFIRMED, FAIL, INFERRED, INSUFFICIENT, NONE, PASS, WARNING, Criterion, Ctx, merge_intervals,
                    overlap_s, pct)
from .timeutil import TimeParseError, fmt_duration, fmt_local, parse_local_near, stamp

NONCE = re.compile(r"^([0-9A-F]{8})-(\d+)$")
BOOT_TEXT = {
    "last_correction_result": "None since boot",
    "last_correction": "Never",
    "last_telemetry_update": "Waiting",
    "last_configuration_update": "Waiting",
    "supervision_state": "STARTUP",
}


def _timeline(ctx: Ctx) -> list:
    ts = []
    for key in catalogue.WITNESS_KEYS:
        s = ctx.ev.get(key)
        if s:
            ts.extend(x.t for x in s.samples)
    ts.extend(e.t for e in ctx.ev.logs)
    ts.sort()
    return ts


def evidence_gaps(ctx: Ctx, timeline: list) -> list:
    a, b, g = ctx.start, ctx.end, timedelta(seconds=ctx.rules.gap_s)
    inside = [t for t in timeline if a <= t <= b]
    pts = [a] + inside + [b]
    gaps = []
    for x, y in zip(pts, pts[1:]):
        if y - x > g:
            gaps.append((x, y))
    return gaps


def unavailable_intervals(ctx: Ctx) -> list:
    """Intervals in which a witness entity was `unavailable` (the ESPHome API connection to the dongle was down)."""
    per = []
    for key in catalogue.WITNESS_KEYS + ("b10", "clock_difference", "supervision_challenge"):
        s = ctx.ev.get(key)
        if not s:
            continue
        cur = None
        ivs = []
        for x in s.samples:
            if x.raw.strip().lower() == "unavailable":
                if cur is None:
                    cur = x.t
            elif cur is not None:
                ivs.append((cur, x.t))
                cur = None
        if cur is not None:
            ivs.append((cur, max(ctx.end, cur)))
        if ivs:
            per.append(ivs)
    if not per:
        return []
    if len(per) == 1:
        return merge_intervals(per[0])
    # an interval counts when at least two witnesses agree (one disabled entity alone is not the device going away)
    marks = sorted([(a, 1) for ivs in per for a, _ in ivs] + [(b, -1) for ivs in per for _, b in ivs], key=lambda m: (m[0], m[1]))
    out, depth, since = [], 0, None
    for t, d in marks:
        depth += d
        if depth >= 2 and since is None:
            since = t
        elif depth < 2 and since is not None:
            if t > since:
                out.append((since, t))
            since = None
    return merge_intervals(out)


def restart_signals(ctx: Ctx) -> list:
    sig = []
    s = ctx.ev.get("supervision_challenge")
    if s:
        prev = None
        for x in s.samples:
            m = NONCE.match(x.raw.strip())
            if not m:
                continue
            if prev is not None and m.group(1) != prev[0]:
                sig.append((x.t, "nonce", f"boot nonce {prev[0]} -> {m.group(1)}", [prev[1], x.ref]))
            prev = (m.group(1), x.ref)
    lo = min((x.t for k in catalogue.MONOTONIC_KEYS if ctx.ev.get(k) for x in ctx.ev.get(k).samples), default=None)
    if lo is not None:
        far = datetime.max.replace(tzinfo=ctx.start.tzinfo)
        for key in catalogue.MONOTONIC_KEYS:
            r = counter_delta(ctx.ev.get(key), lo - timedelta(seconds=1), far)
            for s0, s1 in r.resets:
                sig.append((s1.t, "counter", f"{catalogue.BY_KEY[key].firmware_name} {s0.raw} -> {s1.raw}", [s0.ref, s1.ref]))
    for key, boot in BOOT_TEXT.items():
        s = ctx.ev.get(key)
        if not s:
            continue
        prev = None
        for x in s.samples:
            if is_missing(x.raw):
                continue
            if x.raw.strip() == boot and prev is not None and prev.raw.strip() != boot:
                sig.append((x.t, "boot-text", f"{catalogue.BY_KEY[key].firmware_name} -> {boot!r} (was {prev.raw!r})",
                            [prev.ref, x.ref]))
            prev = x
    for e in ctx.ev.logs:
        if e.kind == "boot_shadow":
            sig.append((e.t, "log", f"firmware log: boot {e.fields.get('nonce')} shadow ready", [e.ref]))
        elif e.kind == "boot_load":
            sig.append((e.t, "log", "firmware log: boot load", [e.ref]))
    sig.sort(key=lambda x: x[0])
    return sig


def cluster(signals: list, window_s: int) -> list:
    out = []
    for t, kind, detail, refs in signals:
        if out and (t - out[-1]["t"]).total_seconds() <= window_s:
            c = out[-1]
            c["kinds"].add(kind)
            c["details"].append(detail)
            c["refs"].extend(refs)
        else:
            out.append({"t": t, "kinds": {kind}, "details": [detail], "refs": list(refs)})
    return out


def nonce_witness(ctx: Ctx, soak_boot_end: datetime) -> dict:
    s = ctx.ev.get("supervision_challenge")
    if not s:
        return {"available": False}
    vals = []
    for x in s.samples:
        m = NONCE.match(x.raw.strip())
        if m and x.t <= ctx.end:
            vals.append((x.t, m.group(1), x.ref))
    if not vals:
        return {"available": False}
    in_force = [v for v in vals if v[0] <= soak_boot_end]
    after = [v for v in vals if v[0] > soak_boot_end]
    first = in_force[-1] if in_force else (after[0] if after else None)
    last = vals[-1]
    tol = timedelta(seconds=ctx.rules.gap_insufficient_s)
    nonces = sorted({v[1] for v in ([first] if first else []) + after})
    spans = (first is not None and first[0] <= soak_boot_end + tol and last[0] >= ctx.end - tol)
    return {"available": True, "nonces": nonces, "first": first, "last": last, "spans": spans,
            "proves": spans and len(nonces) == 1}


def clock_integrity(ctx: Ctx) -> dict:
    s = ctx.ev.get("ntp_time")
    out = {"available": False, "median_offset_s": None, "discontinuities": []}
    if not s:
        return out
    offs = []
    for x in s.between(ctx.start, ctx.end):
        if is_missing(x.raw) or not x.raw[:1].isdigit():
            continue
        try:
            dev = parse_local_near(x.raw.strip(), x.t)
        except TimeParseError:
            continue
        offs.append((x.t, (dev - x.t).total_seconds(), x.ref))
    if not offs:
        return out
    srt = sorted(o for _, o, _ in offs)
    med = srt[len(srt) // 2]
    out.update(available=True, median_offset_s=round(med, 3), samples=len(offs))
    prev_bad = False
    for t, o, ref in offs:
        bad = abs(o - med) > ctx.rules.clock_skew_warn_s
        if bad and not prev_bad:
            out["discontinuities"].append({"t": t, "offset_s": round(o, 3), "ref": ref})
        prev_bad = bad
    return out


def analyse(ctx: Ctx) -> dict:
    r = ctx.rules
    tl = _timeline(ctx)
    have_witness = any(ctx.ev.has(k) for k in catalogue.WITNESS_KEYS)
    coverage_basis = "periodic witness rows" + (" and firmware log lines" if ctx.ev.logs else "")
    if not have_witness:
        # no periodic entity: estimate recording continuity from the on-change rows of every FB-D1 entity (plus any log). A
        # quiet period then reads as a gap (conservative: B10 is NO_EVIDENCE there, never MATCH) and C-CONT-2 can at best WARN.
        tl = sorted(tl + [x.t for s in ctx.ev.series.values() for x in s.samples])
        coverage_basis = "on-change rows" + (" and firmware log lines" if ctx.ev.logs else "") + \
            " only (no periodic witness entity): an estimate"
    gaps = evidence_gaps(ctx, tl)
    ctx.gaps = gaps
    gap_total = sum((b - a).total_seconds() for a, b in gaps)
    coverage = (1.0 - gap_total / ctx.window_s) if (ctx.window_s > 0 and tl) else 0.0
    first_ev = next((t for t in tl if t >= ctx.start - timedelta(days=1)), None)
    last_ev = tl[-1] if tl else None
    unav = [(max(a, ctx.start), min(b, ctx.end)) for a, b in unavailable_intervals(ctx) if b > ctx.start and a < ctx.end]
    ctx.unavailable = unav

    # restarts
    clusters = cluster(restart_signals(ctx), r.restart_cluster_s)
    grace_end = ctx.start + timedelta(seconds=r.boot_grace_s)
    soak_boot = [c for c in clusters if ctx.start - timedelta(seconds=r.boot_grace_s) <= c["t"] <= grace_end]
    unexpected = [c for c in clusters if grace_end < c["t"] <= ctx.end]
    ctx.restarts = unexpected
    for c in unexpected:
        ctx.event(c["t"], "continuity", "FAIL", "unexpected-restart",
                  "dongle restarted during the soak (" + "; ".join(c["details"][:4]) + ")", CONFIRMED, c["refs"],
                  signals=sorted(c["kinds"]))

    nw = nonce_witness(ctx, grace_end)
    hb = counter_delta(ctx.ev.get("valid_heartbeats"), grace_end, ctx.end)
    hb_resets = [x for x in hb.resets if x[1].t > grace_end] if hb.available else []
    hb_proves = bool(hb.available and hb.spans_window and not hb_resets and (hb.delta or 0) > 0)
    proven = bool(nw.get("proves") or hb_proves)
    witnesses = []
    if nw.get("available"):
        witnesses.append(f"boot nonce: {', '.join(nw['nonces'])} ({'spans' if nw['spans'] else 'does not span'} the window)")
    if hb.available:
        witnesses.append(f"valid heartbeat count: +{int(hb.delta or 0)}, {len(hb_resets)} reset(s), "
                         f"{'spans' if hb.spans_window else 'does not span'} the window")

    # suspected restarts: an unavailable period not crossed by a continuity witness
    suspected = []
    for a, b in unav:
        if (b - a).total_seconds() < 5:
            continue
        crossed = nw.get("proves") or hb_proves
        if not crossed and not any(abs((c["t"] - a).total_seconds()) < r.restart_cluster_s for c in clusters):
            suspected.append((a, b))
            ctx.event(a, "continuity", "WARNING", "possible-restart",
                      f"dongle unavailable for {fmt_duration((b - a).total_seconds())}; no continuity witness spans it, so a "
                      "restart can be neither confirmed nor excluded", INFERRED)
    for a, b in unav:
        ctx.event(a, "continuity", "INFO", "device-unavailable",
                  f"dongle entities unavailable for {fmt_duration((b - a).total_seconds())} (ESPHome API connection down)",
                  CONFIRMED)
    for a, b in gaps:
        if (b - a).total_seconds() >= r.gap_warn_s:
            ctx.event(a, "continuity", "WARNING", "evidence-gap",
                      f"no evidence for {fmt_duration((b - a).total_seconds())} ({fmt_local(a)} to {fmt_local(b)})", CONFIRMED)

    # per day
    days = []
    for d in ctx.days:
        g = overlap_s(d.start, d.end, gaps)
        days.append({"day": d.label, "coverage_pct": pct(1 - g / d.seconds) if tl else 0.0,
                     "gap_s": round(g, 1), "unavailable_s": round(overlap_s(d.start, d.end, unav), 1),
                     "restarts": sum(1 for c in unexpected if d.start <= c["t"] < d.end)})
    low_days = [x["day"] for x in days if (x["coverage_pct"] or 0) < 100 * r.day_coverage_min]

    clk = clock_integrity(ctx)
    for dsc in clk["discontinuities"]:
        ctx.event(dsc["t"], "continuity", "WARNING", "clock-discontinuity",
                  f"dongle NTP wall time differs from the Home Assistant row time by {dsc['offset_s']} s (median "
                  f"{clk['median_offset_s']} s)", CONFIRMED, [dsc["ref"]])
    rejected = sum(i.rejected for i in ctx.ev.inputs)
    ooo = sum(1 for d in ctx.ev.diagnostics if d.code == "out-of-order")

    crit = []
    # C-CONT-1
    if unexpected:
        v, summ = FAIL, f"{len(unexpected)} unexpected restart(s) during the soak (first {fmt_local(unexpected[0]['t'])})"
    elif not proven:
        v, summ = INSUFFICIENT, ("no restart signal was found, but no continuity witness (boot nonce or valid-heartbeat counter) "
                                 "spans the window, so an uninterrupted run cannot be established"
                                 + (f"; {len(suspected)} unavailable period(s) could each hide a restart" if suspected else ""))
    else:
        v, summ = PASS, "one boot for the whole window: " + "; ".join(witnesses)
    crit.append(Criterion("C-CONT-1", "continuity", "No unexpected restart (boot continuity)", v,
                          CONFIRMED if (unexpected or proven) else NONE, summ, True, witnesses,
                          {"unexpected_restarts": len(unexpected), "soak_boot_signals": len(soak_boot),
                           "continuity_proven": proven, "suspected_restarts": len(suspected)},
                          [ref for c in unexpected for ref in c["refs"]]))
    # C-CONT-2
    longest = max(((b - a).total_seconds() for a, b in gaps), default=0.0)
    reasons = []
    if not tl:
        v = INSUFFICIENT
        reasons.append("no FB-D1 row and no firmware log in the window: recording continuity cannot be measured")
    elif coverage < r.coverage_min or longest > r.gap_insufficient_s or low_days:
        v = INSUFFICIENT
    elif coverage < r.coverage_pass or longest > r.gap_warn_s or unav or not have_witness:
        v = WARNING
    else:
        v = PASS
    if not have_witness:
        reasons.append("no periodic witness entity (NTP Time, Inverter Time, heartbeat sensors, telemetry stamps, WiFi signal): "
                       "coverage is estimated from on-change rows" + (" and log lines" if ctx.ev.logs else "") +
                       ", so it can never PASS")
    if tl:
        reasons.append(f"coverage {pct(coverage)} % (pass >= {pct(r.coverage_pass)} %, minimum {pct(r.coverage_min)} %)")
        reasons.append(f"{len(gaps)} gap(s) > {r.gap_s} s, longest {fmt_duration(longest)}")
        if low_days:
            reasons.append(f"soak day(s) under {pct(r.day_coverage_min)} % coverage: {', '.join(low_days)}")
        if unav:
            reasons.append(f"{len(unav)} device-unavailable period(s), {fmt_duration(sum((b - a).total_seconds() for a, b in unav))} total")
    crit.append(Criterion("C-CONT-2", "continuity", "Evidence coverage of the soak window", v,
                          CONFIRMED if have_witness else (INFERRED if tl else NONE),
                          f"{pct(coverage)} % of the window has evidence ({coverage_basis})" if tl else "coverage cannot be measured",
                          True, reasons, {"coverage_pct": pct(coverage), "gaps": len(gaps), "longest_gap_s": round(longest, 1),
                                          "unavailable_periods": len(unav)}))
    # C-CONT-3
    tol = timedelta(seconds=r.gap_s)
    starts = first_ev is not None and first_ev <= ctx.start + tol
    ends = last_ev is not None and last_ev >= ctx.end - tol
    if starts and ends:
        v, summ = PASS, f"evidence spans {fmt_local(ctx.start)} to {fmt_local(ctx.end)}"
    else:
        v = INSUFFICIENT
        summ = ("evidence " + ("starts " + (fmt_local(first_ev) or "never") if not starts else "") +
                (" and " if (not starts and not ends) else "") +
                ("ends " + (fmt_local(last_ev) or "never") if not ends else "") +
                f"; the soak window is {fmt_local(ctx.start)} to {fmt_local(ctx.end)}")
    crit.append(Criterion("C-CONT-3", "continuity", "Evidence reaches the scheduled completion", v, CONFIRMED, summ, True, [],
                          {"first_evidence": stamp(first_ev), "last_evidence": stamp(last_ev)}))
    # C-CONT-4 (not required for acceptance on its own)
    reasons = []
    if clk["discontinuities"]:
        reasons.append(f"{len(clk['discontinuities'])} NTP-vs-Home-Assistant clock discontinuities")
    if rejected:
        reasons.append(f"{rejected} malformed row(s) rejected at import")
    if ooo:
        reasons.append(f"{ooo} out-of-order row(s) in the input files")
    if not clk["available"]:
        v, basis = INSUFFICIENT, NONE
        reasons.append("no NTP Time rows: the dongle clock cannot be compared with the export timestamps")
    else:
        v, basis = (WARNING if reasons else PASS), CONFIRMED
    crit.append(Criterion("C-CONT-4", "continuity", "Timestamp and clock integrity", v, basis,
                          "; ".join(reasons) or f"dongle clock within {r.clock_skew_warn_s} s of the export timestamps "
                          f"(median offset {clk['median_offset_s']} s)", False, reasons,
                          {"median_ntp_offset_s": clk["median_offset_s"], "discontinuities": len(clk["discontinuities"]),
                           "rejected_rows": rejected, "out_of_order_rows": ooo}))

    return {
        "criteria": crit,
        "area": {
            "coverage_pct": pct(coverage), "coverage_basis": coverage_basis, "gaps": [{"from": stamp(a), "to": stamp(b), "seconds": round((b - a).total_seconds(), 1)}
                                                    for a, b in gaps],
            "unavailable": [{"from": stamp(a), "to": stamp(b), "seconds": round((b - a).total_seconds(), 1)} for a, b in unav],
            "restarts": [{"time": stamp(c["t"]), "signals": sorted(c["kinds"]), "details": c["details"], "refs": c["refs"][:8]}
                         for c in unexpected],
            "soak_boot": [{"time": stamp(c["t"]), "signals": sorted(c["kinds"]), "details": c["details"]} for c in soak_boot],
            "continuity_witnesses": witnesses, "continuity_proven": proven,
            "clock": {"median_ntp_offset_s": clk["median_offset_s"],
                      "discontinuities": [{"time": stamp(d["t"]), "offset_s": d["offset_s"]} for d in clk["discontinuities"]]},
            "first_evidence": stamp(first_ev), "last_evidence": stamp(last_ev),
            "daily": days,
        },
    }


__all__ = ["analyse", "unavailable_intervals", "evidence_gaps", "restart_signals"]
