#!/usr/bin/env python3
"""L2: the event-loop steps of the BUILT kit under the stand-in Home Assistant (_fake_ha), which starts tasks eagerly unless
told otherwise, as the pinned Core does. Callbacks are fired INSIDE the running loop here (as Home Assistant runs a
timer's callback), so an eager start would run cycle work inside them. The steps and their order are pinned, not their
duration (the duration is an L3 matter).

  [1] the import check (labelled IMPORT, not the runbook's acceptance row T2): the coordinator module is imported inside
      an executor job: a fresh interpreter sets the integration up and records the thread of every module of the package
      first imported during the setup. The coordinator module and the vendored engine come in Home Assistant's import
      executor, through the integration's own import executor job, and no module of the package is first imported on the
      event loop thread; the import starts only after the setup step that submitted it has ended (that step is made to run
      on for 50 ms after the submit)
  [2] non-eager start: the poll-driven step and the tick, fired in the loop, return before any cycle work runs (the
      cycle task exists, named, created with eager_start=False, not yet entered; nothing read, nothing submitted); the
      second-run guard holds back a second start in the same callback and in the next one; then the cycle runs and
      publishes; homeassistant_started only starts the grace
  [3] the steps keep their order and the results: the pause and self-test checks, the snapshot, the history inputs, the
      engine submit and the publish each run in their own loop step, in that order, all in the cycle task (a SLOT cycle:
      the recorder read and the metrics read between the history start and the engine submit; the store write submitted
      in the publish step), and the tick body runs in the first step of a cycle the tick body did not start
      and once at the end as the catch-up, in the cycle task's last step; two
      identical worlds, one with the yields and one with them made not to suspend, publish the same entity states and
      attributes, the same recorder rows, the same envelopes and the same engine jobs
  [4] between the steps (the settle hold at the snapshot, A36; the stand-in's clock is moved through each hold): a dongle
      poll written (with a later clock) after the cycle started and before its snapshot holds the snapshot once to its
      settle delay's end (3 s, in the cycle task, counted), which then reads it with that moment as the cycle time and
      the poll's own liveness, no item blocked for a future observation; a partial poll (the text alone, its SOC 1 s
      later) is read whole, not with the previous poll's SOC; the held cycle covers that poll (its own step, fired at
      its due time after the hold, or due during it and so armed at the cycle's end, starts no second cycle and is not
      deferred); the residual (a second
      poll text during the hold) is counted, not waited for, and that poll's step refreshes at the floor's end; the hold
      is cut to the cycle's deadline; a SLOT cycle reads its history inputs at the cycle time (the cache's read_at, the
      scorecard metrics, the recorder window), not at its start; the real hold sleeps on the loop's clock and yields;
      the tick body (inside a cycle now only its deadline run, the tick being detached) sampling a newer poll text
      between the snapshot and the engine job leaves the job the snapshot's own liveness time (the states and the
      liveness of one job come from one moment)
  [5] an unload and a cancel (Home Assistant's shutdown cancel) at each yield point: before the first step, after the
      checks, during the settle hold at the snapshot, after the snapshot, after the history inputs, while the engine
      runs, and for a SLOT cycle while the recorder read and while the store write run. Each ends the cycle with the
      outcome 'cancelled' and releases the second-run guard; after an unload nothing is written or published and no
      engine job runs that had not started; a cancelled hold covers no poll; after a cancel the next tick starts a new
      cycle that publishes
  [6] the job names: the tick's interval timer carries TICK_JOB_NAME, the poll-driven step's one-shot is a HassJob named
      POLL_STEP_JOB_NAME on _on_poll_step, every cycle task is CYCLE_TASK_NAME; asyncio's reprlib text of the one-shot
      keeps '<Job ecco_int' in front and ends with the integration's name; with the tick's timer laid out as the pinned
      Core's _TrackTimeInterval (a mirror of its source), its slow-callback text is
      '_TrackTimeInterval._interval_listener(<Job ecco_int...nt.py:1610>)>>)'
  [7] the release of executor jobs: the engine job and the recorder read start only after the step that submitted them
      has ended (that step made to run on for 50 ms); release_after_step's flag is set by the loop's next handle;
      released_call waits for it, and starts after SUBMIT_RELEASE_CAP_S when it never comes; it runs its target at once
      when released and returns SUBMIT_COOLDOWN_S after the target has (the cool-down; the quiet-cycle suite pins it on
      every job)
Every scenario also ends with zero write attempts and no stand-in violation. Plain script; exits 1 on any failure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json
import os
import reprlib
import subprocess
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
PREFIX = "ecco_intel_loop_steps_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)

# --- [1] the import check, in a fresh interpreter (nothing of the integration imported before its setup) ----------------
IMPORT_CHILD = r'''
import asyncio, importlib, importlib.abc, json, sys, threading, time
kit, tests, cfg = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, tests)
sys.path.insert(0, kit)
import _fake_ha as F
F.install()
PKG = "custom_components.ecco_intelligence"
pkg = importlib.import_module(PKG)
LOOP = {"label": None}
_run = asyncio.events.Handle._run
def run(self):
    s = getattr(self._callback, "__self__", None)
    prev = LOOP["label"]
    LOOP["label"] = ("task:" + s.get_name()) if isinstance(s, asyncio.Task) else getattr(self._callback, "__qualname__", "?")
    try:
        return _run(self)
    finally:
        LOOP["label"] = prev
asyncio.events.Handle._run = run
first = {}
class Rec(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.startswith(PKG + "."):
            first.setdefault(name, [threading.current_thread().name, LOOP["label"]])
        return None
sys.meta_path.insert(0, Rec())
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from datetime import datetime, timezone
F.CLOCK.now = datetime(2030, 1, 15, 20, 5, tzinfo=timezone.utc)
hass = F.HomeAssistant(loop, cfg)
orig = hass.async_add_import_executor_job
def long_tail(target, *args):
    fut = orig(target, *args)
    end = time.perf_counter() + 0.05          # the submitting step runs on for 50 ms after the submit
    while time.perf_counter() < end:
        pass
    return fut
hass.async_add_import_executor_job = long_tail
entry = F.ConfigEntry(PKG.rpartition(".")[2], {}, "import check")
hass.config_entries._add(entry)
async def main():
    ok = await loop.create_task(pkg.async_setup_entry(hass, entry), name="setup")
    for _ in range(5):
        await asyncio.sleep(0)
    await pkg.async_unload_entry(hass, entry)
    return ok
ok = loop.run_until_complete(main())
print(json.dumps({"ok": ok, "first": first, "loop_thread": threading.current_thread().name,
                  "import_jobs": [getattr(j, "__qualname__", repr(j)) for j in hass.import_jobs],
                  "violations": hass.violations, "write_attempts": hass.write_attempts}))
'''

print("== [1] IMPORT: the coordinator module is imported inside an executor job")
imp_cfg = root / "import_check"
imp_cfg.mkdir()
H.write_site(imp_cfg, H.site_profile())
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
p = subprocess.run([sys.executable, "-I", "-B", "-c", IMPORT_CHILD, str(kit), str(TESTS), str(imp_cfg)], capture_output=True,
                   text=True, timeout=300, env=env, cwd=str(root))
try:
    imp = json.loads(p.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    imp = {"crash": (p.stdout + p.stderr)[-800:]}
first = imp.get("first", {})
COORD_NAME = "custom_components.ecco_intelligence.coordinator"
on_loop = sorted(n for n, (th, _lab) in first.items() if th == imp.get("loop_thread"))
vendor_in_import = [n for n, (th, _lab) in first.items() if "._vendor." in n and th.startswith("fake_ha_import_executor")]
check("IMPORT: the setup ran (no crash, setup returned True)", imp.get("ok") is True, imp.get("crash", "")[-400:])
check("IMPORT: the coordinator module is imported inside an executor job (Home Assistant's import executor), not on the "
      "event loop thread", first.get(COORD_NAME, [""])[0].startswith("fake_ha_import_executor"), str(first.get(COORD_NAME)))
check("IMPORT: the integration's first import executor job is its own (released_call, holding _import_coordinator)",
      imp.get("import_jobs", [None])[0] == "released_call", str(imp.get("import_jobs")))
check("IMPORT: with it the vendored engine comes in the import executor (at least 20 _vendor modules)", len(vendor_in_import) >= 20,
      str(len(vendor_in_import)))
check("IMPORT: no module of the package is first imported on the event loop thread during the setup", first and not on_loop,
      str(on_loop[:6]))
check("IMPORT: the import starts only after the setup step that submitted it has ended (that step ran on for 50 ms)",
      first.get(COORD_NAME, ["", ""])[1] != "task:setup", str(first.get(COORD_NAME)))
check("IMPORT: no write attempt and no stand-in violation", not imp.get("violations") and not imp.get("write_attempts"),
      str(imp.get("violations"))[:300])

# --- the L2 harness (the rest of the suite) -------------------------------------------------------------------------------
h = H.Harness(kit)
C = h.contract
COORD = importlib.import_module(COORD_NAME)
CONST = importlib.import_module("custom_components.ecco_intelligence.const")
PKG = h.integration
ENGINE_LINK = importlib.import_module("custom_components.ecco_intelligence.runtime.engine_link")
HISTORY_SOURCE = importlib.import_module("custom_components.ecco_intelligence.runtime.history_source")
ORIG_COMPUTE = ENGINE_LINK.compute
ORIG_NEXT_STEP = COORD._next_step
ORIG_SETTLE_WAIT = COORD._settle_wait
ORIG_STATS = COORD.statistics_during_period
CORE = h.mods["homeassistant.core"]
CYCLE = CONST.CYCLE_TASK_NAME
TASK_LABEL = "task:" + CYCLE
TEL = H.eid("sensor", "last_telemetry_update")
SOC = H.eid("sensor", "battery_soc")

# which loop handle is running (the loop thread), and a running count of handles
LOOP = {"seq": 0, "label": None}
_orig_handle_run = asyncio.events.Handle._run


def _handle_run(self):
    s = getattr(self._callback, "__self__", None)
    prev = LOOP["label"]
    LOOP["seq"] += 1
    LOOP["label"] = ("task:" + s.get_name()) if isinstance(s, asyncio.Task) else getattr(self._callback, "__qualname__", "?")
    try:
        return _orig_handle_run(self)
    finally:
        LOOP["label"] = prev


asyncio.events.Handle._run = _handle_run


def in_cycle() -> bool:
    try:
        t = asyncio.current_task()
    except RuntimeError:
        return False
    return t is not None and t.get_name() == CYCLE


class FakeSettleWait:
    """Stands in for coordinator._settle_wait (the settle hold at the snapshot; the stand-in's clock stands still while the
    real loop runs): records each hold (the clock at its start, the seconds asked for, the loop handle), runs the world
    events scripted for it (`during`: (offset in seconds, fn), each in its own loop handle with the clock at its offset,
    up to the hold's end inclusive) and ends the hold with the clock at its end. One-shot: `during` is cleared."""

    def __init__(self) -> None:
        self.calls: list = []
        self.during: list = []

    async def __call__(self, seconds: float) -> None:
        t0 = h.now
        self.calls.append((t0, seconds, LOOP["label"]))
        events, self.during = sorted(self.during, key=lambda x: x[0]), []
        for off, fn in events:
            if off <= seconds:
                h.set_now(t0 + timedelta(seconds=off))
                h.loop.call_soon(fn)
                for _ in range(5):                 # fn and whatever it schedules run before the hold ends
                    await asyncio.sleep(0)
        h.set_now(t0 + timedelta(seconds=seconds))
        await asyncio.sleep(0)


class World:
    """One stand-in Home Assistant with the integration set up at NOW (owner-record decisions, fresh states, the start-up
    grace 0), state_changed events on."""

    def __init__(self, name: str, *, stats_days: int = 30) -> None:
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, NOW)
        H.write_site(self.cfg, H.site_profile(decisions=H.owner_decisions()))
        H.seed_fresh_states(self.hass.states, NOW, telemetry_at=NOW - timedelta(seconds=30),
                            config_at=NOW - timedelta(seconds=30))
        h.recorder().statistics = H.synthetic_statistics(NOW, days=stats_days)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 0.0
        self.jobs: list = []
        self.compute_label: list = []
        ENGINE_LINK.compute = self._compute

    def _compute(self, job, run_cycle=None):
        self.jobs.append(job)
        self.compute_label.append(LOOP["label"])
        return ORIG_COMPUTE(job, run_cycle)

    def timer(self) -> dict:
        return [t for t in self.hass.timers if t["active"]][0]

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

    def tick(self, probe=None):
        t = self.timer()
        return self.in_loop(lambda: t["action"](h.now), probe)

    def poll(self, at: datetime | None = None) -> None:
        """A dongle poll: the telemetry poll text and the other entities, now (state_changed reaches the listener)."""
        at = at or h.now
        H.seed_fresh_states(self.hass.states, at, telemetry_at=at, config_at=at)

    def fire_poll_step(self, probe=None):
        due = [t for t in self.hass.later if t["active"] and t["due"] <= h.now]
        t = min(due, key=lambda x: x["due"])
        t["active"] = False
        return self.in_loop(lambda: t["action"](h.now), probe)

    def clean(self) -> bool:
        return not self.hass.write_attempts and not self.hass.violations

    def close(self) -> None:
        ENGINE_LINK.compute = ORIG_COMPUTE
        if not self.c.closed:
            h.unload(self.entry)


