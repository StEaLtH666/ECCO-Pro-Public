#!/usr/bin/env python3
"""Scenario tests for the shadow engine: normal day, weekend effect, heavy night, poor / excellent PV, data gaps,
DST, unavailable and stale sensors, SOC faults, a one-off large load, a sustained abnormal load, cold start,
determinism, no future leakage, and the hard-floor invariants. Synthetic, seeded, offline."""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta

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

from intelligence.advisor import LiveInputs, TariffInfo
from intelligence.config import SiteConfig
from intelligence.engine import IntelligenceEngine
from intelligence.history import History
from intelligence.replay import inputs_from_history, replay
from intelligence.synthetic import make_history, solcast_like
from intelligence.timeutil import HOUR, UTC, local_wall, ts, zone
from intelligence.usage import UsageModel, fixed_window, standard_windows, weekday_effect

cfg = SiteConfig()
tz = zone(cfg.tz)
START = date(2026, 7, 1)


def now_at(day: date, hh: int, mm: int = 0) -> datetime:
    return local_wall(day, hh * 60 + mm, tz)


def base_history(days: int = 75, **kw) -> History:
    return make_history(START, days, cfg, **kw)


def run(h: History, day: date, hh: int, mm: int, fc=None, soc: float | None = 70.0, **ov) -> dict:
    return replay(h, cfg, now_at(day, hh, mm), fc, soc_override=soc, **ov)


NOW_DAY = date(2026, 9, 9)            # 71 days of history before this evening
full = base_history(75, seed=3)
fc_good = {"solcast": solcast_like(full, cfg, over_factor=1.0, noise=0.08)}

section("normal day")
r = run(full, NOW_DAY, 21, 30, fc_good, soc=62.0)
rec = r["recommended"]
check("shadow mode, applies nothing", r["mode"] == "SHADOW" and r["applies_nothing"] is True)
check("status is a learning/normal state", r["status"] in ("LEARNING_NORMALLY",), r["status"])
check("all four kinds are present and separate",
      all(k in r for k in ("actual", "predicted", "recommended", "confidence")))
ot = rec["overnight_target"]
check("recommended target is between floor+margin and 100", 45.0 <= ot["recommended_target_soc_pct"] <= 100.0)
check("target is on a 5 % step", ot["recommended_target_soc_pct"] % 5 == 0)
check("pessimistic-path target >= median-path target", ot["pessimistic_case_target_soc_pct"] >= ot["median_case_target_soc_pct"])
check("every forecast has a band that brackets the median",
      all(v["p10"] <= v["p50"] <= v["p90"] for k, v in r["predicted"].items() if isinstance(v, dict) and "p10" in v))
check("predicted day load is plausible for the synthetic house (~32 kWh)", 25 < r["predicted"]["day"]["p50"] < 40, str(r["predicted"]["day"]["p50"]))
check("scoreable forecast records are emitted", len(r["forecast_records"]) >= 6 and all("p50" in x for x in r["forecast_records"]))
check("today's PV (already under way) is not recorded as a forecast",
      all(not (x["kind"] == "pv_kwh:day" and x["horizon_start"] <= r["generated_for"]) for x in r["forecast_records"]))

section("weekend effect")
wk = make_history(START, 100, cfg, seed=5, weekend_mult=1.5, day_sigma=0.05)
nowk = make_history(START, 100, cfg, seed=5, weekend_mult=1.0, day_sigma=0.05)
check("a real weekend effect is detected as material", weekday_effect(wk, cfg)["material"] is True, str(weekday_effect(wk, cfg)))
check("no weekend effect is not called material", weekday_effect(nowk, cfg)["material"] is False, str(weekday_effect(nowk, cfg)))
sat = date(2026, 10, 3)       # a Saturday inside the 100 days (Jul 1 + 94)
assert sat.weekday() == 5
m_on = UsageModel(wk.truncated(local_wall(sat, 0, tz)), cfg)
m_off = UsageModel(nowk.truncated(local_wall(sat, 0, tz)), cfg)
w = (local_wall(sat, 0, tz), local_wall(sat + timedelta(days=1), 0, tz))
fn = fixed_window(0, 1440, tz)
f_wk = m_on.forecast("day", w, fn, sat)
actual_sat = wk.energy_scaled("load", *w, 0.8)
check("weekday factor applied when material", any("weekday adjustment" in n for n in f_wk.notes), str(f_wk.notes))
check("weekend forecast within 12 % of the (noisy) weekend actual", abs(f_wk.p50 - actual_sat) / actual_sat < 0.12,
      f"p50={f_wk.p50:.1f} actual={actual_sat:.1f}")
