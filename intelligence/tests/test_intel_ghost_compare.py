#!/usr/bin/env python3
"""Ghost, diagnostics-only: the existing schedule against Intelligence's advice (intelligence/ghost_compare.py) on a SYNTHETIC
house (fictional year 2030), plus the plain-text report on a golden diagnostics download.

  [1] the block with a verified tariff: money, SOC (minimum and end of day, both runs, differences, each checked against an
      independent reading of the history), reserve margins, uncertainty, advice followed or not, the period totals
  [2] no verified tariff: NO MONEY, no pence figure anywhere, the behaviour comparison stays
  [3] the verdict rule: noise = efficiency spread + stock-rule spread + baseline error (floor 0.5 p); beyond noise only; within
      the noise never a win; the boundary; recomputed independently from the block's own numbers on every day
  [3b] an export price that is NOT verified: where the advice run exports a different amount than the existing schedule its export
      income difference is unpriced (0 in both runs), so no ahead / behind verdict is given there (review finding G3)
  [4] reserve protection: no breach on a normal run; a breach is flagged (period, day, margin, dates); a breach only at the
      altered efficiencies is told apart; the existing schedule's own dips are reported
  [5] failures are small blocks with a constant reason: no history, too little history, no advice, invalid advice rows only,
      an exception (class name only), a non-finite number; the size bound (oldest days dropped, then SIZE_BOUND)
  [6] nothing leaks: hostile advice ids and extra fields, only constant words and dates, JSON-safe, deterministic, inputs unchanged
  [7] the feed is unchanged by its new `detail` hook; ghost.py's new per-day end SOC is the end of the last slot
  [8] the plain-text report on a golden download; the tool reads a full HA download, the ghost key or the block itself
  [9] no write path (static)
The synthetic house is generated here by an independent simple rule set, not by ghost.py.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import ghost, ghost_compare as gc, ghost_feed as gf, synthetic  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.tariff import NO_VALUE, VERIFIED_FROM_INTEGRATION, RateSlot, TariffResult  # noqa: E402
from intelligence.timeutil import HOUR, ts, utc_from_ts  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
CFG = SiteConfig(tz="UTC", round_trip_efficiency=0.81, battery_capacity_kwh=10.0, max_grid_charge_kw=5.0,
                 user_reserve_soc_pct=40.0, technical_min_soc_pct=10.0, max_soc_pct=100.0, pv_array_kwp=None)
ETA = 0.9
START = date(2030, 1, 1)
DAYS = 16
NIGHT = range(1, 6)
FIXTURES = ROOT / "intelligence" / "tests" / "fixtures" / "ghost_diag"


def house(night_target=80.0, floor_pct: float = 40.0, days: int = DAYS, night=NIGHT) -> History:
    """Independent house: charge from the grid in the cheap hours to the night target (a float, or a date -> target dict),
    otherwise self-use between `floor_pct` and full. The hourly mean SOC is the mean of the hour's start and end."""
    base = synthetic.make_history(START, days, CFG, seed=4, with_soc=False)
    cap, soc, out = CFG.battery_capacity_kwh, 70.0, []
    for s in sorted(base.by_start):
        b = base.by_start[s]
        t = utc_from_ts(s)
        pv, load = b.e["pv"], b.e["load"]
        tgt = night_target.get(t.date(), 80.0) if isinstance(night_target, dict) else night_target
        stored = soc / 100.0 * cap
        chg = dis = 0.0
        net = pv - load
        if t.hour in night and soc < tgt - 1e-9:
            chg = min(CFG.max_grid_charge_kw, (tgt / 100.0 * cap - stored) / ETA)
        elif net > 0:
            chg = min(net, (cap - stored) / ETA)
        else:
            floor = max(floor_pct / 100.0 * cap, tgt / 100.0 * cap) if t.hour in night else floor_pct / 100.0 * cap
            dis = min(-net, max(0.0, stored - floor) * ETA)
        new = stored + chg * ETA - dis / ETA
        grid = load + chg - pv - dis
        rec = HourRecord(start=s)
        rec.e.update({"pv": pv, "load": load, "imp": max(0.0, grid), "exp": max(0.0, -grid), "chg": chg, "dis": dis})
        rec.soc_mean = (soc + new / cap * 100.0) / 2.0
        soc = new / cap * 100.0
        out.append(rec)
    return History(out)


def tariff(history: History, expensive_nights=(), price: float = 40.0, cover_hours: int | None = None, night=NIGHT) -> TariffResult:
    first, last = history.first_last()
    end = last + timedelta(hours=1) if cover_hours is None else first + timedelta(hours=cover_hours)
    slots, t = [], first
    while t < end:
        cheap = t.hour in night
        slots.append(RateSlot(t, t + timedelta(minutes=30), (price if t.date() in expensive_nights else 7.0) if cheap else 30.0))
        t += timedelta(minutes=30)
    return TariffResult("import", VERIFIED_FROM_INTEGRATION, tuple(slots))


def night_advice(h: History, target: float, only: date | None = None, status: str = "OK", reserve: float = 40.0) -> list[dict]:
    first, last = h.first_last()
    rows, d = [], first.date() + timedelta(days=1)
    while d <= last.date():
        if only is None or d == only:
            issued = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=1)
            rows.append({"kind": "charge_target", "status": status, "issued_at": issued.isoformat(),
                         "window_start": (issued + timedelta(hours=2)).isoformat(),
                         "window_end": (issued + timedelta(hours=7)).isoformat(), "target_soc_pct": target,
                         "effective_reserve_pct": reserve, "advice_id": f"t:{d.isoformat()}"})
        d += timedelta(days=1)
    return rows


def raises(fn, exc=Exception) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def leaves(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from ((f"{k}.{p}", x) for p, x in leaves(v))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from ((f"[{i}].{p}", x) for p, x in leaves(v))
    else:
        yield "", o


def money_paths(o) -> list[str]:
    return [p for p, _ in leaves(o) if re.search(r"(^|\.|\])[a-z_]*_p(\.|$|_)|\.p\.", p) or p.split(".")[0].endswith("_p")]


def structure(o):
    """The key structure of a JSON value (dict keys recursively; a list by its first element)."""
    if isinstance(o, dict):
        return {k: structure(v) for k, v in sorted(o.items())}
    if isinstance(o, list):
        return [structure(o[0])] if o else []
    return type(o).__name__ if not isinstance(o, (int, float)) or isinstance(o, bool) else "number"


H0 = house(80.0)
T0 = tariff(H0)
BAD = date(2030, 1, 9)

print("== [1] the block with a verified tariff")
rows = night_advice(H0, 80.0)
rows += night_advice(H0, 100.0, only=BAD)                      # a second, later advice on the bad night: see [3]
B = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0)
check("status OK, money available, the schema and the simulation markers", B["status"] == "OK" and B["reason"] is None
      and B["money_available"] is True and B["schema"] == gc.SCHEMA == "ecco-intel-ghost-diagnostics/1" and B["simulated"] is True
      and B["read_only"] is True and B["intelligence_controlled_nothing"] is True and "SIMULATION" in B["banner"], str(B["status"]))
