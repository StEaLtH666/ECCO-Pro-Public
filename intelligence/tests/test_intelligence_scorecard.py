#!/usr/bin/env python3
"""Tests: prediction scorecard (schema, idempotent recording, scoring, metrics, bias insights, void rules),
expert-weight promotion, recurring-signature discovery, and the authority-separation static check."""

from __future__ import annotations

import ast
import json
import sqlite3
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

from intelligence import stats
from intelligence.advisor import LiveInputs
from intelligence.anomaly import find_signatures
from intelligence.config import SiteConfig
from intelligence.replay import campaign, replay
from intelligence.scorecard import Scorecard, SCHEMA_VERSION
from intelligence.synthetic import make_history, solcast_like
from intelligence.timeutil import HOUR, UTC, local_wall, ts, zone
from intelligence.usage import PRIOR_WEIGHTS, PROMOTE_MAX_WEIGHT, WEIGHT_EVAL_DAYS, adaptive_weights

cfg = SiteConfig()
tz = zone(cfg.tz)
START = date(2026, 7, 1)
hist = make_history(START, 110, cfg, seed=4, day_sigma=0.08)
fc = {"solcast": solcast_like(hist, cfg, over_factor=1.0, noise=0.1)}

section("schema and idempotent recording")
sc = Scorecard(":memory:")
tables = {r["name"] for r in sc.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("tables exist", {"schema_meta", "model_runs", "forecasts", "recommendations"} <= tables)
check("schema version recorded", sc.db.execute("SELECT value FROM schema_meta").fetchone()["value"] == str(SCHEMA_VERSION))
cols = {r["name"] for r in sc.db.execute("PRAGMA table_info(forecasts)")}
need = {"issued_utc", "horizon_start_utc", "horizon_end_utc", "horizon_minutes", "predicted", "band_low", "band_high",
        "actual", "error", "abs_error", "pct_error", "in_band", "model_version", "feature_hash", "explanation_json",
        "status", "target_weekday", "target_hour"}
check("forecast table carries every required field (prediction, horizon, band, outcome, errors, model/feature id, explanation)",
      need <= cols, str(need - cols))
now0 = local_wall(START + timedelta(days=80), 21 * 60 + 30, tz)
rep = replay(hist, cfg, now0, fc, soc_override=62.0)
rid = sc.record_run(rep)
n1 = sc.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
rid2 = sc.record_run(rep)
n2 = sc.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
check("recording the same run twice is idempotent", rid == rid2 and n1 == n2 and n1 > 5, f"{rid} {rid2} {n1} {n2}")
row = sc.db.execute("SELECT * FROM forecasts WHERE kind='load_kwh:day'").fetchone()
check("stored forecast has band, lead time, model version and feature hash",
      row["band_low"] <= row["predicted"] <= row["band_high"] and row["model_version"] == rep["model_version"]
      and row["feature_hash"] == rep["feature_hash"] and row["lead_minutes"] is not None)
check("explanation is stored as JSON", "weights" in json.loads(row["explanation_json"]))
recs = {r["kind"]: r for r in sc.db.execute("SELECT * FROM recommendations")}
check("recommendations are stored in SHADOW mode only", recs and all(r["mode"] == "SHADOW" for r in recs.values()))

section("nothing scored before its horizon has passed")
early = sc.resolve(hist, cfg, now0 + timedelta(hours=1))
check("pending forecasts are not scored early", early == [] and sc.counts().get("SCORED", 0) == 0)

section("scoring, metrics and no look-ahead")
sc2 = Scorecard(":memory:")
n_runs = campaign(hist, cfg, fc, START + timedelta(days=60), START + timedelta(days=95), 21 * 60 + 30, sc2)
done = sc2.resolve(hist, cfg, local_wall(START + timedelta(days=100), 12 * 60, tz))
check("a 36-night campaign produced scored forecasts", n_runs == 36 and len(done) > 150, f"{n_runs} {len(done)}")
m = {x["kind"]: x for x in sc2.metrics()}
d = m["load_kwh:day"]
check("metrics expose MAE, RMSE, bias and interval coverage", all(k in d for k in ("mae", "rmse", "bias", "coverage")) and d["rmse"] >= d["mae"] - 1e-9)
check("synthetic-house day forecast MAE is a small fraction of the ~32 kWh day", d["mae"] < 4.5, f"{d['mae']:.2f}")
check("band coverage is close to the nominal 80 % on a stationary synthetic house", 0.6 <= d["coverage"] <= 1.0, f"{d['coverage']:.2f}")
check("PV forecast metrics are separate from load metrics", "pv_kwh:day" in m and m["pv_kwh:day"]["unit"] == "kWh")
rows = sc2.db.execute("SELECT * FROM forecasts WHERE status='SCORED' AND kind='load_kwh:day'").fetchall()
check("error sign convention: error = actual - predicted", all(abs(r["error"] - (r["actual"] - r["predicted"])) < 1e-9 for r in rows))
check("abs_error and in_band consistent", all(abs(r["abs_error"] - abs(r["error"])) < 1e-9
                                              and r["in_band"] == (1 if r["band_low"] <= r["actual"] <= r["band_high"] else 0) for r in rows))
by_wd = sc2.metrics(kind="load_kwh:day", group_by="target_weekday")
check("metrics can be grouped by weekday", 1 <= len(by_wd) <= 7 and all("target_weekday" in x for x in by_wd))

section("learning from error: bias findings are guarded")
check("no spurious weekday finding on an unbiased synthetic house", sc2.insights(local_wall(START + timedelta(days=100), 12 * 60, tz)) == [],
      str(sc2.insights(local_wall(START + timedelta(days=100), 12 * 60, tz))))
# manufacture a genuine Wednesday-morning under-forecast of ~1.2 kWh and check it is found
sc3 = Scorecard(":memory:")
rnd_vals = [0.9, 1.4, 1.1, 1.3, 1.2, 1.0, 1.5, 1.2]
base_issue = datetime(2026, 8, 3, 21, 0, tzinfo=UTC)
sc3.db.execute("INSERT INTO model_runs (issued_utc, model_version, config_hash, feature_hash, features_json, status) VALUES (?,?,?,?,?,?)",
               (base_issue.isoformat(), "t", "c", "f", "{}", "OK"))
for i, bias in enumerate(rnd_vals):
    wed = datetime(2026, 8, 5, 5, 30, tzinfo=UTC) + timedelta(weeks=i)     # Wednesdays
    sc3.db.execute(
        "INSERT INTO forecasts (run_id, kind, unit, issued_utc, horizon_start_utc, horizon_end_utc, horizon_minutes, lead_minutes, target_weekday, "
        "target_hour, predicted, band_low, band_high, model_version, feature_hash, status, actual, error, abs_error, in_band) "
        "VALUES (1,'load_kwh:morning','kWh',?,?,?,210,500,2,9,4.0,3.0,5.0,'t','f','SCORED',?,?,?,0)",
        (base_issue.isoformat(), wed.isoformat(), (wed + timedelta(hours=3.5)).isoformat(), 4.0 + bias, bias, abs(bias)))
sc3.db.commit()
ins = sc3.insights(datetime(2026, 9, 30, tzinfo=UTC))
check("'I have been underestimating Wednesday mornings by ~1.2 kWh' is produced", any("underestimating Wednesday mornings by 1.2 kWh" in t for t in ins), str(ins))

section("scenario-conditional SOC forecasts are not blamed on the model")
sc4 = Scorecard(":memory:")
nowx = local_wall(START + timedelta(days=80), 21 * 60 + 30, tz)
rx = replay(hist, cfg, nowx, fc, soc_override=60.0)
sc4.record_run(rx)
check("a clean pre-window SOC forecast is recorded (no controller dependence)",
      sc4.db.execute("SELECT COUNT(*) FROM forecasts WHERE kind='soc_pct:pre_window_hour'").fetchone()[0] == 1)
sc4.resolve(hist, cfg, nowx + timedelta(days=2))
row_soc = sc4.db.execute("SELECT * FROM forecasts WHERE kind='soc_pct:pre_window_hour'").fetchone()
check("pre-window SOC is scored against the hourly SOC statistic", row_soc["status"] == "SCORED" and row_soc["actual"] is not None, str(dict(row_soc)))
# a plan-conditional forecast whose plan was not what happened must be VOID, not an error
sc4.db.execute("INSERT INTO model_runs (issued_utc, model_version, config_hash, feature_hash, features_json, status) VALUES ('2026-09-01T20:00:00+00:00','t','c','f2','{}','OK')")
rid_c = sc4.db.execute("SELECT MAX(run_id) FROM model_runs").fetchone()[0]
t_end = local_wall(START + timedelta(days=70), 5 * 60 + 30, tz)
sc4.db.execute(
    "INSERT INTO forecasts (run_id, kind, unit, issued_utc, horizon_start_utc, horizon_end_utc, horizon_minutes, lead_minutes, target_weekday, target_hour, "
    "predicted, band_low, band_high, model_version, feature_hash, explanation_json) VALUES (?, 'soc_pct:charge_end','%',?,?,?,0,500,1,5,70.0,NULL,NULL,'t','f2',?)",
    (rid_c, t_end.isoformat(), t_end.isoformat(), t_end.isoformat(), json.dumps({"conditional_on_target_pct": 70.0})))
sc4.db.commit()
sc4.resolve(hist, cfg, nowx + timedelta(days=2))
stc = sc4.db.execute("SELECT status, score_note FROM forecasts WHERE kind='soc_pct:charge_end'").fetchone()
check("a plan-conditional SOC forecast whose plan was not followed is VOID_SCENARIO with a reason",
      stc["status"] == "VOID_SCENARIO" and "control decision" in stc["score_note"], str(dict(stc)))

section("expert weights: promotion needs sustained evidence")
n = WEIGHT_EVAL_DAYS
fast_err = [1.0, -1.0] * (n // 2)
slow_better = [0.5, -0.5] * (n // 2)
slow_worse = [1.2, -1.2] * (n // 2)
w0 = adaptive_weights({"fast": fast_err, "slow": slow_worse, "median14": slow_worse}, n)
check("default is the fast expert alone", w0 == PRIOR_WEIGHTS == {"fast": 1.0, "slow": 0.0, "median14": 0.0})
w1 = adaptive_weights({"fast": fast_err, "slow": slow_better, "median14": slow_worse}, n)
check("an expert that is clearly better over 28 days is promoted, capped",
      0 < w1["slow"] <= PROMOTE_MAX_WEIGHT and abs(sum(w1.values()) - 1.0) < 1e-9 and w1["median14"] == 0.0, str(w1))
w2 = adaptive_weights({"fast": fast_err[:10], "slow": slow_better[:10], "median14": slow_worse[:10]}, 10)
check("too few scored days -> no change", w2 == PRIOR_WEIGHTS)
spike = list(fast_err)
spike[3] = 40.0                     # one abnormal day in the FAST expert's errors
w3 = adaptive_weights({"fast": spike, "slow": [1.05, -1.05] * (n // 2), "median14": slow_worse}, n)
check("one abnormal day cannot demote the fast expert (winsorised errors)", w3 == PRIOR_WEIGHTS, str(w3))

section("recurring load signatures (neutral labels only)")
tzname = cfg.tz
base = int(datetime(2026, 9, 20, 0, tzinfo=UTC).timestamp())
samples = []
for day in range(8):
    for minute in range(24 * 60):
        t = base + day * 86400 + minute * 60
        w = 700.0
        if 600 <= minute < 606:        # ~2.8 kW for 6 min around 10:00, every day
            w += 2800.0
        if day % 2 == 0 and 1080 <= minute < 1110:   # ~1.9 kW for 30 min, every other day
            w += 1900.0
        samples.append((t, w))
cl = find_signatures(samples, tzname)
check("two recurring patterns found", len(cl) == 2, str([c.text() for c in cl]))
check("labels are neutral letters and no appliance is named", all(c.label in ("A", "B") and c.to_dict()["appliance"] is None for c in cl))
check("amplitude and duration class are right", any(abs(c.amplitude_w - 2800) < 300 and c.duration_class == "<8 min" for c in cl))
check("one-off events are not signatures", find_signatures([(base + i * 60, 700.0 + (3000.0 if 300 <= i < 310 else 0.0)) for i in range(1440)], tzname) == [])

section("authority separation (static)")
pkg = Path(__file__).resolve().parents[1]
forbidden_imports = {"socket", "requests", "urllib", "http", "subprocess", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho"}
forbidden_words = ("write_register", "modbus", "esphome", "supervisor_token", "api/services", "mqtt")
bad = []
for path in sorted(pkg.glob("*.py")):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module.split(".")[0]]
        for nme in names:
            if nme in forbidden_imports:
                bad.append((path.name, "import", nme))
    low = text.lower()
    for wd in forbidden_words:
        # the docstrings legitimately say "never talks to Modbus"; only flag code-like uses
        for i, line in enumerate(low.splitlines(), 1):
            s = line.strip()
            if wd in s and not s.startswith(("#", '"', "'")) and "never" not in s and "no " not in s and "not " not in s:
                bad.append((path.name, "word", wd, i))
check("the engine package imports no network/serial/process modules and contains no control vocabulary in code", not bad, str(bad[:5]))
check("the persisted mode is SHADOW everywhere", all(r["mode"] == "SHADOW" for r in sc.db.execute("SELECT mode FROM model_runs")))
check("report states it applies nothing", rep["applies_nothing"] is True and rep["mode"] == "SHADOW")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence scorecard / learning"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence scorecard / learning"} checks PASSED.")