"""Whole-house usage learning.

One idea, applied everywhere: the house's expected energy in any window is the
sum of its expected energy in each local-clock hour slot, and a slot's
expectation is a robust exponentially weighted mean of what the house used in
that slot on recent days. Because that mean is linear, every window forecast
(next hour, overnight, "to the next cheap window", the whole day) is
consistent with every other, and every number can be explained as "the
recency-weighted average of what this house used in those hours".

Backtest evidence (docs/intelligence/PROTOTYPE_RESULTS.md) is why the memory is
short: on about a year of one real household's data a ~5-day effective memory beat a
30-day mean, a same-weekday average and a naive blend on every window. Weekday
barely mattered there (under 8 % of residual variance) and is therefore NOT a model
input; `weekday_effect()` measures it so the claim stays testable.

Three slot "experts" with different memories are kept (fast ~5-day, slow
~12-day-equivalent long baseline, 14-day median). The fast expert is the point
forecast; the others are promoted only on clear evidence (see
adaptive_weights) and otherwise serve as the long-term baselines for drift and
anomaly context. Every observation is winsorised before it updates anything,
so one abnormal day moves the estimate by at most alpha x 3 sigma. Uncertainty
comes from the model's own walk-forward residuals, available immediately from
history and progressively supplemented by live scorecard residuals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from . import stats
from .config import SiteConfig
from .history import History
from .timeutil import HOUR, UTC, local_wall, overlap_seconds, ts, utc_from_ts, zone

EXPERTS = ("fast", "slow", "median14")
# Default: the fast expert alone. Backtests on about a year of one real household showed every blended or
# inverse-error-adapted ensemble was WORSE than the fast expert alone (docs/intelligence/PROTOTYPE_RESULTS.md),
# so the other experts earn weight only by clearly beating it ("promotion", below) - never by default.
PRIOR_WEIGHTS = {"fast": 1.0, "slow": 0.0, "median14": 0.0}
PROMOTE_WIN_SHARE = 0.70           # an expert must beat the fast expert on >= 70 % of the scored days ...
PROMOTE_RATIO = 0.90               # ... AND have <= 90 % of its trimmed mean absolute error ...
PROMOTE_TRIM = 3                   # (the 3 worst days of each are dropped before comparing)
PROMOTE_MAX_WEIGHT = 0.35          # ... and can then take at most this much weight
WEIGHT_EVAL_DAYS = 28              # ... measured over at least this many scored target days
RESIDUAL_DAYS = 90
SLOT_SIGMA_FLOOR_KWH = 0.10

# Short-horizon persistence of hourly residuals, fitted on 2026 data (lag-1 autocorrelation 0.37).
NOWCAST_RHO = 0.37
NOWCAST_DECAY = 0.65
NOWCAST_HOURS = 4


# ----------------------------------------------------------------------------
# Day x slot table
# ----------------------------------------------------------------------------

class DayTable:
    """Per local-day, per local-hour-slot energy for one field. A DST fall-back
    day's repeated hour is averaged; a spring-forward day simply lacks a slot."""

    def __init__(self, history: History, fieldname: str, tz_name: str):
        self.field = fieldname
        self.tz = zone(tz_name)
        acc: dict[date, list[list[float]]] = {}
        for start, rec in history.by_start.items():
            if fieldname not in rec.e:
                continue
            loc = utc_from_ts(start).astimezone(self.tz)
            slots = acc.setdefault(loc.date(), [[] for _ in range(24)])
            slots[loc.hour].append(rec.e[fieldname])
        self.days: dict[date, list[float | None]] = {
            d: [(sum(v) / len(v)) if v else None for v in slots] for d, slots in acc.items()
        }

    def slots(self, day: date) -> list[float | None] | None:
        return self.days.get(day)

    def complete_days(self, before: date, n: int, min_valid: int = 20) -> list[date]:
        """The most recent <= n days strictly before `before` with >= min_valid valid slots, oldest first."""
        out = []
        d = before - timedelta(days=1)
        floor = before - timedelta(days=n)
        while d >= floor:
            s = self.days.get(d)
            if s is not None and sum(1 for x in s if x is not None) >= min_valid:
                out.append(d)
            d -= timedelta(days=1)
        return list(reversed(out))

    def total(self, day: date, min_valid: int = 20) -> float | None:
        s = self.days.get(day)
        if s is None:
            return None
        valid = [x for x in s if x is not None]
        if len(valid) < min_valid:
            return None
        return sum(valid) * 24.0 / len(valid)


