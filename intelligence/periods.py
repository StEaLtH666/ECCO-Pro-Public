"""Local wall-clock periods across UK clock changes (DST): the ONE place Intelligence measures a window's real length.

A tariff window or an overnight period is written in local wall-clock minutes ("00:30 to 05:30"). Its endpoints are mapped
to UTC per calendar date by `timeutil.local_wall` (the engine's own mapping), so the energy over the window is right on
every night; its *length* is not constant:

    25 Oct 2026 (autumn, clocks go back)    the local day lasts 25 h; 00:30-05:30 lasts 6 h; 22:00 (24th) - 06:00 lasts 9 h
    28 Mar 2027 (spring, clocks go forward) the local day lasts 23 h; 00:30-05:30 lasts 4 h; 22:00 (27th) - 06:00 lasts 7 h

`period_profile` states the nominal and actual hours, their ratio (`factor`), which change (if any) the window spans, and
whether each endpoint falls in a repeated (AMBIGUOUS) or missing (NONEXISTENT) local hour. It refuses a window with no real
length (actual_h <= 0, the spring gap, for example 01:00-02:00 on 28 Mar 2027) and a window lying wholly inside the gap.
`clock_changes` lists the changes in a range. Pure functions of their arguments: no clock read, no I/O.

Callers decide what a changed period means (decision I-D9, intelligence/site_decisions.py); this module only measures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .timeutil import UTC, local_wall, zone

DEFAULT_TZ = "Europe/London"

NONE = "NONE"
AUTUMN_BACK = "AUTUMN_BACK"
SPRING_FORWARD = "SPRING_FORWARD"
CHANGE_KINDS = (NONE, AUTUMN_BACK, SPRING_FORWARD)

OK = "OK"
AMBIGUOUS = "AMBIGUOUS"            # the local time occurs twice (the repeated hour after the clocks go back)
NONEXISTENT = "NONEXISTENT"        # the local time never occurs (the hour skipped when the clocks go forward)
BOUNDARY_KINDS = (OK, AMBIGUOUS, NONEXISTENT)

_EPS_H = 1e-9


@dataclass(frozen=True)
class PeriodProfile:
    """One local wall-clock window on one date, measured in elapsed time."""
    day: date
    start_min: int
    end_min: int
    tz: str
    start_utc: datetime
    end_utc: datetime
    nominal_h: float
    actual_h: float
    factor: float                   # actual_h / nominal_h (1.0 on an ordinary day)
    change_kind: str                # NONE | AUTUMN_BACK | SPRING_FORWARD
    start_boundary: str             # OK | AMBIGUOUS | NONEXISTENT
    end_boundary: str

    @property
    def changed(self) -> bool:
        return self.change_kind != NONE

    @property
    def boundary_in_changed_hour(self) -> bool:
        return self.start_boundary != OK or self.end_boundary != OK

    def to_dict(self) -> dict:
        return {"day": self.day.isoformat(), "start_min": self.start_min, "end_min": self.end_min, "tz": self.tz,
                "start_utc": self.start_utc.isoformat(), "end_utc": self.end_utc.isoformat(),
                "nominal_h": self.nominal_h, "actual_h": self.actual_h, "factor": self.factor,
                "change_kind": self.change_kind, "start_boundary": self.start_boundary, "end_boundary": self.end_boundary}


@dataclass(frozen=True)
class ClockChange:
    """One change of the zone's UTC offset."""
    at_utc: datetime                # the first instant with the new offset
    kind: str                       # AUTUMN_BACK | SPRING_FORWARD
    local_day: date                 # the local date on which it happens
    delta_h: float                  # new offset minus old offset, in hours (-1.0 in autumn, +1.0 in spring for the UK)

    def to_dict(self) -> dict:
        return {"at_utc": self.at_utc.isoformat(), "kind": self.kind, "local_day": self.local_day.isoformat(),
                "delta_h": self.delta_h}


def _tz(tz: str | ZoneInfo) -> ZoneInfo:
    if isinstance(tz, ZoneInfo):
        return tz
    if not isinstance(tz, str) or not tz:
        raise ValueError(f"tz must be a zone name, got {tz!r}")
    try:
        return zone(tz)
    except (ZoneInfoNotFoundError, KeyError, OSError, ValueError) as exc:
        raise ValueError(f"unknown time zone {tz!r}") from exc


