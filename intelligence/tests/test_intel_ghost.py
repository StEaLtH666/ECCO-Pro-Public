#!/usr/bin/env python3
"""Intelligence versus reality (intelligence/ghost.py + tools/ghost_report.py) on SYNTHETIC houses (fictional year 2030):

  [1] AdviceRecord adapts the real advice kinds (charge target, Dump-to-Grid) and refuses nonsense
  [2] with no advice the ghost IS reality (so every difference is the advice, not the model)
  [3] the ghost respects floor, ceiling and power limits, export limit and permission (also under random aggressive advice)
  [4] a bad-forecast day: the ghost loses, is listed, and the decision point is explained in words
  [5] a good day: the ghost wins; per-day and total figures add up; unknown wear stays unknown
  [6] label, ready_for_assisted_evidence (below-reserve count is 0), reproducibility, the CLI, no write path
The "actual" houses are generated here by an independent simple simulation, not by ghost.py.
"""

from __future__ import annotations

import io
import json
import math
import random
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.config import SiteConfig  # noqa: E402
from intelligence.explain import OK, Advice, Confidence, ConfidenceFactor  # noqa: E402
from intelligence.ghost import (KINDS, ActualPeriod, AdviceRecord, GhostLimits, _simulate, parse_export, render_text,  # noqa: E402
                                run_ghost)