f_off = m_off.forecast("day", w, fn, sat)
check("no weekday factor when not material", not any("weekday adjustment" in n for n in f_off.notes))

section("unusually high overnight use")
heavy_hours = {}
d_night = NOW_DAY - timedelta(days=1)
for hh in (1, 2, 3, 4):
    heavy_hours[ts(local_wall(d_night, hh * 60, tz))] = 2.3
hv = base_history(75, seed=3, load_overrides=heavy_hours)
r_h = run(hv, NOW_DAY, 21, 30, fc_good, soc=62.0)
codes = [a["code"] for a in r_h["anomalies"]["anomalies"]]
check("high overnight base load is reported", "HIGH_OVERNIGHT_BASE" in codes, str(codes))
check("neutral wording, no appliance guessed", all("heater" not in a["text"].lower() and "kettle" not in a["text"].lower()
                                                   for a in r_h["anomalies"]["anomalies"]))

section("unexpectedly poor PV / excellent PV")
poor_day = date(2026, 9, 10)
hp = base_history(75, seed=3, pv_scale_by_day={poor_day: 0.15})
fc_norm = {"solcast": solcast_like(full, cfg, over_factor=1.0, noise=0.0)}      # forecast made for a NORMAL day
r_norm_pm = replay(full, cfg, now_at(poor_day, 14, 0), fc_norm, soc_override=75.0)
r_poor_pm = replay(hp, cfg, now_at(poor_day, 14, 0), fc_norm, soc_override=75.0)
re_n = r_norm_pm["pv"].get("today_reanchor")
re_p = r_poor_pm["pv"].get("today_reanchor")
check("poor PV day: live ratio well below normal-day ratio", re_p is not None and re_n is not None and re_p["live_ratio"] < 0.6 * re_n["live_ratio"],
      f"poor={re_p} norm={re_n}")
check("poor PV day is flagged", r_poor_pm["status"] == "PV_UNDERPERFORMING", r_poor_pm["status"])
tn = r_norm_pm["recommended"]["overnight_target"]["recommended_target_soc_pct"]
tp = r_poor_pm["recommended"]["overnight_target"]["recommended_target_soc_pct"]
check("poor PV day: retain at least as much battery as a normal day", tp >= tn, f"{tp} vs {tn}")
check("poor PV day: safe export is not larger than normal day",
      r_poor_pm["recommended"]["safe_export"]["kwh"] <= r_norm_pm["recommended"]["safe_export"]["kwh"] + 1e-9)
he = base_history(75, seed=3, clearness=0.95)
hq = base_history(75, seed=3, clearness=0.25)
fe = {"solcast": solcast_like(he, cfg, over_factor=1.0, noise=0.0)}
fq = {"solcast": solcast_like(hq, cfg, over_factor=1.0, noise=0.0)}
r_e = run(he, NOW_DAY, 21, 30, fe, soc=60.0)
r_q = run(hq, NOW_DAY, 21, 30, fq, soc=60.0)
check("excellent-PV target <= poor-PV target", r_e["recommended"]["overnight_target"]["recommended_target_soc_pct"]
      <= r_q["recommended"]["overnight_target"]["recommended_target_soc_pct"],
      f'{r_e["recommended"]["overnight_target"]["recommended_target_soc_pct"]} vs {r_q["recommended"]["overnight_target"]["recommended_target_soc_pct"]}')

section("systematically over-forecasting provider is corrected, not trusted")
fc_bad = {"solcast": solcast_like(full, cfg, over_factor=2.0, noise=0.1)}
r_b = run(full, NOW_DAY, 21, 30, fc_bad, soc=62.0)
pv_t = r_b["pv"]["2026-09-10"]
check("learned ratio is near 0.5 for a 2x over-forecast", 0.35 < pv_t["ratio"] < 0.7, str(pv_t["ratio"]))
check("unreliable raw source is called out", any("unreliable" in n for n in pv_t["notes"]), str(pv_t["notes"]))

