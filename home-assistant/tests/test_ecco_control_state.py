"""Offline suite for the CONTROL STATE read model (slice S-A1 of the shared control integration):

  home-assistant/packages/ecco_control_state.yaml     three template sensors and nothing else: sensor.ecco_charge_control_state and sensor.ecco_export_control_state (a lifecycle state, why, the next action,
                                                      what blocks a start, what the lease holds) and sensor.ecco_control_owner (who holds the inverter settings)

A DISPLAY, NEVER A GATE: no automation, script, helper, trigger, action or service call, and no package may read it. This suite proves the REAL package YAML against a model of Home Assistant's template
entities (home-assistant/tests/_control_state_sim.py, on the template model of the time trust suite and the FPS1 interpreter, which it reuses unchanged) and against an INDEPENDENT reference of the rules
written from the specification. Nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.

  [0] static      the file loads with no repeated key; only `template:`; the three entities and nothing else; the write vocabulary (no service, action, trigger, helper, script or automation); the exact set of
                  entities it reads (every one existing in the repository) and the exact (entity, attribute) pairs; no `this`, no now(), no state object, no forecast, advice or measurement; only the leases
                  consumer of the time trust package and only the two gates are named; the rule block of each sensor is the same text in every template that carries it; every closed sentence is in the
                  file and has no digit; the gate codes, the status vocabulary and the header; ASCII, LF, no site value; the site renderer; no other package mentions the three entities
  [1] inputs      every input the state needs, one at a time (missing, unavailable, unknown, junk): UNKNOWN, never ready, the cause named; every optional input: never UNKNOWN
  [2] table       every combination of the three flags of both functions, the manual write flag and a status text of each family, against the reference; the arm, the scripts and the armed helper; the gate
                  and the time trust reading in every combination; the proposal and the re-target in every state (absent, unavailable, unknown, a state it does not know)
  [3] properties  seeded random inputs, thousands of cases: the template equals the reference on every one and the properties hold on the template's own answer (start_allowed only with an open gate and
                  a trusted time, never while anything is unreadable, never in a state that is not IDLE, PLANNED or ASSISTED; both functions never RUNNING together; every sentence closed, no digit in one)
  [4] lifecycle   a template reload, a Home Assistant restart and the first state with no input at all, as the lab measured them; the time zone changes nothing
  [5] rows        the same inputs rendered twice, a clock that moves for half an hour, the gates' reasons and the dongle's status text moving with every poll: the same state and attributes and no new row
  [6] vocabulary  every status text the firmware can publish for the two functions lands in exactly one family; the gate's codes are exactly the sentences'
  [7] real gate   the REAL start gate and the REAL plan helper package feeding the read model: time off, stale data, a hold, a running lease, a restore owed
  [8] vocabulary  no service call was ever made by any world above; no forecast, advice or measurement entity changes anything
  [9] mutation    in-memory mutants of the package (every rule, every closed list, every input, the things it must never contain), each caught
  [10] documents  the manifest, the README and the CHANGELOG say the same

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

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
import _control_state_sim as X  # noqa: E402

PKGS = ROOT / "home-assistant" / "packages"
PKG_REL = X.PKG_REL
TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
RAW = (ROOT / PKG_REL).read_bytes()
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
GATE_TEXT = (PKGS / "ecco_start_gate.yaml").read_text(encoding="utf-8")
PLAN_TEXT = (PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
README_TEXT = (PKGS / "README.md").read_text(encoding="utf-8")
CHANGELOG_TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

FAILURES: list[str] = []
SERVICE_LOG: list = []        # every service call any world below made (the model cannot make one; a suite requires it empty)


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


# ===========================================================================================================================
# names
# ===========================================================================================================================
OWN_IDS = set(X.OWN)
EXPECTED_READS = {X.TL, X.CG, X.EG, X.FA, X.FO, X.FS, X.DA, X.DO, X.DS, X.MW, X.FT, X.DT, X.FE, X.DE, X.FW, X.DW, X.FSS, X.FSG, X.DSS, X.DSG, X.FARM, X.DARM, X.FSTAT, X.DSTAT, X.FREQP, X.FREQD,
                  X.DREQP, X.DREQD, X.DREQS, X.CEIL, X.HOLD, X.RES, X.LATCHED, X.LIM, X.CAS, X.PROP, X.P_FLOOR, X.P_NET, X.RETG}
# the exact (entity, attribute) pairs read through state_attr: nothing else (a pin by entity id alone would let a measurement in through an attribute of an entity that is allowed)
EXPECTED_STATE_ATTRS = {(X.CG, "blocked_by"), (X.EG, "blocked_by"), (X.PROP, "actionable"), (X.PROP, "blocked_by"), (X.RETG, "reasons"), (X.RETG, "changes"), (X.HOLD, "held_by")}
STATE_ATTR_RE = re.compile(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_text|input_number|input_boolean|input_datetime|number|script|button|switch|select|automation|light|climate)\.[a-z0-9_]+")
FORBIDDEN_FORECAST = re.compile(r"forecast|solcast|predict|pv_tomorrow|estimate|intel_|house_power|battery_soc|pv_power|grid_power|battery_power|energy_above", re.I)
TIME_ID = "binary_sensor.ecco_time_trusted_for_leases"
GATE_IDS = (X.CG, X.EG)
MARKER = "{#- RULES END -#}"
EXPECTED_ATTRS = {
    X.CHARGE: ["why", "next_action", "blocked_by", "start_allowed", "start_path", "end_path", "lease", "notes"],
    X.EXPORT: ["why", "next_action", "blocked_by", "start_allowed", "start_path", "end_path", "lease", "notes", "proposal", "retarget", "facts"],
    X.OWNER: ["live_match", "note"],
}
# how many templates of each sensor carry the shared rule block (the rest are tails that read nothing of it)
CORE_COUNT = {X.CHARGE: 5, X.EXPORT: 6, X.OWNER: 2}
HEADER_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "DISPLAY ONLY", "DISPLAY, NEVER A GATE", "THE READ MODEL WRITES NOTHING", "no automation, no script, no helper, no trigger, no action, no service call",
               "NO PACKAGE MAY READ IT", "THE GATES ARE SOFT", "Start buttons", "THE STATES (first match wins", "UNKNOWN, FAULT, ENDING, RUNNING, ARMED, ASSISTED, PLANNED, IDLE", "start_allowed is true ONLY when",
               "never true while", "from a closed list", "a measured number never appears in a sentence", "WHAT IT COMBINES", "the leases consumer ONLY", "gates' number-bearing reasons are NOT copied",
               "Their live figures", "are NOT copied", "Not read, on purpose", "any forecast or advice entity", "THE INPUTS THAT MAKE IT UNKNOWN", "UNREADABLE_<INPUT>", "GATE_INCONSISTENT",
               "THE STATUS TEXTS", "classified by prefix into families", "THE ONE-LEASE RULE", "both read FAULT", "NO LIVE NUMBERS, NO MOVING TIME", "never call now()", "write no recorder row",
               "RESTART, RELOAD AND FIRST STATE", "13 to 27 s", "RESTORED state for tens of", "wait 60 s after a start", "Core process time zone", "`this` is not used", "THE NOTES", "SOFT_GATE",
               "CARD_START_NOT_GATED", "GUARDED_START_NOT_GATED", "SCHEDULE_NOT_GATED", "NO_END_GUARD", "PROPOSAL_NOT_INSTALLED", "LIMITS, stated plainly", "display, never proof", "persisted owner",
               "Recalled from Home Assistant core", "NOT verified on a real Home Assistant", "INSTALL", "needs the owner's go", "template.reload", "no restart", "Install ONLY with NO Dump to Grid or Free Power lease running",
               "OUTSIDE any armed scheduled Export or charge run", "window end plus 10 minutes", "re-creates EVERY template entity", "It changes no existing entity")


# ===========================================================================================================================
# the worlds and the comparison with the reference
# ===========================================================================================================================
def full_of(raw: dict) -> dict:
    """Every entity the package reads, set to the raw reading or removed (an entity not in `raw` does not exist)."""
    full = {e: None for e in EXPECTED_READS}
    full.update(raw)
    return full


def new_world(text: str | None = None, **kw) -> "X.CtlWorld":
    return X.CtlWorld(text, healthy=False, **kw)


def apply_raw(w: "X.CtlWorld", raw: dict) -> None:
    w.bulk(full_of(raw))
    SERVICE_LOG.extend(w.w.service_log)


def compare(w: "X.CtlWorld", raw: dict) -> list[str]:
    """Everything the three sensors publish against the reference; the list of differences."""
    bad: list[str] = []
    ref = X.reference(raw)
    snap = w.snapshot()
    for eid in X.OWN:
        gs, ga = snap[eid]
        rs, ra = ref[eid]
        if gs != rs:
            bad.append(f"{eid} state {gs} != {rs}")
        for k in sorted(set(ga) | set(ra)):
            if ga.get(k) != ra.get(k):
                bad.append(f"{eid} {k} {ga.get(k)!r} != {ra.get(k)!r}")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


def run_row(label: str, raw: dict, w: "X.CtlWorld | None" = None, text: str | None = None) -> list[str]:
    w = w or new_world(text)
    apply_raw(w, raw)
    return [f"{label}: {b}" for b in compare(w, raw)]


READY_SENTENCES = set(X.READY_SENTENCES.values())
NOT_READY_RE = re.compile(r"^Not ready: ")


def all_sentences() -> set:
    out = set(X.GATE_SENTENCES.values()) | set(X.READY_SENTENCES.values()) | set(X.OTHER_SENTENCES.values()) | set(X.RUNNING_SENTENCES.values()) | set(X.NEXT_SENTENCES.values())
    out |= set(X.OWNER_NOTES.values())
    for fn in ("charge", "export"):
        for lab in X.UNREADABLE_LABELS.values():
            out.add(lab.format(lease=X.FUNCS[fn]["lease"], other_lease=X.FUNCS[fn]["other_lease"]) + " cannot be read, so nothing is shown as ready.")
    out.add(X.END_NOW_MESSAGE)
    return out


SENTENCES = all_sentences()
GENERIC_NOT_READY = re.compile(r"^Not ready: the start gate is closed \([^()]{0,40}\)\.$")


def why_is_closed(s: str) -> bool:
    if s in SENTENCES or GENERIC_NOT_READY.match(s):
        return True
    return s.startswith("Not ready: ") and s[len("Not ready: "):] in SENTENCES


def property_problems(snap: dict, label: str = "") -> list[str]:
    """What must hold of the template's OWN answer, whatever the inputs: the properties of the design."""
    bad: list[str] = []
    for eid in (X.CHARGE, X.EXPORT):
        st, a = snap[eid]
        if st not in X.STATES:
            bad.append(f"{label}{eid}: state {st!r} is not in the closed list")
            continue
        if not isinstance(a.get("start_allowed"), bool):
            bad.append(f"{label}{eid}: start_allowed is not a boolean")
            continue
        why, nxt, blocked = a.get("why", ""), a.get("next_action", ""), a.get("blocked_by")
        if not isinstance(why, str) or not why_is_closed(why):
            bad.append(f"{label}{eid}: why is not a closed sentence: {str(why)[:80]!r}")
        if not isinstance(nxt, str) or nxt not in X.NEXT_SENTENCES.values():
            bad.append(f"{label}{eid}: next_action is not a closed sentence: {str(nxt)[:80]!r}")
        if re.search(r"\d", str(why)) or re.search(r"\d", str(nxt)):
            bad.append(f"{label}{eid}: a digit in a sentence (a measured number must never appear in one)")
        if a["start_allowed"]:
            if st not in ("IDLE", "PLANNED", "ASSISTED") or blocked != [] or why not in READY_SENTENCES:
                bad.append(f"{label}{eid}: start_allowed with state {st}, blocked_by {blocked}, why {str(why)[:50]!r}")
        if st == "UNKNOWN":
            if a["start_allowed"] or not any(str(c).startswith("UNREADABLE_") for c in (blocked or [])) or "cannot be read" not in why:
                bad.append(f"{label}{eid}: UNKNOWN must never be ready and must name what cannot be read: {blocked} {why[:60]!r}")
        if st in ("IDLE", "PLANNED", "ASSISTED") and not a["start_allowed"]:
            if not NOT_READY_RE.match(why) or not blocked:
                bad.append(f"{label}{eid}: {st} that is not startable must say so in plain words and name why: {why[:60]!r} {blocked}")
        if st in ("FAULT", "ENDING", "RUNNING", "ARMED") and a["start_allowed"]:
            bad.append(f"{label}{eid}: start_allowed in {st}")
        if a.get("start_path") != "GUARDED_SCRIPT" or a.get("end_path") != "END_BUTTON":
            bad.append(f"{label}{eid}: start_path / end_path changed")
    if snap[X.CHARGE][0] == "RUNNING" and snap[X.EXPORT][0] == "RUNNING":
        bad.append(f"{label}both functions read RUNNING (the one-lease rule)")
    if snap[X.OWNER][0] not in X.OWNERS:
        bad.append(f"{label}owner {snap[X.OWNER][0]!r} is not in the closed list")
    if snap[X.EXPORT][1].get("proposal", {}).get("actionable") and snap[X.EXPORT][0] != "ASSISTED":
        bad.append(f"{label}the proposal says actionable while the state is {snap[X.EXPORT][0]}")
    return bad