@dataclass
class SlotProfile:
    values: list[float | None]
    sigma: list[float]                 # robust sigma of the day-values per slot (anomaly scale)
    n_days: int
    clipped: int


def build_profile(table: DayTable, upto: date, alpha: float, lookback: int, k: float,
                  mode: str = "ewma") -> SlotProfile:
    days = table.complete_days(upto, lookback)
    values: list[float | None] = []
    sigmas: list[float] = []
    clipped = 0
    for s in range(24):
        series = [table.days[d][s] for d in days]
        if mode == "median":
            v = stats.clean(series)
            values.append(stats.median(v) if v else None)
            sigmas.append(stats.robust_sigma(v, SLOT_SIGMA_FLOOR_KWH) if v else SLOT_SIGMA_FLOOR_KWH)
        else:
            est, c = stats.robust_ewma(series, alpha, k, 28, SLOT_SIGMA_FLOOR_KWH)
            values.append(est)
            sigmas.append(stats.robust_sigma(stats.clean(series), SLOT_SIGMA_FLOOR_KWH))
            clipped += c
    return SlotProfile(values, sigmas, len(days), clipped)


def window_sum(values: list[float | None], t0: datetime, t1: datetime, tz) -> float | None:
    """Sum of slot expectations over [t0, t1), apportioning partial hours. None if any needed slot is unknown."""
    total = 0.0
    s = ts(t0) - (ts(t0) % HOUR)
    while s < ts(t1):
        frac = overlap_seconds(utc_from_ts(s), utc_from_ts(s + HOUR), t0, t1) / HOUR
        if frac > 0:
            v = values[utc_from_ts(s).astimezone(tz).hour]
            if v is None:
                return None
            total += v * frac
        s += HOUR
    return total


def nowcast_adjustments(recent_residuals: list[float]) -> list[float]:
    """Additive per-hour adjustment (kWh) for the next NOWCAST_HOURS hours from the latest hourly
    residual (actual - expected), decaying geometrically. Empty history -> zeros."""
    if not recent_residuals:
        return [0.0] * NOWCAST_HOURS
    r = recent_residuals[-1]
    return [NOWCAST_RHO * (NOWCAST_DECAY ** i) * r for i in range(NOWCAST_HOURS)]


# ----------------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------------

WindowFn = Callable[[date], tuple[datetime, datetime] | None]


def fixed_window(start_min: int, end_min: int, tz) -> WindowFn:
    """Local wall-clock window anchored on a calendar date; end_min may exceed 1440."""
    def fn(day: date) -> tuple[datetime, datetime]:
        return local_wall(day, start_min, tz), local_wall(day, end_min, tz)
    return fn


def standard_windows(cfg: SiteConfig) -> dict[str, tuple[int, int]]:
    """Name -> (start_min, end_min) local, for the fixed-clock windows the advisor uses."""
    return {
        "cheap_window": (cfg.cheap_window_start_min, cfg.cheap_window_end_min),
        "morning": (cfg.cheap_window_end_min, 540),
        "evening": (1020, 1440),
        "to_next_cheap": (cfg.cheap_window_end_min, 1440 + cfg.cheap_window_start_min),
        "day": (0, 1440),
    }


# ----------------------------------------------------------------------------
# Forecast objects
# ----------------------------------------------------------------------------

