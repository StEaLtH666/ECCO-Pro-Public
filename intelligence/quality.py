"""Input quality for the SHADOW cycle: the independent re-verification of every input the cycle may use.

FROZEN INTERFACE (intelligence/tests/test_intel_contract_signatures.py):

    assess_inputs(inputs: CycleInputs) -> QualityResult{findings, blocked_items, data_quality, ages}
    prepare_history(history, decisions, now, *, accept_provenance=...) -> (History | None, findings)

What `assess_inputs` guarantees (each rule has a code, a severity and the items it affects; docs/intelligence/
DATA_QUALITY_METHOD.md has the table):

  * every age is recomputed from `now` and the raw observation time, never taken from the caller; a dongle-sourced input's
    age comes from the poll-text liveness reading (the dongle publishes only changed values), and a poll text older than
    the PROPOSED liveness bound makes every dongle-sourced input stale; a reading published by the dongle's configuration
    poll (site_decisions.CONFIG_POLL_READINGS) is aged by the larger of the telemetry and the configuration-poll liveness
    ages and is fresh only while both liveness readings are within their PROPOSED bounds, and a missing, future or stale
    configuration-poll liveness reading BLOCKs every item that requires it (CONFIG_LIVENESS_*: every charge-window item;
    contract section 13.3); the supervision state and stable flag are aged by the telemetry liveness; a snapshot signal
    is never younger than the snapshot itself (now - snapshot.as_of), and an old snapshot BLOCKs every item resting on
    it; a missing liveness reading, an unresolved freshness limit, an unknown or future observation time and a
    malformed, non-finite or implausible value all make an input not fresh; the history's age comes from its well-formed
    hour records only;
  * an input the caller called fresh that is not fresh here BLOCKs (CALLER_FRESHNESS_DISAGREES) and makes the data quality
    BLOCKED, as do malformed or self-contradicting caller assessments; an input the caller withheld (judged not fresh) is
    not used either, except a dongle-sourced one, whose age the caller cannot know (the poll-text liveness decides);
  * every item whose required inputs (site_decisions.required_inputs) are not all fresh is blocked;
  * content rules: SOC false zero, SOC sources disagreeing, online flags that cannot time out, the live power balance
    (CT sign reversal), the native-load false zero, LiveInputs against the snapshot, supervision, the I-D4 capacity band,
    SOC near protection, the inverter clock offset against a TOU-derived charge window, tariff and event presence, and the
    history rules (flaps, gaps, coverage, stalls, catch-up jumps, energy balance over the whole history, the learning
    lookback and the most recent hours, clock-change nights, prolonged zero PV against its forecast).

A finding's text never carries a number with a unit (numbers live in `Finding.evidence`, which is not published).
Detection thresholds are technical constants labelled PROPOSED (DQ_PROPOSED), set in the direction that blocks more; none is
an owner value and none unblocks anything.

`prepare_history` returns a COPY: None unless I-D8 is satisfied; otherwise hours that had ended by `now`, with I-D8's load
policies applied (EXCLUDE / KEEP_NON_EXPORTING_ONLY for load power, EXCLUDE_PRE_CUTOVER / KEEP_AFTER_COUNTER_CHECK for the
load counter; a counter hour the check cannot be run on is removed) and the counter faults removed. The History passed in
is never modified.

Three readings (the raw SOC, the inverter clock offset, the event table) are I-D6 keys with no default limit (CCR-DQ-1):
while a site's I-D6 records no limit for one of them it is never fresh (UNRESOLVED), and the rules that need it fail
closed (a SOC false zero BLOCKs; every charge-window item BLOCKs, also with a verified tariff; export_event BLOCKs).

Pure: no clock read, no I/O, never raises for malformed contents of its inputs.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Iterable, Mapping

from ecco_core.state import Snapshot, spec_for

from .advisor import LiveInputs
from .advisory_contract import SITE_READING_KEYS, TOU_OVERLAY_STATES, CycleInputs, DataQuality, SiteReading
from .config import DEFAULT_TECHNICAL_MIN_SOC_PCT
from .explain import finite_number
from .history import (ENERGY_FIELDS, F_GAP_INTERP, F_SOC_SUSPECT, History, HourRecord)
from .overnight import OvernightSettings
from .periods import clock_changes
from .site_decisions import (BLOCK, CAPACITY_READING_BY_KIND, CONDITIONAL_D4_ITEMS, CONFIG_LIVENESS_KEY,
                             CONFIG_POLL_READINGS, DATE_SCOPED_READINGS, DEFAULT_ACCEPT_PROVENANCE, DONGLE_READINGS,
                             DONGLE_SIGNALS, EXCLUDE, EXCLUDE_PRE_CUTOVER, INFO, ITEMS, KEEP_AFTER_COUNTER_CHECK,
                             KEEP_NON_EXPORTING_ONLY, LIVENESS_KEY, LIVENESS_KEYS, OWNER_STATEMENT, PROPOSED,
                             REQUIRED_SIGNALS, WARN, DecisionSet, Finding, InputState, capacity_sources_context, finding,
                             freshness_limits, required_inputs)
from .timeutil import HOUR, UTC, day_bounds, local_date, local_wall, zone

QUALITY_VERSION = "intel-quality-0.3.1-cfg"

FRESH, STALE, UNKNOWN, MISSING = "fresh", "stale", "unknown", "missing"


# ---------------------------------------------------------------------------------------------------------------------
# PROPOSED detection thresholds (technical constants, not owner decisions)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectionThresholds:
    """Every number below is a PROPOSED technical detection constant of the data-quality layer. None is an owner value or
    an owner decision; each is set in the direction that blocks more, and none can make an input fresh or unblock an item.
    The source of each value is in docs/intelligence/DATA_QUALITY_METHOD.md (the PROPOSED thresholds table)."""
    status: str = "PROPOSED"
    liveness_max_age_s: float = 180.0            # the Battery Outlook model's poll-text rule; tighter than the I-D6 proposal
    config_liveness_max_age_s: float = 300.0     # the configuration poll runs about every 60 s: five polls, one late poll
    #                                              tolerated (contract 13.3, A4); no I-D6 entry can loosen it
    snapshot_max_age_s: float = 180.0            # the snapshot is built at cycle time; older than the liveness bound = old
    supervision_max_heartbeat_age_s: float = 90.0  # firmware SUSPECT threshold, applied to reported age + reading age
    supervision_reading_max_age_s: float = 90.0  # the same bound on the supervision state and stable readings' age, which
    #                                              is the telemetry liveness age (both are published only on a change)
    soc_zero_max_pct: float = 0.5                # a SOC at or below this reads as zero (SOC has whole-percent resolution)
    soc_zero_discharge_w: float = 100.0          # a zero SOC while discharging above this is not credible
    protection_margin_pct: float = 10.0          # SOC within this of the protection level withholds export and Dump advice
    load_zero_max_w: float = 0.5                 # the native load reads zero
    load_false_zero_flow_w: float = 150.0        # HD1: inverter + grid above this proves a native zero false
    clock_offset_warn_s: float = 30.0            # firmware background correction floor
    clock_offset_block_s: float = 30.0           # equal to the warn bound: any offset worth a warning refuses a TOU window
    power_max_w: float = 100000.0                # a W reading above this is not a domestic value (plausibility)
    capacity_ah_max: float = 20000.0             # an Ah register above this is not a domestic battery (plausibility)
    pv_forecast_max_kwh_per_kwp: float = 10.0    # a day-ahead PV forecast above this per kWp of array is not physical
    flap_window_h: int = 24
    flap_min_dropouts: int = 2                   # recovered dropouts in the window that count as flapping
    gap_warn_h: int = 6                          # the history builder's longest spread gap
    coverage_window_h: int = 168                 # the most recent week
    coverage_min_fraction: float = 0.8           # History.energy_scaled's default coverage
    stall_energy_max_kwh: float = 0.005          # history.counter_to_hourly's stall test
    stall_power_min_w: float = 300.0             # SiteConfig.stall_power_w default
    catchup_excess_min_kwh: float = 1.0          # a counter hour above twice the power integral and this much above it
    balance_tol_kwh: float = 0.2                 # two counter steps
    balance_tol_fraction: float = 0.10
    ct_reversal_min_hours: int = 6
    ct_reversal_min_share: float = 0.5
    ct_recent_hours: int = 12                    # the most recent distinguishable hours judged on their own (recent onset)
    ct_recent_window_h: int = 72                 # ... looked for within this many hours before now
    export_evidence_kwh: float = 0.05            # an hour exporting more than this is an exporting hour
    false_zero_after_cutover_block_hours: int = 3
    counter_check_tol_kwh: float = 0.1
    counter_check_tol_fraction: float = 0.10
    pv_zero_day_max_kwh: float = 0.05
    pv_forecast_min_kwh: float = 0.5
    pv_zero_min_days: int = 2
    history_day_min_coverage: float = 0.9        # a local day counts for the zero-PV rule only when this well covered


DQ_PROPOSED = DetectionThresholds()

# Readings the rules need: I-D6 keys with no default limit (CCR-DQ-1), so UNRESOLVED (never fresh) until a site's I-D6
# records a limit. Until then the raw SOC never resolves a false zero, export_event BLOCKs TARIFF_EVENTS_NOT_FRESH, and a
# charge-window item whose TOU slot table is fresh BLOCKs CHARGE_WINDOW_CLOCK_UNKNOWN (also with a verified tariff). With
# I-D6 OPEN the table itself is UNRESOLVED, so those items block CHARGE_WINDOW_UNKNOWN first (the clock rule runs only on
# a fresh table).
QUALIFYING_READING_KEYS = ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events")
SUPERVISION_KEYS = ("supervision.state", "supervision.stable", "supervision.heartbeat_age_s")
SUPERVISED = "SUPERVISED"
ONLINE_FLAGS = ("controller.telemetry", "canonical.telemetry")      # flags that hold their last state; no timeout

SOC_ITEMS = tuple(i for i in ITEMS if "battery.soc" in REQUIRED_SIGNALS[i])
POWER_ITEMS = tuple(i for i in ITEMS if "house.power" in REQUIRED_SIGNALS[i])
HEALTH_ITEMS = tuple(i for i in ITEMS if "inverter.healthy" in REQUIRED_SIGNALS[i])
HISTORY_ITEMS = tuple(i for i in ITEMS if "history.hourly" in REQUIRED_SIGNALS[i])
DONGLE_ITEMS = tuple(i for i in ITEMS if any(s in DONGLE_SIGNALS for s in REQUIRED_SIGNALS[i]))
HISTORY_ONLY_ITEMS = tuple(i for i in HISTORY_ITEMS if i not in DONGLE_ITEMS)
EXPORT_ITEMS = ("export_event", "dump_to_grid")                    # supervision and SOC-near-protection BLOCK these
EVENT_ITEMS = ("export_event",)
PV_ITEMS_WARNED = ("charge_target", "predicted_morning_soc")
# findings that tell the cycle an item should be INSUFFICIENT_DATA rather than computed (evidence item_status)
INSUFFICIENT_DATA_CODES = frozenset({"PV_NO_OUTPUT_VS_FORECAST"})

# readings judged whatever the decisions say (their rules need them, or the planning layer reads this layer's judgement:
# the TOU enables and the overlay state, so the configuration-poll enables are never aged by the telemetry poll alone
# downstream; the current TOU target stays the planning layer's own judgement, CCR-PLAN-1)
_TOU_AUX = ("tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state")
_AUX_READINGS = ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events", "tariff.import_rates",
                 "tariff.export_rates", "protection.shutdown_soc_pct", "tou.slot_table") + _TOU_AUX
_NON_NUMERIC_UNITS = ("datetime", "enum", "bool", "table")
_PRESENCE_TABLES = ("tariff.import_rates", "tariff.export_rates", "tou.slot_table")   # an empty table is not present


_S = "<structure>"                     # a CycleInputs field itself (its type, its time, the caller's assessments)
_POWERS = ("house.power", "pv.power", "battery.power", "grid.power")
# Every BLOCK code this module can emit and the inputs it judges. dq BLOCKs only on inputs declared in REQUIRED_SIGNALS,
# REQUIRED_READINGS or SITE_READING_KEYS (plus the reserve helper signal that I-D1's HA_RESERVE_HELPER source adds through
# required_inputs) or on a malformed CycleInputs structure; test_intel_quality checks both directions.
RULE_INPUTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "NOW_INVALID": (_S,), "TZ_INVALID": (_S,), "QUALITY_INTERNAL_ERROR": (_S,), "DECISIONS_MALFORMED": (_S,),
    "SITE_READINGS_MALFORMED": (_S,), "SITE_READING_DUPLICATE": (_S,), "SNAPSHOT_MALFORMED": (_S,),
    "SNAPSHOT_IN_FUTURE": (_S,), "SNAPSHOT_STALE": (_S,), "LIVE_INPUTS_MALFORMED": (_S,), "CALLER_ASSESSMENT_MALFORMED": (_S,),
    "CALLER_ASSESSMENT_INCONSISTENT": (_S,), "CALLER_ASSESSMENT_CONFLICT": (_S,), "CALLER_FRESHNESS_DISAGREES": (_S,),
    "SITE_FACT_MISSING": (_S,),
    # the decision register's own findings, passed through (site_decisions.freshness_limits)
    "DECISION_D6_INVALID": (_S,), "FRESHNESS_OVERRIDE_INVALID": (_S,), "FRESHNESS_OVERRIDE_UNKNOWN_KEY": (_S,),
    "FRESHNESS_OVERRIDE_ABOVE_CEILING": (_S,), "FRESHNESS_OVERRIDE_REFUSED": (_S,),
    "INPUT_NOT_FRESH": tuple(sorted({s for v in REQUIRED_SIGNALS.values() for s in v} | set(SITE_READING_KEYS)
                                    | {"reserve.ha_minimum_soc"})),
    "LIVENESS_MISSING": (LIVENESS_KEY,), "LIVENESS_IN_FUTURE": (LIVENESS_KEY,), "LIVENESS_STALE": (LIVENESS_KEY,),
    "CONFIG_LIVENESS_MISSING": (CONFIG_LIVENESS_KEY,), "CONFIG_LIVENESS_IN_FUTURE": (CONFIG_LIVENESS_KEY,),
    "CONFIG_LIVENESS_STALE": (CONFIG_LIVENESS_KEY,),
    "SOC_OUT_OF_RANGE": ("battery.soc", "battery.soc_raw_pct"),
    "SOC_FALSE_ZERO_UNRESOLVED": ("battery.soc", "battery.soc_raw_pct"),
    "SOC_ZERO_WHILE_DISCHARGING": ("battery.soc", "battery.soc_raw_pct", "battery.power"),
    "SOC_SOURCES_DISAGREE": ("battery.soc", "battery.soc_raw_pct"),
    "ONLINE_FLAG_UNCONFIRMED": ("inverter.healthy", LIVENESS_KEY), "INVERTER_NOT_HEALTHY": ("inverter.healthy",),
    "HOUSE_POWER_NEGATIVE": ("house.power",), "LOAD_FALSE_ZERO": _POWERS, "CT_SIGN_REVERSED": _POWERS,
    "BATTERY_SIGN_REVERSED": _POWERS, "POWER_BALANCE_INCONSISTENT": _POWERS,
    "LIVE_INPUTS_DISAGREE": ("battery.soc", "house.power", "pv.power", "inverter.healthy", "reserve.ha_minimum_soc"),
    "SUPERVISION_NOT_STABLE": SUPERVISION_KEYS + (LIVENESS_KEY,), "TARIFF_EVENTS_NOT_FRESH": ("tariff.events",),
    "CHARGE_WINDOW_UNKNOWN": ("tou.slot_table", "tariff.import_rates"),
    "CHARGE_WINDOW_CLOCK_UNKNOWN": ("tou.slot_table", "inverter.clock_offset_s"),
    "CHARGE_WINDOW_CLOCK_OFFSET": ("tou.slot_table", "inverter.clock_offset_s"),
    "CAPACITY_MISMATCH_UNKNOWN": tuple(CAPACITY_READING_BY_KIND.values()),
    "CAPACITY_SOURCES_CONFLICT": tuple(CAPACITY_READING_BY_KIND.values()),
    "PROTECTION_LEVEL_UNKNOWN": ("battery.soc", "protection.shutdown_soc_pct"),
    "SOC_NEAR_PROTECTION": ("battery.soc", "protection.shutdown_soc_pct"),
    "TELEMETRY_FLAPPING": ("history.hourly",), "HISTORY_COVERAGE_LOW": ("history.hourly",),
    "HISTORY_CT_REVERSED": ("history.hourly",), "HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER": ("history.hourly",),
    "HISTORY_MISSING": ("history.hourly",), "DECISIONS_MISSING": (_S,), "ACCEPT_PROVENANCE_INVALID": (_S,),
    "DECISION_D8_OPEN": (_S,), "DECISION_D8_INVALID": (_S,), "HISTORY_MALFORMED": ("history.hourly",),
    "PV_NO_OUTPUT_VS_FORECAST": ("history.hourly", "pv.forecast_tomorrow_kwh"),
})


@dataclass(frozen=True)
class QualityResult:
    findings: tuple[Finding, ...]
    blocked_items: frozenset[str]
    data_quality: str
    ages: Mapping[str, InputState] = field(default_factory=dict)

    def input_ages(self) -> tuple[dict, ...]:
        """The ages as plain rows for the envelope's unrecorded input_ages attribute (sorted by name). At most 24 rows: the
        liveness reading and the inputs some item requires come first; auxiliary readings fill what is left."""
        names = [k for k in self.ages if _known_name(k)]
        primary = [k for k in names if k not in _AUX_ONLY]
        aux = [k for k in names if k in _AUX_ONLY]
        chosen = sorted(primary)[:_MAX_ROWS]
        chosen = sorted(chosen + sorted(aux)[:max(0, _MAX_ROWS - len(chosen))])
        out = []
        for k in chosen:
            s = self.ages[k]
            status = FRESH if s.fresh else (MISSING if s.value is None and s.age_s is None else
                                            (STALE if s.age_s is not None and s.limit_s is not None else UNKNOWN))
            age = s.age_s if finite_number(s.age_s) and s.age_s >= 0 else None
            lim = s.limit_s if finite_number(s.limit_s) and s.limit_s >= 0 else None
            out.append({"name": k, "age_s": None if age is None else round(float(age), 1), "limit_s": lim, "status": status})
        return tuple(out)

    def insufficient_items(self) -> frozenset[str]:
        """Items a finding marks INSUFFICIENT_DATA (INSUFFICIENT_DATA_CODES) and that no other BLOCK names. Such an item is
        also in blocked_items (fail closed: a cycle that does not read this channel withholds it as BLOCKED); a cycle that
        does may show it as INSUFFICIENT_DATA instead. Either way it carries no number. Empty when data quality is BLOCKED."""
        if self.data_quality == DataQuality.BLOCKED:
            return frozenset()
        marked = {f.subject for f in self.findings if f.code in INSUFFICIENT_DATA_CODES and f.subject in ITEMS
                  and dict(f.evidence).get("item_status") == "INSUFFICIENT_DATA"}
        other = {f.subject for f in self.findings if f.severity == BLOCK and f.code not in INSUFFICIENT_DATA_CODES}
        return frozenset(marked - other)


_MAX_ROWS = 24
_AUX_ONLY = frozenset({"battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events", "supervision.heartbeat_age_s",
                       "protection.shutdown_soc_pct", "controller.telemetry", "canonical.telemetry", *_TOU_AUX})


def _known_name(name: object) -> bool:
    """A name an input-age row may carry (the envelope refuses any other): a reading key or an ecco_core.state signal."""
    return isinstance(name, str) and (name in SITE_READING_KEYS or spec_for(name) is not None)


# ---------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------

def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.tzinfo.utcoffset(x) is not None


def _age(now: datetime, t: object) -> float | None:
    """Seconds from t to now; None when t is unknown or lies in the future (an age that cannot be trusted)."""
    if not _aware(t):
        return None
    a = (now - t).total_seconds()
    return a if a >= 0.0 else None


def _future(now: datetime, t: object) -> bool:
    return _aware(t) and (now - t).total_seconds() < 0.0


def _blocked_all(code: str, text: str, **ev: object) -> QualityResult:
    return QualityResult((finding(code, BLOCK, "inputs", text, **ev),), frozenset(ITEMS), DataQuality.BLOCKED,
                         MappingProxyType({}))


def _value_ok(key: str, v: object) -> bool:
    """A reading's value has the type its unit needs and lies in the plausible range (PROPOSED bounds; DATA_QUALITY_METHOD
    section 11). The raw SOC's range is judged by the SOC rule (SOC_OUT_OF_RANGE BLOCKs every SOC item)."""
    unit = SITE_READING_KEYS.get(key)
    if unit == "datetime":
        return _aware(v)
    if key == "tou.overlay_state":
        return isinstance(v, str) and v in TOU_OVERLAY_STATES       # exactly NONE or ACTIVE (contract 13.1)
    if unit == "enum":
        return isinstance(v, str) and bool(v.strip())
    if unit == "bool":
        return isinstance(v, bool)
    if unit == "table":
        return isinstance(v, (list, tuple)) and not (key in _PRESENCE_TABLES and len(v) == 0)
    if not finite_number(v):
        return False
    x = float(v)
    if unit == "%":
        return key == "battery.soc_raw_pct" or 0.0 <= x <= 100.0
    if unit == "W":
        return 0.0 < x <= DQ_PROPOSED.power_max_w if key == "limits.max_grid_charge_w" else 0.0 <= x <= DQ_PROPOSED.power_max_w
    if unit == "kWh":
        lo, hi = PROPOSED.capacity_plausible_kwh
        return lo <= x <= hi if key == "capacity.helper_kwh" else 0.0 <= x <= hi
    if unit == "Wh/%":
        lo, hi = PROPOSED.capacity_plausible_kwh
        return lo <= x * 100.0 / 1000.0 <= hi
    if unit == "Ah":
        return 0.0 < x <= DQ_PROPOSED.capacity_ah_max
    if key == "supervision.heartbeat_age_s":
        return x >= 0.0
    return True


