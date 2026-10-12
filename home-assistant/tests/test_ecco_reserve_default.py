"""Offline suite for the battery reserve helper's first-run value (post-export entry rsv1).

`input_number.ecco_minimum_reserve_soc` is the user's own battery reserve: editable in Home Assistant, 0-80 %. 40 % is only the STARTING
value of a new installation. This suite pins that, against the real core package (home-assistant/packages/ecco_pro.yaml), with a small
model of what Home Assistant does at start-up (the rules below were read from the Home Assistant 2026.9.4 source):

  - input_number: a configured `initial` WINS over the restored state at every start; otherwise the last state is restored if it is a
    number inside [min, max], else the helper starts at its minimum. A set_value outside [min, max] raises (it does not clamp).
  - input_boolean: a configured `initial` wins; otherwise it is on only if its last state was on, else off.
  - an action that raises ends that automation run: the actions after it do not run.

What is proven:

  [1] the helper       user-editable (0-80, step 1, box), defined once, NO `initial` (an `initial` would overwrite the user's value at
                       every start); the first-run flag is a plain input_boolean without `initial`, so it is restored too
  [2] first run        the one-time automation: Home Assistant start trigger, gated on the flag being off, starts the reserve at 40,
                       turns the flag on in the same run, and every value it sets is inside its helper's range (an out-of-range value
                       would end the run before the flag is set, and the defaults would run again at every start)
  [3] scenarios        a new installation starts at 40; an existing installation keeps ANY value it holds (including 0 and the old
                       first-run 15), whatever default the package ships; an upgrade that changes the shipped default keeps the
                       user's value; a user's change survives repeated restarts; a deliberate 0 is a value, not "unset"; the
                       first-run automation runs once; an unusable restored value falls to the helper's minimum and is never
                       replaced by a guess; the documented limit (a first-run flag that is not restored as on re-applies ALL
                       first-run defaults) is pinned
  [4] one writer       nothing but the first-run automation writes the helper: no other automation, script, dashboard or card source
  [5] runtime          no runtime decision hard-codes 40 %; the configuration mirror sensor passes the selected value through; the
                       firmware cannot see the helper; Intelligence uses its own configured reserve and takes the helper only as a
                       run-time input that can raise it (unusable values ignored), and its default agrees with the starting value;
                       the battery time-to-reserve package reads the helper and treats an unusable value as unavailable
  [6] Dump-to-Grid     its own Stop SOC (firmware number: default 25 %, 10-90 %, start and end gates; the scheduler's 10-90 %
                       helper and bounds) is unchanged and never references the reserve; mutants that wire it to the reserve are caught
  [7] mutation         in-memory mutants of the package are each caught (the old 15, an `initial`, a missing gate, a missing flag
                       turn-on, an out-of-range value, an `initial` flag, a second writer); a harmless change is not

Writes nothing; no Home Assistant, no network, no hardware. It does not prove the automation on a live Home Assistant instance.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import jinja2
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

PKG_DIR = ROOT / "home-assistant" / "packages"
CORE_PKG = PKG_DIR / "ecco_pro.yaml"
RUNTIME_PKG = PKG_DIR / "ecco_runtime_config.yaml"

RESERVE = "ecco_minimum_reserve_soc"
RESERVE_ID = f"input_number.{RESERVE}"
MIRROR_ID = "sensor.ecco_config_minimum_reserve_soc"
FLAG = "ecco_defaults_initialized"
FLAG_ID = f"input_boolean.{FLAG}"
AUTOMATION_ID = "ecco_phase3a_initialize_defaults"
FIRST_RUN_VALUE = 40.0

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))
        FAILURES.append(name)


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps Home Assistant's custom tags (!secret, !include ...) as None."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def load(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


# ===================================================================================================================
# A model of Home Assistant start-up for the helpers and the start automations of one package
# ===================================================================================================================
class HAError(Exception):
    """An action raised: Home Assistant ends the automation run there."""


class Unmodelled(Exception):
    """The package uses something this model does not cover: review it, then extend the model."""


def as_list(v):
    return [] if v is None else v if isinstance(v, list) else [v]


class Instance:
    def __init__(self, pkg: dict, restored: dict[str, str] | None = None):
        restored = restored or {}
        self.pkg = pkg
        self.defs: dict[str, dict] = {}
        self.state: dict[str, object] = {}
        self.aborted: list[str] = []
        for domain in ("input_number", "input_boolean", "input_select"):
            for key, cfg in (pkg.get(domain) or {}).items():
                eid = f"{domain}.{key}"
                cfg = cfg or {}
                self.defs[eid] = cfg
                self.state[eid] = self._start_state(domain, cfg, restored.get(eid))
        self._home_assistant_start()

    @staticmethod
    def _start_state(domain: str, cfg: dict, restored):
        if domain == "input_number":
            lo, hi = float(cfg["min"]), float(cfg["max"])
            if cfg.get("initial") is not None:
                return float(cfg["initial"])
            try:
                v = float(restored)
            except (TypeError, ValueError):
                return lo
            return v if lo <= v <= hi else lo
        if domain == "input_boolean":
            if cfg.get("initial") is not None:
                return "on" if cfg["initial"] else "off"
            return "on" if restored == "on" else "off"
        options = cfg["options"]
        if cfg.get("initial") in options:
            return cfg["initial"]
        return restored if restored in options else options[0]

    # ---- services -------------------------------------------------------------------------------------------------
    def call(self, action: str, entity_ids: list[str], data: dict | None = None) -> None:
        data = data or {}
        for eid in entity_ids:
            if eid not in self.defs:
                raise HAError(f"{action}: {eid} does not exist")
            cfg = self.defs[eid]
            if action == "input_number.set_value":
                v = float(data["value"])
                if v < float(cfg["min"]) or v > float(cfg["max"]):
                    raise HAError(f"{eid}: {v} is outside [{cfg['min']}, {cfg['max']}]")
                self.state[eid] = v
            elif action in ("input_boolean.turn_on", "input_boolean.turn_off"):
                self.state[eid] = "on" if action.endswith("turn_on") else "off"
            elif action == "input_select.select_option":
                if data["option"] not in cfg["options"]:
                    raise HAError(f"{eid}: {data['option']} is not an option")
                self.state[eid] = data["option"]
            else:
                raise Unmodelled(action)

    def user_set(self, eid: str, value: float) -> None:
        """The user edits a helper in Home Assistant (a service call from the UI)."""
        self.call("input_number.set_value", [eid], {"value": value})

    # ---- start automations ----------------------------------------------------------------------------------------
    def _home_assistant_start(self) -> None:
        for auto in as_list(self.pkg.get("automation")):
            triggers = as_list(auto.get("triggers", auto.get("trigger")))
            if not any((t.get("trigger", t.get("platform")) == "homeassistant" and t.get("event") == "start") for t in triggers):
                continue
            if not all(self._condition(c) for c in as_list(auto.get("conditions", auto.get("condition")))):
                continue
            try:
                for act in as_list(auto.get("actions", auto.get("action"))):
                    name = act.get("action", act.get("service"))
                    if name is None:
                        raise Unmodelled(str(sorted(act)))
                    ids = as_list((act.get("target") or {}).get("entity_id"))
                    self.call(name, ids, act.get("data"))
            except HAError as err:
                self.aborted.append(f"{auto.get('id')}: {err}")

    def _condition(self, c: dict) -> bool:
        if c.get("condition") != "state":
            raise Unmodelled(str(c))
        want = [str(s) for s in as_list(c["state"])]
        return all(str(self.state[e]) in want for e in as_list(c["entity_id"]))

    # ---- the user's view ------------------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, str]:
        """What Home Assistant stores at shutdown and restores at the next start."""
        return {k: (str(v) if not isinstance(v, str) else v) for k, v in self.state.items()}

    def restart(self) -> "Instance":
        return Instance(self.pkg, self.snapshot())

    def num(self, eid: str) -> float:
        return float(self.state[eid])


def first_run_automation(pkg: dict) -> dict:
    found = [a for a in as_list(pkg.get("automation")) if a.get("id") == AUTOMATION_ID]
    return found[0] if len(found) == 1 else {}


def reserve_actions(pkg: dict) -> list[dict]:
    return [a for a in as_list(first_run_automation(pkg).get("actions"))
            if a.get("action") == "input_number.set_value" and as_list((a.get("target") or {}).get("entity_id")) == [RESERVE_ID]]


def with_first_run_value(pkg: dict, value: float) -> dict:
    out = copy.deepcopy(pkg)
    for a in reserve_actions(out):
        a["data"]["value"] = value
    return out


def scenarios(pkg: dict) -> list[str]:
    """Runs every installation / restart / user-change scenario against `pkg`; returns the names of the ones that fail."""
    bad: list[str] = []

    def expect(name: str, cond: bool) -> None:
        if not cond:
            bad.append(name)

    fresh = Instance(pkg)
    expect("a new installation starts at the first-run value (40)", fresh.num(RESERVE_ID) == FIRST_RUN_VALUE)
    expect("the first run turns the flag on", fresh.state[FLAG_ID] == "on")
    expect("the first run completes (no action raised)", not fresh.aborted)

    for v in (0, 1, 15, 25, 33, 40, 55, 80):
        ex = Instance(pkg, {RESERVE_ID: str(float(v)), FLAG_ID: "on"})
        expect(f"an initialised installation keeps its reserve {v}", ex.num(RESERVE_ID) == v and not ex.aborted)
    old = Instance(pkg, {RESERVE_ID: "15.0", FLAG_ID: "on"})
    expect("an installation still holding the old first-run 15 is not migrated", old.num(RESERVE_ID) == 15)

    for shipped in (15, 40, 60):
        variant = with_first_run_value(pkg, shipped)
        expect(f"if the shipped default were {shipped}, a new installation would start there", Instance(variant).num(RESERVE_ID) == shipped)
        expect(f"if the shipped default were {shipped}, an existing 25 stays 25",
               Instance(variant, {RESERVE_ID: "25.0", FLAG_ID: "on"}).num(RESERVE_ID) == 25)

    inst = Instance(pkg)
    inst.user_set(RESERVE_ID, 33)
    expect("the user's change takes effect", inst.num(RESERVE_ID) == 33)
    for n in (1, 2, 3):
        inst = inst.restart()
        expect(f"the user's 33 survives restart {n}", inst.num(RESERVE_ID) == 33 and inst.state[FLAG_ID] == "on" and not inst.aborted)
    inst.user_set(RESERVE_ID, 0)
    inst = inst.restart()
    expect("a deliberate 0 survives a restart (a value, not 'unset')", inst.num(RESERVE_ID) == 0)
    inst.user_set(RESERVE_ID, 80)
    inst = inst.restart().restart()
    expect("the top of the range survives restarts", inst.num(RESERVE_ID) == 80)

    upd = Instance(with_first_run_value(pkg, 15))
    upd.user_set(RESERVE_ID, 29)
    upd = Instance(pkg, upd.snapshot())
    expect("an update that changes the shipped default keeps the user's value", upd.num(RESERVE_ID) == 29)

    # An unusable restored reserve: Home Assistant starts the helper at its minimum and the first-run automation (flag on) does not
    # guess a value for an installation it already initialised.
    for unusable in ("unknown", "unavailable", "", "abc", "nan", "-5", "81", "1000"):
        iv = Instance(pkg, {RESERVE_ID: unusable, FLAG_ID: "on"})
        expect(f"an unusable restored reserve {unusable!r} falls to the helper's minimum, never to a guessed value",
               iv.num(RESERVE_ID) == 0 and iv.state[FLAG_ID] == "on" and not iv.aborted)
    # The documented limit: a first-run flag that is not restored as ON makes the installation look new, so ALL first-run defaults
    # (the reserve included) are applied again. Home Assistant stores the helpers and the flag in the same file, so this needs that
    # file to be lost or the flag to be reset on purpose.
    for lost in (None, "off", "unknown", "unavailable"):
        lf = Instance(pkg, {RESERVE_ID: "25.0", **({} if lost is None else {FLAG_ID: lost})})
        expect(f"documented limit: a first-run flag restored as {lost!r} applies the first-run defaults again",
               lf.num(RESERVE_ID) == 40 and lf.state[FLAG_ID] == "on")
    return bad


# ===================================================================================================================
print("[1] the helper: user-editable, restored by Home Assistant")
# ===================================================================================================================
core = load(CORE_PKG)
helper = (core.get("input_number") or {}).get(RESERVE) or {}
check("the core package defines the reserve helper with the range 0-80, step 1, box input",
      helper.get("min") == 0 and helper.get("max") == 80 and helper.get("step") == 1 and helper.get("mode") == "box"
      and helper.get("unit_of_measurement") == "%", str(helper))
check("the helper has NO `initial` (an `initial` would overwrite the user's value at every Home Assistant start)",
      "initial" not in helper)
packages = {p.name: load(p) for p in sorted(PKG_DIR.glob("*.yaml"))}
defined_in = [n for n, d in packages.items() if RESERVE in ((d or {}).get("input_number") or {})]
check("the helper is defined exactly once across the Home Assistant packages", defined_in == ["ecco_pro.yaml"], str(defined_in))
flag = (core.get("input_boolean") or {}).get(FLAG)
check("the first-run flag is a plain input_boolean without `initial`, so Home Assistant restores it too",
      isinstance(flag, dict) and "initial" not in flag, str(flag))

# ===================================================================================================================
print("[2] the one-time first-run automation")
# ===================================================================================================================
auto = first_run_automation(core)
triggers = as_list(auto.get("triggers"))
check("the first-run automation exists once and fires only on the Home Assistant start event",
      bool(auto) and len(triggers) == 1 and triggers[0].get("trigger") == "homeassistant" and triggers[0].get("event") == "start")
check("it is gated on the flag being off", as_list(auto.get("conditions")) == [{"condition": "state", "entity_id": FLAG_ID, "state": "off"}])
actions = as_list(auto.get("actions"))
res = reserve_actions(core)
check("it starts the reserve at 40 (one action, the helper by literal entity id)",
      len(res) == 1 and res[0].get("data") == {"value": 40}, str(res))
last_on = [i for i, a in enumerate(actions) if a.get("action") == "input_boolean.turn_on"
           and FLAG_ID in as_list((a.get("target") or {}).get("entity_id"))]
check("it turns the flag on in the same run, so it never runs again", len(last_on) == 1)
out_of_range = []
for a in actions:
    if a.get("action") == "input_number.set_value":
        eid = as_list((a.get("target") or {}).get("entity_id"))[0]
        cfg = core["input_number"][eid.split(".", 1)[1]]
        if not float(cfg["min"]) <= float(a["data"]["value"]) <= float(cfg["max"]):
            out_of_range.append(f"{eid}={a['data']['value']}")
check("every value it sets is inside its helper's range (else the run would end before the flag is set)", not out_of_range, str(out_of_range))

# ===================================================================================================================
print("[3] installation scenarios against the real package")
# ===================================================================================================================
failed = scenarios(core)
check("every first-installation, existing-setting, restart-persistence and user-change scenario holds", not failed, str(failed))
fresh = Instance(core)
check("a new installation starts at 40 and the first run completes", fresh.num(RESERVE_ID) == 40 and not fresh.aborted and fresh.state[FLAG_ID] == "on")
check("the same installation, restarted, keeps 40 and does not re-run the defaults", fresh.restart().num(RESERVE_ID) == 40)
before_user = Instance(core)
before_user.user_set(RESERVE_ID, 25)
check("a user lowering the reserve to 25 keeps 25 after two restarts (the shipped 40 is not re-applied)",
      before_user.restart().restart().num(RESERVE_ID) == 25)

# ===================================================================================================================
print("[4] nothing but the first-run automation writes the reserve")
# ===================================================================================================================
WRITE_SERVICES = ("input_number.set_value", "input_number.increment", "input_number.decrement")


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def collect_variables(node) -> dict[str, list[str]]:
    """Every string-valued `variables:` entry anywhere under one automation / script, by name."""
    out: dict[str, list[str]] = {}

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("variables"), dict):
                for k, v in n["variables"].items():
                    if isinstance(v, str):
                        out.setdefault(str(k), []).append(v)
            for x in n.values():
                walk(x)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(node)
    return out


def entity_targets(call: dict, varmap: dict[str, list[str]]) -> list[str]:
    """The entity ids a service call addresses: target, entity_id, data.entity_id (values such as data.value are not entities).
    A bare `{{ name }}` is resolved through the `variables:` of the same automation / script; an unknown name stays dynamic."""
    data = call.get("data")
    out: list[str] = []
    for s in strings([call.get("target"), call.get("entity_id"), data.get("entity_id") if isinstance(data, dict) else None]):
        m = re.fullmatch(r"\{\{\s*(\w+)\s*\}\}", s.strip())
        out.extend(varmap[m.group(1)] if m and m.group(1) in varmap else [s])
    return out


def could_be_reserve(entity: str) -> bool:
    """True if `entity` is the reserve, or a template whose literal prefix could still resolve to it (an empty prefix always could)."""
    if RESERVE_ID in entity:
        return True
    if "{{" in entity or "{%" in entity:
        prefix = re.split(r"\{[{%]", entity, maxsplit=1)[0].strip()
        return RESERVE_ID.startswith(prefix)
    return False


def _calls(node, label: str, varmap: dict[str, list[str]]):
    if isinstance(node, dict):
        name = node.get("action", node.get("service"))
        if isinstance(name, str) and name in WRITE_SERVICES:
            yield label, entity_targets(node, varmap)
        for v in node.values():
            yield from _calls(v, label, varmap)
    elif isinstance(node, list):
        for v in node:
            yield from _calls(v, label, varmap)


def writers(doc):
    """Yield (label, entity targets) for every input_number write service call in a parsed package: each automation (label = its
    id), each script (label = its key) and every other top-level section (label = its key)."""
    for auto in as_list(doc.get("automation")):
        yield from _calls(auto, str(auto.get("id") or auto.get("alias")), collect_variables(auto))
    for key, script in (doc.get("script") or {}).items():
        yield from _calls(script, str(key), collect_variables(script))
    for key, section in doc.items():
        if key not in ("automation", "script"):
            yield from _calls(section, str(key), collect_variables(section))


found: list[tuple[str, str]] = []
dynamic: list[str] = []
for fname, doc in packages.items():
    for label, targets in writers(doc):
        for t in targets:
            if RESERVE_ID in t:
                found.append((fname, label))
            elif could_be_reserve(t):
                dynamic.append(f"{fname}:{label}:{t.strip()[:50]}")
check("no input_number write uses a templated entity id that could resolve to the reserve (so the scan below is sound)", not dynamic, str(dynamic))
check("exactly one writer of the reserve exists: the first-run automation", found == [("ecco_pro.yaml", AUTOMATION_ID)], str(found))

WRITE_NEAR = re.compile(r"callService|perform-action|call-service|action:\s*input_number\.|service:\s*input_number\.")
SCAN_DIRS = [ROOT / "home-assistant" / "dashboards", ROOT / "home-assistant" / "prototypes"] + sorted((ROOT / "frontend").glob("*/src"))
offenders = []
for d in SCAN_DIRS:
    for f in sorted(p for p in d.rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml", ".ts", ".js")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(re.escape(RESERVE), text):
            window = text[max(0, m.start() - 300):m.end() + 300]
            if WRITE_NEAR.search(window) and re.search(r"set_value|increment|decrement", window):
                offenders.append(f"{f.relative_to(ROOT).as_posix()}@{m.start()}")
check("no dashboard, prototype or card source calls a write service on the reserve", not offenders, str(offenders[:5]))

# ===================================================================================================================
print("[5] runtime: the selected value is used, 40 is never a hard-coded limit")
# ===================================================================================================================
STANDALONE_40 = re.compile(r"(?<![\d.])40(?![\d.])")
JINJA_SET = re.compile(r"\{%-?\s*set\s+(\w+)\s*=\s*(.*?)\s*-?%\}", re.S)
JINJA_EXPR = re.compile(r"\{\{-?\s*(.*?)\s*-?\}\}", re.S)
READS_RESERVE = (RESERVE, MIRROR_ID.split(".", 1)[1])


def hard_coded_reserve_40(text: str) -> list[str]:
    """Places in one template string where the reserve is ASSIGNED or READ through a literal 40 percent: a `set` of a reserve variable
    (or of anything read from the helper) with a 40 in its right-hand side, or an expression that reads the helper and contains a 40
    (a fallback such as float(40)). A 40 elsewhere in the same template (a 40 W threshold, say) is not a reserve and is not flagged."""
    out = []
    for m in JINJA_SET.finditer(text):
        name, rhs = m.group(1), m.group(2)
        if ("reserve" in name.lower() or any(r in rhs for r in READS_RESERVE)) and STANDALONE_40.search(rhs):
            out.append(f"set {name} = {rhs.strip()[:60]}")
    for m in JINJA_EXPR.finditer(text):
        if any(r in m.group(1) for r in READS_RESERVE) and STANDALONE_40.search(m.group(1)):
            out.append(f"{{{{ {m.group(1).strip()[:60]} }}}}")
    return out


hard = [f"{fname}: {h}" for fname, doc in packages.items() for s in strings(doc) for h in hard_coded_reserve_40(s)]
check("no package template assigns the reserve, or reads the helper with a fallback, through a literal 40", not hard, str(hard))
check("the scan flags a reserve variable set to 40, a 40 fallback on the helper and on the mirror, and a 40 assigned from the helper",
      all(hard_coded_reserve_40(s) for s in (
          "{% set reserve = 40 %}",
          "{%- set reserve_pct = states('input_number.ecco_minimum_reserve_soc') | float(40) -%}",
          "{{ states('sensor.ecco_config_minimum_reserve_soc') | float(40) }}",
          "{% set floor = (states('input_number.ecco_minimum_reserve_soc') | float(0)) + 40 %}")))
check("the scan does not flag an unrelated 40 (a 40 W threshold or divisor guard) in a template that also reads the reserve",
      not hard_coded_reserve_40("{%- set reserve = states('input_number.ecco_minimum_reserve_soc') | float(0) -%}"
                                "{%- if usage >= 60 or (ns.direction == 'discharging' and usage >= 40) -%}x{%- endif -%}"
                                "{%- set raw = (soc - reserve) * wh / ([dis, 40] | max) * 60 -%}{{ raw }}"))

fw_refs = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "firmware").rglob("*"))
           if p.is_file() and p.suffix in (".yaml", ".yml", ".h", ".cpp", ".c") and RESERVE in p.read_text(encoding="utf-8", errors="replace")]
check("the firmware does not reference the helper (it cannot read Home Assistant state), so it cannot enforce or hard-code it", not fw_refs, str(fw_refs))

runtime = load(RUNTIME_PKG)
mirror = None
for block in as_list(runtime.get("template")):
    for s in as_list(block.get("sensor")):
        if s.get("unique_id") == "ecco_config_minimum_reserve_soc":
            mirror = s
check("the configuration mirror sensor exists once", mirror is not None)
env = jinja2.Environment()


def render(template: str, states: dict[str, str]) -> str:
    return env.from_string(template).render(states=lambda eid: states.get(eid, "unknown")).strip()


if mirror:
    ok_values = True
    for h in ("0", "15", "25", "40", "55", "80"):
        ok_values &= render(mirror["state"], {RESERVE_ID: h}) in (h, f"{float(h)}") and render(mirror["availability"], {RESERVE_ID: h}) == "True"
    check("the mirror sensor passes whatever value the user selected straight through (0 to 80)", ok_values)
    check("the mirror sensor is unavailable while the helper is unknown or unavailable",
          all(render(mirror["availability"], {RESERVE_ID: s}) == "False" for s in ("unknown", "unavailable")))

from intelligence.config import DEFAULT_USER_RESERVE_SOC_PCT, DEFAULT_TECHNICAL_MIN_SOC_PCT, SiteConfig  # noqa: E402

check("Intelligence's default user reserve agrees with the starting value, so a new installation is coherent end to end",
      DEFAULT_USER_RESERVE_SOC_PCT == FIRST_RUN_VALUE, str(DEFAULT_USER_RESERVE_SOC_PCT))
follows = True
for u in (0.0, 25.0, 40.0, 60.0):
    cfg = SiteConfig(user_reserve_soc_pct=u)
    follows &= cfg.effective_min_soc_pct() == max(u, DEFAULT_TECHNICAL_MIN_SOC_PCT)
    for h in (0.0, 15.0, 55.0, 80.0):
        follows &= cfg.effective_min_soc_pct(h) == max(u, DEFAULT_TECHNICAL_MIN_SOC_PCT, h)
check("Intelligence's effective reserve follows the configured user reserve and a run-time helper value, with no fixed 40", follows)
cfg_default = SiteConfig()
check("Intelligence ignores an unusable helper value (none, NaN, infinite, text, a bool) and a low or negative one never lowers its reserve",
      all(cfg_default.effective_reserve(x).effective_pct == 40.0 and cfg_default.effective_reserve(x).binding == "user_reserve"
          for x in (None, float("nan"), float("inf"), float("-inf"), "40", True, -5.0, 0.0, 15.0)))
check("Intelligence lets a helper value of 55 or 80 raise its reserve and caps one above 100 at 100",
      cfg_default.effective_reserve(55.0).effective_pct == 55.0 and cfg_default.effective_reserve(80.0).effective_pct == 80.0
      and cfg_default.effective_reserve(150.0).effective_pct == 100.0)

BR_PKG = PKG_DIR / "ecco_battery_runtime.yaml"
br_text = BR_PKG.read_text(encoding="utf-8") if BR_PKG.is_file() else ""
check("the battery time-to-reserve package (FE-1) reads the reserve from the helper by entity id, assigns it no number of its own and "
      "treats an unusable value as unavailable (its own suite covers the values)",
      f"{{%- set e_reserve = '{RESERVE_ID}' -%}}" in br_text and "{%- set reserve = states(e_reserve) | float(none) -%}" in br_text
      and "reserve_unavailable" in br_text)

safety =" ".join((ROOT / "SAFETY.md").read_text(encoding="utf-8").split())
check("SAFETY.md calls 40 % a starting value, says Home Assistant keeps the user's value across restarts and updates, and no longer says 15 %",
      "starting value of 40%" in safety and "across restarts and updates" in safety and not re.search(r"sets it to 15 ?%", safety))

# ===================================================================================================================
print("[6] Dump-to-Grid's own Stop SOC stays independent of the reserve")
# ===================================================================================================================
FIRMWARE_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
DUMP_PKG_TEXT = (PKG_DIR / "ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
FW_STOP_GATES = (("id(ecco_battery_soc).state > id(dump_stop_soc).state", 1), ("id(dump_stop_soc).state >= 10.0f", 2),
                 ("id(dump_stop_soc).state <= 90.0f", 2), ('"STOP SOC REACHED"', 1),
                 ("id(ecco_battery_soc).state <= (float) id(dump_target_stop_soc)", 1))


def dump_stop_problems(fw: str, pkg_text: str, helpers: dict) -> list[str]:
    """What must stay true for Dump-to-Grid's own Stop SOC (a per-transaction setting of 10-90 %, default 25 %, enforced against the
    battery SOC by the firmware): [] when it does. The reserve never feeds it."""
    out: list[str] = []
    i = fw.find("id: dump_stop_soc")
    blk = fw[fw.rfind("  - platform: template", 0, i):fw.find("\n  - platform:", i)] if i >= 0 else ""
    for s in ("optimistic: true", "restore_value: true", "initial_value: 25", "min_value: 10", "max_value: 90", "step: 1"):
        if s not in blk:
            out.append(f"the firmware Stop SOC number lacks {s!r}")
    for needle, n in FW_STOP_GATES:
        if fw.count(needle) != n:
            out.append(f"the firmware Stop SOC gate {needle!r} is not present {n}x")
    sched = helpers.get("ecco_dump_to_grid_schedule_stop_soc") or {}
    if not (sched.get("min") == 10 and sched.get("max") == 90):
        out.append("the scheduler's Stop SOC helper is not 10-90 %")
    if pkg_text.count("outside safe range 10-90%") != 2:
        out.append("the scheduler does not keep both 10-90 % Stop SOC bounds")
    if "number.ecco_clock_dongle_dump_to_grid_stop_soc" not in pkg_text:
        out.append("the scheduler no longer sets the firmware Stop SOC number")
    for what, text in (("the firmware", fw), ("the Dump-to-Grid scheduler package", pkg_text)):
        if any(r in text for r in READS_RESERVE):
            out.append(f"{what} references the reserve")
    return out


DUMP_HELPERS = packages["ecco_dump_to_grid_schedule.yaml"].get("input_number") or {}
check("Dump-to-Grid keeps its own Stop SOC, unchanged and independent of the reserve: firmware number (restored, default 25 %, 10-90 %), "
      "its start / end gates, the scheduler's 10-90 % helper and bounds, and no reference to the reserve",
      not dump_stop_problems(FIRMWARE_TEXT, DUMP_PKG_TEXT, DUMP_HELPERS), str(dump_stop_problems(FIRMWARE_TEXT, DUMP_PKG_TEXT, DUMP_HELPERS)))
DUMP_MUTANTS = (
    ("the firmware Stop SOC default raised to 40", lambda fw, pk, h: (fw.replace("initial_value: 25\n    min_value: 10", "initial_value: 40\n    min_value: 10"), pk, h)),
    ("the firmware Stop SOC floor raised to 40", lambda fw, pk, h: (fw.replace("min_value: 10\n    max_value: 90\n    step: 1\n    unit_of_measurement: \"%\"\n    icon: \"mdi:battery-arrow-down\"",
                                                                              "min_value: 40\n    max_value: 90\n    step: 1\n    unit_of_measurement: \"%\"\n    icon: \"mdi:battery-arrow-down\""), pk, h)),
    ("the firmware start gate no longer compares with the Stop SOC", lambda fw, pk, h: (fw.replace("id(ecco_battery_soc).state > id(dump_stop_soc).state", "true"), pk, h)),
    ("the firmware ends the transaction at the reserve", lambda fw, pk, h: (fw + "\n# stop at " + RESERVE + "\n", pk, h)),
    ("the scheduler reads the reserve", lambda fw, pk, h: (fw, pk + "\n# " + RESERVE_ID + "\n", h)),
    ("the scheduler's Stop SOC helper floor raised to 40", lambda fw, pk, h: (fw, pk, {**h, "ecco_dump_to_grid_schedule_stop_soc": {**h["ecco_dump_to_grid_schedule_stop_soc"], "min": 40}})),
    ("the scheduler loses a 10-90 % bound", lambda fw, pk, h: (fw, pk.replace("outside safe range 10-90%", "outside range", 1), h)),
)
for dname, dfn in DUMP_MUTANTS:
    mutated = dfn(FIRMWARE_TEXT, DUMP_PKG_TEXT, DUMP_HELPERS)
    check(f"mutant caught: {dname}", bool(dump_stop_problems(*mutated)) and mutated != (FIRMWARE_TEXT, DUMP_PKG_TEXT, DUMP_HELPERS))

# ===================================================================================================================
print("[7] mutation: the wrong package is caught")
# ===================================================================================================================


def mutate(fn):
    m = copy.deepcopy(core)
    fn(m)
    return m


def add_initial(m):
    m["input_number"][RESERVE]["initial"] = 40


def drop_gate(m):
    first_run_automation(m)["conditions"] = []


def drop_flag_on(m):
    a = first_run_automation(m)
    a["actions"] = [x for x in a["actions"] if not (x.get("action") == "input_boolean.turn_on" and FLAG_ID in as_list(x["target"]["entity_id"]))]
    a["actions"].append({"action": "input_boolean.turn_off", "target": {"entity_id": ["input_boolean.ecco_grid_charging_enabled"]}})


def flag_initial_on(m):
    m["input_boolean"][FLAG]["initial"] = True


def second_writer(m):
    m["automation"].append({"id": "rogue", "triggers": [{"trigger": "homeassistant", "event": "start"}], "conditions": [],
                            "actions": [{"action": "input_number.set_value", "target": {"entity_id": RESERVE_ID}, "data": {"value": 40}}]})


def second_writer_templated(m):
    m["automation"].append({"id": "rogue", "triggers": [{"trigger": "time_pattern", "minutes": "/5"}],
                            "actions": [{"action": "input_number.set_value", "target": {"entity_id": "{{ 'input_number.' ~ x }}"}, "data": {"value": 40}}]})


def second_writer_via_variable(m):
    m["automation"].append({"id": "rogue", "triggers": [{"trigger": "time_pattern", "minutes": "/5"}],
                            "actions": [{"variables": {"t": RESERVE_ID}},
                                        {"action": "input_number.set_value", "target": {"entity_id": "{{ t }}"}, "data": {"value": 40}}]})


MUTANTS = [
    ("the old first-run 15", lambda m: [a["data"].update(value=15) for a in reserve_actions(m)]),
    ("an `initial` on the helper", add_initial),
    ("the gate removed (defaults re-applied at every start)", drop_gate),
    ("the flag never turned on", drop_flag_on),
    ("a first-run value outside the helper's range", lambda m: [a["data"].update(value=90) for a in reserve_actions(m)]),
    ("an `initial: on` flag (the defaults never run)", flag_initial_on),
]
killed = 0
for name, fn in MUTANTS:
    dead = bool(scenarios(mutate(fn)))
    killed += dead
    check(f"mutant caught by the scenarios: {name}", dead)
rogue_hits = {lbl for lbl, tg in writers(mutate(second_writer)) if any(RESERVE_ID in t for t in tg)}
check("mutant caught by the writer scan: a second automation that sets the reserve", rogue_hits == {AUTOMATION_ID, "rogue"}, str(rogue_hits))
check("mutant caught by the writer scan: a writer whose `{{ variable }}` target resolves to the reserve through the automation's variables",
      {lbl for lbl, tg in writers(mutate(second_writer_via_variable)) if any(RESERVE_ID in t for t in tg)} == {AUTOMATION_ID, "rogue"})
check("the existing manual-TOU sync writers resolve through their variables to the manual-slot helpers (none can be the reserve)",
      not [1 for d in packages.values() for _l, tg in writers(d) if any(RESERVE_ID not in t and could_be_reserve(t) for t in tg)])
check("mutant caught by the soundness rule: a fully dynamic entity id on an input_number write",
      any(could_be_reserve(t) for _l, tg in writers(mutate(second_writer_templated)) for t in tg))
check("mutant caught by the soundness rule: a template whose literal prefix could resolve to the reserve",
      could_be_reserve("input_number.ecco_minimum_{{ x }}"))
check("the soundness rule lets the existing manual-slot helpers through (their prefix cannot resolve to the reserve)",
      not could_be_reserve("input_number.ecco_manual_slot_{{ n }}_power_staged"))
check("a rogue second writer also breaks the scenarios (it re-applies 40 over a user's value at every start)",
      bool(scenarios(mutate(second_writer))))
control = mutate(lambda m: first_run_automation(m).update(alias="renamed"))
check("control: a harmless change (the alias) is not flagged", not scenarios(control))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All reserve-default offline tests PASSED.")
print("NOTE: a model of Home Assistant start-up and restore against the real package; not proven on a live Home Assistant instance.")
