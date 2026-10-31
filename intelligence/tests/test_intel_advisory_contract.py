#!/usr/bin/env python3
"""Intelligence foundation: intelligence/advisory_contract.py, the SHADOW output contract `ecco-intel-entities/1`.

  [1] entity ids: ecco_intel_*, unique_id == object id, no overlap with any id or unique_id under home-assistant/
  [2] the envelope refuses anything but SHADOW / applies_nothing; reserved blocks stay null; scorecard_report never
      carries 'recommended'; engine_comparison only with an OK charge_target
  [3] the null rule: STARTING / PAUSED / STALE / SELF_TEST_FAILED publish no number; last_good only unrecorded
  [4] BLOCKED / INSUFFICIENT_DATA items carry no number anywhere; OK items only until valid_until
  [5] status precedence (derive_status)
  [6] golden fixtures regenerate byte-identical; fictional 2030 timestamps; no 13-digit numbers
  [7] byte budget: every entity <= 16 KiB, also for a maximal envelope; recorded / unrecorded name sets
  [8] attribute names drift-checked against ecco_core.bridge.AdvisoryRecord.display_attributes
  [9] CycleInputs, SITE_READING_KEYS and SiteReading; import rules
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import re
import sys
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gen_contract_fixtures as gen  # noqa: E402
from ecco_core.bridge import record  # noqa: E402  (tests may read ecco_core freely)
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.explain import (BLOCKED, INSUFFICIENT, OK, Advice, Blocker, Confidence, ConfidenceFactor,  # noqa: E402
                                  Reason, blocked)

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "intelligence" / "advisory_contract.py"
UTC = timezone.utc


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def numbers(v, path="") -> list[str]:
    """Paths of every JSON number (not bool) inside v."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return []
    if isinstance(v, (int, float)):
        return [path]
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in numbers(x, f"{path}.{k}")]
    if isinstance(v, (list, tuple)):
        return [p for i, x in enumerate(v) for p in numbers(x, f"{path}[{i}]")]
    return [path + "?"]


NOW = gen.NOW
ok_env = gen.synthetic_ok()
blk_env = gen.all_open_blocked()

# ---------------------------------------------------------------------------------------------------------------------
section("[1] entity ids")
check("contract version is ecco-intel-entities/1", ac.CONTRACT_VERSION == "ecco-intel-entities/1")
check("the thirteen entity ids are exactly the contract's",
      dict(ac.ENTITY_IDS) == {"status": "sensor.ecco_intel_status", "charge_target": "sensor.ecco_intel_charge_target",
                              "overnight_demand": "sensor.ecco_intel_overnight_demand", "export_event": "sensor.ecco_intel_export_event",
                              "dump_to_grid": "sensor.ecco_intel_dump_to_grid", "predicted_day_load": "sensor.ecco_intel_predicted_day_load",
                              "pv_tomorrow": "sensor.ecco_intel_pv_tomorrow", "predicted_morning_soc": "sensor.ecco_intel_predicted_morning_soc",
                              "accuracy": "sensor.ecco_intel_accuracy", "data_quality": "sensor.ecco_intel_data_quality",
                              "fresh": "binary_sensor.ecco_intel_fresh", "paused": "input_boolean.ecco_intel_paused",
                              "watchdog_fresh": "binary_sensor.ecco_intel_watchdog_fresh"})
check("unique_id equals the object id for every entity",
      all(ac.UNIQUE_IDS[k] == v.split(".", 1)[1] for k, v in ac.ENTITY_IDS.items()))
check("to_entity_payloads publishes the eleven integration entities (not the two package entities)",
      set(ac.to_entity_payloads(ok_env)) == {ac.ENTITY_IDS[k] for k in ac.INTEGRATION_ENTITY_KEYS} and len(ac.INTEGRATION_ENTITY_KEYS) == 11)
ha_ids, ha_uids = set(), set()
id_re = re.compile(r"\b(?:sensor|binary_sensor|input_boolean|input_number|input_select|input_text|input_datetime|switch|button|"
                   r"number|select|script|automation|template|counter|timer)\.([a-z0-9_]+)")
uid_re = re.compile(r"unique_id\s*:\s*['\"]?([A-Za-z0-9_]+)")
# The ui stream owns these three files: they define the package entities and reference the integration's ids by design, so
# they are the contract's consumers, not an overlap. Every other file under home-assistant/ (the prototypes included) must
# neither define nor mention any ecco_intel_* id.
UI_OWNED = {"home-assistant/packages/ecco_intelligence.yaml", "home-assistant/dashboards/ecco_intelligence.yaml",
            "home-assistant/tests/test_ecco_intelligence_package.py"}
