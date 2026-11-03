#!/usr/bin/env python3
"""Planning stream: the baselines and the one energy replay (intelligence/baselines.py). SYNTHETIC values only.

  [1] ALWAYS_100 always; HOLD_CURRENT only with a fresh percentage reading (absent when missing / stale / not a number);
      V1_CONFIG_WINDOW only when the decisions are satisfied
  [2] the replay: energy balance, the reserve held (never raised), the window charge, PV overflow, no target = no charge
  [3] every policy is replayed on the same inputs (an identical target gives an identical outcome and a zero delta)
  [4] cost_p: no rate -> None (never a guessed price); export earns only with a rate
  [5] no GBP figure without VERIFIED provenance (the cycle and the backtest)
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence import baselines as bl  # noqa: E402
from intelligence.battery import eta_one_way  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.shadow_cycle import judged_reading, run_cycle  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
T0 = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
W = (datetime(2030, 1, 16, 1, 0, tzinfo=UTC), datetime(2030, 1, 16, 4, 30, tzinfo=UTC))
END = datetime(2030, 1, 17, 1, 0, tzinfo=UTC)
CFG = SiteConfig(battery_capacity_kwh=20.0, round_trip_efficiency=0.92, user_reserve_soc_pct=30.0, technical_min_soc_pct=12.0,
                 max_grid_charge_kw=5.0)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def tou_cur(v, fresh=True, limit=300.0):
    return InputState("tou.current_target_soc_pct", v, fresh, 20.0, limit)


print("== [1] the baselines")
b, n = bl.baselines(max_soc_pct=100.0, tou_current=tou_cur(80.0), v1_target_pct=90.0, decisions_satisfied=True)
check("all three, in order", list(b) == [bl.ALWAYS_100, bl.HOLD_CURRENT, bl.V1_CONFIG_WINDOW]
      and b[bl.ALWAYS_100].target_soc_pct == 100.0 and b[bl.HOLD_CURRENT].target_soc_pct == 80.0
      and b[bl.V1_CONFIG_WINDOW].target_soc_pct == 90.0 and n == [])
for label, st in (("missing", None), ("stale", tou_cur(80.0, fresh=False)), ("no limit", tou_cur(80.0, limit=None)),
                  ("not a number", tou_cur("80")), ("out of range", tou_cur(140.0)), ("NaN", tou_cur(float("nan")))):
    bb, nn = bl.baselines(max_soc_pct=100.0, tou_current=st, v1_target_pct=90.0, decisions_satisfied=True)
    check(f"HOLD_CURRENT absent when its reading is {label}", bl.HOLD_CURRENT not in bb
          and any(f.code == "BASELINE_HOLD_CURRENT_ABSENT" for f in nn))
bb, nn = bl.baselines(max_soc_pct=100.0, tou_current=tou_cur(80.0), v1_target_pct=90.0, decisions_satisfied=False)
check("V1_CONFIG_WINDOW absent unless the decisions are satisfied", bl.V1_CONFIG_WINDOW not in bb
      and any(f.code == "BASELINE_V1_ABSENT" for f in nn))
check("... or without a V1 target", bl.V1_CONFIG_WINDOW not in bl.baselines(max_soc_pct=100.0, tou_current=None, v1_target_pct=None,
                                                                           decisions_satisfied=True)[0])
vin = ph.verified_inputs(synthetic_recorded=True)
env = run_cycle(vin)
st = judged_reading(vin, "tou.current_target_soc_pct")
check("in the cycle (a verified tariff, so a value block exists) HOLD_CURRENT is listed exactly when the cycle judges the "
      f"current TOU target fresh (here: {st.fresh}, limit {st.limit_s}); with no defined limit it is absent (fail closed)",
      env.value is not None and (bl.HOLD_CURRENT in env.value["baselines"]) == bool(st.fresh)
      and (st.fresh or bl.HOLD_CURRENT not in env.value["baselines"]), str(env.value and list(env.value["baselines"])))
with ph.simulated_ccr_plan_1(300.0):
    env_l = run_cycle(vin)
    st_l = judged_reading(vin, "tou.current_target_soc_pct")
check("... with a defined limit (CCR-PLAN-1 simulated in process) the fresh reading gives HOLD_CURRENT (not vacuous)",
      st_l.fresh and env_l.value is not None and bl.HOLD_CURRENT in env_l.value["baselines"],
      str(env_l.value and list(env_l.value["baselines"])))
with ph.simulated_ccr_plan_1(10.0):
    env_s = run_cycle(vin)
check("... and a reading older than that limit gives none (stale)", env_s.value is not None
      and bl.HOLD_CURRENT not in env_s.value["baselines"], str(env_s.value and list(env_s.value["baselines"])))

print("== [2] the replay")
flat = lambda v: (lambda _h: v)  # noqa: E731
o = bl.replay(CFG, 30.0, 100.0, 50.0, T0, END, W, flat(1.0), flat(0.0))
eta = eta_one_way(CFG)
check("the window charges toward the target at up to the grid limit (5 kW x 3.5 h minus the house load)",
      o.window_import_kwh <= 5.0 * 3.5 + 1e-6 and o.window_import_kwh > 3.5, str(o.window_import_kwh))
check("outside the window the battery carries the house down to the reserve, then the grid (peak import)",
      o.peak_import_kwh > 0 and abs(min(p[1] for p in o.points) - 30.0) < 1e-6)
check("the unconstrained track goes below the reserve where the held track does not", o.min_soc_unconstrained < 30.0)
check("import = window + peak", abs(o.import_kwh - (o.window_import_kwh + o.peak_import_kwh)) < 1e-9)
low = bl.replay(CFG, 30.0, None, 10.0, T0, W[0], None, flat(1.0), flat(0.0))
check("a battery already below the reserve is held where it is (never raised by import)",
      abs(max(p[1] for p in low.points) - 10.0) < 1e-9 and abs(low.peak_import_kwh - 4.0) < 1e-6, str((low.peak_import_kwh, low.points[:2])))
nt = bl.replay(CFG, 30.0, None, 60.0, T0, END, W, flat(0.5), flat(0.0))
check("no target: no grid charge in the window", nt.window_import_kwh == 0.0)
sun = bl.replay(CFG, 30.0, 100.0, 95.0, T0, END, W, flat(0.2), lambda h: 3.0 if 10 <= h.hour <= 14 else 0.0)
check("a PV surplus fills the battery to the maximum and the rest is exported", sun.export_kwh > 0 and max(p[1] for p in sun.points) <= 100.0 + 1e-9)
bad = []
for i in range(300):
    rnd = random.Random(70 + i)
    loads = [rnd.uniform(0, 3) for _ in range(30)]
    pvs = [rnd.uniform(0, 4) if 9 <= k % 24 <= 15 else 0.0 for k in range(30)]
    lf = lambda h, L=loads: L[int((h - T0).total_seconds() // 3600) % 30]  # noqa: E731
    pf = lambda h, P=pvs: P[int((h - T0).total_seconds() // 3600) % 30]  # noqa: E731
    tgt = rnd.choice([None, rnd.uniform(30, 100)])
    s0 = rnd.uniform(0, 100)
    x = bl.replay(CFG, 30.0, tgt, s0, T0, END, W, lf, pf)
    if not (x.window_import_kwh >= -1e-9 and x.peak_import_kwh >= -1e-9 and x.export_kwh >= -1e-9):
        bad.append((i, "negative energy"))
    if any(p[1] > 100.0 + 1e-9 or p[1] < min(30.0, s0) - 1e-9 for p in x.points):
        bad.append((i, "held SOC out of range"))
    if any(st.import_kwh < -1e-9 or st.export_kwh < -1e-9 for st in x.steps):
        bad.append((i, "step"))
    if abs(sum(st.import_kwh for st in x.steps) - x.import_kwh) > 1e-6:
        bad.append((i, "steps do not add up", sum(st.import_kwh for st in x.steps), x.import_kwh))
check("300 seeded replays: energies non-negative, held SOC within [min(reserve, start), max], steps add up", not bad, str(bad[:3]))

print("== [3] one definition, the same inputs")
lf, pf = flat(1.1), (lambda h: 2.0 if 11 <= h.hour <= 13 else 0.0)
a = bl.replay(CFG, 30.0, 80.0, 50.0, T0, END, W, lf, pf)
b2 = bl.replay(CFG, 30.0, 80.0, 50.0, T0, END, W, lf, pf)
check("an identical target on the same inputs gives an identical outcome", a == b2)
cmp = bl.compare({bl.ADVICE: a, bl.ALWAYS_100: bl.replay(CFG, 30.0, 100.0, 50.0, T0, END, W, lf, pf), "SAME": b2})
check("compare(): a zero delta against the same policy, a negative import delta against ALWAYS_100 here",
      cmp["SAME"] == {"import_kwh_delta": 0.0, "peak_import_kwh_delta": 0.0} and cmp[bl.ALWAYS_100]["import_kwh_delta"] < 0, str(cmp))

print("== [4] cost_p")
rate = lambda t: 7.5 if W[0] <= t < W[1] else 30.0  # noqa: E731
c1 = bl.cost_p(a, rate, None)
check("a cost in pence from the step energies and the rates", c1 is not None and c1 > 0)
check("a missing rate on an importing step: None, never a guessed price", bl.cost_p(a, lambda t: None if t.hour == 2 else 30.0) is None)
c2 = bl.cost_p(sun, rate, lambda t: 15.0)
c3 = bl.cost_p(sun, rate, None)
check("export earns only with an export rate", c2 is not None and c3 is not None and c2 < c3)

print("== [5] no GBP figure without VERIFIED provenance")
unv = run_cycle(cf.cycle_inputs(synthetic_recorded=True))
ver = run_cycle(ph.verified_inputs(synthetic_recorded=True))
check("the cycle without a verified tariff: no value block, no price range", unv.tariff["provenance"] != "VERIFIED_FROM_INTEGRATION"
      and unv.value is None and unv.tariff["price_range"] is None)
check("... with one: a value block whose baselines were all replayed", ver.value is not None
      and set(ver.value["baselines"]) <= set(bl.BASELINE_NAMES) and bl.ALWAYS_100 in ver.value["baselines"], str(ver.value))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all baseline checks passed")
