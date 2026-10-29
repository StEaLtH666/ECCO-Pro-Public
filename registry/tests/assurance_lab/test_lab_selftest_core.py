#!/usr/bin/env python3
"""Harness self-tests of the assurance lab core: _lab_clock (Europe/London tzinfo against the two hand-coded oracles and,
only when usable, zoneinfo; both transitions in detail; fromutc / fromtimestamp; the HA sim LOCAL patch) and _lab_trace
(canonical JSON and event-log digest, known-risk anchors, vocabularies, expectation operators, the replay DSL engine with a
dummy tier registered in-test, the drift rule, the strict corpus schema, record(), ddmin, the V0.1 suite output helpers
finish / failed_line / unsupported_line), the bytecode guard of every lab suite and tool (a static AST check with negative
controls), with the harness negative controls. Offline assurance lab V0 (test-only: no network, no Home Assistant, no
hardware; writes nothing; the corpus-file round trip uses tempfile.TemporaryDirectory outside the worktree).
Quick mode: 15-minute sweeps of 2026-01-01..2027-12-31 plus per-second sweeps of +-2 h around the four 2026/2027 changes.
ECCO_LAB_EXTENDED=1 (or --extended): additionally a 15-minute UTC sweep of 2000-01-01..2037-12-31.
zoneinfo: when _lab_clock.zoneinfo_available() is False (no tz database for Europe/London in this process) every zoneinfo
cross-check is printed as an '  info  SKIPPED (zoneinfo unavailable): <check>' line, never as a PASS, no PASS text names
zoneinfo, and LAB-SUMMARY reports "zoneinfo": false; the other oracles still run.
Process-state independent: no check assumes which lab tiers are registered (importing _lab_fw / _lab_rtc / _lab_ha registers
'firmware' / 'rtc' / 'coupled'), so the suite also passes in a process that imported them first (e.g. run in-process via runpy).
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # worktree root
for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
FAILURES: list[str] = []
PASSES: list[str] = []
PINS: list[str] = []            # held 'finding-reproduces:' checks (a self-test suite has none; counted apart from PASSES)
COUNTED: list[str] = []         # counted findings (none: harness self-tests reproduce no finding)
UNSUPPORTED_POINTS: list[str] = []    # one id per printed UNSUPPORTED line (none here)
BLOCKED: list[str] = []         # blocked scenarios (none: no scenario runs here)
# Phase-sensitivity registry (B4 change 7; HL-10): check-name prefix -> why that check's verdict depends on the lab's
# scheduler phase. The lab runs every firmware interval first at its startup_delay (else one period) after power-on with
# zero offset and reschedules it at due+T; the coupled tier samples the polled template sensors on the uptime grid and
# the RTC rig starts its intervals at the rig boot with a fixed phase. ESPHome 2026.8.2 runs each interval first at
# setup + startup_delay + a random offset in [0, min(T/2, 5 s)) and reschedules it at now+T (scheduler.cpp:105-110,
# 181-184, 540; interval.h; component.cpp:381-391). The tags were found by running every suite under an in-memory
# ESPHome-like phase patch (scratch only, not shipped; quick mode: 8 seeds of the full patch and 3 seeds of each of 3
# narrower variants; extended mode: 3 seeds) plus the audit's list of timing-bound checks. LAB-SUMMARY 'phase_sensitive'
# counts the EXECUTED checks (held or failed) whose name starts with a registered prefix (detected per run, never a
# literal); check_phase_registry() FAILS on a stale prefix (no executed check matches it), a prefix without a reason, or
# an unregistered PHASE_SENSITIVE_EXTENDED_ONLY entry (the prefixes whose checks run only in extended mode: they are
# required to match only there).
PHASE_SENSITIVE_TAGS: dict[str, str] = {}   # no check of this suite runs a scheduler
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []       # executed checks whose name starts with a tag


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (PINS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + PINS + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import ast  # noqa: E402
import calendar  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _fbd1_harness as F  # noqa: E402  (oracle 1: london_offset_s / utc_of_local / EspTime)
from fbd1_soak import timeutil as TU  # noqa: E402  (oracle 2)
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402

UTC = timezone.utc
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)
EPOCH_NAIVE = datetime(1970, 1, 1)
FALL, SPRING = C.DST_FALL_2026_UTC, C.DST_SPRING_2027_UTC
# zoneinfo is a cross-check oracle only when this process can load Europe/London (C.zoneinfo_available(), which is also the
# LAB-SUMMARY 'zoneinfo' value). Without it every zoneinfo check is printed as SKIPPED (never dropped silently) and no
# PASS text names zoneinfo.
if C.zoneinfo_available():
    import zoneinfo
    ZL = zoneinfo.ZoneInfo("Europe/London")
else:
    ZL = None
    print("  info  zoneinfo (Europe/London) is not usable in this process: every zoneinfo cross-check is SKIPPED and "
          "listed below; LAB-SUMMARY reports zoneinfo false")
ZONEINFO_SKIPPED: list[str] = []
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}; zoneinfo cross-check: {'on' if ZL else 'SKIPPED'}")


def zoneinfo_skipped(name: str) -> None:
    """A zoneinfo cross-check that cannot run here: an explicit info line (not a PASS, not counted)."""
    ZONEINFO_SKIPPED.append(name)
    print(f"  info  SKIPPED (zoneinfo unavailable): {name}")


def raises(exc_type, fn, *args, **kwargs) -> tuple[bool, str]:
    """(fn raised exc_type, its message). Any other exception propagates: a crash is a FAIL, never a pass."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return True, str(exc)
    return False, "no exception"


def _ep(*fields) -> int:
    return calendar.timegm(tuple(fields) + (0,) * (6 - len(fields)))


# =============================================================================================================================
# [1] clock constants and helpers
# =============================================================================================================================
def section_clock_basics() -> None:
    print("[1] clock constants, bounds, ISO helpers, input validation")
    check("DST_FALL_2026_UTC is 2026-10-25T01:00:00Z", FALL == _ep(2026, 10, 25, 1) and C.iso_utc(FALL) == "2026-10-25T01:00:00Z")
    check("DST_SPRING_2027_UTC is 2027-03-28T01:00:00Z",
          SPRING == _ep(2027, 3, 28, 1) and C.iso_utc(SPRING) == "2027-03-28T01:00:00Z")
    check("bst_bounds_utc(2026) = [2026-03-29T01Z, 2026-10-25T01Z), (2027) = [2027-03-28T01Z, 2027-10-31T01Z)",
          C.bst_bounds_utc(2026) == (_ep(2026, 3, 29, 1), FALL) and C.bst_bounds_utc(2027) == (SPRING, _ep(2027, 10, 31, 1)))
    tu_b = {y: tuple(int(x.timestamp()) for x in TU.bst_bounds_utc(y)) for y in range(2000, 2038)}
    check("bst_bounds_utc equals timeutil.bst_bounds_utc for every year 2000-2037",
          all(C.bst_bounds_utc(y) == tu_b[y] for y in tu_b))
    check("parse_iso_utc inverts iso_utc", C.parse_iso_utc("2026-10-25T01:00:00Z") == FALL
          and C.parse_iso_utc(C.iso_utc(SPRING + 59)) == SPRING + 59)
    bad = ["2026-10-25T01:00:00", "2026-10-25 01:00:00Z", "2026-10-25T01:00:00+00:00", "2026-13-01T00:00:00Z", FALL]
    check("parse_iso_utc rejects every non-strict form (no Z, space, offset, month 13, an int)",
          all(raises(ValueError, C.parse_iso_utc, b)[0] for b in bad))
    check("iso_utc renders milliseconds only when present", C.iso_utc(1.5) == "1970-01-01T00:00:01.500Z"
          and C.iso_utc(FALL + 0.0) == "2026-10-25T01:00:00Z")
    check("iso_local disambiguates the repeated hour by its offset",
          C.iso_local(FALL - 1800) == "2026-10-25T01:30:00+01:00" and C.iso_local(FALL + 1800) == "2026-10-25T01:30:00+00:00"
          and C.iso_local(SPRING) == "2027-03-28T02:00:00+01:00" and C.iso_local(SPRING - 1) == "2027-03-28T00:59:59+00:00")
    check("london_offset_s takes float epochs (floor) and flips exactly at 01:00Z",
          C.london_offset_s(FALL - 0.5) == 3600 and C.london_offset_s(FALL + 0.0) == 0 and C.london_offset_s(SPRING - 0.001) == 0
          and C.london_offset_s(SPRING) == 3600 and C.is_dst(FALL - 1) and not C.is_dst(FALL))
    check("london_offset_s fails loud on bool / None / str / NaN / inf",
          raises(TypeError, C.london_offset_s, True)[0] and raises(TypeError, C.london_offset_s, None)[0]
          and raises(TypeError, C.london_offset_s, "1")[0] and raises(ValueError, C.london_offset_s, float("nan"))[0]
          and raises(ValueError, C.london_offset_s, float("inf"))[0])
    check("utc_of_local rejects fold 2 and an invalid date", raises(ValueError, C.utc_of_local, 2026, 1, 1, fold=2)[0]
          and raises(ValueError, C.utc_of_local, 2026, 2, 30)[0])
    check("local_fields returns (y, m, d, h, mi, s, is_dst)",
          C.local_fields(FALL - 1800) == (2026, 10, 25, 1, 30, 0, True) and C.local_fields(FALL + 1800) == (2026, 10, 25, 1, 30, 0, False)
          and C.local_fields(SPRING + 0.9) == (2027, 3, 28, 2, 0, 0, True))


# =============================================================================================================================
# [2] sweeps against the oracles
# =============================================================================================================================
_TU_BOUNDS: dict[int, tuple[int, int]] = {}


def _second_occurrence(t: int) -> bool:
    """Independent of _lab_clock: [end, end + 1 h) of timeutil's BST bounds is the repeated (second-occurrence) hour."""
    y = (EPOCH_UTC + timedelta(seconds=t)).year
    if y not in _TU_BOUNDS:
        _TU_BOUNDS[y] = tuple(int(x.timestamp()) for x in TU.bst_bounds_utc(y))
    end = _TU_BOUNDS[y][1]
    return end <= t < end + 3600


def utc_sweep(start: int, end: int, step: int, offset_fn=C.london_offset_s) -> dict[str, list]:
    """Every property of the UTC -> local path at start, start + step, ... < end; {property: [failing t, ...]}."""
    bad: dict[str, list] = {k: [] for k in ("offset==fbd1", "offset==timeutil", "fromtimestamp==timeutil.to_local",
                                            "fields==local_fields", "utcoffset", "fold", "timestamp round trip",
                                            "utc_of_local(fold) round trip", "fbd1.utc_of_local (BST reading)",
                                            "timeutil.local_to_utc(fold)", "fbd1.EspTime fields", "iso_local==isoformat",
                                            "zoneinfo")}
    for t in range(start, end, step):
        u = EPOCH_UTC + timedelta(seconds=t)
        off = offset_fn(t)
        if off != F.london_offset_s(t):
            bad["offset==fbd1"].append(t)
        if off != int(TU.london_offset(u).total_seconds()):
            bad["offset==timeutil"].append(t)
        if offset_fn is not C.london_offset_s:
            continue                                     # a mutant offset function: only the oracle comparison applies
        lt = datetime.fromtimestamp(t, C.LONDON)
        naive = lt.replace(tzinfo=None)
        f = C.local_fields(t)
        if naive != TU.to_local(u):
            bad["fromtimestamp==timeutil.to_local"].append(t)
        if (lt.year, lt.month, lt.day, lt.hour, lt.minute, lt.second, off == 3600) != f:
            bad["fields==local_fields"].append(t)
        if lt.utcoffset() != timedelta(seconds=off):
            bad["utcoffset"].append(t)
        if lt.fold != int(_second_occurrence(t)):
            bad["fold"].append(t)
        if lt.timestamp() != t:
            bad["timestamp round trip"].append(t)
        if C.utc_of_local(*f[:6], fold=lt.fold) != t:
            bad["utc_of_local(fold) round trip"].append(t)
        if F.utc_of_local(*f[:6]) != (t - 3600 * lt.fold):
            bad["fbd1.utc_of_local (BST reading)"].append(t)
        if TU.local_to_utc(naive, fold=lt.fold) != u:
            bad["timeutil.local_to_utc(fold)"].append(t)
        e = F.EspTime(t, True)
        if (e.year, e.month, e.day_of_month, e.hour, e.minute, e.second, e.is_dst) != f:
            bad["fbd1.EspTime fields"].append(t)
        if C.iso_local(t) != lt.isoformat():
            bad["iso_local==isoformat"].append(t)
        if ZL is not None:
            z = datetime.fromtimestamp(t, ZL)
            if (z.replace(tzinfo=None), z.fold, z.utcoffset()) != (naive, lt.fold, lt.utcoffset()):
                bad["zoneinfo"].append(t)
    return bad


