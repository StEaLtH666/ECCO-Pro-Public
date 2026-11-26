"""Offline suite for the EXPORT COORDINATOR v0 (item N3 of the architecture reconciliation):

  home-assistant/packages/ecco_export_coordinator.yaml     nine template sensors and nothing else: a proposal for Export to Grid (the Stop SOC floor, the usable energy, the expected
                                                           battery power, the net export target, the duration, a state with its reasons), the re-target shadow and the shadow comparison

A READ-ONLY SHADOW: no automation, script, helper, trigger, action or service call. This suite proves the REAL package YAML against a model of Home Assistant's template entities
(home-assistant/tests/_export_coordinator_sim.py, on the template model of the time trust suite and the FPS1 interpreter, which it reuses unchanged, plus `this`) and against an
INDEPENDENT reference of the rules written from the specification. Nothing was installed, nothing was written live, and nothing here binds the dongle's own Start button.

  [0] static      the file loads with no repeated key; only `template:`; the nine entities and nothing else; the write vocabulary (no service, action, trigger, helper, script or
                  automation); the exact set of entities it reads, every one of them existing in the repository; NO forecast entity; neither the start gate nor the time trust input is
                  mentioned (both packages pin who may read them); the header states the rules, the constants and the limits and the constants equal the templates'; ASCII, LF, no
                  site value; the site renderer; the eight lookups repeat one identical check; the manifest, README and CHANGELOG say the same
  [1] inputs      every input one at a time (missing, unavailable, unknown, empty, text, nan, infinite, negative, out of range, huge) and at each boundary: always INVALID, the cause named
                  with the entity, every numeric sensor unavailable and never 0; the poll freshness boundaries and the clock-driven re-render; the dongle's limits, the plan hold
  [2] maths       the floor is the maximum of its members (every member in turn, the rounding up of the reserve), the energy (the margin, the efficiency, the measured capacity, never
                  negative), the net export target against the export limit, the expected power (measured PV only, the clamps, the lower floor that keeps the division defined), the
                  duration (rounded down, the schedule window, the minimum worth starting), UNVERIFIED above the proven level; hand-computed anchors; the template against the reference
  [3] sweep       seeded random inputs, thousands of cases: the template equals the reference on every one, and no VALID proposal ever has a floor below the reserve or either Stop SOC
                  request, a power above the ceiling or the proven level, a duration beyond the window or below the minimum, an energy below 0, or a number while it is not VALID or UNVERIFIED
  [4] shadow      while a lease runs: the comparison and the re-target (the 30 minute rules, the deadbands, the memory of the previous would-change, the three spellings of `this`, a
                  clock that moved), against the reference; no template error anywhere
  [5] lookups     the model not updating, the model unreadable: every lookup withholds everything
  [6] plan        the REAL plan helper package feeding the coordinator (a Hold battery, Skip tonight, Prepare for power cut)
  [7] vocabulary  no service call was ever made by any world above
  [8] mutation    in-memory mutants of the package (every comparison, clamp, ordering, default, availability guard and the forecast ban), each caught

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

PIN_LITERALS = True           # a development switch: False shows which mutants only the literal pins kill (the behaviour tests alone must kill them too)
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
DONGLE = X.DONGLE
OWN_IDS = set(X.OWN)
EXPECTED_READS = {X.SOC, X.LOAD, X.PV, X.GRID, X.CAP, X.CAPM, X.HOLD, X.RESERVE, X.STOP_S, X.STOP_D, X.TGT, X.WIN, X.PCEIL, X.PROV, X.MX, X.LIM, X.TEL, X.POLL, X.LEASE,
                  X.L_STOP, X.L_EXP, X.L_CMD, X.L_END, X.MODEL}
FORBIDDEN_FORECAST = re.compile(r"forecast|solcast|predict|pv_tomorrow|estimate|intel_", re.I)
PINNED_NAMES = ("ecco_time_trust", "ecco_charge_start_allowed", "ecco_export_start_allowed", "ecco_start_bypass")   # the packages that pin who may mention them
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_text|input_number|input_boolean|input_datetime|number|script|button|switch|select|automation|light|climate)\.[a-z0-9_]+")
BAD_RAW = (None, "unknown", "unavailable", "", "none", "abc", "nan", "inf", "-inf", "1e999", "-1e999", "1e12", "-5", "True")
CODE_OF = {X.SOC: "SOC_UNREADABLE", X.LOAD: "HOUSE_LOAD_UNREADABLE", X.PV: "PV_UNREADABLE", X.GRID: "GRID_UNREADABLE", X.CAP: "CAPACITY_UNREADABLE",
           X.STOP_S: "STOP_SOC_SCHEDULE_UNREADABLE", X.STOP_D: "STOP_SOC_STAGED_UNREADABLE", X.TGT: "SCHEDULE_POWER_UNREADABLE", X.WIN: "SCHEDULE_DURATION_UNREADABLE",
           X.PCEIL: "CEILING_UNREADABLE", X.PROV: "PROVEN_UNREADABLE", X.MX: "EXPORT_LIMIT_UNREADABLE"}
RANGE_OF = {X.SOC: (0, 100), X.LOAD: (0, 30000), X.PV: (0, 30000), X.GRID: (-30000, 30000), X.CAP: (1, 1000), X.STOP_S: (0, 100), X.STOP_D: (0, 100), X.TGT: (1, 30000),
            X.WIN: (1, 240), X.PCEIL: (500, 30000), X.PROV: (500, 30000), X.MX: (0, 30000)}
CONSTANT_PINS = (("MAX_TELEMETRY_AGE_S = 90", "<= 90"), ("DONGLE_STOP_SOC_MIN = 10", "reserve, 10]"), ("DONGLE_STOP_SOC_MAX = 90", "floor > 90"),
                 ("DISCHARGE_EFFICIENCY = 0.92", "* cap * 0.92"), ("SOC_MARGIN_POINTS = 1", "soc - floor - 1"), ("MIN_COMMAND_W = 500", "[p, 500] | max"),
                 ("EXPORT_HEADROOM", "[100, 0.03 * mx]"), ("MIN_TARGET_W = 500", "net < 500"), ("MIN_DURATION_MIN = 10", "dur < 10"), ("RETARGET_MIN_AGE_S = 1800", "age < 1800"),
                 ("RETARGET_MIN_GAP_S = 1800", "(now_ts - prev_entry) < 1800"), ("RETARGET_STOP_DEADBAND = 1", "(d_stop | abs) >= 1"),
                 ("RETARGET_EXPORT_DEADBAND_W = 200", "(d_exp | abs) >= 200"), ("RETARGET_END_DEADBAND_MIN = 20", "d_end >= 20"), ("PHYSICAL_MAX_W = 30000", "0, 30000)"),
                 ("MODEL_MAX_AGE_S = 180", "age <= 180"))
HEADER_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "READ-ONLY SHADOW", "no automation, no script, no helper", "no service call", "NOTHING READS THESE SENSORS YET",
               "THE HOME ASSISTANT GATES ARE SOFT", "Start button", "A VALID proposal is not permission to start", "THE START GATE AND THE TIME TRUST INPUT ARE NOT READ HERE",
               "READERS allow-list", "no forecast entity is read", "Measured PV only", "never a guess and never 0", "UNAVAILABLE (never 0)", "FLOOR = the largest of", "rounded UP",
               "never below any", "DOWN to the minute", "UNVERIFIED", "supervised-proven", "unresolved control-authority question", "HOLD while", "END of the lease plus a guarded re-START",
               "at most one per", "never writes anything into a running lease", "SHADOW COMPARISON", "FAIL SAFE", "CONSTANTS", "LIMITS, stated plainly", "Recalled from Home Assistant core",
               "NOT verified on a real Home Assistant", "INSTALL", "needs the owner's go", "template.reload", "no restart", "intelligence/dump_advice.py", "limit is a safety CEILING",
               "never the target")


# ===========================================================================================================================
# the worlds and the comparison with the reference
# ===========================================================================================================================
def new_world(text: str | None = None, **kw) -> X.CoordWorld:
    return X.CoordWorld(text, healthy=False, **kw)


def apply_case(w: X.CoordWorld, over: dict | None = None, *, poll_age: "float | None" = 0.0, poll_text: str | None = None, capm: "tuple | None" = None) -> tuple:
    """Set every input (the healthy set with `over` on top; a None removes the entity) and the poll text, render ONCE, and return what the reference needs: (raw readings, poll skew,
    capacity attributes). The skew is Home Assistant's clock minus the time the poll text carries (None when the text is not a time in the firmware's form)."""
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
    SERVICE_LOG.extend(w.w.service_log)
    return raw, skew, capm


def close(a, b) -> bool:
    return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(b))


def compare(w: X.CoordWorld, ref: dict) -> list[str]:
    """Everything the template publishes against the reference; the list of differences."""
    bad: list[str] = []
    st = w.state(X.PROPOSAL)
    if st != ref["state"]:
        bad.append(f"state {st} != {ref['state']}")
    codes = list(w.attr(X.PROPOSAL, "blocked_by") or [])
    if codes != ref["blocked_by"]:
        bad.append(f"blocked_by {codes} != {ref['blocked_by']}")
    notes = [n.split(":")[0].replace("NOTE ", "") for n in (w.attr(X.PROPOSAL, "notes") or []) if n.startswith("NOTE ")]
    if notes != ref["notes"]:
        bad.append(f"notes {notes} != {ref['notes']}")
    exp = {X.P_FLOOR: ref["floor"], X.P_ENERGY: None if ref["energy"] is None else round(ref["energy"], 3), X.P_POWER: None if ref["power"] is None else math.floor(ref["power"]),
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
    for key, e in (("floor_pct", ref["floor"]), ("battery_power_w", None if ref["power"] is None else math.floor(ref["power"])), ("duration_min", ref["duration"]),
                   ("raw_battery_power_w", None if ref["raw_power"] is None else round(ref["raw_power"]))):
        if (m.get(key) is None) != (e is None) or (e is not None and not close(float(m.get(key)), float(e))):
            bad.append(f"model {key} {m.get(key)} != {e}")
    if (w.attr(X.PROPOSAL, "limited_by") or "") != ref["limited_by"]:
        bad.append(f"limited_by {w.attr(X.PROPOSAL, 'limited_by')!r} != {ref['limited_by']!r}")
    if w.errors:
        bad.append(f"template errors {w.errors[:2]}")
    return bad


def run_row(label: str, over: dict | None = None, *, poll_age=0.0, poll_text=None, capm=None, w: X.CoordWorld | None = None, text: str | None = None) -> list[str]:
    w = w or new_world(text)
    raw, skew, cm = apply_case(w, over, poll_age=poll_age, poll_text=poll_text, capm=capm)
    ref = X.reference(raw, poll_skew_s=skew, capacity_attrs=cm)
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
    # the floor: every member in turn, ties, the rounding up, the minimum and the maximum
    for s, d, r in ((50, 30, 40), (30, 50, 40), (30, 30, 62.4), (5, 8, 3), (10, 10, 10), (90, 10, 10), (89.2, 10, 10), (90.2, 10, 10), (10, 10, 91), (10, 10, 90), (33.2, 33.0, 12),
                    (10, 91, 10), (40, 40, 40), (25, 25, 0), (0, 0, 0), (100, 100, 100)):
        add(f"floor from stops {s}/{d} and reserve {r}", {X.STOP_S: str(float(s)), X.STOP_D: str(float(d)), X.RESERVE: str(r)})
    # the SOC against the floor
    for soc in (39, 40, 41, 41.5, 42, 43, 44, 45, 60, 100, 0):
        add(f"soc {soc} with the floor 40", {X.SOC: str(float(soc))})
    for cap in (1, 5, 27.17, 27.18, 30, 100, 1000):
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
    # the duration: the window, the minimum worth starting, rounding down
    for win in (1, 9, 10, 11, 60, 169, 170, 240):
        add(f"window {win}", {X.WIN: str(float(win))})
    for soc in (43, 44, 45, 46, 50, 60, 70, 100):
        for pv in (0, 3500):
            add(f"soc {soc} pv {pv}", {X.SOC: str(float(soc)), X.PV: str(float(pv))})
    # the poll freshness and the forms of the poll text
    for age in (0, 1, 60, 89, 90, 91, 120, 300, 3600, -1, -89, -90, -91, -3600):
        add(f"poll {age} s old", poll_age=age)
    for txt in ("", "unknown", "unavailable", "Waiting", "2026-11-26T17:00:00", "2026-11-26", "2026-11-26 17:00", "17:00:00", "abc", "2026-13-40 99:99:99", "2026-11-26 17:00:00 ",
                "1970-01-01 00:00:00"):
        add(f"poll text {txt!r}", poll_text=txt)
    add("poll missing", poll_age=None)
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
# hand-computed anchors (independent of the reference)
# ===========================================================================================================================
def anchors(text: str | None = None) -> list[str]:
    bad: list[str] = []

    def expect(label: str, over: dict, want_state: str, **nums) -> None:
        w = new_world(text)
        apply_case(w, over)
        got = {"floor": w.state(X.P_FLOOR), "energy": w.state(X.P_ENERGY), "power": w.state(X.P_POWER), "net": w.state(X.P_NET), "duration": w.state(X.P_DUR)}
        if w.state(X.PROPOSAL) != want_state:
            bad.append(f"{label}: state {w.state(X.PROPOSAL)} != {want_state} ({w.attr(X.PROPOSAL, 'blocked_by')})")
        for k, v in nums.items():
            if got[k] != v:
                bad.append(f"{label}: {k} {got[k]} != {v}")
    expect("the healthy evening", {}, "VALID", floor="40", energy="10.764", power="3800", net="3000", duration="169")
    expect("PV carries part of it", {X.PV: "1000.0"}, "VALID", power="2800", duration="230")
    expect("PV covers the target: no battery power, the divisor floor 500 W, the window", {X.PV: "5000.0"}, "VALID", power="0", duration="240")
    expect("a reserve that rises sets the floor", {X.RESERVE: "62.4"}, "VALID", floor="63")
    expect("a higher Stop SOC request wins", {X.STOP_S: "50.0"}, "VALID", floor="50")
    expect("the dongle minimum is the floor", {X.STOP_S: "5.0", X.STOP_D: "8.0", X.RESERVE: "3"}, "VALID", floor="10")
    expect("the export limit is a ceiling for the target", {X.TGT: "3500.0"}, "VALID", net="3400")
    expect("the power ceiling clamps (the proven level equals it: not UNVERIFIED)", {X.LOAD: "3001.0", X.PCEIL: "6000.0", X.PROV: "6000.0"}, "VALID", power="6000")
    expect("above the proven level with a higher ceiling is UNVERIFIED and clamped to the proven level", {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}, "UNVERIFIED",
           power="6000")
    expect("a ceiling below the proven level clamps and stays VALID", {X.LOAD: "3001.0", X.PCEIL: "5000.0", X.PROV: "6000.0"}, "VALID", power="5000")
    expect("the schedule window bounds the duration", {X.WIN: "100.0"}, "VALID", duration="100")
    expect("no energy above the floor", {X.SOC: "41.0"}, "INVALID", floor="unavailable", energy="unavailable", power="unavailable", net="unavailable", duration="unavailable")
    expect("a hold gives no number at all", {X.HOLD: "held"}, "HOLD", floor="unavailable", energy="unavailable", power="unavailable", net="unavailable", duration="unavailable")
    expect("a reserve above the dongle's Stop SOC range", {X.RESERVE: "91"}, "INVALID", floor="unavailable")
    expect("the unconfigured export limit", {X.MX: "0.0"}, "INVALID", net="unavailable")
    w = new_world(text)
    apply_case(w, {X.SOC: "43.0", X.CAP: "27.17", X.LOAD: "0.0"})
    if w.state(X.PROPOSAL) != "INVALID" or "BELOW_MINIMUM_DURATION" not in (w.attr(X.PROPOSAL, "blocked_by") or []):
        bad.append(f"9.99 minutes is below the minimum worth starting: {w.state(X.PROPOSAL)} {w.attr(X.PROPOSAL, 'blocked_by')} {w.state(X.P_DUR)}")
    apply_case(w, {X.SOC: "43.0", X.CAP: "27.18", X.LOAD: "0.0"})
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
    over[X.LOAD] = str(rng.uniform(0, 6000) if easy else rng.uniform(-100, 31000))
    over[X.PV] = str(rng.choice([0.0, rng.uniform(0, 8000)]) if easy else rng.uniform(-100, 31000))
    over[X.GRID] = str(rng.uniform(-6000, 6000) if easy else rng.uniform(-31000, 31000))
    over[X.CAP] = str(rng.uniform(5, 60) if easy else rng.uniform(-1, 1100))
    over[X.RESERVE] = str(rng.choice([rng.uniform(5, 45), float(rng.randint(5, 45))]) if easy else rng.uniform(-5, 105))
    over[X.STOP_S] = str(float(rng.randint(10, 40)) if easy else rng.uniform(-5, 105))
    over[X.STOP_D] = str(float(rng.randint(10, 40)) if easy else rng.uniform(-5, 105))
    over[X.TGT] = str(float(rng.randrange(500, 8100, 100)) if easy else rng.uniform(-1, 31000))
    over[X.WIN] = str(float(rng.randint(1, 240)) if easy else rng.uniform(-1, 250))
    over[X.PCEIL] = str(float(rng.randrange(500, 8100, 100)) if easy else rng.uniform(400, 31000))
    over[X.PROV] = str(float(rng.randrange(3000, 8100, 100)) if easy else rng.uniform(400, 31000))
    over[X.MX] = str(float(rng.randrange(500, 8100, 10)) if easy else rng.uniform(-1, 31000))
    if rng.random() < 0.05:
        over[X.MX] = "0.0"
    over[X.LIM] = "VALID" if (easy or rng.random() < 0.8) else rng.choice(["INVALID", "NOT CONFIGURED", "UNAVAILABLE", "unknown", None])
    over[X.TEL] = "on" if (easy or rng.random() < 0.85) else rng.choice(["off", "unavailable", "unknown", None])
    over[X.HOLD] = "clear" if (easy or rng.random() < 0.8) else rng.choice(["held", "unknown", "unavailable", None, "weird"])
    for eid in list(RANGE_OF) + [X.RESERVE]:
        if rng.random() < (0.015 if easy else 0.06):
            over[eid] = rng.choice(BAD_STATE)
    poll_age: "float | None" = float(rng.choice([0, 5, 30, 89, 90, 91, 200, -50, -95])) if (not easy and rng.random() < 0.3) else 0.0
    poll_text = None
    if rng.random() < 0.02:
        poll_text = rng.choice(["", "unknown", "Waiting", "2026-11-26T17:00:00", "abc"])
    capm = None
    if rng.random() < 0.3:
        capm = (rng.choice([rng.uniform(1, 40), rng.uniform(-5, 2000), "abc", None]), rng.choice(["measured", "measured", "configured", "estimated"]))
    return over, poll_age, poll_text, capm


def property_problems(w: X.CoordWorld, over: dict, capm: "tuple | None" = None) -> list[str]:
    """The properties no case may break, read from what the template published (no reference involved)."""
    bad: list[str] = []
    st = w.state(X.PROPOSAL)
    nums = {eid: w.state(eid) for eid in X.NUMERIC}
    if st in ("VALID", "UNVERIFIED"):
        try:
            floor, energy, power, net, dur = (float(nums[e]) for e in (X.P_FLOOR, X.P_ENERGY, X.P_POWER, X.P_NET, X.P_DUR))
        except ValueError:
            return [f"{st} but a number is not published: {nums}"]
        raw = {**X.HEALTHY, **over}

        def val(eid):
            return X.num(raw.get(eid), -1e18, 1e18)
        floors = [val(X.STOP_S), val(X.STOP_D), val(X.RESERVE), 10.0]
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
        if st == "UNVERIFIED" and not (float(w.attr(X.PROPOSAL, "raw_battery_power_w")) > val(X.PROV) and val(X.PCEIL) > val(X.PROV)):
            bad.append("UNVERIFIED without a requirement above the proven level and a ceiling above it")
        # the exact rational minutes: the published duration is the exact value rounded DOWN (never up), from the readings and the published floor and net export
        cap = Fraction(raw[X.CAP].strip())
        if capm is not None and capm[1] == "measured" and X.num(capm[0], 1, 1000) is not None:
            cap = min(cap, Fraction(str(capm[0])))
        load, pv = Fraction(raw[X.LOAD].strip()), Fraction(raw[X.PV].strip())
        p_exact = max(min(max(Fraction(net) + load - pv, 0), Fraction(min(val(X.PCEIL), val(X.PROV)))), 500)
        e_exact = max(Fraction(raw[X.SOC].strip()) - Fraction(floor) - 1, 0) / 100 * cap * Fraction(92, 100)
        d_exact = min(e_exact * 1000 / p_exact * 60, Fraction(val(X.WIN)))
        if dur > d_exact + Fraction(1, 10 ** 9) or dur < d_exact - 1 - Fraction(1, 10 ** 9):
            bad.append(f"the duration {dur} is not the exact {float(d_exact):.9f} minutes rounded down")
    else:
        if any(v != "unavailable" for v in nums.values()):
            bad.append(f"{st} but a numeric sensor reads {nums}")
        if st not in ("INVALID", "HOLD"):
            bad.append(f"the state {st} is not one of VALID, INVALID, UNVERIFIED, HOLD")
        if not w.attr(X.PROPOSAL, "blocked_by"):
            bad.append(f"{st} with no blocking cause named")
        if st == "HOLD" and "OVERRIDE_ACTIVE" not in w.attr(X.PROPOSAL, "blocked_by"):
            bad.append("HOLD without OVERRIDE_ACTIVE")
    return bad


def sweep_problems(n: int, seed: int, text: str | None = None, first_only: bool = False, properties: bool = True) -> tuple[list[str], dict]:
    rng = random.Random(seed)
    w = new_world(text)
    bad: list[str] = []
    tally = {"VALID": 0, "INVALID": 0, "UNVERIFIED": 0, "HOLD": 0}
    for i in range(n):
        over, age, ptext, capm = random_case(rng)
        raw, skew, cm = apply_case(w, over, poll_age=age, poll_text=ptext, capm=capm)
        ref = X.reference(raw, poll_skew_s=skew, capacity_attrs=cm)
        tally[ref["state"]] += 1
        bad += [f"case {i} {over}: {b}" for b in compare(w, ref)]
        if properties:
            bad += [f"case {i}: {b}" for b in property_problems(w, over, capm)]
        if bad and first_only:
            return bad, tally
    return bad, tally


# ===========================================================================================================================
# [4] the lease: the comparison and the re-target
# ===========================================================================================================================
def lease_world(text: str | None = None, this_mode: str = "ha", over: dict | None = None) -> X.CoordWorld:
    w = new_world(text, this_mode=this_mode)
    w.make_healthy(over)
    w.start_feed()
    return w


def lease_state(w: X.CoordWorld) -> dict:
    s = w.snapshot()
    rt, cm = s[X.RETARGET], s[X.COMPARE]
    return {"rt": rt[0], "reasons": rt[1].get("reasons"), "changes": rt[1].get("changes"), "wait": rt[1].get("wait_until_ts"), "cmp": cm[0], "cmp_attrs": cm[1], "last": rt[1].get("last_would_change_ts"),
            "proposal": s[X.PROPOSAL][0]}


def reasons_have(st: dict, code: str) -> bool:
    return any(r.startswith(code + ":") for r in (st["reasons"] or []))


def lease_problems(text: str | None = None, first_only: bool = False) -> list[str]:
    bad: list[str] = []

    def expect(label: str, cond: bool, detail: str = "") -> None:
        if not cond:
            bad.append(f"{label}: {detail}")

    # no lease
    w = lease_world(text)
    st = lease_state(w)
    expect("no lease", st["rt"] == "NOT RUNNING" and st["cmp"] == "NOT RUNNING", str(st["rt"]) + str(st["cmp"]))
    for bad_flag in ("unavailable", "unknown", None, "weird"):
        w.bulk({X.LEASE: bad_flag})
        st = lease_state(w)
        expect(f"lease flag {bad_flag!r}", st["rt"] == "UNKNOWN" and st["cmp"] == "UNKNOWN" and reasons_have(st, "LEASE_UNREADABLE"), str(st["rt"]))
    # the baseline lease: the proposal is floor 40, net 3000, power 3800, end now + 169 min
    w = lease_world(text)
    w.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=10)
    w.advance(60)
    st = lease_state(w)
    expect("a young lease with a deviation waits", st["rt"] == "WAIT" and reasons_have(st, "LEASE_TOO_YOUNG") and st["cmp"] == "DIFFERS", str(st["rt"]))
    expect("the wait ends 30 minutes after the lease start", st["wait"] is not None and abs(st["wait"] - (w.w.changed_at[X.LEASE] + 1800)) < 1, str(st["wait"]))
    expect("what it would change is named", any(c.startswith("STOP_SOC 30.0 -> 40") for c in st["changes"]) and any(c.startswith("END ") for c in st["changes"]), str(st["changes"]))
    expect("no export change below the deadband", not any(c.startswith("EXPORT_TARGET") for c in st["changes"]), str(st["changes"]))
    w.age(X.LEASE, 1799)
    st = lease_state(w)
    expect("29 min 59 s old still waits", st["rt"] == "WAIT", st["rt"])
    w.age(X.LEASE, 1800)
    st = lease_state(w)
    expect("30 min old is allowed", st["rt"] == "ALLOWED" and not st["reasons"] and st["last"] == w.now_ts(), f"{st['rt']} {st['last']}")
    entry = st["last"]
    w.advance(60)
    st = lease_state(w)
    expect("an episode continues while the deviation stands", st["rt"] == "ALLOWED" and st["last"] == entry, f"{st['rt']} {st['last']}")
    # in line: the latched values equal the proposal; the lease's end later than the energy needs is no deviation
    w.bulk({X.L_STOP: "40.0", X.L_EXP: "3000.0", X.L_END: w.local_text(w.now_ts() + 400 * 60)})
    st = lease_state(w)
    expect("in line (the lease outlasting the energy needs no change)", st["rt"] == "NO CHANGE" and st["cmp"] == "IN LINE", f"{st['rt']} {st['cmp']}")
    w.bulk({X.L_STOP: "30.0"})
    st = lease_state(w)
    expect("a deviation within 30 minutes of the previous would-change waits", st["rt"] == "WAIT" and reasons_have(st, "RECENT_CHANGE") and abs(st["wait"] - (entry + 1800)) < 1,
           f"{st['rt']} {st['reasons']} {st['wait']}")
    for offset, want in ((900, "WAIT"), (1799, "WAIT"), (1800, "ALLOWED")):
        w.w.run_until(entry + offset)
        w.force()
        st = lease_state(w)
        expect(f"{offset} s after the previous would-change", st["rt"] == want and (want == "ALLOWED" or reasons_have(st, "RECENT_CHANGE")), f"{st['rt']} {st['reasons']} want {want}")
    expect("and the second would-change is stamped", lease_state(w)["last"] == entry + 1800, str(lease_state(w)["last"]))
    # the three spellings of `this`
    for mode in ("none", "undefined"):
        w2 = lease_world(text, this_mode=mode)
        w2.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=40)
        w2.advance(60)
        st = lease_state(w2)
        expect(f"`this` is {mode}: never ALLOWED, and it says why", st["rt"] == "WAIT" and reasons_have(st, "MEMORY_UNAVAILABLE") and not w2.errors, f"{st['rt']} {w2.errors[:2]}")
    # each deviation alone, at its deadband
    base = {"stop": 40.0, "export": 3000.0}
    def case(label: str, stop, export, end_min, want: str, **kw):
        w3 = lease_world(text)
        w3.lease_on(stop=stop, export=export, command=3800, ends_in_min=end_min, age_min=45)
        w3.advance(0)
        s3 = lease_state(w3)
        expect(label, s3["rt"] == want and not w3.errors, f"{s3['rt']} want {want} {s3['reasons']} {s3['changes']} {w3.errors[:2]}")
    case("everything in line", 40, 3000, 169, "NO CHANGE")
    case("the Stop SOC 1 point lower", 39, 3000, 169, "ALLOWED")
    case("the Stop SOC 1 point higher", 41, 3000, 169, "ALLOWED")
    case("the Stop SOC 0.5 points off is no deviation", 40.5, 3000, 169, "NO CHANGE")
    case("the target export 200 W off", 40, 2800, 169, "ALLOWED")
    case("the target export 200 W the other way", 40, 3200, 169, "ALLOWED")
    case("the target export 100 W off is no deviation", 40, 2900, 169, "NO CHANGE")
    case("the energy lasts 20 minutes beyond the lease", 40, 3000, 149, "ALLOWED")
    case("the energy lasts 19 minutes beyond the lease", 40, 3000, 150, "NO CHANGE")
    case("the lease outlasting the energy by an hour is no deviation", 40, 3000, 229, "NO CHANGE")
    # the lease facts that cannot be read
    for label, over_l in (("the latched Stop SOC", {X.L_STOP: "unknown"}), ("the latched target", {X.L_EXP: "unavailable"}), ("the end time", {X.L_END: "Active - end time unavailable"}),
                          ("the end time text", {X.L_END: "soon"}), ("the end time missing", {X.L_END: None}), ("a negative latched Stop SOC", {X.L_STOP: "-5"})):
        w4 = lease_world(text)
        w4.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=45)
        w4.bulk(over_l)
        s4 = lease_state(w4)
        expect(f"{label} cannot be read", s4["rt"] == "UNKNOWN" and s4["cmp"] == "UNKNOWN" and reasons_have(s4, "LEASE_FACTS_UNREADABLE"), f"{s4['rt']} {s4['reasons']}")
    # a proposal that is not VALID gives nothing to change to
    for label, over_p, want in (("INVALID", {X.SOC: "unknown"}, "INVALID"), ("HOLD", {X.HOLD: "held"}, "HOLD"), ("UNVERIFIED", {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"}, "UNVERIFIED")):
        w5 = lease_world(text)
        w5.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=45)
        w5.bulk(over_p)
        s5 = lease_state(w5)
        expect(f"a {label} proposal", s5["rt"] == "UNKNOWN" and s5["proposal"] == want and reasons_have(s5, "PROPOSAL_NOT_VALID"), f"{s5['rt']} {s5['proposal']} {s5['reasons']}")
    # a clock that moved: the lease appears to have started in the future
    w6 = lease_world(text)
    w6.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=0)
    w6.w.changed_at[X.LEASE] = w6.now_ts() + 600
    w6.force()
    s6 = lease_state(w6)
    expect("a lease started in the future", s6["rt"] == "WAIT" and reasons_have(s6, "CLOCK_BACKWARDS"), f"{s6['rt']} {s6['reasons']}")
    # stale telemetry during a lease: nothing is allowed
    w7 = lease_world(text)
    w7.lease_on(stop=30, export=3000, command=3500, ends_in_min=60, age_min=45)
    w7.stop_feed()
    w7.advance(5 * 60)
    s7 = lease_state(w7)
    expect("the telemetry stops: the proposal is INVALID and no change is allowed", s7["proposal"] == "INVALID" and s7["rt"] == "UNKNOWN", f"{s7['proposal']} {s7['rt']}")
    # the comparison's numbers
    w8 = lease_world(text)
    w8.lease_on(stop=30, export=2800, command=3500, ends_in_min=60, age_min=45)
    w8.advance(0)
    ca = lease_state(w8)["cmp_attrs"]
    expect("the comparison shows both sides and the signed differences", ca.get("stop_soc_proposed") == 40 and ca.get("stop_soc_lease") == 30.0 and ca.get("stop_soc_difference") == 10.0
           and ca.get("export_w_proposed") == 3000 and ca.get("export_w_lease") == 2800.0 and ca.get("export_w_difference") == 200.0 and ca.get("battery_w_proposed") == 3800
           and ca.get("battery_w_commanded") == 3500.0 and ca.get("battery_w_difference") == 300.0 and ca.get("end_difference_min") == 109.0, str(ca))
    expect("no template error in any lease world", not (w.errors or w8.errors or w7.errors or w6.errors), str(w.errors[:2]))
    return bad


def lease_sweep_problems(n: int, seed: int, text: str | None = None, first_only: bool = False) -> list[str]:
    """Random lease facts and ages against the reference, in fresh worlds. The lease facts are set with ONE render, then the lease flag is aged (a second render): the second render's
    previous state is the first render's, which is what the reference is given."""
    rng = random.Random(seed)
    bad: list[str] = []
    for i in range(n):
        mode = rng.choice(["ha", "ha", "ha", "none", "undefined"])
        soc = float(rng.randint(41, 100))
        w = lease_world(text, this_mode=mode, over={X.SOC: str(soc)})
        flag = rng.choice(["on", "on", "on", "off", "unavailable", "unknown", None])
        stop = rng.choice([30.0, 39.0, 40.0, 41.0, 40.5, "unknown", 55.0, "-5"])
        export = rng.choice([3000.0, 2800.0, 2900.0, 3200.0, 3100.0, "unavailable", 1000.0])
        cmd = rng.choice([3500.0, 3800.0, 0.0, "unknown"])
        end_min = rng.choice([60, 100, 148, 149, 150, 169, 170, 229, 400, None])
        age_s = rng.choice([0, 300, 1739, 1740, 1799, 1800, 1801, 3600, 5400])
        w.bulk({X.LEASE: flag, X.L_STOP: str(stop), X.L_EXP: str(export), X.L_CMD: str(cmd),
                X.L_END: "Inactive" if end_min is None else w.local_text(w.now_ts() + end_min * 60)})
        prev = dict(w.model())
        w.age(X.LEASE, float(age_s))
        got = lease_state(w)
        raw = {**X.HEALTHY, X.SOC: str(soc)}
        ref_p = X.reference(raw, poll_skew_s=0.0)
        end_ts = None if end_min is None else float(int(w.now_ts() + end_min * 60))
        l_start = w.w.changed_at.get(X.LEASE) if X.LEASE in w.w.states else None
        ref = X.reference_lease(ref_p, lease=("unknown" if flag is None else flag), l_stop=X.num(str(stop), 0, 100), l_exp=X.num(str(export), 0, 30000), l_cmd=X.num(str(cmd), 0, 30000),
                                l_end_ts=end_ts, l_start_ts=l_start, now_ts=w.now_ts(), prev_state=prev.get("rt_state"), prev_entry=prev.get("rt_entry"), mem_ok=(mode == "ha"))
        m = w.model()
        if got["rt"] != ref["rt_state"] or got["cmp"] != ref["cmp_state"] or m.get("rt_entry") != ref["rt_entry"]:
            bad.append(f"lease case {i} ({mode} {flag} {stop} {export} end {end_min} age {age_s}): rt {got['rt']} cmp {got['cmp']} entry {m.get('rt_entry')} != {ref['rt_state']} {ref['cmp_state']} {ref['rt_entry']}")
        for key, want in (("stop_soc_difference", ref["d_stop"]), ("export_w_difference", ref["d_exp"]), ("battery_w_difference", ref["d_bat"]), ("end_difference_min", ref["d_end"])):
            have = m.get(key)
            if (have is None) != (want is None) or (want is not None and abs(have - want) > 0.06):
                bad.append(f"lease case {i}: {key} {have} != {want}")
        if w.errors:
            bad.append(f"lease case {i}: template errors {w.errors[:2]}")
        SERVICE_LOG.extend(w.w.service_log)
        if bad and first_only:
            return bad
    return bad


