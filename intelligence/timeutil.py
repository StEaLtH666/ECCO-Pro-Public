"""Local-time handling. All storage is UTC; all human-facing windows are local
wall-clock and are converted per calendar date, so DST days (23 / 25 hours)
need no special casing in callers."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
HOUR = 3600


def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def utc_from_ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def local_wall(day: date, minutes: int, tz: ZoneInfo) -> datetime:
    """Local wall-clock `minutes` after local midnight of `day`, as aware UTC.

    minutes may exceed 1440 (next day) or be negative. Wall-clock arithmetic
    is done on the date, not on elapsed time, so a window that spans a DST
    change keeps its wall-clock endpoints."""
    extra_days, rem = divmod(minutes, 1440)
    d = day + timedelta(days=extra_days)
    naive = datetime(d.year, d.month, d.day, rem // 60, rem % 60)
    return naive.replace(tzinfo=tz).astimezone(UTC)


def local_date(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def local_hour(dt: datetime, tz: ZoneInfo) -> int:
    return dt.astimezone(tz).hour


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC instants of local midnight at the start and end of `day` (23/24/25 h apart)."""
    return local_wall(day, 0, tz), local_wall(day, 1440, tz)


def sun_times(day: date, lat: float, lon: float) -> tuple[datetime | None, datetime | None]:
    """Sunrise and sunset (aware UTC) for the date at lat/lon, NOAA algorithm.

    Accurate to roughly a minute at UK latitudes. Returns (None, None) in
    polar day/night."""
    n = day.toordinal() - date(2000, 1, 1).toordinal() + 0.5  # days since J2000 at 12:00 UT of `day`
    jd_cycle = n - lon / 360.0
    mean_anom = math.radians((357.5291 + 0.98560028 * jd_cycle) % 360)
    center = 1.9148 * math.sin(mean_anom) + 0.0200 * math.sin(2 * mean_anom) + 0.0003 * math.sin(3 * mean_anom)
    ecl_lon = math.radians((math.degrees(mean_anom) + center + 180 + 102.9372) % 360)
    transit = 0.0053 * math.sin(mean_anom) - 0.0069 * math.sin(2 * ecl_lon)  # days offset from mean noon
    decl = math.asin(math.sin(ecl_lon) * math.sin(math.radians(23.44)))
    cos_h = (math.sin(math.radians(-0.833)) - math.sin(math.radians(lat)) * math.sin(decl)) / (
        math.cos(math.radians(lat)) * math.cos(decl)
    )
    if cos_h > 1 or cos_h < -1:
        return None, None
    hour_angle_days = math.degrees(math.acos(cos_h)) / 360.0
    noon_utc = datetime(day.year, day.month, day.day, 12, tzinfo=UTC) - timedelta(days=lon / 360.0 - transit)
    return noon_utc - timedelta(days=hour_angle_days), noon_utc + timedelta(days=hour_angle_days)


def overlap_seconds(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    lo = max(a0, b0)
    hi = min(a1, b1)
    return max(0.0, (hi - lo).total_seconds())
