"""Offline suite for the reserve floor read-back package (home-assistant/packages/ecco_reserve_floor_status.yaml): READ-ONLY.

The package reads what the inverter's own registers say about the battery reserve (the lowest target SOC of the non-charging TOU slots and the battery shutdown SOC,
from the dongle's configuration read) and compares it with the plan's effective reserve: MATCH / BELOW / ABOVE / PENDING / UNREADABLE, one binary sensor
(on only for BELOW or UNREADABLE) and one opt-in notification. A register is not behaviour: the package makes NO claim of enforcement, and has NO DRIFT state (no reliable
fact exists to base one on). Nothing was installed and nothing was written live. This suite proves the package against a model of Home Assistant's template entities
(home-assistant/tests/_reserve_floor_status_sim.py) running the REAL package YAML, its helper and its automation.

  [0] static      only template / input_boolean / automation; the three template entities and nothing else; one helper with no initial value; the only service calls are
                  persistent_notification create and dismiss; it reads exactly the listed entities, every dongle one of them exists in the firmware; no forecast, no
                  Intelligence entity, no write domain; no claim of enforcement and no DRIFT; ASCII, LF, no site value; the header states the rules; the site renderer's
                  exact slug rules; the manifest stanza, the README section and the CHANGELOG bullet
  [1] model       control experiments on the model itself (the availability super template, a reload, a restart's restored window, now() by time alone)
  [2] table       the state table: every verdict, the floor rule (shutdown, the lowest non-charging slot, TOU off, a charging slot never counted), the binary sensor
  [3] sweeps      every input missing, unavailable, unknown, empty, non-numeric or out of range, one at a time; PENDING one cause at a time; freshness at its limits
  [4] differential  the package against an independent model of the rules over a seeded random sample
  [5] notification  the opt-in, the 10 minute debounce, a flap, a reload, a restart, dismissal
  [6] no writes   the model saw no service call but the notification, and no state outside the package's own entities and helper
  [7] mutation    in-memory mutants of the package, each caught

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _reserve_floor_status_sim as M  # noqa: E402
import ecco_site_render as render  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_reserve_floor_status.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
PKG_RAW = (ROOT / PKG_REL).read_bytes()
PKGS = ROOT / "home-assistant" / "packages"
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
DONGLE = "ecco_clock_dongle"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------------------
# helpers shared by the static checks and the mutation battery
# ---------------------------------------------------------------------------------------------------------------------------
class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


class FwLoader(yaml.SafeLoader):
    pass


FwLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def firmware_ids() -> set:
    d = yaml.load(FW_TEXT, Loader=FwLoader)
    out = set()
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                out.add(f"{domain}.{DONGLE}_{slug(e['name'])}")
    return out


FW_IDS = firmware_ids()
OWN_EXPECT = {M.CORE, M.STATUS, M.BINARY}
DONGLE_READS = {e for e in M.READS if e.split(".", 1)[1].startswith(DONGLE + "_")}
ID_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:binary_)?sensor|input_[a-z]+|switch|button|number|select|script|automation|climate|light|lock|cover|fan|esphome|modbus|mqtt|rest_command|"
                   r"shell_command|scene|group|timer|counter|persistent_notification)\.([a-z0-9_]+)")
FORBIDDEN_DOMAINS = ("number", "select", "switch", "button", "script", "climate", "light", "lock", "cover", "fan", "esphome", "modbus", "mqtt", "rest_command",
                     "shell_command", "scene", "group", "timer", "counter", "input_number", "input_text", "input_select", "input_datetime")
# the words a contract id, a forecast or a claim of enforcement would need (the split literals keep this file clear of the Intelligence id scan)
INTEL = "ecco_" "intel"
SOLCAST = "solc" "ast"


def code_lines(text: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))


def collect_actions(node, acc: list) -> list:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "action" and isinstance(v, str):
                acc.append(v)
            collect_actions(v, acc)
    elif isinstance(node, list):
        for v in node:
            collect_actions(v, acc)
    return acc


def privacy_problems(text: str) -> list:
    bad = []
    if re.search(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", text):
        bad.append("an IPv4 address")
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", text):
        bad.append("an e-mail address")
    if re.search(r"https?://|www\.", text):
        bad.append("a link")
    if re.search(r"api[_ -]?key|password|secret|token", text, re.I):
        bad.append("a key or secret word")
    if re.search(r"[A-Za-z]:\\|/Users/|/home/", text):
        bad.append("a path")
    if any(ord(c) > 126 or (ord(c) < 32 and c != "\n") for c in text):
        bad.append("a non-ASCII or control character")
    if re.search(r"[ \t]+$", text, re.M):
        bad.append("trailing space")
    return bad


HEADER_MUST = ("A REGISTER IS NOT BEHAVIOUR", "NO DRIFT STATE", "THE FLOOR.", "PENDING", "UNREADABLE (never a guess)", "THE BINARY SENSOR", "THE NOTIFICATION", "FAIL SAFE",
               "HARD RULES", "LIMITS", "RECORDER FOOTPRINT (ESTIMATE", "INSTALL.", "proof R6", "naive local-time text", "measured on a real core", "1800 s", "150 s", "10 minutes")


def static_problems(text: str) -> list:
    """Everything the file itself must satisfy: returns the problems found (empty = clean). Used on the package and on every mutant."""
    bad = []
    try:
        doc = yaml.load(text, Loader=UniqueKeyLoader) or {}
    except Exception as exc:  # noqa: BLE001
        return [f"YAML does not parse: {str(exc)[:100]}"]
    if set(doc) != {"input_boolean", "template", "automation"}:
        bad.append(f"top-level keys are {sorted(doc)}")
        return bad
    names = []
    for block in doc.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                names.append((f"{kind}.{slug(it.get('name', ''))}", it.get("unique_id")))
    if {n for n, _u in names} != OWN_EXPECT or len(names) != 3:
        bad.append(f"template entities are {sorted(n for n, _u in names)}")
    if sorted(u for _n, u in names) != sorted(n.split(".", 1)[1] for n, _u in names):
        bad.append("a unique_id is not the entity id's object")
    hb = doc.get("input_boolean") or {}
    if set(hb) != {M.OPTIN.split(".", 1)[1]} or any("initial" in (v or {}) for v in hb.values()):
        bad.append("the opt-in helper is not the one helper without an initial value")
    if [a.get("id") for a in doc.get("automation") or []] != ["ecco_reserve_floor_notify"]:
        bad.append("the automation is not exactly ecco_reserve_floor_notify")
    acts = collect_actions(doc, [])
    if sorted(set(acts)) != ["persistent_notification.create", "persistent_notification.dismiss"]:
        bad.append(f"the service calls are {sorted(set(acts))}")
    code = code_lines(text)
    ids = {f"{m.group(1)}.{m.group(2)}" for m in ID_RE.finditer(code)}
    allowed = M.READS | OWN_EXPECT | {M.OPTIN}
    extra = sorted(i for i in ids if i not in allowed and not i.startswith("persistent_notification."))
    if extra:
        bad.append(f"it mentions entities outside its list: {extra[:3]}")
    missing = sorted(allowed - ids)
    if missing:
        bad.append(f"it no longer reads: {missing[:3]}")
    dom = sorted({i for i in ids if i.split(".", 1)[0] in FORBIDDEN_DOMAINS})
    if dom:
        bad.append(f"a write domain appears: {dom[:3]}")
    low = code.lower()
    for word in (INTEL, SOLCAST, "forecast", "intelligence"):
        if word in low:
            bad.append(f"it reads or names {word!r}")
    if re.search(r"\b(ENFORCED|HELD|PROTECTED|DRIFT)\b", code):
        bad.append("a state word claims enforcement or DRIFT")
    if "NOT PROVEN" not in code:
        bad.append("the behaviour note is gone")
    for p in privacy_problems(text):
        bad.append(f"hygiene: {p}")
    if "\r" in text or "\t" in text:
        bad.append("a CR or a tab")
    for phrase in HEADER_MUST:
        if phrase not in text:
            bad.append(f"the header lost {phrase!r}")
    vals = set(re.findall(r"set r\.v = '([A-Z]+)'", text))
    if vals != {"UNREADABLE", "PENDING", "MATCH", "BELOW", "ABOVE"}:
        bad.append(f"the verdicts are {sorted(vals)}")
    return bad


# ===========================================================================================================================
# the oracle: an independent model of the rules (it does not read the package)
# ===========================================================================================================================
FRESH_S, LOST_S, DEBOUNCE_S = 150, 1800, 600


def whole(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0 or v > 100 or v != int(v):
        return None
    return int(v)


def oracle(st: dict, now: float, zone) -> tuple:
    """(verdict, floor or None) of the rules, from a map entity -> state text (a missing entity reads 'unknown')."""
    g = lambda e: st.get(e, "unknown")  # noqa: E731
    E = whole(g(M.PLAN))
    if E is None:
        return "UNREADABLE", None
    flags = [g(f) for f in M.FLAGS]
    if any(f not in ("on", "off") for f in flags):
        return "UNREADABLE", None
    rfp, rdg = g(M.REC_FP), g(M.REC_DG)
    if rfp in ("unknown", "unavailable", "") or rdg in ("unknown", "unavailable", ""):
        return "UNREADABLE", None
    if "on" in flags or rfp != "NONE" or not (rdg.startswith("NONE") or rdg.startswith("ACCEPTED")):
        return "PENDING", None
    online, txt = g(M.ONLINE), g(M.CFGTIME)
    age = None
    try:
        age = abs(now - datetime.strptime(txt, M.FMT).replace(tzinfo=zone).timestamp())
    except ValueError:
        age = None
    if online not in ("on", "off") or age is None:
        return "UNREADABLE", None
    if age > LOST_S:
        return "UNREADABLE", None
    if online == "off" or age > FRESH_S:
        return "PENDING", None
    socs = [whole(g(e)) for e in M.SOC]
    srcs = [g(e) for e in M.SRC]
    if any(s is None for s in socs) or any(s not in ("None", "Grid", "Generator", "Grid + Generator") for s in srcs):
        return "UNREADABLE", None
    shut, tou = whole(g(M.SHUT)), g(M.TOU)
    if shut is None or tou not in ("on", "off"):
        return "UNREADABLE", None
    nc = [socs[i] for i in range(6) if srcs[i] == "None"]
    if tou == "on" and not nc:
        return "UNREADABLE", None
    floor = max(shut, min(nc)) if tou == "on" else shut
    return ("MATCH" if floor == E else ("BELOW" if floor < E else "ABOVE")), floor


# ===========================================================================================================================
# worlds and scenarios (each returns the list of problems it found, for the package and for every mutant)
# ===========================================================================================================================
def world(text: str, live: bool = False, **kw):
    """A healthy house. `live`: the dongle publishes its configuration time every 60 s (a world that lets time pass); otherwise one read made right now."""
    fw = M.FloorWorld(text)
    fw.feed_handle = M.house(fw, feed=live, **kw)
    if not live:
        fw.put(M.CFGTIME, fw.local_text(fw.w.t), None)      # a configuration read made right now
    fw.force()
    return fw


def rec(fw) -> dict:
    p = fw.state(M.CORE).split("|")
    return dict(zip(("v", "floor", "slot", "shut", "res", "nc", "ch", "tou", "cfg", "why"), p)) if len(p) == 10 else {"v": fw.state(M.CORE)}


def snapshot(fw) -> dict:
    return {e: fw.w.states[e][0] for e in (M.READS) if e in fw.w.states}


def apply(fw, mods: dict) -> dict:
    """Apply `mods` (entity -> state, None removes) and return what to put back."""
    back = {e: (fw.w.states[e][0] if e in fw.w.states else None) for e in mods}
    for e, s in mods.items():
        fw.put(e, s)
    return back


def undo(fw, back: dict) -> None:
    for e, s in back.items():
        fw.put(e, s)


def aged(fw, seconds: float) -> str:
    return fw.local_text(fw.w.t + fw.w.clock_offset - seconds)


# the state table: (label, mods, verdict, floor or None). The base house: reserve 5, slot 1 charges (Grid, 100), slots 2 to 6 None at 5, shutdown 0, TOU on.
def table(fw) -> list:
    g = lambda **k: k  # noqa: E731
    cases = [
        ("the base house matches", {}, "MATCH", 5),
        ("today's house: non-charging targets at 0 percent read BELOW", {**{e: "0" for e in M.SOC[1:]}}, "BELOW", 0),
        ("one non-charging slot below the others lowers the floor", {M.SOC[3]: "3"}, "BELOW", 3),
        ("the lowest non-charging slot wins over the others above it", {**{M.SOC[1]: "9", M.SOC[2]: "7", M.SOC[3]: "5", M.SOC[4]: "8", M.SOC[5]: "6"}}, "MATCH", 5),
        ("every non-charging slot above the reserve reads ABOVE", {**{e: "10" for e in M.SOC[1:]}}, "ABOVE", 10),
        ("a shutdown SOC above the slot floors is the floor", {M.SHUT: "10"}, "ABOVE", 10),
        ("a shutdown SOC equal to the reserve matches with lower slot floors", {M.SHUT: "5", **{e: "0" for e in M.SOC[1:]}}, "MATCH", 5),
        ("the charge slot's own target is never counted (slot 1 at 0 percent, source Grid)", {M.SOC[0]: "0"}, "MATCH", 5),
        ("a Generator slot is a charging slot and is not counted", {M.SRC[2]: "Generator", M.SOC[2]: "0"}, "MATCH", 5),
        ("a Grid + Generator slot is a charging slot and is not counted", {M.SRC[3]: "Grid + Generator", M.SOC[3]: "0"}, "MATCH", 5),
        ("two charging slots are both left out", {M.SRC[1]: "Grid", M.SOC[1]: "0", M.SRC[4]: "Generator", M.SOC[4]: "0"}, "MATCH", 5),
        ("TOU off: the slot targets are not in force, the floor is the shutdown SOC (0 here)", {M.TOU: "off"}, "BELOW", 0),
        ("TOU off with a shutdown SOC equal to the reserve matches", {M.TOU: "off", M.SHUT: "5"}, "MATCH", 5),
        ("TOU off: a slot target of 90 does not raise the floor", {M.TOU: "off", **{e: "90" for e in M.SOC[1:]}}, "BELOW", 0),
        ("TOU on and every slot charging: no slot to read a floor from", {**{e: "Grid" for e in M.SRC}}, "UNREADABLE", None),
        ("TOU off and every slot charging: the shutdown SOC alone", {M.TOU: "off", M.SHUT: "5", **{e: "Grid" for e in M.SRC}}, "MATCH", 5),
        ("a reserve of 0 with floors of 0 matches", {M.PLAN: "0", M.SHUT: "0", **{e: "0" for e in M.SOC[1:]}}, "MATCH", 0),
        ("a reserve of 80 with floors of 5 reads BELOW (a power cut reserve)", {M.PLAN: "80"}, "BELOW", 5),
        ("a reserve of 100 is a reading", {M.PLAN: "100"}, "BELOW", 5),
        ("a floor of 100 everywhere matches a reserve of 100", {M.PLAN: "100", **{e: "100" for e in M.SOC}}, "MATCH", 100),
        ("a fractional text that is whole reads (5.0)", {M.PLAN: "5.0", M.SOC[1]: "5.0"}, "MATCH", 5),
    ]
    return cases


def sc_table(text: str) -> list:
    bad = []
    fw = world(text)
    base = rec(fw)
    if base.get("v") != "MATCH":
        return [f"the base house reads {base}"]
    for label, mods, verdict, floor in table(fw):
        back = apply(fw, mods)
        r = rec(fw)
        st, b = fw.state(M.STATUS), fw.state(M.BINARY)
        want_b = "on" if verdict in ("BELOW", "UNREADABLE") else "off"
        if r.get("v") != verdict or st != verdict or b != want_b or (floor is not None and r.get("floor") != str(floor)):
            bad.append(f"{label}: record {r.get('v')}/{r.get('floor')}, status {st}, binary {b}; wanted {verdict}/{floor}/{want_b}")
        undo(fw, back)
    if fw.errors:
        bad.append(f"template errors {fw.errors[:2]}")
    return bad


def sc_unreadable(text: str) -> list:
    """Every input missing, unavailable, unknown, empty, non-numeric or out of range, one at a time, is UNREADABLE (never MATCH, never a guess)."""
    bad = []
    fw = world(text)
    junk_num = [None, "unavailable", "unknown", "", "abc", "nan", "inf", "-1", "101", "5.5", "1e9", "None", "on"]
    for e in [M.PLAN, M.SHUT] + M.SOC:
        for j in junk_num:
            back = apply(fw, {e: j})
            v = rec(fw).get("v")
            if v != "UNREADABLE" or fw.state(M.BINARY) != "on":
                bad.append(f"{e} = {j!r} reads {v}/{fw.state(M.BINARY)}")
            undo(fw, back)
    for e in M.SRC:
        for j in [None, "unavailable", "unknown", "", "Unknown", "none", "GRID", "Battery", "0", "None "]:
            back = apply(fw, {e: j})
            v = rec(fw).get("v")
            if v != "UNREADABLE":
                bad.append(f"{e} = {j!r} reads {v}")
            undo(fw, back)
    for e in [M.TOU, M.ONLINE] + M.FLAGS:
        for j in [None, "unavailable", "unknown", "", "ON", "true", "1", "maybe"]:
            back = apply(fw, {e: j})
            v = rec(fw).get("v")
            if v != "UNREADABLE":
                bad.append(f"{e} = {j!r} reads {v}")
            undo(fw, back)
    for e in (M.REC_FP, M.REC_DG):
        for j in [None, "unavailable", "unknown", ""]:
            back = apply(fw, {e: j})
            v = rec(fw).get("v")
            if v != "UNREADABLE":
                bad.append(f"{e} = {j!r} reads {v}")
            undo(fw, back)
    for j in [None, "unavailable", "unknown", "", "Waiting", "2026-11-27", "2026-11-27 12:00", "2026-11-27T12:00:00", "27/11/2026 12:00:00", "12:00:00"]:
        back = apply(fw, {M.CFGTIME: j})
        v = rec(fw).get("v")
        if v != "UNREADABLE":
            bad.append(f"the configuration time {j!r} reads {v}")
        undo(fw, back)
    if rec(fw).get("v") != "MATCH":
        bad.append("the sweep did not restore the base house")
    return bad


def sc_pending(text: str) -> list:
    bad = []
    fw = world(text)
    for e in M.FLAGS:
        back = apply(fw, {e: "on"})
        v = rec(fw).get("v")
        if v != "PENDING" or fw.state(M.BINARY) != "off":
            bad.append(f"{e} on reads {v}/{fw.state(M.BINARY)}")
        undo(fw, back)
    for e, val, want in [(M.REC_FP, "RESTORE OWED", "PENDING"), (M.REC_FP, "none", "PENDING"), (M.REC_DG, "ACTIVE - export", "PENDING"), (M.REC_DG, "NONE - idle", "MATCH"),
                         (M.REC_DG, "NONE", "MATCH"), (M.REC_DG, "ACCEPTED - operator", "MATCH"), (M.REC_DG, "accepted", "PENDING"), (M.REC_DG, "RECOVERY BLOCKED", "PENDING")]:
        back = apply(fw, {e: val})
        v = rec(fw).get("v")
        if v != want:
            bad.append(f"{e} = {val!r} reads {v}, wanted {want}")
        undo(fw, back)
    # a lease beats an unreadable slot (the slots are not judged while a lease owns them), an unreadable flag beats a lease
    back = apply(fw, {M.FLAGS[0]: "on", M.SOC[2]: "unavailable"})
    if rec(fw).get("v") != "PENDING":
        bad.append("a lease with an unreadable slot is not PENDING")
    undo(fw, back)
    back = apply(fw, {M.FLAGS[0]: "on", M.FLAGS[3]: "unavailable"})
    if rec(fw).get("v") != "UNREADABLE":
        bad.append("a lease with an unreadable flag is not UNREADABLE")
    undo(fw, back)
    back = apply(fw, {M.FLAGS[1]: "on", M.PLAN: "unknown"})
    if rec(fw).get("v") != "UNREADABLE":
        bad.append("a lease with an unreadable reserve is not UNREADABLE")
    undo(fw, back)
    # freshness at its limits (150 s fresh, 151 s stale, offline stale, 1800 s stale, 1801 s lost, a future text judged by its distance)
    for age, online, want in [(0, "on", "MATCH"), (149, "on", "MATCH"), (150, "on", "MATCH"), (151, "on", "PENDING"), (900, "on", "PENDING"), (1799, "on", "PENDING"), (1800, "on", "PENDING"),
                              (1801, "on", "UNREADABLE"), (7200, "on", "UNREADABLE"), (10, "off", "PENDING"), (1801, "off", "UNREADABLE"), (-149, "on", "MATCH"), (-151, "on", "PENDING"),
                              (-1801, "on", "UNREADABLE")]:
        back = apply(fw, {M.CFGTIME: aged(fw, age), M.ONLINE: online})
        v = rec(fw).get("v")
        if v != want:
            bad.append(f"a configuration read {age} s old with online {online} reads {v}, wanted {want}")
        undo(fw, back)
    return bad


def sc_attributes(text: str) -> list:
    bad = []
    fw = world(text)
    a = lambda n: fw.attr(M.STATUS, n)  # noqa: E731
    if (a("floor_percent"), a("slot_floor_percent"), a("shutdown_percent"), a("effective_reserve_percent"), a("difference_percent"), a("mismatch")) != (5, 5, 0, 5, 0, False):
        bad.append(f"MATCH attributes {[a(n) for n in ('floor_percent', 'slot_floor_percent', 'shutdown_percent', 'effective_reserve_percent', 'difference_percent', 'mismatch')]}")
    if (a("non_charging_slots"), a("charging_slots"), a("tou_enabled"), a("configuration_read")) != ([2, 3, 4, 5, 6], [1], True, "fresh"):
        bad.append("slots, TOU flag or configuration read attribute")
    if not str(a("behaviour")).startswith("NOT PROVEN"):
        bad.append("the behaviour note")
    inputs = a("inputs") or []
    if not (isinstance(inputs, list) and len(inputs) == len(M.READS) - 1 and all(isinstance(x, str) for x in inputs)):
        bad.append(f"the inputs attribute has {len(inputs) if isinstance(inputs, list) else inputs!r} entries")
    elif not all(any(x.startswith(e + " = ") for x in inputs) for e in M.READS if e != M.CFGTIME) or f"{M.PLAN} = 5 (live)" not in inputs:
        bad.append("an input is missing from the inputs attribute")
    elif not any(x == f"{M.SOC[2]} = 5 (fresh)" for x in inputs):
        bad.append("an input does not carry its freshness")
    back = apply(fw, {e: "0" for e in M.SOC[1:]})
    if (a("floor_percent"), a("difference_percent"), a("mismatch"), fw.state(M.STATUS), a("reason")) != (0, -5, True, "BELOW", "the registers read a floor of 0 percent, below the effective reserve of 5 percent: the reserve is software only"):
        bad.append(f"BELOW attributes {[a(n) for n in ('floor_percent', 'difference_percent', 'mismatch', 'reason')]}")
    undo(fw, back)
    back = apply(fw, {M.SHUT: "10"})
    if (a("difference_percent"), a("mismatch"), fw.state(M.STATUS)) != (5, True, "ABOVE"):
        bad.append("ABOVE attributes")
    undo(fw, back)
    back = apply(fw, {M.FLAGS[3]: "on"})
    if (a("floor_percent"), a("slot_floor_percent"), a("difference_percent"), a("mismatch"), a("shutdown_percent"), a("effective_reserve_percent")) != ("unknown", "unknown", "unknown", "unknown", 0, 5):
        bad.append(f"PENDING attributes {[a(n) for n in ('floor_percent', 'slot_floor_percent', 'difference_percent', 'mismatch')]}")
    undo(fw, back)
    back = apply(fw, {M.CFGTIME: aged(fw, 300)})
    if a("configuration_read") != "stale":
        bad.append("a late read is not shown as stale")
    undo(fw, back)
    back = apply(fw, {M.TOU: "off"})
    if (a("tou_enabled"), a("slot_floor_percent")) != (False, "unknown"):
        bad.append("TOU off attributes")
    undo(fw, back)
    back = apply(fw, {M.PLAN: "unknown"})
    if (fw.state(M.STATUS), fw.state(M.BINARY), a("effective_reserve_percent")) != ("UNREADABLE", "on", "unknown"):
        bad.append("an unreadable reserve attributes")
    undo(fw, back)
    if len(fw.state(M.CORE)) > 255 or any(len(rec(fw).get("why", "")) > 140 for _ in (0,)):
        bad.append("the record is too long")
    return bad


def sc_reasons(text: str) -> list:
    """The reason names the cause in words and is never cut short; the record stays below 255 characters in the worst case."""
    bad = []
    fw = world(text)
    worst = 0
    cases = [({M.SOC[4]: "unavailable"}, "reads unavailable"), ({M.SRC[5]: "Battery"}, "reads Battery"), ({M.FLAGS[6]: "on"}, "in progress"), ({M.REC_FP: "OWED"}, "recovery state is open"),
             ({M.CFGTIME: aged(fw, 400)}, "waiting for a fresh configuration read"), ({M.ONLINE: "off"}, "offline"), ({M.CFGTIME: aged(fw, 4000)}, "cannot be trusted"),
             ({M.PLAN: "unknown"}, "plan effective reserve cannot be read"), ({M.SHUT: "unknown"}, "shutdown SOC cannot be read"), ({M.TOU: "unknown"}, "Time Of Use flag"),
             ({**{e: "Grid" for e in M.SRC}}, "no slot has charge source None"), ({M.PLAN: "7"}, "software only"), ({M.PLAN: "3"}, "above the effective reserve of 3 percent"),
             ({M.REC_DG: "unknown", M.REC_FP: "unknown"}, "a recovery state cannot be read")]
    for mods, needle in cases:
        back = apply(fw, mods)
        r = rec(fw)
        worst = max(worst, len(fw.state(M.CORE)))
        if needle not in r.get("why", ""):
            bad.append(f"{mods} reason {r.get('why')!r} lacks {needle!r}")
        undo(fw, back)
    long_id = {M.CFGTIME: "x" * 300, M.ONLINE: "y" * 300}
    back = apply(fw, long_id)
    worst = max(worst, len(fw.state(M.CORE)))
    undo(fw, back)
    if worst > 255 or fw.errors:
        bad.append(f"the worst record is {worst} characters, errors {fw.errors[:1]}")
    return bad


def sc_binary(text: str) -> list:
    """The binary sensor is an allow-list on the status sensor: on only for BELOW and UNREADABLE, unavailable while the status is unreadable."""
    bad = []
    fw = world(text)
    for status, want in [("MATCH", "off"), ("ABOVE", "off"), ("PENDING", "off"), ("BELOW", "on"), ("UNREADABLE", "on"), ("unavailable", "unavailable"), ("unknown", "unavailable"),
                         ("", "unavailable"), ("match", "unavailable"), ("DRIFT", "unavailable"), ("ENFORCED", "unavailable")]:
        fw.override(M.STATUS, status)
        if fw.state(M.BINARY) != want:
            bad.append(f"status {status!r} gives the binary sensor {fw.state(M.BINARY)}, wanted {want}")
    fw.override(M.STATUS, None)
    if fw.attr(M.BINARY, "status") != fw.state(M.STATUS):
        bad.append("the binary sensor's status attribute")
    # the status sensor is unavailable while the record cannot be read
    for j in ["unavailable", "unknown", "", "BELOW|1|2", "WHATEVER|-|-|-|-|-|-|-|-|x", "MATCH|1|2|3|4|5|6|7|8|9|10"]:
        fw.override(M.CORE, j)
        if fw.state(M.STATUS) != "unavailable" or fw.state(M.BINARY) != "unavailable":
            bad.append(f"a record {j!r} gives status {fw.state(M.STATUS)} and binary {fw.state(M.BINARY)}")
    fw.override(M.CORE, None)
    return bad


def sc_notify(text: str) -> list:
    bad = []
    # the opt-in is off: BELOW for half an hour raises nothing
    fw = world(text, live=True)
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(1800)
    if fw.notifications:
        bad.append("a notification without the opt-in")
    # the opt-in on: nothing before 10 minutes, one after, and only one
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(599)
    if fw.notifications:
        bad.append("a notification before the debounce ended")
    fw.advance(62)
    if list(fw.notifications) != [M.NOTE]:
        bad.append(f"no single notification after 10 minutes: {list(fw.notifications)}")
    n = len([x for x in fw.w.notification_log if x[1] == "create"])
    fw.advance(3600)
    if len([x for x in fw.w.notification_log if x[1] == "create"]) != n:
        bad.append("the notification is created again while it stands")
    # it is dismissed when the verdict returns to MATCH
    for e in M.SOC[1:]:
        fw.put(e, "5")
    fw.advance(1)
    if fw.notifications:
        bad.append("not dismissed at MATCH")
    # a flap restarts the 10 minutes; PENDING (a lease) and ABOVE are no warning
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(500)
    fw.put(M.FLAGS[0], "on")
    fw.advance(30)
    fw.put(M.FLAGS[0], "off")
    fw.advance(500)
    if fw.notifications:
        bad.append("a flap did not restart the debounce")
    fw.advance(200)
    if list(fw.notifications) != [M.NOTE]:
        bad.append("no notification after the restarted debounce")
    # UNREADABLE for 10 minutes also raises it; turning the opt-in off dismisses it
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    fw.put(M.SHUT, "unavailable")
    fw.advance(660)
    if list(fw.notifications) != [M.NOTE]:
        bad.append("UNREADABLE for 10 minutes raised nothing")
    fw.put(M.OPTIN, "off")
    fw.advance(1)
    if fw.notifications:
        bad.append("turning the opt-in off did not dismiss it")
    # the opt-in turned on after BELOW has persisted raises it at once (the template trigger turns true)
    fw = world(text, live=True)
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(1200)
    fw.put(M.OPTIN, "on")
    fw.advance(1)
    if list(fw.notifications) != [M.NOTE]:
        bad.append("the opt-in turned on after 20 minutes of BELOW raised nothing")
    # ABOVE and PENDING never raise it
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    fw.put(M.SHUT, "10")
    fw.advance(1200)
    fw.put(M.SHUT, "0")
    fw.put(M.FLAGS[0], "on")
    fw.advance(1200)
    if fw.notifications or fw.errors:
        bad.append(f"ABOVE or PENDING raised a notification {list(fw.notifications)} {fw.errors[:1]}")
    return bad


def sc_reload_restart(text: str) -> list:
    bad = []
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(660)
    if list(fw.notifications) != [M.NOTE]:
        return ["no notification to start the reload test from"]
    creates = lambda: len([x for x in fw.w.notification_log if x[1] == "create"])  # noqa: E731
    c0 = creates()
    # a template reload: every template entity reads unavailable once, then its value; the notification is neither dismissed nor created again at once
    fw.reload()
    if fw.state(M.STATUS) != "BELOW" or fw.state(M.BINARY) != "on" or fw.errors:
        bad.append(f"after a reload {fw.state(M.STATUS)}/{fw.state(M.BINARY)} {fw.errors[:1]}")
    if creates() != c0 or M.NOTE not in fw.notifications:
        bad.append("a reload created or dismissed the notification at once")
    # the debounce restarts after a reload (last_changed is new): a second notice comes only after another 10 minutes, and replaces the first (one fixed id)
    fw.advance(660)
    if creates() > c0 + 1 or list(fw.notifications) != [M.NOTE]:
        bad.append("a reload made more than one notification")
    # a restart: the restored states exist before the first render; a new automation instance starts; no notification is created by the restart itself
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    fw.advance(30)
    c1 = len([x for x in fw.w.notification_log if x[1] == "create"])
    fw.feed_handle["on"] = False
    fw.restart(gone=tuple(e for e in M.READS if e.startswith("sensor.ecco_clock_dongle") or e.startswith("binary_sensor.ecco_clock_dongle")))
    fw.advance(0.01)
    if fw.state(M.STATUS) != "MATCH" or fw.state(M.BINARY) != "off":
        bad.append(f"the restored window shows {fw.state(M.STATUS)}/{fw.state(M.BINARY)}")
    fw.advance(0.2)
    if fw.state(M.STATUS) not in ("UNREADABLE", "unavailable") or len([x for x in fw.w.notification_log if x[1] == "create"]) != c1:
        bad.append(f"after the first render with the dongle gone: {fw.state(M.STATUS)}")
    # the dongle comes back, healthy: MATCH, and no notification at any time
    fw.feed_handle = M.house(fw, feed=True)
    fw.force()
    fw.advance(3600)
    if fw.state(M.STATUS) != "MATCH" or fw.notifications or fw.errors:
        bad.append(f"after the dongle returned {fw.state(M.STATUS)} {list(fw.notifications)} {fw.errors[:1]}")
    # a restart while BELOW has stood for an hour: the restored 'on' is a new state, so nothing is created for 10 minutes after the restart
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(3600)
    fw.w.notifications.clear()
    c2 = len([x for x in fw.w.notification_log if x[1] == "create"])
    fw.restart()
    fw.advance(300)
    if len([x for x in fw.w.notification_log if x[1] == "create"]) != c2:
        bad.append("a restart created the notification inside the debounce")
    fw.advance(400)
    if len([x for x in fw.w.notification_log if x[1] == "create"]) != c2 + 1:
        bad.append("a persistent BELOW after a restart never raised the notification")
    return bad


def sc_time(text: str) -> list:
    """The configuration read goes stale by the passing of time alone (the templates use now()), and the dongle's feed keeps it fresh."""
    bad = []
    fw = M.FloorWorld(text)
    handle = M.house(fw, feed=True)
    fw.advance(300)
    if rec(fw).get("v") != "MATCH":
        bad.append(f"a fed configuration read reads {rec(fw).get('v')}")
    handle["on"] = False
    fw.advance(100)
    v1 = rec(fw).get("v")
    fw.advance(100)
    v2 = rec(fw).get("v")
    fw.advance(1900)
    v3 = rec(fw).get("v")
    if (v1, v2, v3) != ("MATCH", "PENDING", "UNREADABLE"):
        bad.append(f"a read that stops reads {v1} at 100 s (or less than 150), {v2} at 200 s, {v3} after 2200 s")
    return bad


