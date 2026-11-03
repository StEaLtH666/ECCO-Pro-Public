"""Tariff adapter for the SHADOW cycle (planning stream): integration-shaped rate payloads -> verified rate slots.

Pure: no clock read (every time is an argument), no file or network access. It NEVER invents a price. A payload that is
missing, stale, of an unknown shape, unit-mismatched, timezone-naive, gappy, overlapping, future-dated or that does not
cover the period asked for gives a BLOCK or NO_VALUE finding and no rate; only a payload that passes every check is
VERIFIED_FROM_INTEGRATION.

Accepted shapes (the SiteReading value the runtime passes for `tariff.import_rates` / `tariff.export_rates`), modelled on
the Octopus Energy integration's rate events (entity ids are site-private, for example `event.your_..._current_day_rates`):

  * a list of rate rows `{start, end, value_inc_vat}`: ISO-8601 times WITH an offset and a rate in GBP/kWh (the
    integration's unit); optional row keys (`is_capped`, `is_intelligent_adjusted`, `value_exc_vat`) are ignored;
  * one event's attributes `{rates: [...], unit_of_measurement?}` (a stated unit must be GBP/kWh);
  * the rate events merged: `{previous_day | current_day | next_day: <either of the above>}`.

The runtime passes only the first shape (the quality layer accepts only a list for a table reading): the rows of the one
rate event mapped for the key, or the rows of the two or three day events mapped for it, merged by the Home Assistant
runtime in day order under fail-closed rules (A38 Part B, CCR-RT-DAYS: the contract that runtime implements;
FOUNDATION CONTRACT section 3). A site maps the import rates as [current day, next day], the recommended form (A42);
the three-event form, with the previous day first, is allowed. One day-rates event never covers the cheap-run search
period outside local midnight; the day events cover it once the next day's rates are published (13.5). The other two
shapes are parsed when this adapter is called directly.

Units: GBP/kWh x 100 = p/kWh. A rate whose magnitude exceeds PROPOSED_MAX_ABS_GBP_PER_KWH is taken as a unit mismatch (a
p/kWh figure given where GBP/kWh is expected), never rescaled; so is a payload whose median rate exceeds
PROPOSED_MAX_MEDIAN_GBP_PER_KWH (a p/kWh table whose every figure is small). The list shape states no unit, so this is
a plausibility guard, not a proof (UNKNOWN: a p/kWh table whose every figure is below the median bound still passes).
Rows that carry a price under another key are not integration-shaped and are refused. VAT and the standing charge are
UNKNOWN and excluded: rates are used exactly as the payload states them (no VAT is added or removed) and the standing
charge, the same under every plan compared, is left out.

Cheap window: only from rates that cover the whole search period [now, now + PROPOSED_WINDOW_SEARCH_H) (otherwise a
cheaper run could lie in the part that is not published yet), and only when the run is clearly cheaper than the rest
(PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH) and not longer than PROPOSED_MAX_CHEAP_WINDOW_MIN: a flat or nearly flat tariff
names no cheap run. The run is found among the slots still running at `now` and starting before the search horizon,
so its start and end are cut by both and are not the tariff's own period boundaries: a caller that checks another period
against the tariff compares that period's rate slots with the cheap band's ceiling (CheapWindow.ceiling_p_per_kwh, the
lowest candidate rate plus PROPOSED_CHEAP_BAND_P_PER_KWH), never with the run's start and end. When the tariff names no
cheap run, the caller compares them with the window check's lowest rate instead (horizon_low_p_per_kwh: the slots that
overlap the search period or the PROPOSED_WINDOW_SEARCH_H before `now`, whatever slots exist there, neither part need
be covered; A38). Only that lowest rate looks back: the cheap run and its band never do.

Age: a rate payload counts only when the quality layer judged its reading fresh under a defined limit (an I-D6 override;
UNRESOLVED is never fresh) and its observation time is not in the future.

Events (`tariff.events`): Saving Session and free-electricity session periods, `{saving_sessions | free_electricity:
[rows] or {joined_events | events: [rows]}}` or a list of rows `{start, end, kind?}`. Rewards (octopoints) are not
modelled (open decision O-4); only the periods are read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from .explain import finite_number
from .site_decisions import BLOCK, INFO, WARN, Finding, InputState, finding
from .timeutil import UTC, local_wall

TARIFF_VERSION = "intel-tariff-0.1.0"

VERIFIED_FROM_INTEGRATION = "VERIFIED_FROM_INTEGRATION"
NOT_VERIFIED = "NOT_VERIFIED"
NO_VALUE = "NO_VALUE"
STATUSES = (VERIFIED_FROM_INTEGRATION, BLOCK, NO_VALUE)

INTEGRATION_UNIT = "GBP/kWh"
PRICE_KEY = "value_inc_vat"
FOREIGN_PRICE_KEYS = ("p_per_kwh", "price", "rate", "value", "unit_rate", "pence")
RATE_GROUP_KEYS = ("previous_day", "current_day", "next_day")
EVENT_KINDS = ("saving_session", "free_electricity")

# PROPOSED engineering constants (conservative; not owner values)
PROPOSED_MAX_ABS_GBP_PER_KWH = 1.5       # beyond this magnitude a GBP/kWh rate is a unit mismatch (a p/kWh figure)
PROPOSED_MAX_MEDIAN_GBP_PER_KWH = 0.75   # a payload whose median rate is above this is taken as a unit mismatch
PROPOSED_CHEAP_BAND_P_PER_KWH = 0.5      # slots within this of the cheapest rate belong to the cheap window
PROPOSED_MIN_CHEAP_WINDOW_MIN = 60       # a cheap run shorter than this is not a named cheap run
PROPOSED_MAX_CHEAP_WINDOW_MIN = 720      # a longer cheap run is not a named cheap run (a flat / near-flat tariff)
PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH = 2.0  # the cheap run must be this much cheaper than every slot outside the cheap band
PROPOSED_WINDOW_SEARCH_H = 24            # the cheap window is looked for in [now, now + this), which the rates must cover
MAX_SLOTS = 400                          # more rows than this is not a rate payload (a 48 h half-hour table has 96)


@dataclass(frozen=True)
class RateSlot:
    start: datetime          # aware UTC
    end: datetime            # aware UTC, after start
    p_per_kwh: float


@dataclass(frozen=True)
class TariffEvent:
    kind: str                # saving_session | free_electricity
    start: datetime          # aware UTC
    end: datetime


@dataclass(frozen=True)
class TariffResult:
    """One rate payload as judged: VERIFIED_FROM_INTEGRATION with its slots, or BLOCK / NO_VALUE with no slot."""
    kind: str                                  # "import" | "export"
    status: str
    slots: tuple[RateSlot, ...] = ()
    findings: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown tariff status {self.status!r}")
        if self.status != VERIFIED_FROM_INTEGRATION and self.slots:
            raise ValueError("only a verified tariff carries rate slots")

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED_FROM_INTEGRATION

    @property
    def provenance(self) -> str:
        return VERIFIED_FROM_INTEGRATION if self.verified else NOT_VERIFIED

    def rate_at(self, t: datetime) -> float | None:
        for s in self.slots:
            if s.start <= t < s.end:
                return s.p_per_kwh
        return None

    def covers(self, a: datetime, b: datetime) -> bool:
        """True when the (contiguous) slots cover [a, b) completely."""
        if not self.slots or not b > a:
            return False
        return self.slots[0].start <= a and self.slots[-1].end >= b

    def overlapping(self, a: datetime, b: datetime) -> tuple[RateSlot, ...]:
        """The slots that overlap [a, b) (all of [a, b) is priced by them only when covers(a, b))."""
        return tuple(s for s in self.slots if s.end > a and s.start < b)

    def price_range(self, a: datetime, b: datetime) -> tuple[float, float] | None:
        """(lowest, highest) p/kWh over [a, b), or None when not covered."""
        if not self.covers(a, b):
            return None
        ps = [s.p_per_kwh for s in self.overlapping(a, b)]
        return (min(ps), max(ps)) if ps else None

    def covers_local_day(self, day, tz) -> bool:
        """True when the slots cover the whole local calendar day (23 h, 24 h or 25 h long)."""
        return self.covers(local_wall(day, 0, tz), local_wall(day, 1440, tz))


def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.tzinfo.utcoffset(x) is not None


def _time(v: object) -> tuple[datetime | None, str | None]:
    """(aware UTC datetime, None) or (None, problem code)."""
    if isinstance(v, datetime):
        return (v.astimezone(UTC), None) if _aware(v) else (None, "TARIFF_TIMEZONE_NAIVE")
    if isinstance(v, str):
        try:
            t = datetime.fromisoformat(v)
        except ValueError:
            return None, "TARIFF_TIME_UNPARSEABLE"
        return (t.astimezone(UTC), None) if _aware(t) else (None, "TARIFF_TIMEZONE_NAIVE")
    return None, "TARIFF_TIME_UNPARSEABLE"


_TEXTS = {
    "TARIFF_MISSING": "no tariff payload is available",
    "TARIFF_SHAPE_UNKNOWN": "the tariff payload is not an integration-shaped rate list",
    "TARIFF_SHAPE_NOT_INTEGRATION": "the rate rows carry a price under a key the integration does not use; it is not interpreted",
    "TARIFF_UNIT_MISMATCH": "a rate is outside what the integration's GBP per kWh unit allows, or a stated unit is not that unit",
    "TARIFF_TIMEZONE_NAIVE": "a rate slot time has no UTC offset",
    "TARIFF_TIME_UNPARSEABLE": "a rate slot time is not an ISO-8601 date-time",
    "TARIFF_RATE_INVALID": "a rate is not a finite number",
    "TARIFF_SLOT_INVALID": "a rate slot does not end after it starts, or is longer than a day",
    "TARIFF_OVERLAP": "two rate slots overlap or repeat",
    "TARIFF_GAP": "the rate slots are not contiguous",
    "TARIFF_TOO_MANY_ROWS": "the payload has more rows than any rate table",
    "TARIFF_EMPTY": "the payload has no rate rows",
    "TARIFF_NOT_FRESH": "the tariff reading is stale, of unknown age or has no defined freshness limit",
    "TARIFF_FUTURE_DATED": "the tariff reading is observed in the future",
    "TARIFF_COVERAGE_SHORT": "the rates do not cover the planned period",
    "TARIFF_UNIT_IMPLAUSIBLE": "the payload's typical rate is implausible in the integration's GBP per kWh unit; it is not "
                               "interpreted",
    "TARIFF_EVENTS_SHAPE_UNKNOWN": "the events payload is not a list of periods",
    "TARIFF_EVENT_INVALID": "an event period is naive, unparseable or does not end after it starts",
}


def _f(code: str, severity: str, subject: str, **evidence: object) -> Finding:
    return finding(code, severity, subject, _TEXTS.get(code, code.lower().replace("_", " ")), **evidence)


def _rows(payload: object) -> tuple[list | None, str | None]:
    """The rate rows of a payload, or (None, problem code)."""
    if isinstance(payload, (list, tuple)):
        return list(payload), None
    if isinstance(payload, Mapping):
        unit = payload.get("unit_of_measurement", payload.get("unit"))
        if unit is not None and (not isinstance(unit, str) or unit.strip().lower() != INTEGRATION_UNIT.lower()):
            return None, "TARIFF_UNIT_MISMATCH"
        if "rates" in payload:
            r = payload.get("rates")
            return (list(r), None) if isinstance(r, (list, tuple)) else (None, "TARIFF_SHAPE_UNKNOWN")
        groups = [k for k in RATE_GROUP_KEYS if k in payload]
        if groups and not (set(payload) - set(RATE_GROUP_KEYS) - {"unit", "unit_of_measurement"}):
            out: list = []
            for k in groups:
                sub, bad = _rows(payload[k])
                if bad:
                    return None, bad
                out += sub or []
            return out, None
    return None, "TARIFF_SHAPE_UNKNOWN"


def parse_rates(payload: object, kind: str = "import") -> tuple[tuple[RateSlot, ...], list[Finding]]:
    """Structural checks only (shape, unit, offsets, finite rates, contiguity). Returns the sorted slots, or () with BLOCK
    findings. Never raises."""
    subject = f"tariff.{kind}_rates"
    rows, bad = _rows(payload)
    if bad:
        return (), [_f(bad, BLOCK, subject)]
    if not rows:
        return (), [_f("TARIFF_EMPTY", BLOCK, subject)]
    if len(rows) > MAX_SLOTS:
        return (), [_f("TARIFF_TOO_MANY_ROWS", BLOCK, subject, rows=len(rows))]
    slots: list[RateSlot] = []
    problems: dict[str, int] = {}

    def note(code: str) -> None:
        problems[code] = problems.get(code, 0) + 1

    for r in rows:
        if not isinstance(r, Mapping):
            note("TARIFF_SHAPE_UNKNOWN")
            continue
        if PRICE_KEY not in r:
            note("TARIFF_SHAPE_NOT_INTEGRATION" if any(k in r for k in FOREIGN_PRICE_KEYS) else "TARIFF_SHAPE_UNKNOWN")
            continue
        a, pa = _time(r.get("start"))
        b, pb = _time(r.get("end"))
        if pa or pb:
            note(pa or pb)
            continue
        v = r.get(PRICE_KEY)
        if not finite_number(v):
            note("TARIFF_RATE_INVALID")
            continue
        if abs(float(v)) > PROPOSED_MAX_ABS_GBP_PER_KWH:
            note("TARIFF_UNIT_MISMATCH")
            continue
        if not b > a or (b - a) > timedelta(days=1):
            note("TARIFF_SLOT_INVALID")
            continue
        slots.append(RateSlot(a, b, round(float(v) * 100.0, 4)))
    if problems:
        return (), [_f(code, BLOCK, subject, rows=n) for code, n in sorted(problems.items())]
    vals = sorted(s.p_per_kwh for s in slots)
    median_gbp = (vals[(len(vals) - 1) // 2] + vals[len(vals) // 2]) / 200.0
    if median_gbp > PROPOSED_MAX_MEDIAN_GBP_PER_KWH:
        return (), [_f("TARIFF_UNIT_IMPLAUSIBLE", BLOCK, subject, median_gbp_per_kwh=round(median_gbp, 4))]
    slots.sort(key=lambda s: (s.start, s.end))
    for x, y in zip(slots, slots[1:]):
        if y.start < x.end:
            return (), [_f("TARIFF_OVERLAP", BLOCK, subject, at=y.start)]
        if y.start > x.end:
            return (), [_f("TARIFF_GAP", BLOCK, subject, after=x.end, before=y.start)]
    return tuple(slots), []


def assess_rates(state: InputState | None, now: datetime, *, kind: str = "import", observed_at: datetime | None = None,
                 need: tuple[datetime, datetime] | None = None) -> TariffResult:
    """Judge one rate reading: `state` is the quality layer's judged input (value = the payload). VERIFIED only when the
    payload parses, the reading is fresh under a defined limit, it is not observed in the future and (when `need` is
    given) the slots cover [need[0], need[1]). Never raises."""
    subject = f"tariff.{kind}_rates"
    try:
        if not isinstance(state, InputState) or state.value is None:
            return TariffResult(kind, NO_VALUE, (), (_f("TARIFF_MISSING", WARN, subject),))
        if _aware(observed_at) and _aware(now) and observed_at > now:
            return TariffResult(kind, BLOCK, (), (_f("TARIFF_FUTURE_DATED", BLOCK, subject),))
        slots, bad = parse_rates(state.value, kind)
        if bad:
            return TariffResult(kind, BLOCK, (), tuple(bad))
        if not (state.fresh and state.limit_s is not None):
            return TariffResult(kind, NO_VALUE, (), (_f("TARIFF_NOT_FRESH", WARN, subject, age_s=state.age_s,
                                                         limit_s=state.limit_s),))
        res = TariffResult(kind, VERIFIED_FROM_INTEGRATION, slots, (_f("TARIFF_VERIFIED", INFO, subject, slots=len(slots)),))
        if need is not None and not res.covers(need[0], need[1]):
            return TariffResult(kind, NO_VALUE, (), (_f("TARIFF_COVERAGE_SHORT", WARN, subject, need_start=need[0],
                                                         need_end=need[1]),))
        return res
    except Exception:  # noqa: BLE001 - a malformed payload is a refused payload, never a crash
        return TariffResult(kind, BLOCK, (), (_f("TARIFF_SHAPE_UNKNOWN", BLOCK, subject),))


@dataclass(frozen=True)
class CheapWindow:
    """The cheap run a VERIFIED import tariff names (cheap_window) and the cheap band it was found in. `start` / `end`
    are the run among the candidate slots (a run in progress starts at the slot that holds `now`; a run is cut at the
    search horizon), so they are never the boundaries another window is checked against: a rate slot is in the cheap band
    when its price is at or below `ceiling_p_per_kwh` (in_band)."""
    start: datetime          # aware UTC
    end: datetime
    p_per_kwh: float         # the cheapest rate inside it
    slots: int
    ceiling_p_per_kwh: float  # the cheap band's ceiling: the lowest candidate rate plus PROPOSED_CHEAP_BAND_P_PER_KWH

    def in_band(self, slot: RateSlot) -> bool:
        """True when the slot is priced in the cheap band (the same test cheap_window applies)."""
        return slot.p_per_kwh <= self.ceiling_p_per_kwh


def horizon_low_p_per_kwh(result: TariffResult, now: datetime) -> float | None:
    """The window check's lowest rate (p/kWh, `low` of A35 / A38): the lowest rate among a VERIFIED tariff's slots that
    overlap [now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H), the cheap-run search period ahead and the
    same span before it (A38: the look-back), whatever slots exist there (neither part need be covered). The slot that
    holds `now` counts; a slot that ends exactly PROPOSED_WINDOW_SEARCH_H before `now`, or starts exactly
    PROPOSED_WINDOW_SEARCH_H after it, does not. Only the no-run window check (daily_plan) reads it: cheap_window and its
    band never look back (the band's ceiling is the lowest rate of the slots still running at `now` plus
    PROPOSED_CHEAP_BAND_P_PER_KWH), so this is at or below the rate the band starts from, and lower only when a cheaper
    slot lies in the look-back. A lower value can only add BLOCKs to the window check. None when the tariff is not
    verified, `now` is not aware or no slot overlaps the period. Never raises."""
    if not isinstance(result, TariffResult) or not result.verified or not _aware(now):
        return None
    span = timedelta(hours=PROPOSED_WINDOW_SEARCH_H)
    ps = [s.p_per_kwh for s in result.overlapping(now - span, now + span)]
    return min(ps) if ps else None


def cheap_window(result: TariffResult, now: datetime) -> tuple[CheapWindow | None, list[Finding]]:
    """The cheap run a VERIFIED import tariff names: the longest contiguous run (earliest on a tie) of slots priced
    within PROPOSED_CHEAP_BAND_P_PER_KWH of the cheapest rate, among slots that end after `now` and start before
    now + PROPOSED_WINDOW_SEARCH_H, at least PROPOSED_MIN_CHEAP_WINDOW_MIN and at most PROPOSED_MAX_CHEAP_WINDOW_MIN long.
    A run in progress counts from the slot that holds `now` (the slots that have ended are not candidates) and a run is
    cut at the search horizon, so the run's start and end are not the tariff's own period boundaries; the band's ceiling
    is returned with it (CheapWindow.ceiling_p_per_kwh). Fail closed, None with a WARN:
      * the rates do not cover the whole search period (a cheaper run could lie in the unpublished part);
      * no run qualifies by length (a flat or nearly flat tariff gives one run that is too long);
      * the run is not at least PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH cheaper than every slot outside the cheap band."""
    subject = "tariff.import_rates"
    if not result.verified:
        return None, [finding("TARIFF_NOT_VERIFIED", WARN, subject, "the import tariff is not verified")]
    horizon = now + timedelta(hours=PROPOSED_WINDOW_SEARCH_H)
    if not result.covers(now, horizon):
        return None, [finding("TARIFF_COVERAGE_SHORT", WARN, subject, "the verified rates do not cover the whole "
                                                                      "cheap-run search period",
                              need_start=now, need_end=horizon)]
    cand = [s for s in result.slots if s.end > now and s.start < horizon]
    if not cand:
        return None, [finding("TARIFF_NO_SLOTS_AHEAD", WARN, subject, "no rate slot lies ahead")]
    low = min(s.p_per_kwh for s in cand)
    ceiling = low + PROPOSED_CHEAP_BAND_P_PER_KWH

    def cheap(s: RateSlot) -> bool:
        return s.p_per_kwh <= ceiling

    runs: list[list[RateSlot]] = []
    cur: list[RateSlot] = []
    for s in cand:
        if cheap(s) and (not cur or cur[-1].end == s.start):
            cur.append(s)
            continue
        if cur:
            runs.append(cur)
        cur = [s] if cheap(s) else []
    if cur:
        runs.append(cur)
    best = None
    for r in runs:
        length = (r[-1].end - r[0].start).total_seconds()
        if best is None or length > best[0]:
            best = (length, r)
    if best is None or best[0] < PROPOSED_MIN_CHEAP_WINDOW_MIN * 60:
        return None, [finding("TARIFF_NO_CHEAP_WINDOW", WARN, subject,
                              "no cheap run long enough lies ahead")]
    if best[0] > PROPOSED_MAX_CHEAP_WINDOW_MIN * 60:
        return None, [finding("TARIFF_CHEAP_RUN_TOO_LONG", WARN, subject,
                              "the cheapest run is longer than PROPOSED_MAX_CHEAP_WINDOW_MIN: the tariff is flat or "
                              "nearly flat",
                              run_minutes=round(best[0] / 60.0))]
    r = best[1]
    rest = [s.p_per_kwh for s in cand if not cheap(s)]
    if not rest or min(rest) - max(s.p_per_kwh for s in r) < PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH:
        return None, [finding("TARIFF_NO_PRICE_SPREAD", WARN, subject, "the cheapest run is not clearly cheaper than the "
                                                                       "rest of the period, so it names no cheap run",
                              spread_p_per_kwh=None if not rest else round(min(rest) - max(s.p_per_kwh for s in r), 4))]
    return CheapWindow(r[0].start, r[-1].end, min(s.p_per_kwh for s in r), len(r), ceiling), []


def _event_rows(payload: object) -> tuple[list[tuple[str, object]] | None, str | None]:
    if isinstance(payload, (list, tuple)):
        out = []
        for r in payload:
            k = r.get("kind", r.get("type", "saving_session")) if isinstance(r, Mapping) else None
            out.append((k if k in EVENT_KINDS else "unknown", r))
        return out, None
    if isinstance(payload, Mapping):
        out = []
        alias = {"saving_sessions": "saving_session", "saving_session": "saving_session",
                 "free_electricity": "free_electricity", "free_electricity_sessions": "free_electricity"}
        if set(payload) - set(alias):
            return None, "TARIFF_EVENTS_SHAPE_UNKNOWN"
        for key, sub in payload.items():
            kind = alias[key]
            if isinstance(sub, Mapping):
                sub = sub.get("joined_events", sub.get("events"))
            if not isinstance(sub, (list, tuple)):
                return None, "TARIFF_EVENTS_SHAPE_UNKNOWN"
            out += [(kind, r) for r in sub]
        return out, None
    return None, "TARIFF_EVENTS_SHAPE_UNKNOWN"


def parse_events(payload: object) -> tuple[tuple[TariffEvent, ...], list[Finding]]:
    """Saving Session / free-electricity periods (sorted), or () with BLOCK findings. An empty list is a valid 'no events'.
    Rewards are ignored (O-4). Never raises."""
    try:
        rows, bad = _event_rows(payload)
        if bad:
            return (), [_f(bad, BLOCK, "tariff.events")]
        out: list[TariffEvent] = []
        for kind, r in rows or []:
            if kind not in EVENT_KINDS or not isinstance(r, Mapping):
                return (), [_f("TARIFF_EVENTS_SHAPE_UNKNOWN", BLOCK, "tariff.events")]
            a, pa = _time(r.get("start"))
            b, pb = _time(r.get("end"))
            if pa or pb or not b > a or (b - a) > timedelta(days=1):
                return (), [_f("TARIFF_EVENT_INVALID", BLOCK, "tariff.events")]
            out.append(TariffEvent(kind, a, b))
        return tuple(sorted(out, key=lambda e: (e.start, e.end, e.kind))), []
    except Exception:  # noqa: BLE001
        return (), [_f("TARIFF_EVENTS_SHAPE_UNKNOWN", BLOCK, "tariff.events")]


def hhmm(minutes: int) -> str:
    """Minutes after local midnight -> 'HH:MM' (1440 -> '24:00')."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
