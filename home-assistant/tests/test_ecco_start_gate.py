"""Offline suite for the shared START GATE, the GUARDED FREE POWER START and the IN-LEASE END GUARDS:

  home-assistant/packages/ecco_start_gate.yaml                      two template binary sensors (binary_sensor.ecco_charge_start_allowed, binary_sensor.ecco_export_start_allowed),
                                                                    one helper (the grid-import ceiling, no initial value) and script.ecco_free_power_start_guarded
  home-assistant/packages/ecco_lease_guard_dump.yaml                one automation that only ever presses an existing END button (Dump to Grid)
  home-assistant/packages/ecco_lease_guard_free_power_time.yaml     one automation, the same for Free Power, when the time is not trusted for 5 minutes
  home-assistant/packages/ecco_lease_guard_free_power_import.yaml   one automation, the same for Free Power, when the grid import stays above the ceiling for 30 seconds

Item N2 of the architecture reconciliation: ONE start gate for both functions built only from facts ECCO already has (time trust, telemetry, no open recovery obligation, the other
function not running, the Stage 3 facts for Export, an import headroom check for Charge that is DISABLED until the owner supplies a ceiling), a guarded Free Power start bound to it,
and guards that end a lease whose plan, time or supply no longer allows it. The HA gates are SOFT: the dongle's own Start button bypasses them until a firmware gate exists. This
suite proves the REAL package YAML against a model of Home Assistant and the dongle (home-assistant/tests/_start_gate_sim.py, on the repository's FPS1 interpreter, the template model
of the time trust suite and the Free Power model of the schedule suites); nothing was installed, nothing was written live, nothing here binds the dongle's own Start button.

  [0] static      the files load with no repeated key; the entities, helper, script and automations they define and nothing else (one automation in each guard file); every entity they read
                  exists in the repository; the write vocabulary is pinned (the only services, each aimed at its one entity); the state, `reasons` and `blocked_by` templates share ONE rule
                  block; the guards press only the two END buttons and have no restart, reload or start trigger; the two Free Power guards carry the same verdict; the headers state the rules
                  and the limits; ASCII, LF, no site value; the site renderer; the firmware and card facts the headers rely on (the Free Power END is the operator's retry, the Dump END is
                  not); the manifest (four stanzas), README and CHANGELOG say the same
  [1] gate        every input one at a time (off, unavailable, unknown, missing and the other odd values), each blocking cause named once with its entity; the boundaries of the poll
                  freshness; the Stage 3 cases (hold, reserve, Stop SOC, revision); the import ceiling (a readable 0 is not configured, whatever its spelling; unknown, unavailable and missing
                  BLOCK; then configured: the boundary, a breach, an unreadable import or request, an invalid ceiling); both gates against an independent model over every single deviation and
                  a seeded random sample; the state, `reasons` and `blocked_by` always agree; the real plan helper package feeding the gate
  [2] start       the guarded Free Power start: refusals (nothing staged, armed, pressed or switched; one notification; the stable code), the allowed path (exactly the calls the scheduled start
                  and the card make: the two request numbers, the arm, the one start button), explicit and staged requests, the press-time recheck (and the staged values this run replaced
                  put back, once, read back), the answers of the dongle (refused, failed, no answer), a second start, the equality with the scheduled start's staging, and a write enable that
                  ends off only when this run turned it on
  [3] guards      the Dump guard (a hold turns on, also from the hold sensor's own unknown; the reserve rises above the latched Stop SOC; a lease that starts under a violation), the Free
                  Power time guard (5 minutes) and the import guard (30 seconds): each fires only on its condition and at its delay, presses only its END button, never on unreadable data,
                  once per violation; the Free Power guards press ONLY for a verified running lease (every status the firmware can publish but one refuses; no operation in progress; an end
                  time in the future; END not pressed in this lease, by either guard or the operator) and at most once per lease, and a restore owed, blocked or locked out is never pressed
  [4] restart     a Home Assistant restart, a template reload, a reconnect of the dongle and a boot, with violations standing, press nothing and raise nothing
  [5] vocabulary  every service call every world above made is one of the allowed (service, entity) pairs, and each of them was made; no other button was ever pressed
  [6] mutation    in-memory mutants of the four packages (the Free Power verdict in both guard files), each caught by the proof designed for it

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
GUARD_NAMES = ("dump", "time", "import")           # the three lease guards, one package file and one automation each, always in this order
GUARDS_REL = ("home-assistant/packages/ecco_lease_guard_dump.yaml", "home-assistant/packages/ecco_lease_guard_free_power_time.yaml",
              "home-assistant/packages/ecco_lease_guard_free_power_import.yaml")
GUARD_ID = {"dump": "ecco_lease_guard_dump_end", "time": "ecco_lease_guard_free_power_time", "import": "ecco_lease_guard_free_power_import"}
NOTICE_ID = "ecco_lease_guard_free_power_import_inert"      # the second, small automation of the import guard file: it only says so when the ceiling cannot be read, and never presses
GUARD_AUTOS = {"dump": (GUARD_ID["dump"],), "time": (GUARD_ID["time"],), "import": (GUARD_ID["import"], NOTICE_ID)}
GATE_TEXT = (ROOT / GATE_REL).read_text(encoding="utf-8")
GUARDS_TEXT = tuple((ROOT / rel).read_text(encoding="utf-8") for rel in GUARDS_REL)
GATE_RAW = (ROOT / GATE_REL).read_bytes()
GUARDS_RAW = tuple((ROOT / rel).read_bytes() for rel in GUARDS_REL)
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
CHARGE_CODES = ["IMPORT_CEILING_UNREADABLE", "IMPORT_CEILING_INVALID", "IMPORT_UNREADABLE", "REQUEST_UNREADABLE", "IMPORT_HEADROOM"]
FACT_ENT = {"tl": G.TL, "ts": G.TS, "tel": G.TEL, "cfg": G.CFG, "poll": G.POLL, "fp_active": G.FP_ACTIVE, "fp_op": G.FP_OP, "fp_snap": G.FP_SNAP, "dg_active": G.DG_ACTIVE,
            "dg_op": G.DG_OP, "dg_snap": G.DG_SNAP, "manual": G.MANUAL, "hold": G.HOLD, "eff": G.EFF, "stop": G.STOP, "rev": G.REV, "ceil": G.CEIL, "grid": G.GRID, "req": G.REQ}
BUSY = [("fp_active", "FREE_POWER_ACTIVE"), ("fp_op", "FREE_POWER_OPERATION"), ("fp_snap", "FREE_POWER_SNAPSHOT"), ("dg_active", "DUMP_ACTIVE"), ("dg_op", "DUMP_OPERATION"),
        ("dg_snap", "DUMP_SNAPSHOT"), ("manual", "MANUAL_WRITE")]
HEALTHY_F = {"tl": "on", "ts": "on", "tel": "on", "cfg": "on", "poll": ("age", 0), "fp_active": "off", "fp_op": "off", "fp_snap": "off", "dg_active": "off", "dg_op": "off",
             "dg_snap": "off", "manual": "off", "hold": "clear", "eff": "40", "stop": "40.0", "rev": "12.0", "ceil": "0.0", "grid": "1500.0", "req": "4000.0"}
CODE_ENTITY = {"TIME_LEASES": G.TL, "TIME_SCHEDULES": G.TS, "TELEMETRY_OFFLINE": G.TEL, "CONFIGURATION_OFFLINE": G.CFG, "TELEMETRY_STALE": G.POLL, "FREE_POWER_ACTIVE": G.FP_ACTIVE,
               "FREE_POWER_OPERATION": G.FP_OP, "FREE_POWER_SNAPSHOT": G.FP_SNAP, "DUMP_ACTIVE": G.DG_ACTIVE, "DUMP_OPERATION": G.DG_OP, "DUMP_SNAPSHOT": G.DG_SNAP, "MANUAL_WRITE": G.MANUAL,
               "OVERRIDE_ACTIVE": G.HOLD, "OVERRIDE_UNREADABLE": G.HOLD, "RESERVE_INVALID": G.EFF, "RESERVE_UNKNOWN": G.EFF, "STOP_SOC_UNREADABLE": G.STOP, "STOP_SOC_BELOW_RESERVE": "Stop SOC",
               "REVISION_UNREADABLE": G.REV, "IMPORT_CEILING_UNREADABLE": G.CEIL, "IMPORT_CEILING_INVALID": G.CEIL, "IMPORT_UNREADABLE": G.GRID, "REQUEST_UNREADABLE": G.REQ, "IMPORT_HEADROOM": "grid-import ceiling"}

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
OTHER_PKGS = {p.name: p for p in sorted(PKGS.glob("*.yaml")) if p.name not in ("ecco_start_gate.yaml", "ecco_lease_guard_dump.yaml", "ecco_lease_guard_free_power_time.yaml",
                                                                      "ecco_lease_guard_free_power_import.yaml")}
FW_IDS = firmware_ids()
REPO_IDS = set(FW_IDS)
for _p in OTHER_PKGS.values():
    REPO_IDS |= package_ids(_p)

GATE_OWN = {G.CHARGE_GATE, G.EXPORT_GATE, G.CEIL, "script.ecco_free_power_start_guarded"}
GATE_READS = {G.TL, G.TS, G.TEL, G.CFG, G.POLL, G.FP_ACTIVE, G.FP_OP, G.FP_SNAP, G.DG_ACTIVE, G.DG_OP, G.DG_SNAP, G.MANUAL, G.HOLD, G.EFF, G.STOP, G.REV, G.GRID, G.REQ, G.DUR, G.ARM,
              G.START_FP, G.STATUS, G.LIMIT, G.SCHED, G.LAST}
# what each guard file reads, by name (the facts of the verdict are the Free Power guards': the lease flag, the operation flag, the status text, the end time, the End button)
VERDICT_READS = {G.FP_ACTIVE, G.FP_OP, G.STATUS, G.ENDS_AT, G.END_FP}
GUARD_READS = {"dump": {G.HOLD, G.EFF, G.DG_ACTIVE, G.LATCHED, G.END_DUMP},
               "time": VERDICT_READS | {G.TL},
               "import": VERDICT_READS | {G.CEIL, G.GRID}}
SCRIPT_SERVICES = ALLOWED_SERVICES - {("button.press", G.END_DUMP), ("button.press", G.END_FP)}
GUARD_SERVICES = {"dump": {("button.press", G.END_DUMP), ("persistent_notification.create", "")},
                  "time": {("button.press", G.END_FP), ("persistent_notification.create", "")},
                  "import": {("button.press", G.END_FP), ("persistent_notification.create", "")}}
GUARD_NOTES = {"dump": {G.NOTE_DUMP}, "time": {G.NOTE_FP, G.NOTE_FP_DECLINED}, "import": {G.NOTE_FP, G.NOTE_FP_DECLINED}}
GUARD_TRIGGERS = {"dump": [("state", G.HOLD, "held", "hold"), ("state", G.EFF, None, "reserve"), ("state", G.DG_ACTIVE, "on", "lease_started")],
                  "time": [("state", G.TL, "off", "trust_lost"), ("state", G.FP_ACTIVE, "on", "lease_started")],
                  "import": [("template", None, "-", "import_breach")]}
GUARD_WAITS = {"dump": ["00:00:15"], "time": ["00:05:00"], "import": ["00:00:30"]}
# the steps of each guard's action list in order (the kind of each top-level step)
GUARD_SHAPE = {"dump": ["wait", "variables", "condition", "action", "action", "delay"],
               "time": ["wait", "condition", "variables", "choose", "delay"],
               "import": ["wait", "condition", "variables", "choose", "delay"]}
# the sentences of the verdict, each a fact the Free Power guards must check before they press the operator's End
VERDICT_PINS = ("states('sensor.ecco_clock_dongle_free_power_status')", "states('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress')", "states('sensor.ecco_clock_dongle_free_power_ends_at')",
                "strptime(ea, '%Y-%m-%d %H:%M:%S', none)", "states['binary_sensor.ecco_clock_dongle_free_power_active']", "as_timestamp(act.last_changed, none) if act is not none else none",
                "states('button.ecco_clock_dongle_end_free_power_restore_now')", "as_timestamp(bt, none)", "op != 'off'", "not st.startswith('ACTIVE - VERIFIED OK')",
                "eat is none or as_timestamp(eat) <= as_timestamp(now())", "bt != 'unknown' and pressed is none", "pressed is not none and pressed >= since")
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
             "reload three things", "No restart", "Never \"reload all\"", "ecco_lease_guard_dump.yaml", "ecco_lease_guard_free_power_time.yaml", "ecco_lease_guard_free_power_import.yaml",
             "IMPORT_CEILING_UNREADABLE", "ONLY a readable 0 means NO CEILING CONFIGURED", "LIMIT_OUT_OF_RANGE", "ONLY IF THIS RUN TURNED IT ON", "puts the values this run replaced back",
             "A REFUSAL AT THE PRESS-TIME CHECK AFTER AN EXPLICIT REQUEST", "a BYPASS", "TELEMETRY_STALE", "within 300 s of Home Assistant's clock", "IMPORT_HEADROOM",
             "IMPORT_CEILING_INVALID", "GATE_BLOCKED", "NOT_CONFIRMED", "NO_ANSWER", "START_FAILED", "FIRMWARE_REFUSED", "SCHEDULED_START_RUNNING", "blocked_by", "reasons",
             "Time-zone assumption", "the in-lease guard", "the dongle's own gate refused the press", "Item N2 of the architecture reconciliation")
GUARD_COMMON_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "each stands alone", "The guard is SOFT: it runs in Home Assistant",
                     "The ONLY service calls are button.press", "never presses a START button",
                     "A restart, a template reload, a reconnect of the dongle and a boot never end a lease by themselves", "A guard acts only on a POSITIVE reading",
                     "A violation that already stands when Home Assistant starts is NOT acted on until the next change",
                     "Recalled from Home Assistant core, NOT verified on a real Home Assistant", "reload the AUTOMATIONS", "no restart", "never \"reload all\"", "separate from the start gate",
                     "Item N2 of the architecture reconciliation", "INSTALL.")
FP_OPERATOR_PINS = ("THIS PRESS IS THE OPERATOR'S END", "the one button the firmware reads as an operator's explicit retry", "free_power_operator_retry_pending", "restore_free_power_snapshot",
                    "clears the durable operator-decision lockout", "the next-attempt time", "VERIFIED RUNNING lease", "ACTIVE - VERIFIED OK", "AT MOST ONE PRESS PER LEASE",
                    "END is never gated for a human", "the declined notification", "ecco_lease_guard_free_power_declined", "ecco_lease_guard_free_power_ended", "one press per lease",
                    "Charge Battery (Free Power) has no target-reached guard here", "NOT ended by the Free Power guards", "An automatic END with no operator authority is a firmware option")
GUARD_PINS = {
    "dump": GUARD_COMMON_PINS + ("waits up to 15 s", "the dongle's active Stop SOC", "ecco_lease_guard_dump_end", "END is always allowed", "the exact values, never a computed one",
                                 "THE DUMP END IS NOT AN OPERATOR RETRY", "dump_force_restore_bypass", "request_dump_end", "its manual End button", "A hold of any kind, Skip tonight included",
                                 "reads `unknown` as a VALUE", "one press per violation"),
    "time": GUARD_COMMON_PINS + FP_OPERATOR_PINS + ("5 MINUTES", "ecco_lease_guard_free_power_time", "READERS allow-list"),
    "import": GUARD_COMMON_PINS + FP_OPERATOR_PINS + ("30 SECONDS", "ecco_lease_guard_free_power_import", "NONE CONFIGURED", "CANNOT BE READ", "ecco_lease_guard_free_power_inert",
                                                       "IMPORT_CEILING_UNREADABLE", "The ceiling is a SAFETY ceiling, never a target"),
}


def header_problems(text: str, pins: tuple) -> list[str]:
    head = head_flat(text, "\nautomation:" if "\nautomation:" in text else "\ninput_number:")
    return [f"header lacks {p!r}" for p in pins if p not in head]


def flat_actions(actions) -> list:
    """The steps of an action list in order; the branches of a `choose` and an `if` are entered (their steps follow the step that holds them)."""
    out = []
    for a in actions or []:
        out.append(a)
        if "choose" in a:
            for br in a["choose"]:
                out.extend(flat_actions(br["sequence"]))
            out.extend(flat_actions(a.get("default")))
        if "if" in a:
            out.extend(flat_actions(a.get("then")))
            out.extend(flat_actions(a.get("else")))
    return out


def step_kind(x: dict) -> str:
    for k in ("wait_template", "condition", "variables", "choose", "delay", "if", "stop"):
        if k in x:
            return {"wait_template": "wait"}.get(k, k)
    return "action" if "action" in x else "?"


def guards_static(guards_text: tuple, add) -> None:
    """The three guard files: what each is (one guard automation, and in the import guard file a second one that only says so when the ceiling cannot be read), the only services each
    calls, its triggers and delays, the verdict the two Free Power guards share, the entities it reads, its header. `guards_text` is the three texts in the order of GUARD_NAMES."""
    if len(guards_text) != len(GUARD_NAMES):
        add(f"{len(guards_text)} guard files, expected {len(GUARD_NAMES)}")
        return
    verdicts = {}
    for name, text in zip(GUARD_NAMES, guards_text):
        aid = GUARD_ID[name]
        try:
            g = yaml.load(text, Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001
            add(f"{aid}: the file does not load: {str(exc)[:100]}")
            continue
        if not isinstance(g, dict) or set(g) != {"automation"} or [x.get("id") for x in g["automation"]] != list(GUARD_AUTOS[name]):
            add(f"{aid}: the file is not exactly the automations {GUARD_AUTOS[name]} ({sorted(g) if isinstance(g, dict) else repr(g)[:40]})")
            continue
        a = g["automation"][0]
        for x in g["automation"]:
            if x.get("mode") != "single" or x.get("max_exceeded") != "silent":
                add(f"{x.get('id')}: mode")
        pairs = service_pairs(a.get("actions"))
        if pairs != GUARD_SERVICES[name]:
            add(f"{aid}: services {sorted(pairs ^ GUARD_SERVICES[name])}")
        trg = [(tr.get("trigger"), tr.get("entity_id"), tr.get("to", "-"), tr.get("id")) for tr in a["triggers"]]
        if trg != GUARD_TRIGGERS[name]:
            add(f"{aid}: triggers {trg}")
        acts_all = [act for x in g["automation"] for act in walk_actions(x.get("actions"), [])]
        for act in acts_all:
            if "entity_id" in (act.get("data") or {}):
                add(f"{aid}: an action carries entity_id in its data")
        if sum(1 for x in acts_all if x["action"] == "button.press") != 1:
            add(f"{aid}: not exactly one press in the file")
        acts = walk_actions(a.get("actions"), [])
        notes = {(x.get("data") or {}).get("notification_id") for x in acts if x["action"] == "persistent_notification.create"}
        if notes != GUARD_NOTES[name]:
            add(f"{aid}: notification ids {sorted(n for n in notes if n)}")
        flat = flat_actions(a["actions"])
        waits = [x.get("timeout") for x in flat if "wait_template" in x]
        delays = [x.get("delay") for x in flat if "delay" in x]
        if waits != GUARD_WAITS[name] or delays != ["00:01:00"]:
            add(f"{aid}: waits {waits} delays {delays}")
        if [step_kind(x) for x in a["actions"]] != GUARD_SHAPE[name]:
            add(f"{aid}: the steps are {[step_kind(x) for x in a['actions']]}")
        conds = re.sub(r"\s+", " ", "".join(str(c.get("value_template", "")) for c in a.get("conditions") or []))
        if name == "dump" and "not in (['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown'])" not in conds:
            add("the Dump guard does not refuse a change from unavailable or nothing (and, but for the hold sensor's own unknown, from unknown)")
        if name == "time" and "in ['on', 'off']" not in conds:
            add("the time guard does not require a change from a reading")
        if name == "import":
            pre = [re.search(r"\{%- set breached.*?-%\}", str(x), re.S) for x in (a["triggers"][0]["value_template"], a["actions"][0]["wait_template"], a["actions"][1]["value_template"])]
            if not all(pre) or len({m.group(0) for m in pre if m}) != 1:
                add("the import breach expression differs between its three places")
            # the notice: its own automation, it can only say so (one notification), after a minute of grace, when a lease is active and the ceiling reads unknown or unavailable
            n = g["automation"][1]
            unr = "{{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and states('input_number.ecco_grid_import_ceiling_w') in ['unknown', 'unavailable'] }}"
            want_wait = "{{ not (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and states('input_number.ecco_grid_import_ceiling_w') in ['unknown', 'unavailable']) }}"
            ok = ([(tr.get("trigger"), tr.get("id"), re.sub(r"\s+", " ", tr.get("value_template", "")).strip()) for tr in n["triggers"]] == [("template", "ceiling_unreadable", unr)]
                  and [step_kind(x) for x in n["actions"]] == ["wait", "condition", "action"]
                  and re.sub(r"\s+", " ", n["actions"][0]["wait_template"]).strip() == want_wait and n["actions"][0].get("timeout") == "00:01:00"
                  and re.sub(r"\s+", " ", n["actions"][1]["value_template"]).strip() == unr
                  and service_pairs(n["actions"]) == {("persistent_notification.create", "")} and n["actions"][2]["data"].get("notification_id") == G.NOTE_FP_INERT)
            if not ok:
                add("the import guard's notice of an unreadable ceiling is not (one minute of grace, still true, one notification) on its own trigger")
        if name in ("time", "import"):
            ver = next((x["variables"]["verdict"] for x in flat if isinstance(x.get("variables"), dict) and "verdict" in x["variables"]), None)
            verdicts[name] = re.sub(r"\s+", " ", ver or "").strip()
            for pin in VERDICT_PINS:
                if pin not in verdicts[name]:
                    add(f"{aid}: the verdict lacks {pin!r}")
            chs = [x for x in a["actions"] if "choose" in x]
            ok = (len(chs) == 1 and len(chs[0]["choose"]) == 1
                  and chs[0]["choose"][0]["conditions"] == [{"condition": "template", "value_template": "{{ verdict == '' }}"}]
                  and [x.get("action") for x in chs[0]["choose"][0]["sequence"]] == ["button.press", "persistent_notification.create"]
                  and [x.get("action") for x in chs[0].get("default") or []] == ["persistent_notification.create"])
            if not ok:
                add(f"{aid}: the press is not exactly the branch of an empty verdict (the other branch only says why it was declined)")
        nc = noncomment(text)
        mentioned = set(ENTITY_RE.findall(entity_text(text)))
        if mentioned != GUARD_READS[name]:
            add(f"{aid}: entities read {sorted(mentioned ^ GUARD_READS[name])}")
        if not GUARD_READS[name] <= REPO_IDS | GATE_OWN:
            add(f"{aid}: not in the repository: {sorted(GUARD_READS[name] - REPO_IDS - GATE_OWN)}")
        for m in re.finditer(r"(?<![A-Za-z0-9_.])(?:switch|number|input_boolean|input_text|script)\.|(?<![A-Za-z0-9_.])(?:esphome|modbus|homeassistant|event_type)(?![A-Za-z0-9_])", entity_text(text)):
            add(f"{aid}: guard token {m.group(0)}")
        if "button.ecco_clock_dongle_start_" in nc:
            add(f"{aid}: a guard names a START button")
        if ("ecco_time_trust" in text) != (name == "time"):
            add(f"{aid}: only the Free Power time guard may mention the time trust package (it is on that package's READERS allow-list)")
        for p in header_problems(text, GUARD_PINS[name]) + privacy_problems(text, text.encode("utf-8")):
            add(f"{aid}: {p}")
    if verdicts.get("time") != verdicts.get("import") or not verdicts.get("time"):
        add("the two Free Power guards do not carry the same verdict")


def static_problems(gate_text: str, guards_text: tuple, only: str = "both", pb: "Problems | None" = None) -> list[str]:
    """Everything the four files must be, without running them (`guards_text` is the three guard files). `only` is 'gate', 'guards' or 'both'."""
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
        guards_static(guards_text, add)
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
        c_gone = cr in BAD                                                   # unknown, unavailable, missing: it cannot be told whether a ceiling is configured
        c_unset = (not c_gone) and cf is not None and cf == 0               # ONLY a readable 0 is "none configured"
        c_ok = cf is not None and cf == cf and 1 <= cf <= 100000
        gi = flt(f["grid"])
        gi_ok = gi is not None and gi == gi and abs(gi) < 1e9
        rq = flt(f["req"])
        rq_ok = rq is not None and rq == rq and 0 < rq < 1e9
        if c_gone:
            codes.append("IMPORT_CEILING_UNREADABLE")
        if (not c_gone) and (not c_unset) and (not c_ok):
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
    ({"ceil": "unknown", "grid": "abc", "req": "abc"}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": None, "grid": "abc", "req": "abc"}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": "unavailable"}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": "unavailable", "grid": "unavailable", "req": "unavailable"}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": ""}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": "none"}, ["IMPORT_CEILING_UNREADABLE"], []),
    ({"ceil": "-0.0"}, [], []),
    ({"ceil": "5000", "req": "3500", "tl": "off"}, ["TIME_LEASES"], ["TIME_LEASES"]),
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
    """A refusal before anything is staged: nothing staged, armed, pressed or switched (no call reaches the dongle at all), the stable code in the result text and ONE notification."""
    last, note = gw.state(G.LAST), gw.w.notifications.get(G.NOTE_START, {})
    if dongle_calls(gw, n0) != [] or gw.d.press_log or gw.d.number_log or gw.d.presses:
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
        ("the grid charge limit is 0 (readable, outside the range)", lambda g: g.put(G.LIMIT, "0"), {}, "LIMIT_OUT_OF_RANGE", "reads 0 W"),
        ("the grid charge limit is below the minimum (readable, outside the range)", lambda g: g.put(G.LIMIT, "400"), {}, "LIMIT_OUT_OF_RANGE", "reads 400 W, outside the supported range of 500 W to 100000 W"),
        ("the grid charge limit is above the maximum (readable, outside the range)", lambda g: g.put(G.LIMIT, "100001"), {}, "LIMIT_OUT_OF_RANGE", "reads 100001 W"),
        ("the grid charge limit is nan", lambda g: g.put(G.LIMIT, "nan"), {}, "LIMIT_UNREADABLE", "it reads nan"),
        ("the grid charge limit is infinite", lambda g: g.put(G.LIMIT, "inf"), {}, "LIMIT_UNREADABLE", "it reads inf"),
        ("the grid charge limit is absurd (readable, outside the range)", lambda g: g.put(G.LIMIT, "500000"), {}, "LIMIT_OUT_OF_RANGE", "reads 500000 W"),
        ("the grid charge limit is beyond a million watts (not a limit that can be read)", lambda g: g.put(G.LIMIT, "2000000"), {}, "LIMIT_UNREADABLE", "it reads 2000000"),
        ("the grid charge limit is text", lambda g: g.put(G.LIMIT, "abc"), {}, "LIMIT_UNREADABLE", "it reads abc"),
        ("the staged power is unreadable and none is given", lambda g: g.put(G.REQ, "unknown"), {}, "POWER_INVALID", "(unreadable)"),
        ("the staged duration is unreadable and none is given", lambda g: g.put(G.DUR, "unavailable"), {}, "DURATION_INVALID", "(unreadable)"),
        ("the gate is closed only by an unreadable ceiling, with an explicit request that differs from the staged one (never deferred)", lambda g: g.put(G.CEIL, "unavailable"),
         {"power_w": 2000}, "GATE_BLOCKED", "IMPORT_CEILING_UNREADABLE"),
        ("the gate is closed only by an unreadable ceiling", lambda g: g.put(G.CEIL, "unknown"), {}, "GATE_BLOCKED", "IMPORT_CEILING_UNREADABLE"),
        ("the gate is closed only by an unreadable import, with an explicit request that differs from the staged one (never deferred: nothing is staged)", lambda g: (g.put(G.CEIL, "5000"), g.put(G.GRID, "unavailable")),
         {"power_w": 2000}, "GATE_BLOCKED", "IMPORT_UNREADABLE"),
        ("the gate is closed only by an unreadable import, with an explicit request equal to the staged one", lambda g: (g.put(G.CEIL, "5000"), g.put(G.GRID, "unknown")),
         {"power_w": 4000}, "GATE_BLOCKED", "IMPORT_UNREADABLE"),
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
    if [(e, v) for _t, e, v in gw.d.number_log] != [(G.REQ, 3500), (G.REQ, 4000)] or gw.state(G.REQ) != "4000.0" or gw.state(G.DUR) != "60.0":
        pb.add(f"the staged request of a refused explicit start is put back, once: {gw.d.number_log} now {gw.state(G.REQ)} {gw.state(G.DUR)}")
    if "The staged request was put back to 4000 W for 60 min." not in gw.state(G.LAST) or "The staged request was put back to 4000 W for 60 min." not in gw.w.notifications.get(G.NOTE_START, {}).get("message", ""):
        pb.add(f"the result text and the notification say that the staged request was put back: {gw.state(G.LAST)[-80:]!r}")
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
        ("the scheduled start script becomes unavailable while the request is staged (never read as not running)", "SCHEDULED_START_RUNNING", lambda g: lambda: g.put(G.SCHED, "unavailable"), {}, None),
        ("the scheduled start script goes missing while the request is staged", "SCHEDULED_START_RUNNING", lambda g: lambda: g.put(G.SCHED, None), {}, None),
        ("the gate becomes unavailable during the 5 s confirmation (a template reload)", "GATE_CLOSED", lambda g: lambda: g.tw.override(G.CHARGE_GATE, "unavailable"), {}, None),
        ("the gate becomes unknown during the 5 s confirmation", "GATE_CLOSED", lambda g: lambda: g.tw.override(G.CHARGE_GATE, "unknown"), {}, None),
        ("the gate becomes unavailable during the 5 s confirmation of an explicit request", "GATE_CLOSED", lambda g: lambda: g.tw.override(G.CHARGE_GATE, "unavailable"), {"power_w": 3000, "duration_minutes": 30}, None),
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

    # --- SG-6: a refusal at the press-time check puts back what this run replaced on the dongle, once, and reads it back --------------------------------
    def gate_closes(g, at=0.5):
        g.w.at(g.w.t + at, lambda: g.put(G.TL, "off"))

    def numbers(g):
        return [(e, v) for _t, e, v in g.d.number_log]

    def note_of(g):
        return g.w.notifications.get(G.NOTE_START, {}).get("message", "")

    for label, data, staged, want_text in (
            ("the power only", {"power_w": 3000}, [(G.REQ, 3000), (G.REQ, 4000)], "The staged request was put back to 4000 W for 60 min."),
            ("the duration only", {"duration_minutes": 30}, [(G.DUR, 30), (G.DUR, 60)], "The staged request was put back to 4000 W for 60 min."),
            ("both, the power first", {"power_w": 3000, "duration_minutes": 30}, [(G.REQ, 3000), (G.DUR, 30), (G.REQ, 4000), (G.DUR, 60)], "The staged request was put back to 4000 W for 60 min."),
            ("a request equal to the staged one", {"power_w": 4000, "duration_minutes": 60}, [], ""),
            ("no explicit values", {}, [], "")):
        gw = sw(gate_text)
        reset(gw)
        gate_closes(gw)
        n0 = run_start(gw, data, 14.0)
        press_refused(gw, n0, "GATE_CLOSED", f"a refused start with {label}", pb)
        last, msg = gw.state(G.LAST), note_of(gw)
        if numbers(gw) != staged or gw.state(G.REQ) != "4000.0" or gw.state(G.DUR) != "60.0":
            pb.add(f"a refused start with {label}: the staged numbers {numbers(gw)}, now {gw.state(G.REQ)} {gw.state(G.DUR)}, expected writes {staged} and the owner's 4000 W for 60 min back")
        if want_text and (want_text not in last or want_text not in msg):
            pb.add(f"a refused start with {label}: the result text and the notification must say the request was put back: {last[-90:]!r} {msg[-110:]!r}")
        if not want_text and ("put back" in last or "put back" in msg or "  " in msg or "NOT" in last):
            pb.add(f"a refused start with {label} changed nothing and must not claim a put-back: {last[-90:]!r} {msg[-110:]!r}")
        if len(last) > 250:
            pb.add(f"the result text is {len(last)} characters")
        harvest(gw)
    # the same with the gate closed by SEVERAL causes (a long result text): the note that the request was put back is never cut off
    gw = sw(gate_text)
    reset(gw)
    gw.w.at(gw.w.t + 0.5, lambda: [gw.put(eid, "off") for eid in (G.TL, G.TS, G.TEL, G.CFG)])
    n0 = run_start(gw, {"power_w": 3000, "duration_minutes": 30}, 14.0)
    if len(gw.state(G.LAST)) > 250 or not gw.state(G.LAST).endswith("The staged request was put back to 4000 W for 60 min.") or "TIME_LEASES" not in gw.state(G.LAST):
        pb.add(f"a long refusal text keeps the put-back note and its code: {len(gw.state(G.LAST))} {gw.state(G.LAST)[-90:]!r}")
    # a staged value that could not be read before the run cannot be put back, and that is said
    gw = sw(gate_text)
    reset(gw)
    gw.put(G.REQ, "unknown")
    gate_closes(gw)
    n0 = run_start(gw, {"power_w": 2000}, 14.0)
    last = gw.state(G.LAST)
    if numbers(gw) != [(G.REQ, 2000)] or "could NOT be put back and confirmed" not in last or "it was unreadable for 60 min" not in last or "-1" in last:
        pb.add(f"a staged power that could not be read cannot be put back and the text says so: {numbers(gw)} {last[-170:]!r}")
    # the dongle takes the staged value and then stops taking numbers: the put-back is written once, not confirmed, and the text says what the dongle holds
    gw = sw(gate_text)
    reset(gw)
    gw.w.at(gw.w.t + 0.7, lambda: setattr(gw.d, "drop_numbers", True))
    gate_closes(gw, 0.8)
    n0 = run_start(gw, {"power_w": 3000}, 20.0)
    last, msg = gw.state(G.LAST), note_of(gw)
    if (numbers(gw) != [(G.REQ, 3000), (G.REQ, 4000)] or gw.state(G.REQ) != "3000.0" or "could NOT be put back and confirmed" not in last or "it was 4000 W for 60 min" not in last
            or "the dongle now reads 3000.0 W for 60.0 min" not in last or "could NOT be put back" not in msg or gw.state(G.ARM) != "off"):
        pb.add(f"a put-back the dongle does not confirm is written once and reported as it is: {numbers(gw)} {last[-170:]!r}")
    # a slow dongle (its readback takes 3 s, as does its confirmation of the staged request): the put-back is waited for, up to 5 s, and reported as it then stands
    gw = sw(gate_text)
    reset(gw)
    gw.d.publish = 3.0
    gate_closes(gw)
    n0 = run_start(gw, {"power_w": 3000}, 40.0)
    last = gw.state(G.LAST)
    if numbers(gw) != [(G.REQ, 3000), (G.REQ, 4000)] or gw.state(G.REQ) != "4000.0" or "The staged request was put back to 4000 W for 60 min." not in last or "NOT" in last:
        pb.add(f"a put-back that the dongle confirms after 3 s is waited for: {numbers(gw)} now {gw.state(G.REQ)} {last[-110:]!r}")
    # NOT_CONFIRMED (the dongle never took the numbers): the staged request never changed, so the readback equals it and the text says it stands
    gw = sw(gate_text)
    reset(gw)
    gw.d.drop_numbers = True
    n0 = run_start(gw, {"power_w": 3000}, 14.0)
    press_refused(gw, n0, "NOT_CONFIRMED", "the dongle never takes the numbers", pb)
    if numbers(gw) != [(G.REQ, 3000), (G.REQ, 4000)] or gw.state(G.REQ) != "4000.0" or "The staged request was put back to 4000 W for 60 min." not in gw.state(G.LAST):
        pb.add(f"a start whose numbers the dongle never took: {numbers(gw)} {gw.state(G.LAST)[-90:]!r}")
    # a refusal text names the right cause at the press-time check: a limit that cannot be read is not a limit that fell
    for label, val, want in (("the limit becomes unreadable", "unavailable", "can no longer be read (it reads unavailable)"),
                             ("the limit is lowered", "3000", "fell to 3000 W, below the request (4000 W)"),
                             ("the limit is text", "abc", "can no longer be read (it reads abc)")):
        gw = sw(gate_text)
        reset(gw)
        gw.w.at(gw.w.t + 0.5, lambda v=val, g=gw: g.put(G.LIMIT, v))
        n0 = run_start(gw, {}, 12.0)
        press_refused(gw, n0, "LIMIT_LOWERED", label, pb)
        if want not in gw.state(G.LAST) or "-1" in gw.state(G.LAST):
            pb.add(f"{label}: the refusal text says {gw.state(G.LAST)[-120:]!r}, expected {want!r}")

    # --- SG-9: an unreadable staged value is printed as unreadable, never as -1 ---------------------------------------------------------------------------
    for label, setup, code in (("the staged power", lambda g: g.put(G.REQ, "unknown"), "POWER_INVALID"), ("the staged duration", lambda g: g.put(G.DUR, "unavailable"), "DURATION_INVALID")):
        gw = sw(gate_text)
        reset(gw)
        setup(gw)
        run_start(gw, {})
        shown = gw.state(G.LAST) + " " + note_of(gw)
        if "-1" in shown or "(unreadable)" not in shown or f"(reason {code})" not in shown:
            pb.add(f"{label} that cannot be read is printed as unreadable, not as -1: {shown[:200]!r}")

    # --- SG-7: the write enable ends off only if THIS run turned it on -----------------------------------------------------------------------------
    def armed_by_another(g):
        g.w.set(G.ARM, "on")
        g.d.arm = True

    gw = sw(gate_text)
    reset(gw)
    armed_by_another(gw)
    gw.put(G.SCHED, "on")
    n0 = run_start(gw, {})
    if dongle_calls(gw, n0) != [] or gw.state(G.ARM) != "on" or not gw.state(G.LAST).startswith("REFUSED SCHEDULED_START_RUNNING - "):
        pb.add(f"a refusal before the arm leaves a write enable that another actor armed alone: {dongle_calls(gw, n0)} arm {gw.state(G.ARM)}")
    gw = sw(gate_text)
    reset(gw)
    armed_by_another(gw)
    gw.put(G.TL, "off")
    n0 = run_start(gw, {"power_w": 3000})
    if dongle_calls(gw, n0) != [] or gw.state(G.ARM) != "on" or "GATE_BLOCKED" not in gw.state(G.LAST):
        pb.add(f"a closed gate leaves a write enable that another actor armed alone, and stages nothing: {dongle_calls(gw, n0)} arm {gw.state(G.ARM)}")
    gw = sw(gate_text)
    reset(gw)
    armed_by_another(gw)
    n0 = run_start(gw, {}, 200.0)
    if dongle_calls(gw, n0) != [("switch.turn_on", G.ARM), ("button.press", G.START_FP)] or gw.state(G.ARM) != "off" or not gw.state(G.LAST).startswith("STARTED free_power at 4000 W for 60 min"):
        pb.add(f"a start with a write enable that is already on presses, never switches it off itself (the firmware disarms it at the press): {dongle_calls(gw, n0)} arm {gw.state(G.ARM)}")
    gw = sw(gate_text)
    reset(gw)
    armed_by_another(gw)
    gate_closes(gw)
    n0 = run_start(gw, {}, 12.0)
    if ("switch.turn_off", G.ARM) in dongle_calls(gw, n0) or gw.state(G.ARM) != "on" or not gw.state(G.LAST).startswith("REFUSED GATE_CLOSED - ") or gw.d.press_log:
        pb.add(f"a press-time refusal leaves a write enable that was already on as it was found: {dongle_calls(gw, n0)} arm {gw.state(G.ARM)}")
    gw = sw(gate_text)
    reset(gw)
    armed_by_another(gw)
    gw.d.handle_delays = [900.0]
    n0 = run_start(gw, {}, 120.0)
    last, msg = gw.state(G.LAST), note_of(gw)
    if (len(gw.d.press_log) != 1 or not last.startswith("FAILED NO_ANSWER - ") or "write enable was already on before this start and is left on" not in last
            or "left on" not in msg or ("switch.turn_off", G.ARM) in dongle_calls(gw, n0) or gw.state(G.ARM) != "on"):
        pb.add(f"a press with no answer and a write enable that was already on: left on, and the text says so: {dongle_calls(gw, n0)} {last[-120:]!r}")
    harvest(gw)


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


def fp_world(gate_text: str, guards_text: str, *, leases: str = "on", lease: bool = True, ceiling: str = "0.0", grid: str = "1500.0", end_after: float = 20.0, **lease_kw) -> "G.GateWorld":
    """A Free Power lease that is VERIFIED RUNNING (the firmware's own status text, no operation in progress, an end time an hour away) unless `lease_kw` says otherwise: it is handed to
    LeaseDongle.fp_start (status, ends_at, minutes, snapshot, op)."""
    gw = G.GateWorld(gate_text, guards_text, poll=False, start_ha=False)
    gw.d.end_after = end_after
    gw.put(G.TL, leases)
    gw.put(G.CEIL, ceiling)
    gw.put(G.GRID, grid)
    if lease:
        gw.d.fp_start(**lease_kw)
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


def fp_status_texts() -> list:
    """Every text the firmware can publish as the Free Power status (the literals of publish_state in the firmware, the formatted ones with a plausible fill, the repository model's own
    and the three readings of an entity that has no text) except the one a verified activation publishes."""
    lits = re.findall(r'id\(free_power_status\)\.publish_state\("((?:[^"\\]|\\.)*)"\)', FW_TEXT)
    filled = ["SNAPSHOT DURABLY COMMITTED - 4000W at 52.0V -> 77A grid charge target",
              "RESTORE BLOCKED - register 244 context changed since this lease started (a context); 232/256-261 already restored, 268-279/230 withheld",
              "RESTORE BLOCKED - register 244 context changed since this lease started (a context)",
              "ACCEPT REFUSED - Free Power residue: 230", "ACCEPT REFUSED - implausible value: 232=99999"]
    model = [G.FP_RESTORED, "IDLE - no Free Power override active", "RESTORED - exact snapshot verified", "ACTIVATION WRITE FAILED - restoring saved snapshot", "", "unknown", "unavailable",
             " ACTIVE - VERIFIED OK; 155A grid charge", "active - verified ok; 155A grid charge", "ACTIVE - VERIFIED", "ACTIVE VERIFIED OK; 155A grid charge"]
    return sorted((set(lits) | set(filled) | set(model)) - {G.FP_VERIFIED})


def fp_both(gate_text: str, guards_text, *, settle: float = 330.0, end_after: float = 1e9, **lease_kw):
    """A Free Power lease with the conditions of BOTH Free Power guards true from the same moment (the import above its ceiling, the time not trusted); returns (world, that moment).
    The dongle never ends the lease by itself unless `end_after` says so, so every press the guards make shows."""
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=end_after, **lease_kw)
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.put(G.TL, "off")
    gw.advance(settle)
    return gw, t0


def verdict_problems(gate_text: str, guards_text, pb: Problems) -> None:
    """SG-1. END FREE POWER is the operator's one-shot retry in the firmware (it clears the durable lockout and resets the backoff): the Free Power guards press it only for a lease
    verified running, and at most once per lease."""
    F = G.END_FP
    # the positive control: a verified lease is pressed once, at 30 s, by the import guard, and the time guard (300 s) then finds END already pressed
    gw, t0 = fp_both(gate_text, guards_text)
    note = gw.w.notifications
    if [round(x - t0) for x in gw.d.pressed(F)] != [30] or set(note) != {G.NOTE_FP, G.NOTE_FP_DECLINED} or "was already pressed during this lease" not in note[G.NOTE_FP_DECLINED]["message"]:
        pb.add(f"both guards on a verified lease: one press at 30 s and the time guard declines: presses {[round(x - t0) for x in gw.d.pressed(F)]} notifications {sorted(note)}")
    msg = note.get(G.NOTE_FP, {}).get("message", "")
    if "THIS PRESS IS THE OPERATOR'S END" not in msg or "ACTIVE - VERIFIED OK" not in msg or "at most once per lease" not in msg or "6000 W" not in msg:
        pb.add(f"the notification of a press says that it is the operator's End and why the guard pressed: {msg[:200]!r}")
    harvest(gw)
    # the same with a dongle that ends the lease: one press, no declined notice (the lease is over when the time guard looks)
    gw, t0 = fp_both(gate_text, guards_text, end_after=20.0)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30] or G.NOTE_FP_DECLINED in gw.w.notifications:
        pb.add(f"both guards on a lease the dongle ends: {[round(x - t0) for x in gw.d.pressed(F)]} {sorted(gw.w.notifications)}")
    # the other order: the time guard presses first (300 s), a breach that starts later is declined (the same lease)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(310)
    gw.put(G.GRID, "6000")
    gw.advance(60)
    if [round(x - t0) for x in gw.d.pressed(F)] != [300] or "was already pressed during this lease" not in gw.w.notifications.get(G.NOTE_FP_DECLINED, {}).get("message", ""):
        pb.add(f"the time guard presses first and the import guard declines: {[round(x - t0) for x in gw.d.pressed(F)]} {sorted(gw.w.notifications)}")
    # both decide in the same instant (300 s): exactly one press whichever runs first
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(270)
    gw.put(G.GRID, "6000")
    gw.advance(60)
    if [round(x - t0) for x in gw.d.pressed(F)] != [300] or len(gw.d.button_log) != 1:
        pb.add(f"both guards decide in the same instant: exactly one press: {[(round(x - t0), e[-12:]) for x, e in gw.d.button_log]}")
    # the firmware's own status after a press (END REQUESTED) declines the second guard too, whatever the marker says
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    gw.d.model_end_status = True
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.put(G.TL, "off")
    gw.advance(330)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30] or "END REQUESTED" not in gw.w.notifications.get(G.NOTE_FP_DECLINED, {}).get("message", ""):
        pb.add(f"the status after a press declines the second guard: {[round(x - t0) for x in gw.d.pressed(F)]} {gw.w.notifications.get(G.NOTE_FP_DECLINED, {}).get('message', '')[:140]!r}")
    # one press per LEASE, not once for ever: the lease ends, a new one starts under the same breach, and it is pressed again
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=20.0)
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.advance(100)
    gw.d.fp_start()
    gw.advance(60)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30, 130]:
        pb.add(f"one press per lease: a second lease under the same breach is pressed again: {[round(x - t0) for x in gw.d.pressed(F)]}")
    # an END pressed by the operator (or the card) during the lease stops every guard press; one from an earlier lease does not
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    t0 = gw.w.t
    gw.w.at(t0 + 10.0, lambda: gw.d.stamp(F))
    gw.put(G.GRID, "6000")
    gw.put(G.TL, "off")
    gw.advance(330)
    if gw.d.pressed(F) or set(gw.w.notifications) != {G.NOTE_FP_DECLINED} or "already pressed during this lease" not in gw.w.notifications[G.NOTE_FP_DECLINED]["message"]:
        pb.add(f"an End pressed by the operator during the lease stops the guards: {gw.d.pressed(F)} {sorted(gw.w.notifications)}")
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", lease=False, end_after=1e9)
    gw.d.stamp(F)
    gw.advance(5)
    gw.d.fp_start()
    gw.advance(1)
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.advance(40)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30]:
        pb.add(f"an End pressed before this lease began does not stop the guards: {[round(x - t0) for x in gw.d.pressed(F)]}")
    for val, want in (("unknown", True), ("unavailable", False), ("none", False), ("", False), ("garbage", False)):
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", lease=False, end_after=1e9)
        gw.put(F, val)
        gw.advance(5)
        gw.d.fp_start()
        gw.advance(1)
        t0 = gw.w.t
        gw.put(G.GRID, "6000")
        gw.advance(40)
        if bool(gw.d.pressed(F)) != want:
            pb.add(f"the End button reading {val!r}: pressed {bool(gw.d.pressed(F))}, expected {want} (only a never-pressed button, or a press before the lease, lets a guard press)")
    # the lease began when the lease flag last CHANGED: an End pressed in the very instant it began counts, and an update of the flag's attributes alone does not move it
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", lease=False, end_after=1e9)
    gw.advance(5)
    gw.d.fp_start()
    gw.d.stamp(F)
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.advance(340)
    if gw.d.button_log or G.NOTE_FP_DECLINED not in gw.w.notifications:
        pb.add(f"an End pressed in the very instant the lease began counts as pressed in it: {len(gw.d.button_log)} presses {sorted(gw.w.notifications)}")
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    t0 = gw.w.t
    gw.w.at(t0 + 10.0, lambda: gw.d.stamp(F))
    gw.w.at(t0 + 20.0, lambda: gw.put(G.FP_ACTIVE, "on", {"refreshed_at": "x"}))
    gw.put(G.GRID, "6000")
    gw.advance(50)
    if gw.d.button_log:
        pb.add(f"an update of the lease flag's attributes alone does not move the time the lease began: {[round(x - t0) for x in gw.d.pressed(F)]}")
    # every other status the firmware can publish refuses the press, in both guards, and says what it read
    texts = fp_status_texts()
    for s in texts:
        gw, t0 = fp_both(gate_text, guards_text, status=s)
        m = gw.w.notifications.get(G.NOTE_FP_DECLINED, {}).get("message", "")
        if gw.d.button_log or set(gw.w.notifications) != {G.NOTE_FP_DECLINED} or (s.strip() and s[:40] not in m):
            pb.add(f"the status {s[:70]!r} must refuse the press in both guards and say so: presses {len(gw.d.button_log)} notifications {sorted(gw.w.notifications)} {m[100:230]!r}")
    # the verified text is accepted with any amperage; the operation flag must read off; the snapshot flag does not matter here
    for amps in ("1", "77", "155", "1000"):
        gw, t0 = fp_both(gate_text, guards_text, status=f"ACTIVE - VERIFIED OK; {amps}A grid charge; automatic restore armed")
        if [round(x - t0) for x in gw.d.pressed(F)] != [30]:
            pb.add(f"the verified status with {amps} A is pressed: {[round(x - t0) for x in gw.d.pressed(F)]}")
    for op in ("on", "unavailable", "unknown", "", "ON"):
        gw, t0 = fp_both(gate_text, guards_text, op=op)
        if gw.d.button_log or G.NOTE_FP_DECLINED not in gw.w.notifications or "operation flag reads" not in gw.w.notifications[G.NOTE_FP_DECLINED]["message"]:
            pb.add(f"the operation flag reading {op!r} refuses the press: {len(gw.d.button_log)} presses {sorted(gw.w.notifications)}")
    gw, t0 = fp_both(gate_text, guards_text, snapshot=False)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30]:
        pb.add("a running lease whose snapshot flag reads off is still pressed (the status and the end time are the proof): the model's flag is not part of the verdict")
    # the end time: a time in the firmware's exact form strictly after Home Assistant's clock, else the lease is the dongle's
    for label, make, want in (("an end time 31 s after the lease began (the import guard looks at 30 s)", lambda g, t: g.d.local_text(t + 31), [30]),
                              ("an end time exactly when the import guard looks", lambda g, t: g.d.local_text(t + 30), []),
                              ("an end time a second before it", lambda g, t: g.d.local_text(t + 29), []),
                              ("an end time in the past", lambda g, t: g.d.local_text(t - 3600), []),
                              ("an end time a day away", lambda g, t: g.d.local_text(t + 86400), [30]),
                              ("Inactive", lambda g, t: "Inactive", []),
                              ("Active - end time unavailable", lambda g, t: "Active - end time unavailable", []),
                              ("unavailable", lambda g, t: "unavailable", []),
                              ("unknown", lambda g, t: "unknown", []),
                              ("empty", lambda g, t: "", []),
                              ("garbage", lambda g, t: "tomorrow", []),
                              ("a time in another form (ISO, with a T)", lambda g, t: g.d.local_text(t + 3600).replace(" ", "T"), []),
                              ("a time with no seconds", lambda g, t: g.d.local_text(t + 3600)[:16], []),
                              ("a time with a fraction", lambda g, t: g.d.local_text(t + 3600) + ".5", []),
                              ("a time with spaces around it", lambda g, t: " " + g.d.local_text(t + 3600), [])):
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", lease=False, end_after=1e9)
        t = gw.w.t
        gw.d.fp_start(ends_at=make(gw, t))
        gw.put(G.GRID, "6000")
        gw.advance(40)
        got = [round(x - t) for x in gw.d.pressed(F)]
        if got != want:
            pb.add(f"{label}: presses at {got}, expected {want}")
        if not want and (gw.d.button_log or G.NOTE_FP_DECLINED not in gw.w.notifications or "end time is not a time in the future" not in gw.w.notifications[G.NOTE_FP_DECLINED]["message"]):
            pb.add(f"{label}: the guard must say that the end time is not a time in the future: {sorted(gw.w.notifications)}")
    # a lease that is about to end when the time guard (300 s) looks: its end passed during the wait, so the dongle's own watchdog has it
    gw = fp_world(gate_text, guards_text, leases="on", end_after=1e9, minutes=4.0)
    gw.put(G.TL, "off")
    gw.advance(330)
    if gw.d.button_log or G.NOTE_FP_DECLINED not in gw.w.notifications:
        pb.add(f"a lease whose end passes during the 5 minute count is left to the dongle: {len(gw.d.button_log)} presses {sorted(gw.w.notifications)}")
    # the same boundary for the time guard (it looks at 300 s): an end exactly then, or before, is the dongle's; a second later is pressed
    for label, k, want in (("an end time exactly when the time guard looks", 300, []), ("an end time a second before it", 299, []), ("an end time a second after it", 301, [300]),
                           ("an end time in the past", -3600, [])):
        gw = fp_world(gate_text, guards_text, leases="off", lease=False, end_after=1e9)
        t = gw.w.t
        gw.d.fp_start(ends_at=gw.d.local_text(t + k))
        gw.advance(330)
        got = [round(x - t) for x in gw.d.pressed(F)]
        if got != want:
            pb.add(f"the time guard with {label}: presses at {got}, expected {want}")
    # SG-1, the reviewer's reproductions: a restore that is OWED or BLOCKED (the lockout set, the End that would clear it never ending the lease): no guard ever presses, however long
    blocked = "OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying, or press End Free Power to retry"
    gw, t0 = fp_both(gate_text, guards_text, status=blocked, settle=400.0)
    if gw.d.button_log:
        pb.add(f"a blocked restore (the operator-decision lockout set): the import breach and the lost time press nothing: {[round(x - t0) for x in gw.d.pressed(F)]}")
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000.0", end_after=1e9, status=blocked)
    for _ in range(10):
        gw.put(G.GRID, "6000.0")
        gw.advance(60)
        gw.put(G.GRID, "4000.0")
        gw.advance(60)
    if gw.d.button_log:
        pb.add(f"a blocked restore and an import that oscillates around the ceiling for 20 minutes: {len(gw.d.button_log)} presses (each would be an operator retry)")
    gw = fp_world(gate_text, guards_text, leases="on", end_after=1e9, status=blocked)
    for _ in range(3):
        gw.put(G.TL, "off")
        gw.advance(330)
        gw.put(G.TL, "on")
        gw.advance(60)
    if gw.d.button_log:
        pb.add(f"a blocked restore and a time trust that flaps: {len(gw.d.button_log)} presses (each would be an operator retry)")
    for status in ("RESTORE VERIFY FAILED - snapshot retained for retry", "RESTORE WRITE FAILED - snapshot retained; will retry automatically", "END DEFERRED - another inverter write is active",
                   "RESTORING - confirming live inverter state before writing", "ACTIVE - reboot recovery pending", "RECOVERY REQUIRED - saved snapshot found"):
        gw, t0 = fp_both(gate_text, guards_text, status=status, settle=400.0, op="off")
        if gw.d.button_log:
            pb.add(f"a restore that is owed ({status[:40]}): {len(gw.d.button_log)} presses")
        gw, t0 = fp_both(gate_text, guards_text, status=status, settle=400.0, op="on")
        if gw.d.button_log:
            pb.add(f"a restore in progress ({status[:40]}): {len(gw.d.button_log)} presses")
    # the Free Power guards never press the Dump End, and the Dump guard never presses the Free Power End
    gw, t0 = fp_both(gate_text, guards_text)
    if {e for _t, e in gw.d.button_log} != {F}:
        pb.add(f"the Free Power guards press the Free Power End and nothing else: {sorted({e for _t, e in gw.d.button_log})}")
    harvest(gw)


def notice_problems(gate_text: str, guards_text, pb: Problems) -> None:
    """SG-4. A ceiling that cannot be read is not 'none configured' (only a readable 0 is): the import guard stays inert, because it never acts on a value it cannot read, but it SAYS SO
    (one notification, after a minute of grace) while a Free Power lease is active; and the notice never presses anything and never blocks the guard's own run."""
    F = G.END_FP
    for bad in ("unavailable", "unknown"):
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1500.0", end_after=1e9)
        gw.put(G.CEIL, bad)
        gw.advance(59)
        if G.NOTE_FP_INERT in gw.w.notifications:
            pb.add(f"the ceiling {bad} for 59 s: the notice waits a full minute")
        gw.advance(3)
        m = gw.w.notifications.get(G.NOTE_FP_INERT, {}).get("message", "")
        if set(gw.w.notifications) != {G.NOTE_FP_INERT} or gw.d.button_log or "INERT" not in m or f"reads {bad}" not in m or "IMPORT_CEILING_UNREADABLE" not in m:
            pb.add(f"the ceiling {bad} during a lease: one notice, no press: {sorted(gw.w.notifications)} {m[:140]!r} presses {len(gw.d.button_log)}")
    gw = fp_world(gate_text, guards_text, ceiling="unavailable", grid="9000", lease=False, end_after=1e9)
    gw.d.fp_start()
    gw.advance(120)
    if G.NOTE_FP_INERT not in gw.w.notifications or gw.d.button_log:
        pb.add(f"a lease that starts while the ceiling cannot be read: the notice, and never a press on a measured import: {sorted(gw.w.notifications)} {len(gw.d.button_log)} presses")
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1500.0", end_after=1e9)
    gw.put(G.CEIL, "unavailable")
    gw.advance(40)
    gw.put(G.CEIL, "5000")
    gw.advance(120)
    if gw.w.notifications:
        pb.add(f"a ceiling that is unreadable for 40 s only (a reload) raises nothing: {sorted(gw.w.notifications)}")
    for ok in ("0.0", "0", "-0.0", "5000", "abc", "100001", "nan"):
        gw = fp_world(gate_text, guards_text, ceiling=ok, grid="1500.0", end_after=1e9)
        gw.advance(200)
        if G.NOTE_FP_INERT in gw.w.notifications:
            pb.add(f"a ceiling that reads {ok!r} is readable: no notice")
        gw = fp_world(gate_text, guards_text, ceiling="5000", grid="1500.0", end_after=1e9)
        gw.advance(5)
        gw.put(G.CEIL, ok)
        gw.advance(200)
        if G.NOTE_FP_INERT in gw.w.notifications:
            pb.add(f"a ceiling that changes to {ok!r} during a lease is readable: no notice")
    gw = fp_world(gate_text, guards_text, ceiling="unavailable", grid="1500.0", lease=False, end_after=1e9)
    gw.advance(200)
    if gw.w.notifications:
        pb.add(f"an unreadable ceiling with no lease raises nothing: {sorted(gw.w.notifications)}")
    gw = fp_world(gate_text, guards_text, ceiling="unavailable", grid="1500.0", end_after=1e9)
    gw.advance(600)
    if gw.w.notifications:
        pb.add(f"a ceiling that is unreadable when Home Assistant starts is not acted on until it changes (nothing is armed while it already stands): {sorted(gw.w.notifications)}")
    # the notice does not hold the guard's run: a breach that arrives while the notice waits is still ended after its 30 s once the ceiling is back (the notice is its own automation)
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="9000", end_after=1e9)
    gw.advance(5)
    gw.put(G.CEIL, "unavailable")
    gw.advance(10)
    t0 = gw.w.t
    gw.put(G.CEIL, "5000")
    gw.advance(45)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30]:
        pb.add(f"the notice's minute of grace does not hold the import guard: {[round(x - t0) for x in gw.d.pressed(F)]}")


