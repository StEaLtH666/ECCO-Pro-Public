"""A hand-written, standard-library stand-in for the Home Assistant modules the runtime boundary suite allows (L2 tests).

install() puts module objects into sys.modules for EXACTLY the allowlisted names (plus their parent packages, whose
__path__ is empty so no other homeassistant module can be imported): anything else the integration tried to import -
storage, restore_state, the entity or device registry helpers, update_coordinator - fails with ImportError.

Every write path is a recorded FAILURE (hass.write_attempts), and raises WriteAttempt:
  * hass.states.async_set / set / async_set_internal / async_remove / remove (a foreign state write);
  * hass.bus.async_fire / fire / async_fire_internal (an event fire);
  * any attribute of hass.services (a service call or registration);
  * hass.config_entries.async_update_entry / async_reload / async_remove / async_set_disabled_by / ... (entry mutation).
The only state writes allowed are an integration entity's own async_write_ha_state() (how a sensor publishes). Those are
checked too (hass.violations): on the event loop thread only, for an entity the integration's own platform added, JSON
serialisable, at most 16 KiB of attributes, an ENUM state among its options. statistics_during_period refuses to run on
the event loop thread.

The recorder view models Home Assistant's two tables. A write that changes the state or any attribute fires
state_changed and adds a `states` row (hass.recorder_rows: entity id, state and the attributes not listed in the entity's
unrecorded set, as the real recorder keeps them); a write that changes nothing only moves last_reported and adds no row.
A `state_attributes` row is added only for a set of recorded attributes not stored before (the recorder deduplicates
them by content, hass.recorder_attributes). Every write is logged with its time (hass.state_write_log: time, entity id,
whether it changed anything) and every states row too (hass.recorder_log: time, entity id, whether it added an
attributes row), so a test can measure state writes and recorder rows per hour.

helpers.event: async_track_time_interval (hass.timers, with the job name given; the harness fires it at every
Harness.tick() call, or at its own times under Harness.run_until), async_call_later (hass.later: a one-shot fired once at
or after its due time; its action a @callback or a core.HassJob whose target is one, as the pinned Core accepts) and
async_track_state_change_event (a state listener: a seeded state or attribute change of its entity calls it on the event
loop with a state_changed event, as Home Assistant does; a write that changes neither calls nothing; hass.states.events
False delivers no event at all, as the pre-A23 suites assume).

Tasks and executors as the pinned Core has them: hass.async_create_task and hass.async_create_background_task start a task
EAGERLY unless eager_start=False is passed (the Core's default is eager_start=True: the coroutine then runs inside the
calling callback up to its first suspension, when that callback runs on the event loop); every call is logged
(hass.task_log: name, eager_start). hass.async_add_import_executor_job runs its job in a separate one-thread import executor
(hass.import_jobs logs each job's target), and the platforms forwarded by async_forward_entry_setups are imported there
when not imported yet, as the Core's loader does (an integration's import_executor defaults to true).

This is a model of Home Assistant behaviour written for these tests, not Home Assistant: whatever it covers is L2 evidence
only (see docs/intelligence/INTELLIGENCE_HA_RUNTIME.md, "APIs covered only by the L2 fake").
"""

from __future__ import annotations

import asyncio
import enum
import importlib
import inspect
import json
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
ALLOWED_MODULES = (
    "homeassistant.core", "homeassistant.const", "homeassistant.config_entries", "homeassistant.exceptions",
    "homeassistant.components.sensor", "homeassistant.components.binary_sensor", "homeassistant.components.diagnostics",
    "homeassistant.components.recorder", "homeassistant.components.recorder.statistics", "homeassistant.helpers.event",
    "homeassistant.helpers.device_registry", "homeassistant.helpers.entity_platform", "homeassistant.helpers.typing",
    "homeassistant.util.dt",
)
PARENT_PACKAGES = ("homeassistant", "homeassistant.components", "homeassistant.helpers", "homeassistant.util")
MAX_ATTR_BYTES = 16 * 1024


class WriteAttempt(AssertionError):
    """The integration tried to write something it must never write."""


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)


CLOCK = Clock()


# ---------------------------------------------------------------------------------------------------------------------
# homeassistant.core
# ---------------------------------------------------------------------------------------------------------------------

def callback(func: Callable) -> Callable:
    func._hass_callback = True  # noqa: SLF001
    return func


