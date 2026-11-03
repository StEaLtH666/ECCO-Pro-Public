"""One planning view per SHADOW cycle (planning stream): the charge window, the V1.1 charge target as the single
authority, and what follows from it. Advice only: nothing here changes any setting.

  charge window      always the TOU slot table's single grid-charge run (intelligence.tou_table, fail closed: an
                     unknown slot, either enable off or unknown, an overlay active or unknown, more than one grid run, a
                     run across local midnight or of the whole day each BLOCK). With a VERIFIED import tariff that names
                     a cheap run, every rate slot of the TOU occurrence from now on must be priced in the tariff's cheap
                     band (INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF), else BLOCK (CHARGE_WINDOW_SOURCES_DISAGREE); rates that
                     do not cover that occurrence, or a fresh table that does not classify, BLOCK
                     (CHARGE_WINDOW_TOU_UNCHECKED); a verified tariff alone is never a window. A verified tariff that
                     names no cheap run still checks the slots it prices (A35): a slot of the TOU occurrence from now
                     on priced at least PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH above the lowest rate priced in the search
                     period or the same span before now (A38) BLOCKs (CHARGE_WINDOW_SOURCES_DISAGREE); otherwise it, or
                     no verified tariff, leaves the TOU window with a WARN (CHARGE_WINDOW_FROM_TOU_TABLE), and with INFO
                     CHARGE_WINDOW_NOT_PRICED when no price check covered the whole occurrence (no verified tariff, or
                     one that does not price the whole occurrence; A41). Never the SiteConfig example window, never an
                     invented period, never an overlap of the two sources.
  grid-charge limit  `limits.max_grid_charge_w`, through site_decisions.apply_to_siteconfig (never the example 8 kW); the
                     SHADOW cycle caps it at the lowest slot power of the TOU run (it can only lower it).
  charge target      intelligence.charge_target.advise_charge_target: THE target. The planner never computes another.
  planned SOC        the SOC planned at the window end: min(target, what the window can reach), or the predicted SOC at
                     the window start when that is already above the target (a window charges up to a target, never
                     down to it). The plan is OK only when it is at least the effective reserve plus the safety margin.
  precharge timing   from the V1 advisor's PRE_WINDOW reasons (PRE_WINDOW_FLOOR / PRE_WINDOW_RISK) of a run on the
                     DECIDED configuration: the first trajectory point before the window at or below the reserve.
  headroom ceiling   the highest window-end SOC that leaves room for the conservative PV surplus after the window
                     (PV at its low multiplier, load at its high one) on the reserve-held energy account (the same as
                     baselines.replay); never below the effective reserve plus margin.
  reserve runout     when the battery would reach the effective reserve without grid charging (load p50, PV low).
  morning SOC        the band at the morning anchor on the same reserve-held account (never below the reserve).
  Saving Session     intelligence.events.advise_event on planning (p90) demand; no reward model (open decision O-4). An
                     event after a refill starts from the plan's window-end SOC (event_start_basis).
  cycling cost       only when `pref.wear_cost_p_per_kwh` is present: the preference times the grid charge energy.

Every output is gated by the caller (the SHADOW cycle) on the decisions and fresh inputs; this module never decides
whether something may be published. Pure: no clock read (every time is an argument), no file or network access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Mapping

from .baselines import replay
from .battery import build_steps, eta_one_way, simulate
from .config import SiteConfig
from .events import EventInputs, ExportEvent, advise_event
from .explain import OK as ADVICE_OK, Advice, finite_number
from . import tou_table
from .site_decisions import BLOCK, CHARGE_WINDOW_KEY, INFO, WARN, Finding, InputState, finding
from .tariff import (PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH, CheapWindow, TariffResult, cheap_window, hhmm,
                     horizon_low_p_per_kwh)
from .timeutil import UTC, local_date, local_wall
from .usage import UsageForecast, fixed_window

PLAN_VERSION = "intel-daily-plan-0.1.0"

SOURCE_TARIFF = "TARIFF"
SOURCE_TOU_TABLE = "TOU_TABLE"
# FOUNDATION CONTRACT 13.5 / 13.8 (A41): INFO, value-free. The window stands on the TOU table without a price check of
# its whole occurrence: no usable verified import tariff for the window check, or a verified tariff that names no cheap
# run and does not price the whole clipped occurrence. Never beside a named-run INSIDE result, never when the whole
# occurrence was priced and found within the spread, never on a refused window. It blocks nothing and changes no number.
CHARGE_WINDOW_NOT_PRICED = "CHARGE_WINDOW_NOT_PRICED"
CHARGE_WINDOW_NOT_PRICED_TEXT = ("the charge window stands on the read-only TOU slot table without a price check of "
                                 "its whole occurrence")

# PROPOSED engineering constants (conservative; not owner values)
PROPOSED_MORNING_ANCHOR_MIN = 540        # 09:00 local: the end of the V1 'morning' window; predicted_morning_soc is read here
PROPOSED_ADVICE_VALIDITY_S = 900.0       # an item is valid at most this long (equal to the SOC advisory limit)

PLAN_OK, PLAN_BLOCKED = "OK", "BLOCKED"
MORNING_ROUNDING_PCT = 0.05                # the morning SOC band is published to 0.1 point

def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.tzinfo.utcoffset(x) is not None


# ---------------------------------------------------------------------------------------------------------------------
# the charge window
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ChargeWindow:
    """The next (or current) charge window: aware UTC endpoints, its local minutes and the judged input for
    site_decisions.CHARGE_WINDOW_KEY (fresh exactly as its sources). `keys`: the readings it rests on (its validity is
    bounded by their remaining freshness); empty means the source's own reading. `tou_run`: the TOU grid-charge run the
    window is (its slots give the power cap and the claim); None only for a window built outside choose_charge_window."""
    source: str
    start: datetime
    end: datetime
    local_minutes: tuple[int, int]
    state: InputState
    keys: tuple[str, ...] = ()
    tou_run: tou_table.GridRun | None = None

    @property
    def input_keys(self) -> tuple[str, ...]:
        if self.keys:
            return self.keys
        return ("tariff.import_rates",) if self.source == SOURCE_TARIFF else ("tou.slot_table",)

    @property
    def label(self) -> str:
        return f"{hhmm(self.local_minutes[0])}-{hhmm(self.local_minutes[1])}"

    def occurrence(self, day: date, tz) -> tuple[datetime, datetime]:
        a, b = self.local_minutes
        return local_wall(day, a, tz), local_wall(day, b, tz)

    def next_start_after(self, t: datetime, tz) -> datetime:
        """The first window start at or after `t` (local wall-clock minutes on successive dates)."""
        d = local_date(t, tz) - timedelta(days=1)
        for _ in range(4):
            s, _e = self.occurrence(d, tz)
            if s >= t:
                return s
            d += timedelta(days=1)
        return self.occurrence(d, tz)[0]


def _tou_charge_window(tou_state: InputState | None, enabled: InputState | None, grid_enabled: InputState | None,
                       overlay: InputState | None, now: datetime, tz) -> tuple[ChargeWindow | None, list[Finding]]:
    """The charge window of the TOU table's single grid-charge run (tou_table.grid_window: fail closed), or None with the
    reasons. Its input keys are the table, both enables and the overlay reading."""
    tw, notes, _c = tou_table.grid_window(tou_state, enabled, grid_enabled, overlay, now, tz)
    if tw is None:
        return None, notes
    state = InputState(CHARGE_WINDOW_KEY, (int(tw.local_minutes[0]), int(tw.local_minutes[1])), bool(tw.fresh), tw.age_s,
                       tw.limit_s)
    return ChargeWindow(SOURCE_TOU_TABLE, tw.start.astimezone(UTC), tw.end.astimezone(UTC), tw.local_minutes, state,
                        tou_table.TOU_INPUT_KEYS, tw.run), notes


def _tou_against_tariff(imp: TariffResult, band: CheapWindow, tou_cw: ChargeWindow, now: datetime) -> Finding | None:
    """The TOU occurrence checked against the VERIFIED tariff's rate slots (never against the cheap run's start and end,
    which cheap_window cuts at `now` and at its search horizon): the occurrence is clipped to [max(now, start), end), and
    every slot that overlaps it must be priced in the cheap band (CheapWindow.in_band). The tariff's cheap run may cross
    local midnight; only the TOU window must lie on one local date (tou_table refuses a run across midnight). None when
    the check passes, else the BLOCK: CHARGE_WINDOW_TOU_UNCHECKED when the slots do not cover the clipped occurrence,
    CHARGE_WINDOW_SOURCES_DISAGREE when a slot overlapping it is priced above the band's ceiling."""
    a, b = max(now, tou_cw.start), tou_cw.end
    if not imp.covers(a, b):
        return finding("CHARGE_WINDOW_TOU_UNCHECKED", BLOCK, CHARGE_WINDOW_KEY,
                       "the verified tariff's rate slots do not cover the TOU grid-charge window, so it cannot be checked "
                       "against the tariff; no window is assumed")
    above = [s for s in imp.overlapping(a, b) if not band.in_band(s)]
    if above:
        return finding("CHARGE_WINDOW_SOURCES_DISAGREE", BLOCK, CHARGE_WINDOW_KEY,
                       "a rate slot of the TOU grid-charge window is priced above the verified tariff's cheap band; no "
                       "window is assumed", slots_above=len(above))
    return None


