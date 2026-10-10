"""The normalised evidence model: per-entity state series, firmware log events and ingest diagnostics.

A Series holds the rows Home Assistant recorded for one entity, in time order. Home Assistant records a row when the state
CHANGES (or the entity becomes unavailable / available again), so a state holds from its row until the next row. Nothing
here ever invents a value: an instant before the first row has NO evidence, `unavailable` / `unknown` are kept as such, and
a value that cannot be read as the entity's kind is reported, never coerced.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MISSING_STATES = frozenset({"unavailable", "unknown", "none", "nan", ""})


@dataclass(frozen=True)
class Sample:
    t: datetime  # aware UTC
    raw: str
    ref: str  # where the row came from: "<input>#<entity>[<i>]" or "<input>:<line>"


@dataclass
class Series:
    key: str
    entity_id: str
    samples: list = field(default_factory=list)
    _times: list | None = None

    def finalise(self) -> None:
        self.samples.sort(key=lambda s: s.t)
        self._times = [s.t for s in self.samples]

    @property
    def times(self) -> list:
        if self._times is None:
            self.finalise()
        return self._times

    def at(self, t: datetime) -> Sample | None:
        """The row in force at `t` (the latest row at or before it), or None when there is no earlier row."""
        i = bisect.bisect_right(self.times, t) - 1
        return self.samples[i] if i >= 0 else None

    def between(self, a: datetime, b: datetime) -> list:
        lo = bisect.bisect_left(self.times, a)
        hi = bisect.bisect_right(self.times, b)
        return self.samples[lo:hi]

    def segments(self, a: datetime, b: datetime) -> list:
        """Time-weighted [start, end, sample-or-None] pieces covering [a, b): None where no row is in force yet."""
        out = []
        cur = self.at(a)
        t = a
        for s in self.between(a, b):
            if s.t <= a:
                cur = s
                continue
            if s.t > t:
                out.append([t, s.t, cur])
            t = s.t
            cur = s
        if b > t:
            out.append([t, b, cur])
        return out


def is_missing(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in MISSING_STATES


def as_float(raw: str | None) -> float | None:
    if is_missing(raw):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def as_bool(raw: str | None) -> bool | None:
    if is_missing(raw):
        return None
    r = raw.strip().lower()
    if r in ("on", "true", "1", "1.0"):
        return True
    if r in ("off", "false", "0", "0.0"):
        return False
    return None


@dataclass
class LogEvent:
    t: datetime
    level: str
    tag: str
    msg: str
    ref: str
    kind: str = "other"
    fields: dict = field(default_factory=dict)


@dataclass
class Diagnostic:
    severity: str  # "error" (data rejected) | "warning" (data kept, but suspicious) | "info"
    code: str
    detail: str
    ref: str = ""


@dataclass
class InputInfo:
    path: str
    fmt: str
    sha256: str
    rows: int = 0
    accepted: int = 0
    rejected: int = 0
    first: datetime | None = None
    last: datetime | None = None


@dataclass
class Evidence:
    series: dict = field(default_factory=dict)  # key -> Series
    logs: list = field(default_factory=list)  # LogEvent, time-ordered
    inputs: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    unknown_entities: dict = field(default_factory=dict)  # entity id -> rows ignored
    invalid_values: dict = field(default_factory=dict)  # key -> [(ref, raw)]

    def get(self, key: str) -> Series | None:
        return self.series.get(key)

    def has(self, key: str) -> bool:
        s = self.series.get(key)
        return bool(s and s.samples)

    def add(self, key: str, entity_id: str, sample: Sample) -> None:
        s = self.series.get(key)
        if s is None:
            s = self.series[key] = Series(key, entity_id)
        elif s.entity_id != entity_id and entity_id not in s.entity_id.split(" | "):
            s.entity_id = f"{s.entity_id} | {entity_id}"
        s.samples.append(sample)
        s._times = None

    def diag(self, severity: str, code: str, detail: str, ref: str = "") -> None:
        self.diagnostics.append(Diagnostic(severity, code, detail, ref))

    def finalise(self) -> None:
        for s in self.series.values():
            # drop exact duplicates (same instant, same state) that several overlapping exports produce
            s.samples.sort(key=lambda x: (x.t, x.raw))
            dedup = []
            for x in s.samples:
                if dedup and dedup[-1].t == x.t and dedup[-1].raw == x.raw:
                    continue
                dedup.append(x)
            s.samples = dedup
            s.finalise()
        self.logs.sort(key=lambda e: e.t)

    def all_times(self) -> list:
        ts = [x.t for s in self.series.values() for x in s.samples]
        ts.extend(e.t for e in self.logs)
        ts.sort()
        return ts


# ---------------------------------------------------------------------------------------------------------------------------
# Monotonic ("since boot") series
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class CounterResult:
    available: bool
    delta: float | None  # increase inside [a, b], restart-aware; None when it cannot be established
    first: Sample | None
    last: Sample | None
    resets: list  # [(Sample before, Sample after)] decreases (a restart signal for a since-boot counter)
    increments: list  # [(t, amount, ref)] every increase, in time order
    spans_window: bool  # a valid value is in force at a (or within tolerance) and is seen near b
    note: str = ""


def counter_delta(series: Series | None, a: datetime, b: datetime, tol: timedelta = timedelta(minutes=10)) -> CounterResult:
    """Restart-aware increase of a since-boot counter inside [a, b].

    Values are taken from valid numeric rows only (unavailable / unknown / non-numeric rows are skipped, never read as 0). The
    baseline is the value in force at `a` (or the first valid value after it). A decrease is a reset: the post-reset value
    counts in full (the counter restarted from zero). `spans_window` is False when the evidence starts more than `tol` after `a`
    or ends more than `tol` before `b`; the delta is then a lower bound."""
    if series is None or not series.samples:
        return CounterResult(False, None, None, None, [], [], False, "no rows")
    vals = []
    base = None
    for s in series.samples:
        v = as_float(s.raw)
        if v is None:
            continue
        if s.t <= a:
            base = (s, v)
            continue
        if s.t > b:
            break
        vals.append((s, v))
    if base is None and not vals:
        return CounterResult(False, None, None, None, [], [], False, "no valid numeric value in the window")
    seq = ([base] if base else []) + vals
    resets, incs = [], []
    total = 0.0
    for (s0, v0), (s1, v1) in zip(seq, seq[1:]):
        if v1 >= v0:
            if v1 > v0:
                incs.append((s1.t, v1 - v0, s1.ref))
            total += v1 - v0
        else:
            resets.append((s0, s1))
            if v1 > 0:
                incs.append((s1.t, v1, s1.ref))
            total += v1
    first = seq[0][0]
    last = seq[-1][0]
    starts_ok = base is not None or (first.t - a) <= tol
    # Home Assistant records a counter only when it changes: the row in force at b must still be a valid value (an
    # `unavailable` row there means the end of the window is not covered). Recording continuity itself is judged elsewhere.
    nxt = series.at(b)
    ends_ok = nxt is not None and as_float(nxt.raw) is not None
    return CounterResult(True, total, first, last, resets, incs, bool(starts_ok and ends_ok),
                         "" if (starts_ok and ends_ok) else "evidence does not span the window: the delta is a lower bound")
