"""Test support for the reserve floor read-back package (home-assistant/packages/ecco_reserve_floor_status.yaml): ONE virtual Home Assistant that holds, on one
state machine and one virtual clock,

  - the package's TEMPLATE entities (template sensors and a template binary sensor with an availability template and attributes), run by a small model of
    Home Assistant's state-based template entities: dependency tracking (an entity is rendered again only when an entity it read changes), a render at the start
    of every minute for a template that called now(), the availability template as a SUPER template (while it is false nothing else is rendered and the entity
    reads unavailable), attributes parsed natively, a render error leaving a sensor `unknown` and counted in `errors` (a suite requires it to stay empty), a
    template RELOAD (every template entity reads unavailable once, then is created again and rendered) and a RESTART (the entities exist with their RESTORED
    state, and a new automation instance starts, before the first render, which comes a few milliseconds later: measured 43 and 74 ms on a real core);
  - its HELPER and its AUTOMATION, run by the FPS1 interpreter (_ha_script_sim.HA) on the same World, which this module reuses unchanged.

It is the same technique as the time trust suite's template model (a smaller copy: only what this package needs; no delayed binary sensors). Home Assistant's own
behaviour is MODELLED as recalled, NOT verified on a real instance: how as_timestamp() reads a naive text (as local time in the zone: the Core process zone is the
house's assumption), that states['x'].last_changed is new at a restart, that the template trigger fires on a false-to-true change only. There is no network, no
hardware and no write other than the persistent notifications the interpreter itself records.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml

import _ha_script_sim as S

FMT = "%Y-%m-%d %H:%M:%S"
_MARK = {"_model": 1}          # World.set keeps the old attributes when handed an empty dict: every write carries this marker
_YAML: dict = {}
_CODE: dict = {}

D = "ecco_clock_dongle"
PLAN = "sensor.ecco_plan_effective_reserve"
CORE = "sensor.ecco_reserve_floor_core"
STATUS = "sensor.ecco_reserve_floor_status"
BINARY = "binary_sensor.ecco_reserve_not_held_by_inverter"
OPTIN = "input_boolean.ecco_tell_me_reserve_not_enforced"
NOTE = "ecco_reserve_floor_not_held"
SHUT = f"sensor.{D}_ecco_battery_shutdown"
TOU = f"binary_sensor.{D}_ecco_time_of_use_enabled"
ONLINE = f"binary_sensor.{D}_configuration_online"
CFGTIME = f"sensor.{D}_last_configuration_update"
SOC = [f"sensor.{D}_ecco_timezone{n}_soc" for n in range(1, 7)]
SRC = [f"sensor.{D}_ecco_timezone{n}_charge" for n in range(1, 7)]
FLAGS = [f"binary_sensor.{D}_free_power_active", f"binary_sensor.{D}_free_power_operation_in_progress", f"binary_sensor.{D}_free_power_snapshot_valid",
         f"binary_sensor.{D}_dump_to_grid_active", f"binary_sensor.{D}_dump_to_grid_operation_in_progress", f"binary_sensor.{D}_dump_to_grid_snapshot_valid",
         f"binary_sensor.{D}_manual_write_in_progress", "input_boolean.ecco_cfg_edit_in_flight"]
REC_FP = f"sensor.{D}_free_power_recovery_state"
REC_DG = f"sensor.{D}_dump_to_grid_recovery_state"
READS = set(SOC + SRC + FLAGS + [PLAN, SHUT, TOU, ONLINE, CFGTIME, REC_FP, REC_DG])
OWN = {CORE, STATUS, BINARY}


@lru_cache(maxsize=8192)
def _native_cached(text: str):
    return S._native(text)


def native(text: str):
    v = _native_cached(text)
    return copy.deepcopy(v) if isinstance(v, (list, dict)) else v


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


# --- Home Assistant's date parsing (dt_util.parse_datetime), as recalled: ISO 8601 first, then its own pattern -----------------------------------------
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?)?(Z|[+-]\d{2}(?::?\d{2})?)?")


def ha_as_timestamp(value, zone):
    """dt_util.as_timestamp: a datetime is used as it is; a text is parsed (a naive one is LOCAL time in the zone); a text that is no date raises ValueError."""
    if isinstance(value, datetime):
        dt = value
    else:
        m = _ISO.fullmatch(str(value))
        if m is None:
            raise ValueError("not a valid date/time.")
        y, mo, d, h, mi, s, frac, tz = m.groups()
        off = None
        if tz == "Z":
            off = timezone.utc
        elif tz:
            digits = tz[1:].replace(":", "")
            delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]) if len(digits) > 2 else 0)
            off = timezone(-delta if tz[0] == "-" else delta)
        dt = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0), tzinfo=off)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.timestamp()


class _Ent:
    def __init__(self, kind: str, cfg: dict):
        self.kind = kind
        self.eid = f"{kind}.{slug(cfg['name'])}"
        self.state_tpl = cfg["state"]
        self.attr_tpls = dict(cfg.get("attributes") or {})
        self.avail_tpl = cfg.get("availability")
        self.deps: set = set()
        self.uses_now = False
        self.state_txt = None
        self.attrs: dict = {}
        self.avail = True
        self.value = None
        self.dead = False
        self.override = None


def package_parts(text: str) -> dict:
    """A package without its template block: the interpreter runs the helper and the automation, the template model runs the templates."""
    d = yaml.safe_load(text) or {}
    d.pop("template", None)
    return d


class FloorWorld:
    """One virtual Home Assistant for the reserve floor read-back package."""

    def __init__(self, package_text: str, start: str = "2026-11-27 12:00:00", zone: str = "Europe/London", extra: tuple = ()):
        self.zone = ZoneInfo(zone)
        self.t0 = datetime.strptime(start, FMT).replace(tzinfo=self.zone).timestamp()
        self.w = S.World(self.t0)
        self.errors: list[str] = []
        self.pending: set = set()
        self.renders: dict = {}
        self._tpl: dict = {}
        self._rec: set = set()
        self._now_used = False
        self._busy = False
        self._again = False
        self.package_text = package_text
        self._parts = [package_parts(package_text)] + [yaml.safe_load(t) for t in extra]
        self._install_env()
        self._wrap_set()
        self._build()
        self.w.listeners.append(self._on_world)
        self.ha = S.HA(self.w, self._parts)
        self._settle("start")
        self.ha.start()

    # --- the package's template entities -------------------------------------------------------------------------------
    def _build(self) -> None:
        text = self.package_text
        if text not in _YAML:
            _YAML[text] = yaml.safe_load(text) or {}
        self.ents: list[_Ent] = []
        for block in _YAML[text].get("template") or []:
            for kind, items in block.items():
                for it in items:
                    self.ents.append(_Ent(kind, it))
        self.by_id = {e.eid: e for e in self.ents}
        if len(self.by_id) != len(self.ents):
            raise S.Unsupported("two template entities with one entity id")

    def _install_env(self) -> None:
        w, z, me = self.w, self.zone, self

        def now():
            me._now_used = True
            return datetime.fromtimestamp(w.t + w.clock_offset, z)

        def as_ts(value, default=S._MISSING):
            try:
                return ha_as_timestamp(value, z)
            except (TypeError, ValueError):
                if default is S._MISSING:
                    raise S.SimError(f"as_timestamp could not parse {value!r} and no default was given")
                return default

        def strptime(string, fmt, default=S._MISSING):
            try:
                return datetime.strptime(string, fmt)
            except (ValueError, AttributeError, TypeError):
                if default is S._MISSING:
                    raise S.SimError(f"strptime could not parse {string!r} and no default was given")
                return default

        def state_obj(eid):
            me._rec.add(eid)
            st = w.states.get(eid)
            if st is None:
                return None
            return S._StateObj(st[0], w.changed_at.get(eid, 0.0), w.updated_at.get(eid))

        class _States:
            def __call__(self, eid):
                me._rec.add(eid)
                return w.state(eid)

            def __getattr__(self, name):
                if name.startswith("_") or name in ("unsafe_callable", "alters_data"):
                    raise AttributeError(name)
                if "." in name:
                    return state_obj(name)

                class _Domain:
                    def __getattr__(_s, obj):
                        return state_obj(f"{name}.{obj}")
                return _Domain()

            __getitem__ = __getattr__

        def is_state(eid, value):
            me._rec.add(eid)
            return w.is_state(eid, value)

        def state_attr(eid, attr):
            me._rec.add(eid)
            return w.state_attr(eid, attr)

        w.env.globals.update(now=now, as_timestamp=as_ts, strptime=strptime, states=_States(), is_state=is_state, state_attr=state_attr)
        w.env.globals.setdefault("range", range)

    def _wrap_set(self) -> None:
        w = self.w
        orig = w.set

        def set_(entity_id, state, attrs=None):
            old = w.states.get(entity_id)
            if old is None or old[0] != str(state) or (attrs is not None and attrs != old[1]):
                self.pending.add(entity_id)
            orig(entity_id, state, attrs)
        w.set = set_

    # --- the world around the package ------------------------------------------------------------------------------------
    def put(self, eid: str, state, attrs: dict | None = None) -> None:
        """A plain entity (the dongle's, the plan's, a helper) takes a state; None removes it (it does not exist)."""
        if state is None:
            if eid in self.w.states:
                del self.w.states[eid]
                self.pending.add(eid)
                self._settle("state")
            return
        self.w.set(eid, state, dict(attrs or {}) or dict(_MARK))

    def local_text(self, true_epoch: float) -> str:
        return datetime.fromtimestamp(true_epoch, self.zone).strftime(FMT)

    def feed(self, eid: str, period: float = 60.0) -> dict:
        """The dongle publishes a local-time text every `period` seconds (the true time); handle['on'] = False stops it."""
        h = {"on": True}

        def tick():
            if not h["on"]:
                return
            self.w.set(eid, self.local_text(self.w.t + self.w.clock_offset), dict(_MARK))
            self.w.after(period, tick)
        tick()
        return h

    def advance(self, seconds: float) -> None:
        self.w.run_until(self.w.t + seconds)

    def force(self) -> None:
        self._settle("start", force_all=True)

    def put_many(self, states: dict) -> None:
        """Several plain entities take a state at the same instant, and the templates render ONCE afterwards (a faster path for a suite that sweeps thousands of worlds)."""
        self.w.listeners.remove(self._on_world)
        try:
            for eid, state in states.items():
                if state is None:
                    self.w.states.pop(eid, None)
                else:
                    self.w.set(eid, state, dict(_MARK))
        finally:
            self.w.listeners.insert(0, self._on_world)
        self.pending = set()
        self._settle("start", force_all=True)

    def override(self, eid: str, state) -> None:
        """Fix a template entity's state (None releases it): to drive a consumer in isolation."""
        e = self.by_id[eid]
        e.override = state
        self._publish(e)
        self._settle("state")

    def reload(self) -> None:
        """template.reload: every template entity of the package reads unavailable once (a row), then is created again and rendered."""
        for e in self.ents:
            e.dead = True
            self.w.set(e.eid, "unavailable", dict(_MARK))
        self.pending = set()
        self._build()
        self._settle("start")

    def restart(self, gone: tuple = (), render_after: float = 0.05) -> None:
        """Home Assistant restarts. The old automations die; the entities in `gone` read unavailable until they report again; the template entities exist with their
        RESTORED state and a NEW automation instance starts at once; the first render of the templates comes `render_after` seconds later (43 and 74 ms measured)."""
        self.ha.stop()
        for e in self.ents:
            e.dead = True                                     # the old entities die first: nothing renders while the world around them changes
        for eid in gone:
            self.put(eid, "unavailable")
        self.pending = set()
        stamp = self.w.t + self.w.clock_offset
        for e in self.ents:                                   # a restored state is a NEW state object: its last_changed is the start (recalled, not verified)
            self.w.changed_at[e.eid] = stamp
            self.w.updated_at[e.eid] = stamp
        self._build()
        self.ha = S.HA(self.w, self._parts)
        self.ha.start()
        self.w.after(render_after, lambda: self._settle("start"))

    # --- reading ---------------------------------------------------------------------------------------------------------
    def state(self, eid: str) -> str:
        return self.w.state(eid)

    def attr(self, eid: str, name: str):
        return self.w.states.get(eid, ("unknown", {}))[1].get(name)

    @property
    def notifications(self) -> dict:
        return self.w.notifications

    # --- the engine ------------------------------------------------------------------------------------------------------
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
        st, attrs, avail = None, {}, True
        try:
            avail = True if e.avail_tpl is None else S._truthy(native(self._render(e.avail_tpl).strip()))
            if avail:
                st = self._render(e.state_tpl).strip()
                attrs = {k: native(self._render(t).strip()) if isinstance(t, str) and ("{{" in t or "{%" in t) else t for k, t in e.attr_tpls.items()}
        except Exception as exc:  # noqa: BLE001 - a template error is a recorded finding, then `unknown`
            self.errors.append(f"{e.eid}: {type(exc).__name__}: {str(exc)[:120]}")
            st, attrs, avail = None, {}, True
        e.deps, e.uses_now = set(self._rec), self._now_used
        return st, attrs, avail

    def _refresh(self, e: _Ent) -> None:
        if e.dead:
            return
        st, attrs, avail = self._eval(e)
        e.avail = avail
        if avail:
            e.attrs = attrs
            if e.kind == "binary_sensor":
                e.value = None if st is None else S._truthy(native(st))
            else:
                e.state_txt = "unknown" if st is None else st
        self._publish(e)

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
        if len(shown) > 255:                                   # Home Assistant refuses a state longer than 255 characters (the state becomes unknown)
            self.errors.append(f"{e.eid}: state of {len(shown)} characters")
            shown = "unknown"
        attrs = {} if (e.override is not None or shown == "unavailable") else dict(e.attrs)
        attrs.update(_MARK)
        self.w.set(e.eid, shown, attrs)


# ---------------------------------------------------------------------------------------------------------------------------
# A house: the healthy dongle and plan, and the day it is in
# ---------------------------------------------------------------------------------------------------------------------------
def house(fw: FloorWorld, reserve=5, floors=(100, 5, 5, 5, 5, 5), sources=("Grid", "None", "None", "None", "None", "None"), shutdown=0, tou="on",
          feed: bool = True) -> dict | None:
    """Put the dongle and the plan in a healthy state: every flag off, every recovery state clear, the configuration online and published every 60 s. Returns the feed handle."""
    for e in FLAGS:
        fw.put(e, "off")
    fw.put(REC_FP, "NONE")
    fw.put(REC_DG, "NONE")
    fw.put(PLAN, str(reserve))
    fw.put(SHUT, str(shutdown))
    fw.put(TOU, tou)
    fw.put(ONLINE, "on")
    for n in range(6):
        fw.put(SOC[n], str(floors[n]))
        fw.put(SRC[n], sources[n])
    handle = fw.feed(CFGTIME, 60.0) if feed else None
    fw.force()
    return handle
