"""FB-B1 harness: the discrete-event engine behind FbbSim.

_dump_sim runs scripts synchronously to completion and FB-B0's FbbSim adds a
blocking wait loop. FB-B1's behaviour (a gate that is NOT running while the
dispatch it started is parked, a stale Modbus callback delivered after a
bounded wait failed, a housekeeping interval firing while a script waits)
needs ESPHome's real shape: ONE loop task, scripts that park at wait_until /
delay and let everything else run. This module adds exactly that to FbbSim
(opt-in per call - the FB-B0 blocking `execute()` is unchanged):

  timeline     virtual clock `sim.now_ms` (an unbounded int; millis() is its
               low 32 bits, so a wrap is a start time near 2**32). Events are
               ordered by (time, priority, order, insertion):
                 P_EXTERNAL 0  the world changes first: injected events (bank
                               mutation, button press from HA, foreign frame,
                               power cut)
                 P_SCHED    1  ESPHome's scheduler: intervals (in declaration
                               order), `delay` expiry, `wait_until` timeouts
                 P_LOOP     2  the component loop: hub frame start / reply
                               delivery (handlers) and `wait_until` condition
                               polls (every `tick_ms`)
               This is one ESPHome main-loop iteration: scheduler first, then
               the loops.
  tasks        a script / button automation / interval is a generator over its
               action tree. `script.execute` runs the callee until its FIRST
               park and returns (the caller continues immediately), exactly
               as ESPHome does; `mode: single` re-entry is dropped;
               `is_running()` is true from start until the last action.
               A lambda is atomic (it can never park).
  intervals    `start_intervals(select)`: period, startup_delay, declaration
               order, optional per-interval phase, re-armed on the SCHEDULED
               time (no drift). Each firing is its own task.
  modbus       `set_modbus_mode("deferred", latency_ms)`: a read node queues a
               frame on the hub model; frames go on the wire one at a time,
               tx_buffer_empty() / tx_blocked() follow the queue / the frame in
               flight, and the outcome handler is delivered `latency_ms` later
               by the engine - also while no script runs, and after the
               script that issued it has long given up.
  events       at / after / at_press / at_bank / at_foreign_frame /
               at_power_cut / hold_script_running / hold_bus.
  safety       mark() / since(): zero writes, zero NVS sets, exact read list.

FB-B2 additions (self-tested by test_fallback_save_harness.py):
  api          call_api(name, **vars): an api action by name, its `string` variables as esphome::StringRef (_fbb1_types), its
               `then:` on the same scheduler (it is not a script: no is_running(), two calls run side by side); at_api().
  switches     template-switch model: Switch::turn_on()/turn_off() = write_state(): the turn_on_action / turn_off_action
               automation runs EVERY time, then (optimistic) publish_state(), which deduplicates and fires on_turn_on /
               on_turn_off / on_state; operator_switch() / at_operator_switch() are Home Assistant flipping a switch.
  safety+      Since.fb_sets / violations_fb(): the FB-B2 variant of Since.violations() - it allows exactly the expected
               ordered direct-NVS sets of the two FB durable keys (FBW then FBP) with exactly the expected bytes, and still
               flags any Modbus write, any set to another key (FBS never), any ecco_durable commit.

No I/O, no hardware.
"""

from __future__ import annotations

import copy
import heapq
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _dump_sim as ds  # noqa: E402
import fallback_durable as fd  # noqa: E402
from _fbb1_types import FbbNotModelled, FbbTimeout, PowerCut, STRINGREF_TAIL, StringRef, duration_ms  # noqa: E402

# FB-B3 Slice A: the Live Match tick's own RAM-only state (see state_diff).
FBB3_OWN_GLOBALS = ("fallback_profile_live_fence_seq", "fallback_profile_live_edge_seq", "fallback_profile_live_writes_fp",
                    "fallback_profile_live_fence_flags")
FBB3_OWN_ENTITY = "fallback_profile_live_match_text"

P_EXTERNAL, P_SCHED, P_LOOP = 0, 1, 2
FRAME_OUTCOMES = ("ok", "error", "not_sent", "no_response", "custom_response", "timeout")
_HANDLER_OF = {"ok": "on_response", "error": "on_error", "not_sent": "on_not_sent", "no_response": "on_no_response",
               "custom_response": "on_custom_response"}
MAX_EVENTS_PER_PUMP = 2_000_000


@dataclass
class FrameSpec:
    """How one Modbus read behaves. `latency_ms` is the time on the wire in
    deferred mode (default `sim.frame_latency_ms`); `exception_code` is what an
    on_error handler sees (default `sim.exception_code`); `values` replaces the
    register-bank snapshot an on_response handler receives."""

    outcome: str = "ok"
    latency_ms: int | None = None
    exception_code: int | None = None
    values: list | None = None


@dataclass
class Wire:
    """One frame on the simulated wire (`sim.wire_log`, in wire order)."""

    origin: str          # "fw" (a YAML action) | "foreign" (injected: a config poll, an RTC read, another master)
    kind: str            # "read" | "write"
    addr: int
    count: int
    outcome: str
    t_queued: int
    t_start: int | None = None
    t_end: int | None = None
    values: list | None = None
    issuer: str | None = None  # the script / "button:<id>" / "interval[<n>]" task that issued it (None: foreign / no task)


class Frame:
    def __init__(self, origin, addr, count, spec, body=None, local=None, on_deliver=None):
        self.origin, self.addr, self.count, self.spec = origin, addr, count, spec
        self.body, self.local, self.on_deliver = body, local, on_deliver
        self.wire = Wire(origin, "read", addr, count, spec.outcome, t_queued=0)
        self.values = None


class _Ev:
    __slots__ = ("t", "fn", "name", "cancelled", "recurring")

    def __init__(self, t, fn, name, recurring):
        self.t, self.fn, self.name, self.cancelled, self.recurring = t, fn, name, False, recurring


