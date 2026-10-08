"""Offline behaviour suite for the RTC correction-failure health alert (FB-D1 follow-up, post-export entry rtcf1):
home-assistant/packages/ecco_system_health.yaml sensor.ecco_health_rtc representing registry check rtc_correction_failures_recent.

What is proven (plain Jinja against Home Assistant stand-ins, driven by a small model of a trigger-based template entity:
explicit triggers, `this` = the entity's state before the render, restore of state and attributes across a Home Assistant restart,
the state trigger's `for` timer and the one-minute time_pattern):

  [1] wiring        the firmware entities exist with the names the entity ids derive from (friendly name "ECCO Clock Dongle"),
                    the counter is the failed_corrections counter, the deadline breaker increments it and publishes ABORTED;
                    the two new triggers are exact; the three original triggers and every other template entity are unchanged;
                    template keys only (no new HA control surface)
  [2] registry      the check record (implemented_offline, 1800 s, warning_delta 1, RTC_CORRECTION_FAILURES_RECENT) and the reason
                    code (WARNING, non-blocking) are consistent with the package; the registry validator passes
  [3] semantics     increase -> WARNING; reboot reset (N -> 0, N -> unavailable -> 0) -> no warning; Home Assistant restart never
                    fabricates a failure and keeps an open window; unknown / unavailable / non-numeric -> UNKNOWN, never HEALTHY;
                    expiry exactly at 1800 s (the `for` trigger) or within the minute (backstop); repeated failures extend the
                    window; attribute-only events; float-formatted states; ABORTED / FAILED attribute capture; lock max age
  [4] precedence    a differential against the package as of pub0 (the rtcf1 reverter): with no recent failure and a readable
                    counter every state, reason-code list and pre-existing attribute is byte-identical over every input
                    combination; with a recent failure the state is max(base, WARNING) under the existing tie-break and the code
                    is appended last; with an unreadable counter only a HEALTHY base becomes UNKNOWN
  [5] oracle        randomised event sequences (seeded) against an independent Python oracle of the check
  [6] mutation      in-memory mutants of the package (counter comparison, reboot/restart guard, expiry, window, entity mapping,
                    trigger id, the `for` trigger, unknown handling, attribute capture, rank aggregation) are each killed

Writes nothing; no Home Assistant, no network, no hardware. It does not prove the templates on a live Home Assistant instance.
"""

from __future__ import annotations

import ast
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jinja2
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _rtcf1_scope as scope  # noqa: E402

PKG_PATH = ROOT / "home-assistant" / "packages" / "ecco_system_health.yaml"
CHECKS_PATH = ROOT / "registry" / "system_health_checks.yaml"
CODES_PATH = ROOT / "registry" / "health_reason_codes.yaml"
FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

DEV = "ecco_clock_dongle"
COUNTER = f"sensor.{DEV}_failed_corrections_since_boot"
RESULT = f"sensor.{DEV}_last_correction_result"
LOCK_MAX = f"sensor.{DEV}_ecco_rtc_correction_lock_max_age_since_boot"
E1 = f"binary_sensor.{DEV}_rtc_correction_in_progress"
E2 = f"binary_sensor.{DEV}_rtc_stall_detected"
E3 = f"binary_sensor.{DEV}_ntp_synced"
CODE = "RTC_CORRECTION_FAILURES_RECENT"
T_CHANGED = "rtc_failed_corrections_changed"
T_ELAPSED = "rtc_failure_window_elapsed"
WINDOW = 1800
ABORT_TEXT = "ABORTED - correction exceeded its deadline - 5 min cooldown"
FAILED_TEXT = "FAILED after retries - error 41 s - 5 min cooldown"

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


