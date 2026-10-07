#!/usr/bin/env python3
"""Intelligence V1.1 charge-target advice on SYNTHETIC inputs (fictional year 2030): the closed-form budget is pinned
analytically, the effective reserve (user default 40 %, technical minimum, HA reserve raising only) is always respected,
the limiting constraint is named, PV is credited only when vouched for, weak demand evidence retains the battery, a stale
SOC withholds only what needs it, and a change of target is attributed to the inputs that moved."""

from __future__ import annotations

import itertools
import math
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.battery import eta_one_way  # noqa: E402
from intelligence.charge_target import ChargeTargetInputs, advise_charge_target  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.explain import BLOCKED, INSUFFICIENT, OK  # noqa: E402
from intelligence.overnight import NightObservation as N  # noqa: E402
from intelligence.overnight import OvernightSettings, learn_overnight  # noqa: E402

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
T = date(2030, 3, 2)
NOW = datetime(2030, 3, 1, 23, 0, tzinfo=UTC)
WIN = (datetime(2030, 3, 2, 0, 30, tzinfo=UTC), datetime(2030, 3, 2, 5, 30, tzinfo=UTC))


def demand(level: float, n: int = 40, prior: float | None = None):
    obs = [N(T - timedelta(days=k), level) for k in range(1, n + 1)]          # a perfectly flat house: planning == level
    return learn_overnight(obs, T, OvernightSettings.from_site(cfg, prior_kwh=prior))


def ct(c=cfg, d=None, **kw):
    return advise_charge_target(c, ChargeTargetInputs(NOW, WIN, d or demand(9.0), **kw))


def expected_target(c: SiteConfig, end_floor: float, need_kwh: float) -> float:
    raw = end_floor + need_kwh / eta_one_way(c) / c.battery_capacity_kwh * 100.0
    return min(c.max_soc_pct, math.ceil(raw / c.target_step_pct - 1e-9) * c.target_step_pct)


print("[1] the budget, pinned analytically")
d9 = demand(9.0)
P9 = d9.recommendation["planning_kwh"]
check("a flat 9 kWh house plans a little above 9 kWh (the band is never zero: 2 % sigma floor x z90)",
      abs(P9 - 9.0 * (1 + 1.2815515655446004 * 0.02)) < 1e-3, str(P9))
a = ct(soc_pct=50.0, soc_age_s=60.0)
r = a.recommendation
check("target = ceil5(40 reserve + 5 margin + planned kWh / eta / capacity)", r["target_soc_pct"] == expected_target(cfg, 45.0, P9)
      and r["target_soc_pct"] == 80.0, str(r["target_soc_pct"]))
check("the unrounded target is the budget exactly", abs(r["raw_target_soc_pct"] - (45.0 + P9 / ETA / cfg.battery_capacity_kwh * 100)) < 0.01)
check("the demand set it (binding DEMAND), OK, applies nothing", r["binding_constraint"] == "DEMAND" and a.status == OK
      and a.applies_nothing)
check("the reasons say what it rests on", any(x.code == "TARGET" for x in a.reasons) and "40% reserve" in [x for x in a.reasons if x.code == "TARGET"][0].text)
check("before the window opens, today's SOC is NOT used for the grid energy or the reach (it is not the start SOC)",
      r["grid_charge_kwh"] is None and r["achievable_soc_pct"] is None and any(x.code == "WINDOW_NOT_OPEN" for x in a.reasons))
IN_WIN = datetime(2030, 3, 2, 1, 0, tzinfo=UTC)
ins_ = advise_charge_target(cfg, ChargeTargetInputs(IN_WIN, WIN, d9, soc_pct=50.0, soc_age_s=60.0)).recommendation
check("inside the window: grid energy = (target - current SOC) x capacity / eta",
      abs(ins_["grid_charge_kwh"] - round((80.0 - 50.0) / 100 * cfg.battery_capacity_kwh / ETA, 2)) < 1e-9
      and ins_["window_start_soc_source"].startswith("current SOC"))
