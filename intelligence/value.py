"""Projected value of the SHADOW plan (planning stream): savings against the baselines as a RANGE in GBP, with its
assumptions. Only with a VERIFIED import tariff that covers the whole horizon; otherwise NO_VALUE with a reason. A value
is never shown without a verified tariff, never with more precision than the evidence, and never as a real-data claim.

Method: the advice target and every baseline (baselines.baselines) are replayed by the one energy account
(baselines.replay) over [now, value end) on three forecast scenarios (low load with high PV, the median, high load with
low PV); each replay is costed at the verified rates of each step (baselines.cost_p). The value end is the horizon end
(the next window start) or, when the verified rates stop earlier, the end of the rates; the rates must cover at least the
charge window. Energy left in the battery above the reserve at the value end is credited at the lowest and at the
highest verified import rate of that period (both kept: it only widens the range), so a policy is never rewarded for
leaving the battery empty. The saving against a baseline is its cost minus the advice's cost; the range is the lowest
and the highest over the scenarios and valuations, rounded OUTWARD to PROPOSED_VALUE_STEP_GBP. Exported PV is valued at
the verified export rate; without a verified export tariff it is valued anywhere between nothing and the highest
verified import rate, which only widens the range. VAT
and the standing charge are UNKNOWN and excluded (rates as the payload states them; the standing charge is the same under
every plan). Battery wear is not costed unless the cycling-cost preference is given (it is then an assumption, not part
of the range).

Pure: no clock read, no file or network access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from .baselines import ADVICE, ALWAYS_100, HOLD_CURRENT, Baseline, cost_p, replay
from .battery import eta_one_way
from .config import SiteConfig
from .daily_plan import HourlyView
from .explain import finite_number
from .site_decisions import INFO, WARN, Finding, finding
from .tariff import TariffResult

VALUE_VERSION = "intel-value-0.1.0"
VERIFIED = "VERIFIED"
NO_VALUE = "NO_VALUE"

# PROPOSED engineering constant (not an owner value)
PROPOSED_VALUE_STEP_GBP = 0.05           # ranges are rounded outward to this step: no precision beyond the evidence


@dataclass(frozen=True)
class ValueResult:
    status: str                                       # VERIFIED | NO_VALUE
    findings: tuple[Finding, ...]
    range_gbp: tuple[float, float] | None = None      # against the primary baseline
    primary: str | None = None
    baselines: Mapping[str, tuple[float, float]] | None = None
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == NO_VALUE and (self.range_gbp is not None or self.baselines):
            raise ValueError("NO_VALUE carries no figure")
        if self.range_gbp is not None:
            lo, hi = self.range_gbp
            if not (finite_number(lo) and finite_number(hi) and lo <= hi):
                raise ValueError("a value range is finite and ordered")

    def block(self) -> dict | None:
        """The envelope's value block {range_gbp, assumptions, baselines}; None unless VERIFIED."""
        if self.status != VERIFIED or self.range_gbp is None:
            return None
        return {"range_gbp": [self.range_gbp[0], self.range_gbp[1]], "assumptions": list(self.assumptions),
                "baselines": {k: [v[0], v[1]] for k, v in (self.baselines or {}).items()}}


def _outward(lo: float, hi: float) -> tuple[float, float]:
    s = PROPOSED_VALUE_STEP_GBP
    a = math.floor(lo / s + 1e-9) * s
    b = math.ceil(hi / s - 1e-9) * s
    return round(a, 2), round(b, 2)


def no_value(code: str, text: str) -> ValueResult:
    return ValueResult(NO_VALUE, (finding(code, WARN, "value", text),))


ASSUMPTIONS = (
    "Projected on forecasts; synthetic or unverified data gives no real-data claim.",
    "Rates as the verified tariff states them; VAT and standing charge excluded.",
    "Same energy account for the advice and every baseline; inverter slot behaviour above target unverified.",
)