@dataclass
class UsageForecast:
    kind: str
    t0: datetime
    t1: datetime
    p10: float
    p50: float
    p90: float
    expert_preds: dict[str, float]
    weights: dict[str, float]
    n_days: int
    n_residuals: int
    empirical_coverage: float | None   # share of walk-forward actuals inside the stated p10-p90 (nominal 0.8)
    confidence: float
    label: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "t0": self.t0.isoformat(), "t1": self.t1.isoformat(),
            "p10": round(self.p10, 3), "p50": round(self.p50, 3), "p90": round(self.p90, 3),
            "expert_preds": {k: round(v, 3) for k, v in self.expert_preds.items()},
            "weights": {k: round(v, 3) for k, v in self.weights.items()},
            "n_days": self.n_days, "n_residuals": self.n_residuals,
            "empirical_coverage": None if self.empirical_coverage is None else round(self.empirical_coverage, 3),
            "confidence": round(self.confidence, 3), "label": self.label, "notes": list(self.notes),
            # INSUFFICIENT forecasts are built on too little data to quote: consumers must not display the numbers
            "usable": self.label != "INSUFFICIENT",
        }


def confidence_label(c: float) -> str:
    if c >= 0.75:
        return "HIGH"
    if c >= 0.50:
        return "MEDIUM"
    if c >= 0.25:
        return "LOW"
    return "INSUFFICIENT"


def prior_rel_sigma(hours: float) -> float:
    """Relative 1-sigma prior used until enough walk-forward residuals exist. Deliberately wide."""
    if hours <= 3:
        return 0.40
    if hours <= 8:
        return 0.30
    return 0.20


def adaptive_weights(errors: dict[str, list[float]], n_eval: int) -> dict[str, float]:
    """Evidence-gated expert weights ("promotion", not blending).

    Start from the prior (fast expert only). A secondary expert is promoted only if, over at least
    WEIGHT_EVAL_DAYS scored days, it (a) beats the fast expert's absolute error on at least PROMOTE_WIN_SHARE of
    the days and (b) has at most PROMOTE_RATIO of its trimmed mean absolute error. A win count moves by at most
    one per day and the trim removes each expert's worst days, so one abnormal day can neither promote an expert
    nor demote the fast one. The weight is proportional to the margin and capped at PROMOTE_MAX_WEIGHT."""
    w = dict(PRIOR_WEIGHTS)
    if n_eval < WEIGHT_EVAL_DAYS or any(len(v) < WEIGHT_EVAL_DAYS for v in errors.values()):
        return w

    def trimmed_mae(errs: list[float]) -> float:
        a = sorted(abs(e) for e in errs)[:-PROMOTE_TRIM]
        return max(sum(a) / len(a), 1e-9)

    base_abs = [abs(e) for e in errors["fast"]]
    base = trimmed_mae(errors["fast"])
    promoted = 0.0
    for name in ("slow", "median14"):
        wins = sum(1 for x, f in zip((abs(e) for e in errors[name]), base_abs) if x < f)
        ratio = trimmed_mae(errors[name]) / base
        if wins >= PROMOTE_WIN_SHARE * len(base_abs) and ratio <= PROMOTE_RATIO:
            w[name] = min(PROMOTE_MAX_WEIGHT, 2.0 * (1.0 - ratio))
            promoted += w[name]
    if promoted > 0:
        w["fast"] = max(0.0, 1.0 - promoted)
    return w


