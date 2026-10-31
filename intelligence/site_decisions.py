"""The Intelligence decision register: typed site decisions I-D1..I-D9, their provenance, the gates they drive and the
freshness rules they feed (SHADOW, advisory; the single source of truth for all of these).

Nothing here is an owner decision. The repository records none: every decision is OPEN until a site file supplies a typed,
valid record, and a record counts only when its provenance is accepted (by default only an OWNER_RECORD with an opaque
record reference, loaded from the site-local file). Values are never invented: an OPEN, INVALID or unaccepted decision
BLOCKs every item that depends on it, and no battery figure of the shipped example configuration is ever kept
(`apply_to_siteconfig`).

    ids          internal D1..D9 (finding codes DECISION_D<n>_OPEN / DECISION_D<n>_INVALID); display label I-D<n>.
                 The loader accepts both spellings.
    statuses     OPEN, RECORDED, INVALID. Free text is never RECORDED; INVALID always BLOCKs.
    provenance   SYNTHETIC_TEST, SYNTHETIC_EXAMPLE, CALLER_DECLARATION_UNVERIFIED, OWNER_RECORD.
    values       I-D1 PlanningFloor, I-D2 Protection, I-D3 CapacityAuthority, I-D4 CapacityBand, I-D5 Efficiency,
                 I-D6 FreshnessOverrides, I-D7 RequiredInputsOverride (retired: the required inputs are the code constants
                 REQUIRED_SIGNALS / REQUIRED_READINGS; a site may only ADD to them), I-D8 HD1Cutover, I-D9 DSTPolicy.

Reserve roles are kept apart (ReserveRole). Firmware features (Dump to Grid) do not honour any planning floor: a floor
limits what the advice recommends, nothing more (SAFETY.md section 9).

PROPOSED_ANSWERS are engineering suggestions shown to the owner as text. They are never applied while a decision is OPEN
and are never a loadable decisions mapping.

Imports: the standard library, intelligence.config / explain / timeutil / periods, and ecco_core.state only. No I/O, no
clock read: every time is a caller argument.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Iterable, Mapping

from ecco_core.state import spec_for

from .config import DEFAULT_TECHNICAL_MIN_SOC_PCT, SiteConfig
from .explain import finite_number
from .periods import DEFAULT_TZ, clock_changes
from .timeutil import UTC

REGISTER_VERSION = "ecco-intel-decisions/1"

# ---------------------------------------------------------------------------------------------------------------------
# findings (the one Finding type of the Intelligence foundation; S0's shape)
# ---------------------------------------------------------------------------------------------------------------------

INFO, WARN, BLOCK = "INFO", "WARN", "BLOCK"
SEVERITIES = (BLOCK, WARN, INFO)


def _jsonable(v: object) -> object:
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, datetime):
        return v.isoformat()
    return v


@dataclass(frozen=True)
class Finding:
    """One observation: code, severity (BLOCK / WARN / INFO), subject, plain-language text and sorted evidence pairs."""
    code: str
    severity: str
    subject: str
    text: str
    evidence: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {self.severity!r}")
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def message(self) -> str:
        """The S0 name of `text`."""
        return self.text

    @property
    def blocks(self) -> bool:
        return self.severity == BLOCK

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "subject": self.subject, "text": self.text,
                "evidence": {k: v for k, v in self.evidence}}


def finding(code: str, severity: str, subject: str, text: str, **evidence: object) -> Finding:
    return Finding(code, severity, subject, text, tuple(sorted((k, _jsonable(v)) for k, v in evidence.items())))


def blocking(findings: Iterable[Finding]) -> bool:
    return any(f.severity == BLOCK for f in findings)


# ---------------------------------------------------------------------------------------------------------------------
# ids, statuses, provenance
# ---------------------------------------------------------------------------------------------------------------------

DECISION_IDS = tuple(f"D{i}" for i in range(1, 10))
_ID_PATTERN = r"^(?:I-)?(D[1-9])$"   # applied with re.match (the re module caches the compiled form)


def display_label(did: str) -> str:
    """'D1' -> 'I-D1' (the label every display surface uses)."""
    if did not in DECISION_IDS:
        raise ValueError(f"unknown decision id {did!r}")
    return "I-" + did


def normalise_id(key: object) -> str | None:
    """'D1' or 'I-D1' -> 'D1'; anything else -> None."""
    if not isinstance(key, str):
        return None
    m = re.match(_ID_PATTERN, key)
    return m.group(1) if m else None


class DecisionStatus:
    OPEN = "OPEN"
    RECORDED = "RECORDED"
    INVALID = "INVALID"
    ALL = (OPEN, RECORDED, INVALID)


class Provenance:
    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    SYNTHETIC_EXAMPLE = "SYNTHETIC_EXAMPLE"
    CALLER_DECLARATION_UNVERIFIED = "CALLER_DECLARATION_UNVERIFIED"
    OWNER_RECORD = "OWNER_RECORD"
    ALL = (SYNTHETIC_TEST, SYNTHETIC_EXAMPLE, CALLER_DECLARATION_UNVERIFIED, OWNER_RECORD)


DEFAULT_ACCEPT_PROVENANCE = frozenset({Provenance.OWNER_RECORD})
ALL_PROVENANCE = frozenset(Provenance.ALL)
RECORD_REF_PATTERN = r"^REC-[0-9]{8}-[a-z0-9][a-z0-9-]{2,63}$"   # always applied with re.fullmatch (see record_ref_ok)


def record_ref_ok(ref: object) -> bool:
    """A record reference REC-YYYYMMDD-<slug>, matched over the WHOLE string (a trailing newline is refused)."""
    return isinstance(ref, str) and re.fullmatch(RECORD_REF_PATTERN, ref) is not None


_ref_ok = record_ref_ok   # the internal name used below

# where a decisions mapping came from. Only the site-local file can carry an OWNER_RECORD.
SOURCE_SITE_LOCAL = "site_local"
SOURCES = (SOURCE_SITE_LOCAL, "example_profile", "declaration", "test")


class ReserveRole:
    SOFT_PLANNING_FLOOR = "SOFT_PLANNING_FLOOR"        # a preference every recommendation stays above
    HA_RESERVE_HELPER = "HA_RESERVE_HELPER"            # the Home Assistant helper; ACS1's lower bound; raise-only in advice
    FEATURE_STOP_LEVEL = "FEATURE_STOP_LEVEL"          # where one feature stops (the Dump to Grid stop SOC)
    PHYSICAL_PROTECTION = "PHYSICAL_PROTECTION"        # the inverter's own battery protection; read-only to ECCO
    INVERTER_TOU_SETTING = "INVERTER_TOU_SETTING"      # a TOU slot's target SOC: an inverter schedule setting
    DERIVED_EFFECTIVE = "DERIVED_EFFECTIVE"            # SiteConfig.effective_reserve: computed, never set
    ALL = (SOFT_PLANNING_FLOOR, HA_RESERVE_HELPER, FEATURE_STOP_LEVEL, PHYSICAL_PROTECTION, INVERTER_TOU_SETTING,
           DERIVED_EFFECTIVE)


DECISION_TITLES = MappingProxyType({
    "D1": "Canonical soft planning floor",
    "D2": "Inverter physical protection level",
    "D3": "Battery capacity authority",
    "D4": "Capacity mismatch band",
    "D5": "Efficiency basis",
    "D6": "Advisory freshness limits",
    "D7": "Required signals per advisor (retired)",
    "D8": "Derived house-load cut-over and pre-fix history",
    "D9": "Clock-change night policy",
})

DECISION_QUESTIONS = MappingProxyType({
    "D1": "Which of the helper, the Intelligence user reserve, a feature stop level or a new single setting is THE "
          "planning floor, and must precharge and Dump advice honour it or only display it?",
    "D2": "What is the inverter's own protection (shutdown) level, and how is it to be supplied without a write?",
    "D3": "Which source is canonical (owner helper, learned from discharge, or an Ah register with a stated voltage), "
          "and what is each other source for?",
    "D4": "Is 8 % (|a-b| / mean) the right warning band?",
    "D5": "Is the single canonical value round-trip (the engine applies sqrt each way) and in what unit?",
    "D6": "What limit applies to house / PV / battery / grid power, inverter status and the reserve helper "
          "(only SOC and hourly history have one today)?",
    "D7": "No longer an owner question: the required signals and readings are code constants (REQUIRED_SIGNALS / "
          "REQUIRED_READINGS); a site may only add to them.",
    "D8": "At what instant did the derived load sensor take effect, and is earlier load history excluded, replaced, or "
          "kept only where not exporting?",
    "D9": "Should a 25 h or 23 h night be excluded from learning, normalised per hour, or planned as its own length?",
})

# ---------------------------------------------------------------------------------------------------------------------
# value vocabularies
# ---------------------------------------------------------------------------------------------------------------------

INTELLIGENCE_USER_RESERVE = "INTELLIGENCE_USER_RESERVE"
HA_RESERVE_HELPER = ReserveRole.HA_RESERVE_HELPER
FEATURE_STOP_LEVEL = ReserveRole.FEATURE_STOP_LEVEL
NEW_SINGLE_SETTING = "NEW_SINGLE_SETTING"
PLANNING_FLOOR_SOURCES = (INTELLIGENCE_USER_RESERVE, HA_RESERVE_HELPER, FEATURE_STOP_LEVEL, NEW_SINGLE_SETTING)
FLOOR_SOURCES_WITH_VALUE = (INTELLIGENCE_USER_RESERVE, NEW_SINGLE_SETTING)

OWNER_STATEMENT = "OWNER_STATEMENT"
READ_ONLY_SENSOR_SNAPSHOT = "READ_ONLY_SENSOR_SNAPSHOT"
PROTECTION_SUPPLIERS = (OWNER_STATEMENT, READ_ONLY_SENSOR_SNAPSHOT)

CAPACITY_KINDS = ("CONFIGURED_HELPER", "SITECONFIG_VALUE", "LEARNED_FROM_DISCHARGE", "REGISTER_AH", "EXAMPLE_DEFAULT")
CAPACITY_AUTHORITY_KINDS = tuple(k for k in CAPACITY_KINDS if k != "EXAMPLE_DEFAULT")

FRACTION, PERCENT = "fraction", "percent"
EFFICIENCY_UNITS = (FRACTION, PERCENT)
ROUND_TRIP, ONE_WAY = "ROUND_TRIP", "ONE_WAY"
EFFICIENCY_BASES = (ROUND_TRIP, ONE_WAY)

EXCLUDE, KEEP_NON_EXPORTING_ONLY = "EXCLUDE", "KEEP_NON_EXPORTING_ONLY"
LOAD_POWER_POLICIES = (EXCLUDE, KEEP_NON_EXPORTING_ONLY)
EXCLUDE_PRE_CUTOVER, KEEP_AFTER_COUNTER_CHECK = "EXCLUDE_PRE_CUTOVER", "KEEP_AFTER_COUNTER_CHECK"
LOAD_COUNTER_POLICIES = (EXCLUDE_PRE_CUTOVER, KEEP_AFTER_COUNTER_CHECK)

EXCLUDE_CHANGED_PERIODS, NORMALISE_TO_NOMINAL = "EXCLUDE_CHANGED_PERIODS", "NORMALISE_TO_NOMINAL"
DST_HISTORY_RULES = (EXCLUDE_CHANGED_PERIODS, NORMALISE_TO_NOMINAL)
SCALE_TO_ACTUAL, SCALE_UP_ONLY = "SCALE_TO_ACTUAL", "SCALE_UP_ONLY"
DST_TARGET_RULES = (SCALE_TO_ACTUAL, SCALE_UP_ONLY)


@dataclass(frozen=True)
class ProposedThresholds:
    """Every number below is a PROPOSAL (the single copy; S0's values). None is an owner decision."""
    status: str = "PROPOSED_PENDING_OWNER"
    capacity_warn_band_pct: float = 8.0          # symmetric: |a-b| / mean(a,b); 8 % is the stated capacity uncertainty
    capacity_plausible_kwh: tuple[float, float] = (0.5, 500.0)
    efficiency_round_trip_max_plausible: float = 0.97   # a "round-trip" figure above this is probably one-way
    efficiency_one_way_min_plausible: float = 0.88      # a "one-way" figure below this is probably round-trip
    efficiency_agree_tolerance: float = 0.01
    soc_agree_points: float = 2.0                # SOC is an integer percentage; allow one step either way
    power_agree_w: float = 100.0
    power_agree_fraction: float = 0.05
    other_agree_fraction: float = 0.05


PROPOSED = ProposedThresholds()

# ---------------------------------------------------------------------------------------------------------------------
# freshness (a mirror of ecco_core.freshness's ADVISORY catalogue; a drift test compares them)
# ---------------------------------------------------------------------------------------------------------------------

ADVISORY_LIMITS_S: Mapping[str, float | None] = MappingProxyType({
    "battery.soc": 900.0,                 # intelligence/advisor.py STALE_SOC_SECONDS
    "history.hourly": 6 * 3600.0,         # intelligence/engine.py: learning history older than 6 h is stale
    "inverter.healthy": None,             # UNRESOLVED: never fresh until a site limit is recorded (I-D6)
    "house.power": None,
    "pv.power": None,
    "battery.power": None,
    "grid.power": None,
    "reserve.ha_minimum_soc": None,
})
PROPOSED_FRESHNESS_CEILING_S = 900.0      # equal to the defined SOC advisory limit; an override above it is INVALID

LIVENESS_KEY = "liveness.dongle_poll_changed_at"
# The dongle firmware publishes a value only when it changes, so a dongle-sourced input's age is taken from the time the
# poll text last changed (LIVENESS_KEY), never from the value's own last change.
DONGLE_SIGNALS = ("battery.soc", "battery.power", "grid.power", "house.power", "pv.power", "inverter.healthy")
DONGLE_READINGS = ("battery.soc_raw_pct", "capacity.reg204_ah", "protection.shutdown_soc_pct", "stop.dump_soc_pct",
                   "tou.slot_table", "tou.current_target_soc_pct", "inverter.clock_offset_s")
# A day-ahead forecast is judged by its local issue date, not by an age limit: fresh only when observed on the same local
# date as `now` (and not in the future). This is a structural rule, not an owner threshold.
DATE_SCOPED_READINGS = ("pv.forecast_today_kwh", "pv.forecast_tomorrow_kwh")

# ---------------------------------------------------------------------------------------------------------------------
# items, gates and required inputs (add-only)
# ---------------------------------------------------------------------------------------------------------------------

ITEMS = ("overnight_demand", "charge_target", "export_event", "dump_to_grid", "v1_summary", "predicted_morning_soc",
         "predicted_day_load", "pv_tomorrow")
PUBLISHED_ITEMS = tuple(i for i in ITEMS if i != "v1_summary")

ITEM_GATES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "overnight_demand": ("D8",),
    "charge_target": ("D1", "D2", "D3", "D5", "D8"),
    "export_event": ("D1", "D2", "D3", "D5", "D6", "D8"),
    "dump_to_grid": ("D1", "D2", "D3", "D5", "D6", "D8"),
    "v1_summary": ("D1", "D2", "D3", "D5", "D8"),
    "predicted_morning_soc": ("D1", "D2", "D3", "D5", "D8"),
    "predicted_day_load": ("D8",),
    "pv_tomorrow": (),
})
# I-D4 is required when two or more capacity sources are present for an item that rests on capacity (I-D3).
CONDITIONAL_D4_ITEMS = tuple(i for i in ITEMS if "D3" in ITEM_GATES[i])
# I-D9 is required when a period, or a learning period within the overnight lookback, crosses a clock change.
CONDITIONAL_D9_ITEMS = ("overnight_demand", "charge_target", "predicted_morning_soc")

