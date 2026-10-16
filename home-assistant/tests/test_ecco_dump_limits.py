#!/usr/bin/env python3
"""fcc1 full-capability controls (home-assistant/packages/ecco_dump_limits.yaml, home-assistant/dashboards/ecco_full_capability.yaml):
offline proofs.

The package's and the dashboard's REAL Jinja templates are rendered in an immutable sandboxed Jinja environment with stand-ins for
the Home Assistant functions they use (states / is_state / state_attr / this, the forgiving float filter, is_number, default).

  [0] static: the package writes nothing to the dongle (its only actions create / dismiss one persistent notification), the helper
      has no `initial` and starts at 3000 W, every entity it reads exists (dongle entities from the firmware, not internal; helpers
      from their packages), the device slug appears only inside entity ids, the manifest deploys the package
  [1] firmware coupling: every status text the firmware can publish on "Dump Power Limits Status" (its real snprintf formats,
      filled with sample values) is classified as an independent Python model says
  [2] the limits state: VALID / NOT CONFIGURED / INVALID / AWAITING CONFIRMATION / UNKNOWN / UNAVAILABLE; a refused request keeps
      the previous state; the last refusal is remembered; the explanation names the state
  [3] the ceiling against the supervised proven level (owner record), its 3000 W fallback, an unavailable ceiling
  [4] the not-configured flag (and its availability) and the attention flag
  [5] the notification automation: create while a schedule is armed and the limits are not VALID, dismiss otherwise
  [6] the dashboard: one admin view, built-in cards only, no service call anywhere, the banner's condition, the markdown in the
      factory, valid and above-proven states; every entity it shows exists
  [7] the firmware factory state after the flash (3000 W, export 0) reads NOT CONFIGURED, shows the banner and raises attention
  [8] the post-export declaration (PEX entry fcc1): its place after fcp2, exactly the manifest chain-pinned, no frozen file, the
      files it adds, its fingerprint; undone, the manifest (as of fcc1) is its fcp2 state byte for byte
  [9] mutation: each named mutant of the package or the dashboard is caught
  [10] the old firmware (no fcp1 / fcp2 entities, e.g. the 4 October 2026 image): UNAVAILABLE, both flags unavailable, no
       notification even with a schedule armed, no banner, no values in the summary
  [11] the wording: the limit boxes and the arm are described as write-capable and firmware-protected, require_admin as NOT access
       control, the proven level as guidance; no DNO export value is assumed anywhere
  [12] reload-only initialisation (A5 fix, 15 Oct 2026): the limits state is also evaluated on event_template_reloaded, so an
       install or update by reloads alone (no restart) reads the dongle's real state at once instead of staying `unknown`; the
       fresh entity (no memory) still fails closed: a refusal on screen reads UNKNOWN with attention ON, an absent dongle
       UNAVAILABLE with both flags unavailable; nothing else in the trigger block or any other block changes

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import jinja2.sandbox
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _fcc1_scope as F  # noqa: E402
import _pex  # noqa: E402
import _scope_chain as chain  # noqa: E402

PKG_REL = F.PACKAGE_REL
DASH_REL = F.DASHBOARD_REL
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
DASH_TEXT = (ROOT / DASH_REL).read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
SCHED_TEXT = (ROOT / "home-assistant" / "packages" / "ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


E_STATUS = "sensor.ecco_clock_dongle_dump_power_limits_status"
E_CEIL = "number.ecco_clock_dongle_dump_to_grid_power_ceiling"
E_EXPORT = "number.ecco_clock_dongle_dump_to_grid_max_grid_export"
E_CAP = "sensor.ecco_clock_dongle_dump_to_grid_capability"
E_ARM = "switch.ecco_clock_dongle_dump_power_limits_write_enable"
E_PROVEN = "input_number.ecco_dump_supervised_proven_w"
E_STATE = "sensor.ecco_dump_limits_state"
E_ASSESS = "sensor.ecco_dump_ceiling_assessment"
E_NOTCONF = "binary_sensor.ecco_dump_export_limit_not_configured"
E_ATTN = "binary_sensor.ecco_dump_limits_attention"
E_SCHED = "input_boolean.ecco_dump_to_grid_schedule_armed"
STATES = ("VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION", "UNKNOWN", "UNAVAILABLE")


class L(yaml.SafeLoader):
    pass


L.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


# ---- a minimal Home Assistant template stand-in ---------------------------------------------------------------------------------
class This:
    def __init__(self, state=None, attributes=None):
        self.state = state
        self.attributes = dict(attributes or {})


def _float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        if default is None:
            raise ValueError(f"float filter without default on {v!r}")
        return default


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def render(template: str, world: dict, attrs: dict | None = None, this: This | None = None) -> str:
    env = jinja2.sandbox.ImmutableSandboxedEnvironment()
    env.filters["float"] = _float
    env.filters["is_number"] = _is_number
    attrs = attrs or {}
    g = {
        "states": lambda e: str(world.get(e, "unknown")),
        "is_state": lambda e, s: str(world.get(e, "unknown")) == s,
        "state_attr": lambda e, a: attrs.get(e, {}).get(a),
        "this": this or This(),
    }
    return env.from_string(template).render(**g).strip()


def package(text: str = PKG_TEXT) -> dict:
    return yaml.load(text, Loader=L)


def parts(text: str = PKG_TEXT):
    d = package(text)
    trig, plain = d["template"][0], d["template"][1]
    sensors = {s["unique_id"]: s for s in trig["sensor"] + plain["sensor"]}
    binaries = {b["unique_id"]: b for b in plain["binary_sensor"]}
    return d, sensors, binaries


def limits_state(world, prev=None, prev_attrs=None, text=PKG_TEXT):
    """(state, attributes) of sensor.ecco_dump_limits_state after one trigger, from the package's own templates."""
    _d, s, _b = parts(text)
    t = This(prev, prev_attrs)
    st = render(s["ecco_dump_limits_state"]["state"], world, this=t)
    at = {k: render(v, world, this=t) for k, v in s["ecco_dump_limits_state"]["attributes"].items()}
    return st, at


