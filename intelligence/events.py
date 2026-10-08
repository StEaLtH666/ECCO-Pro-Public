"""Saving Session / export-event advice (Intelligence V1.1 foundation, SHADOW): an energy budget, never applied.

For one event (a period in which not importing, or exporting, is rewarded) it answers, on planning (conservative) demand:

  * can the battery carry the house through the event without importing, while keeping what the house needs AFTER the
    event (until the battery can next be refilled) above the effective reserve plus margin;
  * how much it could export on top, within the battery's discharge limit and the export limit, when both are known;
  * which constraint binds: the energy above the reserve (after what must be kept for later), or the power limits.

The effective reserve is SiteConfig.effective_reserve() (user reserve, default 40 %, never below the technical minimum,
raised by a run-time HA reserve). No reward or price is modelled (open decision O-4 in the V1 architecture): the advice
is about energy only. Fail closed: a stale or unknown SOC, an inverter status that is not known to be healthy, an
unknown demand figure or an invalid / finished event withholds the advice. Unknown power limits withhold only the export
amount, never the household-cover answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .advisor import STALE_SOC_SECONDS
from .battery import eta_one_way
from .config import SiteConfig
from .explain import (LABEL_FACTOR, OK, Advice, Blocker, Confidence, ConfidenceFactor, InputAge, Reason, blocked,
                      finite_number, input_blockers, nonneg_number)

KIND = "export_event"


@dataclass(frozen=True)
class ExportEvent:
    start: datetime                      # aware
    end: datetime                        # aware
    label: str = "saving_session"


@dataclass(frozen=True)
class EventInputs:
    now: datetime
    event: ExportEvent
    soc_pct: float | None
    soc_age_s: float | None
    inverter_ok: bool | None
    demand_before_kwh: float | None      # planning demand from now to the event start (ignored once it has started)
    demand_during_kwh: float | None      # planning demand during the (remaining) event
    demand_after_kwh: float | None       # planning demand after the event until the battery can next be refilled
    demand_label: str | None = None      # confidence label of those demand figures
    pv_before_kwh: float = 0.0           # solar the caller vouches for, per segment (AC kWh, conservative)
    pv_during_kwh: float = 0.0
    pv_after_kwh: float = 0.0
    max_discharge_kw: float | None = None
    max_export_kw: float | None = None
    ha_reserve_pct: float | None = None
    min_export_kwh: float = 0.1          # the advice resolution (exports are floored to 0.1 kWh, as in V1); raise to taste


def advise_event(cfg: SiteConfig, inp: EventInputs) -> Advice:
    ev = inp.event
    soc_in = InputAge.assess("soc", inp.soc_age_s, STALE_SOC_SECONDS)
    inputs = (soc_in,)
    bl: list[Blocker] = []
    valid_times = bool(ev.start.tzinfo and ev.end.tzinfo and inp.now.tzinfo) and ev.end > ev.start
    if not valid_times:
        bl.append(Blocker("INVALID_EVENT", "the event needs aware start/end times with the end after the start"))
    elif inp.now >= ev.end:
        bl.append(Blocker("EVENT_OVER", "the event has already ended"))
    bl += input_blockers(inputs)
    if not (finite_number(inp.soc_pct) and 0.0 <= inp.soc_pct <= 100.0):
        bl.append(Blocker("NO_SOC", "no valid battery SOC reading"))
    if inp.inverter_ok is not True:
        bl.append(Blocker("INVERTER_STATUS", "inverter status is unknown or not healthy"))
    started = valid_times and inp.now >= ev.start
    needed = [("demand_during_kwh", inp.demand_during_kwh), ("demand_after_kwh", inp.demand_after_kwh)]
    if not started:
        needed.append(("demand_before_kwh", inp.demand_before_kwh))
    for name, v in needed:
        if not nonneg_number(v):
            bl.append(Blocker("DEMAND_UNKNOWN", f"{name} is missing or not a valid non-negative number"))
    for name in ("pv_before_kwh", "pv_during_kwh", "pv_after_kwh", "min_export_kwh"):
        if not nonneg_number(getattr(inp, name)):
            bl.append(Blocker("INVALID_INPUT", f"{name} must be a non-negative number"))
    if inp.demand_label not in (None, "HIGH", "MEDIUM", "LOW", "INSUFFICIENT"):
        bl.append(Blocker("INVALID_INPUT", f"unknown demand confidence label {inp.demand_label!r}"))
    elif inp.demand_label == "INSUFFICIENT":
        bl.append(Blocker("DEMAND_INSUFFICIENT", "the demand figures rest on insufficient history"))
    if bl:
        return blocked(KIND, bl, inputs, assumptions=_ASSUMPTIONS)

    reserve = cfg.effective_reserve(inp.ha_reserve_pct)
    floor = reserve.effective_pct
    desired = floor + cfg.soc_safety_margin_pct
    cap = cfg.battery_capacity_kwh
    eta = eta_one_way(cfg)
    reasons: list[Reason] = []
    if reserve.override_reason:
        reasons.append(Reason(reserve.override_code, reserve.override_reason))

    t0 = max(inp.now, ev.start)
    hours = (ev.end - t0).total_seconds() / 3600.0
    pre_ac = 0.0 if started else max(0.0, inp.demand_before_kwh - inp.pv_before_kwh)
    soc_start = inp.soc_pct - pre_ac / eta / cap * 100.0
    usable_ac = max(0.0, (soc_start - desired) / 100.0 * cap * eta)
    keep_after = max(0.0, inp.demand_after_kwh - inp.pv_after_kwh)
    during = max(0.0, inp.demand_during_kwh - inp.pv_during_kwh)
    budget = usable_ac - keep_after
    covers = budget >= during - 1e-9
    energy_for_export = max(0.0, budget - during)

    export_kwh = export_kw = None
    binding = None
    limits_known = (nonneg_number(inp.max_discharge_kw) and inp.max_discharge_kw > 0 and nonneg_number(inp.max_export_kw))
    if limits_known:
        by_power = max(0.0, min(inp.max_discharge_kw * eta * hours - during, inp.max_export_kw * hours))
        raw = min(energy_for_export, by_power)
        export_kwh = math.floor(raw * 10 + 1e-9) / 10.0
        export_kw = round(export_kwh / hours, 2) if hours > 0 else 0.0
        binding = "POWER_LIMIT" if by_power < energy_for_export else "ENERGY_ABOVE_RESERVE"
    else:
        reasons.append(Reason("EXPORT_LIMITS_UNKNOWN", "The battery discharge limit and/or the export limit is not known, "
                                                       "so no export amount is advised; only household cover is assessed."))
    export_advised = export_kwh is not None and export_kwh >= inp.min_export_kwh and covers
    soc_end = soc_start - (min(during, max(0.0, budget)) + (export_kwh if export_advised else 0.0)) / eta / cap * 100.0
    if not covers:
        binding = "ENERGY_ABOVE_RESERVE"
        reasons.append(Reason("CANNOT_COVER", (
            f"From about {soc_start:.0f}% at the start, the battery has {usable_ac:.1f} kWh above your {desired:.0f}% minimum "
            f"(reserve {floor:.0f}% plus margin); keeping {keep_after:.1f} kWh for after the event leaves {max(0.0, budget):.1f} "
            f"kWh, less than the house's planned {during:.1f} kWh during it. Expect some import during the event.")))
    else:
        reasons.append(Reason("COVER", (
            f"The battery can carry the house's planned {during:.1f} kWh during the event from about {soc_start:.0f}% at "
            f"the start, and still keep {keep_after:.1f} kWh for after it above your {desired:.0f}% minimum.")))
        if export_advised:
            reasons.append(Reason("EXPORT", (
                f"On top, about {export_kwh:.1f} kWh could be exported (about {export_kw:.1f} kW on average), limited by "
                + ("the discharge / export power limits." if binding == "POWER_LIMIT" else
                   "the energy above your reserve after what is kept for later.") + "")))
        elif export_kwh is not None:
            reasons.append(Reason("NO_EXPORT", f"Exportable energy ({export_kwh:.1f} kWh) is below the "
                                               f"{inp.min_export_kwh:.1f} kWh worth advising."))
    factors = [ConfidenceFactor("demand", LABEL_FACTOR.get(inp.demand_label or "LOW", 0.55),
                                f"demand confidence {inp.demand_label or 'not stated (treated as LOW)'}")]
    if inp.pv_before_kwh + inp.pv_during_kwh + inp.pv_after_kwh > 0:
        factors.append(ConfidenceFactor("pv_credit", 0.9, "solar credit supplied by the caller"))
    rec = {"event": {"label": ev.label, "start": ev.start.isoformat(), "end": ev.end.isoformat(), "started": started,
                     "remaining_hours": round(hours, 3)},
           "cover_household_from_battery": covers, "export_advised": export_advised,
           "export_kwh": export_kwh, "export_kw_avg": export_kw, "binding_constraint": binding,
           "soc_at_start_pct": round(soc_start, 1), "soc_at_end_expected_pct": round(soc_end, 1),
           "effective_reserve_pct": floor, "desired_min_pct": desired, "reserve": reserve.as_dict(),
           "energy_above_minimum_kwh": round(usable_ac, 3), "keep_for_after_kwh": round(keep_after, 3),
           "household_during_kwh": round(during, 3), "energy_for_export_kwh": round(energy_for_export, 3)}
    return Advice(KIND, OK, rec, Confidence.combine(factors), tuple(reasons), _ASSUMPTIONS, (), inputs)


_ASSUMPTIONS = (
    "Demand figures are planning (conservative) values supplied by the caller; solar is credited only where supplied.",
    "Battery arithmetic uses the configured capacity and a one-way efficiency of sqrt(round-trip efficiency).",
    "The discharge limit is applied on the battery side and the export limit on the grid side, averaged over the event.",
    "No reward, price or baseline rule of any event scheme is modelled: energy only.",
    "Advice only: nothing here changes any setting.",
)
