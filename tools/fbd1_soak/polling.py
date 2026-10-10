"""Area 4: Modbus read failures and polling liveness (telemetry 10 s, configuration Blocks A/B/C 60 s, D1 catch-up).

`Last Configuration Update` carries the dongle's NTP wall time of every successful Block B response, so its VALUES (not the
Home Assistant row times) give the configuration-poll cadence; `Last Telemetry Update` does the same for telemetry. A Block B
gap that overlaps an evidence gap cannot be verified (Home Assistant may simply have recorded nothing) and is reported as
such. Block C (register 330) failures are only visible in the firmware log: the Configuration Read Failures counter includes
them without telling them apart. An unavailable counter is reported as unavailable, never as zero.
"""

from __future__ import annotations

from datetime import timedelta

from .evidence import as_bool, counter_delta, is_missing
from .model import (CONFIRMED, FAIL, INFERRED, INSUFFICIENT, NONE, PASS, WARNING, Criterion, Ctx, num, overlap_s)
from .timeutil import TimeParseError, fmt_duration, parse_local_near, stamp


def _stamps(ctx: Ctx, key: str) -> list:
    s = ctx.ev.get(key)
    out = []
    if not s:
        return out
    seen = set()
    for x in s.samples:
        if is_missing(x.raw) or not x.raw.strip()[:1].isdigit():
            continue
        try:
            t = parse_local_near(x.raw.strip(), x.t)
        except TimeParseError:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append((t, x.t, x.ref))
    out.sort()
    return out


def off_intervals(ctx: Ctx, key: str) -> tuple:
    s = ctx.ev.get(key)
    off, unav = [], []
    if not s:
        return off, unav
    cur_off = cur_un = None
    for x in s.samples:
        b = as_bool(x.raw)
        if b is False and cur_off is None:
            cur_off = x.t
        if b is not False and cur_off is not None:
            off.append((cur_off, x.t))
            cur_off = None
        if b is None and cur_un is None:
            cur_un = x.t
        if b is not None and cur_un is not None:
            unav.append((cur_un, x.t))
            cur_un = None
    if cur_off is not None:
        off.append((cur_off, max(cur_off, ctx.end)))
    if cur_un is not None:
        unav.append((cur_un, max(cur_un, ctx.end)))
    clip = lambda ivs: [(max(a, ctx.start), min(b, ctx.end)) for a, b in ivs if b > ctx.start and a < ctx.end]  # noqa: E731
    return clip(off), clip(unav)


def cadence(ctx: Ctx, key: str, gap_s: float, early_s: float | None) -> dict:
    st = [x for x in _stamps(ctx, key) if ctx.start - timedelta(minutes=5) <= x[0] <= ctx.end]
    gaps, early = [], []
    for (t0, _, r0), (t1, h1, r1) in zip(st, st[1:]):
        d = (t1 - t0).total_seconds()
        if d > gap_s:
            unverifiable = overlap_s(t0, t1, ctx.gaps) > 0
            gaps.append({"from": t0, "to": t1, "seconds": d, "unverifiable": unverifiable, "refs": [r0, r1]})
        elif early_s is not None and d < early_s:
            after_corr = any(e.t_end and timedelta(0) <= t1 - e.t_end <= timedelta(seconds=120) for e in ctx.episodes)
            early.append({"time": t1, "interval_s": d, "after_rtc_correction": after_corr, "ref": r1})
    return {"stamps": len(st), "gaps": gaps, "early": early}