def _readings_by_key(readings: Iterable[object]) -> tuple[dict[str, SiteReading], list[Finding]]:
    out: dict[str, SiteReading] = {}
    notes: list[Finding] = []
    dup: set[str] = set()
    for r in readings:
        if not isinstance(r, SiteReading) or not isinstance(r.key, str):
            notes.append(finding("SITE_READING_MALFORMED", WARN, "site_readings", "an entry is not a SiteReading; ignored"))
            continue
        if r.key in out:
            dup.add(r.key)
        out[r.key] = r
    for k in sorted(dup):
        out.pop(k, None)
        notes.append(finding("SITE_READING_DUPLICATE", BLOCK, k, "two readings for one key: neither is used"))
    return out, notes


@dataclass
class _Ctx:
    """The working state of one assessment (internal)."""
    now: datetime
    findings: list
    blocked: set
    ages: dict
    reasons: dict
    global_block: bool = False

    def block(self, items: Iterable[str], code: str, text: str, **ev: object) -> None:
        for item in items:
            self.findings.append(finding(code, BLOCK, item, text, **ev))
            self.blocked.add(item)

    def note(self, severity: str, subject: str, code: str, text: str, **ev: object) -> None:
        self.findings.append(finding(code, severity, subject, text, **ev))

    def block_all(self, code: str, text: str, subject: str = "inputs", **ev: object) -> None:
        self.findings.append(finding(code, BLOCK, subject, text, **ev))
        self.global_block = True


