#!/usr/bin/env python3
"""Durable advice log (scorecard advice_log + tools/advice_export.py) on SYNTHETIC data:

  [1] fresh and old databases (no table) both work; an old file gains only the new table
  [2] one row per published change; an identical re-publish is not written twice; A,B,A writes three rows
  [3] the dump advice's intended duration is recorded; charge-target window, reserve and fallback flag are recorded
  [4] retention drops rows older than 400 days at write time
  [5] a write failure is isolated (returns 0, counted, nothing raised, no partial rows)
  [6] export round trip into ghost.parse_export's advice format; the export opens the file read-only
  [7] existing scorecard behaviour is unchanged (tables, row counts, schema version)
  [8] the advice table cannot break the scorecard (review finding G1): opening the store never touches advice_log (the table is
      created by the advice WRITE path, inside its own try); an incompatible pre-existing table, a DDL that raises and a write
      that raises each leave the existing scorecard paths (open, record_run, counts, metrics) working; reading tolerates a missing
      or incompatible table
  [9] one row per slot cycle (the engine's validity, hourly slots: N identical advices are N rows, in the table, the export and the
      read API: no deduplication) and the age bound of the retention (a running check on the real 400 days, also after a failed
      write; the only insert path)
  [10] a verified write: the rows just written are read back by their own ids after the commit (found: verified; not found, or
      the read-back itself fails: unverified, never a failure of the caller; nothing to write: neutral)
  [11] the incident table (advice_incident): created only when an incident is persisted (never when the scorecard is opened or an
      advice row is written), closed incidents only, bounded to the newest ADVICE_INCIDENTS_KEPT, idempotent, its failures isolated
      (a table of another shape, a DDL that raises), only a class name as a reason, readable read-only (library and CLI)
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
import intelligence.scorecard as scmod  # noqa: E402
from intelligence.scorecard import ADVICE_LOG_DDL, ADVICE_LOG_RETENTION_DAYS, DDL, SCHEMA_VERSION, Scorecard  # noqa: E402
from intelligence.tools import advice_export  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


T0 = datetime(2030, 3, 4, 20, 0, tzinfo=timezone.utc)


def payloads(gen: datetime, ct_target=80.0, dump_kwh=3.2, dump_ok=True, ct_status="OK", fallback=False, valid_s=None) -> dict:
    """Published payloads in the shape of advisory_contract.to_entity_payloads (built with its own _view_advice). The validity
    is 6 h unless `valid_s` (seconds) is given: the engine's own is at most 900 s."""
    base = {"mode": "SHADOW", "applies_nothing": True, "contract_version": ac.CONTRACT_VERSION}
    until = gen + (timedelta(hours=6) if valid_s is None else timedelta(seconds=valid_s))
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


def has_table(db, name="advice_log") -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


