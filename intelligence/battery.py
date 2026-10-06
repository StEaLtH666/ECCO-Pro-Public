"""Hourly battery state-of-charge simulation (pure arithmetic, no control).

All SOC maths is in percent of the configured capacity. Energy at the load
(AC side) is converted to battery energy with a one-way efficiency of
sqrt(round-trip). The simulation answers "what would SOC do if load and PV
were these", never "what should the inverter do".

Two ways of keeping the floor are reported side by side:
* `min_soc_unconstrained` - where SOC would go if nothing intervened;
* `import_to_hold_floor_kwh` - the grid/peak energy needed so SOC never drops
  below the floor (the inverter, not this module, decides what really happens).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .config import SiteConfig
from .timeutil import HOUR, overlap_seconds, ts, utc_from_ts


@dataclass
class Step:
    t0: datetime
    t1: datetime
    load_kwh: float                    # AC-side energy consumed by the house in this step
    pv_kwh: float                      # PV energy produced in this step
    charge_cap_kwh: float = 0.0        # grid energy that may be taken into the battery in this step (cheap window)


@dataclass
class SimPoint:
    t: datetime
    soc: float                         # unconstrained SOC at the END of the step
    imp_cum: float = 0.0               # cumulative grid energy needed to hold the floor, up to the END of the step


@dataclass
class SimResult:
    points: list[SimPoint]
    min_soc_unconstrained: float
    min_soc_time: datetime
    import_to_hold_floor_kwh: float
    grid_charge_kwh: float
    pv_overflow_kwh: float             # PV that could not be stored (battery full)
    final_soc: float
    time_to_floor: datetime | None     # first time unconstrained SOC <= floor
    floor: float = 0.0

    def import_by(self, t: datetime) -> float:
        """Cumulative floor-holding grid energy needed up to time t (end of the last step not after t)."""
        out = 0.0
        for p in self.points:
            if p.t <= t:
                out = p.imp_cum
            else:
                break
        return out

    def soc_at(self, t: datetime) -> float | None:
        prev = None
        for p in self.points:
            if p.t >= t:
                return p.soc if prev is None else prev.soc + (p.soc - prev.soc) * (
                    (t - prev.t).total_seconds() / max(1.0, (p.t - prev.t).total_seconds()))
            prev = p
        return self.points[-1].soc if self.points else None


def eta_one_way(cfg: SiteConfig) -> float:
    return math.sqrt(max(0.01, min(1.0, cfg.round_trip_efficiency)))


def build_steps(start: datetime, end: datetime, load_slot: callable, pv_slot: callable,
                charge_windows: list[tuple[datetime, datetime]] | None = None,
                max_grid_charge_kw: float = 8.0) -> list[Step]:
    """Steps covering [start, end), split at every UTC hour boundary AND at every charging-window edge, so a
    00:30-05:30 window is never widened to whole hours. `load_slot(hour_start_utc)` / `pv_slot(hour_start_utc)`
    return the energy of the FULL hour; each step takes its time-share of that hour."""
    cuts = {ts(start), ts(end)}
    s = ts(start) - (ts(start) % HOUR) + HOUR
    while s < ts(end):
        cuts.add(s)
        s += HOUR
    for w0, w1 in charge_windows or []:
        for edge in (ts(w0), ts(w1)):
            if ts(start) < edge < ts(end):
                cuts.add(edge)
    pts = sorted(cuts)
    steps: list[Step] = []
    for c0, c1 in zip(pts, pts[1:]):
        a, b = utc_from_ts(c0), utc_from_ts(c1)
        h0 = utc_from_ts(c0 - (c0 % HOUR))
        frac = (c1 - c0) / HOUR
        cc = 0.0
        for w0, w1 in charge_windows or []:
            cc += overlap_seconds(a, b, w0, w1) / HOUR * max_grid_charge_kw
        steps.append(Step(a, b, load_slot(h0) * frac, pv_slot(h0) * frac, cc))
    return steps


def _advance(soc: float, st: Step, cfg: SiteConfig, eta: float, charge_target_pct: float | None,
             floor_pct: float | None) -> tuple[float, float, float, float]:
    """One step. Returns (soc_after, grid_charge_kwh, pv_overflow_kwh, import_to_hold_floor_kwh).
    `floor_pct=None` leaves SOC unclamped (the unconstrained track).

    Inside a charging step (cheap window with a target set):
      * below the target: the grid supplies the house load and charges the battery toward the target;
      * at or above the target: the battery is allowed to cover the house DOWN TO the target (the slot SOC acting as
        a per-slot floor), after which the grid carries it. How the real inverter slot behaves above its SOC setting
        is UNVERIFIED (docs/DUMP_TO_GRID_V1.md lists the effect of slot SOC on discharge as unknown), so the
        simulation takes the more cautious reading: SOC falls to the target rather than being held where it was.
    Outside a charging step the battery covers any deficit and absorbs any PV surplus."""
    cap = cfg.battery_capacity_kwh
    gchg = 0.0
    overflow = 0.0
    imp = 0.0
    charging_step = charge_target_pct is not None and st.charge_cap_kwh > 0
    if charging_step and soc < charge_target_pct:
        load_from_grid = st.load_kwh                      # grid carries the house while it charges
        net = st.pv_kwh                                   # only PV can still reach the battery
        want_kwh = (charge_target_pct - soc) / 100.0 * cap / eta
        take = max(0.0, min(want_kwh, st.charge_cap_kwh - load_from_grid))
        soc += take * eta / cap * 100.0
        gchg = take
    else:
        net = st.pv_kwh - st.load_kwh                     # +ve surplus, -ve deficit (AC side)
    if net >= 0:
        d = net * eta / cap * 100.0
        room = max(0.0, cfg.max_soc_pct - soc)
        if d > room:
            overflow = (d - room) / 100.0 * cap / eta
            d = room
        soc += d
    else:
        soc += net / eta / cap * 100.0
        if charging_step and soc < charge_target_pct:
            soc = charge_target_pct                      # grid covers what the slot floor will not
        if floor_pct is not None and soc < floor_pct:
            imp = (floor_pct - soc) / 100.0 * cap * eta
            soc = floor_pct
    return soc, gchg, overflow, imp


def simulate(soc0: float, steps: list[Step], cfg: SiteConfig, floor_pct: float,
             charge_target_pct: float | None = None) -> SimResult:
    """Run the hourly SOC model twice: an unconstrained track (what SOC would do) and a floor-holding track
    (how much grid energy it would take to never drop below the floor). If `charge_target_pct` is given,
    grid charging up to that SOC is applied in steps that carry a `charge_cap_kwh` (the cheap window)."""
    eta = eta_one_way(cfg)
    soc_u = soc0
    soc_c = soc0
    pts: list[SimPoint] = []
    min_u = soc0
    min_t = steps[0].t0 if steps else utc_from_ts(0)
    imp_total = 0.0
    gchg_total = 0.0
    overflow_total = 0.0
    t_floor = None
    for st in steps:
        soc_u, g, o, _ = _advance(soc_u, st, cfg, eta, charge_target_pct, None)
        gchg_total += g
        overflow_total += o
        soc_c, _g2, _o2, imp = _advance(soc_c, st, cfg, eta, charge_target_pct, floor_pct)
        imp_total += imp
        pts.append(SimPoint(st.t1, soc_u, imp_total))
        if soc_u < min_u:
            min_u, min_t = soc_u, st.t1
        if t_floor is None and soc_u <= floor_pct:
            t_floor = st.t1
    return SimResult(pts, min_u, min_t, imp_total, gchg_total, overflow_total, soc_u, t_floor, floor_pct)