_REASON_TEXT = {
    "missing": "is missing",
    "invalid": "is malformed or not a usable value",
    "future": "has an observation time in the future",
    "age_unknown": "has an unknown observation time",
    "limit_unresolved": "has no defined freshness limit (UNRESOLVED)",
    "liveness": "is dongle-sourced and the dongle liveness reading is missing or stale",
    "config_liveness": "is published by the configuration poll and the configuration-poll liveness reading is missing or "
                       "stale",
    "stale": "is older than its freshness limit",
    "empty": "is an empty table",
    "caller_withheld": "was judged not fresh by the caller",
}


# ---------------------------------------------------------------------------------------------------------------------
# judging one input
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Liveness:
    at: datetime | None
    age: float | None
    fresh: bool
    code: str | None = None                      # the configuration-poll liveness: the code its items BLOCK with
    reason: str | None = None                    # missing / invalid / future / stale when not fresh


def _liveness_time(now: datetime, r: SiteReading | None) -> tuple[datetime | None, str | None]:
    """(the change time, None) of a liveness reading, or (None, why: missing / invalid / future). The value is the poll
    text's change time; the older of it and its observation time counts (conservative)."""
    if r is None:
        return None, "missing"
    if r.problems() or not _aware(r.value) or not _aware(r.observed_at):
        return None, "invalid"
    if _future(now, r.value) or _future(now, r.observed_at):
        return None, "future"
    return min(r.value, r.observed_at), None


def _judge_liveness(c: _Ctx, r: SiteReading | None) -> _Liveness:
    bound = DQ_PROPOSED.liveness_max_age_s
    at, reason = _liveness_time(c.now, r)
    if at is None:
        c.ages[LIVENESS_KEY] = InputState(LIVENESS_KEY, None, False, None, bound)
        code = "LIVENESS_IN_FUTURE" if reason == "future" else "LIVENESS_MISSING"
        c.note(BLOCK, LIVENESS_KEY, code, "no valid dongle liveness reading: no dongle-sourced input can be shown fresh",
               reason=reason)
        return _Liveness(None, None, False)
    age = (c.now - at).total_seconds()
    fresh = age <= bound
    c.ages[LIVENESS_KEY] = InputState(LIVENESS_KEY, at.isoformat(), fresh, age, bound)
    if not fresh:
        c.note(BLOCK, LIVENESS_KEY, "LIVENESS_STALE", "the dongle poll text has not changed within the PROPOSED liveness "
               "bound: every dongle-sourced input is stale", age_s=round(age, 1), bound_s=bound)
    return _Liveness(at, age, fresh)


def _judge_config_liveness(c: _Ctx, r: SiteReading | None) -> _Liveness:
    """The configuration-poll liveness reading (contract 13.3): the time the dongle's configuration-poll text last
    changed, judged against its fixed PROPOSED bound (never an I-D6 key). It is recorded in `ages`; the items requiring it
    BLOCK with the returned code (CONFIG_LIVENESS_MISSING / _IN_FUTURE / _STALE) in assess_inputs."""
    bound = DQ_PROPOSED.config_liveness_max_age_s
    at, reason = _liveness_time(c.now, r)
    if at is None:
        c.ages[CONFIG_LIVENESS_KEY] = InputState(CONFIG_LIVENESS_KEY, None, False, None, bound)
        code = "CONFIG_LIVENESS_IN_FUTURE" if reason == "future" else "CONFIG_LIVENESS_MISSING"
        return _Liveness(None, None, False, code, reason)
    age = (c.now - at).total_seconds()
    fresh = age <= bound
    c.ages[CONFIG_LIVENESS_KEY] = InputState(CONFIG_LIVENESS_KEY, at.isoformat(), fresh, age, bound)
    return _Liveness(at, age, fresh, None if fresh else "CONFIG_LIVENESS_STALE", None if fresh else "stale")


_CONFIG_LIVENESS_TEXT = {
    "CONFIG_LIVENESS_MISSING": "no valid configuration-poll liveness reading: the TOU table and the other readings of the "
                               "dongle's configuration poll cannot be shown fresh",
    "CONFIG_LIVENESS_IN_FUTURE": "the configuration-poll liveness time lies in the future: the TOU table and the other "
                                 "readings of the dongle's configuration poll cannot be shown fresh",
    "CONFIG_LIVENESS_STALE": "the configuration-poll text has not changed within the PROPOSED bound: the TOU table and the "
                             "other readings of the dongle's configuration poll are stale",
}


def _judge_signal(c: _Ctx, snap: Snapshot | None, sig: str, lim: float | None, live: _Liveness) -> None:
    st, reason = _signal_state(c.now, snap, sig, lim, live)
    c.ages[sig] = st
    if reason is not None:
        c.reasons[sig] = reason


def _signal_state(now: datetime, snap: Snapshot | None, sig: str, lim: float | None,
                  live: _Liveness) -> tuple[InputState, str | None]:
    """One snapshot signal judged: (state, reason it is not fresh or None)."""
    obs = None
    if snap is not None:
        try:
            obs = snap.get(sig)
        except Exception:  # noqa: BLE001 - a malformed snapshot is a missing input
            obs = None
    value = getattr(obs, "value", None)
    if obs is None or value is None:
        return InputState(sig, None, False, None, lim), "missing"
    if not _signal_value_ok(sig, value):
        return InputState(sig, None, False, None, lim), "invalid"
    t = getattr(obs, "observed_at", None)
    own_age = _age(now, t)
    as_of = getattr(snap, "as_of", None)
    snap_age = _age(now, as_of)                  # a value is never younger than the snapshot that carries it
    if own_age is None or snap_age is None:
        age = None
    elif sig in DONGLE_SIGNALS:
        age = None if live.age is None else max(live.age, snap_age)
    else:
        age = max(own_age, snap_age)
    fresh = age is not None and lim is not None and age <= lim and (live.fresh or sig not in DONGLE_SIGNALS)
    if fresh:
        return InputState(sig, value, True, age, lim), None
    reason = ("future" if _future(now, t) or _future(now, as_of) else "age_unknown" if own_age is None or snap_age is None
              else "limit_unresolved" if lim is None else "liveness" if sig in DONGLE_SIGNALS and not live.fresh else "stale")
    return InputState(sig, value, False, age, lim), reason


def _signal_value_ok(sig: str, value: object) -> bool:
    """A snapshot value of the type its signal needs: inverter health a bool, the reserve helper a percentage, every other
    judged signal a finite number (ecco_core.state already refuses strings for signals with a unit)."""
    if sig == "inverter.healthy":
        return isinstance(value, bool)
    if sig == "history.hourly":
        return True                              # a marker observation; the History itself is judged
    if not finite_number(value):
        return False
    return sig != "reserve.ha_minimum_soc" or 0.0 <= float(value) <= 100.0


def _judge_reading(c: _Ctx, tz, by_key: Mapping[str, SiteReading], key: str, limits: Mapping, live: _Liveness,
                   cfg: _Liveness) -> None:
    lim = limits.get(key)                       # strict: a key without a limit is UNRESOLVED (QUALIFYING_READING_KEYS too)
    r = by_key.get(key)
    if r is None:
        c.ages[key] = InputState(key, None, False, None, lim)
        c.reasons[key] = "missing"
        return
    probs = r.problems()
    if probs or not _value_ok(key, r.value):
        c.ages[key] = InputState(key, None, False, None, lim)
        empty = not probs and isinstance(r.value, (list, tuple)) and len(r.value) == 0
        c.reasons[key] = "empty" if empty else "invalid"
        if not empty:
            c.note(WARN, key, "READING_INVALID", "a reading is malformed (key, unit, time, source or value) and is not used",
                   problems=tuple(probs) or ("value",))
        return
    if _future(c.now, r.observed_at):
        c.ages[key] = InputState(key, r.value, False, None, lim)
        c.reasons[key] = "future"
        c.note(WARN, key, "READING_IN_FUTURE", "a reading's observation time lies in the future; it is not fresh")
        return
    if key in DATE_SCOPED_READINGS:
        obs_age = _age(c.now, r.observed_at)
        same_day = obs_age is not None and local_date(r.observed_at, tz) == local_date(c.now, tz)
        day_limit = (c.now - local_wall(local_date(c.now, tz), 0, tz)).total_seconds()
        c.ages[key] = InputState(key, r.value, bool(same_day), obs_age, max(0.0, day_limit))
        if not same_day:
            c.reasons[key] = "stale"
        return
    own_age = _age(c.now, r.observed_at)
    config = key in CONFIG_POLL_READINGS
    dongle = config or key in DONGLE_READINGS
    if config:
        # published by the configuration poll: aged by the larger of the two liveness ages, fresh only while both
        # liveness readings are within their bounds (contract 13.3; tighten-only against the telemetry rule)
        age = (max(live.age, cfg.age) if own_age is not None and live.age is not None and cfg.age is not None
               else None)
        fresh = live.fresh and cfg.fresh and age is not None and lim is not None and age <= lim
    elif dongle:
        age = live.age if own_age is not None else None
        fresh = live.fresh and age is not None and lim is not None and age <= lim
    else:
        age = own_age
        fresh = age is not None and lim is not None and age <= lim
    c.ages[key] = InputState(key, r.value, fresh, age, lim)
    if not fresh:
        c.reasons[key] = ("age_unknown" if own_age is None else "limit_unresolved" if lim is None else
                          "liveness" if dongle and not live.fresh else
                          "config_liveness" if config and not cfg.fresh else "stale")