# ===========================================================================================================================
# [1] inputs one at a time, [2] the table
# ===========================================================================================================================
REQUIRED = {
    "charge": [(X.CG, "GATE"), (X.TL, "TIME"), (X.FA, "ACTIVE"), (X.FO, "OPERATION"), (X.FS, "SNAPSHOT"), (X.DA, "OTHER_ACTIVE"), (X.DO, "OTHER_OPERATION"), (X.DS, "OTHER_SNAPSHOT"),
               (X.MW, "MANUAL_WRITE"), (X.FT, "STATUS"), (X.FW, "WRITE_ENABLE"), (X.FSS, "START_SCRIPT"), (X.FSG, "GUARDED_SCRIPT"), (X.FARM, "SCHEDULE_ARMED")],
    "export": [(X.EG, "GATE"), (X.TL, "TIME"), (X.DA, "ACTIVE"), (X.DO, "OPERATION"), (X.DS, "SNAPSHOT"), (X.FA, "OTHER_ACTIVE"), (X.FO, "OTHER_OPERATION"), (X.FS, "OTHER_SNAPSHOT"),
               (X.MW, "MANUAL_WRITE"), (X.DT, "STATUS"), (X.DW, "WRITE_ENABLE"), (X.DSS, "START_SCRIPT"), (X.DSG, "GUARDED_SCRIPT"), (X.DARM, "SCHEDULE_ARMED")],
}
# the reserved tokens of the fallback and failback records, spelled as adjacent literals so that this file carries none whole (the pin chain's BANNED scan reads every home-assistant/ file)
RESERVED_TOKENS = re.compile(r"ecco_" "fallback|FALLBACK_" "PROFILE|FAILBACK_" "STATE|ecco_" "failback")
BAD_FLAG = (None, "unavailable", "unknown", "", "x", "ON", "true", "1")
BAD_TEXT = (None, "unavailable", "unknown", "", "a text nobody knows", "ACTIVE")
OPTIONAL = [X.CEIL, X.FE, X.DE, X.FREQP, X.FREQD, X.DREQP, X.DREQD, X.DREQS, X.HOLD, X.RES, X.LATCHED, X.LIM, X.CAS, X.FSTAT, X.DSTAT, X.PROP, X.P_FLOOR, X.P_NET, X.RETG]
BAD_OPTIONAL = (None, "unavailable", "unknown", "x", "nan", "-1", "1e999")


def inputs_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    bad: list[str] = []
    w = new_world(text)
    for fn, pairs in REQUIRED.items():
        sensor = X.FUNCS[fn]["sensor"]
        for eid, code in pairs:
            is_text = eid in (X.FT, X.DT)
            for v in (BAD_TEXT if is_text else BAD_FLAG):
                if eid in (X.CG, X.EG) and v == "ON":
                    continue
                raw = X.merged({eid: v}, proposal=True)
                if eid in (X.CG, X.EG) and isinstance(v, str):
                    raw[eid] = (v, {"blocked_by": []})            # a gate that reads a bad state with a list; the list itself is tested in the table
                bad += run_row(f"{fn} {eid} {v!r}", raw, w)
                snap = w.snapshot()
                st, a = snap[sensor]
                if st != "UNKNOWN" or a["start_allowed"] or f"UNREADABLE_{code}" not in a["blocked_by"]:
                    bad.append(f"{fn} {eid} {v!r}: the state is {st}, start_allowed {a['start_allowed']}, blocked_by {a['blocked_by']}: an input the state needs is unreadable")
                bad += property_problems(snap, f"{fn} {eid} {v!r}: ")
                if first_only and bad:
                    return bad
    # a gate whose blocked_by list cannot be read (missing, a text, none): unreadable, never open
    for label, attrs in (("no list", {}), ("a text", {"blocked_by": "TIME_LEASES"}), ("none", {"blocked_by": None}), ("a number", {"blocked_by": 3})):
        for g, fn in ((X.CG, "charge"), (X.EG, "export")):
            raw = X.merged({g: ("on", attrs)}, proposal=True)
            bad += run_row(f"{fn} gate with {label}", raw, w)
            st, a = w.snapshot()[X.FUNCS[fn]["sensor"]]
            if st != "UNKNOWN" or a["start_allowed"] or "UNREADABLE_GATE" not in a["blocked_by"]:
                bad.append(f"{fn} gate on with {label}: {st} {a['start_allowed']} {a['blocked_by']}")
    # every optional input: never UNKNOWN
    for eid in OPTIONAL:
        for v in BAD_OPTIONAL:
            raw = X.merged({eid: v}, proposal=True)
            bad += run_row(f"optional {eid} {v!r}", raw, w)
            snap = w.snapshot()
            for s in (X.CHARGE, X.EXPORT):
                if snap[s][0] == "UNKNOWN":
                    bad.append(f"optional {eid} {v!r}: {s} reads UNKNOWN, it must not")
            bad += property_problems(snap, f"optional {eid} {v!r}: ")
            if first_only and bad:
                return bad
    return bad


STATUS_BY_FAMILY = {
    "ACTIVE": (X.FP_ACTIVE_TEXT, X.DG_ACTIVE_TEXT),
    "FAULT": ("OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying", "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot)"),
    "ENDING": ("END REQUESTED - restoring as soon as inverter write path is clear", "RESTORING - writing back original inverter settings"),
    "STARTING": ("STARTING - taking fresh inverter snapshot", "Snapshot durably committed - writing export power ceiling"),
    "DONE": (X.DONE_TEXT, "Inactive"),
    "OTHER": ("a text nobody knows", "ACTIVE"),
}


def table_rows(step: int = 1) -> list[tuple]:
    """Every combination of the three flags of both functions and the manual write flag, with a status text of each family on both: 2^7 x 6 rows (decimated by `step`)."""
    rows = []
    n = 0
    for bits in range(128):
        la, lo, ls, ya, yo, ys, mw = (("on" if bits >> i & 1 else "off") for i in range(7))
        for fam, (ftxt, dtxt) in STATUS_BY_FAMILY.items():
            n += 1
            if n % step:
                continue
            rows.append((f"flags {bits:07b} {fam}", X.merged({X.FA: la, X.FO: lo, X.FS: ls, X.DA: ya, X.DO: yo, X.DS: ys, X.MW: mw, X.FT: ftxt, X.DT: dtxt}, proposal=True)))
    return rows


def combo_rows() -> list[tuple]:
    """The arm, the scripts, the armed helper, the gates, the time trust reading, the proposal and the re-target in their combinations."""
    rows = []
    H = X.merged
    for bits in range(32):
        v = {e: ("on" if bits >> i & 1 else "off") for i, e in enumerate((X.FW, X.FSS, X.FSG, X.FARM, X.DW))}
        v.update({e: ("on" if bits >> i & 1 else "off") for i, e in ((0, X.DSS), (1, X.DSG), (2, X.DARM))})
        rows.append((f"arm/scripts/armed {bits:05b}", H(v, proposal=True)))
    gate_states = (("on", []), ("on", ["TIME_LEASES"]), ("off", []), ("off", ["TIME_LEASES", "TIME_SCHEDULES"]), ("off", ["DUMP_ACTIVE"]), ("off", ["SOME_NEW_CODE"]), ("off", ["x" * 60]),
                   ("off", ["IMPORT_HEADROOM", "OVERRIDE_ACTIVE"]), ("on", [3]), ("off", [None, "MANUAL_WRITE"]))
    for code in sorted(X.GATE_SENTENCES):                      # every code the gate can name, alone, on both gates: its sentence is the one the model says
        rows.append((f"gate code {code}", H({X.CG: ("off", {"blocked_by": [code]}), X.EG: ("off", {"blocked_by": [code]})}, proposal=True)))
    for tl in ("on", "off", "unavailable"):
        for cs, cl in gate_states:
            for es, el in gate_states[::2]:
                rows.append((f"gates {cs}{cl} {es}{el} tl {tl}", H({X.TL: tl, X.CG: (cs, {"blocked_by": cl}), X.EG: (es, {"blocked_by": el})}, proposal=True)))
    for ps in ("VALID", "INVALID", "UNVERIFIED", "HOLD", "NOT ALLOWED", "weird", "unknown", "unavailable", None):
        for act in (True, False, None, "True", 1):
            for gate_ok in (True, False):
                over = {X.PROP: None if ps is None else (ps, {"actionable": act, "blocked_by": ["SOC_UNREADABLE"]}), X.P_FLOOR: "40", X.P_NET: "3000"}
                if not gate_ok:
                    over[X.TL] = "off"
                rows.append((f"proposal {ps} actionable {act!r} gate_ok {gate_ok}", H(over)))
    for rs in ("NOT RUNNING", "UNKNOWN", "NO CHANGE", "WAIT", "ALLOWED", "END NOW", "weird", "unknown", "unavailable", None):
        for reasons, changes in (([], []), (["LEASE_TOO_YOUNG: the lease is 12 minutes old", "TIME_NOT_TRUSTED: x"], ["STOP_SOC 40.0 -> 42 (a raise)", "END 16:00 -> 17:00 (x)"]),
                                 (["not a code: x", 3, None, ("x" * 60) + ": y"], ["WEIRD 1", "EXPORT_TARGET 3000 -> 2800 W", 7]), ("text", "text"), (None, None)):
            attrs = {}
            if reasons is not None:
                attrs["reasons"] = reasons
            if changes is not None:
                attrs["changes"] = changes
            rows.append((f"retarget {rs} {reasons!r}", H({X.RETG: None if rs is None else (rs, attrs)}, proposal=True)))
    for hold, hb in (("clear", ""), ("held", "hold_battery"), ("held", "hold_battery,skip_tonight,prepare_power_cut,x"), ("unknown", None), ("unavailable", None), (None, None), ("held", None), ("held", 5)):
        rows.append((f"hold {hold} {hb!r}", H({X.HOLD: None if hold is None else (hold, {"held_by": hb})})))
    for latched, res, lease_on in (("40", "40", True), ("40", "41", True), ("40", "39.2", True), ("unknown", "40", True), ("40", "unknown", True), ("101", "40", True), ("40", "40", False), ("30", "40", False)):
        over = {X.LATCHED: latched, X.RES: res}
        if lease_on:
            over.update({X.DA: "on", X.DS: "on", X.DT: X.DG_ACTIVE_TEXT})
        rows.append((f"latched {latched} reserve {res} lease {lease_on}", H(over, proposal=True)))
    for lim in ("VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION", "UNKNOWN", "UNAVAILABLE", "weird", "unavailable", None):
        for cas in ("ABOVE PROVEN LEVEL", "AT PROVEN LEVEL", "BELOW PROVEN LEVEL", "UNAVAILABLE", "weird", None):
            rows.append((f"limits {lim} ceiling {cas}", H({X.LIM: lim, X.CAS: cas})))
    for ends in ("Inactive", "2026-11-27 18:00:00", "Active - end time unavailable", "2026-11-27 18:00", "2026-13-40 99:99:99", "unknown", "", None, "junk", "2026-11-27T18:00:00"):
        rows.append((f"ends at {ends!r}", H({X.FE: ends, X.DE: ends})))
    for val in ("4000.0", "4000", "0", "0.0", "1e7", "-1", "nan", "inf", "abc", "12.5", "100.4", "100.6", None, "unknown"):
        rows.append((f"numbers {val!r}", H({X.FREQP: val, X.FREQD: val, X.DREQP: val, X.DREQD: val, X.DREQS: val, X.CEIL: val, X.RES: val, X.P_FLOOR: val, X.P_NET: val}, proposal=True)))
    for ss in ("IDLE", "ARMED", "FAILED", "STARTING", "ACTIVE", "COMPLETED", "weird", None):
        rows.append((f"schedule status {ss}", H({X.FSTAT: ss, X.DSTAT: ss})))
    return rows