def sc_differential(text: str, samples: int = 400, seed: int = 7) -> list:
    rnd = random.Random(seed)
    bad = []
    fw = world(text)
    zone = fw.zone
    pools = {
        **{e: ["0", "5", "10", "50", "100"] for e in M.SOC},
        M.SHUT: ["0", "5", "10", "30"], M.PLAN: ["0", "5", "5", "10", "80", "100"],
        M.TOU: ["on", "on", "on", "off"], M.ONLINE: ["on", "on", "on", "off"],
        **{e: ["None", "None", "None", "Grid", "Generator", "Grid + Generator"] for e in M.SRC},
        **{e: ["off", "off", "off", "off", "off", "on"] for e in M.FLAGS},
        M.REC_FP: ["NONE", "NONE", "NONE", "RESTORE OWED"], M.REC_DG: ["NONE", "NONE - idle", "ACCEPTED - x", "NONE", "RECOVERY OPEN"],
    }
    bads = {e: ["unavailable", "unknown", "", "abc", "101", "-3", "5.5", None] for e in pools}
    ages = [0, 30, 149, 150, 151, 600, 1799, 1800, 1801, 4000, -100, -200]
    for _ in range(samples):
        mods = {}
        for e, pool in pools.items():
            r = rnd.random()
            mods[e] = rnd.choice(bads[e]) if r < 0.04 else rnd.choice(pool)
        age = rnd.choice(ages)
        mods[M.CFGTIME] = rnd.choice(["Waiting", "unavailable", aged(fw, age)]) if rnd.random() < 0.06 else aged(fw, age)
        fw.put_many(mods)
        st = snapshot(fw)
        want, floor = oracle(st, fw.w.t + fw.w.clock_offset, zone)
        r = rec(fw)
        if r.get("v") != want or (floor is not None and r.get("floor") != str(floor)):
            bad.append(f"{r.get('v')}/{r.get('floor')} against the model's {want}/{floor} for {mods}")
            if len(bad) >= 3:
                break
    if fw.errors:
        bad.append(f"template errors {fw.errors[:2]}")
    return bad


