"""Verdicts, decision thresholds, findings and the shared analysis context."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from .evidence import Evidence
from .timeutil import UTC, fmt_local, stamp

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
_RANK = {PASS: 0, WARNING: 1, INSUFFICIENT: 2, FAIL: 3}

# basis of a finding
CONFIRMED = "confirmed"  # read directly from a firmware counter, state string or log line
INFERRED = "inferred"  # derived from timing, trends or the absence of a row; plausible, not proven
MIXED = "mixed"
NONE = "none"  # nothing to base it on

# FB-D1 went live on the ESP32-S3 at 2026-10-04 23:14:37 BST (owner OTA, reset "Reboot request from esphome.ota").
DEFAULT_SOAK_START = datetime(2026, 10, 4, 22, 14, 37, tzinfo=UTC)
DEFAULT_SOAK_DAYS = 7


def worst(*verdicts: str) -> str:
    vs = [v for v in verdicts if v]
    return max(vs, key=lambda v: _RANK[v]) if vs else PASS


@dataclass
class Rules:
    """Every decision threshold the analyser applies. All are reported in the JSON so a verdict can be re-derived by hand."""
    # window / continuity
    boot_grace_s: int = 600  # a boot this soon after the soak start is the soak's own (OTA) boot, not a restart
    restart_cluster_s: int = 600  # restart signals this close together are one restart
    gap_s: int = 300  # no witness row for longer than this = an evidence gap
    gap_warn_s: int = 900
    gap_insufficient_s: int = 7200
    coverage_pass: float = 0.98
    coverage_min: float = 0.90
    day_coverage_min: float = 0.50
    clock_skew_warn_s: float = 5.0  # NTP Time string vs Home Assistant row time
    # RTC
    threshold_s: float | None = None  # Clock Correction Threshold when the export has no setting row (None = unknown)
    daylight_pv_w: float = 20.0
    high_pv_w: float = 1500.0
    daylight_hours: tuple = (7, 19)  # local fallback when there is no PV evidence (inferred)
    drift_night_s_per_min: float = 0.5  # measured: 0 at night
    drift_low_pv_s_per_min: float = 4.5  # measured: +1 .. +4.5 s/min at 20-1500 W
    drift_high_pv_s_per_min: float = 7.5  # measured: -7 s/min at >= 2 kW
    staleness_allowance_s: float = 10.0  # measured: register image 0-10 s stale
    pair_tolerance_s: float = 3.0
    trend_window_s: int = 600
    read_match_s: float = 3.0
    corrections_per_day_warn: int = 48
    corrections_per_day_fail: int = 144
    failed_corrections_fail: int = 3
    consecutive_failures_fail: int = 2
    aborts_fail: int = 2
    correction_lock_warn_s: float = 50.0  # legitimate holds are bounded at about 50 s
    correction_lock_fail_s: float = 100.0  # the 90 s breaker must have released by then
    edge_tolerance_s: float = 2.0
    # B10
    b10_match_pass: float = 0.95
    b10_match_fail: float = 0.80  # the FB-D1 harness floor (F3: >= 80 % MATCH under -7 s/min drift)
    b10_coverage_min: float = 0.90
    b10_recovery_warn_s: float = 120.0
    b10_lock_overlap_fail_s: float = 12.0
    # polling
    block_b_gap_s: float = 150.0  # two missed 60 s polls
    block_b_fail_s: float = 600.0
    telemetry_gap_s: float = 60.0
    catchup_early_s: float = 50.0
    read_failures_fail_per_day: float = 50.0
    offline_fail_s: float = 600.0
    # safety
    write_lock_warn_s: float = 60.0
    write_lock_leak_s: float = 180.0
    max_write_attempts_per_correction: int = 3

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Criterion:
    id: str
    area: str
    title: str
    verdict: str
    basis: str
    summary: str
    required: bool = True
    reasons: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    refs: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "area": self.area, "title": self.title, "verdict": self.verdict, "basis": self.basis,
                "required": self.required, "summary": self.summary, "reasons": self.reasons, "metrics": self.metrics,
                "refs": self.refs[:40]}


@dataclass
class Event:
    t: datetime | None
    area: str
    severity: str  # FAIL | WARNING | INFO
    code: str
    summary: str
    basis: str
    refs: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"time": stamp(self.t), "area": self.area, "severity": self.severity, "code": self.code, "summary": self.summary,
                "basis": self.basis, "refs": self.refs[:12], "details": self.details}

    def line(self) -> str:
        return f"{fmt_local(self.t) or 'n/a'} [{self.severity}] {self.code}: {self.summary}"


@dataclass
class Day:
    index: int
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"D{self.index}"

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class Ctx:
    ev: Evidence
    rules: Rules
    start: datetime
    end: datetime
    as_of: datetime | None = None
    days: list = field(default_factory=list)
    events: list = field(default_factory=list)
    # shared intermediate results (filled by the areas in order)
    gaps: list = field(default_factory=list)  # [(a, b)] evidence gaps inside the window
    unavailable: list = field(default_factory=list)  # [(a, b)] device-unavailable intervals
    restarts: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    lease_intervals: list = field(default_factory=list)
    config_offline: list = field(default_factory=list)

    @property
    def window_s(self) -> float:
        return (self.end - self.start).total_seconds()

    def event(self, t, area, severity, code, summary, basis, refs=None, **details) -> Event:
        e = Event(t, area, severity, code, summary, basis, list(refs or []), details)
        self.events.append(e)
        return e

    def day_of(self, t: datetime) -> Day | None:
        for d in self.days:
            if d.start <= t < d.end:
                return d
        return None


def make_days(start: datetime, end: datetime) -> list:
    out, i, a = [], 1, start
    while a < end:
        b = min(a + timedelta(days=1), end)
        out.append(Day(i, a, b))
        a, i = b, i + 1
    return out


def overlap_s(a: datetime, b: datetime, intervals) -> float:
    tot = 0.0
    for x, y in intervals:
        lo, hi = max(a, x), min(b, y)
        if hi > lo:
            tot += (hi - lo).total_seconds()
    return tot


def merge_intervals(intervals) -> list:
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def num(x):
    """A count for display: 3.0 -> 3, None -> 'unavailable'."""
    if x is None:
        return "unavailable"
    return int(x) if float(x).is_integer() else x


def pct(x: float | None) -> float | None:
    return None if x is None else round(100.0 * x, 3)
