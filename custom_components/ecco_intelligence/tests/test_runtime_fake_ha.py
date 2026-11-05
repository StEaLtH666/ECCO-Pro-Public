#!/usr/bin/env python3
"""L2: the BUILT integration kit under the stand-in Home Assistant (_fake_ha implements only the allowlisted modules).

Scenarios (each ends with: zero write attempts of any kind, no stand-in violation, the configuration tree unchanged except
under ecco/intelligence/state/). The world is set between ticks without state_changed events, as before A23, so the
coordinator's one state listener never fires here and these scenarios pin the tick's own rules (which govern whenever the
poll text stops moving); the poll-driven refresh is test_runtime_poll_phase.py's:
  setup / unload / disable / re-enable (one timer, no bus listener, exactly one state listener: on the mapped telemetry
  poll text, removed on unload; none when no poll text is mapped); HA not yet started (the grace starts at
  homeassistant_started);
  restart in the middle of a run (the interrupted run records nothing; no duplicate scorecard rows);
  an engine exception -> SELF_TEST_FAILED, every item state None, the last values only in last_good; the exception's
  message appears in no state, attribute, recorder row, self-test value or diagnostics download (only its type);
  a time-budget overrun -> SELF_TEST_FAILED with the reason, its late result discarded;
  an engine thread that hangs -> STALE through the one-minute timer, every item None, last values only in last_good;
  an injected result with no valid_until (the real cycle always sets one, at most 900 s ahead, and goes STALE then) with
  a hung next run -> STALE once it is older than PROPOSED_RESULT_MAX_AGE_S (the defensive age rule);
  a second run never starts while one is in flight;
  owner-record decisions on fresh inputs -> charge_target OK with a number (so the withholding checks below are not
  vacuous); across two hours of minute ticks no entity holds a number, and fresh is never on, at any moment past its
  valid_until (the payloads are mapped as of the next tick); next_run_at is the next schedule slot on every computed and
  STALE envelope;
  flapping and stale inputs -> BLOCKED, the numbers withheld; a caller / quality freshness disagreement -> BLOCKED;
  recorder gaps and a failing recorder read -> BLOCKED (no crash);
  the 25 h and 23 h nights: the schedule (every full hour plus 21:30 Europe/London) and the I-D9 gate;
  refresh before expiry (INTELLIGENCE_FOUNDATION_CONTRACT.md 13.4): the runtime margin equals the engine's (drift test);
  three simulated hours on fresh inputs never go STALE after the first result (no STALE status row in the recorder, so not
  even for the length of one cycle: A32), statistics are read once per slot and the
  scorecard records once per slot while refreshes run between; next_run_at lies between generated_at and valid_until;
  the published state and attributes stay exactly the contract mapping, and Home Assistant's recorder (as the stand-in
  models it) stores no timestamp-only attribute, so state writes, states rows and attributes rows per hour are measured
  and an unchanged refresh adds no attributes row (A17); only the entities whose payload changed are written; the CPU
  guard suspends refreshes (slot cycles continue) and lifts; a job that raises is retried exactly once after 300 s, then
  slot cycles only; a hanging refresh blocks further refreshes; a time-budget overrun gets no refresh before the next
  slot; a result published STALE at once backs off 60, 120, 240, 300 s; cached recorder rows ending before the slot's
  hour are read again once 300 s after the slot, and a failed read at most every 600 s; an item the engine BLOCKED
  INPUT_EXPIRING starts a refresh at the next tick (next_run_at the refresh floor) until no item is; V-4: a frozen
  poll text past the liveness bound blocks the dongle items with no CALLER_FRESHNESS_DISAGREES while the history-only items keep their
  numbers; a helper that is never rewritten stays BLOCKED (INPUT_NOT_FRESH); the configuration-poll text has its own
  liveness memory and its change time reaches the engine job; last_cycle_timing / cycle_stats in the diagnostics (T1);
  A50: every recorder read is parsed once, the slot's cache keeps its image and every other cycle reuses the parsed
  history; a refused read keeps none (no history until the next read is parsed); cycle_stats keeps at least 4800 runs
  (more than the 72 h acceptance can start), in a bounded deque, and the full download stays JSON, small and redacted;
  supervision steady while the poll text moves (site_decisions puts supervision in DONGLE_READINGS, WP-1);
  every decision OPEN -> every gated item without a number; the example profile as the site file -> the same;
  the pause helper on -> PAUSED and nothing computed; the pause helper missing -> not paused, pause_control MISSING,
  self-test WARN; the pause helper turned on while a cycle is in flight (with and without a tick in between) -> PAUSED,
  the result discarded, no number and no scorecard row; a failure published while the helper is on (a time-budget
  overrun) -> PAUSED; an entity id collision ('_2') -> SELF_TEST_FAILED; a contract entity Home Assistant never adds
  (e.g. disabled in the registry) -> SELF_TEST_FAILED and nothing computed; one entity whose state write raises -> every
  other entity still follows (SELF_TEST_FAILED, ENTITY_WRITE), and the minute tick never raises.
L3 (the isolated test Home Assistant) and L4 (the site) are separate levels and are not attempted here. Plain script;
exits 1 on any failure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
PREFIX = "ecco_intel_l2_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
COORD = __import__("importlib").import_module("custom_components.ecco_intelligence.coordinator")
VEN_CYCLE = __import__("importlib").import_module("custom_components.ecco_intelligence._vendor.intelligence.shadow_cycle")
DIAG = __import__("importlib").import_module("custom_components.ecco_intelligence.diagnostics")
PAUSE_ID = "input_boolean.ecco_intel_paused"
ITEM_KEYS = C.ADVICE_ITEMS + C.FORECAST_ITEMS
SD = __import__("importlib").import_module("custom_components.ecco_intelligence._vendor.intelligence.site_decisions")
DONGLE_ITEMS = tuple(k for k in H.gated_keys(C) if set(SD.REQUIRED_SIGNALS.get(k, ())) & set(SD.DONGLE_SIGNALS))
VEN_Q = __import__("importlib").import_module("custom_components.ecco_intelligence._vendor.intelligence.quality")
CONST = __import__("importlib").import_module("custom_components.ecco_intelligence.const")
ENGINE_LINK = __import__("importlib").import_module("custom_components.ecco_intelligence.runtime.engine_link")
HA_OWN = {"friendly_name", "unit_of_measurement", "device_class", "options"}
TS_ONLY = ("generated_at", "valid_until", "next_run_at")
PENDING: list[str] = []


class Scn:
    def __init__(self, name, profile, *, now=NOW, stats_days=30, pause="off", grace=120.0, seed=True, stats=None,
                 running=True, pre=None):
        self.name = name
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, now)
        # these scenarios set the world between ticks without state_changed events, as before A23: the coordinator's
        # state listener (registered, pinned below) never fires, so they pin the tick's own rules, which govern whenever
        # the poll text stops moving. The poll-driven refresh is exercised with events in test_runtime_poll_phase.py.
        self.hass.states.events = False
        if not running:
            self.hass.state = h.mods["homeassistant.core"].CoreState.starting
        H.write_site(self.cfg, profile)
        self.pause = pause
        self.frozen_poll: str | None = None
        self.after_seed = None                 # a callable(scn) run after every re-seed (a scenario's own entities)
        if seed:
            H.seed_fresh_states(self.hass.states, now, pause=pause)
        h.recorder().statistics = stats if stats is not None else H.synthetic_statistics(now, days=stats_days)
        if pre is not None:
            pre(self)
        self.before = H.tree_hashes(self.cfg)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = grace

    def seed(self, **kw):
        H.seed_fresh_states(self.hass.states, h.now, pause=self.pause, **kw)
        if self.frozen_poll is not None:
            self.hass.states.seed(H.eid("sensor", "last_telemetry_update"), self.frozen_poll)
        if self.after_seed is not None:
            self.after_seed(self)

    def advance(self, seconds=60.0, n=1, settle=10.0, reseed=True, **kw):
        for _ in range(n):
            h.set_now(h.now + timedelta(seconds=seconds))
            if reseed:
                self.seed(**kw)
            h.tick(0, settle=settle)

    def warm(self, settle=20.0):
        """Three ticks with a moving poll text (liveness confirmed), then past the grace: the first cycle runs."""
        self.advance(60, n=3, settle=settle)

    def st(self, key="status"):
        return h.state(key)

    def attrs(self, key="status"):
        s = h.state(key)
        return {} if s is None else dict(s.attributes)

    def items_numeric(self, keys=ITEM_KEYS):
        return [k for k in keys if H.numeric_state(h.state(k))]

    def close(self, unload=True):
        if unload and self.c is not None and not self.c.closed:
            h.unload(self.entry)
        after = H.tree_hashes(self.cfg)
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)
                         and not k.startswith("ecco/intelligence/state/"))
        check(f"{self.name}: zero write attempts", not self.hass.write_attempts, str(self.hass.write_attempts[:3]))
        check(f"{self.name}: no stand-in violation", not self.hass.violations, str(self.hass.violations[:3]))
        check(f"{self.name}: the configuration tree changed only under ecco/intelligence/state/", not changed, str(changed[:3]))


def pv_ok_cycle(*, value=4.2, valid_h=1.0, report=None, block=None, sleep=0.0, error=None, calls=None, started=None):
    """An injected run_cycle built ONLY from the contract constructors of the kit: pv_tomorrow OK (no decision gates it),
    everything else BLOCKED. Options: block on an Event, sleep, raise, attach a scorecard report, signal `started`."""
    def run(inputs):
        if calls is not None:
            calls.append(inputs.now)
        if started is not None:
            started.set()
        if block is not None:
            block.wait(60)
        if sleep:
            time.sleep(sleep)
        if error is not None:
            raise error
        bl = (("TEST_BLOCK", "synthetic block"),)
        items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
        fc = (C.ForecastView("predicted_day_load", C.ItemStatus.BLOCKED, blockers=bl),
              C.ForecastView("pv_tomorrow", C.ItemStatus.OK, value=value, valid_until=inputs.now + timedelta(hours=valid_h)),
              C.ForecastView("predicted_morning_soc", C.ItemStatus.BLOCKED, blockers=bl))
        return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                                   decisions=inputs.decisions, paused=inputs.paused,
                                   valid_until=inputs.now + timedelta(hours=valid_h),
                                   scorecard_report=None if report is None else report(inputs.now))
    return run


def scripted_cycle(step, calls):
    """An injected run_cycle built ONLY from the contract constructors of the kit. Call n does what step(n) returns:
    {"valid_s": validity of the envelope (and of pv_tomorrow, its only OK item), "pv_valid_s": pv_tomorrow's own validity
    when shorter, "block": an Event to wait on, "sleep": seconds, "burn": CPU seconds to spend in the engine thread,
    "shift_clock_s": seconds to move the stand-in wall clock while the job runs, "error": an exception to raise}. Every
    call's inputs.now is appended to `calls`."""
    def run(inputs):
        n = len(calls)
        calls.append(inputs.now)
        sp = step(n) or {}
        if sp.get("block") is not None:
            sp["block"].wait(60)
        if sp.get("sleep"):
            time.sleep(sp["sleep"])
        if sp.get("burn"):
            t0 = time.thread_time()
            while time.thread_time() - t0 < sp["burn"]:
                pass
        if sp.get("shift_clock_s"):
            h.set_now(h.now + timedelta(seconds=sp["shift_clock_s"]))
        if sp.get("error") is not None:
            raise sp["error"]
        vs = float(sp.get("valid_s", 180.0))
        pvs = float(sp.get("pv_valid_s", vs))
        bl = (("TEST_BLOCK", "synthetic block"),)
        items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
        fc = (C.ForecastView("predicted_day_load", C.ItemStatus.BLOCKED, blockers=bl),
              C.ForecastView("pv_tomorrow", C.ItemStatus.OK, value=4.2, valid_until=inputs.now + timedelta(seconds=pvs)),
              C.ForecastView("predicted_morning_soc", C.ItemStatus.BLOCKED, blockers=bl))
        return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                                   decisions=inputs.decisions, paused=inputs.paused,
                                   valid_until=inputs.now + timedelta(seconds=vs))
    return run


def pv_shown() -> bool:
    """The injected cycles' result is on the entities: pv_tomorrow carries its number and fresh is on (the status is
    BLOCKED, as every advice item is)."""
    return h.state("pv_tomorrow").state == "4.2" and h.state("fresh").state == "on"


