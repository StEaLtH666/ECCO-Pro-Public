#!/usr/bin/env python3
"""L2: the quiet cycle, the publish horizon kept and the cool-down, on the BUILT kit under the stand-in Home Assistant.

While a cycle is in flight (from the moment _maybe_start creates its task until it has ended) no timer of the integration
fires and none is created; the tick body still runs at least every TICK_S + PROPOSED_TICK_MARGIN_S; every executor job
ends with the SUBMIT_COOLDOWN_S cool-down. Callbacks are fired inside the running loop where the order matters, and the
stand-in's clock is moved by the test (the harness's job wait follows it for the tick body's deadline).

  [1] the quiet cycle: a cycle's start detaches the tick (counted in ticks_deferred) and cancels a pending poll-driven
      step, keeping its due time (poll_steps_held_busy); while the cycle runs a poll is noted inline (the text, the
      time, the count, polls_seen) but arms no step: its due time only moves earlier (A33: a second poll keeps the earlier
      one), and no timer or one-shot is created at all until the cycle ends; the diagnostics show it
  [2] the cycle's end: the second-run guard is released, then the tick body runs once as the catch-up, in the cycle task;
      the tick is attached again (one active timer, first due 60 s after the end: its phase follows the end) and the held
      step is armed at max(its due time, now) (a due time after the end: armed there; one that passed during the cycle:
      armed at the end); fired, it meets the floor as before (deferred to the floor's end); after a cycle the catch-up
      starts no refresh (the floor)
  [3] a slot that fell due while a cycle ran starts from the catch-up at that cycle's end (the guard released first), at
      once; while that slot cycle runs (its engine job held) no timer and no one-shot is active and none was created (the
      catch-up start is a cycle start like any other), and the held step stays held; the tick is attached again, and the
      held step armed, only when that slot cycle has ended
  [4] the publish horizon inside a cycle: an engine job held for more than two minutes (its wait starting 10 s after the
      tick body's run: the history inputs take that long on the stand-in's clock) gets the tick body run by the cycle
      task itself at each deadline (its last run plus TICK_S, the moment the tick would have come; tick_deadline_runs),
      with no timer attached meanwhile, and the cycle then publishes (that cycle, started by the tick, ran none at its
      first step); each deadline run comes the whole PROPOSED_TICK_MARGIN_S before the horizon the publish before it
      mapped its payloads to (so the margin takes the run's own latency and no number outlives its valid_until); a
      cycle the tick body did not start runs it at its first step, before any job (tick_start_runs): 63 s after its last
      run (so a settle hold right after meets no deadline), and 2 s after a tick body that started nothing, so its
      deadline run comes TICK_S after the cycle's start, not TICK_S after that tick; the real job wait times out on the
      loop's clock and leaves the job running
  [5] the tick body never goes longer than TICK_S + PROPOSED_TICK_MARGIN_S without running: 90 minutes of polls (60 s plus
      or minus 3 s) with jobs that take time on the stand-in's clock (polls that arrive during a job reach the listener at
      their time), cycles that hold their snapshot for a poll seen since their start, recorder reads at the slots and one
      engine job of 110 s, every tick-body run recorded, each deadline run the whole margin before the horizon of the
      publish before it; and in steady poll-driven operation (a cycle each poll, jobs of a few seconds) its deadline run
      never comes
  [6] the cool-down: every executor job the integration submits (the import, the start-up gates, the recorder read, the
      scorecard metrics, the engine, the store write) goes through released_call and completes at least
      SUBMIT_COOLDOWN_S after its target returned; a target that raises cools down too; SUBMIT_COOLDOWN_S is 0.15 s (more
      than one 100 ms CPU-quota period); cycle_stats names the timings that include it, and a real engine job's engine_s
      does
  [7] unload and cancel during a cycle: an unload leaves no timer, no one-shot and no held step, and the cycle's end after
      it attaches nothing and runs no catch-up; a cancel (Home Assistant's shutdown cancel) ends the cycle, runs the
      catch-up and attaches the tick again, with the held step armed; Home Assistant's shutdown itself (Core stopping,
      the task cancelled, the entry not unloaded): the catch-up runs and publishes, no cycle starts although a slot is
      due, and the tick and the held step come back; an engine thread abandoned at the time budget gets
      the tick attached again at the cycle's end (so the tick runs every minute while it hangs), a poll meanwhile arms
      nothing, and the step is armed when the thread ends, but not after an unload; that overrun runs through the real
      job wait (asyncio.wait_for on a shielded job, the loop's clock), the one budget scenario here that does
  [8] RR-N1: a snapshot hold cut short by the cycle's deadline is read inside the settle delay: counted in
      snapshot_residual_reads, and the cycle does not cover that poll (its step is deferred to the floor's end)
  [9] the end of a failed cycle: a cycle that ends 'self_test_failed' (an entity write that raised in its start run's
      publish) and one that ends 'discarded_failed' (an entity write that raised at the deadline run while the engine
      computed) still get the catch-up, the tick attached again (first due TICK_S after the end) and the held step armed
  [10] the held step armed unheld: a settle hold's step held through a cycle is armed unheld at the cycle's end, so when
      it comes inside the settle delay of a poll seen in the cycle's last 3 s it is held once more (no start inside that
      delay, no residual) and the cycle starts at the delay's end
  [11] the diagnostics raise: when recording a cycle's diagnostics (_finish) raises at its end, the guard is released and
      the catch-up, the tick and the held step still come back
  [12] the catch-up raises: when the catch-up's tick body raises at a cycle's end (after the diagnostics were recorded),
      the exception leaves the cycle task, and the tick (first due TICK_S after the end) and the held step (at its due
      time) still come back
Every scenario also ends with zero write attempts and no stand-in violation. Plain script; exits 1 on any failure.
"""

from __future__ import annotations

import asyncio
import importlib
import random
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
PREFIX = "ecco_intel_quiet_cycle_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)

h = H.Harness(kit)
C = h.contract
PKG = h.integration
COORD = importlib.import_module("custom_components.ecco_intelligence.coordinator")
CONST = importlib.import_module("custom_components.ecco_intelligence.const")
ENGINE_LINK = importlib.import_module("custom_components.ecco_intelligence.runtime.engine_link")
ORIG_COMPUTE = ENGINE_LINK.compute
ORIG_SETTLE_WAIT = COORD._settle_wait
CYCLE = CONST.CYCLE_TASK_NAME
TICK = CONST.TICK_S
MARGIN = CONST.PROPOSED_TICK_MARGIN_S
SPAN = TICK + MARGIN
SETTLE = timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S)
FLOOR = timedelta(seconds=CONST.PROPOSED_REFRESH_FLOOR_S)


