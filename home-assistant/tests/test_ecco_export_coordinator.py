"""Offline suite for the EXPORT COORDINATOR v0 (item N3 of the architecture reconciliation):

  home-assistant/packages/ecco_export_coordinator.yaml     nine template sensors and nothing else: a proposal for Export to Grid (the Stop SOC floor, the usable energy, the expected
                                                           battery power, the net export target, the duration, a state with its reasons), the re-target shadow and the shadow comparison

A READ-ONLY SHADOW: no automation, script, helper, trigger, action or service call. This suite proves the REAL package YAML against a model of Home Assistant's template entities
(home-assistant/tests/_export_coordinator_sim.py, on the template model of the time trust suite and the FPS1 interpreter, which it reuses unchanged, plus `this`) and against an
INDEPENDENT reference of the rules written from the specification. Nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.

  [0] static      the file loads with no repeated key; only `template:`; the nine entities and nothing else; the write vocabulary (no service, action, trigger, helper, script or
                  automation); the exact set of entities it reads, every one of them existing in the repository, and the exact set of (entity, attribute) pairs, state objects and `this`
                  reads; NO forecast entity; of the start gate and the time trust packages exactly two entities are mentioned, whole and with their domain (the Export start gate and the leases
                  consumer: both packages pin their readers, widened for this one deliberately, design decision D-PIN) and nothing else of either; the header states the rules, the constants and
                  the limits and the constants equal the templates'; ASCII, LF, no site value; the site renderer; the eight lookups repeat one identical two-line check
  [1] inputs      every input one at a time (missing, unavailable, unknown, empty, text, nan, infinite, negative, out of range, huge) and at each boundary: always INVALID, the cause named
                  with the entity, every numeric sensor unavailable and never 0; the poll freshness boundaries and the clock-driven re-render; the dongle's limits, the plan hold; the Export
                  schedule's window (its start unreadable, the time left in it, every boundary of the schedule's own rounding); a PV surplus the target cannot hold
  [2] maths       the floor is the maximum of its members (every member in turn, the rounding up of the reserve; the dongle's staged Stop SOC is NOT one), the energy (the margin, the
                  efficiency, the measured capacity, never negative), the net export target against the export limit, the expected power (measured PV only, the clamps, the lower floor that
                  keeps the division defined), the duration (rounded down, the schedule's window and the time left in it, the minimum worth starting), UNVERIFIED above the proven level and
                  the loop figures beside it; hand-computed anchors; the template against the reference
  [3] sweep       seeded random inputs, thousands of cases: the template equals the reference on every one, and no VALID proposal ever has a floor below the reserve or the Stop SOC request, a
                  power above the ceiling or the proven level, a duration beyond the window or the time left in it or below the minimum, an energy below 0, an infeasible PV surplus, or a
                  number while it is not VALID or UNVERIFIED
  [1b] gate       the Export start gate and the leases consumer, read as far as the pins allow (slice S-A2): a VALID proposal that the gate does not allow is NOT ALLOWED and names the gate's own codes (GATE_UNREADABLE,
                  GATE_INCONSISTENT, GATE_SETTLING), `actionable` is true only for a VALID proposal with the gate open for 60 s, the re-target is ALLOWED only while the consumer reads on for 60 s (WAIT with
                  TIME_NOT_TRUSTED), a restart shows young restored values and a reload keeps nothing; and the model publishes NOTHING with unchanged inputs (no per-render time: D-C04a route a)
  [4] shadow      while a lease runs: the comparison and the re-target for a lease the schedule started (the 30 minute rules, the deadbands, the memory of the previous would-change and its age
                  across a template reload and a restart, the four spellings of `this`, a clock that moved, a previous would-change in the future), a lease the schedule did not start, the
                  window-limited, late-start, 60 minute manual and full-window leases, END NOW, an end time in a skipped or a repeated hour, the churn of the published states; the TAIL OF
                  THE WINDOW (a run pressed in the first 20 s of its window rendered at every second to its own end, a lease that ends 100 s after the window end) and the schedule's helpers edited while
                  a lease runs: a running lease gets no time past its window and a lease the schedule started none past its own end plus the schedule's 20 s, at every render; against the reference
  [5] lookups     the model unreadable: every lookup withholds everything and says MODEL_UNREADABLE (the model carries no time of its evaluation, so no age is judged); every attribute
                  reads its own key; NOT ALLOWED and `actionable` are passed on
  [6] plan        the REAL plan helper package feeding the coordinator (a Hold battery, Skip tonight, Prepare for power cut, a reserve that rises), also during a lease
  [7] vocabulary  no service call was ever made by any world above
  [8] mutation    in-memory mutants of the package (every comparison, clamp, ordering, default, availability guard and the forecast ban, the window, the bound of a running lease, the origin, the memory, END NOW),
                  each caught
  [9] documents   the manifest, the README and the CHANGELOG say the same

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import math
import random
import re
import sys
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _export_coordinator_sim as X  # noqa: E402

PKGS = ROOT / "home-assistant" / "packages"
PKG_REL = X.PKG_REL
TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
RAW = (ROOT / PKG_REL).read_bytes()
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
README_TEXT = (PKGS / "README.md").read_text(encoding="utf-8")
CHANGELOG_TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
PLAN_TEXT = (PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8")

GATE_AGES = (600.0, 600.0)    # how long the Export start gate and the leases consumer have read on in the ordinary row: long enough (the hold-off is 60 s)
PIN_LITERALS = True           # a development switch: False shows which mutants only the literal pins kill (the behaviour tests alone must kill them too)
FAILURES: list[str] = []
SERVICE_LOG: list = []        # every service call any world below made (the model cannot make one; a suite requires it empty)

ZONE = ZoneInfo(X.ZONE)
T0 = datetime.strptime(X.START, X.FMT).replace(tzinfo=ZONE).timestamp()


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def text_at(epoch: float, zone: ZoneInfo = ZONE) -> str:
    """The local text (the form of the dongle's and the helpers' times) of an epoch."""
    return datetime.fromtimestamp(epoch, zone).strftime(X.FMT)


def started_ago(seconds: float, now: float = T0) -> str:
    """The Export schedule's start helper text for a window that began `seconds` before `now`."""
    return text_at(now - seconds)


# ===========================================================================================================================
# names
# ===========================================================================================================================
DONGLE = X.DONGLE
OWN_IDS = set(X.OWN)
EXPECTED_READS = {X.SOC, X.LOAD, X.PV, X.GRID, X.CAP, X.CAPM, X.HOLD, X.RESERVE, X.STOP_S, X.TGT, X.WIN, X.SCH_START, X.SCRIPT, X.PCEIL, X.PROV, X.MX, X.LIM, X.TEL, X.POLL, X.LEASE,
                  X.L_STOP, X.L_EXP, X.L_CMD, X.L_END, X.MODEL, X.EG, X.TL}
# the exact (entity, attribute) pairs read through state_attr, the state objects read through states['...'] (for last_changed) and what `this` is used for: nothing else (a pin by entity
# id alone would let a forecast or an estimate in through an attribute of an entity that is allowed)
EXPECTED_STATE_ATTRS = {(X.CAPM, "capacity_kwh"), (X.CAPM, "capacity_basis"), (X.HOLD, "held_by"), (X.SCRIPT, "last_triggered"), (X.MODEL, "model"), (X.EG, "blocked_by")}
EXPECTED_STATE_OBJECTS = {X.LEASE, X.EG, X.TL}
EXPECTED_THIS_ATTRS = {"model"}
STATE_ATTR_RE = re.compile(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")
STATES_OBJ_RE = re.compile(r"states\[\s*'([^']+)'\s*\]")
THIS_RE = re.compile(r"\bthis\b(?: is defined| is not none|\.attributes\.get\('([a-z_]+)'\))")
FORBIDDEN_FORECAST = re.compile(r"forecast|solcast|predict|pv_tomorrow|estimate|intel_", re.I)
PINNED_NAMES = ("ecco_charge_start_allowed", "ecco_start_bypass")   # the packages that pin who may mention them: this one never does
ALLOWED_WHOLE = ("binary_sensor.ecco_export_start_allowed", "binary_sensor.ecco_time_trusted_for_leases")   # the only two entities of those packages it may mention, whole, with their domain (D-PIN)
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_text|input_number|input_boolean|input_datetime|number|script|button|switch|select|automation|light|climate)\.[a-z0-9_]+")
BAD_RAW = (None, "unknown", "unavailable", "", "none", "abc", "nan", "inf", "-inf", "1e999", "-1e999", "1e12", "-5", "True")
CODE_OF = {X.SOC: "SOC_UNREADABLE", X.LOAD: "HOUSE_LOAD_UNREADABLE", X.PV: "PV_UNREADABLE", X.GRID: "GRID_UNREADABLE", X.CAP: "CAPACITY_UNREADABLE",
           X.STOP_S: "STOP_SOC_SCHEDULE_UNREADABLE", X.TGT: "SCHEDULE_POWER_UNREADABLE", X.WIN: "SCHEDULE_DURATION_UNREADABLE", X.SCH_START: "SCHEDULE_START_UNREADABLE",
           X.PCEIL: "CEILING_UNREADABLE", X.PROV: "PROVEN_UNREADABLE", X.MX: "EXPORT_LIMIT_UNREADABLE"}
RANGE_OF = {X.SOC: (0, 100), X.LOAD: (0, 30000), X.PV: (0, 30000), X.GRID: (-30000, 30000), X.CAP: (1, 1000), X.STOP_S: (0, 100), X.TGT: (1, 30000),
            X.WIN: (1, 240), X.PCEIL: (500, 30000), X.PROV: (500, 30000), X.MX: (0, 30000)}
CONSTANT_PINS = (("MAX_TELEMETRY_AGE_S = 90", "<= 90"), ("DONGLE_STOP_SOC_MIN = 10", "reserve, 10, (l_stop"), ("DONGLE_STOP_SOC_MAX = 90", "floor > 90"),
                 ("DISCHARGE_EFFICIENCY = 0.90", "* cap * 0.90"), ("SOC_MARGIN_POINTS = 1", "soc - floor - 1"), ("MIN_COMMAND_W = 500", "[p_q, 500] | max"),
                 ("MIN_COMMAND_W = 500", "[lp_q, 500] | max"), ("POWER_STEP_W = 500", "(p / 500) | round(0, 'ceil')"), ("POWER_STEP_W = 500", "(lp / 500) | round(0, 'ceil')"),
                 ("POWER_STEP_W = 500", "(raw_p / 500) | round(0, 'ceil')"), ("DURATION_STEP_MIN = 5", "(dur / 5) | round(0, 'floor')"), ("DURATION_STEP_MIN = 5", "(ldur / 5) | round(0, 'floor')"), ("MIN_COMMAND_W = 500", "(surplus + 500) > nstart"),
                 ("EXPORT_HEADROOM", "[100, 0.03 * mx]"), ("MIN_TARGET_W = 500", "net < 500"), ("MIN_DURATION_MIN = 10", "dur < 10"),
                 ("INFEASIBLE_LOW_DEADBAND_W = 150", "raw_p < -150"), ("WINDOW_END_ROUNDING_S = 20", "(w_end - now_ts + 20) / 60"), ("WINDOW_END_ROUNDING_S = 20", "(run_end - now_ts + 20) / 60"),
                 ("RETARGET_MIN_AGE_S = 1800", "age < 1800"), ("RETARGET_MIN_GAP_S = 1800", "(now_ts - prev_entry) < 1800"), ("RETARGET_MIN_GAP_S = 1800", "mem_age < 1800 or not time_ok)"),
                 ("RETARGET_STOP_DEADBAND = 1", "d_stop >= 1"), ("RETARGET_EXPORT_DEADBAND_W = 200", "(d_exp | abs) >= 200"), ("RETARGET_END_DEADBAND_MIN = 20", "d_end >= 20"),
                 ("RETARGET_END_DEADBAND_MIN = 20", "dev_stop or dev_exp or dev_end"),     # the END rule cannot fire for a lease the schedule started (its end is bounded): the pins keep it, behaviour cannot reach it
                 ("ORIGIN_RUN_WINDOW_S = 900", "since_run <= 900"), ("ORIGIN_RUN_TOLERANCE_S = 10", "since_run >= -10"), ("ORIGIN_WINDOW_START_TOLERANCE_S = 60", "l_start_ts >= w_start - 60"),
                 ("ORIGIN_WINDOW_END_TOLERANCE_S = 120", "l_end_ts <= w_end + 120"), ("PHYSICAL_MAX_W = 30000", "0, 30000)"),
                 ("GATE_SETTLE_S = 60", "eg_age >= 60"), ("GATE_SETTLE_S = 60", "tl_age >= 60"))
HEADER_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "READ-ONLY SHADOW", "no automation, no script, no helper", "no service call", "ONLY THE CONTROL STATE READ MODEL",
               "THE HOME ASSISTANT GATES ARE SOFT", "Start button", "A VALID proposal is not permission to start", "THE START GATE AND THE TIME TRUST INPUT ARE READ HERE, ONLY AS FAR AS THE PINS ALLOW",
               "READERS allow-list", "design decision D-PIN", "binary_sensor.ecco_export_start_allowed", "binary_sensor.ecco_time_trusted_for_leases (the leases consumer ONLY)", "NOT ALLOWED", "actionable",
               "GATE_SETTLE_S = 60", "GATE_SETTLING", "GATE_UNREADABLE", "GATE_INCONSISTENT", "TIME_NOT_TRUSTED", "THE MODEL NO LONGER CARRIES THE TIME OF ITS EVALUATION", "decision D-C04a, route a",
               "393 rows an hour", "A RESTART does not", "decision D-C04d", "MODEL_UNREADABLE", "lab D2", "no forecast entity is read", "Measured PV only", "never a guess and never 0", "UNAVAILABLE (never 0)", "FLOOR = the largest of", "rounded UP",
               "never below any", "DOWN to the minute", "UNVERIFIED", "supervised-proven", "unresolved control-authority question", "HOLD while", "END of the lease plus a guarded re-START",
               "at most one per", "never writes anything into a running lease", "SHADOW COMPARISON", "FAIL SAFE", "CONSTANTS", "LIMITS, stated plainly", "Recalled from Home Assistant core",
               "NOT verified on a real Home Assistant", "INSTALL", "needs the owner's go", "template.reload", "no restart", "intelligence/dump_advice.py", "limit is a safety CEILING",
               "never the target", "WHICH START THE NUMBERS ARE FOR", "The SCHEDULE path", "is NOT read", "never enters the floor", "LEASE_ORIGIN_UNKNOWN", "THE AUTHORISED WINDOW",
               "BOUNDED BY THE SCHEDULE'S OWN WINDOW", "floor((window end - now + 20 s) / 60 s)", "loop_battery_power_w", "loop_duration_min", "not a proposal", "TARGET_INFEASIBLE_LOW",
               "PV_SURPLUS_EXPORT_GUARD", "SCHEDULE_START_UNREADABLE", "END NOW", "the lease guard rule", "MEMORY_YOUNG", "a skipped local time", "a repeated one",
               "Install ONLY with NO Dump to Grid or Free Power lease running", "OUTSIDE any armed scheduled Export or charge run", "window end plus 10 minutes",
               "re-creates EVERY template entity", "Exclude sensor.ecco_export_coordinator_model and the lookups", "MANDATORY", "THE ROW RATE", "358 rows an hour", "POWER_STEP_W", "DURATION_STEP_MIN", "is NOT established", "NOT a bound at every power",
               "An UNKNOWN re-target lists no changes", "No attribute carries a time that moves with the clock", "except as the latched value of a RUNNING lease", "LEASE_STOP_SOC_UNREADABLE",
               "FLOOR_FROM_RUNNING_LEASE", "WHILE A LEASE RUNS the same bound holds at EVERY render", "a running lease gets no time past the end of the window it runs in",
               "min(window end, the lease's own latched end) + 20 s", "editing the schedule's duration or start helper while it runs cannot move it later", "can only KEEP the end or SHORTEN it, never move it later",
               "THE END RULE NEVER FIRES")


# ===========================================================================================================================
# the worlds and the comparison with the reference
# ===========================================================================================================================
def new_world(text: str | None = None, **kw) -> X.CoordWorld:
    return X.CoordWorld(text, healthy=False, **kw)


def apply_case(w: X.CoordWorld, over: dict | None = None, *, poll_age: "float | None" = 0.0, poll_text: str | None = None, capm: "tuple | None" = None,
               gate_ages: tuple = GATE_AGES) -> tuple:
    """Set every input (the healthy set with `over` on top; a None removes the entity) and the poll text, render ONCE, and return what the reference needs: (raw readings, poll skew,
    capacity attributes). The skew is Home Assistant's clock minus the time the poll text carries (None when the text is not a time in the firmware's form). The Export start gate and the leases
    consumer are given the ages `gate_ages` (the hold-off reads how long each has read on)."""
    raw = {**X.HEALTHY, **(over or {})}
    mapping = dict(raw)
    if poll_text is not None:
        mapping[X.POLL] = poll_text
        try:
            skew = w.now_ts() - datetime.strptime(poll_text, X.FMT).replace(tzinfo=w.zone).timestamp()
        except ValueError:
            skew = None
    elif poll_age is None:
        mapping[X.POLL] = None
        skew = None
    else:
        mapping[X.POLL] = w.local_text(w.now_ts() - poll_age)
        skew = float(poll_age)
    w.bulk(mapping, capm=capm)
    w.set_gate_ages(*gate_ages)
    SERVICE_LOG.extend(w.w.service_log)
    return raw, skew, capm


def close(a, b) -> bool:
    return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(b))


MODEL_KEYS = ("state", "verdict", "actionable", "reasons", "blocked_by", "notes", "floor_pct", "energy_kwh", "battery_power_w", "net_export_w", "duration_min", "raw_battery_power_w", "loop_power_w",
              "loop_duration_min", "limited_by", "window_end_ts", "lease_origin", "cmp_state", "stop_soc_proposed", "stop_soc_lease", "stop_soc_difference", "export_w_proposed", "export_w_lease",
              "export_w_difference", "battery_w_proposed", "battery_w_loop", "battery_w_commanded", "battery_w_difference", "battery_w_loop_difference", "end_lease_ts", "end_difference_min",
              "rt_state", "rt_reasons", "rt_changes", "rt_entry", "rt_wait_until_ts", "lease_age_min", "mem_since_ts")


def compare(w: X.CoordWorld, ref: dict) -> list[str]:
    """Everything the template publishes against the reference; the list of differences."""
    bad: list[str] = []
    if tuple(w.model()) != MODEL_KEYS:          # TEST-08 (E20): the model's key set and order are exactly these (an extra key, even a boolean, is a change of the interface)
        bad.append(f"the model's keys differ: {sorted(set(w.model()) ^ set(MODEL_KEYS))}")
    if any(isinstance(w.model()[k], bool) for k in w.model() if k not in ("actionable",)):
        bad.append(f"a boolean in the model beyond `actionable`: {[k for k in w.model() if isinstance(w.model()[k], bool)]}")
    st = w.state(X.PROPOSAL)
    if st != ref["state"]:
        bad.append(f"state {st} != {ref['state']}")
    if w.attr(X.PROPOSAL, "actionable") is not ref["actionable"]:
        bad.append(f"actionable {w.attr(X.PROPOSAL, 'actionable')!r} != {ref['actionable']!r}")
    codes = list(w.attr(X.PROPOSAL, "blocked_by") or [])
    if codes != ref["blocked_by"]:
        bad.append(f"blocked_by {codes} != {ref['blocked_by']}")
    notes = [n.split(":")[0].replace("NOTE ", "") for n in (w.attr(X.PROPOSAL, "notes") or []) if n.startswith("NOTE ")]
    if notes != ref["notes"]:
        bad.append(f"notes {notes} != {ref['notes']}")
    exp = {X.P_FLOOR: ref["floor"], X.P_ENERGY: None if ref["energy"] is None else round(ref["energy"], 3), X.P_POWER: ref["power"],
           X.P_NET: None if ref["net"] is None else math.floor(ref["net"]), X.P_DUR: ref["duration"]}
    for eid, e in exp.items():
        s = w.state(eid)
        if e is None:
            if s != "unavailable":
                bad.append(f"{eid} reads {s}, it must be unavailable")
        else:
            try:
                ok = close(float(s), float(e))
            except ValueError:
                ok = False
            if not ok:
                bad.append(f"{eid} reads {s} != {e}")
    m = w.model()
    for key, e in (("floor_pct", ref["floor"]), ("battery_power_w", ref["power"]), ("duration_min", ref["duration"]),
                   ("raw_battery_power_w", ref["raw_power"]),
                   ("loop_power_w", ref["loop_power"]), ("loop_duration_min", ref["loop_duration_pub"]),
                   ("window_end_ts", None if ref["window_end"] is None else round(ref["window_end"]))):
        if (m.get(key) is None) != (e is None) or (e is not None and not close(float(m.get(key)), float(e))):
            bad.append(f"model {key} {m.get(key)} != {e}")
    for attr, key in (("loop_battery_power_w", "loop_power_w"), ("loop_duration_min", "loop_duration_min"), ("raw_battery_power_w", "raw_battery_power_w"), ("window_end_ts", "window_end_ts")):
        if w.attr(X.PROPOSAL, attr) != m.get(key):
            bad.append(f"proposal attribute {attr} {w.attr(X.PROPOSAL, attr)} != model {m.get(key)}")
    if (w.attr(X.PROPOSAL, "limited_by") or "") != ref["limited_by"]:
        bad.append(f"limited_by {w.attr(X.PROPOSAL, 'limited_by')!r} != {ref['limited_by']!r}")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


def run_row(label: str, over: dict | None = None, *, poll_age=0.0, poll_text=None, capm=None, w: X.CoordWorld | None = None, text: str | None = None, gate_ages: tuple = GATE_AGES) -> list[str]:
    w = w or new_world(text)
    raw, skew, cm = apply_case(w, over, poll_age=poll_age, poll_text=poll_text, capm=capm, gate_ages=gate_ages)
    ref = X.reference(raw, poll_skew_s=skew, capacity_attrs=cm, now_ts=w.now_ts(), gate_ages=gate_ages)
    return [f"{label}: {b}" for b in compare(w, ref)]


# ===========================================================================================================================
# the boundary and logic rows (each is also run against the reference)
# ===========================================================================================================================
def rows() -> list[tuple]:
    out: list[tuple] = []

    def add(label, over=None, **kw):
        out.append((label, over or {}, kw))
    for eid, (lo, hi) in RANGE_OF.items():
        short = eid.split(".")[1]
        for v in (lo, hi):
            add(f"{short} at its limit {v}", {eid: str(float(v))})
        for v in (lo - 0.1, hi + 0.1, hi * 10 + 1):
            add(f"{short} outside {v}", {eid: str(float(v))})
        for v in BAD_RAW:
            add(f"{short} reads {v!r}", {eid: v})
    for v in ("0", "100", "-0.1", "100.1", "62.4", "62.0", "99.5", "nan", "inf", "unknown", "abc", None, "-1", "1e12"):
        add(f"reserve reads {v!r}", {X.RESERVE: v})
    for v in ("VALID", "NOT CONFIGURED", "INVALID", "AWAITING CONFIRMATION", "UNKNOWN", "UNAVAILABLE", "unavailable", "unknown", "", None):
        add(f"limits state {v!r}", {X.LIM: v})
    for v in ("on", "off", "unavailable", "unknown", "", None):
        add(f"telemetry online {v!r}", {X.TEL: v})
    for v in ("clear", "held", "unknown", "unavailable", "weird", "", None):
        add(f"hold {v!r}", {X.HOLD: v})
    # the floor: every member in turn, ties, the rounding up, the minimum and the maximum (the dongle's staged Stop SOC is not a member: it is set to a wild value in every row below)
    for s, r in ((50, 40), (30, 50), (30, 62.4), (5, 3), (10, 10), (90, 10), (89.2, 10), (90.2, 10), (10, 91), (10, 90), (33.2, 12), (40, 40), (25, 0), (0, 0), (100, 100)):
        add(f"floor from stop {s} and reserve {r}", {X.STOP_S: str(float(s)), X.RESERVE: str(r), X.STOP_D: "85.0"})
    # the Stop SOC a RUNNING lease latched is a member of the floor (raise-only); the same value of a lease that is not running is not; an unreadable one blocks while a lease runs
    for flag in ("on", "off", "unavailable", "unknown", None):
        for v in ("30.0", "39.9", "40.0", "40.1", "50.0", "89.5", "90.0", "90.1", "100.0", "100.1", "-5", "unknown", "abc", "nan", None):
            add(f"lease flag {flag!r} and a latched Stop SOC {v!r}", {X.LEASE: flag, X.L_STOP: v})
    # the SOC against the floor
    for soc in (39, 40, 41, 41.5, 42, 43, 44, 45, 60, 100, 0):
        add(f"soc {soc} with the floor 40", {X.SOC: str(float(soc))})
    for cap in (1, 5, 27.77, 27.78, 30, 100, 1000):
        add(f"capacity {cap} just above the floor", {X.CAP: str(float(cap)), X.SOC: "43.0", X.TGT: "3000.0", X.LOAD: "0.0"})
    for cm in ((25.0, "measured"), (31.0, "measured"), (25.0, "configured"), (25.0, "estimated"), (0.5, "measured"), ("abc", "measured"), (None, "measured"), (30.0, "measured"),
               (1.0, "measured"), (1000.0, "measured"), (float("nan"), "measured")):
        add(f"measured capacity {cm}", capm=cm)
    # the net export target against the export limit and the START headroom
    for tgt, mx in ((3500, 3600), (3000, 3600), (3000, 2000), (3000, 500), (3000, 50), (8000, 8000), (3400, 3600), (3492, 3600), (3500, 3600), (500, 600), (1900, 2000), (1950, 2000),
                    (600, 700), (500, 700), (100, 3600), (3000, 10), (3000, 3000), (3000, 3100), (3000, 3099)):
        add(f"target {tgt} against the export limit {mx}", {X.TGT: str(float(tgt)), X.MX: str(float(mx))})
    # the expected power: the load and the PV, the clamps, the proven level, the ceiling
    for load, pv in ((0, 0), (800, 0), (800, 1000), (0, 5000), (800, 3800), (800, 3801), (3000, 0), (3001, 0), (3500, 0), (7000, 0), (30000, 0), (0, 30000), (4000, 4000), (200, 3700)):
        for ceil, prov in ((6000, 6000), (8000, 6000), (3000, 6000), (6000, 3000), (3000, 3000), (8000, 3000), (500, 3000), (8000, 8000)):
            add(f"load {load} pv {pv} ceiling {ceil} proven {prov}", {X.LOAD: str(float(load)), X.PV: str(float(pv)), X.PCEIL: str(float(ceil)), X.PROV: str(float(prov))})
    # a PV surplus the target cannot hold: the firmware's TARGET INFEASIBLE LOW (the surplus above the target and the 150 W deadband) and its export guard (the surplus and the 500 W the loop never goes
    # below, against the limit less the START headroom), at every boundary, for several targets and limits
    for tgt, mx in ((3000, 3600), (3000, 8000), (500, 8000), (8000, 8000), (3400, 3600), (500, 600), (2000, 2100)):
        nstart = mx - max(100, 0.03 * mx)
        net = min(tgt, math.floor(nstart / 100) * 100)
        for surplus in (net + 149, net + 150, net + 151, nstart - 501, nstart - 500, nstart - 499, 0, 100, net - 1):
            if surplus >= 0:
                add(f"PV surplus {surplus:g} W target {tgt} export limit {mx}", {X.TGT: str(float(tgt)), X.MX: str(float(mx)), X.LOAD: "800.0", X.PV: f"{800 + surplus:.1f}"})
    # the duration: the window, the minimum worth starting, rounding down
    for win in (1, 9, 10, 11, 60, 169, 170, 240):
        add(f"window {win}", {X.WIN: str(float(win))})
    for cap, win in ((50.0, 90.0), (50.1, 90.0), (49.9, 90.0)):          # an energy that lasts exactly the window (4.5 kWh at 3000 W is 90 minutes), a little more, a little less
        add(f"capacity {cap} against a window of {win} minutes", {X.SOC: "51.0", X.CAP: str(cap), X.LOAD: "0.0", X.WIN: str(win)})
    for soc in (43, 44, 45, 46, 50, 60, 70, 100):
        for pv in (0, 3500):
            add(f"soc {soc} pv {pv}", {X.SOC: str(float(soc)), X.PV: str(float(pv))})
    # the Export schedule's window: its start unreadable or wild, then every boundary of the time left in it (the schedule caps a run at floor((window end - now + 20 s) / 60 s))
    for v in BAD_RAW + ("2026-13-40 99:99:99", "2026-11-26", "2026-11-26T18:00:00", "2026-11-26 18:00", "1970-01-01 00:00:00", "2026-11-26 18:00:00 ", "9999-12-31 23:59:59", "0001-01-01 00:00:00"):
        add(f"schedule start reads {v!r}", {X.SCH_START: v})
    for win in (240.0, 120.0, 30.0, 12.0):
        for left in (win * 60 + 1, win * 60, win * 60 - 1, 3600 + 20, 3600 + 19, 3600 + 21, 1200, 641, 640, 639, 621, 620, 619, 601, 600, 599, 581, 580, 579, 100, 41, 40, 39, 21, 20, 19, 1, 0, -1):
            if left <= win * 60 + 1:
                for soc in (80.0, 50.0):
                    add(f"window {win:g} min, {left} s left, soc {soc:g}", {X.WIN: str(win), X.SCH_START: started_ago(win * 60 - left), X.SOC: str(soc)})
    for off in (-1, -3600, -86400):
        add(f"window starts in {-off} s", {X.SCH_START: started_ago(off)})
    for off in (86400, 3 * 86400):
        add(f"window ended long ago ({off} s)", {X.SCH_START: started_ago(off)})
    # the poll freshness and the forms of the poll text
    for age in (0, 1, 60, 89, 90, 91, 120, 300, 3600, -1, -89, -90, -91, -3600):
        add(f"poll {age} s old", poll_age=age)
    for txt in ("", "unknown", "unavailable", "Waiting", "2026-11-26T17:00:00", "2026-11-26", "2026-11-26 17:00", "17:00:00", "abc", "2026-13-40 99:99:99", "2026-11-26 17:00:00 ",
                "1970-01-01 00:00:00"):
        add(f"poll text {txt!r}", poll_text=txt)
    add("poll missing", poll_age=None)
    # CS-06: a proven level that is not a multiple of the 500 W step (the proposal is clamped to it, the loop's figure is the proposal's below it, never above the proven level)
    for prov, pceil in (("6250.0", "8000.0"), ("6250.0", "6250.0"), ("2750.5", "8000.0"), ("2750.5", "2750.5"), ("3000.0", "8000.0")):
        for load in (700.0, 1700.0, 2400.0, 2900.0, 3100.0, 3250.0, 3300.0, 3750.0, 5200.0):
            add(f"proven {prov}, ceiling {pceil}, load {load:g}", {X.PROV: prov, X.PCEIL: pceil, X.LOAD: str(load)})
    # the power at the edges of its step: PV that leaves the requirement just under, on and just over a multiple of 500 W, and below zero
    for pv in (0.0, 299.0, 300.0, 301.0, 800.0, 1300.0, 2799.0, 2800.0, 2801.0, 3299.0, 3300.0, 3301.0, 3799.0, 3800.0, 3801.0, 3849.0, 3850.0, 3851.0, 3949.0, 3951.0, 4000.0):
        add(f"pv {pv:g} W (the requirement {3800 - pv:g} W)", {X.PV: str(pv)})
    return out


ROWS = rows()


def boundary_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    bad: list[str] = []
    w = new_world(text)
    for label, over, kw in ROWS:
        bad += run_row(label, over, w=w, **kw)
        if bad and first_only:
            return bad
    return bad


# ===========================================================================================================================
# [1b] the Export start gate (slice S-A2): every reading of it at every age, against the reference; hand-computed anchors; the hold-off in real time
# ===========================================================================================================================
GATE_LONG_CODE = "BLOCKED_" + "X" * 40        # longer than the 40 characters the proposal keeps of a code
GATE_READINGS = (
    ("open", ("on", {"blocked_by": []})),
    ("closed by one cause", ("off", {"blocked_by": ["TIME_LEASES"]})),
    ("closed by three causes", ("off", {"blocked_by": ["TIME_LEASES", "DUMP_ACTIVE", "OVERRIDE_ACTIVE"]})),
    ("closed by a cause longer than 40 characters", ("off", {"blocked_by": [GATE_LONG_CODE, "DUMP_ACTIVE"]})),
    ("closed, a cause that is no text", ("off", {"blocked_by": ["TIME_LEASES", 5, None]})),
    ("on with a cause", ("on", {"blocked_by": ["TIME_LEASES"]})),
    ("off with no cause", ("off", {"blocked_by": []})),
    ("off, the only cause is no text", ("off", {"blocked_by": [5]})),
    ("off, the only cause is none", ("off", {"blocked_by": [None]})),
    ("off, causes none of which is text", ("off", {"blocked_by": [5, None, 7.5]})),
    ("an unreadable state with causes", ("maybe", {"blocked_by": ["TIME_LEASES", "DUMP_ACTIVE"]})),
    ("unavailable with a cause", ("unavailable", {"blocked_by": ["DUMP_ACTIVE"]})),
    ("on, the list is a text", ("on", {"blocked_by": "TIME_LEASES"})),
    ("on, the list is a mapping", ("on", {"blocked_by": {"TIME_LEASES": 1}})),
    ("on, the list is a number", ("on", {"blocked_by": 3})),
    ("on, the list is missing", ("on", {})),
    ("on, the list is none", ("on", {"blocked_by": None})),
    ("unavailable", ("unavailable", {"blocked_by": []})),
    ("unknown", ("unknown", {"blocked_by": []})),
    ("an empty state", ("", {"blocked_by": []})),
    ("neither on nor off", ("maybe", {"blocked_by": []})),
    ("missing", None),
)
GATE_AGE_PAIRS = ((600.0, 600.0), (0.0, 600.0), (1.0, 600.0), (59.0, 600.0), (59.9, 600.0), (60.0, 600.0), (61.0, 600.0), (600.0, 0.0))
GATE_PROPOSALS = (("VALID", {}), ("HOLD", {X.HOLD: "held"}), ("INVALID", {X.SOC: "unknown"}), ("UNVERIFIED", {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}))