def _tou_against_no_run_tariff(imp: TariffResult, tou_cw: ChargeWindow, now: datetime) -> tuple[Finding | None, bool]:
    """A35: the TOU occurrence checked against a VERIFIED tariff that names no cheap run (cheap_window found the search
    period not covered, no slot ahead, no run long enough, a run too long or no spread). The occurrence is clipped to
    [max(now, start), end) as in A30; `low` is the lowest rate among the slots that overlap
    [now - PROPOSED_WINDOW_SEARCH_H, now + PROPOSED_WINDOW_SEARCH_H) (tariff.horizon_low_p_per_kwh, whatever slots
    exist; the slot that holds `now` counts): the look-back of A38, so a payload of one day-rates event still compares
    the window with that day's cheap slots after they have passed. Only `low` looks back: the slots checked against it
    are those of the clipped occurrence. Every slot that overlaps the clipped occurrence and is priced at or above
    low + PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH is a conflict: the check runs on the slots that exist, so a known
    conflicting slot BLOCKs (CHARGE_WINDOW_SOURCES_DISAGREE) even when the occurrence is only partly priced. A tariff
    that does not price the occurrence gives nothing to conflict with, so that alone is no BLOCK here. Returns (the
    BLOCK or None, whether the slots price the whole clipped occurrence and the check period has a lowest rate).
    The comparison is on the difference rounded to the slots' own 0.0001 p precision, so a slot exactly at the spread
    counts as at it whatever the binary rounding."""
    a, b = max(now, tou_cw.start), tou_cw.end
    low = horizon_low_p_per_kwh(imp, now)
    if low is not None:
        conflict = [s for s in imp.overlapping(a, b)
                    if round(s.p_per_kwh - low, 4) >= PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH]
        if conflict:
            return finding("CHARGE_WINDOW_SOURCES_DISAGREE", BLOCK, CHARGE_WINDOW_KEY,
                           "a rate slot of the TOU grid-charge window is priced at least the minimum cheap spread above "
                           "the verified tariff's lowest rate, while the tariff names no cheap run; no window is assumed",
                           slots_above=len(conflict)), False
    return None, low is not None and imp.covers(a, b)