def local_sweep(tz, start: datetime, end: datetime, step: timedelta) -> tuple[dict[str, list], list]:
    """Every naive wall time start, start + step, ... < end with fold 0 and 1 through `tz`; ({property: [...]}, special)."""
    bad: dict[str, list] = {k: [] for k in ("utcoffset", "tzname", "dst", "timestamp", "utc_of_local", "kind==timeutil",
                                            "zoneinfo")}
    special = []
    n = start
    while n < end:
        kind = C.local_kind(n.year, n.month, n.day, n.hour, n.minute, n.second)
        if kind != "normal":
            special.append((n.strftime("%Y-%m-%d %H:%M"), kind))
        if TU.is_ambiguous_local(n) != (kind == "ambiguous"):
            bad["kind==timeutil"].append(n)
        for fold in (0, 1):
            try:
                exp = int((n - TU.local_to_utc(n, fold=fold).replace(tzinfo=None)).total_seconds())
                if kind == "gap":
                    bad["kind==timeutil"].append(n)
            except TU.TimeParseError:                     # the oracle has no reading in the gap: PEP 495 / zoneinfo rule
                exp = 3600 if fold else 0
                if kind != "gap":
                    bad["kind==timeutil"].append(n)
            a = n.replace(tzinfo=tz, fold=fold)
            if a.utcoffset() != timedelta(seconds=exp):
                bad["utcoffset"].append((n, fold))
            if a.tzname() != ("BST" if exp else "GMT"):
                bad["tzname"].append((n, fold))
            if a.dst() != timedelta(seconds=exp):
                bad["dst"].append((n, fold))
            want_ts = int((n - EPOCH_NAIVE).total_seconds()) - exp
            if a.timestamp() != want_ts:
                bad["timestamp"].append((n, fold))
            if C.utc_of_local(n.year, n.month, n.day, n.hour, n.minute, n.second, fold=fold) != want_ts:
                bad["utc_of_local"].append((n, fold))
            if ZL is not None:
                b = n.replace(tzinfo=ZL, fold=fold)
                if (b.utcoffset(), b.tzname(), b.dst(), b.timestamp()) != (a.utcoffset(), a.tzname(), a.dst(), a.timestamp()):
                    bad["zoneinfo"].append((n, fold))
        n += step
    return bad, special


def _report(prefix: str, bad: dict[str, list]) -> None:
    for prop, hits in bad.items():
        if prop == "zoneinfo" and ZL is None:
            zoneinfo_skipped(f"{prefix}: {prop}")
            continue
        check(f"{prefix}: {prop}", not hits, f"{len(hits)} mismatch(es), first {hits[:3]}")


class _SwappedFold(C.London):
    """NEGATIVE CONTROL: a London whose fold is inverted (ambiguous and gap readings swapped)."""

    def _off(self, dt):
        return super()._off(dt.replace(fold=1 - dt.fold))


def section_sweeps() -> None:
    print("[2] sweeps: UTC -> local every 15 min and local -> UTC every 15 min (fold 0/1), 2026-01-01..2027-12-31")
    a, b = _ep(2026, 1, 1), _ep(2028, 1, 1)
    _report("UTC 15-min sweep 2026-2027", utc_sweep(a, b, 900))
    bad, special = local_sweep(C.LONDON, datetime(2026, 1, 1), datetime(2028, 1, 1), timedelta(minutes=15))
    _report("local 15-min sweep 2026-2027 (fold 0 and 1)", bad)
    want = ([(f"2026-03-29 01:{m:02d}", "gap") for m in (0, 15, 30, 45)]
            + [(f"2026-10-25 01:{m:02d}", "ambiguous") for m in (0, 15, 30, 45)]
            + [(f"2027-03-28 01:{m:02d}", "gap") for m in (0, 15, 30, 45)]
            + [(f"2027-10-31 01:{m:02d}", "ambiguous") for m in (0, 15, 30, 45)])
    check("local_kind: exactly the 01:00-01:45 wall times of the four change days are gap / ambiguous", special == want,
          str(special))
    print("[2b] per-second sweeps of +-2 h around the four 2026/2027 changes")
    for label, edge in (("2026 spring", C.bst_bounds_utc(2026)[0]), ("2026 fall", FALL), ("2027 spring", SPRING),
                        ("2027 fall", C.bst_bounds_utc(2027)[1])):
        _report(f"per-second {label}", utc_sweep(edge - 7200, edge + 7200, 1))
    hours = {datetime.fromtimestamp(t, C.LONDON).hour for t in range(SPRING - 3600, SPRING + 3600)}
    check("2027-03-28: no instant renders in the missing 01:xx wall hour", 1 not in hours and hours == {0, 2}, str(hours))
    print("[2c] negative controls of the sweep comparators")
    fixed = utc_sweep(a, b, 900, offset_fn=lambda t: 3600)
    check("negative control: a fixed UTC+1 offset (the HA sim default) is caught by both oracles",
          len(fixed["offset==fbd1"]) > 0 and len(fixed["offset==fbd1"]) == len(fixed["offset==timeutil"]),
          str(len(fixed["offset==fbd1"])))
    week = utc_sweep(a, b, 900, offset_fn=lambda t: 0 if FALL - 7 * 86400 <= t < FALL else C.london_offset_s(t))
    check("negative control: an October 2026 change one week early is caught at exactly 7 x 96 sweep points",
          len(week["offset==fbd1"]) == 672 and len(week["offset==timeutil"]) == 672, str(len(week["offset==fbd1"])))
    sw, _ = local_sweep(_SwappedFold(), datetime(2026, 1, 1), datetime(2028, 1, 1), timedelta(minutes=15))
    check("negative control: an inverted fold is caught at exactly the 16 gap/ambiguous wall times x 2 folds",
          len(sw["utcoffset"]) == 32, str(len(sw["utcoffset"])))
    if EXTENDED:
        print("[2d] EXTENDED: UTC 15-min sweep 2000-01-01..2037-12-31")
        _report("EXTENDED UTC 15-min sweep 2000-2037", utc_sweep(_ep(2000, 1, 1), _ep(2038, 1, 1), 900))
    if ZL is None:
        print(f"  info  zoneinfo unavailable: {len(ZONEINFO_SKIPPED)} zoneinfo sweep cross-check(s) SKIPPED so far (listed "
              "above); the other oracles still ran")


# =============================================================================================================================
# [3] both transitions in detail
# =============================================================================================================================
def _wall(y, m, d, h, mi, s, fold) -> tuple:
    a = datetime(y, m, d, h, mi, s, fold=fold, tzinfo=C.LONDON)
    return int(a.utcoffset().total_seconds()), a.tzname(), C.iso_utc(int(a.timestamp())), C.utc_of_local(y, m, d, h, mi, s, fold=fold)


def _from_utc(t: int) -> tuple:
    lt = datetime.fromtimestamp(t, C.LONDON)
    return lt.strftime("%H:%M:%S"), lt.fold, lt.tzname()


def section_transitions() -> None:
    print("[3] fall-back 2026-10-25 and spring-forward 2027-03-28 in detail")
    fall = {  # (h, m, s, fold) -> (offset s, tzname, iso utc)
        (0, 59, 59, 0): (3600, "BST", "2026-10-24T23:59:59Z"), (0, 59, 59, 1): (3600, "BST", "2026-10-24T23:59:59Z"),
        (1, 0, 0, 0): (3600, "BST", "2026-10-25T00:00:00Z"), (1, 0, 0, 1): (0, "GMT", "2026-10-25T01:00:00Z"),
        (1, 30, 0, 0): (3600, "BST", "2026-10-25T00:30:00Z"), (1, 30, 0, 1): (0, "GMT", "2026-10-25T01:30:00Z"),
        (1, 59, 59, 0): (3600, "BST", "2026-10-25T00:59:59Z"), (1, 59, 59, 1): (0, "GMT", "2026-10-25T01:59:59Z"),
        (2, 0, 0, 0): (0, "GMT", "2026-10-25T02:00:00Z"), (2, 0, 0, 1): (0, "GMT", "2026-10-25T02:00:00Z"),
    }
    for (h, mi, s, fold), want in fall.items():
        got = _wall(2026, 10, 25, h, mi, s, fold)
        check(f"fall wall {h:02d}:{mi:02d}:{s:02d} fold={fold} -> {want[1]} {want[2]}",
              got[:3] == want and got[3] == C.parse_iso_utc(want[2]), str(got))
    for t, want in ((FALL - 1, ("01:59:59", 0, "BST")), (FALL, ("01:00:00", 1, "GMT")), (FALL + 3599, ("01:59:59", 1, "GMT")),
                    (FALL + 3600, ("02:00:00", 0, "GMT"))):
        check(f"fall fromutc {C.iso_utc(t)} -> {want[0]} fold={want[1]} {want[2]}", _from_utc(t) == want, str(_from_utc(t)))
    spring = {
        (0, 59, 59, 0): (0, "GMT", "2027-03-28T00:59:59Z"), (0, 59, 59, 1): (0, "GMT", "2027-03-28T00:59:59Z"),
        (1, 0, 0, 0): (0, "GMT", "2027-03-28T01:00:00Z"), (1, 0, 0, 1): (3600, "BST", "2027-03-28T00:00:00Z"),
        (1, 30, 0, 0): (0, "GMT", "2027-03-28T01:30:00Z"), (1, 30, 0, 1): (3600, "BST", "2027-03-28T00:30:00Z"),
        (1, 59, 59, 0): (0, "GMT", "2027-03-28T01:59:59Z"), (1, 59, 59, 1): (3600, "BST", "2027-03-28T00:59:59Z"),
        (2, 0, 0, 0): (3600, "BST", "2027-03-28T01:00:00Z"), (2, 0, 0, 1): (3600, "BST", "2027-03-28T01:00:00Z"),
    }
    for (h, mi, s, fold), want in spring.items():
        got = _wall(2027, 3, 28, h, mi, s, fold)
        check(f"spring wall {h:02d}:{mi:02d}:{s:02d} fold={fold} -> {want[1]} {want[2]}",
              got[:3] == want and got[3] == C.parse_iso_utc(want[2]), str(got))
    for t, want in ((SPRING - 1, ("00:59:59", 0, "GMT")), (SPRING, ("02:00:00", 0, "BST"))):
        check(f"spring fromutc {C.iso_utc(t)} -> {want[0]} fold={want[1]} {want[2]}", _from_utc(t) == want, str(_from_utc(t)))
    check("spec example: 2027-03-28 01:30 (fold 0, gap) -> 01:30Z = 02:30 BST",
          C.utc_of_local(2027, 3, 28, 1, 30) == SPRING + 1800 and C.iso_local(SPRING + 1800) == "2027-03-28T02:30:00+01:00")
    check("oracle difference characterised: fbd1.utc_of_local raises ValueError and timeutil.local_to_utc raises "
          "TimeParseError for the gap; _lab_clock follows " + ("zoneinfo instead" if ZL is not None else
                                                               "the PEP 495 gap rule instead"),
          raises(ValueError, F.utc_of_local, 2027, 3, 28, 1, 30)[0]
          and raises(TU.TimeParseError, TU.local_to_utc, datetime(2027, 3, 28, 1, 30))[0])
    check("utcoffset / dst / tzname of None are None (" + ("ZoneInfo protocol" if ZL is not None else
                                                           "the tzinfo convention") + ")",
          C.LONDON.utcoffset(None) is None and C.LONDON.dst(None) is None and C.LONDON.tzname(None) is None)
    check("fromutc refuses a datetime of another tzinfo and a non-datetime",
          raises(ValueError, C.LONDON.fromutc, datetime(2026, 1, 1, tzinfo=UTC))[0]
          and raises(TypeError, C.LONDON.fromutc, "2026-01-01")[0])
    rt = [datetime.fromtimestamp(t, UTC).astimezone(C.LONDON).astimezone(UTC) == datetime.fromtimestamp(t, UTC)
          and datetime.fromtimestamp(t, UTC).astimezone(C.LONDON) == datetime.fromtimestamp(t, C.LONDON)
          for t in range(FALL - 5400, FALL + 5400, 60)]
    check("astimezone UTC -> LONDON -> UTC round trips across the fall change and equals fromtimestamp", all(rt))
    start = datetime(2026, 10, 25, 0, 30, tzinfo=C.LONDON)
    later = start + timedelta(hours=2)
    ok = (later.strftime("%H:%M %Z") == "02:30 GMT" and later.timestamp() - start.timestamp() == 10800)
    arith = "same-tzinfo arithmetic is wall-time (00:30 BST + 2 h = 02:30 GMT = 3 h real)"
    if ZL is not None:
        zs = datetime(2026, 10, 25, 0, 30, tzinfo=ZL)
        zl2 = zs + timedelta(hours=2)
        ok = ok and zl2.strftime("%H:%M %Z") == "02:30 GMT" and zl2.timestamp() - zs.timestamp() == 10800
        check(f"{arith}, identical to zoneinfo", ok)
    else:
        check(arith, ok)
        zoneinfo_skipped(f"{arith}: the comparison with zoneinfo")


