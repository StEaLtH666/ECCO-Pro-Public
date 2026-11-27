"""Test support for the control state read model (home-assistant/packages/ecco_control_state.yaml): ONE virtual Home Assistant that runs the package's REAL template
entities, and an INDEPENDENT reference of the rules written from the specification (not from the templates), so a suite can run both on the same inputs.

The template entities run on the template model of the time trust suite (_time_trust_sim.TrustWorld: dependency tracking, a render at the start of every minute for a
template that uses now(), an availability template that is a super template, attributes parsed natively), on the FPS1 interpreter's state machine and Jinja environment
(_ha_script_sim.py). Both are reused unchanged. This module adds only what the read model needs:

  - the world builder: the healthy input set (nothing running, both gates on), the helpers that put a lease, an operation, a restore owed or a status text into the world,
    and a bulk setter that renders once;
  - the reference: for any set of raw readings the exact state and attributes of the three sensors, with the closed sentences the read model may say;
  - the status vocabulary: the prefix families of the dongle's own texts (the suite reads the firmware's literals and requires each one to land in exactly one family).

Nothing here touches Home Assistant, a dongle or an inverter. There is no service, no action and no write: the model cannot call anything.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import _time_trust_sim as T

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PKG_REL = "home-assistant/packages/ecco_control_state.yaml"

DONGLE = "ecco_clock_dongle"
ZONE = "Europe/London"
START = "2026-11-27 17:00:00"
FMT = "%Y-%m-%d %H:%M:%S"

# ---- the entities the package reads (the repository's own; the generic device slug) ---------------------------------------------------------------------------------------
TL = "binary_sensor.ecco_time_trusted_for_leases"
CG = "binary_sensor.ecco_charge_start_allowed"
EG = "binary_sensor.ecco_export_start_allowed"
FA = f"binary_sensor.{DONGLE}_free_power_active"
FO = f"binary_sensor.{DONGLE}_free_power_operation_in_progress"
FS = f"binary_sensor.{DONGLE}_free_power_snapshot_valid"
DA = f"binary_sensor.{DONGLE}_dump_to_grid_active"
DO = f"binary_sensor.{DONGLE}_dump_to_grid_operation_in_progress"
DS = f"binary_sensor.{DONGLE}_dump_to_grid_snapshot_valid"
MW = f"binary_sensor.{DONGLE}_manual_write_in_progress"
FT = f"sensor.{DONGLE}_free_power_status"
DT = f"sensor.{DONGLE}_dump_to_grid_status"
FE = f"sensor.{DONGLE}_free_power_ends_at"
DE = f"sensor.{DONGLE}_dump_to_grid_ends_at"
FW = f"switch.{DONGLE}_free_power_write_enable"
DW = f"switch.{DONGLE}_dump_to_grid_write_enable"
FSS = "script.ecco_free_power_start_scheduled"
FSG = "script.ecco_free_power_start_guarded"
DSS = "script.ecco_dump_to_grid_start_scheduled"
DSG = "script.ecco_dump_to_grid_start_guarded"
FARM = "input_boolean.ecco_free_power_schedule_armed"
DARM = "input_boolean.ecco_dump_to_grid_schedule_armed"
FSTAT = "sensor.ecco_free_power_schedule_status"
DSTAT = "sensor.ecco_dump_to_grid_schedule_status"
FREQP = f"number.{DONGLE}_free_power_max_charge_power"
FREQD = f"number.{DONGLE}_free_power_duration"
DREQP = f"number.{DONGLE}_dump_to_grid_export_power"
DREQD = f"number.{DONGLE}_dump_to_grid_duration"
DREQS = f"number.{DONGLE}_dump_to_grid_stop_soc"
CEIL = "input_number.ecco_grid_import_ceiling_w"
HOLD = "sensor.ecco_plan_export_hold"
RES = "sensor.ecco_plan_effective_reserve"
LATCHED = f"sensor.{DONGLE}_dump_to_grid_active_stop_soc"
LIM = "sensor.ecco_dump_limits_state"
CAS = "sensor.ecco_dump_ceiling_assessment"
PROP = "sensor.ecco_export_proposal"
P_FLOOR = "sensor.ecco_export_proposal_floor"
P_NET = "sensor.ecco_export_proposal_net_export"
RETG = "sensor.ecco_export_retarget"
LM = f"sensor.{DONGLE}_ecco_fallback_profile_live_match"

# the package's own entities
CHARGE = "sensor.ecco_charge_control_state"
EXPORT = "sensor.ecco_export_control_state"
OWNER = "sensor.ecco_control_owner"
OWN = (CHARGE, EXPORT, OWNER)

BAD = ("unknown", "unavailable", "none", "")
STATES = ("IDLE", "PLANNED", "ARMED", "ASSISTED", "RUNNING", "ENDING", "FAULT", "UNKNOWN")
OWNERS = ("NONE", "CHARGE", "EXPORT", "MANUAL_WRITE", "RESTORE_OWED", "UNKNOWN")

# the statuses of a verified running lease (the firmware's own texts)
FP_ACTIVE_TEXT = "ACTIVE - VERIFIED OK; 155A grid charge; automatic restore armed"
DG_ACTIVE_TEXT = "ACTIVE - VERIFIED OK; target 3000W export - TRACKING - battery ceiling 3800W; Stop SOC 40%"
DONE_TEXT = "RESTORED OK - original inverter settings verified"

# ---- the status families (prefix tables; the order of the tests is the order below) ------------------------------------------------------------------------------------------
FAULT_PREFIXES = ("OPERATOR DECISION REQUIRED", "RECOVERY BLOCKED", "RECOVERY REQUIRED", "RESTORE BLOCKED", "RESTORE WRITE FAILED", "RESTORE VERIFY ",
                  "ACTIVATION VERIFY TIMEOUT", "ACTIVATION VERIFY REFUSED", "ACTIVATION VERIFY ERROR", "END BLOCKED", "FORCE RESTORE REFUSED", "FORCE RESTORE FAILED",
                  "FORCE RESTORE ORIGINAL FAILED", "ACCEPT REFUSED", "ACCEPT FAILED", "REJECTED - RECOVERY BLOCKED", "ACTIVE - reboot recovery pending")
ENDING_PREFIXES = ("RESTORING", "END REQUESTED", "END DEFERRED", "FORCE RESTORE - ", "RESTORE VERIFIED", "RESTORE DEFERRED", "Retrying durable", "RECOVERY RESOLVED - ",
                   "RECOVERY OBLIGATION RESOLVED", "ACTIVATION WRITE FAILED", "ACTIVATION VERIFY FAILED", "FORCE RESTORE ORIGINAL SUCCESS - hardware",
                   "ACCEPT CURRENT STATE SUCCESS - accepted")
STARTING_PREFIXES = ("STARTING", "Snapshot durably committed", "SNAPSHOT DURABLY COMMITTED")
DONE_PREFIXES = ("Inactive", "RECOVERY RESOLVED OK", "FORCE RESTORE ORIGINAL SUCCESS - original", "ACCEPT CURRENT STATE SUCCESS - current", "END IGNORED", "REJECTED", "START FAILED")
RESTORED_PREFIX = "RESTORED OK - "


def family(t: str) -> str:
    """The family of a status text: ACTIVE (a verified running lease), FAULT (needs the owner), ENDING (a restore or an end under way), STARTING, DONE (nothing under way,
    nothing owed by this text) or OTHER (a text this model does not know)."""
    if t.startswith("ACTIVE - VERIFIED OK"):
        return "ACTIVE"
    if t.startswith(FAULT_PREFIXES):
        return "FAULT"
    if t.startswith(ENDING_PREFIXES) or (t.startswith(RESTORED_PREFIX) and t != DONE_TEXT):
        return "ENDING"
    if t.startswith(STARTING_PREFIXES):
        return "STARTING"
    if t.startswith(DONE_PREFIXES) or t == DONE_TEXT:
        return "DONE"
    return "OTHER"


# ---- the closed sentences ----------------------------------------------------------------------------------------------------------------------------------------------
GATE_SENTENCES = {
    "TIME_LEASES": "Time is not trusted for leases: the Home Assistant clock and the dongle clock are not shown to agree.",
    "TIME_SCHEDULES": "Time is not trusted for Home Assistant schedules: the Home Assistant clock is not shown to be right.",
    "TELEMETRY_OFFLINE": "The inverter telemetry is not arriving.",
    "CONFIGURATION_OFFLINE": "The inverter configuration readback is not arriving.",
    "TELEMETRY_STALE": "The inverter data are not fresh.",
    "FREE_POWER_ACTIVE": "A Charge Battery (Free Power) lease is running.",
    "FREE_POWER_OPERATION": "A Charge Battery (Free Power) start or restore is in progress.",
    "FREE_POWER_SNAPSHOT": "A saved Charge Battery (Free Power) snapshot is waiting to be restored.",
    "DUMP_ACTIVE": "An Export to Grid (Dump to Grid) lease is running.",
    "DUMP_OPERATION": "An Export to Grid (Dump to Grid) start or restore is in progress.",
    "DUMP_SNAPSHOT": "A saved Export to Grid (Dump to Grid) snapshot is waiting to be restored.",
    "MANUAL_WRITE": "A manual inverter write is in progress.",
    "OVERRIDE_ACTIVE": "A Hold battery, Skip tonight or Prepare for power cut is active.",
    "OVERRIDE_UNREADABLE": "The override records cannot be read.",
    "RESERVE_UNKNOWN": "The effective reserve cannot be read.",
    "RESERVE_INVALID": "The effective reserve is not a valid percentage.",
    "STOP_SOC_UNREADABLE": "The staged Stop SOC cannot be read.",
    "STOP_SOC_BELOW_RESERVE": "The staged Stop SOC is below the effective reserve.",
    "REVISION_UNREADABLE": "The plan revision cannot be read.",
    "IMPORT_CEILING_UNREADABLE": "The grid import ceiling cannot be read.",
    "IMPORT_CEILING_INVALID": "The grid import ceiling is not a usable value.",
    "IMPORT_UNREADABLE": "The grid import reading cannot be read.",
    "REQUEST_UNREADABLE": "The staged charge request cannot be read.",
    "IMPORT_HEADROOM": "The staged charge request does not fit under the grid import ceiling.",
    "GATE_INCONSISTENT": "The start gate state and its blocked_by list disagree.",
}
UNREADABLE_LABELS = {
    "GATE": "The start gate",
    "TIME": "The time trust reading for leases",
    "ACTIVE": "The lease flag of {lease}",
    "OPERATION": "The operation-in-progress flag of {lease}",
    "SNAPSHOT": "The saved-snapshot flag of {lease}",
    "OTHER_ACTIVE": "The lease flag of {other_lease}",
    "OTHER_OPERATION": "The operation-in-progress flag of {other_lease}",
    "OTHER_SNAPSHOT": "The saved-snapshot flag of {other_lease}",
    "MANUAL_WRITE": "The manual-write flag",
    "WRITE_ENABLE": "The write enable switch of {lease}",
    "START_SCRIPT": "The scheduled start script of {lease}",
    "GUARDED_SCRIPT": "The guarded start script of {lease}",
    "SCHEDULE_ARMED": "The schedule armed helper of {lease}",
    "STATUS": "The status text of {lease} (missing, or not one this model knows)",
}
UNREADABLE_ORDER = ("GATE", "TIME", "ACTIVE", "OPERATION", "SNAPSHOT", "OTHER_ACTIVE", "OTHER_OPERATION", "OTHER_SNAPSHOT", "MANUAL_WRITE", "WRITE_ENABLE", "START_SCRIPT",
                    "GUARDED_SCRIPT", "SCHEDULE_ARMED", "STATUS")
READY_SENTENCES = {
    "IDLE": "Nothing is running and the start gate is open.",
    "PLANNED": "A scheduled start is armed and the start gate is open.",
    "ASSISTED": "ECCO has a valid proposal and the start gate is open.",
}
OTHER_SENTENCES = {
    "ENDING": "The dongle is ending the lease and restoring the saved inverter settings.",
    "ARMED": "A start is under way: the write enable is on or a start script is running.",
    "FAULT_CONFLICT": "Both leases read active at once, which the one-lease rule forbids.",
    "FAULT_TEXT": "The dongle status says a restore or recovery is blocked, failed or waiting for a decision.",
    "FAULT_OWED": "A saved snapshot of the inverter settings is waiting for a restore and nothing is running.",
    "FAULT_UNCONFIRMED": "The lease reads active but the dongle status does not confirm that it is running normally.",
}
RUNNING_SENTENCES = {
    "charge": "Charge Battery is running: the dongle holds the charge rate fixed since the start until the lease ends.",
    "export": "Export to Grid is running: the dongle loop holds the net export target above the latched Stop SOC until the lease ends.",
}
NEXT_SENTENCES = {
    "UNKNOWN": "Wait for the unreadable inputs to return; nothing can be shown as ready until then.",
    "FAULT": "Needs you: read the dongle status text and recover with its End and recovery controls; do not start anything.",
    "ENDING": "Wait for the restore to finish; do not start anything.",
    "RUNNING": "Let it run, or press End and Restore to stop it.",
    "ARMED": "Wait for the start to finish, or switch the write enable off.",
    "NOT_READY": "Clear the cause named in why; the start gate must read on first.",
    "ASSISTED": "Start it with the guarded Start when you want it: one press.",
    "PLANNED": "Nothing to do: the scheduled start runs at its time; cancel the schedule to stop it.",
    "IDLE": "Start it when you want, or arm a schedule.",
}
OWNER_NOTES = {
    "NONE": "No lease and no manual write holds the inverter settings. Only the firmware refusal keeps two functions apart; a persisted owner needs a later firmware step.",
    "CHARGE": "Charge Battery (Free Power) holds the inverter settings; the firmware refuses Export to Grid while it does.",
    "EXPORT": "Export to Grid (Dump to Grid) holds the inverter settings; the firmware refuses Charge Battery while it does.",
    "MANUAL_WRITE": "A manual inverter write holds the inverter write mutex; the firmware refuses a lease start while it does.",
    "RESTORE_OWED": "A saved snapshot of the inverter settings is waiting for a restore: the owner has to see it through before anything starts.",
    "UNKNOWN": "A flag cannot be read, or both functions claim the inverter settings at once: nobody is shown as the owner.",
}
END_NOW_MESSAGE = "ECCO would end this export; no END guard is installed: press END."
LIVE_MATCH_VALUES = ("MATCH", "DRIFT", "NO_PROFILE", "PAUSED", "PAUSED_IO", "OUT_OF_DOMAIN", "EXPORT", "CONTEXT")
HELD_KINDS = ("hold_battery", "skip_tonight", "prepare_power_cut")
PROPOSAL_STATES = ("VALID", "INVALID", "UNVERIFIED", "HOLD", "NOT ALLOWED")
RETARGET_STATES = ("NOT RUNNING", "UNKNOWN", "NO CHANGE", "WAIT", "ALLOWED", "END NOW")
CHANGE_KINDS = ("STOP_SOC", "EXPORT_TARGET", "END")
LIMITS_VALUES = ("VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION", "UNKNOWN", "UNAVAILABLE")
CEILING_VALUES = ("ABOVE PROVEN LEVEL", "AT PROVEN LEVEL", "BELOW PROVEN LEVEL", "UNAVAILABLE")

# the wiring of this base, which the notes say (each slice that binds a path removes its note in its own commit)
NOTES_CHARGE = ("SOFT_GATE", "CARD_START_NOT_GATED", "SCHEDULE_NOT_GATED", "RATE_FIXED_AT_START", "NO_TARGET_REACHED_END")
NOTES_EXPORT = ("SOFT_GATE", "GUARDED_START_NOT_GATED", "SCHEDULE_NOT_GATED", "NO_END_GUARD")

FUNCS = {
    "charge": dict(label="Charge Battery", lease="Free Power", other_lease="Dump to Grid", sensor=CHARGE, gate=CG, a=FA, o=FO, s=FS, xa=DA, xo=DO, xs=DS, status=FT, ends=FE,
                   arm=FW, sched=FSS, guard=FSG, armed=FARM, sstat=FSTAT),
    "export": dict(label="Export to Grid", lease="Dump to Grid", other_lease="Free Power", sensor=EXPORT, gate=EG, a=DA, o=DO, s=DS, xa=FA, xo=FO, xs=FS, status=DT, ends=DE,
                   arm=DW, sched=DSS, guard=DSG, armed=DARM, sstat=DSTAT),
}

# ---- the healthy world: nothing runs, both gates read on, the time is trusted --------------------------------------------------------------------------------------------
OPEN_GATE = ("on", {"blocked_by": [], "reasons": ["ALLOWED: every check passed"]})
HEALTHY: dict = {
    TL: "on", CG: OPEN_GATE, EG: OPEN_GATE,
    FA: "off", FO: "off", FS: "off", DA: "off", DO: "off", DS: "off", MW: "off",
    FT: "Inactive", DT: "Inactive", FE: "Inactive", DE: "Inactive", FW: "off", DW: "off",
    FSS: "off", FSG: "off", DSS: "off", DSG: "off", FARM: "off", DARM: "off", FSTAT: "IDLE", DSTAT: "IDLE",
    FREQP: "4000.0", FREQD: "60.0", DREQP: "3000.0", DREQD: "60.0", DREQS: "40.0",
    CEIL: "0.0", HOLD: ("clear", {"held_by": ""}), RES: "40", LATCHED: "unknown", LIM: "VALID", CAS: "BELOW PROVEN LEVEL",
    RETG: ("NOT RUNNING", {"reasons": [], "changes": []}),
    LM: "FB-B3;m=MATCH;ca=F;obl=-;eh=U",
}
# the export coordinator's sensors are NOT in the healthy set: a house without it must read cleanly ("proposal not installed")
PROPOSAL_VALID = {PROP: ("VALID", {"actionable": True, "blocked_by": []}), P_FLOOR: "40", P_NET: "3000"}


def split(v) -> tuple:
    """A world value is a state text, or (state, attributes)."""
    if isinstance(v, tuple):
        return str(v[0]), dict(v[1])
    return str(v), {}


class CtlMixin:
    """The helpers every world of the read model has (a TrustWorld of its own, or the template model adopted on another world's state machine)."""

    def bulk(self, mapping: dict) -> None:
        """Set many entities and render ONCE (a poll that changes several readings together). A value of None removes the entity (it does not exist)."""
        saved = list(self.w.listeners)
        self.w.listeners[:] = [fn for fn in saved if getattr(fn, "__self__", None) is not self]
        try:
            for eid, v in mapping.items():
                if v is None:
                    self.w.states.pop(eid, None)
                    self.pending.add(eid)
                else:
                    st, attrs = split(v)
                    self.w.set(eid, st, dict(attrs) or dict(T._MARK))
        finally:
            self.w.listeners[:] = saved
        self.force()

    def set1(self, eid: str, v) -> None:
        self.bulk({eid: v})

    def snapshot(self) -> dict:
        """The state and attributes of the three sensors, as a consumer reads them."""
        return {eid: (self.state(eid), {k: v for k, v in self.w.states.get(eid, ("unknown", {}))[1].items() if k != "_model"}) for eid in OWN}

    def rows(self) -> dict:
        """How many state or attribute changes each sensor has made so far (what the recorder would write)."""
        out: dict = {}
        for _t, eid, _s in self.w.history:
            if eid in OWN:
                out[eid] = out.get(eid, 0) + 1
        return out

    def lease(self, fn: str, *, text: str | None = None, ends: str = "2026-11-27 18:00:00", snapshot: bool = True) -> None:
        """A verified lease of `fn` is running (both gates read closed with the code the firmware's flag gives)."""
        F = FUNCS[fn]
        closed = ("off", {"blocked_by": ["FREE_POWER_ACTIVE" if fn == "charge" else "DUMP_ACTIVE"], "reasons": ["x"]})
        self.bulk({F["a"]: "on", F["s"]: "on" if snapshot else "off", F["status"]: text or (FP_ACTIVE_TEXT if fn == "charge" else DG_ACTIVE_TEXT), F["ends"]: ends, CG: closed, EG: closed})

    def end_lease(self, fn: str) -> None:
        F = FUNCS[fn]
        self.bulk({F["a"]: "off", F["s"]: "off", F["status"]: DONE_TEXT, F["ends"]: "Inactive", CG: OPEN_GATE, EG: OPEN_GATE})


class CtlWorld(CtlMixin, T.TrustWorld):
    """The package's template entities on one virtual Home Assistant."""

    def __init__(self, package_text: str | None = None, *, start: str = START, zone: str = ZONE, healthy: bool = True, restore=None, preload: dict | None = None):
        self.package_text = package_text if package_text is not None else (ROOT / PKG_REL).read_text(encoding="utf-8")
        super().__init__(self.package_text, start=start, zone=zone, restore=restore, preload=preload)
        if healthy:
            self.bulk(HEALTHY)


# ===========================================================================================================================
# THE INDEPENDENT REFERENCE: the rules written from the specification, in Python, with no template in sight
# ===========================================================================================================================
def _state(raw: dict, eid: str) -> str:
    v = raw.get(eid)
    return "unknown" if v is None else split(v)[0]


def _attr(raw: dict, eid: str, name: str):
    v = raw.get(eid)
    return None if v is None else split(v)[1].get(name)


def _num(raw: dict, eid: str):
    """A reading as a float, or None (unknown, text, ...): the float(none) filter."""
    s = _state(raw, eid)
    try:
        return float(str(s).strip())
    except ValueError:
        return None


def _int_in(x, lo, hi):
    """A rounded whole number when x is a number inside [lo, hi] (nan fails every comparison), else None."""
    if x is None or x != x or x < lo or x > hi:
        return None
    return int(round(x))


def _list_of(v):
    """`(v | list) if (v is iterable and v is not string and v is not mapping) else none`."""
    if isinstance(v, (list, tuple, set, frozenset)):
        return list(v)
    return None


def _strings(items) -> list:
    return [c[:40] for c in (items or []) if isinstance(c, str)]


def function_rules(raw: dict, fn: str) -> dict:
    """Everything the read model decides for one function (charge or export): the unreadable inputs, the gate codes, the lifecycle state and the readiness."""
    F = FUNCS[fn]
    g = _state(raw, F["gate"])
    gl = _list_of(_attr(raw, F["gate"], "blocked_by"))
    tl = _state(raw, TL)
    la, lo, ls = (_state(raw, F[k]) for k in ("a", "o", "s"))
    ya, yo, ys = (_state(raw, F[k]) for k in ("xa", "xo", "xs"))
    mw = _state(raw, MW)
    t = _state(raw, F["status"])
    ar, sc, gd, sa = (_state(raw, F[k]) for k in ("arm", "sched", "guard", "armed"))
    fam = family(t)
    unreadable: list = []
    if g not in ("on", "off") or gl is None:
        unreadable.append("GATE")
    for code, v in (("TIME", tl), ("ACTIVE", la), ("OPERATION", lo), ("SNAPSHOT", ls), ("OTHER_ACTIVE", ya), ("OTHER_OPERATION", yo), ("OTHER_SNAPSHOT", ys), ("MANUAL_WRITE", mw),
                    ("WRITE_ENABLE", ar), ("START_SCRIPT", sc), ("GUARDED_SCRIPT", gd), ("SCHEDULE_ARMED", sa)):
        if v not in ("on", "off"):
            unreadable.append(code)
    if t in BAD or fam == "OTHER":
        unreadable.append("STATUS")
    codes = _strings(gl)
    incons = g in ("on", "off") and gl is not None and ((g == "on") != (len(gl) == 0))
    if tl == "off" and "TIME_LEASES" not in codes:
        codes.append("TIME_LEASES")
    if incons:
        codes.append("GATE_INCONSISTENT")
    unk = bool(unreadable)
    open_ = g == "on" and gl is not None and len(gl) == 0 and tl == "on"
    conflict = la == "on" and ya == "on"
    owed = ls == "on" and la == "off" and lo == "off"
    assisted = False
    if fn == "export":
        assisted = open_ and _state(raw, PROP) == "VALID" and _attr(raw, PROP, "actionable") is True
    if unk:
        st = "UNKNOWN"
    elif conflict or fam == "FAULT" or owed:
        st = "FAULT"
    elif lo == "on" and fam == "STARTING":
        st = "ARMED"
    elif lo == "on":
        st = "ENDING"
    elif la == "on":
        st = {"ACTIVE": "RUNNING", "ENDING": "ENDING", "STARTING": "ARMED"}.get(fam, "FAULT")
    elif ar == "on" or sc == "on" or gd == "on":
        st = "ARMED"
    elif assisted:
        st = "ASSISTED"
    elif sa == "on":
        st = "PLANNED"
    else:
        st = "IDLE"
    ok = open_ and st in ("IDLE", "PLANNED", "ASSISTED")
    return dict(g=g, gl=gl, tl=tl, fam=fam, unreadable=unreadable, codes=codes, incons=incons, unk=unk, open=open_, conflict=conflict, owed=owed, st=st, ok=ok, la=la)


def why_of(fn: str, r: dict) -> str:
    F = FUNCS[fn]
    if r["unk"]:
        label = UNREADABLE_LABELS[r["unreadable"][0]].format(lease=F["lease"], other_lease=F["other_lease"])
        return label + " cannot be read, so nothing is shown as ready."
    if r["conflict"]:
        return OTHER_SENTENCES["FAULT_CONFLICT"]
    if r["fam"] == "FAULT":
        return OTHER_SENTENCES["FAULT_TEXT"]
    if r["owed"]:
        return OTHER_SENTENCES["FAULT_OWED"]
    if r["st"] == "FAULT":
        return OTHER_SENTENCES["FAULT_UNCONFIRMED"]
    if r["st"] == "RUNNING":
        return RUNNING_SENTENCES[fn]
    if r["st"] in ("ENDING", "ARMED"):
        return OTHER_SENTENCES[r["st"]]
    if r["ok"]:
        return READY_SENTENCES[r["st"]]
    code0 = r["codes"][0] if r["codes"] else ""
    if r["tl"] == "off":
        nr = GATE_SENTENCES["TIME_LEASES"]
    elif r["incons"]:
        nr = GATE_SENTENCES["GATE_INCONSISTENT"]
    elif code0 in GATE_SENTENCES:
        nr = GATE_SENTENCES[code0]
    else:
        nr = "the start gate is closed (" + code0 + ")."
    return "Not ready: " + nr


def next_of(r: dict) -> str:
    st = r["st"]
    if st in ("UNKNOWN", "FAULT", "ENDING", "RUNNING", "ARMED"):
        return NEXT_SENTENCES[st]
    if not r["ok"]:
        return NEXT_SENTENCES["NOT_READY"]
    return NEXT_SENTENCES[st]


def lease_of(raw: dict, fn: str) -> dict:
    F = FUNCS[fn]
    ea = _state(raw, F["ends"])
    try:
        datetime.strptime(ea, FMT)
        valid = ea not in BAD
    except ValueError:
        valid = False
    ends = ea if valid else ("NONE" if ea == "Inactive" else ("UNAVAILABLE" if ea.startswith("Active - end time") else "NOT_READ"))
    if fn == "charge":
        return {"ends_at": ends, "power_w": _int_in(_num(raw, FREQP), 0, 1000000) if _int_in(_num(raw, FREQP), 0, 1000000) is not None else "NOT_READ",
                "duration_min": _int_in(_num(raw, FREQD), 0, 1000000) if _int_in(_num(raw, FREQD), 0, 1000000) is not None else "NOT_READ"}
    pw, dm, sp = _int_in(_num(raw, DREQP), 0, 1000000), _int_in(_num(raw, DREQD), 0, 1000000), _int_in(_num(raw, DREQS), 0, 100)
    return {"ends_at": ends, "export_w": "NOT_READ" if pw is None else pw, "duration_min": "NOT_READ" if dm is None else dm, "stop_soc": "NOT_READ" if sp is None else sp}


def notes_of(raw: dict, fn: str) -> list:
    F = FUNCS[fn]
    ss = _state(raw, F["sstat"])
    if fn == "charge":
        cr = _state(raw, CEIL)
        cf = _num(raw, CEIL)
        notes = list(NOTES_CHARGE)
        if cr not in BAD and cf is not None and cf == 0:
            notes.append("IMPORT_NOT_CONFIGURED")
        if cr in BAD:
            notes.append("IMPORT_CEILING_NOT_READ")
    else:
        notes = list(NOTES_EXPORT)
        if _state(raw, PROP) in BAD:
            notes.append("PROPOSAL_NOT_INSTALLED")
    if ss == "FAILED":
        notes.append("SCHEDULE_LAST_RUN_FAILED")
    return notes


def proposal_of(raw: dict, r: dict) -> dict:
    ps0 = _state(raw, PROP)
    pstate = "NOT_INSTALLED" if ps0 in BAD else (ps0 if ps0 in PROPOSAL_STATES else "UNKNOWN")
    pb = _list_of(_attr(raw, PROP, "blocked_by"))
    return {"state": pstate, "actionable": r["st"] == "ASSISTED", "blocked_by": _strings(pb), "floor_pct": _int_in(_num(raw, P_FLOOR), 0, 100), "net_export_w": _int_in(_num(raw, P_NET), 0, 30000)}


def retarget_of(raw: dict) -> dict:
    rs = _state(raw, RETG)
    rstate = "NOT_INSTALLED" if rs in BAD else (rs if rs in RETARGET_STATES else "UNKNOWN")
    codes, kinds = [], []
    for x in (_list_of(_attr(raw, RETG, "reasons")) or []):
        if isinstance(x, str):
            k = x.split(":")[0]
            if k.isupper() and k.replace("_", "").isalpha() and len(k) <= 40:
                codes.append(k)
    for x in (_list_of(_attr(raw, RETG, "changes")) or []):
        if isinstance(x, str):
            k = x.split(" ")[0]
            if k in CHANGE_KINDS:
                kinds.append(k)
    return {"state": rstate, "changes": kinds, "codes": codes, "message": END_NOW_MESSAGE if rstate == "END NOW" else ""}


def facts_of(raw: dict) -> dict:
    hs = _state(raw, HOLD)
    hb = _attr(raw, HOLD, "held_by")
    rvn = _int_in(_num(raw, RES), 0, 100)
    lvn = _int_in(_num(raw, LATCHED), 0, 100)
    la = _state(raw, DA)
    lim, cas = _state(raw, LIM), _state(raw, CAS)
    if la == "off":
        floor = "NO_LEASE"
    elif lvn is None or rvn is None:
        floor = "NOT_READ"
    else:
        floor = "OK" if lvn >= rvn else "BELOW_RESERVE"
    return {"hold": hs if hs in ("clear", "held") else "NOT_READ", "held_by": [x for x in hb.split(",") if x in HELD_KINDS] if isinstance(hb, str) else [],
            "reserve_pct": "NOT_READ" if rvn is None else rvn, "stop_soc_latched": "NONE" if la == "off" else ("NOT_READ" if lvn is None else lvn), "floor": floor,
            "limits": lim if lim in LIMITS_VALUES else "NOT_READ", "ceiling": cas if cas in CEILING_VALUES else "NOT_READ"}


def owner_of(raw: dict) -> tuple:
    fa, fo, fs = (_state(raw, e) for e in (FA, FO, FS))
    da, dq, ds = (_state(raw, e) for e in (DA, DO, DS))
    mw = _state(raw, MW)
    unk = any(v not in ("on", "off") for v in (fa, fo, fs, da, dq, ds, mw))
    if unk or ((fa == "on" or fo == "on") and (da == "on" or dq == "on")):
        own = "UNKNOWN"
    elif (fs == "on" and fa == "off" and fo == "off") or (ds == "on" and da == "off" and dq == "off"):
        own = "RESTORE_OWED"
    elif fa == "on" or fo == "on":
        own = "CHARGE"
    elif da == "on" or dq == "on":
        own = "EXPORT"
    elif mw == "on":
        own = "MANUAL_WRITE"
    else:
        own = "NONE"
    lm = _state(raw, LM)
    mm = lm.split("m=")[1].split(";")[0] if "m=" in lm else "UNKNOWN"
    live = "NOT_READ" if lm in BAD else (mm if mm in LIVE_MATCH_VALUES else "UNKNOWN")
    return own, {"live_match": live, "note": OWNER_NOTES[own]}


def reference(raw: dict) -> dict:
    """The state and every attribute the three sensors must publish for these raw readings (entity id -> state text or (state, attributes); a missing key is an entity that
    does not exist): {entity id: (state, attributes)}."""
    out = {}
    for fn in ("charge", "export"):
        F = FUNCS[fn]
        r = function_rules(raw, fn)
        attrs = {"why": why_of(fn, r), "next_action": next_of(r), "blocked_by": ["UNREADABLE_" + c for c in r["unreadable"]] + r["codes"], "start_allowed": r["ok"],
                 "start_path": "GUARDED_SCRIPT", "end_path": "END_BUTTON", "lease": lease_of(raw, fn), "notes": notes_of(raw, fn)}
        if fn == "export":
            attrs["proposal"] = proposal_of(raw, r)
            attrs["retarget"] = retarget_of(raw)
            attrs["facts"] = facts_of(raw)
        out[F["sensor"]] = (r["st"], attrs)
    own, oattrs = owner_of(raw)
    out[OWNER] = (own, oattrs)
    return out


def merged(overrides: dict | None = None, *, proposal: bool = False) -> dict:
    """The healthy raw readings with `overrides` on top (a None removes the entity)."""
    raw = dict(HEALTHY)
    if proposal:
        raw.update(PROPOSAL_VALID)
    for k, v in (overrides or {}).items():
        if v is None:
            raw.pop(k, None)
        else:
            raw[k] = v
    return raw