def blocked_cycle(*, block=None, calls=None):
    """An injected run_cycle (contract constructors only) whose result is BLOCKED with no valid_until at all. The real
    run_cycle never gives that: its BLOCKED result (all-OPEN decisions included) is valid for at most 900 s and goes STALE
    then. Only an envelope without a validity can go STALE by its age alone (PROPOSED_RESULT_MAX_AGE_S), the defensive
    rule this injection exercises."""
    def run(inputs):
        if calls is not None:
            calls.append(inputs.now)
        if block is not None:
            block.wait(60)
        bl = (("TEST_BLOCK", "synthetic block"),)
        items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
        fc = tuple(C.ForecastView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.FORECAST_ITEMS)
        return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                                   decisions=inputs.decisions, paused=inputs.paused, valid_until=None)
    return run


def wait_for(cond, seconds=10.0):
    """Wait for `cond` while the event loop runs (executor results and loop timers are processed meanwhile)."""
    for _ in range(int(seconds * 10)):
        if cond():
            return True
        h.run(asyncio.sleep(0.1))
    return cond()


def report(issued):
    t0 = issued + timedelta(hours=1)
    return {"generated_for": issued.isoformat(), "features": {"synthetic": 1}, "model_version": "intel-test", "config_hash": "t",
            "feature_hash": f"f{issued.timestamp():.0f}", "status": "OK", "confidence": {"overall": 0.5}, "mode": "SHADOW",
            "forecast_records": [{"kind": "load_kwh:day", "unit": "kWh", "horizon_start": t0.isoformat(),
                                  "horizon_end": (t0 + timedelta(hours=24)).isoformat(), "p50": 9.0, "p10": 7.0, "p90": 11.0,
                                  "confidence": 0.5, "explanation": {}}]}


def counts(cfg):
    return h.store_mod.RuntimeStateStore(str(cfg)).counts()


def strings_with_numbers_or_numbers(attrs, skip=()):
    return [k for k, v in attrs.items() if k not in skip and H.has_number(v)]


def stale_input_withheld(scn, signals):
    """(passed, detail) for a result computed while `signals` were not fresh: every gated item whose required signals
    include one of them is BLOCKED and carries no number, charge_target among them with INPUT_NOT_FRESH; an item that rests
    on none of them follows its own inputs' freshness (a history-only item may be OK); the status is the contract's
    derivation (OK exactly when an advice item is OK, else BLOCKED, since charge_target is BLOCKED); data quality not OK."""
    hit = tuple(k for k in H.gated_keys(C) if set(SD.REQUIRED_SIGNALS.get(k, ())) & set(signals))
    statuses = {k: scn.attrs(k).get("status") for k in ITEM_KEYS}
    ok_advice = [k for k in C.ADVICE_ITEMS if statuses[k] == "OK"]
    rc = scn.attrs("charge_target").get("reason_codes", [])
    dq = h.state("data_quality").state
    passed = ("charge_target" in hit and all(statuses[k] == "BLOCKED" for k in hit) and "INPUT_NOT_FRESH" in rc
              and not scn.items_numeric(hit) and scn.st().state == ("OK" if ok_advice else "BLOCKED")
              and dq in ("DEGRADED", "BLOCKED"))
    return passed, f"{scn.st().state} dq={dq} resting={hit} statuses={statuses} codes={rc[:5]}"


