#!/usr/bin/env python3
"""The durable advice log wired into the runtime (Ghost step 1): the slot cycle's store step logs what was just published.

The BUILT kit runs under the stand-in Home Assistant with owner-record decisions (synthetic test values) and the real
vendored run_cycle, on identical inputs:
  C  the store step as it was before the wiring (record_cycle called without the advice): the reference outputs;
  A  as shipped: the slot cycle's store step records the published advice in the scorecard's advice_log;
  B  the advice log's write raises (Scorecard.record_advice replaced by a function that raises): caught and counted in
     last_store, nothing raised, every published entity byte-identical to C;
  D  the whole store step raises: every published entity byte-identical to C.
It shows: A's published entity set, states, attributes and contract version equal C's; a normal cycle writes rows (the
charge target with its window, target and reserve; the dump's window unknown because the engine passes no duration); a
store given no advice writes nothing and reports no advice keys; a closed store writes nothing; an identical re-publish
is not logged twice.
Plain script; exits 1 on any failure. Synthetic data only; no network.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
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


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
PREFIX = "ecco_intel_advice_log_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
STORE = importlib.import_module("custom_components.ecco_intelligence.runtime.store")
VEN_SC = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.scorecard")


def run_scenario(name: str, patch=None):
    """One warm slot cycle on the generic owner-decision site file. Returns (entities, counts, last_store, counters, dir)."""
    cfg = root / name
    cfg.mkdir()
    hass = h.new_hass(cfg, NOW)
    hass.states.events = False
    H.write_site(cfg, H.site_profile(decisions=H.owner_decisions()))
    H.seed_fresh_states(hass.states, NOW)
    h.recorder().statistics = H.synthetic_statistics(NOW, days=30)
    entry = h.new_entry()
    restore = patch() if patch is not None else None
    try:
        h.setup(entry)
        c = h.coordinator(entry)
        c.grace_s = 120.0
        for _ in range(3):
            h.set_now(h.now + timedelta(seconds=60))
            H.seed_fresh_states(hass.states, h.now)
            h.tick(0, settle=20.0)
        ents = {eid: (st.state, json.dumps(dict(st.attributes), sort_keys=True, default=str))
                for eid, st in hass.states._states.items() if eid.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel"))}
        last_store = dict(c.last_store)
        counters = dict(c.counters)
        h.unload(entry)
    finally:
        if restore is not None:
            restore()
    cnt = STORE.RuntimeStateStore(str(cfg)).counts()
    check(f"{name}: no stand-in violation, no write attempt", not hass.violations and not hass.write_attempts)
    return ents, cnt, last_store, counters, cfg


def advice_rows(cfg: Path) -> list:
    con = sqlite3.connect(f"file:{(cfg / 'ecco' / 'intelligence' / 'state' / 'scorecard.sqlite3').as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM advice_log ORDER BY kind").fetchall()
    finally:
        con.close()


def strip_advice():
    """record_cycle as before the wiring: the advice arguments are dropped."""
    real = STORE.RuntimeStateStore.record_cycle

    def old(self, report, slot_utc, now, history=None, cfg=None, advice=None, dump_duration_min=None):
        return real(self, report, slot_utc, now, history, cfg)
    STORE.RuntimeStateStore.record_cycle = old
    return lambda: setattr(STORE.RuntimeStateStore, "record_cycle", real)


def raising_record_advice():
    real = VEN_SC.Scorecard.record_advice

    def boom(self, *a, **k):
        raise RuntimeError("synthetic advice-log failure")
    VEN_SC.Scorecard.record_advice = boom
    return lambda: setattr(VEN_SC.Scorecard, "record_advice", real)


def raising_record_cycle():
    real = STORE.RuntimeStateStore.record_cycle

    def boom(self, *a, **k):
        raise OSError("synthetic store failure")
    STORE.RuntimeStateStore.record_cycle = boom
    return lambda: setattr(STORE.RuntimeStateStore, "record_cycle", real)


try:
    print("== C: the store step as before the wiring (reference outputs)")
    ent_c, cnt_c, ls_c, ctr_c, cfg_c = run_scenario("old_store_step", strip_advice)
    check("non-vacuity: every contract entity was published and the cycle completed once",
          len(ent_c) == len(C.INTEGRATION_ENTITY_KEYS) and ctr_c["runs_published"] >= 1 and cnt_c.get("model_runs") == 1,
          f"{len(ent_c)} {ctr_c['runs_published']} {cnt_c}")
    ct_state = ent_c[C.ENTITY_IDS["charge_target"]][0]
    check("non-vacuity: charge_target is OK with a number (so there is advice to log)",
          ct_state not in ("unknown", "unavailable", "None"), str(ct_state))
    check("the reference run wrote no advice rows", len(advice_rows(cfg_c)) == 0)
    check("the reference step reports no advice keys", "advice_rows" not in ls_c, str(ls_c))

    print("== A: as shipped, a normal cycle records the advice")
    ent_a, cnt_a, ls_a, ctr_a, cfg_a = run_scenario("shipped")
    rows = advice_rows(cfg_a)
    kinds = {r["kind"] for r in rows}
    check("rows were written and none failed", "charge_target" in kinds and ls_a.get("advice_rows", 0) >= 1
          and ls_a.get("advice_write_failures") == 0, f"{kinds} {ls_a}")
    ct = next(r for r in rows if r["kind"] == "charge_target")
    check("the charge target row: status OK, a window, a target and an effective reserve",
          ct["status"] == "OK" and ct["window_start_utc"] and ct["target_soc_pct"] is not None
          and ct["effective_reserve_pct"] is not None, str(dict(ct)))
    dumps = [r for r in rows if r["kind"] == "dump_to_grid"]
    check("every logged dump row has an unknown window (the engine passes no intended duration)",
          all(r["window_start_utc"] is None and r["duration_min"] is None for r in dumps), str([dict(r) for r in dumps]))
    check("the scorecard record is unchanged: one run, one slot, no recommendations",
          (cnt_a.get("model_runs"), cnt_a.get("ecco_intel_slots"), cnt_a.get("recommendations"))
          == (cnt_c.get("model_runs"), cnt_c.get("ecco_intel_slots"), cnt_c.get("recommendations")), f"{cnt_a} {cnt_c}")
    check("published entity set, states, attributes and contract version equal the reference run exactly",
          ent_a == ent_c and sorted(ent_a) == sorted(C.ENTITY_IDS[k] for k in C.INTEGRATION_ENTITY_KEYS),
          str({k for k in set(ent_a) | set(ent_c) if ent_a.get(k) != ent_c.get(k)}))
    check("the contract version is the frozen one and is on the published status",
          C.CONTRACT_VERSION == "ecco-intel-entities/1"
          and "ecco-intel-entities/1" in ent_a[C.ENTITY_IDS["status"]][1])
    check("no new coordinator counter appears", set(ctr_a) == set(ctr_c))

    print("== B: the advice log's write raises: caught and counted, outputs identical")
    ent_b, cnt_b, ls_b, ctr_b, cfg_b = run_scenario("advice_write_raises", raising_record_advice)
    check("the failure is counted in last_store, not raised, and the scorecard run is still recorded",
          ls_b.get("advice_write_failures", 0) >= 1 and ls_b.get("recorded") is True and ctr_b["exceptions"] == 0, str(ls_b))
    check("published outputs byte-identical to the reference run", ent_b == ent_c)
    check("no advice rows were written", not cnt_b.get("advice_log"), str(cnt_b))

    print("== D: the whole store step raises: outputs identical")
    ent_d, cnt_d, ls_d, ctr_d, cfg_d = run_scenario("store_raises", raising_record_cycle)
    check("published outputs byte-identical to the reference run", ent_d == ent_c)
    check("no cycle exception was counted (the store step's own guard caught it)", ctr_d["exceptions"] == 0, str(ctr_d))

    print("== the store: no advice, no rows; a closed store writes nothing")
    cfg = root / "unit"
    cfg.mkdir()
    H.write_site(cfg, H.site_profile())
    st = STORE.RuntimeStateStore(str(cfg))
    ok, text = st.try_open()
    out = st.record_cycle(None, NOW, NOW)
    check("a store given no advice logs nothing and reports no advice keys",
          ok and "advice_rows" not in out and "advice_write_failures" not in out and st.counts().get("advice_log") == 0,
          f"{out} {st.counts()}")
    payloads = {"sensor.x": ("OK", {"kind": "charge_target", "status": "OK", "generated_at": NOW.isoformat(),
                                    "valid_until": (NOW + timedelta(minutes=10)).isoformat(), "reason_codes": []},
                            {"advice": {"target_soc_pct": 80.0, "effective_reserve_pct": 20.0,
                                        "window": [NOW.isoformat(), (NOW + timedelta(hours=3)).isoformat()]}})}
    out = st.record_cycle(None, NOW, NOW, advice=payloads)
    check("a given payload set is logged (one charge_target row)",
          out.get("advice_rows") == 1 and st.counts().get("advice_log") == 1, str(out))
    later = NOW + timedelta(minutes=1)
    payloads2 = {"sensor.x": ("OK", {**payloads["sensor.x"][1], "generated_at": later.isoformat()}, payloads["sensor.x"][2])}
    out = st.record_cycle(None, later, later, advice=payloads2)
    check("an identical re-publish while current is not logged again",
          out.get("advice_rows") == 0 and st.counts().get("advice_log") == 1, str(out))
    st.close()
    out = st.record_cycle(None, NOW, NOW, advice=payloads)
    check("a closed store writes nothing", out.get("refused") == "closed" and "advice_rows" not in out, str(out))
finally:
    h.loop.close()
    H.rmtree_own(root, PREFIX)

check("the temporary directory is removed", not root.exists(), str(root))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the runtime advice-log suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime advice-log checks passed")