def gate_rows_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    """The Export start gate in every reading and at every age, for each kind of proposal, against the reference; then hand-computed anchors that do not use the reference."""
    bad: list[str] = []
    w = new_world(text)
    for pname, pover in GATE_PROPOSALS:
        for rname, reading in GATE_READINGS:
            for ages in GATE_AGE_PAIRS:
                bad += run_row(f"a {pname} proposal, the gate {rname}, ages {ages}", {**pover, X.EG: reading}, w=w, gate_ages=ages)
                if bad and first_only:
                    return bad

    def one(over: dict | None = None, ages: tuple = GATE_AGES) -> X.CoordWorld:
        w1 = new_world(text)
        apply_case(w1, over or {}, gate_ages=ages)
        return w1
    healthy_numbers = ("40", "10.53", "4000", "3000", "155")
    unavailable = ("unavailable",) * 5

    def expect(label: str, w1: X.CoordWorld, state: str, codes: list, actionable: bool, nums: "tuple | None" = healthy_numbers) -> None:
        got = (w1.state(X.PROPOSAL), list(w1.attr(X.PROPOSAL, "blocked_by") or []), w1.attr(X.PROPOSAL, "actionable"))
        if got != (state, codes, actionable) or (nums is not None and tuple(w1.state(e) for e in X.NUMERIC) != nums) or w1.errors:
            bad.append(f"{label}: {got} {tuple(w1.state(e) for e in X.NUMERIC)} wanted {(state, codes, actionable, nums)} {w1.errors[:1]}")
    expect("the gate is open and has read on for 10 minutes", one(), "VALID", [], True)
    w1 = one({X.EG: ("off", {"blocked_by": ["TIME_LEASES", "DUMP_ACTIVE"]})})
    expect("the gate is closed by two causes: NOT ALLOWED with the gate's own codes, the numbers kept", w1, "NOT ALLOWED", ["TIME_LEASES", "DUMP_ACTIVE"], False)
    first = (w1.attr(X.PROPOSAL, "reasons") or [""])[0]
    if not first.startswith("NOT ALLOWED: the proposal itself is VALID, but binary_sensor.ecco_export_start_allowed does not allow a start now (") or "TIME_LEASES, DUMP_ACTIVE" not in first \
            or w1.attr(X.PROPOSAL, "notes") != [] or w1.attr(X.PROPOSAL, "limited_by") != "" or len(w1.attr(X.PROPOSAL, "reasons") or []) != 1:
        bad.append(f"NOT ALLOWED names the gate and its codes in its first reason and adds nothing else: {w1.attr(X.PROPOSAL, 'reasons')}")
    for age, state, codes, act in ((0.0, "NOT ALLOWED", ["GATE_SETTLING"], False), (1.0, "NOT ALLOWED", ["GATE_SETTLING"], False), (59.0, "NOT ALLOWED", ["GATE_SETTLING"], False),
                                   (59.9, "NOT ALLOWED", ["GATE_SETTLING"], False), (60.0, "VALID", [], True), (61.0, "VALID", [], True), (3600.0, "VALID", [], True)):
        expect(f"the gate is open and has read on for {age} s", one(ages=(age, 600.0)), state, codes, act)
    for label, reading in (("unavailable", ("unavailable", {"blocked_by": []})), ("missing", None), ("on with a list that is a text", ("on", {"blocked_by": "TIME_LEASES"})),
                           ("on with no list", ("on", {})), ("neither on nor off", ("maybe", {"blocked_by": []})), ("on with a mapping for its list", ("on", {"blocked_by": {"a": 1}}))):
        expect(f"the gate reads {label}: it cannot be read", one({X.EG: reading}), "NOT ALLOWED", ["GATE_UNREADABLE"], False)
    expect("the gate is on with a cause: its own cause, then inconsistent, never open", one({X.EG: ("on", {"blocked_by": ["TIME_LEASES"]})}), "NOT ALLOWED", ["TIME_LEASES", "GATE_INCONSISTENT"], False)
    expect("the gate is off with no cause: inconsistent", one({X.EG: ("off", {"blocked_by": []})}), "NOT ALLOWED", ["GATE_INCONSISTENT"], False)
    expect("a cause longer than 40 characters is cut", one({X.EG: ("off", {"blocked_by": [GATE_LONG_CODE]})}), "NOT ALLOWED", [GATE_LONG_CODE[:40]], False)
    expect("a cause that is no text is left out", one({X.EG: ("off", {"blocked_by": ["TIME_LEASES", 5]})}), "NOT ALLOWED", ["TIME_LEASES"], False)
    closed = ("off", {"blocked_by": ["TIME_LEASES"]})
    expect("a Hold battery with the gate closed: HOLD with its own cause, never the gate's", one({X.HOLD: "held", X.EG: closed}), "HOLD", ["OVERRIDE_ACTIVE"], False, unavailable)
    expect("an INVALID proposal with the gate closed: INVALID with its own causes", one({X.SOC: "unknown", X.EG: closed}), "INVALID", ["SOC_UNREADABLE"], False, unavailable)
    expect("an INVALID proposal with the gate unreadable: its own causes", one({X.SOC: "unknown", X.EG: None}), "INVALID", ["SOC_UNREADABLE"], False, unavailable)
    unv = {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}
    expect("an UNVERIFIED proposal with the gate open is not actionable (nobody has proven it)", one(unv), "UNVERIFIED", [], False, None)
    expect("an UNVERIFIED proposal with the gate closed stays UNVERIFIED", one({**unv, X.EG: closed}), "UNVERIFIED", [], False, None)
    # the gate's own words cannot change a number: the same numbers with the gate open, closed, young and unreadable
    open_nums = tuple(one().state(e) for e in X.NUMERIC)
    for label, reading, ages in (("closed", closed, GATE_AGES), ("young", ("on", {"blocked_by": []}), (5.0, 600.0)), ("unreadable", None, GATE_AGES)):
        if tuple(one({X.EG: reading}, ages).state(e) for e in X.NUMERIC) != open_nums:
            bad.append(f"the numbers change with the gate ({label})")
    return bad


def gate_realtime_problems(text: str | None = None) -> list[str]:
    """In real time (the clock advances, the dongle polls every 10 s): the hold-off after the gate turns on (60 s, judged by the age of its STATE, never of its attributes), a flapping gate, the
    young entities of a restart, and the leases consumer turning on and off while a change is allowed."""
    bad: list[str] = []

    def prop(w1: X.CoordWorld) -> tuple:
        return (w1.state(X.PROPOSAL), list(w1.attr(X.PROPOSAL, "blocked_by") or []), w1.attr(X.PROPOSAL, "actionable"))
    settling = ("NOT ALLOWED", ["GATE_SETTLING"], False)
    w = lease_world(text)
    w.advance(60.0 - (w.now_ts() % 60.0))                       # a minute boundary
    if prop(w) != ("VALID", [], True):
        bad.append(f"a healthy world: {prop(w)}")
    w.bulk({X.EG: ("off", {"blocked_by": ["TIME_LEASES"]})})
    if prop(w) != ("NOT ALLOWED", ["TIME_LEASES"], False):
        bad.append(f"the gate closes: {prop(w)}")
    w.bulk({X.EG: ("on", {"blocked_by": []})})
    t_on = w.now_ts()
    for dt in (0, 10, 30, 50, 59):
        w.w.run_until(t_on + dt)
        w.force()
        if prop(w) != settling:
            bad.append(f"the gate has been on for {dt} s: {prop(w)}")
    w.w.run_until(t_on + 60)
    w.force()
    if prop(w) != ("VALID", [], True):
        bad.append(f"the gate has been on for 60 s: {prop(w)}")
    # a gate that is published again with new attributes keeps its age: the hold-off is judged by the last CHANGE of its state, not by its last update
    for i in range(5):
        w.bulk({X.EG: ("on", {"blocked_by": [], "reasons": [f"ALLOWED: every check passed ({i})"]})})
        if prop(w) != ("VALID", [], True):
            bad.append(f"the gate is published again with other reasons ({i}): {prop(w)}")
            break
    # a gate that flaps starts the 60 s afresh each time
    w.bulk({X.EG: ("off", {"blocked_by": ["TIME_LEASES"]})})
    w.advance(5)
    w.bulk({X.EG: ("on", {"blocked_by": []})})
    t_on2 = w.now_ts()
    w.w.run_until(t_on2 + 59)
    w.force()
    if prop(w) != settling:
        bad.append(f"a gate that flapped, on again for 59 s: {prop(w)}")
    w.w.run_until(t_on2 + 70)
    if prop(w) != ("VALID", [], True):
        bad.append(f"a gate that flapped, on again for 70 s (the poll renders it): {prop(w)}")
    # a restart: every entity is new and young, the dongle polls from then on
    w = new_world(text)
    w.bulk({**X.HEALTHY}, poll_age=0.0)
    w.start_feed(10.0)
    w.w.run_until(w.now_ts() + 10)
    if prop(w) != settling:
        bad.append(f"10 s after a restart: {prop(w)}")
    w.w.run_until(w.now_ts() + 40)
    if prop(w) != settling:
        bad.append(f"50 s after a restart: {prop(w)}")
    w.w.run_until(w.now_ts() + 30)
    if prop(w) != ("VALID", [], True):
        bad.append(f"80 s after a restart: {prop(w)}")
    # the leases consumer turns on and off while a change is allowed: the re-target waits for 60 s of trust, and then for the 30 minutes since its first would-change
    w = lease_world(text, over=STOP50)
    w.sched_lease_on(stop=49, export=3000, command=3800, age_min=45)
    w.advance(60)
    s1 = lease_state(w)
    stamp = s1["last"]
    if s1["rt"] != "ALLOWED" or stamp is None:
        bad.append(f"a lease 45 minutes old with a deviation: {s1['rt']} {s1['reasons']} {stamp}")
        return bad
    w.bulk({X.TL: ("on", {"detail": "attribute that changes"})})                       # an attribute alone changes: the consumer's age is its state's
    if lease_state(w)["rt"] != "ALLOWED":
        bad.append("the leases consumer is published again with another attribute: the change is no longer allowed")
    w.bulk({X.TL: "off"})
    s2 = lease_state(w)
    codes2 = [r.split(":")[0] for r in (s2["reasons"] or [])]
    if s2["rt"] != "WAIT" or codes2 != ["TIME_NOT_TRUSTED"] or s2["wait"] is not None or s2["last"] != stamp or not s2["changes"]:
        bad.append(f"the leases consumer turns off: {s2['rt']} {codes2} {s2['wait']} {s2['last']} {s2['changes']}")
    w.advance(120)
    w.bulk({X.TL: "on"})
    s3 = lease_state(w)
    codes3 = [r.split(":")[0] for r in (s3["reasons"] or [])]
    if s3["rt"] != "WAIT" or sorted(codes3) != ["RECENT_CHANGE", "TIME_NOT_TRUSTED"] or s3["wait"] is None or abs(s3["wait"] - (stamp + 1800)) > 1:
        bad.append(f"the leases consumer is back, on for 0 s: {s3['rt']} {codes3} {s3['wait']} {stamp + 1800}")
    w.w.run_until(w.now_ts() + 59)
    w.force()
    s4 = lease_state(w)
    if "TIME_NOT_TRUSTED" not in [r.split(":")[0] for r in (s4["reasons"] or [])]:
        bad.append(f"the leases consumer has been on for 59 s: {s4['rt']} {s4['reasons']}")
    w.w.run_until(w.now_ts() + 1)
    w.force()
    s5 = lease_state(w)
    codes5 = [r.split(":")[0] for r in (s5["reasons"] or [])]
    if s5["rt"] != "WAIT" or codes5 != ["RECENT_CHANGE"] or s5["wait"] is None or abs(s5["wait"] - (stamp + 1800)) > 1:
        bad.append(f"the leases consumer has been on for 60 s: only the 30 minute gap remains: {s5['rt']} {codes5} {s5['wait']}")
    w.w.run_until(stamp + 1799)
    w.force()
    if lease_state(w)["rt"] != "WAIT":
        bad.append("1799 s after the first would-change the second is allowed")
    w.w.run_until(stamp + 1800)
    w.force()
    s6 = lease_state(w)
    if s6["rt"] != "ALLOWED" or s6["last"] != stamp + 1800 or s6["reasons"]:
        bad.append(f"1800 s after the first would-change: {s6['rt']} {s6['reasons']} {s6['last']} {stamp + 1800}")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


# ===========================================================================================================================
# hand-computed anchors (independent of the reference)
# ===========================================================================================================================
def anchors(text: str | None = None) -> list[str]:
    bad: list[str] = []

    def expect(label: str, over: dict, want_state: str, **nums) -> X.CoordWorld:
        w = new_world(text)
        apply_case(w, over)
        got = {"floor": w.state(X.P_FLOOR), "energy": w.state(X.P_ENERGY), "power": w.state(X.P_POWER), "net": w.state(X.P_NET), "duration": w.state(X.P_DUR)}
        if w.state(X.PROPOSAL) != want_state:
            bad.append(f"{label}: state {w.state(X.PROPOSAL)} != {want_state} ({w.attr(X.PROPOSAL, 'blocked_by')})")
        for k, v in nums.items():
            if got[k] != v:
                bad.append(f"{label}: {k} {got[k]} != {v}")
        return w
    # 39 points x 0.30 kWh x 0.90 = 10.53 kWh; 3800 W is published as 4000 W (rounded UP to a multiple of 500 W) and 10.53 kWh / 4000 W = 157.95 min, 157 whole minutes, published as 155 (rounded DOWN to 5 minutes)
    expect("the healthy evening", {}, "VALID", floor="40", energy="10.53", power="4000", net="3000", duration="155")
    expect("PV carries part of it", {X.PV: "1000.0"}, "VALID", power="3000", duration="210")
    expect("PV nearly covers the target: a little battery power (100 W, published as the 500 W step), the divisor floor 500 W, the window", {X.PV: "3700.0"}, "VALID", power="500", duration="240")
    expect("a reserve that rises sets the floor", {X.RESERVE: "62.4"}, "VALID", floor="63")
    expect("a higher Stop SOC request wins", {X.STOP_S: "50.0"}, "VALID", floor="50")
    expect("the dongle minimum is the floor", {X.STOP_S: "5.0", X.RESERVE: "3"}, "VALID", floor="10")
    expect("the dongle's staged Stop SOC, a leftover of a manual run, is not a member of the floor", {X.STOP_D: "80.0"}, "VALID", floor="40", energy="10.53", duration="155")
    expect("nor a leftover below it", {X.STOP_D: "10.0", X.STOP_S: "45.0"}, "VALID", floor="45")
    # the Stop SOC a RUNNING lease latched is a member (raise-only): 29 points x 0.30 x 0.90 = 7.83 kWh at 3800 W is 123 minutes
    w = expect("a running lease latched 50 %: the floor is not below it (the schedule says 25, the reserve 40)", {X.LEASE: "on", X.L_STOP: "50.0"}, "VALID", floor="50", energy="7.83", duration="115")
    if not any(n.startswith("NOTE FLOOR_FROM_RUNNING_LEASE") and "(50.0 %)" in n for n in (w.attr(X.PROPOSAL, "notes") or [])):
        bad.append(f"a floor that is the running lease's latched Stop SOC says so: {w.attr(X.PROPOSAL, 'notes')}")
    for latched in ("30.0", "40.0"):
        w = expect(f"a running lease latched {latched} %, not above the reserve: the floor is the reserve", {X.LEASE: "on", X.L_STOP: latched}, "VALID", floor="40", duration="155")
        if any(n.startswith("NOTE FLOOR_FROM_RUNNING_LEASE") for n in (w.attr(X.PROPOSAL, "notes") or [])):
            bad.append(f"a latched Stop SOC at or below the others is not the floor: {w.attr(X.PROPOSAL, 'notes')}")
    expect("a stale latched value of a lease that is not running is not a member", {X.LEASE: "off", X.L_STOP: "80.0"}, "VALID", floor="40", duration="155")
    expect("nor when the lease flag cannot be read (the re-target says so)", {X.LEASE: "unavailable", X.L_STOP: "80.0"}, "VALID", floor="40")
    for v in ("unknown", "unavailable", "-5", "abc", "101"):
        w = expect(f"a running lease whose latched Stop SOC reads {v!r}: the floor cannot be shown to respect it", {X.LEASE: "on", X.L_STOP: v}, "INVALID")
        if w.attr(X.PROPOSAL, "blocked_by") != ["LEASE_STOP_SOC_UNREADABLE"]:
            bad.append(f"a running lease whose latched Stop SOC reads {v!r}: {w.attr(X.PROPOSAL, 'blocked_by')}")
    expect("a running lease latched 95 %: no room under the dongle's 90 %", {X.LEASE: "on", X.L_STOP: "95.0"}, "INVALID")
    expect("the export limit is a ceiling for the target", {X.TGT: "3500.0"}, "VALID", net="3400")
    expect("the power ceiling clamps (the proven level equals it: not UNVERIFIED)", {X.LOAD: "3001.0", X.PCEIL: "6000.0", X.PROV: "6000.0"}, "VALID", power="6000")
    w = expect("above the proven level with a higher ceiling is UNVERIFIED and clamped to the proven level", {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}, "UNVERIFIED", power="6000")
    if w.attr(X.PROPOSAL, "loop_battery_power_w") != 6500 or w.attr(X.PROPOSAL, "loop_duration_min") != 95:
        bad.append(f"UNVERIFIED: the loop would run at 6500 W (6001 rounded up) for 95 minutes: {w.attr(X.PROPOSAL, 'loop_battery_power_w')} {w.attr(X.PROPOSAL, 'loop_duration_min')}")
    expect("a ceiling below the proven level clamps and stays VALID", {X.LOAD: "3001.0", X.PCEIL: "5000.0", X.PROV: "6000.0"}, "VALID", power="5000")
    # the recorded live limits (Power Ceiling 8000 W, proven level 3000 W), the evening load 1656 W, SOC 60 %, floor 25 %: 34 points x 0.30 x 0.90 = 9.18 kWh
    live = {X.PCEIL: "8000.0", X.PROV: "3000.0", X.LOAD: "1656.0", X.SOC: "60.0", X.STOP_S: "25.0", X.RESERVE: "25"}
    w = expect("the live-like limits: the proposal stays at the proven level, 9.18 kWh at 3000 W is 183 minutes, published as 180", live, "UNVERIFIED", floor="25", energy="9.18", power="3000", duration="180")
    if (w.attr(X.PROPOSAL, "loop_battery_power_w"), w.attr(X.PROPOSAL, "loop_duration_min"), w.attr(X.PROPOSAL, "raw_battery_power_w"), w.attr(X.PROPOSAL, "limited_by")) != (5000, 110, 5000, "PROVEN_LEVEL"):
        bad.append(f"the live-like limits: the loop would run at 5000 W (4656 rounded up) for 110 minutes, not the clamp: {w.attr(X.PROPOSAL, 'loop_battery_power_w')} {w.attr(X.PROPOSAL, 'loop_duration_min')}")
    if not any(n.startswith("UNVERIFIED ABOVE_PROVEN_LEVEL") and "5000" in n and "110" in n and "3000" in n and "180" in n for n in (w.attr(X.PROPOSAL, "notes") or [])):
        bad.append(f"the live-like limits: the note names the clamp and the loop: {w.attr(X.PROPOSAL, 'notes')}")
    w = expect("with the ceiling at the proven level the proposal is VALID and the loop figures equal it", {**live, X.PCEIL: "3000.0"}, "VALID", floor="25", power="3000", duration="180")
    if (w.attr(X.PROPOSAL, "loop_battery_power_w"), w.attr(X.PROPOSAL, "loop_duration_min")) != (3000, 180):
        bad.append(f"ceiling = proven: the loop figures equal the proposal's: {w.attr(X.PROPOSAL, 'loop_battery_power_w')} {w.attr(X.PROPOSAL, 'loop_duration_min')}")
    expect("the schedule window bounds the duration", {X.WIN: "100.0"}, "VALID", duration="100")
    w = expect("the energy lasts exactly as long as the window (4.5 kWh at 3000 W is 90.0 minutes): the window is not what limits it", {X.SOC: "51.0", X.CAP: "50.0", X.LOAD: "0.0", X.WIN: "90.0"}, "VALID",
               energy="4.5", power="3000", duration="90")
    if any(n.startswith("NOTE DURATION_LIMITED_BY_WINDOW") for n in (w.attr(X.PROPOSAL, "notes") or [])):
        bad.append(f"an energy that lasts exactly the window is not limited by it: {w.attr(X.PROPOSAL, 'notes')}")
    w = expect("one capacity step more: the window limits it, and says so", {X.SOC: "51.0", X.CAP: "50.1", X.LOAD: "0.0", X.WIN: "90.0"}, "VALID", duration="90")
    if not any(n.startswith("NOTE DURATION_LIMITED_BY_WINDOW") for n in (w.attr(X.PROPOSAL, "notes") or [])):
        bad.append(f"an energy that lasts longer than the window is limited by it, with a note: {w.attr(X.PROPOSAL, 'notes')}")
    expect("no energy above the floor", {X.SOC: "41.0"}, "INVALID", floor="unavailable", energy="unavailable", power="unavailable", net="unavailable", duration="unavailable")
    expect("a hold gives no number at all", {X.HOLD: "held"}, "HOLD", floor="unavailable", energy="unavailable", power="unavailable", net="unavailable", duration="unavailable")
    expect("a reserve above the dongle's Stop SOC range", {X.RESERVE: "91"}, "INVALID", floor="unavailable")
    expect("the unconfigured export limit", {X.MX: "0.0"}, "INVALID", net="unavailable")
    # a PV surplus the target cannot hold (Max Grid Export 3600 W: START ceiling 3492 W; target 3000 W: net 3000 W)
    expect("a PV surplus of 2992 W plus the 500 W of the loop is exactly the export ceiling: allowed", {X.PV: "3792.0"}, "VALID", power="500", duration="240")
    w = expect("a PV surplus of 2993 W plus 500 W is above the export ceiling: the export guard would end the lease", {X.PV: "3793.0"}, "INVALID", power="unavailable")
    if w.attr(X.PROPOSAL, "blocked_by") != ["PV_SURPLUS_EXPORT_GUARD"]:
        bad.append(f"the export guard cause: {w.attr(X.PROPOSAL, 'blocked_by')}")
    expect("PV 5000 W against a load of 800 W: the surplus 4200 W is no proposal (it was VALID with no battery power)", {X.PV: "5000.0"}, "INVALID")
    expect("a surplus of 3150 W with a target of 3000 W and an 8000 W limit: exactly the deadband, allowed", {X.MX: "8000.0", X.PV: "3950.0"}, "VALID", power="0")
    w = expect("a surplus of 3151 W: TARGET INFEASIBLE LOW", {X.MX: "8000.0", X.PV: "3951.0"}, "INVALID")
    if w.attr(X.PROPOSAL, "blocked_by") != ["TARGET_INFEASIBLE_LOW"]:
        bad.append(f"the infeasible low cause: {w.attr(X.PROPOSAL, 'blocked_by')}")
    # the window: 100 minutes into a 240 minute window (the schedule allows 140 minutes more: 17:00 + 140 = 19:20 = the window end)
    w = expect("inside the window the duration is the time left (140 minutes, not the 155 the energy lasts)", {X.SCH_START: started_ago(100 * 60)}, "VALID", duration="140")
    if w.attr(X.PROPOSAL, "window_end_ts") != round(T0 + 140 * 60) or not any(n.startswith("NOTE DURATION_LIMITED_BY_WINDOW") for n in (w.attr(X.PROPOSAL, "notes") or [])):
        bad.append(f"inside the window: the window end and the note: {w.attr(X.PROPOSAL, 'window_end_ts')} {w.attr(X.PROPOSAL, 'notes')}")
    expect("the schedule's own +20 s: 140 minutes and 19 s left is 140 minutes, 140 minutes and 40 s is 141 (never later than the window end plus 20 s)", {X.SCH_START: started_ago(14400 - 8419)}, "VALID", duration="140")
    expect("one second more", {X.SCH_START: started_ago(14400 - 8440)}, "VALID", duration="140")
    w = expect("12 minutes left: a start that fits", {X.SCH_START: started_ago(14400 - 720)}, "VALID", duration="10")
    w = expect("5 minutes left: no start fits (below the 10 minutes worth a start)", {X.SCH_START: started_ago(14400 - 300)}, "INVALID")
    if w.attr(X.PROPOSAL, "blocked_by") != ["BELOW_MINIMUM_DURATION"] or not any("window leaves 5 minutes" in r for r in (w.attr(X.PROPOSAL, "reasons") or [])):
        bad.append(f"5 minutes left: the cause names the window: {w.attr(X.PROPOSAL, 'blocked_by')} {w.attr(X.PROPOSAL, 'reasons')}")
    expect("before the window a start at its own time may run the whole energy", {X.SCH_START: started_ago(-600)}, "VALID", duration="155")
    expect("after the window the next one will", {X.SCH_START: started_ago(14401)}, "VALID", duration="155")
    # a lease that RUNS: the same bound at every render, and after the window end it gets no time (the next window is for the next start, not for a run still going)
    expect("a lease running before its window opens: the whole length, as for a start at the window's own time", {X.LEASE: "on", X.L_STOP: "30.0", X.SCH_START: started_ago(-600)}, "VALID", duration="155")
    expect("a lease running inside the window: the time left (140 minutes), as for a start", {X.LEASE: "on", X.L_STOP: "30.0", X.SCH_START: started_ago(100 * 60)}, "VALID", duration="140")
    for after, label in ((14400, "at the window end"), (14419, "19 s after the window end (the schedule's own 20 s still count 0 minutes)"), (14421, "21 s after the window end"), (14401, "1 s after the window end"),
                         (14400 + 3600, "an hour after the window end"), (14400 + 86400, "a day after the window end")):
        w = expect(f"a lease still running {label}: it gets no time (not the next window's 155 minutes): INVALID", {X.LEASE: "on", X.L_STOP: "30.0", X.SCH_START: started_ago(after)}, "INVALID",
                   floor="unavailable", energy="unavailable", power="unavailable", net="unavailable", duration="unavailable")
        if w.attr(X.PROPOSAL, "blocked_by") != ["BELOW_MINIMUM_DURATION"] or not any("the proposed duration is 0 minutes" in r and "the window the running lease is authorised for leaves 0 minutes" in r
                                                                                     for r in (w.attr(X.PROPOSAL, "reasons") or [])):
            bad.append(f"a lease still running {label}: the cause names the window it runs in and 0 minutes: {w.attr(X.PROPOSAL, 'blocked_by')} {w.attr(X.PROPOSAL, 'reasons')}")
    expect("a lease that does not run (the flag off) after the window end: the next window's proposal", {X.LEASE: "off", X.SCH_START: started_ago(14401)}, "VALID", duration="155")
    expect("a lease flag that cannot be read after the window end is not a running lease: the next window's proposal (the re-target says it cannot tell)", {X.LEASE: "unavailable", X.SCH_START: started_ago(14401)}, "VALID",
           duration="155")
    w = expect("an unreadable window start", {X.SCH_START: "unknown"}, "INVALID")
    if w.attr(X.PROPOSAL, "blocked_by") != ["SCHEDULE_START_UNREADABLE"]:
        bad.append(f"the unreadable window start: {w.attr(X.PROPOSAL, 'blocked_by')}")
    # the minute worth starting: 2 points x 0.2777 kWh... : energy = 2 x cap/100 x 0.90 kWh; at 3000 W, 10 minutes is 0.5 kWh, so a capacity of 27.78 kWh just reaches it
    w = new_world(text)
    apply_case(w, {X.SOC: "43.0", X.CAP: "27.77", X.LOAD: "0.0"})
    if w.state(X.PROPOSAL) != "INVALID" or "BELOW_MINIMUM_DURATION" not in (w.attr(X.PROPOSAL, "blocked_by") or []):
        bad.append(f"9.99 minutes is below the minimum worth starting: {w.state(X.PROPOSAL)} {w.attr(X.PROPOSAL, 'blocked_by')} {w.state(X.P_DUR)}")
    apply_case(w, {X.SOC: "43.0", X.CAP: "27.78", X.LOAD: "0.0"})
    if w.state(X.PROPOSAL) != "VALID" or w.state(X.P_DUR) != "10":
        bad.append(f"10.0 minutes is worth starting: {w.state(X.PROPOSAL)} {w.state(X.P_DUR)}")
    return bad


# ===========================================================================================================================
# the sweep: seeded random inputs
# ===========================================================================================================================
BAD_STATE = (None, "unknown", "unavailable", "", "abc", "nan", "inf", "-inf", "-1", "1e12", "1e999", "None")


def random_case(rng: random.Random) -> tuple:
    """(overrides, poll age or None, poll text or None, capm): about half the cases are healthy-ish so VALID and UNVERIFIED are common, the rest wander."""
    easy = rng.random() < 0.55
    over: dict = {}
    over[X.SOC] = str(rng.choice([rng.uniform(45, 100), float(rng.randint(40, 100)), 0.0, 100.0]) if easy else rng.uniform(-5, 105))
    over[X.LOAD] = str(rng.uniform(300, 6000) if easy else rng.uniform(-100, 31000))
    over[X.PV] = str(rng.choice([0.0, 0.0, rng.uniform(0, 3000), rng.uniform(0, 8000)]) if easy else rng.uniform(-100, 31000))
    over[X.GRID] = str(rng.uniform(-6000, 6000) if easy else rng.uniform(-31000, 31000))
    over[X.CAP] = str(rng.uniform(5, 60) if easy else rng.uniform(-1, 1100))
    over[X.RESERVE] = str(rng.choice([rng.uniform(5, 45), float(rng.randint(5, 45))]) if easy else rng.uniform(-5, 105))
    over[X.STOP_S] = str(float(rng.randint(10, 40)) if easy else rng.uniform(-5, 105))
    over[X.TGT] = str(float(rng.randrange(500, 8100, 100)) if easy else rng.uniform(-1, 31000))
    over[X.WIN] = str(float(rng.randint(1, 240)) if easy else rng.uniform(-1, 250))
    over[X.PCEIL] = str(float(rng.randrange(500, 8100, 100)) if easy else rng.uniform(400, 31000))
    over[X.PROV] = str(float(rng.randrange(3000, 8100, 100)) if easy else rng.uniform(400, 31000))
    over[X.MX] = str(float(rng.randrange(500, 8100, 10)) if easy else rng.uniform(-1, 31000))
    if rng.random() < 0.05:
        over[X.MX] = "0.0"
    # the Export schedule's window: not open yet, open (a start that many seconds ago), over, or unreadable
    over[X.SCH_START] = started_ago(rng.choice([-7200, -60, 0, 30, 600, 3600, 7200, 12000, 14000, 14300, 14380, 14400, 20000, 100000]) + rng.choice([0, 0, 1, 19, 20, 21, 59]))
    over[X.STOP_D] = str(rng.uniform(0, 100))                    # the dongle's staged Stop SOC: a leftover, never read
    if rng.random() < 0.2:
        over[X.LEASE] = rng.choice(["on", "on", "on", "off", "unavailable"])
        over[X.L_STOP] = str(rng.choice([rng.uniform(0, 100), float(rng.randint(10, 60)), "unknown", "-5", "abc", 30.0, 50.0]))
    over[X.LIM] = "VALID" if (easy or rng.random() < 0.8) else rng.choice(["INVALID", "NOT CONFIGURED", "UNAVAILABLE", "unknown", None])
    over[X.TEL] = "on" if (easy or rng.random() < 0.85) else rng.choice(["off", "unavailable", "unknown", None])
    over[X.HOLD] = "clear" if (easy or rng.random() < 0.8) else rng.choice(["held", "unknown", "unavailable", None, "weird"])
    for eid in list(RANGE_OF) + [X.RESERVE]:
        if rng.random() < (0.015 if easy else 0.06):
            over[eid] = rng.choice(BAD_STATE)
    if rng.random() < (0.01 if easy else 0.05):
        over[X.SCH_START] = rng.choice(BAD_STATE)
    # the Export start gate and the leases consumer: mostly open for long enough, sometimes closed, unreadable, inconsistent, missing or young
    gate_ages = (600.0, 600.0)
    r = rng.random()
    if r < 0.06:
        over[X.EG] = ("off", {"blocked_by": rng.sample(["TIME_LEASES", "DUMP_ACTIVE", "OVERRIDE_ACTIVE", "TELEMETRY_STALE", "MANUAL_WRITE"], rng.randint(1, 3))})
    elif r < 0.08:
        over[X.EG] = ("unavailable", {})
    elif r < 0.10:
        over[X.EG] = ("on", {"blocked_by": ["TIME_LEASES"]})            # a gate that is on with a cause: inconsistent
    elif r < 0.12:
        over[X.EG] = ("off", {"blocked_by": []})                        # a gate that is off with no cause: inconsistent
    elif r < 0.14:
        over[X.EG] = ("on", {"blocked_by": rng.choice(["text", None, 3])})   # a list that cannot be read
    elif r < 0.16:
        over[X.EG] = None                                               # the gate does not exist
    elif r < 0.24:
        gate_ages = (float(rng.choice([0, 1, 30, 59, 59.9, 60, 61, 120])), 600.0)
    r = rng.random()
    if r < 0.05:
        over[X.TL] = rng.choice(["off", "unavailable", "unknown", None])
    elif r < 0.10:
        gate_ages = (gate_ages[0], float(rng.choice([0, 30, 59, 60, 61])))
    poll_age: "float | None" = float(rng.choice([0, 5, 30, 89, 90, 91, 200, -50, -95])) if (not easy and rng.random() < 0.3) else 0.0
    poll_text = None
    if rng.random() < 0.02:
        poll_text = rng.choice(["", "unknown", "Waiting", "2026-11-26T17:00:00", "abc"])
    capm = None
    if rng.random() < 0.3:
        capm = (rng.choice([rng.uniform(1, 40), rng.uniform(-5, 2000), "abc", None]), rng.choice(["measured", "measured", "configured", "estimated"]))
    return over, poll_age, poll_text, capm, gate_ages