class Task:
    """A running automation: a script instance, a button press or an interval firing."""

    def __init__(self, tid, script_id, label, gen):
        self.id, self.script_id, self.label, self.gen = tid, script_id, label, gen
        self.done = False
        self.started_ms = 0
        self.finished_ms = None
        self.park = None  # None | "delay" | "wait"
        self.timed_out = False
        self.result_error = None

    @property
    def parked(self):
        """None (ready / done), "wait" (in a wait_until) or "delay"."""
        return "wait" if isinstance(self.park, _Wait) else self.park

    def __repr__(self):
        return f"Task({self.label}#{self.id} {'done' if self.done else (self.parked or 'ready')})"


class _Wait:
    def __init__(self, cond, deadline):
        self.cond, self.deadline = cond, deadline
        self.done = False
        self.poll = None
        self.timeout = None


@dataclass
class _IntervalState:
    idx: int
    period: int
    next: int
    rearm: str
    fired: int = 0
    ev: object = None


@dataclass
class Mark:
    modbus: int
    wire: int
    nvs_ops: int
    commits: int
    loads: int
    executed: int
    events: int
    legacy_nvs: dict  # tag -> record fingerprint at mark time
    nvs_sets: int = 0  # FB-B2: len(DirectNvs.sets) at mark time (the payload-carrying set log)


class Since:
    """Everything that happened after a Mark - the safety evidence."""

    def __init__(self, sim, m: Mark):
        self.modbus = list(sim.modbus_log[m.modbus:])
        self.wire = list(sim.wire_log[m.wire:])
        self.nvs_ops = list(sim.nvs_direct.ops[m.nvs_ops:])
        self.commits = list(sim.nvs_commits[m.commits:])
        self.loads = list(sim.nvs_loads[m.loads:])
        self.executed = list(sim.executed[m.executed:])
        self.events = list(sim.events[m.events:])
        self.legacy_changed = sorted(k for k in set(sim.nvs) | set(m.legacy_nvs)
                                     if _rec_key(sim.nvs.get(k)) != m.legacy_nvs.get(k))
        # FB-B2: every direct-NVS set_blob since the mark as (key, bytes, result)
        self.nvs_set_log = list(sim.nvs_direct.sets[m.nvs_sets:])

    @property
    def writes(self):
        return [e for e in self.modbus if e[0] == "write"]

    @property
    def reads(self):
        """(address, count) of every firmware read that reached the wire, in order."""
        return [(e[1], len(e[2])) for e in self.modbus if e[0] == "read"]

    @property
    def wire_reads(self):
        return [(w.addr, w.count, w.origin) for w in self.wire if w.kind == "read"]

    def reads_by(self, issuer_prefix: str):
        """(address, count) of the firmware reads on the wire issued by tasks whose label starts with
        `issuer_prefix` (e.g. "fallback_profile_") - lets a test run the real polls next to a REVIEW."""
        return [(w.addr, w.count) for w in self.wire
                if w.kind == "read" and w.origin == "fw" and (w.issuer or "").startswith(issuer_prefix)]

    @property
    def nvs_sets(self):
        return [o for o in self.nvs_ops if o[0] == "set"]

    @property
    def nvs_read_probes(self):
        """Direct-NVS size probes: one per read_direct_t call (the data step is a second op)."""
        return [o for o in self.nvs_ops if o[0] == "get"]

    # -- FB-B2: the write-allowing safety audit ------------------------------------------------------------------
    @property
    def fb_sets(self):
        """[(name, bytes, result)] of every direct-NVS set to an FB key since the mark, in call order (name FBP / FBW / FBS)."""
        return [(FB_KEY_NAMES[k], d, r) for k, d, r in self.nvs_set_log if k in FB_KEY_NAMES]

    @property
    def fb_set_order(self):
        """The FB key names of the sets, in order: ["FBW", "FBP"] for a clean SAVE / INVALIDATE."""
        return [n for n, _d, _r in self.fb_sets]

    @property
    def other_nvs_sets(self):
        """Direct-NVS sets to any key that is not FBP / FBW / FBS (decimal key strings)."""
        return [fd.decimal_key(k) for k, _d, _r in self.nvs_set_log if k not in FB_KEY_NAMES]

    def violations_fb(self, expect=(), *, bytes_=None, reads=None, allow_legacy=False):
        """The FB-B2 variant of violations(): empty list = nothing but the EXPECTED durable write happened.
        Always flagged: ANY Modbus write; a direct-NVS set to a key that is not FBP / FBW (FBS is never written in FB-B);
        any FB set sequence other than `expect` - the ordered FB key names / keys, e.g. ("FBW", "FBP") for a SAVE or
        INVALIDATE (witness first), ("FBW",) for a witness-only landing, () for "nothing was written"; a set whose bytes
        differ from `bytes_` (a dict name -> bytes, or a sequence aligned with `expect`); an ecco_durable commit / record
        change (unless allow_legacy); and, if given, a read list other than `reads`."""
        out = []
        if self.writes:
            out.append(f"Modbus writes: {self.writes}")
        if self.other_nvs_sets:
            out.append(f"direct NVS sets to keys that are not FBP / FBW: {self.other_nvs_sets}")
        if "FBS" in self.fb_set_order:
            out.append("a direct NVS set of FBS (FBS is never written in FB-B)")
        want = [fb_key_name(x) for x in expect]
        order = [n for n in self.fb_set_order if n != "FBS"]
        if order != want:
            out.append(f"FB NVS sets {order} != expected {want}")
        if bytes_ is not None:
            fb = [(n, d) for n, d, _r in self.fb_sets if n != "FBS"]
            if isinstance(bytes_, dict):
                exp = [(n, bytes_[n]) for n, _d in fb if n in bytes_]
                got = [(n, d) for n, d in fb if n in bytes_]
            else:
                exp = list(zip(want, [bytes(b) for b in bytes_]))
                got = fb
            if len(exp) != len(got):
                out.append(f"FB set count {len(got)} != expected byte images {len(exp)}")
            for i, ((gn, gd), (en, ed)) in enumerate(zip(got, exp)):
                if gn != en or bytes(gd) != bytes(ed):
                    out.append(f"FB set #{i} {gn}: bytes {bytes(gd).hex()} != expected {en} {bytes(ed).hex()}")
        if not allow_legacy:
            if self.commits:
                out.append(f"ecco_durable commits: {[(k, r._kind) for k, r in self.commits]}")
            if self.legacy_changed:
                out.append(f"ecco_durable records changed: {self.legacy_changed}")
        if reads is not None and self.reads != [tuple(r) for r in reads]:
            out.append(f"reads {self.reads} != expected {[tuple(r) for r in reads]}")
        return out

    def violations(self, reads=None):
        """Empty list = read-only: no Modbus write, no NVS set, no legacy ecco_durable
        commit or change, and (if given) exactly this ordered list of (addr, count) reads."""
        out = []
        if self.writes:
            out.append(f"Modbus writes: {self.writes}")
        if self.nvs_sets:
            out.append(f"direct NVS sets: {self.nvs_sets}")
        if self.commits:
            out.append(f"ecco_durable commits: {[(k, r._kind) for k, r in self.commits]}")
        if self.legacy_changed:
            out.append(f"ecco_durable records changed: {self.legacy_changed}")
        if reads is not None and self.reads != [tuple(r) for r in reads]:
            out.append(f"reads {self.reads} != expected {[tuple(r) for r in reads]}")
        return out


