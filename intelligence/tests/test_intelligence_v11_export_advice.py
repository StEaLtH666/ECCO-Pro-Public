#!/usr/bin/env python3
"""Intelligence V1.1 export-event (Saving Session) and dynamic Dump-to-Grid advice on SYNTHETIC inputs (fictional year
2030): the energy budgets are pinned analytically, the effective reserve plus margin is never planned through, power
limits bind when they should, the feature's 10-90 % stop range is respected, and every stale / unknown / conflicting
input refuses the advice with a stated reason."""

from __future__ import annotations

import itertools
import math
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.battery import eta_one_way  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.dump_advice import FEATURE_STOP_MAX_PCT, FEATURE_STOP_MIN_PCT, DumpInputs, advise_dump  # noqa: E402
from intelligence.events import EventInputs, ExportEvent, advise_event  # noqa: E402
from intelligence.explain import BLOCKED, OK  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
cfg = SiteConfig()
ETA = eta_one_way(cfg)
CAP = cfg.battery_capacity_kwh
T0 = datetime(2030, 3, 2, 15, 0, tzinfo=UTC)
EV = ExportEvent(datetime(2030, 3, 2, 17, 0, tzinfo=UTC), datetime(2030, 3, 2, 18, 0, tzinfo=UTC))


def ev(c=cfg, **kw):
    base = dict(now=T0, event=EV, soc_pct=90.0, soc_age_s=20.0, inverter_ok=True, demand_before_kwh=2.0,
                demand_during_kwh=1.2, demand_after_kwh=6.0, demand_label="HIGH", max_discharge_kw=5.0, max_export_kw=4.0)
    base.update(kw)
    return advise_event(c, EventInputs(**base))


print("[1] export event: the budget, pinned")
a = ev()
r = a.recommendation
soc_start = 90.0 - 2.0 / ETA / CAP * 100
usable = (soc_start - 45.0) / 100 * CAP * ETA
check("SOC at the start = SOC now minus the planned demand before it", abs(r["soc_at_start_pct"] - round(soc_start, 1)) < 1e-9)
check("energy above the minimum = (start SOC - 45 %) x capacity x eta", abs(r["energy_above_minimum_kwh"] - round(usable, 3)) < 1e-9)
check("the house is covered", r["cover_household_from_battery"] is True and a.status == OK)
by_power = min(5.0 * ETA * 1.0 - 1.2, 4.0 * 1.0)
check("export = floor(min(energy left after cover and keep, power-limited), 0.1)",
      r["export_kwh"] == math.floor(min(usable - 6.0 - 1.2, by_power) * 10 + 1e-9) / 10 and r["binding_constraint"] == "POWER_LIMIT")
check("the expected SOC at the end stays above the 45 % minimum plus what is kept for after",
      r["soc_at_end_expected_pct"] >= 45.0 + 6.0 / ETA / CAP * 100 - 0.1)
check("applies nothing", a.applies_nothing and a.mode == "SHADOW")
e2 = ev(max_discharge_kw=20.0, max_export_kw=20.0, demand_after_kwh=12.0).recommendation
check("with generous power limits, the energy above the reserve binds", e2["binding_constraint"] == "ENERGY_ABOVE_RESERVE")
e3 = ev(soc_pct=55.0)
check("too little energy: the house cannot be covered, no export, and it says so",
      e3.recommendation["cover_household_from_battery"] is False and e3.recommendation["export_advised"] is False
      and any(x.code == "CANNOT_COVER" for x in e3.reasons))
e4 = ev(max_discharge_kw=None)
check("unknown power limits: no export amount, but the cover answer stands",
      e4.status == OK and e4.recommendation["export_kwh"] is None and e4.recommendation["cover_household_from_battery"] is True
      and any(x.code == "EXPORT_LIMITS_UNKNOWN" for x in e4.reasons))
running = ev(now=datetime(2030, 3, 2, 17, 30, tzinfo=UTC), demand_before_kwh=None)
check("an event already running ignores the 'before' demand and uses the remaining time",
      running.status == OK and running.recommendation["event"]["started"] is True and running.recommendation["event"]["remaining_hours"] == 0.5)
check("an HA reserve can only raise the minimum", ev(ha_reserve_pct=70.0).recommendation["desired_min_pct"] == 75.0
      and ev(ha_reserve_pct=10.0).recommendation["desired_min_pct"] == 45.0)