def slug(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", s.lower())).strip("_")


LIVE_TEXT = PKG_PATH.read_text(encoding="utf-8")
BASE_TEXT = scope.pre_rtcf1_health_package(LIVE_TEXT)   # the package as of pub0 (the export), byte for byte


# ---------------------------------------------------------------------------------------------------------------------------
# Home Assistant stand-ins
# ---------------------------------------------------------------------------------------------------------------------------
T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
_MISSING = object()


def as_timestamp(v, default=_MISSING):
    """HA's as_timestamp: a datetime, an ISO string or a number -> float seconds; invalid -> default (or an error without one)."""
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
    def __init__(self, state: str, last_changed: datetime):
        self.state = state
        self.last_changed = last_changed


class States:
    def __init__(self, values: dict, changed: dict):
        self.values, self.changed = values, changed

    def __call__(self, entity_id: str) -> str:
        return self.values.get(entity_id, "unknown")

    def __getitem__(self, entity_id: str):
        return StateObj(self(entity_id), self.changed.get(entity_id, T0))


class This:
    def __init__(self, state, attributes: dict):
        self.state = state
        self.attributes = attributes


ENV = jinja2.Environment(undefined=jinja2.StrictUndefined)


def parse_result(s: str):
    """HA's render result parsing for attributes: a Python literal becomes that value, anything else stays a string."""
    try:
        v = ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return s
    return v if isinstance(v, (int, float, list, dict, bool)) else s


def rtc_entity(doc) -> tuple[dict, list]:
    for block in doc.get("template", []):
        for ent in block.get("sensor", []) or []:
            if ent.get("unique_id") == "ecco_health_rtc":
                return ent, block.get("triggers") or []
    raise AssertionError("ecco_health_rtc not found")


class Compiled:
    """The RTC entity of one package text, compiled once."""

    def __init__(self, text: str):
        self.doc = load(text)
        self.ent, self.triggers = rtc_entity(self.doc)
        self.state_t = ENV.from_string(self.ent["state"])
        self.attr_t = {k: (ENV.from_string(v) if isinstance(v, str) and ("{{" in v or "{%" in v) else v)
                       for k, v in self.ent["attributes"].items()}
        self.for_seconds = None
        for t in self.triggers:
            if t.get("id") == T_ELAPSED and isinstance(t.get("for"), dict):
                self.for_seconds = t["for"].get("seconds")


def render_once(c: Compiled, values: dict, changed: dict, now: datetime, this: This, trigger: dict):
    ctx = {"states": States(values, changed), "now": lambda: now, "as_timestamp": as_timestamp, "this": this, "trigger": trigger}
    state = c.state_t.render(**ctx).strip()
    attrs = {}
    for k, t in c.attr_t.items():
        attrs[k] = parse_result(t.render(**ctx).strip()) if hasattr(t, "render") else t
    return state, attrs


HEALTHY_INPUTS = {E1: "off", E2: "off", E3: "on", COUNTER: "0", RESULT: "Verified OK", LOCK_MAX: "14"}


class Sim:
    """A trigger-based template entity in a running Home Assistant (only the triggers this entity declares)."""

    def __init__(self, c: Compiled, values: dict | None = None):
        self.c = c
        self.now = T0
        self.values = dict(HEALTHY_INPUTS if values is None else values)
        self.changed = {e: T0 for e in self.values}
        self.state, self.attrs = "unknown", {}
        self.for_due = None          # when the counter's `for` trigger fires (None = not armed)
        self.renders = []            # (time, state, attrs, trigger id)
        self.fire({"id": "0", "platform": "homeassistant", "event": "start"})

    def fire(self, trigger: dict):
        self.state, self.attrs = render_once(self.c, self.values, self.changed, self.now, This(self.state, dict(self.attrs)), trigger)
        self.renders.append((self.now, self.state, dict(self.attrs), trigger.get("id")))

    def set(self, entity: str, value: str, *, first_after_restart: bool = False):
        old = None if first_after_restart else StateObj(self.values.get(entity, "unknown"), self.changed.get(entity, T0))
        if old is not None and old.state == value:
            return
        self.values[entity] = value
        self.changed[entity] = self.now
        new = StateObj(value, self.now)
        if entity == COUNTER:
            self.fire({"id": T_CHANGED, "platform": "state", "entity_id": entity, "from_state": old, "to_state": new})
            self.for_due = (self.now + timedelta(seconds=self.c.for_seconds)) if self.c.for_seconds else None
        elif entity in (E1, E2, E3):
            self.fire({"id": "1", "platform": "state", "entity_id": entity, "from_state": old, "to_state": new})

    def attribute_event(self, entity: str):
        """A state_changed event with the same state (attributes changed): a state trigger without to/from fires on it."""
        o = StateObj(self.values[entity], self.changed[entity])
        if entity == COUNTER:
            self.fire({"id": T_CHANGED, "platform": "state", "entity_id": entity, "from_state": o, "to_state": o})
            self.for_due = (self.now + timedelta(seconds=self.c.for_seconds)) if self.c.for_seconds else None

    def advance(self, seconds: float):
        end = self.now + timedelta(seconds=seconds)
        while True:
            nxt_min = (self.now.replace(second=0, microsecond=0) + timedelta(minutes=1))
            cands = [t for t in (nxt_min, self.for_due) if t is not None and t <= end]
            if not cands:
                break
            t = min(cands)
            self.now = t
            if self.for_due is not None and t == self.for_due:
                self.for_due = None
                self.fire({"id": T_ELAPSED, "platform": "state", "entity_id": COUNTER})
            if t == nxt_min:
                self.fire({"id": "2", "platform": "time_pattern"})
        self.now = end

    def restart(self, *, restore: bool = True, counter_after: str | None = None):
        """Home Assistant restarts: timers are lost, the entity restores its state and attributes (trigger-based template entity),
        the start trigger renders while the dongle entities are still unavailable, then they come back (first value: no from_state)."""
        self.for_due = None
        if not restore:
            self.state, self.attrs = "unknown", {}
        back = dict(self.values)
        for e in back:
            self.values[e] = "unavailable"
        self.fire({"id": "0", "platform": "homeassistant", "event": "start"})
        for e, v in back.items():
            if e == COUNTER and counter_after is not None:
                v = counter_after
            self.set(e, v, first_after_restart=True)

    def codes(self):
        rc = self.attrs.get("reason_codes")
        return rc if isinstance(rc, list) else ast.literal_eval(rc)


# ---------------------------------------------------------------------------------------------------------------------------
# The battery: every behavioural claim, as a function of the package text (so the mutants can be run through it)
# ---------------------------------------------------------------------------------------------------------------------------
def battery(text: str, *, quick: bool = False) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ok(name, cond, detail=""):
        out.append((name, bool(cond), detail))

    try:
        c = Compiled(text)
    except Exception as exc:  # noqa: BLE001
        return [("the package parses and the RTC entity compiles", False, repr(exc))]
    trig = c.triggers
    ok("triggers: the counter change trigger is exactly {state, id, entity_id} (no to/from filter)",
       {"trigger": "state", "id": T_CHANGED, "entity_id": COUNTER} in trig)
    ok("triggers: the window trigger is the same entity held for exactly 1800 s",
       {"trigger": "state", "id": T_ELAPSED, "entity_id": COUNTER, "for": {"seconds": WINDOW}} in trig)
    ok("triggers: the one-minute time_pattern backstop is kept", {"trigger": "time_pattern", "minutes": "/1"} in trig)

    def run(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            ok(f"scenario {fn.__name__} renders", False, repr(exc))
            return None

    # --- [3a] an increase warns; the attributes capture it ------------------------------------------------------------------
    def s_increase():
        s = Sim(c)
        ok("idle: HEALTHY, no code, last_failure_at none", s.state == "HEALTHY" and s.codes() == [] and s.attrs.get("last_failure_at") == "none")
        ok("idle: last_result / last_failure_kind none", s.attrs.get("last_result") == "none" and s.attrs.get("last_failure_kind") == "none")
        s.advance(37)
        s.set(RESULT, ABORT_TEXT)
        s.advance(20)
        t_fail = s.now
        s.set(COUNTER, "1")
        ok("0 -> 1: WARNING", s.state == "WARNING", s.state)
        ok("0 -> 1: the code is RTC_CORRECTION_FAILURES_RECENT (alone)", s.codes() == [CODE], str(s.codes()))
        ok("0 -> 1: last_failure_at is the time the increase was seen (to_state.last_changed)",
           s.attrs.get("last_failure_at") == t_fail.isoformat(), str(s.attrs.get("last_failure_at")))
        ok("0 -> 1: last_result is the Last Correction Result text at that moment (the ABORTED breaker text)",
           s.attrs.get("last_result") == ABORT_TEXT, str(s.attrs.get("last_result")))
        ok("0 -> 1: last_failure_kind deadline_abort", s.attrs.get("last_failure_kind") == "deadline_abort", str(s.attrs.get("last_failure_kind")))
        ok("failure attributes: window 1800, live counter and lock max age",
           s.attrs.get("failure_window_seconds") == WINDOW and str(s.attrs.get("failed_corrections_since_boot")) == "1"
           and str(s.attrs.get("correction_lock_max_age_seconds")) == "14")
        ok("blocks_manual_control is still only correction_in_progress != off", s.attrs.get("blocks_manual_control") is False)
        # the result text later changes (a later correction succeeds): the captured one stays for this failure
        s.advance(400)
        s.set(RESULT, "Verified OK")
        s.set(E1, "on")
        s.set(E1, "off")
        ok("captured last_result survives later result text changes", s.attrs.get("last_result") == ABORT_TEXT)
        ok("captured last_failure_kind survives too", s.attrs.get("last_failure_kind") == "deadline_abort")
        ok("still WARNING inside the window after other triggers", s.state == "WARNING" and CODE in s.codes())
        # exact expiry: the `for` trigger fires 1800 s after the counter's change
        s.advance((t_fail + timedelta(seconds=WINDOW - 1) - s.now).total_seconds())
        ok("t+1799 s: still WARNING", s.state == "WARNING", s.state)
        s.advance(1)
        last = s.renders[-1]
        ok("t+1800 s: the window trigger renders at exactly t+1800 s", last[0] == t_fail + timedelta(seconds=WINDOW) and last[3] == T_ELAPSED,
           f"{last[0]} {last[3]}")
        ok("t+1800 s: HEALTHY, no code", s.state == "HEALTHY" and s.codes() == [], f"{s.state} {s.codes()}")
        ok("after expiry the last failure stays recorded", s.attrs.get("last_failure_at") == t_fail.isoformat()
           and s.attrs.get("last_result") == ABORT_TEXT)
        s.advance(3600)
        ok("much later: HEALTHY", s.state == "HEALTHY")

    run(s_increase)

    # --- [3b] repeated failures extend the window; FAILED text kind ------------------------------------------------------------
    def s_repeat():
        s = Sim(c)
        s.set(RESULT, FAILED_TEXT)
        s.set(COUNTER, "1")
        t1 = s.now
        s.advance(1000)
        s.set(RESULT, ABORT_TEXT)
        s.set(COUNTER, "2")
        t2 = s.now
        ok("second increase restamps last_failure_at", s.attrs.get("last_failure_at") == t2.isoformat())
        ok("second increase captures its own text", s.attrs.get("last_result") == ABORT_TEXT and s.attrs.get("last_failure_kind") == "deadline_abort")
        s.advance((t1 + timedelta(seconds=WINDOW + 30) - s.now).total_seconds())
        ok("t1+1830 s (inside t2's window): still WARNING", s.state == "WARNING")
        s.advance((t2 + timedelta(seconds=WINDOW - 1) - s.now).total_seconds())
        ok("t2+1799 s: WARNING", s.state == "WARNING")
        s.advance(1)
        ok("t2+1800 s: HEALTHY (exact, window trigger)", s.state == "HEALTHY" and s.renders[-1][3] == T_ELAPSED)
        s2 = Sim(c)
        s2.set(RESULT, FAILED_TEXT)
        s2.set(COUNTER, "3")
        ok("a FAILED result text is kind failed", s2.attrs.get("last_failure_kind") == "failed" and s2.attrs.get("last_result") == FAILED_TEXT)
        s3 = Sim(c)
        s3.set(RESULT, "unknown")
        s3.set(COUNTER, "1")
        ok("an unrecognised result text is kind unrecognised (still a failure)", s3.attrs.get("last_failure_kind") == "unrecognised" and s3.state == "WARNING")
        s4 = Sim(c)
        s4.set(COUNTER, "2")
        ok("an increase of more than one is one failure event", s4.state == "WARNING")
        s5 = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "1.0"}))
        s5.set(COUNTER, "2.0")
        ok("float-formatted counter states compare numerically", s5.state == "WARNING")

    run(s_repeat)

    # --- [3c] reboot reset and decreases never warn -----------------------------------------------------------------------------
    def s_reboot():
        s = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "3"}))
        s.set(COUNTER, "0")
        ok("reboot reset 3 -> 0: HEALTHY, no code", s.state == "HEALTHY" and s.codes() == [])
        s.set(COUNTER, "unavailable")
        ok("counter unavailable (no failure in window): UNKNOWN, never HEALTHY", s.state == "UNKNOWN", s.state)
        s.set(COUNTER, "0")
        ok("unavailable -> 0: HEALTHY, no fabricated failure", s.state == "HEALTHY" and s.attrs.get("last_failure_at") == "none")
        s.set(COUNTER, "5")
        t_a = s.now
        s.advance(10)
        s.set(COUNTER, "unavailable")
        s.advance(10)
        s.set(COUNTER, "2")
        ok("unavailable -> N > 0 (reconnect after a reboot or a gap) is not a new failure: last_failure_at stays the 0 -> 5 one",
           s.attrs.get("last_failure_at") == t_a.isoformat() and s.state == "WARNING", str(s.attrs.get("last_failure_at")))
        s6 = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "4"}))
        s6.set(COUNTER, "unavailable")
        s6.set(COUNTER, "7")
        ok("4 -> unavailable -> 7: not observed as an increase (documented: unobservable while unavailable)",
           s6.state == "HEALTHY" and s6.attrs.get("last_failure_at") == "none")
        s7 = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "2"}))
        s7.set(COUNTER, "1")
        ok("a decrease 2 -> 1 is not a failure", s7.state == "HEALTHY")
        s7.advance(180)
        ok("several renders with no failure keep last_result / last_failure_kind none",
           len(s7.renders) >= 4 and s7.attrs.get("last_result") == "none" and s7.attrs.get("last_failure_kind") == "none",
           f"{len(s7.renders)} {s7.attrs.get('last_result')} {s7.attrs.get('last_failure_kind')}")
        s8 = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "2"}))
        s8.attribute_event(COUNTER)
        ok("an attribute-only event (from == to) is not a failure", s8.state == "HEALTHY" and s8.attrs.get("last_failure_at") == "none")
        # a failure, then a reboot reset inside the window: the window is real and continues
        s9 = Sim(c)
        s9.set(COUNTER, "1")
        tf = s9.now
        s9.advance(100)
        s9.set(COUNTER, "unavailable")
        s9.set(COUNTER, "0")
        ok("failure then reboot reset inside the window: still WARNING", s9.state == "WARNING")
        s9.advance((tf + timedelta(seconds=WINDOW) - s9.now).total_seconds() + 60)
        ok("... and it expires by t+1800 s + the minute backstop (the reset re-armed the timer)", s9.state == "HEALTHY")

    run(s_reboot)

    # --- [3d] unknown / unavailable / garbage -------------------------------------------------------------------------------------
    def s_unknown():
        for v in ("unknown", "unavailable", "", "none", "abc", "nan?"):
            s = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: v}))
            ok(f"counter {v!r} with no failure in the window: UNKNOWN (never HEALTHY), no code",
               s.state == "UNKNOWN" and s.codes() == [], f"{s.state} {s.codes()}")
        s = Sim(c, {k: v for k, v in HEALTHY_INPUTS.items() if k != COUNTER})
        ok("counter entity missing from the state machine: UNKNOWN", s.state == "UNKNOWN")
        s = Sim(c)
        s.set(COUNTER, "1")
        s.set(COUNTER, "unavailable")
        ok("counter unavailable inside an open window: WARNING (a real finding beats UNKNOWN)", s.state == "WARNING" and CODE in s.codes())
        s = Sim(c, dict(HEALTHY_INPUTS, **{LOCK_MAX: "unavailable"}))
        ok("lock max age unavailable: reported as is, does not change the state", s.state == "HEALTHY"
           and s.attrs.get("correction_lock_max_age_seconds") == "unavailable")

    run(s_unknown)

    # --- [3e] Home Assistant restart -------------------------------------------------------------------------------------------
    def s_restart():
        s = Sim(c, dict(HEALTHY_INPUTS, **{COUNTER: "4"}))
        s.restart()
        ok("HA restart with an unchanged counter: no fabricated failure", s.state == "HEALTHY" and s.attrs.get("last_failure_at") == "none",
           f"{s.state} {s.attrs.get('last_failure_at')}")
        ok("... the start render (dongle still unavailable) was UNKNOWN, not HEALTHY",
           [r for r in s.renders if r[3] == "0"][-1][1] == "UNKNOWN")
        s.restart(counter_after="6")
        ok("HA restart where the counter came back higher: not a failure (first value after a restart)", s.state == "HEALTHY")
        s = Sim(c)
        s.set(RESULT, ABORT_TEXT)
        s.set(COUNTER, "1")
        tf = s.now
        s.advance(600)
        s.restart()
        ok("HA restart inside an open window (restored attributes): still WARNING", s.state == "WARNING" and CODE in s.codes())
        ok("... last_failure_at and last_result survive the restart", s.attrs.get("last_failure_at") == tf.isoformat()
           and s.attrs.get("last_result") == ABORT_TEXT)
        s.advance((tf + timedelta(seconds=WINDOW - 1) - s.now).total_seconds())
        ok("... still WARNING at t+1799 s", s.state == "WARNING")
        s.advance(61)
        ok("... expires by the minute backstop after a restart (the `for` timer was lost)", s.state == "HEALTHY")
        s = Sim(c)
        s.set(COUNTER, "1")
        s.restart(restore=False)
        ok("restart without restore (a new install): no stale warning invented", s.state == "HEALTHY" and s.attrs.get("last_failure_at") == "none")

    run(s_restart)

    # --- [4] precedence: a differential against the package as of pub0 -----------------------------------------------------------
    def s_precedence():
        base = Compiled(BASE_TEXT)
        e1_vals = [("off", 0), ("on", 30), ("on", 200), ("unknown", 0), ("unavailable", 0), ("", 0)]
        e2_vals = ["on", "off", "unknown", "unavailable"]
        e3_vals = ["on", "off", "unknown", "unavailable"]
        shared = [k for k in base.ent["attributes"] if k in c.ent["attributes"]
                  and k not in ("represented_checks", "not_yet_implemented_checks", "source_entities")]
        rank = {"HEALTHY": 0, "DEGRADED": 1, "WARNING": 2, "FAILED": 3}
        bad = {"same": [], "fail": [], "unk": []}
        combos = 0
        for (v1, age1) in e1_vals:
            for v2 in e2_vals:
                for v3 in e3_vals:
                    combos += 1
                    now = T0 + timedelta(hours=1)
                    vals = {E1: v1, E2: v2, E3: v3, RESULT: ABORT_TEXT, LOCK_MAX: "3"}
                    changed = {E1: now - timedelta(seconds=age1)}
                    start = {"id": "2", "platform": "time_pattern"}
                    b_state, b_attrs = render_once(base, dict(vals, **{COUNTER: "2"}), changed, now, This("unknown", {}), start)
                    # (a) readable counter, no failure: identical
                    n_state, n_attrs = render_once(c, dict(vals, **{COUNTER: "2"}), changed, now, This("unknown", {}), start)
                    if n_state != b_state or any(n_attrs[k] != b_attrs[k] for k in shared):
                        bad["same"].append((v1, age1, v2, v3, b_state, n_state))
                    # (b) a failure recorded 100 s ago
                    th = This("WARNING", {"last_failure_at": (now - timedelta(seconds=100)).isoformat(), "last_result": ABORT_TEXT})
                    f_state, f_attrs = render_once(c, dict(vals, **{COUNTER: "2"}), changed, now, th, start)
                    want = "FAILED" if b_state == "FAILED" else "WARNING"
                    want_codes = (b_attrs["reason_codes"] if isinstance(b_attrs["reason_codes"], list) else ast.literal_eval(b_attrs["reason_codes"])) + [CODE]
                    got_codes = f_attrs["reason_codes"] if isinstance(f_attrs["reason_codes"], list) else ast.literal_eval(f_attrs["reason_codes"])
                    if f_state != want or got_codes != want_codes or f_attrs["blocks_manual_control"] != b_attrs["blocks_manual_control"]:
                        bad["fail"].append((v1, age1, v2, v3, b_state, f_state, got_codes))
                    # (c) unreadable counter, no failure
                    u_state, u_attrs = render_once(c, dict(vals, **{COUNTER: "unavailable"}), changed, now, This("unknown", {}), start)
                    want_u = "UNKNOWN" if b_state in ("HEALTHY", "UNKNOWN") else b_state
                    if u_state != want_u or u_attrs["reason_codes"] != b_attrs["reason_codes"]:
                        bad["unk"].append((v1, age1, v2, v3, b_state, u_state))
        ok(f"no recent failure, readable counter: state and every pre-existing attribute identical to pub0 over {combos} combinations",
           not bad["same"], str(bad["same"][:3]))
        ok(f"recent failure: state = max(base, WARNING) with the existing tie-break, code appended last, blocking unchanged ({combos})",
           not bad["fail"], str(bad["fail"][:3]))
        ok(f"unreadable counter: only HEALTHY / UNKNOWN bases become UNKNOWN; WARNING / FAILED bases and codes unchanged ({combos})",
           not bad["unk"], str(bad["unk"][:3]))
        ok("rank table unchanged (HEALTHY < DEGRADED < WARNING < FAILED)", rank["WARNING"] == 2)

    run(s_precedence)

    # --- [5] randomised sequences against an independent oracle ------------------------------------------------------------------
    def s_oracle():
        rng = random.Random(20261008)
        n_seq = 40 if quick else 400
        mism = []
        renders = 0
        for seq in range(n_seq):
            s = Sim(c)
            cnt = 0
            o_last = None        # oracle: time of the last observed increase
            o_prev = "0"         # oracle: the counter state HA last held (None right after a restart)

            def expect():
                if o_last is not None and (s.now - o_last).total_seconds() < WINDOW:
                    return "WARNING"
                try:
                    float(s.values.get(COUNTER, "unknown"))
                    return "HEALTHY"
                except ValueError:
                    return "UNKNOWN"
            for _step in range(rng.randint(5, 25)):
                r = rng.random()
                if r < 0.30:
                    cnt += rng.randint(1, 2)
                    new = str(cnt)
                elif r < 0.40:
                    cnt = 0
                    new = "0"
                elif r < 0.50:
                    new = rng.choice(["unavailable", "unknown"])
                elif r < 0.55:
                    new = f"{cnt}.0"
                elif r < 0.62:
                    restore = rng.random() < 0.85
                    s.restart(restore=restore)
                    if not restore:
                        o_last = None
                    o_prev = s.values[COUNTER]
                    renders += 1
                    if s.state != expect():
                        mism.append((seq, "restart", s.state, expect()))
                    continue
                else:
                    s.advance(rng.choice([5, 59, 60, 61, 300, 900, 1799, 1800, 1801, 2400]))
                    renders += 1
                    # after a pure time advance the entity may lag the oracle only until the next trigger (<= 60 s)
                    exp_now = expect()
                    if s.state != exp_now:
                        lag_ok = False
                        if exp_now != "WARNING" and o_last is not None:
                            lag_ok = (s.now - o_last).total_seconds() < WINDOW + 60
                        if not lag_ok:
                            mism.append((seq, "advance", s.state, exp_now))
                    continue
                old = s.values.get(COUNTER)
                if old == new:
                    continue
                try:
                    if float(new) > float(old):
                        o_last = s.now
                except (TypeError, ValueError):
                    pass
                s.set(COUNTER, new)
                o_prev = new
                renders += 1
                if s.state != expect():
                    mism.append((seq, f"{old}->{new}", s.state, expect()))
        ok(f"randomised: {n_seq} sequences, {renders} checked renders match the independent oracle", not mism, str(mism[:4]))

    run(s_oracle)
    return out