def stand_alone_problems(gate_text: str, guards_text, pb: Problems) -> None:
    """Each guard file stands alone: with the other two absent it still ends its lease, and a lease with only the other two present is not touched by it."""
    F, D = G.END_FP, G.END_DUMP
    for i, name in enumerate(GUARD_NAMES):
        only = (guards_text[i],)
        if name == "dump":
            gw = G.GateWorld(gate_text, only, poll=False, start_ha=False)
            gw.put(G.HOLD, "clear")
            gw.d.dump_start(latched=40.0)
            gw.ha.start()
            gw.advance(2)
            gw.put(G.HOLD, "held")
            want = D
        elif name == "time":
            gw = fp_world(gate_text, only, end_after=20.0)
            gw.put(G.TL, "off")
            want = F
        else:
            gw = fp_world(gate_text, only, ceiling="5000", grid="1000", end_after=20.0)
            gw.put(G.GRID, "9000")
            want = F
        gw.advance(320)
        if [e for _t, e in gw.d.button_log] != [want]:
            pb.add(f"the {name} guard file alone: presses {[e[-24:] for _t, e in gw.d.button_log]}")
        others = tuple(x for j, x in enumerate(guards_text) if j != i)
        gw = G.GateWorld(gate_text, others, poll=False, start_ha=False)
        gw.ha.start()
        gw.advance(2)
        if any(a.id in (GUARD_AUTOS[name]) for a in gw.ha.automations):
            pb.add(f"the {name} guard is present although its file is left out")


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
    for pre in ("unavailable", None):
        gw = dump_world(gate_text, guards_text, hold=pre, eff="40")
        gw.put(G.HOLD, "held")
        gw.advance(120)
        silent(gw, f"the hold sensor turning on from {pre!r} during a Dump lease", pb)
    for pre in ("unavailable", "unknown", None):
        gw = dump_world(gate_text, guards_text, eff=pre)
        gw.put(G.EFF, "80")
        gw.advance(120)
        silent(gw, f"the reserve sensor reading 80 from {pre!r} above the latched Stop SOC", pb)
    # SG-3: the plan's hold sensor reads unknown as a VALUE (nothing is active and a record cannot be read): a Hold battery or Skip tonight that turns it to held from that reading is a real
    # change and ends the lease; the same from unavailable, or from nothing, is not (above)
    gw = dump_world(gate_text, guards_text, hold="unknown")
    t0 = gw.w.t
    gw.put(G.HOLD, "held", {"held_by": "hold_battery"})
    gw.advance(40)
    pressed_once(gw, D, t0, 1.0, "a Hold battery turns the hold sensor from its own unknown to held", pb, G.NOTE_DUMP, ("Hold battery", "hold_battery"))
    gw = dump_world(gate_text, guards_text, hold="clear")
    t0 = gw.w.t
    gw.put(G.HOLD, "unknown")
    gw.advance(30)
    silent(gw, "the hold sensor turning unknown during a Dump lease (a record cannot be read) is not a hold", pb)
    gw.put(G.HOLD, "held", {"held_by": "skip_tonight"})
    gw.advance(40)
    pressed_once(gw, D, t0 + 30, 1.0, "Skip tonight turns the hold sensor from unknown to held after it went clear, unknown", pb, G.NOTE_DUMP, ("Hold battery, Skip tonight", "skip_tonight"))
    for frm in ("held", "clear"):
        gw = dump_world(gate_text, guards_text, hold=frm)
        gw.put(G.HOLD, "unknown")
        gw.advance(60)
        if frm == "clear":
            silent(gw, f"the hold sensor going from {frm} to unknown", pb)
    # R17: a lease that ends in the very instant a hold turns on (the guard's run is already queued) is not ended again: the final condition needs the lease
    gw = dump_world(gate_text, guards_text, eff="40", latched=40.0)
    t0 = gw.w.t

    def hold_and_end():
        gw.put(G.HOLD, "held")
        gw.d.dump_end()
    gw.w.at(t0 + 5.0, hold_and_end)
    gw.advance(60)
    silent(gw, "a Dump lease that ends in the very instant a hold turns on (the guard's run finds no lease)", pb)
    if any("already running" in x for x in gw.w.warnings):
        pb.add(f"R17 scenario: a trigger was dropped: {gw.w.warnings[:1]}")
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
    gw.advance(400)
    if len(gw.d.pressed(D)) != 2:
        pb.add(f"a trigger that arrives while the Dump guard is busy is dropped, never queued for later: presses at {[round(t - t0) for t in gw.d.pressed(D)]}")
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
    # the minute after a press: a trigger that arrives meanwhile is dropped (mode single), so one violation is one press and no run waits behind it (a second run would only decline)
    gw = fp_world(gate_text, guards_text, end_after=1e9)
    t0 = gw.w.t
    gw.put(G.TL, "off")
    gw.advance(310)
    gw.put(G.TL, "on")
    gw.advance(5)
    gw.put(G.TL, "off")
    gw.advance(400)
    if [round(x - t0) for x in gw.d.pressed(F)] != [300] or G.NOTE_FP_DECLINED in gw.w.notifications:
        pb.add(f"the time guard's minute after a press drops a trust loss that arrives in it: presses {[round(x - t0) for x in gw.d.pressed(F)]} notifications {sorted(gw.w.notifications)}")
    gw = fp_world(gate_text, guards_text, ceiling="5000", grid="4000", end_after=1e9)
    t0 = gw.w.t
    gw.put(G.GRID, "6000")
    gw.advance(35)
    gw.put(G.GRID, "4000")
    gw.advance(5)
    gw.put(G.GRID, "6000")
    gw.advance(150)
    if [round(x - t0) for x in gw.d.pressed(F)] != [30] or G.NOTE_FP_DECLINED in gw.w.notifications:
        pb.add(f"the import guard's minute after a press drops a breach that arrives in it: presses {[round(x - t0) for x in gw.d.pressed(F)]} notifications {sorted(gw.w.notifications)}")


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
ALL_PARTS = ("static", "gate", "plan", "script", "verdict", "notice", "guards", "alone", "restart")