files = [p for p in (ROOT / "home-assistant").rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml", ".json", ".py", ".md", ".js", ".ts")]
scanned = [p for p in files if p.relative_to(ROOT).as_posix() not in UI_OWNED]
mentions = []
contract_id_re = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, set(ac.UNIQUE_IDS.values())), key=len, reverse=True)) + r")\b")
for p in scanned:
    t = p.read_text(encoding="utf-8", errors="replace")
    ha_ids |= {m.group(0) for m in id_re.finditer(t)} | {m.group(1) for m in id_re.finditer(t)}
    ha_uids |= {m.group(1) for m in uid_re.finditer(t)}
    if contract_id_re.search(t):
        mentions.append(p.relative_to(ROOT).as_posix())
check(f"home-assistant/ was scanned (incl. prototypes): {len(scanned)} files outside the ui-owned three, the prototype ids found",
      "ecco_intelligence_status" in ha_uids and len(scanned) > 20
      and any("prototypes" in p.parts for p in scanned), str(len(scanned)))
check("no ecco_intel entity id or unique_id overlaps any id or unique_id under home-assistant/ (outside the ui-owned files)",
      not ({*ac.ENTITY_IDS.values(), *ac.UNIQUE_IDS.values()} & (ha_ids | ha_uids)),
      str({*ac.ENTITY_IDS.values(), *ac.UNIQUE_IDS.values()} & (ha_ids | ha_uids)))
check("only the ui-owned package, dashboard and package test mention any contract entity id (as a whole word)",
      mentions == [], str(mentions[:5]))
check("the prototype keeps its own ecco_intelligence_* ids (no ecco_intel_* prefix collision)",
      all(not u.startswith("ecco_intel_") for u in ha_uids) and "ecco_intelligence_status" in ha_uids)

# ---------------------------------------------------------------------------------------------------------------------
section("[2] SHADOW only; reserved blocks")
check("an envelope with mode ASSISTED / AUTONOMOUS / OFF cannot exist",
      all(raises(lambda m=m: replace(ok_env, mode=m)) for m in ("ASSISTED", "AUTONOMOUS", "OFF", "shadow", None)))
check("an envelope with applies_nothing other than True cannot exist",
      all(raises(lambda a=a: replace(ok_env, applies_nothing=a)) for a in (False, None, 1, "true")))
check("a wrong contract version is refused", raises(lambda: replace(ok_env, contract_version="ecco-intel-entities/2")))
check("drift and calibration are always null in v0.1", raises(lambda: replace(ok_env, drift={"x": 1}))
      and raises(lambda: replace(ok_env, calibration={"x": 1})) and ok_env.drift is None and ok_env.calibration is None)
check("scorecard_report never contains 'recommended' (at any depth)",
      raises(lambda: replace(ok_env, scorecard_report={"recommended": {}}))
      and raises(lambda: replace(ok_env, scorecard_report={"a": [{"recommended": 1}]})))
check("scorecard_report is not published in any entity", "days" not in json.dumps(ac.to_entity_payloads(ok_env)))
check("engine_comparison only when charge_target is OK", raises(lambda: replace(blk_env, engine_comparison={"v1_target_soc_pct": 80.0})))
check("items and forecasts must be exactly the contract's, in order",
      raises(lambda: replace(ok_env, items=ok_env.items[:3])) and raises(lambda: replace(ok_env, items=tuple(reversed(ok_env.items))))
      and raises(lambda: replace(ok_env, forecasts=ok_env.forecasts[:2])))
check("decisions must name every I-D label with a known status", raises(lambda: replace(ok_env, decisions={"I-D1": "OPEN"}))
      and raises(lambda: replace(ok_env, decisions={**ok_env.decisions, "I-D1": "MAYBE"})))
check("non-JSON or non-finite blocks are refused", raises(lambda: replace(ok_env, tariff={"price": float("nan")}))
      and raises(lambda: replace(ok_env, plan={"at": NOW})))
SYN_DS = gen._synthetic_decisions()
SYN_ACC = frozenset({sd.Provenance.SYNTHETIC_TEST})
OK_CT = ac.ItemView("charge_target", ac.ItemStatus.OK, 80.0, gen.VALID, "MEDIUM", (), ("SYNTHETIC_FIXTURE",), {"target_soc_pct": 80.0})


def assemble(items=None, *, decisions=SYN_DS, accept=SYN_ACC, dq="OK", valid_until=gen.VALID, **kw):
    its = items if items is not None else (OK_CT,) + blk_env.items[1:]
    return ac.assemble_envelope(NOW, gen.VERSIONS, items=its, forecasts=blk_env.forecasts, data_quality=dq, decisions=decisions,
                                accept_provenance=accept, paused=False, valid_until=valid_until, **kw)


