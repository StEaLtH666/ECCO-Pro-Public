#!/usr/bin/env python3
"""Regression tests for the final safety guards of the shadow engine (all synthetic, seeded, offline):

  [1] PV forecast plausibility: an impossible forecast is rejected, not turned into confident advice
  [2] non-finite / negative inputs (PV forecast, reserve, SOC age, readings) never reach the arithmetic
  [3] absence / return-day protection: the pessimistic path leans on a longer baseline, the median does not move
  [4] behaviour-shift and abnormal-load triggers of the same guard
  [5] the effective minimum SOC (user reserve vs technical minimum) cannot be lowered by any input path
  [6] the formerly hard-coded advisor constants are configuration and are validated
  [7] low-history cold start fails closed
  [8] the synthetic fixtures are deterministic, in-process and across interpreter hash seeds
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

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

from intelligence import engine as eng_mod
from intelligence.advisor import LiveInputs, soc_is_stale
from intelligence.config import DEFAULT_TECHNICAL_MIN_SOC_PCT, DEFAULT_USER_RESERVE_SOC_PCT, SiteConfig
from intelligence.replay import replay
from intelligence.synthetic import make_history, solcast_like
from intelligence.timeutil import HOUR, local_wall, ts, zone, day_bounds

ROOT = Path(__file__).resolve().parents[2]
cfg = SiteConfig()
tz = zone(cfg.tz)
START = date(2026, 7, 1)
NOW_DAY = date(2026, 9, 9)
TOM = NOW_DAY + timedelta(days=1)
NOW = local_wall(NOW_DAY, 21 * 60 + 30, tz)


def quiet_hours(first: date, last: date, kwh: float) -> dict[int, float]:
    """load_overrides making every hour of [first, last] equal to `kwh` (an empty house)."""
    out = {}
    d = first
    while d <= last:
        t0, t1 = day_bounds(d, tz)
        s = ts(t0)
        while s < ts(t1):
            out[s] = kwh
            s += HOUR
        d += timedelta(days=1)
    return out


normal = make_history(START, 75, cfg, seed=3)
fc_normal = {"solcast": solcast_like(normal, cfg, over_factor=1.0, noise=0.08)}


def run(h=normal, fc=None, c=cfg, now=NOW, soc=62.0, **ov):
    return replay(h, c, now, fc_normal if fc is None else fc, soc_override=soc, **ov)


def tgt(r) -> float:
    return r["recommended"]["overnight_target"]["recommended_target_soc_pct"]


def codes(r) -> list[str]:
    return [x["code"] for x in r["recommended"].get("reasons", [])]


# ---------------------------------------------------------------------------------------------------------------
section("[1] PV forecast plausibility")
realistic = fc_normal["solcast"][TOM]
good = run()
check("a realistic forecast is accepted at HIGH confidence on this history",
      good["confidence"]["label"] == "HIGH" and good["pv"][TOM.isoformat()]["plausibility"]["verdict"] == "OK", str(good["confidence"]))
check("the verdict carries the ceilings it used (physical, all-time, recent)",
      set(good["pv"][TOM.isoformat()]["plausibility"]["limits_kwh"]) == {"site_physical", "history_max", "recent_max"})
check("the physical ceiling is the configured array size x the per-kWp ceiling, not a constant in pv.py",
      good["pv"][TOM.isoformat()]["plausibility"]["limits_kwh"]["site_physical"] == round(cfg.pv_array_kwp * cfg.pv_max_kwh_per_kwp_day, 2))

absurd = run(pv_raw_tomorrow={"solcast": 10.0 * realistic})
pv_t = absurd["pv"][TOM.isoformat()]
check("a 10x forecast is REJECTED", pv_t["plausibility"]["verdict"] == "REJECTED" and pv_t["plausibility"]["rejected"], str(pv_t["plausibility"]))
check("the rejection names the source, the raw value and the limit that was broken",
      pv_t["plausibility"]["rejected"][0]["source"] == "solcast" and pv_t["plausibility"]["rejected"][0]["raw_kwh"] > 200
      and pv_t["plausibility"]["rejected"][0]["limit_kwh"] > 0 and pv_t["plausibility"]["rejected"][0]["reason"])
check("the rejected value is not what the day was forecast from (persistence, not 10x)",
      pv_t["source"] == "persistence" and pv_t["p50"] < 2.0 * realistic, f"{pv_t['source']} {pv_t['p50']}")
check("overall confidence is never above LOW after a rejection",
      absurd["confidence"]["label"] in ("LOW", "INSUFFICIENT") and "PV_FORECAST_REJECTED" in absurd["confidence"]["downgrade_reasons"],
      str(absurd["confidence"]))
check("the recommendation carries the reason code and a HIGH uncertainty entry",
      "PV_FORECAST_REJECTED" in codes(absurd)
      and any(u["code"] == "PV_FORECAST_REJECTED" and u["severity"] == "HIGH" for u in absurd["recommended"]["uncertainty"]))
none = run(pv_raw_tomorrow={})
check("an absurd forecast is never LESS cautious than no forecast at all (target >= the no-forecast target)",
      tgt(absurd) >= tgt(none), f"{tgt(absurd)} vs {tgt(none)}")
check("an absurd forecast is not more cautious-FREE than a sane one either: its target is not below the sane target",
      tgt(absurd) >= tgt(good), f"{tgt(absurd)} vs {tgt(good)}")

# the all-time maximum alone is not enough: build 60 bright days then 40 dim ones; 3.5x the recent best is below the
# all-time ceiling (and the array size is unknown) but must still be rejected by the recent ceiling
bright_then_dim = make_history(date(2026, 6, 1), 100, cfg, seed=4, clearness=0.9,
                               pv_scale_by_day={date(2026, 6, 1) + timedelta(days=k): 0.3 for k in range(60, 100)})
cfg_nokwp = replace(cfg, pv_array_kwp=None)
dim_now = local_wall(date(2026, 9, 7), 21 * 60 + 30, tz)
dim_tom = date(2026, 9, 8)
fc_dim = {"solcast": solcast_like(bright_then_dim, cfg_nokwp, over_factor=1.0, noise=0.05)}
r_dim_ok = replay(bright_then_dim, cfg_nokwp, dim_now, fc_dim, soc_override=62.0)
lim = r_dim_ok["pv"][dim_tom.isoformat()]["plausibility"]["limits_kwh"]
check("without a configured array size the physical ceiling is simply absent (observed ceilings only)", "site_physical" not in lim and {"history_max", "recent_max"} <= set(lim), str(lim))
dim_real = fc_dim["solcast"][dim_tom]
over = 3.5 * lim["recent_max"] / cfg_nokwp.pv_recent_headroom
check("test setup: the bad value is below the all-time ceiling but above the recent one", over < lim["history_max"] and over > lim["recent_max"], f"{over} {lim}")
r_dim_bad = replay(bright_then_dim, cfg_nokwp, dim_now, fc_dim, soc_override=62.0, pv_raw_tomorrow={"solcast": over})
check("the recent-output ceiling catches what the all-time maximum lets through",
      r_dim_bad["pv"][dim_tom.isoformat()]["plausibility"]["verdict"] == "REJECTED"
      and r_dim_bad["pv"][dim_tom.isoformat()]["plausibility"]["rejected"][0]["limit"] == "recent_max",
      str(r_dim_bad["pv"][dim_tom.isoformat()]["plausibility"]))
check("... and the same dim-period run with a sane forecast is accepted (no false rejection)", r_dim_ok["pv"][dim_tom.isoformat()]["plausibility"]["verdict"] == "OK")

# physical ceiling alone, with no history to compare to at all: 8 days of data => no ratio => forecast unused, but a
# raw value above the array's physical limit is still reported
tiny = make_history(START, 8, cfg, seed=5)
r_tiny = replay(tiny, cfg, local_wall(START + timedelta(days=7), 21 * 60 + 30, tz), None, soc_override=62.0,
                pv_raw_tomorrow={"solcast": 500.0})
tiny_day = (START + timedelta(days=8)).isoformat()
check("history too short to learn a ratio: the raw forecast is not used, and the physical breach is still recorded",
      r_tiny["pv"][tiny_day]["source"] != "solcast" and r_tiny["pv"][tiny_day]["plausibility"]["verdict"] == "REJECTED"
      and r_tiny["pv"][tiny_day]["plausibility"]["rejected"][0]["limit"] == "site_physical", str(r_tiny["pv"][tiny_day]["plausibility"]))

# ---------------------------------------------------------------------------------------------------------------
section("[2] non-finite and negative inputs")
for label, val in (("NaN", float("nan")), ("+inf", float("inf")), ("-inf", float("-inf")), ("negative", -7.0), ("string", "30"), ("bool", True)):
    r = run(pv_raw_tomorrow={"solcast": val})
    t = r["pv"][TOM.isoformat()]
    check(f"PV forecast {label}: ignored, persistence used, never HIGH",
          t["source"] == "persistence" and r["confidence"]["label"] != "HIGH" and any("ignored" in n for n in t["notes"]),
          f"{t['source']} {r['confidence']['label']} {t['notes']}")
    check(f"PV forecast {label}: no NaN/inf anywhere in the report",
          json.dumps(r, allow_nan=False, default=str) is not None)
    check(f"PV forecast {label}: advice is no less cautious than with no forecast", tgt(r) >= tgt(none) - 1e-9, f"{tgt(r)} vs {tgt(none)}")
r_so_far = run(pv_actual_so_far_kwh=float("nan"), pv_raw_today=fc_normal["solcast"] and {"solcast": fc_normal["solcast"][NOW_DAY]})
check("a NaN 'PV so far today' is dropped, not turned into a 1.6x re-anchor",
      r_so_far["actual"]["pv_so_far_kwh"] is None and r_so_far["pv"].get("today_reanchor") is None, str(r_so_far["pv"].get("today_reanchor")))
r_neg = run(pv_actual_so_far_kwh=-3.0, load_w=float("nan"), pv_w=float("inf"))
check("negative / NaN / inf live readings are dropped with a note",
      r_neg["actual"]["pv_so_far_kwh"] is None and r_neg["actual"]["load_w"] is None and r_neg["actual"]["pv_w"] is None
      and len([n for n in r_neg["notes"] if "not a valid number" in n]) == 3, str(r_neg["notes"]))
for label, age in (("NaN", float("nan")), ("negative", -30.0), ("inf", float("inf")), ("string", "5"), ("bool", True)):
    check(f"SOC age {label} is stale", soc_is_stale(age) is True)
    r = run(soc_age_s=age)
    check(f"SOC age {label}: export withheld, status DATA_STALE, report is valid JSON",
          r["recommended"]["safe_export"]["kwh"] == 0.0 and r["recommended"]["safe_export"].get("withheld_because")
          and any(u["code"] == "STALE_SOC" for u in r["recommended"]["uncertainty"])
          and r["status"] == "DATA_STALE" and json.dumps(r, allow_nan=False, default=str) is not None, f"{r['status']}")
check("a fresh SOC age is not stale and 0 is fresh", soc_is_stale(0.0) is False and soc_is_stale(899.0) is False and soc_is_stale(901.0) is True)
for label, res in (("NaN", float("nan")), ("+inf", float("inf")), ("-inf", float("-inf")), ("negative", -10.0), ("string", "high"), ("None", None)):
    r = run(ha_reserve_pct=res)
    check(f"HA reserve {label}: effective minimum stays at the user reserve (40 default)", r["recommended"]["floor_pct"] == 40.0, str(r["recommended"]["floor_pct"]))
r_bad_soc = run(soc=float("nan"))
check("a NaN SOC gives no recommendation at all", r_bad_soc["recommended"]["status"] == "NO_SOC")
check("an out-of-range SOC is ignored", run(soc=140.0)["recommended"]["status"] == "NO_SOC")

# ---------------------------------------------------------------------------------------------------------------
section("[3] absence / return-day protection")
away = quiet_hours(NOW_DAY - timedelta(days=6), NOW_DAY, 0.25)            # a week of an empty house, up to tonight
h_away = make_history(START, 75, cfg, seed=3, load_overrides=away)
fc_away = {"solcast": solcast_like(h_away, cfg, over_factor=1.0, noise=0.08)}
guarded = run(h_away, fc_away, soc=70.0)
orig_guard = eng_mod.baseline_guard
eng_mod.baseline_guard = lambda m, a, t: ({"active": False, "triggers": [], "uplift_day_kwh": 0.0}, None)
try:
    unguarded = run(h_away, fc_away, soc=70.0)
finally:
    eng_mod.baseline_guard = orig_guard
g = guarded["load_baseline_guard"]
check("the guard is ACTIVE after a quiet week and says why", g["active"] and "FAST_BELOW_BASELINE" in g["triggers"], str(g))
check("the guard reports both profiles and a material uplift", g["fast_day_kwh"] < 0.8 * g["baseline_day_kwh"] and g["uplift_day_kwh"] > 5.0, str(g))
check("the long baseline is a robust one: the quiet week did not drag it to the quiet level", g["baseline_day_kwh"] > 2.0 * g["fast_day_kwh"], str(g))
check("the guarded pessimistic target is higher than the unguarded one",
      guarded["recommended"]["overnight_target"]["pessimistic_case_target_soc_pct"] > unguarded["recommended"]["overnight_target"]["pessimistic_case_target_soc_pct"]
      and tgt(guarded) > tgt(unguarded), f"{tgt(guarded)} vs {tgt(unguarded)}")
check("the guarded safe export is smaller",
      guarded["recommended"]["safe_export"]["kwh"] < unguarded["recommended"]["safe_export"]["kwh"],
      f"{guarded['recommended']['safe_export']['kwh']} vs {unguarded['recommended']['safe_export']['kwh']}")
check("the MEDIAN forecasts and the median-case target are NOT pushed up (the guard is for the safety path only)",
      all(abs(guarded["predicted"][k]["p50"] - unguarded["predicted"][k]["p50"]) < 1e-9
          for k in ("day", "to_next_cheap", "cheap_window", "morning", "overnight"))
      and guarded["recommended"]["overnight_target"]["median_case_target_soc_pct"] == unguarded["recommended"]["overnight_target"]["median_case_target_soc_pct"])
# Planner level: the baseline reaches pessimistic / hard only, never the median or optimistic path
from intelligence.advisor import Planner
_inp = LiveInputs(now=NOW, soc_pct=70.0, soc_age_s=0.0, inverter_ok=True)
_pl = Planner(cfg, [0.5] * 24, (-0.2, 0.2), {}, _inp, [0.0] * 4, "HIGH", 1.0, [1.5] * 24)
_h = NOW + timedelta(hours=3)
check("Planner: median and optimistic loads use the fast profile; pessimistic and hard use the higher baseline",
      abs(_pl._load_fn("p50")(_h) - 0.5) < 1e-9 and _pl._load_fn("opt")(_h) < 0.5 and _pl._load_fn("pess")(_h) > 1.5 and _pl._load_fn("hard")(_h) > 1.5,
      str([_pl._load_fn(k)(_h) for k in ("p50", "opt", "pess", "hard")]))
_pl2 = Planner(cfg, [2.0] * 24, (-0.2, 0.2), {}, _inp, [0.0] * 4, "HIGH", 1.0, [1.0] * 24)
check("Planner: a baseline BELOW the fast profile never lowers anything", _pl2._load_fn("pess")(_h) >= 2.0)
check("the advice carries the reason code and a WATCH uncertainty",
      "LOAD_BASELINE_GUARD" in codes(guarded) and any(u["code"] == "LOAD_BASELINE_GUARD" for u in guarded["recommended"]["uncertainty"]))
check("confidence is signalled, not hidden: it is not HIGH while the guard is active",
      guarded["confidence"]["label"] != "HIGH" and "LOAD_BASELINE_GUARD" in guarded["confidence"]["downgrade_reasons"], str(guarded["confidence"]))
check("an ordinary house: guard inactive, nothing changed", run()["load_baseline_guard"]["active"] is False and "LOAD_BASELINE_GUARD" not in codes(run()))

# the first normal day back: one normal day after the quiet week; the fast profile has only partly recovered
away_week = quiet_hours(NOW_DAY - timedelta(days=7), NOW_DAY - timedelta(days=1), 0.25)
h_back = make_history(START, 75, cfg, seed=3, load_overrides=away_week)
fc_back = {"solcast": solcast_like(h_back, cfg, over_factor=1.0, noise=0.08)}
back = run(h_back, fc_back, soc=70.0)
check("the evening of the first normal day back is still protected by the longer baseline (fast profile not yet recovered)",
      back["load_baseline_guard"]["active"] and back["load_baseline_guard"]["uplift_day_kwh"] > 5.0
      and back["load_baseline_guard"]["baseline_day_kwh"] > 1.5 * back["load_baseline_guard"]["fast_day_kwh"], str(back["load_baseline_guard"]))
check("... and it still signals MEDIUM rather than HIGH", back["confidence"]["label"] != "HIGH", str(back["confidence"]))

# ---------------------------------------------------------------------------------------------------------------
section("[4] behaviour-shift and abnormal-load triggers")
shift_ov = {}
for s in range(0, 14):
    d = NOW_DAY - timedelta(days=s)
    shift_ov.update({k: normal.get(k).e["load"] * 0.55 for k in range(ts(day_bounds(d, tz)[0]), ts(day_bounds(d, tz)[1]), HOUR) if normal.get(k) is not None})
h_shift = make_history(START, 75, cfg, seed=3, load_overrides=shift_ov)
r_shift = run(h_shift, {"solcast": solcast_like(h_shift, cfg, over_factor=1.0, noise=0.08)}, soc=70.0)
check("a downward behaviour shift raises BEHAVIOUR_SHIFT and activates the guard",
      any(a["code"] == "BEHAVIOUR_SHIFT" for a in r_shift["anomalies"]["anomalies"]) and "BEHAVIOUR_SHIFT" in r_shift["load_baseline_guard"]["triggers"], str(r_shift["load_baseline_guard"]))
check("... and the safety path is therefore at least as cautious as without it", r_shift["load_baseline_guard"]["uplift_day_kwh"] > 0)
# sustained abnormal load: +2.5 kW for the last five hours before now
hrs = {ts(NOW) - (ts(NOW) % HOUR) - k * HOUR: 3.6 for k in range(1, 6)}
h_abn = make_history(START, 75, cfg, seed=3, load_overrides=hrs)
r_abn = run(h_abn, {"solcast": solcast_like(h_abn, cfg, over_factor=1.0, noise=0.08)}, soc=70.0)
check("a sustained abnormal load activates the guard with the ABNORMAL trigger",
      r_abn["anomalies"]["abnormal_load_now"] and "ABNORMAL" in r_abn["load_baseline_guard"]["triggers"], str(r_abn["load_baseline_guard"]))
eng_mod.baseline_guard = lambda m, a, t: ({"active": False, "triggers": [], "uplift_day_kwh": 0.0}, None)
try:
    r_abn_off = run(h_abn, {"solcast": solcast_like(h_abn, cfg, over_factor=1.0, noise=0.08)}, soc=70.0)
finally:
    eng_mod.baseline_guard = orig_guard
check("... where it can only RAISE caution: pessimistic target and export are never below / above the unguarded run",
      tgt(r_abn) >= tgt(r_abn_off) and r_abn["recommended"]["safe_export"]["kwh"] <= r_abn_off["recommended"]["safe_export"]["kwh"] + 1e-9,
      f"{tgt(r_abn)} vs {tgt(r_abn_off)}")

# ---------------------------------------------------------------------------------------------------------------
section("[5] the effective minimum SOC cannot be lowered below the user reserve or the technical minimum")
check("the defaults are 40 % user reserve (a preference) and a separate technical minimum that is not 40",
      DEFAULT_USER_RESERVE_SOC_PCT == 40.0 and DEFAULT_TECHNICAL_MIN_SOC_PCT < DEFAULT_USER_RESERVE_SOC_PCT)
for hm in (0.0, 10.0, -50.0, float("nan"), float("-inf")):
    try:
        c = SiteConfig(technical_min_soc_pct=hm)
        ok = c.effective_min_soc_pct(None) == 40.0 and c.effective_min_soc_pct(5.0) == 40.0 and c.effective_min_soc_pct(float("nan")) == 40.0
    except ValueError:
        ok = True      # refusing the config is also safe
    check(f"technical_min_soc_pct={hm!r} cannot pull the effective minimum below the 40 % user reserve", ok)
check("the minimum can still be RAISED by config and by a HA reserve; both capped at 100",
      SiteConfig(user_reserve_soc_pct=55.0).effective_min_soc_pct(None) == 55.0 and cfg.effective_min_soc_pct(70.0) == 70.0
      and cfg.effective_min_soc_pct(250.0) == 100.0 and SiteConfig(user_reserve_soc_pct=55.0).effective_min_soc_pct(60.0) == 60.0)
for kw in ({"max_soc_pct": 30.0}, {"max_soc_pct": 40.0}, {"max_soc_pct": 44.0}, {"max_soc_pct": float("nan")}, {"max_soc_pct": 120.0},
           {"soc_safety_margin_pct": -10.0}, {"soc_safety_margin_pct": float("nan")}):
    try:
        SiteConfig(**kw)
        ok = False
    except ValueError:
        ok = True
    check(f"a config that could put a recommendation at or below the floor is refused: {kw}", ok)
low_cfg = SiteConfig(technical_min_soc_pct=10.0)
sweep = [run(c=low_cfg, soc=s, ha_reserve_pct=res) for s in (45.0, 62.0, 90.0) for res in (None, 0.0, 15.0, float("nan"))]
check("with a technical minimum of 10 and an HA reserve of 0/15/NaN every report still uses the 40 % user reserve",
      all(r["recommended"]["floor_pct"] == 40.0 for r in sweep))
check("every recommended target, in every sweep run, is at least the 40 % reserve plus the margin",
      all(tgt(r) >= 45.0 for r in sweep), str(sorted({tgt(r) for r in sweep})))
check("every export advice is zero or leaves the pessimistic path above floor + margin (re-checked by the advisor's own bound)",
      all(r["recommended"]["safe_export"]["kwh"] <= max(0.0, (r["actual"]["soc_pct"] - 45.0) / 100.0 * low_cfg.battery_capacity_kwh) for r in sweep))

# ---------------------------------------------------------------------------------------------------------------
section("[6] advisor constants are configuration, and validated")
c10 = replace(cfg, target_step_pct=10.0)
check("target step is configurable (10 % steps)", tgt(run(c=c10)) % 10 == 0 and tgt(run(c=c10)) >= tgt(good))
check("the default step is unchanged (5 %)", tgt(good) % 5 == 0)
slow_chg = run(c=replace(cfg, max_grid_charge_kw=2.0), soc=45.0)
fast_chg = run(c=cfg, soc=45.0)
check("the grid-charge cap is configurable and 2 kW can reach less in the window than 8 kW",
      slow_chg["recommended"]["overnight_target"]["grid_charge_kwh_median"] <= fast_chg["recommended"]["overnight_target"]["grid_charge_kwh_median"] + 1e-9
      and "2 kW" in " ".join(slow_chg["recommended"]["assumptions"]))
wide = run(c=replace(cfg, band_kappa=1.0))
check("kappa is configurable: a wider pessimistic share is at least as cautious", tgt(wide) >= tgt(good))
for kw in ({"band_kappa": 0.1}, {"band_kappa": float("nan")}, {"max_grid_charge_kw": 0.0}, {"max_grid_charge_kw": float("inf")},
           {"target_step_pct": 0.0}, {"target_step_pct": 60.0}, {"pv_array_kwp": -1.0}, {"baseline_guard_ratio": 0.0}):
    try:
        SiteConfig(**kw)
        ok = False
    except ValueError:
        ok = True
    check(f"nonsense advisor config refused: {kw}", ok)
src = (ROOT / "intelligence" / "advisor.py").read_text(encoding="utf-8")
check("advisor.py no longer defines the 8 kW cap, the target step or kappa as module constants",
      all(f"\n{n} = " not in src for n in ("KAPPA", "MAX_GRID_CHARGE_KW", "TARGET_STEP_PCT")))
check("the config hash covers the new fields", SiteConfig().config_hash() != replace(cfg, band_kappa=1.0).config_hash()
      and SiteConfig().config_hash() != replace(cfg, max_grid_charge_kw=7.0).config_hash())

# ---------------------------------------------------------------------------------------------------------------
section("[7] low-history cold start")
for n_days in (0, 3, 6):
    h = make_history(START, max(n_days, 1), cfg, seed=6)
    r = replay(h, cfg, local_wall(START + timedelta(days=max(n_days, 1)), 21 * 60 + 30, tz), None, soc_override=62.0)
    check(f"{n_days} days of history: INSUFFICIENT_HISTORY, retain the battery, export withheld, guard unavailable, valid JSON",
          r["status"] == "INSUFFICIENT_HISTORY" and tgt(r) == 100.0 and r["recommended"]["safe_export"]["kwh"] == 0.0
          and r["load_baseline_guard"]["active"] is False and r["confidence"]["label"] in ("INSUFFICIENT", "LOW")
          and json.dumps(r, allow_nan=False, default=str) is not None, f"{r['status']} {tgt(r)} {r['confidence']}")
h20 = make_history(START, 20, cfg, seed=6)
r20 = replay(h20, cfg, local_wall(START + timedelta(days=20), 21 * 60 + 30, tz), None, soc_override=62.0)
check("20 days: not INSUFFICIENT, the guard is available (>= 14 days) and quiet", r20["status"] != "INSUFFICIENT_HISTORY" and r20["load_baseline_guard"]["active"] is False
      and r20["load_baseline_guard"]["baseline_day_kwh"] is not None, str(r20["load_baseline_guard"]))
r10 = replay(make_history(START, 10, cfg, seed=6), cfg, local_wall(START + timedelta(days=10), 21 * 60 + 30, tz), None, soc_override=62.0)
check("10 days: guard reports 'unavailable', does not crash and does not activate", r10["load_baseline_guard"]["active"] is False and "note" in r10["load_baseline_guard"])

# ---------------------------------------------------------------------------------------------------------------
section("[8] synthetic fixtures are deterministic")
def digest(rep: dict) -> str:
    import hashlib
    rep = dict(rep)
    return hashlib.sha256(json.dumps(rep, sort_keys=True, default=str).encode()).hexdigest()
check("same seed, same history, same report byte for byte (in process)", digest(run()) == digest(run()))
check("a different seed gives a different history", digest(run()) != digest(replay(make_history(START, 75, cfg, seed=4), cfg, NOW, None, soc_override=62.0)))
SNIPPET = (
    "import sys, json, hashlib\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from datetime import date\n"
    "from intelligence.config import SiteConfig\n"
    "from intelligence.synthetic import make_history, solcast_like\n"
    "from intelligence.replay import replay\n"
    "from intelligence.timeutil import local_wall, zone\n"
    "cfg = SiteConfig(); tz = zone(cfg.tz)\n"
    "h = make_history(date(2026, 7, 1), 75, cfg, seed=3)\n"
    "fc = {'solcast': solcast_like(h, cfg, over_factor=1.0, noise=0.08)}\n"
    "r = replay(h, cfg, local_wall(date(2026, 9, 9), 21 * 60 + 30, tz), fc, soc_override=62.0)\n"
    "print(hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest())\n"
)
outs = []
for seed in ("0", "1", "12345"):
    env = dict(os.environ, PYTHONHASHSEED=seed)
    outs.append(subprocess.run([sys.executable, "-c", SNIPPET], capture_output=True, text=True, env=env, timeout=600).stdout.strip())
check("the report is identical across interpreter hash seeds and processes", len(set(outs)) == 1 and len(outs[0]) == 64, str(outs))
check("... and equals the in-process report", outs[0] == digest(run()), f"{outs[0]} {digest(run())}")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence safety-guard"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence safety-guard"} checks PASSED.")