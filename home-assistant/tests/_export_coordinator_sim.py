"""Test support for the export coordinator (home-assistant/packages/ecco_export_coordinator.yaml): ONE virtual Home Assistant that runs the package's REAL template
entities, and an INDEPENDENT reference of the rules written from the specification (not from the templates), so a suite can run both on the same inputs.

The template entities run on the template model of the time trust suite (_time_trust_sim.TrustWorld: dependency tracking, a render at the start of every minute for a
template that uses now(), an availability template that is a super template, attributes parsed natively), on the FPS1 interpreter's state machine and Jinja environment
(_ha_script_sim.py). Both are reused unchanged. This module adds only what the coordinator needs and the older packages did not:

  - `this`: a template entity reads its own previous state (the re-target remembers its previous would-change, and since when it remembers, through it). Home Assistant's
    behaviour is RECALLED, not verified. The model offers four spellings so the template can be proved robust to each: "ha" (a state object ALWAYS: its state and attributes once
    the entity has published, and a state object with state unknown and NO attributes before that and after a template reload), "first-none" (none before the first publish,
    then the state object), "none" (always none) and "undefined" (the name is not defined at all, as in a Home Assistant that does not offer it to template entities);
  - a zone-aware `timestamp_custom` filter (the interpreter's own is a fixed UTC+1);
  - the world builder: the healthy input set, the dongle's telemetry poll text with a chosen age, a Dump to Grid lease with the values the firmware latches, the Export
    schedule's window and the time its start script last ran (a lease the SCHEDULE started), and a test hook that sets how old the re-target memory is.

Nothing here touches Home Assistant, a dongle or an inverter. There is no service, no action and no write: the model cannot call anything.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import _ha_script_sim as S
import _time_trust_sim as T

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PKG_REL = "home-assistant/packages/ecco_export_coordinator.yaml"

DONGLE = "ecco_clock_dongle"
ZONE = "Europe/London"
START = "2026-11-26 17:00:00"
FMT = "%Y-%m-%d %H:%M:%S"

# ---- the entities the package reads (the repository's own; the generic device slug) -------------------------------------------------------------------------------------
SOC = f"sensor.{DONGLE}_ecco_battery_soc"
LOAD = "sensor.ecco_house_power"
PV = f"sensor.{DONGLE}_ecco_pv_power"
GRID = f"sensor.{DONGLE}_ecco_grid_power_ct_clamp"
CAP = "input_number.ecco_battery_model_capacity"
CAPM = "sensor.ecco_battery_time_to_reserve"            # attributes capacity_kwh and capacity_basis
HOLD = "sensor.ecco_plan_export_hold"
RESERVE = "sensor.ecco_plan_effective_reserve"
STOP_S = "input_number.ecco_dump_to_grid_schedule_stop_soc"
STOP_D = f"number.{DONGLE}_dump_to_grid_stop_soc"       # the staged Stop SOC: NOT read by the package (a leftover of the last run); a suite sets it to prove that
TGT = "input_number.ecco_dump_to_grid_schedule_power"
WIN = "input_number.ecco_dump_to_grid_schedule_duration"
SCH_START = "input_datetime.ecco_dump_to_grid_schedule_start"
SCRIPT = "script.ecco_dump_to_grid_start_scheduled"     # attribute last_triggered
PCEIL = f"number.{DONGLE}_dump_to_grid_power_ceiling"
PROV = "input_number.ecco_dump_supervised_proven_w"
MX = f"number.{DONGLE}_dump_to_grid_max_grid_export"
LIM = "sensor.ecco_dump_limits_state"
TEL = f"binary_sensor.{DONGLE}_telemetry_online"
POLL = f"sensor.{DONGLE}_last_telemetry_update"
LEASE = f"binary_sensor.{DONGLE}_dump_to_grid_active"
L_STOP = f"sensor.{DONGLE}_dump_to_grid_active_stop_soc"
L_EXP = f"sensor.{DONGLE}_dump_to_grid_active_export_power"
L_CMD = f"sensor.{DONGLE}_dump_to_grid_commanded_battery_ceiling"
L_END = f"sensor.{DONGLE}_dump_to_grid_ends_at"

# the package's own entities
MODEL = "sensor.ecco_export_coordinator_model"
PROPOSAL = "sensor.ecco_export_proposal"
P_FLOOR = "sensor.ecco_export_proposal_floor"
P_ENERGY = "sensor.ecco_export_proposal_energy"
P_POWER = "sensor.ecco_export_proposal_power"
P_NET = "sensor.ecco_export_proposal_net_export"
P_DUR = "sensor.ecco_export_proposal_duration"
RETARGET = "sensor.ecco_export_retarget"
COMPARE = "sensor.ecco_export_shadow_comparison"
OWN = (MODEL, PROPOSAL, P_FLOOR, P_ENERGY, P_POWER, P_NET, P_DUR, RETARGET, COMPARE)
NUMERIC = (P_FLOOR, P_ENERGY, P_POWER, P_NET, P_DUR)

# a healthy evening: the battery at 80 %, a 30 kWh pack, the owner's reserve 40 %, a 3000 W target, no PV, the house drawing 800 W, the Export schedule's window starting in an hour (so
# no window limits the proposal yet). The dongle's staged Stop SOC (STOP_D) is deliberately not in it: the package does not read it.
HEALTHY = {
    SOC: "80.0", LOAD: "800.0", PV: "0.0", GRID: "800.0", CAP: "30.0", HOLD: "clear", RESERVE: "40", STOP_S: "25.0",
    TGT: "3000.0", WIN: "240.0", SCH_START: "2026-11-26 18:00:00", PCEIL: "6000.0", PROV: "6000.0", MX: "3600.0", LIM: "VALID", TEL: "on", LEASE: "off", L_STOP: "unknown",
}
# the constants of the package header (the suite pins header and templates to these)
MAX_TELEMETRY_AGE_S = 90
DONGLE_STOP_SOC_MIN, DONGLE_STOP_SOC_MAX = 10, 90
DISCHARGE_EFFICIENCY = 0.90
SOC_MARGIN_POINTS = 1
MIN_COMMAND_W = 500
MIN_TARGET_W = 500
MIN_DURATION_MIN = 10
INFEASIBLE_LOW_DEADBAND_W = 150
WINDOW_END_ROUNDING_S = 20
RETARGET_MIN_AGE_S = 1800
RETARGET_MIN_GAP_S = 1800
RETARGET_STOP_DEADBAND = 1
RETARGET_EXPORT_DEADBAND_W = 200
RETARGET_END_DEADBAND_MIN = 20
ORIGIN_RUN_WINDOW_S = 900
ORIGIN_RUN_TOLERANCE_S = 10
ORIGIN_WINDOW_START_TOLERANCE_S = 60
ORIGIN_WINDOW_END_TOLERANCE_S = 120
PHYSICAL_MAX_W = 30000
MODEL_MAX_AGE_S = 180
THIS_MODES = ("ha", "first-none", "none", "undefined")


class ThisState:
    """What `this` is in a template entity: its own current state object."""

    def __init__(self, state: str, attrs: dict):
        self.state = state
        self.attributes = dict(attrs)


class ThisMixin:
    """`this` and a zone-aware `timestamp_custom` for any template-entity world (TrustWorld, or the adapter that runs on an existing World). `this_mode`: "ha", "first-none", "none" or
    "undefined" (see the module docstring)."""

    this_mode = "ha"
    fold = 0                       # which of two equal local times a naive time is read as: 0 the first (the model of the repository), 1 the second (the other reading, which no package may depend on)
    _this = None

    def _install_env(self) -> None:
        super()._install_env()
        zone = self.zone
        if self.fold == 1:
            def as_ts(value, default=S._MISSING):
                try:
                    if isinstance(value, datetime):
                        dt = value
                    else:
                        dt = T.ha_parse_datetime(str(value))
                        if dt is None:
                            raise ValueError("not a valid date/time.")
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=zone, fold=1)
                    return dt.timestamp()
                except (TypeError, ValueError):
                    if default is S._MISSING:
                        raise S.SimError(f"as_timestamp could not parse {value!r} and no default was given")
                    return default
            self.w.env.globals["as_timestamp"] = as_ts

        def ts_custom(value, fmt=FMT, local=True, default=S._MISSING):
            try:
                return datetime.fromtimestamp(float(value), zone).strftime(fmt)
            except (TypeError, ValueError, OverflowError, OSError):
                if default is S._MISSING:
                    raise S.SimError(f"timestamp_custom could not convert {value!r} and no default was given")
                return default
        self.w.env.filters["timestamp_custom"] = ts_custom

    def _eval(self, e):
        st = self.w.states.get(e.eid)
        if st is None:
            # an entity that has not published (the first render, and the first render after a template reload, which removes the state): Home Assistant hands the template a state
            # object with state unknown and NO attributes (recalled); the older reading is none, and is kept as "first-none"
            self._this = None if self.this_mode == "first-none" else ThisState("unknown", {})
        else:
            self._this = ThisState(st[0], {k: v for k, v in st[1].items() if k != "_model"})
        state, attrs, avail = super()._eval(e)
        # Home Assistant parses a rendered `None` back to None (recalled: its result parser is ast.literal_eval and keeps a result that is not a string, a complex number or a bare
        # numeric word); the interpreter's own parser keeps the text "None" for it. An attribute that is exactly None is None here, as it is there.
        return state, {k: (None if v == "None" else v) for k, v in attrs.items()}, avail

    def _render(self, source: str) -> str:
        tpl = self._tpl.get(source)
        if tpl is None:
            env = self.w.env
            if source not in T._CODE:
                T._CODE[source] = env.compile(source)
            tpl = self._tpl[source] = env.template_class.from_code(env, T._CODE[source], env.make_globals(None), None)
        if self.this_mode == "undefined":
            return tpl.render()
        return tpl.render(this=None if self.this_mode == "none" else self._this)


class CoordWorld(ThisMixin, T.TrustWorld):
    """The package's template entities on one virtual Home Assistant, with `this`."""

    def __init__(self, package_text: str | None = None, *, start: str = START, zone: str = ZONE, this_mode: str = "ha", healthy: bool = True, fold: int = 0):
        if this_mode not in THIS_MODES or fold not in (0, 1):
            raise ValueError((this_mode, fold))
        self.this_mode = this_mode
        self.fold = fold
        self._this = None
        self.package_text = package_text if package_text is not None else (ROOT / PKG_REL).read_text(encoding="utf-8")
        super().__init__(self.package_text, start=start, zone=zone)
        if healthy:
            self.make_healthy()

    # --- the world ----------------------------------------------------------------------------------------------------------------
    def make_healthy(self, overrides: dict | None = None, poll_age: float | None = 0.0) -> None:
        """The healthy input set (with `overrides` on top; a None removes the entity) and a poll text `poll_age` seconds old (None leaves the poll alone), rendered once."""
        self.bulk({**HEALTHY, **(overrides or {})}, poll_age="keep" if poll_age is None else poll_age)

    def start_feed(self, period: float = 10.0) -> dict:
        """The dongle publishes the poll text every `period` seconds from now on (a healthy dongle). `stop_feed()` ends it (a dead one)."""
        self.stop_feed()
        self._feed = self.feed(POLL, period=period)
        return self._feed

    def stop_feed(self) -> None:
        if getattr(self, "_feed", None):
            self._feed["on"] = False

    def bulk(self, mapping: dict, *, poll_age: "float | None | str" = "keep", capm: "tuple | None | str" = "keep") -> None:
        """Set many entities and render ONCE (a poll that changes several readings together). A value of None removes the entity (it does not exist). `poll_age` sets the poll text
        (a number of seconds old, None removes it, "keep" leaves it); `capm` = (capacity_kwh, capacity_basis) of the battery runtime sensor (None removes it)."""
        saved = list(self.w.listeners)
        self.w.listeners[:] = [fn for fn in saved if getattr(fn, "__self__", None) is not self]
        try:
            for eid, st in mapping.items():
                if st is None:
                    self.w.states.pop(eid, None)
                    self.pending.add(eid)
                else:
                    self.w.set(eid, st, dict(T._MARK))
            if poll_age != "keep":
                self.set_poll(poll_age)
            if capm != "keep":
                if capm is None:
                    self.w.states.pop(CAPM, None)
                    self.pending.add(CAPM)
                else:
                    self.w.set(CAPM, "x", {"capacity_kwh": capm[0], "capacity_basis": capm[1]})
        finally:
            self.w.listeners[:] = saved
        self.force()

    def set_poll(self, age_s: float | None, text: str | None = None) -> None:
        """The dongle's last telemetry update text of a poll made `age_s` seconds ago by the true clock (or exactly `text`; None removes it)."""
        if age_s is None and text is None:
            self.put(POLL, None)
        else:
            self.put(POLL, text if text is not None else self.local_text(self.w.t + self.w.clock_offset - age_s))

    def now_ts(self) -> float:
        return self.w.t + self.w.clock_offset

    def lease_on(self, *, stop: float | str = 40.0, export: float | str = 3000.0, command: float | str = 3800.0, ends_in_min: float | None = 60.0,
                 ends_text: str | None = None, age_min: float = 0.0) -> None:
        """A Dump to Grid lease is running with the values the firmware latches at its start. `age_min` makes the lease flag that old (its last_changed). Nothing says who started it: the
        schedule's start script has not run (use sched_lease_on for a lease the schedule started)."""
        self.put(L_STOP, str(stop))
        self.put(L_EXP, str(export))
        self.put(L_CMD, str(command))
        self.put(L_END, ends_text if ends_text is not None else self.local_text(self.now_ts() + (ends_in_min or 0) * 60.0))
        self.put(LEASE, "on")
        if age_min:
            self.age(LEASE, age_min * 60.0)
        else:
            self.force()

    def script_ran(self, ts: float | None) -> None:
        """The Export schedule's start script (script.ecco_dump_to_grid_start_scheduled) last ran at the epoch `ts` (its `last_triggered` attribute, an ISO time with its offset; None: it never ran)."""
        iso = None if ts is None else datetime.fromtimestamp(ts, ZoneInfo(ZONE)).isoformat()
        self.put(SCRIPT, "off", {"last_triggered": iso})

    def schedule_window(self, start_ts: float, minutes: float | None = None) -> None:
        """The Export schedule's helpers: the window starts at the epoch `start_ts` (local text) and lasts `minutes` (the duration helper; None keeps it)."""
        self.put(SCH_START, self.local_text(start_ts))
        if minutes is not None:
            self.put(WIN, str(float(minutes)))

    def sched_lease_on(self, *, stop: float | str = 40.0, export: float | str = 3000.0, command: float | str = 3800.0, age_min: float = 45.0, window_min: float | None = None,
                       start_gap_s: float = 5.0, run_gap_s: float = 3.0, ends_in_min: float | None = None, ends_text: str | None = None, script: bool = True) -> None:
        """A lease the Export SCHEDULE started: the window (`window_min`, the duration helper) began `start_gap_s` before the lease flag turned on, `age_min` minutes ago; the start script
        last ran `run_gap_s` before the flag; the lease ends at the window end (a full-window lease) unless `ends_in_min` or `ends_text` say otherwise. `script=False` leaves the script out."""
        now = self.now_ts()
        lease_start = now - age_min * 60.0
        win = float(window_min) if window_min is not None else float(num(self.state(WIN), 1, 240) or 240.0)
        self.schedule_window(lease_start - start_gap_s, win)
        if script:
            self.script_ran(lease_start - run_gap_s)
        ends_in = ends_in_min if ends_in_min is not None else ((lease_start - start_gap_s + win * 60.0) - now) / 60.0
        self.lease_on(stop=stop, export=export, command=command, ends_in_min=ends_in, ends_text=ends_text, age_min=age_min)

    def lease_off(self) -> None:
        self.put(LEASE, "off")
        for eid in (L_STOP, L_EXP, L_CMD):
            self.put(eid, "unknown")
        self.put(L_END, "Inactive")
        self.force()

    def set_memory_age(self, seconds: float, *, eval_age: float = 0.0, rt_entry="keep", rt_state="keep") -> None:
        """A TEST HOOK: the re-target memory (the model's own previous attribute) has existed for `seconds`, its last evaluation was `eval_age` seconds ago, and optionally its previous
        would-change (`rt_entry`, an epoch or None) and previous re-target state (`rt_state`) are what is given: rewrites those keys of the published model (a sweep cannot advance the clock
        half an hour in every world; the real-time tests advance it). The next render reads it back through `this`."""
        st = self.w.states.get(MODEL)
        if st is None or not isinstance(st[1].get("model"), dict):
            raise AssertionError("the model has not published a dict yet")
        m = dict(st[1]["model"])
        m["mem_since_ts"] = math.floor(self.now_ts() - seconds)
        m["evaluated_ts"] = round(self.now_ts() - eval_age)
        if rt_entry != "keep":
            m["rt_entry"] = rt_entry
        if rt_state != "keep":
            m["rt_state"] = rt_state
        attrs = dict(st[1])
        attrs["model"] = m
        self.w.states[MODEL] = (st[0], attrs)

    def model(self) -> dict:
        m = self.attr(MODEL, "model")
        return m if isinstance(m, dict) else {}

    def snapshot(self) -> dict:
        """The state and attributes of every entity of the package, as a consumer reads them."""
        return {eid: (self.state(eid), {k: v for k, v in self.w.states.get(eid, ("unknown", {}))[1].items() if k != "_model"}) for eid in OWN}