VERIFIED_TARIFF = {"provenance": "VERIFIED_FROM_INTEGRATION", "window": "01:00-04:30", "price_range": [7.5, 15.0]}
check("assemble_envelope accepts an OK charge_target only with its decisions satisfied under the accepted provenance",
      assemble().status == "OK" and raises(lambda: assemble(decisions=sd.DecisionSet(), accept=sd.DEFAULT_ACCEPT_PROVENANCE))
      and raises(lambda: assemble(accept=sd.DEFAULT_ACCEPT_PROVENANCE)) and raises(lambda: assemble(decisions=SYN_DS.without("D2"))))
_bad9 = sd.DecisionSet({**SYN_DS.decisions, "D9": sd.DecisionSet.from_mapping({"D9": {"value": 42}}, source="test").get("D9")})
check("... and never while a decision that can gate it is INVALID (an INVALID I-D9 out of scope included)",
      raises(lambda: assemble(decisions=_bad9)))
check("... never while data quality is BLOCKED (CALLER_FRESHNESS_DISAGREES and the like)", raises(lambda: assemble(dq="BLOCKED")))
check("... never without a validity covering now: an expired or unbounded OK item, or no envelope validity",
      raises(lambda: assemble((replace(OK_CT, valid_until=NOW - timedelta(seconds=1)),) + blk_env.items[1:]))
      and raises(lambda: assemble((ac.ItemView("charge_target", "OK", 80.0, None),) + blk_env.items[1:]))
      and raises(lambda: assemble(valid_until=None)))
check("a plan block only while charge_target is OK; a value block only with a VERIFIED tariff and an OK charge_target",
      raises(lambda: assemble(blk_env.items, decisions=sd.DecisionSet(), accept=sd.DEFAULT_ACCEPT_PROVENANCE,
                              plan={"precharge_by": None, "headroom_ceiling_pct": 85.0, "reserve_runout_at": None}))
      and raises(lambda: assemble(blk_env.items, tariff=VERIFIED_TARIFF, value={"range_gbp": [0.4, 1.2]}))
      and raises(lambda: assemble(value={"range_gbp": [0.4, 1.2]}))
      and raises(lambda: assemble(tariff={**VERIFIED_TARIFF, "provenance": "TOU_TABLE"}, value={"range_gbp": [0.4, 1.2]}))
      and assemble(tariff=VERIFIED_TARIFF, value={"range_gbp": [0.4, 1.2]}, plan={"headroom_ceiling_pct": 85.0}).status == "OK")
check("tariff prices only with a VERIFIED provenance; a window string alone is allowed",
      raises(lambda: assemble(blk_env.items, decisions=sd.DecisionSet(), tariff={"provenance": "EXAMPLE", "price_range": [7.5, 15.0]}))
      and assemble(blk_env.items, decisions=sd.DecisionSet(), tariff={"provenance": None, "window": "01:00-04:30", "price_range": None}).status == "BLOCKED")
check("the pre-declared blocks carry only their declared keys",
      all(raises(lambda n=n: replace(ok_env, **{n: {"charge_target_pct": 85.0}})) for n in ("tariff", "value", "plan", "accuracy")))
check("accuracy carries measured figures only (finite >= 0, n an int)",
      raises(lambda: replace(ok_env, accuracy={"mae_7d": -1.0})) and raises(lambda: replace(ok_env, accuracy={"n": 7.5}))
      and raises(lambda: replace(ok_env, accuracy={"n": True})) and replace(ok_env, accuracy={"mae_7d": 0.5, "coverage_7d": None, "n": 3}).accuracy["n"] == 3)
_row = {"name": "battery.soc", "age_s": 40.0, "limit_s": 900.0, "status": "fresh"}
check("input_ages rows are exactly {name, age_s, limit_s, status} with a known, unique name: no battery figure can ride along",
      all(raises(lambda r=r: replace(ok_env, input_ages=(r,))) for r in (
          {**_row, "note": 85.0}, {**_row, "name": "charge_target"}, {**_row, "status": "ok"}, {**_row, "age_s": -1.0},
          {**_row, "limit_s": float("nan")}, {k: v for k, v in _row.items() if k != "status"}, "battery.soc"))
      and raises(lambda: replace(ok_env, input_ages=(_row, _row)))
      and replace(ok_env, input_ages=(_row, {**_row, "name": "tou.slot_table", "age_s": None, "limit_s": None, "status": "missing"})).input_ages[1]["status"] == "missing")