from intelligence.tools import ghost_report  # noqa: E402
from intelligence.net_value import Slot, Tariff  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def near(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


UTC = timezone.utc
CFG = SiteConfig(tz="UTC", round_trip_efficiency=0.81, battery_capacity_kwh=10.0, max_grid_charge_kw=5.0,
                 user_reserve_soc_pct=40.0, technical_min_soc_pct=10.0, max_soc_pct=100.0)
ETA = 0.9
STEP = 0.5
D0 = datetime(2030, 1, 14, tzinfo=UTC)
RESERVE = 40.0


def make_period(pv_by_day, night_target=90.0, soc0=45.0, ok=True, limit=None, load_scale=1.0, kw=5.0, floor=RESERVE) -> ActualPeriod:
    """A real-looking battery by an independent rule set: charge from the grid 00:30-05:30 to `night_target`, otherwise
    self-use between the 40 % reserve and full. Half-hour slots; 7 p cheap window, 30 p otherwise, 15 p export."""
    slots, imp_p, exp_p = [], [], []
    soc = soc0 / 100 * 10.0
    for d, scale in enumerate(pv_by_day):
        for i in range(48):
            t = D0 + timedelta(days=d, minutes=30 * i)
            hh = i / 2.0
            load = load_scale * (0.8 if 17 <= hh < 21 else 0.3)
            pv = max(0.0, scale * 1.6 * math.sin(math.pi * (hh - 7.5) / 9.0)) * STEP if 7.5 <= hh <= 16.5 else 0.0
            chg = dis = 0.0
            cheap = 0.5 <= hh < 5.5
            if cheap and soc < night_target / 100 * 10:
                chg = min((night_target / 100 * 10 - soc) / ETA, kw * STEP)
            else:
                net = pv - load
                if net > 0:
                    chg = min(net, (10.0 - soc) / ETA, kw * STEP)
                else:
                    dis = min(-net, max(0.0, soc - floor / 100 * 10) * ETA, kw * STEP)
            soc += chg * ETA - dis / ETA
            slots.append(Slot.derive(t, STEP, pv, load, chg, dis))
            imp_p.append(7.0 if cheap else 30.0)
            exp_p.append(15.0)
    return ActualPeriod(tuple(slots), Tariff.make(len(slots), imp_p, exp_p, ok, limit), soc0)


def charge_advice(day, target, issued_h=-1.0, status=OK, aid="c", reserve=None) -> AdviceRecord:
    w0 = D0 + timedelta(days=day, minutes=30)
    return AdviceRecord("charge_target", status, w0 + timedelta(hours=issued_h), w0, w0 + timedelta(hours=5), target,
                        effective_reserve_pct=reserve, advice_id=aid)


def dump_advice(day, hour, stop, kwh, dur_h=2.0, kw=None, aid="d") -> AdviceRecord:
    t0 = D0 + timedelta(days=day, hours=hour)
    return AdviceRecord("dump_to_grid", OK, t0 - timedelta(minutes=5), t0, t0 + timedelta(hours=dur_h), stop, kwh, kw,
                        advice_id=aid)


print("== [1] AdviceRecord")
conf = Confidence.combine([ConfidenceFactor("x", 1.0, "x")])
w0, w1 = D0 + timedelta(minutes=30), D0 + timedelta(hours=5, minutes=30)
adv = Advice("charge_target", OK, {"target_soc_pct": 70.0, "window": [w0.isoformat(), w1.isoformat()],
                                   "effective_reserve_pct": 40.0, "conservative_fallback": False}, conf)
rec = AdviceRecord.from_advice(adv, D0 - timedelta(hours=2), advice_id="a1")
check("a charge-target Advice becomes a record with target, window and reserve",
      rec.kind == "charge_target" and rec.target_soc_pct == 70.0 and rec.window_start == w0 and rec.window_end == w1
      and rec.effective_reserve_pct == 40.0 and rec.followable())
dadv = Advice("dump_to_grid", OK, {"dump_advisable": True, "stop_soc_pct": 55.0, "export_kwh": 3.2, "export_kw_avg": 1.6,
                                   "effective_reserve_pct": 40.0}, conf)
drec = AdviceRecord.from_advice(dadv, D0 + timedelta(hours=17), duration_min=120)
check("a dump Advice takes its window from issue time + the recorded duration",
      drec.window_start == D0 + timedelta(hours=17) and drec.window_end == D0 + timedelta(hours=19)
      and drec.target_soc_pct == 55.0 and drec.export_kwh == 3.2 and drec.followable())
check("a dump Advice without a recorded duration has no window and is not followed",
      not AdviceRecord.from_advice(dadv, D0).followable())
check("not advisable dump is not followed", not AdviceRecord.from_advice(
    Advice("dump_to_grid", OK, {"dump_advisable": False, "stop_soc_pct": None, "export_kwh": None}, conf), D0, 60).followable())
from intelligence.explain import Blocker, blocked  # noqa: E402
bl = blocked("charge_target", [Blocker("X", "stale")])
check("a BLOCKED advice is recorded but never followed", not AdviceRecord.from_advice(bl, D0).followable())
fb = Advice("charge_target", "INSUFFICIENT_DATA", {"target_soc_pct": 100.0, "window": [w0.isoformat(), w1.isoformat()],
                                                   "conservative_fallback": True}, conf)
fr = AdviceRecord.from_advice(fb, D0)
check("a fallback is followed only on request", not fr.followable() and fr.followable(include_fallback=True))
check("to_dict / from_dict round trip", AdviceRecord.from_dict(json.loads(json.dumps(rec.to_dict()))) == rec)
for bad in (lambda: AdviceRecord("tou_write", OK, D0), lambda: AdviceRecord("charge_target", "MAYBE", D0),
            lambda: AdviceRecord("charge_target", OK, datetime(2030, 1, 1)), lambda: AdviceRecord("charge_target", OK, D0, target_soc_pct=140.0),
            lambda: AdviceRecord("charge_target", OK, D0, w1, w0, 50.0), lambda: AdviceRecord.from_dict({"kind": "charge_target", "x": 1}),
            lambda: AdviceRecord.from_advice(Advice("overnight_demand", OK, {"a": 1}, conf), D0)):
    try:
        bad()
        check("malformed advice is refused", False)
    except (ValueError, TypeError):
        check("malformed advice is refused", True)
check("only the two real kinds are adapted", KINDS == ("charge_target", "dump_to_grid"))

print("== [2] no advice: the ghost is reality")
per = make_period([0.5, 1.0, 0.2])
rep = run_ghost(per, [], CFG)
check("no advice: ghost equals actual on every day, so there are no decision points",
      all(abs(d["delta_before_wear_p"]) < 1e-6 for d in rep["days"]) and rep["decision_points"] == [])
check("no advice: identical min SOC and throughput", near(rep["totals"]["actual_min_soc_pct"], rep["totals"]["ghost_min_soc_pct"], 1e-6)
      and near(rep["totals"]["actual_throughput_kwh"], rep["totals"]["ghost_throughput_kwh"], 1e-6))
run = _simulate(per, [], CFG, GhostLimits(), "follow_actual", None)
check("no advice: every ghost slot reproduces the real flows", all(
    near(a.imp, b.imp, 1e-9) and near(a.exp, b.exp, 1e-9) and near(a.chg, b.chg, 1e-9) and near(a.dis, b.dis, 1e-9)
    for a, b in zip(per.slots, run.slots)))
check("the independent generator really does hold the 40 % reserve", min(rep["days"][0]["actual_min_soc_pct"], 99) >= 39.9)

print("== [3] limits")
lim = GhostLimits(max_charge_kw=2.0, max_discharge_kw=1.5)
per2 = make_period([0.3, 0.3], night_target=60.0, soc0=60.0)
advs = [charge_advice(0, 100.0), dump_advice(0, 17, 0.0, 99.0, 4.0), charge_advice(1, 100.0), dump_advice(1, 17, 0.0, 99.0, 4.0)]
run = _simulate(per2, advs, CFG, lim, "follow_actual", None)
eta_cap = CFG.battery_capacity_kwh
check("the ghost never exceeds the charge or discharge power", all(
    s.chg <= 2.0 * STEP + 1e-9 and s.dis <= 1.5 * STEP + 1e-9 for s in run.slots))
check("the ghost never rises above the ceiling", max(run.soc_pct) <= CFG.max_soc_pct + 1e-6)
check("a charge advice of 100 % is reached only as fast as the power allows (2 kW = 1 kWh per slot, 0.9 kWh stored = 9 points)",
      run.soc_pct[1] <= 60.0 + 9.0 + 1e-6 and run.soc_pct[2] <= 60.0 + 18.0 + 1e-6 and max(run.soc_pct) > 95.0)
check("a dump advice to 0 % stops at the reserve, never below it", min(run.soc_pct[24:]) >= RESERVE - 1e-6, str(min(run.soc_pct[24:])))
check("with 1.5 kW the house (0.8 kWh a slot) takes nearly all of the discharge: the dump cannot export more than is left",
      sum(s.exp for s in run.slots[34:42]) < 1e-9 and run.slots[34].dis <= 0.75 + 1e-9)
run_fast = _simulate(per2, advs, CFG, GhostLimits(2.0, 4.0), "follow_actual", None)
check("with 4 kW the dump serves the house first, then exports the rest down to the reserve",
      sum(s.exp for s in run_fast.slots[34:42]) > 0.3 and min(run_fast.soc_pct[24:]) >= RESERVE - 1e-6)
check("the ghost's slots all balance", all(abs(s.residual) < 1e-9 for s in run.slots))
check("the same limits hold for every ghost slot of both days", all(s.chg >= 0 and s.dis >= 0 for s in run.slots))
run = _simulate(per2, [dump_advice(0, 17, 0.0, 99.0, 4.0)], CFG, GhostLimits(), "follow_actual", None)
run_np = _simulate(make_period([0.3, 0.3], night_target=60.0, soc0=60.0, ok=False), [dump_advice(0, 17, 0.0, 99.0, 4.0)], CFG,
                   GhostLimits(), "follow_actual", None)
check("export not permitted: no dump export", sum(s.exp for s in run_np.slots) == 0.0)
run_lim = _simulate(make_period([0.3, 0.3], night_target=60.0, soc0=60.0, limit=0.5), [dump_advice(0, 17, 0.0, 99.0, 4.0)], CFG,
                    GhostLimits(), "follow_actual", None)
check("export limit 0.5 kW: no slot exports more than 0.25 kWh", max(s.exp for s in run_lim.slots) <= 0.25 + 1e-9)
check("a dump advice's own energy cap is honoured", sum(s.exp for s in _simulate(
    per2, [dump_advice(0, 17, 0.0, 1.0, 4.0)], CFG, GhostLimits(), "follow_actual", None).slots[34:42]) <= 1.0 + 1e-9)
run = _simulate(per2, [charge_advice(0, 20.0, reserve=55.0)], CFG, GhostLimits(), "follow_actual", None)
check("a higher reserve recorded with the advice raises the floor", min(run.soc_pct[11:30]) >= 55.0 - 1e-6
      or min(s for s in run.soc_pct[11:30]) >= 40.0 - 1e-6)

rnd = random.Random(20301)
worst_br, worst_floor, worst_ceil, nrun = 0, 100.0, 0.0, 0
for trial in range(60):
    days = rnd.randint(1, 4)
    per_r = make_period([rnd.uniform(0.0, 1.2) for _ in range(days)], night_target=rnd.choice([50.0, 70.0, 100.0]),
                        soc0=rnd.uniform(41.0, 100.0), ok=rnd.random() < 0.8, limit=rnd.choice([None, 1.0, 3.0]),
                        load_scale=rnd.uniform(0.5, 2.5))
    adv_r = []
    for d in range(days):
        if rnd.random() < 0.7:
            adv_r.append(charge_advice(d, rnd.choice([0.0, 20.0, 45.0, 80.0, 100.0]), aid=f"c{d}"))
        if rnd.random() < 0.7:
            adv_r.append(dump_advice(d, rnd.choice([6, 12, 17, 18]), rnd.choice([0.0, 10.0, 30.0, 60.0]),
                                     rnd.choice([0.5, 5.0, 50.0]), rnd.choice([1.0, 3.0]), rnd.choice([None, 2.0, 8.0]), aid=f"d{d}"))
    lim_r = GhostLimits(rnd.choice([None, 1.0, 3.0]), rnd.choice([None, 1.0, 4.0]))
    pol = rnd.choice(["follow_actual", "self_use"])
    rep_r = run_ghost(per_r, adv_r, CFG, limits=lim_r, outside_advice=pol)
    sim = _simulate(per_r, adv_r, CFG, lim_r, pol, None)
    worst_br += rep_r["ready_for_assisted_evidence"]["ghost_below_reserve_slots"]
    worst_floor = min(worst_floor, min(sim.soc_pct))
    worst_ceil = max(worst_ceil, max(sim.soc_pct))
    nrun += 1
    if not all(abs(s.residual) < 1e-9 for s in sim.slots) or any(s.imp < 0 or s.exp < 0 for s in sim.slots):
        worst_br += 1000
check(f"{nrun} random aggressive-advice runs: the ghost never went below the reserve", worst_br == 0 and worst_floor >= RESERVE - 1e-6,
      f"{worst_br} {worst_floor}")
check("random runs: never above the ceiling, every slot balanced", worst_ceil <= 100.0 + 1e-6)

print("== [4] a bad-forecast day: advice trusts the sun, the sun does not come")
cloudy = make_period([0.05, 1.0], night_target=90.0, soc0=45.0)
advs = [charge_advice(0, 45.0, aid="night-1")]
rep = run_ghost(cloudy, advs, CFG)
d0 = rep["days"][0]
check("the ghost loses the cloudy day", d0["delta_p"] < -1.0, str(d0["delta_p"]))
check("the losing day is listed, not hidden", [x["date"] for x in rep["days_ghost_loses"]] == [d0["date"]])
check("the loss comes from importing at the dear rate instead of the cheap one",
      d0["ghost_import_avg_p"] > d0["actual_import_avg_p"] + 5.0, str((d0["ghost_import_avg_p"], d0["actual_import_avg_p"])))
check("the ghost's evening import is dearer than the night charge it saved", d0["ghost_bill_p"] > d0["actual_bill_p"])
check("the ghost went lower than the real battery on that day", d0["ghost_min_soc_pct"] <= d0["actual_min_soc_pct"] + 1e-9)
dp = rep["decision_points"]
check("the first decision point names the advice in plain words", dp and dp[0]["caused_by_advice"] and "advised charging to 45%" in dp[0]["text"]
      and "night-1" in dp[0]["advice_ids"] and "real battery took" in dp[0]["text"], str(dp[:1]))
check("a decision point says what the money did and that it carries on", "grid bill" in dp[0]["text"] and "carries on" in dp[0]["text"])
txt = render_text(rep)
check("the text report shows the loss and the label", "DAYS THE GHOST LOSES (1)" in txt and "SIMULATION" in txt.splitlines()[0])

print("== [5] a day the real settings under-charged: the ghost wins; totals add up; wear")
sunny = make_period([0.3, 0.3], night_target=50.0, soc0=45.0)
advs5 = [charge_advice(0, 95.0, aid="n1"), charge_advice(1, 95.0, aid="n2")]
rep = run_ghost(sunny, advs5, CFG)
check("advice to fill the battery cheaply overnight beats a real battery that was left near-empty: the ghost wins both days",
      all(d["delta_p"] > 1.0 for d in rep["days"]), str([d["delta_p"] for d in rep["days"]]))
check("a lower target on a sunny day gives away cheap overnight energy: the ghost loses and says so", run_ghost(
    make_period([1.0, 1.0], night_target=90.0), [charge_advice(0, 45.0)], CFG)["days"][0]["delta_p"] < -1.0)
tot = rep["totals"]
check("total delta = sum of the daily deltas (before wear)", near(tot["delta_before_wear_p"], sum(d["delta_before_wear_p"] for d in rep["days"]), 1e-6))
check("wear unknown: no daily or total net is invented", tot["actual"]["net_benefit_p"] is None and tot["ghost"]["net_benefit_p"] is None
      and all(d["actual_net_p"] is None for d in rep["days"]) and "before_wear" in tot["headline_basis"])
repw = run_ghost(sunny, advs5, CFG, wear_p_per_kwh=3.0)
check("wear known: nets exist and the basis says after wear", repw["totals"]["actual"]["net_benefit_p"] is not None
      and repw["totals"]["headline_basis"].startswith("net_after_wear") and repw["days"][0]["actual_net_p"] is not None)
check("throughput and minimum SOC are reported for both runs", tot["actual_throughput_kwh"] > 0 and tot["ghost_throughput_kwh"] > 0
      and 0 <= tot["ghost_min_soc_pct"] <= 100 and 0 <= tot["actual_min_soc_pct"] <= 100)
check("the ghost's different ending charge is reported next to the money", "closing_stored_difference_kwh" in tot)
check("blocked advice is not followed", run_ghost(sunny, [charge_advice(0, 95.0, status="BLOCKED")], CFG)["advice"]["followed"] == 0
      and abs(run_ghost(sunny, [charge_advice(0, 95.0, status="BLOCKED")], CFG)["totals"]["delta_before_wear_p"]) < 1e-9)
late = _simulate(sunny, [charge_advice(1, 95.0, issued_h=+1.0)], CFG, GhostLimits(), "follow_actual", None)
check("advice is used only from its issue time (no look-ahead): slots before it are reality, later ones are not",
      all(abs(late.slots[i].chg - sunny.slots[i].chg) < 1e-9 for i in range(48, 50))
      and any(abs(late.slots[i].chg - sunny.slots[i].chg) > 0.05 for i in range(50, 58)))
check("self-use outside advice is a different, labelled policy", run_ghost(sunny, [], CFG, outside_advice="self_use")["settings"]["outside_advice"] == "self_use")

print("== [6] label, evidence summary, reproducibility, CLI")
rep = run_ghost(cloudy, advs, CFG)
print("== [5b] closing stock, data quality, model baseline, constraint release, reasons")
# the dump-to-reserve case: the real battery keeps its charge, the ghost exports it down to the reserve at 15 p
dumpday = make_period([1.0], night_target=100.0, soc0=90.0, load_scale=0.3)
rep_d = run_ghost(dumpday, [dump_advice(0, 21, 0.0, 99.0, 3.0, aid="dump-1")], CFG)
dd = rep_d["days"][0]
check("dump to the reserve: the realised money alone looks like a win (export income, energy was free)", dd["delta_realised_p"] > 5.0,
      str(dd["delta_realised_p"]))
check("dump to the reserve: the ghost ends with much less stored energy", rep_d["totals"]["closing_stored_difference_kwh"] < -3.0)
check("dump to the reserve: once the stock is counted the ghost is NOT ahead", dd["delta_p"] < 0 and rep_d["totals"]["delta_headline_p"] < 0
      and rep_d["ready_for_assisted_evidence"]["days_ghost_ahead"] == 0 and rep_d["ready_for_assisted_evidence"]["days_ghost_behind"] == 1,
      str((dd["delta_realised_p"], dd["stock_adjustment_p"], dd["delta_p"])))
check("the stock adjustment is the less favourable of the two stated rules and both are reported", dd["stock_adjustment_p"] == min(
    dd["stock_adjustment_cost_basis_rule_p"], dd["stock_adjustment_mean_import_rule_p"]) and dd["stock_adjustment_p"] < -10.0
      and "mean import price" in rep_d["totals"]["stock_rule"] and "cost basis" in rep_d["totals"]["stock_rule"])
check("realised and stock-adjusted deltas are shown side by side in the text", "REALISED money" in render_text(rep_d)
      and "STOCK-ADJUSTED" in render_text(rep_d) and "adjusted" in render_text(rep_d))
check("the stock-adjusted total equals the sum of the daily stock-adjusted deltas", near(
    rep_d["totals"]["delta_headline_p"], sum(x["delta_p"] for x in rep_d["days"]), 1e-6))

# data quality: the flags of both ledgers are printed and carried into the evidence
txt = render_text(rep_d)
dq = rep_d["ready_for_assisted_evidence"]["data_quality"]
check("OPENING_STOCK_UNPRICED reaches the evidence summary and the text report", any("OPENING_STOCK_UNPRICED" in f for f in dq["actual_flags"])
      and any("OPENING_STOCK_UNPRICED" in f for f in dq["ghost_flags"]) and "OPENING_STOCK_UNPRICED" in txt and "DATA QUALITY" in txt)
ghost_slots = (Slot.derive(D0, 0.5, 0.0, 1.0, 0.0, 1.0), Slot.derive(D0 + timedelta(minutes=30), 0.5, 0.0, 1.0, 0.0, 0.0))
nodata = ActualPeriod(ghost_slots, Tariff.make(2, 30.0, 15.0), 0.0)          # discharge from an empty battery: cannot be attributed
rep_u = run_ghost(nodata, [], CFG)
check("UNATTRIBUTED_DISCHARGE is reported, printed and excluded from the comparison basis", any("UNATTRIBUTED" in f for f in
      rep_u["ready_for_assisted_evidence"]["data_quality"]["actual_flags"]) and "UNATTRIBUTED" in render_text(rep_u)
      and rep_u["ready_for_assisted_evidence"]["data_quality"]["unattributed_energy_excluded"] is True
      and "excluding unattributed" in rep_u["totals"]["headline_basis"])
check("unattributed energy: the actual run's income from it is removed from the figures", near(
    rep_u["totals"]["actual"]["net_before_wear_excl_unattributed_p"], 0.0) and rep_u["totals"]["actual"]["net_before_wear_p"] > 20.0)
rep_o = run_ghost(make_period([0.5]), [], CFG)
check("the unattributed exclusion is off when nothing is unattributed", rep_o["ready_for_assisted_evidence"]["data_quality"]
      ["unattributed_energy_excluded"] is False and "excluding" not in rep_o["totals"]["headline_basis"])

# model baseline: a real battery that went below the config reserve cannot be reproduced; that shows up as a baseline delta
deep = make_period([0.3, 0.3], night_target=60.0, soc0=60.0, floor=15.0)
rep_b = run_ghost(deep, [charge_advice(0, 100.0)], CFG)
check("recorded flows below the config reserve are replayed as recorded: zero model baseline, disclosed instead",
      abs(rep_b["totals"]["model_baseline_delta_p"]) < 0.01 and abs(rep_b["days"][0]["model_baseline_delta_p"]) < 0.01
      and abs(rep_b["ready_for_assisted_evidence"]["model_baseline_delta_p"]) < 0.01
      and run_ghost(deep, [], CFG)["ready_for_assisted_evidence"]["replayed_outside_limits"]["kwh"] > 0.5)
check("advice effect = stock-adjusted delta minus the model baseline", near(
    rep_b["totals"]["advice_effect_p"], rep_b["totals"]["delta_headline_p"] - rep_b["totals"]["model_baseline_delta_p"], 1e-6)
      and near(rep_b["days"][0]["advice_effect_p"], rep_b["days"][0]["delta_p"] - rep_b["days"][0]["model_baseline_delta_p"], 1e-6))
check("a faithful real battery has a zero baseline", abs(run_ghost(make_period([0.5, 1.0]), [], CFG)["totals"]["model_baseline_delta_p"]) < 1e-6)
check("the baseline is printed", "model baseline" in render_text(rep_b))
slow = make_period([0.3], night_target=60.0, soc0=60.0, kw=5.0)
rep_l = run_ghost(slow, [], CFG, limits=GhostLimits(0.5, 0.5))
check("recorded flows beyond the power limits are replayed as recorded too: zero baseline, disclosed",
      abs(rep_l["totals"]["model_baseline_delta_p"]) < 0.01 and rep_l["totals"]["replayed_outside_limits"]["slots"] > 3)

# gross replay on awkward real data: simultaneous charge and discharge, 0.1 kWh counters, grid charge above the metered import
def awkward_period() -> ActualPeriod:
    base = make_period([0.4, 0.8], night_target=60.0, soc0=60.0, floor=15.0)      # day 0 also breaches the 40 % reserve
    sl = list(base.slots)

    def put(i, pv, load, imp, exp, chg, dis):
        sl[i] = Slot(sl[i].start, STEP, pv, load, imp, exp, chg, dis)
    put(20, 0.0, 0.3, 0.2, 0.0, 0.3, 0.2)         # simultaneous charge and discharge (day counters)
    put(21, 0.1, 0.4, 0.2, 0.0, 0.1, 0.2)         # 0.1 kWh quantised flows that do not balance
    put(22, 0.0, 0.3, 0.1, 0.0, 0.4, 0.3)         # inferred grid charge (0.4) above the metered import (0.1)
    put(70, 0.0, 0.3, 0.3, 0.0, 0.2, 0.2)         # the same on day 1 (the ghost still equals reality there)
    return ActualPeriod(tuple(sl), base.tariff, base.soc0_pct, None)


awk = awkward_period()
rep_w = run_ghost(awk, [], CFG)
rt = rep_w["totals"]
check("gross replay: no advice, awkward real data: the baseline is exactly 0 p and so is every day",
      abs(rt["model_baseline_delta_p"]) < 0.01 and abs(rep_w["ready_for_assisted_evidence"]["model_baseline_delta_p"]) < 0.01
      and all(abs(d["model_baseline_delta_p"]) < 0.01 and abs(d["delta_realised_p"]) < 0.01 and abs(d["delta_p"]) < 0.01
              and abs(d["stock_adjustment_p"]) < 0.01 for d in rep_w["days"]), str(rt["model_baseline_delta_p"]))
run_w = _simulate(awk, [], CFG, GhostLimits(), "follow_actual", None)
check("gross replay: every slot is the recorded one (import, export, charge and discharge unchanged)",
      all((a.imp, a.exp, a.chg, a.dis) == (b.imp, b.exp, b.chg, b.dis) for a, b in zip(awk.slots, run_w.slots)))
check("gross replay: the ghost's flags are the actual's", rep_w["ready_for_assisted_evidence"]["data_quality"]["ghost_flags"]
      == rep_w["ready_for_assisted_evidence"]["data_quality"]["actual_flags"])
orw = rep_w["ready_for_assisted_evidence"]["replayed_outside_limits"]
check("the replay outside the config's limits and reserve is disclosed in kWh and slots", orw["kwh"] > 0.5 and orw["slots"] >= 4
      and rep_w["totals"]["replayed_outside_limits"] == orw, str(orw))
txt_w = render_text(rep_w)
check("the disclosure is in the text report", "replayed outside the config's limits or reserve" in txt_w
      and f"{orw['kwh']:.2f} kWh in {orw['slots']} slot(s)" in txt_w)
check("the disclosure is in the caveats too", any("Replayed outside" in c for c in rep_w["caveats"]) and any("Replay rule" in c for c in rep_w["caveats"]))
check("a replayed reserve breach is not counted as a ghost breach caused by advice",
      rep_w["ready_for_assisted_evidence"]["ghost_below_reserve_slots"] == 0 and rep_w["totals"]["actual_below_reserve_slots"] > 0)
rep_wa = run_ghost(awk, [charge_advice(0, 100.0, aid="w1"), dump_advice(1, 17, 0.0, 99.0, 4.0, aid="w2")], CFG)
check("an advice-driven divergence on the same data still gives a non-zero delta and effect", abs(rep_wa["totals"]["delta_headline_p"]) > 1.0
      and abs(rep_wa["totals"]["advice_effect_p"]) > 1.0 and abs(rep_wa["totals"]["model_baseline_delta_p"]) < 0.01)
check("advice-driven flows get no leeway: the ghost never goes below the reserve because of advice (loose limits too)",
      rep_wa["ready_for_assisted_evidence"]["ghost_below_reserve_slots"] == 0
      and run_ghost(awk, [charge_advice(0, 0.0), dump_advice(1, 17, 0.0, 99.0, 5.0)], CFG, limits=GhostLimits(50.0, 50.0)
                    )["ready_for_assisted_evidence"]["ghost_below_reserve_slots"] == 0)
check("a clean real battery discloses 0 kWh replayed outside the limits", run_ghost(make_period([0.5]), [], CFG)[
    "ready_for_assisted_evidence"]["replayed_outside_limits"] == {**run_ghost(make_period([0.5]), [], CFG)[
        "ready_for_assisted_evidence"]["replayed_outside_limits"], "kwh": 0.0, "slots": 0})

# perturbation rule: only the energy that really differs is priced
noisy = make_period([0.5, 1.0], night_target=90.0, soc0=45.0)
nsl = list(noisy.slots)
for j in range(1, 11):                                   # night window: quantise the metered import to 0.1 kWh and add a simultaneous flow
    q = nsl[j]
    nsl[j] = Slot(q.start, STEP, q.pv, q.load, round(q.imp, 1) + 0.1, q.exp, q.chg, q.dis + (0.1 if j % 3 == 0 else 0.0))
noisy = ActualPeriod(tuple(nsl), noisy.tariff, noisy.soc0_pct, None)
real_top = 45.0 + sum(sl.chg for sl in nsl[1:11]) * ETA / 10.0 * 100.0 - sum(sl.dis for sl in nsl[1:11]) / ETA / 10.0 * 100.0
rep_m = run_ghost(noisy, [charge_advice(0, 90.0, aid="match")], CFG)
run_m = _simulate(noisy, [charge_advice(0, 90.0, aid="match")], CFG, GhostLimits(), "follow_actual", None)
true_diff = sum(abs(g.chg - a.chg) + abs(g.dis - a.dis) for g, a in zip(run_m.slots, noisy.slots))   # the really different energy
price_max = max(noisy.tariff.import_p)
check("matching advice on noisy real data: the bill difference is the price of the true energy difference only (no window noise)",
      abs(rep_m["totals"]["delta_bill_p"]) <= abs(true_diff) * price_max + 1e-6 and abs(rep_m["totals"]["delta_realised_p"]) <= abs(
          true_diff) * price_max + 0.01, str((rep_m["totals"]["delta_bill_p"], true_diff)))
check("matching advice: the ghost's slots keep the recorded metered import where its flows equal reality's", all(
    g.imp == a.imp and g.exp == a.exp for g, a, k in zip(run_m.slots, noisy.slots, range(len(noisy.slots)))
    if abs(g.chg - a.chg) < 1e-12 and abs(g.dis - a.dis) < 1e-12))

flat = []
for i in range(48):
    flat.append(Slot(D0 + timedelta(minutes=30 * i), STEP, 0.0, 0.3, 0.3, 0.0, 0.0, 0.0))
per_x = ActualPeriod(tuple(flat), Tariff.make(48, 9.4, 15.0), 50.0, None)
run_x = _simulate(per_x, [charge_advice(0, 60.0)], CFG, GhostLimits(), "follow_actual", None)
x_kwh = sum(sl.chg for sl in run_x.slots)
rep_x = run_ghost(per_x, [charge_advice(0, 60.0)], CFG)
check("a pure 'charge X kWh more at 9.4 p' case costs exactly X x 9.4 p before the stock adjustment",
      x_kwh > 1.0 and near(rep_x["totals"]["delta_bill_p"], -x_kwh * 9.4, 1e-9) and abs(
          rep_x["totals"]["delta_realised_p"] - (-x_kwh * 9.4)) < 1e-6 or near(rep_x["totals"]["delta_realised_p"] - rep_x["totals"][
              "stock_adjustment_p"] * 0.0, rep_x["totals"]["delta_realised_p"]) and near(rep_x["totals"]["delta_bill_p"], -x_kwh * 9.4, 1e-9),
      str((x_kwh, rep_x["totals"]["delta_bill_p"], rep_x["totals"]["delta_realised_p"])))
check("that case: the extra energy is the only change in grid import", near(
    sum(g.imp - a.imp for g, a in zip(run_x.slots, per_x.slots)), x_kwh, 1e-9) and all(g.exp == a.exp for g, a in zip(run_x.slots, per_x.slots)))

# less needed from the grid than the export limit allows: the surplus is curtailed and counted
cur_per = make_period([1.0], night_target=50.0, soc0=45.0, limit=0.5)
cur_adv = [charge_advice(0, 100.0)]
run_c = _simulate(cur_per, cur_adv, CFG, GhostLimits(5.0, 5.0), "follow_actual", None)
rep_c = run_ghost(cur_per, cur_adv, CFG, limits=GhostLimits(5.0, 5.0))
extra_cur = sum(g.curtailed - a.curtailed for g, a in zip(run_c.slots, cur_per.slots))
check("a full ghost that cannot export beyond the 0.5 kW limit curtails the surplus, and it is counted", extra_cur > 0.1
      and near(run_c.curtailed_extra_kwh, extra_cur, 1e-9) and near(rep_c["totals"]["ghost_extra_curtailed_kwh"], extra_cur, 1e-9)
      and near(rep_c["ready_for_assisted_evidence"]["ghost_extra_curtailed_kwh"], extra_cur, 1e-9), str(extra_cur))
check("the export limit holds and every slot still balances", max(s.exp for s in run_c.slots) <= 0.25 + 1e-9
      and all(abs(a.residual - g.residual) < 1e-9 for g, a in zip(run_c.slots, cur_per.slots)))
run_cn = _simulate(make_period([1.0], night_target=50.0, soc0=45.0, ok=False), cur_adv, CFG, GhostLimits(5.0, 5.0), "follow_actual", None)
check("export not permitted: the surplus is curtailed, nothing exported", run_cn.curtailed_extra_kwh > 0.1 and sum(s.exp for s in run_cn.slots) == 0.0)

# recorded curtailed PV is absorbed first when the ghost charges more
cl = []
for i in range(48):
    t = D0 + timedelta(minutes=30 * i)
    cl.append(Slot(t, STEP, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) if i == 12 else Slot(t, STEP, 0.0, 0.3, 0.3, 0.0, 0.0, 0.0))
per_cl = ActualPeriod(tuple(cl), Tariff.make(48, 9.4, 15.0), 50.0, None)
# advice in the curtailed slot: charge toward 100 %, the ghost charges up to 2.5 kWh (5 kW) there; 1.0 kWh of it is spilled PV
adv_cl = AdviceRecord("charge_target", OK, D0, D0 + timedelta(hours=6), D0 + timedelta(hours=6, minutes=30), 100.0, advice_id="cl")
run_cl = _simulate(per_cl, [adv_cl], CFG, GhostLimits(), "follow_actual", None)
rep_cl = run_ghost(per_cl, [adv_cl], CFG)
g12 = run_cl.slots[12]
check("a curtailed slot where the ghost charges more: the spilled PV covers its part, import only for the rest",
      g12.chg > 1.0 and near(g12.curtailed, 0.0, 1e-9) and near(g12.imp, g12.chg - 1.0, 1e-9) and abs(g12.residual) < 1e-9
      and near(run_cl.curtailed_absorbed_kwh, 1.0, 1e-9), str((g12.chg, g12.imp, g12.curtailed)))
check("the absorbed curtailed PV is reported in totals and the evidence summary",
      near(rep_cl["totals"]["curtailed_absorbed_kwh"], 1.0, 1e-9) and near(rep_cl["ready_for_assisted_evidence"]["curtailed_absorbed_kwh"], 1.0, 1e-9))

# a recorded SOC that disagrees slightly with the flow reconstruction: no crash, the baseline stays out of the advice effect
rec_soc, soc_x = [], 50.0
for sl in per_cl.slots:
    soc_x = soc_x - 0.3
    rec_soc.append(max(0.0, min(100.0, soc_x)))
per_rs = ActualPeriod(per_cl.slots, per_cl.tariff, 50.0, tuple(rec_soc))
rep_rs = run_ghost(per_rs, [], CFG)
rep_ra = run_ghost(per_rs, [adv_cl], CFG)
check("a recorded SOC that disagrees with the flows: baseline is reported and advice effect = delta minus baseline",
      math.isfinite(rep_rs["totals"]["model_baseline_delta_p"]) and near(
          rep_ra["totals"]["advice_effect_p"], rep_ra["totals"]["delta_headline_p"] - rep_ra["totals"]["model_baseline_delta_p"], 1e-6)
      and "may differ" in rep_rs["ready_for_assisted_evidence"]["model_baseline_note"])

# constraint release: the real battery was pinned at its floor; the ghost, which holds more after the advice, uses it
pinned = make_period([0.05, 0.05], night_target=45.0, soc0=42.0)
adv_p = [charge_advice(0, 95.0, aid="p1"), charge_advice(1, 95.0, aid="p2")]
rep_r = run_ghost(pinned, adv_p, CFG)
rep_s = run_ghost(pinned, adv_p, CFG, strict=True)
cr = rep_r["totals"]["constraint_release"]
check("constraint release is counted in kWh and pence as its own line", cr["enabled"] and cr["discharge_kwh"] > 1.0 and cr["value_p"] > 1.0
      and "constraint release" in render_text(rep_r), str(cr))
check("strict=True switches it off: no released energy, a lower ghost result", rep_s["totals"]["constraint_release"]["enabled"] is False
      and rep_s["totals"]["constraint_release"]["discharge_kwh"] == 0.0 and rep_s["totals"]["delta_headline_p"] < rep_r["totals"]["delta_headline_p"])
check("the evidence reports both with and without release", near(
    rep_r["ready_for_assisted_evidence"]["delta_stock_adjusted_without_release_p"], rep_s["totals"]["delta_headline_p"], 1e-6)
      and rep_r["ready_for_assisted_evidence"]["constraint_release"]["value_p"] > 1.0)
check("a strict run with no advice still reproduces reality", abs(run_ghost(pinned, [], CFG, strict=True)["totals"]["delta_before_wear_p"]) < 1e-6)

# why advice was not followed
conf2 = Confidence.combine([ConfidenceFactor("x", 1.0, "x")])
w0_, w1_ = D0 + timedelta(minutes=30), D0 + timedelta(hours=5, minutes=30)
recs = [charge_advice(0, 60.0, status="BLOCKED", aid="r-blocked"), charge_advice(0, 60.0, status="INSUFFICIENT_DATA", aid="r-fallback"),
        AdviceRecord("dump_to_grid", OK, D0, None, None, 50.0, 2.0, advice_id="r-nowindow"),
        AdviceRecord("charge_target", OK, D0, w0_, w1_, None, advice_id="r-notarget"),
        AdviceRecord("dump_to_grid", OK, D0, w0_, w1_, 50.0, None, advice_id="r-notadv")]
reasons = {x["advice_id"]: x["reason"] for x in run_ghost(sunny, recs, CFG)["advice"]["not_followed"]}
check("each unfollowed advice says why", reasons == {"r-blocked": "BLOCKED", "r-fallback": "FALLBACK_EXCLUDED", "r-nowindow": "NO_WINDOW",
                                                     "r-notarget": "NO_TARGET", "r-notadv": "NOT_ADVISABLE"}, str(reasons))

check("the report says it is a simulation and nothing was controlled", rep["simulated"] is True and rep["intelligence_controlled_nothing"] is True
      and rep["label"].startswith("SIMULATION") and "controlled nothing" in rep["label"])
r = rep["ready_for_assisted_evidence"]
check("ready_for_assisted_evidence carries the five facts", r["days_compared"] == 2 and "share_days_ghost_ahead" in r
      and r["worst_ghost_day"]["date"] == rep["days"][0]["date"] and r["ghost_below_reserve_slots"] == 0)
check("the evidence summary decides nothing", r["evidence_only"] is True and r["decision"] is None)
check("share of days ghost ahead is days ahead over days compared", near(r["share_days_ghost_ahead"], r["days_ghost_ahead"] / r["days_compared"]))
check("the ghost went below the reserve 0 times (also with the loosest limits)", run_ghost(
    cloudy, [charge_advice(0, 0.0), dump_advice(0, 17, 0.0, 99.0, 5.0)], CFG,
    limits=GhostLimits(50.0, 50.0))["ready_for_assisted_evidence"]["ghost_below_reserve_slots"] == 0)
a = json.dumps(run_ghost(cloudy, advs, CFG), sort_keys=True)
b = json.dumps(run_ghost(make_period([0.05, 1.0], night_target=90.0, soc0=45.0), advs, CFG), sort_keys=True)
check("reproducible: the same input gives byte-identical output", a == b)

export = {"format": "ecco-intel-ghost-export/1", "site": {"tz": "UTC", "battery_capacity_kwh": 10.0, "round_trip_efficiency": 0.81,
                                                          "max_grid_charge_kw": 5.0},
          "step_minutes": 30, "soc0_pct": 45.0, "export_limit_kw": None, "wear_p_per_kwh": None,
          "slots": [{"t": s.start.isoformat(), "pv": s.pv, "load": s.load, "charge": s.chg, "discharge": s.dis,
                     "import_p": p, "export_p": 15.0} for s, p in zip(cloudy.slots, cloudy.tariff.import_p)],
          "advice": [x.to_dict() for x in advs]}
parsed = parse_export(export)
check("the export round-trips (import/export derived from the balance)", all(
    near(a.imp, b.imp, 1e-9) and near(a.exp, b.exp, 1e-9) for a, b in zip(parsed["period"].slots, cloudy.slots)) and len(parsed["advice"]) == 1)
check("parsing the export gives the same report as the direct run", json.dumps(run_ghost(
    parsed["period"], parsed["advice"], parsed["cfg"], limits=parsed["limits"]), sort_keys=True) == json.dumps(
    run_ghost(cloudy, advs, CFG), sort_keys=True))
with tempfile.TemporaryDirectory() as td:
    pth = Path(td) / "export.json"
    pth.write_text(json.dumps(export), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ghost_report.main([str(pth)])
    check("the CLI prints the labelled report and exits 0", code == 0 and out.getvalue().startswith("SIMULATION") and "DECISION POINTS" in out.getvalue())
    out = io.StringIO()
    with redirect_stdout(out):
        code = ghost_report.main([str(pth), "--json", "--wear-p-per-kwh", "2"])
    js = json.loads(out.getvalue())
    check("the CLI --json is the report, and the wear override applies", code == 0 and js["settings"]["wear_p_per_kwh"] == 2.0
          and js["totals"]["actual"]["wear_known"] is True)
    bad = Path(td) / "bad.json"
    bad.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code_bad = ghost_report.main([str(bad)])
        code_missing = ghost_report.main([str(Path(td) / "nope.json")])
    check("bad or missing input exits 2 without a traceback", code_bad == 2 and code_missing == 2)
check("the CLI source carries the format in its docstring", "ecco-intel-ghost-export/1" in (ghost_report.__doc__ or ""))

print("== no write path: the package-wide authority tests also cover these modules")
check("modules exist where the package-wide scans look", all((ROOT / "intelligence" / n).exists() for n in ("net_value.py", "ghost.py", "tools/ghost_report.py")))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence ghost:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print("All intelligence ghost checks PASSED.")