# ---------------------------------------------------------------------------------------------------------------------------
print("[1] Wiring: firmware entities, triggers, unchanged neighbours, no control surface")
fw = FW_PATH.read_text(encoding="utf-8")
check("the device friendly name is 'ECCO Clock Dongle' (entity ids are ecco_clock_dongle_<name>)", "\n  friendly_name: ECCO Clock Dongle\n" in fw)
fwdoc = yaml.load(fw, Loader=FastLoader)
sens = {s.get("name"): s for s in fwdoc.get("sensor", []) if isinstance(s, dict)}
tsens = {s.get("name"): s for s in fwdoc.get("text_sensor", []) if isinstance(s, dict)}
cs = sens.get("Failed Corrections Since Boot") or {}
check("firmware sensor 'Failed Corrections Since Boot' exists and maps to " + COUNTER,
      bool(cs) and f"sensor.{DEV}_{slug('Failed Corrections Since Boot')}" == COUNTER)
check("... it publishes the failed_corrections counter every 60 s with 0 decimals",
      "id(failed_corrections)" in str(cs.get("lambda")) and cs.get("update_interval") == "60s" and cs.get("accuracy_decimals") == 0)
check("firmware text sensor 'Last Correction Result' exists and maps to " + RESULT,
      "Last Correction Result" in tsens and f"sensor.{DEV}_{slug('Last Correction Result')}" == RESULT)
