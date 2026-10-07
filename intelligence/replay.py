"""Replay the engine at a past instant using only what was known then (offline demos, backtests, tests)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .advisor import LiveInputs, TariffInfo, default_cheap_windows
from .config import SiteConfig
from .engine import IntelligenceEngine
from .history import History
from .inputs import history_snapshot, live_inputs_from_snapshot
from .timeutil import zone


def inputs_from_history(history: History, cfg: SiteConfig, now: datetime,
                        forecasts: dict[str, dict[date, float]] | None = None,
                        soc_override: float | None = None) -> LiveInputs:
    """Build LiveInputs for `now` from a (truncated) history: SOC and powers from the last complete hour,
    PV forecasts from the issue-time series for today and tomorrow (tomorrow's value is only the
    pre-dawn issue of that day, which a real run would also have by the evening).

    Routed through the state model: the history becomes an ecco_core Snapshot (inputs.history_snapshot) and the
    snapshot becomes LiveInputs (inputs.live_inputs_from_snapshot), the same single path any live source would use."""
    return live_inputs_from_snapshot(history_snapshot(history, cfg, now, forecasts, soc_override),
                                     tariff=TariffInfo(default_cheap_windows(cfg, now)))


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
