#!/usr/bin/env python3
"""Offline suite for home-assistant/packages/ecco_intelligence_prefs.yaml: the ECCO Intelligence raise-only advisory reserve
helper input_number.ecco_advisory_reserve_raise_pct (post-export entry isp1).

The runtime reads it only when the owner's site file maps it as `pref.advisory_reserve_raise_pct`; it can only raise the advisory
planning floor (max of the I-D1 floor, the technical minimum, the Home Assistant reserve helper and this value), and once mapped an
unusable value BLOCKs the reserve items (PREF_RESERVE_RAISE_UNKNOWN). This suite pins the package against that contract, with a
small model of what Home Assistant does with an input_number at start-up (the same rules test_ecco_reserve_default.py states: a
configured `initial` wins over the restored state at every start; otherwise the last state is restored if it is a number inside
[min, max], else the helper starts at its minimum).

  [1] static      exactly one input_number with a fixed key set (min 0, max 100, step 1, box, %), no `initial` (key or line), no
                  other key, no automation, script, template, service call or entity reference
  [2] contract    the contract's unit of pref.advisory_reserve_raise_pct is the helper's unit, the key is optional (unmapped means
                  no raise), and every value the helper can hold (min..max by step, both bounds included) is read by the
                  runtime's own reader as that usable number; a value outside the helper's range would be refused by the reader
  [3] start-up    a new helper starts at 0 % (raises nothing); the owner's value survives repeated restarts; a restored value the
                  helper cannot hold falls to 0 %, never to a guess
  [4] one owner   nothing in the repository writes the helper (no package, dashboard, card source or integration code names a
                  write service near it); it is not the Home Assistant reserve helper and not a contract entity id
  [5] isp1        the manifest lists the package as a package stanza and isp1 declares it and this suite as added files
  [6] mutation    in-memory mutants of the package are each caught (an `initial`, a wider range, a negative minimum, a wrong
                  unit, an automation, a second helper)

Writes nothing; no Home Assistant, no network, no hardware.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.ecco_intelligence.runtime import sources  # noqa: E402  (pure: no homeassistant import)
from intelligence import advisory_contract as ac  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_intelligence_prefs.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
SELF_REL = "home-assistant/tests/test_ecco_intelligence_prefs_package.py"
OBJ = "ecco_advisory_reserve_raise_pct"
HELPER = f"input_number.{OBJ}"
KEY = "pref.advisory_reserve_raise_pct"
RESERVE = "input_number.ecco_minimum_reserve_soc"     # the Home Assistant reserve helper of the core package (not this one)
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=timezone.utc)   # fictional

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def code_text(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def helper_cfg(text: str) -> dict:
    doc = yaml.safe_load(text) or {}
    return ((doc.get("input_number") or {}).get(OBJ)) or {}


def holdable(cfg: dict) -> list[float]:
    """Every value the helper can hold: min..max by step, both bounds included."""
    lo, hi, step = float(cfg["min"]), float(cfg["max"]), float(cfg["step"])
    n = int(round((hi - lo) / step))
    return [lo + i * step for i in range(n + 1)]


def runtime_reads(state: str, unit: str = "%"):
    """The runtime's own reader on the mapped helper: (value or None, note)."""
    view = {"state": state, "attributes": {"unit_of_measurement": unit}, "last_changed": NOW - timedelta(days=2),
            "last_updated": NOW - timedelta(days=2), "last_reported": NOW - timedelta(days=2)}
    value, _at, note, _src = sources._reading_value(KEY, {"entity": HELPER}, {HELPER: view}, NOW)
    return value, note


def ha_start(cfg: dict, restored: str | None) -> float:
    """Home Assistant's input_number at start-up: a configured `initial` wins at every start; else a restored number inside
    [min, max]; else the minimum."""
    if "initial" in cfg:
        return float(cfg["initial"])
    try:
        v = float(restored) if restored is not None else None
    except ValueError:
        v = None
    if v is not None and float(cfg["min"]) <= v <= float(cfg["max"]):
        return v
    return float(cfg["min"])


