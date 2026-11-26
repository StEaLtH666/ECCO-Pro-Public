#!/usr/bin/env python3
"""The advice log's incidents and its verified write (Ghost, the diagnostics-only advice log): health recovers, history stays.

A failed advice write opens an INCIDENT (when it first failed and last failed, how many attempts and slot cycles were missed, the
exception class name as the reason, the issue times of the advice that could not be written). STORE_RECORD is WARN with the reason
and the counts while the latest write attempt has failed or is unverified, and returns to PASS only after a VERIFIED write: the
rows just written are read back from the database by their own ids after the commit and found. The incident is then CLOSED and
KEPT (in the diagnostics, bounded to the newest few, and in a small table that exists only once an incident has been persisted).
The cumulative failure counter is history and is never reset.

  [A] the ledger (runtime/store.py AdviceHealth), pure: first write; failure; extension; recovery; a second incident; unverified
      (a written row not found, a missing read-back, a failing read-back); a cycle with nothing to write (neutral); a step
      failure (timeout or exception: counted only inside the incident, not in the since-start count of the WARN text); the bound and
      the dropped count; only a class name as a reason; the text fits the check
  [B] the store, on real files: the verified flag of record_cycle, a row removed by a trigger, the incident table created only when
      incidents are persisted and never at open or by an advice write, closed incidents only, bounded, idempotent, isolated; the
      known limit that incidents are keyed and pruned by the text of their first failure time
  [C] the BUILT kit under the stand-in Home Assistant, a stub engine and real SQLite: first write; failure then recovery; two
      failures then recovery; failure, recovery and a new failure; a table of another shape; an unverified write; a store step
      that raises or times out; a cycle with no advice; a restart; the diagnostics download; N slot cycles with the identical
      advice are N rows; no published value changes; AFTER a verified write the persist of the closed incident fails (an
      advice_incident table of another shape), times out or raises: the store step stays a success, STORE_RECORD stays PASS, no
      published value differs from a reference run, the failure shows only in the persist's own record, and the incident stays
      pending and listed, is offered again at each later verified write and is persisted exactly once

Plain script; exits 1 on any failure. Synthetic data only (the fictional year 2030); no network.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class guard:
    """Run a block of checks; an exception inside it is a FAIL of the named check, not a crash of the whole suite."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb) -> bool:
        if et is not None and issubclass(et, Exception):
            check(self.name, False, f"raised {et.__name__}: {str(ev)[:200]}")
            return True
        return False


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
T0 = datetime(2030, 1, 15, 0, 0, tzinfo=UTC)
PREFIX = "ecco_intel_advice_incident_"
SECRET = "SECRET-1234 /private/path sensor.test_secret_entity"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
STORE = importlib.import_module("custom_components.ecco_intelligence.runtime.store")
COORD = importlib.import_module("custom_components.ecco_intelligence.coordinator")
DIAG = importlib.import_module("custom_components.ecco_intelligence.diagnostics")
VEN_SC = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.scorecard")
AH = getattr(STORE, "AdviceHealth", None)
KEPT = getattr(VEN_SC, "ADVICE_INCIDENTS_KEPT", None)


def at(k: float) -> datetime:
    return T0 + timedelta(hours=k)


def ls(rows: int = 2, failures: int = 0, unverified: int = 0, verified=True, error: str | None = None, offered: bool = True) -> dict:
    """A RuntimeStateStore.record_cycle result, as the coordinator reads it."""
    d = {"recorded": True, "scored": 0, "removed": 0, "duplicate_slot": False}
    if offered:
        d.update({"advice_rows": rows, "advice_write_failures": failures, "advice_unverified": unverified, "advice_verified": verified})
        if error is not None:
            d["advice_error"] = error
    return d


def feed(ah, k: float, **kw) -> str:
    """One slot cycle's store step at slot k (issued 30 s after the slot, finished 40 s after it)."""
    return ah.note_store_result(ls(**kw), slot=at(k), issued=at(k) + timedelta(seconds=30), now=at(k) + timedelta(seconds=40))


def fail_step(ah, k: float, reason: str = "TimeoutError") -> str:
    return ah.note_step_failure(reason, slot=at(k), issued=at(k) + timedelta(seconds=30), now=at(k) + timedelta(seconds=40))


def snap(ah) -> dict:
    return ah.snapshot()


# =====================================================================================================================
print("== [A] the ledger: health recovers after a verified write, the incident stays")
with guard("[A] ledger exists"):
    check("runtime/store.py has the ledger class AdviceHealth and the incident bound is a small named constant",
          AH is not None and isinstance(KEPT, int) and 1 <= KEPT <= 50, f"{AH} {KEPT}")

with guard("[A1] first-ever write and a neutral first cycle"):
    a = AH()
    check("a new ledger has no incident, is not failing and has verified nothing (health is never assumed)",
          not a.failing and snap(a)["open"] is None and snap(a)["closed"] == [] and snap(a)["verified_writes"] == 0
          and snap(a)["last_verified_utc"] is None and snap(a)["current_failure"] is False)
    check("a cycle with nothing to write on a new ledger is NEUTRAL and is not recorded as PASS: INFO, until its own first verified write",
          feed(a, 0, rows=0, verified=None) == "NEUTRAL" and a.store_check(0)[0] == "INFO" and not a.failing, str(a.store_check(0)))
    check("a store that was not given any advice (no advice keys) is not an advice cycle: the old PASS text",
          feed(a, 1, offered=False) == "NOT_OFFERED" and a.store_check(0)[0] == "PASS", str(a.store_check(0)))
    check("the first verified write: VERIFIED, PASS, no incident, counted", feed(a, 2) == "VERIFIED" and a.store_check(0)[0] == "PASS"
          and not a.failing and snap(a)["verified_writes"] == 1 and snap(a)["last_verified_utc"] is not None and snap(a)["closed"] == [])
    check("after that a neutral cycle keeps PASS (health unchanged)", feed(a, 3, rows=0, verified=None) == "NEUTRAL"
          and a.store_check(0)[0] == "PASS")

with guard("[A2] failure, extension, neutral, recovery"):
    a = AH()
    feed(a, 0)
    out1 = feed(a, 1, rows=0, failures=1, verified=False, error="OperationalError")
    s1 = snap(a)
    o = s1["open"]
    check("a failed write opens an incident: FAILED, failing, the reason is the class name, one attempt, one slot cycle missed",
          out1 == "FAILED" and a.failing and s1["current_failure"] is True and o is not None and o["reason"] == "OperationalError"
          and o["first_reason"] == "OperationalError" and o["failed_count"] == 1 and o["missed_slots"] == 1 and o["state"] == "OPEN"
          and o["recovered_utc"] is None, str(o))
    check("... with the times: first and last failure, and the issue time of the advice that could not be written",
          o["first_failed_utc"] == o["last_failed_utc"] == (at(1) + timedelta(seconds=40)).isoformat()
          and o["first_issued_utc"] == o["last_issued_utc"] == (at(1) + timedelta(seconds=30)).isoformat(), str(o))
    lvl, txt = a.store_check(1)
    check("STORE_RECORD is WARN with the reason and the counts, within the check's 160 characters",
          lvl == "WARN" and "OperationalError" in txt and "1 slot" in txt and len(txt) <= 160, f"{lvl} {txt!r}")
    out2 = feed(a, 2, rows=0, failures=1, verified=False, error="DatabaseError")
    o2 = snap(a)["open"]
    check("a second failure extends the same incident (two attempts, two slot cycles, the latest reason, the first reason kept)",
          out2 == "FAILED" and o2["failed_count"] == 2 and o2["missed_slots"] == 2 and o2["reason"] == "DatabaseError"
          and o2["first_reason"] == "OperationalError" and o2["first_failed_utc"] == o["first_failed_utc"]
          and o2["last_failed_utc"] == (at(2) + timedelta(seconds=40)).isoformat() and len(snap(a)["closed"]) == 0, str(o2))
    check("... and the text says two", "2 slot" in a.store_check(2)[1])
    out_same = feed(a, 2, rows=0, failures=1, verified=False, error="DatabaseError")
    o3 = snap(a)["open"]
    check("a second attempt in the same slot cycle counts as an attempt, not as another missed slot cycle",
          o3["failed_count"] == 3 and o3["missed_slots"] == 2, str(o3))
    check("a cycle with nothing to write while failing is NEUTRAL: still failing, the incident unchanged, nothing recorded",
          feed(a, 3, rows=0, verified=None) == "NEUTRAL" and a.failing and snap(a)["open"] == o3 and a.store_check(3) is None)
    out_ok = feed(a, 4, rows=2)
    s4 = snap(a)
    check("a verified write recovers: PASS, not failing, the incident is CLOSED and kept (recovered time, rows written, slot cycles missed)",
          out_ok == "VERIFIED" and not a.failing and s4["current_failure"] is False and s4["open"] is None and len(s4["closed"]) == 1
          and s4["closed"][0]["state"] == "CLOSED" and s4["closed"][0]["recovered_utc"] == (at(4) + timedelta(seconds=40)).isoformat()
          and s4["closed"][0]["rows_since"] == 2 and s4["closed"][0]["missed_slots"] == 2 and s4["closed"][0]["failed_count"] == 3
          and a.store_check(3)[0] == "PASS", str(s4))
    check("... and a later verified write changes nothing in the kept incident", (feed(a, 5), snap(a)["closed"])[1] == s4["closed"])