def sc_writes(text: str) -> list:
    """Over a whole session the model saw nothing but the notification service, and wrote no state outside the package's own entities and helper."""
    bad = []
    fw = world(text, live=True)
    fw.put(M.OPTIN, "on")
    for e in M.SOC[1:]:
        fw.put(e, "0")
    fw.advance(700)
    fw.put(M.SOC[2], "5")
    fw.reload()
    fw.advance(100)
    services = {s for _t, s, _e, _d in fw.w.service_log}
    if services - {"persistent_notification.create", "persistent_notification.dismiss"}:
        bad.append(f"services called: {sorted(services)}")
    touched = {e for _t, e, _s in fw.w.history}
    known = M.READS | M.OWN | {M.OPTIN}
    if touched - known:
        bad.append(f"states written outside the package: {sorted(touched - known)[:3]}")
    return bad


BATTERY = [("static", lambda t: static_problems(t)), ("table", sc_table), ("attributes", sc_attributes), ("pending", sc_pending), ("unreadable", sc_unreadable),
           ("binary", sc_binary), ("reasons", sc_reasons), ("notify", sc_notify), ("reload-restart", sc_reload_restart), ("time", sc_time), ("writes", sc_writes)]


def battery(text: str, kill: bool = False, prefer: str | None = None, info: dict | None = None) -> list:
    found = []
    order = sorted(BATTERY, key=lambda b: 0 if b[0] == prefer else 1)
    for name, fn in order:
        try:
            probs = fn(text)
        except Exception as exc:  # noqa: BLE001 - a mutant that breaks the model is caught
            probs = [f"{type(exc).__name__}: {str(exc)[:100]}"]
        if probs:
            found += [f"[{name}] {p}" for p in probs]
            if info is not None:
                info["section"] = name
            if kill:
                return found
    return found