def model_state(msg: str, export: str, prev: str | None) -> str:
    """The independent reference: what the limits state must be for a status text."""
    if msg in ("unknown", "unavailable", "none", ""):
        return "UNAVAILABLE"
    if msg.startswith("REFUSED"):
        return prev if prev in ("VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION") else "UNKNOWN"
    if msg.startswith("INVALID"):
        return "AWAITING CONFIRMATION" if " confirmed; " in msg else "INVALID"
    if msg.startswith("VALID"):
        return "NOT CONFIGURED" if ("NOT CONFIGURED" in msg or _float(export, -1) == 0) else "VALID"
    return "UNKNOWN"


def firmware_entities() -> dict:
    d = yaml.load(FW_TEXT, Loader=L)
    out = {}
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor"), ("switch", "switch"),
                         ("number", "number"), ("button", "button"), ("select", "select")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", e["name"].lower())).strip("_")
                out[f"{domain}.ecco_clock_dongle_{slug}"] = e
    return out


FW_ENTITIES = firmware_entities()


# =====================================================================================================================================
def static_checks(pkg_text=PKG_TEXT, dash_text=DASH_TEXT, quiet=False) -> list[str]:
    """[0] / [6] static rules; returns the names of the rules broken (empty = all hold)."""
    bad = []
    d = package(pkg_text)
    if set(d) != {"input_number", "template", "automation"}:
        bad.append("top-level keys")
    actions = re.findall(r"^\s*-?\s*(?:action|service):\s*([\w.]+)", pkg_text, re.M)
    if sorted(set(actions)) != ["persistent_notification.create", "persistent_notification.dismiss"]:
        bad.append(f"package actions {sorted(set(actions))}")
    for tok in ("number.set_value", "switch.turn_on", "switch.turn_off", "button.press", "esphome.", "modbus", "script.", "input_number.set_value"):
        if tok in pkg_text:
            bad.append(f"package token {tok}")
    h = d["input_number"]["ecco_dump_supervised_proven_w"]
    if "initial" in h or h.get("min") != 3000 or h.get("max") > 8000:
        bad.append("proven helper initial / range")
    dd = yaml.load(dash_text, Loader=L)
    views = dd.get("views") or []
    types = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("type"), str):
                types.add(o["type"])
            for k, v in o.items():
                if k in ("tap_action", "hold_action", "double_tap_action", "service", "action", "perform_action"):
                    bad.append(f"dashboard key {k}")
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(views)
    if len(views) != 1 or not types <= {"conditional", "markdown", "entities"}:
        bad.append(f"dashboard views / card types {len(views)} {sorted(types)}")
    if "custom:" in dash_text or "button-card" in dash_text:
        bad.append("dashboard custom card")
    return bad


def referenced(text: str) -> set:
    """entity ids used in YAML content (comment lines, which name services in prose, are skipped)"""
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    return set(re.findall(r"\b((?:sensor|binary_sensor|number|switch|button|select|input_number|input_boolean)\.[a-z0-9_]+)", text))


print("[0] static: read only, helper, entities, slug, manifest")
bad = static_checks()
check("the package's only actions are persistent_notification.create / dismiss; no number / switch / button / script / esphome / "
      "Modbus token; top-level keys exactly input_number, template, automation", not [b for b in bad if b.startswith(("package", "top"))], str(bad))
d0 = package()
h0 = d0["input_number"]["ecco_dump_supervised_proven_w"]
check("the supervised proven level helper has NO `initial` (Home Assistant restores the owner's record) and its first-run value, the "
      "minimum, is 3000 W; range 3000..8000 W in 100 W steps", "initial" not in h0 and h0["min"] == 3000 and h0["max"] == 8000 and h0["step"] == 100)
own = {E_STATE, E_ASSESS, E_NOTCONF, E_ATTN, E_PROVEN}
pkg_refs = referenced(PKG_TEXT)
dongle = sorted(e for e in pkg_refs | referenced(DASH_TEXT) if "ecco_clock_dongle_" in e)
missing = [e for e in dongle if e not in FW_ENTITIES]
internal = [e for e in dongle if e in FW_ENTITIES and str(FW_ENTITIES[e].get("internal")).lower() in ("true", "yes")]
check(f"every dongle entity the package and the dashboard read ({len(dongle)}) exists in the firmware under that name and is not internal",
      not missing and not internal and len(dongle) >= 17, f"missing {missing} internal {internal}")
