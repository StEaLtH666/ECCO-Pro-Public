"""Developer CLI: audit / backtest / replay against an exported HA statistics file. Read-only, offline.

    python -m intelligence audit    --stats hist_stats_hourly.csv.gz
    python -m intelligence backtest --stats hist_stats_hourly.csv.gz --from 2030-02-01 --to 2030-10-04
    python -m intelligence replay   --stats hist_stats_hourly.csv.gz --now 2030-10-04T21:30 --soc 62

Never contacts Home Assistant or any device: it only reads the file you give it."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from . import backtest as bt
from .config import SiteConfig
from .history import audit, build_history, forecast_issue_series, iter_stats_csv, load_profile
from .replay import replay
from .timeutil import zone



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m intelligence", description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["audit", "backtest", "replay"])
    ap.add_argument("--stats", required=True, help="long-format HA statistics export (csv or csv.gz)")
    ap.add_argument("--profile", required=True,
                    help="site profile JSON (copy intelligence/profiles/site_profile.example.json to a *.local.json and fill in your entity ids)")
    ap.add_argument("--lat", type=float, default=51.5)
    ap.add_argument("--lon", type=float, default=-0.1)
    ap.add_argument("--pv-kwp", type=float, default=None,
                    help="array nameplate kWp for the PV plausibility ceiling (default: the profile's site.pv_array_kwp, else SiteConfig's; 0 = unknown)")
    ap.add_argument("--reserve-soc", type=float, default=None,
                    help="minimum battery reserve %% (default: the profile's site.user_reserve_soc_pct, else 40)")
    ap.add_argument("--technical-min-soc", type=float, default=None,
                    help="technical minimum SOC %% the reserve can never go below (default: the profile's site.technical_min_soc_pct, else 10)")
    ap.add_argument("--from", dest="d_from")
    ap.add_argument("--to", dest="d_to")
    ap.add_argument("--now", help="local ISO time, e.g. 2030-10-04T21:30")
    ap.add_argument("--soc", type=float)
    a = ap.parse_args(argv)

    profile = load_profile(a.profile)
    kwp = a.pv_kwp if a.pv_kwp is not None else profile.get("site", {}).get("pv_array_kwp")
    extra = {} if kwp is None else {"pv_array_kwp": kwp or None}      # 0 = explicitly unknown
    site = profile.get("site", {})
    for key, cli in (("user_reserve_soc_pct", a.reserve_soc), ("technical_min_soc_pct", a.technical_min_soc)):
        val = cli if cli is not None else site.get(key)
        if val is not None:
            extra[key] = val                  # SiteConfig validates it (finite, 0-100, below max SOC) and refuses a bad value
    cfg = SiteConfig(latitude=a.lat, longitude=a.lon, **extra)
    rows = list(iter_stats_csv(a.stats))
    hist = build_history(rows, profile, cfg)
    if a.command == "audit":
        print(json.dumps(audit(hist), indent=2))
        return 0
    if a.command == "backtest":
        rs = bt.backtest_usage(hist, cfg, date.fromisoformat(a.d_from), date.fromisoformat(a.d_to))
        print(json.dumps({"summary": bt.summarise(rs), "experts_mae": bt.expert_comparison(rs)}, indent=2))
        return 0
    fc = {name.replace("_day", ""): forecast_issue_series(rows, spec["id"], cfg.tz, 6)
          for name, spec in profile.get("forecasts", {}).items() if name in ("solcast_day",)}
    now = datetime.fromisoformat(a.now).replace(tzinfo=zone(cfg.tz))
    rep = replay(hist, cfg, now, fc, soc_override=a.soc)
    rep.pop("features", None)
    print(json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