def analyse(ctx: Ctx) -> dict:
    r = ctx.rules
    ev = ctx.ev
    tel = counter_delta(ev.get("telemetry_failures"), ctx.start, ctx.end)
    cfg = counter_delta(ev.get("configuration_failures"), ctx.start, ctx.end)
    cfg_off, cfg_unav = off_intervals(ctx, "configuration_online")
    tel_off, tel_unav = off_intervals(ctx, "telemetry_online")
    ctx.config_offline = cfg_off
    bb = cadence(ctx, "last_configuration_update", r.block_b_gap_s, r.catchup_early_s)
    tc = cadence(ctx, "last_telemetry_update", r.telemetry_gap_s, None)
    win = [e for e in ev.logs if ctx.start <= e.t <= ctx.end]
    logs = {k: sum(1 for e in win if e.kind == k) for k in ("config_block_error", "block_c_error", "telemetry_error", "config_yield",
                                                            "config_deferred", "block_c_skipped", "telemetry_skipped")}
    by_block = {}
    for e in win:
        if e.kind == "config_block_error":
            blk = next((v for k, v in e.fields.items() if k.startswith("blk")), "?")
            by_block[blk] = by_block.get(blk, 0) + 1
    for g in bb["gaps"]:
        sev = "INFO" if g["unverifiable"] else ("FAIL" if g["seconds"] > r.block_b_fail_s else "WARNING")
        ctx.event(g["from"], "polling", sev, "block-b-gap",
                  f"no successful Block B for {fmt_duration(g['seconds'])}" + (" (overlaps an evidence gap: unverifiable)"
                                                                               if g["unverifiable"] else ""),
                  CONFIRMED if not g["unverifiable"] else INFERRED, g["refs"])
    for a, b in cfg_off:
        d = (b - a).total_seconds()
        ctx.event(a, "polling", "FAIL" if d > r.offline_fail_s else "WARNING", "configuration-offline",
                  f"Configuration Online off for {fmt_duration(d)}", CONFIRMED)
    for a, b in tel_off:
        d = (b - a).total_seconds()
        ctx.event(a, "polling", "FAIL" if d > r.offline_fail_s else "WARNING", "telemetry-offline",
                  f"Telemetry Online off for {fmt_duration(d)}", CONFIRMED)

    daily = []
    for d in ctx.days:
        t1 = counter_delta(ev.get("telemetry_failures"), d.start, d.end)
        c1 = counter_delta(ev.get("configuration_failures"), d.start, d.end)
        daily.append({"day": d.label, "telemetry_failures": t1.delta if t1.available else None,
                      "configuration_failures": c1.delta if c1.available else None,
                      "block_b_gaps": sum(1 for g in bb["gaps"] if d.start <= g["from"] < d.end and not g["unverifiable"]),
                      "configuration_offline_s": round(overlap_s(d.start, d.end, cfg_off), 1)})

    crit = []
    reasons = []
    n_days = max(1.0, ctx.window_s / 86400)
    for name, c in (("Telemetry Read Failures", tel), ("Configuration Read Failures", cfg)):
        if not c.available:
            reasons.append(f"{name} Since Boot: UNAVAILABLE (not the same as zero)")
        else:
            reasons.append(f"{name} Since Boot: +{int(c.delta or 0)}" + ("" if c.spans_window else " (lower bound: does not span the window)"))
    worst_off = max([(b - a).total_seconds() for a, b in cfg_off + tel_off], default=0.0)
    rate = max((tel.delta or 0), (cfg.delta or 0)) / n_days
    if rate > r.read_failures_fail_per_day or worst_off > r.offline_fail_s:
        v = FAIL
    elif not (tel.available and cfg.available and tel.spans_window and cfg.spans_window):
        v = INSUFFICIENT  # a missing or partial counter cannot confirm the failure count (any failures seen are still listed)
    elif (tel.delta or 0) > 0 or (cfg.delta or 0) > 0 or cfg_off or tel_off:
        v = WARNING
    else:
        v = PASS
    if cfg_off or tel_off:
        reasons.append(f"Configuration Online off {len(cfg_off)}x, Telemetry Online off {len(tel_off)}x, longest {fmt_duration(worst_off)}")
    crit.append(Criterion("C-POLL-1", "polling", "Modbus read failures and online state", v,
                          CONFIRMED if (tel.available or cfg.available) else NONE,
                          f"telemetry failures {num(tel.delta) if tel.available else 'unavailable'}, configuration failures "
                          f"{num(cfg.delta) if cfg.available else 'unavailable'}", True, reasons,
                          {"telemetry_failures": tel.delta, "configuration_failures": cfg.delta,
                           "telemetry_counter_available": tel.available, "configuration_counter_available": cfg.available,
                           "configuration_offline_intervals": len(cfg_off), "telemetry_offline_intervals": len(tel_off),
                           "longest_offline_s": worst_off}))
    reasons = []
    real = [g for g in bb["gaps"] if not g["unverifiable"]]
    if not bb["stamps"]:
        v, basis = INSUFFICIENT, NONE
        reasons.append("no Last Configuration Update values: Block B cadence cannot be measured")
    else:
        basis = CONFIRMED
        longest = max((g["seconds"] for g in real), default=0.0)
        v = FAIL if longest > r.block_b_fail_s else (WARNING if real else PASS)
        reasons.append(f"{bb['stamps']} Block B successes; {len(real)} gap(s) > {r.block_b_gap_s:.0f} s (longest "
                       f"{fmt_duration(longest)}); {len(bb['gaps']) - len(real)} unverifiable gap(s) inside evidence gaps")
        reasons.append(f"{len(bb['early'])} early poll(s) (< {r.catchup_early_s:.0f} s after the previous one), "
                       f"{sum(1 for x in bb['early'] if x['after_rtc_correction'])} within 2 min of an RTC correction release "
                       "(consistent with the D1 catch-up; inferred)")
        if ev.logs:
            reasons.append(f"log: {logs['config_yield']} Block B yield(s) with catch-up owed, {logs['config_deferred']} deferred poll(s)")
    crit.append(Criterion("C-POLL-2", "polling", "Configuration poll (Block B) continuity", v, basis,
                          f"{len(real)} Block B interruption(s)", True, reasons,
                          {"block_b_successes": bb["stamps"], "gaps": len(real), "unverifiable_gaps": len(bb["gaps"]) - len(real),
                           "early_polls": len(bb["early"])}))
    reasons = []
    if not ev.logs:
        v, basis = INSUFFICIENT, NONE
        reasons.append("Block C (register 330) errors are only visible in the firmware log, and no log was supplied; they are "
                       "included in Configuration Read Failures without attribution")
    else:
        basis = CONFIRMED
        v = WARNING if (logs["block_c_error"] or by_block) else PASS
        reasons.append(f"log: {logs['block_c_error']} Block C error(s), {logs['block_c_skipped']} skipped read(s) (not failures), "
                       f"Block A/B errors {by_block or 0}, telemetry errors {logs['telemetry_error']}")
    crit.append(Criterion("C-POLL-3", "polling", "Block A/B/C read errors (firmware log)", v, basis,
                          f"{logs['block_c_error']} Block C error(s)" if ev.logs else "no firmware log", False, reasons,
                          {"block_c_errors": logs["block_c_error"] if ev.logs else None, "block_errors": by_block}))
    return {
        "criteria": crit,
        "area": {
            "telemetry_failures": {"available": tel.available, "delta": tel.delta, "spans_window": tel.spans_window},
            "configuration_failures": {"available": cfg.available, "delta": cfg.delta, "spans_window": cfg.spans_window},
            "configuration_offline": [{"from": stamp(a), "to": stamp(b), "seconds": round((b - a).total_seconds(), 1)} for a, b in cfg_off],
            "telemetry_offline": [{"from": stamp(a), "to": stamp(b), "seconds": round((b - a).total_seconds(), 1)} for a, b in tel_off],
            "configuration_online_unavailable_s": round(sum((b - a).total_seconds() for a, b in cfg_unav), 1),
            "block_b": {"successes": bb["stamps"],
                        "gaps": [{"from": stamp(g["from"]), "to": stamp(g["to"]), "seconds": round(g["seconds"], 1),
                                  "unverifiable": g["unverifiable"]} for g in bb["gaps"]],
                        "early_polls": [{"time": stamp(x["time"]), "interval_s": round(x["interval_s"], 1),
                                         "after_rtc_correction": x["after_rtc_correction"]} for x in bb["early"][:100]]},
            "telemetry": {"successes": tc["stamps"], "gaps": len(tc["gaps"]),
                          "longest_gap_s": max((g["seconds"] for g in tc["gaps"]), default=None)},
            "log_counts": logs if ev.logs else None,
            "block_errors_by_block": by_block,
            "daily": daily,
        },
    }