# ===========================================================================================================================
# THE INDEPENDENT REFERENCE: the rules written from the specification, in Python, with no template in sight
# ===========================================================================================================================
def num(raw, lo: float, hi: float):
    """A reading as a number inside [lo, hi], or None: missing, unavailable, unknown, text, nan, infinite and out of range all give None."""
    if raw is None:
        return None
    try:
        x = float(str(raw).strip())
    except ValueError:
        return None
    if not math.isfinite(x) or x < lo or x > hi:
        return None
    return x


def _ceil(x: float) -> int:
    return int(math.ceil(x))


def schedule_start_ts(raw_text, zone: ZoneInfo | None = None):
    """The epoch of the Export schedule's start helper (the platform's own reading of a time text, as the schedule makes it), or None: missing, unknown, unavailable, none, empty or not a time."""
    if raw_text is None or str(raw_text) in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return T.ha_as_timestamp(str(raw_text), zone or ZoneInfo(ZONE))
    except (ValueError, TypeError, OverflowError):
        return None


def local_end_ts(text, zone: ZoneInfo | None = None):
    """The epoch of a local time text with no offset (the lease's end time), or None when the text cannot be read as ONE instant: not in the form, a SKIPPED local time (the hour that does not
    exist when the clocks go forward: neither reading gives back the text) or a REPEATED one (the second hour when they go back: the two readings are two instants)."""
    zone = zone or ZoneInfo(ZONE)
    try:
        naive = datetime.strptime(str(text), FMT)
    except (ValueError, TypeError):
        return None
    found = set()
    for fold in (0, 1):
        ts = naive.replace(tzinfo=zone, fold=fold).timestamp()
        if datetime.fromtimestamp(ts, zone).strftime(FMT) == str(text):
            found.add(ts)
    return found.pop() if len(found) == 1 else None