def battery(gate_text: str = GATE_TEXT, guards_text: tuple = GUARDS_TEXT, parts: tuple = ALL_PARTS, first_only: bool = True) -> Problems:
    """The proofs a mutant must fail, in the order they are tried. `guards_text` is the three guard files."""
    pb = Problems(first_only)
    try:
        if "static" in parts:
            only = "gate" if "gate" in parts else ("guards" if ("guards" in parts or "verdict" in parts or "notice" in parts) else "both")
            static_problems(gate_text, guards_text, only, pb)
        if "gate" in parts:
            gate_problems(gate_text, pb)
        if "plan" in parts:
            plan_problems(gate_text, pb)
        if "script" in parts:
            script_problems(gate_text, pb)
        if "verdict" in parts:
            verdict_problems(gate_text, guards_text, pb)
        if "notice" in parts:
            notice_problems(gate_text, guards_text, pb)
        if "guards" in parts:
            guard_problems(gate_text, guards_text, pb)
        if "alone" in parts:
            stand_alone_problems(gate_text, guards_text, pb)
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


def guards_with(i: int, text: str) -> tuple:
    """The three guard texts with the i-th replaced."""
    return tuple(text if j == i else g for j, g in enumerate(GUARDS_TEXT))


sp = static_problems(GATE_TEXT, GUARDS_TEXT)
check("the four files load with no repeated key; the gate has exactly the two binary sensors, the ceiling helper (no initial value) and the guarded start script; each guard file has exactly its automation "
      "(the import guard file a second one, the notice, that never presses); the state, `reasons` and `blocked_by` templates of each gate share ONE rule block; every entity read exists in the repository; "
      "the write vocabulary is pinned (each service aimed at its one entity); the guards press only the two END buttons, once in the file, with no restart, reload, event or start trigger; the two Free Power guards "
      "carry the same verdict and press only on an empty one; only the Free Power time guard mentions the time trust package; the headers state the rules and the limits; ASCII, LF, no site value",
      sp == [], str(list(sp[:4])))
