#!/usr/bin/env python3
"""Geek Mode coverage suite (ECCO Intelligence tab): every available source and attribute of the view is in the catalogue (the
universe is COMPUTED from code, never typed), and every way of getting that wrong is caught (mutation tests).

  [1] the contract: every ENTITY_IDS entity, every attribute list entry, every block key, every decision label, derived here from
      advisory_contract directly (not through the tool), is in the committed catalogue
  [2] the REAL engine: one SHADOW cycle on the shared synthetic inputs publishes entity payloads; every attribute and every
      first-level key of every dict attribute it publishes is in the catalogue (the tool's reading of the advisors' source is checked
      against what the engine really emits)
  [3] packages, dashboard, card and live shape: the pause helper, the watchdog, the three alert automations and the reserve helper;
      every entity the dashboard references; every attribute the Production card reads; nothing live is undeclared
  [4] reproducibility: the tool, run on a scratch copy of the code, writes a catalogue byte-identical to the committed one
  [5] MUTATIONS (each must fail with the right message): a source dropped; an attribute dropped; an invented attribute; an undeclared
      attribute added to a scratch copy of the contract (constant and payload; constant only); an undeclared advice key; a new
      automation; a new entity; a changed description; an orphan text; a missing text; an unalerted status

Test-only, no network, nothing live. Scratch copies live in the system temp directory and are removed.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import ROOT, cleanup, copy_outputs, copy_read_set, patch_file, run_tool, scratch_dir  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "intelligence" / "tests"))
import geek_mode_coverage as G  # noqa: E402
import geek_mode_texts_intelligence as T  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

cat = json.loads((ROOT / G.CATALOGUE_REL).read_bytes())
by_eid = {s["entity_id"]: s for s in cat["sources"]}


def names(eid: str) -> set[str]:
    return {a["name"] for a in by_eid[eid]["attributes"]}


# ===========================================================================
print("[1] the contract, derived here directly")
# ===========================================================================
check("all 13 contract entities are catalogued sources", len(ac.ENTITY_IDS) == 13 and all(e in by_eid for e in ac.ENTITY_IDS.values()),
      str([e for e in ac.ENTITY_IDS.values() if e not in by_eid]))
expect = {ac.ENTITY_IDS["status"]: set(ac.STATUS_RECORDED + ac.STATUS_UNRECORDED), ac.ENTITY_IDS["accuracy"]: set(ac.DIAG_RECORDED),
          ac.ENTITY_IDS["data_quality"]: set(ac.DIAG_RECORDED), ac.ENTITY_IDS["fresh"]: set(ac.FRESH_RECORDED)}
expect.update({ac.ENTITY_IDS[k]: set(ac.ITEM_RECORDED + ac.ITEM_UNRECORDED) for k in ac.ADVICE_ITEMS})
expect.update({ac.ENTITY_IDS[k]: set(ac.FORECAST_RECORDED + ac.FORECAST_UNRECORDED) for k in ac.FORECAST_ITEMS})
for eid, attrs in sorted(expect.items()):
    missing = sorted(attrs - names(eid))
    check(f"{eid}: all {len(attrs)} contract attributes are in the catalogue", not missing, str(missing))
check("the status entity's catalogue attributes are exactly the 27 contract ones plus Home Assistant's three, plus nested paths",
      {n for n in names(ac.ENTITY_IDS["status"]) if "." not in n} == expect[ac.ENTITY_IDS["status"]] | {"friendly_name", "device_class", "options"})
st = names(ac.ENTITY_IDS["status"])
for block, keys in ac.BLOCK_KEYS.items():
    check(f"status.{block}: every declared block key is a catalogue path", all(f"{block}.{k}" in st for k in keys), str(keys))
labels = [sd.display_label(d) for d in sd.DECISION_IDS]
check("status.decisions: all nine I-D labels are catalogue paths", all(f"decisions.{lb}" in st for lb in labels) and len(labels) == 9)
check("status.last_good: generated_at and values", {"last_good.generated_at", "last_good.values"} <= st)
for k in ac.PV_TOMORROW_SUMMARY_KEYS:
    check(f"pv_tomorrow.advice.{k} is a catalogue path", f"advice.{k}" in names(ac.ENTITY_IDS["pv_tomorrow"]))
for k, v in ac.ITEM_UNITS.items():
    check(f"{k}: the catalogue source unit is the contract's {v!r}", by_eid[ac.ENTITY_IDS[k]]["unit"] == v)
check("the non-OK advice shape (status, blocker_codes) is a catalogue path of all seven items and forecasts",
      all({"advice.status", "advice.blocker_codes"} <= names(ac.ENTITY_IDS[k]) for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS))
check("engine_comparison keys are catalogue paths of the charge target", len([n for n in names(ac.ENTITY_IDS["charge_target"]) if n.startswith("engine_comparison.")]) == 6)
check("the contract field that no entity publishes (scorecard_report) is an exception, not silently missing",
      any(e["id"] == "envelope.scorecard_report" and e["reason"] == "not_exposed_in_states" for e in cat["exceptions"]))
check("the coverage function finds no problem with the committed catalogue", G.coverage_problems(cat, G.build_universe()) == [])

# ===========================================================================
print("")
print("[2] the real engine: what one SHADOW cycle publishes is covered")
# ===========================================================================
import _cycle_fixtures as CF  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

DYNAMIC = {"self_test"}      # a dict whose keys are check codes: the keys are data, not attribute names
real_missing: list[str] = []
ok_items: list[str] = []
for label, inputs in (("synthetic decisions recorded", CF.cycle_inputs(synthetic_recorded=True)), ("all decisions open", CF.cycle_inputs()),
                      ("paused", CF.cycle_inputs(paused=True)), ("stale liveness", CF.cycle_inputs(synthetic_recorded=True, stale_liveness=True))):
    env = run_cycle(inputs)
    for eid, (state, rec, unrec) in ac.to_entity_payloads(env).items():
        have = names(eid)
        for k, v in {**rec, **unrec}.items():
            if k not in have:
                real_missing.append(f"{label}: {eid} {k}")
            if isinstance(v, dict) and k not in DYNAMIC:
                real_missing += [f"{label}: {eid} {k}.{kk}" for kk in v if f"{k}.{kk}" not in have]
        if rec.get("status") == "OK" and rec.get("kind") in ac.ITEM_UNITS and label == "synthetic decisions recorded":
            ok_items.append(rec["kind"])
check("every attribute and first-level key the real cycle publishes is in the catalogue (4 situations)", not real_missing, str(real_missing[:6]))
check("the real cycle with recorded synthetic decisions produces OK advice (so real advice shapes were compared)", len(ok_items) >= 1,
      f"OK items: {ok_items}")
print(f"  info  real cycle: OK items with the synthetic decisions recorded: {sorted(ok_items)}")

# ===========================================================================
print("")
print("[3] packages, dashboard, card, live shape")
# ===========================================================================
pkg = G._yaml(ROOT, "home-assistant/packages/ecco_intelligence.yaml")
check("the pause helper is catalogued", "input_boolean.ecco_intel_paused" in by_eid and ac.ENTITY_IDS["paused"] in by_eid)
check("the watchdog is catalogued", "binary_sensor.ecco_intel_watchdog_fresh" in by_eid)
alerts = {f"automation.{G._slug(a['alias'])}": a["id"] for a in pkg["automation"]}
check("all three alert automations are catalogued, by the entity id Home Assistant derives from the alias", len(alerts) == 3 and all(e in by_eid for e in alerts), str(alerts))
check("their source ids carry the automation's own unique id", all(by_eid[e]["id"] == f"intel.automation.{i[len('ecco_intel_'):]}" for e, i in alerts.items()))
check("the raise-only reserve helper (the prefs package) is catalogued", "input_number.ecco_advisory_reserve_raise_pct" in by_eid)
dash = G._yaml(ROOT, "home-assistant/dashboards/ecco_intelligence.yaml")
dash_ents = G._dashboard_entities(ROOT)
check("the dashboard references 13 entities, all catalogued", len(dash_ents) == 13 and all(e in by_eid for e in dash_ents), str(dash_ents))
card = G._card_reads(ROOT)
check("the card's default entities are the contract's 13", sorted(card["entities"]) == sorted(ac.ENTITY_IDS.values()))
all_names = {n.split(".")[0] for s in cat["sources"] for n in (a["name"] for a in s["attributes"])}
check("every attribute name the Production card reads is a catalogue attribute (Geek Mode shows at least all of Production)",
      set(card["attributes"]) <= all_names, str(sorted(set(card["attributes"]) - all_names)))
check("every block key the card reads is a catalogue path of the status entity",
      all(f"{b}.{k}" in st for b, ks in card["blocks"].items() if b in ac.BLOCK_KEYS or b == "last_good" for k in ks))
check("the card's one advice key (binding_constraint) is a catalogue path", "advice.binding_constraint" in names(ac.ENTITY_IDS["charge_target"]))
shape = G.load_shape(ROOT / G.SHAPE_REL)
live = G.compare_live(G.build_universe(), shape)
check("the live shape lists 16 entities, every one declared (nothing UNDECLARED)", live["live_entities"] == 16 and live["undeclared"] == [], str(live["undeclared"][:3]))
check("no declared entity is missing live; the one not checked is the reserve helper (outside the listing's name filter)",
      not [r for r in live["not_present_live"] if r["path"] is None] and live["not_checked_live"] == ["input_number.ecco_advisory_reserve_raise_pct"])
check("every declared-but-absent live attribute is explained as conditional",
      all(r["why"].startswith("conditional") for r in live["not_present_live"]), str([r for r in live["not_present_live"] if not r["why"].startswith("conditional")][:2]))
live_attr_count = sum(1 for (e, p), v in live["attributes"].items() if v["live"] == "PRESENT_LIVE")
check("the live listing's 335 attribute rows are all matched or explained", live_attr_count + len(live["not_present_live"]) >= 335, str(live_attr_count))

# ===========================================================================
print("")
print("[4] reproducibility: the catalogue is a pure function of the code")
# ===========================================================================
S1, O1 = scratch_dir(), scratch_dir()
try:
    copy_read_set(S1)
    rc, out = run_tool("geek_mode_coverage.py", "--repo-root", str(S1), "--out-root", str(O1), "--no-shape")
    check("the tool runs on a scratch copy of the code", rc == 0, out[-300:])
    p = O1 / G.CATALOGUE_REL
    check("the catalogue it writes is byte-identical to the committed one", p.is_file() and p.read_bytes() == (ROOT / G.CATALOGUE_REL).read_bytes())

    # ===========================================================================
    print("")
    print("[5] mutations: each must fail, with the right message")
    # ===========================================================================
    def mutate_scratch(label, edits, expect, *, expect_rc=1):
        d, o = scratch_dir(), scratch_dir()
        try:
            copy_read_set(d)
            for rel, old, new in edits:
                if old == "APPEND":
                    f = d / rel
                    f.write_text(f.read_text(encoding="utf-8") + new, encoding="utf-8", newline="\n")
                else:
                    patch_file(d / rel, old, new)
            rc, out = run_tool("geek_mode_coverage.py", "--repo-root", str(d), "--out-root", str(o), "--no-shape")
            check(f"mutation '{label}' is refused (exit {expect_rc})", rc == expect_rc, f"rc={rc}: {out[-300:]}")
            check(f"mutation '{label}': the message says {expect!r}", expect in out, out[-400:])
        finally:
            cleanup(d, o)

    CONTRACT = "intelligence/advisory_contract.py"
    mutate_scratch("an undeclared attribute added to the contract (list and payload)",
                   [(CONTRACT, 'STATUS_RECORDED = ("mode",', 'STATUS_RECORDED = ("zz_new_attr", "mode",'),
                    (CONTRACT, '"drift": None, "calibration": None, "kind": "status", "status": env.status,',
                     '"drift": None, "calibration": None, "kind": "status", "status": env.status, "zz_new_attr": 1,')],
                   "UNCATALOGUED attribute sensor.ecco_intel_status zz_new_attr")
    mutate_scratch("an attribute added to the contract's list only (nothing publishes it)",
                   [(CONTRACT, 'STATUS_RECORDED = ("mode",', 'STATUS_RECORDED = ("zz_listed_only", "mode",')],
                   "the contract attribute list and the payload the contract builder produces disagree")
    mutate_scratch("an attribute published without being listed",
                   [(CONTRACT, '"drift": None, "calibration": None, "kind": "status", "status": env.status,',
                     '"drift": None, "calibration": None, "kind": "status", "status": env.status, "zz_unlisted": 1,')],
                   "zz_unlisted")
    mutate_scratch("an undeclared advice key in the charge-target advisor",
                   [("intelligence/charge_target.py", 'rec = {"target_soc_pct": target, "raw_target_soc_pct": round(raw, 2), "binding_constraint": binding,',
                     'rec = {"zz_new_advice_key": 1, "target_soc_pct": target, "raw_target_soc_pct": round(raw, 2), "binding_constraint": binding,')],
                   "UNCATALOGUED attribute sensor.ecco_intel_charge_target advice.zz_new_advice_key")
    mutate_scratch("an undeclared key in the pv_tomorrow summary key set",
                   [(CONTRACT, 'PV_TOMORROW_SUMMARY_KEYS = frozenset({"inflation",', 'PV_TOMORROW_SUMMARY_KEYS = frozenset({"zz_pv_key", "inflation",')],
                   "UNCATALOGUED attribute sensor.ecco_intel_pv_tomorrow advice.zz_pv_key")
    mutate_scratch("a new block key",
                   [(CONTRACT, '"accuracy": frozenset({"mae_7d", "coverage_7d", "n"}),', '"accuracy": frozenset({"mae_7d", "coverage_7d", "n", "zz_block"}),')],
                   "UNCATALOGUED attribute sensor.ecco_intel_status accuracy.zz_block")
    mutate_scratch("a new alert automation in the presentation package",
                   [("home-assistant/packages/ecco_intelligence.yaml", "APPEND",
                     '\n  - id: "ecco_intel_alert_zz_new"\n    alias: "ECCO Intel - alert: zz new"\n    triggers:\n      - trigger: homeassistant\n'
                     '        event: start\n    actions: []\n')],
                   "UNCATALOGUED source intel.automation.alert_zz_new")
    mutate_scratch("a new contract entity",
                   [(CONTRACT, '"watchdog_fresh": "binary_sensor.ecco_intel_watchdog_fresh",', '"watchdog_fresh": "binary_sensor.ecco_intel_watchdog_fresh",\n    "zz_extra": "sensor.ecco_intel_zz_extra",')],
                   "ENTITY_IDS holds ['zz_extra'] that this tool does not classify")
    mutate_scratch("a new diagnostics section",
                   [("custom_components/ecco_intelligence/coordinator.py", '"mode": MODE, "versions": {"integration_version"', '"zz_new_section": 1, "mode": MODE, "versions": {"integration_version"')],
                   "UNCATALOGUED diagnostics section zz_new_section")
    mutate_scratch("a new contract envelope field that no entity publishes",
                   [(CONTRACT, "    scorecard_report: Mapping | None = None      # NOT published; never contains 'recommended'",
                     "    scorecard_report: Mapping | None = None      # NOT published; never contains 'recommended'\n    zz_hidden: Mapping | None = None")],
                   "zz_hidden")
    mutate_scratch("a watchdog threshold that no longer follows the integration's constants",
                   [("home-assistant/packages/ecco_intelligence.yaml", "(t - gt) <= 1200", "(t - gt) <= 1500")],
                   "1200 s maximum age derived from the integration constants")

    # ---- mutations of the catalogue itself, found by the coverage function and by --check ----
    cu = G.build_universe()

    def drop_source(c):
        c["sources"] = [s for s in c["sources"] if s["entity_id"] != "sensor.ecco_intel_pv_tomorrow"]

    def drop_attr(c):
        s = next(s for s in c["sources"] if s["entity_id"] == "sensor.ecco_intel_status")
        s["attributes"] = [a for a in s["attributes"] if a["name"] != "pause_control"]

    def invent_attr(c):
        s = next(s for s in c["sources"] if s["entity_id"] == "sensor.ecco_intel_status")
        s["attributes"].append({"name": "invented_value", "description": "x", "unit": None, "priority": "normal"})

    def drop_nested(c):
        s = next(s for s in c["sources"] if s["entity_id"] == "sensor.ecco_intel_charge_target")
        s["attributes"] = [a for a in s["attributes"] if a["name"] != "advice.target_soc_pct"]

    def wrong_id(c):
        next(s for s in c["sources"] if s["entity_id"] == "binary_sensor.ecco_intel_fresh")["id"] = "intel.other"

    for label, fn, expect in (("a source dropped", drop_source, "UNCOVERED source sensor.ecco_intel_pv_tomorrow"),
                              ("an attribute dropped", drop_attr, "UNCOVERED attribute sensor.ecco_intel_status pause_control"),
                              ("a nested attribute dropped", drop_nested, "UNCOVERED attribute sensor.ecco_intel_charge_target advice.target_soc_pct"),
                              ("an invented attribute", invent_attr, "UNAVAILABLE attribute sensor.ecco_intel_status invented_value"),
                              ("a source id changed", wrong_id, "WRONG ID")):
        c = copy.deepcopy(cat)
        fn(c)
        probs = G.coverage_problems(c, cu)
        check(f"coverage_problems finds '{label}'", any(expect in p for p in probs), str(probs[:3]))
        o = scratch_dir()
        try:
            copy_outputs(o)
            (o / G.CATALOGUE_REL).write_bytes(G._json_bytes(c, 4))
            rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(o))
            check(f"--check fails on '{label}' (the committed catalogue no longer equals a regeneration)", rc == 1 and "intelligence.catalogue.json" in out, out[-300:])
        finally:
            cleanup(o)

    # changing one description
    o = scratch_dir()
    try:
        copy_outputs(o)
        p = o / G.CATALOGUE_REL
        txt = p.read_text(encoding="utf-8")
        old = "The one word that says whether ECCO Intelligence has advice for you right now"
        check("the description to change exists", old in txt)
        p.write_text(txt.replace(old, "A word that says whether there is advice"), encoding="utf-8", newline="\n")
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(o))
        check("--check fails when one description is changed (catalogue and ledger bind to its hash)", rc == 1 and "differs" in out and "intelligence.catalogue.json" in out, out[-300:])
        (o / G.LEDGER_MD_REL).write_text((o / G.LEDGER_MD_REL).read_text(encoding="utf-8") + "extra line\n", encoding="utf-8", newline="\n")
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(o))
        check("--check also fails on a hand-edited ledger", rc == 1 and "GEEK_MODE_COVERAGE_LEDGER_intelligence.md" in out, out[-300:])
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(o / "nowhere"))
        check("--check fails when the generated files are missing", rc == 1 and "missing" in out, out[-300:])
    finally:
        cleanup(o)

    # ---- the texts themselves (in process) ----
    def with_text_mutation(label, apply, undo, expect):
        apply()
        try:
            try:
                G.build_catalogue(cu, T)
                check(f"mutation '{label}' is refused", False, "no error raised")
            except G.CoverageError as exc:
                check(f"mutation '{label}': {expect!r}", expect in str(exc), str(exc)[:300])
        finally:
            undo()

    T.COMMON_ATTRS["zz_orphan"] = T.N("an orphan text")
    with_text_mutation("an orphan common text", lambda: None, lambda: T.COMMON_ATTRS.pop("zz_orphan"), "ORPHAN text (common layer) for attribute zz_orphan")
    saved = T.KIND_ATTRS["item"].pop("advice.reserve")
    with_text_mutation("a missing attribute text", lambda: None, lambda: T.KIND_ATTRS["item"].__setitem__("advice.reserve", saved),
                       "UNCATALOGUED attribute sensor.ecco_intel_charge_target advice.reserve")
    saved = T.SOURCES.pop("intel.fresh")
    with_text_mutation("a missing source text", lambda: None, lambda: T.SOURCES.__setitem__("intel.fresh", saved), "UNCATALOGUED source intel.fresh")
    T.SOURCES["intel.ghost"] = dict(group="health", title="x", priority="normal", description="x")
    with_text_mutation("an orphan source text", lambda: None, lambda: T.SOURCES.pop("intel.ghost"), "ORPHAN text for source intel.ghost")
    saved = T.STATUS_ALERTS.pop("STALE")
    with_text_mutation("a status with no alert text", lambda: None, lambda: T.STATUS_ALERTS.__setitem__("STALE", saved), "the system statuses are")
    saved = T.DIAG_COVERED["mode"]
    T.DIAG_COVERED["mode"] = ("zz_not_a_status_attribute",)
    with_text_mutation("a diagnostics section claimed covered by an attribute that does not exist", lambda: None,
                       lambda: T.DIAG_COVERED.__setitem__("mode", saved), "declared covered by status attributes that do not exist")
    T.DIAG_COVERED["zz_gone"] = ("mode",)
    with_text_mutation("a covered diagnostics section that the download no longer has", lambda: None, lambda: T.DIAG_COVERED.pop("zz_gone"),
                       "ORPHAN text for covered diagnostics section zz_gone")
    saved = T.DIAG_SECTIONS.pop("cadence")
    with_text_mutation("a diagnostics section with no text", lambda: None, lambda: T.DIAG_SECTIONS.__setitem__("cadence", saved),
                       "UNCATALOGUED diagnostics section cadence")
    T.ENTITY_ATTRS["intel.status"]["zz_stale_text"] = T.N("a text for an attribute that is gone")
    with_text_mutation("a stale entity text", lambda: None, lambda: T.ENTITY_ATTRS["intel.status"].pop("zz_stale_text"),
                       "ORPHAN text (entity layer, intel.status) for attribute zz_stale_text")
    check("after the mutations the texts build the committed catalogue again", G._json_bytes(G.build_catalogue(cu, T), 4) == (ROOT / G.CATALOGUE_REL).read_bytes())
finally:
    cleanup(S1, O1)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