check("the days are the newest local days, oldest first; the period covers them",
      [d["date"] for d in B["days"]] == sorted(d["date"] for d in B["days"]) and len(B["days"]) == 14 and B["days_dropped"] == 0
      and B["period"]["hours"] >= 14 * 24, str(B["period"]))
feed = gf.build_ghost_feed(H0, rows, CFG, import_tariff=T0, max_bytes=1 << 20)
check("every day carries money, SOC, reserve and advice figures, and they equal the feed's own figures for that day",
      all(set(d) >= {"existing_net_p", "advice_net_p", "advice_effect_p", "noise_p", "verdict", "existing_min_soc_pct",
                     "advice_min_soc_pct", "min_soc_diff_pct", "existing_end_soc_pct", "advice_end_soc_pct", "end_soc_diff_pct",
                     "existing_reserve_margin_pct", "advice_reserve_margin_pct", "advice_breach", "advice_in_force_hours",
                     "advice_followed"} for d in B["days"])
      and all(d["existing_net_p"] == fd["actual_net_before_wear_p"] and d["advice_net_p"] == fd["ghost_net_before_wear_p"]
              and d["advice_effect_p"] == fd["advice_effect_p"] and d["existing_min_soc_pct"] == fd["actual_min_soc_pct"]
              and d["advice_min_soc_pct"] == fd["ghost_min_soc_pct"] for d, fd in zip(B["days"], feed["days"])), str(B["days"][0]))

# the end-of-day SOC, read independently from the history: the end of a day's last hour is the mean of that hour's and the
# next hour's mean SOC (the period's last hour: its own)
def end_soc(day: str) -> float:
    last = max(s for s in H0.by_start if utc_from_ts(s).date().isoformat() == day)
    nxt = H0.get(last + HOUR)
    a = H0.get(last).soc_mean
    return a if nxt is None else (a + nxt.soc_mean) / 2.0


check("the existing schedule's end-of-day SOC equals the independent reading of the recorded SOC (every day)",
      all(abs(d["existing_end_soc_pct"] - end_soc(d["date"])) <= 0.06 for d in B["days"]),
      str([(d["date"], d["existing_end_soc_pct"], round(end_soc(d["date"]), 2)) for d in B["days"] if abs(d["existing_end_soc_pct"] - end_soc(d["date"])) > 0.06][:3]))
EVE = range(21, 24)
H_eve = house(80.0, night=EVE)
eve_rows = []
for d_ in range(2, DAYS):
    issued = datetime(2030, 1, d_, 20, tzinfo=UTC)
    eve_rows.append({"kind": "charge_target", "status": "OK", "issued_at": issued.isoformat(), "window_start": (issued + timedelta(hours=1)).isoformat(),
                     "window_end": (issued + timedelta(hours=4)).isoformat(), "target_soc_pct": 80.0, "effective_reserve_pct": 40.0, "advice_id": f"e:{d_}"})
Ev = gc.build_ghost_comparison(H_eve, eve_rows, CFG, import_tariff=tariff(H_eve, night=EVE))


def end_soc_of(hist: History, day: str) -> float:
    last = max(s for s in hist.by_start if utc_from_ts(s).date().isoformat() == day)
    nxt = hist.get(last + HOUR)
    a = hist.get(last).soc_mean
    return a if nxt is None else (a + nxt.soc_mean) / 2.0


check("a house that charges in the evening ends each day well above its minimum, and the block's end-of-day SOC is that end, not the minimum",
      Ev["status"] == "OK" and all(abs(d["existing_end_soc_pct"] - end_soc_of(H_eve, d["date"])) <= 0.06 for d in Ev["days"])
      and sum(1 for d in Ev["days"] if d["existing_end_soc_pct"] - d["existing_min_soc_pct"] > 10.0) >= 10
      and all(abs(d["advice_end_soc_pct"] - d["existing_end_soc_pct"]) <= 3.0 for d in Ev["days"]),
      str([(d["date"], d["existing_end_soc_pct"], d["existing_min_soc_pct"], round(end_soc_of(H_eve, d["date"]), 1)) for d in Ev["days"][:3]]))
check("the SOC differences are advice minus existing, to a tenth",
      all(abs(d["min_soc_diff_pct"] - round(d["advice_min_soc_pct"] - d["existing_min_soc_pct"], 1)) < 1e-9
          and abs(d["end_soc_diff_pct"] - round(d["advice_end_soc_pct"] - d["existing_end_soc_pct"], 1)) < 1e-9 for d in B["days"]))
check("the reserve margins are the minimum SOC minus the reserve in force, for both runs",
      all(abs(d["existing_reserve_margin_pct"] - round(d["existing_min_soc_pct"] - B["reserve"]["in_force_pct"], 1)) <= 0.11
          and abs(d["advice_reserve_margin_pct"] - round(d["advice_min_soc_pct"] - B["reserve"]["in_force_pct"], 1)) <= 0.11
          for d in B["days"]) and B["reserve"]["in_force_pct"] == 40.0, str(B["reserve"]))
t = B["totals"]
check("the period totals carry money (existing, advice, realised, stock, baseline, effect), SOC and the closing stock",
      all(k in t for k in ("existing_net_p", "advice_net_p", "realised_difference_p", "stock_adjustment_p", "stock_adjusted_difference_p",
                           "baseline_p", "advice_effect_p", "existing_min_soc_pct", "advice_min_soc_pct", "min_soc_diff_pct",
                           "existing_end_soc_pct", "advice_end_soc_pct", "end_soc_diff_pct", "closing_stored_difference_kwh")), str(t))
check("the period totals agree with the feed's", t["advice_effect_p"] == feed["totals"]["advice_effect_p"]
      and t["existing_net_p"] == feed["totals"]["actual_net_before_wear_p"] and t["advice_min_soc_pct"] == feed["totals"]["ghost_min_soc_pct"])
check("advice followed and not followed are counted (the second advice on the bad night supersedes the first, both followed)",
      B["advice"]["followed"] == feed["advice"]["followed"] > 0 and B["advice"]["not_followed"] == {}
      and B["advice"]["records_in_period"] == feed["advice"]["records_in_period"], str(B["advice"]))
