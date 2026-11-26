"""Discrete-time plant model for the dynamic-energy-control test bench: battery, inverter, house, solar and grid.

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. Not wired to Home Assistant, the dongle, the inverter or any register; stdlib
only; deterministic (a seeded generator is the only source of noise); it writes nothing outside its own return values.

THE SIMULATOR IS NOT THE INVERTER. Every parameter below carries a grade in PARAMETERS: MEASURED_REPLAY (computed from saved real
telemetry, aggregates only), VERIFIED_LIVE (observed in a recorded live test), ASSUMED (a placeholder with a stated reason) or
UNMEASURED (no data either way: the default is a documented choice and the flag says so). Where the real behaviour is UNMEASURED
(the charge response below the top rate, the taper at gentle rates, the off-grid effect of a lowered slot power, the unit of the
setpoint) the behaviour is a PARAMETER, so a scenario can run every alternative the control-authority study lists.

What is NOT in this file, and where it is: command delay and loss, telemetry staleness and gaps, a dongle restart or a dead dongle, a Home
Assistant outage, the untrusted-clock state and the one-owner arbiter are properties of the channels and of the two controllers' hosts, so
they live in bench.py (which owns the clocks and the queues and takes the kernel as a module); the plant only keeps what the world does to
the battery: the registers, the physics, the house, the sun and the grid.

The plant does NOT enforce any grid limit: the inverter did not protect the supply (12.46 kW of import was seen with nothing reducing the
charge), so an import ceiling and a Max Grid Export are limits ECCO enforces, configured in the bench (bench.Scenario.import_ceiling_w and
max_export_w; the import ceiling defaults to none) and judged by the invariants.

Sign conventions follow the firmware: battery power positive = discharge (register 190, DC side); grid positive = import (CT,
register 172); inverter AC power positive = output, negative = input (charging); PV is DC and never negative.
"""

import math
import random
from dataclasses import dataclass
from typing import Optional

DT_S = 15   # the step: the dongle's guard tick. Telemetry arrives once per step (the real cadence is 10 s; a coarser one is conservative).