bad = []
for soc, keep, dur, user in itertools.product((50.0, 70.0, 90.0, 100.0), (0.0, 4.0, 10.0), (0.5, 2.0, 5.0), (20.0, 40.0, 60.0)):
    c = replace(cfg, user_reserve_soc_pct=user)
    x = ev(c, soc_pct=soc, demand_after_kwh=keep, demand_during_kwh=dur, max_discharge_kw=8.0, max_export_kw=8.0).recommendation
    if x["export_advised"]:
        end = x["soc_at_end_expected_pct"]
        if end < user + cfg.soc_safety_margin_pct + keep / ETA / CAP * 100 - 0.2:
            bad.append((soc, keep, dur, user, end))
check("108 combinations: an advised export never plans below reserve + margin + what is kept for after", not bad, str(bad[:3]))

print("[2] export event: fail closed")
for label, kw, code in (("stale SOC", {"soc_age_s": 3600.0}, "STALE_SOC"), ("unknown SOC age", {"soc_age_s": None}, "UNKNOWN_SOC"),
                        ("no SOC", {"soc_pct": None}, "NO_SOC"), ("inverter unknown", {"inverter_ok": None}, "INVERTER_STATUS"),
                        ("inverter unhealthy", {"inverter_ok": False}, "INVERTER_STATUS"),
                        ("event over", {"now": datetime(2030, 3, 2, 19, 0, tzinfo=UTC)}, "EVENT_OVER"),
                        ("event inverted", {"event": ExportEvent(EV.end, EV.start)}, "INVALID_EVENT"),
                        ("demand unknown", {"demand_after_kwh": None}, "DEMAND_UNKNOWN"),
                        ("demand not a number", {"demand_during_kwh": float("nan")}, "DEMAND_UNKNOWN"),
                        ("demand on insufficient history", {"demand_label": "INSUFFICIENT"}, "DEMAND_INSUFFICIENT"),
                        ("negative PV credit", {"pv_during_kwh": -1.0}, "INVALID_INPUT")):
    x = ev(**kw)
    check(f"{label}: BLOCKED ({code}), no number", x.status == BLOCKED and x.recommendation is None
          and code in [b.code for b in x.blocking], str([b.code for b in x.blocking]))
run_stale = ev(now=datetime(2030, 3, 2, 17, 30, tzinfo=UTC), demand_before_kwh=None, soc_age_s=3600.0)
check("a running event with a stale SOC names only the stale SOC (the 'before' demand is not needed once it runs)",
      [b.code for b in run_stale.blocking] == ["STALE_SOC"], str([b.code for b in run_stale.blocking]))

print("[3] dynamic Dump-to-Grid: the stop level, pinned")
NOW = datetime(2030, 3, 2, 16, 0, tzinfo=UTC)
REFILL = datetime(2030, 3, 3, 0, 30, tzinfo=UTC)


def dg(c=cfg, **kw):
    base = dict(now=NOW, soc_pct=85.0, soc_age_s=20.0, inverter_ok=True, refill_at=REFILL, demand_until_refill_kwh=8.0,
                demand_label="HIGH", duration_min=60, max_discharge_kw=5.0, max_export_kw=4.0, in_charge_window=False)
    base.update(kw)
    return advise_dump(c, DumpInputs(**base))


d = dg()
rr = d.recommendation
stop = math.ceil(45.0 + 8.0 / ETA / CAP * 100 - 1e-9)
check("stop = ceil(40 reserve + 5 margin + 8 kWh / eta / capacity)", rr["stop_soc_pct"] == stop, f"{rr['stop_soc_pct']} vs {stop}")
check("export = floor((SOC - stop) x capacity x eta, 0.1)", rr["export_kwh"] == math.floor((85.0 - stop) / 100 * CAP * ETA * 10 + 1e-9) / 10)
check("advisable, OK, applies nothing", rr["dump_advisable"] is True and d.status == OK and d.applies_nothing)
check("the feature's own stop range is reported", rr["feature_stop_bounds_pct"] == (FEATURE_STOP_MIN_PCT, FEATURE_STOP_MAX_PCT))
check("the stop is set by reserve and demand; the export by the energy down to it",
      rr["stop_set_by"] == "RESERVE_AND_DEMAND" and rr["export_limited_by"] == "STOP_LEVEL")
lo = dg(c=replace(cfg, user_reserve_soc_pct=0.0, technical_min_soc_pct=0.0), demand_until_refill_kwh=0.0).recommendation
check("never below the feature's 10 % minimum (and the two constraints are reported separately)",
      lo["stop_soc_pct"] == FEATURE_STOP_MIN_PCT and lo["stop_set_by"] == "FEATURE_MINIMUM" and lo["export_limited_by"] == "POWER_LIMIT")