check("the recorded reserve of the followed advice is shown next to the reserve in force", B["reserve"]["advice_recorded_max_pct"] == 40.0)
u = B["uncertainty"]
check("the uncertainty carries the stock rules, the efficiency band, the sensitivity, the noise and the verdict",
      u["round_trip_efficiency_pct"] == {"base": 81.0, "minus": 78.0, "plus": 84.0} and "closing stock" in u["closing_stock_rules"]
      and set(u["components_p"]) == {"efficiency_spread", "stock_rule_spread", "baseline_error"}
      and set(u["effect_at_efficiency_p"]) == {"minus", "base", "plus"} and u["verdict"] in gc.VERDICTS
      and u["noise_floor_p"] == 0.5 and "rule" in u, str(u))
check("the data-quality flags and the model baseline are visible", "ghost_model_flags" in B["data_quality"]
      and isinstance(u["data_quality_flags"], list))

print("== [2] no verified tariff: NO MONEY, behaviour only")
N = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=None)
check("status OK, money_available False, the tariff NOT_VERIFIED, the verdict not assessed",
      N["status"] == "OK" and N["money_available"] is False and N["tariff"]["import"] == "NOT_VERIFIED"
      and N["uncertainty"]["verdict"] == "NOT_ASSESSED_NO_MONEY", str(N["uncertainty"].get("verdict")))
check("no pence figure anywhere (totals, days, uncertainty): not one key that names money", money_paths(N) == [], str(money_paths(N)[:6]))
check("the behaviour comparison stays: SOC both runs, differences, reserve margins and breach, advice followed",
      all(k in N["days"][0] for k in ("existing_min_soc_pct", "advice_min_soc_pct", "min_soc_diff_pct", "existing_end_soc_pct",
                                     "advice_end_soc_pct", "end_soc_diff_pct", "existing_reserve_margin_pct", "advice_reserve_margin_pct",
                                     "advice_breach", "advice_followed")) and "verdict" not in N["days"][0]
      and N["reserve"]["verdict"] in gc.RESERVE_VERDICTS and N["advice"]["followed"] > 0)
check("the notes say why there is no money", any("NO_VERIFIED_TARIFF" in n for n in N["data_quality"]["notes"]), str(N["data_quality"]["notes"]))
T_short = tariff(H0, cover_hours=20)                              # verified, but covering under 24 usable hours
S = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T_short)
check("a verified tariff covering under 24 hours is no money either (and says so)", S["money_available"] is False
      and money_paths(S) == [] and any("TARIFF_COVERS_TOO_LITTLE" in n for n in S["data_quality"]["notes"]))
NV = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=TariffResult("import", NO_VALUE))
check("an unverified tariff object is no money", NV["money_available"] is False and money_paths(NV) == [])
T_part = tariff(H0, cover_hours=8 * 24)                           # the rates cover the first 8 days only
P = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T_part)
check("rates covering only part of the history: money for the covered days only, and the period says so",
      P["money_available"] is True and P["period"]["hours"] <= 8 * 24 and P["period"]["longest_usable_run_hours"] == 14 * 24
      and len(P["days"]) <= 9, str(P["period"]))

print("== [3] the verdict rule")
check("the rule's boundaries: beyond the noise only, strictly",
      gc._verdict(1.0, 1.0, True) == gc.V_WITHIN and gc._verdict(-1.0, 1.0, True) == gc.V_WITHIN
      and gc._verdict(1.0001, 1.0, True) == gc.V_AHEAD and gc._verdict(-1.0001, 1.0, True) == gc.V_BEHIND
      and gc._verdict(0.0, 0.5, True) == gc.V_WITHIN and gc._verdict(99.0, 0.5, False) == gc.V_NONE)


def rederive(block: dict) -> list[str]:
    """Every verdict of a money block, recomputed from the block's own published numbers."""
    bad = []
    uu = block["uncertainty"]
    comp = uu["components_p"]
    noise = max(0.5, comp["efficiency_spread"] + comp["stock_rule_spread"] + comp["baseline_error"])
    if abs(noise - uu["noise_p"]) > 0.02:
        bad.append(f"period noise {noise} vs {uu['noise_p']}")
    eff = uu["advice_effect_p"]
    want = gc.V_NONE if block["advice"]["followed"] == 0 else gc.V_AHEAD if eff > uu["noise_p"] + 0.011 else gc.V_BEHIND if eff < -uu["noise_p"] - 0.011 else None
    if want is not None and uu["verdict"] != want:
        bad.append(f"period verdict {uu['verdict']} vs {want}")
    if uu["verdict"] == gc.V_AHEAD and not eff > uu["noise_p"] - 0.011 or uu["verdict"] == gc.V_BEHIND and not eff < -uu["noise_p"] + 0.011:
        bad.append("a win or loss claimed within the noise")
    for d in block["days"]:
        if d["verdict"] == gc.V_AHEAD and not d["advice_effect_p"] > d["noise_p"] - 0.011:
            bad.append(f"{d['date']} ahead within noise")
        if d["verdict"] == gc.V_BEHIND and not d["advice_effect_p"] < -d["noise_p"] + 0.011:
            bad.append(f"{d['date']} behind within noise")
        if d["verdict"] == gc.V_WITHIN and abs(d["advice_effect_p"]) > d["noise_p"] + 0.011:
            bad.append(f"{d['date']} within but beyond noise")
        if d["noise_p"] < 0.5:
            bad.append(f"{d['date']} noise below the floor")
    return bad


H_exp = house({BAD: 100.0})
T_exp = tariff(H_exp, expensive_nights=(BAD,), price=100.0)
scen = {"matching advice": (H0, T0, night_advice(H0, 80.0)), "losing night": (H0, tariff(H0, (BAD,)), night_advice(H0, 100.0, only=BAD)),
        "saving night": (H_exp, T_exp, night_advice(H_exp, 80.0, only=BAD)), "no advice followed": (H0, T0, night_advice(H0, 80.0, status="BLOCKED"))}
for name, (hh, tt, aa) in scen.items():
    blk = gc.build_ghost_comparison(hh, aa, CFG, import_tariff=tt)
    check(f"{name}: status OK and every verdict agrees with the rule recomputed from the block's numbers", blk["status"] == "OK"
          and rederive(blk) == [], str(rederive(blk)[:3]))
check("matching advice is within the noise (a zero effect is never a win)", gc.build_ghost_comparison(H0, night_advice(H0, 80.0), CFG, import_tariff=T0)["uncertainty"]["verdict"] == gc.V_WITHIN)
nf = gc.build_ghost_comparison(H0, night_advice(H0, 80.0, status="BLOCKED"), CFG, import_tariff=T0)
check("blocked advice only: nothing followed, NO_ADVICE_EFFECT, the reasons are counted, every day NO_ADVICE_EFFECT",
      nf["advice"]["followed"] == 0 and nf["advice"]["not_followed"].get("BLOCKED", 0) > 0 and nf["uncertainty"]["verdict"] == gc.V_NONE
      and all(d["verdict"] == gc.V_NONE for d in nf["days"]) and nf["uncertainty"]["advice_effect_p"] == 0.0)