_BATTERY = ("battery.soc", "history.hourly")
_POWERS = ("house.power", "pv.power", "battery.power", "grid.power", "inverter.healthy")
REQUIRED_SIGNALS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "overnight_demand": ("history.hourly",),
    "charge_target": _BATTERY,
    "export_event": _BATTERY + _POWERS,
    "dump_to_grid": _BATTERY + _POWERS,
    "v1_summary": _BATTERY,
    "predicted_morning_soc": _BATTERY,
    "predicted_day_load": ("history.hourly",),
    "pv_tomorrow": ("history.hourly",),
})
REQUIRED_READINGS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "overnight_demand": (),
    "charge_target": ("limits.max_grid_charge_w",),
    "export_event": ("limits.max_grid_charge_w", "tariff.export_rates"),
    "dump_to_grid": ("limits.max_grid_charge_w", "stop.dump_soc_pct", "tariff.export_rates"),
    "v1_summary": ("limits.max_grid_charge_w",),
    "predicted_morning_soc": ("limits.max_grid_charge_w",),
    "predicted_day_load": (),
    "pv_tomorrow": ("pv.forecast_tomorrow_kwh",),
})
REQUIRED_SITE_FACTS: Mapping[str, tuple[str, ...]] = MappingProxyType({"pv_tomorrow": ("pv_array_kwp",)})
# The charge window: a VERIFIED tariff (judged by the planning layer), else the read-only TOU slot table with a WARN,
# else BLOCK. Never the SiteConfig example window. Export and Dump advice rest on the refill window too (add-only).
CHARGE_WINDOW_ITEMS = ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc", "v1_summary")
CHARGE_WINDOW_SOURCES = ("tariff.import_rates", "tou.slot_table")
# The window the planning layer derived from one of CHARGE_WINDOW_SOURCES, handed to apply_to_siteconfig as a judged input
# (an InputState whose value is (start_min, end_min) after local midnight, fresh under its source's limit). It is not a
# SiteReading: nothing reads it from Home Assistant.
CHARGE_WINDOW_KEY = "charge_window.local_minutes"
# readings a decision's chosen source brings with it (added to every item gated by that decision)
CAPACITY_READING_BY_KIND = MappingProxyType({"CONFIGURED_HELPER": "capacity.helper_kwh",
                                             "LEARNED_FROM_DISCHARGE": "capacity.fe1_wh_per_pct",
                                             "REGISTER_AH": "capacity.reg204_ah"})