def choose_charge_window(now: datetime, tz, import_result: TariffResult | None, import_state: InputState | None,
                         tou_state: InputState | None, *, tou_enabled: InputState | None = None,
                         grid_charge_enabled: InputState | None = None,
                         tou_overlay: InputState | None = None) -> tuple[ChargeWindow | None, list[Finding]]:
    """The charge window is always the TOU table's single grid-charge run (tou_table: the inverter grid-charges only in
    its slots), never a guess. With a VERIFIED tariff whose cheap-run analysis (tariff.cheap_window: search horizon,
    coverage, length, spread) names a cheap run, the TOU occurrence the window refers to, clipped to
    [max(now, start), end), is checked against the tariff's rate slots: every slot overlapping it priced in the cheap
    band gives the TOU window (INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF; the tariff only checks the TOU window), a slot
    above the band's ceiling BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE and slots that do not cover it BLOCK
    CHARGE_WINDOW_TOU_UNCHECKED. A fresh table that does not classify beside such a tariff BLOCKs
    CHARGE_WINDOW_TOU_UNCHECKED, and a verified tariff alone is never a window (no fresh table: CHARGE_WINDOW_UNKNOWN).
    A verified tariff that names no cheap run (its own WARN stays in the findings) still checks the slots it prices
    (A35, _tou_against_no_run_tariff): a slot of the clipped occurrence priced at least
    PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH above the lowest rate priced in the search period or the same span before now
    (A38) BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE;
    otherwise it, or no verified tariff, leaves the TOU window with a WARN (CHARGE_WINDOW_FROM_TOU_TABLE) whose text
    says which case applies (no verified tariff; every priced slot within the spread; the window not wholly priced).
    In the first and the last case the window also carries INFO CHARGE_WINDOW_NOT_PRICED (A41): no price check covered
    its whole occurrence. Of a WARN or INFO finding only the code is published (a BLOCK finding's text is published as
    its blocker text), so this code is what tells that residual apart from a window whose whole occurrence was checked.
    Without a TOU window, BLOCK CHARGE_WINDOW_UNKNOWN. No finding carries a severity other than contract 13.8's."""
    notes: list[Finding] = []
    tou_cw, n_tou = _tou_charge_window(tou_state, tou_enabled, grid_charge_enabled, tou_overlay, now, tz)
    verified = (isinstance(import_result, TariffResult) and import_result.verified
                and isinstance(import_state, InputState))
    band = None
    if isinstance(import_result, TariffResult):
        if not verified:
            notes.append(finding("CHARGE_WINDOW_TARIFF_NOT_VERIFIED", INFO, CHARGE_WINDOW_KEY,
                                 "the import tariff is not verified, so it does not check the charge window"))
        else:
            band, n1 = cheap_window(import_result, now)
            notes += n1
    if band is not None:
        if tou_cw is None:
            fresh_table = isinstance(tou_state, InputState) and tou_state.fresh and tou_state.limit_s is not None
            if fresh_table:
                return None, notes + n_tou + [finding(
                    "CHARGE_WINDOW_TOU_UNCHECKED", BLOCK, CHARGE_WINDOW_KEY,
                    "the TOU slot table does not classify as one grid-charge window, so the verified tariff's cheap "
                    "run cannot be checked against it; no window is assumed")]
            return None, notes + n_tou + [finding(
                "CHARGE_WINDOW_UNKNOWN", BLOCK, CHARGE_WINDOW_KEY,
                "a verified tariff alone is never a charge window: the read-only TOU slot table is not fresh, so "
                "whether the inverter grid-charges in the cheap run is unknown")]
        bad = _tou_against_tariff(import_result, band, tou_cw, now)
        if bad is not None:
            return None, notes + [bad]
        a, b = import_state, tou_cw.state
        ages = [x for x in (a.age_s, b.age_s) if x is not None]
        lims = [x for x in (a.limit_s, b.limit_s) if x is not None]
        state = InputState(CHARGE_WINDOW_KEY, (int(tou_cw.local_minutes[0]), int(tou_cw.local_minutes[1])),
                           bool(a.fresh and b.fresh), max(ages) if len(ages) == 2 else None,
                           min(lims) if len(lims) == 2 else None)
        return ChargeWindow(SOURCE_TARIFF, tou_cw.start, tou_cw.end, tou_cw.local_minutes, state,
                            ("tariff.import_rates",) + tou_table.TOU_INPUT_KEYS, tou_cw.tou_run), notes + [
            finding("CHARGE_WINDOW_TOU_INSIDE_TARIFF", INFO, CHARGE_WINDOW_KEY,
                    "every rate slot of the TOU grid-charge window lies in the verified tariff's cheap band; the window "
                    "is the TOU window"),
            finding("CHARGE_WINDOW_FROM_TARIFF", INFO, CHARGE_WINDOW_KEY,
                    "the charge window is checked against the verified import tariff")]
    notes += n_tou
    if tou_cw is None:
        notes.append(finding("CHARGE_WINDOW_UNKNOWN", BLOCK, CHARGE_WINDOW_KEY,
                             "no classified TOU grid-charge window (a verified tariff only cross-checks it); the "
                             "example window is never used"))
        return None, notes
    if not verified:
        why, whole = "no verified tariff", False
    else:
        bad, whole = _tou_against_no_run_tariff(import_result, tou_cw, now)
        if bad is not None:
            return None, notes + [bad]
        why = ("the verified import tariff names no cheap run; every priced slot of the TOU window is within the minimum "
               "cheap spread of its lowest rate" if whole else
               "the verified import tariff names no cheap run and does not price the whole TOU window")
    notes.append(finding("CHARGE_WINDOW_FROM_TOU_TABLE", WARN, CHARGE_WINDOW_KEY,
                         f"{why}: the charge window comes from the read-only TOU slot table"))
    if not whole:
        notes.append(finding(CHARGE_WINDOW_NOT_PRICED, INFO, CHARGE_WINDOW_KEY, CHARGE_WINDOW_NOT_PRICED_TEXT))
    return tou_cw, notes


