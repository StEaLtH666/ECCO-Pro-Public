#!/usr/bin/env python3
"""Offline tests: statistics helpers, local-time/DST handling, sun times, cumulative-counter conversion,
history quality flags, and the effective-minimum SOC rule. Pure and deterministic."""

from __future__ import annotations

from datetime import date, datetime

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")

from intelligence import stats
from intelligence.config import SiteConfig
from intelligence.history import (F_GAP_INTERP, F_RESET, F_SOC_JUMP, F_SOC_SUSPECT, F_STALL_REDIST, F_STALLED,
                                  HourRecord, History, build_history, counter_to_hourly, power_is_flat)
from intelligence.timeutil import HOUR, UTC, day_bounds, local_wall, sun_times, ts, zone

cfg = SiteConfig()
tz = zone("Europe/London")
H0 = ts(datetime(2026, 9, 1, 0, tzinfo=UTC))

section("statistics helpers")
check("median odd/even", stats.median([3, 1, 2]) == 2 and stats.median([1, 2, 3, 4]) == 2.5)
check("quantile interpolates", abs(stats.quantile([0, 10], 0.25) - 2.5) < 1e-9)
xs = [10.0] * 20
est, clipped = stats.robust_ewma(xs + [100.0], 0.3, 3.0, 28, 0.5)
plain = 10.0 + 0.3 * (100.0 - 10.0)
check("one abnormal value is winsorised, not absorbed", est < plain and clipped == 1, f"est={est} plain={plain}")
check("winsorised move is bounded by alpha*k*sigma_floor", est - 10.0 <= 0.3 * 3.0 * 0.5 + 1e-9, f"move={est - 10.0}")
est2, _ = stats.robust_ewma([10, 11, 9, 10, 10, 11, 9, 10, 12, 8], 0.3, 3.0, 28, 0.5)
check("normal data is not clipped", 9.0 < est2 < 11.0)
check("no outlier call with <5 reference points", stats.winsorise(99, [1, 2, 3], 3.0, 0.1) == (99, False))

section("local time and DST")
for d, hours in ((date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 6, 1), 24)):
    a, b = day_bounds(d, tz)
    check(f"{d} is {hours} h long", (b - a).total_seconds() / 3600 == hours)
check("00:30 local on a BST date is 23:30 UTC the day before",
      local_wall(date(2026, 10, 5), 30, tz) == datetime(2026, 10, 4, 23, 30, tzinfo=UTC))
check("00:30 local on a GMT date is 00:30 UTC",
      local_wall(date(2026, 11, 5), 30, tz) == datetime(2026, 11, 5, 0, 30, tzinfo=UTC))
sr, ss = sun_times(date(2026, 6, 21), 51.5, -0.1)
check("London midsummer sunrise ~04:43 local",
      abs((sr.astimezone(tz) - sr.astimezone(tz).replace(hour=4, minute=43, second=0)).total_seconds()) < 300)
check("London midsummer sunset ~21:21 local",
      abs((ss.astimezone(tz) - ss.astimezone(tz).replace(hour=21, minute=21, second=0)).total_seconds()) < 300)
sr, ss = sun_times(date(2026, 12, 21), 51.5, -0.1)
check("London midwinter day is ~7.8 h", abs((ss - sr).total_seconds() / 3600 - 7.8) < 0.3)
check("polar night returns None", sun_times(date(2026, 12, 21), 80.0, 0.0) == (None, None))

section("cumulative counters -> hourly energy")
states = {H0 + i * HOUR: 100.0 + i * 1.0 for i in range(6)}
e, f = counter_to_hourly(states, None, cfg)
check("consecutive hours: delta", all(abs(e[H0 + i * HOUR] - 1.0) < 1e-9 for i in range(1, 6)))
states = {H0: 100.0, H0 + 1 * HOUR: 101.0, H0 + 4 * HOUR: 104.5}
e, f = counter_to_hourly(states, None, cfg)
check("gap spread evenly and flagged",
      all(abs(e[H0 + k * HOUR] - 1.1666666) < 1e-3 and F_GAP_INTERP in f[H0 + k * HOUR] for k in (2, 3, 4)))
states = {H0: 100.0, H0 + 12 * HOUR: 112.0}
e, f = counter_to_hourly(states, None, cfg)
check("gap longer than the limit stays missing (no invented data)", not e)
states = {H0: 100.0, H0 + HOUR: 101.0, H0 + 2 * HOUR: 0.5, H0 + 3 * HOUR: 1.5}
e, f = counter_to_hourly(states, None, cfg)
check("counter reset -> hour missing and flagged, never negative energy",
      (H0 + 2 * HOUR) not in e and F_RESET in f[H0 + 2 * HOUR] and all(v >= 0 for v in e.values()))
states = {H0: 100.0, H0 + HOUR: 99.95, H0 + 2 * HOUR: 101.0}
e, f = counter_to_hourly(states, None, cfg)
check("a tiny backwards counter wobble never yields negative energy", e[H0 + HOUR] == 0.0 and all(v >= 0 for v in e.values()), str(e))
states = {H0 + i * HOUR: v for i, v in enumerate([100.0, 101.2, 101.2, 101.2, 104.8, 106.0])}
power = {H0 + i * HOUR: 1200.0 for i in range(6)}
e, f = counter_to_hourly(states, power, cfg)
share = (104.8 - 101.2) / 3
check("stalled run re-spread with the catch-up hour",
      all(abs(e[H0 + k * HOUR] - share) < 1e-6 and F_STALL_REDIST in f[H0 + k * HOUR] for k in (2, 3, 4)), str(e))
