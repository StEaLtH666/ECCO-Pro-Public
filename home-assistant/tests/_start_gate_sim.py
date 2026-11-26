"""Test support for the start gate and the lease guards (home-assistant/packages/ecco_start_gate.yaml and ecco_lease_guards.yaml): ONE virtual Home Assistant
that holds, on one state machine and one virtual clock,

  - the gate package's TEMPLATE entities (two template binary sensors with attributes), run by the template model of the time trust suite
    (_time_trust_sim.TrustWorld: dependency tracking, a render at the start of every minute for a template that uses now(), attributes);
  - its SCRIPT and the guards' AUTOMATIONS, run by the FPS1 interpreter (_ha_script_sim.HA) on the same World, so a script reads the gate sensors exactly as
    Home Assistant would (is_state / state_attr on the published state);
  - the dongle's Free Power model (_ha_script_sim.Dongle: the start gate, the staged numbers, the arm, the transaction) extended here with the END buttons, the Dump
    lease entities and a record of EVERY button press, so a suite can require that the guards press the two END buttons and nothing else.

It reuses the repository's three models unchanged and only adds: a subclass of the dongle model, an adapter that lets the template model run on an existing World
(a PlanWorld's, so the real plan helper package can feed the gate), and the world builder. Nothing here touches Home Assistant, a dongle or an inverter.

Home Assistant's own behaviour is MODELLED as recalled (not verified on a real instance): the trigger variables (`trigger.from_state`, `trigger.id`), `wait_template` with
`continue_on_timeout`, `mode: single` dropping a trigger while a run is busy, a button entity's state being the time of its last press, and a restart making every entity
unavailable until its integration reports again.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml

import _ha_script_sim as S
import _plan_sim as PL
import _time_trust_sim as T

DONGLE = "ecco_clock_dongle"
START = "2026-11-26 12:00:00"
ZONE = "Europe/London"

# The facts the gate reads (the repository's own entities)
TL = "binary_sensor.ecco_time_trusted_for_leases"
TS = "binary_sensor.ecco_time_trusted_for_ha_schedules"
TEL = f"binary_sensor.{DONGLE}_telemetry_online"
CFG = f"binary_sensor.{DONGLE}_configuration_online"
POLL = f"sensor.{DONGLE}_last_telemetry_update"
FP_ACTIVE = f"binary_sensor.{DONGLE}_free_power_active"
FP_OP = f"binary_sensor.{DONGLE}_free_power_operation_in_progress"
FP_SNAP = f"binary_sensor.{DONGLE}_free_power_snapshot_valid"
DG_ACTIVE = f"binary_sensor.{DONGLE}_dump_to_grid_active"
DG_OP = f"binary_sensor.{DONGLE}_dump_to_grid_operation_in_progress"
DG_SNAP = f"binary_sensor.{DONGLE}_dump_to_grid_snapshot_valid"
MANUAL = f"binary_sensor.{DONGLE}_manual_write_in_progress"
HOLD = "sensor.ecco_plan_export_hold"
EFF = "sensor.ecco_plan_effective_reserve"
STOP = f"number.{DONGLE}_dump_to_grid_stop_soc"
REV = "input_number.ecco_plan_revision"
CEIL = "input_number.ecco_grid_import_ceiling_w"
GRID = f"sensor.{DONGLE}_ecco_grid_power_ct_clamp"
REQ = f"number.{DONGLE}_free_power_max_charge_power"
DUR = f"number.{DONGLE}_free_power_duration"
ARM = f"switch.{DONGLE}_free_power_write_enable"
LIMIT = "sensor.ecco_config_maximum_grid_charge_power"
SCHED = "script.ecco_free_power_start_scheduled"
STATUS = f"sensor.{DONGLE}_free_power_status"
LATCHED = f"sensor.{DONGLE}_dump_to_grid_active_stop_soc"
START_FP = f"button.{DONGLE}_start_free_power_charge_now"
END_FP = f"button.{DONGLE}_end_free_power_restore_now"
START_DUMP = f"button.{DONGLE}_start_dump_to_grid_now"
END_DUMP = f"button.{DONGLE}_end_dump_to_grid_restore_now"
LAST = "input_text.ecco_plan_last_result"
CHARGE_GATE = "binary_sensor.ecco_charge_start_allowed"
EXPORT_GATE = "binary_sensor.ecco_export_start_allowed"
NOTE_START = "ecco_free_power_start_blocked"
NOTE_DUMP = "ecco_lease_guard_dump_ended"
NOTE_FP = "ecco_lease_guard_free_power_ended"

# every fact the gate reads, with its healthy value
HEALTHY = {
    TL: "on", TS: "on", TEL: "on", CFG: "on",
    FP_ACTIVE: "off", FP_OP: "off", FP_SNAP: "off", DG_ACTIVE: "off", DG_OP: "off", DG_SNAP: "off", MANUAL: "off",
    HOLD: "clear", EFF: "40", STOP: "40.0", REV: "12.0", GRID: "1500.0", LIMIT: "8000", SCHED: "off",
}


class _AutomationFromNothing(S._Automation):
    """The interpreter's automation, with one addition: a state trigger for an entity that did not exist before carries `from_state` none, as Home Assistant's does (the interpreter reads
    a missing old state as 'unknown'). The guards' conditions are written for both, and the suite needs the first to prove it."""

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