# ---------------------------------------------------------------------------------------------------------------------
# load and PV views (from the V1 models, passed in by the caller)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Band:
    """A window energy with its band (kWh)."""
    p10: float
    p50: float
    p90: float
    label: str

    @staticmethod
    def of(f: UsageForecast | None) -> "Band | None":
        if f is None or f.label == "INSUFFICIENT" or not all(finite_number(x) for x in (f.p10, f.p50, f.p90)):
            return None
        return Band(float(f.p10), float(f.p50), float(f.p90), f.label)


def load_band(usage, kind: str, a: datetime, b: datetime, tz, asof: date) -> Band | None:
    """The V1 usage model's forecast for [a, b) as a Band (None when unusable). The walk-forward window is the same local
    wall-clock window on every past day."""
    if not (_aware(a) and _aware(b)) or not b > a:
        return Band(0.0, 0.0, 0.0, "HIGH") if _aware(a) and _aware(b) and a == b else None
    la = a.astimezone(tz)
    start_min = la.hour * 60 + la.minute
    span = int(round((b - a).total_seconds() / 60.0))
    try:
        fn = fixed_window(start_min, start_min + span, tz)
        return Band.of(usage.forecast(kind, (a, b), fn, asof))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


@dataclass(frozen=True)
class HourlyView:
    """Hourly load and PV expectations for simulations: `load(h0)` / `pv(h0)` give the kWh of the full hour starting at
    h0 (aware UTC); the multipliers turn them into the conservative paths."""
    load: Callable[[datetime], float]
    pv: Callable[[datetime], float]
    load_lo: float = 1.0          # p10 / p50
    load_hi: float = 1.0          # p90 / p50
    pv_lo: float = 1.0            # p10 / p50
    pv_hi: float = 1.0            # p90 / p50

    def scaled(self, load_mult: float, pv_mult: float) -> tuple[Callable, Callable]:
        return (lambda h: max(0.0, self.load(h) * load_mult)), (lambda h: max(0.0, self.pv(h) * pv_mult))


