"""Test support for the time trust package (home-assistant/packages/ecco_time_trust.yaml): a small, deterministic model of Home Assistant's
STATE-BASED template entities (template sensors and template binary sensors), built on the FPS1 interpreter's state machine and Jinja
environment (_ha_script_sim.py), which it reuses unchanged.

The interpreter's own package loader runs scripts, automations and template SENSORS rendered on read. The time trust package needs more: binary
sensors with `delay_on`, an `availability` template, attributes, entities that read each other, and templates that must re-render by the passing
of time alone (a frozen text must turn UNTRUSTED without any entity changing). This module models exactly that, as RECALLED from Home Assistant
core (not verified against a live instance; the package header lists what is recalled):

  - an entity id is `<kind>.<slug of the name>`; the state template, every attribute template and the availability template are rendered together;
  - DEPENDENCY TRACKING: the entities a render reads (`states('x')`, `states.<domain>.<object>`, `is_state`, `state_attr`) are recorded, and the entity
    is rendered again only when one of them changes; a template that called now() is also rendered again at the start of every minute;
  - a render error leaves the entity `unknown` (a sensor) and is counted in `errors` (a suite requires it to stay empty: every template is total);
  - an entity whose availability template is false reads `unavailable` and has no attributes;
  - attribute results are parsed natively (a number, a list, a string);
  - a binary sensor turns the state result into a boolean, and UPDATES ITS STATE ONLY WHEN THE STATE RESULT CHANGES: with `delay_on` a change to true
    starts a timer (the entity keeps its state while it counts), any later change of the result cancels it, and the entity turns on when the timer
    ends; a change to false is immediate. A first result of true with a delay leaves the entity `unknown` (or a restored `off`) until the delay ends;
  - nothing is restored at a restart (`restore_off=True` models a restored `off` for the delayed sensors).

`override(entity, state)` replaces a template entity's state by a fixed one (to drive a consumer, or an input rule, in isolation); the dongle's own
entities are plain `put()` states. There is no service, no action and no write: the model cannot call anything. No I/O, no network, no hardware.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

import _ha_script_sim as S

_YAML: dict = {}       # package text -> parsed document (read only)
_CODE: dict = {}       # template source -> compiled Jinja code (every world builds its environment alike)

FMT = "%Y-%m-%d %H:%M:%S"
_MARK = {"_model": 1}          # World.set keeps the old attributes when handed an empty dict: every write carries this marker


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def _seconds(text: str) -> float:
    h, m, s = (int(x) for x in str(text).split(":"))
    return float(h * 3600 + m * 60 + s)


class _Ent:
    def __init__(self, kind: str, cfg: dict):
        self.kind = kind
        self.name = cfg["name"]
        self.eid = f"{kind}.{slug(cfg['name'])}"
        self.unique_id = cfg.get("unique_id")
        self.state_tpl = cfg["state"]
        self.attr_tpls = dict(cfg.get("attributes") or {})
        self.avail_tpl = cfg.get("availability")
        self.delay_on = _seconds(cfg["delay_on"]) if cfg.get("delay_on") else 0.0
        self.delay_off = _seconds(cfg["delay_off"]) if cfg.get("delay_off") else 0.0
        self.deps: set = set()
        self.uses_now = False
        self.last_result = None
        self.first = True
        self.value = None                  # a binary sensor's committed state (True / False / None = unknown)
        self.timer = None
        self.override = None
        self.state_txt = None
        self.attrs: dict = {}
        self.avail = True


class TrustWorld:
    """One virtual Home Assistant holding the package's template entities, over a virtual clock."""

    def __init__(self, package_text: str, start: str = "2026-11-25 12:00:00", zone: str = "Europe/London", restore_off: bool = False,
                 preload: dict | None = None):
        self.zone = ZoneInfo(zone)
        t0 = datetime.strptime(start, FMT).replace(tzinfo=self.zone).timestamp()
        self.w = S.World(t0)
        self.errors: list[str] = []
        self.restore_off = restore_off
        self.pending: set = set()
        self.renders: dict = {}
        self.rendered_at: dict = {}
        self._tpl: dict = {}
        self._rec: set = set()
        self._now_used = False
        self._busy = False
        self._again = False
        self._install_env()
        self._wrap_set()
        if package_text not in _YAML:
            _YAML[package_text] = yaml.safe_load(package_text) or {}
        pkg = _YAML[package_text]
        self.ents: list[_Ent] = []
        for block in pkg.get("template") or []:
            for kind, items in block.items():
                for it in items:
                    self.ents.append(_Ent(kind, it))
        self.by_id = {e.eid: e for e in self.ents}
        if len(self.by_id) != len(self.ents):
            raise S.Unsupported("two template entities with one entity id")
        for e in self.ents:
            if e.kind == "binary_sensor" and self.restore_off and (e.delay_on or e.delay_off):
                e.value = False
        for eid, st in (preload or {}).items():          # entities that already exist when the template entities are first rendered (a template reload)
            self.w.set(eid, st, dict(_MARK))
        self.w.listeners.append(self._on_world)
        self._settle("start")

    # --- the environment ---------------------------------------------------------------------------------------------
    def _install_env(self) -> None:
        w, z, tw = self.w, self.zone, self

        def now():
            tw._now_used = True
            return datetime.fromtimestamp(w.t + w.clock_offset, z)

        def as_ts(value, default=S._MISSING):
            try:
                if isinstance(value, datetime):
                    return value.timestamp()
                if isinstance(value, (int, float)):
                    return float(value)
                # a text with no offset is read as local time in the zone, the FIRST of two equal times (fold 0), as the R9 packages assume
                return datetime.strptime(str(value), FMT).replace(tzinfo=z).timestamp()
            except (TypeError, ValueError):
                if default is S._MISSING:
                    raise S.SimError(f"as_timestamp could not parse {value!r} and no default was given")
                return default

        def state_obj(eid):
            tw._rec.add(eid)
            st = w.states.get(eid)
            if st is None:
                return None                                  # Home Assistant: an entity that does not exist is none
            return S._StateObj(st[0], w.changed_at.get(eid, 0.0), w.updated_at.get(eid))

        class _States:
            def __call__(self, eid):
                tw._rec.add(eid)
                return w.state(eid)

            def __getattr__(self, name):
                if name.startswith("_") or name in ("unsafe_callable", "alters_data"):      # the sandbox's own probes are not names
                    raise AttributeError(name)
                if "." in name:                                  # states['domain.object']: the state object of that entity
                    return state_obj(name)

                class _Domain:
                    def __getattr__(_s, obj):                    # states.domain.object
                        return state_obj(f"{name}.{obj}")
                return _Domain()

            __getitem__ = __getattr__

        def is_state(eid, value):
            tw._rec.add(eid)
            return w.is_state(eid, value)

        def state_attr(eid, attr):
            tw._rec.add(eid)
            return w.state_attr(eid, attr)

        w.env.globals.update(now=now, as_timestamp=as_ts, states=_States(), is_state=is_state, state_attr=state_attr)

    def _wrap_set(self) -> None:
        w = self.w
        orig = w.set

        def set_(entity_id, state, attrs=None):
            old = w.states.get(entity_id)
            if old is None or old[0] != str(state) or (attrs is not None and attrs != old[1]):
                self.pending.add(entity_id)
            orig(entity_id, state, attrs)
        w.set = set_

    # --- the dongle's side -------------------------------------------------------------------------------------------
    def put(self, eid: str, state, attrs: dict | None = None) -> None:
        """A plain entity (the dongle's) takes a state. `None` removes the entity (it does not exist in Home Assistant)."""
        if state is None:
            if eid in self.w.states:
                del self.w.states[eid]
                self.pending.add(eid)
                self._settle("state")
            return
        self.w.set(eid, state, dict(attrs or {}) or dict(_MARK))

    def local_text(self, true_epoch: float, zone: str | None = None) -> str:
        return datetime.fromtimestamp(true_epoch, ZoneInfo(zone) if zone else self.zone).strftime(FMT)

    def feed(self, eid: str, period: float = 60.0, offset_s: float = 0.0, until: float | None = None, zone: str | None = None) -> dict:
        """The dongle publishes a text sensor every `period` seconds (a local-time string of the TRUE time plus `offset_s`, in `zone`: the dongle's own
        zone, by default Home Assistant's), now and then on every period, until the virtual time `until`. Returns a handle: handle['on'] = False
        stops it."""
        h = {"on": True}

        def tick():
            if not h["on"] or (until is not None and self.w.t > until):
                return
            self.w.set(eid, self.local_text(self.w.t + offset_s, zone), dict(_MARK))
            self.w.after(period, tick)
        tick()
        return h

    def age(self, eid: str, seconds: float) -> None:
        """Make an entity's state `seconds` old (last_changed and last_updated, by Home Assistant's own clock), then render everything."""
        stamp = self.w.t + self.w.clock_offset - seconds
        self.w.changed_at[eid] = stamp
        self.w.updated_at[eid] = stamp
        self.force()

    def advance(self, seconds: float) -> None:
        self.w.run_until(self.w.t + seconds)

    def force(self) -> None:
        """Render every entity now (some entity it reads changed at this instant), whatever the dependency tracking says."""
        self._settle("start", force_all=True)

    def override(self, eid: str, state) -> None:
        """Fix a template entity's state (None releases it). For driving a consumer or an input rule in isolation."""
        e = self.by_id[eid]
        e.override = state
        self._publish(e)
        self._settle("state")

    # --- reading -----------------------------------------------------------------------------------------------------
    def state(self, eid: str) -> str:
        return self.w.state(eid)

    def attr(self, eid: str, name: str):
        return self.w.states.get(eid, ("unknown", {}))[1].get(name)

    # --- the engine --------------------------------------------------------------------------------------------------
    def _on_world(self, kind: str) -> None:
        if kind == "minute":
            self._settle("minute")
        elif self.pending:
            self._settle("state")

    def _settle(self, kind: str, force_all: bool = False) -> None:
        if self._busy:
            self._again = True
            return
        self._busy = True
        try:
            first = kind == "start" or force_all
            minute = kind == "minute"
            for _ in range(60):
                changed, self.pending = self.pending, set()
                todo = [e for e in self.ents if first or (minute and e.uses_now) or (changed & e.deps)]
                first = minute = False
                self._again = False
                for e in todo:
                    self._refresh(e)
                if not self.pending and not self._again:
                    return
            raise RuntimeError("template feedback loop: the entities never settled")
        finally:
            self._busy = False

    def _render(self, source: str) -> str:
        tpl = self._tpl.get(source)
        if tpl is None:
            env = self.w.env
            if source not in _CODE:
                _CODE[source] = env.compile(source)
            tpl = self._tpl[source] = env.template_class.from_code(env, _CODE[source], env.make_globals(None), None)
        return tpl.render()

    def _eval(self, e: _Ent):
        self._rec, self._now_used = set(), False
        self.renders[e.eid] = self.renders.get(e.eid, 0) + 1
        self.rendered_at[e.eid] = self.w.t              # the virtual time of the render: what an entity shows is as of its last render
        try:
            st = self._render(e.state_tpl).strip()
            attrs = {k: S._native(self._render(t).strip()) for k, t in e.attr_tpls.items()}
            avail = True if e.avail_tpl is None else S._truthy(S._native(self._render(e.avail_tpl).strip()))
        except Exception as exc:  # noqa: BLE001 - a template error is a recorded finding, then `unknown` (Home Assistant's own outcome)
            self.errors.append(f"{e.eid}: {type(exc).__name__}: {str(exc)[:120]}")
            st, attrs, avail = None, {}, True
        e.deps, e.uses_now = set(self._rec), self._now_used
        return st, attrs, avail

    def _refresh(self, e: _Ent) -> None:
        st, attrs, avail = self._eval(e)
        e.attrs, e.avail = attrs, avail
        if e.kind == "binary_sensor":
            result = None if st is None else S._truthy(S._native(st))
            if e.first or result != e.last_result:
                e.first, e.last_result = False, result
                self._binary_update(e, result)
        else:
            e.state_txt = "unknown" if st is None else st
        self._publish(e)

    def _binary_update(self, e: _Ent, result) -> None:
        if e.timer is not None:
            e.timer = None                     # cancelled: the callback below checks its token
        if result == e.value:
            return
        delay = e.delay_on if result else e.delay_off
        if not delay or result is None:
            e.value = result
            return
        token = object()
        e.timer = token

        def fire():
            if e.timer is token:
                e.timer, e.value = None, result
                self._publish(e)
                self._settle("state")
        self.w.after(delay, fire)

    def _shown(self, e: _Ent) -> str:
        if e.override is not None:
            return str(e.override)
        if not e.avail:
            return "unavailable"
        if e.kind == "binary_sensor":
            return {True: "on", False: "off", None: "unknown"}[e.value]
        return e.state_txt if e.state_txt is not None else "unknown"

    def _publish(self, e: _Ent) -> None:
        shown = self._shown(e)
        attrs = {} if (e.override is not None or shown == "unavailable") else dict(e.attrs)
        attrs.update(_MARK)
        self.w.set(e.eid, shown, attrs)