def project_value(*, cfg: SiteConfig, floor_pct: float, now: datetime, horizon_end: datetime,
                  window: tuple[datetime, datetime], soc_pct: float | None, advice_target_pct: float,
                  baselines: Mapping[str, Baseline], view: HourlyView | None, import_tariff: TariffResult | None,
                  export_tariff: TariffResult | None = None, cycling_cost_p: float | None = None) -> ValueResult:
    """The projected savings range (see the module docstring), or NO_VALUE with the reason. Never raises for these
    inputs."""
    try:
        if not (isinstance(import_tariff, TariffResult) and import_tariff.verified):
            return no_value("VALUE_TARIFF_NOT_VERIFIED", "no verified import tariff: no money figure is shown")
        if not import_tariff.covers(now, window[1]):
            return no_value("VALUE_TARIFF_COVERAGE_SHORT", "the verified rates do not cover the charge window")
        end = min(horizon_end, import_tariff.slots[-1].end)
        if not finite_number(soc_pct):
            return no_value("VALUE_SOC_UNKNOWN", "the battery SOC is not known fresh")
        if view is None:
            return no_value("VALUE_FORECAST_UNKNOWN", "no usable load forecast")
        if not baselines:
            return no_value("VALUE_NO_BASELINE", "no baseline is available")
        imp = import_tariff.rate_at
        exp_verified = (isinstance(export_tariff, TariffResult) and export_tariff.verified
                        and export_tariff.covers(now, end))
        rng = import_tariff.price_range(now, end)
        if rng is None:
            return no_value("VALUE_TARIFF_COVERAGE_SHORT", "the verified rates do not cover the value period")
        low_rate, top_rate = rng
        eta_cap = eta_one_way(cfg) * cfg.battery_capacity_kwh / 100.0     # AC kWh per SOC point drawn from the battery
        export_options: list[Callable[[datetime], float | None] | None]
        if exp_verified:
            export_options = [export_tariff.rate_at]
        else:
            export_options = [lambda _t: 0.0, (lambda _t: top_rate)]
        savings: dict[str, list[float]] = {k: [] for k in baselines}
        for lm, pm in ((view.load_lo, view.pv_hi), (1.0, 1.0), (view.load_hi, view.pv_lo)):
            load_fn, pv_fn = view.scaled(lm, pm)
            runs = {ADVICE: replay(cfg, floor_pct, advice_target_pct, float(soc_pct), now, end, window, load_fn, pv_fn)}
            for k, b in baselines.items():
                runs[k] = replay(cfg, floor_pct, b.target_soc_pct, float(soc_pct), now, end, window, load_fn, pv_fn)
            for ex in export_options:
                costs = {k: cost_p(o, imp, ex) for k, o in runs.items()}
                if any(c is None for c in costs.values()):
                    return no_value("VALUE_RATE_MISSING", "a step of the value period has no verified rate")
                for stored_rate in (low_rate, top_rate):
                    net = {k: costs[k] - (o.end_soc - floor_pct) * eta_cap * stored_rate for k, o in runs.items()}
                    for k in baselines:
                        savings[k].append((net[k] - net[ADVICE]) / 100.0)
        per = {k: _outward(min(v), max(v)) for k, v in savings.items() if v}
        primary = HOLD_CURRENT if HOLD_CURRENT in per else (ALWAYS_100 if ALWAYS_100 in per else next(iter(per), None))
        if primary is None:
            return no_value("VALUE_NO_BASELINE", "no baseline could be costed")
        notes = [finding("VALUE_PROJECTED", INFO, "value", "projected savings range against the baselines",
                         primary=primary, scenarios=3, export_verified=bool(exp_verified), value_end=end,
                         truncated=end < horizon_end)]
        assumptions = list(ASSUMPTIONS)
        if not exp_verified:
            assumptions.append("Export unverified: valued between nothing and the top import rate.")
        if end < horizon_end:
            assumptions.append("Rates end before the horizon: stored energy valued at verified rates.")
        if cycling_cost_p is not None:
            assumptions.append("Battery wear preference given; not inside the range.")
        return ValueResult(VERIFIED, tuple(notes), per[primary], primary, per, tuple(assumptions))
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:
        return no_value("VALUE_NOT_COMPUTED", f"the projection failed closed ({type(exc).__name__})")