class _Adopt(T.TrustWorld):
    """The template model on an EXISTING World (a PlanWorld's): the same engine as TrustWorld, whose own constructor makes its World."""

    def __init__(self, world: S.World, zone: str, package_text: str):
        self.zone = ZoneInfo(zone)
        self.w = world
        self.errors = []
        self.pending = set()
        self.renders = {}
        self.rendered_at = {}
        self._tpl = {}
        self._rec = set()
        self._now_used = False
        self._busy = False
        self._again = False
        self._package_text = package_text
        self._install_env()
        self._wrap_set()
        self._build(None)
        self.w.listeners.append(self._on_world)
        self._settle("start")


class LeaseDongle(S.Dongle):
    """The Free Power model of the repository plus what the gate and the guards touch: the END buttons, a Dump lease (the active flag and the latched Stop SOC), a record of
    every button press and the timestamp a button entity shows after a press. The model's Modbus bus is quiet unless `bus_on` (a press is then refused when it lands in a busy window)."""

    def __init__(self, world: S.World, end_after: float = 20.0, **kw):
        super().__init__(world, **kw)
        self.end_after = end_after
        self.bus_on = False
        self.button_log: list[tuple[float, str]] = []
        self.dump_active = False
        for e, s in ((DG_OP, "off"), (LATCHED, "unknown"), (END_FP, "unknown"), (END_DUMP, "unknown"), (START_DUMP, "unknown"), (START_FP, "unknown")):
            world.set(e, s)
        world.service_handlers["button.press"] = self._press_any

    def bus_busy(self, t: float) -> bool:
        return self.bus_on and super().bus_busy(t)

    # --- buttons -------------------------------------------------------------------------------------------------------
    def _press_any(self, entity, data):
        self.button_log.append((self.w.t, entity))
        # Home Assistant's button entity: its state is the time of its last press (UTC, ISO 8601)
        self.w.set(entity, datetime.fromtimestamp(self.w.t + self.w.clock_offset, timezone.utc).isoformat())
        if entity == START_FP:
            return S.Dongle._press(self, entity, data)
        if entity == END_FP:
            self.w.after(self.end_after, self.fp_end)
        elif entity == END_DUMP:
            self.w.after(self.end_after, self.dump_end)
        # START_DUMP and any other button are only recorded: a suite requires that nothing but the two END buttons and the Free Power start is ever pressed

    def pressed(self, entity: str) -> list[float]:
        """The virtual times at which a button entity was pressed (the model's own `presses` list is the Free Power start gate's answers)."""
        return [t for t, e in self.button_log if e == entity]

    # --- a Free Power lease ----------------------------------------------------------------------------------------------
    def fp_start(self) -> None:
        """A Free Power lease is running (started by whatever: the model's own transaction is not run)."""
        self.active = True
        self.w.set(S.E_ACTIVE, "on")

    def fp_end(self) -> None:
        if self.active:
            self.active = False
            self.w.set(S.E_ACTIVE, "off")

    # --- a Dump lease --------------------------------------------------------------------------------------------------
    def dump_start(self, latched: float = 40.0, latched_delay: float = 0.0) -> None:
        """A Dump to Grid lease is running; its latched Stop SOC is published at once or `latched_delay` seconds later (the dongle's sensor updates every 5 s)."""
        self.dump_active = True
        self.w.set(S.E_DUMP_ACTIVE, "on")
        if latched_delay:
            self.w.after(latched_delay, lambda: self.w.set(LATCHED, f"{float(latched)}") if self.dump_active else None)
        else:
            self.w.set(LATCHED, f"{float(latched)}")

    def dump_end(self) -> None:
        if self.dump_active:
            self.dump_active = False
            self.w.set(S.E_DUMP_ACTIVE, "off")
            self.w.set(LATCHED, "unknown")