def first_cycle_world(name: str, **kw) -> World:
    """A world whose first poll-driven step is due now (a SLOT cycle: the first run)."""
    w = World(name, **kw)
    h.set_now(NOW + timedelta(seconds=10))
    w.poll()
    h.set_now(h.now + timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S))
    return w


# --- [2] non-eager start ----------------------------------------------------------------------------------------------------
print("== [2] non-eager start: the callbacks only schedule the cycle")
w = first_cycle_world("start_poll")
calls = {"collect": 0}
orig_collect = w.c._collect_states


def counting_collect():
    calls["collect"] += 1
    return orig_collect()


w.c._collect_states = counting_collect
n_exec = len(w.jobs)
n_tasks = len(w.hass.task_log)


def probe_after_start():
    co = w.c
    task = co._task  # noqa: SLF001
    second = co._maybe_start(h.now, COORD.POLL)  # noqa: SLF001 - a second start inside the same callback
    return {"task": task, "done": task is not None and task.done(), "pending": co._pending_start is not None,  # noqa: SLF001
            "busy": co._busy, "collect": calls["collect"], "jobs": len(w.jobs), "second": second,  # noqa: SLF001
            "log": list(w.hass.task_log[n_tasks:]), "skipped": co.counters["skipped_in_flight"]}


ret, pr = w.fire_poll_step(probe_after_start)
check("the poll-driven step returns before any cycle work runs: the cycle task exists, not done and not yet entered",
      pr["task"] is not None and not pr["done"] and pr["pending"], str(pr))
