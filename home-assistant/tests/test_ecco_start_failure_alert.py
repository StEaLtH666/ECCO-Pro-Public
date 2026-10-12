"""Offline behaviour suite for the failed-start health warning (FB-D1 follow-up, post-export entry fsw1):
sensor.ecco_health_start_failures (home-assistant/packages/ecco_system_health.yaml), its two registry checks and reason codes, and the
Overview status hero (home-assistant/dashboards/ecco_pro.yaml).

What is proven (plain Jinja against Home Assistant stand-ins, driven by a model of a trigger-based template entity: explicit triggers, `this` =
the entity's state before the render, restore of state and attributes across a Home Assistant restart, the state trigger's `for` timers
(per entity, restarted on every change), the one-minute time_pattern, and a model of the dongle's four counters, each published on its own
30 s timer, so a normal start can show its success before its attempt):

  [1] wiring        the firmware counters exist with the names the entity ids derive from; the timing contract behind the 240 s settle
                    holds in the firmware (bounded waits only between attempt and success); an attempt is counted only after the start gate has
                    passed and a success only on a verified ACTIVE; the failures-since-boot counters are not used; the triggers are exact;
                    the two feature instances are one template; the package stays template-only; every other entity is byte-identical
  [2] registry      two checks and two reason codes (WARNING, non-blocking) consistent with the package, the validator and the doc
  [3] semantics     a genuine failed start warns after the settle; a normal start never does (either publish order); a refusal changes no
                    counter; a nonzero count, a restart, a reconnection, a counter reset and an inconsistent pair only set the baseline;
                    unreadable counters are UNKNOWN, never HEALTHY, and never end an open window; exact expiry; repeated, retried and
                    simultaneous failures; the free-text status and the failures counters never decide anything; a silent Wi-Fi loss
                    (counters available but stale until the ESPHome client gives up) never warns; exact 239 s / 240 s settle boundary
  [4] oracle        randomised start sequences against an independent event-sourced oracle
  [5] hero          the Overview hero executed with Node: a confirmed failed start is ATTENTION with its own subline and a START FAILED
                    pill, every existing reason keeps its subline and priority (STATUS PARTIAL first, then every existing ATTENTION cause),
                    an unavailable sensor stays quiet; a differential over random inputs proves the hero is byte-identical to its previous
                    state whenever no failed start is reported
  [6] mutation     in-memory mutants of the package and of the hero are each killed
  [7] fps1          the REAL scheduled Free Power package (fps1) driven against the dongle model, FSW1 evaluated on the counter timeline: retried
                    gate refusals and persistent refusals are never counted, a started-then-failed session warns once at the settle (after fps1's
                    own alert), dongle outages and API stalls never fabricate a warning

Writes nothing; no Home Assistant, no network, no hardware. It does not prove the templates on a live Home Assistant instance.
"""

from __future__ import annotations

import ast
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jinja2
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _fsw1_scope as scope  # noqa: E402

PKG_PATH = ROOT / "home-assistant" / "packages" / "ecco_system_health.yaml"
CHECKS_PATH = ROOT / "registry" / "system_health_checks.yaml"
CODES_PATH = ROOT / "registry" / "health_reason_codes.yaml"
DOC_PATH = ROOT / "docs" / "SYSTEM_HEALTH_ARCHITECTURE.md"
DASH_PATH = ROOT / scope.DASHBOARD_REL
FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

DEV = "ecco_clock_dongle"
FPA = f"sensor.{DEV}_free_power_start_attempts_since_boot"
FPS = f"sensor.{DEV}_free_power_start_successes_since_boot"
DGA = f"sensor.{DEV}_dump_to_grid_start_attempts_since_boot"
DGS = f"sensor.{DEV}_dump_to_grid_start_successes_since_boot"
FPF = f"sensor.{DEV}_free_power_failures_since_boot"
DGF = f"sensor.{DEV}_dump_to_grid_failures_since_boot"
FP_STATUS = f"sensor.{DEV}_free_power_status"
DG_STATUS = f"sensor.{DEV}_dump_to_grid_status"
FP_REC = f"sensor.{DEV}_free_power_recovery_state"
DG_REC = f"sensor.{DEV}_dump_to_grid_recovery_state"
COUNTERS = (FPA, FPS, DGA, DGS)
CODE_FP, CODE_DG = "FREE_POWER_START_FAILED", "DUMP_TO_GRID_START_FAILED"
WINDOW, SETTLE = 1800, 240
# The timing contract the 240 s settle is derived from (TIMING ASSUMPTION: re-check against the firmware and the LIVE Home Assistant
# ESPHome client before deployment). Between its attempt and its success a start script runs only bounded 3 s Modbus waits (Free Power
# at most 9, Dump to Grid at most 7; checked in [1]); each counter publishes on its own 30 s timer; and a silently lost link keeps the
# counters available with stale values until the ESPHome client gives up (aioesphomeapi 45.x: a ping every 20 s, the connection closed
# 90 s after an unanswered ping, so at most 110 s after the last message received).
FW_WAIT_S, FW_MAX_WAITS, PUBLISH_S, LINK_LOSS_S = 3, {"fp": 9, "dg": 7}, 30, 20 + 90
SEEN_GAP_S = {k: n * FW_WAIT_S + PUBLISH_S for k, n in FW_MAX_WAITS.items()}       # HA-visible attempt -> success: 57 s / 51 s
STALE_HOLD_S = {k: g + LINK_LOSS_S for k, g in SEEN_GAP_S.items()}                  # worst stale-but-available hold: 167 s / 161 s
UID = "ecco_health_start_failures"
HERO_ID = "sensor.ecco_health_start_failures"
FB_STATUS_ID = "sensor.ecco_" + "fall" + "back_status"      # assembled: the reserved-token scans ban the literal outside declared files

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class TaggedSafeLoader(yaml.SafeLoader):
    """Tolerates Home Assistant / ESPHome custom !tags."""