def problems(text: str) -> list[str]:
    """Every rule [1]-[3] states, over a package text (the mutants in [6] run through this)."""
    out = []
    doc = yaml.safe_load(text) or {}
    code = code_text(text)
    if set(doc) != {"input_number"} or list(doc.get("input_number") or {}) != [OBJ]:
        out.append("not exactly one input_number")
    cfg = helper_cfg(text)
    if set(cfg) != {"name", "icon", "min", "max", "step", "mode", "unit_of_measurement"}:
        out.append("helper keys")
    if re.search(r"^\s*initial\s*:", code, re.M) or "initial" in cfg:
        out.append("initial")
    if not out:
        if (cfg["min"], cfg["max"], cfg["step"], cfg["mode"], cfg["unit_of_measurement"]) != (0, 100, 1, "box", "%"):
            out.append("range / unit")
        if cfg["unit_of_measurement"] != ac.SITE_READING_KEYS[KEY]:
            out.append("unit differs from the contract")
        bad = [v for v in holdable(cfg) if runtime_reads(f"{v:g}", cfg["unit_of_measurement"])[0] != v]
        if bad:
            out.append(f"values the runtime refuses: {bad[:3]}")
        if ha_start(cfg, None) != 0.0:
            out.append("a new helper does not start at 0 %")
    ids = set(re.findall(r"\b(?:sensor|binary_sensor|input_\w+|switch|button|number|select|script|automation)\.[a-z0-9_]+", code))
    if ids - {HELPER}:
        out.append(f"names other entities {sorted(ids - {HELPER})}")
    if re.search(r"^\s*(?:action|service)\s*:", code, re.M):
        out.append("a service call")
    return out


PKG = yaml.safe_load(PKG_TEXT)
CFG = helper_cfg(PKG_TEXT)

# =====================================================================================================================
print("[1] static")
# =====================================================================================================================
code = code_text(PKG_TEXT)
check("the package is exactly one input_number, input_number.ecco_advisory_reserve_raise_pct, and nothing else (no automation, "
      "script, template or other helper)", set(PKG) == {"input_number"} and list(PKG["input_number"]) == [OBJ], str(PKG))
check("its keys are exactly name, icon, min, max, step, mode and unit_of_measurement",
      set(CFG) == {"name", "icon", "min", "max", "step", "mode", "unit_of_measurement"}, str(CFG))
check("min 0, max 100, step 1, box mode, unit % (the contract's 0..100 % range of pref.advisory_reserve_raise_pct)",
      (CFG.get("min"), CFG.get("max"), CFG.get("step"), CFG.get("mode"), CFG.get("unit_of_measurement")) == (0, 100, 1, "box", "%"))
check("no `initial:` (key or line): Home Assistant restores the owner's value at every start",
      "initial" not in CFG and not re.search(r"^\s*initial\s*:", code, re.M))
check("no entity reference other than its own id, no service call, no recorder block",
      not (set(re.findall(r"\b(?:sensor|binary_sensor|input_\w+|switch|button|number|select|script|automation)\.[a-z0-9_]+", code))
           - {HELPER}) and not re.search(r"^\s*(?:action|service|recorder)\s*:", code, re.M))
check("the header states the raise-only rule, the fail-closed mapping, the missing `initial` and that nothing writes it",
      "can only RAISE the" in PKG_TEXT and "PREF_RESERVE_RAISE_UNKNOWN" in PKG_TEXT and "No `initial:`" in PKG_TEXT
      and "Nothing in ECCO writes this helper" in PKG_TEXT and "never a decision" in PKG_TEXT)
FB = "fall" + "back"
BANNED = ["ecco_" + FB, FB.upper() + "_PROFILE", "FAIL" + "BACK_STATE", "ecco_" + "fail" + "back", "ecco_" + "shadow_",
          "Shadow " + "Recovery", "ecco_clock_" + "dongle", "ecco-flow-" + "3d-card", "octo" + "pus"]
own = PKG_TEXT + (ROOT / SELF_REL).read_text(encoding="utf-8")
check("no reserved / device-slug / tariff / 3D-card token in the package or this suite", not [b for b in BANNED if b in own])
check("problems() finds nothing in the real package (the mutants below run through it)", problems(PKG_TEXT) == [], str(problems(PKG_TEXT)))

# =====================================================================================================================
print("")
print("[2] the contract and the runtime's reader")
# =====================================================================================================================
check("the contract names pref.advisory_reserve_raise_pct in %, as an optional reading (unmapped: no reading, no raise)",
      ac.SITE_READING_KEYS.get(KEY) == "%" == CFG["unit_of_measurement"] and KEY in ac.OPTIONAL_READING_KEYS
      and sources.PREF_RESERVE_RAISE_KEY == KEY)
vals = holdable(CFG)
reads = [runtime_reads(f"{v:g}") for v in vals]
check(f"every value the helper can hold ({len(vals)} values, 0 and 100 included) is read by the runtime as that usable number",
      len(vals) == 101 and all(r[0] == v for r, v in zip(reads, vals)), str([(v, r) for r, v in zip(reads, vals) if r[0] != v][:3]))
check("the runtime refuses what the helper cannot hold (-1, 100.5, 140, a non-number, unavailable): no number, never 0",
      all(runtime_reads(s)[0] is None for s in ("-1", "100.5", "140", "abc", "unavailable", "unknown")))
check("the runtime refuses the helper's value under another unit (a unit that is not % is not this preference)",
      runtime_reads("55", "W")[0] is None and runtime_reads("55")[0] == 55.0)