lose = gc.build_ghost_comparison(H0, night_advice(H0, 100.0, only=BAD), CFG, import_tariff=tariff(H0, (BAD,)))
dd = next(d for d in lose["days"] if d["date"] == BAD.isoformat())
check("the losing night is negative on its day and the days around it are untouched",
      dd["advice_effect_p"] < -1.0 and dd["advice_net_p"] < dd["existing_net_p"] and sum(1 for d in lose["days"] if d["verdict"] == gc.V_NONE) >= 5,
      str(dd))
check("the day's noise includes the efficiency band, the stock rules and the baseline (never below 0.5 p)",
      all(d["noise_p"] >= 0.5 for d in lose["days"]) and dd["noise_p"] > 0.5)


def seam(edit_base=None, edit_sens=None, breach=None):
    """Wrap ghost_feed.run_ghost: the first call (the base run) and the two efficiency runs (minus, plus) are edited by the given
    functions after the real simulation ran, to drive the block's own logic with chosen numbers."""
    real = gf.run_ghost
    calls = {"n": 0}

    def wrapped(*a, **k):
        rep = real(*a, **k)
        i = calls["n"]
        calls["n"] += 1
        if i == 0 and edit_base:
            edit_base(rep)
        if i in (1, 2) and edit_sens:
            edit_sens(i, rep)
        if breach is not None:
            breach(i, rep)
        return rep
    return real, wrapped


def run_seam(edit_base=None, edit_sens=None, breach=None, hist=H0, tar=T0, adv=None, **kw):
    real, wrapped = seam(edit_base, edit_sens, breach)
    gf.run_ghost = wrapped
    try:
        return gc.build_ghost_comparison(hist, adv if adv is not None else night_advice(hist, 80.0), CFG, import_tariff=tar, **kw)
    finally:
        gf.run_ghost = real


def force(effect: float, spread: float = 1.0, day: float | None = None, day_spread: float = 1.0, plus_spread: float | None = None):
    """(edit_base, edit_sens): the base run's period and per-day advice effect set to `effect` / `day`, the two efficiency runs
    to that moved by +/- the spread (so the efficiency component of the noise is exactly `spread` / `day_spread`)."""
    d0 = effect if day is None else day

    def edit_base(rep):
        rep["totals"]["advice_effect_p"] = effect
        for d in rep["days"]:
            d["advice_effect_p"] = d0

    def edit_sens(i, rep):
        sign = 1.0 if i == 1 else -1.0
        rep["totals"]["advice_effect_p"] = effect + sign * (spread if i == 1 or plus_spread is None else plus_spread)
        for d in rep["days"]:
            d["advice_effect_p"] = d0 + sign * day_spread
    return edit_base, edit_sens


ahead = run_seam(*force(5000.0))
check("an effect far beyond the noise is AHEAD, period and days (and the rule re-derives)", ahead["uncertainty"]["verdict"] == gc.V_AHEAD
      and all(d["verdict"] == gc.V_AHEAD for d in ahead["days"]) and rederive(ahead) == [], str((ahead["uncertainty"]["verdict"], rederive(ahead)[:2])))
behind = run_seam(*force(-5000.0))
check("an effect far below minus the noise is BEHIND, period and days", behind["uncertainty"]["verdict"] == gc.V_BEHIND
      and all(d["verdict"] == gc.V_BEHIND for d in behind["days"]) and rederive(behind) == [])
within = run_seam(*force(0.3, 0.1))
check("a small effect is WITHIN_NOISE (the 0.5 p floor)", within["uncertainty"]["verdict"] == gc.V_WITHIN and within["uncertainty"]["noise_p"] == 0.5
      and all(d["verdict"] == gc.V_WITHIN for d in within["days"]))
edge = run_seam(*force(10.0, 10.0))
check("an effect exactly as large as the noise is WITHIN_NOISE (strictly beyond only)", edge["uncertainty"]["verdict"] == gc.V_WITHIN
      and abs(edge["uncertainty"]["noise_p"] - 10.0) < 0.01, str(edge["uncertainty"]["components_p"]))
just = run_seam(*force(10.05, 10.0))
check("just beyond the noise is AHEAD", just["uncertainty"]["verdict"] == gc.V_AHEAD)
wide = run_seam(*force(60.0, 400.0))
check("an effect that would be beyond a narrow band is WITHIN_NOISE when the efficiency band moves it more (+/-3 points)",
      wide["uncertainty"]["verdict"] == gc.V_WITHIN and wide["uncertainty"]["components_p"]["efficiency_spread"] >= 399.0
      and wide["uncertainty"]["noise_p"] > 60.0, str(wide["uncertainty"]["components_p"]))
asym = run_seam(*force(60.0, 10.0, plus_spread=300.0))
check("the efficiency spread is the LARGER of the two altered efficiencies (here the plus run moves it 300, the minus run 10)",
      abs(asym["uncertainty"]["components_p"]["efficiency_spread"] - 300.0) < 0.01 and asym["uncertainty"]["verdict"] == gc.V_WITHIN,
      str(asym["uncertainty"]["components_p"]))
mixed = run_seam(*force(500.0, 1.0, day=3.0, day_spread=50.0))
check("the period can be beyond its noise while the days are each within theirs (and the other way round)",
      mixed["uncertainty"]["verdict"] == gc.V_AHEAD and all(d["verdict"] == gc.V_WITHIN for d in mixed["days"])
      and mixed["uncertainty"]["days"]["within_noise"] == len(mixed["days"]), str(mixed["uncertainty"]["days"]))


def stock_gap(rep):
    rep["totals"]["advice_effect_p"] = 30.0
    rep["totals"]["stock_adjustment_cost_basis_rule_p"] = 100.0
    rep["totals"]["stock_adjustment_mean_import_rule_p"] = 10.0


gap = run_seam(stock_gap, force(30.0, 1.0)[1])
check("the two closing-stock rules disagreeing by more than the effect makes it WITHIN_NOISE", gap["uncertainty"]["verdict"] == gc.V_WITHIN
      and abs(gap["uncertainty"]["components_p"]["stock_rule_spread"] - 90.0) < 0.01, str(gap["uncertainty"]["components_p"]))


def baseline_err(rep):
    rep["totals"]["advice_effect_p"] = 30.0
    rep["totals"]["model_baseline_delta_p"] = -80.0


bl = run_seam(baseline_err, force(30.0, 1.0)[1])
check("a no-advice replay error larger than the effect makes it WITHIN_NOISE", bl["uncertainty"]["verdict"] == gc.V_WITHIN
      and abs(bl["uncertainty"]["components_p"]["baseline_error"] - 80.0) < 0.01)