# readings the quality layer needs to judge a required input (each gets its own I-D6 key; UNRESOLVED until recorded;
# CCR-DQ-1, add-only)
QUALIFYING_READING_KEYS = ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events")
GATE_READING_KEYS = tuple(sorted({LIVENESS_KEY, "protection.shutdown_soc_pct", "stop.dump_soc_pct",
                                  *CAPACITY_READING_BY_KIND.values(), *CHARGE_WINDOW_SOURCES,
                                  *QUALIFYING_READING_KEYS,
                                  *(r for rs in REQUIRED_READINGS.values() for r in rs)}))
# readings the planning layer judges although no item requires them (each gets its own I-D6 key; UNRESOLVED until
# recorded; CCR-PLAN-1, add-only; tariff.events comes through QUALIFYING_READING_KEYS)
PLANNING_READING_KEYS = ("tou.current_target_soc_pct",)
FRESHNESS_OVERRIDE_KEYS = tuple(sorted(set(ADVISORY_LIMITS_S) | (set(GATE_READING_KEYS) | set(PLANNING_READING_KEYS))
                                       - set(DATE_SCOPED_READINGS) - {LIVENESS_KEY}))


def items_gated_by(did: str) -> tuple[str, ...]:
    """Every item a decision can block (unconditional and conditional), in ITEMS order. I-D7 (retired) gates nothing
    while valid; an INVALID I-D7 blocks every item."""
    if did not in DECISION_IDS:
        raise ValueError(f"unknown decision id {did!r}")
    cond = {"D4": CONDITIONAL_D4_ITEMS, "D9": CONDITIONAL_D9_ITEMS}.get(did, ())
    return tuple(i for i in ITEMS if did in ITEM_GATES[i] or i in cond)


# ---------------------------------------------------------------------------------------------------------------------
# typed decision values
# ---------------------------------------------------------------------------------------------------------------------

def _num(x: object) -> float | None:
    return float(x) if finite_number(x) else None


def _pct_ok(x: object) -> bool:
    return finite_number(x) and 0.0 <= x <= 100.0


def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.tzinfo.utcoffset(x) is not None


def _parse_dt(v: object, what: str) -> object:
    """An ISO-8601 string -> datetime (validation of awareness happens later); anything else is passed through."""
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return v
    return v


def _strict_keys(obj: Mapping, allowed: Iterable[str], what: str) -> None:
    extra = set(obj) - set(allowed)
    if extra:
        raise ValueError(f"{what}: unknown keys {sorted(map(str, extra))}")


@dataclass(frozen=True)
class PlanningFloor:
    """I-D1. `value_pct` is required for INTELLIGENCE_USER_RESERVE and NEW_SINGLE_SETTING and must be absent for
    HA_RESERVE_HELPER and FEATURE_STOP_LEVEL (their value is a fresh reading at every cycle). `advice_honours`: must
    precharge / export / Dump ADVICE honour the floor (True) or only display it (False). Firmware features (Dump) do not
    honour any floor whatever this says."""
    source: str
    value_pct: float | None = None
    advice_honours: bool | None = None

    def problems(self) -> list[str]:
        out = []
        if self.source not in PLANNING_FLOOR_SOURCES:
            out.append(f"source {self.source!r} is not one of {PLANNING_FLOOR_SOURCES}")
        elif self.source in FLOOR_SOURCES_WITH_VALUE and not _pct_ok(self.value_pct):
            out.append(f"{self.source} needs value_pct, a finite percentage in 0..100")
        elif self.source not in FLOOR_SOURCES_WITH_VALUE and self.value_pct is not None:
            out.append(f"{self.source} is read at every cycle; a recorded value_pct would go stale and is refused")
        if not isinstance(self.advice_honours, bool):
            out.append("advice_honours must be true or false")
        return out

    def to_dict(self) -> dict:
        return {"source": self.source, "value_pct": self.value_pct, "advice_honours": self.advice_honours}


@dataclass(frozen=True)
class Protection:
    """I-D2. OWNER_STATEMENT: the owner read the level (value_pct, observed_at). READ_ONLY_SENSOR_SNAPSHOT: the level is the
    fresh protection.shutdown_soc_pct reading at every cycle (value_pct absent). Raise-only on the technical minimum."""
    supplied_by: str
    value_pct: float | None = None
    observed_at: datetime | None = None

    def problems(self) -> list[str]:
        out = []
        if self.supplied_by not in PROTECTION_SUPPLIERS:
            out.append(f"supplied_by {self.supplied_by!r} is not one of {PROTECTION_SUPPLIERS}")
        elif self.supplied_by == OWNER_STATEMENT:
            if not _pct_ok(self.value_pct):
                out.append("an owner statement needs value_pct, a finite percentage in 0..100")
            if not _aware(self.observed_at):
                out.append("an owner statement needs observed_at, an aware date-time")
        else:
            if self.value_pct is not None:
                out.append("a sensor snapshot is read at every cycle; a recorded value_pct is refused")
            if self.observed_at is not None and not _aware(self.observed_at):
                out.append("observed_at must be an aware date-time")
        return out

    def to_dict(self) -> dict:
        return {"supplied_by": self.supplied_by, "value_pct": self.value_pct,
                "observed_at": None if self.observed_at is None else _jsonable(self.observed_at)}


@dataclass(frozen=True)
class CapacityAuthority:
    """I-D3. Either a stated value_kwh or resolve_at_run (the kind's reading, fresh at every cycle). An Ah register needs
    nominal_voltage_v. EXAMPLE_DEFAULT is never an authority."""
    kind: str
    value_kwh: float | None = None
    resolve_at_run: bool = False
    nominal_voltage_v: float | None = None

    def problems(self) -> list[str]:
        out = []
        lo, hi = PROPOSED.capacity_plausible_kwh
        if self.kind not in CAPACITY_AUTHORITY_KINDS:
            out.append(f"kind {self.kind!r} is not one of {CAPACITY_AUTHORITY_KINDS}")
            return out
        if not isinstance(self.resolve_at_run, bool):
            out.append("resolve_at_run must be true or false")
            return out
        if self.resolve_at_run:
            if self.value_kwh is not None:
                out.append("give either value_kwh or resolve_at_run, not both")
            if self.kind not in CAPACITY_READING_BY_KIND:
                out.append(f"{self.kind} has no reading to resolve at run time; state value_kwh")
            if self.kind == "REGISTER_AH" and not (finite_number(self.nominal_voltage_v) and self.nominal_voltage_v > 0):
                out.append("an Ah register needs nominal_voltage_v, a positive number")
        elif not (finite_number(self.value_kwh) and lo <= self.value_kwh <= hi):
            out.append(f"value_kwh must be a finite number in {lo:g}..{hi:g} kWh (or set resolve_at_run)")
        if self.nominal_voltage_v is not None and not (finite_number(self.nominal_voltage_v) and self.nominal_voltage_v > 0):
            out.append("nominal_voltage_v must be a positive number")
        return out

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value_kwh": self.value_kwh, "resolve_at_run": self.resolve_at_run,
                "nominal_voltage_v": self.nominal_voltage_v}


