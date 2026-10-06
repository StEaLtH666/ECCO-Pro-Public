"""Walk-forward backtest of the usage model against history (offline, deterministic).

Every forecast for day D uses only history strictly before D (profiles, weights
and the residuals that set its interval). This is the same code path the live
engine runs, so the numbers are what the engine would have achieved."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from . import stats
from .config import SiteConfig
from .history import History
from .usage import UsageModel, fixed_window, standard_windows


@dataclass
class BacktestRow:
    kind: str
    day: date
    p10: float
    p50: float
    p90: float
    actual: float
    err: float          # actual - p50  (positive = under-forecast)
    expert_preds: dict


def backtest_usage(history: History, cfg: SiteConfig, start: date, end: date,
                   kinds: tuple[str, ...] | None = None) -> list[BacktestRow]:
    model = UsageModel(history, cfg)
    wins = standard_windows(cfg)
    rows: list[BacktestRow] = []
    for kind, (a, b) in wins.items():
        if kinds and kind not in kinds:
            continue
        fn = fixed_window(a, b, model.tz)
        d = start
        while d <= end:
            w = fn(d)
            actual = history.energy_scaled("load", w[0], w[1], 0.8)
            if actual is not None:
                f = model.forecast(kind, w, fn, d)
                if f.label != "INSUFFICIENT" and f.p50 > 0:
                    rows.append(BacktestRow(kind, d, f.p10, f.p50, f.p90, actual, actual - f.p50, f.expert_preds))
            d += timedelta(days=1)
    return rows


def summarise(rows: list[BacktestRow]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for kind in sorted({r.kind for r in rows}):
        rs = [r for r in rows if r.kind == kind]
        errs = [r.err for r in rs]
        out[kind] = {
            "n": len(rs),
            "mean_actual": round(sum(r.actual for r in rs) / len(rs), 3),
            "mae": round(stats.mae(errs), 3),
            "rmse": round(stats.rmse(errs), 3),
            "bias": round(sum(errs) / len(errs), 3),
            "coverage_p10_p90": round(sum(1 for r in rs if r.p10 <= r.actual <= r.p90) / len(rs), 3),
            "mean_band_width": round(sum(r.p90 - r.p10 for r in rs) / len(rs), 3),
            "mape_pct": round(100.0 * sum(abs(r.err) / r.actual for r in rs if r.actual > 0.2) / max(1, sum(1 for r in rs if r.actual > 0.2)), 1),
        }
    return out


def expert_comparison(rows: list[BacktestRow]) -> dict[str, dict[str, float]]:
    """MAE of each individual expert and of the ensemble, per window kind."""
    out: dict[str, dict[str, float]] = {}
    for kind in sorted({r.kind for r in rows}):
        rs = [r for r in rows if r.kind == kind]
        d = {"ensemble": stats.mae([r.err for r in rs])}
        for e in rs[0].expert_preds:
            d[e] = stats.mae([r.actual - r.expert_preds[e] for r in rs])
        out[kind] = {k: round(v, 3) for k, v in d.items()}
    return out
