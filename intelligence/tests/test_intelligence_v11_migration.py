#!/usr/bin/env python3
"""Proof migration: `replay.inputs_from_history` now goes History -> ecco_core Snapshot -> LiveInputs
(intelligence/inputs.py). This suite proves the behaviour is preserved against a verbatim copy of the OLD implementation
(commit 8292a91): identical LiveInputs on 400 randomised SYNTHETIC cases (fictional years 2030+), byte-identical engine
reports on every shipped example scenario and more, and exactly the documented, deliberate differences for inputs that
are not finite numbers or a `now` with a fraction of a second."""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "intelligence" / "tools"))

import intelligence.replay as replay_mod  # noqa: E402
from intelligence.advisor import LiveInputs, TariffInfo, default_cheap_windows  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History  # noqa: E402
from intelligence.inputs import history_snapshot  # noqa: E402
from intelligence.synthetic import make_history, solcast_like  # noqa: E402
from intelligence.timeutil import HOUR, day_bounds, local_wall, ts, zone  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def legacy_inputs_from_history(history: History, cfg: SiteConfig, now: datetime,
                               forecasts: dict[str, dict[date, float]] | None = None,
                               soc_override: float | None = None) -> LiveInputs:
    """VERBATIM the implementation at commit 8292a91 (the oracle)."""
    tz = zone(cfg.tz)
    last_hour = ts(now) - (ts(now) % HOUR) - HOUR
    rec = history.get(last_hour)
    soc = soc_override if soc_override is not None else (rec.soc_mean if rec else None)
    today = now.astimezone(tz).date()
    f = forecasts or {}
    raw_today = {s: v[today] for s, v in f.items() if today in v}
    raw_tom = {s: v[today + timedelta(days=1)] for s, v in f.items() if (today + timedelta(days=1)) in v}
    t0, _ = day_bounds(today, tz)
    so_far, cov = history.energy("pv", t0, now)
    return LiveInputs(
        now=now, soc_pct=soc, soc_age_s=0.0 if soc_override is not None else (None if rec is None else (ts(now) - (last_hour + HOUR)) + 0.0),
        load_w=None if rec is None else rec.load_w_mean, pv_w=None if rec is None else rec.pv_w_mean,
        pv_raw_today=raw_today, pv_raw_tomorrow=raw_tom,
        pv_actual_so_far_kwh=(so_far / cov) if cov > 0.7 else None,
        tariff=TariffInfo(default_cheap_windows(cfg, now)), inverter_ok=True)


def as_tuple(x: LiveInputs) -> tuple:
    """Every field, with types, and dicts with their ORDER (a source order change would be a behaviour change)."""
    out = []
    for f in fields(LiveInputs):
        v = getattr(x, f.name)
        if isinstance(v, dict):
            v = tuple((k, type(w).__name__, repr(w)) for k, w in v.items())
        elif isinstance(v, TariffInfo):
            v = (tuple(v.cheap_windows), v.import_cheap_p, v.import_peak_p, v.export_p, v.source)
        out.append((f.name, type(v).__name__, repr(v)))
    return tuple(out)


cfg = SiteConfig()
tz = zone(cfg.tz)
NEW = replay_mod.inputs_from_history

print("[1] identical LiveInputs on randomised synthetic cases")
rnd = random.Random(20301)
diffs, n_cases = [], 0
for i in range(400):
    start = date(2030, 1, 1) + timedelta(days=rnd.randrange(0, 300))
    days = rnd.choice((2, 5, 12, 30, 45))
    h = make_history(start, days, cfg, seed=rnd.randrange(1000), soc_noise=rnd.choice((0.0, 2.0)),
                     drop_hours={ts(local_wall(start, 0, tz)) + HOUR * k for k in range(0, days * 24, rnd.choice((3, 7, 11, 10_000)))})
    if rnd.random() < 0.2:                      # some hours with SOC unknown but the record present
        for r in list(h.by_start.values())[::5]:
            r.soc_mean = None
    now = local_wall(start + timedelta(days=rnd.randrange(0, days + 2)), rnd.randrange(0, 1440), tz) + timedelta(seconds=rnd.choice((0, 0, 17)))
    fc = {}
    for src in rnd.sample(["solcast", "forecast.solar", "src 3"], rnd.randrange(0, 4)):
        fc[src] = {start + timedelta(days=k): rnd.choice((rnd.uniform(0, 40), 0.0, -2.0, None, float("nan"), "12", True))
                   for k in range(-1, days + 3) if rnd.random() < 0.8}
    soc = rnd.choice((None, None, round(rnd.uniform(-10, 110), 2), 62.0, 62, 140.0))
    hh = h.truncated(now)
    a, b = legacy_inputs_from_history(hh, cfg, now, fc, soc), NEW(hh, cfg, now, fc, soc)
    n_cases += 1
    if as_tuple(a) != as_tuple(b):
        diffs.append((i, [x for x, y in zip(as_tuple(a), as_tuple(b)) if x != y][:2]))
check(f"{n_cases} cases (gaps, unknown SOC, odd forecast values, int / float / out-of-range overrides): every field identical",
      not diffs, str(diffs[:2]))
check("the new path really goes through a Snapshot", history_snapshot(make_history(date(2030, 6, 1), 3, cfg), cfg,
      local_wall(date(2030, 6, 3), 600, tz)).get("battery.soc").kind == "derived")
from ecco_core.state import RAW, Observation, Snapshot  # noqa: E402
from intelligence.inputs import live_inputs_from_snapshot  # noqa: E402