others = sorted(e for e in pkg_refs | referenced(DASH_TEXT) if "ecco_clock_dongle_" not in e and e not in own)
check("the only other entity read is the Dump schedule's armed helper, defined by its own package",
      others == [E_SCHED] and "ecco_dump_to_grid_schedule_armed:" in SCHED_TEXT, str(others))
outside = []
for line in (PKG_TEXT + DASH_TEXT).splitlines():
    for m in re.finditer(r"ecco_clock_dongle", line):
        in_entity = re.search(r"(sensor|binary_sensor|number|switch|button|select)\.$", line[:m.start()]) and line[m.end():m.end() + 1] == "_"
        prose = line.lstrip().startswith("#") and line[m.start() - 1:m.start()] == "`" and line[m.end():m.end() + 1] == "`"
        if not (in_entity or prose):
            outside.append(line.strip()[:90])
check("the device slug appears only inside dongle entity ids (`<domain>.ecco_clock_dongle_<object>`, the site renderer's rule) "
      "and once as the quoted default slug in the dashboard's header comment", not outside, str(outside[:3]))
man = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
md = yaml.safe_load(man)
check("the manifest deploys the package to /config/packages/ecco_dump_limits.yaml (the dashboard is deployed by hand: admin-only)",
      any(p.get("source") == PKG_REL and p.get("destination") == "/config/packages/ecco_dump_limits.yaml" for p in md["home_assistant_packages"])
      and md["dashboard"]["source"] == "home-assistant/dashboards/ecco_pro.yaml")

# =====================================================================================================================================
print("\n[1] firmware coupling: every status text the firmware publishes on Dump Power Limits Status")
fmts = sorted(set(re.findall(r'snprintf\(msg, sizeof\(msg\), "((?:VALID|INVALID|REFUSED|%s)[^"]*)"', FW_TEXT)))
limit_fmts = [f for f in fmts if "power ceiling" in f or "maximum grid export" in f or "INVALID - %s" in f]
check(f"the firmware has the limits status formats the package relies on ({len(limit_fmts)}): boot VALID / VALID NOT CONFIGURED / "
      "INVALID, per-limit REFUSED, VALID after a change, INVALID not saved, INVALID confirmed (awaiting the other limit)",
      len(limit_fmts) >= 9 and any(f.startswith("VALID - power ceiling %d W; maximum grid export NOT CONFIGURED") for f in limit_fmts)
      and sum(" confirmed; " in f for f in limit_fmts) == 2 and sum(f.startswith("REFUSED") for f in limit_fmts) == 2, str(limit_fmts))
fills_s = ["VALID", "", " (NOT CONFIGURED)", "integrity check failed (incomplete or corrupt save)",
           "stored for a different inverter capability profile", "arm Dump Power Limits Write Enable first"]
samples = []
for f in limit_fmts:
    n = f.count("%s")
    combos = [[]]
    for i in range(n):
        combos = [c + [x] for c in combos for x in (["VALID"] if (i == 0 and f.startswith("%s")) else fills_s[1:])]
    for c in combos:
        msg = f
        for x in c:
            msg = msg.replace("%s", x, 1)
        msg = re.sub(r"%d", "3000", msg)
        samples.append(msg)
mism = []
for msg in samples:
    for export in ("0", "3680", "unavailable"):
        for prev in (None, "VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION", "UNKNOWN"):
            got, _ = limits_state({E_STATUS: msg, E_EXPORT: export}, prev)
            want = model_state(msg, export, prev)
            if got != want:
                mism.append((msg[:60], export, prev, got, want))
check(f"all {len(samples)} firmware status texts x 3 export readings x 6 previous states: the package's state equals the independent "
      "model", not mism, str(mism[:4]))

# =====================================================================================================================================
print("\n[2] the limits state, its memory and its explanation")
W = lambda msg, ex="3680": {E_STATUS: msg, E_EXPORT: ex, E_CEIL: "3000.0", E_CAP: "8000"}   # noqa: E731
boot_nc = "VALID - power ceiling 3000 W; maximum grid export NOT CONFIGURED (Dump START refused until set)"
for msg, ex, prev, want in (
        (boot_nc, "0", None, "NOT CONFIGURED"),
        ("VALID - power ceiling 3000 W; maximum grid export 3680 W", "3680", None, "VALID"),
        ("VALID - power ceiling 3000 W; maximum grid export 3680 W (was 0 W)", "3680", "NOT CONFIGURED", "VALID"),
        ("VALID - power ceiling 3000 W; maximum grid export 0 W (was 3680 W) (NOT CONFIGURED)", "0", "VALID", "NOT CONFIGURED"),
        ("INVALID - integrity check failed (incomplete or corrupt save); Dump START refused until both limits are set again (arm, idle)", "3680", "VALID", "INVALID"),
        ("INVALID - power ceiling 3000 W confirmed; the maximum grid export must also be set again (after INVALID both limits are re-confirmed)", "3680", "INVALID", "AWAITING CONFIRMATION"),
        ("INVALID - power ceiling 3500 W could NOT be saved to flash (a power cut could restore the previous value); set both limits again", "3680", "VALID", "INVALID"),
        ("REFUSED - power ceiling 4000 W: arm Dump Power Limits Write Enable first; kept 3000 W", "3680", "VALID", "VALID"),
        ("REFUSED - maximum grid export 3680 W: arm Dump Power Limits Write Enable first; kept 0 W", "0", "NOT CONFIGURED", "NOT CONFIGURED"),
        ("REFUSED - power ceiling 4000 W: a raise is only accepted while Dump to Grid is idle; kept 3000 W", "3680", "INVALID", "INVALID"),
        ("REFUSED - power ceiling 4000 W: arm Dump Power Limits Write Enable first; kept 3000 W", "3680", None, "UNKNOWN"),
        ("unavailable", "unavailable", "VALID", "UNAVAILABLE"),
        ("something new", "3680", "VALID", "UNKNOWN")):
    got, at = limits_state(W(msg, ex), prev)
    check(f"{msg[:58]!r} (export {ex}, previous {prev}) -> {want}", got == want, got)