with guard("[A3] a second incident"):
    a = AH()
    feed(a, 0)
    feed(a, 1, rows=0, failures=1, verified=False, error="OperationalError")
    feed(a, 2)
    feed(a, 3, rows=0, failures=1, verified=False, error="ProgrammingError")
    s = snap(a)
    check("failure, recovery, new failure: the first incident stays closed, a second one is open, newest first in the list",
          a.failing and s["open"] is not None and s["open"]["reason"] == "ProgrammingError" and len(s["closed"]) == 1
          and s["closed"][0]["reason"] == "OperationalError" and s["open"]["first_failed_utc"] > s["closed"][0]["last_failed_utc"], str(s))
    feed(a, 4)
    s = snap(a)
    check("... recovered again: two closed incidents, newest first", not a.failing and len(s["closed"]) == 2
          and s["closed"][0]["reason"] == "ProgrammingError" and s["closed"][1]["reason"] == "OperationalError")

with guard("[A4] unverified is not a recovery"):
    a = AH()
    feed(a, 0)
    o_un = feed(a, 1, rows=2, unverified=1, verified=False, error="AdviceReadBackMissing")
    s = snap(a)
    check("a write whose rows were not found again opens an incident (UNVERIFIED, reason as the class or code given)",
          o_un == "UNVERIFIED" and a.failing and s["open"]["reason"] == "AdviceReadBackMissing" and s["open"]["failed_count"] == 1,
          str(s))
    check("... and its text says so", "unverified" in a.store_check(0)[1].lower(), a.store_check(0)[1])
    check("rows reported without a verification at all (no advice_verified) are UNVERIFIED too, never a success",
          feed(a, 2, rows=2, verified=None) == "UNVERIFIED" and a.failing and snap(a)["open"]["failed_count"] == 2)
    check("rows with advice_verified False and nothing else are UNVERIFIED, the incident stays open",
          feed(a, 3, rows=2, verified=False) == "UNVERIFIED" and a.failing and snap(a)["open"]["failed_count"] == 3
          and len(snap(a)["closed"]) == 0)
    check("a failing read-back (the class name of its error) is UNVERIFIED and extends the incident",
          feed(a, 4, rows=2, unverified=1, verified=False, error="OperationalError") == "UNVERIFIED" and a.failing
          and snap(a)["open"]["reason"] == "OperationalError")
    check("a fresh ledger: an unverified write opens an incident, it does not pass",
          feed(AH(), 0, rows=2, verified=False, unverified=1) == "UNVERIFIED")
    a2 = AH()
    check("a fresh ledger: rows reported with no verification information are not a success either",
          feed(a2, 0, rows=3, verified=None) == "UNVERIFIED" and a2.failing and a2.store_check(0)[0] == "WARN")
    check("... and a verified write then recovers", feed(a, 5) == "VERIFIED" and not a.failing and len(snap(a)["closed"]) == 1)

with guard("[A5] a store step that failed as a whole"):
    a = AH()
    feed(a, 0)
    check("a timeout of the whole store step opens an incident with the class name TimeoutError", fail_step(a, 1, "TimeoutError") == "STEP_FAILED"
          and a.failing and snap(a)["open"]["reason"] == "TimeoutError" and snap(a)["open"]["missed_slots"] == 1, str(snap(a)["open"]))
    check("... an exception extends it with its class name", fail_step(a, 2, "OSError") == "STEP_FAILED"
          and snap(a)["open"]["reason"] == "OSError" and snap(a)["open"]["first_reason"] == "TimeoutError"
          and snap(a)["open"]["failed_count"] == 2 and snap(a)["open"]["missed_slots"] == 2)
    check("... and a verified write closes it", feed(a, 3) == "VERIFIED" and not a.failing and len(snap(a)["closed"]) == 1)
    b_ = AH()
    fail_step(b_, 0, SECRET)
    check("a step failure whose 'reason' is not a class name stores UnknownError, never the text", snap(b_)["open"]["reason"] == "UnknownError"
          and "SECRET" not in json.dumps(snap(b_)))

with guard("[A6] only a class name is ever a reason"):
    a = AH()
    for k_, bad in enumerate((SECRET, "has space", "x" * 200, "", None, 42, "9starts_with_digit", "a.b", "line\nbreak")):
        feed(a, k_, rows=0, failures=1, verified=False, error=bad)
    o = snap(a)["open"]
    check("a message, an empty or a non-string error, a very long or a non-identifier name: the reason is UnknownError, every time",
          o["reason"] == "UnknownError" and o["first_reason"] == "UnknownError" and o["failed_count"] == 9
          and "SECRET" not in json.dumps(snap(a)) and "private" not in json.dumps(snap(a)))
    feed(a, 20, rows=0, failures=1, verified=False, error="IntegrityError")
    check("... and a class name is kept", snap(a)["open"]["reason"] == "IntegrityError")

with guard("[A7] bounded: the newest few, the rest counted as dropped"):
    a = AH()
    n_inc = (KEPT or 10) + 7
    for i_ in range(n_inc):
        feed(a, 3 * i_, rows=0, failures=1, verified=False, error="OperationalError")
        feed(a, 3 * i_ + 1)
    s = snap(a)
    check(f"after {n_inc} incidents the ledger keeps exactly {KEPT} and says how many it dropped", len(s["closed"]) == KEPT
          and s["dropped"] == n_inc - KEPT and s["kept_max"] == KEPT, f"{len(s['closed'])} {s['dropped']}")
    check("... the newest ones are the ones kept (newest first)", [c["first_failed_utc"] for c in s["closed"]]
          == sorted((c["first_failed_utc"] for c in s["closed"]), reverse=True) and s["closed"][0]["first_failed_utc"]
          == (at(3 * (n_inc - 1)) + timedelta(seconds=40)).isoformat())
    feed(a, 500, rows=0, failures=1, verified=False, error="OperationalError")
    s = snap(a)
    check("an open incident is never the one dropped: with the list full, a new incident drops the oldest closed one",
          s["open"] is not None and len(s["closed"]) == KEPT - 1 and s["dropped"] == n_inc - KEPT + 1, f"{len(s['closed'])} {s['dropped']}")
    big = AH()
    for i_ in range(200):
        fail_step(big, i_)
    check("an open incident does not grow the ledger: 200 failed steps are one incident", len(snap(big)["closed"]) == 0
          and snap(big)["open"]["failed_count"] == 200 and len(json.dumps(snap(big))) < 4000)

with guard("[A8] the text fits"):
    a = AH()
    for k_ in range(99999):                       # a very long outage: six-digit counts
        fail_step(a, k_, "x" * 40)
    feed(a, 99999, rows=0, failures=1, verified=False, error="x" * 40)
    txt = (a.store_check(100000) or ("", ""))[1]
    check("the WARN text of the longest class name and six-digit counts is at most 160 characters (the check keeps 160)",
          0 < len(txt) <= 160 and snap(a)["open"]["missed_slots"] == 100000, f"{len(txt)} {txt!r}")

with guard("[A9] what still needs persisting"):
    a = AH()
    feed(a, 0)
    feed(a, 1, rows=0, failures=1, verified=False, error="OperationalError")
    check("an open incident is never offered for persisting", a.pending_incidents() == [])
    feed(a, 2)
    p = a.pending_incidents()
    check("a closed one that is not persisted yet is offered, as a copy", len(p) == 1 and p[0]["state"] == "CLOSED" and p[0]["persisted"] is False)
    p[0]["reason"] = "Changed"
    check("... changing the copy does not change the ledger", snap(a)["closed"][0]["reason"] == "OperationalError")
    a.note_persisted([p[0]["first_failed_utc"]])
    check("once persisted it is not offered again, and the snapshot says it is persisted", a.pending_incidents() == []
          and snap(a)["closed"][0]["persisted"] is True)
    a.note_persisted(["nothing like it"])
    check("an unknown key is ignored", a.pending_incidents() == [])

with guard("[A10] step failures count only inside the incident"):
    a = AH()
    feed(a, 0)
    fail_step(a, 1, "TimeoutError")
    fail_step(a, 2, "OSError")
    feed(a, 3, rows=0, failures=1, verified=False, error="OperationalError")
    o10 = snap(a)["open"]
    txt10 = a.store_check(1)[1]                    # the coordinator passes advice_write_failures + advice_unverified_writes: 1 here
    check("two failed steps and one failed write are one incident of three attempts and three missed slot cycles; the WARN text says three "
          "slot(s) missed but only the one failed write since start: the step failures are in the incident, not in the since-start count",
          o10["failed_count"] == 3 and o10["missed_slots"] == 3 and "3 slot(s) missed" in txt10 and "1 failed/unverified since start" in txt10,
          f"{o10} {txt10!r}")
    check("... and the since-start count is the caller's: given 0 (only step failures so far) the text says 0, never the attempts",
          "0 failed/unverified since start" in a.store_check(0)[1] and "3 slot(s) missed" in a.store_check(0)[1], a.store_check(0)[1])