class guard:
    """Run a block of checks; an exception inside it is a FAIL of the named check, not a crash of the whole suite."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb) -> bool:
        if et is not None and issubclass(et, Exception):
            check(self.name, False, f"raised {et.__name__}: {str(ev)[:160]}")
            return True
        return False


print("== [1] fresh and old databases")
sc = Scorecard(":memory:")
check("a fresh store has NO advice_log yet: opening creates nothing for the advice log (G1), and reading advice gives []",
      not has_table(sc.db) and sc.advice_records() == [])
sc.record_advice(payloads(T0))
check("the first advice write creates the table (and only then)", has_table(sc.db) and len(rows(sc)) == 2)
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
check("opening the old file adds nothing (G1: the advice table is not created by opening)", tables_after == tables_before,
      str(tables_after ^ tables_before))
check("old file records advice", sc_old.record_advice(payloads(T0), dump_duration_min=30) == 2)
tables_rec = {r[0] for r in sc_old.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("the first advice write only adds advice_log", tables_rec - tables_before == {"advice_log"} and tables_before <= tables_rec,
      str(tables_rec ^ tables_before))

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
sc.db.execute("CREATE TABLE advice_log (x INTEGER)")        # a table the advice write cannot use (not the DDL's shape)
res, raised = None, False
try:
    res = sc.record_advice(pay, dump_duration_min=30)
except Exception:
    raised = True
check("a broken table: nothing raised, 0 written, failure counted", not raised and res == 0 and sc.advice_write_failures == 1)
check("the published payloads are untouched", json.dumps(pay, sort_keys=True, default=str) == snapshot)
sc_d = Scorecard(":memory:")
sc_d.record_advice(payloads(T0))
sc_d.db.execute("DROP TABLE advice_log")
check("a dropped table is simply created again by the next advice write (nothing counted)",
      sc_d.record_advice(payloads(T0 + timedelta(hours=1))) == 2 and sc_d.advice_write_failures == 0 and len(rows(sc_d)) == 2)
bad = {"x": ("s", {"kind": "charge_target", "status": "OK", "generated_at": "not a time"}, {})}
check("malformed input is also swallowed and counted", Scorecard(":memory:").record_advice(bad) == 0)
sc3 = Scorecard(":memory:")
sc3.record_advice(bad)
check("the counter increments", sc3.advice_write_failures == 1)
sc4 = Scorecard(":memory:")
sc4.db.executescript(ADVICE_LOG_DDL)                         # the table the trigger needs (the first write would create it)
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
check("the four original tables are all there; advice_log only after the first advice write",
      {"schema_meta", "model_runs", "forecasts", "recommendations"} <= names and "advice_log" not in names, str(names))
check("schema version unchanged", sc.db.execute("SELECT value FROM schema_meta").fetchone()[0] == str(SCHEMA_VERSION) == "1")
sc.record_advice(payloads(T0))
check("recording advice touches no existing table", all(sc.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
                                                         for t in ("model_runs", "forecasts", "recommendations")))
check("opening twice is idempotent", Scorecard(str(db)).db.execute("SELECT COUNT(*) FROM advice_log").fetchone()[0] == 6)

print("== [8] the advice table cannot break the scorecard (G1 fault injection)")


def tried(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the test records what happened
        return f"raised {type(exc).__name__}"


def mini_report(issued: datetime) -> dict:
    recs = []
    for k in range(2):
        t0 = issued + timedelta(hours=1 + 24 * k)
        recs.append({"kind": "load_kwh:day", "unit": "kWh", "horizon_start": t0.isoformat(), "horizon_end": (t0 + timedelta(hours=24)).isoformat(),
                     "p50": 10.0, "p10": 8.0, "p90": 12.0, "confidence": 0.6, "explanation": {"synthetic": True}})
    return {"generated_for": issued.isoformat(), "features": {"synthetic": 1}, "model_version": "intel-test", "config_hash": "test",
            "feature_hash": "f1", "status": "OK", "confidence": {"overall": 0.6}, "mode": "SHADOW", "forecast_records": recs}


def old_paths(sc) -> str:
    """The scorecard's own paths: record_run, counts, metrics. 'ok' or what went wrong."""
    try:
        run_id = sc.record_run(mini_report(T0))
        if not isinstance(run_id, int) or sc.counts() != {"PENDING": 2} or sc.metrics() != []:
            return f"unexpected {run_id} {sc.counts()}"
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}"


def opened(path):
    try:
        return Scorecard(path), "ok"
    except Exception as exc:  # noqa: BLE001
        return None, f"raised {type(exc).__name__}"


# a. an advice_log table that already exists with other columns (a foreign or older shape)
inc = tmp / "incompatible.db"
c = sqlite3.connect(inc)
c.executescript(DDL)
c.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
c.execute("CREATE TABLE advice_log (foo TEXT, bar INTEGER)")
c.execute("INSERT INTO advice_log VALUES ('x', 1)")
c.commit()
c.close()
sc_i, why = opened(str(inc))
check("an incompatible pre-existing advice_log does not stop the scorecard from opening", sc_i is not None, why)
if sc_i is not None:
    check("... the existing scorecard paths (record_run, counts, metrics) still work on it", old_paths(sc_i) == "ok", old_paths(sc_i))
    n0 = sc_i.advice_write_failures
    res = tried(lambda: sc_i.record_advice(payloads(T0), dump_duration_min=30))
    check("... an advice write on it fails alone: 0 rows, counted, nothing raised", res == 0 and sc_i.advice_write_failures == n0 + 1, str(res))
    check("... the odd table is left exactly as it was (its row and its columns)",
          [tuple(r) for r in sc_i.db.execute("SELECT * FROM advice_log")] == [("x", 1)]
          and [r[1] for r in sc_i.db.execute("PRAGMA table_info(advice_log)")] == ["foo", "bar"])
    check("... reading advice from it gives no rows, not an exception", tried(lambda: sc_i.advice_records()) == [])
    check("... and a clear status says why", tried(lambda: sc_i.advice_log_status()) == "INCOMPATIBLE",
          str(tried(lambda: sc_i.advice_log_status())))
    sc_i.db.close()