hi = dg(demand_until_refill_kwh=20.0)
check("a stop level above 90 % is not advised (the feature cannot express it)",
      hi.recommendation["dump_advisable"] is False and hi.recommendation["stop_soc_pct"] is None
      and hi.recommendation["stop_set_by"] == "ABOVE_FEATURE_RANGE" and hi.recommendation["export_limited_by"] is None)
nh = dg(soc_pct=60.0)
check("SOC at or below the stop level: nothing to export", nh.recommendation["dump_advisable"] is False
      and nh.recommendation["export_kwh"] is None and any(x.code == "NO_HEADROOM" for x in nh.reasons))
pw = dg(duration_min=20, max_discharge_kw=2.0, max_export_kw=2.0).recommendation
check("a short run at low power is POWER_LIMIT-bound", pw["export_limited_by"] == "POWER_LIMIT" and pw["export_kwh"] <= 2.0 * ETA * 20 / 60 + 1e-9)
check("an HA reserve can only raise the stop level", dg(ha_reserve_pct=55.0).recommendation["stop_soc_pct"] > stop
      and dg(ha_reserve_pct=5.0).recommendation["stop_soc_pct"] == stop)
viol = []
for soc, keep, user, tech in itertools.product((30.0, 60.0, 85.0, 100.0), (0.0, 3.0, 9.0), (0.0, 20.0, 40.0, 60.0), (10.0, 30.0)):
    c = replace(cfg, user_reserve_soc_pct=user, technical_min_soc_pct=tech)
    x = dg(c, soc_pct=soc, demand_until_refill_kwh=keep).recommendation
    if x["dump_advisable"]:
        floor_needed = max(user, tech) + cfg.soc_safety_margin_pct + keep / ETA / CAP * 100
        after = soc - x["export_kwh"] / ETA / CAP * 100
        if x["stop_soc_pct"] < floor_needed - 1e-9 or after < x["stop_soc_pct"] - 1e-6 or not 10.0 <= x["stop_soc_pct"] <= 90.0:
            viol.append((soc, keep, user, tech, x["stop_soc_pct"], round(after, 2)))
check("96 combinations: stop >= reserve + margin + kept demand, export never takes SOC below the stop, stop within 10-90 %",
      not viol, str(viol[:3]))

print("[4] dynamic Dump-to-Grid: fail closed")
for label, kw, code in (("stale SOC", {"soc_age_s": 1000.0}, "STALE_SOC"), ("unknown SOC age", {"soc_age_s": float("nan")}, "UNKNOWN_SOC"),
                        ("inverter unknown", {"inverter_ok": None}, "INVERTER_STATUS"),
                        ("charge window open", {"in_charge_window": True}, "CHARGE_WINDOW"),
                        ("charge window state unknown", {"in_charge_window": None}, "CHARGE_WINDOW"),
                        ("Saving Session in 2 h", {"saving_sessions": ((NOW + timedelta(hours=2), NOW + timedelta(hours=3)),)}, "SAVING_SESSION"),
                        ("Saving Session running", {"saving_sessions": ((NOW - timedelta(minutes=10), NOW + timedelta(minutes=50)),)}, "SAVING_SESSION"),
                        ("refill time passed", {"refill_at": NOW - timedelta(hours=1)}, "NO_REFILL_AHEAD"),
                        ("demand unknown", {"demand_until_refill_kwh": None}, "DEMAND_UNKNOWN"),
                        ("demand on insufficient history", {"demand_label": "INSUFFICIENT"}, "DEMAND_INSUFFICIENT")):
    x = dg(**kw)
    check(f"{label}: BLOCKED ({code}), no number", x.status == BLOCKED and x.recommendation is None
          and code in [b.code for b in x.blocking], str([b.code for b in x.blocking]))
check("a Saving Session more than 3 h away does not block",
      dg(saving_sessions=((NOW + timedelta(hours=4), NOW + timedelta(hours=5)),)).status == OK)
for label, sess in (("naive", (datetime(2030, 3, 2, 18, 0), datetime(2030, 3, 2, 19, 0))),
                    ("inverted", (NOW + timedelta(hours=5), NOW + timedelta(hours=4)))):
    x = dg(saving_sessions=(sess,))
    check(f"a {label} Saving Session is refused as INVALID_SESSION (fail closed, never a crash)",
          x.status == BLOCKED and "INVALID_SESSION" in [b.code for b in x.blocking])

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in intelligence V1.1 export advice:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll intelligence V1.1 export advice checks passed")