class UsageModel:
    """Walk-forward usage forecaster over a History (one field, default `load`)."""

    def __init__(self, history: History, cfg: SiteConfig, fieldname: str = "load"):
        self.history = history
        self.cfg = cfg
        self.tz = zone(cfg.tz)
        self.table = DayTable(history, fieldname, cfg.tz)
        self._profiles: dict[tuple[date, str], SlotProfile] = {}
        self._resid_cache: dict[tuple, list[tuple[date, dict[str, float], float]]] = {}
        self._dow_cache: dict[date, dict[int, float]] = {}

    # --- weekday factor: applied ONLY when the weekday effect is statistically material ---------------------
    def weekday_factors(self, asof: date, weeks: int = 12) -> dict[int, float]:
        """{weekday: multiplier} from the last `weeks` weeks, or {} when the effect is not material.

        Materiality = F-test on residuals of a short-memory level AND >= 8 % of residual variance explained
        (weekday_effect). Factors are the mean ratio of a day's total to the level that preceded it, shrunk
        toward 1 by n/(n+4) and clipped to [0.7, 1.4]."""
        hit = self._dow_cache.get(asof)
        if hit is not None:
            return hit
        days = [d for d in self.table.complete_days(asof, weeks * 7) if self.table.total(d) is not None]
        out: dict[int, float] = {}
        if len(days) >= 42:
            totals = [self.table.total(d) for d in days]
            level = None
            ratios: dict[int, list[float]] = {}
            res, dow = [], []
            for d, t in zip(days, totals):
                if level is not None and level > 0:
                    ratios.setdefault(d.weekday(), []).append(t / level)
                    res.append(t - level)
                    dow.append(d.weekday())
                level = t if level is None else level + 0.3 * (t - level)
            if len(res) >= 28:
                gm = sum(res) / len(res)
                ss_tot = sum((r - gm) ** 2 for r in res)
                groups: dict[int, list[float]] = {}
                for r, w in zip(res, dow):
                    groups.setdefault(w, []).append(r)
                ss_b = sum(len(g) * (sum(g) / len(g) - gm) ** 2 for g in groups.values())
                k, n = len(groups), len(res)
                ss_w = ss_tot - ss_b
                f = (ss_b / (k - 1)) / (ss_w / (n - k)) if ss_w > 0 and k > 1 else 0.0
                if f > 2.2 and ss_tot > 0 and ss_b / ss_tot >= 0.08:
                    mean_all = sum(sum(v) for v in ratios.values()) / sum(len(v) for v in ratios.values())
                    for w, v in ratios.items():
                        raw = (sum(v) / len(v)) / mean_all
                        shrink = len(v) / (len(v) + 4.0)
                        out[w] = max(0.7, min(1.4, 1.0 + (raw - 1.0) * shrink))
        self._dow_cache[asof] = out
        return out

    # --- experts ------------------------------------------------------------
    def profile(self, upto: date, expert: str) -> SlotProfile:
        key = (upto, expert)
        p = self._profiles.get(key)
        if p is None:
            c = self.cfg
            if expert == "fast":
                p = build_profile(self.table, upto, c.fast_alpha, c.lookback_days_fast, c.winsor_k)
            elif expert == "slow":
                p = build_profile(self.table, upto, c.slow_alpha, c.lookback_days_slow, c.winsor_k)
            elif expert == "median14":
                p = build_profile(self.table, upto, 0.0, 14, c.winsor_k, mode="median")
            else:
                raise ValueError(expert)
            self._profiles[key] = p
        return p

    def expert_window(self, upto: date, window: tuple[datetime, datetime], target_day: date | None = None
                      ) -> dict[str, float]:
        """Per-expert window energy using profiles built from days strictly before `upto`. If the weekday
        effect is material, the window is scaled by the target weekday's factor (relative to an average day)."""
        fac = 1.0
        if target_day is not None:
            fac = self.weekday_factors(upto).get(target_day.weekday(), 1.0)
        out = {}
        for e in EXPERTS:
            v = window_sum(self.profile(upto, e).values, window[0], window[1], self.tz)
            if v is not None:
                out[e] = v * fac
        return out

    # --- walk-forward residuals --------------------------------------------
    def residuals(self, kind: str, window_fn: WindowFn, asof: date, n_days: int = RESIDUAL_DAYS
                  ) -> list[tuple[date, dict[str, float], float]]:
        """For each of the last n_days complete target days before `asof`: per-expert predictions made with
        history strictly before that day, and the actual window energy. Returns (day, preds, actual)."""
        key = (kind, asof, n_days)
        cached = self._resid_cache.get(key)
        if cached is not None:
            return cached
        out = []
        d = asof - timedelta(days=n_days)
        while d < asof:
            w = window_fn(d)
            if w is not None:
                actual = self.history.energy_scaled(self.table.field, w[0], w[1], 0.8)
                if actual is not None:
                    preds = self.expert_window(d, w, d)
                    if len(preds) == len(EXPERTS) and self.profile(d, "fast").n_days >= self.cfg.min_days_for_forecast:
                        out.append((d, preds, actual))
            d += timedelta(days=1)
        self._resid_cache[key] = out
        return out

    # --- main entry ---------------------------------------------------------
    def forecast(self, kind: str, window: tuple[datetime, datetime], window_fn: WindowFn, asof: date,
                 nowcast: list[float] | None = None) -> UsageForecast:
        """Forecast window energy as of local date `asof` (history strictly before `asof` is used for the
        profiles; today's already-observed hours feed only the optional `nowcast` adjustment)."""
        notes: list[str] = []
        fast = self.profile(asof, "fast")
        n_days = fast.n_days
        target_day = window[0].astimezone(self.tz).date()
        preds = self.expert_window(asof, window, target_day)
        if self.weekday_factors(asof):
            notes.append(f"weekday adjustment x{self.weekday_factors(asof).get(target_day.weekday(), 1.0):.2f} (weekday effect is material)")
        hours = (window[1] - window[0]).total_seconds() / 3600.0
        if not preds:
            return UsageForecast(kind, window[0], window[1], 0.0, 0.0, 0.0, {}, dict(PRIOR_WEIGHTS), n_days, 0, None,
                                 0.0, "INSUFFICIENT", ["no usable history for this window"])
        resid = self.residuals(kind, window_fn, asof)
        weights = dict(PRIOR_WEIGHTS)
        if len(resid) >= WEIGHT_EVAL_DAYS:
            tail = resid[-WEIGHT_EVAL_DAYS:]
            errs = {e: [a - p[e] for _d, p, a in tail] for e in EXPERTS}
            weights = adaptive_weights(errs, len(tail))
            if weights != PRIOR_WEIGHTS:
                notes.append("expert weights promoted: " + ", ".join(f"{k} {v:.2f}" for k, v in weights.items() if v > 0))
        elif n_days < self.cfg.min_days_for_forecast:
            notes.append(f"only {n_days} days of history: below the {self.cfg.min_days_for_forecast}-day minimum")
        point = sum(weights[e] * preds[e] for e in preds) / sum(weights[e] for e in preds)
        if nowcast:
            adj = sum(nowcast[: max(1, int(math.ceil(hours)))][: NOWCAST_HOURS])
            point = max(0.0, point + adj)
            notes.append(f"short-term persistence adjustment {adj:+.2f} kWh")

        # --- interval from walk-forward relative residuals of the ENSEMBLE --------------------------
        rel = []
        for _d, p, a in resid:
            ens = sum(weights[e] * p[e] for e in p) / sum(weights[e] for e in p)
            if ens > 0.05:
                rel.append((a - ens) / ens)
        prior = prior_rel_sigma(hours)
        z10, z90 = -1.2816, 1.2816
        if len(rel) >= 20:
            lo, hi = stats.quantile(rel, 0.10), stats.quantile(rel, 0.90)
            # never narrower than the Gaussian band implied by the observed spread, and never zero
            sig = stats.robust_sigma(rel, 0.02)
            lo, hi = min(lo, z10 * sig), max(hi, z90 * sig)
        elif len(rel) >= 5:
            w_emp = (len(rel) - 4) / 16.0
            lo = w_emp * stats.quantile(rel, 0.10) + (1 - w_emp) * z10 * prior
            hi = w_emp * stats.quantile(rel, 0.90) + (1 - w_emp) * z90 * prior
        else:
            lo, hi = z10 * prior, z90 * prior
            notes.append("uncertainty from prior (too few walk-forward residuals)")
        p10, p90 = max(0.0, point * (1 + lo)), max(point, point * (1 + hi))
        cov = None
        if len(rel) >= 10:
            inside = 0
            for _d, p, a in resid:
                ens = sum(weights[e] * p[e] for e in p) / sum(weights[e] for e in p)
                if ens > 0.05 and ens * (1 + lo) <= a <= ens * (1 + hi):
                    inside += 1
            cov = inside / len(rel)

        # --- confidence ---------------------------------------------------------------------------
        hist_f = min(1.0, n_days / float(self.cfg.min_days_for_high_confidence))
        # NOTE: `cov` (empirical_coverage) is IN-SAMPLE (the band is built from the same residuals), so it sits near
        # the nominal 80 % by construction and must not feed confidence; out-of-sample coverage comes from the scorecard.
        cal_f = 1.0
        res_f = min(1.0, len(rel) / 20.0) * 0.4 + 0.6
        conf = max(0.0, min(1.0, hist_f * cal_f * res_f))
        if n_days < self.cfg.min_days_for_forecast:
            conf = min(conf, 0.2)
        return UsageForecast(kind, window[0], window[1], p10, point, p90, preds, weights, n_days, len(rel), cov,
                             conf, confidence_label(conf), notes)