def _history_state(history: object, now: datetime, limit: float | None) -> InputState:
    """The history's age: from the end of its newest WELL-FORMED hour record that carries at least one finite energy (a
    junk entry, a record filed under another hour or an empty record proves nothing about how recent the history is)."""
    if not isinstance(history, History) or len(history) == 0:
        return InputState("history.hourly", None, False, None, limit)
    starts = [s for s, r in _records(history).items() if any(finite_number(v) for v in r.e.values())]
    if not starts:
        return InputState("history.hourly", None, False, None, limit)
    newest_end = max(starts) + HOUR
    age = (now - datetime.fromtimestamp(newest_end, UTC)).total_seconds()
    if age < 0:
        return InputState("history.hourly", True, False, None, limit)       # an hour from the future: not trusted
    return InputState("history.hourly", True, limit is not None and age <= limit, age, limit)


def _fresh(c: _Ctx, key: str) -> bool:
    s = c.ages.get(key)
    return isinstance(s, InputState) and s.fresh


def _num(c: _Ctx, key: str, fresh_only: bool = True) -> float | None:
    s = c.ages.get(key)
    if not isinstance(s, InputState) or (fresh_only and not s.fresh) or not finite_number(s.value):
        return None
    return float(s.value)


# ---------------------------------------------------------------------------------------------------------------------
# assess_inputs
# ---------------------------------------------------------------------------------------------------------------------

def assess_inputs(inputs: CycleInputs) -> QualityResult:
    """Re-verify every input the cycle could use (see the module docstring). Never raises for malformed contents of a
    CycleInputs; a malformed `now`, time zone or caller assessment blocks everything."""
    try:
        return _assess(inputs)
    except Exception as exc:  # noqa: BLE001 - fail closed: an internal error withholds everything, never raises
        return _blocked_all("QUALITY_INTERNAL_ERROR", "the quality layer could not assess the inputs; every item is withheld",
                            error=type(exc).__name__)


def _assess(inputs: CycleInputs) -> QualityResult:
    now = getattr(inputs, "now", None)
    if not _aware(now):
        return _blocked_all("NOW_INVALID", "the cycle time is not an aware datetime")
    c = _Ctx(now, [], set(), {}, {})
    raw_decisions = getattr(inputs, "decisions", None)
    decisions = raw_decisions if isinstance(raw_decisions, DecisionSet) else DecisionSet()
    if not isinstance(raw_decisions, DecisionSet):
        c.note(BLOCK, "decisions", "DECISIONS_MALFORMED", "the decisions are not a DecisionSet: every decision counts as OPEN")
    raw_acc = getattr(inputs, "accept_provenance", None)
    accept = raw_acc if isinstance(raw_acc, frozenset) else DEFAULT_ACCEPT_PROVENANCE
    tz_name = getattr(getattr(inputs, "site_facts", None), "tz", "Europe/London")
    if not isinstance(tz_name, str) or not tz_name:
        return _blocked_all("TZ_INVALID", "the site time zone is not a known zone")
    try:
        tz = zone(tz_name)
    except Exception:  # noqa: BLE001 - an unknown zone name is a quality failure, never a crash
        return _blocked_all("TZ_INVALID", "the site time zone is not a known zone")
    limits, notes = freshness_limits(decisions, accept)
    c.findings += notes

    readings = getattr(inputs, "site_readings", ())
    if isinstance(readings, list):
        readings = tuple(readings)
    if not isinstance(readings, tuple):
        c.note(BLOCK, "site_readings", "SITE_READINGS_MALFORMED", "the site readings are not a sequence: none is used")
        readings = ()
    by_key, rnotes = _readings_by_key(readings)
    c.findings += rnotes

    raw_snap = getattr(inputs, "snapshot", None)
    snap = raw_snap if isinstance(raw_snap, Snapshot) else None
    if raw_snap is not None and snap is None:
        c.note(BLOCK, "snapshot", "SNAPSHOT_MALFORMED", "the snapshot is not an ecco_core Snapshot: no signal is used")
    if snap is not None and _future(now, snap.as_of):
        c.block_all("SNAPSHOT_IN_FUTURE", "the snapshot is dated after the cycle time", subject="snapshot")

    live = _judge_liveness(c, by_key.get(LIVENESS_KEY))
    cfg = _judge_config_liveness(c, by_key.get(CONFIG_LIVENESS_KEY))

    # what every item needs
    per_item = {}
    needed_signals: set[str] = set()
    needed_readings: set[str] = set()
    for item in ITEMS:
        ri = required_inputs(item, decisions, accept)
        per_item[item] = ri
        needed_signals |= set(ri.signals)
        needed_readings |= set(ri.readings) | set(ri.charge_window_sources)
    needed_readings |= set(CAPACITY_READING_BY_KIND.values()) | set(_AUX_READINGS)

    history = getattr(inputs, "history", None)
    for sig in sorted(needed_signals):
        if sig == "history.hourly":
            st = _history_state(history, now, limits.get(sig))
            c.ages[sig] = st
            if not st.fresh:
                c.reasons[sig] = ("missing" if st.value is None else "future" if st.age_s is None else "stale")
            continue
        _judge_signal(c, snap, sig, limits.get(sig), live)
    for key in sorted(needed_readings - set(LIVENESS_KEYS)):
        _judge_reading(c, tz, by_key, key, limits, live, cfg)
    _pv_forecast_plausibility(c, getattr(getattr(inputs, "site_facts", None), "pv_array_kwp", None))

    _caller_assessments(c, inputs, snap, limits, live)

    # the items that rest on a snapshot signal (anything but the history)
    snap_items = [i for i, ri in per_item.items() if any(s != "history.hourly" for s in ri.signals)]
    snap_age = _age(now, snap.as_of) if snap is not None else None
    if snap_age is not None and snap_age > DQ_PROPOSED.snapshot_max_age_s:
        c.block(snap_items, "SNAPSHOT_STALE", "the snapshot was taken well before the cycle time: no item resting on it is "
                "shown", age_s=round(snap_age, 1), bound_s=DQ_PROPOSED.snapshot_max_age_s)

    # required inputs per item
    for item, ri in per_item.items():
        for k in ri.signals + ri.readings:
            if k == LIVENESS_KEY:
                if not live.fresh:
                    c.block([item], "INPUT_NOT_FRESH", "the dongle liveness reading is missing, invalid or stale", input=k,
                            reason="stale" if live.at else "missing")
                continue
            if k == CONFIG_LIVENESS_KEY:
                if not cfg.fresh:
                    ev = ({"age_s": round(cfg.age, 1), "bound_s": DQ_PROPOSED.config_liveness_max_age_s}
                          if cfg.age is not None else {"reason": cfg.reason})
                    c.block([item], cfg.code or "CONFIG_LIVENESS_MISSING",
                            _CONFIG_LIVENESS_TEXT.get(cfg.code or "CONFIG_LIVENESS_MISSING", ""), **ev)
                continue
            if not _fresh(c, k):
                reason = c.reasons.get(k, "missing")
                c.block([item], "INPUT_NOT_FRESH", f"{k} {_REASON_TEXT.get(reason, 'is not fresh')}", input=k, reason=reason)
        for fact in ri.site_facts:
            v = getattr(getattr(inputs, "site_facts", None), fact, None)
            if not (finite_number(v) and v > 0):
                c.block([item], "SITE_FACT_MISSING", f"the site fact {fact} is not known", fact=fact)

    _charge_window_rules(c, per_item)
    _soc_rules(c)
    _online_flag_rules(c, snap, live)
    _power_rules(c)
    _live_inputs_rules(c, getattr(inputs, "live", None), snap, snap_items)
    _supervision_rules(c, by_key, live)
    _tariff_rules(c)
    _capacity_rules(c, decisions, accept)
    _protection_rules(c, decisions, accept)
    for f in history_findings(history, now, tz, getattr(inputs, "pv_forecast_history", None)):
        if f.severity == BLOCK and f.subject in ITEMS:
            c.blocked.add(f.subject)
        c.findings.append(f)

    if c.global_block:
        dq = DataQuality.BLOCKED
        c.blocked |= set(ITEMS)
    elif c.blocked or any(f.severity in (BLOCK, WARN) for f in c.findings):
        dq = DataQuality.DEGRADED
    else:
        dq = DataQuality.OK
    return QualityResult(tuple(c.findings), frozenset(c.blocked), dq, MappingProxyType(dict(sorted(c.ages.items()))))


def _caller_assessments(c: _Ctx, inputs: CycleInputs, snap: Snapshot | None, limits: Mapping, live: _Liveness) -> None:
    """The caller's own assessments must never be fresher than ours, nor contradict themselves."""
    assessments = getattr(inputs, "caller_assessments", ())
    if isinstance(assessments, list):
        assessments = tuple(assessments)
    if not isinstance(assessments, tuple):
        c.block_all("CALLER_ASSESSMENT_MALFORMED", "the caller assessments are not a sequence of (signal, fresh, age_s)",
                    subject="caller_assessments")
        return
    seen: dict[str, set] = {}
    for a in assessments:
        if not (isinstance(a, tuple) and len(a) == 3 and isinstance(a[0], str) and isinstance(a[1], bool)):
            c.block_all("CALLER_ASSESSMENT_MALFORMED", "a caller assessment is not (signal, fresh, age_s)",
                        subject="caller_assessments")
            continue
        sig, caller_fresh, caller_age = a
        seen.setdefault(sig, set()).add(caller_fresh)
        if caller_fresh and not (finite_number(caller_age) and caller_age >= 0):
            c.block_all("CALLER_ASSESSMENT_INCONSISTENT", "the caller judged an input fresh without a usable age",
                        subject=sig)
        mine = c.ages.get(sig)
        if mine is None:
            if sig == "history.hourly":
                mine = _history_state(getattr(inputs, "history", None), c.now, limits.get(sig))
            else:
                mine = _signal_state(c.now, snap, sig, limits.get(sig), live)[0]
        if caller_fresh and not mine.fresh:
            c.block_all("CALLER_FRESHNESS_DISAGREES", "the caller judged this input fresh; re-verified from its observation "
                        "and liveness times it is not", subject=sig, recomputed_age_s=mine.age_s, limit_s=mine.limit_s)
        elif not caller_fresh and mine.fresh:
            if sig in DONGLE_SIGNALS:
                # by design: the caller ages a dongle value from its last change, quality from the poll-text liveness
                c.note(INFO, sig, "CALLER_JUDGED_NOT_FRESH", "the caller judged this dongle-sourced input not fresh from "
                       "its last change; the poll-text liveness shows it current")
            elif sig in c.ages:
                c.ages[sig] = InputState(sig, mine.value, False, mine.age_s, mine.limit_s)
                c.reasons[sig] = "caller_withheld"
                c.note(WARN, sig, "CALLER_JUDGED_NOT_FRESH", "the caller judged this input not fresh: it is not used, and "
                       "every item requiring it is withheld")
    for sig, vals in sorted(seen.items()):
        if len(vals) > 1:
            c.block_all("CALLER_ASSESSMENT_CONFLICT", "the caller assessed one input both fresh and not fresh", subject=sig)