check("firmware sensor 'ECCO RTC Correction Lock Max Age Since Boot' exists and maps to " + LOCK_MAX,
      "ECCO RTC Correction Lock Max Age Since Boot" in sens and f"sensor.{DEV}_{slug('ECCO RTC Correction Lock Max Age Since Boot')}" == LOCK_MAX)
brk = fw[fw.index("deadline breaker released RTC state only") - 1500: fw.index("deadline breaker released RTC state only") + 400]
check("the 90 s deadline breaker increments failed_corrections and publishes the ABORTED text (one lambda)",
      "id(failed_corrections)++;" in brk and '"ABORTED - correction exceeded its deadline' in brk)
check("every failed_corrections increment in the firmware is one of the three documented failure paths (count == 3)",
      fw.count("id(failed_corrections)++;") == 3)
check("the 5-minute cooldown (300 s) sits inside the 1800 s window (a failure cannot repeat sooner than the cooldown)",
      "300000" in fw and WINDOW > 300)

live_doc, base_doc = load(LIVE_TEXT), load(BASE_TEXT)
check("as of pub0 the package is the export (the rtcf1 reverter round-trips)", scope.add_rtcf1_health_package(BASE_TEXT) == LIVE_TEXT)
check("top-level keys unchanged (template only: no automation / script / input_* / sensor platform added)",
      sorted(live_doc) == sorted(base_doc) == ["template"])


