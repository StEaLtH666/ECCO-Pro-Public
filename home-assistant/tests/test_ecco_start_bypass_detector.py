"""Offline suite for the start bypass detector (home-assistant/packages/ecco_start_bypass_detector.yaml): DETECT AND ALERT ONLY.

The dongle's own Start buttons (Dump to Grid, Free Power) can be pressed by anything that can call a Home Assistant service, and the firmware has no
notion of ECCO's plan, so such a start is not bound by an override or by the effective reserve (release gate RG-ST3). The package notices a session
that turns active without ECCO's own record of the start and says so. It prevents nothing. This suite proves the package against a model of Home
Assistant and the dongle; nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.

The REAL package YAML runs under the FPS1 interpreter (_ha_script_sim.py, through _plan_sim.py's helper layer). The dongle models are the repository's
(_ha_dump_sim.DumpDongle and _ha_script_sim.Dongle); the schedule, guarded start and plan packages run for real in the end-to-end cases.

  [0] static      only helpers, two automations; the only services are persistent_notification.create, input_text.set_value, input_number.set_value and
                  input_datetime.set_datetime, aimed only at this package's own helpers; the entities it reads are exactly the eight it names and each
                  exists in the repository; its own ids are defined nowhere else; no duplicate key, helper, automation, script or unique id across the
                  packages; texts fit the 255-character helper; the stated limits are in the header and in the notice; ASCII, LF, no site value
  [1] ECCO's own  an ECCO scheduled start (Dump to Grid and Charge Battery) and the guarded start, through the real scripts: nothing to report, the
                  dongle sees exactly the calls it sees without the package
  [2] bypass      a raw press (stage, arm, press) of each kind: one notification, the incident record (time, kind, text, counter), the wording;
                  the three facts, for a table of hold / reserve / staged Stop SOC values against an independent model
  [3] markers     the verdict over a grid of schedule texts (own form, stale, recovery, failed, blocked, unreadable) x guarded start (age, state)
                  x facts, against an independent model; the 45 s wait, the 10 s freshness window and the 180 s guard window at their edges
  [4] unreadable  a marker that cannot be read is CANNOT CLASSIFY (a notification, no counter, never an all clear, no log noise)
  [5] restart     a restart or reconnect with a session running raises nothing; a restart or an automation reload during a check becomes one
                  CANNOT CLASSIFY, and a storm of restarts adds none; an ordinary start or reload is silent
  [6] repeats     a flap during a check is dropped silently; a new start after a check is a new check; the documented flap limit is pinned
  [7] mute        the mute switch hides the popups and never the record
  [8] mutation    in-memory mutants of the package, each caught

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import copy
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _plan_sim as P  # noqa: E402

PKGS = ROOT / "home-assistant" / "packages"
DET_REL = "home-assistant/packages/ecco_start_bypass_detector.yaml"
DET_TEXT = (ROOT / DET_REL).read_text(encoding="utf-8")
DUMP_TEXT = (PKGS / "ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
FREE_TEXT = (PKGS / "ecco_free_power_schedule.yaml").read_text(encoding="utf-8")
PLAN_TEXT = (PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8")
GUARD_TEXT = (PKGS / "ecco_dump_to_grid_guarded_start.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
DET_RAW = (ROOT / DET_REL).read_bytes()

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


DUMP, FREE = "dump_to_grid", "free_power"
ACTIVE = {DUMP: D.D_ACTIVE, FREE: S.E_ACTIVE}
LAST = {DUMP: "input_text.ecco_dump_to_grid_schedule_last_result", FREE: "input_text.ecco_free_power_schedule_last_result"}
GUARD = "script.ecco_dump_to_grid_start_guarded"
STOP = D.D_SOC
HOLD, EFF = "sensor.ecco_plan_export_hold", "sensor.ecco_plan_effective_reserve"
OWNER = "input_number.ecco_minimum_reserve_soc"
CHECK, KIND, TEXT = ("input_text.ecco_start_bypass_last_check", "input_text.ecco_start_bypass_last_kind", "input_text.ecco_start_bypass_last_text")
COUNT, TIME, MUTED = "input_number.ecco_start_bypass_count", "input_datetime.ecco_start_bypass_last_time", "input_boolean.ecco_start_bypass_notice_muted"
NOTE = {DUMP: "ecco_start_bypass_dump_to_grid", FREE: "ecco_start_bypass_free_power"}
UNCL = "ecco_start_bypass_unclassified"
OWN_HELPERS = {MUTED, TIME, COUNT, KIND, TEXT, CHECK}
T0 = "2026-11-23 21:00:00"
ZONE = "Etc/GMT-1"
OWN_TEXT = {DUMP: "STARTED OK - 2000W for 30 min, Stop SOC 25% (attempt 1; ends by 21:30)",
            FREE: "STARTED OK - 2000W for 30 min (attempt 1; ends by 21:30)"}
KIND_NAME = {DUMP: "Dump to Grid (Export to Grid)", FREE: "Free Power (Charge Battery)"}
WAIT = 45.0                 # the wait for ECCO's own record
FRESH = 10.0                # a record written up to 10 s before the session turned active still counts
GUARD_WINDOW = 180.0

DET_PKG = yaml.safe_load(DET_TEXT)
PARSED = {n: yaml.safe_load(t) for n, t in (("dump", DUMP_TEXT), ("free", FREE_TEXT), ("plan", PLAN_TEXT), ("guard", GUARD_TEXT))}
MSG_PINS = ("deliberate start from the dongle's own screen or button", "PREVENTS NOTHING", "looks like a person", "while Home Assistant is down",
            "OUTSIDE ECCO's own paths", "End and restore")


# ================================================================================================================================
# [0] static
# ================================================================================================================================
class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)
UniqueKeyLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)   # !secret and the like


class FwLoader(yaml.SafeLoader):
    pass


FwLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def firmware_ids() -> set:
    d = yaml.load(FW_TEXT, Loader=FwLoader)
    out = set()
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor"), ("switch", "switch"),
                         ("number", "number"), ("button", "button"), ("select", "select")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                out.add(f"{domain}.ecco_clock_dongle_{slug(e['name'])}")
    return out


def package_ids(path: Path) -> set:
    """The entity ids a package file defines: helper keys, script keys and template sensors (by name)."""
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


def walk_actions(node, found):
    """Every dict with an `action` key, anywhere in the automations."""
    if isinstance(node, dict):
        if isinstance(node.get("action"), str):
            found.append(node)
        for v in node.values():
            walk_actions(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_actions(v, found)


ALLOWED_ACTIONS = {"persistent_notification.create", "input_text.set_value", "input_number.set_value", "input_datetime.set_datetime"}
EXPECT_READS = {
    "binary_sensor.ecco_clock_dongle_dump_to_grid_active", "binary_sensor.ecco_clock_dongle_free_power_active",
    "sensor.ecco_plan_export_hold", "sensor.ecco_plan_effective_reserve", "number.ecco_clock_dongle_dump_to_grid_stop_soc",
    "script.ecco_dump_to_grid_start_guarded", "input_text.ecco_dump_to_grid_schedule_last_result", "input_text.ecco_free_power_schedule_last_result",
}
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_text|input_number|input_boolean|input_datetime|number|script|button|switch|select|climate|light|automation|notify)\.[a-z0-9_]+")
OTHER_PKGS = {p.name: p for p in sorted(PKGS.glob("*.yaml")) if p.name != "ecco_start_bypass_detector.yaml"}
FW_IDS = firmware_ids()
REPO_IDS = set(FW_IDS)
for _p in OTHER_PKGS.values():
    REPO_IDS |= package_ids(_p)


def static_problems(text: str) -> list[str]:
    bad: list[str] = []
    try:
        d = yaml.load(text, Loader=UniqueKeyLoader)
    except Exception as exc:  # noqa: BLE001 - a package that does not load (or repeats a key) is a failed proof
        return [f"does not load: {str(exc)[:100]}"]
    if set(d) != {"input_boolean", "input_datetime", "input_number", "input_text", "automation"}:
        bad.append(f"top-level keys {sorted(d)}")
    nc = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    acts: list = []
    walk_actions(d.get("automation"), acts)
    services = {a["action"] for a in acts}
    if not services or not services <= ALLOWED_ACTIONS:
        bad.append(f"services {sorted(services - ALLOWED_ACTIONS)}")
    own = {f"{dom}.{k}" for dom in ("input_boolean", "input_datetime", "input_number", "input_text") for k in (d.get(dom) or {})}
    for a in acts:
        tgt = (a.get("target") or {}).get("entity_id")
        tgt = [tgt] if isinstance(tgt, str) else (tgt or [])
        if a["action"] != "persistent_notification.create" and (not tgt or not set(tgt) <= own):
            bad.append(f"an action targets {tgt}")
        if a["action"] == "persistent_notification.create" and tgt:
            bad.append("a notification with a target")
        if "entity_id" in (a.get("data") or {}):
            bad.append("an action carries entity_id in its data")
    if own != {f"{dom}.{k}" for dom, ks in (("input_boolean", ["ecco_start_bypass_notice_muted"]), ("input_datetime", ["ecco_start_bypass_last_time"]),
                                            ("input_number", ["ecco_start_bypass_count"]),
                                            ("input_text", ["ecco_start_bypass_last_kind", "ecco_start_bypass_last_text", "ecco_start_bypass_last_check"])) for k in ks}:
        bad.append(f"own helpers {sorted(own)}")
    mentioned = set(ENTITY_RE.findall(re.sub(r"(?m)^\s*-?\s*action:.*$", "", nc)))
    external = mentioned - own
    if external != EXPECT_READS:
        bad.append(f"entities read {sorted(external ^ EXPECT_READS)}")
    if not EXPECT_READS <= REPO_IDS:
        bad.append(f"not in the repository: {sorted(EXPECT_READS - REPO_IDS)}")
    for tok in ("esphome", "modbus"):
        if tok in nc:
            bad.append(f"token {tok}")
    for m in re.finditer(r"(?<![A-Za-z_])(?:button|switch|select|climate|light|notify|homeassistant|automation|script\.turn)\.", nc):
        bad.append(f"token {m.group(0)}")
    for dom, keys in (("input_text", d.get("input_text") or {}),):
        for k, v in keys.items():
            if int(v.get("max", 100)) > 255:
                bad.append(f"{k} max")
    if d.get("input_number", {}).get("ecco_start_bypass_count", {}).get("max") != 1000000:
        bad.append("counter max")
    autos = {a["id"]: a for a in d.get("automation") or []}
    if set(autos) != {"ecco_start_bypass_detect", "ecco_start_bypass_interrupted"}:
        bad.append(f"automation ids {sorted(autos)}")
    else:
        det, itr = autos["ecco_start_bypass_detect"], autos["ecco_start_bypass_interrupted"]
        trg = [(t.get("trigger"), t.get("entity_id"), t.get("to"), t.get("id")) for t in det["triggers"]]
        if trg != [("state", "binary_sensor.ecco_clock_dongle_dump_to_grid_active", "on", DUMP),
                   ("state", "binary_sensor.ecco_clock_dongle_free_power_active", "on", FREE)]:
            bad.append(f"detect triggers {trg}")
        if det.get("mode") != "single" or itr.get("mode") != "single":
            bad.append("mode")
        if [(t.get("trigger"), t.get("event") or t.get("event_type")) for t in itr["triggers"]] != [("homeassistant", "start"), ("event", "automation_reloaded")]:
            bad.append("interrupted triggers")
    if "'off'" not in nc.split("conditions:")[1].split("actions:")[0]:
        bad.append("the detect automation does not require a change from off")
    # every free text a run writes into the incident record or the last-check helper is cut to 250 characters
    for a in acts:
        tgt = (a.get("target") or {}).get("entity_id")
        if a["action"] == "input_text.set_value" and tgt in ("input_text.ecco_start_bypass_last_text", "input_text.ecco_start_bypass_last_check"):
            if "[:250]" not in str((a.get("data") or {}).get("value", "")):
                bad.append(f"{tgt} written without [:250]")
    return bad


print("[0] static")
sp = static_problems(DET_TEXT)
check("the package loads with no repeated key; only helpers and two automations; the only services are the four allowed ones, aimed only at its own helpers; "
      "it reads exactly the eight entities it names, each of which exists in the repository", sp == [], str(sp))
own_ids = {f"{dom}.{k}" for dom in ("input_boolean", "input_datetime", "input_number", "input_text") for k in DET_PKG[dom]}
check("its six helpers and two automation ids are defined nowhere else in the repository's packages, and the notification ids appear nowhere else",
      not (own_ids & REPO_IDS) and not [n for n, p in OTHER_PKGS.items() if "ecco_start_bypass" in p.read_text(encoding="utf-8")])
dup: list = []
seen_h: dict = {}
seen_a: dict = {}
seen_u: dict = {}
for _n, _p in sorted({**OTHER_PKGS, "ecco_start_bypass_detector.yaml": PKGS / "ecco_start_bypass_detector.yaml"}.items()):
    try:
        _d = yaml.load(_p.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}
    except Exception as exc:  # noqa: BLE001
        dup.append(f"{_n}: {exc}")
        continue
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in _d.get(dom) or {}:
            if (dom, k) in seen_h:
                dup.append(f"{dom}.{k}: {seen_h[(dom, k)]} and {_n}")
            seen_h[(dom, k)] = _n
    for a in _d.get("automation") or []:
        if isinstance(a, dict) and "id" in a:
            if a["id"] in seen_a:
                dup.append(f"automation {a['id']}: {seen_a[a['id']]} and {_n}")
            seen_a[a["id"]] = _n
    for block in _d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                if isinstance(it, dict) and "unique_id" in it:
                    if it["unique_id"] in seen_u:
                        dup.append(f"unique_id {it['unique_id']}: {seen_u[it['unique_id']]} and {_n}")
                    seen_u[it["unique_id"]] = _n
check(f"no repeated key inside any package, and no helper, script, automation id or template unique_id defined twice across the {len(OTHER_PKGS) + 1} packages", dup == [], str(dup[:3]))
nc0 = "\n".join(line for line in DET_TEXT.split("\n") if not line.lstrip().startswith("#"))
head = DET_TEXT.split("\ninput_boolean:")[0]
check("the header states, in plain words: not installed, detect and alert only, never actuates, prevents nothing, visible within about a minute, blind while Home Assistant is down, "
      "a script using the API key looks like a person, a deliberate owner start from the dongle's own UI is also outside the guarded path",
      all(s in head for s in ("NOT INSTALLED, NOT LIVE-PROVEN", "DETECT AND ALERT ONLY", "NEVER actuates", "PREVENTS NOTHING", "VISIBLE within about a minute",
                              "BLIND while Home Assistant is down", "LOOKS LIKE A PERSON", "deliberate start from the dongle's own", "Recalled, NOT verified")))
check("the notice says the same in the text the owner sees (deliberate start, prevents nothing, looks like a person, down, outside ECCO's own paths, End and restore)",
      all(s in DET_TEXT for s in MSG_PINS))
check("ASCII only, LF line ends, no tab, no site value (no address, e-mail, link, key or secret)",
      DET_TEXT.isascii() and b"\r" not in DET_RAW and "\t" not in DET_TEXT
      and not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|@|https?://|secret|token|password|api_key", nc0, re.I))
manifest = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
stanza = re.findall(r"- source: home-assistant/packages/ecco_start_bypass_detector\.yaml\n\s+destination: (\S+)\n\s+method: (\S+)\n\s+restart_required: (\S+)", manifest)
check("when the deployment manifest lists the package it lists it once, to /config/packages, by ssh_file_copy, with restart_required true (it may not list it yet)",
      stanza in ([], [("/config/packages/ecco_start_bypass_detector.yaml", "ssh_file_copy", "true")]), str(stanza))


# ================================================================================================================================
# the worlds
# ================================================================================================================================
class Light:
    """The detector package alone. The plan sensors, the schedule texts, the guarded script and the dongle's sensors are plain states that the case sets;
    the case schedules every event at an explicit offset from the instant the session turns active (`start`)."""

    def __init__(self, pkg=None, hold="clear", reserve="20.0", stop="30.0", muted=False, guard="off", texts=None):
        self.pw = P.PlanWorld(T0, [copy.deepcopy(DET_PKG if pkg is None else pkg)], ZONE)
        self.w = self.pw.w
        w = self.w
        D.add_ha_filters(w)
        for e, s in ((ACTIVE[DUMP], "off"), (ACTIVE[FREE], "off"), (LAST[DUMP], (texts or {}).get(DUMP, "")), (LAST[FREE], (texts or {}).get(FREE, "")),
                     (STOP, stop), (HOLD, hold), (EFF, reserve)):
            w.set(e, s)
        if guard is not None:
            w.set(GUARD, guard)
        if muted:
            w.set(MUTED, "on")
        self.pw.ha.start()
        w.run_until(w.t + 20)
        self.t_start = w.t + 20          # the instant every case turns a session on
        self.pkg = pkg

    def at(self, offset, fn):
        self.w.at(self.t_start + offset, fn)

    def set_at(self, offset, entity, state, attrs=None):
        self.w.at(self.t_start + offset, lambda: self.w.set(entity, state, attrs))

    def guard_ran(self, age, state="off"):
        """The guarded start was triggered `age` seconds before the session turns active (negative: after)."""
        ts = self.t_start - age
        when = min(ts, self.t_start - 1)         # a negative age is a last_triggered dated AFTER the start (clock skew, garbage): already set when the session turns active
        self.w.at(when, lambda: self.w.set(GUARD, state, {"last_triggered": datetime.fromtimestamp(ts, self.pw.zone)}))

    def go(self, kind=DUMP, secs=70.0):
        self.set_at(0, ACTIVE[kind], "on")
        self.w.run_until(self.t_start + secs)
        return self

    def creates(self):
        return [(round(t - self.t_start, 1), nid) for t, op, nid, _ in self.w.notification_log if op == "create"]

    def s(self, entity):
        return self.w.state(entity)

    def count(self):
        return float(self.s(COUNT))

    def title(self, nid):
        return (self.w.notifications.get(nid) or {}).get("title", "")

    def message(self, nid):
        return (self.w.notifications.get(nid) or {}).get("message", "")


def quiet(L: Light, allow_drops: bool = False) -> list[str]:
    """The log-quiet rule: no warning of the interpreter (an aborted run, a refused text) and no helper refusing a write."""
    ws = [x for x in L.w.warnings if not (allow_drops and "already running" in x and "ecco_start_bypass_detect" in x)]
    return [f"warnings {ws[:2]}"] if ws else []


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def model_facts(kind, hold, reserve, stop):
    """The independent reference for the three facts."""
    r, s = num(reserve), num(stop)
    r_ok = r is not None and 0 <= r <= 100
    s_ok = s is not None and 0 <= s <= 100
    f_over = hold == "held"
    f_below = kind == DUMP and r_ok and s_ok and s < r
    f_unr = hold not in ("held", "clear") or not r_ok or (kind == DUMP and not s_ok)
    return f_over, f_below, f_unr, (r_ok and s_ok)


def expected_record(kind, hold, reserve, stop):
    f_over, f_below, f_unr, comparable = model_facts(kind, hold, reserve, stop)
    ov = "ACTIVE" if f_over else ("none" if hold == "clear" else "UNREADABLE")
    bl = "n/a" if kind != DUMP else ("YES" if f_below else ("cannot compare" if not comparable else "no"))
    if kind == DUMP and any((f_over, f_below, f_unr)):
        tail = "- WHILE A PLAN CHECK WOULD HAVE REFUSED IT"
    elif kind != DUMP and (f_over or f_unr):
        tail = "- with an override active or unreadable"
    else:
        tail = "(informational)"
    return ov, bl, ("YES" if f_unr else "no"), tail


# ---- the cases ------------------------------------------------------------------------------------------------------------------
def case_raw(pkg, kind, hold="clear", reserve="20.0", stop="30.0") -> list[str]:
    """A raw press: one notification at the end of the wait, the record, the wording, the facts against the model."""
    L = Light(pkg, hold=hold, reserve=reserve, stop=stop).go(kind)
    bad = quiet(L)
    cr = L.creates()
    if [n for _t, n in cr] != [NOTE[kind]] or not (WAIT - 1 <= cr[0][0] <= 60):
        bad.append(f"notifications {cr}")
        return bad
    ov, bl, rd, tail = expected_record(kind, hold, reserve, stop)
    want = f"{KIND_NAME[kind]} started at 21:00 outside ECCO scheduled or guarded start. Override: {ov}. Stop SOC below reserve: {bl}. Plan reading unreadable: {rd}. Detected only; not stopped."
    if L.s(TEXT) != want:
        bad.append(f"text {L.s(TEXT)!r} != {want!r}")
    if L.s(KIND) != kind or L.count() != 1.0:
        bad.append(f"kind {L.s(KIND)} count {L.s(COUNT)}")
    if L.w.states[TIME][1].get("timestamp") != int(L.t_start):
        bad.append(f"time {L.w.states[TIME]}")
    if not L.s(CHECK).startswith(f"BYPASS NOTICE - {KIND_NAME[kind]} started at 21:00 "):
        bad.append(f"check {L.s(CHECK)!r}")
    if not L.title(NOTE[kind]).endswith(tail) or "started OUTSIDE ECCO scheduled or guarded start" not in L.title(NOTE[kind]):
        bad.append(f"title {L.title(NOTE[kind])!r} tail {tail!r}")
    msg = L.message(NOTE[kind])
    for pin in MSG_PINS:
        if pin not in msg:
            bad.append(f"message lacks {pin!r}")
    if (kind == FREE) != ("ECCO does not gate a Charge Battery start" in msg):
        bad.append("the Charge Battery sentence")
    return bad


def case_marker(pkg, kind, sched=None, guard=None, hold="clear", reserve="20.0", stop="30.0", muted=False):
    """One session against a schedule text written at an offset (None: never) and a guarded start of an age (None: never). Returns (verdict, problems)."""
    texts = {}
    L = Light(pkg, hold=hold, reserve=reserve, stop=stop, muted=muted, guard=None if guard == "missing" else "off", texts=texts)
    if sched is not None:
        text, off = sched
        if text in ("unavailable", "unknown"):
            L.w.set(LAST[kind], text)
        elif off is None:
            L.w.set(LAST[kind], text)
        else:
            L.set_at(off, LAST[kind], text)
    if guard not in (None, "missing"):
        gstate, age = guard
        if gstate in ("unavailable", "unknown"):
            L.w.set(GUARD, gstate, None if age is None else {"last_triggered": datetime.fromtimestamp(L.t_start - age, L.pw.zone)})
        else:
            L.guard_ran(age, gstate)
    L.go(kind)
    return L


def verdict_of(L: Light) -> str:
    c = L.s(CHECK)
    return ("ECCO" if c.startswith("ECCO START - ") else "BYPASS" if c.startswith("BYPASS NOTICE - ") else "CANNOT" if c.startswith("CANNOT CLASSIFY - ")
            else "PENDING" if c.startswith("PENDING") else f"?{c[:20]}")


def model_verdict(kind, sched, guard, hold="clear", reserve="20.0", stop="30.0"):
    """The independent reference for the verdict. `guard`: None (the script exists and never ran), "missing", or (state, age in seconds before the start)."""
    f_over, f_below, f_unr, _ = model_facts(kind, hold, reserve, stop)
    any_fact = f_over or f_below or f_unr
    text, off = sched if sched else ("", None)
    own = bool(re.match(r"STARTED OK - [0-9]+W for [0-9]+ min", text)) and off is not None and -FRESH <= off <= WAIT
    guarded, guard_ok = False, True
    if kind == DUMP:
        gstate, age = ("unknown", None) if guard == "missing" else (("off", None) if guard is None else guard)
        guard_ok = gstate in ("on", "off")
        guarded = guard_ok and age is not None and 0 <= age <= GUARD_WINDOW and not any_fact
    sched_ok = text not in ("unavailable", "unknown")
    if guarded or own:
        return "ECCO"
    return "BYPASS" if (sched_ok and guard_ok) else "CANNOT"


def case_marker_model(pkg, kind, sched, guard, **facts) -> list[str]:
    L = case_marker(pkg, kind, sched, guard, **facts)
    want, got = model_verdict(kind, sched, guard, **facts), verdict_of(L)
    bad = quiet(L)
    if got != want:
        bad.append(f"{kind} sched={sched} guard={guard} {facts}: got {got} want {want} ({L.s(CHECK)[:60]!r})")
        return bad
    cr = [n for _t, n in L.creates()]
    exp = {"ECCO": [], "BYPASS": [NOTE[kind]], "CANNOT": [UNCL]}[want]
    if cr != exp:
        bad.append(f"{sched} {guard}: notifications {cr} want {exp}")
    if want == "CANNOT" and (L.count() != 0 or L.s(CHECK).startswith("ECCO START")):
        bad.append("a cannot-classify start counted or read as an all clear")
    if want == "ECCO" and (L.count() != 0 or L.s(KIND) != ""):
        bad.append("an ECCO start left an incident record")
    return bad


def case_ecco_fast(pkg) -> list[str]:
    """A recognised ECCO start is settled at once: no wait for the 45 s."""
    bad = []
    L = case_marker(pkg, DUMP, (OWN_TEXT[DUMP], 0.4), None)
    L2 = Light(pkg)
    L2.set_at(0, ACTIVE[DUMP], "on")
    L2.set_at(0.4, LAST[DUMP], OWN_TEXT[DUMP])
    L2.w.run_until(L2.t_start + 3)
    if L2.s(CHECK) != "ECCO START - Dump to Grid (Export to Grid) at 21:00: the scheduled run recorded its own verified start (STARTED OK). Nothing to report.":
        bad.append(f"scheduled not settled at once: {L2.s(CHECK)!r}")
    L3 = Light(pkg)
    L3.guard_ran(5)
    L3.set_at(0, ACTIVE[DUMP], "on")
    L3.w.run_until(L3.t_start + 3)
    if L3.s(CHECK) != "ECCO START - Dump to Grid (Export to Grid) at 21:00: the guarded start ran 5 s earlier and its checks were clear. Nothing to report.":
        bad.append(f"guarded not settled at once: {L3.s(CHECK)!r}")
    return bad + quiet(L) + quiet(L2) + quiet(L3)


FACT_DUMP = [(h, r, s) for h in ("clear", "held", "unavailable", "junk") for r in ("20.0", "unavailable", "nan", "inf", "120", "-5", "0") for s in ("30.0",)]
FACT_DUMP += [("clear", "20.0", s) for s in ("10.0", "20.0", "19.0", "unavailable", "150", "nan", "-1")] + [("held", "20.0", "10.0"), ("unavailable", "unavailable", "unavailable")]
FACT_FREE = [(h, r, "30.0") for h in ("clear", "held", "unavailable", "junk") for r in ("20.0", "unavailable")] + [("clear", "50.0", "30.0"), ("clear", "20.0", "unavailable"), ("clear", "20.0", "150")]
FACT_QUICK_DUMP = [("clear", "20.0", "30.0"), ("held", "20.0", "30.0"), ("unavailable", "20.0", "30.0"), ("clear", "unavailable", "30.0"), ("clear", "nan", "30.0"),
                   ("clear", "20.0", "10.0"), ("clear", "20.0", "20.0"), ("clear", "20.0", "unavailable"), ("clear", "120", "30.0"), ("junk", "20.0", "30.0")]
FACT_QUICK_FREE = [("clear", "20.0", "30.0"), ("held", "20.0", "30.0"), ("junk", "unavailable", "30.0"), ("clear", "50.0", "30.0"), ("clear", "20.0", "unavailable")]

RECOVERY = "STARTED OK - running (Home Assistant restarted during the session)"
OTHER_TEXTS = ["STARTING - 2000W until 21:30", "FAILED TO START - retries ended at 21:00: IDLE; Dump to Grid is active now, but this run did not confirm that it started it",
               "BLOCKED - a Hold battery, Skip tonight or Prepare for power cut is active; nothing started (reason OVERRIDE_ACTIVE)",
               "UNCONFIRMED - Dump to Grid is active after a Home Assistant restart, but this schedule did not confirm that it started it", "CANCELLED - scheduled Dump to Grid cancelled before it started",
               "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own", "started ok - 2000W for 30 min", " STARTED OK - 2000W for 30 min"]


def case_markers_core(pkg) -> list[str]:
    """The decisive marker cases, in the order that kills most mutants first."""
    bad: list[str] = []
    for kind in (DUMP, FREE):
        own = OWN_TEXT[kind]
        for sched, guard, label in (
                ((own, 0.4), None, "scheduled, fresh"), ((own, -FRESH), None, "scheduled, written 10 s before"), ((own, -FRESH - 1), None, "stale by 1 s"),
                ((own, -3600), None, "an hour old"), ((own, WAIT - 1), None, "written at 44 s (inside the wait)"), ((own, WAIT + 2), None, "written at 47 s (too late)"),
                ((RECOVERY, 0.4), None, "the recovery text"), (("STARTED OK - 2000W for 30 min", None), None, "own form, written long before")):
            bad += [f"{label}: {p}" for p in case_marker_model(pkg, kind, sched, guard)]
        if kind == DUMP:
            for guard in (("off", 5), ("off", GUARD_WINDOW), ("off", GUARD_WINDOW + 1), ("off", -3), ("off", -3600), ("on", 5), ("off", 0), ("unavailable", 5), ("unknown", 5)):
                bad += [f"guard {guard}: {p}" for p in case_marker_model(pkg, DUMP, None, guard)]
    return bad


def case_guard_facts(pkg) -> list[str]:
    """The refused-then-raw case: the guarded script ran, but a fact is true, so it cannot have passed: a bypass (the guard's own checks decide)."""
    bad = []
    for hold, reserve, stop in (("held", "20.0", "30.0"), ("clear", "50.0", "30.0"), ("unavailable", "20.0", "30.0"), ("clear", "unavailable", "30.0"), ("clear", "20.0", "unavailable")):
        bad += [f"{hold}/{reserve}/{stop}: {p}" for p in case_marker_model(pkg, DUMP, None, ("off", 5), hold=hold, reserve=reserve, stop=stop)]
    bad += case_marker_model(pkg, DUMP, None, ("off", 5), hold="clear", reserve="30.0", stop="30.0")     # equal: the guard would pass
    return bad


def case_unreadable(pkg) -> list[str]:
    bad = []
    for kind in (DUMP, FREE):
        for text in ("unavailable", "unknown"):
            bad += [f"{kind} {text}: {p}" for p in case_marker_model(pkg, kind, (text, None), None)]
    for guard in (("unavailable", None), ("unknown", None), "missing"):
        bad += [f"guard {guard}: {p}" for p in case_marker_model(pkg, DUMP, None, guard)]
    # a positive record still counts while the other marker cannot be read
    bad += case_marker_model(pkg, DUMP, (OWN_TEXT[DUMP], 0.4), ("unavailable", None))
    bad += case_marker_model(pkg, DUMP, ("unavailable", None), ("off", 5))
    L = case_marker(pkg, DUMP, ("unavailable", None), None)
    if "the schedule result could not be read" not in L.message(UNCL) or "NOT an all clear" not in L.message(UNCL):
        bad.append("the unclassified notice does not say why or that it is not an all clear")
    if "not an all clear" not in L.s(CHECK) or not L.s(CHECK).startswith("CANNOT CLASSIFY - "):
        bad.append(f"check {L.s(CHECK)!r}")
    L = case_marker(pkg, DUMP, ("unavailable", None), ("unavailable", None))
    if "the schedule result and the guarded start script could not be read" not in L.message(UNCL):
        bad.append("both markers unreadable: reason")
    L = case_marker(pkg, DUMP, None, ("unavailable", None))
    if "the guarded start script could not be read" not in L.message(UNCL):
        bad.append("guard unreadable: reason")
    return bad


def reload_ha(L: Light, ha_start: bool = True, reload_event: bool = False):
    """Home Assistant restarts (or only its automations reload): the old instance dies with its runs, a new one loads the packages."""
    w = L.w
    L.pw.ha.stop()
    L.pw.ha = S.HA(w, [copy.deepcopy(L.pkg if L.pkg is not None else DET_PKG)])
    for a in L.pw.ha.automations:
        a.setup()
    if ha_start:
        for a in L.pw.ha.automations:
            a.ha_start()
    if reload_event:
        L.pw.ha.fire_event("automation_reloaded")


def case_restart(pkg) -> list[str]:
    bad: list[str] = []
    # (a) a restart with a session already running: unavailable / unknown / missing -> on is not a start
    for how in ("unavailable", "unknown", "missing"):
        for kind in (DUMP, FREE):
            L = Light(pkg)
            L.w.set(ACTIVE[kind], "on")                                          # the session was running before the restart (a check, if any, is over)
            L.w.run_until(L.w.t + 100)
            before = (L.s(CHECK), L.creates(), L.s(COUNT))
            L.pw.ha.stop()
            if how == "missing":
                L.w.states.pop(ACTIVE[kind])
            else:
                L.w.set(ACTIVE[kind], how)
            L.pw.ha = S.HA(L.w, [copy.deepcopy(DET_PKG if pkg is None else pkg)])
            for a in L.pw.ha.automations:
                a.setup()
            for a in L.pw.ha.automations:
                a.ha_start()
            L.w.run_until(L.w.t + 5)
            L.w.set(ACTIVE[kind], "on")
            L.w.run_until(L.w.t + 120)
            after = (L.s(CHECK), L.creates(), L.s(COUNT))
            if before != after or "PENDING" in L.s(CHECK):
                bad.append(f"restart with a {kind} session running ({how} -> on): {before} / {after}")
            bad += quiet(L, allow_drops=True)
    # (b) a restart during the wait of a check
    for kind in (DUMP, FREE):
        for mode in ("restart", "reload"):
            L = Light(pkg)
            L.set_at(0, ACTIVE[kind], "on")
            L.w.run_until(L.t_start + 10)
            if not L.s(CHECK).startswith("PENDING - "):
                bad.append(f"{kind}: the check is not marked PENDING during its wait: {L.s(CHECK)!r}")
            reload_ha(L, ha_start=(mode == "restart"), reload_event=(mode == "reload"))
            L.w.run_until(L.w.t + 120)
            cr = L.creates()
            if [n for _t, n in cr] != [UNCL] or not L.s(CHECK).startswith(
                    "CANNOT CLASSIFY - interrupted by a Home Assistant restart or an automation reload (not an all clear); it was: " + KIND_NAME[kind] + " became active at 21:00"):
                bad.append(f"{kind} {mode} during a check: {cr} {L.s(CHECK)!r}")
            if L.count() != 0 or L.s(KIND) != "":
                bad.append(f"{kind} {mode}: an interrupted check left a bypass record")
            if "NOT classified" not in L.message(UNCL) or "not an all clear" not in L.message(UNCL):
                bad.append("the interrupted notice does not say it is not an all clear")
            # a storm of restarts and reloads adds nothing
            for _ in range(3):
                reload_ha(L, ha_start=True, reload_event=True)
                L.w.run_until(L.w.t + 30)
            if len(L.creates()) != 1:
                bad.append(f"{kind} {mode}: a storm of restarts raised {L.creates()}")
            bad += quiet(L, allow_drops=True)
    # (c) ordinary starts and reloads are silent, whatever the last check said
    for last in ("", "ECCO START - Dump to Grid (Export to Grid) at 21:00: the scheduled run recorded its own verified start (STARTED OK). Nothing to report.",
                 "BYPASS NOTICE - x", "CANNOT CLASSIFY - x", "pending", "PEND"):
        L = Light(pkg)
        L.w.set(CHECK, last)
        reload_ha(L, ha_start=True, reload_event=True)
        L.w.run_until(L.w.t + 60)
        if L.creates() or L.s(CHECK) != last:
            bad.append(f"an ordinary start with last check {last[:20]!r} raised {L.creates()} / {L.s(CHECK)[:30]!r}")
    # (d) after an interrupted check a new raw start is an ordinary new check
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 10)
    reload_ha(L)
    L.w.run_until(L.w.t + 60)
    L.w.set(ACTIVE[DUMP], "off")
    L.w.run_until(L.w.t + 10)
    L.w.set(ACTIVE[DUMP], "on")
    L.w.run_until(L.w.t + 60)
    if [n for _t, n in L.creates()] != [UNCL, NOTE[DUMP]] or L.count() != 1.0:
        bad.append(f"a new start after an interrupted check: {L.creates()} count {L.s(COUNT)}")
    return bad