class CoreState(enum.Enum):
    not_running = "NOT_RUNNING"
    starting = "STARTING"
    running = "RUNNING"
    stopping = "STOPPING"


class HassJobType(enum.Enum):
    Coroutinefunction = 1
    Callback = 2
    Executor = 3


class HassJob:
    """core.HassJob as the pinned Core defines it: a target, an optional name, the job type and the same repr."""

    def __init__(self, target: Callable, name: str | None = None, *, cancel_on_shutdown: bool | None = None,
                 job_type: HassJobType | None = None) -> None:
        self.target = target
        self.name = name
        self._cancel_on_shutdown = cancel_on_shutdown
        self._job_type = job_type

    @property
    def job_type(self) -> HassJobType:
        if self._job_type is None:
            if inspect.iscoroutinefunction(self.target):
                self._job_type = HassJobType.Coroutinefunction
            elif getattr(self.target, "_hass_callback", False):
                self._job_type = HassJobType.Callback
            else:
                self._job_type = HassJobType.Executor
        return self._job_type

    @property
    def cancel_on_shutdown(self) -> bool | None:
        return self._cancel_on_shutdown

    def __repr__(self) -> str:
        return f"<Job {self.name} {self.job_type} {self.target}>"


class State:
    def __init__(self, entity_id: str, state: str, attributes: Mapping | None = None, last_changed: datetime | None = None,
                 last_updated: datetime | None = None, last_reported: datetime | None = None) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = MappingProxyType(dict(attributes or {}))
        self.last_changed = last_changed or CLOCK.now
        self.last_updated = last_updated or self.last_changed
        self.last_reported = last_reported or self.last_updated
        self.domain = entity_id.split(".", 1)[0]


class Event:
    def __init__(self, event_type: str, data: Mapping | None = None) -> None:
        self.event_type = event_type
        self.data = dict(data or {})
        self.time_fired = CLOCK.now