@dataclass(frozen=True)
class CapacityBand:
    """I-D4: the symmetric mismatch band |a-b| / mean(a, b), in percent."""
    pct: float

    def problems(self) -> list[str]:
        return [] if finite_number(self.pct) and 0.0 < self.pct <= 50.0 else ["pct must be a finite number in (0, 50]"]

    def to_dict(self) -> dict:
        return {"pct": self.pct}


@dataclass(frozen=True)
class Efficiency:
    """I-D5: one canonical value with its unit (fraction | percent) and basis (ROUND_TRIP | ONE_WAY). It reaches
    SiteConfig.round_trip_efficiency through efficiency_round_trip."""
    value: float
    unit: str
    basis: str
    name: str = "I-D5"

    def problems(self) -> list[str]:
        bad = efficiency_round_trip(self)[2]
        return [] if bad is None else [f"{bad.code}: {bad.text}"]

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "basis": self.basis}


@dataclass(frozen=True)
class FreshnessOverrides:
    """I-D6: per signal or gate reading, a maximum age in seconds. Tighten-only for a defined limit; at most the ceiling for
    an unresolved one; unknown keys refused."""
    limits_s: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.limits_s, Mapping):
            raise ValueError("limits_s must be a mapping")
        object.__setattr__(self, "limits_s", MappingProxyType(dict(self.limits_s)))

    def entry_problems(self) -> list[tuple[str, str, str]]:
        """(key, code, text) per refused entry."""
        out = []
        for key, v in sorted(self.limits_s.items(), key=lambda kv: str(kv[0])):
            if key not in FRESHNESS_OVERRIDE_KEYS:
                out.append((str(key), "FRESHNESS_OVERRIDE_UNKNOWN_KEY",
                            f"{key!r} is not a known advisory signal or gate reading"))
                continue
            n = _num(v)
            if n is None or n <= 0.0:
                out.append((key, "FRESHNESS_OVERRIDE_INVALID", "an override must be a positive finite number of seconds"))
                continue
            defined = ADVISORY_LIMITS_S.get(key)
            if defined is not None and n > defined:
                out.append((key, "FRESHNESS_OVERRIDE_REFUSED", f"an override may tighten the defined {defined:g} s limit, "
                                                                f"never loosen it (requested {n:g} s)"))
            elif defined is None and n > PROPOSED_FRESHNESS_CEILING_S:
                out.append((key, "FRESHNESS_OVERRIDE_ABOVE_CEILING", f"{n:g} s is above the {PROPOSED_FRESHNESS_CEILING_S:g} s "
                                                                      "ceiling for a signal with no defined limit"))
        return out

    def problems(self) -> list[str]:
        return [f"{code} {key}: {text}" for key, code, text in self.entry_problems()]

    def to_dict(self) -> dict:
        return {"limits_s": dict(sorted(self.limits_s.items()))}


@dataclass(frozen=True)
class RequiredInputsOverride:
    """I-D7 (retired): an add-only site extension of REQUIRED_SIGNALS / REQUIRED_READINGS, per item."""
    add_signals: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    add_readings: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("add_signals", "add_readings"):
            v = getattr(self, name)
            if not isinstance(v, Mapping):
                raise ValueError(f"{name} must be a mapping of item -> list")
            object.__setattr__(self, name, MappingProxyType({k: tuple(x) if isinstance(x, (list, tuple)) else x
                                                             for k, x in v.items()}))

    def problems(self) -> list[str]:
        out = []
        for name, known in (("add_signals", lambda s: spec_for(s) is not None),
                            ("add_readings", lambda r: r in GATE_READING_KEYS)):
            for item, keys in getattr(self, name).items():
                if item not in ITEMS:
                    out.append(f"{name}: unknown item {item!r}")
                elif not isinstance(keys, tuple) or not all(isinstance(k, str) and known(k) for k in keys):
                    out.append(f"{name}[{item}]: every entry must be a known " + ("signal" if name == "add_signals" else "reading"))
        return out

    def to_dict(self) -> dict:
        return {"add_signals": {k: list(v) for k, v in sorted(self.add_signals.items())},
                "add_readings": {k: list(v) for k, v in sorted(self.add_readings.items())}}


@dataclass(frozen=True)
class HD1Cutover:
    """I-D8. `cutover` (aware) is the site fact; both KEEP options need a counter-check evidence reference."""
    cutover: datetime
    load_power_policy: str
    load_counter_policy: str
    counter_check_evidence_ref: str | None = None

    def problems(self) -> list[str]:
        out = []
        if not _aware(self.cutover):
            out.append("cutover must be an aware date-time")
        if self.load_power_policy not in LOAD_POWER_POLICIES:
            out.append(f"load_power_policy {self.load_power_policy!r} is not one of {LOAD_POWER_POLICIES}")
        if self.load_counter_policy not in LOAD_COUNTER_POLICIES:
            out.append(f"load_counter_policy {self.load_counter_policy!r} is not one of {LOAD_COUNTER_POLICIES}")
        keeps = self.load_power_policy == KEEP_NON_EXPORTING_ONLY or self.load_counter_policy == KEEP_AFTER_COUNTER_CHECK
        ref = self.counter_check_evidence_ref
        if keeps and not _ref_ok(ref):
            out.append("a KEEP option needs counter_check_evidence_ref matching REC-YYYYMMDD-<slug>")
        elif ref is not None and not _ref_ok(ref):
            out.append("counter_check_evidence_ref must match REC-YYYYMMDD-<slug>")
        return out

    def to_dict(self) -> dict:
        return {"cutover": _jsonable(self.cutover), "load_power_policy": self.load_power_policy,
                "load_counter_policy": self.load_counter_policy,
                "counter_check_evidence_ref": self.counter_check_evidence_ref}


@dataclass(frozen=True)
class DSTPolicy:
    """I-D9: how history from a changed period is learned and how a changed target period is planned. Fixed rule
    regardless: a period boundary in a repeated or missing hour BLOCKs."""
    history_rule: str
    target_rule: str

    def problems(self) -> list[str]:
        out = []
        if self.history_rule not in DST_HISTORY_RULES:
            out.append(f"history_rule {self.history_rule!r} is not one of {DST_HISTORY_RULES}")
        if self.target_rule not in DST_TARGET_RULES:
            out.append(f"target_rule {self.target_rule!r} is not one of {DST_TARGET_RULES}")
        return out

    def to_dict(self) -> dict:
        return {"history_rule": self.history_rule, "target_rule": self.target_rule}


VALUE_TYPES: Mapping[str, type] = MappingProxyType({
    "D1": PlanningFloor, "D2": Protection, "D3": CapacityAuthority, "D4": CapacityBand, "D5": Efficiency,
    "D6": FreshnessOverrides, "D7": RequiredInputsOverride, "D8": HD1Cutover, "D9": DSTPolicy,
})


def efficiency_round_trip(d) -> tuple[float | None, float | None, Finding | None]:
    """(round-trip fraction, one-way fraction, a finding when unusable) for any object with value / unit / basis
    (and optionally name). Unit 'fraction' or 'percent'; basis ROUND_TRIP or ONE_WAY. Fail closed."""
    name = getattr(d, "name", "efficiency")
    v = _num(d.value)
    if v is None:
        return None, None, finding("EFFICIENCY_VALUE_MISSING", BLOCK, name, "no finite value declared")
    if d.unit not in EFFICIENCY_UNITS:
        return None, None, finding("EFFICIENCY_UNIT_UNSTATED", BLOCK, name, "unit must be stated as fraction or percent")
    frac = v / 100.0 if d.unit == PERCENT else v
    if (d.unit == FRACTION and v > 1.0) or (d.unit == PERCENT and v <= 1.0):
        return None, None, finding("EFFICIENCY_UNIT_MISMATCH", BLOCK, name,
                                   "the number does not fit the stated unit (a fraction above 1, or a percentage of 1 or less)",
                                   value=v, unit=d.unit)
    if not 0.5 <= frac <= 1.0:
        return None, None, finding("EFFICIENCY_OUT_OF_RANGE", BLOCK, name, "outside the plausible efficiency range",
                                   fraction=round(frac, 4), lower=0.5, upper=1.0)
    if d.basis not in EFFICIENCY_BASES:
        return None, None, finding("EFFICIENCY_BASIS_UNSTATED", BLOCK, name,
                                   "the basis (ROUND_TRIP or ONE_WAY) must be stated; the engine applies sqrt(round-trip) each way")
    if d.basis == ROUND_TRIP:
        return frac, math.sqrt(frac), None
    return frac * frac, frac, None


# ---- strict parsing of a value mapping -------------------------------------------------------------------------------