def case_repeats(pkg) -> list[str]:
    bad: list[str] = []
    # a flap during a check is dropped silently: one notice, one count
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.set_at(3, ACTIVE[DUMP], "off")
    L.set_at(6, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 80)
    if [n for _t, n in L.creates()] != [NOTE[DUMP]] or L.count() != 1.0:
        bad.append(f"a flap during a check: {L.creates()} count {L.s(COUNT)}")
    bad += quiet(L, allow_drops=True)
    # the other kind flapping on during the check (cannot happen on the dongle) is dropped silently too
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.set_at(8, ACTIVE[FREE], "on")
    L.w.run_until(L.t_start + 80)
    if [n for _t, n in L.creates()] != [NOTE[DUMP]] or L.count() != 1.0:
        bad.append(f"two kinds during a check: {L.creates()}")
    bad += quiet(L, allow_drops=True)
    # a new start after the check is a new check: a second notice replaces the first (same id), the counter moves, the record follows
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.set_at(100, ACTIVE[DUMP], "off")
    L.set_at(200, ACTIVE[FREE], "on")
    L.w.run_until(L.t_start + 300)
    if [n for _t, n in L.creates()] != [NOTE[DUMP], NOTE[FREE]] or L.count() != 2.0 or L.s(KIND) != FREE or set(L.w.notifications) != {NOTE[DUMP], NOTE[FREE]}:
        bad.append(f"two sessions: {L.creates()} count {L.s(COUNT)} kind {L.s(KIND)}")
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.set_at(100, ACTIVE[DUMP], "off")
    L.set_at(200, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 300)
    if [n for _t, n in L.creates()] != [NOTE[DUMP], NOTE[DUMP]] or L.count() != 2.0 or list(L.w.notifications) != [NOTE[DUMP]]:
        bad.append(f"two Dump sessions: {L.creates()} count {L.s(COUNT)}")
    # the counter saturates at its helper's maximum and never raises an error
    n_rej = len(P.PlanWorld.rejected_all)
    L = Light(pkg)
    L.w.set(COUNT, "1000000.0")
    L.go(DUMP)
    if L.count() != 1000000.0 or len(P.PlanWorld.rejected_all) != n_rej:
        bad.append(f"the counter at its maximum: {L.s(COUNT)} {P.PlanWorld.rejected_all[n_rej:][:1]}")
    return bad + quiet(L)


