"""The SHADOW cycle: one pure function from CycleInputs to an AdvisoryEnvelope (planning-stream body behind the seam).

FROZEN INTERFACE (intelligence/tests/test_intel_contract_signatures.py):

    run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope

Order (each step fails closed; intelligence/tests/test_intel_shadow_cycle_contract.py holds for this body):

  1. paused -> paused_envelope (all nulls); a pause value other than True / False / None -> SELF_TEST_FAILED
     (PAUSE_CONTROL_INVALID);
  2. quality: intelligence.quality.assess_inputs re-verifies every input, prepare_history gives the learning history
     (none without a satisfied I-D8);
  3. tariff (intelligence.tariff): VERIFIED_FROM_INTEGRATION or a BLOCK / NO_VALUE finding, never a default price; the
     import rates must cover the whole charge-window search period to count for prices, the tariff block and the value;
     the window check reads the same payload judged without that coverage need (same parse, freshness and future-dated
     gates), so a payload short of the period never names a cheap run but its priced slots are still checked;
  4. charge window (intelligence.daily_plan, intelligence.tou_table): always the TOU slot table's single grid-charge run,
     classified fail closed (FOUNDATION CONTRACT section 13.5); with a VERIFIED tariff that names a cheap run, every rate
     slot of its occurrence from now on must lie in the tariff's cheap band; with one that names no cheap run (the
     search period not covered included), a priced slot of the occurrence at least the minimum cheap spread above the
     lowest rate priced in the search period or the same span before now (the look-back, A38) BLOCKs; otherwise (or
     with no such tariff) it stands with a WARN, and the charge-window items carry INFO CHARGE_WINDOW_NOT_PRICED when
     no price check covered the whole occurrence (A41); anything unknown, stale or in conflict BLOCKs. A
     configuration-poll reading is never younger than the configuration-poll liveness age (tighten-only, section 13.3);
  5. gates (site_decisions.gate) per item with the conditional context wired (capacity sources for I-D4; the clock
     changes and the window boundaries for I-D9 and the fixed DST rule); an unaccepted provenance counts as OPEN; every
     INVALID decision is also a top-level BLOCK;
  6. the decided configuration: site_decisions.apply_to_siteconfig, with the grid-charge limit capped at the lowest slot
     power of the TOU run (it can only lower it). When it returns None every battery-derived item and
     predicted_morning_soc is BLOCKED: the SiteConfig example capacity, efficiency, reserve, placeholder, window and
     grid-charge limit are never used for anything published. The raise-only reserve preference
     (pref.advisory_reserve_raise_pct, section 13.7) can only raise the planning floor; mapped but unusable, it BLOCKs
     the items I-D1 gates;
  7. forecasts: the V1 load and PV models (intelligence.engine.IntelligenceEngine). The V1 engine report is run on the
     DECIDED configuration when there is one, otherwise on the forecast-only configuration; every battery-derived V1
     output (recommended, trajectory, export, floor ETA, SOC forecast records) of a forecast-only run is discarded;
  8. V1.1 advisors (overnight, charge_target, events, dump_advice) only when the item's gates pass and its inputs are
     fresh; item views come from ItemView.from_advice (the single answer format). An OK item valid for less than
     REFRESH_MARGIN_S at compute time becomes BLOCKED INPUT_EXPIRING (section 13.4). An OK charge_target and an OK
     predicted_morning_soc carry exactly one TOU claim code (section 13.6), never a number;
  9. the pre-declared blocks: tariff (prices only with a VERIFIED tariff and an OK charge target), value (value.py,
     VERIFIED tariff only), plan (daily_plan), accuracy (outcome_metrics); drift and calibration stay None;
     engine_comparison only when charge_target is OK; scorecard_report is the V1 report without 'recommended'.

The null rule and the status precedence come from intelligence.advisory_contract (assemble_envelope), never from here.
Pure: `inputs.now` is the only time, no file or network access, never raises (an internal error gives SELF_TEST_FAILED).
Pure in its result also across cycles: the one state the engine keeps between calls is the exact, bounded memo of
intelligence.usage.build_profile (the usage model's slot profiles, most of a cycle's CPU when rebuilt every minute;
FOUNDATION CONTRACT section 13.4). Its key is an exact image of everything a profile is built from, so a hit returns
exactly what a fresh build would: the same inputs give a byte-identical envelope whether the memo is cold or warm.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType

from . import daily_plan as dp
from . import tariff as tf
from . import value as vl
from .advisor import LiveInputs, TariffInfo
from .advisory_contract import (ADVICE_ITEMS, FORECAST_ITEMS, MAX_BLOCKERS, MAX_REASON_CODES, MAX_SUMMARY_BYTES,
                                PV_TOMORROW_SUMMARY_KEYS, AdvisoryEnvelope, CycleInputs, DataQuality, ForecastView,
                                ItemStatus, ItemView, OutcomeMetrics, SiteReading, Versions, assemble_envelope,
                                paused_envelope, self_test_failed_envelope)
from .baselines import baselines as make_baselines, replay
from .battery import eta_one_way
from .charge_target import ChargeTargetInputs, advise_charge_target
from .config import SiteConfig
from .dump_advice import DumpInputs, advise_dump
from .engine import IntelligenceEngine
from .explain import OK as ADVICE_OK, Advice, Reason, blocked as blocked_advice, Blocker, finite_number
from .history import History
from .overnight import NightObservation, OvernightSettings, learn_overnight, nightly_totals
from .periods import clock_changes, period_profile
from .pv import PvModel, pv_hour_shape
from .quality import DQ_PROPOSED, assess_inputs, prepare_history, well_formed_records as _judged_records
from .site_decisions import (BLOCK, WARN, CHARGE_WINDOW_ITEMS, CHARGE_WINDOW_KEY, CONFIG_LIVENESS_KEY,
                             CONFIG_POLL_READINGS, DATE_SCOPED_READINGS, DECISION_IDS, DECISION_TITLES,
                             DEFAULT_ACCEPT_PROVENANCE,
                             DONGLE_READINGS, DONGLE_SIGNALS, EXCLUDE_CHANGED_PERIODS, HA_RESERVE_HELPER,
                             LIVENESS_KEY, SCALE_TO_ACTUAL, DecisionSet, DecisionStatus, DSTPolicy, Finding, GateContext,
                             InputState, apply_to_siteconfig, blocking, capacity_sources_context, clock_change_in_scope,
                             display_label, finding, freshness_limits, gate, items_gated_by, required_inputs)
from .tou_table import TOU_ENABLED_KEY, TOU_GRID_CHARGE_ENABLED_KEY, TOU_OVERLAY_KEY
from .timeutil import UTC, local_date, local_wall, zone
from .usage import fixed_window

CYCLE_VERSION = "intel-shadow-cycle-0.1.0-plan"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)      # the envelope time when the cycle time itself is unusable
HORIZON_H = 48                                          # PROPOSED: the forward periods a cycle plans (tonight, tomorrow)
PV_SOURCE_READING = "site_reading"                      # the PV forecast source name when the history names no single one
# Published blocker texts are fixed phrases: codes and words, never a value (integrator decision 4: numbers stay in
# Finding.evidence, which is not published). A text that nevertheless carries a value-shaped token (a number with a
# unit, a decimal number, a clock time) is not rewritten piecemeal: the WHOLE text is replaced by a fixed sentence and
# the item carries PUBLISHED_TEXT_REDACTED, so the replacement is visible (and the plan suites assert it never happens
# on their inputs). This is a last-resort guard, not the frozen suite's detector. It is a plain pattern string applied
# with re.search (the re module caches the compiled form): the vendor scan refuses any call named compile (CCR-1r2).
_VALUE_TOKEN_PATTERN = (r"\d\s?(?:%|kwh\b|kw\b|wh\b|w\b|ah\b|v\b|p/kwh|gbp\b|pence\b|min\b|h\b|s\b)|\u00a3|\d\.\d"
                        r"|\d:\d\d")
REDACTED_TEXT = "a detail of this finding is not shown in published text; see its reason code"
REDACTED_CODE = "PUBLISHED_TEXT_REDACTED"
# fixed published phrases for the codes whose upstream finding text used to state a value. Since CCR-PLAN-4 the
# foundation's texts carry no value and equal these phrases; they stay as a guard (a later upstream text change cannot
# reach a published text through these codes).
_FIXED_TEXTS = {
    "GRID_CHARGE_LIMIT_UNKNOWN": "no fresh finite grid-charge limit is available; the example limit is never used",
    "SITECONFIG_INVALID": "the decided values do not form a valid site configuration",
}

# FOUNDATION CONTRACT section 13.4: two 60 s runtime ticks plus 5 s, the shortest validity shown without a gap between
# ticks. An OK item valid for less than this at compute time is BLOCKED INPUT_EXPIRING (per item, tighten-only); the
# runtime's refresh margin has a drift test against this constant.
REFRESH_MARGIN_S = 125.0
# Section 13.4 (A31): the inputs of a quality-layer gate an item rests on bound its validity, with one documented
# exemption. The inverter clock offset gates every charge-window item (CHARGE_WINDOW_CLOCK_*), so it is in their validity
# (tighten-only). The supervision readings (quality.SUPERVISION_KEYS, a 90 s bound) gate export and Dump advice but are
# NOT in any item's validity, by design: the 90 s bound is shorter than REFRESH_MARGIN_S, so they would make export and
# Dump permanently INPUT_EXPIRING. Supervision is enforced at every compute instead, so a published OK export / Dump
# item can outlive a supervision lapse until the next compute: while polls arrive the runtime's poll-driven refresh
# (A23) computes after every telemetry poll (about one poll plus the settle delay plus the compute time); when the polls
# stop, the tick holds its refresh while the last poll is at most PROPOSED_POLL_ACTIVE_S (90 s) old, so the dongle items
# go INPUT_EXPIRING at the first tick after that (at most about 150 s after the last poll, plus the compute time); and in
# every runtime state the item never outlives its own validity (at most the 180 s liveness bound after its poll). Any
# ASSISTED use of export or Dump validity needs supervision in the validity first (a separate owner decision).
VALIDITY_GATE_READINGS = MappingProxyType({k: ("inverter.clock_offset_s",) for k in CHARGE_WINDOW_ITEMS})
INPUT_EXPIRING_TEXT = ("an input this item rests on expires before the next refresh, so the item is withheld until the "
                       "inputs are refreshed")
# Section 13.6: what the advice may claim about the inverter's own grid charging, as exactly one INFO code on an OK
# charge_target and an OK predicted_morning_soc (no window, target or other number). A grid-sourced slot is necessary,
# never sufficient: no text says that charging will happen.
TOU_CLAIM_CONFIGURED = "TOU_CLAIM_CONFIGURED"
TOU_CLAIM_NOT_EXPECTED = "TOU_CLAIM_NOT_EXPECTED"
TOU_CLAIM_UNCERTAIN = "TOU_CLAIM_UNCERTAIN"
TOU_CLAIM_CODES = (TOU_CLAIM_CONFIGURED, TOU_CLAIM_NOT_EXPECTED, TOU_CLAIM_UNCERTAIN)
# Fail closed: register 248 bits 1-15 are not decoded (they may restrict TOU to some weekdays), so CONFIGURED is reported
# as UNCERTAIN. Lifting this cap needs the owner's decision and an independent review.
TOU_CLAIM_CAPPED = True
MORNING_SOC_ASSUMES_CHARGE = "MORNING_SOC_ASSUMES_CHARGE"
# Section 13.5: the register-230 grid-charge current limit is not modelled in v0.1 (a WARN code, no number)
GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED = "GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED"
GRID_CHARGE_ITEMS = ("charge_target", "predicted_morning_soc", "v1_summary")
# Sections 13.5 and 13.8: the planning layer's INFO codes every charge-window item carries while the window stands:
# CHARGE_WINDOW_TOU_INSIDE_TARIFF (a named cheap run checked the whole occurrence) or CHARGE_WINDOW_NOT_PRICED (A41: no
# price check covered the whole occurrence; the residual the 72 h and 7-day acceptance count). Codes only, no number.
CHARGE_WINDOW_NOT_PRICED = dp.CHARGE_WINDOW_NOT_PRICED
CHARGE_WINDOW_ITEM_INFO_CODES = ("CHARGE_WINDOW_TOU_INSIDE_TARIFF", CHARGE_WINDOW_NOT_PRICED)
# Section 13.7: the raise-only advisory reserve preference
RESERVE_RAISE_KEY = "pref.advisory_reserve_raise_pct"
PREF_RESERVE_RAISE_UNKNOWN_TEXT = ("the advisory reserve raise preference is mapped but not usable (unavailable, not a "
                                   "percentage or observed in the future); a raised reserve is never dropped silently")
DECISION_VALUE_FROM_HELPER_TEXT = ("I-D1 takes the planning floor from the Home Assistant reserve helper: a live helper "
                                   "value acts as the floor, not a recorded value")


def _text_for(code: str, text: object) -> object:
    return _FIXED_TEXTS.get(code, text)


def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.tzinfo.utcoffset(x) is not None


def _pub(text: object) -> tuple[str, bool]:
    """(published text, redacted?): the text itself, or REDACTED_TEXT when it carries a value-shaped token."""
    t = str(text)
    return (REDACTED_TEXT, True) if re.search(_VALUE_TOKEN_PATTERN, t, re.IGNORECASE) else (t, False)


def _raw_history(history: object, now: datetime) -> History | None:
    """The unprepared history the PV model learns from: exactly the entries the quality layer judges (quality.well_formed_records:
    hour records filed under their own hour-aligned start, with dict energies, flags and sources), the same set
    prepare_history starts from, cut to the hours that had completely ended by `now`. Every other entry (junk, None, a
    record filed under another hour, a record with a malformed field) is left out here as the quality layer leaves it out
    (HISTORY_RECORD_MALFORMED, WARN); the quality layer judges the history and blocks the items that rest on it. For a
    well-formed history this equals history.truncated(now)."""
    if not isinstance(history, History):
        return None
    return History(_judged_records(history).values()).truncated(now)


def _hhmm(v: object) -> int | None:
    """'HH:MM' -> minutes after local midnight (24:00 allowed as 1440); anything else None."""
    if not (isinstance(v, str) and len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit()):
        return None
    h, m = int(v[:2]), int(v[3:])
    return h * 60 + m if (h < 24 and m < 60) or (h == 24 and m == 0) else None


def _slot_windows(slot_table: InputState | None) -> list[tuple[int, int]]:
    """(start_min, end_min) of every parseable slot of a FRESH TOU slot table reading ({start, end} 'HH:MM'); a window that
    ends at or before its start runs into the next day."""
    if not isinstance(slot_table, InputState) or not slot_table.fresh or not isinstance(slot_table.value, (list, tuple)):
        return []
    out = []
    for s in slot_table.value:
        if not hasattr(s, "get"):
            continue
        a, b = _hhmm(s.get("start")), _hhmm(s.get("end"))
        if a is None or b is None or a == b:
            continue
        out.append((a, b if b > a else b + 1440))
    return out


def dst_context(now: datetime, tz: str, slot_table: InputState | None, lookback_nights: int,
                extra_windows: tuple[tuple[int, int], ...] = ()) -> tuple[bool, bool]:
    """(clock change in scope, a period boundary in a changed hour) for the conditional I-D9 gate and the fixed DST rule.

    In scope: a change within the learning lookback, or within the forward horizon [now, now + HORIZON_H h) the cycle plans.
    Boundary: a charge-window slot of the fresh TOU table, or the judged charge window (`extra_windows`), on today's or
    tomorrow's local date, starts or ends in a repeated or missing hour, or lies in the spring gap (period_profile refuses
    it). Fail closed: an unusable zone gives (True, True); a change in the forward horizon with no window that can be
    profiled counts as a boundary in a changed hour."""
    try:
        horizon = (now, now + timedelta(hours=HORIZON_H))
        in_scope = clock_change_in_scope(now, (horizon,), lookback_nights, tz)
        ahead = bool(clock_changes(horizon[0], horizon[1], tz))
        z = zone(tz)
    except Exception:  # noqa: BLE001 - an unusable zone is never a pass
        return True, True
    windows = _slot_windows(slot_table) + [w for w in extra_windows if isinstance(w, tuple) and len(w) == 2]
    if ahead and not windows:
        return in_scope, True
    today = local_date(now, z)
    for day in (today, today + timedelta(days=1)):
        for a, b in windows:
            try:
                if period_profile(day, a, b, tz).boundary_in_changed_hour:
                    return in_scope, True
            except ValueError:                           # the window has no real length: it lies in the spring gap
                return in_scope, True
    return in_scope, False


def judged_reading(inputs: CycleInputs, key: str) -> InputState:
    """The cycle's judgement of one site reading at `inputs.now`: the quality layer's when it made one, else the same
    rule the cycle applies (_own_state). The backtest uses it so that its baselines rest on exactly the judgement the
    cycle makes (one baseline definition). Never raises: anything unusable is a reading that is not fresh."""
    try:
        if not _aware(inputs.now):
            return InputState(key, None, False, None, None)
        now = inputs.now.astimezone(UTC)
        decisions = inputs.decisions if isinstance(inputs.decisions, DecisionSet) else DecisionSet()
        accept = inputs.accept_provenance if isinstance(inputs.accept_provenance, frozenset) else DEFAULT_ACCEPT_PROVENANCE
        ages = dict(assess_inputs(inputs).ages)
        st = ages.get(key)
        config_age = _config_liveness_age(ages)
        if isinstance(st, InputState):
            return _config_aged(st, config_age) if key in CONFIG_POLL_READINGS else st
        live = ages.get(LIVENESS_KEY)
        liveness_age = live.age_s if isinstance(live, InputState) and live.fresh else None
        limits, _n = freshness_limits(decisions, accept)
        tzname = getattr(inputs.site_facts, "tz", "Europe/London")
        tz = zone(tzname) if isinstance(tzname, str) else None
        return _own_state(key, _readings_by_key(inputs.site_readings), limits, now, liveness_age, tz, config_age)
    except Exception:  # noqa: BLE001 - fail closed
        return InputState(key, None, False, None, None)


def run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope:
    """See the module docstring. Never raises. Its result depends on `inputs` alone: the usage profile memo it shares
    with earlier cycles (intelligence.usage.build_profile) only saves CPU and never changes a result."""
    try:
        return _run(inputs)
    except Exception as exc:  # noqa: BLE001 - fail closed: any internal error is a failed self-test, never an exception
        now = getattr(inputs, "now", None)
        versions = getattr(inputs, "versions", None)
        return self_test_failed_envelope(now if _aware(now) else _EPOCH,
                                         versions if isinstance(versions, Versions) else Versions(),
                                         {"CYCLE_INTERNAL_ERROR": type(exc).__name__})


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------

def _readings_by_key(readings: object) -> dict[str, SiteReading]:
    """Valid SiteReadings by key; a key given twice is dropped (neither is used), as the quality layer does."""
    out: dict[str, SiteReading] = {}
    dup: set[str] = set()
    for r in readings if isinstance(readings, tuple) else ():
        if not isinstance(r, SiteReading) or not isinstance(r.key, str):
            continue
        if r.key in out:
            dup.add(r.key)
        out[r.key] = r
    for k in dup:
        out.pop(k, None)
    return out


def _own_state(key: str, by_key: dict, limits, now: datetime, liveness_age: float | None, tz=None,
               config_age: float | None = None) -> InputState:
    """A reading the quality layer does not assess, judged with the same rule: the age from its observation time (a
    dongle reading: from the poll-text liveness time; a configuration-poll reading: the larger of the telemetry and the
    configuration liveness ages, unknown unless both are fresh), fresh only under a defined limit; a date-scoped forecast
    is fresh only when observed on the same local date as `now`."""
    r = by_key.get(key)
    lim = limits.get(key)
    if r is None or r.problems() or r.value is None or not _aware(r.observed_at):
        return InputState(key, None, False, None, lim)
    own = (now - r.observed_at).total_seconds()
    if own < 0:
        return InputState(key, r.value, False, None, lim)
    if key in DATE_SCOPED_READINGS:
        if tz is None:
            return InputState(key, r.value, False, own, None)
        day_limit = (now - local_wall(local_date(now, tz), 0, tz)).total_seconds()
        return InputState(key, r.value, local_date(r.observed_at, tz) == local_date(now, tz), own, day_limit)
    if key in CONFIG_POLL_READINGS:
        age = None if liveness_age is None or config_age is None else max(float(liveness_age), float(config_age))
    else:
        age = liveness_age if key in DONGLE_READINGS else own
    fresh = age is not None and lim is not None and age <= lim
    return InputState(key, r.value, fresh, age, lim)


def _config_liveness_age(ages) -> float | None:
    """The configuration-poll liveness age when the quality layer judged it fresh (FOUNDATION CONTRACT section 13.3),
    else None: then no configuration-poll reading is fresh."""
    st = ages.get(CONFIG_LIVENESS_KEY) if hasattr(ages, "get") else None
    if not isinstance(st, InputState) or st.fresh is not True or not finite_number(st.age_s) or st.age_s < 0:
        return None
    return float(st.age_s)


def _config_aged(st: object, config_age: float | None) -> object:
    """A configuration-poll reading is never younger than the configuration-poll liveness age, and never fresh without a
    fresh configuration liveness (tighten-only: the quality layer's own rule, applied again here)."""
    if not isinstance(st, InputState):
        return st
    if config_age is None or st.age_s is None:
        return InputState(st.key, st.value, False, st.age_s, st.limit_s)
    age = max(float(st.age_s), config_age)
    return InputState(st.key, st.value, bool(st.fresh) and st.limit_s is not None and age <= st.limit_s, age, st.limit_s)


def _power_capped(st: object, cw) -> object:
    """The grid-charge limit capped at the lowest slot power of the TOU run (section 13.5): min(limit, slot power), so it
    can only lower the limit. A window without a TOU run, or a limit that is not a number, is left as it is."""
    run = getattr(cw, "tou_run", None)
    cap = run.min_power_w if run is not None else None
    if not isinstance(st, InputState) or cap is None or not finite_number(st.value) or float(st.value) <= cap:
        return st
    return InputState(st.key, float(cap), st.fresh, st.age_s, st.limit_s)


def _reserve_raise(readings: object, now: datetime) -> tuple[bool, float | None]:
    """(present, usable value) of the raise-only reserve preference (section 13.7). Present = mapped: at least one
    reading with its key. Usable = exactly one well-formed reading, not observed in the future, whose value is a finite
    percentage in 0..100. A preference does not go stale like a sensor."""
    rs = tuple(readings) if isinstance(readings, (tuple, list)) else ()
    mine = [r for r in rs if isinstance(r, SiteReading) and r.key == RESERVE_RAISE_KEY]
    if not mine:
        return False, None
    if len(mine) != 1:
        return True, None
    r = mine[0]
    if r.problems() or not _aware(r.observed_at) or r.observed_at > now or not finite_number(r.value) \
            or not 0.0 <= float(r.value) <= 100.0:
        return True, None
    return True, float(r.value)


def _start_soc_bounds(cfg: SiteConfig, cw: dp.ChargeWindow, now: datetime, soc: float | None,
                      view: dp.HourlyView | None, ha: float | None,
                      rz: float | None = None) -> tuple[float, float] | None:
    """(lowest, highest) plausible SOC at the window start: high load and low PV down to the technical minimum, low load
    and high PV with the effective reserve held (each on the energy account of baselines.replay); the SOC now when the
    window has already started. None when the SOC or the hourly view is unknown."""
    if not finite_number(soc):
        return None
    if now >= cw.start:
        return float(soc), float(soc)
    if view is None:
        return None
    top = float(cfg.max_soc_pct)
    lo_load, lo_pv = view.scaled(view.load_hi, view.pv_lo)
    hi_load, hi_pv = view.scaled(view.load_lo, view.pv_hi)
    lo = replay(cfg, float(cfg.technical_min_soc_pct), None, float(soc), now, cw.start, None, lo_load, lo_pv).end_soc
    hi = replay(cfg, cfg.effective_reserve(ha, rz).effective_pct, None, float(soc), now, cw.start, None, hi_load,
                hi_pv).end_soc
    return max(0.0, min(top, lo)), max(0.0, min(top, hi))


def tou_claim(cw: dp.ChargeWindow | None, cfg: SiteConfig, now: datetime, soc: float | None,
              view: dp.HourlyView | None, ha: float | None, ages, inverter_ok: bool | None, *,
              reserve_raise_pct: float | None = None) -> str:
    """The TOU claim (section 13.6): CONFIGURED needs one target across the run above the highest plausible SOC at the
    window start, every slot power and the grid-charge limit above 0, inverter.healthy fresh and true, a fresh clock offset
    within its bound and a fresh, classified window; NOT_EXPECTED when the target is at or below the lowest plausible
    SOC; UNCERTAIN otherwise. While TOU_CLAIM_CAPPED, CONFIGURED is reported as UNCERTAIN. Never raises."""
    try:
        run = getattr(cw, "tou_run", None)
        target = run.single_target_pct if run is not None else None
        bounds = _start_soc_bounds(cfg, cw, now, soc, view, ha, reserve_raise_pct) if run is not None else None
        if target is None or bounds is None:
            return TOU_CLAIM_UNCERTAIN
        lo, hi = bounds
        if target <= lo + 1e-9:
            return TOU_CLAIM_NOT_EXPECTED
        gw = _fresh_number(ages.get("limits.max_grid_charge_w"), 0.0)
        off = _fresh_number(ages.get("inverter.clock_offset_s"))
        power = run.min_power_w
        configured = (target > hi + 1e-9 and power is not None and power > 0.0 and gw is not None and gw > 0.0
                      and inverter_ok is True and off is not None and abs(off) <= DQ_PROPOSED.clock_offset_block_s
                      and cw.state.fresh is True)
        return TOU_CLAIM_CONFIGURED if configured and not TOU_CLAIM_CAPPED else TOU_CLAIM_UNCERTAIN
    except Exception:  # noqa: BLE001 - a claim that cannot be judged is UNCERTAIN, never an exception
        return TOU_CLAIM_UNCERTAIN


def _signal_state(name: str, snapshot: object, limits, now: datetime, liveness_age: float | None) -> InputState:
    """A snapshot signal the quality layer did not assess, judged with its rule: the age from the observation time (a
    dongle signal: from the poll-text liveness time), fresh only under a defined limit; unknown or future times are
    never fresh."""
    lim = limits.get(name)
    try:
        obs = snapshot.get(name) if snapshot is not None and hasattr(snapshot, "get") else None
    except Exception:  # noqa: BLE001 - a malformed snapshot is a missing input
        obs = None
    value = getattr(obs, "value", None)
    at = getattr(obs, "observed_at", None)
    if obs is None or value is None or not _aware(at) or (now - at).total_seconds() < 0:
        return InputState(name, value, False, None, lim)
    age = liveness_age if name in DONGLE_SIGNALS else (now - at).total_seconds()
    return InputState(name, value, age is not None and lim is not None and age <= lim, age, lim)


def _preference(key: str, by_key: dict, now: datetime) -> float | None:
    """An optional owner preference (pref.*): present, well-formed, not observed in the future, a finite number >= 0.
    A preference does not go stale like a sensor."""
    r = by_key.get(key)
    if r is None or r.problems() or not _aware(r.observed_at) or r.observed_at > now:
        return None
    return float(r.value) if finite_number(r.value) and r.value >= 0 else None


def _remaining_s(st: InputState | None, now: datetime, tz) -> float:
    if not isinstance(st, InputState) or not st.fresh:
        return 0.0
    if st.key in DATE_SCOPED_READINGS:
        nxt = local_wall(local_date(now, tz) + timedelta(days=1), 0, tz)
        return max(0.0, (nxt - now).total_seconds())
    if st.limit_s is None or st.age_s is None:
        return 0.0
    return max(0.0, float(st.limit_s) - float(st.age_s))


def _valid_until(now: datetime, keys, ages, tz, cap: datetime | None = None) -> datetime:
    """Never later than the shortest remaining freshness of `keys`. The dongle liveness reading counts like every other
    input: a dongle input's age is the liveness age, but its own limit (I-D6, up to the ceiling) can be longer than the
    quality layer's liveness bound, after which every dongle input is stale."""
    rem = dp.PROPOSED_ADVICE_VALIDITY_S
    for k in keys:
        rem = min(rem, _remaining_s(ages.get(k), now, tz))
    vu = now + timedelta(seconds=rem)
    if cap is not None and cap < vu:
        vu = cap
    return max(vu, now)


def _clean_pv_history(pvh: object, today: date) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    if not isinstance(pvh, dict):
        return out
    for src, series in pvh.items():
        if not isinstance(src, str) or not isinstance(series, dict):
            continue
        clean = {d: float(v) for d, v in series.items() if isinstance(d, date) and not isinstance(d, datetime)
                 and d <= today and finite_number(v) and v >= 0}
        if clean:
            out[src] = dict(sorted(clean.items()))
    return dict(sorted(out.items()))


def _fresh_number(st: InputState | None, lo: float | None = None, hi: float | None = None) -> float | None:
    if not isinstance(st, InputState) or not st.fresh or st.limit_s is None or not finite_number(st.value):
        return None
    v = float(st.value)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def _trim_advice(advice: Advice) -> Advice:
    """The same Advice with long lists inside its recommendation shortened, so its view fits the summary byte budget."""
    rec = advice.recommendation
    if rec is None:
        return advice
    d = json.loads(json.dumps(advice.to_dict()["recommendation"], allow_nan=False))
    if len(json.dumps(d, separators=(",", ":"), sort_keys=True).encode("utf-8")) <= MAX_SUMMARY_BYTES:
        return advice
    for k in sorted(d):
        if isinstance(d[k], list) and len(d[k]) > 3:
            d[k] = d[k][:3]
        if isinstance(d[k], dict) and k in ("reserve", "changed_from_previous", "inputs_used"):
            d[k] = {kk: vv for kk, vv in d[k].items() if not isinstance(vv, str)}
    return Advice(advice.kind, advice.status, d, advice.confidence, advice.reasons, advice.assumptions, advice.blocking,
                  advice.inputs)


def _rebuild(view, **changes):
    """A copy of an ItemView / ForecastView with some fields changed (its summary as a plain mapping again, so the
    view's own checks run on it unchanged)."""
    summary = None if view.summary is None else dict(view.summary)
    blockers = changes.get("blockers", view.blockers)
    codes = changes.get("reason_codes", view.reason_codes)
    if isinstance(view, ForecastView):
        return ForecastView(view.key, view.status, view.value, view.p10, view.p90, view.valid_until, view.confidence,
                            blockers, codes, summary)
    return ItemView(view.key, view.status, view.value, view.valid_until, view.confidence, blockers, codes, summary)


def _sanitise(view):
    pubs = [(c, _pub(_text_for(c, t))) for c, t in view.blockers]
    v = _rebuild(view, blockers=tuple((c, p[0]) for c, p in pubs))
    return _with_codes(v, (REDACTED_CODE,)) if any(p[1] for _c, p in pubs) else v


def _codes(codes) -> tuple[str, ...]:
    """Unique codes within the cap; PUBLISHED_TEXT_REDACTED first, so it is never truncated away."""
    cs = tuple(codes)
    first = (REDACTED_CODE,) if REDACTED_CODE in cs else ()
    return tuple(dict.fromkeys(first + cs))[:MAX_REASON_CODES]


def _with_codes(view, codes):
    return _rebuild(view, reason_codes=_codes(tuple(view.reason_codes) + tuple(codes)))


def _view(key: str, advice: Advice, vu: datetime | None, extra_codes=()) -> ItemView:
    v = ItemView.from_advice(_trim_advice(advice), key=key, valid_until=vu if advice.status == ADVICE_OK else None)
    if v.status != ItemStatus.OK:
        v = _sanitise(v)
    return _with_codes(v, extra_codes)


class _Blocks:
    """Per-item blockers and reason codes collected from the gates, the quality layer and the planning layer."""

    def __init__(self) -> None:
        self.blockers: dict[str, list[tuple[str, str]]] = {}
        self.codes: dict[str, list[str]] = {}

    def _blocker(self, item: str, code: str, text: object) -> None:
        t, redacted = _pub(_text_for(code, text))
        self.blockers.setdefault(item, []).append((code, t))
        if redacted:
            self.codes.setdefault(item, []).append(REDACTED_CODE)

    def add(self, item: str, f: Finding) -> None:
        if f.severity == BLOCK:
            self._blocker(item, f.code, f.text)
        self.codes.setdefault(item, []).append(f.code)

    def block(self, item: str, code: str, text: str) -> None:
        self._blocker(item, code, text)
        self.codes.setdefault(item, []).append(code)

    def code(self, item: str, code: str) -> None:
        self.codes.setdefault(item, []).append(code)

    def blocked(self, item: str) -> bool:
        return bool(self.blockers.get(item))

    def parts(self, item: str) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
        first: dict[str, str] = {}
        for c, t in self.blockers.get(item, []):
            first.setdefault(c, t)                      # one blocker per code (the first, most specific text)
        bl = tuple(first.items())[:MAX_BLOCKERS]
        return bl, _codes(self.codes.get(item, []))


def _require(blocks: _Blocks, item: str, ok: bool) -> None:
    """A prerequisite the gates and the quality layer do not name (a model, a window, a configuration) BLOCKs too."""
    if not ok and not blocks.blocked(item):
        blocks.block(item, "PLANNING_INPUTS_MISSING", "a planning input this item rests on is not available")


def _blocked_item(key: str, blocks: _Blocks) -> ItemView:
    bl, rc = blocks.parts(key)
    return ItemView(key, ItemStatus.BLOCKED, blockers=bl or (("INPUTS_NOT_VERIFIED", "the quality layer blocked this item"),),
                    reason_codes=rc)


def _blocked_forecast(key: str, blocks: _Blocks) -> ForecastView:
    bl, rc = blocks.parts(key)
    return ForecastView(key, ItemStatus.BLOCKED, blockers=bl or (("INPUTS_NOT_VERIFIED", "the quality layer blocked this item"),),
                        reason_codes=rc)


def _insufficient(key: str, blocks: _Blocks, code: str, forecast: bool = False):
    _bl, rc = blocks.parts(key)
    rc = _codes(rc + (code,))
    return ForecastView(key, ItemStatus.INSUFFICIENT_DATA, reason_codes=rc) if forecast else \
        ItemView(key, ItemStatus.INSUFFICIENT_DATA, reason_codes=rc)


def _overnight(history: History, cfg: SiteConfig, window: dp.ChargeWindow, tz, tzname: str, now: datetime,
               dst: DSTPolicy | None) -> Advice:
    """overnight_demand for the period the charge target must carry: from the window end to the next window start
    (local wall clock), learned from complete past periods only. I-D9: a changed history period is excluded or normalised
    to its nominal length; a changed target period is scaled to its actual length (SCALE_TO_ACTUAL) or only up
    (SCALE_UP_ONLY). Without a satisfied I-D9 a changed period is never learned from or planned."""
    a, b = window.local_minutes
    start_min, end_min = b, 1440 + a
    target = local_date(window.end, tz)
    s = OvernightSettings.from_site(cfg)
    first = target - timedelta(days=s.lookback_nights)
    last = target - timedelta(days=1)
    while last >= first and local_wall(last, end_min, tz) > now:
        last -= timedelta(days=1)
    try:
        obs = nightly_totals(history, cfg, start_min, end_min, first, last) if last >= first else []
    except ValueError:                       # a period the V1 counter cannot measure: this item only, never the cycle
        return blocked_advice("overnight_demand", [Blocker("OVERNIGHT_PERIOD_INVALID",
                                                           "the period from the charge window end to the next window "
                                                           "start cannot be measured")])
    adjusted = []
    for o in obs:
        try:
            pp = period_profile(o.night, start_min, end_min, tzname)
        except ValueError:
            adjusted.append(NightObservation(o.night, None, "DST_PERIOD_UNMEASURABLE"))
            continue
        if not pp.changed or o.kwh is None:
            adjusted.append(o)
        elif dst is None or dst.history_rule == EXCLUDE_CHANGED_PERIODS:
            adjusted.append(NightObservation(o.night, None, "DST_CHANGED_PERIOD"))
        else:
            adjusted.append(NightObservation(o.night, o.kwh / pp.factor))
    period = f"{tf.hhmm(b)} to {tf.hhmm(a)}, the charge window end to the next start"
    adv = learn_overnight(adjusted, target, s, period=period)
    try:
        tp = period_profile(target, start_min, end_min, tzname)
    except ValueError:
        return blocked_advice("overnight_demand", [Blocker("DST_PERIOD_UNMEASURABLE",
                                                           "the coming period cannot be measured across the clock change")])
    if not tp.changed or adv.recommendation is None:
        return adv
    if dst is None:
        return blocked_advice("overnight_demand", [Blocker("DST_POLICY_REQUIRED",
                                                           "the coming period crosses a clock change and I-D9 is not satisfied")])
    f = tp.factor if dst.target_rule == SCALE_TO_ACTUAL else max(1.0, tp.factor)
    rec = json.loads(json.dumps(adv.to_dict()["recommendation"]))
    for k in ("expected_kwh", "planning_kwh"):
        if finite_number(rec.get(k)):
            rec[k] = round(rec[k] * f, 3)
    rec["dst_target_factor"] = round(f, 4)
    reasons = adv.reasons + (Reason("DST_TARGET_SCALED", "the coming period crosses a clock change; its demand is scaled "
                                                        "as I-D9 records"),)
    return Advice(adv.kind, adv.status, rec, adv.confidence, reasons, adv.assumptions, adv.blocking, adv.inputs)


def _scorecard_report(report: dict | None, decided: bool) -> dict | None:
    """The V1 report without 'recommended'; SOC forecast records only from a run on the decided configuration."""
    if not isinstance(report, dict):
        return None
    rep = {k: v for k, v in report.items() if k != "recommended"}
    recs = [r for r in rep.get("forecast_records") or [] if isinstance(r, dict)
            and (str(r.get("kind", "")).startswith(("load_kwh:", "pv_kwh:")) or (decided and str(r.get("kind", "")).startswith("soc_pct:")))]
    rep["forecast_records"] = recs
    rep["shadow_scope"] = "decided configuration" if decided else "forecast-only configuration: battery outputs discarded"
    try:
        out = json.loads(json.dumps(rep, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError):
        return None
    return None if _has_key(out, "recommended") else out


def _has_key(v: object, key: str) -> bool:
    if isinstance(v, dict):
        return key in v or any(_has_key(x, key) for x in v.values())
    if isinstance(v, list):
        return any(_has_key(x, key) for x in v)
    return False


def _windows_around(cw: dp.ChargeWindow, now: datetime, tz) -> list[tuple[datetime, datetime]]:
    d0 = local_date(now, tz) - timedelta(days=1)
    return [cw.occurrence(d0 + timedelta(days=k), tz) for k in range(4)]


# ---------------------------------------------------------------------------------------------------------------------
# the cycle
# ---------------------------------------------------------------------------------------------------------------------

def _run(inputs: CycleInputs) -> AdvisoryEnvelope:
    versions = inputs.versions if isinstance(inputs.versions, Versions) else Versions()
    if not _aware(inputs.now):
        return self_test_failed_envelope(_EPOCH, versions, {"NOW_INVALID": "the cycle time is not an aware datetime"})
    now = inputs.now.astimezone(UTC)
    decisions = inputs.decisions if isinstance(inputs.decisions, DecisionSet) else DecisionSet()
    accept = inputs.accept_provenance if isinstance(inputs.accept_provenance, frozenset) else DEFAULT_ACCEPT_PROVENANCE
    if inputs.paused is True:
        return paused_envelope(now, versions, decisions=decisions, accept_provenance=accept)
    if inputs.paused is not False and inputs.paused is not None:
        # a pause value that is neither True, False nor None (1, 'on', ...) is a broken pause control: no advice at all
        return self_test_failed_envelope(now, versions, {"PAUSE_CONTROL_INVALID": "the pause control value is not a "
                                                                                  "boolean"},
                                         decisions=decisions, accept_provenance=accept, paused=None)
    paused = inputs.paused

    # ---- 2. quality ---------------------------------------------------------------------------------------------
    q = assess_inputs(inputs)
    ages = dict(q.ages)
    tzname = getattr(inputs.site_facts, "tz", "Europe/London")
    tzname = tzname if isinstance(tzname, str) else ""
    try:
        tz = zone(tzname)
    except Exception:  # noqa: BLE001 - an unknown zone is a blocked cycle, never a crash
        tz = None
    blocks = _Blocks()
    top_codes: list[str] = []
    by_key = _readings_by_key(inputs.site_readings)
    limits, _ln = freshness_limits(decisions, accept)
    live_state = ages.get(LIVENESS_KEY)
    liveness_age = live_state.age_s if isinstance(live_state, InputState) and live_state.fresh else None
    # a configuration-poll reading is never younger than the configuration-poll liveness age, and is not fresh without a
    # fresh configuration liveness (section 13.3; tighten-only, the quality layer's rule applied again)
    config_age = _config_liveness_age(ages)
    for k in CONFIG_POLL_READINGS:
        if k in ages:
            ages[k] = _config_aged(ages[k], config_age)

    # ---- 3. tariff ----------------------------------------------------------------------------------------------
    def obs_at(key: str):
        r = by_key.get(key)
        return r.observed_at if r is not None else None
    # the import rates verify only when they cover the whole cheap-run search period: a payload with only today's rates
    # (tomorrow's not published yet), or only a few slots, never names a cheap run and is never a price
    imp = tf.assess_rates(ages.get("tariff.import_rates"), now, kind="import", observed_at=obs_at("tariff.import_rates"),
                          need=(now, now + timedelta(hours=tf.PROPOSED_WINDOW_SEARCH_H)))
    # the window check (A30 / A35, contract 13.5) reads the same payload with the same parse, freshness and future-dated
    # gates but WITHOUT the coverage need: a payload short of the search period names no cheap run (cheap_window refuses
    # it with TARIFF_COVERAGE_SHORT), so it never sets or confirms the window, yet a slot it prices that conflicts with
    # the TOU window still BLOCKs (ENG6-1; tighten-only: the result is that BLOCK or the same TOU window with a WARN).
    # The no-run check's lowest rate also reads this judgement's slots up to PROPOSED_WINDOW_SEARCH_H before now (A38,
    # tariff.horizon_low_p_per_kwh), so one day-rates event keeps its passed cheap slots as the comparison.
    # Prices, the tariff block and the value keep `imp`, judged with the coverage need.
    imp_window = imp if imp.verified else tf.assess_rates(ages.get("tariff.import_rates"), now, kind="import",
                                                          observed_at=obs_at("tariff.import_rates"))
    exp = tf.assess_rates(ages.get("tariff.export_rates"), now, kind="export", observed_at=obs_at("tariff.export_rates"))
    top_codes.append("TARIFF_VERIFIED" if imp.verified else (imp.findings[0].code if imp.findings else "TARIFF_NOT_VERIFIED"))
    def judged(key: str) -> InputState:
        """The quality layer's judgement of a reading when it made one, else the same rule applied here."""
        st = ages.get(key)
        return st if isinstance(st, InputState) else _own_state(key, by_key, limits, now, liveness_age, tz, config_age)
    ev_state = judged("tariff.events")
    events, ev_notes = tf.parse_events(ev_state.value) if ev_state.value is not None else ((), [])
    events_known = ev_state.fresh and ev_state.value is not None and not blocking(ev_notes)

    # ---- 4. the charge window -----------------------------------------------------------------------------------
    # the enables and the overlay come from the quality layer when it judged them, else the same rule here
    tou_states = {k: judged(k) for k in (TOU_ENABLED_KEY, TOU_GRID_CHARGE_ENABLED_KEY, TOU_OVERLAY_KEY)}
    cw, cw_notes = (dp.choose_charge_window(now, tz, imp_window, ages.get("tariff.import_rates"), ages.get("tou.slot_table"),
                                            tou_enabled=tou_states[TOU_ENABLED_KEY],
                                            grid_charge_enabled=tou_states[TOU_GRID_CHARGE_ENABLED_KEY],
                                            tou_overlay=tou_states[TOU_OVERLAY_KEY])
                    if tz is not None else (None, [finding("TZ_INVALID", BLOCK, CHARGE_WINDOW_KEY, "the site time zone is unusable")]))
    top_codes.append("CHARGE_WINDOW_FROM_TARIFF" if cw is not None and cw.source == dp.SOURCE_TARIFF else
                     ("CHARGE_WINDOW_FROM_TOU_TABLE" if cw is not None else "CHARGE_WINDOW_UNKNOWN"))
    cw_info = [f.code for f in cw_notes if cw is not None and f.code in CHARGE_WINDOW_ITEM_INFO_CODES]
    # why the window is what it is, or why there is none (e.g. why the tariff check refused the window, a TOU refusal)
    top_codes += [f.code for f in cw_notes if f.severity in (BLOCK, WARN)]

    # ---- 5. gates -----------------------------------------------------------------------------------------------
    n_cap, mismatch = capacity_sources_context(decisions, ages, accept)
    in_scope, boundary = dst_context(now, tzname, ages.get("tou.slot_table"), OvernightSettings().lookback_nights,
                                     (cw.local_minutes,) if cw is not None else ())
    ctx = GateContext(capacity_sources=n_cap, capacity_mismatch_pct=mismatch, clock_change_in_scope=in_scope,
                      boundary_in_changed_hour=boundary)
    all_keys = ADVICE_ITEMS + FORECAST_ITEMS + ("v1_summary",)
    tariff_sets_window = cw is not None and cw.source == dp.SOURCE_TARIFF
    for k in all_keys:
        for f in gate(k, decisions, ctx, accept):
            blocks.add(k, f)
        for f in q.findings:
            if f.subject == k:
                if tariff_sets_window and f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" and f.severity == WARN:
                    continue                 # the quality layer's 'would come from the TOU table' does not apply
                blocks.add(k, f)
        if k in q.blocked_items and not blocks.blocked(k):
            blocks.block(k, "INPUTS_NOT_VERIFIED", "the quality layer blocked this item")
        if q.data_quality == DataQuality.BLOCKED and not blocks.blocked(k):
            blocks.block(k, "DATA_QUALITY_BLOCKED", "data quality is BLOCKED")
        if tz is None:
            blocks.block(k, "TZ_INVALID", "the site time zone is unusable")
    # an INVALID record means the site decisions file is broken: no advice at all until it is fixed (stricter than the
    # per-item gate, which already blocks every item the decision can gate). pv_tomorrow rests on no decision.
    if any(decisions.get(did).status == DecisionStatus.INVALID for did in DECISION_IDS):
        for k in ADVICE_ITEMS + ("predicted_day_load", "predicted_morning_soc", "v1_summary"):
            blocks.block(k, "SITE_DECISIONS_INVALID", "a recorded decision is INVALID; no advice is shown until the site "
                                                      "decisions file is corrected")

    # ---- 6. the decided configuration ---------------------------------------------------------------------------
    base = inputs.base_cfg if isinstance(inputs.base_cfg, SiteConfig) else None
    facts = inputs.site_facts
    fcfg = None
    if base is not None and tz is not None:
        lat, lon = getattr(facts, "latitude", None), getattr(facts, "longitude", None)
        kwp = getattr(facts, "pv_array_kwp", None)
        a, b = cw.local_minutes if cw is not None else (base.cheap_window_start_min, base.cheap_window_end_min)
        try:
            # the forecast-only configuration: site facts (zone, position, array size) and the judged window; its battery
            # fields stay the base values and are used for nothing published (apply_to_siteconfig replaces them all)
            fcfg = replace(base, tz=tzname, latitude=float(lat) if finite_number(lat) else base.latitude,
                           longitude=float(lon) if finite_number(lon) else base.longitude,
                           pv_array_kwp=float(kwp) if finite_number(kwp) and kwp > 0 else None,
                           cheap_window_start_min=a, cheap_window_end_min=b)
        except (TypeError, ValueError):
            fcfg = None
    readings = dict(ages)
    if cw is not None:
        readings[CHARGE_WINDOW_KEY] = cw.state
        # the grid-charge power: min(the limit reading, the lowest slot power of the TOU run); it can only lower it
        readings["limits.max_grid_charge_w"] = _power_capped(readings.get("limits.max_grid_charge_w"), cw)
    if fcfg is not None:
        cfg, cfg_notes = apply_to_siteconfig(fcfg, decisions, readings, accept)
    else:
        cfg, cfg_notes = None, [finding("BASE_CONFIG_MISSING", BLOCK, "site_config",
                                        "no usable site configuration built from site facts")]
    battery_items = ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc", "v1_summary")
    if cfg is None:
        for k in battery_items:
            for f in cfg_notes:
                if f.severity == BLOCK:
                    blocks.add(k, f)
            if not blocks.blocked(k):
                blocks.block(k, "SITE_CONFIG_NOT_DECIDED", "the battery configuration is not fully decided")
    if cw is None:
        for k in ("overnight_demand",) + battery_items:
            for f in cw_notes:
                if f.severity in (BLOCK, WARN):
                    blocks.add(k, f)                 # the BLOCK as a blocker; why no source served as a reason code
            if not blocks.blocked(k):
                blocks.block(k, "CHARGE_WINDOW_UNKNOWN", "no charge window: the TOU slot table gives none")
    else:
        for k in ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"):
            blocks.code(k, "CHARGE_WINDOW_FROM_TARIFF" if cw.source == dp.SOURCE_TARIFF else "CHARGE_WINDOW_FROM_TOU_TABLE")
        for k in battery_items:
            for c in cw_info:
                blocks.code(k, c)
        for k in GRID_CHARGE_ITEMS:                      # the register-230 current limit is not modelled (WARN, no number)
            blocks.code(k, GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED)

    # ---- 7. forecasts -------------------------------------------------------------------------------------------
    hist, h_notes = prepare_history(inputs.history, decisions, now, accept_provenance=accept)
    for f in h_notes:
        if f.severity == BLOCK:
            for k in ("overnight_demand", "predicted_day_load", "charge_target", "predicted_morning_soc", "export_event",
                      "dump_to_grid", "v1_summary"):
                blocks.add(k, f)
    raw_hist = _raw_history(inputs.history, now)
    today = local_date(now, tz) if tz is not None else None
    tomorrow = today + timedelta(days=1) if today is not None else None
    pvh = _clean_pv_history(inputs.pv_forecast_history, today) if today is not None else {}
    src = next(iter(pvh)) if len(pvh) == 1 else PV_SOURCE_READING
    pv_raw = {}
    for day_key, key in (("today", "pv.forecast_today_kwh"), ("tomorrow", "pv.forecast_tomorrow_kwh")):
        v = _fresh_number(judged(key), 0.0)
        pv_raw[day_key] = {src: v} if v is not None else {}

    soc_st = ages.get("battery.soc")
    soc = _fresh_number(soc_st, 0.0, 100.0)
    soc_age = soc_st.age_s if soc is not None else None
    inv = ages.get("inverter.healthy")
    inverter_ok = True if isinstance(inv, InputState) and inv.fresh and inv.limit_s is not None and inv.value is True else None
    # the HA reserve helper is ACS1's lower bound, raise-only in advice (contract reserve roles): with I-D1 =
    # HA_RESERVE_HELPER it is the floor (judged by the quality layer and apply_to_siteconfig); with any other I-D1 source a
    # fresh in-range helper value still raises the effective reserve (never lowers it), and is recorded in a reason code
    d1_helper = decisions.satisfied("D1", accept) and getattr(decisions.value("D1"), "source", None) == HA_RESERVE_HELPER
    helper_key = "reserve.ha_minimum_soc"
    helper_st = ages.get(helper_key) if d1_helper else _signal_state(helper_key, inputs.snapshot, limits, now, liveness_age)
    ha = _fresh_number(helper_st, 0.0, 100.0)
    ha_codes: tuple[str, ...] = ()
    if not d1_helper and decisions.satisfied("D1", accept):
        if ha is not None:
            ha_codes = ("HA_RESERVE_HELPER_RAISE_ONLY",)
        elif isinstance(helper_st, InputState) and helper_st.value is not None:
            ha_codes = ("HA_RESERVE_HELPER_IGNORED",)          # present but stale, of unresolved age or not a percentage
    for k in ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"):
        for c in ha_codes:
            blocks.code(k, c)
    d1_items = items_gated_by("D1")
    if d1_helper:                                    # a helper never acts as a decision unseen (section 13.7)
        for k in d1_items:
            blocks.add(k, finding("DECISION_VALUE_FROM_HELPER", WARN, k, DECISION_VALUE_FROM_HELPER_TEXT))
    # the raise-only reserve preference: a run-time input of its own beside the HA helper (`rz`; `ha` stays the helper's
    # own value), so it can only raise the effective reserve (config.effective_reserve takes the maximum; a reserve the
    # configuration cannot hold is the advisors' SHORTFALL) and the breakdown names it as itself, never as the helper
    # (A33, ENG-5). Every consumer of the reserve takes both.
    raise_present, raise_pct = _reserve_raise(inputs.site_readings, now)
    rz = None
    if raise_present and raise_pct is None:
        for k in d1_items:
            blocks.block(k, "PREF_RESERVE_RAISE_UNKNOWN", PREF_RESERVE_RAISE_UNKNOWN_TEXT)
    elif raise_pct is not None:
        rz = raise_pct
        if cfg is not None and cfg.effective_reserve(ha, rz).binding == "reserve_raise":
            for k in d1_items:
                blocks.code(k, "PREF_RESERVE_RAISE")
    sessions = [(e.start, e.end) for e in events if e.kind == "saving_session"]

    engine = report = None
    run_cfg = cfg if cfg is not None else fcfg
    if hist is not None and run_cfg is not None and tz is not None:
        engine = IntelligenceEngine(hist, run_cfg, pvh)
        if cw is not None:
            live1 = LiveInputs(now=now, soc_pct=soc, soc_age_s=soc_age,
                               load_w=_fresh_number(ages.get("house.power")), pv_w=_fresh_number(ages.get("pv.power"), 0.0),
                               pv_raw_today=dict(pv_raw["today"]), pv_raw_tomorrow=dict(pv_raw["tomorrow"]),
                               ha_reserve_pct=ha, reserve_raise_pct=rz,
                               tariff=TariffInfo(_windows_around(cw, now, tz), source="octopus_rates" if cw.source ==
                                                 dp.SOURCE_TARIFF else "tou_slot_table"),
                               saving_sessions=list(sessions), inverter_ok=inverter_ok)
            report = engine.run(live1)
    v1_ok = (cfg is not None and report is not None and not blocks.blocked("v1_summary"))
    v1_rec = report.get("recommended") if v1_ok and isinstance(report, dict) else None

    pv_model = engine.pv if engine is not None else None
    if pv_model is None and raw_hist is not None and fcfg is not None:
        pv_model = PvModel(raw_hist, fcfg, pvh)      # PV learning uses the PV channel only (I-D8 concerns house load)
    pv_fc = {}
    if pv_model is not None and today is not None:
        for d, k in ((today, "today"), (tomorrow, "tomorrow")):
            try:
                pv_fc[d] = pv_model.forecast_day(d, pv_raw[k])
            except (ValueError, ZeroDivisionError, OverflowError):
                pass
    usage = engine.usage if engine is not None else None
    asof = today

    # ---- 8. items -----------------------------------------------------------------------------------------------
    items: dict[str, ItemView] = {}
    fcs: dict[str, ForecastView] = {}

    vu_states = dict(ages)
    vu_states["tariff.events"] = ev_state            # the judged event list (the quality layer may not assess it)
    vu_states.update(tou_states)                     # the judged enables and overlay a TOU window rests on

    def vu_for(key: str, cap: datetime | None = None) -> datetime:
        """Never longer than the shortest remaining freshness of what the item rests on: its required inputs, the
        charge-window source(s) (also for the overnight demand, whose period is the charge window), for export / Dump
        advice the event list, for the charge-window items the inverter clock offset their quality gate reads
        (VALIDITY_GATE_READINGS, A31), and the dongle liveness reading whenever any of these is a dongle input (the same
        rule as required_inputs: a window read from the TOU slot table rests on the dongle through the window alone).
        The supervision readings are not in it, by design (VALIDITY_GATE_READINGS, contract 13.4)."""
        ri = required_inputs(key, decisions, accept)
        keys = list(ri.signals) + list(ri.readings)
        if cw is not None and key in ("overnight_demand", "charge_target", "export_event", "dump_to_grid",
                                      "predicted_morning_soc"):
            keys += list(cw.input_keys)
        if key in ("export_event", "dump_to_grid"):
            keys.append("tariff.events")
        keys += list(VALIDITY_GATE_READINGS.get(key, ()))
        if any(k in DONGLE_SIGNALS or k in DONGLE_READINGS or k in CONFIG_POLL_READINGS for k in keys):
            keys.append(LIVENESS_KEY)
        if any(k in CONFIG_POLL_READINGS for k in keys):
            keys.append(CONFIG_LIVENESS_KEY)         # both liveness keys bound a configuration-poll input (13.3)
        return _valid_until(now, keys, vu_states, tz, cap)

    def finish(v):
        """INPUT_EXPIRING (section 13.4): an OK item valid for less than REFRESH_MARGIN_S at compute time is BLOCKED (per
        item, tighten-only), so it never shortens the envelope's validity below the margin."""
        if v.status != ItemStatus.OK or v.valid_until is None or (v.valid_until - now).total_seconds() >= REFRESH_MARGIN_S:
            return v
        blocks.block(v.key, "INPUT_EXPIRING", INPUT_EXPIRING_TEXT)
        return _blocked_forecast(v.key, blocks) if isinstance(v, ForecastView) else _blocked_item(v.key, blocks)

    def claimed(v, *codes):
        """An OK view with these codes first (never truncated away); any other view unchanged."""
        if v.status != ItemStatus.OK:
            return v
        return _rebuild(v, reason_codes=_codes(tuple(codes) + tuple(v.reason_codes)))

    # overnight demand
    overnight = None
    _require(blocks, "overnight_demand", hist is not None and cw is not None and fcfg is not None and tz is not None)
    if blocks.blocked("overnight_demand"):
        items["overnight_demand"] = _blocked_item("overnight_demand", blocks)
    else:
        d9 = decisions.value("D9") if decisions.satisfied("D9", accept) else None
        overnight = _overnight(hist, fcfg, cw, tz, tzname, now, d9)
        _bl, rc = blocks.parts("overnight_demand")
        items["overnight_demand"] = finish(_view("overnight_demand", overnight, vu_for("overnight_demand"), rc))

    # the hourly view (load and PV) for the plan and the value
    period_band = None
    view = None
    if usage is not None and cw is not None and asof is not None:
        horizon_end = cw.next_start_after(cw.end, tz)
        period_band = dp.load_band(usage, "plan_period", cw.end, horizon_end, tz, asof)
        try:
            prof = usage.profile(asof, "fast").values
            shape = pv_hour_shape(hist, run_cfg, asof)
        except (ValueError, ZeroDivisionError):
            prof, shape = None, [0.0] * 24
        pv_shape = shape
        pv_days = {d: (fc.p50, shape) for d, fc in pv_fc.items() if fc.label != "INSUFFICIENT"}
        tfc = pv_fc.get(tomorrow)
        pv_band = (tfc.p10, tfc.p50, tfc.p90) if tfc is not None and tfc.label != "INSUFFICIENT" else None
        view = dp.hourly_view(prof, pv_days, tz, period_band, pv_band) if prof is not None else None
    else:
        horizon_end = None
        pv_shape = [0.0] * 24

    # charge target
    target = None
    _require(blocks, "charge_target", cfg is not None and cw is not None and usage is not None)
    if not blocks.blocked("charge_target") and (overnight is None or items["overnight_demand"].status == ItemStatus.BLOCKED):
        blocks.block("charge_target", "DEMAND_NOT_AVAILABLE", "the overnight demand it rests on is not available")
    if blocks.blocked("charge_target"):
        items["charge_target"] = _blocked_item("charge_target", blocks)
    else:
        credit, credit_label = None, None
        pv_day = local_date(cw.end, tz)
        fc = pv_fc.get(pv_day)
        if fc is not None and fc.label in ("MEDIUM", "HIGH") and cw.end.astimezone(tz).hour < 12:
            # only the PV after the window end's hour counts (conservative), at its p10
            share = sum(pv_shape[h] for h in range(cw.end.astimezone(tz).hour + 1, 24)) if len(pv_shape) == 24 else 0.0
            credit, credit_label = max(0.0, fc.p10 * share), fc.label
        wl = dp.load_band(usage, "plan_window", max(now, cw.start), cw.end, tz, asof)
        start_soc = None
        if now < cw.start and soc is not None:
            pre = dp.load_band(usage, "plan_pre_window", now, cw.start, tz, asof)
            if pre is not None:
                # planning (p90) drain until the window opens; the battery is taken as held at the effective reserve
                # (the grid carries the house below it), the same energy account as the baselines
                start_soc = dp.held_soc_after(cfg, soc, pre.p90, cfg.effective_reserve(ha, rz).effective_pct)
        target = advise_charge_target(cfg, ChargeTargetInputs(
            now=now, window=(cw.start, cw.end), demand=overnight, soc_pct=soc, soc_age_s=soc_age, ha_reserve_pct=ha,
            pv_credit_kwh=credit, pv_credit_label=credit_label, window_load_kwh=None if wl is None else wl.p50,
            soc_at_window_start_pct=start_soc, reserve_raise_pct=rz))
        _bl, rc = blocks.parts("charge_target")
        items["charge_target"] = finish(_view("charge_target", target, vu_for("charge_target", cw.end), rc))
    ct_ok = items["charge_target"].status == ItemStatus.OK
    claim = None
    if ct_ok:
        claim = tou_claim(cw, cfg, now, soc, view, ha, ages, inverter_ok, reserve_raise_pct=rz)
        items["charge_target"] = claimed(items["charge_target"], claim)

    # the plan
    plan = None
    if ct_ok and horizon_end is not None:
        plan = dp.build_plan(cfg=cfg, now=now, tz=tz, window=cw, horizon_end=horizon_end, target=target,
                             ha_reserve_pct=ha, soc_pct=soc, view=view, v1_recommended=v1_rec,
                             wear_cost_p_per_kwh=_preference("pref.wear_cost_p_per_kwh", by_key, now),
                             morning_band=dp.load_band(usage, "plan_morning", cw.end, dp.morning_anchor(cw.end, tz), tz,
                                                       asof), reserve_raise_pct=rz)
        top_codes += [f.code for f in plan.findings if f.severity in (BLOCK, WARN)]

    # export event (Saving Session energy plan)
    ek = "export_event"
    _require(blocks, ek, cfg is not None and cw is not None and usage is not None)
    if not blocks.blocked(ek) and not events_known:
        blocks.block(ek, "TARIFF_EVENTS_NOT_FRESH", "the event list is missing, malformed or of unresolved age, so no "
                                                    "event can be planned or ruled out")
    if blocks.blocked(ek):
        items[ek] = _blocked_item(ek, blocks)
    else:
        ahead = [e for e in events if e.kind == "saving_session" and e.end > now and e.start < now + timedelta(hours=HORIZON_H)]
        if not ahead:
            _bl, rc = blocks.parts(ek)
            items[ek] = ItemView(ek, ItemStatus.NO_ADVICE, reason_codes=tuple(dict.fromkeys(rc + ("NO_EVENT_AHEAD",)))[:MAX_REASON_CODES])
        else:
            e = ahead[0]
            refill = cw.next_start_after(e.end, tz)
            # the SOC the event starts from: never a drain carried across a charge window as if nothing charged
            basis, w_end = dp.event_start_basis(now, e.start, cw, tz)
            ev_soc, before_from, ev_codes, ev_cap = soc, now, (), e.end
            if basis == dp.EVENT_AFTER_WINDOW and w_end == cw.end and ct_ok and plan is not None \
                    and plan.status == dp.PLAN_OK and finite_number(plan.planned_soc_pct):
                ev_soc, before_from = float(plan.planned_soc_pct), cw.end
                ev_codes = ("EVENT_START_FROM_PLANNED_WINDOW_END",)
                ev_cap = min(e.end, items["charge_target"].valid_until or now)       # it rests on the charge target
            elif basis != dp.EVENT_FROM_NOW:
                blocks.block(ek, "EVENT_AFTER_REFILL_NOT_MODELLED",
                             "the event comes after a charge window (or inside one) and no OK charge target plans the "
                             "battery level it would start from")
            if blocks.blocked(ek):
                items[ek] = _blocked_item(ek, blocks)
            else:
                # the drain before the event on the reserve-held account (the same as the charge target's window-start
                # SOC and the baselines): the event starts from at least the reserve, never from a level below empty
                before = dp.load_band(usage, "event_before", before_from, e.start, tz, asof) if e.start > now else None
                if before is not None and ev_soc is not None:
                    raw = ev_soc - before.p90 / eta_one_way(cfg) / cfg.battery_capacity_kwh * 100.0
                    ev_soc = dp.held_soc_after(cfg, ev_soc, before.p90, cfg.effective_reserve(ha, rz).effective_pct)
                    if ev_soc > raw + 1e-9:
                        ev_codes += ("EVENT_START_HELD_AT_RESERVE",)
                    before = dp.Band(0.0, 0.0, 0.0, before.label)     # already taken: advise_event starts from ev_soc
                adv = dp.session_advice(cfg, now=now, start=e.start, end=e.end, soc_pct=ev_soc, soc_age_s=soc_age,
                                        inverter_ok=inverter_ok, ha_reserve_pct=ha, before=before,
                                        during=dp.load_band(usage, "event_during", max(now, e.start), e.end, tz, asof),
                                        after=dp.load_band(usage, "event_after", e.end, refill, tz, asof),
                                        reserve_raise_pct=rz)
                rec = adv.recommendation if adv.status == ADVICE_OK and hasattr(adv.recommendation, "get") else {}
                socs = [rec.get(k) for k in ("soc_at_start_pct", "soc_at_end_expected_pct")]
                if adv.status == ADVICE_OK and not all(finite_number(x) and 0.0 <= x <= 100.0 for x in socs):
                    blocks.block(ek, "EVENT_SOC_OUT_OF_RANGE", "the event plan's battery level is outside what a battery "
                                                               "can hold, so the plan is withheld")
                    items[ek] = _blocked_item(ek, blocks)
                else:
                    _bl, rc = blocks.parts(ek)
                    items[ek] = finish(_view(ek, adv, vu_for(ek, ev_cap), rc + ev_codes))

    # Dump to Grid (reserve-aware stop level)
    dk = "dump_to_grid"
    _require(blocks, dk, cfg is not None and cw is not None and usage is not None)
    if not blocks.blocked(dk) and not events_known:
        blocks.block(dk, "TARIFF_EVENTS_NOT_FRESH", "the event list is missing, malformed or of unresolved age, so a "
                                                    "Saving Session ahead cannot be ruled out")
    if blocks.blocked(dk):
        items[dk] = _blocked_item(dk, blocks)
    else:
        refill = cw.start if cw.start > now else cw.next_start_after(now, tz)
        until = dp.load_band(usage, "dump_until_refill", now, refill, tz, asof)
        lsess = getattr(inputs.live, "saving_sessions", None)
        extra = [s for s in lsess if isinstance(s, tuple) and len(s) == 2] if isinstance(lsess, list) else []
        adv = advise_dump(cfg, DumpInputs(now=now, soc_pct=soc, soc_age_s=soc_age, inverter_ok=inverter_ok, refill_at=refill,
                                          demand_until_refill_kwh=None if until is None else until.p90,
                                          demand_label=None if until is None else until.label,
                                          in_charge_window=cw.start <= now < cw.end,
                                          saving_sessions=tuple(sessions) + tuple(extra), ha_reserve_pct=ha,
                                          reserve_raise_pct=rz))
        _bl, rc = blocks.parts(dk)
        items[dk] = finish(_view(dk, adv, vu_for(dk, refill), rc))

    # forecasts: predicted_day_load (tomorrow), pv_tomorrow, predicted_morning_soc
    fk = "predicted_day_load"
    _require(blocks, fk, usage is not None and tomorrow is not None)
    if blocks.blocked(fk):
        fcs[fk] = _blocked_forecast(fk, blocks)
    else:
        fn = fixed_window(0, 1440, tz)
        f = usage.forecast("day", fn(tomorrow), fn, asof)
        _bl, rc = blocks.parts(fk)
        if f.label == "INSUFFICIENT" or not all(finite_number(x) for x in (f.p10, f.p50, f.p90)):
            fcs[fk] = _insufficient(fk, blocks, "LOAD_HISTORY_INSUFFICIENT", True)
        else:
            summ = {k: v for k, v in f.to_dict().items() if k in ("kind", "t0", "t1", "p10", "p50", "p90", "n_days",
                                                                   "n_residuals", "confidence", "label", "usable")}
            # 'tomorrow' is date-scoped: never valid past the next local midnight (then it describes today)
            fcs[fk] = finish(ForecastView(fk, ItemStatus.OK, round(f.p50, 2), round(f.p10, 2), round(f.p90, 2),
                                          _valid_until(now, ["history.hourly"], ages, tz, local_wall(tomorrow, 0, tz)),
                                          f.label, (), tuple(dict.fromkeys(("LOAD_FORECAST_V1",) + rc))[:MAX_REASON_CODES],
                                          summ))
    pk = "pv_tomorrow"
    tfc = pv_fc.get(tomorrow) if tomorrow is not None else None
    if blocks.blocked(pk):
        fcs[pk] = _blocked_forecast(pk, blocks)
    elif tfc is None or tfc.label == "INSUFFICIENT":
        fcs[pk] = _insufficient(pk, blocks, "PV_FORECAST_INSUFFICIENT", True)
    else:
        summ = {k: v for k, v in tfc.to_dict().items() if k in PV_TOMORROW_SUMMARY_KEYS}
        try:
            summ = json.loads(json.dumps(summ, allow_nan=False))
            if len(json.dumps(summ, separators=(",", ":")).encode("utf-8")) > MAX_SUMMARY_BYTES:
                summ = {k: v for k, v in summ.items() if k != "notes"}
        except (TypeError, ValueError):
            summ = None
        _bl, rc = blocks.parts(pk)
        fcs[pk] = finish(ForecastView(pk, ItemStatus.OK, round(tfc.p50, 2), round(tfc.p10, 2), round(tfc.p90, 2),
                                      _valid_until(now, ["history.hourly", "pv.forecast_tomorrow_kwh"], ages, tz),
                                      tfc.label, (), tuple(dict.fromkeys(("PV_FORECAST_V1",) + rc))[:MAX_REASON_CODES],
                                      summ))
    mk = "predicted_morning_soc"
    if blocks.blocked(mk):
        fcs[mk] = _blocked_forecast(mk, blocks)
    elif not ct_ok or plan is None or plan.status != dp.PLAN_OK or plan.morning_soc is None:
        code = "CHARGE_TARGET_NOT_OK" if not ct_ok else "PLAN_NOT_OK"
        fcs[mk] = _insufficient(mk, blocks, code, True)
    else:
        lo, mid, hi = plan.morning_soc
        _bl, rc = blocks.parts(mk)
        at_reserve = tuple(f.code for f in plan.findings if f.code == "MORNING_SOC_AT_RESERVE")
        fcs[mk] = finish(ForecastView(mk, ItemStatus.OK, mid, lo, hi, vu_for(mk, cw.end), items["charge_target"].confidence,
                                      (), _codes(("MORNING_SOC_FROM_CHARGE_TARGET",) + at_reserve + rc),
                                      {"at": plan.morning_at.isoformat(), "planned_window_end_soc_pct": plan.planned_soc_pct,
                                       "basis": "the V1.1 charge target reached at the window end, then the forecast load "
                                                "and PV, with the effective reserve held"}))
        # it starts from the planned window-end SOC, so it assumes the window charges: said plainly while the claim is
        # not CONFIGURED (with the cap: always)
        fcs[mk] = claimed(fcs[mk], *((claim,) if claim is not None else ()) + (
            (MORNING_SOC_ASSUMES_CHARGE,) if claim != TOU_CLAIM_CONFIGURED else ()))

    # ---- 9. the pre-declared blocks ------------------------------------------------------------------------------
    ct_view = items["charge_target"]
    # tariff.window (foundation contract, CCR-INT-1): the charge window the plan used, {start, end} as aware ISO-8601 UTC
    # timestamps, or None
    tariff_window = (None if cw is None else
                     {"start": cw.start.astimezone(UTC).isoformat(), "end": cw.end.astimezone(UTC).isoformat()})
    tariff_block = {"provenance": imp.provenance, "window": tariff_window, "price_range": None}
    if imp.verified and ct_ok and horizon_end is not None:
        pr = imp.price_range(now, min(horizon_end, imp.slots[-1].end))     # over the verified part of the horizon
        tariff_block["price_range"] = None if pr is None else [round(pr[0], 2), round(pr[1], 2)]
    value_block = None
    plan_block = None
    engine_cmp = None
    if ct_ok and plan is not None and plan.status == dp.PLAN_OK:
        plan_block = plan.plan_block()
    if ct_ok and imp.verified and horizon_end is not None:
        v1_target = None
        if isinstance(v1_rec, dict):
            v1_target = (v1_rec.get("overnight_target") or {}).get("recommended_target_soc_pct")
        bls, _bn = make_baselines(max_soc_pct=cfg.max_soc_pct,
                                  tou_current=judged("tou.current_target_soc_pct"),
                                  v1_target_pct=v1_target, decisions_satisfied=v1_ok)
        vr = vl.project_value(cfg=cfg, floor_pct=cfg.effective_reserve(ha, rz).effective_pct, now=now,
                              horizon_end=horizon_end,
                              window=(cw.start, cw.end), soc_pct=soc, advice_target_pct=ct_view.value,
                              baselines=bls, view=view, import_tariff=imp, export_tariff=exp,
                              cycling_cost_p=None if plan is None else plan.cycling_cost_p)
        value_block = vr.block()
        top_codes += [f.code for f in vr.findings]
    elif ct_ok:
        top_codes.append("VALUE_TARIFF_NOT_VERIFIED")
    if ct_ok and isinstance(v1_rec, dict):
        ot = v1_rec.get("overnight_target") or {}
        v1t = ot.get("recommended_target_soc_pct")
        if finite_number(v1t) and finite_number(ct_view.value):
            engine_cmp = {"v1_target_soc_pct": float(v1t), "v11_target_soc_pct": float(ct_view.value),
                          "difference_pct": round(float(v1t) - float(ct_view.value), 2),
                          "v1_feasible_on_pessimistic_path": bool(ot.get("feasible_on_pessimistic_path")),
                          "authority": "V1.1 charge_target",
                          "basis": "V1 hourly simulation versus the V1.1 closed-form budget, both on the decided configuration"}
    om = inputs.outcome_metrics
    accuracy = None
    if isinstance(om, OutcomeMetrics):
        okm = all(x is None or (finite_number(x) and x >= 0) for x in (om.mae_7d, om.coverage_7d))
        okn = isinstance(om.n, int) and not isinstance(om.n, bool) and om.n >= 0
        if okm and okn:
            accuracy = {"mae_7d": om.mae_7d, "coverage_7d": om.coverage_7d, "n": om.n}
    scorecard = _scorecard_report(report, v1_ok) if report is not None else None

    # ---- top level: quality blockers that name no item, and every INVALID decision ---------------------------------
    named = set(ADVICE_ITEMS + FORECAST_ITEMS + ("v1_summary",))
    top: list[tuple[str, str]] = []

    def top_blocker(code: str, text: object) -> None:
        t, redacted = _pub(_text_for(code, text))
        top.append((code, t))
        if redacted:
            top_codes.append(REDACTED_CODE)

    for f in q.findings:
        if f.severity == BLOCK and f.subject not in named:
            top_blocker(f.code, f.text)
    for did in DECISION_IDS:
        d = decisions.get(did)
        code = f"DECISION_{did}_INVALID"
        if d.status == DecisionStatus.INVALID and code not in {c for c, _t in top}:
            top_blocker(code, f"{display_label(did)} ({DECISION_TITLES[did]}) is INVALID: " + "; ".join(d.problems))
    top_t = tuple(dict.fromkeys(top))[:MAX_BLOCKERS]
    first = [REDACTED_CODE] if REDACTED_CODE in top_codes else []      # a redaction is never truncated away
    reason_codes = tuple(dict.fromkeys(first + [c for c, _t in top_t] + top_codes))[:MAX_REASON_CODES - 1]

    item_views = tuple(items[k] for k in ADVICE_ITEMS)
    forecast_views = tuple(fcs[k] for k in FORECAST_ITEMS)
    ok_vus = [v.valid_until for v in item_views + forecast_views if v.status == ItemStatus.OK and v.valid_until is not None]
    env_vu = min(ok_vus + [now + timedelta(seconds=dp.PROPOSED_ADVICE_VALIDITY_S)])
    return assemble_envelope(now, versions, items=item_views, forecasts=forecast_views, data_quality=q.data_quality,
                             decisions=decisions, accept_provenance=accept, paused=paused, valid_until=max(env_vu, now),
                             next_run_at=None, blockers=top_t, reason_codes=reason_codes, input_ages=q.input_ages(),
                             tariff=tariff_block, value=value_block, plan=plan_block, accuracy=accuracy,
                             engine_comparison=engine_cmp, scorecard_report=scorecard)