def property_problems(w: X.CoordWorld, over: dict, capm: "tuple | None" = None, gate_ages: tuple = GATE_AGES) -> list[str]:
    """The properties no case may break, read from what the template published (no reference involved)."""
    bad: list[str] = []
    st = w.state(X.PROPOSAL)
    nums = {eid: w.state(eid) for eid in X.NUMERIC}
    if w.attr(X.PROPOSAL, "actionable") is not (st == "VALID"):
        return [f"actionable {w.attr(X.PROPOSAL, 'actionable')!r} in the state {st}: it is true only for VALID"]
    # the gate, read from the inputs themselves: a VALID proposal needs the Export start gate on with no cause that has read on for 60 s; a NOT ALLOWED one is the opposite
    g_state, g_attrs = X.split(X.HEALTHY[X.EG] if X.EG not in over else (over[X.EG] if over[X.EG] is not None else ("unknown", {})))
    g_list = g_attrs.get("blocked_by")
    g_open = g_state == "on" and isinstance(g_list, (list, tuple)) and len(g_list) == 0
    if st == "VALID" and not (g_open and gate_ages[0] >= 60):
        bad.append(f"VALID while the start gate reads {g_state} {g_list!r} after {gate_ages[0]} s: it must be open for 60 s")
    if st == "NOT ALLOWED" and g_open and gate_ages[0] >= 60:
        bad.append("NOT ALLOWED although the start gate is open and has been for 60 s")
    if st in ("VALID", "UNVERIFIED", "NOT ALLOWED"):
        try:
            floor, energy, power, net, dur = (float(nums[e]) for e in (X.P_FLOOR, X.P_ENERGY, X.P_POWER, X.P_NET, X.P_DUR))
        except ValueError:
            return [f"{st} but a number is not published: {nums}"]
        raw = {**X.HEALTHY, **over}

        def val(eid):
            return X.num(raw.get(eid), -1e18, 1e18)
        floors = [val(X.STOP_S), val(X.RESERVE), 10.0]
        if raw.get(X.LEASE) == "on":
            floors.append(val(X.L_STOP))                         # a running lease's latched Stop SOC is a member
        if any(f is None for f in floors) or floor < max(floors) or floor != int(floor):
            bad.append(f"the floor {floor} is below one of {floors} or not whole")
        if floor > 90:
            bad.append(f"the floor {floor} is above the dongle's range")
        if energy < 0:
            bad.append(f"the energy {energy} is below 0")
        if power > min(val(X.PCEIL), val(X.PROV)) or power < 0:
            bad.append(f"the power {power} is outside 0..min(ceiling {val(X.PCEIL)}, proven {val(X.PROV)})")
        if dur > val(X.WIN) or dur < 10 or dur != int(dur):
            bad.append(f"the duration {dur} is beyond the window {val(X.WIN)}, below 10 or not whole")
        if net < 500 or net > val(X.TGT):
            bad.append(f"the net export {net} is below 500 W or above the target")
        if net > val(X.MX) - max(100, 0.03 * val(X.MX)) + 1e-9:
            bad.append(f"the net export {net} leaves less than the START headroom under the export limit {val(X.MX)}")
        if st == "VALID" and (w.attr(X.PROPOSAL, "blocked_by") or w.attr(X.PROPOSAL, "limited_by") == "PROVEN_LEVEL"):
            bad.append("VALID with a blocking cause or limited by the proven level")
        if st == "NOT ALLOWED" and (not w.attr(X.PROPOSAL, "blocked_by") or w.attr(X.PROPOSAL, "limited_by") == "PROVEN_LEVEL"):
            bad.append("NOT ALLOWED with no gate code named, or limited by the proven level (that is UNVERIFIED)")
        if st == "UNVERIFIED" and not (float(w.attr(X.PROPOSAL, "raw_battery_power_w")) > val(X.PROV) and val(X.PCEIL) > val(X.PROV)):
            bad.append("UNVERIFIED without a requirement above the proven level and a ceiling above it")
        # a surplus of measured PV the target cannot hold is never proposed (the firmware's TARGET INFEASIBLE LOW and its export guard)
        surplus = val(X.PV) - val(X.LOAD)
        if surplus - net > 150 + 1e-9:
            bad.append(f"a PV surplus of {surplus} W above the net target {net} W plus 150 W is proposed")
        if surplus + 500 > val(X.MX) - max(100, 0.03 * val(X.MX)) + 1e-9:
            bad.append(f"a PV surplus of {surplus} W plus 500 W is above the export limit less the START headroom and is proposed")
        # the window: never longer than the time left in it, as the schedule counts it, and the end of the proposal is never later than the window end plus the schedule's own 20 s
        ws = X.schedule_start_ts(raw.get(X.SCH_START))
        if ws is None:
            bad.append("a proposal with an unreadable schedule start")
        else:
            we = ws + val(X.WIN) * 60
            if ws <= w.now_ts() < we:
                if dur > math.floor((we - w.now_ts() + 20) / 60) or w.now_ts() + dur * 60 > we + 20 + 1e-6:
                    bad.append(f"the duration {dur} ends after the window end {we} (now {w.now_ts()})")
            if raw.get(X.LEASE) == "on" and w.now_ts() >= we:
                bad.append(f"a proposal is {st} while a lease still runs after the window end {we} (now {w.now_ts()}): a running lease gets no time past its window")
        # the loop figures: what the dongle's own loop would do, never below the proposal's power, never above its ceiling
        lp, ld = w.attr(X.PROPOSAL, "loop_battery_power_w"), w.attr(X.PROPOSAL, "loop_duration_min")
        if lp is None or ld is None or lp > val(X.PCEIL) or lp < power or ld < 0 or ld > val(X.WIN) or (st == "VALID" and (lp != power or ld != dur)):
            bad.append(f"the loop figures {lp} W {ld} min against power {power} duration {dur} ceiling {val(X.PCEIL)} ({st})")
        # the exact rational minutes: the published duration is the exact value rounded DOWN (never up), from the readings and the published floor and net export
        cap = Fraction(raw[X.CAP].strip())
        if capm is not None and capm[1] == "measured" and X.num(capm[0], 1, 1000) is not None:
            cap = min(cap, Fraction(str(capm[0])))
        load, pv = Fraction(raw[X.LOAD].strip()), Fraction(raw[X.PV].strip())
        raw_exact = max(Fraction(net) + load - pv, 0)
        p_exact = max(min(Fraction(math.ceil(raw_exact / 500) * 500), Fraction(min(val(X.PCEIL), val(X.PROV)))), 500)      # CS-06: the power is rounded UP to 500 W (never above the clamp)
        e_exact = max(Fraction(raw[X.SOC].strip()) - Fraction(floor) - 1, 0) / 100 * cap * Fraction(90, 100)
        d_exact = min(e_exact * 1000 / p_exact * 60, Fraction(val(X.WIN)))
        if ws is not None and ws <= w.now_ts() < ws + val(X.WIN) * 60:
            d_exact = min(d_exact, Fraction(math.floor((ws + val(X.WIN) * 60 - w.now_ts() + 20) / 60)))
        if dur > d_exact + Fraction(1, 10 ** 9) or dur < d_exact - 1 - 4 - Fraction(1, 10 ** 9) or dur % 5 != 0:
            bad.append(f"the duration {dur} is not the exact {float(d_exact):.9f} minutes rounded down to a multiple of 5")
    else:
        if any(v != "unavailable" for v in nums.values()):
            bad.append(f"{st} but a numeric sensor reads {nums}")
        if st not in ("INVALID", "HOLD"):
            bad.append(f"the state {st} is not one of VALID, INVALID, UNVERIFIED, HOLD")
        if not w.attr(X.PROPOSAL, "blocked_by"):
            bad.append(f"{st} with no blocking cause named")
        if st == "HOLD" and "OVERRIDE_ACTIVE" not in w.attr(X.PROPOSAL, "blocked_by"):
            bad.append("HOLD without OVERRIDE_ACTIVE")
        if w.attr(X.PROPOSAL, "loop_battery_power_w") is not None or w.attr(X.PROPOSAL, "loop_duration_min") is not None:
            bad.append(f"{st} but the loop figures are published")
    return bad


def sweep_problems(n: int, seed: int, text: str | None = None, first_only: bool = False, properties: bool = True) -> tuple[list[str], dict]:
    rng = random.Random(seed)
    w = new_world(text)
    bad: list[str] = []
    tally = {"VALID": 0, "INVALID": 0, "UNVERIFIED": 0, "HOLD": 0, "NOT ALLOWED": 0}
    for i in range(n):
        over, age, ptext, capm, gages = random_case(rng)
        raw, skew, cm = apply_case(w, over, poll_age=age, poll_text=ptext, capm=capm, gate_ages=gages)
        ref = X.reference(raw, poll_skew_s=skew, capacity_attrs=cm, now_ts=w.now_ts(), gate_ages=gages)
        tally[ref["state"]] += 1
        bad += [f"case {i} {over}: {b}" for b in compare(w, ref)]
        if properties:
            bad += [f"case {i}: {b}" for b in property_problems(w, over, capm, gages)]
        if bad and first_only:
            return bad, tally
    return bad, tally


# ===========================================================================================================================
# [4] the lease: the comparison and the re-target
# ===========================================================================================================================
def lease_world(text: str | None = None, this_mode: str = "ha", over: dict | None = None, memory_s: float | None = 7200.0, feed: float = 10.0) -> X.CoordWorld:
    """A healthy world with the dongle polling every `feed` seconds. The re-target memory is given an age of `memory_s` seconds (a test hook: the real-time tests below advance the clock instead);
    None leaves it as the world made it."""
    w = new_world(text, this_mode=this_mode)
    w.make_healthy(over)
    w.start_feed(feed)
    if memory_s is not None:
        w.set_memory_age(memory_s)
    return w


def lease_state(w: X.CoordWorld) -> dict:
    s = w.snapshot()
    rt, cm = s[X.RETARGET], s[X.COMPARE]
    return {"rt": rt[0], "reasons": rt[1].get("reasons"), "changes": rt[1].get("changes"), "wait": rt[1].get("wait_until_ts"), "cmp": cm[0], "cmp_attrs": cm[1], "last": rt[1].get("last_would_change_ts"),
            "proposal": s[X.PROPOSAL][0], "origin": rt[1].get("lease_origin"), "rt_attrs": rt[1]}


def reasons_have(st: dict, code: str) -> bool:
    return any(r.startswith(code + ":") for r in (st["reasons"] or []))


END_SLACK_S = 21.0     # the schedule's own 20 s rounding of the time left in its window, and a second for the whole-second window end the model publishes


def run_end_problems(w: X.CoordWorld, label: str = "") -> list[str]:
    """The property of EVERY render while a lease runs, read from what the template published (no reference involved). A VALID or UNVERIFIED proposal never ends (now plus its duration, and now plus the
    loop's duration) after the window end plus the schedule's own 20 s, and for a lease the schedule started never after the lease's own latched end plus 20 s either; nothing is VALID or UNVERIFIED after the
    window end while the lease still runs; and a lease the schedule started is never listed an END change (its proposed end cannot be later than its own end, so the END rule cannot fire for it)."""
    bad: list[str] = []
    if w.errors:
        bad.append(f"{label}: template errors {w.errors[:2]}")
    if w.state(X.LEASE) != "on":
        return bad
    now = w.now_ts()
    scheduled = w.attr(X.RETARGET, "lease_origin") == "SCHEDULE"
    if scheduled and any(str(c).startswith("END ") for c in (w.attr(X.RETARGET, "changes") or [])):
        bad.append(f"{label}: a lease the schedule started is listed an END change {w.attr(X.RETARGET, 'changes')}")
    if w.state(X.PROPOSAL) not in ("VALID", "UNVERIFIED"):
        return bad
    we, own = w.attr(X.PROPOSAL, "window_end_ts"), w.attr(X.COMPARE, "end_lease_ts")
    try:
        ends = {"proposal": now + float(w.state(X.P_DUR)) * 60, "loop": now + float(w.attr(X.PROPOSAL, "loop_duration_min")) * 60}
    except (TypeError, ValueError):
        return bad + [f"{label}: a {w.state(X.PROPOSAL)} proposal without a duration while a lease runs"]
    for name, end in ends.items():
        if we is None or end > we + END_SLACK_S:
            bad.append(f"{label}: the {name} ends {end - (we or 0):+.0f} s from the window end while a lease runs (limit +20 s)")
        if scheduled and (own is None or end > own + END_SLACK_S):
            bad.append(f"{label}: the {name} ends {end - (own or 0):+.0f} s from the end of the lease the schedule started (limit +20 s)")
    if we is not None and now >= we:
        bad.append(f"{label}: a {w.state(X.PROPOSAL)} proposal {now - we:+.0f} s from the window end while the lease still runs: it gets no time")
    return bad


STOP50 = {X.STOP_S: "50.0"}      # the floor is 50 (above the reserve 40): a lease latched at 49, 50 or 51 is not under the lease guard's reserve rule
# healthy, STOP50: 29 points x 0.30 x 0.90 = 7.83 kWh at 3800 W = 123 minutes


