"""Test support for the export coordinator (home-assistant/packages/ecco_export_coordinator.yaml): ONE virtual Home Assistant that runs the package's REAL template
entities, and an INDEPENDENT reference of the rules written from the specification (not from the templates), so a suite can run both on the same inputs.

The template entities run on the template model of the time trust suite (_time_trust_sim.TrustWorld: dependency tracking, a render at the start of every minute for a
template that uses now(), an availability template that is a super template, attributes parsed natively), on the FPS1 interpreter's state machine and Jinja environment
(_ha_script_sim.py). Both are reused unchanged. This module adds only what the coordinator needs and the older packages did not:

  - `this`: a template entity reads its own previous state (the re-target remembers its previous would-change through it). Home Assistant's behaviour is RECALLED, not
    verified: `this` is the entity's current state object (its state and attributes) once the entity has published, and nothing useful before that. The model offers three
    spellings so the template can be proved robust to each: "ha" (none before the first publish, then the state object), "none" (always none) and "undefined" (the name is not
    defined at all, as in a Home Assistant that does not offer it to template entities);
  - a zone-aware `timestamp_custom` filter (the interpreter's own is a fixed UTC+1);
  - the world builder: the healthy input set, the dongle's telemetry poll text with a chosen age, a Dump to Grid lease with the values the firmware latches.

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
STOP_D = f"number.{DONGLE}_dump_to_grid_stop_soc"
TGT = "input_number.ecco_dump_to_grid_schedule_power"
WIN = "input_number.ecco_dump_to_grid_schedule_duration"
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

# a healthy evening: the battery at 80 %, a 30 kWh pack, the owner's reserve 40 %, a 3000 W target, no PV, the house drawing 800 W
HEALTHY = {
    SOC: "80.0", LOAD: "800.0", PV: "0.0", GRID: "800.0", CAP: "30.0", HOLD: "clear", RESERVE: "40", STOP_S: "25.0", STOP_D: "25.0",
    TGT: "3000.0", WIN: "240.0", PCEIL: "6000.0", PROV: "6000.0", MX: "3600.0", LIM: "VALID", TEL: "on", LEASE: "off",
}
# the constants of the package header (the suite pins header and templates to these)
MAX_TELEMETRY_AGE_S = 90
DONGLE_STOP_SOC_MIN, DONGLE_STOP_SOC_MAX = 10, 90
DISCHARGE_EFFICIENCY = 0.92
SOC_MARGIN_POINTS = 1
MIN_COMMAND_W = 500
MIN_TARGET_W = 500
MIN_DURATION_MIN = 10
RETARGET_MIN_AGE_S = 1800
RETARGET_MIN_GAP_S = 1800
RETARGET_STOP_DEADBAND = 1
RETARGET_EXPORT_DEADBAND_W = 200
RETARGET_END_DEADBAND_MIN = 20
PHYSICAL_MAX_W = 30000
MODEL_MAX_AGE_S = 180


class ThisState:
    """What `this` is in a template entity: its own current state object."""

    def __init__(self, state: str, attrs: dict):
        self.state = state
        self.attributes = dict(attrs)


class ThisMixin:
    """`this` and a zone-aware `timestamp_custom` for any template-entity world (TrustWorld, or the adapter that runs on an existing World). `this_mode`: "ha", "none" or
    "undefined" (see the module docstring)."""

    this_mode = "ha"
    _this = None

    def _install_env(self) -> None:
        super()._install_env()
        zone = self.zone

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
        self._this = None if st is None else ThisState(st[0], {k: v for k, v in st[1].items() if k != "_model"})
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

    def __init__(self, package_text: str | None = None, *, start: str = START, zone: str = ZONE, this_mode: str = "ha", healthy: bool = True):
        if this_mode not in ("ha", "none", "undefined"):
            raise ValueError(this_mode)
        self.this_mode = this_mode
        self._this = None
        self.package_text = package_text if package_text is not None else (ROOT / PKG_REL).read_text(encoding="utf-8")
        super().__init__(self.package_text, start=start, zone=zone)
        if healthy:
            self.make_healthy()

    # --- the world ----------------------------------------------------------------------------------------------------------------
    def make_healthy(self, overrides: dict | None = None, poll_age: float | None = 0.0) -> None:
        for eid, st in {**HEALTHY, **(overrides or {})}.items():
            if st is None:
                self.put(eid, None)
            else:
                self.put(eid, st)
        if poll_age is not None:
            self.set_poll(poll_age)
        self.force()

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
        """A Dump to Grid lease is running with the values the firmware latches at its start. `age_min` makes the lease flag that old (its last_changed)."""
        self.put(L_STOP, str(stop))
        self.put(L_EXP, str(export))
        self.put(L_CMD, str(command))
        self.put(L_END, ends_text if ends_text is not None else self.local_text(self.now_ts() + (ends_in_min or 0) * 60.0))
        self.put(LEASE, "on")
        if age_min:
            self.age(LEASE, age_min * 60.0)
        else:
            self.force()

    def lease_off(self) -> None:
        self.put(LEASE, "off")
        for eid in (L_STOP, L_EXP, L_CMD):
            self.put(eid, "unknown")
        self.put(L_END, "Inactive")
        self.force()

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


def reference(raw: dict, *, poll_skew_s: float | None, capacity_attrs: tuple | None = None, held_by: str = "unknown") -> dict:
    """What the proposal must be for these raw readings (strings or None for a missing entity). `poll_skew_s` is Home Assistant's clock minus the poll text, in seconds (None: the
    text cannot be read as a time). `capacity_attrs` = (capacity_kwh, capacity_basis) of the battery runtime sensor. Returns the state, the blocking codes in their fixed order, the
    notes' codes and every number (None unless the state is VALID or UNVERIFIED)."""
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
    stop_d = num(raw.get(STOP_D), 0, 100)
    tgt = num(raw.get(TGT), 1, PHYSICAL_MAX_W)
    win = num(raw.get(WIN), 1, 240)
    pceil = num(raw.get(PCEIL), 500, PHYSICAL_MAX_W)
    prov = num(raw.get(PROV), 500, PHYSICAL_MAX_W)
    mx = num(raw.get(MX), 0, PHYSICAL_MAX_W)
    lim = raw.get(LIM) if raw.get(LIM) is not None else "unknown"
    tel = raw.get(TEL) if raw.get(TEL) is not None else "unknown"
    fresh = poll_skew_s is not None and abs(round(poll_skew_s)) <= MAX_TELEMETRY_AGE_S

    floor = None
    if stop_s is not None and stop_d is not None and reserve >= 0:
        floor = _ceil(max(stop_s, stop_d, reserve, DONGLE_STOP_SOC_MIN))
    nmax = None
    if mx is not None and mx > 0:
        nmax = math.floor((mx - max(100, 0.03 * mx)) / 100) * 100
    net = min(tgt, nmax) if (tgt is not None and nmax is not None) else None
    energy = None
    if soc is not None and floor is not None and cap is not None:
        energy = max(soc - floor - SOC_MARGIN_POINTS, 0) / 100 * cap * DISCHARGE_EFFICIENCY
    hi = min(pceil, prov) if (pceil is not None and prov is not None) else None
    raw_p = (net + load - pv) if (net is not None and load is not None and pv is not None) else None
    p = min(max(raw_p, 0), hi) if (raw_p is not None and hi is not None) else None
    p_eff = max(p, MIN_COMMAND_W) if p is not None else None
    dur_raw = (energy * 1000 / p_eff * 60) if (energy is not None and p_eff is not None) else None
    dur = math.floor(min(dur_raw, win)) if (dur_raw is not None and win is not None) else None

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
    for code, val in (("STOP_SOC_SCHEDULE_UNREADABLE", stop_s), ("STOP_SOC_STAGED_UNREADABLE", stop_d), ("SCHEDULE_POWER_UNREADABLE", tgt), ("SCHEDULE_DURATION_UNREADABLE", win),
                      ("CEILING_UNREADABLE", pceil), ("PROVEN_UNREADABLE", prov), ("EXPORT_LIMIT_UNREADABLE", mx)):
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
        if dur_raw > win:
            notes.append("DURATION_LIMITED_BY_WINDOW")
        if cap_m is not None and cap_m < cap_c:
            notes.append("CAPACITY_MEASURED")
    return {
        "state": state, "blocked_by": codes, "notes": notes,
        "floor": floor if numeric else None, "energy": energy if numeric else None, "power": p if numeric else None, "net": net if numeric else None,
        "duration": dur if numeric else None, "raw_power": raw_p if numeric else None, "dur_raw": dur_raw if numeric else None,
        "limited_by": ("PROVEN_LEVEL" if state == "UNVERIFIED" else ("POWER_CEILING" if (numeric and raw_p > pceil) else "")) if numeric else "",
        "parsed": {"soc": soc, "load": load, "pv": pv, "grid": grid, "cap": cap, "reserve": reserve, "stop_s": stop_s, "stop_d": stop_d, "tgt": tgt, "win": win, "pceil": pceil,
                   "prov": prov, "mx": mx},
    }


