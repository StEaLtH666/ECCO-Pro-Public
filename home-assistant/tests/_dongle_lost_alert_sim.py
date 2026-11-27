"""Test support for the dongle-lost alert package (home-assistant/packages/ecco_dongle_lost_alert.yaml): ONE virtual Home Assistant that runs its two AUTOMATIONS on the
FPS1 interpreter (_ha_script_sim.HA), reused unchanged, over one virtual clock, with the three dongle entities the package reads.

What this module adds, and why:
  - a state trigger for an entity that did not exist before carries `from_state` none, as Home Assistant's does (the interpreter reads a missing old state as 'unknown'); the
    package's conditions are written for both, and the suite needs the first to prove it (the same adapter as the start gate suite);
  - the dongle's side: `lose()` makes entities unavailable one by one IN A CHOSEN ORDER (an ESPHome device's entities all read unavailable when its connection drops, in no fixed
    order), `back()` returns them, `restart()` stops the old automations (their countdowns die), makes the entities unavailable until they report again and starts a NEW instance,
    and `reload_automations()` replaces the instance without touching any state (an automation reload kills a countdown in progress).
Home Assistant's own behaviour is MODELLED as recalled, NOT verified on a real instance (the package header lists it). No network, no hardware, no write to anything: the model
supports only the persistent notification service and raises on any other (the interpreter is fail loud).
"""
from __future__ import annotations

import contextlib

import yaml

import _ha_script_sim as S

D = "ecco_clock_dongle"
FP = f"binary_sensor.{D}_free_power_active"
DG = f"binary_sensor.{D}_dump_to_grid_active"
TEL = f"binary_sensor.{D}_telemetry_online"
NOTE = "ecco_dongle_lost_in_lease"
ALL = (FP, DG, TEL)
START = 1795780800.0          # 2026-11-27 12:00:00 UTC (a whole minute: the minute ticks are on the minute)


class _AutomationFromNothing(S._Automation):
    def fire(self, trigger: dict):
        if trigger.get("platform") == "state" and trigger.get("entity_id") not in getattr(self, "_last_states", {}):
            trigger = dict(trigger, from_state=None)
        super().fire(trigger)


@contextlib.contextmanager
def _from_nothing():
    saved = S._Automation
    S._Automation = _AutomationFromNothing
    try:
        yield
    finally:
        S._Automation = saved


class AlertWorld:
    def __init__(self, package_text: str, fp: str = "off", dg: str = "off", tel: str = "on", t0: float = START, present: tuple = ALL):
        self.text = package_text
        self.pkg = yaml.safe_load(package_text)
        self.w = S.World(t0)
        for eid, st in ((FP, fp), (DG, dg), (TEL, tel)):
            if eid in present:
                self.w.set(eid, st)
        with _from_nothing():
            self.ha = S.HA(self.w, [self.pkg])
        self.ha.start()

    # --- the dongle's side ---------------------------------------------------------------------------------------------------
    def put(self, eid: str, state: str) -> None:
        self.w.set(eid, state)

    def lose(self, order=(FP, DG, TEL), to: str = "unavailable") -> None:
        """The dongle's entities go to `to` one by one in `order`."""
        for eid in order:
            self.w.set(eid, to)

    def back(self, states: dict, order=(TEL, FP, DG)) -> None:
        for eid in order:
            if eid in states:
                self.w.set(eid, states[eid])

    def restart(self, gone=ALL) -> None:
        """Home Assistant restarts: the old automations die with their countdowns, the entities in `gone` read unavailable until they report again, a NEW instance starts."""
        self.ha.stop()
        for eid in gone:
            self.w.set(eid, "unavailable")
        with _from_nothing():
            self.ha = S.HA(self.w, [self.pkg])
        self.ha.start()

    def reload_automations(self) -> None:
        """automation.reload: the instance is replaced, no state is touched and a countdown in progress dies."""
        self.ha.stop()
        with _from_nothing():
            self.ha = S.HA(self.w, [self.pkg])
        self.ha.start()

    # --- running and reading -------------------------------------------------------------------------------------------------
    def advance(self, seconds: float) -> None:
        self.w.run_until(self.w.t + seconds)

    def state(self, eid: str) -> str:
        return self.w.state(eid)

    @property
    def notifications(self) -> dict:
        return self.w.notifications

    def creates(self) -> int:
        return len([x for x in self.w.notification_log if x[1] == "create"])

    def services(self, since: int = 0) -> list:
        return [(s, e, d) for _t, s, e, d in self.w.service_log[since:]]
