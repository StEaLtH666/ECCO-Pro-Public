#!/usr/bin/env python3
"""End-to-end: the BUILT SHADOW kit runs the real run_cycle on its own (integration step IP-4, step 5).

  * tools/build_ha_integration.py --out <temporary directory> builds the kit (exit 0, the kit's vendored shadow_cycle);
  * the synthetic inputs of the shared cycle fixture (intelligence/tests/_cycle_fixtures.py) are written to JSON: all
    decisions OPEN under the default acceptance, every decision SYNTHETIC_TEST under an explicit SYNTHETIC_TEST
    acceptance, the same paused, and dq's no_pv fault (intelligence/faults.py) on both, over several seeds. The round
    trip is checked first: each case rebuilt with the repository's classes gives exactly the envelope of the original
    inputs;
  * a fresh `python -I -B` interpreter with ONLY the build directory on sys.path rebuilds every case with the kit's own
    classes and runs the kit's run_cycle; no top-level intelligence / ecco_core / homeassistant module is loaded there,
    and its envelopes equal the repository's;
  * on the kit's entity payloads: mode SHADOW and applies_nothing on every entity; the null rule (a BLOCKED or
    INSUFFICIENT_DATA item carries no number in its state or in any attribute; a numeric state only for an OK item);
    all OPEN: no finite number anywhere except pv_tomorrow and the diagnostics (the accuracy entity, the status entity's
    accuracy block and input ages); paused: status PAUSED, the pause control reported, every state None and no number in
    any entity; no_pv: pv_tomorrow never OK and its entity carries no number;
  * between cycles, on every computed case: the kit's own mapping one second past the envelope's valid_until (fresh False,
    an item numeric only while its own validity lasts) and one second past every item's validity (no item number at all),
    and the kit's stale_from (STALE, no number outside the unrecorded last_good, fresh False);
  * WP-E, the grid-charge TOU classification and its freshness through the kit's run_cycle (SYNTHETIC_TEST decisions;
    every case also passes every check above): the fixture's one Grid slot gives charge_target OK with the TOU claim
    capped at UNCERTAIN and MORNING_SOC_ASSUMES_CHARGE; slot 3's charge source unknown BLOCKs every charge-window item
    and overnight_demand (TOU_SLOT_SOURCE_UNKNOWN); a frozen configuration-poll text (liveness 400 s old) BLOCKs the
    charge-window items (CONFIG_LIVENESS_STALE) and overnight_demand (CHARGE_WINDOW_UNKNOWN); configuration-online off
    (the runtime then withholds the liveness and every configuration-poll reading) the same with
    CONFIG_LIVENESS_MISSING; a configuration-poll age of 130 s (one deferred poll) leaves them OK under the 300 s bound,
    190 s BLOCKs overnight_demand INPUT_EXPIRING (what rests on it is withheld in turn) with pv_tomorrow and
    predicted_day_load still OK and the envelope valid past the next tick; the raise-only reserve helper mapped but
    unusable BLOCKs every item I-D1 gates (PREF_RESERVE_RAISE_UNKNOWN). In each such case pv_tomorrow keeps its number
    and no withheld item's entity carries one.

Plain script; exits 1 on any failure. A temporary directory is created and removed by this suite. Synthetic data only;
no Home Assistant, no network, no hardware.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "intelligence" / "tests"))

import _cycle_fixtures as cf  # noqa: E402
import _harness as H  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.inputs import live_inputs_from_snapshot  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


PREFIX = "ecco_intel_e2e_"
KIT_PREFIX = "custom_components.ecco_intelligence._vendor."
NO_PV_SEEDS = (1, 2, 3)
CYCLE_FIELDS = {"now", "snapshot", "live", "caller_assessments", "history", "pv_forecast_history", "base_cfg", "site_facts",
                "decisions", "accept_provenance", "site_readings", "outcome_metrics", "paused", "previous", "versions"}
ITEM_ENTITIES = {k: ac.ENTITY_IDS[k] for k in ("charge_target", "overnight_demand", "export_event", "dump_to_grid",
                                               "predicted_day_load", "pv_tomorrow", "predicted_morning_soc")}
# WP-E: the published items that rest on the charge window (site_decisions.CHARGE_WINDOW_ITEMS without the internal
# v1_summary, and overnight_demand, which rests on its window), and those I-D1 gates
TOU_ITEMS = ("charge_target", "overnight_demand", "export_event", "dump_to_grid", "predicted_morning_soc")
D1_ITEMS = tuple(k for k in sd.items_gated_by("D1") if k in ITEM_ENTITIES)
AT_OBSERVATION = object()          # a liveness reading: its value is its observation time


def with_reading(ci: ac.CycleInputs, key: str, value, age_s: float) -> ac.CycleInputs:
    """The same inputs with reading `key` replaced, observed `age_s` before now (synthetic)."""
    at = ci.now - timedelta(seconds=age_s)
    rs = [r for r in ci.site_readings if r.key != key]
    rs.append(ac.SiteReading(key, at if value is AT_OBSERVATION else value, ac.SITE_READING_KEYS[key], at, f"synthetic:{key}"))
    return replace(ci, site_readings=tuple(rs))


def without_readings(ci: ac.CycleInputs, keys) -> ac.CycleInputs:
    return replace(ci, site_readings=tuple(r for r in ci.site_readings if r.key not in set(keys)))


def wp_e_cases(base: ac.CycleInputs) -> dict[str, ac.CycleInputs]:
    """The WP-E cases, each a change of the SYNTHETIC_TEST case (whose fixture table has one Grid slot, 01:00-04:30)."""
    table = [dict(r) for r in next(r.value for r in base.site_readings if r.key == "tou.slot_table")]
    table[2]["charge_source"] = None                                # slot 3: unknown (HA 'unknown' becomes null)
    age = {r.key: (base.now - r.observed_at).total_seconds() for r in base.site_readings}
    return {
        "tou_slot3_unknown": with_reading(base, "tou.slot_table", table, age["tou.slot_table"]),
        "config_frozen": with_reading(base, sd.CONFIG_LIVENESS_KEY, AT_OBSERVATION, 400.0),
        "config_offline": without_readings(base, (sd.CONFIG_LIVENESS_KEY,) + tuple(sd.CONFIG_POLL_READINGS)),
        "config_age_130": with_reading(base, sd.CONFIG_LIVENESS_KEY, AT_OBSERVATION, 130.0),
        "config_age_190": with_reading(base, sd.CONFIG_LIVENESS_KEY, AT_OBSERVATION, 190.0),
        "raise_unusable": with_reading(base, "pref.advisory_reserve_raise_pct", None, age["pref.advisory_reserve_raise_pct"]),
    }


# ---------------------------------------------------------------------------------------------------------------------
# the JSON form of one CycleInputs (synthetic values only)
# ---------------------------------------------------------------------------------------------------------------------

def enc(v):
    if isinstance(v, datetime):
        return {"__dt__": v.isoformat()}
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    return v


def to_doc(ci: ac.CycleInputs) -> dict:
    ds = ci.decisions
    decisions = {sd.display_label(did): {"status": d.status, "provenance": d.provenance, "value": d.recorded_json()}
                 for did, d in ds.decisions.items() if d.status == sd.DecisionStatus.RECORDED}
    hist = None if ci.history is None else [
        {**{f.name: getattr(r, f.name) for f in fields(r) if f.name != "flags"},
         "flags": {k: sorted(v) for k, v in r.flags.items()}} for r in ci.history.by_start.values()]
    om = ci.outcome_metrics
    return {
        "now": ci.now.isoformat(),
        "observations": ci.snapshot.to_dict()["observations"],
        "caller_assessments": [list(a) for a in ci.caller_assessments],
        "history": hist,
        "pv_forecast_history": {s: {d.isoformat(): kwh for d, kwh in m.items()} for s, m in (ci.pv_forecast_history or {}).items()},
        "base_cfg": {k: getattr(ci.base_cfg, k) for k in ("latitude", "longitude", "tz", "pv_array_kwp")},
        "site_facts": {f.name: getattr(ci.site_facts, f.name) for f in fields(ci.site_facts)},
        "decisions": decisions, "decisions_source": ds.source,
        "accept_provenance": sorted(ci.accept_provenance),
        "site_readings": [[r.key, enc(r.value), r.unit, r.observed_at.isoformat(), r.source] for r in ci.site_readings],
        "outcome_metrics": None if om is None else [om.mae_7d, om.coverage_7d, om.n],
        "paused": ci.paused,
        "versions": [ci.versions.integration_version, ci.versions.engine_version, ci.versions.git_sha, ci.versions.config_hash],
    }


def faithful(ci: ac.CycleInputs) -> list[str]:
    """What the JSON form would not carry for this case (it must be nothing)."""
    out = []
    if {f.name for f in fields(ci)} != CYCLE_FIELDS:
        out.append(f"CycleInputs fields changed: {sorted({f.name for f in fields(ci)} ^ CYCLE_FIELDS)}")
    if ci.previous is not None:
        out.append("previous is not None")
    if ci.live != live_inputs_from_snapshot(ci.snapshot):
        out.append("live is not the LiveInputs of the snapshot")
    if ci.base_cfg != SiteConfig(**{k: getattr(ci.base_cfg, k) for k in ("latitude", "longitude", "tz", "pv_array_kwp")}):
        out.append("base_cfg carries more than latitude, longitude, tz and pv_array_kwp")
    rebuilt = sd.DecisionSet.from_mapping(to_doc(ci)["decisions"], source=ci.decisions.source)
    if rebuilt.to_dict() != ci.decisions.to_dict():
        out.append("the decisions do not round-trip")
    return out


# the child: rebuilds every case with the classes of one module tree (the repository's, or the kit's) and runs run_cycle
CHILD = r'''
import importlib, json, sys
from datetime import date, datetime, timedelta
sys.path.insert(0, sys.argv[1])
P = sys.argv[2]
m = lambda name: importlib.import_module(P + name)
ac, sd, st, hi = m("intelligence.advisory_contract"), m("intelligence.site_decisions"), m("ecco_core.state"), m("intelligence.history")
cfgm, inp, sc = m("intelligence.config"), m("intelligence.inputs"), m("intelligence.shadow_cycle")

def dec(v):
    if isinstance(v, dict):
        return datetime.fromisoformat(v["__dt__"]) if set(v) == {"__dt__"} else {k: dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [dec(x) for x in v]
    return v

def dt(s):
    return None if s is None else datetime.fromisoformat(s)

out = {}
for name, d in json.loads(sys.stdin.read()).items():
    now = dt(d["now"])
    obs = [st.Observation(o["signal"], o["value"], dt(o["observed_at"]), o["source"], o["kind"], o["unit"], o["raw"],
                          tuple(o["derived_from"]), tuple(o["quality"])) for o in d["observations"]]
    snap = st.Snapshot.of(now, obs)
    hist = None
    if d["history"] is not None:
        hist = hi.History(hi.HourRecord(**{**r, "flags": {k: set(v) for k, v in r["flags"].items()}}) for r in d["history"])
    om = d["outcome_metrics"]
    ci = ac.CycleInputs(
        now=now, snapshot=snap, live=inp.live_inputs_from_snapshot(snap),
        caller_assessments=tuple(tuple(a) for a in d["caller_assessments"]), history=hist,
        pv_forecast_history={s: {date.fromisoformat(k): v for k, v in mm.items()} for s, mm in d["pv_forecast_history"].items()},
        base_cfg=cfgm.SiteConfig(**d["base_cfg"]), site_facts=ac.SiteFacts(**d["site_facts"]),
        decisions=sd.DecisionSet.from_mapping(d["decisions"], source=d["decisions_source"]),
        accept_provenance=frozenset(d["accept_provenance"]),
        site_readings=tuple(ac.SiteReading(k, dec(v), u, dt(t), s) for k, v, u, t, s in d["site_readings"]),
        outcome_metrics=None if om is None else ac.OutcomeMetrics(*om), paused=d["paused"], previous=None,
        versions=ac.Versions(*d["versions"]))
    env = sc.run_cycle(ci)
    rec = {"env": env.to_dict(), "payloads": {k: list(v) for k, v in ac.to_entity_payloads(env).items()}}
    # between cycles: the kit's own mapping just past the envelope's validity and just past every item's validity, and
    # the kit's stale_from (what the runtime publishes once a computed result has expired)
    if env.status not in ac.SystemStatus.NULL and env.valid_until is not None:
        one = timedelta(seconds=1)
        last = max([env.valid_until] + [v.valid_until for v in env.items + env.forecasts if v.valid_until is not None])
        rec["late_env"] = {k: list(v) for k, v in ac.to_entity_payloads(env, env.valid_until + one).items()}
        rec["late_all"] = {k: list(v) for k, v in ac.to_entity_payloads(env, last + one).items()}
        se = ac.stale_from(env, env.valid_until + one)
        rec["stale_status"] = se.status
        rec["stale"] = {k: list(v) for k, v in ac.to_entity_payloads(se, env.valid_until + one).items()}
    out[name] = rec
top = sorted(k for k in sys.modules if k.split(".")[0] in ("intelligence", "ecco_core", "homeassistant"))
print(json.dumps({"cases": out, "top": top, "cycle_file": sc.__file__}, default=str))
'''


def run_child(path: Path, prefix: str, docs: dict) -> tuple[dict, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(path), prefix], input=json.dumps(docs), capture_output=True,
                       text=True, timeout=900, cwd=str(path), env=env)
    if r.returncode != 0:
        return {}, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1]), ""


def numbers(v, path: str = "") -> list[str]:
    """The paths of every finite or non-finite number in a JSON value (booleans and strings are not numbers)."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return []
    if isinstance(v, (int, float)):
        return [path or "."]
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in numbers(x, f"{path}.{k}")]
    if isinstance(v, (list, tuple)):
        return [p for i, x in enumerate(v) for p in numbers(x, f"{path}[{i}]")]
    return [path + "?"]


