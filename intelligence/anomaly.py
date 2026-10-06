"""Load anomaly detection and neutral recurring-signature discovery.

Everything here is descriptive. It never names an appliance: aggregate CT data
cannot identify one. A recurring pattern gets a neutral label ("Recurring load
signature A: ~2.0 kW for <8 min, usually around 10:00") and only receives an
appliance name if the caller supplies independent evidence (a name map keyed
by the neutral label), which V1 does not.

Thresholds are robust (median / MAD of the model's own recent residuals), so
they scale with how noisy this house normally is, and they need persistence:
one high hour is not an anomaly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import stats
from .config import SiteConfig
from .history import History
from .timeutil import HOUR, ts, utc_from_ts, zone
from .usage import SLOT_SIGMA_FLOOR_KWH, UsageModel

SUSTAINED_Z = 2.5                 # robust z of hourly residual
SUSTAINED_MIN_HOURS = 3           # consecutive hours
MIN_EXCESS_KWH_PER_H = 0.40       # and at least this much above expectation (0.4 kW)
BASE_LOAD_HOURS = (1, 2, 3, 4)    # local hours that define the overnight base load
UNUSUAL_DAY_Z = 2.5


@dataclass
class Anomaly:
    code: str                      # SUSTAINED_HIGH_LOAD | LOW_LOAD | HIGH_OVERNIGHT_BASE | UNUSUAL_DAY | BEHAVIOUR_SHIFT
    severity: str                  # INFO | WATCH | ABNORMAL
    text: str
    value: float | None = None
    since: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "text": self.text, "value": self.value, "since": self.since}


@dataclass
class AnomalyReport:
    anomalies: list[Anomaly] = field(default_factory=list)
    abnormal_load_now: bool = False
    excess_kw_now: float = 0.0
    base_load_kw: float | None = None
    base_load_norm_kw: float | None = None

    def to_dict(self) -> dict:
        return {"abnormal_load_now": self.abnormal_load_now, "excess_kw_now": round(self.excess_kw_now, 3),
                "base_load_kw": None if self.base_load_kw is None else round(self.base_load_kw, 3),
                "base_load_norm_kw": None if self.base_load_norm_kw is None else round(self.base_load_norm_kw, 3),
                "anomalies": [a.to_dict() for a in self.anomalies]}


def hourly_residuals_today(model: UsageModel, now: datetime, hours: int = 8) -> list[tuple[datetime, float, float, float]]:
    """(hour_start, actual, expected, robust_z) for the last `hours` COMPLETE hours before `now`."""
    tz = model.tz
    asof = now.astimezone(tz).date()
    prof = model.profile(asof, "fast")
    out = []
    s = ts(now) - (ts(now) % HOUR)
    for k in range(hours, 0, -1):
        h0 = s - k * HOUR
        rec = model.history.get(h0)
        if rec is None or "load" not in rec.e:
            continue
        loc = utc_from_ts(h0).astimezone(tz)
        # the profile for `asof` is built from days strictly before today; a window that started yesterday uses the
        # same slot values (slots are time-of-day, not date, specific)
        exp = prof.values[loc.hour]
        if exp is None:
            continue
        sig = max(prof.sigma[loc.hour], SLOT_SIGMA_FLOOR_KWH)
        out.append((utc_from_ts(h0), rec.e["load"], exp, (rec.e["load"] - exp) / sig))
    return out


def detect(model: UsageModel, now: datetime, cfg: SiteConfig) -> AnomalyReport:
    rep = AnomalyReport()
    tz = model.tz
    asof = now.astimezone(tz).date()
    if model.profile(asof, "fast").n_days < cfg.min_days_for_forecast:
        return rep

    # --- sustained abnormal load (the last complete hours, newest first) -----------------------------------
    res = hourly_residuals_today(model, now, 8)
    run = 0
    excess = 0.0
    since = None
    for t, act, exp, z in reversed(res):
        if z >= SUSTAINED_Z and (act - exp) >= MIN_EXCESS_KWH_PER_H:
            run += 1
            excess += act - exp
            since = t
        else:
            break
    if run >= SUSTAINED_MIN_HOURS:
        rep.abnormal_load_now = True
        rep.excess_kw_now = excess / run
        rep.anomalies.append(Anomaly(
            "SUSTAINED_HIGH_LOAD", "ABNORMAL",
            f"House load has been about {excess / run:.1f} kW above its normal level for the last {run} hours "
            f"(since {since.astimezone(tz).strftime('%H:%M')}).", round(excess / run, 3), since.isoformat()))
    elif run == 2:
        rep.anomalies.append(Anomaly(
            "SUSTAINED_HIGH_LOAD", "WATCH",
            f"House load has been about {excess / run:.1f} kW above normal for 2 hours.", round(excess / run, 3),
            since.isoformat() if since else None))
    # sustained LOW load is informative for away/holiday detection
    runl = 0
    for t, act, exp, z in reversed(res):
        if z <= -SUSTAINED_Z and (exp - act) >= MIN_EXCESS_KWH_PER_H:
            runl += 1
        else:
            break
    if runl >= SUSTAINED_MIN_HOURS:
        rep.anomalies.append(Anomaly("LOW_LOAD", "INFO", f"House load has been well below normal for {runl} hours.", float(runl)))

    # --- overnight base load: median of the 01-05 local hours, last night vs the last 28 nights ---------------
    def night_base(day: date) -> float | None:
        slots = model.table.days.get(day)
        if not slots:
            return None
        vals = [slots[h] for h in BASE_LOAD_HOURS if slots[h] is not None]
        return stats.median(vals) if len(vals) >= 3 else None
    nights = [night_base(asof - timedelta(days=k)) for k in range(1, 30)]
    last = nights[0] if nights else None
    hist = stats.clean(nights[1:])
    if last is not None and len(hist) >= 14:
        norm = stats.median(hist)
        sig = max(stats.robust_sigma(hist, 0.05), 0.05)
        rep.base_load_kw, rep.base_load_norm_kw = last, norm
        z = (last - norm) / sig
        if z >= SUSTAINED_Z and last - norm >= 0.15:
            rep.anomalies.append(Anomaly(
                "HIGH_OVERNIGHT_BASE", "WATCH",
                f"Last night's base load was {last:.2f} kW versus a normal {norm:.2f} kW "
                f"(+{(last - norm) * 1000:.0f} W).", round(last - norm, 3)))

    # --- unusual day total vs the model's own expectation, with similar-day context -----------------------------
    # (evaluated on the last complete day)
    yday = asof - timedelta(days=1)
    tot = model.table.total(yday)
    if tot is not None:
        days = model.table.complete_days(yday, 60)
        totals = stats.clean([model.table.total(d) for d in days])
        if len(totals) >= 14:
            exp = stats.robust_ewma(totals, model.cfg.fast_alpha, model.cfg.winsor_k, 28, 0.5)[0]
            sig = max(stats.robust_sigma([t - exp for t in totals], 0.5), 0.5)
            z = (tot - exp) / sig
            if abs(z) >= UNUSUAL_DAY_Z:
                same = [t for d, t in zip(days, [model.table.total(d) for d in days])
                        if t is not None and d.weekday() == yday.weekday()][-8:]
                ctx = f" (similar {yday.strftime('%A')}s: median {stats.median(same):.1f} kWh)" if len(same) >= 4 else ""
                rep.anomalies.append(Anomaly(
                    "UNUSUAL_DAY", "INFO",
                    f"Yesterday used {tot:.1f} kWh against an expected {exp:.1f} kWh{ctx}.", round(tot - exp, 2)))

    # --- behaviour shift: last 14 days vs the previous 42 (daily totals) ---------------------------------------
    d14 = stats.clean([model.table.total(asof - timedelta(days=k)) for k in range(1, 15)])
    d42 = stats.clean([model.table.total(asof - timedelta(days=k)) for k in range(15, 57)])
    if len(d14) >= 10 and len(d42) >= 28:
        shift = stats.median(d14) - stats.median(d42)
        sig = max(stats.robust_sigma(d42, 1.0), 1.0)
        se = 1.2533 * sig * (1.0 / len(d14) + 1.0 / len(d42)) ** 0.5     # standard error of a difference of medians
        if abs(shift) >= 3.0 * se and abs(shift) >= 0.08 * stats.median(d42):
            rep.anomalies.append(Anomaly(
                "BEHAVIOUR_SHIFT", "INFO",
                f"Demand over the last 14 days is {shift:+.1f} kWh/day versus the previous six weeks.", round(shift, 2)))
    return rep


# ----------------------------------------------------------------------------
# Recurring load signatures (needs >= 1-minute data; hourly cannot see them)
# ----------------------------------------------------------------------------

@dataclass
class SignatureCluster:
    label: str
    amplitude_w: float
    duration_class: str
    count: int
    days_seen: int
    median_local_hour: float
    last_seen: str

    def text(self) -> str:
        return (f"Recurring load signature {self.label}: ~{self.amplitude_w / 1000:.1f} kW for {self.duration_class}, "
                f"seen on {self.days_seen} days, usually around {int(self.median_local_hour):02d}:00")

    def to_dict(self) -> dict:
        return {"label": self.label, "amplitude_w": round(self.amplitude_w), "duration_class": self.duration_class,
                "count": self.count, "days_seen": self.days_seen, "median_local_hour": round(self.median_local_hour, 1),
                "last_seen": self.last_seen, "text": self.text(), "appliance": None}


def _dur_class(m: float) -> str:
    if m <= 8:
        return "<8 min"
    if m <= 20:
        return "8-20 min"
    if m <= 45:
        return "20-45 min"
    if m <= 90:
        return "45-90 min"
    return "90+ min"


def find_signatures(samples: list[tuple[int, float]], tz_name: str, min_step_w: float = 1200.0,
                    min_count: int = 4, min_days: int = 3) -> list[SignatureCluster]:
    """Recurring step-up / step-down load events from (epoch_seconds, watts) samples at <= ~1 min spacing.

    1-minute medians; a step up of >= min_step_w is paired with the next matching step down (0.7-1.4x the
    magnitude) within 2-150 minutes. Pairs are binned by amplitude (250 W) and duration class; bins seen at
    least min_count times on at least min_days distinct days become neutral clusters, labelled A, B, C ...
    by decreasing count. No appliance is ever named."""
    if len(samples) < 100:
        return []
    tz = zone(tz_name)
    buckets: dict[int, list[float]] = {}
    for t, w in samples:
        buckets.setdefault(t // 60, []).append(w)
    minutes = sorted(buckets)
    series = [(m, stats.median(buckets[m])) for m in minutes]
    ups: list[tuple[int, float]] = []
    downs: list[tuple[int, float]] = []
    for (m0, w0), (m1, w1) in zip(series, series[1:]):
        if m1 - m0 > 3:
            continue
        d = w1 - w0
        if d >= min_step_w:
            ups.append((m1, d))
        elif d <= -min_step_w:
            downs.append((m1, -d))
    events = []
    for m, amp in ups:
        for dm, damp in downs:
            if dm <= m + 1:
                continue
            if dm > m + 150:
                break
            if 0.7 * amp <= damp <= 1.4 * amp:
                events.append((m, dm - m, (amp + damp) / 2))
                break
    bins: dict[tuple[int, str], list[tuple[int, float, float]]] = {}
    for m, dur, amp in events:
        bins.setdefault((int(round(amp / 250.0)), _dur_class(dur)), []).append((m, dur, amp))
    out = []
    for (ab, dc), evs in bins.items():
        days = {datetime.fromtimestamp(m * 60, tz).date() for m, _d, _a in evs}
        if len(evs) >= min_count and len(days) >= min_days:
            hrs = [datetime.fromtimestamp(m * 60, tz).hour + datetime.fromtimestamp(m * 60, tz).minute / 60 for m, _d, _a in evs]
            out.append((len(evs), ab, dc, evs, days, hrs))
    out.sort(key=lambda x: (-x[0], x[1], x[2]))
    clusters = []
    for i, (n, ab, dc, evs, days, hrs) in enumerate(out):
        last = max(m for m, _d, _a in evs)
        clusters.append(SignatureCluster(
            label=chr(ord("A") + i) if i < 26 else f"A{i}", amplitude_w=sum(a for _m, _d, a in evs) / n, duration_class=dc,
            count=n, days_seen=len(days), median_local_hour=stats.median(hrs),
            last_seen=datetime.fromtimestamp(last * 60, tz).isoformat()))
    return clusters