# ---------------------------------------------------------------------------------------------------------------------
# content rules
# ---------------------------------------------------------------------------------------------------------------------

def _charge_window_rules(c: _Ctx, per_item: Mapping) -> None:
    """The charge window: the read-only TOU slot table's grid-charge run, which a VERIFIED tariff (judged by the planning
    layer) only cross-checks (a tariff alone is never a window; contract 13.5, A30), else BLOCK. The TOU slot times run on
    the inverter's clock, so the window needs a fresh clock offset within the PROPOSED block bound. This layer does not
    judge the tariff, so it fails closed: every charge-window item needs a fresh TOU slot table and a known, small clock
    offset, also when a verified tariff checks the window (the change requests that would let a tariff stand alone,
    CCR-DQ-2 / CCR-PLAN-2, are deferred). The texts say so, and stay value-free."""
    items = [i for i, ri in per_item.items() if ri.charge_window_sources]
    offset = _num(c, "inverter.clock_offset_s")
    raw_offset = _num(c, "inverter.clock_offset_s", fresh_only=False)
    if raw_offset is not None and abs(raw_offset) > DQ_PROPOSED.clock_offset_warn_s:
        c.note(WARN, "inverter.clock_offset_s", "INVERTER_CLOCK_OFFSET", "the inverter clock is off by more than the "
               "PROPOSED warning bound", offset_s=raw_offset, warn_s=DQ_PROPOSED.clock_offset_warn_s)
    if not items:
        return
    if not _fresh(c, "tou.slot_table"):
        c.block(items, "CHARGE_WINDOW_UNKNOWN", "no fresh TOU slot table: a charge-window item needs one, also when a "
                "verified tariff checks the window")
        return
    if offset is None:
        c.block(items, "CHARGE_WINDOW_CLOCK_UNKNOWN", "the inverter clock offset is missing or not fresh: a charge-window item "
                "needs a known offset, also when a verified tariff checks the window")
        return
    if abs(offset) > DQ_PROPOSED.clock_offset_block_s:
        c.block(items, "CHARGE_WINDOW_CLOCK_OFFSET", "the inverter clock is off by more than the PROPOSED block bound: a "
                "charge-window item needs a small offset, also when a verified tariff checks the window",
                offset_s=offset, block_s=DQ_PROPOSED.clock_offset_block_s)
        return
    for item in items:
        c.note(WARN, item, "CHARGE_WINDOW_FROM_TOU_TABLE",
               "the charge window comes from the read-only TOU slot table; a verified tariff only cross-checks it")


def _soc_rules(c: _Ctx) -> None:
    canon = c.ages.get("battery.soc")
    if not isinstance(canon, InputState) or not finite_number(canon.value):
        return
    v = float(canon.value)
    raw = _num(c, "battery.soc_raw_pct")
    if not 0.0 <= v <= 100.0:
        c.block(SOC_ITEMS, "SOC_OUT_OF_RANGE", "the SOC reading is not a percentage", value=v)
        c.ages["battery.soc"] = InputState("battery.soc", None, False, canon.age_s, canon.limit_s)
        return
    if raw is not None and not 0.0 <= raw <= 100.0:
        c.block(SOC_ITEMS, "SOC_OUT_OF_RANGE", "the raw SOC reading is not a percentage", value=raw)
        return
    if v <= DQ_PROPOSED.soc_zero_max_pct:
        if raw is not None and raw > DQ_PROPOSED.soc_zero_max_pct:
            c.ages["battery.soc"] = InputState("battery.soc", raw, canon.fresh and _fresh(c, "battery.soc_raw_pct"),
                                               c.ages["battery.soc_raw_pct"].age_s, canon.limit_s)
            c.note(WARN, "battery.soc", "SOC_FALSE_ZERO_RAW_USED", "the canonical SOC reads zero while the raw SOC does not: "
                   "the raw reading is used", canonical=v, raw=raw)
            return
        if raw is None:
            c.block(SOC_ITEMS, "SOC_FALSE_ZERO_UNRESOLVED", "the canonical SOC reads zero and no fresh raw SOC can confirm "
                    "or correct it", canonical=v)
            return
        bp = _num(c, "battery.power")
        if bp is not None and bp > DQ_PROPOSED.soc_zero_discharge_w:
            c.block(SOC_ITEMS, "SOC_ZERO_WHILE_DISCHARGING", "the SOC reads zero while the battery is discharging", power_w=bp)
        return
    if raw is not None and abs(v - raw) > PROPOSED.soc_agree_points:
        c.block(SOC_ITEMS, "SOC_SOURCES_DISAGREE", "the canonical and the raw SOC disagree beyond the PROPOSED tolerance",
                canonical=v, raw=raw, tolerance_points=PROPOSED.soc_agree_points)


def _online_flag_rules(c: _Ctx, snap: Snapshot | None, live: _Liveness) -> None:
    """An online flag holds its last state and has no timeout: while the poll-text liveness is not fresh it proves nothing."""
    healthy = None
    if snap is not None:
        o = snap.get("inverter.healthy")
        healthy = None if o is None else o.value
    if not live.fresh:
        if healthy is True:
            c.block(HEALTH_ITEMS, "ONLINE_FLAG_UNCONFIRMED", "the inverter reads healthy, but the dongle liveness is not fresh: "
                    "a flag without a timeout is treated as stale")
        for flag in ONLINE_FLAGS:
            o = None if snap is None else snap.get(flag)
            if o is not None and o.value is True:
                c.note(WARN, flag, "ONLINE_FLAG_UNCONFIRMED", "an online flag reads on while the dongle liveness is not fresh: "
                       "it is treated as stale")
                c.ages[flag] = InputState(flag, True, False, live.age, None)
    elif healthy is False and _fresh(c, "inverter.healthy"):
        c.block(HEALTH_ITEMS, "INVERTER_NOT_HEALTHY", "the inverter does not report normal operation")


def _power_rules(c: _Ctx) -> None:
    """The live power balance: house = PV + battery (positive = discharging) + grid (positive = importing)."""
    vals = {k: _num(c, k, fresh_only=False) for k in ("house.power", "pv.power", "battery.power", "grid.power")}
    h, p, b, g = vals["house.power"], vals["pv.power"], vals["battery.power"], vals["grid.power"]
    if h is not None and h < -DQ_PROPOSED.load_zero_max_w:
        c.block(POWER_ITEMS, "HOUSE_POWER_NEGATIVE", "the house load reads negative, which is not credible", house_w=h)
        return
    if None in (h, p, b, g):
        return
    flow = p + b + g
    if abs(h) <= DQ_PROPOSED.load_zero_max_w and flow > DQ_PROPOSED.load_false_zero_flow_w:
        c.block(POWER_ITEMS, "LOAD_FALSE_ZERO", "the house load reads zero while inverter and grid show a load (the native "
                "load false zero; HD1)", flow_w=round(flow, 1))
        return
    tol = max(PROPOSED.power_agree_w, PROPOSED.power_agree_fraction * max(abs(h), abs(p), abs(b), abs(g)))
    resid = h - flow
    if abs(resid) <= tol:
        return
    if abs(h - (p + b - g)) <= tol and abs(g) > tol / 2.0:
        c.block(POWER_ITEMS, "CT_SIGN_REVERSED", "the power balance fits only with the grid CT sign reversed",
                residual_w=round(resid, 1), tolerance_w=round(tol, 1))
    elif abs(h - (p - b + g)) <= tol and abs(b) > tol / 2.0:
        c.block(POWER_ITEMS, "BATTERY_SIGN_REVERSED", "the power balance fits only with the battery power sign reversed",
                residual_w=round(resid, 1), tolerance_w=round(tol, 1))
    else:
        c.block(POWER_ITEMS, "POWER_BALANCE_INCONSISTENT", "house, PV, battery and grid power do not balance",
                residual_w=round(resid, 1), tolerance_w=round(tol, 1))


LIVE_PAIRS = (("soc_pct", "battery.soc"), ("load_w", "house.power"), ("pv_w", "pv.power"), ("inverter_ok", "inverter.healthy"),
              ("ha_reserve_pct", "reserve.ha_minimum_soc"))


def _live_inputs_rules(c: _Ctx, live_inputs: object, snap: Snapshot | None, snap_items: list[str]) -> None:
    """The bridge's LiveInputs must be built from this snapshot: the same time and the same values (a value the bridge
    withheld, None, is fine; a different one is not). A disagreement on any signal shows the two do not describe the same
    moment, so neither side is trusted: every item that rests on a snapshot signal BLOCKs, whichever signal differs (the
    reserve helper included). A malformed LiveInputs BLOCKs the same items."""
    if live_inputs is None:
        return
    if not isinstance(live_inputs, LiveInputs):
        c.block(snap_items, "LIVE_INPUTS_MALFORMED", "the live inputs are not the bridge's LiveInputs: no item resting on the "
                "snapshot is shown")
        return
    differ = []
    for attr, sig in LIVE_PAIRS:
        lv = getattr(live_inputs, attr, None)
        sv = None if snap is None else snap.value(sig)
        if lv is None:
            continue
        if isinstance(lv, bool) or isinstance(sv, bool):
            same = lv is sv
        elif finite_number(lv) or finite_number(sv):
            same = finite_number(lv) and finite_number(sv) and abs(float(lv) - float(sv)) <= 1e-9
        else:
            same = lv == sv                      # e.g. the same unusable state text on both sides (judged elsewhere)
        if not same:
            differ.append(sig)
    lnow = getattr(live_inputs, "now", None)
    if snap is not None and _aware(lnow) and lnow != snap.as_of:
        differ.append("snapshot.as_of")
    if differ:
        c.block(snap_items, "LIVE_INPUTS_DISAGREE", "the live inputs and the snapshot disagree, so they do not describe the "
                "same moment: no item resting on the snapshot is shown", signals=tuple(differ))