# ----------------------------------------------------------------------------
# Slow-baseline guard: absence / return-day protection
# ----------------------------------------------------------------------------

BASELINE_MIN_DAYS = 14             # the long baseline is not trusted on fewer complete days than this


def baseline_guard(model: "UsageModel", asof: date, anomaly_triggers: list[str]) -> tuple[dict, list[float | None] | None]:
    """(report, per-slot baseline or None).

    The fast expert has a ~5-day memory, so after several unusually quiet days (the house empty, a holiday) it
    under-forecasts the first normal day back, and the pessimistic path built on it under-reserves. The guard
    keeps a longer, robust baseline = per slot the HIGHER of the `baseline_days` (30) median and the slow expert,
    and says it is ACTIVE when an abnormal / behaviour-shift / low-load condition is active or the fast profile's
    24 h total is below `baseline_guard_ratio` x the baseline's. When active the caller applies max(fast, baseline)
    to the pessimistic and hard paths ONLY: the median forecast is deliberately left alone."""
    cfg = model.cfg
    out: dict = {"active": False, "triggers": [], "applies_to": "pessimistic and hard scenario paths only",
                 "baseline_source": f"max(slow expert, {cfg.baseline_days}-day per-hour median)",
                 "fast_day_kwh": None, "baseline_day_kwh": None, "uplift_day_kwh": 0.0, "ratio": None}
    key = (asof, f"median{cfg.baseline_days}")
    med = model._profiles.get(key)
    if med is None:
        med = build_profile(model.table, asof, 0.0, cfg.baseline_days, cfg.winsor_k, mode="median")
        model._profiles[key] = med
    if med.n_days < BASELINE_MIN_DAYS:
        out["note"] = f"only {med.n_days} complete days of history: below the {BASELINE_MIN_DAYS}-day minimum, guard unavailable"
        return out, None
    fast, slow = model.profile(asof, "fast").values, model.profile(asof, "slow").values
    base: list[float | None] = []
    for f, sl, m in zip(fast, slow, med.values):
        cands = [x for x in (sl, m) if x is not None]
        base.append(max(cands) if cands else None)
    pairs = [(f, b) for f, b in zip(fast, base) if f is not None and b is not None]
    if len(pairs) < 20:
        out["note"] = "too few hour slots with both a fast and a baseline value"
        return out, None
    fast_day, base_day = sum(f for f, _b in pairs), sum(b for _f, b in pairs)
    out["fast_day_kwh"], out["baseline_day_kwh"] = round(fast_day, 2), round(base_day, 2)
    out["ratio"] = round(fast_day / base_day, 3) if base_day > 0 else None
    out["uplift_day_kwh"] = round(sum(max(0.0, b - f) for f, b in pairs), 2)
    triggers = list(anomaly_triggers)
    if base_day > 0 and fast_day < cfg.baseline_guard_ratio * base_day:
        triggers.append("FAST_BELOW_BASELINE")
    out["triggers"] = triggers
    out["active"] = bool(triggers)
    return out, (base if triggers else None)