def case_flap_limit(pkg) -> list[str]:
    """PINNED LIMIT: a flap AFTER a recognised ECCO start is a new start: ECCO's record must be younger than 10 s, so it is reported when it is older."""
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.set_at(0.4, LAST[DUMP], OWN_TEXT[DUMP])
    L.set_at(20, ACTIVE[DUMP], "off")
    L.set_at(25, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 120)
    first = L.creates()
    L2 = Light(pkg)
    L2.set_at(0, ACTIVE[DUMP], "on")
    L2.set_at(0.4, LAST[DUMP], OWN_TEXT[DUMP])
    L2.set_at(4, ACTIVE[DUMP], "off")
    L2.set_at(7, ACTIVE[DUMP], "on")
    L2.w.run_until(L2.t_start + 120)
    return ([] if [n for _t, n in first] == [NOTE[DUMP]] and L2.creates() == [] else [f"flap limit: late {first}, early {L2.creates()}"])


def case_mute(pkg) -> list[str]:
    bad = []
    for kind in (DUMP, FREE):
        L = Light(pkg, muted=True).go(kind)
        if L.creates() or L.count() != 1.0 or L.s(KIND) != kind or not L.s(TEXT) or not L.s(CHECK).startswith("BYPASS NOTICE - "):
            bad.append(f"muted {kind} bypass: {L.creates()} count {L.s(COUNT)} check {L.s(CHECK)[:30]!r}")
    L = case_marker(pkg, DUMP, ("unavailable", None), None, muted=True)
    if L.creates() or not L.s(CHECK).startswith("CANNOT CLASSIFY - "):
        bad.append(f"muted cannot classify: {L.creates()} {L.s(CHECK)[:30]!r}")
    L = Light(pkg, muted=True)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 10)
    reload_ha(L)
    L.w.run_until(L.w.t + 60)
    if L.creates() or not L.s(CHECK).startswith("CANNOT CLASSIFY - interrupted"):
        bad.append(f"muted interrupted: {L.creates()} {L.s(CHECK)[:40]!r}")
    L = Light(pkg, muted=False)
    L.w.set(MUTED, "off")
    L.go(DUMP)
    if len(L.creates()) != 1:
        bad.append("an unmuted switch (off) did not notify")
    L = Light(pkg)
    L.w.set(MUTED, "unavailable")
    L.go(DUMP)
    if len(L.creates()) != 1:
        bad.append("an unavailable mute switch silenced the notice (it must notify)")
    return bad