_st, at1 = limits_state(W("REFUSED - power ceiling 4000 W: arm Dump Power Limits Write Enable first; kept 3000 W"), "VALID")
_st, at2 = limits_state(W("VALID - power ceiling 3000 W; maximum grid export 3680 W"), "VALID", at1)
check("a refusal is remembered in last_refusal and survives the next accepted change; the status attribute is the dongle's text",
      at1["last_refusal"].startswith("REFUSED - power ceiling 4000 W") and at2["last_refusal"] == at1["last_refusal"]
      and at2["status"].startswith("VALID - power ceiling"))
expl = {}
for msg, ex, prev in ((boot_nc, "0", None), ("VALID - power ceiling 3000 W; maximum grid export 3680 W", "3680", None),
                      ("INVALID - integrity check failed (incomplete or corrupt save); Dump START refused until both limits are set again (arm, idle)", "3680", None),
                      ("INVALID - power ceiling 3000 W confirmed; the maximum grid export must also be set again (after INVALID both limits are re-confirmed)", "3680", None),
                      ("unavailable", "unavailable", None), ("REFUSED - x", "3680", None)):
    s, a = limits_state(W(msg, ex), prev)
    expl[s] = a["explanation"]
check("the explanation matches the state: NOT CONFIGURED says every START is refused until the DNO export is set; INVALID needs both "
      "limits again; AWAITING names the other limit; UNAVAILABLE / UNKNOWN say the dongle still enforces its state",
      "every Dump to Grid START" in expl["NOT CONFIGURED"] and "DNO" in expl["NOT CONFIGURED"] and "BOTH limits" in expl["INVALID"]
      and "the other must also be set again" in expl["AWAITING CONFIRMATION"] and "does not report" in expl["UNAVAILABLE"]
      and "enforces its own state" in expl["UNKNOWN"] and expl["VALID"].startswith("Both limits are valid"), str(expl))

# =====================================================================================================================================
print("\n[3] the ceiling against the supervised proven level")
_d, SENS, BIN = parts()
for ceil, proven, want in (("3000.0", "3000.0", "AT PROVEN LEVEL"), ("4000.0", "3000.0", "ABOVE PROVEN LEVEL"), ("2500.0", "3000.0", "BELOW PROVEN LEVEL"),
                           ("4000.0", "4000.0", "AT PROVEN LEVEL"), ("4000.0", "unavailable", "ABOVE PROVEN LEVEL"), ("3000.0", "unknown", "AT PROVEN LEVEL"),
                           ("unavailable", "3000.0", "UNAVAILABLE")):
    got = render(SENS["ecco_dump_ceiling_assessment"]["state"], {E_CEIL: ceil, E_PROVEN: proven})
    check(f"ceiling {ceil}, proven {proven} -> {want} (an unreadable record counts as 3000 W, never higher)", got == want, got)

# =====================================================================================================================================
print("\n[4] the not-configured and attention flags")
for ex, want, avail in (("0.0", "True", "True"), ("3680.0", "False", "True"), ("unavailable", "False", "False"), ("unknown", "False", "False")):
    b = BIN["ecco_dump_export_limit_not_configured"]
    got, av = render(b["state"], {E_EXPORT: ex}), render(b["availability"], {E_EXPORT: ex})
    check(f"export {ex}: not configured {want}, available {avail}", got == want and av == avail, f"{got} {av}")
for st, assess, arm, want in (("VALID", "AT PROVEN LEVEL", "off", "False"), ("NOT CONFIGURED", "AT PROVEN LEVEL", "off", "True"),
                              ("INVALID", "AT PROVEN LEVEL", "off", "True"), ("AWAITING CONFIRMATION", "AT PROVEN LEVEL", "off", "True"),
                              ("UNKNOWN", "AT PROVEN LEVEL", "off", "True"), ("UNAVAILABLE", "UNAVAILABLE", "unavailable", "True"),
                              ("VALID", "ABOVE PROVEN LEVEL", "off", "True"), ("VALID", "BELOW PROVEN LEVEL", "on", "True")):
    got = render(BIN["ecco_dump_limits_attention"]["state"], {E_STATE: st, E_ASSESS: assess, E_ARM: arm})
    check(f"attention: state {st}, {assess}, arm {arm} -> {want}", got == want, got)