check("self_test values are 'PASS' or 'FAIL: ...' strings only",
      raises(lambda: replace(ok_env, self_test={"target_soc_pct": 85})) and raises(lambda: replace(ok_env, self_test={"X": "ok"}))
      and raises(lambda: replace(ok_env, self_test={"": "PASS"})) and replace(ok_env, self_test={"X": "FAIL: y"}).self_test["X"] == "FAIL: y")
check("pv_tomorrow's summary is limited to the PV forecast keys (it is published while decisions are OPEN)",
      raises(lambda: ac.ForecastView("pv_tomorrow", "OK", 4.2, 3.0, 5.0, gen.VALID, "MEDIUM", (), (), {"kwh": 4.2, "charge_target_pct": 85}))
      and ac.ForecastView("pv_tomorrow", "OK", 4.2, 3.0, 5.0, gen.VALID, "MEDIUM", (), (),
                          {"p10": 3.0, "p50": 4.2, "p90": 5.0, "source": "synthetic", "label": "LOW"}).summary["p50"] == 4.2)
_mut_env = copy.copy(ok_env)
object.__setattr__(_mut_env, "mode", "AUTONOMOUS")
_mut_env2 = copy.copy(ok_env)
object.__setattr__(_mut_env2, "applies_nothing", False)
check("to_entity_payloads re-checks SHADOW / applies_nothing: an envelope mutated after construction is never published",
      raises(lambda: ac.to_entity_payloads(_mut_env)) and raises(lambda: ac.to_entity_payloads(_mut_env2)))
check("CycleInputs.accept_provenance is keyword-only: a positional tenth argument cannot set it",
      inspect.signature(ac.CycleInputs).parameters["accept_provenance"].kind == inspect.Parameter.KEYWORD_ONLY
      and ac.CycleInputs(NOW, None, None, (), None, None, None, ac.SiteFacts(), sd.DecisionSet(),
                         frozenset({"SYNTHETIC_TEST"})).accept_provenance == sd.DEFAULT_ACCEPT_PROVENANCE)
check("the pre-declared blocks exist as null by default",
      all(getattr(blk_env, n) is None for n in ("tariff", "value", "plan", "accuracy", "drift", "calibration")))
check("status attributes carry the pre-declared blocks (null) and mode / applies_nothing",
      all(n in ac.to_entity_payloads(blk_env)[ac.ENTITY_IDS["status"]][1] for n in ("tariff", "value", "plan", "accuracy", "drift", "calibration"))
      and ac.to_entity_payloads(blk_env)[ac.ENTITY_IDS["status"]][1]["mode"] == "SHADOW")

# ---------------------------------------------------------------------------------------------------------------------
section("[3] the null rule")
nulls = {"starting": gen.starting(), "paused": gen.paused(), "stale": gen.stale(), "self_test_failed": gen.self_test_failed()}
for name, env in nulls.items():
    pay = ac.to_entity_payloads(env)
    states = {eid: st for eid, (st, _r, _u) in pay.items() if eid not in (ac.ENTITY_IDS["status"], ac.ENTITY_IDS["fresh"])}
    nums = [p for eid, (st, rec, un) in pay.items() for p in numbers({"state": st, "rec": rec, "un": {k: v for k, v in un.items() if k != "last_good"}}, eid)]
    check(f"{name}: status {env.status}, every item / forecast / diagnostic state is None, fresh is False",
          env.status in ac.SystemStatus.NULL and all(v is None for v in states.values()) and pay[ac.ENTITY_IDS["fresh"]][0] is False, str(states))
    check(f"{name}: no number in any state or attribute except the unrecorded last_good", nums == [], str(nums[:5]))
st_pay = ac.to_entity_payloads(nulls["stale"])[ac.ENTITY_IDS["status"]]
check("stale: the last values appear only in the unrecorded last_good {generated_at, values}",
      st_pay[2]["last_good"]["values"] == {"charge_target": 80.0, "overnight_demand": 6.4, "predicted_day_load": 14.2,
                                           "predicted_morning_soc": 72.0, "pv_tomorrow": 9.8}
      and st_pay[2]["last_good"]["generated_at"] == NOW.isoformat() and "last_good" in ac.UNRECORDED_ATTRIBUTES
      and "last_good" not in ac.RECORDED_ATTRIBUTES)
check("a null-rule envelope cannot carry a computed item, accuracy or plan",
      raises(lambda: replace(nulls["paused"], items=ok_env.items)) and raises(lambda: replace(nulls["paused"], accuracy={"mae_7d": 1.0}))
      and raises(lambda: replace(nulls["starting"], plan={"precharge_by": "x"})))
