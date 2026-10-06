#!/usr/bin/env python3
"""Reproducible data-quality and descriptive-statistics audit (stdlib only, offline, read-only).

Reads the long-format statistics export produced by export_ha_statistics.py and prints/writes the numbers behind
docs/intelligence/DATA_QUALITY_METHOD.md (method only; the numbers stay private). Output paths are git-ignored.

    python intelligence/tools/quality_report.py --hourly hist_stats_hourly.csv.gz --out quality_report_data.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import stats  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import (audit, build_history, forecast_issue_series, index_stats, iter_stats_csv,  # noqa: E402
                                  load_profile)
from intelligence.pv import PvModel  # noqa: E402
from intelligence.timeutil import HOUR, UTC, utc_from_ts, zone  # noqa: E402
from intelligence.usage import DayTable, weekday_effect  # noqa: E402



def pct(xs, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    return {str(q): round(stats.quantile(xs, q), 2) for q in qs} if xs else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", required=True)
    ap.add_argument("--profile", required=True, help="site profile JSON (see intelligence/profiles/site_profile.example.json)")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = SiteConfig()
    tz = zone(cfg.tz)
    profile = load_profile(a.profile)
    rows = list(iter_stats_csv(a.hourly))
    hist = build_history(rows, profile, cfg)
    out: dict = {"audit": audit(hist)}
    # entity-id prefixes come from the profile (every source lists a `load_power` id), never from code
    by_name = {s["name"]: s["entities"] for s in profile["sources"]}
    DONGLE = by_name["dongle"]["load_power"]["id"].removesuffix("load_power")
    LEGACY = next(e for n, e in by_name.items() if n != "dongle")["load_power"]["id"].removesuffix("load_power")

    wanted = {LEGACY + n for n in ("load_power", "summary_total_load", "summary_day_load", "summary_total_pv",
                                    "summary_total_grid_import_buy", "summary_total_grid_export_sell",
                                    "summary_total_battery_charge", "summary_total_battery_discharge", "battery_soc",
                                    "battery_output_power")}
    wanted |= {DONGLE + n for n in ("load_power", "total_load_energy", "total_pv_energy", "battery_soc")}
    idx = index_stats(rows, wanted)

    # ---- 1. stale (flat-lined) instantaneous power, by month ------------------------------------------------
    lp = idx[LEGACY + "load_power"]
    by_month: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for h, v in lp.items():
        m = utc_from_ts(h).astimezone(tz).strftime("%Y-%m")
        by_month[m][1] += 1
        if v["min"] is not None and v["max"] is not None and abs(v["max"] - v["min"]) <= 0.5 and (v["mean"] or 0) > 0:
            by_month[m][0] += 1
    flat_total = sum(v[0] for v in by_month.values())
    out["legacy_flat_power"] = {
        "hours": flat_total, "of": len(lp), "share": round(flat_total / len(lp), 4),
        "by_month_pct": {m: round(100.0 * f / n, 1) for m, (f, n) in sorted(by_month.items())}}

    # ---- 2. daily integral of power vs counter delta (legacy) ------------------------------------------------
    tot = {h: v["state"] * 1000.0 for h, v in idx[LEGACY + "summary_total_load"].items() if v["state"] is not None}
    days: dict[date, list[int]] = defaultdict(list)
    for h in sorted(tot):
        days[utc_from_ts(h).astimezone(tz).date()].append(h)
    diffs_all, diffs_noflat = [], []
    for d, hs in days.items():
        if len(hs) != 24:
            continue
        ctr = tot[hs[-1]] - tot[hs[0]]
        integ = sum((lp[h]["mean"] or 0) for h in hs if h in lp) / 1000.0
        flats = sum(1 for h in hs if h in lp and lp[h]["min"] is not None and abs(lp[h]["max"] - lp[h]["min"]) <= 0.5
                    and (lp[h]["mean"] or 0) > 0)
        diffs_all.append(integ - ctr)
        if flats == 0:
            diffs_noflat.append(integ - ctr)
    out["integral_vs_counter_legacy_kwh_per_day"] = {
        "days": len(diffs_all), "mae_all": round(stats.mae(diffs_all), 2),
        "days_no_flat_hours": len(diffs_noflat), "mae_no_flat": round(stats.mae(diffs_noflat), 2),
        "bias_no_flat": round(sum(diffs_noflat) / len(diffs_noflat), 2)}

    # ---- 3. daily energy balance residual (legacy totals) -----------------------------------------------------
    def tcol(n):
        return {h: v["state"] * 1000.0 for h, v in idx[LEGACY + n].items() if v["state"] is not None}
    cols = {k: tcol(n) for k, n in (("load", "summary_total_load"), ("pv", "summary_total_pv"),
                                     ("imp", "summary_total_grid_import_buy"), ("exp", "summary_total_grid_export_sell"),
                                     ("chg", "summary_total_battery_charge"), ("dis", "summary_total_battery_discharge"))}
    resid, loads = [], []
    for d, hs in days.items():
        if len(hs) != 24 or any(h not in c for c in cols.values() for h in (hs[0], hs[-1])):
            continue
        dl = {k: c[hs[-1]] - c[hs[0]] for k, c in cols.items()}
        resid.append(dl["pv"] + dl["imp"] + dl["dis"] - dl["load"] - dl["exp"] - dl["chg"])
        loads.append(dl["load"])
    out["energy_balance_legacy_kwh_per_day"] = {
        "days": len(resid), "mean_residual": round(sum(resid) / len(resid), 2), "sd": round(stats.rmse([r - sum(resid) / len(resid) for r in resid]), 2),
        "min": round(min(resid), 2), "max": round(max(resid), 2),
        "median_share_of_load": round(stats.median([abs(r) / l for r, l in zip(resid, loads)]), 3)}

    # ---- 4. inverter day-counter reset hour (local) -----------------------------------------------------------
    dl = {h: v["state"] for h, v in idx[LEGACY + "summary_day_load"].items() if v["state"] is not None}
    hs = sorted(dl)
    reset_hours: dict[int, int] = defaultdict(int)
    for a_, b_ in zip(hs, hs[1:]):
        if b_ - a_ == HOUR and dl[b_] < dl[a_] - 1.0:
            reset_hours[utc_from_ts(b_).astimezone(tz).hour] += 1
    out["legacy_day_counter_reset_local_hour"] = dict(sorted(reset_hours.items()))

    # ---- 5. dongle vs legacy agreement over the overlap ---------------------------------------------------------
    dt = {h: v["state"] for h, v in idx[DONGLE + "total_load_energy"].items() if v["state"] is not None}
    lt = {h: v["state"] * 1000.0 for h, v in idx[LEGACY + "summary_total_load"].items() if v["state"] is not None}
    common = sorted(set(dt) & set(lt))
    dd = [(dt[b] - dt[a]) - (lt[b] - lt[a]) for a, b in zip(common, common[1:]) if b - a == HOUR]
    out["dongle_vs_legacy_hourly_load_energy_kwh"] = {"hours": len(dd), "mean_diff": round(sum(dd) / len(dd), 4),
                                                       "mean_abs_diff": round(stats.mae(dd), 4)}
    dint = []
    dpow = idx[DONGLE + "load_power"]
    for a_, b_ in zip(common, common[1:]):
        if b_ - a_ == HOUR and b_ in dpow and dpow[b_]["mean"] is not None:
            dint.append((dpow[b_]["mean"] / 1000.0, dt[b_] - dt[a_]))
    out["dongle_integral_vs_counter"] = {"hours": len(dint), "integral_kwh": round(sum(x for x, _ in dint), 1),
                                         "counter_kwh": round(sum(y for _, y in dint), 1)}

    # ---- 6. descriptive statistics -----------------------------------------------------------------------------------
    table = DayTable(hist, "load", cfg.tz)
    totals = {d: table.total(d) for d in sorted(table.days) if table.total(d) is not None}
    vals = list(totals.values())
    out["daily_load_kwh"] = {"days": len(vals), "percentiles": pct(vals)}
    wk = [v for d, v in totals.items() if d.weekday() < 5]
    we = [v for d, v in totals.items() if d.weekday() >= 5]
    out["weekday_vs_weekend_mean_kwh"] = {"weekday": round(sum(wk) / len(wk), 2), "weekend": round(sum(we) / len(we), 2)}
    out["median_by_weekday_kwh"] = {str(w): round(stats.median([v for d, v in totals.items() if d.weekday() == w]), 1) for w in range(7)}
    month: dict[str, list[float]] = defaultdict(list)
    for d, v in totals.items():
        month[d.strftime("%Y-%m")].append(v)
    out["monthly_daily_load_kwh"] = {m: {"median": round(stats.median(v), 1), "min": round(min(v), 1), "max": round(max(v), 1)}
                                      for m, v in sorted(month.items())}
    ds = sorted(totals)
    last = [totals[d] for d in ds[-30:]]
    out["rolling_demand_kwh_per_day"] = {"last_7": round(sum(last[-7:]) / len(last[-7:]), 1), "last_14": round(sum(last[-14:]) / len(last[-14:]), 1),
                                          "last_30": round(sum(last) / len(last), 1)}
    prev = [totals[d] for d in ds[-56:-14]]
    out["recent_vs_prior"] = {"last_14_median": round(stats.median(last[-14:]), 1), "previous_42_median": round(stats.median(prev), 1)}
    slots: list[list[float]] = [[] for _ in range(24)]
    for d, s in table.days.items():
        for h in range(24):
            if s[h] is not None:
                slots[h].append(s[h])
    out["hourly_load_kwh_by_local_hour"] = {str(h): {"p10": round(stats.quantile(v, .1), 2), "p50": round(stats.quantile(v, .5), 2), "p90": round(stats.quantile(v, .9), 2)} for h, v in enumerate(slots)}
    # cheap window / overnight / morning
    from intelligence.timeutil import local_wall
    cw, mw = [], []
    for d in ds:
        e = hist.energy_scaled("load", local_wall(d, cfg.cheap_window_start_min, tz), local_wall(d, cfg.cheap_window_end_min, tz), 0.8)
        if e is not None:
            cw.append(e)
        e2 = hist.energy_scaled("load", local_wall(d, cfg.cheap_window_end_min, tz), local_wall(d, 540, tz), 0.8)
        if e2 is not None:
            mw.append(e2)
    out["energy_kwh_distribution"] = {"cheap_window_00:30-05:30": pct(cw), "morning_05:30-09:00": pct(mw)}
    # SOC at key local hours (hourly mean), all history vs last 60 days
    socs: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for h, r in hist.by_start.items():
        if r.soc_mean is not None:
            lt_ = utc_from_ts(h).astimezone(tz)
            if lt_.hour in (0, 5, 7, 12, 17, 22):
                socs[lt_.hour].append((lt_.date(), r.soc_mean))
    out["soc_percentiles_at_local_hour"] = {
        "all": {str(h): pct([v for _d, v in vs]) for h, vs in sorted(socs.items())},
        "last_60_days": {str(h): pct([v for d_, v in vs if d_ >= ds[-60]]) for h, vs in sorted(socs.items())}}
    out["weekday_effect"] = weekday_effect(hist, cfg)

    # ---- 7. Solcast calibration ----------------------------------------------------------------------------------------
    sol = forecast_issue_series(rows, profile["forecasts"]["solcast_day"]["id"], cfg.tz, 6)
    pvm = PvModel(hist, cfg, {"solcast": sol})
    ratios: dict[str, list[float]] = defaultdict(list)
    raw_err, cor_err = [], []
    for d, f in sorted(sol.items()):
        act = pvm.actual(d)
        if act is not None and f >= 1.0:
            ratios[d.strftime("%Y-%m")].append(act / f)
            raw_err.append(act - f)
            r, n = pvm.ratio("solcast", d)
            if r is not None:
                cor_err.append(act - f * r)
    out["solcast_actual_over_forecast_ratio_by_month"] = {m: {"n": len(v), "median": round(stats.median(v), 2), "p10": round(stats.quantile(v, .1), 2), "p90": round(stats.quantile(v, .9), 2)} for m, v in sorted(ratios.items())}
    out["solcast_day_ahead"] = {"days": len(raw_err), "raw_mae_kwh": round(stats.mae(raw_err), 2), "raw_bias_actual_minus_forecast": round(sum(raw_err) / len(raw_err), 2),
                                "corrected_mae_kwh_7d_median_ratio": round(stats.mae(cor_err), 2), "corrected_n": len(cor_err)}

    text = json.dumps(out, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
