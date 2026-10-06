"""PV: learn how far to trust each forecast source, and correct it.

Evidence (docs/intelligence/PROTOTYPE_RESULTS.md section 2, private data, aggregate): a raw
day-ahead forecast source can over-predict an array by up to about a factor of two in autumn and
winter while being close to unbiased in midsummer; a trailing 7-day median ratio roughly halved
the error and beat 5, 10, 14 and 21 days in every period tried, because the ratio itself drifts
with the season. The learner here is exactly that, kept
deliberately simple: a winsorised trailing median of actual / forecast per
source, an honest walk-forward interval, and a persistence fallback when no
forecast exists. Nothing is hidden: the correction factor is reported.

PLAUSIBILITY GUARD (a forecast source can be wrong by far more than the ratio learner can absorb, e.g. a unit
error or a stale value 10x too high). Three simple ceilings, each reported with the verdict:
  site_physical  pv_array_kwp x pv_max_kwh_per_kwp_day (not data-driven; only when the site size is configured)
  history_max    pv_history_headroom x the best day observed in the last ~400 days
  recent_max     pv_recent_headroom  x the best day observed in the last pv_recent_days days (catches an
                 out-of-season value that the all-time maximum would let through)
A source whose raw value exceeds the physical ceiling, or whose corrected value exceeds the lowest ceiling, is
REJECTED: it is not used, the notes and `plausibility` say why, and the forecast falls back to persistence at LOW
confidence. Rejecting is the safe direction for the advisor (less PV assumed => more battery retained)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import stats
from .config import SiteConfig
from .history import History
from .timeutil import day_bounds, zone

RATIO_WINDOW_DAYS = 7
RATIO_MIN_PAIRS = 5
RATIO_CLIP = (0.10, 3.0)
MIN_FORECAST_KWH = 1.0          # ratios from tiny forecasts are noise
RESIDUAL_DAYS = 90
PRIOR_REL_SIGMA = 0.45          # used until enough walk-forward residuals exist


def actual_pv_kwh(history: History, day: date, tz_name: str) -> float | None:
    t0, t1 = day_bounds(day, zone(tz_name))
    return history.energy_scaled("pv", t0, t1, 0.9)


@dataclass
class PvForecast:
    day: date
    source: str                          # forecast source used, or "persistence"
    raw_kwh: float | None
    ratio: float | None                  # correction factor applied
    p10: float
    p50: float
    p90: float
    n_pairs: int
    mae_corrected: float | None          # trailing walk-forward MAE of the corrected forecast
    mae_raw: float | None
    confidence: float
    label: str
    notes: list[str] = field(default_factory=list)
    inflation: float = 1.0               # >1 when the band was widened by coverage feedback
    plausibility: dict = field(default_factory=dict)   # verdict + ceilings + any rejected sources (see module docstring)

    def to_dict(self) -> dict:
        return {
            "inflation": round(self.inflation, 3), "usable": self.label != "INSUFFICIENT", "day": self.day.isoformat(), "source": self.source, "raw_kwh": None if self.raw_kwh is None else round(self.raw_kwh, 2),
            "ratio": None if self.ratio is None else round(self.ratio, 3),
            "p10": round(self.p10, 2), "p50": round(self.p50, 2), "p90": round(self.p90, 2),
            "n_pairs": self.n_pairs,
            "mae_corrected": None if self.mae_corrected is None else round(self.mae_corrected, 2),
            "mae_raw": None if self.mae_raw is None else round(self.mae_raw, 2),
            "confidence": round(self.confidence, 3), "label": self.label, "notes": list(self.notes),
            "plausibility": self.plausibility,
        }


class PvModel:
    """`forecasts` is {source: {local_date: day-ahead forecast kWh as issued before dawn}}."""

    def __init__(self, history: History, cfg: SiteConfig, forecasts: dict[str, dict[date, float]]):
        self.history = history
        self.cfg = cfg
        self.forecasts = forecasts
        self._actual: dict[date, float | None] = {}

    def actual(self, day: date) -> float | None:
        if day not in self._actual:
            self._actual[day] = actual_pv_kwh(self.history, day, self.cfg.tz)
        return self._actual[day]

    def _pairs(self, source: str, before: date, n_days: int) -> list[tuple[date, float, float]]:
        out = []
        f = self.forecasts.get(source, {})
        d = before - timedelta(days=n_days)
        while d < before:
            fc, act = f.get(d), self.actual(d)
            if fc is not None and act is not None and fc >= MIN_FORECAST_KWH:
                out.append((d, fc, act))
            d += timedelta(days=1)
        return out

    def ratio(self, source: str, before: date) -> tuple[float | None, int]:
        pairs = self._pairs(source, before, RATIO_WINDOW_DAYS + 7)[-RATIO_WINDOW_DAYS:]
        if len(pairs) < RATIO_MIN_PAIRS:
            return None, len(pairs)
        rs = [max(RATIO_CLIP[0], min(RATIO_CLIP[1], a / f)) for _d, f, a in pairs]
        return stats.median(rs), len(pairs)

    def walk_forward(self, source: str, asof: date, n_days: int = RESIDUAL_DAYS
                     ) -> list[tuple[date, float, float, float]]:
        """(day, raw, corrected, actual) for each scored day before `asof`, correcting with the ratio
        known at the time."""
        out = []
        f = self.forecasts.get(source, {})
        d = asof - timedelta(days=n_days)
        while d < asof:
            fc, act = f.get(d), self.actual(d)
            if fc is not None and act is not None and fc >= MIN_FORECAST_KWH:
                r, n = self.ratio(source, d)
                if r is not None:
                    out.append((d, fc, fc * r, act))
            d += timedelta(days=1)
        return out

    def plausibility_limits(self, day: date) -> dict[str, float]:
        """The kWh/day ceilings that apply to a forecast for `day` (only those that can be computed)."""
        cfg = self.cfg
        caps: dict[str, float] = {}
        if cfg.pv_array_kwp is not None:
            caps["site_physical"] = round(cfg.pv_array_kwp * cfg.pv_max_kwh_per_kwp_day, 2)
        obs = [(d, self.actual(d)) for d in (day - timedelta(days=k) for k in range(1, 401))]
        obs = [(d, a) for d, a in obs if a is not None and math.isfinite(a)]
        if len(obs) >= 14:
            caps["history_max"] = round(cfg.pv_history_headroom * max(a for _d, a in obs), 2)
        recent = [a for d, a in obs if (day - d).days <= cfg.pv_recent_days]
        if len(recent) >= 10:
            caps["recent_max"] = round(cfg.pv_recent_headroom * max(recent), 2)
        return caps

    def forecast_day(self, day: date, raw_by_source: dict[str, float]) -> PvForecast:
        """Corrected PV for `day` given today's raw forecasts per source. Picks the source with the best
        trailing corrected MAE (ties/short history -> first available)."""
        notes: list[str] = []
        best = None
        caps = self.plausibility_limits(day)
        rejected: list[dict] = []
        for src, raw in sorted(raw_by_source.items()):
            if not (isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) and raw >= 0.0):
                notes.append(f"{src} forecast ignored: {raw!r} is not a finite non-negative kWh value")
                continue
            r, n = self.ratio(src, day)
            if r is None:
                if "site_physical" in caps and raw > caps["site_physical"]:
                    rejected.append({"source": src, "raw_kwh": round(raw, 2), "corrected_kwh": None,
                                     "reason": "raw value exceeds the physical limit of the array", "limit": "site_physical",
                                     "limit_kwh": caps["site_physical"]})
                continue
            point_c = raw * r
            breach = None
            if "site_physical" in caps and raw > caps["site_physical"]:
                breach = ("site_physical", f"raw value exceeds the physical limit of the array ({caps['site_physical']:.0f} kWh/day)", raw)
            else:
                for name in ("history_max", "recent_max"):
                    if name in caps and point_c > caps[name]:
                        breach = (name, f"corrected value exceeds the {'all-time' if name == 'history_max' else 'recent'} "
                                        f"observed-output ceiling ({caps[name]:.0f} kWh/day)", point_c)
                        break
            if breach is not None:
                rejected.append({"source": src, "raw_kwh": round(raw, 2), "corrected_kwh": round(point_c, 2),
                                 "reason": breach[1], "limit": breach[0], "limit_kwh": caps[breach[0]]})
                notes.append(f"{src} forecast REJECTED as implausible: {raw:.1f} kWh raw / {point_c:.1f} kWh corrected; {breach[1]}")
                continue
            wf = self.walk_forward(src, day, 30)
            mae_c = stats.mae([a - c for _d, _f, c, a in wf]) if len(wf) >= 7 else None
            mae_r = stats.mae([a - f for _d, f, _c, a in wf]) if len(wf) >= 7 else None
            key = (mae_c if mae_c is not None else 1e9, src)
            if best is None or key < best[0]:
                best = (key, src, raw, r, n, mae_c, mae_r)
        verdict = {"verdict": "REJECTED" if rejected else ("OK" if caps else "UNCHECKED"), "limits_kwh": caps, "rejected": rejected}
        if best is None:
            why = ("every usable forecast source was rejected as implausible; using persistence" if rejected
                   else "no forecast source has enough scored history; using persistence")
            pf = self._persistence(day, notes + [why])
            pf.plausibility = verdict
            if rejected:
                pf.confidence = min(pf.confidence, 0.3)        # LOW at best: the inputs were not credible
                pf.label = "INSUFFICIENT" if pf.label == "INSUFFICIENT" else "LOW"
            return pf
        _k, src, raw, r, n, mae_c, mae_r = best
        point = raw * r
        wf = self.walk_forward(src, day, RESIDUAL_DAYS)
        rel = [(a - c) / c for _d, _f, c, a in wf if c > 0.5]
        if len(rel) >= 20:
            lo, hi = stats.quantile(rel, 0.10), stats.quantile(rel, 0.90)
            sig = stats.robust_sigma(rel, 0.05)
            lo, hi = min(lo, -1.2816 * sig), max(hi, 1.2816 * sig)
        else:
            lo, hi = -1.2816 * PRIOR_REL_SIGMA, 1.2816 * PRIOR_REL_SIGMA
            notes.append("PV uncertainty from prior (too few walk-forward residuals)")
        # Coverage feedback: when the band would not have held the most recent days (regime change, e.g. autumn
        # decline), widen it in proportion rather than keep trusting a stale spread.
        infl = 1.0
        recent = [(a - c) / c for _d, _f, c, a in wf[-21:] if c > 0.5]
        if len(recent) >= 10:
            cov = sum(1 for r in recent if lo <= r <= hi) / len(recent)
            if cov < 0.70:
                infl = min(1.5, 0.80 / max(cov, 0.4))
                lo, hi = lo * infl, hi * infl
                notes.append(f"PV band widened x{infl:.2f}: it only held {cov:.0%} of the last {len(recent)} days")
        p10, p90 = max(0.0, point * (1 + max(lo, -0.95))), point * (1 + hi)
        if mae_r is not None and mae_c is not None and mae_r > 1.5 * max(mae_c, 0.1):
            notes.append(f"raw {src} forecast is unreliable here: trailing raw MAE {mae_r:.1f} kWh vs {mae_c:.1f} kWh after correction")
        conf = min(1.0, n / RATIO_WINDOW_DAYS) * (0.6 + 0.4 * min(1.0, len(rel) / 20.0))
        if infl > 1.0:
            conf *= 0.6      # the band recently failed to hold: do not present this forecast as HIGH confidence
        if point > 0 and (p90 - p10) / point > 1.2:
            conf *= 0.7
            notes.append("PV band is wide relative to the forecast")
        from .usage import confidence_label
        return PvForecast(day, src, raw, r, p10, point, p90, n, mae_c, mae_r, conf, confidence_label(conf), notes, infl, verdict)

    def _persistence(self, day: date, notes: list[str]) -> PvForecast:
        days = []
        d = day - timedelta(days=1)
        while len(days) < 30 and d >= day - timedelta(days=60):
            a = self.actual(d)
            if a is not None:
                days.append(a)
            d -= timedelta(days=1)
        days = list(reversed(days))
        if len(days) < 5:
            from .usage import confidence_label
            return PvForecast(day, "none", None, None, 0.0, 0.0, 0.0, len(days), None, None, 0.0, "INSUFFICIENT",
                              notes + ["no PV history"])
        est, _ = stats.robust_ewma(days, 0.3, 3.0, 28, 0.5)
        sig = max(stats.robust_sigma(days, 1.0), 0.35 * est)
        notes.append("persistence only: no forecast correction available")
        from .usage import confidence_label
        conf = 0.3
        return PvForecast(day, "persistence", None, None, max(0.0, est - 1.2816 * sig), est, est + 1.2816 * sig,
                          len(days), None, None, conf, confidence_label(conf), notes)


def pv_hour_shape(history: History, cfg: SiteConfig, asof: date, n_days: int = 14) -> list[float]:
    """Fraction of a day's PV that arrives in each local hour slot: per-slot median over the last n_days,
    renormalised. Adapts to the season within about two weeks."""
    tz = zone(cfg.tz)
    slots: list[list[float]] = [[] for _ in range(24)]
    d = asof - timedelta(days=1)
    seen = 0
    while seen < n_days and d >= asof - timedelta(days=n_days + 10):
        t0, t1 = day_bounds(d, tz)
        tot = history.energy_scaled("pv", t0, t1, 0.9)
        if tot is not None and tot > 1.0:
            per = [0.0] * 24
            for rec, s, frac in history.hours_between(t0, t1):
                if rec is not None and "pv" in rec.e:
                    from .timeutil import utc_from_ts
                    per[utc_from_ts(s).astimezone(tz).hour] += rec.e["pv"] * frac
            for h in range(24):
                slots[h].append(per[h] / tot)
            seen += 1
        d -= timedelta(days=1)
    shape = [stats.median(v) if v else 0.0 for v in slots]
    total = sum(shape)
    return [x / total for x in shape] if total > 0 else [0.0] * 24


def useful_pv_start(history: History, cfg: SiteConfig, day: date) -> datetime | None:
    """First moment on local `day` when PV reaches cfg.useful_pv_threshold_w, interpolating linearly
    between hourly means placed at mid-hour. Resolution is therefore ~30 min at best."""
    tz = zone(cfg.tz)
    t0, t1 = day_bounds(day, tz)
    thr = cfg.useful_pv_threshold_w
    prev_mid = None
    prev_w = None
    from .timeutil import ts, utc_from_ts, HOUR
    s = ts(t0)
    while s < ts(t1):
        rec = history.get(s)
        w = None
        if rec is not None:
            w = rec.pv_w_mean if rec.pv_w_mean is not None else (rec.e["pv"] * 1000.0 if "pv" in rec.e else None)
        if w is not None and utc_from_ts(s).astimezone(tz).hour >= 3:
            mid = s + HOUR // 2
            if w >= thr:
                if prev_w is not None and prev_w < thr and w > prev_w:
                    frac = (thr - prev_w) / (w - prev_w)
                    return utc_from_ts(int(prev_mid + frac * (mid - prev_mid)))
                return utc_from_ts(s)
            prev_mid, prev_w = mid, w
        s += HOUR
    return None
