"""Overnight demand learning (Intelligence V1.1 foundation, SHADOW).

Learns how much energy the house uses over ONE recurring overnight period. The caller defines the period (for example
from the end of the cheap charging window to the next one, or from evening to morning) and supplies one total per past
night; `nightly_totals()` extracts those totals from the canonical hourly History. The result is an `Advice` with

  * the expected (p50) and planning (default p90) energy for the coming night;
  * a confidence that grows with the number of clean nights and falls with dispersion, missing recent nights and a
    change of regime, each effect named;
  * the reasons behind the numbers: which nights were used, which were clipped as outliers or excluded, whether a
    configured default was blended in, and whether a change of regime made the planning value lean on the longer baseline.

The learned estimate is kept apart from every safety limit: this module knows nothing about the battery reserve, the
technical minimum or the battery itself (charge_target.py combines them). With too little clean history and no configured
default it returns INSUFFICIENT_DATA with no number; it never invents a household-size figure.

Return-from-away / abnormal demand. A recency-weighted mean follows the last few nights, so after several empty nights it
would under-plan the first normal night back. The regime check compares the most recent nights with the older baseline:
recent nights far BELOW it (an empty house, a holiday) or far ABOVE it lower the confidence, and the planning value then
uses the higher of the learned and the baseline/recent planning values; the expected value is left alone, as in the V1
baseline guard (usage.baseline_guard). Nights the caller declares as excluded (for example "DECLARED_AWAY", a choice the
user makes, not something inferred) are never learned from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

from . import stats
from .config import SiteConfig
from .explain import (INSUFFICIENT, OK, Advice, Confidence, ConfidenceFactor, InputAge, Reason, finite_number)
from .history import History
from .timeutil import local_wall, zone

KIND = "overnight_demand"
SIGMA_FLOOR_KWH = 0.10           # robust-sigma floor for nightly totals (kWh)
PRIOR_REL_SIGMA = 0.20           # wide relative 1-sigma used until enough walk-forward errors exist (usage.prior_rel_sigma, > 8 h)
MIN_BAND_ERRORS = 10             # walk-forward errors needed before the empirical band replaces the prior
MIN_BASELINE_NIGHTS = 5          # older nights needed before a regime can be judged


@dataclass(frozen=True)
class NightObservation:
    night: date                      # local date on which the overnight period STARTS
    kwh: float | None                # energy used over the period; None when the data did not cover it
    excluded: str | None = None      # caller-declared exclusion code (e.g. "DECLARED_AWAY", "DATA_GAP"): never learned from


@dataclass(frozen=True)
class OvernightSettings:
    """Learning constants. `from_site` binds the shared ones to SiteConfig so V1 and V1.1 use one set of values."""
    lookback_nights: int = 28
    alpha: float = 0.30                  # recency (SiteConfig.fast_alpha)
    winsor_k: float = 5.0                # outlier clip, robust sigmas (SiteConfig.winsor_k)
    min_nights: int = 7                  # below this: INSUFFICIENT_DATA (SiteConfig.min_days_for_forecast)
    full_confidence_nights: int = 28     # history depth for full confidence (SiteConfig.min_days_for_high_confidence)
    prior_kwh: float | None = None       # a configured conservative default; None = none
    prior_strength_nights: float = 7.0   # the prior counts like this many nights while history is short
    planning_quantile: float = 0.90
    recent_nights: int = 3               # regime check: the most recent nights ...
    regime_ratio: float = 0.25           # ... are a different regime if their median differs by >= 25 % ...
    regime_z: float = 2.0                # ... AND by >= 2 robust sigmas of the older baseline
    max_gap_nights: int = 2              # more missing recent nights than this = stale history

    def __post_init__(self) -> None:
        def bad(name: str, ok: bool) -> None:
            if not ok:
                raise ValueError(f"OvernightSettings.{name} = {getattr(self, name)!r} is not acceptable")
        bad("lookback_nights", isinstance(self.lookback_nights, int) and 7 <= self.lookback_nights <= 120)
        bad("alpha", finite_number(self.alpha) and 0.0 < self.alpha <= 1.0)
        bad("winsor_k", finite_number(self.winsor_k) and 2.0 <= self.winsor_k <= 10.0)
        bad("min_nights", isinstance(self.min_nights, int) and 3 <= self.min_nights <= self.lookback_nights)
        bad("full_confidence_nights", isinstance(self.full_confidence_nights, int)
            and self.min_nights <= self.full_confidence_nights <= self.lookback_nights)
        bad("prior_kwh", self.prior_kwh is None or (finite_number(self.prior_kwh) and 0.0 < self.prior_kwh <= 200.0))
        bad("prior_strength_nights", finite_number(self.prior_strength_nights) and 0.0 < self.prior_strength_nights <= 60.0)
        bad("planning_quantile", finite_number(self.planning_quantile) and 0.5 <= self.planning_quantile < 1.0)
        bad("recent_nights", isinstance(self.recent_nights, int) and 2 <= self.recent_nights <= 7)
        bad("regime_ratio", finite_number(self.regime_ratio) and 0.05 <= self.regime_ratio <= 0.9)
        bad("regime_z", finite_number(self.regime_z) and 0.5 <= self.regime_z <= 6.0)
        bad("max_gap_nights", isinstance(self.max_gap_nights, int) and 0 <= self.max_gap_nights <= 14)

    @classmethod
    def from_site(cls, cfg: SiteConfig, **overrides) -> "OvernightSettings":
        base = {"alpha": cfg.fast_alpha, "winsor_k": cfg.winsor_k, "min_nights": cfg.min_days_for_forecast,
                "full_confidence_nights": cfg.min_days_for_high_confidence}
        base.update(overrides)
        return cls(**base)


def nightly_totals(history: History, cfg: SiteConfig, start_min: int, end_min: int, first_night: date,
                   last_night: date, min_coverage: float = 0.8) -> list[NightObservation]:
    """One NightObservation per local date in [first_night, last_night]: the house load over the local wall-clock period
    from `start_min` on that date to `end_min` (may exceed 1440 = the next day). Hours missing from the history are scaled
    for only while at least `min_coverage` of the period is covered; otherwise the night's value is None (never invented)."""
    if not end_min > start_min:
        raise ValueError("the overnight period must end after it starts (end_min may exceed 1440)")
    tz = zone(cfg.tz)
    out = []
    d = first_night
    while d <= last_night:
        kwh = history.energy_scaled("load", local_wall(d, start_min, tz), local_wall(d, end_min, tz), min_coverage)
        out.append(NightObservation(d, kwh))
        d += timedelta(days=1)
    return out