def _value_from_mapping(did: str, raw: object) -> object:
    """A typed value from its JSON form. Unknown keys raise ValueError (refused). A value of the wrong shape (free text,
    a bare number) is returned as-is so that the decision becomes INVALID, never RECORDED."""
    cls = VALUE_TYPES[did]
    if not isinstance(raw, Mapping):
        return raw
    allowed = [f.name for f in fields(cls) if not (cls is Efficiency and f.name == "name")]
    _strict_keys(raw, allowed, f"{display_label(did)} value")
    kw = dict(raw)
    if did == "D2" and "observed_at" in kw:
        kw["observed_at"] = _parse_dt(kw["observed_at"], "observed_at")
    if did == "D8" and "cutover" in kw:
        kw["cutover"] = _parse_dt(kw["cutover"], "cutover")
    if did == "D6":
        if not isinstance(kw.get("limits_s"), Mapping):
            return raw
    if did == "D7":
        for k in ("add_signals", "add_readings"):
            if k in kw and not isinstance(kw[k], Mapping):
                return raw
            if k in kw:
                kw[k] = {i: tuple(x) if isinstance(x, list) else x for i, x in kw[k].items()}
    try:
        return cls(**kw)
    except TypeError:
        return raw                        # a required field is missing: an incomplete record is INVALID


# ---------------------------------------------------------------------------------------------------------------------
# Decision and DecisionSet
# ---------------------------------------------------------------------------------------------------------------------

def _record_problems(did: str, value: object, provenance: object, record_ref: object) -> list[str]:
    """Why (did, value, provenance, record_ref) cannot be a RECORDED decision; [] when it can. The invariants live on the
    type: a RECORDED decision always has a valid typed value, a known provenance and, for an OWNER_RECORD, a valid
    record reference (the site-local source is enforced by DecisionSet)."""
    out: list[str] = []
    cls = VALUE_TYPES[did]
    if not isinstance(value, cls):
        out.append(f"the value must be a typed {cls.__name__} record; free text or a bare number is never recorded")
    else:
        try:
            out += value.problems()
        except (TypeError, ValueError) as exc:                  # a malformed field inside the record
            out.append(f"malformed {cls.__name__}: {exc}")
    if provenance not in Provenance.ALL:
        out.append(f"provenance {provenance!r} is not one of {Provenance.ALL}")
    elif provenance == Provenance.OWNER_RECORD and not _ref_ok(record_ref):
        out.append("an OWNER_RECORD needs record_ref matching REC-YYYYMMDD-<slug>")
    if record_ref is not None and not _ref_ok(record_ref) and provenance != Provenance.OWNER_RECORD:
        out.append("record_ref must match REC-YYYYMMDD-<slug>")
    return out


@dataclass(frozen=True)
class Decision:
    """One decision. The invariants are enforced here, so no code path can build a RECORDED decision that the loader would
    refuse: RECORDED needs a valid typed value, a known provenance and (OWNER_RECORD) a valid record_ref; OPEN carries
    nothing; INVALID names its problems."""
    id: str
    status: str
    value: object = None
    provenance: str | None = None
    record_ref: str | None = None
    problems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.id not in DECISION_IDS:
            raise ValueError(f"unknown decision id {self.id!r}")
        if self.status not in DecisionStatus.ALL:
            raise ValueError(f"unknown decision status {self.status!r}")
        object.__setattr__(self, "problems", tuple(self.problems))
        if self.status == DecisionStatus.RECORDED:
            bad = list(self.problems) + _record_problems(self.id, self.value, self.provenance, self.record_ref)
            if bad:
                raise ValueError("a RECORDED decision carries a valid typed value, a known provenance (an OWNER_RECORD "
                                 "with a valid record_ref) and no problem: " + "; ".join(bad))
        if self.status == DecisionStatus.OPEN and (self.value is not None or self.provenance is not None
                                                   or self.record_ref is not None or self.problems):
            raise ValueError("an OPEN decision carries no value, provenance, record_ref or problem")
        if self.status == DecisionStatus.INVALID and not self.problems:
            raise ValueError("an INVALID decision names at least one problem")

    @property
    def label(self) -> str:
        return display_label(self.id)

    @property
    def title(self) -> str:
        return DECISION_TITLES[self.id]

    def recorded_json(self) -> object:
        """The typed value as plain JSON data (None unless RECORDED)."""
        return self.value.to_dict() if self.status == DecisionStatus.RECORDED else None

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "status": self.status, "provenance": self.provenance,
                "record_ref": self.record_ref, "value": self.recorded_json(), "problems": list(self.problems)}


def open_decision(did: str) -> Decision:
    return Decision(did, DecisionStatus.OPEN)


