#!/usr/bin/env python3
"""Durable advice log (scorecard advice_log + tools/advice_export.py) on SYNTHETIC data:

  [1] fresh and old databases (no table) both work; an old file gains only the new table
  [2] one row per published change; an identical re-publish is not written twice; A,B,A writes three rows
  [3] the dump advice's intended duration is recorded; charge-target window, reserve and fallback flag are recorded
  [4] retention drops rows older than 400 days at write time
  [5] a write failure is isolated (returns 0, counted, nothing raised, no partial rows)
  [6] export round trip into ghost.parse_export's advice format; the export opens the file read-only
  [7] existing scorecard behaviour is unchanged (tables, row counts, schema version)
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import advisory_contract as ac  # noqa: E402
from intelligence.ghost import AdviceRecord, parse_export  # noqa: E402
from intelligence.scorecard import ADVICE_LOG_RETENTION_DAYS, DDL, SCHEMA_VERSION, Scorecard  # noqa: E402
from intelligence.tools import advice_export  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


T0 = datetime(2030, 3, 4, 20, 0, tzinfo=timezone.utc)


def payloads(gen: datetime, ct_target=80.0, dump_kwh=3.2, dump_ok=True, ct_status="OK", fallback=False) -> dict:
    """Published payloads in the shape of advisory_contract.to_entity_payloads (built with its own _view_advice)."""
    base = {"mode": "SHADOW", "applies_nothing": True, "contract_version": ac.CONTRACT_VERSION}
    until = gen + timedelta(hours=6)
    ct_sum = {"target_soc_pct": ct_target, "effective_reserve_pct": 40.0, "conservative_fallback": fallback,
              "window": [(T0 + timedelta(hours=2)).isoformat(), (T0 + timedelta(hours=6)).isoformat()]}
    dp_sum = {"dump_advisable": True, "stop_soc_pct": 55.0, "export_kwh": dump_kwh, "export_kw_avg": 3.2,
              "effective_reserve_pct": 40.0}
    ct = ac.ItemView("charge_target", ct_status, ct_target if ct_status == "OK" else None,
                     until if ct_status == "OK" else None, "MEDIUM", () if ct_status == "OK" else (("B1", "blocked"),), ("R1", "R2"), ct_sum if ct_status == "OK" else None)
    dp = ac.ItemView("dump_to_grid", "OK" if dump_ok else "BLOCKED", dump_kwh if dump_ok else None, until if dump_ok else None,
                     "LOW", () if dump_ok else (("B2", "blocked"),), ("D1",), dp_sum if dump_ok else None)
    out = {}
    for v in (ct, dp):
        rec = {**base, "kind": v.key, "status": v.status, "generated_at": gen.isoformat(), "unit": v.unit,
               "valid_until": v.valid_until.isoformat() if v.valid_until else None, "confidence": v.confidence,
               "blockers": [], "reason_codes": list(v.reason_codes)}
        out[ac.ENTITY_IDS[v.key]] = (v.value, rec, {"advice": ac._view_advice(v, v.status == "OK")})
    return out


def rows(db_path_or_sc, sql="SELECT * FROM advice_log ORDER BY advice_id"):
    return [dict(r) for r in db_path_or_sc.db.execute(sql)]


print("== [1] fresh and old databases")
sc = Scorecard(":memory:")
check("a fresh store has advice_log, empty", rows(sc) == [])
tmp = Path(tempfile.mkdtemp(prefix="advlog_"))
old = tmp / "old.db"
c = sqlite3.connect(old)
c.executescript(DDL)
c.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
c.commit()
tables_before = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
c.close()
check("the old file really has no advice_log", "advice_log" not in tables_before)
exp_old = advice_export.read_advice(str(old))
check("export of an old file (no table) is [] and does not create the table (read-only)", exp_old == []
      and "advice_log" not in {r[0] for r in sqlite3.connect(old).execute("SELECT name FROM sqlite_master")})
sc_old = Scorecard(str(old))
tables_after = {r[0] for r in sc_old.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("opening the old file only adds advice_log", tables_after - tables_before == {"advice_log"}
      and tables_before <= tables_after, str(tables_after ^ tables_before))
check("old file records advice", sc_old.record_advice(payloads(T0), dump_duration_min=30) == 2)

print("== [2] one row per change, idempotent")
sc = Scorecard(":memory:")
check("first publish writes both kinds", sc.record_advice(payloads(T0), dump_duration_min=30) == 2)
check("identical re-publish (later issue time) writes nothing", sc.record_advice(payloads(T0 + timedelta(minutes=10)),
                                                                                  dump_duration_min=30) == 0)
check("still two rows", len(rows(sc)) == 2)
sc5 = Scorecard(":memory:")
sc5.record_advice(payloads(T0), dump_duration_min=30)
check("same dump advice inside its window (T0+29m) is skipped, charge target too",
      sc5.record_advice(payloads(T0 + timedelta(minutes=29)), dump_duration_min=30) == 0)
check("same dump advice after its window lapsed (T0+31m) is written; charge target (valid 6 h) still skipped",
      sc5.record_advice(payloads(T0 + timedelta(minutes=31)), dump_duration_min=30) == 1
      and [r["kind"] for r in rows(sc5)][-1] == "dump_to_grid")
check("same advice one day later: both written (events, not duplicates)",
      sc5.record_advice(payloads(T0 + timedelta(days=1)), dump_duration_min=30) == 2)
sc6 = Scorecard(":memory:")
sc6.record_advice(payloads(T0), dump_duration_min=30)
check("charge target past its valid_until (T0+7h) is written again", sc6.record_advice(
    payloads(T0 + timedelta(hours=7)), dump_duration_min=30) == 2)
sc7 = Scorecard(":memory:")
sc7.record_advice(payloads(T0))
check("dump without a duration: identical re-publish within valid_until is skipped",
      sc7.record_advice(payloads(T0 + timedelta(minutes=10))) == 0 and len(rows(sc7)) == 2)
check("... and written again once valid_until (6 h) has passed", sc7.record_advice(payloads(T0 + timedelta(hours=7))) == 2)
check("a change writes one row for that kind", sc.record_advice(payloads(T0 + timedelta(minutes=20), ct_target=90.0),
                                                                dump_duration_min=30) == 1)
check("changing back writes again (A,B,A is three rows)", sc.record_advice(payloads(T0 + timedelta(minutes=25)),
                                                                          dump_duration_min=30) == 1
      and len([r for r in rows(sc) if r["kind"] == "charge_target"]) == 3)
check("a blocked status is a change and carries no numbers", sc.record_advice(
    payloads(T0 + timedelta(minutes=40), ct_status="BLOCKED", dump_ok=False), dump_duration_min=30) == 2
      and rows(sc)[-1]["target_soc_pct"] is None and rows(sc)[-1]["status"] == "BLOCKED")
check("run id and hash are stored", sc.record_advice(payloads(T0 + timedelta(hours=1), ct_target=70.0), run_id=7) >= 1
      and rows(sc)[-1]["run_id"] == 7 and len(rows(sc)[-1]["content_hash"]) == 24)

print("== [3] recorded fields")
sc = Scorecard(":memory:")
sc.record_advice(payloads(T0, fallback=True), dump_duration_min=45)
ct = [r for r in rows(sc) if r["kind"] == "charge_target"][0]
dp = [r for r in rows(sc) if r["kind"] == "dump_to_grid"][0]
check("charge target: window, reserve, fallback, valid_until, reasons", ct["window_start_utc"] == (T0 + timedelta(hours=2)).isoformat()
      and ct["window_end_utc"] == (T0 + timedelta(hours=6)).isoformat() and ct["effective_reserve_pct"] == 40.0
      and ct["conservative_fallback"] == 1 and ct["valid_until_utc"] == (T0 + timedelta(hours=6)).isoformat()
      and json.loads(ct["reasons_json"]) == ["R1", "R2"] and ct["target_soc_pct"] == 80.0)
check("dump: stop SOC, kWh, kW, advisable and the intended duration", dp["stop_soc_pct"] == 55.0 and dp["export_kwh"] == 3.2
      and dp["export_kw_avg"] == 3.2 and dp["dump_advisable"] == 1 and dp["duration_min"] == 45.0)
check("dump window = issue time + duration", dp["window_start_utc"] == T0.isoformat()
      and dp["window_end_utc"] == (T0 + timedelta(minutes=45)).isoformat())
sc2 = Scorecard(":memory:")
sc2.record_advice(payloads(T0))
dp2 = [r for r in rows(sc2) if r["kind"] == "dump_to_grid"][0]
check("no duration supplied: duration and window stay NULL", dp2["duration_min"] is None and dp2["window_end_utc"] is None)

print("== [4] retention")
sc = Scorecard(":memory:")
sc.record_advice(payloads(T0 - timedelta(days=ADVICE_LOG_RETENTION_DAYS + 5)))
check("an old row is stored when it is the newest", len(rows(sc)) == 2)
sc.record_advice(payloads(T0, ct_target=61.0, dump_kwh=1.0))
check("rows older than 400 days are dropped at the next write", len(rows(sc)) == 2
      and all(r["issued_utc"] >= (T0 - timedelta(days=ADVICE_LOG_RETENTION_DAYS)).isoformat() for r in rows(sc)))
sc.record_advice(payloads(T0 - timedelta(days=ADVICE_LOG_RETENTION_DAYS - 5), ct_target=62.0))
check("a row 395 days old is kept", any(r["target_soc_pct"] == 62.0 for r in rows(sc)))

print("== [5] write failure is isolated")
sc = Scorecard(":memory:")
sc.record_advice(payloads(T0), dump_duration_min=30)
n = len(rows(sc))
pay = payloads(T0 + timedelta(hours=1), ct_target=71.0)
snapshot = json.dumps(pay, sort_keys=True, default=str)
sc.db.execute("DROP TABLE advice_log")
res, raised = None, False
try:
    res = sc.record_advice(pay, dump_duration_min=30)
except Exception:
    raised = True
check("a broken table: nothing raised, 0 written, failure counted", not raised and res == 0 and sc.advice_write_failures == 1)
check("the published payloads are untouched", json.dumps(pay, sort_keys=True, default=str) == snapshot)
bad = {"x": ("s", {"kind": "charge_target", "status": "OK", "generated_at": "not a time"}, {})}
check("malformed input is also swallowed and counted", Scorecard(":memory:").record_advice(bad) == 0)
sc3 = Scorecard(":memory:")
sc3.record_advice(bad)
check("the counter increments", sc3.advice_write_failures == 1)
sc4 = Scorecard(":memory:")
sc4.db.execute("CREATE TRIGGER boom BEFORE INSERT ON advice_log WHEN NEW.kind='dump_to_grid' BEGIN SELECT RAISE(ABORT,'boom'); END")
check("a failure on the second row rolls the first back (no partial rows)", sc4.record_advice(payloads(T0)) == 0
      and rows(sc4) == [] and sc4.advice_write_failures == 1)
check("the scorecard stays usable after a failure", sc4.db.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 0)

print("== [6] export round trip")
db = tmp / "sc.db"
sc = Scorecard(str(db))
sc.record_advice(payloads(T0), dump_duration_min=30)
sc.record_advice(payloads(T0 + timedelta(days=1), ct_target=65.0, dump_kwh=2.0), dump_duration_min=30)
sc.record_advice(payloads(T0 + timedelta(days=2), ct_status="BLOCKED", dump_ok=False))
sc.db.close()
out = io.StringIO()
with redirect_stdout(out):
    rc = advice_export.main([str(db), "--from", "2030-03-04", "--to", "2030-03-06T00:00:00Z"])
data = json.loads(out.getvalue())
check("CLI exit 0 and the time range excludes the third day (4 rows)", rc == 0 and len(data) == 4, str(len(data)))
exp = {"format": "ecco-intel-ghost-export/1", "advice": data}
adv = [AdviceRecord.from_dict(a) for a in data]
check("every row builds an AdviceRecord", len(adv) == 4 and {a.kind for a in adv} == {"charge_target", "dump_to_grid"})
d1 = [a for a in adv if a.kind == "dump_to_grid"][0]
check("dump record: stop, kWh, kW, window", d1.target_soc_pct == 55.0 and d1.export_kwh == 3.2 and d1.export_kw == 3.2
      and d1.window_end - d1.window_start == timedelta(minutes=30) and d1.dump_advisable)
c1 = [a for a in adv if a.kind == "charge_target"][0]
check("charge record: target, reserve, window", c1.target_soc_pct == 80.0 and c1.effective_reserve_pct == 40.0
      and c1.window_start == T0 + timedelta(hours=2))
import inspect  # noqa: E402
check("the AdviceRecord field names match ghost.parse_export's advice parsing",
      set(data[0]) <= set(AdviceRecord.__dataclass_fields__) and "advice" in inspect.getsource(parse_export))
kind_only = advice_export.read_advice(str(db), kind="dump_to_grid")
check("kind filter and open range work", {r["kind"] for r in kind_only} == {"dump_to_grid"} and len(kind_only) == 3)
before = db.read_bytes()
advice_export.read_advice(str(db))
check("the export does not change the file", db.read_bytes() == before)
try:
    ro = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    ro.execute("INSERT INTO schema_meta VALUES ('x','y')")
    wrote = True
except sqlite3.OperationalError:
    wrote = False
check("a mode=ro connection really refuses writes", not wrote)
err = io.StringIO()
import contextlib  # noqa: E402
with contextlib.redirect_stderr(err):
    rc = advice_export.main([str(tmp / "missing.db")])
check("a missing database exits 2 and creates no file", rc == 2 and not (tmp / "missing.db").exists())

print("== [7] existing scorecard behaviour unchanged")
sc = Scorecard(":memory:")
names = {r[0] for r in sc.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("the four original tables are all there plus advice_log", {"schema_meta", "model_runs", "forecasts", "recommendations",
                                                                  "advice_log"} <= names)
check("schema version unchanged", sc.db.execute("SELECT value FROM schema_meta").fetchone()[0] == str(SCHEMA_VERSION) == "1")
sc.record_advice(payloads(T0))
check("recording advice touches no existing table", all(sc.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
                                                         for t in ("model_runs", "forecasts", "recommendations")))
check("opening twice is idempotent", Scorecard(str(db)).db.execute("SELECT COUNT(*) FROM advice_log").fetchone()[0] == 6)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence advice log:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All intelligence advice log checks PASSED.")