def vocab_rows() -> list[tuple]:
    """Every kind of status text of the spec, on both functions, with the lease flag off and on: the family decides the state."""
    rows = []
    for t in list(EXPECTED_FAMILY) + FILLED:
        for fn in ("charge", "export"):
            F = X.FUNCS[fn]
            for a in ("off", "on"):
                rows.append((f"{fn} status {t[:40]!r} lease {a}", X.merged({F["status"]: t, F["a"]: a})))
    return rows


def rows_problems(text: str | None = None, first_only: bool = False, step: int = 1) -> list[str]:
    bad: list[str] = []
    w = new_world(text)
    for label, raw in [("healthy", X.merged()), ("healthy with the proposal", X.merged(proposal=True))] + table_rows(step) + combo_rows() + vocab_rows():
        bad += run_row(label, raw, w)
        bad += property_problems(w.snapshot(), f"{label}: ")
        if first_only and bad:
            return bad
    return bad


# ===========================================================================================================================
# [3] seeded random inputs
# ===========================================================================================================================
STATUS_POOL = [X.FP_ACTIVE_TEXT, X.DG_ACTIVE_TEXT, X.DONE_TEXT, "Inactive", "STARTING - taking fresh inverter snapshot", "END REQUESTED - restoring as soon as inverter write path is clear",
               "OPERATOR DECISION REQUIRED - automatic recovery is blocked; Review Live State before retrying", "RECOVERY REQUIRED - saved snapshot found", "REJECTED - arm Free Power Write Enable first",
               "RESTORE VERIFIED - durable clear pending;", "ACTIVATION VERIFY FAILED - restoring saved snapshot", "START FAILED - could not capture complete inverter snapshot",
               "SNAPSHOT DURABLY COMMITTED - 4000W at 52.0V -> 77A grid charge target", "RESTORED OK - original inverter settings verified, but ECCO could not durably record it; snapshot RETAINED",
               "ACTIVE - reboot recovery pending"]
CODE_POOL = ["TIME_LEASES", "TIME_SCHEDULES", "TELEMETRY_STALE", "TELEMETRY_OFFLINE", "DUMP_ACTIVE", "FREE_POWER_ACTIVE", "OVERRIDE_ACTIVE", "IMPORT_HEADROOM", "MANUAL_WRITE", "STOP_SOC_BELOW_RESERVE"]


def pick(rng: random.Random, good: list, bad: list, p: float):
    return rng.choice(bad) if rng.random() < p else rng.choice(good)


def random_raw(rng: random.Random, p: float) -> dict:
    raw = dict(X.HEALTHY)
    for e in (X.FA, X.FO, X.FS, X.DA, X.DO, X.DS, X.MW, X.FW, X.DW, X.FSS, X.FSG, X.DSS, X.DSG, X.FARM, X.DARM):
        v = "on" if rng.random() < 0.18 else "off"
        raw[e] = pick(rng, [v], ["unavailable", "unknown", "x", None], p)
        if raw[e] is None:
            del raw[e]
    raw[X.TL] = pick(rng, ["on", "on", "on", "off"], ["unavailable", "unknown"], p)
    for e in (X.FT, X.DT):
        raw[e] = pick(rng, STATUS_POOL, ["unknown", "unavailable", "", "weird text"], p)
    for e in (X.CG, X.EG):
        st = rng.choice(["on", "on", "off"])
        codes = [] if st == "on" else rng.sample(CODE_POOL, rng.randint(1, 3))
        if rng.random() < p * 2:
            codes = rng.sample(CODE_POOL, rng.randint(0, 2))
        raw[e] = (pick(rng, [st], ["unavailable"], p), {"blocked_by": codes})
    if rng.random() < 0.6:
        raw[X.PROP] = (rng.choice(["VALID", "VALID", "INVALID", "NOT ALLOWED", "HOLD", "UNVERIFIED", "weird"]), {"actionable": rng.choice([True, True, False]), "blocked_by": rng.choice([[], ["SOC_UNREADABLE"]])})
        raw[X.P_FLOOR] = rng.choice(["40", "42.4", "unavailable"])
        raw[X.P_NET] = rng.choice(["3000", "2800", "x"])
    if rng.random() < 0.4:
        raw[X.RETG] = (rng.choice(X.RETARGET_STATES + ("weird",)), {"reasons": rng.choice([[], ["LEASE_TOO_YOUNG: x"], ["TIME_NOT_TRUSTED: y", "MEMORY_YOUNG: z"]]), "changes": rng.choice([[], ["STOP_SOC 40.0 -> 42"], ["END 16:00 -> 17:00"]])})
    if rng.random() < 0.5:
        raw[X.LATCHED] = rng.choice(["40", "unknown", "45"])
        raw[X.RES] = rng.choice(["40", "42", "unknown"])
        raw[X.HOLD] = (rng.choice(["clear", "held", "unknown"]), {"held_by": rng.choice(["", "hold_battery", "skip_tonight,prepare_power_cut"])})
        raw[X.CEIL] = rng.choice(["0.0", "4000.0", "unknown"])
        raw[X.FE] = rng.choice(["Inactive", "2026-11-27 18:00:00", "Active - end time unavailable", "x"])
        raw[X.DE] = rng.choice(["Inactive", "2026-11-27 18:00:00", "Active - end time unavailable", "x"])
    return raw


def sweep_problems(n: int, seed: int, text: str | None = None, first_only: bool = False) -> tuple[list[str], dict]:
    bad: list[str] = []
    rng = random.Random(seed)
    w = new_world(text)
    seen: dict = {}
    for i in range(n):
        p = (0.0, 0.02, 0.08)[i % 3]
        raw = random_raw(rng, p)
        apply_raw(w, raw)
        snap = w.snapshot()
        for s in (X.CHARGE, X.EXPORT):
            seen[snap[s][0]] = seen.get(snap[s][0], 0) + 1
        bad += [f"case {i}: {b}" for b in compare(w, raw)]
        bad += property_problems(snap, f"case {i}: ")
        if first_only and bad:
            return bad, seen
    return bad, seen


# ===========================================================================================================================
# [4] the lifecycle: a reload, a restart, the first state, the time zone
# ===========================================================================================================================
def ready(snap: dict, sensor: str) -> bool:
    return snap[sensor][1]["start_allowed"] is True


def lifecycle_problems(text: str | None = None) -> list[str]:
    bad: list[str] = []
    # the first state: no input exists at all (a fresh install, the packages it reads not installed): UNKNOWN, never ready, no error
    w = new_world(text)
    apply_raw(w, {})
    snap = w.snapshot()
    if [snap[e][0] for e in X.OWN] != ["UNKNOWN", "UNKNOWN", "UNKNOWN"] or any(snap[e][1]["start_allowed"] for e in (X.CHARGE, X.EXPORT)) or w.errors:
        bad.append(f"the first state with no input: {[snap[e][0] for e in X.OWN]} {w.errors[:2]}")
    bad += property_problems(snap, "first state: ")
    # a template reload as the lab measured it: every template entity is re-created; the consumers and both gates read OFF within 1 ms, back ON after 13 to 27 s (bound 70 s): the read model
    # never says ready while they are off, and is ready again only when the gate and the consumer both say so
    w = new_world(text)
    dip = ("off", {"blocked_by": ["TIME_LEASES", "TIME_SCHEDULES"]})
    seq = [
        ("ready", {}, True),
        ("a re-created gate and consumer are unavailable for an instant", {X.TL: "unavailable", X.CG: "unavailable", X.EG: "unavailable"}, False),
        ("then OFF with the dip's codes", {X.TL: "off", X.CG: dip, X.EG: dip}, False),
        ("the consumer is back, the gates are not", {X.TL: "on"}, False),
        ("a gate is back with the consumer still off", {X.TL: "off", X.CG: X.OPEN_GATE}, False),
        ("both back", {X.TL: "on", X.CG: X.OPEN_GATE, X.EG: X.OPEN_GATE}, True),
    ]
    cur = X.merged()
    for label, over, want_ready in seq:
        cur = {**cur, **over}
        apply_raw(w, cur)
        snap = w.snapshot()
        bad += [f"reload step {label!r}: {b}" for b in compare(w, cur)]
        bad += property_problems(snap, f"reload step {label!r}: ")
        for s in (X.CHARGE, X.EXPORT):
            if ready(snap, s) != want_ready:
                bad.append(f"reload step {label!r}: {s} start_allowed {ready(snap, s)}, wanted {want_ready}")
        if label.startswith("then OFF") and not (snap[X.CHARGE][1]["why"].startswith("Not ready: Time is not trusted for leases") and "TIME_LEASES" in snap[X.CHARGE][1]["blocked_by"]):
            bad.append(f"reload step {label!r}: the read model does not say, in words, that time is not trusted: {snap[X.CHARGE][1]['why'][:70]!r}")
    # the read model's own entities re-created in the middle: it reads its inputs afresh and has no memory (no `this`): the same answer
    before = w.snapshot()
    w.reload()
    after = w.snapshot()
    if before != after or w.errors:
        bad.append(f"a template reload of the read model itself changes its answer: {before == after} {w.errors[:2]}")
    # a Home Assistant restart: the template entities exist with their RESTORED state for tens of milliseconds (consumers and gates ON), then read OFF until their inputs are read. The first render of the
    # read model sees the restored values and shows what the gate shows; nothing may act on that (nothing reads this file, and anything that acts waits 60 s after a start); the next render follows.
    import _ha_script_sim as S
    import _start_gate_sim as G

    class AdoptCtl(X.CtlMixin, G._Adopt):
        pass

    world = S.World(datetime.strptime(X.START, X.FMT).replace(tzinfo=__import__("zoneinfo").ZoneInfo(X.ZONE)).timestamp())
    for eid, v in X.merged(proposal=True).items():
        st, attrs = X.split(v)
        world.set(eid, st, attrs or None)
    cw = AdoptCtl(world, X.ZONE, text if text is not None else TEXT)
    snap = cw.snapshot()
    restored = X.merged(proposal=True)
    bad += [f"restart, restored values: {b}" for b in compare(cw, restored)]
    if not (ready(snap, X.CHARGE) and ready(snap, X.EXPORT)) or snap[X.EXPORT][0] != "ASSISTED":
        bad.append("restored values: the read model shows what the gates show (ready), and the proposal as the coordinator shows it")
    off = {**restored, X.TL: "off", X.CG: dip, X.EG: dip}
    cw.bulk(off)
    snap = cw.snapshot()
    bad += [f"restart, after the OFF: {b}" for b in compare(cw, off)]
    if ready(snap, X.CHARGE) or ready(snap, X.EXPORT) or "TIME_LEASES" not in snap[X.EXPORT][1]["blocked_by"] or snap[X.EXPORT][0] != "IDLE":
        bad.append("after the restart's OFF the read model is still ready, or does not name the cause")
    # the time zone changes nothing: the read model parses no time (it shows an end-time text as it is, after a check of its form)
    raw = X.merged({X.FE: "2026-11-27 18:00:00", X.DE: "2026-03-29 01:30:00", X.DA: "on", X.DS: "on", X.DT: X.DG_ACTIVE_TEXT}, proposal=True)
    answers = []
    for zone in ("Europe/London", "Pacific/Auckland", "UTC", "America/Los_Angeles"):
        wz = X.CtlWorld(text, healthy=False, zone=zone)
        apply_raw(wz, raw)
        answers.append(wz.snapshot())
    if any(a != answers[0] for a in answers) or answers[0][X.EXPORT][1]["lease"]["ends_at"] != "2026-03-29 01:30:00":
        bad.append("the time zone changes the answer (an end-time text, a skipped local hour included, must be shown as it is)")
    return bad


