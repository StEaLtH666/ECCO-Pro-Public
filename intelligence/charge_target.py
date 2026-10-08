"""Charge-target advice (Intelligence V1.1 foundation, SHADOW): an explainable energy budget, never applied.

    target = ceil_to_step( end-of-period floor + battery share of the planned demand )
    end-of-period floor = max(effective reserve + safety margin, desired morning SOC)
    planned demand      = the overnight learner's planning value minus any PV credit the caller vouches for

The effective reserve is SiteConfig.effective_reserve(): max(user reserve (default 40 %), technical minimum, a run-time HA
reserve that can only raise it). Learned demand and hard limits stay separate inputs, and the answer names the constraint
that set or limited it: RESERVE, DESIRED_MORNING_SOC, DEMAND, MAX_SOC (a shortfall: even a full battery may not cover the
period) or CHARGE_WINDOW (the window cannot reach the target from the current SOC). With a `previous` advice it also says
why the target moved, input by input.

Conservative by construction: the planning (p90) demand is used, PV is credited only when the caller supplies it with at
least MEDIUM confidence, INSUFFICIENT demand evidence means "retain the battery" (the maximum SOC, as the V1 advisor does),
and a stale or unknown SOC withholds only the parts that need it (the grid energy and whether the window can reach the
target), never the target itself, which does not depend on the current SOC. Those two parts are computed from the SOC at
the window START: the current SOC once the window is open, before that only a prediction the caller supplies.

This is a closed-form budget, not the V1 hourly simulation (advisor.py): it ignores when, inside the period, demand and
PV happen. It is the explainable foundation a future dynamic-charging feature can build on; the V1 shadow report keeps
its simulated target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .advisor import STALE_SOC_SECONDS, _ceil_to
from .battery import eta_one_way
from .config import EffectiveReserve, SiteConfig
from .explain import (BLOCKED, INSUFFICIENT, OK, Advice, Blocker, Confidence, ConfidenceFactor, InputAge, Reason,
                      blocked, finite_number)

KIND = "charge_target"
_LABELS = ("INSUFFICIENT", "LOW", "MEDIUM", "HIGH")
MEANINGFUL_NEED_PCT = 0.5        # below this the demand term is noise next to the floor


@dataclass(frozen=True)
class ChargeTargetInputs:
    now: datetime                               # aware
    window: tuple[datetime, datetime]           # the charging window (aware); the target is the SOC at its end
    demand: Advice                              # an overnight_demand Advice (overnight.learn_overnight)
    soc_pct: float | None = None
    soc_age_s: float | None = None
    ha_reserve_pct: float | None = None
    desired_morning_soc_pct: float | None = None
    pv_credit_kwh: float | None = None          # PV the caller vouches will offset demand within the period (AC kWh)
    pv_credit_label: str | None = None          # confidence label of that PV figure (HIGH/MEDIUM/LOW/INSUFFICIENT)
    window_load_kwh: float | None = None        # expected house load inside the window (the grid carries it)
    soc_at_window_start_pct: float | None = None  # the caller's PREDICTION of SOC when the window opens (e.g. V1's trajectory)
    previous: Advice | None = None              # the previous charge_target Advice, for change attribution


def _raw_target(end_floor: float, need_kwh: float, eta: float, cap: float) -> float:
    return end_floor + max(0.0, need_kwh) / eta / cap * 100.0


def _change(prev: Advice | None, now_used: dict, target_now: float) -> dict | None:
    """Attribute the change of target to the inputs that moved (sequential substitution in a fixed order)."""
    if prev is None or prev.kind != KIND or prev.recommendation is None:
        return None
    pu = prev.recommendation.get("inputs_used")
    if not pu:
        return None
    order = ("end_floor_pct", "demand_planning_kwh", "pv_credit_used_kwh", "battery_capacity_kwh", "eta_one_way")
    cur = {k: pu[k] for k in order}
    raw = _raw_target(cur["end_floor_pct"], cur["demand_planning_kwh"] - cur["pv_credit_used_kwh"], cur["eta_one_way"],
                      cur["battery_capacity_kwh"])
    drivers = []
    for k in order:
        if abs(now_used[k] - cur[k]) > 1e-9:
            cur[k] = now_used[k]
            nxt = _raw_target(cur["end_floor_pct"], cur["demand_planning_kwh"] - cur["pv_credit_used_kwh"],
                              cur["eta_one_way"], cur["battery_capacity_kwh"])
            drivers.append({"input": k, "from": pu[k], "to": now_used[k], "effect_pct": round(nxt - raw, 2)})
            raw = nxt
    prev_target = prev.recommendation.get("target_soc_pct")
    delta = None if prev_target is None else round(target_now - prev_target, 2)
    return {"previous_target_soc_pct": prev_target, "target_soc_pct": target_now, "delta_pct": delta,
            "drivers": drivers, "unexplained_by_inputs_pct": None if delta is None else
            round(delta - sum(d["effect_pct"] for d in drivers), 2),
            "note": "effects are on the unrounded target; the remainder is rounding to the target step and caps"}


def advise_charge_target(cfg: SiteConfig, inp: ChargeTargetInputs) -> Advice:
    w0, w1 = inp.window
    if not (w0.tzinfo and w1.tzinfo and inp.now.tzinfo) or not w1 > w0:
        return blocked(KIND, [Blocker("INVALID_WINDOW", "the charging window must be aware datetimes with end after start")])
    if inp.now >= w1:
        return blocked(KIND, [Blocker("WINDOW_OVER", "the charging window has already ended")])
    reserve: EffectiveReserve = cfg.effective_reserve(inp.ha_reserve_pct)
    floor = reserve.effective_pct
    buffer = cfg.soc_safety_margin_pct
    cap = cfg.battery_capacity_kwh
    eta = eta_one_way(cfg)
    reasons: list[Reason] = []
    if reserve.override_reason:
        reasons.append(Reason(reserve.override_code, reserve.override_reason))

    end_floor, floor_kind = floor + buffer, "RESERVE"
    dm = inp.desired_morning_soc_pct
    if dm is not None:
        if not finite_number(dm) or not 0.0 <= dm <= cfg.max_soc_pct:
            return blocked(KIND, [Blocker("INVALID_DESIRED_MORNING_SOC", f"desired morning SOC {dm!r} is not within 0-"
                                                                         f"{cfg.max_soc_pct:g} %")])
        if dm > end_floor:
            end_floor, floor_kind = float(dm), "DESIRED_MORNING_SOC"

    soc_in = InputAge.assess("soc", inp.soc_age_s, STALE_SOC_SECONDS, required=False,
                             note="needed only for the grid energy and window reach, not for the target")
    soc_fresh = (inp.soc_pct is not None and finite_number(inp.soc_pct) and 0.0 <= inp.soc_pct <= 100.0
                 and finite_number(inp.soc_age_s) and 0.0 <= inp.soc_age_s <= STALE_SOC_SECONDS)
    inputs = (soc_in,) + tuple(inp.demand.inputs)

    # ---- demand evidence ----------------------------------------------------------------------------------------
    d = inp.demand
    if d.kind != "overnight_demand":
        return blocked(KIND, [Blocker("WRONG_DEMAND_KIND", f"expected an overnight_demand advice, got {d.kind!r}")])
    fallback = d.status != OK or d.recommendation is None or d.recommendation.get("conservative_fallback", False)
    factors = [ConfidenceFactor("demand", d.confidence.score, f"overnight demand confidence {d.confidence.label}")]
    if fallback and (d.recommendation is None or d.status == BLOCKED):
        target = cfg.max_soc_pct
        reasons.append(Reason("RETAIN_BATTERY", (
            f"There is not enough demand evidence to justify anything below {target:.0f}%: the advice is to retain the "
            "battery (charge to the maximum) until overnight demand has been learned.")))
        conf = Confidence.combine(factors, cap_label="INSUFFICIENT")
        rec = {"target_soc_pct": target, "raw_target_soc_pct": None, "binding_constraint": "NO_DEMAND_EVIDENCE",
               "conservative_fallback": True, "effective_reserve_pct": floor, "buffer_pct": buffer,
               "end_of_period_floor_pct": end_floor, "reserve": reserve.as_dict(), "window": [w0.isoformat(), w1.isoformat()],
               "achievable_soc_pct": None, "grid_charge_kwh": None, "inputs_used": None, "changed_from_previous": None}
        return Advice(KIND, INSUFFICIENT, rec, conf, tuple(reasons), _ASSUMPTIONS, (), inputs)

    demand_kwh = float(d.recommendation["planning_kwh"])
    expected_kwh = float(d.recommendation["expected_kwh"])

    # ---- PV credit: only when vouched for --------------------------------------------------------------------------
    pv_used = 0.0
    if inp.pv_credit_kwh is not None:
        ok_pv = finite_number(inp.pv_credit_kwh) and inp.pv_credit_kwh >= 0.0
        ok_label = inp.pv_credit_label in ("MEDIUM", "HIGH")
        if ok_pv and ok_label:
            pv_used = min(float(inp.pv_credit_kwh), demand_kwh)
            factors.append(ConfidenceFactor("pv_credit", 0.9 if inp.pv_credit_label == "MEDIUM" else 1.0,
                                            f"PV credit of {pv_used:.1f} kWh at {inp.pv_credit_label} confidence"))
        else:
            reasons.append(Reason("PV_CREDIT_IGNORED", "A PV credit was supplied but not used: "
                                  + ("its value is not a valid non-negative number." if not ok_pv else
                                     f"its confidence ({inp.pv_credit_label}) is below MEDIUM.")))
    need_kwh = max(0.0, demand_kwh - pv_used)
    need_pct = need_kwh / eta / cap * 100.0
    raw = end_floor + need_pct
    target = min(cfg.max_soc_pct, _ceil_to(raw, cfg.target_step_pct))
    shortfall = max(0.0, raw - cfg.max_soc_pct)
    if fallback:            # INSUFFICIENT demand advice with a conservative default: use it, flag it, keep confidence low
        reasons.append(Reason("CONSERVATIVE_DEMAND_DEFAULT", "Overnight demand is still the configured conservative "
                                                             "default, not a learned value."))

    # ---- what the window can reach: from the SOC AT THE WINDOW START ------------------------------------------------
    # Inside the window that is the current (fresh) SOC. Before it, this budget does not predict how the SOC moves until
    # the window opens, so it uses the caller's prediction if one is given and otherwise states nothing.
    achievable = grid_kwh = None
    start_soc, start_src = None, None
    window_open = w0 <= inp.now
    pred = inp.soc_at_window_start_pct
    if window_open and soc_fresh:
        start_soc, start_src = float(inp.soc_pct), "current SOC (window open)"
    elif not window_open and finite_number(pred) and 0.0 <= pred <= 100.0:
        start_soc, start_src = float(pred), "caller's predicted SOC at the window start"
    if start_soc is not None:
        hours = max(0.0, (w1 - max(inp.now, w0)).total_seconds() / 3600.0)
        wl = inp.window_load_kwh if finite_number(inp.window_load_kwh) and inp.window_load_kwh >= 0 else 0.0
        into_battery_ac = max(0.0, cfg.max_grid_charge_kw * hours - wl)
        achievable = min(cfg.max_soc_pct, start_soc + into_battery_ac * eta / cap * 100.0)
        grid_kwh = round(max(0.0, (target - start_soc) / 100.0 * cap / eta), 2)
    elif window_open:
        factors.append(ConfidenceFactor("soc", 0.9, "SOC stale or unknown: window reach not checked"))
        reasons.append(Reason("SOC_NOT_FRESH", "The battery SOC is stale or of unknown age, so the grid energy needed and "
                                               "whether the window can reach the target are not stated."))
    else:
        reasons.append(Reason("WINDOW_NOT_OPEN", "The window has not opened yet and no prediction of the SOC at its start "
                                                 "was supplied, so the grid energy needed and whether the window can reach "
                                                 "the target are not stated (they depend on that SOC, not today's)."))

    if shortfall > 0:
        binding = "MAX_SOC"
        reasons.append(Reason("SHORTFALL", (
            f"Even {cfg.max_soc_pct:.0f}% may not cover the period: the budget needs {raw:.0f}% ({shortfall:.0f} points "
            f"more). Expect to import, or to reach the {floor:.0f}% reserve, before the period ends.")))
    elif achievable is not None and target > achievable + 1e-9:
        binding = "CHARGE_WINDOW"
        reasons.append(Reason("CHARGE_WINDOW_LIMIT", (
            f"From {start_soc:.0f}% ({start_src}) the window can reach only about {achievable:.0f}% at "
            f"{cfg.max_grid_charge_kw:g} kW; the target of {target:.0f}% cannot be met in this window.")))
    elif need_pct >= MEANINGFUL_NEED_PCT:
        binding = "DEMAND"
    else:
        binding = floor_kind
    floor_txt = (f"your desired {end_floor:.0f}% in the morning" if floor_kind == "DESIRED_MORNING_SOC" else
                 f"the {floor:.0f}% reserve plus a {buffer:.0f}% margin")
    reasons.append(Reason("TARGET", (
        f"Charge to {target:.0f}% by the end of the window: {floor_txt} ({end_floor:.0f}%) plus {need_pct:.0f} points for "
        f"{need_kwh:.1f} kWh of planned demand (planning value {demand_kwh:.1f} kWh, expected {expected_kwh:.1f} kWh"
        + (f", minus {pv_used:.1f} kWh solar credit" if pv_used > 0 else "") + ").")))

    # stored rounded, and compared rounded, so an unchanged input can never show up as a (rounding) driver
    used = {k: round(float(v), 6) for k, v in (("end_floor_pct", end_floor), ("demand_planning_kwh", demand_kwh),
                                                ("pv_credit_used_kwh", pv_used), ("battery_capacity_kwh", cap),
                                                ("eta_one_way", eta))}
    change = _change(inp.previous, used, target)
    if change is not None and change["delta_pct"]:
        parts = [f"{x['input']} {x['from']:g} -> {x['to']:g} ({x['effect_pct']:+.1f} points)" for x in change["drivers"]]
        reasons.append(Reason("CHANGED", f"Target moved {change['delta_pct']:+.0f} points since the previous advice"
                              + (": " + "; ".join(parts) if parts else " (rounding or caps only)") + "."))
    conf = Confidence.combine(factors, cap_label="LOW" if fallback else None)
    rec = {"target_soc_pct": target, "raw_target_soc_pct": round(raw, 2), "binding_constraint": binding,
           "shortfall_soc_pct": round(shortfall, 2), "conservative_fallback": bool(fallback),
           "effective_reserve_pct": floor, "buffer_pct": buffer, "end_of_period_floor_pct": end_floor,
           "desired_morning_soc_pct": dm, "reserve": reserve.as_dict(),
           "demand_planning_kwh": demand_kwh, "demand_expected_kwh": expected_kwh, "pv_credit_used_kwh": round(pv_used, 3),
           "net_need_kwh": round(need_kwh, 3), "need_soc_pct": round(need_pct, 2),
           "window": [w0.isoformat(), w1.isoformat()],
           "achievable_soc_pct": None if achievable is None else round(achievable, 1), "grid_charge_kwh": grid_kwh,
           "window_start_soc_pct": None if start_soc is None else round(start_soc, 1), "window_start_soc_source": start_src,
           "inputs_used": used,
           "changed_from_previous": change}
    return Advice(KIND, INSUFFICIENT if fallback else OK, rec, conf, tuple(reasons), _ASSUMPTIONS, (), inputs)


_ASSUMPTIONS = (
    "Planned demand is the overnight learner's planning value (default p90), not its expected value.",
    "Battery arithmetic uses the configured capacity and a one-way efficiency of sqrt(round-trip efficiency).",
    "A closed-form energy budget: when, inside the period, demand and solar happen is not modelled.",
    "Grid charging is assumed available at up to the configured grid-charge limit inside the window.",
    "Advice only: nothing here changes any setting.",
)