# =====================================================================================================================
print("== [B] the store on real files: the verified flag, and the incident table that exists only once an incident is persisted")


def pay(gen: datetime, valid_s: float = 900.0, status: str = "OK") -> dict:
    ok = status == "OK"
    out = {}
    for kind, eid in (("charge_target", "sensor.t_ct"), ("dump_to_grid", "sensor.t_dp")):
        rec = {"kind": kind, "status": status, "generated_at": gen.isoformat(),
               "valid_until": (gen + timedelta(seconds=valid_s)).isoformat() if ok else None, "reason_codes": []}
        unrec = {"advice": {"target_soc_pct": 80.0, "effective_reserve_pct": 20.0, "stop_soc_pct": 40.0, "export_kwh": 1.0,
                            "export_kw_avg": 2.0, "dump_advisable": True,
                            "window": [at(26).isoformat(), at(29).isoformat()]}} if ok else {}
        out[eid] = (status, rec, unrec)
    return out


def tables(path: Path) -> set:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def sql(path: Path, *stmts: str) -> None:
    con = sqlite3.connect(str(path))
    try:
        for s_ in stmts:
            con.execute(s_)
        con.commit()
    finally:
        con.close()


def closed_inc(n: int, reason: str = "OperationalError") -> dict:
    t = T0 + timedelta(days=n)
    return {"first_failed_utc": t.isoformat(), "last_failed_utc": (t + timedelta(hours=2)).isoformat(), "failed_count": 3,
            "missed_slots": 3, "reason": reason, "first_reason": reason, "first_issued_utc": t.isoformat(),
            "last_issued_utc": (t + timedelta(hours=2)).isoformat(), "state": "CLOSED",
            "recovered_utc": (t + timedelta(hours=3)).isoformat(), "rows_since": 2, "persisted": False}


with guard("[B1] record_cycle: verified, unverified, failed"):
    cfg_b = root / "b1"
    cfg_b.mkdir()
    H.write_site(cfg_b, H.site_profile())
    st = STORE.RuntimeStateStore(str(cfg_b))
    ok, text = st.try_open()
    db_path = st.root / "scorecard.sqlite3"
    check("the store opens", ok, text)
    check("opening creates neither an advice table nor an incident table", not ({"advice_log", "advice_incident"} & tables(db_path)),
          str(tables(db_path)))
    out0 = st.record_cycle(None, at(0), at(0))
    check("a record_cycle with no advice reports no advice keys and creates neither table",
          "advice_rows" not in out0 and "advice_verified" not in out0 and not ({"advice_log", "advice_incident"} & tables(db_path)))
    out1 = st.record_cycle(None, at(1), at(1), advice=pay(at(1)), dump_duration_min=30)
    check("a first advice write: two rows, verified (read back by id), nothing failed or unverified",
          out1.get("advice_rows") == 2 and out1.get("advice_verified") is True and out1.get("advice_write_failures") == 0
          and out1.get("advice_unverified") == 0 and "advice_error" not in out1, str(out1))
    check("... it created the advice table and still no incident table", "advice_log" in tables(db_path) and "advice_incident" not in tables(db_path))
    out_n = st.record_cycle(None, at(1) + timedelta(minutes=5), at(1) + timedelta(minutes=5), advice=pay(at(1) + timedelta(minutes=5)),
                            dump_duration_min=30)
    check("the same advice inside its validity writes nothing: rows 0, nothing verified (neutral), nothing failed",
          out_n.get("advice_rows") == 0 and out_n.get("advice_verified") is None and out_n.get("advice_write_failures") == 0
          and out_n.get("advice_unverified") == 0, str(out_n))
    out_e = st.record_cycle(None, at(2), at(2), advice={})
    check("an empty published set is neutral: rows 0, nothing verified", out_e.get("advice_rows") == 0 and out_e.get("advice_verified") is None
          and out_e.get("advice_write_failures") == 0, str(out_e))
    sql(db_path, "CREATE TRIGGER gone AFTER INSERT ON advice_log BEGIN DELETE FROM advice_log WHERE advice_id = NEW.advice_id; END")
    out_u = st.record_cycle(None, at(3), at(3), advice=pay(at(3)), dump_duration_min=30)
    check("a write that raises nothing but whose rows are not there afterwards is UNVERIFIED: verified False, one unverified, no failure, "
          "the fixed code as the reason",
          out_u.get("advice_verified") is False and out_u.get("advice_unverified") == 1 and out_u.get("advice_write_failures") == 0
          and out_u.get("advice_error") == "AdviceReadBackMissing", str(out_u))
    sql(db_path, "DROP TRIGGER gone", "CREATE TRIGGER boom BEFORE INSERT ON advice_log BEGIN SELECT RAISE(ABORT, 'SECRET-1234 /private/path'); END")
    out_f = st.record_cycle(None, at(4), at(4), advice=pay(at(4)), dump_duration_min=30)
    check("a write that raises: one failure, 0 rows, not verified, the class name as the reason and never the message",
          out_f.get("advice_write_failures") == 1 and out_f.get("advice_rows") == 0 and out_f.get("advice_verified") is False
          and out_f.get("advice_error") == "IntegrityError" and "SECRET" not in json.dumps(out_f), str(out_f))
    check("... and no incident table was created by any of this", "advice_incident" not in tables(db_path), str(tables(db_path)))
    sql(db_path, "DROP TRIGGER boom")
    out_r = st.record_cycle(None, at(5), at(5), advice=pay(at(5)), dump_duration_min=30)
    check("once the database takes the write again, it is verified again", out_r.get("advice_verified") is True and out_r.get("advice_rows") == 2, str(out_r))
    st.close()

with guard("[B2] persisting incidents: lazily, closed only, bounded, idempotent, isolated"):
    cfg_p = root / "b2"
    cfg_p.mkdir()
    H.write_site(cfg_p, H.site_profile())
    sp = STORE.RuntimeStateStore(str(cfg_p))
    sp.try_open()
    dbp = sp.root / "scorecard.sqlite3"
    sp.record_cycle(None, at(0), at(0), advice=pay(at(0)), dump_duration_min=30)
    counts_before = sp.counts()
    check("reading incidents from a store that has none: [] and no table created", sp.advice_incidents() == []
          and "advice_incident" not in tables(dbp))
    open_inc = {**closed_inc(9), "state": "OPEN", "recovered_utc": None, "rows_since": None}
    res = sp.log_advice_incidents([closed_inc(1), open_inc], at(1))
    check("persisting writes the closed incident and creates the table now; the open one is neither written nor reported persisted",
          res.get("persisted") == [closed_inc(1)["first_failed_utc"]] and res.get("error") is None and "advice_incident" in tables(dbp), str(res))
    check("... the scorecard's own tables and counts are as they were", {k: v for k, v in sp.counts().items()} == counts_before)
    got = sp.advice_incidents()
    check("... it reads back (read-only) with its class name, counts and times", len(got) == 1 and got[0]["reason"] == "OperationalError"
          and got[0]["failed_count"] == 3 and got[0]["recovered_utc"] == closed_inc(1)["recovered_utc"], str(got))
    sp.log_advice_incidents([closed_inc(1)], at(2))
    check("persisting the same incident again changes nothing (one row)", len(sp.advice_incidents()) == 1)
    for n_ in range(2, (KEPT or 10) + 6):
        sp.log_advice_incidents([closed_inc(n_)], at(3))
    check("the table is bounded to the newest few", len(sp.advice_incidents()) == KEPT and sp.advice_incidents()[0]["first_failed_utc"]
          == closed_inc((KEPT or 10) + 5)["first_failed_utc"])
    res_s = sp.log_advice_incidents([closed_inc(40, reason=SECRET)], at(4))
    check("a reason that is not a class name is stored as UnknownError", "SECRET" not in json.dumps(sp.advice_incidents())
          and "UnknownError" in json.dumps(sp.advice_incidents()), str(res_s))
    sp.close()
    check("a closed store persists nothing and says so", sp.log_advice_incidents([closed_inc(60)], at(5)).get("refused") == "closed")