# ===========================================================================================================================
# [5] rows: the same inputs, the same answer, no new row
# ===========================================================================================================================
def churn_problems(text: str | None = None) -> list[str]:
    bad: list[str] = []
    w = new_world(text)
    raw = X.merged(proposal=True)
    apply_raw(w, raw)
    snap, rows = w.snapshot(), w.rows()
    w.force()
    w.force()
    if w.snapshot() != snap or w.rows() != rows:
        bad.append("the same inputs rendered twice: a different state or attributes, or a new row")
    w.advance(1800)
    w.force()
    if w.snapshot() != snap or w.rows() != rows:
        bad.append("half an hour with unchanged inputs: a different state or attributes, or a new row")
    # a poll moves the number-bearing reasons of the gates and a running lease moves the dongle's status text: the read model reads both and publishes neither
    for i in range(60):
        gate = ("on", {"blocked_by": [], "reasons": [f"ALLOWED: every check passed ({i} s from the clock)"]})
        w.bulk({X.CG: gate, X.EG: gate})
    if w.snapshot() != snap or w.rows() != rows:
        bad.append("the gates' reasons move with every poll and the read model publishes a new row: a number-bearing text leaks into an attribute")
    w.lease("export")
    running = w.snapshot()
    rows = w.rows()
    for i in range(60):
        w.bulk({X.DT: f"ACTIVE - VERIFIED OK; target 3000W export - TRACKING - battery ceiling {3000 + 10 * i}W; Stop SOC 40%",
                X.EG: ("off", {"blocked_by": ["DUMP_ACTIVE"], "reasons": [f"DUMP_ACTIVE: x {i}"]})})
    if running[X.EXPORT][0] != "RUNNING" or w.snapshot() != running or w.rows() != rows:
        bad.append("a running lease: the dongle's status text moves with every poll and the read model publishes a new row, or does not read RUNNING")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


# ===========================================================================================================================
# [6] the vocabulary: the firmware's own status texts, the gate's own codes
# ===========================================================================================================================
FILLED = ["SNAPSHOT DURABLY COMMITTED - 4000W at 52.0V -> 77A grid charge target", "ACTIVE - VERIFIED OK; 155A grid charge; automatic restore armed",
          "RESTORE BLOCKED - register 244 context changed since this lease started (a context); 232/256-261 already restored, 268-279/230 withheld",
          "RESTORE BLOCKED - register 244 context changed since this lease started (a context)", "ACCEPT REFUSED - Free Power residue: 230", "ACCEPT REFUSED - implausible value: 232=99999",
          "ACTIVE - VERIFIED OK; target 3000W export - TRACKING - battery ceiling 3800W; Stop SOC 40%", "ACTIVE - VERIFIED OK; target 3000W export - SATURATED LOW - battery ceiling 500W (PV export already exceeds target); Stop SOC 40%",
          "ACTIVE - VERIFIED OK; target 3000W export - NO RESPONSE - holding ~60s before a bounded retry (1 of 3 retries used); battery ceiling 3800W; Stop SOC 40%",
          "ACCEPT REFUSED - no Dump to Grid operator decision is pending"]
# the formats the firmware builds with snprintf (checked to exist in the firmware: a firmware change that removes one fails the suite until the model is looked at again)
FORMATS = ["SNAPSHOT DURABLY COMMITTED - %.0fW at %.1fV -> %uA grid charge target", "ACTIVE - VERIFIED OK; %uA grid charge; automatic restore armed",
           "RESTORE BLOCKED - register 244 context changed since this lease started (%s)", "ACCEPT REFUSED - Free Power residue: %s", "ACCEPT REFUSED - implausible value: %s",
           "ACTIVE - VERIFIED OK; target %uW export - TRACKING - battery ceiling %uW; Stop SOC %d%%", "ACTIVE - VERIFIED OK; target %uW export - SATURATED LOW - battery ceiling %uW"]
# the spec: the family of each kind of text (hand-written from the firmware's own words, so the table below and the prefixes are two independent statements)
EXPECTED_FAMILY = {
    "ACTIVE - VERIFIED OK; 155A grid charge; automatic restore armed": "ACTIVE", "ACTIVE - VERIFIED OK; target 3000W export - SETTLING - battery ceiling 3800W; Stop SOC 40%": "ACTIVE",
    "ACTIVE - reboot recovery pending": "FAULT", "OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State": "FAULT",
    "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted": "FAULT", "RECOVERY REQUIRED - saved snapshot found": "FAULT",
    "RESTORE BLOCKED - live inverter state matches neither the saved snapshot nor the intended state; operator decision required": "FAULT",
    "RESTORE WRITE FAILED - snapshot retained; will retry automatically": "FAULT", "RESTORE VERIFY TIMEOUT - snapshot retained for retry": "FAULT",
    "RESTORE VERIFY FAILED - snapshot retained for retry": "FAULT", "ACTIVATION VERIFY TIMEOUT - restore required": "FAULT", "END BLOCKED - RECOVERY BLOCKED: x": "FAULT",
    "FORCE RESTORE REFUSED - LIVE STATE CHANGED SINCE REVIEW - review again": "FAULT", "FORCE RESTORE ORIGINAL FAILED - durable recovery obligation retained": "FAULT",
    "ACCEPT REFUSED - state is ORIGINAL, not NEITHER": "FAULT", "ACCEPT FAILED - durable clear commit failed;": "FAULT", "REJECTED - RECOVERY BLOCKED: durable recovery marker exists": "FAULT",
    "RESTORING - writing back original inverter settings": "ENDING", "END REQUESTED - restoring as soon as inverter write path is clear": "ENDING", "END DEFERRED - another inverter write is active": "ENDING",
    "FORCE RESTORE - fingerprint confirmed, writing original values": "ENDING", "RESTORE VERIFIED - durable clear pending;": "ENDING", "RESTORE DEFERRED - outstanding Dump to Grid snapshot found at boot;": "ENDING",
    "Retrying durable recovery-marker clear (recovery obligation already resolved)...": "ENDING", "RECOVERY RESOLVED - durable recovery-marker clear still pending; will retry": "ENDING",
    "RECOVERY OBLIGATION RESOLVED - durable clear pending (will retry automatically)": "ENDING", "ACTIVATION WRITE FAILED - restoring saved snapshot": "ENDING",
    "ACTIVATION VERIFY FAILED - restoring saved snapshot": "ENDING", "FORCE RESTORE ORIGINAL SUCCESS - hardware restored and verified; durable recovery-marker clear pending, will retry": "ENDING",
    "ACCEPT CURRENT STATE SUCCESS - accepted; durable recovery-marker clear pending, will retry": "ENDING",
    "RESTORED OK - original inverter settings verified, but ECCO could not durably record it; snapshot RETAINED": "ENDING",
    "STARTING - taking fresh inverter snapshot": "STARTING", "Snapshot durably committed - writing export power ceiling": "STARTING", "SNAPSHOT DURABLY COMMITTED - 4000W at 52.0V -> 77A grid charge target": "STARTING",
    "Inactive": "DONE", "RESTORED OK - original inverter settings verified": "DONE", "RECOVERY RESOLVED OK - durable recovery marker cleared": "DONE",
    "FORCE RESTORE ORIGINAL SUCCESS - original inverter settings verified, durable recovery marker cleared": "DONE",
    "ACCEPT CURRENT STATE SUCCESS - current live configuration accepted, durable recovery marker cleared": "DONE", "END IGNORED - no saved Free Power snapshot": "DONE",
    "REJECTED - arm Free Power Write Enable first": "DONE", "REJECTED - Dump to Grid already active": "DONE", "START FAILED - could not capture complete inverter snapshot; nothing written": "DONE",
    "": "OTHER", "unknown": "OTHER", "unavailable": "OTHER", "a text nobody knows": "OTHER", "active - verified ok": "OTHER", "ACTIVE": "OTHER",
}


def firmware_status_literals() -> list:
    lits = []
    for sensor in ("free_power_status", "dump_status"):
        lits += re.findall(rf'id\({sensor}\)\.publish_state\("((?:[^"\\]|\\.)*)"', FW_TEXT)
    return sorted(set(lits))


def template_family(text: str | None, fn: str, t: str) -> str:
    """The family the TEMPLATE puts a status text in, read back from the sensor: ACTIVE -> RUNNING, FAULT -> FAULT, ENDING -> ENDING, STARTING -> ARMED, DONE -> IDLE, OTHER -> UNKNOWN (own flags: a lease
    running, or none: the flags that fit the family; the two others shown with the lease flag on, no operation, no snapshot)."""
    F = X.FUNCS[fn]
    raw = X.merged({F["status"]: t, F["a"]: "on" if t.startswith("ACTIVE") or X.family(t) == "ENDING" else "off"})
    w = new_world(text)
    apply_raw(w, raw)
    return w.state(F["sensor"])


def vocabulary_problems(text: str | None = None) -> list[str]:
    bad: list[str] = []
    lits = firmware_status_literals()
    if len(lits) < 80:
        bad.append(f"only {len(lits)} status literals found in the firmware: the extraction is broken")
    for t in lits + FILLED:
        fam = X.family(t)
        if fam == "OTHER":
            bad.append(f"the firmware can publish {t[:90]!r} and no family takes it")
    for t, fam in EXPECTED_FAMILY.items():
        if X.family(t) != fam:
            bad.append(f"the reference puts {t[:70]!r} in {X.family(t)}, the spec says {fam}")
    for f in FORMATS:
        if f not in FW_TEXT:
            bad.append(f"the firmware no longer builds {f!r}")
    # the TEMPLATE puts every text where the reference does: the families through the lifecycle (a lease running or ending, a fault, a start, nothing under way, unknown)
    for t in list(EXPECTED_FAMILY) + lits[::3] + FILLED:
        for fn in ("charge", "export"):
            fam = X.family(t)
            on = t.startswith("ACTIVE") or fam == "ENDING"
            raw = X.merged({X.FUNCS[fn]["status"]: t, X.FUNCS[fn]["a"]: "on" if on else "off"})
            ref = X.reference(raw)[X.FUNCS[fn]["sensor"]][0]
            got = template_family(text, fn, t)
            if got != ref:
                bad.append(f"{fn}: the status {t[:60]!r} gives {got}, the reference {ref}")
    # a FAULT text is never ready, and a stale DONE or STARTING text with every flag off is just IDLE
    for t in lits:
        fam = X.family(t)
        for fn in ("charge", "export"):
            w = new_world(text)
            apply_raw(w, X.merged({X.FUNCS[fn]["status"]: t}))
            st = w.state(X.FUNCS[fn]["sensor"])
            if fam == "FAULT" and (st != "FAULT" or w.snapshot()[X.FUNCS[fn]["sensor"]][1]["start_allowed"]):
                bad.append(f"{fn}: the FAULT text {t[:60]!r} reads {st}")
            if fam in ("DONE", "STARTING") and st != "IDLE":
                bad.append(f"{fn}: the stale text {t[:60]!r} with every flag off reads {st}, not IDLE")
    return bad


def gate_codes() -> set:
    """Every code the gate package can name (the first literal of each ('CODE', hit, text) tuple of its rule blocks)."""
    return set(re.findall(r"\('([A-Z][A-Z_]+)', [^,]+,", GATE_TEXT)) | set(re.findall(r"^\s*\('(?:binary_sensor|sensor)\.[a-z0-9_]+', '([A-Z][A-Z_]+)',", GATE_TEXT, re.M))