# ===========================================================================================================================
# [5] the lookups: the model not updating
# ===========================================================================================================================
def lookup_text(text: str | None = None) -> str:
    """The package without the model entity: the lookups then read a model the suite writes (a plain state with a dict attribute)."""
    d = yaml.safe_load(text if text is not None else TEXT)
    d["template"][0]["sensor"] = [e for e in d["template"][0]["sensor"] if e["name"] != "ECCO Export Coordinator Model"]
    return yaml.safe_dump(d, sort_keys=False, width=10 ** 6)


def lookups_problems(text: str | None = None) -> list[str]:
    bad: list[str] = []
    w = X.CoordWorld(lookup_text(text), healthy=False)
    good = {"state": "VALID", "reasons": ["VALID: a proposal from measured values"], "blocked_by": [], "notes": [], "floor_pct": 40, "energy_kwh": 10.764, "battery_power_w": 3800,
            "net_export_w": 3000, "duration_min": 169, "raw_battery_power_w": 3800, "limited_by": "", "end_ts": 1, "cmp_state": "IN LINE", "rt_state": "NO CHANGE", "rt_reasons": [],
            "rt_changes": [], "rt_entry": None, "rt_wait_until_ts": None, "lease_age_min": None, "stop_soc_proposed": 40, "stop_soc_lease": 40.0, "stop_soc_difference": 0.0,
            "export_w_proposed": 3000, "export_w_lease": 3000.0, "export_w_difference": 0.0, "battery_w_proposed": 3800, "battery_w_commanded": 3800.0, "battery_w_difference": 0.0,
            "end_proposed_ts": 1, "end_lease_ts": 1, "end_difference_min": 0.0}

    def put_model(offset: float | None, **kw):
        m = dict(good)
        m.update(kw)
        if offset is not None:
            m["evaluated_ts"] = round(w.now_ts() - offset)
        w.put(X.MODEL, "model", {"model": m})
        w.force()

    def numbers_available() -> list[str]:
        return [eid for eid in X.NUMERIC if w.state(eid) != "unavailable"]
    put_model(0)
    if w.state(X.PROPOSAL) != "VALID" or len(numbers_available()) != 5 or w.state(X.RETARGET) != "NO CHANGE" or w.state(X.COMPARE) != "IN LINE":
        bad.append(f"a fresh model is read through: {w.snapshot()}")
    for off in (180, 100, 0, -5):
        put_model(off)
        if w.state(X.PROPOSAL) != "VALID" or len(numbers_available()) != 5:
            bad.append(f"a model {off} s old is still fresh")
    for off in (181, 1000, -6, -3600):
        put_model(off)
        if w.state(X.PROPOSAL) != "INVALID" or numbers_available() or w.state(X.RETARGET) != "UNKNOWN" or w.state(X.COMPARE) != "UNKNOWN" \
                or w.attr(X.PROPOSAL, "blocked_by") != ["MODEL_NOT_UPDATING"] or w.attr(X.PROPOSAL, "end_ts") is not None or any(w.attr(X.COMPARE, a) is not None for a in ("stop_soc_proposed", "end_lease_ts")):
            bad.append(f"a model {off} s old is withheld: {w.snapshot()}")
    # a model that cannot be read at all
    for label, put in (("missing", lambda: w.put(X.MODEL, None)), ("a text", lambda: w.put(X.MODEL, "model", {"model": "nonsense"})), ("no evaluation time", lambda: w.put(X.MODEL, "model", {"model": {"state": "VALID", "floor_pct": 40}})),
                       ("a text evaluation time", lambda: w.put(X.MODEL, "model", {"model": {"state": "VALID", "floor_pct": 40, "evaluated_ts": "now"}}))):
        put()
        w.force()
        if w.state(X.PROPOSAL) != "INVALID" or numbers_available() or w.state(X.RETARGET) != "UNKNOWN" or w.state(X.COMPARE) != "UNKNOWN":
            bad.append(f"a model that is {label} is withheld: {w.snapshot()}")
    # a state the lookups do not know is not passed on; a number that is not a number is unavailable
    put_model(0, state="VALID!")
    if w.state(X.PROPOSAL) != "INVALID":
        bad.append("an unknown state is passed on")
    put_model(0, state="INVALID")
    if numbers_available():
        bad.append("numbers are published for an INVALID model")
    put_model(0, state="HOLD")
    if numbers_available():
        bad.append("numbers are published for a HOLD model")
    put_model(0, floor_pct=None, energy_kwh="x", battery_power_w=float("inf") if False else None)
    if w.state(X.P_FLOOR) != "unavailable" or w.state(X.P_ENERGY) != "unavailable" or w.state(X.P_POWER) != "unavailable":
        bad.append("a number that is not a number is published")
    put_model(0, rt_state="ALLOWED!", cmp_state="MAYBE")
    if w.state(X.RETARGET) != "UNKNOWN" or w.state(X.COMPARE) != "UNKNOWN":
        bad.append("an unknown re-target or comparison state is passed on")
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
            tw.put(eid, st)
    feed = tw.feed(X.POLL, period=10.0)
    w.run_until(w.t + 30)
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
    feed["on"] = False
    if tw.errors:
        bad.append(f"template errors {tw.errors[:2]}")
    if PL.PlanWorld.rejected_all:
        bad.append(f"a helper refused a write: {PL.PlanWorld.rejected_all[:2]}")
    SERVICE_LOG.extend(c for c in w.service_log if c[1] not in ("input_number.set_value", "input_datetime.set_datetime", "input_text.set_value", "persistent_notification.create",
                                                                 "persistent_notification.dismiss"))
    return bad