with guard("[B3] persisting is isolated"):
    cfg_o = root / "b3"
    cfg_o.mkdir()
    H.write_site(cfg_o, H.site_profile())
    so = STORE.RuntimeStateStore(str(cfg_o))
    so.try_open()
    dbo = so.root / "scorecard.sqlite3"
    sql(dbo, "CREATE TABLE advice_incident (foo TEXT)", "INSERT INTO advice_incident VALUES ('x')")
    res_o = so.log_advice_incidents([closed_inc(1)], at(1))
    check("an advice_incident table of another shape: nothing raised, nothing persisted, the class name as the error, the table untouched",
          res_o.get("persisted") == [] and res_o.get("error") == "DatabaseError"
          and sqlite3.connect(str(dbo)).execute("SELECT * FROM advice_incident").fetchall() == [("x",)], str(res_o))
    check("... the scorecard record and the gate still work", so.record_cycle(None, at(2), at(2))["recorded"] is False
          and so.try_open()[0] is True)
    try:
        so.advice_incidents()
        unreadable = False
    except Exception:  # noqa: BLE001 - the test asks whether it raised
        unreadable = True
    check("... reading an incident table of another shape raises, so the caller can tell it from an empty one", unreadable)
    so.close()

with guard("[B4] reading from a store with no file"):
    cfg_n = root / "b4"
    cfg_n.mkdir()
    H.write_site(cfg_n, H.site_profile())
    sn = STORE.RuntimeStateStore(str(cfg_n))
    check("no state directory at all: [] and nothing created", sn.advice_incidents() == [] and not (cfg_n / "ecco" / "intelligence" / "state").exists())

with guard("[B5] a known limit: incidents are keyed and pruned by the text of their first failure time"):
    cfg_k = root / "b5"
    cfg_k.mkdir()
    H.write_site(cfg_k, H.site_profile())
    sk = STORE.RuntimeStateStore(str(cfg_k))
    sk.try_open()
    newest_n = 10 + (KEPT or 10)
    for n_ in range(10, newest_n):
        sk.log_advice_incidents([closed_inc(n_)], at(1))
    check("non-vacuity: the table holds exactly the newest few", len(sk.advice_incidents()) == KEPT, str(len(sk.advice_incidents())))
    older = closed_inc(3)                           # a clock stepped backwards: a NEW incident whose first failure is older than every stored one
    res_k = sk.log_advice_incidents([older], at(2))
    keys_k = [x["first_failed_utc"] for x in sk.advice_incidents()]
    check("such an incident is reported persisted (no error) and is pruned at once: it is not in the table, the stored ones are unchanged",
          res_k.get("persisted") == [older["first_failed_utc"]] and res_k.get("error") is None and older["first_failed_utc"] not in keys_k
          and keys_k == [closed_inc(n_)["first_failed_utc"] for n_ in range(newest_n - 1, 9, -1)], f"{res_k} {keys_k}")
    sk.close()


# =====================================================================================================================
print("== [C] the built kit under the stand-in Home Assistant: a stub engine, real SQLite")
DIAG_KEYS = ("current_failure", "last_outcome", "attempts", "verified_writes", "last_verified_utc", "kept_max", "dropped", "open", "closed")


def stub(inputs):
    """An injected run_cycle built only from the kit's contract constructors: every advice item BLOCKED (so the advice log gets a row
    for the charge target and one for the Dump-to-Grid, each slot cycle), pv_tomorrow OK."""
    bl = (("TEST_BLOCK", "synthetic block"),)
    items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
    fc = (C.ForecastView("predicted_day_load", C.ItemStatus.BLOCKED, blockers=bl),
          C.ForecastView("pv_tomorrow", C.ItemStatus.OK, value=4.2, valid_until=inputs.now + timedelta(hours=1)),
          C.ForecastView("predicted_morning_soc", C.ItemStatus.BLOCKED, blockers=bl))
    return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                               decisions=inputs.decisions, paused=inputs.paused, valid_until=inputs.now + timedelta(hours=1))


class Scn:
    """One coordinator on a fresh configuration directory (or on an existing one: a restart)."""

    def __init__(self, name: str, *, cfg: Path | None = None, now: datetime = NOW, pre=None, engine=stub) -> None:
        self.name = name
        self.cfg = cfg or (root / name)
        self.cfg.mkdir(exist_ok=True)
        self.hass = h.new_hass(self.cfg, now)
        self.hass.states.events = False
        H.write_site(self.cfg, H.site_profile(decisions=H.owner_decisions()))
        H.seed_fresh_states(self.hass.states, now)
        h.recorder().statistics = H.synthetic_statistics(now, days=30)
        if pre is not None:
            pre(self)
        self.before = H.tree_hashes(self.cfg)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 120.0
        if engine is not None:
            H.inject(self.c, engine)
        self.slots_seen = 0
        self.real_engine = engine is None

    @property
    def db(self) -> Path:
        return self.cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"

    def advance(self, n: int = 1, settle: float = 10.0) -> None:
        for _ in range(n):
            h.set_now(h.now + timedelta(seconds=60))
            H.seed_fresh_states(self.hass.states, h.now)
            h.tick(0, settle=settle)

    def warm(self) -> None:
        """Three ticks past the grace: the first slot cycle runs."""
        self.advance(3, settle=20.0)
        self.slots_seen = self.c.counters["slot_runs_started"]

    def slot(self) -> None:
        """Move to the next full hour (a schedule slot) and let that slot cycle run; one slot cycle, no more."""
        n0 = self.c.counters["slot_runs_started"]
        nxt = h.now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        h.set_now(nxt - timedelta(seconds=60))
        if self.real_engine:                              # the recorder compiles each hour as it ends
            h.recorder().statistics = H.synthetic_statistics(h.now, days=30)
        self.advance(3, settle=20.0)
        check(f"{self.name}: non-vacuity: exactly one more slot cycle ran", self.c.counters["slot_runs_started"] == n0 + 1,
              f"{n0} {self.c.counters['slot_runs_started']}")

    def sc(self) -> str | None:
        return self.c.selftest.as_dict().get("STORE_RECORD")

    def inc(self) -> dict:
        return self.c.diagnostics().get("advice_incidents") or {}

    def open_(self) -> dict:
        return self.inc().get("open") or {}

    def closed_(self) -> list:
        return self.inc().get("closed") or []

    def ents(self) -> dict:
        """The published entities as the state-machine stand-in holds them: {entity id: (state, attributes as sorted JSON)}."""
        return {eid: (st.state, json.dumps(dict(st.attributes), sort_keys=True, default=str))
                for eid, st in self.hass.states._states.items() if eid.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel"))}

    def download(self) -> dict:
        return h.run(DIAG.async_get_config_entry_diagnostics(self.hass, self.entry), timeout=120.0)

    def rows(self) -> list:
        if not self.db.is_file() or "advice_log" not in tables(self.db):
            return []
        con = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("SELECT kind, status, content_hash FROM advice_log ORDER BY advice_id").fetchall()
        finally:
            con.close()

    def stored(self) -> list:
        if not self.db.is_file() or "advice_incident" not in tables(self.db):
            return []
        con = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM advice_incident ORDER BY first_failed_utc")]
        finally:
            con.close()

    def trigger(self, name: str, ddl: str | None) -> None:
        """Install (ddl) or drop (None) a trigger on the advice table, as a real SQLite fault."""
        sql(self.db, f"DROP TRIGGER IF EXISTS {name}", *([ddl] if ddl else []))

    def close(self, unload: bool = True) -> None:
        if unload and self.c is not None and not self.c.closed:
            h.unload(self.entry)
        after = H.tree_hashes(self.cfg)
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)
                         and not k.startswith("ecco/intelligence/state/"))
        check(f"{self.name}: zero write attempts and no stand-in violation", not self.hass.write_attempts and not self.hass.violations,
              str((self.hass.write_attempts[:2], self.hass.violations[:2])))
        check(f"{self.name}: the configuration tree changed only under ecco/intelligence/state/", not changed, str(changed[:3]))


BOOM = "CREATE TRIGGER boom BEFORE INSERT ON advice_log BEGIN SELECT RAISE(ABORT, 'SECRET-1234 /private/path sensor.test_secret_entity'); END"
GONE = "CREATE TRIGGER gone AFTER INSERT ON advice_log BEGIN DELETE FROM advice_log WHERE advice_id = NEW.advice_id; END"


def stored_of(download: dict) -> dict:
    """The stored incidents the download carries: the `stored` member of its advice_incidents block."""
    return (download.get("advice_incidents") or {}).get("stored") or {}


def no_secret(*objs) -> bool:
    text = json.dumps(objs, default=str)
    return "SECRET" not in text and "test_secret_entity" not in text and "/private" not in text