check("the noise is the sum of the three components (here 1 + 90 + 0), never below the 0.5 p floor",
      abs(gap["uncertainty"]["noise_p"] - 91.0) < 0.02 and run_seam(*force(0.0, 0.0))["uncertainty"]["noise_p"] == 0.5)

print("== [3b] an unverified export price: no money verdict where the exports differ (G3)")
NA_EXPORT = "NOT_ASSESSED_EXPORT_UNVERIFIED"


def etariff(history: History, price: float = 15.0) -> TariffResult:
    first, last = history.first_last()
    end, slots, t = last + timedelta(hours=1), [], first
    while t < end:
        slots.append(RateSlot(t, t + timedelta(minutes=30), price))
        t += timedelta(minutes=30)
    return TariffResult("export", VERIFIED_FROM_INTEGRATION, tuple(slots))


H_s = house({BAD: 100.0})                                   # the real battery charged to 100 % on the expensive night
T_s = tariff(H_s, expensive_nights=(BAD,), price=100.0)
adv_s = night_advice(H_s, 40.0, only=BAD)                   # the advice would have charged to 40 %: it stores less, so it exports less
det_s: dict = {}
gf.build_ghost_feed(H_s, adv_s, CFG, import_tariff=T_s, max_bytes=1 << 20, detail=det_s)
gap_s = {d["date"]: d["extra_export_kwh_in_ghost"] for d in det_s["rep"]["days"]}
check("non-vacuity: the advice run exports LESS than the existing schedule on the bad night's day (the lost income is unpriced)",
      gap_s[BAD.isoformat()] < -0.1 and all(abs(v) < 1e-9 for k, v in gap_s.items() if k != BAD.isoformat()), str(gap_s))
V_ver = gc.build_ghost_comparison(H_s, adv_s, CFG, import_tariff=T_s, export_tariff=etariff(H_s, 15.0))
U_ver = V_ver["uncertainty"]
check("non-vacuity: with a VERIFIED export price the same world is AHEAD beyond the noise (the verdict rule itself is unchanged)",
      V_ver["tariff"]["export"] == "VERIFIED_FROM_INTEGRATION" and U_ver["verdict"] == gc.V_AHEAD, str((V_ver["tariff"], U_ver["verdict"])))
U_un = gc.build_ghost_comparison(H_s, adv_s, CFG, import_tariff=T_s)
check("export NOT verified and the advice run exporting a different amount: the period verdict is NOT_ASSESSED_EXPORT_UNVERIFIED, "
      "not a claim of AHEAD", U_un["tariff"]["export"] == "NOT_VERIFIED" and U_un["money_available"] is True
      and U_un["uncertainty"]["verdict"] == NA_EXPORT, str(U_un["uncertainty"]["verdict"]))
check("... the constant is in VERDICTS and counted as not assessed", NA_EXPORT in gc.VERDICTS and U_un["uncertainty"]["days"]["not_assessed"] >= 1,
      str(U_un["uncertainty"]["days"]))
days_un = {d["date"]: d["verdict"] for d in U_un["days"]}
check("... exactly the days whose exports differ are not assessed; every other day keeps the rule's own verdict",
      days_un[BAD.isoformat()] == NA_EXPORT and all((v == NA_EXPORT) == (abs(gap_s.get(k, 0.0)) > 1e-3) for k, v in days_un.items()),
      str(days_un))
check("... the money figures themselves are still shown (the verdict is withheld, not the arithmetic)",
      "advice_effect_p" in U_un["uncertainty"] and "noise_p" in U_un["uncertainty"] and "advice_effect_p" in U_un["totals"])
txt_un = gc.render_text(U_un)
check("the verdict text says why: the export is priced 0 and the exports differ (in the report, and in VERDICT_TEXT)",
      NA_EXPORT in txt_un and "export price is not verified" in txt_un and "export price is not verified" in gc.VERDICT_TEXT.get(NA_EXPORT, ""),
      txt_un[:400])
check("the report's per-day column fits and names it", max(len(x) for x in txt_un.splitlines()) <= 118 and "not assessed" in txt_un)
M_un = gc.build_ghost_comparison(H0, night_advice(H0, 80.0), CFG, import_tariff=T0)
check("the rule applies only where the exports differ: matching advice (equal exports) with the export price unverified keeps WITHIN_NOISE",
      M_un["tariff"]["export"] == "NOT_VERIFIED" and M_un["uncertainty"]["verdict"] == gc.V_WITHIN
      and all(d["verdict"] in (gc.V_WITHIN, gc.V_NONE) for d in M_un["days"]), str(M_un["uncertainty"]["verdict"]))
N_un = gc.build_ghost_comparison(H_s, adv_s, CFG, import_tariff=None)
check("no money at all keeps NOT_ASSESSED_NO_MONEY (the older, more basic reason wins)", N_un["uncertainty"]["verdict"] == gc.V_NO_MONEY)
f_un = gf.build_ghost_feed(H_s, adv_s, CFG, import_tariff=T_s)
notes_un = [n for n in f_un["data_quality"]["notes"] if n.startswith("EXPORT_TARIFF_NOT_VERIFIED")]
check("the feed's note no longer claims an unverified export can only understate the gain: it says both runs count export as 0 and "
      "that the figure can be too high or too low where the exports differ",
      len(notes_un) == 1 and "understates a ghost that exports" not in notes_un[0] and "both runs" in notes_un[0]
      and "too high or too low" in notes_un[0], str(notes_un))
check("the feed's module text no longer says it can only understate", "can only understate" not in (gf.__doc__ or ""))

print("== [4] reserve protection")
check("a normal run does not breach: the reserve verdict NO_BREACH, margins non-negative, no day flagged",
      B["reserve"]["verdict"] == gc.RESERVE_OK and B["reserve"]["advice_would_breach"] is False
      and B["reserve"]["advice_below_reserve_slots"] == 0 and not any(d["advice_breach"] for d in B["days"])
      and B["reserve"]["advice_below_reserve_slots_at_efficiency"] == {"minus": 0, "base": 0, "plus": 0}, str(B["reserve"]))


def add_breach(day: str, slots: int, low: float | None = None):
    def edit(rep):
        r = rep["ready_for_assisted_evidence"]
        r["ghost_below_reserve_slots"], r["ghost_below_reserve_days"] = slots, 1
        r["ghost_below_reserve_dates"] = [day]
        if low is not None:
            for d in rep["days"]:
                if d["date"] == day:
                    d["ghost_min_soc_pct"] = low
            rep["totals"]["ghost_min_soc_pct"] = min(rep["totals"]["ghost_min_soc_pct"], low)
    return edit