def _fmt(x: float) -> str:
    return f"{x:.1f}"


def learn_overnight(observations: list[NightObservation], target_night: date, settings: OvernightSettings,
                    period: str = "the overnight period") -> Advice:
    """Expected and planning demand for the night starting on `target_night`, from nights strictly BEFORE it."""
    s = settings
    reasons: list[Reason] = []
    window_start = target_night - timedelta(days=s.lookback_nights)

    # ---- partition the window: valid / excluded / invalid / duplicates (nothing on or after the target night) ----
    counts: dict[date, int] = {}
    for o in observations:
        if window_start <= o.night < target_night:
            counts[o.night] = counts.get(o.night, 0) + 1
    duplicates = sorted(d for d, c in counts.items() if c > 1)
    valid: list[tuple[date, float]] = []
    excluded: dict[str, int] = {}
    invalid = 0
    for o in sorted(observations, key=lambda x: x.night):
        if not (window_start <= o.night < target_night) or o.night in duplicates:
            continue
        if o.excluded is not None:
            excluded[str(o.excluded)] = excluded.get(str(o.excluded), 0) + 1
        elif o.kwh is None:
            continue                                            # no data for that night: simply absent
        elif not finite_number(o.kwh) or o.kwh < 0.0:
            invalid += 1
        else:
            valid.append((o.night, float(o.kwh)))
    if duplicates:
        reasons.append(Reason("DUPLICATE_NIGHTS_IGNORED", f"{len(duplicates)} night(s) were supplied more than once and "
                                                          "are ignored rather than guessed between."))
    if invalid:
        reasons.append(Reason("INVALID_VALUES_IGNORED", f"{invalid} night total(s) were not a valid non-negative number "
                                                        "and are ignored."))
    if excluded:
        reasons.append(Reason("NIGHTS_EXCLUDED", "Nights excluded by the caller are not learned from: "
                              + ", ".join(f"{k} x{v}" for k, v in sorted(excluded.items())) + "."))
    n = len(valid)
    latest = valid[-1][0] if valid else None
    gap = None if latest is None else (target_night - latest).days - 1
    stale = gap is not None and gap > s.max_gap_nights
    # history age is judged here as a confidence factor (STALE_HISTORY), not as a blocker: the consumer decides
    inputs = (InputAge.assess("night_totals", None if gap is None else float(gap * 86400), float(s.max_gap_nights * 86400),
                              required=False,
                              note=f"nights missing since the latest clean night: {gap}" if gap is not None else "no clean night"),)
    assumptions = (f"Each night's total covers the same local-time period ({period}).",
                   "Demand only: the battery reserve, technical minimum and battery limits are applied separately.",
                   "No weather, occupancy or appliance information is used.")
    z = NormalDist().inv_cdf(s.planning_quantile)

    # ---- too little history -----------------------------------------------------------------------------------
    if n < s.min_nights:
        reasons.append(Reason("INSUFFICIENT_HISTORY", f"Only {n} clean night(s) in the last {s.lookback_nights}; at least "
                                                      f"{s.min_nights} are needed to learn overnight demand."))
        conf = Confidence.combine([ConfidenceFactor("history_depth", n / s.full_confidence_nights,
                                                    f"{n} of {s.full_confidence_nights} nights")], cap_label="INSUFFICIENT")
        rec = None
        if s.prior_kwh is not None:
            w = n / (n + s.prior_strength_nights)
            learned = stats.median([v for _d, v in valid]) if valid else s.prior_kwh
            expected = w * learned + (1.0 - w) * s.prior_kwh
            planning = max(s.prior_kwh, learned) * (1.0 + z * PRIOR_REL_SIGMA)
            rec = {"expected_kwh": round(expected, 3), "planning_kwh": round(planning, 3),
                   "planning_quantile": s.planning_quantile, "nights_used": n, "prior_kwh": s.prior_kwh,
                   "prior_weight": round(1.0 - w, 3), "conservative_fallback": True, "regime": "UNKNOWN"}
            reasons.append(Reason("CONSERVATIVE_DEFAULT", f"Using the configured default of {_fmt(s.prior_kwh)} kWh for "
                                  f"{period} (planning {_fmt(planning)} kWh, the higher of the default and the few nights "
                                  "seen, plus a wide margin) until enough nights are learned."))
        return Advice(KIND, INSUFFICIENT, rec, conf, tuple(reasons), assumptions, (), inputs)

    # ---- recency-weighted mean of winsorised nights, walk-forward relative errors ---------------------------------
    est: float | None = None
    raw_seen: list[float] = []
    rel_errs: list[float] = []
    clipped: list[dict] = []
    for d, x in valid:
        v, was = stats.winsorise(x, raw_seen[-s.lookback_nights:], s.winsor_k, SIGMA_FLOOR_KWH)
        if was:
            clipped.append({"night": d.isoformat(), "kwh": round(x, 3), "clipped_to_kwh": round(v, 3)})
        if est is not None and est > 0.1:
            rel_errs.append((x - est) / est)
        est = v if est is None else est + s.alpha * (v - est)
        raw_seen.append(x)
    learned = float(est)
    values = [v for _d, v in valid]
    med_all = stats.median(values)

    if len(rel_errs) >= MIN_BAND_ERRORS:
        hi = max(stats.quantile(rel_errs, s.planning_quantile), z * stats.robust_sigma(rel_errs, 0.02))
        band_note = f"from {len(rel_errs)} walk-forward errors"
    else:
        hi = z * PRIOR_REL_SIGMA
        if len(rel_errs) >= 3:
            hi = max(hi, stats.quantile(rel_errs, s.planning_quantile))
        band_note = f"from a deliberately wide prior ({len(rel_errs)} walk-forward errors, {MIN_BAND_ERRORS} needed)"
    hi = max(0.0, hi)
    expected = learned
    planning = learned * (1.0 + hi)
    reasons.append(Reason("OVERNIGHT_LEARNED", (
        f"Recency-weighted average of {n} clean night(s) for {period}: {_fmt(learned)} kWh (median {_fmt(med_all)}, range "
        f"{_fmt(min(values))}-{_fmt(max(values))} kWh); planning value {_fmt(planning)} kWh at the "
        f"{s.planning_quantile:.0%} level, band {band_note}.")))
    if clipped:
        reasons.append(Reason("OUTLIERS_CLIPPED", f"{len(clipped)} unusual night(s) were clipped to "
                              f"{s.winsor_k:g} robust sigmas before learning, so one odd night cannot move the estimate far: "
                              + ", ".join(f"{c['night']} {c['kwh']:.1f}->{c['clipped_to_kwh']:.1f} kWh" for c in clipped[:5])
                              + ("" if len(clipped) <= 5 else ", ...") + "."))

    # ---- shrink toward a configured default while history is short ----------------------------------------------
    prior_weight = 0.0
    if s.prior_kwh is not None and n < s.full_confidence_nights:
        w = n / (n + s.prior_strength_nights)
        prior_weight = 1.0 - w
        expected = w * learned + prior_weight * s.prior_kwh
        planning = w * planning + prior_weight * s.prior_kwh * (1.0 + z * PRIOR_REL_SIGMA)
        reasons.append(Reason("PRIOR_BLENDED", f"Only {n} night(s) learned: blended {prior_weight:.0%} with the configured "
                                               f"default of {_fmt(s.prior_kwh)} kWh."))

    # ---- regime (return-from-away / unusual period) ------------------------------------------------------------
    recent_cut = target_night - timedelta(days=s.recent_nights)
    recent = [v for d, v in valid if d >= recent_cut]
    baseline = [v for d, v in valid if d < recent_cut]
    regime, ratio, zr = "UNKNOWN", None, None
    regime_factor = 1.0
    rm = stats.median(recent) if recent else None
    bm = stats.median(baseline) if baseline else None
    if len(baseline) < MIN_BASELINE_NIGHTS:
        reasons.append(Reason("REGIME_UNKNOWN", f"Only {len(baseline)} older night(s) to compare the last "
                                                f"{s.recent_nights} with; a change of routine cannot be judged yet."))
        regime_factor = 0.9
    else:
        b_plan = max(stats.quantile(baseline, s.planning_quantile), bm * (1.0 + hi))
        bs = stats.robust_sigma(baseline, SIGMA_FLOOR_KWH)
        if len(recent) < 2:
            regime = "INSUFFICIENT_RECENT"
            regime_factor = 0.8
            if b_plan > planning:
                planning = b_plan
            reasons.append(Reason("REGIME_INSUFFICIENT_RECENT", (
                f"Fewer than two of the last {s.recent_nights} nights have data, so recent behaviour is unknown; the "
                f"planning value uses at least the older baseline ({_fmt(b_plan)} kWh).")))
        else:
            # a zero baseline makes any rise an unbounded ratio (it must still count as HIGH_RECENT) and no change 1.0
            ratio = rm / bm if bm > 0 else (math.inf if rm > 0 else 1.0)
            zr = (rm - bm) / bs
            if ratio <= 1.0 - s.regime_ratio and zr <= -s.regime_z:
                regime = "LOW_RECENT"
                regime_factor = 0.7
                lifted = b_plan > planning
                planning = max(planning, b_plan)
                reasons.append(Reason("REGIME_LOW_RECENT", (
                    f"The last {len(recent)} night(s) used {_fmt(rm)} kWh (median), far below the older baseline of "
                    f"{_fmt(bm)} kWh (for example an empty house). A return to normal use is planned for: the planning "
                    f"value is {'raised to' if lifted else 'kept at'} {_fmt(planning)} kWh; the expected value is unchanged.")))
            elif ratio >= 1.0 + s.regime_ratio and zr >= s.regime_z:
                regime = "HIGH_RECENT"
                regime_factor = 0.8
                r_plan = max(max(recent), rm * (1.0 + hi))
                planning = max(planning, r_plan)
                reasons.append(Reason("REGIME_HIGH_RECENT", (
                    f"The last {len(recent)} night(s) used {_fmt(rm)} kWh (median), far above the older baseline of "
                    f"{_fmt(bm)} kWh; the planning value is at least {_fmt(r_plan)} kWh while that lasts.")))
            else:
                regime = "STABLE"

    # ---- confidence -----------------------------------------------------------------------------------------------
    cv = stats.robust_sigma(values, SIGMA_FLOOR_KWH) / med_all if med_all > 0 else 1.0
    factors = [
        ConfidenceFactor("history_depth", min(1.0, n / s.full_confidence_nights), f"{n} of {s.full_confidence_nights} nights"),
        ConfidenceFactor("band_evidence", 0.6 + 0.4 * min(1.0, len(rel_errs) / 20.0),
                         f"{len(rel_errs)} walk-forward errors behind the band"),
        ConfidenceFactor("dispersion", max(0.5, min(1.0, 1.1 - cv)), f"night-to-night robust spread {cv:.0%} of the median"),
        ConfidenceFactor("regime", regime_factor, f"regime {regime}"),
    ]
    if stale:
        factors.append(ConfidenceFactor("data_age", 0.6, f"the latest clean night was {gap + 1} nights ago"))
        reasons.append(Reason("STALE_HISTORY", f"No clean night in the last {gap} night(s) before this one; the "
                                               "estimate rests on older nights."))
    if len(clipped) > 0.25 * n:
        factors.append(ConfidenceFactor("outlier_share", 0.8, f"{len(clipped)} of {n} nights needed clipping"))
    conf = Confidence.combine(factors)

    rec = {"expected_kwh": round(expected, 3), "planning_kwh": round(max(planning, expected), 3),
           "planning_quantile": s.planning_quantile, "learned_kwh": round(learned, 3),
           "nights_used": n, "nights_window": s.lookback_nights, "latest_night": latest.isoformat(),
           "nights_missing_since_latest": gap, "nights_clipped": clipped, "nights_excluded": dict(sorted(excluded.items())),
           "nights_invalid": invalid, "prior_kwh": s.prior_kwh, "prior_weight": round(prior_weight, 3),
           "regime": regime, "recent_median_kwh": None if rm is None else round(rm, 3),
           "baseline_median_kwh": None if bm is None else round(bm, 3),
           "recent_to_baseline_ratio": None if ratio is None or not math.isfinite(ratio) else round(ratio, 3),
           "recent_robust_z": None if zr is None else round(zr, 2), "conservative_fallback": False}
    return Advice(KIND, OK, rec, conf, tuple(reasons), assumptions, (), inputs)