with guard("[C1] first-ever write ok; N slot cycles of identical advice are N rows"):
    s = Scn("ok")
    s.warm()
    check("the first slot cycle writes and verifies: STORE_RECORD PASS, two rows, no incident, no failure counted",
          s.sc() == "PASS" and len(s.rows()) == 2 and s.c.counters["advice_write_failures"] == 0
          and s.c.counters.get("advice_current_failure") == 0 and s.inc().get("open") is None and s.inc().get("verified_writes") == 1,
          f"{s.sc()} {len(s.rows())} {s.inc()}")
    check("the diagnostics carry the incident block with its fixed keys", set(DIAG_KEYS) <= set(s.inc()), str(sorted(s.inc())))
    for _ in range(4):
        s.slot()
    check("five slot cycles with the identical advice are five rows of each kind, with one content hash per kind (no deduplication)",
          len(s.rows()) == 10 and len({r[2] for r in s.rows() if r[0] == "charge_target"}) == 1
          and len({r[2] for r in s.rows() if r[0] == "dump_to_grid"}) == 1 and s.sc() == "PASS", str(len(s.rows())))
    check("no incident table exists in a store that never failed", "advice_incident" not in tables(s.db), str(tables(s.db)))
    check("... and every slot cycle was verified", s.inc().get("verified_writes") == 5, str(s.inc()))
    s.close()

with guard("[C2] failure, then recovery (two failures)"):
    s = Scn("recover")
    s.warm()
    s.trigger("boom", BOOM)
    s.slot()
    sc2 = s.sc()
    check("a failed write: STORE_RECORD is WARN with the class name and counts, the cumulative counter and the current-failure flag say so",
          str(sc2).startswith("WARN") and "IntegrityError" in str(sc2) and s.c.counters["advice_write_failures"] == 1
          and s.c.counters.get("advice_current_failure") == 1 and s.open_().get("failed_count") == 1 and no_secret(sc2, s.inc()), str(sc2))
    check("... the incident table does not exist while the database cannot take the advice write", "advice_incident" not in tables(s.db))
    s.slot()
    check("a second failure extends the same incident: two attempts, two slot cycles missed", s.open_().get("failed_count") == 2
          and s.open_().get("missed_slots") == 2 and s.c.counters["advice_write_failures"] == 2 and str(s.sc()).startswith("WARN")
          and len(s.closed_()) == 0 and "advice_incident" not in tables(s.db))
    s.trigger("boom", None)
    s.slot()
    inc = s.inc()
    check("a verified write recovers: STORE_RECORD is PASS and the current-failure flag is 0",
          s.sc() == "PASS" and s.c.counters.get("advice_current_failure") == 0 and inc.get("open") is None and inc.get("current_failure") is False,
          f"{s.sc()} {inc}")
    check("... the cumulative counter is history: it is not reset", s.c.counters["advice_write_failures"] == 2)
    cl = [dict(x) for x in (inc.get("closed") or [])]
    c0 = cl[0] if cl else {}
    check("... the incident is closed and kept with its counts, its reason and the rows of the recovering write",
          len(cl) == 1 and c0.get("state") == "CLOSED" and c0.get("failed_count") == 2 and c0.get("missed_slots") == 2
          and c0.get("reason") == "IntegrityError" and c0.get("rows_since") == 2 and c0.get("recovered_utc") is not None
          and c0.get("first_failed_utc", "z") <= c0.get("last_failed_utc", "") < c0.get("recovered_utc", ""), str(cl))
    st_rows = s.stored()
    r0 = st_rows[0] if st_rows else {}
    check("... and it is persisted now (the table is created only when the database is demonstrably writable again), once",
          len(st_rows) == 1 and c0.get("persisted") is True and r0.get("failed_count") == 2 and r0.get("missed_slots") == 2
          and r0.get("reason") == "IntegrityError" and r0.get("first_failed_utc") == c0.get("first_failed_utc")
          and r0.get("recovered_utc") == c0.get("recovered_utc") and r0.get("rows_since") == 2, str(st_rows))
    s.slot()
    check("a later slot cycle changes nothing in the kept incident and does not write it again", len(s.stored()) == 1 and s.sc() == "PASS"
          and s.closed_() == cl and s.c.counters["advice_write_failures"] == 2)
    d = s.download()
    check("the download carries the incident block and the stored incidents, with no message, entity id or path",
          set(DIAG_KEYS) <= set(d.get("advice_incidents", {})) and len(stored_of(d).get("incidents", [])) == 1
          and stored_of(d).get("status") == "OK" and no_secret(d), str(stored_of(d)))
    check("... and no top-level key was added to the download (the keys are the coordinator's own plus ghost)",
          set(d) == {"loaded"} | set(s.c.diagnostics()) | {"ghost"}, str(set(d) ^ ({"loaded"} | set(s.c.diagnostics()) | {"ghost"})))
    check("the published advice rows of the failed slot cycles are missing, the others are there (3 verified slot cycles of 5 -> 6 rows)",
          len(s.rows()) == 6, str(len(s.rows())))
    s.close()

with guard("[C3] failure, recovery, a new failure: a second incident"):
    s = Scn("second")
    s.warm()
    s.trigger("boom", BOOM)
    s.slot()
    s.trigger("boom", None)
    s.slot()
    check("first incident closed and persisted", s.sc() == "PASS" and len(s.closed_()) == 1 and len(s.stored()) == 1)
    s.trigger("boom", BOOM)
    s.slot()
    i3 = s.inc()
    check("a new failure opens a second incident: WARN again, the first stays closed, the cumulative counter is 2",
          str(s.sc()).startswith("WARN") and bool(i3.get("open")) and len(i3.get("closed") or []) == 1
          and (i3.get("open") or {}).get("first_failed_utc") != ((i3.get("closed") or [{}])[0]).get("first_failed_utc")
          and s.c.counters["advice_write_failures"] == 2
          and s.c.counters.get("advice_current_failure") == 1, str(i3))
    check("... the open one is not in the table, the closed one is", len(s.stored()) == 1)
    s.trigger("boom", None)
    s.slot()
    check("recovered again: two closed incidents, both persisted, PASS, the counter still 2", s.sc() == "PASS"
          and len(s.closed_()) == 2 and len(s.stored()) == 2 and s.c.counters["advice_write_failures"] == 2
          and all(c["persisted"] for c in s.closed_()))
    s.close()

with guard("[C4] a table of another shape: no verified write is possible, so it stays WARN"):
    def odd_table(scn) -> None:
        d = scn.cfg / "ecco" / "intelligence" / "state"
        d.mkdir(parents=True, exist_ok=True)
        sql(d / "scorecard.sqlite3", "CREATE TABLE advice_log (foo TEXT, bar INTEGER)")
    s = Scn("odd", pre=odd_table)
    s.warm()
    check("the start-up gate passes", s.c.selftest.as_dict().get("STORE_WRITABLE") == "PASS")
    for _ in range(3):
        check("a slot cycle with the odd table: WARN", str(s.sc()).startswith("WARN"), str(s.sc()))
        s.slot()
    i4 = s.inc()
    check("four failed attempts are one open incident, DatabaseError, four slot cycles missed; never recovered; nothing persisted",
          (i4.get("open") or {}) is not None and (i4.get("open") or {}).get("failed_count") == 4 and (i4.get("open") or {}).get("missed_slots") == 4
          and (i4.get("open") or {}).get("reason") == "DatabaseError" and (i4.get("closed") or []) == [] and str(s.sc()).startswith("WARN")
          and s.c.counters.get("advice_current_failure") == 1 and "advice_incident" not in tables(s.db), str(i4))
    check("... the store step itself completed (the advice failure is the only thing that failed) and no cycle exception was counted",
          s.c.last_store.get("advice_write_failures") == 1 and "recorded" in s.c.last_store and s.c.counters["exceptions"] == 0,
          str(s.c.last_store))
    s.close()

with guard("[C5] an unverified write is not a recovery"):
    s = Scn("unverified")
    s.warm()
    s.trigger("gone", GONE)
    s.slot()
    txt5 = str(s.sc())
    check("rows that are not there after the commit: STORE_RECORD is WARN and says unverified; the failure counter is untouched, the unverified "
          "counter and the current-failure flag say so", txt5.startswith("WARN") and "unverified" in txt5.lower()
          and s.c.counters["advice_write_failures"] == 0 and s.c.counters.get("advice_unverified_writes") == 1
          and s.c.counters.get("advice_current_failure") == 1 and s.open_().get("reason") == "AdviceReadBackMissing", txt5)
    s.slot()
    check("a second unverified write extends the incident, still WARN", s.open_().get("failed_count") == 2 and str(s.sc()).startswith("WARN")
          and s.c.counters.get("advice_unverified_writes") == 2 and "advice_incident" not in tables(s.db))
    s.trigger("gone", None)
    s.slot()
    check("a verified write then recovers it: PASS, closed incident kept and persisted, the counters are history",
          s.sc() == "PASS" and len(s.closed_()) == 1 and s.closed_()[0]["reason"] == "AdviceReadBackMissing"
          and len(s.stored()) == 1 and s.c.counters.get("advice_unverified_writes") == 2 and s.c.counters.get("advice_current_failure") == 0)
    s.close()