def hourly_view(profile: list | tuple, pv_by_day: Mapping[date, tuple[float, list]], tz, load_band_: Band | None,
                pv_band: tuple[float, float, float] | None) -> HourlyView | None:
    """profile: 24 local-hour kWh slots (the V1 fast expert); pv_by_day: {local date: (p50 kWh, 24-slot shape)}. None when
    a load slot is unknown."""
    if not isinstance(profile, (list, tuple)) or len(profile) != 24 or any(not finite_number(v) for v in profile):
        return None
    prof = [max(0.0, float(v)) for v in profile]

    def load(h0: datetime) -> float:
        return prof[h0.astimezone(tz).hour]

    def pv(h0: datetime) -> float:
        loc = h0.astimezone(tz)
        d = pv_by_day.get(loc.date())
        if d is None:
            return 0.0
        p50, shape = d
        return max(0.0, p50 * shape[loc.hour]) if len(shape) == 24 else 0.0

    lo = hi = 1.0
    if load_band_ is not None and load_band_.p50 > 0:
        lo, hi = load_band_.p10 / load_band_.p50, load_band_.p90 / load_band_.p50
    plo = phi = 1.0
    if pv_band is not None and pv_band[1] > 0:
        plo, phi = pv_band[0] / pv_band[1], pv_band[2] / pv_band[1]
    return HourlyView(load, pv, max(0.0, lo), max(1.0, hi), max(0.0, min(1.0, plo)), max(1.0, phi))


# ---------------------------------------------------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DailyPlan:
    status: str                                  # OK | BLOCKED
    findings: tuple[Finding, ...]
    window_label: str | None = None
    window_source: str | None = None
    target_soc_pct: float | None = None
    planned_soc_pct: float | None = None         # min(target, reachable) at the window end
    effective_reserve_pct: float | None = None
    margin_pct: float | None = None
    headroom_ceiling_pct: float | None = None
    precharge_by: datetime | None = None
    reserve_runout_at: datetime | None = None
    morning_at: datetime | None = None
    morning_soc: tuple[float, float, float] | None = None    # (p10, p50, p90) %
    grid_charge_kwh: float | None = None
    cycling_cost_p: float | None = None

    def __post_init__(self) -> None:
        if self.status not in (PLAN_OK, PLAN_BLOCKED):
            raise ValueError(f"unknown plan status {self.status!r}")
        if self.status == PLAN_OK:
            floor = (self.effective_reserve_pct or 0.0) + (self.margin_pct or 0.0)
            if self.planned_soc_pct is None or self.planned_soc_pct < floor - 1e-9:
                raise ValueError("an OK plan keeps the planned SOC at or above the effective reserve plus margin")
            if self.headroom_ceiling_pct is not None and self.headroom_ceiling_pct < floor - 1e-9:
                raise ValueError("the headroom ceiling is never below the effective reserve plus margin")

    def plan_block(self) -> dict:
        """The envelope's pre-declared plan block {precharge_by, headroom_ceiling_pct, reserve_runout_at}."""
        return {"precharge_by": None if self.precharge_by is None else self.precharge_by.isoformat(),
                "headroom_ceiling_pct": self.headroom_ceiling_pct,
                "reserve_runout_at": None if self.reserve_runout_at is None else self.reserve_runout_at.isoformat()}


def _ceil1(x: float) -> float:
    return math.ceil(x * 10.0 - 1e-9) / 10.0


HEADROOM_BISECT_STEPS = 40              # bisection steps for the headroom ceiling (far below the 0.1-point rounding)