# ---------------------------------------------------------------------------------------------------------------------------
# Parameter table: name, default, unit, grade, source. PlantParams must carry exactly these defaults (test_sim.py checks).
# ---------------------------------------------------------------------------------------------------------------------------
PARAMETERS = (
    # battery
    ("capacity_kwh", 35.0, "kWh", "MEASURED_REPLAY",
     "usable energy per 100 % of the SOC reading: DC energy over SOC points on four saved nights (34.7 to 35.2); a site value, override it"),
    ("soc_resolution_pct", 1.0, "%", "MEASURED_REPLAY", "the SOC reading steps in whole percent (2 % per 5 min at the plateau)"),
    ("soc_bias_pct", 0.0, "%", "ASSUMED", "sensor scale or offset error added to the true SOC; the planner allows 3 % scale error, the default is none"),
    ("charge_eff", 0.945, "DC per AC", "MEASURED_REPLAY", "0.94 to 0.95 W reaches the battery per W of AC drawn (four nights, power-balance fit)"),
    ("discharge_eff", 0.924, "AC per DC", "MEASURED_REPLAY", "AC delivered per DC drawn, power-balance fit over 32 497 samples"),
    ("standby_w", 50.0, "W", "MEASURED_REPLAY", "the fixed part of the discharge-side loss in the same fit"),
    # the charge characteristic at the top rate
    ("ac_input_cap_w", 8980.0, "W", "MEASURED_REPLAY",
     "the inverter's own AC input held constant at 8.982 to 8.987 kW on every saved night with the slot at 8000 W; what sets it is NOT ESTABLISHED"),
    ("knee_soc_pct", 98.0, "%", "MEASURED_REPLAY", "the plateau is flat to SOC 98 to 99 %, then the cliff (top rate only)"),
    ("cliff_width_pct", 0.85, "%", "MEASURED_REPLAY",
     "SOC span over which the power falls to the tail: 2.5 to 4.8 min at about 8.4 kW is about 0.3 kWh (0.85 %); the 30 to 50 min trickle at 0.6 kW then covers the last 1.15 %"),
    ("tail_dc_w", 600.0, "W", "MEASURED_REPLAY", "the trickle after the cliff: 0.55 to 0.65 kW for 30 to 50+ min (top rate)"),
    # the charge characteristic BELOW the top rate: UNMEASURED
    ("taper_below_top_measured", False, "flag", "UNMEASURED",
     "FLAG: no night was saved below the top rate, so the two gentle-rate values below are choices, not data"),
    ("knee_soc_gentle_pct", 98.0, "%", "UNMEASURED", "default = the top-rate figure carried over; the cell-voltage cliff may arrive later at a gentle rate"),
    ("tail_gentle_dc_w", 600.0, "W", "UNMEASURED", "default = the top-rate trickle carried over, capped by the commanded power"),
    ("charge_response", "scaled", "enum", "UNMEASURED",
     "what a slot power below 8000 W does to a charge: 'scaled' (H1: AC input = setpoint x unit_scale), 'unbound' (H2/H3: the setpoint does not bind, the AC input stays at its cap)"),
    ("charge_min_ac_w", None, "W", "UNMEASURED",
     "a floor under the AC input in 'scaled' mode (a charger that cannot throttle below this); None = no floor; a scenario sets one to give a WEAK response"),
    ("unit_scale", 1.1225, "AC per setpoint W", "UNMEASURED",
     "measured at ONE point only (8000 W gave 8.98 kW AC); alternatives the study lists: 1.0 (AC grid watts), 1.06 (DC battery watts), 1.1225 (the one point), 10x (a wrong unit)"),
    ("fp_dc_per_request", 0.94, "DC per request W", "MEASURED_REPLAY", "Free Power: the battery took about 0.94 of the register-230 request (one event, 11 Oct)"),
    # the discharge characteristic
    ("ac_output_cap_w", 7890.0, "W", "VERIFIED_LIVE", "the inverter delivered 7.89 kW AC at an 8000 W slot-power ceiling"),
    ("discharge_unit_scale", 1.0, "AC per setpoint W", "VERIFIED_LIVE", "a slot power is an AC-output ceiling, held from 500 to 7000 W"),
    ("shutdown_soc_pct", 10.0, "%", "ASSUMED", "the inverter's own last-resort low-SOC cutoff (registers 217 to 219 are read-only and site-specific); a placeholder"),
    ("ignore_ceiling_w", None, "W", "VERIFIED_LIVE", "fault injection: the 22 Sept 2026 anomaly, the battery discharged about 8.6 kW against a 1000 W ceiling (cause UNKNOWN); None = off"),
    # dynamics
    ("tau_charge_s", 5.0, "s", "MEASURED_REPLAY", "the battery reached 98 % of its plateau within 17 s of a verified Free Power start"),
    ("tau_discharge_s", 15.0, "s", "MEASURED_REPLAY", "telemetry needs about 45 s to settle after a slot-power change (the firmware's settle)"),
    # grid and house
    ("pv_eff", 0.97, "AC per DC", "ASSUMED", "PV DC to inverter AC; the firmware's feed-forward ignores it and the loop corrects"),
    ("island_ac_cap_w", 8000.0, "W", "ASSUMED", "the most AC the inverter can supply to the house off grid"),
    ("slot_caps_offgrid_discharge", False, "flag", "UNMEASURED",
     "UNKNOWN until proof rung R3: does a lowered slot power also cap the battery's supply to the house off grid? default no; a scenario sets yes"),
)


@dataclass(frozen=True)
class PlantParams:
    capacity_kwh: float = 35.0
    soc_resolution_pct: float = 1.0
    soc_bias_pct: float = 0.0
    charge_eff: float = 0.945
    discharge_eff: float = 0.924
    standby_w: float = 50.0
    ac_input_cap_w: float = 8980.0
    knee_soc_pct: float = 98.0
    cliff_width_pct: float = 0.85
    tail_dc_w: float = 600.0
    taper_below_top_measured: bool = False
    knee_soc_gentle_pct: float = 98.0
    tail_gentle_dc_w: float = 600.0
    charge_response: str = "scaled"
    charge_min_ac_w: Optional[float] = None
    unit_scale: float = 1.1225
    fp_dc_per_request: float = 0.94
    ac_output_cap_w: float = 7890.0
    discharge_unit_scale: float = 1.0
    shutdown_soc_pct: float = 10.0
    ignore_ceiling_w: Optional[float] = None
    tau_charge_s: float = 5.0
    tau_discharge_s: float = 15.0
    pv_eff: float = 0.97
    island_ac_cap_w: float = 8000.0
    slot_caps_offgrid_discharge: bool = False


# the alternatives the control-authority study lists for the unit of the charge setpoint (CONTROL_AUTHORITY.md section 4.2: H1, H2, H3)
UNIT_ALTERNATIVES = {
    "ac_grid_watts": {"unit_scale": 1.0, "charge_response": "scaled"},
    "dc_battery_watts": {"unit_scale": 1.0 / 0.945, "charge_response": "scaled"},
    "h1_measured_point": {"unit_scale": 1.1225, "charge_response": "scaled"},
    "h2_h3_unbound": {"unit_scale": 1.1225, "charge_response": "unbound"},
    "wrong_x10": {"unit_scale": 11.225, "charge_response": "scaled"},
    "wrong_div10": {"unit_scale": 0.11225, "charge_response": "scaled"},
}