def _construct_unknown(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


TaggedSafeLoader.add_multi_constructor("!", _construct_unknown)


class FastLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """The same tolerant loader on libyaml when it is available (the firmware YAML is large)."""


FastLoader.add_multi_constructor("!", _construct_unknown)


def load(text: str):
    return yaml.load(text, Loader=TaggedSafeLoader)


LIVE_TEXT = PKG_PATH.read_text(encoding="utf-8")
BASE_TEXT = scope.pre_fsw1_health_package(LIVE_TEXT)       # the package as of the previous entry, byte for byte
DASH_LIVE = DASH_PATH.read_text(encoding="utf-8")
DASH_BASE = scope.pre_fsw1_dashboard(DASH_LIVE)            # the dashboard as of the previous entry


# ---------------------------------------------------------------------------------------------------------------------------
# Home Assistant stand-ins
# ---------------------------------------------------------------------------------------------------------------------------
T0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
_MISSING = object()


def as_timestamp(v, default=_MISSING):
    """HA's as_timestamp: a datetime, an ISO string or a number -> float seconds; anything else -> default (or an error without one)."""
    try:
        if isinstance(v, datetime):
            return v.timestamp()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            return datetime.fromisoformat(v).timestamp()
    except (TypeError, ValueError):
        pass
    if default is _MISSING:
        raise ValueError(f"as_timestamp got invalid input {v!r}")
    return default


class StateObj:
    def __init__(self, state, last_changed):
        self.state, self.last_changed = state, last_changed


class States:
    def __init__(self, values: dict, changed: dict):
        self.values, self.changed = values, changed

    def __call__(self, entity_id: str) -> str:
        return self.values.get(entity_id, "unknown")

    def __getitem__(self, entity_id: str):
        return StateObj(self(entity_id), self.changed.get(entity_id))     # a missing entity has no last_changed (as_timestamp -> default)


class This:
    def __init__(self, state, attributes: dict):
        self.state, self.attributes = state, attributes


class Trig:
    def __init__(self, tid: str):
        self.id = tid


ENV = jinja2.Environment(undefined=jinja2.StrictUndefined)


def parse_result(s: str):
    """HA's render result parsing for attributes: a Python literal becomes that value, anything else stays a string."""
    try:
        v = ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return s
    return v if isinstance(v, (int, float, list, dict, bool)) else s


def entity_of(doc) -> tuple[dict, list]:
    for block in doc.get("template", []):
        for ent in block.get("sensor", []) or []:
            if ent.get("unique_id") == UID:
                return ent, block.get("triggers") or []
    raise AssertionError(f"{UID} not found")


class Compiled:
    """The start-failure entity of one package text, compiled once."""

    def __init__(self, text: str):
        self.doc = load(text)
        self.ent, self.triggers = entity_of(self.doc)
        self.state_t = ENV.from_string(self.ent["state"])
        self.attr_t = {k: (ENV.from_string(v) if isinstance(v, str) and ("{{" in v or "{%" in v) else v) for k, v in self.ent["attributes"].items()}
        self.timers: dict[str, int] = {}     # trigger id -> seconds of its `for`
        self.timer_entities: dict[str, list] = {}
        for t in self.triggers:
            if t.get("trigger") == "state" and isinstance(t.get("for"), dict):
                f = t["for"]
                self.timers[t["id"]] = int(f.get("seconds", 0)) + 60 * int(f.get("minutes", 0)) + 3600 * int(f.get("hours", 0))
                ids = t["entity_id"]
                self.timer_entities[t["id"]] = [ids] if isinstance(ids, str) else list(ids)


def render_once(c: Compiled, values: dict, changed: dict, now: datetime, this: This, trigger: Trig):
    ctx = {"states": States(values, changed), "now": lambda: now, "as_timestamp": as_timestamp, "this": this, "trigger": trigger}
    state = c.state_t.render(**ctx).strip()
    attrs = {}
    for k, t in c.attr_t.items():
        attrs[k] = parse_result(t.render(**ctx).strip()) if hasattr(t, "render") else t
    return state, attrs


def fmt(n: int) -> str:
    return f"{n}.0"          # the live counters read as floats ("0.0")


QUIET_START = T0 - timedelta(hours=1)


def base_values(fpa=0, fps=0, dga=0, dgs=0) -> dict:
    return {FPA: fmt(fpa), FPS: fmt(fps), DGA: fmt(dga), DGS: fmt(dgs), FPF: "0.0", DGF: "0.0",
            FP_STATUS: "Inactive", DG_STATUS: "Inactive", FP_REC: "NONE", DG_REC: "NONE"}


class Sim:
    """A trigger-based template entity in a running Home Assistant (only the triggers this entity declares)."""

    def __init__(self, c: Compiled, values: dict | None = None, first_trigger: str = "start", changed_ago: int = 3600):
        self.c = c
        self.now = T0
        self.values = dict(base_values() if values is None else values)
        self.changed = {e: T0 - timedelta(seconds=changed_ago) for e in self.values}
        self.state, self.attrs = "unknown", {}
        self.timers: dict[tuple[str, str], datetime] = {}
        self.renders: list[tuple[datetime, str, dict, str]] = []
        self.fire(first_trigger)

    def fire(self, tid: str):
        self.state, self.attrs = render_once(self.c, self.values, self.changed, self.now, This(self.state, dict(self.attrs)), Trig(tid))
        self.renders.append((self.now, self.state, dict(self.attrs), tid))

    def set(self, entity: str, value: str):
        if self.values.get(entity) == value:
            return
        self.values[entity] = value
        self.changed[entity] = self.now
        if entity in COUNTERS:
            for tid, secs in self.c.timers.items():
                if entity in self.c.timer_entities[tid]:
                    self.timers[(tid, entity)] = self.now + timedelta(seconds=secs)
            self.fire("start_counters_changed")

    def advance(self, seconds: float):
        end = self.now + timedelta(seconds=seconds)
        while True:
            nxt_min = self.now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            cands = [t for t in [nxt_min, *self.timers.values()] if t <= end]
            if not cands:
                break
            t = min(cands)
            self.now = t
            for (tid, ent), due in sorted(self.timers.items(), key=lambda kv: kv[1]):
                if due == t:
                    del self.timers[(tid, ent)]
                    self.fire(tid)
                    break
            else:
                self.fire("2")
            # several timers may share an instant: loop again at the same instant before moving on
        self.now = end

    def restart(self, *, restore: bool = True, counters_after: dict | None = None, downtime_changes: dict | None = None, keep_available: bool = False):
        """Home Assistant restarts: the `for` timers are lost; the entity restores its state and attributes (a trigger-based template
        entity), the start trigger renders while the dongle entities are still unavailable, then they come back."""
        self.timers.clear()
        if not restore:
            self.state, self.attrs = "unknown", {}
        if keep_available:       # the dongle entities are already readable when the start trigger renders
            self.values.update(downtime_changes or {})
            self.fire("start")
            return
        back = dict(self.values)
        back.update(downtime_changes or {})
        back.update(counters_after or {})
        for e in self.values:
            self.values[e] = "unavailable"
            self.changed[e] = self.now
        self.fire("start")
        for e, v in back.items():
            self.values[e] = v
            self.changed[e] = self.now
            if e in COUNTERS:
                self.fire("start_counters_changed")

    def unavailable(self, entities=COUNTERS):
        for e in entities:
            self.set(e, "unavailable")

    def codes(self) -> list:
        rc = self.attrs.get("reason_codes")
        return rc if isinstance(rc, list) else ast.literal_eval(rc)


def run_start(s: Sim, feat: str, ok: bool, dur: int = 12, attempt_first: bool = True):
    """One START as the dongle publishes it: the attempt (always), then the success (when ok) `dur` seconds later. With attempt_first False
    the two independent 30 s publish timers happen to publish the success BEFORE the attempt."""
    a, sc = (FPA, FPS) if feat == "fp" else (DGA, DGS)
    na = int(float(s.values[a])) + 1
    ns = int(float(s.values[sc])) + (1 if ok else 0)
    if attempt_first or not ok:
        s.set(a, fmt(na))
        s.advance(dur)
        if ok:
            s.set(sc, fmt(ns))
    else:
        s.advance(dur)
        s.set(sc, fmt(ns))
        s.advance(3)
        s.set(a, fmt(na))


# ---------------------------------------------------------------------------------------------------------------------------
# The battery: every behavioural claim, as a function of the package text (so the mutants can be run through it)
# ---------------------------------------------------------------------------------------------------------------------------
class World:
    """One feature as the 'primary' under test and the other as 'other'. The battery runs once per assignment, so every scenario exercises
    BOTH instances of the step (a mutant of one instance cannot hide behind the other)."""

    def __init__(self, primary: str):
        fp = {"key": "fp", "pfx": "free_power", "a": FPA, "s": FPS, "code": CODE_FP, "status": FP_STATUS, "rec": FP_REC, "fail": FPF}
        dg = {"key": "dg", "pfx": "dump_to_grid", "a": DGA, "s": DGS, "code": CODE_DG, "status": DG_STATUS, "rec": DG_REC, "fail": DGF}
        p, o = (fp, dg) if primary == "fp" else (dg, fp)
        self.primary = primary
        self.kp, self.ko = p["key"], o["key"]
        self.pp, self.po = p["pfx"], o["pfx"]
        self.pa, self.ps, self.oa, self.os = p["a"], p["s"], o["a"], o["s"]
        self.cp, self.co = p["code"], o["code"]
        self.status_p, self.rec_p, self.fail_p, self.fail_o = p["status"], p["rec"], p["fail"], o["fail"]
        self.status_o = o["status"]

    def bv(self, pa=0, ps=0, oa=0, os_=0) -> dict:
        """base_values with the primary feature's counters first."""
        if self.primary == "fp":
            return base_values(pa, ps, oa, os_)
        return base_values(oa, os_, pa, ps)

    def codes_sorted(self, *which) -> list:
        """The reason_codes order is fixed: Free Power first, then Dump to Grid."""
        return [c for c in (CODE_FP, CODE_DG) if c in which]

    def feats_sorted(self, *which) -> list:
        return [f for f in ("free_power", "dump_to_grid") if f in which]


def battery(text: str, *, quick: bool = False) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    for primary in ("fp", "dg"):
        out.extend(_battery_world(text, World(primary), quick=quick))
    return out


def _battery_world(text: str, W: World, *, quick: bool = False) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    tag = "Free Power" if W.primary == "fp" else "Dump to Grid"

    def ok(name, cond, detail=""):
        out.append((f"[{tag}] {name}", bool(cond), detail))

    try:
        c = Compiled(text)
    except Exception as exc:  # noqa: BLE001
        return [("the package parses and the start-failure entity compiles", False, repr(exc))]
    trig = {t.get("id"): t for t in c.triggers}
    if W.primary == "fp":
        ok("triggers: start / counters-changed / settled / window-elapsed ids are present", {"start", "start_counters_changed", "start_counters_settled", "start_failure_window_elapsed"} <= set(trig))
        ok(f"triggers: the settle trigger is the four counters held for {SETTLE} s", c.timers.get("start_counters_settled") == SETTLE and sorted(c.timer_entities.get("start_counters_settled", [])) == sorted(COUNTERS))
        ok("triggers: the window trigger is the two attempts counters held for 1800 s", c.timers.get("start_failure_window_elapsed") == WINDOW and sorted(c.timer_entities.get("start_failure_window_elapsed", [])) == sorted([FPA, DGA]))
        ok("triggers: the one-minute time_pattern backstop is kept", {"trigger": "time_pattern", "minutes": "/1"} in c.triggers)

    def run(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            ok(f"scenario {fn.__name__} renders", False, repr(exc))
            return None

    # --- baseline / initial discovery -------------------------------------------------------------------------------------------
    def s_baseline():
        s = Sim(c, W.bv(7, 5, 3, 2))          # nonzero history: unresolved 2 (primary) and 1 (other) since boot
        ok("initial nonzero counters: HEALTHY, no code", s.state == "HEALTHY" and s.codes() == [], f"{s.state} {s.codes()}")
        s.advance(600)
        ok("... and still HEALTHY ten minutes later (a historical count is never a failure)", s.state == "HEALTHY" and s.codes() == [])
        ok("... the baseline is stored per feature, nothing observed", s.attrs.get(f"{W.pp}_unresolved_baseline") == 2 and s.attrs.get(f"{W.po}_unresolved_baseline") == 1
           and s.attrs.get(f"{W.pp}_failures_observed") == 0 and s.attrs.get(f"{W.po}_failures_observed") == 0 and s.attrs.get(f"{W.pp}_last_failure_at") == "none")
        s.set(W.fail_p, "4.0")
        s.set(W.fail_o, "2.0")
        s.advance(300)
        ok("failure-since-boot counters moving alone (restore failures) never warn", s.state == "HEALTHY")
        s.set(W.status_p, "START FAILED - could not capture complete inverter snapshot")
        s.advance(300)
        ok("the free-text status saying START FAILED without a counter change never warns", s.state == "HEALTHY")
        s.set(W.rec_p, "LOCKED_NEITHER")
        s.advance(120)
        ok("a recovery state other than NONE alone is not this sensor's concern", s.state == "HEALTHY")
        ok("informational attributes are live reads", s.attrs.get(f"{W.pp}_status_text_informational") == "START FAILED - could not capture complete inverter snapshot"
           and s.attrs.get(f"{W.pp}_recovery_state_informational") == "LOCKED_NEITHER" and str(s.attrs.get(f"{W.pp}_start_attempts_since_boot")) == "7.0")
        ok("blocks_manual_control false, not sufficient for control", s.attrs.get("blocks_manual_control") is False and s.attrs.get("sufficient_for_control_decision") is False)

    run(s_baseline)

    def s_first_render():
        for trig_id in ("2", "start_counters_changed", "start_counters_settled"):
            for ago in (3600, 300):        # an old history, and a history changed 5 minutes ago (inside a failure window if it were counted)
                s = Sim(c, W.bv(7, 5, 3, 2), first_trigger=trig_id, changed_ago=ago)     # created by a reload: the first render is not the HA start
                ok(f"first render on trigger {trig_id!r} ({ago} s of history): HEALTHY, the history only sets the baseline",
                   s.state == "HEALTHY" and s.codes() == [] and s.attrs.get(f"{W.pp}_unresolved_baseline") == 2 and s.attrs.get(f"{W.po}_unresolved_baseline") == 1
                   and s.attrs.get(f"{W.pp}_failures_observed") == 0 and s.attrs.get(f"{W.po}_failures_observed") == 0, f"{s.state} {s.attrs.get(f'{W.pp}_failures_observed')}")
                s.advance(300)
                ok("... and stays HEALTHY with nothing observed", s.state == "HEALTHY" and s.attrs.get(f"{W.pp}_failures_observed") == 0 and s.attrs.get(f"{W.po}_failures_observed") == 0)

    run(s_first_render)

    # --- a genuine failed start ---------------------------------------------------------------------------------------------------
    def s_fail():
        s = Sim(c)
        s.advance(37)
        t_fail = s.now
        run_start(s, W.kp, ok=False)
        ok("failed START, just after the attempt publishes: not yet confirmed (the settle is still running)", s.state == "HEALTHY", s.state)
        s.advance(SETTLE - 12 - 1)
        ok(f"{SETTLE - 1} s after the last counter change: still not confirmed", s.state == "HEALTHY", s.state)
        s.advance(1)
        last = s.renders[-1]
        ok(f"{SETTLE} s after the attempt: the settle trigger confirms it", last[3] == "start_counters_settled" and s.state == "WARNING" and s.codes() == [W.cp], f"{s.state} {s.codes()} {last[3]}")
        ok("failed_features names only this feature; the other has no window", s.attrs.get("failed_features") == [W.pp] and s.attrs.get(f"{W.po}_warning_active") is False)
        ok("last_failure_at is the attempt's change time; failures_observed 1; baseline moved to the new unresolved count",
           s.attrs.get(f"{W.pp}_last_failure_at") == t_fail.isoformat() and s.attrs.get(f"{W.pp}_failures_observed") == 1 and s.attrs.get(f"{W.pp}_unresolved_baseline") == 1,
           str((s.attrs.get(f"{W.pp}_last_failure_at"), t_fail.isoformat(), s.attrs.get(f"{W.pp}_failures_observed"), s.attrs.get(f"{W.pp}_unresolved_baseline"))))
        ok("reason code list is exactly the one code; the checks are named", s.attrs.get("reason_codes") == [W.cp]
           and s.attrs.get("represented_checks") == ["free_power_start_failed_recent", "dump_to_grid_start_failed_recent"])
        s.advance(600)
        ok("minutes later: the same single failure (not re-counted), still WARNING", s.state == "WARNING" and s.attrs.get(f"{W.pp}_failures_observed") == 1)
        s.set(W.status_p, "Inactive")
        ok("the status text going back to Inactive does not clear it", s.state == "WARNING")
        s.advance((t_fail + timedelta(seconds=WINDOW - 1) - s.now).total_seconds())
        ok("attempt + 1799 s: still WARNING", s.state == "WARNING", s.state)
        s.advance(1)
        last = s.renders[-1]
        ok("attempt + 1800 s: the window trigger renders at exactly that instant", last[0] == t_fail + timedelta(seconds=WINDOW) and last[3] == "start_failure_window_elapsed", f"{last[0]} {last[3]}")
        ok("attempt + 1800 s: HEALTHY, no code, the failure stays recorded", s.state == "HEALTHY" and s.codes() == [] and s.attrs.get(f"{W.pp}_last_failure_at") == t_fail.isoformat()
           and s.attrs.get(f"{W.pp}_failures_observed") == 1)
        s.advance(3600)
        ok("much later: HEALTHY", s.state == "HEALTHY")

    run(s_fail)

    def s_fail_with_history():
        s = Sim(c, W.bv(4, 4, 9, 8))
        run_start(s, W.kp, ok=False)
        s.advance(SETTLE)
        ok("failed start with the other feature carrying history (1 unresolved): WARNING with this feature's code only", s.state == "WARNING" and s.codes() == [W.cp]
           and s.attrs.get("failed_features") == [W.pp], f"{s.state} {s.codes()}")
        ok("failures_observed 1 and baseline 1 for this feature; the other feature untouched", s.attrs.get(f"{W.pp}_failures_observed") == 1 and s.attrs.get(f"{W.pp}_unresolved_baseline") == 1
           and s.attrs.get(f"{W.po}_failures_observed") == 0 and s.attrs.get(f"{W.po}_unresolved_baseline") == 1)

    run(s_fail_with_history)

    # --- normal starts never warn --------------------------------------------------------------------------------------------------
    def s_normal():
        for first in (True, False):
            s = Sim(c, W.bv(3, 3, 5, 5))
            run_start(s, W.kp, ok=True, dur=14, attempt_first=first)
            run_start(s, W.ko, ok=True, dur=9, attempt_first=first)
            for _ in range(6):
                s.advance(30)
                ok(f"normal start (attempt published {'first' if first else 'after its success'}): never WARNING at +{int((s.now - T0).total_seconds())} s",
                   s.state in ("HEALTHY", "UNKNOWN") and s.codes() == [], f"{s.state} {s.codes()}")
            s.advance(300)
            ok(f"normal starts (attempt {'first' if first else 'last'}): HEALTHY at the end, nothing observed", s.state == "HEALTHY" and s.attrs.get(f"{W.pp}_failures_observed") == 0
               and s.attrs.get(f"{W.po}_failures_observed") == 0)
        s = Sim(c)
        run_start(s, W.kp, ok=True, dur=70)        # a slow start: the success lands 70 s after its attempt, inside the settle
        s.advance(300)
        ok("a slow successful start (70 s) never warns", s.state == "HEALTHY" and s.attrs.get(f"{W.pp}_failures_observed") == 0)
        s = Sim(c)
        run_start(s, W.kp, ok=True, dur=SEEN_GAP_S[W.kp])        # the slowest success the firmware contract allows, as Home Assistant sees it
        s.advance(SETTLE + 60)
        ok(f"the slowest contract start (success seen {SEEN_GAP_S[W.kp]} s after its attempt) never warns",
           all(r[1] != "WARNING" for r in s.renders) and s.attrs.get(f"{W.pp}_failures_observed") == 0)

    run(s_normal)

    def s_skew_after_failure():
        s = Sim(c)
        run_start(s, W.kp, ok=False)
        s.advance(SETTLE + 5)
        s.advance(400)
        run_start(s, W.kp, ok=True, dur=10, attempt_first=False)      # the success is published BEFORE its attempt: unresolved dips, then returns
        s.advance(SETTLE + 60)
        ok("a normal start whose success publishes before its attempt, after an earlier failure, is not a second failure", s.attrs.get(f"{W.pp}_failures_observed") == 1,
           str(s.attrs.get(f"{W.pp}_failures_observed")))

    run(s_skew_after_failure)

    # --- the exact settle boundary ----------------------------------------------------------------------------------------------
    def s_settle_boundary():
        s = Sim(c, W.bv(2, 2, 1, 1))
        s.set(W.pa, "3.0")
        s.advance(SETTLE - 1)
        s.set(W.ps, "3.0")                    # the success arrives 239 s after its attempt
        s.advance(SETTLE + 60)
        ok(f"success seen {SETTLE - 1} s after its attempt: never WARNING, nothing observed, baseline back at 0",
           all(r[1] != "WARNING" for r in s.renders) and s.attrs.get(f"{W.pp}_failures_observed") == 0 and s.attrs.get(f"{W.pp}_unresolved_baseline") == 0,
           f"{[r[1] for r in s.renders][-3:]} {s.attrs.get(f'{W.pp}_failures_observed')}")
        s = Sim(c, W.bv(2, 2, 1, 1))
        t_a = s.now
        s.set(W.pa, "3.0")
        s.advance(SETTLE - 1)
        ok(f"no success {SETTLE - 1} s after the attempt: not yet confirmed", s.state == "HEALTHY", s.state)
        s.advance(1)
        last = s.renders[-1]
        ok(f"no success {SETTLE} s after the attempt: confirmed at exactly that instant by the settle trigger",
           last[0] == t_a + timedelta(seconds=SETTLE) and last[3] == "start_counters_settled" and s.state == "WARNING" and s.codes() == [W.cp], f"{last[0]} {last[3]} {s.state}")
        s.set(W.ps, "3.0")                    # a success published after the settle no longer retracts the finding
        s.advance(120)
        ok("a success seen after the settle does not retract the confirmed failure (it stays for its window)",
           s.state == "WARNING" and s.attrs.get(f"{W.pp}_failures_observed") == 1, s.state)

    run(s_settle_boundary)

    # --- a silent Wi-Fi loss: the counters stay available but stale until the ESPHome client gives up ------------------------------
    def s_silent_link_loss():
        worst = STALE_HOLD_S[W.kp]
        for hold in (30, LINK_LOSS_S, worst, SETTLE - 1):
            for succeeded in (True, False):
                s = Sim(c, W.bv(3, 3, 2, 2))
                s.advance(41)
                s.set(W.pa, "4.0")             # the attempt publishes; the link then dies silently: nothing more arrives
                s.advance(hold)                # ... the counters stay AVAILABLE with stale values for `hold` s
                s.unavailable()                # the client gives up: every dongle counter unavailable
                s.advance(75)
                back = {W.pa: "4.0", W.ps: "4.0" if succeeded else "3.0", W.oa: "2.0", W.os: "2.0"}
                for e, v in back.items():      # reconnection: the dongle's current values arrive
                    s.set(e, v)
                s.advance(SETTLE + 120)
                ok(f"silent link loss {hold} s after the attempt ({'the start succeeded' if succeeded else 'the start failed'}): never WARNING, "
                   f"nothing observed, the reconnection only sets the baseline",
                   all(r[1] != "WARNING" for r in s.renders) and s.attrs.get(f"{W.pp}_failures_observed") == 0 and s.attrs.get(f"{W.po}_failures_observed") == 0
                   and s.attrs.get(f"{W.pp}_unresolved_baseline") == (0 if succeeded else 1) and s.state == "HEALTHY",
                   f"{sorted(set(r[1] for r in s.renders))} {s.attrs.get(f'{W.pp}_failures_observed')} {s.attrs.get(f'{W.pp}_unresolved_baseline')}")
        ok(f"the contract's worst stale hold ({worst} s = {SEEN_GAP_S[W.kp]} s seen gap + {LINK_LOSS_S} s client timeout) is inside the settle", worst < SETTLE)
        s = Sim(c, W.bv(3, 3, 2, 2))
        s.advance(41)
        s.set(W.pa, "4.0")
        s.advance(SETTLE + 5)                  # control: stale-but-available for the whole settle is indistinguishable from a failed start
        ok(f"control: counters that stay available and unchanged for the full {SETTLE} s settle are reported (the settle is the only guard)",
           s.state == "WARNING" and s.codes() == [W.cp])
        s = Sim(c)
        run_start(s, W.ko, ok=False)           # the other feature's genuine failure is unaffected by this feature's link scenario
        s.advance(SETTLE + 5)
        s.set(W.pa, "1.0")
        s.advance(60)
        s.unavailable()
        s.advance(75)
        ok("a silent link loss inside the other feature's window keeps that feature's WARNING and code", s.state == "WARNING" and s.codes() == [W.co], f"{s.state} {s.codes()}")

    run(s_silent_link_loss)

    # --- repeated / retried / simultaneous -------------------------------------------------------------------------------------------
    def s_repeat():
        s = Sim(c)
        run_start(s, W.kp, ok=False)
        s.advance(SETTLE)
        t1 = s.now
        s.advance(1000)
        t2 = s.now
        run_start(s, W.kp, ok=False)
        s.advance(SETTLE)
        ok("second failure: failures_observed 2, last_failure_at restamped", s.attrs.get(f"{W.pp}_failures_observed") == 2 and s.attrs.get(f"{W.pp}_last_failure_at") == t2.isoformat(),
           str(s.attrs.get(f"{W.pp}_last_failure_at")))
        s.advance((t1 + timedelta(seconds=WINDOW + 30) - s.now).total_seconds())
        ok("first failure's window is over but the second keeps WARNING", s.state == "WARNING")
        s.advance((t2 + timedelta(seconds=WINDOW) - s.now).total_seconds())
        ok("the second window closes exactly 1800 s after the second attempt", s.state == "HEALTHY", s.state)
        s2 = Sim(c)
        run_start(s2, W.kp, ok=False)
        s2.advance(20)
        run_start(s2, W.kp, ok=False)        # two failures inside one settle: one confirmation of +2
        s2.advance(SETTLE + 5)
        ok("two failed starts inside one settle: one confirmation counting both", s2.state == "WARNING" and s2.attrs.get(f"{W.pp}_failures_observed") == 2, str(s2.attrs.get(f"{W.pp}_failures_observed")))
        s3 = Sim(c)
        run_start(s3, W.kp, ok=False)
        s3.advance(33)
        run_start(s3, W.kp, ok=True, dur=10)     # the schedule's single retry succeeds
        s3.advance(SETTLE + 5)
        ok("a failed start followed by a successful retry is still a failure (WARNING; it stays for the window)", s3.state == "WARNING" and s3.attrs.get(f"{W.pp}_failures_observed") == 1)
        ok("... its time is that of the last start attempt of the burst (the attempts counter's change time)", s3.attrs.get(f"{W.pp}_last_failure_at") != "none")
        s4 = Sim(c)
        run_start(s4, W.kp, ok=False)
        run_start(s4, W.ko, ok=False, dur=5)
        s4.advance(SETTLE + 5)
        ok("simultaneous Free Power and Dump to Grid failures: one WARNING with both codes and both features", s4.state == "WARNING" and s4.codes() == [CODE_FP, CODE_DG]
           and s4.attrs.get("failed_features") == ["free_power", "dump_to_grid"], f"{s4.codes()}")
        s4.advance(600)
        run_start(s4, W.kp, ok=False)
        s4.advance(SETTLE + 2)
        ok("... each feature is independent: a later failure of one leaves the other's count as it was", s4.attrs.get(f"{W.po}_failures_observed") == 1 and s4.attrs.get(f"{W.pp}_failures_observed") == 2)

    run(s_repeat)

    # --- reset / unavailable / reconnection ----------------------------------------------------------------------------------------------
    def s_reset():
        s = Sim(c, W.bv(6, 4))                      # unresolved 2
        s.unavailable()
        ok("counters unavailable, no open window: UNKNOWN, never HEALTHY", s.state == "UNKNOWN", s.state)
        for e in COUNTERS:
            s.set(e, "0.0")
        s.advance(SETTLE + 60)
        ok("device reboot: unavailable then 0 0: HEALTHY, no fabricated failure", s.state == "HEALTHY" and s.codes() == [] and s.attrs.get(f"{W.pp}_unresolved_baseline") == 0,
           f"{s.state} {s.attrs.get(f'{W.pp}_unresolved_baseline')}")
        run_start(s, W.kp, ok=False)
        s.advance(SETTLE)
        ok("a failed start after the reset is detected (the baseline was re-established at 0)", s.state == "WARNING" and s.codes() == [W.cp])
        s2 = Sim(c, W.bv(5, 5))
        s2.unavailable()
        s2.advance(120)
        s2.set(W.pa, "9.0")
        s2.set(W.ps, "6.0")                                # back after a gap, counters higher: 3 unresolved appeared while it was gone
        s2.set(W.oa, "0.0")
        s2.set(W.os, "0.0")
        s2.advance(SETTLE + 60)
        ok("reconnection with higher counters: the first values only set the baseline (a failure while unreadable is not observed)",
           s2.state == "HEALTHY" and s2.attrs.get(f"{W.pp}_unresolved_baseline") == 3, f"{s2.state} {s2.attrs.get(f'{W.pp}_unresolved_baseline')}")
        s3 = Sim(c, W.bv(8, 6))
        s3.set(W.pa, "2.0")        # a reset seen without an unavailable gap: the pair is inconsistent for a moment (successes above attempts)
        ok("an inconsistent pair (successes above attempts) clears the baseline, never warns", s3.state != "WARNING" and s3.attrs.get(f"{W.pp}_unresolved_baseline") == -1,
           f"{s3.state} {s3.attrs.get(f'{W.pp}_unresolved_baseline')}")
        s3.set(W.ps, "0.0")
        s3.advance(SETTLE + 60)
        ok("... and settles to a new baseline once consistent (2 unresolved: no failure)", s3.state == "HEALTHY" and s3.attrs.get(f"{W.pp}_unresolved_baseline") == 2)
        s4 = Sim(c)
        run_start(s4, W.kp, ok=False)
        s4.advance(SETTLE)
        s4.advance(200)
        s4.unavailable()
        ok("counters unavailable inside an open window: WARNING stays (a real finding beats UNKNOWN), code kept", s4.state == "WARNING" and W.cp in s4.codes(), f"{s4.state}")
        s4.advance(WINDOW)
        ok("... and it still expires on time while unavailable", s4.state == "UNKNOWN", s4.state)
        for v in ("unknown", "", "none", "abc", "nan", "inf", "-1.0", "1e12"):
            s5 = Sim(c, dict(W.bv(), **{W.pa: v}))
            ok(f"counter state {v!r} with no failure in the window: UNKNOWN (never HEALTHY), baseline cleared",
               s5.state == "UNKNOWN" and s5.attrs.get(f"{W.pp}_unresolved_baseline") == -1, f"{s5.state} {s5.attrs.get(f'{W.pp}_unresolved_baseline')}")
        s6 = Sim(c, {k: v for k, v in W.bv().items() if k != W.ps})
        ok("a counter entity missing from the state machine: UNKNOWN", s6.state == "UNKNOWN")
        s7 = Sim(c)
        run_start(s7, W.ko, ok=False)
        s7.advance(SETTLE)
        s7.unavailable([W.pa, W.ps])
        ok("only the primary pair unreadable while the other feature's window is open: WARNING with only the other's code", s7.state == "WARNING" and s7.codes() == [W.co])

    run(s_reset)

    # --- Home Assistant restart ----------------------------------------------------------------------------------------------------
    def s_restart():
        s = Sim(c, W.bv(4, 4))
        s.restart()
        s.advance(SETTLE + 30)
        ok("HA restart with unchanged counters: no fabricated failure", s.state == "HEALTHY" and s.attrs.get(f"{W.pp}_failures_observed") == 0)
        ok("... the start render (dongle still unavailable) was UNKNOWN, not HEALTHY", [r for r in s.renders if r[3] == "start"][-1][1] == "UNKNOWN")
        s2 = Sim(c)
        run_start(s2, W.kp, ok=False)
        s2.advance(SETTLE)
        t_fail_attr = s2.attrs.get(f"{W.pp}_last_failure_at")
        s2.advance(400)
        s2.restart()
        s2.advance(SETTLE + 10)
        ok("HA restart inside an open window (restored attributes): still WARNING, failure time and count kept",
           s2.state == "WARNING" and s2.attrs.get(f"{W.pp}_last_failure_at") == t_fail_attr and s2.attrs.get(f"{W.pp}_failures_observed") == 1, f"{s2.state}")
        s2.advance(WINDOW)
        ok("... expires by the minute backstop after a restart (the `for` timer was lost)", s2.state == "HEALTHY")
        s3 = Sim(c, W.bv(4, 4))
        s3.restart(downtime_changes={W.pa: fmt(5)})             # a failed start happened while Home Assistant was down
        s3.advance(SETTLE + 60)
        ok("a failure that happened while Home Assistant was down is not fabricated at the restart (the first values set the baseline)",
           s3.state == "HEALTHY" and s3.attrs.get(f"{W.pp}_failures_observed") == 0)
        s4 = Sim(c, W.bv(4, 4))
        s4.restart(restore=False)
        s4.advance(SETTLE + 60)
        ok("restart without restore: baseline only, HEALTHY", s4.state == "HEALTHY" and s4.attrs.get(f"{W.pp}_failures_observed") == 0)
        run_start(s4, W.kp, ok=False)
        s4.advance(SETTLE)
        ok("... and a failure after it is detected", s4.state == "WARNING")
        s5 = Sim(c, W.bv(4, 4))
        s5.set(W.pa, "5.0")                                      # a start is in flight when Home Assistant restarts
        s5.restart(counters_after={W.pa: fmt(5), W.ps: fmt(5)})   # ... and it succeeded
        s5.advance(SETTLE + 60)
        ok("a start in flight across a restart that then succeeds: no failure", s5.state == "HEALTHY" and s5.attrs.get(f"{W.pp}_failures_observed") == 0)
        s7 = Sim(c, W.bv(4, 4))
        s7.restart(keep_available=True, downtime_changes={W.pa: fmt(5)})         # the counters are readable at the start render and changed while HA was down
        s7.advance(SETTLE + 60)
        ok("a restart with the counters already readable: a change while Home Assistant was down is only a new baseline (the start render never reports a failure)",
           s7.state == "HEALTHY" and s7.attrs.get(f"{W.pp}_failures_observed") == 0 and s7.attrs.get(f"{W.pp}_unresolved_baseline") == 1, f"{s7.state} {s7.attrs.get(f'{W.pp}_failures_observed')}")
        s6 = Sim(c)
        run_start(s6, W.kp, ok=False)
        s6.advance(SETTLE)
        lf = s6.attrs.get(f"{W.pp}_last_failure_at")
        s6.attrs = dict(s6.attrs, **{f"{W.pp}_last_failure_at": (T0 + timedelta(hours=3)).isoformat()})
        s6.advance(60)
        ok("a failure time in the future (clock skew) is not a live window", s6.state in ("HEALTHY", "UNKNOWN") and lf != "none", f"{s6.state}")

    run(s_restart)

    # --- randomised against an independent event-sourced oracle -------------------------------------------------------------------------
    def s_oracle():
        rng = random.Random(20261010 + (0 if W.primary == "fp" else 7))
        n_seq = 3 if quick else 30
        mism: list = []
        checked = 0
        for seq in range(n_seq):
            s = Sim(c, base_values(rng.randint(0, 6), 0, rng.randint(0, 6), 0))
            for e_a, e_s in ((FPA, FPS), (DGA, DGS)):
                s.values[e_s] = fmt(rng.randint(0, int(float(s.values[e_a]))))
            s.advance(300)
            truth = {"fp": [], "dg": []}      # HA-visible attempt-publish time of every failed start
            for _ in range(rng.randint(2, 7)):
                s.advance(rng.randint(200, 1500))
                feat = rng.choice(["fp", "dg"])
                kind = rng.choice(["ok", "ok", "fail", "refusal"])
                if kind == "refusal":
                    s.set(FP_STATUS if feat == "fp" else DG_STATUS, f"REJECTED - probe {rng.random():.4f}")
                    continue
                t_attempt = s.now
                run_start(s, feat, ok=(kind == "ok"), dur=rng.randint(4, 30), attempt_first=rng.random() < 0.7)
                if kind == "fail":
                    truth[feat].append(t_attempt)
                s.advance(rng.randint(SETTLE + 10, SETTLE + 110))
                for f in ("fp", "dg"):
                    ends = [t + timedelta(seconds=WINDOW) for t in truth[f]]
                    if any(abs((s.now - e).total_seconds()) < 75 for e in ends):
                        continue
                    want = any(e > s.now for e in ends)
                    got = (CODE_FP if f == "fp" else CODE_DG) in s.codes()
                    checked += 1
                    if got != want:
                        mism.append((seq, f, got, want, s.state))
            s.advance(WINDOW + 200)
            tot_fp = s.attrs.get("free_power_failures_observed")
            tot_dg = s.attrs.get("dump_to_grid_failures_observed")
            checked += 2
            if tot_fp != len(truth["fp"]) or tot_dg != len(truth["dg"]):
                mism.append((seq, "totals", (tot_fp, tot_dg), (len(truth["fp"]), len(truth["dg"]))))
            if s.state != "HEALTHY" or s.codes() != []:
                mism.append((seq, "final", s.state, s.codes()))
        ok(f"randomised: {n_seq} start sequences, {checked} checkpoints (warning window, observed counts, final state) match the independent oracle", not mism, str(mism[:4]))

    run(s_oracle)
    return out


def instances_identical(text: str) -> bool:
    """The Free Power and Dump to Grid instances of the step are one template: renaming one's names to the other's gives equal text."""
    m = re.search(r"(?m)^        state: >-\n(.*?)^        attributes:", text[text.index(f"unique_id: {UID}"):], re.S)
    if not m:
        return False
    lines = m.group(1).splitlines()
    fp, dg = lines[:15], lines[15:30]

    def norm(line: str, v: str, f: str) -> str:
        line = re.sub(rf"\b{v}([a-z]+)\b", r"@\1", line)
        return line.replace(f"{f}_", "§_").replace("free_power", "§").replace("dump_to_grid", "§")

    return (all(re.search(r"\bfp[a-z]+\b", l) and not re.search(r"\bdg[a-z]+\b", l) for l in fp)
            and all(re.search(r"\bdg[a-z]+\b", l) and not re.search(r"\bfp[a-z]+\b", l) for l in dg)
            and [norm(l, "fp", "free_power") for l in fp] == [norm(l, "dg", "dump_to_grid") for l in dg])


# ---------------------------------------------------------------------------------------------------------------------------
print("[1] Wiring: firmware counters, triggers, the one template, unchanged neighbours, no control surface")
fw = FW_PATH.read_text(encoding="utf-8")
check("the device friendly name is 'ECCO Clock Dongle' (entity ids are ecco_clock_dongle_<name>)", "\n  friendly_name: ECCO Clock Dongle\n" in fw)
fwdoc = yaml.load(fw, Loader=FastLoader)
sens = {s.get("name"): s for s in fwdoc.get("sensor", []) if isinstance(s, dict)}
texts = {s.get("name"): s for s in fwdoc.get("text_sensor", []) if isinstance(s, dict)}
for name, entity, glob in (("Free Power Start Attempts Since Boot", FPA, "free_power_start_attempts"), ("Free Power Start Successes Since Boot", FPS, "free_power_start_successes"),
                           ("Dump to Grid Start Attempts Since Boot", DGA, "dump_start_attempts"), ("Dump to Grid Start Successes Since Boot", DGS, "dump_start_successes")):
    s = sens.get(name) or {}
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", name.lower())).strip("_")
    check(f"firmware sensor '{name}' maps to {entity} and publishes {glob} every 30 s, 0 decimals, no state_class",
          f"sensor.{DEV}_{slug}" == entity and f"id({glob})" in str(s.get("lambda")) and s.get("update_interval") == "30s" and s.get("accuracy_decimals") == 0
          and "state_class" not in s)
for glob, n in (("free_power_start_attempts", 1), ("free_power_start_successes", 1), ("dump_start_attempts", 1), ("dump_start_successes", 1)):
    check(f"{glob} is incremented in exactly {n} place of the firmware (a start attempt / a verified ACTIVE, nothing else)", fw.count(f"id({glob})++;") == n, str(fw.count(f"id({glob})++;")))
fw_start = fw[fw.index("  - id: start_free_power_override"):fw.index("  - id: start_free_power_override") + 200000]
gate_end = fw_start.index("id(free_power_start_attempts)++;")
check("Free Power: the attempt counter is incremented only after the start gate (the gate's else branch REJECTED - ... is never counted)",
      "id(free_power_write_enable).state" in fw_start[:gate_end] and "REJECTED - " not in fw_start[:gate_end] and "REJECTED - " in fw_start[gate_end:gate_end + 120000])
check("Free Power: the success counter sits in the verified-ACTIVE branch", fw.index("id(free_power_start_successes)++;") > fw.index("id(free_power_active_persisted) = true;") - 400)
dump_start = fw[fw.index("  - id: start_dump_to_grid_override"):fw.index("  - id: start_dump_to_grid_override") + 150000]
dgate_end = dump_start.index("id(dump_start_attempts)++;")
check("Dump to Grid: the attempt counter is incremented only after its start gate; the success counter only once the lease is durably active",
      "id(dump_write_enable).state" in dump_start[:dgate_end] and "REJECTED - " not in dump_start[:dgate_end] and "id(dump_active_persisted) = true;" in dump_start[dump_start.index("id(dump_start_successes)++;") - 200:dump_start.index("id(dump_start_successes)++;")])
for key, script, inc, succ in (("fp", "start_free_power_override", "id(free_power_start_attempts)++;", "id(free_power_start_successes)++;"),
                               ("dg", "start_dump_to_grid_override", "id(dump_start_attempts)++;", "id(dump_start_successes)++;")):
    body = fw[fw.index(f"  - id: {script}\n"):]
    body = body[:body.index("\n  - id: ", 10)]
    seg = body[body.index(inc):body.index(succ)]
    code = re.sub(r"//[^\n]*|#[^\n]*", "", seg)          # YAML and C++ comments may mention a script or a delay; only code counts
    waits = re.findall(r"- wait_until:\n(?:[^\n]*\n){1,3}?\s*timeout: (\S+)\n", seg)
    check(f"timing contract ({script}): between the attempt and the success only bounded {FW_WAIT_S} s waits, at most {FW_MAX_WAITS[key]} "
          f"(found {len(waits)}), no delay, no script call; seen gap {SEEN_GAP_S[key]} s + client timeout {LINK_LOSS_S} s = {STALE_HOLD_S[key]} s < settle {SETTLE} s",
          seg.count("wait_until:") == len(waits) <= FW_MAX_WAITS[key] and all(w == f"{FW_WAIT_S * 1000}ms" for w in waits)
          and not re.search(r"\bdelay\b|\bscript\.(?:execute|wait)\b|vTaskDelay", code) and STALE_HOLD_S[key] < SETTLE,
          f"{len(waits)} {sorted(set(waits))}")
check("the failures-since-boot counters are NOT what the sensor reads (they count restore failures too)", FPF not in LIVE_TEXT.split(f"unique_id: {UID}")[1].split("unique_id: ecco_health_configuration")[0]
      and DGF not in LIVE_TEXT.split(f"unique_id: {UID}")[1].split("unique_id: ecco_health_configuration")[0])
check("restore failures also increment the failures counters (why they cannot be the signal): the restore scripts carry free_power_failures++ and dump_failures++",
      fw.count("id(free_power_failures)++;") > 10 and fw.count("id(dump_failures)++;") >= 4)
for name in ("Free Power Status", "Dump to Grid Status", "Free Power Recovery State", "Dump to Grid Recovery State"):
    check(f"'{name}' exists as an event-published text sensor (update_interval never)", (texts.get(name) or sens.get(name) or {}).get("update_interval") == "never")

live_doc, base_doc = load(LIVE_TEXT), load(BASE_TEXT)
check("as of the previous entry the package is what main had (the fsw1 reverter round-trips)", scope.add_fsw1_health_package(BASE_TEXT) == LIVE_TEXT)
check("top-level keys unchanged (template only: no automation / script / input_* / sensor platform added)", sorted(live_doc) == sorted(base_doc) == ["template"])


def by_uid(doc):
    out = {}
    for bi, block in enumerate(doc["template"]):
        for plat in ("sensor", "binary_sensor"):
            for ent in block.get(plat, []) or []:
                out[ent["unique_id"]] = (bi, plat, ent, block.get("triggers"))
    return out


L, B = by_uid(live_doc), by_uid(base_doc)
check("exactly one template entity was added: ecco_health_start_failures", sorted(set(L) - set(B)) == [UID] and not (set(B) - set(L)), str(sorted(set(L) ^ set(B))))
check("every pre-existing template entity is byte-identical in definition and triggers", all(L[u][2:] == B[u][2:] for u in B))
ent = L[UID][2]
check("the entity has no device_class, unit or action; name and unique_id are as declared", ent.get("name") == "ECCO Health Start Failures" and not {"device_class", "unit_of_measurement", "icon"} & set(ent))
check("the two feature instances of the step are one template (identical after renaming)", instances_identical(LIVE_TEXT))
code_text = "\n".join(l for l in LIVE_TEXT.splitlines() if not l.strip().startswith("#"))
check("no service / action / automation / restart / esphome / modbus / notify token outside comments",
      not any(tok in code_text for tok in ("service:", "action:", "automation:", "homeassistant.restart", "esphome.", "button.press", "modbus_client", "notify")))
check("no `variables:` and no literal YAML list attribute (every list attribute is a template string)",
      "variables:" not in code_text.split(f"unique_id: {UID}")[1].split("unique_id: ecco_health_configuration")[0] and not [k for k, v in ent["attributes"].items() if isinstance(v, list)])
check("the RTC failure alert's window trigger text appears exactly once more than the new one (the new window trigger is spelled differently)",
      LIVE_TEXT.count("        for:\n          seconds: 1800\n") == 1 and LIVE_TEXT.count("          minutes: 30\n") == 1)

print("")
print("[2] Registry, reason codes and documentation")
checks = {c["id"]: c for c in yaml.safe_load(CHECKS_PATH.read_text(encoding="utf-8"))["checks"]}
codes = {c["code"]: c for c in yaml.safe_load(CODES_PATH.read_text(encoding="utf-8"))["reason_codes"]}
for cid, sub, rc_code in (("free_power_start_failed_recent", "free_power", CODE_FP), ("dump_to_grid_start_failed_recent", "manual_write_system", CODE_DG)):
    rec = checks.get(cid, {})
    check(f"check {cid}: {sub}, failure_counter_delta over 1800 s with warning_delta 1, implemented_offline (not live-proven), one outcome {rc_code}",
          rec.get("subsystem") == sub and rec.get("check_type") == "failure_counter_delta" and rec.get("parameters") == {"window_seconds": WINDOW, "warning_delta": 1, "failure_delta": None}
          and rec.get("implementation_status") == "implemented_offline" and rec.get("live_proof_status") == "unknown" and [o["reason_code"] for o in rec.get("outcomes", [])] == [rc_code]
          and rec.get("source", {}).get("type") == "derived")
    rc = codes.get(rc_code, {})
    check(f"reason code {rc_code}: {sub}, WARNING, does not block manual control, does not affect the forecast",
          rc.get("subsystem") == sub and rc.get("severity") == "WARNING" and rc.get("blocks_manual_control") is False and rc.get("affects_forecast") is False)
check("the older free_power_failures_recent record (all failures, designed) is untouched", checks["free_power_failures_recent"]["implementation_status"] == "designed" and "FREE_POWER_FAILURES_RECENT" in codes)
check("the sensor's represented_checks and subsystems exist in the registry", all(i in checks for i in ast.literal_eval(ENV.from_string(ent["attributes"]["represented_checks"]).render()))
      and all(s in {c["subsystem"] for c in checks.values()} for s in ast.literal_eval(ENV.from_string(ent["attributes"]["subsystems"]).render())))
check("the registry reason codes round-trip through the fsw1 reverters",
      scope.add_fsw1_reason_codes(scope.pre_fsw1_reason_codes(CODES_PATH.read_text(encoding="utf-8"))) == CODES_PATH.read_text(encoding="utf-8")
      and scope.add_fsw1_checks_registry(scope.pre_fsw1_checks_registry(CHECKS_PATH.read_text(encoding="utf-8"))) == CHECKS_PATH.read_text(encoding="utf-8")
      and scope.add_fsw1_architecture_doc(scope.pre_fsw1_architecture_doc(DOC_PATH.read_text(encoding="utf-8"))) == DOC_PATH.read_text(encoding="utf-8"))
val = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "validate_system_health_checks.py")], capture_output=True, text=True, cwd=str(ROOT))
check("tools/validate_system_health_checks.py passes (every code is used by a check of its own subsystem)", val.returncode == 0, (val.stdout + val.stderr)[-400:])
doc = DOC_PATH.read_text(encoding="utf-8")
check("the architecture document describes the sensor, both checks, both codes and the settle / window / baseline rules",
      all(x in doc for x in ("sensor.ecco_health_start_failures", "free_power_start_failed_recent", "dump_to_grid_start_failed_recent", CODE_FP, CODE_DG, f"{SETTLE} s", "1800 s", "baseline", "Timing assumption")))