def lease_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    bad: list[str] = []

    def expect(label: str, cond: bool, detail: str = "") -> None:
        if not cond:
            bad.append(f"{label}: {detail}")

    # no lease
    w = lease_world(text)
    st = lease_state(w)
    expect("no lease", st["rt"] == "NOT RUNNING" and st["cmp"] == "NOT RUNNING" and st["origin"] == "", str(st["rt"]) + str(st["cmp"]))
    for bad_flag in ("unavailable", "unknown", None, "weird"):
        w.bulk({X.LEASE: bad_flag})
        st = lease_state(w)
        expect(f"lease flag {bad_flag!r}", st["rt"] == "UNKNOWN" and st["cmp"] == "UNKNOWN" and reasons_have(st, "LEASE_UNREADABLE") and st["changes"] == [], str(st["rt"]))
        w.bulk({X.HOLD: "held"})
        st = lease_state(w)
        expect(f"lease flag {bad_flag!r} and a hold: nothing is known to run, so nothing ends", st["rt"] == "UNKNOWN", str(st["rt"]))
        w.bulk({X.HOLD: "clear"})
    w.bulk({X.LEASE: "off", X.HOLD: "held"})
    expect("a hold and no lease", lease_state(w)["rt"] == "NOT RUNNING", lease_state(w)["rt"])
    for bad_flag in ("unavailable", "unknown", "weird"):
        w = lease_world(text, over=STOP50)
        w.sched_lease_on(stop=49, export=2800, command=3500, age_min=45)
        w.bulk({X.LEASE: bad_flag})
        w.age(X.LEASE, 2700.0)                                  # the flag changed 45 minutes ago, as the start script and the window say: every other fact of the scheduled lease still reads
        st = lease_state(w)
        ca = st["cmp_attrs"]
        expect(f"a lease flag that reads {bad_flag!r} while every other fact of a scheduled lease reads: nothing is compared, no origin, no difference", st["rt"] == "UNKNOWN" and st["cmp"] == "UNKNOWN"
               and st["origin"] == "" and all(ca.get(k) is None for k in ("stop_soc_difference", "export_w_difference", "battery_w_difference", "battery_w_loop_difference", "end_difference_min"))
               and st["changes"] == [], f"{st['rt']} {st['cmp']} {st['origin']} {ca}")
    # the baseline lease: the schedule started it (a 240 minute window), 10 minutes ago, latched Stop SOC 49 (the floor is 50), the proposal is floor 50, net 3000, power 3800, 123 minutes
    w = lease_world(text, over=STOP50)
    w.sched_lease_on(stop=49, export=3000, command=3500, age_min=29.0)
    w.advance(0)
    st = lease_state(w)
    expect("a lease 29 minutes old with a deviation waits", st["rt"] == "WAIT" and reasons_have(st, "LEASE_TOO_YOUNG") and st["cmp"] == "DIFFERS" and st["origin"] == "SCHEDULE", str(st["rt"]))
    expect("the wait ends 30 minutes after the lease start", st["wait"] is not None and abs(st["wait"] - (w.w.changed_at[X.LEASE] + 1800)) < 1, str(st["wait"]))
    expect("what it would change is named, and nothing else", [c.split(" ")[0] for c in st["changes"]] == ["STOP_SOC"] and st["changes"][0].startswith("STOP_SOC 49.0 -> 50 (a raise"), str(st["changes"]))
    w.w.run_until(w.w.changed_at[X.LEASE] + 1799)
    w.force()
    st = lease_state(w)
    expect("29 min 59 s old still waits", st["rt"] == "WAIT" and reasons_have(st, "LEASE_TOO_YOUNG"), st["rt"])
    w.advance(1)
    st = lease_state(w)
    expect("30 min old is allowed", st["rt"] == "ALLOWED" and not st["reasons"] and st["last"] == w.now_ts(), f"{st['rt']} {st['last']}")
    entry = st["last"]
    w.advance(60)
    st = lease_state(w)
    expect("an episode continues while the deviation stands", st["rt"] == "ALLOWED" and st["last"] == entry, f"{st['rt']} {st['last']}")
    # in line: the latched values equal the proposal; the lease's end later than the energy needs is no deviation
    w.bulk({X.L_STOP: "50.0", X.L_EXP: "3000.0"})
    st = lease_state(w)
    expect("in line (the lease outlasting the energy needs no change)", st["rt"] == "NO CHANGE" and st["cmp"] == "IN LINE" and st["changes"] == [], f"{st['rt']} {st['cmp']}")
    w.bulk({X.L_STOP: "49.0"})
    st = lease_state(w)
    expect("a deviation within 30 minutes of the previous would-change waits", st["rt"] == "WAIT" and reasons_have(st, "RECENT_CHANGE") and abs(st["wait"] - (entry + 1800)) < 1,
           f"{st['rt']} {st['reasons']} {st['wait']}")
    for offset, want in ((900, "WAIT"), (1799, "WAIT"), (1800, "ALLOWED")):
        w.w.run_until(entry + offset)
        w.force()
        st = lease_state(w)
        expect(f"{offset} s after the previous would-change", st["rt"] == want and (want == "ALLOWED" or reasons_have(st, "RECENT_CHANGE")), f"{st['rt']} {st['reasons']} want {want}")
    expect("and the second would-change is stamped", lease_state(w)["last"] == entry + 1800, str(lease_state(w)["last"]))
    # the previous would-change is in the FUTURE (the clock moved back): the gap rule still holds
    w = lease_world(text, over=STOP50)
    w.sched_lease_on(stop=49, export=3000, command=3800, age_min=45)
    w.set_memory_age(7200, rt_entry=w.now_ts() + 600, rt_state="WAIT")
    w.force()
    st = lease_state(w)
    expect("a previous would-change in the future waits", st["rt"] == "WAIT" and reasons_have(st, "RECENT_CHANGE") and abs(st["wait"] - (w.now_ts() + 600 + 1800)) < 1, f"{st['rt']} {st['reasons']} {st['wait']}")
    # the four spellings of `this`
    for mode in ("none", "undefined"):
        w2 = lease_world(text, this_mode=mode, over=STOP50)
        w2.sched_lease_on(stop=49, export=3000, command=3800, age_min=40)
        w2.advance(60)
        st = lease_state(w2)
        expect(f"`this` is {mode}: never ALLOWED, and it says why", st["rt"] == "WAIT" and reasons_have(st, "MEMORY_UNAVAILABLE") and not w2.errors, f"{st['rt']} {w2.errors[:2]}")
    for mode in ("ha", "first-none"):
        w2 = lease_world(text, this_mode=mode, over=STOP50)
        w2.sched_lease_on(stop=49, export=3000, command=3800, age_min=40)
        w2.advance(60)
        st = lease_state(w2)
        expect(f"`this` is {mode}: the memory carries, ALLOWED", st["rt"] == "ALLOWED" and not w2.errors, f"{st['rt']} {w2.errors[:2]}")
    # a template reload (the model's state leaves the state machine: `this` is a state object with no attributes, or none): the memory starts afresh, nothing is allowed for 30 minutes
    for mode in ("ha", "first-none"):
        w2 = lease_world(text, this_mode=mode, over=STOP50)
        w2.sched_lease_on(stop=49, export=3000, command=3800, age_min=40)
        w2.advance(60)
        first = lease_state(w2)
        w2.advance(300)
        w2.reload()
        st = lease_state(w2)
        # right after a reload `this` is a state object with no attributes ("ha": the memory is young) or none ("first-none": the first render cannot read its own state at all); both wait
        expect(f"`this` is {mode}: a template reload does not allow a second change 5 minutes after the first", first["rt"] == "ALLOWED" and st["rt"] == "WAIT"
               and reasons_have(st, "MEMORY_YOUNG" if mode == "ha" else "MEMORY_UNAVAILABLE") and st["last"] is None and not w2.errors, f"{first['rt']} {st['rt']} {st['reasons']} {w2.errors[:2]}")
        expect(f"`this` is {mode}: the wait is 30 minutes from the reload", st["wait"] is not None and abs(st["wait"] - (w2.now_ts() + 1800)) < 1, str(st["wait"]))
        w2.advance(10)
        st = lease_state(w2)
        expect(f"`this` is {mode}: the memory carries on after the reload", st["rt"] == "WAIT" and reasons_have(st, "MEMORY_YOUNG") and abs(st["wait"] - (w2.w.t + w2.w.clock_offset - 10 + 1800)) < 1, f"{st['rt']} {st['wait']}")
        for seconds, want in ((1799, "WAIT"), (1800, "ALLOWED")):
            w2.set_memory_age(seconds)
            w2.force()
            st = lease_state(w2)
            expect(f"the memory is {seconds} s old", st["rt"] == want and (want == "ALLOWED" or reasons_have(st, "MEMORY_YOUNG")), f"{st['rt']} {st['reasons']}")
    # what the memory says about its own continuity: a start no more than 5 s in the future is kept as it is, a later one starts afresh; there is no pause rule any more (the model carries no time of its
    # evaluation: decision D-C04a, route a) and a memory of any age, a month included, carries on
    for mem_s, want in ((3600, "ALLOWED"), (-5, "WAIT"), (-6, "WAIT"), (1800, "ALLOWED"), (1799, "WAIT"), (86400 * 30, "ALLOWED")):
        w2 = lease_world(text, over=STOP50)
        w2.sched_lease_on(stop=49, export=3000, command=3800, age_min=45)
        w2.set_memory_age(mem_s)
        w2.force()
        st = lease_state(w2)
        expect(f"the memory is {mem_s} s old", st["rt"] == want and (want == "ALLOWED" or reasons_have(st, "MEMORY_YOUNG")) and w2.model().get("mem_since_ts") is not None, f"{st['rt']} {st['reasons']}")
        if want == "WAIT" and mem_s < -5:
            expect("a memory that starts in the future starts afresh", w2.model().get("mem_since_ts") == math.floor(w2.now_ts()), str(w2.model().get("mem_since_ts")))
    # each deviation alone, at its deadband (a lease the schedule started, 45 minutes ago, plenty of window left; the floor is 50: 7.83 kWh, 123 minutes)
    def case(label: str, stop, export, end_min, want: str, **kw):
        w3 = lease_world(text, over=STOP50)
        w3.sched_lease_on(stop=stop, export=export, command=3800, age_min=45, ends_in_min=end_min)
        s3 = lease_state(w3)
        expect(label, s3["rt"] == want and not w3.errors, f"{s3['rt']} want {want} {s3['reasons']} {s3['changes']} {w3.errors[:2]}")
    case("everything in line", 50, 3000, 190, "NO CHANGE")
    case("the Stop SOC 1 point lower", 49, 3000, 190, "ALLOWED")
    case("the lease latched 1 point above the schedule's Stop SOC: the floor follows it (never below what the lease enforces), nothing to change", 51, 3000, 190, "NO CHANGE")
    case("the lease latched 0.5 points above the floor 50: the floor is 51, 0.5 points off is no deviation", 50.5, 3000, 190, "NO CHANGE")
    case("the target export 200 W off", 50, 2800, 190, "ALLOWED")
    case("the target export 200 W the other way", 50, 3200, 190, "ALLOWED")
    case("the target export 100 W off is no deviation", 50, 2900, 190, "NO CHANGE")
    # the END rule never fires for a lease the schedule started: its proposed end is bounded by its own latched end plus the schedule's 20 s (a lease is never extended beyond the window it was authorised
    # for), which is far below the 20 minute deadband; the rule stays as a second line and its mutants are killed by the literal pins, no behaviour reaches it
    case("the energy lasts 20 minutes beyond the lease: no END beyond the run's own end is proposed", 50, 3000, 103, "NO CHANGE")
    case("the energy lasts 19 minutes beyond the lease", 50, 3000, 104, "NO CHANGE")
    case("the energy lasts two hours beyond the lease: still no END beyond the run's own end", 50, 3000, 3, "UNKNOWN")
    case("the energy lasts an hour beyond the lease", 50, 3000, 63, "NO CHANGE")
    case("the lease outlasting the energy by an hour is no deviation", 50, 3000, 183, "NO CHANGE")
    # the lease facts that cannot be read
    for label, over_l, code in (("the latched Stop SOC", {X.L_STOP: "unknown"}, "PROPOSAL_NOT_VALID"), ("the latched target", {X.L_EXP: "unavailable"}, "LEASE_FACTS_UNREADABLE"),
                                ("the end time", {X.L_END: "Active - end time unavailable"}, "LEASE_FACTS_UNREADABLE"), ("the end time text", {X.L_END: "soon"}, "LEASE_FACTS_UNREADABLE"),
                                ("the end time missing", {X.L_END: None}, "LEASE_FACTS_UNREADABLE"), ("a negative latched Stop SOC", {X.L_STOP: "-5"}, "PROPOSAL_NOT_VALID"),
                                ("the end text of an inactive lease", {X.L_END: "Inactive"}, "LEASE_FACTS_UNREADABLE")):
        w4 = lease_world(text, over=STOP50)
        w4.sched_lease_on(stop=49, export=3000, command=3500, age_min=45)
        w4.bulk(over_l)
        s4 = lease_state(w4)
        # (the latched Stop SOC is a member of the floor while a lease runs: unreadable, the proposal itself is INVALID)
        expect(f"{label} cannot be read", s4["rt"] == "UNKNOWN" and s4["cmp"] == "UNKNOWN" and reasons_have(s4, code) and s4["changes"] == [], f"{s4['rt']} {s4['reasons']}")
    # an end time that reads before now or before the lease start is never read: the lease would otherwise look as if it ended
    for label, shift in (("a minute before now", -60), ("a second before now", -1), ("now", 0)):
        w4 = lease_world(text, over=STOP50)
        w4.sched_lease_on(stop=49, export=3000, command=3500, age_min=45)
        w4.bulk({X.L_END: w4.local_text(w4.now_ts() + shift)})
        s4 = lease_state(w4)
        expect(f"an end time {label} cannot be read", s4["rt"] == "UNKNOWN" and s4["cmp"] == "UNKNOWN" and reasons_have(s4, "LEASE_FACTS_UNREADABLE") and s4["cmp_attrs"].get("end_lease_ts") is None,
               f"{s4['rt']} {s4['reasons']}")
    w4 = lease_world(text, over=STOP50)
    w4.sched_lease_on(stop=49, export=3000, command=3500, age_min=45)
    w4.bulk({X.L_END: w4.local_text(w4.now_ts() + 1)})
    s4 = lease_state(w4)
    expect("an end time a second ahead is read (the lease has no time left to propose: the proposal is INVALID, the re-target UNKNOWN for that reason and not for an unreadable fact)",
           s4["cmp_attrs"].get("end_lease_ts") == w4.now_ts() + 1 and s4["origin"] == "SCHEDULE" and s4["proposal"] == "INVALID" and s4["rt"] == "UNKNOWN" and reasons_have(s4, "PROPOSAL_NOT_VALID")
           and not reasons_have(s4, "LEASE_FACTS_UNREADABLE"), f"{s4['rt']} {s4['cmp_attrs'].get('end_lease_ts')} {s4['reasons']}")
    w4 = lease_world(text, over=STOP50)
    w4.sched_lease_on(stop=49, export=3000, command=3500, age_min=45)
    w4.bulk({X.L_END: w4.local_text(w4.now_ts() - 2700 - 1)})     # one second before the lease started (and before now)
    expect("an end time before the lease start cannot be read", lease_state(w4)["rt"] == "UNKNOWN", lease_state(w4)["rt"])
    w4 = lease_world(text, over=STOP50)
    w4.sched_lease_on(stop=49, export=3000, command=3500, age_min=0)       # the lease has just started and its end lies before that start by the clock having moved: end 300 s ahead, start 600 s ahead
    w4.w.changed_at[X.LEASE] = w4.now_ts() + 600
    w4.bulk({X.L_END: w4.local_text(w4.now_ts() + 300)})
    expect("an end time before the lease start (a start that appears to be in the future) cannot be read", lease_state(w4)["cmp_attrs"].get("end_lease_ts") is None and lease_state(w4)["rt"] == "UNKNOWN",
           str(lease_state(w4)["rt"]))
    # a proposal that is not VALID gives nothing to change to: UNKNOWN with no change listed (a hold is END NOW, below)
    for label, over_p, want in (("INVALID", {X.SOC: "unknown"}, "INVALID"), ("UNVERIFIED", {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}, "UNVERIFIED")):
        w5 = lease_world(text, over=STOP50)
        w5.sched_lease_on(stop=49, export=3000, command=3500, age_min=45)
        w5.bulk(over_p)
        s5 = lease_state(w5)
        expect(f"a {label} proposal", s5["rt"] == "UNKNOWN" and s5["proposal"] == want and reasons_have(s5, "PROPOSAL_NOT_VALID") and s5["changes"] == [], f"{s5['rt']} {s5['proposal']} {s5['reasons']} {s5['changes']}")
    # a clock that moved: the lease appears to have started in the future
    w6 = lease_world(text, over=STOP50)
    w6.sched_lease_on(stop=49, export=3000, command=3500, age_min=0)
    w6.w.changed_at[X.LEASE] = w6.now_ts() + 600
    w6.force()
    s6 = lease_state(w6)
    expect("a lease started in the future", s6["rt"] == "WAIT" and reasons_have(s6, "CLOCK_BACKWARDS"), f"{s6['rt']} {s6['reasons']}")
    # stale telemetry during a lease: nothing is allowed
    w7 = lease_world(text, over=STOP50)
    w7.sched_lease_on(stop=50, export=2800, command=3500, age_min=45)
    w7.stop_feed()
    w7.advance(5 * 60)
    s7 = lease_state(w7)
    expect("the telemetry stops: the proposal is INVALID and no change is allowed", s7["proposal"] == "INVALID" and s7["rt"] == "UNKNOWN", f"{s7['proposal']} {s7['rt']}")
    # the comparison's numbers: a lease the schedule started 45 minutes ago, Stop SOC 49, 2800 W, ceiling 3500 W (proposal 50 %, 3000 W, 3800 W, 123 minutes, the lease ends at the window end)
    w8 = lease_world(text, over=STOP50)
    w8.sched_lease_on(stop=49, export=2800, command=3500, age_min=45)
    w8.advance(0)
    ca = lease_state(w8)["cmp_attrs"]
    # the window end is 11695 s ahead (240 minutes less 45 minutes less the 5 s the window began before the lease); the energy lasts 123 minutes: 123 - 194.9 = -71.9
    expect("the comparison shows both sides and the signed differences", ca.get("stop_soc_proposed") == 50 and ca.get("stop_soc_lease") == 49.0 and ca.get("stop_soc_difference") == 1.0
           and ca.get("export_w_proposed") == 3000 and ca.get("export_w_lease") == 2800.0 and ca.get("export_w_difference") == 200.0 and ca.get("battery_w_proposed") == 4000
           and ca.get("battery_w_loop") == 4000 and ca.get("battery_w_commanded") == 3500.0 and ca.get("battery_w_difference") == 500.0 and ca.get("battery_w_loop_difference") == 500.0
           and ca.get("end_difference_min") == -78 and ca.get("end_lease_ts") == w8.now_ts() + 11695, str(ca))
    # the comparison and the re-target of an UNVERIFIED proposal: the live-like limits. The re-target is UNKNOWN with no change listed (it was a list that said END + 127 minutes); the comparison shows the
    # loop: 4656 W expected against the 4600 W commanded, and the END difference is the loop's (118 minutes: 77 minutes short of the lease's end at the window end), not the clamp's (183 minutes: 12 short).
    # The lease latched an export target 300 W below the proposal's, which is what makes the comparison DIFFER
    live = {X.PCEIL: "8000.0", X.PROV: "3000.0", X.LOAD: "1656.0", X.SOC: "60.0", X.STOP_S: "25.0", X.RESERVE: "25"}
    w9 = lease_world(text, over=live)
    w9.sched_lease_on(stop=25, export=2700, command=4600, age_min=45)
    s9 = lease_state(w9)
    ca = s9["cmp_attrs"]
    expect("an UNVERIFIED proposal: the re-target is UNKNOWN with no change listed", s9["rt"] == "UNKNOWN" and s9["proposal"] == "UNVERIFIED" and reasons_have(s9, "PROPOSAL_NOT_VALID") and s9["changes"] == [], f"{s9['rt']} {s9['changes']}")
    expect("an UNVERIFIED proposal: the comparison shows how the live loop compares (the loop's power and END, and the clamp)", s9["cmp"] == "DIFFERS" and ca.get("battery_w_proposed") == 3000 and ca.get("battery_w_loop") == 5000
           and ca.get("battery_w_commanded") == 4600.0 and ca.get("battery_w_difference") == -1600.0 and ca.get("battery_w_loop_difference") == 400.0 and ca.get("export_w_difference") == 300.0
           and ca.get("end_difference_min") == -85, str(ca))
    # ---- F1: the schedule's own window bounds the proposal and the re-target ---------------------------------------------------------------------------------------
    p1 = {X.STOP_S: "25.0", X.RESERVE: "25", X.SOC: "93.0"}               # plenty of energy: 67 points x 0.30 x 0.90 = 18.09 kWh = 285 minutes at 3800 W
    for label, win, age, want_dur in (("a full-window lease 35 minutes in", 240, 35, 205), ("the same lease 90 minutes in", 240, 90, 150), ("a 120 minute window, 31 minutes in", 120, 31, 89),
                                      ("a 120 minute window, 100 minutes in (20 minutes left)", 120, 100, 20), ("a 30 minute window, 5 minutes in", 30, 5, 25)):
        w = lease_world(text, over={**p1, X.WIN: str(float(win))})
        w.sched_lease_on(stop=25, export=3000, command=3800, age_min=age, window_min=win)
        w.set_memory_age(7200)
        w.force()
        s = lease_state(w)
        win_end = w.attr(X.PROPOSAL, "window_end_ts")
        dur = w.attr(X.PROPOSAL, "loop_duration_min")
        expect(f"{label}: IN LINE, never a later END; the duration is the time left in the window", s["rt"] == "NO CHANGE" and s["cmp"] == "IN LINE" and s["changes"] == [] and s["origin"] == "SCHEDULE"
               and w.state(X.P_DUR) == str(want_dur // 5 * 5) and dur == want_dur // 5 * 5 and w.now_ts() + want_dur * 60 <= win_end + 20 and not w.errors,
               f"{s['rt']} {s['cmp']} {s['changes']} {w.state(X.P_DUR)} {dur} {s['origin']}")
        w.advance(1800)                                              # half an hour later it is still in line, still never ALLOWED to a later END
        w.set_memory_age(7200)
        w.force()
        s = lease_state(w)
        expect(f"{label}: and half an hour later", s["rt"] in ("NO CHANGE", "UNKNOWN") and s["changes"] == [] and s["rt"] != "ALLOWED", f"{s['rt']} {s['changes']}")
    # a late start: the window began 85 minutes before the lease, which the schedule capped at the window end
    w = lease_world(text, over={**p1})
    w.sched_lease_on(stop=25, export=3000, command=3800, age_min=5, start_gap_s=85 * 60)
    s = lease_state(w)
    expect("a late start (85 minutes into the window, 5 minutes ago): the lease ends at the window end, IN LINE, no END beyond it", s["rt"] == "NO CHANGE" and s["cmp"] == "IN LINE" and s["origin"] == "SCHEDULE"
           and s["changes"] == [] and w.state(X.P_DUR) == str(math.floor((240 * 60 - 90 * 60 - 5 + 20) / 60 + 0) // 5 * 5), f"{s['rt']} {s['cmp']} {s['origin']} {w.state(X.P_DUR)}")
    # a lease the schedule did not start: a 60 minute manual lease 31 minutes in (the schedule helpers say 240 minutes: the lease is not judged against them)
    w = lease_world(text, over=p1)
    w.lease_on(stop=25, export=3000, command=3800, ends_in_min=29, age_min=31)
    s = lease_state(w)
    ca = s["cmp_attrs"]
    expect("a 60 minute manual lease 31 minutes in: UNKNOWN, LEASE_ORIGIN_UNKNOWN, no change listed, no difference published (it was ALLOWED to END + 211 minutes)", s["rt"] == "UNKNOWN" and s["cmp"] == "UNKNOWN"
           and reasons_have(s, "LEASE_ORIGIN_UNKNOWN") and s["changes"] == [] and s["origin"] == "OTHER" and ca.get("stop_soc_difference") is None and ca.get("export_w_difference") is None
           and ca.get("end_difference_min") is None and ca.get("battery_w_difference") is None and ca.get("battery_w_loop_difference") is None and ca.get("stop_soc_lease") == 25.0 and ca.get("end_lease_ts") is not None,
           f"{s['rt']} {s['cmp']} {s['reasons']} {s['changes']} {ca}")
    # what makes a lease the schedule's (each condition on its own, at its boundary)
    def origin_case(label: str, want: str, *, run_gap_s=3.0, start_gap_s=5.0, ends_delta_s=0.0, script=True, window_min=240.0, age_min=45.0):
        wo = lease_world(text, over=p1)
        wo.sched_lease_on(stop=25, export=3000, command=3800, age_min=age_min, window_min=window_min, start_gap_s=start_gap_s, run_gap_s=run_gap_s, script=script)
        w_end = T0 - age_min * 60 - start_gap_s + window_min * 60
        wo.bulk({X.L_END: wo.local_text(w_end + ends_delta_s)})
        so = lease_state(wo)
        expect(label, so["origin"] == want and (so["cmp"] != "UNKNOWN") == (want == "SCHEDULE") and (so["rt"] != "UNKNOWN") == (want == "SCHEDULE") and not wo.errors,
               f"{so['origin']} {so['cmp']} {so['rt']} {so['reasons']}")
    origin_case("the schedule started it", "SCHEDULE")
    origin_case("no start script ran at all", "OTHER", script=False)
    origin_case("the start script ran 900 s before the lease", "SCHEDULE", run_gap_s=900.0)
    origin_case("the start script ran 901 s before the lease", "OTHER", run_gap_s=901.0)
    origin_case("the start script ran 2 hours before the lease (an earlier run)", "OTHER", run_gap_s=7200.0)
    origin_case("the start script ran 10 s after the lease flag changed (two clocks)", "SCHEDULE", run_gap_s=-10.0)
    origin_case("the start script ran 11 s after the lease flag changed", "OTHER", run_gap_s=-11.0)
    origin_case("the lease turned on 60 s before the window start", "SCHEDULE", start_gap_s=-60.0)
    origin_case("the lease turned on 61 s before the window start", "OTHER", start_gap_s=-61.0)
    origin_case("the window starts a day after the lease (the schedule was armed for tomorrow while it ran)", "OTHER", start_gap_s=-86400.0)
    origin_case("the lease ends 120 s after the window end", "SCHEDULE", ends_delta_s=120.0)
    origin_case("the lease ends 121 s after the window end", "OTHER", ends_delta_s=121.0)
    origin_case("the lease ends an hour before the window end", "SCHEDULE", ends_delta_s=-3600.0)
    wo = lease_world(text, over=p1)
    wo.sched_lease_on(stop=25, export=3000, command=3800, age_min=45)
    wo.bulk({X.WIN: "205.0"})                                  # the owner shortened the window while the lease ran: the lease ends 35 minutes after the window end
    so = lease_state(wo)
    expect("the owner shortened the window while the lease ran (it ends 35 minutes after the window end): not the schedule's lease any more", so["origin"] == "OTHER" and so["rt"] == "UNKNOWN"
           and reasons_have(so, "LEASE_ORIGIN_UNKNOWN"), f"{so['origin']} {so['rt']} {so['reasons']}")
    # the owner raised the window while the lease ran (it ends 135 minutes before the window end) and the energy lasts beyond the lease: the run was authorised for ITS window, the one captured at its start
    # (its own latched end), so no END beyond that end is proposed, only the 20 s the schedule rounds by; the re-target keeps the end (RC2 of the second review)
    wo = lease_world(text, over={**p1})
    wo.sched_lease_on(stop=25, export=3000, command=3800, age_min=45, ends_in_min=60)
    so = lease_state(wo)
    own_end = wo.attr(X.COMPARE, "end_lease_ts")
    expect("a lease that ends before the window end and the energy lasts beyond it: NO CHANGE, the proposed end is the lease's own end (never later than it plus the schedule's 20 s)",
           so["rt"] == "NO CHANGE" and so["cmp"] == "IN LINE" and so["changes"] == [] and so["origin"] == "SCHEDULE" and wo.state(X.P_DUR) == "60" and wo.attr(X.PROPOSAL, "loop_duration_min") == 60
           and own_end == wo.now_ts() + 3600 and wo.now_ts() + 60 * 60 <= own_end + 20 and not wo.errors, f"{so['rt']} {so['cmp']} {so['changes']} {wo.state(X.P_DUR)} {wo.attr(X.PROPOSAL, 'loop_duration_min')}")
    # the same lease after the owner edits the duration or the start helper (the schedule disarms after its start, so the card lets the owner edit them for the next night): nothing moves the bound (RC2)
    for label, edit, want_dur, want_origin in (("the duration raised to 240", {X.WIN: "240.0"}, "20", "SCHEDULE"), ("the duration raised to 61", {X.WIN: "61.0"}, "20", "SCHEDULE")):
        we2 = lease_world(text, over={**p1, X.WIN: "60.0"})
        we2.sched_lease_on(stop=25, export=3000, command=3800, age_min=40, window_min=60)
        before = lease_state(we2)
        we2.bulk(edit)
        we2.set_memory_age(7200)
        we2.force()
        after = lease_state(we2)
        expect(f"a scheduled lease 40 minutes into its 60 minute window, then {label}: it stays in line, its end is its own", before["rt"] == "NO CHANGE" and before["cmp"] == "IN LINE" and after["rt"] == "NO CHANGE"
               and after["cmp"] == "IN LINE" and after["changes"] == [] and after["origin"] == want_origin and we2.state(X.P_DUR) == want_dur and not run_end_problems(we2, label),
               f"{before['rt']} {after['rt']} {after['cmp']} {after['changes']} {after['origin']} {we2.state(X.P_DUR)} {run_end_problems(we2, label)}")
    # ---- F5: END NOW (the lease guard's rule), outside the 30 minute rules --------------------------------------------------------------------------------------
    def end_case(label: str, want: str, *, over=None, stop=30, age_min=10.0, scheduled=True, after=None, code=None):
        we = lease_world(text, over=over)
        if scheduled:
            we.sched_lease_on(stop=stop, export=3000, command=3800, age_min=age_min)
        else:
            we.lease_on(stop=stop, export=3000, command=3800, ends_in_min=100, age_min=age_min)
        if after:
            we.bulk(after)
        se = lease_state(we)
        expect(label, se["rt"] == want and (code is None or reasons_have(se, code)) and not we.errors and (want != "END NOW" or not reasons_have(se, "LEASE_TOO_YOUNG")), f"{se['rt']} {se['reasons']}")
        return se
    se = end_case("the reserve (40) is above the Stop SOC the lease latched (30), the lease 10 minutes old: END NOW, never WAIT", "END NOW", code="RESERVE_ABOVE_LEASE_STOP_SOC")
    expect("END NOW still compares and lists what it would change", se["cmp"] == "DIFFERS" and any(c.startswith("STOP_SOC 30.0 -> 40 (a raise") for c in se["changes"]), f"{se['cmp']} {se['changes']}")
    end_case("a lease that was not started by the schedule: the same rule", "END NOW", scheduled=False, code="RESERVE_ABOVE_LEASE_STOP_SOC")
    end_case("a lease 1 minute old", "END NOW", age_min=1.0)
    end_case("the reserve equals the latched Stop SOC: no", "NO CHANGE", stop=40)
    end_case("the reserve is 1 above: yes", "END NOW", stop=39)
    end_case("the reserve 40 against a latched 39.5: yes", "END NOW", stop=39.5)
    end_case("the reserve below the latched Stop SOC: no", "NO CHANGE", stop=41, over={X.STOP_S: "41.0"})
    end_case("a Hold battery (the proposal is HOLD, with no number)", "END NOW", stop=40, over={X.HOLD: "held"}, code="HOLD_ACTIVE")
    end_case("a hold and a lease the schedule did not start", "END NOW", stop=40, over={X.HOLD: "held"}, scheduled=False, code="HOLD_ACTIVE")
    se = end_case("a hold and a reserve above the latched Stop SOC: both are named", "END NOW", stop=30, over={X.HOLD: "held"}, code="HOLD_ACTIVE")
    expect("both causes are named", reasons_have(se, "RESERVE_ABOVE_LEASE_STOP_SOC"), str(se["reasons"]))
    end_case("a hold that cannot be read does not end anything", "UNKNOWN", stop=40, over={X.HOLD: "unknown"})
    end_case("a hold that is unavailable does not end anything", "UNKNOWN", stop=40, over={X.HOLD: "unavailable"})
    end_case("a reserve that cannot be read does not end anything", "UNKNOWN", stop=30, over={X.RESERVE: "unknown"})
    end_case("a reserve that is not a number does not end anything", "UNKNOWN", stop=30, over={X.RESERVE: "nan"})
    end_case("a latched Stop SOC that cannot be read does not end anything", "UNKNOWN", stop="unknown")
    end_case("no lease: nothing to end", "NOT RUNNING", after={X.LEASE: "off", X.HOLD: "held"})
    end_case("stale telemetry: END NOW needs no VALID proposal", "END NOW", over={X.TEL: "off"})
    # the 30 minute rules, the memory and the age have nothing to say about it
    wo = lease_world(text, memory_s=None)
    wo.sched_lease_on(stop=30, export=3000, command=3800, age_min=0.5)
    so = lease_state(wo)
    expect("a lease half a minute old, a memory a few seconds old: END NOW", so["rt"] == "END NOW" and so["wait"] is None, f"{so['rt']} {so['wait']}")
    return bad


def dst_problems(text: str | None = None) -> list[str]:
    """An end time in an hour that does not exist (the clocks go forward) or happens twice (they go back) is never read as one time: the naive text resolves to the FIRST of two equal times, an hour early."""
    bad: list[str] = []

    def expect(label: str, cond: bool, detail: str = "") -> None:
        if not cond:
            bad.append(f"{label}: {detail}")

    def world(start: str, fold: int = 0, **over) -> X.CoordWorld:
        w = X.CoordWorld(text, start=start, healthy=False, this_mode="ha", fold=fold)
        w.make_healthy({X.SOC: "51.5", X.STOP_S: "40.0", **over})
        w.start_feed()
        w.set_memory_age(7200)
        return w
    # the clocks go BACK on 2026-10-25: 02:00 BST becomes 01:00 GMT, the hour 01:00-01:59 happens twice. A scheduled lease started at 00:35 BST (the window is 240 minutes, to 03:35 GMT)
    for fold in (0, 1):                                           # a naive time is read as the first of two equal times (the model's reading) or as the second: the repeated hour is refused on either
        for label, end_text, readable in (("01:20 (the hour that happens twice)", "2026-10-25 01:20:00", False), ("01:00", "2026-10-25 01:00:00", False), ("01:59:59", "2026-10-25 01:59:59", False),
                                          ("00:59:59 (the last time before it)", "2026-10-25 00:59:59", True), ("02:00 (the first time after it)", "2026-10-25 02:00:00", True), ("02:20", "2026-10-25 02:20:00", True),
                                          ("03:35 (the window end)", "2026-10-25 03:35:00", True)):
            w = world("2026-10-25 00:40:00", fold)
            w.sched_lease_on(stop=40, export=3000, command=3800, age_min=5, window_min=240.0, ends_text=end_text)
            s = lease_state(w)
            expect(f"the fall-back night, an end time {label} (fold {fold})", (s["cmp_attrs"].get("end_lease_ts") is not None) == readable and (s["rt"] != "UNKNOWN") == readable
                   and (readable or reasons_have(s, "LEASE_FACTS_UNREADABLE")) and not w.errors, f"{s['rt']} {s['cmp']} {s['cmp_attrs'].get('end_lease_ts')} {w.errors[:2]}")
    # the lease started in the first 01:xx hour, ending at 01:10 GMT, the second one (the reviewer's case: the naive text is an hour early and used to give a spurious END)
    for fold in (0, 1):
        w = world("2026-10-25 01:30:00", fold)
        w.sched_lease_on(stop=40, export=3000, command=3800, age_min=45, window_min=240.0, ends_text="2026-10-25 01:10:00")
        s = lease_state(w)
        # (read as the second 01:30 the poll text itself is an hour late: the telemetry is stale and the proposal INVALID, which is as far from ALLOWED as it gets)
        expect(f"the fall-back night: an end text in the repeated hour, 20 minutes before now by the naive reading, is not read (fold {fold})", s["rt"] == "UNKNOWN" and s["cmp"] == "UNKNOWN"
               and (fold == 1 or reasons_have(s, "LEASE_FACTS_UNREADABLE")) and s["changes"] == [], f"{s['rt']} {s['cmp']} {s['changes']} {s['reasons']}")
    # the clocks go FORWARD on 2026-03-29: 01:00 GMT becomes 02:00 BST, the hour 01:00-01:59 does not exist
    for fold in (0, 1):
        for label, end_text, readable in (("01:30 (the hour that does not exist)", "2026-03-29 01:30:00", False), ("01:00", "2026-03-29 01:00:00", False), ("00:59:59", "2026-03-29 00:59:59", True),
                                          ("02:00", "2026-03-29 02:00:00", True), ("02:30", "2026-03-29 02:30:00", True)):
            w = world("2026-03-29 00:10:00", fold)
            w.sched_lease_on(stop=40, export=3000, command=3800, age_min=5, window_min=240.0, ends_text=end_text)
            s = lease_state(w)
            expect(f"the spring-forward night, an end time {label} (fold {fold})", (s["cmp_attrs"].get("end_lease_ts") is not None) == readable and (s["rt"] != "UNKNOWN") == readable
                   and (readable or reasons_have(s, "LEASE_FACTS_UNREADABLE")) and not w.errors, f"{s['rt']} {s['cmp']} {s['cmp_attrs'].get('end_lease_ts')} {w.errors[:2]}")
    # a window and a lease that cross the change are read on the real instants: the window end is 03:35 GMT after the clocks went back, and the lease's end equals it
    w = world("2026-10-25 00:40:00")
    w.sched_lease_on(stop=40, export=3000, command=3800, age_min=5, window_min=240.0)
    s = lease_state(w)
    expect("a lease across the fall-back change, ending at the window end: IN LINE", s["origin"] == "SCHEDULE" and s["cmp"] == "IN LINE" and s["cmp_attrs"].get("end_lease_ts") == w.attr(X.PROPOSAL, "window_end_ts"),
           f"{s['origin']} {s['cmp']} {s['cmp_attrs'].get('end_lease_ts')} {w.attr(X.PROPOSAL, 'window_end_ts')}")
    # the template against the reference for every end text across both nights, every five minutes, from now (two readings of `this`)
    for start, day in (("2026-10-25 00:10:00", "2026-10-25"), ("2026-03-29 00:10:00", "2026-03-29")):
        w = world(start)
        w.sched_lease_on(stop=40, export=3000, command=3800, age_min=5, window_min=240.0)
        for hour in range(0, 6):
            for minute in range(0, 60, 5):
                txt = f"{day} {hour:02d}:{minute:02d}:00"
                w.bulk({X.L_END: txt})
                got = lease_state(w)["cmp_attrs"].get("end_lease_ts")
                ts = X.local_end_ts(txt)
                want = ts if (ts is not None and ts > w.now_ts() and ts > w.w.changed_at[X.LEASE]) else None
                if got != want:
                    bad.append(f"the end text {txt} reads {got}, the reference says {want}")
    return bad


def tail_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    """THE TAIL OF THE WINDOW and the schedule's helpers edited while a lease runs (RC1 and RC2 of the second review of N3).

    RC1. The schedule fixes a run's end at its start plus its length, so a run pressed in the first 20 s of its window ends up to 20 s AFTER the window end, and the lease still runs in the seconds between
    the window end and its own end. A running lease gets no time past the end of the window it runs in (a re-target never moves its END beyond the window): at every second from a minute before the window end
    to the lease's own end the proposal is INVALID (no start fits), the re-target UNKNOWN with no change listed, and no render ends past the window end plus 20 s; the lease ends, and the next window's
    proposal is back. The same for a lease that ends 100 s after the window end (inside the origin's 120 s tolerance), rendered every 10 s from half an hour before it, and for a lease the schedule did not start.
    RC2. A lease the schedule started is bounded by its OWN latched end (the window captured at its start): editing the duration or the start helper during the lease (the schedule disarms after its start, so the
    card lets the owner edit them for the next night) cannot move the bound. Every edit, rendered, against what it must give."""
    bad: list[str] = []
    p1 = {X.STOP_S: "25.0", X.RESERVE: "25", X.SOC: "93.0"}      # 285 minutes of energy at 3800 W: only the window and the lease's own end can limit a proposal

    def expect(label: str, cond: bool, detail: str = "") -> None:
        if not cond:
            bad.append(f"{label}: {detail}")

    # (a) a run pressed in the first 20 s of its window, rendered at EVERY SECOND from 70 s before the window end to its own end: the proposal gives it no time, the re-target changes nothing
    for win_min in (60, 240):
        for press in (0, 10, 20):
            staged = 60 * math.floor((win_min * 60 - press + 20) / 60)              # what the schedule stages: min(length, floor((time left + 20 s) / 60 s)) minutes
            w = lease_world(text, over={**p1, X.WIN: str(float(win_min))})
            age_s = win_min * 60 - press - 70                                       # the window ends 70 s from now
            lease_end = w.now_ts() - age_s + staged                                 # the lease ends `press` s after the window end
            w.sched_lease_on(stop=25, export=3000, command=3800, age_min=age_s / 60, window_min=win_min, start_gap_s=press, run_gap_s=3.0, ends_text=w.local_text(lease_end))
            w.set_memory_age(7200)
            w.force()
            w_end = w.attr(X.PROPOSAL, "window_end_ts")
            for k in range(0, int(lease_end - w.now_ts()) + 7):
                if k:
                    w.advance(1)
                if w.now_ts() >= lease_end:
                    w.lease_off()
                else:
                    w.force()
                rel = w.now_ts() - w_end
                lbl = f"a {win_min} minute window, the run pressed {press} s into it, {rel:+.0f} s from the window end"
                bad += run_end_problems(w, lbl)
                s = lease_state(w)
                if w.state(X.LEASE) == "on":
                    expect(f"{lbl}: the lease still runs and gets no time", s["proposal"] == "INVALID" and w.attr(X.PROPOSAL, "blocked_by") == ["BELOW_MINIMUM_DURATION"] and s["rt"] == "UNKNOWN"
                           and s["changes"] == [] and s["origin"] == "SCHEDULE" and s["cmp"] == "UNKNOWN", f"{s['proposal']} {w.attr(X.PROPOSAL, 'blocked_by')} {s['rt']} {s['changes']} {s['origin']} {s['cmp']}")
                else:
                    expect(f"{lbl}: the lease is over, the next window's proposal is back", s["rt"] == "NOT RUNNING" and s["proposal"] == "VALID" and w.state(X.P_DUR) == str(min(271, win_min) // 5 * 5),
                           f"{s['rt']} {s['proposal']} {w.state(X.P_DUR)}")
            if bad and first_only:
                return bad
    # (b) a lease that ends 100 s after the window end (the origin tolerates 120 s): in the window the proposed end is the WINDOW's, not the lease's later one; after the window end it gets no time, and the text says 0
    w = lease_world(text, over={**p1, X.WIN: "60.0"})
    age_s = 60 * 60 - 5 - 1800                                                      # the window ends in half an hour
    lease_end = w.now_ts() - age_s + 3600 + 100 - 5
    w.sched_lease_on(stop=25, export=3000, command=3800, age_min=age_s / 60, window_min=60, start_gap_s=5, ends_text=w.local_text(lease_end))
    w.set_memory_age(7200)
    w.force()
    w_end = w.attr(X.PROPOSAL, "window_end_ts")
    seen = set()
    while w.now_ts() < lease_end + 10:
        if w.now_ts() >= lease_end:
            w.lease_off()
        else:
            w.force()
        rel = w.now_ts() - w_end
        lbl = f"a lease ending 100 s after the window end, {rel:+.0f} s from the window end"
        bad += run_end_problems(w, lbl)
        s = lease_state(w)
        seen.add((s["proposal"], s["rt"]))
        if w.state(X.LEASE) == "on" and rel > 20:
            reasons = " ".join(w.attr(X.PROPOSAL, "reasons") or [])
            expect(f"{lbl}: more than the schedule's 20 s past the window end the time left is 0, never a negative number", s["proposal"] == "INVALID" and "the window the running lease is authorised for leaves 0 minutes" in reasons
                   and "the proposed duration is 0 minutes" in reasons, reasons[:200])
        if w.state(X.LEASE) == "on" and rel < -660:
            expect(f"{lbl}: inside the window the end is the window's: the duration is the time left (the lease's later end counts for nothing)", s["proposal"] == "VALID"
                   and w.state(X.P_DUR) == str(math.floor((w_end - w.now_ts() + 20) / 60) // 5 * 5) and s["rt"] == "NO CHANGE", f"{s['proposal']} {w.state(X.P_DUR)} {s['rt']}")
        w.advance(10)
    expect("a lease ending 100 s after the window end: valid inside the window, INVALID to its end, then the next window's proposal", ("VALID", "NO CHANGE") in seen and ("INVALID", "UNKNOWN") in seen and ("VALID", "NOT RUNNING") in seen, str(sorted(seen)))
    if bad and first_only:
        return bad
    # (c) the helpers edited while the lease runs (RC2): a lease the schedule started, 40 minutes into its 60 minute window (it ends in 1195 s, the window with it), then each edit
    day = 86400
    edits = (("the duration raised to 240", lambda w, ws: w.bulk({X.WIN: "240.0"}), "SCHEDULE", "VALID", "20"),
             ("the duration raised to 61", lambda w, ws: w.bulk({X.WIN: "61.0"}), "SCHEDULE", "VALID", "20"),
             ("the duration lowered to 45 (the window now ends 295 s from now: the lease no longer fits it)", lambda w, ws: w.bulk({X.WIN: "45.0"}), "OTHER", "INVALID", "unavailable"),
             ("the start moved 1 minute earlier (the window ends a minute before the lease: the smaller bound)", lambda w, ws: w.schedule_window(ws - 60), "SCHEDULE", "VALID", "15"),
             ("the start moved 3 minutes earlier (the lease no longer fits the window)", lambda w, ws: w.schedule_window(ws - 180), "OTHER", "VALID", "15"),
             ("the start moved half an hour earlier (the window is over, the lease runs on)", lambda w, ws: w.schedule_window(ws - 1800), "OTHER", "INVALID", "unavailable"),
             ("the start moved 1 minute later", lambda w, ws: w.schedule_window(ws + 60), "SCHEDULE", "VALID", "20"),
             ("the start moved half an hour later (the lease began before this window)", lambda w, ws: w.schedule_window(ws + 1800), "OTHER", "VALID", "50"),
             ("the start moved to tomorrow (arming the next night)", lambda w, ws: w.schedule_window(ws + day), "OTHER", "VALID", "60"),
             ("the start moved to yesterday", lambda w, ws: w.schedule_window(ws - day), "OTHER", "INVALID", "unavailable"),
             ("the duration raised to 240 and the start moved 1 minute later", lambda w, ws: (w.schedule_window(ws + 60), w.bulk({X.WIN: "240.0"})), "SCHEDULE", "VALID", "20"),
             ("the start moved tomorrow and the duration raised to 240", lambda w, ws: (w.schedule_window(ws + day), w.bulk({X.WIN: "240.0"})), "OTHER", "VALID", "240"))
    for label, edit, want_origin, want_prop, want_dur in edits:
        w = lease_world(text, over={**p1, X.WIN: "60.0"})
        w.sched_lease_on(stop=25, export=3000, command=3800, age_min=40, window_min=60)
        ws = w.now_ts() - 40 * 60 - 5
        s0 = lease_state(w)
        expect(f"a scheduled lease 40 minutes into its window: in line before the edit ({label})", s0["rt"] == "NO CHANGE" and s0["cmp"] == "IN LINE" and s0["origin"] == "SCHEDULE" and w.state(X.P_DUR) == "20",
               f"{s0['rt']} {s0['cmp']} {s0['origin']} {w.state(X.P_DUR)}")
        edit(w, ws)
        w.set_memory_age(7200)
        w.force()
        s = lease_state(w)
        lbl = f"a scheduled lease, {label}"
        bad += run_end_problems(w, lbl)
        expect(f"{lbl}: origin {want_origin}, the proposal {want_prop}, the duration {want_dur}, no END change, never ALLOWED", s["origin"] == want_origin and s["proposal"] == want_prop and w.state(X.P_DUR) == want_dur
               and s["rt"] != "ALLOWED" and not any(c.startswith("END ") for c in s["changes"]) and (want_origin == "SCHEDULE" or s["rt"] == "UNKNOWN"),
               f"{s['origin']} {s['proposal']} {w.state(X.P_DUR)} {s['rt']} {s['changes']}")
        if bad and first_only:
            return bad
    # (d) a lease the schedule did not start, running through the window end: it gets no time either
    w = lease_world(text, over={**p1, X.WIN: "60.0"})
    w.lease_on(stop=25, export=3000, command=3800, ends_in_min=120, age_min=20)
    w.schedule_window(w.now_ts() - 55 * 60, 60.0)
    w.force()
    w_end = w.attr(X.PROPOSAL, "window_end_ts")
    for k in range(0, 24):
        w.advance(30)
        w.force()
        rel = w.now_ts() - w_end
        lbl = f"a manual lease through the window end, {rel:+.0f} s from the window end"
        bad += run_end_problems(w, lbl)
        s = lease_state(w)
        expect(f"{lbl}: not the schedule's lease: UNKNOWN, no change, and after the window end no time", s["origin"] == "OTHER" and s["rt"] == "UNKNOWN" and s["changes"] == [] and (rel < 0 or s["proposal"] == "INVALID"),
               f"{s['origin']} {s['rt']} {s['changes']} {s['proposal']}")
    if bad and first_only:
        return bad
    # (e) a whole run in real time, polled every 10 s (a 60 minute window, the run pressed 15 s into it, in line all the way): NO CHANGE until the last 10 minutes, then UNKNOWN to its end, never ALLOWED
    w = lease_world(text, over={**p1, X.WIN: "60.0"})
    w.sched_lease_on(stop=25, export=3000, command=3800, age_min=0.0, window_min=60, start_gap_s=15, ends_in_min=60)
    lease_end = w.now_ts() + 3600
    w_end = w.attr(X.PROPOSAL, "window_end_ts")
    seen = {}
    while w.now_ts() < lease_end:
        w.advance(10)
        if w.now_ts() >= lease_end:
            w.lease_off()
        else:
            rt = lease_state(w)["rt"]
            seen[rt] = seen.get(rt, 0) + 1
            bad += run_end_problems(w, f"a whole run, {w.now_ts() - w_end:+.0f} s from the window end")
    s = lease_state(w)
    expect("a whole run in real time: in line (NO CHANGE) until the last minutes, UNKNOWN to its end, never WAIT or ALLOWED; then NOT RUNNING and the next window's proposal", set(seen) == {"NO CHANGE", "UNKNOWN"}
           and s["rt"] == "NOT RUNNING" and s["proposal"] == "VALID" and not w.errors, f"{seen} {s['rt']} {s['proposal']} {w.errors[:2]}")
    return bad


def lease_sweep_problems(n: int, seed: int, text: str | None = None, first_only: bool = False, scheduled: bool = False) -> list[str]:
    """Random lease worlds against the reference, in fresh worlds: what started the lease (the start script, the window, the end), its age, the latched values, the hold and the reserve, the memory
    (its age, when it was last evaluated, the previous would-change and re-target state) and the four spellings of `this`. The facts are set, the memory is written, and ONE final render is compared:
    the re-target, the comparison and the PROPOSAL (a running lease's bound is in it), and the property of every render while a lease runs.
    `scheduled`: almost every lease is the schedule's own, at a random moment of its window or of the seconds after it (the tail), its end as the schedule stages it or a little off it, and the
    schedule's duration or start helper sometimes edited while it runs."""
    rng = random.Random(seed)
    bad: list[str] = []
    for i in range(n):
        mode = rng.choice(["ha", "ha", "ha", "first-none", "none", "undefined"])
        now = T0
        edit = "none"
        press = 0
        rel = 0.0
        if scheduled:
            soc = float(rng.choice([93, 93, 93, rng.randint(41, 100)]))
            hold = "clear"
            reserve = rng.choice(["25", "25", "25", "25", "25", "40", "24"])
            stop_s = rng.choice(["25.0", "25.0", "26.0", "35.0"])
            win0 = rng.choice([15.0, 30.0, 60.0, 120.0, 240.0])
            flag = "on"
            press = rng.choice([0, 3, 5, 10, 19, 20, 21, 45, 100])             # the second of the window the start button was pressed (the window began that long before the lease flag turned on)
            run_gap = rng.choice([3, 3, 3, 0, 8, -5, 10])
            lo = press - win0 * 60                                              # the lease has started
            r = rng.random()
            rel = rng.uniform(lo, -700.0) if r < 0.5 else (rng.uniform(-700.0, -30.0) if r < 0.7 else rng.uniform(-30.0, 130.0))   # seconds from the window end: inside it, its last minutes, its tail
            rel = float(round(rel))
            age_s = int(rel + win0 * 60 - press)
            start_gap = press
            lease_start = now - age_s
            w_start0 = lease_start - press
            w_end0 = w_start0 + win0 * 60
            staged = 60 * min(win0, math.floor((win0 * 60 - press + 20) / 60))   # what the schedule stages: min(length, floor((time left + 20 s) / 60 s)) minutes
            end_kind = rng.choice(["window"] * 7 + ["w-600", "w-60", "w+30", "w+100", "w+120", "w+121"])
            end_text = text_at({"window": lease_start + staged, "w-600": w_end0 - 600, "w-60": w_end0 - 60, "w+30": w_end0 + 30, "w+100": w_end0 + 100, "w+120": w_end0 + 120, "w+121": w_end0 + 121}[end_kind])
            win, w_start = win0, w_start0
            edit = rng.choice(["none"] * 6 + ["dur240", "dur+1", "dur-30", "start-60", "start+60", "start-180", "start+180", "start-1800", "start+1800", "start+day", "start-day"])
            if edit == "dur240":
                win = 240.0
            elif edit == "dur+1":
                win = min(240.0, win0 + 1)
            elif edit == "dur-30":
                win = max(1.0, win0 - 30)
            elif edit.startswith("start"):
                w_start = w_start0 + {"start-60": -60, "start+60": 60, "start-180": -180, "start+180": 180, "start-1800": -1800, "start+1800": 1800, "start+day": 86400, "start-day": -86400}[edit]
            stop = rng.choice([25.0, 25.0, 25.0, 25.0, 25.0, 24.0, 26.0, 30.0, 40.0, "unknown"])
            export = rng.choice([3000.0, 3000.0, 3000.0, 2800.0, 3200.0, 2900.0])
            cmd = 3800.0
            mem_s = rng.choice([7200, 7200, 7200, 1799, 1800, 0])
            rt_entry = rng.choice(["keep", "keep", "keep", now - 100, now - 1801])
            rt_state = rng.choice(["keep", "keep", "ALLOWED", "WAIT"])
        else:
            soc = float(rng.randint(41, 100))
            hold = rng.choice(["clear"] * 7 + ["held", "unknown"])
            reserve = rng.choice(["40", "40", "40", "30", "62", "45.5", "unknown", "nan"])
            stop_s = rng.choice(["25.0", "25.0", "50.0", "35.0"])
            win = rng.choice([240.0, 240.0, 120.0, 60.0, 30.0, 15.0])
            flag = rng.choice(["on", "on", "on", "on", "off", "unavailable", "unknown", None])
            age_s = rng.choice([-600, 0, 300, 1739, 1740, 1799, 1800, 1801, 3600, 5400, 7200, 12000])
            run_gap = rng.choice([None, 3, 3, 3, 3, -12, -10, 0, 10, 899, 900, 901, 7200])
            start_gap = rng.choice([5, 5, 5, 0, -59, -60, -61, 20000, -4000])
            if rng.random() < 0.8:                                   # most leases run inside their window (a running lease gets no time past the window end, so a window that is over says nothing else)
                win = min(240.0, max(win, float(math.ceil((max(age_s + start_gap, 0) / 60) + 15))))
            lease_start = now - age_s
            w_start = lease_start - start_gap
            w_end = w_start + win * 60
            end_kind = rng.choice(["window", "window", "window", "w+120", "w+121", "w-600", "soon", "late", "past", "garbage", "inactive", "missing"])
            end_text = {"window": text_at(w_end), "w+120": text_at(w_end + 120), "w+121": text_at(w_end + 121), "w-600": text_at(w_end - 600), "soon": text_at(now + 60), "late": text_at(now + 3000),
                        "past": text_at(now - 60), "garbage": "soon-ish", "inactive": "Inactive", "missing": None}[end_kind]
            stop = rng.choice([30.0, 39.0, 40.0, 41.0, 40.5, "unknown", 55.0, "-5", 49.0, 50.0, 51.0])
            export = rng.choice([3000.0, 2800.0, 2900.0, 3200.0, 3100.0, "unavailable", 1000.0])
            cmd = rng.choice([3500.0, 3800.0, 0.0, "unknown"])
            mem_s = rng.choice([-6, -5, 0, 1, 1799, 1800, 1801, 7200])
            rt_entry = rng.choice(["keep", None, now - 100, now - 1799, now - 1800, now - 1801, now + 600])
            rt_state = rng.choice(["keep", None, "ALLOWED", "WAIT", "NO CHANGE"])
        w = lease_world(text, this_mode=mode, over={X.SOC: str(soc), X.HOLD: hold, X.RESERVE: reserve, X.STOP_S: stop_s, X.WIN: str(win)}, memory_s=None)
        assert w.now_ts() == now
        w.bulk({X.LEASE: flag, X.L_STOP: str(stop), X.L_EXP: str(export), X.L_CMD: str(cmd), X.L_END: end_text})
        if run_gap is None:
            w.put(X.SCRIPT, None)
        else:
            w.script_ran(lease_start - run_gap)
        w.schedule_window(w_start)
        # the leases consumer: on for long enough (most), off, or on for less than 60 s (20, 59, and exactly 60 s)
        tl_mode = rng.choice(["on"] * 6 + ["off", "young", "young59", "young60"])
        tl_age = {"on": 600.0, "off": 0.0, "young": 20.0, "young59": 59.0, "young60": 60.0}[tl_mode]
        if tl_mode == "off":
            w.bulk({X.TL: "off"})
        elif tl_mode != "on":
            w.bulk({X.TL: "off"})
            w.bulk({X.TL: "on"})
        w.set_gate_ages(600.0, tl_age)
        prev = dict(w.model())
        w.set_memory_age(mem_s, rt_entry=rt_entry, rt_state=rt_state)
        w.age(X.LEASE, float(age_s))
        got = lease_state(w)
        m = w.model()
        raw = {**X.HEALTHY, X.SOC: str(soc), X.HOLD: hold, X.RESERVE: reserve, X.STOP_S: stop_s, X.WIN: str(win), X.SCH_START: text_at(w_start), X.LEASE: flag, X.L_STOP: str(stop),
               X.TL: "off" if tl_mode == "off" else "on"}
        l_start = w.w.changed_at.get(X.LEASE) if X.LEASE in w.w.states else None
        run_ts = None if run_gap is None else lease_start - run_gap
        # the proposal of a running lease is bounded by its window, and for a lease the schedule started by its own end: the reference needs the lease's facts to say which
        ref_p = X.reference(raw, poll_skew_s=0.0, now_ts=now, lease={"end_text": end_text, "start_ts": l_start, "run_ts": run_ts}, gate_ages=(600.0, tl_age))
        mem_ok = mode in ("ha", "first-none")
        # when `this` cannot be read there is no previous model at all: no previous would-change and no previous state
        prev_entry = (prev.get("rt_entry") if rt_entry == "keep" else rt_entry) if mem_ok else None
        prev_state = (prev.get("rt_state") if rt_state == "keep" else rt_state) if mem_ok else None
        ref = X.reference_lease(ref_p, lease=("unknown" if flag is None else flag), l_stop_raw=str(stop), l_exp_raw=str(export), l_cmd_raw=str(cmd), l_end_text=("unknown" if end_text is None else end_text),
                                l_start_ts=l_start, run_ts=run_ts, now_ts=now, prev_state=prev_state, prev_entry=prev_entry, mem_age=X.memory_age(mem_s, mem_ok), mem_ok=mem_ok, time_ok=tl_mode in ("on", "young60"))
        label = (f"lease case {i} (mode {mode} flag {flag} age {age_s} script {run_gap} window {win} start_gap {start_gap} end {end_kind} stop {stop} export {export} mem {mem_s} tl {tl_mode} entry {rt_entry} state {rt_state} "
                 f"hold {hold} reserve {reserve}" + (f", scheduled: {rel:+.0f} s from the window end, edit {edit}" if scheduled else "") + ")")
        if got["rt"] != ref["rt_state"] or got["cmp"] != ref["cmp_state"] or m.get("rt_entry") != ref["rt_entry"]:
            bad.append(f"{label}: rt {got['rt']} cmp {got['cmp']} entry {m.get('rt_entry')} != {ref['rt_state']} {ref['cmp_state']} {ref['rt_entry']}")
        codes = [r.split(":")[0] for r in (got["reasons"] or [])]
        if codes != ref["codes"]:
            bad.append(f"{label}: reasons {codes} != {ref['codes']}")
        changes = [c.split(" ")[0] for c in (got["changes"] or [])]
        if changes != ref["changes"]:
            bad.append(f"{label}: changes {changes} != {ref['changes']}")
        if (got["wait"] is None) != (ref["wait_until"] is None) or (ref["wait_until"] is not None and abs(got["wait"] - ref["wait_until"]) > 1e-6):
            bad.append(f"{label}: wait_until {got['wait']} != {ref['wait_until']}")
        if got["origin"] != ref["lease_origin"] or m.get("mem_since_ts") != ref["mem_since"]:
            bad.append(f"{label}: origin {got['origin']} mem_since {m.get('mem_since_ts')} != {ref['lease_origin']} {ref['mem_since']}")
        want_age = None if (flag != "on" or ref["age"] is None) else math.floor(ref["age"] / 60)
        if got["rt_attrs"].get("lease_age_min") != want_age:
            bad.append(f"{label}: lease_age_min {got['rt_attrs'].get('lease_age_min')} != {want_age}")
        for key, want in (("stop_soc_difference", ref["d_stop"]), ("export_w_difference", ref["d_exp"]), ("battery_w_difference", ref["d_bat"]), ("battery_w_loop_difference", ref["d_loop"])):
            have = m.get(key)
            if (have is None) != (want is None) or (want is not None and abs(have - want) > 0.06):
                bad.append(f"{label}: {key} {have} != {want}")
        have, want = m.get("end_difference_min"), ref["d_end"]
        if (have is None) != (want is None) or (want is not None and abs(have - round(want)) > 1e-9):
            bad.append(f"{label}: end_difference_min {have} != {want}")
        if (m.get("end_lease_ts") is None) != (ref["l_end_ts"] is None) or (ref["l_end_ts"] is not None and abs(m.get("end_lease_ts") - ref["l_end_ts"]) > 1e-6):
            bad.append(f"{label}: end_lease_ts {m.get('end_lease_ts')} != {ref['l_end_ts']}")
        # the proposal itself against the reference (state, causes, numbers, the loop's figures, the window end: the bound of a running lease is in all of them), and the property of every render while a lease runs
        bad += [f"{label}: proposal {b}" for b in compare(w, ref_p)]
        bad += run_end_problems(w, label)
        if w.errors:
            bad.append(f"{label}: template errors {w.errors[:2]}")
        SERVICE_LOG.extend(w.w.service_log)
        if bad and first_only:
            return bad
    return bad


def time_trust_problems(text: str | None = None) -> list[str]:
    """The leases consumer of the time trust package and the re-target (slice S-A2): a change is ALLOWED only while binary_sensor.ecco_time_trusted_for_leases reads on and has read on for 60 s;
    otherwise WAIT, with the cause TIME_NOT_TRUSTED and no time to wait for (it is not a time), the changes still listed. Nothing else about the re-target moves with it."""
    bad: list[str] = []

    def build(tl, age: float, *, stop: float = 49, age_min: float = 45.0, memory_s: float = 7200.0) -> X.CoordWorld:
        """The consumer is given its state and age BEFORE the lease starts, so the one render that matters is the first that can allow a change (no earlier render has stamped a would-change)."""
        w = lease_world(text, over=STOP50, memory_s=memory_s)
        w.bulk({X.TL: tl})
        w.set_gate_ages(600.0, age)
        w.sched_lease_on(stop=stop, export=3000, command=3800, age_min=age_min)
        return w
    for label, tl, age, want in (("on for 10 minutes", "on", 600.0, "ALLOWED"), ("on for exactly 60 s", "on", 60.0, "ALLOWED"), ("on for 59.9 s", "on", 59.9, "WAIT"), ("on for 20 s", "on", 20.0, "WAIT"),
                                 ("on for 0 s", "on", 0.0, "WAIT"), ("off", "off", 600.0, "WAIT"), ("unavailable", "unavailable", 600.0, "WAIT"), ("unknown", "unknown", 600.0, "WAIT"),
                                 ("an empty state", "", 600.0, "WAIT"), ("missing", None, 600.0, "WAIT")):
        w = build(tl, age)
        st = lease_state(w)
        codes = [r.split(":")[0] for r in (st["reasons"] or [])]
        if want == "ALLOWED":
            ok = st["rt"] == "ALLOWED" and not st["reasons"] and st["last"] == w.now_ts() and st["changes"]
        else:
            named = [r for r in (st["reasons"] or []) if r.startswith("TIME_NOT_TRUSTED: binary_sensor.ecco_time_trusted_for_leases reads ")]
            ok = st["rt"] == "WAIT" and codes == ["TIME_NOT_TRUSTED"] and len(named) == 1 and st["wait"] is None and st["last"] is None and st["changes"] and st["cmp"] == "DIFFERS"
            if ok and tl == "off" and "reads off (it must read on)" not in named[0]:
                ok = False
            if ok and tl == "on" and ", but it turned on less than 60 s ago" not in named[0]:
                ok = False
        if not ok or w.errors:
            bad.append(f"the leases consumer is {label}: {st['rt']} {codes} wait {st['wait']} last {st['last']} {st['changes']} {w.errors[:1]}")
    # the other waits are named beside it, and the wait is theirs
    w = build("off", 600.0, age_min=29.0)
    st = lease_state(w)
    codes = [r.split(":")[0] for r in (st["reasons"] or [])]
    if st["rt"] != "WAIT" or sorted(codes) != ["LEASE_TOO_YOUNG", "TIME_NOT_TRUSTED"] or st["wait"] is None or abs(st["wait"] - (w.w.changed_at[X.LEASE] + 1800)) > 1:
        bad.append(f"the leases consumer is off and the lease is 29 minutes old: {st['rt']} {codes} {st['wait']}")
    w = build("off", 600.0, memory_s=60.0)
    st = lease_state(w)
    codes = [r.split(":")[0] for r in (st["reasons"] or [])]
    if st["rt"] != "WAIT" or sorted(codes) != ["MEMORY_YOUNG", "TIME_NOT_TRUSTED"]:
        bad.append(f"the leases consumer is off and the memory is a minute old: {st['rt']} {codes}")
    # nothing else moves with it: no deviation is no change, an END NOW stays END NOW, a lease the schedule did not start and a proposal that is not VALID stay UNKNOWN, the comparison is the same
    w = build("off", 600.0, stop=50)
    st = lease_state(w)
    if st["rt"] != "NO CHANGE" or st["reasons"] or st["cmp"] != "IN LINE":
        bad.append(f"the leases consumer is off and the lease is in line: {st['rt']} {st['reasons']} {st['cmp']}")
    w = build("off", 600.0)
    w.bulk({X.HOLD: "held"})
    st = lease_state(w)
    if st["rt"] != "END NOW" or [r.split(":")[0] for r in (st["reasons"] or [])] != ["HOLD_ACTIVE"]:
        bad.append(f"the leases consumer is off and a hold is active: {st['rt']} {st['reasons']}")
    w = build("off", 600.0)
    w.bulk({X.SOC: "unknown"})
    st = lease_state(w)
    if st["rt"] != "UNKNOWN" or not reasons_have(st, "PROPOSAL_NOT_VALID") or reasons_have(st, "TIME_NOT_TRUSTED"):
        bad.append(f"the leases consumer is off and the proposal is INVALID: {st['rt']} {st['reasons']}")
    w = lease_world(text, over=STOP50)
    w.lease_on(stop=49, export=3000, command=3800, age_min=45)
    w.bulk({X.TL: "off"})
    st = lease_state(w)
    if st["rt"] != "UNKNOWN" or not reasons_have(st, "LEASE_ORIGIN_UNKNOWN") or reasons_have(st, "TIME_NOT_TRUSTED"):
        bad.append(f"the leases consumer is off and the lease is not the schedule's: {st['rt']} {st['reasons']}")
    # the Export start gate has no say in the re-target: a closed gate (the lease itself closes it) leaves the re-target as it is
    w = build("on", 600.0)
    w.bulk({X.EG: ("off", {"blocked_by": ["DUMP_ACTIVE"]})})
    w.set_gate_ages(5.0, 600.0)
    st = lease_state(w)
    if st["rt"] != "ALLOWED" or st["reasons"]:
        bad.append(f"the Export start gate is closed (a lease runs): the re-target is not its business: {st['rt']} {st['reasons']}")
    return bad


def reload_realtime_problems(text: str | None = None) -> list[str]:
    """In real time (the clock advances; the dongle polls every minute): a template reload five minutes after a would-change does not allow another for 30 minutes, then it does; a restart (a new
    world) is the same."""
    bad: list[str] = []
    for mode in ("ha", "first-none"):
        w = lease_world(text, this_mode=mode, over=STOP50, memory_s=None, feed=60.0)
        w.set_memory_age(7200)
        w.sched_lease_on(stop=49, export=3000, command=3800, age_min=40)
        w.advance(60)
        s = lease_state(w)
        if s["rt"] != "ALLOWED":
            bad.append(f"{mode}: before the reload the change is allowed: {s['rt']} {s['reasons']}")
        w.advance(300)
        w.reload()
        t_r = w.now_ts()
        s = lease_state(w)
        if s["rt"] != "WAIT" or not reasons_have(s, "MEMORY_YOUNG" if mode == "ha" else "MEMORY_UNAVAILABLE"):
            bad.append(f"{mode}: right after the reload: {s['rt']} {s['reasons']}")
        w.w.run_until(t_r + 1799)
        w.force()
        s = lease_state(w)
        if s["rt"] != "WAIT" or not reasons_have(s, "MEMORY_YOUNG") or w.model().get("mem_since_ts") != t_r:
            bad.append(f"{mode}: 1799 s after the reload: {s['rt']} {s['reasons']} {w.model().get('mem_since_ts')} {t_r}")
        w.w.run_until(t_r + 1800)
        s = lease_state(w)
        if s["rt"] != "ALLOWED" or s["last"] != t_r + 1800:
            bad.append(f"{mode}: 1800 s after the reload: {s['rt']} {s['reasons']} {s['last']}")
        if w.errors:
            bad.append(f"{mode}: template errors {w.errors[:2]}")
    # a Home Assistant restart: a new world (the lease flag's last_changed is new, and so is the memory); the lease cannot be matched to the schedule any more once the restart is more than 15 minutes
    # after the scheduled start script ran
    w = lease_world(text, over=STOP50, memory_s=None, feed=60.0)
    w.sched_lease_on(stop=49, export=3000, command=3800, age_min=40)
    w.script_ran(w.now_ts() - 3600)                                 # the script ran an hour ago: this world's lease flag (a restart's last_changed, 40 minutes) is 20 minutes after it
    w.force()
    s = lease_state(w)
    if s["rt"] != "UNKNOWN" or not reasons_have(s, "LEASE_ORIGIN_UNKNOWN"):
        bad.append(f"after a restart, 20 minutes after the start script: {s['rt']} {s['reasons']}")
    return bad


def churn_problems(text: str | None = None) -> list[str]:
    """What is published again when no input changes: NOTHING, the model included (decision D-C04a, route a: the lab measured 393 rows an hour from the model's per-render time of its evaluation, which
    is gone). A poll that moves only the poll text, a gate that is published again with moving reasons: the same. A lease the schedule started: only the two counters in whole minutes (the lease's age
    and the comparison's END difference) may move, once in a minute, and nothing else."""
    bad: list[str] = []

    def rows(w) -> dict:
        n: dict = {}
        for _t, eid, _s in w.w.history:
            if eid in X.OWN:
                n[eid] = n.get(eid, 0) + 1
        return n

    def keys(a: dict, b: dict) -> set:
        return {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
    w = lease_world(text)
    w.advance(30)
    snap, r0, model0 = w.snapshot(), rows(w), dict(w.model())
    w.advance(600)                                              # ten minutes: sixty polls (the poll text moves) and ten renders at the start of a minute, nothing else changes
    if rows(w) != r0 or w.snapshot() != snap or w.model() != model0:
        bad.append(f"no lease, ten minutes of polls: published again {[e for e in X.OWN if rows(w).get(e) != r0.get(e)]} {sorted(keys(model0, w.model()))}")
    for i in range(30):                                         # the gate is published again with a reason that moves (a number in its text) and the same list of codes
        w.bulk({X.EG: ("on", {"blocked_by": [], "reasons": [f"ALLOWED: every check passed ({i})"]})})
    if rows(w) != r0 or w.snapshot() != snap or w.model() != model0:
        bad.append("the gate's reasons move with every poll and the coordinator publishes a new row")
    if "evaluated_ts" in w.model() or any(k.endswith("_ts") and isinstance(v, (int, float)) and abs(v - w.now_ts()) < 5 for k, v in w.model().items()):
        bad.append(f"the model carries a time of its own evaluation: {[k for k in w.model() if k.endswith('_ts')]}")
    # a lease the schedule started, in line: the counters in whole minutes may move once a minute, nothing else
    w = lease_world(text, over=STOP50)
    w.sched_lease_on(stop=50, export=3000, command=3800, age_min=45)
    w.advance(5)
    snap, model0 = w.snapshot(), dict(w.model())
    w.advance(40)
    new = w.snapshot()
    allowed = {"lease_age_min", "end_difference_min"}
    if not keys(model0, w.model()) <= allowed:
        bad.append(f"a lease: the model published again with {sorted(keys(model0, w.model()) - allowed)}")
    for e in X.OWN:
        if e != X.MODEL and (snap[e][0] != new[e][0] or not keys(snap[e][1], new[e][1]) <= allowed):
            bad.append(f"a lease: {e} published again with {sorted(keys(snap[e][1], new[e][1]) - allowed)}")
    # CS-06: a PV surplus the target cannot hold is INVALID with a reason that names the surplus rounded UP to a step: a PV that wanders inside the step publishes nothing again
    w = lease_world(text, over={X.PV: "4000.0"})
    w.advance(30)
    snap, r0, model0 = w.snapshot(), rows(w), dict(w.model())
    if snap[X.PROPOSAL][0] != "INVALID" or "TARGET_INFEASIBLE_LOW" not in w.attr(X.PROPOSAL, "blocked_by"):
        bad.append(f"a PV surplus the target cannot hold is not INVALID: {snap[X.PROPOSAL][0]} {w.attr(X.PROPOSAL, 'blocked_by')}")
    for pv in (4010.0, 4050.0, 4100.0, 4200.0, 4000.0):
        w.bulk({X.PV: str(pv)})                                     # the surplus is 3200 to 3400 W: one step (3500 W)
    if rows(w) != r0 or w.snapshot() != snap or w.model() != model0:
        bad.append(f"a PV that wanders inside a 500 W step of the surplus publishes again: {[e for e in X.OWN if rows(w).get(e) != r0.get(e)]} {sorted(keys(model0, w.model()))}")
    w.bulk({X.PV: "4400.0"})                                       # 3600 W: the next step
    if rows(w) == r0 or "3500" in " ".join(w.attr(X.PROPOSAL, "reasons") or []):
        bad.append("a PV that leaves its step does not publish a new reason")
    # CS-06: the row rate under a moving house load (10 s polls, one simulated hour, a load that wanders up to 150 W a poll): the model, the proposal and the lookups write a row when a 500 W or 5 minute step is
    # crossed: the measured worst case is 61 rows an hour (353 before the steps), a calm house 7 (40 before); the bound here is generous so that the check is about the order of magnitude
    for profile, bound in (("moving", 120), ("calm", 25)):
        wr = new_world(text)
        wr.start_feed(10.0)
        wr.advance(30)
        rng = random.Random(20261127)
        load = 800.0
        wr.bulk({X.LOAD: f"{load:.1f}"})
        r_before = rows(wr)
        for _i in range(360):
            wr.advance(10)
            if profile == "moving" or rng.random() < 0.10:
                load = min(max(load + rng.uniform(-150, 150), 200.0), 2800.0)
            wr.bulk({X.LOAD: f"{load:.1f}", X.GRID: f"{load:.1f}"})
        r_after = rows(wr)
        worst = max((r_after.get(e, 0) - r_before.get(e, 0)) for e in X.OWN)
        if worst > bound:
            bad.append(f"{profile} house load: {worst} rows an hour for one entity (bound {bound}): {[(e.split('.')[1], r_after.get(e, 0) - r_before.get(e, 0)) for e in X.OWN]}")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


# ===========================================================================================================================
# [5] the lookups: the model not updating
# ===========================================================================================================================
def lookup_text(text: str | None = None) -> str:
    """The package without the model entity: the lookups then read a model the suite writes (a plain state with a dict attribute)."""
    d = yaml.safe_load(text if text is not None else TEXT)
    d["template"][0]["sensor"] = [e for e in d["template"][0]["sensor"] if e["name"] != "ECCO Export Coordinator Model"]
    return yaml.safe_dump(d, sort_keys=False, width=10 ** 6)


# every attribute of every lookup and the key of the model it reads
LOOKUP_ATTRS = {X.PROPOSAL: {"reasons": "reasons", "blocked_by": "blocked_by", "notes": "notes", "raw_battery_power_w": "raw_battery_power_w", "loop_battery_power_w": "loop_power_w",
                             "loop_duration_min": "loop_duration_min", "limited_by": "limited_by", "window_end_ts": "window_end_ts"},
                X.RETARGET: {"reasons": "rt_reasons", "changes": "rt_changes", "wait_until_ts": "rt_wait_until_ts", "last_would_change_ts": "rt_entry", "lease_age_min": "lease_age_min",
                             "lease_origin": "lease_origin"},
                X.COMPARE: {"stop_soc_proposed": "stop_soc_proposed", "stop_soc_lease": "stop_soc_lease", "stop_soc_difference": "stop_soc_difference", "export_w_proposed": "export_w_proposed",
                            "export_w_lease": "export_w_lease", "export_w_difference": "export_w_difference", "battery_w_proposed": "battery_w_proposed", "battery_w_loop": "battery_w_loop",
                            "battery_w_commanded": "battery_w_commanded", "battery_w_difference": "battery_w_difference", "battery_w_loop_difference": "battery_w_loop_difference",
                            "end_lease_ts": "end_lease_ts", "end_difference_min": "end_difference_min"}}


def lookups_problems(text: str | None = None) -> list[str]:
    bad: list[str] = []
    w = X.CoordWorld(lookup_text(text), healthy=False)
    good = {"state": "VALID", "verdict": "VALID", "actionable": True, "reasons": ["VALID: a proposal from measured values"], "blocked_by": [], "notes": [], "floor_pct": 40, "energy_kwh": 10.53,
            "battery_power_w": 3800, "net_export_w": 3000, "duration_min": 166, "raw_battery_power_w": 3801, "loop_power_w": 3802, "loop_duration_min": 165, "limited_by": "", "window_end_ts": 1795730400,
            "lease_origin": "SCHEDULE", "cmp_state": "IN LINE", "rt_state": "NO CHANGE", "rt_reasons": [], "rt_changes": [], "rt_entry": None, "rt_wait_until_ts": None, "lease_age_min": None,
            "stop_soc_proposed": 40, "stop_soc_lease": 40.0, "stop_soc_difference": 0.0, "export_w_proposed": 3000, "export_w_lease": 3000.0, "export_w_difference": 0.0,
            "battery_w_proposed": 3800, "battery_w_loop": 3803, "battery_w_commanded": 3800.0, "battery_w_difference": 0.0, "battery_w_loop_difference": 3.0,
            "end_lease_ts": 1, "end_difference_min": 0, "mem_since_ts": 5}

    def put_model(**kw):
        m = dict(good)
        m.update(kw)
        w.put(X.MODEL, "model", {"model": m})
        w.force()

    def numbers_available() -> list[str]:
        return [eid for eid in X.NUMERIC if w.state(eid) != "unavailable"]
    put_model()
    if w.state(X.PROPOSAL) != "VALID" or len(numbers_available()) != 5 or w.state(X.RETARGET) != "NO CHANGE" or w.state(X.COMPARE) != "IN LINE" or w.attr(X.PROPOSAL, "actionable") is not True:
        bad.append(f"a model is read through: {w.snapshot()}")
    # every attribute reads its own key of the model: each key carries a value of its own
    distinct = {k: (f"text-{k}" if isinstance(v, str) or v is None else (v + 1000 + i if isinstance(v, (int, float)) and not isinstance(v, bool) else v))
                for i, (k, v) in enumerate(good.items()) if k not in ("state", "verdict", "actionable")}
    for key in ("reasons", "blocked_by", "notes", "rt_reasons", "rt_changes"):
        distinct[key] = [f"item-{key}"]
    put_model(**distinct)
    for eid, amap in LOOKUP_ATTRS.items():
        for attr, key in amap.items():
            if w.attr(eid, attr) != distinct[key]:
                bad.append(f"{eid} {attr} reads {w.attr(eid, attr)!r}, the model's {key} is {distinct[key]!r}")
    for eid, key in ((X.P_FLOOR, "floor_pct"), (X.P_ENERGY, "energy_kwh"), (X.P_POWER, "battery_power_w"), (X.P_NET, "net_export_w"), (X.P_DUR, "duration_min")):
        if w.state(eid) != str(distinct[key]):
            bad.append(f"{eid} reads {w.state(eid)}, the model's {key} is {distinct[key]}")
    # the actionable flag: only the boolean true is true
    for v, want in ((True, True), (False, False), ("True", False), ("true", False), (1, False), (None, False)):
        put_model(actionable=v)
        if w.attr(X.PROPOSAL, "actionable") is not want:
            bad.append(f"actionable {v!r} in the model reads {w.attr(X.PROPOSAL, 'actionable')!r}, wanted {want}")
    # a model carries no time (decision D-C04a, route a): it is read as it is, whatever its age (no age is published and none is judged)
    put_model(evaluated_ts=1)
    if w.state(X.PROPOSAL) != "VALID" or len(numbers_available()) != 5:
        bad.append("a model with an old time of evaluation is not read through")
    # a model that cannot be read at all withholds everything and says so
    for label, put in (("missing", lambda: w.put(X.MODEL, None)), ("a text", lambda: w.put(X.MODEL, "model", {"model": "nonsense"})), ("a number", lambda: w.put(X.MODEL, "model", {"model": 5})),
                       ("a list", lambda: w.put(X.MODEL, "model", {"model": ["VALID"]})), ("no attribute", lambda: w.put(X.MODEL, "model", {}))):
        put()
        w.force()
        withheld = [(eid, a) for eid, amap in LOOKUP_ATTRS.items() for a in amap if a not in ("reasons", "blocked_by", "notes", "changes") and w.attr(eid, a) not in (None, "")]
        if w.state(X.PROPOSAL) != "INVALID" or numbers_available() or w.state(X.RETARGET) != "UNKNOWN" or w.state(X.COMPARE) != "UNKNOWN" or w.attr(X.PROPOSAL, "blocked_by") != ["MODEL_UNREADABLE"] \
                or w.attr(X.PROPOSAL, "actionable") is not False or withheld or w.attr(X.RETARGET, "changes") != []:
            bad.append(f"a model that is {label} is withheld: {w.snapshot()} {withheld}")
    # the states the lookups know and the numbers' availability (it follows the verdict of the proposal itself, not the published state)
    put_model(state="VALID!")
    if w.state(X.PROPOSAL) != "INVALID":
        bad.append("an unknown state is passed on")
    put_model(state="INVALID", verdict="INVALID", actionable=False)
    if numbers_available():
        bad.append("numbers are published for an INVALID model")
    put_model(state="HOLD", verdict="HOLD", actionable=False)
    if numbers_available():
        bad.append("numbers are published for a HOLD model")
    put_model(state="NOT ALLOWED", verdict="VALID", actionable=False, blocked_by=["TIME_LEASES"])
    if w.state(X.PROPOSAL) != "NOT ALLOWED" or len(numbers_available()) != 5 or w.attr(X.PROPOSAL, "blocked_by") != ["TIME_LEASES"] or w.attr(X.PROPOSAL, "actionable") is not False:
        bad.append(f"NOT ALLOWED is not passed on with its numbers and the gate's codes: {w.snapshot()[X.PROPOSAL]}")
    put_model(state="VALID", verdict="INVALID")
    if numbers_available():
        bad.append("the numbers follow the published state, not the verdict of the proposal itself")
    put_model(state="NOT ALLOWED", verdict="HOLD")
    if numbers_available():
        bad.append("numbers are published for a NOT ALLOWED model whose proposal is a HOLD")
    put_model(state="UNVERIFIED", verdict="UNVERIFIED", actionable=False)
    if len(numbers_available()) != 5 or w.state(X.PROPOSAL) != "UNVERIFIED":
        bad.append("numbers are not published for an UNVERIFIED model")
    put_model(floor_pct=None, energy_kwh="x", battery_power_w=None)
    if w.state(X.P_FLOOR) != "unavailable" or w.state(X.P_ENERGY) != "unavailable" or w.state(X.P_POWER) != "unavailable":
        bad.append("a number that is not a number is published")
    put_model(rt_state="ALLOWED!", cmp_state="MAYBE")
    if w.state(X.RETARGET) != "UNKNOWN" or w.state(X.COMPARE) != "UNKNOWN":
        bad.append("an unknown re-target or comparison state is passed on")
    put_model(rt_state="END NOW")
    if w.state(X.RETARGET) != "END NOW":
        bad.append("END NOW is not passed on")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


# ===========================================================================================================================
# [6] the real plan helper package feeding the coordinator
# ===========================================================================================================================
def plan_problems(text: str | None = None) -> list[str]:
    import _plan_sim as PL
    import _start_gate_sim as G
    bad: list[str] = []

    class Adopt(X.ThisMixin, G._Adopt):
        """The coordinator's template model on the plan world's state machine: the hold and the reserve are produced by the REAL plan helper package."""

    pw = PL.PlanWorld(X.START, [yaml.safe_load(PLAN_TEXT)], X.ZONE)
    w = pw.w
    tw = Adopt(w, X.ZONE, text if text is not None else TEXT)
    # the owner's accepted limits, confirmed, and the owner's reserve
    for ent, v in (("min_expiry", 15), ("hold_default", 240), ("hold_cap", 1440), ("skip_cap", 1440), ("cut_default", 1440), ("cut_cap", 4320), ("cut_reserve", 80)):
        w.set(f"input_number.ecco_plan_policy_{ent}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    w.set("input_number.ecco_plan_revision", "7.0")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    for eid, st in X.HEALTHY.items():
        if eid not in (X.HOLD, X.RESERVE):
            s0, a0 = X.split(st)
            tw.put(eid, s0, a0 or None)
    feed = tw.feed(X.POLL, period=10.0)
    w.run_until(w.t + 30)
    tw.age(X.EG, 600.0)                                        # the start gate and the consumer have read on for long enough (the hold-off is 60 s)
    tw.age(X.TL, 600.0)
    tw.force()
    if w.state(X.HOLD) != "clear" or w.state(X.RESERVE) != "40" or tw.state(X.PROPOSAL) != "VALID" or tw.state(X.P_FLOOR) != "40":
        bad.append(f"the real plan sensors feed the coordinator: hold {w.state(X.HOLD)} reserve {w.state(X.RESERVE)} proposal {tw.state(X.PROPOSAL)} floor {tw.state(X.P_FLOOR)} {tw.errors[:2]}")
    w.set("input_number.ecco_minimum_reserve_soc", "62.4")
    tw.force()
    if w.state(X.RESERVE) != "63" or tw.state(X.P_FLOOR) != "63":
        bad.append(f"the effective reserve is rounded up by the plan package and the floor follows: {w.state(X.RESERVE)} {tw.state(X.P_FLOOR)}")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    for kind, want_reserve in (("hold_battery", "40"), ("skip_tonight", "40"), ("prepare_power_cut", "80")):
        pw.run_script("ecco_plan_override_start", {"kind": kind, "expiry_min": 60}, seconds=30)
        tw.force()
        if w.state(X.HOLD) != "held" or tw.state(X.PROPOSAL) != "HOLD" or any(tw.state(e) != "unavailable" for e in X.NUMERIC) or "OVERRIDE_ACTIVE" not in (tw.attr(X.PROPOSAL, "blocked_by") or []):
            bad.append(f"{kind}: the real hold sensor reads {w.state(X.HOLD)}, the coordinator {tw.state(X.PROPOSAL)} numbers {[tw.state(e) for e in X.NUMERIC]} "
                       f"({w.state('input_text.ecco_plan_last_result')[:80]})")
        if w.state(X.RESERVE) != want_reserve:
            bad.append(f"{kind}: the effective reserve reads {w.state(X.RESERVE)}, wanted {want_reserve}")
        pw.run_script("ecco_plan_override_cancel", {"kind": kind}, seconds=30)
        w.run_until(w.t + 120)
        tw.force()
        if w.state(X.HOLD) != "clear" or tw.state(X.PROPOSAL) != "VALID":
            bad.append(f"{kind} cancelled: hold {w.state(X.HOLD)} proposal {tw.state(X.PROPOSAL)} ({w.state('input_text.ecco_plan_last_result')[:80]})")
    # a lease the schedule started is running (10 minutes old, Stop SOC 40 latched at the reserve of then): the REAL hold and the REAL reserve end it (END NOW), whatever the 30 minute rules say
    now = w.t + w.clock_offset
    tw.put(X.WIN, "240.0")
    tw.put(X.SCH_START, tw.local_text(now - 605))
    tw.put(X.SCRIPT, "off", {"last_triggered": datetime.fromtimestamp(now - 603, ZONE).isoformat()})
    tw.put(X.L_STOP, "40.0")
    tw.put(X.L_EXP, "3000.0")
    tw.put(X.L_CMD, "3800.0")
    tw.put(X.L_END, tw.local_text(now - 605 + 240 * 60))
    tw.put(X.LEASE, "on")
    tw.age(X.LEASE, 600.0)
    tw.force()
    if tw.state(X.RETARGET) != "NO CHANGE" or tw.state(X.COMPARE) != "IN LINE":
        bad.append(f"a scheduled lease in line: {tw.state(X.RETARGET)} {tw.state(X.COMPARE)} {tw.attr(X.RETARGET, 'reasons')} {tw.errors[:2]}")
    for kind in ("hold_battery", "skip_tonight", "prepare_power_cut"):
        pw.run_script("ecco_plan_override_start", {"kind": kind, "expiry_min": 60}, seconds=30)
        tw.force()
        codes = [r.split(":")[0] for r in (tw.attr(X.RETARGET, "reasons") or [])]
        want = ["HOLD_ACTIVE", "RESERVE_ABOVE_LEASE_STOP_SOC"] if kind == "prepare_power_cut" else ["HOLD_ACTIVE"]
        if tw.state(X.RETARGET) != "END NOW" or codes != want or tw.state(X.PROPOSAL) != "HOLD":
            bad.append(f"{kind} during a lease: {tw.state(X.RETARGET)} {codes} (want {want}) proposal {tw.state(X.PROPOSAL)}")
        pw.run_script("ecco_plan_override_cancel", {"kind": kind}, seconds=30)
        w.run_until(w.t + 120)
        tw.force()
        if tw.state(X.RETARGET) != "NO CHANGE":
            bad.append(f"{kind} cancelled during a lease: {tw.state(X.RETARGET)} {tw.attr(X.RETARGET, 'reasons')}")
    w.set("input_number.ecco_minimum_reserve_soc", "62.4")
    tw.force()
    codes = [r.split(":")[0] for r in (tw.attr(X.RETARGET, "reasons") or [])]
    if tw.state(X.RETARGET) != "END NOW" or codes != ["RESERVE_ABOVE_LEASE_STOP_SOC"] or w.state(X.HOLD) != "clear":
        bad.append(f"the real effective reserve rises (63) above the latched Stop SOC (40) with no hold: {tw.state(X.RETARGET)} {codes}")
    w.set("input_number.ecco_minimum_reserve_soc", "40.0")
    tw.force()
    if tw.state(X.RETARGET) != "NO CHANGE":
        bad.append(f"the reserve is back: {tw.state(X.RETARGET)}")
    feed["on"] = False
    if tw.errors:
        bad.append(f"template errors {tw.errors[:2]}")
    if PL.PlanWorld.rejected_all:
        bad.append(f"a helper refused a write: {PL.PlanWorld.rejected_all[:2]}")
    SERVICE_LOG.extend(c for c in w.service_log if c[1] not in ("input_number.set_value", "input_datetime.set_datetime", "input_text.set_value", "persistent_notification.create",
                                                                 "persistent_notification.dismiss"))
    return bad


def gate_problems(text: str | None = None) -> list[str]:
    """The REAL start gate and the REAL plan helper package in one world with the coordinator, which now READS the gate (slice S-A2; the pins were widened deliberately): a proposal the gate does not allow
    is NOT ALLOWED and names the gate's own codes, `actionable` is true only while the gate has read on for 60 s, a Hold battery stays a HOLD, and the proposal's own causes (stale telemetry: 90 s,
    against the gate's 300 s) are judged first."""
    import _start_gate_sim as G
    bad: list[str] = []
    gate_text = (PKGS / "ecco_start_gate.yaml").read_text(encoding="utf-8")

    class Adopt(X.ThisMixin, G._Adopt):
        pass

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
    tw = Adopt(w, X.ZONE, text if text is not None else TEXT)
    for eid, st in X.HEALTHY.items():
        if eid not in (X.HOLD, X.RESERVE, X.LEASE, X.TEL, X.EG, X.TL):
            s0, a0 = X.split(st)
            tw.put(eid, s0, a0 or None)

    def both() -> tuple:
        gw.sync()
        tw.force()
        return gw.state(G.EXPORT_GATE), tw.state(X.PROPOSAL), tw.attr(X.PROPOSAL, "actionable"), list(tw.attr(X.PROPOSAL, "blocked_by") or [])
    gw.advance(10)
    first = both()
    if first[1] != "NOT ALLOWED" or first[2] is not False or first[3] != ["GATE_SETTLING"]:
        bad.append(f"the gate has been on for seconds: the proposal is NOT ALLOWED (GATE_SETTLING), never actionable: {first}")
    gw.advance(80)
    if both() != ("on", "VALID", True, []):
        bad.append(f"healthy, the gate on for more than 60 s: gate, proposal, actionable, blocked_by {both()} {gw.attr(G.EXPORT_GATE, 'blocked_by')}")
    pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
    held = both()
    if held[0] != "off" or held[1] != "HOLD" or held[2] is not False or "OVERRIDE_ACTIVE" not in held[3] or any(tw.state(e) != "unavailable" for e in X.NUMERIC):
        bad.append(f"a Hold battery: the gate is off and the proposal is a HOLD with no number, not actionable: {held}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
    back = both()
    if back[1] != "NOT ALLOWED" or back[3] != ["GATE_SETTLING"]:
        bad.append(f"a cancelled Hold battery: the gate is back on for less than 60 s, so NOT ALLOWED (GATE_SETTLING): {back}")
    gw.advance(70)
    if both() != ("on", "VALID", True, []):
        bad.append(f"a cancelled Hold battery, 70 s later: {both()}")
    gw.put(G.TL, "off")
    off = both()
    if off[0] != "off" or off[1] != "NOT ALLOWED" or off[2] is not False or off[3] != ["TIME_LEASES"] or any(tw.state(e) == "unavailable" for e in X.NUMERIC):
        bad.append(f"the time trust the gate reads is off: the proposal itself is still VALID and says NOT ALLOWED with the gate's code, its numbers stay: {off}")
    if not (tw.attr(X.PROPOSAL, "reasons") or [""])[0].startswith("NOT ALLOWED: ") or "TIME_LEASES" not in (tw.attr(X.PROPOSAL, "reasons") or [""])[0]:
        bad.append(f"NOT ALLOWED names the gate's codes in its reasons: {tw.attr(X.PROPOSAL, 'reasons')}")
    gw.put(G.TL, "on")
    on_again = both()
    if on_again[1] != "NOT ALLOWED" or on_again[3] != ["GATE_SETTLING"]:
        bad.append(f"the time trust is back: the gate is young again (GATE_SETTLING): {on_again}")
    gw.advance(70)
    if both() != ("on", "VALID", True, []):
        bad.append(f"the time trust back for 70 s: {both()}")
    w.set("input_number.ecco_plan_revision", "unavailable")
    rev = both()
    if rev[0] != "off" or rev[1] != "NOT ALLOWED" or rev[3] != ["REVISION_UNREADABLE"]:
        bad.append(f"an unreadable plan revision closes the gate: the proposal is NOT ALLOWED with its code: {rev}")
    w.set("input_number.ecco_plan_revision", "7.0")
    gw.advance(70)
    gw.d.dump_start(latched=40.0)
    gw.sync()
    tw.put(X.L_EXP, "3000.0")
    tw.put(X.L_CMD, "3500.0")
    tw.put(X.L_END, tw.local_text(w.t + w.clock_offset + 3600))
    tw.force()
    # a lease the dongle's own button (or a guarded start) began: the schedule did not start it, so the coordinator compares and re-targets nothing (UNKNOWN, LEASE_ORIGIN_UNKNOWN); the gate is closed
    # (DUMP_ACTIVE) and the proposal reads NOT ALLOWED for as long as a lease runs
    lease = both()
    if lease[0] != "off" or lease[1] != "NOT ALLOWED" or "DUMP_ACTIVE" not in lease[3] or tw.state(X.RETARGET) != "UNKNOWN" or tw.state(X.COMPARE) != "UNKNOWN" \
            or not any(r.startswith("LEASE_ORIGIN_UNKNOWN") for r in (tw.attr(X.RETARGET, "reasons") or [])):
        bad.append(f"a lease the schedule did not start is running: the gate is closed (DUMP_ACTIVE), the proposal NOT ALLOWED, the re-target and the comparison UNKNOWN: {lease} {tw.state(X.RETARGET)} "
                   f"{tw.state(X.COMPARE)} {tw.attr(X.RETARGET, 'reasons')}")
    gw.d.dump_end()
    gw.sync()
    gw.stop_poll()
    gw.advance(150)
    gw.sync()
    tw.force()
    stale = both()
    if stale[0] != "on" or stale[1] != "INVALID" or stale[2] is not False or stale[3] != ["TELEMETRY_STALE"]:
        bad.append(f"150 s after the last poll the gate (300 s bound) still allows and the proposal (90 s bound) is INVALID: it is judged before the gate: {stale}")
    if tw.errors or gw.tw.errors:
        bad.append(f"template errors {tw.errors[:2]} {gw.tw.errors[:2]}")
    return bad


def size_problems(text: str | None = None) -> list[str]:
    """The model's attribute is the biggest thing the package publishes: the worst case (every input missing, every cause named) stays well below the recorder's 16 kB attribute limit."""
    w = new_world(text)
    w.bulk({eid: "unavailable" for eid in X.HEALTHY}, poll_age=None)
    import json
    size = len(json.dumps(w.model()))
    return [] if 0 < size < 6000 and not w.errors else [f"the worst-case model attribute is {size} bytes (limit 6000) {w.errors[:2]}"]


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
                out.add(f"{domain}.{DONGLE}_{slug(e['name'])}")
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


OTHER_TEXT = {p.name: p.read_text(encoding="utf-8") for p in sorted(PKGS.glob("*.yaml")) if p.name != "ecco_export_coordinator.yaml"}
REPO_IDS = firmware_ids()
for _t in OTHER_TEXT.values():
    REPO_IDS |= package_ids(_t)
REPO_UNIQUE = {u for _t in OTHER_TEXT.values() for u in re.findall(r"unique_id: \"?([a-z0-9_]+)", _t)}


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
    ents = [it for block in d["template"] for kind in block for it in block[kind]]
    if [list(b) for b in d["template"]] != [["sensor"]]:
        bad.append("the template block holds anything but one sensor list")
    ids = {f"sensor.{slug(e['name'])}" for e in ents}
    if ids != OWN_IDS or len(ents) != 9:
        bad.append(f"the entities are {sorted(ids ^ OWN_IDS)} off the nine expected")
    uids = [e.get("unique_id") for e in ents]
    if uids != [slug(e["name"]) for e in ents] or len(set(uids)) != 9:
        bad.append("each unique_id is the slug of its name, once")
    if ids & REPO_IDS or set(uids) & REPO_UNIQUE:
        bad.append(f"an id is defined elsewhere in the repository: {sorted(ids & REPO_IDS)} {sorted(set(uids) & REPO_UNIQUE)}")
    # the write vocabulary: nothing that can call a service, start anything or define a helper
    for tok in ("action", "actions", "service", "trigger", "triggers", "condition", "conditions", "sequence", "automation", "script", "input_number", "input_boolean", "input_text", "input_datetime",
                "button", "choose", "variables"):
        if re.search(rf"^\s*-?\s*{tok}\s*:", text, re.M):
            bad.append(f"the key `{tok}:` appears: the package must contain no service call, script, automation, helper or trigger")
    for tok in (".turn_on", ".turn_off", ".press", ".set_value", ".toggle", "persistent_notification", "homeassistant.", "esphome.", "rest_command", "shell_command", "notify.", "mqtt.",
                "button.press", "input_text.", "script.turn_on", "automation.trigger"):
        if tok in text:
            bad.append(f"the write vocabulary token {tok!r} appears")
    # what it reads
    tpl = "\n".join(template_strings(d))
    reads = set(ENTITY_RE.findall(tpl))
    if reads != EXPECTED_READS:
        bad.append(f"it reads {sorted(reads ^ EXPECTED_READS)} off the expected set")
    missing = sorted(reads - OWN_IDS - REPO_IDS)
    if missing:
        bad.append(f"it reads entities that exist nowhere in the repository: {missing}")
    pairs = set(STATE_ATTR_RE.findall(tpl))
    if pairs != EXPECTED_STATE_ATTRS or tpl.count("state_attr(") != len(STATE_ATTR_RE.findall(tpl)):
        bad.append(f"the (entity, attribute) pairs it reads are {sorted(pairs ^ EXPECTED_STATE_ATTRS)} off the expected set (or an attribute is read with a name that is not a literal)")
    objs = set(STATES_OBJ_RE.findall(tpl))
    if objs != EXPECTED_STATE_OBJECTS or tpl.count("states[") != len(STATES_OBJ_RE.findall(tpl)) or re.search(r"\bstates\.[a-z_]+\.[a-z_]+", tpl) or "is_state_attr" in tpl:
        bad.append(f"the state objects it reads are {sorted(objs ^ EXPECTED_STATE_OBJECTS)} off the expected set (or another form of state object is used)")
    this_uses = THIS_RE.findall(tpl)
    if set(this_uses) - {""} != EXPECTED_THIS_ATTRS or len(re.findall(r"\bthis\b", tpl)) != len(this_uses):
        bad.append(f"`this` is used for {sorted(set(this_uses))} and elsewhere: only its `model` attribute and its being defined are expected")
    for eid in sorted(set(ENTITY_RE.findall(text))):
        if FORBIDDEN_FORECAST.search(eid):
            bad.append(f"a forecast or estimate entity id appears: {eid}")
    # who may be mentioned (the pins of the start gate suite and of the time trust suite were widened for this package, design decision D-PIN): the Export start gate and the leases consumer, whole
    # and with their domain, and nothing else of either package (not the charge gate, not the bypass, not another consumer, a per-clock sensor, the overall sensor or an internal helper)
    for name in PINNED_NAMES:
        if name in text:
            bad.append(f"it mentions {name!r}: the package that pins who may mention it would fail")
    rest = text.replace("ecco_time_trust.yaml", "")
    for whole in ALLOWED_WHOLE:
        rest = rest.replace(whole, "")
    for stem in ("ecco_time_trust", "ecco_export_start_allowed"):
        if stem in rest:
            bad.append(f"it mentions {stem!r} in a form other than the two entities it may read, whole and with their domain: {ALLOWED_WHOLE}")
    for whole in ALLOWED_WHOLE:
        if whole not in tpl:
            bad.append(f"the templates no longer read {whole}")
    # hygiene
    if not text.isascii() or "\r" in text or "\t" in text:
        bad.append("not ASCII / LF / tab-free")
    for pat in (r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+(?:\.\d+)?\b", r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", r"[Cc]:\\Users", r"/Users/", r"\bsk-[A-Za-z0-9]{10,}", r"\bpassword\b|\bsecret\b|\btoken\b"):
        if re.search(pat, text):
            bad.append(f"a site value or secret pattern appears: {pat}")
    if re.search(r"(?<![a-z_.])(?:sensor|binary_sensor|number|button|switch)\.(?!ecco_clock_dongle_|ecco_|input_)", tpl):
        bad.append("an entity id outside the ecco namespace is read")
    if re.search(r"\binitial\s*:", text):
        bad.append("an `initial:` appears")
    hdr = "\n".join(line.lstrip("#") for line in text.splitlines() if line.startswith("#"))
    hflat = flat(hdr)
    for pin in HEADER_PINS:
        if flat(pin) not in hflat:
            bad.append(f"the header lost: {pin!r}")
    for const, literal in CONSTANT_PINS:
        if const not in hdr:
            bad.append(f"the header lost the constant {const!r}")
        if PIN_LITERALS and literal not in tpl:
            bad.append(f"the templates lost the literal {literal!r} of {const!r}")
    # the eight lookups repeat one identical check (a readable model: the model carries no time of its evaluation any more, so the lookups judge no age: decision D-C04a, route a)
    check_prefix = "{%- set m = state_attr('sensor.ecco_export_coordinator_model', 'model') -%} {%- set ok = m is mapping -%}"
    for e in ents:
        if e["name"] == "ECCO Export Coordinator Model":
            continue
        strings = [(k, e[k]) for k in ("state", "availability") if isinstance(e.get(k), str)] + [(f"attributes.{k}", v) for k, v in (e.get("attributes") or {}).items() if isinstance(v, str)]
        for k, s in strings:
            s = flat(s)
            if k == "attributes.rule":
                continue
            if e["name"] in ("ECCO Export Proposal Floor", "ECCO Export Proposal Energy", "ECCO Export Proposal Power", "ECCO Export Proposal Net Export", "ECCO Export Proposal Duration") and k == "state":
                if not s.startswith("{%- set m = state_attr('sensor.ecco_export_coordinator_model', 'model') -%} {{ m.get(") or "if m is mapping else 'unknown' }}" not in s:
                    bad.append(f"{e['name']} {k} is not the guarded lookup")
                continue
            if not s.startswith(check_prefix):
                bad.append(f"{e['name']} {k} does not start with the shared two-line check")
    units = {e["name"]: (e.get("unit_of_measurement"), e.get("device_class")) for e in ents}
    if units.get("ECCO Export Proposal Floor") != ("%", None) or units.get("ECCO Export Proposal Energy") != ("kWh", "energy_storage") or units.get("ECCO Export Proposal Power") != ("W", "power") \
            or units.get("ECCO Export Proposal Net Export") != ("W", "power") or units.get("ECCO Export Proposal Duration") != ("min", "duration"):
        bad.append(f"the units and device classes changed: {units}")
    if any("state_class" in e for e in ents):
        bad.append("a state_class would put the proposal into the long-term statistics")
    return bad


# ===========================================================================================================================
# the battery run on a package text: static, boundary rows, anchors, a short sweep, the lease
# ===========================================================================================================================
def battery(text: str, deep: bool = False) -> list[str]:
    bad = static_problems(text)
    if bad:
        return bad
    try:
        bad += anchors(text)
        if bad:
            return bad
        bad += boundary_problems(text, first_only=True)
        if bad:
            return bad
        bad += gate_rows_problems(text, first_only=True)
        if bad:
            return bad
        bad += sweep_problems(120 if not deep else 400, 20261126, text, first_only=True)[0]
        if bad:
            return bad
        bad += lease_problems(text, first_only=True)
        if bad:
            return bad
        bad += time_trust_problems(text)
        if bad:
            return bad
        bad += gate_realtime_problems(text)
        if bad:
            return bad
        bad += dst_problems(text)
        if bad:
            return bad
        bad += tail_problems(text, first_only=True)
        if bad:
            return bad
        bad += lease_sweep_problems(60 if not deep else 200, 7, text, first_only=True)
        if bad:
            return bad
        bad += lease_sweep_problems(60 if not deep else 200, 29, text, first_only=True, scheduled=True)
        if bad:
            return bad
        bad += churn_problems(text)
        if bad:
            return bad
        bad += lookups_problems(text)
    except Exception as exc:  # noqa: BLE001 - a package that breaks the model is a dead mutant, not a crash
        bad.append(f"the model raised {type(exc).__name__}: {str(exc)[:120]}")
    return bad


# ===========================================================================================================================
# the mutants: (label, old, new)
# ===========================================================================================================================
MUTANTS = [
    ("SOC accepted above 100", "rng(states('sensor.ecco_clock_dongle_ecco_battery_soc'), 0, 100)", "rng(states('sensor.ecco_clock_dongle_ecco_battery_soc'), 0, 101)"),
    ("SOC accepted below 0", "rng(states('sensor.ecco_clock_dongle_ecco_battery_soc'), 0, 100)", "rng(states('sensor.ecco_clock_dongle_ecco_battery_soc'), -1, 100)"),
    ("house load accepted when negative", "rng(states('sensor.ecco_house_power'), 0, 30000)", "rng(states('sensor.ecco_house_power'), -1, 30000)"),
    ("house load accepted above the physical range", "rng(states('sensor.ecco_house_power'), 0, 30000)", "rng(states('sensor.ecco_house_power'), 0, 40000)"),
    ("PV accepted when negative", "rng(states('sensor.ecco_clock_dongle_ecco_pv_power'), 0, 30000)", "rng(states('sensor.ecco_clock_dongle_ecco_pv_power'), -1, 30000)"),
    ("grid accepted above its range", "rng(states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'), -30000, 30000)", "rng(states('sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp'), -30000, 40000)"),
    ("capacity accepted at 0", "rng(states('input_number.ecco_battery_model_capacity'), 1, 1000)", "rng(states('input_number.ecco_battery_model_capacity'), 0, 1000)"),
    ("an unreadable reading becomes 0", "{%- set x = raw | float(none) -%}", "{%- set x = raw | float(0) -%}"),
    ("the freshness bound is 91 s", "(pskew | abs) <= 90", "(pskew | abs) <= 91"),
    ("a poll text from the future is fresh", "(pskew | abs) <= 90", "pskew <= 90"),
    ("telemetry offline is not a cause", "('TELEMETRY_OFFLINE', tel != 'on',", "('TELEMETRY_OFFLINE', tel == 'off',"),
    ("a reserve above 100 is accepted", "{%- set reserve = r if (r >= 0 and r <= 100) else (-1 if r < 0 else -2) -%}", "{%- set reserve = r if r >= 0 else -1 -%}"),
    ("the unreadable and invalid reserve swap", "else (-1 if r < 0 else -2) -%}", "else (-2 if r < 0 else -1) -%}"),
    ("the floor ignores the effective reserve", "[stop_s, reserve, 10, (l_stop if", "[stop_s, 10, (l_stop if"),
    ("the staged Stop SOC of the dongle enters the floor", "[stop_s, reserve, 10, (l_stop if", "[stop_s, (states('number.ecco_clock_dongle_dump_to_grid_stop_soc') | float(0)), reserve, 10, (l_stop if"),
    ("the floor ignores the schedule's Stop SOC", "[stop_s, reserve, 10, (l_stop if", "[reserve, 10, (l_stop if"),
    ("the floor ignores the dongle minimum", "[stop_s, reserve, 10, (l_stop if", "[stop_s, reserve, (l_stop if"),
    ("the floor is the minimum, not the maximum", "else 0)] | max | round(0, 'ceil'))", "else 0)] | min | round(0, 'ceil'))"),
    ("the Stop SOC a running lease latched is not a member of the floor", "[stop_s, reserve, 10, (l_stop if (lease_on and l_stop is not none) else 0)]", "[stop_s, reserve, 10]"),
    ("the Stop SOC of a lease that is not running is a member of the floor", "(l_stop if (lease_on and l_stop is not none) else 0)", "(l_stop if l_stop is not none else 0)"),
    ("an unreadable latched Stop SOC of a running lease is no cause", "('LEASE_STOP_SOC_UNREADABLE', lease_on and l_stop is none,", "('LEASE_STOP_SOC_UNREADABLE', false,"),
    ("an unreadable latched Stop SOC blocks while no lease runs", "('LEASE_STOP_SOC_UNREADABLE', lease_on and l_stop is none,", "('LEASE_STOP_SOC_UNREADABLE', l_stop is none,"),
    ("the floor from a running lease is not named", "('FLOOR_FROM_RUNNING_LEASE', num and lease_on and l_stop > ([stop_s, reserve, 10] | max),", "('FLOOR_FROM_RUNNING_LEASE', false,"),
    ("the floor from a running lease is named at equality", "('FLOOR_FROM_RUNNING_LEASE', num and lease_on and l_stop > ([stop_s, reserve, 10] | max),", "('FLOOR_FROM_RUNNING_LEASE', num and lease_on and l_stop >= ([stop_s, reserve, 10] | max),"),
    ("the floor is rounded down", "| max | round(0, 'ceil')) if (stop_s", "| max | round(0, 'floor')) if (stop_s"),
    ("a floor of 91 is allowed", "floor is not none and floor > 90", "floor is not none and floor > 91"),
    ("the SOC margin is dropped", "([soc - floor - 1, 0] | max)", "([soc - floor, 0] | max)"),
    ("the efficiency is 0.95", "* cap * 0.90", "* cap * 0.95"),
    ("the efficiency is the old 0.92", "* cap * 0.90", "* cap * 0.92"),
    ("the efficiency is dropped", "* cap * 0.90", "* cap"),
    ("the energy uses the larger capacity", "([cap_c, cap_m] | min)", "([cap_c, cap_m] | max)"),
    ("the export headroom is 1 %", "[100, 0.03 * mx]", "[100, 0.01 * mx]"),
    ("the export headroom ignores the 100 W minimum", "[100, 0.03 * mx]", "[0, 0.03 * mx]"),
    ("the target limit rounds up", "(((nstart / 100) | round(0, 'floor')) * 100)", "(((nstart / 100) | round(0, 'ceil')) * 100)"),
    ("the target ignores the export limit", "([tgt, nmax] | min)", "tgt"),
    ("the target is the larger of the two", "([tgt, nmax] | min)", "([tgt, nmax] | max)"),
    ("a target below 500 W is allowed", "net is not none and net < 500", "net is not none and net < 400"),
    ("the load is subtracted", "(net + load - pv)", "(net - load - pv)"),
    ("the PV is added", "(net + load - pv)", "(net + load + pv)"),
    ("the PV is ignored", "(net + load - pv)", "(net + load)"),
    ("the power has no upper clamp", "[[raw_p, 0] | max, hi] | min", "[raw_p, 0] | max"),
    ("the power ignores the proven level", "([pceil, prov] | min)", "pceil"),
    ("the power ignores the ceiling", "([pceil, prov] | min)", "prov"),
    ("the divisor floor is dropped", "([p_q, 500] | max)", "p_q"),
    ("the divisor floor is 100 W", "([p_q, 500] | max)", "([p_q, 100] | max)"),
    ("the duration is rounded to the nearest", "([dur_raw, dlim] | min) | round(0, 'floor')", "([dur_raw, dlim] | min) | round(0)"),
    ("the duration ignores the schedule window and the time left in it", "([dur_raw, dlim] | min)", "dur_raw"),
    ("the minimum duration is 5", "dur is not none and energy > 0 and dur < 10", "dur is not none and energy > 0 and dur < 5"),
    ("above the proven level is VALID", "'UNVERIFIED' if (raw_p > prov and pceil > prov) else 'VALID'", "'VALID'"),
    ("UNVERIFIED without the ceiling condition", "(raw_p > prov and pceil > prov)", "(raw_p > prov)"),
    ("UNVERIFIED at the proven level", "(raw_p > prov and pceil > prov)", "(raw_p >= prov and pceil > prov)"),
    ("a hold does not give HOLD", "'HOLD' if 'OVERRIDE_ACTIVE' in ns.c else", "'INVALID' if 'OVERRIDE_ACTIVE' in ns.c else"),
    ("an unreadable hold is not a cause", "hold not in ['held', 'clear']", "hold not in ['held', 'clear', 'unknown']"),
    ("numbers are published for an INVALID state", "{%- set num = verdict in ['VALID', 'UNVERIFIED'] -%}", "{%- set num = verdict in ['VALID', 'UNVERIFIED', 'INVALID'] -%}"),
    ("numbers are published for a HOLD state", "{%- set num = verdict in ['VALID', 'UNVERIFIED'] -%}", "{%- set num = verdict != 'INVALID' -%}"),
    ("the dongle's limits are not checked", "('LIMITS_NOT_VALID', lim != 'VALID',", "('LIMITS_NOT_VALID', false,"),
    ("an unconfigured export limit is accepted", "mx is not none and mx <= 0", "mx is not none and mx < 0"),
    ("the schedule window is not read", "rng(states('input_number.ecco_dump_to_grid_schedule_duration'), 1, 240)", "rng(states('input_number.ecco_dump_to_grid_schedule_duration'), 0, 240)"),
    ("a forecast entity is read", "rng(states('sensor.ecco_house_power'), 0, 30000) | float(none) -%}", "rng(states('sensor.ecco_house_power'), 0, 30000) | float(none) -%}\n            {%- set fc = states('sensor.solcast_pv_forecast_today') -%}"),
    ("a service call is added", "state: \"model\"", "state: \"model\"\n        action: button.press"),
    ("a trigger is added", "      - name: ECCO Export Coordinator Model\n", "      - name: ECCO Export Coordinator Model\n        trigger: homeassistant\n"),
    ("the charge gate is mentioned", "# INSTALL (needs the owner's go", "# see binary_sensor.ecco_charge_start_allowed\n# INSTALL (needs the owner's go"),
    ("the start bypass is mentioned", "# INSTALL (needs the owner's go", "# see ecco_start_bypass\n# INSTALL (needs the owner's go"),
    ("the export gate is named without its domain", "# INSTALL (needs the owner's go", "# see ecco_export_start_allowed\n# INSTALL (needs the owner's go"),
    ("a per-clock sensor of the time trust package is mentioned", "# INSTALL (needs the owner's go", "# see sensor.ecco_time_trust_ha_clock\n# INSTALL (needs the owner's go"),
    ("another consumer of the time trust package is mentioned", "# INSTALL (needs the owner's go", "# see binary_sensor.ecco_time_trusted_for_ha_schedules\n# INSTALL (needs the owner's go"),
    ("the overall time trust sensor is mentioned", "# INSTALL (needs the owner's go", "# see sensor.ecco_time_trust\n# INSTALL (needs the owner's go"),
    ("the leases consumer is named without its domain", "# INSTALL (needs the owner's go", "# see ecco_time_trusted_for_leases\n# INSTALL (needs the owner's go"),
    ("the gate is read from the charge gate", "{%- set egs = states('binary_sensor.ecco_export_start_allowed') -%}", "{%- set egs = states('binary_sensor.ecco_charge_start_allowed') -%}"),
    ("a site address appears", "# INSTALL (needs the owner's go", "# " + ".".join(("192", "168", "1", "20")) + "\n# INSTALL (needs the owner's go"),
    ("the lease is left alone for 10 minutes only", "age < 1800 or recent", "age < 600 or recent"),
    ("the gap between would-changes is 10 minutes", "(now_ts - prev_entry) < 1800", "(now_ts - prev_entry) < 600"),
    ("a continuing episode counts as recent", "prev_entry is not none and not cont and", "prev_entry is not none and"),
    ("the Stop SOC deadband is 2 points", "d_stop is not none and d_stop >= 1", "d_stop is not none and d_stop >= 2"),
    ("the Stop SOC deadband is exclusive", "d_stop is not none and d_stop >= 1", "d_stop is not none and d_stop > 1"),
    ("the export deadband is exclusive", "(d_exp | abs) >= 200", "(d_exp | abs) > 200"),
    ("the end deadband is 40 minutes", "d_end >= 20", "d_end >= 40"),
    ("a lease outlasting the energy is a deviation", "d_end is not none and d_end >= 20", "d_end is not none and (d_end | abs) >= 20"),
    ("the re-target needs no VALID proposal", "(verdict != 'VALID' or not complete or age is none or not origin)", "(verdict == 'HOLD' or not complete or age is none or not origin)"),
    ("a lease with unreadable facts is compared", "{%- set complete = num and l_stop is not none and l_exp is not none and l_end_ts is not none -%}", "{%- set complete = num -%}"),
    ("a lookup accepts a model that is not a dict", "{%- set ok = m is mapping -%}\n          {{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD', 'NOT ALLOWED']) else 'INVALID' }}",
     "{%- set ok = m is not none -%}\n          {{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD', 'NOT ALLOWED']) else 'INVALID' }}"),
    ("a numeric lookup ignores the verdict", "{{ ok and m.get('verdict') in ['VALID', 'UNVERIFIED'] and m.get('duration_min') is number }}", "{{ ok and m.get('duration_min') is number }}"),
    ("a numeric lookup follows the published state, not the verdict of the proposal", "{{ ok and m.get('verdict') in ['VALID', 'UNVERIFIED'] and m.get('floor_pct') is number }}",
     "{{ ok and m.get('state') in ['VALID', 'UNVERIFIED'] and m.get('floor_pct') is number }}"),
    ("the proposal state is passed on whatever it is", "{{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD', 'NOT ALLOWED']) else 'INVALID' }}", "{{ m.get('state') if ok else 'INVALID' }}"),
    ("NOT ALLOWED is not passed on by the proposal lookup", "{{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD', 'NOT ALLOWED']) else 'INVALID' }}",
     "{{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD']) else 'INVALID' }}"),
    ("the actionable lookup passes anything true-like", "{{ ok and m.get('actionable') is sameas true }}", "{{ ok and m.get('actionable') }}"),
    ("the actionable lookup is not guarded by a readable model", "{{ ok and m.get('actionable') is sameas true }}", "{{ m.get('actionable') is sameas true }}"),
    ("an unreadable model is not named in blocked_by", "else ['MODEL_UNREADABLE'] }}", "else [] }}"),
    # ---- the reviewer's survivors (R01, R27, R28) -------------------------------------------------------------------------------------------------------------------
    ("R02: a lease that appears to start in the future is not waited for", "(age < 1800 or recent or mem_age < 1800 or not time_ok)", "((age < 1800 and age >= 0) or recent or mem_age < 1800 or not time_ok)"),
    ("R06: the re-target is judged while the lease flag is unreadable", "('UNKNOWN' if not lease_on else ('END NOW'", "('UNKNOWN' if false else ('END NOW'"),
    ("R08: the export deviation compares the target with the commanded battery ceiling", "{%- set d_exp = (net - l_exp) if (cmp_ok and l_exp is not none) else none -%}",
     "{%- set d_exp = (net - l_cmd) if (cmp_ok and l_cmd is not none) else none -%}"),
    ("R15: the reserve is rounded half-even before the maximum", "[stop_s, reserve, 10, (l_stop if", "[stop_s, reserve | round(0), 10, (l_stop if"),
    ("R25: the re-target lookup passes on any state", "{{ m.get('rt_state') if (ok and m.get('rt_state') in ['NOT RUNNING', 'UNKNOWN', 'NO CHANGE', 'WAIT', 'ALLOWED', 'END NOW']) else 'UNKNOWN' }}",
     "{{ m.get('rt_state') if ok else 'UNKNOWN' }}"),
    ("R01: a previous would-change in the future is not recent (the clock moved back)", "(now_ts - prev_entry) < 1800 -%}", "(now_ts - prev_entry) < 1800 and (now_ts - prev_entry) >= 0 -%}"),
    ("R27: the house load is the smaller of the measured one and an estimate read from an attribute of an allowed entity",
     "{%- set load = rng(states('sensor.ecco_house_power'), 0, 30000) | float(none) -%}",
     "{%- set load = ([rng(states('sensor.ecco_house_power'), 0, 30000) | float(none), state_attr('sensor.ecco_battery_time_to_reserve', 'discharge_w') | float(99999)] | min) "
     "if (rng(states('sensor.ecco_house_power'), 0, 30000) | float(none)) is not none else none -%}"),
    ("R28: the PV is the larger of the measured one and an older sample read from an attribute of an allowed entity",
     "{%- set pv = rng(states('sensor.ecco_clock_dongle_ecco_pv_power'), 0, 30000) | float(none) -%}",
     "{%- set pv = ([rng(states('sensor.ecco_clock_dongle_ecco_pv_power'), 0, 30000) | float(none), state_attr('sensor.ecco_battery_time_to_reserve', 'pv_w') | float(0)] | max) "
     "if (rng(states('sensor.ecco_clock_dongle_ecco_pv_power'), 0, 30000) | float(none)) is not none else none -%}"),
    # ---- F1: the schedule's own window --------------------------------------------------------------------------------------------------------------------------
    ("the time left in the window ignores the schedule's 20 s", "(((w_end - now_ts + 20) / 60) | round(0, 'floor'))", "(((w_end - now_ts) / 60) | round(0, 'floor'))"),
    ("the time left in the window is 30 s more generous", "(((w_end - now_ts + 20) / 60) | round(0, 'floor'))", "(((w_end - now_ts + 50) / 60) | round(0, 'floor'))"),
    ("the time left in the window rounds to the nearest", "(((w_end - now_ts + 20) / 60) | round(0, 'floor')) if in_win", "(((w_end - now_ts + 20) / 60) | round(0)) if in_win"),
    ("the time left in the window is not applied", "(([win, wcap] | min) if wcap is not none else win)", "win"),
    ("the window includes its end", "now_ts >= w_start and now_ts < w_end", "now_ts >= w_start and now_ts <= w_end"),
    ("an unreadable schedule start is no cause", "('SCHEDULE_START_UNREADABLE', w_start is none,", "('SCHEDULE_START_UNREADABLE', false,"),
    ("the window end is the start plus the length in seconds", "(w_start + win * 60)", "(w_start + win)"),
    ("the window's start is not read", "as_timestamp(sch_txt, none) if sch_txt not in bad else none", "none"),
    ("the window's start is read as zero when unreadable", "as_timestamp(sch_txt, none) if sch_txt not in bad else none", "as_timestamp(sch_txt, 0) if sch_txt not in bad else 0"),
    ("the window note is not given", "('DURATION_LIMITED_BY_WINDOW', num and dur_raw > dlim,", "('DURATION_LIMITED_BY_WINDOW', false,"),
    ("the window note fires at equality", "('DURATION_LIMITED_BY_WINDOW', num and dur_raw > dlim,", "('DURATION_LIMITED_BY_WINDOW', num and dur_raw >= dlim,"),
    ("the window end is not published", "'window_end_ts': (w_end | round(0)) if w_end is not none else none,", "'window_end_ts': none,"),
    ("the proposal's window end lookup reads another key", "{{ m.get('window_end_ts') if ok else none }}", "{{ m.get('mem_since_ts') if ok else none }}"),
    # the origin of a lease
    ("a lease the schedule did not start is judged: no script needed", "since_run is not none and since_run >= -10 and since_run <= 900 and", "since_run is not none and"),
    ("the origin accepts a start script 30 minutes before", "since_run <= 900", "since_run <= 1800"),
    ("the origin accepts a start script 14 minutes before only", "since_run <= 900", "since_run <= 840"),
    ("the origin tolerates a script 60 s after the flag", "since_run >= -10", "since_run >= -60"),
    ("the origin tolerates no script after the flag", "since_run >= -10", "since_run >= 0"),
    ("the origin accepts a lease 10 minutes before the window", "l_start_ts >= w_start - 60", "l_start_ts >= w_start - 600"),
    ("the origin needs the lease to start after the window start", "l_start_ts >= w_start - 60", "l_start_ts >= w_start"),
    ("the origin accepts a lease ending 2 hours after the window", "l_end_ts <= w_end + 120", "l_end_ts <= w_end + 7200"),
    ("the origin tolerates no end after the window", "l_end_ts <= w_end + 120", "l_end_ts <= w_end"),
    ("the origin ignores the lease flag", "{%- set origin = lease_on and w_end is not none", "{%- set origin = w_end is not none"),
    ("the comparison is made for any lease", "{%- set cmp_ok = num and origin -%}", "{%- set cmp_ok = num -%}"),
    ("the comparison state ignores the origin", "('UNKNOWN' if (not lease_on or not complete or not origin) else ('DIFFERS' if dev else 'IN LINE'))", "('UNKNOWN' if (not lease_on or not complete) else ('DIFFERS' if dev else 'IN LINE'))"),
    ("the origin is not named", "('LEASE_ORIGIN_UNKNOWN', rt == 'UNKNOWN' and lease_on and verdict == 'VALID' and complete and age is not none and not origin,",
     "('LEASE_ORIGIN_UNKNOWN', false,"),
    ("the lease origin is not published", "'lease_origin': (('SCHEDULE' if origin else 'OTHER') if lease_on else ''),", "'lease_origin': '',"),
    ("the script's last run is read from another attribute", "state_attr('script.ecco_dump_to_grid_start_scheduled', 'last_triggered')", "state_attr('script.ecco_dump_to_grid_start_scheduled', 'current')"),
    # F2: the loop figures, the changes of an UNKNOWN re-target
    ("the loop power is clamped to the proven level", "[[raw_p, 0] | max, pceil] | min", "[[raw_p, 0] | max, hi] | min"),
    ("the loop duration is worked out at the clamped power", "(energy * 1000 / lp_eff * 60)", "(energy * 1000 / p_eff * 60)"),
    ("the loop duration is not bounded by the window", "(([ldur_raw, dlim] | min) | round(0, 'floor'))", "(ldur_raw | round(0, 'floor'))"),
    ("the loop power has no divisor floor", "([lp_q, 500] | max)", "lp_q"),
    ("the loop figures are published for any state", "'loop_power_w': lp_i if num else none,", "'loop_power_w': lp_i if lp is not none else none,"),
    ("the loop power lookup reads the clamped power", "{{ m.get('loop_power_w') if ok else none }}", "{{ m.get('battery_power_w') if ok else none }}"),
    ("the END difference is the clamp's, not the loop's", "((lp_end - l_end_ts) / 60)", "((p_end - l_end_ts) / 60)"),
    ("the loop difference is the clamp's", "{%- set d_loop = (lp_i - l_cmd)", "{%- set d_loop = (p_i - l_cmd)"),
    ("an UNKNOWN re-target lists its changes", "{%- if rt in ['WAIT', 'ALLOWED', 'END NOW'] -%}", "{%- if true -%}"),
    ("a WAIT re-target lists no changes", "{%- if rt in ['WAIT', 'ALLOWED', 'END NOW'] -%}", "{%- if rt in ['ALLOWED', 'END NOW'] -%}"),
    ("END NOW lists no changes", "{%- if rt in ['WAIT', 'ALLOWED', 'END NOW'] -%}", "{%- if rt in ['WAIT', 'ALLOWED'] -%}"),
    # F3: the PV surplus
    ("the infeasible low deadband is 200 W", "raw_p < -150", "raw_p < -200"),
    ("the infeasible low deadband is 100 W", "raw_p < -150", "raw_p < -100"),
    ("the infeasible low includes its boundary", "raw_p < -150", "raw_p <= -150"),
    ("the infeasible low is no cause", "('TARGET_INFEASIBLE_LOW', raw_p is not none and raw_p < -150,", "('TARGET_INFEASIBLE_LOW', false,"),
    ("the export guard counts 400 W for the loop's floor", "(surplus + 500) > nstart", "(surplus + 400) > nstart"),
    ("the export guard counts no floor of the loop", "(surplus + 500) > nstart", "surplus > nstart"),
    ("the export guard includes its boundary", "(surplus + 500) > nstart", "(surplus + 500) >= nstart"),
    ("the export guard is against the rounded target limit", "(surplus + 500) > nstart", "(surplus + 500) > nmax"),
    ("the export guard is no cause", "('PV_SURPLUS_EXPORT_GUARD', surplus is not none and nstart is not none and (surplus + 500) > nstart,", "('PV_SURPLUS_EXPORT_GUARD', false,"),
    ("the surplus is the load less the PV", "{%- set surplus = (pv - load)", "{%- set surplus = (load - pv)"),
    # F4: the memory
    ("the memory must only be 10 minutes old", "(age < 1800 or recent or mem_age < 1800 or not time_ok)", "(age < 1800 or recent or mem_age < 600 or not time_ok)"),
    ("the memory age is not required", "(age < 1800 or recent or mem_age < 1800 or not time_ok)", "(age < 1800 or recent or not time_ok)"),
    ("the memory never carries on", "{%- set mem_since = pm_since if mem_cont else now_ts -%}", "{%- set mem_since = now_ts -%}"),
    ("the memory always carries on", "{%- set mem_since = pm_since if mem_cont else now_ts -%}", "{%- set mem_since = pm_since if pm_since is number else now_ts -%}"),
    ("the memory is dropped after a day (a pause rule)", "{%- set mem_cont = pm_since is number and (now_ts - pm_since) >= -5 -%}", "{%- set mem_cont = pm_since is number and (now_ts - pm_since) >= -5 and (now_ts - pm_since) <= 86400 -%}"),
    ("the memory is dropped after two hours", "{%- set mem_cont = pm_since is number and (now_ts - pm_since) >= -5 -%}", "{%- set mem_cont = pm_since is number and (now_ts - pm_since) >= -5 and (now_ts - pm_since) <= 7200 -%}"),
    ("the memory survives a start in the future", "and (now_ts - pm_since) >= -5 -%}", " -%}"),
    ("the memory is not told by a reload", "{%- set mem_ok = this is defined and this is not none -%}", "{%- set mem_ok = true -%}"),
    ("the wait ignores the memory", "(mem_since + 1800) if mem_age < 1800 else 0", "0"),
    ("the wait ignores the previous would-change", "(prev_entry + 1800) if recent else 0", "0"),
    ("the wait ignores the age of the lease", "(l_start_ts + 1800) if (age is not none and age < 1800) else 0", "0"),
    ("the memory is not published", "'mem_since_ts': (mem_since | round(0, 'floor'))\n", "'mem_since_ts': none\n"),
    ("the young memory is not named", "('MEMORY_YOUNG', rt == 'WAIT' and mem_ok and mem_age < 1800,", "('MEMORY_YOUNG', false,"),
    ("an unreadable `this` is not named", "('MEMORY_UNAVAILABLE', rt == 'WAIT' and not mem_ok,", "('MEMORY_UNAVAILABLE', false,"),
    # F5: END NOW
    ("END NOW ignores a hold", "{%- set end_hold = hold == 'held' -%}", "{%- set end_hold = false -%}"),
    ("END NOW ignores the reserve", "{%- set end_res = reserve >= 0 and l_stop is not none and reserve > l_stop -%}", "{%- set end_res = false -%}"),
    ("END NOW at an equal reserve", "reserve > l_stop -%}", "reserve >= l_stop -%}"),
    ("END NOW only for a lease older than 30 minutes", "('END NOW' if end_now else", "('END NOW' if (end_now and age is not none and age >= 1800) else"),
    ("END NOW only with a VALID proposal", "('END NOW' if end_now else", "('END NOW' if (end_now and verdict == 'VALID') else"),
    ("END NOW only for a lease the schedule started", "('END NOW' if end_now else", "('END NOW' if (end_now and origin) else"),
    ("END NOW is reported as WAIT", "('END NOW' if end_now else", "('WAIT' if end_now else"),
    ("the hold is not named", "('HOLD_ACTIVE', rt == 'END NOW' and end_hold,", "('HOLD_ACTIVE', false,"),
    ("the reserve is not named", "('RESERVE_ABOVE_LEASE_STOP_SOC', rt == 'END NOW' and end_res,", "('RESERVE_ABOVE_LEASE_STOP_SOC', false,"),
    ("the re-target lookup does not pass END NOW on", "'WAIT', 'ALLOWED', 'END NOW']) else 'UNKNOWN' }}", "'WAIT', 'ALLOWED']) else 'UNKNOWN' }}"),
    # F6: the lease's end text
    ("an end text in a repeated hour is read", "(l_end_rt and not l_end_rep and", "(l_end_rt and"),
    ("an end text in a skipped hour is read", "(l_end_rt and not l_end_rep and", "(l_end_raw is not none and not l_end_rep and"),
    ("an end text before now is read", "l_end_raw > now_ts and (l_start_ts is none or l_end_raw > l_start_ts)", "(l_start_ts is none or l_end_raw > l_start_ts)"),
    ("an end text before the lease start is read", "l_end_raw > now_ts and (l_start_ts is none or l_end_raw > l_start_ts)", "l_end_raw > now_ts"),
    ("the repeated hour is told by the hour after only", "or ((l_end_raw - 3600) | timestamp_custom('%Y-%m-%d %H:%M:%S', true, '')) == l_end_txt)", ")"),
    ("the repeated hour is told by the hour before only", "(((l_end_raw + 3600) | timestamp_custom('%Y-%m-%d %H:%M:%S', true, '')) == l_end_txt or ", "("),
    # F9: a per-render time in a published attribute
    ("a time that moves with the clock is published on the proposal", "{{ m.get('limited_by') if ok else '' }}", "{{ m.get('limited_by') if ok else '' }}{{ as_timestamp(now()) | round(0) }}"),
    ("the model carries the time of its evaluation (the 393 rows an hour of the lab)", "'verdict': verdict,", "'verdict': verdict,\n                  'evaluated_ts': (now_ts | round(0)),"),
    ("the model carries the poll's time", "'verdict': verdict,", "'verdict': verdict,\n                  'poll_skew_s': pskew,"),
    ("the END deviation is ignored", "{%- set dev = dev_stop or dev_exp or dev_end -%}", "{%- set dev = dev_stop or dev_exp -%}"),
    ("the export deviation is ignored", "{%- set dev = dev_stop or dev_exp or dev_end -%}", "{%- set dev = dev_stop or dev_end -%}"),
    ("the Stop SOC deviation is ignored", "{%- set dev = dev_stop or dev_exp or dev_end -%}", "{%- set dev = dev_exp or dev_end -%}"),
    ("the origin is reported for a lease that is not running", "'lease_origin': (('SCHEDULE' if origin else 'OTHER') if lease_on else ''),", "'lease_origin': ('SCHEDULE' if origin else 'OTHER'),"),
    ("the lease age is published in tenths of a minute", "'lease_age_min': age_min_i if lease_on else none,", "'lease_age_min': ((age / 60) | round(1)) if (lease_on and age is not none) else none,"),
    # ---- RC1 and RC2 of the second review: a RUNNING lease's bound (the window it runs in at every render, and for a lease the schedule started its own latched end) --------------------------------
    ("RC1: a running lease is bounded only inside the window (after the window end it gets the whole length again)", "if (lease_on and run_end is not none) else none -%}", "if (lease_on and run_end is not none and now_ts < w_end) else none -%}"),
    ("RC1: the running lease's bound is not used at all (the old behaviour)", "{%- set wcap = wcap_r if wcap_r is not none else wcap_w -%}", "{%- set wcap = wcap_w -%}"),
    ("RC1: the window's own count wins over the running lease's", "{%- set wcap = wcap_r if wcap_r is not none else wcap_w -%}", "{%- set wcap = wcap_w if wcap_w is not none else wcap_r -%}"),
    ("RC1: a lease that is not running is bounded too (the next window's start gets no time after the window end)", "if (lease_on and run_end is not none) else none -%}", "if (run_end is not none) else none -%}"),
    ("RC1: the running lease's time left is not clipped at 0 (a negative duration)", "([(((run_end - now_ts + 20) / 60) | round(0, 'floor')), 0] | max)", "(((run_end - now_ts + 20) / 60) | round(0, 'floor'))"),
    ("RC1: the running lease's time left ignores the schedule's 20 s", "(((run_end - now_ts + 20) / 60) | round(0, 'floor'))", "(((run_end - now_ts) / 60) | round(0, 'floor'))"),
    ("RC1: the running lease's time left is 30 s more generous", "(((run_end - now_ts + 20) / 60) | round(0, 'floor'))", "(((run_end - now_ts + 50) / 60) | round(0, 'floor'))"),
    ("RC1: the running lease's time left rounds to the nearest minute", "(((run_end - now_ts + 20) / 60) | round(0, 'floor'))", "(((run_end - now_ts + 20) / 60) | round(0))"),
    ("RC2: the running lease's bound ignores its own latched end (a helper edited while it runs moves it)", "{%- set run_end = ([w_end, l_end_ts] | min) if origin else w_end -%}", "{%- set run_end = w_end -%}"),
    ("RC2: the running lease's bound is the later of the window end and its own end", "{%- set run_end = ([w_end, l_end_ts] | min) if origin else w_end -%}", "{%- set run_end = ([w_end, l_end_ts] | max) if origin else w_end -%}"),
    ("RC2: the lease's own end bounds any lease that has a readable end, not only the schedule's", "if origin else w_end -%}", "if (w_end is not none and l_end_ts is not none) else w_end -%}"),
    ("RC2: the lease's own end counts a minute early", "{%- set run_end = ([w_end, l_end_ts] | min) if origin else w_end -%}", "{%- set run_end = ([w_end, l_end_ts - 60] | min) if origin else w_end -%}"),
    ("RC1: the reason does not say it is the running lease's window that leaves nothing", "(', the window the running lease is authorised for leaves ' ~ wcap ~ ' minutes' if (lease_on and wcap is not none) else",
     "(', the authorised schedule window leaves ' ~ wcap ~ ' minutes' if (lease_on and wcap is not none) else"),

    # ---- S-A2: the Export start gate (NOT ALLOWED, actionable, the hold-off) and the leases consumer (the re-target) -----------------------------------------------------------------
    ("NOT ALLOWED is never published", "{%- set pub = 'NOT ALLOWED' if (verdict == 'VALID' and (gcodes | length) > 0) else verdict -%}", "{%- set pub = verdict -%}"),
    ("NOT ALLOWED replaces an UNVERIFIED proposal too", "{%- set pub = 'NOT ALLOWED' if (verdict == 'VALID' and (gcodes | length) > 0) else verdict -%}",
     "{%- set pub = 'NOT ALLOWED' if (verdict in ['VALID', 'UNVERIFIED'] and (gcodes | length) > 0) else verdict -%}"),
    ("NOT ALLOWED replaces any proposal", "{%- set pub = 'NOT ALLOWED' if (verdict == 'VALID' and (gcodes | length) > 0) else verdict -%}", "{%- set pub = 'NOT ALLOWED' if (gcodes | length) > 0 else verdict -%}"),
    ("the published state is the proposal's own verdict", "'state': pub,", "'state': verdict,"),
    ("actionable ignores the gate", "{%- set actionable = verdict == 'VALID' and g_open and eg_age is not none and eg_age >= 60 and (gcodes | length) == 0 -%}", "{%- set actionable = verdict == 'VALID' -%}"),
    ("actionable is true for an UNVERIFIED proposal", "{%- set actionable = verdict == 'VALID' and g_open and eg_age is not none and eg_age >= 60 and (gcodes | length) == 0 -%}", "{%- set actionable = verdict in ['VALID', 'UNVERIFIED'] and g_open and eg_age is not none and eg_age >= 60 and (gcodes | length) == 0 -%}"),
    ("actionable is true while the gate settles", "{%- set actionable = verdict == 'VALID' and g_open and eg_age is not none and eg_age >= 60 and (gcodes | length) == 0 -%}", "{%- set actionable = verdict == 'VALID' and g_read and not g_incons and egs == 'on' -%}"),
    ("actionable is never true", "'actionable': actionable,", "'actionable': false,"),
    ("the gate's codes are not published", "'blocked_by': gcodes if pub == 'NOT ALLOWED' else ns.c,", "'blocked_by': ns.c,"),
    ("the gate's codes replace the proposal's own causes", "'blocked_by': gcodes if pub == 'NOT ALLOWED' else ns.c,", "'blocked_by': gcodes if (gcodes | length) > 0 else ns.c,"),
    ("NOT ALLOWED does not name the gate's codes in its reason", "does not allow a start now (' ~ (gcodes | join(', ')) ~ ')'] + ns.n) if pub == 'NOT ALLOWED' else", "does not allow a start now'] + ns.n) if pub == 'NOT ALLOWED' else"),
    ("NOT ALLOWED gives the reasons of a VALID proposal", "+ ns.n) if pub == 'NOT ALLOWED' else ((ns.b + ns.n)", "+ ns.n) if false else ((ns.b + ns.n)"),
    ("the hold-off is 59 s", "(eg_age is not none and eg_age >= 60)", "(eg_age is not none and eg_age >= 59)"),
    ("the hold-off is 61 s", "(eg_age is not none and eg_age >= 60)", "(eg_age is not none and eg_age >= 61)"),
    ("the hold-off excludes exactly 60 s", "(eg_age is not none and eg_age >= 60)", "(eg_age is not none and eg_age > 60)"),
    ("the hold-off is not applied", "(['GATE_SETTLING'] if (g_open and not (eg_age is not none and eg_age >= 60)) else [])", "[]"),
    ("the hold-off is named for a closed gate too", "(['GATE_SETTLING'] if (g_open and not", "(['GATE_SETTLING'] if (g_read and not"),
    ("the hold-off is judged by the gate's last update, not its last change", "as_timestamp(eg_obj.last_changed, none)) if (eg_obj is not none and eg_obj.last_changed is defined)",
     "as_timestamp(eg_obj.last_updated, none)) if (eg_obj is not none and eg_obj.last_updated is defined)"),
    ("an unreadable gate is not named", "['GATE_UNREADABLE'] if not g_read else", "[] if not g_read else"),
    ("an inconsistent gate is not named", "(['GATE_INCONSISTENT'] if g_incons else [])", "[]"),
    ("a gate on with a cause is not inconsistent", "{%- set g_incons = g_read and ((egs == 'on' and (egl | length) > 0) or (egs == 'off' and (gn.c | length) == 0)) -%}", "{%- set g_incons = g_read and (egs == 'off' and (gn.c | length) == 0) -%}"),
    ("a gate off with no cause is not inconsistent", "{%- set g_incons = g_read and ((egs == 'on' and (egl | length) > 0) or (egs == 'off' and (gn.c | length) == 0)) -%}", "{%- set g_incons = g_read and (egs == 'on' and (egl | length) > 0) -%}"),
    ("CS-04: a gate off whose causes are none of them text is not inconsistent", "{%- set g_incons = g_read and ((egs == 'on' and (egl | length) > 0) or (egs == 'off' and (gn.c | length) == 0)) -%}", "{%- set g_incons = g_read and ((egs == 'on' and (egl | length) > 0) or (egs == 'off' and (egl | length) == 0)) -%}"),
    ("TEST-08 (E18): an unreadable gate also lists the codes of its list", "['GATE_UNREADABLE'] if not g_read else", "((['GATE_UNREADABLE'] + gn.c) if not g_read else"),
    ("TEST-08 (E20): the model carries an extra boolean", "'actionable': actionable,", "'actionable': actionable, 'gate_open': g_open,"),
    ("CS-06: the published power is not rounded up", "{%- set p_i = (p_q | round(0, 'floor')) if p_q is not none else none -%}", "{%- set p_i = (p | round(0, 'floor')) if p is not none else none -%}"),
    ("CS-06: the power is rounded to the nearest step, not up", "{%- set p_q = ([(((p / 500) | round(0, 'ceil')) * 500), hi] | min)", "{%- set p_q = ([(((p / 500) | round(0, 'common')) * 500), hi] | min)"),
    ("CS-06: the rounded power may pass the proven level", "{%- set p_q = ([(((p / 500) | round(0, 'ceil')) * 500), hi] | min)", "{%- set p_q = ([(((p / 500) | round(0, 'ceil')) * 500), 1e9] | min)"),
    ("CS-06: the loop power may pass the Power Ceiling", "([(((lp / 500) | round(0, 'ceil')) * 500), pceil] | min)", "([(((lp / 500) | round(0, 'ceil')) * 500), 1e9] | min)"),
    ("CS-06: the loop power is not the proposal power below the proven level", "(p_q if lp == p else", "(p_q if false else"),
    ("CS-06: the duration is worked out at the unrounded power", "{%- set p_eff = ([p_q, 500] | max) if p_q is not none else none -%}", "{%- set p_eff = ([p, 500] | max) if p is not none else none -%}"),
    ("CS-06: the duration is rounded to the nearest 5 minutes", "{%- set dur_i = ((((dur / 5) | round(0, 'floor')) * 5) | int)", "{%- set dur_i = ((((dur / 5) | round(0, 'common')) * 5) | int)"),
    ("CS-06: the duration is rounded up to 5 minutes", "{%- set dur_i = ((((dur / 5) | round(0, 'floor')) * 5) | int)", "{%- set dur_i = ((((dur / 5) | round(0, 'ceil')) * 5) | int)"),
    ("CS-06: the loop duration is rounded up to 5 minutes", "{%- set ldur_i = ((((ldur / 5) | round(0, 'floor')) * 5) | int)", "{%- set ldur_i = ((((ldur / 5) | round(0, 'ceil')) * 5) | int)"),
    ("CS-06: the raw requirement is rounded down", "{%- set raw_p_i = ((((raw_p / 500) | round(0, 'ceil')) * 500) | int)", "{%- set raw_p_i = ((((raw_p / 500) | round(0, 'floor')) * 500) | int)"),
    ("CS-06: the PV surplus text carries the live surplus", "{%- set surplus_i = ((((surplus / 500) | round(0, 'ceil')) * 500) | int)", "{%- set surplus_i = (surplus | round(0))"),
    ("an open gate needs no empty list", "{%- set g_open = g_read and egs == 'on' and (egl | length) == 0 -%}", "{%- set g_open = g_read and egs == 'on' -%}"),
    ("an unknown gate state is read", "{%- set g_read = egs in ['on', 'off'] and egl is not none -%}", "{%- set g_read = egs in ['on', 'off', 'unknown'] and egl is not none -%}"),
    ("a gate whose list cannot be read is read", "{%- set g_read = egs in ['on', 'off'] and egl is not none -%}", "{%- set g_read = egs in ['on', 'off'] -%}"),
    ("a text is a list of causes", "(egb | list) if (egb is iterable and egb is not string and egb is not mapping) else none", "(egb | list) if (egb is iterable and egb is not mapping) else none"),
    ("a mapping is a list of causes", "(egb | list) if (egb is iterable and egb is not string and egb is not mapping) else none", "(egb | list) if (egb is iterable and egb is not string) else none"),
    ("a cause is cut at 41 characters", "{%- set gn.c = gn.c + [c[:40]] -%}", "{%- set gn.c = gn.c + [c[:41]] -%}"),
    ("a cause is not cut", "{%- set gn.c = gn.c + [c[:40]] -%}", "{%- set gn.c = gn.c + [c] -%}"),
    ("a cause that is no text is read", "{%- for c in (egl if egl is not none else []) if c is string -%}", "{%- for c in (egl if egl is not none else []) -%}"),
    ("the gate's causes are kept in no order", "{%- set gcodes = ['GATE_UNREADABLE'] if not g_read else (gn.c + (", "{%- set gcodes = ['GATE_UNREADABLE'] if not g_read else (((gn.c | reverse | list)) + ("),
    # the leases consumer
    ("the re-target ignores the leases consumer", "(age < 1800 or recent or mem_age < 1800 or not time_ok)", "(age < 1800 or recent or mem_age < 1800)"),
    ("the leases consumer counts when it is not off", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 60 -%}", "{%- set time_ok = tls != 'off' and tl_age is not none and tl_age >= 60 -%}"),
    ("the leases consumer counts the moment it turns on", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 60 -%}", "{%- set time_ok = tls == 'on' -%}"),
    ("the leases consumer counts after 59 s", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 60 -%}", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 59 -%}"),
    ("the leases consumer counts after 61 s", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 60 -%}", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 61 -%}"),
    ("the leases consumer counts after more than 60 s", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age >= 60 -%}", "{%- set time_ok = tls == 'on' and tl_age is not none and tl_age > 60 -%}"),
    ("the leases consumer's age is the gate's", "as_timestamp(tl_obj.last_changed, none)) if (tl_obj is not none and tl_obj.last_changed is defined)", "as_timestamp(eg_obj.last_changed, none)) if (tl_obj is not none and tl_obj.last_changed is defined)"),
    ("the leases consumer's age is its last update", "as_timestamp(tl_obj.last_changed, none)) if (tl_obj is not none and tl_obj.last_changed is defined)",
     "as_timestamp(tl_obj.last_updated, none)) if (tl_obj is not none and tl_obj.last_updated is defined)"),
    ("the lack of time trust is not named", "('TIME_NOT_TRUSTED', rt == 'WAIT' and not time_ok,", "('TIME_NOT_TRUSTED', false,"),
    ("the lack of time trust is named outside a wait", "('TIME_NOT_TRUSTED', rt == 'WAIT' and not time_ok,", "('TIME_NOT_TRUSTED', not time_ok,"),
    ("the lack of time trust is described as off for a young consumer", "(', but it turned on less than 60 s ago' if tls == 'on' else ' (it must read on)')", "(', but it turned on less than 60 s ago' if tls != 'on' else ' (it must read on)')"),
    ("the lack of time trust of an off consumer is worded differently", "(', but it turned on less than 60 s ago' if tls == 'on' else ' (it must read on)')", "(', but it turned on less than 60 s ago' if tls == 'on' else ' (off)')"),
    ("the wait of a lack of time trust is a time", "{%- set wait_until = (([w_age, w_rec, w_mem] | max) if ([w_age, w_rec, w_mem] | max) > 0 else none) if rt == 'WAIT' else none -%}",
     "{%- set wait_until = ([w_age, w_rec, w_mem] | max) if rt == 'WAIT' else none -%}"),
    ("the lack of time trust blocks END NOW", "('END NOW' if end_now else", "('END NOW' if (end_now and time_ok) else"),
    ("the lack of time trust blocks a re-target with no deviation", "('NO CHANGE' if not dev else ('WAIT' if", "('NO CHANGE' if (not dev and time_ok) else ('WAIT' if"),
]


def mutate(text: str, old: str, new: str) -> str:
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"a mutant anchor must occur exactly once, found {n}x: {old[:70]!r}")
    return text.replace(old, new)


# ===========================================================================================================================
# run
# ===========================================================================================================================
README_PINS = ("READ-ONLY SHADOW", "NOTHING INSTALLED", "soft", "time trust", "pinned", "Intelligence", "schedule", "DISCHARGE_EFFICIENCY", "UNVERIFIED",
               "the END of the lease plus a guarded re-START", "exc1", "NOT ESTABLISHED", "NOT ALLOWED", "actionable", "GATE_SETTLING", "GATE_UNREADABLE", "GATE_INCONSISTENT", "TIME_NOT_TRUSTED", "D-PIN", "D-C04a",
               "binary_sensor.ecco_export_start_allowed", "binary_sensor.ecco_time_trusted_for_leases", "the leases consumer ONLY", "a restart restores the model's state and attribute", "a coordinator decision taken as an engineering decision", "END NOW", "LEASE_ORIGIN_UNKNOWN", "energy_above_reserve_kwh", "0.90", "recorder",
               "bounded by the schedule's own window", "loop_battery_power_w", "TARGET_INFEASIBLE_LOW", "MEMORY_YOUNG", "Install ONLY with NO Dump to Grid or Free Power lease running",
               "OUTSIDE any armed scheduled Export or charge run", "window end plus 10 minutes", "test_ecco_start_gate.py", "owner decision", "except as the latched value of a RUNNING lease", "LEASE_STOP_SOC_UNREADABLE", "lower the dongle's Power Ceiling to the proven level",
               "prove the proven level and raise it", "a shadow with no re-target data", "SCHEDULE path", "never enters the floor", "a running lease gets no time past the end of the window it runs in",
               "min(window end, the lease's own latched end) + 20 s", "cannot move it later", "the END rule never fires", "can only keep the end or shorten it")


def main() -> int:
    print("[0] static")
    sp = static_problems(TEXT)
    check("the file loads with no repeated key; only `template:`; the nine entities and nothing else; no service call, action, trigger, helper, script or automation; it reads exactly the "
          "expected entities, (entity, attribute) pairs and state objects, every entity existing in the repository; `this` is used for its model attribute only; no forecast entity; of the start gate and the "
          "time trust packages exactly the Export start gate and the leases consumer are mentioned, whole and with their domain (never the charge gate, the bypass, another consumer, a per-clock sensor, the overall "
          "sensor or an internal helper); the header states the rules, the constants (equal to the templates') and the limits; ASCII, LF, no site value; the eight lookups share one two-line check", sp == [], str(sp[:3]))
    import ecco_site_render as render
    site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
    spots = [m.start() for m in re.finditer(DONGLE, TEXT)]
    try:
        rendered, counts = render.render_text(PKG_REL, TEXT, site, render.firmware_actions(ROOT))
    except render.RenderError as exc:
        rendered, counts = "", {"error": str(exc)[:120]}
    check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them and leaves none behind",
          counts == {"entity": len(spots)} and len(spots) >= 10 and DONGLE not in rendered and "site_dongle_" in rendered, str(counts))
    check("the header pins are live: a header that loses a rule, a constant or the soft-gate statement is refused",
          bool(static_problems(TEXT.replace("READ-ONLY SHADOW", "READ-ONLY NOTE", 1))) and bool(static_problems(TEXT.replace("ONLY THE CONTROL STATE READ MODEL", "ANYTHING MAY READ", 1)))
          and bool(static_problems(TEXT.replace("THE START GATE AND THE TIME TRUST INPUT ARE READ HERE, ONLY AS FAR AS THE PINS ALLOW", "THE GATE IS READ", 1)))
          and bool(static_problems(TEXT.replace("GATE_SETTLE_S = 60", "GATE_SETTLE_S = 30"))) and bool(static_problems(TEXT.replace("eg_age >= 60", "eg_age >= 30")))
          and bool(static_problems(TEXT.replace("DISCHARGE_EFFICIENCY = 0.90", "DISCHARGE_EFFICIENCY = 0.95", 1))) and bool(static_problems(TEXT.replace("* cap * 0.90", "* cap * 0.93", 1)))
          and bool(static_problems(TEXT.replace("Install ONLY with NO Dump to Grid or Free Power lease running", "Install any time", 1)))
          and bool(static_problems(TEXT.replace("is NOT read", "is read", 1))))

    print("[1] inputs")
    bp = boundary_problems()
    check(f"{len(ROWS)} rows (every input one at a time at its limits, beyond them and unreadable; the hold, the limits state, the telemetry flag, the floor members (the dongle's staged Stop SOC set to 85 in "
          "each), the SOC against the floor, the capacity, the target against the export limit, the load and PV against the clamps, a PV surplus the target cannot hold at every boundary, the window, "
          "the Export schedule's window start unreadable and every boundary of the time left in it, the poll freshness and the forms of the poll text): the template equals the independent "
          "reference on every one (state, causes in order, notes, every number, the loop figures, the window end, every numeric sensor unavailable and never 0 unless VALID or UNVERIFIED)", bp == [], str(bp[:3]))
    w = new_world()
    ok_codes = True
    for eid, code in CODE_OF.items():
        for v in BAD_RAW:
            if eid == X.GRID and v == "-5":
                continue                    # a grid reading may be negative (export); every other input in the list is garbage for it
            w.bulk({**X.HEALTHY, eid: v}, poll_age=0.0)
            if w.state(X.PROPOSAL) != "INVALID" or code not in (w.attr(X.PROPOSAL, "blocked_by") or []) or any(w.state(e) != "unavailable" for e in X.NUMERIC):
                ok_codes = False
                print(f"      {eid} {v!r}: {w.state(X.PROPOSAL)} {w.attr(X.PROPOSAL, 'blocked_by')}")
    check("every numeric input and the schedule's start, read as missing, unavailable, unknown, empty, text, nan, infinite or huge, makes the proposal INVALID with its own cause named and no number published", ok_codes)
    w.bulk({**X.HEALTHY, X.SOC: "unknown", X.PV: "abc"}, poll_age=0.0)
    texts = w.attr(X.PROPOSAL, "reasons") or []
    check("a cause is named with the entity and what it reads", any(t.startswith("SOC_UNREADABLE: sensor.ecco_clock_dongle_ecco_battery_soc reads unknown") for t in texts)
          and any(t.startswith("PV_UNREADABLE: sensor.ecco_clock_dongle_ecco_pv_power reads abc") for t in texts), str(texts[:3]))
    w = new_world()
    w.make_healthy()
    w.start_feed()
    w.advance(30)
    healthy_before = w.state(X.PROPOSAL)
    w.stop_feed()
    w.advance(60)
    mid = w.state(X.PROPOSAL)
    w.advance(120)
    after = w.state(X.PROPOSAL)
    codes = w.attr(X.PROPOSAL, "blocked_by")
    check("the freshness is judged by the poll text's VALUE and moves with the clock alone: valid while the dongle polls, still valid within 90 s of the last poll, INVALID (TELEMETRY_STALE) "
          "after the minute that follows 90 s, with no entity changing", healthy_before == "VALID" and mid == "VALID" and after == "INVALID" and codes == ["TELEMETRY_STALE"], f"{healthy_before} {mid} {after} {codes}")
    # the window moves with the clock too: a proposal made 5 minutes before the window ends is INVALID 6 minutes later (no start fits), with no entity changing
    w = new_world()
    w.make_healthy({X.SCH_START: started_ago(14400 - 900)})
    w.start_feed()
    w.advance(30)
    open_ = (w.state(X.PROPOSAL), w.state(X.P_DUR))
    w.advance(6 * 60)
    late = (w.state(X.PROPOSAL), w.attr(X.PROPOSAL, "blocked_by"), w.state(X.P_DUR))
    check("the window closes with the clock alone: 15 minutes left it proposes at most 14 minutes (the schedule's own count; published as 10, rounded down to 5), 6 minutes later no start fits and the proposal is INVALID",
          open_ == ("VALID", "10") and late[0] == "INVALID" and late[1] == ["BELOW_MINIMUM_DURATION"], f"{open_} {late}")
    gr = gate_rows_problems()
    check(f"[1b] the Export start gate: {len(GATE_READINGS)} readings (open, closed by one, three or a very long cause, a cause that is no text, on with a cause, off with none, a list that is a text, a mapping, a number, "
          f"missing or none, unavailable, unknown, empty, neither on nor off, the entity missing) x {len(GATE_AGE_PAIRS)} ages (0, 1, 59, 59.9, 60, 61 and 600 s; the consumer's age too) x {len(GATE_PROPOSALS)} proposals "
          "(VALID, HOLD, INVALID, UNVERIFIED): the template equals the reference on every one (state, the gate's codes in order, actionable, every number); hand-computed anchors: NOT ALLOWED names the gate's codes in its first "
          "reason and keeps the numbers, GATE_SETTLING below 60 s and VALID with actionable at 60 s, GATE_UNREADABLE, GATE_INCONSISTENT in both directions, a code cut at 40 characters, a HOLD or an INVALID proposal keeps its own "
          "causes, an UNVERIFIED one is never actionable", gr == [], str(gr[:3]))
    grt = gate_realtime_problems()
    check("[1b] in real time: the gate turned on is NOT ALLOWED with GATE_SETTLING for 59 s and VALID with actionable at 60 s; an attribute that changes alone does not renew its age (last_changed, not last_updated); a gate that "
          "flaps starts the 60 s afresh; 10 s and 50 s after a restart (every entity young) it is settling and 80 s after it is VALID; the leases consumer turned off while a change is allowed is WAIT with TIME_NOT_TRUSTED "
          "only (no time to wait for, the would-change stamp kept), turned on again it adds RECENT_CHANGE until 30 minutes after the first would-change, and 60 s of trust leave only that gap", grt == [], str(grt[:3]))
    am = anchors()
    check("hand-computed anchors: the healthy evening is floor 40 %, 10.53 kWh (0.90), 4000 W (3800 rounded up to 500), net 3000 W, 155 min (157 rounded down to 5); PV, the reserve rounding up, the Stop SOC requests, the dongle minimum, the dongle's "
          "staged Stop SOC left at 80 (not a member), the export limit as a ceiling, the clamps, UNVERIFIED with the loop figures, the live-like limits (3000 W for 183 minutes against the loop's 4656 W "
          "for 118), the window and the time left in it at the schedule's own rounding, a PV surplus the target cannot hold, no energy, a hold, the 10 minute minimum on both sides", am == [], str(am[:3]))

    print("[2] maths")
    wm = new_world()
    ok_order = True
    for s, r in ((20, 50), (50, 20), (35, 50), (50, 35), (50, 5), (5, 50)):
        apply_case(wm, {X.STOP_S: str(float(s)), X.RESERVE: str(r)})
        if wm.state(X.P_FLOOR) != "50":
            ok_order = False
            print(f"      floor from stop {s} and reserve {r} is {wm.state(X.P_FLOOR)}, not 50")
    apply_case(wm, {X.STOP_S: "5.0", X.RESERVE: "3"})
    ok_order = ok_order and wm.state(X.P_FLOOR) == "10"
    apply_case(wm, {X.STOP_S: "33.2", X.RESERVE: "12"})
    ok_order = ok_order and wm.state(X.P_FLOOR) == "34"
    apply_case(wm, {X.STOP_S: "33.2", X.RESERVE: "12", X.STOP_D: "95.0"})
    ok_order = ok_order and wm.state(X.P_FLOOR) == "34"
    check("the floor is the maximum of the schedule's Stop SOC, the effective reserve and the dongle minimum, whatever their order, and is rounded UP (33.2 gives 34, a reserve of 62.4 gives 63): "
          "never below any of them; the dongle's staged Stop SOC (a leftover) is not a member, even at 95", ok_order)
    apply_case(wm, {})
    base_power = float(wm.state(X.P_POWER))
    apply_case(wm, {X.PV: "500.0"})
    less = float(wm.state(X.P_POWER))
    wm.put("sensor.solcast_pv_forecast_today", "99999")
    # the Intelligence ids are split in two adjacent literals: intelligence/tests/test_intel_advisory_contract.py forbids the whole ids in any other HA file
    wm.put("sensor.ecco_" "intel_pv_tomorrow", "99999")
    wm.put("sensor.ecco_" "intel_dump_to_grid", "99999", {"advice": {"stop_soc_pct": 99, "export_kwh": 99}})
    wm.put(X.CAPM, "x", {"capacity_kwh": 30.0, "capacity_basis": "configured", "discharge_w": 1, "pv_w": 99999, "energy_above_reserve_kwh": 99.0})
    wm.force()
    check("the power follows MEASURED PV exactly (500 W of PV is 500 W less battery power) and no forecast or advice entity, and no attribute of the battery runtime sensor beyond its capacity, changes anything, even a huge one",
          base_power - less == 500.0 and float(wm.state(X.P_POWER)) == less and wm.state(X.PROPOSAL) == "VALID" and wm.state(X.P_ENERGY) == "10.53", f"{base_power} {less} {wm.state(X.P_POWER)} {wm.state(X.P_ENERGY)}")
    apply_case(wm, {X.PV: "99999.0"})
    check("an implausible PV reading is INVALID, never a huge credit that justifies an export", wm.state(X.PROPOSAL) == "INVALID" and "PV_UNREADABLE" in wm.attr(X.PROPOSAL, "blocked_by"))
    apply_case(wm, {X.PV: "3700.0"})
    check("PV that nearly covers the target gives a small power, a duration worked out at the dongle's 500 W floor (no division by zero), and says so in a note",
          wm.state(X.P_POWER) == "500" and wm.state(X.PROPOSAL) == "VALID" and any(n.startswith("NOTE LOW_BATTERY_POWER") for n in wm.attr(X.PROPOSAL, "notes")), str(wm.attr(X.PROPOSAL, "notes")))
    apply_case(wm, {X.PV: "5000.0"})
    check("PV that exceeds the whole target (and the load) is no proposal: the dongle would show TARGET INFEASIBLE LOW and its export guard would end the lease; it was VALID with a power of 0",
          wm.state(X.PROPOSAL) == "INVALID" and "TARGET_INFEASIBLE_LOW" in wm.attr(X.PROPOSAL, "blocked_by") and "PV_SURPLUS_EXPORT_GUARD" in wm.attr(X.PROPOSAL, "blocked_by")
          and all(wm.state(e) == "unavailable" for e in X.NUMERIC), f"{wm.state(X.PROPOSAL)} {wm.attr(X.PROPOSAL, 'blocked_by')}")
    apply_case(wm, {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"})
    check("above the proven level the power is clamped to it and the state is UNVERIFIED, with the reason; the numbers are still published (clamped), the raw requirement is shown, and the loop's own figures "
          "(its power at the ceiling and the duration at it) are published separately",
          wm.state(X.PROPOSAL) == "UNVERIFIED" and wm.state(X.P_POWER) == "6000" and wm.attr(X.PROPOSAL, "raw_battery_power_w") == 6500 and wm.attr(X.PROPOSAL, "limited_by") == "PROVEN_LEVEL"
          and wm.attr(X.PROPOSAL, "loop_battery_power_w") == 6500 and any(n.startswith("UNVERIFIED ABOVE_PROVEN_LEVEL") for n in wm.attr(X.PROPOSAL, "notes")), f"{wm.state(X.PROPOSAL)} {wm.state(X.P_POWER)} {wm.attr(X.PROPOSAL, 'notes')}")
    sink = []
    for soc in range(41, 101):
        apply_case(wm, {X.SOC: str(float(soc))})
        if wm.state(X.PROPOSAL) == "VALID":
            ex = max(soc - 40 - 1, 0) / 100 * 30.0 * 0.90 * 1000 / 4000 * 60
            sink.append(float(wm.state(X.P_DUR)) == min(int(ex), 240) // 5 * 5)
    check("the duration is the exact minutes (at the power rounded up to 500 W) rounded DOWN to 5 minutes, bounded by the schedule window, over every SOC from 41 to 100", sink and all(sink), f"{len(sink)} cases")
    apply_case(wm, {X.MX: "3600.0", X.TGT: "9000.0"})
    check("an export limit is a ceiling for the target, never the target: a target above the limit less the START headroom is held at 3400 W and says so; the limit itself is never proposed",
          wm.state(X.P_NET) == "3400" and any(n.startswith("NOTE TARGET_LIMITED_BY_EXPORT_LIMIT") for n in wm.attr(X.PROPOSAL, "notes")))
    apply_case(wm, {}, capm=(25.0, "measured"))
    e_meas = wm.state(X.P_ENERGY)
    apply_case(wm, {}, capm=(35.0, "measured"))
    e_big = wm.state(X.P_ENERGY)
    apply_case(wm, {})
    e_cfg = wm.state(X.P_ENERGY)
    check("a capacity the battery runtime package has MEASURED below the configured one is used (and noted); a larger or a not measured one is never trusted over the configured",
          e_meas == "8.775" and e_big == e_cfg == "10.53", f"{e_meas} {e_big} {e_cfg}")
    wm2 = new_world()
    seen = []
    for left in range(1, 1500, 7):                               # (at 0 s left the window is over: the proposal is for the next one)
        apply_case(wm2, {X.WIN: "240.0", X.SCH_START: started_ago(14400 - left)})
        if wm2.state(X.PROPOSAL) == "VALID":
            seen.append(T0 + float(wm2.state(X.P_DUR)) * 60 <= T0 + left + 20 + 1e-6)
    check("the proposal never ends after the schedule's window end (plus its own 20 s rounding), at every time left from 1 s to 25 minutes", len(seen) > 100 and all(seen), f"{len(seen)} cases")

    print("[3] sweep")
    sw, tally = sweep_problems(3000, 20261126)
    check(f"3000 seeded random cases ({tally}): the template equals the reference on every one, and no VALID proposal ever has a floor below the reserve or the Stop SOC request, a "
          "power above the ceiling or the proven level, a duration beyond the window or the time left in it or below the minimum, an energy below 0, a net export above the target or without the START headroom, "
          "a PV surplus the target cannot hold, or a number while it is not VALID, UNVERIFIED or NOT ALLOWED; the start gate (open, closed, unreadable, inconsistent, missing, young) and the leases consumer vary "
          "in every case, and a VALID proposal never has a gate that is not open for 60 s", sw == [] and tally["VALID"] > 300 and tally["INVALID"] > 300 and tally["UNVERIFIED"] > 30 and tally["HOLD"] > 30 and tally["NOT ALLOWED"] > 80, str(sw[:2]) + str(tally))
    sw2, tally2 = sweep_problems(1500, 424242)
    check(f"a second seed, 1500 cases ({tally2})", sw2 == [] and tally2["VALID"] > 100, str(sw2[:2]))

    print("[4] shadow")
    lp = lease_problems()
    check("a lease the schedule started: the comparison and the re-target (no lease, an unreadable flag, the 30 minute age rule at 29:59 and 30:00, the memory of the previous would-change (waits, continues, "
          "is allowed again after 30 minutes, in the future), the four spellings of `this`, a template reload (the memory starts afresh: 1799 s waits, 1800 s allows), the memory's own continuity, "
          "each deviation at its deadband, unreadable lease facts, an end time before now or before the lease start, a proposal that is not VALID (no change listed), a lease that appears to start in the "
          "future, stale telemetry, the comparison's numbers, the UNVERIFIED live-like limits); the full-window, window-limited, late-start and 60 minute manual leases; what makes a lease the schedule's at "
          "every boundary; an END inside the window only; END NOW (the reserve, a hold, never WAIT, nothing unreadable ends anything)", lp == [], str(lp[:3]))
    ttp = time_trust_problems()
    check("the leases consumer and the re-target (slice S-A2): ALLOWED only while binary_sensor.ecco_time_trusted_for_leases has read on for 60 s (60 s exactly allows, 59.9 s does not); off, unavailable, unknown, empty or "
          "missing is WAIT with TIME_NOT_TRUSTED and nothing else, no time to wait for, the would-change not stamped, the changes still listed, the comparison unchanged; named beside LEASE_TOO_YOUNG and MEMORY_YOUNG, whose "
          "wait stays; a re-target with no deviation, an END NOW, an UNKNOWN one and a closed start gate are not moved by it", ttp == [], str(ttp[:3]))
    dp = dst_problems()
    check("the end time of a lease in an hour that happens twice (the clocks go back) or does not exist (they go forward) is not read, never ALLOWED; every five minutes across both nights equals the reference; a "
          "lease across the change ends at the window end", dp == [], str(dp[:3]))
    tp = tail_problems()
    check("THE TAIL OF THE WINDOW and the helpers edited during a lease (the second review's RC1 and RC2): a run pressed 0, 10 and 20 s into its 60 and 240 minute windows rendered at EVERY SECOND from 70 s before the "
          "window end to its own end, up to 20 s after it (the lease gets no time: the proposal INVALID, the re-target UNKNOWN with no change, never ALLOWED to a later END; the next window's proposal is back "
          "when it ends); a lease that ends 100 s after the window end (the window's own end in the window, a duration of 0 minutes and not a negative one after it); the duration and the start helper edited "
          "12 ways (raised, lowered, moved by 1 minute, 3 minutes, half an hour and a day, both): a lease the schedule started keeps its own end as the bound, one that no longer fits the window is UNKNOWN; "
          "a lease the schedule did not start through the window end; a whole run in real time polled every 10 s; and at every one of those renders no proposal ends past the window end plus 20 s or, for "
          "a lease the schedule started, past its own end plus 20 s", tp == [], str(tp[:3]))
    ls = lease_sweep_problems(400, 11)
    check("400 random lease worlds (the flag, what started the lease, the window, the end, the latched values, the hold and the reserve, the memory and its continuity, the previous would-change, the four spellings of "
          "`this`): the comparison, the re-target, the reasons, the changes, the wait, the origin and the memory equal the reference; so does the PROPOSAL of every one of them (state, causes, notes, every number, "
          "the loop's figures, the window end: the bound of a running lease is in them), and no render while a lease runs breaks the property of the window's and the lease's own end", ls == [], str(ls[:3]))
    ls2 = lease_sweep_problems(400, 12, scheduled=True)
    check("400 random leases the SCHEDULE started (a window of 15 to 240 minutes, the start button pressed 0 to 100 s into it, at a random moment of the window, its last minutes or the seconds after its end, "
          "the lease ending as the schedule stages it or 10 minutes, 1 minute, 30 s, 100 s, 120 s or 121 s off, the duration or start helper edited in 11 ways in nearly half of them, the Stop SOC, the target, "
          "the reserve and the memory varied): the proposal, the comparison and the re-target equal the reference at every one, and no render ends past the window end plus 20 s or past the lease's own end "
          "plus 20 s, or lists an END change", ls2 == [], str(ls2[:3]))
    rl = reload_realtime_problems()
    check("in real time: a template reload five minutes after a would-change allows nothing for 30 minutes and then allows it (to the second), whether `this` is a state object with no attributes or none first; a restart "
          "cannot be matched to the scheduled start", rl == [], str(rl[:3]))
    cp = churn_problems()
    check("with no input changing NOTHING is published again, the model included (decision D-C04a, route a: it no longer holds the time of its evaluation; the lab measured 393 rows an hour from it): ten minutes of polls "
          "(sixty), a gate published again thirty times with moving reasons, a lease the schedule started and in line (only the two minute counters move, once a minute)", cp == [], str(cp[:3]))
    zp = size_problems()
    check("the worst-case model attribute (every input missing, every cause named) stays below 6000 bytes", zp == [], str(zp[:2]))

    print("[5] lookups")
    lk = lookups_problems()
    check("a model that is missing, a text, a number, a list or has no attribute makes every lookup withhold everything and say MODEL_UNREADABLE (no age is judged: the model carries none); a readable one is read through "
          "whatever the time in it; every attribute reads its own key of the model; NOT ALLOWED is passed on with its numbers and the gate's codes; `actionable` is true only for the boolean true; the numbers follow the "
          "verdict of the proposal, not the published state; an unknown state or a non-number is never passed on; END NOW is", lk == [], str(lk[:3]))

    print("[6] plan")
    pp = plan_problems()
    check("the REAL plan helper package feeds the coordinator: the reserve is rounded up by it and the floor follows; a Hold battery, Skip tonight and Prepare for power cut each give HOLD with "
          "no number, and cancelling gives VALID again; during a lease the schedule started they each give END NOW (a Prepare for power cut for both causes), and so does a reserve that rises above the latched "
          "Stop SOC with no hold", pp == [], str(pp[:3]))

    gp = gate_problems()
    check("the REAL start gate and the REAL plan package in one world with the coordinator (slice S-A2: the coordinator now READS the real gate): they coexist (no id clash, loop or template error); a gate on for seconds is "
          "NOT ALLOWED with GATE_SETTLING and never actionable, 90 s later VALID and actionable; a Hold battery is a HOLD with the gate's OVERRIDE_ACTIVE beside it and not actionable, and 70 s after it is cancelled VALID again; the "
          "time trust the gate reads going off gives NOT ALLOWED with TIME_LEASES and the numbers kept; an unreadable plan revision gives REVISION_UNREADABLE; a lease the schedule did not start closes the gate (DUMP_ACTIVE) and is "
          "UNKNOWN for the re-target and the comparison; 150 s of stale telemetry (the gate's bound is 300 s, the proposal's 90 s) is INVALID before the gate is asked", gp == [], str(gp[:3]))

    print("[7] vocabulary")
    check("no world made a service call of the coordinator's (the model cannot call anything, and the package has no action)", SERVICE_LOG == [], str(SERVICE_LOG[:2]))

    print("[8] mutation")
    ok_text = battery(TEXT, deep=True)
    check("the full battery holds on the package as written", ok_text == [], str(ok_text[:3]))
    survivors = []
    for label, old, new in MUTANTS:
        try:
            mutated = mutate(TEXT, old, new)
        except AssertionError as exc:
            FAILURES.append(f"mutant anchor: {label}: {exc}")
            print(f"  FAIL  mutant anchor: {label}: {exc}")
            continue
        if not battery(mutated):
            survivors.append(label)
            FAILURES.append(f"mutant survived: {label}")
            print(f"  FAIL  mutant survived: {label}")
    check(f"{len(MUTANTS)} mutants (every range, the freshness, each member of the floor and the staged Stop SOC, its rounding, the margin, the efficiency, the clamps in both directions, the divisor floor, the duration "
          "rounding and window and minimum, the time left in the window at the schedule's own rounding and boundaries, UNVERIFIED, the loop figures, the state ordering, the numbers of a non-VALID state, "
          "the limits, the PV surplus rules, the origin of a lease at each boundary, the comparison, the lease's deadbands and 30 minute rules, the memory and its continuity, END NOW, the lease's end text, "
          "the lookups' availability and readability, a forecast entity, an attribute of an allowed entity (R27, R28), a previous would-change in the future (R01), a service call, a trigger, the pinned names (the charge "
          "gate, the bypass, the export gate and the leases consumer without their domain, a per-clock sensor, the overall sensor, another consumer), the Export start gate (NOT ALLOWED for every verdict, never, with its codes "
          "dropped or replacing the proposal's own, the hold-off at 59, 60, 61 s and not at all, judged by the last update, unreadable, inconsistent, an unknown state, a list that is a text or a mapping, a code cut at "
          "41, uncut or no text), the leases consumer (ignored, counted when not off, not settled, 59, 60 and 61 s, the gate's age, its last update, not named, named outside a wait, a wait that is a time, blocking END NOW or a "
          "re-target with no deviation), the model's time of its evaluation, the memory's pause rule, "
          "a site address, and the bound of a RUNNING lease (RC1, RC2: inside the window only, not used, the window's count first, not clipped at 0, no 20 s, 30 s too many, rounded to the nearest, its own end "
          "ignored, the later end, any lease's end, a minute early, the reason's wording)): all caught (the END rule's own deadband and term are caught by the literal pins alone: no behaviour reaches it)", not survivors and len(MUTANTS) >= 230, str(survivors[:3]))
    harmless = TEXT.replace("# WHAT THIS IS. Item N3", "# WHAT THIS IS, restated. Item N3", 1)
    check("a harmless rewrite (a comment) survives the static battery, and a rewrite of a rule does not", harmless != TEXT and static_problems(harmless) == []
          and bool(battery(TEXT.replace("(pskew | abs) <= 90", "(pskew | abs) <= 190", 1))))

    print("[9] documents")
    stanza = re.search(r"  # Export coordinator - exc1.*?\n  - source: home-assistant/packages/ecco_export_coordinator\.yaml\n    destination: /config/packages/ecco_export_coordinator\.yaml\n    method: ssh_file_copy\n    restart_required: false\n",
                       MANIFEST_TEXT, re.S)
    check("the deployment manifest lists the package with its own stanza (an offline, read-only shadow, nothing installed, the owner's go, no restart, the install cautions), once",
          stanza is not None and MANIFEST_TEXT.count("ecco_export_coordinator.yaml") == 2
          and all(s in flat(re.sub(r"\s*\n\s*#\s*", " ", stanza.group(0))) for s in ("NOT installed", "NOT LIVE-PROVEN", "READ-ONLY", "shadow", "needs the owner's go", "NO Dump to Grid or Free Power lease running",
                                                                                      "armed scheduled Export or charge run", "window end plus 10 minutes", "bounded by the schedule's own window", "NOT ALLOWED", "TIME_NOT_TRUSTED", "D-PIN",
                                                                                      "gets no time past the end of the window it runs in", "END it can only keep or shorten")),
          "" if stanza else "no stanza")
    sec = README_TEXT.split("## Export coordinator", 1)
    rflat = flat(sec[1]) if len(sec) == 2 else ""
    names = ["`sensor.%s`" % e.split(".")[1] for e in X.OWN]
    missing_pins = [s for s in README_PINS if s not in rflat]
    check("the packages README has an Export coordinator section that names the nine sensors, says it is a read-only shadow, nothing installed, that the gate is soft, which two entities of the start gate and "
          "the time trust packages it reads and why (the pinned lists widened deliberately, D-PIN), NOT ALLOWED and its codes, `actionable`, the leases consumer's 60 s, how it relates to the Intelligence advice, "
          "the battery runtime figure and the schedule, the schedule path, the window bound, the origin of a lease, END NOW, the memory (a reload starts it afresh, a restart does not), the model that publishes "
          "nothing with unchanged inputs, the efficiency, the install cautions and the recorder, the edit of the start gate suite, and the owner's decision on the Power Ceiling", len(sec) == 2 and all(n in rflat for n in names)
          and not missing_pins, ("no section" if len(sec) != 2 else f"missing {missing_pins[:4]}"))
    check("the CHANGELOG has the bullet (Export coordinator v0, read-only shadow, nothing installed, the window bound, END NOW)", "Export coordinator v0" in CHANGELOG_TEXT and "ecco_export_coordinator.yaml" in CHANGELOG_TEXT
          and "read-only shadow" in CHANGELOG_TEXT and "bounded by the schedule's own window" in CHANGELOG_TEXT and "END NOW" in CHANGELOG_TEXT and "test_ecco_start_gate.py" in CHANGELOG_TEXT
          and "gets no time past the end of the window it runs in" in CHANGELOG_TEXT and "can only keep the end or shorten it" in CHANGELOG_TEXT
          and all(x in CHANGELOG_TEXT for x in ("NOT ALLOWED", "TIME_NOT_TRUSTED", "D-PIN", "D-C04a", "the leases consumer of the time trust package")))

    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("\nAll export coordinator checks passed.")
    print("These prove the package against a model of Home Assistant's template entities and an independent reference; nothing was installed, nothing was written live, and nothing here binds "
          "the dongle's own Start button or wires the proposal to any start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