# =============================================================================================================================
# [4] the Home Assistant sim LOCAL patch
# =============================================================================================================================
class _Boom(Exception):
    """A sentinel raised inside test bodies."""


def section_ha_local() -> None:
    print("[4] patched_ha_local(S): HA sim rendering in Europe/London, restore on exit and on exception")
    orig = S.LOCAL
    check("baseline: the HA sim zone is fixed UTC+1 (2026-10-25 01:30Z renders 02:30)",
          orig.utcoffset(None) == timedelta(hours=1) and S.local_str(FALL + 1800) == "2026-10-25 02:30:00")
    with C.patched_ha_local(S) as tz:
        inside = S.LOCAL
        w = S.World(FALL + 1800)
        D.add_ha_filters(w)
        r = {
            "first 01:30": S.local_str(FALL - 1800), "second 01:30": S.local_str(FALL + 1800),
            "parse ambiguous": S.parse_local("2026-10-25 01:30:00"), "parse gap": S.parse_local("2027-03-28 01:30:00"),
            "now": w.render("{{ now().strftime('%Y-%m-%d %H:%M:%S %Z') }} fold={{ now().fold }}"),
            "as_timestamp": w.render("{{ as_timestamp('2026-10-25 01:30:00') | int }}"),
            "timestamp_custom": w.render("{{ %d | timestamp_custom('%%H:%%M %%Z') }}" % (FALL + 1800)),
            "timestamp_local": w.render("{{ %d | timestamp_local }}" % (FALL + 1800)),
            "last_changed": S._StateObj("on", FALL - 1800).last_changed.isoformat(),
        }
    check("inside: S.LOCAL is LONDON and the context value is LONDON", inside is C.LONDON and tz is C.LONDON)
    check("inside: S.local_str renders 01:30:00 for BOTH 00:30Z and 01:30Z (the repeated hour)",
          r["first 01:30"] == "2026-10-25 01:30:00" and r["second 01:30"] == "2026-10-25 01:30:00", str(r))
    check("inside: S.parse_local resolves the repeated 01:30 to the BST occurrence (00:30Z) and the missing 01:30 to 01:30Z",
          r["parse ambiguous"] == FALL - 1800 and r["parse gap"] == SPRING + 1800, str(r))
    check("inside: World.now() renders 01:30:00 GMT with fold=1 at 01:30Z", r["now"] == "2026-10-25 01:30:00 GMT fold=1",
          r["now"])
    check("inside: template as_timestamp / timestamp_custom / D.timestamp_local / last_changed follow London",
          r["as_timestamp"] == str(FALL - 1800) and r["timestamp_custom"] == "01:30 GMT"
          and r["timestamp_local"] == "2026-10-25T01:30:00+00:00" and r["last_changed"] == "2026-10-25T01:30:00+01:00", str(r))
    check("after exit: S.LOCAL is the original object again and renders UTC+1",
          S.LOCAL is orig and S.local_str(FALL + 1800) == "2026-10-25 02:30:00")
    caught = False
    try:
        with C.patched_ha_local(S):
            raise _Boom("body raises")
    except _Boom:
        caught = True
    check("an exception in the body propagates and S.LOCAL is still restored", caught and S.LOCAL is orig)
    with C.patched_ha_local(S):
        S.LOCAL = timezone(timedelta(hours=5))
    check("a body that reassigns S.LOCAL is still restored to the original", S.LOCAL is orig)
    with C.patched_ha_local(S):
        with C.patched_ha_local(S):
            pass
        nested_mid = S.LOCAL
    check("nested use restores LIFO (LONDON after the inner exit, the original after the outer)",
          nested_mid is C.LONDON and S.LOCAL is orig)
    check("a module without LOCAL fails loud (AttributeError) and gains no attribute",
          raises(AttributeError, lambda: C.patched_ha_local(types.SimpleNamespace()).__enter__())[0])


# =============================================================================================================================
# [5] canonical JSON, [6] event log
# =============================================================================================================================
def section_canonical() -> None:
    print("[5] canonical JSON")
    a = {"b": 1, "a": {"y": 2, "x": [1, 2]}}
    b = {"a": {"x": [1, 2], "y": 2}, "b": 1}
    check("canonical JSON is identical for every dict insertion order",
          T.canonical_json(a) == T.canonical_json(b) == '{"a":{"x":[1,2],"y":2},"b":1}', T.canonical_json(a))
    check("floats are rounded to 3 dp, -0.0 -> 0.0, tuples -> lists",
          T.canonical(0.1 + 0.2) == 0.3 and T.canonical_json(-0.0) == "0.0" and T.canonical(1.23456) == 1.235
          and T.canonical((1, (2, 3))) == [1, [2, 3]])
    check("bool and int stay distinct; output is ASCII", T.canonical_json(True) == "true" and T.canonical_json(1) == "1"
          and T.canonical_json(chr(0xE9)) == '"\\u00e9"')
    bad = [float("nan"), float("inf"), {1: "x"}, {"s": {1, 2}}, b"x", object()]
    check("NaN, inf, non-str keys, sets, bytes and objects raise LabTraceError",
          all(raises(T.LabTraceError, T.canonical, v)[0] for v in bad))


def _mk_log(events) -> T.EventLog:
    log = T.EventLog()
    for e in events:
        log.append(**e)
    return log


BASE_EVENTS = [
    {"t_utc": FALL - 60, "up_ms": 2000, "boot": 1, "src": "fw", "kind": "status", "data": {"dom": "fp", "text": "IDLE"}},
    {"t_utc": FALL - 59.5, "up_ms": 2500, "boot": 1, "src": "fw", "kind": "modbus.write", "data": {"addr": 244, "values": [2]}},
    {"t_utc": FALL, "up_ms": None, "boot": None, "src": "ha", "kind": "service", "data": {"svc": "button.press", "b": 1, "a": 2}},
    {"t_utc": FALL + 1, "up_ms": None, "boot": None, "src": "lab", "kind": "fault", "data": {}},
]


def section_eventlog() -> None:
    print("[6] EventLog and its digest")
    log1, log2 = _mk_log(BASE_EVENTS), _mk_log(copy.deepcopy(BASE_EVENTS))
    check("the digest is stable for an identical rebuild", log1.digest() == log2.digest())
    check("seq is assigned 0..n-1 and canonical() == canonical_json(list(log)) == the digested text",
          [e["seq"] for e in log1] == [0, 1, 2, 3] and log1.canonical() == T.canonical_json(list(log1))
          and log1.digest() == T.digest_of(list(log1)))
    variants = {}
    for label, (i, key, val) in {"one data value": (0, "data", {"dom": "fp", "text": "IDLE "}),
                                 "one t_utc": (1, "t_utc", FALL - 59.4), "one src": (3, "src", "ha"),
                                 "one kind": (2, "kind", "service2"), "one boot": (1, "boot", 2)}.items():
        ev = copy.deepcopy(BASE_EVENTS)
        ev[i][key] = val
        variants[label] = _mk_log(ev).digest()
    for label, dg in variants.items():
        check(f"negative control: changing {label} of one event changes the digest", dg != log1.digest())
    reordered = copy.deepcopy(BASE_EVENTS)
    reordered[2]["data"] = {"a": 2, "svc": "button.press", "b": 1}
    check("a different data-key insertion order gives the same digest", _mk_log(reordered).digest() == log1.digest())
    longer = _mk_log(BASE_EVENTS)
    longer.append(t_utc=FALL + 2, up_ms=None, boot=None, src="lab", kind="x")
    check("appending an event changes the digest", longer.digest() != log1.digest())
    sub_ms = copy.deepcopy(BASE_EVENTS)
    sub_ms[1]["t_utc"] = FALL - 59.5004
    check("MODEL: float times differing below 1 ms digest equal (3 dp rounding); 1 ms apart they differ",
          _mk_log(sub_ms).digest() == log1.digest() and variants["one t_utc"] != log1.digest())
    log3 = _mk_log(BASE_EVENTS)
    d0 = log3.digest()
    returned = log3.append(t_utc=FALL + 5, up_ms=1, boot=1, src="fw", kind="k", data={"v": [1]})
    d1 = log3.digest()
    returned["data"]["v"].append(2)
    log3[4]["data"]["v"].append(3)
    for e in log3:
        e["kind"] = "tampered"
    check("append-only: mutating returned / iterated / indexed events never changes the log", log3.digest() == d1 != d0
          and log3[4]["data"] == {"v": [1]})
    caller = {"v": [1]}
    log4 = T.EventLog()
    log4.append(t_utc=1, up_ms=0, boot=0, src="fw", kind="k", data=caller)
    dg4 = log4.digest()
    caller["v"].append(9)
    check("append-only: mutating the caller's data object after append does not change the log", log4.digest() == dg4)
    badargs = [dict(t_utc=1, up_ms=0, boot=0, src="xx", kind="k"), dict(t_utc=1, up_ms=None, boot=0, src="fw", kind="k"),
               dict(t_utc=1, up_ms=0, boot=None, src="fw", kind="k"), dict(t_utc=1, up_ms=0, boot=-1, src="fw", kind="k"),
               dict(t_utc=True, up_ms=0, boot=0, src="fw", kind="k"), dict(t_utc=float("nan"), up_ms=0, boot=0, src="fw", kind="k"),
               dict(t_utc=1, up_ms=0, boot=0, src="fw", kind=""), dict(t_utc=1, up_ms=0, boot=0, src="fw", kind="a b"),
               dict(t_utc=1, up_ms=0.5, boot=0, src="fw", kind="k"), dict(t_utc=1, up_ms=0, boot=0, src="fw", kind="k", data={"s": {1}})]
    check("append fails loud on a bad src / missing fw up_ms or boot / negative / bool / NaN time / bad kind / float up_ms / "
          "non-JSON data", all(raises(T.LabTraceError, T.EventLog().append, **kw)[0] for kw in badargs))
    reg = T.EventLog()
    for t in (10, 11, 9, 12):
        reg.append(t_utc=t, up_ms=None, boot=None, src="lab", kind="tick")
    check("utc_regressions() reports exactly the event whose t_utc went backwards", reg.utc_regressions() == [2]
          and log1.utc_regressions() == [])
    check("events() / last() filter by kind and src",
          [e["seq"] for e in log1.events(src="fw")] == [0, 1] and log1.last(kind="service")["seq"] == 2
          and log1.last(kind="nope") is None and len(log1.events(boot=1)) == 2)