check("inside the window: 8 kW for the remaining 4.5 h can reach it", ins_["achievable_soc_pct"] == 100.0)
pr = ct(soc_pct=90.0, soc_age_s=60.0, soc_at_window_start_pct=45.0).recommendation
check("before the window, a supplied prediction of the start SOC is used (not today's 90 %)",
      abs(pr["grid_charge_kwh"] - round((80.0 - 45.0) / 100 * cfg.battery_capacity_kwh / ETA, 2)) < 1e-9
      and pr["window_start_soc_pct"] == 45.0 and "predicted" in pr["window_start_soc_source"])
check("an invalid prediction is ignored", ct(soc_at_window_start_pct=float("nan")).recommendation["grid_charge_kwh"] is None)

print("[2] the effective reserve is always respected")
bad = []
for user, tech, ha, lvl in itertools.product((0.0, 20.0, 40.0, 60.0), (10.0, 25.0, 50.0), (None, 15.0, 70.0), (0.0, 4.0, 12.0, 40.0)):
    c = replace(cfg, user_reserve_soc_pct=user, technical_min_soc_pct=tech)
    adv = advise_charge_target(c, ChargeTargetInputs(NOW, WIN, demand(lvl), ha_reserve_pct=ha))
    eff = max(user, tech, ha or 0.0)
    t = adv.recommendation["target_soc_pct"]
    if not (t >= min(c.max_soc_pct, eff + c.soc_safety_margin_pct) and adv.recommendation["effective_reserve_pct"] == eff):
        bad.append((user, tech, ha, lvl, t))
check("144 reserve / technical-minimum / HA-reserve / demand combinations: target >= effective reserve + margin", not bad, str(bad[:3]))
check("no hidden 40 % floor: a 20 % reserve and no demand gives 25 %",
      advise_charge_target(replace(cfg, user_reserve_soc_pct=20.0), ChargeTargetInputs(NOW, WIN, demand(0.0))).recommendation["target_soc_pct"] == 25.0)
t1 = advise_charge_target(replace(cfg, user_reserve_soc_pct=20.0, technical_min_soc_pct=30.0), ChargeTargetInputs(NOW, WIN, demand(0.0)))
check("a technical minimum above the user reserve binds, and says so",
      t1.recommendation["target_soc_pct"] == 35.0 and t1.recommendation["binding_constraint"] == "RESERVE"
      and any(x.code == "TECHNICAL_MIN_OVERRIDES_USER_RESERVE" for x in t1.reasons))
t2 = ct(d=demand(0.0), ha_reserve_pct=60.0)
check("an HA reserve can only raise it", t2.recommendation["target_soc_pct"] == 65.0
      and ct(d=demand(0.0), ha_reserve_pct=10.0).recommendation["target_soc_pct"] == 45.0)

print("[3] desired morning SOC, PV credit, shortfall, window limit")
m = ct(d=demand(2.0), desired_morning_soc_pct=70.0).recommendation
check("a desired morning SOC above the floor sets the floor", m["end_of_period_floor_pct"] == 70.0
      and m["target_soc_pct"] == expected_target(cfg, 70.0, 2.0))
check("...and is named when demand is negligible", ct(d=demand(0.0), desired_morning_soc_pct=70.0).recommendation["binding_constraint"] == "DESIRED_MORNING_SOC")
check("an invalid desired morning SOC blocks", ct(desired_morning_soc_pct=150.0).status == BLOCKED)
pv_ok = ct(pv_credit_kwh=4.0, pv_credit_label="MEDIUM").recommendation
check("PV vouched at MEDIUM is credited", pv_ok["pv_credit_used_kwh"] == 4.0 and pv_ok["target_soc_pct"] == expected_target(cfg, 45.0, P9 - 4.0))
pv_low = ct(pv_credit_kwh=4.0, pv_credit_label="LOW")
check("PV at LOW confidence is ignored, and the advice says so", pv_low.recommendation["pv_credit_used_kwh"] == 0.0
      and any(x.code == "PV_CREDIT_IGNORED" for x in pv_low.reasons))
