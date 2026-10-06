#!/usr/bin/env python3
"""Arithmetic and gate tests that pin the numbers, not just the direction: SOC simulation maths, window-edge splitting,
slot-floor charging semantics, the analytic safe-export bound, fail-closed export gates, scorecard weekday keys and the
multiple-comparison table, PV coverage feedback, interval floor, anomaly persistence, energy plausibility, useful-PV
interpolation, expert promotion win share. Written after an independent review showed the suite caught qualitative
regressions but not wrong arithmetic (22 of 41 mutations survived)."""

from __future__ import annotations

import ast
import json
import math
import sys
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

from intelligence.advisor import LiveInputs, Planner, advise, default_cheap_windows
from intelligence.battery import Step, build_steps, eta_one_way, simulate
from intelligence.config import SiteConfig
from intelligence.history import F_IMPLAUSIBLE, HourRecord, History, build_history, counter_to_hourly
from intelligence.pv import PvModel, useful_pv_start
from intelligence.scorecard import Scorecard, t_crit
from intelligence.synthetic import make_history, solcast_like
from intelligence.timeutil import HOUR, UTC, local_wall, ts, utc_from_ts, zone
from intelligence.usage import UsageModel, adaptive_weights, fixed_window

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "intelligence" / "tools"))
import render_ha_prototype as rhp  # noqa: E402

cfg = SiteConfig()
tz = zone(cfg.tz)
eta = eta_one_way(cfg)
cap = cfg.battery_capacity_kwh

section("SOC arithmetic")
st = [Step(utc_from_ts(0), utc_from_ts(HOUR), 3.0, 0.0)]
r = simulate(80.0, st, cfg, 40.0)
check("discharge: SOC drop = load / eta / capacity", abs((80.0 - r.final_soc) - 3.0 / eta / cap * 100.0) < 1e-9, str(r.final_soc))
st = [Step(utc_from_ts(0), utc_from_ts(HOUR), 0.0, 4.0)]
r = simulate(50.0, st, cfg, 40.0)
check("PV surplus: SOC gain = surplus * eta / capacity", abs((r.final_soc - 50.0) - 4.0 * eta / cap * 100.0) < 1e-9)
r = simulate(98.0, st, cfg, 40.0)
check("PV beyond 100 % is overflow, not stored", r.final_soc == 100.0 and r.pv_overflow_kwh > 0)
st = [Step(utc_from_ts(0), utc_from_ts(HOUR), 10.0, 0.0)]
r = simulate(50.0, st, cfg, 40.0)
soc_after = 50.0 - 10.0 / eta / cap * 100.0
check("floor-holding import is the energy needed to stay at the floor",
      abs(r.import_to_hold_floor_kwh - (40.0 - soc_after) / 100.0 * cap * eta) < 1e-9 and r.import_to_hold_floor_kwh > 5.0)
check("unconstrained track still shows where SOC would go", abs(r.final_soc - soc_after) < 1e-9)

section("charging-step semantics (cautious slot-floor reading)")
t0 = utc_from_ts(0)
cstep = [Step(t0, t0 + timedelta(hours=1), 1.0, 0.0, charge_cap_kwh=8.0)]
r = simulate(40.0, cstep, cfg, 40.0, charge_target_pct=60.0)
want = 20.0 / 100.0 * cap / eta
check("below target: grid charges toward it while carrying the house load", abs(r.grid_charge_kwh - min(want, 8.0 - 1.0)) < 1e-9
      and abs(r.final_soc - (40.0 + min(want, 7.0) * eta / cap * 100.0)) < 1e-9, str((r.grid_charge_kwh, r.final_soc)))
r = simulate(80.0, cstep, cfg, 40.0, charge_target_pct=60.0)
check("above target: battery covers the house down to the target (not held where it was)",
      abs(r.final_soc - (80.0 - 1.0 / eta / cap * 100.0)) < 1e-9 and r.grid_charge_kwh == 0.0, str(r.final_soc))
heavy = [Step(t0, t0 + timedelta(hours=1), 12.0, 0.0, charge_cap_kwh=8.0)]
r = simulate(65.0, heavy, cfg, 40.0, charge_target_pct=60.0)
check("...and never below the slot target (grid covers the rest)", r.final_soc >= 60.0 - 1e-9, str(r.final_soc))