def _supervision_rules(c: _Ctx, by_key: Mapping[str, SiteReading], live: _Liveness) -> None:
    """Stable supervision: state SUPERVISED and stable true, each current within the PROPOSED bound, and a heartbeat whose
    reported age plus the reading's own age stays within it. Otherwise export and Dump advice BLOCK and every other item
    gets a WARN.

    The state and the stable flag are dongle readings published only when they change (site_decisions.DONGLE_READINGS),
    so their age is the telemetry liveness age, never their own last change: steady supervision is current while the poll
    text keeps moving, and a poll text frozen beyond the bound (or a missing liveness reading) makes them old. This is a
    loosening against the reading's own observation time, bounded by the heartbeat rule, which keeps the heartbeat
    reading's own observation time (it is re-published every 20 s)."""
    why = []
    vals = {}
    for k in SUPERVISION_KEYS:
        r = by_key.get(k)
        if r is None:
            why.append(f"{k}:missing")
        elif r.problems() or not _value_ok(k, r.value):
            why.append(f"{k}:invalid")
        elif _future(c.now, r.observed_at):
            why.append(f"{k}:future")
        else:
            vals[k] = r
    eff = None
    hb = vals.get("supervision.heartbeat_age_s")
    if hb is not None:
        reading_age = _age(c.now, hb.observed_at)
        eff = None if reading_age is None or hb.value < 0 else float(hb.value) + reading_age
        c.ages["supervision.heartbeat_age_s"] = InputState("supervision.heartbeat_age_s", hb.value, eff is not None and
                                                           eff <= DQ_PROPOSED.supervision_max_heartbeat_age_s, eff,
                                                           DQ_PROPOSED.supervision_max_heartbeat_age_s)
        if eff is None or eff > DQ_PROPOSED.supervision_max_heartbeat_age_s:
            why.append("supervision.heartbeat_age_s:old")
    for k in ("supervision.state", "supervision.stable"):
        if k in vals:
            own = _age(c.now, vals[k].observed_at)
            a = live.age if own is not None and live.at is not None else None
            if a is None or a > DQ_PROPOSED.supervision_reading_max_age_s:
                why.append(f"{k}:old")
    if "supervision.state" in vals and vals["supervision.state"].value != SUPERVISED:
        why.append("supervision.state:not_supervised")
    if "supervision.stable" in vals and vals["supervision.stable"].value is not True:
        why.append("supervision.stable:false")
    if not why:
        return
    c.block(EXPORT_ITEMS, "SUPERVISION_NOT_STABLE", "supervision is not stable (SUPERVISED, stable, recent heartbeat): "
            "export and Dump advice are withheld", why=tuple(why))
    c.note(WARN, "supervision.state", "SUPERVISION_NOT_STABLE", "supervision is not stable; advice other than export and "
           "Dump is shown with a warning", why=tuple(why), items=tuple(i for i in ITEMS if i not in EXPORT_ITEMS))


def _tariff_rules(c: _Ctx) -> None:
    """Presence and age only: the content of the rates and events is the planning layer's to judge."""
    if not _fresh(c, "tariff.events"):
        reason = c.reasons.get("tariff.events", "missing")
        c.block(EVENT_ITEMS, "TARIFF_EVENTS_NOT_FRESH", f"tariff.events {_REASON_TEXT.get(reason, 'is not fresh')}",
                reason=reason)
        c.note(WARN, "tariff.events", "TARIFF_EVENTS_NOT_FRESH", "the event table is not fresh; Dump advice is shown with a "
               "warning", reason=reason)
    if _fresh(c, "tariff.import_rates"):
        c.note(INFO, "tariff.import_rates", "TARIFF_IMPORT_RATES_PRESENT", "import rates are present and fresh; whether they "
               "are a VERIFIED tariff is the planning layer's judgement")
    elif c.reasons.get("tariff.import_rates") not in (None, "missing"):
        c.note(WARN, "tariff.import_rates", "TARIFF_IMPORT_RATES_NOT_FRESH", "the import rates are present but not usable",
               reason=c.reasons.get("tariff.import_rates"))


def _pv_forecast_plausibility(c: _Ctx, kwp: object) -> None:
    """A day-ahead PV forecast above the PROPOSED yield per kWp of the array is not physical: it is not used (the items
    requiring it BLOCK INPUT_NOT_FRESH, reason invalid). Without a known array size pv_tomorrow BLOCKs SITE_FACT_MISSING."""
    if not (finite_number(kwp) and kwp > 0):
        return
    for key in DATE_SCOPED_READINGS:
        s = c.ages.get(key)
        if not isinstance(s, InputState) or not finite_number(s.value):
            continue
        if float(s.value) > float(kwp) * DQ_PROPOSED.pv_forecast_max_kwh_per_kwp:
            c.ages[key] = InputState(key, None, False, s.age_s, s.limit_s)
            c.reasons[key] = "invalid"
            c.note(WARN, key, "PV_FORECAST_IMPLAUSIBLE", "the PV forecast is above what the array can produce in a day; it is "
                   "not used", per_kwp_max=DQ_PROPOSED.pv_forecast_max_kwh_per_kwp)


def _capacity_rules(c: _Ctx, decisions: DecisionSet, accept: frozenset) -> None:
    n, mismatch = capacity_sources_context(decisions, c.ages, accept)
    if n < 2 or not decisions.satisfied("D4", accept):
        return                                        # with I-D4 not satisfied the gate itself BLOCKs (DECISION_D4_OPEN)
    band = float(decisions.value("D4").pct)
    if mismatch is None:
        c.block(CONDITIONAL_D4_ITEMS, "CAPACITY_MISMATCH_UNKNOWN", "two or more capacity sources are present and their "
                "agreement cannot be computed", sources=n)
    elif not finite_number(mismatch) or mismatch > band:
        c.block(CONDITIONAL_D4_ITEMS, "CAPACITY_SOURCES_CONFLICT", "the capacity sources disagree beyond the recorded I-D4 "
                "band", sources=n, difference_pct=mismatch, band_pct=band)


def _protection_rules(c: _Ctx, decisions: DecisionSet, accept: frozenset) -> None:
    """SOC near the protection level withholds export and Dump advice. The level is the highest known of: the placeholder
    technical minimum, a fresh protection reading, a satisfied I-D2 owner statement. Unknown -> BLOCK."""
    soc = _num(c, "battery.soc")
    if soc is None:
        return
    levels = [DEFAULT_TECHNICAL_MIN_SOC_PCT]
    known = False
    prot = _num(c, "protection.shutdown_soc_pct")
    if prot is not None and 0.0 <= prot <= 100.0:
        levels.append(prot)
        known = True
    if decisions.satisfied("D2", accept):
        d2 = decisions.value("D2")
        if d2.supplied_by == OWNER_STATEMENT and finite_number(d2.value_pct):
            levels.append(float(d2.value_pct))
            known = True
    if not known:
        c.block(EXPORT_ITEMS, "PROTECTION_LEVEL_UNKNOWN", "the protection level is not known, so the distance of the SOC from "
                "it cannot be checked")
        return
    threshold = max(levels) + DQ_PROPOSED.protection_margin_pct
    if soc <= threshold:
        c.block(EXPORT_ITEMS, "SOC_NEAR_PROTECTION", "the SOC is within the PROPOSED margin of the protection level",
                soc_pct=soc, level_pct=max(levels), margin_pct=DQ_PROPOSED.protection_margin_pct)


# ---------------------------------------------------------------------------------------------------------------------
# history rules (shared by assess_inputs, prepare_history and the capture validator)
# ---------------------------------------------------------------------------------------------------------------------

_FLAG_SETS = (set, frozenset, tuple, list)


def _well_formed(s: object, r: object) -> bool:
    """An int key, an HourRecord whose own start is that key, hour aligned, with dict energies, flags (of collections)
    and sources."""
    return (isinstance(s, int) and not isinstance(s, bool) and isinstance(r, HourRecord) and r.start == s and s % HOUR == 0
            and isinstance(r.e, dict) and isinstance(r.flags, dict) and isinstance(r.sources, dict)
            and all(isinstance(v, _FLAG_SETS) for v in r.flags.values()))


def _records(history: History) -> dict[int, HourRecord]:
    """The well-formed hour records (_well_formed); every other entry is ignored by every rule."""
    return {s: r for s, r in history.by_start.items() if _well_formed(s, r)}


def well_formed_records(history: History) -> dict[int, HourRecord]:
    """The hour records every history rule judges (the well-formed ones), by start. The plan body learns its PV model from
    exactly these; this public name keeps that dependency off the private helpers, so a refactor here cannot silently change
    what the planner learns from (test_intel_quality pins both)."""
    return _records(history)


def _e(rec: HourRecord, fld: str) -> float | None:
    v = rec.e.get(fld) if isinstance(rec.e, dict) else None
    return float(v) if finite_number(v) else None