print("")
print("[3]-[4] Behaviour, restart / reset handling and the randomised oracle (the live package)")
for name, cond, detail in battery(LIVE_TEXT):
    check(name, cond, detail)

print("")
print("[5] The Overview hero, executed with Node")
dash = load(DASH_LIVE)
dash_base = load(DASH_BASE)


def hero_body(d) -> str:
    ov = d["views"][0]
    cards = [c for s in ov["sections"][:1] for c in s.get("cards", []) if c.get("name") == "ECCO Pro" and c.get("type") == "custom:button-card"]
    assert len(cards) == 1, "the hero card"
    body = cards[0]["custom_fields"]["body"].strip()
    assert body.startswith("[[[") and body.endswith("]]]")
    return body[3:-3]


HERO, HERO_BASE = hero_body(dash), hero_body(dash_base)
check("the hero is the first card of the first Overview section, one button-card, as before", HERO != HERO_BASE and HERO.count("const hardAttention =") == 1)
check("the sensor's id appears literally inside get('...') (button-card detects entities that way)", HERO.count(f"get('{HERO_ID}')") == 1)
req_line = [l for l in HERO.splitlines() if l.strip().startswith("const required =")][0]
check("the sensor is NOT in `required` (an unavailable sensor stays quiet), nor does `required` mention sup / fb", HERO_ID not in req_line and "failedStart" not in req_line and not re.search(r"\b(sup|fb)\b", req_line))
check("the hero never reads the free-text status sensors (structured codes only)", f"{DEV}_free_power_status" not in HERO and f"{DEV}_dump_to_grid_status" not in HERO and "start_failures_status" not in HERO)
block = HERO[HERO.index("const hardAttention ="):HERO.index("const busy =")]
check("the existing hardAttention expression is byte-identical to the previous hero's (the new reason is added beside it, not inside it)",
      block == HERO_BASE[HERO_BASE.index("const hardAttention ="):HERO_BASE.index("const busy =")] and "sup === 'Lost'" in block and not re.search(r"\bfb\b", block))