check("no null-rule constructor can carry a tariff block (prices or a window) or a value, plan or engine comparison",
      all(raises(lambda e=e, n=n, b=b: replace(e, **{n: b})) for e in nulls.values()
          for n, b in (("tariff", {"provenance": "EXAMPLE", "window": "00:30-05:30", "price_range": [7.5, 15.0]}),
                       ("tariff", {"provenance": None, "window": "01:00-04:30", "price_range": None}),
                       ("value", {"range_gbp": None}), ("plan", {"precharge_by": None}),
                       ("engine_comparison", {"v1_target_soc_pct": 85.0}))))
pz_prev = ac.with_last_good(nulls["paused"], ok_env)
st_paused = ac.stale_from(pz_prev, NOW + timedelta(hours=2))
check("stale_from with the pause control ON gives PAUSED (PAUSED > STALE), keeping last_good",
      st_paused.status == "PAUSED" and st_paused.pause_control == "ON" and st_paused.last_good is not None
      and ac.stale_from(ok_env, NOW + timedelta(hours=2), paused=True).status == "PAUSED"
      and ac.stale_from(ok_env, NOW + timedelta(hours=2)).status == "STALE", st_paused.status)
nxt = NOW + timedelta(minutes=55)


def _without_next(e) -> dict:
    d = e.to_dict()
    d.pop("next_run_at")
    return d


st_late = nulls["stale"]
nxt_stale = st_late.generated_at + timedelta(minutes=40)
check("with_next_run_at sets next_run_at and nothing else, on a computed and on a STALE envelope, and the status entity "
      "carries it", ac.with_next_run_at(ok_env, nxt).next_run_at == nxt
      and _without_next(ac.with_next_run_at(ok_env, nxt)) == _without_next(ok_env)
      and _without_next(ac.with_next_run_at(st_late, nxt_stale)) == _without_next(st_late)
      and ac.to_entity_payloads(ac.with_next_run_at(st_late, nxt_stale))[ac.ENTITY_IDS["status"]][1]["next_run_at"]
      == nxt_stale.isoformat())
check("with_next_run_at refuses a naive time and a time before the envelope's generated_at",
      raises(lambda: ac.with_next_run_at(ok_env, datetime(2030, 1, 15, 22, 0)))
      and raises(lambda: ac.with_next_run_at(ok_env, ok_env.generated_at - timedelta(seconds=1)))
      and ac.with_next_run_at(ok_env, None).next_run_at is None)
check("last_good is refused outside a null-rule status", raises(lambda: replace(ok_env, last_good={"generated_at": None, "values": {}})))
check("with_last_good copies only OK values", ac.with_last_good(nulls["paused"], blk_env).last_good["values"] == {})
check("a paused cycle cannot be assembled as a computed one",
      raises(lambda: ac.assemble_envelope(NOW, gen.VERSIONS, items=ok_env.items, forecasts=ok_env.forecasts, data_quality="OK",
                                          decisions=sd.DecisionSet(), paused=True)))
miss = ac.assemble_envelope(NOW, gen.VERSIONS, items=blk_env.items, forecasts=blk_env.forecasts, data_quality="OK",
                            decisions=sd.DecisionSet(), paused=None, valid_until=gen.VALID)
check("a missing pause control is not paused: pause_control MISSING with PAUSE_CONTROL_MISSING",
      miss.status == "BLOCKED" and miss.pause_control == "MISSING" and "PAUSE_CONTROL_MISSING" in miss.reason_codes)

# ---------------------------------------------------------------------------------------------------------------------
section("[4] no number for BLOCKED / INSUFFICIENT items; OK only until valid_until")
bp = ac.to_entity_payloads(blk_env)
leak = [p for k in ac.ADVICE_ITEMS + ("predicted_day_load", "predicted_morning_soc", "pv_tomorrow")
        for p in numbers({"state": bp[ac.ENTITY_IDS[k]][0], "rec": bp[ac.ENTITY_IDS[k]][1], "un": bp[ac.ENTITY_IDS[k]][2]}, k)]
check("all_open_blocked: no item or forecast entity carries a number anywhere", leak == [], str(leak))
check("an item view refuses a number, summary or validity unless OK",
      all(raises(lambda s=s: ac.ItemView("charge_target", s, 80.0)) for s in ("BLOCKED", "INSUFFICIENT_DATA", "NO_ADVICE", "WITHHELD"))
      and raises(lambda: ac.ItemView("charge_target", "INSUFFICIENT_DATA", summary={"target_soc_pct": 80.0}))
      and raises(lambda: ac.ForecastView("pv_tomorrow", "BLOCKED", p10=1.0, blockers=(("X", "y"),))))