def headroom_ceiling(cfg: SiteConfig, floor_plus_margin: float, start: datetime, end: datetime, view: HourlyView, *,
                     reserve_pct: float) -> float:
    """The highest SOC at `start` from which the conservative path until `end` (PV at its low multiplier, load at its
    high one) clips no PV, on the reserve-held energy account of baselines.replay (no grid charge; below `reserve_pct`
    the grid carries the house, so a PV surplus after a deep drain starts from the reserve). Never below
    floor_plus_margin (when even that clips, the ceiling is floor_plus_margin: the reserve comes first) and never above
    max_soc. A missing view gives max_soc (no headroom is claimed)."""
    top = float(cfg.max_soc_pct)
    if view is None or not end > start:
        return max(floor_plus_margin, top)
    load_fn, pv_fn = view.scaled(view.load_hi, view.pv_lo)

    def clips(s: float) -> bool:
        return replay(cfg, reserve_pct, None, s, start, end, None, load_fn, pv_fn).export_kwh > 1e-6

    lo, hi = min(floor_plus_margin, top), top
    if not clips(hi):
        best = hi
    elif clips(lo):
        best = lo
    else:
        for _ in range(HEADROOM_BISECT_STEPS):              # the held path rises with its start SOC: clipping is monotone
            mid = (lo + hi) / 2.0
            if clips(mid):
                hi = mid
            else:
                lo = mid
        best = lo
    return _ceil1(max(floor_plus_margin, min(top, best)))           # rounded UP: never below floor + margin


def reserve_runout(cfg: SiteConfig, floor_pct: float, soc_pct: float | None, start: datetime, end: datetime,
                   view: HourlyView | None) -> datetime | None:
    """When the battery would reach the effective reserve without grid charging (load p50, PV at its low multiplier),
    within [start, end); None when it would not, or when the SOC or the view is unknown."""
    if view is None or not finite_number(soc_pct) or not end > start:
        return None
    if soc_pct <= floor_pct:
        return start
    load_fn, pv_fn = view.scaled(1.0, view.pv_lo)
    sim = simulate(float(soc_pct), build_steps(start, end, load_fn, pv_fn, None, cfg.max_grid_charge_kw), cfg, floor_pct)
    return sim.time_to_floor


def morning_soc(cfg: SiteConfig, planned_soc: float, start: datetime, at: datetime, view: HourlyView | None,
                band: Band | None = None, *, floor_pct: float = 0.0) -> tuple[float, float, float] | None:
    """(p10, p50, p90) SOC at `at` from `planned_soc` at `start` (the window end): the low SOC from high load and low PV,
    the high SOC from low load and high PV, each on the reserve-held energy account of baselines.replay (below
    `floor_pct`, the effective reserve, the grid carries the house), so the band is never below the reserve the plan
    holds. The load band is the V1 forecast of [start, at) itself when given (a short window is more uncertain than the
    whole period), else the view's. Clamped to 0..max_soc. None without a view."""
    if view is None or not at > start:
        return None if view is None else (planned_soc, planned_soc, planned_soc)
    lo, hi = view.load_lo, view.load_hi
    if band is not None and band.p50 > 0:
        lo, hi = max(0.0, band.p10 / band.p50), max(1.0, band.p90 / band.p50)
    out = []
    for lm, pm in ((hi, view.pv_lo), (1.0, 1.0), (lo, view.pv_hi)):
        load_fn, pv_fn = view.scaled(lm, pm)
        o = replay(cfg, float(floor_pct), None, float(planned_soc), start, at, None, load_fn, pv_fn)
        out.append(max(0.0, min(float(cfg.max_soc_pct), o.end_soc)))
    lo, mid, hi = sorted(out)
    return round(lo, 1), round(mid, 1), round(hi, 1)


def morning_anchor(window_end: datetime, tz) -> datetime:
    """PROPOSED_MORNING_ANCHOR_MIN local on the window end's date, or the next date when the window ends after it."""
    d = local_date(window_end, tz)
    t = local_wall(d, PROPOSED_MORNING_ANCHOR_MIN, tz)
    return t if t > window_end else local_wall(d + timedelta(days=1), PROPOSED_MORNING_ANCHOR_MIN, tz)


