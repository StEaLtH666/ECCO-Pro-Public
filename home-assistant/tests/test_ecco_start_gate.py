"""Offline suite for the shared START GATE, the GUARDED FREE POWER START and the IN-LEASE END GUARDS:

  home-assistant/packages/ecco_start_gate.yaml    two template binary sensors (binary_sensor.ecco_charge_start_allowed, binary_sensor.ecco_export_start_allowed),
                                                  one helper (the grid-import ceiling, no initial value) and script.ecco_free_power_start_guarded
  home-assistant/packages/ecco_lease_guards.yaml  three automations that only ever press an existing END button (Dump to Grid; Free Power time trust; Free Power import ceiling)

Item N2 of the architecture reconciliation: ONE start gate for both functions built only from facts ECCO already has (time trust, telemetry, no open recovery obligation, the other
function not running, the Stage 3 facts for Export, an import headroom check for Charge that is DISABLED until the owner supplies a ceiling), a guarded Free Power start bound to it,
and guards that end a lease whose plan, time or supply no longer allows it. The HA gates are SOFT: the dongle's own Start button bypasses them until a firmware gate exists. This
suite proves the REAL package YAML against a model of Home Assistant and the dongle (home-assistant/tests/_start_gate_sim.py, on the repository's FPS1 interpreter, the template model
of the time trust suite and the Free Power model of the schedule suites); nothing was installed, nothing was written live, nothing here binds the dongle's own Start button.

  [0] static      the files load with no repeated key; the entities, helper, script and automations they define and nothing else; every entity they read exists in the repository; the
                  write vocabulary is pinned (the only services, each aimed at its one entity); the state, `reasons` and `blocked_by` templates share ONE rule block; the guards press only
                  the two END buttons and have no restart, reload or start trigger; the headers state the rules and the limits; ASCII, LF, no site value; the site renderer; the firmware
                  and card facts the headers rely on; the manifest, README and CHANGELOG say the same
  [1] gate        every input one at a time (off, unavailable, unknown, missing and the other odd values), each blocking cause named once with its entity; the boundaries of the poll
                  freshness; the Stage 3 cases (hold, reserve, Stop SOC, revision); the import ceiling (not configured by every spelling, then configured: the boundary, a breach, an
                  unreadable import or request, an invalid ceiling); both gates against an independent model over every single deviation and a seeded random sample; the state, `reasons` and
                  `blocked_by` always agree; the real plan helper package feeding the gate
  [2] start       the guarded Free Power start: refusals (nothing staged, armed or pressed; one notification; the stable code), the allowed path (exactly the calls the scheduled start and the
                  card make: the two request numbers, the arm, the one start button), explicit and staged requests, the press-time recheck, the answers of the dongle (refused, failed, no
                  answer), a second start, the equality with the scheduled start's staging, and a write enable that always ends off
  [3] guards      the Dump guard (a hold turns on, the reserve rises above the latched Stop SOC, a lease that starts under a violation), the Free Power time guard (5 minutes) and the
                  import guard (30 seconds): each fires only on its condition and at its delay, presses only its END button, never on unreadable data, once per violation
  [4] restart     a Home Assistant restart, a template reload, a reconnect of the dongle and a boot, with violations standing, press nothing and raise nothing
  [5] vocabulary  every service call every world above made is one of the allowed (service, entity) pairs, and each of them was made; no other button was ever pressed
  [6] mutation    in-memory mutants of both packages, each caught

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import random
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _ha_script_sim as S  # noqa: E402
import _start_gate_sim as G  # noqa: E402

PKGS = ROOT / "home-assistant" / "packages"
GATE_REL = "home-assistant/packages/ecco_start_gate.yaml"
GUARDS_REL = "home-assistant/packages/ecco_lease_guards.yaml"
GATE_TEXT = (ROOT / GATE_REL).read_text(encoding="utf-8")
GUARDS_TEXT = (ROOT / GUARDS_REL).read_text(encoding="utf-8")
GATE_RAW = (ROOT / GATE_REL).read_bytes()
GUARDS_RAW = (ROOT / GUARDS_REL).read_bytes()
PLAN_TEXT = (PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8")
FREE_TEXT = (PKGS / "ecco_free_power_schedule.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
CARD_TEXT = (ROOT / "frontend" / "ecco-energy-actions-card" / "src" / "ecco-energy-actions-card.ts").read_text(encoding="utf-8")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class _Stop(Exception):
    pass


class Problems(list):
    """The problems a battery finds. In first_only mode the first one stops the battery (a mutant is dead as soon as one check says so)."""

    def __init__(self, first_only: bool = False):
        super().__init__()
        self.first_only = first_only

    def add(self, msg: str) -> None:
        self.append(msg)
        if self.first_only:
            raise _Stop()


# ===========================================================================================================================
# names
# ===========================================================================================================================
DONGLE = "ecco_clock_dongle"
FMT = "%Y-%m-%d %H:%M:%S"
ZONE = ZoneInfo(G.ZONE)
BAD = ("unknown", "unavailable", "none", "")
COMMON_CODES = ["TIME_LEASES", "TIME_SCHEDULES", "TELEMETRY_OFFLINE", "CONFIGURATION_OFFLINE", "TELEMETRY_STALE", "FREE_POWER_ACTIVE", "FREE_POWER_OPERATION", "FREE_POWER_SNAPSHOT",
                "DUMP_ACTIVE", "DUMP_OPERATION", "DUMP_SNAPSHOT", "MANUAL_WRITE"]
EXPORT_CODES = ["OVERRIDE_ACTIVE", "OVERRIDE_UNREADABLE", "RESERVE_INVALID", "RESERVE_UNKNOWN", "STOP_SOC_UNREADABLE", "STOP_SOC_BELOW_RESERVE", "REVISION_UNREADABLE"]
CHARGE_CODES = ["IMPORT_CEILING_INVALID", "IMPORT_UNREADABLE", "REQUEST_UNREADABLE", "IMPORT_HEADROOM"]
FACT_ENT = {"tl": G.TL, "ts": G.TS, "tel": G.TEL, "cfg": G.CFG, "poll": G.POLL, "fp_active": G.FP_ACTIVE, "fp_op": G.FP_OP, "fp_snap": G.FP_SNAP, "dg_active": G.DG_ACTIVE,
            "dg_op": G.DG_OP, "dg_snap": G.DG_SNAP, "manual": G.MANUAL, "hold": G.HOLD, "eff": G.EFF, "stop": G.STOP, "rev": G.REV, "ceil": G.CEIL, "grid": G.GRID, "req": G.REQ}
BUSY = [("fp_active", "FREE_POWER_ACTIVE"), ("fp_op", "FREE_POWER_OPERATION"), ("fp_snap", "FREE_POWER_SNAPSHOT"), ("dg_active", "DUMP_ACTIVE"), ("dg_op", "DUMP_OPERATION"),
        ("dg_snap", "DUMP_SNAPSHOT"), ("manual", "MANUAL_WRITE")]
HEALTHY_F = {"tl": "on", "ts": "on", "tel": "on", "cfg": "on", "poll": ("age", 0), "fp_active": "off", "fp_op": "off", "fp_snap": "off", "dg_active": "off", "dg_op": "off",
             "dg_snap": "off", "manual": "off", "hold": "clear", "eff": "40", "stop": "40.0", "rev": "12.0", "ceil": "0.0", "grid": "1500.0", "req": "4000.0"}
CODE_ENTITY = {"TIME_LEASES": G.TL, "TIME_SCHEDULES": G.TS, "TELEMETRY_OFFLINE": G.TEL, "CONFIGURATION_OFFLINE": G.CFG, "TELEMETRY_STALE": G.POLL, "FREE_POWER_ACTIVE": G.FP_ACTIVE,
               "FREE_POWER_OPERATION": G.FP_OP, "FREE_POWER_SNAPSHOT": G.FP_SNAP, "DUMP_ACTIVE": G.DG_ACTIVE, "DUMP_OPERATION": G.DG_OP, "DUMP_SNAPSHOT": G.DG_SNAP, "MANUAL_WRITE": G.MANUAL,
               "OVERRIDE_ACTIVE": G.HOLD, "OVERRIDE_UNREADABLE": G.HOLD, "RESERVE_INVALID": G.EFF, "RESERVE_UNKNOWN": G.EFF, "STOP_SOC_UNREADABLE": G.STOP, "STOP_SOC_BELOW_RESERVE": "Stop SOC",
               "REVISION_UNREADABLE": G.REV, "IMPORT_CEILING_INVALID": G.CEIL, "IMPORT_UNREADABLE": G.GRID, "REQUEST_UNREADABLE": G.REQ, "IMPORT_HEADROOM": "grid-import ceiling"}

ALLOWED_SERVICES = {
    ("input_text.set_value", G.LAST), ("persistent_notification.create", ""), ("persistent_notification.dismiss", ""), ("number.set_value", G.REQ), ("number.set_value", G.DUR),
    ("switch.turn_on", G.ARM), ("switch.turn_off", G.ARM), ("button.press", G.START_FP), ("button.press", G.END_DUMP), ("button.press", G.END_FP),
}
SEEN: set = set()          # every (service, entity) any world below made
BUTTONS: set = set()       # every button any world below saw pressed


def harvest(gw: "G.GateWorld") -> None:
    if getattr(gw, "foreign", False):          # a world that runs another package's scripts (the plan helpers, the schedule): their calls are theirs
        return
    SEEN.update((s, e) for _t, s, e, _d in gw.w.service_log)
    BUTTONS.update(e for _t, e in gw.d.button_log)


# ===========================================================================================================================
# [0] static
# ===========================================================================================================================
class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)
UniqueKeyLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


class FwLoader(yaml.SafeLoader):
    pass


FwLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def firmware_ids() -> set:
    d = yaml.load(FW_TEXT, Loader=FwLoader)
    out = set()
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor"), ("switch", "switch"), ("number", "number"), ("button", "button"),
                         ("select", "select")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                out.add(f"{domain}.{DONGLE}_{slug(e['name'])}")
    return out


def package_ids(path: Path) -> set:
    d = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}
    out = set()
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in d.get(dom) or {}:
            out.add(f"{dom}.{k}")
    for block in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                if isinstance(it, dict) and it.get("name"):
                    out.add(f"{kind}.{slug(it['name'])}")
    return out


def walk_actions(node, found: list) -> list:
    """Every dict with an `action` key, anywhere under `node`."""
    if isinstance(node, dict):
        if isinstance(node.get("action"), str):
            found.append(node)
        for v in node.values():
            walk_actions(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_actions(v, found)
    return found


def service_pairs(node) -> set:
    out = set()
    for a in walk_actions(node, []):
        tgt = (a.get("target") or {}).get("entity_id")
        if isinstance(tgt, list):
            tgt = ",".join(tgt)
        out.add((a["action"], tgt or ""))
    return out


ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_text|input_number|input_boolean|input_datetime|number|script|button|switch|select|automation)\.[a-z0-9_]+")
OTHER_PKGS = {p.name: p for p in sorted(PKGS.glob("*.yaml")) if p.name not in ("ecco_start_gate.yaml", "ecco_lease_guards.yaml")}
FW_IDS = firmware_ids()
REPO_IDS = set(FW_IDS)
for _p in OTHER_PKGS.values():
    REPO_IDS |= package_ids(_p)

GATE_OWN = {G.CHARGE_GATE, G.EXPORT_GATE, G.CEIL, "script.ecco_free_power_start_guarded"}
GATE_READS = {G.TL, G.TS, G.TEL, G.CFG, G.POLL, G.FP_ACTIVE, G.FP_OP, G.FP_SNAP, G.DG_ACTIVE, G.DG_OP, G.DG_SNAP, G.MANUAL, G.HOLD, G.EFF, G.STOP, G.REV, G.GRID, G.REQ, G.DUR, G.ARM,
              G.START_FP, G.STATUS, G.LIMIT, G.SCHED, G.LAST}
GUARDS_READS = {G.HOLD, G.EFF, G.DG_ACTIVE, G.LATCHED, G.END_DUMP, G.FP_ACTIVE, G.TL, G.END_FP, G.CEIL, G.GRID}
SCRIPT_SERVICES = ALLOWED_SERVICES - {("button.press", G.END_DUMP), ("button.press", G.END_FP)}
GUARD_SERVICES = {"ecco_lease_guard_dump_end": {("button.press", G.END_DUMP), ("persistent_notification.create", "")},
                  "ecco_lease_guard_free_power_time": {("button.press", G.END_FP), ("persistent_notification.create", "")},
                  "ecco_lease_guard_free_power_import": {("button.press", G.END_FP), ("persistent_notification.create", "")}}
GUARD_TRIGGERS = {"ecco_lease_guard_dump_end": [("state", G.HOLD, "held", "hold"), ("state", G.EFF, None, "reserve"), ("state", G.DG_ACTIVE, "on", "lease_started")],
                  "ecco_lease_guard_free_power_time": [("state", G.TL, "off", "trust_lost"), ("state", G.FP_ACTIVE, "on", "lease_started")],
                  "ecco_lease_guard_free_power_import": [("template", None, "-", "import_breach")]}
RULE_END = re.compile(r"\{\{(?:(?!\{\{).)*\}\}\s*$", re.S)


def rules_of(tpl: str) -> str:
    """A gate template without its final output expression: the rule block the state, `reasons` and `blocked_by` templates must share."""
    m = RULE_END.search(tpl)
    return tpl[:m.start()].rstrip() if m else tpl


def privacy_problems(text: str, raw: bytes) -> list[str]:
    bad = []
    if not text.isascii() or b"\r" in raw or "\t" in text or re.search(r"[ ]+$", text, re.M):
        bad.append("not plain ASCII, LF, tab-free and trailing-space-free")
    m = re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|@|https?://|secret|token|password|api_key", text, re.I)
    if m:
        bad.append(f"a site value or secret-like word: {m.group(0)!r}")
    return bad


def noncomment(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))


def entity_text(text: str) -> str:
    """The text without comments and without the `action:` lines (a service name looks like an entity id)."""
    return re.sub(r"(?m)^\s*-?\s*action:.*$", "", noncomment(text))


def head_flat(text: str, marker: str) -> str:
    return re.sub(r"\s*\n#\s*", " ", text.split(marker)[0])


GATE_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "ONE start gate", "THE GATE IS SOFT", "HA GATES ARE SOFT", "can still be pressed from Home Assistant or by an assistant", "a firmware gate binds it",
             "THE CARD IS NOT CHANGED IN THIS STEP", "separate card change", "NO CEILING CONFIGURED", "NOT_CONFIGURED", "does NOT block", "SAFETY ceiling, never a target",
             "request + max(import, 0) > ceiling", "NO charger-loss factor and NO margin is applied", "FAIL SAFE", "never \"not off\" or \"not unavailable\"", "NEW START PATH BOUND TO THE GATE",
             "It adds NO helper", "input_text.ecco_plan_last_result", "does NOT reuse the Free Power schedule's result text", "as a start with no ECCO record",
             "STARTED OK - <n>W for <m> min", "smr1", "replaces the owner's staged request", "Recalled from Home Assistant core, NOT verified on a real Home Assistant", "INSTALL.",
             "reload three things", "No restart", "Never \"reload all\"", "ecco_lease_guards.yaml", "TELEMETRY_STALE", "within 300 s of Home Assistant's clock", "IMPORT_HEADROOM",
             "IMPORT_CEILING_INVALID", "GATE_BLOCKED", "NOT_CONFIRMED", "NO_ANSWER", "START_FAILED", "FIRMWARE_REFUSED", "SCHEDULED_START_RUNNING", "blocked_by", "reasons",
             "Time-zone assumption", "the in-lease guard", "the dongle's own gate refused the press", "Item N2 of the architecture reconciliation")
GUARDS_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "EACH GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "each stands alone", "END is always allowed", "They are SOFT: they run in Home Assistant",
               "5 MINUTES", "30 SECONDS", "waits up to 15 s", "The ONLY service calls are button.press", "never presses a START button",
               "A restart, a template reload, a reconnect of the dongle and a boot never end a lease by themselves", "A guard acts only on a POSITIVE reading",
               "A violation that already stands when Home Assistant starts is NOT acted on until the next change", "one press per violation",
               "Recalled from Home Assistant core, NOT verified on a real Home Assistant", "reload the AUTOMATIONS", "no restart", "never \"reload all\"", "ecco_start_gate.yaml",
               "the exact values, never a computed one", "Charge Battery (Free Power) has no target-reached guard here", "NOT ended by the Free Power guards",
               "the dongle's active Stop SOC", "ecco_lease_guard_dump_end", "ecco_lease_guard_free_power_time", "ecco_lease_guard_free_power_import")


def header_problems(text: str, pins: tuple) -> list[str]:
    head = head_flat(text, "\nautomation:" if "\nautomation:" in text else "\ninput_number:")
    return [f"header lacks {p!r}" for p in pins if p not in head]


def static_problems(gate_text: str, guards_text: str, only: str = "both", pb: "Problems | None" = None) -> list[str]:
    """Everything the two files must be, without running them. `only` is 'gate', 'guards' or 'both'."""
    bad = pb if pb is not None else Problems()
    add = bad.add
    if only in ("gate", "both"):
        try:
            d = yaml.load(gate_text, Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001 - a package that does not load (or repeats a key) is a failed proof
            add(f"gate does not load: {str(exc)[:100]}")
            d = None
        if d is not None:
            if not isinstance(d, dict) or set(d) != {"input_number", "template", "script"}:
                add(f"gate top-level keys {sorted(d) if isinstance(d, dict) else repr(d)[:40]}")
            else:
                inp = d["input_number"]
                if set(inp) != {"ecco_grid_import_ceiling_w"}:
                    add(f"the helpers {sorted(inp)}")
                else:
                    c = inp["ecco_grid_import_ceiling_w"]
                    if "initial" in c:
                        add("the ceiling helper has an initial value")
                    if (c.get("min"), c.get("max"), c.get("step"), c.get("mode"), c.get("unit_of_measurement")) != (0, 100000, 10, "box", "W"):
                        add(f"the ceiling helper's range {c}")
                blocks = d["template"]
                if len(blocks) != 1 or set(blocks[0]) != {"binary_sensor"} or [e.get("name") for e in blocks[0]["binary_sensor"]] != ["ECCO Charge Start Allowed", "ECCO Export Start Allowed"]:
                    add("the template entities are not exactly the two gate binary sensors")
                else:
                    for ent in blocks[0]["binary_sensor"]:
                        if set(ent) != {"name", "unique_id", "icon", "state", "attributes"} or set(ent["attributes"]) != {"reasons", "blocked_by"} or ent["unique_id"] != slug(ent["name"]):
                            add(f"{ent.get('name')}: entity keys {sorted(ent)} / attributes {sorted(ent.get('attributes', {}))}")
                            continue
                        r_state, r_reasons, r_by = rules_of(ent["state"]), rules_of(ent["attributes"]["reasons"]), rules_of(ent["attributes"]["blocked_by"])
                        if not (r_state == r_reasons == r_by) or len(r_state) < 1000:
                            add(f"{ent['name']}: the state, reasons and blocked_by templates do not share ONE rule block")
                        if (not ent["state"].strip().endswith("{{ (ns.c | length) == 0 }}") or not ent["attributes"]["blocked_by"].strip().endswith("{{ ns.c }}")
                                or not ent["attributes"]["reasons"].strip().endswith("{{ (ns.b + ns.n) if (ns.c | length) > 0 else (['ALLOWED: every check passed'] + ns.n) }}")):
                            add(f"{ent['name']}: an output expression")
                scr = d["script"]
                if set(scr) != {"ecco_free_power_start_guarded"}:
                    add(f"scripts {sorted(scr)}")
                else:
                    s = scr["ecco_free_power_start_guarded"]
                    if s.get("mode") != "single" or set(s.get("fields", {})) != {"power_w", "duration_minutes"}:
                        add("the script's mode or fields")
                    pairs = service_pairs(s)
                    if pairs != SCRIPT_SERVICES:
                        add(f"the script's services {sorted(pairs ^ SCRIPT_SERVICES)}")
                    for a in walk_actions(s, []):
                        if "entity_id" in (a.get("data") or {}):
                            add("an action carries entity_id in its data")
                        if a["action"].startswith("persistent_notification") and (a.get("data") or {}).get("notification_id") != "ecco_free_power_start_blocked":
                            add("a notification without the one fixed id")
            nc = noncomment(gate_text)
            mentioned = set(ENTITY_RE.findall(entity_text(gate_text)))
            if mentioned - GATE_OWN != GATE_READS:
                add(f"gate entities read {sorted((mentioned - GATE_OWN) ^ GATE_READS)}")
            if not GATE_READS <= REPO_IDS:
                add(f"not in the repository: {sorted(GATE_READS - REPO_IDS)}")
            for tok in ("esphome", "modbus", "write_register", "automation:", "trigger:", "homeassistant.", "rest_command", "shell_command"):
                if tok in nc:
                    add(f"gate token {tok}")
            for m in re.finditer(r"as_timestamp\(((?:[^()]|\([^()]*\))*)\)", nc):
                if m.group(1).split(",")[0].strip() not in ("now()", "pdt"):
                    add(f"as_timestamp of {m.group(1)!r}: a text is read with strptime only")
            for m in re.finditer(r"strptime\(([^()]*)\)", nc):
                if re.sub(r"\s+", "", m.group(1)) != "pt,'%Y-%m-%d%H:%M:%S',none":
                    add(f"strptime({m.group(1)[:40]})")
            if "ns.c = ns.c + [" not in nc or "refusal.split('|')" not in nc or "'REFUSED '" not in nc:
                add("the rule block or the Dump pattern of the refusal text")
            for p in header_problems(gate_text, GATE_PINS) + privacy_problems(gate_text, gate_text.encode("utf-8")):
                add(p)
    if only in ("guards", "both"):
        try:
            g = yaml.load(guards_text, Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001
            add(f"guards do not load: {str(exc)[:100]}")
            g = None
        if g is not None:
            if not isinstance(g, dict) or set(g) != {"automation"}:
                add(f"guards top-level keys {sorted(g) if isinstance(g, dict) else repr(g)[:40]}")
            else:
                autos = {a["id"]: a for a in g["automation"]}
                if set(autos) != set(GUARD_SERVICES):
                    add(f"guard ids {sorted(autos)}")
                for aid, a in autos.items():
                    if a.get("mode") != "single" or a.get("max_exceeded") != "silent":
                        add(f"{aid}: mode")
                    pairs = service_pairs(a.get("actions"))
                    if pairs != GUARD_SERVICES.get(aid):
                        add(f"{aid}: services {sorted(pairs ^ GUARD_SERVICES.get(aid, set()))}")
                    trg = [(t.get("trigger"), t.get("entity_id"), t.get("to", "-"), t.get("id")) for t in a["triggers"]]
                    if trg != GUARD_TRIGGERS.get(aid):
                        add(f"{aid}: triggers {trg}")
                    for act in walk_actions(a.get("actions"), []):
                        if "entity_id" in (act.get("data") or {}):
                            add(f"{aid}: an action carries entity_id in its data")
                    waits = [x.get("timeout") for x in a["actions"] if "wait_template" in x]
                    delays = [x.get("delay") for x in a["actions"] if "delay" in x]
                    wantw = {"ecco_lease_guard_dump_end": ["00:00:15"], "ecco_lease_guard_free_power_time": ["00:05:00"], "ecco_lease_guard_free_power_import": ["00:00:30"]}.get(aid)
                    if waits != wantw or delays != ["00:01:00"]:
                        add(f"{aid}: waits {waits} delays {delays}")
                    if sum(1 for x in a["actions"] if x.get("action") == "button.press") != 1:
                        add(f"{aid}: not exactly one press")
                dump = autos.get("ecco_lease_guard_dump_end")
                if dump is not None:
                    if "not in ['unavailable', 'unknown']" not in "".join(str(c.get("value_template", "")) for c in dump["conditions"]):
                        add("the Dump guard does not refuse a change from unavailable or unknown")
                tm = autos.get("ecco_lease_guard_free_power_time")
                if tm is not None and "in ['on', 'off']" not in "".join(str(c.get("value_template", "")) for c in tm["conditions"]):
                    add("the time guard does not require a change from a reading")
                imp = autos.get("ecco_lease_guard_free_power_import")
                if imp is not None:
                    pre = [re.search(r"\{%- set breached.*?-%\}", str(x), re.S) for x in (imp["triggers"][0]["value_template"], imp["actions"][0]["wait_template"], imp["actions"][1]["value_template"])]
                    if not all(pre) or len({m.group(0) for m in pre if m}) != 1:
                        add("the import breach expression differs between its three places")
            nc = noncomment(guards_text)
            mentioned = set(ENTITY_RE.findall(entity_text(guards_text)))
            if mentioned != GUARDS_READS:
                add(f"guard entities read {sorted(mentioned ^ GUARDS_READS)}")
            if not GUARDS_READS <= REPO_IDS | GATE_OWN:
                add(f"not in the repository: {sorted(GUARDS_READS - REPO_IDS - GATE_OWN)}")
            for m in re.finditer(r"(?<![A-Za-z0-9_.])(?:switch|number|input_boolean|input_text|script)\.|(?<![A-Za-z0-9_.])(?:esphome|modbus|homeassistant|event_type)(?![A-Za-z0-9_])", entity_text(guards_text)):
                add(f"guard token {m.group(0)}")
            if "button.ecco_clock_dongle_start_" in nc:
                add("a guard names a START button")
            for p in header_problems(guards_text, GUARDS_PINS) + privacy_problems(guards_text, guards_text.encode("utf-8")):
                add(p)
    return bad


# ===========================================================================================================================
# the model of the gate (independent of the templates) and the facts
# ===========================================================================================================================
def st(raw):
    """What states('x') returns for a raw state: a missing entity reads 'unknown'."""
    return "unknown" if raw is None else raw


def flt(raw):
    """The float filter with the default none: a number (nan and inf included) or None."""
    try:
        return float(st(raw).strip())
    except ValueError:
        return None


def oracle(kind: str, f: dict, now_ts: float):
    """(the blocking codes in the gate's own order, whether the NOT_CONFIGURED note is shown) for the facts `f` (raw states; the poll text resolved)."""
    codes = []
    if st(f["tl"]) != "on":
        codes.append("TIME_LEASES")
    if st(f["ts"]) != "on":
        codes.append("TIME_SCHEDULES")
    if st(f["tel"]) != "on":
        codes.append("TELEMETRY_OFFLINE")
    if st(f["cfg"]) != "on":
        codes.append("CONFIGURATION_OFFLINE")
    skew = None
    s = st(f["poll"])
    if s not in BAD:
        try:
            skew = round(now_ts - datetime.strptime(s, FMT).replace(tzinfo=ZONE).timestamp())
        except ValueError:
            skew = None
    if skew is None or abs(skew) > 300:
        codes.append("TELEMETRY_STALE")
    for key, code in BUSY:
        if st(f[key]) != "off":
            codes.append(code)
    note = False
    if kind == "export":
        hold = st(f["hold"])
        if hold == "held":
            codes.append("OVERRIDE_ACTIVE")
        if hold not in ("held", "clear"):
            codes.append("OVERRIDE_UNREADABLE")
        r = flt(f["eff"])
        r = -1.0 if r is None else r
        reserve = r if (r >= 0 and r <= 100) else (-1 if r < 0 else -2)
        if reserve == -2:
            codes.append("RESERVE_INVALID")
        if reserve == -1:
            codes.append("RESERVE_UNKNOWN")
        sv = flt(f["stop"])
        sv = -1.0 if sv is None else sv
        stop = sv if (sv >= 0 and sv <= 100) else -1
        if stop < 0:
            codes.append("STOP_SOC_UNREADABLE")
        if stop >= 0 and reserve >= 0 and stop < reserve:
            codes.append("STOP_SOC_BELOW_RESERVE")
        rv = flt(f["rev"])
        if not (rv is not None and rv == rv and 0 <= rv < 1e9 and rv % 1 == 0):
            codes.append("REVISION_UNREADABLE")
    else:
        cr, cf = st(f["ceil"]), flt(f["ceil"])
        c_unset = cr in BAD or (cf is not None and cf == 0)
        c_ok = cf is not None and cf == cf and 1 <= cf <= 100000
        gi = flt(f["grid"])
        gi_ok = gi is not None and gi == gi and abs(gi) < 1e9
        rq = flt(f["req"])
        rq_ok = rq is not None and rq == rq and 0 < rq < 1e9
        if (not c_unset) and (not c_ok):
            codes.append("IMPORT_CEILING_INVALID")
        if c_ok and not gi_ok:
            codes.append("IMPORT_UNREADABLE")
        if c_ok and not rq_ok:
            codes.append("REQUEST_UNREADABLE")
        if c_ok and gi_ok and rq_ok and rq > cf - max(gi, 0):
            codes.append("IMPORT_HEADROOM")
        note = c_unset
    return codes, note


def apply(gw: "G.GateWorld", f: dict) -> dict:
    """Put every fact into the world (a fact not named is healthy); a value of None removes the entity. Returns the facts with the poll text resolved."""
    full = dict(HEALTHY_F)
    full.update(f)
    for key, eid in FACT_ENT.items():
        v = full[key]
        if key == "poll" and isinstance(v, tuple):
            v = gw.poll_text(v[1])
            full["poll"] = v
        gw.put(eid, v)
    return full


def gate_case(gw: "G.GateWorld", f: dict, label: str, pb: Problems) -> None:
    full = apply(gw, f)
    now_ts = gw.w.t + gw.w.clock_offset
    for kind, eid in (("charge", G.CHARGE_GATE), ("export", G.EXPORT_GATE)):
        codes, note = oracle(kind, full, now_ts)
        state, by, reasons = gw.gate(eid)
        if state != ("off" if codes else "on") or by != codes:
            pb.add(f"{label}: the {kind} gate reads {state} {by}, expected {'off' if codes else 'on'} {codes}")
            continue
        if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) for r in reasons):
            pb.add(f"{label}: the {kind} gate's reasons {reasons!r}")
            continue
        blocking = [r for r in reasons if not r.startswith(("NOTE ", "ALLOWED"))]
        notes = [r for r in reasons if r.startswith("NOTE ")]
        if [r.split(":", 1)[0] for r in blocking] != codes:
            pb.add(f"{label}: the {kind} gate's blocking reasons {[r[:30] for r in blocking]} do not match its blocked_by {codes}")
        for r, code in zip(blocking, codes):
            if not r.startswith(code + ": ") or CODE_ENTITY[code] not in r or "|" in r:
                pb.add(f"{label}: the {kind} reason for {code} does not name its cause: {r[:120]!r}")
        for r, code in zip(blocking, codes):
            key = next((k for k, c in BUSY if c == code), None)
            if key is not None:
                v = st(full[key])
                if (v == "on") != ("reads on: " in r) or (v != "on" and ("so it is not known whether" not in r or f"reads {v}" not in r)):
                    pb.add(f"{label}: the {kind} reason for {code} does not say what the flag reads ({v!r}): {r[:140]!r}")
        if bool(codes) == reasons[0].startswith("ALLOWED: "):
            pb.add(f"{label}: the {kind} gate's first reason {reasons[0][:40]!r} does not say allowed or blocked")
        if len(notes) != (1 if note else 0) or (note and not notes[0].startswith("NOTE IMPORT_NOT_CONFIGURED: ")):
            pb.add(f"{label}: the {kind} gate's notes {[n[:40] for n in notes]}, expected the not-configured note {note}")