check("... nothing of the cycle ran inside the callback (no snapshot, no engine job)", pr["collect"] == 0 and pr["jobs"] == 0,
      str(pr))
check("... the cycle task is named CYCLE_TASK_NAME and was created with eager_start=False (the stand-in, as the Core, "
      "starts a task eagerly otherwise)", pr["log"][:1] == [(CYCLE, False)] and pr["task"].get_name() == CYCLE, str(pr["log"]))
check("... the second-run guard is set before the task runs and holds back a second start in the same callback",
      pr["busy"] is True and pr["second"] is False and len(pr["log"]) == 1, str(pr))
_r2, pr2 = w.in_loop(lambda: w.c._maybe_start(h.now, COORD.POLL))  # noqa: SLF001
check("... and in the next callback, before the cycle has finished", _r2 is False and w.c._busy is True  # noqa: SLF001
      and sum(1 for n, _e in w.hass.task_log if n == CYCLE) == 1, str(w.hass.task_log))
h.settle()
check("... then the cycle runs once and publishes a computed status",
      w.c.counters["runs_published"] == 1 and calls["collect"] == 1 and len(w.jobs) == 1
      and h.state("status").state in C.SystemStatus.ALL and h.state("status").state not in C.SystemStatus.NULL,
      f"{w.c.counters['runs_published']} {calls} {h.state('status').state}")
check("... the guard is released and the cycle is not pending", w.c._busy is False and w.c._pending_start is None,  # noqa: SLF001
      str(w.c._busy))  # noqa: SLF001
check("... and it was ended once (one diagnostics row, 'published')", [r[2] for r in w.c.cycle_stats] == ["published"],
      str(list(w.c.cycle_stats)))
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

w = World("start_tick")
h.set_now(NOW + timedelta(seconds=60))
n_tasks = len(w.hass.task_log)
_r, pr = w.tick(lambda: {"pending": w.c._pending_start is not None, "jobs": len(w.jobs),  # noqa: SLF001
                         "log": list(w.hass.task_log[n_tasks:]), "task": w.c._task})  # noqa: SLF001
check("the tick returns before any cycle work runs (no polls seen: the tick starts the first cycle; it is not entered)",
      pr["pending"] and pr["jobs"] == 0 and pr["log"] == [(CYCLE, False)] and not pr["task"].done(), str(pr))
h.settle()
check("... then that cycle publishes", w.c.counters["runs_published"] == 1 and len(w.jobs) == 1, str(w.c.counters))
w.close()

w = World("start_started")
co = w.c
co._started_at = None  # noqa: SLF001 - as before homeassistant_started
n_tasks = len(w.hass.task_log)
_r, pr = w.in_loop(lambda: co._on_started(None), lambda: {"log": list(w.hass.task_log[n_tasks:]),  # noqa: SLF001
                                                          "started": co._started_at is not None})  # noqa: SLF001
check("homeassistant_started only starts the grace (no task, no cycle work)", pr["started"] and pr["log"] == []
      and len(w.jobs) == 0, str(pr))
w.close()

# --- [3] the steps keep their order and the results ------------------------------------------------------------------------
print("== [3] the steps keep their order and the results")


def instrument(w: World) -> list:
    """Record each cycle phase with the loop handle it ran in: (phase, handle number, handle label)."""
    marks: list = []
    co = w.c
    o_pause, o_collect, o_hist, o_pub = co._pause_state, co._collect_states, co._history_inputs, co._publish  # noqa: SLF001
    o_tick = co._tick_body  # noqa: SLF001
    inside = {"tick": False}

    def tick_body(now):
        """The tick body as one phase (the catch-up, or a deadline run, in the cycle task); its own reads and publish
        are not cycle phases."""
        if in_cycle():
            marks.append(("tick_body", LOOP["seq"], LOOP["label"]))
        inside["tick"] = True
        try:
            return o_tick(now)
        finally:
            inside["tick"] = False

    def pause():
        if in_cycle() and not inside["tick"]:
            marks.append(("checks", LOOP["seq"], LOOP["label"]))
        return o_pause()

    def collect():
        marks.append(("snapshot", LOOP["seq"], LOOP["label"]))
        return o_collect()

    async def hist(*a, **k):
        marks.append(("history", LOOP["seq"], LOOP["label"]))
        return await o_hist(*a, **k)

    def pub(env, now):
        if in_cycle() and not inside["tick"]:
            marks.append(("publish", LOOP["seq"], LOOP["label"]))
        return o_pub(env, now)

    o_exec = w.hass.async_add_executor_job
    o_rec = h.recorder().async_add_executor_job

    def name_of(target, args):
        real = args[1] if getattr(target, "__name__", "") == "released_call" and len(args) > 1 else target
        n = getattr(real, "__name__", repr(real))
        return "compute" if n in ("compute", "_compute") else n

    def ex(target, *args):
        marks.append(("submit:" + name_of(target, args), LOOP["seq"], LOOP["label"]))
        return o_exec(target, *args)

    def rec(target, *args):
        marks.append(("submit:" + name_of(target, args), LOOP["seq"], LOOP["label"]))
        return o_rec(target, *args)
    co._pause_state, co._collect_states, co._history_inputs, co._publish = pause, collect, hist, pub  # noqa: SLF001
    co._tick_body = tick_body  # noqa: SLF001
    w.hass.async_add_executor_job = ex
    h.recorder().async_add_executor_job = rec
    return marks


w = first_cycle_world("order")
marks = instrument(w)
w.fire_poll_step()
h.settle()
slot_marks = list(marks)
names = [m[0] for m in slot_marks]


def seq_of(marks: list) -> dict:
    """{phase: handle number}; the second 'checks' (after the engine) is 'checks2'; the first tick body (the cycle's
    first step) 'tick_start', the last (the catch-up) 'tick_body'."""
    out: dict = {}
    for m in marks:
        if m[0] == "tick_body" and "checks1" not in out:
            out["tick_start"] = m[1]
            continue
        out["checks2" if m[0] == "checks" and "checks1" in out else ("checks1" if m[0] == "checks" else m[0])] = m[1]
    return out


seq = seq_of(slot_marks)
want_slot = ["tick_body", "checks", "snapshot", "history", "submit:statistics_during_period", "submit:outcome_metrics",
             "submit:compute", "checks", "publish", "submit:record_cycle", "tick_body"]
check("a SLOT cycle 13 s after the tick body's last run (the start's publish): the tick body (the tick body did not "
      "start this cycle), checks, snapshot, history inputs (the recorder read, the metrics read), the engine submit, the "
      "checks again, the publish, the store write, then the catch-up tick body, in that order", names == want_slot,
      str(names))
check("... all in the cycle task", all(m[2] == TASK_LABEL for m in slot_marks), str({m[2] for m in slot_marks}))
check("... the checks, the snapshot, the history inputs and the engine submit each in their own loop step",
      seq.get("checks1", 0) < seq.get("snapshot", 0) < seq.get("history", 0) < seq.get("submit:compute", 0)
      < seq.get("publish", 0), str(seq))
check("... the engine submit is a later step than the metrics read; the publish and the store write share one step",
      seq.get("submit:outcome_metrics", 0) < seq.get("submit:compute", 0)
      and seq.get("publish") == seq.get("submit:record_cycle") == seq.get("checks2"), str(seq))
check("... the first tick body runs in the checks' step, before any job; the catch-up in a later step than the store "
      "write (after its result)", seq.get("tick_start") == seq.get("checks1")
      and seq.get("tick_body", 0) > seq.get("submit:record_cycle", 0), str(seq))
