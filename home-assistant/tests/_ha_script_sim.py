"""A small, deterministic, FAIL-LOUD interpreter for the Home Assistant script / automation subset used by the
scheduled Free Power package (FPS1), plus a model of the dongle's Free Power start gate and its Modbus poll.

It exists so the offline suite can run the REAL package YAML against a virtual clock. Anything outside the
supported subset raises Unsupported instead of being guessed. Semantics follow Home Assistant 2026.9:
  - script / automation `variables` render to native types, in order; script fields are variables;
  - `choose` (first matching branch, else default), `if` / `then` / `else`, `repeat` (`sequence` + `until`,
    `repeat.index` from 1), `delay` (HH:MM:SS or {seconds: template}), `wait_template` (timeout,
    continue_on_timeout), service calls with `target.entity_id` and `data`;
  - conditions: state, template, or, and, not, trigger (id); a list of conditions is AND;
  - calling `script.<name>` as an action waits for it; a `mode: single` script that is already running is not
    started again (HA logs a warning and continues);
  - automation triggers: time (`at: input_datetime.x`, fires once at a date+time helper's instant), event (fired
    only through HA.fire_event), template
    (fires on a false -> true change; re-rendered on every state change and at every minute boundary, as HA does
    for now() templates), homeassistant start; automation `mode: single` drops a trigger while running;
  - the state machine records only changes (an identical value is not a new state), and a template sensor is
    rendered on read.
Times are epoch seconds; the local zone is fixed at UTC+1 (BST), which is what the incident used.
"""
from __future__ import annotations

import ast
import heapq
import itertools
import math
from datetime import datetime, timedelta, timezone

import jinja2
import jinja2.sandbox

LOCAL = timezone(timedelta(hours=1))


class Unsupported(Exception):
    pass


class SimError(Exception):
    pass


class ServiceError(Exception):
    """A service call that raises in Home Assistant (e.g. an ESPHome API reconnect race)."""


class StopRun(Exception):
    """A `stop` action, or a failing action-level `condition`: the whole script / automation run ends (not an error)."""


def local_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, LOCAL).strftime("%Y-%m-%d %H:%M:%S")


def parse_local(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL).timestamp()


_MISSING = object()


def _num(value, default, conv):
    try:
        if isinstance(value, bool):
            return conv(int(value))
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError
            return conv(value)
        return conv(float(str(value).strip()))
    except (TypeError, ValueError):
        if default is _MISSING:
            raise SimError(f"template could not convert {value!r} and no default was given")
        return default


def _native(text: str):
    """Home Assistant's result parsing for native-type rendering."""
    s = text.strip()
    if s in ("True", "False"):
        return s == "True"
    try:
        v = ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return s
    if isinstance(v, (int, float, list, dict, bool)) and not (isinstance(v, str)):
        return v
    return s


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "on", "yes", "1", "enable")
    return bool(value)


class _StateObj:
    """What `states.domain.object` returns in a template: the state and its last_changed (aware datetime)."""

    def __init__(self, state: str, last_changed: float):
        self.state = state
        self.last_changed = datetime.fromtimestamp(last_changed, LOCAL)


class _States:
    """`states('x')`, and `states.domain.object` (None when the entity does not exist), as in Home Assistant."""

    def __init__(self, world: "World"):
        self._w = world

    def __call__(self, entity_id: str) -> str:
        return self._w.state(entity_id)

    def __getattr__(self, domain: str):
        w = self._w
        if domain.startswith("_") or not any(e.startswith(domain + ".") for e in w.states):
            raise AttributeError(domain)        # also answers the sandbox's unsafe_callable / alters_data probes

        class _Domain:
            def __getattr__(self, obj: str):
                eid = f"{domain}.{obj}"
                if eid not in w.states:
                    return None
                return _StateObj(w.states[eid][0], w.changed_at.get(eid, 0.0))
        return _Domain()