# =============================================================================================================================
# [7] known risks, [8] vocabularies, [9] expectation operators
# =============================================================================================================================
REQUIRED_RISKS = ("SG-25", "N10", "N15", "N16", "N17", "PR41-GHOST", "NVS-PARTITION-ERASE", "PLATFORM-ABSENT", "FCP2-R1",
                  "FCP2-C1", "FCP2-F2", "FCP2-F3", "FCP2-F6", "FCP2-F7", "FCP2-F8", "SMR1-OWNER-STAGING",
                  "SMR1-OWNER-RESTORING", "SMR1-UNCLEAN-SHUTDOWN", "SMR1-STALE-24H")
S4_DOC = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
FW_DOC = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# the S4 section 2.10 blind spots the two registry additions anchor (exact substrings, verified exactly once below)
GHOST_TEXT = "A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear)"
ERASE_TEXT = "A partition erase (E04 P10; ESPHome erases the partition when"
# V0.1 (B1): the S4 design record is NON-BEHAVIOURAL, read only by exactly-once anchors. The row / item / section checks
# below are exactly-once anchors of the FULL lines (the N16 / N17 table rows that say 'Accepted residual', the blind-spot
# items '1.' and '3.') and of the section 2.10 heading; no other content of the file is used (the V0 checks took the line
# around an anchor and the nearest heading above it, which made the file behavioural). A reworded row, item or heading is
# a FAIL here (re-anchor it after checking it still says the same). Source: S4_domains_decisions_final.md table 1.4 rows
# N16 / N17 and section 2.10 'Blind spots (reported, not hidden)' items 1 and 3.
S4_ROWS = {
    "N16": ("| **N16** | P0 can overlay a **trusted** R244 obligation. The S4 arbitration fires only when both sides are "
            "non-corrupt (FW:815-819); SG-02's gate has no `rSV` term (FW:17075-17087) | Dump marker malformed or data-bad "
            "(C set, K armed) + R244 RR trusted at the same boot \u2192 containment may write 244 := 2 over a held harness "
            "value; the harness restore then hits its drift guard (FW:14511) | R244 dead end (N11) | Accepted residual "
            "(restrictive direction). FB-C: DUMP L3 wins; R244 is still reported |"),
    "N17": ("| **N17** | P1 restores (FP and Dump) carry no cross-domain terms. With the other domain corrupt/unknown (so the "
            "boot arbitrations FW:815-822 / 904-911 do not fire), a trusted P1 restore writes the shared 256-261 over the "
            "other domain's unresolved obligation. This violates R1 as restated | FW:7726-7734, 16425-16447 (no "
            "other-domain terms) | Both domains still block Fallback; the write direction is the domain's own ORIGINAL | "
            "Accepted residual; FB-D may add `!other_corrupt` terms. FB-C: L3 of the corrupt domain wins |"),
}
S4_210_HEADING = "### 2.10 The durable leg inside FB-C: no NVS reads [REC, LOCKED]"
GHOST_ITEM = ("  1. " + GHOST_TEXT + " is invisible unless FB-B's REVIEW/SAVE probe latched it this boot. FB-F's precheck "
              "probe owns it (ARCH row 10, `ARCH:531`; A17 `ARCH:905`). The detail `aborted_start_mask` flags START "
              "attempts that ended without an obligation in RAM (ghost possible).")
ERASE_ITEM = ("  3. " + ERASE_TEXT + " `nvs_open` fails, V2 (5)) makes every marker ABSENT. F11.h/D12 catch it only if a "
              "retry record survived; otherwise R3 blocks FB-F by absence anyway.")


def _once(path: str, text: str) -> bool:
    return T.anchor_count(path, text)[0] == 1


def section_known_risk_corrections() -> None:
    print("[7b] KNOWN_RISKS corrections: N16 / N17 accepted residuals, PR41-GHOST and NVS-PARTITION-ERASE (S4 2.10 blind spots)")
    for rid in ("N16", "N17"):
        r = T.KNOWN_RISKS[rid]
        row = S4_ROWS[rid]
        check(f"{rid} is ACCEPTED-RESIDUAL and its full S4 table row, which starts with the registry anchor and says "
              "'Accepted residual', occurs exactly once (an exactly-once anchor of the whole row)",
              r["class"] == "ACCEPTED-RESIDUAL" and r["path"] == S4_DOC and row.startswith(r["text"])
              and "Accepted residual" in row and _once(S4_DOC, row), f"{r['class']} | found {T.anchor_count(S4_DOC, row)[0]}x")
    g, e = T.KNOWN_RISKS["PR41-GHOST"], T.KNOWN_RISKS["NVS-PARTITION-ERASE"]
    heading_once = _once(S4_DOC, S4_210_HEADING)
    check("PR41-GHOST: DOCUMENTED-LIMIT, anchored at the S4 2.10 blind spot 1 text (exactly once); the full item line '1. "
          "...' and the section 2.10 heading each occur exactly once (exactly-once anchors)",
          g["class"] == "DOCUMENTED-LIMIT" and g["path"] == S4_DOC and g["text"] == GHOST_TEXT
          and _once(S4_DOC, GHOST_TEXT) and GHOST_ITEM.lstrip().startswith("1. " + GHOST_TEXT) and _once(S4_DOC, GHOST_ITEM)
          and heading_once, f"{g['class']} item {T.anchor_count(S4_DOC, GHOST_ITEM)[0]}x heading {heading_once}")
    check("NVS-PARTITION-ERASE: PLATFORM-LIMIT, anchored at the S4 2.10 blind spot 3 text (exactly once); the full item "
          "line '3. ...' and the section 2.10 heading each occur exactly once (exactly-once anchors)",
          e["class"] == "PLATFORM-LIMIT" and e["path"] == S4_DOC and e["text"] == ERASE_TEXT
          and _once(S4_DOC, ERASE_TEXT) and ERASE_ITEM.lstrip().startswith("3. " + ERASE_TEXT) and _once(S4_DOC, ERASE_ITEM)
          and heading_once, f"{e['class']} item {T.anchor_count(S4_DOC, ERASE_ITEM)[0]}x heading {heading_once}")
    refs = T.KNOWN_RISK_REFS
    check("KNOWN_RISK_REFS: every id is registered and every secondary reference text occurs exactly once in its file",
          set(refs) <= set(T.KNOWN_RISKS) and all(T.anchor_count(p, t)[0] == 1 for rs in refs.values() for p, t in rs),
          str({rid: [T.anchor_count(p, t)[0] for p, t in rs] for rid, rs in refs.items()}))
    fw_ref = "Free Power<->Dump dual durable-obligation dead-end (256-261)"
    check("PR41-GHOST names the firmware's on_boot dual-obligation arbitration comment as its second reference (title and "
          "KNOWN_RISK_REFS, in the firmware file)", fw_ref in g["title"] and (FW_DOC, fw_ref) in refs.get("PR41-GHOST", ()))
    for rid, rs in refs.items():
        for p, t in rs:
            print(f"  info  {rid} also documented at {p}:{T.anchor_count(p, t)[1]}  {t[:60]}")
    typo = GHOST_TEXT.replace("RAM is clear", "RAM is clean")
    ok, msg = raises(T.AnchorError, T.anchor_line, S4_DOC, typo)
    check("negative control: the blind-spot anchor with one changed word is found 0 times (anchor_line refuses it)",
          ok and "0 times" in msg, msg)
    check("the classes used are all in RISK_CLASSES; FINDING-KNOWN:PR41-GHOST / :NVS-PARTITION-ERASE parse",
          all(r["class"] in T.RISK_CLASSES for r in T.KNOWN_RISKS.values())
          and T.parse_classification("FINDING-KNOWN:PR41-GHOST") == ("FINDING-KNOWN", "PR41-GHOST")
          and T.parse_classification(T.classify("FINDING-KNOWN", "NVS-PARTITION-ERASE"))[1] == "NVS-PARTITION-ERASE")


def section_known_risks() -> None:
    print("[7] KNOWN_RISKS: every anchor text occurs exactly once in its public file")
    check("every required known-risk id is registered", set(REQUIRED_RISKS) <= set(T.KNOWN_RISKS),
          str(sorted(set(REQUIRED_RISKS) - set(T.KNOWN_RISKS))))
    shape_ok = all(set(r) == {"title", "path", "text", "line_at_record", "doc_anchor", "class"} and r["class"] in T.RISK_CLASSES
                   and r["doc_anchor"] == f"{r['path']}:{r['line_at_record']}" and r["text"].isascii()
                   and r["title"].strip() for r in T.KNOWN_RISKS.values())
    check("every entry has {title, path, text, line_at_record, doc_anchor, class}, a known class and an ASCII anchor", shape_ok)
    status = T.known_risk_status()
    for rid in sorted(T.KNOWN_RISKS):
        r, st = T.KNOWN_RISKS[rid], status[rid]
        check(f"known risk {rid}: anchor occurs exactly once in {r['path']}", st["count"] == 1, f"count {st['count']}")
        moved = "" if st["line"] == st["line_at_record"] else f" (recorded at line {st['line_at_record']}: MOVED)"
        print(f"  info  {rid} [{r['class']}] {r['path']}:{st['line']}{moved}")
    fw = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
    ok3, msg3 = raises(T.AnchorError, T.anchor_line, fw, "a reboot may make the record read as absent")
    ok0, msg0 = raises(T.AnchorError, T.anchor_line, fw, "this text is not in the firmware file at all")
    check("negative control: anchor_line refuses a text found 3 times and one found 0 times",
          ok3 and "3 times" in msg3 and ok0 and "0 times" in msg0, f"{msg3} | {msg0}")
    check("known_risk() returns a copy and refuses an unknown id",
          T.known_risk("SG-25") == T.KNOWN_RISKS["SG-25"] and T.known_risk("SG-25") is not T.KNOWN_RISKS["SG-25"]
          and raises(T.LabTraceError, T.known_risk, "NOPE")[0])
    check("anchor paths must be repo-relative POSIX", all(raises(T.LabTraceError, T.read_source_text, p)[0]
                                                         for p in ("/etc/x", "a\\b", "../x", "a//b", "")))


def section_vocab() -> None:
    print("[8] classification and grade vocabularies")
    check("CLASSIFICATIONS and GRADES are exactly the spec's vocabularies",
          T.CLASSIFICATIONS == ("PASS", "FAIL", "FINDING-NEW", "FINDING-KNOWN", "UNSUPPORTED", "BLOCKED")
          and T.GRADES == ("VERIFIED", "REPORTED", "INFERRED", "UNKNOWN"))
    plain = [c for c in T.CLASSIFICATIONS if c != "FINDING-KNOWN"]
    check("every plain classification round-trips", all(T.parse_classification(T.classify(c)) == (c, None) for c in plain))
    check("FINDING-KNOWN:<id> builds and parses for every registered risk",
          all(T.parse_classification(T.classify("FINDING-KNOWN", r)) == ("FINDING-KNOWN", r) for r in T.KNOWN_RISKS))
    bad = ["FINDING-KNOWN", "FINDING-KNOWN:NOPE", "PASSED", "pass", "FINDING-KNOWN:", "", None]
    check("anything outside the vocabulary raises", all(raises(T.LabTraceError, T.parse_classification, b)[0] for b in bad))
    check("a risk id goes with FINDING-KNOWN only", raises(T.LabTraceError, T.classify, "FAIL", "SG-25")[0]
          and raises(T.LabTraceError, T.classify, "FINDING-KNOWN")[0])