section("steps split at window edges, first/last hours apportioned")
w = (datetime(2026, 10, 4, 23, 30, tzinfo=UTC), datetime(2026, 10, 5, 4, 30, tzinfo=UTC))
steps = build_steps(datetime(2026, 10, 4, 22, 0, tzinfo=UTC), datetime(2026, 10, 5, 6, 0, tzinfo=UTC), lambda h: 1.0, lambda h: 0.0, [w], 8.0)
edges = {s.t0 for s in steps} | {s.t1 for s in steps}
check("steps break exactly at 23:30 and 04:30", w[0] in edges and w[1] in edges)
chg = [s for s in steps if s.charge_cap_kwh > 0]
check("charging capacity covers exactly the 5 window hours (8 kW x 5 h)", abs(sum(s.charge_cap_kwh for s in chg) - 40.0) < 1e-9)
check("no step outside the window carries charging capacity", all(w[0] <= s.t0 and s.t1 <= w[1] for s in chg))
first = build_steps(datetime(2026, 10, 4, 18, 30, tzinfo=UTC), datetime(2026, 10, 4, 20, 0, tzinfo=UTC), lambda h: 2.0, lambda h: 0.0)
check("a partial first hour takes only its share of the hour's energy", abs(first[0].load_kwh - 1.0) < 1e-9 and abs(first[1].load_kwh - 2.0) < 1e-9)
check("total load over a span equals the hours covered", abs(sum(s.load_kwh for s in steps) - 8.0) < 1e-9)

section("safe export: analytic bound under flat load, no PV")
now = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)               # 12:00 BST
windows = default_cheap_windows(cfg, now)
inp = LiveInputs(now=now, soc_pct=90.0, soc_age_s=10.0, inverter_ok=True, tariff=None)
planner = Planner(cfg, [1.0] * 24, (0.0, 0.0), {}, inp, [0.0] * 4, "HIGH", 1.0)


def adv(inp_, label="HIGH", abnormal=False, data_stale=False, win=windows):
    p = Planner(cfg, [1.0] * 24, (0.0, 0.0), {}, inp_, [0.0] * 4, label, 1.0)
    return advise(cfg, p, inp_, win, label, abnormal, None, None, None, data_stale)


out = adv(inp)
w0 = next(x for x in sorted(windows) if x[1] > now)[0]
hours = (w0 - now).total_seconds() / 3600.0
drop = hours * 1.0 / eta / cap * 100.0
expected = (90.0 - 45.0 - drop) / 100.0 * cap * eta
check("export = (SOC - floor - margin - discharge until the window) x capacity x eta", abs(out["safe_export"]["kwh"] - math.floor(expected * 10) / 10) < 0.11,
      f'{out["safe_export"]["kwh"]} vs {expected:.2f}')
check("export is measured against floor+margin (not the bare floor)", out["safe_export"]["kwh"] < (90.0 - 40.0 - drop) / 100.0 * cap * eta - 0.5)
check("export uses the AC-side efficiency direction (energy out = SOC points x capacity x eta)",
      out["safe_export"]["kwh"] < (90.0 - 45.0 - drop) / 100.0 * cap + 1e-9)