for st, want in (("VALID", "True"), ("NOT CONFIGURED", "True"), ("UNKNOWN", "True"), ("UNAVAILABLE", "False"), ("unknown", "False")):
    got = render(BIN["ecco_dump_limits_attention"]["availability"], {E_STATE: st})
    check(f"attention availability with limits state {st} -> {want}", got == want, got)

# =====================================================================================================================================
print("\n[5] the notification automation")
aut = d0["automation"]
a = aut[0] if len(aut) == 1 else {}
ch = a.get("actions", [{}])[0].get("choose", [{}])[0] if a else {}
conds = ch.get("conditions", [])
check("one automation, notification only: create (id ecco_dump_limits_schedule) when the schedule helper is on AND the limits state is "
      "not VALID, else dismiss the same id; triggers on start, the limits state and the schedule helper",
      len(aut) == 1 and conds[0].get("entity_id") == E_SCHED and conds[0].get("state") == "on"
      and all(render(conds[1]["value_template"], {E_STATE: s}) == ("True" if s in ("NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION") else "False")
              for s in STATES)
      and ch["sequence"][0]["action"] == "persistent_notification.create" and ch["sequence"][0]["data"]["notification_id"] == "ecco_dump_limits_schedule"
      and a["actions"][0]["default"][0]["action"] == "persistent_notification.dismiss"
      and a["actions"][0]["default"][0]["data"]["notification_id"] == "ecco_dump_limits_schedule"
      and {E_STATE, E_SCHED} <= set(a["triggers"][1]["entity_id"]))
msg = render(ch["sequence"][0]["data"]["message"], {E_STATE: "NOT CONFIGURED"}, {E_STATE: {"explanation": "X-EXPLANATION"}})
check("the notification names the state and carries its explanation", "NOT CONFIGURED" in msg and "X-EXPLANATION" in msg, msg)

# =====================================================================================================================================
print("\n[6] the dashboard")
check("one admin view; built-in cards only (conditional, markdown, entities); no tap / hold / double-tap action, service or action key "
      "anywhere; no custom card", not [b for b in static_checks() if b.startswith("dashboard")], str(static_checks()))
DD = yaml.load(DASH_TEXT, Loader=L)
cards = DD["views"][0]["cards"]
ban = cards[0]
check("the first card is the NOT CONFIGURED banner, shown only while the not-configured flag is on, and says every START is refused",
      ban["type"] == "conditional" and ban["conditions"] == [{"condition": "state", "entity": E_NOTCONF, "state": "on"}]
      and "Every Dump to Grid START is refused" in ban["card"]["content"] and "DNO" in ban["card"]["content"])
ents = [e["entity"] if isinstance(e, dict) else e for c in cards if c["type"] == "entities" for e in c["entities"]]
check("the dashboard shows the two limits, the arm, the state, the dongle status, the assessment, the lease ceiling, the profile and its "
      "capability, the proven record, the restore / containment / lockout states and the four readiness states",
      {E_CEIL, E_EXPORT, E_ARM, E_STATE, E_STATUS, E_ASSESS, E_PROVEN, E_CAP,
       "sensor.ecco_clock_dongle_inverter_capability_profile", "sensor.ecco_clock_dongle_dump_to_grid_lease_ceiling",
       "sensor.ecco_clock_dongle_dump_to_grid_recovery_state", "sensor.ecco_clock_dongle_dump_to_grid_export_containment",
       "sensor.ecco_clock_dongle_dump_to_grid_controller_state", "binary_sensor.ecco_clock_dongle_ecco_safe_to_flash",
       "sensor.ecco_clock_dongle_ecco_flash_readiness", "sensor.ecco_clock_dongle_restart_status",
       "sensor.ecco_clock_dongle_ecco_build_identity"} <= set(ents), str(sorted(set(ents))))
check("no recovery or restart CONTROL is offered here (Force Restore, Accept, Restart, Restart Override Arm stay off this dashboard)",
      not any(x in DASH_TEXT for x in ("button.ecco_clock_dongle", "restart_override_arm", "recovery_arm")))
summary = next(c for c in cards if c.get("title") == "Dump to Grid limits")
m_nc = render(summary["content"], {E_STATE: "NOT CONFIGURED", E_CEIL: "3000.0", E_EXPORT: "0.0", E_PROVEN: "3000.0", E_NOTCONF: "on", E_ASSESS: "AT PROVEN LEVEL"},
              {E_STATE: {"explanation": "EXPL-NC", "last_refusal": ""}})
m_hi = render(summary["content"], {E_STATE: "VALID", E_CEIL: "4000.0", E_EXPORT: "3680.0", E_PROVEN: "3000.0", E_NOTCONF: "off", E_ASSESS: "ABOVE PROVEN LEVEL"},
              {E_STATE: {"explanation": "EXPL-V", "last_refusal": "REFUSED - power ceiling 5000 W: arm first; kept 4000 W"}})
