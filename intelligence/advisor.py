"""Shadow battery advisor: turns forecasts into explainable, conservative recommendations.

NOTHING HERE CONTROLS ANYTHING. The output is advice with numbers, reasons and
uncertainty. The effective minimum SOC (SiteConfig.effective_reserve: the user's
reserve, default 40 %, never below the technical minimum, raised by any HA
reserve) is applied inside every calculation: no recommendation is ever
generated that predicts SOC below effective minimum + margin on the pessimistic
path; when that is impossible the advice is a SHORTFALL warning, not a smaller
number. The "floor" in this module is that effective minimum.

Conservatism rules (each is also stated back to the user as a reason):
* The "pessimistic" path scales the load band (p90) and the PV band (p10) by
  sqrt(1/2) each. That equals the combined 90th percentile only when the two
  uncertainties are equal; with PV at zero it is nearer the 82nd. It is used for
  the overnight TARGET. Export advice, which is more floor-sensitive, uses the
  "hard" path: BOTH bands in full (load p90 and PV p10 together, well beyond a
  joint 90th percentile). Independent replay sweeps (review 2026-10-05) showed
  the sqrt(1/2) path alone let ~8 % of export advices dip under the comfort
  margin on synthetic data; the hard path exists for that reason.
* When the recent (fast) load profile sits materially below a longer robust baseline (an empty house, then the
  first normal day back) or an abnormal / behaviour-shift / low-load condition is active, the pessimistic and
  hard paths use the HIGHER of the fast profile and that baseline per hour. The median path is not changed.
* A PV forecast that is physically impossible for the site or far outside anything observed is REJECTED upstream
  (pv.py) and replaced by persistence at LOW confidence; the advice says so.
* LOW confidence widens those deviations x1.5. FAIL CLOSED: INSUFFICIENT
  history, stale data, an unknown or stale SOC age, an unknown or unhealthy
  inverter status, an open charge window, or a Saving Session due within
  three hours or already running withholds any export advice.
* An abnormal sustained load persists for the next hours (it is already in
  the short-term adjustment) and halves any export advice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .battery import SimResult, build_steps, eta_one_way, simulate
from .config import SiteConfig
from .timeutil import HOUR, local_wall, ts, zone

# Site-tunable constants (kappa, grid-charge cap, target step) live in SiteConfig; the rest are fixed policy.
LOW_CONF_WIDEN = 1.5
STALE_SOC_SECONDS = 15 * 60
SESSION_LEAD_NO_EXPORT_H = 3.0


def soc_is_stale(age_s) -> bool:
    """Fail closed: an unknown, NaN/inf, negative (clock skew) or non-numeric age is NOT fresh."""
    return not (isinstance(age_s, (int, float)) and not isinstance(age_s, bool) and 0.0 <= age_s <= STALE_SOC_SECONDS)


@dataclass
class TariffInfo:
    cheap_windows: list[tuple[datetime, datetime]]          # UTC
    import_cheap_p: float | None = None
    import_peak_p: float | None = None
    export_p: float | None = None
    source: str = "config_default"                          # 'octopus_rates' | 'config_default'


@dataclass
class LiveInputs:
    now: datetime
    soc_pct: float | None
    soc_age_s: float | None = None          # None = unknown = treated as NOT fresh (export withheld)
    load_w: float | None = None
    pv_w: float | None = None
    pv_raw_today: dict[str, float] = field(default_factory=dict)
    pv_raw_tomorrow: dict[str, float] = field(default_factory=dict)
    pv_raw_remaining_today: dict[str, float] = field(default_factory=dict)
    pv_actual_so_far_kwh: float | None = None
    ha_reserve_pct: float | None = None
    tariff: TariffInfo | None = None
    saving_sessions: list[tuple[datetime, datetime]] = field(default_factory=list)
    inverter_ok: bool | None = None         # None = unknown = export withheld


def default_cheap_windows(cfg: SiteConfig, now: datetime, days_ahead: int = 3) -> list[tuple[datetime, datetime]]:
    tz = zone(cfg.tz)
    d0 = now.astimezone(tz).date() - timedelta(days=1)
    return [(local_wall(d0 + timedelta(days=k), cfg.cheap_window_start_min, tz),
             local_wall(d0 + timedelta(days=k), cfg.cheap_window_end_min, tz)) for k in range(days_ahead + 1)]


def _ceil_to(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step


@dataclass
class PvDay:
    """PV p10/p50/p90 for one local day with its hourly allocation. For today, `remaining_p50` and
    `now_local_hour` restrict the simulation to what has not yet happened."""
    day: date
    p10: float
    p50: float
    p90: float
    shape: list[float]
    remaining_p50: float | None = None
    now_local_hour: int | None = None

    def hour_kwh(self, local_hour: int) -> float:
        if self.remaining_p50 is None or self.now_local_hour is None:
            return self.p50 * self.shape[local_hour]
        shares = [s if h >= self.now_local_hour else 0.0 for h, s in enumerate(self.shape)]
        tot = sum(shares)
        return self.remaining_p50 * (shares[local_hour] / tot) if tot > 0 else 0.0


class Planner:
    """Scenario paths and shadow answers for one `now`."""

    def __init__(self, cfg: SiteConfig, load_profile: list, load_rel: tuple[float, float],
                 pv_by_day: dict[date, PvDay], inputs: LiveInputs, nowcast: list[float], conf_label: str,
                 pv_inflation: float = 1.0, baseline_profile: list | None = None):
        self.cfg = cfg
        self.tz = zone(cfg.tz)
        self.profile = load_profile
        self.load_rel_lo, self.load_rel_hi = load_rel          # (p10 - 1, p90 - 1) of window load energy
        self.pv_by_day = pv_by_day
        self.inp = inputs
        self.nowcast = nowcast
        self.widen = LOW_CONF_WIDEN if conf_label == "LOW" else 1.0
        self.pv_widen = max(1.0, pv_inflation)      # PV band recently failed to hold: lean on it harder
        self.baseline = baseline_profile            # long robust load baseline, applied to pess/hard only when set
        self.kappa = cfg.band_kappa

    def load_mult(self, scen: str) -> float:
        k = (1.0 if scen == "hard" else self.kappa) * self.widen
        if scen in ("pess", "hard"):
            return 1.0 + k * max(0.0, self.load_rel_hi)
        if scen == "opt":
            return max(0.2, 1.0 + k * min(0.0, self.load_rel_lo))
        return 1.0

    def pv_mult(self, day: PvDay, scen: str) -> float:
        k = (1.0 if scen == "hard" else self.kappa) * self.widen * self.pv_widen
        if day.p50 <= 0:
            return 1.0
        if scen in ("pess", "hard"):
            return max(0.0, 1.0 - k * (1.0 - day.p10 / day.p50))
        if scen == "opt":
            return 1.0 + k * (day.p90 / day.p50 - 1.0)
        return 1.0

    def _load_fn(self, scen: str):
        mult = self.load_mult(scen)
        now_hour = ts(self.inp.now) - (ts(self.inp.now) % HOUR)
        guarded = scen in ("pess", "hard") and self.baseline is not None

        def fn(h0: datetime) -> float:
            hh = h0.astimezone(self.tz).hour
            base = self.profile[hh]
            base = 1.0 if base is None else base
            if guarded and self.baseline[hh] is not None:
                base = max(base, self.baseline[hh])
            k = (ts(h0) - now_hour) // HOUR
            adj = self.nowcast[k] if 0 <= k < len(self.nowcast) else 0.0
            return max(0.0, (base + adj) * mult)
        return fn

    def _pv_fn(self, scen: str):
        def fn(h0: datetime) -> float:
            loc = h0.astimezone(self.tz)
            day = self.pv_by_day.get(loc.date())
            if day is None:
                return 0.0
            return day.hour_kwh(loc.hour) * self.pv_mult(day, scen)
        return fn

    def sim(self, soc0: float, start: datetime, end: datetime, scen: str, floor: float,
            windows: list[tuple[datetime, datetime]] | None = None, target: float | None = None) -> SimResult:
        steps = build_steps(start, end, self._load_fn(scen), self._pv_fn(scen), windows, self.cfg.max_grid_charge_kw)
        return simulate(soc0, steps, self.cfg, floor, target)


def _min_after(sim: SimResult, t: datetime) -> tuple[float, datetime | None]:
    best, bt = None, None
    for p in sim.points:
        if p.t >= t and (best is None or p.soc < best):
            best, bt = p.soc, p.t
    return (best if best is not None else sim.final_soc), bt


def _traj(sim: SimResult, every: int = 1) -> list[tuple[datetime, float]]:
    return [(p.t, p.soc) for i, p in enumerate(sim.points) if i % every == 0]


def advise(cfg: SiteConfig, planner: Planner, inp: LiveInputs, windows: list[tuple[datetime, datetime]],
           conf_label: str, abnormal_load: bool, sunrise: datetime | None, useful_pv: datetime | None,
           tariff: TariffInfo | None, data_stale: bool = False) -> dict:
    """The shadow answers. Returns a plain dict (JSON-serialisable via the engine)."""
    now = inp.now
    tz = zone(cfg.tz)
    reserve = cfg.effective_reserve(inp.ha_reserve_pct)
    floor = reserve.effective_pct               # the effective minimum SOC: nothing below may be advised as safe
    desired = floor + cfg.soc_safety_margin_pct
    eta = eta_one_way(cfg)
    cap = cfg.battery_capacity_kwh
    reasons: list[dict] = []
    uncertainty: list[dict] = []
    out: dict = {"floor_pct": floor, "safety_margin_pct": cfg.soc_safety_margin_pct, "desired_min_pct": desired,
                 # what the UI needs to explain the number: asked-for reserve, technical minimum, what applies and why
                 "reserve": reserve.as_dict()}
    if reserve.override_reason:
        reasons.append({"code": reserve.override_code, "text": reserve.override_reason})

    if inp.soc_pct is None:
        out["status"] = "NO_SOC"
        out["reasons"] = [{"code": "NO_SOC", "text": "No battery SOC reading: no recommendation is possible."}]
        return out
    soc0 = inp.soc_pct
    # fail closed: an unknown, negative (clock skew) or non-numeric age is NOT fresh
    stale = soc_is_stale(inp.soc_age_s)
    if stale:
        ok_age = isinstance(inp.soc_age_s, (int, float)) and not isinstance(inp.soc_age_s, bool) and math.isfinite(inp.soc_age_s) and inp.soc_age_s >= 0
        age_txt = f"{inp.soc_age_s / 60:.0f} min old" if ok_age else "of unknown or invalid age"
        uncertainty.append({"code": "STALE_SOC", "severity": "HIGH",
                            "text": f"SOC reading is {age_txt}; export advice is withheld."})

    ws = sorted(windows)
    cur = next((w for w in ws if w[1] > now), None)
    nxt = next((w for w in ws if cur is not None and w[0] >= cur[1]), None)
    if cur is None or nxt is None:
        out["status"] = "NO_TARIFF_WINDOW"
        out["reasons"] = [{"code": "NO_WINDOW", "text": "No cheap charging window known ahead."}]
        return out
    w0, w1 = cur
    horizon_end = nxt[0]
    in_window = w0 <= now < w1
    eff_w = (max(now, w0), w1)

    # ---- the overnight target: smallest SOC at window end that survives the pessimistic day ---------------
    def post_min(scen: str, T: float | None) -> tuple[float, SimResult]:
        s = planner.sim(soc0, now, horizon_end, scen, floor, [eff_w] if eff_w[1] > eff_w[0] else None, T)
        m, _t = _min_after(s, w1)
        return m, s

    def solve_target(scen: str) -> tuple[float, bool]:
        lo = int(math.ceil(desired))
        for T in range(lo, int(cfg.max_soc_pct) + 1):
            m, _s = post_min(scen, float(T))
            if m >= desired - 1e-9:
                return float(T), True
        return float(cfg.max_soc_pct), False

    t_pess, ok_pess = solve_target("pess")
    t_p50, _ = solve_target("p50")
    rec_target = min(cfg.max_soc_pct, _ceil_to(max(t_pess, desired), cfg.target_step_pct))
    insufficient = conf_label == "INSUFFICIENT"
    if insufficient:
        rec_target = cfg.max_soc_pct            # no evidence to justify anything less: retain the battery
    _, sim_p50 = post_min("p50", rec_target)
    _, sim_pess = post_min("pess", rec_target)
    _, sim_opt = post_min("opt", rec_target)
    _, sim_none = post_min("p50", None)

    out["overnight_target"] = {
        "recommended_target_soc_pct": rec_target,
        "median_case_target_soc_pct": t_p50,
        "pessimistic_case_target_soc_pct": t_pess,
        "feasible_on_pessimistic_path": ok_pess,
        "grid_charge_needed": sim_p50.grid_charge_kwh > 0.5,
        "grid_charge_kwh_median": round(sim_p50.grid_charge_kwh, 2),
        "window": [w0.isoformat(), w1.isoformat()],
        "period_end": horizon_end.isoformat(),
        # shortfall AFTER the charge window is what the target can influence; before it, nothing the target does helps
        "expected_import_after_charge_kwh_pessimistic": round(sim_pess.import_to_hold_floor_kwh - sim_pess.import_by(w1), 2),
        "expected_import_before_window_kwh_pessimistic": round(sim_pess.import_by(min(w0, horizon_end)), 2),
    }
    if insufficient:
        reasons.append({"code": "INSUFFICIENT_HISTORY", "text": (
            "Not enough clean history to justify a lower target: the advice is simply to retain the battery "
            f"({rec_target:.0f}%). The model's own estimate would have been {t_pess:.0f}% on the pessimistic path.")})
    elif ok_pess:
        reasons.append({"code": "TARGET", "text": (
            f"Charging to {rec_target:.0f}% by {w1.astimezone(tz).strftime('%H:%M')} keeps the battery above "
            f"{desired:.0f}% (your {floor:.0f}% reserve plus a {cfg.soc_safety_margin_pct:.0f}% margin) until the next "
            f"cheap window, even if demand runs high and solar low. The expected-case need is {t_p50:.0f}%.")})
    else:
        after = sim_pess.import_to_hold_floor_kwh - sim_pess.import_by(w1)
        tail = (f"about {after:.1f} kWh of peak-rate import would be needed to stay at your {floor:.0f}% reserve"
                if after >= 0.05 else f"it would still stay above your {floor:.0f}% reserve")
        reasons.append({"code": "SHORTFALL", "text": (
            f"Even a full charge may dip below the {desired:.0f}% comfort level before the next cheap window if demand runs "
            f"high and solar low: {tail}. Recommend {rec_target:.0f}% (the maximum).")})

    # ---- trajectories under the recommended target (what the user would see) --------------------------------
    def at(sim: SimResult, t: datetime | None) -> float | None:
        return None if t is None else sim.soc_at(t)
    out["predicted"] = {
        # every SOC below assumes the RECOMMENDED target is applied; the configured slot may differ (e.g. 100 %)
        "assumes_recommended_target_followed": True, "assumed_target_soc_pct": rec_target,
        "soc_at_charge_end_median": at(sim_p50, w1),
        "soc_at_sunrise_median": at(sim_p50, sunrise) if sunrise and sunrise > now else None,
        "soc_at_useful_pv_median": at(sim_p50, useful_pv) if useful_pv and useful_pv > now else None,
        "soc_at_useful_pv_pessimistic": at(sim_pess, useful_pv) if useful_pv and useful_pv > now else None,
        "min_soc_after_charge_median": _min_after(sim_p50, w1)[0],
        "min_soc_after_charge_pessimistic": _min_after(sim_pess, w1)[0],
        "min_soc_after_charge_time": (_min_after(sim_p50, w1)[1].isoformat() if _min_after(sim_p50, w1)[1] else None),
        "time_to_floor_without_grid_charging": sim_none.time_to_floor.isoformat() if sim_none.time_to_floor else None,
        "soc_at_period_end_median": sim_p50.final_soc,
        "pv_overflow_kwh_median": round(sim_p50.pv_overflow_kwh, 2),
    }
    pre_min, pre_t = None, None
    for p in sim_p50.points:
        if p.t <= w0 and (pre_min is None or p.soc < pre_min):
            pre_min, pre_t = p.soc, p.t
    out["predicted"]["pre_window_min_soc_median"] = pre_min
    if pre_min is not None and pre_min < floor and not in_window:
        reasons.append({"code": "PRE_WINDOW_FLOOR", "text": (
            f"Before the cheap window opens at {w0.astimezone(tz).strftime('%H:%M')} the battery is predicted to fall to "
            f"{pre_min:.0f}% - below your {floor:.0f}% reserve. The target above cannot fix that: it needs an earlier "
            f"top-up or less discharge.")})
    pre_imp = sim_pess.import_by(min(w0, horizon_end))
    if pre_imp > 0.2 and not in_window:
        first_breach = next((p.t for p in sim_pess.points if p.soc <= floor and p.t <= w0), None)
        reasons.append({"code": "PRE_WINDOW_RISK", "text": (
            f"On the pessimistic path the battery would reach your {floor:.0f}% reserve"
            + (f" at about {first_breach.astimezone(tz).strftime('%H:%M')}" if first_breach else "")
            + f" before the cheap window opens, needing about {pre_imp:.1f} kWh of peak-rate import. "
            "This is a risk to watch, not something the overnight target can change.")})
    if sim_none.time_to_floor and sim_none.time_to_floor < w0:
        reasons.append({"code": "FLOOR_ETA", "text": (
            f"Without grid charging the battery would reach {floor:.0f}% at about "
            f"{sim_none.time_to_floor.astimezone(tz).strftime('%H:%M')}.")})
    out["trajectory"] = [
        {"t": a.isoformat(), "soc_median": round(a_soc, 1), "soc_low": round(b_soc, 1), "soc_high": round(c_soc, 1)}
        for (a, a_soc), (_b, b_soc), (_c, c_soc) in zip(_traj(sim_p50), _traj(sim_pess), _traj(sim_opt))
    ]

    # ---- safe export now ------------------------------------------------------------------------------------
    export: dict = {"kwh": 0.0, "assumes_refill_in_cheap_window": True}
    withheld = None
    if conf_label == "INSUFFICIENT":
        withheld = "history is insufficient"
    elif stale:
        withheld = "SOC reading is stale or of unknown age"
    elif data_stale:
        withheld = "the learning history is stale"
    elif inp.inverter_ok is not True:
        withheld = "inverter status is unknown or not healthy"
    elif in_window:
        withheld = "the cheap charging window is open"
    else:
        for s0, e0 in inp.saving_sessions:
            lead = (s0 - now).total_seconds() / 3600.0
            if (0 <= lead <= SESSION_LEAD_NO_EXPORT_H) or (s0 <= now < e0):
                withheld = "a Saving Session is running or starts within three hours"
    if withheld is None:
        def survives(e_ac: float) -> bool:
            soc_after = soc0 - (e_ac / eta) / cap * 100.0
            s = planner.sim(soc_after, now, w0, "hard", floor)
            return min([soc_after] + [p.soc for p in s.points]) >= desired - 1e-9
        hi = max(0.0, (soc0 - desired) / 100.0 * cap * eta)
        if hi <= 0 or not survives(0.0):
            e_max = 0.0
        else:
            lo_e, hi_e = 0.0, hi
            for _ in range(40):
                mid = 0.5 * (lo_e + hi_e)
                if survives(mid):
                    lo_e = mid
                else:
                    hi_e = mid
            e_max = lo_e
        factor = 1.0
        if abnormal_load:
            factor *= 0.5
            export["reduced_for"] = export.get("reduced_for", []) + ["abnormal load"]
        if conf_label == "LOW":
            factor *= 0.5
            export["reduced_for"] = export.get("reduced_for", []) + ["low confidence"]
        export["kwh"] = math.floor(e_max * factor * 10 + 1e-9) / 10.0
        export["kwh_before_reductions"] = math.floor(e_max * 10 + 1e-9) / 10.0
        if tariff and tariff.export_p is not None and tariff.import_cheap_p is not None:
            export["net_value_p_per_kwh"] = round(tariff.export_p - tariff.import_cheap_p / (eta * eta), 2)
            export["value_note"] = "export rate minus the cost of buying the energy back in the cheap window after round-trip losses"
        reasons.append({"code": "EXPORT", "text": (
            f"About {export['kwh']:.1f} kWh could be exported now while the pessimistic path still stays above "
            f"{desired:.0f}% until the cheap window opens at {w0.astimezone(tz).strftime('%H:%M')}, even with demand at its "
            f"p90 and solar at its p10 together"
            + (f" (reduced for {', '.join(export.get('reduced_for', []))})" if export.get("reduced_for") else "") + ".")})
    else:
        export["withheld_because"] = withheld
        reasons.append({"code": "EXPORT_WITHHELD", "text": f"No export advice: {withheld}."})
    out["safe_export"] = export

    # ---- Saving Session cover check ------------------------------------------------------------------------
    sess = None
    for s0, e0 in sorted(inp.saving_sessions):
        if e0 > now and s0 < horizon_end:
            soc_s = sim_p50.soc_at(max(s0, now)) if s0 > now else soc0
            need_sim = lambda start_soc: planner.sim(start_soc, max(s0, now), e0, "pess", floor)  # noqa: E731
            res = need_sim(soc_s)
            covers = min([soc_s] + [p.soc for p in res.points]) >= desired
            lo_s = None
            for cand in range(int(math.ceil(desired)), int(cfg.max_soc_pct) + 1):
                r2 = need_sim(float(cand))
                if min([float(cand)] + [p.soc for p in r2.points]) >= desired:
                    lo_s = float(cand)
                    break
            sess = {"start": s0.isoformat(), "end": e0.isoformat(), "soc_at_start_median": soc_s,
                    "covered_from_battery_pessimistic": covers, "min_soc_start_to_cover": lo_s}
            reasons.append({"code": "SESSION", "text": (
                f"Saving Session {s0.astimezone(tz).strftime('%H:%M')}-{e0.astimezone(tz).strftime('%H:%M')}: "
                + (f"the battery is predicted to cover it ({soc_s:.0f}% at the start)." if covers else
                   f"the battery may not cover it from {soc_s:.0f}%; retain at least "
                   f"{lo_s if lo_s is not None else cfg.max_soc_pct:.0f}% at the start."))})
            break
    out["saving_session"] = sess
    out["reasons"] = reasons
    out["uncertainty"] = uncertainty
    out["status"] = "OK"
    out["assumptions"] = [
        "Battery SOC arithmetic uses the configured capacity and round-trip efficiency; the true usable capacity is uncertain by several percent.",
        "Hourly resolution: sub-hour spikes are averaged out.",
        "Beyond tomorrow no PV is assumed (conservative).",
        f"Grid charging is assumed available at up to {cfg.max_grid_charge_kw:g} kW inside the cheap window.",
    ]
    return out