section("export gates fail closed")
base = dict(now=now, soc_pct=90.0, soc_age_s=10.0, inverter_ok=True)
check("healthy inputs give export advice", adv(LiveInputs(**base))["safe_export"]["kwh"] > 0)
check("unknown SOC age withholds", "withheld_because" in adv(LiveInputs(**{**base, "soc_age_s": None}))["safe_export"])
check("stale SOC age withholds", "withheld_because" in adv(LiveInputs(**{**base, "soc_age_s": 1800.0}))["safe_export"])
check("unknown inverter status withholds", "withheld_because" in adv(LiveInputs(**{**base, "inverter_ok": None}))["safe_export"])
check("unhealthy inverter withholds", "withheld_because" in adv(LiveInputs(**{**base, "inverter_ok": False}))["safe_export"])
check("stale learning data withholds", "withheld_because" in adv(LiveInputs(**base), data_stale=True)["safe_export"])
check("INSUFFICIENT history withholds", "withheld_because" in adv(LiveInputs(**base), label="INSUFFICIENT")["safe_export"])
sess_soon = [(now + timedelta(hours=2), now + timedelta(hours=3))]
check("a Saving Session within 3 h withholds", "withheld_because" in adv(LiveInputs(**base, saving_sessions=sess_soon))["safe_export"])
sess_now = [(now - timedelta(minutes=30), now + timedelta(minutes=30))]
check("a Saving Session already running withholds", "withheld_because" in adv(LiveInputs(**base, saving_sessions=sess_now))["safe_export"])
sess_far = [(now + timedelta(hours=8), now + timedelta(hours=9))]
check("a session more than 3 h away does not withhold", "withheld_because" not in adv(LiveInputs(**base, saving_sessions=sess_far))["safe_export"])
in_win = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)         # 02:00 BST, inside 00:30-05:30 local
check("an open charging window withholds", "withheld_because" in adv(LiveInputs(**{**base, "now": in_win}), win=default_cheap_windows(cfg, in_win))["safe_export"])
check("abnormal load halves export and says so", adv(LiveInputs(**base), abnormal=True)["safe_export"].get("reduced_for") == ["abnormal load"]
      and adv(LiveInputs(**base), abnormal=True)["safe_export"]["kwh"] <= adv(LiveInputs(**base))["safe_export"]["kwh"] * 0.5 + 0.11)

section("pessimism: hard path is stricter than the target path")
pl = Planner(cfg, [1.0] * 24, (-0.2, 0.2), {}, inp, [0.0] * 4, "HIGH", 1.0)
check("hard load multiplier > pessimistic > median", pl.load_mult("hard") > pl.load_mult("pess") > pl.load_mult("p50") == 1.0)
pl_low = Planner(cfg, [1.0] * 24, (-0.2, 0.2), {}, inp, [0.0] * 4, "LOW", 1.0)
check("LOW confidence widens the pessimistic path", pl_low.load_mult("pess") > pl.load_mult("pess"))

section("pre-window risk is reported")
low_soc = LiveInputs(now=datetime(2026, 10, 5, 19, 0, tzinfo=UTC), soc_pct=48.0, soc_age_s=5.0, inverter_ok=True)
pl2 = Planner(cfg, [1.6] * 24, (0.0, 0.15), {}, low_soc, [0.0] * 4, "HIGH", 1.0)
o2 = advise(cfg, pl2, low_soc, default_cheap_windows(cfg, low_soc.now), "HIGH", False, None, None, None)
codes = [x["code"] for x in o2["reasons"]]
check("floor risk before the cheap window is stated", any(c in ("PRE_WINDOW_RISK", "PRE_WINDOW_FLOOR") for c in codes), str(codes))

section("scorecard: weekday key and multiple-comparison table")
check("t critical values are the Bonferroni-style table", abs(t_crit(7) - 5.41) < 1e-9 and abs(t_crit(30) - 3.65) < 1e-9 and t_crit(1000) > 3.0)
sc = Scorecard(":memory:")
wed = datetime(2026, 10, 7, 0, 0, tzinfo=tz).astimezone(UTC)
rep = {"generated_for": "2026-10-06T20:30:00+00:00", "features": {}, "model_version": "t", "config_hash": "c", "feature_hash": "f",
       "status": "OK", "confidence": {"overall": 0.8}, "mode": "SHADOW", "recommended": {},
       "forecast_records": [{"kind": "load_kwh:day", "unit": "kWh", "horizon_start": wed.isoformat(),
                             "horizon_end": (wed + timedelta(hours=24)).isoformat(), "p10": 20, "p50": 30, "p90": 40, "confidence": 0.8}]}