# ----------------------------------------------------------------------------
# Weekday effect: measure, do not assume
# ----------------------------------------------------------------------------

def weekday_effect(history: History, cfg: SiteConfig, days: int = 120) -> dict:
    """Share of day-total variance (after removing a 7-day EWMA level) explained by weekday, and a plain
    F-statistic. The V1 model does not use weekday unless this is material; reporting it keeps that
    decision checkable as data accumulates."""
    table = DayTable(history, "load", cfg.tz)
    dts = sorted(d for d in table.days if table.total(d) is not None)[-days - 1:]
    totals = [table.total(d) for d in dts]
    res = []
    dow = []
    est = None
    for d, v in zip(dts, totals):
        if est is not None:
            res.append(v - est)
            dow.append(d.weekday())
        est = v if est is None else est + 0.3 * (v - est)
    if len(res) < 28:
        return {"n": len(res), "explained_variance": None, "f_stat": None, "material": False}
    gm = sum(res) / len(res)
    ss_tot = sum((r - gm) ** 2 for r in res)
    groups: dict[int, list[float]] = {}
    for r, w in zip(res, dow):
        groups.setdefault(w, []).append(r)
    ss_b = sum(len(g) * (sum(g) / len(g) - gm) ** 2 for g in groups.values())
    ss_w = ss_tot - ss_b
    k, n = len(groups), len(res)
    f = (ss_b / (k - 1)) / (ss_w / (n - k)) if ss_w > 0 and k > 1 else 0.0
    ev = ss_b / ss_tot if ss_tot > 0 else 0.0
    # F(6, ~100) 5 % critical value is ~2.2; require it AND a >= 8 % explained share to call it material
    return {"n": n, "explained_variance": round(ev, 4), "f_stat": round(f, 2), "material": bool(f > 2.2 and ev >= 0.08)}