with guard("[C6] the whole store step raises"):
    real_rc = STORE.RuntimeStateStore.record_cycle
    flag = {"raise": False}

    def maybe_raise(self, *a, **k):
        if flag["raise"]:
            raise OSError(SECRET)
        return real_rc(self, *a, **k)
    s = Scn("step_raises")
    s.warm()
    STORE.RuntimeStateStore.record_cycle = maybe_raise
    try:
        flag["raise"] = True
        s.slot()
        check("the existing WARN text is kept (the class name only) and an incident is opened",
              s.sc() == "WARN: the scorecard step failed: OSError" and bool(s.open_()) and s.open_().get("reason") == "OSError"
              and s.open_().get("failed_count") == 1 and no_secret(s.sc(), s.inc()), str(s.sc()))
        s.slot()
        check("a second failed step extends it", s.open_().get("failed_count") == 2 and s.open_().get("missed_slots") == 2
              and s.c.counters["exceptions"] == 0)
        check("... a failed step is counted only inside the incident: not in advice_write_failures or advice_unverified_writes, which count "
              "the advice log's own failures; the current-failure flag is 1",
              s.c.counters["advice_write_failures"] == 0 and s.c.counters["advice_unverified_writes"] == 0
              and s.c.counters.get("advice_current_failure") == 1, str(s.c.counters))
        flag["raise"] = False
        s.slot()
    finally:
        STORE.RuntimeStateStore.record_cycle = real_rc
    check("a verified write after it recovers: PASS, the incident closed and persisted", s.sc() == "PASS" and len(s.closed_()) == 1
          and s.closed_()[0]["reason"] == "OSError" and len(s.stored()) == 1 and no_secret(s.download()))
    s.close()

with guard("[C7] the whole store step times out"):
    real_rc = STORE.RuntimeStateStore.record_cycle
    gate = threading.Event()
    flag = {"hang": False}

    def maybe_hang(self, *a, **k):
        if flag["hang"]:
            gate.wait(20.0)
        return real_rc(self, *a, **k)
    s = Scn("step_times_out")
    s.warm()
    STORE.RuntimeStateStore.record_cycle = maybe_hang
    try:
        flag["hang"] = True
        s.c.time_budget_s = 3.0
        s.slot()
        gate.set()
        h.run(asyncio.sleep(0.5))
        s.c.time_budget_s = COORD.PROPOSED_TIME_BUDGET_S
        check("the existing WARN text is kept and an incident is opened with the class name TimeoutError",
              s.sc() == "WARN: the scorecard step exceeded the time budget" and bool(s.open_())
              and s.open_().get("reason") == "TimeoutError", f"{s.sc()} {s.inc().get('open')}")
        check("... a timed-out step is counted only inside the incident: not in advice_write_failures or advice_unverified_writes",
              s.c.counters["advice_write_failures"] == 0 and s.c.counters["advice_unverified_writes"] == 0
              and s.c.counters.get("advice_current_failure") == 1, str(s.c.counters))
        flag["hang"] = False
        s.slot()
    finally:
        STORE.RuntimeStateStore.record_cycle = real_rc
        gate.set()
    check("a verified write after it recovers", s.sc() == "PASS" and len(s.closed_()) == 1)
    s.close()

with guard("[C8] a cycle with no advice to write is neutral"):
    real_rc = STORE.RuntimeStateStore.record_cycle
    flag = {"empty": False}

    def maybe_empty(self, report, slot_utc, now, history=None, cfg=None, advice=None, dump_duration_min=None):
        return real_rc(self, report, slot_utc, now, history, cfg, {} if flag["empty"] else advice, dump_duration_min)
    s = Scn("neutral")
    s.warm()
    STORE.RuntimeStateStore.record_cycle = maybe_empty
    try:
        flag["empty"] = True
        s.slot()
        check("while healthy it neither recovers nor fails: PASS stays, no incident", s.sc() == "PASS" and not s.open_()
              and s.c.counters["advice_write_failures"] == 0 and len(s.rows()) == 2)
        flag["empty"] = False
        s.trigger("boom", BOOM)
        s.slot()
        before = (s.sc(), dict(s.open_()))
        flag["empty"] = True
        s.slot()
        check("while failing it neither recovers nor fails: WARN stays as it was and the incident is unchanged",
              s.sc() == before[0] and s.open_() == before[1], f"{s.sc()} {s.open_()} {before}")
        flag["empty"] = False
        s.trigger("boom", None)
        s.slot()
    finally:
        STORE.RuntimeStateStore.record_cycle = real_rc
    check("a verified write then recovers it", s.sc() == "PASS" and len(s.closed_()) == 1)
    s.close()

with guard("[C9] a restart never assumes health"):
    s = Scn("restart_open")
    s.warm()
    s.trigger("boom", BOOM)
    s.slot()
    s.slot()
    check("before the restart: an open incident of two missed slot cycles", s.open_().get("missed_slots") == 2)
    s.close()
    cfg_r = s.cfg
    sql(cfg_r / "ecco" / "intelligence" / "state" / "scorecard.sqlite3", "DROP TRIGGER boom")
    s2 = Scn("restart_open", cfg=cfg_r, now=h.now + timedelta(minutes=10))
    check("a new coordinator starts with no incident in memory, is not failing, has verified nothing and records no STORE_RECORD yet",
          s2.inc().get("open") is None and s2.inc().get("closed") == [] and s2.inc().get("current_failure") is False
          and s2.inc().get("verified_writes") == 0 and s2.sc() is None and s2.c.counters.get("advice_write_failures") == 0, str(s2.inc()))
    check("... the incident the old process never closed was never persisted: it is lost, with only the logged warning left",
          "advice_incident" not in tables(s2.db) and s2.stored() == [])
    s2.warm()
    check("PASS only after its own first verified write", s2.sc() == "PASS" and s2.inc().get("verified_writes") == 1)
    d = s2.download()
    check("the download after the restart: nothing stored, nothing open", stored_of(d).get("incidents") == []
          and (d.get("advice_incidents") or {}).get("open") is None)
    s2.close()

    s3 = Scn("restart_closed")
    s3.warm()
    s3.trigger("boom", BOOM)
    s3.slot()
    s3.trigger("boom", None)
    s3.slot()
    check("before the restart: one closed, persisted incident", len(s3.stored()) == 1 and len((s3.inc().get("closed") or [])) == 1)
    s3.close()
    s4 = Scn("restart_closed", cfg=s3.cfg, now=h.now + timedelta(minutes=10))
    check("after the restart the new coordinator's memory is empty and its health is not assumed", s4.closed_() == []
          and s4.sc() is None and s4.inc().get("verified_writes") == 0)
    d4 = s4.download()
    check("... yet the earlier incident is still there for diagnosis: the download lists it from the table, with its counts and its class name",
          len(stored_of(d4).get("incidents", [])) == 1 and stored_of(d4).get("incidents", [{}])[0].get("reason") == "IntegrityError"
          and stored_of(d4).get("incidents", [{}])[0].get("failed_count") == 1 and no_secret(d4), str(stored_of(d4)))
    s4.warm()
    check("PASS only after its own first verified write; the earlier incident is neither lost nor written twice",
          s4.sc() == "PASS" and len(s4.stored()) == 1)
    s4.close()

with guard("[C10] the download never fails for the incident read"):
    s = Scn("download")
    s.warm()
    s.trigger("boom", BOOM)
    s.slot()
    s.trigger("boom", None)
    s.slot()
    real_adv = STORE.RuntimeStateStore.advice_incidents

    def broken(self):
        raise sqlite3.OperationalError(SECRET)
    STORE.RuntimeStateStore.advice_incidents = broken
    try:
        d = s.download()
    finally:
        STORE.RuntimeStateStore.advice_incidents = real_adv
    check("a failing read of the stored incidents gives a small block with the class name only; the rest of the download is intact",
          d["loaded"] is True and stored_of(d).get("status") == "ERROR"
          and stored_of(d).get("error_type") == "OperationalError" and no_secret(d) and "self_test" in d and "counters" in d,
          str(stored_of(d)))
    check("the next download reads again", stored_of(s.download()).get("status") == "OK")
    s.close()

with guard("[C11] N slot cycles through the real engine are N rows of each kind"):
    s = Scn("engine", engine=None)
    s.warm()
    for _ in range(2):
        s.slot()
    rows_e = s.rows()
    check("three slot cycles of the real vendored engine: two rows each, all verified, STORE_RECORD PASS, no incident",
          len(rows_e) == 6 and s.sc() == "PASS" and s.inc().get("verified_writes") == 3 and s.inc().get("open") is None
          and s.c.counters["slot_runs_started"] == 3, f"{len(rows_e)} {s.sc()} {s.inc()}")
    per_kind = {k_: [r[2] for r in rows_e if r[0] == k_] for k_ in ("charge_target", "dump_to_grid")}
    check("... three rows of each kind, and at least one kind logged the identical advice (the same content hash) more than once, so a "
          "deduplicating write would have dropped rows",
          all(len(v) == 3 for v in per_kind.values()) and any(len(set(v)) < 3 for v in per_kind.values()), str(per_kind))
    s.close()

