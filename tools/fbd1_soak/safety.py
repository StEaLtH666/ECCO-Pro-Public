"""Area 6 (safety / write authority) and area 5 (part 2: supervision, durable state, health warnings).

WRITE ACCOUNTING. The dongle counts every inverter write path it owns: RTC writes (RTC Write Attempts Since Boot), manual
configuration writes, Free Power and Dump to Grid starts / restores. Every RTC write must belong to a correction (at most
Rules.max_write_attempts_per_correction attempts each). An absent counter makes the "no unexpected write" claim
INSUFFICIENT: no logged write is not evidence of no write. Writes by a second Modbus master (for example a SmartDeye
reader with writable clock controls) are invisible to the dongle and to this analysis.
"""

from __future__ import annotations

from . import catalogue
from .evidence import as_bool, as_float, counter_delta, is_missing
from .model import CONFIRMED, FAIL, INSUFFICIENT, NONE, PASS, WARNING, Criterion, Ctx, merge_intervals, num, overlap_s
from .timeutil import fmt_duration, stamp


def _on_intervals(ctx: Ctx, key: str) -> list:
    s = ctx.ev.get(key)
    out, on = [], None
    if not s:
        return out
    for x in s.samples:
        b = as_bool(x.raw)
        if b and on is None:
            on = x.t
        elif b is not True and on is not None:
            out.append((on, x.t))
            on = None
    if on is not None:
        out.append((on, max(on, ctx.end)))
    return [(max(a, ctx.start), min(b, ctx.end)) for a, b in out if b > ctx.start and a < ctx.end]


def _changes(ctx: Ctx, key: str) -> list:
    s = ctx.ev.get(key)
    if not s:
        return []
    out = []
    prev = s.at(ctx.start)
    prev_v = None if (prev is None or is_missing(prev.raw)) else prev.raw.strip()
    for x in s.between(ctx.start, ctx.end):
        if is_missing(x.raw):
            continue
        v = x.raw.strip()
        if prev_v is not None and v != prev_v:
            out.append((x.t, prev_v, v, x.ref))
        prev_v = v
    return out