# b. a DDL that raises (a failing CREATE INDEX or a full disk at the first create look the same to the opener)
real_ddl = scmod.ADVICE_LOG_DDL
scmod.ADVICE_LOG_DDL = "CREATE TABLE advice_log (;"
try:
    sc_b, why = opened(":memory:")
    check("a DDL that raises does not stop the scorecard from opening", sc_b is not None, why)
    if sc_b is not None:
        check("... the existing scorecard paths still work", old_paths(sc_b) == "ok", old_paths(sc_b))
        res = tried(lambda: sc_b.record_advice(payloads(T0)))
        check("... the advice write fails alone: 0 rows, counted, nothing raised", res == 0 and sc_b.advice_write_failures == 1, str(res))
        sc_b.db.close()
finally:
    scmod.ADVICE_LOG_DDL = real_ddl

# c. a write that raises (a trigger): the old paths are unaffected
sc_c = Scorecard(":memory:")
sc_c.db.executescript(ADVICE_LOG_DDL)
sc_c.db.execute("CREATE TRIGGER boom_all BEFORE INSERT ON advice_log BEGIN SELECT RAISE(ABORT,'boom'); END")
check("a write that raises: 0 rows, counted, nothing raised, and the existing scorecard paths still work",
      tried(lambda: sc_c.record_advice(payloads(T0))) == 0 and sc_c.advice_write_failures == 1 and old_paths(sc_c) == "ok")

# d. reading tolerates a missing table; the status names the three states
sc_m = Scorecard(":memory:")
check("reading a store with no advice table: no rows and the status MISSING",
      tried(lambda: sc_m.advice_records()) == [] and tried(lambda: sc_m.advice_log_status()) == "MISSING",
      f"{tried(lambda: sc_m.advice_records())} {tried(lambda: sc_m.advice_log_status())}")
sc_m.record_advice(payloads(T0))
check("... and OK once the advice write has created it", tried(lambda: sc_m.advice_log_status()) == "OK")

print("== [9] R1: one row per slot cycle (no deduplication) and the age bound of the retention")
from intelligence.daily_plan import PROPOSED_ADVICE_VALIDITY_S  # noqa: E402 - the engine's own validity ceiling

ADVICE_KINDS = ("charge_target", "dump_to_grid")
SLOTS_A_DAY = 25                   # 24 full hours and the 21:30 slot (the runtime's due_slot); 26 on the day the clocks go back


def n_rows(scx) -> int:
    return scx.db.execute("SELECT COUNT(*) FROM advice_log").fetchone()[0]