class Series:
    """A time series of watts: step or linear points, plus rectangular spikes added on top. Deterministic."""

    def __init__(self, points, mode="step", spikes=()):
        self.points = tuple(sorted(points))
        self.mode = mode
        self.spikes = tuple(spikes)

    def at(self, t):
        pts = self.points
        if not pts:
            v = 0.0
        elif t <= pts[0][0]:
            v = pts[0][1]
        elif t >= pts[-1][0]:
            v = pts[-1][1]
        else:
            v = pts[0][1]
            for i in range(len(pts) - 1):
                (t0, v0), (t1, v1) = pts[i], pts[i + 1]
                if t0 <= t < t1:
                    v = v0 if self.mode == "step" else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
                    break
        for (s0, dur, extra) in self.spikes:
            if s0 <= t < s0 + dur:
                v += extra
        return max(0.0, v)


@dataclass
class Regs:
    """The four register groups the controllers write (the bench never writes a register outside this set)."""
    slot_power_w: float = 8000.0   # the charge slot's power (256-261 of the active slot)
    fp_rate_w: float = 0.0         # a Free Power override request, 0 = none (register 230 and the six powers)
    allow_export: bool = False     # register 244: True = Allow Export, False = Zero Export
    dump_ceiling_w: float = 0.0    # the battery discharge ceiling of a Dump lease, 0 = none

    def snapshot(self):
        return {"slot_power_w": self.slot_power_w, "fp_rate_w": self.fp_rate_w, "allow_export": self.allow_export,
                "dump_ceiling_w": self.dump_ceiling_w}

    def restore(self, snap):
        for k, v in snap.items():
            setattr(self, k, v)


@dataclass(frozen=True)
class Env:
    """What the world does in one step."""
    house_w: float
    pv_w: float
    grid_up: bool
    window_active: bool       # the owner's table has a charge window running (on the inverter's own clock)
    slot_target_pct: float    # the slot's own target SOC: the inverter ends the charge there


@dataclass(frozen=True)
class Meas:
    """The true state at the end of a step (before any telemetry channel touches it)."""
    t: float
    soc_true: float
    soc_reading: float
    batt_w: float         # DC, positive = discharge
    grid_w: float         # positive = import
    pv_w: float
    inv_ac_w: float       # positive = output, negative = input
    house_w: float
    mode: str
    unserved_w: float     # house load the plant could not supply (off grid)
    ac_in_w: float
    batt_ac_out_w: float