def lease_end_reading(l_end_text, now_ts: float, l_start_ts, zone: ZoneInfo | None = None):
    """The epoch of the running lease's end text, or None: not readable as ONE instant (see local_end_ts), or an end that lies before now or before the lease start (it cannot be right)."""
    if l_end_text in (None, "unknown", "unavailable", "none", ""):
        return None
    ts = local_end_ts(l_end_text, zone)
    if ts is not None and not (ts > now_ts and (l_start_ts is None or ts > l_start_ts)):
        return None
    return ts


def lease_origin(*, running: bool, w_start, w_end, l_start_ts, run_ts, l_end_ts) -> bool:
    """Did the Export SCHEDULE start the running lease? Inferred, not recorded: the scheduled start script last ran at most ORIGIN_RUN_WINDOW_S before the lease flag turned on (and at most
    ORIGIN_RUN_TOLERANCE_S after it), the lease turned on no earlier than ORIGIN_WINDOW_START_TOLERANCE_S before the window start, and it ends no later than ORIGIN_WINDOW_END_TOLERANCE_S after the
    window end."""
    since_run = (l_start_ts - run_ts) if (l_start_ts is not None and run_ts is not None) else None
    return bool(running and w_end is not None and since_run is not None and -ORIGIN_RUN_TOLERANCE_S <= since_run <= ORIGIN_RUN_WINDOW_S and l_start_ts >= w_start - ORIGIN_WINDOW_START_TOLERANCE_S
                and l_end_ts is not None and l_end_ts <= w_end + ORIGIN_WINDOW_END_TOLERANCE_S)


