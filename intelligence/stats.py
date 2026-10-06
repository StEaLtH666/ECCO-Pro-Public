"""Small, deterministic, dependency-free statistics helpers."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

MAD_TO_SIGMA = 1.4826


def clean(xs: Iterable[float | None]) -> list[float]:
    return [float(x) for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty sequence")
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


def quantile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (same convention as numpy's default)."""
    s = sorted(xs)
    if not s:
        raise ValueError("quantile of empty sequence")
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def mad(xs: Sequence[float]) -> float:
    m = median(xs)
    return median([abs(x - m) for x in xs])


def robust_sigma(xs: Sequence[float], floor: float = 0.0) -> float:
    return max(MAD_TO_SIGMA * mad(xs), floor) if len(xs) >= 3 else floor


def winsorise(x: float, reference: Sequence[float], k: float, sigma_floor: float) -> tuple[float, bool]:
    """Clip x to median(reference) +/- k robust sigma. Returns (value, was_clipped).

    With fewer than 5 reference points nothing is clipped (not enough evidence
    to call anything an outlier)."""
    if len(reference) < 5:
        return x, False
    m = median(reference)
    s = robust_sigma(reference, sigma_floor)
    hi, lo = m + k * s, m - k * s
    if x > hi:
        return hi, True
    if x < lo:
        return lo, True
    return x, False


def robust_ewma(
    xs: Sequence[float | None],
    alpha: float,
    k: float = 3.0,
    window: int = 28,
    sigma_floor: float = 0.0,
) -> tuple[float | None, int]:
    """Exponentially weighted mean, oldest -> newest, with outlier winsorising.

    Each observation is first clipped against the median +/- k robust sigma of
    the (unclipped) values that precede it, so one abnormal day can move the
    estimate by at most alpha * k * sigma. Missing values (None) are skipped.
    Returns (estimate or None, number_of_clipped_observations)."""
    est: float | None = None
    seen: list[float] = []
    clipped = 0
    for x in xs:
        if x is None:
            continue
        ref = seen[-window:]
        v, was = winsorise(x, ref, k, sigma_floor)
        clipped += 1 if was else 0
        est = v if est is None else est + alpha * (v - est)
        seen.append(x)
    return est, clipped


def mae(errors: Sequence[float]) -> float:
    return sum(abs(e) for e in errors) / len(errors)


def rmse(errors: Sequence[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors))
