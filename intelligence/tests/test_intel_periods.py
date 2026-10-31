#!/usr/bin/env python3
"""Intelligence foundation: intelligence/periods.py, the one measure of a local wall-clock window across UK clock changes.

  [1] the 25 h autumn day (25 Oct 2026) and the 23 h spring day (28 Mar 2027); 00:30-05:30 lasts 6 h / 4 h
  [2] 22:00-06:00 lasts 9 h across the autumn change and 7 h across the spring change
  [3] boundaries in the repeated hour are AMBIGUOUS, in the skipped hour NONEXISTENT
  [4] a window with no real length (the spring gap) or wholly inside the gap is refused (ValueError); malformed windows too
  [5] clock_changes finds exactly one long and one short Sunday per year 2026-2030, at 01:00 UTC
  [6] agreement with timeutil.local_wall (the engine's mapping) and purity (no clock read, no I/O)
Synthetic dates only; offline.
"""

from __future__ import annotations

import ast
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import periods as P  # noqa: E402
from intelligence.timeutil import UTC, local_wall, zone  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def refused(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


LON = "Europe/London"
AUT, SPR = date(2026, 10, 25), date(2027, 3, 28)

section("[1] the long and the short day")
pa = P.period_profile(AUT, 0, 1440)
ps = P.period_profile(SPR, 0, 1440)
check("2026-10-25 lasts 25 h (AUTUMN_BACK)", pa.actual_h == 25.0 and pa.nominal_h == 24.0 and pa.change_kind == P.AUTUMN_BACK, str(pa))
check("2027-03-28 lasts 23 h (SPRING_FORWARD)", ps.actual_h == 23.0 and ps.change_kind == P.SPRING_FORWARD, str(ps))
check("an ordinary day lasts 24 h with factor 1 and no change",
      P.period_profile(date(2026, 10, 20), 0, 1440).actual_h == 24.0 and P.period_profile(date(2026, 10, 20), 0, 1440).factor == 1.0
      and P.period_profile(date(2026, 10, 20), 0, 1440).change_kind == P.NONE)
w_a, w_s = P.period_profile(AUT, 30, 330), P.period_profile(SPR, 30, 330)
check("00:30-05:30 lasts 6 h on 25 Oct 2026 (factor 1.2)", w_a.actual_h == 6.0 and abs(w_a.factor - 1.2) < 1e-12, str(w_a))
check("00:30-05:30 lasts 4 h on 28 Mar 2027 (factor 0.8)", w_s.actual_h == 4.0 and abs(w_s.factor - 0.8) < 1e-12, str(w_s))
check("the evening before each change is an ordinary 5 h window",
      P.period_profile(date(2026, 10, 24), 30, 330).actual_h == 5.0 and P.period_profile(date(2027, 3, 27), 30, 330).actual_h == 5.0)
check("a window after the change on the same day is unchanged (02:00-05:00 on both days)",
      P.period_profile(AUT, 120, 300).change_kind == P.NONE and P.period_profile(SPR, 120, 300).change_kind == P.NONE)

section("[2] evening-to-morning windows")
check("22:00 (24 Oct 2026) - 06:00 lasts 9 h", P.period_profile(date(2026, 10, 24), 22 * 60, 30 * 60).actual_h == 9.0)
check("22:00 (27 Mar 2027) - 06:00 lasts 7 h", P.period_profile(date(2027, 3, 27), 22 * 60, 30 * 60).actual_h == 7.0)
check("22:00 (25 Oct 2026) - 06:00 starts after the change: 8 h", P.period_profile(AUT, 22 * 60, 30 * 60).actual_h == 8.0)

section("[3] boundary classification")
check("01:00 and 01:30 on 25 Oct 2026 are AMBIGUOUS (the repeated hour)",
      P.boundary_kind(AUT, 60) == P.AMBIGUOUS and P.boundary_kind(AUT, 90) == P.AMBIGUOUS)
check("02:00 on 25 Oct 2026 and 00:59 are OK", P.boundary_kind(AUT, 120) == P.OK and P.boundary_kind(AUT, 59) == P.OK)
check("01:00 and 01:30 on 28 Mar 2027 are NONEXISTENT (the skipped hour)",
      P.boundary_kind(SPR, 60) == P.NONEXISTENT and P.boundary_kind(SPR, 90) == P.NONEXISTENT)
check("02:00 on 28 Mar 2027 is OK", P.boundary_kind(SPR, 120) == P.OK)
amb = P.period_profile(AUT, 90, 300)
check("a window starting in the repeated hour is classified AMBIGUOUS at its start and flagged",
      amb.start_boundary == P.AMBIGUOUS and amb.end_boundary == P.OK and amb.boundary_in_changed_hour, str(amb))
ne = P.period_profile(SPR, 90, 300)
check("a window starting in the skipped hour is classified NONEXISTENT at its start and flagged",
      ne.start_boundary == P.NONEXISTENT and ne.boundary_in_changed_hour, str(ne))
check("an ordinary window has OK boundaries", not P.period_profile(AUT, 30, 330).boundary_in_changed_hour)
check("boundaries are classified on the next day too (end_min > 1440)",
      P.period_profile(date(2027, 3, 27), 22 * 60, 24 * 60 + 90).end_boundary == P.NONEXISTENT)

section("[4] refusals")
check("the spring-gap window 01:00-02:00 on 28 Mar 2027 is refused (no real length)", refused(lambda: P.period_profile(SPR, 60, 120)))
check("a window wholly inside the gap (01:15-01:45) is refused", refused(lambda: P.period_profile(SPR, 75, 105)))
check("01:30-02:30 on 28 Mar 2027 has no real length on the engine's mapping and is refused", refused(lambda: P.period_profile(SPR, 90, 150)))
check("a window that ends before it starts is refused", refused(lambda: P.period_profile(AUT, 330, 30)))
check("an empty window is refused", refused(lambda: P.period_profile(AUT, 30, 30)))
for bad in (1.5, True, "30", None):
    check(f"start_min {bad!r} is refused", refused(lambda b=bad: P.period_profile(AUT, b, 330)))
check("a datetime is not a date", refused(lambda: P.period_profile(datetime(2026, 10, 25, tzinfo=UTC), 30, 330)))
check("an unknown zone name is refused or raises", refused(lambda: P.period_profile(AUT, 30, 330, "")))
check("an unknown zone and out-of-range minutes raise ValueError, never another exception",
      refused(lambda: P.period_profile(AUT, 30, 330, "Nowhere/Zone")) and refused(lambda: P.period_profile(AUT, 0, 10 ** 12))
      and refused(lambda: P.period_profile(AUT, -(10 ** 12), 30)) and refused(lambda: P.clock_changes(AUT, date(2026, 11, 1), "Nowhere/Zone")))
end_gap = P.period_profile(SPR, 30, 90)
check("a window ending in the skipped hour (00:30-01:30 on 28 Mar 2027) keeps its 1 h length but is marked as crossing the "
      "change (SPRING_FORWARD, changed) and its end NONEXISTENT",
      end_gap.actual_h == 1.0 and end_gap.factor == 1.0 and end_gap.change_kind == P.SPRING_FORWARD and end_gap.changed
      and end_gap.end_boundary == P.NONEXISTENT, str(end_gap))
check("... while a window that starts exactly at the change instant does not cross it (02:00-05:00 on 28 Mar 2027)",
      P.period_profile(SPR, 120, 300).change_kind == P.NONE and P.period_profile(AUT, 70, 110).change_kind == P.NONE)
check("a factor of zero can never be produced: every accepted window has factor > 0",
      all(P.period_profile(d, s, s + 60).factor > 0 for d in (AUT, SPR) for s in range(0, 1440, 15)
          if not refused(lambda d=d, s=s: P.period_profile(d, s, s + 60))))

section("[5] clock_changes")
for year in range(2026, 2031):
    ch = P.clock_changes(date(year, 1, 1), date(year + 1, 1, 1))
    kinds = [c.kind for c in ch]
    check(f"{year}: one SPRING_FORWARD then one AUTUMN_BACK, both on Sundays at 01:00 UTC",
          kinds == [P.SPRING_FORWARD, P.AUTUMN_BACK] and all(c.local_day.weekday() == 6 for c in ch)
          and all(c.at_utc.hour == 1 and c.at_utc.minute == 0 for c in ch)
          and [c.delta_h for c in ch] == [1.0, -1.0], str(ch))
    long_days = [c.local_day for c in ch if c.kind == P.AUTUMN_BACK]
    short_days = [c.local_day for c in ch if c.kind == P.SPRING_FORWARD]
    check(f"{year}: the change days are the 25 h and 23 h days",
          P.period_profile(long_days[0], 0, 1440).actual_h == 25.0 and P.period_profile(short_days[0], 0, 1440).actual_h == 23.0)
check("2026-10-25 and 2027-03-28 are the changes", [c.local_day for c in P.clock_changes(date(2026, 10, 1), date(2027, 4, 1))]
      == [AUT, SPR])
check("a range without a change is empty", P.clock_changes(date(2026, 11, 1), date(2027, 3, 1)) == ())
at = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
check("the range is half-open: [at, ...) contains the change, [..., at) does not",
      len(P.clock_changes(at, at + timedelta(hours=1))) == 1 and P.clock_changes(at - timedelta(hours=1), at) == ())
check("an inverted range is empty", P.clock_changes(date(2027, 1, 1), date(2026, 1, 1)) == ())
check("a naive datetime is refused", refused(lambda: P.clock_changes(datetime(2026, 10, 1), datetime(2026, 11, 1))))
check("window_crosses_change: 22:00-06:00 across the autumn change crosses; the evening after does not",
      P.window_crosses_change(local_wall(date(2026, 10, 24), 1320, zone(LON)), local_wall(date(2026, 10, 24), 1800, zone(LON)))
      and not P.window_crosses_change(local_wall(AUT, 1320, zone(LON)), local_wall(AUT, 1800, zone(LON))))

section("[6] agreement with the engine's mapping; purity")
z = zone(LON)
agree = all(P.period_profile(d, s, s + 300).start_utc == local_wall(d, s, z) and P.period_profile(d, s, s + 300).end_utc == local_wall(d, s + 300, z)
            for d in (date(2026, 10, 24), AUT, date(2027, 3, 27), date(2030, 6, 1)) for s in (0, 30, 600, 1320))
check("start_utc / end_utc are exactly timeutil.local_wall's instants", agree)
check("to_dict is plain JSON data", isinstance(P.period_profile(AUT, 30, 330).to_dict()["start_utc"], str))
src = (Path(__file__).resolve().parents[1] / "periods.py").read_text(encoding="utf-8")
tree = ast.parse(src)
mods = sorted({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
              | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
check("periods.py imports only the standard library datetime/zoneinfo/dataclasses and timeutil",
      set(mods) <= {"__future__", "dataclasses", "datetime", "zoneinfo", "timeutil"}, str(mods))
calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
check("periods.py never reads the clock or opens a file", not [c for c in calls if c.endswith((".now", ".today", "time.time", "open"))], str(calls))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all periods checks passed")
