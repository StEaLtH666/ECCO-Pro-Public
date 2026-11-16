"""Offline suite for the PROPOSED plan helper (stage 3 preparation of the two-master-card energy-control work).

The proposal is a YAML file of Home Assistant helper entities (frontend/ecco-plan-core/proposals/ecco_plan_helpers.proposal.yaml). It is
not installed and no deploy tool loads it. This suite keeps it honest, statically:

  [1] shape         it parses; only the three helper domains; only whitelisted attributes (so no `initial`, no service, no script, no
                    automation can hide in it); every object id is a generic `ecco_plan_` name
  [2] agreement     the entities are exactly the ones the card's reader names (HELPER_IDS in src/plan/helpers.ts), and every
                    min / max / step / unit equals the plan core's validator bounds (HELPER_BOUNDS in src/overridePolicy.ts), so a
                    helper cannot hold a value the validator refuses and the hard ceilings cannot be lifted from Home Assistant
  [3] records       one start and one expiry per override kind (at most one active override per kind, by construction), date and time
                    helpers; the reserve record has the reserve bounds; the skip-until helper is time only
  [4] no writes     no service call, script, automation, inverter / dongle / table entity; no entity id inside any value; no site value
                    (address, coordinate, secret, URL, serial) anywhere, comments included
  [5] not loaded    the deploy manifest does not mention it and no Home Assistant package already defines an ecco_plan_ entity
  [6] mapping       the plan-core README names every entity of the proposal
  [7] mutation      in-memory mutants of the proposal are each caught; a harmless change is not

Writes nothing; no Home Assistant, no network, no hardware. It does not prove the helpers on a live Home Assistant instance.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

PROPOSAL = ROOT / "frontend" / "ecco-plan-core" / "proposals" / "ecco_plan_helpers.proposal.yaml"
POLICY_TS = ROOT / "frontend" / "ecco-plan-core" / "src" / "overridePolicy.ts"
OVERRIDES_TS = ROOT / "frontend" / "ecco-plan-core" / "src" / "overrides.ts"
HELPERS_TS = ROOT / "frontend" / "ecco-energy-actions-card" / "src" / "plan" / "helpers.ts"
README = ROOT / "frontend" / "ecco-plan-core" / "README.md"
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"
PACKAGES = ROOT / "home-assistant" / "packages"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def block(path: Path, begin: str, end: str, name: str) -> dict:
    """The strict-JSON object literal between the BEGIN / END markers of a TypeScript source."""
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"// BEGIN " + begin + r"\r?\nexport const " + name + r" = (\{.*?\n\}) as const;\r?\n// END " + end,
        text,
        re.S,
    )
    if not m:
        raise AssertionError(f"{path.name}: markers for {name} not found")
    return json.loads(m.group(1))


BOUNDS = block(POLICY_TS, "HELPER_BOUNDS_JSON", "HELPER_BOUNDS_JSON", "HELPER_BOUNDS")
IDS = block(HELPERS_TS, "HELPER_IDS_JSON", "HELPER_IDS_JSON", "HELPER_IDS")
_kinds = re.search(r"OVERRIDE_KINDS: readonly OverrideKind\[\] = \[([^\]]*)\]", OVERRIDES_TS.read_text(encoding="utf-8"))
KINDS = re.findall(r'"([a-z_]+)"', _kinds.group(1)) if _kinds else []

ALLOWED_DOMAINS = {"input_boolean", "input_number", "input_datetime"}
ALLOWED_ATTRS = {
    "input_boolean": {"name"},
    "input_number": {"name", "min", "max", "step", "mode", "unit_of_measurement"},
    "input_datetime": {"name", "has_date", "has_time"},
}
BANNED_WORDS = re.compile(r"(inverter|dongle|modbus|deye|sunsynk|tou\b|mqtt|wifi|password|token|secret|http|esphome|service|script|automation)", re.I)
ENTITY_REF = re.compile(r"\b[a-z_]+\.[a-z][a-z0-9_]*\b")
SITE_PATTERNS = [
    ("an IP address", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("an e-mail address", re.compile(r"\S+@\S+\.\S+")),
    ("a secret reference", re.compile(r"!secret|api[_ ]?key|bearer", re.I)),
    ("a URL", re.compile(r"https?://", re.I)),
    ("a coordinate", re.compile(r"\b(latitude|longitude)\b", re.I)),
    ("a MAC address", re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.I)),
    ("a long serial-like number", re.compile(r"\b\d{11,}\b")),
]


def entities(doc: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for domain, items in doc.items():
        for object_id, attrs in (items or {}).items():
            out[f"{domain}.{object_id}"] = attrs if isinstance(attrs, dict) else {"__bad__": attrs}
    return out


def problems(text: str) -> list[str]:
    """Everything wrong with a proposal text; an empty list means it passes every static rule."""
    found: list[str] = []
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"does not parse: {exc}"]
    if not isinstance(doc, dict):
        return ["not a mapping"]
    for key in doc:
        if key not in ALLOWED_DOMAINS:
            found.append(f"top-level key {key!r} is not a helper domain")
    ents = entities({k: v for k, v in doc.items() if k in ALLOWED_DOMAINS})

    # [1] shape
    for eid, attrs in ents.items():
        domain, object_id = eid.split(".", 1)
        if not object_id.startswith("ecco_plan_") or not re.fullmatch(r"[a-z_]+", object_id):
            found.append(f"{eid}: not a generic ecco_plan_ name")
        extra = set(attrs) - ALLOWED_ATTRS[domain]
        if extra:
            found.append(f"{eid}: attributes outside the whitelist: {sorted(extra)}")
        name = attrs.get("name")
        if not isinstance(name, str) or not name:
            found.append(f"{eid}: no name")
        else:
            if BANNED_WORDS.search(name):
                found.append(f"{eid}: the name mentions something that is not a plain helper")
            if ENTITY_REF.search(name):
                found.append(f"{eid}: the name contains an entity id")

    # [2] agreement with the reader and the validator
    want = set(IDS.values())
    have = set(ents)
    if want - have:
        found.append(f"entities the reader names but the proposal lacks: {sorted(want - have)}")
    if have - want:
        found.append(f"entities in the proposal that the reader does not name: {sorted(have - want)}")
    for key, b in BOUNDS.items():
        eid = IDS.get(key)
        if eid is None:
            found.append(f"bounds key {key} has no entity id in the reader")
            continue
        attrs = ents.get(eid)
        if attrs is None or key == "skip_until":
            continue
        for field in ("min", "max", "step"):
            if attrs.get(field) != b[field]:
                found.append(f"{eid}: {field} is {attrs.get(field)!r}, the validator bound is {b[field]}")
        unit = b["unit"]
        if (attrs.get("unit_of_measurement") or "") != unit:
            found.append(f"{eid}: unit is {attrs.get('unit_of_measurement')!r}, expected {unit!r}")
        if attrs.get("mode") != "box":
            found.append(f"{eid}: mode must be box")
    for eid in ents:
        if eid.startswith("input_number.") and attrs_is_number_without_bounds(ents[eid]):
            found.append(f"{eid}: a number helper needs min, max and step")
    reserve_rec = ents.get(IDS.get("prepare_power_cut_reserve", ""), {})
    for field in ("min", "max", "step"):
        if reserve_rec.get(field) != BOUNDS["cut_reserve"][field]:
            found.append(f"the running power-cut reserve {field} differs from the policy reserve bounds")
    if ents.get(IDS.get("confirmed", ""), None) is None or not IDS.get("confirmed", "").startswith("input_boolean."):
        found.append("the confirmation switch must be an input_boolean")

    # [3] records
    for kind in KINDS:
        for part in ("start", "expires"):
            eid = IDS.get(f"{kind}_{part}")
            attrs = ents.get(eid or "")
            if attrs is None:
                found.append(f"{kind}: no {part} record")
            elif not (eid or "").startswith("input_datetime.") or attrs.get("has_date") is not True or attrs.get("has_time") is not True:
                found.append(f"{eid}: a record must be an input_datetime with date and time")
        mine = [e for e in ents if e.startswith(f"input_datetime.ecco_plan_override_{kind}_")]
        if len(mine) != 2:
            found.append(f"{kind}: {len(mine)} record entities (exactly one start and one expiry, so at most one active override)")
    if not KINDS:
        found.append("the override kinds could not be read from overrides.ts")
    sk = ents.get(IDS.get("skip_until", ""), {})
    if sk.get("has_time") is not True or sk.get("has_date") is not False:
        found.append("the skip-until helper must be time only (has_time true, has_date false)")

    # [4] no writes, no entity references inside values, no site values anywhere (comments included)
    for pattern_name, pattern in SITE_PATTERNS:
        if pattern.search(text):
            found.append(f"the text contains {pattern_name}")
    for eid, attrs in ents.items():
        for k, v in attrs.items():
            if isinstance(v, str) and k != "name" and ENTITY_REF.search(v):
                found.append(f"{eid}: {k} holds an entity reference")
    if re.search(r"^\s*(service|action|actions|sequence|trigger|platform)\s*:", text, re.M):
        found.append("a service, action, sequence, trigger or platform key is present")
    return found


def attrs_is_number_without_bounds(attrs: dict) -> bool:
    return any(not isinstance(attrs.get(f), (int, float)) or isinstance(attrs.get(f), bool) for f in ("min", "max", "step"))


TEXT = PROPOSAL.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)

print("[1-4] the proposal against the reader and the validator")
check("the proposal file exists and parses", isinstance(DOC, dict))
check("the bounds and ids blocks were read", len(BOUNDS) == 9 and len(IDS) == 17, f"{len(BOUNDS)} bounds, {len(IDS)} ids")
check("the three override kinds were read from overrides.ts", KINDS == ["hold_battery", "skip_tonight", "prepare_power_cut"], str(KINDS))
found = problems(TEXT)
check("the proposal passes every static rule", not found, "; ".join(found))
check("only the three helper domains are used", set(DOC) == ALLOWED_DOMAINS, str(sorted(DOC)))
check("no helper sets an initial value (the proposed values are never applied by creating them)", not re.search(r"^\s*initial\s*:", TEXT, re.M))
check("the entity count is 17", len(entities(DOC)) == 17, str(len(entities(DOC))))
check("the revision helper holds a counter only (no plan value is copied into a helper)",
      not [e for e in entities(DOC) if re.search(r"(power|soc|target|stop|start_time|duration)", e) and "override" not in e and "policy" not in e])
check("the ceilings equal the cap maxima (a helper cannot lift a hard ceiling)",
      BOUNDS["hold_cap"]["max"] == 4320 and BOUNDS["skip_cap"]["max"] == 2160 and BOUNDS["cut_cap"]["max"] == 10080
      and BOUNDS["hold_default"]["max"] == BOUNDS["hold_cap"]["max"] and BOUNDS["cut_default"]["max"] == BOUNDS["cut_cap"]["max"])
check("the minimum expiry bound is greater than zero", BOUNDS["min_expiry"]["min"] > 0)

print("[5] not loaded by anything")
manifest = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
check("the deploy manifest does not mention the proposal", "ecco_plan_helpers" not in manifest and "proposals/" not in manifest and "ecco-plan-core" not in manifest)
defined = [p.name for p in PACKAGES.glob("*.yaml") if re.search(r"\becco_plan_[a-z_]+\b", p.read_text(encoding="utf-8"))]
check("no Home Assistant package already defines or references an ecco_plan_ entity", not defined, str(defined))
check("the proposal lives outside home-assistant/", "home-assistant" not in PROPOSAL.relative_to(ROOT).parts)

print("[6] mapping")
readme = README.read_text(encoding="utf-8")
missing = [eid.split(".", 1)[1] for eid in IDS.values() if eid.split(".", 1)[1] not in readme]
check("the plan-core README names every entity of the proposal", not missing, str(missing))

print("[7] mutation")


def reload_with(mutate) -> str:
    doc = copy.deepcopy(DOC)
    mutate(doc)
    return yaml.safe_dump(doc, sort_keys=False)


MUTANTS = {
    "an initial value": lambda d: d["input_number"]["ecco_plan_policy_hold_default"].update(initial=240),
    "a hold cap above the ceiling": lambda d: d["input_number"]["ecco_plan_policy_hold_cap"].update(max=5000),
    "a skip cap above the ceiling": lambda d: d["input_number"]["ecco_plan_policy_skip_cap"].update(max=2161),
    "a power-cut cap above the ceiling": lambda d: d["input_number"]["ecco_plan_policy_cut_cap"].update(max=20160),
    "a minimum expiry of zero": lambda d: d["input_number"]["ecco_plan_policy_min_expiry"].update(min=0),
    "a different step": lambda d: d["input_number"]["ecco_plan_policy_cut_reserve"].update(step=5),
    "a reserve below the reserve limit": lambda d: d["input_number"]["ecco_plan_policy_cut_reserve"].update(min=5),
    "the running reserve with other bounds": lambda d: d["input_number"]["ecco_plan_override_prepare_power_cut_reserve"].update(max=90),
    "a slider": lambda d: d["input_number"]["ecco_plan_policy_hold_cap"].update(mode="slider"),
    "a missing unit": lambda d: d["input_number"]["ecco_plan_policy_hold_cap"].pop("unit_of_measurement"),
    "a missing expiry record": lambda d: d["input_datetime"].pop("ecco_plan_override_skip_tonight_expires"),
    "a second record for one kind": lambda d: d["input_datetime"].update(ecco_plan_override_hold_battery_start2={"name": "x", "has_date": True, "has_time": True}),
    "a record without a date": lambda d: d["input_datetime"]["ecco_plan_override_hold_battery_expires"].update(has_date=False),
    "a skip-until with a date": lambda d: d["input_datetime"]["ecco_plan_policy_skip_until"].update(has_date=True),
    "a missing policy entity": lambda d: d["input_number"].pop("ecco_plan_policy_cut_default"),
    "an extra entity the reader does not know": lambda d: d["input_number"].update(ecco_plan_extra={"name": "x", "min": 0, "max": 1, "step": 1, "mode": "box"}),
    "a name not starting with ecco_plan_": lambda d: d["input_number"].update(other_thing=d["input_number"].pop("ecco_plan_revision")),
    "a script section": lambda d: d.update(script={"ecco_plan_start": {"sequence": [{"service": "number.set_value"}]}}),
    "an automation section": lambda d: d.update(automation=[{"alias": "x"}]),
    "a switch of the inverter": lambda d: d.update(switch={"ecco_plan_write": {"name": "x"}}),
    "a service key inside a helper": lambda d: d["input_boolean"]["ecco_plan_overrides_enabled"].update(service="button.press"),
    "an entity reference in a name": lambda d: d["input_boolean"]["ecco_plan_overrides_enabled"].update(name="mirror of number.some_inverter_power"),
    "the dongle in a name": lambda d: d["input_boolean"]["ecco_plan_overrides_enabled"].update(name="ECCO dongle write enable"),
    "the confirmation switch as a number": lambda d: d["input_number"].update(ecco_plan_overrides_enabled=d["input_boolean"].pop("ecco_plan_overrides_enabled")),
}
for label, mutate in MUTANTS.items():
    try:
        text = reload_with(mutate)
        caught = bool(problems(text))
    except (KeyError, AttributeError):
        caught = False
    check(f"mutant caught: {label}", caught)

TEXT_MUTANTS = {
    "an IP address in a comment": TEXT + "\n# bridge at 192.168.1.20\n",
    "an e-mail address in a comment": TEXT + "\n# owner@example.org\n",
    "a secret reference": TEXT + "\n# api_key: abc\n",
    "a URL": TEXT + "\n# see https://example.org/x\n",
    "a coordinate": TEXT + "\n# latitude: 1\n",
    "a serial-like number": TEXT + "\n# 12345678901234\n",
    "an unparsable file": TEXT + "\n  broken: [unclosed\n",
}
for label, text in TEXT_MUTANTS.items():
    check(f"mutant caught: {label}", bool(problems(text)))

check("control: a harmless change (a display name) is not flagged", not problems(reload_with(lambda d: d["input_number"]["ecco_plan_policy_hold_cap"].update(name="Hold battery longest length"))))
check("control: the untouched proposal is not flagged", not problems(TEXT))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All plan-helper proposal offline tests PASSED.")
print("NOTE: a static check of a proposal file; the helpers are not installed and not proven on a live Home Assistant instance.")