sc.record_run(rep)
wd = sc.db.execute("SELECT target_weekday FROM forecasts").fetchone()[0]
check("a Wednesday whole-day forecast is stored as Wednesday (horizon START, not end)", wd == 2, str(wd))
sc3 = Scorecard(":memory:")
sc3.db.execute("INSERT INTO model_runs (issued_utc, model_version, config_hash, feature_hash, features_json, status) VALUES ('2026-08-01T00:00:00+00:00','t','c','f','{}','OK')")
errs = [2.0, -0.5, 1.5, 0.2, 1.8, -1.0]            # mean 0.67, sd ~1.2: t ~1.4, far below the corrected threshold
for i, e in enumerate(errs):
    h0 = datetime(2026, 8, 5, 5, 30, tzinfo=UTC) + timedelta(weeks=i)
    sc3.db.execute("INSERT INTO forecasts (run_id, kind, unit, issued_utc, horizon_start_utc, horizon_end_utc, horizon_minutes, lead_minutes, target_weekday, target_hour, "
                   "predicted, band_low, band_high, model_version, feature_hash, status, actual, error, abs_error, in_band) "
                   "VALUES (1,'load_kwh:morning','kWh','2026-08-01T00:00:00+00:00',?,?,210,500,2,9,4,3,5,'t','f','SCORED',?,?,?,0)",
                   (h0.isoformat(), (h0 + timedelta(hours=3.5)).isoformat(), 4 + e, e, abs(e)))
sc3.db.commit()
check("noisy small-sample bias is NOT reported as a finding", sc3.insights(datetime(2026, 10, 1, tzinfo=UTC)) == [])

section("PV coverage feedback widens a band that stopped holding")
# modest clearness keeps even the 4x-shifted raw forecast below the array's physical ceiling (that case is the plausibility guard's)
hist = make_history(date(2026, 7, 1), 100, cfg, seed=2, clearness=0.35)
fc = solcast_like(hist, cfg, over_factor=2.0, noise=0.05, seed=3)
last_day = date(2026, 7, 1) + timedelta(days=95)
# regime shift: the last 14 days the forecast becomes 4x too high
shifted = {d: (v * 2.0 if d > last_day - timedelta(days=14) else v) for d, v in fc.items()}
pvm = PvModel(hist, cfg, {"solcast": shifted})
f1 = pvm.forecast_day(last_day, {"solcast": shifted[last_day]})
check("a band that failed on recent days is widened and says so", f1.inflation > 1.0 and any("widened" in n for n in f1.notes), str((f1.inflation, f1.notes)))
pvm2 = PvModel(hist, cfg, {"solcast": fc})
f2 = pvm2.forecast_day(last_day, {"solcast": fc[last_day]})
check("a stable regime is not widened", f2.inflation == 1.0)
check("widening lowers confidence", f1.confidence < f2.confidence)

section("intervals are never degenerate")
flat = make_history(date(2026, 7, 1), 60, cfg, seed=1, hour_noise=0.0, day_sigma=0.0)
um = UsageModel(flat, cfg)
d = date(2026, 8, 31)
fn = fixed_window(0, 1440, tz)
f = um.forecast("day", fn(d), fn, d)
check("perfectly stable data still gets a band of non-zero width", f.p10 < f.p50 < f.p90, f"{f.p10} {f.p50} {f.p90}")

section("anomaly persistence: 1 h is nothing, 2 h watch, 3 h abnormal")
base_h = make_history(date(2026, 7, 1), 75, cfg, seed=3)
nd = date(2026, 9, 9)


from intelligence.replay import replay  # noqa: E402


def abn(hours_high):
    ov = {ts(local_wall(nd, hh * 60, tz)): 3.8 for hh in hours_high}
    h = make_history(date(2026, 7, 1), 75, cfg, seed=3, load_overrides=ov)
    r_ = replay(h, cfg, local_wall(nd, 17 * 60 + 30, tz), None, soc_override=80.0)
    return r_["anomalies"]


a1 = abn([16])
a2 = abn([15, 16])
a3 = abn([14, 15, 16])
check("one high hour: nothing", not a1["abnormal_load_now"] and not a1["anomalies"], str(a1))
check("two high hours: WATCH only", not a2["abnormal_load_now"] and any(x["severity"] == "WATCH" for x in a2["anomalies"]), str(a2))
check("three high hours: ABNORMAL", a3["abnormal_load_now"] is True)

section("energy plausibility and clean-value preference")
H0 = ts(datetime(2026, 9, 1, tzinfo=UTC))
e, f = counter_to_hourly({H0: 100.0, H0 + HOUR: 5100.0, H0 + 2 * HOUR: 5101.0}, None, cfg)
check("a +5000 kWh one-hour counter glitch is dropped and flagged, not accepted as energy", (H0 + HOUR) not in e and F_IMPLAUSIBLE in f[H0 + HOUR], str((e, f)))
D, L = "sensor.d_", "sensor.l_"
profile = {"sources": [{"name": "dongle", "priority": 1, "entities": {"load_energy": {"id": D + "load"}}},
                       {"name": "legacy", "priority": 2, "entities": {"load_energy": {"id": L + "load"}}}]}