# facts one at a time: the values that matter for each (None = the entity does not exist)
ODD = {
    "tl": ["off", "unavailable", "unknown", None, "", "ON", "true", "1"],
    "ts": ["off", "unavailable", "unknown", None, "", "ON", "true", "1"],
    "tel": ["off", "unavailable", "unknown", None, "", "ON", "true"],
    "cfg": ["off", "unavailable", "unknown", None, "", "ON", "true"],
    "poll": [("age", 299), ("age", 300), ("age", 301), ("age", -299), ("age", -300), ("age", -301), ("age", 3600), ("age", 86400), None, "unknown", "unavailable", "", "Waiting for NTP",
             "NTP time invalid", "2026-11-26", "2026-11-26T12:00:00", "12:00:00", "2026-11-26 25:00:00", "garbage", "2026-11-26 12:00:00.5", " 2026-11-26 12:00:00"],
    **{k: ["on", "unavailable", "unknown", None, "", "OFF", "false", "0"] for k in ("fp_active", "fp_op", "fp_snap", "dg_active", "dg_op", "dg_snap", "manual")},
    "hold": ["held", "unknown", "unavailable", None, "", "weird", "CLEAR", "held,skip_tonight"],
    "eff": ["unknown", "unavailable", None, "", "-1", "-0.5", "abc", "nan", "inf", "-inf", "101", "100.5", "0", "100", "40.0", "41", "62.4", "63", "1e9", "NaN"],
    "stop": ["unknown", "unavailable", None, "", "-1", "nan", "101", "abc", "0", "10", "39", "39.9", "40", "41", "100", "90"],
    "rev": ["unknown", "unavailable", None, "", "-1", "1.5", "nan", "inf", "abc", "0", "1000000000", "999999999", "12"],
    "ceil": [None, "unknown", "unavailable", "", "0", "0.0", "-0.0", "5000", "5000.0", "100000", "100001", "-5", "nan", "inf", "abc", "0.5", "1", "1e5", "9999999999"],
    "grid": ["unknown", "unavailable", None, "", "abc", "nan", "inf", "-inf", "-2000", "0", "1e12", "999999999", "8000", "1499", "3500"],
    "req": ["unknown", "unavailable", None, "", "abc", "nan", "inf", "-5", "0", "500", "3500", "3501", "8000", "1e12"],
}
# the same with a ceiling configured (the grid, request and ceiling facts only matter then)
WITH_CEIL = {"ceil": "5000", "grid": "1500.0", "req": "3500.0"}


# the named causes: each fact deviation with the codes BOTH gates must list (charge, export), written out by hand (not from the model above)
NAMED = [
    ({"tl": "off"}, ["TIME_LEASES"], ["TIME_LEASES"]),
    ({"tl": "unavailable"}, ["TIME_LEASES"], ["TIME_LEASES"]),
    ({"tl": None}, ["TIME_LEASES"], ["TIME_LEASES"]),
    ({"ts": "off"}, ["TIME_SCHEDULES"], ["TIME_SCHEDULES"]),
    ({"ts": "unknown"}, ["TIME_SCHEDULES"], ["TIME_SCHEDULES"]),
    ({"tel": "off"}, ["TELEMETRY_OFFLINE"], ["TELEMETRY_OFFLINE"]),
    ({"tel": "unavailable"}, ["TELEMETRY_OFFLINE"], ["TELEMETRY_OFFLINE"]),
    ({"cfg": "off"}, ["CONFIGURATION_OFFLINE"], ["CONFIGURATION_OFFLINE"]),
    ({"cfg": None}, ["CONFIGURATION_OFFLINE"], ["CONFIGURATION_OFFLINE"]),
    ({"poll": ("age", 301)}, ["TELEMETRY_STALE"], ["TELEMETRY_STALE"]),
    ({"poll": None}, ["TELEMETRY_STALE"], ["TELEMETRY_STALE"]),
    ({"poll": "Waiting for NTP"}, ["TELEMETRY_STALE"], ["TELEMETRY_STALE"]),
    ({"fp_active": "on"}, ["FREE_POWER_ACTIVE"], ["FREE_POWER_ACTIVE"]),
    ({"fp_op": "on"}, ["FREE_POWER_OPERATION"], ["FREE_POWER_OPERATION"]),
    ({"fp_snap": "on"}, ["FREE_POWER_SNAPSHOT"], ["FREE_POWER_SNAPSHOT"]),
    ({"dg_active": "on"}, ["DUMP_ACTIVE"], ["DUMP_ACTIVE"]),
    ({"dg_op": "unavailable"}, ["DUMP_OPERATION"], ["DUMP_OPERATION"]),
    ({"dg_snap": "on"}, ["DUMP_SNAPSHOT"], ["DUMP_SNAPSHOT"]),
    ({"manual": "on"}, ["MANUAL_WRITE"], ["MANUAL_WRITE"]),
    ({"manual": None}, ["MANUAL_WRITE"], ["MANUAL_WRITE"]),
    ({"hold": "held"}, [], ["OVERRIDE_ACTIVE"]),
    ({"hold": "unknown"}, [], ["OVERRIDE_UNREADABLE"]),
    ({"hold": None}, [], ["OVERRIDE_UNREADABLE"]),
    ({"eff": "unknown"}, [], ["RESERVE_UNKNOWN"]),
    ({"eff": "nan"}, [], ["RESERVE_INVALID"]),
    ({"eff": "101"}, [], ["RESERVE_INVALID"]),
    ({"eff": "50"}, [], ["STOP_SOC_BELOW_RESERVE"]),
    ({"eff": "40"}, [], []),
    ({"stop": "unknown"}, [], ["STOP_SOC_UNREADABLE"]),
    ({"stop": "30"}, [], ["STOP_SOC_BELOW_RESERVE"]),
    ({"stop": "39.9"}, [], ["STOP_SOC_BELOW_RESERVE"]),
    ({"stop": "40"}, [], []),
    ({"stop": "55"}, [], []),
    ({"stop": "30", "eff": "unknown"}, [], ["RESERVE_UNKNOWN"]),
    ({"rev": "unknown"}, [], ["REVISION_UNREADABLE"]),
    ({"rev": "1.5"}, [], ["REVISION_UNREADABLE"]),
    ({"hold": "held", "eff": "80"}, [], ["OVERRIDE_ACTIVE", "STOP_SOC_BELOW_RESERVE"]),
    ({"ceil": "5000", "req": "3500"}, [], []),
    ({"ceil": "5000", "req": "3501"}, ["IMPORT_HEADROOM"], []),
    ({"ceil": "5000", "req": "5000", "grid": "-2000"}, [], []),
    ({"ceil": "5000", "req": "5001", "grid": "-2000"}, ["IMPORT_HEADROOM"], []),
    ({"ceil": "5000", "grid": "6000", "req": "500"}, ["IMPORT_HEADROOM"], []),
    ({"ceil": "5000", "grid": "unknown"}, ["IMPORT_UNREADABLE"], []),
    ({"ceil": "5000", "req": "unknown"}, ["REQUEST_UNREADABLE"], []),
    ({"ceil": "5000", "grid": "nan"}, ["IMPORT_UNREADABLE"], []),
    ({"ceil": "abc"}, ["IMPORT_CEILING_INVALID"], []),
    ({"ceil": "-5"}, ["IMPORT_CEILING_INVALID"], []),
    ({"ceil": "100001"}, ["IMPORT_CEILING_INVALID"], []),
    ({"ceil": "0.5"}, ["IMPORT_CEILING_INVALID"], []),
    ({"ceil": "nan"}, ["IMPORT_CEILING_INVALID"], []),
    ({"ceil": "0", "grid": "abc", "req": "abc"}, [], []),
    ({"ceil": "unknown", "grid": "abc", "req": "abc"}, [], []),
    ({"ceil": None, "grid": "abc", "req": "abc"}, [], []),
    ({"tl": "off", "tel": "off", "fp_active": "on", "ceil": "5000", "req": "4000", "grid": "2000"}, ["TIME_LEASES", "TELEMETRY_OFFLINE", "FREE_POWER_ACTIVE", "IMPORT_HEADROOM"],
     ["TIME_LEASES", "TELEMETRY_OFFLINE", "FREE_POWER_ACTIVE"]),
]