try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== setup / unload / disable / re-enable")
    s = Scn("lifecycle", H.site_profile())
    ids = sorted(e for e in s.hass.states._states if e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel")))
    check("setup creates exactly the eleven contract entities", ids == sorted(C.ENTITY_IDS[k] for k in C.INTEGRATION_ENTITY_KEYS),
          str(ids))
    check("the status starts at STARTING with every item unknown", s.st().state == "STARTING" and not s.items_numeric())
    poll_eid = H.READING_MAP["liveness.dongle_poll_changed_at"]["entity"]
    check("one timer (the one-minute tick), no bus listener while HA is running, and exactly one state listener: on the "
          "entity mapped for the telemetry poll text (A23)",
          len([t for t in s.hass.timers if t["active"]]) == 1 and s.hass.bus.listener_count() == 0
          and s.hass.states.change_listeners() == {poll_eid: 1}, str(s.hass.states.change_listeners()))
    s.warm()
    check("the first cycle ran after the grace", s.c.counters["runs_started"] == 1 and s.st().state != "STARTING",
          f"{s.c.counters} {s.st().state}")
    h.unload(s.entry)
    check("unload removes every entity, cancels the timer and removes the state listener",
          not any(e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel")) for e in s.hass.states._states)
          and not any(t["active"] for t in s.hass.timers) and not any(t["active"] for t in s.hass.later)
          and s.hass.states.change_listeners() == {}, str(s.hass.states.change_listeners()))
    n_before = s.c.counters["runs_started"]
    s.advance(3600, n=2)
    check("after unload nothing runs", s.c.counters["runs_started"] == n_before)
    s.entry.disabled_by = "user"
    check("disable: the entry stays unloaded (no entity, no timer)", not any(t["active"] for t in s.hass.timers))
    s.entry.disabled_by = None
    h.setup(s.entry)
    s.c = h.coordinator(s.entry)
    check("re-enable: set up again from STARTING", s.st().state == "STARTING" and s.c.counters["runs_started"] == 0)
    s.close()

    s = Scn("not_started", H.site_profile(), running=False)
    check("HA not started yet: one homeassistant_started listener, no grace running",
          s.hass.bus.listener_count() == 1 and not s.c.diagnostics()["started"])
    s.advance(60, n=4)
    check("... so no cycle runs before HA has started", s.c.counters["runs_started"] == 0)
    s.hass.state = h.mods["homeassistant.core"].CoreState.running
    s.hass.bus.seed_fire("homeassistant_started")
    s.advance(60, n=3, settle=20)
    check("after homeassistant_started + the grace the first cycle runs", s.c.counters["runs_started"] == 1, str(s.c.counters))
    s.hass.state = h.mods["homeassistant.core"].CoreState.stopping
    s.advance(3600, n=2)
    check("while Home Assistant is stopping no cycle starts", s.c.counters["runs_started"] == 1, str(s.c.counters))
    s.hass.state = h.mods["homeassistant.core"].CoreState.running
    s.close()
    s = Scn("unload_before_start", H.site_profile(), running=False)
    h.unload(s.entry)
    check("unload before HA started removes its listeners (no bus or state listener left)",
          s.hass.bus.listener_count() == 0 and s.hass.states.change_listeners() == {})
    s.close(unload=False)

    # -----------------------------------------------------------------------------------------------------------------
    print("== restart in the middle of a run: no duplicate scorecard rows")
    gate = threading.Event()
    calls: list = []
    s = Scn("restart", H.site_profile())
    H.inject(s.c, pv_ok_cycle(report=report, block=gate, calls=calls))
    s.warm(settle=1.0)
    check("the first run is in flight", len(calls) == 1 and s.c.diagnostics()["busy"])
    h.unload(s.entry)
    gate.set()
    time.sleep(0.5)
    h.settle(1.0)
    check("the interrupted run recorded nothing", counts(s.cfg).get("model_runs", 0) == 0, str(counts(s.cfg)))
    for attempt in (1, 2):
        h.setup(s.entry)
        s.c = h.coordinator(s.entry)
        s.c.grace_s = 120
        H.inject(s.c, pv_ok_cycle(report=report))
        s.warm()
        check(f"after restart {attempt} the run completed", s.c.counters["runs_published"] == 1, str(s.c.counters))
        h.unload(s.entry)
    c_ = counts(s.cfg)
    check("one scorecard run for the slot, not two (the second restart in the same slot records nothing)",
          c_.get("model_runs") == 1 and c_.get("ecco_intel_slots") == 1 and c_.get("recommendations") == 0, str(c_))
    s.close(unload=False)

    # -----------------------------------------------------------------------------------------------------------------
    print("== an engine exception -> SELF_TEST_FAILED, all item states None, last values only in last_good")
    s = Scn("exception", H.site_profile())
    H.inject(s.c, pv_ok_cycle())
    s.warm()
    check("a good result first: pv_tomorrow carries its number", h.state("pv_tomorrow").state == "4.2")
    H.inject(s.c, pv_ok_cycle(error=RuntimeError("synthetic engine failure")))
    s.advance(3600, settle=20)
    st = s.st()
    check("the status is SELF_TEST_FAILED naming RUNTIME_EXCEPTION", st.state == "SELF_TEST_FAILED"
          and "RUNTIME_EXCEPTION" in (st.attributes.get("self_test") or {}), str(st.attributes.get("self_test")))
    check("every item, forecast and diagnostic state is None", not s.items_numeric() and h.state("accuracy").state == "unknown"
          and h.state("data_quality").state == "unknown" and h.state("fresh").state == "off")
    lg = st.attributes.get("last_good") or {}
    check("the last values only in the unrecorded last_good", lg.get("values", {}).get("pv_tomorrow") == 4.2
          and not any("last_good" in rec for eid, _st, rec in s.hass.recorder_rows))
    dl = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    hits = H.text_anywhere(s.hass, "synthetic engine failure", {"download": dl, "coordinator": s.c.diagnostics()})
    check("the exception's message appears in no state, attribute, recorder row, self-test value or diagnostics",
          not hits and st.attributes["self_test"].get("RUNTIME_EXCEPTION") == "FAIL: RuntimeError", f"{hits} "
          f"{st.attributes.get('self_test')}")
    H.inject(s.c, lambda inputs: "not an envelope")
    s.advance(3600, settle=20)
    check("an engine that returns something else is a failed self-test too", s.st().state == "SELF_TEST_FAILED")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== a time-budget overrun -> SELF_TEST_FAILED with the reason; the late result is discarded")
    calls = []
    s = Scn("budget", H.site_profile())
    s.c.time_budget_s = 0.3
    H.inject(s.c, pv_ok_cycle(sleep=2.0, calls=calls))
    s.warm(settle=3.0)
    st = s.st()
    check("SELF_TEST_FAILED with CYCLE_TIME_BUDGET", st.state == "SELF_TEST_FAILED"
          and "CYCLE_TIME_BUDGET" in (st.attributes.get("self_test") or {}), f"{st.state} {st.attributes.get('self_test')}")
    check("the run is still in flight (its thread has not ended)", s.c.diagnostics()["busy"])
    s.advance(3600, settle=0.2)
    check("a second run never starts while one is in flight", len(calls) == 1 and s.c.counters["skipped_in_flight"] >= 1,
          f"{len(calls)} {s.c.counters}")
    time.sleep(2.5)
    h.settle(0.5)
    check("the late result is discarded (not published)", s.st().state == "SELF_TEST_FAILED"
          and s.c.counters["late_results_discarded"] == 1 and h.state("pv_tomorrow").state == "unknown", str(s.c.counters))
    s.c.time_budget_s = 120
    H.inject(s.c, pv_ok_cycle(calls=calls))
    s.advance(60, settle=20)
    check("once the thread has ended the next cycle runs and publishes", len(calls) == 2 and h.state("pv_tomorrow").state == "4.2",
          f"{len(calls)} {s.st().state}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== an engine thread that hangs -> STALE via the one-minute timer")
    gate = threading.Event()
    calls = []
    s = Scn("hang", H.site_profile())
    s.c.time_budget_s = 3600
    H.inject(s.c, pv_ok_cycle(valid_h=0.5, calls=calls))
    s.warm()
    check("a valid result first", h.state("pv_tomorrow").state == "4.2" and h.state("fresh").state == "on")
    H.inject(s.c, pv_ok_cycle(valid_h=0.5, block=gate, calls=calls))
    s.advance(55 * 60, settle=0.3)       # the next full hour (and past valid_until): a run starts and hangs
    for _ in range(50):
        if len(calls) == 2:
            break
        time.sleep(0.1)
    check("the second run hangs in flight", len(calls) == 2 and s.c.diagnostics()["busy"], f"{len(calls)}")
    s.advance(60, n=3, settle=0.1)
    st = s.st()
    check("the timer applied STALE although the engine thread hangs", st.state == "STALE", st.state)
    check("STALE: every item state None", not s.items_numeric() and h.state("fresh").state == "off")
    check("STALE: the last values only in the unrecorded last_good",
          (st.attributes.get("last_good") or {}).get("values", {}).get("pv_tomorrow") == 4.2)
    s.advance(3600, n=2, settle=0.1)
    check("while it hangs no further run starts", len(calls) == 2 and s.c.counters["skipped_in_flight"] >= 2, str(s.c.counters))
    h.unload(s.entry)
    gate.set()
    time.sleep(0.3)
    h.settle(0.5)
    check("the hung run's late result after unload is discarded (nothing recorded)", counts(s.cfg).get("model_runs", 0) == 0)
    s.close(unload=False)

    print("== an injected BLOCKED result with no valid_until (never the real cycle's) goes STALE by its age while the next "
          "run hangs")
    gate = threading.Event()
    calls = []
    s = Scn("stale_by_age", H.site_profile())
    s.c.time_budget_s = 3600
    H.inject(s.c, blocked_cycle(calls=calls))
    s.warm()
    env0 = s.c.envelope
    check("a computed BLOCKED result with no valid_until", s.st().state == "BLOCKED" and env0 is not None
          and env0.valid_until is None, s.st().state)
    H.inject(s.c, blocked_cycle(block=gate, calls=calls))
    s.advance(3600, settle=0.3)                 # the next full hour: a run starts and hangs
    check("the next run hangs in flight", wait_for(lambda: len(calls) == 2) and s.c.diagnostics()["busy"], f"{len(calls)}")
    s.advance(3600, settle=0.1)                 # 2 h old: younger than PROPOSED_RESULT_MAX_AGE_S (2 h 15 min)
    check("2 h old: still BLOCKED (younger than the PROPOSED maximum age)", s.st().state == "BLOCKED", s.st().state)
    s.advance(20 * 60, settle=0.1)              # 2 h 20 min old
    check("older than PROPOSED_RESULT_MAX_AGE_S -> STALE although nothing expired", s.st().state == "STALE"
          and (h.now - env0.generated_at).total_seconds() > COORD.PROPOSED_RESULT_MAX_AGE_S, s.st().state)
    check("STALE by age: every item state None", not s.items_numeric() and h.state("fresh").state == "off"
          and h.state("data_quality").state == "unknown")
    h.unload(s.entry)
    gate.set()
    time.sleep(0.3)
    h.settle(0.5)
    s.close(unload=False)

    # -----------------------------------------------------------------------------------------------------------------
    print("== the publish horizon and next_run_at, slot cycles only (refresh switched off; owner-record decisions, fresh "
          "inputs, the real vendored cycle)")
    s = Scn("horizon", H.site_profile(decisions=H.owner_decisions()), now=datetime(2030, 1, 15, 19, 55, tzinfo=UTC))
    s.c.refresh_enabled = False                # pins the slot-only behaviour: STALE comes before the validity ends
    ticks = []
    for _ in range(125):                       # two hours of minute ticks: three hourly runs
        s.advance(60, settle=10)
        nums = {k: s.attrs(k).get("valid_until") for k in ITEM_KEYS if H.numeric_state(h.state(k))}
        a = s.attrs()
        ticks.append((h.now, s.st().state, nums, h.state("fresh").state, a.get("valid_until"), a.get("generated_at"),
                      a.get("next_run_at")))
    nxt_tick = timedelta(seconds=COORD.TICK_S)
    with_numbers = [t for t in ticks if "charge_target" in t[2]]
    check("non-vacuity: charge_target carries a number on some ticks of every hourly run",
          len({COORD.due_slot(t[0]) for t in with_numbers}) >= 2, str(sorted({COORD.due_slot(t[0]).isoformat() for t in with_numbers})))
    overrun = [(t[0].isoformat(), k, vu) for t in ticks for k, vu in t[2].items()
               if vu is None or datetime.fromisoformat(vu) < t[0] + nxt_tick]
    check("no entity holds a number at any moment past its valid_until: every number written at a tick is valid at least "
          "until the next tick", not overrun, str(overrun[:4]))
    fresh_over = [t[0].isoformat() for t in ticks if t[3] == "on" and (t[4] is None or datetime.fromisoformat(t[4]) < t[0] + nxt_tick)]
    check("fresh is never on at any moment past the result's valid_until", not fresh_over and any(t[3] == "on" for t in ticks),
          str(fresh_over[:4]))
    check("a computed result goes STALE (all nulls) before its validity ends, not a tick after it",
          any(t[1] == "STALE" for t in ticks) and all(not t[2] for t in ticks if t[1] == "STALE"))
    want_next = [(t[0].isoformat(), t[1], t[6]) for t in ticks if t[1] not in ("STARTING", "SELF_TEST_FAILED")
                 and t[6] != COORD.next_slot(datetime.fromisoformat(t[5])).isoformat()]
    check("refresh off: next_run_at is the next schedule slot (after generated_at) on every computed and STALE envelope",
          not want_next and any(t[1] == "STALE" for t in ticks) and any(t[1] == "OK" for t in ticks), str(want_next[:4]))
    s.close()

    print("== every decision OPEN (complete fresh inputs, the real vendored cycle) -> every gated item without a number")
    s = Scn("all_open", H.site_profile())
    s.warm()
    st = s.st()
    check("a computed status (not a null-rule one)", st.state in ("BLOCKED", "INSUFFICIENT_DATA", "NO_ADVICE", "OK"), st.state)
    check("every I-D decision is OPEN on the status entity", set(st.attributes["decisions"].values()) == {"OPEN"})
    gated = H.gated_keys(C)
    check("no gated item has a number in its state", not s.items_numeric(gated), str(s.items_numeric(gated)))
    leaks = {k: strings_with_numbers_or_numbers(s.attrs(k)) for k in gated}
    check("... nor in any attribute", not any(leaks.values()), str(leaks))
    sa = strings_with_numbers_or_numbers(s.attrs(), skip=("input_ages", "accuracy", "options"))
    check("the status entity carries numbers only in input_ages / accuracy", not sa, str(sa))
    check("the provenance is OK (nothing recorded, nothing widened)", st.attributes["provenance_ok"] is True)
    env0 = s.c.envelope
    check("the real cycle's BLOCKED result carries a validity of at most 900 s (never none)", env0 is not None
          and env0.valid_until is not None and env0.valid_until <= env0.generated_at + timedelta(seconds=900),
          f"{env0 and env0.generated_at} {env0 and env0.valid_until}")
    r0 = s.c.counters["refresh_runs_started"]
    rows16 = len(s.hass.recorder_rows)
    seen = []
    for _ in range(16):
        s.advance(60)
        seen.append((s.st().state, tuple(s.items_numeric(gated)),
                     tuple(k for k in gated if strings_with_numbers_or_numbers(s.attrs(k)))))
    stale16 = [r for r in s.hass.recorder_rows[rows16:] if r[0] == C.ENTITY_IDS["status"] and r[1] == "STALE"]
    check("... and it is refreshed before that validity ends (refresh before expiry): never STALE over 16 minutes (at "
          "any tick and in any status row of the recorder), a refresh ran, and still no gated number in any state or "
          "attribute",
          all(x[0] != "STALE" and not x[1] and not x[2] for x in seen) and not stale16
          and s.c.counters["refresh_runs_started"] > r0
          and s.c.envelope.generated_at > env0.generated_at, f"{sorted(set(seen))} {len(stale16)} "
          f"{s.c.counters['refresh_runs_started'] - r0}")
    s.c.refresh_enabled = False
    s.advance(60, n=16)
    lc = s.c._last_computed
    check("with refresh off the same kind of result goes STALE once its validity ends, long before the age rule "
          "(PROPOSED_RESULT_MAX_AGE_S) could apply", s.st().state == "STALE" and not s.items_numeric()
          and lc.valid_until <= h.now and (h.now - lc.generated_at).total_seconds() < COORD.PROPOSED_RESULT_MAX_AGE_S,
          f"{s.st().state} {lc.generated_at} {lc.valid_until}")
    s.close()

    print("== the example profile as the site file -> the same")
    ex = json.loads((H.REPO / "intelligence" / "profiles" / "site_profile.example.json").read_text(encoding="utf-8"))
    s = Scn("example_profile", ex)
    s.warm()
    st = s.st()
    check("a computed BLOCKED status (no live input is mapped)", st.state == "BLOCKED", st.state)
    check("no telemetry poll text mapped -> no state listener at all (A23)", s.hass.states.change_listeners() == {},
          str(s.hass.states.change_listeners()))
    check("no item at all has a number (pv_tomorrow has no forecast reading either)", not s.items_numeric())
    leaks = {k: strings_with_numbers_or_numbers(s.attrs(k)) for k in H.gated_keys(C)}
    check("no number in any gated item's attributes", not any(leaks.values()), str(leaks))
    check("the self-test warns that no entity map exists, and ignores the reserve hints",
          s.c.selftest.get("SITE_ENTITY_MAP").level == "WARN"
          and s.c.selftest.get("SITE_HINT_IGNORED_USER_RESERVE_SOC_PCT").level == "INFO")
    check("the example's <placeholder> ids are never queried", all("<" not in i for i in s.c.site.plan.statistic_ids))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== flapping and stale inputs -> BLOCKED (owner-record decisions, the real vendored cycle)")
    s = Scn("inputs", H.site_profile(decisions=H.owner_decisions()))
    s.warm()
    rc = s.attrs("charge_target").get("reason_codes", [])
    check("fresh inputs: charge_target is not blocked by its inputs", "INPUT_NOT_FRESH" not in rc and "LIVENESS_MISSING" not in rc,
          str(rc))
    numeric_fresh = s.items_numeric(DONGLE_ITEMS)
    check("non-vacuity: owner-record decisions on fresh inputs give charge_target OK with a number, its window from the "
          "verified tariff, and predicted_morning_soc a number too (so the withholding checks below can fail)",
          s.attrs("charge_target").get("status") == "OK" and {"charge_target", "predicted_morning_soc"} <= set(numeric_fresh)
          and "CHARGE_WINDOW_FROM_TARIFF" in rc and (s.attrs().get("tariff") or {}).get("provenance") == "VERIFIED_FROM_INTEGRATION",
          f"{s.attrs('charge_target').get('status')} {numeric_fresh} {rc[:6]} {s.attrs().get('tariff')}")
    s.frozen_poll = "2030-01-15 20:09:40"
    s.advance(60, n=17, settle=10)      # the poll text stops moving; > 900 s later the next full hour runs
    s.advance(60, n=40, settle=10)
    ok_, detail = stale_input_withheld(s, SD.DONGLE_SIGNALS)
    check("a frozen poll text -> every item resting on a dongle signal BLOCKED (charge_target: INPUT_NOT_FRESH) without a "
          "number; the status is the contract's (OK only through an item that rests on no dongle signal)", ok_, detail)
    # The items that rest on a dongle signal (site_decisions.REQUIRED_SIGNALS of the kit) are withheld. A history-only item
    # (predicted_day_load, overnight_demand) rests on the recorder history alone and follows that history's own freshness,
    # as the quality layer judges it: it is not covered by this check.
    check("the gated items resting on a dongle signal are charge_target, export_event, dump_to_grid and predicted_morning_soc",
          set(DONGLE_ITEMS) == {"charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"}, str(DONGLE_ITEMS))
    check("... and no number among the items that rest on a dongle signal", not s.items_numeric(DONGLE_ITEMS),
          str(s.items_numeric(H.gated_keys(C))))
    s.frozen_poll = None
    flip = {"n": 0}

    def flap_seed():
        flip["n"] += 1
        s.seed()
        if flip["n"] % 2:
            s.hass.states.seed(H.eid("sensor", "battery_soc"), "unavailable")
            s.hass.states.seed("sensor.test_canonical_battery_soc", "unavailable")
    for _ in range(3):
        h.set_now(h.now + timedelta(seconds=60))
        flap_seed()
        h.tick(0, settle=10)
    h.set_now(h.now.replace(minute=59) + timedelta(minutes=1))
    flip["n"] = 0
    flap_seed()                                    # odd: the SOC is unavailable exactly when the hourly run starts
    h.tick(0, settle=20)
    ok_, detail = stale_input_withheld(s, ("battery.soc",))
    check("a flapping SOC (unavailable at the run) -> every item resting on the SOC BLOCKED (charge_target: INPUT_NOT_FRESH) "
          "without a number; the status is the contract's", ok_, detail)
    s.close()

    s = Scn("flapping_poll", H.site_profile(decisions=H.owner_decisions()))
    s.warm()
    check("non-vacuity: before the flapping, the items resting on a dongle signal carry numbers",
          "charge_target" in s.items_numeric(DONGLE_ITEMS), str(s.items_numeric(DONGLE_ITEMS)))
    text = s.hass.states._states[H.eid("sensor", "last_telemetry_update")].state
    seen = []
    flap_start = h.now
    last_poll = h.now - timedelta(seconds=s.c.diagnostics()["liveness"]["telemetry"]["age_s"])
    bound_at = last_poll + timedelta(seconds=VEN_Q.DQ_PROPOSED.liveness_max_age_s)
    for i in range(70):                    # the poll text flaps unavailable / the same old text: no new poll is seen
        h.set_now(h.now + timedelta(seconds=60))
        s.seed()
        s.hass.states.seed(H.eid("sensor", "last_telemetry_update"), "unavailable" if i % 2 else text)
        h.tick(0, settle=10)
        gen = s.attrs().get("generated_at")
        ct_ = s.attrs("charge_target")
        gen_t = datetime.fromisoformat(gen) if isinstance(gen, str) else None
        vus = [datetime.fromisoformat(s.attrs(k)["valid_until"]) for k in s.items_numeric(DONGLE_ITEMS)]
        seen.append((s.st().state, tuple(ct_.get("reason_codes", [])), tuple(s.items_numeric(DONGLE_ITEMS)),
                     gen_t is not None and gen_t > bound_at, ct_.get("status"),
                     gen_t is not None and flap_start < gen_t <= bound_at, max(vus) if vus else None))
    # The poll text stopped changing when the flapping began (it flaps unavailable / the same old text: no new poll is
    # seen), so every dongle input is fresh only until the liveness bound after the last real poll. Refreshes run while
    # the result expires: a result generated past that bound must be STALE or carry charge_target BLOCKED
    # (INPUT_NOT_FRESH) with no number on any item resting on a dongle signal; a result generated before it may still show
    # those numbers, but never valid past the bound.
    after = [x for x in seen if x[3]]
    ran = [x for x in after if x[0] not in ("STALE",)]
    check("a poll text flapping with a replayed old text -> stale: on every tick whose result was generated past the "
          "liveness bound after the last real poll, the result is STALE or charge_target BLOCKED (INPUT_NOT_FRESH), and no "
          "item resting on a dongle signal shows a number",
          bool(ran) and all(x[0] == "STALE" or (x[4] == "BLOCKED" and "INPUT_NOT_FRESH" in x[1]) for x in after)
          and not any(x[2] for x in after),
          f"{sorted({(x[0], x[4]) for x in after})}; last {seen[-1] if seen else None}")
    early = [x for x in seen if x[5]]
    check("... and a result generated between the flapping's start and that bound never shows a dongle item valid past "
          "the bound", all(x[6] is None or x[6] <= bound_at for x in early),
          f"{[(x[0], x[6] and x[6].isoformat()) for x in early]} bound {bound_at.isoformat()}")
    s.close()

    print("== a caller / quality freshness disagreement -> BLOCKED")
    s = Scn("disagree", H.site_profile(decisions=H.owner_decisions()))

    def lying_caller(inputs):
        fake = tuple((sig, True, 1.0) if sig == "battery.soc" else (sig, fr, age) for sig, fr, age in inputs.caller_assessments)
        return VEN_CYCLE.run_cycle(dataclasses.replace(inputs, caller_assessments=fake))
    H.inject(s.c, lying_caller)
    s.frozen_poll = "2030-01-15 20:00:00"
    s.warm()
    s.advance(60, n=60, settle=10)
    st = s.st()
    check("the quality layer's CALLER_FRESHNESS_DISAGREES is published as BLOCKED",
          st.state == "BLOCKED" and "CALLER_FRESHNESS_DISAGREES" in st.attributes.get("reason_codes", [])
          and h.state("data_quality").state == "BLOCKED", f"{st.state} {st.attributes.get('reason_codes')}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== recorder gaps and a failing recorder read")
    gap_stats = H.synthetic_statistics(NOW, days=30, gap=(200, 100), drop_newest_hours=8)
    s = Scn("recorder_gaps", H.site_profile(decisions=H.owner_decisions()), stats=gap_stats)
    s.warm()
    rc = s.attrs("overnight_demand").get("reason_codes", [])
    check("the newest 8 hours missing -> history stale -> BLOCKED (no crash)",
          s.st().state == "BLOCKED" and "INPUT_NOT_FRESH" in rc and s.c.counters["exceptions"] == 0, f"{s.st().state} {rc}")
    check("the gaps are visible in the cycle diagnostics", s.c.last_diag.get("history_hours", 0) < 30 * 24 - 100)
    h.recorder().fail_with = RuntimeError("synthetic recorder failure")
    s.advance(3600, settle=20)
    check("a failing recorder read -> RECORDER_READ WARN, no history, BLOCKED (not a crash)",
          s.c.selftest.get("RECORDER_READ").level == "WARN" and s.st().state == "BLOCKED", s.st().state)
    h.recorder().fail_with = None
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== the 25 h and 23 h nights")
    for label, start, day_start, day_end, expect in (
            ("autumn", datetime(2026, 10, 24, 12, 0, tzinfo=UTC), datetime(2026, 10, 24, 23, 0, tzinfo=UTC),
             datetime(2026, 10, 26, 0, 0, tzinfo=UTC), 26),
            ("spring", datetime(2027, 3, 27, 12, 0, tzinfo=UTC), datetime(2027, 3, 28, 0, 0, tzinfo=UTC),
             datetime(2027, 3, 28, 23, 0, tzinfo=UTC), 24)):
        calls = []
        s = Scn(f"dst_{label}", H.site_profile(), now=start, stats_days=10)
        H.inject(s.c, pv_ok_cycle(calls=calls))
        s.warm(settle=5)
        steps = int((day_end - h.now).total_seconds() // 900) + 8
        s.advance(900, n=steps, settle=5)
        slots = sorted({COORD.due_slot(t) for t in calls if day_start <= COORD.due_slot(t) < day_end})
        check(f"{label}: {expect} cycles in the {expect - 1} h local day (every full hour plus 21:30)", len(slots) == expect,
              f"{len(slots)}")
        daily = [t for t in slots if t.minute == 30]
        local = [t.astimezone(COORD.LONDON) for t in daily]
        check(f"{label}: the daily cycle is at 21:30 Europe/London", len(daily) == 1 and (local[0].hour, local[0].minute) == (21, 30),
              str(local))
        s.close()
    s = Scn("dst_gate", H.site_profile(decisions=H.owner_decisions(open_ids=("I-D9",))),
            now=datetime(2026, 10, 24, 20, 5, tzinfo=UTC))
    s.warm()
    bad = [k for k in ("charge_target", "overnight_demand", "predicted_morning_soc")
           if s.attrs(k).get("status") != "BLOCKED" or "DECISION_D9_OPEN" not in
           (s.attrs(k).get("reason_codes", []) + [b_["code"] for b_ in s.attrs(k).get("blockers", [])])]
    check("the eve of the 25 h night with I-D9 OPEN: charge_target, overnight_demand, predicted_morning_soc BLOCKED (I-D9)",
          not bad, str(bad))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== the pause helper")
    calls = []
    s = Scn("paused", H.site_profile(), pause="on")
    H.inject(s.c, pv_ok_cycle(calls=calls))
    check("pause on at start -> PAUSED", s.st().state == "PAUSED")
    s.warm()
    s.advance(3600, n=2)
    check("pause on -> PAUSED, nothing computed, every item None", s.st().state == "PAUSED" and not calls and not s.items_numeric()
          and s.st().attributes["pause_control"] == "ON")
    s.pause = "off"
    s.advance(60, settle=20)
    check("pause off -> a cycle runs at once", len(calls) == 1 and s.st().state != "PAUSED", s.st().state)
    s.pause = "on"
    s.advance(60)
    check("pause on again -> PAUSED with the last values in last_good",
          s.st().state == "PAUSED" and (s.attrs().get("last_good") or {}).get("values", {}).get("pv_tomorrow") == 4.2)
    s.close()

    calls = []
    s = Scn("pause_missing", H.site_profile(), pause=None)
    H.inject(s.c, pv_ok_cycle(calls=calls))
    s.warm()
    st = s.st()
    check("pause helper missing -> not paused (the cycle ran)", len(calls) == 1 and st.state != "PAUSED", st.state)
    check("... pause_control MISSING and the reason code PAUSE_CONTROL_MISSING", st.attributes["pause_control"] == "MISSING"
          and "PAUSE_CONTROL_MISSING" in st.attributes["reason_codes"])
    check("... and a self-test WARN", s.c.selftest.get("PAUSE_CONTROL").level == "WARN"
          and s.c.diagnostics()["self_test"]["PAUSE_CONTROL"].startswith("WARN"))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== the pause helper turned on while a cycle is in flight")
    gate, started = threading.Event(), threading.Event()
    calls = []
    s = Scn("pause_mid_cycle", H.site_profile())
    H.inject(s.c, pv_ok_cycle(report=report, block=gate, calls=calls, started=started))
    s.warm(settle=0.5)
    check("a cycle is in flight", wait_for(started.is_set) and s.c.diagnostics()["busy"])
    s.pause = "on"
    s.hass.states.seed(PAUSE_ID, "on")             # turned on mid-cycle, no tick in between
    gate.set()
    check("... the run ends", wait_for(lambda: not s.c.diagnostics()["busy"]))
    h.settle(2.0)
    st = s.st()
    check("helper on when the result arrives -> PAUSED (the result is discarded)", st.state == "PAUSED"
          and st.attributes["pause_control"] == "ON" and s.c.counters["results_discarded_paused"] == 1
          and s.c.counters["runs_published"] == 0, f"{st.state} {s.c.counters}")
    check("... no item carries a number", not s.items_numeric() and h.state("fresh").state == "off")
    check("... and nothing is recorded in the scorecard", counts(s.cfg).get("model_runs", 0) == 0, str(counts(s.cfg)))
    s.pause = "off"
    gate, started = threading.Event(), threading.Event()
    H.inject(s.c, pv_ok_cycle(report=report, block=gate, calls=calls, started=started))
    s.advance(60, settle=0.5)                      # un-paused: a cycle starts at this tick
    check("un-paused: a new cycle is in flight", wait_for(started.is_set) and len(calls) == 2, f"{len(calls)}")
    check("... and the status left PAUSED for STARTING (all nulls) while it runs", s.st().state == "STARTING"
          and s.st().attributes["pause_control"] == "OFF" and not s.items_numeric(), s.st().state)
    s.pause = "on"
    s.advance(30, settle=0.3)                      # a tick while it runs publishes PAUSED
    check("a tick while it runs publishes PAUSED", s.st().state == "PAUSED")
    gate.set()
    check("... the run ends", wait_for(lambda: not s.c.diagnostics()["busy"]))
    h.settle(2.0)
    check("the late result does not overwrite PAUSED; no number; nothing recorded", s.st().state == "PAUSED"
          and not s.items_numeric() and counts(s.cfg).get("model_runs", 0) == 0
          and s.c.counters["results_discarded_paused"] == 2, f"{s.st().state} {s.c.counters} {counts(s.cfg)}")
    s.pause = "off"
    H.inject(s.c, pv_ok_cycle(report=report, calls=calls))
    s.advance(60, settle=20)
    check("pause off -> the next cycle publishes and records once", h.state("pv_tomorrow").state == "4.2"
          and counts(s.cfg).get("model_runs") == 1, f"{s.st().state} {counts(s.cfg)}")
    s.close()

    print("== a failure published while the pause helper is on -> PAUSED (PAUSED > SELF_TEST_FAILED)")
    gate, started = threading.Event(), threading.Event()
    s = Scn("failed_while_paused", H.site_profile(), stats_days=3)
    s.c.time_budget_s = 2.0
    H.inject(s.c, pv_ok_cycle(block=gate, started=started))
    s.warm(settle=0.2)
    check("a cycle is in flight", wait_for(started.is_set))
    s.pause = "on"
    s.hass.states.seed(PAUSE_ID, "on")
    h.settle(6.0)                                  # the 2 s budget runs out while the helper is on (no tick)
    check("the time-budget overrun while paused publishes PAUSED, not SELF_TEST_FAILED",
          s.c.counters["budget_exceeded"] == 1 and s.st().state == "PAUSED", f"{s.st().state} {s.c.counters}")
    gate.set()
    wait_for(lambda: not s.c.diagnostics()["busy"])
    h.settle(0.5)
    s.close()

    print("== a contract entity Home Assistant never adds -> SELF_TEST_FAILED")
    orig_add = h.fake.EntityPlatform._add

    async def skip_status(self, ents):
        await orig_add(self, [e for e in ents if getattr(e, "_key", None) != "status"])
    h.fake.EntityPlatform._add = skip_status
    calls = []
    try:
        s = Scn("entity_missing", H.site_profile())
    finally:
        h.fake.EntityPlatform._add = orig_add
    H.inject(s.c, pv_ok_cycle(calls=calls))
    s.warm()
    chk = s.c.selftest.get("ENTITY_IDS")
    check("the status entity was never added", s.st() is None)
    check("ENTITY_IDS FAILs naming the missing key", chk is not None and chk.level == "FAIL" and "status" in chk.text,
          str(chk))
    check("nothing is computed", not calls and s.c.counters["runs_started"] == 0, str(s.c.counters))
    check("the entities that exist show SELF_TEST_FAILED nulls", s.c.envelope is not None
          and s.c.envelope.status == "SELF_TEST_FAILED" and h.state("data_quality").state == "unknown"
          and h.state("fresh").state == "off" and not s.items_numeric(),
          f"{s.c.envelope and s.c.envelope.status} {h.state('data_quality').state} {h.state('fresh').state}")
    s.close()

    print("== one entity whose state write raises: the others still follow; the tick never raises")
    s = Scn("entity_write_fails", H.site_profile())
    s.c.time_budget_s = 3600
    H.inject(s.c, pv_ok_cycle(valid_h=0.5))
    s.warm()
    check("a valid result first", h.state("pv_tomorrow").state == "4.2" and h.state("fresh").state == "on")
    acc = [e for p_ in s.hass.config_entries.platforms[s.entry.entry_id] for e in p_.entities
           if getattr(e, "_key", None) == "accuracy"][0]

    def refuse():
        raise ValueError("synthetic refusal of one entity state")
    acc.async_write_ha_state = refuse
    raised = None
    try:
        s.advance(45 * 60, settle=5)               # past valid_until: the timer's STALE goes to every entity
        s.advance(60, settle=5)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    st = s.st()
    check("the minute tick does not raise", raised is None, str(raised))
    check("SELF_TEST_FAILED naming ENTITY_WRITE (the failing entity's key, the exception type)",
          st.state == "SELF_TEST_FAILED" and "accuracy (ValueError)" in (st.attributes.get("self_test") or {}).get(
              "ENTITY_WRITE", ""), f"{st.state} {st.attributes.get('self_test')}")
    check("every other entity followed: fresh off, data_quality unknown, no number", h.state("fresh").state == "off"
          and h.state("data_quality").state == "unknown" and not s.items_numeric(ITEM_KEYS))
    check("the refusal's message appears nowhere", not H.text_anywhere(s.hass, "synthetic refusal",
                                                                         {"coordinator": s.c.diagnostics()}))
    n_runs = s.c.counters["runs_started"]
    s.advance(3600, settle=5)
    check("a failed self-test computes nothing more", s.c.counters["runs_started"] == n_runs
          and s.st().state == "SELF_TEST_FAILED", str(s.c.counters))
    gen_before, w_, f_ = s.attrs().get("generated_at"), s.c.counters["entity_writes"], s.c.counters["entity_write_failures"]
    s.advance(60, n=3, settle=1)
    check("... the entity that keeps refusing is tried again at each tick, without a SELF_TEST_FAILED republish (no other "
          "entity is written, generated_at unchanged)", s.c.counters["entity_write_failures"] - f_ == 3
          and s.c.counters["entity_writes"] == w_ and s.attrs().get("generated_at") == gen_before,
          f"{s.c.counters['entity_write_failures'] - f_} {s.c.counters['entity_writes'] - w_} {gen_before}")
    del acc.async_write_ha_state
    s.close()

    print("== an entity id collision -> SELF_TEST_FAILED")

    def foreign(scn):
        scn.hass.states.seed("sensor.ecco_intel_status", "something else", {"friendly_name": "a foreign entity"})
    calls = []
    s = Scn("collision", H.site_profile(), pre=foreign)
    H.inject(s.c, pv_ok_cycle(calls=calls))
    s.warm()
    moved = s.hass.states._states.get("sensor.ecco_intel_status_2")
    check("the status entity was given another id ('_2')", moved is not None)
    check("SELF_TEST_FAILED naming ENTITY_IDS", moved is not None and moved.state == "SELF_TEST_FAILED"
          and "ENTITY_IDS" in (moved.attributes.get("self_test") or {}))
    check("nothing is computed", not calls and s.c.counters["runs_started"] == 0)
    check("the foreign entity is untouched", s.hass.states._states["sensor.ecco_intel_status"].state == "something else")
    s.pause = "on"
    s.advance(60)
    moved = s.hass.states._states.get("sensor.ecco_intel_status_2")
    check("pause on over a failed self-test -> PAUSED (PAUSED > SELF_TEST_FAILED)", moved is not None and moved.state == "PAUSED")
    s.pause = "off"
    s.advance(60)
    moved = s.hass.states._states.get("sensor.ecco_intel_status_2")
    check("pause off again -> SELF_TEST_FAILED again, still nothing computed", moved is not None
          and moved.state == "SELF_TEST_FAILED" and not calls)
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== refresh before expiry: the runtime margin and the engine's (drift test)")
    eng_margin = getattr(VEN_CYCLE, "REFRESH_MARGIN_S", None)
    cyc_src = Path(VEN_CYCLE.__file__).read_text(encoding="utf-8")
    fc_doc = (H.REPO / "docs" / "intelligence" / "INTELLIGENCE_FOUNDATION_CONTRACT.md").read_text(encoding="utf-8")
    m_doc = re.search(r"`REFRESH_MARGIN_S = ([0-9]+(?:\.[0-9]+)?)`", fc_doc)
    check("the runtime's refresh margin is two ticks plus the tick margin (125 s), the value the foundation contract "
          "(13.4) gives the engine constant, and the coordinator uses that constant",
          CONST.REFRESH_MARGIN_S == 2 * CONST.TICK_S + CONST.PROPOSED_TICK_MARGIN_S == 125.0 and m_doc is not None
          and float(m_doc.group(1)) == CONST.REFRESH_MARGIN_S and COORD.REFRESH_MARGIN_S == CONST.REFRESH_MARGIN_S,
          f"{CONST.REFRESH_MARGIN_S} {m_doc and m_doc.group(1)}")
    check("... and equals the engine's shadow_cycle.REFRESH_MARGIN_S (WP-2 is merged: the engine defines it and emits "
          "INPUT_EXPIRING)", isinstance(eng_margin, (int, float)) and float(eng_margin) == CONST.REFRESH_MARGIN_S
          and "INPUT_EXPIRING" in cyc_src, repr(eng_margin))

    print("== refresh before expiry: three simulated hours on fresh inputs (owner-record decisions, the real vendored cycle)")
    reads_setup = h.recorder().calls
    s = Scn("cadence", H.site_profile(decisions=H.owner_decisions()))
    s.warm()
    first = s.st().state
    reads0, slots0 = h.recorder().calls, s.c.counters["slot_runs_started"]
    w0, r0 = len(s.hass.state_write_log), len(s.hass.recorder_log)
    rows0 = len(s.hass.recorder_rows)
    cs0 = len(s.c.cycle_stats)
    t_begin = h.now
    log, mismatch = [], []
    for _ in range(180):
        h.set_now(h.now + timedelta(seconds=60))
        if h.now.minute == 0:                      # the recorder compiles each hour as it ends (no catch-up needed)
            h.recorder().statistics = H.synthetic_statistics(h.now, days=30)
        s.seed()
        h.tick(0, settle=10)
        a = s.attrs()
        nums = {k: s.attrs(k).get("valid_until") for k in ITEM_KEYS if H.numeric_state(h.state(k))}
        log.append((h.now, s.st().state, a.get("generated_at"), a.get("valid_until"), a.get("next_run_at"), nums))
        for key in C.INTEGRATION_ENTITY_KEYS:
            eid_, st_ = C.ENTITY_IDS[key], h.state(key)
            p_ = s.c.payloads.get(eid_)
            if st_ is None or p_ is None or {k: v for k, v in st_.attributes.items() if k not in HA_OWN} != {**p_[1], **p_[2]}:
                mismatch.append((h.now.isoformat(), key))
    stale = [t[0].isoformat() for t in log if t[1] != "OK"]
    status_rows = [r[1] for r in s.hass.recorder_rows[rows0:] if r[0] == C.ENTITY_IDS["status"]]
    check("fresh inputs for three hours: never STALE (or anything but OK) after the first result, at any tick and in "
          f"any status row of the recorder ({len(status_rows)}: every write counted, also one replaced within its tick)",
          first == "OK" and not stale and len(status_rows) >= 150 and set(status_rows) == {"OK"},
          f"{first} {stale[:5]} {sorted(set(status_rows))}")
    n_slots = s.c.counters["slot_runs_started"] - slots0
    n_ref = s.c.counters["refresh_runs_started"]
    check("non-vacuity: charge_target carries a number on every tick, refreshes ran between the slots",
          all("charge_target" in t[5] for t in log) and n_ref >= 150, f"refreshes {n_ref}")
    sc_rows = counts(s.cfg)
    check("statistics are read once per slot (refreshes reuse the slot's rows); the scorecard records one slot row per slot "
          "cycle; more cycles ran than slots", n_slots == 4 and h.recorder().calls - reads0 == n_slots
          and sc_rows.get("ecco_intel_slots") == n_slots + 1 and s.c.counters["runs_started"] > n_slots + 1
          and s.c.counters["history_catchup_reads"] == 0,
          f"slots {n_slots} reads {h.recorder().calls - reads0} {sc_rows} {s.c.counters}")
    n_par, n_reu = s.c.counters["history_parses"], s.c.counters["history_reuses"]
    check("A50: every recorder read is parsed once (the first cycle after it), the slot's cache then keeps its image and "
          "every other cycle reuses the parsed history (parses = reads, parses + reuses = cycles started); every read "
          "drops what was kept, so it rebuilds (builds = reads; the 21:30 slot reads the 21:00 slot's rows again); the "
          "diagnostics' last cycle says which", n_par == h.recorder().calls - reads_setup >= 5
          and n_par + n_reu == s.c.counters["runs_started"] and n_reu >= 150
          and s.c._history_reuse.builds == n_par
          and isinstance(s.c._hist["stats"], ENGINE_LINK.history_source.StatisticsImage)
          and {"history_parsed", "history_reused"} <= set(s.c.diagnostics()["last_cycle"]),
          f"parses {n_par} reuses {n_reu} reads {h.recorder().calls - reads_setup} started {s.c.counters['runs_started']}")

    def _dt(v):
        return datetime.fromisoformat(v) if isinstance(v, str) else None
    bad_next = [(t[0].isoformat(), t[2], t[4], t[3]) for t in log
                if None in (_dt(t[2]), _dt(t[3]), _dt(t[4])) or not (_dt(t[2]) <= _dt(t[4]) <= _dt(t[3]))]
    check("next_run_at lies between generated_at and valid_until on every computed envelope", not bad_next, str(bad_next[:3]))
    over = [(t[0].isoformat(), k) for t in log for k, vu in t[5].items()
            if vu is None or datetime.fromisoformat(vu) < t[0] + timedelta(seconds=COORD.TICK_S)]
    check("... and no entity holds a number past its valid_until (each number written at a tick is valid until the next)",
          not over, str(over[:3]))
    check("the published state and attributes are exactly the contract mapping on every tick (keeping attributes out of "
          "the recorder changes nothing that is published)", not mismatch, str(mismatch[:3]))
    leaked = sorted({k for _e, _st, rec in s.hass.recorder_rows[rows0:] for k in rec if k in TS_ONLY or k in C.UNRECORDED_ATTRIBUTES})
    check("A17: no recorder row holds a timestamp-only attribute (generated_at, valid_until, next_run_at) or an unrecorded "
          "contract attribute (input_ages, self_test, last_good, advice, engine_comparison)", not leaked
          and all(type(e)._combined_unrecorded >= C.UNRECORDED_ATTRIBUTES | set(TS_ONLY)
                  for p_ in s.hass.config_entries.platforms[s.entry.entry_id] for e in p_.entities), str(leaked))
    writes, rrows = s.hass.state_write_log[w0:], s.hass.recorder_log[r0:]
    cyc = [r for r in list(s.c.cycle_stats)[cs0:] if str(r[2]).startswith("published")]
    hr0 = t_begin.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    per_hour = []
    for k in range(2):
        a_, b_ = hr0 + timedelta(hours=k), hr0 + timedelta(hours=k + 1)
        per_hour.append({"hour": a_.isoformat(), "state_writes": sum(1 for t, *_x in writes if a_ <= t < b_),
                         "states_rows": sum(1 for t, *_x in rrows if a_ <= t < b_),
                         "attributes_rows": sum(1 for t, _e, new in rrows if a_ <= t < b_ and new),
                         "cycles_published": sum(1 for r in cyc if a_ <= datetime.fromisoformat(r[0]) < b_)})
    print("  measured per hour (stand-in recorder): " + json.dumps(per_hour))
    check("A17: state writes per hour are at most the eleven entities per published cycle (an entity whose payload is "
          "unchanged is not written again)", all(x["state_writes"] <= 11 * x["cycles_published"] + 11 for x in per_hour)
          and all(x["cycles_published"] >= 50 for x in per_hour), json.dumps(per_hour))
    check("A17: an unchanged refresh adds no attributes row: attributes rows per hour stay far below the states rows "
          "(each refresh still adds one states row per written entity, as Home Assistant's recorder does)",
          all(x["attributes_rows"] * 10 <= x["states_rows"] for x in per_hour), json.dumps(per_hour))
    d = s.c.diagnostics()
    byk = d["cycle_stats"]["by_kind"]
    print("  measured cycle times on this machine (real vendored cycle): " + json.dumps(byk)
          + f"; engine CPU in the last hour {d['cadence']['cpu_s_rolling_hour']:.2f} s")
    check("T1: the diagnostics carry last_cycle_timing, cycle_duration_s and cycle_stats for both cycle kinds",
          set(d["last_cycle_timing"]) >= {"recorder_s", "engine_s", "store_s", "total_s", "cpu_s", "kind", "outcome"}
          and d["cycle_duration_s"] == d["last_cycle_timing"]["total_s"] and byk["SLOT"]["n"] >= 5 and byk["REFRESH"]["n"] >= 150
          and byk["REFRESH"]["total_s_p95"] is not None and d["cycle_stats"]["kept"] == len(d["cycle_stats"]["runs"]),
          f"{d['last_cycle_timing']} {byk}")
    s.close()

    print("== only the entities whose payload changed are written")
    calls = []
    s = Scn("entity_diff", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 3600.0, "pv_valid_s": 600.0}, calls))
    s.warm()
    t_first = calls[0] if calls else h.now
    per_tick = []
    for _ in range(9):
        w = len(s.hass.state_write_log)
        s.advance(60)
        per_tick.append(((h.now - t_first).total_seconds(), [e for _t, e, _u in s.hass.state_write_log[w:]]))
    quiet = [x for x in per_tick if x[0] < 540]
    at_exp = [x for x in per_tick if x[0] == 540]
    check("unchanged ticks write no entity; the tick at which pv_tomorrow's validity passes the publish horizon writes "
          "exactly that one entity", len(calls) == 1 and all(not x[1] for x in quiet) and len(at_exp) == 1
          and at_exp[0][1] == [C.ENTITY_IDS["pv_tomorrow"]] and h.state("pv_tomorrow").state == "unknown",
          f"{len(calls)} {per_tick}")
    s.close()

    print("== an entity whose state write raised is written again at the next tick (no stale number stays on it)")
    calls = []
    s = Scn("dirty_rewrite", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 3600.0, "pv_valid_s": 600.0}, calls))
    s.warm()
    t_first = calls[0] if calls else h.now
    pv_ent = [e for p_ in s.hass.config_entries.platforms[s.entry.entry_id] for e in p_.entities
              if getattr(e, "_key", None) == "pv_tomorrow"][0]
    left = {"n": 2}

    def flaky():
        if left["n"] > 0:
            left["n"] -= 1
            raise ValueError("synthetic transient refusal")
        type(pv_ent).async_write_ha_state(pv_ent)
    pv_ent.async_write_ha_state = flaky
    while (h.now - t_first).total_seconds() < 540:
        s.advance(60)
    after_fail = h.state("pv_tomorrow").state
    s.advance(60)
    check("pv_tomorrow's write is refused twice (when it expires, and in the SELF_TEST_FAILED that follows): its old number "
          "stays only until the next tick, which writes it again although its payload did not change",
          after_fail == "4.2" and left["n"] == 0 and h.state("pv_tomorrow").state == "unknown"
          and s.st().state == "SELF_TEST_FAILED" and "pv_tomorrow (ValueError)" in s.c.selftest.get("ENTITY_WRITE").text,
          f"{after_fail} {left} {h.state('pv_tomorrow').state} {s.st().state}")
    n_w = s.c.counters["entity_writes"]
    s.advance(60, n=3)
    check("... and a failed self-test then writes nothing more on unchanged ticks", s.c.counters["entity_writes"] == n_w,
          f"{s.c.counters['entity_writes'] - n_w}")
    del pv_ent.async_write_ha_state
    s.close()

    print("== the wall clock steps back across a slot while a cycle runs: the result is still published")
    calls = []
    s = Scn("clock_step_back", H.site_profile(), now=datetime(2030, 1, 15, 20, 57, 5, tzinfo=UTC))
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0, "shift_clock_s": -10.0 if n == 1 else 0.0}, calls))
    s.advance(60, n=3)                            # the first cycle at 20:59:05; the 21:00 slot's at 21:00:05 steps back 10 s
    a = s.attrs()
    check("published although the clock now reads before the slot and before generated_at: next_run_at is never before "
          "generated_at (with_next_run_at would refuse it), no exception", len(calls) == 2 and pv_shown()
          and s.c.counters["exceptions"] == 0 and a.get("next_run_at") is not None
          and datetime.fromisoformat(a["next_run_at"]) >= datetime.fromisoformat(a["generated_at"]),
          f"{len(calls)} {s.st().state} {s.c.counters['exceptions']} {a.get('generated_at')} {a.get('next_run_at')}")
    s.close()

    print("== at most one cycle start per tick: a tick that comes early starts no refresh (the 55 s floor)")
    calls = []
    s = Scn("refresh_floor", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 130.0}, calls))
    s.advance(60, n=2)                            # the first (slot) cycle runs at the second tick (grace 120 s)
    t0_ = calls[-1]
    for dt_ in (30, 25, 35):                      # ticks at +30 s, +55 s and +90 s (a refresh is due at each)
        h.set_now(h.now + timedelta(seconds=dt_))
        s.seed()
        h.tick(0, settle=5)
    check("a result valid 130 s: no refresh at a tick 30 s after the last start, one 55 s after it, none 35 s after that",
          [(t - t0_).total_seconds() for t in calls] == [0.0, 55.0], f"{[(t - t0_).total_seconds() for t in calls]}")
    s.close()

    print("== the CPU guard suspends refreshes (slot cycles continue) and lifts")
    calls = []
    s = Scn("cpu_guard", H.site_profile(), stats_days=3)
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0, "burn": 0.2}, calls))
    s.c.cpu_budget_s = 0.5
    s.warm()
    s.advance(60, n=5)
    n_susp = len(calls)
    s.advance(60, n=3)
    nra = s.attrs().get("next_run_at")
    check("over the budget (0.5 s of engine CPU in the rolling hour, lowered for the test) refreshes stop and the result "
          "goes STALE (fails closed); the self-test warns CPU_BUDGET; next_run_at is the next slot",
          2 <= n_susp <= 4 and len(calls) == n_susp and s.st().state == "STALE" and s.c.counters["refresh_suppressed_cpu"] >= 3
          and s.c.selftest.get("CPU_BUDGET") is not None and s.c.selftest.get("CPU_BUDGET").level == "WARN"
          and nra == COORD.next_slot(h.now).isoformat() and s.c.diagnostics()["cadence"]["refresh_suspended_cpu"],
          f"{n_susp} {len(calls)} {s.st().state} {s.c.counters} {nra}")
    while h.now.minute != 59:
        s.advance(60)
    s.advance(60)
    check("... the slot cycle still runs while refreshes are suspended", len(calls) == n_susp + 1, f"{len(calls)} {h.now}")
    s.advance(60, n=3)
    n_slot = len(calls)
    s.c.cpu_budget_s = CONST.PROPOSED_CPU_BUDGET_S_PER_H     # the rolling hour is now under the budget
    s.advance(60, n=2)
    check("... and once the rolling hour is under the budget the refreshes resume at the next tick (CPU_BUDGET PASS)",
          n_slot == n_susp + 1 and len(calls) == n_slot + 2 and pv_shown() and s.c.selftest.get("CPU_BUDGET").level == "PASS",
          f"{n_slot} {len(calls)} {s.st().state} {s.c.selftest.get('CPU_BUDGET')}")
    s.close()

    print("== an engine job that raises once is retried exactly once, 300 s after the failed start")
    calls = []
    fail = {"from": None, "n": 0}

    def fail_step(n):
        if fail["from"] is not None and fail["from"] <= n < fail["from"] + fail["n"]:
            return {"error": RuntimeError("synthetic refresh failure")}
        return {"valid_s": 180.0}
    s = Scn("exception_retry", H.site_profile())
    H.inject(s.c, scripted_cycle(fail_step, calls))
    s.warm()
    fail["from"], fail["n"] = len(calls), 1
    s.advance(60)
    st1, t_fail, n_fail = s.st(), calls[-1], len(calls)
    s.advance(60, n=4)
    n_wait = len(calls)
    s.advance(60)
    check("a refresh that raises -> SELF_TEST_FAILED (RUNTIME_EXCEPTION); no run in the next 240 s; the retry starts "
          "300 s after the failed start and publishes", st1.state == "SELF_TEST_FAILED"
          and "RUNTIME_EXCEPTION" in (st1.attributes.get("self_test") or {}) and n_fail == fail["from"] + 1
          and n_wait == n_fail and len(calls) == n_fail + 1 and (calls[-1] - t_fail).total_seconds() == 300.0
          and pv_shown() and s.c.counters["exception_retries"] == 1, f"{st1.state} {n_wait} {len(calls)} {s.c.counters}")
    fail["from"], fail["n"] = len(calls), 10 ** 6
    n0 = len(calls)
    while not (h.now.minute == 59):
        s.advance(60)
    in_slot = len(calls) - n0
    s.advance(60)
    check("a job that keeps raising: one refresh fails, its single retry 300 s later fails, then nothing until the next "
          "slot, whose cycle runs", in_slot == 2 and len(calls) == n0 + 3 and s.c.counters["exception_retries"] == 2
          and s.st().state == "SELF_TEST_FAILED", f"{in_slot} {len(calls) - n0} {s.c.counters}")
    s.close()

    print("== a hanging refresh: no further refresh starts while it is in flight (the second-run guard)")
    gate = threading.Event()
    calls = []
    hold = {"n": None}
    s = Scn("refresh_hang", H.site_profile())
    s.c.time_budget_s = 3600
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0, "block": gate if n == hold["n"] else None}, calls))
    s.warm()
    hold["n"] = len(calls)
    s.advance(60, settle=0.3)
    check("the refresh hangs in flight", wait_for(lambda: len(calls) == hold["n"] + 1) and s.c.diagnostics()["busy"],
          f"{len(calls)}")
    sk0 = s.c.counters["refresh_skipped_in_flight"]
    s.advance(60, n=4, settle=0.1)
    check("... no refresh starts while it hangs, the skips are counted, and the result goes STALE",
          len(calls) == hold["n"] + 1 and s.c.counters["refresh_skipped_in_flight"] - sk0 >= 3 and s.st().state == "STALE",
          f"{len(calls)} {s.c.counters} {s.st().state}")
    gate.set()
    wait_for(lambda: not s.c.diagnostics()["busy"])
    h.settle(0.5)
    s.advance(60, n=2)
    check("... once it ends the refreshes resume", len(calls) >= hold["n"] + 2 and pv_shown(), f"{len(calls)} {s.st().state}")
    s.close()

    print("== a time-budget overrun in a refresh: no refresh before the next slot")
    calls = []
    slow = {"n": None}
    s = Scn("refresh_budget", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0, "sleep": 1.5 if n == slow["n"] else 0.0}, calls))
    s.warm()
    s.c.time_budget_s = 0.3
    slow["n"] = len(calls)
    s.advance(60, settle=1.0)
    st1 = s.st()
    time.sleep(1.6)
    h.settle(0.5)
    s.c.time_budget_s = 120
    n0 = len(calls)
    s.advance(60, n=10, settle=2)
    check("SELF_TEST_FAILED (CYCLE_TIME_BUDGET); after the abandoned thread ends no refresh and no retry starts before "
          "the next slot", st1.state == "SELF_TEST_FAILED" and "CYCLE_TIME_BUDGET" in (st1.attributes.get("self_test") or {})
          and len(calls) == n0 and s.c.diagnostics()["cadence"]["refresh_barred_until_next_slot"]
          and s.c.diagnostics()["cadence"]["retry_at"] is None, f"{st1.state} {len(calls) - n0} {s.c.diagnostics()['cadence']}")
    while h.now.minute != 0:
        s.advance(60, settle=2)
    s.advance(60, n=2, settle=2)
    check("... the next slot's cycle runs and refreshes resume after it", len(calls) >= n0 + 2 and pv_shown(),
          f"{len(calls) - n0} {s.st().state}")
    s.close()

    print("== a result published STALE at once: the next refresh backs off 60, 120, 240, 300 s; a good result resets it")
    calls = []
    short = {"on": True}
    s = Scn("stale_backoff", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 50.0 if short["on"] else 180.0}, calls))
    s.warm()
    s.advance(60, n=20)
    starts = [(t - calls[0]).total_seconds() for t in calls]
    gaps = [b_ - a_ for a_, b_ in zip(starts, starts[1:])]
    check("validity 50 s (published STALE at once, values in last_good): refreshes start 60, 120, 240, 300, 300 s apart",
          gaps[:5] == [60.0, 120.0, 240.0, 300.0, 300.0] and s.st().state == "STALE" and not s.items_numeric()
          and s.c.counters["stale_backoffs"] >= 5, f"{gaps}")
    short["on"] = False
    n0 = len(calls)
    for _ in range(6):
        s.advance(60)
        if len(calls) > n0:
            break
    t_good = calls[-1]
    s.advance(60, n=2)
    check("... a result published as computed resets the back-off: the next refresh follows one tick later",
          pv_shown() and len(calls) >= n0 + 2 and (calls[n0 + 1] - t_good).total_seconds() == 60.0
          and s.c.diagnostics()["cadence"]["stale_backoff_s"] is None, f"{s.st().state} {len(calls) - n0}")
    s.close()

    print("== recorder rows ending before the slot's hour are read again once, 300 s after the slot; a failed read at most "
          "every 600 s")
    calls = []
    s = Scn("history_catchup", H.site_profile(), now=datetime(2030, 1, 15, 20, 50, tzinfo=UTC))
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0}, calls))
    s.warm()
    while h.now < datetime(2030, 1, 15, 21, 0, tzinfo=UTC):
        s.advance(60)
    reads = {}
    for _ in range(25):                           # 21:01 .. 21:25
        r_ = h.recorder().calls
        if h.now == datetime(2030, 1, 15, 21, 2, tzinfo=UTC):
            h.recorder().statistics = H.synthetic_statistics(h.now, days=30)      # the hour is compiled now
        s.advance(60)
        reads[h.now.strftime("%H:%M")] = h.recorder().calls - r_
    ne = s.c.last_diag.get("history_newest_end")
    check("the 21:00 slot read rows ending 20:00; refreshes reuse them until 21:05, read once then (rows now ending 21:00), "
          "and not again in that slot", [k for k, v in reads.items() if v] == ["21:05"] and reads["21:05"] == 1
          and ne == "2030-01-15T21:00:00+00:00" and s.c.counters["history_catchup_reads"] == 1, f"{reads} {ne}")
    while h.now < datetime(2030, 1, 15, 21, 29, tzinfo=UTC):
        s.advance(60)
    h.recorder().fail_with = RuntimeError("synthetic recorder failure")
    reads, hdiag = {}, {}
    for _ in range(24):                           # 21:30 .. 21:53
        r_ = h.recorder().calls
        if h.now == datetime(2030, 1, 15, 21, 44, tzinfo=UTC):
            h.recorder().fail_with = None
        s.advance(60)
        reads[h.now.strftime("%H:%M")] = h.recorder().calls - r_
        ld = s.c.last_diag
        hdiag[h.now.strftime("%H:%M")] = (ld.get("history_hours"), ld.get("history_parsed"), ld.get("history_reused"))
    check("a failed slot read (21:30) is retried by a refresh at most every 600 s (21:40 fails, 21:50 reads)",
          [k for k, v in reads.items() if v] == ["21:30", "21:40", "21:50"] and s.c.counters["recorder_retry_reads"] == 2
          and s.c.selftest.get("RECORDER_READ").level == "PASS", f"{reads} {s.c.counters}")
    _refused = [v for k, v in hdiag.items() if "21:30" <= k < "21:50"]
    check("A50: a refused read keeps no parsed history: from the failed 21:30 read to the 21:50 read every cycle has no "
          "history and neither parses nor reuses one; the 21:50 read is parsed and built again, the refreshes after it "
          "reuse it", len(_refused) == 20 and all(v == (0, False, False) for v in _refused)
          and hdiag.get("21:50", (0,))[0] > 0 and hdiag["21:50"][1:] == (True, False)
          and all(hdiag[k][2] is True and hdiag[k][0] == hdiag["21:50"][0] for k in ("21:51", "21:52", "21:53")),
          str(hdiag))
    s.close()

    print("== an item the engine BLOCKED INPUT_EXPIRING asks for a refresh at the next tick (since A4 its short validity no "
          "longer shortens the envelope's)")
    calls = []
    expiring = {"on": True, "where": "blockers"}

    def expiring_cycle(inputs):
        """charge_target BLOCKED INPUT_EXPIRING (while expiring['on']; the code in its blockers or only in its reason
        codes; or, 'forecast', predicted_morning_soc instead), every other item BLOCKED otherwise, pv_tomorrow OK and the
        envelope valid for 900 s (contract constructors only)."""
        calls.append(inputs.now)
        bl = (("TEST_BLOCK", "synthetic block"),)
        where = expiring["where"] if expiring["on"] else None
        exp_bl = (("INPUT_EXPIRING", "synthetic expiry"),) if where in ("blockers", "forecast") else bl
        exp_rc = ("INPUT_EXPIRING",) if where == "reason_codes" else ()
        items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=exp_bl, reason_codes=exp_rc)
                      if (k == "charge_target" and where in ("blockers", "reason_codes"))
                      else C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
        fc = (C.ForecastView("predicted_day_load", C.ItemStatus.BLOCKED, blockers=bl),
              C.ForecastView("pv_tomorrow", C.ItemStatus.OK, value=4.2, valid_until=inputs.now + timedelta(seconds=900)),
              C.ForecastView("predicted_morning_soc", C.ItemStatus.BLOCKED, blockers=exp_bl if where == "forecast" else bl))
        return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                                   decisions=inputs.decisions, paused=inputs.paused,
                                   valid_until=inputs.now + timedelta(seconds=900))
    s = Scn("input_expiring_refresh", H.site_profile())
    H.inject(s.c, expiring_cycle)
    s.warm()
    n0, r0 = len(calls), s.c.counters["refresh_input_expiring"]
    nra = []
    for _ in range(4):
        s.advance(60)
        a_ = s.attrs()
        nra.append((datetime.fromisoformat(a_["next_run_at"]) - datetime.fromisoformat(a_["generated_at"])).total_seconds())
    check("a result whose charge_target is BLOCKED INPUT_EXPIRING (envelope valid 900 s): a refresh at every tick, counted "
          "as refresh_input_expiring, pv_tomorrow shown throughout", n0 >= 1 and len(calls) == n0 + 4
          and s.c.counters["refresh_input_expiring"] == r0 + 4 and pv_shown(), f"{len(calls) - n0} {s.c.counters}")
    check("... and next_run_at is the refresh floor after the cycle start (one tick ahead), not valid_until - margin",
          all(abs(x - COORD.PROPOSED_REFRESH_FLOOR_S) <= 1.0 for x in nra), str(nra))
    expiring["where"] = "reason_codes"
    n1 = len(calls)
    s.advance(60, n=2)
    check("... the code among the item's reason codes only (a truncated blocker list) also asks for it",
          len(calls) == n1 + 2, f"{len(calls) - n1}")
    expiring["where"] = "forecast"
    n1 = len(calls)
    s.advance(60, n=2)
    check("... and so does a forecast (predicted_morning_soc) BLOCKED INPUT_EXPIRING", len(calls) == n1 + 2, f"{len(calls) - n1}")
    n1 = len(calls)
    for _ in range(4):
        s.advance(30)
    check("... still at most one start per PROPOSED_REFRESH_FLOOR_S: four ticks 30 s apart start two refreshes",
          len(calls) == n1 + 2, f"{len(calls) - n1}")
    expiring["on"] = False
    n2 = len(calls)
    s.advance(60)                                 # this refresh still follows the last expiring result
    gen_ok = datetime.fromisoformat(s.attrs()["generated_at"])
    nr_ok = datetime.fromisoformat(s.attrs()["next_run_at"])
    s.advance(60, n=5)
    check("once no item is BLOCKED INPUT_EXPIRING, refreshes follow the envelope's validity again: no refresh for the next "
          "five ticks, next_run_at = valid_until - margin", len(calls) == n2 + 1 and pv_shown()
          and (nr_ok - gen_ok).total_seconds() == 900.0 - COORD.REFRESH_MARGIN_S,
          f"{len(calls) - n2} {(nr_ok - gen_ok).total_seconds()}")
    s.c.refresh_enabled = False
    expiring["on"], expiring["where"] = True, "blockers"
    s.advance(3600 - (h.now.minute * 60 + h.now.second) + 60)        # the next slot cycle publishes an expiring result
    n3 = len(calls)
    s.advance(60, n=3)
    check("refresh switched off: an INPUT_EXPIRING item starts no refresh (the slot cycle ran)",
          n3 > n2 + 1 and len(calls) == n3, f"{n3 - n2} {len(calls) - n3}")
    s.close()

    print("== V-4: a frozen poll text past the liveness bound -> the dongle items BLOCKED, the history-only items keep their "
          "numbers, no caller / quality disagreement")
    dec_owner = SD.DecisionSet.from_mapping(H.owner_decisions(), source="site_local")
    ov = ENGINE_LINK.advisory_overrides(dec_owner)
    lim_owner, _n = SD.freshness_limits(dec_owner)
    bound = VEN_Q.DQ_PROPOSED.liveness_max_age_s
    ov_open = ENGINE_LINK.advisory_overrides(SD.DecisionSet())
    check("V-4: each dongle signal's caller limit is min(its limit, the quality layer's liveness bound) (the SOC's 900 s "
          "becomes 180 s), every other limit is unchanged and none is looser than freshness_limits",
          ov.get("battery.soc") == bound == ov_open.get("battery.soc") and all(v <= bound for k, v in ov.items() if k in SD.DONGLE_SIGNALS)
          and all(v == float(lim_owner[k]) for k, v in ov.items() if k not in SD.DONGLE_SIGNALS)
          and all(v <= float(lim_owner[k]) for k, v in ov.items()) and set(ov_open) == {"battery.soc", "history.hourly"},
          f"{ov} {ov_open}")
    s = Scn("v4_frozen_poll", H.site_profile(decisions=H.owner_decisions()))
    s.warm()
    hist_only = [k for k in ("pv_tomorrow", "predicted_day_load") if H.numeric_state(h.state(k))]
    s.frozen_poll = "2030-01-15 20:09:40"
    rows_v4 = []
    for _ in range(14):
        s.advance(60, settle=10)
        dg = s.c.diagnostics()
        gen = datetime.fromisoformat(s.attrs()["generated_at"])
        age_at_gen = None if dg["liveness"]["telemetry"]["age_s"] is None else \
            dg["liveness"]["telemetry"]["age_s"] - (h.now - gen).total_seconds()
        codes = set(s.attrs().get("reason_codes", [])) | {c_ for k in ITEM_KEYS for c_ in s.attrs(k).get("reason_codes", [])}
        rows_v4.append((s.st().state, age_at_gen, "CALLER_FRESHNESS_DISAGREES" in codes, tuple(s.items_numeric(DONGLE_ITEMS)),
                        tuple(k for k in hist_only if H.numeric_state(h.state(k))), s.attrs("charge_target").get("status"),
                        "INPUT_NOT_FRESH" in s.attrs("charge_target").get("reason_codes", [])))
    window = [r_ for r_ in rows_v4 if r_[0] != "STALE" and r_[1] is not None and bound < r_[1] <= 900.0]
    check("non-vacuity: before the freeze the history-only items carry numbers, and a result was computed while the poll "
          "text was between the liveness bound and the SOC's 900 s limit old", bool(hist_only) and bool(window),
          f"{hist_only} {rows_v4}")
    check("V-4: such a result has no CALLER_FRESHNESS_DISAGREES; charge_target BLOCKED (INPUT_NOT_FRESH) and no item "
          "resting on a dongle signal shows a number; the history-only items keep their numbers",
          all(not r_[2] and not r_[3] and r_[5] == "BLOCKED" and r_[6] and r_[4] == tuple(hist_only) for r_ in window),
          str(window))
    s.close()

    print("== a helper that is never rewritten stays BLOCKED (INPUT_NOT_FRESH) through every refresh (pin)")
    dec_h = H.owner_decisions()
    dec_h["I-D3"]["value"] = {"kind": "CONFIGURED_HELPER", "resolve_at_run": True}
    s = Scn("helper_never_rewritten", H.site_profile(decisions=dec_h))
    old_t = h.now - timedelta(hours=3)

    def helper_not_rewritten(scn):
        scn.hass.states.seed("input_number.test_battery_model_capacity", "20", {"unit_of_measurement": "kWh"},
                             changed_at=old_t, reported_at=old_t)
    s.after_seed = helper_not_rewritten
    helper_not_rewritten(s)
    s.warm()
    pin = []
    for _ in range(16):
        s.advance(60)
        ct_ = s.attrs("charge_target")
        pin.append((ct_.get("status"), "INPUT_NOT_FRESH" in ct_.get("reason_codes", []), H.numeric_state(h.state("charge_target"))))
    check("I-D3 resolved at run time from a capacity helper whose state is three hours old: charge_target BLOCKED with "
          "INPUT_NOT_FRESH and no number on every tick, while refreshes run", s.c.counters["refresh_runs_started"] >= 1
          and all(x == ("BLOCKED", True, False) for x in pin), f"{pin} {s.c.counters['refresh_runs_started']}")
    s.close()

    print("== the configuration-poll text has its own liveness memory; its change time reaches the engine job")
    cfg_spec = dict(H.READING_MAP.get(SD.CONFIG_LIVENESS_KEY) or {"entity": H.eid("sensor", "last_configuration_update")})
    readings_cfg = dict(H.READING_MAP)
    readings_cfg[SD.CONFIG_LIVENESS_KEY] = cfg_spec
    cfg = {"frozen": None, "changed": None}

    def cfg_seed(scn):
        if cfg["frozen"] is not None:
            scn.hass.states.seed(cfg_spec["entity"], cfg["frozen"])
        else:
            cfg["changed"] = h.now - timedelta(seconds=30)
            scn.hass.states.seed(cfg_spec["entity"], cfg["changed"].strftime("%Y-%m-%d %H:%M:%S"), changed_at=cfg["changed"])
        if "online_entity" in cfg_spec:
            scn.hass.states.seed(cfg_spec["online_entity"], "on")
    jobs = []
    orig_compute = ENGINE_LINK.compute

    def spy_compute(job, run_cycle=None):
        jobs.append(job)
        return orig_compute(job, run_cycle)
    ENGINE_LINK.compute = spy_compute
    try:
        calls = []
        s = Scn("config_liveness", H.site_profile(readings=readings_cfg), pre=cfg_seed)
        s.after_seed = cfg_seed
        H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0}, calls))
        s.advance(60)
        first_sight = s.c.diagnostics()["liveness"]["config"]
        s.advance(60, n=2)
        j1 = jobs[-1] if jobs else None
        check("first sighting is no change (no time), the next change is: the job carries the configuration-poll text's "
              "change time, separate from the telemetry liveness, and the diagnostics show its age",
              first_sight == {"mapped": True, "age_s": None} and j1 is not None and j1.config_liveness_at == cfg["changed"]
              and j1.liveness_at is not None and s.c.diagnostics()["liveness"]["config"]["age_s"] == 30.0,
              f"{first_sight} {j1 and j1.config_liveness_at} {cfg['changed']}")
        last_change = cfg["changed"]
        cfg["frozen"] = s.hass.states._states[cfg_spec["entity"]].state
        s.advance(60, n=5)
        recent = [j for j in jobs if j.now > last_change + timedelta(seconds=60)]
        check("a frozen configuration-poll text keeps its last change time (it grows old) while the telemetry liveness "
              "keeps moving", recent and all(j.config_liveness_at == last_change for j in recent)
              and recent[-1].liveness_at > last_change + timedelta(seconds=120)
              and s.c.diagnostics()["liveness"]["config"]["age_s"] >= 330.0,
              f"{[(j.now.isoformat(), j.config_liveness_at) for j in recent[-2:]]}")
        s.close()
        jobs.clear()
        # the harness maps the configuration-poll liveness by default (WP-3), so "not mapped" drops it from the map
        s = Scn("config_unmapped", H.site_profile(readings={k: v for k, v in H.READING_MAP.items()
                                                            if k != SD.CONFIG_LIVENESS_KEY}))
        H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0}, []))
        s.warm()
        check("not mapped -> no configuration-poll liveness time in the job", jobs and all(j.config_liveness_at is None for j in jobs)
              and s.c.diagnostics()["liveness"]["config"] == {"mapped": False, "age_s": None})
        s.close()
    finally:
        ENGINE_LINK.compute = orig_compute

    print("== T1: cycle timing in the diagnostics")
    calls = []
    s = Scn("timing", H.site_profile())
    H.inject(s.c, scripted_cycle(lambda n: {"valid_s": 180.0, "sleep": 0.6}, calls))
    s.advance(60, n=2, settle=5)                  # the first (slot) cycle runs at the second tick (grace 120 s)
    lt1 = dict(s.c.diagnostics()["last_cycle_timing"])
    s.advance(60, settle=5)
    lt2 = dict(s.c.diagnostics()["last_cycle_timing"])
    dl = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    check("a slot cycle whose engine job takes 0.6 s: engine_s >= 0.6 and total_s covers recorder + engine + store; the "
          "engine's CPU time is recorded", lt1.get("kind") == "SLOT" and lt1.get("outcome") == "published"
          and lt1["engine_s"] >= 0.6 and lt1["total_s"] >= lt1["engine_s"] + lt1["recorder_s"] + lt1["store_s"] - 1e-6
          and lt1["cpu_s"] is not None and lt1["recorder_s"] > 0, str(lt1))
    check("... a refresh reads neither the recorder nor the store (its recorder_s and store_s are 0)",
          lt2.get("kind") == "REFRESH" and lt2["recorder_s"] == 0.0 and lt2["store_s"] == 0.0 and lt2["engine_s"] >= 0.6, str(lt2))
    check("... and the diagnostics download carries cycle_stats (both kinds) and the cadence state, JSON-serialisable and "
          "without an entity id", dl["cycle_stats"]["by_kind"]["SLOT"]["n"] == 1 and dl["cycle_stats"]["by_kind"]["REFRESH"]["n"] == 1
          and dl["cycle_duration_s"] == lt2["total_s"] and "cadence" in dl and json.dumps(dl, allow_nan=False)
          and "test_dongle" not in json.dumps(dl) and "sensor.test" not in json.dumps(dl), json.dumps(dl.get("cycle_stats"))[:300])
    s.close()

    print("== supervision steady while the poll text moves (supervision aged by the telemetry poll, WP-1)")
    check("WP-1 is merged: the vendored site_decisions puts supervision.state and supervision.stable in DONGLE_READINGS",
          "supervision.state" in SD.DONGLE_READINGS and "supervision.stable" in SD.DONGLE_READINGS)
    s = Scn("supervision_steady", H.site_profile(decisions=H.owner_decisions()))
    sup_t = h.now - timedelta(minutes=10)

    def sup_not_rewritten(scn):
        scn.hass.states.seed("sensor.test_supervision_status", "SUPERVISED", changed_at=sup_t, reported_at=sup_t)
        scn.hass.states.seed("binary_sensor.test_supervision_stable", "on", changed_at=sup_t, reported_at=sup_t)
    s.after_seed = sup_not_rewritten
    sup_not_rewritten(s)
    s.warm()
    s.advance(60, n=10)
    sup_codes = [c_ for k in ("export_event", "dump_to_grid") for c_ in s.attrs(k).get("reason_codes", [])]
    check("supervision unchanged for over 10 minutes (not re-reported) while the poll text moves: export and Dump "
          "advice are not withheld for supervision", "SUPERVISION_NOT_STABLE" not in sup_codes, str(sup_codes))
    s.frozen_poll = h.now.strftime("%Y-%m-%d %H:%M:%S")
    s.advance(60, n=3)                      # the frozen text is seen at the first tick; 120 s later a cycle runs
    lc = s.c._last_computed
    ex = {i.key: i for i in lc.items}
    sup_codes = [c_ for k in ("export_event", "dump_to_grid") for c_ in [b_[0] for b_ in ex[k].blockers] + list(ex[k].reason_codes)]
    check("... the poll text frozen for more than 90 s: the cycle computed then withholds export and Dump advice "
          "(SUPERVISION_NOT_STABLE) and no export number is shown", (h.now - lc.generated_at).total_seconds() < 60
          and "SUPERVISION_NOT_STABLE" in sup_codes and not s.items_numeric(("export_event", "dump_to_grid")),
          f"{lc.generated_at} {sup_codes}")
    s.close()

    print("== diagnostics are redacted")
    s = Scn("diagnostics", H.site_profile())
    d = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    check("entity ids, the configuration hash and the git sha are redacted", d["entities"] == "**REDACTED**"
          and d["versions"]["config_hash"] == "**REDACTED**" and d["versions"]["git_sha"] == "**REDACTED**")
    check("PROPOSED constants are shown as PROPOSED", all(k.startswith("PROPOSED_") for k in d["proposed_constants"]))
    n_keep = CONST.PROPOSED_CYCLE_STATS_N
    # the most cycle starts 72 h can hold: a refresh starts at least PROPOSED_REFRESH_FLOOR_S after the previous start of
    # either kind, and a slot cycle may start at each schedule slot (every full hour and 21:30: at most 26 a day)
    most_72h = int(72 * 3600 // CONST.PROPOSED_REFRESH_FLOOR_S) + 1 + 3 * 26
    check("A50: cycle_stats keeps at least 4800 runs, more than the 72 h acceptance can start at the highest cycle rate "
          f"({most_72h}), in a bounded deque", n_keep >= 4800 and n_keep >= most_72h
          and s.c.cycle_stats.maxlen == n_keep and d["proposed_constants"]["PROPOSED_CYCLE_STATS_N"] == n_keep,
          f"{n_keep} {most_72h} {s.c.cycle_stats.maxlen}")
    t_cs = h.now
    timing_ = {"recorder_s": 0.0, "engine_s": 0.25, "store_s": 0.0, "cpu_s": 0.25}
    for i in range(n_keep + 250):
        s.c._finish(t_cs + timedelta(seconds=55 * i), "SLOT" if i % 65 == 0 else "REFRESH", "published", timing_, 0.31,
                    "POLL", 3.0)
    d = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    text = json.dumps(d, allow_nan=False)
    runs_ = d["cycle_stats"]["runs"]
    mem = sum(sys.getsizeof(r_) + sum(sys.getsizeof(x) for x in r_) for r_ in s.c.cycle_stats)
    check("... it holds exactly that many after more runs (the oldest dropped), the download carries them all, "
          "JSON-serialisable and under 2 MB, and the kept rows stay under 4 MB of memory",
          d["cycle_stats"]["kept"] == len(runs_) == n_keep == d["cycle_stats"]["max_kept"]
          and runs_[0][0] == (t_cs + timedelta(seconds=55 * 250)).isoformat() and len(text) < 2_000_000 and mem < 4_000_000,
          f"kept {d['cycle_stats']['kept']} size {len(text)} mem {mem}")
    check("... and the full download is still redacted as before (entity ids, the configuration hash, the git sha; no "
          "entity id anywhere)", d["entities"] == "**REDACTED**" and d["versions"]["config_hash"] == "**REDACTED**"
          and d["versions"]["git_sha"] == "**REDACTED**" and "test_dongle" not in text and "sensor.test" not in text)
    s.close()
finally:
    h.loop.close()
    H.rmtree_own(root, PREFIX)


print("")
for p_ in PENDING:
    print(f"  PENDING  {p_}")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime L2 (stand-in Home Assistant):")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime L2 (stand-in Home Assistant) checks passed")