def section_ops() -> None:
    print("[9] expectation operators")
    table = [("==", "A", "A", True), ("==", 1, True, False), ("==", 1, 1.0, False), ("==", [1, 2], (1, 2), True),
             ("==", {"a": 1, "b": 2}, {"b": 2, "a": 1}, True), ("==", None, None, True), ("!=", "A", "B", True),
             ("!=", "A", "A", False), ("startswith", "RECOVERY BLOCKED - x", "RECOVERY", True),
             ("startswith", "x", "RECOVERY", False), ("startswith", None, "R", False), ("contains", "abc", "b", True),
             ("contains", [1, 2], 2, True), ("contains", [1, 2], 3, False), ("contains", [[1], 2], [1], True),
             ("contains", {"k": 1}, "k", True), ("contains", 5, 5, False), ("not_contains", "abc", "z", True),
             ("not_contains", "abc", "b", False), ("not_contains", None, "b", False), ("not_contains", [1], True, True),
             ("<=", 3, 3, True), ("<=", 4, 3, False), (">=", 2.5, 2, True), (">=", True, 0, False), ("<=", "1", 2, False),
             (">=", None, 0, False)]
    wrong = [(op, o, v, want) for op, o, v, want in table if T.eval_expectation(op, o, v)[0] is not want]
    check(f"all {len(table)} operator cases (type mismatches FAIL, never pass)", not wrong, str(wrong))
    check("an unknown op raises CorpusSchemaError; a non-JSON observation raises LabTraceError",
          raises(T.CorpusSchemaError, T.eval_expectation, "~=", 1, 1)[0]
          and raises(T.LabTraceError, T.eval_expectation, "==", {1, 2}, [1, 2])[0])


# =============================================================================================================================
# [10] replay engine with a dummy tier registered in-test
# =============================================================================================================================
DUMMY = {"built": 0, "worlds": [], "nondet": 0}
TIER = "selftest"
TIERS = T.TIERS + (TIER,)
ANCHOR_PATH = "docs/dev/schedule-manual-restore.md"
TWICE_PATH, TWICE_TEXT = "registry/tests/assurance_lab/_lab_trace.py", "\ndef "    # a text a lab file repeats


class DummyWorld:
    """A tiny deterministic world honouring the replay WORLD PROTOCOL (log, t_utc, advance_to, close)."""

    def __init__(self, *, utc_start: int, seed: int, start_count: int = 0):
        self.log, self.t_utc, self.utc0 = T.EventLog(), utc_start, utc_start
        self.count, self.status, self.closed = start_count, "IDLE", False
        self.rng = random.Random(seed)
        DUMMY["built"] += 1
        DUMMY["worlds"].append(self)

    def advance_to(self, utc_s) -> None:
        self.t_utc = utc_s

    def close(self) -> None:
        self.closed = True

    def emit(self, kind: str, **data) -> None:
        self.log.append(t_utc=self.t_utc, up_ms=int((self.t_utc - self.utc0) * 1000) + 2000, boot=1, src="fw", kind=kind,
                        data=data)


def act_inc(world, n: int = 1) -> None:
    world.count += n
    world.emit("dummy.inc", n=n, count=world.count, r=world.rng.randrange(1000))


def act_status(world, text: str) -> None:
    world.status = text
    world.emit("dummy.status", text=text)


def act_run_for(world, seconds: float) -> None:
    world.t_utc += seconds
    world.emit("dummy.ran", seconds=seconds)


def act_boom(world) -> None:
    raise _Boom("harness exception inside an action")


def act_nondet(world) -> None:
    DUMMY["nondet"] += 1                       # NEGATIVE CONTROL: state that leaks across runs (non-deterministic world)
    world.emit("dummy.nondet", k=DUMMY["nondet"])


def obs_impure(world) -> int:
    world.emit("dummy.observed")
    return 0


DRAFT = {
    "schema": T.SCHEMA, "id": "ST-00-a", "title": "core self-test synthetic replay", "tier": TIER, "seed": 7,
    "utc_start": "2026-10-25T00:30:00Z", "synthetic": True, "ownership": "synthetic: the dummy tier owns everything",
    "source_anchors": [{"path": ANCHOR_PATH, "text": "## Limits and choices", "line_at_record": 1}],
    "source_digests": {ANCHOR_PATH: "0" * 64}, "world": {"start_count": 1},
    "actions": [{"at_s": 0, "do": "inc", "args": {"n": 2}}, {"at_s": 30, "do": "status", "args": {"text": "ACTIVE - synthetic"}},
                {"at_s": 30, "do": "run_for", "args": {"seconds": 60}}, {"at_s": 120, "do": "inc", "args": {}}],
    "expect": [{"observe": "count", "args": {}, "op": "==", "value": 4},
               {"observe": "status", "args": {}, "op": "startswith", "value": "ACTIVE"},
               {"observe": "count", "args": {}, "op": ">=", "value": 4}],
    "classification": "PASS", "invariant": "INV-LAB-SELFTEST", "grade": "VERIFIED", "confidence": "high",
    "failure_outcome": "none (harness self-test)", "smallest_safe_repair_scope": "n/a (harness self-test)",
}