with guard("[9] N slot cycles of identical advice"):
    N = 30
    r1 = tmp / "r1.db"
    sc9 = Scorecard(str(r1))
    for k in range(N):
        sc9.record_advice(payloads(T0 + timedelta(hours=k), valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    per = {kd: [r for r in rows(sc9) if r["kind"] == kd] for kd in ADVICE_KINDS}
    check("the engine's validity ceiling is at most 900 s, shorter than the hourly slot spacing",
          0 < PROPOSED_ADVICE_VALIDITY_S <= 900.0, str(PROPOSED_ADVICE_VALIDITY_S))
    check(f"{N} slot cycles with the identical advice give {N} rows of each kind (nothing is deduplicated away)",
          all(len(v) == N for v in per.values()), str({k: len(v) for k, v in per.items()}))
    check("... and they are identical in content (one content hash per kind), so a deduplication on content would have dropped them",
          all(len({r["content_hash"] for r in v}) == 1 for v in per.values()))
    exported = advice_export.read_advice(str(r1))
    check("... the export returns every one of them", len(exported) == 2 * N and len({e["advice_id"] for e in exported}) == 2 * N,
          str(len(exported)))
    check("... and so does Scorecard.advice_records", len(sc9.advice_records()) == 2 * N)
    sc9b = Scorecard(":memory:")
    for k in range(N):
        sc9b.record_advice(payloads(T0 + timedelta(hours=k), valid_s=3599), dump_duration_min=30)
    check("even a validity of 3599 s (just under the slot spacing) keeps one row per slot cycle", n_rows(sc9b) == 2 * N, str(n_rows(sc9b)))
    sc9c = Scorecard(":memory:")
    sc9c.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    check("the one skip that remains: the same advice published again inside the previous row's own validity (within one slot) is "
          "not a second row",
          sc9c.record_advice(payloads(T0 + timedelta(minutes=5), valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30) == 0
          and n_rows(sc9c) == 2)
    sc9.db.close()

with guard("[9] the retention is an age bound that runs at every write"):
    check("the retention is 400 days of the advice's own issue time", scmod.ADVICE_LOG_RETENTION_DAYS == ADVICE_LOG_RETENTION_DAYS == 400)
    real_days = scmod.ADVICE_LOG_RETENTION_DAYS
    scmod.ADVICE_LOG_RETENTION_DAYS = 20                    # the mechanism on a short bound, so a month of slot cycles shows it
    try:
        scr = Scorecard(":memory:")
        issued, peak = [], 0
        for d in range(32):
            for k in range(SLOTS_A_DAY):
                g = T0 + timedelta(days=d, minutes=57 * k)
                scr.record_advice(payloads(g, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
                issued.append(g)
                peak = max(peak, n_rows(scr))
    finally:
        scmod.ADVICE_LOG_RETENTION_DAYS = real_days
    cut = (issued[-1] - timedelta(days=20)).isoformat()
    want = 2 * sum(1 for g in issued if g.isoformat() >= cut)
    check("on a 20-day bound, 32 days of 25 slot cycles keep exactly the rows of the last 20 days", n_rows(scr) == want,
          f"{n_rows(scr)} {want}")
    check("... the count never exceeded 2 kinds x 26 slot cycles x the bound in days", peak <= 2 * 26 * 20, str(peak))
    check("... and no kept row is older than the bound",
          scr.db.execute("SELECT COUNT(*) FROM advice_log WHERE issued_utc < ?", (cut,)).fetchone()[0] == 0)

with guard("[9] the real 400-day bound, also after a failed write"):
    scp = Scorecard(":memory:")
    scp.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)       # creates the table
    bulk = []
    for d in range(ADVICE_LOG_RETENTION_DAYS):
        for k in range(SLOTS_A_DAY):
            g = (T0 + timedelta(days=d, minutes=57 * k)).isoformat()
            bulk.extend([("charge_target", "OK", g, "[]", "x"), ("dump_to_grid", "OK", g, "[]", "x")])
    scp.db.executemany("INSERT INTO advice_log (kind, status, issued_utc, reasons_json, content_hash) VALUES (?,?,?,?,?)", bulk)
    scp.db.commit()
    check("non-vacuity: 400 days of 25 slot cycles of 2 kinds is 20 000 rows (plus the first write's two)",
          n_rows(scp) == 2 * SLOTS_A_DAY * ADVICE_LOG_RETENTION_DAYS + 2, str(n_rows(scp)))
    scp.db.execute("CREATE TRIGGER boom BEFORE INSERT ON advice_log BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    scp.db.commit()
    before = n_rows(scp)
    t_fail = T0 + timedelta(days=ADVICE_LOG_RETENTION_DAYS + 3)
    scp.record_advice(payloads(t_fail, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    check("a failed write adds nothing and prunes nothing (the whole write is rolled back) and is counted",
          n_rows(scp) == before and scp.advice_write_failures == 1, f"{n_rows(scp)} {before}")
    scp.db.execute("DROP TRIGGER boom")
    scp.db.commit()
    t_ok = T0 + timedelta(days=ADVICE_LOG_RETENTION_DAYS + 5)
    check("the next good write succeeds", scp.record_advice(payloads(t_ok, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30) == 2)
    cut2 = (t_ok - timedelta(days=ADVICE_LOG_RETENTION_DAYS)).isoformat()
    check("... and prunes by its own issue time: nothing older than 400 days of it remains",
          scp.db.execute("SELECT COUNT(*) FROM advice_log WHERE issued_utc < ?", (cut2,)).fetchone()[0] == 0)
    check("... so the table is within 2 kinds x 26 slot cycles x 400 days", n_rows(scp) <= 2 * 26 * ADVICE_LOG_RETENTION_DAYS,
          str(n_rows(scp)))
    scp.db.close()

with guard("[9] the only insert path"):
    srcs = {}
    for base_dir in (ROOT / "intelligence", ROOT / "custom_components" / "ecco_intelligence"):
        for p in base_dir.rglob("*.py"):
            if "tests" not in p.relative_to(ROOT).parts:
                srcs[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8")
    inserts = sorted(k for k, t in srcs.items() if "INSERT INTO advice_log" in t)
    callers = sorted(k for k, t in srcs.items() if ".record_advice(" in t)
    check("the only INSERT into advice_log is in intelligence/scorecard.py (Scorecard.record_advice)",
          inserts == ["intelligence/scorecard.py"], str(inserts))
    check("... and the only caller of record_advice outside the scorecard is the runtime store's advice step",
          callers == ["custom_components/ecco_intelligence/runtime/store.py"], str(callers))

print("== [10] a verified write: the rows just written are read back by their own ids after the commit")
with guard("[10] verified, neutral"):
    scv = Scorecard(":memory:")
    nv = scv.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    check("rows written and found again by their ids: advice_last_verified is True and the two ids are kept",
          nv == 2 and scv.advice_last_verified is True and len(scv.advice_last_ids) == 2, f"{nv} {scv.advice_last_verified}")
    check("... nothing is counted as failed or unverified", scv.advice_write_failures == 0 and scv.advice_unverified_writes == 0)
    check("... the ids are the rows' own", sorted(scv.advice_last_ids) == sorted(r["advice_id"] for r in rows(scv)))
    n0 = scv.record_advice(payloads(T0 + timedelta(minutes=5), valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    check("a call that wrote nothing (the same advice inside its validity) is neutral: nothing to verify",
          n0 == 0 and scv.advice_last_verified is None and scv.advice_last_ids == [], f"{n0} {scv.advice_last_verified}")
    check("an empty published set is neutral too", scv.record_advice({}) == 0 and scv.advice_last_verified is None)
    check("a later write is verified again and the neutral call did not count anything",
          scv.record_advice(payloads(T0 + timedelta(hours=1), valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30) == 2
          and scv.advice_last_verified is True and scv.advice_write_failures == 0 and scv.advice_unverified_writes == 0)

with guard("[10] a write that returns without an error but whose rows are not there"):
    scg = Scorecard(":memory:")
    scg.db.executescript(ADVICE_LOG_DDL)
    scg.db.execute("CREATE TRIGGER gone AFTER INSERT ON advice_log BEGIN DELETE FROM advice_log WHERE advice_id = NEW.advice_id; END")
    scg.db.commit()
    rg = tried(lambda: scg.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30))
    check("the write raises nothing, yet the rows are not found again: UNVERIFIED (not verified, and not a failure of the write)",
          rg == 2 and scg.advice_last_verified is False and scg.advice_unverified_writes == 1 and scg.advice_write_failures == 0,
          f"{rg} {scg.advice_last_verified} {scg.advice_unverified_writes} {scg.advice_write_failures}")
    check("... with a fixed code as the reason (an identifier, no message)", scg.advice_last_error == "AdviceReadBackMissing",
          str(scg.advice_last_error))

with guard("[10] the read-back itself fails"):
    scf = Scorecard(":memory:")
    real_rb = getattr(Scorecard, "_read_back_advice", None)

    def rb_boom(self, ids):
        raise sqlite3.OperationalError("SECRET-readback-message /private/path")
    Scorecard._read_back_advice = rb_boom
    try:
        rf = tried(lambda: scf.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30))
    finally:
        if real_rb is not None:
            Scorecard._read_back_advice = real_rb
        else:
            del Scorecard._read_back_advice
    check("a failing read-back is unverified, nothing is raised, the rows stay, and only the class name is kept",
          rf == 2 and scf.advice_last_verified is False and scf.advice_last_error == "OperationalError"
          and "SECRET" not in str(scf.advice_last_error) and n_rows(scf) == 2, f"{rf} {scf.advice_last_verified} {scf.advice_last_error}")
    check("... and it counts as unverified, not as a failed write", scf.advice_unverified_writes == 1 and scf.advice_write_failures == 0)

with guard("[10] a failed write is not verified"):
    scx = Scorecard(":memory:")
    scx.db.executescript(ADVICE_LOG_DDL)
    scx.db.execute("CREATE TRIGGER boom BEFORE INSERT ON advice_log BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    scx.db.commit()
    check("a write that raises: 0 rows, counted, advice_last_verified is False and the reason is the class name",
          scx.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S)) == 0 and scx.advice_write_failures == 1
          and scx.advice_last_verified is False and scx.advice_last_ids == [] and scx.advice_unverified_writes == 0
          and scx.advice_last_error == "IntegrityError", f"{scx.advice_last_verified} {scx.advice_last_error}")

print("== [11] the incident table")
KEPT = getattr(scmod, "ADVICE_INCIDENTS_KEPT", None)
SECRET = "boom: SECRET-1234 /private/path sensor.test_secret_entity"


def inc(n: int, reason: str = "OperationalError", closed: bool = True) -> dict:
    t = T0 + timedelta(days=n)
    return {"first_failed_utc": t.isoformat(), "last_failed_utc": (t + timedelta(hours=2)).isoformat(), "failed_count": 3,
            "missed_slots": 3, "reason": reason, "first_reason": reason, "first_issued_utc": t.isoformat(),
            "last_issued_utc": (t + timedelta(hours=2)).isoformat(),
            "recovered_utc": (t + timedelta(hours=3)).isoformat() if closed else None, "rows_since": 2}


with guard("[11] lazily created, closed incidents only"):
    check("the bound is a small named constant", isinstance(KEPT, int) and 1 <= KEPT <= 50, str(KEPT))
    sci = Scorecard(":memory:")
    check("opening the scorecard creates no incident table, and reading gives no rows",
          not has_table(sci.db, "advice_incident") and sci.advice_incidents() == [])
    sci.record_advice(payloads(T0, valid_s=PROPOSED_ADVICE_VALIDITY_S), dump_duration_min=30)
    check("an advice write creates the advice table and still no incident table", has_table(sci.db) and not has_table(sci.db, "advice_incident"))
    meta0 = [tuple(r) for r in sci.db.execute("SELECT * FROM schema_meta ORDER BY key")]
    adv0 = [tuple(r) for r in sci.db.execute("SELECT * FROM advice_log ORDER BY advice_id")]
    res = sci.persist_advice_incidents([inc(1), inc(2, closed=False)], T0 + timedelta(days=3))
    check("persisting writes the closed incident and creates the table only now; an open incident is neither written nor reported",
          res.get("persisted") == [inc(1)["first_failed_utc"]] and res.get("error") is None and has_table(sci.db, "advice_incident")
          and sci.db.execute("SELECT COUNT(*) FROM advice_incident").fetchone()[0] == 1, str(res))
    check("... the old tables, schema_meta and the advice rows are exactly as they were",
          [tuple(r) for r in sci.db.execute("SELECT * FROM schema_meta ORDER BY key")] == meta0
          and [tuple(r) for r in sci.db.execute("SELECT * FROM advice_log ORDER BY advice_id")] == adv0
          and all(sci.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in ("model_runs", "forecasts", "recommendations")))
    got = sci.advice_incidents()
    check("... it reads back as stored (counts, class name, times) with the time it was recorded",
          len(got) == 1 and {k: got[0][k] for k in inc(1)} == inc(1) and got[0].get("recorded_utc") == (T0 + timedelta(days=3)).isoformat(),
          str(got))
    sci.persist_advice_incidents([inc(1)], T0 + timedelta(days=4))
    check("persisting the same incident again replaces it (one row)", sci.db.execute("SELECT COUNT(*) FROM advice_incident").fetchone()[0] == 1)

with guard("[11] a file that never had the table"):
    old2 = tmp / "old2.db"
    c2 = sqlite3.connect(old2)
    c2.executescript(DDL)
    c2.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
    c2.commit()
    t_before = {r[0] for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c2.close()
    sco = Scorecard(str(old2))
    t_open = {r[0] for r in sco.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check("opening an old file adds neither an advice nor an incident table", t_open == t_before, str(t_open ^ t_before))
    sco.persist_advice_incidents([inc(1)], T0)
    t_after = {r[0] for r in sco.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check("the first persisted incident adds only advice_incident", t_after - t_before == {"advice_incident"} and t_before <= t_after,
          str(t_after ^ t_before))
    sco.db.close()

with guard("[11] bounded to the newest ADVICE_INCIDENTS_KEPT"):
    scb = Scorecard(":memory:")
    allinc = [inc(n) for n in range(1, KEPT + 6)]
    for i_ in allinc:
        scb.persist_advice_incidents([i_], T0 + timedelta(days=100))
    got = scb.advice_incidents()
    check(f"after {len(allinc)} incidents the table holds exactly the newest {KEPT}", len(got) == KEPT
          and [g["first_failed_utc"] for g in got] == [i_["first_failed_utc"] for i_ in reversed(allinc)][:KEPT], str(len(got)))
    scb2 = Scorecard(":memory:")
    scb2.persist_advice_incidents(allinc, T0 + timedelta(days=100))
    check("... also when they arrive in one call", scb2.db.execute("SELECT COUNT(*) FROM advice_incident").fetchone()[0] == KEPT)

with guard("[11] failures are isolated and only a class name is kept"):
    sch = Scorecard(":memory:")
    sch.db.execute("CREATE TABLE advice_incident (foo TEXT)")
    sch.db.execute("INSERT INTO advice_incident VALUES ('x')")
    sch.db.commit()
    rr = tried(lambda: sch.persist_advice_incidents([inc(1)], T0))
    check("an advice_incident table of another shape: nothing raised, nothing persisted, counted, the table untouched, the old paths work",
          isinstance(rr, dict) and rr.get("persisted") == [] and rr.get("error") == "DatabaseError" and sch.incident_write_failures == 1
          and [tuple(r) for r in sch.db.execute("SELECT * FROM advice_incident")] == [("x",)] and old_paths(sch) == "ok", str(rr))
    check("... reading it gives no rows, not an exception", tried(lambda: sch.advice_incidents()) == [])
    real_idl = scmod.ADVICE_INCIDENT_DDL
    scmod.ADVICE_INCIDENT_DDL = "CREATE TABLE advice_incident (;"
    try:
        scd = Scorecard(":memory:")
        rd = tried(lambda: scd.persist_advice_incidents([inc(1)], T0))
        check("a DDL that raises: nothing raised, nothing persisted, counted, the old paths work",
              isinstance(rd, dict) and rd.get("persisted") == [] and isinstance(rd.get("error"), str) and rd["error"].isidentifier()
              and scd.incident_write_failures == 1 and old_paths(scd) == "ok", str(rd))
    finally:
        scmod.ADVICE_INCIDENT_DDL = real_idl
    sce = Scorecard(":memory:")
    sce.persist_advice_incidents([inc(1, reason=SECRET), {**inc(2), "first_reason": SECRET}], T0)
    stored = json.dumps(sce.advice_incidents())
    check("a reason that is not a class name is never stored (only an identifier, or UnknownError)",
          "SECRET" not in stored and "private" not in stored and "sensor." not in stored and "UnknownError" in stored, stored[:200])
    scz = Scorecard(":memory:")
    bad_time = {**inc(1), "first_failed_utc": "not a time"}
    rz = tried(lambda: scz.persist_advice_incidents([bad_time], T0))
    check("a malformed incident is swallowed and counted too", isinstance(rz, dict) and rz.get("persisted") == []
          and scz.incident_write_failures == 1, str(rz))

with guard("[11] read-only reading: the library and the command line"):
    dbi = tmp / "inc.db"
    scs = Scorecard(str(dbi))
    scs.persist_advice_incidents([inc(1), inc(2)], T0)
    scs.db.close()
    b_before = dbi.read_bytes()
    check("the exporter's column list is the scorecard's", advice_export.INCIDENT_COLUMNS == scmod.ADVICE_INCIDENT_COLUMNS)
    lib = advice_export.read_incidents(str(dbi))
    check("read_incidents returns the stored incidents, newest first, and does not change the file",
          [x["first_failed_utc"] for x in lib] == [inc(2)["first_failed_utc"], inc(1)["first_failed_utc"]] and dbi.read_bytes() == b_before)
    out_i = io.StringIO()
    with redirect_stdout(out_i):
        rc_i = advice_export.main([str(dbi), "--incidents"])
    check("the command line prints them (exit 0)", rc_i == 0 and [x["first_failed_utc"] for x in json.loads(out_i.getvalue())]
          == [x["first_failed_utc"] for x in lib])
    no_tab = tmp / "no_inc.db"
    sn = Scorecard(str(no_tab))
    sn.db.close()
    check("a database without the table gives [] and creates nothing", advice_export.read_incidents(str(no_tab)) == []
          and "advice_incident" not in {r[0] for r in sqlite3.connect(no_tab).execute("SELECT name FROM sqlite_master")})
    err_i = io.StringIO()
    with contextlib.redirect_stderr(err_i):
        rc_m = advice_export.main([str(tmp / "missing_inc.db"), "--incidents"])
    check("a missing database exits 2 and creates no file", rc_m == 2 and not (tmp / "missing_inc.db").exists())

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence advice log:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All intelligence advice log checks PASSED.")