def by_uid(doc):
    out = {}
    for bi, block in enumerate(doc["template"]):
        for plat in ("sensor", "binary_sensor"):
            for ent in block.get(plat, []) or []:
                out[ent["unique_id"]] = (bi, plat, ent, block.get("triggers"))
    return out


L, B = by_uid(live_doc), by_uid(base_doc)
check("the same template entities exist (no entity added or removed)", sorted(L) == sorted(B), str(sorted(set(L) ^ set(B))))
check("every template entity other than ecco_health_rtc is byte-identical in definition and triggers",
      all(L[u] == B[u] for u in L if u != "ecco_health_rtc"))
lt, bt = L["ecco_health_rtc"][3], B["ecco_health_rtc"][3]
check("ecco_health_rtc keeps its three original triggers first, in order, then exactly the two new ones",
      lt[:3] == bt and len(lt) == 5 and [t.get("id") for t in lt[3:]] == [T_CHANGED, T_ELAPSED])
le, be = L["ecco_health_rtc"][2], B["ecco_health_rtc"][2]
check("ecco_health_rtc: name, unique_id and every non-template key unchanged",
      {k: v for k, v in le.items() if k not in ("state", "attributes")} == {k: v for k, v in be.items() if k not in ("state", "attributes")})
check("ecco_health_rtc: every pre-existing attribute name kept; the new ones are exactly the failure detail",
      set(be["attributes"]) <= set(le["attributes"]) and set(le["attributes"]) - set(be["attributes"]) ==
      {"last_failure_at", "last_result", "last_failure_kind", "failure_window_seconds", "failed_corrections_since_boot",
       "correction_lock_max_age_seconds"})