def _quiet_replay(doc, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = T.replay(doc, **kw)
    return r, buf.getvalue()


def section_replay() -> None:
    print("[10] replay DSL engine, drift rule, strict corpus schema, record()")
    check("the dummy tier registered in-test", T.registered(TIER) == {
        "factory": True, "actions": ["boom", "inc", "nondet", "run_for", "status"], "observers": ["count", "impure", "status"]})
    draft_before = copy.deepcopy(DRAFT)
    doc = T.record(DRAFT, tiers=TIERS)
    check("record() fills the source digest, the anchor line and the trace digest, and leaves the draft untouched",
          doc["source_digests"] == {ANCHOR_PATH: T.source_digest(ANCHOR_PATH)}
          and doc["source_anchors"][0]["line_at_record"] == T.anchor_line(ANCHOR_PATH, "## Limits and choices")
          and len(doc["trace_digest"]) == 64 and DRAFT == draft_before)
    check("record() is deterministic (byte-identical corpus text twice)",
          T.dumps_doc(T.record(DRAFT, tiers=TIERS)) == T.dumps_doc(doc))
    built0 = DUMMY["built"]
    r, out = _quiet_replay(doc, tiers=TIERS)
    w = DUMMY["worlds"][-1]
    check("replay of the recorded document passes: ok, no drift, digest == trace_digest, nothing printed",
          r.ok and not r.drift and r.digest == doc["trace_digest"] and not r.failed_expectations and not r.digest_mismatch
          and not r.anchor_problems and out == "", f"{r.failed_expectations} {out!r}")
    check("observations are the canonical observer values in expectation order", r.observations == [4, "ACTIVE - synthetic", 4])
    acts = r.log.events(kind="replay.action")
    check("the engine logs one src=lab replay.action per action at its due time; the world was built once and closed",
          [(e["data"]["do"], e["t_utc"] - C.parse_iso_utc(doc["utc_start"])) for e in acts]
          == [("inc", 0), ("status", 30), ("run_for", 30), ("inc", 120)]
          and all(e["src"] == "lab" for e in acts) and DUMMY["built"] == built0 + 1 and w.closed)
    check("two replays give the same digest", _quiet_replay(doc, tiers=TIERS)[0].digest == r.digest)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / f"{doc['id']}.json").write_bytes(T.dumps_doc(doc).encode("ascii"))
        docs = T.load_corpus(td, tiers=TIERS)
        r_file = _quiet_replay(docs[0], tiers=TIERS)[0]
        (Path(td) / "ST-00-b.json").write_bytes(T.dumps_doc(doc).encode("ascii"))
        stem_bad = raises(T.CorpusSchemaError, T.load_corpus, td, tiers=TIERS)
    check("corpus-file form: dumps_doc -> file -> load_corpus -> replay passes", docs == [doc] and r_file.ok)
    check("load_corpus refuses a file whose stem is not the document id", stem_bad[0], stem_bad[1])
    text = T.dumps_doc(doc)
    dup = text.replace('"seed": 7,', '"seed": 7,\n  "seed": 8,', 1)
    nan = text.replace('"seed": 7,', '"seed": NaN,', 1)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "dup.json").write_bytes(dup.encode("ascii"))
        (Path(td) / "nan.json").write_bytes(nan.encode("ascii"))
        dup_r = raises(T.CorpusSchemaError, T.load_doc, Path(td) / "dup.json", tiers=TIERS)
        nan_r = raises(T.CorpusSchemaError, T.load_doc, Path(td) / "nan.json", tiers=TIERS)
    check("load_doc refuses duplicate JSON keys and NaN (strict JSON)", dup != text and nan != text and dup_r[0] and nan_r[0])
    check("load_corpus of a missing directory raises", raises(FileNotFoundError, T.load_corpus,
                                                              Path(tempfile.gettempdir()) / "ecco-lab-no-such-dir-xyz")[0])

    alt = copy.deepcopy(doc)
    alt["expect"][0]["value"] = 5
    r2 = _quiet_replay(alt, tiers=TIERS)[0]
    check("negative control: an altered expectation value FAILS (index 0 reported; digest unchanged, no drift)",
          not r2.ok and [f["index"] for f in r2.failed_expectations] == [0] and r2.failed_expectations[0]["observed"] == 4
          and r2.digest == doc["trace_digest"] and not r2.drift and not r2.digest_mismatch)
    alt_op = copy.deepcopy(doc)
    alt_op["expect"][1]["op"] = "not_contains"
    check("negative control: an altered expectation op FAILS", not _quiet_replay(alt_op, tiers=TIERS)[0].ok)

    built1 = DUMMY["built"]
    unk = copy.deepcopy(doc)
    unk["actions"].append({"at_s": 200, "do": "no_such_action", "args": {}})
    ok_u, msg_u = raises(T.ReplayDispatchError, T.replay, unk, tiers=TIERS)
    unk_o = copy.deepcopy(doc)
    unk_o["expect"].append({"observe": "no_such_observer", "args": {}, "op": "==", "value": 1})
    ok_o, msg_o = raises(T.ReplayDispatchError, T.replay, unk_o, tiers=TIERS)
    check("an unknown action / observer raises ReplayDispatchError before any world is built",
          ok_u and "no_such_action" in msg_u and ok_o and "no_such_observer" in msg_o and DUMMY["built"] == built1,
          f"{msg_u} | {msg_o}")
    # Importing _lab_fw / _lab_rtc / _lab_ha registers 'firmware' / 'rtc' / 'coupled' at import time, so the unregistered
    # tiers below are in-test names that no lab module registers: these checks hold in any process and in any suite order.
    fw_doc = copy.deepcopy(doc)
    fw_doc["tier"] = "firmware"
    check("a built-in tier name is valid under the default tiers whether or not its module is imported",
          T.validate_doc(fw_doc) is fw_doc)
    ghost, half = f"{TIER}_unregistered", f"{TIER}_nofactory"
    unreg = copy.deepcopy(doc)
    unreg["tier"] = ghost
    ok_g, msg_g = raises(T.ReplayDispatchError, T.replay, unreg, tiers=TIERS + (ghost,))
    check("a valid but unregistered tier raises ReplayDispatchError before any world is built",
          T.registered(ghost) == {"factory": False, "actions": [], "observers": []} and ok_g
          and "no registered factory" in msg_g and DUMMY["built"] == built1, msg_g)
    T.register_actions(half, {"inc": act_inc})
    try:
        half_reg = T.registered(half)
        nofac = copy.deepcopy(doc)
        nofac["tier"] = half
        ok_h, msg_h = raises(T.ReplayDispatchError, T.replay, nofac)
    finally:
        T.unregister_tier(half)
    check("a tier with actions but no factory passes the default-tier schema and its replay raises ReplayDispatchError",
          half_reg == {"factory": False, "actions": ["inc"], "observers": []} and ok_h and "no registered factory" in msg_h
          and DUMMY["built"] == built1 and T.registered(half) == T.registered(ghost), msg_h)
    boom = copy.deepcopy(doc)
    boom["actions"].append({"at_s": 130, "do": "boom", "args": {}})
    ok_b = raises(_Boom, T.replay, boom, tiers=TIERS)[0]
    check("a harness exception inside an action propagates (never a pass) and the world is still closed",
          ok_b and DUMMY["worlds"][-1].closed)
    impure = copy.deepcopy(doc)
    impure["expect"].append({"observe": "impure", "args": {}, "op": "==", "value": 0})
    check("an observer that appends to the log raises ReplayDispatchError",
          raises(T.ReplayDispatchError, T.replay, impure, tiers=TIERS)[0] and DUMMY["worlds"][-1].closed)
    late = copy.deepcopy(doc)
    late["actions"] = [{"at_s": 0, "do": "run_for", "args": {"seconds": 100}}, {"at_s": 50, "do": "inc", "args": {}}]
    check("an action due before the world clock raises ReplayDispatchError",
          raises(T.ReplayDispatchError, T.replay, late, tiers=TIERS)[0])
    badarg = copy.deepcopy(doc)
    badarg["actions"][0]["args"] = {"n": 1, "unexpected": 2}
    check("an action argument the handler does not take raises TypeError (fail loud)",
          raises(TypeError, T.replay, badarg, tiers=TIERS)[0])

    print("  -- strict schema")
    missing = [k for k in T.REQUIRED_KEYS if not raises(T.CorpusSchemaError, T.validate_doc,
                                                        {x: v for x, v in doc.items() if x != k}, tiers=TIERS)[0]]
    check(f"removing any one of the {len(T.REQUIRED_KEYS)} required keys raises CorpusSchemaError", not missing, str(missing))
    ok_m, msg_m = raises(T.CorpusSchemaError, T.replay, {x: v for x, v in doc.items() if x != "expect"}, tiers=TIERS)
    check("replay() of a document with a missing required key raises and names the key", ok_m and "'expect'" in msg_m, msg_m)

    def mutated(fn):
        d = copy.deepcopy(doc)
        fn(d)
        return d

    cases = {
        "unknown top-level key": lambda d: d.update(extra=1),
        "unknown action key": lambda d: d["actions"][0].update(when=1),
        "action without args": lambda d: d["actions"][0].pop("args"),
        "unknown anchor key": lambda d: d["source_anchors"][0].update(note="x"),
        "unknown expectation key": lambda d: d["expect"][0].update(why="x"),
        "seed is a bool": lambda d: d.update(seed=True),
        "seed < 0": lambda d: d.update(seed=-1),
        "synthetic is false": lambda d: d.update(synthetic=False),
        "utc_start not strict ISO Z": lambda d: d.update(utc_start="2026-10-25 00:30:00"),
        "trace_digest uppercase": lambda d: d.update(trace_digest=d["trace_digest"].upper()),
        "source digest not sha256": lambda d: d["source_digests"].update({ANCHOR_PATH: "abc"}),
        "source_digests empty": lambda d: d.update(source_digests={}),
        "anchor path absolute": lambda d: d["source_anchors"][0].update(path="/etc/x"),
        "anchor path with a backslash": lambda d: d["source_anchors"][0].update(path="docs\\dev\\x.md"),
        "anchor path with ..": lambda d: d["source_anchors"][0].update(path="../x.md"),
        "anchor path without a digest": lambda d: d["source_anchors"][0].update(path="docs/dev/other.md"),
        "anchor line 0": lambda d: d["source_anchors"][0].update(line_at_record=0),
        "source_anchors empty": lambda d: d.update(source_anchors=[]),
        "at_s decreasing": lambda d: d["actions"][3].update(at_s=10),
        "at_s negative": lambda d: d["actions"][0].update(at_s=-1),
        "at_s a bool": lambda d: d["actions"][0].update(at_s=False),
        "bad action name": lambda d: d["actions"][0].update(do="Inc!"),
        "unknown op": lambda d: d["expect"][0].update(op="=~"),
        "expectation value not JSON": lambda d: d["expect"][0].update(value={1, 2}),
        "expect empty": lambda d: d.update(expect=[]),
        "classification unknown risk": lambda d: d.update(classification="FINDING-KNOWN:NOPE"),
        "grade outside the vocabulary": lambda d: d.update(grade="CONFIRMED"),
        "confidence upper case": lambda d: d.update(confidence="HIGH"),
        "invariant lower case": lambda d: d.update(invariant="inv-x"),
        "id lower case": lambda d: d.update(id="st-00-a"),
        "world key reserved (seed)": lambda d: d["world"].update(seed=1),
        "world not an object": lambda d: d.update(world=[1]),
        "scenario_priority P4": lambda d: d.update(scenario_priority="P4", finding_priority=None),
        "finding_priority P4": lambda d: d.update(scenario_priority="P1", finding_priority="P4"),
        "scenario_priority without finding_priority": lambda d: d.update(scenario_priority="P1"),
        "the V0 key 'priority' (renamed scenario_priority in V0.1)": lambda d: d.update(priority="P1"),
        "notes not a string": lambda d: d.update(notes=5),
        "tier not allowed": lambda d: d.update(tier="nosuch"),
        "schema version": lambda d: d.update(schema="ecco-assurance-lab-replay/v1"),
        "empty failure_outcome": lambda d: d.update(failure_outcome=" "),
    }
    not_raised = [label for label, fn in cases.items() if not raises(T.CorpusSchemaError, T.validate_doc, mutated(fn),
                                                                       tiers=TIERS)[0]]
    check(f"all {len(cases)} schema violations raise CorpusSchemaError", not not_raised, str(not_raised))
    ok_opt = (T.validate_doc(mutated(lambda d: d.update(scenario_priority="P1", finding_priority=None, notes="synthetic")),
                             tiers=TIERS)["scenario_priority"] == "P1"
              and T.validate_doc(mutated(lambda d: d.update(scenario_priority="P2", finding_priority="P3")),
                                 tiers=TIERS)["finding_priority"] == "P3")
    check("the optional keys scenario_priority / finding_priority (null allowed) / notes are accepted", ok_opt)
    check("validate_doc with the default tiers refuses the in-test tier only when told to",
          raises(T.CorpusSchemaError, T.validate_doc, doc, tiers=T.TIERS)[0] and T.validate_doc(doc) is doc)

    print("  -- drift rule")
    dr = copy.deepcopy(doc)
    dr["source_digests"][ANCHOR_PATH] = "f" * 64
    dr["trace_digest"] = "0" * 64
    r3, out3 = _quiet_replay(dr, tiers=TIERS)
    check("a source digest mismatch sets drift=True, prints SOURCE DRIFT and judges by expectations only (ok)",
          r3.drift and r3.ok and r3.drifted_paths == (ANCHOR_PATH,) and not r3.digest_mismatch
          and out3 == f"SOURCE DRIFT: {ANCHOR_PATH}\n", repr(out3))
    print(f"  info  captured: {out3.strip()}")
    dr2 = copy.deepcopy(dr)
    dr2["expect"][0]["value"] = 99
    check("drift does not hide a failing expectation", not _quiet_replay(dr2, tiers=TIERS)[0].ok)
    gone = copy.deepcopy(doc)
    gone["source_digests"]["docs/dev/no-such-file-for-lab-selftest.md"] = "a" * 64
    r4, out4 = _quiet_replay(gone, tiers=TIERS)
    check("a source file that no longer exists is drift too", r4.drift and r4.ok and "no-such-file-for-lab-selftest" in out4)
    nd = copy.deepcopy(doc)
    nd["trace_digest"] = "0" * 64
    r5, out5 = _quiet_replay(nd, tiers=TIERS)
    check("negative control: sources unchanged but the replay digest differs from trace_digest -> FAIL (digest_mismatch)",
          not r5.ok and r5.digest_mismatch and not r5.drift and not r5.failed_expectations and out5 == "")
    mv = copy.deepcopy(doc)
    mv["source_anchors"][0]["line_at_record"] = 1
    r6 = _quiet_replay(mv, tiers=TIERS)[0]
    check("an anchor not at its recorded line without source drift -> FAIL (anchor_problems)",
          not r6.ok and not r6.drift and len(r6.anchor_problems) == 1)

    print("  -- record() negative controls")
    bad_exp = copy.deepcopy(DRAFT)
    bad_exp["expect"][0]["value"] = 5
    check("record() refuses a draft whose expectations do not hold", raises(T.LabTraceError, T.record, bad_exp, tiers=TIERS)[0])
    nondet = copy.deepcopy(DRAFT)
    nondet["actions"].append({"at_s": 130, "do": "nondet", "args": {}})
    ok_nd, msg_nd = raises(T.LabTraceError, T.record, nondet, tiers=TIERS)
    check("negative control: record() catches a non-deterministic world (two digests differ)",
          ok_nd and "different digests" in msg_nd, msg_nd)
    # V0.1 (B1): the repeated text is taken from a lab file (pinned exactly), not counted in the non-behavioural doc
    twice = copy.deepcopy(DRAFT)
    twice["source_anchors"][0].update(path=TWICE_PATH, text=TWICE_TEXT)
    check("record() refuses an anchor that does not occur exactly once (a text repeated in a lab file)",
          T.anchor_count(TWICE_PATH, TWICE_TEXT)[0] > 1 and raises(T.AnchorError, T.record, twice, tiers=TIERS)[0])
    check("re-registering a different function under a taken name raises; the same function is a no-op",
          raises(T.ReplayDispatchError, T.register_actions, TIER, {"inc": lambda w: None})[0]
          and T.register_actions(TIER, {"inc": act_inc}) is None)


# =============================================================================================================================
# [11] ddmin
# =============================================================================================================================
def _counted(pred):
    calls = []

    def f(sub):
        calls.append(tuple(sub) if all(isinstance(x, (int, str)) for x in sub) else len(sub))
        return pred(sub)
    return f, calls


def section_ddmin(doc_actions_pred) -> None:
    print("[11] ddmin")
    items = list(range(20))
    p1, c1 = _counted(lambda s: {3, 7, 11} <= set(s))
    p2, c2 = _counted(lambda s: {3, 7, 11} <= set(s))
    m1, m2 = T.ddmin(items, p1), T.ddmin(items, p2)
    check("ddmin finds the known minimal failing subset [3, 7, 11]", m1 == [3, 7, 11], str(m1))
    check("ddmin is deterministic (same result, same predicate call sequence)", m1 == m2 and c1 == c2 and len(c1) > 0)
    check("the result is 1-minimal (removing any element passes)",
          all(not ({3, 7, 11} <= set(m1[:i] + m1[i + 1:])) for i in range(len(m1))))
    check("a single culprit shrinks to it", T.ddmin(items, lambda s: 5 in s) == [5])
    seq = "x a y b a".split()

    def ordered(s):
        return "a" in s and "b" in s[s.index("a"):]
    m3 = T.ddmin(seq, ordered)
    check("order is preserved (subsequence 'a' before 'b')", m3 == ["a", "b"] and T.ddmin(seq, ordered) == m3, str(m3))
    check("an always-failing predicate shrinks to []", T.ddmin(items, lambda s: True) == [])
    check("the full input must fail; a non-bool predicate result and an exceeded budget raise LabTraceError",
          raises(T.LabTraceError, T.ddmin, items, lambda s: False)[0]
          and raises(T.LabTraceError, T.ddmin, items, lambda s: 1)[0]
          and raises(T.LabTraceError, T.ddmin, items, lambda s: {3, 7, 11} <= set(s), max_tests=3)[0])
    rng = random.Random(20261025)
    acts = [{"at_s": 10 * i, "do": "inc", "args": {"n": rng.choice([0, 0, 1, 2])}} for i in range(16)]
    full_fails = doc_actions_pred(acts)
    shrunk = T.ddmin(acts, doc_actions_pred) if full_fails else []
    again = T.ddmin(acts, doc_actions_pred) if full_fails else []
    one_min = full_fails and all(not doc_actions_pred(shrunk[:i] + shrunk[i + 1:]) for i in range(len(shrunk)))
    ns = [a["args"]["n"] for a in shrunk]
    check("ddmin shrinks a failing seeded replay sequence (count <= 5) to a 1-minimal, deterministic, still-failing list",
          full_fails and doc_actions_pred(shrunk) and one_min and shrunk == again and 0 not in ns and sum(ns) >= 5
          and len(shrunk) < len(acts), f"{len(acts)} -> {ns}")


B1_FW = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
B1_LAB_PIN = "registry/tests/assurance_lab/_lab_clock.py"     # a lab file (the record(tier_pins=True) control pins it)