def package_parts(text: str) -> dict:
    """A package without its template block (the interpreter runs scripts, automations and helpers; the template model runs the templates)."""
    d = yaml.safe_load(text) or {}
    d.pop("template", None)
    return d


class GateWorld:
    """One virtual Home Assistant for the start gate and the lease guards. `plan_text` puts the REAL plan helper package on the same World (through a PlanWorld) so the
    export hold and the effective reserve are produced by their real templates; without it they are plain states the suite sets."""

    def __init__(self, gate_text: str, guards_text: str | None = None, *, plan_text: str | None = None, start: str = START, zone: str = ZONE,
                 healthy: bool = True, start_ha: bool = True, poll: bool = True, extra: tuple = ()):
        self.gate_text, self.guards_text, self.plan_text, self.zone = gate_text, guards_text, plan_text, zone
        self.pkgs = [package_parts(gate_text)] + ([package_parts(guards_text)] if guards_text else []) + [yaml.safe_load(t) for t in extra]
        if plan_text:
            with _from_nothing():
                self.pw = PL.PlanWorld(start, [yaml.safe_load(plan_text)] + self.pkgs, zone)
            self.w, self.ha = self.pw.w, self.pw.ha
            self.tw = _Adopt(self.w, zone, gate_text)
        else:
            self.pw = None
            self.tw = T.TrustWorld(gate_text, start=start, zone=zone)
            self.w = self.tw.w
            with _from_nothing():
                self.ha = S.HA(self.w, self.pkgs)
        self.d = LeaseDongle(self.w)
        if healthy:
            self.make_healthy()
        self.poll_feed = self.tw.feed(POLL, period=10.0) if poll else None
        if plan_text:
            self.sync()
        if start_ha:
            self.ha.start()

    # --- the facts -----------------------------------------------------------------------------------------------------
    def make_healthy(self) -> None:
        for eid, st in HEALTHY.items():
            if self.plan_text and eid in (HOLD, EFF, REV):
                continue                                       # produced by the real plan package
            self.tw.put(eid, st)
        self.d.power, self.d.duration = 4000, 60
        self.w.set(REQ, "4000.0")
        self.w.set(DUR, "60.0")
        self.sync()

    def put(self, eid: str, state, attrs: dict | None = None) -> None:
        self.tw.put(eid, state, attrs)

    def sync(self) -> None:
        """Render every template now (a template entity of another package changed without a state change the model sees)."""
        self.tw.force()

    def stop_poll(self) -> None:
        if self.poll_feed:
            self.poll_feed["on"] = False

    def poll_text(self, age_s: float) -> str:
        """The telemetry poll text of a poll made `age_s` seconds ago by the true clock."""
        return self.tw.local_text(self.w.t + self.w.clock_offset - age_s)

    # --- reading -----------------------------------------------------------------------------------------------------
    def state(self, eid: str) -> str:
        return self.w.state(eid)

    def attr(self, eid: str, name: str):
        return self.w.states.get(eid, ("unknown", {}))[1].get(name)

    def gate(self, eid: str):
        """(state, blocked_by, reasons) of a gate sensor as a consumer reads them."""
        return self.state(eid), self.attr(eid, "blocked_by"), self.attr(eid, "reasons")

    # --- running -------------------------------------------------------------------------------------------------------
    def advance(self, seconds: float) -> None:
        self.w.run_until(self.w.t + seconds)

    def script(self, name: str, data: dict | None = None, seconds: float = 200.0) -> bool:
        ok = self.ha.start_script(name, dict(data or {}))
        self.advance(seconds)
        return ok

    def services(self, since: int = 0) -> list[tuple[str, str, dict]]:
        return [(s, e, d) for _t, s, e, d in self.w.service_log[since:]]

    # --- a Home Assistant restart -----------------------------------------------------------------------------------------
    def restart_ha(self, *, gone: tuple = (), after: float = 0.0) -> None:
        """Home Assistant restarts: the old instance dies (no trigger, timer or step runs again), the entities in `gone` are unavailable until they report again, and a NEW
        instance (fresh automations) starts. The states of everything else are kept (helpers restore)."""
        self.ha.stop()
        for eid in gone:
            self.tw.put(eid, "unavailable")
        with _from_nothing():
            if self.pw is None:
                self.ha = S.HA(self.w, self.pkgs)
            else:
                self.ha = S.HA(self.w, [yaml.safe_load(self.plan_text)] + self.pkgs)
        self.ha.start()
        if after:
            self.advance(after)