# ===========================================================================================================================
print("[0] static: the file, its entities, its vocabulary, its words")
# ===========================================================================================================================
check("the package parses and satisfies every static rule (entities, helper, vocabulary, reads, words, hygiene, header)", static_problems(PKG_TEXT) == [], str(static_problems(PKG_TEXT)[:3]))
check("the static rules are live: each flags an injected breach",
      all(static_problems(m) for m in (PKG_TEXT + "\n# 203.0.113.5\n", PKG_TEXT.replace("persistent_notification.dismiss", "button.press"),
                                       PKG_TEXT.replace("ecco_cfg_edit_in_flight", "ecco_cfg_edit_in_flight_x"), PKG_TEXT + "\t",
                                       PKG_TEXT.replace("icon: mdi:bell-ring-outline", "icon: mdi:bell-ring-outline\n    initial: true"),
                                       PKG_TEXT.replace("NOT PROVEN: a register", "a register"), PKG_TEXT.replace("set r.v = 'ABOVE'", "set r.v = 'ENFORCED'"))))
check("the dongle entities it reads all exist in the firmware (ids derived from the firmware's own names)", sorted(DONGLE_READS - FW_IDS) == [], str(sorted(DONGLE_READS - FW_IDS)))
check(f"it reads {len(M.READS)} entities and defines {len(OWN_EXPECT)} template entities, one helper and one automation", len(M.READS) == 27 and len(OWN_EXPECT) == 3)
check("the firmware facts the rule relies on, pinned: the charge source texts, the TOU flag (register 248 bit 0), the configuration time text and the telemetry flag",
      all(s in FW_TEXT for s in ('std::string("None")', 'std::string("Grid")', 'std::string("Generator")', 'std::string("Grid + Generator")',
                                 "id(ecco_time_of_use_enabled).publish_state((values[7] & 0x0001) != 0);", "id(ecco_tou2_soc).publish_state(values[28]);",
                                 "id(ecco_tou2_charge).publish_state(charge_source(values[34]));", 'name: "Last Configuration Update"'))
      and 'id(last_configuration_update).publish_state("Waiting")' in FW_TEXT.replace(" ", "").replace('publish_state("Waiting");', 'publish_state("Waiting")').replace("id(last_configuration_update)", 'id(last_configuration_update)'))