rows = []
for i, v in ((0, 100.0), (1, 101.0), (4, 104.0)):                  # dongle has a 3-hour gap -> interpolated 1/1/1
    rows.append({"statistic_id": D + "load", "start_ts": H0 + i * HOUR, "state": v})
for i, v in ((0, 10.0), (1, 11.0), (2, 11.2), (3, 13.0), (4, 14.0)):  # legacy measured every hour: 0.2, 1.8, 1.0
    rows.append({"statistic_id": L + "load", "start_ts": H0 + i * HOUR, "state": v})
hh = build_history(rows, profile, cfg)
check("a clean measured fallback hour replaces an interpolated primary hour", abs(hh.get(H0 + 2 * HOUR).e["load"] - 0.2) < 1e-9 and abs(hh.get(H0 + 3 * HOUR).e["load"] - 1.8) < 1e-9,
      str([hh.get(H0 + k * HOUR).e["load"] for k in (2, 3, 4)]))

section("useful-PV start is interpolated at the threshold")
cfg500 = SiteConfig(useful_pv_threshold_w=500.0)
day = date(2026, 6, 15)
recs = []
for k, w_ in enumerate([0, 0, 100, 300, 900, 1500]):                 # local hours 05..10 -> UTC 04..09 (BST)
    t_ = ts(local_wall(day, (5 + k) * 60, tz))
    recs.append(HourRecord(start=t_, pv_w_mean=float(w_), e={"pv": w_ / 1000.0}))
hp = History(recs)
st_ = useful_pv_start(hp, cfg500, day)
mid_prev = ts(local_wall(day, 8 * 60, tz)) + HOUR // 2             # 08:30 local mean 300 W
mid_now = ts(local_wall(day, 9 * 60, tz)) + HOUR // 2              # 09:30 local mean 900 W
expect = mid_prev + (500 - 300) / (900 - 300) * (mid_now - mid_prev)
check("crossing 500 W is interpolated between hour midpoints", st_ is not None and abs(ts(st_) - expect) < 2, str(st_))
check("a zero threshold would be caught (start is NOT the first daylight hour)", st_ is not None and ts(st_) > ts(local_wall(day, 8 * 60, tz)))

section("expert promotion needs a win share, not just a lower average")
n = 28
fast = [1.0, -1.0] * (n // 2)
slow_rare_big = [0.1 if i < 5 else 1.4 for i in range(n)]            # tiny errors on 5 days only
check("beating the fast expert on a few days is not promotion", adaptive_weights({"fast": fast, "slow": slow_rare_big, "median14": [1.2] * n}, n)["slow"] == 0.0)

section("re-anchoring really scales the rest of today")
hist2 = make_history(date(2026, 7, 1), 75, cfg, seed=3, pv_scale_by_day={date(2026, 9, 10): 0.15})
fc2 = {"solcast": solcast_like(make_history(date(2026, 7, 1), 75, cfg, seed=3), cfg, over_factor=1.0, noise=0.0)}
rp = replay(hist2, cfg, local_wall(date(2026, 9, 10), 14 * 60, tz), fc2, soc_override=75.0)
ra = rp["pv"]["today_reanchor"]
check("a poor-PV morning cuts the remaining-today estimate (factor well below 1)", ra is not None and ra["factor"] < 0.9, str(ra))
rn = replay(make_history(date(2026, 7, 1), 75, cfg, seed=3), cfg, local_wall(date(2026, 9, 10), 14 * 60, tz), fc2, soc_override=75.0)
t_poor = {x["t"]: x["soc_median"] for x in rp["recommended"]["trajectory"]}
t_norm = {x["t"]: x["soc_median"] for x in rn["recommended"]["trajectory"]}
common = sorted(set(t_poor) & set(t_norm))
check("...and the predicted SOC path for the rest of today is visibly lower than on a normal day",
      bool(common) and max(t_norm[k] - t_poor[k] for k in common) > 3.0, str((t_poor.get(common[0]), t_norm.get(common[0]))))

section("renderer never publishes an unusable forecast")
check("band() returns None for an INSUFFICIENT forecast", rhp.band({"p10": 1, "p50": 2, "p90": 3, "label": "INSUFFICIENT", "usable": False}) is None)
check("band() carries notes and window times for a usable one", len(rhp.band({"p10": 1, "p50": 2, "p90": 3, "label": "HIGH", "usable": True, "notes": ["n"], "t0": "a", "t1": "b"})) == 9)

section("authority separation (AST-based, scans tools/ too)")
pkg = ROOT / "intelligence"
bad_imports = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho",
               "ssl", "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc"}