def _decide(did: str, value: object, provenance: str, record_ref: str | None, source: str, *,
            from_site_file: bool) -> Decision:
    did = normalise_id(did) or did
    if did not in DECISION_IDS:
        raise ValueError(f"unknown decision id {did!r}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    probs: list[str] = []
    if provenance == Provenance.OWNER_RECORD:
        if source != SOURCE_SITE_LOCAL:
            probs.append("an OWNER_RECORD is accepted only from the site-local decisions file")
        elif not from_site_file:
            probs.append("an OWNER_RECORD is accepted only by DecisionSet.from_mapping(..., source='site_local'), "
                         "never built in code")
    probs += _record_problems(did, value, provenance, record_ref)
    cls = VALUE_TYPES[did]
    if probs:
        return Decision(did, DecisionStatus.INVALID, value if isinstance(value, cls) else None,
                        provenance if provenance in Provenance.ALL else None,
                        record_ref if isinstance(record_ref, str) else None, tuple(probs))
    return Decision(did, DecisionStatus.RECORDED, value, provenance, record_ref)


def decide(did: str, value: object, provenance: str, record_ref: str | None = None,
           source: str = "test") -> Decision:
    """A decision from a typed value (tests and declarations): RECORDED when the value is the right type and valid and the
    provenance is known, otherwise INVALID with the reasons. An OWNER_RECORD is never RECORDED here: only the strict loader
    of the site-local file (DecisionSet.from_mapping(..., source='site_local')) can carry one. Never raises for a bad
    value."""
    return _decide(did, value, provenance, record_ref, source, from_site_file=False)


def satisfied(decision: Decision | None, accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> bool:
    """True only when the decision is RECORDED, still valid (the record is re-checked, so a mutated object never counts)
    and its provenance is accepted (default: OWNER_RECORD only)."""
    acc = frozenset(accept_provenance)
    return (isinstance(decision, Decision) and decision.status == DecisionStatus.RECORDED and decision.provenance in acc
            and not decision.problems
            and not _record_problems(decision.id, decision.value, decision.provenance, decision.record_ref))


_ENTRY_KEYS = ("status", "provenance", "record_ref", "value")


@dataclass(frozen=True)
class DecisionSet:
    """All nine decisions (missing ones are OPEN). Immutable. Build it with from_mapping (a site or example file) or with
    with_decision (tests and declarations)."""
    decisions: Mapping[str, Decision] = field(default_factory=dict)
    source: str = "test"

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        got = dict(self.decisions)
        for k, d in got.items():
            if k not in DECISION_IDS or not isinstance(d, Decision) or d.id != k:
                raise ValueError(f"decision key {k!r} does not match its decision")
            if (d.status == DecisionStatus.RECORDED and d.provenance == Provenance.OWNER_RECORD
                    and self.source != SOURCE_SITE_LOCAL):
                raise ValueError(f"{display_label(k)}: an OWNER_RECORD decision belongs only to the site-local "
                                 f"DecisionSet, not to source {self.source!r}")
        for did in DECISION_IDS:
            got.setdefault(did, open_decision(did))
        object.__setattr__(self, "decisions", MappingProxyType({did: got[did] for did in DECISION_IDS}))

    def get(self, did: str) -> Decision:
        key = normalise_id(did)
        if key is None:
            raise ValueError(f"unknown decision id {did!r}")
        return self.decisions[key]

    def status(self, did: str) -> str:
        return self.get(did).status

    def value(self, did: str) -> object:
        return self.get(did).value

    def satisfied(self, did: str, accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> bool:
        d = self.get(did)
        return satisfied(d, accept_provenance) and (d.provenance != Provenance.OWNER_RECORD
                                                    or self.source == SOURCE_SITE_LOCAL)

    def with_decision(self, did: str, value: object, provenance: str, record_ref: str | None = None) -> "DecisionSet":
        """A copy with one decision built by `decide` (tests and declarations; an OWNER_RECORD is INVALID here)."""
        d = decide(did, value, provenance, record_ref, self.source)
        return DecisionSet({**self.decisions, d.id: d}, self.source)

    def without(self, did: str) -> "DecisionSet":
        key = normalise_id(did)
        if key is None:
            raise ValueError(f"unknown decision id {did!r}")
        return DecisionSet({**self.decisions, key: open_decision(key)}, self.source)

    def recorded(self) -> tuple[Decision, ...]:
        return tuple(d for d in self.decisions.values() if d.status == DecisionStatus.RECORDED)

    def status_map(self) -> dict[str, str]:
        """{"I-D1": "OPEN", ...}: what a display shows."""
        return {display_label(did): d.status for did, d in self.decisions.items()}

    def provenance_ok(self, accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> bool:
        """True when every RECORDED decision's provenance is accepted (vacuously true when none is recorded)."""
        acc = frozenset(accept_provenance)
        return all(d.provenance in acc for d in self.recorded())

    def to_dict(self) -> dict:
        return {"register_version": REGISTER_VERSION, "source": self.source,
                "decisions": {display_label(did): d.to_dict() for did, d in self.decisions.items()}}

    @staticmethod
    def from_mapping(mapping: Mapping, *, source: str) -> "DecisionSet":
        """Strict loader for a decisions block, keyed D<n> or I-D<n>:

            {"I-D4": {"status": "RECORDED", "provenance": "OWNER_RECORD", "record_ref": "REC-20301015-band",
                      "value": {"pct": 8.0}},
             "I-D9": {"status": "OPEN"}}

        Unknown keys (top level, per entry, inside a value) raise ValueError. An id given twice (D1 and I-D1) raises. A
        value of the wrong shape, an incomplete record, an unknown provenance, or an OWNER_RECORD from any source but the
        site-local file / without a valid record_ref makes that decision INVALID. No file I/O."""
        if not isinstance(mapping, Mapping):
            raise ValueError("a decisions block must be a mapping")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        out: dict[str, Decision] = {}
        for key, entry in mapping.items():
            did = normalise_id(key)
            if did is None:
                if isinstance(key, str) and key.startswith("_"):
                    continue                  # "_comment" style keys are documentation
                raise ValueError(f"decisions: unknown key {key!r} (expected D1..D9 or I-D1..I-D9)")
            if did in out:
                raise ValueError(f"decisions: {display_label(did)} is given twice")
            if not isinstance(entry, Mapping):
                raise ValueError(f"decisions: {key} must be an object with status / provenance / value")
            _strict_keys(entry, _ENTRY_KEYS + ("_note",), f"decisions: {key}")
            status = entry.get("status", DecisionStatus.RECORDED if entry.get("value") is not None else DecisionStatus.OPEN)
            value = entry.get("value")
            if status == DecisionStatus.OPEN:
                if value is not None or entry.get("provenance") is not None:
                    out[did] = Decision(did, DecisionStatus.INVALID, None, None, None,
                                        ("an OPEN decision carries no value and no provenance",))
                else:
                    out[did] = open_decision(did)
                continue
            if status != DecisionStatus.RECORDED:
                out[did] = Decision(did, DecisionStatus.INVALID, None, None, None,
                                    (f"status {status!r} cannot be declared (OPEN or RECORDED)",))
                continue
            typed = _value_from_mapping(did, value)
            out[did] = _decide(did, typed, entry.get("provenance"), entry.get("record_ref"), source, from_site_file=True)
        return DecisionSet(out, source)


# ---------------------------------------------------------------------------------------------------------------------
# PROPOSED answers (text only; never applied, never loadable)
# ---------------------------------------------------------------------------------------------------------------------

PROPOSED_ANSWERS_STATUS = "PROPOSED_PENDING_OWNER"
PROPOSED_ANSWERS: Mapping[str, str] = MappingProxyType({
    "I-D4": "PROPOSED_PENDING_OWNER (not an owner decision): capacity mismatch band 8.0 % of the mean of the two sources.",
    "I-D6": "PROPOSED_PENDING_OWNER (not an owner decision): 300 s for every dongle signal and gate reading, judged by "
            "the poll-text liveness time, within the 900 s ceiling.",
    "I-D8": "PROPOSED_PENDING_OWNER (not an owner decision): load power policy EXCLUDE and load counter policy "
            "EXCLUDE_PRE_CUTOVER (drop pre-cut-over load history until a counter check exists).",
    "I-D9": "PROPOSED_PENDING_OWNER (not an owner decision): history rule NORMALISE_TO_NOMINAL and target rule "
            "SCALE_UP_ONLY (normalise a 25 h / 23 h night to its nominal length; never plan a changed night below an "
            "ordinary one).",
})


# ---------------------------------------------------------------------------------------------------------------------
# freshness limits
# ---------------------------------------------------------------------------------------------------------------------

def freshness_limits(decisions: DecisionSet, accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE
                     ) -> tuple[Mapping[str, float | None], list[Finding]]:
    """The advisory limit per signal and gate reading: the mirror of the defined catalogue, every gate reading UNRESOLVED
    (None: never fresh), tightened / supplied by a SATISFIED I-D6 only (FreshnessPolicy semantics: tighten-only for a
    defined limit, unknown keys refused, at most PROPOSED_FRESHNESS_CEILING_S for an unresolved one). An INVALID I-D6
    applies nothing and BLOCKs. Date-scoped readings (forecasts) carry no age limit (see DATE_SCOPED_READINGS)."""
    limits: dict[str, float | None] = dict(ADVISORY_LIMITS_S)
    for k in GATE_READING_KEYS:
        if k not in DATE_SCOPED_READINGS and k != LIVENESS_KEY:
            limits.setdefault(k, None)
    for k in PLANNING_READING_KEYS:
        limits.setdefault(k, None)
    notes: list[Finding] = []
    d6 = decisions.get("D6")
    if d6.status == DecisionStatus.INVALID:
        if isinstance(d6.value, FreshnessOverrides):
            for key, code, text in d6.value.entry_problems():
                notes.append(finding(code, WARN if code == "FRESHNESS_OVERRIDE_REFUSED" else BLOCK, key, text))
        notes.append(finding("DECISION_D6_INVALID", BLOCK, "I-D6",
                             "the freshness overrides are invalid, so none is applied: " + "; ".join(d6.problems)))
    elif d6.status == DecisionStatus.RECORDED and d6.provenance in frozenset(accept_provenance):
        # re-check every entry before applying anything: a record is trusted only as far as it re-validates
        entries = (d6.value.entry_problems() if isinstance(d6.value, FreshnessOverrides)
                   else [("I-D6", "FRESHNESS_OVERRIDE_INVALID", "the value is not a FreshnessOverrides record")])
        if entries or not decisions.satisfied("D6", accept_provenance):
            for key, code, text in entries:
                notes.append(finding(code, BLOCK, key, text))
            notes.append(finding("DECISION_D6_INVALID", BLOCK, "I-D6",
                                 "the recorded freshness overrides do not re-validate, so none is applied"))
        else:
            for key, v in d6.value.limits_s.items():
                limits[key] = float(v)
    return MappingProxyType(limits), notes


# ---------------------------------------------------------------------------------------------------------------------
# gates and required inputs
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class GateContext:
    """What a gate needs to know beyond the decisions (computed by the caller from its inputs)."""
    capacity_sources: int = 0                    # usable capacity sources present (readings and stated values)
    capacity_mismatch_pct: float | None = None   # largest pairwise |a-b| / mean in percent, when two or more exist
    clock_change_in_scope: bool = False          # a period, or a learning period within the lookback, crosses a change
    boundary_in_changed_hour: bool = False       # a period boundary falls in a repeated or missing local hour


@dataclass(frozen=True)
class RequiredInputs:
    signals: tuple[str, ...]
    readings: tuple[str, ...]
    site_facts: tuple[str, ...]
    charge_window_sources: tuple[str, ...]       # any one of these, in order of preference; empty = not needed


def _decision_finding(did: str, d: Decision, item: str, accept: frozenset) -> Finding:
    lab = display_label(did)
    if d.status == DecisionStatus.INVALID:
        return finding(f"DECISION_{did}_INVALID", BLOCK, item,
                       f"{lab} ({DECISION_TITLES[did]}) is INVALID: " + "; ".join(d.problems), decision=lab)
    if d.status == DecisionStatus.RECORDED and (d.problems or _record_problems(did, d.value, d.provenance, d.record_ref)):
        return finding(f"DECISION_{did}_INVALID", BLOCK, item,
                       f"{lab} ({DECISION_TITLES[did]}) is recorded but its record does not re-validate", decision=lab)
    why = "OPEN" if d.status == DecisionStatus.OPEN else f"recorded with provenance {d.provenance}, which is not accepted here"
    return finding(f"DECISION_{did}_OPEN", BLOCK, item,
                   f"{lab} ({DECISION_TITLES[did]}) is {why}; this item depends on it and is withheld", decision=lab)


def gate(item: str, decisions: DecisionSet, context: GateContext = GateContext(),
         accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> list[Finding]:
    """BLOCK findings for every decision the item needs that is not satisfied (an unaccepted provenance counts as OPEN),
    plus the conditional I-D4 / I-D9 gates (with two or more capacity sources a mismatch beyond the band, or one that
    cannot be computed, BLOCKs), the fixed DST boundary rule, and every INVALID decision that can gate the item at all
    (items_gated_by: unconditional and conditional; an INVALID I-D7 blocks every item). INVALID always BLOCKs. Empty = not
    blocked by decisions (inputs are judged separately)."""
    if item not in ITEM_GATES:
        raise ValueError(f"unknown item {item!r}")
    acc = frozenset(accept_provenance)
    out: list[Finding] = []
    needed = list(ITEM_GATES[item])
    if item in CONDITIONAL_D4_ITEMS and context.capacity_sources >= 2:
        needed.append("D4")
    if item in CONDITIONAL_D9_ITEMS and context.clock_change_in_scope:
        needed.append("D9")
    for did in needed:
        d = decisions.get(did)
        if not decisions.satisfied(did, acc):
            out.append(_decision_finding(did, d, item, acc))
    if "D4" in needed and decisions.satisfied("D4", acc):
        band = decisions.value("D4").pct
        if context.capacity_mismatch_pct is None:
            out.append(finding("CAPACITY_MISMATCH_UNKNOWN", BLOCK, item,
                               "two or more capacity sources are present and their agreement cannot be computed (a source "
                               "lacks a unit conversion), so the I-D4 band cannot be checked", sources=context.capacity_sources))
        elif not finite_number(context.capacity_mismatch_pct) or context.capacity_mismatch_pct > band:
            out.append(finding("CAPACITY_MISMATCH_BEYOND_BAND", BLOCK, item,
                               "the capacity sources disagree beyond the recorded I-D4 band",
                               difference_pct=context.capacity_mismatch_pct, band_pct=band))
    if item in CONDITIONAL_D9_ITEMS and context.boundary_in_changed_hour:
        out.append(finding("DST_BOUNDARY_IN_CHANGED_HOUR", BLOCK, item,
                           "a period boundary falls in a repeated or missing local hour (fixed rule, whatever I-D9 says)"))
    for did in DECISION_IDS:
        if did in needed or decisions.status(did) != DecisionStatus.INVALID:
            continue
        if did == "D7" or item in items_gated_by(did):
            out.append(_decision_finding(did, decisions.get(did), item, acc))
    return out


def required_inputs(item: str, decisions: DecisionSet,
                    accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> RequiredInputs:
    """The inputs that must be present and fresh for `item`: the code constants, the readings the chosen I-D1 / I-D2 /
    I-D3 sources bring, the dongle liveness reading whenever a dongle-sourced input is needed, and any recorded I-D7
    additions (add-only, so applied whatever their provenance)."""
    if item not in ITEM_GATES:
        raise ValueError(f"unknown item {item!r}")
    acc = frozenset(accept_provenance)
    sig = list(REQUIRED_SIGNALS[item])
    rd = list(REQUIRED_READINGS[item])
    gates = ITEM_GATES[item]
    if "D1" in gates and decisions.satisfied("D1", acc):
        src = decisions.value("D1").source
        if src == HA_RESERVE_HELPER:
            sig.append("reserve.ha_minimum_soc")
        elif src == FEATURE_STOP_LEVEL:
            rd.append("stop.dump_soc_pct")
    if "D2" in gates and decisions.satisfied("D2", acc) and decisions.value("D2").supplied_by == READ_ONLY_SENSOR_SNAPSHOT:
        rd.append("protection.shutdown_soc_pct")
    if "D3" in gates and decisions.satisfied("D3", acc) and decisions.value("D3").resolve_at_run:
        rd.append(CAPACITY_READING_BY_KIND[decisions.value("D3").kind])
    d7 = decisions.get("D7")
    if d7.status == DecisionStatus.RECORDED:
        sig += list(d7.value.add_signals.get(item, ()))
        rd += list(d7.value.add_readings.get(item, ()))
    if any(s in DONGLE_SIGNALS for s in sig) or any(r in DONGLE_READINGS for r in rd):
        rd.append(LIVENESS_KEY)
    cw = CHARGE_WINDOW_SOURCES if item in CHARGE_WINDOW_ITEMS else ()
    return RequiredInputs(tuple(dict.fromkeys(sig)), tuple(dict.fromkeys(rd)), REQUIRED_SITE_FACTS.get(item, ()), cw)


def clock_change_in_scope(now: datetime, periods: Iterable[tuple[datetime, datetime]], lookback_nights: int,
                          tz: str = DEFAULT_TZ) -> bool:
    """True when any (start, end) period, or the learning lookback [now - lookback_nights days, now), crosses a clock
    change. The caller passes OvernightSettings.lookback_nights (28 by default)."""
    if not _aware(now):
        raise ValueError("now must be an aware datetime")
    if isinstance(lookback_nights, bool) or not isinstance(lookback_nights, int) or lookback_nights < 0:
        raise ValueError("lookback_nights must be a non-negative int")
    if clock_changes(now - timedelta(days=lookback_nights), now, tz):
        return True
    for a, b in periods:
        if clock_changes(a, b, tz):
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------------
# applying decisions to a SiteConfig (no fallbacks)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class InputState:
    """One judged input (by the quality layer): its value and whether it is fresh under a defined limit."""
    key: str
    value: object
    fresh: bool
    age_s: float | None = None
    limit_s: float | None = None

    @property
    def usable_number(self) -> float | None:
        return float(self.value) if self.fresh and self.limit_s is not None and finite_number(self.value) else None


def _reading(readings: Mapping[str, InputState], key: str) -> float | None:
    st = readings.get(key)
    return None if st is None or not isinstance(st, InputState) else st.usable_number


def _charge_window(readings: Mapping[str, InputState]) -> tuple[int, int] | None:
    """The fresh (start_min, end_min) of CHARGE_WINDOW_KEY: ints with 0 <= start < end <= 1440, judged fresh under a
    defined limit; anything else is None."""
    st = readings.get(CHARGE_WINDOW_KEY)
    if not isinstance(st, InputState) or not st.fresh or st.limit_s is None:
        return None
    v = st.value
    if not (isinstance(v, (tuple, list)) and len(v) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in v)):
        return None
    s, e = int(v[0]), int(v[1])
    return (s, e) if 0 <= s < e <= 1440 else None


def apply_to_siteconfig(base_cfg: SiteConfig, decisions: DecisionSet, readings: Mapping[str, InputState],
                        accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE
                        ) -> tuple[SiteConfig | None, list[Finding]]:
    """A SiteConfig whose battery and charge-window fields come ONLY from satisfied decisions and fresh readings, or None
    with the reasons.

    Never keeps the shipped example capacity, round-trip efficiency, 40 % reserve, 8 kW grid-charge limit or cheap window:
    every one of those fields is replaced (dataclasses.replace) or the result is None. I-D2 only raises the technical
    minimum above the placeholder; with a sensor snapshot a missing / stale / non-numeric reading BLOCKs
    (PHYSICAL_PROTECTION_UNKNOWN), never falls back. The cheap window comes from `readings[CHARGE_WINDOW_KEY]`, the window
    the planning layer derived from a charge-window source (a VERIFIED tariff, else the read-only TOU slot table); without
    a fresh one the result is None (CHARGE_WINDOW_UNKNOWN)."""
    acc = frozenset(accept_provenance)
    out: list[Finding] = []
    for did in ("D1", "D2", "D3", "D5"):
        d = decisions.get(did)
        if not decisions.satisfied(did, acc):
            out.append(_decision_finding(did, d, "site_config", acc))
    if blocking(out):
        return None, out

    # I-D2: protection, raise-only above the placeholder
    prot = decisions.value("D2")
    if prot.supplied_by == OWNER_STATEMENT:
        prot_pct = float(prot.value_pct)
    else:
        prot_pct = _reading(readings, "protection.shutdown_soc_pct")
        if prot_pct is None or not 0.0 <= prot_pct <= 100.0:
            out.append(finding("PHYSICAL_PROTECTION_UNKNOWN", BLOCK, "protection.shutdown_soc_pct",
                               "I-D2 reads the protection level from the read-only sensor, and no fresh finite reading is "
                               "available; the placeholder is never used instead"))
            prot_pct = None
    technical_min = None if prot_pct is None else max(DEFAULT_TECHNICAL_MIN_SOC_PCT, prot_pct)

    # I-D1: the planning floor
    floor = decisions.value("D1")
    user_reserve: float | None = None
    if floor.source in FLOOR_SOURCES_WITH_VALUE:
        user_reserve = float(floor.value_pct)
    elif floor.source == HA_RESERVE_HELPER:
        helper = _reading(readings, "reserve.ha_minimum_soc")
        if helper is None:
            out.append(finding("RESERVE_HELPER_NOT_FRESH", BLOCK, "reserve.ha_minimum_soc",
                               "I-D1 makes the Home Assistant helper the floor, and no fresh finite helper value with a "
                               "defined freshness limit is available"))
        elif not 0.0 <= helper <= 100.0:
            out.append(finding("RESERVE_HELPER_OUT_OF_RANGE", BLOCK, "reserve.ha_minimum_soc",
                               "the Home Assistant helper value is not a percentage in 0..100", value=helper))
        else:
            user_reserve = technical_min       # the helper enters at run time (ha_reserve_pct) and can only raise it
    elif floor.source == FEATURE_STOP_LEVEL:
        stop = _reading(readings, "stop.dump_soc_pct")
        if stop is None or not 0.0 <= stop <= 100.0:
            out.append(finding("FEATURE_STOP_NOT_FRESH", BLOCK, "stop.dump_soc_pct",
                               "I-D1 makes the feature stop level the floor, and no fresh finite stop level is available"))
        else:
            user_reserve = stop
    out.append(finding("PLANNING_FLOOR_ADVICE_HONOURS" if floor.advice_honours else "PLANNING_FLOOR_DISPLAY_ONLY", INFO,
                       "I-D1", "advice honours the planning floor" if floor.advice_honours else
                       "the planning floor is displayed, not honoured by precharge / export / Dump advice; firmware "
                       "features honour no floor in any case"))

    # I-D3: capacity
    cap_d = decisions.value("D3")
    capacity: float | None = None
    if not cap_d.resolve_at_run:
        capacity = float(cap_d.value_kwh)
    else:
        key = CAPACITY_READING_BY_KIND[cap_d.kind]
        raw = _reading(readings, key)
        if raw is not None and raw > 0:
            if cap_d.kind == "CONFIGURED_HELPER":
                capacity = raw
            elif cap_d.kind == "LEARNED_FROM_DISCHARGE":
                capacity = raw * 100.0 / 1000.0            # Wh per SOC percent -> kWh for 100 %
            else:
                capacity = raw * float(cap_d.nominal_voltage_v) / 1000.0
        lo, hi = PROPOSED.capacity_plausible_kwh
        if capacity is None or not lo <= capacity <= hi:
            out.append(finding("CAPACITY_READING_NOT_USABLE", BLOCK, key,
                               "I-D3 resolves the capacity at run time and no fresh, finite, plausible reading is available"))
            capacity = None

    # I-D5: efficiency
    rt, _ow, bad = efficiency_round_trip(decisions.value("D5"))
    if bad is not None:                                        # cannot happen for a RECORDED I-D5; kept fail closed
        out.append(bad)

    # the grid-charge limit is a reading, never the example 8 kW
    gw = _reading(readings, "limits.max_grid_charge_w")
    if gw is None or gw <= 0:
        out.append(finding("GRID_CHARGE_LIMIT_UNKNOWN", BLOCK, "limits.max_grid_charge_w",
                           "no fresh finite grid-charge limit is available; the example limit is never used"))
        gw = None

    # the cheap window: from a charge-window source, never the example window
    window = _charge_window(readings)
    if window is None:
        out.append(finding("CHARGE_WINDOW_UNKNOWN", BLOCK, CHARGE_WINDOW_KEY,
                           "no fresh charge window derived from a charge-window source (a verified tariff, else the "
                           "read-only TOU slot table); the example window is never kept"))

    if blocking(out) or None in (technical_min, user_reserve, capacity, rt, gw, window):
        return None, out
    try:
        cfg = replace(base_cfg, user_reserve_soc_pct=float(user_reserve), technical_min_soc_pct=float(technical_min),
                      battery_capacity_kwh=float(capacity), round_trip_efficiency=float(rt),
                      max_grid_charge_kw=float(gw) / 1000.0, cheap_window_start_min=window[0],
                      cheap_window_end_min=window[1])
    except (TypeError, ValueError) as exc:
        out.append(finding("SITECONFIG_INVALID", BLOCK, "site_config", "the decided values do not form a valid site configuration",
                           error_type=type(exc).__name__, error=str(exc)))
        return None, out
    out.append(finding("CHARGE_WINDOW_FROM_SOURCE", INFO, "site_config",
                       "the cheap window comes from the charge-window source the planning layer judged, not the example",
                       start_min=window[0], end_min=window[1]))
    return cfg, out


def capacity_context(values_kwh: Iterable[float]) -> tuple[int, float | None]:
    """(number of usable capacity sources, largest pairwise symmetric difference in percent or None). The values must
    already be in kWh: use capacity_sources_context for readings in their own units."""
    vs = [float(v) for v in values_kwh if finite_number(v) and v > 0]
    worst = None
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            rel = abs(vs[i] - vs[j]) / ((vs[i] + vs[j]) / 2.0) * 100.0
            worst = rel if worst is None else max(worst, rel)
    return len(vs), worst


def capacity_sources_context(decisions: DecisionSet, readings: Mapping[str, InputState],
                             accept_provenance: Iterable[str] = DEFAULT_ACCEPT_PROVENANCE) -> tuple[int, float | None]:
    """(capacity sources PRESENT, largest pairwise symmetric difference in percent or None) for the conditional I-D4 gate.

    A source is present when it exists, fresh or not: a satisfied I-D3 stated value_kwh, and every capacity reading with a
    finite positive value. Each is converted to kWh before comparing: capacity.helper_kwh as is, capacity.fe1_wh_per_pct
    x 100 / 1000, capacity.reg204_ah x the nominal voltage stated in a satisfied I-D3 / 1000. A source that cannot be
    converted (an Ah reading without a stated voltage) still counts, and makes the difference None (unknown), which the
    gate BLOCKs when two or more sources are present."""
    acc = frozenset(accept_provenance)
    kwh: list[float | None] = []
    cap = decisions.value("D3") if decisions.satisfied("D3", acc) else None
    if isinstance(cap, CapacityAuthority) and not cap.resolve_at_run and finite_number(cap.value_kwh) and cap.value_kwh > 0:
        kwh.append(float(cap.value_kwh))
    volts = (float(cap.nominal_voltage_v) if isinstance(cap, CapacityAuthority) and finite_number(cap.nominal_voltage_v)
             and cap.nominal_voltage_v > 0 else None)
    for key in ("capacity.helper_kwh", "capacity.fe1_wh_per_pct", "capacity.reg204_ah"):
        st = readings.get(key)
        v = getattr(st, "value", None)
        if not (finite_number(v) and v > 0):
            continue
        if key == "capacity.helper_kwh":
            kwh.append(float(v))
        elif key == "capacity.fe1_wh_per_pct":
            kwh.append(float(v) * 100.0 / 1000.0)
        else:
            kwh.append(None if volts is None else float(v) * volts / 1000.0)
    n = len(kwh)
    if n < 2 or any(x is None for x in kwh):
        return n, None
    return n, capacity_context(kwh)[1]


def site_hints_ignored(site: Mapping | None) -> list[Finding]:
    """INFO SITE_HINT_IGNORED for each reserve hint in a profile's `site` block: the SHADOW path takes reserves only from
    I-D1 / I-D2 (the hints stay for the V1 command line)."""
    out = []
    for k in ("user_reserve_soc_pct", "technical_min_soc_pct"):
        if isinstance(site, Mapping) and k in site:
            out.append(finding("SITE_HINT_IGNORED", INFO, f"site.{k}",
                               "a profile reserve hint is ignored by the SHADOW path; reserves come only from I-D1 / I-D2"))
    return out