def reference_lease(prop: dict, *, lease: str, l_stop, l_exp, l_cmd, l_end_ts, l_start_ts, now_ts: float, prev_state: str | None, prev_entry: float | None,
                    mem_ok: bool = True) -> dict:
    """The comparison and the re-target for a proposal (from `reference`) and the lease's facts. `lease` is the raw state of the lease flag; `l_end_ts` and `l_start_ts` are epoch
    seconds or None; `prev_state` and `prev_entry` are the re-target's memory (its state and the entry time of its latest ALLOWED episode)."""
    numeric = prop["state"] in ("VALID", "UNVERIFIED")
    floor, net, p = prop["floor"], prop["net"], prop["power"]
    dur = prop["duration"]
    p_end = (now_ts + dur * 60) if (numeric and dur is not None) else None
    age = (now_ts - l_start_ts) if l_start_ts is not None else None
    d_stop = (floor - l_stop) if (numeric and l_stop is not None) else None
    d_exp = (net - l_exp) if (numeric and l_exp is not None) else None
    d_bat = (p - l_cmd) if (numeric and l_cmd is not None) else None
    d_end = ((p_end - l_end_ts) / 60) if (p_end is not None and l_end_ts is not None) else None
    dev_stop = d_stop is not None and abs(d_stop) >= RETARGET_STOP_DEADBAND
    dev_exp = d_exp is not None and abs(d_exp) >= RETARGET_EXPORT_DEADBAND_W
    dev_end = d_end is not None and d_end >= RETARGET_END_DEADBAND_MIN
    dev = dev_stop or dev_exp or dev_end
    on = lease == "on"
    complete = numeric and l_stop is not None and l_exp is not None and l_end_ts is not None
    if lease == "off":
        cmp_state = "NOT RUNNING"
    elif not on or not complete:
        cmp_state = "UNKNOWN"
    else:
        cmp_state = "DIFFERS" if dev else "IN LINE"
    cont = prev_state == "ALLOWED"
    recent = prev_entry is not None and not cont and (now_ts - prev_entry) < RETARGET_MIN_GAP_S
    if lease == "off":
        rt = "NOT RUNNING"
    elif not on or prop["state"] != "VALID" or not complete or age is None:
        rt = "UNKNOWN"
    elif not dev:
        rt = "NO CHANGE"
    elif age < RETARGET_MIN_AGE_S or recent or not mem_ok:
        rt = "WAIT"
    else:
        rt = "ALLOWED"
    entry = now_ts if (rt == "ALLOWED" and not cont) else prev_entry
    return {"cmp_state": cmp_state, "rt_state": rt, "rt_entry": entry, "dev_stop": dev_stop, "dev_exp": dev_exp, "dev_end": dev_end, "d_stop": d_stop, "d_exp": d_exp,
            "d_bat": d_bat, "d_end": d_end, "age": age, "p_end": p_end}