check("the configuration read the floor comes from is a 60 s interval of the firmware (two block reads a minute, skipped while an RTC correction or a manual write holds the bus), so 150 s is two and a half "
      "periods and 1800 s is thirty",
      re.search(r"- interval: 60s\s+startup_delay: 20s\s+then:\s+- if:\s+condition:\s+lambda: \|-\s+return id\(configuration_polling\)\.state && !id\(correction_in_progress\) && !id\(manual_write_in_progress\);\s+then:\s+- script\.execute:\s+id: poll_inverter_configuration",
                FW_TEXT) is not None and "only two block reads" in FW_TEXT)
class _TagTolerantLoader(UniqueKeyLoader):
    pass


_TagTolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)   # !secret and the like


def defined_ids(path_or_text) -> tuple:
    """(entity ids, unique_ids, automation ids) a package defines."""
    text = path_or_text.read_text(encoding="utf-8") if isinstance(path_or_text, Path) else path_or_text
    d = yaml.load(text, Loader=_TagTolerantLoader) or {}
    ents, uids = set(), set()
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in d.get(dom) or {}:
            ents.add(f"{dom}.{k}")
    for blk in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in blk.get(kind) or []:
                if isinstance(it, dict) and it.get("name"):
                    ents.add(f"{kind}.{slug(it['name'])}")
                    if it.get("unique_id"):
                        uids.add(it["unique_id"])
    autos = {a["id"] for a in d.get("automation") or [] if isinstance(a, dict) and a.get("id")}
    return ents, uids, autos