def entity_numbers(payload: list) -> list[str]:
    state, rec, unrec = payload
    return numbers({"state": state, "recorded": rec, "unrecorded": unrec})


def statuses(env: dict) -> dict:
    """{key: status} over the advice items AND the forecasts of an envelope's dict form."""
    return {v["key"]: v["status"] for part in ("items", "forecasts") for v in env.get(part) or []}


def jsonable(e) -> dict:
    return json.loads(json.dumps(e.to_dict(), default=str))


# ---------------------------------------------------------------------------------------------------------------------
print("== the cases (synthetic) and their JSON round trip")
# ---------------------------------------------------------------------------------------------------------------------
cases: dict[str, ac.CycleInputs] = {
    "all_open": cf.cycle_inputs(),
    "synthetic": cf.cycle_inputs(synthetic_recorded=True),
    "paused": cf.cycle_inputs(synthetic_recorded=True, paused=True),
}
for seed in NO_PV_SEEDS:
    cases[f"no_pv_open_{seed}"] = faults.inject("no_pv", cases["all_open"], seed)
    cases[f"no_pv_synthetic_{seed}"] = faults.inject("no_pv", cases["synthetic"], seed)
cases.update(wp_e_cases(cases["synthetic"]))
check("all OPEN under the default acceptance; SYNTHETIC_TEST under an explicit SYNTHETIC_TEST acceptance; the paused case paused",
      all(cases["all_open"].decisions.status(d) == "OPEN" for d in sd.DECISION_IDS)
      and cases["all_open"].accept_provenance == sd.DEFAULT_ACCEPT_PROVENANCE
      and cases["synthetic"].accept_provenance == frozenset({sd.Provenance.SYNTHETIC_TEST})
      and all(d.provenance == sd.Provenance.SYNTHETIC_TEST for d in cases["synthetic"].decisions.recorded())
      and cases["paused"].paused is True and cases["synthetic"].paused is False)