try:
    live_inputs_from_snapshot(Snapshot.of(local_wall(date(2030, 6, 3), 600, tz),
                                          [Observation("pv.forecast.today.x", 5.0, None, "somewhere", RAW, raw=5.0)]))
    check("a forecast observation not built by forecast_observations() is refused loudly", False)
except ValueError:
    check("a forecast observation not built by forecast_observations() is refused loudly", True)

print("[2] byte-identical engine reports (every shipped example scenario and more)")
import make_examples as mx  # noqa: E402

c2, base, poor, fc2 = mx.build_inputs()
scen = [(base, local_wall(date(2030, 10, 4), mx.EVENING, tz), {"soc_override": 62.0}),
        (poor, local_wall(date(2030, 10, 4), 14 * 60, tz), {"soc_override": 78.0}),
        (base, local_wall(date(2030, 10, 3), 17 * 60 + 30, tz), {"soc_override": 75.0}),
        (base, local_wall(date(2030, 7, 15), mx.EVENING, tz), {"soc_override": 85.0}),
        (base, local_wall(mx.START + timedelta(days=4), mx.EVENING, tz), {"soc_override": 62.0}),
        (base, local_wall(date(2030, 10, 5), 8 * 60 + 10, tz), {"soc_override": 88.0, "load_w": 1100.0, "pv_w": 200.0}),
        (base, local_wall(date(2030, 9, 1), 19 * 60, tz), {}),                         # SOC from history, not an override
        (base, local_wall(date(2030, 6, 21), 3 * 60, tz), {"soc_override": None}),
        (base, local_wall(date(2030, 8, 15), 23 * 60 + 59, tz), {"ha_reserve_pct": 55.0})]


def report(fn, hist, now, kw) -> str:
    saved = replay_mod.inputs_from_history
    replay_mod.inputs_from_history = fn
    try:
        return json.dumps(replay_mod.replay(hist, c2, now, fc2, **kw), sort_keys=True, default=str)
    finally:
        replay_mod.inputs_from_history = saved


same = [report(legacy_inputs_from_history, h_, n_, kw) == report(NEW, h_, n_, kw) for h_, n_, kw in scen]
check(f"{len(scen)} scenarios: the full report (feature hash included) is byte-identical", all(same), str(same))

print("[3] the documented, deliberate differences - and nothing else")
h3 = make_history(date(2030, 5, 1), 40, cfg, seed=5)
n3 = local_wall(date(2030, 6, 8), 21 * 60 + 30, tz)
for bad in (float("nan"), float("inf")):
    a = legacy_inputs_from_history(h3.truncated(n3), cfg, n3, None, bad)
    b = NEW(h3.truncated(n3), cfg, n3, None, bad)
    check(f"SOC override {bad!r}: only soc_pct differs (dropped at the snapshot boundary)",
          [x[0] for x, y in zip(as_tuple(a), as_tuple(b)) if x != y] == ["soc_pct"] and b.soc_pct is None)
    ra = report(legacy_inputs_from_history, h3, n3, {"soc_override": bad})
    rb = report(NEW, h3, n3, {"soc_override": bad})
    ja, jb = json.loads(ra), json.loads(rb)
    check(f"...and the report differs only by the engine's 'is ignored' note (same status, same advice)",
          ja["status"] == jb["status"] and ja["recommended"] == jb["recommended"]
          and [n for n in ja["notes"] if n not in jb["notes"]] == [f"SOC reading {bad} is outside 0-100 and is ignored"]
          and {k: v for k, v in ja.items() if k not in ("notes",)} == {k: v for k, v in jb.items() if k not in ("notes",)})
hb = make_history(date(2030, 5, 1), 40, cfg, seed=5)
rec = hb.get(ts(n3) - ts(n3) % HOUR - HOUR)
rec.load_w_mean = float("inf")
a, b = legacy_inputs_from_history(hb.truncated(n3), cfg, n3), NEW(hb.truncated(n3), cfg, n3)
check("an infinite history power is dropped at the boundary (old: passed on, then dropped by the engine)",
      a.load_w == float("inf") and b.load_w is None and [x[0] for x, y in zip(as_tuple(a), as_tuple(b)) if x != y] == ["load_w"])
nf = n3 + timedelta(microseconds=600_000)
a, b = legacy_inputs_from_history(h3.truncated(nf), cfg, nf), NEW(h3.truncated(nf), cfg, nf)
check("a now with a fraction of a second: only the SOC age differs, by less than one second (exact vs truncated)",
      [x[0] for x, y in zip(as_tuple(a), as_tuple(b)) if x != y] == ["soc_age_s"] and 0 < b.soc_age_s - a.soc_age_s < 1.0)
check("a boolean SOC override now reads as no SOC (it used to be taken as 1 %)",
      legacy_inputs_from_history(h3.truncated(n3), cfg, n3, None, True).soc_pct is True and NEW(h3.truncated(n3), cfg, n3, None, True).soc_pct is None)
for label, call in (("a naive `now`", lambda: NEW(h3, cfg, datetime(2030, 6, 8, 21, 30))),
                    ("a forecast source name that is not a string", lambda: NEW(h3.truncated(n3), cfg, n3, {7: {date(2030, 6, 8): 5.0}}))):
    try:
        call()
        check(f"{label} is refused loudly (ValueError), as the type hints always said", False)
    except ValueError:
        check(f"{label} is refused loudly (ValueError), as the type hints always said", True)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in intelligence V1.1 migration:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll intelligence V1.1 migration checks passed")