check("a BLOCKED view names a blocker", raises(lambda: ac.ItemView("charge_target", "BLOCKED")))
conf = Confidence.combine([ConfidenceFactor("x", 0.5, "x")])
ins = Advice("charge_target", INSUFFICIENT, {"target_soc_pct": 90.0, "raw_target_soc_pct": None}, conf, (Reason("NO_DEMAND_EVIDENCE", "x"),))
iv = ac.ItemView.from_advice(ins)
check("from_advice: an INSUFFICIENT fallback recommendation is never published", iv.status == "INSUFFICIENT_DATA" and iv.value is None
      and iv.summary is None and iv.reason_codes == ("NO_DEMAND_EVIDENCE",))
bv = ac.ItemView.from_advice(blocked("charge_target", [Blocker("STALE_SOC", "soc is old")]))
check("from_advice: a BLOCKED advice keeps its blockers only", bv.status == "BLOCKED" and bv.blockers == (("STALE_SOC", "soc is old"),)
      and bv.value is None)
okv = ac.ItemView.from_advice(Advice("charge_target", OK, {"target_soc_pct": 75.0}, conf), valid_until=gen.VALID)
check("from_advice: an OK advice gives its value and summary", okv.value == 75.0 and okv.summary["target_soc_pct"] == 75.0 and okv.valid_until == gen.VALID)
op = ac.to_entity_payloads(ok_env)
check("synthetic_ok: OK items are numeric before valid_until", op[ac.ENTITY_IDS["charge_target"]][0] == 80.0
      and op[ac.ENTITY_IDS["pv_tomorrow"]][0] == 9.8 and op[ac.ENTITY_IDS["fresh"]][0] is True)
late = ac.to_entity_payloads(ok_env, now=gen.VALID + timedelta(seconds=1))
late_leak = [p for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS for p in numbers({"s": late[ac.ENTITY_IDS[k]][0], "r": late[ac.ENTITY_IDS[k]][1],
                                                                              "u": late[ac.ENTITY_IDS[k]][2]}, k)]
check("after valid_until no item or forecast publishes a number and fresh is False", late_leak == [] and late[ac.ENTITY_IDS["fresh"]][0] is False,
      str(late_leak))
check("engine_comparison is published (unrecorded) on charge_target only while it is numeric",
      op[ac.ENTITY_IDS["charge_target"]][2]["engine_comparison"] == {"v1_target_soc_pct": 85.0, "difference_pct": 5.0}
      and late[ac.ENTITY_IDS["charge_target"]][2]["engine_comparison"] is None)

# ---------------------------------------------------------------------------------------------------------------------
section("[5] status precedence")
S = ac.SystemStatus
check("precedence order", S.PRECEDENCE == ("PAUSED", "SELF_TEST_FAILED", "STALE", "STARTING", "BLOCKED", "INSUFFICIENT_DATA", "NO_ADVICE", "OK"))


def ds(**kw):
    a = dict(paused=False, self_test_failed=False, stale=False, starting=False, data_quality="OK", item_statuses=("OK",))
    a.update(kw)
    return ac.derive_status(**a)


check("PAUSED beats everything", ds(paused=True, self_test_failed=True, stale=True, starting=True, data_quality="BLOCKED") == "PAUSED")
check("a missing pause control (None) is not paused", ds(paused=None) == "OK")
check("SELF_TEST_FAILED > STALE > STARTING", ds(self_test_failed=True, stale=True) == "SELF_TEST_FAILED"
      and ds(stale=True, starting=True) == "STALE" and ds(starting=True, data_quality="BLOCKED") == "STARTING")
check("data quality BLOCKED -> BLOCKED even with an OK item", ds(data_quality="BLOCKED") == "BLOCKED")
check("no OK item and one BLOCKED -> BLOCKED", ds(item_statuses=("BLOCKED", "INSUFFICIENT_DATA")) == "BLOCKED")
check("no OK item, INSUFFICIENT -> INSUFFICIENT_DATA; none -> NO_ADVICE",
      ds(item_statuses=("INSUFFICIENT_DATA", "NO_ADVICE")) == "INSUFFICIENT_DATA" and ds(item_statuses=("NO_ADVICE",)) == "NO_ADVICE")
check("one OK item -> OK", ds(item_statuses=("BLOCKED", "OK")) == "OK")
check("the fixtures' statuses", (blk_env.status, ok_env.status) == ("BLOCKED", "OK"))