class World:
    """The virtual clock, the state machine, the event queue and the Jinja environment."""

    def __init__(self, t0: float):
        self.t = t0
        self.states: dict[str, tuple[str, dict]] = {}
        self.history: list[tuple[float, str, str]] = []
        self.template_entities: dict[str, str] = {}
        self._q: list = []
        self._seq = itertools.count()
        self.waiters: list = []           # (predicate, resume) pairs for wait_template
        self.listeners: list = []         # called after any state change
        self.service_handlers: dict = {}  # "domain.service" -> callable(entity_id, data)
        self.text_max: dict[str, int] = {}         # input_text entity -> max length (HA keeps the old value if longer)
        self.fail_services: dict[str, int] = {}     # test hook: "domain.service" -> number of calls that raise
        self.notifications: dict[str, dict] = {}
        self.notification_log: list[tuple[float, str, str, str]] = []
        self.service_log: list[tuple[float, str, str, dict]] = []
        self.warnings: list[str] = []
        env = jinja2.sandbox.ImmutableSandboxedEnvironment(undefined=jinja2.StrictUndefined,
                                                           extensions=["jinja2.ext.loopcontrols"])
        self.changed_at: dict[str, float] = {}
        env.globals.update(states=_States(self), is_state=self.is_state, state_attr=self.state_attr,
                           now=self.now, as_timestamp=self.as_timestamp, namespace=jinja2.utils.Namespace)
        env.filters.update({
            "int": lambda v, d=_MISSING: _num(v, d, lambda x: int(float(x))),
            "float": lambda v, d=_MISSING: _num(v, d, float),
            "timestamp_custom": lambda v, fmt="%Y-%m-%d %H:%M:%S", local=True: datetime.fromtimestamp(
                float(v), LOCAL if local else timezone.utc).strftime(fmt),
            "round": self._round,
        })
        self.env = env
        self._cache: dict[str, jinja2.Template] = {}

    # --- clock and events -------------------------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.fromtimestamp(self.t, LOCAL)

    def at(self, when: float, fn) -> None:
        heapq.heappush(self._q, (when, next(self._seq), fn))

    def after(self, dt: float, fn) -> None:
        self.at(self.t + dt, fn)

    def run_until(self, end: float) -> None:
        minute = math.floor(self.t / 60) * 60 + 60
        while True:
            nxt = self._q[0][0] if self._q else math.inf
            if minute <= nxt and minute <= end:
                self.t = minute
                minute += 60
                self._minute_tick()
                continue
            if nxt > end:
                break
            when, _, fn = heapq.heappop(self._q)
            self.t = max(self.t, when)
            fn()
        self.t = max(self.t, end)

    def _minute_tick(self):
        for fn in list(self.listeners):
            fn("minute")

    # --- state machine ---------------------------------------------------------------------------------------
    def set(self, entity_id: str, state, attrs: dict | None = None) -> None:
        state = str(state)
        old = self.states.get(entity_id)
        if old is not None and old[0] == state and (attrs is None or attrs == old[1]):
            return
        self.states[entity_id] = (state, dict(attrs or (old[1] if old else {})))
        if old is None or old[0] != state:
            self.changed_at[entity_id] = self.t
        self.history.append((self.t, entity_id, state))
        self._changed()

    def _changed(self):
        for pred, resume in list(self.waiters):
            if (pred, resume) in self.waiters and pred():
                self.waiters.remove((pred, resume))
                resume(True)
        for fn in list(self.listeners):
            fn("state")

    def state(self, entity_id: str) -> str:
        if entity_id in self.template_entities:
            return self.render(self.template_entities[entity_id]).strip()
        return self.states.get(entity_id, ("unknown", {}))[0]

    def _states_fn(self, entity_id: str) -> str:
        return self.state(entity_id)

    def is_state(self, entity_id: str, value) -> bool:
        vals = value if isinstance(value, list) else [value]
        return self.state(entity_id) in [str(v) for v in vals]

    def state_attr(self, entity_id: str, attr: str):
        return self.states.get(entity_id, ("unknown", {}))[1].get(attr)

    def as_timestamp(self, value, default=_MISSING):
        try:
            if isinstance(value, datetime):
                return value.timestamp()
            if isinstance(value, (int, float)):
                return float(value)
            return parse_local(str(value))
        except (TypeError, ValueError):
            if default is _MISSING:
                raise SimError(f"as_timestamp could not parse {value!r} and no default was given")
            return default

    @staticmethod
    def _round(value, precision=0, method="common", default=_MISSING):
        try:
            v = float(value)
        except (TypeError, ValueError):
            if default is _MISSING:
                raise SimError(f"round could not convert {value!r}")
            return default
        m = 10 ** precision
        if method == "floor":
            r = math.floor(v * m) / m
        elif method == "ceil":
            r = math.ceil(v * m) / m
        elif method == "common":
            r = round(v, precision)
        else:
            raise Unsupported(f"round method {method}")
        return int(r) if precision == 0 else r

    # --- templates ------------------------------------------------------------------------------------------
    def render(self, template, variables: dict | None = None) -> str:
        if not isinstance(template, str):
            return str(template)
        if template not in self._cache:
            self._cache[template] = self.env.from_string(template)
        return self._cache[template].render(**(variables or {}))

    def render_native(self, template, variables: dict | None = None):
        if not isinstance(template, str):
            return template
        if "{{" not in template and "{%" not in template:
            return template
        return _native(self.render(template, variables))

    # --- services -------------------------------------------------------------------------------------------
    def call(self, service: str, entity_ids: list[str], data: dict) -> None:
        self.service_log.append((self.t, service, ",".join(entity_ids), dict(data)))
        if service == "persistent_notification.create":
            nid = str(data.get("notification_id", "default"))
            self.notifications[nid] = {"title": data.get("title", ""), "message": data.get("message", "")}
            self.notification_log.append((self.t, "create", nid, str(data.get("title", ""))))
            return
        if service == "persistent_notification.dismiss":
            nid = str(data.get("notification_id", "default"))
            if self.notifications.pop(nid, None) is not None:
                self.notification_log.append((self.t, "dismiss", nid, ""))
            return
        if self.fail_services.get(service, 0) > 0:
            self.fail_services[service] -= 1
            raise ServiceError(service)
        handler = self.service_handlers.get(service)
        if handler is None:
            domain, _, svc = service.partition(".")
            if domain in ("input_text",) and svc == "set_value":
                def handler(e, d):
                    v = str(d["value"])
                    if len(v) > self.text_max.get(e, 255):
                        self.warnings.append(f"{self.t:.3f} input_text {e}: invalid value of length {len(v)} (kept old)")
                        return
                    self.set(e, v)
            elif domain == "input_boolean" and svc in ("turn_on", "turn_off"):
                handler = lambda e, d, s=svc: self.set(e, "on" if s == "turn_on" else "off")  # noqa: E731
            elif domain == "input_number" and svc == "set_value":
                handler = lambda e, d: self.set(e, f"{float(d['value'])}")  # noqa: E731
            elif domain == "input_datetime" and svc == "set_datetime":
                def handler(e, d):
                    hh, mm, ss = (int(x) for x in str(d["time"]).split(":"))
                    self.set(e, f"{hh:02d}:{mm:02d}:{ss:02d}", {"hour": hh, "minute": mm, "second": ss})
            else:
                raise Unsupported(f"service {service}")
        for e in entity_ids:
            handler(e, data)