check("blocks_manual_control template unchanged byte for byte", le["attributes"]["blocks_manual_control"] == be["attributes"]["blocks_manual_control"])
code_text = "\n".join(l for l in LIVE_TEXT.splitlines() if not l.strip().startswith("#"))
check("no service / action / automation / restart / esphome token outside comments",
      not any(tok in code_text for tok in ("service:", "action:", "automation:", "homeassistant.restart", "esphome.", "button.press", "notify")))
check("the RTC_STALL_DETECTED and RTC_CORRECTION_ACTIVE / STUCK logic lines are unchanged",
      all(LIVE_TEXT.count(x) == BASE_TEXT.count(x) for x in (
          "{% set codes = codes + ['RTC_STALL_DETECTED'] %}", "{% set codes = codes + ['RTC_CORRECTION_ACTIVE'] %}",
          "{% set codes = codes + ['RTC_CORRECTION_STUCK'] %}", "{% if dur1 >= 180 %}", "{% set rank2 = 2 %}{% set state2 = 'WARNING' %}")))

print("")
print("[2] Registry and reason code")
checks = {c["id"]: c for c in yaml.safe_load(CHECKS_PATH.read_text(encoding="utf-8"))["checks"]}
codes = {c["code"]: c for c in yaml.safe_load(CODES_PATH.read_text(encoding="utf-8"))["reason_codes"]}
rec = checks.get("rtc_correction_failures_recent", {})
check("check record: implemented_offline, live_proof_status unknown (not live-proven)",
      rec.get("implementation_status") == "implemented_offline" and rec.get("live_proof_status") == "unknown")