def reference(raw: dict, *, poll_skew_s: float | None, capacity_attrs: tuple | None = None, held_by: str = "unknown", now_ts: float | None = None, zone: ZoneInfo | None = None,
              lease: dict | None = None) -> dict:
    """What the proposal must be for these raw readings (strings or None for a missing entity). `poll_skew_s` is Home Assistant's clock minus the poll text, in seconds (None: the
    text cannot be read as a time). `capacity_attrs` = (capacity_kwh, capacity_basis) of the battery runtime sensor. `now_ts` is Home Assistant's clock (needed while the Export
    schedule's window is open and while a lease runs). `lease` = {"end_text", "start_ts", "run_ts"} (the raw end text of the lease, the epoch its flag last changed, the epoch the scheduled
    start script last ran; each may be None): what tells a lease the SCHEDULE started, whose end bounds the proposal; None says nothing is known of it (a running lease is then bounded by the
    window alone). Returns the state, the blocking codes in their fixed order, the notes' codes and every number (None unless the state is VALID or UNVERIFIED)."""
    codes: list[str] = []
    soc = num(raw.get(SOC), 0, 100)
    load = num(raw.get(LOAD), 0, PHYSICAL_MAX_W)
    pv = num(raw.get(PV), 0, PHYSICAL_MAX_W)
    grid = num(raw.get(GRID), -PHYSICAL_MAX_W, PHYSICAL_MAX_W)
    cap_c = num(raw.get(CAP), 1, 1000)
    cap_m = None
    if capacity_attrs is not None and capacity_attrs[1] == "measured":
        cap_m = num(capacity_attrs[0], 1, 1000)
    cap = min(cap_c, cap_m) if (cap_c is not None and cap_m is not None) else cap_c
    hold = raw.get(HOLD) if raw.get(HOLD) is not None else "unknown"
    # the reserve is split as the start gate and the schedule split it: -1 = cannot be read (text, missing, below 0), -2 = not a finite number from 0 to 100 (nan, infinity, above 100)
    try:
        rres = float(str(raw.get(RESERVE)).strip()) if raw.get(RESERVE) is not None else None
    except ValueError:
        rres = None
    if rres is None:
        reserve = -1
    elif rres != rres:
        reserve = -2
    elif 0 <= rres <= 100:
        reserve = rres
    elif rres < 0:
        reserve = -1
    else:
        reserve = -2
    stop_s = num(raw.get(STOP_S), 0, 100)
    tgt = num(raw.get(TGT), 1, PHYSICAL_MAX_W)
    win = num(raw.get(WIN), 1, 240)
    w_start = schedule_start_ts(raw.get(SCH_START), zone)
    w_end = (w_start + win * 60) if (w_start is not None and win is not None) else None
    in_win = w_end is not None and now_ts is not None and w_start <= now_ts < w_end
    wcap_w = math.floor((w_end - now_ts + WINDOW_END_ROUNDING_S) / 60) if in_win else None
    # a RUNNING lease: the same count at every render, to the end of the window it runs in (never below 0: after the window end it gets no time, however the next window starts), and for a lease
    # the SCHEDULE started to the smaller of that and the lease's own latched end (the window captured at its start: a helper edited while it runs cannot move it)
    running = raw.get(LEASE) == "on"
    l_end_ts, origin, run_end = None, False, w_end
    if running and lease is not None and now_ts is not None and w_end is not None:
        l_end_ts = lease_end_reading(lease.get("end_text"), now_ts, lease.get("start_ts"), zone)
        origin = lease_origin(running=True, w_start=w_start, w_end=w_end, l_start_ts=lease.get("start_ts"), run_ts=lease.get("run_ts"), l_end_ts=l_end_ts)
        if origin:
            run_end = min(w_end, l_end_ts)
    wcap_r = max(0, math.floor((run_end - now_ts + WINDOW_END_ROUNDING_S) / 60)) if (running and run_end is not None and now_ts is not None) else None
    wcap = wcap_r if wcap_r is not None else wcap_w
    pceil = num(raw.get(PCEIL), 500, PHYSICAL_MAX_W)
    prov = num(raw.get(PROV), 500, PHYSICAL_MAX_W)
    mx = num(raw.get(MX), 0, PHYSICAL_MAX_W)
    lim = raw.get(LIM) if raw.get(LIM) is not None else "unknown"
    tel = raw.get(TEL) if raw.get(TEL) is not None else "unknown"
    fresh = poll_skew_s is not None and abs(round(poll_skew_s)) <= MAX_TELEMETRY_AGE_S
    l_stop_v = num(raw.get(L_STOP), 0, 100)                     # the Stop SOC a RUNNING lease latched: a member of the floor, only while the lease runs

    floor = None
    if stop_s is not None and reserve >= 0:
        floor = _ceil(max(stop_s, reserve, DONGLE_STOP_SOC_MIN, l_stop_v if (running and l_stop_v is not None) else 0))
    nstart = (mx - max(100, 0.03 * mx)) if (mx is not None and mx > 0) else None
    nmax = math.floor(nstart / 100) * 100 if nstart is not None else None
    net = min(tgt, nmax) if (tgt is not None and nmax is not None) else None
    energy = None
    if soc is not None and floor is not None and cap is not None:
        energy = max(soc - floor - SOC_MARGIN_POINTS, 0) / 100 * cap * DISCHARGE_EFFICIENCY
    hi = min(pceil, prov) if (pceil is not None and prov is not None) else None
    raw_p = (net + load - pv) if (net is not None and load is not None and pv is not None) else None
    p = min(max(raw_p, 0), hi) if (raw_p is not None and hi is not None) else None
    p_eff = max(p, MIN_COMMAND_W) if p is not None else None
    lp = min(max(raw_p, 0), pceil) if (raw_p is not None and pceil is not None) else None       # what the dongle's own loop would command: no proven level
    lp_eff = max(lp, MIN_COMMAND_W) if lp is not None else None
    dlim = (min(win, wcap) if wcap is not None else win) if win is not None else None
    dur_raw = (energy * 1000 / p_eff * 60) if (energy is not None and p_eff is not None) else None
    dur = math.floor(min(dur_raw, dlim)) if (dur_raw is not None and dlim is not None) else None
    ldur_raw = (energy * 1000 / lp_eff * 60) if (energy is not None and lp_eff is not None) else None
    ldur = math.floor(min(ldur_raw, dlim)) if (ldur_raw is not None and dlim is not None) else None
    surplus = (pv - load) if (pv is not None and load is not None) else None

    if hold == "held":
        codes.append("OVERRIDE_ACTIVE")
    if hold not in ("held", "clear"):
        codes.append("OVERRIDE_UNREADABLE")
    if tel != "on":
        codes.append("TELEMETRY_OFFLINE")
    if not fresh:
        codes.append("TELEMETRY_STALE")
    for code, val in (("SOC_UNREADABLE", soc), ("HOUSE_LOAD_UNREADABLE", load), ("PV_UNREADABLE", pv), ("GRID_UNREADABLE", grid), ("CAPACITY_UNREADABLE", cap)):
        if val is None:
            codes.append(code)
    if reserve == -1:
        codes.append("RESERVE_UNKNOWN")
    if reserve == -2:
        codes.append("RESERVE_INVALID")
    for code, val in (("STOP_SOC_SCHEDULE_UNREADABLE", stop_s), ("LEASE_STOP_SOC_UNREADABLE", l_stop_v if running else 0), ("SCHEDULE_POWER_UNREADABLE", tgt),
                      ("SCHEDULE_DURATION_UNREADABLE", win), ("SCHEDULE_START_UNREADABLE", w_start), ("CEILING_UNREADABLE", pceil), ("PROVEN_UNREADABLE", prov), ("EXPORT_LIMIT_UNREADABLE", mx)):
        if val is None:
            codes.append(code)
    if mx is not None and mx <= 0:
        codes.append("EXPORT_LIMIT_NOT_CONFIGURED")
    if lim != "VALID":
        codes.append("LIMITS_NOT_VALID")
    if floor is not None and floor > DONGLE_STOP_SOC_MAX:
        codes.append("FLOOR_ABOVE_DONGLE_MAX")
    if net is not None and net < MIN_TARGET_W:
        codes.append("TARGET_BELOW_MINIMUM")
    if raw_p is not None and raw_p < -INFEASIBLE_LOW_DEADBAND_W:
        codes.append("TARGET_INFEASIBLE_LOW")
    if surplus is not None and nstart is not None and surplus + MIN_COMMAND_W > nstart:
        codes.append("PV_SURPLUS_EXPORT_GUARD")
    if energy is not None and energy <= 0:
        codes.append("NO_ENERGY_ABOVE_FLOOR")
    if dur is not None and energy > 0 and dur < MIN_DURATION_MIN:
        codes.append("BELOW_MINIMUM_DURATION")

    if "OVERRIDE_ACTIVE" in codes:
        state = "HOLD"
    elif codes:
        state = "INVALID"
    elif raw_p > prov and pceil > prov:
        state = "UNVERIFIED"
    else:
        state = "VALID"
    numeric = state in ("VALID", "UNVERIFIED")
    notes: list[str] = []
    if numeric:
        if tgt > net:
            notes.append("TARGET_LIMITED_BY_EXPORT_LIMIT")
        if raw_p < MIN_COMMAND_W:
            notes.append("LOW_BATTERY_POWER")
        if raw_p > pceil and pceil <= prov:
            notes.append("POWER_LIMITED_BY_CEILING")
        if dur_raw > dlim:
            notes.append("DURATION_LIMITED_BY_WINDOW")
        if cap_m is not None and cap_m < cap_c:
            notes.append("CAPACITY_MEASURED")
        if running and l_stop_v is not None and l_stop_v > max(stop_s, reserve, DONGLE_STOP_SOC_MIN):
            notes.append("FLOOR_FROM_RUNNING_LEASE")
    return {
        "state": state, "blocked_by": codes, "notes": notes,
        "floor": floor if numeric else None, "energy": energy if numeric else None, "power": p if numeric else None, "net": net if numeric else None,
        "duration": dur if numeric else None, "raw_power": raw_p if numeric else None, "dur_raw": dur_raw if numeric else None,
        "loop_power": lp if numeric else None, "loop_duration": ldur if numeric else None,
        "limited_by": ("PROVEN_LEVEL" if state == "UNVERIFIED" else ("POWER_CEILING" if (numeric and raw_p > pceil) else "")) if numeric else "",
        "window_end": w_end, "window_cap": wcap, "run_end": run_end if (running and origin) else None, "run_origin": origin, "run_end_ts": l_end_ts,
        "parsed": {"soc": soc, "load": load, "pv": pv, "grid": grid, "cap": cap, "reserve": reserve, "stop_s": stop_s, "tgt": tgt, "win": win, "pceil": pceil,
                   "prov": prov, "mx": mx, "hold": hold, "w_start": w_start, "w_end": w_end},
    }