_mine = defined_ids(PKG_TEXT)
_clash = []
for _p in sorted(PKGS.glob("*.yaml")):
    if _p.name == Path(PKG_REL).name:
        continue
    try:
        _theirs = defined_ids(_p)
    except Exception as exc:  # noqa: BLE001
        _clash.append(f"{_p.name}: {exc}")
        continue
    for _a, _b, _what in zip(_mine, _theirs, ("entity", "unique_id", "automation id")):
        if _a & _b:
            _clash.append(f"{_p.name}: {_what} {sorted(_a & _b)[:2]}")
check(f"every id the package defines ({sum(len(x) for x in _mine)}: entities, unique_ids, automation ids) is defined in no other package of the repository ({len(list(PKGS.glob('*.yaml'))) - 1} others)",
      _clash == [] and sum(len(x) for x in _mine) >= 2, str(_clash[:3]))

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
slug_spots = [m.start() for m in re.finditer(DONGLE, PKG_TEXT)]
try:
    rendered, counts = render.render_text(PKG_REL, PKG_TEXT, site, render.firmware_actions(ROOT))
except render.RenderError as exc:
    rendered, counts = "", {"error": str(exc)[:120]}
check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them for another device slug and leaves none behind",
      counts == {"entity": len(slug_spots)} and len(slug_spots) >= 20 and DONGLE not in rendered and "sensor.site_dongle_ecco_timezone3_soc" in rendered
      and "binary_sensor.site_dongle_ecco_time_of_use_enabled" in rendered, str(counts))
man = yaml.safe_load(MANIFEST_TEXT)
stanza = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
check("the deployment manifest lists the package exactly once, to /config/packages, by ssh_file_copy, with restart_required false (three reloads install it; the pin-chain entry rrb1 pins the stanza)",
      stanza == [{"source": PKG_REL, "destination": "/config/packages/ecco_reserve_floor_status.yaml", "method": "ssh_file_copy", "restart_required": False}], str(stanza))
README = re.sub(r"\s+", " ", (PKGS / "README.md").read_text(encoding="utf-8"))
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if "ecco_reserve_floor_status.yaml" in ln), "")
check("the packages README has a Reserve floor read-back section (the entities, the floor rule, the five states, the binary sensor, no DRIFT, a register is not behaviour, the install reloads) and the CHANGELOG has one bullet that says "
      "read-only, offline, nothing installed and makes no claim of enforcement",
      all(s in README for s in ("## Reserve floor read-back", "sensor.ecco_reserve_floor_status", "binary_sensor.ecco_reserve_not_held_by_inverter", "input_boolean.ecco_tell_me_reserve_not_enforced",
                                "MATCH", "BELOW", "ABOVE", "PENDING", "UNREADABLE", "no DRIFT state", "A register is not behaviour", "proof R6", "Template entities, Input booleans and Automations"))
      and all(s in BULLET for s in ("read-only", "nothing installed", "no claim of enforcement", "BELOW", "restart_required: false", "proof R6")), BULLET[:80])
check("the package, the model and this suite are ASCII with LF line ends", b"\r" not in PKG_RAW and all(ord(c) < 128 for c in PKG_TEXT)
      and b"\r" not in (HERE / "_reserve_floor_status_sim.py").read_bytes() and b"\r" not in Path(__file__).read_bytes())

# ===========================================================================================================================
print("[1] model: control experiments on the model itself")
# ===========================================================================================================================
probe_text = """template:
  - sensor:
      - name: Probe A
        availability: "{{ is_state('sensor.in', 'on') }}"
        state: "{{ now().minute }}"
      - name: Probe B
        state: "{{ states('sensor.probe_a') }}"
        attributes:
          n: "{{ [1, 2] }}"
"""
pw_ = M.FloorWorld(probe_text)
pw_.put("sensor.in", "off")
check("the availability template is a super template: while it is false the entity reads unavailable, drops its attributes and nothing else is rendered",
      pw_.state("sensor.probe_a") == "unavailable" and pw_.attr("sensor.probe_a", "n") is None)
pw_.put("sensor.in", "on")
m0 = pw_.state("sensor.probe_a")
pw_.advance(61)
check("a template that calls now() is rendered again at the start of every minute by time alone; a consumer follows it; an attribute list arrives as a list",
      pw_.state("sensor.probe_a") != m0 and pw_.state("sensor.probe_b") == pw_.state("sensor.probe_a") and pw_.attr("sensor.probe_b", "n") == [1, 2])