FB_KEY_NAMES = {fd.FALLBACK_PROFILE_KEY: "FBP", fd.FAILBACK_PROVISION_KEY: "FBW", fd.FAILBACK_STATE_KEY: "FBS"}
_KEY_OF_NAME = {v: k for k, v in FB_KEY_NAMES.items()}


def fb_key_name(key):
    """"FBP" / "FBW" / "FBS" for a name, a 32-bit key or its decimal key string; raises on anything else."""
    if isinstance(key, str) and key in _KEY_OF_NAME:
        return key
    k = int(key)
    if k in FB_KEY_NAMES:
        return FB_KEY_NAMES[k]
    raise FbbNotModelled(f"{key!r} is not an FB durable key (FBP {fd.FALLBACK_PROFILE_KEY}, FBW {fd.FAILBACK_PROVISION_KEY}, "
                         f"FBS {fd.FAILBACK_STATE_KEY})")


def _automation_actions(spec):
    """An ESPHome automation as an action list: `[...]`, `{then: [...]}` or one bare action mapping."""
    if spec is None:
        return []
    if isinstance(spec, dict) and "then" in spec:
        return list(spec["then"] or [])
    if isinstance(spec, list):
        return spec
    if isinstance(spec, dict):
        return [spec]
    raise FbbNotModelled(f"automation {spec!r}")


def _freeze(v):
    if isinstance(v, list):
        return tuple(v)
    if hasattr(v, "to_bytes") and hasattr(v, "as_dict"):
        return (type(v).__name__, v.to_bytes())
    if isinstance(v, str):
        return str(v)
    return v


def _rec_key(rec):
    if rec is None:
        return None
    return (rec._kind, tuple(sorted((f, getattr(rec, f)) for f in ds._RECORD_FIELDS[rec._kind])))


