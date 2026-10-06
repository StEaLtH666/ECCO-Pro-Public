"""Canonical hourly history.

The learning layer works on ONE table: a UTC hour-aligned record per hour with
interval energies (kWh) derived from the inverter's cumulative counters
wherever possible, plus hourly SOC statistics and per-field quality flags.
Why counters first (see docs/intelligence/DATA_QUALITY_METHOD.md): some
integrations hold a stale instantaneous-power value for hours while the
cumulative counters keep counting.

Inputs are HA long-term-statistics rows (statistic_id, start_ts, mean, min,
max, state, sum) - the same shape the read-only exporter in
intelligence/tools/export_ha_statistics.py produces - plus a site profile
mapping canonical fields to entity ids with per-hour source preference
(dongle first, legacy fill-in), mirroring the repo's canonical/legacy
telemetry pattern. No entity id is hard-coded here.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .config import SiteConfig
from .timeutil import HOUR, overlap_seconds, ts, utc_from_ts

ENERGY_FIELDS = ("load", "pv", "imp", "exp", "chg", "dis")

# quality flags (plain strings so they serialise trivially)
F_GAP_INTERP = "gap_interpolated"
F_STALL_REDIST = "stall_redistributed"
F_STALLED = "stalled_unrecovered"
F_RESET = "counter_reset"
F_POWER_INTEGRAL = "power_integral"
F_POWER_STALE = "power_stale"
F_SOC_SUSPECT = "soc_zero_suspect"
F_FALLBACK_SOURCE = "fallback_source"
F_SOC_JUMP = "soc_jump"
F_IMPLAUSIBLE = "implausible_energy"
SOC_MAX_HOURLY_STEP_PCT = 35.0     # 8 kW into ~32 kWh is ~25 %/h; more than this between hourly means is a sensor fault


@dataclass
class HourRecord:
    start: int                                              # UTC epoch seconds, hour aligned
    e: dict[str, float] = field(default_factory=dict)       # field -> kWh in this hour
    soc_mean: float | None = None
    soc_min: float | None = None
    soc_max: float | None = None
    pv_w_mean: float | None = None
    load_w_mean: float | None = None
    batt_w_mean: float | None = None
    grid_w_mean: float | None = None
    flags: dict[str, set[str]] = field(default_factory=dict)    # field -> flags
    sources: dict[str, str] = field(default_factory=dict)      # field -> source name

    def flag(self, fieldname: str, f: str) -> None:
        self.flags.setdefault(fieldname, set()).add(f)


class History:
    """Hour-indexed container with window/aggregate helpers."""

    def __init__(self, records: Iterable[HourRecord] = ()):
        self.by_start: dict[int, HourRecord] = {}
        for r in records:
            self.by_start[r.start] = r

    def __len__(self) -> int:
        return len(self.by_start)

    def get(self, start: int) -> HourRecord | None:
        return self.by_start.get(start)

    def truncated(self, before: datetime) -> "History":
        """A copy containing only hours that had COMPLETELY ended by `before` (for leak-free replay): the in-progress
        hour would carry up to 59 minutes of the future."""
        cut = ts(before)
        return History(r for s, r in self.by_start.items() if s + HOUR <= cut)

    def first_last(self) -> tuple[datetime, datetime] | None:
        if not self.by_start:
            return None
        return utc_from_ts(min(self.by_start)), utc_from_ts(max(self.by_start))

    def hours_between(self, t0: datetime, t1: datetime) -> Iterator[tuple[HourRecord | None, int, float]]:
        """Yield (record or None, hour_start_ts, overlap_fraction) for hours touching [t0, t1)."""
        s = ts(t0) - (ts(t0) % HOUR)
        while s < ts(t1):
            frac = overlap_seconds(utc_from_ts(s), utc_from_ts(s + HOUR), t0, t1) / HOUR
            if frac > 0:
                yield self.by_start.get(s), s, frac
            s += HOUR

    def energy(self, fieldname: str, t0: datetime, t1: datetime) -> tuple[float, float]:
        """(sum over valid hours, covered fraction of the window). Partially
        covered hours are apportioned uniformly."""
        total = 0.0
        cov = 0.0
        span = 0.0
        for rec, _s, frac in self.hours_between(t0, t1):
            span += frac
            if rec is not None and fieldname in rec.e:
                total += rec.e[fieldname] * frac
                cov += frac
        return total, (cov / span if span else 0.0)

    def energy_scaled(self, fieldname: str, t0: datetime, t1: datetime, min_coverage: float = 0.8) -> float | None:
        """Window energy scaled up for missing hours; None if coverage is below min_coverage."""
        total, cov = self.energy(fieldname, t0, t1)
        if cov < min_coverage or cov == 0:
            return None
        return total / cov

    def soc_at(self, t: datetime, tol_hours: int = 2) -> float | None:
        """Hourly-mean SOC of the hour containing t (nearest valid hour within tolerance)."""
        s = ts(t) - (ts(t) % HOUR)
        for off in sorted(range(-tol_hours, tol_hours + 1), key=lambda o: (abs(o), o)):
            r = self.by_start.get(s + off * HOUR)
            if r is not None and r.soc_mean is not None:
                return r.soc_mean
        return None


# ----------------------------------------------------------------------------
# Loading HA statistics rows
# ----------------------------------------------------------------------------

def iter_stats_csv(path: str | Path) -> Iterator[dict]:
    """Rows of the long-format statistics export (optionally .gz)."""
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            yield row


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def index_stats(rows: Iterable[Mapping], wanted_ids: set[str]) -> dict[str, dict[int, dict]]:
    """statistic_id -> {hour_start_ts: {mean,min,max,state,sum}} for the wanted ids only."""
    out: dict[str, dict[int, dict]] = {sid: {} for sid in wanted_ids}
    for r in rows:
        sid = r["statistic_id"]
        if sid not in out:
            continue
        start = int(float(r["start_ts"]))
        out[sid][start] = {k: _f(r.get(k)) for k in ("mean", "min", "max", "state", "sum")}
    return out


def load_profile(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def profile_entity_ids(profile: Mapping) -> set[str]:
    ids: set[str] = set()
    for src in profile["sources"]:
        for spec in src["entities"].values():
            ids.add(spec["id"])
    return ids


# ----------------------------------------------------------------------------
# Counter -> interval energy
# ----------------------------------------------------------------------------

def counter_to_hourly(
    states: Mapping[int, float],
    power_mean_w: Mapping[int, float] | None,
    cfg: SiteConfig,
    reset_tolerance_kwh: float = 0.15,
) -> tuple[dict[int, float], dict[int, set[str]]]:
    """Cumulative-counter end-of-hour states -> energy per hour.

    * Consecutive observed hours: energy = delta.
    * Missing hours between two observations: the delta is spread evenly over
      the gap (<= cfg.max_gap_fill_hours) and flagged; longer gaps stay missing.
    * A decrease larger than the tolerance is a counter reset: hours left missing.
    * Stalls: a counter that does not move while corroborating power is high is
      a stuck counter, not zero consumption. The stalled run plus the following
      catch-up hour are re-spread evenly; if no catch-up arrives within 12 h the
      stalled hours stay missing."""
    energy: dict[int, float] = {}
    flags: dict[int, set[str]] = {}
    hrs = sorted(states)
    for a, b in zip(hrs, hrs[1:]):
        gap = (b - a) // HOUR
        delta = states[b] - states[a]
        if delta < -reset_tolerance_kwh:
            for k in range(1, gap + 1):
                flags.setdefault(a + k * HOUR, set()).add(F_RESET)
            continue
        delta = max(delta, 0.0)
        if delta > cfg.max_hourly_kwh * gap:          # physically impossible: a counter glitch, not energy
            for k in range(1, gap + 1):
                flags.setdefault(a + k * HOUR, set()).add(F_IMPLAUSIBLE)
            continue
        if gap == 1:
            energy[b] = delta
        elif gap <= cfg.max_gap_fill_hours:
            for k in range(1, gap + 1):
                h = a + k * HOUR
                energy[h] = delta / gap
                flags.setdefault(h, set()).add(F_GAP_INTERP)
        # longer gaps: left missing (absence is the signal)
    if power_mean_w:
        stalled = sorted(
            h for h, e in energy.items()
            if e <= 0.005 and (power_mean_w.get(h) or 0.0) >= cfg.stall_power_w
        )
        i = 0
        while i < len(stalled):
            j = i
            while j + 1 < len(stalled) and stalled[j + 1] == stalled[j] + HOUR:
                j += 1
            run = list(range(stalled[i], stalled[j] + HOUR, HOUR))
            catch = run[-1] + HOUR
            if catch in energy and catch not in stalled and catch <= run[-1] + 12 * HOUR:
                share = energy[catch] / (len(run) + 1)
                for h in run + [catch]:
                    energy[h] = share
                    flags.setdefault(h, set()).add(F_STALL_REDIST)
            else:
                for h in run:
                    del energy[h]
                    flags.setdefault(h, set()).add(F_STALLED)
            i = j + 1
    return energy, flags


def power_is_flat(stat_rows: Mapping[int, dict], tol_w: float = 0.5) -> set[int]:
    """Hours in which an instantaneous-power statistic never moved (min == max): a held, stale value."""
    out = set()
    for h, r in stat_rows.items():
        lo, hi = r.get("min"), r.get("max")
        if lo is not None and hi is not None and abs(hi - lo) <= tol_w:
            out.add(h)
    return out


# ----------------------------------------------------------------------------
# Profile-driven build
# ----------------------------------------------------------------------------

def build_history(rows: Iterable[Mapping], profile: Mapping, cfg: SiteConfig) -> History:
    """Merge every profile source (priority order) into one hourly History.

    Per field and hour the first source that has a valid value wins; hours
    taken from a lower-priority source are flagged `fallback_source`."""
    idx = index_stats(rows, profile_entity_ids(profile))
    sources = sorted(profile["sources"], key=lambda s: s["priority"])
    recs: dict[int, HourRecord] = {}

    def rec(h: int) -> HourRecord:
        r = recs.get(h)
        if r is None:
            r = recs[h] = HourRecord(start=h)
        return r

    for si, src in enumerate(sources):
        ents = src["entities"]
        pw = {
            "load": {h: v["mean"] for h, v in idx[ents["load_power"]["id"]].items() if v["mean"] is not None}
            if "load_power" in ents else None,
            "pv": {h: v["mean"] for h, v in idx[ents["pv_power"]["id"]].items() if v["mean"] is not None}
            if "pv_power" in ents else None,
        }
        # --- energy counters ------------------------------------------------
        for fld in ENERGY_FIELDS:
            spec = ents.get(f"{fld}_energy")
            if not spec:
                continue
            scale = spec.get("scale", 1.0)
            states = {h: v["state"] * scale for h, v in idx[spec["id"]].items() if v["state"] is not None}
            energy, flags = counter_to_hourly(states, pw.get(fld), cfg)
            for h, e in energy.items():
                r = rec(h)
                if fld in r.e:
                    # a lower-priority source replaces the incumbent only if the incumbent is an interpolation/
                    # redistribution and the newcomer is a clean, directly measured hour
                    weak = {F_GAP_INTERP, F_STALL_REDIST}
                    if not (r.flags.get(fld, set()) & weak and not (flags.get(h, set()) & weak)):
                        continue
                    r.flags[fld] = set()
                r.e[fld] = e
                r.sources[fld] = src["name"]
                for fl in flags.get(h, ()):
                    r.flag(fld, fl)
                if si > 0:
                    r.flag(fld, F_FALLBACK_SOURCE)
            for h, fl in flags.items():
                if h not in energy:  # unrecovered stalls/resets: record why the hour is missing
                    r = rec(h)
                    for f1 in fl:
                        r.flag(fld, f1)
        # --- SOC ------------------------------------------------------------
        if "soc" in ents:
            batt = idx[ents["batt_power"]["id"]] if "batt_power" in ents else {}
            for h, v in idx[ents["soc"]["id"]].items():
                r = rec(h)
                if r.soc_mean is not None or v["mean"] is None:
                    continue
                r.soc_mean, r.soc_min, r.soc_max = v["mean"], v["min"], v["max"]
                r.sources["soc"] = src["name"]
                bw = (batt.get(h) or {}).get("mean")
                if v["max"] is not None and v["max"] <= 0.0 and bw is not None and abs(bw) > cfg.stall_power_w:
                    r.flag("soc", F_SOC_SUSPECT)
                if si > 0:
                    r.flag("soc", F_FALLBACK_SOURCE)
        # --- power means (diagnostics, flat-line detection, power-integral fallback)
        for key, attr in (("load_power", "load_w_mean"), ("pv_power", "pv_w_mean"),
                          ("batt_power", "batt_w_mean"), ("grid_power", "grid_w_mean")):
            if key not in ents:
                continue
            table = idx[ents[key]["id"]]
            flat = power_is_flat(table) if key == "load_power" else set()
            for h, v in table.items():
                if v["mean"] is None:
                    continue
                r = rec(h)
                if getattr(r, attr) is None:
                    setattr(r, attr, v["mean"])
                    if h in flat and (v["mean"] or 0) > 0:
                        r.flag("load", F_POWER_STALE)

    # physically impossible SOC steps between consecutive hourly means
    prev = None
    for h in sorted(recs):
        r = recs[h]
        if r.soc_mean is None:
            prev = None
            continue
        if prev is not None and prev[0] == h - HOUR and abs(r.soc_mean - prev[1]) > SOC_MAX_HOURLY_STEP_PCT:
            r.flag("soc", F_SOC_JUMP)
        prev = (h, r.soc_mean)

    # power-integral fallback for load/pv where no counter energy exists and power is not stale
    for r in recs.values():
        for fld, attr in (("load", "load_w_mean"), ("pv", "pv_w_mean")):
            pwr = getattr(r, attr)
            if fld not in r.e and pwr is not None and F_POWER_STALE not in r.flags.get(fld, set()):
                r.e[fld] = max(pwr, 0.0) / 1000.0
                r.sources[fld] = "power_integral"
                r.flag(fld, F_POWER_INTEGRAL)
    return History(recs.values())


# ----------------------------------------------------------------------------
# Quality audit
# ----------------------------------------------------------------------------

def audit(history: History) -> dict:
    """Machine-readable data-quality summary (feeds the quality report)."""
    fl = history.first_last()
    if fl is None:
        return {"hours": 0}
    first, last = fl
    expected = int((ts(last) - ts(first)) // HOUR) + 1
    present = len(history)
    missing_runs: list[tuple[str, int]] = []
    run_start = None
    run_len = 0
    s = ts(first)
    while s <= ts(last):
        if s not in history.by_start:
            if run_start is None:
                run_start, run_len = s, 0
            run_len += 1
        elif run_start is not None:
            missing_runs.append((utc_from_ts(run_start).isoformat(), run_len))
            run_start = None
        s += HOUR
    if run_start is not None:
        missing_runs.append((utc_from_ts(run_start).isoformat(), run_len))
    per_field: dict[str, dict] = {}
    for fld in ENERGY_FIELDS:
        n = sum(1 for r in history.by_start.values() if fld in r.e)
        flagc: dict[str, int] = {}
        for r in history.by_start.values():
            for f in r.flags.get(fld, ()):
                flagc[f] = flagc.get(f, 0) + 1
        per_field[fld] = {"hours_with_value": n, "coverage": round(n / expected, 4), "flags": dict(sorted(flagc.items()))}
    soc_n = sum(1 for r in history.by_start.values() if r.soc_mean is not None)
    soc_flags = sum(1 for r in history.by_start.values() if F_SOC_SUSPECT in r.flags.get("soc", ()))
    load_stale = sum(1 for r in history.by_start.values() if F_POWER_STALE in r.flags.get("load", ()))
    soc_jumps = sum(1 for r in history.by_start.values() if F_SOC_JUMP in r.flags.get("soc", ()))
    return {
        "first_utc": first.isoformat(), "last_utc": last.isoformat(),
        "hours_expected": expected, "hours_present": present,
        "hours_missing": expected - present, "missing_runs": missing_runs,
        "fields": per_field, "soc_hours": soc_n, "soc_suspect_hours": soc_flags, "soc_jump_hours": soc_jumps,
        "load_power_stale_hours": load_stale,
        "days_span": round(expected / 24.0, 1),
    }


def forecast_issue_series(rows: Iterable[Mapping], entity_id: str, tz_name: str, issue_hour_local: int = 6
                          ) -> dict:
    """{local_date: day-total forecast kWh} taken from the statistics bucket at `issue_hour_local`.

    For a 'forecast today' sensor the value just before dawn is the day-ahead
    estimate as the user would have seen it; later values are re-estimated
    with partial-day knowledge and would leak the answer."""
    from .timeutil import zone
    tz = zone(tz_name)
    out: dict = {}
    for r in rows:
        if r["statistic_id"] != entity_id:
            continue
        v = _f(r.get("state"))
        if v is None:
            v = _f(r.get("mean"))
        if v is None:
            continue
        loc = utc_from_ts(int(float(r["start_ts"]))).astimezone(tz)
        if loc.hour == issue_hour_local:
            out[loc.date()] = v
    return out
