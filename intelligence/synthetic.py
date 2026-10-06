"""Deterministic synthetic households for tests and demos (seeded, stdlib only).

Not a model of reality: just a controllable generator so each behaviour the
engine must handle (a weekend effect, a heavy night, a poor-PV day, gaps, DST,
a cold start) can be created on purpose and asserted on."""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from .config import SiteConfig
from .history import HourRecord, History
from .timeutil import HOUR, UTC, day_bounds, sun_times, ts, utc_from_ts, zone


def _generic_profile() -> list[float]:
    """kWh per local hour: a generic weekday load shape built from a stated formula (night base load, a morning bump around
    07:30, a daytime plateau 09:00-17:00 and an evening peak around 19:00), scaled to about 30 kWh/day - a deliberately heavy
    synthetic house so the examples exercise a battery that is small relative to the load. Not derived from any measured
    household."""
    raw = [0.7 + 0.6 * math.exp(-((h + 0.5 - 7.5) / 1.2) ** 2) + (0.45 if 9 <= h <= 16 else 0.0)
           + 0.95 * math.exp(-((h + 0.5 - 19.0) / 2.2) ** 2) for h in range(24)]
    s = sum(raw)
    return [round(x * 30.0 / s, 3) for x in raw]


DEFAULT_PROFILE = _generic_profile()


def make_history(start_day: date, days: int, cfg: SiteConfig, seed: int = 1, level: float = 1.0,
                 profile: list[float] | None = None, hour_noise: float = 0.10, day_sigma: float = 0.10,
                 pv_peak_kw: float = 6.0, clearness: float | None = None, weekend_mult: float = 1.0,
                 drop_hours: set[int] | None = None, load_overrides: dict[int, float] | None = None,
                 pv_scale_by_day: dict[date, float] | None = None, soc_noise: float = 0.0,
                 with_soc: bool = True) -> History:
    """Hourly History for `days` local days from `start_day`.

    drop_hours: epoch hour-starts to omit entirely (data gaps).
    load_overrides: epoch hour-start -> kWh replacing the generated load (one-off loads, heavy nights).
    pv_scale_by_day: local date -> multiplier on that day's PV (poor / excellent PV days)."""
    rnd = random.Random(seed)
    tz = zone(cfg.tz)
    prof = profile or DEFAULT_PROFILE
    recs: dict[int, HourRecord] = {}
    soc = 80.0
    eta = math.sqrt(cfg.round_trip_efficiency)
    cap = cfg.battery_capacity_kwh
    for k in range(days):
        day = start_day + timedelta(days=k)
        t0, t1 = day_bounds(day, tz)
        day_level = level * (1.0 + day_sigma * rnd.gauss(0, 1)) * (weekend_mult if day.weekday() >= 5 else 1.0)
        sr, ss = sun_times(day, cfg.latitude, cfg.longitude)
        clear = clearness if clearness is not None else min(1.0, max(0.15, rnd.betavariate(2.2, 1.6)))
        clear *= (pv_scale_by_day or {}).get(day, 1.0)
        s = ts(t0)
        while s < ts(t1):
            h0 = utc_from_ts(s)
            lh = h0.astimezone(tz).hour
            load = max(0.05, prof[lh] * day_level * (1.0 + hour_noise * rnd.gauss(0, 1)))
            if load_overrides and s in load_overrides:
                load = load_overrides[s]
            pv = 0.0
            if sr and ss and sr <= h0 + timedelta(minutes=30) <= ss:
                x = ((h0 + timedelta(minutes=30)) - sr).total_seconds() / (ss - sr).total_seconds()
                pv = pv_peak_kw * (math.sin(math.pi * x) ** 1.3) * clear
            if not (drop_hours and s in drop_hours):
                r = HourRecord(start=s)
                r.e["load"] = load
                r.e["pv"] = pv
                r.load_w_mean = load * 1000.0
                r.pv_w_mean = pv * 1000.0
                recs[s] = r
            if with_soc:
                in_window = cfg.cheap_window_start_min <= (h0.astimezone(tz).hour * 60 + h0.astimezone(tz).minute) < cfg.cheap_window_end_min
                if in_window:
                    soc = min(cfg.max_soc_pct, soc + 30.0)
                net = pv - load
                soc += (net * eta if net >= 0 else net / eta) / cap * 100.0
                soc = max(0.0, min(cfg.max_soc_pct, soc))
                if s in recs:
                    recs[s].soc_mean = max(0.0, min(100.0, soc + soc_noise * rnd.gauss(0, 1)))
            s += HOUR
    return History(recs.values())


def solcast_like(history: History, cfg: SiteConfig, over_factor: float = 1.8, seed: int = 7,
                 noise: float = 0.15) -> dict[date, float]:
    """A day-ahead PV forecast series that systematically over-forecasts by `over_factor` (like a biased forecast source
    series in autumn), for exercising the ratio learner."""
    rnd = random.Random(seed)
    tz = zone(cfg.tz)
    first, last = history.first_last()
    out: dict[date, float] = {}
    d = first.astimezone(tz).date()
    while d <= last.astimezone(tz).date():
        t0, t1 = day_bounds(d, tz)
        a = history.energy_scaled("pv", t0, t1, 0.9)
        if a is not None:
            out[d] = max(1.0, a * over_factor * (1.0 + noise * rnd.gauss(0, 1)))
        d += timedelta(days=1)
    return out
