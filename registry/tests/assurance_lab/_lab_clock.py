"""Assurance lab V0: Europe/London civil time without a tz database, UTC-true timeline helpers and the Home Assistant sim
LOCAL patch (test-only helper: no network, no Home Assistant, no hardware; writes nothing; reads nothing except the tz
database that zoneinfo_available() probes through the standard zoneinfo module).

The lab's true timeline is the UTC epoch in SECONDS (int, or float for sub-second instants). Everything local is derived from it
with the EU rule in force since 1996: British Summer Time (UTC+1) from 01:00 UTC on the last Sunday of March to 01:00 UTC on
the last Sunday of October, GMT (UTC+0) otherwise. The rule is computed here independently (calendar.monthrange) so that the
self-test can cross-check it against the two existing hand-coded oracles and, only when importable, zoneinfo.

PUBLIC API
  UTC                                   datetime.timezone.utc
  DST_FALL_2026_UTC   = 1792890000      2026-10-25T01:00:00Z (02:00 BST -> 01:00 GMT; local 01:00-01:59:59 happens twice)
  DST_SPRING_2027_UTC = 1806195600      2027-03-28T01:00:00Z (01:00 GMT -> 02:00 BST; local 01:00-01:59:59 never happens)
  bst_bounds_utc(year) -> (start_s, end_s)       [start, end) of BST in `year`, UTC epoch seconds
  london_offset_s(utc_s) -> int                  3600 inside BST, else 0 (utc_s int or finite float; bool rejected)
  is_dst(utc_s) -> bool
  local_kind(y, m, d, h=0, mi=0, s=0) -> str     'normal' | 'ambiguous' (repeated hour) | 'gap' (nonexistent wall time)
  class London(datetime.tzinfo); LONDON = London()
      utcoffset / dst / tzname of a NAIVE LOCAL wall time honouring `fold` with zoneinfo semantics:
        ambiguous: fold=0 -> first occurrence (BST, +01:00), fold=1 -> second occurrence (GMT, +00:00)
        gap:       fold=0 -> the offset BEFORE the transition (GMT), so 2027-03-28 01:30 -> 01:30Z = 02:30 BST;
                   fold=1 -> the offset after it (BST), so 01:30 -> 00:30Z = 00:30 GMT
      fromutc(dt) (used by datetime.fromtimestamp(ts, LONDON) and astimezone): the local wall time, fold=1 exactly for the
      second occurrence of a repeated wall time. utcoffset(None) / dst(None) / tzname(None) return None (as ZoneInfo does).
      Use the singleton LONDON: Python compares and subtracts aware datetimes as wall times only when they share the SAME
      tzinfo object (identity), exactly as with one ZoneInfo instance.
  utc_of_local(y, m, d, h=0, mi=0, s=0, fold=0) -> int   UTC epoch of a London wall time with the tzinfo's fold/gap semantics
                                                          (it never raises for a gap; use local_kind() to detect one)
  local_fields(utc_s) -> (y, m, d, h, mi, s, is_dst)     London wall-time fields (floor to the whole second)
  iso_utc(utc_s) -> 'YYYY-MM-DDTHH:MM:SSZ'               '.mmm' added when utc_s has a non-zero millisecond part
  iso_local(utc_s) -> 'YYYY-MM-DDTHH:MM:SS+01:00'        the explicit offset disambiguates the repeated hour
  parse_iso_utc(text) -> int                             strict inverse of iso_utc for whole seconds ('...Z' only)
  patched_ha_local(S)                                    context manager: S.LOCAL = LONDON inside, the previous object restored
                                                          on exit, also when the body raises (the exception propagates)
  zoneinfo_available() -> bool                           True iff zoneinfo.ZoneInfo('Europe/London') loads in this process
                                                          (the stdlib module and a tz database, e.g. the tzdata package on
                                                          Windows); never raises; probed once and cached per process. Every
                                                          suite's LAB-SUMMARY 'zoneinfo' field is this value
                                                          (_lab_trace.finish), and the zoneinfo cross-checks run only when it
                                                          is True (they are printed as skipped otherwise, never dropped
                                                          silently). Nothing else in this module depends on it.

MODEL ASSUMPTIONS
  - The EU rule above holds for every year handled (true since 1996; no future rule change is modelled).
  - Home Assistant resolves an input_datetime wall time with zoneinfo semantics (fold=0). How real Home Assistant treats a
    NONEXISTENT or AMBIGUOUS input_datetime value stays UNVERIFIED (no homeassistant package offline); this module only
    reproduces Python zoneinfo, which the HA sim then uses through `.timestamp()` / `datetime.fromtimestamp(ts, LOCAL)`.
  - Same-tzinfo aware arithmetic is wall-time arithmetic (Python semantics, identical to ZoneInfo): LONDON-aware
    00:30 BST + 2 h on 2026-10-25 is 02:30 GMT, i.e. 3 h of real time. The HA sim's `now() + timedelta(...)` inherits this.

SOURCE ANCHORS (text snippet -> line at writing)
  home-assistant/tests/_ha_script_sim.py  "LOCAL = timezone(timedelta(hours=1))"                         :32  (fixed UTC+1)
                                          "return datetime.fromtimestamp(ts, LOCAL).strftime("            :52  (local_str)
                                          "replace(tzinfo=LOCAL).timestamp()"                             :56  (parse_local)
                                          "return datetime.fromtimestamp(self.t, LOCAL)"                  :164 (World.now)
  home-assistant/tests/_ha_dump_sim.py    "datetime.fromtimestamp(float(v), S.LOCAL).isoformat()"         :90  (timestamp_local)
    The sim reads the module global LOCAL at call time, so patching S.LOCAL changes every one of these paths.
  registry/tests/_fbd1_harness.py         "def london_offset_s(utc_s: int) -> int:"                       :136 (oracle 1)
                                          "def utc_of_local(Y: int, M: int, D: int,"                      :141 (raises for a gap)
  tools/fbd1_soak/timeutil.py             "def local_to_utc(local: datetime, fold: int = 0) -> datetime:" :54  (oracle 2)
  firmware/ecco_clock_dongle_stage3_4_free_power.yaml  "timezone: Europe/London"                         :1692 (SNTP zone)

NOT MODELLED
  - Leap seconds, historical (pre-1996) or future UK rule changes, any zone other than Europe/London.
  - Real Home Assistant input_datetime behaviour in the gap / repeated hour (see MODEL ASSUMPTIONS).
  - The firmware's own ESPTime conversion (the firmware tiers install _fbd1_harness.WallClock, which uses oracle 1).
"""
from __future__ import annotations