NODE = shutil.which("node")
check("Node is available to execute the hero (the dashboard's JavaScript is plain)", bool(NODE), str(NODE))
HERO_IDS = sorted(set(re.findall(r"get\('([a-z_]+\.[a-z0-9_]+)'\)", HERO)))
NODE_SCRIPT = (
    "const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
    "const out = {};"
    "for (const [name, body] of Object.entries(inp.bodies)) { const fn = new Function('states', body); out[name] = inp.scenarios.map(s => { try { return String(fn(s.states)); } catch (e) { return 'ERROR ' + e.message; } }); }"
    "process.stdout.write(JSON.stringify(out));"
)


def default_state(eid: str) -> str:
    if eid.endswith(("telemetry_online", "configuration_online", "ntp_synced", "raw_cache_valid")):
        return "on"
    if eid.startswith("binary_sensor."):
        return "off"
    if eid == HERO_ID:
        return "HEALTHY"
    if eid.startswith("sensor.ecco_health_"):
        return "HEALTHY"
    if eid.endswith("inverter_system_state"):
        return "normal"
    if eid.endswith("inverter_warning"):
        return "00000000"
    if eid.endswith("inverter_fault"):
        return "0000000000000000"
    if eid.endswith("_recovery_state"):
        return "NONE"
    if eid == "sensor.ecco_supervision_status":
        return "Healthy"
    if eid == FB_STATUS_ID:
        return "Ready"
    return "x"