def _wall(day: date, minutes: int) -> datetime:
    extra_days, rem = divmod(minutes, 1440)
    d = day + timedelta(days=extra_days)
    return datetime(d.year, d.month, d.day, rem // 60, rem % 60)


def boundary_kind(day: date, minutes: int, tz: str | ZoneInfo = DEFAULT_TZ) -> str:
    """OK, AMBIGUOUS (the wall time occurs twice) or NONEXISTENT (it never occurs) for `minutes` after local midnight."""
    z = _tz(tz)
    naive = _wall(day, minutes)
    first, second = naive.replace(tzinfo=z, fold=0), naive.replace(tzinfo=z, fold=1)
    if first.utcoffset() == second.utcoffset():
        return OK
    back = first.astimezone(UTC).astimezone(z).replace(tzinfo=None)
    return AMBIGUOUS if back == naive else NONEXISTENT


def period_profile(day: date, start_min: int, end_min: int, tz: str | ZoneInfo = DEFAULT_TZ) -> PeriodProfile:
    """Measure the window [start_min, end_min) after local midnight of `day` (end_min may exceed 1440: the next day).

    `change_kind` says which clock change the window spans in elapsed time: from its length (longer = AUTUMN_BACK, shorter
    = SPRING_FORWARD) or, when the length is unchanged (an endpoint in the skipped hour), from a change strictly inside
    (start_utc, end_utc). `changed` is therefore true whenever the window crosses a change.

    Raises ValueError (and only ValueError) when the window is malformed or out of range, the zone is unknown, it has no
    real length (actual_h <= 0: the spring gap) or both endpoints lie in the skipped hour (a window wholly inside the gap)."""
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError(f"day must be a date, got {day!r}")
    for name, v in (("start_min", start_min), ("end_min", end_min)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{name} must be an int number of minutes, got {v!r}")
    if not end_min > start_min:
        raise ValueError("the window must end after it starts (end_min may exceed 1440)")
    z = _tz(tz)
    tz_name = tz if isinstance(tz, str) else str(z.key)
    try:
        t0, t1 = local_wall(day, start_min, z), local_wall(day, end_min, z)
        sb, eb = boundary_kind(day, start_min, z), boundary_kind(day, end_min, z)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"the window {start_min}-{end_min} min on {day.isoformat()} is out of range: {exc}") from None
    nominal = (end_min - start_min) / 60.0
    actual = (t1 - t0).total_seconds() / 3600.0
    if actual <= 0.0:
        raise ValueError(f"the window {start_min}-{end_min} min on {day.isoformat()} has no real length ({actual:g} h): "
                         "it lies in the hour skipped when the clocks go forward")
    if sb == NONEXISTENT and eb == NONEXISTENT:
        raise ValueError(f"the window {start_min}-{end_min} min on {day.isoformat()} lies wholly inside the skipped hour")
    change = NONE
    if actual > nominal + _EPS_H:
        change = AUTUMN_BACK
    elif actual < nominal - _EPS_H:
        change = SPRING_FORWARD
    else:
        inside = [c for c in clock_changes(t0, t1, z) if t0 < c.at_utc]
        if inside:
            change = inside[0].kind
    return PeriodProfile(day, start_min, end_min, tz_name, t0, t1, nominal, actual, actual / nominal, change, sb, eb)


def _as_utc(x: date | datetime, z: ZoneInfo, what: str) -> datetime:
    if isinstance(x, datetime):
        if x.tzinfo is None:
            raise ValueError(f"{what} must be timezone-aware")
        return x.astimezone(UTC)
    if isinstance(x, date):
        return local_wall(x, 0, z)
    raise ValueError(f"{what} must be a date or an aware datetime, got {x!r}")


def clock_changes(start: date | datetime, end: date | datetime, tz: str | ZoneInfo = DEFAULT_TZ) -> tuple[ClockChange, ...]:
    """Every UTC-offset change at an instant t with start <= t < end (a date means that date's local midnight)."""
    z = _tz(tz)
    a, b = _as_utc(start, z, "start"), _as_utc(end, z, "end")
    if b <= a:
        return ()
    out: list[ClockChange] = []
    step = timedelta(hours=1)
    t = a.replace(minute=0, second=0, microsecond=0) - step      # one hour early, so a change exactly at `start` is seen
    prev_off = t.astimezone(z).utcoffset()
    while t < b:
        nxt = t + step
        off = nxt.astimezone(z).utcoffset()
        if off != prev_off:
            lo, hi = t, nxt                      # offset(lo) == prev_off, offset(hi) == off: find the first new instant
            while (hi - lo) > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(z).utcoffset() == prev_off:
                    lo = mid
                else:
                    hi = mid
            at = hi.replace(microsecond=0)
            if a <= at < b:
                delta = (off - prev_off).total_seconds() / 3600.0
                out.append(ClockChange(at, AUTUMN_BACK if delta < 0 else SPRING_FORWARD, at.astimezone(z).date(), delta))
            prev_off = off
        t = nxt
    return tuple(out)


def window_crosses_change(t0: datetime, t1: datetime, tz: str | ZoneInfo = DEFAULT_TZ) -> bool:
    """True when the elapsed interval [t0, t1) contains a clock change (both ends aware)."""
    return bool(clock_changes(t0, t1, tz))