def case_facts(pkg, quick: bool) -> list[str]:
    bad: list[str] = []
    for kind, rows in ((DUMP, FACT_QUICK_DUMP if quick else FACT_DUMP), (FREE, FACT_QUICK_FREE if quick else FACT_FREE)):
        for hold, reserve, stop in rows:
            bad += [f"{kind} {hold}/{reserve}/{stop}: {p}" for p in case_raw(pkg, kind, hold, reserve, stop)]
    return bad


def case_timing(pkg) -> list[str]:
    """The wait is 45 s: ECCO's record at 44 s is seen (no notice); a raw start is reported at 45 s and not after a minute."""
    bad = []
    L = Light(pkg)
    L.set_at(0, ACTIVE[DUMP], "on")
    L.w.run_until(L.t_start + 40)
    if L.creates():
        bad.append(f"a notice before the wait is over: {L.creates()}")
    L.w.run_until(L.t_start + 60)
    cr = L.creates()
    if len(cr) != 1 or not (WAIT - 0.5 <= cr[0][0] <= WAIT + 1):
        bad.append(f"the notice at {cr}")
    L = Light(pkg)
    L.set_at(0, ACTIVE[FREE], "on")
    L.w.run_until(L.t_start + 59)
    if len(L.creates()) != 1:
        bad.append("a Charge Battery raw start is not reported within a minute")
    return bad