def precharge_from_v1(v1_recommended: Mapping | None, floor_pct: float, window_start: datetime) -> tuple[datetime | None, list[Finding]]:
    """Precharge timing from the V1 advisor's PRE_WINDOW reasons (a run on the DECIDED configuration): PRE_WINDOW_RISK
    -> the first pessimistic trajectory point before the window at or below the reserve; PRE_WINDOW_FLOOR -> the first
    median point below it. The earlier of the two; None when neither reason is present."""
    if not isinstance(v1_recommended, Mapping):
        return None, [finding("PRECHARGE_NOT_ASSESSED", INFO, "plan", "no V1 run on the decided configuration")]
    codes = {r.get("code") for r in v1_recommended.get("reasons") or [] if isinstance(r, Mapping)}
    if not codes & {"PRE_WINDOW_RISK", "PRE_WINDOW_FLOOR"}:
        return None, []
    found: list[datetime] = []
    for p in v1_recommended.get("trajectory") or []:
        if not isinstance(p, Mapping):
            continue
        try:
            t = datetime.fromisoformat(p.get("t"))
        except (TypeError, ValueError):
            continue
        if not _aware(t) or t > window_start:
            continue
        lo, mid = p.get("soc_low"), p.get("soc_median")
        if ("PRE_WINDOW_RISK" in codes and finite_number(lo) and lo <= floor_pct) or (
                "PRE_WINDOW_FLOOR" in codes and finite_number(mid) and mid < floor_pct):
            found.append(t.astimezone(UTC))
    if not found:
        return None, [finding("PRECHARGE_TIME_UNKNOWN", WARN, "plan",
                              "the V1 advisor names a pre-window risk but its trajectory gives no time")]
    return min(found), [finding("PRECHARGE_NEEDED", WARN, "plan",
                                "the battery is predicted to reach the reserve before the charge window opens")]


def build_plan(*, cfg: SiteConfig, now: datetime, tz, window: ChargeWindow, horizon_end: datetime, target: Advice,
               ha_reserve_pct: float | None, soc_pct: float | None, view: HourlyView | None,
               v1_recommended: Mapping | None = None, wear_cost_p_per_kwh: float | None = None,
               morning_band: Band | None = None, reserve_raise_pct: float | None = None) -> DailyPlan:
    """The planning view around one OK charge_target advice (V1.1, the single authority). BLOCKED when the advice is not
    OK, or when the planned SOC would fall below the effective reserve plus margin. Never raises for these inputs."""
    notes: list[Finding] = []
    reserve = cfg.effective_reserve(ha_reserve_pct, reserve_raise_pct)
    floor = reserve.effective_pct
    margin = cfg.soc_safety_margin_pct
    fm = floor + margin
    base = dict(window_label=window.label, window_source=window.source, effective_reserve_pct=floor, margin_pct=margin)
    if not isinstance(target, Advice) or target.status != ADVICE_OK or target.recommendation is None:
        return DailyPlan(PLAN_BLOCKED, (finding("PLAN_NO_TARGET", BLOCK, "plan", "the charge target is not OK"),), **base)
    rec = target.recommendation
    t_pct = rec.get("target_soc_pct")
    if not finite_number(t_pct):
        return DailyPlan(PLAN_BLOCKED, (finding("PLAN_NO_TARGET", BLOCK, "plan", "the charge target has no number"),), **base)
    reach = rec.get("achievable_soc_pct")
    start = rec.get("window_start_soc_pct")
    planned = float(t_pct) if not finite_number(reach) else min(float(t_pct), float(reach))
    if finite_number(start) and float(start) >= float(t_pct):
        planned = min(float(cfg.max_soc_pct), float(start))    # a window only charges up to the target, never down to it
    if planned < fm - 1e-9:
        return DailyPlan(PLAN_BLOCKED, (finding("PLAN_BELOW_RESERVE_MARGIN", BLOCK, "plan",
                                                "the window cannot reach the effective reserve plus margin; no plan is "
                                                "shown", planned_soc_pct=round(planned, 1), floor_plus_margin=fm),),
                         target_soc_pct=float(t_pct), **base)
    ceiling = headroom_ceiling(cfg, fm, window.end, horizon_end, view, reserve_pct=floor)
    if ceiling < planned - 1e-9:
        notes.append(finding("TARGET_ABOVE_HEADROOM_CEILING", INFO, "plan",
                             "the charge target is above the conservative PV headroom ceiling; the target stays the "
                             "authority (the reserve comes first)"))
    runout = reserve_runout(cfg, floor, soc_pct, now, horizon_end, view)
    if runout is not None:
        notes.append(finding("RESERVE_RUNOUT_AHEAD", INFO, "plan",
                             "without grid charging the battery would reach the effective reserve before the horizon"))
    pre, pn = precharge_from_v1(v1_recommended, floor, window.start)
    notes += pn
    anchor = morning_anchor(window.end, tz)
    mor = morning_soc(cfg, planned, window.end, anchor, view, morning_band, floor_pct=floor)
    if mor is not None and mor[0] <= floor + MORNING_ROUNDING_PCT:          # the band is rounded to 0.1 point
        notes.append(finding("MORNING_SOC_AT_RESERVE", INFO, "plan",
                             "on the conservative path the battery reaches the effective reserve before the morning "
                             "anchor; the grid carries the house below it"))
    gk = rec.get("grid_charge_kwh")
    cyc = None
    if wear_cost_p_per_kwh is not None:
        if finite_number(wear_cost_p_per_kwh) and wear_cost_p_per_kwh >= 0 and finite_number(gk):
            cyc = round(float(wear_cost_p_per_kwh) * float(gk), 2)
        else:
            notes.append(finding("CYCLING_COST_NOT_STATED", INFO, "plan",
                                 "the wear-cost preference or the grid energy is not usable"))
    return DailyPlan(PLAN_OK, tuple(notes), target_soc_pct=float(t_pct), planned_soc_pct=round(planned, 1),
                     headroom_ceiling_pct=ceiling, precharge_by=pre, reserve_runout_at=runout, morning_at=anchor,
                     morning_soc=mor, grid_charge_kwh=float(gk) if finite_number(gk) else None, cycling_cost_p=cyc,
                     **base)


