"""Run every area over one evidence set and assemble the machine-readable report.

Overall verdict = the worst verdict of the REQUIRED criteria (FAIL > INSUFFICIENT_EVIDENCE > WARNING > PASS); a criterion
that is not required still turns the overall verdict into WARNING or FAIL, but its INSUFFICIENT_EVIDENCE does not block.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import ANALYSER_VERSION, REPORT_SCHEMA, b10, catalogue, continuity, polling, rtc, safety
from .evidence import Evidence, as_bool, as_float, is_missing
from .model import (DEFAULT_SOAK_DAYS, DEFAULT_SOAK_START, FAIL, INSUFFICIENT, PASS, WARNING, Ctx, Rules, make_days, pct, worst)
from .timeutil import fmt_local, stamp


def entity_coverage(ctx: Ctx) -> list:
    out = []
    for e in catalogue.ENTITIES:
        s = ctx.ev.get(e.key)
        if not s or not s.samples:
            out.append({"key": e.key, "firmware_name": e.firmware_name, "area": e.area, "present": False})
            continue
        inwin = s.between(ctx.start, ctx.end)
        unav = 0.0
        for a, b, smp in s.segments(ctx.start, ctx.end):
            if smp is None or is_missing(smp.raw):
                unav += (b - a).total_seconds()
        invalid = []
        for x in s.samples:
            if is_missing(x.raw):
                continue
            if e.kind in ("counter", "maxboot", "numeric") and as_float(x.raw) is None:
                invalid.append((x.ref, x.raw))
            elif e.kind == "binary" and as_bool(x.raw) is None:
                invalid.append((x.ref, x.raw))
        if invalid:
            ctx.ev.invalid_values[e.key] = invalid
            ctx.event(None, "evidence", "WARNING", "invalid-values",
                      f"{e.firmware_name}: {len(invalid)} row(s) not valid for a {e.kind} entity (e.g. {invalid[0][1]!r}); "
                      "ignored, never coerced", "confirmed", [r for r, _ in invalid[:5]])
        out.append({"key": e.key, "firmware_name": e.firmware_name, "area": e.area, "present": True, "entity_id": s.entity_id,
                    "rows": len(s.samples), "rows_in_window": len(inwin), "first": stamp(s.samples[0].t),
                    "last": stamp(s.samples[-1].t), "no_value_pct_of_window": pct(unav / ctx.window_s) if ctx.window_s else None,
                    "invalid_rows": len(invalid)})
    return out


def outstanding(ctx: Ctx, crit: list, areas: dict, now: datetime | None) -> list:
    req = []
    byid = {c.id: c for c in crit}

    def add(what, why):
        req.append({"requirement": what, "why": why})

    if (now is not None and now < ctx.end) or byid["C-CONT-3"].verdict != PASS:
        add(f"Export the evidence again after the scheduled completion ({fmt_local(ctx.end)}) covering the whole window "
            f"from {fmt_local(ctx.start)}", byid["C-CONT-3"].summary)
    if byid["C-CONT-1"].verdict != PASS:
        add("Include `ECCO Supervision Challenge` (boot nonce) and `ECCO Supervision Valid Heartbeat Count` for the full window",
            byid["C-CONT-1"].summary)
    reads = [z for z in ctx.reads if ctx.start <= z.t <= ctx.end]
    nights = sum(1 for z in reads if rtc.daylight(ctx, z.t)[0] is False)
    if not nights:
        add("Observe at least one night of RTC reads (drift ~0: any night background correction is a stale-read candidate)",
            "no night-time RTC read is in the evidence")
    high = [z for z in reads if (rtc.pv_at(ctx, z.t) or 0) >= 2000]
    if not high:
        add("Observe a high-PV midday (>= 2 kW, measured drift about -7 s/min) with its background corrections",
            "no RTC read at >= 2 kW PV is in the evidence" + ("" if ctx.ev.has("pv_power") else " (no ECCO PV Power rows)"))
    pw = areas["rtc"]["precision_windows"]
    if not pw.get("with_read"):
        add("Observe a TOU precision window (one read in [b-120 s, b-60 s) before a zone start, e.g. 00:23-00:24 BST before "
            "00:25)", pw.get("note") or "no regular read inside any precision window is in the evidence")
    elif not pw.get("precision_corrections"):
        add("A precision correction itself (error >= max(P/2, 5 s) inside a precision window) was not exercised",
            f"{pw['with_read']} precision window(s) observed, every one within the precision threshold or held")
    if not ctx.ev.logs:
        add("Capture the firmware log (`esphome logs`) across at least one night: `RTC STALL detected`, `RTC policy:` and "
            "`RTC correction held (...)` lines are the only direct evidence of the stale-first-read mechanism and of Block C errors",
            "no firmware log was supplied; stall-first-read verdicts rest on Home Assistant rows only")
    cands = [e for e in ctx.episodes if e.a.get("classification") in ("stale_first_read_candidate", "false_confirmation_candidate")]
    if cands and not any(e.a.get("stall_on_prior_read") for e in cands):
        add("Confirm the stall flag on the first confirming read of each false-confirmation candidate",
            "candidates exist but no stall evidence was found on their prior reads")
    missing = [x["firmware_name"] for x in areas["coverage"] if not x["present"] and x["area"] in ("rtc", "polling", "b10", "continuity")
               and x["key"] in ("verified_corrections", "failed_corrections", "rtc_stall_count", "rtc_write_attempts",
                                "telemetry_failures", "configuration_failures", "b10", "supervision_challenge",
                                "valid_heartbeats", "last_correction_result", "clock_difference", "inverter_time",
                                "rtc_correction_in_progress", "correction_lock_max", "last_configuration_update")]
    if missing:
        add("Export these diagnostics for the whole window: " + ", ".join(missing), "they are absent from the evidence, so the "
            "criteria that read them cannot be confirmed (absence is never read as zero)")
    for c in crit:
        if c.verdict == INSUFFICIENT and c.required:
            add(f"Evidence for {c.id} ({c.title})", "; ".join(c.reasons[:2]) or c.summary)
    add("Take the 24-48 h counter snapshot after completion (verified / failed corrections, RTC write attempts, stall count, read "
        "failures, lock max ages, supervision events) and compare it with this report",
        "LP-D1 asks for the counters at the end of the soak; HA history only records changes")
    add("Attribute every write, protected-state and setting change listed in the suspicious events (owner, SmartDeye or "
        "firmware)", "a second Modbus master's writes are invisible to the dongle")
    return req


LIMITATIONS = [
    "Home Assistant records a state only when it changes: two equal consecutive Clock Difference reads leave one row (the second "
    "read is recovered from Inverter Time when that entity is exported); identical consecutive Last Correction Result strings "
    "collapse into one row.",
    "Row timestamps are when Home Assistant received the state (typically < 1 s after the dongle published it); quiet-window and "
    "precision-window checks allow Rules.edge_tolerance_s and report boundary cases as `edge`, never as a violation.",
    "Day/night uses ECCO PV Power (>= Rules.daylight_pv_w); without PV rows a fixed local daylight window is used and marked "
    "inferred.",
    "Stale-read classifications are inferences from the read trend, the measured drift envelope (0 / +4.5 / -7 s/min) and the "
    "0-10 s register staleness; only the stall-detector state and the logged policy lines are direct firmware facts.",
    "Writes by another Modbus master are invisible to the dongle; write accounting covers the dongle's own write paths only.",
    "Block C (register 330) errors are attributable only from the firmware log.",
    "A counter's in-window delta is a lower bound when its rows do not span the window; this is flagged per counter.",
]


def run(ev: Evidence, *, start: datetime = DEFAULT_SOAK_START, days: float = DEFAULT_SOAK_DAYS, end: datetime | None = None,
        rules: Rules | None = None, now: datetime | None = None, inputs_note: str = "") -> dict:
    rules = rules or Rules()
    ev.finalise()
    end = end or (start + timedelta(days=days))
    ctx = Ctx(ev, rules, start, end, as_of=now)
    ctx.days = make_days(start, end)
    cont = continuity.analyse(ctx)
    r = rtc.analyse(ctx)
    poll = polling.analyse(ctx)
    saf = safety.analyse(ctx)
    b = b10.analyse(ctx)
    crit = cont["criteria"] + r["criteria"] + b["criteria"] + poll["criteria"] + saf["criteria"]
    areas = {"continuity": cont["area"], "rtc": r["area"], "b10": b["area"], "polling": poll["area"], "safety": saf["area"]}
    areas["coverage"] = entity_coverage(ctx)
    req_v = [c.verdict for c in crit if c.required]
    opt_v = [c.verdict for c in crit if not c.required and c.verdict in (WARNING, FAIL)]
    overall = worst(*(req_v + opt_v))
    blocking = [c.id for c in crit if c.verdict == overall and (c.required or overall in (WARNING, FAIL))]
    # daily table
    daily = []
    for i, d in enumerate(ctx.days):
        row = {"day": d.label, "from": stamp(d.start), "to": stamp(d.end), "hours": round(d.seconds / 3600, 2)}
        for src, key in ((cont["area"]["daily"], ("coverage_pct", "gap_s", "unavailable_s", "restarts")),
                         (r["area"]["daily"], ("corrections", "verified_counter", "failed_counter", "aborts", "stalls_counter",
                                               "night_background", "stale_candidates")),
                         (b["area"]["daily"], ("match_pct_of_day", "match_pct_of_observed", "not_match_s", "blocked_s", "unknown_s",
                                               "no_evidence_s")),
                         (poll["area"]["daily"], ("telemetry_failures", "configuration_failures", "block_b_gaps",
                                                  "configuration_offline_s"))):
            for k in key:
                row[k] = src[i].get(k)
        daily.append(row)
    sev_rank = {"FAIL": 0, "WARNING": 1, "INFO": 2}
    events = sorted(ctx.events, key=lambda e: (e.t is None, e.t or start, sev_rank.get(e.severity, 3)))
    report = {
        "schema": REPORT_SCHEMA,
        "analyser_version": ANALYSER_VERSION,
        "subject": "FB-D1 seven-day soak (ESP32-S3 ECCO clock dongle)",
        "window": {"start": stamp(start), "end": stamp(end), "days": round((end - start).total_seconds() / 86400, 3),
                   "as_of": stamp(now), "complete": bool(now is None or now >= end)},
        "overall": {"verdict": overall, "deciding_criteria": blocking,
                    "rule": "worst required criterion (FAIL > INSUFFICIENT_EVIDENCE > WARNING > PASS); optional criteria add "
                            "WARNING/FAIL only"},
        "criteria": [dict(c.to_dict(), confidence=confidence(c, cont["area"]["coverage_pct"], rules)) for c in crit],
        "daily": daily,
        "areas": areas,
        "a3_stall_veto": r["a3"],
        "suspicious_events": [e.to_dict() for e in events if e.severity in ("FAIL", "WARNING")],
        "informational_events": [e.to_dict() for e in events if e.severity == "INFO"][:300],
        "outstanding_live_proof": outstanding(ctx, crit, areas, now),
        "evidence": {
            "inputs": [{"path": i.path, "format": i.fmt, "sha256": i.sha256, "rows": i.rows, "accepted": i.accepted,
                        "rejected": i.rejected, "first": stamp(i.first), "last": stamp(i.last)} for i in ev.inputs],
            "unknown_entities": dict(sorted(ev.unknown_entities.items())[:200]),
            "diagnostics": [{"severity": d.severity, "code": d.code, "detail": d.detail, "ref": d.ref} for d in ev.diagnostics[:500]],
            "diagnostics_total": len(ev.diagnostics),
            "note": inputs_note,
        },
        "rules": rules.to_dict(),
        "limitations": LIMITATIONS,
    }
    return report


def confidence(c, coverage_pct, rules: Rules) -> str:
    """high: confirmed evidence over (nearly) the whole window; medium: confirmed but partial coverage, or mixed / inferred;
    low: nothing to base the verdict on."""
    if c.verdict == INSUFFICIENT or c.basis == "none":
        return "low"
    if c.basis == "confirmed" and (coverage_pct or 0) >= 100 * rules.coverage_pass:
        return "high"
    return "medium"


def summary_line(report: dict) -> str:
    o = report["overall"]
    n = {v: sum(1 for c in report["criteria"] if c["verdict"] == v) for v in (PASS, WARNING, INSUFFICIENT, FAIL)}
    return (f"FB-D1 soak: {o['verdict']}  ({n[PASS]} pass, {n[WARNING]} warning, {n[INSUFFICIENT]} insufficient, {n[FAIL]} fail; "
            f"{len(report['suspicious_events'])} suspicious event(s))")


__all__ = ["run", "summary_line"]