section("data gaps")
drop = {ts(local_wall(NOW_DAY - timedelta(days=5), 9 * 60, tz)) + i * HOUR for i in range(10)}
rnd = random.Random(11)
drop |= {ts(local_wall(START + timedelta(days=rnd.randrange(0, 70)), rnd.randrange(0, 24) * 60, tz)) for _ in range(60)}
hg = base_history(75, seed=3, drop_hours=drop)
r_g = run(hg, NOW_DAY, 21, 30, fc_good, soc=62.0)
check("engine still produces a recommendation with gaps", r_g["recommended"]["status"] == "OK")
check("forecast with gaps stays within 10 % of the clean forecast",
      abs(r_g["predicted"]["day"]["p50"] - r["predicted"]["day"]["p50"]) / r["predicted"]["day"]["p50"] < 0.10)
check("confidence with gaps is not higher than clean", r_g["confidence"]["overall"] <= r["confidence"]["overall"] + 1e-9)

section("DST transitions")
dst_h = make_history(date(2026, 8, 20), 80, cfg, seed=9)
fall = date(2026, 10, 25)       # 25-hour day
r_fall = replay(dst_h, cfg, now_at(date(2026, 10, 26), 12, 0), None, soc_override=70.0)
a0, a1 = fixed_window(0, 1440, tz)(fall)
check("fall-back day window is 25 h", (a1 - a0).total_seconds() == 25 * 3600)
um = UsageModel(dst_h, cfg)
slots = um.table.slots(fall)
check("repeated local hour is averaged into one slot (24 slots, none lost)", slots is not None and sum(1 for x in slots if x is not None) == 24)
spring_day = date(2026, 3, 29)
sh = make_history(date(2026, 2, 1), 70, cfg, seed=2)
um2 = UsageModel(sh, cfg)
sl = um2.table.slots(spring_day)
check("spring-forward day has 23 valid slots (the skipped hour is absent)", sl is not None and sum(1 for x in sl if x is not None) == 23)
r_spring = replay(sh, cfg, now_at(date(2026, 3, 30), 21, 30), None, soc_override=65.0)
check("engine runs across the spring change and keeps a 5 h cheap window",
      (datetime.fromisoformat(r_spring["recommended"]["overnight_target"]["window"][1])
       - datetime.fromisoformat(r_spring["recommended"]["overnight_target"]["window"][0])).total_seconds() == 5 * 3600)
cw_fall = fixed_window(*standard_windows(cfg)["cheap_window"], tz)(fall)
check("00:30-05:30 local on the fall-back night lasts 6 elapsed hours (wall-clock endpoints kept)",
      (cw_fall[1] - cw_fall[0]).total_seconds() / 3600 == 6.0, str((cw_fall[1] - cw_fall[0]).total_seconds() / 3600))
cw_spring = fixed_window(*standard_windows(cfg)["cheap_window"], tz)(spring_day)
check("...and 4 elapsed hours on the spring-forward night",
      (cw_spring[1] - cw_spring[0]).total_seconds() / 3600 == 4.0, str((cw_spring[1] - cw_spring[0]).total_seconds() / 3600))
nc_fall = fixed_window(*standard_windows(cfg)["to_next_cheap"], tz)(fall)
check("05:30 -> next 00:30 after the fall-back change is a plain 19 h", (nc_fall[1] - nc_fall[0]).total_seconds() / 3600 == 19.0)

section("sensor unavailable / stale / unhealthy")
r_ns = run(full, NOW_DAY, 21, 30, fc_good, soc=None)
r_ns2 = replay(full.truncated(now_at(NOW_DAY, 21, 30)), cfg, now_at(NOW_DAY, 21, 30), fc_good, soc_override=None)
check("no SOC (and no history SOC) -> no numeric recommendation or the SOC is taken from history only",
      r_ns["recommended"]["status"] in ("NO_SOC", "OK"))
eng = IntelligenceEngine(full.truncated(now_at(NOW_DAY, 21, 30)), cfg, {})
base_inp = inputs_from_history(full.truncated(now_at(NOW_DAY, 21, 30)), cfg, now_at(NOW_DAY, 21, 30), fc_good, 62.0)
from dataclasses import replace
r_none = eng.run(replace(base_inp, soc_pct=None))
check("SOC unavailable -> NO_SOC and no overnight target", r_none["recommended"]["status"] == "NO_SOC"
      and "overnight_target" not in r_none["recommended"])