day_x = B["days"][5]["date"]
br = run_seam(add_breach(day_x, 3, 31.5), None)
rv = br["reserve"]
check("a breach is flagged in the period: would breach, the slots, the days, the dates, the verdict BREACH",
      rv["advice_would_breach"] is True and rv["advice_below_reserve_slots"] == 3 and rv["advice_below_reserve_days"] == 1
      and rv["advice_below_reserve_dates"] == [day_x] and rv["verdict"] == gc.RESERVE_BREACH, str(rv))
check("... on its day, with a negative margin to the reserve, and only that day",
      [d["advice_breach"] for d in br["days"]].count(True) == 1 and next(d for d in br["days"] if d["date"] == day_x)["advice_breach"]
      and next(d for d in br["days"] if d["date"] == day_x)["advice_reserve_margin_pct"] == -8.5 and rv["advice_margin_pct"] == -8.5, str(rv))
only_plus = run_seam(None, None, lambda i, rep: add_breach(day_x, 2)(rep) if i == 2 else None)
check("a breach only when the efficiency is altered is told apart (BREACH_ONLY_AT_ALTERED_EFFICIENCY), not hidden",
      only_plus["reserve"]["verdict"] == gc.RESERVE_SENSITIVE and only_plus["reserve"]["advice_would_breach"] is False
      and only_plus["reserve"]["advice_below_reserve_slots_at_efficiency"] == {"minus": 0, "base": 0, "plus": 2}, str(only_plus["reserve"]))
H_low = house(80.0, floor_pct=20.0)                              # the real battery discharges below the 40 % reserve
Lw = gc.build_ghost_comparison(H_low, night_advice(H_low, 80.0), CFG, import_tariff=tariff(H_low))
check("the existing schedule's own dips below the reserve are reported (negative margin, slots), the advice run is not blamed",
      Lw["reserve"]["existing_margin_pct"] < 0 and Lw["reserve"]["existing_below_reserve_slots"] > 0
      and Lw["reserve"]["advice_would_breach"] is False and any(d["existing_reserve_margin_pct"] < 0 for d in Lw["days"]), str(Lw["reserve"]))
check("a higher reserve recorded with the advice is shown and is the ghost's floor while it is in force",
      gc.build_ghost_comparison(H0, night_advice(H0, 80.0, reserve=55.0), CFG, import_tariff=T0)["reserve"]["advice_recorded_max_pct"] == 55.0)

print("== [5] failures are small blocks with a constant reason")
def small_ok(blk, status, reason) -> bool:
    return (blk["status"] == status and blk["reason"] == reason and blk["money_available"] is False and blk["schema"] == gc.SCHEMA
            and blk["simulated"] and blk["read_only"] and not ({"totals", "days", "reserve", "uncertainty", "advice"} & set(blk))
            and len(json.dumps(blk)) < 2500 and reason in gc.REASONS and status in gc.STATUSES)


E0 = gc.build_ghost_comparison(History([]), rows, CFG, import_tariff=T0)
check("no history at all: INSUFFICIENT_HISTORY / NO_HISTORY", small_ok(E0, "INSUFFICIENT_HISTORY", "NO_HISTORY"), str(E0))
short = History([r for s, r in sorted(H0.by_start.items())[:10]])
E1 = gc.build_ghost_comparison(short, rows, CFG, import_tariff=tariff(short))
check("ten hours of history: INSUFFICIENT_HISTORY / NO_24H_RUN_OF_USABLE_HOURS with the data counts",
      small_ok(E1, "INSUFFICIENT_HISTORY", "NO_24H_RUN_OF_USABLE_HOURS") and E1["data_quality"]["usable_hours"] == 10, str(E1))
nobat = History([HourRecord(start=s) for s in H0.by_start])
for r_, (s_, src_) in zip(nobat.by_start.values(), sorted(H0.by_start.items())):
    r_.e.update({k: v for k, v in src_.e.items() if k not in ("chg", "dis")})
    r_.soc_mean = src_.soc_mean
E2 = gc.build_ghost_comparison(nobat, rows, CFG, import_tariff=T0)
check("a history with no battery charge or discharge counters: it names the hourly fields no hour carries (chg, dis)",
      small_ok(E2, "INSUFFICIENT_HISTORY", "NO_24H_RUN_OF_USABLE_HOURS") and E2["history_fields_absent"] == ["chg", "dis"]
      and E2["data_quality"]["unusable_by_reason"].get("missing_energy", 0) > 0, str(E2))
E3 = gc.build_ghost_comparison(H0, [], CFG, import_tariff=T0)
check("an empty advice log: NO_ADVICE_LOGGED / NO_ADVICE_IN_PERIOD with the period",
      E3["status"] == "NO_ADVICE_LOGGED" and E3["reason"] == "NO_ADVICE_IN_PERIOD" and E3["period"]["hours"] >= 24
      and not ({"totals", "days", "reserve", "uncertainty"} & set(E3)) and E3["money_available"] is True, str(E3))
E3b = gc.build_ghost_comparison(H0, [{"kind": "bogus", "status": "OK", "issued_at": "x"}, {"nope": 1}], CFG, import_tariff=T0)
check("only invalid advice rows: NO_ADVICE_LOGGED, the invalid ones counted", E3b["status"] == "NO_ADVICE_LOGGED"
      and E3b["data_quality"]["advice_rows_invalid"] == 2, str(E3b["data_quality"]))
old_rows = night_advice(H0, 80.0)[:2]
E3c = gc.build_ghost_comparison(H0, old_rows, CFG, import_tariff=T0, now=datetime(2030, 1, 20, tzinfo=UTC) - timedelta(days=0))
check("a clock after the history: still only a status and a reason when nothing is in the period", E3c["status"] in ("OK", "NO_ADVICE_LOGGED", "INSUFFICIENT_HISTORY"))
E4 = gc.build_ghost_comparison(None, rows, CFG, import_tariff=T0)
check("a wrong argument type (no History): ERROR / FEED_EXCEPTION with the class name, never an exception",
      small_ok(E4, "ERROR", "FEED_EXCEPTION") and E4["error_type"] == "TypeError", str(E4))


class Evil:
    @property
    def verified(self):
        raise RuntimeError("secret sensor.entity_secret 51.5 -0.1")


E5 = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=Evil())
check("an exception raised by a collaborator: ERROR with its class only, its message nowhere",
      E5["status"] == "OK" or (E5["status"] == "ERROR" and "secret" not in json.dumps(E5) and E5["error_type"] == "RuntimeError"), str(E5))
E5b = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, days=0)
check("a bad argument value (days=0): ERROR / ValueError", small_ok(E5b, "ERROR", "FEED_EXCEPTION") and E5b["error_type"] == "ValueError")
real_feed = gf.build_ghost_feed
gf.build_ghost_feed = None
try:
    E6 = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0)