class EngineMixin:
    """Mixed into FbbSim (see _fbb_harness). Needs: now_ms, fw, scripts, running, executed,
    entities, bank, modbus_log, events, event_hook, hub, tick_ms, run_lambda, _log_event."""

    # ------------------------------------------------------------------ setup
    def _engine_init(self):
        self._events: list = []
        self._seq = 0
        self._ctx = 0
        self._cur_task = None
        self._tid = 0
        self.tasks: list = []
        self._live: set = set()
        self._script_task: dict = {}
        self.wire_log: list = []
        self.interval_log: list = []
        self._intervals: dict = {}
        self.modbus_mode = "immediate"
        self.frame_latency_ms = 120
        self.frame_script: list = []
        self._hub_kick_pending = False
        self.sched_rng = random.Random(0x5CED)  # == seed_rng(0): separate from the random_uint32() stream

    # --------------------------------------------------------------- timeline
    def schedule(self, t, fn, prio=P_EXTERNAL, order=0, name="", recurring=False):
        self._seq += 1
        ev = _Ev(max(int(t), self.now_ms), fn, name, recurring)
        heapq.heappush(self._events, (ev.t, prio, order, self._seq, ev))
        return ev

    @staticmethod
    def cancel(ev) -> None:
        ev.cancelled = True

    def _next_time(self):
        while self._events and self._events[0][4].cancelled:
            heapq.heappop(self._events)
        return self._events[0][0] if self._events else None

    def _pump(self, target: int) -> None:
        n = 0
        while True:
            t = self._next_time()
            if t is None or t > target:
                break
            _t, _prio, _order, _seq, ev = heapq.heappop(self._events)
            if ev.t > self.now_ms:
                self.now_ms = ev.t
            n += 1
            if n > MAX_EVENTS_PER_PUMP:
                raise FbbNotModelled("scheduler livelock: too many events without the clock advancing")
            self._ctx += 1
            try:
                ev.fn()
            finally:
                self._ctx -= 1
        if target > self.now_ms:
            self.now_ms = target

    def run_until(self, t_ms: int) -> None:
        """Advance virtual time to `t_ms`, running everything due on the way."""
        self._pump(int(t_ms))

    def run_for(self, ms: int) -> None:
        self._pump(self.now_ms + int(ms))

    def busy(self) -> bool:
        if self._live:
            return True
        if self.hub.frames or self.hub.in_flight_frame is not None:
            return True
        return any(not e[4].cancelled and not e[4].recurring for e in self._events)

    def run_until_idle(self, max_ms: int = 600_000) -> int:
        """Until no task is alive, no frame is queued / in flight and no one-shot event is pending
        (recurring intervals do not count). Returns the virtual ms elapsed."""
        start = self.now_ms
        while self.busy():
            t = self._next_time()
            if t is None or t - start > max_ms:
                raise FbbTimeout(f"not idle after {max_ms} virtual ms (tasks: {sorted(self._live, key=lambda x: x.id)})")
            self._pump(t)
        return self.now_ms - start

    def run_until_done(self, what, max_ms: int = 600_000) -> int:
        """Until a Task (or the newest task of a script id) has finished."""
        task = what if isinstance(what, Task) else self.task_of(what)
        start = self.now_ms
        while not task.done:
            t = self._next_time()
            if t is None or t - start > max_ms:
                raise FbbTimeout(f"{task} did not finish within {max_ms} virtual ms")
            self._pump(t)
        return self.now_ms - start

    def task_of(self, script_id):
        for t in reversed(self.tasks):
            if t.script_id == script_id:
                return t
        raise FbbNotModelled(f"no task was ever started for script {script_id!r}")

    def rebase_clock(self, new_now_ms: int) -> None:
        """Jump the clock (e.g. to just before a millis() wrap) keeping every pending event's
        offset from `now`: timers, polls and intervals simply continue from the new time."""
        delta = int(new_now_ms) - self.now_ms
        rebuilt = []
        for t, prio, order, seq, ev in self._events:
            if ev.cancelled:
                continue
            ev.t += delta
            rebuilt.append((ev.t, prio, order, seq, ev))
        heapq.heapify(rebuilt)
        self._events = rebuilt
        self.now_ms += delta
        for st in self._intervals.values():
            st.next += delta

    # ------------------------------------------------------------------ tasks
    def _new_task(self, script_id, actions, local, label):
        self._tid += 1
        gen = self._gen_actions(actions, local)
        task = Task(self._tid, script_id, label, gen)
        task.started_ms = self.now_ms
        self.tasks.append(task)
        self._live.add(task)
        return task

    def _advance_task(self, task):
        if task.done:
            return
        self._ctx += 1
        prev, self._cur_task = self._cur_task, task
        try:
            try:
                req = next(task.gen)
            except StopIteration:
                self._finish_task(task)
                return
            except BaseException as e:
                task.result_error = e
                self._finish_task(task)
                raise
            self._park(task, req)
        finally:
            self._cur_task = prev
            self._ctx -= 1

    def _finish_task(self, task):
        task.done = True
        self._live.discard(task)
        task.park = None
        task.finished_ms = self.now_ms
        if task.script_id is not None and self._script_task.get(task.script_id) is task:
            del self._script_task[task.script_id]
            self.running.discard(task.script_id)
        self._log_event(("task", task.label, "done"))

    def _park(self, task, req):
        kind = req[0]
        if kind == "delay":
            task.park = "delay"
            self._log_event(("task", task.label, "park:delay"))
            self.schedule(self.now_ms + req[1], lambda: self._resume_delay(task), P_SCHED, order=10_000, name="delay")
            return
        if kind == "wait":
            cond, timeout = req[1], req[2]
            wait = _Wait(cond, None if timeout is None else self.now_ms + timeout)
            task.park = wait
            task.timed_out = False
            self._log_event(("task", task.label, "park:wait"))
            wait.poll = self.schedule(self.now_ms + self.tick_ms, lambda: self._poll_wait(task, wait), P_LOOP,
                                      name="wait-poll")
            if timeout is not None:
                wait.timeout = self.schedule(wait.deadline, lambda: self._timeout_wait(task, wait), P_SCHED,
                                             order=10_000, name="wait-timeout")
            return
        raise FbbNotModelled(f"park request {kind!r}")

    def _resume_delay(self, task):
        if task.done or task.park != "delay":
            return
        task.park = None
        self._log_event(("task", task.label, "resume"))
        self._advance_task(task)

    def _poll_wait(self, task, wait):
        if wait.done or task.park is not wait:
            return
        if wait.cond():
            self._release_wait(task, wait, timed_out=False)
            self._advance_task(task)
        else:
            wait.poll = self.schedule(self.now_ms + self.tick_ms, lambda: self._poll_wait(task, wait), P_LOOP,
                                      name="wait-poll")

    def _timeout_wait(self, task, wait):
        if wait.done or task.park is not wait:
            return
        self._release_wait(task, wait, timed_out=True)
        self._advance_task(task)

    def _release_wait(self, task, wait, timed_out):
        wait.done = True
        for ev in (wait.poll, wait.timeout):
            if ev is not None:
                ev.cancelled = True
        task.park = None
        task.timed_out = timed_out
        self._log_event(("task", task.label, "resume:timeout" if timed_out else "resume"))

    # ------------------------------------------------------------ action trees
    def _cond(self, body, local):
        cond = body.get("condition", body) if isinstance(body, dict) else body
        if not (isinstance(cond, dict) and set(cond) == {"lambda"}):
            raise FbbNotModelled(f"condition {cond!r}: only `lambda:` conditions are modelled")
        return cond["lambda"]

    def _eval_cond(self, code, local):
        return bool(self.run_lambda(code, local, params=tuple((local or {}).keys())))

    def _exec_params(self, body, local):
        params = {}
        for k, v in body.items():
            if k == "id":
                continue
            if isinstance(v, ds.LambdaStr):
                params[k] = ds.CStr(self.run_lambda(v, local, params=tuple((local or {}).keys())))
            else:
                params[k] = ds.CStr(v)
        return params

    def _gen_actions(self, actions, local):
        """The action interpreter as a generator: it yields a park request
        (("delay", ms) / ("wait", cond_callable, timeout_ms | None)) and is
        resumed by the engine when the park ends."""
        for action in actions or []:
            if not isinstance(action, dict) or len(action) != 1:
                raise FbbNotModelled(f"action {action!r}")
            (kind, body), = action.items()
            params = tuple((local or {}).keys())
            if kind == "lambda":
                self.run_lambda(body, local, params=params)
            elif kind == "if":
                code = self._cond(body, local)
                taken = self._eval_cond(code, local)
                yield from self._gen_actions(body.get("then" if taken else "else"), local)
            elif kind == "wait_until":
                code = self._cond(body, local)
                timeout = duration_ms(body["timeout"]) if isinstance(body, dict) and "timeout" in body else None
                if self._eval_cond(code, local):
                    continue
                yield ("wait", (lambda c=code, lo=local: self._eval_cond(c, lo)), timeout)
            elif kind == "delay":
                yield ("delay", duration_ms(body))
            elif kind == "script.execute":
                if isinstance(body, str):
                    self.start_script(body)
                else:
                    self.start_script(body["id"], self._exec_params(body, local))
            elif kind == "button.press":
                self.press_button(body["id"] if isinstance(body, dict) else body)
            elif kind == ds.READ:
                self._modbus_read(body, local)
            elif kind == ds.WRITE:
                self._modbus_write(body, local)
            elif kind == "logger.log":
                pass
            else:
                raise FbbNotModelled(f"action {kind!r} is not modelled by the FB-B engine")

    def _run_sync_actions(self, actions, local):
        """A Modbus handler's `then:` - ESPHome forbids delay / wait_until there."""
        g = self._gen_actions(actions, local)
        try:
            next(g)
        except StopIteration:
            return
        g.close()
        raise FbbNotModelled("a Modbus handler parked (delay / wait_until) - ESPHome forbids that in a handler")

    # -------------------------------------------------------------- entry points
    def start_script(self, script_id, params=None):
        """`script.execute`: run until the first park and return the Task (None if dropped by
        `mode: single`, exactly as ESPHome drops it)."""
        if script_id not in self.scripts:
            raise FbbNotModelled(f"script {script_id!r} does not exist")
        self.executed.append((script_id, dict(params or {})))
        sc = self.scripts[script_id]
        if sc.get("mode", "single") != "single":
            raise FbbNotModelled(f"script {script_id!r} mode {sc.get('mode')!r}: only `single` is modelled")
        missing = [p for p in (sc.get("parameters") or {}) if p not in (params or {})]
        if missing:
            raise FbbNotModelled(f"script {script_id!r}: parameter(s) {missing} not supplied")
        if script_id in self.running:
            return None
        self.running.add(script_id)
        task = self._new_task(script_id, sc["then"], dict(params or {}), script_id)
        self._script_task[script_id] = task
        self._log_event(("task", script_id, "start"))
        self._advance_task(task)
        return task

    def _button(self, button_id):
        for b in self.fw.get("button") or []:
            if b.get("id") == button_id:
                return b
        raise FbbNotModelled(f"button {button_id!r} does not exist")

    def press_button(self, button_id):
        """The button's on_press automation, run until its first park (it is not a script: no
        `is_running`, and two presses run side by side, as in ESPHome)."""
        b = self._button(button_id)
        on_press = b.get("on_press")
        actions = on_press.get("then") if isinstance(on_press, dict) else on_press
        if not actions:
            raise FbbNotModelled(f"button {button_id!r} has no on_press actions")
        task = self._new_task(None, actions, {}, f"button:{button_id}")
        self._log_event(("task", task.label, "start"))
        self._advance_task(task)
        return task

    # ------------------------------------------------------------------ api actions (FB-B2)
    def api_action(self, name):
        """The api `actions:` entry called `name` (exactly one), else FbbNotModelled."""
        acts = [a for a in ((self.fw.get("api") or {}).get("actions") or []) if isinstance(a, dict)]
        hits = [a for a in acts if a.get("action") == name]
        if len(hits) != 1:
            raise FbbNotModelled(f"{len(hits)} api actions are called {name!r} (the firmware has: "
                                 f"{[a.get('action') for a in acts]})")
        return hits[0]

    def call_api(self, api_name_, /, **variables):
        """Home Assistant calls the ESPHome action `api_name_` (esphome.<node>_<name>) with these variables: the action's
        `then:` runs on the engine until its first park and the Task is returned (an api action is not a script: no
        is_running(), and two calls run side by side). Every declared variable must be supplied and nothing else; a `string`
        arrives as an esphome::StringRef (`.str()` copies; `.c_str()` is NOT NUL-terminated - it reads on into `_tail`, the
        bytes behind the string in the receive buffer, default STRINGREF_TAIL), `bool` / `int` / `float` as the plain value."""
        tail = variables.pop("_tail", STRINGREF_TAIL)
        act = self.api_action(api_name_)
        decl = act.get("variables") or {}
        missing, extra = sorted(set(decl) - set(variables)), sorted(set(variables) - set(decl))
        if missing or extra:
            raise FbbNotModelled(f"api action {api_name_!r}: variables {missing} not supplied, {extra} not declared "
                                 f"(declared: {dict(decl)})")
        local = {}
        for k, ctype in decl.items():
            v = variables[k]
            if ctype == "string":
                if not isinstance(v, (str, StringRef)):
                    raise FbbNotModelled(f"api action {api_name_!r}: variable {k!r} is a string, got {type(v).__name__}")
                local[k] = v if isinstance(v, StringRef) else StringRef(v, tail)
            elif ctype == "bool":
                local[k] = bool(v)
            elif ctype == "int":
                local[k] = ds.wrap(int(v), "int32_t")
            elif ctype == "float":
                local[k] = float(v)
            else:
                raise FbbNotModelled(f"api action {api_name_!r}: variable type {ctype!r} is not modelled (string / bool / int / float)")
        task = self._new_task(None, act.get("then") or [], local, f"api:{api_name_}")
        self._log_event(("task", task.label, "start"))
        self._advance_task(task)
        return task

    def at_api(self, t_ms, api_name_, /, **variables):
        """call_api() at absolute virtual time `t_ms` (before the device's own loop work of that millisecond)."""
        return self.at(t_ms, lambda s: s.call_api(api_name_, **variables), name=f"api:{api_name_}")

    # ----------------------------------------------------------------- template switches (FB-B2)
    def _switch_write(self, name, state):
        """esphome::template_::TemplateSwitch::write_state() as reached by Switch::turn_on() / turn_off() / control(): the
        turn_on_action (or turn_off_action) automation runs EVERY time - also when the switch is already in that state -
        and, if the switch is `optimistic`, the state is then published (which deduplicates). Not modelled: stopping the
        previous trigger's still-running actions, the boot-time turn_on() / turn_off() of the restore mode."""
        cfg = self._switches.get(name)
        if cfg is None:
            raise FbbNotModelled(f"id({name}) is not a switch of this firmware")
        if cfg.get("inverted"):
            raise FbbNotModelled(f"switch {name!r}: `inverted: true` is not modelled")
        state = bool(state)
        self._log_event(("switch", name, "write", state))
        actions = _automation_actions(cfg.get("turn_on_action" if state else "turn_off_action"))
        if actions:
            task = self._new_task(None, actions, {}, f"switch:{name}:{'on' if state else 'off'}")
            self._advance_task(task)
        if cfg.get("optimistic"):
            self._switch_publish(name, state)

    def _switch_publish(self, name, state):
        """Switch::publish_state(): a repeat of the last published state is dropped (publish_dedup_); otherwise the state
        changes, is recorded in `published` and the state callbacks fire: on_state (variable `x`), on_turn_on / on_turn_off."""
        cfg = self._switches[name]
        ent = self.ent(name)
        state = bool(state)
        if ent._pub_dedup is not None and ent._pub_dedup == state:
            return
        ent._pub_dedup = state
        ent.state, ent._has = state, True
        ent.published.append(state)
        self._log_event(("switch", name, "state", state))
        for key, local in (("on_state", {"x": state}), ("on_turn_on" if state else "on_turn_off", {})):
            actions = _automation_actions(cfg.get(key))
            if actions:
                task = self._new_task(None, actions, local, f"switch:{name}:{key}")
                self._advance_task(task)

    def operator_switch(self, name, on):
        """Home Assistant `switch.turn_on` / `switch.turn_off` on an ESPHome switch: the API server calls
        Switch::control(on) from the main loop - the same path as a lambda's turn_on() / turn_off()."""
        if name not in self._switches:
            raise FbbNotModelled(f"id({name}) is not a switch of this firmware")
        self._log_event(("api", "switch", name, bool(on)))
        self._switch_write(name, bool(on))

    def at_operator_switch(self, t_ms, name, on):
        return self.at(t_ms, lambda s: s.operator_switch(name, on), name=f"switch:{name}")

    def operator_press(self, button_id):
        """Home Assistant presses a button entity (`button.press`): its on_press runs as a task, as in ESPHome."""
        return self.press_button(button_id)

    def _lambda_execute(self, script_id):
        """`id(script).execute();` from inside a lambda."""
        if self._ctx > 0:
            self.start_script(script_id)
        else:
            self.execute(script_id)

    def _lambda_press(self, button_id):
        task = self.press_button(button_id)
        if self._ctx == 0:
            self.run_until_done(task)

    # ---------------------------------------------------------------- intervals
    def _select_intervals(self, select):
        ivs = self.fw.get("interval") or []
        if select == "all":
            return list(range(len(ivs)))
        if isinstance(select, int):
            chosen = [select]
        elif isinstance(select, str):
            import yaml
            chosen = [i for i, iv in enumerate(ivs) if select in yaml.dump(iv["then"])]
        elif callable(select):
            chosen = [i for i, iv in enumerate(ivs) if select(i, iv)]
        else:
            chosen = [int(i) for i in select]
        if not chosen or any(not 0 <= i < len(ivs) for i in chosen):
            raise FbbNotModelled(f"no interval matches {select!r} (the firmware has {len(ivs)})")
        return sorted(chosen)

    def interval_index(self, marker: str) -> int:
        """The index of THE interval whose actions contain `marker` (exactly one, else raises)."""
        hits = self._select_intervals(marker)
        if len(hits) != 1:
            raise FbbNotModelled(f"{len(hits)} intervals contain {marker!r}")
        return hits[0]

    def start_intervals(self, select, *, phase=None, boot_ms=None, rearm="scheduled"):
        """Schedule the selected `interval:` entries. `select`: an index, an iterable of indexes,
        a substring of the interval's actions, a predicate(idx, interval) or "all".
        First firing = boot + startup_delay + phase; then every period (re-armed on the scheduled
        time; rearm="actual" re-arms from the firing time). `phase`: None/0, an int (ms), a dict
        idx -> ms, or "random" ([0, min(period/2, 5000)) from the scheduler RNG - ESPHome's
        initial offset). Returns the started indexes."""
        ivs = self.fw.get("interval") or []
        if rearm not in ("scheduled", "actual"):
            raise FbbNotModelled(f"rearm {rearm!r}")
        boot = self.now_ms if boot_ms is None else int(boot_ms)
        started = []
        for idx in self._select_intervals(select):
            if idx in self._intervals:
                raise FbbNotModelled(f"interval {idx} is already running")
            iv = ivs[idx]
            period = duration_ms(iv["interval"])
            if period <= 0:
                raise FbbNotModelled(f"interval {idx}: period {period}")
            if phase == "random":
                ph = self.sched_rng.randrange(0, max(1, min(period // 2, 5000)))
            elif isinstance(phase, dict):
                ph = int(phase.get(idx, 0))
            else:
                ph = int(phase or 0)
            first = boot + duration_ms(iv.get("startup_delay", 0)) + ph
            st = _IntervalState(idx, period, first, rearm)
            self._intervals[idx] = st
            st.ev = self.schedule(first, lambda st=st: self._fire_interval(st), P_SCHED, order=idx, name=f"interval{idx}",
                                  recurring=True)
            started.append(idx)
        return started

    def stop_intervals(self, select=None):
        for idx in list(self._intervals if select is None else self._select_intervals(select)):
            st = self._intervals.pop(idx, None)
            if st is not None and st.ev is not None:
                st.ev.cancelled = True

    def _fire_interval(self, st):
        iv = (self.fw.get("interval") or [])[st.idx]
        self.interval_log.append((self.now_ms, st.idx))
        st.fired += 1
        st.next = (st.next + st.period) if st.rearm == "scheduled" else (self.now_ms + st.period)
        st.ev = self.schedule(st.next, lambda: self._fire_interval(st), P_SCHED, order=st.idx, name=f"interval{st.idx}",
                              recurring=True)
        task = self._new_task(None, iv["then"], {}, f"interval[{st.idx}]")
        self._advance_task(task)

    # ------------------------------------------------------------ injected events
    def at(self, t_ms, fn, *, name="", prio=P_EXTERNAL):
        """Run `fn(sim)` at absolute virtual time `t_ms` (before the device's own loop work of
        that millisecond unless prio says otherwise)."""
        return self.schedule(t_ms, lambda: fn(self), prio=prio, name=name or "at")

    def after(self, d_ms, fn, **kw):
        return self.at(self.now_ms + int(d_ms), fn, **kw)

    def at_press(self, t_ms, button_id):
        return self.at(t_ms, lambda s: s.press_button(button_id), name=f"press:{button_id}")

    def at_bank(self, t_ms, updates: dict):
        """Mutate the inverter register bank (another master / the LCD / the cloud) at `t_ms`."""
        return self.at(t_ms, lambda s: s.bank.update({int(k): int(v) for k, v in updates.items()}), name="bank")

    def at_power_cut(self, t_ms, message="power cut"):
        def cut(sim):
            raise PowerCut(f"{message} at t={sim.now_ms}")
        return self.at(t_ms, cut, name="power-cut")

    def power_cut_when(self, predicate, message="power cut"):
        """Raise PowerCut from the first sim event (sim.events entry) that satisfies predicate(event)."""
        prev = self.event_hook

        def hook(event):
            if prev is not None:
                prev(event)
            if predicate(event):
                raise PowerCut(f"{message} at event {event!r}")
        self.event_hook = hook

    def at_foreign_frame(self, t_ms, addr, count, *, latency_ms=120, outcome="ok", values=None, on_deliver=None):
        """A frame that is NOT part of the firmware under test (the config poll, an RTC read, a
        second master) goes on the wire at `t_ms` (queued behind whatever is there)."""
        return self.at(t_ms, lambda s: s.inject_foreign_frame(addr, count, latency_ms=latency_ms, outcome=outcome,
                                                              values=values, on_deliver=on_deliver), name="foreign-frame")

    def inject_foreign_frame(self, addr, count, *, latency_ms=120, outcome="ok", values=None, on_deliver=None):
        spec = self._spec(FrameSpec(outcome=outcome, latency_ms=latency_ms, values=values))
        frame = Frame("foreign", int(addr), int(count), spec, on_deliver=on_deliver)
        self._hub_submit(frame)
        return frame

    def hold_bus(self, duration_ms_, at=None):
        """The bus is busy (tx_blocked) for `duration_ms_` from `at` (default now), opaque to the firmware."""
        def go(sim):
            sim.hub.in_flight_until = max(sim.hub.in_flight_until or 0, sim.now_ms + int(duration_ms_))
            sim._hub_kick()
        return self.at(self.now_ms if at is None else at, go, name="hold-bus")

    def hold_script_running(self, script_id, duration_ms_, at=None):
        """`id(script).is_running()` is true for `duration_ms_` from `at` (a foreign script, e.g. the
        configuration poll, that this test does not execute)."""
        if script_id not in self.scripts:
            raise FbbNotModelled(f"script {script_id!r} does not exist")
        t0 = self.now_ms if at is None else int(at)

        def start(sim):
            sim.running.add(script_id)
            sim.schedule(sim.now_ms + int(duration_ms_), lambda: sim.running.discard(script_id), P_SCHED, name="release")
        return self.at(t0, start, name=f"hold:{script_id}")

    # -------------------------------------------------------------------- modbus
    def set_modbus_mode(self, mode, latency_ms=None):
        if mode not in ("immediate", "deferred"):
            raise FbbNotModelled(f"modbus mode {mode!r}")
        self.modbus_mode = mode
        if latency_ms is not None:
            self.frame_latency_ms = int(latency_ms)

    def queue_frames(self, *specs):
        """Outcomes for the next firmware reads, consumed one per read in call order (a str, a dict or
        a FrameSpec); once exhausted `outcome_fn(kind, addr, count)` decides."""
        self.frame_script.extend(specs)

    def _spec(self, r):
        if isinstance(r, FrameSpec):
            spec = copy.copy(r)
        elif isinstance(r, str):
            spec = FrameSpec(outcome=r)
        elif isinstance(r, dict):
            try:
                spec = FrameSpec(**r)
            except TypeError as e:
                raise FbbNotModelled(f"frame spec {r!r}: {e}") from e
        else:
            raise FbbNotModelled(f"frame outcome {r!r}")
        if spec.outcome not in FRAME_OUTCOMES:
            raise FbbNotModelled(f"frame outcome {spec.outcome!r} (modelled: {', '.join(FRAME_OUTCOMES)})")
        return spec

    def _next_spec(self, kind, addr, count):
        if self.frame_script:
            r = self.frame_script.pop(0)
            if callable(r):
                r = r(addr, count)
            return self._spec(r)
        return self._spec(self.outcome_fn(kind, addr, count))

    def _modbus_read(self, body, local):
        addr, count = int(body["start_address"]), int(body["count"])
        spec = self._next_spec("read", addr, count)
        if self.modbus_mode == "immediate" or spec.outcome == "not_sent":
            # synchronous delivery (the older behaviour); not_sent never reaches the wire
            self._immediate_read(body, local, addr, count, spec)
            return
        frame = Frame("fw", addr, count, spec, body=body, local=dict(local or {}))
        frame.wire.issuer = self._cur_task.label if self._cur_task is not None else None
        self._hub_submit(frame)

    def _snapshot(self, addr, count, spec):
        """What the inverter's registers hold when the frame goes on the wire (`count` words, as logged)."""
        values = [self.bank.get(addr + i, 0) for i in range(count)]
        if self.read_override_fn:
            values = self.read_override_fn(addr, count, values)
        return values

    @staticmethod
    def _reply_values(spec, snapshot):
        """What the on_response handler receives: the snapshot, unless the frame spec overrides it (a short reply)."""
        return list(spec.values) if spec.values is not None else snapshot

    def _immediate_read(self, body, local, addr, count, spec):
        values = self._snapshot(addr, count, spec)
        w = Wire("fw", "read", addr, count, spec.outcome, t_queued=self.now_ms, t_start=self.now_ms, t_end=self.now_ms,
                 values=list(values), issuer=self._cur_task.label if self._cur_task is not None else None)
        if spec.outcome != "not_sent":
            self.wire_log.append(w)
        self.modbus_log.append(("read", addr, list(values), spec.outcome))
        self._log_event(("read", addr, count, spec.outcome))
        handler = _HANDLER_OF.get(spec.outcome)
        self._handler(body, handler, local, self._reply_values(spec, values) if handler == "on_response" else None,
                      exception_code=(spec.exception_code if spec.exception_code is not None else self.exception_code)
                      if handler == "on_error" else None)

    def _modbus_write(self, body, local):
        """Writes are always delivered immediately (FB-B1 has none: any write is logged in
        modbus_log / wire_log so the safety assertions see it)."""
        saved = self.outcome_fn

        def norm(kind, addr, count):
            if kind == "write" and self.frame_script:
                r = self.frame_script.pop(0)
            else:
                r = saved(kind, addr, count)
            return r.outcome if isinstance(r, FrameSpec) else (r.get("outcome", "ok") if isinstance(r, dict) else r)
        self.outcome_fn = norm
        n = len(self.modbus_log)
        try:
            ds.Sim._modbus_write(self, body, local)
        finally:
            self.outcome_fn = saved
        for e in self.modbus_log[n:]:
            self.wire_log.append(Wire("fw", "write", e[1], len(e[2]), e[3], self.now_ms, self.now_ms, self.now_ms,
                                      list(e[2]), self._cur_task.label if self._cur_task is not None else None))

    # -- the hub: a FIFO of frames, one in flight --------------------------------
    def _hub_submit(self, frame):
        frame.wire.t_queued = self.now_ms
        self.hub.frames.append(frame)
        self._hub_kick()

    def _hub_kick(self):
        if self._hub_kick_pending:
            return
        self._hub_kick_pending = True
        self.schedule(self.now_ms, self._hub_loop, P_LOOP, name="hub")

    def _hub_loop(self):
        self._hub_kick_pending = False
        hub = self.hub
        if hub.in_flight_frame is not None or not hub.frames:
            return
        free_at = max(hub.in_flight_until or 0, hub.turnaround_until or 0)
        if self.now_ms < free_at:
            self._hub_kick_pending = True
            self.schedule(free_at, self._hub_loop, P_LOOP, name="hub")
            return
        frame = hub.frames.pop(0)
        hub.in_flight_frame = frame
        w = frame.wire
        w.t_start = self.now_ms
        frame.values = self._snapshot(frame.addr, frame.count, frame.spec)
        w.values = list(frame.values)
        self.wire_log.append(w)
        if frame.origin == "fw":
            self.modbus_log.append(("read", frame.addr, list(frame.values), frame.spec.outcome))
            self._log_event(("read", frame.addr, frame.count, frame.spec.outcome))
        else:
            self._log_event(("frame_start", frame.origin, frame.addr, frame.count, frame.spec.outcome))
        latency = frame.spec.latency_ms if frame.spec.latency_ms is not None else self.frame_latency_ms
        self.schedule(self.now_ms + int(latency), lambda: self._hub_complete(frame), P_LOOP, name="frame-reply")

    def _hub_complete(self, frame):
        hub = self.hub
        hub.in_flight_frame = None
        hub.turnaround_until = (self.now_ms + hub.turnaround_ms) if hub.turnaround_ms else None
        frame.wire.t_end = self.now_ms
        self._log_event(("deliver", frame.origin, frame.addr, frame.count, frame.spec.outcome))
        if frame.on_deliver is not None:
            frame.on_deliver(self, frame)
        if frame.origin == "fw":
            handler = _HANDLER_OF.get(frame.spec.outcome)
            self._handler(frame.body, handler, frame.local,
                          self._reply_values(frame.spec, frame.values) if handler == "on_response" else None,
                          exception_code=(frame.spec.exception_code if frame.spec.exception_code is not None
                                          else self.exception_code) if handler == "on_error" else None)
        self._hub_kick()

    def _handler(self, body, name, local, values=None, exception_code=None):
        """A Modbus outcome handler: the `then:` list runs atomically in the component loop, with
        `values` (a vector) and `exception_code` in scope."""
        if name is None or name not in body:
            return
        loc = dict(local or {})
        if values is not None:
            loc["values"] = ds.Vec(values)
        if exception_code is not None:
            loc["exception_code"] = int(exception_code)
        self._ctx += 1
        try:
            self._run_sync_actions(body[name]["then"], loc)
        finally:
            self._ctx -= 1

    # ------------------------------------------------------------------- safety
    def mark(self) -> Mark:
        return Mark(len(self.modbus_log), len(self.wire_log), len(self.nvs_direct.ops), len(self.nvs_commits),
                    len(self.nvs_loads), len(self.executed), len(self.events),
                    {k: _rec_key(v) for k, v in self.nvs.items()}, len(self.nvs_direct.sets))

    def since(self, m: Mark) -> Since:
        return Since(self, m)

    def snapshot_state(self) -> dict:
        """Every global (arrays / records / strings frozen to comparable values) and how many times each
        entity was published - the evidence for "this refusal touched NOTHING" / "only these globals moved"."""
        return {"g": {k: _freeze(v) for k, v in self.g.items()},
                "pub": {k: len(e.published) for k, e in self.entities.items()}}

    def state_diff(self, snap: dict, ignore=()) -> dict:
        """{"globals": [names that changed], "published": {entity: [values published since]}}."""
        # FB-B3 Slice A: the Live Match tick's own RAM-only bookkeeping (the four fence scalars and the B10 text) is not part of
        # the FB-B1 / FB-B2 flows' evidence; it is proven by test_fallback_live_match.py. Every other global / entity still counts.
        ignore = tuple(ignore) + FBB3_OWN_GLOBALS
        changed = sorted(k for k, v in self.g.items() if k not in ignore and _freeze(v) != snap["g"].get(k))
        pub = {k: [str(x) for x in e.published[snap["pub"].get(k, 0):]] for k, e in self.entities.items()
               if len(e.published) > snap["pub"].get(k, 0) and k != FBB3_OWN_ENTITY}
        return {"globals": changed, "published": pub}