BATTERY_QUICK = (
    ("raw Dump to Grid", lambda p: case_raw(p, DUMP)), ("raw Charge Battery", lambda p: case_raw(p, FREE)),
    ("markers", case_markers_core), ("ECCO starts settle at once", case_ecco_fast), ("facts", lambda p: case_facts(p, True)),
    ("guard with a fact true", case_guard_facts), ("unreadable markers", case_unreadable), ("restart", case_restart),
    ("repeats", case_repeats), ("flap limit", case_flap_limit), ("mute", case_mute), ("timing", case_timing),
)


def battery(text: str, first_only: bool = True) -> list[str]:
    """Every case against the package text; the problems found (empty = all hold)."""
    out = static_problems(text)
    if first_only and out:
        return out
    try:
        pkg = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"does not load: {str(exc)[:80]}"]
    for label, fn in BATTERY_QUICK:
        try:
            found = fn(pkg)
        except Exception as exc:  # noqa: BLE001 - a mutant the interpreter cannot run is caught too (it is fail-loud)
            found = [f"raised {type(exc).__name__}: {str(exc)[:70]}"]
        out += [f"{label}: {p}" for p in found]
        if first_only and out:
            return out
    return out


# ================================================================================================================================
# [1] the real scripts, end to end
# ================================================================================================================================
def arm_detector(pw):
    """Only the detector's two automations run (the schedule packages' own automations are not part of these cases)."""
    for a in pw.ha.automations:
        if a.id.startswith("ecco_start_bypass"):
            a.setup()


