"""Replay the engine at a past instant using only what was known then (offline demos, backtests, tests)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .advisor import LiveInputs, TariffInfo, default_cheap_windows
from .config import SiteConfig
from .engine import IntelligenceEngine
from .history import History
from .timeutil import day_bounds, ts, utc_from_ts, zone, HOUR


def inputs_from_history(history: History, cfg: SiteConfig, now: datetime,
                        forecasts: dict[str, dict[date, float]] | None = None,
                        soc_override: float | None = None) -> LiveInputs:
    """Build LiveInputs for `now` from a (truncated) history: SOC and powers from the last complete hour,
    PV forecasts from the issue-time series for today and tomorrow (tomorrow's value is only the
    pre-dawn issue of that day, which a real run would also have by the evening)."""
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


def replay(history: History, cfg: SiteConfig, now: datetime, forecasts: dict[str, dict[date, float]] | None = None,
           soc_override: float | None = None, **overrides) -> dict:
    known = history.truncated(now)
    fc_known = {s: {d: v for d, v in tab.items() if d <= now.astimezone(zone(cfg.tz)).date()} for s, tab in (forecasts or {}).items()}
    eng = IntelligenceEngine(known, cfg, fc_known)
    inp = inputs_from_history(known, cfg, now, forecasts, soc_override)
    for k, v in overrides.items():
        setattr(inp, k, v)
    return eng.run(inp)


def campaign(history: History, cfg: SiteConfig, forecasts: dict[str, dict[date, float]], start: date, end: date,
             local_minute: int, scorecard, soc_by_day: dict[date, float] | None = None) -> int:
    """Issue one shadow run per local day at `local_minute` (e.g. 21:30) over [start, end], each using only the
    history known then, and record it in `scorecard`. Returns the number of runs. Scoring is a separate,
    later step (`scorecard.resolve(full_history, cfg, now)`), so nothing can leak."""
    from .timeutil import local_wall
    tz = zone(cfg.tz)
    n = 0
    d = start
    while d <= end:
        now = local_wall(d, local_minute, tz)
        soc = None if soc_by_day is None else soc_by_day.get(d)
        rep = replay(history, cfg, now, forecasts, soc_override=soc)
        scorecard.record_run(rep)
        n += 1
        d += timedelta(days=1)
    return n