marks.clear()
h.set_now(h.now + timedelta(seconds=60))
w.poll()
h.set_now(h.now + timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S))
w.fire_poll_step()
h.settle()
names = [m[0] for m in marks]
seq = seq_of(marks)
check("a REFRESH cycle (the slot's cached history), 63 s after the catch-up: the tick body, checks, snapshot, history "
      "inputs, engine submit, checks, publish, the catch-up tick body; no recorder read and no store write",
      names == ["tick_body", "checks", "snapshot", "history", "submit:compute", "checks", "publish", "tick_body"],
      str(names))
check("... each of the first four in its own loop step; the catch-up in the publish step, the cycle task's last",
      seq.get("checks1", 0) < seq.get("snapshot", 0) < seq.get("history", 0) < seq.get("submit:compute", 0)
      < seq.get("publish", 0) == seq.get("tick_body", -1), str(seq))
check("... a computed result was published by both cycles (non-vacuity)", w.c.counters["runs_published"] == 2
      and H.numeric_state(h.state("charge_target")), str(w.c.counters["runs_published"]))
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()


async def _no_yield() -> None:
    return None


def run_world(name: str, yields: bool) -> dict:
    """Three polls a minute apart after the first cycle; every computed envelope, state write, recorder row and job."""
    COORD._next_step = ORIG_NEXT_STEP if yields else _no_yield
    try:
        w = first_cycle_world(name)
        marks = instrument(w)
        envs: list = []
        o_pub = w.c._publish  # noqa: SLF001

        def pub(env, now):
            envs.append(env)
            return o_pub(env, now)
        w.c._publish = pub  # noqa: SLF001
        w.fire_poll_step()
        h.settle()
        for _k in range(3):
            h.set_now(h.now + timedelta(seconds=60 - CONST.PROPOSED_POLL_SETTLE_S))
            w.poll()
            h.set_now(h.now + timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S))
            w.fire_poll_step()
            h.settle()
        out = {"rows": list(w.hass.recorder_rows), "writes": [(e, s) for e, s in w.hass.state_writes],
               "envs": [C.to_entity_payloads(e, e.generated_at) for e in envs],
               "jobs": [(j.now, j.liveness_at, j.config_liveness_at, json.dumps(j.states, default=str, sort_keys=True),
                         j.previous, j.paused, j.outcome_metrics) for j in w.jobs],
               "stats": [(r[1], r[2], r[8]) for r in w.c.cycle_stats], "marks": marks,
               "published": w.c.counters["runs_published"], "clean": w.clean(),
               "numbers": H.numeric_state(h.state("charge_target"))}
        w.close()
        return out
    finally:
        COORD._next_step = ORIG_NEXT_STEP


A = run_world("same_yield", True)
B = run_world("same_no_yield", False)


def steps_of(marks: list) -> set:
    """The loop steps of a REFRESH's first four phases (its first 'checks', the snapshot, the history, the submit)."""
    first: dict = {}
    for m in marks:
        if m[0] in ("checks", "snapshot", "history", "submit:compute") and m[0] not in first:
            first[m[0]] = m[1]
    return set(first.values()) if len(first) == 4 else set()


check("non-vacuity: with the yields the first four phases of a REFRESH are four loop steps, with them made not to "
      "suspend one", len(steps_of(A["marks"][-8:])) == 4 and len(steps_of(B["marks"][-8:])) == 1
      and A["marks"][-1][0] == B["marks"][-1][0] == A["marks"][-8][0] == "tick_body",
      f"{steps_of(A['marks'][-8:])} {steps_of(B['marks'][-8:])}")
check("the same results with and without the yields: four cycles published, charge_target with a number",
      A["published"] == B["published"] == 4 and A["numbers"] and B["numbers"], f"{A['published']} {B['published']}")
check("... the same entity state writes and the same recorder rows (states and recorded attributes)",
      A["writes"] == B["writes"] and A["rows"] == B["rows"] and len(A["rows"]) > 11, f"{len(A['rows'])} {len(B['rows'])}")
check("... the same envelopes (every entity payload of every publish)", A["envs"] == B["envs"] and len(A["envs"]) >= 4)
check("... the same engine jobs (cycle time, liveness times, states, previous summary, pause, metrics)",
      A["jobs"] == B["jobs"] and len(A["jobs"]) == 4)
check("... the same cycle kinds, outcomes and triggers", A["stats"] == B["stats"], f"{A['stats']} {B['stats']}")
check("... no write attempt and no stand-in violation in either", A["clean"] and B["clean"])

# --- [4] between the steps --------------------------------------------------------------------------------------------------
print("== [4] between the steps")
SETTLE = timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S)
CANON_SOC = "sensor.test_canonical_battery_soc"


def refresh_world(name: str) -> World:
    """A world after its first cycle and the next poll: that poll's step (a REFRESH, past the floor) is due now."""
    w = World(name)
    h.set_now(NOW + timedelta(seconds=60))
    w.tick()                                   # samples the poll text (its memory) and runs the first cycle
    h.settle()
    h.set_now(h.now + timedelta(seconds=60))   # the next poll, past the refresh floor
    w.poll()
    h.set_now(h.now + SETTLE)
    return w


def write_soc(w: World, value: str) -> None:
    w.hass.states.seed(SOC, value, {"unit_of_measurement": "%"}, changed_at=h.now)
    w.hass.states.seed(CANON_SOC, value, {"unit_of_measurement": "%"}, changed_at=h.now)


def write_text(w: World) -> None:
    w.hass.states.seed(TEL, H.poll_time_text(h.now), changed_at=h.now)


def late_poll(w: World, late: dict, soc: str | None):
    """A dongle poll after the cycle started and before its snapshot step, half a second later on the clock: its poll text
    and, unless `soc` is None, its SOC readings in the same handle."""
    def go() -> None:
        h.set_now(h.now + timedelta(seconds=0.5))
        late["at"] = h.now
        write_text(w)
        if soc is not None:
            write_soc(w, soc)
    return go


def blockers(env) -> set:
    codes: set = set()
    if env is not None:
        for v in tuple(env.items) + tuple(env.forecasts):
            codes |= set(v.reason_codes) | {c_ for c_, _t in v.blockers}
    return codes


def held_cycle(w: World, soc_with_text: str | None, during=(), lag: float = 0.0) -> tuple:
    """Fire the due poll-driven step with a late poll scheduled behind it (so between the cycle's start and its snapshot;
    `lag`: the clock then moves on that many seconds in a later handle, still before the snapshot step), under a
    FakeSettleWait running `during`; return (the new engine job, late, the hold, the counters before, the start)."""
    hold = FakeSettleWait()
    hold.during = list(during)
    COORD._settle_wait = hold
    late: dict = {}
    n_jobs, c0, start = len(w.jobs), dict(w.c.counters), h.now

    def behind() -> None:
        h.loop.call_soon(late_poll(w, late, soc_with_text))
        if lag:
            h.loop.call_soon(lambda: h.set_now(h.now + timedelta(seconds=lag)))
    try:
        w.fire_poll_step(behind)
        h.settle()
    finally:
        COORD._settle_wait = ORIG_SETTLE_WAIT
    job = w.jobs[n_jobs] if len(w.jobs) > n_jobs else None
    return job, late, hold, c0, start


def delta(w: World, c0: dict, key: str) -> int:
    return w.c.counters[key] - c0[key]


def fire_due_step(w: World) -> bool:
    """Fire the pending poll-driven step when it is due now (then let its cycle finish); True when one was."""
    if not any(t["active"] and t["due"] <= h.now for t in w.hass.later):
        return False
    w.fire_poll_step()
    h.settle()
    return True