pw_.reload()
check("a template reload makes the entities read unavailable once and then their value again", ("unavailable" in [h[2] for h in pw_.w.history if h[1] == "sensor.probe_a"][-3:]) and pw_.state("sensor.probe_a") != "unavailable")
fwx = world(PKG_TEXT)
fwx.restart(gone=())
check("a restart's restored window: the entities keep their states for a few milliseconds before the first render, and a new automation instance exists",
      fwx.state(M.STATUS) == "MATCH" and fwx.ha is not None and fwx.w.states[M.STATUS][0] == "MATCH")
pl_ = M.FloorWorld(probe_text + """      - name: Probe Long
        state: "{{ 'x' * 300 }}"
""")
check("a state longer than 255 characters is refused by the model as by Home Assistant (the state becomes unknown, an error is recorded)",
      pl_.state("sensor.probe_long") == "unknown" and any("300 characters" in e for e in pl_.errors))

# ===========================================================================================================================
print("[2] to [3] the table, the sweeps, the attributes, the reasons, the binary sensor, time")
# ===========================================================================================================================
for name, fn in BATTERY[1:8] + [BATTERY[9]]:
    probs = fn(PKG_TEXT)
    check({"table": "the state table: every verdict, the floor rule (shutdown, the lowest non-charging slot, TOU off, a charging slot never counted, 21 cases), the binary sensor",
           "attributes": "the attributes: the floor, the slot floor, the shutdown SOC, the reserve, the difference, mismatch, the slots, the TOU flag, the configuration read, the behaviour note and every input with its freshness",
           "pending": "PENDING one cause at a time (each flag, each recovery state), the precedence over an unreadable slot and under an unreadable flag, and the configuration freshness at its limits (149 to 151 s, 1799 to 1801 s, offline, a future text)",
           "unreadable": "every input missing, unavailable, unknown, empty, non-numeric, infinite, nan, fractional, negative or above 100, one at a time, is UNREADABLE and the binary sensor is on (never MATCH, never a guess)",
           "binary": "the binary sensor is an allow-list on the status sensor (on only for BELOW and UNREADABLE) and the status sensor is unavailable while the record cannot be read",
           "reasons": "every reason names its cause in words, is never cut short, and the record stays below 255 characters in the worst case",
           "notify": "the notification: off without the opt-in, nothing before 10 minutes, one after, none again while it stands, dismissed at MATCH, restarted by a flap, raised by UNREADABLE, by the opt-in turned on late, never by ABOVE or PENDING",
           "time": "a configuration read that stops goes stale by the passing of time alone: MATCH, PENDING after 150 s, UNREADABLE after 1800 s"}[name],
          probs == [], str(probs[:2]))
check("the restart and reload rules: a reload reads unavailable once and creates nothing; the restored window shows the old state for milliseconds and creates nothing; a restart with the dongle gone reads UNREADABLE or "
      "unavailable and raises nothing; the dongle's return reads MATCH; a persistent BELOW after a restart raises the notice only after the debounce", sc_reload_restart(PKG_TEXT) == [], str(sc_reload_restart(PKG_TEXT)[:2]))

# ===========================================================================================================================
print("[4] differential: the package against an independent model of the rules")
# ===========================================================================================================================
diff = sc_differential(PKG_TEXT)
check("the verdict and the floor equal the independent model's over 400 seeded random worlds (every input valid or, one time in 25, junk; ages from -200 s to 4000 s)", diff == [], str(diff[:2]))
check("the model itself is sane: it reads today's house as BELOW, and an unreadable reserve as UNREADABLE",
      oracle({**{e: "off" for e in M.FLAGS}, M.REC_FP: "NONE", M.REC_DG: "NONE", M.PLAN: "5", M.SHUT: "0", M.TOU: "on", M.ONLINE: "on", M.CFGTIME: "2026-11-27 12:00:00",
              **{e: "0" for e in M.SOC}, **{e: "None" for e in M.SRC}}, datetime.strptime("2026-11-27 12:00:10", M.FMT).replace(tzinfo=M.ZoneInfo("Europe/London")).timestamp(), M.ZoneInfo("Europe/London")) == ("BELOW", 0))

# ===========================================================================================================================
print("[6] no writes")
# ===========================================================================================================================
check("over a whole session (a notification, its dismissal, a reload) the model saw nothing but persistent_notification create and dismiss, and no state outside the package's own entities and helper",
      sc_writes(PKG_TEXT) == [])

