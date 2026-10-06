"""Prediction scorecard: persist every forecast, score it when its horizon has passed, learn from the error.

SQLite (stdlib) in a file of its own - never in the Home Assistant recorder
database. Everything takes explicit timestamps; nothing reads the clock.

A forecast row carries what was predicted (p50 and a p10-p90 band), when and for
what horizon, which model/config/feature snapshot produced it and why
(explanation). Later `resolve()` fills in the actual, the signed error
(actual - predicted: positive = under-forecast), absolute and percentage error
and whether the actual fell inside the band. `metrics()` and `insights()` turn
those rows into MAE / RMSE / bias / interval coverage and plain-language
findings such as "I have been underestimating Wednesday mornings by 1.2 kWh".

SOC forecasts are conditional on the plan being followed. They are only scored
when the planned charge target was approximately reached; otherwise the row is
VOID_SCENARIO, so a controller decision cannot masquerade as a model error."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from . import stats
from .config import SiteConfig
from .history import History
from .timeutil import UTC, day_bounds, ts, zone

SCHEMA_VERSION = 1
SETTLE_HOURS = 2.0              # wait this long after a horizon ends before scoring (statistics lag)
BAND_NOMINAL = 0.8

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    issued_utc    TEXT NOT NULL,
    model_version TEXT NOT NULL,
    config_hash   TEXT NOT NULL,
    feature_hash  TEXT NOT NULL,
    features_json TEXT NOT NULL,
    status        TEXT NOT NULL,
    confidence    REAL,
    mode          TEXT NOT NULL DEFAULT 'SHADOW',
    UNIQUE (issued_utc, model_version, feature_hash)
);
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER NOT NULL REFERENCES model_runs(run_id),
    kind               TEXT NOT NULL,
    unit               TEXT NOT NULL,
    issued_utc         TEXT NOT NULL,
    horizon_start_utc  TEXT NOT NULL,
    horizon_end_utc    TEXT NOT NULL,
    horizon_minutes    INTEGER NOT NULL,
    lead_minutes       INTEGER NOT NULL,
    target_weekday     INTEGER NOT NULL,
    target_hour        INTEGER NOT NULL,
    predicted          REAL NOT NULL,
    band_low           REAL,
    band_high          REAL,
    band_nominal       REAL NOT NULL DEFAULT 0.8,
    confidence         REAL,
    model_version      TEXT NOT NULL,
    feature_hash       TEXT NOT NULL,
    explanation_json   TEXT,
    status             TEXT NOT NULL DEFAULT 'PENDING',
    actual             REAL,
    error              REAL,
    abs_error          REAL,
    pct_error          REAL,
    in_band            INTEGER,
    scored_utc         TEXT,
    score_note         TEXT,
    UNIQUE (run_id, kind, horizon_start_utc, horizon_end_utc)
);
CREATE INDEX IF NOT EXISTS ix_forecasts_status ON forecasts (status, horizon_end_utc);
CREATE INDEX IF NOT EXISTS ix_forecasts_kind ON forecasts (kind, target_weekday, target_hour);
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES model_runs(run_id),
    kind          TEXT NOT NULL,
    value         REAL,
    unit          TEXT,
    confidence    REAL,
    reasons_json  TEXT NOT NULL,
    valid_until_utc TEXT,
    mode          TEXT NOT NULL DEFAULT 'SHADOW',
    outcome_json  TEXT,
    UNIQUE (run_id, kind)
);
"""


# Two-sided Student-t critical values at p = 0.001, i.e. a Bonferroni-style allowance for the ~50 weekday x
# window-kind comparisons that insights() scans (0.05 / 50). Plain "3 sigma" is not enough with n of 6-10.
_T_CRIT_P001 = {2: 31.6, 3: 12.9, 4: 8.61, 5: 6.87, 6: 5.96, 7: 5.41, 8: 5.04, 9: 4.78, 10: 4.59, 12: 4.32, 15: 4.07,
                20: 3.85, 30: 3.65, 60: 3.46}


def t_crit(df: int) -> float:
    for k in sorted(_T_CRIT_P001):
        if df <= k:
            return _T_CRIT_P001[k]
    return 3.3


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