def heavy_dump(owner=40, stop=None, detector=True):
    pkgs = [copy.deepcopy(PARSED[k]) for k in ("dump", "plan", "guard")] + ([copy.deepcopy(DET_PKG)] if detector else [])
    pw = P.PlanWorld(T0, pkgs, ZONE)
    w = pw.w
    D.add_ha_filters(w)
    d = D.DumpDongle(w, phase=0.0, handle_delays=(0.117,))
    w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "on")
    w.set("input_boolean.ecco_free_power_schedule_armed", "off")
    w.set(LAST[DUMP], "")
    w.set("input_text.ecco_plan_last_result", "")
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set(OWNER, f"{float(owner)}")
    if stop is not None:
        d.stop_soc = stop
        w.set(D.D_SOC, f"{float(stop)}")
    if detector:
        arm_detector(pw)
    return pw, d


def heavy_free(detector=True):
    pkgs = [copy.deepcopy(PARSED[k]) for k in ("free", "plan")] + ([copy.deepcopy(DET_PKG)] if detector else [])
    pw = P.PlanWorld(T0, pkgs, ZONE)
    w = pw.w
    D.add_ha_filters(w)
    d = S.Dongle(w, phase=0.0, handle_delays=(0.6, 0.1))
    w.set("sensor.ecco_config_maximum_grid_charge_power", "8000")
    w.set("input_boolean.ecco_free_power_schedule_armed", "on")
    w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "off")
    w.set(LAST[FREE], "")
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set(OWNER, "40.0")
    if detector:
        arm_detector(pw)
    return pw, d


def scheduled(pw, kind, seconds=150, minutes=30, stop_soc=25, power=2000):
    end = pw.w.t + minutes * 60 + 60
    if kind == DUMP:
        pw.ha.start_script("ecco_dump_to_grid_start_scheduled", {"duration_minutes": minutes, "power_w": power, "stop_soc": stop_soc, "window_end_ts": end})
    else:
        pw.ha.start_script("ecco_free_power_start_scheduled", {"duration_minutes": minutes, "power_w": power, "window_end_ts": end})
    pw.w.run_until(pw.w.t + seconds)


def guarded(pw, seconds=120):
    """The card's guarded start (the owner staged and armed first). Home Assistant stamps last_triggered when a script starts: the interpreter does not model it."""
    pw.ha.start_script("ecco_dump_to_grid_start_guarded", {})
    w = pw.w
    w.set("script.ecco_dump_to_grid_start_guarded", w.states["script.ecco_dump_to_grid_start_guarded"][0], {"last_triggered": datetime.fromtimestamp(w.t, pw.zone)})
    w.run_until(w.t + seconds)


def owner_arm(d):
    d.arm = True
    d.w.set(D.D_ARM, "on")


def raw_dump(pw, d, stop=25, seconds=120):
    """Anything that can call a service: stage the Stop SOC, arm, press. No ECCO script is involved."""
    d.stop_soc = stop
    pw.w.set(D.D_SOC, f"{float(stop)}")
    d.manual_start(pw.w.t + 1, duration=30, power=2000, stop_soc=stop)
    pw.w.run_until(pw.w.t + seconds)


def raw_free(pw, d, seconds=120):
    d.manual_start(pw.w.t + 1, duration=30)
    pw.w.run_until(pw.w.t + seconds)


def detector_creates(pw):
    return [nid for _t, op, nid, _ in pw.w.notification_log if op == "create" and nid.startswith("ecco_start_bypass")]


def dongle_trace(pw, d):
    """What the dongle and the rest of the world saw, with every call of the detector (its helpers, its notifications) taken out."""
    calls = [(s, e, tuple(sorted((k, str(v)) for k, v in data.items())))
             for _t, s, e, data in pw.w.service_log
             if not (e in OWN_HELPERS or (s == "persistent_notification.create" and str(data.get("notification_id", "")).startswith("ecco_start_bypass")))]
    return (tuple(d.press_log), tuple(d.number_log), tuple(d.presses), d.successes, tuple(calls))


print("[1] ECCO's own starts through the real scripts: nothing to report, and the package changes nothing the dongle sees")
for kind in (DUMP, FREE):
    pws = []
    for detector in (True, False):
        pw, d = (heavy_dump(owner=40, detector=detector) if kind == DUMP else heavy_free(detector=detector))
        scheduled(pw, kind)
        pws.append((pw, d))
    (pw, d), (pw0, d0) = pws
    name = "Dump to Grid" if kind == DUMP else "Charge Battery"
    check(f"[1] a scheduled {name} start through the real script: the dongle started once, the schedule wrote its own STARTED OK",
          d.successes == 1 and pw.w.state(LAST[kind]).startswith("STARTED OK - "), pw.w.state(LAST[kind])[:60])
    check(f"[1] {name}: nothing to report: no notification, no incident, the count stays 0, the last check says ECCO's scheduled run, settled at once",
          detector_creates(pw) == [] and pw.w.state(COUNT) == "0.0" and pw.w.state(KIND) == ""
          and pw.w.state(CHECK).startswith(f"ECCO START - {KIND_NAME[kind]} at 21:00: the scheduled run recorded its own verified start (STARTED OK). Nothing to report."), pw.w.state(CHECK)[:90])
    check(f"[1] {name}: the dongle and every other service call are identical with and without the package (it never actuates, never writes a number, a switch or a button)",
          dongle_trace(pw, d) == dongle_trace(pw0, d0) and pw.w.warnings == pw0.w.warnings, str(len(dongle_trace(pw, d)[4])))

pw, d = heavy_dump(owner=40, stop=45)
owner_arm(d)
guarded(pw)
check("[1] the guarded Dump to Grid start through the real script (Stop SOC 45 against the reserve 40): the dongle started, nothing to report, settled at once as the guarded start",
      d.successes == 1 and detector_creates(pw) == [] and pw.w.state(COUNT) == "0.0"
      and re.fullmatch(r"ECCO START - Dump to Grid \(Export to Grid\) at 21:00: the guarded start ran [0-9]+ s earlier and its checks were clear\. Nothing to report\.", pw.w.state(CHECK)), pw.w.state(CHECK)[:100])
pw0, d0 = heavy_dump(owner=40, stop=45, detector=False)
owner_arm(d0)
guarded(pw0)
check("[1] the guarded start: the dongle and every other call are identical with and without the package", dongle_trace(pw, d) == dongle_trace(pw0, d0))

print("[2] raw presses through the dongle model: anything that can call a service")
pw, d = heavy_dump(owner=40)
raw_dump(pw, d, stop=45)
check("[2] a raw Dump to Grid press (stage, arm, press; the plan clear, Stop SOC 45 against 40): the dongle starts, ECCO did not: one notice (informational), the record, count 1",
      d.successes == 1 and detector_creates(pw) == [NOTE[DUMP]] and pw.w.state(COUNT) == "1.0" and pw.w.state(KIND) == DUMP
      and pw.w.state(LAST[DUMP]) == "" and pw.w.notifications[NOTE[DUMP]]["title"].endswith("(informational)"), f"{d.successes} {detector_creates(pw)} {pw.w.state(CHECK)[:50]}")
pw, d = heavy_dump(owner=40)
pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
held = pw.w.state(HOLD)
raw_dump(pw, d, stop=25)
check("[2] THE BYPASS: a Hold battery is running (the hold sensor reads held) and Stop SOC 25 is below the reserve 40; a raw press starts Dump to Grid anyway (the firmware does not know), "
      "and the notice names both facts and says a plan check would have refused it",
      held == "held" and d.successes == 1 and detector_creates(pw) == [NOTE[DUMP]]
      and "- WHILE A PLAN CHECK WOULD HAVE REFUSED IT" in pw.w.notifications[NOTE[DUMP]]["title"]
      and "override: an override was ACTIVE" in pw.w.notifications[NOTE[DUMP]]["message"] and "was BELOW the effective reserve (40 %)" in pw.w.notifications[NOTE[DUMP]]["message"]
      and "Override: ACTIVE. Stop SOC below reserve: YES. Plan reading unreadable: no." in pw.w.state(TEXT), f"{held} {d.successes} {pw.w.state(TEXT)[:140]}")