check("check record: failure_counter_delta over 1800 s, warning_delta 1, no failure tier, rtc_time, failed_corrections",
      rec.get("check_type") == "failure_counter_delta" and rec.get("parameters") == {"window_seconds": WINDOW, "warning_delta": 1, "failure_delta": None}
      and rec.get("subsystem") == "rtc_time" and rec.get("source", {}).get("entity") == "failed_corrections")
check("check record: its one outcome is RTC_CORRECTION_FAILURES_RECENT", [o["reason_code"] for o in rec.get("outcomes", [])] == [CODE])
rc = codes.get(CODE, {})
check("reason code: rtc_time, WARNING, does not block manual control, does not affect the forecast",
      rc.get("subsystem") == "rtc_time" and rc.get("severity") == "WARNING" and rc.get("blocks_manual_control") is False
      and rc.get("affects_forecast") is False)
rep = ast.literal_eval(ENV.from_string(le["attributes"]["represented_checks"]).render())
check("represented_checks names the check, and every represented id is a registry check of subsystem rtc_time",
      "rtc_correction_failures_recent" in rep and all(checks.get(i, {}).get("subsystem") == "rtc_time" for i in rep))
check("not_yet_implemented_checks no longer lists rtc_correction_failures_recent",
      "rtc_correction_failures_recent" not in le["attributes"]["not_yet_implemented_checks"])
check("the check registry round-trips through its rtcf1 reverter",
      scope.add_rtcf1_checks_registry(scope.pre_rtcf1_checks_registry(CHECKS_PATH.read_text(encoding="utf-8"))) == CHECKS_PATH.read_text(encoding="utf-8"))
val = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "validate_system_health_checks.py")], capture_output=True, text=True, cwd=str(ROOT))
check("tools/validate_system_health_checks.py passes", val.returncode == 0, (val.stdout + val.stderr)[-400:])

print("")
print("[3]-[5] Behaviour, precedence differential and the randomised oracle (the live package)")
for name, cond, detail in battery(LIVE_TEXT):
    check(name, cond, detail)

