#!/usr/bin/env python3
"""Planning stream: the projected value (intelligence/value.py). SYNTHETIC tariffs only (fictional 2030 prices).

  [1] no GBP figure without a VERIFIED tariff: NO_VALUE with a reason, no block
  [2] ranges ordered, finite and rounded outward to the PROPOSED step; seeded sweep
  [3] baselines computed on the same inputs (a baseline equal to the advice saves exactly nothing)
  [4] coverage: the rates must cover the charge window; a shorter horizon is valued with the stored energy
  [5] in the cycle: a value block only with a verified tariff and an OK charge target; never while all OPEN
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import baselines as bl  # noqa: E402
from intelligence import daily_plan as dp  # noqa: E402
from intelligence import tariff as tf  # noqa: E402
from intelligence import value as vl  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402
from intelligence.timeutil import zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
Z = zone("Europe/London")
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
W = (datetime(2030, 1, 16, 1, 0, tzinfo=UTC), datetime(2030, 1, 16, 4, 30, tzinfo=UTC))
END = datetime(2030, 1, 17, 1, 0, tzinfo=UTC)
CFG = SiteConfig(battery_capacity_kwh=20.0, round_trip_efficiency=0.92, user_reserve_soc_pct=30.0, technical_min_soc_pct=12.0,
                 max_grid_charge_kw=5.0, cheap_window_start_min=60, cheap_window_end_min=270)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def verified(payload, now=NOW, kind="import"):
    return tf.assess_rates(InputState(f"tariff.{kind}_rates", payload, True, 120.0, 300.0), now, kind=kind)


IMP = verified(ph.rates_payload(NOW))
EXP = verified(ph.rates_payload(NOW, export=True), kind="export")
VIEW = dp.hourly_view([1.1] * 24, {}, Z, dp.Band(20.0, 25.0, 31.0, "MEDIUM"), None)
BASES = bl.baselines(max_soc_pct=100.0, tou_current=InputState("tou.current_target_soc_pct", 80.0, True, 20.0, 300.0),
                     v1_target_pct=90.0, decisions_satisfied=True)[0]


def project(**kw):
    args = dict(cfg=CFG, floor_pct=30.0, now=NOW, horizon_end=END, window=W, soc_pct=50.0, advice_target_pct=70.0,
                baselines=BASES, view=VIEW, import_tariff=IMP, export_tariff=EXP)
    args.update(kw)
    return vl.project_value(**args)


print("== [1] no GBP without a VERIFIED tariff")
for label, imp in (("no tariff", None), ("NO_VALUE", tf.TariffResult("import", tf.NO_VALUE)), ("BLOCK", tf.TariffResult("import", tf.BLOCK)),
                   ("the shared fixture's rows", verified([{"start": "2030-01-16T01:00:00+00:00", "end": "2030-01-16T04:30:00+00:00", "p_per_kwh": 7.5}])),
                   ("a stale payload", tf.assess_rates(InputState("tariff.import_rates", ph.rates_payload(NOW), False, 7200.0, 300.0), NOW))):
    r = project(import_tariff=imp)
    check(f"{label}: NO_VALUE with a reason, no figure, no block", r.status == vl.NO_VALUE and r.range_gbp is None
          and not r.baselines and r.block() is None and r.findings and r.findings[0].code.startswith("VALUE_"), str(r.findings[:1]))
check("no SOC / no forecast / no baseline: NO_VALUE", project(soc_pct=None).status == vl.NO_VALUE
      and project(view=None).status == vl.NO_VALUE and project(baselines={}).status == vl.NO_VALUE)
try:
    vl.ValueResult(vl.NO_VALUE, (), range_gbp=(0.1, 0.2))
    refused = False
except ValueError:
    refused = True
check("a NO_VALUE result cannot carry a figure", refused)

print("== [2] ranges ordered, finite, rounded outward")
r = project()
check("VERIFIED: a range against HOLD_CURRENT (the primary baseline) and one per baseline", r.status == vl.VERIFIED
      and r.primary == bl.HOLD_CURRENT and set(r.baselines) == set(BASES), str((r.primary, r.baselines)))
step = vl.PROPOSED_VALUE_STEP_GBP
on_step = lambda x: abs(round(x / step) * step - x) < 1e-9  # noqa: E731
check("ordered and on the PROPOSED step", all(lo <= hi and on_step(lo) and on_step(hi) for lo, hi in r.baselines.values()))
blk = r.block()
check("the value block has exactly the declared keys and fits the byte budget", set(blk) == {"range_gbp", "assumptions", "baselines"}
      and len(json.dumps(blk)) <= ac.MAX_BLOCK_BYTES and all(isinstance(a, str) for a in blk["assumptions"]), str(len(json.dumps(blk))))
bad = []
for i in range(200):
    rnd = random.Random(300 + i)
    v = dp.hourly_view([rnd.uniform(0.1, 3.0) for _ in range(24)], {}, Z, dp.Band(10.0, rnd.uniform(10.0, 20.0), rnd.uniform(20.0, 40.0), "LOW"), None)
    res = project(view=v, soc_pct=rnd.uniform(0, 100), advice_target_pct=rnd.uniform(35, 100))
    if res.status != vl.VERIFIED:
        bad.append((i, res.status))
        continue
    for lo, hi in res.baselines.values():
        if not (lo <= hi and abs(lo) < 1e6 and abs(hi) < 1e6 and on_step(lo) and on_step(hi)):
            bad.append((i, lo, hi))
check("200 seeded projections: every range finite, ordered, on the step", not bad, str(bad[:3]))

print("== [3] the same inputs for the advice and every baseline")
same = project(advice_target_pct=100.0, baselines={bl.ALWAYS_100: bl.Baseline(bl.ALWAYS_100, 100.0, "test")})
check("a baseline equal to the advice saves exactly nothing", same.range_gbp == (0.0, 0.0), str(same.range_gbp))
check("an unverified export tariff only widens the range", (lambda a, b: a[0] <= b[0] and a[1] >= b[1])(
    project(export_tariff=None).range_gbp, project().range_gbp))

print("== [4] coverage")
short = verified({"current_day": {"rates": ph.go_like_rates(NOW.date(), 1)}})
check("rates that stop before the charge window: NO_VALUE TARIFF coverage", project(import_tariff=short).status == vl.NO_VALUE
      and project(import_tariff=short).findings[0].code == "VALUE_TARIFF_COVERAGE_SHORT")
check("rates that cover the window but end before the horizon: VERIFIED, valued with the stored energy (an assumption says so)",
      r.status == vl.VERIFIED and any("stored energy" in a for a in r.assumptions))

print("== [5] in the cycle")
syn = run_cycle(ph.verified_inputs(synthetic_recorded=True))
check("a verified tariff and an OK charge target: a value block (range, assumptions, baselines)", syn.value is not None
      and syn.item("charge_target").status == "OK" and len(syn.value["range_gbp"]) == 2
      and syn.value["range_gbp"][0] <= syn.value["range_gbp"][1], str(syn.value))
opn = run_cycle(ph.verified_inputs())
check("all OPEN with the same tariff payload: no value block", opn.value is None and opn.tariff["price_range"] is None)
unv = run_cycle(cf.cycle_inputs(synthetic_recorded=True))
check("an OK charge target without a verified tariff: no value block, reason VALUE_TARIFF_NOT_VERIFIED",
      unv.value is None and "VALUE_TARIFF_NOT_VERIFIED" in unv.reason_codes)
st_attrs = ac.to_entity_payloads(syn)[ac.ENTITY_IDS["status"]][1]
check("the value block is the status entity's value attribute (a range, never a point)", st_attrs["value"] == syn.value
      and isinstance(st_attrs["value"]["range_gbp"], list))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all value checks passed")