class Script:
    """One script (or an automation's action list), run as a generator under the World's clock."""

    def __init__(self, ha: "HA", name: str, cfg: dict):
        self.ha, self.name, self.cfg = ha, name, cfg
        self.mode = cfg.get("mode", "single")
        if self.mode != "single":
            raise Unsupported(f"script mode {self.mode}")
        self.running = False


class HA:
    """Scripts, automations and template sensors loaded from one package."""

    def __init__(self, world: World, package):
        self.w = world
        if isinstance(package, list):
            merged: dict = {}
            for pk in package:
                for k, v in pk.items():
                    if isinstance(v, list):
                        merged.setdefault(k, []).extend(v)
                    else:
                        merged.setdefault(k, {}).update(v)
            package = merged
        allowed = {"input_boolean", "input_datetime", "input_number", "input_text", "script", "automation", "template"}
        unknown = set(package) - allowed
        if unknown:
            raise Unsupported(f"package keys {unknown}")
        self.scripts = {k: Script(self, k, v) for k, v in (package.get("script") or {}).items()}
        for k in self.scripts:                      # an idle script entity reads "off" in Home Assistant
            if world.states.get(f"script.{k}", ("off",))[0] != "on":
                world.set(f"script.{k}", "off")
        for k, v in (package.get("input_text") or {}).items():
            world.text_max[f"input_text.{k}"] = int(v.get("max", 100))
        self._init_helpers(package)
        self.automations = []
        for a in package.get("automation") or []:
            self.automations.append(_Automation(self, a))
        for block in package.get("template") or []:
            for kind, items in block.items():
                if kind != "sensor":
                    raise Unsupported(f"template {kind}")
                for it in items:
                    eid = "sensor." + it["name"].lower().replace(" ", "_")
                    world.template_entities[eid] = it["state"]
        world.listeners.append(self._on_event)
        self.runs: list[tuple[float, str]] = []
        self.dead = False

    def _init_helpers(self, package):
        """Helper entities start at their `initial` (or the HA default) unless a state already exists (restored)."""
        w = self.w
        for k, v in (package.get("input_number") or {}).items():
            e = f"input_number.{k}"
            if e not in w.states:
                w.set(e, f"{float(v.get('initial', v.get('min', 0)))}")
        for k, v in (package.get("input_text") or {}).items():
            e = f"input_text.{k}"
            if e not in w.states:
                w.set(e, str(v.get("initial", "")))
        for k, v in (package.get("input_boolean") or {}).items():
            e = f"input_boolean.{k}"
            if e not in w.states:
                w.set(e, "on" if v.get("initial") else "off")
        for k, v in (package.get("input_datetime") or {}).items():
            e = f"input_datetime.{k}"
            if e in w.states:
                continue
            if v.get("has_date"):
                continue                                  # date+time helpers are set by the tests
            hh, mm, ss = (int(x) for x in str(v.get("initial", "00:00:00")).split(":"))
            w.set(e, f"{hh:02d}:{mm:02d}:{ss:02d}", {"hour": hh, "minute": mm, "second": ss})

    def stop(self):
        """Home Assistant goes down: no trigger, timer or script step of this instance runs again."""
        self.dead = True
        for a in self.automations:
            a.ready = False
        if self._on_event in self.w.listeners:
            self.w.listeners.remove(self._on_event)
        for name, sc in self.scripts.items():
            if sc.running:
                sc.running = False
                self.w.set(f"script.{name}", "off")

    # --- running ---------------------------------------------------------------------------------------------
    def start_script(self, name: str, variables: dict, on_done=None) -> bool:
        sc = self.scripts[name]
        if sc.running:
            self.w.warnings.append(f"{self.w.t:.3f} script.{name} already running")
            if on_done:
                on_done()
            return False
        sc.running = True
        self.w.set(f"script.{name}", "on")
        self.runs.append((self.w.t, name))
        variables = dict(variables)
        variables.setdefault("this", {})

        def done(err=None):
            sc.running = False
            self.w.set(f"script.{name}", "off")
            if on_done:
                on_done(err) if err is not None else on_done()

        self._drive(self._seq(sc.cfg["sequence"], variables, script_vars=sc.cfg.get("variables")), done)
        return True

    def _drive(self, gen, done):
        """Step a generator: it yields ('delay', s) / ('wait', pred, timeout) / ('call', name, vars)."""
        def step(value=None, error=None):
            if self.dead:
                return
            try:
                req = gen.throw(error) if error is not None else gen.send(value)
            except (StopIteration, StopRun):
                done()
                return
            except ServiceError as exc:
                self.w.warnings.append(f"{self.w.t:.3f} run aborted by a service error: {exc}")
                done(exc)
                return
            kind = req[0]
            if kind == "delay":
                self.w.after(req[1], lambda: step(None))
            elif kind == "wait":
                pred, timeout = req[1], req[2]
                if pred():
                    self.w.after(0, lambda: step(True))
                    return
                state = {"done": False}

                def resume(ok):
                    if state["done"]:
                        return
                    state["done"] = True
                    self.w.after(0, lambda: step(ok))

                entry = (pred, resume)
                self.w.waiters.append(entry)

                def on_timeout():
                    if entry in self.w.waiters:
                        self.w.waiters.remove(entry)
                    resume(False)

                self.w.after(timeout, on_timeout)
            elif kind == "call":
                def child_done(err=None, coe=req[3]):
                    if err is not None and not coe:
                        self.w.after(0, lambda: step(None, err))
                    else:
                        self.w.after(0, lambda: step(None))
                self.start_script(req[1], req[2], on_done=child_done)
            else:
                raise Unsupported(f"yield {kind}")
        self.w.after(0, step)

    # --- sequence interpreter ---------------------------------------------------------------------------------
    def _render_vars(self, spec: dict, variables: dict) -> dict:
        out = dict(variables)
        for k, v in spec.items():
            out[k] = self.w.render_native(v, out) if isinstance(v, str) else v
        return out

    def _seq(self, actions, variables, script_vars=None):
        if script_vars:
            variables = self._render_vars(script_vars, variables)
        for act in actions:
            variables = yield from self._action(act, variables)

    def _action(self, act: dict, v: dict):
        keys = set(act) - {"alias", "enabled", "continue_on_error"}
        if "condition" in keys:
            if not self.cond([act], v):
                raise StopRun("condition")
            return v
        if "stop" in keys:
            raise StopRun(str(act["stop"]))
        if "variables" in keys:
            return self._render_vars(act["variables"], v)
        if "choose" in keys:
            for br in act["choose"]:
                if self.cond(br["conditions"], v):
                    yield from self._seq(br["sequence"], dict(v))
                    return v
            if "default" in act:
                yield from self._seq(act["default"], dict(v))
            return v
        if "if" in keys:
            if self.cond(act["if"], v):
                yield from self._seq(act["then"], dict(v))
            elif "else" in act:
                yield from self._seq(act["else"], dict(v))
            return v
        if "repeat" in keys:
            r = act["repeat"]
            if set(r) == {"for_each", "sequence"}:
                items = r["for_each"]
                if isinstance(items, str):
                    items = self.w.render_native(items, v)
                for i, item in enumerate(items, 1):
                    yield from self._seq(r["sequence"], dict(v, repeat={"index": i, "first": i == 1, "item": item}))
                return v
            if set(r) - {"sequence", "until"}:
                raise Unsupported(f"repeat form {set(r)}")
            index = 0
            while True:
                index += 1
                iv = dict(v, repeat={"index": index, "first": index == 1})
                yield from self._seq(r["sequence"], dict(iv))
                if self.cond(r["until"], iv):
                    return v
        if "delay" in keys:
            d = act["delay"]
            if isinstance(d, str):
                h, m, s = (float(x) for x in self.w.render(d, v).split(":"))
                secs = h * 3600 + m * 60 + s
            elif isinstance(d, dict) and set(d) == {"seconds"}:
                secs = float(self.w.render_native(d["seconds"], v))
            else:
                raise Unsupported(f"delay form {d!r}")
            yield ("delay", secs)
            return v
        if "wait_template" in keys:
            tpl = act["wait_template"]
            h, m, s = (float(x) for x in str(act.get("timeout", "00:00:00")).split(":"))
            timeout = h * 3600 + m * 60 + s
            if not act.get("continue_on_timeout", True) or timeout <= 0:
                raise Unsupported("wait_template without a timeout that continues")
            ok = yield ("wait", lambda: _truthy(self.w.render_native(tpl, v)), timeout)
            return dict(v, wait={"completed": bool(ok)})
        if "action" in keys:
            service = act["action"]
            data = {k: self.w.render_native(val, v) if isinstance(val, str) else val
                    for k, val in (act.get("data") or {}).items()}
            if service.startswith("script."):
                yield ("call", service.split(".", 1)[1], data, bool(act.get("continue_on_error")))
                return v
            target = (act.get("target") or {}).get("entity_id", [])
            ents = target if isinstance(target, list) else [target]
            ents = [str(self.w.render_native(x, v)) if isinstance(x, str) and "{{" in x else x for x in ents]
            try:
                self.w.call(service, ents, data)
            except ServiceError:
                if not act.get("continue_on_error"):
                    raise
                self.w.warnings.append(f"{self.w.t:.3f} {service} raised (continue_on_error)")
            return v
        raise Unsupported(f"action {sorted(keys)}")

    # --- conditions -------------------------------------------------------------------------------------------
    def cond(self, conds, v) -> bool:
        if isinstance(conds, dict):
            conds = [conds]
        for c in conds:
            kind = c.get("condition")
            if kind == "state":
                want = c["state"] if isinstance(c["state"], list) else [c["state"]]
                if self.w.state(c["entity_id"]) not in [str(x) for x in want]:
                    return False
            elif kind == "template":
                if not _truthy(self.w.render_native(c["value_template"], v)):
                    return False
            elif kind == "or":
                if not any(self.cond(x, v) for x in c["conditions"]):
                    return False
            elif kind == "and":
                if not all(self.cond(x, v) for x in c["conditions"]):
                    return False
            elif kind == "not":
                if any(self.cond(x, v) for x in c["conditions"]):
                    return False
            elif kind == "trigger":
                ids = c["id"] if isinstance(c["id"], list) else [c["id"]]
                if (v.get("trigger") or {}).get("id") not in ids:
                    return False
            else:
                raise Unsupported(f"condition {kind}")
        return True

    # --- automation triggers ----------------------------------------------------------------------------------
    def _on_event(self, kind):
        for a in self.automations:
            a.poll(kind)

    def fire_event(self, event_type: str):
        """An event on the bus (smr1: `automation_reloaded`): fire the event triggers that match its type."""
        for a in self.automations:
            for i, tr in enumerate(a.triggers):
                if a.ready and tr["trigger"] == "event" and tr.get("event_type") == event_type:
                    a.fire({"id": tr.get("id", str(i)), "platform": "event", "event": {"event_type": event_type}})

    def start(self):
        """homeassistant start: arm the automations' trigger state, fire start triggers."""
        for a in self.automations:
            a.setup()
        for a in self.automations:
            a.ha_start()