class Scorecard:
    def __init__(self, path: str = ":memory:", tz_name: str = "Europe/London"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.tz = zone(tz_name)
        self.db.executescript(DDL)
        self.db.execute("INSERT OR IGNORE INTO schema_meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.db.commit()

    # --- write ----------------------------------------------------------------------------------------------
    def record_run(self, report: dict) -> int:
        issued = datetime.fromisoformat(report["generated_for"])
        feats = json.dumps(report["features"], sort_keys=True, default=str)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO model_runs (issued_utc, model_version, config_hash, feature_hash, features_json, status, confidence, mode) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_iso(issued), report["model_version"], report["config_hash"], report["feature_hash"], feats, report["status"],
             report["confidence"]["overall"], report["mode"]))
        if cur.rowcount == 0:                       # identical run already recorded: idempotent
            row = self.db.execute("SELECT run_id FROM model_runs WHERE issued_utc=? AND model_version=? AND feature_hash=?",
                                  (_iso(issued), report["model_version"], report["feature_hash"])).fetchone()
            return int(row["run_id"])
        run_id = int(cur.lastrowid)
        for r in report["forecast_records"]:
            t0 = datetime.fromisoformat(r["horizon_start"])
            t1 = datetime.fromisoformat(r["horizon_end"])
            loc = t0.astimezone(self.tz)       # weekday/hour of the horizon START: a 'Wednesday day' starts on Wednesday
            self.db.execute(
                "INSERT OR IGNORE INTO forecasts (run_id, kind, unit, issued_utc, horizon_start_utc, horizon_end_utc, horizon_minutes, "
                "lead_minutes, target_weekday, target_hour, predicted, band_low, band_high, band_nominal, confidence, model_version, "
                "feature_hash, explanation_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, r["kind"], r["unit"], _iso(issued), _iso(t0), _iso(t1), int((t1 - t0).total_seconds() // 60),
                 int((t0 - issued).total_seconds() // 60), loc.weekday(), loc.hour, r["p50"], r["p10"], r["p90"], BAND_NOMINAL,
                 r["confidence"], report["model_version"], report["feature_hash"], json.dumps(r.get("explanation"), default=str)))
        rec = report.get("recommended") or {}
        ot = rec.get("overnight_target")
        if ot:
            self.db.execute(
                "INSERT OR IGNORE INTO recommendations (run_id, kind, value, unit, confidence, reasons_json, valid_until_utc, mode) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, "overnight_target_soc", ot["recommended_target_soc_pct"], "%", report["confidence"]["overall"],
                 json.dumps([r["text"] for r in rec.get("reasons", [])]), ot["window"][1], report["mode"]))
        se = rec.get("safe_export")
        if se is not None:
            self.db.execute(
                "INSERT OR IGNORE INTO recommendations (run_id, kind, value, unit, confidence, reasons_json, valid_until_utc, mode) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, "safe_export_kwh", se.get("kwh", 0.0), "kWh", report["confidence"]["overall"],
                 json.dumps([r["text"] for r in rec.get("reasons", []) if r["code"].startswith("EXPORT")]),
                 _iso(issued + timedelta(minutes=30)), report["mode"]))
        self.db.commit()
        return run_id

    # --- score ----------------------------------------------------------------------------------------------
    def resolve(self, history: History, cfg: SiteConfig, now: datetime) -> list[dict]:
        """Score every PENDING forecast whose horizon ended at least SETTLE_HOURS ago."""
        cutoff = _iso(now - timedelta(hours=SETTLE_HOURS))
        rows = self.db.execute("SELECT * FROM forecasts WHERE status='PENDING' AND horizon_end_utc <= ? ORDER BY forecast_id",
                               (cutoff,)).fetchall()
        done = []
        for r in rows:
            t0 = datetime.fromisoformat(r["horizon_start_utc"])
            t1 = datetime.fromisoformat(r["horizon_end_utc"])
            kind = r["kind"]
            actual, status, note = None, "VOID_NO_DATA", "no usable history for the horizon"
            if kind.startswith("load_kwh:"):
                actual = history.energy_scaled("load", t0, t1, 0.8)
            elif kind.startswith("pv_kwh:"):
                actual = history.energy_scaled("pv", t0, t1, 0.9)
            elif kind == "soc_pct:pre_window_hour":
                rec = history.get(ts(t0))
                actual = rec.soc_mean if rec is not None else None
            elif kind.startswith("soc_pct:"):
                actual = history.soc_at(t1, 1)
                expl = json.loads(r["explanation_json"] or "{}")
                target = expl.get("conditional_on_target_pct")
                if actual is not None and target is not None:
                    if abs(actual - target) > 3.0:
                        actual, status, note = None, "VOID_SCENARIO", (
                            f"the planned {target:.0f}% charge target was not what happened (SOC {actual:.0f}%); "
                            "that is a control decision, not a forecast error")
            if actual is not None:
                err = actual - r["predicted"]
                pct = (err / actual * 100.0) if abs(actual) > (0.5 if r["unit"] == "kWh" else 5.0) else None
                inb = None
                if r["band_low"] is not None and r["band_high"] is not None:
                    inb = 1 if r["band_low"] <= actual <= r["band_high"] else 0
                self.db.execute("UPDATE forecasts SET status='SCORED', actual=?, error=?, abs_error=?, pct_error=?, in_band=?, scored_utc=?, score_note=NULL WHERE forecast_id=?",
                                (actual, err, abs(err), pct, inb, _iso(now), r["forecast_id"]))
                done.append({"forecast_id": r["forecast_id"], "kind": kind, "predicted": r["predicted"], "actual": actual, "error": err})
            else:
                self.db.execute("UPDATE forecasts SET status=?, scored_utc=?, score_note=? WHERE forecast_id=?",
                                (status, _iso(now), note, r["forecast_id"]))
        self.db.commit()
        return done

    # --- read -----------------------------------------------------------------------------------------------
    def metrics(self, kind: str | None = None, since: datetime | None = None, group_by: str | None = None,
                min_lead_minutes: int | None = None) -> list[dict]:
        q = "SELECT * FROM forecasts WHERE status='SCORED'"
        args: list = []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if since:
            q += " AND horizon_end_utc >= ?"
            args.append(_iso(since))
        if min_lead_minutes is not None:
            q += " AND lead_minutes >= ?"
            args.append(min_lead_minutes)
        rows = self.db.execute(q, args).fetchall()
        groups: dict[tuple, list[sqlite3.Row]] = {}
        for r in rows:
            key = (r["kind"],) + ((r[group_by],) if group_by else ())
            groups.setdefault(key, []).append(r)
        out = []
        for key, rs in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            errs = [r["error"] for r in rs]
            band = [r["in_band"] for r in rs if r["in_band"] is not None]
            pct = [abs(r["pct_error"]) for r in rs if r["pct_error"] is not None]
            out.append({
                "kind": key[0], **({group_by: key[1]} if group_by else {}), "n": len(rs),
                "mae": stats.mae(errs), "rmse": stats.rmse(errs), "bias": sum(errs) / len(errs),
                "coverage": (sum(band) / len(band)) if band else None, "band_nominal": BAND_NOMINAL,
                "mape_pct": (sum(pct) / len(pct)) if pct else None, "unit": rs[0]["unit"]})
        return out

    def insights(self, now: datetime, weeks: int = 10, min_n: int = 6) -> list[str]:
        """Plain-language, statistically guarded findings about systematic bias by weekday."""
        since = _iso(now - timedelta(weeks=weeks))
        rows = self.db.execute("SELECT * FROM forecasts WHERE status='SCORED' AND horizon_end_utc >= ? AND kind LIKE 'load_kwh:%' "
                               "AND lead_minutes >= 60", (since,)).fetchall()
        groups: dict[tuple[str, int], list[float]] = {}
        for r in rows:
            groups.setdefault((r["kind"], r["target_weekday"]), []).append(r["error"])
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        label = {"morning": "mornings", "cheap_window": "cheap-window nights", "evening": "evenings",
                 "day": "whole days", "to_next_cheap": "days (to the next cheap window)", "overnight": "nights",
                 "to_useful_pv": "pre-solar hours"}
        out = []
        for (kind, wd), errs in sorted(groups.items()):
            if len(errs) < min_n:
                continue
            m = sum(errs) / len(errs)
            sd = stats.rmse([e - m for e in errs]) if len(errs) > 1 else 0.0
            se = sd / (len(errs) ** 0.5) if sd > 0 else float("inf")
            # This scans ~7 weekdays x ~7 window kinds, so the bar is a multiple-comparison-corrected t-test, not "2 sigma"
            if abs(m) >= t_crit(len(errs) - 1) * se and abs(m) >= 0.3:
                k = kind.split(":", 1)[1]
                out.append(f"I have been {'under' if m > 0 else 'over'}estimating {names[wd]} {label.get(k, k)} by "
                           f"{abs(m):.1f} kWh (n={len(errs)}).")
        return out

    def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.db.execute("SELECT status, COUNT(*) n FROM forecasts GROUP BY status")}

    def close(self) -> None:
        self.db.close()