def section_tiers() -> None:
    print("[11b] B1 source tiers and the tiered drift rule (_lab_trace; the end-to-end controls run in "
          "test_lab_replay_corpus [5])")
    reader = T.TreeReader()
    probs = T.tier_table_problems(T.pinned_by_table(), exists=reader.exists)
    check("tier table: consistent against the files it requires pinned (tiers disjoint, no lab path, every listed file "
          "exists with its evidence, TIER_SOURCES inside the behavioural tier and covering exactly the replay tiers)",
          probs == [], "; ".join(probs[:3]))
    nb_decided = ["firmware/include/ecco_rtc_policy.h", "frontend/ecco-energy-actions-card/src/dumpState.ts",
                  "frontend/ecco-energy-actions-card/src/recoveryPresentation.ts",
                  "frontend/ecco-energy-actions-card/src/schedule.ts", "home-assistant/packages/ecco_system_health.yaml",
                  "registry/health_reason_codes.yaml", "registry/system_health_checks.yaml", S4_DOC, ANCHOR_PATH,
                  "CHANGELOG.md", "SAFETY.md"]
    beh_decided = [B1_FW, "firmware/include/ecco_durable_snapshot.h", "registry/rtc_policy.py",
                   "home-assistant/packages/ecco_free_power_schedule.yaml", "home-assistant/packages/ecco_runtime_config.yaml",
                   "registry/tests/_fbd1_harness.py", "tools/fbd1_soak/timeutil.py"]
    check("tier table: the traced classifications this suite relies on (the anchor-only files, among them the V0.1 "
          "decision D-B1 files and this suite's S4 / SMR1 anchors, are non-behavioural and pinned; the executed firmware, "
          "header, packages, simulators and the rtc_policy mirror are behavioural)",
          all(T.source_tier(p) == "non-behavioural" and T.NON_BEHAVIOURAL[p][0] for p in nb_decided)
          and all(T.source_tier(p) == "behavioural" for p in beh_decided)
          and T.source_tier(T.LAB_PREFIX + "x.py") == "lab" and T.source_tier("no/such/file.md") == "unclassified")
    imported = [p for p in T.imported_repo_files() if not T.is_lab_path(p)]
    stray = T.unclassified_imports()
    saved_b = dict(T.BEHAVIOURAL)
    try:
        del T.BEHAVIOURAL["tools/fbd1_soak/timeutil.py"]
        planted = T.unclassified_imports()
    finally:
        T.BEHAVIOURAL.clear()
        T.BEHAVIOURAL.update(saved_b)
    check(f"run-time import guard: every repository module this suite imported outside the lab ({len(imported)}) is "
          "behavioural; with tools/fbd1_soak/timeutil.py removed from the table it is reported (table restored)",
          not stray and "tools/fbd1_soak/timeutil.py" in imported and planted == ["tools/fbd1_soak/timeutil.py"]
          and T.unclassified_imports() == [], f"{stray} {planted}")
    rtc, fw, cp = (set(T.TIER_SOURCES[t]) for t in ("rtc", "firmware", "coupled"))
    check("TIER_SOURCES: rtc < firmware < coupled; the firmware tier adds the durable header and the SG-01 recovery "
          "harness, the coupled tier the four packages and the two HA simulators",
          rtc < fw < cp and B1_FW in rtc and "firmware/include/ecco_durable_snapshot.h" in fw - rtc
          and len(cp - fw) == 6 and all(p.startswith("home-assistant/") for p in cp - fw),
          f"{len(rtc)} / {len(fw)} / {len(cp)}")
    # negative controls of the table checks (the table is restored afterwards)
    saved = (dict(T.BEHAVIOURAL), dict(T.NON_BEHAVIOURAL), dict(T.TIER_SOURCES))
    caught = {}
    try:
        T.NON_BEHAVIOURAL[B1_FW] = (True, "planted")
        caught["a file in both tiers"] = any("in both tiers" in p for p in T.tier_table_problems(T.pinned_by_table()))
        T.NON_BEHAVIOURAL.clear()
        T.NON_BEHAVIOURAL.update(saved[1])
        T.TIER_SOURCES["rtc"] = tuple(sorted(T.TIER_SOURCES["rtc"] + ("CHANGELOG.md",)))
        caught["a tier source outside the behavioural tier"] = any(
            "not a subset" in p for p in T.tier_table_problems(T.pinned_by_table()))
        T.TIER_SOURCES["rtc"] = saved[2]["rtc"]
        caught["a pinned file in neither tier"] = any(
            "neither tier" in p for p in T.tier_table_problems(T.pinned_by_table() + ["docs/unclassified.md"]))
        caught["an existence-only file that is pinned"] = any(
            "marked unpinned" in p for p in T.tier_table_problems(T.pinned_by_table() + ["registry/tests/test_dump_safety_fcp2.py"]))
        caught["a behavioural file left unpinned"] = any(
            "not pinned in baseline.sources" in p for p in T.tier_table_problems(
                [p for p in T.pinned_by_table() if p != "registry/rtc_policy.py"]))
    finally:
        for live, old in zip((T.BEHAVIOURAL, T.NON_BEHAVIOURAL, T.TIER_SOURCES), saved):
            live.clear()
            live.update(old)
    check("tier table negative controls: " + "; ".join(caught) + " are each reported (table restored)",
          all(caught.values()) and len(caught) == 5 and T.tier_table_problems(T.pinned_by_table()) == [], str(caught))
    # the drift function on synthetic baselines (no file is read: sha_of is a stub)
    docs = {"FW-90-a": {"tier": "firmware", "source_digests": {B1_FW: "1" * 64}},
            "HF-90-a": {"tier": "coupled", "source_digests": {ANCHOR_PATH: "2" * 64}},
            "RT-90-a": {"tier": "rtc", "source_digests": {B1_LAB_PIN: "3" * 64}}}
    pinned = {B1_LAB_PIN: "3" * 64, B1_FW: "1" * 64, "registry/rtc_policy.py": "4" * 64, "CHANGELOG.md": "5" * 64,
              ANCHOR_PATH: "2" * 64, "home-assistant/packages/ecco_runtime_config.yaml": "6" * 64, "docs/unclassified.md": "7" * 64}
    now = dict(pinned, **{B1_LAB_PIN: "a" * 64, "registry/rtc_policy.py": "b" * 64, "CHANGELOG.md": "c" * 64,
                          "home-assistant/packages/ecco_runtime_config.yaml": "d" * 64, "docs/unclassified.md": None})
    rep = T.drift_report(pinned, docs, sha_of=now.get)
    titles = [t for t, _d in rep.failures()]
    details = dict(rep.failures())
    check("drift_report (tiered): a changed lab file -> 're-generate the catalogue: lab file changed' naming the documents "
          "that still record its old digest; a changed behavioural file -> one 'behavioural source changed' failure per file listing every "
          "document whose effective pins (own source_digests plus its tier's TIER_SOURCES) include it and the re-record "
          "procedure; a changed non-behavioural file -> only a 'SOURCE DRIFT (non-behavioural): <path>' line; a changed "
          "unclassified file -> a failure; unchanged files -> nothing",
          titles == ["unclassified pinned source changed: docs/unclassified.md",
                     "behavioural source changed: home-assistant/packages/ecco_runtime_config.yaml",
                     "behavioural source changed: registry/rtc_policy.py",
                     "re-generate the catalogue: lab file changed: " + B1_LAB_PIN]
          and rep.drift_lines() == [T.DRIFT_LINE + "CHANGELOG.md"]
          and "sha256 missing != recorded 7777" in details[titles[0]]
          and "1 corpus document(s) replay it (HF-90-a)" in details[titles[1]]
          and f"{T.RERECORD_CMD} HF-90-a (" in details[titles[1]]
          and "3 corpus document(s) replay it (FW-90-a; HF-90-a; RT-90-a)" in details[titles[2]]
          and f"{T.RERECORD_CMD} --all" in details[titles[2]] and T.REGENERATE_CMD in details[titles[2]]
          and "1 corpus document(s) still record the old digest (RT-90-a)" in details[titles[3]]
          and [i.stale_documents for i in rep.items if i.tier == "lab"] == [("RT-90-a",)]
          and T.drift_report(pinned, docs, sha_of=pinned.get).items == (), f"{titles} {rep.drift_lines()}")
    strict = T.drift_report(pinned, docs, sha_of=now.get, strict=True)
    check("drift_report (STRICT, ECCO_LAB_STRICT_BASELINE=1): the non-behavioural change is a failure too and no SOURCE "
          "DRIFT line is printed",
          [t for t, _d in strict.failures()] == [
              "non-behavioural source changed (STRICT, ECCO_LAB_STRICT_BASELINE=1): CHANGELOG.md"] + titles
          and strict.drift_lines() == [] and len(strict.messages()) == 5, str([t for t, _d in strict.failures()]))
    check("compact_ids groups corpus ids by family; rerecord_procedure names the ids (--all above 12 or for every "
          "document) or, for no document, the lab run and the regeneration",
          T.compact_ids(["FW-01-b", "FW-01-a", "FW-09-b2", "HF-07-a"]) == "FW-01-a,b; FW-09-b2; HF-07-a"
          and T.compact_ids([]) == "none" and f"{T.RERECORD_CMD} A-01-a B-01-a (" in T.rerecord_procedure(["B-01-a", "A-01-a"], 9)
          and f"{T.RERECORD_CMD} --all" in T.rerecord_procedure([f"X-{i:02d}-a" for i in range(13)], 97)
          and "run_lab.py" in T.rerecord_procedure([], 97))
    # TreeReader overlays (nothing is written; the edited file is a lab file, so no non-lab content is read here)
    on_disk = T.source_digest(B1_LAB_PIN)
    ov = T.TreeReader(overlay={B1_LAB_PIN: reader.read_bytes(B1_LAB_PIN) + b"# x\n", "docs/gone.md": None})
    check("TreeReader: an overlay edits the tree in memory (another digest, the appended text, an overlaid absent file "
          "reads as missing); the file on disk is unchanged; CRLF bytes digest like LF",
          ov.sha(B1_LAB_PIN) != on_disk and ov.text(B1_LAB_PIN).endswith("# x\n")
          and reader.sha(B1_LAB_PIN) == on_disk and T.source_digest(B1_LAB_PIN) == on_disk
          and not ov.exists("docs/gone.md") and ov.read_bytes("docs/gone.md") is None and ov.exists(ANCHOR_PATH)
          and T.TreeReader(overlay={"a.md": b"x\r\ny\n"}).sha("a.md") == T.TreeReader(overlay={"a.md": b"x\ny\n"}).sha("a.md"))
    # record(tier_pins=True) pins the tier's TIER_SOURCES (rerecord_corpus.py --pin-tier-sources); the default does not
    T.TIER_SOURCES[TIER] = (B1_LAB_PIN,)
    try:
        pinned_doc = T.record(DRAFT, tiers=TIERS, tier_pins=True)
        plain_doc = T.record(DRAFT, tiers=TIERS)
    finally:
        T.TIER_SOURCES.pop(TIER, None)
    check("record(tier_pins=True) adds the document tier's TIER_SOURCES to source_digests (same trace digest); the "
          "default record() pins only the draft's own keys and anchor paths",
          sorted(pinned_doc["source_digests"]) == sorted([ANCHOR_PATH, B1_LAB_PIN])
          and pinned_doc["source_digests"][B1_LAB_PIN] == T.source_digest(B1_LAB_PIN)
          and sorted(plain_doc["source_digests"]) == [ANCHOR_PATH]
          and pinned_doc["trace_digest"] == plain_doc["trace_digest"] and TIER not in T.TIER_SOURCES)
    check("effective_pins / affected_documents: a document is judged against its own pins plus its tier's TIER_SOURCES",
          T.effective_pins(docs["HF-90-a"]) == sorted({ANCHOR_PATH} | set(T.TIER_SOURCES["coupled"]))
          and T.affected_documents(B1_FW, docs) == ["FW-90-a", "HF-90-a", "RT-90-a"]
          and T.affected_documents("home-assistant/packages/ecco_runtime_config.yaml", docs) == ["HF-90-a"]
          and T.affected_documents("CHANGELOG.md", docs) == [])