def analyse(ctx: Ctx) -> dict:
    r = ctx.rules
    ev = ctx.ev
    C = {k: counter_delta(ev.get(k), ctx.start, ctx.end) for k in (
        "rtc_write_attempts", "manual_write_attempts", "manual_write_successes", "manual_write_failures", "fp_start_attempts",
        "fp_start_successes", "fp_restore_successes", "fp_failures", "dtg_start_attempts", "dtg_start_successes",
        "dtg_restore_successes", "dtg_failures", "verified_corrections", "failed_corrections", "suspect_events", "lost_events",
        "invalid_heartbeats")}
    lease = merge_intervals(_on_intervals(ctx, "free_power_active") + _on_intervals(ctx, "dump_active") +
                            _on_intervals(ctx, "free_power_op") + _on_intervals(ctx, "dump_op"))
    ctx.lease_intervals = lease
    manual_iv = _on_intervals(ctx, "manual_write_in_progress")
    rtc_iv = _on_intervals(ctx, "rtc_correction_in_progress")

    # --- write accounting
    eps = [e for e in ctx.episodes]
    ep_attempts = sum(max(e.attempts, len(e.acks)) for e in eps)
    att = C["rtc_write_attempts"]
    ver, fail = C["verified_corrections"], C["failed_corrections"]
    unexplained = None
    if att.available:
        n_corr = max((ver.delta or 0) + (fail.delta or 0), len([e for e in eps if e.outcome in ("verified", "failed", "aborted")]))
        allowed = n_corr * r.max_write_attempts_per_correction
        unexplained = max(0.0, (att.delta or 0) - allowed)
        if unexplained > 0:
            ctx.event(None, "safety", "WARNING", "unexplained-rtc-writes",
                      f"{int(att.delta)} RTC write attempt(s) for {n_corr} correction(s): {int(unexplained)} more than "
                      f"{r.max_write_attempts_per_correction} per correction", CONFIRMED)
        if ver.available and (att.delta or 0) < (ver.delta or 0):
            ctx.event(None, "safety", "WARNING", "write-count-inconsistent",
                      f"fewer RTC write attempts (+{int(att.delta or 0)}) than verified corrections (+{int(ver.delta or 0)})",
                      CONFIRMED)
    other_writes = {k: C[k].delta for k in ("manual_write_attempts", "fp_start_attempts", "dtg_start_attempts") if C[k].available}
    for k, d in other_writes.items():
        if d:
            for t, amount, ref in C[k].increments:
                ctx.event(t, "safety", "WARNING", "write-operation",
                          f"{catalogue.BY_KEY[k].firmware_name} +{int(amount)}: an inverter write path ran during the soak "
                          "(owner must attribute it)", CONFIRMED, [ref])
    fails = {k: C[k].delta for k in ("manual_write_failures", "fp_failures", "dtg_failures") if C[k].available}
    for k, d in fails.items():
        if d:
            ctx.event(None, "safety", "WARNING", "write-failure", f"{catalogue.BY_KEY[k].firmware_name} +{int(d)}", CONFIRMED)

    # --- lease / ownership interaction
    lease_violations = [e for e in eps if any(c["check"] == "lease-hold" and c["result"] == "violation"
                                              for c in e.a.get("policy", {}).get("checks", []))]
    contention = []
    for a, b in rtc_iv:
        o = overlap_s(a, b, manual_iv)
        if o > 0:
            contention.append((a, b, o))
    ack_in_manual = [e for e in eps for t in e.acks if any(x <= t <= y for x, y in manual_iv)]
    for e in ack_in_manual:
        ctx.event(e.acks[0], "safety", "FAIL", "rtc-write-during-manual-write",
                  f"RTC write of correction #{e.idx} acknowledged while Manual Write In Progress was on", CONFIRMED, e.refs[:4])
    for a, b, o in contention:
        ctx.event(a, "safety", "INFO", "write-path-contention",
                  f"RTC correction lock and manual write overlapped for {o:.0f} s (the RTC write must defer)", CONFIRMED)
    corr_in_lease = [e for e in eps if e.t and any(x <= e.t <= y for x, y in lease)]

    # --- lock ages
    def vals(key):
        s = ev.get(key)
        return [v for v in (as_float(x.raw) for x in (s.between(ctx.start, ctx.end) if s else [])) if v is not None]

    wl = vals("write_lock_age") + vals("write_lock_max")
    wl_max = max(wl, default=None)
    if wl_max is not None and wl_max > r.write_lock_leak_s:
        ctx.event(None, "safety", "FAIL", "write-lock-leak", f"Modbus write lock held {wl_max:.0f} s (leak signature)", CONFIRMED)
    elif wl_max is not None and wl_max > r.write_lock_warn_s:
        ctx.event(None, "safety", "WARNING", "write-lock-long", f"Modbus write lock held up to {wl_max:.0f} s", CONFIRMED)

    # --- protected control state and operator settings
    prot = []
    for key in catalogue.PROTECTED_KEYS + catalogue.SETTING_KEYS:
        for t, a, b, ref in _changes(ctx, key):
            prot.append({"time": stamp(t), "entity": catalogue.BY_KEY[key].firmware_name, "from": a, "to": b, "ref": ref})
            ctx.event(t, "safety", "WARNING", "protected-state-change" if key in catalogue.PROTECTED_KEYS else "setting-change",
                      f"{catalogue.BY_KEY[key].firmware_name}: {a!r} -> {b!r}", CONFIRMED, [ref])

    # --- supervision / durable state / health
    sup = {}
    s = ev.get("supervision_state")
    if s:
        for a, b, smp in s.segments(ctx.start, ctx.end):
            k = "NO_EVIDENCE" if smp is None else (smp.raw.strip() if not is_missing(smp.raw) else "UNAVAILABLE")
            sup[k] = sup.get(k, 0.0) + (b - a).total_seconds()
    prof = _changes(ctx, "profile_state")
    shadow = _changes(ctx, "shadow_state")
    for t, a, b, ref in prof:
        ctx.event(t, "supervision", "WARNING", "profile-state-change", f"Fallback Profile State {a!r} -> {b!r} (durable state "
                  "disturbance?)", CONFIRMED, [ref])
    warn_vals = []
    for key in ("inverter_warning", "inverter_fault"):
        for t, a, b, ref in _changes(ctx, key):
            warn_vals.append({"time": stamp(t), "entity": catalogue.BY_KEY[key].firmware_name, "from": a, "to": b})
            ctx.event(t, "supervision", "INFO", "inverter-health", f"{catalogue.BY_KEY[key].firmware_name}: {a!r} -> {b!r}",
                      CONFIRMED, [ref])
    win_logs = [e for e in ev.logs if ctx.start <= e.t <= ctx.end]
    blocked = [e for e in win_logs if e.kind == "recovery_blocked"]
    for e in blocked:
        ctx.event(e.t, "supervision", "FAIL", "recovery-blocked", e.msg[:160], CONFIRMED, [e.ref])
    errs = [e for e in win_logs if e.level == "E"]
    warns = {}
    for e in win_logs:
        if e.level == "W":
            warns[e.tag] = warns.get(e.tag, 0) + 1
    for e in errs:
        if e.kind not in ("recovery_blocked",):
            ctx.event(e.t, "supervision", "WARNING", "firmware-error-log", f"[{e.tag}] {e.msg[:160]}", CONFIRMED, [e.ref])

    crit = []
    # C-SAFE-1 write accounting
    reasons = []
    if not att.available:
        v, basis = INSUFFICIENT, NONE
        reasons.append("RTC Write Attempts Since Boot is not in the evidence: RTC writes cannot be accounted for")
    else:
        basis = CONFIRMED
        reasons.append(f"RTC write attempts +{int(att.delta or 0)}, attributed to corrections; unexplained "
                       f"{int(unexplained or 0)}")
        v = WARNING if unexplained else PASS
        if not att.spans_window:
            v = INSUFFICIENT if v == PASS else v
            reasons.append("the RTC write counter does not span the window")
    missing = [catalogue.BY_KEY[k].firmware_name for k in ("manual_write_attempts", "fp_start_attempts", "dtg_start_attempts")
               if not C[k].available]
    if missing:
        reasons.append("unavailable (cannot be counted as zero): " + ", ".join(missing))
        if v == PASS:
            v = INSUFFICIENT
    if any(other_writes.values()):
        v = WARNING if v in (PASS,) else v
        reasons.append("other write paths ran: " + ", ".join(f"{catalogue.BY_KEY[k].firmware_name} +{int(d)}"
                                                             for k, d in other_writes.items() if d))
    if any(fails.values()):
        reasons.append("write failures: " + ", ".join(f"{catalogue.BY_KEY[k].firmware_name} +{int(d)}" for k, d in fails.items() if d))
        v = WARNING if v == PASS else v
    if prot:
        reasons.append(f"{len(prot)} protected control state / setting change(s) (see the events)")
        v = WARNING if v == PASS else v
    if wl_max is not None and wl_max > r.write_lock_leak_s:
        v = FAIL
        reasons.append(f"Modbus write lock held {wl_max:.0f} s (leak > {r.write_lock_leak_s:.0f} s)")
    elif wl_max is not None and wl_max > r.write_lock_warn_s:
        v = WARNING if v == PASS else v
        reasons.append(f"Modbus write lock held up to {wl_max:.0f} s")
    reasons.append("writes by another Modbus master are invisible to the dongle and to this analysis")
    crit.append(Criterion("C-SAFE-1", "safety", "Write accounting: no unexpected inverter writes", v, basis,
                          f"RTC writes {int(att.delta) if att.available and att.delta is not None else 'unavailable'}; other write "
                          f"paths {sum(int(d or 0) for d in other_writes.values()) if other_writes else 'unavailable'}", True,
                          reasons, {"rtc_write_attempts": att.delta, "episode_attempts": ep_attempts, "unexplained_rtc_writes": unexplained,
                                    "other_writes": other_writes, "write_failures": fails, "write_lock_max_s": wl_max,
                                    "protected_changes": len(prot)}))
    # C-SAFE-2 lease / ownership
    reasons = []
    lease_ev = any(ev.has(k) for k in ("free_power_active", "dump_active", "free_power_op", "dump_op"))
    if lease_violations or ack_in_manual:
        v = FAIL
        if lease_violations:
            reasons.append(f"{len(lease_violations)} non-large correction(s) queued during a lease: "
                           + ", ".join(f"#{e.idx}" for e in lease_violations))
        if ack_in_manual:
            reasons.append(f"{len(ack_in_manual)} RTC write(s) acknowledged during a manual write")
    elif not lease_ev:
        v = INSUFFICIENT
        reasons.append("Free Power / Dump to Grid lease state is not in the evidence")
    else:
        v = PASS
        reasons.append(f"{len(lease)} lease interval(s) ({fmt_duration(sum((b - a).total_seconds() for a, b in lease))}); "
                       f"{len(corr_in_lease)} correction(s) inside a lease, all large-error exempt" if corr_in_lease else
                       f"{len(lease)} lease interval(s); no RTC correction inside a lease")
    if contention:
        reasons.append(f"{len(contention)} RTC/manual write-path overlap(s) (the RTC write defers; informational)")
    crit.append(Criterion("C-SAFE-2", "safety", "Lease and write-ownership interaction", v, CONFIRMED if lease_ev else NONE,
                          f"{len(lease)} lease interval(s), {len(lease_violations)} lease violation(s)", True, reasons,
                          {"lease_intervals": len(lease), "corrections_in_lease": len(corr_in_lease),
                           "lease_violations": len(lease_violations), "rtc_manual_overlaps": len(contention)}))
    # C-SUP-1 supervision / durable state
    reasons = []
    sus = C["suspect_events"]
    lost = C["lost_events"]
    have_sup = ev.has("supervision_state") or sus.available or lost.available or ev.has("profile_state")
    if blocked:
        v = FAIL
        reasons.append(f"{len(blocked)} RECOVERY BLOCKED log line(s)")
    elif not have_sup:
        v = INSUFFICIENT
        reasons.append("no supervision state, supervision event counters or fallback profile state in the evidence")
    else:
        v = PASS
        if (sus.delta or 0) > 0 or (lost.delta or 0) > 0:
            v = WARNING
        reasons.append(f"supervision SUSPECT events +{num(sus.delta) if sus.available else 'unavailable'}, LOST events "
                       f"+{num(lost.delta) if lost.available else 'unavailable'}")
        if sup:
            reasons.append("time by supervision state: " + ", ".join(f"{k} {fmt_duration(x)}" for k, x in sorted(sup.items())))
        if prof:
            v = WARNING
            reasons.append(f"{len(prof)} Fallback Profile State change(s)")
        if errs:
            v = WARNING
            reasons.append(f"{len(errs)} firmware E-level log line(s)")
        if not (sus.available and lost.available):
            v = INSUFFICIENT if v == PASS else v
            reasons.append("supervision event counters incomplete")
    crit.append(Criterion("C-SUP-1", "supervision", "D1 supervision and durable state undisturbed", v,
                          CONFIRMED if have_sup else NONE, "; ".join(reasons[:2]), True, reasons,
                          {"suspect_events": sus.delta, "lost_events": lost.delta, "profile_changes": len(prof),
                           "shadow_changes": len(shadow), "error_log_lines": len(errs)}))
    return {
        "criteria": crit,
        "area": {
            "counters": {k: {"available": c.available, "delta": c.delta, "spans_window": c.spans_window} for k, c in C.items()},
            "lease_intervals": [{"from": stamp(a), "to": stamp(b), "seconds": round((b - a).total_seconds(), 1)} for a, b in lease],
            "corrections_in_lease": [e.idx for e in corr_in_lease],
            "rtc_manual_overlaps": len(contention),
            "write_lock_max_s": wl_max,
            "protected_changes": prot,
            "supervision_time_s": {k: round(x, 1) for k, x in sup.items()},
            "profile_state_changes": [{"time": stamp(t), "from": a, "to": b} for t, a, b, _ in prof],
            "shadow_state_changes": len(shadow),
            "inverter_health_changes": warn_vals,
            "log_warnings_by_tag": warns,
            "log_errors": len(errs),
        },
    }


__all__ = ["analyse"]