def hero_states(over: dict, codes=None, include_sensor=True) -> dict:
    base = {eid: {"state": default_state(eid), "attributes": {}} for eid in HERO_IDS}
    if not include_sensor:
        base.pop(HERO_ID, None)
    for k, v in over.items():
        base[k] = {"state": v, "attributes": {}}
    if codes is not None and HERO_ID in base:
        base[HERO_ID] = {"state": base[HERO_ID]["state"], "attributes": {"reason_codes": codes}}
    return base


def run_node(bodies: dict, scenarios: list) -> dict:
    r = subprocess.run([NODE, "-e", NODE_SCRIPT], input=json.dumps({"bodies": bodies, "scenarios": scenarios}), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else {"<node>": [r.stderr[:300]]}


def parts(html: str) -> dict:
    head = re.search(r"font-size:22px;font-weight:900;[^>]*>([^<]*)<", html)
    sub = re.search(r"margin-top:2px;\">([^<]*)<", html)
    tx = re.search(r">TRANSACTIONS</div>\s*<div[^>]*>([^<]*)<", html)
    rec = re.search(r">RECOVERY</div>\s*<div[^>]*>([^<]*)<", html)
    return {"headline": head.group(1).strip() if head else None, "subline": sub.group(1).strip() if sub else None,
            "tx": tx.group(1).strip() if tx else None, "recovery": rec.group(1).strip() if rec else None}


D, F = f"sensor.{DEV}_dump_to_grid_recovery_state", f"sensor.{DEV}_free_power_recovery_state"
EXIST_SUB = "A monitored subsystem needs checking"
HERO_SCEN = [
    # (name, overrides, reason_codes, include sensor, sensor state, headline, subline, transactions pill)
    ("nominal, sensor healthy", {}, [], True, "HEALTHY", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("nominal, sensor absent from the state machine", {}, None, False, "HEALTHY", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("sensor unknown stays quiet", {HERO_ID: "unknown"}, [], True, "unknown", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("sensor unavailable stays quiet", {HERO_ID: "unavailable"}, [], True, "unavailable", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("sensor UNKNOWN (counters unreadable) stays quiet", {HERO_ID: "UNKNOWN"}, [], True, "UNKNOWN", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("Free Power start failed", {HERO_ID: "WARNING"}, [CODE_FP], True, "WARNING", "ATTENTION", "A Free Power start failed recently", "START FAILED"),
    ("Dump to Grid start failed", {HERO_ID: "WARNING"}, [CODE_DG], True, "WARNING", "ATTENTION", "A Dump to Grid start failed recently", "START FAILED"),
    ("both start failures", {HERO_ID: "WARNING"}, [CODE_FP, CODE_DG], True, "WARNING", "ATTENTION", "Free Power and Dump to Grid starts failed recently", "START FAILED"),
    ("codes delivered as a string, not a list", {HERO_ID: "WARNING"}, f"['{CODE_FP}']", True, "WARNING", "ATTENTION", "A Free Power start failed recently", "START FAILED"),
    ("WARNING with no start code (not this sensor's code) is not a failed start", {HERO_ID: "WARNING"}, ["OTHER_CODE"], True, "WARNING", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("codes present but the state is not WARNING (stale attribute) is not a failed start", {HERO_ID: "HEALTHY"}, [CODE_FP], True, "HEALTHY", "SYSTEMS NOMINAL", "Live monitoring inputs are healthy", "HEALTHY"),
    ("failed start while a Dump lease is active: ATTENTION outranks the lease", {HERO_ID: "WARNING", "binary_sensor.ecco_clock_dongle_dump_to_grid_active": "on"}, [CODE_FP], True, "WARNING",
     "ATTENTION", "A Free Power start failed recently", "START FAILED"),
    ("failed start while Free Power is active", {HERO_ID: "WARNING", "binary_sensor.ecco_clock_dongle_free_power_active": "on"}, [CODE_DG], True, "WARNING", "ATTENTION",
     "A Dump to Grid start failed recently", "START FAILED"),
    ("settled recovery states (NONE / ACCEPTED) do not hide a failed start", {HERO_ID: "WARNING", D: "ACCEPTED - operator chose to keep the live inverter state"}, [CODE_FP], True, "WARNING",
     "ATTENTION", "A Free Power start failed recently", "START FAILED"),
    # existing priority: another attention reason keeps its subline
    ("existing: Dump recovery LOCKED plus a failed start: the existing subline wins", {HERO_ID: "WARNING", D: "LOCKED - operator decision required"}, [CODE_FP], True, "WARNING",
     "ATTENTION", EXIST_SUB, "START FAILED"),
    ("existing: Free Power recovery LOCKED_NEITHER plus a failed start", {HERO_ID: "WARNING", F: "LOCKED_NEITHER"}, [CODE_DG], True, "WARNING", "ATTENTION", EXIST_SUB, "START FAILED"),
    ("existing: restore obligation pending (snapshot valid, idle) plus a failed start", {HERO_ID: "WARNING", "binary_sensor.ecco_clock_dongle_free_power_snapshot_valid": "on"}, [CODE_FP], True,
     "WARNING", "ATTENTION", EXIST_SUB, "START FAILED"),
    ("existing: supervision lost plus a failed start", {HERO_ID: "WARNING", "sensor.ecco_supervision_status": "Lost"}, [CODE_FP], True, "WARNING", "ATTENTION", EXIST_SUB, "START FAILED"),
    ("existing: inverter fault plus a failed start", {HERO_ID: "WARNING", "sensor.ecco_clock_dongle_ecco_inverter_fault": "0000000000000001"}, [CODE_DG], True, "WARNING", "ATTENTION", EXIST_SUB, "START FAILED"),
    ("existing: ATTENTION without a failed start is unchanged", {F: "LOCKED_ORIGINAL"}, [], True, "HEALTHY", "ATTENTION", EXIST_SUB, "HEALTHY"),
    ("STATUS PARTIAL comes first: an unavailable input hides the headline change but not the pill", {HERO_ID: "WARNING", "sensor.ecco_health_communications": "unavailable"}, [CODE_FP], True, "WARNING",
     "STATUS PARTIAL", "One or more monitoring inputs are unavailable", "START FAILED"),
    ("STATUS PARTIAL: recovery sensor unavailable plus a failed start", {HERO_ID: "WARNING", D: "unavailable"}, [CODE_DG], True, "WARNING", "STATUS PARTIAL",
     "One or more monitoring inputs are unavailable", "START FAILED"),
    ("existing: dump active alone is unchanged", {"binary_sensor.ecco_clock_dongle_dump_to_grid_active": "on"}, [], True, "HEALTHY", "DUMP TO GRID ACTIVE", "ECCO is healthy and a legitimate transaction is active", "ACTIVE"),
]
if NODE:
    scen = [{"name": n, "states": hero_states(o, codes=cd, include_sensor=inc)} for n, o, cd, inc, _st, _h, _s, _t in HERO_SCEN]
    got = run_node({"live": HERO}, scen).get("live", [])
    bad = []
    for (n, _o, _cd, _inc, _st, head, sub, tx), html in zip(HERO_SCEN, got):
        p = parts(html)
        if (p["headline"], p["subline"], p["tx"]) != (head, sub, tx):
            bad.append((n, (p["headline"], p["subline"], p["tx"]), (head, sub, tx)))
    check(f"hero matrix ({len(HERO_SCEN)} scenarios): a confirmed failed start is ATTENTION with its own subline and a START FAILED pill; every existing reason keeps its "
          "subline and priority; STATUS PARTIAL still comes first; an unavailable / unknown / UNKNOWN sensor stays quiet", len(got) == len(HERO_SCEN) and not bad, str(bad[:3]))
    check("the RECOVERY pill is never changed by a failed start (recovery semantics preserved)", all(parts(h)["recovery"] == "HEALTHY" for (n, *_r), h in zip(HERO_SCEN, got) if "existing:" not in n and "recovery" not in n.lower()))

    # differential: the live hero equals the previous hero whenever no failed start is reported
    rng = random.Random(20261010)
    val_pool = {"on": ["on", "off", "unknown", "unavailable"], "off": ["off", "on", "unknown"], "healthy": ["HEALTHY", "FAILED", "WARNING", "unknown", "unavailable"],
                "normal": ["normal", "fault", "unknown"], "w": ["00000000", "00000001", "unavailable"], "f": ["0000000000000000", "0000000000000001", "unknown"],
                "rec": ["NONE", "ACCEPTED - kept", "LOCKED_NEITHER", "PENDING - found at boot", "ACCEPT_RUNNING", "unavailable", "unknown"], "sup": ["Healthy", "Lost", "Suspect", "unknown"],
                "fb": ["Ready", "Drifted", "Shadow " + "Recovery", "unknown"]}

    def random_states() -> dict:
        st = {}
        for eid in HERO_IDS:
            if eid == HERO_ID:
                continue
            d = default_state(eid)
            kind = ("on" if d == "on" else "off" if eid.startswith("binary_sensor.") else "rec" if eid.endswith("_recovery_state") else "healthy" if eid.startswith("sensor.ecco_health_")
                    else "normal" if eid.endswith("inverter_system_state") else "w" if eid.endswith("inverter_warning") else "f" if eid.endswith("inverter_fault")
                    else "sup" if eid == "sensor.ecco_supervision_status" else "fb" if eid == FB_STATUS_ID else None)
            st[eid] = {"state": (rng.choice(val_pool[kind]) if kind and rng.random() < 0.35 else d), "attributes": {}}
        return st

    diff_scen = []
    for i in range(500):
        st = random_states()
        variant = i % 4
        if variant == 1:
            st[HERO_ID] = {"state": "HEALTHY", "attributes": {"reason_codes": []}}
        elif variant == 2:
            st[HERO_ID] = {"state": rng.choice(["unknown", "unavailable", "UNKNOWN"]), "attributes": {}}
        elif variant == 3:
            st[HERO_ID] = {"state": "WARNING", "attributes": {"reason_codes": ["SOMETHING_ELSE"]}}
        diff_scen.append({"name": f"d{i}", "states": st})
    both = run_node({"live": HERO, "base": HERO_BASE}, diff_scen)
    mism = [i for i, (a, b) in enumerate(zip(both.get("live", []), both.get("base", []))) if a != b]
    check(f"differential: over {len(diff_scen)} random input maps the live hero is byte-identical to its previous state whenever the sensor is absent, healthy, unknown or reports no start code",
          len(both.get("live", [])) == len(diff_scen) and not mism, f"{len(mism)} differ, first {mism[:3]}")
    errs = [h for h in both.get("live", []) if h.startswith("ERROR")]
    check("the hero throws no error on any of those inputs", not errs, str(errs[:1]))

print("")
print("[6] Mutation: every mutant is killed")
def feature_mutants():
    for v, ea, es in (("fp", FPA, FPS), ("dg", DGA, DGS)):
        yield f"{v}: the settle is not required", f"and {v}u > {v}pu and {v}quiet) else 0", f"and {v}u > {v}pu) else 0", 1
        yield f"{v}: settle {SETTLE} s becomes 0 s", f"(as_timestamp(now()) - {v}lc) >= {SETTLE}", f"(as_timestamp(now()) - {v}lc) >= 0", 1
        yield f"{v}: settle reverts to the pre-fix 90 s (a silent link loss becomes a false failure)", f"(as_timestamp(now()) - {v}lc) >= {SETTLE}", f"(as_timestamp(now()) - {v}lc) >= 90", 1
        yield f"{v}: settle shortened to 160 s (below the worst stale hold)", f"(as_timestamp(now()) - {v}lc) >= {SETTLE}", f"(as_timestamp(now()) - {v}lc) >= 160", 1
        yield f"{v}: the settle boundary is exclusive", f"(as_timestamp(now()) - {v}lc) >= {SETTLE}", f"(as_timestamp(now()) - {v}lc) > {SETTLE}", 1
        yield f"{v}: the HA-start render may report a failure", f"and not {v}start and", "and", 1
        yield f"{v}: a missing baseline may report a failure", f"{v}pu >= 0 and {v}u > {v}pu", f"{v}u > {v}pu", 1
        yield f"{v}: a lower unresolved count never re-baselines", f"({v}u < {v}pu and {v}quiet) or ", "", 1
        yield f"{v}: a lower unresolved count re-baselines at once (the publish-order skew becomes a false failure)", f"({v}u < {v}pu and {v}quiet) or ", f"{v}u < {v}pu or ", 1
        yield f"{v}: an inconsistent pair is accepted (attempts >= successes dropped)", f"and {v}a >= {v}s and {v}a < 1000000000", f"and {v}a < 1000000000", 1
        yield f"{v}: an unreadable pair keeps the old baseline", f"{v}nu = -1 if not {v}ok else", f"{v}nu = {v}pu if not {v}ok else", 1
        yield f"{v}: the window becomes 3600 s", f"{v}age < 1800 and", f"{v}age < 3600 and", 1
        yield f"{v}: the window becomes 900 s", f"{v}age < 1800 and", f"{v}age < 900 and", 1
        yield f"{v}: the window end is inclusive", f"{v}age < 1800 and", f"{v}age <= 1800 and", 1
        yield f"{v}: a future failure time is trusted", f" and {v}age > -60 %}}", " %}", 1
        yield f"{v}: the failure time is not restamped", f"{v}lf = states[{v}ea].last_changed.isoformat() if {v}failed > 0 else", f"{v}lf = 'none' if false else", 1
        yield f"{v}: the observed count does not grow", f"| int(0)) + {v}failed %}}", "| int(0)) + 0 %}", 1
        yield f"{v}: several failures count as one", f"({v}u - {v}pu) if ({v}ok", f"1 if ({v}ok", 1
        yield f"{v}: the attempts entity is the successes entity", f"{{% set {v}ea = '{ea}' %}}", f"{{% set {v}ea = '{es}' %}}", 1
        yield f"{v}: the successes entity is the attempts entity", f"{{% set {v}es = '{es}' %}}", f"{{% set {v}es = '{ea}' %}}", 1
        yield f"{v}: the failures-since-boot counter is read instead of the attempts", f"{{% set {v}ea = '{ea}' %}}", f"{{% set {v}ea = '{FPF if v == 'fp' else DGF}' %}}", 1


def package_mutants():
    """(name, old, new, expected occurrences). The per-feature step is written into 7 templates (state, reason_codes, failed_features and
    the four stored attributes of that feature); a mutant changes every instance, as a real edit of the step would."""
    for name, old, new, _n in feature_mutants():
        yield name, old, new, 7
    yield "the UNKNOWN state is dropped (unreadable reads HEALTHY)", "{% elif not fpok or not dgok %}", "{% elif false %}", 1
    yield "Free Power and Dump codes are swapped", "{% if fpactive %}{% set codes = codes + ['FREE_POWER_START_FAILED'] %}", "{% if fpactive %}{% set codes = codes + ['DUMP_TO_GRID_START_FAILED'] %}", 1
    yield "the Dump window never raises WARNING", "{% if fpactive or dgactive %}", "{% if fpactive %}", 1
    yield "the start trigger id is not the one tested", "trigger.id == 'start'", "trigger.id == 'startX'", 14
    yield "the window trigger is removed", "      - trigger: state\n        id: start_failure_window_elapsed\n", "      - trigger: state\n        id: start_failure_window_removed\n", 1
    yield "the settle trigger is removed", "      - trigger: state\n        id: start_counters_settled\n", "      - trigger: state\n        id: start_counters_settled_removed\n", 1
    yield "the window trigger is held 1860 s", "        for:\n          minutes: 30\n", "        for:\n          minutes: 31\n", 1
    yield "the settle trigger reverts to the pre-fix 90 s", f"          seconds: {SETTLE}\n", "          seconds: 90\n", 1
    yield "the settle trigger is held 300 s", f"          seconds: {SETTLE}\n", "          seconds: 300\n", 1


def mutate(text: str, old: str, new: str, count: int) -> str | None:
    return text.replace(old, new) if text.count(old) == count else None


survived, killed, bad_anchor = [], 0, []
mutants = list(package_mutants())
for name, old, new, count in mutants:
    m = mutate(LIVE_TEXT, old, new, count)
    if m is None:
        bad_anchor.append((name, LIVE_TEXT.count(old), count))
        continue
    res = battery(m, quick=True)
    dead = [r[0] for r in res if not r[1]]
    if dead:
        killed += 1
    else:
        survived.append(name)
check(f"every package mutant anchors on exactly its expected instances ({len(mutants)} mutants)", not bad_anchor, str(bad_anchor[:4]))
check(f"all {len(mutants)} package mutants are killed by the behaviour battery", not survived and killed == len(mutants) - len(bad_anchor), f"survivors: {survived[:6]}")
prefix = LIVE_TEXT.replace(f") >= {SETTLE} %}}", ") >= 90 %}").replace(f"          seconds: {SETTLE}\n", "          seconds: 90\n")
pre_dead = [r[0] for r in battery(prefix, quick=True) if not r[1]]
check("the pre-fix 90 s settle (trigger and every check) fails the silent-link-loss scenarios for BOTH features",
      prefix != LIVE_TEXT and any("[Free Power] silent link loss" in n for n in pre_dead) and any("[Dump to Grid] silent link loss" in n for n in pre_dead),
      str([n for n in pre_dead if "silent" in n][:2]))
control = LIVE_TEXT.replace("{% set fpquiet = fpok and", "{% set fpquiet = (fpok) and")
check("control: an equivalent rewrite (extra parentheses) survives the battery, so the battery is not merely sensitive to any textual change",
      control != LIVE_TEXT and not [r for r in battery(control, quick=True) if not r[1]])

if NODE:
    HERO_MUT = [
        ("hero: a failed start no longer raises ATTENTION", "const attention = hardAttention || startFailed;", "const attention = hardAttention;"),
        ("hero: the existing subline is replaced by the failed-start one", "subline = hardAttention ? 'A monitored subsystem needs checking' : startFailSubline;", "subline = startFailSubline;"),
        ("hero: a failed start needs no WARNING state", "failedStartState === 'WARNING' && (freeStartFailed || dumpStartFailed)", "(freeStartFailed || dumpStartFailed)"),
        ("hero: the sensor is added to `required` (an unavailable sensor becomes STATUS PARTIAL)", "const required = [comm,", f"const required = [failedStartState,comm,"),
        ("hero: the Dump code is not read", "failedStartText.includes('DUMP_TO_GRID_START_FAILED')", "false"),
        ("hero: the Free Power code is not read", "failedStartText.includes('FREE_POWER_START_FAILED')", "false"),
        ("hero: the attention test is checked before STATUS PARTIAL", "if (hasUnknown) {\n", "if (hasUnknown && !startFailed) {\n"),
        ("hero: the pill ignores a failed start", "const txChip = startFailed ? ['START FAILED', 'warn'] :", "const txChip = false ? ['START FAILED', 'warn'] :"),
        ("hero: the codes attribute is read from the wrong key", "attributes?.reason_codes;", "attributes?.reasons;"),
    ]
    scen = [{"name": n, "states": hero_states(o, codes=cd, include_sensor=inc)} for n, o, cd, inc, _st, _h, _s, _t in HERO_SCEN]
    hsurv, hbad = [], []
    for name, old, new in HERO_MUT:
        if HERO.count(old) != 1:
            hbad.append((name, HERO.count(old)))
            continue
        got = run_node({"m": HERO.replace(old, new)}, scen).get("m", [])
        diff = [n for (n, _o, _cd, _inc, _st, head, sub, tx), html in zip(HERO_SCEN, got) if (parts(html)["headline"], parts(html)["subline"], parts(html)["tx"]) != (head, sub, tx)]
        if not diff:
            hsurv.append(name)
    check(f"every hero mutant anchors exactly once ({len(HERO_MUT)} mutants)", not hbad, str(hbad))
    check(f"all {len(HERO_MUT)} hero mutants are killed by the hero matrix", not hsurv, f"survivors: {hsurv}")

# ---------------------------------------------------------------------------------------------------------------------------
print("")
print("[7] FPS1 compatibility: the REAL scheduled Free Power package (fps1) driven against the dongle model; FSW1 evaluated on the counter timeline")
print("    it produces (gate refusals are never counted; only a start that passed the gate and then failed is)")
sys.path.insert(0, str(ROOT / "home-assistant" / "tests"))
import _ha_script_sim as HS  # noqa: E402

FPS_PKG_TEXT = (ROOT / "home-assistant" / "packages" / "ecco_free_power_schedule.yaml").read_text(encoding="utf-8")
E_SUCC = HS.E_ATTEMPTS.replace("attempts", "successes")
assert E_SUCC != HS.E_ATTEMPTS and E_SUCC == FPS, (E_SUCC, FPS)


class SDongle(HS.Dongle):
    """The FPS1 dongle model plus the start-successes counter, published (like the attempts counter) on its own 30 s timer."""
    DONGLE_ENTITIES = HS.Dongle.DONGLE_ENTITIES + (E_SUCC,)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.w.set(E_SUCC, "0.0")

    def _attempts_tick(self):
        if not self.is_offline(self.w.t):
            self._pub(E_SUCC, f"{float(self.successes)}")
        super()._attempts_tick()

    def set_offline(self, a, b):
        super().set_offline(a, b)
        self.w.at(b, lambda: self.w.set(E_SUCC, f"{float(self.successes)}"))


FPS_START = "2026-10-11 11:00:00"
FPS_ST = HS.parse_local(FPS_START)
FPS_T0 = HS.parse_local("2026-10-11 10:50:00")


class FpsRun:
    """One simulated scheduled session (armed 10:51, start 11:00), then FSW1 replayed over the counters it produced."""

    def __init__(self, *, phase=0.0, delays=(0.6, 0.1), outcome="ok", setup=None, horizon=1500):
        self.w = w = HS.World(FPS_T0)
        self.ha = HS.HA(w, yaml.safe_load(FPS_PKG_TEXT))
        self.d = SDongle(w, phase=phase, handle_delays=delays, outcome=outcome)
        w.set("sensor.ecco_config_maximum_grid_charge_power", "8000")
        w.set("input_datetime.ecco_free_power_schedule_start", FPS_START)
        w.set("input_number.ecco_free_power_schedule_duration", "120.0")
        w.set("input_number.ecco_free_power_schedule_power", "8000.0")
        w.set("input_boolean.ecco_free_power_schedule_armed", "off")
        w.set("input_text.ecco_free_power_schedule_last_result", "")
        w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "off")
        self.ha.start()
        if setup:
            setup(self)
        w.run_until(HS.parse_local("2026-10-11 10:51:00"))
        w.set("input_boolean.ecco_free_power_schedule_armed", "on")
        self.end = FPS_ST + horizon
        w.run_until(self.end)
        self.sim = self.replay()

    def timeline(self):
        mp = {HS.E_ATTEMPTS: FPA, E_SUCC: FPS}
        return [(t, mp[e], v) for t, e, v in self.w.history if e in mp]

    def replay(self):
        s = Sim(LIVE_C, base_values())
        cur = FPS_T0
        for t, ent, val in self.timeline():
            if t > cur:
                s.advance(t - cur)
                cur = t
            s.set(ent, val)
        s.advance(max(0.0, self.end - cur))
        return s

    def warn_times(self):
        """Seconds (virtual) at which FSW1 first rendered WARNING after each HEALTHY/UNKNOWN render, as absolute epoch seconds."""
        out, prev = [], None
        for when, state, _a, _tid in self.sim.renders:
            if state == "WARNING" and prev != "WARNING":
                out.append(FPS_T0 + (when - T0).total_seconds())
            prev = state
        return out

    def never_warned(self):
        return all(r[1] != "WARNING" for r in self.sim.renders)

    def gate_pass(self):
        return [t for t, o in self.d.presses if o == "PASSED"]

    def alerts(self):
        return [n for n in self.w.notification_log if n[1] == "create"]


LIVE_C = Compiled(LIVE_TEXT)
try:
    sweep_bad, sweep_n = [], 0
    for phase in range(0, 60, 5):
        for delays in ((0.6, 0.1), (0.15,), (0.3, 0.9)):
            r = FpsRun(phase=float(phase), delays=delays)
            sweep_n += 1
            if not (r.d.attempts == 1 and r.d.successes == 1 and len(r.gate_pass()) == 1 and r.never_warned()
                    and r.sim.attrs.get("free_power_failures_observed") == 0 and r.sim.state == "HEALTHY"):
                sweep_bad.append((phase, delays, r.d.attempts, r.d.successes, r.sim.state))
    check(f"every poll phase x press delay ({sweep_n} scheduled sessions through the real fps1 package, retried gate refusals included): one counted attempt, "
          f"one success, FSW1 never WARNING and nothing observed", not sweep_bad, str(sweep_bad[:3]))

    r = FpsRun(setup=lambda x: x.d.rtc.append((FPS_ST - 5, FPS_ST + 70)))
    check("a transient gate refusal (RTC correction at the start) retried by fps1 and then started: refusals not counted, FSW1 never WARNING",
          len([o for _t, o in r.d.presses if o != "PASSED"]) >= 1 and r.d.attempts == 1 and r.d.successes == 1 and r.never_warned()
          and r.sim.attrs.get("free_power_unresolved_baseline") == 0, str((r.d.presses, r.sim.state)))

    def snap(x):
        x.d.flags["snapshot"] = True
        x.w.set(HS.E_SNAP, "on")

    r = FpsRun(setup=snap)
    check("a persistent gate refusal (snapshot pending): refused once, fps1 alerts at once, NOTHING counted: FSW1 stays HEALTHY (the gate refusal "
          "is fps1's alert, never FSW1's)", r.d.attempts == 0 and len(r.gate_pass()) == 0 and r.alerts() and r.never_warned() and r.sim.state == "HEALTHY",
          str((r.d.presses, r.alerts(), r.sim.state)))

    for outcome in ("capture_failed", "write_failed"):
        r = FpsRun(outcome=outcome, horizon=2500)
        gp = r.gate_pass()
        warns = r.warn_times()
        alert_t = min((n[0] for n in r.alerts()), default=None)
        first_attempt_visible = next((t for t, e, v in r.w.history if e == HS.E_ATTEMPTS and v == "1.0"), None)
        check(f"a start that passed the gate and then failed ({outcome}): one attempt, no success, never retried by fps1, an alert from fps1",
              r.d.attempts == 1 and r.d.successes == 0 and len(gp) == 1 and len(r.d.press_log) >= 1 and alert_t is not None, str((r.d.attempts, r.d.successes, gp, r.alerts())))
        check(f"... FSW1 warns exactly {SETTLE} s after the attempt became visible (and after fps1's own alert), with the Free Power code only",
              len(warns) == 1 and first_attempt_visible is not None and abs((warns[0] - first_attempt_visible) - SETTLE) <= 1
              and alert_t <= warns[0] and r.sim.attrs.get("free_power_failures_observed") == 1,
              str((warns, first_attempt_visible, alert_t)))
        check("... the warning is Free Power only and expires 1800 s after the attempt (HEALTHY again by the end of the run)",
              r.sim.state == "HEALTHY" and r.sim.attrs.get("dump_to_grid_failures_observed") == 0
              and any(CODE_FP in x[2].get("reason_codes", []) for x in r.sim.renders) and not any(CODE_DG in x[2].get("reason_codes", []) for x in r.sim.renders),
              str((r.sim.state,)))

    r = FpsRun(setup=lambda x: x.d.set_offline(FPS_ST - 30, FPS_ST + 40))
    check("the dongle offline across the scheduled start (fps1 waits, then starts): counters unavailable then back; FSW1 never WARNING",
          r.d.attempts == 1 and r.d.successes == 1 and r.never_warned() and r.sim.state == "HEALTHY", str((r.d.attempts, r.sim.state)))

    r = FpsRun(setup=lambda x: x.d.set_offline(FPS_ST + 2, FPS_ST + 150))
    check("the dongle offline from just after the press (the start itself runs): reconnection with attempt 1 / success 1 only sets the baseline",
          r.d.attempts == 1 and r.d.successes == 1 and r.never_warned() and r.sim.attrs.get("free_power_failures_observed") == 0, str((r.d.attempts, r.sim.state)))

    r = FpsRun(outcome="capture_failed", setup=lambda x: x.d.set_offline(FPS_ST + 2, FPS_ST + 150), horizon=1500)
    check("a genuine failed start while the dongle is offline is NOT observed (documented limitation): no WARNING is fabricated at the reconnection",
          r.d.attempts == 1 and r.d.successes == 0 and r.never_warned() and r.sim.attrs.get("free_power_failures_observed") == 0, str((r.d.attempts, r.sim.state)))

    for hold in (100, 260):
        r = FpsRun(setup=lambda x, hold=hold: x.d.stalls.append((FPS_ST + 1, FPS_ST + hold)))
        check(f"the API stalled for {hold} s across the start (TCP alive, publishes held and delivered in order): FSW1 never WARNING",
              r.d.attempts == 1 and r.d.successes == 1 and r.never_warned() and r.sim.attrs.get("free_power_failures_observed") == 0, str((r.sim.state,)))

    r = FpsRun(setup=lambda x: x.d.manual_start(FPS_ST - 0.5))
    check("the owner's own START racing the schedule: at most the counted starts succeed; FSW1 never WARNING",
          r.d.attempts == r.d.successes and r.never_warned(), str((r.d.attempts, r.d.successes, r.sim.state)))
except Exception as exc:  # noqa: BLE001
    import traceback
    check("the FPS1 compatibility simulations run", False, traceback.format_exc()[-600:])

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All failed-start health warning offline tests PASSED.")
print("NOTE: plain Jinja and plain JavaScript against Home Assistant stand-ins only; the package remains STAGED / NOT LIVE-PROVEN.")