def dropout_runs(recs: Mapping[int, HourRecord], start: int, end: int) -> list[tuple[int, int]]:
    """(first missing hour, length) of every run of missing or gap-spread hours in [start, end) that ended (a present hour
    follows it inside the window)."""
    runs = []
    run_start = None
    s = start - start % HOUR
    while s < end:
        r = recs.get(s)
        bad = r is None or any(F_GAP_INTERP in fl for fl in (r.flags.values() if isinstance(r.flags, dict) else ()))
        if bad:
            if run_start is None:
                run_start = s
        elif run_start is not None:
            runs.append((run_start, (s - run_start) // HOUR))
            run_start = None
        s += HOUR
    return runs


def stall_hours(recs: Mapping[int, HourRecord]) -> dict[str, list[int]]:
    """{field: hour starts} of counter stalls (energy at zero while the power mean shows real flow) and catch-up jumps
    (energy far above the power integral), for load and PV. A load at zero while exporting is the native-load false zero
    (I-D8 / HD1), judged by prepare_history, not a stall."""
    out: dict[str, list[int]] = {"stall": [], "catchup": []}
    for s in sorted(recs):
        r = recs[s]
        for fld, attr in (("load", "load_w_mean"), ("pv", "pv_w_mean")):
            e = _e(r, fld)
            p = getattr(r, attr, None)
            if e is None or not finite_number(p) or r.sources.get(fld) == "power_integral":
                continue
            if fld == "load" and _load_false_zero(r):
                continue
            p_kwh = max(float(p), 0.0) / 1000.0
            if e <= DQ_PROPOSED.stall_energy_max_kwh and p >= DQ_PROPOSED.stall_power_min_w:
                out["stall"].append(s)
            elif e - p_kwh > max(DQ_PROPOSED.catchup_excess_min_kwh, p_kwh):
                out["catchup"].append(s)
    return out


def _balance_class(rec: HourRecord) -> tuple[str, bool] | None:
    """(balanced / swapped / unbalanced, import and export distinguishable) for an hour with all six counters, else None.
    load = pv + imp - exp + dis - chg; `swapped` balances only with import and export exchanged (a reversed CT)."""
    v = {f: _e(rec, f) for f in ENERGY_FIELDS}
    if None in v.values():
        return None
    terms = max(abs(x) for x in v.values())
    tol = max(DQ_PROPOSED.balance_tol_kwh, DQ_PROPOSED.balance_tol_fraction * terms)
    base = v["pv"] + v["dis"] - v["chg"]
    res = v["load"] - (base + v["imp"] - v["exp"])
    res_sw = v["load"] - (base + v["exp"] - v["imp"])
    cls = "balanced" if abs(res) <= tol else "swapped" if abs(res_sw) <= tol else "unbalanced"
    return cls, abs(v["imp"] - v["exp"]) > tol


def balance_counts(recs: Mapping[int, HourRecord]) -> dict[str, int]:
    """Energy balance per hour where all six counters exist: load = pv + imp - exp + dis - chg. Counts hours that balance,
    hours that balance only with import and export swapped (a reversed CT), and hours that balance neither way (these three
    add up to every such hour, whether or not import and export can be told apart); `distinguishable` counts the hours in
    which import and export can be told apart, and `distinguishable_only_swapped` those of them that balance only swapped
    (the share rule's numerator, ct_reversed)."""
    n = {"balanced": 0, "balanced_only_swapped": 0, "unbalanced": 0, "distinguishable": 0,
         "distinguishable_only_swapped": 0}
    key = {"balanced": "balanced", "swapped": "balanced_only_swapped", "unbalanced": "unbalanced"}
    for r in recs.values():
        bc = _balance_class(r)
        if bc is None:
            continue
        n[key[bc[0]]] += 1
        if bc[1]:
            n["distinguishable"] += 1
            n["distinguishable_only_swapped"] += bc[0] == "swapped"
    return n


def ct_reversed(counts: Mapping[str, int]) -> bool:
    """The share rule: of the hours in which import and export can be told apart, at least the PROPOSED number, and at
    least the PROPOSED share, balance only with import and export swapped. Both sides of the share count only those hours:
    an hour in which import and export cannot be told apart says nothing about the CT's direction, so it is never counted
    (`balanced_only_swapped` counts it and is not read here). Takes balance_counts' or recent_balance_counts' counts."""
    sw = counts["distinguishable_only_swapped"]
    dist = counts["distinguishable"]
    return sw >= DQ_PROPOSED.ct_reversal_min_hours and dist > 0 and sw / dist >= DQ_PROPOSED.ct_reversal_min_share


def recent_balance_counts(recs: Mapping[int, HourRecord], end: int) -> dict[str, int]:
    """The share rule's counts over the most recent PROPOSED number of distinguishable hours within the PROPOSED recent
    window before `end` (a reversal that began recently, which the long windows would dilute), under balance_counts'
    names: `distinguishable` and `distinguishable_only_swapped`."""
    n = sw = 0
    s = end - end % HOUR - HOUR
    lo = end - DQ_PROPOSED.ct_recent_window_h * HOUR
    while s >= lo and n < DQ_PROPOSED.ct_recent_hours:
        r = recs.get(s)
        bc = _balance_class(r) if r is not None else None
        if bc is not None and bc[1]:
            n += 1
            sw += bc[0] == "swapped"
        s -= HOUR
    return {"distinguishable": n, "distinguishable_only_swapped": sw}


CT_SHARE_KEYS = ("distinguishable", "distinguishable_only_swapped")   # the counts ct_reversed reads


def ct_reversal(recs: Mapping[int, HourRecord], end: int, lookback_nights: int) -> tuple[bool, dict]:
    """The one CT-reversal judgement shared by assess_inputs and prepare_history: the share rule over the whole history
    before `end`, over the learning lookback, and over the most recent distinguishable hours. Reversed when any says so.
    Returns (reversed, evidence: the windows that fired and, for each window, the two counts the share rule read, as
    `<window>_distinguishable` and `<window>_distinguishable_only_swapped` with window history, lookback or recent)."""
    before = {s: r for s, r in recs.items() if s < end}
    lb = {s: r for s, r in before.items() if s >= end - lookback_nights * 24 * HOUR}
    counts = (("history", balance_counts(before)), ("lookback", balance_counts(lb)),
              ("recent", recent_balance_counts(before, end)))
    fired = tuple(w for w, c in counts if ct_reversed(c))
    ev: dict = {f"{w}_{k}": c[k] for w, c in counts for k in CT_SHARE_KEYS}
    ev["windows"] = fired
    return bool(fired), ev


def clock_change_nights(start: datetime, end: datetime, tz_name: str) -> list[tuple[str, str]]:
    """(local date, kind) of every clock change in [start, end) (periods.clock_changes)."""
    return [(ch.local_day.isoformat(), ch.kind) for ch in clock_changes(start, end, tz_name)]


def _zero_pv_days(recs: Mapping[int, HourRecord], now: datetime, tz, forecasts: object) -> list[str]:
    """The most recent complete local days on which the history shows (almost) no PV while a forecast said there would be
    some; consecutive from yesterday backwards."""
    if not isinstance(forecasts, Mapping):
        return []
    days = []
    d = local_date(now, tz) - timedelta(days=1)
    for _ in range(14):
        t0, t1 = day_bounds(d, tz)
        hours = [s for s in range(int(t0.timestamp()), int(t1.timestamp()), HOUR)]
        present = [recs[s] for s in hours if s in recs and _e(recs[s], "pv") is not None]
        if not hours or len(present) < DQ_PROPOSED.history_day_min_coverage * len(hours):
            break
        actual = sum(_e(r, "pv") for r in present)
        fc = []
        for tab in forecasts.values():
            if isinstance(tab, Mapping):
                v = tab.get(d)
                if finite_number(v):
                    fc.append(float(v))
        if not (actual <= DQ_PROPOSED.pv_zero_day_max_kwh and fc and max(fc) >= DQ_PROPOSED.pv_forecast_min_kwh):
            break
        days.append(d.isoformat())
        d -= timedelta(days=1)
    return days


def history_findings(history: object, now: datetime, tz, pv_forecast_history: object = None,
                     lookback_nights: int | None = None) -> list[Finding]:
    """The history rules over the learning lookback before `now`: flaps, gaps, coverage, stalls, catch-up jumps, the energy
    balance (CT reversal), clock-change nights, history SOC false zeros and prolonged zero PV against its forecast.
    A missing history is judged elsewhere (INPUT_NOT_FRESH); this returns [] for it."""
    if not isinstance(history, History) or len(history) == 0 or not _aware(now):
        return []
    out: list[Finding] = []
    nights = lookback_nights if isinstance(lookback_nights, int) and lookback_nights > 0 else OvernightSettings().lookback_nights
    end = int(now.timestamp()) - int(now.timestamp()) % HOUR
    start = end - nights * 24 * HOUR
    allrecs = _records(history)
    junk = len(history.by_start) - len(allrecs)
    if junk:
        out.append(finding("HISTORY_RECORD_MALFORMED", WARN, "history.hourly", "history entries that are not well-formed hour "
                           "records are ignored (they never count towards the history's age)", entries=junk))
    recs = {s: r for s, r in allrecs.items() if start <= s < end}
    if not recs:
        return out
    first = min(recs)
    tz_name = getattr(tz, "key", None) or "Europe/London"

    def each(items, code, text, **ev):
        for i in items:
            out.append(finding(code, BLOCK, i, text, **ev))

    def warn(items, code, text, **ev):
        for i in items:
            out.append(finding(code, WARN, i, text, **ev))

    bad_values = sum(1 for r in recs.values() for v in (r.e.values() if isinstance(r.e, dict) else ())
                     if not finite_number(v) or v < 0)
    if bad_values:
        out.append(finding("HISTORY_VALUE_INVALID", WARN, "history.hourly", "the history holds non-finite or negative "
                           "energies; they are not learned from", values=bad_values))
    flap_start = end - DQ_PROPOSED.flap_window_h * HOUR
    flaps = dropout_runs(allrecs, max(flap_start, first), end)
    if len(flaps) >= DQ_PROPOSED.flap_min_dropouts:
        each(DONGLE_ITEMS, "TELEMETRY_FLAPPING", "the telemetry dropped out and recovered repeatedly in the recent window",
             dropouts=len(flaps), window_h=DQ_PROPOSED.flap_window_h)
        warn(HISTORY_ONLY_ITEMS, "TELEMETRY_FLAPPING", "the telemetry dropped out and recovered repeatedly in the recent "
             "window", dropouts=len(flaps))
    runs = dropout_runs(allrecs, first, end)
    long_runs = [n for _s, n in runs if n >= DQ_PROPOSED.gap_warn_h]
    if long_runs:
        out.append(finding("HISTORY_GAP", WARN, "history.hourly", "the learning lookback holds a long gap",
                           gaps=len(long_runs), longest_h=max(long_runs)))
    cov_start = max(first, end - DQ_PROPOSED.coverage_window_h * HOUR)
    span = (end - cov_start) // HOUR
    if span > 0:
        cov = sum(1 for s in range(cov_start, end, HOUR) if s in allrecs) / span
        if cov < DQ_PROPOSED.coverage_min_fraction:
            each(HISTORY_ITEMS, "HISTORY_COVERAGE_LOW", "the most recent week of history is too incomplete to learn from",
                 coverage=round(cov, 3), minimum=DQ_PROPOSED.coverage_min_fraction)
    st = stall_hours(recs)
    if st["stall"]:
        out.append(finding("HISTORY_COUNTER_STALL", WARN, "history.hourly", "a counter stood still while its power showed "
                           "flow; those hours are not learned from", hours=len(st["stall"])))
    if st["catchup"]:
        out.append(finding("HISTORY_COUNTER_CATCHUP", WARN, "history.hourly", "a counter jumped far above its power integral "
                           "(a catch-up after a stall); those hours are not learned from", hours=len(st["catchup"])))
    bc = balance_counts(recs)
    reversed_, ct_ev = ct_reversal(allrecs, end, nights)
    if reversed_:
        each(HISTORY_ITEMS, "HISTORY_CT_REVERSED", "the hourly energy balance fits only with import and export swapped "
             "(a reversed grid CT)", **ct_ev)
    elif bc["unbalanced"] and bc["unbalanced"] >= max(DQ_PROPOSED.ct_reversal_min_hours,
                                                      0.2 * (bc["balanced"] + bc["balanced_only_swapped"] + bc["unbalanced"])):
        out.append(finding("HISTORY_BALANCE_RESIDUAL", WARN, "history.hourly", "many hours do not balance (load against PV, "
                           "grid and battery energy)", **bc))
    suspect = sum(1 for r in recs.values() if (F_SOC_SUSPECT in (r.flags.get("soc", ()) if isinstance(r.flags, dict) else ()))
                  or (finite_number(r.soc_mean) and r.soc_mean <= DQ_PROPOSED.soc_zero_max_pct
                      and finite_number(r.batt_w_mean) and r.batt_w_mean > DQ_PROPOSED.soc_zero_discharge_w))
    if suspect:
        out.append(finding("HISTORY_SOC_SUSPECT", WARN, "history.hourly", "the history holds zero SOC readings while the "
                           "battery was discharging; they are not learned from", hours=suspect))
    try:
        nights_list = clock_change_nights(datetime.fromtimestamp(start, UTC), now, tz_name)
    except Exception:  # noqa: BLE001 - an unusable zone is judged elsewhere
        nights_list = []
    if nights_list:
        out.append(finding("DST_NIGHT_IN_LOOKBACK", WARN, "history.hourly", "the learning lookback holds a clock-change night; "
                           "I-D9 governs how it is learned", nights=tuple(d for d, _k in nights_list)))
    zero_days = _zero_pv_days(allrecs, now, tz, pv_forecast_history)
    if len(zero_days) >= DQ_PROPOSED.pv_zero_min_days:
        # BLOCK (fail closed): the item is withheld whether or not the cycle reads insufficient_items(); a cycle that does
        # may show it as INSUFFICIENT_DATA instead (evidence item_status), never with a number
        out.append(finding("PV_NO_OUTPUT_VS_FORECAST", BLOCK, "pv_tomorrow", "the PV produced almost nothing on the most "
                           "recent days although a forecast said it would: the PV forecast has insufficient data",
                           days=len(zero_days), item_status="INSUFFICIENT_DATA"))
        warn(PV_ITEMS_WARNED, "PV_NO_OUTPUT_VS_FORECAST", "the PV produced almost nothing on the most recent days although a "
             "forecast said it would", days=len(zero_days))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# prepare_history
# ---------------------------------------------------------------------------------------------------------------------

def _exporting(rec: HourRecord) -> bool:
    exp = _e(rec, "exp")
    g = rec.grid_w_mean
    return (exp is not None and exp > DQ_PROPOSED.export_evidence_kwh) or (
        finite_number(g) and g < -DQ_PROPOSED.load_false_zero_flow_w)


def _non_exporting(rec: HourRecord) -> bool:
    """A recorded zero export (and no exporting grid mean): the only hours KEEP_NON_EXPORTING_ONLY keeps."""
    exp = rec.e.get("exp") if isinstance(rec.e, dict) else None
    g = rec.grid_w_mean
    return finite_number(exp) and exp == 0.0 and not (finite_number(g) and g < 0.0)


def _load_false_zero(rec: HourRecord) -> bool:
    e = _e(rec, "load")
    return e is not None and e <= DQ_PROPOSED.stall_energy_max_kwh and _exporting(rec)


def _counter_disagrees(rec: HourRecord) -> bool | None:
    """The load counter against the balance-derived load (pv + imp - exp + dis - chg); None when it cannot be computed."""
    v = {f: _e(rec, f) for f in ENERGY_FIELDS}
    if None in v.values():
        return None
    derived = v["pv"] + v["imp"] - v["exp"] + v["dis"] - v["chg"]
    tol = max(DQ_PROPOSED.counter_check_tol_kwh, DQ_PROPOSED.counter_check_tol_fraction * max(abs(derived), abs(v["load"])))
    return abs(v["load"] - derived) > tol


def prepare_history(history: History | None, decisions: DecisionSet, now: datetime, *,
                    accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> tuple[History | None, list[Finding]]:
    """The learning history the cycle may use: None unless I-D8 is satisfied; otherwise a COPY truncated to hours that had
    ended by `now`, with I-D8 applied before the cut-over:

      load power   EXCLUDE removes it; KEEP_NON_EXPORTING_ONLY keeps it only for hours with a recorded zero export
                   (load energy integrated from load power counts as load power);
      load counter EXCLUDE_PRE_CUTOVER removes it; KEEP_AFTER_COUNTER_CHECK keeps it only for hours whose counter check
                   ran and passed: an hour that reads zero while exporting, disagrees with the balance-derived load, or
                   lacks a counter the check needs is removed (WARN HISTORY_COUNTER_CHECK_UNAVAILABLE counts the last);

    and, at any time, counter stalls and catch-up jumps, non-finite or negative energies and zero SOC while discharging
    removed. After the cut-over a load that reads zero while exporting is removed, and repeated ones BLOCK (the cut-over
    instant cannot be right). A history whose energy balance shows a reversed CT (ct_reversal: the same judgement as
    assess_inputs) BLOCKs. Never modifies its input and never raises: anything unexpected returns None with a BLOCK
    (HISTORY_MALFORMED)."""
    try:
        return _prepare(history, decisions, now, accept_provenance)
    except Exception as exc:  # noqa: BLE001 - fail closed: a history that cannot be prepared is not used
        return None, [finding("HISTORY_MALFORMED", BLOCK, "history", "the history could not be prepared; no history is used "
                              "for learning", error=type(exc).__name__)]


def _prepare(history: object, decisions: object, now: object, accept_provenance: object
             ) -> tuple[History | None, list[Finding]]:
    out: list[Finding] = []
    if not _aware(now):
        return None, [finding("NOW_INVALID", BLOCK, "history", "the cycle time is not an aware datetime")]
    if not isinstance(history, History) or len(history) == 0:
        return None, [finding("HISTORY_MISSING", BLOCK, "history", "no history was supplied")]
    if not isinstance(decisions, DecisionSet):
        return None, [finding("DECISIONS_MISSING", BLOCK, "history", "no decision set was supplied")]
    try:
        acc = frozenset(accept_provenance)
    except TypeError:
        return None, [finding("ACCEPT_PROVENANCE_INVALID", BLOCK, "history", "the accepted provenances are not a set")]
    d8 = decisions.get("D8")
    if not decisions.satisfied("D8", acc):
        code = "DECISION_D8_INVALID" if d8.status == "INVALID" else "DECISION_D8_OPEN"
        return None, [finding(code, BLOCK, "history",
                              "I-D8 (derived house-load cut-over) is not satisfied, so no history is used for learning")]
    pol = d8.value
    cut = pol.cutover.astimezone(UTC)
    cut_ts = int(cut.timestamp())
    now_ts = int(now.timestamp())
    src = _records(history)
    skipped = len(history.by_start) - len(src)
    if skipped:
        out.append(finding("HISTORY_RECORD_MALFORMED", WARN, "history", "history entries that are not hour records are "
                           "ignored", entries=skipped))
    copy_ = History(copy.deepcopy(r) for s, r in sorted(src.items()) if s + HOUR <= now_ts)
    recs = copy_.by_start
    counts = {"power_hours": 0, "energy_hours": 0, "false_zero_pre": 0, "counter_mismatch_pre": 0,
              "counter_unverifiable_pre": 0, "false_zero_post": 0, "stall": 0, "catchup": 0, "invalid": 0, "soc_suspect": 0}

    reversed_, ct_ev = ct_reversal(recs, now_ts - now_ts % HOUR, OvernightSettings().lookback_nights)
    if reversed_:
        return None, [finding("HISTORY_CT_REVERSED", BLOCK, "history", "the hourly energy balance fits only with import and "
                              "export swapped (a reversed grid CT): no history is used for learning", **ct_ev)]

    for s, rec in recs.items():
        for k in list(rec.e):
            if not finite_number(rec.e[k]) or rec.e[k] < 0:
                del rec.e[k]
                counts["invalid"] += 1
        for attr in ("load_w_mean", "pv_w_mean", "batt_w_mean", "grid_w_mean", "soc_mean", "soc_min", "soc_max"):
            v = getattr(rec, attr)
            if v is not None and not finite_number(v):
                setattr(rec, attr, None)
                counts["invalid"] += 1
        if rec.soc_mean is not None and not 0.0 <= rec.soc_mean <= 100.0:
            rec.soc_mean = None
            counts["invalid"] += 1
        if rec.soc_mean is not None and (F_SOC_SUSPECT in rec.flags.get("soc", ()) or (
                rec.soc_mean <= DQ_PROPOSED.soc_zero_max_pct and finite_number(rec.batt_w_mean)
                and rec.batt_w_mean > DQ_PROPOSED.soc_zero_discharge_w)):
            rec.soc_mean = rec.soc_min = rec.soc_max = None
            counts["soc_suspect"] += 1
    st = stall_hours(recs)
    for kind in ("stall", "catchup"):
        for s in st[kind]:
            r = recs[s]
            for fld, attr in (("load", "load_w_mean"), ("pv", "pv_w_mean")):
                e, p = _e(r, fld), getattr(r, attr)
                if e is None or not finite_number(p) or (fld == "load" and _load_false_zero(r)):
                    continue
                p_kwh = max(float(p), 0.0) / 1000.0
                hit = (e <= DQ_PROPOSED.stall_energy_max_kwh and p >= DQ_PROPOSED.stall_power_min_w) if kind == "stall" \
                    else (e - p_kwh > max(DQ_PROPOSED.catchup_excess_min_kwh, p_kwh))
                if hit:
                    del r.e[fld]
                    counts[kind] += 1

    for s, rec in recs.items():
        if s < cut_ts:                                   # an hour that begins before the cut-over
            integral = rec.sources.get("load") == "power_integral"
            keep_power = pol.load_power_policy == KEEP_NON_EXPORTING_ONLY and _non_exporting(rec)
            if pol.load_power_policy == EXCLUDE or not keep_power:
                if rec.load_w_mean is not None:
                    rec.load_w_mean = None
                    counts["power_hours"] += 1
                if integral and "load" in rec.e:
                    del rec.e["load"]
                    counts["energy_hours"] += 1
            if "load" not in rec.e or integral:
                continue
            if pol.load_counter_policy == EXCLUDE_PRE_CUTOVER:
                del rec.e["load"]
                counts["energy_hours"] += 1
            elif pol.load_counter_policy == KEEP_AFTER_COUNTER_CHECK:
                check = _counter_disagrees(rec)
                if _load_false_zero(rec):
                    del rec.e["load"]
                    counts["false_zero_pre"] += 1
                elif check is None:                      # the check cannot run: the counter is not kept unchecked
                    del rec.e["load"]
                    counts["counter_unverifiable_pre"] += 1
                elif check:
                    del rec.e["load"]
                    counts["counter_mismatch_pre"] += 1
            else:                                        # an unknown policy keeps nothing (HD1Cutover refuses one)
                del rec.e["load"]
                counts["energy_hours"] += 1
        elif _load_false_zero(rec):
            del rec.e["load"]
            counts["false_zero_post"] += 1

    if counts["false_zero_post"] >= DQ_PROPOSED.false_zero_after_cutover_block_hours:
        return None, out + [finding("HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER", BLOCK, "history", "the load reads zero while "
                                    "exporting in several hours after the recorded cut-over: the cut-over instant cannot be "
                                    "right, so no history is used for learning", hours=counts["false_zero_post"],
                                    cutover=cut.isoformat())]
    if counts["power_hours"] or counts["energy_hours"]:
        out.append(finding("HISTORY_PRE_CUTOVER_LOAD_REMOVED", INFO, "history",
                           "pre-cut-over load removed from the learning copy as I-D8 records",
                           power_hours=counts["power_hours"], energy_hours=counts["energy_hours"], cutover=cut.isoformat(),
                           load_power_policy=pol.load_power_policy, load_counter_policy=pol.load_counter_policy))
    for key, code, text in (
            ("false_zero_pre", "HISTORY_LOAD_FALSE_ZERO_REMOVED", "pre-cut-over load hours reading zero while exporting were "
                                                                  "removed although the counter is kept"),
            ("counter_mismatch_pre", "HISTORY_COUNTER_CHECK_REMOVED", "pre-cut-over load hours disagreeing with the "
                                                                      "balance-derived load were removed"),
            ("counter_unverifiable_pre", "HISTORY_COUNTER_CHECK_UNAVAILABLE", "pre-cut-over load hours lacking a counter the "
                                                                              "counter check needs were removed, not kept "
                                                                              "unchecked"),
            ("false_zero_post", "HISTORY_LOAD_FALSE_ZERO_REMOVED", "load hours reading zero while exporting after the "
                                                                   "cut-over were removed"),
            ("stall", "HISTORY_COUNTER_STALL", "counter stall hours were removed from the learning copy"),
            ("catchup", "HISTORY_COUNTER_CATCHUP", "counter catch-up hours were removed from the learning copy"),
            ("invalid", "HISTORY_VALUE_INVALID", "non-finite, negative or out-of-range values were removed"),
            ("soc_suspect", "HISTORY_SOC_SUSPECT", "zero SOC readings while discharging were removed")):
        if counts[key]:
            out.append(finding(code, WARN, "history", text, hours=counts[key]))
    return copy_, out