# =====================================================================================================================
print("== [C12] to [C14]: AFTER a verified write, the persist of the closed incident fails, times out or raises")
# The coordinator hands a closed incident to the store only right after a VERIFIED advice write (coordinator._persist_incidents). That
# call has its own isolation: whatever happens in it must be visible only in the persist's own record (last_persist), must not turn the
# store step into a failure, must not change STORE_RECORD (PASS) or any published value, and must leave the incident pending so that the
# next verified write offers it again. A reference run of the identical sequence with a good incident table is the yardstick.
COUNTER_KEYS = ("exceptions", "budget_exceeded", "advice_write_failures", "advice_unverified_writes", "advice_current_failure")
AFTER_ONE_FAILURE = {"exceptions": 0, "budget_exceeded": 0, "advice_write_failures": 1, "advice_unverified_writes": 0,
                     "advice_current_failure": 0}


def mark(s: Scn) -> dict:
    """What a slot cycle left behind: the published entities, STORE_RECORD, the health ledger's outcome and counts, the counters."""
    led = s.inc()
    return {"ents": s.ents(), "sc": s.sc(), "outcome": led.get("last_outcome"), "attempts": led.get("attempts"),
            "failing": led.get("current_failure"), "ctr": {k_: s.c.counters.get(k_) for k_ in COUNTER_KEYS}}


def held(marks: list, ref: list, k: int) -> tuple[bool, str]:
    """Slot cycle k (1-based) shows no trace of a persist problem outside the persist's own record: the published entities and the
    STORE_RECORD level are those of the reference run, STORE_RECORD is PASS, the cycle is a VERIFIED advice cycle (not a step failure:
    one attempt per slot cycle), nothing is failing, no cycle exception or budget overrun, and the cumulative counters are exactly what
    the one real advice failure of cycle 2 left."""
    m, r = marks[k - 1], ref[k - 1]
    diff = sorted(e for e in set(m["ents"]) | set(r["ents"]) if m["ents"].get(e) != r["ents"].get(e))
    ok = (not diff and m["sc"] == r["sc"] == "PASS" and m["outcome"] == "VERIFIED" and m["attempts"] == k and m["failing"] is False
          and m["ctr"] == AFTER_ONE_FAILURE)
    return ok, f"cycle {k}: entities differ {diff[:3]}; {m['sc']!r} vs {r['sc']!r}; {m['outcome']} {m['attempts']} {m['failing']} {m['ctr']}"


def run_to_failure(s: Scn, marks: list) -> None:
    """Cycle 1 (verified), cycle 2 (the advice write fails: an incident opens). The fault is cleared at the end, so the next slot cycle
    is the verified write that closes the incident and offers it for persisting."""
    s.warm()
    marks.append(mark(s))
    s.trigger("boom", BOOM)
    s.slot()
    marks.append(mark(s))
    s.trigger("boom", None)


def odd_incident_table(scn) -> None:
    """An advice_incident table of another shape, in a scorecard file that exists before the integration starts."""
    d = scn.cfg / "ecco" / "intelligence" / "state"
    d.mkdir(parents=True, exist_ok=True)
    sql(d / "scorecard.sqlite3", "CREATE TABLE advice_incident (foo TEXT)", "INSERT INTO advice_incident VALUES ('x')")