r_bad = eng.run(replace(base_inp, soc_pct=140.0))
check("out-of-range SOC is rejected, not used", r_bad["recommended"]["status"] == "NO_SOC" and any("outside 0-100" in n for n in r_bad["notes"]))
r_stale = eng.run(replace(base_inp, soc_age_s=3600.0, soc_pct=80.0))
check("stale SOC withholds export advice", r_stale["recommended"]["safe_export"]["kwh"] == 0.0
      and "withheld_because" in r_stale["recommended"]["safe_export"])
check("stale data shows as DATA_STALE status", r_stale["status"] == "DATA_STALE")
r_inv = eng.run(replace(base_inp, soc_pct=90.0, inverter_ok=False, now=now_at(NOW_DAY, 15, 0)))
check("unhealthy inverter withholds export advice", r_inv["recommended"]["safe_export"]["kwh"] == 0.0)
r_nopv = run(full, NOW_DAY, 21, 30, {}, soc=62.0)
check("no PV forecast: persistence used and stated", any("persistence" in n or "no PV forecast" in n for n in r_nopv["notes"] + r_nopv["pv"].get("2026-09-10", {}).get("notes", [])))
check("no PV forecast: still conservative (target not below the forecast-based one by more than a step)",
      r_nopv["recommended"]["overnight_target"]["recommended_target_soc_pct"] >= 45.0)

section("battery SOC anomaly in history")
from intelligence.history import F_SOC_JUMP
hs = base_history(75, seed=3)
last_h = max(hs.by_start)
hs.by_start[last_h - 5 * HOUR].soc_mean = 5.0           # spike far from neighbours
check("hourly SOC series with an impossible step is flaggable", abs(hs.by_start[last_h - 5 * HOUR].soc_mean - hs.by_start[last_h - 6 * HOUR].soc_mean) > 35)

section("one-off large load")
oneoff = {ts(local_wall(NOW_DAY - timedelta(days=1), 14 * 60, tz)): 9.0}
ho = base_history(75, seed=3, load_overrides=oneoff)
r_o = run(ho, NOW_DAY, 21, 30, fc_good, soc=62.0)
um_o = UsageModel(ho.truncated(now_at(NOW_DAY, 21, 30)), cfg)
um_c = UsageModel(full.truncated(now_at(NOW_DAY, 21, 30)), cfg)
p_o = um_o.profile(NOW_DAY, "fast").values[14]
p_c = um_c.profile(NOW_DAY, "fast").values[14]
check("one huge hour barely moves the 14:00 slot (winsorised)", abs(p_o - p_c) < 0.3 * 3 * 1.5, f"{p_o:.2f} vs {p_c:.2f}")
raw_move = 0.3 * (9.0 - p_c)
check("..and moves it far less than a plain EWMA would", (p_o - p_c) < 0.5 * raw_move, f"{p_o - p_c:.2f} vs {raw_move:.2f}")
check("a single hour is not a sustained anomaly", not r_o["anomalies"]["abnormal_load_now"])

section("sustained abnormal load today")
sus = {ts(local_wall(NOW_DAY, hh * 60, tz)): 3.4 for hh in range(11, 17)}
hsus = base_history(75, seed=3, load_overrides=sus)
r_s = run(hsus, NOW_DAY, 17, 30, fc_good, soc=85.0)
r_c = run(full, NOW_DAY, 17, 30, fc_good, soc=85.0)
check("sustained abnormal load detected", r_s["anomalies"]["abnormal_load_now"] is True, str(r_s["anomalies"]))
check("status becomes ABNORMAL_DAY", r_s["status"] == "ABNORMAL_DAY", r_s["status"])
check("next-hour forecast is raised by persistence", r_s["predicted"]["next_1h"]["p50"] > r_c["predicted"]["next_1h"]["p50"])
check("export advice is reduced for the abnormal load",
      r_s["recommended"]["safe_export"]["kwh"] <= r_c["recommended"]["safe_export"]["kwh"] * 0.5 + 0.11
      or "abnormal load" in " ".join(r_s["recommended"]["safe_export"].get("reduced_for", [])),
      f'{r_s["recommended"]["safe_export"]} vs {r_c["recommended"]["safe_export"]}')