def memory_age(mem_seconds, eval_age, mem_ok: bool) -> float:
    """How old the re-target memory reads at a render, given what the previous model attribute says (`mem_seconds` since when it remembers, `eval_age` seconds since its last evaluation) and
    whether `this` can be read at all. A memory that is not there, was not evaluated within the last MODEL_MAX_AGE_S (or is from the future by more than 5 s) starts afresh: age 0."""
    if not mem_ok or mem_seconds is None:
        return 0.0
    if -5 <= eval_age <= MODEL_MAX_AGE_S and mem_seconds >= -5:
        return float(mem_seconds)
    return 0.0


def reference_lease(prop: dict, *, lease: str, l_stop_raw, l_exp_raw, l_cmd_raw, l_end_text, l_start_ts, run_ts, now_ts: float, prev_state: str | None, prev_entry: float | None,
                    mem_age: float, mem_ok: bool = True, zone: ZoneInfo | None = None) -> dict:
    """The comparison and the re-target for a proposal (from `reference`) and the lease's raw facts. `lease` is the raw state of the lease flag; `l_end_text` the raw end text; `l_start_ts`
    the epoch the flag last changed and `run_ts` the epoch the Export schedule's start script last ran (each None when unknown); `prev_state` and `prev_entry` are the re-target's memory (its state
    and the entry time of its latest ALLOWED episode); `mem_age` is how old that memory reads in seconds (see memory_age) and `mem_ok` whether `this` can be read at all."""
    parsed = prop["parsed"]
    numeric = prop["state"] in ("VALID", "UNVERIFIED")
    floor, net, p, lp = prop["floor"], prop["net"], prop["power"], prop["loop_power"]
    l_stop, l_exp, l_cmd = num(l_stop_raw, 0, 100), num(l_exp_raw, 0, PHYSICAL_MAX_W), num(l_cmd_raw, 0, PHYSICAL_MAX_W)
    l_end_ts = lease_end_reading(l_end_text, now_ts, l_start_ts, zone)      # an end that lies before now or before the lease start cannot be right
    lp_end = (now_ts + prop["loop_duration"] * 60) if (numeric and prop["loop_duration"] is not None) else None
    age = (now_ts - l_start_ts) if l_start_ts is not None else None
    on = lease == "on"
    w_start, w_end = parsed["w_start"], parsed["w_end"]
    origin = lease_origin(running=on, w_start=w_start, w_end=w_end, l_start_ts=l_start_ts, run_ts=run_ts, l_end_ts=l_end_ts)
    cmp_ok = numeric and origin                                  # a difference against the schedule's numbers only for a lease the schedule started
    d_stop = (floor - l_stop) if (cmp_ok and l_stop is not None) else None
    d_exp = (net - l_exp) if (cmp_ok and l_exp is not None) else None
    d_bat = (p - l_cmd) if (cmp_ok and l_cmd is not None) else None
    d_loop = (lp - l_cmd) if (cmp_ok and l_cmd is not None) else None
    d_end = ((lp_end - l_end_ts) / 60) if (cmp_ok and lp_end is not None and l_end_ts is not None) else None
    dev_stop = d_stop is not None and d_stop >= RETARGET_STOP_DEADBAND         # the floor is never below the Stop SOC the running lease latched: a raise only
    dev_exp = d_exp is not None and abs(d_exp) >= RETARGET_EXPORT_DEADBAND_W
    dev_end = d_end is not None and d_end >= RETARGET_END_DEADBAND_MIN
    dev = dev_stop or dev_exp or dev_end
    reserve = parsed["reserve"]
    end_hold = on and parsed["hold"] == "held"
    end_res = bool(on and reserve >= 0 and l_stop is not None and reserve > l_stop)
    end_now = end_hold or end_res
    complete = numeric and l_stop is not None and l_exp is not None and l_end_ts is not None
    if lease == "off":
        cmp_state = "NOT RUNNING"
    elif not on or not complete or not origin:
        cmp_state = "UNKNOWN"
    else:
        cmp_state = "DIFFERS" if dev else "IN LINE"
    cont = prev_state == "ALLOWED"
    recent = prev_entry is not None and not cont and (now_ts - prev_entry) < RETARGET_MIN_GAP_S
    mem_young = mem_age < RETARGET_MIN_GAP_S
    if lease == "off":
        rt = "NOT RUNNING"
    elif not on:
        rt = "UNKNOWN"
    elif end_now:
        rt = "END NOW"
    elif prop["state"] != "VALID" or not complete or age is None or not origin:
        rt = "UNKNOWN"
    elif not dev:
        rt = "NO CHANGE"
    elif age < RETARGET_MIN_AGE_S or recent or mem_young:
        rt = "WAIT"
    else:
        rt = "ALLOWED"
    entry = now_ts if (rt == "ALLOWED" and not cont) else prev_entry
    codes: list[str] = []
    if lease not in ("on", "off"):
        codes.append("LEASE_UNREADABLE")
    if rt == "END NOW" and end_hold:
        codes.append("HOLD_ACTIVE")
    if rt == "END NOW" and end_res:
        codes.append("RESERVE_ABOVE_LEASE_STOP_SOC")
    if rt == "UNKNOWN" and on and prop["state"] != "VALID":
        codes.append("PROPOSAL_NOT_VALID")
    if rt == "UNKNOWN" and on and prop["state"] == "VALID" and not complete:
        codes.append("LEASE_FACTS_UNREADABLE")
    if rt == "UNKNOWN" and on and prop["state"] == "VALID" and complete and age is None:
        codes.append("LEASE_START_UNKNOWN")
    if rt == "UNKNOWN" and on and prop["state"] == "VALID" and complete and age is not None and not origin:
        codes.append("LEASE_ORIGIN_UNKNOWN")
    if rt == "WAIT" and age < 0:
        codes.append("CLOCK_BACKWARDS")
    if rt == "WAIT" and 0 <= age < RETARGET_MIN_AGE_S:
        codes.append("LEASE_TOO_YOUNG")
    if rt == "WAIT" and recent:
        codes.append("RECENT_CHANGE")
    if rt == "WAIT" and not mem_ok:
        codes.append("MEMORY_UNAVAILABLE")
    if rt == "WAIT" and mem_ok and mem_young:
        codes.append("MEMORY_YOUNG")
    wait_until = None
    if rt == "WAIT":
        wait_until = max([(l_start_ts + RETARGET_MIN_AGE_S) if (age is not None and age < RETARGET_MIN_AGE_S) else 0,
                          (prev_entry + RETARGET_MIN_GAP_S) if recent else 0,
                          (math.floor(now_ts - mem_age) + RETARGET_MIN_GAP_S) if mem_young else 0])
    changes: list[str] = []
    if rt in ("WAIT", "ALLOWED", "END NOW"):
        if dev_stop:
            changes.append("STOP_SOC")
        if dev_exp:
            changes.append("EXPORT_TARGET")
        if dev_end:
            changes.append("END")
    return {"cmp_state": cmp_state, "rt_state": rt, "rt_entry": entry, "dev_stop": dev_stop, "dev_exp": dev_exp, "dev_end": dev_end, "d_stop": d_stop, "d_exp": d_exp,
            "d_bat": d_bat, "d_loop": d_loop, "d_end": d_end, "age": age, "lp_end": lp_end, "origin": origin, "end_now": end_now, "end_hold": end_hold, "end_res": end_res,
            "l_end_ts": l_end_ts, "complete": complete, "recent": recent, "mem_young": mem_young, "codes": codes, "wait_until": wait_until, "changes": changes,
            "mem_since": math.floor(now_ts - mem_age), "lease_origin": (("SCHEDULE" if origin else "OTHER") if on else "")}