finally:
    gf.build_ghost_feed = real_feed
check("an exception inside the feed: ERROR, the block stays small", small_ok(E6, "ERROR", "FEED_EXCEPTION"), str(E6))


def nonfinite(rep):
    rep["totals"]["advice_effect_p"] = float("nan")


E7 = run_seam(nonfinite, None)
check("a non-finite figure never reaches the block: ERROR, not a NaN in JSON", small_ok(E7, "ERROR", "FEED_EXCEPTION")
      or (E7["status"] == "OK" and math.isfinite(E7["uncertainty"]["noise_p"])), str(E7)[:200])
hostile = type("X", (Exception,), {})("x" * 5000)
check("the exception class name is kept only when it is a plain identifier (an odd class gets UNKNOWN)",
      gc.error_block(type("a b", (Exception,), {})("m"))["error_type"] == "UNKNOWN" and gc.error_block(hostile)["error_type"] == "X")

print("== [5b] the size bound")
mx = len(json.dumps(B, sort_keys=True, separators=(",", ":")).encode())
check(f"the normal block is bounded ({mx} bytes <= {gc.MAX_BYTES})", mx <= gc.MAX_BYTES and gc.MAX_BYTES == 12288)
cut = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, max_bytes=5000)
check("a smaller bound drops the OLDEST days, counts them, and the block fits",
      len(json.dumps(cut, sort_keys=True, separators=(",", ":")).encode()) <= 5000 and cut["days_dropped"] > 0
      and len(cut["days"]) + cut["days_dropped"] == len(B["days"]) and cut["days"][-1]["date"] == B["days"][-1]["date"]
      and cut["days"][0]["date"] > B["days"][0]["date"] and cut["uncertainty"] == B["uncertainty"] and cut["totals"] == B["totals"],
      str((cut["days_dropped"], len(cut["days"]))))
tiny = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, max_bytes=700)
check("a bound too small even for one day: ERROR / SIZE_BOUND, not a clipped figure", small_ok(tiny, "ERROR", "SIZE_BOUND"), str(tiny)[:200])
check("the bound is on the serialized block, texts included (a bound above the block drops nothing)",
      gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, max_bytes=mx)["days_dropped"] == 0
      and gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, max_bytes=mx - 1)["days_dropped"] == 1)

print("== [6] nothing leaks; JSON-safe; deterministic; inputs unchanged")
hostile_rows = copy.deepcopy(rows) + [dict(rows[0], advice_id="sensor.test_secret_entity_9", issued_at=rows[0]["issued_at"]),
                                      dict(rows[1], note="free text from a sensor"), {"kind": "charge_target", "status": "OK",
                                      "issued_at": "2030-01-10T00:00:00+00:00", "advice_id": "binary_sensor.leak", "extra": "x"}]
before = copy.deepcopy(hostile_rows)
L1 = gc.build_ghost_comparison(H0, hostile_rows, CFG, import_tariff=T0)
text = json.dumps(L1)
check("hostile advice ids, extra fields and free text never appear (the extra-field rows are counted invalid)",
      "test_secret_entity" not in text and "binary_sensor.leak" not in text and "free text" not in text
      and L1["data_quality"]["advice_rows_invalid"] == 2 and "t:2030" not in text, str(L1["data_quality"]["advice_rows_invalid"]))
check("the inputs are not changed", hostile_rows == before)
strings = [x for _p, x in leaves(L1) if isinstance(x, str)]
ok_re = re.compile(r"^[A-Za-z0-9 _:.,;()/+%'=<>&\-]+$")
check("every string is a fixed character set (constant words, dates, ISO times): nothing free-form",
      all(ok_re.match(x) for x in strings), str([x for x in strings if not ok_re.match(x)][:3]))
check("no entity id, no domain.object_name, no time zone name, no coordinates",
      not re.search(r"\b(sensor|binary_sensor|input_number|event|number|switch)\.[a-z0-9_]+", text) and "UTC" not in text.replace("SIMULATION", "")
      and "timezone" not in text and "latitude" not in text and "tz" not in {k for k in L1})
check("strict JSON (no NaN, no infinity), and the block is deterministic",
      json.dumps(L1, allow_nan=False) == json.dumps(gc.build_ghost_comparison(H0, copy.deepcopy(hostile_rows), CFG, import_tariff=T0), allow_nan=False))
check("every block of every scenario above is plain JSON", all(json.dumps(x, allow_nan=False) for x in (B, N, S, P, nf, lose, br, E0, E1, E2, E3, E4)))

print("== [7] the feed and the simulation are unchanged by the new, optional hooks")
f_plain = gf.build_ghost_feed(H0, rows, CFG, import_tariff=T0)
det: dict = {}
f_det = gf.build_ghost_feed(H0, rows, CFG, import_tariff=T0, detail=det)
check("build_ghost_feed with and without `detail` returns the same summary; the detail holds the run's internals",
      f_plain == f_det and {"rep", "sens", "money", "starts", "advice", "reason", "soc_start_pct"} <= set(det) and set(det["sens"]) == {"minus", "plus"})
check("the feed's own size bound and schema are what they were", gf.MAX_BYTES == 8192 and f_plain["schema"] == "ecco-intel-ghost-feed/1"
      and len(json.dumps(f_plain, sort_keys=True, separators=(",", ":")).encode()) <= 8192)
check("no detail on a failure (insufficient history): the dict stays empty", (lambda d: (gf.build_ghost_feed(History([]), [], CFG, detail=d), d)[1])({}) == {})
rep0 = det["rep"]
check("ghost.py's per-day end SOC is the SOC at the end of the day's last slot of each run",
      all("actual_end_soc_pct" in d and "ghost_end_soc_pct" in d and 0.0 <= d["actual_end_soc_pct"] <= 100.0 for d in rep0["days"])
      and abs(rep0["days"][0]["actual_end_soc_pct"] - end_soc(rep0["days"][0]["date"])) <= 0.06)