check("the summary in the factory state: state NOT CONFIGURED, export shown as NOT CONFIGURED (never as 0 W), ceiling 3000 W, no "
      "above-proven warning, no refusal line", "State: NOT CONFIGURED" in m_nc and "maximum grid export **NOT CONFIGURED**" in m_nc
      and "3000.0 W" in m_nc and "ABOVE" not in m_nc and "refused" not in m_nc and "EXPL-NC" in m_nc, m_nc)
check("the summary above the proven level: the warning and the last refusal are shown, the export in W",
      "ABOVE the supervised proven level" in m_hi and "Last refused request: REFUSED - power ceiling 5000 W" in m_hi and "3680.0 W" in m_hi, m_hi)
howto = next(c for c in cards if c.get("title") == "How the limits change")["content"]
check("the how-to states the dongle's rules: lowering any time, raising needs the arm (60 s, one change) and idle, both limits after "
      "INVALID, a rated power is not a proof", all(x in howto for x in ("Lowering", "any time", "Limits write enable", "60 s", "idle",
                                                                        "**both** limits", "not a proof")))

# =====================================================================================================================================
print("\n[7] the firmware factory state after the flash")
fw_init = {g["id"]: str(g.get("initial_value")) for g in yaml.load(FW_TEXT, Loader=L)["globals"] if g.get("id") in ("dump_op_ceiling_w", "dump_max_export_w")}
subs = yaml.load(FW_TEXT, Loader=L)["substitutions"]
check("the firmware's factory limits are a 3000 W ceiling and export 0 (not configured)",
      fw_init == {"dump_op_ceiling_w": "${ecco_dump_controller_max_ceiling_w}", "dump_max_export_w": "0"}
      and str(subs["ecco_dump_controller_max_ceiling_w"]) == "3000", str(fw_init))
st, at = limits_state(W(boot_nc, "0"), None)
attn = render(BIN["ecco_dump_limits_attention"]["state"], {E_STATE: st, E_ASSESS: "AT PROVEN LEVEL", E_ARM: "off"})
nc = render(BIN["ecco_dump_export_limit_not_configured"]["state"], {E_EXPORT: "0.0"})
check("first boot: NOT CONFIGURED, the banner flag on, attention on", st == "NOT CONFIGURED" and nc == "True" and attn == "True", f"{st} {nc} {attn}")

# =====================================================================================================================================
print("\n[8] the post-export declaration (PEX entry fcc1)")
E = chain.CHAIN.entry("fcc1")
ids = [e.id for e in chain.POST_EXPORT_ENTRIES]
check("fcc1 sits right after fcp2", "fcc1" in ids and chain.CHAIN.prev_id("fcc1") == "fcp2", str(ids))   # smr1: no longer the newest
check("fcc1 chain-pins exactly the manifest, edits no frozen file, adds exactly its five files (all present)",
      set(E.reverts) == {F.MANIFEST_REL} and not E.frozen_reverts and E.added_files == F.ADDED_FILES
      and all((ROOT / p).is_file() for p in F.ADDED_FILES), str(sorted(E.added_files)))
live = _pex.read(F.MANIFEST_REL)   # PEX: today's manifest
cur = _pex.as_of(F.MANIFEST_REL, "fcc1", live)   # PEX: the manifest as of fcc1 (smr1 edits it later)
before = _pex.as_of(F.MANIFEST_REL, "fcp2", live)   # PEX: the manifest as of fcp2 (fcc1 undone exactly, sha256-checked)
check("undone exactly, the manifest is its fcp2 state, and applying fcc1's pair to it gives today's manifest; the checkpoint is its sha256",
      F.pre_fcc1_manifest(cur) == before and F.add_fcc1_manifest(before) == cur and E.checkpoints == {chain.HA_MANIFEST: F.sha(cur)})
check("fcc1's fingerprint is sealed and linked to fcp2's", E.fingerprint == _pex.fingerprint(E)   # PEX: hash link
      and _pex.record(E)["parent"] == chain.CHAIN.entry("fcp2").fingerprint)

# =====================================================================================================================================
print("\n[9] mutation: each named mutant is caught")


def caught_state(text):
    try:
        bad_rows = []
        for msg, ex, prev, want in ((boot_nc, "0", None, "NOT CONFIGURED"),
                                    ("REFUSED - power ceiling 4000 W: arm Dump Power Limits Write Enable first; kept 3000 W", "3680", "INVALID", "INVALID"),
                                    ("INVALID - power ceiling 3000 W confirmed; the maximum grid export must also be set again (after INVALID both limits are re-confirmed)", "3680", None, "AWAITING CONFIRMATION"),
                                    ("VALID - power ceiling 3000 W; maximum grid export 0 W", "0", None, "NOT CONFIGURED")):
            if limits_state(W(msg, ex), prev, text=text)[0] != want:
                bad_rows.append(msg)
        _d2, s2, _b2 = parts(text)
        if render(s2["ecco_dump_ceiling_assessment"]["state"], {E_CEIL: "4000.0", E_PROVEN: "unknown"}) != "ABOVE PROVEN LEVEL":
            bad_rows.append("assessment")
        return bool(bad_rows) or bool(static_checks(text, DASH_TEXT))
    except Exception:
        return True


