#!/usr/bin/env python3
"""Intelligence foundation: intelligence/site_decisions.py, the typed decision register I-D1..I-D9 (synthetic values only).

  [1] ids and the loader: D<n> and I-D<n> both load; unknown keys refused; duplicates refused; no file I/O
  [2] statuses: free text and bare numbers are never RECORDED; I-D9 'garbage' / 42 are INVALID and BLOCK; incomplete
      records are INVALID; the KEEP options of I-D8 need an evidence reference
  [3] provenance: OWNER_RECORD only from the site-local file with a pattern-valid record_ref; a non-accepted provenance
      counts as OPEN; the default acceptance is OWNER_RECORD only
  [4] gates: ITEM_GATES, conditional I-D4 / I-D9, the fixed DST boundary rule, an INVALID I-D7
  [5] required inputs: the code constants, decision-chosen readings, dongle liveness, add-only I-D7
  [6] freshness: the mirror equals ecco_core.freshness's ADVISORY catalogue; overrides tighten-only, unknown refused,
      above the 900 s ceiling INVALID; nothing applies unless I-D6 is satisfied
  [7] apply_to_siteconfig: no example value survives; HA_RESERVE_HELPER / READ_ONLY_SENSOR_SNAPSHOT without a fresh finite
      reading BLOCK; I-D2 never lowers the technical minimum; I-D5 percent / one-way is normalised
  [8] PROPOSED answers are text only and never loadable; reserve roles; import and token rules
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecco_core.freshness import ADVISORY, CATALOGUE  # noqa: E402  (tests may read ecco_core freely)
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.overnight import OvernightSettings  # noqa: E402
from intelligence.timeutil import UTC  # noqa: E402

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "intelligence" / "site_decisions.py"


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


T = sd.Provenance.SYNTHETIC_TEST
O = sd.Provenance.OWNER_RECORD
REF = "REC-20300115-synthetic-test"
NOW = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)
CUT = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)

FLOOR = sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 35.0, True)
PROT = sd.Protection(sd.OWNER_STATEMENT, 12.0, NOW)
CAP = sd.CapacityAuthority("CONFIGURED_HELPER", 20.0)
EFF = sd.Efficiency(0.95, sd.FRACTION, sd.ONE_WAY)
HD1 = sd.HD1Cutover(CUT, sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER)
DST = sd.DSTPolicy(sd.NORMALISE_TO_NOMINAL, sd.SCALE_UP_ONLY)


def full(prov: str = T, **over) -> sd.DecisionSet:
    """Every gating decision RECORDED with SYNTHETIC_TEST values (test values, not recommendations)."""
    vals = {"D1": FLOOR, "D2": PROT, "D3": CAP, "D4": sd.CapacityBand(8.0), "D5": EFF,
            "D6": sd.FreshnessOverrides({"house.power": 300.0}), "D8": HD1, "D9": DST}
    vals.update(over)
    ds = sd.DecisionSet()
    for did, v in vals.items():
        if v is not None:
            ds = ds.with_decision(did, v, prov)
    return ds


def st(key: str, value, fresh=True, limit=300.0) -> sd.InputState:
    return sd.InputState(key, value, fresh, 10.0 if fresh else 9999.0, limit)


WINDOW = (60, 270)                       # 01:00-04:30 local: deliberately NOT the SiteConfig example window (30, 330)
GOOD_READINGS = {"limits.max_grid_charge_w": st("limits.max_grid_charge_w", 5000.0),
                 sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, WINDOW)}
ACC_T = frozenset({T})

# ---------------------------------------------------------------------------------------------------------------------
section("[1] ids and the loader")
check("nine internal ids D1..D9, display labels I-D1..I-D9",
      sd.DECISION_IDS == tuple(f"D{i}" for i in range(1, 10)) and [sd.display_label(d) for d in sd.DECISION_IDS]
      == [f"I-D{i}" for i in range(1, 10)])
check("normalise_id accepts D<n> and I-D<n> only", sd.normalise_id("D4") == "D4" and sd.normalise_id("I-D4") == "D4"
      and sd.normalise_id("D10") is None and sd.normalise_id("i-d4") is None and sd.normalise_id(4) is None)
a = sd.DecisionSet.from_mapping({"D4": {"provenance": T, "value": {"pct": 8.0}}}, source="test")
b = sd.DecisionSet.from_mapping({"I-D4": {"provenance": T, "value": {"pct": 8.0}}}, source="test")
check("D4 and I-D4 load to the same RECORDED decision", a.get("D4") == b.get("D4") and a.status("I-D4") == sd.DecisionStatus.RECORDED)
check("an empty mapping is all OPEN", set(sd.DecisionSet.from_mapping({}, source="test").status_map().values()) == {"OPEN"})
check("DecisionSet() is all OPEN and has all nine", sorted(sd.DecisionSet().decisions) == list(sd.DECISION_IDS)
      and all(d.status == "OPEN" for d in sd.DecisionSet().decisions.values()))
check("an unknown top-level key is refused", raises(lambda: sd.DecisionSet.from_mapping({"D10": {}}, source="test")))
check("an unknown entry key is refused", raises(lambda: sd.DecisionSet.from_mapping({"D4": {"value": {"pct": 8}, "extra": 1}}, source="test")))
check("an unknown key inside a value is refused",
      raises(lambda: sd.DecisionSet.from_mapping({"D4": {"provenance": T, "value": {"pct": 8, "x": 1}}}, source="test")))
check("the same decision under both spellings is refused",
      raises(lambda: sd.DecisionSet.from_mapping({"D4": {"status": "OPEN"}, "I-D4": {"status": "OPEN"}}, source="test")))
check("an unknown source is refused", raises(lambda: sd.DecisionSet.from_mapping({}, source="internet")))
check("a non-mapping block or entry is refused", raises(lambda: sd.DecisionSet.from_mapping([], source="test"))
      and raises(lambda: sd.DecisionSet.from_mapping({"D1": "OPEN"}, source="test")))
check("'_comment' style keys are documentation and ignored",
      sd.DecisionSet.from_mapping({"_comment": "x", "I-D1": {"status": "OPEN"}}, source="test").status("D1") == "OPEN")
rt = sd.DecisionSet.from_mapping(json.loads(json.dumps({sd.display_label(k): {"status": "RECORDED", "provenance": T,
                                                                                 "value": v.to_dict()}
                                                        for k, v in (("D1", FLOOR), ("D2", PROT), ("D3", CAP), ("D5", EFF),
                                                                     ("D8", HD1), ("D9", DST))})), source="test")
check("typed values survive a JSON round trip and load RECORDED", all(rt.status(d) == "RECORDED" for d in ("D1", "D2", "D3", "D5", "D8", "D9"))
      and rt.value("D8").cutover == CUT and rt.value("D2").observed_at == NOW, str(rt.status_map()))
check("status_map uses display labels", list(sd.DecisionSet().status_map()) == [f"I-D{i}" for i in range(1, 10)])

# ---------------------------------------------------------------------------------------------------------------------
section("[2] statuses: free text is never RECORDED")
for did, text in (("D1", "SiteConfig.user_reserve_soc_pct"), ("D3", "CONFIGURED_HELPER"), ("D5", "ROUND_TRIP"),
                  ("D9", "NORMALISE_PER_HOUR"), ("D8", "2030-03-10T12:00:00+00:00"), ("D4", 8.0), ("D6", {"house.power": 1})):
    d = sd.decide(did, text, T)
    check(f"{sd.display_label(did)} free text / bare value {text!r} is INVALID", d.status == "INVALID" and d.value is None, str(d))
for junk in ("garbage", 42, None, ["NORMALISE_TO_NOMINAL"], {"history_rule": "garbage", "target_rule": "SCALE_UP_ONLY"}):
    ds = sd.DecisionSet.from_mapping({"I-D9": {"status": "RECORDED", "provenance": T, "value": junk}}, source="test")
    gi = sd.gate("charge_target", ds, sd.GateContext(clock_change_in_scope=True), ACC_T)
    check(f"I-D9 {junk!r} is INVALID and BLOCKs a gated item (DECISION_D9_INVALID)",
          ds.status("D9") == "INVALID" and "DECISION_D9_INVALID" in [f.code for f in gi if f.severity == sd.BLOCK], str(ds.get("D9")))
check("an incomplete record (I-D8 without its policies) is INVALID",
      sd.DecisionSet.from_mapping({"D8": {"provenance": T, "value": {"cutover": "2030-01-01T00:00:00+00:00"}}}, source="test").status("D8") == "INVALID")
check("an OPEN entry with a value is INVALID", sd.DecisionSet.from_mapping({"D4": {"status": "OPEN", "value": {"pct": 8}}}, source="test").status("D4") == "INVALID")
check("status INVALID cannot be declared", sd.DecisionSet.from_mapping({"D4": {"status": "INVALID"}}, source="test").status("D4") == "INVALID")
check("HA_RESERVE_HELPER is a valid I-D1 source (no value: it is read at every cycle)",
      sd.decide("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), T).status == "RECORDED")
check("... but a recorded helper number is refused (it would go stale)",
      sd.decide("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, 25.0, True), T).status == "INVALID")
check("INTELLIGENCE_USER_RESERVE and NEW_SINGLE_SETTING need a value",
      sd.decide("D1", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, None, True), T).status == "INVALID"
      and sd.decide("D1", sd.PlanningFloor(sd.NEW_SINGLE_SETTING, 101.0, True), T).status == "INVALID")
check("advice_honours must be stated as a boolean", sd.decide("D1", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 40.0), T).status == "INVALID")
check("an unknown floor source is INVALID", sd.decide("D1", sd.PlanningFloor("THE_HELPER", 40.0, True), T).status == "INVALID")
check("I-D2 owner statement needs a value and an aware observed_at; a snapshot carries no value",
      sd.decide("D2", sd.Protection(sd.OWNER_STATEMENT, 10.0, None), T).status == "INVALID"
      and sd.decide("D2", sd.Protection(sd.OWNER_STATEMENT, 10.0, datetime(2030, 1, 1)), T).status == "INVALID"
      and sd.decide("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT, None, None), T).status == "RECORDED"
      and sd.decide("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT, 10.0, None), T).status == "INVALID")
check("I-D3: EXAMPLE_DEFAULT is never an authority; Ah resolved at run needs a voltage; implausible kWh refused",
      sd.decide("D3", sd.CapacityAuthority("EXAMPLE_DEFAULT", 31.7), T).status == "INVALID"
      and sd.decide("D3", sd.CapacityAuthority("REGISTER_AH", None, True), T).status == "INVALID"
      and sd.decide("D3", sd.CapacityAuthority("REGISTER_AH", None, True, 51.2), T).status == "RECORDED"
      and sd.decide("D3", sd.CapacityAuthority("CONFIGURED_HELPER", 31700.0), T).status == "INVALID"
      and sd.decide("D3", sd.CapacityAuthority("SITECONFIG_VALUE", None, True), T).status == "INVALID"
      and sd.decide("D3", sd.CapacityAuthority("CONFIGURED_HELPER", 20.0, True), T).status == "INVALID")
check("I-D4 band must be in (0, 50]", sd.decide("D4", sd.CapacityBand(0.0), T).status == "INVALID"
      and sd.decide("D4", sd.CapacityBand(float("nan")), T).status == "INVALID" and sd.decide("D4", sd.CapacityBand(8.0), T).status == "RECORDED")
check("I-D5 without a unit or basis is INVALID", sd.decide("D5", sd.Efficiency(0.9, None, sd.ROUND_TRIP), T).status == "INVALID"
      and sd.decide("D5", sd.Efficiency(0.9, sd.FRACTION, None), T).status == "INVALID")
for pol, ref, ok in ((sd.KEEP_NON_EXPORTING_ONLY, None, False), (sd.KEEP_NON_EXPORTING_ONLY, "evidence.txt", False),
                     (sd.KEEP_NON_EXPORTING_ONLY, REF, True), (sd.EXCLUDE, None, True), (sd.EXCLUDE, "C:/x", False)):
    d = sd.decide("D8", sd.HD1Cutover(CUT, pol, sd.EXCLUDE_PRE_CUTOVER, ref), T)
    check(f"I-D8 power policy {pol} with evidence {ref!r} -> {'RECORDED' if ok else 'INVALID'}", (d.status == "RECORDED") == ok, str(d.problems))
check("I-D8 KEEP_AFTER_COUNTER_CHECK needs an evidence reference",
      sd.decide("D8", sd.HD1Cutover(CUT, sd.EXCLUDE, sd.KEEP_AFTER_COUNTER_CHECK), T).status == "INVALID")
check("I-D8 cut-over must be aware", sd.decide("D8", sd.HD1Cutover(datetime(2030, 1, 1), sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER), T).status == "INVALID")
check("KEEP_PRE_CUTOVER_LOAD does not exist", "KEEP_PRE_CUTOVER_LOAD" not in SRC.read_text(encoding="utf-8"))
check("a RECORDED decision cannot be constructed with a problem or the wrong type",
      raises(lambda: sd.Decision("D4", "RECORDED", 8.0, T)) and raises(lambda: sd.Decision("D4", "OPEN", sd.CapacityBand(8.0))))
check("the invariants live on the type: a directly built RECORDED decision with an invalid value is refused "
      "(I-D6 loosening SOC / above the ceiling, I-D1 at 150 %)",
      raises(lambda: sd.Decision("D6", "RECORDED", sd.FreshnessOverrides({"battery.soc": 86400.0}), T))
      and raises(lambda: sd.Decision("D6", "RECORDED", sd.FreshnessOverrides({"house.power": 99999.0}), T))
      and raises(lambda: sd.Decision("D1", "RECORDED", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 150.0, True), T)))
check("... a RECORDED decision needs a known provenance, and an OWNER_RECORD a full-match record_ref",
      raises(lambda: sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), None))
      and raises(lambda: sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), "OWNER"))
      and raises(lambda: sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), O, None))
      and raises(lambda: sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), O, REF + "\n"))
      and raises(lambda: sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), T, "not-a-ref")))
check("... an OPEN decision carries nothing; an INVALID one names a problem",
      raises(lambda: sd.Decision("D4", "OPEN", None, T)) and raises(lambda: sd.Decision("D4", "OPEN", None, None, REF))
      and raises(lambda: sd.Decision("D4", "INVALID")) and sd.Decision("D4", "INVALID", None, None, None, ("x",)).status == "INVALID")
_own_d = sd.Decision("D4", "RECORDED", sd.CapacityBand(8.0), O, REF)
check("an OWNER_RECORD decision object fits only a site-local DecisionSet",
      all(raises(lambda s=s: sd.DecisionSet({"D4": _own_d}, source=s)) for s in ("test", "example_profile", "declaration"))
      and sd.DecisionSet({"D4": _own_d}, source="site_local").satisfied("D4"))
check("an OWNER_RECORD is never minted in code: decide / with_decision give INVALID, even on a site-local set",
      sd.decide("D4", sd.CapacityBand(8.0), O, REF, source="site_local").status == "INVALID"
      and sd.DecisionSet(source="site_local").with_decision("D4", sd.CapacityBand(8.0), O, REF).status("D4") == "INVALID"
      and not sd.DecisionSet(source="site_local").with_decision("D4", sd.CapacityBand(8.0), O, REF).satisfied("D4"))
_mut = sd.decide("D6", sd.FreshnessOverrides({"house.power": 300.0}), T)
object.__setattr__(_mut.value, "limits_s", {"house.power": 99999.0, "battery.soc": 86400.0})
_mut_set = sd.DecisionSet({"D6": _mut})
_mut_lim, _mut_notes = sd.freshness_limits(_mut_set, frozenset({T}))
check("a RECORDED record mutated after construction never counts: not satisfied, nothing applied, I-D6 BLOCKs",
      not sd.satisfied(_mut, frozenset({T})) and _mut_lim["house.power"] is None and _mut_lim["battery.soc"] == 900.0
      and "DECISION_D6_INVALID" in [f.code for f in _mut_notes if f.blocks]
      and "DECISION_D6_INVALID" in [f.code for f in sd.gate("export_event", _mut_set, accept_provenance=frozenset({T}))],
      str([(f.code, f.severity) for f in _mut_notes]))

# ---------------------------------------------------------------------------------------------------------------------
section("[3] provenance and acceptance")
check("the default acceptance is OWNER_RECORD only", sd.DEFAULT_ACCEPT_PROVENANCE == frozenset({"OWNER_RECORD"}))
own = {"I-D4": {"status": "RECORDED", "provenance": O, "record_ref": REF, "value": {"pct": 8.0}}}
check("an OWNER_RECORD with a valid record_ref from the site-local file is RECORDED and satisfied",
      sd.DecisionSet.from_mapping(own, source="site_local").satisfied("D4"))
for src in ("test", "example_profile", "declaration"):
    check(f"an OWNER_RECORD from source {src!r} is refused (INVALID)", sd.DecisionSet.from_mapping(own, source=src).status("D4") == "INVALID")
for bad_ref in (None, "", "REC-2030-x", "REC-20300115-AB", "REC-20300115-ab", "../private/records/rec.md", "REC-20300115-" + "a" * 70, 12,
                REF + "\n", " " + REF):
    m = {"I-D4": {"status": "RECORDED", "provenance": O, "record_ref": bad_ref, "value": {"pct": 8.0}}}
    check(f"an OWNER_RECORD with record_ref {bad_ref!r} is refused", sd.DecisionSet.from_mapping(m, source="site_local").status("D4") == "INVALID")
check("record references are matched over the whole string (fullmatch): a trailing newline is refused for the I-D8 evidence too",
      sd.decide("D8", sd.HD1Cutover(CUT, sd.KEEP_NON_EXPORTING_ONLY, sd.EXCLUDE_PRE_CUTOVER, REF + "\n"), T).status == "INVALID"
      and sd.decide("D8", sd.HD1Cutover(CUT, sd.KEEP_NON_EXPORTING_ONLY, sd.EXCLUDE_PRE_CUTOVER, REF), T).status == "RECORDED")
check("an unknown provenance is INVALID", sd.decide("D4", sd.CapacityBand(8.0), "OWNER").status == "INVALID")
syn = full()
check("a SYNTHETIC_TEST record is RECORDED but not satisfied under the default acceptance",
      syn.status("D1") == "RECORDED" and not syn.satisfied("D1") and syn.satisfied("D1", ACC_T))
g_default = [f.code for f in sd.gate("charge_target", syn)]
check("... so the gate treats it as OPEN (DECISION_D<n>_OPEN), naming the provenance",
      g_default == ["DECISION_D1_OPEN", "DECISION_D2_OPEN", "DECISION_D3_OPEN", "DECISION_D5_OPEN", "DECISION_D8_OPEN"]
      and "SYNTHETIC_TEST" in sd.gate("charge_target", syn)[0].text, str(g_default))
check("with SYNTHETIC_TEST explicitly accepted the same set passes the decision gate", sd.gate("charge_target", syn, accept_provenance=ACC_T) == [])
check("provenance_ok is False when a recorded provenance is not accepted", not syn.provenance_ok() and syn.provenance_ok(ACC_T)
      and sd.DecisionSet().provenance_ok())
check("satisfied(None) is False", not sd.satisfied(None))

# ---------------------------------------------------------------------------------------------------------------------
section("[4] gates")
check("ITEM_GATES covers exactly the items, with the contract's decision sets",
      dict(sd.ITEM_GATES) == {"overnight_demand": ("D8",), "charge_target": ("D1", "D2", "D3", "D5", "D8"),
                              "export_event": ("D1", "D2", "D3", "D5", "D6", "D8"), "dump_to_grid": ("D1", "D2", "D3", "D5", "D6", "D8"),
                              "v1_summary": ("D1", "D2", "D3", "D5", "D8"), "predicted_morning_soc": ("D1", "D2", "D3", "D5", "D8"),
                              "predicted_day_load": ("D8",), "pv_tomorrow": ()})
check("no item is gated on the retired I-D7", not [i for i, g in sd.ITEM_GATES.items() if "D7" in g])
allopen = sd.DecisionSet()
check("all OPEN: every gated item BLOCKs; pv_tomorrow does not",
      all(sd.blocking(sd.gate(i, allopen)) for i in sd.ITEMS if i != "pv_tomorrow") and sd.gate("pv_tomorrow", allopen) == [])
check("an unknown item raises", raises(lambda: sd.gate("free_power", allopen)))
nob4 = full(D4=None).without("D4")
check("I-D4 is required only when two or more capacity sources are present",
      sd.gate("charge_target", nob4, sd.GateContext(capacity_sources=1), ACC_T) == []
      and [f.code for f in sd.gate("charge_target", nob4, sd.GateContext(capacity_sources=2), ACC_T)] == ["DECISION_D4_OPEN"])
check("with I-D4 satisfied, a mismatch beyond the band BLOCKs and one within it passes",
      [f.code for f in sd.gate("charge_target", syn, sd.GateContext(2, 9.0), ACC_T)] == ["CAPACITY_MISMATCH_BEYOND_BAND"]
      and sd.gate("charge_target", syn, sd.GateContext(2, 7.9), ACC_T) == [])
check("with two or more sources and a mismatch that cannot be computed, a satisfied I-D4 still BLOCKs",
      [f.code for f in sd.gate("charge_target", syn, sd.GateContext(2, None), ACC_T)] == ["CAPACITY_MISMATCH_UNKNOWN"])
_cap_rd = {"capacity.helper_kwh": st("capacity.helper_kwh", 20.0), "capacity.fe1_wh_per_pct": st("capacity.fe1_wh_per_pct", 201.0),
           "capacity.reg204_ah": st("capacity.reg204_ah", 400.0, fresh=False)}
_volt = full(D3=sd.CapacityAuthority("CONFIGURED_HELPER", 20.0, False, 51.2))
n_v, mm_v = sd.capacity_sources_context(_volt, _cap_rd, ACC_T)
check("capacity_sources_context converts every present source to kWh (FE-1 Wh/% x 100 / 1000, Ah x the stated voltage) "
      "and counts a stale one", n_v == 4 and mm_v is not None and abs(mm_v - (20.48 - 20.0) / 20.24 * 100.0) < 1e-9, str((n_v, mm_v)))
n_nv, mm_nv = sd.capacity_sources_context(syn, _cap_rd, ACC_T)
check("... an Ah reading without a stated voltage counts as a source but makes the difference unknown (None)",
      n_nv == 4 and mm_nv is None, str((n_nv, mm_nv)))
check("... a stated I-D3 value counts only when I-D3 is satisfied; nothing present gives (0, None)",
      sd.capacity_sources_context(syn, {}, ACC_T) == (1, None) and sd.capacity_sources_context(syn, {}) == (0, None)
      and sd.capacity_sources_context(allopen, {"capacity.helper_kwh": st("capacity.helper_kwh", float("nan"))}) == (0, None))
check("... raw readings in mixed units are never compared directly (201 Wh/% and 400 Ah are not a 181 % mismatch)",
      sd.capacity_sources_context(_volt, {"capacity.fe1_wh_per_pct": st("capacity.fe1_wh_per_pct", 201.0)}, ACC_T)[1] < 1.0)
nob9 = syn.without("D9")
check("I-D9 is required only when a clock change is in scope, and only for period items",
      sd.gate("charge_target", nob9, sd.GateContext(), ACC_T) == []
      and [f.code for f in sd.gate("charge_target", nob9, sd.GateContext(clock_change_in_scope=True), ACC_T)] == ["DECISION_D9_OPEN"]
      and sd.gate("export_event", nob9, sd.GateContext(clock_change_in_scope=True), ACC_T) == [])
check("the fixed DST rule BLOCKs a boundary in a changed hour even with I-D9 recorded",
      [f.code for f in sd.gate("overnight_demand", syn, sd.GateContext(clock_change_in_scope=True, boundary_in_changed_hour=True), ACC_T)]
      == ["DST_BOUNDARY_IN_CHANGED_HOUR"])
bad7 = syn.with_decision("D7", sd.RequiredInputsOverride({"charge_target": ("no.such_signal",)}), T)
check("an INVALID I-D7 BLOCKs every item, pv_tomorrow included",
      bad7.status("D7") == "INVALID" and all("DECISION_D7_INVALID" in [f.code for f in sd.gate(i, bad7, accept_provenance=ACC_T)] for i in sd.ITEMS))
bad9 = sd.DecisionSet({**syn.decisions, "D9": sd.DecisionSet.from_mapping({"D9": {"value": "garbage"}}, source="test").get("D9")})
check("an INVALID I-D9 BLOCKs its items even with no clock change in scope (INVALID always BLOCKs)",
      all("DECISION_D9_INVALID" in [f.code for f in sd.gate(i, bad9, sd.GateContext(), ACC_T)] for i in sd.CONDITIONAL_D9_ITEMS)
      and sd.gate("export_event", bad9, sd.GateContext(), ACC_T) == [] and sd.gate("pv_tomorrow", bad9, sd.GateContext(), ACC_T) == [])
bad4 = sd.DecisionSet({**syn.decisions, "D4": sd.DecisionSet.from_mapping(
    {"D4": {"provenance": T, "value": {"pct": 99}}}, source="test").get("D4")})
check("an INVALID I-D4 BLOCKs every capacity item even with a single capacity source",
      bad4.status("D4") == "INVALID"
      and all("DECISION_D4_INVALID" in [f.code for f in sd.gate(i, bad4, sd.GateContext(capacity_sources=1), ACC_T)]
              for i in sd.CONDITIONAL_D4_ITEMS)
      and [f.code for f in sd.gate("charge_target", bad4, sd.GateContext(capacity_sources=2), ACC_T)].count("DECISION_D4_INVALID") == 1)
check("items_gated_by is the inverse of ITEM_GATES plus the conditional items",
      sd.items_gated_by("D8") == sd.ITEMS[:-1] and sd.items_gated_by("D6") == ("export_event", "dump_to_grid")
      and sd.items_gated_by("D7") == () and sd.items_gated_by("D9") == sd.CONDITIONAL_D9_ITEMS
      and set(sd.items_gated_by("D4")) == {i for i in sd.ITEMS if "D3" in sd.ITEM_GATES[i]})
lb = OvernightSettings().lookback_nights
check("the overnight lookback is 28 nights", lb == 28)
check("clock_change_in_scope: within 28 nights after 25 Oct 2026 -> True; 40 nights after -> False",
      sd.clock_change_in_scope(datetime(2026, 11, 10, 12, tzinfo=UTC), (), lb)
      and not sd.clock_change_in_scope(datetime(2026, 12, 4, 12, tzinfo=UTC), (), lb))
check("... a target period across the spring change -> True",
      sd.clock_change_in_scope(datetime(2027, 3, 27, 12, tzinfo=UTC),
                               ((datetime(2027, 3, 27, 22, tzinfo=UTC), datetime(2027, 3, 28, 5, tzinfo=UTC)),), lb))
check("... a naive now is refused", raises(lambda: sd.clock_change_in_scope(datetime(2027, 3, 27), (), lb)))

# ---------------------------------------------------------------------------------------------------------------------
section("[5] required inputs")
ri = sd.required_inputs("charge_target", allopen)
check("charge_target: SOC + history, the grid-charge limit, dongle liveness, a charge-window source",
      ri.signals == ("battery.soc", "history.hourly") and "limits.max_grid_charge_w" in ri.readings
      and sd.LIVENESS_KEY in ri.readings and ri.charge_window_sources == ("tariff.import_rates", "tou.slot_table"), str(ri))
pv = sd.required_inputs("pv_tomorrow", allopen)
check("pv_tomorrow: history, the tomorrow forecast and the pv_array_kwp site fact; no dongle input so no liveness",
      pv.signals == ("history.hourly",) and pv.readings == ("pv.forecast_tomorrow_kwh",) and pv.site_facts == ("pv_array_kwp",))
check("every item with a dongle-sourced input needs the liveness reading",
      all(sd.LIVENESS_KEY in sd.required_inputs(i, allopen).readings for i in sd.ITEMS
          if any(s in sd.DONGLE_SIGNALS for s in sd.REQUIRED_SIGNALS[i])))
check("export_event and dump_to_grid need every power, the inverter health and their readings",
      set(sd._POWERS) <= set(sd.required_inputs("export_event", allopen).signals)
      and "stop.dump_soc_pct" in sd.required_inputs("dump_to_grid", allopen).readings
      and "tariff.export_rates" in sd.required_inputs("export_event", allopen).readings
      and "tariff.export_rates" in sd.required_inputs("dump_to_grid", allopen).readings)
check("export_event and dump_to_grid need a charge-window source too (their refill window is never the example window)",
      all(sd.required_inputs(i, allopen).charge_window_sources == ("tariff.import_rates", "tou.slot_table")
          for i in ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc", "v1_summary"))
      and sd.required_inputs("overnight_demand", allopen).charge_window_sources == ())
helper = syn.with_decision("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), T).with_decision(
    "D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT), T).with_decision("D3", sd.CapacityAuthority("REGISTER_AH", None, True, 51.2), T)
rh = sd.required_inputs("charge_target", helper, ACC_T)
check("the chosen I-D1 / I-D2 / I-D3 sources bring their readings (helper, shutdown sensor, Ah register)",
      "reserve.ha_minimum_soc" in rh.signals and "protection.shutdown_soc_pct" in rh.readings and "capacity.reg204_ah" in rh.readings, str(rh))
check("... but only when those decisions are satisfied", "reserve.ha_minimum_soc" not in sd.required_inputs("charge_target", helper).signals)
add7 = allopen.with_decision("D7", sd.RequiredInputsOverride({"overnight_demand": ("house.power",)}, {"pv_tomorrow": ("tou.slot_table",)}), T)
check("a recorded I-D7 only ADDS (and brings liveness for a dongle input)",
      sd.required_inputs("overnight_demand", add7).signals == ("history.hourly", "house.power")
      and sd.LIVENESS_KEY in sd.required_inputs("overnight_demand", add7).readings
      and "tou.slot_table" in sd.required_inputs("pv_tomorrow", add7).readings)
check("every reading named by the gates is a gate reading key", set(sd.GATE_READING_KEYS) >= {r for rs in sd.REQUIRED_READINGS.values() for r in rs})
check("every required signal is a known ecco_core.state signal",
      all(sd.spec_for(s) is not None for ss in sd.REQUIRED_SIGNALS.values() for s in ss))

# ---------------------------------------------------------------------------------------------------------------------
section("[6] freshness")
adv = {lim.signal: lim.max_age_s for lim in CATALOGUE if lim.purpose == ADVISORY}
check("ADVISORY_LIMITS_S equals ecco_core.freshness's ADVISORY catalogue exactly (drift test)", dict(sd.ADVISORY_LIMITS_S) == adv, str(adv))
check("SOC 900 s, history 6 h, everything else unresolved",
      sd.ADVISORY_LIMITS_S["battery.soc"] == 900.0 and sd.ADVISORY_LIMITS_S["history.hourly"] == 21600.0
      and all(v is None for k, v in sd.ADVISORY_LIMITS_S.items() if k not in ("battery.soc", "history.hourly")))
check("the ceiling is 900 s, equal to the SOC advisory limit", sd.PROPOSED_FRESHNESS_CEILING_S == 900.0 == sd.ADVISORY_LIMITS_S["battery.soc"])
lim0, n0 = sd.freshness_limits(allopen)
check("with I-D6 OPEN every gate reading and unresolved signal is None (never fresh)",
      all(lim0[k] is None for k in lim0 if k not in ("battery.soc", "history.hourly")) and n0 == []
      and "limits.max_grid_charge_w" in lim0 and lim0["limits.max_grid_charge_w"] is None)


def d6(limits: dict) -> sd.DecisionSet:
    return allopen.with_decision("D6", sd.FreshnessOverrides(limits), T)


good = d6({"house.power": 300.0, "battery.soc": 120.0, "limits.max_grid_charge_w": 900.0})
lim1, _ = sd.freshness_limits(good, ACC_T)
check("a satisfied I-D6 supplies and tightens limits", lim1["house.power"] == 300.0 and lim1["battery.soc"] == 120.0
      and lim1["limits.max_grid_charge_w"] == 900.0 and lim1["pv.power"] is None)
lim_na, _ = sd.freshness_limits(good)
check("... but applies nothing when its provenance is not accepted", lim_na["house.power"] is None and lim_na["battery.soc"] == 900.0)
for bad, code in (({"battery.soc": 1000.0}, "FRESHNESS_OVERRIDE_REFUSED"), ({"house.power": 901.0}, "FRESHNESS_OVERRIDE_ABOVE_CEILING"),
                  ({"house.power": 0.0}, "FRESHNESS_OVERRIDE_INVALID"), ({"house.power": float("inf")}, "FRESHNESS_OVERRIDE_INVALID"),
                  ({"house.power": True}, "FRESHNESS_OVERRIDE_INVALID"), ({"house.powr": 60.0}, "FRESHNESS_OVERRIDE_UNKNOWN_KEY"),
                  ({sd.LIVENESS_KEY: 60.0}, "FRESHNESS_OVERRIDE_UNKNOWN_KEY"), ({"pv.forecast_tomorrow_kwh": 60.0}, "FRESHNESS_OVERRIDE_UNKNOWN_KEY")):
    ds = d6({**bad, "pv.power": 60.0})
    lim, notes = sd.freshness_limits(ds, ACC_T)
    check(f"I-D6 {bad} is INVALID ({code}); nothing is applied and it BLOCKs",
          ds.status("D6") == "INVALID" and code in [f.code for f in notes] and "DECISION_D6_INVALID" in [f.code for f in notes if f.blocks]
          and lim["pv.power"] is None, str([f.code for f in notes]))
check("history.hourly may be tightened below 6 h (a defined limit is not capped by the ceiling)",
      d6({"history.hourly": 3600.0}).status("D6") == "RECORDED")
check("an INVALID I-D6 BLOCKs export_event", "DECISION_D6_INVALID" in [f.code for f in sd.gate("export_event", full(D6=sd.FreshnessOverrides({"house.power": 5000.0})), accept_provenance=ACC_T)])
CCR_KEYS = ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events", "tou.current_target_soc_pct")
check("CCR-DQ-1 / CCR-PLAN-1: the qualifying and planning readings are I-D6 keys, each once, with no default limit (None: "
      "never fresh until a site records one)",
      sd.QUALIFYING_READING_KEYS == ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events")
      and sd.PLANNING_READING_KEYS == ("tou.current_target_soc_pct",)
      and all(sd.FRESHNESS_OVERRIDE_KEYS.count(k) == 1 and k in lim0 and lim0[k] is None for k in CCR_KEYS)
      and not any(k in sd.ADVISORY_LIMITS_S for k in CCR_KEYS), str({k: lim0.get(k, "absent") for k in CCR_KEYS}))
lim_ccr, _ = sd.freshness_limits(d6({k: 600.0 for k in CCR_KEYS}), ACC_T)
check("... a satisfied I-D6 supplies them (capped by the 900 s ceiling like every unresolved key)",
      all(lim_ccr[k] == 600.0 for k in CCR_KEYS) and d6({"tariff.events": 901.0}).status("D6") == "INVALID"
      and d6({"tou.current_target_soc_pct": 901.0}).status("D6") == "INVALID")

# ---------------------------------------------------------------------------------------------------------------------
section("[7] apply_to_siteconfig: no fallbacks")
base = SiteConfig()
cfg, notes = sd.apply_to_siteconfig(base, syn, GOOD_READINGS, ACC_T)
check("fully satisfied with a fresh grid-charge limit and charge window -> a SiteConfig built only from the decisions",
      cfg is not None and cfg.user_reserve_soc_pct == 35.0 and cfg.technical_min_soc_pct == 12.0 and cfg.battery_capacity_kwh == 20.0
      and abs(cfg.round_trip_efficiency - 0.9025) < 1e-12 and cfg.max_grid_charge_kw == 5.0
      and (cfg.cheap_window_start_min, cfg.cheap_window_end_min) == WINDOW, str([f.code for f in notes]))
_no_w = {k: v for k, v in GOOD_READINGS.items() if k != sd.CHARGE_WINDOW_KEY}
check("no fresh charge window -> None with CHARGE_WINDOW_UNKNOWN (the example cheap window 00:30-05:30 is never kept)",
      all(sd.apply_to_siteconfig(base, syn, rd, ACC_T)[0] is None
          and "CHARGE_WINDOW_UNKNOWN" in [f.code for f in sd.apply_to_siteconfig(base, syn, rd, ACC_T)[1] if f.blocks]
          for rd in (_no_w, {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, WINDOW, fresh=False)},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, WINDOW, limit=None)},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, (330, 30))},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, (30.0, 330.0))},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, (True, 330))},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, (0, 1500))},
                     {**_no_w, sd.CHARGE_WINDOW_KEY: st(sd.CHARGE_WINDOW_KEY, "00:30-05:30")})))
check("I-D5 one-way 0.95 is normalised to round-trip 0.9025; 90 percent round-trip to 0.90",
      abs(sd.efficiency_round_trip(sd.Efficiency(90.0, sd.PERCENT, sd.ROUND_TRIP))[0] - 0.9) < 1e-12
      and abs(sd.efficiency_round_trip(EFF)[0] - 0.9025) < 1e-12)
cfg_none, n_none = sd.apply_to_siteconfig(base, syn, GOOD_READINGS)
check("the same set under the default acceptance -> None (nothing kept from the example)", cfg_none is None
      and {"DECISION_D1_OPEN", "DECISION_D2_OPEN", "DECISION_D3_OPEN", "DECISION_D5_OPEN"} <= {f.code for f in n_none})
check("all OPEN -> None", sd.apply_to_siteconfig(base, allopen, GOOD_READINGS, ACC_T)[0] is None)
check("no fresh grid-charge limit -> None (the example 8 kW is never kept)",
      sd.apply_to_siteconfig(base, syn, {}, ACC_T)[0] is None
      and sd.apply_to_siteconfig(base, syn, {"limits.max_grid_charge_w": st("limits.max_grid_charge_w", 5000.0, fresh=False)}, ACC_T)[0] is None
      and sd.apply_to_siteconfig(base, syn, {"limits.max_grid_charge_w": st("limits.max_grid_charge_w", 5000.0, limit=None)}, ACC_T)[0] is None)
_gl = [f for f in sd.apply_to_siteconfig(base, syn, {}, ACC_T)[1] if f.code == "GRID_CHARGE_LIMIT_UNKNOWN"]
_sc_cfg, _sc_notes = sd.apply_to_siteconfig(base, syn, {**GOOD_READINGS, "limits.max_grid_charge_w": st("limits.max_grid_charge_w", 60000.0)}, ACC_T)
_sci = [f for f in _sc_notes if f.code == "SITECONFIG_INVALID"]
_eff = sd.efficiency_round_trip(sd.Efficiency(0.3, sd.FRACTION, sd.ROUND_TRIP))[2]
check("CCR-PLAN-4: the grid-limit, site-configuration and efficiency-range texts state no value; the numbers and the "
      "exception are evidence only",
      len(_gl) == 1 and not any(ch.isdigit() for ch in _gl[0].text)
      and _sc_cfg is None and len(_sci) == 1 and not any(ch.isdigit() for ch in _sci[0].text)
      and dict(_sci[0].evidence).get("error_type") == "ValueError" and "max_grid_charge_kw" in str(dict(_sci[0].evidence).get("error"))
      and _eff is not None and _eff.code == "EFFICIENCY_OUT_OF_RANGE" and not any(ch.isdigit() for ch in _eff.text)
      and dict(_eff.evidence) == {"fraction": 0.3, "lower": 0.5, "upper": 1.0},
      str((_gl and _gl[0].text, _sci and _sci[0].text, _eff and (_eff.text, _eff.evidence))))
hs = syn.with_decision("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), T)
for label, rd in (("missing", {}), ("stale", {"reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", 25.0, fresh=False)}),
                  ("no defined limit", {"reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", 25.0, limit=None)}),
                  ("non-numeric", {"reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", "unavailable")}),
                  ("NaN", {"reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", float("nan"))})):
    c, n = sd.apply_to_siteconfig(base, hs, {**GOOD_READINGS, **rd}, ACC_T)
    check(f"HA_RESERVE_HELPER with a {label} helper reading BLOCKs (no example-40 or placeholder fallback)",
          c is None and "RESERVE_HELPER_NOT_FRESH" in [f.code for f in n if f.blocks])
for bad_helper in (150.0, -1.0, 100.5):
    c, n = sd.apply_to_siteconfig(base, hs, {**GOOD_READINGS, "reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", bad_helper)}, ACC_T)
    check(f"HA_RESERVE_HELPER with an out-of-range helper reading {bad_helper} % BLOCKs (RESERVE_HELPER_OUT_OF_RANGE)",
          c is None and "RESERVE_HELPER_OUT_OF_RANGE" in [f.code for f in n if f.blocks])
c, n = sd.apply_to_siteconfig(base, hs, {**GOOD_READINGS, "reserve.ha_minimum_soc": st("reserve.ha_minimum_soc", 25.0)}, ACC_T)
check("HA_RESERVE_HELPER with a fresh helper: user reserve := technical minimum (the helper raises it at run time)",
      c is not None and c.user_reserve_soc_pct == c.technical_min_soc_pct == 12.0 and c.effective_reserve(25.0).effective_pct == 25.0)
ss = syn.with_decision("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT), T)
for label, rd in (("missing", {}), ("stale", {"protection.shutdown_soc_pct": st("protection.shutdown_soc_pct", 20.0, fresh=False)}),
                  ("non-numeric", {"protection.shutdown_soc_pct": st("protection.shutdown_soc_pct", None)})):
    c, n = sd.apply_to_siteconfig(base, ss, {**GOOD_READINGS, **rd}, ACC_T)
    check(f"READ_ONLY_SENSOR_SNAPSHOT with a {label} shutdown reading BLOCKs PHYSICAL_PROTECTION_UNKNOWN (no placeholder)",
          c is None and "PHYSICAL_PROTECTION_UNKNOWN" in [f.code for f in n if f.blocks])
c, _ = sd.apply_to_siteconfig(base, ss, {**GOOD_READINGS, "protection.shutdown_soc_pct": st("protection.shutdown_soc_pct", 20.0)}, ACC_T)
check("... with a fresh reading the technical minimum is that reading", c is not None and c.technical_min_soc_pct == 20.0)
for p in (0.0, 5.0, 9.9):
    c, _ = sd.apply_to_siteconfig(base, full(D2=sd.Protection(sd.OWNER_STATEMENT, p, NOW)), GOOD_READINGS, ACC_T)
    check(f"I-D2 {p} % never lowers the technical minimum below the placeholder", c is not None and c.technical_min_soc_pct == 10.0)
fs = syn.with_decision("D1", sd.PlanningFloor(sd.FEATURE_STOP_LEVEL, None, False), T)
check("FEATURE_STOP_LEVEL needs a fresh stop level",
      sd.apply_to_siteconfig(base, fs, GOOD_READINGS, ACC_T)[0] is None
      and sd.apply_to_siteconfig(base, fs, {**GOOD_READINGS, "stop.dump_soc_pct": st("stop.dump_soc_pct", 30.0)}, ACC_T)[0].user_reserve_soc_pct == 30.0)
ra = syn.with_decision("D3", sd.CapacityAuthority("LEARNED_FROM_DISCHARGE", None, True), T)
check("a capacity resolved at run time needs a fresh plausible reading (FE-1 Wh per percent -> kWh)",
      sd.apply_to_siteconfig(base, ra, GOOD_READINGS, ACC_T)[0] is None
      and sd.apply_to_siteconfig(base, ra, {**GOOD_READINGS, "capacity.fe1_wh_per_pct": st("capacity.fe1_wh_per_pct", 250.0)}, ACC_T)[0].battery_capacity_kwh == 25.0
      and sd.apply_to_siteconfig(base, ra, {**GOOD_READINGS, "capacity.fe1_wh_per_pct": st("capacity.fe1_wh_per_pct", 250000.0)}, ACC_T)[0] is None)
check("site hints in a profile are reported as ignored", [f.code for f in sd.site_hints_ignored({"user_reserve_soc_pct": 40, "technical_min_soc_pct": 10})]
      == ["SITE_HINT_IGNORED", "SITE_HINT_IGNORED"] and sd.site_hints_ignored(None) == [])
check("capacity_context: count and largest symmetric difference", sd.capacity_context([20.0, 22.0, float("nan")]) == (2, 200.0 / 21.0)
      and sd.capacity_context([20.0]) == (1, None))

# ---------------------------------------------------------------------------------------------------------------------
section("[4b] one ITEM_GATES table drives the S0 diagnostic's decision register")
from intelligence.tools import s0_input_consistency as s0  # noqa: E402
_states = s0.decision_states(s0.example_declaration())
check("S0 decision_states: every decision's blocks are items_gated_by (ITEM_GATES plus the conditional items)",
      [x.id for x in _states] == list(sd.DECISION_IDS) and all(x.blocks == sd.items_gated_by(x.id) for x in _states))
check("S0 uses the single ProposedThresholds, efficiency_round_trip, Finding and reserve roles of site_decisions",
      s0.ProposedThresholds is sd.ProposedThresholds and s0.efficiency_round_trip is sd.efficiency_round_trip
      and s0.Finding is sd.Finding and s0.HA_RESERVE_HELPER == sd.ReserveRole.HA_RESERVE_HELPER)
check("S0's defined advisory limits are the defined entries of ADVISORY_LIMITS_S",
      s0.DEFINED_ADVISORY_LIMITS_S == {k: v for k, v in sd.ADVISORY_LIMITS_S.items() if v is not None})
check("S0 shows the I-D labels and the I-D titles of the register",
      [x.label for x in _states] == [sd.display_label(d) for d in sd.DECISION_IDS]
      and [x.title for x in _states] == [sd.DECISION_TITLES[d] for d in sd.DECISION_IDS])

section("[8] PROPOSED answers, roles, import and token rules")
check("PROPOSED_ANSWERS cover I-D4, I-D6, I-D8, I-D9 as text labelled PROPOSED_PENDING_OWNER and 'not an owner decision'",
      sorted(sd.PROPOSED_ANSWERS) == ["I-D4", "I-D6", "I-D8", "I-D9"]
      and all(isinstance(v, str) and v.startswith(sd.PROPOSED_ANSWERS_STATUS) and "not an owner decision" in v for v in sd.PROPOSED_ANSWERS.values()))
check("the proposals carry the agreed figures", "8.0 %" in sd.PROPOSED_ANSWERS["I-D4"] and "300 s" in sd.PROPOSED_ANSWERS["I-D6"]
      and "EXCLUDE_PRE_CUTOVER" in sd.PROPOSED_ANSWERS["I-D8"] and "NORMALISE_TO_NOMINAL" in sd.PROPOSED_ANSWERS["I-D9"]
      and "SCALE_UP_ONLY" in sd.PROPOSED_ANSWERS["I-D9"])
check("PROPOSED_ANSWERS cannot be loaded as decisions", raises(lambda: sd.DecisionSet.from_mapping(dict(sd.PROPOSED_ANSWERS), source="test")))
check("the single ProposedThresholds keeps S0's values", sd.ProposedThresholds() == sd.ProposedThresholds(
    "PROPOSED_PENDING_OWNER", 8.0, (0.5, 500.0), 0.97, 0.88, 0.01, 2.0, 100.0, 0.05, 0.05))
check("six reserve roles, kept apart", len(set(sd.ReserveRole.ALL)) == 6 and "INVERTER_TOU_SETTING" in sd.ReserveRole.ALL
      and "DERIVED_EFFECTIVE" in sd.ReserveRole.ALL)
check("the docstring says firmware features honour no floor", "do not honour any planning floor" in (ast.get_docstring(ast.parse(SRC.read_text(encoding="utf-8"))) or ""))
tree = ast.parse(SRC.read_text(encoding="utf-8"))
mods = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        mods |= {a.name for a in n.names}
    elif isinstance(n, ast.ImportFrom):
        mods.add(("." * n.level) + (n.module or ""))
allowed_rel = {".config", ".explain", ".timeutil", ".periods"}
check("imports: standard library, config / explain / timeutil / periods, ecco_core.state only",
      all(m in allowed_rel or m == "ecco_core.state" or m.split(".")[0] in {"__future__", "math", "re", "dataclasses", "datetime", "types", "typing"}
          for m in mods), str(sorted(mods)))
text = SRC.read_text(encoding="utf-8")
check("no forbidden policy names", not any(w in text for w in ("OWNER_POLICY_FLOOR", "hard_min_soc_pct", "effective_floor_pct")))
calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
check("no clock read and no file access", not [c for c in calls if c.endswith((".now", ".today", "time.time")) or c in ("open", "print")], str(calls))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all site-decision checks passed")