# ---------------------------------------------------------------------------------------------------------------------
# Saving Session energy plan (events.advise_event) and the Dump refill
# ---------------------------------------------------------------------------------------------------------------------

def held_soc_after(cfg: SiteConfig, soc_pct: float, drain_kwh: float, floor_pct: float) -> float:
    """The SOC after a planning drain (AC kWh) on the reserve-held energy account of baselines.replay: the battery
    carries the house down to the effective reserve, below which the grid does (a battery already below it is held where
    it is, never raised). Clamped to 0..100."""
    raw = float(soc_pct) - float(drain_kwh) / eta_one_way(cfg) / cfg.battery_capacity_kwh * 100.0
    return max(0.0, min(100.0, max(min(float(soc_pct), float(floor_pct)), raw)))


EVENT_FROM_NOW = "FROM_NOW"                   # no charge window runs between now and the event start
EVENT_AFTER_WINDOW = "AFTER_WINDOW"           # exactly one window (the planned one) ends before the event starts
EVENT_NOT_MODELLED = "NOT_MODELLED"           # the event starts inside a window, or after more than one refill


def event_start_basis(now: datetime, start: datetime, window: ChargeWindow, tz) -> tuple[str, datetime | None]:
    """How the SOC at an event's start is reached. A drain must never be carried across a charge window as if no charge
    happened (events.advise_event subtracts the demand before the event from the SOC now). FROM_NOW: no window occurrence
    overlaps [now, start); AFTER_WINDOW (with that window's end): exactly one occurrence lies in it and ends at or before
    the event start, so the event starts from that window's end SOC; NOT_MODELLED otherwise (the caller withholds the
    advice)."""
    if start <= now:
        occ = [window.occurrence(local_date(now, tz) + timedelta(days=k), tz) for k in (-1, 0)]
        return (EVENT_NOT_MODELLED, None) if any(s <= now < e for s, e in occ) else (EVENT_FROM_NOW, None)
    d0 = local_date(now, tz) - timedelta(days=1)
    span = max(0, (local_date(start, tz) - d0).days) + 1
    between = []
    for k in range(span + 1):
        s, e = window.occurrence(d0 + timedelta(days=k), tz)
        if e > now and s < start:
            between.append((s, e))
    if not between:
        return EVENT_FROM_NOW, None
    if len(between) == 1 and between[0][1] <= start:
        return EVENT_AFTER_WINDOW, between[0][1]
    return EVENT_NOT_MODELLED, None


def session_advice(cfg: SiteConfig, *, now: datetime, start: datetime, end: datetime, soc_pct: float | None,
                   soc_age_s: float | None, inverter_ok: bool | None, ha_reserve_pct: float | None,
                   before: Band | None, during: Band | None, after: Band | None,
                   reserve_raise_pct: float | None = None) -> Advice:
    """The Saving Session energy plan: events.advise_event on PLANNING (p90) demand before, during and after the event
    (`after` runs to the next refill), no PV credit, unknown power limits (only household cover is assessed). No reward
    model (O-4)."""
    def p90(b: Band | None) -> float | None:
        return None if b is None else b.p90
    labels = [b.label for b in (before, during, after) if b is not None]
    order = ("INSUFFICIENT", "LOW", "MEDIUM", "HIGH")
    label = min(labels, key=order.index) if labels else None
    return advise_event(cfg, EventInputs(now=now, event=ExportEvent(start, end, "saving_session"), soc_pct=soc_pct,
                                         soc_age_s=soc_age_s, inverter_ok=inverter_ok, demand_before_kwh=p90(before),
                                         demand_during_kwh=p90(during), demand_after_kwh=p90(after), demand_label=label,
                                         ha_reserve_pct=ha_reserve_pct, reserve_raise_pct=reserve_raise_pct))