import calendar
import math
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone, tzinfo

UTC = timezone.utc
_EPOCH_ORD = date(1970, 1, 1).toordinal()
_EPOCH_NAIVE = datetime(1970, 1, 1)
_ZERO = timedelta(0)
_HOUR = timedelta(hours=1)
_BOUNDS: dict[int, tuple[int, int]] = {}

DST_FALL_2026_UTC = 1792890000      # 2026-10-25T01:00:00Z
DST_SPRING_2027_UTC = 1806195600    # 2027-03-28T01:00:00Z


def _seconds(utc_s) -> int:
    """Floor of a finite int/float epoch; bool, None, NaN and other types raise (fail loud)."""
    if isinstance(utc_s, bool) or not isinstance(utc_s, (int, float)):
        raise TypeError(f"epoch seconds must be int or float, got {type(utc_s).__name__}")
    if isinstance(utc_s, float) and not math.isfinite(utc_s):
        raise ValueError(f"epoch seconds must be finite, got {utc_s!r}")
    return int(math.floor(utc_s))


def _last_sunday_0100_utc(year: int, month: int) -> int:
    last = calendar.monthrange(year, month)[1]
    day = last - (calendar.weekday(year, month, last) + 1) % 7      # weekday(): Monday 0 .. Sunday 6
    return (date(year, month, day).toordinal() - _EPOCH_ORD) * 86400 + 3600


def bst_bounds_utc(year: int) -> tuple[int, int]:
    """[start, end) of British Summer Time in `year` as UTC epoch seconds."""
    b = _BOUNDS.get(year)
    if b is None:
        b = _BOUNDS[year] = (_last_sunday_0100_utc(year, 3), _last_sunday_0100_utc(year, 10))
    return b