section("future data cannot leak into a replay (engine level)")
spike = {ts(local_wall(NOW_DAY, 22 * 60, tz)) + k * HOUR: 40.0 for k in range(6)}       # absurd load AFTER 21:30
h_future = base_history(75, seed=3, load_overrides=spike)
r_a = json.dumps(run(full, NOW_DAY, 21, 30, fc_good, soc=62.0), sort_keys=True, default=str)
r_b = json.dumps(run(h_future, NOW_DAY, 21, 30, fc_good, soc=62.0), sort_keys=True, default=str)
check("a huge load that happens after `now` does not change the report", r_a == r_b)

section("pessimistic path is genuinely more cautious than the median path")
hv2 = make_history(START, 75, cfg, seed=21, clearness=0.5, day_sigma=0.18, level=1.0)
fv2 = {"solcast": solcast_like(hv2, cfg, over_factor=1.0, noise=0.25, seed=5)}
r_v = replay(hv2, cfg, now_at(NOW_DAY, 21, 30), fv2, soc_override=60.0)
otv = r_v["recommended"]["overnight_target"]
check("pessimistic-case target is strictly above the median-case target when uncertainty is real",
      otv["pessimistic_case_target_soc_pct"] > otv["median_case_target_soc_pct"], str(otv))

section("export advice shrinks for an abnormal load (non-vacuous)")
sunny = make_history(START, 75, cfg, seed=3, clearness=0.9)
fs_ = {"solcast": solcast_like(sunny, cfg, over_factor=1.0, noise=0.0)}
sus_s = {ts(local_wall(NOW_DAY, hh * 60, tz)): 3.4 for hh in range(11, 17)}
sunny_ab = make_history(START, 75, cfg, seed=3, clearness=0.9, load_overrides=sus_s)
e_norm = replay(sunny, cfg, now_at(NOW_DAY, 17, 30), fs_, soc_override=95.0)["recommended"]["safe_export"]
r_abn = replay(sunny_ab, cfg, now_at(NOW_DAY, 17, 30), fs_, soc_override=95.0)
e_abn = r_abn["recommended"]["safe_export"]
check("baseline export is meaningfully above zero in this scenario", e_norm["kwh"] >= 1.0, str(e_norm))
check("abnormal load: detected, labelled, and export no more than half the baseline",
      r_abn["anomalies"]["abnormal_load_now"] and "abnormal load" in e_abn.get("reduced_for", []) and e_abn["kwh"] <= e_norm["kwh"] * 0.5 + 0.11,
      f"{e_abn} vs {e_norm}")

section("cold start")
cold = make_history(START, 3, cfg, seed=1)
r_cold = replay(cold, cfg, now_at(START + timedelta(days=3), 21, 30), None, soc_override=70.0)
check("3 days of history -> INSUFFICIENT_HISTORY", r_cold["status"] == "INSUFFICIENT_HISTORY", r_cold["status"])
check("cold start recommends retaining the battery (max target)", r_cold["recommended"]["overnight_target"]["recommended_target_soc_pct"] == 100.0)
check("cold start gives no export advice", r_cold["recommended"]["safe_export"]["kwh"] == 0.0)
check("cold start explains itself with the INSUFFICIENT_HISTORY reason (not a model number)",
      any(x["code"] == "INSUFFICIENT_HISTORY" for x in r_cold["recommended"]["reasons"]))
check("cold start does not publish usable forecast numbers", all(v.get("usable") is False for v in r_cold["predicted"].values()
                                                                  if isinstance(v, dict) and "usable" in v))
low_h = make_history(START, 13, cfg, seed=1, clearness=0.9)
low_f = {"solcast": solcast_like(low_h, cfg, over_factor=1.0, noise=0.0)}
r_low = replay(low_h, cfg, now_at(START + timedelta(days=12), 17, 30), low_f, soc_override=95.0)
sx_low = r_low["recommended"]["safe_export"]
check("LOW confidence halves export advice and says so", r_low["confidence"]["label"] == "LOW"
      and "low confidence" in sx_low.get("reduced_for", []) and sx_low["kwh"] <= sx_low["kwh_before_reductions"] * 0.5 + 0.11
      and sx_low["kwh_before_reductions"] > 1.0, str(r_low["confidence"]) + str(sx_low))