def gate_problems(text: str | None = None) -> list[str]:
    """The REAL start gate and the REAL plan helper package in one world with the coordinator: the package reads neither the gate nor time trust (their suites pin who may read them), so a
    consumer must itself require BOTH the gate and a VALID proposal. This proves the two coexist (no id clash, no loop, no template error) and that the AND is what a consumer needs: each case
    below has a VALID proposal that the gate refuses, or the reverse."""
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
        if eid not in (X.HOLD, X.RESERVE, X.LEASE, X.TEL, X.STOP_D):
            tw.put(eid, st)

    def both() -> tuple:
        gw.sync()
        tw.force()
        gate = gw.state(G.EXPORT_GATE)
        prop = tw.state(X.PROPOSAL)
        return gate, prop, gate == "on" and prop == "VALID"
    if both() != ("on", "VALID", True):
        bad.append(f"healthy: gate, proposal, consumer {both()} {gw.attr(G.EXPORT_GATE, 'blocked_by')} {tw.attr(X.PROPOSAL, 'blocked_by')}")
    pw.run_script("ecco_plan_override_start", {"kind": "hold_battery", "expiry_min": 120})
    if both() != ("off", "HOLD", False):
        bad.append(f"a Hold battery: {both()}")
    pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
    if both() != ("on", "VALID", True):
        bad.append(f"a cancelled Hold battery: {both()}")
    gw.put(G.TL, "off")
    if both() != ("off", "VALID", False) or "TIME_LEASES" not in gw.attr(G.EXPORT_GATE, "blocked_by"):
        bad.append(f"the time trust the gate reads is off, the proposal (which does not read it) stays VALID, the consumer's AND refuses: {both()}")
    gw.put(G.TL, "on")
    w.set("input_number.ecco_plan_revision", "unavailable")
    if both() != ("off", "VALID", False) or gw.attr(G.EXPORT_GATE, "blocked_by") != ["REVISION_UNREADABLE"]:
        bad.append(f"an unreadable plan revision closes the gate and not the proposal: {both()}")
    w.set("input_number.ecco_plan_revision", "7.0")
    gw.d.dump_start(latched=40.0)
    gw.sync()
    tw.put(X.L_EXP, "3000.0")
    tw.put(X.L_CMD, "3500.0")
    tw.put(X.L_END, tw.local_text(w.t + w.clock_offset + 3600))
    tw.force()
    if both() != ("off", "VALID", False) or "DUMP_ACTIVE" not in gw.attr(G.EXPORT_GATE, "blocked_by") or tw.state(X.RETARGET) not in ("WAIT", "NO CHANGE", "ALLOWED") \
            or tw.state(X.COMPARE) not in ("IN LINE", "DIFFERS"):
        bad.append(f"a lease is running: the gate is closed (DUMP_ACTIVE) while the coordinator keeps proposing and compares: {both()} {tw.state(X.RETARGET)} {tw.state(X.COMPARE)}")
    gw.d.dump_end()
    gw.sync()
    gw.stop_poll()
    gw.advance(150)
    gw.sync()
    tw.force()
    if gw.state(G.EXPORT_GATE) != "on" or tw.state(X.PROPOSAL) != "INVALID" or tw.attr(X.PROPOSAL, "blocked_by") != ["TELEMETRY_STALE"]:
        bad.append(f"150 s after the last poll the gate (300 s bound) still allows and the proposal (90 s bound) is INVALID: {gw.state(G.EXPORT_GATE)} {tw.state(X.PROPOSAL)} {tw.attr(X.PROPOSAL, 'blocked_by')}")
    if tw.errors or gw.tw.errors:
        bad.append(f"template errors {tw.errors[:2]} {gw.tw.errors[:2]}")
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
    for eid in sorted(set(ENTITY_RE.findall(text))):
        if FORBIDDEN_FORECAST.search(eid):
            bad.append(f"a forecast or estimate entity id appears: {eid}")
    for name in PINNED_NAMES:
        if name in text:
            bad.append(f"it mentions {name!r}: the package that pins who may mention it would fail")
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
    # the eight lookups repeat one identical check
    check_prefix = ("{%- set m = state_attr('sensor.ecco_export_coordinator_model', 'model') -%} {%- set age = (as_timestamp(now()) - m.get('evaluated_ts')) if (m is mapping and "
                    "m.get('evaluated_ts') is number) else none -%} {%- set ok = age is not none and age >= -5 and age <= 180 -%}")
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
                bad.append(f"{e['name']} {k} does not start with the shared four-line check")
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
        bad += sweep_problems(120 if not deep else 400, 20261126, text, first_only=True)[0]
        if bad:
            return bad
        bad += lease_problems(text, first_only=True)
        if bad:
            return bad
        bad += lease_sweep_problems(40 if not deep else 150, 7, text, first_only=True)
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
    ("the floor ignores the effective reserve", "[stop_s, stop_d, reserve, 10] | max", "[stop_s, stop_d, 10] | max"),
    ("the floor ignores the staged Stop SOC", "[stop_s, stop_d, reserve, 10] | max", "[stop_s, reserve, 10] | max"),
    ("the floor ignores the schedule's Stop SOC", "[stop_s, stop_d, reserve, 10] | max", "[stop_d, reserve, 10] | max"),
    ("the floor ignores the dongle minimum", "[stop_s, stop_d, reserve, 10] | max", "[stop_s, stop_d, reserve] | max"),
    ("the floor is the minimum, not the maximum", "[stop_s, stop_d, reserve, 10] | max | round(0, 'ceil')", "[stop_s, stop_d, reserve, 10] | min | round(0, 'ceil')"),
    ("the floor is rounded down", "| max | round(0, 'ceil')) if (stop_s", "| max | round(0, 'floor')) if (stop_s"),
    ("a floor of 91 is allowed", "floor is not none and floor > 90", "floor is not none and floor > 91"),
    ("the SOC margin is dropped", "([soc - floor - 1, 0] | max)", "([soc - floor, 0] | max)"),
    ("the efficiency is 0.95", "* cap * 0.92", "* cap * 0.95"),
    ("the efficiency is dropped", "* cap * 0.92", "* cap"),
    ("the energy uses the larger capacity", "([cap_c, cap_m] | min)", "([cap_c, cap_m] | max)"),
    ("the export headroom is 1 %", "[100, 0.03 * mx]", "[100, 0.01 * mx]"),
    ("the export headroom ignores the 100 W minimum", "[100, 0.03 * mx]", "[0, 0.03 * mx]"),
    ("the target limit rounds up", "| round(0, 'floor')) * 100) if (mx", "| round(0, 'ceil')) * 100) if (mx"),
    ("the target ignores the export limit", "([tgt, nmax] | min)", "tgt"),
    ("the target is the larger of the two", "([tgt, nmax] | min)", "([tgt, nmax] | max)"),
    ("a target below 500 W is allowed", "net is not none and net < 500", "net is not none and net < 400"),
    ("the load is subtracted", "(net + load - pv)", "(net - load - pv)"),
    ("the PV is added", "(net + load - pv)", "(net + load + pv)"),
    ("the PV is ignored", "(net + load - pv)", "(net + load)"),
    ("the power has no lower clamp", "[[raw_p, 0] | max, hi] | min", "[raw_p, hi] | min"),
    ("the power has no upper clamp", "[[raw_p, 0] | max, hi] | min", "[raw_p, 0] | max"),
    ("the power ignores the proven level", "([pceil, prov] | min)", "pceil"),
    ("the power ignores the ceiling", "([pceil, prov] | min)", "prov"),
    ("the divisor floor is dropped", "([p, 500] | max)", "p"),
    ("the divisor floor is 100 W", "([p, 500] | max)", "([p, 100] | max)"),
    ("the duration is rounded to the nearest", "([dur_raw, win] | min) | round(0, 'floor')", "([dur_raw, win] | min) | round(0)"),
    ("the duration ignores the schedule window", "([dur_raw, win] | min)", "dur_raw"),
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
    ("the start gate is mentioned", "# INSTALL (needs the owner's go", "# see binary_sensor.ecco_export_start_allowed\n# INSTALL (needs the owner's go"),
    ("a site address appears", "# INSTALL (needs the owner's go", "# " + ".".join(("192", "168", "1", "20")) + "\n# INSTALL (needs the owner's go"),
    ("the lease is left alone for 10 minutes only", "age < 1800 or recent", "age < 600 or recent"),
    ("the gap between would-changes is 10 minutes", "(now_ts - prev_entry) < 1800", "(now_ts - prev_entry) < 600"),
    ("a continuing episode counts as recent", "prev_entry is not none and not cont and", "prev_entry is not none and"),
    ("the Stop SOC deadband is 2 points", "(d_stop | abs) >= 1", "(d_stop | abs) >= 2"),
    ("a lower floor is no deviation", "(d_stop | abs) >= 1", "d_stop >= 1"),
    ("the export deadband is exclusive", "(d_exp | abs) >= 200", "(d_exp | abs) > 200"),
    ("the end deadband is 40 minutes", "d_end >= 20", "d_end >= 40"),
    ("a lease outlasting the energy is a deviation", "d_end is not none and d_end >= 20", "d_end is not none and (d_end | abs) >= 20"),
    ("the missing memory is ignored", "age < 1800 or recent or not mem_ok", "age < 1800 or recent"),
    ("the re-target needs no VALID proposal", "verdict != 'VALID' or not complete", "verdict == 'HOLD' or not complete"),
    ("a lease with unreadable facts is compared", "{%- set complete = num and l_stop is not none and l_exp is not none and l_end_ts is not none -%}", "{%- set complete = num -%}"),
    ("the model's age bound is 1800 s in a lookup", "{%- set ok = age is not none and age >= -5 and age <= 180 -%}\n          {{ m.get('state') if", "{%- set ok = age is not none and age >= -5 and age <= 1800 -%}\n          {{ m.get('state') if"),
    ("a lookup accepts a model from the future", "{%- set ok = age is not none and age >= -5 and age <= 180 -%}\n          {{ ok and m.get('state') in ['VALID', 'UNVERIFIED'] and m.get('floor_pct') is number }}",
     "{%- set ok = age is not none and age <= 180 -%}\n          {{ ok and m.get('state') in ['VALID', 'UNVERIFIED'] and m.get('floor_pct') is number }}"),
    ("a numeric lookup ignores the state", "{{ ok and m.get('state') in ['VALID', 'UNVERIFIED'] and m.get('duration_min') is number }}", "{{ ok and m.get('duration_min') is number }}"),
    ("the proposal state is passed on whatever it is", "{{ m.get('state') if (ok and m.get('state') in ['VALID', 'INVALID', 'UNVERIFIED', 'HOLD']) else 'INVALID' }}", "{{ m.get('state') if ok else 'INVALID' }}"),
]


