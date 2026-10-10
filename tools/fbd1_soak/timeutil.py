"""Timezone-aware time handling for the FB-D1 soak analyser (stdlib only, no tz database needed).

Every instant inside the analyser is an aware UTC datetime. Home Assistant exports carry UTC (or an explicit offset); the
dongle's own strings (NTP Time, Inverter Time, Last Configuration Update, ESPHome log clocks) are Europe/London wall time,
because the firmware's SNTP component runs with `timezone: Europe/London`.

Europe/London is hand-coded with the EU rule in force since 1996 (the same approach as registry/tests/_fbd1_harness.py):
BST (UTC+1) from 01:00 UTC on the last Sunday of March to 01:00 UTC on the last Sunday of October, GMT (UTC+0) otherwise.
A local wall time in the spring-forward gap does not exist; one in the autumn fall-back hour is ambiguous and resolves to
the first (BST) occurrence unless `fold=1` asks for the second.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
_BST = timedelta(hours=1)
_GMT = timedelta(0)


class TimeParseError(ValueError):
    """A timestamp could not be parsed or does not exist."""


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def bst_bounds_utc(year: int) -> tuple[datetime, datetime]:
    """[start, end) of British Summer Time in `year`, as aware UTC instants."""
    a = _last_sunday(year, 3)
    b = _last_sunday(year, 10)
    return (datetime(a.year, a.month, a.day, 1, tzinfo=UTC), datetime(b.year, b.month, b.day, 1, tzinfo=UTC))


def london_offset(t_utc: datetime) -> timedelta:
    a, b = bst_bounds_utc(t_utc.year)
    return _BST if a <= t_utc < b else _GMT


def to_local(t_utc: datetime) -> datetime:
    """Naive Europe/London wall time of an aware instant."""
    t = t_utc.astimezone(UTC)
    return (t + london_offset(t)).replace(tzinfo=None)


def zone_abbr(t_utc: datetime) -> str:
    return "BST" if london_offset(t_utc.astimezone(UTC)) == _BST else "GMT"


def local_to_utc(local: datetime, fold: int = 0) -> datetime:
    """Aware UTC instant of a naive Europe/London wall time. Raises TimeParseError for a non-existent wall time."""
    naive = local.replace(tzinfo=None)
    cands = []
    for off in (_BST, _GMT):
        u = (naive - off).replace(tzinfo=UTC)
        if london_offset(u) == off:
            cands.append(u)
    if not cands:
        raise TimeParseError(f"{naive.isoformat(sep=' ')} does not exist in Europe/London (spring-forward gap)")
    cands.sort()
    return cands[-1] if (fold and len(cands) > 1) else cands[0]


def is_ambiguous_local(local: datetime) -> bool:
    naive = local.replace(tzinfo=None)
    return sum(1 for off in (_BST, _GMT) if london_offset((naive - off).replace(tzinfo=UTC)) == off) > 1


_ISO = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?\s*(Z|z|UTC|[+-]\d{2}:?\d{2})?\s*$")


def parse_ts(value, *, naive_is_local: bool = True) -> datetime:
    """Parse an export timestamp into an aware UTC datetime.

    Accepts ISO 8601 (`T` or space separator, optional fraction, `Z` / `UTC` / `+HH:MM` / `+HHMM`), and numeric epoch
    seconds (int / float / numeric string; values above 1e11 are taken as milliseconds). A naive ISO string is Europe/London
    wall time when `naive_is_local` (the dongle's own strings), else UTC."""
    if isinstance(value, bool) or value is None:
        raise TimeParseError(f"not a timestamp: {value!r}")
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    s = str(value).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return _from_epoch(float(s))
    m = _ISO.match(s)
    if not m:
        raise TimeParseError(f"unrecognised timestamp {s!r}")
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    try:
        micro = int((frac or "0")[:6].ljust(6, "0"))
        naive = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0), micro)
    except ValueError as exc:
        raise TimeParseError(f"invalid timestamp {s!r}: {exc}") from exc
    if tz is None:
        return local_to_utc(naive) if naive_is_local else naive.replace(tzinfo=UTC)
    if tz in ("Z", "z", "UTC"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if tz[0] == "+" else -1
    digits = tz[1:].replace(":", "")
    off = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return (naive - sign * off).replace(tzinfo=UTC)


def parse_local_near(value: str, near: datetime) -> datetime:
    """A naive Europe/London wall-time string (the dongle's NTP Time / Last ... Update) resolved against a nearby aware
    instant: in the autumn fall-back hour the wall time occurs twice, and the occurrence closer to `near` is the right one."""
    t0 = parse_ts(value, naive_is_local=True)
    if not is_naive_iso(value):
        return t0
    m = _ISO.match(value)
    y, mo, d, h, mi, sec, frac, _tz = m.groups()
    naive = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0), int((frac or "0")[:6].ljust(6, "0")))
    if not is_ambiguous_local(naive):
        return t0
    t1 = local_to_utc(naive, fold=1)
    return t0 if abs((t0 - near).total_seconds()) <= abs((t1 - near).total_seconds()) else t1


def is_naive_iso(value) -> bool:
    """True for an ISO date-time string that carries no UTC offset."""
    if not isinstance(value, str):
        return False
    m = _ISO.match(value)
    return bool(m) and m.group(8) is None


def _from_epoch(x: float) -> datetime:
    if x != x or x in (float("inf"), float("-inf")):
        raise TimeParseError("epoch is not finite")
    if abs(x) > 1e11:
        x /= 1000.0
    return datetime.fromtimestamp(x, tz=UTC)


def iso_utc(t: datetime | None) -> str | None:
    if t is None:
        return None
    t = t.astimezone(UTC)
    frac = f".{t.microsecond // 1000:03d}" if t.microsecond else ""
    return t.strftime("%Y-%m-%dT%H:%M:%S") + frac + "Z"


def fmt_local(t: datetime | None, seconds: bool = True) -> str | None:
    """`2026-10-05 00:03:12 BST`."""
    if t is None:
        return None
    lt = to_local(t)
    return lt.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M") + " " + zone_abbr(t)


def stamp(t: datetime | None) -> dict | None:
    """The JSON form of one instant: both UTC and Europe/London wall time."""
    if t is None:
        return None
    return {"utc": iso_utc(t), "local": fmt_local(t)}


def local_seconds_of_day(t: datetime) -> int:
    lt = to_local(t)
    return lt.hour * 3600 + lt.minute * 60 + lt.second


def days_from_civil_local(local: datetime) -> int:
    """Days since 1970-01-01 of a naive local date (the firmware's ecco_rtc::days_from_civil of the NTP date)."""
    return (local.date() - date(1970, 1, 1)).days


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    s = int(round(seconds))
    neg = s < 0
    s = abs(s)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, r = divmod(r, 60)
    if d:
        out = f"{d}d {h:02d}h {m:02d}m"
    elif h:
        out = f"{h}h {m:02d}m {r:02d}s"
    elif m:
        out = f"{m}m {r:02d}s"
    else:
        out = f"{r}s"
    return ("-" if neg else "") + out