gaps = {n: faithful(ci) for n, ci in cases.items()}
check("every case is carried completely by its JSON form", not any(gaps.values()), str({n: g for n, g in gaps.items() if g}))
docs = {n: to_doc(ci) for n, ci in cases.items()}
direct = {n: jsonable(run_cycle(ci)) for n, ci in cases.items()}
repo_doc, repo_err = run_child(REPO, "", docs)
check("the repository's own modules, rebuilt from the JSON in a fresh -I interpreter, give exactly the envelopes of the "
      "original inputs (the round trip loses nothing)",
      not repo_err and all(repo_doc["cases"][n]["env"] == direct[n] for n in cases), repo_err
      or str([n for n in cases if repo_doc["cases"][n]["env"] != direct[n]]))

root = H.mktemp(PREFIX)
try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== the build")
    # -----------------------------------------------------------------------------------------------------------------
    out = root / "kit"
    b = H.build_kit(out)
    pkg = out / "custom_components" / "ecco_intelligence"
    check("tools/build_ha_integration.py --out <temporary directory> exits 0 and writes the kit with its vendored shadow_cycle",
          b.returncode == 0 and (pkg / "_vendor" / "intelligence" / "shadow_cycle.py").is_file()
          and (out / "VENDOR_MANIFEST.json").is_file() and (out / "SHA256SUMS").is_file(), (b.stdout + b.stderr)[-400:])

    # -----------------------------------------------------------------------------------------------------------------
    print("== the kit's run_cycle, in a fresh -I interpreter with only the build directory on sys.path")
    # -----------------------------------------------------------------------------------------------------------------
    kit_doc, kit_err = run_child(out, KIT_PREFIX, docs) if b.returncode == 0 else ({}, "no kit")
    kc = kit_doc.get("cases", {})
    check("the kit's run_cycle runs every case", not kit_err and set(kc) == set(cases), kit_err)
    check("... from inside the kit, with no top-level intelligence / ecco_core / homeassistant module loaded",
          kit_doc.get("top") == [] and Path(kit_doc.get("cycle_file", "/")).resolve().is_relative_to(out.resolve()),
          str((kit_doc.get("top"), kit_doc.get("cycle_file"))))
    check("the kit's envelopes equal the repository's, case by case",
          bool(kc) and all(kc[n]["env"] == repo_doc["cases"][n]["env"] for n in cases),
          str([n for n in cases if n in kc and kc[n]["env"] != repo_doc["cases"][n]["env"]]))

    # -----------------------------------------------------------------------------------------------------------------
    print("== SHADOW, applies nothing, and the null rule on the kit's entity payloads")
    # -----------------------------------------------------------------------------------------------------------------
    pls = {n: c["payloads"] for n, c in kc.items()}
    check("every entity of every case says mode SHADOW and applies_nothing true, and so does every envelope",
          bool(pls) and all(p[1].get("mode") == "SHADOW" and p[1].get("applies_nothing") is True for pl in pls.values() for p in pl.values())
          and all(c["env"]["mode"] == "SHADOW" and c["env"]["applies_nothing"] is True for c in kc.values()))
    bad_null, bad_numeric = [], []
    for n, c in kc.items():
        status_of = statuses(c["env"])
        for key, eid in ITEM_ENTITIES.items():
            p = pls[n][eid]
            if status_of.get(key) in ("BLOCKED", "INSUFFICIENT_DATA") and entity_numbers(p):
                bad_null.append((n, key, entity_numbers(p)[:3]))
            if numbers(p[0]) and status_of.get(key) != "OK":
                bad_numeric.append((n, key, status_of.get(key)))
    check("null rule: a BLOCKED or INSUFFICIENT_DATA item carries no number in its state or in any attribute (every case)",
          bool(kc) and not bad_null, str(bad_null[:3]))
    check("null rule: a numeric item state only for an OK item (every case)", bool(kc) and not bad_numeric, str(bad_numeric[:3]))

    op = pls.get("all_open", {})
    status_e = ac.ENTITY_IDS["status"]
    allowed = {ac.ENTITY_IDS["pv_tomorrow"], ac.ENTITY_IDS["accuracy"]}
    stray = {eid: entity_numbers(p) for eid, p in op.items() if eid not in allowed and eid != status_e and entity_numbers(p)}
    status_stray = [x for x in (entity_numbers(op[status_e]) if status_e in op else ["missing"])
                    if not x.startswith((".recorded.accuracy.", ".unrecorded.input_ages["))]
    check("all OPEN: status BLOCKED, every decision-gated item BLOCKED, pv_tomorrow OK",
          kc.get("all_open", {}).get("env", {}).get("status") == "BLOCKED"
          and all(statuses(kc["all_open"]["env"]).get(k) == "BLOCKED" for k in H.gated_keys(ac))
          and statuses(kc["all_open"]["env"]).get("pv_tomorrow") == "OK",
          str(statuses(kc.get("all_open", {}).get("env", {}))))
    check("all OPEN: no finite number anywhere except pv_tomorrow and the diagnostics (the accuracy entity; the status "
          "entity's accuracy block and input ages)", bool(op) and not stray and not status_stray,
          str((stray, status_stray[:4])))
    check("all OPEN: the tariff block is NOT_VERIFIED with no window and no price range; no value, plan or engine comparison",
          bool(op) and op[status_e][1].get("tariff") == {"provenance": "NOT_VERIFIED", "window": None, "price_range": None}
          and all(op[status_e][1].get(k) is None for k in ("value", "plan"))
          and kc["all_open"]["env"].get("engine_comparison") is None, str(op.get(status_e, [None, {}])[1].get("tariff")))

    syn = kc.get("synthetic", {}).get("env", {})
    check("SYNTHETIC_TEST accepted: the cycle gives OK advice with numbers (so the checks above are not vacuous), still SHADOW",
          syn.get("status") == "OK" and statuses(syn).get("charge_target") == "OK"
          and numbers(pls.get("synthetic", {}).get(ac.ENTITY_IDS["charge_target"], [None])[0]) == ["."],
          str(syn.get("status")))

    pz = kc.get("paused", {}).get("env", {})
    pz_numbers = {eid: entity_numbers(p) for eid, p in pls.get("paused", {}).items() if entity_numbers(p)}
    check("paused: status PAUSED, the pause control reported, every item and forecast withheld",
          pz.get("status") == "PAUSED" and pls["paused"][status_e][0] == "PAUSED"
          and pls["paused"][status_e][1].get("pause_control") not in (None, "MISSING")
          and len(statuses(pz)) == len(ITEM_ENTITIES) and all(s == "WITHHELD" for s in statuses(pz).values()),
          str((pz.get("status"), pz.get("pause_control"), statuses(pz))))
    check("paused: every entity state but the status and the fresh flag is None, and no entity carries a number",
          bool(pls.get("paused")) and not pz_numbers
          and all(p[0] is None for eid, p in pls["paused"].items() if eid not in (status_e, ac.ENTITY_IDS["fresh"])),
          str(pz_numbers))

    nopv = {n: statuses(c["env"]).get("pv_tomorrow") for n, c in kc.items() if n.startswith("no_pv")}
    check(f"no_pv (dq's fault, seeds {list(NO_PV_SEEDS)}, all OPEN and SYNTHETIC_TEST): pv_tomorrow is never OK",
          len(nopv) == 2 * len(NO_PV_SEEDS) and all(s not in (None, "OK") for s in nopv.values()), str(nopv))
    check("no_pv: the pv_tomorrow entity carries no number (state None, no attribute number)",
          bool(nopv) and all(not entity_numbers(pls[n][ac.ENTITY_IDS["pv_tomorrow"]]) for n in nopv),
          str({n: entity_numbers(pls[n][ac.ENTITY_IDS["pv_tomorrow"]])[:3] for n in nopv}))
    check("... while the same inputs without the fault give pv_tomorrow OK (the fault is what withholds it)",
          statuses(kc.get("all_open", {}).get("env", {})).get("pv_tomorrow") == "OK" and statuses(syn).get("pv_tomorrow") == "OK")

    # -----------------------------------------------------------------------------------------------------------------
    print("== WP-E: the grid-charge TOU classification and its freshness through the kit's run_cycle")
    # -----------------------------------------------------------------------------------------------------------------
    def views(n):
        return {v["key"]: v for part in ("items", "forecasts") for v in kc.get(n, {}).get("env", {}).get(part) or []}

    def codes(n, key):
        v = views(n).get(key) or {}
        return {b["code"] for b in v.get("blockers") or []} | set(v.get("reason_codes") or [])

    def item_numbers(n, keys):
        return {k: entity_numbers(pls[n][ITEM_ENTITIES[k]]) for k in keys if n in pls and entity_numbers(pls[n][ITEM_ENTITIES[k]])}

    def blocked_with(n, keys, code, withheld=TOU_ITEMS):
        """(passed, detail): every item in `keys` BLOCKED with `code`; every item in `withheld` (default: the charge-window
        items) not OK, with no number on its entity; pv_tomorrow OK with a number (only what rests on the cause is
        withheld)."""
        st = statuses(kc.get(n, {}).get("env", {}))
        bad = {k: (st.get(k), sorted(codes(n, k))[:4]) for k in keys if st.get(k) != "BLOCKED" or code not in codes(n, k)}
        shown = {k: st.get(k) for k in withheld if st.get(k) == "OK"}
        nums = item_numbers(n, tuple(dict.fromkeys(tuple(withheld) + tuple(keys))))
        pv_ok = st.get("pv_tomorrow") == "OK" and n in pls and numbers(pls[n][ITEM_ENTITIES["pv_tomorrow"]][0]) == ["."]
        return (bool(st) and not bad and not shown and not nums and pv_ok), f"{bad} {shown} {nums} pv={st.get('pv_tomorrow')}"

    gen = datetime.fromisoformat(syn["generated_at"]) if syn.get("generated_at") else None
    ct_s = views("synthetic").get("charge_target") or {}
    check("slot 1 Grid (the fixture's one grid-charge slot, literal 'None' elsewhere): charge_target OK with a number, valid "
          "at least REFRESH_MARGIN_S, the TOU claim capped at UNCERTAIN (no other claim), GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED "
          "on it, MORNING_SOC_ASSUMES_CHARGE on predicted_morning_soc",
          ct_s.get("status") == "OK" and gen is not None and ct_s.get("valid_until") is not None
          and (datetime.fromisoformat(ct_s["valid_until"]) - gen).total_seconds() >= 125.0
          and "TOU_CLAIM_UNCERTAIN" in codes("synthetic", "charge_target")
          and not {"TOU_CLAIM_CONFIGURED", "TOU_CLAIM_NOT_EXPECTED"} & codes("synthetic", "charge_target")
          and "GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED" in codes("synthetic", "charge_target")
          and "MORNING_SOC_ASSUMES_CHARGE" in codes("synthetic", "predicted_morning_soc"),
          f"{ct_s.get('status')} {sorted(codes('synthetic', 'charge_target'))[:8]}")
    cw_items = tuple(k for k in TOU_ITEMS if k != "overnight_demand")     # the published CHARGE_WINDOW_ITEMS
    for name, keys, code, label in (
            ("tou_slot3_unknown", TOU_ITEMS, "TOU_SLOT_SOURCE_UNKNOWN", "slot 3's charge source unknown: every charge-window "
                                                                        "item and overnight_demand"),
            ("config_frozen", cw_items, "CONFIG_LIVENESS_STALE", "a frozen configuration-poll text (its liveness 400 s old, "
                                                                 "telemetry alive): every charge-window item"),
            ("config_offline", cw_items, "CONFIG_LIVENESS_MISSING", "configuration-online off (no configuration liveness and no "
                                                                    "configuration-poll reading, as the runtime withholds "
                                                                    "them): every charge-window item"),
            ("config_frozen", ("overnight_demand",), "CHARGE_WINDOW_UNKNOWN", "... frozen: overnight_demand (its window rests "
                                                                              "on the table, no longer fresh)"),
            ("config_offline", ("overnight_demand",), "CHARGE_WINDOW_UNKNOWN", "... offline: overnight_demand (no table)"),
            ("config_age_190", ("overnight_demand",), "INPUT_EXPIRING", "a configuration-poll age of 190 s (less than "
                                                                        "REFRESH_MARGIN_S of validity left): overnight_demand "
                                                                        "(the items resting on it are withheld in turn)")):
        ok_, detail = blocked_with(name, keys, code)
        check(f"{label} BLOCKED {code}; no charge-window item OK or numeric; pv_tomorrow keeps its number", ok_, detail)
    st130 = statuses(kc.get("config_age_130", {}).get("env", {}))
    ct130 = views("config_age_130").get("charge_target") or {}
    gen130 = kc.get("config_age_130", {}).get("env", {}).get("generated_at")
    check("a configuration-poll age of 130 s (one deferred poll): charge_target and predicted_morning_soc stay OK with numbers, "
          "valid at least REFRESH_MARGIN_S, no INPUT_EXPIRING anywhere (the 300 s bound tolerates it)",
          st130.get("charge_target") == "OK" and st130.get("predicted_morning_soc") == "OK" and gen130 is not None
          and (datetime.fromisoformat(ct130["valid_until"]) - datetime.fromisoformat(gen130)).total_seconds() >= 125.0
          and not any("INPUT_EXPIRING" in codes("config_age_130", k) for k in ITEM_ENTITIES)
          and set(item_numbers("config_age_130", ("charge_target", "predicted_morning_soc"))) == {"charge_target",
                                                                                                 "predicted_morning_soc"},
          f"{st130} {sorted(codes('config_age_130', 'charge_target'))[:6]}")
    e190 = kc.get("config_age_190", {}).get("env", {})
    check("... 190 s: the envelope stays valid past the next tick (no STALE then; INPUT_EXPIRING never shortens it), and "
          "only the items resting on the configuration poll are withheld (predicted_day_load stays OK)",
          bool(e190) and (datetime.fromisoformat(e190["valid_until"]) - datetime.fromisoformat(e190["generated_at"])).total_seconds()
          >= 125.0 and statuses(e190).get("predicted_day_load") == "OK", str((e190.get("generated_at"), e190.get("valid_until"))))
    ok_, detail = blocked_with("raise_unusable", D1_ITEMS, "PREF_RESERVE_RAISE_UNKNOWN", withheld=D1_ITEMS)
    check(f"the raise-only reserve helper mapped but unusable (value null): every item I-D1 gates {list(D1_ITEMS)} BLOCKED "
          "PREF_RESERVE_RAISE_UNKNOWN with no number; pv_tomorrow keeps its number", ok_ and set(D1_ITEMS) >= {
              "charge_target", "predicted_morning_soc"}, detail)
    check("... while overnight_demand, which I-D1 does not gate, stays OK", statuses(kc.get("raise_unusable", {}).get("env", {}))
          .get("overnight_demand") == "OK")

    # -----------------------------------------------------------------------------------------------------------------
    print("== between cycles: the kit's mapping past the validity, and the kit's stale_from")
    # -----------------------------------------------------------------------------------------------------------------
    computed = {n: c for n, c in kc.items() if "late_env" in c}
    fresh_e = ac.ENTITY_IDS["fresh"]
    check("every computed case is rendered past its validity and through stale_from (the synthetic and all-OPEN cases among "
          "them)", {"synthetic", "all_open"} <= set(computed) and "paused" not in computed, str(sorted(computed)))
    late_bad = []
    for n, c in computed.items():
        t_late = datetime.fromisoformat(c["env"]["valid_until"]) + timedelta(seconds=1)
        views = {v["key"]: v for part in ("items", "forecasts") for v in c["env"][part]}
        for key, eid in ITEM_ENTITIES.items():
            vu = views[key]["valid_until"]
            still_valid = views[key]["status"] == "OK" and vu is not None and datetime.fromisoformat(vu) >= t_late
            if entity_numbers(c["late_env"][eid]) and not still_valid:
                late_bad.append((n, key))
        if c["late_env"][fresh_e][0] is not False:
            late_bad.append((n, "fresh"))
    check("one second past the envelope's valid_until: fresh is False, and an item keeps a number only while its own validity "
          "lasts (the mapping's own null rule)", bool(computed) and not late_bad, str(late_bad[:4]))
    all_bad = {n: [k for k, eid in ITEM_ENTITIES.items() if entity_numbers(c["late_all"][eid])] + (
        ["fresh"] if c["late_all"][fresh_e][0] is not False else []) for n, c in computed.items()}
    check("one second past every item's validity: no item entity carries a number anywhere, and fresh is False "
          "(the synthetic case had numbers at generated_at)", bool(computed) and not any(all_bad.values())
          and numbers(pls["synthetic"][ac.ENTITY_IDS["charge_target"]][0]) == ["."],
          str({n: b for n, b in all_bad.items() if b}))
    stale_bad = {}
    for n, c in computed.items():
        pl = c["stale"]
        other = {eid: entity_numbers(p) for eid, p in pl.items() if eid != status_e and entity_numbers(p)}
        st_nums = [x for x in entity_numbers(pl[status_e]) if not x.startswith(".unrecorded.last_good.")]
        if c["stale_status"] != "STALE" or other or st_nums or pl[status_e][0] != "STALE" or pl[fresh_e][0] is not False:
            stale_bad[n] = (c["stale_status"], other, st_nums[:3])
    syn_lg = (computed.get("synthetic", {}).get("stale", {}).get(status_e, [None, {}, {}])[2] or {}).get("last_good") or {}
    check("the kit's stale_from: status STALE, no entity carries a number except the unrecorded last_good, fresh False",
          bool(computed) and not stale_bad, str(stale_bad))
    check("... and the synthetic case's OK values are in that last_good only",
          (syn_lg.get("values") or {}).get("charge_target") == syn["items"][0]["value"], str(syn_lg)[:200])
finally:
    H.rmtree_own(root, PREFIX)

check("the temporary directory is removed", not root.exists(), str(root))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all integration end-to-end checks passed")
