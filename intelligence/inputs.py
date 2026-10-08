"""Intelligence's one reading of system state: an ecco_core Snapshot -> the engine's LiveInputs (SHADOW, read-only).

Everything the engine knows about "now" can pass through `live_inputs_from_snapshot`: it copies values (and the SOC's age)
out of an immutable snapshot and nothing else. It takes no freshness decision of its own (the engine applies its 15-minute
SOC rule; ecco_core.bridge gates readings the engine cannot judge, such as the inverter status) and it can write nothing
anywhere. Only `ecco_core.state`, the plain data model, is imported from ecco_core.

`history_snapshot` builds such a snapshot from the canonical hourly History for replays (tests, examples, backtests, the
CLI): the last complete hour's mean SOC and powers (DERIVED, observed at that hour's end), today's PV so far, the forecast
values known at `now` (raw, exactly as the provider gave them) and the replay's standing assumption that the inverter was
healthy. `replay.inputs_from_history` is this pair; it used to build LiveInputs inline, and for every finite input it
produces exactly what it used to (tests/test_intelligence_v11_migration.py). Two deliberate, tested differences:
a reading that is not a finite number (NaN, infinity, a boolean or a string; neither the canonical history nor a caller
should produce one) is dropped at the snapshot boundary instead of inside the engine. For NaN / infinity the advice is
unchanged and only the engine's "reading ... is ignored" note disappears; a boolean SOC used to be taken as 0 or 1 % and
a string SOC raised a TypeError, and both now read as "no SOC" (fail closed). The SOC's age is computed from exact
times, where the old code truncated `now` to whole seconds (a difference below one second, only when `now` carries a
fraction of a second). Two inputs that the type hints already excluded are now refused loudly instead of being half
handled: a naive `now` (which the engine would read in the machine's own timezone) and a forecast source name that is
not a string.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ecco_core.state import DERIVED, NORMALIZED, RAW, Observation, Snapshot

from .advisor import LiveInputs, TariffInfo
from .config import SiteConfig
from .explain import finite_number
from .history import History
from .timeutil import HOUR, day_bounds, ts, utc_from_ts, zone

_FORECAST_DAYS = ("today", "tomorrow", "remaining_today")


def _num(v: object) -> float | int | None:
    """The value itself when it is a finite number (type kept, so a report prints exactly as before), else None: the
    snapshot boundary refuses non-finite readings (the original stays in `raw`)."""
    return v if finite_number(v) else None


def forecast_observations(day_kind: str, raw: dict, observed_at: datetime | None = None) -> list[Observation]:
    """One RAW observation per forecast source, in the given order. The provider's value is kept as `raw` whatever it is
    (the engine's PV guards judge it); `value` is it only when it is a finite non-negative number."""
    if day_kind not in _FORECAST_DAYS:
        raise ValueError(day_kind)
    out = []
    for i, (src, v) in enumerate(raw.items()):
        if not isinstance(src, str):        # the key IS the source name: a string, so it survives the snapshot unchanged
            raise ValueError(f"forecast source names must be strings, got {src!r}")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", src)
        out.append(Observation(f"pv.forecast.{day_kind}.s{i:03d}_{safe}", float(v) if finite_number(v) and v >= 0 else None,
                               observed_at, f"forecast:{src}", RAW, raw=v))
    return out


def history_snapshot(history: History, cfg: SiteConfig, now: datetime,
                     forecasts: dict[str, dict[date, float]] | None = None, soc_override: float | None = None) -> Snapshot:
    """The replay's view of `now` from a (truncated) History, as a Snapshot. `now` must be timezone-aware: a naive time
    would silently be read in the machine's own timezone."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError(f"`now` must be a timezone-aware datetime, got {now!r}")
    tz = zone(cfg.tz)
    last_hour = ts(now) - (ts(now) % HOUR) - HOUR
    hour_end = utc_from_ts(last_hour + HOUR)
    rec = history.get(last_hour)
    obs: list[Observation] = []
    if soc_override is not None:
        obs.append(Observation("battery.soc", _num(soc_override), now, "caller_override", NORMALIZED, raw=soc_override,
                               quality=("caller_override",)))
    elif rec is not None:
        obs.append(Observation("battery.soc", _num(rec.soc_mean), hour_end, "history:hour_mean", DERIVED,
                               raw=rec.soc_mean, derived_from=("history.hourly",), quality=("hour_mean",)))
    if rec is not None:
        obs.append(Observation("house.power", _num(rec.load_w_mean), hour_end, "history:hour_mean", DERIVED,
                               raw=rec.load_w_mean, derived_from=("history.hourly",), quality=("hour_mean",)))
        obs.append(Observation("pv.power", _num(rec.pv_w_mean), hour_end, "history:hour_mean", DERIVED,
                               raw=rec.pv_w_mean, derived_from=("history.hourly",), quality=("hour_mean",)))
    today = now.astimezone(tz).date()
    f = forecasts or {}
    obs += forecast_observations("today", {s: v[today] for s, v in f.items() if today in v})
    obs += forecast_observations("tomorrow", {s: v[today + timedelta(days=1)] for s, v in f.items()
                                              if (today + timedelta(days=1)) in v})
    so_far, cov = history.energy("pv", day_bounds(today, tz)[0], now)
    if cov > 0.7:
        obs.append(Observation("pv.energy_today_so_far", _num(so_far / cov), hour_end, "history:energy", DERIVED,
                               raw=so_far / cov, derived_from=("history.hourly",), quality=(f"coverage_{cov:.2f}",)))
    obs.append(Observation("inverter.healthy", True, now, "replay_assumption", NORMALIZED, quality=("assumed",)))
    return Snapshot.of(now, obs)


def live_inputs_from_snapshot(snapshot: Snapshot, *, tariff: TariffInfo | None = None,
                              saving_sessions: list | None = None) -> LiveInputs:
    """Copy a snapshot into LiveInputs. SOC age = its observation's age (None when unknown); everything else is the value."""
    soc = snapshot.get("battery.soc")
    raw_pv = {k: {} for k in _FORECAST_DAYS}
    for day_kind in _FORECAST_DAYS:
        for sig in snapshot.signals(f"pv.forecast.{day_kind}."):
            o = snapshot.get(sig)
            if not o.source.startswith("forecast:"):
                raise ValueError(f"{sig}: forecast observations are built with forecast_observations() (source 'forecast:<name>')")
            raw_pv[day_kind][o.source[len("forecast:"):]] = o.raw
    return LiveInputs(
        now=snapshot.as_of, soc_pct=None if soc is None else soc.value,
        soc_age_s=None if soc is None else soc.age_s(snapshot.as_of),
        load_w=snapshot.value("house.power"), pv_w=snapshot.value("pv.power"),
        pv_raw_today=raw_pv["today"], pv_raw_tomorrow=raw_pv["tomorrow"], pv_raw_remaining_today=raw_pv["remaining_today"],
        pv_actual_so_far_kwh=snapshot.value("pv.energy_today_so_far"), ha_reserve_pct=snapshot.value("reserve.ha_minimum_soc"),
        tariff=tariff, saving_sessions=list(saving_sessions or []), inverter_ok=snapshot.value("inverter.healthy"))