pw, d = heavy_dump(owner=40)
pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
owner_arm(d)
d.stop_soc = 45
pw.w.set(D.D_SOC, "45.0")
guarded(pw, seconds=20)
refused = pw.w.state("input_text.ecco_plan_last_result")
pw.w.run_until(pw.w.t + 10)
raw_dump(pw, d, stop=45, seconds=100)
check("[2] the guarded start refuses during the Hold battery (nothing pressed), and a raw press 30 s later starts it anyway: reported as a bypass, not mistaken for the guarded start",
      refused.startswith("REFUSED OVERRIDE_ACTIVE") and d.successes == 1 and detector_creates(pw) == [NOTE[DUMP]]
      and "WHILE A PLAN CHECK WOULD HAVE REFUSED IT" in pw.w.notifications[NOTE[DUMP]]["title"], f"{refused[:40]} {d.successes} {detector_creates(pw)}")
pw, d = heavy_dump(owner=40)
pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
scheduled(pw, DUMP, seconds=150)
res = pw.w.state(LAST[DUMP])
raw_dump(pw, d, stop=45, seconds=100)
check("[2] a scheduled Dump to Grid start is BLOCKED by the Hold battery (ECCO's own record says so), and a raw press starts Dump to Grid afterwards: a bypass is reported",
      res.startswith("BLOCKED") and d.successes == 1 and detector_creates(pw) == [NOTE[DUMP]], f"{res[:40]} {d.successes} {detector_creates(pw)}")
pw, d = heavy_dump(owner=60)
raw_dump(pw, d, stop=20)
check("[2] a raw press with the staged Stop SOC (20) below the effective reserve (60): the fact is reported, and the same press through the guarded start would have been refused",
      d.successes == 1 and "Stop SOC below reserve: YES" in pw.w.state(TEXT) and "was BELOW the effective reserve (60 %)" in pw.w.notifications[NOTE[DUMP]]["message"], pw.w.state(TEXT)[:140])
pw, d = heavy_free()
raw_free(pw, d)
check("[2] a raw Charge Battery press: the dongle starts, one notice for kind free_power (informational: Charge Battery has no Stop SOC and is not gated by an override), count 1",
      d.successes == 1 and detector_creates(pw) == [NOTE[FREE]] and pw.w.state(KIND) == FREE and pw.w.state(COUNT) == "1.0"
      and pw.w.notifications[NOTE[FREE]]["title"].endswith("(informational)") and "Stop SOC below reserve: n/a" in pw.w.state(TEXT)
      and "ECCO does not gate a Charge Battery start" in pw.w.notifications[NOTE[FREE]]["message"], pw.w.state(TEXT)[:140])
pw, d = heavy_free()
pw.run_script("ecco_plan_override_start", {"kind": "skip_tonight", "expiry_min": 120})
raw_free(pw, d)
check("[2] a raw Charge Battery press during Skip tonight: reported with the override fact for information (ECCO does not gate Charge Battery on it)",
      d.successes == 1 and "Override: ACTIVE" in pw.w.state(TEXT) and pw.w.notifications[NOTE[FREE]]["title"].endswith("- with an override active or unreadable"), pw.w.state(TEXT)[:100])
pw, d = heavy_dump(owner=40)
pw0, d0 = heavy_dump(owner=40, detector=False)
for x, y in ((pw, d), (pw0, d0)):
    raw_dump(x, y, stop=45)
check("[2] a raw press: the dongle and every other service call are identical with and without the package (the detector only notices)", dongle_trace(pw, d) == dongle_trace(pw0, d0))

print("[2] the three facts, against an independent model (a raw press in a world that holds only the package)")
bad_f = case_facts(DET_PKG, quick=False)
check(f"[2] {len(FACT_DUMP)} Dump to Grid and {len(FACT_FREE)} Charge Battery combinations of hold, effective reserve and staged Stop SOC (clear / held / unavailable / junk; a number, unavailable, nan, inf, below 0, above 100, equal) "
      "give exactly the modelled override, Stop SOC, unreadable facts, title and record text", bad_f == [], str(bad_f[:3]))

print("[3] the verdict over a grid of ECCO's own records")
grid_bad: list[str] = []
n_cells = 0
sched_grid = [(OWN_TEXT[DUMP], 0.4), (OWN_TEXT[DUMP], -FRESH), (OWN_TEXT[DUMP], -FRESH - 1), (OWN_TEXT[DUMP], WAIT), (OWN_TEXT[DUMP], WAIT + 2), (RECOVERY, 0.4), ("unavailable", None), ("unknown", None), ("", None)] \
    + [(t, 0.4) for t in OTHER_TEXTS] + [(OWN_TEXT[DUMP], None)]
guard_grid = [None, ("off", 5), ("on", 5), ("off", GUARD_WINDOW), ("off", GUARD_WINDOW + 1), ("off", -3), ("off", -3600), ("unavailable", None), ("unavailable", 5), ("unknown", None), "missing"]
for hold, reserve, stop in (("clear", "20.0", "30.0"), ("held", "20.0", "30.0"), ("clear", "20.0", "10.0"), ("unavailable", "20.0", "30.0")):
    for sched in sched_grid:
        for guard in guard_grid:
            n_cells += 1
            grid_bad += case_marker_model(None, DUMP, sched, guard, hold=hold, reserve=reserve, stop=stop)
for sched in sched_grid:
    for hold in ("clear", "held"):
        n_cells += 1
        grid_bad += case_marker_model(None, FREE, (OWN_TEXT[FREE] if sched[0] == OWN_TEXT[DUMP] else sched[0], sched[1]), None, hold=hold)
check(f"[3] {n_cells} cells (schedule text x guarded start x facts, both kinds): the verdict, the notifications and the record equal the independent model", grid_bad == [], str(grid_bad[:3]))
check("[3] the edges: ECCO's record 10 s before the session counts and 11 s before does not; at 45 s counts and at 47 s does not; the guarded start 180 s before counts, 181 s does not, "
      "after the session (-3 s) does not; the recovery text, FAILED, BLOCKED, UNCONFIRMED, CANCELLED, a lower-case or space-led text and the own form written long before do not count",
      case_markers_core(None) == [] and case_guard_facts(None) == [])
check("[3] recognised ECCO starts are settled at once; a raw start is reported at 45 s and at the latest within a minute", case_ecco_fast(None) == [] and case_timing(None) == [])

print("[4] unreadable markers")
bad_u = case_unreadable(None)
check("[4] an unreadable schedule text or guarded start script is CANNOT CLASSIFY: one unclassified notice, no counter, the last check never says ECCO START; a positive record still wins; "
      "the notice says which marker and that it is not an all clear", bad_u == [], str(bad_u[:3]))

print("[5] restart")
bad_r = case_restart(None)
check("[5] a restart or reconnect with a session running (unavailable, unknown or missing -> on) raises nothing, for both kinds; a restart or an automation reload during a check becomes ONE "
      "CANNOT CLASSIFY (not an all clear, no record) and a storm of restarts adds none; an ordinary start or reload is silent; a new start afterwards is an ordinary check", bad_r == [], str(bad_r[:3]))
pw, d = heavy_dump(owner=40)
scheduled(pw, DUMP)
pkgs_now = [copy.deepcopy(PARSED[k]) for k in ("dump", "plan", "guard")] + [copy.deepcopy(DET_PKG)]
pw.ha.stop()
pw.w.set(D.D_ACTIVE, "unavailable")
pw.ha = S.HA(pw.w, pkgs_now)
arm_detector(pw)
for a in pw.ha.automations:
    if a.id.startswith("ecco_start_bypass"):
        a.ha_start()
pw.w.run_until(pw.w.t + 5)
pw.w.set(D.D_ACTIVE, "on")
pw.w.run_until(pw.w.t + 200)
check("[5] end to end: Home Assistant restarts during a scheduled Dump to Grid session (the sensor goes unavailable, then on): the real packages load again, and the detector raises nothing",
      detector_creates(pw) == [] and pw.w.state(COUNT) == "0.0" and pw.w.state(CHECK).startswith("ECCO START - "), f"{detector_creates(pw)} {pw.w.state(CHECK)[:50]}")

print("[6] repeats")
bad_p = case_repeats(None)
check("[6] a flap or the other kind during a check is dropped silently (one notice, count 1); a new start after a check is a new check (the second notice replaces the first, count 2); "
      "the counter stops at its helper's maximum without an error", bad_p == [], str(bad_p[:3]))
bad_fl = case_flap_limit(None)
check("[6] PINNED LIMIT: a flap of the sensor after a recognised ECCO start is a new start; reported once ECCO's record is older than 10 s, not within 10 s", bad_fl == [], str(bad_fl))