def gate_problems(gate_text: str, pb: Problems) -> None:
    gw = G.GateWorld(gate_text, None, poll=False, start_ha=False)
    gate_case(gw, {}, "healthy", pb)
    # the named causes, by hand: each deviation lists exactly the codes written here (the model above is checked against them, and they against the templates)
    for f, want_charge, want_export in NAMED:
        gate_case(gw, f, f"named {f}", pb)
        for kind, eid, want in (("charge", G.CHARGE_GATE, want_charge), ("export", G.EXPORT_GATE, want_export)):
            if gw.attr(eid, "blocked_by") != want:
                pb.add(f"named {f}: the {kind} gate lists {gw.attr(eid, 'blocked_by')}, written expectation {want}")
    # the boundaries of the poll freshness, and the time-driven re-render
    for age, want in ((0, "on"), (299, "on"), (300, "on"), (301, "off"), (-299, "on"), (-300, "on"), (-301, "off")):
        apply(gw, {"poll": ("age", age)})
        if gw.state(G.CHARGE_GATE) != want or gw.state(G.EXPORT_GATE) != want:
            pb.add(f"the poll text {age} s from the Home Assistant clock reads {gw.state(G.CHARGE_GATE)}, expected {want}")
    gt = G.GateWorld(gate_text, None, poll=False, start_ha=False)
    gt.put(G.POLL, gt.poll_text(0))
    gt.advance(300)
    if gt.state(G.CHARGE_GATE) != "on":
        pb.add("the gate blocked a poll text exactly 300 s old")
    gt.advance(60)
    if gt.state(G.CHARGE_GATE) != "off" or gt.attr(G.CHARGE_GATE, "blocked_by") != ["TELEMETRY_STALE"] or gt.state(G.EXPORT_GATE) != "off":
        pb.add(f"a poll text that is only getting older is not noticed by the clock alone: {gt.gate(G.CHARGE_GATE)[:2]}")
    if gt.tw.errors:
        pb.add(f"template errors {gt.tw.errors[:2]}")
    # every fact one at a time, then with a ceiling configured
    for key, values in ODD.items():
        for v in values:
            gate_case(gw, {key: v}, f"{key}={v!r}", pb)
            if key in ("ceil", "grid", "req"):
                gate_case(gw, {**WITH_CEIL, key: v}, f"configured {key}={v!r}", pb)
    # everything unreadable at once, and everything bad at once
    for label, val in (("unavailable", "unavailable"), ("missing", None), ("unknown", "unknown")):
        gate_case(gw, {k: val for k in FACT_ENT}, f"every fact {label}", pb)
    gate_case(gw, {k: "on" for k in ("tl", "ts", "tel", "cfg")} | {k: "on" for k in ("fp_active", "fp_op", "fp_snap", "dg_active", "dg_op", "dg_snap", "manual")} | {"hold": "held", "eff": "99", "stop": "10",
              "ceil": "5000", "grid": "4900", "req": "3000", "poll": ("age", 5000), "rev": "abc"}, "everything wrong", pb)
    # the seeded random sample
    rng = random.Random(20261126)
    for i in range(300):
        f = {}
        for key, values in ODD.items():
            if rng.random() < 0.22:
                f[key] = rng.choice(values)
        if rng.random() < 0.4:
            f.update({k: v for k, v in WITH_CEIL.items() if k not in f})
        gate_case(gw, f, f"random {i} {f}", pb)
    if gw.tw.errors:
        pb.add(f"template errors {gw.tw.errors[:2]}")
    if gw.w.warnings:
        pb.add(f"warnings {gw.w.warnings[:2]}")
    # a fresh helper reads 0: no ceiling configured, the check is off and says so
    g0 = G.GateWorld(gate_text, None, poll=False, start_ha=False)
    if g0.state(G.CEIL) != "0.0":
        pb.add(f"the fresh ceiling helper reads {g0.state(G.CEIL)}, not 0")
    harvest(g0)