class _Automation:
    def __init__(self, ha: HA, cfg: dict):
        self.ha, self.cfg = ha, cfg
        self.id = cfg["id"]
        self.mode = cfg.get("mode", "single")
        if self.mode not in ("single", "restart", "queued"):
            raise Unsupported(f"automation mode {self.mode}")
        self.queue: list = []
        self.running = False
        self.triggers = cfg["triggers"]
        self._tpl_last: dict[int, bool] = {}
        self._time_fired: set = set()
        self.disabled_triggers: set = set()   # test hook: ids of triggers that are lost
        self.fired: list[tuple[float, str]] = []
        self._gen = 0
        self.ready = False

    def setup(self):
        self.ready = True
        for i, tr in enumerate(self.triggers):
            kind = tr["trigger"]
            if kind == "template":
                self._tpl_last[i] = _truthy(self.ha.w.render_native(tr["value_template"], {}))
            elif kind == "time":
                self._time_fired.discard(i)
            elif kind in ("state", "homeassistant", "event"):
                pass
            else:
                raise Unsupported(f"trigger {kind}")
        self._last_states = dict(self.ha.w.states)

    def ha_start(self):
        for tr in self.triggers:
            if tr["trigger"] == "homeassistant" and tr.get("event") == "start":
                self.fire({"id": tr.get("id", "0"), "platform": "homeassistant"})

    def poll(self, kind):
        if not self.ready:
            return
        w = self.ha.w
        for i, tr in enumerate(self.triggers):
            t = tr["trigger"]
            tid = tr.get("id", str(i))
            if t == "template":
                val = _truthy(w.render_native(tr["value_template"], {}))
                was = self._tpl_last.get(i, False)
                self._tpl_last[i] = val
                if val and not was and tid not in self.disabled_triggers:
                    self.fire({"id": tid, "platform": "template"})
            elif t == "time":
                ent = tr["at"]
                if not isinstance(ent, str) or not ent.startswith("input_datetime."):
                    raise Unsupported(f"time trigger at {ent!r}")
                st = w.state(ent)
                try:
                    when = parse_local(st)
                except ValueError:
                    continue
                key = (i, when)
                if w.t >= when and key not in self._time_fired and w.t - when < 1.0:
                    self._time_fired.add(key)
                    if tid not in self.disabled_triggers:
                        self.fire({"id": tid, "platform": "time"})
            elif t == "state" and kind == "state":
                ents = tr["entity_id"] if isinstance(tr["entity_id"], list) else [tr["entity_id"]]
                for ent in ents:
                    new = w.states.get(ent, ("unknown", {}))
                    old = self._last_states.get(ent, ("unknown", {}))
                    want = tr.get("to", new[0])     # smr1: `to: ~` (None) = any change of the state, never of attributes alone
                    if new[0] != old[0] and str(new[0] if want is None else want) == new[0]:
                        self.fire({"id": tid, "platform": "state", "entity_id": ent,
                                   "to_state": {"state": new[0], "attributes": dict(new[1])},
                                   "from_state": {"state": old[0], "attributes": dict(old[1])}})
        self._last_states = dict(w.states)

    def schedule_time_triggers(self):
        """Put the exact instant of every time trigger on the event queue (so it fires at the second)."""
        w = self.ha.w
        for i, tr in enumerate(self.triggers):
            if tr["trigger"] == "time":
                try:
                    when = parse_local(w.state(tr["at"]))
                except ValueError:
                    continue
                if when >= w.t:
                    w.at(when, lambda: self.poll("time"))

    def fire(self, trigger: dict):
        w = self.ha.w
        if self.running and self.mode == "queued":
            if len(self.queue) < int(self.cfg.get("max", 10)):
                self.queue.append(trigger)
            return
        if self.running and self.mode == "single":
            w.warnings.append(f"{w.t:.3f} automation {self.id} already running (trigger {trigger['id']} dropped)")
            return
        variables = {"trigger": trigger, "this": {}}
        if not self.ha.cond(self.cfg.get("conditions") or [], variables):
            return
        self.fired.append((w.t, trigger["id"]))
        self.running = True
        self._gen += 1
        gen = self._gen

        def done(err=None):
            if gen == self._gen:
                self.running = False
                if self.queue:
                    nxt = self.queue.pop(0)
                    w.after(0, lambda: self.fire(nxt))

        self.ha._drive(self.ha._seq(self.cfg["actions"], variables), done)