def london_offset_s(utc_s) -> int:
    """3600 while British Summer Time is in force at the UTC instant `utc_s`, else 0."""
    u = _seconds(utc_s)
    a, b = bst_bounds_utc(date.fromordinal(_EPOCH_ORD + u // 86400).year)
    return 3600 if a <= u < b else 0


def is_dst(utc_s) -> bool:
    return london_offset_s(utc_s) == 3600


def _local_s(y: int, m: int, d: int, h: int, mi: int, s: int) -> int:
    """Seconds since 1970-01-01 00:00 of a naive wall time (validated by the datetime constructor)."""
    datetime(y, m, d, h, mi, s)
    return (date(y, m, d).toordinal() - _EPOCH_ORD) * 86400 + h * 3600 + mi * 60 + s


def _readings(local_s: int) -> tuple[bool, bool]:
    """(the BST reading exists, the GMT reading exists) for a naive wall time."""
    return london_offset_s(local_s - 3600) == 3600, london_offset_s(local_s) == 0


def _kind(local_s: int) -> str:
    bst_ok, gmt_ok = _readings(local_s)
    return "ambiguous" if (bst_ok and gmt_ok) else ("normal" if (bst_ok or gmt_ok) else "gap")


def local_kind(y: int, m: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> str:
    """'normal', 'ambiguous' (the repeated autumn hour) or 'gap' (the skipped spring hour) for a London wall time."""
    return _kind(_local_s(y, m, d, h, mi, s))


def _offset_for_local(local_s: int, fold: int) -> int:
    bst_ok, gmt_ok = _readings(local_s)
    if bst_ok and gmt_ok:
        return 0 if fold else 3600          # repeated hour: fold=0 first (BST) occurrence, fold=1 second (GMT)
    if bst_ok:
        return 3600
    if gmt_ok:
        return 0
    # Gap. London's only gap is the spring change GMT -> BST: fold=0 takes the offset before it (GMT), fold=1 the one after.
    return 3600 if fold else 0


class London(tzinfo):
    """Europe/London as a stdlib tzinfo with ZoneInfo fold / gap semantics (see the module docstring). Use LONDON."""

    def _off(self, dt: datetime) -> int:
        return _offset_for_local(_local_s(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second), dt.fold)

    def utcoffset(self, dt):
        if dt is None:
            return None
        return _HOUR if self._off(dt) else _ZERO

    def dst(self, dt):
        if dt is None:
            return None
        return _HOUR if self._off(dt) else _ZERO

    def tzname(self, dt):
        if dt is None:
            return None
        return "BST" if self._off(dt) else "GMT"

    def fromutc(self, dt: datetime) -> datetime:
        if not isinstance(dt, datetime):
            raise TypeError("fromutc() requires a datetime argument")
        if dt.tzinfo is not self:
            raise ValueError("fromutc: dt.tzinfo is not self")
        u = _local_s(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)     # the UTC fields as an epoch
        off = london_offset_s(u)
        fold = 1 if (off == 0 and _kind(u) == "ambiguous") else 0                   # second occurrence of a repeated time
        return (dt.replace(tzinfo=None) + timedelta(seconds=off)).replace(tzinfo=self, fold=fold)

    def __repr__(self) -> str:
        return "London()"


LONDON = London()


def utc_of_local(y: int, m: int, d: int, h: int = 0, mi: int = 0, s: int = 0, fold: int = 0) -> int:
    """UTC epoch seconds of the London wall time y-m-d h:mi:s with the tzinfo's fold / gap semantics."""
    if fold not in (0, 1):
        raise ValueError(f"fold must be 0 or 1, got {fold!r}")
    loc = _local_s(y, m, d, h, mi, s)
    return loc - _offset_for_local(loc, fold)


def local_fields(utc_s) -> tuple[int, int, int, int, int, int, bool]:
    """(year, month, day, hour, minute, second, is_dst) of the London wall time at `utc_s` (floored to the second)."""
    u = _seconds(utc_s)
    off = london_offset_s(u)
    t = _EPOCH_NAIVE + timedelta(seconds=u + off)
    return (t.year, t.month, t.day, t.hour, t.minute, t.second, off == 3600)


def _split_ms(utc_s) -> tuple[int, int]:
    _seconds(utc_s)                                   # type / finiteness check
    ms = int(utc_s) * 1000 if isinstance(utc_s, int) else int(round(utc_s * 1000))
    return divmod(ms, 1000)


def iso_utc(utc_s) -> str:
    sec, ms = _split_ms(utc_s)
    t = _EPOCH_NAIVE + timedelta(seconds=sec)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + (f".{ms:03d}" if ms else "") + "Z"


def iso_local(utc_s) -> str:
    sec, ms = _split_ms(utc_s)
    off = london_offset_s(sec)
    t = _EPOCH_NAIVE + timedelta(seconds=sec + off)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + (f".{ms:03d}" if ms else "") + ("+01:00" if off else "+00:00")


_ISO_Z = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")


def parse_iso_utc(text: str) -> int:
    """'YYYY-MM-DDTHH:MM:SSZ' -> UTC epoch seconds. Anything else raises ValueError."""
    m = _ISO_Z.match(text) if isinstance(text, str) else None
    if not m:
        raise ValueError(f"not a strict ISO UTC timestamp 'YYYY-MM-DDTHH:MM:SSZ': {text!r}")
    return _local_s(*(int(g) for g in m.groups()))


_ZONEINFO_OK: bool | None = None


def zoneinfo_available() -> bool:
    """True iff zoneinfo.ZoneInfo('Europe/London') loads in this process; never raises; probed once, then cached.

    An environment probe, not a check: any failure to import zoneinfo or to load the key (ImportError,
    ZoneInfoNotFoundError, a broken tz file) means "not available"; the callers then print their zoneinfo cross-checks as
    skipped and LAB-SUMMARY reports "zoneinfo": false (never a silent pass)."""
    global _ZONEINFO_OK
    if _ZONEINFO_OK is None:
        try:
            import zoneinfo
            zoneinfo.ZoneInfo("Europe/London")
            ok = True
        except Exception:    # noqa: BLE001 - a probe: every failure means "not available" (reported, never a pass)
            ok = False
        _ZONEINFO_OK = ok
    return _ZONEINFO_OK


@contextmanager
def patched_ha_local(S):
    """Temporarily make the HA sim module `S` (home-assistant/tests/_ha_script_sim) render Europe/London: S.LOCAL = LONDON.
    The previous object is restored on exit, also when the body raises (the exception is not swallowed)."""
    prev = S.LOCAL                      # AttributeError for a module without LOCAL: fail loud
    S.LOCAL = LONDON
    try:
        yield LONDON
    finally:
        S.LOCAL = prev