# =====================================================================================================================
print("")
print("[3] Home Assistant start-up")
# =====================================================================================================================
check("a new helper (nothing restored) starts at its minimum, 0 %: the floor is a maximum with 0, so it raises nothing",
      ha_start(CFG, None) == 0.0)
check("the owner's value survives repeated restarts (55 %, 0 %, 100 %)",
      all(ha_start(CFG, ha_start(CFG, ha_start(CFG, s))) == float(s) for s in ("55", "0", "100")))
check("a restored value the helper cannot hold (unknown, 140, -1) falls to the minimum, 0 %, never to a guess",
      all(ha_start(CFG, s) == 0.0 for s in ("unknown", "140", "-1")))

# =====================================================================================================================
print("")
print("[4] one owner, one id")
# =====================================================================================================================
WRITE = re.compile(r"input_number\.(?:set_value|increment|decrement|reload)|perform-action|call-service|callService")
offenders = []
for base in ("home-assistant/packages", "home-assistant/dashboards", "home-assistant/prototypes", "frontend", "custom_components"):
    for f in sorted(p for p in (ROOT / base).rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml", ".ts", ".js", ".py", ".mjs")
                    and "node_modules" not in p.parts):
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(re.escape(OBJ), text):
            if WRITE.search(text[max(0, m.start() - 300):m.end() + 300]):
                offenders.append(f"{f.relative_to(ROOT).as_posix()}@{m.start()}")
check("nothing in the repository writes the helper (no write service within 300 characters of its id in any package, dashboard, "
      "card source or integration file)", not offenders, str(offenders[:4]))
named = sorted(f.relative_to(ROOT).as_posix() for base in ("home-assistant", "frontend", "custom_components")
               for f in (ROOT / base).rglob("*") if f.is_file() and f.suffix in (".yaml", ".yml", ".ts", ".js", ".py", ".mjs")
               and "node_modules" not in f.parts and OBJ in f.read_text(encoding="utf-8", errors="replace"))
check("only the package and this suite name the helper among the Home Assistant, card and integration files (the site file maps it)",
      named == sorted([PKG_REL, SELF_REL]), str(named))
check("it is not the Home Assistant reserve helper, and not a contract entity id (no ecco_intel_ prefix, so the contract's id "
      "scans and the test instance's entity census never count it)",
      HELPER != RESERVE and HELPER not in ac.ENTITY_IDS.values() and not OBJ.startswith("ecco_intel_")
      and OBJ not in ac.UNIQUE_IDS.values())

# =====================================================================================================================
print("")
print("[5] the isp1 declaration")
# =====================================================================================================================
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _isp1_scope as I  # noqa: E402

man = yaml.safe_load((ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8"))
check("the manifest lists the package once, as a package stanza to /config/packages/ (restart required, the established method)",
      [s for s in man["home_assistant_packages"] if s.get("source") == PKG_REL]
      == [{"source": PKG_REL, "destination": "/config/packages/ecco_intelligence_prefs.yaml", "method": "ssh_file_copy",
           "restart_required": True}])
ver = yaml.safe_load((ROOT / "VERSION.yaml").read_text(encoding="utf-8"))
check("VERSION.yaml's intelligence block names the package; isp1 declares the package and this suite as added files",
      (ver["current"].get("intelligence") or {}).get("prefs_package") == PKG_REL and {PKG_REL, SELF_REL} <= I.ADDED_FILES)

# =====================================================================================================================
print("")
print("[6] mutation: each in-memory mutant is caught")
# =====================================================================================================================
MUTANTS = (
    ("an `initial: 40`", "    mode: box\n", "    mode: box\n    initial: 40\n"),
    ("the maximum widened to 150", "    max: 100\n", "    max: 150\n"),
    ("a negative minimum", "    min: 0\n", "    min: -10\n"),
    ("a minimum of 30 (a new helper would raise the floor)", "    min: 0\n", "    min: 30\n"),
    ("the unit changed to W", '    unit_of_measurement: "%"\n', '    unit_of_measurement: "W"\n'),
    ("an automation that writes it", 'unit_of_measurement: "%"\n',
     'unit_of_measurement: "%"\n\nautomation:\n  - id: x\n    triggers: []\n    actions:\n      - action: input_number.set_value\n'
     '        target:\n          entity_id: input_number.ecco_advisory_reserve_raise_pct\n        data:\n          value: 40\n'),
    ("a second helper", "input_number:\n", "input_number:\n  ecco_other_raise:\n    min: 0\n    max: 100\n"),
)
for label, old, new in MUTANTS:
    mutant = PKG_TEXT.replace(old, new, 1)
    applied = mutant != PKG_TEXT and PKG_TEXT.count(old) == 1
    try:
        caught = bool(problems(mutant))
    except Exception:  # noqa: BLE001  (a mutant that breaks the checks is caught too)
        caught = True
    check(f"mutant caught: {label}", applied and caught, "not applied" if not applied else "not caught")

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