check("PV credit never exceeds the planned demand", ct(pv_credit_kwh=50.0, pv_credit_label="HIGH").recommendation["net_need_kwh"] == 0.0)
check("a non-finite PV credit is ignored", ct(pv_credit_kwh=float("nan"), pv_credit_label="HIGH").recommendation["pv_credit_used_kwh"] == 0.0)
sh = ct(d=demand(30.0))
check("demand beyond a full battery is a SHORTFALL at the maximum, never a smaller number",
      sh.recommendation["target_soc_pct"] == 100.0 and sh.recommendation["binding_constraint"] == "MAX_SOC"
      and sh.recommendation["shortfall_soc_pct"] > 0 and any(x.code == "SHORTFALL" for x in sh.reasons))
late = advise_charge_target(cfg, ChargeTargetInputs(datetime(2030, 3, 2, 5, 0, tzinfo=UTC), WIN, demand(9.0), soc_pct=40.0, soc_age_s=10.0))
check("half an hour of window from 40 % cannot reach 80 %: CHARGE_WINDOW is named",
      late.recommendation["binding_constraint"] == "CHARGE_WINDOW" and late.recommendation["achievable_soc_pct"] < 80.0)

print("[4] weak evidence and stale inputs")
ins = ct(d=demand(9.0, n=3))
check("INSUFFICIENT demand evidence: retain the battery (maximum SOC), flagged", ins.status == INSUFFICIENT
      and ins.recommendation["target_soc_pct"] == 100.0 and ins.recommendation["conservative_fallback"] is True
      and ins.confidence.label == "INSUFFICIENT")
pri = ct(d=demand(6.0, n=3, prior=12.0))
check("a conservative default is used but flagged, and confidence stays at most LOW",
      pri.status == INSUFFICIENT and pri.recommendation["conservative_fallback"] is True and pri.confidence.label in ("LOW", "INSUFFICIENT")
      and pri.recommendation["demand_planning_kwh"] >= 12.0)
st = advise_charge_target(cfg, ChargeTargetInputs(IN_WIN, WIN, d9, soc_pct=50.0, soc_age_s=3600.0))
check("inside the window, a stale SOC withholds the grid energy and the window check, not the target",
      st.status == OK and st.recommendation["target_soc_pct"] == 80.0 and st.recommendation["grid_charge_kwh"] is None
      and st.recommendation["achievable_soc_pct"] is None and any(x.code == "SOC_NOT_FRESH" for x in st.reasons))
check("an unknown SOC age is treated as stale",
      advise_charge_target(cfg, ChargeTargetInputs(IN_WIN, WIN, d9, soc_pct=50.0, soc_age_s=None)).recommendation["grid_charge_kwh"] is None)
check("a window that has ended blocks", advise_charge_target(cfg, ChargeTargetInputs(datetime(2030, 3, 2, 6, 0, tzinfo=UTC), WIN, d9)).status == BLOCKED)
check("a window in naive time blocks", advise_charge_target(cfg, ChargeTargetInputs(NOW, (datetime(2030, 3, 2, 0, 30), datetime(2030, 3, 2, 5, 30)), d9)).status == BLOCKED)

print("[5] why the target changed")
prev = ct()
up = ct(d=demand(12.0), previous=prev).recommendation["changed_from_previous"]
check("more demand: one driver, the demand, with its effect in points",
      [x["input"] for x in up["drivers"]] == ["demand_planning_kwh"] and up["drivers"][0]["effect_pct"] > 0
      and abs(sum(x["effect_pct"] for x in up["drivers"]) + up["unexplained_by_inputs_pct"] - up["delta_pct"]) < 0.02)
both = ct(d=demand(12.0), ha_reserve_pct=50.0, previous=prev)
ch = both.recommendation["changed_from_previous"]
check("reserve and demand both moved: both named, reserve first", [x["input"] for x in ch["drivers"]] == ["end_floor_pct", "demand_planning_kwh"]
      and any(x.code == "CHANGED" for x in both.reasons))
same_adv = ct(previous=prev)
same = same_adv.recommendation["changed_from_previous"]
check("nothing moved: no drivers and no CHANGED reason", len(same["drivers"]) == 0 and same["delta_pct"] == 0.0
      and not any(x.code == "CHANGED" for x in same_adv.reasons))
check("no previous advice: no change block", ct().recommendation["changed_from_previous"] is None)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in intelligence V1.1 charge target:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll intelligence V1.1 charge target checks passed")