# ================================================================================================================
# The dongle: Free Power start gate, transaction and timer, and the shared Modbus bus.
# ================================================================================================================
P = "ecco_clock_dongle_"
E_ARM = f"switch.{P}free_power_write_enable"
E_PRESS = f"button.{P}start_free_power_charge_now"
E_STATUS = f"sensor.{P}free_power_status"
E_ACTIVE = f"binary_sensor.{P}free_power_active"
E_OP = f"binary_sensor.{P}free_power_operation_in_progress"
E_SNAP = f"binary_sensor.{P}free_power_snapshot_valid"
E_TEL = f"binary_sensor.{P}telemetry_online"
E_CFG = f"binary_sensor.{P}configuration_online"
E_NTP = f"binary_sensor.{P}ntp_synced"
E_DUR = f"number.{P}free_power_duration"
E_PWR = f"number.{P}free_power_max_charge_power"
E_DUMP_ACTIVE = f"binary_sensor.{P}dump_to_grid_active"
E_DUMP_SNAP = f"binary_sensor.{P}dump_to_grid_snapshot_valid"
E_MANUAL = f"binary_sensor.{P}manual_write_in_progress"
E_ATTEMPTS = f"sensor.{P}free_power_start_attempts_since_boot"
E_LIMIT = "sensor.ecco_config_maximum_grid_charge_power"   # an HA template over a dongle sensor: unavailable with it