check("the static scans are live: each flags an injected fault (a start button in a guard, a Home Assistant start trigger, a service on a foreign entity, a site address, an initial value, a changed copy of the "
      "rule block, a changed copy of the verdict, an unpinned notification id, a guard that mentions the time trust package without being on its allow-list, a guard file with a second press)",
      bool(static_problems(GATE_TEXT, guards_with(0, GUARDS_TEXT[0].replace("button.ecco_clock_dongle_end_dump_to_grid_restore_now", "button.ecco_clock_dongle_start_dump_to_grid_now", 1)), "guards"))
      and bool(static_problems(GATE_TEXT, guards_with(0, GUARDS_TEXT[0].replace("    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "    triggers:\n      - trigger: homeassistant\n        event: start\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", 1)), "guards"))
      and bool(static_problems(GATE_TEXT, guards_with(1, GUARDS_TEXT[1].replace("notification_id: ecco_lease_guard_free_power_declined", "notification_id: ecco_lease_guard_free_power_other", 1)), "guards"))
      and bool(static_problems(GATE_TEXT, guards_with(2, GUARDS_TEXT[2].replace("{%- if op != 'off' -%}", "{%- if op == 'on' -%}", 1)), "guards"))
      and bool(static_problems(GATE_TEXT, guards_with(0, GUARDS_TEXT[0] + "# see ecco_time_trust.yaml\n"), "guards"))
      and bool(static_problems(GATE_TEXT, guards_with(2, GUARDS_TEXT[2].replace("      - delay: \"00:01:00\"\n\n  # THE NOTICE", "      - action: button.press\n        target:\n          entity_id: button.ecco_clock_dongle_end_free_power_restore_now\n      - delay: \"00:01:00\"\n\n  # THE NOTICE", 1)), "guards"))
      and bool(static_problems(GATE_TEXT.replace("entity_id: input_text.ecco_plan_last_result", "entity_id: input_text.ecco_foreign", 1), GUARDS_TEXT, "gate"))
      and bool(static_problems(GATE_TEXT + "# 203.0.113.5\n", GUARDS_TEXT, "gate")) and bool(static_problems(GATE_TEXT.replace("    min: 0\n    max: 100000", "    min: 0\n    initial: 0\n    max: 100000", 1), GUARDS_TEXT, "gate"))
      and bool(static_problems(GATE_TEXT.replace("tl != 'on'", "tl == 'off'", 1), GUARDS_TEXT, "gate")))

# the site renderer, the repository's packages, the firmware and the card: what the headers rely on
import ecco_site_render as render  # noqa: E402

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
for rel, text in [(GATE_REL, GATE_TEXT)] + list(zip(GUARDS_REL, GUARDS_TEXT)):
    spots = [m.start() for m in re.finditer(DONGLE, text)]
    try:
        rendered, counts = render.render_text(rel, text, site, render.firmware_actions(ROOT))
    except render.RenderError as exc:
        rendered, counts = "", {"error": str(exc)[:120]}
    check(f"{rel}: the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them, touches nothing else and leaves none behind",
          counts == {"entity": len(spots)} and len(spots) >= 5 and DONGLE not in rendered and "site_dongle_" in rendered, str(counts))
own_ids = package_ids(PKGS / "ecco_start_gate.yaml")
other_auto = {a["id"] for p in OTHER_PKGS.values() for a in (yaml.load(p.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}).get("automation", []) if isinstance(a, dict) and "id" in a}
guard_ids = {a["id"] for gt in GUARDS_TEXT for a in yaml.safe_load(gt)["automation"]}
check("the entities the gate package defines are defined nowhere else in the repository, its unique ids repeat no other template unique id, the guard automations' ids repeat no other automation id and the guards define no entity",
      own_ids == GATE_OWN and not (own_ids & set().union(*[package_ids(p) for p in OTHER_PKGS.values()])) and not (guard_ids & other_auto) and guard_ids == {i for ids in GUARD_AUTOS.values() for i in ids}
      and all(package_ids(ROOT / rel) == set() for rel in GUARDS_REL)
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
fwc = re.sub(r"\s*\n\s*#\s*", " ", FW_TEXT)                      # the firmware with its comment lines joined
_texts = fp_status_texts()
_dump_end = re.search(r"- id: request_dump_end\n    mode: single.*?\n  # Clear-only completion of an already-verified restore", FW_TEXT, re.S)
# the firmware automation id is split in two adjacent literals: registry/tests/test_free_power_recovery_evidence.py forbids the whole token in any HA file
_force = re.search(r"- id: dump_force_" r"restore_original\n    mode: single.*?\n  - id: ", FW_TEXT, re.S)
check("the firmware facts the Free Power guards rely on: the Free Power End is the operator's one-shot retry (the button sets free_power_operator_retry_pending, restore_free_power_snapshot consumes it as its first "
      "action, an explicit request clears free_power_operator_needed and zeroes the comms attempts, the verify-mismatch count and the next-attempt time, an automatic call is refused while operator_needed with "
      "'OPERATOR DECISION REQUIRED ... press End Free Power to retry', the lockout trips at two mismatches); the verified running status is 'ACTIVE - VERIFIED OK; %uA grid charge; automatic restore armed' and "
      "no other text the firmware publishes starts with it; the ends-at text is the local time in the exact form, or Inactive, or Active - end time unavailable, every 10 s; the dongle's own watchdog ends a "
      "lease that is past its end; and the status vocabulary the suite refuses one by one is read from the firmware",
      fw.count("id(free_power_operator_retry_pending) = true;") == 1
      and "id(free_power_operator_retry_this_call) = id(free_power_operator_retry_pending); id(free_power_operator_retry_pending) = false;" in fw
      and "bool explicit_operator_request = id(free_power_operator_retry_this_call); if (explicit_operator_request) { id(free_power_operator_needed) = false; id(free_power_comms_restore_attempts) = 0; "
          "id(free_power_verify_mismatch_count) = 0; id(free_power_restore_next_attempt_ms) = 0;" in fw
      and "if (!explicit_operator_request) { if (id(free_power_operator_needed)) { id(free_power_restore_gate_ok) = false;" in fw
      and "OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying, or press End Free Power to retry" in fw
      and "if (id(free_power_verify_mismatch_count) >= 2) {" in fw
      and 'snprintf(msg, sizeof(msg), "ACTIVE - VERIFIED OK; %uA grid charge; automatic restore armed", id(free_power_target_reg230));' in fw
      and re.fullmatch(r"ACTIVE - VERIFIED OK; \d+A grid charge; automatic restore armed", G.FP_VERIFIED) is not None
      and len(_texts) >= 60 and not [s for s in _texts if s.startswith("ACTIVE - VERIFIED OK")] and "OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying" in _texts
      and re.search(r'name: "Free Power Ends At"\s+id: free_power_ends_at\s+update_interval: 10s', FW_TEXT) is not None
      and 'if (!id(free_power_active_persisted)) return std::string("Inactive"); auto now = id(ntp_time).now(); if (!now.is_valid() || id(free_power_end_epoch) == 0) return std::string("Active - end time unavailable");' in fw
      and 'strftime(b, sizeof(b), "%Y-%m-%d %H:%M:%S", &tm_buf); return std::string(b);' in fw
      and "if (id(free_power_restore_requested)) return true;" in fw and "return (uint32_t) now.timestamp >= id(free_power_end_epoch);" in fw, f"{len(_texts)} status texts")
check("the firmware facts the Dump guard relies on: the Dump End is NOT an operator retry (request_dump_end only records restore_requested and runs the shared worker; it never touches the one-shot bypass, the "
      "operator lockout, the backoff or the mismatch count; the worker refuses while the lockout stands unless Force Restore Original set the bypass, and that is the only place it is set; the dongle's own "
      "watchdog calls the same script every 15 s, so a press on a lease that is already ending changes nothing the dongle would not do itself)",
      _dump_end is not None and all(w not in _dump_end.group(0) for w in ("dump_force_restore_bypass", "dump_operator_needed", "dump_restore_next_attempt_ms", "dump_comms_restore_attempts", "dump_verify_mismatch_count"))
      and "id(dump_restore_requested) = true;" in _dump_end.group(0) and "script.execute: restore_dump_to_grid_snapshot" in _dump_end.group(0)
      and "(!id(dump_operator_needed) || id(dump_force_restore_this_call))" in fw and fw.count("id(dump_force_restore_bypass) = true;") == 1
      and _force is not None and "id(dump_force_restore_bypass) = true;" in _force.group(0)
      and "Calling it when a restore is merely due for retry (nothing new to request) is idempotent" in fwc,
      f"{_dump_end is not None} {_force is not None}")
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
sys.path.append(str(ROOT / "registry" / "tests"))
import _sgt1_scope as _sgt1  # noqa: E402
import _scope_chain as _sc  # noqa: E402

_post = [e.id for e in _sc.POST_EXPORT_ENTRIES]
# The manifest as sgt1 left it: the edit of every LATER chain entry undone, newest first (a reverter that cannot apply raises, so a later entry that does not undo exactly fails this suite loudly). The pins
# below that say "the last five stanzas" and "the entry pins the manifest as it is" are about sgt1's own state, so they are read as of sgt1 and keep passing after a later entry (exc1) is appended.
MANIFEST_AT_SGT1 = MANIFEST_TEXT
for _later in reversed(_sc.POST_EXPORT_ENTRIES[_post.index("sgt1") + 1:]):
    if _sc.HA_MANIFEST in _later.reverts:
        MANIFEST_AT_SGT1 = _later.reverts[_sc.HA_MANIFEST](MANIFEST_AT_SGT1)
man = yaml.safe_load(MANIFEST_TEXT)
man_sgt1 = yaml.safe_load(MANIFEST_AT_SGT1)
stanzas = [p for p in man["home_assistant_packages"] if p["source"] in (GATE_REL,) + GUARDS_REL]
check("the deployment manifest lists the gate and each of the three guard files exactly once, to /config/packages, by ssh_file_copy, with restart_required false (a reload installs each: the input_number "
      "helpers, the template entities and the scripts; the automations), after the time trust stanza, and its comment blocks say not installed, soft, the card is not changed, that each guard needs the "
      "owner's separate authorisation, and that the Free Power press is the operator's End",
      stanzas == [{"source": GATE_REL, "destination": "/config/packages/ecco_start_gate.yaml", "method": "ssh_file_copy", "restart_required": False}]
      + [{"source": rel, "destination": "/config/packages/" + rel.rsplit("/", 1)[1], "method": "ssh_file_copy", "restart_required": False} for rel in GUARDS_REL]
      and [p["source"] for p in man_sgt1["home_assistant_packages"]][-5:] == ["home-assistant/packages/ecco_time_trust.yaml", GATE_REL, *GUARDS_REL]
      and all(s in re.sub(r"\s*\n\s*#\s*", " ", MANIFEST_TEXT) for s in ("Start gate - sgt1 (NOT installed, NOT LIVE-PROVEN)", "THE GATE IS SOFT", "the Energy Actions card is NOT changed in this step",
                                                                      "reload the input_number helpers first, then the template entities, then the scripts",
                                                                      "Lease guard, Dump to Grid - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION",
                                                                      "Lease guard, Free Power time trust - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION",
                                                                      "Lease guard, Free Power grid import - sgt1 (NOT installed, NOT LIVE-PROVEN). THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION",
                                                                      "THAT PRESS IS THE OPERATOR'S END", "at most once per lease", "reload the automations: no restart")))
README = (PKGS / "README.md").read_text(encoding="utf-8")
README_FLAT = re.sub(r"\s+", " ", README)
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if ln.startswith("- **Shared start gate, guarded Free Power start")), "")
check("the packages README has a Start gate and lease guards section that names every entity, every code of the gate and of the script, the soft gate, that the card is not changed, the ceiling helper with no initial "
      "value, NOT_CONFIGURED and what an unreadable ceiling does, that no charger-loss factor is applied, the guards' delays and constants, that the Free Power press is the operator's End and what a verified running "
      "lease is, the once-per-lease marker, what a restart does not do, the install routes (no restart), the limits about the detector and smr1, the follow-ups not built, and what is not established",
      "## Start gate and lease guards" in README and all(c in README_FLAT for c in COMMON_CODES + EXPORT_CODES + CHARGE_CODES)
      and all(s in README_FLAT for s in ("`binary_sensor.ecco_charge_start_allowed`", "`binary_sensor.ecco_export_start_allowed`", "`input_number.ecco_grid_import_ceiling_w`", "`script.ecco_free_power_start_guarded`", "ecco_lease_guard_dump_end",
                                         "ecco_lease_guard_free_power_time", "ecco_lease_guard_free_power_import", "ecco_lease_guard_free_power_import_inert", "`ecco_lease_guard_dump.yaml`", "`ecco_lease_guard_free_power_time.yaml`",
                                         "`ecco_lease_guard_free_power_import.yaml`", "GATE_UNREADABLE", "GATE_BLOCKED", "SCHEDULED_START_RUNNING", "LIMIT_UNREADABLE", "LIMIT_OUT_OF_RANGE", "POWER_INVALID", "DURATION_INVALID", "GATE_CLOSED",
                                         "NOT_CONFIRMED", "LIMIT_LOWERED", "FIRMWARE_REFUSED", "START_FAILED", "NO_ANSWER", "The gate is SOFT", "is NOT changed in this step", "no initial value", "NOT_CONFIGURED", "never a target",
                                         "No charger-loss factor and no margin is applied", "5 minutes", "30 seconds", "up to 15 s", "never end a lease by themselves", "each need the owner's separate install authorisation",
                                         "reload the input_number helpers first", "reload the automations", "never \"reload all\"", "no restart", "bpd1, pinned", "smr1", "NOT ESTABLISHED",
                                         "Recalled from Home Assistant core and not verified", "no target-reached guard", "does not use the Free Power schedule's result text", "ecco_free_power_start_blocked",
                                         "ONLY a readable 0", "THIS run turned it on", "put back", "The Free Power press is the operator's End", "ACTIVE - VERIFIED OK", "at most once per lease", "ecco_lease_guard_free_power_declined",
                                         "ecco_lease_guard_free_power_ended", "ecco_lease_guard_free_power_inert", "Follow-ups, not built here", "target-reached guard", "card wiring", "BYPASS", "the Dump END is not an operator retry",
                                         "free_power_operator_retry_pending", "restore_free_power_snapshot", "last changed")))
check("the CHANGELOG has one bullet for it that says offline, nothing installed, soft, that the card is not changed, no initial value and NOT_CONFIGURED, an unreadable ceiling, never a target, separate authorisation for "
      "each guard (three files), the operator's End and the verified running lease, no restart (restart_required: false), the detector and smr1 limits, the follow-ups, recalled and not verified, and names the suite and sgt1",
      BULLET != "" and all(s in BULLET for s in ("offline, nothing installed; the gate is SOFT", "ecco_start_gate.yaml", "ecco_lease_guard_dump.yaml", "ecco_lease_guard_free_power_time.yaml", "ecco_lease_guard_free_power_import.yaml",
                                                  "item N2", "Energy Actions card is NOT changed", "no initial value", "NOT_CONFIGURED", "IMPORT_CEILING_UNREADABLE", "never a target", "no charger-loss factor", "separate install authorisation",
                                                  "operator's End", "ACTIVE - VERIFIED OK", "at most once per lease", "restart_required: false", "start bypass detector (pinned)", "smr1", "put back",
                                                  "Recalled from Home Assistant core, not verified live", "follow-ups", "test_ecco_start_gate.py", "`sgt1`")) and BULLET.isascii())
_entry = next((e for e in _sc.POST_EXPORT_ENTRIES if e.id == "sgt1"), None)
check("the chain entry sgt1 follows ttr1 exactly as ttr1 followed bpd1: its scope module holds the manifest edit as an exact round-trip pair and the seven added files (all present), the entry pins the manifest after the edit and "
      "declares no other file, and it is sealed after ttr1 (read as of sgt1: a later entry's edit is undone first, so a later entry can follow)",
      _entry is not None and _post[_post.index("sgt1") - 1:_post.index("sgt1") + 1] == ["ttr1", "sgt1"] and _sgt1.add_sgt1_manifest(_sgt1.pre_sgt1_manifest(MANIFEST_AT_SGT1)) == MANIFEST_AT_SGT1
      and _sgt1.pre_sgt1_manifest(MANIFEST_AT_SGT1) != MANIFEST_AT_SGT1
      and _sgt1.ADDED_FILES == frozenset({GATE_REL, *GUARDS_REL, "home-assistant/tests/_start_gate_sim.py", "home-assistant/tests/test_ecco_start_gate.py", "registry/tests/_sgt1_scope.py"})
      and all((ROOT / f).is_file() for f in _sgt1.ADDED_FILES) and _entry.added_files == _sgt1.ADDED_FILES and set(_entry.reverts) == {"deployment/ha-manifest.yaml"}
      and not _entry.frozen_reverts and not _entry.deltas and not _entry.op_paths_changed and not _entry.includes_added
      and _entry.checkpoints == {"deployment/ha-manifest.yaml": __import__("hashlib").sha256(MANIFEST_AT_SGT1.encode("utf-8")).hexdigest()}, str(_post[-3:]))

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
psa = Problems()
stand_alone_problems(GATE_TEXT, GUARDS_TEXT, psa)
check("each guard stands alone: with the other two files absent it still ends its lease (the Dump guard, the Free Power time guard, the import guard), and a guard whose file is left out does not exist", psa == [], str(list(psa[:3])))
pvd = Problems()
verdict_problems(GATE_TEXT, GUARDS_TEXT, pvd)
check("the Free Power guards press the operator's End ONLY for a verified running lease and at most once per lease: every status the firmware can publish but the verified one refuses (read from the firmware), "
      "an operation in progress, an end time that is not a time in the future, a button pressed in this lease (by either guard or the operator) or unreadable; a blocked or owed restore with the lockout set is "
      "never pressed over 20 minutes of a breach or a flapping time; the second guard declines and says why", pvd == [], str(list(pvd[:3])))
pnt = Problems()
notice_problems(GATE_TEXT, GUARDS_TEXT, pnt)
check("a ceiling that cannot be read leaves the import guard inert and it says so (one notification after a minute of grace, never a press, nothing at a restart, nothing for a readable 0), and the notice never holds the guard's own run",
      pnt == [], str(list(pnt[:3])))

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
print("[6] mutation: in-memory mutants of the four packages are each caught")


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
    ("a ceiling of 0 is invalid, not unset", "{%- set c_unset = (not c_gone) and cf is number and cf == 0 -%}", "{%- set c_unset = false -%}", "all"),
    ("an unreadable ceiling counts as not configured (the silent switch-off)", "{%- set c_unset = (not c_gone) and cf is number and cf == 0 -%}", "{%- set c_unset = c_gone or (cf is number and cf == 0) -%}", "all"),
    ("an unreadable ceiling does not block", "('IMPORT_CEILING_UNREADABLE', c_gone,", "('IMPORT_CEILING_UNREADABLE', false,", "all"),
    ("an unreadable ceiling is also invalid", "('IMPORT_CEILING_INVALID', (not c_gone) and (not c_unset) and (not c_ok),", "('IMPORT_CEILING_INVALID', (not c_unset) and (not c_ok),", "all"),
    ("the unreadable code is renamed", "'IMPORT_CEILING_UNREADABLE'", "'IMPORT_CEILING_GONE'", "all"),
    ("a ceiling of none or the empty text reads as a number", "{%- set c_gone = cr in bad -%}", "{%- set c_gone = cr in ['unknown', 'unavailable'] -%}", "all"),
    ("an invalid ceiling is read as no ceiling", "('IMPORT_CEILING_INVALID', (not c_gone) and (not c_unset) and (not c_ok),", "('IMPORT_CEILING_INVALID', false,", "all"),
    ("an unset ceiling is invalid", "('IMPORT_CEILING_INVALID', (not c_gone) and (not c_unset) and (not c_ok),", "('IMPORT_CEILING_INVALID', (not c_gone) and (not c_ok),", "all"),
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
    ("the arm wait is one second", "timeout: \"00:00:05\"", "timeout: \"00:00:01\"", 0),
    ("the put-back wait is one second", "timeout: \"00:00:05\"", "timeout: \"00:00:01\"", 1),
    ("the settle delay before the press-time check is zero", "- delay:\n              seconds: 1\n", "- delay:\n              seconds: 0\n", "one"),
    ("the press-time gate check is dropped", "{%- if g != 'on' -%}GATE_CLOSED", "{%- if false -%}GATE_CLOSED", "one"),
    ("the press-time scheduled check is dropped", "{%- elif states('script.ecco_free_power_start_scheduled') != 'off' -%}SCHEDULED_START_RUNNING", "{%- elif false -%}SCHEDULED_START_RUNNING", "one"),
    ("the press-time confirmation is dropped", "{%- elif not (is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on') and", "{%- elif false and (is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on') and", "one"),
    ("the press-time limit check is dropped", "{%- elif lim < req_power -%}LIMIT_LOWERED", "{%- elif false -%}LIMIT_LOWERED", "one"),
    ("the press-time limit check refuses a request equal to the limit", "{%- elif lim < req_power -%}LIMIT_LOWERED", "{%- elif lim <= req_power -%}LIMIT_LOWERED", "one"),
    ("the press-time limit check passes a limit that cannot be read", "{%- elif lim < 0 -%}LIMIT_LOWERED", "{%- elif false -%}LIMIT_LOWERED", "one"),
    ("the press-time limit check reads an unreadable limit as a huge one", "{%- set lim = lim if (lim >= 0 and lim <= 1000000) else -1 -%}", "{%- set lim = lim if (lim >= 0 and lim <= 1000000) else 99999999 -%}", "one"),
    ("the Dump start button is pressed", "entity_id: button.ecco_clock_dongle_start_free_power_charge_now", "entity_id: button.ecco_clock_dongle_start_dump_to_grid_now", "one"),
    ("the answer wait is one second", "timeout: \"00:00:15\"", "timeout: \"00:00:01\"", "one"),
    ("a refusal at the dongle's gate counts as a begun start", "and not states('sensor.ecco_clock_dongle_free_power_status').startswith('REJECTED')", "", "one"),
    ("the transaction wait is one second", "timeout: \"00:02:00\"", "timeout: \"00:00:01\"", "one"),
    ("a press with no answer is retried as a refusal", "value_template: \"{{ answered and not began }}\"", "value_template: \"{{ not began }}\"", "one"),
    ("the success text is the schedule's proof text", "'STARTED free_power at '", "'STARTED OK - '", "one"),
    ("the refusal text is renamed", "('REFUSED ' ~ refusal.split('|')[0]", "('REJECTED ' ~ refusal.split('|')[0]", "one"),
    ("the press-time refusal text is renamed", "{%- set base = 'REFUSED ' ~ press_block.split('|')[0]", "{%- set base = 'REJECTED ' ~ press_block.split('|')[0]", "one"),
    ("a failure after the press is written as a refusal", "('FAILED START_FAILED - ", "('REFUSED START_FAILED - ", "one"),
    ("the notification id is changed", "notification_id: ecco_free_power_start_blocked\n                  title: \"ECCO: Charge Battery (Free Power) was not started\"\n                  message: \"{{ refusal.split('|')[1] }}", "notification_id: ecco_free_power_start_refused\n                  title: \"ECCO: Charge Battery (Free Power) was not started\"\n                  message: \"{{ refusal.split('|')[1] }}", "one"),
    ("the refusal notification is not raised", "message: \"{{ refusal.split('|')[1] }} (reason {{ refusal.split('|')[0] }})\"", "message: \"{{ refusal.split('|')[1] }}\"", "one"),
    ("a success does not clear the notification", "- action: persistent_notification.dismiss", "- action: persistent_notification.create", "one"),
    ("the write enable does not end off", "            then:\n              - action: switch.turn_off\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "            then:\n              - action: switch.turn_on\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "one"),
    ("the final write enable is another switch", "            then:\n              - action: switch.turn_off\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "            then:\n              - action: switch.turn_off\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_dump_to_grid_write_enable\n", "one"),
    ("the unanswered press leaves the write enable on", "                      - action: switch.turn_off\n                        continue_on_error: true\n                        target:\n                          entity_id: switch.ecco_clock_dongle_free_power_write_enable\n                      - wait_template: \"{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}\"", "                      - action: switch.turn_on\n                        continue_on_error: true\n                        target:\n                          entity_id: switch.ecco_clock_dongle_free_power_write_enable\n                      - wait_template: \"{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}\"", "one"),
    ("the mode is queued (two starts at once would both run)", "    mode: single\n    fields:", "    mode: queued\n    fields:", "one"),
    ("the result text is the schedule's helper", "entity_id: input_text.ecco_plan_last_result\n                data:\n                  value: \"{{ ('REFUSED ' ~ refusal", "entity_id: input_text.ecco_free_power_schedule_last_result\n                data:\n                  value: \"{{ ('REFUSED ' ~ refusal", "one"),
    ("an unreadable import is also deferred, so a refusal stages and arms (R09)", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE'])", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE', 'IMPORT_UNREADABLE'])", "one"),
    ("an unreadable ceiling is also deferred", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE'])", "reject('in', ['IMPORT_HEADROOM', 'REQUEST_UNREADABLE', 'IMPORT_CEILING_UNREADABLE'])", "one"),
    ("the press-time check lets an unreadable scheduled start script pass (R12)", "{%- elif states('script.ecco_free_power_start_scheduled') != 'off' -%}SCHEDULED_START_RUNNING", "{%- elif states('script.ecco_free_power_start_scheduled') == 'on' -%}SCHEDULED_START_RUNNING", "one"),
    ("the press-time check accepts a gate that cannot be read (R13)", "{%- if g != 'on' -%}GATE_CLOSED", "{%- if g == 'off' -%}GATE_CLOSED", "one"),
    ("a refused explicit power is not put back", "value_template: \"{{ power_changed and staged_power >= 0 }}\"", "value_template: \"{{ false }}\"", "one"),
    ("a refused explicit duration is not put back", "value_template: \"{{ duration_changed and staged_duration >= 0 }}\"", "value_template: \"{{ false }}\"", "one"),
    ("the put-back writes the request again, not what was staged", "                          value: \"{{ staged_power | int(0) }}\"", "                          value: \"{{ req_power | int(0) }}\"", "one"),
    ("the put-back writes the staged power into the duration", "                          value: \"{{ staged_duration | int(0) }}\"", "                          value: \"{{ staged_power | int(0) }}\"", "one"),
    ("a staged value that could not be read is put back as -1", "value_template: \"{{ power_changed and staged_power >= 0 }}\"", "value_template: \"{{ power_changed }}\"", "one"),
    ("the put-back is made although nothing was replaced", "value_template: \"{{ power_changed and staged_power >= 0 }}\"", "value_template: \"{{ staged_power >= 0 }}\"", "one"),
    ("the put-back is not read back", "{{ ((not power_changed) or", "{{ true or ((not power_changed) or", "one"),
    ("a put-back that the dongle did not confirm is reported as done", "{%- elif p_ok and d_ok -%}", "{%- elif true -%}", "one"),
    ("the put-back note is cut off a long result text", "{{ base[:(248 - (put_back | length))] ~ ' ' ~ put_back }}", "{{ (base ~ ' ' ~ put_back)[:250] }}", "one"),
    ("the notification does not say what was put back", "{{ (' ' ~ put_back) if put_back != '' else '' }}", "", "one"),
    ("the result text does not say what was put back", "{{ base[:(248 - (put_back | length))] ~ ' ' ~ put_back }}", "{{ base[:250] }}", "one"),
    ("the write enable that was already on is turned off at the end", "                value_template: \"{{ arm_mine }}\"\n            then:\n              - action: switch.turn_off\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "                value_template: \"{{ true }}\"\n            then:\n              - action: switch.turn_off\n                continue_on_error: true\n                target:\n                  entity_id: switch.ecco_clock_dongle_free_power_write_enable\n", "one"),
    ("an unanswered press turns off a write enable that was already on", "                        value_template: \"{{ arm_mine }}\"", "                        value_template: \"{{ true }}\"", "one"),
    ("this run takes a write enable that was already on for its own", "arm_mine: \"{{ arm_before != 'on' }}\"", "arm_mine: \"{{ true }}\"", "one"),
    ("this run never takes the write enable for its own", "arm_mine: \"{{ arm_before != 'on' }}\"", "arm_mine: \"{{ false }}\"", "one"),
    ("the write enable is read from the Dump switch", "arm_before: \"{{ states('switch.ecco_clock_dongle_free_power_write_enable') }}\"", "arm_before: \"{{ states('switch.ecco_clock_dongle_dump_to_grid_write_enable') }}\"", "one"),
    ("an out-of-range limit is not told from a limit that cannot be read", "{%- elif not (limit >= 500 and limit <= 100000) -%}LIMIT_OUT_OF_RANGE", "{%- elif false -%}LIMIT_OUT_OF_RANGE", "one"),
    ("a limit that cannot be read is reported as out of range", "{%- elif limit < 0 -%}LIMIT_UNREADABLE", "{%- elif false -%}LIMIT_UNREADABLE", "one"),
    ("a limit that cannot be read does not say what it reads", "(it reads {{ limit_raw }}), so Charge Battery was not started (it fails closed).\n            {%- elif not (limit", "), so Charge Battery was not started (it fails closed).\n            {%- elif not (limit", "one"),
    ("an unreadable staged power is printed as -1", "            {%- else -%}unreadable\n            {%- endif -%}\n          duration_shown:", "            {%- else -%}{{ staged_power }}\n            {%- endif -%}\n          duration_shown:", "one"),
    ("an unreadable staged duration is printed as -1", "            {%- else -%}unreadable\n            {%- endif -%}\n          # What this run is about to replace", "            {%- else -%}{{ staged_duration }}\n            {%- endif -%}\n          # What this run is about to replace", "one"),
    ("a limit that fell is reported as unreadable at the press", "{%- elif lim < 0 -%}LIMIT_LOWERED|The effective grid charge limit can no longer be read (it reads {{ lim_raw }})", "{%- elif lim < 0 -%}LIMIT_LOWERED|The effective grid charge limit fell", "one"),
]
# ---- the guards: (label, file, old, new, mode[, the parts that must kill it]); `fp` is both Free Power guard files, so the verdict they share is mutated in both ----
V_SET_ST = "{%- set st = states('sensor.ecco_clock_dongle_free_power_status') -%}"
V_SET_OP = "{%- set op = states('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress') -%}"
V_SET_EA = "{%- set ea = states('sensor.ecco_clock_dongle_free_power_ends_at') -%}"
V_SET_EAT = "{%- set eat = strptime(ea, '%Y-%m-%d %H:%M:%S', none) -%}"
V_SET_ACT = "{%- set act = states['binary_sensor.ecco_clock_dongle_free_power_active'] -%}"
V_SET_SINCE = "{%- set since = as_timestamp(act.last_changed, none) if act is not none else none -%}"
V_SET_BT = "{%- set bt = states('button.ecco_clock_dongle_end_free_power_restore_now') -%}"
V_OP = "{%- if op != 'off' -%}"
V_ST = "{%- elif not st.startswith('ACTIVE - VERIFIED OK') -%}"
V_EA = "{%- elif eat is none or as_timestamp(eat) <= as_timestamp(now()) -%}"
V_BT = "{%- elif bt != 'unknown' and pressed is none -%}"
V_PR = "{%- elif pressed is not none and pressed >= since -%}"
VERD = ("verdict",)
GUARD_MUTANTS = [
    # ---- the Dump guard ----
    ("the Dump guard waits for a hold that never comes", "dump", "        to: \"held\"\n        id: hold", "        to: \"clear\"\n        id: hold", "one"),
    ("the Dump guard ignores a change of the reserve", "dump", "        to: ~\n        id: reserve", "        to: \"nan\"\n        id: reserve", "one"),
    ("the Dump guard ignores a lease that starts", "dump", "        to: \"on\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING. A Home Assistant start", "        to: \"off\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING. A Home Assistant start", "one"),
    ("the Dump guard acts on a change from unavailable or unknown (no check of the old state)", "dump", "and trigger.from_state.state not in (['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown']) }}", "and true }}", "one"),
    ("the Dump guard refuses a change from the hold sensor's own unknown (SG-3 undone)", "dump", "(['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown'])", "['unavailable', 'unknown']", "one"),
    ("the Dump guard acts on a reserve that changes from unknown", "dump", "(['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown'])", "['unavailable']", "one"),
    ("the Dump guard acts on a hold that turns on from unavailable", "dump", "(['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown'])", "([] if trigger.id == 'hold' else ['unavailable', 'unknown'])", "one"),
    ("the Dump guard acts on a change from unavailable", "dump", "(['unavailable'] if trigger.id == 'hold' else ['unavailable', 'unknown'])", "['unknown']", "one"),
    ("the Dump guard acts on a change from nothing", "dump", "{{ trigger.from_state is not none", "{{ trigger.from_state is none or true", "one"),
    ("the Dump guard acts with no lease", "dump", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        state: \"on\"\n    actions:", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        state: \"off\"\n    actions:", "one"),
    ("the Dump guard does not wait for the latched Stop SOC", "dump", "timeout: \"00:00:15\"", "timeout: \"00:00:01\"", "one"),
    ("the Dump guard waits a minute for the latched Stop SOC", "dump", "timeout: \"00:00:15\"", "timeout: \"00:01:00\"", "one"),
    ("the Dump guard's wait ignores a hold", "dump", "             or is_state('sensor.ecco_plan_export_hold', 'held')\n", "", "one"),
    ("the Dump guard's wait ignores the end of the lease", "dump", "          {{ not is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')\n             or is_state('sensor.ecco_plan_export_hold', 'held')", "          {{ is_state('sensor.ecco_plan_export_hold', 'held')", "one"),
    ("the Dump guard ends a lease when the reserve equals its Stop SOC", "dump", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ reserve >= 0 and latched >= 0 and reserve >= latched }}\"", "one"),
    ("the Dump guard judges the reserve with no latched value", "dump", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ reserve >= 0 and reserve > latched }}\"", "one"),
    ("the Dump guard never judges the reserve", "dump", "above: \"{{ reserve >= 0 and latched >= 0 and reserve > latched }}\"", "above: \"{{ false }}\"", "one"),
    ("the Dump guard needs both a hold and a reserve", "dump", "value_template: \"{{ lease and (held_now or above) }}\"", "value_template: \"{{ lease and (held_now and above) }}\"", "one"),
    ("the Dump guard's final condition no longer needs the lease (R17)", "dump", "value_template: \"{{ lease and (held_now or above) }}\"", "value_template: \"{{ held_now or above }}\"", "one"),
    ("the Dump guard ends a lease on any hold reading but clear", "dump", "held_now: \"{{ hold == 'held' }}\"", "held_now: \"{{ hold != 'clear' }}\"", "one"),
    ("the Dump guard accepts a reserve above 100", "dump", "{{ r if (r >= 0 and r <= 100) else (-1 if r < 0 else -2) }}", "{{ r if (r >= 0) else (-1 if r < 0 else -2) }}", "one"),
    ("the Dump guard reads an unreadable latched Stop SOC as 0", "dump", "{%- set s = states('sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc') | float(-1) -%}", "{%- set s = states('sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc') | float(0) -%}", "one"),
    ("the Dump guard presses the Free Power End button", "dump", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now", "one"),
    ("the Dump guard presses the Dump Start button", "dump", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "entity_id: button.ecco_clock_dongle_start_dump_to_grid_now", "one"),
    ("the Dump guard presses nothing", "dump", "      - action: button.press\n        target:\n          entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now\n", "", "one"),
    ("the Dump guard does not pause after a press", "dump", "      - delay: \"00:01:00\"\n", "      - delay: \"00:00:01\"\n", "one"),
    ("the Dump guard pauses ten minutes after a press", "dump", "      - delay: \"00:01:00\"\n", "      - delay: \"00:10:00\"\n", "one"),
    ("the Dump guard raises no notification", "dump", "          notification_id: ecco_lease_guard_dump_ended", "          notification_id: ecco_lease_guard_dump_end", "one"),
    ("the Dump guard's notification does not say why", "dump", "{% if held_now %}a Hold battery, Skip tonight or Prepare for power cut turned on", "{% if held_now %}something happened", "one"),
    ("the Dump guard is not single", "dump", "    mode: single\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "    mode: queued\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id: sensor.ecco_plan_export_hold", "one"),
    # ---- the Free Power time guard ----
    ("the time guard fires when the leases sensor turns on", "time", "        to: \"off\"\n        id: trust_lost", "        to: \"on\"\n        id: trust_lost", "one"),
    ("the time guard ignores a lease that starts", "time", "        to: \"on\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING (on or off)", "        to: \"off\"\n        id: lease_started\n    conditions:\n      # A change FROM A READING (on or off)", "one"),
    ("the time guard acts on a change from unavailable", "time", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off', 'unavailable', 'unknown'] }}", "one"),
    ("the time guard acts on a change from nothing", "time", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ trigger.from_state is none or trigger.from_state.state in ['on', 'off'] }}", "one"),
    ("the time guard acts on any trigger", "time", "{{ trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] }}", "{{ true }}", "one"),
    ("the time guard acts with no lease", "time", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n        state: \"on\"\n      # The sensor must READ off", "      - condition: state\n        entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n        state: \"off\"\n      # The sensor must READ off", "one"),
    ("the time guard also counts from a sensor that cannot be read", "time", "{{ is_state('binary_sensor.ecco_time_trusted_for_leases', 'off') }}\"\n    actions:", "{{ not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\"\n    actions:", "one"),
    ("the time guard waits one minute", "time", "timeout: \"00:05:00\"", "timeout: \"00:01:00\"", "one"),
    ("the time guard waits ten minutes", "time", "timeout: \"00:05:00\"", "timeout: \"00:10:00\"", "one"),
    ("the time guard's wait ignores the recovery of the time", "time", "             or is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\n        timeout: \"00:05:00\"", "             }}\n        timeout: \"00:05:00\"", "one"),
    ("the time guard's wait ignores the end of the lease", "time", "          {{ not is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             or is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "          {{ is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "one"),
    ("the time guard goes on although the time is trusted again", "time", "          {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             and not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}", "          {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') }}", "one"),
    ("the time guard goes on only while the sensor reads off", "time", "             and not is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\n      # THE VERDICT", "             and is_state('binary_sensor.ecco_time_trusted_for_leases', 'off') }}\n      # THE VERDICT", "one"),
    ("the time guard presses the Dump End button", "time", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "one"),
    ("the time guard does not pause after a press", "time", "      - delay: \"00:01:00\"\n", "      - delay: \"00:00:01\"\n", "one"),
    ("the time guard's notification does not say why", "time", "has not read on for 5 minutes (it reads", "has changed (it reads", "one"),
    # ---- the Free Power import guard ----
    ("the import guard treats a ceiling of 0.5 W as a ceiling", "import", "c >= 1 and c <= 100000", "c > 0 and c <= 100000", "all"),
    ("the import guard treats a ceiling above 100000 W as a ceiling", "import", "c >= 1 and c <= 100000", "c >= 1", "all"),
    ("the import guard ends a lease at exactly the ceiling", "import", "g is number and g == g and g > c", "g is number and g == g and g >= c", "all"),
    ("the import guard compares the import with a fixed number", "import", "g is number and g == g and g > c", "g is number and g == g and g > 5000", "all"),
    ("the import guard acts with no lease", "import", "{%- set breached = is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and c >= 1", "{%- set breached = c >= 1", "all"),
    ("the import guard acts on an unreadable import", "import", "and g is number and g == g and g > c", "and (g is not number or g > c)", "all"),
    ("the import guard waits ten seconds", "import", "timeout: \"00:00:30\"", "timeout: \"00:00:10\"", "one"),
    ("the import guard waits five minutes", "import", "timeout: \"00:00:30\"", "timeout: \"00:05:00\"", "one"),
    ("the import guard goes on although the breach is over", "import", "      - condition: template\n        value_template: >-\n          {%- set c = states('input_number.ecco_grid_import_ceiling_w') | float(0) -%}\n          {%- set g = states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp') | float(none) -%}\n          {%- set breached = is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and c >= 1 and c <= 100000 and g is number and g == g and g > c -%}\n          {{ breached }}\n", "      - condition: template\n        value_template: \"{{ true }}\"\n", "one"),
    ("the import guard's wait never ends early", "import", "          {{ not breached }}\n        timeout: \"00:00:30\"", "          {{ false }}\n        timeout: \"00:00:30\"", "one"),
    ("the import guard presses the Dump End button", "import", "entity_id: button.ecco_clock_dongle_end_free_power_restore_now", "entity_id: button.ecco_clock_dongle_end_dump_to_grid_restore_now", "one"),
    ("the import guard does not pause after a press", "import", "      - delay: \"00:01:00\"\n", "      - delay: \"00:00:01\"\n", "one"),
    ("the import guard reads the ceiling from another helper", "import", "states('input_number.ecco_grid_import_ceiling_w') | float(0)", "states('input_number.ecco_plan_revision') | float(0)", "all"),
    ("the import guard reads the house power", "import", "states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp') | float(none)", "states('sensor.ecco_clock_dongle_ecco_load_power') | float(none)", "all"),
    # ---- the notice of the import guard (SG-4): its own automation, it only says so ----
    ("the notice fires with no lease", "import", "{{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             and states('input_number.ecco_grid_import_ceiling_w') in ['unknown', 'unavailable'] }}", "{{ states('input_number.ecco_grid_import_ceiling_w') in ['unknown', 'unavailable'] }}", "all", ("notice",)),
    ("the notice counts only an unknown ceiling", "import", "in ['unknown', 'unavailable']", "in ['unknown']", "all", ("notice",)),
    ("the notice counts a ceiling of 0 as unreadable", "import", "in ['unknown', 'unavailable']", "in ['unknown', 'unavailable', '0.0']", "all", ("notice",)),
    ("the notice has no minute of grace", "import", "        timeout: \"00:01:00\"", "        timeout: \"00:00:01\"", "one", ("notice",)),
    ("the notice waits five minutes", "import", "        timeout: \"00:01:00\"", "        timeout: \"00:05:00\"", "one", ("notice",)),
    ("the notice is raised although the ceiling is readable again", "import", "      - condition: template\n        value_template: >-\n          {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')\n             and states('input_number.ecco_grid_import_ceiling_w') in ['unknown', 'unavailable'] }}\n      - action: persistent_notification.create", "      - action: persistent_notification.create", "one", ("notice",)),
    ("the notice does not say that the guard is inert", "import", "active, so it cannot know whether a ceiling is configured and it is INERT", "active, so it is fine", "one", ("notice",)),
    # ---- the verdict of the Free Power guards (SG-1), in BOTH files ----
    ("the verdict ignores the operation flag", "fp", V_OP, "{%- if false -%}", "one", VERD),
    ("the verdict lets an operation flag that cannot be read pass", "fp", V_OP, "{%- if op == 'on' -%}", "one", VERD),
    ("the verdict reads the Dump operation flag", "fp", V_SET_OP, "{%- set op = states('binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress') -%}", "one", VERD),
    ("the verdict ignores the status", "fp", V_ST, "{%- elif false -%}", "one", VERD),
    ("the verdict accepts any status that starts with ACTIVE", "fp", "st.startswith('ACTIVE - VERIFIED OK')", "st.startswith('ACTIVE')", "one", VERD),
    ("the verdict refuses only END REQUESTED (a deny-list of one)", "fp", V_ST, "{%- elif st.startswith('END REQUESTED') -%}", "one", VERD),
    ("the verdict refuses only the states the reviewer named (a deny-list)", "fp", V_ST, "{%- elif st.startswith(('END REQUESTED', 'RESTORE', 'RECOVERY', 'OPERATOR DECISION', 'ACTIVATION VERIFY', 'FORCE')) -%}", "one", VERD),
    ("the verdict reads the Dump status", "fp", V_SET_ST, "{%- set st = states('sensor.ecco_clock_dongle_dump_to_grid_status') -%}", "one", VERD),
    ("the verdict ignores the end time", "fp", V_EA, "{%- elif false -%}", "one", VERD),
    ("the verdict lets an end time that cannot be read pass", "fp", "eat is none or as_timestamp(eat) <= as_timestamp(now())", "eat is not none and as_timestamp(eat) <= as_timestamp(now())", "one", VERD),
    ("the verdict lets an end time that is exactly now pass", "fp", "as_timestamp(eat) <= as_timestamp(now())", "as_timestamp(eat) < as_timestamp(now())", "one", VERD),
    ("the verdict presses only a lease whose end is in the past", "fp", "as_timestamp(eat) <= as_timestamp(now())", "as_timestamp(eat) >= as_timestamp(now())", "one", VERD),
    ("the verdict reads the end time as a date", "fp", V_SET_EAT, "{%- set eat = strptime(ea, '%Y-%m-%d', none) -%}", "one", VERD),
    ("the verdict reads the Dump end time", "fp", V_SET_EA, "{%- set ea = states('sensor.ecco_clock_dongle_dump_to_grid_ends_at') -%}", "one", VERD),
    ("the verdict ignores a press of END in this lease", "fp", V_PR, "{%- elif false -%}", "one", VERD),
    ("the verdict counts a press in the very instant the lease began as before it", "fp", "pressed >= since", "pressed > since", "one", VERD),
    ("the verdict dates the lease by the last update of its flag, not the last change", "fp", "act.last_changed", "act.last_updated", "one", VERD),
    ("the verdict dates the lease by the Dump lease flag", "fp", V_SET_ACT, "{%- set act = states['binary_sensor.ecco_clock_dongle_dump_to_grid_active'] -%}", "one", VERD),
    ("the verdict reads the Dump End button for the marker", "fp", V_SET_BT, "{%- set bt = states('button.ecco_clock_dongle_end_dump_to_grid_restore_now') -%}", "one", VERD),
    ("the verdict lets an End button that cannot be read pass", "fp", V_BT, "{%- elif false -%}", "one", VERD),
    ("the verdict lets any text but unknown pass for an End button", "fp", "bt != 'unknown' and pressed is none", "bt == 'unavailable'", "one", VERD),
    ("the press is made whatever the verdict says", "fp", "value_template: \"{{ verdict == '' }}\"", "value_template: \"{{ true }}\"", "one", VERD),
    ("the press is made only when the verdict names a reason", "fp", "value_template: \"{{ verdict == '' }}\"", "value_template: \"{{ verdict != '' }}\"", "one", VERD),
    ("a declined press says nothing about why", "fp", "pressed nothing: {{ verdict }}.", "pressed nothing: nothing.", "one", VERD),
    ("the press no longer says that it is the operator's End", "fp", "THIS PRESS IS THE OPERATOR'S END, the same press as the card's End & Restore Now", "THIS PRESS IS A NORMAL END, the same press as the card's End & Restore Now", "one", VERD),
    ("the time guard alone ignores the status", "time", V_ST, "{%- elif false -%}", "one", ("static",)),
    ("the import guard alone ignores the status", "import", V_ST, "{%- elif false -%}", "one", ("static",)),
    ("the time guard alone ignores a press of END in this lease", "time", V_PR, "{%- elif false -%}", "one", ("static",)),
    ("the import guard alone ignores a press of END in this lease", "import", V_PR, "{%- elif false -%}", "one", ("static",)),
]
# ---- the headers (the stated rules) ----
HEADER_MUTANTS = [
    ("the gate header no longer says the gate is soft", "THE GATE IS SOFT.", "THE GATE IS FIRM.", "gate", "one"),
    ("the gate header no longer says the card is unchanged", "THE CARD IS NOT CHANGED IN", "THE CARD IS CHANGED IN", "gate", "one"),
    ("the gate header no longer says no margin is applied", "NO charger-loss factor and NO margin is applied", "A charger-loss factor and a margin are applied", "gate", "one"),
    ("the gate header no longer says why the schedule's result text is not reused", "does NOT reuse the Free Power schedule's result text", "reuses the Free Power schedule's result text", "gate", "one"),
    ("the gate header no longer says that only a readable 0 is no ceiling", "ONLY a readable 0 means NO CEILING CONFIGURED", "0, unknown or unavailable means NO CEILING CONFIGURED", "gate", "one"),
    ("the gate header no longer says the write enable is turned off only if this run turned it on", "ONLY IF THIS RUN TURNED IT ON", "ON EVERY PATH", "gate", "one"),
    ("the gate header no longer says a refused request is put back", "puts the values this run replaced back", "leaves the values this run replaced", "gate", "one"),
    ("the gate header no longer says the detector records a bypass", "a BYPASS", "a start", "gate", "one"),
    ("the Dump header no longer asks for a separate authorisation", "THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "THIS GUARD IS INSTALLED WITH THE GATE", "dump", "one"),
    ("the time header no longer asks for a separate authorisation", "THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "THIS GUARD IS INSTALLED WITH THE GATE", "time", "one"),
    ("the import header no longer asks for a separate authorisation", "THIS GUARD NEEDS THE OWNER'S SEPARATE INSTALL AUTHORISATION", "THIS GUARD IS INSTALLED WITH THE GATE", "import", "one"),
    ("the Dump header no longer says a restart never ends a lease", "never end a lease by themselves", "may end a lease", "dump", "one"),
    ("the time header no longer says a restart never ends a lease", "never end a lease by themselves", "may end a lease", "time", "one"),
    ("the import header no longer says a restart never ends a lease", "never end a lease by themselves", "may end a lease", "import", "one"),
    ("the Dump header no longer says END is always allowed", "END is always allowed", "END is sometimes refused", "dump", "one"),
    ("the Dump header no longer says the Dump End is not an operator retry", "THE DUMP END IS NOT AN OPERATOR RETRY", "THE DUMP END IS AN OPERATOR RETRY", "dump", "one"),
    ("the Free Power headers no longer say the press is the operator's End", "THIS PRESS IS THE OPERATOR'S END.", "THIS PRESS IS AN ORDINARY END.", "fp", "one"),
    ("the Free Power headers no longer say at most one press per lease", "AT MOST ONE PRESS PER LEASE", "ONE PRESS PER VIOLATION", "fp", "one"),
    ("the Free Power headers no longer say the press needs a verified running lease", "ONLY for a VERIFIED RUNNING lease", "for any lease", "fp", "one"),
    ("the Free Power headers no longer say END is never gated for a human", "END is never gated for a human", "END is gated for a human", "fp", "one"),
    ("the import header no longer says that an unreadable ceiling is reported", "A ceiling that CANNOT BE READ", "A ceiling that is missing", "import", "one"),
    ("the time header no longer says it is on the READERS allow-list of the time trust package", "READERS allow-list", "readers list", "time", "one"),
]


def apply_mutant(which: str, old: str, new: str, mode):
    """(gate text, guard texts) with the mutation applied to the file(s) `which` names ('fp' is both Free Power guard files), or None when its anchor is not found there."""
    if which == "gate":
        m = mutate(GATE_TEXT, old, new, mode)
        return None if m is None or m == GATE_TEXT else (m, GUARDS_TEXT)
    guards = list(GUARDS_TEXT)
    for i in {"dump": [0], "time": [1], "import": [2], "fp": [1, 2]}[which]:
        m = mutate(guards[i], old, new, mode)
        if m is None or m == guards[i]:
            return None
        guards[i] = m
    return GATE_TEXT, tuple(guards)


ALL = [(lbl, "gate", old, new, mode, ("static", "gate", "plan", "script")) for lbl, old, new, mode in GATE_MUTANTS + SCRIPT_MUTANTS] \
    + [(m[0], m[1], m[2], m[3], m[4], m[5] if len(m) > 5 else ("guards", "restart")) for m in GUARD_MUTANTS] \
    + [(lbl, wh, old, new, mode, ("static",)) for lbl, old, new, wh, mode in HEADER_MUTANTS]
labels = [m[0] for m in ALL]
check("every mutant has a unique label", len(labels) == len(set(labels)), str([lb for lb in labels if labels.count(lb) > 1][:3]))
killed = 0
for label, which, old, new, mode, parts in ALL:
    built = apply_mutant(which, old, new, mode)
    if built is None:
        check(f"mutant anchor: {label}", False, f"anchor not found (or no change) in {which} (mode {mode})")
        continue
    found = battery(built[0], built[1], parts)
    if found:
        killed += 1
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(ALL)} mutants of the gate, the guarded start, the three guards (the Free Power verdict in both files) and the stated rules, all caught", killed == len(ALL) and len(ALL) >= 200, f"{killed}/{len(ALL)}")
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