# ----------------------------------------------------------------------------
# Next-hour forecast (pooled hourly residuals)
# ----------------------------------------------------------------------------

def hourly_pairs(model: UsageModel, asof: date, days: int = 60) -> list[tuple[float, float]]:
    """(predicted, actual) hourly load energy for the last `days` days before `asof`, each prediction
    made with the profile known at the time plus the one-hour-back persistence adjustment."""
    out = []
    d = asof - timedelta(days=days)
    while d < asof:
        slots = model.table.days.get(d)
        if slots is not None:
            prof = model.profile(d, "fast").values
            for s in range(1, 24):
                if slots[s] is None or slots[s - 1] is None or prof[s] is None or prof[s - 1] is None:
                    continue
                adj = nowcast_adjustments([slots[s - 1] - prof[s - 1]])[0]
                out.append((max(0.0, prof[s] + adj), slots[s]))
        d += timedelta(days=1)
    return out


def next_hour_forecast(model: UsageModel, now: datetime, last_hour_residual: float | None) -> UsageForecast:
    """Energy in [now, now+1h]: the slot expectation (apportioned across two slots), plus persistence from
    the latest complete hour, with an absolute band from pooled hourly residuals at a similar level."""
    asof = now.astimezone(model.tz).date()
    t1 = now + timedelta(hours=1)
    prof = model.profile(asof, "fast")
    base = window_sum(prof.values, now, t1, model.tz)
    if base is None:
        return UsageForecast("next_1h", now, t1, 0.0, 0.0, 0.0, {}, dict(PRIOR_WEIGHTS), prof.n_days, 0, None, 0.0,
                             "INSUFFICIENT", ["no usable history"])
    adj = nowcast_adjustments([last_hour_residual])[0] if last_hour_residual is not None else 0.0
    point = max(0.0, base + adj)
    pairs = [(p, a) for p, a in hourly_pairs(model, asof) if 0.6 * point <= p <= 1.4 * max(point, 0.2)]
    notes = []
    if len(pairs) >= 20:
        res = [a - p for p, a in pairs]
        lo, hi = stats.quantile(res, 0.10), stats.quantile(res, 0.90)
    else:
        sig = max(0.25, 0.3 * point)
        lo, hi = -1.2816 * sig, 1.2816 * sig
        notes.append("uncertainty from prior (too few similar hours)")
    if last_hour_residual is not None:
        notes.append(f"short-term persistence adjustment {adj:+.2f} kWh")
    conf = min(1.0, prof.n_days / float(model.cfg.min_days_for_high_confidence)) * (1.0 if len(pairs) >= 20 else 0.7)
    cov = None
    if len(pairs) >= 20:
        cov = sum(1 for p, a in pairs if lo <= a - p <= hi) / len(pairs)
    return UsageForecast("next_1h", now, t1, max(0.0, point + lo), point, point + hi, {"fast": base}, dict(PRIOR_WEIGHTS),
                         prof.n_days, len(pairs), cov, conf, confidence_label(conf), notes)