print("[7] mute")
bad_m = case_mute(None)
check("[7] the mute switch hides the popups (bypass, cannot classify, interrupted) and never the record or the last-check text; off or unavailable notifies", bad_m == [], str(bad_m[:3]))
check("[7] no helper refused a write in any world above", P.PlanWorld.rejected_all == [], str(P.PlanWorld.rejected_all[:2]))

# ================================================================================================================================
print("[8] mutation: in-memory mutants of the package are each caught")


def nth_replace(text, old, new, n):
    idx = -1
    for _ in range(n + 1):
        idx = text.index(old, idx + 1)
    return text[:idx] + new + text[idx + len(old):]


MUT_MUTE = "value_template: \"{{ not is_state('input_boolean.ecco_start_bypass_notice_muted', 'on') }}\""
MUTANTS = [
    ("a start from unavailable counts (the off -> on condition removed)", "{{ trigger.from_state is not none and trigger.from_state.state == 'off' }}", "{{ true }}", None),
    ("a start from anything but on counts (!= 'on')", "trigger.from_state.state == 'off' }}", "trigger.from_state.state != 'on' }}", None),
    ("the Free Power trigger is lost", "entity_id: binary_sensor.ecco_clock_dongle_free_power_active", "entity_id: binary_sensor.ecco_clock_dongle_free_power_activex", None),
    ("the Dump to Grid trigger is lost", "entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active", "entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_activex", None),
    ("any STARTED text counts as ECCO's own start", "STARTED OK - [0-9]+W for [0-9]+ min", "STARTED", None),
    ("a stale record counts (no freshness test)", "and as_timestamp(o.last_updated, 0) >= started_ts - 10", "and true", None),
    ("a record of any age up to a day counts", "started_ts - 10) }}", "started_ts - 86400) }}", None),
    ("the guarded start window is open for a day", "guard_age <= 180", "guard_age <= 86400", None),
    ("a guarded start after the session counts (negative age)", "guard_age >= 0 and ", "", None),
    ("the guarded start counts although a fact is true", "guard_age <= 180 and not any_fact }}", "guard_age <= 180 }}", None),
    ("the guarded start counts with its script unreadable", "guard_state in ['on', 'off'] and guard_age >= 0", "true and guard_age >= 0", None),
    ("the override fact is inverted (not clear)", "f_override: \"{{ plan_hold == 'held' }}\"", "f_override: \"{{ plan_hold != 'clear' }}\"", None),
    ("the Stop SOC fact compares with <=", "staged_stop_soc < plan_reserve }}", "staged_stop_soc <= plan_reserve }}", None),
    ("the Stop SOC fact is never true", "and staged_stop_soc >= 0 and staged_stop_soc < plan_reserve }}", "and false }}", None),
    ("an unreadable reserve is not an unreadable fact", "or plan_reserve < 0 or (kind", "or (kind", None),
    ("an unreadable hold is not an unreadable fact", "plan_hold not in ['held', 'clear'] or ", "false or ", None),
    ("an unreadable Stop SOC is not an unreadable fact", "or (kind == 'dump_to_grid' and staged_stop_soc < 0) }}", "}}", None),
    ("an unreadable marker is not cannot-classify (it reads as a bypass)", "{%- elif not sched_readable or not guard_readable -%}CANNOT_CLASSIFY", "{%- elif false -%}CANNOT_CLASSIFY", None),
    ("an unreadable marker reads as an ECCO start (a false all clear)", "{%- elif not sched_readable or not guard_readable -%}CANNOT_CLASSIFY", "{%- elif not sched_readable or not guard_readable -%}ECCO_SCHEDULED", None),
    ("only the schedule marker is checked for readability", "or not guard_readable -%}CANNOT_CLASSIFY", "-%}CANNOT_CLASSIFY", None),
    ("a missing schedule text reads as readable (only unavailable is unreadable)", "sched_text not in ['unknown', 'unavailable']", "sched_text != 'unavailable'", None),
    ("an ECCO scheduled start is reported as a bypass", "{%- elif wait.completed -%}ECCO_SCHEDULED", "{%- elif wait.completed -%}BYPASS", None),
    ("the guarded start is never recognised", "{%- if guarded -%}ECCO_GUARDED", "{%- if false -%}ECCO_GUARDED", None),
    ("the mute switch is ignored for the bypass notice", MUT_MUTE, "value_template: \"{{ true }}\"", 0),
    ("the mute switch is inverted for the bypass notice", MUT_MUTE, "value_template: \"{{ is_state('input_boolean.ecco_start_bypass_notice_muted', 'on') }}\"", 0),
    ("the mute switch is ignored for the unclassified notice", MUT_MUTE, "value_template: \"{{ true }}\"", 1),
    ("the mute switch is ignored for the interrupted notice", MUT_MUTE, "value_template: \"{{ true }}\"", 2),
    ("the counter is not incremented", "value: \"{{ new_count }}\"", "value: \"{{ 0 }}\"", None),
    ("the counter is not clamped to its helper's maximum", "[(states('input_number.ecco_start_bypass_count') | int(0)) + 1, 1000000] | min", "(states('input_number.ecco_start_bypass_count') | int(0)) + 1", None),
    ("the wrong kind is recorded", "value: \"{{ kind }}\"", "value: \"dump_to_grid\"", None),
    ("the time of the incident is not recorded", "timestamp: \"{{ started_ts | int }}\"", "timestamp: \"{{ 0 }}\"", None),
    ("both kinds share one notification id", "'ecco_start_bypass_dump_to_grid' if kind == 'dump_to_grid' else 'ecco_start_bypass_free_power'", "'ecco_start_bypass_dump_to_grid'", None),
    ("the check is not marked pending (an interrupted check is silent)", "'PENDING - '", "'CHECKING - '", None),
    ("the interrupted check alerts on every start (no pending condition)", "states('input_text.ecco_start_bypass_last_check').startswith('PENDING') }}", "true }}", None),
    ("the wait for ECCO's record is 30 minutes", "timeout: \"00:00:45\"", "timeout: \"00:30:00\"", None),
    ("the wait for ECCO's record is one second", "timeout: \"00:00:45\"", "timeout: \"00:00:01\"", None),
    ("the deliberate-start sentence is dropped from the notice", "That includes a deliberate start from the dongle's own screen or button, ", "That includes ", None),
    ("the prevents-nothing sentence is dropped from the notice", "PREVENTS NOTHING: it did not stop this start and cannot stop one. ", "", None),
    ("an actuating call is added (a button press instead of the time record)", "- action: input_datetime.set_datetime", "- action: button.press", None),
    ("a dongle number is written (the staged Stop SOC) instead of the counter", "- action: input_number.set_value\n                continue_on_error: true\n                target:\n                  entity_id: input_number.ecco_start_bypass_count",
     "- action: number.set_value\n                continue_on_error: true\n                target:\n                  entity_id: number.ecco_clock_dongle_dump_to_grid_stop_soc", None),
    ("Charge Battery counts an unreadable Stop SOC as an unreadable plan reading", "or (kind == 'dump_to_grid' and staged_stop_soc < 0) }}", "or staged_stop_soc < 0 }}", None),
    ("the Charge Battery title tail claims a plan check would have refused it", "{%- if kind == 'dump_to_grid' and any_fact -%}", "{%- if any_fact -%}", None),
    ("the incident text drops the facts", "start. Override: '", "start. '", None),
    ("a second entity is read (the dongle's write enable)", "script.ecco_dump_to_grid_start_guarded', 'last_triggered'", "switch.ecco_clock_dongle_dump_to_grid_write_enable', 'last_triggered'", None),
]
killed = 0
for label, old, new, nth in MUTANTS:
    n = DET_TEXT.count(old)
    if (nth is None and n != 1) or (nth is not None and n <= nth):
        check(f"mutant anchor: {label}", False, f"anchor found {n}x")
        continue
    mutated = DET_TEXT.replace(old, new) if nth is None else nth_replace(DET_TEXT, old, new, nth)
    found = battery(mutated)
    if found:
        killed += 1
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS)} mutants, all caught", killed == len(MUTANTS) and len(MUTANTS) >= 15, f"{killed}/{len(MUTANTS)}")
check("the full battery holds on the package as written", battery(DET_TEXT, first_only=False) == [])
_harmless = DET_TEXT.replace("Notification and record only. When a Dump", "Notification and record only (restated). When a Dump")
check("a harmless rewrite (an automation description) survives, and a rewrite of a pinned result text does not",
      _harmless != DET_TEXT and battery(_harmless) == [] and battery(DET_TEXT.replace("Nothing to report.", "Nothing to report here.")) != [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll start bypass detector checks passed.")
print("These prove the package against a model of Home Assistant and the dongle; nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.")