no_process = {"subprocess", "os", "pty", "shutil"}
violations = []
for path in sorted(list(pkg.glob("*.py")) + list((pkg / "tools").glob("*.py"))):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    in_tools = path.parent.name == "tools"
    allowed_process = {"preview_dashboard.py": {"subprocess"}, "export_ha_statistics.py": set()}.get(path.name, set()) if in_tools else set()
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        for m in mods:
            if m in bad_imports or (m in no_process and m not in allowed_process and not in_tools) or (in_tools and m in ("subprocess",) and m not in allowed_process):
                violations.append((path.name, m))
        if isinstance(node, ast.Call):
            fn_ = node.func
            name = fn_.attr if isinstance(fn_, ast.Attribute) else getattr(fn_, "id", "")
            if name in ("system", "popen", "Popen", "exec", "eval", "__import__", "execv", "spawn"):
                if not (path.name == "preview_dashboard.py" and name in ("Popen", "run")):
                    violations.append((path.name, "call", name))
check("no network/serial/process/dynamic-exec in engine or tools (except the Node preview runner)", not violations, str(violations))
vocab = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish")
hits = []
for path in sorted(list(pkg.glob("*.py")) + list((pkg / "tools").glob("*.py"))):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
            if any(v in node.value.lower() for v in vocab):
                hits.append((path.name, node.value[:40]))
check("no control vocabulary in executable string literals", not hits, str(hits[:3]))

section("malformed inputs fail closed (independent review 2026-10-05)")
check("a lower technical minimum cannot lower the user's reserve; a lower HA reserve cannot either",
      SiteConfig(technical_min_soc_pct=10.0).effective_min_soc_pct(None) == 40.0 and SiteConfig(technical_min_soc_pct=10.0).effective_min_soc_pct(15.0) == 40.0)
check("a config may RAISE the reserve", SiteConfig(user_reserve_soc_pct=50.0).effective_min_soc_pct(None) == 50.0)
check("a NaN / infinite HA reserve is ignored; one above 100 is capped",
      cfg.effective_min_soc_pct(float("nan")) == 40.0 and cfg.effective_min_soc_pct(float("inf")) == 40.0 and cfg.effective_min_soc_pct(150.0) == 100.0)
_h_fc = make_history(date(2026, 7, 1), 75, cfg, seed=3)
_fc_bad = {"solcast": solcast_like(_h_fc, cfg, over_factor=1.0, noise=0.08)}
_now_bad = local_wall(date(2026, 9, 9), 19 * 60, tz)
for _age in (float("nan"), -5000.0):
    _r = replay(_h_fc, cfg, _now_bad, _fc_bad, soc_override=80.0, soc_age_s=_age, inverter_ok=True)
    _x = _r["recommended"]["safe_export"]
    check(f"SOC age {_age} is treated as stale: export withheld", _x["kwh"] == 0.0 and "stale" in _x.get("withheld_because", ""), str(_x))
_pvm = PvModel(_h_fc, cfg, _fc_bad)
for _bad in (float("nan"), float("inf"), -5.0):
    _f = _pvm.forecast_day(date(2026, 9, 9), {"solcast": _bad})
    check(f"a PV forecast of {_bad} is ignored (persistence, finite band)",
          _f.source != "solcast" and all(math.isfinite(v) and v >= 0.0 for v in (_f.p10, _f.p50, _f.p90)), _f.source)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence arithmetic / gates"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence arithmetic / gates"} checks PASSED.")