MUTANTS = [
    ("a refusal no longer keeps the previous state", "{%- elif m.startswith('REFUSED') -%}{{ prev }}", "{%- elif false -%}{{ prev }}"),
    ("AWAITING CONFIRMATION folded into INVALID", "{%- elif m.startswith('INVALID') and ' confirmed; ' in m -%}AWAITING CONFIRMATION\n",
     "{%- elif false -%}AWAITING CONFIRMATION\n"),
    ("NOT CONFIGURED read only from the text, not from export 0", "{%- if 'NOT CONFIGURED' in m or (ex | float(-1)) == 0 -%}NOT CONFIGURED",
     "{%- if 'NOT CONFIGURED' in m -%}NOT CONFIGURED"),
    ("an unreadable proven record counts as 8000 W", "| float(3000) -%}", "| float(8000) -%}"),
    ("the package writes the ceiling", "            sequence:\n              - action: persistent_notification.create",
     "            sequence:\n              - action: number.set_value\n                target:\n                  entity_id: number.ecco_clock_dongle_dump_to_grid_power_ceiling\n                data:\n                  value: 3000\n              - action: persistent_notification.create"),
    ("the proven record gets an initial value", "    min: 3000\n", "    initial: 8000\n    min: 3000\n"),
]
for name, old, new in MUTANTS:
    assert PKG_TEXT.count(old) >= 1, name
    check(f"mutant caught: {name}", caught_state(PKG_TEXT.replace(old, new, 1)))
dash_mut = DASH_TEXT.replace("          - entity: sensor.ecco_dump_limits_state\n", "          - entity: sensor.ecco_dump_limits_state\n            tap_action:\n              action: perform-action\n              perform_action: number.set_value\n", 1)
check("mutant caught: the dashboard gains a service-calling tap action", bool(static_checks(PKG_TEXT, dash_mut)))
check("the unmutated package and dashboard pass every mutant check", not caught_state(PKG_TEXT))

# =====================================================================================================================================
print("\n[10] the old firmware: the fcp1 / fcp2 entities do not exist")
OLD = {E_SCHED: "on", E_PROVEN: "3000.0"}   # every dongle entity missing: states() reads 'unknown'
st, at = limits_state(OLD, None)
st2, _ = limits_state(OLD, "VALID")
check("the limits state reads UNAVAILABLE (also after a VALID state), with an explanation that names firmware without fcp1",
      st == "UNAVAILABLE" and st2 == "UNAVAILABLE" and "firmware without fcp1" in at["explanation"], f"{st} {st2}")
w_old = dict(OLD, **{E_STATE: st, E_ASSESS: render(SENS["ecco_dump_ceiling_assessment"]["state"], OLD)})
check("the ceiling assessment reads UNAVAILABLE, the not-configured flag and the attention flag are unavailable (no false alert)",
      w_old[E_ASSESS] == "UNAVAILABLE" and render(BIN["ecco_dump_export_limit_not_configured"]["availability"], OLD) == "False"
      and render(BIN["ecco_dump_limits_attention"]["availability"], w_old) == "False")
check("with a Dump schedule ARMED, the automation's condition is false: no notification (the old firmware refuses no START for limits)",
      render(conds[1]["value_template"], w_old) == "False")
check("the NOT CONFIGURED banner stays hidden (its flag is not 'on')", ban["conditions"][0]["state"] == "on" and w_old.get(E_NOTCONF, "unavailable") != "on")
m_old = render(summary["content"], dict(w_old, **{E_NOTCONF: "unavailable"}), {E_STATE: {"explanation": at["explanation"], "last_refusal": ""}})
check("the summary shows the state and its explanation but no limit values (never 'unknown W')",
      "State: UNAVAILABLE" in m_old and "unknown W" not in m_old and "Power ceiling" not in m_old, m_old)

# =====================================================================================================================================
print("\n[11] the wording: write-capable, protected, not access control, guidance, no DNO value assumed")
DOC = (ROOT / "docs" / "dev" / "full-capability-controls.md").read_text(encoding="utf-8")
check("the dashboard and the docs call the limit boxes and the arm write-capable and say the dongle validates every request",
      "WRITE-CAPABLE" in DASH_TEXT and "number.set_value / switch.turn_on" in DASH_TEXT and "**write-capable**" in DOC
      and "validates every request" in DASH_TEXT)
check("require_admin is described as hiding the dashboard, NOT as access control (dashboard header and docs)",
      "It is NOT" in DASH_TEXT and "access" in DASH_TEXT.split("It is NOT", 1)[1][:30] and "it is **not**" in DOC and "access control" in DOC
      and "admin-only" not in DASH_TEXT.lower() and "admin-only" not in DOC.lower())
check("the proven level is described as guidance, not a limit, with the dongle's ceiling as the enforced one (package, dashboard, docs)",
      "GUIDANCE ONLY" in PKG_TEXT and "it is not a limit" in PKG_TEXT and "guidance" in DASH_TEXT and "**Guidance only:**" in DOC)