def incident_table_shape(path: Path):
    """(column names, rows) of the advice_incident table, read-only; None when the table does not exist."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        cols = [r_[1] for r_ in con.execute("PRAGMA table_info(advice_incident)")]
        return (cols, con.execute("SELECT * FROM advice_incident").fetchall()) if cols else None
    finally:
        con.close()


def wait_for(pred, secs: float = 10.0) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        h.run(asyncio.sleep(0.2))
    return bool(pred())


class PersistSpy:
    """Wraps RuntimeStateStore.log_advice_incidents, the call the coordinator makes (on an executor thread) after a verified write.
    Records every call (the incident keys offered, the mode it ran in, its result) and, by `mode`, passes through ("real"), hangs
    until `gate` is set and then runs the real call, a late result ("hang"), or raises ("raise"). restore() puts the real method back."""

    def __init__(self) -> None:
        self.real = STORE.RuntimeStateStore.log_advice_incidents
        self.mode = "real"
        self.gate = threading.Event()
        self.calls: list[dict] = []
        spy = self

        def wrapped(store, incidents, now):
            mode = spy.mode
            rec = {"mode": mode, "keys": [i_.get("first_failed_utc") for i_ in incidents], "result": None}
            spy.calls.append(rec)
            if mode == "hang":
                spy.gate.wait(20.0)
            elif mode == "raise":
                raise OSError(SECRET)
            rec["result"] = spy.real(store, incidents, now)
            return rec["result"]
        STORE.RuntimeStateStore.log_advice_incidents = wrapped

    def restore(self) -> None:
        STORE.RuntimeStateStore.log_advice_incidents = self.real
        self.gate.set()


REF: list = []
with guard("[C12] reference run: the same sequence with a good incident table"):
    s = Scn("persist_ref")
    spy = PersistSpy()
    try:
        run_to_failure(s, REF)
        for _ in range(4):                          # cycles 3 to 6
            s.slot()
            REF.append(mark(s))
    finally:
        spy.restore()
    check("reference, non-vacuity: six slot cycles, every contract entity published, the failed write of cycle 2 is WARN, cycles 3 to 6 are "
          "PASS with one attempt per slot cycle",
          len(REF) == 6 and len(REF[0]["ents"]) == len(C.INTEGRATION_ENTITY_KEYS) and str(REF[1]["sc"]).startswith("WARN")
          and all(REF[i_]["sc"] == "PASS" and REF[i_]["attempts"] == i_ + 1 for i_ in (2, 3, 4, 5)) and REF[1]["ents"] != REF[0]["ents"],
          str([(m_["sc"], m_["attempts"]) for m_ in REF]))
    check("reference, non-vacuity: the incident is persisted at cycle 3 by one persist call and never offered again, once in the table",
          len(spy.calls) == 1 and (spy.calls[0]["result"] or {}).get("persisted") == spy.calls[0]["keys"] and len(spy.calls[0]["keys"]) == 1
          and len(s.stored()) == 1 and all(m_["ctr"] == AFTER_ONE_FAILURE for m_ in REF[2:]), str(spy.calls))
    s.close()

with guard("[C12] the persist FAILS: an advice_incident table of another shape"):
    marks: list = []
    s = Scn("persist_odd", pre=odd_incident_table)
    spy = PersistSpy()
    try:
        run_to_failure(s, marks)
        check("the start-up gate passes with the odd incident table in place, and cycles 1 and 2 are as in the reference run (the table "
              "matters only to the persist)", s.c.selftest.as_dict().get("STORE_WRITABLE") == "PASS" and marks[0]["ents"] == REF[0]["ents"]
              and marks[1]["ents"] == REF[1]["ents"] and marks[1]["sc"] == REF[1]["sc"] and not spy.calls)
        s.slot()                                    # cycle 3: verified write; the incident closes and is offered; the persist fails
        marks.append(mark(s))
        cl3 = s.closed_()
        lp3 = s.inc().get("last_persist") or {}
        key = cl3[0]["first_failed_utc"] if cl3 else None
        check("cycle 3, non-vacuity: a verified write closed the incident and offered exactly it, once, to the store",
              len(cl3) == 1 and cl3[0]["state"] == "CLOSED" and cl3[0]["reason"] == "IntegrityError" and not s.open_()
              and len(spy.calls) == 1 and spy.calls[0]["keys"] == [key], f"{cl3} {spy.calls}")
        check("the persist failure is visible in the persist's own record: its time, nothing persisted, the exception class name only",
              lp3.get("error") == "DatabaseError" and lp3.get("persisted") == 0 and bool(lp3.get("at")) and no_secret(s.inc()), str(lp3))
        ok3, why3 = held(marks, REF, 3)
        check("... and nowhere else: STORE_RECORD stays PASS, the step is a verified one (not a failure), every published entity is "
              "byte-identical to the reference run's, no cycle exception, the failure counters are as before", ok3, why3)
        check("... the incident is still pending: closed, listed in the diagnostics, not marked persisted",
              cl3[0]["persisted"] is False and s.inc().get("current_failure") is False and s.inc().get("verified_writes") == 2, str(cl3))
        check("... the odd table is as it was (one column, one row), the verified rows are in the log (2 + 2) and the failed write's are not",
              incident_table_shape(s.db) == (["foo"], [("x",)]) and len(s.rows()) == 4, str((incident_table_shape(s.db), len(s.rows()))))
        d3 = s.download()
        check("the download still works: the incident is listed from memory, the stored incidents are a small error block with the class "
              "name only, no message, entity id or path", d3["loaded"] is True and len(d3["advice_incidents"]["closed"]) == 1
              and stored_of(d3).get("status") == "ERROR" and stored_of(d3).get("error_type") == "DatabaseError" and no_secret(d3),
              str(stored_of(d3)))
        s.slot()                                    # cycle 4: the next verified write offers the same incident again; it fails again
        marks.append(mark(s))
        lp4 = s.inc().get("last_persist") or {}
        check("the next verified write offers the SAME incident again (a second persist call, the same key), it fails the same way and the "
              "persist record has a later time; still one incident, still pending, nothing duplicated",
              len(spy.calls) == 2 and spy.calls[1]["keys"] == [key] and lp4.get("error") == "DatabaseError" and lp4.get("persisted") == 0
              and str(lp4.get("at")) > str(lp3.get("at")) and len(s.closed_()) == 1 and s.closed_()[0]["persisted"] is False
              and not s.open_() and incident_table_shape(s.db) == (["foo"], [("x",)]), f"{lp3} {lp4} {spy.calls}")
        ok4, why4 = held(marks, REF, 4)
        check("... and again nothing but the persist record shows it (STORE_RECORD PASS, entities as the reference run)", ok4, why4)
        sql(s.db, "DROP TABLE advice_incident")     # the odd table is gone: the state is good again
        s.slot()                                    # cycle 5: the third offer is persisted
        marks.append(mark(s))
        lp5 = s.inc().get("last_persist") or {}
        cl5 = s.closed_()
        st5 = s.stored()
        check("once the odd table is gone, the next verified write persists it: a third persist call with the same key, no error, one "
              "persisted, the ledger marks it persisted",
              len(spy.calls) == 3 and spy.calls[2]["keys"] == [key] and (spy.calls[2]["result"] or {}).get("persisted") == [key]
              and lp5.get("error") is None and lp5.get("persisted") == 1 and len(cl5) == 1 and cl5[0]["persisted"] is True,
              f"{lp5} {spy.calls[2:]}")
        check("... it is in the table exactly once, with the counts, times and class name the ledger has",
              len(st5) == 1 and st5[0]["first_failed_utc"] == key and st5[0]["failed_count"] == cl5[0]["failed_count"]
              and st5[0]["missed_slots"] == cl5[0]["missed_slots"] and st5[0]["reason"] == cl5[0]["reason"] == "IntegrityError"
              and st5[0]["recovered_utc"] == cl5[0]["recovered_utc"] and st5[0]["rows_since"] == cl5[0]["rows_since"], str(st5))
        ok5, why5 = held(marks, REF, 5)
        check("... with STORE_RECORD PASS and the entities of the reference run", ok5, why5)
        s.slot()                                    # cycle 6
        marks.append(mark(s))
        ok6, why6 = held(marks, REF, 6)
        check("a later verified write does not offer it again: still three persist calls, one row, PASS, entities as the reference run",
              len(spy.calls) == 3 and len(s.stored()) == 1 and ok6, why6)
        check("... every verified slot cycle's rows are there (five of six cycles: ten rows) and the failed one's are not", len(s.rows()) == 10,
              str(len(s.rows())))
        check("the download after it: the stored incidents are readable again and hold the one incident", stored_of(s.download()).get("status")
              == "OK" and len(stored_of(s.download()).get("incidents", [])) == 1)
    finally:
        spy.restore()
    s.close()

with guard("[C13] the persist TIMES OUT"):
    marks = []
    s = Scn("persist_timeout")
    spy = PersistSpy()
    try:
        run_to_failure(s, marks)
        spy.mode = "hang"
        s.c.time_budget_s = 4.0                     # the cycle's earlier steps take about a second; the hung persist outlasts the rest
        s.slot()                                    # cycle 3: verified write; the persist call hangs and is abandoned at the time budget
        s.c.time_budget_s = COORD.PROPOSED_TIME_BUDGET_S
        marks.append(mark(s))
        cl3 = s.closed_()
        lp3 = s.inc().get("last_persist") or {}
        key = cl3[0]["first_failed_utc"] if cl3 else None
        check("cycle 3, non-vacuity: the verified write closed the incident, the persist was called with it and had not returned when the "
              "cycle went on (the table does not exist yet)", len(cl3) == 1 and cl3[0]["state"] == "CLOSED" and len(spy.calls) == 1
              and spy.calls[0]["mode"] == "hang" and spy.calls[0]["keys"] == [key] and spy.calls[0]["result"] is None
              and "advice_incident" not in tables(s.db), f"{cl3} {spy.calls}")
        check("the timeout is visible in the persist's own record: the class name TimeoutError, nothing persisted",
              lp3.get("error") == "TimeoutError" and lp3.get("persisted") == 0 and bool(lp3.get("at")), str(lp3))
        ok3, why3 = held(marks, REF, 3)
        check("... and nowhere else: the store step is a verified one, not a failure (no step incident, no budget overrun, no cycle "
              "exception), STORE_RECORD stays PASS, every published entity is byte-identical to the reference run's", ok3, why3)
        check("... the incident is still pending and listed", cl3[0]["persisted"] is False and not s.open_()
              and s.inc().get("current_failure") is False and s.inc().get("verified_writes") == 2, str(cl3))
        spy.mode = "real"
        spy.gate.set()                              # the abandoned job now finishes late and runs the real call
        late = wait_for(lambda: spy.calls[0]["result"] is not None and s.c.counters.get("late_results_discarded") == 1)
        h.run(asyncio.sleep(0.5))
        check("the abandoned job finished late and wrote the incident into the table, but its result is discarded, so the ledger is not told: "
              "it stays pending in memory (the ledger claims only what it was told)",
              late and len(s.stored()) == 1 and s.closed_()[0]["persisted"] is False
              and (s.inc().get("last_persist") or {}).get("error") == "TimeoutError", f"{late} {s.stored()} {s.closed_()}")
        s.slot()                                    # cycle 4: the next verified write offers it again; the real call is idempotent
        marks.append(mark(s))
        lp4 = s.inc().get("last_persist") or {}
        ok4, why4 = held(marks, REF, 4)
        check("the next verified write offers the same incident again (a second persist call, the same key) and it is persisted: no error, "
              "one persisted, the ledger marks it persisted, and the table still holds it exactly once",
              len(spy.calls) == 2 and spy.calls[1]["keys"] == [key] and spy.calls[1]["mode"] == "real"
              and (spy.calls[1]["result"] or {}).get("persisted") == [key] and lp4.get("error") is None and lp4.get("persisted") == 1
              and s.closed_()[0]["persisted"] is True and len(s.stored()) == 1 and s.stored()[0]["first_failed_utc"] == key,
              f"{lp4} {spy.calls[1:]} {s.stored()}")
        check("... with STORE_RECORD PASS and the entities of the reference run", ok4, why4)
        s.slot()                                    # cycle 5
        marks.append(mark(s))
        ok5, why5 = held(marks, REF, 5)
        check("a later verified write does not offer it again: still two persist calls, one row, PASS", len(spy.calls) == 2
              and len(s.stored()) == 1 and ok5, why5)
    finally:
        s.c.time_budget_s = COORD.PROPOSED_TIME_BUDGET_S
        spy.restore()
    s.close()

with guard("[C14] the persist RAISES (the store's own promise never to raise broken)"):
    marks = []
    s = Scn("persist_raises")
    spy = PersistSpy()
    try:
        run_to_failure(s, marks)
        spy.mode = "raise"
        s.slot()                                    # cycle 3
        marks.append(mark(s))
        cl3 = s.closed_()
        lp3 = s.inc().get("last_persist") or {}
        key = cl3[0]["first_failed_utc"] if cl3 else None
        check("cycle 3, non-vacuity: the verified write closed the incident and the persist was called with it and raised",
              len(cl3) == 1 and cl3[0]["state"] == "CLOSED" and len(spy.calls) == 1 and spy.calls[0]["mode"] == "raise"
              and spy.calls[0]["keys"] == [key] and "advice_incident" not in tables(s.db), f"{cl3} {spy.calls}")
        check("the failure is visible in the persist's own record with the class name OSError only, never the message",
              lp3.get("error") == "OSError" and lp3.get("persisted") == 0 and no_secret(s.inc(), s.download()), str(lp3))
        ok3, why3 = held(marks, REF, 3)
        check("... and nowhere else: the store step is a verified one, STORE_RECORD stays PASS, the entities are those of the reference run",
              ok3, why3)
        check("... the incident is still pending and listed", cl3[0]["persisted"] is False and not s.open_()
              and s.inc().get("current_failure") is False, str(cl3))
        spy.mode = "real"
        s.slot()                                    # cycle 4: offered again, persisted
        marks.append(mark(s))
        ok4, why4 = held(marks, REF, 4)
        check("the next verified write offers it again and it is persisted exactly once, with STORE_RECORD PASS and the reference entities",
              len(spy.calls) == 2 and spy.calls[1]["keys"] == [key] and (spy.calls[1]["result"] or {}).get("persisted") == [key]
              and (s.inc().get("last_persist") or {}).get("error") is None and s.closed_()[0]["persisted"] is True
              and len(s.stored()) == 1 and ok4, why4)
    finally:
        spy.restore()
    s.close()

h.loop.close()
H.rmtree_own(root, PREFIX)
check("the temporary directory is removed", not root.exists(), str(root))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the advice-incident suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all advice-incident checks passed")