# ---------------------------------------------------------------------------------------------------------------------
section("[6] golden fixtures")
for name in gen.NAMES:
    path = gen.OUT_DIR / f"{name}.json"
    check(f"{name}.json regenerates byte-identical from the literal constructors",
          path.is_file() and path.read_bytes() == gen.render(name).encode("utf-8"))
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    stamps = set(re.findall(r"\b(\d{4})-\d{2}-\d{2}T", text))
    check(f"{name}.json: every timestamp is in the fictional year 2030, no 13-digit number, LF only",
          stamps == {"2030"} and not re.search(r"\d{13}", text) and b"\r" not in path.read_bytes(), str(stamps))
gsrc = (ROOT / "intelligence" / "tests" / "_gen_contract_fixtures.py").read_text(encoding="utf-8")
check("the generator never calls run_cycle", "run_cycle" not in gsrc.replace('"""', "").split("from __future__")[1])

# ---------------------------------------------------------------------------------------------------------------------
section("[7] byte budget and attribute name sets")
for name in gen.NAMES:
    pay = ac.to_entity_payloads(gen.BUILDERS[name]())
    sizes = {eid: ac.entity_json_bytes(*v) for eid, v in pay.items()}
    check(f"{name}: every entity JSON is at most 16 KiB (largest {max(sizes.values())} bytes)", max(sizes.values()) <= ac.MAX_ENTITY_JSON_BYTES)
big_text = "x" * 400
_names = sorted(ac.SITE_READING_KEYS)[:ac.MAX_INPUT_AGES - 1] + ["battery.soc"]
# the largest envelope the contract admits: an OK charge_target with a maximal summary and engine comparison, every other item
# BLOCKED with the maximum blockers and reason codes, and every status block at its byte cap
big = ac.assemble_envelope(NOW, gen.VERSIONS,
                           items=(replace(OK_CT, summary={"target_soc_pct": 80.0, "note": "s" * 1900}),)
                           + tuple(ac.ItemView(k, "BLOCKED", blockers=tuple((f"C{i}", big_text) for i in range(ac.MAX_BLOCKERS)),
                                               reason_codes=tuple(f"R{i}" for i in range(ac.MAX_REASON_CODES)))
                                   for k in ac.ADVICE_ITEMS[1:]),
                           forecasts=blk_env.forecasts, data_quality="DEGRADED", decisions=SYN_DS, accept_provenance=SYN_ACC,
                           valid_until=gen.VALID,
                           blockers=tuple((f"B{i}", big_text) for i in range(ac.MAX_BLOCKERS)),
                           reason_codes=tuple(f"R{i}" for i in range(ac.MAX_REASON_CODES)),
                           input_ages=tuple({"name": n, "age_s": 123456.5, "limit_s": 900.0, "status": "unknown"} for n in _names),
                           tariff={"provenance": "VERIFIED", "window": "w" * 680, "price_range": [7.5, 15.0]},
                           value={"range_gbp": [0.4, 1.2], "assumptions": ["v" * 690]}, plan={"precharge_by": "q" * 700},
                           accuracy={"mae_7d": 123456.5, "coverage_7d": 0.8, "n": 123456}, self_test={"CHECK": "FAIL: " + "s" * 690},
                           engine_comparison={"v1_target_soc_pct": 85.0, "note": "e" * 700})
bsz = {eid: ac.entity_json_bytes(*v) for eid, v in ac.to_entity_payloads(big).items()}
check(f"a maximal envelope stays within 16 KiB per entity (largest {max(bsz.values())} bytes)", max(bsz.values()) <= ac.MAX_ENTITY_JSON_BYTES)
check("more than the maximum blockers / input ages, an oversized block or code is refused; a long text is truncated",
      raises(lambda: replace(big, blockers=big.blockers + (("X", "y"),))) and raises(lambda: replace(big, input_ages=big.input_ages + ({},)))
      and raises(lambda: replace(big, plan={"x": "y" * 800})) and raises(lambda: replace(big, plan={"precharge_by": "y" * 800}))
      and raises(lambda: replace(big, reason_codes=("C" * 65,)))
      and len(big.blockers[0][1]) == ac.MAX_TEXT_CHARS
      and ac.self_test_failed_envelope(NOW, gen.VERSIONS, {f"F{i}": "z" * 500 for i in range(50)}).status == "SELF_TEST_FAILED")
check("recorded and unrecorded attribute names are disjoint", not (ac.RECORDED_ATTRIBUTES & ac.UNRECORDED_ATTRIBUTES))
names_ok = all(set(rec) <= ac.RECORDED_ATTRIBUTES and set(un) <= ac.UNRECORDED_ATTRIBUTES
               for name in gen.NAMES for _st, rec, un in ac.to_entity_payloads(gen.BUILDERS[name]()).values())