def plan_problems(gate_text: str, pb: Problems) -> None:
    """The REAL plan helper package feeds the gate: the hold, the effective reserve (rounded up) and the plan revision as it produces them."""
    gw = G.GateWorld(gate_text, None, plan_text=PLAN_TEXT, poll=True, start_ha=False)
    gw.foreign = True
    pw, w = gw.pw, gw.w
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    gw.put(G.STOP, "40.0")
    gw.sync()

    def gate():
        gw.sync()
        return gw.state(G.EXPORT_GATE), gw.attr(G.EXPORT_GATE, "blocked_by"), gw.state(G.CHARGE_GATE)
    if gate() != ("on", [], "on"):
        pb.add(f"the real plan helpers: the export gate reads {gate()} with nothing active")
    pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
    if gate() != ("off", ["OVERRIDE_ACTIVE"], "on"):
        pb.add(f"a running Hold battery does not close the export gate (and only it): {gate()}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
    if gate() != ("on", [], "on"):
        pb.add(f"a cancelled Hold battery still closes the export gate: {gate()}")
    pw.run_script("ecco_plan_override_start", {"kind": "prepare_power_cut", "expiry_min": 600})
    if gw.state(G.EFF) != "80" or gate() != ("off", ["OVERRIDE_ACTIVE", "STOP_SOC_BELOW_RESERVE"], "on"):
        pb.add(f"a power cut (reserve 80) with a staged Stop SOC of 40 must close the export gate with both causes: eff {gw.state(G.EFF)} {gate()}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "prepare_power_cut"})
    w.set("input_number.ecco_minimum_reserve_soc", "62.4")
    gw.put(G.STOP, "62.0")
    if gw.state(G.EFF) != "63" or gate() != ("off", ["STOP_SOC_BELOW_RESERVE"], "on"):
        pb.add(f"a fractional reserve 62.4 is published as 63 and a staged Stop SOC of 62 is below it: eff {gw.state(G.EFF)} {gate()}")
    gw.put(G.STOP, "63.0")
    if gate() != ("on", [], "on"):
        pb.add(f"a staged Stop SOC equal to the rounded-up reserve must pass: {gate()}")
    w.set("input_number.ecco_minimum_reserve_soc", "unavailable")
    if gate() != ("off", ["RESERVE_UNKNOWN"], "on"):
        pb.add(f"an unreadable owner reserve must close the export gate: {gate()}")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    w.set("input_number.ecco_plan_revision", "unavailable")
    if gate() != ("off", ["REVISION_UNREADABLE"], "on"):
        pb.add(f"an unreadable plan revision must close the export gate: {gate()}")
    if gw.tw.errors:
        pb.add(f"template errors {gw.tw.errors[:2]}")


# ===========================================================================================================================
# [2] the guarded Free Power start
# ===========================================================================================================================
START_OK = [("switch.turn_on", G.ARM), ("button.press", G.START_FP), ("switch.turn_off", G.ARM)]
SAFE_END = [("switch.turn_off", G.ARM)]


def sw(gate_text: str, **kw) -> "G.GateWorld":
    return G.GateWorld(gate_text, None, **kw)


def reset(gw: "G.GateWorld") -> None:
    """Every fact the script reads back to healthy, the dongle idle, the notifications and the last result cleared."""
    gw.make_healthy()
    gw.put(G.CEIL, "0.0")
    gw.tw.override(G.CHARGE_GATE, None)
    gw.w.notifications.clear()
    gw.put(G.LAST, "")
    gw.d.flags["ntp_bad"] = False
    gw.d.outcome = "ok"
    gw.d.handle_delays = [0.15]
    gw.d.drop_numbers = False
    for log in (gw.d.press_log, gw.d.presses, gw.d.number_log, gw.d.button_log):
        log.clear()
    gw.d.active = False
    gw.w.set(S.E_ACTIVE, "off")
    gw.w.set(G.ARM, "off")
    gw.d.arm = False
    gw.stop_poll()
    gw.put(G.POLL, gw.poll_text(0))


def run_start(gw: "G.GateWorld", data: dict | None = None, seconds: float = 6.0) -> int:
    n0 = len(gw.w.service_log)
    gw.script("ecco_free_power_start_guarded", data or {}, seconds)
    return n0


def dongle_calls(gw: "G.GateWorld", n0: int) -> list:
    """The calls a run made that reach the dongle (the result text and the notifications are looked at on their own)."""
    return [(s, e) for s, e, _d in gw.services(n0) if not s.startswith(("input_text.", "persistent_notification."))]


def refused(gw: "G.GateWorld", n0: int, code: str, label: str, pb: Problems, text: str = "") -> None:
    """A refusal before anything is staged: nothing staged, armed or pressed (only the write enable is put off), the stable code in the result text and ONE notification."""
    last, note = gw.state(G.LAST), gw.w.notifications.get(G.NOTE_START, {})
    if dongle_calls(gw, n0) != SAFE_END or gw.d.press_log or gw.d.number_log or gw.d.presses:
        pb.add(f"{label}: not a clean refusal: calls {dongle_calls(gw, n0)}, presses {gw.d.press_log}, numbers {gw.d.number_log}")
    if not last.startswith(f"REFUSED {code} - ") or len(last) > 250 or f"(reason {code})" not in note.get("message", "") or len(gw.w.notifications) != 1:
        pb.add(f"{label}: the result text or the notification: {last[:60]!r} {note.get('message', '')[-40:]!r} {sorted(gw.w.notifications)}")
    if text and text not in last + " " + note.get("message", ""):
        pb.add(f"{label}: the text does not say {text!r}: {last[:120]!r}")
    if gw.state(G.ARM) != "off" or gw.state("script.ecco_free_power_start_guarded") != "off":
        pb.add(f"{label}: the write enable or the script is not off")


def press_refused(gw: "G.GateWorld", n0: int, code: str, label: str, pb: Problems) -> None:
    """A refusal at the press-time check: staged and armed, but nothing pressed, and the write enable ends off."""
    calls, last = dongle_calls(gw, n0), gw.state(G.LAST)
    if ("button.press", G.START_FP) in calls or gw.d.press_log or gw.d.presses or calls[-1:] != SAFE_END or ("switch.turn_on", G.ARM) not in calls:
        pb.add(f"{label}: not a press-time refusal: {calls} presses {gw.d.press_log}")
    if not last.startswith(f"REFUSED {code} - ") or f"(reason {code})" not in gw.w.notifications.get(G.NOTE_START, {}).get("message", ""):
        pb.add(f"{label}: the result text or the notification: {last[:80]!r}")
    if gw.state(G.ARM) != "off":
        pb.add(f"{label}: the write enable is not off")


def script_problems(gate_text: str, pb: Problems) -> None:
    # --- the allowed path: exactly the calls the schedule and the card make -----------------------------------------------------------------------
    gw = sw(gate_text)
    n0 = run_start(gw, {}, 200.0)
    if dongle_calls(gw, n0) != START_OK or gw.d.number_log or len(gw.d.press_log) != 1 or [p[1] for p in gw.d.presses] != ["PASSED"]:
        pb.add(f"allowed start with nothing given: calls {dongle_calls(gw, n0)}, numbers {gw.d.number_log}, presses {gw.d.press_log} {gw.d.presses}")
    if not gw.state(G.LAST).startswith("STARTED free_power at 4000 W for 60 min") or gw.w.notifications or gw.state(S.E_ACTIVE) != "on" or gw.state(G.ARM) != "off":
        pb.add(f"allowed start: result {gw.state(G.LAST)!r}, notifications {sorted(gw.w.notifications)}, active {gw.state(S.E_ACTIVE)}, arm {gw.state(G.ARM)}")
    if gw.w.warnings or gw.tw.errors:
        pb.add(f"allowed start: warnings {gw.w.warnings[:2]} errors {gw.tw.errors[:2]}")
    harvest(gw)
    for data, nums, text in (({"power_w": 3000, "duration_minutes": 45}, [(G.REQ, 3000), (G.DUR, 45)], "3000 W for 45 min"),
                             ({"power_w": "3000", "duration_minutes": "45"}, [(G.REQ, 3000), (G.DUR, 45)], "3000 W for 45 min"),
                             ({"power_w": 4000, "duration_minutes": 60}, [], "4000 W for 60 min"),
                             ({"power_w": 2000}, [(G.REQ, 2000)], "2000 W for 60 min"),
                             ({"duration_minutes": 30}, [(G.DUR, 30)], "4000 W for 30 min"),
                             ({"power_w": "", "duration_minutes": ""}, [], "4000 W for 60 min"),
                             ({"power_w": 8000, "duration_minutes": 240}, [(G.REQ, 8000), (G.DUR, 240)], "8000 W for 240 min"),
                             ({"power_w": 500, "duration_minutes": 5}, [(G.REQ, 500), (G.DUR, 5)], "500 W for 5 min")):
        gw = sw(gate_text)
        n0 = run_start(gw, data, 200.0)
        want = [("number.set_value", e) for e, _v in nums] + START_OK
        if dongle_calls(gw, n0) != want or [(e, v) for _t, e, v in gw.d.number_log] != nums or len(gw.d.press_log) != 1:
            pb.add(f"allowed start {data}: calls {dongle_calls(gw, n0)}, numbers {gw.d.number_log}, expected staging {nums}")
        if not gw.state(G.LAST).startswith("STARTED free_power at " + text) or gw.state(S.E_ACTIVE) != "on" or gw.state(G.ARM) != "off":
            pb.add(f"allowed start {data}: result {gw.state(G.LAST)!r}")
        harvest(gw)

    # --- the refusals before anything is staged -----------------------------------------------------------------------------------------------------
    gw = sw(gate_text)
    cases = [
        ("the gate is closed (time trust)", lambda g: g.put(G.TL, "off"), {}, "GATE_BLOCKED", "TIME_LEASES"),
        ("the gate is closed (telemetry)", lambda g: g.put(G.TEL, "unavailable"), {}, "GATE_BLOCKED", "TELEMETRY_OFFLINE"),
        ("the gate is closed (Free Power running)", lambda g: g.put(G.FP_ACTIVE, "on"), {}, "GATE_BLOCKED", "FREE_POWER_ACTIVE"),
        ("the gate is closed (a Dump snapshot is owed)", lambda g: g.put(G.DG_SNAP, "on"), {}, "GATE_BLOCKED", "DUMP_SNAPSHOT"),
        ("the gate is closed (stale poll)", lambda g: g.put(G.POLL, g.poll_text(400)), {}, "GATE_BLOCKED", "TELEMETRY_STALE"),
        ("the gate is closed by two causes", lambda g: (g.put(G.TS, "off"), g.put(G.MANUAL, "on")), {}, "GATE_BLOCKED", "TIME_SCHEDULES, MANUAL_WRITE"),
        ("the gate is closed (import headroom) with no explicit request", lambda g: (g.put(G.CEIL, "5000"), g.put(G.GRID, "2000")), {}, "GATE_BLOCKED", "IMPORT_HEADROOM"),
        ("the gate is closed (import headroom) with an explicit request equal to the staged one", lambda g: (g.put(G.CEIL, "5000"), g.put(G.GRID, "2000")), {"power_w": 4000}, "GATE_BLOCKED", "IMPORT_HEADROOM"),
        ("the gate is closed by time trust although the request would fit", lambda g: (g.put(G.TL, "off"), g.put(G.CEIL, "5000"), g.put(G.GRID, "2000")), {"power_w": 2000}, "GATE_BLOCKED", "TIME_LEASES"),
        ("the gate is closed by an unreadable request that an explicit one would fix, with another cause", lambda g: (g.put(G.CEIL, "5000"), g.put(G.REQ, "unknown"), g.put(G.TL, "off")), {"power_w": 2000}, "GATE_BLOCKED", "REQUEST_UNREADABLE"),
        ("the gate sensor is unavailable", lambda g: g.tw.override(G.CHARGE_GATE, "unavailable"), {}, "GATE_UNREADABLE", "unavailable"),
        ("the gate sensor is unknown", lambda g: g.tw.override(G.CHARGE_GATE, "unknown"), {}, "GATE_UNREADABLE", "unknown"),
        ("the gate sensor reads something else", lambda g: g.tw.override(G.CHARGE_GATE, "maybe"), {}, "GATE_UNREADABLE", "maybe"),
        ("a scheduled start is running", lambda g: g.put(G.SCHED, "on"), {}, "SCHEDULED_START_RUNNING", "wait for it"),
        ("the scheduled start script is unavailable", lambda g: g.put(G.SCHED, "unavailable"), {}, "SCHEDULED_START_RUNNING", "unavailable"),
        ("the scheduled start script is missing", lambda g: g.put(G.SCHED, None), {}, "SCHEDULED_START_RUNNING", "unknown"),
        ("the grid charge limit is unavailable", lambda g: g.put(G.LIMIT, "unavailable"), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is missing", lambda g: g.put(G.LIMIT, None), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is 0", lambda g: g.put(G.LIMIT, "0"), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is below the minimum", lambda g: g.put(G.LIMIT, "400"), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is nan", lambda g: g.put(G.LIMIT, "nan"), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is infinite", lambda g: g.put(G.LIMIT, "inf"), {}, "LIMIT_UNREADABLE", ""),
        ("the grid charge limit is absurd", lambda g: g.put(G.LIMIT, "500000"), {}, "LIMIT_UNREADABLE", ""),
        ("the staged power is unreadable and none is given", lambda g: g.put(G.REQ, "unknown"), {}, "POWER_INVALID", ""),
        ("the staged duration is unreadable and none is given", lambda g: g.put(G.DUR, "unavailable"), {}, "DURATION_INVALID", ""),
        ("the limit is lower than the staged power", lambda g: g.put(G.LIMIT, "3000"), {}, "POWER_INVALID", "3000 W"),
        ("the gate is closed and the power is invalid: the gate is named first", lambda g: g.put(G.TL, "off"), {"power_w": 123}, "GATE_BLOCKED", "TIME_LEASES"),
        ("a scheduled start runs and the power is invalid: the schedule is named first", lambda g: g.put(G.SCHED, "on"), {"power_w": 123}, "SCHEDULED_START_RUNNING", ""),
        ("the limit is unreadable and the power is invalid: the limit is named first", lambda g: g.put(G.LIMIT, "unknown"), {"power_w": 123}, "LIMIT_UNREADABLE", ""),
        ("the power and the duration are invalid: the power is named first", lambda g: None, {"power_w": 123, "duration_minutes": 0}, "POWER_INVALID", ""),
    ]
    for power in (400, 8100, 4050, "abc", "nan", -100, 0, 0.5, "inf", 499, 8001):
        cases.append((f"the requested power {power!r}", lambda g: None, {"power_w": power}, "POWER_INVALID", ""))
    for dur in (0, 241, 1.5, "abc", "nan", -1, "inf", 0.5, 240.5):
        cases.append((f"the requested duration {dur!r}", lambda g: None, {"duration_minutes": dur}, "DURATION_INVALID", ""))
    for label, setup, data, code, text in cases:
        reset(gw)
        setup(gw)
        n0 = run_start(gw, data)
        refused(gw, n0, code, label, pb, text)
    harvest(gw)

    # --- the gate closed ONLY by what the request decides is judged again after the explicit request is staged ----------------------------------------------
    def configured(g):
        g.put(G.CEIL, "5000")
        g.put(G.GRID, "2000")           # headroom 3000 W; the staged 4000 W does not fit
    gw = sw(gate_text)
    reset(gw)
    configured(gw)
    n0 = run_start(gw, {"power_w": 3000}, 200.0)
    if dongle_calls(gw, n0) != [("number.set_value", G.REQ)] + START_OK or [(e, v) for _t, e, v in gw.d.number_log] != [(G.REQ, 3000)] or not gw.state(G.LAST).startswith("STARTED free_power at 3000 W"):
        pb.add(f"an explicit request that fits the headroom must start: {dongle_calls(gw, n0)} {gw.state(G.LAST)[:60]!r}")
    reset(gw)
    configured(gw)
    n0 = run_start(gw, {"power_w": 3500}, 10.0)
    press_refused(gw, n0, "GATE_CLOSED", "an explicit request that does not fit the headroom", pb)
    if [(e, v) for _t, e, v in gw.d.number_log] != [(G.REQ, 3500)]:
        pb.add(f"the staged request of a refused explicit start stays staged (stated): {gw.d.number_log}")
    reset(gw)
    gw.put(G.CEIL, "5000")
    gw.put(G.GRID, "2000")
    gw.put(G.REQ, "unknown")
    n0 = run_start(gw, {"power_w": 2500}, 200.0)
    if dongle_calls(gw, n0) != [("number.set_value", G.REQ)] + START_OK or not gw.state(G.LAST).startswith("STARTED free_power at 2500 W"):
        pb.add(f"an explicit request fixes an unreadable staged one: {dongle_calls(gw, n0)} {gw.state(G.LAST)[:60]!r}")
    harvest(gw)

    # --- the press-time check: this run staged and waited since it read the gate --------------------------------------------------------------------
    def interfere(gw, fn, at=0.5):
        gw.w.at(gw.w.t + at, fn)

    for label, code, fn, data, setup in (
        ("the gate closes while the request is staged", "GATE_CLOSED", lambda g: lambda: g.put(G.TL, "off"), {}, None),
        ("the gate closes (a Dump lease starts) while the request is staged", "GATE_CLOSED", lambda g: lambda: g.put(G.DG_ACTIVE, "on"), {}, None),
        ("a scheduled start begins while the request is staged", "SCHEDULED_START_RUNNING", lambda g: lambda: g.put(G.SCHED, "on"), {}, None),
        ("the grid charge limit is lowered below the request while it is staged", "LIMIT_LOWERED", lambda g: lambda: g.put(G.LIMIT, "3000"), {}, None),
        ("the grid charge limit becomes unreadable while it is staged", "LIMIT_LOWERED", lambda g: lambda: g.put(G.LIMIT, "unavailable"), {}, None),
        ("the dongle does not confirm the staged values", "NOT_CONFIRMED", lambda g: lambda: None, {"power_w": 3000}, lambda g: setattr(g.d, "drop_numbers", True)),
        ("the dongle does not confirm the arm", "NOT_CONFIRMED", lambda g: lambda: g.put(G.ARM, "off"), {}, None),
    ):
        gw = sw(gate_text)
        reset(gw)
        if setup:
            setup(gw)
        interfere(gw, fn(gw))
        if code == "NOT_CONFIRMED" and not data:
            gw.w.at(gw.w.t + 0.4, lambda: setattr(gw.d, "arm", False))    # the arm is dropped on the dongle before it is confirmed
        n0 = run_start(gw, data, 12.0)
        press_refused(gw, n0, code, label, pb)
        harvest(gw)
    # the waits are real waits: the dongle gets 5 s to confirm the arm and the staged values, and 15 s to answer a press
    gw = sw(gate_text)
    reset(gw)
    gw.d.drop_numbers = True
    run_start(gw, {"power_w": 3000}, 4.0)
    if gw.state("script.ecco_free_power_start_guarded") != "on" or gw.state(G.LAST) != "":
        pb.add(f"the guarded start gave up on the confirmation before 5 s: script {gw.state('script.ecco_free_power_start_guarded')} result {gw.state(G.LAST)[:40]!r}")
    gw.advance(6)
    if not gw.state(G.LAST).startswith("REFUSED NOT_CONFIRMED - "):
        pb.add(f"the guarded start did not refuse after 5 s: {gw.state(G.LAST)[:60]!r}")
    gw = sw(gate_text)
    reset(gw)
    gw.d.handle_delays = [900.0]
    run_start(gw, {}, 10.0)
    if gw.state("script.ecco_free_power_start_guarded") != "on" or gw.state(G.LAST) != "":
        pb.add(f"the guarded start gave up on the dongle's answer before 15 s: result {gw.state(G.LAST)[:40]!r}")
    gw.advance(14)
    if not gw.state(G.LAST).startswith("FAILED NO_ANSWER - ") or gw.state("script.ecco_free_power_start_guarded") != "off":
        pb.add(f"the unanswered press is not reported by 24 s (the wait for the write enable to go off is 10 s at most): {gw.state(G.LAST)[:60]!r}")

    # --- what the dongle answers --------------------------------------------------------------------------------------------------------------------
    gw = sw(gate_text)
    reset(gw)
    gw.d.flags["ntp_bad"] = True
    n0 = run_start(gw, {}, 60.0)
    last, note = gw.state(G.LAST), gw.w.notifications.get(G.NOTE_START, {})
    if (dongle_calls(gw, n0) != START_OK or len(gw.d.press_log) != 1 or not gw.d.presses[0][1].startswith("REJECTED") or not last.startswith("FAILED FIRMWARE_REFUSED - ")
            or "valid NTP time required" not in last or "(reason FIRMWARE_REFUSED)" not in note.get("message", "") or gw.state(G.ARM) != "off" or gw.state(S.E_ACTIVE) != "off"):
        pb.add(f"a start the dongle refuses: {dongle_calls(gw, n0)} {gw.d.presses} {last[:90]!r}")
    for outcome in ("capture_failed", "write_failed"):
        gw = sw(gate_text)
        reset(gw)
        gw.d.outcome = outcome
        n0 = run_start(gw, {}, 200.0)
        last, note = gw.state(G.LAST), gw.w.notifications.get(G.NOTE_START, {})
        if (dongle_calls(gw, n0) != START_OK or len(gw.d.press_log) != 1 or not last.startswith("FAILED START_FAILED - ") or "(reason START_FAILED)" not in note.get("message", "")
                or gw.state(S.E_ACTIVE) != "off" or gw.state(G.ARM) != "off"):
            pb.add(f"a start transaction that fails ({outcome}): {dongle_calls(gw, n0)} {last[:90]!r}")
    gw = sw(gate_text)
    reset(gw)
    gw.d.handle_delays = [900.0]
    n0 = run_start(gw, {}, 120.0)
    last, note = gw.state(G.LAST), gw.w.notifications.get(G.NOTE_START, {})
    if (len(gw.d.press_log) != 1 or not last.startswith("FAILED NO_ANSWER - ") or "(reason NO_ANSWER)" not in note.get("message", "") or gw.state(G.ARM) != "off"
            or ("switch.turn_off", G.ARM) not in dongle_calls(gw, n0)):
        pb.add(f"a press the dongle never answers: {dongle_calls(gw, n0)} {last[:90]!r}")
    harvest(gw)

    # --- a second start, and two at once --------------------------------------------------------------------------------------------------------------
    gw = sw(gate_text)
    n0 = run_start(gw, {}, 200.0)
    n1 = run_start(gw, {}, 20.0)
    if len(gw.d.press_log) != 1 or not gw.state(G.LAST).startswith("REFUSED GATE_BLOCKED - ") or "FREE_POWER_ACTIVE" not in gw.state(G.LAST):
        pb.add(f"a second start while Free Power runs: presses {gw.d.press_log} {gw.state(G.LAST)[:90]!r}")
    gw = sw(gate_text)
    gw.w.warnings.clear()
    first = gw.ha.start_script("ecco_free_power_start_guarded", {})
    second = gw.ha.start_script("ecco_free_power_start_guarded", {})
    gw.advance(200)
    if not first or second or len(gw.d.press_log) != 1 or len(gw.w.warnings) != 1:
        pb.add(f"two starts at once (mode single): {first} {second} presses {gw.d.press_log} warnings {gw.w.warnings}")
    harvest(gw)

    # --- the same staging as the scheduled start (the repository's own script run against the same dongle model) ----------------------------------------------
    sched = G.GateWorld(gate_text, None, extra=(FREE_TEXT,), poll=False, start_ha=False)      # the schedule's own automations are not started: only its script runs
    sched.foreign = True
    sched.w.set("input_boolean.ecco_free_power_schedule_armed", "on")
    sched.advance(2)
    sched.ha.start_script("ecco_free_power_start_scheduled", {"duration_minutes": 45, "power_w": 3000, "window_end_ts": sched.w.t + 3600})
    sched.advance(200)
    guard = sw(gate_text)
    run_start(guard, {"power_w": 3000, "duration_minutes": 45}, 200.0)
    kinds = ("number.set_value", "switch.turn_on", "switch.turn_off", "button.press")
    a = {(s, e) for s, e, _d in sched.services() if s in kinds}
    b = {(s, e) for s, e, _d in guard.services() if s in kinds}
    if a != b or [(e, v) for _t, e, v in sched.d.number_log] != [(e, v) for _t, e, v in guard.d.number_log] or not sched.d.presses or [p[1] for p in guard.d.presses] != [p[1] for p in sched.d.presses]:
        pb.add(f"the staging differs from the scheduled start's: {sorted(a ^ b)} {sched.d.number_log} {guard.d.number_log}")
    harvest(sched)
    harvest(guard)


# ===========================================================================================================================
# [3] the guards
# ===========================================================================================================================
def dump_world(gate_text: str, guards_text: str, *, hold: str = "clear", eff: str = "40", latched: float = 40.0, lease: bool = True, latched_delay: float = 0.0,
                end_after: float = 20.0) -> "G.GateWorld":
    gw = G.GateWorld(gate_text, guards_text, poll=False, start_ha=False)
    gw.d.end_after = end_after
    gw.put(G.HOLD, hold)
    gw.put(G.EFF, eff)
    if lease:
        gw.d.dump_start(latched=latched, latched_delay=latched_delay)
    gw.ha.start()
    gw.advance(2)
    return gw


def fp_world(gate_text: str, guards_text: str, *, leases: str = "on", lease: bool = True, ceiling: str = "0.0", grid: str = "1500.0", end_after: float = 20.0) -> "G.GateWorld":
    gw = G.GateWorld(gate_text, guards_text, poll=False, start_ha=False)
    gw.d.end_after = end_after
    gw.put(G.TL, leases)
    gw.put(G.CEIL, ceiling)
    gw.put(G.GRID, grid)
    if lease:
        gw.d.fp_start()
    gw.ha.start()
    gw.advance(2)
    return gw


def pressed_once(gw: "G.GateWorld", button: str, at: float, tol: float, label: str, pb: Problems, note: str = "", words: tuple = ()) -> None:
    ts = gw.d.pressed(button)
    n = gw.w.notifications.get(note, {}).get("message", "") if note else ""
    if len(ts) != 1 or abs(ts[0] - at) > tol:
        pb.add(f"{label}: presses of {button.split('_', 3)[-1]} at {[round(t - at, 1) for t in ts]} s from the event, expected one within {tol} s")
    elif note and (note not in gw.w.notifications or any(w not in n for w in words)):
        pb.add(f"{label}: the notification {note}: {n[:140]!r} lacks {[w for w in words if w not in n]}")


def silent(gw: "G.GateWorld", label: str, pb: Problems) -> None:
    if gw.d.button_log or gw.w.notifications:
        pb.add(f"{label}: expected nothing, got presses {[(round(t), e.split('_', 3)[-1]) for t, e in gw.d.button_log]} notifications {sorted(gw.w.notifications)}")


def guard_problems(gate_text: str, guards_text: str, pb: Problems) -> None:
    D, F = G.END_DUMP, G.END_FP
    # ---- the Dump guard ------------------------------------------------------------------------------------------------------------------------------
    gw = dump_world(gate_text, guards_text)
    t0 = gw.w.t
    gw.put(G.HOLD, "held", {"held_by": "hold_battery"})
    gw.advance(40)
    pressed_once(gw, D, t0, 1.0, "a hold turns on during a Dump lease", pb, G.NOTE_DUMP, ("END DUMP TO GRID - RESTORE NOW", "Hold battery", "hold_battery"))
    if gw.d.dump_active or [e for _t, e in gw.d.button_log] != [D]:
        pb.add(f"the Dump lease should have been ended by the press and nothing else pressed: {gw.d.button_log}")
    harvest(gw)
    for latched, e0, e1, want in ((40, "40", "41", True), (40, "40", "39", False), (40, "30", "40", False), (50, "45", "51", True), (50, "45", "50", False), (40, "40", "80", True),
                                  (40, "40", "100", True), (40, "40", "101", False), (40, "40", "nan", False), (40, "40", "unknown", False), (40, "40", "unavailable", False),
                                  (40, "40", "-1", False), (40, "40", "", False), (90, "40", "91", True), (10, "5", "11", True)):
        gw = dump_world(gate_text, guards_text, eff=e0, latched=float(latched))
        t0 = gw.w.t
        gw.put(G.EFF, e1)
        gw.advance(40)
        if want:
            pressed_once(gw, D, t0, 1.0, f"the reserve {e0} -> {e1} over a latched Stop SOC of {latched}", pb, G.NOTE_DUMP, (f"effective reserve ({int(float(e1))} %)", f"({latched} %)"))
        else:
            silent(gw, f"the reserve {e0} -> {e1} against a latched Stop SOC of {latched}", pb)
        harvest(gw)
    gw = dump_world(gate_text, guards_text, eff="80", latched=40.0)      # a violation stands
    gw.put(G.EFF, "80", {"refreshed_at": "2026-11-26T12:01:00"})
    gw.advance(120)
    silent(gw, "an attribute-only update of the reserve sensor (a standing violation)", pb)
    gw = dump_world(gate_text, guards_text, lease=False)
    gw.put(G.HOLD, "held")
    gw.put(G.EFF, "80")
    gw.advance(60)
    silent(gw, "a hold and a reserve rise with no Dump lease", pb)
    gw = dump_world(gate_text, guards_text)
    for v in ("unknown", "unavailable", None):
        gw.put(G.HOLD, v)
    gw.put(G.EFF, "unavailable")
    gw.put(G.EFF, "unknown")
    gw.advance(60)
    silent(gw, "records that cannot be read during a Dump lease", pb)
    # a lease that starts under a violation
    gw = dump_world(gate_text, guards_text, hold="held", lease=False)
    t0 = gw.w.t
    gw.d.dump_start(latched=40.0)
    gw.advance(40)
    pressed_once(gw, D, t0, 1.0, "a Dump lease starts under a hold", pb, G.NOTE_DUMP, ("Hold battery",))
    gw = dump_world(gate_text, guards_text, eff="80", lease=False)
    t0 = gw.w.t
    gw.d.dump_start(latched=40.0, latched_delay=4.0)
    gw.advance(40)
    pressed_once(gw, D, t0 + 4.0, 1.0, "a Dump lease starts under a reserve above its Stop SOC (the latched value arrives 4 s later)", pb, G.NOTE_DUMP, ("effective reserve (80 %)", "(40 %)"))
    gw = dump_world(gate_text, guards_text, eff="80", lease=False)
    gw.d.dump_start(latched=40.0, latched_delay=1000.0)
    gw.advance(120)
    silent(gw, "a Dump lease whose latched Stop SOC is never published", pb)
    gw = dump_world(gate_text, guards_text, eff="80", lease=False)
    gw.d.dump_start(latched=40.0, latched_delay=16.0)
    gw.advance(120)
    silent(gw, "a latched Stop SOC published after the 15 s wait (stated: the guard has given up)", pb)
    gw = dump_world(gate_text, guards_text, eff="40", lease=False)
    gw.d.dump_start(latched=40.0)
    gw.advance(120)
    silent(gw, "a Dump lease that starts with no violation", pb)
    gw2 = dump_world(gate_text, guards_text, eff="40", latched=40.0)
    gw2.put(G.LATCHED, "unknown")
    t0b = gw2.w.t
    gw2.put(G.EFF, "80")
    gw2.w.at(t0b + 10.0, lambda: gw2.put(G.LATCHED, "40.0"))
    gw2.advance(60)
    pressed_once(gw2, D, t0b + 10.0, 1.0, "the reserve rises while the latched Stop SOC is not yet readable (it arrives 10 s later)", pb)
    gw3 = dump_world(gate_text, guards_text, eff="40", latched=40.0)
    gw3.put(G.LATCHED, "unknown")
    t0c = gw3.w.t
    gw3.put(G.EFF, "80")
    gw3.w.at(t0c + 16.0, lambda: gw3.put(G.LATCHED, "40.0"))
    gw3.advance(120)
    silent(gw3, "the reserve rises and the latched Stop SOC arrives after the wait", pb)
    gw = dump_world(gate_text, guards_text, eff="40", latched=40.0)
    gw.put(G.LATCHED, "unknown")
    t0 = gw.w.t
    gw.put(G.HOLD, "held")
    gw.advance(40)
    pressed_once(gw, D, t0, 1.0, "a hold turns on while the latched Stop SOC cannot be read (a hold needs no Stop SOC): pressed at once", pb, G.NOTE_DUMP, ("Hold battery",))
    # a change FROM unavailable, unknown or nothing is never a reason, with the violation standing
    # a lease that ends during the wait for the latched Stop SOC releases the guard at once: a new lease that starts under a violation is judged then
    gw = dump_world(gate_text, guards_text, eff="80", lease=False)
    t0 = gw.w.t
    gw.d.dump_start(latched=40.0, latched_delay=1000.0)
    gw.advance(2)
    gw.d.dump_end()
    gw.advance(1)
    gw.d.dump_start(latched=40.0)
    gw.advance(30)
    pressed_once(gw, D, t0 + 3.0, 1.0, "a lease ends during the wait and a new one starts under a violation: the guard was released at once", pb, G.NOTE_DUMP)
    if any("already running" in x for x in gw.w.warnings):
        pb.add(f"the second lease's start arrived while the first run was still waiting (the wait must end with its lease): {gw.w.warnings[:1]}")
    for pre in ("unavailable", "unknown", None):
        gw = dump_world(gate_text, guards_text, hold=pre, eff="40")
        gw.put(G.HOLD, "held")
        gw.advance(120)
        silent(gw, f"the hold sensor turning on from {pre!r} during a Dump lease", pb)
        gw = dump_world(gate_text, guards_text, eff=pre)
        gw.put(G.EFF, "80")
        gw.advance(120)
        silent(gw, f"the reserve sensor reading 80 from {pre!r} above the latched Stop SOC", pb)
    gw = dump_world(gate_text, guards_text, eff="80", lease=False)
    gw.d.dump_active = True
    gw.put(G.DG_ACTIVE, "unavailable")
    gw.put(G.LATCHED, "40.0")
    gw.put(G.DG_ACTIVE, "on")
    gw.advance(120)
    silent(gw, "the lease flag coming back from unavailable (a reconnect) under a standing violation", pb)
    # once per violation
    gw = dump_world(gate_text, guards_text, end_after=1000.0)
    t0 = gw.w.t
    gw.put(G.EFF, "41")
    gw.advance(30)
    gw.put(G.EFF, "42")
    gw.advance(20)
    gw.put(G.HOLD, "held")
    gw.advance(9)
    if len(gw.d.pressed(D)) != 1:
        pb.add(f"one violation must be one press: presses at {[round(t - t0) for t in gw.d.pressed(D)]}")
    gw.advance(5)
    gw.put(G.EFF, "43")
    gw.advance(10)
    if len(gw.d.pressed(D)) != 2 or set(e for _t, e in gw.d.button_log) != {D}:
        pb.add(f"a new violation after the minute presses again: {[round(t - t0) for t in gw.d.pressed(D)]} {sorted({e for _t, e in gw.d.button_log})}")
    harvest(gw)

    # ---- the Free Power time guard -----------------------------------------------------------------------------------------------------------------
    gw = fp_world(gate_text, guards_text)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(299)
    if gw.d.button_log:
        pb.add(f"the time guard pressed before its 5 minutes: {gw.d.button_log}")
    gw.advance(10)
    pressed_once(gw, F, t0 + 300, 1.5, "the leases sensor leaves on for 5 minutes", pb, G.NOTE_FP, ("END FREE POWER - RESTORE NOW", "5 minutes", "reads off"))
    gw = fp_world(gate_text, guards_text)
    gw.put(G.TL, "off")
    gw.advance(299)
    gw.put(G.TL, "on")
    gw.advance(700)
    silent(gw, "the leases sensor is back on at 299 s", pb)
    gw = fp_world(gate_text, guards_text)
    gw.put(G.TL, "off")
    gw.advance(100)
    gw.d.fp_end()
    gw.advance(400)
    silent(gw, "the Free Power lease ends during the 5 minutes", pb)
    gw = fp_world(gate_text, guards_text, leases="off", lease=False)
    t0 = gw.w.t
    gw.advance(10)
    gw.d.fp_start()
    gw.advance(310)
    pressed_once(gw, F, t0 + 310, 1.5, "a lease starts while the leases sensor reads off (counted from the start: 300 s)", pb, G.NOTE_FP)
    for pre in ("unavailable", "unknown", None):
        gw = fp_world(gate_text, guards_text, leases=pre if pre else "unavailable")
        gw.put(G.TL, pre)
        gw.put(G.TL, "off")
        gw.advance(800)
        silent(gw, f"the leases sensor coming back from {pre!r} as off", pb)
    gw = fp_world(gate_text, guards_text)
    gw.put(G.TL, "unavailable")
    gw.advance(700)
    gw.put(G.TL, "unknown")
    gw.advance(700)
    silent(gw, "the leases sensor unreadable for 20 minutes (never a reason on its own)", pb)
    gw = fp_world(gate_text, guards_text)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(100)
    gw.put(G.TL, "unavailable")
    gw.advance(220)
    pressed_once(gw, F, t0 + 300, 1.5, "the leases sensor goes off and then unreadable: still not on after 5 minutes", pb, G.NOTE_FP)
    for pre in ("unavailable", "unknown", None):
        gw = fp_world(gate_text, guards_text, leases=pre, lease=False)
        gw.advance(10)
        gw.d.fp_start()
        gw.advance(800)
        silent(gw, f"a lease starts while the leases sensor cannot be read ({pre!r}: a missing time trust package must not end every lease)", pb)
    gw = fp_world(gate_text, guards_text, leases="off", lease=False)
    t0 = gw.w.t
    gw.d.fp_start()
    gw.advance(100)
    gw.d.fp_end()
    gw.advance(50)
    gw.d.fp_start()
    gw.advance(320)
    pressed_once(gw, F, t0 + 450, 1.5, "a lease ends during the count and another starts: the count starts again", pb, G.NOTE_FP)
    gw = fp_world(gate_text, guards_text, leases="off", lease=True)
    gw.put(G.FP_ACTIVE, "unavailable")
    gw.put(G.FP_ACTIVE, "on")
    gw.advance(800)
    silent(gw, "the lease flag coming back from unavailable with the leases sensor off (a reconnect)", pb)
    gw = fp_world(gate_text, guards_text)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(100)
    gw.put(G.TL, "on")
    gw.advance(50)
    gw.put(G.TL, "off")
    gw.advance(310)
    pressed_once(gw, F, t0 + 450, 1.5, "the leases sensor flaps: the count starts again at the second loss", pb)
    harvest(gw)

    # ---- the Free Power import guard ------------------------------------------------------------------------------------------------------------------
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000")
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.advance(29)
    if gw.d.button_log:
        pb.add("the import guard pressed before its 30 seconds")
    gw.advance(5)
    pressed_once(gw, F, t0 + 30, 1.5, "the import stays above the ceiling for 30 s", pb, G.NOTE_FP, ("6000 W", "5000 W", "30 seconds", "safety ceiling"))
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000")
    gw.put(G.GRID, "6000")
    gw.advance(29)
    gw.put(G.GRID, "4000")
    gw.advance(300)
    silent(gw, "the breach ends at 29 s", pb)
    for grid, want in (("5000", False), ("5001", True), ("4999.9", False), ("9000", True), ("-3000", False)):
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1000")
        t0 = gw.w.t
        gw.put(G.GRID, grid)
        gw.advance(40)
        if want:
            pressed_once(gw, F, t0 + 30, 1.5, f"the import {grid} W against a ceiling of 5000 W", pb)
        else:
            silent(gw, f"the import {grid} W against a ceiling of 5000 W", pb)
    for ceiling in ("0.0", "0", "unknown", "unavailable", None, "abc", "100001", "0.5", "nan", "-5"):
        gw = fp_world(gate_text, guards_text, ceiling=ceiling, grid="-500")
        gw.put(G.GRID, "200000")
        gw.advance(200)
        silent(gw, f"a ceiling of {ceiling!r} is no ceiling (the guard is inert)", pb)
    for ceiling, grid, want in (("7000", "6000", False), ("7000", "8000", True), ("3000", "4000", True), ("3000", "2999", False), ("100000", "99999", False), ("100000", "100001", True), ("1", "2", True)):
        gw = fp_world(gate_text, guards_text, ceiling=ceiling, grid="-500")
        t0 = gw.w.t
        gw.put(G.GRID, grid)
        gw.advance(40)
        if want:
            pressed_once(gw, F, t0 + 30, 1.5, f"the import {grid} W against a ceiling of {ceiling} W", pb)
        else:
            silent(gw, f"the import {grid} W against a ceiling of {ceiling} W", pb)
    for grid in ("unknown", "unavailable", "nan", "abc", None):
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1000")
        gw.put(G.GRID, "9000")
        gw.advance(10)
        gw.put(G.GRID, grid)
        gw.advance(200)
        silent(gw, f"an import that stops being readable ({grid!r}) is not a breach", pb)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="9000", lease=False)
    gw.advance(100)
    silent(gw, "an import above the ceiling with no Free Power lease", pb)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1000")
    t0 = gw.w.t
    gw.put(G.GRID, "9000")
    gw.advance(10)
    gw.put(G.GRID, "1000")
    gw.advance(10)
    gw.put(G.GRID, "9000")
    gw.advance(40)
    pressed_once(gw, F, t0 + 50, 1.5, "a breach ends at 10 s and another starts at 20 s: the count starts again", pb)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1000")
    gw.put(G.GRID, "9000")
    gw.advance(10)
    gw.d.fp_end()
    gw.advance(200)
    silent(gw, "the Free Power lease ends during the 30 s", pb)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="9000", lease=False)
    t0 = gw.w.t
    gw.d.fp_start()
    gw.advance(40)
    pressed_once(gw, F, t0 + 30, 1.5, "a lease starts while the import is above the ceiling", pb)
    harvest(gw)


# ===========================================================================================================================
# [4] a restart, a reload, a reconnect and a boot press nothing
# ===========================================================================================================================
def restart_problems(gate_text: str, guards_text: str, pb: Problems) -> None:
    orders = [("dongle first", [(G.DG_ACTIVE, "on"), (G.LATCHED, "40.0"), (G.HOLD, "held"), (G.EFF, "80")]),
              ("plan first", [(G.HOLD, "held"), (G.EFF, "80"), (G.DG_ACTIVE, "on"), (G.LATCHED, "40.0")]),
              ("interleaved", [(G.EFF, "80"), (G.DG_ACTIVE, "on"), (G.HOLD, "held"), (G.LATCHED, "40.0")])]
    for label, order in orders:
        gw = dump_world(gate_text, guards_text, hold="held", eff="80", latched=40.0)
        gw.restart_ha(gone=(G.HOLD, G.EFF, G.DG_ACTIVE, G.LATCHED))
        for eid, v in order:
            gw.put(eid, v)
            gw.advance(3)
        gw.advance(900)
        silent(gw, f"a Home Assistant restart with a hold and a reserve violation standing ({label})", pb)
        harvest(gw)
    gw = fp_world(gate_text, guards_text, leases="off", ceiling="5000", grid="1000")
    gw.restart_ha(gone=(G.TL, G.FP_ACTIVE, G.GRID, G.CEIL))
    for eid, v in ((G.FP_ACTIVE, "on"), (G.TL, "off"), (G.GRID, "1000"), (G.CEIL, "5000")):
        gw.put(eid, v)
        gw.advance(5)
    gw.advance(1500)
    silent(gw, "a Home Assistant restart while a Free Power lease runs with the time not trusted", pb)
    # a restart with the entities still readable, and an automation reload (the same thing to a guard): a standing violation is not acted on
    for label, g in (("dump", dump_world(gate_text, guards_text, hold="held", eff="80")), ("free power", fp_world(gate_text, guards_text, leases="off", ceiling="5000", grid="9000"))):
        g.restart_ha()
        g.advance(1500)
        silent(g, f"an automation reload with a standing violation ({label})", pb)
    # a reconnect of the dongle (the dongle's entities leave and come back) and a boot (nothing existed yet)
    gw = dump_world(gate_text, guards_text, hold="held", eff="80")
    for eid in (G.DG_ACTIVE, G.LATCHED):
        gw.put(eid, "unavailable")
    gw.advance(30)
    gw.put(G.DG_ACTIVE, "on")
    gw.put(G.LATCHED, "40.0")
    gw.advance(900)
    silent(gw, "a reconnect of the dongle during a Dump lease with a violation standing", pb)
    gw = G.GateWorld(gate_text, guards_text, healthy=False, poll=False, start_ha=False)
    for eid in (G.HOLD, G.EFF, G.DG_ACTIVE, G.LATCHED, G.TL, G.FP_ACTIVE, G.GRID):
        gw.put(eid, None)
    gw.ha.start()
    gw.advance(5)
    for eid, v in ((G.HOLD, "held"), (G.EFF, "80"), (G.DG_ACTIVE, "on"), (G.LATCHED, "40.0"), (G.TL, "off"), (G.FP_ACTIVE, "on"), (G.GRID, "9000")):
        gw.put(eid, v)
        gw.advance(5)
    gw.advance(900)
    silent(gw, "a boot: every entity appears for the first time with violations standing", pb)
    # the contrast, stated: a measured breach that persists after the entities return IS ended after its 30 s (a fact about the supply, not about the restart)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="9000", lease=False)
    gw.d.fp_start()
    gw.advance(2)
    gw.d.button_log.clear()
    gw.w.notifications.clear()
    gw.restart_ha(gone=(G.FP_ACTIVE, G.GRID, G.CEIL))
    t0 = gw.w.t
    for eid, v in ((G.FP_ACTIVE, "on"), (G.GRID, "9000"), (G.CEIL, "5000")):
        gw.put(eid, v)
    gw.advance(60)
    if len(gw.d.pressed(G.END_FP)) != 1 or abs(gw.d.pressed(G.END_FP)[0] - (t0 + 30)) > 1.5:
        pb.add(f"a breach that persists after the entities return is ended after its 30 s: presses at {[round(t - t0, 1) for t in gw.d.pressed(G.END_FP)]}")
    harvest(gw)
    # a template reload of the gate package (the gate entities leave and come back) touches no guard and no lease
    gw = fp_world(gate_text, guards_text, leases="off")
    gw.tw.reload()
    gw.advance(900)
    silent(gw, "a template reload", pb)


# ===========================================================================================================================
# the battery (the proofs a mutant must fail), the vocabulary, and the documents
# ===========================================================================================================================
def battery(gate_text: str = GATE_TEXT, guards_text: str = GUARDS_TEXT, parts: tuple = ("static", "gate", "plan", "script", "guards", "restart"), first_only: bool = True) -> Problems:
    pb = Problems(first_only)
    try:
        if "static" in parts:
            only = "gate" if "gate" in parts else ("guards" if "guards" in parts else "both")
            static_problems(gate_text, guards_text, only, pb)
        if "gate" in parts:
            gate_problems(gate_text, pb)
        if "plan" in parts:
            plan_problems(gate_text, pb)
        if "script" in parts:
            script_problems(gate_text, pb)
        if "guards" in parts:
            guard_problems(gate_text, guards_text, pb)
        if "restart" in parts:
            restart_problems(gate_text, guards_text, pb)
    except _Stop:
        pass
    except Exception as exc:  # noqa: BLE001 - a package that makes the model raise has failed the proof
        pb.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return pb

# ===========================================================================================================================
# run
# ===========================================================================================================================
_orig_world_init = G.GateWorld.__init__
WORLDS: list = []


def _tracked_init(self, *a, **k):
    _orig_world_init(self, *a, **k)
    WORLDS.append(self)


G.GateWorld.__init__ = _tracked_init       # every world the proofs below build is read back by [5]; restored before the mutants

print("[0] static")
sp = static_problems(GATE_TEXT, GUARDS_TEXT)
check("both files load with no repeated key; the gate has exactly the two binary sensors, the ceiling helper (no initial value) and the guarded start script, the guards exactly three automations; the state, "
      "`reasons` and `blocked_by` templates of each gate share ONE rule block; every entity read exists in the repository; the write vocabulary is pinned (each service aimed at its one entity); the "
      "guards press only the two END buttons, with no restart, reload, event or start trigger; the headers state the rules and the limits; ASCII, LF, no site value", sp == [], str(list(sp[:4])))
check("the static scans are live: each flags an injected fault (a start button in a guard, a Home Assistant start trigger, a service on a foreign entity, a site address, an initial value, a changed copy of the rule block)",
      bool(static_problems(GATE_TEXT, GUARDS_TEXT.replace("button.ecco_clock_dongle_end_dump_to_grid_restore_now", "button.ecco_clock_dongle_start_dump_to_grid_now", 1), "guards"))
      and bool(static_problems(GATE_TEXT, GUARDS_TEXT.replace("    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "    triggers:\n      - trigger: homeassistant\n        event: start\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", 1), "guards"))
      and bool(static_problems(GATE_TEXT.replace("entity_id: input_text.ecco_plan_last_result", "entity_id: input_text.ecco_foreign", 1), GUARDS_TEXT, "gate"))
      and bool(static_problems(GATE_TEXT + "# 203.0.113.5\n", GUARDS_TEXT, "gate")) and bool(static_problems(GATE_TEXT.replace("    min: 0\n    max: 100000", "    min: 0\n    initial: 0\n    max: 100000", 1), GUARDS_TEXT, "gate"))
      and bool(static_problems(GATE_TEXT.replace("tl != 'on'", "tl == 'off'", 1), GUARDS_TEXT, "gate")))

# the site renderer, the repository's packages, the firmware and the card: what the headers rely on
import ecco_site_render as render  # noqa: E402

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
for rel, text in ((GATE_REL, GATE_TEXT), (GUARDS_REL, GUARDS_TEXT)):
    spots = [m.start() for m in re.finditer(DONGLE, text)]
    try:
        rendered, counts = render.render_text(rel, text, site, render.firmware_actions(ROOT))
    except render.RenderError as exc:
        rendered, counts = "", {"error": str(exc)[:120]}
    check(f"{rel}: the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them, touches nothing else and leaves none behind",
          counts == {"entity": len(spots)} and len(spots) >= 5 and DONGLE not in rendered and "site_dongle_" in rendered, str(counts))
own_ids = package_ids(PKGS / "ecco_start_gate.yaml")
other_auto = {a["id"] for p in OTHER_PKGS.values() for a in (yaml.load(p.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}).get("automation", []) if isinstance(a, dict) and "id" in a}
guard_ids = {a["id"] for a in yaml.safe_load(GUARDS_TEXT)["automation"]}
check("the entities the gate package defines are defined nowhere else in the repository, its unique ids repeat no other template unique id, the guard automations' ids repeat no other automation id and the guards define no entity",
      own_ids == GATE_OWN and not (own_ids & set().union(*[package_ids(p) for p in OTHER_PKGS.values()])) and not (guard_ids & other_auto) and package_ids(PKGS / "ecco_lease_guards.yaml") == set()
      and not [n for n, p in OTHER_PKGS.items() if "ecco_charge_start_allowed" in p.read_text(encoding="utf-8") or "ecco_export_start_allowed" in p.read_text(encoding="utf-8")]
      and not [u for p in OTHER_PKGS.values() for u in re.findall(r"unique_id: (ecco_(?:charge|export)_start_allowed)", p.read_text(encoding="utf-8"))], str(sorted(own_ids ^ GATE_OWN)))
tt = package_ids(PKGS / "ecco_time_trust.yaml")
check("the facts the gate reads exist where the headers say: the two time sensors are the time trust package's, the plan sensors and the last-result text are the plan helpers', the poll text, the flags, the CT reading, "
      "the request numbers, the arm and the two start and two END buttons are the dongle firmware's, and the effective grid charge limit and the scheduled start script are the repository's",
      {G.TL, G.TS} <= tt and {G.HOLD, G.EFF, G.REV, G.LAST} <= package_ids(PKGS / "ecco_plan_helpers.yaml") and G.LIMIT in package_ids(PKGS / "ecco_runtime_config.yaml")
      and G.SCHED in package_ids(PKGS / "ecco_free_power_schedule.yaml")
      and {G.POLL, G.TEL, G.CFG, G.FP_ACTIVE, G.FP_OP, G.FP_SNAP, G.DG_ACTIVE, G.DG_OP, G.DG_SNAP, G.MANUAL, G.STOP, G.GRID, G.REQ, G.DUR, G.ARM, G.START_FP, G.STATUS, G.LATCHED, G.END_FP, G.END_DUMP, G.START_DUMP} <= FW_IDS)
fw = re.sub(r"\s+", " ", FW_TEXT)
check("the firmware facts the headers rely on: the END buttons restore (the Dump End requests the restore with the reason 'manual End button'; the Free Power End sets its restore request when a snapshot is valid), the "
      "Dump Stop SOC is latched from the staged number at START and is the only floor the dongle enforces (every 15 s: ends the lease when the SOC is at or below it), the active Stop SOC sensor reads NaN (unknown) "
      "unless a lease is active and updates every 5 s, the poll text is published only after a complete poll with NTP time, the CT reading is positive when importing, and the Free Power request numbers are "
      "staging values (power from 500 W in steps of 100, duration 1 to 240 minutes)",
      "request_dump_end reason: \"manual End button\"" in fw.replace("id: request_dump_end reason: \"manual End button\"", "request_dump_end reason: \"manual End button\"")
      and 'name: "END DUMP TO GRID - RESTORE NOW" id: end_dump_to_grid_button icon: "mdi:backup-restore" on_press: - script.execute: id: request_dump_end reason: "manual End button"' in fw
      and 'name: "END FREE POWER - RESTORE NOW" id: end_free_power_button icon: "mdi:backup-restore" on_press: - lambda: |- if (id(free_power_snapshot_valid)) { id(free_power_restore_requested) = true;' in fw
      and "id(dump_target_stop_soc) = (int) lroundf(id(dump_stop_soc).state);" in fw
      and "id(ecco_battery_soc).state <= (float) id(dump_target_stop_soc);" in fw and 'reason: "STOP SOC REACHED"' in fw
      and re.search(r'name: "Dump to Grid Active Stop SOC"\s+id: dump_active_stop_soc_sensor\s+unit_of_measurement: "%"\s+accuracy_decimals: 0\s+update_interval: 5s', FW_TEXT) is not None
      and "if (!id(dump_active_persisted) || id(dump_target_stop_soc) < 0) return NAN;" in fw
      and 'id(telemetry_online).publish_state(true); auto now = id(ntp_time).now(); if (now.is_valid()) { id(last_telemetry_update).publish_state(now.strftime("%Y-%m-%d %H:%M:%S"));' in fw
      and "positive = importing from grid, negative = exporting to" in re.sub(r"\s*\n\s*#\s*", " ", FW_TEXT)
      and "Positive = importing from grid, negative = exporting to grid" in (PKGS / "ecco_canonical_telemetry.yaml").read_text(encoding="utf-8")
      and re.search(r'name: "Free Power Duration"[^-]*?min_value: 1\s+max_value: 240\s+step: 1', FW_TEXT, re.S) is not None
      and re.search(r'name: "Free Power Max Charge Power"[^-]*?restore_value: true[^-]*?min_value: 500\s+max_value: \$\{ecco_inverter_tou_power_ceiling_w\}\s+step: 100', FW_TEXT, re.S) is not None)
card_fp = re.search(r"free_power: \{(.*?)\n      \},", CARD_TEXT, re.S)
card_dg = re.search(r"dump_to_grid: \{(.*?)\n        schedule:", CARD_TEXT, re.S)


def card_ids(block, keys):
    out = {}
    for k in keys:
        m = re.search(rf'\b{k}: "([a-z_]+)\.([a-z0-9_]+)"', block.group(1))
        out[k] = f"{m.group(1)}.{DONGLE}_{m.group(2)}" if m else None
    return out


cf_ = card_ids(card_fp, ("write_enable", "max_charge_power", "duration", "start", "end_restore")) if card_fp else {}
cd_ = card_ids(card_dg, ("end_restore", "active_stop_soc", "stop_soc", "active")) if card_dg else {}
check("the entities of the guarded start and the guards are the ones the Energy Actions card uses: its Free Power write enable, request numbers, start and End buttons and its Dump End button and active Stop SOC sensor; "
      "and the card's Free Power Start still presses its start button directly (the card is not changed in this step), its Dump Start is guarded only through dump_to_grid.guarded_start",
      cf_ == {"write_enable": G.ARM, "max_charge_power": G.REQ, "duration": G.DUR, "start": G.START_FP, "end_restore": G.END_FP}
      and cd_ == {"end_restore": G.END_DUMP, "active_stop_soc": G.LATCHED, "stop_soc": G.STOP, "active": G.DG_ACTIVE}
      and '@click=${() => this._callService("button", "press", { entity_id: ctx.fp.start })}' in CARD_TEXT and "guarded_start?: string;" in (ROOT / "frontend/ecco-energy-actions-card/src/config.ts").read_text(encoding="utf-8"),
      f"{cf_} {cd_}")
FREE_FLAT = re.sub(r"\s+", " ", FREE_TEXT)
DETECTOR_TEXT = (PKGS / "ecco_start_bypass_detector.yaml").read_text(encoding="utf-8")
SMR_TEXT = (PKGS / "ecco_schedule_manual_restore.yaml").read_text(encoding="utf-8")
GUARDED_DUMP = (PKGS / "ecco_dump_to_grid_guarded_start.yaml").read_text(encoding="utf-8")
check("the patterns the guarded start copies are the repository's own: the scheduled start stages the power then the duration with number.set_value, arms with switch.turn_on, waits for the confirmation, presses the same "
      "start button and ends the write enable off; the guarded Dump start writes input_text.ecco_plan_last_result as 'REFUSED <code> - <text>' with one persistent notification and presses only after its checks",
      all(s in FREE_FLAT for s in ("entity_id: number.ecco_clock_dongle_free_power_max_charge_power", "entity_id: number.ecco_clock_dongle_free_power_duration", "action: switch.turn_on", "entity_id: switch.ecco_clock_dongle_free_power_write_enable",
                                   "entity_id: button.ecco_clock_dongle_start_free_power_charge_now", "The write enable always ends off"))
      and FREE_FLAT.index("number.ecco_clock_dongle_free_power_max_charge_power") < FREE_FLAT.index("number.ecco_clock_dongle_free_power_duration")
      and "('REFUSED ' ~ refusal.split('|')[0] ~ ' - ' ~ refusal.split('|')[1])[:250]" in GUARDED_DUMP and "entity_id: input_text.ecco_plan_last_result" in GUARDED_DUMP
      and "action: button.press" in GUARDED_DUMP)
check("the limits the headers state about other packages are true: the start bypass detector knows only the scheduled run's STARTED OK (in the schedule's own result text) and the guarded Dump start as ECCO's records, "
      "never this script; smr1 tracks a request number only while the SCHEDULED start script runs; the schedule's status sensor and retry loop read the schedule's result prefixes",
      "STARTED OK - [0-9]+W for [0-9]+ min" in DETECTOR_TEXT and "script.ecco_dump_to_grid_start_guarded" in DETECTOR_TEXT and "ecco_free_power_start_guarded" not in DETECTOR_TEXT
      and "script.ecco_free_power_start_scheduled" in SMR_TEXT and "ecco_free_power_start_guarded" not in SMR_TEXT and "r.startswith('STARTED')" in FREE_TEXT and "ecco_free_power_start_guarded" not in FREE_TEXT)

# the manifest, the README, the CHANGELOG and the chain entry
man = yaml.safe_load(MANIFEST_TEXT)
stanzas = [p for p in man["home_assistant_packages"] if p["source"] in (GATE_REL, GUARDS_REL)]
check("the deployment manifest lists both packages exactly once, to /config/packages, by ssh_file_copy, with restart_required false (a reload installs each: the template entities, the input_number helpers and the "
      "scripts; the automations), after the time trust stanza, and its comment blocks say not installed, soft, the card is not changed, and the guards' separate authorisation",
      stanzas == [{"source": GATE_REL, "destination": "/config/packages/ecco_start_gate.yaml", "method": "ssh_file_copy", "restart_required": False},
                  {"source": GUARDS_REL, "destination": "/config/packages/ecco_lease_guards.yaml", "method": "ssh_file_copy", "restart_required": False}]
      and [p["source"] for p in man["home_assistant_packages"]][-3:] == ["home-assistant/packages/ecco_time_trust.yaml", GATE_REL, GUARDS_REL]
      and all(s in re.sub(r"\s*\n\s*#\s*", " ", MANIFEST_TEXT) for s in ("Start gate - sgt1 (NOT installed, NOT LIVE-PROVEN)", "THE GATE IS SOFT", "the Energy Actions card is NOT changed in this step", "reload the template entities, the input_number helpers and the scripts",
                                                                      "Lease guards - sgt1 (NOT installed, NOT LIVE-PROVEN). EACH GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "reload the automations: no restart")))
README = (PKGS / "README.md").read_text(encoding="utf-8")
README_FLAT = re.sub(r"\s+", " ", README)
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if ln.startswith("- **Shared start gate, guarded Free Power start")), "")
check("the packages README has a Start gate and lease guards section that names every entity, every code of the gate and of the script, the soft gate, that the card is not changed, the ceiling helper with no initial "
      "value and NOT_CONFIGURED, that no charger-loss factor is applied, the guards' delays and constants, what a restart does not do, the install routes (no restart), the two limits about the detector and smr1, "
      "and what is not established",
      "## Start gate and lease guards" in README and all(c in README_FLAT for c in COMMON_CODES + EXPORT_CODES + CHARGE_CODES)
      and all(s in README_FLAT for s in ("`binary_sensor.ecco_charge_start_allowed`", "`binary_sensor.ecco_export_start_allowed`", "`input_number.ecco_grid_import_ceiling_w`", "`script.ecco_free_power_start_guarded`", "ecco_lease_guard_dump_end",
                                         "ecco_lease_guard_free_power_time", "ecco_lease_guard_free_power_import", "GATE_UNREADABLE", "GATE_BLOCKED", "SCHEDULED_START_RUNNING", "LIMIT_UNREADABLE", "POWER_INVALID", "DURATION_INVALID", "GATE_CLOSED",
                                         "NOT_CONFIRMED", "LIMIT_LOWERED", "FIRMWARE_REFUSED", "START_FAILED", "NO_ANSWER", "The gate is SOFT", "is NOT changed in this step", "no initial value", "NOT_CONFIGURED", "never a target",
                                         "No charger-loss factor and no margin is applied", "5 minutes", "30 seconds", "up to 15 s", "never end a lease by themselves", "each need the owner's separate install authorisation",
                                         "reload the template entities, the input_number helpers and the scripts", "reload the automations", "never \"reload all\"", "no restart", "bpd1, pinned", "smr1", "NOT ESTABLISHED",
                                         "Recalled from Home Assistant core and not verified", "no target-reached guard", "does not use the Free Power schedule's result text", "ecco_free_power_start_blocked")))
check("the CHANGELOG has one bullet for it that says offline, nothing installed, soft, that the card is not changed, no initial value and NOT_CONFIGURED, never a target, separate authorisation for each guard, no restart "
      "(restart_required: false), the detector and smr1 limits, recalled and not verified, and names the suite and sgt1",
      BULLET != "" and all(s in BULLET for s in ("offline, nothing installed; the gate is SOFT", "ecco_start_gate.yaml", "ecco_lease_guards.yaml", "item N2", "Energy Actions card is NOT changed", "no initial value", "NOT_CONFIGURED", "never a target",
                                                  "no charger-loss factor", "separate install authorisation", "restart_required: false", "start bypass detector (pinned)", "smr1", "Recalled from Home Assistant core, not verified live",
                                                  "test_ecco_start_gate.py", "`sgt1`")) and BULLET.isascii())
sys.path.append(str(ROOT / "registry" / "tests"))
import _sgt1_scope as _sgt1  # noqa: E402
import _scope_chain as _sc  # noqa: E402

_entry = next((e for e in _sc.POST_EXPORT_ENTRIES if e.id == "sgt1"), None)
_post = [e.id for e in _sc.POST_EXPORT_ENTRIES]
check("the chain entry sgt1 follows ttr1 exactly as ttr1 followed bpd1: its scope module holds the manifest edit as an exact round-trip pair and the five added files (all present), the entry pins the manifest after the edit and "
      "declares no other file, and it is sealed after ttr1",
      _entry is not None and _post[-2:] == ["ttr1", "sgt1"] and _sgt1.add_sgt1_manifest(_sgt1.pre_sgt1_manifest(MANIFEST_TEXT)) == MANIFEST_TEXT and _sgt1.pre_sgt1_manifest(MANIFEST_TEXT) != MANIFEST_TEXT
      and _sgt1.ADDED_FILES == frozenset({GATE_REL, GUARDS_REL, "home-assistant/tests/_start_gate_sim.py", "home-assistant/tests/test_ecco_start_gate.py", "registry/tests/_sgt1_scope.py"})
      and all((ROOT / f).is_file() for f in _sgt1.ADDED_FILES) and _entry.added_files == _sgt1.ADDED_FILES and set(_entry.reverts) == {"deployment/ha-manifest.yaml"}
      and not _entry.frozen_reverts and not _entry.deltas and not _entry.op_paths_changed and not _entry.includes_added
      and _entry.checkpoints == {"deployment/ha-manifest.yaml": __import__("hashlib").sha256(MANIFEST_TEXT.encode("utf-8")).hexdigest()}, str(_post[-3:]))

print("[1] gate")
pg = Problems()
gate_problems(GATE_TEXT, pg)
check("every input one at a time and the named causes (each blocking cause named once with its entity), the poll freshness boundaries and the clock-driven re-render, the ceiling (not configured by every "
      "spelling, configured, breached, unreadable, invalid), everything unreadable at once, a seeded random sample: both gates agree with an independent model, `blocked_by`, `reasons` and the state agree, "
      "no template error", pg == [], str(list(pg[:4])))
pp = Problems()
plan_problems(GATE_TEXT, pp)
check("the REAL plan helper package feeds the export gate: a Hold battery closes it, a cancel opens it, a power cut (reserve 80) with a staged Stop SOC of 40 closes it with both causes, a reserve of 62.4 "
      "is 63 and a Stop SOC of 62 is below it, an unreadable owner reserve and an unreadable plan revision close it; the charge gate is unaffected", pp == [], str(list(pp[:4])))
gr = G.GateWorld(GATE_TEXT, None, poll=False, start_ha=False)
gr.put(G.POLL, gr.poll_text(0))
before = {e: gr.state(e) for e in (G.CHARGE_GATE, G.EXPORT_GATE)}
gr.tw.reload()
check("a template reload removes and creates the two gate sensors again and they read what they read (the gate keeps no state of its own)",
      {e: gr.state(e) for e in (G.CHARGE_GATE, G.EXPORT_GATE)} == before == {G.CHARGE_GATE: "on", G.EXPORT_GATE: "on"} and not gr.tw.errors)

print("[2] start")
ps = Problems()
script_problems(GATE_TEXT, ps)
check("the guarded Free Power start: the allowed path makes exactly the calls of the scheduled start (the two request numbers when given, the arm, the one start button, the write enable off), the refusals stage, "
      "arm and press nothing, the press-time check, the dongle's answers, a second start, and the staging equals the scheduled start's", ps == [], str(list(ps[:4])))

print("[3] guards")
pgd = Problems()
guard_problems(GATE_TEXT, GUARDS_TEXT, pgd)
check("the Dump guard, the Free Power time guard and the import guard fire only on their conditions and at their delays, press only their END button, once per violation, never on unreadable data", pgd == [], str(list(pgd[:4])))
lonely = []
for aid in ("ecco_lease_guard_dump_end", "ecco_lease_guard_free_power_time", "ecco_lease_guard_free_power_import"):
    doc = yaml.safe_load(GUARDS_TEXT)
    doc["automation"] = [a for a in doc["automation"] if a["id"] == aid]
    alone = yaml.dump(doc, sort_keys=False)
    gw = G.GateWorld(GATE_TEXT, alone, poll=False, start_ha=False)
    gw.put(G.CEIL, "5000")
    gw.put(G.GRID, "9000")
    if aid == "ecco_lease_guard_dump_end":
        gw.put(G.HOLD, "clear")
        gw.d.dump_start(latched=40.0)
        gw.ha.start()
        gw.advance(2)
        gw.put(G.HOLD, "held")
    elif aid == "ecco_lease_guard_free_power_time":
        gw.d.fp_start()
        gw.ha.start()
        gw.advance(2)
        gw.put(G.TL, "off")
    else:
        gw.put(G.GRID, "1000")
        gw.d.fp_start()
        gw.ha.start()
        gw.advance(2)
        gw.put(G.GRID, "9000")
    gw.advance(320)
    lonely.append((aid, [e.rsplit("_", 3)[-3] for _t, e in gw.d.button_log]))
check("each guard stands alone: a copy of the file with only that automation loads and ends its lease (the other two are not needed)", all(len(b) == 1 for _a, b in lonely), str(lonely))

print("[4] restart")
prs = Problems()
restart_problems(GATE_TEXT, GUARDS_TEXT, prs)
check("a restart, a reload, a reconnect and a boot with violations standing press nothing and raise nothing; a measured breach that persists after the entities return is still ended after its 30 s", prs == [], str(list(prs[:4])))

print("[5] vocabulary")
for gw in WORLDS:
    harvest(gw)
n_worlds = len(WORLDS)
WORLDS.clear()
G.GateWorld.__init__ = _orig_world_init
check(f"every service call the {n_worlds} worlds above made is one of the allowed (service, entity) pairs (the staging and the start of the scheduled start, the guarded Dump start's pattern, the two END presses, "
      "the plan last-result text and the notifications) and each of them was made; no other button was ever pressed (never a START button of Dump to Grid)",
      SEEN <= ALLOWED_SERVICES and ALLOWED_SERVICES <= SEEN and BUTTONS == {G.START_FP, G.END_DUMP, G.END_FP}, f"extra {sorted(SEEN - ALLOWED_SERVICES)} unused {sorted(ALLOWED_SERVICES - SEEN)} buttons {sorted(BUTTONS)}")



# ===========================================================================================================================
print("[6] mutation: in-memory mutants of both packages are each caught")


def mutate(text: str, old: str, new: str, mode):
    """The text with `old` replaced: mode 'all' every occurrence (the copies of a repeated rule block change together), 'one' the only occurrence, an int the nth (0-based) occurrence alone."""
    n = text.count(old)
    if mode == "all":
        return text.replace(old, new) if n >= 1 else None
    if mode == "one":
        return text.replace(old, new) if n == 1 else None
    if n <= mode:
        return None
    idx = -1
    for _ in range(mode + 1):
        idx = text.index(old, idx + 1)
    return text[:idx] + new + text[idx + len(old):]


BIND = "ecco_clock_dongle_"
# ---- the gate: a rule block repeated in every template of both sensors changes everywhere at once ('all') ----
GATE_MUTANTS = [
    ("TIME_LEASES: unavailable and unknown no longer close the gate", "tl != 'on'", "tl == 'off'", "all"),
    ("TIME_LEASES never closes the gate", "tl != 'on'", "false", "all"),
    ("TIME_LEASES is inverted", "tl != 'on'", "tl == 'on'", "all"),
    ("TIME_SCHEDULES: unavailable and unknown no longer close the gate", "ts != 'on'", "ts == 'off'", "all"),
    ("TIME_SCHEDULES never closes the gate", "ts != 'on'", "false", "all"),
    ("TIME_SCHEDULES reads the leases sensor", "ts != 'on'", "tl != 'on'", "all"),
    ("TELEMETRY_OFFLINE: unavailable no longer closes the gate", "tel != 'on'", "tel == 'off'", "all"),
    ("TELEMETRY_OFFLINE reads the configuration flag", "tel != 'on'", "cfg != 'on'", "all"),
    ("CONFIGURATION_OFFLINE: unknown no longer closes the gate", "cfg != 'on'", "cfg == 'off'", "all"),
    ("CONFIGURATION_OFFLINE never closes the gate", "cfg != 'on'", "false", "all"),
    ("an unreadable poll text is not stale", "pskew is none or (pskew | abs) > 300", "pskew is not none and (pskew | abs) > 300", "all"),
    ("the poll bound is 3000 s", "(pskew | abs) > 300,", "(pskew | abs) > 3000,", "all"),
    ("the poll bound is 299 s", "(pskew | abs) > 300,", "(pskew | abs) > 299,", "all"),
    ("a poll text from the future is never stale", "(pskew | abs) > 300,", "pskew > 300,", "all"),
    ("the poll text is read as a date only", "'%Y-%m-%d %H:%M:%S', none)", "'%Y-%m-%d', none)", "all"),
    ("the poll text is read in UTC, not in the Home Assistant zone", "as_timestamp(now()) - as_timestamp(pdt)", "as_timestamp(now()) - as_timestamp(pdt) + 3600", "all"),
    ("a busy flag closes the gate only when it reads on", "{%- if v != 'off' -%}", "{%- if v == 'on' -%}", "all"),
    ("a busy flag that reads on is described as unreadable", "if v == 'on' else e ~ ' reads '", "if v == 'xon' else e ~ ' reads '", "all"),
    ("FREE_POWER_ACTIVE reads the Dump flag", "('binary_sensor.ecco_clock_dongle_free_power_active', 'FREE_POWER_ACTIVE'", "('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'FREE_POWER_ACTIVE'", "all"),
    ("FREE_POWER_OPERATION reads the snapshot flag", "('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'FREE_POWER_OPERATION'", "('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'FREE_POWER_OPERATION'", "all"),
    ("FREE_POWER_SNAPSHOT reads the operation flag", "('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'FREE_POWER_SNAPSHOT'", "('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'FREE_POWER_SNAPSHOT'", "all"),
    ("DUMP_ACTIVE reads the Free Power flag", "('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'DUMP_ACTIVE'", "('binary_sensor.ecco_clock_dongle_free_power_active', 'DUMP_ACTIVE'", "all"),
    ("DUMP_OPERATION reads the snapshot flag", "('binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress', 'DUMP_OPERATION'", "('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'DUMP_OPERATION'", "all"),
    ("DUMP_SNAPSHOT reads the operation flag", "('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'DUMP_SNAPSHOT'", "('binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress', 'DUMP_SNAPSHOT'", "all"),
    ("MANUAL_WRITE reads the Dump operation flag", "('binary_sensor.ecco_clock_dongle_manual_write_in_progress', 'MANUAL_WRITE'", "('binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress', 'MANUAL_WRITE'", "all"),
    ("a busy code is renamed", "'DUMP_SNAPSHOT', 'a saved", "'DUMP_SNAPSHOTS', 'a saved", "all"),
    ("an unreadable busy flag does not say so", "', so it is not known whether ' ~ what", "' ~ what", "all"),
    ("OVERRIDE_ACTIVE reads another word", "hold == 'held'", "hold == 'holding'", "all"),
    ("OVERRIDE_UNREADABLE counts only unknown", "hold not in ['held', 'clear']", "hold == 'unknown'", "all"),
    ("OVERRIDE_UNREADABLE counts held too", "hold not in ['held', 'clear']", "hold != 'clear'", "all"),
    ("the hold is read from the reserve sensor", "{%- set hold = states('sensor.ecco_plan_export_hold') -%}", "{%- set hold = states('sensor.ecco_plan_effective_reserve') -%}", "all"),
    ("a reserve of exactly 100 is invalid", "(r >= 0 and r <= 100)", "(r >= 0 and r < 100)", "all"),
    ("a reserve above 100 is valid", "(r >= 0 and r <= 100)", "(r >= 0)", "all"),
    ("an unreadable reserve reads 0", "rraw | float(-1)", "rraw | float(0)", "all"),
    ("an invalid and an unreadable reserve are swapped", "(-1 if r < 0 else -2)", "(-2 if r < 0 else -1)", "all"),
    ("RESERVE_INVALID is never raised", "('RESERVE_INVALID', reserve == -2,", "('RESERVE_INVALID', false,", "all"),
    ("RESERVE_UNKNOWN is never raised", "('RESERVE_UNKNOWN', reserve == -1,", "('RESERVE_UNKNOWN', false,", "all"),
    ("a staged Stop SOC above 100 is valid", "(s >= 0 and s <= 100)", "(s >= 0)", "all"),
    ("an unreadable Stop SOC reads 0", "sraw | float(-1)", "sraw | float(0)", "all"),
    ("STOP_SOC_UNREADABLE is never raised", "('STOP_SOC_UNREADABLE', stop < 0,", "('STOP_SOC_UNREADABLE', false,", "all"),
    ("a Stop SOC equal to the reserve is refused", "stop >= 0 and reserve >= 0 and stop < reserve", "stop >= 0 and reserve >= 0 and stop <= reserve", "all"),
    ("a Stop SOC below the reserve is never refused", "stop >= 0 and reserve >= 0 and stop < reserve", "false", "all"),
    ("the plan revision may be a fraction", "and (rv % 1) == 0", "", "all"),
    ("the plan revision may be negative", "rv >= 0 and rv < 1000000000", "rv < 1000000000", "all"),
    ("the plan revision may be huge", "rv >= 0 and rv < 1000000000", "rv >= 0", "all"),
    ("an unreadable plan revision does not close the gate", "('REVISION_UNREADABLE', not rev_ok,", "('REVISION_UNREADABLE', false,", "all"),
    ("the revision is read from the reserve sensor", "states('input_number.ecco_plan_revision')", "states('sensor.ecco_plan_effective_reserve')", "all"),
    ("a ceiling of 0.5 W is valid", "cf >= 1 and", "cf > 0 and", "all"),
    ("a ceiling above 100000 W is valid", "cf <= 100000", "cf <= 1000000", "all"),
    ("a ceiling of 0 is invalid, not unset", "{%- set c_unset = cr in bad or (cf is number and cf == 0) -%}", "{%- set c_unset = cr in bad -%}", "all"),
    ("a ceiling that is unknown is invalid, not unset", "{%- set c_unset = cr in bad or (cf is number and cf == 0) -%}", "{%- set c_unset = (cf is number and cf == 0) -%}", "all"),
    ("an invalid ceiling is read as no ceiling", "('IMPORT_CEILING_INVALID', (not c_unset) and (not c_ok),", "('IMPORT_CEILING_INVALID', false,", "all"),
    ("an unset ceiling is invalid", "('IMPORT_CEILING_INVALID', (not c_unset) and (not c_ok),", "('IMPORT_CEILING_INVALID', not c_ok,", "all"),
    ("an unreadable import is not a cause", "('IMPORT_UNREADABLE', c_ok and (not gi_ok),", "('IMPORT_UNREADABLE', false,", "all"),
    ("an unreadable import is a cause even with no ceiling", "('IMPORT_UNREADABLE', c_ok and (not gi_ok),", "('IMPORT_UNREADABLE', not gi_ok,", "all"),
    ("an unreadable request is not a cause", "('REQUEST_UNREADABLE', c_ok and (not rq_ok),", "('REQUEST_UNREADABLE', false,", "all"),
    ("a request of 0 is readable", "rq is number and rq == rq and rq > 0 and rq < 1000000000", "rq is number and rq == rq and rq >= 0 and rq < 1000000000", "all"),
    ("a huge request is readable", "rq == rq and rq > 0 and rq < 1000000000", "rq == rq and rq > 0", "all"),
    ("a huge import is readable", "gi == gi and (gi | abs) < 1000000000", "gi == gi", "all"),
    ("a request that exactly fills the headroom is refused", "rq > head,", "rq >= head,", "all"),
    ("a request above the headroom is never refused", "rq_ok and rq > head,", "rq_ok and false,", "all"),
    ("an export of the house counts as headroom", "[gi, 0] | max", "[gi] | max", "all"),
    ("the headroom ignores the house import", "(cf - ([gi, 0] | max))", "cf", "all"),
    ("the ceiling is read from the wrong helper", "states('input_number.ecco_grid_import_ceiling_w')", "states('input_number.ecco_plan_revision')", "all"),
    ("the import is read from the house power", "states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp')", "states('sensor.ecco_clock_dongle_ecco_load_power')", "all"),
    ("the request is read from the duration", "states('number.ecco_clock_dongle_free_power_max_charge_power')", "states('number.ecco_clock_dongle_free_power_duration')", "all"),
    ("the not-configured note is never given", "{%- if c_unset -%}", "{%- if false -%}", "all"),
    ("the not-configured note blocks (it is a code)", "{%- set ns.n = ns.n + ['NOTE IMPORT_NOT_CONFIGURED:", "{%- set ns.c = ns.c + ['IMPORT_NOT_CONFIGURED'] -%}{%- set ns.n = ns.n + ['NOTE IMPORT_NOT_CONFIGURED:", "all"),
    ("the note is renamed", "NOTE IMPORT_NOT_CONFIGURED:", "NOTE IMPORT_UNSET:", "all"),
    ("the state is always on", "{{ (ns.c | length) == 0 }}", "{{ true }}", "all"),
    ("the state is always off", "{{ (ns.c | length) == 0 }}", "{{ false }}", "all"),
    ("a note blocks the state", "{{ (ns.c | length) == 0 }}", "{{ ((ns.c + ns.n) | length) == 0 }}", "all"),
    ("the reasons drop the notes when the gate is closed", "{{ (ns.b + ns.n) if (ns.c | length) > 0", "{{ (ns.b) if (ns.c | length) > 0", "all"),
    ("the reasons say nothing when the gate is on", "(['ALLOWED: every check passed'] + ns.n)", "(ns.n)", "all"),
    ("the allowed text is changed", "['ALLOWED: every check passed']", "['OK']", "all"),
    ("blocked_by lists the codes in reverse", "{{ ns.c }}", "{{ ns.c | reverse | list }}", "all"),
    ("blocked_by is empty", "{{ ns.c }}", "{{ [] }}", "all"),
    ("a reason does not carry its code", "{%- set ns.b = ns.b + [code ~ ': ' ~ text] -%}", "{%- set ns.b = ns.b + [text] -%}", "all"),
    ("the reasons list a code twice", "{%- set ns.b = ns.b + [code ~ ': ' ~ text] -%}", "{%- set ns.b = ns.b + [code ~ ': ' ~ text, code ~ ': ' ~ text] -%}", "all"),
    ("the gate is no longer re-rendered by the clock (no now())", "as_timestamp(now()) - as_timestamp(pdt)", "1795694400 - as_timestamp(pdt)", "all"),
    # one copy of the rule block changed alone (the copies must stay identical)
    ("only the reasons copy of the charge sensor ignores time trust", "tl != 'on'", "false", 1),
    ("only the blocked_by copy of the charge sensor ignores telemetry", "tel != 'on'", "false", 2),
    ("only the state copy of the export sensor ignores the configuration flag", "cfg != 'on'", "false", 3),
    ("only the blocked_by copy of the export sensor ignores the hold", "hold == 'held'", "false", 1),
]
# ---- the guarded start (one occurrence each) ----
SCRIPT_MUTANTS = [
    ("the unreadable gate is not refused", "{%- if gate_state not in ['on', 'off'] -%}GATE_UNREADABLE", "{%- if false -%}GATE_UNREADABLE", "one"),
    ("a closed gate is not refused before staging (no deferral rule)", "{%- elif gate_state == 'off' and not gate_deferrable -%}GATE_BLOCKED", "{%- elif false -%}GATE_BLOCKED", "one"),
    ("a closed gate is always refused, also by the request-dependent codes", "{%- elif gate_state == 'off' and not gate_deferrable -%}GATE_BLOCKED", "{%- elif gate_state == 'off' -%}GATE_BLOCKED", "one"),
    ("the deferral needs no explicit power", "gate_state == 'off' and power_given and req_power != staged_power and", "gate_state == 'off' and", "one"),
    ("the deferral needs no difference from the staged power", "power_given and req_power != staged_power and", "power_given and", "one"),
    ("the deferral also covers the time trust", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE'])", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE', 'TIME_LEASES'])", "one"),
    ("the deferral does not cover an unreadable request", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE'])", "reject('in', ['IMPORT_HEADROOM'])", "one"),
    ("the deferral does not cover the headroom", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE'])", "reject('in', ['REQUEST_UNREADABLE'])", "one"),
    ("a scheduled start that cannot be read does not refuse", "{%- elif scheduled_state != 'off' -%}", "{%- elif scheduled_state == 'on' -%}", "one"),
    ("a running scheduled start does not refuse", "{%- elif scheduled_state != 'off' -%}", "{%- elif false -%}", "one"),
    ("a limit below 500 W is read", "limit >= 500 and limit <= 100000", "limit >= 0 and limit <= 100000", "one"),
    ("a limit above 100000 W is read", "limit >= 500 and limit <= 100000", "limit >= 500", "one"),
    ("the limit is not checked", "{%- elif not (limit >= 500 and limit <= 100000) -%}", "{%- elif false -%}", "one"),
    ("a power below 500 W is allowed", "req_power >= 500 and req_power <= limit", "req_power >= 100 and req_power <= limit", "one"),
    ("a power above the limit is allowed", "req_power >= 500 and req_power <= limit and", "req_power >= 500 and", "one"),
    ("a power that is not a multiple of 100 is allowed", "and (req_power % 100) == 0", "", "one"),
    ("a duration of 0 is allowed", "req_duration >= 1 and", "req_duration >= 0 and", "one"),
    ("a duration above 240 is allowed", "req_duration <= 240", "req_duration <= 2400", "one"),
    ("a fractional duration is allowed", "and (req_duration % 1) == 0", "", "one"),
    ("a given power of 0 is read as not given", "(power_w | default('') | string | trim) != ''", "(power_w | default('', true) | string | trim) != ''", "one"),
    ("a given duration of 0 is read as not given", "(duration_minutes | default('') | string | trim) != ''", "(duration_minutes | default('', true) | string | trim) != ''", "one"),
    ("infinity is kept as a number", "{{ (x if (x >= 0 and x <= 1000000) else -1) if power_given else staged_power }}", "{{ x if power_given else staged_power }}", "one"),
    ("the power is always staged", "value_template: \"{{ req_power != staged_power }}\"", "value_template: \"{{ true }}\"", "one"),
    ("the duration is always staged", "value_template: \"{{ req_duration != staged_duration }}\"", "value_template: \"{{ true }}\"", "one"),
    ("the power is never staged", "value_template: \"{{ req_power != staged_power }}\"", "value_template: \"{{ false }}\"", "one"),
    ("the power number is given the duration", "                  value: \"{{ req_power | int(0) }}\"", "                  value: \"{{ req_duration | int(0) }}\"", "one"),
    ("the duration number is given the power", "                  value: \"{{ req_duration | int(0) }}\"", "                  value: \"{{ req_power | int(0) }}\"", "one"),
    ("the duration is staged into the power number", "entity_id: number.ecco_clock_dongle_free_power_max_charge_power\n                data:", "entity_id: number.ecco_clock_dongle_free_power_duration\n                data:", "one"),
    ("the write enable is turned off instead of on", "- action: switch.turn_on", "- action: switch.turn_off", "one"),
    ("the arm wait is one second", "timeout: \"00:00:05\"", "timeout: \"00:00:01\"", "one"),
    ("the settle delay before the press-time check is zero", "- delay:\n              seconds: 1\n", "- delay:\n              seconds: 0\n", "one"),
    ("the press-time gate check is dropped", "{%- if g != 'on' -%}GATE_CLOSED", "{%- if false -%}GATE_CLOSED", "one"),
    ("the press-time scheduled check is dropped", "{%- elif states('script.ecco_free_power_start_scheduled') != 'off' -%}SCHEDULED_START_RUNNING", "{%- elif false -%}SCHEDULED_START_RUNNING", "one"),
    ("the press-time confirmation is dropped", "{%- elif not (is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on') and", "{%- elif false and (is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on') and", "one"),
    ("the press-time limit check is dropped", "{%- elif not ((states('sensor.ecco_config_maximum_grid_charge_power') | float(-1)) >= req_power) -%}LIMIT_LOWERED", "{%- elif false -%}LIMIT_LOWERED", "one"),
    ("the press-time limit check passes an unreadable limit", "(states('sensor.ecco_config_maximum_grid_charge_power') | float(-1)) >= req_power", "(states('sensor.ecco_config_maximum_grid_charge_power') | float(99999)) >= req_power", "one"),
    ("the Dump start button is pressed", "entity_id: button.ecco_clock_dongle_start_free_power_charge_now", "entity_id: button.ecco_clock_dongle_start_dump_to_grid_now", "one"),
    ("the answer wait is one second", "timeout: \"00:00:15\"", "timeout: \"00:00:01\"", "one"),
    ("a refusal at the dongle's gate counts as a begun start", "and not states('sensor.ecco_clock_dongle_free_power_status').startswith('REJECTED')", "", "one"),
    ("the transaction wait is one second", "timeout: \"00:02:00\"", "timeout: \"00:00:01\"", "one"),
    ("a press with no answer is retried as a refusal", "value_template: \"{{ answered and not began }}\"", "value_template: \"{{ not began }}\"", "one"),
    ("the success text is the schedule's proof text", "'STARTED free_power at '", "'STARTED OK - '", "one"),
    ("the refusal text is renamed", "('REFUSED ' ~ refusal.split('|')[0]", "('REJECTED ' ~ refusal.split('|')[0]", "one"),
    ("the press-time refusal text is renamed", "('REFUSED ' ~ press_block.split('|')[0]", "('REJECTED ' ~ press_block.split('|')[0]", "one"),
    ("a failure after the press is written as a refusal", "('FAILED START_FAILED - ", "('REFUSED START_FAILED - ", "one"),
    ("the notification id is changed", "notification_id: ecco_free_power_start_blocked\n                  title: \"ECCO: Charge Battery (Free Power) was not started\"\n                  message: \"{{ refusal.split('|')[1] }}", "notification_id: ecco_free_power_start_refused\n                  title: \"ECCO: Charge Battery (Free Power) was not started\"\n                  message: \"{{ refusal.split('|')[1] }}", "one"),
    ("the refusal notification is not raised", "message: \"{{ refusal.split('|')[1] }} (reason {{ refusal.split('|')[0] }})\"", "message: \"{{ refusal.split('|')[1] }}\"", "one"),
    ("a success does not clear the notification", "- action: persistent_notification.dismiss", "- action: persistent_notification.create", "one"),
    ("the write enable does not end off", "      # The write enable always ends off (the safe state: it only permits a START).\n      - action: switch.turn_off", "      # The write enable always ends off (the safe state: it only permits a START).\n      - action: switch.turn_on", "one"),
    ("the final write enable is another switch", "      - action: switch.turn_off\n        continue_on_error: true\n        target:\n          entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "      - action: switch.turn_off\n        continue_on_error: true\n        target:\n          entity_id: switch.ecco_clock_dongle_dump_to_grid_write_enable\n", "one"),
    ("the unanswered press leaves the write enable on", "                  - action: switch.turn_off\n                    continue_on_error: true\n                    target:\n                      entity_id: switch.ecco_clock_dongle_free_power_write_enable\n                  - wait_template: \"{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}\"", "                  - action: switch.turn_on\n                    continue_on_error: true\n                    target:\n                      entity_id: switch.ecco_clock_dongle_free_power_write_enable\n                  - wait_template: \"{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}\"", "one"),
    ("the mode is queued (two starts at once would both run)", "    mode: single\n    fields:", "    mode: queued\n    fields:", "one"),
    ("the result text is the schedule's helper", "entity_id: input_text.ecco_plan_last_result\n                data:\n                  value: \"{{ ('REFUSED ' ~ refusal", "entity_id: input_text.ecco_free_power_schedule_last_result\n                data:\n                  value: \"{{ ('REFUSED ' ~ refusal", "one"),
]
# ---- the guards ----
GUARD_MUTANTS = [
    ("the Dump guard waits for a hold that never comes", "        to: \"held\"\n        id: hold", "        to: \"clear\"\n        id: hold", "one"),
    ("the Dump guard ignores a change of the reserve", "        to: ~\n        id: reserve", "        to: \"nan\"\n        id: reserve", "one"),
    ("the Dump guard ignores a lease that starts", "        to: \"on\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING. A Home Assistant start", "        to: \"off\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING. A Home Assistant start", "one"),
    ("the Dump guard acts on a change from unavailable or unknown", "{{ trigger.from_state is not none and trigger.from_state.state not in ['unavailable', 'unknown'] }}", "{{ true }}", "one"),
    ("the Dump guard acts on a change from unknown", "trigger.from_state.state not in ['unavailable', 'unknown'] }}", "trigger.from_state.state not in ['unavailable'] }}", "one"),
    ("the Dump guard acts on a change from unavailable", "trigger.from_state.state not in ['unavailable', 'unknown'] }}", "trigger.from_state.state not in ['unknown'] }}", "one"),
    ("the Dump guard acts on a change from nothing", "{{ trigger.from_state is not none and trigger.from_state.state not in", "{{ trigger.from_state is none or trigger.from_state.state not in", "one"),
    ("the Dump guard acts with no lease", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        state: \"on\"\n    actions:", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        state: \"off\"\n    actions:", "one"),
    ("the Dump guard does not wait for the latched Stop SOC", "timeout: \"00:00:15\"", "timeout: \"00:00:01\"", "one"),
    ("the Dump guard waits a minute for the latched Stop SOC", "timeout: \"00:00:15\"", "timeout: \"00:01:00\"", "one"),
    ("the Dump guard's wait ignores a hold", "             or is_state('sensor.ecco_plan_export_hold', 'held')\n", "", "one"),
    ("the Dump guard's wait ignores the end of the lease", "          {{ not is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')\n             or is_state('sensor.ecco_plan_export_hold', 'held')", "          {{ is_state('sensor.ecco_plan_export_hold', 'held')", "one"),
    ("the Dump guard ends a lease when the reserve equals its Stop SOC", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ reserve >= 0 and latched >= 0 and reserve >= latched }}\"", "one"),
    ("the Dump guard judges the reserve with no latched value", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ reserve >= 0 and reserve > latched }}\"", "one"),
    ("the Dump guard never judges the reserve", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ false }}\"", "one"),
    ("the Dump guard needs both a hold and a reserve", "value_template: \"{{ lease and (held_now or above) }}\"", "value_template: \"{{ lease and (held_now and above) }}\"", "one"),
    ("the Dump guard ends a lease on any hold reading but clear", "held_now: \"{{ hold == 'held' }}\"", "held_now: \"{{ hold != 'clear' }}\"", "one"),
    ("the Dump guard accepts a reserve above 100", "{{ r if (r >= 0 and r <= 100) else (-1 if r < 0 else -2) }}", "{{ r if (r >= 0) else (-1 if r < 0 else -2) }}", "one"),
    ("the Dump guard reads an unreadable latched Stop SOC as 0", "{%- set s = states('sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc') | float(-1) -%}", "{%- set s = states('sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc') | float(0) -%}", "one"),
    ("the Dump guard presses the Free Power End button", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now", "one"),
    ("the Dump guard presses the Dump Start button", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "entity_id: button.ecco_clock_dongle_start_dump_to_grid_now", "one"),
    ("the Dump guard presses nothing", "      - action: button.press\n        target:\n          entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now\n", "", "one"),
    ("the Dump guard does not pause after a press", "      - delay: \"00:01:00\"\n\n  - id: ecco_lease_guard_free_power_time", "      - delay: \"00:00:01\"\n\n  - id: ecco_lease_guard_free_power_time", "one"),
    ("the Dump guard pauses ten minutes after a press", "      - delay: \"00:01:00\"\n\n  - id: ecco_lease_guard_free_power_time", "      - delay: \"00:10:00\"\n\n  - id: ecco_lease_guard_free_power_time", "one"),
    ("the Dump guard raises no notification", "          notification_id: ecco_lease_guard_dump_ended", "          notification_id: ecco_lease_guard_dump_end", "one"),
    ("the Dump guard's notification does not say why", "{% if held_now %}a Hold battery, Skip tonight or Prepare for power cut turned on", "{% if held_now %}something happened", "one"),
    ("the Dump guard is not single", "    mode: single\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "    mode: queued\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "one"),
    ("the time guard fires when the leases sensor turns on", "        to: \"off\"\n        id: trust_lost", "        to: \"on\"\n        id: trust_lost", "one"),
    ("the time guard ignores a lease that starts", "        to: \"on\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING (on or off)", "        to: \"off\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING (on or off)", "one"),
    ("the time guard acts on a change from unavailable", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off', 'unavailable', 'unknown'] }}", "one"),
    ("the time guard acts on a change from nothing", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ trigger.from_state is none or trigger.from_state.state in ['on', 'off'] }}", "one"),
    ("the time guard acts on any trigger", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ true }}", "one"),
    ("the time guard acts with no lease", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n        state: \"on\"\n      # The sensor must READ off now", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n        state: \"off\"\n      # The sensor must READ off now", "one"),
    ("the time guard also counts from a sensor that cannot be read", "{{ is_state('binary_sensor.ecco_time_trusted_for_leases', 'off') }}\"\n    actions:", "{{ not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\"\n    actions:", "one"),
    ("the time guard waits one minute", "timeout: \"00:05:00\"", "timeout: \"00:01:00\"", "one"),
    ("the time guard waits ten minutes", "timeout: \"00:05:00\"", "timeout: \"00:10:00\"", "one"),
    ("the time guard's wait ignores the recovery of the time", "             or is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\n        timeout: \"00:05:00\"", "             }}\n        timeout: \"00:05:00\"", "one"),
    ("the time guard's wait ignores the end of the lease", "          {{ not is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             or is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "          {{ is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "one"),
    ("the time guard ends the lease although the time is trusted again", "          {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             and not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "          {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') }}", "one"),
    ("the time guard ends the lease only while the sensor reads off", "             and not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\n      - action: button.press", "             and is_state('binary_sensor.ecco_time_trusted_for_leases', 'off') }}\n      - action: button.press", "one"),
    ("the time guard presses the Dump End button", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now\n      - action: persistent_notification.create\n        data:\n          notification_id: ecco_lease_guard_free_power_ended\n          title: \"ECCO: a Free Power lease was ended by the lease guard (time not trusted)\"", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now\n      - action: persistent_notification.create\n        data:\n          notification_id: ecco_lease_guard_free_power_ended\n          title: \"ECCO: a Free Power lease was ended by the lease guard (time not trusted)\"", "one"),
    ("the time guard does not pause after a press", "      - delay: \"00:01:00\"\n\n  - id: ecco_lease_guard_free_power_import", "      - delay: \"00:00:01\"\n\n  - id: ecco_lease_guard_free_power_import", "one"),
    ("the time guard's notification does not say why", "has not read on for 5 minutes (it reads", "has changed (it reads", "one"),
    ("the import guard treats a ceiling of 0.5 W as a ceiling", "c >= 1 and c <= 100000", "c > 0 and c <= 100000", "all"),
    ("the import guard treats a ceiling above 100000 W as a ceiling", "c >= 1 and c <= 100000", "c >= 1", "all"),
    ("the import guard ends a lease at exactly the ceiling", "g is number and g == g and g > c", "g is number and g == g and g >= c", "all"),
    ("the import guard compares the import with a fixed number", "g is number and g == g and g > c", "g is number and g == g and g > 5000", "all"),
    ("the import guard acts with no lease", "{%- set breached = is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and c >= 1", "{%- set breached = c >= 1", "all"),
    ("the import guard acts on an unreadable import", "and g is number and g == g and g > c", "and (g is not number or g > c)", "all"),
    ("the import guard waits ten seconds", "timeout: \"00:00:30\"", "timeout: \"00:00:10\"", "one"),
    ("the import guard waits five minutes", "timeout: \"00:00:30\"", "timeout: \"00:05:00\"", "one"),
    ("the import guard ends a lease although the breach is over", "      - condition: template\n        value_template: >-\n          {%- set c = states('input_number.ecco_grid_import_ceiling_w') | float(0) -%}\n          {%- set g = states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp') | float(none) -%}\n          {%- set breached = is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and c >= 1 and c <= 100000 and g is number and g == g and g > c -%}\n          {{ breached }}\n", "      - condition: template\n        value_template: \"{{ true }}\"\n", "one"),
    ("the import guard's wait never ends early", "          {{ not breached }}\n        timeout: \"00:00:30\"", "          {{ false }}\n        timeout: \"00:00:30\"", "one"),
    ("the import guard presses the Dump End button", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now\n      - action: persistent_notification.create\n        data:\n          notification_id: ecco_lease_guard_free_power_ended\n          title: \"ECCO: a Free Power lease was ended by the lease guard (grid import above the ceiling)\"", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now\n      - action: persistent_notification.create\n        data:\n          notification_id: ecco_lease_guard_free_power_ended\n          title: \"ECCO: a Free Power lease was ended by the lease guard (grid import above the ceiling)\"", "one"),
    ("the import guard does not pause after a press", "      - delay: \"00:01:00\"\n", "      - delay: \"00:00:01\"\n", 2),
    ("the import guard reads the ceiling from another helper", "states('input_number.ecco_grid_import_ceiling_w') | float(0)", "states('input_number.ecco_plan_revision') | float(0)", "all"),
    ("the import guard reads the house power", "states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp') | float(none)", "states('sensor.ecco_clock_dongle_ecco_load_power') | float(none)", "all"),
]
# ---- the headers (the stated rules) ----
HEADER_MUTANTS = [
    ("the gate header no longer says the gate is soft", "THE GATE IS SOFT.", "THE GATE IS FIRM.", "gate", "one"),
    ("the gate header no longer says the card is unchanged", "THE CARD IS NOT CHANGED IN", "THE CARD IS CHANGED IN", "gate", "one"),
    ("the gate header no longer says no margin is applied", "NO charger-loss factor and NO margin is applied", "A charger-loss factor and a margin are applied", "gate", "one"),
    ("the gate header no longer says why the schedule's result text is not reused", "does NOT reuse the Free Power schedule's result text", "reuses the Free Power schedule's result text", "gate", "one"),
    ("the guards header no longer asks for a separate authorisation", "EACH GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "EACH GUARD IS INSTALLED WITH THE GATE", "guards", "one"),
    ("the guards header no longer says a restart never ends a lease", "never end a lease by themselves", "may end a lease", "guards", "one"),
    ("the guards header no longer says END is always allowed", "END is always allowed", "END is sometimes refused", "guards", "one"),
]

ALL = [(lbl, "gate", old, new, mode) for lbl, old, new, mode in GATE_MUTANTS + SCRIPT_MUTANTS] + [(lbl, "guards", old, new, mode) for lbl, old, new, mode in GUARD_MUTANTS] \
    + [(lbl, wh, old, new, mode) for lbl, old, new, wh, mode in HEADER_MUTANTS]
labels = [m[0] for m in ALL]
check("every mutant has a unique label", len(labels) == len(set(labels)), str([lb for lb in labels if labels.count(lb) > 1][:3]))
killed = 0
for label, which, old, new, mode in ALL:
    base = GATE_TEXT if which == "gate" else GUARDS_TEXT
    mutated = mutate(base, old, new, mode)
    if mutated is None or mutated == base:
        check(f"mutant anchor: {label}", False, f"anchor found {base.count(old)}x (mode {mode})")
        continue
    found = battery(mutated, GUARDS_TEXT, ("static", "gate", "plan", "script")) if which == "gate" else battery(GATE_TEXT, mutated, ("static", "guards", "restart"))
    if found:
        killed += 1
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(ALL)} mutants of the gate, the guarded start, the three guards and the stated rules, all caught", killed == len(ALL) and len(ALL) >= 150, f"{killed}/{len(ALL)}")
_harmless = GATE_TEXT.replace("# WHY. The same reserve", "# WHY (restated). The same reserve")
check("the full battery holds on the packages as written, and a harmless rewrite (a comment) survives while a rewrite of a pinned header rule does not",
      battery(GATE_TEXT, GUARDS_TEXT, first_only=False) == [] and _harmless != GATE_TEXT and battery(_harmless, GUARDS_TEXT, ("static",)) == []
      and battery(GATE_TEXT.replace("THE GATE IS SOFT.", "THE GATE IS FIRM."), GUARDS_TEXT, ("static",)) != [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll start gate checks passed.")
print("These prove the packages against a model of Home Assistant and the dongle; nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.")
