"""Baselines for the SHADOW planner (planning stream): the ONE definition of what the advice is compared with, and the
ONE energy replay both the projected value (value.py) and the advice backtest (backtest_advice.py) use.

Baselines (each is a charge target for the coming window; nothing here is applied):

  ALWAYS_100        charge to the maximum SOC every window (the simplest safe policy);
  HOLD_CURRENT      keep the TOU slot's current target SOC (`tou.current_target_soc_pct`, read-only); absent when that
                    reading is missing, stale or not a percentage;
  V1_CONFIG_WINDOW  the V1 engine's simulated target on the DECIDED configuration (whose window is the judged charge
                    window); only when every decision it rests on is satisfied, otherwise absent.

The replay (`replay`) is an hourly energy account of one policy over [start, end) on given hourly load and PV:

  * inside the charge window the grid carries the house and charges the battery towards the target at up to the
    grid-charge limit; PV still reaches the battery;
  * outside it the battery covers any deficit down to the effective reserve, below which the grid carries the house
    (peak import; a battery already below the reserve is held where it is, never raised by import); a PV surplus charges
    the battery up to the maximum SOC and the rest is exported;
  * an unconstrained track (no reserve) is kept beside it, so a reserve violation can be seen.

Pure: no clock read, no file or network access. Every policy is replayed on the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from .battery import build_steps, eta_one_way
from .config import SiteConfig
from .explain import finite_number
from .site_decisions import INFO, Finding, InputState, finding

BASELINES_VERSION = "intel-baselines-0.1.0"

ALWAYS_100 = "ALWAYS_100"
HOLD_CURRENT = "HOLD_CURRENT"
V1_CONFIG_WINDOW = "V1_CONFIG_WINDOW"
BASELINE_NAMES = (ALWAYS_100, HOLD_CURRENT, V1_CONFIG_WINDOW)
ADVICE = "ADVICE"


@dataclass(frozen=True)
class Baseline:
    name: str
    target_soc_pct: float
    basis: str


def baselines(*, max_soc_pct: float, tou_current: InputState | None, v1_target_pct: float | None,
              decisions_satisfied: bool) -> tuple[dict[str, Baseline], list[Finding]]:
    """The baselines available for one cycle, in BASELINE_NAMES order, with an INFO finding per absent one."""
    out: dict[str, Baseline] = {}
    notes: list[Finding] = []
    if finite_number(max_soc_pct) and 0.0 < max_soc_pct <= 100.0:
        out[ALWAYS_100] = Baseline(ALWAYS_100, float(max_soc_pct), "charge to the maximum SOC every window")
    v = tou_current.value if isinstance(tou_current, InputState) else None
    if (isinstance(tou_current, InputState) and tou_current.fresh and tou_current.limit_s is not None
            and finite_number(v) and 0.0 <= v <= 100.0):
        out[HOLD_CURRENT] = Baseline(HOLD_CURRENT, float(v), "keep the TOU slot's current target SOC (read-only)")
    else:
        notes.append(finding("BASELINE_HOLD_CURRENT_ABSENT", INFO, "baselines",
                             "the current TOU target reading is missing, stale or not a percentage"))
    if decisions_satisfied and finite_number(v1_target_pct) and 0.0 <= v1_target_pct <= 100.0:
        out[V1_CONFIG_WINDOW] = Baseline(V1_CONFIG_WINDOW, float(v1_target_pct),
                                         "the V1 engine's simulated target on the decided configuration")
    else:
        notes.append(finding("BASELINE_V1_ABSENT", INFO, "baselines",
                             "the V1 baseline needs every decision satisfied and a V1 run on the decided configuration"))
    return {k: out[k] for k in BASELINE_NAMES if k in out}, notes


@dataclass(frozen=True)
class StepEnergy:
    t0: datetime
    t1: datetime
    import_kwh: float           # grid energy into the house and the battery in this step
    export_kwh: float           # PV that could not be stored
    in_window: bool


@dataclass(frozen=True)
class Outcome:
    """One policy replayed over [start, end)."""
    target_soc_pct: float | None
    window_import_kwh: float    # import inside the charge window (house load plus battery charge)
    peak_import_kwh: float      # import outside the window, to keep the battery at the effective reserve
    export_kwh: float
    min_soc_unconstrained: float
    min_soc_after_window: float # the unconstrained minimum after the window end (what the target must carry)
    end_soc: float
    points: tuple[tuple[datetime, float, float], ...]   # (t, SOC with the reserve held, unconstrained SOC) at step ends
    steps: tuple[StepEnergy, ...]

    @property
    def import_kwh(self) -> float:
        return self.window_import_kwh + self.peak_import_kwh

    def soc_at(self, t: datetime) -> float | None:
        """The reserve-held SOC at the end of the last step ending at or before t (None before the first step end)."""
        out = None
        for p in self.points:
            if p[0] <= t:
                out = p[1]
            else:
                break
        return out


def replay(cfg: SiteConfig, floor_pct: float, target_pct: float | None, soc0: float, start: datetime, end: datetime,
           window: tuple[datetime, datetime] | None, load: Callable[[datetime], float],
           pv: Callable[[datetime], float]) -> Outcome:
    """The hourly energy account of one policy (see the module docstring). `load(h0)` / `pv(h0)` give the kWh of the full
    hour starting at h0. A target of None means no grid charging."""
    eta = eta_one_way(cfg)
    cap = cfg.battery_capacity_kwh
    top = float(cfg.max_soc_pct)
    soc_c = soc_u = float(soc0)
    win = [window] if window is not None and target_pct is not None else None
    steps = build_steps(start, end, load, pv, win, cfg.max_grid_charge_kw)
    w_imp = p_imp = exp_total = 0.0
    min_u = soc_u
    min_after = None
    pts = []
    out_steps = []
    for st in steps:
        imp = exp_ = 0.0
        charging = target_pct is not None and st.charge_cap_kwh > 0
        if charging:
            imp += st.load_kwh                                   # the grid carries the house in the window
            room_kwh = max(0.0, st.charge_cap_kwh - st.load_kwh)
            for which in ("c", "u"):
                s = soc_c if which == "c" else soc_u
                take = max(0.0, min((target_pct - s) / 100.0 * cap / eta, room_kwh))
                s += take * eta / cap * 100.0
                if which == "c":
                    imp += take
                    soc_c = s
                else:
                    soc_u = s
            net = st.pv_kwh                                      # only PV still reaches the battery
        else:
            net = st.pv_kwh - st.load_kwh
        if net >= 0:
            for which in ("c", "u"):
                s = soc_c if which == "c" else soc_u
                d = net * eta / cap * 100.0
                room = max(0.0, top - s)
                over = max(0.0, d - room) / 100.0 * cap / eta
                s = min(top, s + d)
                if which == "c":
                    exp_ += over
                    soc_c = s
                else:
                    soc_u = s
        else:
            hold = min(floor_pct, soc_c)                         # the reserve is held, never raised by import
            soc_u += net / eta / cap * 100.0
            soc_c += net / eta / cap * 100.0
            if soc_c < hold:
                imp += (hold - soc_c) / 100.0 * cap * eta        # the grid carries what the reserve will not
                soc_c = hold
        if charging:
            w_imp += imp
        else:
            p_imp += imp
        exp_total += exp_
        min_u = min(min_u, soc_u)
        if window is not None and st.t0 >= window[1]:
            min_after = soc_u if min_after is None else min(min_after, soc_u)
        pts.append((st.t1, soc_c, soc_u))
        out_steps.append(StepEnergy(st.t0, st.t1, imp, exp_, charging))
    return Outcome(target_pct, round(w_imp, 6), round(p_imp, 6), round(exp_total, 6), min_u,
                   min_u if min_after is None else min_after, soc_c, tuple(pts), tuple(out_steps))


def cost_p(outcome: Outcome, import_rate: Callable[[datetime], float | None],
           export_rate: Callable[[datetime], float | None] | None = None) -> float | None:
    """Import cost minus export income in pence, from the step energies and the rates at each step's start (p/kWh).
    None when any step with import lacks a rate (never a guessed price). Export without a rate earns nothing."""
    total = 0.0
    for st in outcome.steps:
        if st.import_kwh > 1e-12:
            r = import_rate(st.t0)
            if r is None or not finite_number(r):
                return None
            total += st.import_kwh * r
        if st.export_kwh > 1e-12 and export_rate is not None:
            r = export_rate(st.t0)
            if r is not None and finite_number(r):
                total -= st.export_kwh * r
    return total


def compare(outcomes: Mapping[str, Outcome]) -> dict[str, dict]:
    """{baseline: {import_kwh_delta, peak_import_kwh_delta}} of the ADVICE outcome against each baseline (positive = the
    advice imports more: an energy regret)."""
    a = outcomes.get(ADVICE)
    if a is None:
        return {}
    return {k: {"import_kwh_delta": round(a.import_kwh - o.import_kwh, 3),
                "peak_import_kwh_delta": round(a.peak_import_kwh - o.peak_import_kwh, 3)}
            for k, o in outcomes.items() if k != ADVICE}