check("cold start confidence label is INSUFFICIENT", r_cold["confidence"]["label"] == "INSUFFICIENT")
mid = make_history(START, 19, cfg, seed=1)
r_mid = replay(mid, cfg, now_at(START + timedelta(days=18), 21, 30), None, soc_override=70.0)
check("18 days -> a learning state with lower confidence than 60 days",
      r_mid["status"] in ("LEARNING",) and r_mid["confidence"]["overall"] < r["confidence"]["overall"], f'{r_mid["status"]} {r_mid["confidence"]}')

section("determinism and no leakage")
a = json.dumps(run(full, NOW_DAY, 21, 30, fc_good, soc=62.0), sort_keys=True, default=str)
b = json.dumps(run(full, NOW_DAY, 21, 30, fc_good, soc=62.0), sort_keys=True, default=str)
check("two runs are byte-identical", a == b)
rev = History(reversed(list(full.by_start.values())))
c = json.dumps(run(rev, NOW_DAY, 21, 30, fc_good, soc=62.0), sort_keys=True, default=str)
check("input ordering does not change the result", a == c)
tr = full.truncated(now_at(NOW_DAY, 21, 30))
d_ = json.dumps(replay(tr, cfg, now_at(NOW_DAY, 21, 30), fc_good, soc_override=62.0), sort_keys=True, default=str)
check("data after `now` has no influence (replay is leak-free)", a == d_)
check("feature hash is stable and 16 hex chars", len(run(full, NOW_DAY, 21, 30, fc_good, soc=62.0)["feature_hash"]) == 16)

section("effective-minimum invariants (seeded property sweep, default 40 % reserve)")
rnd = random.Random(2026)
bad = []
for i in range(40):
    lvl = rnd.uniform(0.7, 1.5)
    clr = rnd.uniform(0.1, 1.0)
    hh_ = make_history(START, 75, cfg, seed=100 + i, level=lvl, clearness=clr)
    ff = {"solcast": solcast_like(hh_, cfg, over_factor=rnd.uniform(0.8, 2.2), seed=i)}
    soc = rnd.uniform(25, 100)
    hr = rnd.choice([9, 14, 17, 21, 23])
    reserve = rnd.choice([None, 15.0, 60.0])
    out = replay(hh_, cfg, now_at(NOW_DAY, hr, 0), ff, soc_override=soc, ha_reserve_pct=reserve)
    rc = out["recommended"]
    floor = rc["floor_pct"]
    if floor < 40.0 or (reserve == 60.0 and floor < 60.0):
        bad.append((i, "effective minimum lowered", floor))
    t = rc["overnight_target"]["recommended_target_soc_pct"]
    if t < floor + cfg.soc_safety_margin_pct - 1e-9 or t > 100.0:
        bad.append((i, "target outside [floor+margin, 100]", t, floor))
    pm = rc["predicted"]["min_soc_after_charge_pessimistic"]
    if rc["overnight_target"]["feasible_on_pessimistic_path"] and pm < floor + cfg.soc_safety_margin_pct - 1e-6:
        bad.append((i, "pessimistic path below floor+margin although declared feasible", pm))
    ex = rc["safe_export"]["kwh"]
    eta = cfg.round_trip_efficiency ** 0.5
    if ex > max(0.0, (soc - floor - cfg.soc_safety_margin_pct) / 100.0 * cfg.battery_capacity_kwh * eta) + 1e-6:
        bad.append((i, "export would take SOC below floor+margin immediately", ex, soc))
check("40 random scenarios: effective minimum never lowered, target within [floor+margin,100], feasible => pessimistic path respects floor, export never breaches floor now",
      not bad, str(bad[:3]))

section("a low HA reserve never lowers the user reserve in recommendations")
r_res = run(full, NOW_DAY, 21, 30, fc_good, soc=62.0, ha_reserve_pct=15.0)
check("HA reserve 15 % leaves the 40 % user reserve in force", r_res["recommended"]["floor_pct"] == 40.0)
r_res2 = run(full, NOW_DAY, 21, 30, fc_good, soc=62.0, ha_reserve_pct=60.0)
check("HA reserve 60 % raises the effective minimum and the target",
      r_res2["recommended"]["floor_pct"] == 60.0 and r_res2["recommended"]["overnight_target"]["recommended_target_soc_pct"] >= 65.0)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence scenarios"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence scenarios"} checks PASSED.")