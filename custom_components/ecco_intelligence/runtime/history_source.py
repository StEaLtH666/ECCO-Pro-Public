"""Recorder long-term statistics -> the canonical hourly History (no homeassistant import; pure).

The coordinator reads `statistics_during_period(hass, start, end, ids, "hour", None, STAT_TYPES)` through the recorder's
own executor (never on the event loop) for the ids `plan_history` takes from the site file's V1 `sources` and `forecasts`
blocks, and hands the result here. This module never reads anything itself.

  * an entity id that is not a valid id (a `<placeholder>` left in the site file) is never queried and is reported;
  * at most PROPOSED_HISTORY_ROW_CAP rows are used (the newest), so a large recorder cannot stall a cycle;
  * gaps are kept as gaps: intelligence.history.build_history interpolates only short counter gaps and flags them, and the
    quality layer judges the newest complete hour's age;
  * a read is parsed once into a StatisticsImage (A50): rows_from_statistics' rows as immutable tuples, the exact content
    the parsed history is reused on (engine_link.HistoryReuse); build is build_full, then truncate at the cycle's `now`.

PROPOSED (engineering suggestions, NOT owner values): the lookback and the row cap below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from operator import itemgetter
from types import MappingProxyType
from typing import Mapping

from intelligence.config import SiteConfig
from intelligence.history import History, build_history, forecast_issue_series

from .sources import valid_entity_id

PROPOSED_HISTORY_LOOKBACK_DAYS = 120          # PROPOSED: SiteConfig.lookback_days_slow (the longest learning window)
PROPOSED_HISTORY_ROW_CAP = 150_000            # PROPOSED: ~ 30 statistic ids x 24 h x 120 days, with headroom
STAT_TYPES = ("mean", "min", "max", "state", "sum")
ROW_FIELDS = ("statistic_id", "start_ts") + STAT_TYPES     # a history row's keys, in the order of a StatisticsImage row
HOUR_S = 3600
UTC = timezone.utc
_ROW_TUPLE = itemgetter(*ROW_FIELDS)


@dataclass(frozen=True)
class HistoryPlan:
    """What to read: the valid statistic ids of the V1 `sources` / `forecasts` blocks, and a copy of those blocks holding
    only valid ids (handed to build_history)."""
    statistic_ids: tuple[str, ...]
    forecast_ids: Mapping[str, str]
    skipped: tuple[str, ...]
    profile: Mapping | None
    problem: str | None = None


def _finite(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def plan_history(profile: Mapping | None) -> HistoryPlan:
    """Read the V1 profile's `sources` (priority order, entities by canonical field) and `forecasts`. Malformed blocks give
    an empty plan with the problem named (no history: the quality layer then blocks every item that needs it)."""
    if not isinstance(profile, Mapping):
        return HistoryPlan((), MappingProxyType({}), (), None, "the site file is not an object")
    sources = profile.get("sources")
    if sources is None:
        return HistoryPlan((), MappingProxyType({}), (), None, "the site file has no V1 'sources' block")
    if not isinstance(sources, list):
        return HistoryPlan((), MappingProxyType({}), (), None, "'sources' must be a list")
    ids: set[str] = set()
    skipped: set[str] = set()
    clean = []
    for i, src in enumerate(sources):
        if not (isinstance(src, Mapping) and isinstance(src.get("name"), str) and _finite(src.get("priority"))
                and isinstance(src.get("entities"), Mapping)):
            return HistoryPlan((), MappingProxyType({}), (), None, f"sources[{i}] needs name, priority and entities")
        ents = {}
        for fld, spec in src["entities"].items():
            if not (isinstance(fld, str) and isinstance(spec, Mapping)):
                return HistoryPlan((), MappingProxyType({}), (), None, f"sources[{i}].entities is malformed")
            eid = spec.get("id")
            scale = spec.get("scale", 1.0)
            if not _finite(scale) or scale <= 0:
                return HistoryPlan((), MappingProxyType({}), (), None, f"sources[{i}].entities: a scale is invalid")
            if not valid_entity_id(eid):
                skipped.add(str(eid))
                continue
            ids.add(eid)
            ents[fld] = {"id": eid, "scale": float(scale)}
        clean.append({"name": src["name"], "priority": src["priority"], "entities": ents})
    fids: dict[str, str] = {}
    forecasts = profile.get("forecasts", {})
    if isinstance(forecasts, Mapping):
        for name, spec in forecasts.items():
            eid = spec.get("id") if isinstance(spec, Mapping) else None
            if isinstance(name, str) and valid_entity_id(eid):
                fids[name] = eid
                ids.add(eid)
            elif isinstance(name, str) and not name.startswith("_"):
                skipped.add(str(eid))
    if not ids:
        return HistoryPlan((), MappingProxyType(fids), tuple(sorted(skipped)), None,
                           "no valid statistic id in the site file (placeholders are never queried)")
    return HistoryPlan(tuple(sorted(ids)), MappingProxyType(dict(sorted(fids.items()))), tuple(sorted(skipped)),
                       MappingProxyType({"sources": clean}))


def window(now: datetime, days: int = PROPOSED_HISTORY_LOOKBACK_DAYS) -> tuple[datetime, datetime]:
    """[start, end): `days` back from the start of the current hour (only complete hours are ever used)."""
    end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return end - timedelta(days=days), end


def _ts(v: object) -> float | None:
    if isinstance(v, datetime):
        return v.timestamp() if v.tzinfo is not None else None
    return float(v) if _finite(v) else None


def rows_from_statistics(result: Mapping | None, cap: int = PROPOSED_HISTORY_ROW_CAP) -> tuple[list[dict], bool]:
    """HA statistics ({statistic_id: [{"start": ts | datetime, "mean": ..., ...}]}) -> history rows
    {statistic_id, start_ts, mean, min, max, state, sum}; non-finite values become None; at most `cap` rows, the newest
    kept. Returns (rows, truncated)."""
    rows: list[dict] = []
    if not isinstance(result, Mapping):
        return rows, False
    for sid in sorted(k for k in result if isinstance(k, str)):
        for r in result[sid] or ():
            if not isinstance(r, Mapping):
                continue
            start = _ts(r.get("start"))
            if start is None:
                continue
            row = {"statistic_id": sid, "start_ts": int(start)}
            for k in STAT_TYPES:
                v = r.get(k)
                row[k] = float(v) if _finite(v) else None
            rows.append(row)
    rows.sort(key=lambda x: (x["start_ts"], x["statistic_id"]))
    truncated = len(rows) > cap
    if truncated:
        rows = rows[len(rows) - cap:]
    return rows, truncated


@dataclass(frozen=True, eq=False)
class StatisticsImage:
    """One recorder statistics read, parsed once (A50): the rows rows_from_statistics gave, in its order, each a tuple in
    ROW_FIELDS order (statistic id str, start int, every value a float or None); whether the row cap cut the read; and the
    position (row, field) of every negative zero among the values. It holds only immutable values, so what it holds can
    never change after the parse.

    content() is the exact content the parsed history is reused on: two images have equal content exactly when their rows
    are bit for bit the same. The rows' == gives the ids, the starts, which values are None and every value up to the
    sign of a zero (a parsed value is never NaN: rows_from_statistics turns a non-finite value into None); the negative
    zeros' positions give that sign. A raw statistics mapping has no such image of its own (it could change in place,
    and == cannot tell True from 1.0 or -0.0 from 0.0), which is why a read is parsed into one."""
    rows: tuple[tuple, ...]
    truncated: bool
    negative_zeros: tuple[tuple[int, int], ...]

    def content(self) -> tuple[tuple[tuple, ...], tuple[tuple[int, int], ...], bool]:
        return (self.rows, self.negative_zeros, self.truncated)

    def row_dicts(self) -> list[dict]:
        """The rows as rows_from_statistics gives them (new dicts)."""
        return [dict(zip(ROW_FIELDS, r)) for r in self.rows]


def image_from_rows(rows: list[dict], truncated: bool) -> StatisticsImage:
    """The StatisticsImage of rows_from_statistics' (rows, truncated)."""
    tup = tuple(map(_ROW_TUPLE, rows))
    nz = tuple((i, j) for i, r in enumerate(tup) for j in range(2, len(ROW_FIELDS))
               if r[j] == 0.0 and math.copysign(1.0, r[j]) < 0.0)
    return StatisticsImage(tup, bool(truncated), nz)