def _shrink_pred_factory():
    base = copy.deepcopy(DRAFT)
    base["actions"] = []
    base["expect"] = [{"observe": "count", "args": {}, "op": "<=", "value": 5}]
    doc = T.record(base, tiers=TIERS)

    def still_fails(acts) -> bool:
        d = copy.deepcopy(doc)
        d["actions"] = copy.deepcopy(acts)
        return bool(_quiet_replay(d, tiers=TIERS)[0].failed_expectations)
    return still_fails


def _finish_out(**kw) -> tuple[list[str], dict | None, str]:
    """(printed lines, returned record or None, LabTraceError text or '') of one T.finish call, stdout captured."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rec = T.finish(**kw)
        err = ""
    except T.LabTraceError as exc:      # the expected outcome of the misuse controls below
        rec, err = None, str(exc)
    return buf.getvalue().splitlines(), rec, err


def _finish_args(**over) -> dict:
    kw = {"suite": "x", "passes": ["a", "b", "c"], "failures": ["f 1"], "finding": {"F-X01-1", "F-X01-2"},
          "finding_pins": ["finding-reproduces:F-X01-1"], "unsupported_points": ["X-01-U1", "X-01-U1", "X-01-U2"],
          "blocked": [], "phase_sensitive": ["timing check"], "runtime_s": 1.23456}
    kw.update(over)
    return kw


V01_KEYS = ["suite", "pass", "fail", "finding", "finding_pins", "unsupported_ids", "unsupported_points", "blocked",
            "zoneinfo", "phase_sensitive", "runtime_s"]


def section_summary_helpers() -> None:
    print("[12] suite output helpers (the V0.1 suite output contract: finish, failed_line, unsupported_line, finding_line)")
    zi = C.zoneinfo_available()
    lines, rec, err = _finish_out(**_finish_args())
    want = ('LAB-SUMMARY {"suite": "x", "pass": 3, "fail": 1, "finding": 2, "finding_pins": 1, "unsupported_ids": 2, '
            f'"unsupported_points": 3, "blocked": 0, "zoneinfo": {"true" if zi else "false"}, "phase_sensitive": 1, '
            '"runtime_s": 1.235}')
    check("finish prints 'FAILED: 1 check(s): f 1' and then LAB-SUMMARY with the V0.1 keys in order and DETECTED counts "
          "(pass = held checks without pins; unsupported_ids = distinct ids of the points; zoneinfo = "
          "_lab_clock.zoneinfo_available(); runtime rounded to 3 dp)",
          not err and lines == ["FAILED: 1 check(s): f 1", want] and list(T.SUMMARY_KEYS) == V01_KEYS
          and rec is not None and list(rec) == V01_KEYS and rec["zoneinfo"] is zi, f"{lines} {err}")
    lines, _rec, err = _finish_out(**_finish_args(failures=[]))
    check("finish without a failure prints exactly one line, LAB-SUMMARY (no FAILED line)",
          not err and len(lines) == 1 and lines[0].startswith('LAB-SUMMARY {"suite": "x", "pass": 3, "fail": 0,'), str(lines))
    misuse = {
        "a finding pin among passes": _finish_args(passes=["a", "finding-reproduces:F-X01-1"]),
        "a non-pin name among finding_pins": _finish_args(finding_pins=["a"]),
        "a literal int count (finding=2)": _finish_args(finding=2),
        "a str as a collection (blocked='B')": _finish_args(blocked="B"),
        "a set of unsupported points (multiplicity lost)": _finish_args(unsupported_points={"X-01-U1"}),
        "an unsupported id with whitespace": _finish_args(unsupported_points=["X-01 U1"]),
        "a negative runtime": _finish_args(runtime_s=-1.0),
        "a bool runtime": _finish_args(runtime_s=True),
        "a NaN runtime": _finish_args(runtime_s=float("nan")),
    }
    res = {k: _finish_out(**v) for k, v in misuse.items()}
    check("finish refuses every misuse with LabTraceError and prints nothing: " + "; ".join(misuse),
          all(err and not lines for lines, _r, err in res.values()),
          str({k: (v[0][:1], v[2][:60]) for k, v in res.items() if not v[2] or v[0]}))
    names = [f"check {i:03d} " + "x" * 20 for i in range(300)]
    fl = T.failed_line(names)
    shown = fl[len("FAILED: 300 check(s): "):fl.rindex(" ... (+")].split("; ")
    k_more = int(fl[fl.rindex("(+") + 2:-len(" more)")])
    check("failed_line: 300 long names are cut at a name boundary to at most 4000 characters, ending ' ... (+k more)' "
          "with k = the names not shown",
          len(fl) <= T.FAILED_LINE_MAX == 4000 and fl.startswith("FAILED: 300 check(s): check 000 ")
          and shown == names[:len(shown)] and k_more == 300 - len(shown) and len(shown) > 50, fl[-60:])
    one = T.failed_line(["y" * 5000])
    fit = T.failed_line(["z" * (4000 - len("FAILED: 1 check(s): "))])
    check("failed_line: a single over-long name is cut to the limit; a line of exactly 4000 characters is not cut; "
          "whitespace inside a name is collapsed; no name at all raises",
          len(one) == 4000 and one.endswith(" ... (+0 more)") and len(fit) == 4000 and "..." not in fit
          and T.failed_line(["a\n  b", "c"]) == "FAILED: 2 check(s): a b; c"
          and raises(T.LabTraceError, T.failed_line, [])[0])
    check("unsupported_line is one line '  UNSUPPORTED  <id> <text>'; an id with whitespace or an empty id raises",
          T.unsupported_line("HF-03-UNS-1", "two\nlines  here") == "  UNSUPPORTED  HF-03-UNS-1 two lines here"
          and T.unsupported_line("FW-07-U1", " ") == "  UNSUPPORTED  FW-07-U1"
          and raises(T.LabTraceError, T.unsupported_line, "HF 03", "x")[0]
          and raises(T.LabTraceError, T.unsupported_line, "", "x")[0])
    check("finding_line is one line", T.finding_line("FW-01-a", "two\nlines  here") == "  FINDING  FW-01-a two lines here")
    check("summary_line is gone (the V0 LAB-SUMMARY writer; finish() replaces it)", not hasattr(T, "summary_line"))
    try:
        import zoneinfo as _zi
        _zi.ZoneInfo("Europe/London")
        independent = True
    except Exception:     # noqa: BLE001 - the independent probe: any failure means "not usable" (compared below)
        independent = False
    check("_lab_clock.zoneinfo_available() is a bool, stable within the process and equal to an independent probe "
          f"(this process: {'usable' if zi else 'NOT usable'})",
          isinstance(zi, bool) and C.zoneinfo_available() is zi and zi == independent and (ZL is not None) == zi)


# =============================================================================================================================
# [13] bytecode guard (B7.5): every lab suite and command-line tool sets sys.dont_write_bytecode before a non-stdlib import
# =============================================================================================================================
STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def _is_guard(stmt: ast.stmt) -> bool:
    t = stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
    return (isinstance(t, ast.Attribute) and t.attr == "dont_write_bytecode" and isinstance(t.value, ast.Name)
            and t.value.id == "sys" and isinstance(stmt.value, ast.Constant) and stmt.value.value is True)


def bytecode_guard_problems(source: str) -> list[str]:
    """[] when a MODULE-LEVEL 'sys.dont_write_bytecode = True' comes before every import of a non-stdlib module (any
    import nested anywhere in an earlier module-level statement counts; relative imports are non-stdlib)."""
    tree = ast.parse(source)
    at = next((i for i, s in enumerate(tree.body) if _is_guard(s)), None)
    if at is None:
        return ["no module-level 'sys.dont_write_bytecode = True'"]
    out = []
    for stmt in tree.body[:at]:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Import):
                mods = [(a.name, 0) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [(node.module or "", node.level)]
            else:
                continue
            for mod, level in mods:
                if level or mod.split(".")[0] not in STDLIB:
                    out.append(f"line {node.lineno}: {'.' * level}{mod} is imported before the guard")
    return out


def section_bytecode_guard() -> None:
    print("[13] bytecode guard: sys.dont_write_bytecode = True at module level before the first non-stdlib import")
    check("the interpreter lists its standard-library modules (sys.stdlib_module_names)", len(STDLIB) > 100
          and {"sys", "pathlib", "zoneinfo", "ast"} <= STDLIB and "yaml" not in STDLIB, str(len(STDLIB)))
    files = sorted(HERE.glob("test_lab_*.py")) + [HERE / n for n in ("run_lab.py", "gen_catalogue.py",
                                                                       "rerecord_corpus.py")]
    bad = {f.name: p for f in files if (p := bytecode_guard_problems(f.read_bytes().decode("utf-8")))}
    suites = [f for f in files if f.name.startswith("test_lab_")]
    check(f"every lab suite ({len(suites)} test_lab_*.py) and command-line tool (run_lab, gen_catalogue, rerecord_corpus) "
          "sets sys.dont_write_bytecode = True at module level before its first non-stdlib import, so a CI-style "
          "'python <file>' run (no -B) writes no bytecode into the tree", len(suites) >= 13 and not bad, str(bad)[:300])
    good = "import sys\nsys.dont_write_bytecode = True\nimport yaml\nimport _lab_trace\n"
    controls = {
        "the guard after a non-stdlib import": "import sys\nimport yaml\nsys.dont_write_bytecode = True\n",
        "a lab helper imported before the guard": ("from __future__ import annotations\nimport sys\nimport _lab_trace\n"
                                                  "sys.dont_write_bytecode = True\n"),
        "a relative import before the guard": "import sys\nfrom . import x\nsys.dont_write_bytecode = True\n",
        "a non-stdlib import nested in an earlier statement": ("import sys\ntry:\n    import yaml\nexcept ImportError:\n"
                                                               "    yaml = None\nsys.dont_write_bytecode = True\n"),
        "the guard only inside an if": "import sys\nif True:\n    sys.dont_write_bytecode = True\nimport yaml\n",
        "the guard set to False": "import sys\nsys.dont_write_bytecode = False\nimport yaml\n",
        "no guard at all": "import sys\nimport yaml\n",
    }
    caught = {k: bool(bytecode_guard_problems(v)) for k, v in controls.items()}
    check("bytecode guard negative controls: a well-guarded synthetic source passes (stdlib and __future__ imports before "
          "the guard are fine); each misplaced, missing or wrong guard is caught: " + "; ".join(controls),
          not bytecode_guard_problems(good) and not bytecode_guard_problems(
              "from __future__ import annotations\nimport sys\nfrom pathlib import Path\nsys.dont_write_bytecode = True\n")
          and all(caught.values()), str(caught))


# =============================================================================================================================
# run
# =============================================================================================================================
section_clock_basics()
section_sweeps()
section_transitions()
section_ha_local()
section_canonical()
section_eventlog()
section_known_risks()
section_known_risk_corrections()
section_vocab()
section_ops()
T.register_tier(TIER, DummyWorld)
T.register_actions(TIER, {"inc": act_inc, "status": act_status, "run_for": act_run_for, "boom": act_boom, "nondet": act_nondet})
T.register_observers(TIER, {"count": lambda w: w.count, "status": lambda w: w.status, "impure": obs_impure})
try:
    section_replay()
    section_ddmin(_shrink_pred_factory())
    section_tiers()
finally:
    T.unregister_tier(TIER)
check("the in-test tier is unregistered again (no process-global leftover)", not T.registered(TIER)["factory"])
section_summary_helpers()
section_bytecode_guard()
check("S.LOCAL is the module's original fixed UTC+1 zone at the end", S.LOCAL.utcoffset(None) == timedelta(hours=1))
if ZONEINFO_SKIPPED:
    print(f"  info  zoneinfo unavailable: {len(ZONEINFO_SKIPPED)} zoneinfo cross-check(s) SKIPPED in all (not PASS, not "
          "counted); LAB-SUMMARY zoneinfo false")

RUNTIME_S = time.perf_counter() - T0
print("")
check_phase_registry()
T.finish("test_lab_selftest_core", passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=PINS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