# ===========================================================================================================================
# [7] the real gate and the real plan helpers feeding the read model
# ===========================================================================================================================
def real_gate_problems(text: str | None = None) -> list[str]:
    import _start_gate_sim as G
    bad: list[str] = []

    class AdoptCtl(X.CtlMixin, G._Adopt):
        pass

    gw = G.GateWorld(GATE_TEXT, None, plan_text=PLAN_TEXT, poll=True, start_ha=False)
    gw.foreign = True
    pw, w = gw.pw, gw.w
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    gw.put(G.STOP, "40.0")
    cw = AdoptCtl(w, X.ZONE, text if text is not None else TEXT)
    extra = {e: v for e, v in X.HEALTHY.items() if e not in w.states and e not in (X.CG, X.EG)}
    cw.bulk({**extra, X.FT: "Inactive", X.DT: "Inactive", X.FE: "Inactive", X.DE: "Inactive", X.CEIL: "0.0"})      # the repository's Free Power model words its idle status its own way: the firmware's is "Inactive"

    def both() -> tuple:
        gw.sync()
        cw.force()
        s = cw.snapshot()
        return s, gw.state(G.EXPORT_GATE), gw.state(G.CHARGE_GATE)

    s, eg, cg = both()
    if (eg, cg) != ("on", "on") or s[X.CHARGE][0] != "IDLE" or s[X.EXPORT][0] != "IDLE" or not (ready(s, X.CHARGE) and ready(s, X.EXPORT)):
        bad.append(f"healthy: gates {eg}/{cg}, charge {s[X.CHARGE][0]} {s[X.CHARGE][1]['blocked_by']}, export {s[X.EXPORT][0]} {s[X.EXPORT][1]['blocked_by']} {cw.errors[:2]}")
    # the time trust consumer the gate reads goes off: the gate closes with its codes and the read model says it, in words, and is not ready
    gw.put(G.TL, "off")
    s, eg, cg = both()
    if eg != "off" or ready(s, X.CHARGE) or ready(s, X.EXPORT) or "TIME_LEASES" not in s[X.EXPORT][1]["blocked_by"] or not s[X.CHARGE][1]["why"].startswith("Not ready: Time is not trusted for leases"):
        bad.append(f"time not trusted: gates {eg}/{cg}, {s[X.CHARGE][1]['blocked_by']} {s[X.CHARGE][1]['why'][:60]!r}")
    gw.put(G.TL, "on")
    # the dongle's poll goes silent: 301 s later the real gate says TELEMETRY_STALE; the read model is not ready and says the data are not fresh
    gw.stop_poll()
    gw.advance(305)
    gw.sync()
    s, eg, cg = both()
    if eg != "off" or ready(s, X.EXPORT) or "TELEMETRY_STALE" not in s[X.EXPORT][1]["blocked_by"] or s[X.EXPORT][1]["why"] != "Not ready: " + X.GATE_SENTENCES["TELEMETRY_STALE"]:
        bad.append(f"stale telemetry: gate {eg}, {s[X.EXPORT][1]['blocked_by']} {s[X.EXPORT][1]['why'][:70]!r}")
    gw.poll_feed = gw.tw.feed(G.POLL, period=10.0)
    gw.advance(15)
    # a Hold battery from the REAL plan helper package: the export gate closes (OVERRIDE_ACTIVE), the charge gate does not read it
    pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
    s, eg, cg = both()
    f = s[X.EXPORT][1]["facts"]
    # (the interpreter renders the plan package's template sensors on read and has no attributes for them: held_by is the one thing the real Home Assistant adds, the unit tests of the model cover it)
    if eg != "off" or cg != "on" or ready(s, X.EXPORT) or not ready(s, X.CHARGE) or "OVERRIDE_ACTIVE" not in s[X.EXPORT][1]["blocked_by"] or f["hold"] != "held" \
            or s[X.EXPORT][1]["why"] != "Not ready: " + X.GATE_SENTENCES["OVERRIDE_ACTIVE"]:
        bad.append(f"a Hold battery: gates {eg}/{cg}, {s[X.EXPORT][1]['blocked_by']} {f}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
    s, eg, cg = both()
    if eg != "on" or not ready(s, X.EXPORT) or s[X.EXPORT][1]["facts"]["hold"] != "clear":
        bad.append(f"the Hold battery cancelled: {eg} {s[X.EXPORT][1]['facts']}")
    # Prepare for power cut raises the effective reserve (the facts show it) and holds the export
    pw.run_script("ecco_plan_override_start", {"kind": "prepare_power_cut", "expiry_min": 60}, seconds=30)
    s, eg, cg = both()
    if s[X.EXPORT][1]["facts"]["reserve_pct"] != 80 or s[X.EXPORT][1]["facts"]["hold"] != "held" or ready(s, X.EXPORT):
        bad.append(f"Prepare for power cut: {s[X.EXPORT][1]['facts']} {eg}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "prepare_power_cut"})
    both()
    # a Dump lease the dongle reports as running (flags, latched Stop SOC, status text): the real gate closes both gates (DUMP_ACTIVE), the export reads RUNNING, the charge function IDLE and not ready,
    # the owner EXPORT; the lease ends and everything is ready again
    gw.d.dump_start(latched=40.0)
    cw.bulk({X.DT: X.DG_ACTIVE_TEXT, X.DE: "2026-11-27 18:00:00", X.DS: "on"})
    w.set(G.DG_SNAP, "on")
    s, eg, cg = both()
    if s[X.EXPORT][0] != "RUNNING" or s[X.CHARGE][0] != "IDLE" or ready(s, X.CHARGE) or s[X.OWNER][0] != "EXPORT" or "DUMP_ACTIVE" not in s[X.CHARGE][1]["blocked_by"] \
            or s[X.CHARGE][1]["why"] != "Not ready: " + X.GATE_SENTENCES["DUMP_ACTIVE"] or s[X.EXPORT][1]["facts"]["floor"] != "OK":
        bad.append(f"a running Dump lease: export {s[X.EXPORT][0]}, charge {s[X.CHARGE][0]} {s[X.CHARGE][1]['why'][:60]!r}, owner {s[X.OWNER][0]} {s[X.EXPORT][1]['facts']}")
    gw.d.dump_end()
    w.set(G.DG_SNAP, "off")
    cw.bulk({X.DT: X.DONE_TEXT, X.DE: "Inactive", X.DS: "off"})
    s, eg, cg = both()
    if s[X.EXPORT][0] != "IDLE" or not ready(s, X.EXPORT) or s[X.OWNER][0] != "NONE":
        bad.append(f"the lease ended: {s[X.EXPORT][0]} {s[X.OWNER][0]}")
    # a restore owed (a snapshot flag with nothing running): FAULT on the function that owns it, the other one not startable, the owner RESTORE_OWED
    w.set(G.DG_SNAP, "on")
    cw.bulk({X.DS: "on"})
    s, eg, cg = both()
    if s[X.EXPORT][0] != "FAULT" or s[X.OWNER][0] != "RESTORE_OWED" or ready(s, X.CHARGE) or ready(s, X.EXPORT) or "DUMP_SNAPSHOT" not in s[X.CHARGE][1]["blocked_by"]:
        bad.append(f"a restore owed: export {s[X.EXPORT][0]}, owner {s[X.OWNER][0]} {s[X.CHARGE][1]['blocked_by']}")
    # every code the real gate printed on the way is one the read model has a sentence for
    if cw.errors or gw.tw.errors:
        bad.append(f"template errors {cw.errors[:2]} {gw.tw.errors[:2]}")
    return bad


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
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor"), ("switch", "switch"), ("number", "number"), ("button", "button"), ("select", "select")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                out.add(f"{domain}.{X.DONGLE}_{slug(e['name'])}")
    return out


def package_ids(text: str) -> set:
    d = yaml.load(text, Loader=UniqueKeyLoader) or {}
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


def template_strings(d: dict) -> list[str]:
    out = []
    for block in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                for key in ("state", "availability"):
                    if isinstance(it.get(key), str):
                        out.append(it[key])
                for v in (it.get("attributes") or {}).values():
                    if isinstance(v, str):
                        out.append(v)
    return out


OTHER_TEXT = {p.name: p.read_text(encoding="utf-8") for p in sorted(PKGS.glob("*.yaml")) if p.name != "ecco_control_state.yaml"}
REPO_IDS = firmware_ids()
for _t in OTHER_TEXT.values():
    REPO_IDS |= package_ids(_t)
REPO_UNIQUE = {u for _t in OTHER_TEXT.values() for u in re.findall(r"unique_id: \"?([a-z0-9_]+)", _t)}
GATE_PACKAGE_CODES = gate_codes()


def mention_problems(others: dict) -> list[str]:
    """No other package may mention the three entities of the read model (it is display, never a gate)."""
    return [f"{name} mentions {eid}" for name, t in sorted(others.items()) for eid in sorted(X.OWN) if eid in t or eid.split(".", 1)[1] in t]


def static_problems(text: str) -> list[str]:
    bad: list[str] = []
    raw = text.encode("utf-8")
    try:
        d = yaml.load(text, Loader=UniqueKeyLoader)
    except Exception as exc:  # noqa: BLE001
        return [f"the file does not load: {str(exc)[:100]}"]
    if not isinstance(d, dict) or set(d) != {"template"}:
        bad.append(f"top-level keys {sorted(d) if isinstance(d, dict) else d}: only `template:` is allowed (no automation, script, helper, trigger)")
        return bad
    if [list(b) for b in d["template"]] != [["sensor"]]:
        bad.append("the template block holds anything but one sensor list")
        return bad
    ents = [it for block in d["template"] for kind in block for it in block[kind]]
    ids = {f"sensor.{slug(e['name'])}" for e in ents}
    if ids != OWN_IDS or len(ents) != 3:
        bad.append(f"the entities are {sorted(ids ^ OWN_IDS)} off the three expected")
    uids = [e.get("unique_id") for e in ents]
    if uids != [slug(e["name"]) for e in ents] or len(set(uids)) != 3:
        bad.append("each unique_id is the slug of its name, once")
    if ids & REPO_IDS or set(uids) & REPO_UNIQUE:
        bad.append(f"an id is defined elsewhere in the repository: {sorted(ids & REPO_IDS)} {sorted(set(uids) & REPO_UNIQUE)}")
    for e in ents:
        if set(e) != {"name", "unique_id", "icon", "state", "attributes"}:
            bad.append(f"{e.get('name')}: keys {sorted(e)} off name, unique_id, icon, state, attributes (no unit, no state_class, no device_class, no availability, no delay)")
        want = EXPECTED_ATTRS.get(f"sensor.{slug(e['name'])}")
        if want is not None and list(e.get("attributes") or {}) != want:
            bad.append(f"{e['name']}: attributes {list(e.get('attributes') or {})} off {want}")
    # the write vocabulary: nothing that can call a service, start anything or define a helper
    for tok in ("action", "actions", "service", "trigger", "triggers", "condition", "conditions", "sequence", "automation", "script", "input_number", "input_boolean", "input_text", "input_datetime",
                "button", "choose", "variables", "event", "mode", "fields", "availability", "delay_on", "delay_off", "unit_of_measurement", "state_class", "device_class"):
        if re.search(rf"^\s*-?\s*{tok}\s*:", text, re.M):
            bad.append(f"the key `{tok}:` appears: the package must contain no service call, script, automation, helper, trigger or availability rule")
    for tok in (".turn_on", ".turn_off", ".press", ".set_value", ".toggle", ".select_option", "persistent_notification", "homeassistant.", "esphome.", "rest_command", "shell_command", "notify.", "mqtt.",
                "button.", "input_text.", "script.turn_on", "automation.trigger"):
        if tok in text:
            bad.append(f"the write vocabulary token {tok!r} appears")
    tpl = "\n".join(template_strings(d))
    reads = set(ENTITY_RE.findall(tpl))
    if reads != EXPECTED_READS:
        bad.append(f"it reads {sorted(reads ^ EXPECTED_READS)} off the expected set")
    missing = sorted(reads - OWN_IDS - REPO_IDS)
    if missing:
        bad.append(f"it reads entities that exist nowhere in the repository: {missing}")
    if reads & OWN_IDS:
        bad.append(f"it reads its own entities: {sorted(reads & OWN_IDS)}")
    pairs = set(STATE_ATTR_RE.findall(tpl))
    if pairs != EXPECTED_STATE_ATTRS or tpl.count("state_attr(") != len(STATE_ATTR_RE.findall(tpl)):
        bad.append(f"the (entity, attribute) pairs it reads are {sorted(pairs ^ EXPECTED_STATE_ATTRS)} off the expected set (or an attribute is read with a name that is not a literal)")
    for pattern, why in ((r"states\[", "a state object (its last_changed would be a moving time)"), (r"(?<![A-Za-z0-9_])states\.", "a state object"), (r"(?<![A-Za-z0-9_'])this\s*(?:\.|\)|is\b)", "`this` (after a reload it has no attributes)"),
                         (r"now\(", "now(): a time that moves"), (r"as_timestamp", "as_timestamp: a time is parsed in the Core process zone"), (r"utcnow", "utcnow"), (r"today_at", "today_at"),
                         (r"is_state", "is_state"), (r"timestamp_custom", "timestamp_custom"), (r"regex_", "a regular expression"), (r"\| random", "randomness"), (r"expand\(", "expand"),
                         (r"device_id", "a device"), (r"area_", "an area"), (r"integration_entities", "integration_entities")):
        if re.search(pattern, tpl):
            bad.append(f"the templates use {why}")
    for eid in sorted(set(ENTITY_RE.findall(text))):
        if FORBIDDEN_FORECAST.search(eid):
            bad.append(f"a forecast, advice or measurement entity id appears: {eid}")
    # who is named: the leases consumer of the time trust package (and the file name) and both gates; nothing of the other pinned names
    t2 = text.replace("ecco_time_trust.yaml", "").replace(TIME_ID, "")
    if "ecco_time_trust" in t2:
        bad.append("it names a time trust entity other than the leases consumer")
    if "ecco_start_bypass" in text:
        bad.append("it mentions the start bypass detector")
    # the shared rule block: the same text in every template that carries it
    for e in ents:
        sid = f"sensor.{slug(e['name'])}"
        strings = [("state", e["state"])] + [(f"attributes.{k}", v) for k, v in (e.get("attributes") or {}).items() if isinstance(v, str)]
        cores = [(k, v.split(MARKER)[0]) for k, v in strings if MARKER in v]
        if len(cores) != CORE_COUNT.get(sid, -1):
            bad.append(f"{e['name']}: {len(cores)} templates carry the rule block, {CORE_COUNT.get(sid)} expected: {[k for k, _ in cores]}")
        if len({flat(c) for _k, c in cores}) > 1:
            bad.append(f"{e['name']}: the rule block is not the same text in {[k for k, _ in cores]}")
        for k, v in strings:
            if MARKER not in v and k in ("state", "attributes.why", "attributes.next_action", "attributes.blocked_by", "attributes.start_allowed", "attributes.note"):
                bad.append(f"{e['name']} {k} carries no rule block")
    # the closed sentences: every one is in the file, and none has a digit
    for table in (X.GATE_SENTENCES, X.READY_SENTENCES, X.OTHER_SENTENCES, X.RUNNING_SENTENCES, X.NEXT_SENTENCES, X.OWNER_NOTES):
        for k, s in table.items():
            if s not in text:
                bad.append(f"the sentence {k} is not in the file: {s[:50]!r}")
            if re.search(r"\d", s):
                bad.append(f"the sentence {k} has a digit")
            if "'" in s or '"' in s:
                bad.append(f"the sentence {k} has a quote")
    for fn in ("charge", "export"):
        for k, lab in X.UNREADABLE_LABELS.items():
            s = lab.format(lease=X.FUNCS[fn]["lease"], other_lease=X.FUNCS[fn]["other_lease"])
            if s not in text:
                bad.append(f"the label {fn} {k} is not in the file: {s[:50]!r}")
    if X.END_NOW_MESSAGE not in text:
        bad.append("the END NOW message is not in the file")
    if set(X.GATE_SENTENCES) - {"GATE_INCONSISTENT"} != GATE_PACKAGE_CODES:
        bad.append(f"the gate's codes and the sentences differ: {sorted((set(X.GATE_SENTENCES) - {'GATE_INCONSISTENT'}) ^ GATE_PACKAGE_CODES)}")
    # the status families and the notes are written in the templates exactly as the model has them
    for table in (X.FAULT_PREFIXES, X.ENDING_PREFIXES, X.STARTING_PREFIXES, X.DONE_PREFIXES):
        for pre in table:
            if f"'{pre}'" not in text:
                bad.append(f"the status prefix {pre!r} is not in the file")
    for note in X.NOTES_CHARGE + X.NOTES_EXPORT + ("IMPORT_NOT_CONFIGURED", "IMPORT_CEILING_NOT_READ", "PROPOSAL_NOT_INSTALLED", "SCHEDULE_LAST_RUN_FAILED"):
        if f"'{note}'" not in text:
            bad.append(f"the note {note} is not in the file")
    # hygiene
    if not text.isascii() or b"\r" in raw or "\t" in text or re.search(r"[ ]+$", text, re.M):
        bad.append("not ASCII / LF / tab-free / trailing-space-free")
    for pat in (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", r"[Cc]:\\Users", r"/Users/", r"\bsk-[A-Za-z0-9]{10,}", r"\bpassword\b|\bsecret\b|\btoken\b|api_key", r"https?://"):
        if re.search(pat, text):
            bad.append(f"a site value or secret pattern appears: {pat}")
    if re.search(r"(?<![a-z_.])(?:sensor|binary_sensor|number|button|switch)\.(?!ecco_clock_dongle_|ecco_|input_)", tpl):
        bad.append("an entity id outside the ecco namespace is read")
    if re.search(r"\binitial\s*:", text):
        bad.append("an `initial:` appears")
    # the firmware's recovery-execute action ids are spelled as two adjacent literals here: the recovery-evidence guards of registry/tests scan every home-assistant/ file for them whole
    for forbidden in ("FORCE_RESTORE" "_ORIGINAL", "force_restore" "_original", "ACCEPT_CURRENT" "_STATE", "accept_current" "_state", "FORCE_RUN" "NING"):
        if forbidden in text:
            bad.append(f"the firmware recovery token {forbidden} appears whole (registry guard)")
    # the saved profile's Live Match entity is not named: registry/tests/test_fallback_live_match.py allows only the fallback status package, the dashboard and the HA package suites; the reserved tokens of the
    # fallback and failback records (registry/tests/_scope_chain.py BANNED) appear nowhere in this package
    if RESERVED_TOKENS.search(text):
        bad.append(f"a reserved fallback token appears: {sorted(set(RESERVED_TOKENS.findall(text)))}")
    hdr = "\n".join(line.lstrip("#") for line in text.splitlines() if line.startswith("#"))
    hflat = flat(hdr)
    for pin in HEADER_PINS:
        if flat(pin) not in hflat:
            bad.append(f"the header lost: {pin!r}")
    return bad


# ===========================================================================================================================
# the battery run on a package text
# ===========================================================================================================================
def battery(text: str, deep: bool = False) -> list[str]:
    bad = static_problems(text)
    if bad:
        return bad
    try:
        bad += rows_problems(text, first_only=True, step=5 if not deep else 1)
        if bad:
            return bad
        bad += sweep_problems(90 if not deep else 600, 20261127, text, first_only=True)[0]
        if bad:
            return bad
        bad += inputs_problems(text, first_only=True)
        if bad:
            return bad
        bad += churn_problems(text)
        if bad:
            return bad
        bad += lifecycle_problems(text)
    except Exception as exc:  # noqa: BLE001 - a package that breaks the model is a dead mutant, not a crash
        bad.append(f"the model raised {type(exc).__name__}: {str(exc)[:120]}")
    return bad


# ===========================================================================================================================
# the mutants: (label, old, new); every occurrence of `old` is replaced (a consistent change of a rule) unless the label starts with "one copy:"
# ===========================================================================================================================
OPEN = "{%- set open = g == 'on' and gl is not none and (gl | length) == 0 and tl == 'on' -%}"
OK_LINE = "{%- set ok = open and st in ['IDLE', 'PLANNED', 'ASSISTED'] -%}"
MUTANTS = [
    ("the gate's time is not part of open", OPEN, "{%- set open = g == 'on' and gl is not none and (gl | length) == 0 -%}"),
    ("the gate's list is not part of open", OPEN, "{%- set open = g == 'on' and tl == 'on' -%}"),
    ("the gate's state is not part of open", OPEN, "{%- set open = gl is not none and (gl | length) == 0 and tl == 'on' -%}"),
    ("a time that reads unavailable is not unreadable and is open", "[('TIME', tl), ", "["),
    ("start_allowed also in ARMED", OK_LINE, "{%- set ok = open and st in ['IDLE', 'PLANNED', 'ASSISTED', 'ARMED'] -%}"),
    ("start_allowed also in RUNNING", OK_LINE, "{%- set ok = open and st in ['IDLE', 'PLANNED', 'ASSISTED', 'RUNNING'] -%}"),
    ("start_allowed ignores the gate", OK_LINE, "{%- set ok = st in ['IDLE', 'PLANNED', 'ASSISTED'] -%}"),
    ("start_allowed not in PLANNED", OK_LINE, "{%- set ok = open and st in ['IDLE', 'ASSISTED'] -%}"),
    ("an unreadable gate list is not unreadable", "{%- if g not in ['on', 'off'] or gl is none -%}", "{%- if g not in ['on', 'off'] -%}"),
    ("an unreadable gate state is not unreadable", "{%- if g not in ['on', 'off'] or gl is none -%}", "{%- if gl is none -%}"),
    ("the time trust reading is not required", "[('TIME', tl), ", "["),
    ("the other function's lease flag is not required", "('OTHER_ACTIVE', ya), ", ""),
    ("the manual write flag is not required", "('MANUAL_WRITE', mw), ", ""),
    ("the write enable is not required", "('WRITE_ENABLE', ar), ", ""),
    ("the guarded start script is not required", "('GUARDED_SCRIPT', gd), ", ""),
    ("the armed helper is not required", ", ('SCHEDULE_ARMED', sa)]", "]"),
    ("a status text this model does not know is not unreadable", "{%- if t in bad or fam == 'OTHER' -%}", "{%- if t in bad -%}"),
    ("a status text this model does not know counts as DONE", "else 'OTHER')))) -%}", "else 'DONE')))) -%}"),
    ("the unreadable list is ignored by the state", "{%- set unk = (ns.u | length) > 0 -%}", "{%- set unk = false -%}"),
    ("two leases at once are not a fault", "else ('FAULT' if (conflict or fam == 'FAULT' or owed)", "else ('FAULT' if (fam == 'FAULT' or owed)"),
    ("a restore owed is not a fault", "else ('FAULT' if (conflict or fam == 'FAULT' or owed)", "else ('FAULT' if (conflict or fam == 'FAULT')"),
    ("a FAULT text is not a fault", "else ('FAULT' if (conflict or fam == 'FAULT' or owed)", "else ('FAULT' if (conflict or owed)"),
    ("a restore is owed while an operation runs", "{%- set owed = ls == 'on' and la == 'off' and lo == 'off' -%}", "{%- set owed = ls == 'on' and la == 'off' -%}"),
    ("a snapshot with a lease running is owed", "{%- set owed = ls == 'on' and la == 'off' and lo == 'off' -%}", "{%- set owed = ls == 'on' and lo == 'off' -%}"),
    ("two leases are only a conflict for the first", "{%- set conflict = la == 'on' and ya == 'on' -%}", "{%- set conflict = la == 'on' and ya == 'on' and lo == 'off' -%}"),
    ("a lease is RUNNING without a verified status", "(('RUNNING' if fam == 'ACTIVE' else", "(('RUNNING' if true else"),
    ("an operation in progress is not ENDING", "else ('ENDING' if lo == 'on'", "else ('ENDING' if false"),
    ("a start in progress is not ARMED", "else ('ARMED' if (lo == 'on' and fam == 'STARTING')", "else ('ARMED' if false"),
    ("the write enable does not arm", "else ('ARMED' if (ar == 'on' or sc == 'on' or gd == 'on')", "else ('ARMED' if (sc == 'on' or gd == 'on')"),
    ("the guarded start script does not arm", "else ('ARMED' if (ar == 'on' or sc == 'on' or gd == 'on')", "else ('ARMED' if (ar == 'on' or sc == 'on')"),
    ("the scheduled start script does not arm", "else ('ARMED' if (ar == 'on' or sc == 'on' or gd == 'on')", "else ('ARMED' if (ar == 'on' or gd == 'on')"),
    ("a schedule armed is not PLANNED", "('PLANNED' if sa == 'on' else 'IDLE')", "('PLANNED' if false else 'IDLE')"),
    ("a running lease with an ending status is RUNNING", "('ENDING' if fam == 'ENDING' else ('ARMED' if fam == 'STARTING' else 'FAULT'))) if la == 'on'", "('RUNNING' if fam == 'ENDING' else ('ARMED' if fam == 'STARTING' else 'FAULT'))) if la == 'on'"),
    ("a lease that is not confirmed is not a fault", "('ARMED' if fam == 'STARTING' else 'FAULT'))) if la == 'on'", "('ARMED' if fam == 'STARTING' else 'IDLE'))) if la == 'on'"),
    ("UNKNOWN comes after the others", "{%- set st = 'UNKNOWN' if unk", "{%- set st = 'UNKNOWN' if false"),
    ("a proposal is assisted without an open gate", "{%- set assisted = open and ps == 'VALID' and pa is sameas true -%}", "{%- set assisted = ps == 'VALID' and pa is sameas true -%}"),
    ("a proposal is assisted without the actionable flag", "{%- set assisted = open and ps == 'VALID' and pa is sameas true -%}", "{%- set assisted = open and ps == 'VALID' -%}"),
    ("an INVALID proposal is assisted", "{%- set assisted = open and ps == 'VALID' and pa is sameas true -%}", "{%- set assisted = open and ps in ['VALID', 'INVALID'] and pa is sameas true -%}"),
    ("the actionable flag is read as truthy", "and pa is sameas true -%}", "and pa -%}"),
    ("Charge Battery is assisted too", "{%- set assisted = false -%}", "{%- set assisted = open -%}"),
    ("a consumer that reads off adds no code", "(['TIME_LEASES'] if (tl == 'off' and 'TIME_LEASES' not in ns.c) else [])", "[]"),
    ("an inconsistent gate adds no code", "(['GATE_INCONSISTENT'] if incons else [])", "[]"),
    ("an inconsistent gate is not detected", "((g == 'on') != ((gl | length) == 0))", "false"),
    ("the gate's codes are cut at 80", "c[:40]", "c[:80]"),
    ("the gate's codes are not cut", "c[:40]", "c"),
    ("blocked_by drops the gate's codes", "{{ ns.u + ns.c }}", "{{ ns.u }}"),
    ("blocked_by drops the unreadable inputs", "{{ ns.u + ns.c }}", "{{ ns.c }}"),
    ("the unreadable codes lose their prefix", "['UNREADABLE_' ~ code]", "[code]"),
    ("start_allowed copies the gate, not the state", "{{ ok }}", "{{ open }}"),
    ("the time sentence is not first", "{%- set nr = GS['TIME_LEASES'] if tl == 'off' else (GS['GATE_INCONSISTENT'] if incons else", "{%- set nr = GS['GATE_INCONSISTENT'] if incons else (GS['TIME_LEASES'] if tl == 'off' else"),
    ("the unreadable sentence names the last input", "UL[ns.u[0][11:]]", "UL[ns.u[-1][11:]]"),
    ("a sentence says ready while not ready", "{%- else -%}{{ 'Not ready: ' ~ nr }}", "{%- else -%}{{ RS['IDLE'] }}"),
    ("a generic sentence loses its plain words", "{{ 'Not ready: ' ~ nr }}", "{{ nr }}"),
    ("a gate sentence is changed", "The inverter data are not fresh.", "The data are fine."),
    ("a ready sentence is changed", "Nothing is running and the start gate is open.", "Nothing is running."),
    ("the next action when not ready is changed", "Clear the cause named in why; the start gate must read on first.", "Start it."),
    ("the running sentence of Export is changed", "the dongle loop holds the net export target above the latched Stop SOC until the lease ends.", "the dongle loop does something."),
    ("a status family loses a prefix", "'RESTORE BLOCKED', ", ""),
    ("a status family gains the bare word ACTIVE", "'END IGNORED', 'REJECTED', 'START FAILED'", "'END IGNORED', 'REJECTED', 'START FAILED', 'ACTIVE'"),
    ("a verified restore whose record is pending is unknown", "'RESTORE VERIFIED', ", ""),
    ("a restore verify failure is not a fault", "'RESTORE VERIFY ', ", ""),
    ("the restored OK text with a pending record is DONE", "(t.startswith('RESTORED OK - ') and t != 'RESTORED OK - original inverter settings verified')", "false"),
    ("the lease's end time is shown as any text", "ea if edt is not none else", "ea if true else"),
    ("a lease that ends later is shown as none", "('NONE' if ea == 'Inactive'", "('NONE' if true"),
    ("a charge request is shown as a decimal", "(p | round(0) | int) if (p is number and p == p and p >= 0 and p <= 1000000) else 'NOT_READ'", "p"),
    ("the ceiling note fires at any ceiling", "cf is number and cf == 0", "cf is number"),
    ("the ceiling note ignores an unreadable ceiling", "(['IMPORT_CEILING_NOT_READ'] if cr in bad else [])", "[]"),
    ("the failed schedule note is dropped", "(['SCHEDULE_LAST_RUN_FAILED'] if ss == 'FAILED' else [])", "[]"),
    ("the proposal note is dropped", "(['PROPOSAL_NOT_INSTALLED'] if pe in bad else [])", "[]"),
    ("a missing proposal is a state of its own", "'NOT_INSTALLED' if ps in bad", "'NONE' if ps in bad"),
    ("a proposal state it does not know is passed on", "(ps if ps in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD', 'NOT ALLOWED'] else 'UNKNOWN')", "ps"),
    ("the proposal's actionable flag is the coordinator's", "'actionable': st == 'ASSISTED'", "'actionable': pa is sameas true"),
    ("a floor that is not a number is shown", "(pf | round(0) | int) if (pf is number and pf == pf and pf >= 0 and pf <= 100) else none", "pf"),
    ("the re-target message is empty", "'ECCO would end this export; no END guard is installed: press END.'", "''"),
    ("a re-target state it does not know is passed on", "(rs if rs in ['NOT RUNNING', 'UNKNOWN', 'NO CHANGE', 'WAIT', 'ALLOWED', 'END NOW'] else 'UNKNOWN')", "rs"),
    ("a re-target change that is not one of three is passed on", "{%- if k in ['STOP_SOC', 'EXPORT_TARGET', 'END'] -%}", "{%- if true -%}"),
    ("a re-target reason with a number in it is passed on", "{%- if k.isupper() and k.replace('_', '').isalpha() and (k | length) <= 40 -%}", "{%- if true -%}"),
    ("the floor compares with a strict inequality", "('OK' if lvn >= rvn else 'BELOW_RESERVE')", "('OK' if lvn > rvn else 'BELOW_RESERVE')"),
    ("a held_by kind it does not know is passed on", "select('in', ['hold_battery', 'skip_tonight', 'prepare_power_cut'])", "select('string')"),
    ("a hold that cannot be read is shown as clear", "(hs if hs in ['clear', 'held'] else 'NOT_READ')", "(hs if hs == 'held' else 'clear')"),
    ("a limits state it does not know is passed on", "(lim if lim in ['VALID', 'NOT CONFIGURED', 'INVALID', 'AWAITING CONFIRMATION', 'UNKNOWN', 'UNAVAILABLE'] else 'NOT_READ')", "lim"),
    ("the owner shows a live match it does not read", "live_match: NOT_READ", "live_match: MATCH"),
    ("the owner reads the saved profile's live match", "live_match: NOT_READ", "live_match: \"{{ states('sensor.ecco_clock_dongle_ecco_fall" "back_profile_live_match') }}\""),
    ("the owner names a reserved fallback token in its header", "# LIMITS, stated plainly", "# see ecco_" "fallback_profile\n# LIMITS, stated plainly"),
    ("the owner ignores the manual write flag", "('MANUAL_WRITE' if mw == 'on' else 'NONE')", "'NONE'"),
    ("the owner is a lease before a restore owed", "('RESTORE_OWED' if ((fs == 'on' and fa == 'off' and fo == 'off') or (ds == 'on' and da == 'off' and dq == 'off')) else ('CHARGE' if (fa == 'on' or fo == 'on') else",
     "('CHARGE' if (fa == 'on' or fo == 'on') else ('RESTORE_OWED' if ((fs == 'on' and fa == 'off' and fo == 'off') or (ds == 'on' and da == 'off' and dq == 'off')) else"),
    ("the owner does not see the other function's restore owed", " or (ds == 'on' and da == 'off' and dq == 'off')", ""),
    ("two functions at once are not unknown for the owner", "('UNKNOWN' if ((fa == 'on' or fo == 'on') and (da == 'on' or dq == 'on')) else", "("),
    ("an unreadable manual write flag is no owner problem", " or (mw not in ['on', 'off'])", ""),
    # what the package must never contain
    ("the package reads the clock", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}{%- set zz = now() -%}"),
    ("the package reads its own previous state", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}{%- set zz = this.state -%}"),
    ("the package reads a state object", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}{%- set zz = states['sensor.ecco_plan_export_hold'] -%}"),
    ("the package copies the gate's reasons", "{%- set gb = state_attr('binary_sensor.ecco_charge_start_allowed', 'blocked_by') -%}", "{%- set gb = state_attr('binary_sensor.ecco_charge_start_allowed', 'reasons') -%}"),
    ("the package reads a forecast", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}{%- set zz = states('sensor.solcast_pv_forecast_today') -%}"),
    ("the package reads a measurement", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}", "{%- set bad = ['unknown', 'unavailable', 'none', ''] -%}{%- set zz = states('sensor.ecco_house_power') -%}"),
    ("the package reads the schedules consumer", "'binary_sensor.ecco_time_trusted_for_leases'", "'binary_sensor.ecco_time_trusted_for_ha_schedules'"),
    ("the package reads the overall time trust", "'binary_sensor.ecco_time_trusted_for_leases'", "'sensor.ecco_time_trust'"),
    ("the package calls a service", "template:\n", "automation:\n  - alias: x\n    action:\n      - action: button.press\ntemplate:\n"),
    ("the package defines a helper", "template:\n", "input_boolean:\n  ecco_x:\n    name: x\ntemplate:\n"),
    ("the package gains a unit", "        icon: mdi:battery-charging-high\n", "        icon: mdi:battery-charging-high\n        unit_of_measurement: W\n"),
    ("the header no longer says it is display only", "DISPLAY, NEVER A GATE.", "A GATE."),
    ("the header no longer says no package may read it", "NO PACKAGE MAY READ IT", "ANY PACKAGE MAY READ IT"),
    ("the header no longer says the gate is soft", "THE GATES ARE SOFT", "THE GATES ARE FIRM"),
    ("the header no longer says nothing acts on a restored state", "wait 60 s after a start", "may act at once"),
    ("the header no longer says no moving time", "NO LIVE NUMBERS, NO MOVING TIME", "LIVE NUMBERS ARE FINE"),
]


def mutate(text: str, old: str, new: str, label: str = "") -> str | None:
    n = text.count(old)
    if n == 0:
        return None
    if label.startswith("one copy:"):
        i = text.index(old)
        return text[:i] + new + text[i + len(old):]
    return text.replace(old, new)


ONE_COPY_MUTANTS = [
    ("one copy: the Charge state template's open", OPEN, "{%- set open = g == 'on' -%}"),
    ("one copy: a template's unreadable list", "{%- set unk = (ns.u | length) > 0 -%}", "{%- set unk = false -%}"),
    ("one copy: a template's start verdict", OK_LINE, "{%- set ok = true -%}"),
]


def main() -> int:
    print("[0] static")
    sp = static_problems(TEXT)
    check("the file loads with no repeated key; only `template:`; exactly the three sensors with exactly the allowed keys and the attributes of the design; no automation, script, helper, trigger, action, "
          "variables, availability rule, unit or service call; the write vocabulary is absent; the entities it reads are exactly the expected 40 and each exists in the repository; the (entity, attribute) "
          "pairs are exactly the 7 expected; no `this`, no now(), no state object, no time parsed, no forecast, advice or measurement; only the leases consumer and the two gates are named; the rule block "
          "of each sensor is the same text in every template that carries it; every closed sentence, label, note and status prefix is in the file and no sentence has a digit; the gate's codes are exactly "
          "the sentences'; the header states the rules, the closed lists, the lab facts and the limits; ASCII, LF, no site value", sp == [], str(sp[:4]))
    check("the static scans are live: each flags an injected fault (a service call, a helper, a clock, `this`, a state object, a forecast, a measurement, the schedules consumer, another time trust entity, "
          "a copy of the gate's reasons, a unit, a changed rule block, a lost header rule, a site address)",
          all(static_problems(mutate(TEXT, o, n) or TEXT) for _l, o, n in [m for m in MUTANTS if m[0] in (
              "the package calls a service", "the package defines a helper", "the package reads the clock", "the package reads its own previous state", "the package reads a state object",
              "the package reads a forecast", "the package reads a measurement", "the package reads the schedules consumer", "the package reads the overall time trust",
              "the package copies the gate's reasons", "the package gains a unit", "the header no longer says it is display only")])
          and static_problems(TEXT + "# 203.0.113.5\n") and static_problems(TEXT.replace("{%- set unk = (ns.u | length) > 0 -%}", "{%- set unk = false -%}", 1)))
    others_bad = mention_problems(OTHER_TEXT)
    check("no other package mentions the three entities of the read model: it is display, never a gate; and the scan is live (a package that reads one fails it)",
          others_bad == [] and mention_problems({**OTHER_TEXT, "ecco_third.yaml": "state: \"{{ states('sensor.ecco_control_owner') }}\"\n"}) != []
          and mention_problems({**OTHER_TEXT, "ecco_third.yaml": "# sensor.ecco_charge_control_state\n"}) != [] and mention_problems({**OTHER_TEXT, "ecco_third.yaml": "# ecco_export_control_state\n"}) != [], str(others_bad[:3]))
    import ecco_site_render as render  # noqa: E402

    site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
    spots = [m.start() for m in re.finditer(X.DONGLE, TEXT)]
    try:
        rendered, counts = render.render_text(PKG_REL, TEXT, site, render.firmware_actions(ROOT))
    except render.RenderError as exc:
        rendered, counts = "", {"error": str(exc)[:120]}
    check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them for another device slug, touches nothing else and leaves none behind",
          counts == {"entity": len(spots)} and len(spots) >= 20 and X.DONGLE not in rendered and "sensor.site_dongle_free_power_status" in rendered and "switch.site_dongle_dump_to_grid_write_enable" in rendered, str(counts))

    print("[1] inputs")
    ib = inputs_problems()
    check("every input the state needs, one at a time (missing, unavailable, unknown, junk, an unreadable gate list): UNKNOWN, start_allowed false, UNREADABLE_<INPUT> named; every optional input "
          "unreadable: never UNKNOWN; every answer equals the reference and has the properties", ib == [], str(ib[:3]))

    print("[2] table")
    tb = rows_problems()
    check(f"every combination of the three flags of both functions and the manual write flag with a status text of each family, the arm, the scripts and the armed helper, the gates and the time reading in "
          f"every combination, the proposal and the re-target in every state, the hold, the reserve, the latched Stop SOC, the limits, the end-time texts and the numbers: {len(table_rows())} flag rows and "
          f"{len(combo_rows())} more and {len(vocab_rows())} status rows, each equal to the reference with the properties holding", tb == [], str(tb[:3]))

    print("[3] properties")
    n_sweep = 2400
    sw, seen = sweep_problems(n_sweep, 20261127)
    check(f"{n_sweep} seeded random inputs: the template equals the reference on every one, the properties hold on every answer, and every state of both functions was reached "
          f"({sorted(seen)})", sw == [] and set(seen) >= set(X.STATES), str(sw[:3]))
    ones = [(f, c) for f in ("charge", "export") for c in (True,)]
    both_running = 0
    wr = new_world()
    for bits in range(256):
        raw = X.merged({X.FA: "on" if bits & 1 else "off", X.DA: "on" if bits & 2 else "off", X.FT: X.FP_ACTIVE_TEXT if bits & 4 else "Inactive", X.DT: X.DG_ACTIVE_TEXT if bits & 8 else "Inactive",
                        X.FO: "on" if bits & 16 else "off", X.DO: "on" if bits & 32 else "off", X.FS: "on" if bits & 64 else "off", X.DS: "on" if bits & 128 else "off"}, proposal=True)
        apply_raw(wr, raw)
        sn = wr.snapshot()
        if sn[X.CHARGE][0] == "RUNNING" and sn[X.EXPORT][0] == "RUNNING":
            both_running += 1
    check("the two functions never both read RUNNING, whatever the flags and the status texts say (256 combinations of the lease, operation, snapshot flags and the two status texts)", both_running == 0 and ones)

    print("[4] lifecycle")
    lc = lifecycle_problems()
    check("the first state with no input at all (UNKNOWN, never ready, no error); a template reload as the lab measured it (the consumers and gates unavailable for an instant, then OFF with the dip's codes, "
          "then back: never ready while one is off, the cause in words); the read model's own reload gives the same answer; a restart (restored values show what the gate shows, the next render follows); "
          "the time zone changes nothing", lc == [], str(lc[:3]))

    print("[5] rows")
    ch = churn_problems()
    check("the same inputs rendered twice, half an hour of a clock that moves, 60 polls that move the gates' number-bearing reasons and 60 polls that move a running lease's status text: the same "
          "state and attributes and no new row (no moving time, no live number)", ch == [], str(ch[:3]))

    print("[6] vocabulary")
    vb = vocabulary_problems()
    lits = firmware_status_literals()
    check(f"every status text the firmware can publish for the two functions ({len(lits)} literals and {len(FILLED)} formatted ones) lands in exactly one family, the families through the lifecycle are "
          "the reference's, a FAULT text is never ready, and a stale DONE or STARTING text with every flag off is IDLE; the {n} hand-written expectations hold".format(n=len(EXPECTED_FAMILY)), vb == [], str(vb[:3]))
    check("the gate package's codes are exactly the sentences' (every code the gate can name has a plain sentence, and no sentence is left without a code)",
          set(X.GATE_SENTENCES) - {"GATE_INCONSISTENT"} == GATE_PACKAGE_CODES and len(GATE_PACKAGE_CODES) == 24, str(sorted(GATE_PACKAGE_CODES))[:200])

    print("[7] real gate")
    rg = real_gate_problems()
    check("the REAL start gate and the REAL plan helper package feeding the read model: healthy, time off, stale data after 305 s, a Hold battery, Prepare for power cut, a running Dump lease, a restore owed",
          rg == [], str(rg[:3]))

    print("[8] vocabulary of calls")
    decoy = new_world()
    apply_raw(decoy, X.merged(proposal=True))
    base = decoy.snapshot()
    decoy.put("sensor.solcast_pv_forecast_today", "99999")
    decoy.put("sensor.ecco_" "intel_pv_tomorrow", "99999")
    decoy.put("sensor.ecco_" "intel_dump_to_grid", "99999", {"advice": {"stop_soc_pct": 99, "export_kwh": 99}})
    decoy.put("sensor.ecco_house_power", "99999")
    decoy.put(f"sensor.{X.DONGLE}_ecco_battery_soc", "1")
    decoy.put("sensor.ecco_battery_time_to_reserve", "x", {"energy_above_reserve_kwh": 99.0})
    decoy.put("binary_sensor.ecco_time_trusted_for_ha_schedules", "off")
    decoy.put("sensor.ecco_time_trust", "UNTRUSTED")
    decoy.force()
    check("no forecast, advice, measurement or other time trust entity changes anything (decoys with huge values change neither a state nor an attribute), and no write happened anywhere: the services every "
          "world made are none", decoy.snapshot() == base and not decoy.errors and SERVICE_LOG == [] and decoy.w.service_log == [], str(SERVICE_LOG[:2]))

    print("[9] mutation")
    killed, survived, total = 0, [], 0
    for label, old, new in MUTANTS + ONE_COPY_MUTANTS:
        total += 1
        mutated = mutate(TEXT, old, new, label)
        if mutated is None:
            check(f"mutant anchor: {label}", False, "anchor not found")
            continue
        if mutated == TEXT:
            check(f"mutant changes the text: {label}", False, "identical")
            continue
        found = battery(mutated)
        if found:
            killed += 1
            print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
        else:
            survived.append(label)
            FAILURES.append(f"mutant survived: {label}")
            print(f"  FAIL  mutant survived: {label}")
    check(f"{total} mutants (every rule of the state, the readiness, the unreadable inputs, the status families, the closed sentences and lists, the lease, the notes, the proposal, the re-target, the facts, the "
          f"owner, and what the package must never contain): all caught", killed == total and total >= 40, f"{killed}/{total} {survivors_text(survived)}")
    harmless = TEXT.replace("# WHY. Two functions, one spine.", "# WHY, restated. Two functions, one spine.")
    check("a harmless rewrite (a comment) survives the battery, and a rewrite of a rule does not", harmless != TEXT and battery(harmless) == [] and battery(TEXT.replace("(gl | length) == 0 and tl == 'on'", "(gl | length) == 0")) != [])

    print("[10] documents")
    man = yaml.safe_load(MANIFEST_TEXT)
    stanza = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
    check("the deployment manifest lists the package exactly once, to /config/packages, by ssh_file_copy, with restart_required false (a template reload installs it)",
          stanza == [{"source": PKG_REL, "destination": "/config/packages/ecco_control_state.yaml", "method": "ssh_file_copy", "restart_required": False}], str(stanza))
    block = re.search(r"  # Control state - csm1.*?\n  - source: home-assistant/packages/ecco_control_state\.yaml\n    destination: /config/packages/ecco_control_state\.yaml\n    method: ssh_file_copy\n    restart_required: false\n",
                      MANIFEST_TEXT, re.S)
    bf = re.sub(r"\s*\n\s*#\s*", " ", block.group(0)) if block else ""
    check("the manifest stanza carries its comment block (read-only display, nothing installed, three sensors, no service call, nothing may read it, the gates are soft, install = copy and a template reload, "
          "the owner's go, no lease running, what it needs)",
          bool(block) and all(s in bf for s in ("NOT installed, NOT LIVE-PROVEN", "Three template sensors", "display", "no automation, script, helper, trigger or service call", "nothing may read them",
                                                  "THE GATES ARE SOFT", "template entities", "no restart", "needs the owner's go", "NO Dump to Grid or Free Power lease running", "ecco_time_trust.yaml",
                                                  "ecco_start_gate.yaml", "optional", "Delete the file and reload")), bf[:200])
    rflat = flat(README_TEXT)
    sec = README_TEXT.split("## Control state", 1)[1].split("\n## ", 1)[0] if "## Control state" in README_TEXT else ""
    sflat = flat(sec)
    check("the packages README has a Control state section that names the three sensors, says it is a display and never a gate, the states and their order, start_allowed, the closed sentences, the unreadable "
          "inputs, the status families, the one-lease rule, the rows, the lab facts, the notes, the two deliberate pin widenings (D-PIN) and what each lists, the install and csm1",
          all(s in sflat for s in ("`sensor.ecco_charge_control_state`", "`sensor.ecco_export_control_state`", "`sensor.ecco_control_owner`", "display", "never a gate", "UNKNOWN, FAULT, ENDING, RUNNING, ARMED, ASSISTED, PLANNED, IDLE",
                                   "start_allowed", "closed", "UNREADABLE_", "families", "one-lease rule", "no recorder row", "13 to 27 s", "RESTORED", "wait 60 s", "SOFT_GATE", "NO_END_GUARD", "D-PIN",
                                   "READERS", "leases consumer", "export coordinator", "csm1", "template reload", "NOT ESTABLISHED", "reseal")), str([s for s in ("D-PIN", "csm1", "reseal") if s not in sflat]))
    bullet = next((ln for ln in CHANGELOG_TEXT.splitlines() if "ecco_control_state.yaml" in ln), "")
    check("the CHANGELOG has the bullet (control state read model, display only, three sensors, nothing installed, the two deliberate pin widenings)",
          all(s in bullet for s in ("Control state read model", "display", "three template sensors", "nothing installed", "READERS", "D-PIN")), bullet[:120])
    del rflat

    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("\nAll control state checks passed.")
    print("These prove the package against a model of Home Assistant's template entities and an independent reference; nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.")
    return 0


def survivors_text(survived: list) -> str:
    return str(survived[:3])


if __name__ == "__main__":
    sys.exit(main())