states = {H0 + i * HOUR: v for i, v in enumerate([100.0, 101.2, 101.2, 101.2])}
e, f = counter_to_hourly(states, {H0 + i * HOUR: 1200.0 for i in range(4)}, cfg)
check("stall with no catch-up stays missing and flagged", (H0 + 2 * HOUR) not in e and F_STALLED in f[H0 + 2 * HOUR])
states = {H0 + i * HOUR: v for i, v in enumerate([100.0, 101.0, 101.0, 102.0])}
e, f = counter_to_hourly(states, {H0 + i * HOUR: 50.0 for i in range(4)}, cfg)
check("zero energy at genuinely low power is NOT treated as a stall",
      abs(e[H0 + 2 * HOUR]) < 1e-9 and F_STALL_REDIST not in f.get(H0 + 2 * HOUR, set()))
flat = power_is_flat({H0: {"min": 5676.0, "max": 5676.0}, H0 + HOUR: {"min": 100.0, "max": 900.0}})
check("flat-lined instantaneous power detected", flat == {H0})

section("profile-driven build: source priority, scale, flags")
D, L = "sensor.d_", "sensor.l_"
profile = {"sources": [
    {"name": "dongle", "priority": 1,
     "entities": {"load_energy": {"id": D + "load"}, "soc": {"id": D + "soc"}, "batt_power": {"id": D + "bp"}}},
    {"name": "legacy", "priority": 2,
     "entities": {"load_energy": {"id": L + "load", "scale": 1000.0}, "soc": {"id": L + "soc"}}}]}
rows = []
for i in range(8):
    t = H0 + i * HOUR
    if i >= 4:   # dongle only from hour 4 on
        rows.append({"statistic_id": D + "load", "start_ts": t, "state": 500.0 + (i - 4) * 2.0})
        rows.append({"statistic_id": D + "soc", "start_ts": t, "mean": 60.0, "min": 59.0, "max": 61.0})
    rows.append({"statistic_id": L + "load", "start_ts": t, "state": 1.0 + i * 0.001})   # MWh
hist = build_history(rows, profile, cfg)
check("legacy MWh scaled to kWh and used before the dongle exists", abs(hist.get(H0 + HOUR).e["load"] - 1.0) < 1e-6)
check("dongle preferred where present",
      hist.get(H0 + 6 * HOUR).sources["load"] == "dongle" and abs(hist.get(H0 + 6 * HOUR).e["load"] - 2.0) < 1e-9)
check("fallback source is flagged", "fallback_source" in hist.get(H0 + HOUR).flags["load"])
rows2 = [{"statistic_id": D + "soc", "start_ts": H0, "mean": 0.0, "min": 0.0, "max": 0.0},
         {"statistic_id": D + "bp", "start_ts": H0, "mean": 2500.0, "min": 0.0, "max": 0.0},
         {"statistic_id": D + "soc", "start_ts": H0 + HOUR, "mean": 80.0, "min": 80.0, "max": 80.0},
         {"statistic_id": D + "soc", "start_ts": H0 + 2 * HOUR, "mean": 20.0, "min": 20.0, "max": 20.0}]
h2 = build_history(rows2, profile, cfg)
check("SOC of 0 while the battery is delivering 2.5 kW is flagged as a sensor fault",
      F_SOC_SUSPECT in h2.get(H0).flags["soc"])
check("an impossible 60-point hourly SOC step is flagged", F_SOC_JUMP in h2.get(H0 + 2 * HOUR).flags["soc"])

section("truncation (the leak-free replay primitive)")
h4 = History(HourRecord(start=H0 + i * HOUR, e={"load": 1.0}) for i in range(10))
cut = datetime.fromtimestamp(H0 + 4 * HOUR, UTC)
t4 = h4.truncated(cut)
check("truncated() keeps only hours strictly before the cut", len(t4) == 4 and max(t4.by_start) == H0 + 3 * HOUR)

section("effective-minimum SOC configuration rule (detail: test_intelligence_reserve.py)")
check("default user reserve is 40 % (a default, not a floor)", SiteConfig().user_reserve_soc_pct == 40.0)
check("a lower HA reserve (15 %) cannot lower the effective minimum", SiteConfig().effective_min_soc_pct(15.0) == 40.0)
check("a higher HA reserve raises the effective minimum", SiteConfig().effective_min_soc_pct(55.0) == 55.0)
check("no HA reserve -> the user reserve", SiteConfig().effective_min_soc_pct(None) == 40.0)

section("window energy apportionment")
h3 = History(HourRecord(start=H0 + i * HOUR, e={"load": 1.0 + i}) for i in range(6))
tot, cov = h3.energy("load", datetime.fromtimestamp(H0 + 1800, UTC), datetime.fromtimestamp(H0 + 2 * HOUR + 1800, UTC))
check("half hours apportioned (0.5*1 + 1*2 + 0.5*3)", abs(tot - 4.0) < 1e-9 and cov == 1.0, f"{tot} {cov}")
tot, cov = h3.energy("load", datetime.fromtimestamp(H0 + 5 * HOUR, UTC), datetime.fromtimestamp(H0 + 8 * HOUR, UTC))
check("coverage reports the part of the window that has data", abs(cov - 1 / 3) < 1e-9)
check("energy_scaled refuses poor coverage",
      h3.energy_scaled("load", datetime.fromtimestamp(H0 + 5 * HOUR, UTC), datetime.fromtimestamp(H0 + 8 * HOUR, UTC)) is None)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence foundations"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence foundations"} checks PASSED.")