check("every entity's attributes fall in the declared recorded / unrecorded sets", names_ok)
check("large attributes (self_test, input_ages, last_good, advice, engine_comparison) are unrecorded",
      {"self_test", "input_ages", "last_good", "advice", "engine_comparison"} <= ac.UNRECORDED_ATTRIBUTES)

# ---------------------------------------------------------------------------------------------------------------------
section("[8] drift check against ecco_core.bridge.AdvisoryRecord.display_attributes")
rec_attrs = record(Advice("charge_target", OK, {"target_soc_pct": 75.0}, conf), NOW).display_attributes()
for k in ac.ADVICE_ITEMS:
    st, rec, un = op[ac.ENTITY_IDS[k]]
    check(f"{k}: carries every AdvisoryRecord display attribute name ({sorted(rec_attrs)})",
          set(rec_attrs) <= set(rec) | set(un) and rec["mode"] == rec_attrs["mode"] and rec["applies_nothing"] is rec_attrs["applies_nothing"])

# ---------------------------------------------------------------------------------------------------------------------
section("[9] CycleInputs, SITE_READING_KEYS, imports")
check("CycleInputs has exactly the contract's fields",
      [f.name for f in fields(ac.CycleInputs)] == ["now", "snapshot", "live", "caller_assessments", "history", "pv_forecast_history",
                                                   "base_cfg", "site_facts", "decisions", "accept_provenance", "site_readings",
                                                   "outcome_metrics", "paused", "previous", "versions"])
ci = ac.CycleInputs(now=NOW)
check("CycleInputs defaults: accept OWNER_RECORD only, all decisions OPEN, pause control not supplied (None)", ci.accept_provenance == frozenset({"OWNER_RECORD"})
      and set(ci.decisions.status_map().values()) == {"OPEN"} and ci.paused is None)
check("CycleInputs freezes lists and sets", ac.CycleInputs(now=NOW, site_readings=[1], accept_provenance={"X"}).site_readings == (1,)
      and isinstance(ac.CycleInputs(now=NOW, accept_provenance={"X"}).accept_provenance, frozenset))
check("SITE_READING_KEYS covers every gate reading of site_decisions", set(sd.GATE_READING_KEYS) <= set(ac.SITE_READING_KEYS),
      str(set(sd.GATE_READING_KEYS) - set(ac.SITE_READING_KEYS)))
check("SITE_READING_KEYS has the contract's keys and units",
      {"liveness.dongle_poll_changed_at", "supervision.state", "supervision.stable", "supervision.heartbeat_age_s", "battery.soc_raw_pct",
       "capacity.helper_kwh", "capacity.fe1_wh_per_pct", "capacity.fe1_basis", "capacity.reg204_ah", "efficiency.helper_pct",
       "protection.shutdown_soc_pct", "stop.dump_soc_pct", "tou.slot_table", "tou.current_target_soc_pct", "limits.max_grid_charge_w",
       "tariff.import_rates", "tariff.export_rates", "tariff.events", "pv.forecast_today_kwh", "pv.forecast_tomorrow_kwh",
       "inverter.clock_offset_s", "pref.wear_cost_p_per_kwh", "pref.normal_max_charge_target_pct"} == set(ac.SITE_READING_KEYS)
      and ac.SITE_READING_KEYS["limits.max_grid_charge_w"] == "W" and ac.SITE_READING_KEYS["protection.shutdown_soc_pct"] == "%")
check("SiteReading.problems: unknown key, wrong unit, naive time, missing source",
      ac.SiteReading("x.y", 1, "W", NOW, "s").problems() and ac.SiteReading("limits.max_grid_charge_w", 1, "kW", NOW, "s").problems()
      and ac.SiteReading("limits.max_grid_charge_w", 1, "W", datetime(2030, 1, 1), "s").problems()
      and ac.SiteReading("limits.max_grid_charge_w", 1, "W", NOW, "").problems()
      and not ac.SiteReading("limits.max_grid_charge_w", 5000, "W", NOW, "ha:helper").problems())
check("RunCycle is a runtime-checkable protocol", isinstance(lambda inputs: None, ac.RunCycle))
tree = ast.parse(SRC.read_text(encoding="utf-8"))
mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0} | \
       {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
check("advisory_contract imports from ecco_core only ecco_core.state", {m for m in mods if m and m.startswith("ecco_core")} == {"ecco_core.state"})
calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
check("no clock read, no file access", not [c for c in calls if c.endswith((".now", ".today", "time.time")) or c in ("open", "print")])
check("render_ha_prototype is untouched and keeps its own (superseded) ecco_intelligence_* ids",
      "sensor.ecco_intelligence_status" in (ROOT / "intelligence" / "tools" / "render_ha_prototype.py").read_text(encoding="utf-8"))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all advisory-contract checks passed")
