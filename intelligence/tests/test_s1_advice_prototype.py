#!/usr/bin/env python3
"""Intelligence S1 offline advice harness (PROTOTYPE, intelligence/prototypes/s1_advice): deterministic, synthetic, offline tests.

  [1] authority: no network / process / write / actuation path; every report and item is SHADOW and applies nothing
  [2] reuse, not re-implementation: the harness returns exactly what the existing V1.1 advisors return; nothing existing changes
  [3] decision gates D1-D9: an OPEN, invalid or non-synthetic decision withholds every item that depends on it, with no number
  [4] stale / UNKNOWN / future inputs fail closed (SOC, inverter status, history)
  [5] 23 h / 25 h local days: a period crossing a clock change is BLOCKED while D9 is OPEN; a recorded policy is applied
  [6] capacity mismatch withholds the battery arithmetic
  [7] reserve semantics: a 5 % helper never lowers a 40 % planning floor; protection (D2), TOU and Dump stop levels kept apart
  [8] zero floor violations over a seeded sweep
  [9] invalid tariffs and malformed inputs; strict JSON; determinism; CLI; the document
  [10] reconciled onto the shared register (intelligence/site_decisions.py) and periods (intelligence/periods.py): typed
       decisions, I-D9 validated, KEEP_PRE_CUTOVER_LOAD removed, SCALE_UP_ONLY, per-signal I-D6 limits, inverter.healthy,
       the learner's own lookback, apply_to_siteconfig, SYNTHETIC_TEST accepted explicitly; then the review fixes: the
       charge window under the DST rules, a pin for every fix, the effective SiteConfig in every advisor
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import random
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
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


def raises(fn, exc=ValueError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


from intelligence.charge_target import ChargeTargetInputs, advise_charge_target  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.prototypes.s1_advice import fixtures as fx  # noqa: E402
from intelligence.prototypes.s1_advice import harness as H  # noqa: E402
from intelligence.prototypes.s1_advice.__main__ import main as cli_main  # noqa: E402
from intelligence.prototypes.s1_advice.scenario import (DecisionRecord, EventDecl, MockHour, Observation,  # noqa: E402
                                                        ReserveContext, TariffDecl)
from intelligence.site_decisions import (EXCLUDE, EXCLUDE_CHANGED_PERIODS, EXCLUDE_PRE_CUTOVER,  # noqa: E402
                                         NORMALISE_TO_NOMINAL, SCALE_TO_ACTUAL, SCALE_UP_ONLY, CapacityAuthority,
                                         DSTPolicy, Efficiency, HD1Cutover, PlanningFloor, Protection)
from intelligence.timeutil import UTC, local_wall, zone  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "intelligence" / "prototypes" / "s1_advice"
DOC = ROOT / "docs" / "intelligence" / "INTELLIGENCE_S1_OFFLINE_ADVICE_PROTOTYPE.md"
cfg = SiteConfig()
TZ = zone("Europe/London")


def run(sc, **kw):
    return H.run_harness(replace(sc, **kw) if kw else sc)


def st(rep, kind):
    it = rep.item(kind)
    return None if it is None else it.status


def codes(rep, kind):
    it = rep.item(kind)
    return [] if it is None else [b.code for b in it.withheld_because]


def rec(rep, kind):
    it = rep.item(kind)
    return None if it is None or it.advice is None else it.advice.get("recommendation")


SHADOW = fx.example_shadow()
BLOCKED_EX = fx.example_blocked()
r_shadow = run(SHADOW)
r_blocked = run(BLOCKED_EX)

# ---------------------------------------------------------------------------------------------------------------------
section("[1] authority: offline, read-only, SHADOW")
BAD = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho", "ssl",
       "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "subprocess", "os", "pty", "shutil",
       "signal", "threading", "sqlite3", "pathlib", "tempfile", "io"}
VOCAB = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish", "/api/",
         "influx", "ssh ")
ACT = ("write", "send", "press", "arm", "apply", "execute", "actuate", "trigger", "command", "schedule", "publish", "post")
mods = sorted(PKG.glob("*.py"))
check("the prototype package has its modules", {p.name for p in mods} >= {"__init__.py", "__main__.py", "harness.py", "scenario.py",
                                                                          "fixtures.py"}, str([p.name for p in mods]))
for p in mods:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    imps = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imps += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            imps.append(n.module)
    check(f"{p.name}: no network / process / file / thread / database import", not [m for m in imps if m.split(".")[0] in BAD], str(imps))
    check(f"{p.name}: nothing from ecco_core (only intelligence's own modules, relatively)", not [m for m in imps if m.startswith("ecco_core")])
    lits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 300]
    check(f"{p.name}: no control / transport vocabulary in string literals", not [v for v in lits if any(w in v.lower() for w in VOCAB)],
          str([v for v in lits if any(w in v.lower() for w in VOCAB)][:3]))
    calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    check(f"{p.name}: no open / exec / eval / write call", not calls & {"open", "exec", "eval", "system", "popen", "Popen", "__import__",
                                                                     "write_text", "write_bytes", "compile", "urlopen"}, str(calls & {"open"}))
    defs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    check(f"{p.name}: no callable named like an actuation", not [d for d in defs if any(d.lower().lstrip("_").startswith(a) for a in ACT)], str(defs))
    check(f"{p.name}: no async code", not any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree)))
for name, rep in (("shadow", r_shadow), ("blocked", r_blocked)):
    d = rep.to_dict()
    check(f"{name}: the report is SHADOW / applies_nothing and every item too",
          d["mode"] == "SHADOW" and d["applies_nothing"] is True and all(i["mode"] == "SHADOW" and i["applies_nothing"] is True for i in d["items"]))
    check(f"{name}: every V1.1 advice inside is SHADOW / applies_nothing",
          all(i["advice"]["mode"] == "SHADOW" and i["advice"]["applies_nothing"] is True for i in d["items"] if i["advice"]))
    check(f"{name}: the report states it is a PROTOTYPE, not production runtime and not configured policy",
          "PROTOTYPE" in d["notice"] and "not production" in d["notice"] and "not configured policy" in d["notice"] and "D1-D9" in d["notice"])
check("the invariant guard refuses a key that reads like an instruction",
      raises(lambda: H._check_invariants(replace(r_shadow, label="x", data_quality={"apply_now": 1})), AssertionError))
check("the invariant guard refuses a BLOCKED item that carries advice", raises(lambda: H._check_invariants(replace(
    r_shadow, items=(replace(r_shadow.items[0], status="BLOCKED"),))), AssertionError))

# ---------------------------------------------------------------------------------------------------------------------
section("[2] reuse, not re-implementation; nothing existing changes")
h_before = cfg.config_hash()
_ = run(SHADOW)
check("running the harness leaves SiteConfig untouched", cfg.config_hash() == h_before and SiteConfig().user_reserve_soc_pct == 40.0)
check("the scenario's own SiteConfig is not mutated (the effective one is a copy)", SHADOW.cfg == SiteConfig())
dem = H.learn_period.__wrapped__ if hasattr(H.learn_period, "__wrapped__") else None
w0, w1 = H._next_window(SHADOW, TZ)
nxt0, _ = H._window_on(w0.astimezone(TZ).date() + timedelta(days=1), SHADOW, TZ)
states = H._decision_states(SHADOW, [])
cfg_eff, _bad = H._effective_cfg(SHADOW, states, [])
hist, _dq = H._build_history(SHADOW, states, [])
demand, _x, _n = H.learn_period(hist, cfg_eff, w1, nxt0, SHADOW, states, "post-window")
direct = advise_charge_target(cfg_eff, ChargeTargetInputs(now=SHADOW.now, window=(w0, w1), demand=demand, soc_pct=62.0,
                                                          soc_age_s=30.0, ha_reserve_pct=5.0))
check("the charge-target item is exactly the existing advisor's answer (byte-identical JSON)",
      json.dumps(r_shadow.item("charge_target").advice, sort_keys=True) == json.dumps(direct.to_dict(), sort_keys=True))
check("the overnight item is exactly the existing learner's answer", json.dumps(r_shadow.item("overnight_demand").advice, sort_keys=True)
      == json.dumps(demand.to_dict(), sort_keys=True))
check("the V1 summary comes from the V1 engine (its model version) and is shadow", (r_shadow.item("v1_report_summary").advice or {}).get(
    "model_version", "").startswith("intel-v1.0") and r_shadow.item("v1_report_summary").advice["mode"] == "SHADOW")

# ---------------------------------------------------------------------------------------------------------------------
section("[3] decision gates D1-D9")
kinds = ("overnight_demand", "charge_target", "export_event", "dump_to_grid", "v1_report_summary")
check("every decision is OPEN by default and the blocked example withholds every item",
      all(x["status"] == "OPEN" for x in r_blocked.decisions) and all(st(r_blocked, k) == "BLOCKED" for k in kinds))
check("... each naming the open decisions it depends on and carrying no advice",
      all(r_blocked.item(k).advice is None and any(c.startswith("DECISION_") for c in codes(r_blocked, k)) for k in kinds))
check("the SHADOW example (all SYNTHETIC_TEST decisions) produces OK advice for every item",
      all(st(r_shadow, k) == "OK" for k in kinds), str([(k, st(r_shadow, k), codes(r_shadow, k)) for k in kinds]))
check("every item that used a decision says SYNTHETIC_TEST, never an owner decision",
      all(r_shadow.item(k).decision_provenance == "SYNTHETIC_TEST" for k in kinds))
for d in ("D1", "D2", "D3", "D5", "D6", "D8"):
    dec = dict(SHADOW.decisions)
    dec.pop(d)
    r = run(SHADOW, decisions=dec)
    dependent = [k for k in kinds if d in H.GATES[k]]
    independent = [k for k in kinds if d not in H.GATES[k] and k != "v1_report_summary"]
    check(f"{d} OPEN: exactly the items that depend on it are BLOCKED with DECISION_{d}_OPEN",
          all(st(r, k) == "BLOCKED" and f"DECISION_{d}_OPEN" in codes(r, k) for k in dependent)
          and all(st(r, k) != "BLOCKED" or f"DECISION_{d}_OPEN" not in codes(r, k) for k in independent),
          str([(k, st(r, k), codes(r, k)) for k in kinds]))
r_d6 = run(SHADOW, decisions={k: v for k, v in SHADOW.decisions.items() if k != "D6"})
check("D6 OPEN: export and Dump advice are BLOCKED naming DECISION_D6_OPEN (the inverter status has no freshness limit)",
      st(r_d6, "export_event") == "BLOCKED" and "DECISION_D6_OPEN" in codes(r_d6, "export_event")
      and st(r_d6, "dump_to_grid") == "BLOCKED" and "DECISION_D6_OPEN" in codes(r_d6, "dump_to_grid")
      and st(r_d6, "charge_target") == "BLOCKED" and "GRID_CHARGE_LIMIT_UNKNOWN" in codes(r_d6, "charge_target")
      and "DECISION_D6_OPEN" not in codes(r_d6, "charge_target"), str(codes(r_d6, "charge_target")))
owner = dict(SHADOW.decisions)
owner["D1"] = DecisionRecord(fx.synthetic_value("D1", 40.0), provenance="OWNER")
r_own = run(SHADOW, decisions=owner)
check("a decision claiming an unknown provenance ('OWNER') is refused and INVALID",
      any(i.code == "DECISION_PROVENANCE_REFUSED" for i in r_own.issues) and "DECISION_D1_INVALID" in codes(r_own, "charge_target"))
TYPED = {"D1": lambda v: PlanningFloor("INTELLIGENCE_USER_RESERVE", v, True),
         "D2": lambda v: Protection("OWNER_STATEMENT", v, fx.SYNTHETIC_STATEMENT_AT),
         "D3": lambda v: CapacityAuthority("CONFIGURED_HELPER", v),
         "D5": lambda v: Efficiency(v, "fraction", "ROUND_TRIP")}
for d, bad in (("D1", 150.0), ("D1", float("nan")), ("D2", -1.0), ("D3", 0.1), ("D3", True), ("D5", 1.2), ("D5", "0.9")):
    dec = dict(SHADOW.decisions)
    dec[d] = DecisionRecord(TYPED[d](bad))
    r = run(SHADOW, decisions=dec)
    check(f"{d} = {bad!r} is invalid: an issue, and the dependent items are BLOCKED",
          any(i.code == "INVALID_DECISION_VALUE" for i in r.issues) and st(r, "charge_target") == "BLOCKED"
          and f"DECISION_{d}_INVALID" in codes(r, "charge_target"), str(codes(r, "charge_target")))
for bad in (HD1Cutover(datetime(2030, 8, 1), EXCLUDE, EXCLUDE_PRE_CUTOVER), HD1Cutover(datetime(2030, 8, 1, tzinfo=UTC), "X", EXCLUDE_PRE_CUTOVER),
            "2030", {"cutover": datetime(2030, 8, 1, tzinfo=UTC), "policy": "KEEP_PRE_CUTOVER_LOAD"}):
    dec = dict(SHADOW.decisions)
    dec["D8"] = DecisionRecord(bad)
    r = run(SHADOW, decisions=dec)
    check(f"D8 = {bad!r} is invalid and withholds the learning", st(r, "overnight_demand") == "BLOCKED" and "DECISION_D8_INVALID" in codes(r, "overnight_demand"))
r_unk = run(SHADOW, decisions=dict(SHADOW.decisions, D10=DecisionRecord(1)))
check("an unknown decision id is reported", any(i.code == "UNKNOWN_DECISION_ID" for i in r_unk.issues))
excl = dict(SHADOW.decisions)
excl["D8"] = DecisionRecord(HD1Cutover(SHADOW.now - timedelta(days=4), EXCLUDE, EXCLUDE_PRE_CUTOVER))
r_ex = run(SHADOW, decisions=excl)
check("D8 EXCLUDE removes the pre-cut-over load from learning (fewer nights, then INSUFFICIENT_DATA)",
      r_ex.data_quality["pre_cutover_load_excluded"] > 0 and st(r_ex, "overnight_demand") in ("INSUFFICIENT_DATA", "BLOCKED"),
      f"{r_ex.data_quality['pre_cutover_load_excluded']} {st(r_ex, 'overnight_demand')}")

# ---------------------------------------------------------------------------------------------------------------------
section("[4] stale / UNKNOWN / future inputs fail closed")
now = SHADOW.now
r = run(SHADOW, soc=Observation(62.0, now - timedelta(seconds=901)))
check("a SOC 901 s old: export and Dump BLOCKED (STALE_SOC), the charge target (which does not need it) still given",
      "STALE_SOC" in codes(r, "export_event") and "STALE_SOC" in codes(r, "dump_to_grid") and st(r, "charge_target") == "OK")
r = run(SHADOW, soc=Observation(62.0, now - timedelta(seconds=900)))
check("a SOC exactly 900 s old is still fresh", st(r, "dump_to_grid") == "OK")
for label, obs in (("no observed_at", Observation(62.0, None)), ("a naive observed_at", Observation(62.0, datetime(2030, 10, 15, 20))),
                   ("a future observed_at", Observation(62.0, now + timedelta(seconds=30))), ("no SOC at all", None)):
    r = run(SHADOW, soc=obs)
    check(f"SOC with {label}: export and Dump BLOCKED", st(r, "export_event") == "BLOCKED" and st(r, "dump_to_grid") == "BLOCKED",
          str(codes(r, "dump_to_grid")))
for v in (float("nan"), True, "62", -3.0, 101.0):
    r = run(SHADOW, soc=Observation(v, now - timedelta(seconds=10)))
    check(f"SOC value {v!r} is not usable: Dump BLOCKED", st(r, "dump_to_grid") == "BLOCKED")
r = run(SHADOW, inverter_healthy=Observation(True, now - timedelta(seconds=301)))
check("inverter status older than the (synthetic) D6 limit: export BLOCKED", "INVERTER_STATUS" in codes(r, "export_event"))
r = run(SHADOW, inverter_healthy=Observation(False, now - timedelta(seconds=5)))
check("inverter reported unhealthy: export and Dump BLOCKED", "INVERTER_STATUS" in codes(r, "export_event") and "INVERTER_STATUS" in codes(r, "dump_to_grid"))
r = run(SHADOW, inverter_healthy=Observation("ok", now - timedelta(seconds=5)))
check("a non-boolean inverter status is unknown: BLOCKED", "INVERTER_STATUS" in codes(r, "export_event"))
cut = SHADOW.now - timedelta(hours=7)
r = run(SHADOW, hours=tuple(h for h in SHADOW.hours if h.start + timedelta(hours=1) <= cut))
check("history ending 7 h before now: every item BLOCKED (STALE_HISTORY)",
      all(st(r, k) == "BLOCKED" for k in kinds) and "STALE_HISTORY" in codes(r, "overnight_demand")
      and r.data_quality["history_fresh"] is False)
r = run(SHADOW, hours=())
check("no history at all: BLOCKED, no exception", all(st(r, k) == "BLOCKED" for k in kinds))

# ---------------------------------------------------------------------------------------------------------------------
section("[5] 23 h / 25 h local days")
check("the fixture dates are the 2030 UK clock-change days (25 h and 23 h)",
      (local_wall(fx.AUTUMN_2030, 1440, TZ) - local_wall(fx.AUTUMN_2030, 0, TZ)) == timedelta(hours=25)
      and (local_wall(fx.SPRING_2030, 1440, TZ) - local_wall(fx.SPRING_2030, 0, TZ)) == timedelta(hours=23))
for autumn, factor, total in ((True, 24 / 23, 24.0), (False, 22 / 23, 22.0)):
    tag = "autumn (+1 h)" if autumn else "spring (-1 h)"
    r_open = run(fx.example_dst(autumn, None))
    check(f"{tag}: with D9 OPEN the period is BLOCKED (DECISION_D9_OPEN) and so is the charge target",
          all(st(r_open, k) == "BLOCKED" and "DECISION_D9_OPEN" in codes(r_open, k) for k in ("overnight_demand", "charge_target")),
          str([(k, codes(r_open, k)) for k in kinds]))
    check(f"{tag}: the V1 summary (per-hour slots, not period totals) is not gated on D9",
          st(r_open, "v1_report_summary") == "OK" and "D9" not in r_open.item("v1_report_summary").decisions_used)
    for pol in (DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_TO_ACTUAL), DSTPolicy(EXCLUDE_CHANGED_PERIODS, SCALE_TO_ACTUAL)):
        r_pol = run(fx.example_dst(autumn, pol))
        o = rec(r_pol, "overnight_demand")
        check(f"{tag}, D9 {pol.history_rule}+{pol.target_rule}: the flat 1 kWh/h house is planned for its own {total:g} h "
              f"(expected {total:g} kWh), labelled",
              st(r_pol, "overnight_demand") == "OK" and abs(o["expected_kwh"] - total) < 0.01
              and abs(o["clock_change_length_factor"] - round(factor, 4)) < 1e-9
              and any(x["code"] == "CLOCK_CHANGE_SCALED" for x in r_pol.item("overnight_demand").advice["reasons"])
              and "D9" in r_pol.item("overnight_demand").decisions_used, str(o and o.get("expected_kwh")))
# an ordinary period AFTER the change, whose history contains the long period
after = fx.example_dst(True, None)
after = replace(after, now=local_wall(fx.AUTUMN_2030 + timedelta(days=2), 21 * 60, TZ),
                hours=fx.hours_from_history(fx.AUTUMN_2030 - timedelta(days=44), 47, cfg, flat_kwh=1.0))
r_a = run(after)
check("an ordinary target period whose learning history contains the long period, D9 OPEN: BLOCKED (raw totals would be "
      "an unstated policy)", st(r_a, "overnight_demand") == "BLOCKED" and "DECISION_D9_OPEN" in codes(r_a, "overnight_demand")
      and st(r_a, "charge_target") == "BLOCKED", str(codes(r_a, "overnight_demand")))
r_an = run(replace(after, decisions=fx.synthetic_decisions(cfg, D9=DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY))))
check("... and with D9 NORMALISE the long history period is normalised (noted, D9 recorded as used)",
      any("normalised" in n for n in r_an.item("overnight_demand").notes) and "D9" in r_an.item("overnight_demand").decisions_used
      and abs(rec(r_an, "overnight_demand")["expected_kwh"] - 23.0) < 0.01)
std = fx._base(local_wall(fx.AUTUMN_2030 - timedelta(days=1), 21 * 60 + 30, TZ), cfg,
               decisions=fx.synthetic_decisions(cfg, D9=DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY)))
r_std = run(std)
ct = rec(r_std, "charge_target")
check("the 00:30-05:30 window on the autumn change day lasts 6 h (it crosses the change: I-D9 in scope, satisfied here)",
      st(r_std, "charge_target") == "OK" and ct is not None
      and (datetime.fromisoformat(ct["window"][1]) - datetime.fromisoformat(ct["window"][0])) == timedelta(hours=6))
sprg = fx._base(local_wall(fx.SPRING_2030 - timedelta(days=1), 21 * 60 + 30, TZ), cfg,
                decisions=fx.synthetic_decisions(cfg, D9=DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY)))
ct2 = rec(run(sprg), "charge_target")
check("... and 4 h on the spring change day", ct2 is not None and (datetime.fromisoformat(ct2["window"][1]) - datetime.fromisoformat(ct2["window"][0])) == timedelta(hours=4))

# review findings (independent Opus review of the first draft): the repeated autumn hour, in-progress periods
fold_ev = EventDecl(datetime(2030, 10, 27, 0, 30, tzinfo=UTC), datetime(2030, 10, 27, 1, 20, tzinfo=UTC))   # 01:30 BST .. 01:20 GMT
base_dst = fx.example_dst(True, DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY))
for d9, want in ((None, "DECISION_D9_OPEN"), (DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY), "DEMAND_UNKNOWN")):
    sc_ = replace(base_dst, decisions=fx.synthetic_decisions(cfg, D9=d9), events=(fold_ev,))
    try:
        r = run(sc_)
        ok_ = st(r, "export_event") == "BLOCKED" and want in codes(r, "export_event")
        det = str(codes(r, "export_event"))
    except Exception as exc:                     # noqa: BLE001
        ok_, det = False, repr(exc)
    check(f"an event inside the repeated autumn hour (D9 {d9.history_rule if d9 else 'OPEN'}) is BLOCKED ({want}), never an exception",
          ok_, det)
second_0130 = datetime(2030, 10, 27, 1, 30, tzinfo=UTC)       # the second 01:30 local (GMT)
sc_ = replace(base_dst, now=second_0130, dump_duration_min=30.0, decisions=fx.synthetic_decisions(cfg, D9=None),
              hours=fx.hours_from_history(fx.AUTUMN_2030 - timedelta(days=45), 46, cfg, flat_kwh=1.0))
try:
    r = run(sc_)
    ok_ = st(r, "dump_to_grid") == "BLOCKED"
    det = str(codes(r, "dump_to_grid"))
except Exception as exc:                         # noqa: BLE001
    ok_, det = False, repr(exc)
check("`now` inside the repeated hour: the until-refill period is ambiguous and withheld, never an exception", ok_, det)
o = rec(r_shadow, "overnight_demand")
check("the period still in progress at `now` (05:30 today to 00:30 tomorrow) is never learned from: latest learned is yesterday's",
      o["latest_night"] == (SHADOW.now.astimezone(TZ).date() - timedelta(days=1)).isoformat(), o["latest_night"])

# ---------------------------------------------------------------------------------------------------------------------
section("[6] capacity mismatch")
for name, kwh, blocked_ in (("learned", cfg.battery_capacity_kwh * 1.2, True), ("learned", cfg.battery_capacity_kwh * 1.05, False)):
    r = run(SHADOW, capacity_sources=((name, kwh),))
    check(f"a capacity source {kwh / cfg.battery_capacity_kwh - 1:+.0%} from the one in use: battery items "
          f"{'BLOCKED (CAPACITY_MISMATCH)' if blocked_ else 'unaffected'}; learning unaffected",
          (st(r, "charge_target") == "BLOCKED") == blocked_ and ("CAPACITY_MISMATCH" in codes(r, "charge_target")) == blocked_
          and (st(r, "dump_to_grid") == "BLOCKED") == blocked_ and st(r, "overnight_demand") == "OK")
r = run(SHADOW, capacity_sources=(("learned", cfg.battery_capacity_kwh * 1.2),), decisions=dict(SHADOW.decisions, D4=fx.synthetic_record("D4", 25.0)))
check("a (synthetic) D4 band of 25 % accepts a 20 % gap", st(r, "charge_target") == "OK")
r = run(SHADOW, capacity_sources=(("x", float("nan")),))
check("a non-numeric capacity source is a WARN, not a crash", any(i.code == "CAPACITY_SOURCE_INVALID" for i in r.issues))
r = run(SHADOW, decisions=dict(SHADOW.decisions, D3=fx.synthetic_record("D3", 20.0)))
check("the D3 capacity is the one the advisors use", rec(r, "charge_target")["inputs_used"]["battery_capacity_kwh"] == 20.0)

r = run(SHADOW, capacity_sources=(("bms", cfg.battery_capacity_kwh * 0.935),), decisions={k: v for k, v in SHADOW.decisions.items() if k != "D4"})
check("capacity sources supplied while D4 is OPEN: battery items BLOCKED naming DECISION_D4_OPEN (the 8 % proposal is not used silently)",
      all("DECISION_D4_OPEN" in codes(r, k) for k in ("charge_target", "dump_to_grid", "export_event")) and st(r, "overnight_demand") == "OK")
r = run(SHADOW, decisions={k: v for k, v in SHADOW.decisions.items() if k != "D4"})
check("without capacity sources D4 is not a dependency", st(r, "charge_target") == "OK" and "D4" not in r.item("charge_target").decisions_used)

# ---------------------------------------------------------------------------------------------------------------------
section("[7] reserve semantics: 5 % helper vs 40 % planning floor")
res = rec(r_shadow, "charge_target")["reserve"]
check("a 5 % helper does not lower the 40 % planning floor (binding: user_reserve)",
      res["ha_reserve_pct"] == 5.0 and res["effective_pct"] == 40.0 and res["binding"] == "user_reserve", str(res))
sem = {x["role"]: x for x in r_shadow.reserve_semantics}
check("the report keeps the helper, the protection, the TOU floor, the Dump stop and the planning floor apart",
      set(sem) == {"SOFT_PLANNING_FLOOR", "HA_RESERVE_HELPER", "PHYSICAL_PROTECTION", "INVERTER_TOU_SETTING", "FEATURE_STOP_LEVEL", "DERIVED"}
      and "raise-only" in sem["HA_RESERVE_HELPER"]["enforced_by"] and sem["DERIVED"]["value_pct"] == 40.0)
check("with D2 OPEN the protection level is UNKNOWN, never assumed", {x["role"]: x for x in r_blocked.reserve_semantics}[
    "PHYSICAL_PROTECTION"]["value_pct"] is None and "D2 OPEN" in {x["role"]: x for x in r_blocked.reserve_semantics}["PHYSICAL_PROTECTION"]["source"])
r = run(SHADOW, ha_reserve_helper=Observation(60.0, now))
check("a 60 % helper raises the floor (binding: ha_reserve)", rec(r, "charge_target")["reserve"]["effective_pct"] == 60.0
      and rec(r, "charge_target")["reserve"]["binding"] == "ha_reserve")
r = run(SHADOW, decisions=dict(SHADOW.decisions, D2=fx.synthetic_record("D2", 50.0)))
check("a (synthetic) protection level of 50 % above the 40 % floor binds (technical minimum raised, never lowered)",
      rec(r, "charge_target")["reserve"]["effective_pct"] == 50.0 and rec(r, "charge_target")["reserve"]["binding"] == "technical_min")
r = run(SHADOW, decisions=dict(SHADOW.decisions, D1=fx.synthetic_record("D1", 5.0), D2=fx.synthetic_record("D2", 10.0)))
check("a (synthetic) 5 % planning floor with a 10 % protection level plans at 10 %", rec(r, "charge_target")["reserve"]["effective_pct"] == 10.0)
r = run(SHADOW, decisions=dict(SHADOW.decisions, D2=fx.synthetic_record("D2", 2.0)))
check("a protection level below SiteConfig's technical minimum never lowers it", rec(r, "charge_target")["reserve"]["technical_min_pct"] == 10.0)
r1 = run(SHADOW, reserve_context=ReserveContext(tou_slot_floor_pct=5.0, dump_stop_soc_pct=10.0))
check("the TOU slot floor and the Dump stop SOC are reported but change no number",
      json.dumps(rec(r1, "charge_target"), sort_keys=True) == json.dumps(rec(r_shadow, "charge_target"), sort_keys=True)
      and {x["role"]: x for x in r1.reserve_semantics}["FEATURE_STOP_LEVEL"]["value_pct"] == 10.0)

semb = {x["role"]: x for x in r_blocked.reserve_semantics}
check("with D1/D2 OPEN no planning-floor or effective-minimum number is reported (only the shipped default, labelled)",
      semb["SOFT_PLANNING_FLOOR"]["value_pct"] is None and semb["DERIVED"]["value_pct"] is None
      and semb["SOFT_PLANNING_FLOOR"]["shipped_default_pct"] == 40.0 and "not a decision" in semb["SOFT_PLANNING_FLOOR"]["source"])
r = run(SHADOW, decisions=dict(SHADOW.decisions, D2=fx.synthetic_record("D2", 3.0)))
check("a protection level below the 10 % placeholder says the placeholder still binds",
      "still binds" in ({x["role"]: x for x in r.reserve_semantics}["PHYSICAL_PROTECTION"]["note"] or ""))
r = run(SHADOW, ha_reserve_helper=Observation(99.0, now))
check("a 99 % helper pushes the end-of-period floor above 100 %: the charge target carries a SHORTFALL note",
      any("SHORTFALL" in n for n in r.item("charge_target").notes) and rec(r, "charge_target")["binding_constraint"] == "MAX_SOC")

# ---------------------------------------------------------------------------------------------------------------------
section("[8] zero floor violations (seeded sweep)")
rnd = random.Random(20301020)
base = replace(SHADOW, include_v1_summary=False)
viol, n_ok = [], 0
for i in range(60):
    d1, d2 = round(rnd.uniform(0, 80), 1), round(rnd.uniform(0, 60), 1)
    helper = rnd.choice([None, 5.0, round(rnd.uniform(0, 90), 1)])
    soc = round(rnd.uniform(0, 100), 1)
    cap, eff = round(rnd.uniform(8, 60), 1), round(rnd.uniform(0.8, 1.0), 3)
    dec = fx.synthetic_decisions(cfg, D1=d1, D2=d2, D3=cap, D5=eff)
    try:
        r = run(base, decisions=dec, soc=Observation(soc, now - timedelta(seconds=20)),
                ha_reserve_helper=None if helper is None else Observation(helper, now))
    except Exception as exc:                     # noqa: BLE001 - a crash is a failure of this sweep
        viol.append(("crash", i, repr(exc)))
        continue
    floor = max(d1, max(cfg.technical_min_soc_pct, d2), helper or 0.0)
    margin = cfg.soc_safety_margin_pct
    ct = rec(r, "charge_target")
    if ct is not None and st(r, "charge_target") in ("OK", "INSUFFICIENT_DATA"):
        n_ok += 1
        if ct["target_soc_pct"] + 1e-9 < min(cfg.max_soc_pct, floor + margin):
            viol.append(("charge_target", i, ct["target_soc_pct"], floor))
        if abs(ct["effective_reserve_pct"] - floor) > 1e-9:
            viol.append(("reserve", i, ct["effective_reserve_pct"], floor))
    du = rec(r, "dump_to_grid")
    if du is not None and st(r, "dump_to_grid") == "OK" and du.get("dump_advisable"):
        if du["stop_soc_pct"] + 1e-9 < floor + margin or not soc > du["stop_soc_pct"]:
            viol.append(("dump", i, du["stop_soc_pct"], floor, soc))
    ev = rec(r, "export_event")
    if ev is not None and st(r, "export_event") == "OK" and ev.get("export_advised"):
        if ev["soc_at_end_expected_pct"] + 1e-9 < ev["desired_min_pct"] or ev["desired_min_pct"] + 1e-9 < floor + margin:
            viol.append(("event", i, ev["soc_at_end_expected_pct"], ev["desired_min_pct"], floor))
check(f"no advice below max(planning floor, protection, helper) + margin over 60 seeded cases ({n_ok} charge targets given)",
      not viol and n_ok >= 30, str(viol[:4]))

# ---------------------------------------------------------------------------------------------------------------------
section("[9] invalid tariffs, malformed inputs, strict JSON, determinism, CLI, document")
for label, t in (("no tariff", None), ("minute 1440", TariffDecl(30, 1440)), ("a float minute", TariffDecl(30.0, 330)),
                 ("a boolean minute", TariffDecl(True, 330)), ("zero length", TariffDecl(330, 330)), ("NaN rate", TariffDecl(30, 330, import_cheap_p=float("nan"))),
                 ("cheap above peak", TariffDecl(30, 330, import_cheap_p=30.0, import_peak_p=10.0)),
                 ("23 h 30 min window", TariffDecl(0, 1410))):
    r = run(SHADOW, tariff=t)
    check(f"tariff with {label}: every item BLOCKED", all(st(r, k) == "BLOCKED" for k in kinds)
          and any(i.code in ("NO_TARIFF", "INVALID_TARIFF") for i in r.issues), str([(k, st(r, k)) for k in kinds]))
r = run(SHADOW, tariff=TariffDecl(23 * 60 + 30, 5 * 60 + 30))
check("a window crossing midnight (23:30-05:30) cannot be carried by CHARGE_WINDOW_KEY (0 <= start < end <= 1440): the "
      "battery items are BLOCKED (CHARGE_WINDOW_UNKNOWN), a contract-induced capability loss pending CCR-1",
      st(r, "charge_target") == "BLOCKED" and "CHARGE_WINDOW_UNKNOWN" in codes(r, "charge_target")
      and any(i.code == "CHARGE_WINDOW_CROSSES_MIDNIGHT" for i in r.issues) and st(r, "overnight_demand") == "OK",
      str(codes(r, "charge_target")))
r = run(SHADOW, tariff=TariffDecl(30, 330, import_cheap_p=-2.0, import_peak_p=30.0))
check("a negative cheap rate (dynamic tariffs) is accepted", st(r, "charge_target") == "OK")
good = list(SHADOW.hours)
t0 = good[100].start
junk = [None, MockHour(datetime(2030, 9, 1, 3), 1.0), MockHour(t0 + timedelta(minutes=30), 1.0), MockHour(t0, float("nan")),
        MockHour(t0, -1.0), MockHour(t0, True), MockHour(t0, 99.0), MockHour(t0, 1.0, soc_mean=150.0), MockHour(t0, None), "garbage"]
r = run(SHADOW, hours=tuple(good + junk))
check("malformed hour records are excluded and counted, the rest is used, nothing crashes",
      r.data_quality["malformed"] == len(junk) and st(r, "charge_target") == "OK", str(r.data_quality))
dup = good + [good[200], good[201]]
r = run(SHADOW, hours=tuple(dup))
check("a duplicated hour is excluded entirely (both copies) and reported",
      r.data_quality["duplicate_hours"] == 4 and any(i.code == "DUPLICATE_HOURS_EXCLUDED" for i in r.issues))
check("future records are never used (no leakage)", r_shadow.data_quality["future_or_incomplete"] >= 1)
st_dup = H._decision_states(SHADOW, [])
hist_dup, _ = H._build_history(replace(SHADOW, hours=tuple(dup)), st_dup, [])
from intelligence.timeutil import ts as _ts  # noqa: E402
check("... and the duplicated hours are absent from the history used", hist_dup.get(_ts(good[200].start)) is None
      and hist_dup.get(_ts(good[202].start)) is not None)
for bad_prior in (-1.0, 500.0, float("nan"), True):
    try:
        r = run(SHADOW, overnight_prior_kwh=bad_prior)
        ok_ = st(r, "overnight_demand") == "OK" and any("ignored" in n for n in r.item("overnight_demand").notes)
    except Exception:                            # noqa: BLE001
        ok_ = False
    check(f"an invalid overnight prior {bad_prior!r} is ignored with a note, never an exception", ok_)
try:
    r = run(SHADOW, decisions=dict(SHADOW.decisions, D1=40.0))
    ok_ = any(i.code == "DECISION_RECORD_INVALID" for i in r.issues) and "DECISION_D1_INVALID" in codes(r, "charge_target")
except Exception:                                # noqa: BLE001
    ok_ = False
check("a decision that is not a DecisionRecord is refused and INVALID, never an exception", ok_)
check("an unknown decision id is a WARN (it blocks nothing)", [i.severity for i in r_unk.issues if i.code == "UNKNOWN_DECISION_ID"] == ["WARN"])
bad_item = replace(r_shadow.items[1], decisions_used=("D1",))
check("the invariant guard refuses a non-BLOCKED item that rests on an OPEN decision",
      raises(lambda: H._check_invariants(replace(r_blocked, items=(bad_item,))), AssertionError))
check("the invariant guard refuses a non-BLOCKED item using a filled decision without SYNTHETIC_TEST provenance",
      raises(lambda: H._check_invariants(replace(r_shadow, items=(replace(r_shadow.items[1], decision_provenance=None),))), AssertionError))
d7 = {x["id"]: x for x in r_shadow.decisions}["D7"]
check("the report says D7 is not consulted by this prototype", "not consulted" in d7.get("effect", ""))

check("a naive `now` is refused loudly", raises(lambda: run(SHADOW, now=datetime(2030, 10, 15, 21))))
r = run(SHADOW, events=(EventDecl(datetime(2030, 10, 16, 17), datetime(2030, 10, 16, 18)),))
check("a naive event is BLOCKED (INVALID_EVENT)", "INVALID_EVENT" in codes(r, "export_event"))
r = run(SHADOW, events=(EventDecl(now + timedelta(hours=2), now + timedelta(hours=1)),))
check("an inverted event is BLOCKED", "INVALID_EVENT" in codes(r, "export_event"))
for name, sc in (("shadow", SHADOW), ("blocked", BLOCKED_EX), ("dst", fx.example_dst(True, None))):
    a, b = json.dumps(run(sc).to_dict(), sort_keys=True, allow_nan=False), json.dumps(run(sc).to_dict(), sort_keys=True, allow_nan=False)
    check(f"{name}: strict JSON and byte-identical on a second run", a == b)
for ex in ("blocked", "shadow", "dst-open", "dst-normalised"):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_main(["--example", ex])
    out = json.loads(buf.getvalue())
    check(f"CLI --example {ex}: exit 0, JSON, SHADOW", rc == 0 and out["mode"] == "SHADOW" and out["applies_nothing"] is True)
if DOC.is_file():
    doc = DOC.read_text(encoding="utf-8")
    head = " ".join(ln.lstrip("> ").strip() for ln in doc.splitlines()[:14])
    check("the document's header says PROTOTYPE, SHADOW, applies nothing, not production, D1-D9 OPEN",
          all(n in head for n in ("PROTOTYPE", "SHADOW", "applies nothing", "not production", "D1-D9", "OPEN")), head[:300])
    check("the document has the owner decision sheet for D1-D9", all(f"| D{i} |" in doc for i in range(1, 10)))
    check("the document's backtest plan is marked NOT EXECUTED", "NOT EXECUTED" in doc)
    check("the document does not call any unresolved value approved", "approved" not in doc.lower().replace("not approved", "")
          .replace("owner-approved", "").replace("unapproved", ""))
else:
    check("the S1 prototype document exists", False, str(DOC))

# ---------------------------------------------------------------------------------------------------------------------
section("[10] reconciled onto the shared register (site_decisions) and periods")
import intelligence.site_decisions as SD  # noqa: E402
from intelligence.overnight import OvernightSettings  # noqa: E402
from intelligence.prototypes.s1_advice import scenario as SC  # noqa: E402

DUPLICATES = {"DECISION_IDS", "DECISION_TITLES", "D8_POLICIES", "D9_POLICIES", "PROPOSED_CAPACITY_BAND_PCT",
              "HISTORY_ADVISORY_LIMIT_S", "LEARNING_LOOKBACK_DAYS"}
for p in mods:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    bound = {t.id for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
             for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
    check(f"{p.name}: declares none of the register's constants (they come from site_decisions)", not bound & DUPLICATES,
          str(sorted(bound & DUPLICATES)))
check("the scenario's ids, titles and gates are the register's own objects",
      SC.DECISION_IDS is SD.DECISION_IDS and SC.DECISION_TITLES is SD.DECISION_TITLES
      and all(H.GATES[k] == SD.ITEM_GATES["v1_summary" if k == "v1_report_summary" else k] for k in kinds))
src_h = (PKG / "harness.py").read_text(encoding="utf-8")
check("the harness measures periods with intelligence.periods and applies decisions with site_decisions",
      "period_profile" in src_h and "apply_to_siteconfig" in src_h and "freshness_limits" in src_h and "gate(" in src_h)
check("the period wrapper measures 23 h / 25 h with periods.period_profile",
      H._period_lengths(fx.AUTUMN_2030 - timedelta(days=1), 23 * 60, 46 * 60, TZ) == (23.0, 24.0)
      and H._period_lengths(fx.SPRING_2030 - timedelta(days=1), 23 * 60, 46 * 60, TZ) == (23.0, 22.0))
check("every report row carries the I-D display label, the register status and whether it is satisfied",
      [x["label"] for x in r_shadow.decisions] == [f"I-D{i}" for i in range(1, 10)]
      and all(x["satisfied"] is (x["id"] != "D7") for x in r_shadow.decisions)
      and {x["id"]: x for x in r_shadow.decisions}["D7"]["status"] == "OPEN")
r_lab = run(SHADOW, decisions={"I-" + k: v for k, v in SHADOW.decisions.items()})
check("decisions keyed I-D<n> load exactly like D<n>",
      json.dumps(r_lab.to_dict(), sort_keys=True) == json.dumps(r_shadow.to_dict(), sort_keys=True))
r_free = run(SHADOW, decisions=dict(SHADOW.decisions, D1=DecisionRecord(40.0), D5=DecisionRecord("90 %")))
rows_free = {x["id"]: x for x in r_free.decisions}
check("a bare number or free text is never RECORDED: I-D1 and I-D5 are INVALID and the battery items BLOCKED",
      rows_free["D1"]["status"] == "INVALID" and rows_free["D5"]["status"] == "INVALID"
      and all(st(r_free, k) == "BLOCKED" for k in ("charge_target", "export_event", "dump_to_grid", "v1_report_summary")))

# I-D9 validated: an invalid policy is INVALID and BLOCKs (it used to be read as "normalise")
for bad in ("garbage", 42, DSTPolicy("X", SCALE_UP_ONLY), DSTPolicy(NORMALISE_TO_NOMINAL, "Y"), "NORMALISE_PER_HOUR"):
    r = run(SHADOW, decisions=dict(SHADOW.decisions, D9=DecisionRecord(bad)))
    check(f"I-D9 = {bad!r} is INVALID: every learning item BLOCKED (DECISION_D9_INVALID) even on an ordinary day",
          {x["id"]: x for x in r.decisions}["D9"]["status"] == "INVALID"
          and all(st(r, k) == "BLOCKED" and "DECISION_D9_INVALID" in codes(r, k)
                  for k in ("overnight_demand", "charge_target", "export_event", "dump_to_grid"))
          and st(r, "v1_report_summary") == "OK", str([(k, codes(r, k)) for k in kinds]))
r = run(fx.example_dst(True, "garbage"))
check("I-D9 = 'garbage' on the clock-change night: the period is BLOCKED and carries no number",
      st(r, "overnight_demand") == "BLOCKED" and rec(r, "overnight_demand") is None
      and "DECISION_D9_INVALID" in codes(r, "overnight_demand"))

# KEEP_PRE_CUTOVER_LOAD removed; the typed I-D8 policies
check("no prototype module offers KEEP_PRE_CUTOVER_LOAD any more",
      all("KEEP_PRE_CUTOVER_LOAD" not in p.read_text(encoding="utf-8") for p in mods))
cut4 = SHADOW.now - timedelta(days=4)
r = run(SHADOW, decisions=dict(SHADOW.decisions, D8=DecisionRecord(HD1Cutover(cut4, SD.KEEP_NON_EXPORTING_ONLY,
                                                                              SD.KEEP_AFTER_COUNTER_CHECK))))
check("an I-D8 KEEP option without a counter-check evidence reference is INVALID and BLOCKs the learning",
      "DECISION_D8_INVALID" in codes(r, "overnight_demand") and st(r, "charge_target") == "BLOCKED")
r = run(SHADOW, decisions=dict(SHADOW.decisions, D8=DecisionRecord(HD1Cutover(cut4, EXCLUDE, SD.KEEP_AFTER_COUNTER_CHECK,
                                                                              "REC-20300901-counter-check"))))
check("EXCLUDE + KEEP_AFTER_COUNTER_CHECK (with evidence): pre-cut-over load power dropped, the energy counter kept",
      r.data_quality["pre_cutover_load_power_excluded"] > 0 and r.data_quality["pre_cutover_load_excluded"] == 0
      and st(r, "overnight_demand") == "OK", str(r.data_quality))
d8 = SHADOW.decisions["D8"]
check("the fixtures' I-D8 is EXCLUDE + EXCLUDE_PRE_CUTOVER with provenance SYNTHETIC_TEST",
      d8.provenance == "SYNTHETIC_TEST" and d8.value.load_power_policy == EXCLUDE
      and d8.value.load_counter_policy == EXCLUDE_PRE_CUTOVER)
check("every fixture decision is a typed register value with provenance SYNTHETIC_TEST (I-D7 retired, left OPEN)",
      all(rr.provenance == "SYNTHETIC_TEST" and isinstance(rr.value, SD.VALUE_TYPES[k]) for k, rr in SHADOW.decisions.items())
      and "D7" not in SHADOW.decisions)

# I-D9 target rule: SCALE_UP_ONLY unless SCALE_TO_ACTUAL is satisfied
for autumn, total, f_ in ((True, 24.0, round(24 / 23, 4)), (False, 23.0, 1.0)):
    tag = "autumn (+1 h)" if autumn else "spring (-1 h)"
    r_up = run(fx.example_dst(autumn, DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY)))
    o = rec(r_up, "overnight_demand")
    check(f"{tag}, I-D9 SCALE_UP_ONLY: planned at {total:g} kWh (a short period is never scaled down)",
          st(r_up, "overnight_demand") == "OK" and abs(o["expected_kwh"] - total) < 0.01
          and o["clock_change_length_factor"] == f_ and o["clock_change_target_rule"] == SCALE_UP_ONLY,
          str(o and (o.get("expected_kwh"), o.get("clock_change_length_factor"))))
sp_up = rec(run(fx.example_dst(False, DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY))), "charge_target")
sp_act = rec(run(fx.example_dst(False, DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_TO_ACTUAL))), "charge_target")
check("spring: the SCALE_UP_ONLY charge target is never below the SCALE_TO_ACTUAL one",
      sp_up is not None and sp_act is not None and sp_up["target_soc_pct"] >= sp_act["target_soc_pct"])
check("the fixtures' default I-D9 is NORMALISE_TO_NOMINAL + SCALE_UP_ONLY (SYNTHETIC_TEST)",
      SHADOW.decisions["D9"].value == DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY))

# I-D6: a per-signal gate through site_decisions.freshness_limits
FS = dict(fx.SYNTHETIC_FRESHNESS_S)
def with_d6(**lim):
    vals = {k: v for k, v in dict(FS, **lim).items() if v is not None}
    return dict(SHADOW.decisions, D6=DecisionRecord(SD.FreshnessOverrides(vals)))
r = run(SHADOW, decisions=with_d6(**{"inverter.healthy": None}))
check("I-D6 recorded without an inverter.healthy limit: export and Dump BLOCKED (INVERTER_STATUS), not DECISION_D6_OPEN; "
      "the charge target unaffected", "INVERTER_STATUS" in codes(r, "export_event") and "INVERTER_STATUS" in codes(r, "dump_to_grid")
      and "DECISION_D6_OPEN" not in codes(r, "export_event") and st(r, "charge_target") == "OK")
r = run(SHADOW, decisions=with_d6(**{"inverter.healthy": 1200.0}))
check("an inverter.healthy limit above the 900 s ceiling makes I-D6 INVALID: nothing applied, every battery item BLOCKED",
      {x["id"]: x for x in r.decisions}["D6"]["status"] == "INVALID" and "DECISION_D6_INVALID" in codes(r, "export_event")
      and st(r, "charge_target") == "BLOCKED" and "GRID_CHARGE_LIMIT_UNKNOWN" in codes(r, "charge_target"))
r = run(SHADOW, decisions=with_d6(**{"battery.soc": 300.0}), soc=Observation(62.0, now - timedelta(seconds=400)))
check("I-D6 tightens battery.soc to 300 s: a 400 s SOC is not used, export and Dump BLOCKED",
      st(r, "export_event") == "BLOCKED" and st(r, "dump_to_grid") == "BLOCKED"
      and any(i.code == "SOC_NOT_FRESH_UNDER_LIMIT" for i in r.issues))
r = run(SHADOW, decisions=with_d6(**{"limits.max_grid_charge_w": None}))
check("no I-D6 limit for limits.max_grid_charge_w: every battery item BLOCKED (GRID_CHARGE_LIMIT_UNKNOWN), never 8 kW",
      all(st(r, k) == "BLOCKED" and "GRID_CHARGE_LIMIT_UNKNOWN" in codes(r, k)
          for k in ("charge_target", "export_event", "dump_to_grid", "v1_report_summary")) and st(r, "overnight_demand") == "OK")
r = run(SHADOW, ha_reserve_helper=Observation(5.0, now - timedelta(seconds=301)))
check("a reserve helper older than its I-D6 limit: the battery items are BLOCKED (RESERVE_HELPER_NOT_FRESH)",
      all("RESERVE_HELPER_NOT_FRESH" in codes(r, k) for k in ("charge_target", "export_event", "dump_to_grid")))
r = run(SHADOW, decisions=with_d6(**{"history.hourly": 3600.0}),
        hours=tuple(h for h in SHADOW.hours if h.start + timedelta(hours=1) <= SHADOW.now - timedelta(hours=2)))
check("I-D6 tightens history.hourly to 1 h: a history ending 2 h ago is STALE_HISTORY",
      "STALE_HISTORY" in codes(r, "overnight_demand") and r.data_quality["history_limit_s"] == 3600.0)

# inverter.healthy (the register's name), never inverter_status
check("the harness names the inverter input inverter.healthy (never inverter_status)",
      "inverter_status" not in src_h and "inverter_status" not in json.dumps(r_shadow.to_dict())
      and [x["signal"] for x in r_shadow.inputs] == ["battery.soc", "inverter.healthy", "reserve.ha_minimum_soc",
                                                     "limits.max_grid_charge_w"]
      and {x["signal"]: x for x in r_shadow.inputs}["inverter.healthy"]["limit_s"] == 300.0)

# the learner's own lookback (OvernightSettings.lookback_nights), not 40 days
lb = OvernightSettings.from_site(cfg).lookback_nights
late = replace(fx.example_dst(True, None), now=local_wall(fx.AUTUMN_2030 + timedelta(days=33), 21 * 60, TZ),
               hours=fx.hours_from_history(fx.AUTUMN_2030 - timedelta(days=10), 45, cfg, flat_kwh=1.0))
r_late = run(late)
check(f"the learning lookback is OvernightSettings.lookback_nights ({lb}): an ordinary period 33 days after a change, "
      "I-D9 OPEN, is not gated on I-D9", lb == 28 and st(r_late, "overnight_demand") == "OK"
      and "D9" not in r_late.item("overnight_demand").decisions_used, str(codes(r_late, "overnight_demand")))
r_mid = run(replace(late, now=local_wall(fx.AUTUMN_2030 + timedelta(days=20), 21 * 60, TZ)))
check("... while 20 days after the change the learning history still holds the long night: BLOCKED (DECISION_D9_OPEN)",
      st(r_mid, "overnight_demand") == "BLOCKED" and "DECISION_D9_OPEN" in codes(r_mid, "overnight_demand"))

# the fixed DST rule: a boundary in a repeated hour BLOCKs whatever I-D9 says
fold = H._decision_states(base_dst, [])
adv_f, ex_f, _n = H.learn_period(H.History([]), cfg, datetime(2030, 10, 27, 0, 30, tzinfo=UTC), datetime(2030, 10, 27, 1, 20, tzinfo=UTC),
                                 base_dst, fold, "probe")
check("a period starting in the repeated autumn hour, I-D9 satisfied: BLOCKED (DST_BOUNDARY_IN_CHANGED_HOUR)",
      adv_f.status == "BLOCKED" and [b.code for b in adv_f.blocking] == ["DST_BOUNDARY_IN_CHANGED_HOUR"] and ex_f == ("D9",))

# the effective SiteConfig comes only from apply_to_siteconfig (never the example's battery fields or window)
sc_w = replace(SHADOW, tariff=TariffDecl(60, 300, "declared", 7.5, 28.0, 15.0))
cfg_w, _b = H._effective_cfg(sc_w, H._decision_states(sc_w, []), [])
check("the effective SiteConfig takes the grid-charge limit reading and the declared window, never the example 8 kW / window",
      cfg_w is not None and cfg_w.max_grid_charge_kw == fx.SYNTHETIC_GRID_CHARGE_LIMIT_W / 1000.0
      and (cfg_w.cheap_window_start_min, cfg_w.cheap_window_end_min) == (60, 300) and cfg_w.user_reserve_soc_pct == 40.0
      and SiteConfig().max_grid_charge_kw != cfg_w.max_grid_charge_kw)
r = run(SHADOW, grid_charge_limit_w=None)
check("no grid-charge limit reading: the battery items are BLOCKED (GRID_CHARGE_LIMIT_UNKNOWN)",
      all("GRID_CHARGE_LIMIT_UNKNOWN" in codes(r, k) for k in ("charge_target", "export_event", "dump_to_grid")))
hel = dict(SHADOW.decisions, D1=DecisionRecord(PlanningFloor(SD.HA_RESERVE_HELPER, None, True)))
r = run(SHADOW, decisions=hel, ha_reserve_helper=Observation(45.0, now))
check("I-D1 = HA_RESERVE_HELPER with a fresh helper: the helper is the floor (45 %, binding ha_reserve)",
      st(r, "charge_target") == "OK" and rec(r, "charge_target")["reserve"]["effective_pct"] == 45.0
      and rec(r, "charge_target")["reserve"]["binding"] == "ha_reserve")
r = run(SHADOW, decisions=hel, ha_reserve_helper=None)
check("I-D1 = HA_RESERVE_HELPER without a helper reading: BLOCKED (RESERVE_HELPER_NOT_FRESH), never the example 40 %",
      st(r, "charge_target") == "BLOCKED" and "RESERVE_HELPER_NOT_FRESH" in codes(r, "charge_target"))
r = run(SHADOW, decisions=dict(SHADOW.decisions, D2=DecisionRecord(Protection(SD.READ_ONLY_SENSOR_SNAPSHOT))))
check("I-D2 = READ_ONLY_SENSOR_SNAPSHOT without a sensor reading: BLOCKED (PHYSICAL_PROTECTION_UNKNOWN), no placeholder",
      st(r, "charge_target") == "BLOCKED" and "PHYSICAL_PROTECTION_UNKNOWN" in codes(r, "charge_target"))

# SYNTHETIC_TEST accepted explicitly, nothing else
check("the harness refuses to accept any provenance but SYNTHETIC_TEST",
      raises(lambda: H.run_harness(SHADOW, accept_provenance={"OWNER_RECORD"}))
      and raises(lambda: H.run_harness(SHADOW, accept_provenance={"SYNTHETIC_TEST", "CALLER_DECLARATION_UNVERIFIED"})))
check("the report states the accepted provenance", r_shadow.to_dict()["accept_provenance"] == ["SYNTHETIC_TEST"])
r_none = H.run_harness(SHADOW, accept_provenance=frozenset())
check("an empty accepted set accepts nothing: every gated item BLOCKED", all(st(r_none, k) == "BLOCKED" for k in kinds))
r = run(SHADOW, decisions=dict(SHADOW.decisions, D1=DecisionRecord(fx.synthetic_value("D1", 40.0), provenance="OWNER_RECORD")))
check("an OWNER_RECORD is never minted by a scenario: I-D1 INVALID, the battery items BLOCKED",
      "DECISION_D1_INVALID" in codes(r, "charge_target") and {x["id"]: x for x in r.decisions}["D1"]["status"] == "INVALID")
r = run(SHADOW, decisions=dict(SHADOW.decisions, D1=DecisionRecord(fx.synthetic_value("D1", 40.0),
                                                                   provenance="CALLER_DECLARATION_UNVERIFIED")))
check("a known but unaccepted provenance counts as OPEN (DECISION_D1_OPEN; recorded, not satisfied)",
      "DECISION_D1_OPEN" in codes(r, "charge_target") and {x["id"]: x for x in r.decisions}["D1"]["satisfied"] is False)
check("the command line passes accept_provenance={SYNTHETIC_TEST} explicitly",
      "accept_provenance=ACCEPT_PROVENANCE" in (PKG / "__main__.py").read_text(encoding="utf-8"))
if DOC.is_file():
    rows_doc = {ln.split("|")[1].strip(): ln for ln in doc.splitlines() if ln.startswith("| D")}
    check("the document links the S0 input contract and the foundation contract",
          "INTELLIGENCE_S0_INPUT_CONTRACT.md" in doc and "INTELLIGENCE_FOUNDATION_CONTRACT.md" in doc)
    check("the document's D4 row says an OPEN band BLOCKs (no proposal is used) and its D7 row says retired",
          "BLOCK" in rows_doc.get("D4", "") and "used for the cross-check" not in rows_doc.get("D4", "")
          and "retired" in rows_doc.get("D7", "").lower())

# ---------------------------------------------------------------------------------------------------------------------
section("[10] review fixes (part B): the charge window under the DST rules, pins for every fix, the effective SiteConfig")
from intelligence.explain import finite_number as finite_number_  # noqa: E402

BAT = ("charge_target", "export_event", "dump_to_grid", "v1_report_summary")
D9_OK = DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY)


def change_eve(day, d9, tariff):
    """The evening before `day` (a clock-change day), 21:30 local, with a late-evening event whose refill window is the
    one on `day`, a Dump request and a fresh 5 % helper."""
    eve = day - timedelta(days=1)
    now_ = local_wall(eve, 21 * 60 + 30, TZ)
    ev_ = EventDecl(local_wall(eve, 23 * 60, TZ), local_wall(eve, 23 * 60 + 45, TZ))
    return fx._base(now_, cfg, decisions=fx.synthetic_decisions(cfg, D9=d9), tariff=tariff, events=(ev_,),
                    dump_duration_min=60.0, ha_reserve_helper=Observation(5.0, now_ - timedelta(seconds=60)),
                    power_limits=SC.PowerLimits(5.0, 5.0))


# the charge window itself crossing a change puts I-D9 in scope for the charge target (register CONDITIONAL_D9_ITEMS)
W_EX = TariffDecl(30, 330, "declared", 7.5, 28.0, 15.0)
for tag, day in (("autumn (6 h)", fx.AUTUMN_2030), ("spring (4 h)", fx.SPRING_2030)):
    r = run(change_eve(day, None, W_EX))
    check(f"a 00:30-05:30 charge window crossing the {tag} change, I-D9 OPEN: charge_target BLOCKED (DECISION_D9_OPEN), "
          "no number, I-D9 named; the ordinary post-window demand and the V1 summary unaffected",
          st(r, "charge_target") == "BLOCKED" and "DECISION_D9_OPEN" in codes(r, "charge_target")
          and r.item("charge_target").advice is None and "D9" in r.item("charge_target").decisions_used
          and st(r, "overnight_demand") == "OK" and st(r, "v1_report_summary") == "OK",
          str([(k, st(r, k), codes(r, k)) for k in kinds]))
    r = run(change_eve(day, D9_OK, W_EX))
    check(f"... with I-D9 satisfied the {tag} charge target is OK and lists I-D9 among its decisions",
          st(r, "charge_target") == "OK" and "D9" in r.item("charge_target").decisions_used
          and r.item("charge_target").decision_provenance == "SYNTHETIC_TEST")
# the fixed rule: a charge / refill window boundary in the repeated or the missing hour BLOCKs whatever I-D9 says
W_0130 = TariffDecl(90, 330, "declared", 7.5, 28.0, 15.0)
for tag, day in (("repeated autumn hour", fx.AUTUMN_2030), ("missing spring hour", fx.SPRING_2030)):
    for d9 in (D9_OK, None):
        r = run(change_eve(day, d9, W_0130))
        check(f"a 01:30-05:30 window starting in the {tag}, I-D9 {'satisfied' if d9 else 'OPEN'}: charge target, export, "
              "Dump and V1 summary BLOCKED (DST_BOUNDARY_IN_CHANGED_HOUR), no number",
              all(st(r, k) == "BLOCKED" and "DST_BOUNDARY_IN_CHANGED_HOUR" in codes(r, k) and r.item(k).advice is None
                  for k in BAT)
              and (d9 is not None or "DECISION_D9_OPEN" in codes(r, "charge_target")),
              str([(k, st(r, k), codes(r, k)) for k in kinds]))
r = run(change_eve(fx.AUTUMN_2030 - timedelta(days=10), None, W_0130))
check("the same 01:30-05:30 window on an ordinary night: charge target, export and V1 summary OK, no DST blocker",
      all(st(r, k) == "OK" for k in ("charge_target", "export_event", "v1_report_summary"))
      and not any("DST_BOUNDARY_IN_CHANGED_HOUR" in codes(r, k) for k in kinds), str([(k, codes(r, k)) for k in kinds]))
# the fixed rule inside learn_period, for the FIRST occurrence of the repeated hour (no 3600 s mismatch to catch it)
adv_1, ex_1, _n = H.learn_period(H.History([]), cfg, datetime(2030, 10, 27, 0, 30, tzinfo=UTC),
                                 datetime(2030, 10, 27, 6, 0, tzinfo=UTC), base_dst, fold, "probe")
check("a period starting at the first 01:30 of the repeated autumn hour, I-D9 satisfied: BLOCKED, only "
      "DST_BOUNDARY_IN_CHANGED_HOUR", adv_1.status == "BLOCKED"
      and [b.code for b in adv_1.blocking] == ["DST_BOUNDARY_IN_CHANGED_HOUR"] and ex_1 == ("D9",),
      str([b.code for b in adv_1.blocking]))

# I-D8: pre-cut-over means the hour BEGINS before the cut-over; KEEP_NON_EXPORTING_ONLY still drops load power
cut_h = datetime(2030, 10, 11, 20, 0, tzinfo=UTC)
ex_h = run(SHADOW, decisions=dict(SHADOW.decisions, D8=DecisionRecord(HD1Cutover(cut_h, EXCLUDE, EXCLUDE_PRE_CUTOVER))))
ex_30 = run(SHADOW, decisions=dict(SHADOW.decisions, D8=DecisionRecord(HD1Cutover(cut_h + timedelta(minutes=30), EXCLUDE,
                                                                                  EXCLUDE_PRE_CUTOVER))))
check("an I-D8 cut-over at hh:30 also excludes the hour that straddles it (exactly one hour more than at hh:00)",
      ex_30.data_quality["pre_cutover_load_excluded"] == ex_h.data_quality["pre_cutover_load_excluded"] + 1
      and ex_30.data_quality["pre_cutover_load_power_excluded"] == ex_h.data_quality["pre_cutover_load_power_excluded"] + 1,
      f"{ex_h.data_quality['pre_cutover_load_excluded']} {ex_30.data_quality['pre_cutover_load_excluded']}")
r = run(SHADOW, decisions=dict(SHADOW.decisions, D8=DecisionRecord(HD1Cutover(cut4, SD.KEEP_NON_EXPORTING_ONLY,
                                                                              EXCLUDE_PRE_CUTOVER, "REC-20300901-counter-check"))))
check("I-D8 KEEP_NON_EXPORTING_ONLY (with evidence): pre-cut-over load power is still dropped (a mock hour never has a "
      "recorded zero export), and EXCLUDE_PRE_CUTOVER drops the energy",
      {x["id"]: x for x in r.decisions}["D8"]["status"] == "RECORDED"
      and r.data_quality["pre_cutover_load_power_excluded"] > 0 and r.data_quality["pre_cutover_load_excluded"] > 0,
      str(r.data_quality))

# I-D9 with a known but unaccepted provenance on a clock-change night counts as OPEN: no number
unacc = dict(fx.example_dst(True, None).decisions, D9=DecisionRecord(D9_OK, provenance="CALLER_DECLARATION_UNVERIFIED"))
r = run(fx.example_dst(True, None), decisions=unacc)
check("I-D9 recorded with an unaccepted provenance on the clock-change night: BLOCKED (DECISION_D9_OPEN), no number",
      st(r, "overnight_demand") == "BLOCKED" and rec(r, "overnight_demand") is None
      and "DECISION_D9_OPEN" in codes(r, "overnight_demand") and st(r, "charge_target") == "BLOCKED"
      and "DECISION_D9_OPEN" in codes(r, "charge_target"), str(codes(r, "overnight_demand")))

# the reserve helper: out of range vs not fresh
for v in (150.0, True, "45"):
    r = run(SHADOW, ha_reserve_helper=Observation(v, now))
    check(f"a fresh reserve helper {v!r} (not a percentage 0..100): the battery items BLOCKED (RESERVE_HELPER_OUT_OF_RANGE)",
          all(st(r, k) == "BLOCKED" and "RESERVE_HELPER_OUT_OF_RANGE" in codes(r, k)
              and "RESERVE_HELPER_NOT_FRESH" not in codes(r, k) for k in BAT)
          and any(i.code == "RESERVE_HELPER_OUT_OF_RANGE" for i in r.issues), str(codes(r, "charge_target")))
r = run(SHADOW, ha_reserve_helper=Observation(150.0, now - timedelta(seconds=301)))
check("a stale out-of-range helper is reported as not fresh (RESERVE_HELPER_NOT_FRESH)",
      all("RESERVE_HELPER_NOT_FRESH" in codes(r, k) for k in BAT))

# I-D6 without a limit for the tariff window or the helper: never fresh (no default limit is invented)
r = run(SHADOW, decisions=with_d6(**{"tariff.import_rates": None}))
check("I-D6 recorded without a tariff.import_rates limit: every battery item BLOCKED (CHARGE_WINDOW_UNKNOWN), the "
      "overnight demand unaffected", all(st(r, k) == "BLOCKED" and "CHARGE_WINDOW_UNKNOWN" in codes(r, k) for k in BAT)
      and st(r, "overnight_demand") == "OK", str([(k, codes(r, k)) for k in kinds]))
r = run(SHADOW, decisions=with_d6(**{"reserve.ha_minimum_soc": None}), ha_reserve_helper=Observation(5.0, now))
check("I-D6 recorded without a reserve.ha_minimum_soc limit: a helper observed just now is still not fresh "
      "(RESERVE_HELPER_NOT_FRESH on the charge target, export and Dump)",
      all("RESERVE_HELPER_NOT_FRESH" in codes(r, k) for k in ("charge_target", "export_event", "dump_to_grid")))

# I-D4: named when two or more capacity sources are present; the band check is the register's (largest pairwise gap)
r = run(SHADOW, capacity_sources=(("learned", cfg.battery_capacity_kwh * 1.2),),
        decisions=dict(SHADOW.decisions, D4=fx.synthetic_record("D4", 25.0)))
check("with two capacity sources the satisfied I-D4 band is named in decisions_used of every battery item",
      all(st(r, k) == "OK" and "D4" in r.item(k).decisions_used for k in BAT))
a_ = cfg.battery_capacity_kwh
r = run(SHADOW, capacity_sources=(("bms", a_ * 0.95), ("learned", a_ * 1.05)))
check("two sources each within the 8 % band of the capacity in use but about 10 % apart: BLOCKED by the register's "
      "pairwise check (CAPACITY_MISMATCH_BEYOND_BAND), mirrored as CAPACITY_MISMATCH",
      all(st(r, k) == "BLOCKED" and "CAPACITY_MISMATCH_BEYOND_BAND" in codes(r, k) and "CAPACITY_MISMATCH" in codes(r, k)
          for k in BAT), str(codes(r, "charge_target")))


# the effective SiteConfig reaches every advisor: D1 / D3 / D5 and a window all distinct from the SiteConfig example
def distinct(d3):
    return replace(SHADOW, tariff=TariffDecl(60, 270, "declared", 7.5, 28.0, 15.0),
                   decisions=dict(SHADOW.decisions, D1=fx.synthetic_record("D1", 35.0), D3=fx.synthetic_record("D3", d3),
                                  D5=fx.synthetic_record("D5", 0.85)))


ex_cfg = SiteConfig()
FIELDS = ("user_reserve_soc_pct", "battery_capacity_kwh", "round_trip_efficiency", "max_grid_charge_kw",
          "cheap_window_start_min", "cheap_window_end_min")
cfg_d, _b = H._effective_cfg(distinct(20.0), H._decision_states(distinct(20.0), []), [])
check("the distinct scenario's effective SiteConfig differs from the example in every battery field and the window",
      cfg_d is not None and tuple(getattr(cfg_d, f) for f in FIELDS) == (35.0, 20.0, 0.85, 6.0, 60, 270)
      and all(getattr(cfg_d, f) != getattr(ex_cfg, f) for f in FIELDS))
r20, r25 = run(distinct(20.0)), run(distinct(25.0))
check("distinct values: every item OK", all(st(r20, k) == "OK" and st(r25, k) == "OK" for k in kinds),
      str([(k, codes(r20, k)) for k in kinds]))
ct_d = rec(r20, "charge_target") or {}
iu = ct_d.get("inputs_used") or {}
check("distinct values: the charge target uses D3 20 kWh, D5 0.85 (one way its square root) and the declared 01:00-04:30 "
      "window", iu.get("battery_capacity_kwh") == 20.0 and abs(iu.get("eta_one_way", 0.0) - math.sqrt(0.85)) < 1e-4
      and ct_d.get("window") == [local_wall(date(2030, 10, 16), 60, TZ).isoformat(),
                                 local_wall(date(2030, 10, 16), 270, TZ).isoformat()], str(iu))
for k, field in (("export_event", "soc_at_start_pct"), ("dump_to_grid", "keep_soc_pct")):
    a20, a25 = rec(r20, k) or {}, rec(r25, k) or {}
    check(f"distinct values: {k} plans on the effective SiteConfig (reserve 35 % from D1; {field} moves with D3)",
          a20.get("effective_reserve_pct") == 35.0 and (a20.get("reserve") or {}).get("user_reserve_pct") == 35.0
          and finite_number_(a20.get(field)) and finite_number_(a25.get(field)) and a20[field] != a25[field],
          f"{a20.get('effective_reserve_pct')} {a20.get(field)} {a25.get(field)}")
v20, v25 = r20.item("v1_report_summary").advice or {}, r25.item("v1_report_summary").advice or {}
check("distinct values: the V1 summary runs on the effective SiteConfig (floor 35 % from D1; its target moves with D3)",
      v20.get("floor_pct") == 35.0 and v20.get("overnight_target_soc_pct") is not None
      and v20.get("overnight_target_soc_pct") != v25.get("overnight_target_soc_pct"),
      f"{v20.get('floor_pct')} {v20.get('overnight_target_soc_pct')} {v25.get('overnight_target_soc_pct')}")

# the command line: SHADOW example OK under the explicit SYNTHETIC_TEST acceptance; the docstring lists every example
from intelligence.prototypes.s1_advice import __main__ as CLI  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = cli_main(["--example", "shadow"])
out = json.loads(buf.getvalue())
check("CLI --example shadow: every item OK and accept_provenance == ['SYNTHETIC_TEST']",
      rc == 0 and out["accept_provenance"] == ["SYNTHETIC_TEST"] and all(i["status"] == "OK" for i in out["items"])
      and {i["kind"] for i in out["items"]} == set(kinds), str([(i["kind"], i["status"]) for i in out["items"]]))
check("the command line's docstring lists every example", all(f"--example {k}" in (CLI.__doc__ or "") for k in CLI.EXAMPLES))

# the residual divergence from REQUIRED_SIGNALS / REQUIRED_READINGS is stated, not hidden
d7e = {x["id"]: x for x in r_shadow.decisions}["D7"]["effect"]
check("the D7 row names the register's required inputs that export and Dump advice are given without",
      all(w in d7e for w in ("stop.dump_soc_pct", "tariff.export_rates", "Residual divergence")))
if DOC.is_file():
    check("the document states the charge-window DST rules, the REQUIRED_* residual and that the SHADOW fixture equals "
          "the SiteConfig example", "charge window" in doc and "DST_BOUNDARY_IN_CHANGED_HOUR" in doc
          and "REQUIRED_READINGS" in doc and "tariff.export_rates" in doc and "equal the SiteConfig example" in doc)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all S1 advice prototype checks passed")
