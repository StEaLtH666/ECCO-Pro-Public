"""Dynamic Dump-to-Grid advice (Intelligence V1.1 foundation, SHADOW): a reserve-aware stop level, never applied.

In 0.9.0 Dump-to-Grid stops at a stop level the user chooses (10-90 %, enforced by the controller and the Home Assistant
scripts) and does NOT use the battery reserve (SAFETY.md section 9). This module computes the stop level a reserve-aware
Dump-to-Grid WOULD use, and how much energy that leaves to export now:

    stop = ceil( effective reserve + margin + battery share of the planned demand until the next refill )
    stop is never below the feature's own 10 % minimum; above its 90 % maximum there is nothing to advise
    export = (SOC now - stop) x capacity x one-way efficiency, limited by power x duration when those are known

Fail closed (BLOCKED, no number): a stale or unknown SOC (the advisory 15-minute limit; the controller's own START gate
separately requires a SOC reading under 90 s old), an inverter status that is not known to be healthy, an unknown demand
figure, an open charging window, a Saving Session running or due within three hours (the same rule as the V1 export
advice), or a refill time that is not in the future. It is advice for a future reserve-aware Dump-to-Grid; nothing
consumes it in this release.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .advisor import SESSION_LEAD_NO_EXPORT_H, STALE_SOC_SECONDS
from .battery import eta_one_way
from .config import SiteConfig
from .explain import (LABEL_FACTOR, OK, Advice, Blocker, Confidence, ConfidenceFactor, InputAge, Reason, blocked,
                      finite_number, input_blockers, nonneg_number)

KIND = "dump_to_grid"
# The existing feature's stop-level bounds (the controller's stop-level number and the Home Assistant helper both use
# 10-90 %); advice outside them could not be expressed by the feature, so it is clamped up to the minimum and refused above
# the maximum. Software bounds of the feature, not battery-safety values.
FEATURE_STOP_MIN_PCT = 10.0
FEATURE_STOP_MAX_PCT = 90.0


@dataclass(frozen=True)
class DumpInputs:
    now: datetime                                 # aware
    soc_pct: float | None
    soc_age_s: float | None
    inverter_ok: bool | None
    refill_at: datetime                           # when the battery can next be refilled (next cheap window start), aware
    demand_until_refill_kwh: float | None         # planning demand from now until refill_at
    demand_label: str | None = None
    pv_until_refill_kwh: float = 0.0              # solar the caller vouches for until refill_at (AC kWh, conservative)
    duration_min: float | None = None             # intended Dump-to-Grid duration, for the power check
    max_discharge_kw: float | None = None
    max_export_kw: float | None = None
    in_charge_window: bool | None = None          # None = unknown = refused
    saving_sessions: tuple[tuple[datetime, datetime], ...] = field(default_factory=tuple)
    ha_reserve_pct: float | None = None


def advise_dump(cfg: SiteConfig, inp: DumpInputs) -> Advice:
    soc_in = InputAge.assess("soc", inp.soc_age_s, STALE_SOC_SECONDS)
    inputs = (soc_in,)
    bl = list(input_blockers(inputs))
    if not (finite_number(inp.soc_pct) and 0.0 <= inp.soc_pct <= 100.0):
        bl.append(Blocker("NO_SOC", "no valid battery SOC reading"))
    if inp.inverter_ok is not True:
        bl.append(Blocker("INVERTER_STATUS", "inverter status is unknown or not healthy"))
    if not (inp.now.tzinfo and inp.refill_at.tzinfo) or inp.refill_at <= inp.now:
        bl.append(Blocker("NO_REFILL_AHEAD", "the next refill time must be an aware time in the future"))
    if inp.in_charge_window is not False:
        bl.append(Blocker("CHARGE_WINDOW", "the cheap charging window is open or its state is unknown"))
    for s0, e0 in inp.saving_sessions:
        if not (isinstance(s0, datetime) and isinstance(e0, datetime) and s0.tzinfo and e0.tzinfo and inp.now.tzinfo
                and e0 > s0):
            bl.append(Blocker("INVALID_SESSION", "a Saving Session needs aware start/end times with the end after the start"))
            break
        lead_h = (s0 - inp.now).total_seconds() / 3600.0
        if (0.0 <= lead_h <= SESSION_LEAD_NO_EXPORT_H) or (s0 <= inp.now < e0):
            bl.append(Blocker("SAVING_SESSION", "a Saving Session is running or starts within three hours"))
            break
    if not nonneg_number(inp.demand_until_refill_kwh):
        bl.append(Blocker("DEMAND_UNKNOWN", "planned demand until the next refill is missing or invalid"))
    if inp.demand_label not in (None, "HIGH", "MEDIUM", "LOW", "INSUFFICIENT"):
        bl.append(Blocker("INVALID_INPUT", f"unknown demand confidence label {inp.demand_label!r}"))
    elif inp.demand_label == "INSUFFICIENT":
        bl.append(Blocker("DEMAND_INSUFFICIENT", "the demand figure rests on insufficient history"))
    if not nonneg_number(inp.pv_until_refill_kwh):
        bl.append(Blocker("INVALID_INPUT", "pv_until_refill_kwh must be a non-negative number"))
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
    keep_ac = max(0.0, inp.demand_until_refill_kwh - inp.pv_until_refill_kwh)
    keep_pct = keep_ac / eta / cap * 100.0
    stop_raw = desired + keep_pct
    stop = float(math.ceil(stop_raw - 1e-9))
    stop_set_by = "RESERVE_AND_DEMAND"           # what set the stop level ...
    limited_by = None                            # ... and, separately, what limits the export amount
    if stop < FEATURE_STOP_MIN_PCT:
        stop, stop_set_by = FEATURE_STOP_MIN_PCT, "FEATURE_MINIMUM"
    soc = float(inp.soc_pct)
    advisable = True
    export_kwh = export_kw = None
    if stop > FEATURE_STOP_MAX_PCT:
        advisable, stop_set_by = False, "ABOVE_FEATURE_RANGE"
        reasons.append(Reason("NO_DUMP_RANGE", (
            f"Keeping your {floor:.0f}% reserve plus margin and {keep_ac:.1f} kWh for the house until the next refill needs "
            f"a stop level of {stop_raw:.0f}%, above the {FEATURE_STOP_MAX_PCT:.0f}% the feature allows: no Dump-to-Grid "
            "is advised.")))
    elif soc <= stop:
        advisable = False
        reasons.append(Reason("NO_HEADROOM", (
            f"The battery is at {soc:.0f}%, at or below the {stop:.0f}% it must keep (reserve {floor:.0f}% plus margin, plus "
            f"{keep_ac:.1f} kWh planned until the next refill): nothing to export.")))
    else:
        export_kwh = math.floor((soc - stop) / 100.0 * cap * eta * 10 + 1e-9) / 10.0
        limited_by = "STOP_LEVEL"
        if (finite_number(inp.duration_min) and inp.duration_min > 0 and nonneg_number(inp.max_discharge_kw)
                and inp.max_discharge_kw > 0 and nonneg_number(inp.max_export_kw)):
            hours = inp.duration_min / 60.0
            by_power = min(inp.max_discharge_kw * eta, inp.max_export_kw) * hours
            if by_power < export_kwh:
                export_kwh, limited_by = math.floor(by_power * 10 + 1e-9) / 10.0, "POWER_LIMIT"
            export_kw = round(export_kwh / hours, 2)
        else:
            reasons.append(Reason("POWER_NOT_CHECKED", "Duration or power limits not supplied: the export energy is not "
                                                       "checked against what the limits allow in the time."))
        reasons.append(Reason("STOP_LEVEL", (
            f"A reserve-aware stop level would be {stop:.0f}%: your {floor:.0f}% reserve plus a "
            f"{cfg.soc_safety_margin_pct:.0f}% margin, plus {keep_pct:.0f} points for {keep_ac:.1f} kWh of planned demand "
            f"until the next refill. From {soc:.0f}% that leaves about {export_kwh:.1f} kWh to export.")))
    factors = [ConfidenceFactor("demand", LABEL_FACTOR.get(inp.demand_label or "LOW", 0.55),
                                f"demand confidence {inp.demand_label or 'not stated (treated as LOW)'}")]
    if inp.pv_until_refill_kwh > 0:
        factors.append(ConfidenceFactor("pv_credit", 0.9, "solar credit supplied by the caller"))
    rec = {"dump_advisable": advisable, "stop_soc_pct": stop if stop <= FEATURE_STOP_MAX_PCT else None,
           "raw_stop_soc_pct": round(stop_raw, 2), "export_kwh": export_kwh, "export_kw_avg": export_kw,
           "stop_set_by": stop_set_by, "export_limited_by": limited_by,
           "soc_pct": soc, "effective_reserve_pct": floor, "desired_min_pct": desired,
           "reserve": reserve.as_dict(), "keep_until_refill_kwh": round(keep_ac, 3), "keep_soc_pct": round(keep_pct, 2),
           "refill_at": inp.refill_at.isoformat(),
           "feature_stop_bounds_pct": [FEATURE_STOP_MIN_PCT, FEATURE_STOP_MAX_PCT]}
    return Advice(KIND, OK, rec, Confidence.combine(factors), tuple(reasons), _ASSUMPTIONS, (), inputs)


_ASSUMPTIONS = (
    "Planned demand until the next refill is a planning (conservative) value supplied by the caller.",
    "Battery arithmetic uses the configured capacity and a one-way efficiency of sqrt(round-trip efficiency).",
    "The stop level is rounded UP to a whole percent and kept inside the feature's 10-90 % range.",
    "Advice only: Dump-to-Grid in this release does not read it, and nothing here changes any setting.",
)