check("no DNO export value is assumed: no 3680 / 3.68 kW in the package, the dashboard or the docs; the docs say not to assume a G98 figure",
      not any(x in s for s in (PKG_TEXT, DASH_TEXT, DOC) for x in ("3680", "3.68")) and "assume a G98 figure is approved" in DOC)


# =====================================================================================================================================
print("\n[12] reload-only initialisation (A5 fix): the limits state is evaluated on a template reload")
# Home Assistant 2026.9.4 (homeassistant/components/template): _reload_config awaits _process_config, whose coordinator attaches the
# triggers at once while Home Assistant is running, and only then fires event_template_reloaded; a trigger entity added after that
# event renders the coordinator's data in async_added_to_hass (and skips the restore). So the reload trigger evaluates the state once.
D12 = package()
TRIG = D12["template"][0]["triggers"]
check("the limits-state block triggers on Home Assistant start, on every template reload, and on the three dongle entities",
      {"trigger": "homeassistant", "event": "start"} in TRIG and {"trigger": "event", "event_type": "event_template_reloaded"} in TRIG
      and [x for x in TRIG if x.get("trigger") == "state"] == [{"trigger": "state", "entity_id": [E_STATUS, E_EXPORT, E_CEIL]}]
      and len(TRIG) == 3, str(TRIG))
check("the reload trigger is the only addition: the block still has no conditions, actions or variables, and the plain block "
      "(assessment, both flags) has no triggers", set(D12["template"][0]) == {"triggers", "sensor"} and "triggers" not in D12["template"][1]
      and len(D12["template"]) == 2)
# A fresh entity after the reload has no memory (this.state unknown): the trigger renders from the dongle's state alone.
st, _at = limits_state(W(boot_nc, "0"), None)
attn_av = render(BIN["ecco_dump_limits_attention"]["availability"], {E_STATE: st})
attn = render(BIN["ecco_dump_limits_attention"]["state"], {E_STATE: st, E_ASSESS: "AT PROVEN LEVEL", E_ARM: "off"})
check("reload-only install on the flashed dongle (factory limits): NOT CONFIGURED at once, attention available and ON",
      st == "NOT CONFIGURED" and attn_av == "True" and attn == "True", f"{st} {attn_av} {attn}")
st_r, _ = limits_state(W("REFUSED - power ceiling 4000 W: arm Dump Power Limits Write Enable first; kept 3000 W", "0"), None)
check("fail closed: a reload while the dongle shows a REFUSED message gives UNKNOWN (no memory to keep), attention available and ON",
      st_r == "UNKNOWN" and render(BIN["ecco_dump_limits_attention"]["availability"], {E_STATE: st_r}) == "True"
      and render(BIN["ecco_dump_limits_attention"]["state"], {E_STATE: st_r, E_ASSESS: "AT PROVEN LEVEL", E_ARM: "off"}) == "True", st_r)
st_u, _ = limits_state({E_STATUS: "unavailable", E_EXPORT: "unavailable", E_CEIL: "unavailable"}, None)
check("fail closed: a reload while the dongle is offline gives UNAVAILABLE, attention and the banner flag unavailable (unchanged)",
      st_u == "UNAVAILABLE" and render(BIN["ecco_dump_limits_attention"]["availability"], {E_STATE: st_u}) == "False"
      and render(BIN["ecco_dump_export_limit_not_configured"]["availability"], {E_EXPORT: "unavailable"}) == "False", st_u)
st_v, _ = limits_state(W("VALID - power ceiling 3000 W; maximum grid export 3680 W", "3680"), None)
check("a reload after the limits are configured gives VALID, attention OFF (no nuisance)",
      st_v == "VALID" and render(BIN["ecco_dump_limits_attention"]["state"], {E_STATE: st_v, E_ASSESS: "AT PROVEN LEVEL", E_ARM: "off"}) == "False", st_v)
# The notification automation follows the state: unknown -> NOT CONFIGURED is a state change of its own trigger entity.
a12 = D12["automation"][0]
check("the schedule notice still triggers on the limits state, so the reload's first evaluation reaches it (create while a schedule "
      "is armed, dismiss otherwise)", E_STATE in a12["triggers"][1]["entity_id"]
      and render(a12["actions"][0]["choose"][0]["conditions"][1]["value_template"], {E_STATE: "NOT CONFIGURED"}) == "True")


def has_reload_trigger(text):
    try:
        return {"trigger": "event", "event_type": "event_template_reloaded"} in package(text)["template"][0]["triggers"]
    except Exception:
        return False


RELOAD = "      - trigger: event\n        event_type: event_template_reloaded\n"
assert PKG_TEXT.count(RELOAD) == 1
check("mutant caught: the reload trigger removed (a reload-only install would stay unknown again)",
      not has_reload_trigger(PKG_TEXT.replace(RELOAD, "", 1)))
check("mutant caught: the reload trigger listening to the wrong event",
      not has_reload_trigger(PKG_TEXT.replace("event_type: event_template_reloaded", "event_type: event_automation_reloaded", 1)))
check("the unmutated package has the reload trigger", has_reload_trigger(PKG_TEXT))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