def fire_due_step_inline(w: World) -> bool:
    """Fire the due poll-driven step inside the current handle (as the loop runs a timer between two task steps)."""
    due = [t for t in w.hass.later if t["active"] and t["due"] <= h.now]
    if not due:
        return False
    t = min(due, key=lambda x: x["due"])
    t["active"] = False
    t["action"](h.now)
    return True


def published_ok(w: World) -> bool:
    return (h.state("status").state in C.SystemStatus.ALL and h.state("status").state not in C.SystemStatus.NULL
            and H.numeric_state(h.state("charge_target")))


# a poll written whole (the text and the readings in one handle) between the start and the snapshot, the snapshot step
# a second after it on the clock
w = refresh_world("between_snapshot")
job, late, hold, c0, start = held_cycle(w, "61", lag=1.0)
check("a poll written after the cycle started and before its snapshot is in the snapshot", job is not None
      and job.states.get(SOC, {}).get("state") == "61" and job.states.get(TEL, {}).get("last_changed") == late.get("at"),
      str(None if job is None else job.states.get(SOC)))
check("... the snapshot is held once to that poll's settle delay's end (2 s asked for, a second after the poll, in the "
      "cycle task), counted in snapshot_holds",
      hold.calls == [(late.get("at") + timedelta(seconds=1.0), CONST.PROPOSED_POLL_SETTLE_S - 1.0, TASK_LABEL)]
      and delta(w, c0, "snapshot_holds") == 1 and delta(w, c0, "snapshot_residual_reads") == 0,
      f"{hold.calls} {w.c.counters['snapshot_holds']}")
check("... the cycle time is that delay's end (read with the snapshot, after the hold)", job is not None
      and job.now == late["at"] + SETTLE, f"{None if job is None else job.now} {late.get('at')}")
check("... its liveness time is that poll's (the change was usable, not in the future)", job is not None
      and job.liveness_at == late["at"], str(None if job is None else job.liveness_at))
codes = blockers(w.c._last_computed)  # noqa: SLF001
check("... no item is blocked for a future observation or a missing liveness, and charge_target has its number",
      not any("FUTURE" in c_ or c_ == "LIVENESS_MISSING" for c_ in codes) and published_ok(w),
      str(sorted(c_ for c_ in codes if "FUTURE" in c_ or "LIVENESS" in c_)))