def build_full(plan: HistoryPlan, rows: list[dict], cfg: SiteConfig) -> History | None:
    """The History of every row (no cut at `now`), or None without a V1 profile or rows. build_history reads only the rows,
    the profile and cfg, so equal inputs give an equal History."""
    if plan.profile is None or not rows:
        return None
    return build_history(rows, plan.profile, cfg)


def truncate(full: History | None, now: datetime) -> tuple[History | None, datetime | None]:
    """(a new History holding the hours of `full` that have ended by `now`, the end of its newest hour) or (None, None).
    The records are `full`'s own (never copied, never changed here)."""
    if full is None:
        return None, None
    hist = full.truncated(now)
    if len(hist) == 0:
        return None, None
    newest = max(hist.by_start) + HOUR_S
    return hist, datetime.fromtimestamp(newest, UTC)


def build(plan: HistoryPlan, rows: list[dict], cfg: SiteConfig, now: datetime) -> tuple[History | None, datetime | None]:
    """(History truncated to hours that have ended by `now`, the end of its newest hour) or (None, None)."""
    return truncate(build_full(plan, rows, cfg), now)


def pv_forecast_history(plan: HistoryPlan, rows: list[dict], tz: str) -> dict[str, dict[date, float]]:
    """{source name: {local date: day-ahead kWh}} from the `forecasts` statistics (intelligence.history.forecast_issue_series)."""
    out: dict[str, dict[date, float]] = {}
    for name, eid in plan.forecast_ids.items():
        series = forecast_issue_series(rows, eid, tz)
        if series:
            out[name] = dict(sorted(series.items()))
    return out