# ===========================================================================================================================
print("[7] mutation: in-memory mutants of the package, each caught")
# ===========================================================================================================================
MUTANTS = [
    ("macro: the lower bound of a percent becomes exclusive", "v >= 0 and v <= 100 and v == (v | round(0))", "v > 0 and v <= 100 and v == (v | round(0))"),
    ("macro: the upper bound of a percent becomes exclusive", "v >= 0 and v <= 100 and v == (v | round(0))", "v >= 0 and v < 100 and v == (v | round(0))"),
    ("macro: the upper bound is widened", "v >= 0 and v <= 100 and v == (v | round(0))", "v >= 0 and v <= 101 and v == (v | round(0))"),
    ("macro: the whole-percent rule is dropped", "v >= 0 and v <= 100 and v == (v | round(0))", "v >= 0 and v <= 100"),
    ("freshness: the lost bound moves up", "'lost' if cage > 1800", "'lost' if cage > 1801"),
    ("freshness: the lost bound is inclusive", "'lost' if cage > 1800", "'lost' if cage >= 1800"),
    ("freshness: the stale bound moves up", "cage > 150) else 'fresh'", "cage > 151) else 'fresh'"),
    ("freshness: the stale bound is inclusive", "cage > 150) else 'fresh'", "cage >= 150) else 'fresh'"),
    ("freshness: the dongle's offline flag no longer makes the read stale", "(online == 'off' or cage > 150)", "(cage > 150)"),
    ("freshness: the age ignores its sign", "| abs | round(0) | int) if cts is not none", "| round(0) | int) if cts is not none"),
    ("freshness: an unreadable online flag is accepted", "online not in ok or cage is none", "online not in ['on', 'off', 'unknown'] or cage is none"),
    ("freshness: a lost read is only PENDING", "elif cfg in ['unreadable', 'lost']", "elif cfg in ['unreadable']"),
    ("freshness: a stale read is no longer PENDING", "{%- elif cfg == 'stale' -%}", "{%- elif cfg == 'never' -%}"),
    ("pending: the Free Power snapshot flag is not read", "'binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', ", "", 0),
    ("pending: the Dump operation flag is not read", "'binary_sensor.ecco_clock_dongle_dump_to_grid_operation_in_progress', ", "", 0),
    ("pending: the manual write flag is not read", "'binary_sensor.ecco_clock_dongle_manual_write_in_progress', ", "", 0),
    ("pending: the editor's in-flight latch is not read", ", 'input_boolean.ecco_cfg_edit_in_flight'] -%}", "] -%}"),
    ("pending: an open Free Power recovery state is ignored", "{%- set rfp_open = rfp != 'NONE' -%}", "{%- set rfp_open = false -%}"),
    ("pending: an accepted Dump recovery state is not clear", "rdg.startswith('NONE') or rdg.startswith('ACCEPTED')", "rdg.startswith('NONE')"),
    ("pending: any Dump recovery text is clear", "not (rdg.startswith('NONE') or rdg.startswith('ACCEPTED'))", "false"),
    ("pending: a lease no longer beats an unreadable slot", "{%- elif c.busy != '' or rfp_open or rdg_open -%}", "{%- elif false -%}"),
    ("floor: the highest non-charging target is used", "{%- set s.lo = [s.lo, soc] | min -%}", "{%- set s.lo = [s.lo, soc] | max -%}"),
    ("floor: a charging source None test is inverted", "{%- elif src == 'None' -%}", "{%- elif src != 'Grid' -%}"),
    ("floor: the shutdown SOC is ignored", "([shut, slotfloor] | max)", "slotfloor"),
    ("floor: the smaller of shutdown and slot is used", "([shut, slotfloor] | max)", "([shut, slotfloor] | min)"),
    ("floor: the TOU flag is ignored for the slot floor", "s.lo if (tou == 'on' and (s.nc | length) > 0) else -1", "s.lo if ((s.nc | length) > 0) else -1"),
    ("floor: no slot to read from is no longer UNREADABLE", "{%- elif tou == 'on' and (s.nc | length) == 0 -%}", "{%- elif false -%}"),
    ("verdict: ABOVE reads MATCH", "{%- elif floor == res -%}", "{%- elif floor >= res -%}"),
    ("verdict: MATCH needs a floor one above the reserve", "{%- elif floor == res -%}", "{%- elif floor == res + 1 -%}"),
    ("verdict: an unreadable reserve is accepted", "{%- if res < 0 -%}", "{%- if res < -5 -%}"),
    ("verdict: an unreadable shutdown SOC is accepted", "{%- elif shut < 0 -%}", "{%- elif shut < -5 -%}"),
    ("verdict: an unreadable TOU flag is accepted", "{%- elif tou not in ok -%}", "{%- elif false -%}"),
    ("verdict: an unreadable flag is accepted", "states(e) not in ok -%}{%- set c.bad", "states(e) not in ['on', 'off', 'unknown'] -%}{%- set c.bad"),
    ("verdict: an unreadable recovery state is accepted", "{%- elif rfp in bad or rdg in bad -%}", "{%- elif false -%}"),
    ("source: any text is a charge source", "src not in ['None', 'Grid', 'Generator', 'Grid + Generator']", "src in ['unavailable']"),
    ("source: Generator is no charging source", "['None', 'Grid', 'Generator', 'Grid + Generator']", "['None', 'Grid', 'Grid + Generator']"),
    ("binary: PENDING warns", "in ['BELOW', 'UNREADABLE'] }}\n        attributes:", "in ['BELOW', 'UNREADABLE', 'PENDING'] }}\n        attributes:"),
    ("binary: only BELOW warns", "in ['BELOW', 'UNREADABLE'] }}\n        attributes:", "in ['BELOW'] }}\n        attributes:"),
    ("binary: ABOVE warns", "in ['BELOW', 'UNREADABLE'] }}\n        attributes:", "in ['BELOW', 'ABOVE', 'UNREADABLE'] }}\n        attributes:"),
    ("binary: availability accepts any status", "{{ states('sensor.ecco_reserve_floor_status') in ['MATCH', 'BELOW', 'ABOVE', 'PENDING', 'UNREADABLE'] }}\n        state:",
     "{{ true }}\n        state:"),
    ("status: the record needs fewer fields", "(p | length) == 10 and p[0]", "(p | length) >= 5 and p[0]"),
    ("status: the state reads the floor field", "split('|')[0] }}\n        attributes:", "split('|')[1] }}\n        attributes:"),
    ("status: mismatch is true for ABOVE only", "true if v in ['BELOW', 'ABOVE'] else", "true if v in ['ABOVE'] else"),
    ("status: the difference changes sign", "((p[1] | int) - (p[4] | int))", "((p[4] | int) - (p[1] | int))"),
    ("status: the reason field is the wrong one", "split('|')[9] }}\n          floor_percent", "split('|')[8] }}\n          floor_percent"),
    ("status: the floor is shown while PENDING", "{%- set shown = r.v in ['MATCH', 'BELOW', 'ABOVE'] -%}", "{%- set shown = true -%}"),
    ("status: the reasons are cut at 20 characters", "[:140]", "[:20]"),
    ("status: the behaviour note says the floor is proven", "NOT PROVEN: a register is not behaviour", "A register is behaviour"),
    ("notify: the debounce is one minute", "> 600) }}", "> 60) }}"),
    ("notify: the debounce is an hour", "> 600) }}", "> 3600) }}"),
    ("notify: the opt-in is not required", "{{ is_state('input_boolean.ecco_tell_me_reserve_not_enforced', 'on')\n             and is_state('binary_sensor", "{{ is_state('binary_sensor"),
    ("notify: the binary sensor is not required", "and is_state('binary_sensor.ecco_reserve_not_held_by_inverter', 'on')\n             and ((as_timestamp", "and ((as_timestamp"),
    ("notify: the notification is never dismissed at off", "        to: \"off\"\n        id: clear\n      - trigger: state\n        entity_id: input_boolean", "        to: \"on\"\n        id: clear\n      - trigger: state\n        entity_id: input_boolean"),
    ("notify: turning the opt-in off dismisses nothing", "entity_id: input_boolean.ecco_tell_me_reserve_not_enforced\n        to: \"off\"", "entity_id: input_boolean.ecco_tell_me_reserve_not_enforced\n        to: \"on\""),
    ("notify: the notification id changes on dismiss", "      notification_id: ecco_reserve_floor_not_held\n", "      notification_id: ecco_reserve_floor_not_held_x\n", 1),
    ("notify: the notification id changes on create", "                  notification_id: ecco_reserve_floor_not_held\n", "                  notification_id: ecco_reserve_floor_not_held_x\n"),
    ("vocabulary: a button press is added", "          - action: persistent_notification.dismiss\n            data:", "          - action: button.press\n            data:"),
    ("hygiene: an address appears in a comment", "# NOT INSTALLED, NOT LIVE-PROVEN.", "# 198.51.100.7 NOT INSTALLED, NOT LIVE-PROVEN."),
    ("wording: the header drops the unproven-behaviour rule", "A REGISTER IS NOT BEHAVIOUR.", "A REGISTER IS BEHAVIOUR."),
    ("reads: a forecast entity is read", "{%- set rfp = states('sensor.ecco_clock_dongle_free_power_recovery_state') -%}", "{%- set rfp = states('sensor.ecco_clock_dongle_free_power_recovery_state') -%}{%- set zz = states('sensor.solc" "ast_forecast') -%}"),
]
total = len(MUTANTS)
killed = survived = 0
survivors: list = []
prefer: dict = {}
for entry in MUTANTS:
    label, old, new = entry[:3]
    nth = entry[3] if len(entry) > 3 else None
    if (nth is None and PKG_TEXT.count(old) != 1) or (nth is not None and PKG_TEXT.count(old) <= nth):
        check(f"mutant anchor is unique: {label}", False, f"{PKG_TEXT.count(old)}x")
        continue
    if nth is None:
        mutated = PKG_TEXT.replace(old, new, 1)
    else:
        parts = PKG_TEXT.split(old)
        mutated = old.join(parts[:nth + 1]) + new + old.join(parts[nth + 1:])
    family = label.split(":", 1)[0]
    info: dict = {}
    found = battery(mutated, kill=True, prefer=prefer.get(family), info=info)
    if found:
        killed += 1
        prefer[family] = info.get("section")
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        survived += 1
        survivors.append(label)
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{total} mutants (every bound on both sides, every unreadable branch, every pending cause, the floor rule, the verdict ladder, the binary sensor's allow-list, the record, the debounce, "
      "the opt-in, the vocabulary and the words): all caught", killed == total and total >= 25, f"{killed}/{total} {survivors[:3]}")
_harmless = PKG_TEXT.replace("# WHY. ECCO's battery reserve is a plan value", "# WHY, restated. ECCO's battery reserve is a plan value")
check("a harmless rewrite (a comment) survives the battery, and a rewrite of a rule does not", _harmless != PKG_TEXT and battery(_harmless, kill=True) == []
      and battery(PKG_TEXT.replace("cage > 150) else 'fresh'", "cage > 15000) else 'fresh'"), kill=True) != [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll reserve floor read-back checks passed.")
print("These prove the package against a model of Home Assistant's template entities; nothing was installed, nothing was written live, and a register is not behaviour: nothing here claims enforcement.")