# Measured on 11 Oct 2026 (HA receive times, BST, see the FPS1 incident record): the two telemetry blocks keep the
# bus busy (queued -> reply -> 600 ms turnaround) at these seconds of every 10 s cycle, and the configuration poll
# plus the inverter clock read at these seconds of every minute (the :40 cycle's telemetry queues behind them).
BUSY_10S = ((2.38, 3.15), (4.88, 5.62))
BUSY_60S = ((39.56, 40.28), (42.06, 43.53), (44.56, 45.91), (48.29, 48.91))

REJECT = {
    "active": "REJECTED - Free Power already active",
    "snapshot": "REJECTED - saved snapshot pending restore/recovery",
    "write": "REJECTED - another inverter write is active",
    "rtc": "REJECTED - RTC correction currently active",
    "dump": "REJECTED - Dump to Grid override/recovery owns inverter settings",
    "config": "REJECTED - inverter configuration offline",
    "ntp": "REJECTED - valid NTP time required for automatic end",
    "arm": "REJECTED - arm Free Power Write Enable first",
    "corrupt": ("REJECTED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data cannot be trusted "
                "(unreadable or invalid); deliberate recovery required"),
    "voltage": "REJECTED - plausible live battery voltage required for W-to-A conversion",
    "bus": "REJECTED - Modbus bus busy with another transaction; try again shortly",
}


