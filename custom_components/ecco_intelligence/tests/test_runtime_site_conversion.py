#!/usr/bin/env python3
"""The optional inverter conversion site facts through the runtime's site loader and the site-check tool (synthetic only).

  [1] absent keys: nothing changes (no new check, all three facts None, the site-check report as before)
  [2] valid keys in the `site` block: a PASS check, the facts carried as numbers, and the engine's loss-aware balance in force
  [3] invalid keys (partial, out of bounds, a string, true, a list, an object): a WARN check that names no value, the facts
      carried so that the quality layer reports them (a non-number as NaN, never as absent), the debug detail naming facts and
      reasons only; a null is absent
  [4] site-check: a valid set is OK; an invalid set is PROBLEMS (SITE_INVERTER_CONVERSION INVALID) and export / Dump read
      BLOCKED with POWER_LOSS_FACTS_INVALID; the other items and a file without the keys are untouched
  [5] the whole path: a site file's facts decide whether a loss-affected set BLOCKs export and Dump in the engine

Plain script; exits 1 on any failure. No Home Assistant import; nothing is written.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))
sys.path.insert(1, str(REPO))
sys.path.insert(2, str(REPO / "intelligence" / "tests"))

import _harness as H  # noqa: E402
from custom_components.ecco_intelligence.runtime import gates  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

import _cycle_fixtures as cf  # noqa: E402  (the engine's synthetic fixtures)

spec = importlib.util.spec_from_file_location("ecco_intel_drill", REPO / "tools" / "ecco_intel_drill.py")
D = importlib.util.module_from_spec(spec)
sys.modules["ecco_intel_drill"] = D
spec.loader.exec_module(D)

FAILURES: list[str] = []
CODE = "SITE_INVERTER_CONVERSION"
FACTS = ("inverter_dc_to_ac_factor", "inverter_ac_to_dc_factor", "inverter_standby_w")
GOOD = {"inverter_dc_to_ac_factor": 0.92, "inverter_ac_to_dc_factor": 0.94, "inverter_standby_w": 40}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


READINGS = {k: v for k, v in H.READING_MAP.items() if k not in D.V01_UNMAPPED_READINGS}


def profile(site_extra: dict | None = None) -> dict:
    p = H.site_profile(decisions=H.owner_decisions(), readings=READINGS)
    p["site"].update(site_extra or {})
    return p


def load(site_extra: dict | None = None, raw: bytes | None = None) -> gates.SiteLoad:
    return gates.load_site(raw if raw is not None else json.dumps(profile(site_extra)).encode(), latitude=51.5, longitude=-0.1)


def level(sl: gates.SiteLoad, code: str = CODE) -> str | None:
    return next((c.level for c in sl.checks if c.code == code), None)


def text(sl: gates.SiteLoad, code: str = CODE) -> str:
    return next((c.text for c in sl.checks if c.code == code), "")


print("== [1] absent keys")
base = load()
check("no inverter keys: no SITE_INVERTER_CONVERSION check at all, so the load checks are as they were",
      level(base) is None and not any(c.code == CODE for c in base.checks))
check("... the three facts are None and the PV array size is carried as before",
      all(getattr(base.site_facts, f) is None for f in FACTS) and base.site_facts.pv_array_kwp == 6.0
      and sd.inverter_conversion(base.site_facts) == (sd.LOSSLESS_CONVERSION, ()))
nulls = load({f: None for f in FACTS})
check("three JSON nulls are absent too (no check, all None)", level(nulls) is None and all(getattr(nulls.site_facts, f) is None for f in FACTS))
check("a site file with no `site` block at all gives None facts and no check",
      level(load(raw=json.dumps({k: v for k, v in profile().items() if k != "site"}).encode())) is None)
check("the other load checks do not change with a valid set (the same codes, plus the one new check)",
      [c.code for c in load(GOOD).checks if c.code != CODE] == [c.code for c in base.checks])

print("== [2] valid keys")
ok = load(GOOD)
check("a valid set: the PASS check, the facts carried as numbers",
      level(ok) == "PASS" and [getattr(ok.site_facts, f) for f in FACTS] == [0.92, 0.94, 40.0]
      and all(isinstance(getattr(ok.site_facts, f), float) for f in FACTS), str([(c.code, c.level) for c in ok.checks]))
check("... the engine's judgement of them is the conversion, no problem",
      sd.inverter_conversion(ok.site_facts) == (sd.InverterConversion(0.92, 0.94, 40.0), ()))
check("... the PASS text names no value", not any(ch.isdigit() for ch in text(ok)), text(ok))
edge = load({"inverter_dc_to_ac_factor": 0.9, "inverter_ac_to_dc_factor": 1, "inverter_standby_w": 100})
check("values exactly at the bounds (0.90, 1, 100 W) load as PASS (inclusive; integers carried as numbers)",
      level(edge) == "PASS" and sd.inverter_conversion(edge.site_facts) == (sd.InverterConversion(0.9, 1.0, 100.0), ()))
zero = load({"inverter_dc_to_ac_factor": 1, "inverter_ac_to_dc_factor": 1, "inverter_standby_w": 0})
check("explicit lossless values (1, 1, 0) load as PASS and the engine treats them as lossless",
      level(zero) == "PASS" and sd.inverter_conversion(zero.site_facts)[0].lossless)

print("== [3] invalid keys")
INVALID = {
    "one key only": {"inverter_dc_to_ac_factor": 0.8123},
    "two keys": {"inverter_dc_to_ac_factor": 0.8123, "inverter_ac_to_dc_factor": 0.9},
    "a factor above 1": {**GOOD, "inverter_dc_to_ac_factor": 1.0377},
    "a factor below the bound": {**GOOD, "inverter_ac_to_dc_factor": 0.8123},
    "a factor just below the bound": {**GOOD, "inverter_dc_to_ac_factor": 0.8945},
    "a standby above the bound": {**GOOD, "inverter_standby_w": 777.5},
    "a standby just above the bound": {**GOOD, "inverter_standby_w": 100.5},
    "a negative standby": {**GOOD, "inverter_standby_w": -12.5},
    "a string": {**GOOD, "inverter_standby_w": "forty-two"},
    "a numeric string": {**GOOD, "inverter_dc_to_ac_factor": "0.9123"},
    "true": {**GOOD, "inverter_ac_to_dc_factor": True},
    "a list": {**GOOD, "inverter_dc_to_ac_factor": [0.9123]},
    "an object": {**GOOD, "inverter_standby_w": {"w": 40.123}},
    "a null among valid values": {**GOOD, "inverter_standby_w": None},
}
LITERALS = ("0.8123", "1.0377", "777.5", "12.5", "forty-two", "0.9123", "40.123", "0.8945", "100.5")
for label, extra in INVALID.items():
    sl = load(extra)
    facts = [getattr(sl.site_facts, f) for f in FACTS]
    conv, problems = sd.inverter_conversion(sl.site_facts)
    detail = " ".join(d for c, d in sl.details if c == CODE)
    check(f"{label}: a WARN check, the lossless balance stays, the engine reports it ({len(problems)} problem(s))",
          level(sl) == "WARN" and conv.lossless and bool(problems), str((level(sl), problems)))
    check(f"{label}: the check text names no value and no digit, the detail names facts and reasons only",
          not any(ch.isdigit() for ch in text(sl)) and not any(x in text(sl) + detail for x in LITERALS)
          and all(part.strip().split(":")[0] in FACTS for part in detail.split(",") if part.strip()), f"{text(sl)} | {detail}")
    check(f"{label}: no value reads as absent unless it is null (a non-number is carried as NaN)",
          all(v is None or isinstance(v, float) for v in facts)
          and all((not math.isnan(v)) or label in ("a string", "a numeric string", "true", "a list", "an object") for v in facts if v is not None))
nan_cases = {"a string": "inverter_standby_w", "a numeric string": "inverter_dc_to_ac_factor", "true": "inverter_ac_to_dc_factor",
             "a list": "inverter_dc_to_ac_factor", "an object": "inverter_standby_w"}
for label, fact in nan_cases.items():
    v = getattr(load(INVALID[label]).site_facts, fact)
    check(f"{label}: carried as NaN, which the quality layer never accepts (not read as absent)",
          isinstance(v, float) and math.isnan(v) and sd.inverter_conversion(load(INVALID[label]).site_facts)[1] == (f"{fact}:not_a_number",))
nonfinite = gates.load_site(b'{"site": {"inverter_standby_w": NaN}}')
check("a NaN literal is refused by the loader's own non-finite rule (SITE_FILE FAIL) as for any other number",
      level(nonfinite, "SITE_FILE") == "FAIL")
check("a refused site file does not raise on the conversion keys", isinstance(gates.load_site(b'["x"]'), gates.SiteLoad))
huge_raw = b'{"site": {"inverter_standby_w": 1' + b"0" * 400 + b"}}"
huge_file = gates.load_site(huge_raw)
check("an integer beyond the double range in the site file is refused by the loader's own rule (SITE_FILE FAIL, no value named), "
      "not raised", level(huge_file, "SITE_FILE") == "FAIL" and level(huge_file) is None
      and not any("0" * 20 in c.text for c in huge_file.checks))
huge_facts, _cfg = gates._facts({"site": {"inverter_standby_w": 10 ** 400, "inverter_dc_to_ac_factor": 0.95,
                                          "inverter_ac_to_dc_factor": 0.95}}, 51.5, -0.1)
check("the facts builder itself never raises on such an integer (a profile that did not come through the loader): carried as NaN, "
      "which the engine reports as a fact that is not a number, never as absent and never as usable",
      isinstance(huge_facts.inverter_standby_w, float) and math.isnan(huge_facts.inverter_standby_w)
      and sd.inverter_conversion(huge_facts) == (sd.LOSSLESS_CONVERSION, ("inverter_standby_w:not_a_number",)))

print("== [4] site-check")
raw_none = json.dumps(profile()).encode()
rep_none = D.site_check_report(raw_none, "site.json")
check("a complete fictional site file without the keys: OK, nothing blocked by the file, no new check",
      rep_none["result"] == "OK" and not any(c["code"] == CODE for c in rep_none["checks"])
      and all(r["readiness"] == "LIVE_INPUTS_DECIDE" for r in rep_none["items"].values()), str(rep_none["problems"]))
rep_ok = D.site_check_report(json.dumps(profile(GOOD)).encode(), "site.json")
check("... with a valid set: OK, the PASS check shows, every item as before",
      rep_ok["result"] == "OK" and any(c["code"] == CODE and c["level"] == "PASS" for c in rep_ok["checks"])
      and {k: v for k, v in rep_ok["items"].items()} == rep_none["items"], str(rep_ok["problems"]))
rep_bad = D.site_check_report(json.dumps(profile(INVALID["a factor above 1"])).encode(), "site.json")
power = {i for i in sd.PUBLISHED_ITEMS if i in q.POWER_ITEMS}
check("an invalid set: result PROBLEMS naming SITE_INVERTER_CONVERSION INVALID, and the WARN check shows",
      rep_bad["result"] == "PROBLEMS" and f"{CODE} INVALID" in rep_bad["problems"]
      and any(c["code"] == CODE and c["level"] == "WARN" for c in rep_bad["checks"]), str(rep_bad["problems"]))
check("... export_event and dump_to_grid read BLOCKED with POWER_LOSS_FACTS_INVALID, every other item as before",
      power == {"export_event", "dump_to_grid"}
      and all("POWER_LOSS_FACTS_INVALID" in rep_bad["items"][i]["blockers"] and rep_bad["items"][i]["readiness"] == "BLOCKED" for i in power)
      and all(rep_bad["items"][i] == rep_none["items"][i] for i in rep_none["items"] if i not in power), str(rep_bad["items"]))
dumped = json.dumps(rep_bad) + D.render_site_check(rep_bad)
check("... and the report shows no value from the file", not any(x in dumped for x in LITERALS) and "1.0377" not in dumped)
check("a partial set is PROBLEMS too", D.site_check_report(json.dumps(profile(INVALID["one key only"])).encode(), "s.json")["result"] == "PROBLEMS")

print("== [5] the whole path: site file -> site facts -> the engine's balance")
inp = cf.cycle_inputs(synthetic_recorded=True)
loss_set = {"house.power": 2700.0, "pv.power": 0.0, "battery.power": 3000.0, "grid.power": 0.0}      # a tenth lost: 300 W
with_none = q.assess_inputs(replace(faults.with_signals(inp, loss_set), site_facts=replace(cf.FACTS, **{
    f: getattr(base.site_facts, f) for f in FACTS})))
with_ok = q.assess_inputs(replace(faults.with_signals(inp, loss_set), site_facts=replace(cf.FACTS, **{
    f: getattr(ok.site_facts, f) for f in FACTS})))
with_bad = q.assess_inputs(replace(faults.with_signals(inp, loss_set), site_facts=replace(cf.FACTS, **{
    f: getattr(load(INVALID["a standby above the bound"]).site_facts, f) for f in FACTS})))
codes = lambda r: {(f.code, f.subject) for f in r.findings if f.severity == "BLOCK"}                     # noqa: E731
check("the same loss-affected set: BLOCKED (balance) with no keys, clear with a valid set, BLOCKED (invalid facts and the "
      "lossless balance) with an invalid one",
      {c for c, _s in codes(with_none)} == {"POWER_BALANCE_INCONSISTENT"} and not codes(with_ok)
      and {c for c, _s in codes(with_bad)} == {"POWER_LOSS_FACTS_INVALID", "POWER_BALANCE_INCONSISTENT"},
      str((codes(with_none), codes(with_ok), codes(with_bad))))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all site-conversion checks passed")