class StateMachine:
    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass = hass
        self._states: dict[str, State] = {}
        # state_changed delivery to the listeners of helpers.event.async_track_state_change_event: Home Assistant calls
        # them for every write that changes the state or any attribute (never for one that only moves last_reported),
        # and for a removal (new_state None). `events` False models the harness setting the world between ticks with no
        # event at all (the pre-A23 suites, which pin the tick's own rules).
        self.events = True
        self._change_listeners: dict[str, list[Callable]] = {}

    def get(self, entity_id: str) -> State | None:
        self._hass._check_loop("hass.states.get")
        return self._states.get(entity_id)

    def async_all(self, domain: str | None = None) -> list[State]:
        return [s for s in self._states.values() if domain is None or s.domain == domain]

    def async_entity_ids(self, domain: str | None = None) -> list[str]:
        return [s.entity_id for s in self.async_all(domain)]

    # every state write by the integration is a failure
    def async_set(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.states.async_set", a)

    def set(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.states.set", a)

    def async_set_internal(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.states.async_set_internal", a)

    def async_remove(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.states.async_remove", a)

    def remove(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.states.remove", a)

    # the harness (test side) seeds foreign states with these; they are not integration writes
    def seed(self, entity_id: str, state: str, attributes: Mapping | None = None, *, changed_at: datetime | None = None,
             reported_at: datetime | None = None) -> State:
        old = self._states.get(entity_id)
        now = CLOCK.now
        if changed_at is None:
            changed_at = old.last_changed if (old is not None and old.state == state) else now
        st = State(entity_id, state, attributes, changed_at, max(changed_at, reported_at or changed_at),
                   reported_at or max(changed_at, now if old is not None and old.state == state else changed_at))
        self._states[entity_id] = st
        if old is None or old.state != st.state or dict(old.attributes) != dict(st.attributes):
            self._notify(entity_id, old, st)
        return st

    def unseed(self, entity_id: str) -> None:
        old = self._states.pop(entity_id, None)
        if old is not None:
            self._notify(entity_id, old, None)

    # helpers.event.async_track_state_change_event
    def _listen(self, entity_id: str, action: Callable) -> Callable[[], None]:
        lst = self._change_listeners.setdefault(entity_id, [])
        entry = (action,)
        lst.append(entry)

        def remove() -> None:
            if entry not in lst:
                self._hass.violations.append(f"the state listener on {entity_id} was removed twice")
                return
            lst.remove(entry)
        return remove

    def change_listeners(self) -> dict[str, int]:
        """{entity id: number of state listeners} for every entity that has one."""
        return {e: len(v) for e, v in self._change_listeners.items() if v}

    def _notify(self, entity_id: str, old: State | None, new: State | None) -> None:
        if not self.events:
            return
        for (action,) in list(self._change_listeners.get(entity_id, [])):
            self._hass._check_loop(f"state_changed listener on {entity_id}")
            try:
                action(Event("state_changed", {"entity_id": entity_id, "old_state": old, "new_state": new}))
            except Exception as exc:  # noqa: BLE001 - Home Assistant logs a raising listener; here it is a violation
                self._hass.violations.append(f"a state listener on {entity_id} raised {type(exc).__name__}: {exc}")

    def _entity_write(self, entity: "Entity", state: str, attributes: dict) -> None:
        hass = self._hass
        hass._check_loop(f"async_write_ha_state({entity.entity_id})")
        if entity.platform is None or entity not in entity.platform.entities:
            hass.violations.append(f"{entity.entity_id}: a state write by an entity no integration platform added")
            return
        try:
            blob = json.dumps(attributes, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            hass.violations.append(f"{entity.entity_id}: attributes are not JSON: {exc}")
            return
        if len(blob.encode("utf-8")) > MAX_ATTR_BYTES:
            hass.violations.append(f"{entity.entity_id}: attributes exceed {MAX_ATTR_BYTES} bytes")
        now = CLOCK.now
        old = self._states.get(entity.entity_id)
        changed = old is None or old.state != state
        updated = changed or dict(old.attributes) != attributes
        st = State(entity.entity_id, state, attributes, now if changed else old.last_changed,
                   now if updated else old.last_updated, now)
        self._states[entity.entity_id] = st
        hass.state_write_log.append((now, entity.entity_id, updated))
        if updated:                                  # state_changed: one states row; unchanged = last_reported only
            unrec = type(entity)._combined_unrecorded
            shared = {k: v for k, v in attributes.items() if k not in unrec}
            hass.recorder_rows.append((entity.entity_id, state, shared))
            key = json.dumps(shared, allow_nan=False, sort_keys=True)
            new_attrs = key not in hass.recorder_attributes
            if new_attrs:
                hass.recorder_attributes[key] = len(hass.recorder_attributes) + 1
            hass.recorder_log.append((now, entity.entity_id, new_attrs))
        hass.state_writes.append((entity.entity_id, state))

    def _entity_removed(self, entity_id: str) -> None:
        self._states.pop(entity_id, None)


class EventBus:
    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass = hass
        self._listeners: dict[str, list[tuple[Callable, bool]]] = {}

    def async_listen(self, event_type: str, listener: Callable) -> Callable[[], None]:
        return self._add(event_type, listener, False)

    def async_listen_once(self, event_type: str, listener: Callable) -> Callable[[], None]:
        return self._add(event_type, listener, True)

    def _add(self, event_type: str, listener: Callable, once: bool) -> Callable[[], None]:
        entry = (listener, once)
        self._listeners.setdefault(event_type, []).append(entry)

        def remove() -> None:
            lst = self._listeners.get(event_type, [])
            if entry not in lst:
                self._hass.violations.append(f"listener for {event_type} removed twice or after it fired")
                return
            lst.remove(entry)
        return remove

    def async_fire(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.bus.async_fire", a)

    def fire(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.bus.fire", a)

    def async_fire_internal(self, *a: Any, **k: Any) -> None:
        self._hass._write("hass.bus.async_fire_internal", a)

    def seed_fire(self, event_type: str) -> int:
        """The harness fires an event (Home Assistant's own, e.g. homeassistant_started)."""
        lst = list(self._listeners.get(event_type, []))
        for listener, once in lst:
            if once:
                self._listeners[event_type].remove((listener, once))
            listener(Event(event_type))
        return len(lst)

    def listener_count(self) -> int:
        return sum(len(v) for v in self._listeners.values())


class _WriteRecorder:
    """hass.services: any use at all is a recorded failure."""

    def __init__(self, hass: "HomeAssistant", name: str) -> None:
        self._hass, self._name = hass, name

    def __getattr__(self, attr: str) -> Callable:
        def fail(*a: Any, **k: Any) -> None:
            self._hass._write(f"{self._name}.{attr}", a)
        return fail


class Config:
    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir
        self.latitude = 51.5
        self.longitude = -0.1
        self.time_zone = "Europe/London"

    def path(self, *parts: str) -> str:
        import os
        return os.path.join(self.config_dir, *parts)


class HomeAssistant:
    def __init__(self, loop: asyncio.AbstractEventLoop, config_dir: str) -> None:
        self.loop = loop
        self._loop_thread = threading.get_ident()
        self.states = StateMachine(self)
        self.bus = EventBus(self)
        self.services = _WriteRecorder(self, "hass.services")
        self.config = Config(config_dir)
        self.config_entries = ConfigEntries(self)
        self.state = CoreState.running
        self.data: dict = {}
        self.write_attempts: list[tuple[str, str]] = []
        self.violations: list[str] = []
        self.recorder_rows: list[tuple] = []
        self.recorder_attributes: dict[str, int] = {}        # recorded-attributes JSON -> attributes row id (deduplicated)
        self.recorder_log: list[tuple] = []                  # (time, entity id, added an attributes row) per states row
        self.state_writes: list[tuple] = []
        self.state_write_log: list[tuple] = []               # (time, entity id, changed state or attributes) per write
        self.tasks: set[asyncio.Task] = set()
        self.task_log: list[tuple[str | None, bool]] = []   # (name, eager_start) of every task created
        self.timers: list[dict] = []
        self.later: list[dict] = []                          # helpers.event.async_call_later one-shot timers
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fake_ha_executor")
        self.import_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake_ha_import_executor")
        self.import_jobs: list[Callable] = []                # the target of every import executor job
        self.data["recorder_instance"] = Recorder(self)

    @property
    def is_running(self) -> bool:
        return self.state == CoreState.running

    def _write(self, what: str, detail: object) -> None:
        self.write_attempts.append((what, repr(detail)[:120]))
        raise WriteAttempt(what)

    def _check_loop(self, what: str) -> None:
        if threading.get_ident() != self._loop_thread:
            self.violations.append(f"{what} called off the event loop thread")

    def async_add_executor_job(self, target: Callable, *args: Any) -> asyncio.Future:
        self._check_loop("hass.async_add_executor_job")
        return self.loop.run_in_executor(self.executor, target, *args)

    def async_add_import_executor_job(self, target: Callable, *args: Any) -> asyncio.Future:
        self._check_loop("hass.async_add_import_executor_job")
        self.import_jobs.append(target)
        return self.loop.run_in_executor(self.import_executor, target, *args)

    def async_create_task(self, target: Any, name: str | None = None, eager_start: bool = True) -> asyncio.Task:
        """As the pinned Core: eager unless eager_start=False (a task created while the loop is not running starts at
        the loop's next step either way, as asyncio does)."""
        self._check_loop("hass.async_create_task")
        self.task_log.append((name, eager_start))
        if eager_start:
            task = asyncio.Task(target, loop=self.loop, name=name, eager_start=True)
            if task.done():
                return task
        else:
            task = self.loop.create_task(target, name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def async_create_background_task(self, target: Any, name: str, eager_start: bool = True) -> asyncio.Task:
        return self.async_create_task(target, name, eager_start)


# ---------------------------------------------------------------------------------------------------------------------
# homeassistant.config_entries / exceptions / const
# ---------------------------------------------------------------------------------------------------------------------

class HomeAssistantError(Exception):
    pass


class ConfigEntryError(HomeAssistantError):
    pass


class ConfigEntryNotReady(HomeAssistantError):
    pass


class ConfigEntryState(enum.Enum):
    NOT_LOADED = "not_loaded"
    LOADED = "loaded"
    SETUP_ERROR = "setup_error"


class ConfigEntry:
    _n = 0

    def __init__(self, domain: str, data: Mapping | None = None, title: str = "", options: Mapping | None = None) -> None:
        ConfigEntry._n += 1
        self.entry_id = f"fake_entry_{ConfigEntry._n}"
        self.domain = domain
        self.data = MappingProxyType(dict(data or {}))
        self.options = MappingProxyType(dict(options or {}))
        self.title = title
        self.state = ConfigEntryState.NOT_LOADED
        self.disabled_by = None
        self._on_unload: list[Callable] = []

    def async_on_unload(self, func: Callable) -> None:
        self._on_unload.append(func)


class ConfigEntries:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entries: dict[str, ConfigEntry] = {}
        self.platforms: dict[str, list["EntityPlatform"]] = {}

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        return [e for e in self._entries.values() if domain is None or e.domain == domain]

    def _add(self, entry: ConfigEntry) -> None:
        self._entries[entry.entry_id] = entry

    async def async_forward_entry_setups(self, entry: ConfigEntry, platforms: Any) -> None:
        for p in platforms:
            p = str(getattr(p, "value", p))
            if p not in ("sensor", "binary_sensor"):
                self._hass.violations.append(f"platform {p!r} forwarded")
                continue
            name = f"custom_components.{entry.domain}.{p}"
            if name in sys.modules:                  # the Core's loader: an imported platform comes from the cache
                mod = sys.modules[name]
            else:                                    # a new one is imported in the import executor
                mod = await self._hass.async_add_import_executor_job(importlib.import_module, name)
            plat = EntityPlatform(self._hass, entry, p)
            self.platforms.setdefault(entry.entry_id, []).append(plat)
            await mod.async_setup_entry(self._hass, entry, plat.add_entities)
            await plat.wait_added()

    async def async_unload_platforms(self, entry: ConfigEntry, platforms: Any) -> bool:
        for plat in self.platforms.pop(entry.entry_id, []):
            await plat.remove_all()
        return True

    def __getattr__(self, attr: str) -> Callable:
        if attr.startswith("async_") or attr in ("update_entry", "remove"):
            def fail(*a: Any, **k: Any) -> None:
                self._hass._write(f"hass.config_entries.{attr}", a)
            return fail
        raise AttributeError(attr)


FLOWS: dict[str, type] = {}


class ConfigFlow:
    VERSION = 1
    hass: HomeAssistant | None = None

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.handler = domain
            FLOWS[domain] = cls

    def _async_current_entries(self, include_ignore: bool | None = None) -> list[ConfigEntry]:
        return self.hass.config_entries.async_entries(self.handler) if self.hass is not None else []

    def async_abort(self, *, reason: str, description_placeholders: Mapping | None = None) -> dict:
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, *, title: str, data: Mapping, description: str | None = None, **kw: Any) -> dict:
        return {"type": "create_entry", "title": title, "data": dict(data)}

    def async_show_form(self, *, step_id: str, data_schema: Any = None, errors: Mapping | None = None, **kw: Any) -> dict:
        return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors}


class Platform(str, enum.Enum):
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"


# ---------------------------------------------------------------------------------------------------------------------
# entities: homeassistant.components.sensor / binary_sensor, helpers.entity_platform / device_registry
# ---------------------------------------------------------------------------------------------------------------------

class Entity:
    entity_id: str | None = None
    hass: HomeAssistant | None = None
    platform: "EntityPlatform | None" = None
    _attr_should_poll = True
    _attr_unique_id: str | None = None
    _attr_name: str | None = None
    _attr_device_info: Mapping | None = None
    _attr_has_entity_name = False
    _attr_device_class: Any = None
    _unrecorded_attributes: frozenset = frozenset()
    _entity_component_unrecorded_attributes: frozenset = frozenset()
    _combined_unrecorded: frozenset = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._combined_unrecorded = frozenset(cls._entity_component_unrecorded_attributes) | frozenset(cls._unrecorded_attributes)

    @property
    def unique_id(self) -> str | None:
        return self._attr_unique_id

    @property
    def name(self) -> str | None:
        return self._attr_name

    @property
    def should_poll(self) -> bool:
        return self._attr_should_poll

    @property
    def device_info(self) -> Mapping | None:
        return self._attr_device_info

    @property
    def device_class(self) -> Any:
        return self._attr_device_class

    @property
    def extra_state_attributes(self) -> Mapping | None:
        return None

    async def async_added_to_hass(self) -> None:
        return None

    async def async_will_remove_from_hass(self) -> None:
        return None

    def async_on_remove(self, func: Callable) -> None:
        self.__dict__.setdefault("_fake_on_remove", []).append(func)

    def _ha_state(self) -> str:
        raise NotImplementedError

    def _ha_attributes(self) -> dict:
        attrs: dict = {}
        if self.name is not None:
            attrs["friendly_name"] = self.name
        dc = self.device_class
        if dc is not None:
            attrs["device_class"] = str(getattr(dc, "value", dc))
        extra = self.extra_state_attributes
        if extra:
            attrs.update(extra)
        return attrs

    def async_write_ha_state(self) -> None:
        if self.hass is None:
            raise RuntimeError("async_write_ha_state before the entity was added")
        self.hass.states._entity_write(self, self._ha_state(), self._ha_attributes())  # noqa: SLF001


class SensorDeviceClass(str, enum.Enum):
    ENUM = "enum"
    ENERGY = "energy"
    BATTERY = "battery"


class SensorEntity(Entity):
    _attr_native_value: Any = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_options: list | None = None

    @property
    def native_value(self) -> Any:
        return self._attr_native_value

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._attr_native_unit_of_measurement

    @property
    def options(self) -> list | None:
        return self._attr_options

    def _ha_state(self) -> str:
        v = self.native_value
        if v is None:
            return "unknown"
        if self.device_class == SensorDeviceClass.ENUM:
            if v not in (self.options or []):
                self.hass.violations.append(f"{self.entity_id}: ENUM state {v!r} is not among its options")
            return str(v)
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            self.hass.violations.append(f"{self.entity_id}: state {v!r} is not a number or string")
        return str(v)

    def _ha_attributes(self) -> dict:
        attrs = super()._ha_attributes()
        if self.native_unit_of_measurement is not None:
            attrs["unit_of_measurement"] = self.native_unit_of_measurement
        if self.device_class == SensorDeviceClass.ENUM:
            attrs["options"] = list(self.options or [])
        return attrs


class BinarySensorEntity(Entity):
    _attr_is_on: bool | None = None

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on

    def _ha_state(self) -> str:
        v = self.is_on
        return "unknown" if v is None else ("on" if v else "off")


class DeviceEntryType(str, enum.Enum):
    SERVICE = "service"


class DeviceInfo(dict):
    pass


class EntityPlatform:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, domain: str) -> None:
        self.hass, self.entry, self.domain = hass, entry, domain
        self.entities: list[Entity] = []
        self._pending: list[asyncio.Task] = []

    def add_entities(self, new_entities: Any, update_before_add: bool = False) -> None:
        self._pending.append(self.hass.loop.create_task(self._add(list(new_entities))))

    async def wait_added(self) -> None:
        while self._pending:
            await self._pending.pop(0)

    async def _add(self, ents: list[Entity]) -> None:
        reg = self.hass.data.setdefault("_fake_entity_registry", {})
        for e in ents:
            if not isinstance(e, Entity):
                self.hass.violations.append(f"{e!r} is not an entity")
                continue
            if e.should_poll:
                self.hass.violations.append(f"{e.entity_id}: a polling entity")
            key = (self.domain, e.unique_id)
            want = e.entity_id or f"{self.domain}.unnamed"
            if not want.startswith(self.domain + "."):
                self.hass.violations.append(f"{want}: entity id outside its platform {self.domain}")
            if key in reg:
                eid = reg[key]
            else:
                eid, n = want, 2
                taken = set(self.hass.states._states) | set(reg.values())  # noqa: SLF001
                while eid in taken:
                    eid, n = f"{want}_{n}", n + 1
                reg[key] = eid
            e.entity_id = eid
            e.hass = self.hass
            e.platform = self
            self.entities.append(e)
            await e.async_added_to_hass()
            e.async_write_ha_state()

    async def remove_all(self) -> None:
        for e in list(self.entities):
            for f in e.__dict__.get("_fake_on_remove", []):
                f()
            await e.async_will_remove_from_hass()
            self.hass.states._entity_removed(e.entity_id)  # noqa: SLF001
            self.entities.remove(e)


AddEntitiesCallback = Callable[..., None]


# ---------------------------------------------------------------------------------------------------------------------
# recorder, diagnostics, event helpers, util.dt
# ---------------------------------------------------------------------------------------------------------------------

class Recorder:
    dialect_name = "sqlite"

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake_recorder")
        self.statistics: dict[str, list[dict]] = {}
        self.fail_with: BaseException | None = None
        self.calls = 0

    def async_add_executor_job(self, target: Callable, *args: Any) -> asyncio.Future:
        self._hass._check_loop("recorder.async_add_executor_job")  # noqa: SLF001
        return self._hass.loop.run_in_executor(self._executor, target, *args)


def get_instance(hass: HomeAssistant) -> Recorder:
    return hass.data["recorder_instance"]


def statistics_during_period(hass: HomeAssistant, start_time: datetime, end_time: datetime | None,
                             statistic_ids: set | None, period: str, units: Any, types_: set) -> dict:
    rec = get_instance(hass)
    if threading.get_ident() == hass._loop_thread:  # noqa: SLF001
        hass.violations.append("statistics_during_period called on the event loop thread")
    if period != "hour":
        hass.violations.append(f"statistics period {period!r}")
    rec.calls += 1
    if rec.fail_with is not None:
        raise rec.fail_with
    t0 = start_time.timestamp()
    t1 = end_time.timestamp() if end_time is not None else float("inf")
    out = {}
    for sid in sorted(statistic_ids or ()):
        rows = [dict({"start": r["start"]}, **{k: r.get(k) for k in types_})
                for r in rec.statistics.get(sid, []) if t0 <= r["start"] < t1]
        if rows:
            out[sid] = rows
    return out


def list_statistic_ids(hass: HomeAssistant, statistic_ids: Any = None, statistic_type: Any = None) -> list:
    return [{"statistic_id": s} for s in sorted(get_instance(hass).statistics)]


REDACTED = "**REDACTED**"


def async_redact_data(data: Any, to_redact: Any) -> Any:
    if isinstance(data, list):
        return [async_redact_data(v, to_redact) for v in data]
    if not isinstance(data, Mapping):
        return data
    out = dict(data)
    for k, v in out.items():
        if k in to_redact:
            out[k] = REDACTED
        elif isinstance(v, (Mapping, list)):
            out[k] = async_redact_data(v, to_redact)
    return out


def async_track_time_interval(hass: HomeAssistant, action: Callable, interval: timedelta, *, name: str | None = None,
                              cancel_on_shutdown: bool | None = None) -> Callable[[], None]:
    """An interval timer. The harness fires it: Harness.tick() at every call (the pre-A23 suites), Harness.run_until() at
    its own times (`next`: registration plus every interval, as Home Assistant does)."""
    hass._check_loop("async_track_time_interval")  # noqa: SLF001
    timer = {"action": action, "interval": interval, "active": True, "next": CLOCK.now + interval, "name": name}
    hass.timers.append(timer)

    def remove() -> None:
        if not timer["active"]:
            hass.violations.append("a timer was cancelled twice")
        timer["active"] = False
    return remove


def async_call_later(hass: HomeAssistant, delay: Any, action: Callable | HassJob) -> Callable[[], None]:
    """A one-shot timer `delay` (seconds or a timedelta) from now; the harness fires it once at or after that time with the
    fire time. `action` is a callable or a HassJob (the Core names an unnamed one 'call_later <delay>'). Its cancel
    callback may be called after it fired or more than once (as Home Assistant's)."""
    hass._check_loop("async_call_later")  # noqa: SLF001
    secs = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
    job = action if isinstance(action, HassJob) else HassJob(action, f"call_later {secs}")
    if job.job_type is not HassJobType.Callback:
        hass.violations.append("async_call_later with an action that is not a @callback")
    timer = {"action": job.target, "job": job, "name": job.name, "due": CLOCK.now + timedelta(seconds=max(secs, 0.0)),
             "active": True}
    hass.later.append(timer)

    def cancel() -> None:
        timer["active"] = False
    return cancel


def async_track_state_change_event(hass: HomeAssistant, entity_ids: Any, action: Callable,
                                   job_type: Any = None) -> Callable[[], None]:
    """A state listener: `action(event)` for every state_changed of the given entities (StateMachine._notify). Its remove
    callback may be called once (a second call is a violation)."""
    hass._check_loop("async_track_state_change_event")  # noqa: SLF001
    ids = [entity_ids] if isinstance(entity_ids, str) else list(entity_ids)
    if not ids or not all(isinstance(e, str) and e == e.lower() and "." in e for e in ids):
        hass.violations.append(f"async_track_state_change_event with entity ids {ids!r}")
    if not getattr(action, "_hass_callback", False):
        hass.violations.append("async_track_state_change_event with an action that is not a @callback")
    removers = [hass.states._listen(e, action) for e in ids]  # noqa: SLF001

    def remove() -> None:
        for r in removers:
            r()
    return remove


def utcnow() -> datetime:
    return CLOCK.now


def now(time_zone: Any = None) -> datetime:
    return CLOCK.now.astimezone(time_zone or LONDON)


def as_local(dt: datetime) -> datetime:
    return dt.astimezone(LONDON)


def as_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------------------------------------------------

def _module(name: str, attrs: Mapping[str, Any], package: bool = False) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    if package:
        m.__path__ = []                     # no submodule other than the ones installed here can be found
    m.__fake_ha__ = True
    return m


def install() -> dict[str, types.ModuleType]:
    """Register the fake modules (idempotent). Returns {name: module}."""
    if "homeassistant" in sys.modules and getattr(sys.modules["homeassistant"], "__fake_ha__", False):
        return {n: sys.modules[n] for n in PARENT_PACKAGES + ALLOWED_MODULES}
    if "homeassistant" in sys.modules:
        raise RuntimeError("a real homeassistant package is loaded: the L2 fake refuses to mix with it")
    mods = {
        "homeassistant": _module("homeassistant", {}, True),
        "homeassistant.components": _module("homeassistant.components", {}, True),
        "homeassistant.helpers": _module("homeassistant.helpers", {}, True),
        "homeassistant.util": _module("homeassistant.util", {}, True),
        "homeassistant.core": _module("homeassistant.core", {
            "HomeAssistant": HomeAssistant, "callback": callback, "CoreState": CoreState, "State": State, "Event": Event,
            "HassJob": HassJob, "HassJobType": HassJobType}),
        "homeassistant.const": _module("homeassistant.const", {
            "EVENT_HOMEASSISTANT_STARTED": "homeassistant_started", "__version__": "2026.10.4-fake",
            "REQUIRED_PYTHON_VER": (3, 13, 2), "STATE_ON": "on", "STATE_OFF": "off", "STATE_UNAVAILABLE": "unavailable",
            "STATE_UNKNOWN": "unknown", "Platform": Platform, "MAJOR_VERSION": 2026, "MINOR_VERSION": 10}),
        "homeassistant.config_entries": _module("homeassistant.config_entries", {
            "ConfigEntry": ConfigEntry, "ConfigFlow": ConfigFlow, "ConfigFlowResult": dict, "ConfigEntryState": ConfigEntryState}),
        "homeassistant.exceptions": _module("homeassistant.exceptions", {
            "HomeAssistantError": HomeAssistantError, "ConfigEntryError": ConfigEntryError,
            "ConfigEntryNotReady": ConfigEntryNotReady}),
        "homeassistant.components.sensor": _module("homeassistant.components.sensor", {
            "SensorEntity": SensorEntity, "SensorDeviceClass": SensorDeviceClass}),
        "homeassistant.components.binary_sensor": _module("homeassistant.components.binary_sensor", {
            "BinarySensorEntity": BinarySensorEntity}),
        "homeassistant.components.diagnostics": _module("homeassistant.components.diagnostics", {
            "async_redact_data": async_redact_data, "REDACTED": REDACTED}),
        "homeassistant.components.recorder": _module("homeassistant.components.recorder", {"get_instance": get_instance},
                                                     True),
        "homeassistant.components.recorder.statistics": _module("homeassistant.components.recorder.statistics", {
            "statistics_during_period": statistics_during_period, "list_statistic_ids": list_statistic_ids}),
        "homeassistant.helpers.event": _module("homeassistant.helpers.event", {
            "async_track_time_interval": async_track_time_interval, "async_call_later": async_call_later,
            "async_track_state_change_event": async_track_state_change_event}),
        "homeassistant.helpers.device_registry": _module("homeassistant.helpers.device_registry", {
            "DeviceInfo": DeviceInfo, "DeviceEntryType": DeviceEntryType}),
        "homeassistant.helpers.entity_platform": _module("homeassistant.helpers.entity_platform", {
            "AddEntitiesCallback": AddEntitiesCallback}),
        "homeassistant.helpers.typing": _module("homeassistant.helpers.typing", {"ConfigType": dict}),
        "homeassistant.util.dt": _module("homeassistant.util.dt", {
            "utcnow": utcnow, "now": now, "as_local": as_local, "as_utc": as_utc, "UTC": UTC, "DEFAULT_TIME_ZONE": LONDON}),
    }
    for name, m in mods.items():
        sys.modules[name] = m
        parent, _dot, child = name.rpartition(".")
        if parent:
            mods[parent].__dict__[child] = m
    return mods