class Dongle:
    """The firmware side, at the level the HA package can observe. `phase` shifts the poll schedule (seconds);
    `handle_delays` is the press -> gate delay per press (cycled); `publish` is dongle -> HA latency."""

    def __init__(self, world: World, phase: float = 0.0, handle_delays=(0.15,), publish: float = 0.12,
                 outcome: str = "ok", transaction_s: float = 6.0):
        self.w = world
        self.phase = phase
        self.handle_delays = list(handle_delays)
        self.publish = publish
        self.outcome = outcome
        self.transaction_s = transaction_s
        self.rtc: list[tuple[float, float]] = []
        self.writes: list[tuple[float, float]] = []    # another (manual) inverter write in progress
        self.offline: list[tuple[float, float]] = []
        self.stalls: list[tuple[float, float]] = []    # the API stops delivering (TCP alive): publishes arrive at the end
        self.flags = {"snapshot": False, "dump": False, "ntp_bad": False, "corrupt": False}
        self.number_log: list[tuple[float, str, int]] = []
        self.drop_numbers = False                      # test hook: staging writes never reach the dongle
        self.op_intervals: list[list[float]] = []
        self.limit = 8000
        self.presses: list[tuple[float, str]] = []     # (gate time, outcome text)
        self.press_log: list[float] = []               # HA press times
        self.attempts = 0
        self.successes = 0
        self.duration = 240                          # restore_value: the last staged values survive a reboot
        self.power = 8000
        self.arm = False
        self.active = False
        self.op = False
        self.ends_at = None
        self.started_at = None
        self.dropped = 0
        for e, s in ((E_ARM, "off"), (E_ACTIVE, "off"), (E_OP, "off"), (E_SNAP, "off"), (E_TEL, "on"),
                     (E_CFG, "on"), (E_NTP, "on"), (E_DUMP_ACTIVE, "off"), (E_DUMP_SNAP, "off"),
                     (E_MANUAL, "off"), (E_ATTEMPTS, "0.0"), (E_DUR, "240.0"), (E_PWR, "8000.0"),
                     (E_STATUS, "IDLE - no Free Power override active")):
            world.set(e, s)
        world.at(world.t + 7.0, self._attempts_tick)
        world.service_handlers.update({
            "switch.turn_on": self._switch(True), "switch.turn_off": self._switch(False),
            "button.press": self._press, "number.set_value": self._number,
        })

    # --- bus -------------------------------------------------------------------------------------------------
    def bus_busy(self, t: float) -> bool:
        s = (t - self.phase) % 60.0
        c = s % 10.0
        if not (40.0 <= s < 50.0) and any(a <= c < b for a, b in BUSY_10S):
            return True
        return any(a <= s < b for a, b in BUSY_60S)

    def rtc_active(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.rtc)

    def is_offline(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.offline)

    DONGLE_ENTITIES = (E_ARM, E_STATUS, E_ACTIVE, E_OP, E_SNAP, E_TEL, E_CFG, E_NTP, E_MANUAL, E_ATTEMPTS, E_DUMP_ACTIVE,
                       E_DUMP_SNAP, E_DUR, E_PWR)

    def set_offline(self, a: float, b: float) -> None:
        """The dongle's API is down: every dongle entity (and the HA limit derived from one) is unavailable."""
        self.offline.append((a, b))

        def down():
            for e in self.DONGLE_ENTITIES:
                self.w.set(e, "unavailable")
            self.w.set(E_LIMIT, "unavailable")

        def up():
            for e, v in ((E_ARM, "on" if self.arm else "off"), (E_ACTIVE, "on" if self.active else "off"),
                         (E_OP, "on" if self.op else "off"), (E_SNAP, "on" if self.flags["snapshot"] else "off"),
                         (E_TEL, "on"), (E_CFG, "on"), (E_NTP, "on"), (E_MANUAL, "on" if self.op else "off"),
                         (E_ATTEMPTS, f"{float(self.attempts)}"), (E_DUMP_ACTIVE, "off"), (E_DUMP_SNAP, "off"),
                         (E_STATUS, self.status), (E_DUR, f"{float(self.duration)}"), (E_PWR, f"{float(self.power)}")):
                self.w.set(e, v)
            self.w.set(E_LIMIT, str(self.limit))
        self.w.at(a, down)
        self.w.at(b, up)

    def _attempts_tick(self):
        if not self.is_offline(self.w.t):
            self._pub(E_ATTEMPTS, f"{float(self.attempts)}")
        self.w.after(30.0, self._attempts_tick)

    def manual_start(self, at: float, duration: int = 60) -> None:
        """The owner's own "Free Power now" (stage the duration, arm, then press) at `at`."""
        def go():
            self.duration = duration
            self.arm = True
            self._pub(E_ARM, "on")
            self.w.after(1.0, lambda: (self.press_log.append(self.w.t), self._gate()))
        self.w.at(at, go)

    status = "IDLE - no Free Power override active"

    def _pub(self, entity, state, delay=None):
        if entity == E_STATUS:
            self.status = state
        when = self.w.t + (self.publish if delay is None else delay)
        for a, b in self.stalls:
            if a <= when < b:
                when = b + (when - a) * 1e-3          # held, then delivered in order when the stall ends
        if self.is_offline(when):
            return
        self.w.at(when, lambda: self.w.set(entity, state))

    # --- services --------------------------------------------------------------------------------------------
    def _switch(self, on: bool):
        def h(entity, data):
            if entity != E_ARM:
                raise Unsupported(f"switch {entity}")
            if self.is_offline(self.w.t):
                return
            self.w.after(0.03, lambda: self._set_arm(on))
        return h

    def _set_arm(self, on: bool):
        self.arm = on
        self._pub(E_ARM, "on" if on else "off")

    def _number(self, entity, data):
        if self.is_offline(self.w.t):
            return
        self.number_log.append((self.w.t, entity, int(float(data["value"]))))
        if self.drop_numbers:
            return
        if entity == E_DUR:
            self.duration = int(float(data["value"]))
        elif entity == E_PWR:
            self.power = int(float(data["value"]))
        else:
            raise Unsupported(f"number {entity}")
        if not self.drop_numbers:
            self._pub(entity, f"{float(data['value'])}")

    def _press(self, entity, data):
        if entity != E_PRESS:
            raise Unsupported(f"button {entity}")
        self.press_log.append(self.w.t)
        if self.is_offline(self.w.t):
            return
        d = self.handle_delays[(len(self.press_log) - 1) % len(self.handle_delays)]
        self.w.after(d, self._gate)

    def _gate(self):
        t = self.w.t
        if self.op:                                   # the firmware script is mode: single - the press is dropped
            self.dropped += 1
            return
        reason = None
        if self.flags["corrupt"]:
            reason = "corrupt"
        elif self.active:
            reason = "active"
        elif self.flags["snapshot"]:
            reason = "snapshot"
        elif any(a <= t < b for a, b in self.writes):
            reason = "write"
        elif self.rtc_active(t):
            reason = "rtc"
        elif self.flags["dump"]:
            reason = "dump"
        elif self.is_offline(t):
            reason = "config"
        elif self.flags["ntp_bad"]:
            reason = "ntp"
        elif not self.arm:
            reason = "arm"
        elif self.bus_busy(t):
            reason = "bus"
        self.arm = False
        if reason:
            self.presses.append((t, REJECT[reason]))
            self._pub(E_STATUS, REJECT[reason])
            self._pub(E_ARM, "off", (self.publish + 0.0003))
            return
        self.presses.append((t, "PASSED"))
        self.attempts += 1
        self.op = True
        self.op_intervals.append([t, None])
        self._pub(E_MANUAL, "on")
        self._pub(E_ARM, "off")
        self._pub(E_STATUS, "STARTING - taking fresh inverter snapshot")
        self._pub(E_OP, "on")
        self.w.after(self.transaction_s, self._finish)

    def _finish(self):
        t = self.w.t
        self.op = False
        self.op_intervals[-1][1] = t
        self._pub(E_MANUAL, "off")
        if self.outcome == "ok":
            self.active = True
            self.successes += 1
            self.started_at = t
            self.ends_at = t + self.duration * 60
            self._pub(E_STATUS, "ACTIVE - VERIFIED OK; 155A grid charge; automatic restore armed")
            self._pub(E_ACTIVE, "on")
            self._pub(E_OP, "off")
            self.w.at(self.ends_at, self._end)
        elif self.outcome == "write_failed":
            self.flags["snapshot"] = True
            self._pub(E_SNAP, "on")
            self._pub(E_STATUS, "ACTIVATION WRITE FAILED - restoring saved snapshot")
            self._pub(E_OP, "off")
        elif self.outcome == "capture_failed":
            self._pub(E_STATUS, "START FAILED - could not capture complete inverter snapshot")
            self._pub(E_OP, "off")
        else:
            raise Unsupported(self.outcome)

    def _end(self):
        self.active = False
        self._pub(E_ACTIVE, "off")
        self._pub(E_STATUS, "RESTORED - exact snapshot verified")