print("== [8] the plain-text report on a golden download")
GOLD_JSON, GOLD_TXT = FIXTURES / "golden_download.json", FIXTURES / "golden_report.txt"
TOOL = ROOT / "intelligence" / "tools" / "ghost_diag_report.py"
check("the golden download and the golden report exist", GOLD_JSON.is_file() and GOLD_TXT.is_file() and TOOL.is_file(), str(FIXTURES))
if GOLD_JSON.is_file() and TOOL.is_file():
    gold = json.loads(GOLD_JSON.read_text(encoding="utf-8"))
    block = gold["data"]["ghost"]
    check("the golden block is a block of this schema, with money, a within-noise verdict and a reserve verdict",
          block["schema"] == gc.SCHEMA and block["status"] == "OK" and block["money_available"] is True
          and block["uncertainty"]["verdict"] in gc.VERDICTS and block["reserve"]["verdict"] in gc.RESERVE_VERDICTS and len(block["days"]) == 3)
    want_txt = GOLD_TXT.read_text(encoding="utf-8")
    got_txt = gc.render_text(block)
    check("render_text on the golden block equals the golden report exactly (every line)", got_txt.rstrip("\n") == want_txt.rstrip("\n"),
          next((f"line {i + 1}: {a!r} != {b!r}" for i, (a, b) in enumerate(zip(got_txt.splitlines(), want_txt.splitlines())) if a != b), "length"))
    check("the report states the simulation, both sides, the money or NO MONEY, SOC, the reserve, the noise and the limits",
          all(w in got_txt for w in ("SIMULATION", "EXISTING SCHEDULE", "INTELLIGENCE ADVICE", "VERDICT", "SOC %", "RESERVE", "noise", "Limits:",
                                     "Read-only simulation")) and max(len(x) for x in got_txt.splitlines()) <= 118 and len(got_txt.splitlines()) <= 42)
    shape = structure(block)
    fresh = gc.build_ghost_comparison(H0, rows, CFG, import_tariff=T0, days=3)
    check("the golden block has the structure the builder produces today (so the golden report is not of a stale shape)",
          structure(fresh) == shape, str(set(json.dumps(structure(fresh))) ^ set(json.dumps(shape)))[:100])
    run = lambda args: subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(TOOL), *args], capture_output=True, text=True,  # noqa: E731
                                      encoding="utf-8", timeout=120)
    r1 = run([str(GOLD_JSON)])
    check("the tool prints the golden report from a whole HA download (data.ghost), exit 0", r1.returncode == 0
          and r1.stdout.rstrip("\n") == want_txt.rstrip("\n") and r1.stderr == "", (r1.stderr or r1.stdout)[-300:])
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ecco_ghost_diag_") as td:
        p_ghost, p_block, p_bad, p_nogh = (Path(td) / n for n in ("ghost.json", "block.json", "bad.json", "nogh.json"))
        p_ghost.write_text(json.dumps({"ghost": block}), encoding="utf-8")
        p_block.write_text(json.dumps(block), encoding="utf-8")
        p_bad.write_text("{not json", encoding="utf-8")
        p_nogh.write_text(json.dumps({"data": {"loaded": True}}), encoding="utf-8")
        r2, r3, r4, r5 = run([str(p_ghost)]), run([str(p_block)]), run([str(p_bad)]), run([str(p_nogh)])
        r6 = run([str(Path(td) / "missing.json")])
        small = Path(td) / "small.json"
        small.write_text(json.dumps({"data": {"ghost": gc.small_block(gc.INSUFFICIENT_HISTORY, gc.R_NO_24H_RUN, history_fields_absent=["chg", "dis"])}}), encoding="utf-8")
        r7 = run([str(small)])
        r8 = run([str(GOLD_JSON), "--json"])
    check("the tool reads the `ghost` key and the bare block the same way", r2.stdout == r1.stdout == r3.stdout and r2.returncode == r3.returncode == 0)
    check("bad JSON, a missing file and a download with no ghost block: exit 2, a one-line message on stderr, nothing on stdout",
          all(r.returncode == 2 and r.stdout == "" and r.stderr.count("\n") <= 2 and "ghost_diag_report" in r.stderr for r in (r4, r5, r6)),
          str((r4.stderr, r5.stderr, r6.stderr)))
    check("a small block prints its status, reason and the absent fields, and says nothing is guessed",
          r7.returncode == 0 and "INSUFFICIENT_HISTORY" in r7.stdout and "NO_24H_RUN_OF_USABLE_HOURS" in r7.stdout and "chg, dis" in r7.stdout
          and "nothing is guessed" in r7.stdout, r7.stdout[-300:])
    check("--json prints the block itself", r8.returncode == 0 and json.loads(r8.stdout) == block)
    nf_txt = gc.render_text(nf)
    check("the report says why advice was not followed, in words, and per day (followed / not followed)",
          "BLOCKED x" in nf_txt and "BLOCKED: the advice was BLOCKED" in nf_txt and "adv f/n" in nf_txt and "VERDICT: NO_ADVICE_EFFECT" in nf_txt
          and re.search("  0/1", nf_txt) is not None, nf_txt[:600])
    nomoney_txt = gc.render_text(N)
    check("the report of a no-money block says NO MONEY and shows no pence figure or column",
          "NO MONEY" in nomoney_txt and "Money (pence" not in nomoney_txt and "ADVICE EFFECT" not in nomoney_txt
          and "existing p" not in nomoney_txt and "VERDICT: NOT_ASSESSED_NO_MONEY" in nomoney_txt)
    within_txt = gc.render_text(within)           # the forced WITHIN_NOISE block of [3] (B itself now has an unpriced export difference: [3b])
    check("the report of a within-noise block says it is not a win", "not a win" in within_txt and "WITHIN_NOISE" in within_txt)
    check("the report refuses a foreign object", all(raises(lambda x=x: gc.render_text(x), ValueError) for x in ({}, {"schema": "x"}, [], None)))

print("== [9] no write path")
SRC = (ROOT / "intelligence" / "ghost_compare.py", ROOT / "intelligence" / "tools" / "ghost_diag_report.py")
bad_imp, bad_call = [], []
for p in SRC:
    if not p.is_file():
        continue
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad_imp += [f"{p.name}: {a.name}" for a in n.names if a.name.split(".")[0] in ("os", "socket", "subprocess", "sqlite3", "shutil", "tempfile", "urllib", "http", "asyncio", "threading")]
        elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in ("os", "socket", "subprocess", "sqlite3", "shutil", "tempfile", "urllib", "http", "asyncio", "threading"):
            bad_imp.append(f"{p.name}: {n.module}")
        elif isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if nm in ("write_text", "write_bytes", "unlink", "mkdir", "rename", "system", "popen", "exec", "eval", "compile", "__import__", "setattr"):
                bad_call.append(f"{p.name}: {nm}")
            if nm == "open" and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and set(a.value) & set("wax+") for a in n.args):
                bad_call.append(f"{p.name}: open for writing")
check("the comparison module and the report tool import no os / network / process / database module", not bad_imp, str(bad_imp))
check("they call no write, delete, exec or dynamic-import function", not bad_call, str(bad_call))
src_text = "".join(p.read_text(encoding="utf-8") for p in SRC if p.is_file()).lower()
check("they carry no control vocabulary", not any(w in src_text for w in ("write_register", "modbus", "call_service", "mqtt.publish", "api/services", "esphome.")))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the Ghost comparison suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all Ghost comparison checks passed")