runs = w.c.counters["runs_started"]
fired = fire_due_step(w)
check("... that poll's own step, at its due time, is covered by the held cycle: no deferral to the floor's end, no "
      "second cycle, no step left", fired and delta(w, c0, "poll_steps_covered") == 1
      and delta(w, c0, "poll_steps_deferred_floor") == 0 and w.c.counters["runs_started"] == runs
      and w.c._poll_due is None,  # noqa: SLF001
      f"fired {fired} covered {delta(w, c0, 'poll_steps_covered')} deferred {delta(w, c0, 'poll_steps_deferred_floor')}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# the poll text alone between the start and the snapshot, its SOC readings one second later (a partial poll)
w = refresh_world("between_partial")
job, late, hold, c0, start = held_cycle(w, None, [(1.0, lambda: write_soc(w, "61"))])
check("a partial poll (the text alone between the start and the snapshot, the SOC 1 s later): the snapshot is held to "
      "the text's settle delay's end and reads the later SOC, not the previous poll's", job is not None
      and job.states.get(SOC, {}).get("state") == "61" and job.states.get(CANON_SOC, {}).get("state") == "61"
      and job.states.get(TEL, {}).get("last_changed") == late.get("at"),
      str(None if job is None else (job.states.get(SOC, {}).get("state"), job.states.get(CANON_SOC, {}).get("state"))))
check("... with the newest poll's liveness and a cycle time at the delay's end; the start (the floor's) is unchanged",
      job is not None and job.liveness_at == late["at"] and job.now == late["at"] + SETTLE
      and w.c._last_start == start  # noqa: SLF001
      and hold.calls[:1] == [(late["at"], CONST.PROPOSED_POLL_SETTLE_S, TASK_LABEL)],
      f"{None if job is None else (job.now, job.liveness_at)} {hold.calls}")
check("... counted (snapshot_holds 1, no residual) and published with numbers", delta(w, c0, "snapshot_holds") == 1
      and delta(w, c0, "snapshot_residual_reads") == 0 and published_ok(w), str(w.c.counters["snapshot_holds"]))
runs = w.c.counters["runs_started"]
fired = fire_due_step(w)
check("... and covers that poll: its own step starts no second cycle and is not deferred to the floor's end",
      fired and delta(w, c0, "poll_steps_covered") == 1 and delta(w, c0, "poll_steps_deferred_floor") == 0
      and w.c.counters["runs_started"] == runs, f"{fired} {delta(w, c0, 'poll_steps_deferred_floor')}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# the poll's own step fires during the hold (at its due time, before the hold ends and the snapshot is read)
w = refresh_world("between_step_first")
probe: dict = {}


def step_during_hold() -> None:
    probe["jobs_before"] = len(w.jobs)
    probe["fired"] = fire_due_step_inline(w)
    probe["armed"] = [t["due"] for t in w.hass.later if t["active"]]
    probe["due"] = w.c._poll_due  # noqa: SLF001


job, late, hold, c0, start = held_cycle(w, None, [(1.0, lambda: write_soc(w, "61")),
                                                  (CONST.PROPOSED_POLL_SETTLE_S, step_during_hold)])
armed_end = [t["due"] for t in w.hass.later if t["active"]]
check("the poll's own step, due during the hold (before the snapshot is read), is neither armed nor fired while the "
      "cycle is in flight (the quiet cycle): its due time is kept",
      probe.get("fired") is False and probe.get("armed") == [] and probe.get("due") == late.get("at") + SETTLE
      and delta(w, c0, "poll_steps_held_busy") == 1, str(probe))
check("... the snapshot is then read at the hold's end (the later SOC) and published; one cycle in all",
      job is not None and probe.get("jobs_before") == len(w.jobs) - 1 and job.states.get(SOC, {}).get("state") == "61"
      and published_ok(w) and delta(w, c0, "runs_started") == 1, f"{probe} {delta(w, c0, 'runs_started')}")
runs = w.c.counters["runs_started"]
fired = fire_due_step(w)
check("... the cycle's end arms it at that due time (max(due, now)); fired there it is covered by the held cycle: no "
      "deferral, no second cycle, no step left", armed_end == [late.get("at") + SETTLE] and fired
      and delta(w, c0, "poll_steps_covered") == 1 and delta(w, c0, "poll_steps_deferred_floor") == 0
      and w.c.counters["runs_started"] == runs and w.c._poll_due is None,  # noqa: SLF001
      f"{armed_end} {fired} {delta(w, c0, 'poll_steps_covered')} {delta(w, c0, 'poll_steps_deferred_floor')}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# the residual: a second poll text during the hold (two polls within one settle delay)
w = refresh_world("between_residual")
second: dict = {}


def second_poll() -> None:
    second["at"] = h.now
    write_text(w)
    write_soc(w, "62")


job, late, hold, c0, start = held_cycle(w, "61", [(1.5, second_poll)])
check("the residual: a second poll text during the hold is not waited for (one hold of 3 s) and is counted in "
      "snapshot_residual_reads", len(hold.calls) == 1 and hold.calls[0][1] == CONST.PROPOSED_POLL_SETTLE_S
      and delta(w, c0, "snapshot_holds") == 1 and delta(w, c0, "snapshot_residual_reads") == 1
      and job is not None and job.liveness_at == second.get("at") and job.now == late["at"] + SETTLE,
      f"{hold.calls} {w.c.counters['snapshot_residual_reads']} {None if job is None else job.liveness_at}")
fired = fire_due_step(w)
check("... that poll is not covered: the step due at the first poll's settle end is deferred to the floor's end",
      fired and delta(w, c0, "poll_steps_covered") == 0 and delta(w, c0, "poll_steps_deferred_floor") == 1
      and w.c._poll_due == start + timedelta(seconds=CONST.PROPOSED_REFRESH_FLOOR_S),  # noqa: SLF001
      f"{fired} {delta(w, c0, 'poll_steps_covered')} {w.c._poll_due}")  # noqa: SLF001
runs = w.c.counters["runs_started"]
h.set_now(start + timedelta(seconds=CONST.PROPOSED_REFRESH_FLOOR_S))
fired = fire_due_step(w)
check("... where it refreshes (a refresh is due: the result's validity is under the poll threshold), and publishes",
      fired and w.c.counters["runs_started"] == runs + 1 and delta(w, c0, "poll_steps_covered") == 0
      and w.c._last_trigger == COORD.POLL and published_ok(w),  # noqa: SLF001
      f"{fired} {w.c.counters['runs_started'] - runs} {w.c._last_trigger}")  # noqa: SLF001
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# a held start inside a newer poll's settle delay (the start's residual) is not held again at its snapshot (one-shot)
w = refresh_world("between_start_residual")
fire_due_step(w)                               # the refresh of the poll refresh_world wrote
a_at = h.now + timedelta(seconds=60)
h.set_now(a_at)
w.poll()                                       # poll A
h.set_now(a_at + timedelta(seconds=2))
write_text(w)                                  # poll B, inside A's settle delay
write_soc(w, "61")
h.set_now(a_at + SETTLE)
c0 = dict(w.c.counters)
fire_due_step(w)                               # A's step: held to B's settle end (A36 at the start)
h.set_now(a_at + timedelta(seconds=4))
write_text(w)                                  # poll C, inside B's settle delay
write_soc(w, "62")
h.set_now(a_at + timedelta(seconds=2) + SETTLE)
hold = FakeSettleWait()
COORD._settle_wait = hold
n_jobs = len(w.jobs)
try:
    fired = fire_due_step(w)                   # the held step: a residual start inside C's settle delay
finally:
    COORD._settle_wait = ORIG_SETTLE_WAIT
check("a held start inside a newer poll's settle delay (the start's residual, counted) is not held again at its "
      "snapshot: no poll since its start, so the snapshot is read at once", fired and len(w.jobs) == n_jobs + 1
      and delta(w, c0, "settle_holds") == 1 and delta(w, c0, "settle_residual_starts") == 1 and hold.calls == []
      and delta(w, c0, "snapshot_holds") == 0, f"{fired} {hold.calls} {w.c.counters['settle_residual_starts']}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# the hold never runs past the cycle's deadline (the time budget)
w = refresh_world("between_deadline")
w.c.time_budget_s = 2.0
job, late, hold, c0, start = held_cycle(w, "61")
check("the hold is cut to the cycle's deadline (a 2 s time budget: less than the 3 s asked otherwise, more than 1.5 s)",
      len(hold.calls) == 1 and 1.5 < hold.calls[0][1] <= 2.0, str(hold.calls))
w.c.time_budget_s = CONST.PROPOSED_TIME_BUDGET_S
for _ in range(100):                           # an engine job left over by the short budget ends before the next world
    if not w.c._orphans:  # noqa: SLF001
        break
    time.sleep(0.05)
    h.settle()
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# a SLOT cycle with a poll between its start and its snapshot: the history inputs are read at the cycle time
w = first_cycle_world("between_slot_history")
metrics_at: list = []
stats_args: list = []
o_metrics = w.c.store.outcome_metrics


def metrics_spy(at):
    metrics_at.append(at)
    return o_metrics(at)


def stats_spy_args(*a):
    stats_args.append(a)
    return ORIG_STATS(*a)


w.c.store.outcome_metrics = metrics_spy
COORD.statistics_during_period = stats_spy_args
try:
    job, late, hold, c0, start = held_cycle(w, "61")
finally:
    COORD.statistics_during_period = ORIG_STATS
hist = w.c._hist or {}  # noqa: SLF001
check("non-vacuity: a held SLOT cycle, whose cycle time is 3.5 s after its start", job is not None
      and w.c._last_kind == COORD.SLOT and job.now == start + timedelta(seconds=0.5) + SETTLE,  # noqa: SLF001
      f"{w.c._last_kind} {None if job is None else job.now} {start}")  # noqa: SLF001
check("the history inputs are read at the cycle time, not at the start: the cache's read_at, the scorecard metrics and "
      "the recorder window", job is not None and hist.get("read_at") == job.now and metrics_at == [job.now]
      and len(stats_args) == 1 and tuple(stats_args[0][1:3]) == tuple(HISTORY_SOURCE.window(job.now)),
      f"read_at {hist.get('read_at')} metrics {metrics_at} job {None if job is None else job.now}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# the real hold waits on the event loop's clock and lets the loop run meanwhile
other: list = []


async def real_hold() -> float:
    h.loop.call_soon(lambda: other.append("ran"))
    t0 = h.loop.time()
    await ORIG_SETTLE_WAIT(0.2)
    return h.loop.time() - t0


dt_hold = h.run(real_hold())
check("the real hold (coordinator._settle_wait) waits the seconds asked on the loop's clock and yields meanwhile",
      0.15 <= dt_hold < 1.5 and other == ["ran"], f"{dt_hold:.3f} {other}")

# a tick between the snapshot and the engine job
w = World("between_tick")
h.set_now(NOW + timedelta(seconds=60))
w.tick()
h.settle()
h.set_now(h.now + timedelta(seconds=60))
w.poll()
h.set_now(h.now + timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S))
snap: dict = {}
o_collect = w.c._collect_states  # noqa: SLF001


def tick_after_snapshot():
    """A tick between the snapshot step and the engine job, after a newer poll text (one second later)."""
    h.set_now(h.now + timedelta(seconds=1))
    w.hass.states.seed(TEL, H.poll_time_text(h.now), changed_at=h.now)
    w.c._tick(h.now)  # noqa: SLF001
    snap["after_tick"] = w.c._liveness_at  # noqa: SLF001


def collect_then_tick():
    out = o_collect()
    snap["liveness_at"] = w.c._liveness_at  # noqa: SLF001
    snap["text"] = out.get(TEL, {}).get("state")
    h.loop.call_soon(tick_after_snapshot)
    return out


w.c._collect_states = collect_then_tick  # noqa: SLF001
n_jobs = len(w.jobs)
w.fire_poll_step()
h.settle()
job = w.jobs[n_jobs] if len(w.jobs) > n_jobs else None
check("non-vacuity: the tick between the steps sampled a newer poll text", snap.get("after_tick") is not None
      and snap.get("after_tick") != snap.get("liveness_at"), str(snap))
check("a tick between the snapshot and the engine job leaves the job the snapshot's liveness time and states",
      job is not None and job.liveness_at == snap.get("liveness_at")
      and job.states.get(TEL, {}).get("state") == snap.get("text"),
      f"{None if job is None else job.liveness_at} {snap}")
check("... no write attempt and no stand-in violation", w.clean(), str(w.hass.violations)[:300])
w.close()

# --- [5] an unload and a cancel at each yield point -------------------------------------------------------------------------
print("== [5] an unload and a cancel at each yield point")


def cancel_at(point: str, how: str) -> None:
    w = first_cycle_world(f"cancel_{point}_{how}")
    co = w.c
    hold = threading.Event()
    held = threading.Event()
    state = {"writes": None, "payloads": None}

    def act() -> None:
        if state.get("acted"):
            return                                 # one-shot: the next cycle runs undisturbed
        state["acted"] = True
        state["writes"] = len(w.hass.state_writes)
        state["payloads"] = dict(co.payloads)
        if how == "cancel":
            co._task.cancel()  # noqa: SLF001 - as Home Assistant cancels a background task at shutdown
        else:
            w.hass.async_create_task(PKG.async_unload_entry(w.hass, w.entry), "unload", eager_start=False)

    def from_executor() -> None:
        h.loop.call_soon_threadsafe(act)
        held.set()
        hold.wait(30)

    if point == "checks":
        o = co._pause_state  # noqa: SLF001
        n = {"k": 0}

        def f():
            r = o()
            if in_cycle():
                n["k"] += 1
                if n["k"] == 1:
                    act()
            return r
        co._pause_state = f  # noqa: SLF001
    elif point == "snapshot":
        o = co._collect_states  # noqa: SLF001

        def f():
            r = o()
            act()
            return r
        co._collect_states = f  # noqa: SLF001
    elif point == "history":
        o = co._history_inputs  # noqa: SLF001

        async def f(*a, **k):
            r = await o(*a, **k)
            act()
            return r
        co._history_inputs = f  # noqa: SLF001
    elif point == "engine":
        def compute(job, run_cycle=None):
            w.jobs.append(job)
            from_executor()
            return ORIG_COMPUTE(job, run_cycle)
        ENGINE_LINK.compute = compute
    elif point == "recorder":
        def stats(*a):
            from_executor()
            return ORIG_STATS(*a)
        COORD.statistics_during_period = stats
    elif point == "store":
        o = co.store.record_cycle

        def rec(*a):
            from_executor()
            return o(*a)
        co.store.record_cycle = rec
    elif point == "hold":                          # during the settle hold at the snapshot (a poll text since the start)
        settle_fake = FakeSettleWait()
        settle_fake.during = [(1.0, act)]
        COORD._settle_wait = settle_fake
    try:
        if point == "start":
            due = [t for t in w.hass.later if t["active"] and t["due"] <= h.now]
            t = min(due, key=lambda x: x["due"])
            t["active"] = False

            def fire():
                t["action"](h.now)
                if how == "cancel":
                    act()
                else:                              # an unload whose first step runs before the cycle's first step
                    state["writes"] = len(w.hass.state_writes)
                    state["payloads"] = dict(co.payloads)
                    coro = co.async_stop()
                    try:
                        coro.send(None)
                    except StopIteration:
                        pass
            w.in_loop(fire)
        elif point == "hold":
            w.fire_poll_step(lambda: h.loop.call_soon(late_poll(w, {}, None)))
        else:
            w.fire_poll_step()
        h.settle()
        if point in ("engine", "recorder", "store"):
            held.wait(10)
            hold.set()
            time.sleep(0.2)
            h.settle()
        if how == "unload" and point == "start":
            h.unload(w.entry)
        last = list(co.cycle_stats)[-1] if co.cycle_stats else None
        label = f"{how} at '{point}'"
        check(f"{label}: the cycle ends once, with the outcome 'cancelled', and the second-run guard released",
              last is not None and [r[2] for r in co.cycle_stats] == ["cancelled"] and co._busy is False  # noqa: SLF001
              and co._pending_start is None, f"{list(co.cycle_stats)} busy={co._busy}")  # noqa: SLF001
        if point == "hold":
            check(f"{label}: the hold was entered, and a cancelled hold covers nothing (that poll is not covered)",
                  len(settle_fake.calls) == 1 and co._read_poll_seq != co._poll_seq,  # noqa: SLF001
                  f"{settle_fake.calls} {co._read_poll_seq} {co._poll_seq}")  # noqa: SLF001
        before_engine = point in ("start", "checks", "hold", "snapshot", "history", "recorder")
        if how == "unload":
            check(f"{label}: nothing is written or published after the unload, and no engine job runs that had not "
                  "started", co.closed and len(w.hass.state_writes) == state["writes"] and co.payloads == state["payloads"]
                  and (not before_engine or len(w.jobs) == 0) and co.counters["runs_published"] == (1 if point == "store"
                                                                                                    else 0),
                  f"writes {len(w.hass.state_writes)} vs {state['writes']}, jobs {len(w.jobs)}")
        else:
            check(f"{label}: no engine job runs that had not started, and nothing is published by the cancelled cycle",
                  (not before_engine or len(w.jobs) == 0)
                  and co.counters["runs_published"] == (1 if point == "store" else 0), f"jobs {len(w.jobs)}")
            ENGINE_LINK.compute = w._compute  # noqa: SLF001
            COORD.statistics_during_period = ORIG_STATS
            before = co.counters["runs_published"]
            # the cancelled cycle was this hour's slot cycle: the next one is due at the next slot (no poll arriving)
            h.set_now(NOW.replace(minute=0) + timedelta(hours=1, minutes=1))
            w.hass.states.events = False
            H.seed_fresh_states(w.hass.states, h.now)
            w.tick()
            h.settle()
            check(f"{label}: the next tick starts a new cycle, which publishes",
                  co.counters["runs_published"] == before + 1,
                  f"{co.counters['runs_published']} {list(co.cycle_stats)[-2:]} {co.counters}")
        check(f"{label}: no write attempt, no stand-in violation, no task left", w.clean()
              and not [x for x in w.hass.tasks if not x.done()], str(w.hass.violations)[:300])
    finally:
        hold.set()
        COORD.statistics_during_period = ORIG_STATS
        COORD._settle_wait = ORIG_SETTLE_WAIT
        w.close()


for point in ("start", "checks", "hold", "snapshot", "history", "recorder", "engine", "store"):
    for how in ("unload", "cancel"):
        cancel_at(point, how)

# --- [6] the job names ------------------------------------------------------------------------------------------------------
print("== [6] the job names")
CORE_EVENT_PY = "homeassistant/helpers/event.py"


def core_track_time_interval():
    """The pinned Core's _TrackTimeInterval (helpers/event.py of 2026.10.4, read only): its slotted dataclass, the two
    HassJobs of async_attach and the call_at of _schedule_timer, compiled under the Core's file name with that call_at at
    its line 1610, so a debug-mode handle's created-at text is the Core's."""
    lines = [""] * 1620

    def put(n: int, text: list[str]) -> None:
        lines[n - 1:n - 1 + len(text)] = text
    put(1574, ["@dataclass(slots=True)",
               "class _TrackTimeInterval:",
               "    hass: object",
               "    seconds: float",
               "    job_name: str",
               "    action: object",
               "    cancel_on_shutdown: object",
               "    _track_job: object = None",
               "    _run_job: object = None",
               "    _timer_handle: object = None"])
    put(1587, ["    def async_attach(self):",
               "        self._track_job = HassJob(self._interval_listener, self.job_name, job_type=HassJobType.Callback,"
               " cancel_on_shutdown=self.cancel_on_shutdown)",
               "        self._run_job = HassJob(self.action, f'track time interval {self.seconds}',"
               " cancel_on_shutdown=self.cancel_on_shutdown)",
               "        self._schedule_timer()"])
    put(1606, ["    def _schedule_timer(self):",
               "        loop = self.hass.loop"])
    put(1610, ["        self._timer_handle = loop.call_at(loop.time() + self.seconds, self._interval_listener,"
               " self._track_job)"])
    put(1614, ["    @callback",
               "    def _interval_listener(self, _):",
               "        self._schedule_timer()"])
    ns = {"dataclass": dataclasses.dataclass, "HassJob": CORE.HassJob, "HassJobType": CORE.HassJobType,
          "callback": CORE.callback}
    exec(compile("\n".join(lines), CORE_EVENT_PY, "exec"), ns)  # noqa: S102 - a fixed mirror of the Core's source
    return ns["_TrackTimeInterval"]


w = World("names")
check("the tick's interval timer carries TICK_JOB_NAME", w.timer().get("name") == CONST.TICK_JOB_NAME
      and CONST.TICK_JOB_NAME.startswith("ecco_intelligence"), str(w.timer().get("name")))
h.set_now(NOW + timedelta(seconds=10))
w.poll()
later = [t for t in w.hass.later if t["active"]]
job = later[-1].get("job") if later else None
check("the poll-driven step's one-shot is a HassJob named POLL_STEP_JOB_NAME on _on_poll_step",
      isinstance(job, CORE.HassJob) and job.name == CONST.POLL_STEP_JOB_NAME and job.target == w.c._on_poll_step  # noqa: SLF001
      and job.job_type is CORE.HassJobType.Callback, repr(job))
text = reprlib.repr(job)
check("asyncio's reprlib text of that job keeps '<Job ecco_int' in front and ends with the integration's name",
      text.startswith("<Job ecco_int") and text.endswith("ntelligence>>>") and len(text) == 30, text)
check("repr of the coordinator names the integration", repr(w.c) == "<EccoIntelCoordinator ecco_intelligence>", repr(w.c))
timer = w.timer()
seconds = timer["interval"].total_seconds()
job_name = f"track time interval {seconds} {timer['action']}"           # the Core's async_track_time_interval
if timer["name"]:
    job_name = f"{timer['name']}: {job_name}"
track = core_track_time_interval()(w.hass, seconds, job_name, timer["action"], None)
debug = h.loop.get_debug()
h.loop.set_debug(True)                     # a slow-callback line comes from a debug session: handles keep where made
try:
    track.async_attach()
    first = track._timer_handle  # noqa: SLF001
    track._interval_listener(None)  # noqa: SLF001 - it ran: the Core's listener schedules the next timer first
    tick_line, tick_job_text, tick_job_full = str(first), reprlib.repr(track._track_job), repr(track._track_job)  # noqa: SLF001
finally:
    first.cancel()
    track._timer_handle.cancel()  # noqa: SLF001
    h.loop.set_debug(debug)
check("the tick's timer, laid out as the pinned Core's _TrackTimeInterval: its job is named '<TICK_JOB_NAME>: track time "
      "interval 60.0 <the tick>' and runs _TrackTimeInterval._interval_listener",
      tick_job_full.startswith(f"<Job {CONST.TICK_JOB_NAME}: track time interval 60.0 {w.c._tick!r} "  # noqa: SLF001
                               "HassJobType.Callback <bound method _TrackTimeInterval._interval_listener of "
                               "_TrackTimeInterval(") and repr(w.c._tick).endswith("<EccoIntelCoordinator ecco_intelligence>>"),  # noqa: SLF001
      tick_job_full[:220])
check("... so its slow-callback line shows '_TrackTimeInterval._interval_listener(<Job ecco_int...nt.py:1610>)>>)' "
      "('<Job ecco_int' in front, the tail the tracker's next handle, made at helpers/event.py:1610)",
      tick_job_text == "<Job ecco_int...nt.py:1610>)>>" and tick_line.startswith("<TimerHandle when=")
      and tick_line.endswith(" _TrackTimeInterval._interval_listener(<Job ecco_int...nt.py:1610>)>>) created at "
                             f"{CORE_EVENT_PY}:1610>"), tick_line)
h.set_now(h.now + timedelta(seconds=CONST.PROPOSED_POLL_SETTLE_S))
w.fire_poll_step()
h.settle()
cycles = [x for x in w.hass.task_log if x[0] == CYCLE]
check("every cycle task is CYCLE_TASK_NAME, created with eager_start=False", cycles == [(CYCLE, False)]
      and all(n is not None for n, _e in w.hass.task_log), str(w.hass.task_log))
w.close()

# --- [7] the release of executor jobs ---------------------------------------------------------------------------------------
print("== [7] the release of executor jobs")
w = first_cycle_world("release")
o_exec = w.hass.async_add_executor_job
o_rec = h.recorder().async_add_executor_job
stats_label: list = []


def long_tail(orig):
    def submit(target, *args):
        fut = orig(target, *args)
        end = time.perf_counter() + 0.05          # the submitting step runs on for 50 ms after the submit
        while time.perf_counter() < end:
            pass
        return fut
    return submit


def stats_spy(*a):
    stats_label.append(LOOP["label"])
    return ORIG_STATS(*a)


w.hass.async_add_executor_job = long_tail(o_exec)
h.recorder().async_add_executor_job = long_tail(o_rec)
COORD.statistics_during_period = stats_spy
try:
    w.fire_poll_step()
    h.settle()
finally:
    COORD.statistics_during_period = ORIG_STATS
check("the engine job starts only after the step that submitted it has ended (that step ran on for 50 ms)",
      len(w.compute_label) == 1 and w.compute_label[0] != TASK_LABEL, str(w.compute_label))
check("... so does the recorder read", len(stats_label) == 1 and stats_label[0] != TASK_LABEL, str(stats_label))
check("... and the cycle published", w.c.counters["runs_published"] == 1 and w.clean(), str(w.c.counters["runs_published"]))
flag_probe: dict = {}


async def flag_steps() -> None:
    flag = PKG.release_after_step(w.hass)
    flag_probe["at_submit"] = flag[0]
    await asyncio.sleep(0)
    flag_probe["next_step"] = flag[0]
h.run(flag_steps())
check("release_after_step's flag is unset in the submitting step and set by the loop's next handle",
      flag_probe == {"at_submit": False, "next_step": True}, str(flag_probe))
ran_at: list = []


def target(x=None):
    ran_at.append(time.perf_counter())
    return "ran" if x is None else x + 1


t0 = time.perf_counter()
r_set = PKG.released_call([True], target, 41)
dt_set, start_set = time.perf_counter() - t0, ran_at[-1] - t0
cap = PKG.SUBMIT_RELEASE_CAP_S
PKG.SUBMIT_RELEASE_CAP_S = 0.05
try:
    t0 = time.perf_counter()
    r_unset = PKG.released_call([False], target)
    start_unset = ran_at[-1] - t0
finally:
    PKG.SUBMIT_RELEASE_CAP_S = cap
check("released_call runs its target at once when released, and returns its result SUBMIT_COOLDOWN_S after the target "
      "has (the cool-down)", r_set == 42 and start_set < 0.04 and dt_set - start_set >= CONST.SUBMIT_COOLDOWN_S - 0.005,
      f"{r_set} {start_set:.3f} {dt_set:.3f}")
check("... and starts it after SUBMIT_RELEASE_CAP_S when the release never comes (never waits for a stopped loop)",
      r_unset == "ran" and 0.04 <= start_unset < 0.5 and CONST.SUBMIT_RELEASE_CAP_S == cap == 1.0,
      f"{r_unset} {start_unset:.3f}")
w.close()

H.rmtree_own(root, PREFIX)
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the runtime loop steps:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime loop-step checks passed")