def mutate(text: str, old: str, new: str) -> str:
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"a mutant anchor must occur exactly once, found {n}x: {old[:70]!r}")
    return text.replace(old, new)


# ===========================================================================================================================
# run
# ===========================================================================================================================
def main() -> None:
    print("[0] static")
    sp = static_problems(TEXT)
    check("the file loads with no repeated key; only `template:`; the nine entities and nothing else; no service call, action, trigger, helper, script or automation; it reads exactly the "
          "expected entities and every one exists in the repository; no forecast entity; neither pinned package is mentioned; the header states the rules, the constants (equal to the "
          "templates') and the limits; ASCII, LF, no site value; the eight lookups share one check", sp == [], str(sp[:3]))
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
          bool(static_problems(TEXT.replace("READ-ONLY SHADOW", "READ-ONLY NOTE", 1))) and bool(static_problems(TEXT.replace("NOTHING READS THESE SENSORS YET", "SOMETHING READS", 1)))
          and bool(static_problems(TEXT.replace("DISCHARGE_EFFICIENCY = 0.92", "DISCHARGE_EFFICIENCY = 0.95", 1))) and bool(static_problems(TEXT.replace("* cap * 0.92", "* cap * 0.93", 1))))

    print("[1] inputs")
    bp = boundary_problems()
    check(f"{len(ROWS)} rows (every input one at a time at its limits, beyond them and unreadable; the hold, the limits state, the telemetry flag, the floor members, the SOC against the floor, "
          "the capacity, the target against the export limit, the load and PV against the clamps, the window, the poll freshness and the forms of the poll text): the template equals the "
          "independent reference on every one (state, causes in order, notes, every number, every numeric sensor unavailable and never 0 unless VALID or UNVERIFIED)", bp == [], str(bp[:3]))
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
    check("every numeric input, read as missing, unavailable, unknown, empty, text, nan, infinite or huge, makes the proposal INVALID with its own cause named and no number published", ok_codes)
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
    am = anchors()
    check("hand-computed anchors: the healthy evening is floor 40 %, 10.764 kWh, 3800 W, net 3000 W, 169 min; PV, the reserve rounding up, the Stop SOC requests, the dongle minimum, the "
          "export limit as a ceiling, the clamps, UNVERIFIED, the window, no energy, a hold, the 10 minute minimum on both sides", am == [], str(am[:3]))

    print("[2] maths")
    wm = new_world()
    ok_order = True
    for s, d, r in ((20, 35, 50), (20, 50, 35), (35, 20, 50), (35, 50, 20), (50, 20, 35), (50, 35, 20)):
        apply_case(wm, {X.STOP_S: str(float(s)), X.STOP_D: str(float(d)), X.RESERVE: str(r)})
        if wm.state(X.P_FLOOR) != "50":
            ok_order = False
            print(f"      floor from stops {s}/{d} and reserve {r} is {wm.state(X.P_FLOOR)}, not 50")
    apply_case(wm, {X.STOP_S: "5.0", X.STOP_D: "8.0", X.RESERVE: "3"})
    ok_order = ok_order and wm.state(X.P_FLOOR) == "10"
    apply_case(wm, {X.STOP_S: "33.2", X.STOP_D: "12.0", X.RESERVE: "12"})
    ok_order = ok_order and wm.state(X.P_FLOOR) == "34"
    check("the floor is the maximum of the schedule's Stop SOC, the staged Stop SOC, the effective reserve and the dongle minimum, whatever their order, and is rounded UP (33.2 gives 34, "
          "a reserve of 62.4 gives 63): never below any of them", ok_order)
    apply_case(wm, {})
    base_power = float(wm.state(X.P_POWER))
    apply_case(wm, {X.PV: "500.0"})
    less = float(wm.state(X.P_POWER))
    wm.put("sensor.solcast_pv_forecast_today", "99999")
    wm.put("sensor.ecco_intel_pv_tomorrow", "99999")
    wm.put("sensor.ecco_intel_dump_to_grid", "99999", {"advice": {"stop_soc_pct": 99, "export_kwh": 99}})
    wm.force()
    check("the power follows MEASURED PV exactly (500 W of PV is 500 W less battery power) and no forecast or advice entity changes anything, even a huge one",
          base_power - less == 500.0 and float(wm.state(X.P_POWER)) == less and wm.state(X.PROPOSAL) == "VALID", f"{base_power} {less} {wm.state(X.P_POWER)}")
    apply_case(wm, {X.PV: "99999.0"})
    check("an implausible PV reading is INVALID, never a huge credit that justifies an export", wm.state(X.PROPOSAL) == "INVALID" and "PV_UNREADABLE" in wm.attr(X.PROPOSAL, "blocked_by"))
    apply_case(wm, {X.PV: "5000.0"})
    check("PV that covers the whole target gives a power of 0 (the lower clamp), a duration worked out at the dongle's 500 W floor (no division by zero), and says so in a note",
          wm.state(X.P_POWER) == "0" and wm.state(X.PROPOSAL) == "VALID" and any(n.startswith("NOTE LOW_BATTERY_POWER") for n in wm.attr(X.PROPOSAL, "notes")), str(wm.attr(X.PROPOSAL, "notes")))
    apply_case(wm, {X.LOAD: "3001.0", X.PCEIL: "8000.0", X.PROV: "6000.0"})
    check("above the proven level the power is clamped to it and the state is UNVERIFIED, with the reason; the numbers are still published (clamped) and the raw requirement is shown",
          wm.state(X.PROPOSAL) == "UNVERIFIED" and wm.state(X.P_POWER) == "6000" and wm.attr(X.PROPOSAL, "raw_battery_power_w") == 6001 and wm.attr(X.PROPOSAL, "limited_by") == "PROVEN_LEVEL"
          and any(n.startswith("UNVERIFIED ABOVE_PROVEN_LEVEL") for n in wm.attr(X.PROPOSAL, "notes")), f"{wm.state(X.PROPOSAL)} {wm.state(X.P_POWER)} {wm.attr(X.PROPOSAL, 'notes')}")
    sink = []
    for soc in range(41, 101):
        apply_case(wm, {X.SOC: str(float(soc))})
        if wm.state(X.PROPOSAL) == "VALID":
            ex = max(soc - 40 - 1, 0) / 100 * 30.0 * 0.92 * 1000 / 3800 * 60
            sink.append(float(wm.state(X.P_DUR)) == min(int(ex), 240))
    check("the duration is the exact minutes rounded DOWN, bounded by the schedule window, over every SOC from 41 to 100", sink and all(sink), f"{len(sink)} cases")
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
          e_meas == "8.97" and e_big == e_cfg == "10.764", f"{e_meas} {e_big} {e_cfg}")

    print("[3] sweep")
    sw, tally = sweep_problems(3000, 20261126)
    check(f"3000 seeded random cases ({tally}): the template equals the reference on every one, and no VALID proposal ever has a floor below the reserve or either Stop SOC request, a "
          "power above the ceiling or the proven level, a duration beyond the window or below the minimum, an energy below 0, a net export above the target or without the START headroom, "
          "or a number while it is not VALID or UNVERIFIED", sw == [] and tally["VALID"] > 300 and tally["INVALID"] > 300 and tally["UNVERIFIED"] > 30 and tally["HOLD"] > 30, str(sw[:2]) + str(tally))
    sw2, tally2 = sweep_problems(1500, 424242)
    check(f"a second seed, 1500 cases ({tally2})", sw2 == [] and tally2["VALID"] > 100, str(sw2[:2]))

    print("[4] shadow")
    lp = lease_problems()
    check("the comparison and the re-target while a lease runs: no lease, an unreadable flag, the 30 minute age rule at 29:59 and 30:00, the memory of the previous would-change (waits, "
          "continues, is allowed again after 30 minutes), `this` unavailable or none (never ALLOWED, says why, no error), each deviation at its deadband, unreadable lease facts, a proposal that "
          "is not VALID, a lease that appears to start in the future, stale telemetry, the comparison's numbers", lp == [], str(lp[:3]))
    ls = lease_sweep_problems(400, 11)
    check("400 random lease worlds (flag, latched values, end, age, the three spellings of `this`): the comparison and the re-target equal the reference, twice (the second render has the first "
          "as its previous state)", ls == [], str(ls[:3]))

    print("[5] lookups")
    lk = lookups_problems()
    check("a model that is not updating (older than 180 s, 6 s in the future), unreadable or malformed makes every lookup withhold everything; a fresh one is read through; an unknown state "
          "or a non-number is never passed on", lk == [], str(lk[:3]))

    print("[6] plan")
    pp = plan_problems()
    check("the REAL plan helper package feeds the coordinator: the reserve is rounded up by it and the floor follows; a Hold battery, Skip tonight and Prepare for power cut each give HOLD with "
          "no number, and cancelling gives VALID again", pp == [], str(pp[:3]))

    gp = gate_problems()
    check("the REAL start gate and the REAL plan package in one world with the coordinator: they coexist (no id clash, loop or template error); the proposal does not read the gate or time trust, so "
          "each case with a VALID proposal that the gate refuses (a Hold battery is both; the time trust, the plan revision, a running lease) or the reverse (150 s of stale telemetry: the gate's "
          "bound is 300 s, the proposal's 90 s) is one the consumer's AND must handle", gp == [], str(gp[:3]))

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
    check(f"{len(MUTANTS)} mutants (every range, the freshness, each member of the floor, its rounding, the margin, the efficiency, the clamps in both directions, the divisor floor, the duration "
          "rounding and window and minimum, UNVERIFIED, the state ordering, the numbers of a non-VALID state, the limits, the lease's deadbands and 30 minute rules, the memory, the lookups' "
          "age bound and availability, a forecast entity, a service call, a trigger, the pinned names, a site address): all caught", not survivors and len(MUTANTS) >= 40, str(survivors[:3]))
    harmless = TEXT.replace("# WHAT THIS IS. Item N3", "# WHAT THIS IS, restated. Item N3", 1)
    check("a harmless rewrite (a comment) survives the static battery, and a rewrite of a rule does not", harmless != TEXT and static_problems(harmless) == []
          and bool(battery(TEXT.replace("(pskew | abs) <= 90", "(pskew | abs) <= 190", 1))))

    print("[9] documents")
    stanza = re.search(r"  # Export coordinator - exc1.*?\n  - source: home-assistant/packages/ecco_export_coordinator\.yaml\n    destination: /config/packages/ecco_export_coordinator\.yaml\n    method: ssh_file_copy\n    restart_required: false\n",
                       MANIFEST_TEXT, re.S)
    check("the deployment manifest lists the package with its own stanza (an offline, read-only shadow, nothing installed, the owner's go, no restart), once",
          stanza is not None and MANIFEST_TEXT.count("ecco_export_coordinator.yaml") == 2 and all(s in stanza.group(0) for s in ("NOT installed", "NOT LIVE-PROVEN", "READ-ONLY", "shadow", "needs the owner's go")),
          "" if stanza else "no stanza")
    sec = README_TEXT.split("## Export coordinator", 1)
    rflat = flat(sec[1]) if len(sec) == 2 else ""
    names = ["`sensor.%s`" % e.split(".")[1] for e in X.OWN]
    check("the packages README has an Export coordinator section that names the nine sensors, says it is a read-only shadow, nothing installed, that the gate is soft, that the start gate and the "
          "time trust input are not read and why, and how it relates to the Intelligence advice and the schedule", len(sec) == 2 and all(n in rflat for n in names)
          and all(s in rflat for s in ("READ-ONLY SHADOW", "NOTHING INSTALLED", "soft", "does not read the start gate", "time trust", "pinned", "Intelligence", "schedule", "DISCHARGE_EFFICIENCY",
                                       "UNVERIFIED", "the END of the lease plus a guarded re-START", "exc1", "NOT ESTABLISHED")), "" if len(sec) == 2 else "no section")
    check("the CHANGELOG has the bullet (Export coordinator v0, read-only shadow, nothing installed)", "Export coordinator v0" in CHANGELOG_TEXT and "ecco_export_coordinator.yaml" in CHANGELOG_TEXT
          and "read-only shadow" in CHANGELOG_TEXT)

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
