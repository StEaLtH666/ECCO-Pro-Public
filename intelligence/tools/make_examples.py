#!/usr/bin/env python3
"""Generate the example reports shipped under docs/intelligence/examples/ from a SYNTHETIC household.

Nothing here is real data: the household is `intelligence.synthetic.make_history` with fixed seeds, in a fictional
year (2030), so a reader can never mistake an example for anybody's actual usage. The reports are the engine's real
output on that synthetic history, so they show real structure and wording.

    python intelligence/tools/make_examples.py            # (re)write docs/intelligence/examples/*.json
    python intelligence/tools/make_examples.py --check    # exit 1 if the checked-in files differ from a fresh run

`--check` compares with a small numeric tolerance (floating-point library differences between platforms) and
ignores `feature_hash`, which depends on rounded floats.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.config import SiteConfig  # noqa: E402
from intelligence.replay import campaign, replay  # noqa: E402
from intelligence.scorecard import Scorecard  # noqa: E402
from intelligence.synthetic import make_history, solcast_like  # noqa: E402
from intelligence.timeutil import UTC, local_wall, zone  # noqa: E402

OUT = ROOT / "docs" / "intelligence" / "examples"
START = date(2030, 4, 1)
DAYS = 200
SEED = 11
EVENING = 21 * 60 + 30

# scenario id -> (file name, description)
FILES = {
    "normal": ("example_normal_evening.json", "Synthetic household, evening, normal conditions, autumn PV over-forecast."),
    "poorpv": ("example_poor_pv_afternoon.json", "Synthetic household, afternoon on which PV is running far below forecast."),
    "afternoon": ("example_afternoon.json", "Synthetic household, late afternoon, normal conditions."),
    "summer": ("example_summer_evening.json", "Synthetic household, summer evening: lower targets and export become possible."),
    "cold": ("example_cold_start.json", "Synthetic household, 4 days of history: the engine must say it is not ready."),
    "live": ("example_live_inputs.json", "Synthetic household with explicit live-style inputs (SOC, powers) on a morning."),
}
ACC_FILE = "example_accuracy_history.json"


def season_factor(d: date) -> float:
    """Raw forecast over-prediction: ~1.0 in summer, rising towards ~1.9 in autumn (a fictional but typical pattern)."""
    if d.month <= 8:
        return 1.0
    return 1.0 + 0.9 * min(1.0, ((d - date(d.year, 8, 31)).days) / 40.0)


def build_inputs():
    cfg = SiteConfig()
    base = make_history(START, DAYS, cfg, seed=SEED)
    raw = solcast_like(base, cfg, over_factor=1.0, noise=0.10, seed=SEED + 1)
    fc = {"solcast": {d: v * season_factor(d) for d, v in raw.items()}}
    poor_day = date(2030, 10, 4)
    poor = make_history(START, DAYS, cfg, seed=SEED, pv_scale_by_day={poor_day: 0.25})
    return cfg, base, poor, fc


def build_reports() -> dict[str, dict]:
    cfg, base, poor, fc = build_inputs()
    tz = zone(cfg.tz)
    spec = {
        "normal": (base, local_wall(date(2030, 10, 4), EVENING, tz), {"soc_override": 62.0}),
        "poorpv": (poor, local_wall(date(2030, 10, 4), 14 * 60, tz), {"soc_override": 78.0}),
        "afternoon": (base, local_wall(date(2030, 10, 3), 17 * 60 + 30, tz), {"soc_override": 75.0}),
        "summer": (base, local_wall(date(2030, 7, 15), EVENING, tz), {"soc_override": 85.0}),
        "cold": (base, local_wall(START + timedelta(days=4), EVENING, tz), {"soc_override": 62.0}),
        "live": (base, local_wall(date(2030, 10, 5), 8 * 60 + 10, tz), {"soc_override": 88.0}),
    }
    out = {}
    for key, (hist, now, kw) in spec.items():
        extra = {"load_w": 1100.0, "pv_w": 200.0} if key == "live" else {}
        rep = replay(hist, cfg, now, fc, **kw, **extra)
        rep.pop("features", None)
        rep["_example"] = {"name": FILES[key][0].removesuffix(".json"), "description": FILES[key][1], "synthetic": True}
        out[key] = json.loads(json.dumps(rep, default=str))
    return out


def build_accuracy() -> dict:
    cfg, base, _poor, fc = build_inputs()
    tz = zone(cfg.tz)
    sc = Scorecard(":memory:")
    first, last = date(2030, 8, 5), date(2030, 10, 3)
    campaign(base, cfg, fc, first, last, EVENING, sc)
    now = local_wall(date(2030, 10, 4), 6 * 60, tz)
    sc.resolve(base, cfg, now)

    def fmt(rows):
        return {r["kind"]: {k: (round(r[k], 3) if isinstance(r[k], float) else r[k])
                            for k in ("n", "mae", "rmse", "bias", "coverage", "band_nominal", "mape_pct", "unit")}
                for r in rows if not r["kind"].startswith("soc_pct")}
    series = {}
    for kind in ("load_kwh:day", "load_kwh:cheap_window", "load_kwh:morning", "pv_kwh:day"):
        rows = sc.db.execute("SELECT * FROM forecasts WHERE status='SCORED' AND kind=? ORDER BY horizon_end_utc DESC LIMIT 14", (kind,)).fetchall()
        series[kind] = [{"target_end_local": datetime.fromisoformat(r["horizon_end_utc"]).astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                         "weekday": datetime.fromisoformat(r["horizon_end_utc"]).astimezone(tz).strftime("%a"),
                         "predicted": round(r["predicted"], 2), "band_low": round(r["band_low"], 2), "band_high": round(r["band_high"], 2),
                         "actual": round(r["actual"], 2), "error": round(r["error"], 2), "in_band": bool(r["in_band"])}
                        for r in reversed(rows)]
    return {
        "_note_soc": "SOC forecast rows are excluded: a campaign replay only has the hourly-mean SOC as input, which lags true SOC by about an hour.",
        "_description": "SYNTHETIC: walk-forward replay of nightly 21:30 shadow runs on a seeded synthetic household "
                        f"({first.isoformat()}..{last.isoformat()}, fictional year), scored against later synthetic history. "
                        "Illustrative of what the scorecard will hold once live; not anybody's real accuracy.",
        "series_last_14": series,
        "accuracy_last_7_days": fmt(sc.metrics(since=now - timedelta(days=7))),
        "all_period_metrics": fmt(sc.metrics()),
        "insights": sc.insights(now),
    }


def build_all() -> dict[str, object]:
    out: dict[str, object] = {FILES[k][0]: v for k, v in build_reports().items()}
    out[ACC_FILE] = build_accuracy()
    return out


def dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def close(a, b, path="") -> list[str]:
    """Structural comparison: exact for everything except floats (relative 1e-6 / absolute 1e-9) and `feature_hash`."""
    if isinstance(a, dict) and isinstance(b, dict):
        bad = []
        for k in sorted(set(a) | set(b)):
            if k == "feature_hash":
                continue
            if k not in a or k not in b:
                bad.append(f"{path}/{k}: key present on one side only")
            else:
                bad += close(a[k], b[k], f"{path}/{k}")
        return bad
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [x for i, (p, q) in enumerate(zip(a, b)) for x in close(p, q, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
            return [] if math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9) else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    out = Path(a.out)
    built = build_all()
    if a.check:
        problems = []
        for name, obj in built.items():
            f = out / name
            if not f.exists():
                problems.append(f"{name}: missing")
                continue
            problems += [f"{name}{p}" for p in close(obj, json.loads(f.read_text(encoding="utf-8")))]
        extra = sorted(p.name for p in out.glob("*.json") if p.name not in built)
        problems += [f"{n}: not produced by the generator (stale or real-data file?)" for n in extra]
        print("\n".join(problems[:30]) if problems else "examples are up to date")
        return 1 if problems else 0
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in built.items():
        (out / name).write_text(dump(obj), encoding="utf-8", newline="\n")
        print("wrote", out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