class Plant:
    def __init__(self, params, soc_pct, regs=None, seed=0):
        self.p = params
        self.e_kwh = max(0.0, min(params.capacity_kwh, soc_pct / 100.0 * params.capacity_kwh))
        self.regs = regs if regs is not None else Regs()
        self.rng = random.Random(seed)
        self.ac_in = 0.0
        self.ac_out = 0.0
        self.t = 0.0
        self.write_ignored = False

    # -- helpers --------------------------------------------------------------------------------------------------------
    def soc(self):
        return self.e_kwh / self.p.capacity_kwh * 100.0

    def reading(self):
        res = self.p.soc_resolution_pct
        v = self.soc() + self.p.soc_bias_pct
        return max(0.0, min(100.0, math.floor(v / res + 0.5) * res))

    def write_reg(self, name, value):
        """The register write path. Returns True when the register took the value (a fault can make the inverter ignore it)."""
        if self.write_ignored:
            return False
        setattr(self.regs, name, value)
        return True

    def read_reg(self, name):
        return getattr(self.regs, name)

    def _lag(self, state, target, tau, dt):
        a = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
        return state + (target - state) * a

    def _taper_dc(self, dc_demand, soc, top):
        p = self.p
        knee = p.knee_soc_pct if (top or p.taper_below_top_measured) else p.knee_soc_gentle_pct
        tail = min(p.tail_dc_w if top else p.tail_gentle_dc_w, dc_demand)
        if soc >= 100.0 - 1e-9:
            return 0.0
        if soc < knee:
            return dc_demand
        frac = (soc - knee) / p.cliff_width_pct
        if frac >= 1.0:
            return tail
        return dc_demand + (tail - dc_demand) * frac

    # -- the step -------------------------------------------------------------------------------------------------------
    def step(self, dt, env):
        p, r = self.p, self.regs
        soc = self.soc()
        house = env.house_w
        pv_ac = env.pv_w * p.pv_eff
        mode = "normal"
        ac_in_t = 0.0
        ac_out_t = 0.0
        if not env.grid_up:
            mode = "island"
        elif r.allow_export and (r.dump_ceiling_w > 0 or p.ignore_ceiling_w is not None):
            mode = "export"
        elif r.fp_rate_w > 0 and soc < 100.0 - 1e-9:
            mode = "free_power"
        elif env.window_active and r.slot_power_w > 0:
            # inside the owner's charge window the inverter charges to the slot's own target (acting on its own SOC reading) and then holds it:
            # the battery is idle and the grid carries the house
            mode = "slot_charge" if soc + p.soc_bias_pct < env.slot_target_pct - 1e-9 else "hold"
        top = False
        dc_in = 0.0
        dc_out = 0.0
        unserved = 0.0
        if mode == "slot_charge":
            if p.charge_response == "unbound":
                ac_in_t = p.ac_input_cap_w
            else:
                ac_in_t = min(p.ac_input_cap_w, max(r.slot_power_w * p.unit_scale, p.charge_min_ac_w or 0.0))
            top = ac_in_t >= 0.9 * p.ac_input_cap_w
        elif mode == "free_power":
            ac_in_t = min(p.ac_input_cap_w, r.fp_rate_w * p.fp_dc_per_request / p.charge_eff)
            top = ac_in_t >= 0.9 * p.ac_input_cap_w
        self.ac_in = self._lag(self.ac_in, ac_in_t, p.tau_charge_s, dt)
        if mode in ("slot_charge", "free_power"):
            dc_in = self._taper_dc(self.ac_in * p.charge_eff, soc, top)
            ac_in = dc_in / p.charge_eff
            self.ac_in = ac_in
            grid = house + ac_in - pv_ac
            inv_ac = -ac_in
            self.ac_out = 0.0
            batt_ac_out = 0.0
        elif mode == "hold":
            self.ac_in = 0.0
            self.ac_out = 0.0
            batt_ac_out = 0.0
            grid = max(0.0, house - pv_ac)
            inv_ac = min(pv_ac, house)
        elif mode == "export":
            ceiling = r.dump_ceiling_w if p.ignore_ceiling_w is None else p.ignore_ceiling_w
            ac_out_t = min(ceiling * p.discharge_unit_scale, p.ac_output_cap_w)
            if soc <= p.shutdown_soc_pct + 1e-9 or self.e_kwh <= 0.0:
                ac_out_t = 0.0
            self.ac_out = self._lag(self.ac_out, ac_out_t, p.tau_discharge_s, dt)
            batt_ac_out = self.ac_out
            dc_out = (batt_ac_out + p.standby_w) / p.discharge_eff if batt_ac_out > 0 else 0.0
            inv_ac = batt_ac_out + pv_ac
            grid = house - inv_ac
            self.ac_in = 0.0
        else:
            self.ac_in = 0.0
            cap = p.island_ac_cap_w if mode == "island" else p.ac_output_cap_w
            if mode == "island" and p.slot_caps_offgrid_discharge:
                cap = min(cap, r.slot_power_w)
            net = house - pv_ac
            if net >= 0:
                batt_ac_out = min(net, cap)
                if soc <= p.shutdown_soc_pct + 1e-9 or self.e_kwh <= 0.0:
                    batt_ac_out = 0.0
                unserved = net - batt_ac_out if mode == "island" else 0.0
                grid = (net - batt_ac_out) if mode == "normal" else 0.0
                dc_out = (batt_ac_out + p.standby_w) / p.discharge_eff if batt_ac_out > 0 else 0.0
            else:
                batt_ac_out = 0.0
                surplus = -net
                dc_in = min(surplus, p.ac_input_cap_w * p.charge_eff)
                if soc >= 100.0 - 1e-9:
                    dc_in = 0.0
                grid = 0.0
            self.ac_out = batt_ac_out
            inv_ac = batt_ac_out + pv_ac if batt_ac_out > 0 else min(pv_ac, house)
        self.e_kwh = max(0.0, min(p.capacity_kwh, self.e_kwh + (dc_in - dc_out) * dt / 3600.0 / 1000.0))
        self.t += dt
        batt_w = dc_out - dc_in
        return Meas(t=self.t, soc_true=self.soc(), soc_reading=self.reading(), batt_w=batt_w, grid_w=grid, pv_w=env.pv_w, inv_ac_w=inv_ac,
                    house_w=house, mode=mode, unserved_w=unserved, ac_in_w=max(0.0, -inv_ac) if mode in ("slot_charge", "free_power") else 0.0,
                    batt_ac_out_w=batt_ac_out)

    def noisy(self, value, sigma):
        if sigma <= 0 or value is None:
            return value
        return value + self.rng.gauss(0.0, sigma)


def parameter_table_md():
    """The MEASURED versus ASSUMED table, generated from PARAMETERS (SIM_README.md carries it verbatim; test_sim.py compares)."""
    lines = ["<!-- params:begin -->", "| Parameter | Default | Unit | Grade | Source |", "|---|---|---|---|---|"]
    for name, default, unit, grade, source in PARAMETERS:
        lines.append("| `%s` | %s | %s | %s | %s |" % (name, default, unit, grade, source.replace("|", "/")))
    lines.append("<!-- params:end -->")
    return "\n".join(lines)