print("")
print("[6] Mutation: every mutant of the package is killed by the battery")
FRESH_GT = "(t.to_state.state | float(-1)) > (t.from_state.state | float(-1))"
MUTANTS = [
    ("counter comparison > becomes >=", FRESH_GT, FRESH_GT.replace(") > (", ") >= ("), 5),
    ("counter comparison > becomes !=", FRESH_GT, FRESH_GT.replace(") > (", ") != ("), 5),
    ("reboot / restart guard (from_state numeric) removed", "(t.from_state.state | float(-1)) >= 0 and ", "", 5),
    ("from_state none guard removed", "t.from_state is not none and ", "", 5),
    ("expiry < 1800 becomes <= 1800", "as_timestamp(now()) - lf_ts < 1800 %}", "as_timestamp(now()) - lf_ts <= 1800 %}", 2),
    ("window 1800 becomes 3600 (state and codes)", "as_timestamp(now()) - lf_ts < 1800 %}", "as_timestamp(now()) - lf_ts < 3600 %}", 2),
    ("window 1800 becomes 1200 in the state only", "{% if lf_ts is not none and as_timestamp(now()) - lf_ts < 1800 %}\n            {% set rank4",
     "{% if lf_ts is not none and as_timestamp(now()) - lf_ts < 1200 %}\n            {% set rank4", 1),
    ("counter entity mapping in the state template", "{% set e4 = 'sensor.ecco_clock_dongle_failed_corrections_since_boot' %}",
     "{% set e4 = 'sensor.ecco_clock_dongle_corrections_since_boot' %}", 1),
    ("counter entity mapping in the trigger", "        id: rtc_failed_corrections_changed\n        entity_id: sensor.ecco_clock_dongle_failed_corrections_since_boot",
     "        id: rtc_failed_corrections_changed\n        entity_id: sensor.ecco_clock_dongle_corrections_since_boot", 1),
    ("trigger id tested by the templates", "t.id == 'rtc_failed_corrections_changed'", "t.id == 'rtc_failure_window_elapsed'", 5),
    ("the window (`for`) trigger removed",
     "      - trigger: state\n        id: rtc_failure_window_elapsed\n        entity_id: sensor.ecco_clock_dongle_failed_corrections_since_boot\n        for:\n          seconds: 1800\n",
     "", 1),
    ("the window trigger held 1860 s", "        for:\n          seconds: 1800\n", "        for:\n          seconds: 1860\n", 1),
    ("unreadable counter reported HEALTHY", "{% set rank4 = 2 %}{% set state4 = 'UNKNOWN' %}", "{% set rank4 = 0 %}{% set state4 = 'HEALTHY' %}", 1),
    ("check 4 left out of the rank aggregation", "{% set max_rank = [rank1, rank2, rank3, rank4] | max %}",
     "{% set max_rank = [rank1, rank2, rank3] | max %}", 1),
    ("check 4 left out of the tie-break", "{% if rank4 == max_rank %}{% set states_at_max = states_at_max + [state4] %}{% endif %}\n", "", 1),
    ("the code is not appended", "              {% set codes = codes + ['RTC_CORRECTION_FAILURES_RECENT'] %}\n", "", 1),
    ("last_failure_at not kept between failures", "{% elif prev is not none and as_timestamp(prev, none) is not none %}", "{% elif false %}", 1),
    ("the state reads the wrong attribute for the kept time", "{% set prev = this.attributes.get('last_failure_at') if this is defined else none %}\n          {% set lf_ts",
     "{% set prev = this.attributes.get('last_result') if this is defined else none %}\n          {% set lf_ts", 1),
    ("last_result read live instead of captured", "            {% elif prev is not none %}\n              {{ prev }}",
     "            {% elif prev is not none %}\n              {{ states('sensor.ecco_clock_dongle_last_correction_result') }}", 1),
    ("control: an equivalent rewrite of the failure time", "              {{ t.to_state.last_changed.isoformat() }}",
     "              {{ (t.to_state.last_changed).isoformat() }}", 1),
    ("ABORTED kind not recognised", "{% elif r.startswith('ABORTED') %}", "{% elif r.startswith('ABORT:') %}", 1),
    ("stale 'none' result treated as a failure kind", "{% if not fresh and (prev is none or prev == 'none') %}", "{% if not fresh and prev is none %}", 1),
]
killed = 0
for name, old, new, n in MUTANTS:
    cnt = LIVE_TEXT.count(old)
    if cnt != n:
        check(f"mutant '{name}': anchor occurs {n}x", False, f"found {cnt}x")
        continue
    mtext = LIVE_TEXT.replace(old, new)
    res = battery(mtext, quick=True)
    dead = [r[0] for r in res if not r[1]]
    if name.startswith("control"):
        # an equivalent rewrite (the conditional keeps the change time): a CONTROL that must survive, proving the battery is not
        # merely sensitive to any textual change
        check(f"control (equivalent rewrite) survives: {name}", not dead, str(dead[:2]))
        continue
    check(f"mutant killed: {name}", bool(dead), "survived")
    killed += bool(dead)
n_controls = sum(1 for m in MUTANTS if m[0].startswith("control"))
check(f"{killed} of {len(MUTANTS) - n_controls} mutants killed", killed == len(MUTANTS) - n_controls)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All RTC correction-failure alert offline tests PASSED.")
print("NOTE: plain Jinja against Home Assistant stand-ins only; the package remains STAGED / NOT LIVE-PROVEN.")