def s_(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


def in_cycle() -> bool:
    try:
        t = asyncio.current_task()
    except RuntimeError:
        return False
    return t is not None and t.get_name() == CYCLE


def wait_for(pred, timeout: float = 15.0) -> bool:
    """Run the loop until pred() holds (or the timeout)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        h.settle(0.05)
        time.sleep(0.01)
    return pred()


class World:
    """One stand-in Home Assistant with the integration set up at `start` (owner-record decisions, fresh states, the
    start-up grace 0). The engine job can be held (`block`: that many next jobs wait for `gate`); every run of the tick
    body is recorded: (the clock, in the cycle task, the second-run guard, active timers, active one-shots, engine
    jobs so far); so is every publish (the clock, the publish horizon it mapped its payloads to) and every deadline run
    of the tick body inside a cycle (the clock, the publishes before it)."""

    def __init__(self, name: str, *, start: datetime = NOW, events: bool = True) -> None:
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, start)
        H.write_site(self.cfg, H.site_profile(decisions=H.owner_decisions()))
        H.seed_fresh_states(self.hass.states, start, telemetry_at=start - s_(30), config_at=start - s_(30))
        h.recorder().statistics = H.synthetic_statistics(start, days=30)
        self.hass.states.events = events
        self.entry = h.new_entry()
        self.start = start
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 0.0
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.block = 0
        self.on_enter = None                               # run on the loop when a held engine job has entered
        self.jobs: list = []
        self.ticks: list[tuple] = []
        o_tick = self.c._tick_body  # noqa: SLF001

        def tick_body(now, _o=o_tick):
            self.ticks.append((h.now, in_cycle(), self.c._busy, len(self.active_timers()),  # noqa: SLF001
                               len(self.active_later()), len(self.jobs)))
            return _o(now)
        self.c._tick_body = tick_body  # noqa: SLF001
        self.pubs: list[tuple] = []
        self.deadline_at: list[tuple] = []
        o_pub, o_deadline = self.c._publish, self.c._deadline_tick  # noqa: SLF001

        def publish(env, now, _o=o_pub):
            if not self.c.closed:
                self.pubs.append((h.now, COORD.publish_horizon(now)))
            return _o(env, now)

        def deadline_tick(_o=o_deadline):
            self.deadline_at.append((h.now, len(self.pubs)))
            return _o()
        self.c._publish, self.c._deadline_tick = publish, deadline_tick  # noqa: SLF001
        ENGINE_LINK.compute = self._compute

    def _compute(self, job, run_cycle=None):
        self.jobs.append(job)
        if self.block > 0:
            self.block -= 1
            if self.on_enter is not None:
                h.loop.call_soon_threadsafe(self.on_enter)
            self.entered.set()
            self.gate.wait(60)
        return ORIG_COMPUTE(job, run_cycle)

    def active_timers(self) -> list:
        return [t for t in self.hass.timers if t["active"]]

    def active_later(self) -> list:
        return [t for t in self.hass.later if t["active"]]

    def in_loop(self, fn, probe=None):
        """Run fn() inside one loop callback, then probe() in the same callback; return (fn's result, probe's)."""
        out: dict = {}

        async def go() -> None:
            fut = h.loop.create_future()

            def cb() -> None:
                try:
                    out["ret"] = fn()
                    out["probe"] = probe() if probe is not None else None
                finally:
                    fut.set_result(None)
            h.loop.call_soon(cb)
            await fut
        h.run(go())
        return out.get("ret"), out.get("probe")

    def fire_tick(self) -> None:
        t = self.active_timers()[0]
        t["action"](h.now)

    def poll(self, at: datetime | None = None) -> None:
        at = at or h.now
        H.seed_fresh_states(self.hass.states, at, telemetry_at=at, config_at=at)

    def fire_due_step(self) -> bool:
        due = [t for t in self.hass.later if t["active"] and t["due"] <= h.now]
        if not due:
            return False
        t = min(due, key=lambda x: x["due"])
        t["active"] = False
        self.in_loop(lambda: t["action"](h.now))
        h.settle(5.0)
        return True

    def rows(self) -> list:
        f = list(COORD.CYCLE_STATS_FIELDS)
        return [dict(zip(f, r)) for r in self.c.cycle_stats]

    def clean(self) -> bool:
        return not self.hass.write_attempts and not self.hass.violations

    def close(self) -> None:
        self.gate.set()
        ENGINE_LINK.compute = ORIG_COMPUTE
        COORD._settle_wait = ORIG_SETTLE_WAIT
        if not self.c.closed:
            h.unload(self.entry)
        wait_for(lambda: not self.c._orphans, 10.0)  # noqa: SLF001


def hung_start(w: World, *, step_due: datetime | None = None, block: int = 1) -> dict:
    """At the current clock: (optionally) a pending poll-driven step armed at step_due (as the floor deferral or a settle
    hold leaves one), then the tick fired in the same loop callback, starting a cycle whose engine job is held. Returns
    the probe taken in that callback, right after the start."""
    w.block = block
    w.entered.clear()

    def go():
        if step_due is not None:
            w.c._arm_poll_step(step_due)  # noqa: SLF001
        w.fire_tick()

    _r, pr = w.in_loop(go, lambda: {"busy": w.c._busy, "live": w.c._cycle_live,  # noqa: SLF001
                                    "timers": len(w.active_timers()), "later": len(w.active_later()),
                                    "due": w.c._poll_due, "runs": w.c.counters["runs_started"]})  # noqa: SLF001
    wait_for(w.entered.is_set)                          # the loop runs meanwhile (the cycle reaches its job)
    h.settle(0.2)
    return pr


def hung_step(w: World, block: int = 1) -> None:
    """A poll 3 s ago, its step fired now in a loop callback: a poll-driven refresh whose engine job is held."""
    t = h.now
    h.set_now(t - SETTLE)
    w.poll()
    h.set_now(t)
    w.block = block
    w.entered.clear()
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: step["action"](h.now))
    wait_for(w.entered.is_set)                          # the loop runs meanwhile (the cycle reaches its job)
    h.settle(0.2)


def deadline_slack(w: World) -> list[float]:
    """For each deadline run of the tick body inside a cycle: the seconds from that run to the publish horizon of the
    publish before it (the moment the entities' payloads were mapped to, so the latest moment they may still show a
    number). The run must come strictly before it; here, on the stand-in's clock, the whole PROPOSED_TICK_MARGIN_S
    before it, which is what a real run's latency (the job wait's timeout, the cycle task's next step) may use."""
    return [(w.pubs[n - 1][1] - at).total_seconds() if n else float("-inf") for at, n in w.deadline_at]


STAND_IN_WAIT = None

try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== [1] the quiet cycle: no timer of the integration while a cycle is in flight")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("quiet")
    check("after setup: exactly one timer, the tick (TICK_JOB_NAME), and no one-shot",
          len(w.active_timers()) == 1 and w.active_timers()[0]["name"] == CONST.TICK_JOB_NAME and not w.active_later(),
          str([(t["name"], t["active"]) for t in w.hass.timers]))
    t1 = NOW + s_(60)
    h.set_now(t1)
    due0 = t1 + s_(30)
    c0 = dict(w.c.counters)
    pr = hung_start(w, step_due=due0)
    check("a cycle starts at the tick with a step pending: in that same callback the tick is detached (ticks_deferred) "
          "and the step cancelled, its due time kept (poll_steps_held_busy); the guard set before the task runs",
          pr["busy"] and pr["live"] and pr["timers"] == 0 and pr["later"] == 0 and pr["due"] == due0
          and pr["runs"] == c0["runs_started"] + 1 and w.c.counters["ticks_deferred"] == c0["ticks_deferred"] + 1
          and w.c.counters["poll_steps_held_busy"] == c0["poll_steps_held_busy"] + 1, str(pr))
    n_timers, n_later = len(w.hass.timers), len(w.hass.later)
    seq0, seen0 = w.c._poll_seq, w.c.counters["polls_seen"]  # noqa: SLF001
    text0 = w.c._poll_text  # noqa: SLF001
    p1 = t1 + s_(1)
    h.set_now(p1)
    w.poll()
    h.settle(0.1)
    d = w.c.diagnostics()["cadence"]
    check("a poll while it runs is noted inline (the text, the time, the count, polls_seen) and arms no step: its step's "
          "due time moves earlier only (A33), held (poll_steps_held_busy)",
          w.c._poll_text != text0 and w.c._poll_seen_at == p1 and w.c._poll_seq == seq0 + 1  # noqa: SLF001
          and w.c.counters["polls_seen"] == seen0 + 1 and w.c._poll_due == p1 + SETTLE  # noqa: SLF001
          and not w.active_later() and w.c.counters["poll_steps_held_busy"] == c0["poll_steps_held_busy"] + 2,
          f"{w.c._poll_due} {w.active_later()} {w.c.counters['poll_steps_held_busy']}")  # noqa: SLF001
    kept0 = w.c.counters["poll_steps_kept_earlier"]
    h.set_now(p1 + s_(1))
    w.poll()
    h.settle(0.1)
    check("... a second poll keeps the earlier due time (A33, kept_earlier) and arms nothing either",
          w.c._poll_due == p1 + SETTLE and w.c.counters["poll_steps_kept_earlier"] == kept0 + 1  # noqa: SLF001
          and not w.active_later() and w.c._poll_seq == seq0 + 2, str(w.c._poll_due))  # noqa: SLF001
    check("... and while the cycle is in flight no timer and no one-shot was created at all (none active, none new)",
          len(w.hass.timers) == n_timers and len(w.hass.later) == n_later and not w.active_timers()
          and not w.active_later(), f"{len(w.hass.timers)} {n_timers} {len(w.hass.later)} {n_later}")
    check("... the diagnostics show it: cycle in flight, tick detached, no step armed, its due time kept",
          d["cycle_in_flight"] is True and d["tick_attached"] is False and d["poll_step_armed"] is False
          and d["poll_step_due"] == (p1 + SETTLE).isoformat() and w.c.diagnostics()["busy"] is True, str(d))

    # -----------------------------------------------------------------------------------------------------------------
    print("== [2] the cycle's end: the catch-up tick body, the tick attached again, the step armed at max(due, now)")
    # -----------------------------------------------------------------------------------------------------------------
    end1 = p1 + s_(1.5)                                # before the held step's due time (p1 + 3 s)
    h.set_now(end1)
    n_ticks, catch0 = len(w.ticks), w.c.counters["catchup_ticks"]
    w.gate.set()
    check("the cycle ends and publishes", wait_for(lambda: not w.c._busy and w.c.counters["runs_published"] == 1),  # noqa: SLF001
          str(w.c.counters["runs_published"]))
    new_ticks = w.ticks[n_ticks:]
    check("the tick body runs once at the end, as the catch-up: in the cycle task, after the second-run guard was released",
          w.c.counters["catchup_ticks"] == catch0 + 1 and len(new_ticks) == 1 and new_ticks[0][0] == end1
          and new_ticks[0][1] is True and new_ticks[0][2] is False and w.c._tick_ran_at == end1,  # noqa: SLF001
          str(new_ticks))
    tm = w.active_timers()
    check("... the tick is attached again: one active timer, a new one, first due 60 s after the end (its phase follows "
          "the cycle's end)", len(tm) == 1 and len(w.hass.timers) == n_timers + 1 and tm[0]["next"] == end1 + s_(60)
          and tm[0]["name"] == CONST.TICK_JOB_NAME, str([(t["next"], t["active"]) for t in w.hass.timers]))
    check("... the held step is armed at its due time, which comes after the end (max(due, now))",
          [t["due"] for t in w.active_later()] == [p1 + SETTLE] and w.c._poll_due == p1 + SETTLE,  # noqa: SLF001
          str([t["due"] for t in w.active_later()]))
    check("... and the catch-up started no cycle (after a cycle the floor bars a refresh)",
          w.c.counters["runs_started"] == c0["runs_started"] + 1, str(w.c.counters["runs_started"]))
    h.set_now(p1 + SETTLE)
    deferred0 = w.c.counters["poll_steps_deferred_floor"]
    fired = w.fire_due_step()
    check("fired at its due time, the step meets the floor as before: deferred to the floor's end, no cycle",
          fired and w.c.counters["poll_steps_deferred_floor"] == deferred0 + 1
          and w.c._poll_due == t1 + FLOOR and w.c.counters["runs_started"] == c0["runs_started"] + 1,  # noqa: SLF001
          f"{fired} {w.c._poll_due}")  # noqa: SLF001
    # a second cycle: the step at the floor's end refreshes; a poll during it; the cycle ends after that poll's due time
    t2 = t1 + FLOOR
    h.set_now(t2)
    w.block, w.entered = 1, threading.Event()
    w.gate = threading.Event()
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: step["action"](h.now))
    wait_for(w.entered.is_set)                          # the loop runs meanwhile (the cycle reaches its job)
    h.settle(0.2)
    check("non-vacuity: the step at the floor's end started a poll-driven refresh, held in flight",
          w.c._busy and w.c._last_trigger == COORD.POLL and w.c._last_kind == COORD.REFRESH,  # noqa: SLF001
          f"{w.c._busy} {w.c._last_trigger} {w.c._last_kind}")  # noqa: SLF001
    p2 = t2 + s_(1)
    h.set_now(p2)
    w.poll()
    h.settle(0.1)
    end2 = p2 + s_(10)                                 # after that poll's step was due (p2 + 3 s)
    h.set_now(end2)
    w.gate.set()
    wait_for(lambda: not w.c._busy)  # noqa: SLF001
    check("a poll whose step fell due while the cycle ran: armed at the end (max(due, now) = now), the tick first due 60 s "
          "after that end", [t["due"] for t in w.active_later()] == [end2] and w.c._poll_due == end2  # noqa: SLF001
          and [t["next"] for t in w.active_timers()] == [end2 + s_(60)],
          f"{[t['due'] for t in w.active_later()]} {[t['next'] for t in w.active_timers()]}")
    deferred0 = w.c.counters["poll_steps_deferred_floor"]
    fired = w.fire_due_step()
    check("... fired at once, it meets the floor of the refresh that just ran (deferred to its end, never dropped)",
          fired and w.c.counters["poll_steps_deferred_floor"] == deferred0 + 1 and w.c._poll_due == t2 + FLOOR,  # noqa: SLF001
          str(w.c._poll_due))  # noqa: SLF001
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [3] a slot that fell due while a cycle ran starts from the catch-up at its end")
    # -----------------------------------------------------------------------------------------------------------------
    s3 = datetime(2030, 1, 15, 20, 58, 30, tzinfo=UTC)
    end3 = datetime(2030, 1, 15, 21, 0, 5, tzinfo=UTC)
    due3 = end3 + s_(20)                                # a pending step, held through both cycles
    w = World("slot_due", start=s3, events=False)       # no poll seen: the tick's own rules
    h.set_now(s3 + s_(60))                              # 20:59:30
    pr = hung_start(w, step_due=due3)
    h.set_now(end3)
    n_timers, n_later = len(w.hass.timers), len(w.hass.later)
    gate1 = w.gate
    w.gate, w.block = threading.Event(), 1              # the slot cycle the catch-up starts: its engine job held too
    w.entered.clear()
    gate1.set()
    check("the cycle ends and publishes; the 21:00 slot that fell due meanwhile starts from the catch-up at once and "
          "reaches its engine job (held)", wait_for(lambda: w.entered.is_set() and w.c.counters["runs_published"] == 1)
          and w.c._busy and w.c._cycle_live and w.c.counters["runs_started"] == 2,  # noqa: SLF001
          f"{w.entered.is_set()} {w.c.counters['runs_published']} {w.c.counters['runs_started']}")
    h.settle(0.2)
    check("... while that slot cycle runs no timer and no one-shot is active and none was created since the first cycle "
          "started (the catch-up start keeps the quiet cycle: the tick is not attached again in between), and the held "
          "step stays held (its due time kept, not armed)",
          not w.active_timers() and not w.active_later() and len(w.hass.timers) == n_timers
          and len(w.hass.later) == n_later and w.c._poll_due == due3 and w.c._poll_cancel is None  # noqa: SLF001
          and w.c.diagnostics()["cadence"]["tick_attached"] is False,
          f"{[(t['next'], t['active']) for t in w.hass.timers]} {n_timers} {[t['due'] for t in w.active_later()]} "
          f"{w.c._poll_due}")  # noqa: SLF001
    w.gate.set()
    check("... then it ends and publishes too", wait_for(lambda: w.c.counters["runs_published"] == 2
                                                          and not w.c._busy), str(w.c.counters))  # noqa: SLF001
    rows = w.rows()
    catch = [t for t in w.ticks if t[0] == end3 and t[1]]
    check("... the second cycle is that slot, started at the first one's end by the tick body run there (in the cycle task, "
          "the guard already released)",
          [(r["kind"], r["trigger"], r["started_at"]) for r in rows] == [("SLOT", "TICK", (s3 + s_(60)).isoformat()),
                                                                         ("SLOT", "TICK", end3.isoformat())]
          and len(catch) >= 1 and catch[0][2] is False, f"{[(r['kind'], r['started_at']) for r in rows]} {catch}")
    check("... the tick was attached again only when the slot cycle had ended (one new timer, first due 60 s after it), "
          "and the held step armed then, at its due time",
          len(w.hass.timers) == n_timers + 1 and [t["next"] for t in w.active_timers()] == [end3 + s_(60)]
          and [t["due"] for t in w.active_later()] == [due3],
          f"{len(w.hass.timers)} {n_timers} {[t['next'] for t in w.active_timers()]} "
          f"{[t['due'] for t in w.active_later()]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [4] the publish horizon inside a cycle: the tick body at its deadline")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("deadline")
    t4 = NOW + s_(60)
    h.set_now(t4)
    h.clear_world()                                     # the job waits schedule the deadline's moment as a world event
    o_hist = w.c._history_inputs  # noqa: SLF001

    async def slow_history(*args, _o=o_hist):
        out = await _o(*args)
        h.set_now(h.now + s_(10))                       # the history inputs take 10 s on the clock: the engine job's wait
        return out                                      # starts 10 s after the tick body's run, its deadline 50 s later
    w.c._history_inputs = slow_history  # noqa: SLF001
    hung_start(w)
    release = t4 + s_(140)
    h.at(release, w.gate.set)
    n_ticks = len(w.ticks)
    h.run_until(t4 + s_(150), settle=1.0)
    check("the cycle publishes after its engine job was held 140 s", wait_for(lambda: not w.c._busy)  # noqa: SLF001
          and w.c.counters["runs_published"] == 1, str(w.c.counters["runs_published"]))
    runs = w.ticks[n_ticks:]
    dl = [r for r in runs if r[2]]
    check("meanwhile the cycle task ran the tick body itself at each deadline (TICK_S after its last run, when the tick "
          "would have come, then TICK_S after that), with the guard set, no timer attached and no one-shot armed; counted "
          "in tick_deadline_runs", [r[0] for r in dl] == [t4 + s_(TICK), t4 + s_(2 * TICK)]
          and all(r[1] and r[3] == 0 and r[4] == 0 for r in dl) and w.c.counters["tick_deadline_runs"] == 2
          and [x[0] for x in w.deadline_at] == [t4 + s_(TICK), t4 + s_(2 * TICK)], str(runs))
    slack = deadline_slack(w)
    check(f"... each deadline run came strictly before the horizon the publish before it mapped its payloads to, the whole "
          f"PROPOSED_TICK_MARGIN_S ({MARGIN:g} s) before it, left for the run's own latency (so no number outlives its "
          f"valid_until): {slack}", len(slack) == 2 and all(x >= MARGIN - 1e-6 for x in slack), str(slack))
    check("... the cycle, started by the tick (whose body had just run), ran no tick body at its first step",
          w.c.counters["tick_start_runs"] == 0, str(w.c.counters["tick_start_runs"]))
    check("... and the catch-up at the cycle's end: the tick body never went longer than TICK_S + PROPOSED_TICK_MARGIN_S "
          "without running", [r[0] for r in runs] == [t4 + s_(TICK), t4 + s_(2 * TICK), release]
          and runs[-1][2] is False and [t["next"] for t in w.active_timers()] == [release + s_(60)], str(runs))
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # a cycle the tick body did not start (here 63 s after its last run) runs it at its first step
    w = World("start_run")
    h.set_now(NOW + s_(60))
    w.fire_tick()                                       # the first cycle; its catch-up runs the tick body at NOW + 60
    h.settle(5.0)
    h.set_now(NOW + s_(120))
    w.poll()                                            # its step at NOW + 123 (the tick, due at NOW + 120, not fired)
    h.set_now(NOW + s_(123))
    holds: list = []

    async def hold(seconds):
        holds.append((h.now, seconds, w.c.counters["tick_start_runs"], w.c.counters["tick_deadline_runs"]))
        h.set_now(h.now + s_(seconds))
        await asyncio.sleep(0)
    COORD._settle_wait = hold
    late = {}

    def late_poll():
        h.set_now(h.now + s_(0.5))
        late["at"] = h.now
        w.hass.states.seed(H.eid("sensor", "last_telemetry_update"), H.poll_time_text(h.now), changed_at=h.now)
    n_ticks, n_jobs = len(w.ticks), len(w.jobs)
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: (step["action"](h.now), h.loop.call_soon(late_poll)))
    h.settle(5.0)
    COORD._settle_wait = ORIG_SETTLE_WAIT
    runs = w.ticks[n_ticks:]
    check("a poll-driven cycle 63 s after the tick body's last run: the cycle task runs the tick body at its first step "
          "(tick_start_runs), with the guard set, no timer attached and before any job of the cycle; so a settle hold "
          "of 3 s right after it never meets the deadline (no deadline run)",
          len(runs) == 2 and runs[0][0] == NOW + s_(123) and runs[0][1] and runs[0][2] and runs[0][3] == 0
          and runs[0][4] == 0 and runs[0][5] == n_jobs and w.c.counters["tick_start_runs"] == 1
          and len(holds) == 1 and holds[0][0] == late.get("at") and holds[0][2:] == (1, 0)
          and w.c.counters["tick_deadline_runs"] == 0 and w.c.counters["runs_published"] == 2 and not runs[1][2],
          f"{holds} {runs}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # a cycle the tick body did not start runs it at its first step even 2 s after a tick body that started nothing, so
    # its deadline comes TICK_S after the cycle's start (never sooner: only a cycle longer than TICK_S meets it)
    w = World("start_run_near")
    h.set_now(NOW + s_(60))
    w.fire_tick()                                       # the first cycle; its catch-up runs the tick body at NOW + 60
    h.settle(5.0)
    h.set_now(NOW + s_(120))
    w.poll()                                            # its step at NOW + 123
    h.set_now(NOW + s_(121))
    runs0 = w.c.counters["runs_started"]
    w.in_loop(w.fire_tick)                              # the tick at NOW + 121: its body runs, it starts no cycle
    near = (w.c._tick_ran_at, w.c.counters["runs_started"], w.c._busy)  # noqa: SLF001
    h.set_now(NOW + s_(123))
    h.clear_world()                                     # the job waits schedule the deadline's moment as a world event
    w.block = 1
    w.entered.clear()
    n_ticks = len(w.ticks)
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: step["action"](h.now))
    wait_for(w.entered.is_set)
    h.settle(0.2)
    started = (w.c._busy, w.c._last_trigger, w.c._last_start)  # noqa: SLF001
    release = NOW + s_(123 + 70)
    h.at(release, w.gate.set)
    h.run_until(release + s_(5), settle=1.0)
    wait_for(lambda: not w.c._busy)  # noqa: SLF001
    runs = w.ticks[n_ticks:]
    check("non-vacuity: the tick at NOW + 121 ran its body (not in a cycle) and started no cycle; the poll's step at NOW "
          "+ 123 started a poll-driven cycle, its engine job held 70 s, which then published",
          near == (NOW + s_(121), runs0, False) and started == (True, COORD.POLL, NOW + s_(123))
          and w.c.counters["runs_published"] == 2, f"{near} {started} {w.c.counters['runs_published']}")
    check("... the cycle's first step ran the tick body (tick_start_runs), 2 s after that tick's, so its one deadline run "
          "came at the cycle's start plus TICK_S (NOW + 183), not TICK_S after the tick (NOW + 181); then the catch-up",
          [r[0] for r in runs] == [NOW + s_(123), NOW + s_(183), release] and runs[0][1] and runs[0][5] == len(w.jobs) - 1
          and w.c.counters["tick_start_runs"] == 1 and [x[0] for x in w.deadline_at] == [NOW + s_(183)]
          and w.c.counters["tick_deadline_runs"] == 1, f"{runs} {w.deadline_at}")
    slack = deadline_slack(w)
    check(f"... that deadline run came the whole PROPOSED_TICK_MARGIN_S before the horizon of the publish before it "
          f"({slack})", len(slack) == 1 and slack[0] >= MARGIN - 1e-6, str(slack))
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # the real job wait: asyncio's, on the loop's clock, leaving the job running

    async def real_wait() -> tuple:
        fut = h.loop.run_in_executor(None, time.sleep, 0.3)
        t0 = h.loop.time()
        try:
            await h.real_job_wait(fut, 0.05)
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True
        dt = h.loop.time() - t0
        cancelled = fut.cancelled()
        await fut
        return timed_out, dt, cancelled, fut.done()
    timed_out, dt, cancelled, done = h.run(real_wait())
    check("the real job wait times out on the loop's clock (asyncio.TimeoutError) and leaves the job running to its end",
          timed_out and 0.04 <= dt < 0.25 and not cancelled and done, f"{timed_out} {dt:.3f} {cancelled}")

    # -----------------------------------------------------------------------------------------------------------------
    print("== [5] the tick body never goes longer than TICK_S + PROPOSED_TICK_MARGIN_S without running")
    # -----------------------------------------------------------------------------------------------------------------

    async def advance_to(target: datetime) -> None:
        """Move the stand-in's clock to `target` from inside a cycle, delivering every scripted world event due by then in
        time order, each at its own time (a poll while a job runs reaches the listener then)."""
        while True:
            world = getattr(h, "_world", [])
            due = [x for x in world if x[0] <= target]
            if not due:
                break
            ev = min(due, key=lambda x: (x[0], x[1]))
            world.remove(ev)
            if ev[0] > h.now:
                h.set_now(ev[0])
            ev[2]()
            for _ in range(3):
                await asyncio.sleep(0)
        if target > h.now:
            h.set_now(target)

    class ClockJobs:
        """Stands in for coordinator._job_wait: each executor job takes dur(name, n) seconds on the stand-in's clock (the
        real job runs first, in milliseconds). When the wait's timeout comes first (the tick body's deadline), the clock
        stops there and the wait times out; the next wait for the same job goes on with what is left."""
        _stand_in_clock = True                         # the harness keeps it installed

        def __init__(self, dur) -> None:
            self.dur, self.left, self.count, self.names = dur, {}, {}, {}
            self.log: list = []

        async def __call__(self, fut, timeout):
            await asyncio.wait({fut})
            k = id(fut)
            if k not in self.left:
                name = self.names.get(k, "?")
                n = self.count.get(name, 0)
                self.count[name] = n + 1
                self.left[k] = float(self.dur(name, n))
                self.log.append((h.now, name, self.left[k]))
            left = self.left[k]
            if left > timeout:
                await advance_to(h.now + s_(timeout))
                self.left[k] = left - timeout
                raise asyncio.TimeoutError
            await advance_to(h.now + s_(left))
            del self.left[k]
            return fut.result()

        def watch(self, world: World) -> None:
            """Name each job by its target as it is submitted (the engine, the recorder read, the metrics, the store)."""
            def wrap(orig):
                def submit(target, *args):
                    fut = orig(target, *args)
                    real = args[1] if getattr(target, "__name__", "") == "released_call" and len(args) > 1 else target
                    self.names[id(fut)] = getattr(real, "__name__", "?").lstrip("_")
                    return fut
                return submit
            world.hass.async_add_executor_job = wrap(world.hass.async_add_executor_job)
            rec = h.recorder()
            rec.async_add_executor_job = wrap(rec.async_add_executor_job)

    def poll_world(name: str, *, seed: int, dur, late_every: int, hours: float) -> tuple:
        """A poll-driven run of `hours`: the telemetry poll every 60 s plus or minus 3 s (each poll writes every mapped entity),
        jobs timed by `dur` on the stand-in's clock, and every `late_every`-th started cycle sees a further poll between
        its start and its snapshot (so it holds its snapshot). Returns (world, ClockJobs, the gaps between tick-body runs)."""
        start = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
        w = World(name, start=start)
        h.clear_world()
        rng = random.Random(seed)
        jobs = ClockJobs(dur)
        jobs.watch(w)
        prev_wait = COORD._job_wait
        COORD._job_wait = jobs
        COORD._settle_wait = lambda seconds: advance_to(h.now + s_(seconds))
        t_end = start + s_(hours * 3600)
        k = 0
        at = start + s_(20)
        while at < t_end:
            h.at(at, w.poll)
            k += 1
            at = start + s_(20 + 60 * k + rng.uniform(-3.0, 3.0))
        hour = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        for j in range(int(hours) + 1):
            h.at(hour + timedelta(hours=j), lambda: setattr(h.recorder(), "statistics", H.synthetic_statistics(h.now)))
        starts = {"n": 0}
        o_ms = w.c._maybe_start  # noqa: SLF001

        def maybe_start(now, trigger=COORD.TICK, held=False):
            started = o_ms(now, trigger, held=held)
            if started:
                starts["n"] += 1
                if late_every and starts["n"] % late_every == 0:
                    def late_poll():
                        h.set_now(h.now + s_(0.5))
                        w.poll()
                    h.loop.call_soon(late_poll)
            return started
        w.c._maybe_start = maybe_start  # noqa: SLF001
        try:
            h.run_until(t_end, settle=5.0)
        finally:
            COORD._job_wait = prev_wait
            COORD._settle_wait = ORIG_SETTLE_WAIT
        times = [w.start] + [t[0] for t in w.ticks]
        gaps = [(b_ - a_).total_seconds() for a_, b_ in zip(times, times[1:])]
        return w, jobs, gaps

    def stress(name: str, n: int) -> float:
        if name == "compute":
            return 110.0 if n == 30 else 2.0 + (n % 3)
        return {"statistics_during_period": 4.0, "outcome_metrics": 1.0, "record_cycle": 1.0}.get(name, 1.0)

    w, jobs, gaps = poll_world("horizon_stress", seed=31, dur=stress, late_every=4, hours=1.5)
    rows = w.rows()
    slots = [r for r in rows if r["kind"] == "SLOT"]
    longest = max((r["total_s"] for r in rows), default=0.0)
    check(f"non-vacuity: {len(rows)} cycles, among them {len(slots)} slot cycles that read the recorder, snapshot holds "
          f"({w.c.counters['snapshot_holds']}), polls during a job ({w.c.counters['poll_steps_held_busy']} held), one "
          "engine job of 110 s and the tick body's deadline runs inside it",
          len(rows) >= 80 and len(slots) >= 3 and h.recorder().calls >= 3 and w.c.counters["snapshot_holds"] >= 10
          and w.c.counters["poll_steps_held_busy"] >= 10 and any(x[1] == "compute" and x[2] == 110.0 for x in jobs.log)
          and w.c.counters["tick_deadline_runs"] >= 1 and w.c.counters["runs_published"] >= 80,
          f"{len(rows)} {len(slots)} {w.c.counters['snapshot_holds']} {w.c.counters['tick_deadline_runs']} {longest}")
    check(f"the tick body never went longer than TICK_S + PROPOSED_TICK_MARGIN_S ({SPAN:g} s) without running, across "
          f"the holds, the slot reads and the 110 s job (longest gap {max(gaps, default=0):g} s over {len(gaps)} runs)",
          gaps and max(gaps) <= SPAN, f"{sorted(gaps)[-5:]}")
    slack = deadline_slack(w)
    check(f"... and each of its {len(slack)} deadline runs came the whole PROPOSED_TICK_MARGIN_S ({MARGIN:g} s) before the "
          f"horizon of the publish before it (least {min(slack, default=0):g} s)",
          slack and len(slack) == w.c.counters["tick_deadline_runs"] and all(x >= MARGIN - 1e-6 for x in slack),
          str(slack))
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    def steady(name: str, n: int) -> float:
        if name == "compute":
            return 1.0 + (n % 2)
        return {"statistics_during_period": 1.5, "outcome_metrics": 0.5, "record_cycle": 0.5}.get(name, 0.5)

    w, jobs, gaps = poll_world("horizon_steady", seed=32, dur=steady, late_every=0, hours=1.5)
    rows = w.rows()
    polls = w.c.counters["polls_seen"]
    check(f"steady poll-driven operation (a cycle each poll: {len(rows)} cycles for {polls} polls, jobs of one or two "
          "seconds, a slot cycle 4.5 s in all): the tick body's deadline run never comes, and the tick body never went longer than "
          f"{SPAN:g} s without running (longest gap {max(gaps, default=0):g} s)",
          len(rows) >= polls - 2 and polls >= 85 and all(r["trigger"] == "POLL" for r in rows[1:])
          and w.c.counters["tick_deadline_runs"] == 0 and gaps and max(gaps) <= SPAN,
          f"{len(rows)} {polls} {w.c.counters['tick_deadline_runs']} {sorted(gaps)[-3:]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [6] the cool-down: every executor job ends SUBMIT_COOLDOWN_S after its target")
    # -----------------------------------------------------------------------------------------------------------------
    cfg = root / "cooldown"
    cfg.mkdir()
    hass = h.new_hass(cfg, NOW)
    H.write_site(cfg, H.site_profile(decisions=H.owner_decisions()))
    H.seed_fresh_states(hass.states, NOW, telemetry_at=NOW - s_(30), config_at=NOW - s_(30))
    h.recorder().statistics = H.synthetic_statistics(NOW, days=30)
    log: list = []

    def timed_submit(orig):
        def submit(target, *args):
            rec = {"via": getattr(target, "__name__", "?"), "name": None, "end": None, "done": None}
            if rec["via"] == "released_call" and len(args) > 1:
                inner = args[1]
                rec["name"] = getattr(inner, "__name__", "?")

                def timed(*a, _inner=inner, _rec=rec):
                    try:
                        return _inner(*a)
                    finally:
                        _rec["end"] = time.perf_counter()
                args = (args[0], timed) + tuple(args[2:])
            log.append(rec)
            fut = orig(target, *args)
            fut.add_done_callback(lambda _f, _rec=rec: _rec.__setitem__("done", time.perf_counter()))
            return fut
        return submit
    hass.async_add_executor_job = timed_submit(hass.async_add_executor_job)
    hass.async_add_import_executor_job = timed_submit(hass.async_add_import_executor_job)
    h.recorder().async_add_executor_job = timed_submit(h.recorder().async_add_executor_job)
    entry = h.new_entry()
    h.setup(entry)
    co = h.coordinator(entry)
    co.grace_s = 0.0
    h.set_now(NOW + s_(60))
    [t for t in hass.timers if t["active"]][0]["action"](h.now)
    h.settle(10.0)
    log[:] = [r for r in log if r["via"] != "import_module"]   # Home Assistant's own platform import, if any
    names = [r["name"] for r in log if r["via"] == "released_call"]
    want = {"_import_coordinator", "_startup_io", "statistics_during_period", "outcome_metrics", "compute",
            "record_cycle"}
    cool = {r["name"]: round(r["done"] - r["end"], 4) for r in log if r["end"] is not None and r["done"] is not None}
    check("every executor job the integration submits goes through released_call: the import, the start-up gates, the "
          "recorder read, the scorecard metrics, the engine and the store write",
          log and all(r["via"] == "released_call" for r in log) and set(names) == want, str([(r["via"], r["name"])
                                                                                             for r in log]))
    check(f"... and each completes at least SUBMIT_COOLDOWN_S ({CONST.SUBMIT_COOLDOWN_S:g} s) after its target returned "
          "(the cool-down)", set(cool) == want and all(v >= CONST.SUBMIT_COOLDOWN_S - 0.005 for v in cool.values()),
          str(cool))
    ran = []

    def boom():
        ran.append(time.perf_counter())
        raise ValueError("synthetic")
    t0 = time.perf_counter()
    try:
        PKG.released_call([True], boom)
        raised = False
    except ValueError:
        raised = True
    after_raise = time.perf_counter() - ran[-1]
    check("a target that raises cools down too, then its exception propagates",
          raised and after_raise >= CONST.SUBMIT_COOLDOWN_S - 0.005, f"{raised} {after_raise:.3f}")
    check("SUBMIT_COOLDOWN_S is 0.15 s, more than one 100 ms CPU-quota period (a fixed constant, not a PROPOSED value)",
          CONST.SUBMIT_COOLDOWN_S == 0.15 and CONST.SUBMIT_COOLDOWN_S > 0.1
          and "SUBMIT_COOLDOWN_S" not in co.diagnostics()["proposed_constants"], str(CONST.SUBMIT_COOLDOWN_S))
    cs = co.diagnostics()["cycle_stats"]
    last = co.last_timing
    check("cycle_stats names the timings that include the cool-down, and a real engine job's engine_s does (total_s "
          "holds every job's)", cs.get("job_cooldown_s") == CONST.SUBMIT_COOLDOWN_S
          and cs.get("timings_with_cooldown") == ["recorder_s", "engine_s", "store_s", "total_s"]
          and last.get("engine_s", 0) >= CONST.SUBMIT_COOLDOWN_S - 0.005
          and last.get("total_s", 0) >= last.get("engine_s", 0) + last.get("recorder_s", 0) + last.get("store_s", 0) - 0.01
          and last.get("recorder_s", 0) >= CONST.SUBMIT_COOLDOWN_S - 0.005, str(last))
    check("... no write attempt and no stand-in violation", not hass.write_attempts and not hass.violations,
          str(hass.violations)[:300])
    h.unload(entry)

    # -----------------------------------------------------------------------------------------------------------------
    print("== [7] unload and cancel during a cycle")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("unload_mid")
    t7 = NOW + s_(60)
    h.set_now(t7)
    hung_start(w, step_due=t7 + s_(30))
    h.set_now(t7 + s_(1))
    w.poll()                                            # held: no step armed
    h.settle(0.1)
    n_timers, n_later, catch0 = len(w.hass.timers), len(w.hass.later), w.c.counters["catchup_ticks"]
    writes0 = len(w.hass.state_writes)
    h.unload(w.entry)
    check("an unload during a cycle: no timer, no one-shot and no held step are left",
          not w.active_timers() and not w.active_later() and w.c._poll_due is None, str(w.c._poll_due))  # noqa: SLF001
    w.gate.set()
    h.settle(1.0)
    time.sleep(0.3)
    h.settle(1.0)
    check("... the cycle's end after it (cancelled) attaches nothing, arms nothing and runs no catch-up; nothing written",
          [r["outcome"] for r in w.rows()][-1:] == ["cancelled"] and not w.active_timers() and not w.active_later()
          and len(w.hass.timers) == n_timers and len(w.hass.later) == n_later
          and w.c.counters["catchup_ticks"] == catch0 and len(w.hass.state_writes) == writes0,
          f"{[r['outcome'] for r in w.rows()]} {len(w.hass.timers)} {n_timers} {w.c.counters['catchup_ticks']}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    w = World("cancel_mid")
    h.set_now(t7)
    hung_start(w, step_due=t7 + s_(30))
    catch0 = w.c.counters["catchup_ticks"]
    h.set_now(t7 + s_(2))
    w.in_loop(lambda: w.c._task.cancel())  # noqa: SLF001 - as Home Assistant cancels a background task at shutdown
    h.settle(1.0)
    check("a cancel during a cycle (Home Assistant's shutdown cancel): the cycle ends 'cancelled', the catch-up runs, the "
          "tick is attached again and the held step is armed at its due time",
          [r["outcome"] for r in w.rows()][-1:] == ["cancelled"] and w.c.counters["catchup_ticks"] == catch0 + 1
          and [t["next"] for t in w.active_timers()] == [t7 + s_(62)]
          and [t["due"] for t in w.active_later()] == [t7 + s_(30)] and not w.c._busy,  # noqa: SLF001
          f"{[r['outcome'] for r in w.rows()]} {[t['next'] for t in w.active_timers()]} "
          f"{[t['due'] for t in w.active_later()]}")
    w.gate.set()
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # Home Assistant's shutdown: Core is stopping when it cancels the background tasks, and the entry is not unloaded
    s7 = datetime(2030, 1, 15, 20, 58, 30, tzinfo=UTC)
    end7 = datetime(2030, 1, 15, 21, 0, 5, tzinfo=UTC)
    due7 = end7 + s_(25)                                # a pending step, held through the cycle
    w = World("shutdown_mid", start=s7, events=False)   # no poll seen: the tick's own rules (as [3])
    h.set_now(s7 + s_(60))                              # 20:59:30
    hung_start(w, step_due=due7)
    catch0, runs0, pubs0 = w.c.counters["catchup_ticks"], w.c.counters["runs_started"], len(w.pubs)
    h.set_now(end7)                                     # the 21:00 slot fell due meanwhile
    w.hass.state = h.fake.CoreState.stopping
    w.in_loop(lambda: w.c._task.cancel())  # noqa: SLF001 - as Home Assistant cancels a background task at shutdown
    h.settle(1.0)
    slot_due7 = w.c._slot_due(end7)  # noqa: SLF001
    check("Home Assistant's shutdown (Core stopping, the cycle task cancelled, the entry not unloaded): the cycle ends "
          "'cancelled', the catch-up runs and publishes, no cycle starts although the 21:00 slot is due (_maybe_start "
          "declines while Core is stopping), and the tick and the held step come back (the tick first due 60 s after "
          "the end, the step at its due time)",
          [r["outcome"] for r in w.rows()][-1:] == ["cancelled"] and w.c.counters["catchup_ticks"] == catch0 + 1
          and w.c.counters["runs_started"] == runs0 and slot_due7 and not w.c.closed
          and [p[0] for p in w.pubs[pubs0:]][-1:] == [end7] and [t["next"] for t in w.active_timers()] == [end7 + s_(60)]
          and [t["due"] for t in w.active_later()] == [due7] and not w.c._busy,  # noqa: SLF001
          f"{[r['outcome'] for r in w.rows()]} {w.c.counters['runs_started']} {slot_due7} {w.pubs[pubs0:]} "
          f"{[t['next'] for t in w.active_timers()]} {[t['due'] for t in w.active_later()]}")
    w.hass.state = h.fake.CoreState.running
    w.gate.set()
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    w = World("orphan")
    h.set_now(t7)
    w.fire_tick()                                       # the first cycle (a slot), not held
    h.settle(5.0)
    h.set_now(t7 + s_(60))
    STAND_IN_WAIT = COORD._job_wait  # noqa: SLF001
    COORD._job_wait = h.real_job_wait                   # this overrun runs through asyncio.wait_for and shield themselves
    w.c.time_budget_s = 2.0                             # the job enters well before it, under load too
    p_in = t7 + s_(60.1)

    def poll_in_job():
        h.set_now(p_in)
        w.poll()
    w.on_enter = poll_in_job                            # a poll while the engine job runs, before the budget ends it
    hung_step(w)                                        # a poll-driven refresh, its engine job held past the budget
    w.on_enter = None
    check("the engine job overruns the time budget, through the real job wait (asyncio.wait_for on the shielded job, the "
          "loop's clock): the cycle ends ('budget', SELF_TEST_FAILED CYCLE_TIME_BUDGET) while the abandoned thread runs "
          "(the job not cancelled, the guard stays set)",
          wait_for(lambda: bool(w.rows()) and w.rows()[-1]["outcome"] == "budget") and w.c._busy  # noqa: SLF001
          and len(w.c._orphans) == 1 and not any(f.done() for f in w.c._orphans)  # noqa: SLF001
          and w.c.counters["budget_exceeded"] == 1 and h.state("status").state == "SELF_TEST_FAILED"
          and COORD._job_wait is h.real_job_wait, f"{w.rows()[-1:]} {w.c._orphans} {h.state('status').state}")  # noqa: SLF001
    check("... the tick is attached again at that cycle's end, although the guard stays set (so the tick runs every "
          "minute while the thread hangs), but the step held for the poll during the job is not armed while it does",
          len(w.active_timers()) == 1 and not w.c._cycle_live and not w.active_later()  # noqa: SLF001
          and w.c._poll_due == p_in + SETTLE, f"{len(w.active_timers())} {w.c._poll_due}")  # noqa: SLF001
    h.set_now(t7 + s_(65))
    w.poll()
    h.settle(0.1)
    check("... a poll meanwhile arms nothing either (it keeps the earlier due time, A33)", not w.active_later()
          and w.c._poll_due == p_in + SETTLE, str(w.c._poll_due))  # noqa: SLF001
    h.set_now(t7 + s_(120))
    w.in_loop(w.fire_tick)
    check("... the tick fires while the thread hangs: its body runs (not in a cycle), no cycle starts",
          w.ticks[-1][0] == t7 + s_(120) and not w.ticks[-1][1] and w.ticks[-1][2] is True
          and w.c.counters["runs_started"] == 2, str(w.ticks[-1:]))
    h.set_now(t7 + s_(121))
    w.gate.set()
    check("... when the thread ends the guard is released and the held step is armed (max(due, now) = now)",
          wait_for(lambda: not w.c._busy) and [t["due"] for t in w.active_later()] == [t7 + s_(121)],  # noqa: SLF001
          str([t["due"] for t in w.active_later()]))
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()
    COORD._job_wait, STAND_IN_WAIT = STAND_IN_WAIT, None  # noqa: SLF001

    w = World("orphan_unload")
    h.set_now(t7)
    w.fire_tick()
    h.settle(5.0)
    h.set_now(t7 + s_(60))
    w.c.time_budget_s = 2.0                             # the job enters well before it, under load too
    hung_step(w)
    wait_for(lambda: bool(w.rows()) and w.rows()[-1]["outcome"] == "budget")
    h.set_now(t7 + s_(65))
    w.poll()
    h.settle(0.1)
    h.unload(w.entry)
    w.gate.set()
    wait_for(lambda: not w.c._orphans)  # noqa: SLF001
    h.settle(0.5)
    check("an unload while the abandoned thread runs: when it ends nothing is armed and no timer is attached",
          not w.active_timers() and not w.active_later() and w.c._poll_due is None, str(w.c._poll_due))  # noqa: SLF001
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [8] RR-N1: a snapshot hold cut short by the cycle's deadline covers nothing")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("hold_cut")
    h.set_now(NOW + s_(60))
    w.fire_tick()
    h.settle(5.0)
    h.set_now(NOW + s_(100))
    w.fire_tick()                                       # a tick body 20 s before the poll (no deadline in the hold)
    h.settle(5.0)
    h.set_now(NOW + s_(120))
    w.poll()
    h.set_now(NOW + s_(123))
    w.c.time_budget_s = 2.0
    holds = []

    async def hold2(seconds):
        holds.append((h.now, seconds))
        h.set_now(h.now + s_(seconds))
        await asyncio.sleep(0)
    COORD._settle_wait = hold2
    late = {}
    c0 = dict(w.c.counters)
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: (step["action"](h.now), h.loop.call_soon(late_poll)))
    h.settle(5.0)
    COORD._settle_wait = ORIG_SETTLE_WAIT
    w.c.time_budget_s = CONST.PROPOSED_TIME_BUDGET_S
    wait_for(lambda: not w.c._busy)  # noqa: SLF001
    check("the hold is cut short by the cycle's 2 s deadline (less than the 3 s asked): read inside the settle delay, so "
          "counted in snapshot_residual_reads, and the cycle does not cover that poll",
          len(holds) == 1 and 1.5 < holds[0][1] < 3.0 and w.c.counters["snapshot_holds"] == c0["snapshot_holds"] + 1
          and w.c.counters["snapshot_residual_reads"] == c0["snapshot_residual_reads"] + 1
          and w.c._read_poll_seq != w.c._poll_seq, f"{holds} {w.c._read_poll_seq} {w.c._poll_seq}")  # noqa: SLF001
    h.set_now(late["at"] + SETTLE)
    covered0, deferred0 = w.c.counters["poll_steps_covered"], w.c.counters["poll_steps_deferred_floor"]
    fired = w.fire_due_step()
    check("... so that poll's step, armed at the cycle's end, is not covered: it is deferred to the floor's end",
          fired and w.c.counters["poll_steps_covered"] == covered0
          and w.c.counters["poll_steps_deferred_floor"] == deferred0 + 1, f"{fired} {w.c._poll_due}")  # noqa: SLF001
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [9] the cycle's end after SELF_TEST_FAILED and after a discarded result")
    # -----------------------------------------------------------------------------------------------------------------
    def refuse() -> None:
        raise ValueError("synthetic refusal of one entity state")

    def refuse_writes(w: World, key: str) -> None:
        """One of the integration's own entities refuses its state write from now on, and is written at the next
        publish (as an entity whose last write raised is)."""
        ent = [e for p_ in w.hass.config_entries.platforms[w.entry.entry_id] for e in p_.entities
               if getattr(e, "_key", None) == key][0]
        ent.async_write_ha_state = refuse
        w.c._dirty.add(C.ENTITY_IDS[key])  # noqa: SLF001

    def write_failure(w: World) -> str:
        return (h.state("status").attributes.get("self_test") or {}).get("ENTITY_WRITE", "")

    w = World("end_self_test_failed")
    h.set_now(NOW + s_(60))
    w.fire_tick()                                       # the first cycle; its catch-up runs the tick body at NOW + 60
    h.settle(5.0)
    h.set_now(NOW + s_(120))
    w.poll()                                            # its step at NOW + 123
    t9 = NOW + s_(123)
    h.set_now(t9)
    refuse_writes(w, "accuracy")                        # the start run's publish writes it, and it raises
    c0 = dict(w.c.counters)
    n_ticks = len(w.ticks)
    step = [t for t in w.hass.later if t["active"] and t["due"] <= h.now][0]
    step["active"] = False
    w.in_loop(lambda: (step["action"](h.now), w.poll()))   # the cycle starts; a poll is noted before its first step
    h.settle(2.0)
    rows = w.rows()
    runs = w.ticks[n_ticks:]
    check("non-vacuity: a poll-driven cycle whose start run's publish raised for one entity (ENTITY_WRITE) ends "
          "'self_test_failed' at its first step, SELF_TEST_FAILED published; a poll was noted while it was in flight",
          rows[-1]["outcome"] == "self_test_failed" and rows[-1]["trigger"] == "POLL"
          and w.c.counters["tick_start_runs"] == c0["tick_start_runs"] + 1 and h.state("status").state == "SELF_TEST_FAILED"
          and "accuracy (ValueError)" in write_failure(w)
          and w.c.counters["poll_steps_held_busy"] == c0["poll_steps_held_busy"] + 1,
          f"{rows[-1:]} {h.state('status').state} {write_failure(w)}")
    check("... its end still runs the catch-up (in the cycle task, the guard released), attaches the tick again (first due "
          "TICK_S after the end) and arms the step held for that poll at its due time",
          w.c.counters["catchup_ticks"] == c0["catchup_ticks"] + 1 and len(runs) == 2 and runs[1][0] == t9 and runs[1][1]
          and runs[1][2] is False and [t["next"] for t in w.active_timers()] == [t9 + s_(TICK)]
          and [t["due"] for t in w.active_later()] == [t9 + SETTLE] and not w.c._busy,  # noqa: SLF001
          f"{runs} {[t['next'] for t in w.active_timers()]} {[t['due'] for t in w.active_later()]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    w = World("end_discarded_failed")
    t9b = NOW + s_(60)
    h.set_now(t9b)
    h.clear_world()                                     # the job waits schedule the deadline's moment as a world event
    due9 = t9b + s_(30)
    hung_start(w, step_due=due9)                        # the tick starts the first cycle, a step pending, the job held
    refuse_writes(w, "accuracy")                        # the deadline run's publish writes it, and it raises
    c0 = dict(w.c.counters)
    h.run_until(t9b + s_(TICK + 5), settle=1.0)         # the tick body's deadline run at t9b + 60, in the cycle
    mid = (h.state("status").state, write_failure(w), w.c._busy)  # noqa: SLF001
    release9 = t9b + s_(TICK + 10)
    h.set_now(release9)
    w.gate.set()
    wait_for(lambda: not w.c._busy)  # noqa: SLF001
    rows = w.rows()
    check("non-vacuity: the deadline run's publish raised for one entity while the engine computed (SELF_TEST_FAILED), so "
          "the cycle's result is discarded ('discarded_failed')",
          w.c.counters["tick_deadline_runs"] == c0["tick_deadline_runs"] + 1 and mid[0] == "SELF_TEST_FAILED"
          and "accuracy (ValueError)" in mid[1] and mid[2] is True and rows[-1]["outcome"] == "discarded_failed"
          and w.c.counters["results_discarded_failed"] == c0["results_discarded_failed"] + 1,
          f"{mid} {rows[-1:]} {w.c.counters['tick_deadline_runs']}")
    check("... its end still runs the catch-up, attaches the tick again (first due TICK_S after the end) and arms the held "
          "step (its due time passed during the cycle: at the end)",
          w.c.counters["catchup_ticks"] == c0["catchup_ticks"] + 1 and w.ticks[-1][0] == release9 and w.ticks[-1][1]
          and w.ticks[-1][2] is False and [t["next"] for t in w.active_timers()] == [release9 + s_(TICK)]
          and [t["due"] for t in w.active_later()] == [release9],
          f"{w.ticks[-2:]} {[t['next'] for t in w.active_timers()]} {[t['due'] for t in w.active_later()]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()
    h.clear_world()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [10] a step held through a cycle is armed unheld at its end")
    # -----------------------------------------------------------------------------------------------------------------
    s10 = datetime(2030, 1, 15, 20, 58, 0, tzinfo=UTC)
    t10 = datetime(2030, 1, 15, 20, 59, 20, tzinfo=UTC)
    p10 = datetime(2030, 1, 15, 21, 0, 8, tzinfo=UTC)  # a poll 1 s before the cycle's end, after the 21:00 slot fell due
    end10 = p10 + s_(1)
    w = World("rearm_unheld", start=s10)
    h.set_now(t10)
    w.block = 1
    w.entered.clear()

    def start10():
        w.c._arm_poll_step(t10, held=True)  # noqa: SLF001 - a settle hold's step, due as the tick comes
        w.fire_tick()                       # the tick starts the first cycle (no poll seen yet: no settle delay)
    w.in_loop(start10)
    wait_for(w.entered.is_set)
    h.settle(0.2)
    pre = (w.c._busy, w.c._poll_due, w.c._poll_held, w.c._poll_cancel)  # noqa: SLF001
    kept0 = w.c.counters["poll_steps_kept_earlier"]
    h.set_now(p10)
    w.poll()
    h.settle(0.1)
    c0 = dict(w.c.counters)
    h.set_now(end10)
    w.gate.set()
    wait_for(lambda: not w.c._busy and w.c.counters["runs_published"] == 1)  # noqa: SLF001
    d = w.c.diagnostics()["cadence"]
    check("non-vacuity: a settle hold's step (its one-shot mark set) was pending when the tick started the cycle, held "
          "with its mark; a poll 1 s before the cycle's end kept the step's earlier due time (A33); the catch-up at the "
          "end started nothing (the 21:00 slot is due, but polls are arriving: the tick holds it back)",
          pre == (True, t10, True, None) and w.c.counters["poll_steps_kept_earlier"] == kept0 + 1
          and w.c.counters["tick_slot_held"] == c0["tick_slot_held"] + 1 and w.c.counters["runs_started"] == 1,
          f"{pre} {w.c.counters['poll_steps_kept_earlier']} {w.c.counters['tick_slot_held']}")
    check("the held step is armed at the cycle's end, unheld: a settle hold's one-shot mark does not outlive the cycle (as "
          "a step that waited for a cycle in flight was resumed before the quiet cycle)",
          [t["due"] for t in w.active_later()] == [end10] and w.c._poll_held is False  # noqa: SLF001
          and d["poll_step_settle_hold"] is False, f"{[t['due'] for t in w.active_later()]} {w.c._poll_held}")  # noqa: SLF001
    fired = w.fire_due_step()
    check("... fired there, inside the settle delay of the poll seen 1 s before, it is held once more to that poll's settle "
          "end (a settle hold; no cycle starts inside the newer poll's settle delay, no residual start)",
          fired and w.c.counters["runs_started"] == 1 and w.c.counters["settle_holds"] == c0["settle_holds"] + 1
          and w.c.counters["settle_residual_starts"] == c0["settle_residual_starts"]
          and [t["due"] for t in w.active_later()] == [p10 + SETTLE] and w.c._poll_held is True,  # noqa: SLF001
          f"{fired} {w.c.counters['runs_started']} {w.c.counters['settle_residual_starts']} "
          f"{[t['due'] for t in w.active_later()]}")
    h.set_now(p10 + SETTLE)
    fired = w.fire_due_step()
    rows = w.rows()
    check("... and at that settle end the slot cycle starts, a held start outside every poll's settle delay",
          fired and [(r["kind"], r["trigger"], r["started_at"]) for r in rows][-1:] == [("SLOT", "POLL",
                                                                                       (p10 + SETTLE).isoformat())]
          and w.c.counters["settle_held_starts"] == c0["settle_held_starts"] + 1
          and w.c.counters["settle_residual_starts"] == c0["settle_residual_starts"],
          f"{[(r['kind'], r['trigger'], r['started_at']) for r in rows]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [11] recording a cycle's diagnostics raises: the catch-up, the tick and the held step still come back")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("finish_raises")
    t11 = NOW + s_(60)
    h.set_now(t11)
    due11 = t11 + s_(30)
    hung_start(w, step_due=due11)
    raised: list = []

    def finish_raises(*_a, **_k):
        raised.append(h.now)
        raise RuntimeError("synthetic diagnostics failure")
    w.c._finish = finish_raises  # noqa: SLF001
    catch0 = w.c.counters["catchup_ticks"]
    end11 = t11 + s_(5)
    h.set_now(end11)
    w.gate.set()
    wait_for(lambda: bool(raised) and w.c._task.done())  # noqa: SLF001
    h.settle(0.5)
    task = w.c._task  # noqa: SLF001
    task_exc = task.exception() if task.done() and not task.cancelled() else None   # retrieved: never logged unhandled
    check("non-vacuity: the cycle published, then recording its diagnostics raised at its end (the exception leaves the "
          "cycle task)", raised == [end11] and w.c.counters["runs_published"] == 1 and isinstance(task_exc, RuntimeError),
          f"{raised} {w.c.counters['runs_published']} {task_exc!r}")
    check("... the guard is released, the catch-up still ran, the tick is attached again (first due TICK_S after the end) "
          "and the held step armed at its due time",
          not w.c._busy and w.c.counters["catchup_ticks"] == catch0 + 1  # noqa: SLF001
          and [t["next"] for t in w.active_timers()] == [end11 + s_(TICK)]
          and [t["due"] for t in w.active_later()] == [due11],
          f"{w.c.counters['catchup_ticks']} {[t['next'] for t in w.active_timers()]} "
          f"{[t['due'] for t in w.active_later()]}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [12] the catch-up raises: the tick and the held step still come back")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("catchup_raises")
    t12 = NOW + s_(60)
    h.set_now(t12)
    due12 = t12 + s_(30)
    hung_start(w, step_due=due12)
    o_catch_up, o_sample = w.c._catch_up, w.c._sample_liveness  # noqa: SLF001
    inside: list = []
    raised12: list = []

    def catch_up(_o=o_catch_up):
        inside.append(h.now)
        try:
            return _o()
        finally:
            inside.pop()

    def sample_raises(now, _o=o_sample):
        if inside and not raised12:                     # once, and only in the catch-up's tick body
            raised12.append((h.now, in_cycle(), w.c._busy))  # noqa: SLF001
            raise RuntimeError("synthetic catch-up failure")
        return _o(now)
    w.c._catch_up, w.c._sample_liveness = catch_up, sample_raises  # noqa: SLF001
    c0 = dict(w.c.counters)
    n_ticks = len(w.ticks)
    end12 = t12 + s_(5)
    h.set_now(end12)
    w.gate.set()
    wait_for(lambda: bool(raised12) and w.c._task.done())  # noqa: SLF001
    h.settle(0.5)
    task = w.c._task  # noqa: SLF001
    task_exc = task.exception() if task.done() and not task.cancelled() else None   # retrieved: never logged unhandled
    rows = w.rows()
    runs = w.ticks[n_ticks:]
    check("non-vacuity: the cycle published and its diagnostics were recorded, then the catch-up's tick body raised at its "
          "end (in the cycle task, the guard released) and the exception leaves the cycle task",
          raised12 == [(end12, True, False)] and w.c.counters["runs_published"] == c0["runs_published"] + 1
          and rows[-1]["outcome"] == "published" and rows[-1]["started_at"] == t12.isoformat()
          and w.c.counters["catchup_ticks"] == c0["catchup_ticks"] + 1 and len(runs) == 1 and runs[0][0] == end12
          and runs[0][1] and isinstance(task_exc, RuntimeError) and "synthetic catch-up" in str(task_exc),
          f"{raised12} {w.c.counters['runs_published']} {rows[-1:]} {runs} {task_exc!r}")
    check("... the tick is attached again (first due TICK_S after the end), the held step is armed at its due time and "
          "no cycle started",
          not w.c._busy and not w.c._cycle_live  # noqa: SLF001
          and [t["next"] for t in w.active_timers()] == [end12 + s_(TICK)]
          and [t["due"] for t in w.active_later()] == [due12]
          and w.c.counters["runs_started"] == c0["runs_started"],
          f"{[t['next'] for t in w.active_timers()]} {[t['due'] for t in w.active_later()]} "
          f"{w.c.counters['runs_started']}")
    check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
    w.close()
finally:
    ENGINE_LINK.compute = ORIG_COMPUTE
    COORD._settle_wait = ORIG_SETTLE_WAIT
    if STAND_IN_WAIT is not None:
        COORD._job_wait = STAND_IN_WAIT  # noqa: SLF001
    h.loop.close()
    H.rmtree_own(root, PREFIX)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the quiet-cycle suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all quiet-cycle checks passed")
