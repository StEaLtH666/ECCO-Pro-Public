#!/usr/bin/env python3
"""runtime/store.py, the integration's only writer.

  * writes only under <config>/ecco/intelligence/state/ (the rest of the tree is byte-identical before and after; nothing
    is created above state/, and without ecco/intelligence/ nothing is created at all);
  * the schema version and the PROPOSED retention are recorded (store_meta.json and the scorecard's schema_meta);
  * only a scorecard_report is recorded, once per schedule slot; a report carrying 'recommended' (anywhere) is refused, so
    the scorecard's recommendations table stays empty; a non-SHADOW report is refused;
  * once per slot holds across a crash: a process that dies after the run row was committed leaves the slot claimed (the
    restart records nothing), and one that dies before that commit leaves neither row (the restart records the slot once);
  * the retention bound is enforced; outcome_metrics comes from Scorecard.metrics;
  * after close() nothing more is written; a containment escape (a name with a separator, '..') is refused;
  * the site file and the package files are only read.
Plain script; exits 1 on any failure. Temporary directories are created and removed by this suite.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


from custom_components.ecco_intelligence.runtime import store as S  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402

UTC = timezone.utc
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
PREFIX = "ecco_intel_store_"


def report(issued: datetime, n: int = 2) -> dict:
    """A V1-report-shaped scorecard report (synthetic) with day-load forecast records."""
    recs = []
    for k in range(n):
        t0 = issued + timedelta(hours=1 + 24 * k)
        recs.append({"kind": "load_kwh:day", "unit": "kWh", "horizon_start": t0.isoformat(),
                     "horizon_end": (t0 + timedelta(hours=24)).isoformat(), "p50": 10.0, "p10": 8.0, "p90": 12.0,
                     "confidence": 0.6, "explanation": {"synthetic": True}})
    return {"generated_for": issued.isoformat(), "features": {"synthetic": 1}, "model_version": "intel-test",
            "config_hash": "test", "feature_hash": f"f{issued.timestamp():.0f}", "status": "OK",
            "confidence": {"overall": 0.6}, "mode": "SHADOW", "forecast_records": recs}


root = H.mktemp(PREFIX)
try:
    cfg = root / "config"
    H.write_site(cfg, H.site_profile())
    (cfg / "configuration.yaml").write_text("# synthetic\n", encoding="utf-8")
    (cfg / "custom_components").mkdir()
    before = {k: v for k, v in H.tree_hashes(cfg).items()}

    print("== set-up")
    st = S.RuntimeStateStore(str(cfg))
    ok, text = st.try_open()
    check("the store opens", ok, text)
    meta = json.loads((cfg / "ecco" / "intelligence" / "state" / "store_meta.json").read_text(encoding="utf-8"))
    check("store_meta.json records the schema and its version", meta["schema"] == S.STORE_SCHEMA
          and meta["schema_version"] == S.STORE_SCHEMA_VERSION)
    check("the retention is recorded and labelled PROPOSED", meta["retention_days"] == S.PROPOSED_RETENTION_DAYS
          and meta["retention_label"] == "PROPOSED")
    con = sqlite3.connect(str(cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    sm = dict(con.execute("SELECT key, value FROM schema_meta").fetchall())
    con.close()
    check("the scorecard's schema_meta records the store schema version and the retention",
          sm.get("ecco_intel_store_schema_version") == str(S.STORE_SCHEMA_VERSION)
          and sm.get("ecco_intel_retention_days") == str(S.PROPOSED_RETENTION_DAYS) and sm.get("schema_version") == "1")

    print("== recording")
    slot = NOW.replace(minute=0)
    r1 = st.record_cycle(report(NOW - timedelta(days=3)), slot, NOW)
    check("a scorecard report is recorded", r1["recorded"] and not r1["duplicate_slot"])
    r2 = st.record_cycle(report(NOW - timedelta(days=3)), slot, NOW + timedelta(minutes=5))
    check("the same slot is never recorded twice (restart mid-run)", not r2["recorded"] and r2["duplicate_slot"])
    c = st.counts()
    check("one model run, its forecasts, no recommendation", c["model_runs"] == 1 and c["forecasts"] == 2
          and c["recommendations"] == 0 and c["ecco_intel_slots"] == 1, str(c))
    with_rec = dict(report(NOW - timedelta(days=2)), recommended={"overnight_target": {"recommended_target_soc_pct": 80}})
    for label, rep in (("top-level 'recommended'", with_rec),
                       ("nested 'recommended'", dict(report(NOW - timedelta(days=2)), features={"x": {"recommended": 1}})),
                       ("a non-SHADOW report", dict(report(NOW - timedelta(days=2)), mode="ASSISTED")),
                       ("a non-mapping report", ["not", "a", "report"])):
        try:
            st.record_cycle(rep, slot + timedelta(hours=1), NOW)
            check(f"refused: {label}", False, "recorded")
        except S.StoreError:
            check(f"refused: {label}", True)
    check("still no recommendation row", st.counts()["recommendations"] == 0)
    check("a None report records nothing", not st.record_cycle(None, slot + timedelta(hours=2), NOW)["recorded"])

    print("== once per slot across a crash between the two writes")
    orig_record_run = S.Scorecard.record_run

    class Died(BaseException):
        """A simulated process death (not an Exception, so nothing on the way may swallow it)."""

    def died_after_commit(self, rep):
        out = orig_record_run(self, rep)        # record_run commits its own rows ...
        raise Died("the process died right after record_run committed")

    def died_before_commit(self, rep):
        raise Died("the process died inside record_run, before its commit")

    crash_slot = slot + timedelta(hours=4)
    c0 = st.counts()
    S.Scorecard.record_run = died_after_commit
    try:
        st.record_cycle(report(NOW - timedelta(days=1, hours=2)), crash_slot, NOW)
        check("the simulated death after the commit happened", False)
    except Died:
        pass
    finally:
        S.Scorecard.record_run = orig_record_run
    c1 = st.counts()
    check("died after the commit: the run row and the slot claim are both there", c1["model_runs"] == c0["model_runs"] + 1
          and c1["ecco_intel_slots"] == c0["ecco_intel_slots"] + 1, f"{c0} {c1}")
    again = st.record_cycle(report(NOW - timedelta(days=1, hours=1)), crash_slot, NOW + timedelta(minutes=4))
    c2 = st.counts()
    check("... and the restarted cycle in the same slot records nothing (no second run row)",
          again["duplicate_slot"] and not again["recorded"] and c2["model_runs"] == c1["model_runs"], f"{again} {c2}")
    crash_slot2 = slot + timedelta(hours=5)
    S.Scorecard.record_run = died_before_commit
    try:
        st.record_cycle(report(NOW - timedelta(hours=20)), crash_slot2, NOW)
        check("the simulated death before the commit happened", False)
    except Died:
        pass
    finally:
        S.Scorecard.record_run = orig_record_run
    c3 = st.counts()
    con = sqlite3.connect(str(cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    claimed = con.execute("SELECT COUNT(*) FROM ecco_intel_slots WHERE slot_utc=?", (crash_slot2.isoformat(),)).fetchone()[0]
    con.close()
    check("died before the commit: neither the slot claim nor a run row is left", claimed == 0
          and c3["model_runs"] == c2["model_runs"] and c3["ecco_intel_slots"] == c2["ecco_intel_slots"], f"{claimed} {c3}")
    once = st.record_cycle(report(NOW - timedelta(hours=19)), crash_slot2, NOW + timedelta(minutes=4))
    c4 = st.counts()
    check("... and the restarted cycle records that slot exactly once", once["recorded"]
          and c4["model_runs"] == c3["model_runs"] + 1 and c4["ecco_intel_slots"] == c3["ecco_intel_slots"] + 1, f"{once} {c4}")
    con = sqlite3.connect(str(cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    zero = con.execute("SELECT COUNT(*) FROM ecco_intel_slots WHERE run_id NOT IN (SELECT run_id FROM model_runs) "
                       "AND slot_utc<>?", (crash_slot.isoformat(),)).fetchone()[0]
    con.close()
    check("every completed slot names its run (only the crashed one may keep the placeholder)", zero == 0, str(zero))

    print("== scoring and metrics")
    from intelligence.history import History, HourRecord
    hrs = []
    base = int((NOW - timedelta(days=4)).timestamp()) // 3600 * 3600
    for k in range(24 * 4):
        hr = HourRecord(start=base + k * 3600)
        hr.e["load"] = 0.5
        hrs.append(hr)
    hist = History(hrs)
    out = st.record_cycle(report(NOW - timedelta(days=1), n=1), slot + timedelta(hours=3), NOW, hist, SiteConfig())
    check("pending forecasts are scored against the history", out["scored"] >= 1, str(out))
    m = st.outcome_metrics(NOW)
    check("outcome_metrics: n, MAE and coverage from Scorecard.metrics (7 days)", m is not None and m.n >= 1
          and m.mae_7d is not None and m.mae_7d >= 0, str(m))
    empty = S.RuntimeStateStore(str(root / "nowhere"))
    check("outcome_metrics of a store that does not exist yet is None (nothing is created)",
          empty.outcome_metrics(NOW) is None and not (root / "nowhere").exists())

    print("== retention")
    old_slot = NOW - timedelta(days=S.PROPOSED_RETENTION_DAYS + 30)
    st.record_cycle(report(old_slot), old_slot, old_slot)
    c_old = st.counts()
    removed = st.enforce_retention(NOW)
    c_new = st.counts()
    check("rows older than the retention are removed", removed >= 3 and c_new["model_runs"] == c_old["model_runs"] - 1
          and c_new["ecco_intel_slots"] == c_old["ecco_intel_slots"] - 1, f"{removed} {c_old} {c_new}")
    con = sqlite3.connect(str(cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    oldest = con.execute("SELECT MIN(issued_utc) FROM model_runs").fetchone()[0]
    con.close()
    check("no remaining row is older than the retention bound",
          datetime.fromisoformat(oldest) >= NOW - timedelta(days=S.PROPOSED_RETENTION_DAYS))
    short = S.RuntimeStateStore(str(cfg), retention_days=2)
    runs_before_short = short.counts()["model_runs"]
    short.enforce_retention(NOW)
    con = sqlite3.connect(str(cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    oldest_short = con.execute("SELECT MIN(issued_utc) FROM model_runs").fetchone()[0]
    con.close()
    check("a shorter retention bound is enforced as well (runs older than 2 days removed, the newer ones kept)",
          short.counts()["model_runs"] < runs_before_short and oldest_short is not None
          and datetime.fromisoformat(oldest_short) >= NOW - timedelta(days=2), f"{runs_before_short} {short.counts()} {oldest_short}")
    for bad in (0, -1, 4000, True, 1.5):
        try:
            S.RuntimeStateStore(str(cfg), retention_days=bad)
            check(f"retention {bad!r} refused", False)
        except S.StoreError:
            check(f"retention {bad!r} refused", True)

    print("== containment")
    for name in ("../x", "a/b", "a\\b", "..", ""):
        try:
            st._inside(name)
            check(f"name {name!r} refused", False)
        except S.StoreError:
            check(f"name {name!r} refused", True)
    after = H.tree_hashes(cfg)
    changed = sorted(k for k in set(before) | set(after)
                     if before.get(k) != after.get(k) and not k.startswith("ecco/intelligence/state/"))
    check("only paths under ecco/intelligence/state/ changed", not changed, str(changed))
    check("the site file is untouched", before["ecco/intelligence/site.local.json"] == after["ecco/intelligence/site.local.json"])
    st.close()
    check("after close() nothing more is recorded", st.record_cycle(report(NOW), slot + timedelta(hours=9), NOW).get("refused")
          == "closed")
    try:
        st.open()
        check("after close() open() is refused", False)
    except S.StoreError:
        check("after close() open() is refused", True)

    print("== no parent, nothing created")
    bare = root / "bare"
    bare.mkdir()
    okb, textb = S.RuntimeStateStore(str(bare)).try_open()
    check("without ecco/intelligence/ the store refuses and creates nothing", not okb and not any(bare.iterdir()), textb)

    print("== read-only helpers")
    raw, prob = S.read_site_file(str(cfg))
    check("the site file is read", raw is not None and prob is None)
    raw2, prob2 = S.read_site_file(str(bare))
    check("a missing site file is reported, not created", raw2 is None and prob2 and not (bare / "ecco").exists())
    big = root / "big"
    H.write_site(big, None)
    (big / "ecco" / "intelligence" / "site.local.json").write_bytes(b"{" + b" " * (S.MAX_SITE_FILE_BYTES + 1) + b"}")
    check("an oversized site file is refused", S.read_site_file(str(big))[0] is None)
    hashes = S.hash_package_files(["manifest.json", "../manifest.json", "/etc/x", "runtime/store.py", "nope.py"])
    check("package hashes: inside files hashed, escapes and missing files None",
          hashes["manifest.json"] is not None and hashes["runtime/store.py"] is not None and hashes["../manifest.json"] is None
          and hashes["/etc/x"] is None and hashes["nope.py"] is None)
    check("the source tree has no VENDOR_MANIFEST.json (not a kit)", S.read_package_manifest() is None)
finally:
    H.rmtree_own(root, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime store:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime store checks passed")
