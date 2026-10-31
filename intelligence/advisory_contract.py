"""The Intelligence advisory output contract `ecco-intel-entities/1` (SHADOW only): what one cycle consumes (CycleInputs), what
it produces (AdvisoryEnvelope) and THE mapping of an envelope to Home Assistant entity payloads (to_entity_payloads).

An envelope cannot exist unless mode == 'SHADOW' and applies_nothing is True. It is built only by the constructors here
(assemble_envelope, starting_envelope, paused_envelope, stale_from, self_test_failed_envelope, with_last_good,
with_next_run_at), so a runtime never builds one by hand.

The null rule (not open to a contract change request):
  * STARTING, PAUSED, STALE, SELF_TEST_FAILED: every item, forecast and diagnostic state is None; the last values appear only
    in the unrecorded `last_good` attribute {generated_at, values}.
  * otherwise an item is numeric only when its status is OK and `now <= valid_until`;
  * a BLOCKED or INSUFFICIENT_DATA item carries no number in its state or in any attribute.

Entity ids are `ecco_intel_*` so they cannot collide with the frozen V1 prototype (`ecco_intelligence_*`); unique_id equals the
object id. `render_ha_prototype` (intelligence/tools) is untouched and superseded by this contract.

Pure data and pure functions: no I/O, no clock read (every time is an argument). From ecco_core only ecco_core.state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from ecco_core.state import Snapshot, spec_for

from .advisor import LiveInputs
from .config import SiteConfig
from .explain import BLOCKED as ADVICE_BLOCKED, INSUFFICIENT as ADVICE_INSUFFICIENT, OK as ADVICE_OK, Advice, finite_number
from .history import History
from .site_decisions import (DEFAULT_ACCEPT_PROVENANCE, ITEM_GATES, DecisionSet, DecisionStatus, GateContext, blocking,
                             display_label, gate, items_gated_by, DECISION_IDS)

CONTRACT_VERSION = "ecco-intel-entities/1"
MODE = "SHADOW"
MAX_ENTITY_JSON_BYTES = 16 * 1024
# per-field caps that keep every entity within MAX_ENTITY_JSON_BYTES (a test builds the maximal envelope)
MAX_BLOCKERS = 16
MAX_REASON_CODES = 24
MAX_INPUT_AGES = 24
MAX_TEXT_CHARS = 160               # a blocker text is truncated to this
MAX_CODE_CHARS = 64                # a code longer than this is refused
MAX_INPUT_AGE_BYTES = 160          # one input-age entry, as JSON
MAX_BLOCK_BYTES = 768              # tariff / value / plan / accuracy / engine_comparison / self_test / last_good, as JSON
MAX_SUMMARY_BYTES = 2048           # an OK item's summary, as JSON

# ---------------------------------------------------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------------------------------------------------

ENTITY_IDS: Mapping[str, str] = MappingProxyType({
    "status": "sensor.ecco_intel_status",
    "charge_target": "sensor.ecco_intel_charge_target",
    "overnight_demand": "sensor.ecco_intel_overnight_demand",
    "export_event": "sensor.ecco_intel_export_event",
    "dump_to_grid": "sensor.ecco_intel_dump_to_grid",
    "predicted_day_load": "sensor.ecco_intel_predicted_day_load",
    "pv_tomorrow": "sensor.ecco_intel_pv_tomorrow",
    "predicted_morning_soc": "sensor.ecco_intel_predicted_morning_soc",
    "accuracy": "sensor.ecco_intel_accuracy",
    "data_quality": "sensor.ecco_intel_data_quality",
    "fresh": "binary_sensor.ecco_intel_fresh",
    "paused": "input_boolean.ecco_intel_paused",                 # package entity (the pause helper)
    "watchdog_fresh": "binary_sensor.ecco_intel_watchdog_fresh",  # package entity (the dead-man watchdog)
})
PACKAGE_ENTITY_KEYS = ("paused", "watchdog_fresh")
INTEGRATION_ENTITY_KEYS = tuple(k for k in ENTITY_IDS if k not in PACKAGE_ENTITY_KEYS)


def object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


UNIQUE_IDS: Mapping[str, str] = MappingProxyType({k: object_id(v) for k, v in ENTITY_IDS.items()})

ADVICE_ITEMS = ("charge_target", "overnight_demand", "export_event", "dump_to_grid")
FORECAST_ITEMS = ("predicted_day_load", "pv_tomorrow", "predicted_morning_soc")
DIAGNOSTIC_ENTITY_KEYS = ("accuracy", "data_quality")
ITEM_UNITS: Mapping[str, str] = MappingProxyType({
    "charge_target": "%", "overnight_demand": "kWh", "export_event": "kWh", "dump_to_grid": "kWh",
    "predicted_day_load": "kWh", "pv_tomorrow": "kWh", "predicted_morning_soc": "%",
})
# the recommendation key whose value becomes an advice item's state
ITEM_VALUE_KEYS: Mapping[str, str] = MappingProxyType({
    "charge_target": "target_soc_pct", "overnight_demand": "planning_kwh", "export_event": "export_kwh",
    "dump_to_grid": "export_kwh",
})

# ---------------------------------------------------------------------------------------------------------------------
# statuses
# ---------------------------------------------------------------------------------------------------------------------


class SystemStatus:
    STARTING = "STARTING"
    OK = "OK"
    NO_ADVICE = "NO_ADVICE"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE = "STALE"
    SELF_TEST_FAILED = "SELF_TEST_FAILED"
    PAUSED = "PAUSED"
    # highest precedence first
    PRECEDENCE = (PAUSED, SELF_TEST_FAILED, STALE, STARTING, BLOCKED, INSUFFICIENT_DATA, NO_ADVICE, OK)
    ALL = PRECEDENCE
    NULL = (STARTING, PAUSED, STALE, SELF_TEST_FAILED)        # the null rule's statuses


class ItemStatus:
    OK = "OK"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_ADVICE = "NO_ADVICE"
    WITHHELD = "WITHHELD"          # not computed: the system status is one of SystemStatus.NULL
    ALL = (OK, BLOCKED, INSUFFICIENT_DATA, NO_ADVICE, WITHHELD)


class DataQuality:
    OK = "OK"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    ALL = (OK, DEGRADED, BLOCKED, UNKNOWN)


PAUSE_CONTROL_STATES = ("ON", "OFF", "MISSING")      # MISSING: the pause helper is absent -> not paused, with a WARN

# the pre-declared attribute blocks: exactly these keys (a new key is an additive contract change request)
BLOCK_KEYS: Mapping[str, frozenset] = MappingProxyType({
    "tariff": frozenset({"provenance", "window", "price_range"}),
    "value": frozenset({"range_gbp", "assumptions", "baselines"}),
    "plan": frozenset({"precharge_by", "headroom_ceiling_pct", "reserve_runout_at"}),
    "accuracy": frozenset({"mae_7d", "coverage_7d", "n"}),
})
# a tariff block may carry prices, and a value block may exist, only with one of these provenances (the planning layer's
# tariff adapter judges them; see INTELLIGENCE_FOUNDATION_CONTRACT.md section 6)
VERIFIED_TARIFF_PROVENANCES = frozenset({"VERIFIED", "VERIFIED_FROM_INTEGRATION"})
# input_ages rows: exactly these keys, these statuses
INPUT_AGE_KEYS = frozenset({"name", "age_s", "limit_s", "status"})
INPUT_AGE_STATUSES = ("fresh", "stale", "unknown", "missing")
# pv_tomorrow is published while every decision is OPEN, so its summary is limited to the V1 PV forecast's own keys
# (intelligence/pv.py PvForecast.to_dict): no battery figure can ride along
PV_TOMORROW_SUMMARY_KEYS = frozenset({"inflation", "usable", "day", "source", "raw_kwh", "ratio", "p10", "p50", "p90", "n_pairs",
                                      "mae_corrected", "mae_raw", "confidence", "label", "notes", "plausibility"})

# ---------------------------------------------------------------------------------------------------------------------
# site readings (add-only)
# ---------------------------------------------------------------------------------------------------------------------

SITE_READING_KEYS: Mapping[str, str] = MappingProxyType({
    "liveness.dongle_poll_changed_at": "datetime",
    "supervision.state": "enum",
    "supervision.stable": "bool",
    "supervision.heartbeat_age_s": "s",
    "battery.soc_raw_pct": "%",
    "capacity.helper_kwh": "kWh",
    "capacity.fe1_wh_per_pct": "Wh/%",
    "capacity.fe1_basis": "enum",
    "capacity.reg204_ah": "Ah",
    "efficiency.helper_pct": "%",
    "protection.shutdown_soc_pct": "%",
    "stop.dump_soc_pct": "%",
    "tou.slot_table": "table",
    "tou.current_target_soc_pct": "%",
    "limits.max_grid_charge_w": "W",
    "tariff.import_rates": "table",
    "tariff.export_rates": "table",
    "tariff.events": "table",
    "pv.forecast_today_kwh": "kWh",
    "pv.forecast_tomorrow_kwh": "kWh",
    "inverter.clock_offset_s": "s",
    "pref.wear_cost_p_per_kwh": "p/kWh",
    "pref.normal_max_charge_target_pct": "%",
})
OPTIONAL_READING_KEYS = ("pref.wear_cost_p_per_kwh", "pref.normal_max_charge_target_pct")


@dataclass(frozen=True)
class SiteReading:
    """One reading that is not an ecco_core.state signal (a helper, a register, a table, a forecast). Permissive by design:
    the quality layer judges it (key, unit, value, observed_at) and never trusts it blindly."""
    key: str
    value: Any
    unit: str | None
    observed_at: datetime | None
    source: str

    def problems(self) -> list[str]:
        out = []
        if self.key not in SITE_READING_KEYS:
            out.append(f"unknown reading key {self.key!r}")
        elif self.unit != SITE_READING_KEYS[self.key]:
            out.append(f"{self.key}: unit {self.unit!r} is not {SITE_READING_KEYS[self.key]!r}")
        if not (isinstance(self.observed_at, datetime) and self.observed_at.tzinfo is not None):
            out.append(f"{self.key}: observed_at must be an aware datetime")
        if not isinstance(self.source, str) or not self.source:
            out.append(f"{self.key}: a source is required")
        return out


# ---------------------------------------------------------------------------------------------------------------------
# cycle inputs
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SiteFacts:
    """Facts about the site that are not owner decisions (all may be None = unknown)."""
    pv_array_kwp: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    tz: str = "Europe/London"


@dataclass(frozen=True)
class OutcomeMetrics:
    """Measured accuracy of past advice (v0.1 carries only these; drift and calibration are reserved)."""
    mae_7d: float | None = None
    coverage_7d: float | None = None
    n: int = 0


@dataclass(frozen=True)
class Versions:
    integration_version: str = "unknown"
    engine_version: str = "unknown"
    git_sha: str | None = None
    config_hash: str | None = None


@dataclass(frozen=True)
class CycleInputs:
    """Everything one SHADOW cycle may use. No defaults are taken from anywhere else; `now` is the only clock."""
    now: datetime
    snapshot: Snapshot | None = None
    live: LiveInputs | None = None
    caller_assessments: tuple = ()               # ((signal, fresh: bool, age_s | None), ...) from the bridge
    history: History | None = None
    pv_forecast_history: Mapping | None = None   # {source: {date: kWh}} as issued (for PV bias learning)
    base_cfg: SiteConfig | None = None           # built from site facts only (never the example battery values)
    site_facts: SiteFacts = field(default_factory=SiteFacts)
    decisions: DecisionSet = field(default_factory=DecisionSet)
    # keyword-only: it can never be passed by position (the runtime never passes it at all; its boundary suite checks)
    accept_provenance: frozenset = field(default=DEFAULT_ACCEPT_PROVENANCE, kw_only=True)
    site_readings: tuple = ()                    # (SiteReading, ...)
    outcome_metrics: OutcomeMetrics | None = None
    paused: bool | None = None                   # None = the pause control is missing (not paused; WARN)
    previous: Mapping | None = None              # the previous envelope's summary (envelope_summary), or None
    versions: Versions = field(default_factory=Versions)

    def __post_init__(self) -> None:
        for name in ("caller_assessments", "site_readings"):
            v = getattr(self, name)
            if isinstance(v, list):
                object.__setattr__(self, name, tuple(v))
        if isinstance(self.accept_provenance, (set, list, tuple)):
            object.__setattr__(self, "accept_provenance", frozenset(self.accept_provenance))


# ---------------------------------------------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------------------------------------------

def _has_number(v: object) -> bool:
    """True when a JSON-like value contains an int/float anywhere (booleans are not numbers)."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, Mapping):
        return any(_has_number(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(_has_number(x) for x in v)
    return True                                    # anything else is not plain data: treat as a number (fail closed)


def _require_json(v: object, what: str) -> None:
    """Plain, strict JSON data only (finite numbers, str, bool, None, lists, mappings); anything else is a ValueError."""
    try:
        json.dumps(v, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be strict JSON data: {exc}") from None


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.isoformat()


def _code(c: object) -> str:
    c = str(c)
    if len(c) > MAX_CODE_CHARS:
        raise ValueError(f"code {c[:20]}... is longer than {MAX_CODE_CHARS} characters")
    return c


def _text(t: object) -> str:
    t = str(t)
    return t if len(t) <= MAX_TEXT_CHARS else t[:MAX_TEXT_CHARS - 3] + "..."


def _pairs(blockers) -> tuple[tuple[str, str], ...]:
    return tuple((_code(c), _text(t)) for c, t in blockers)


def _json_bytes(v: object) -> int:
    return len(json.dumps(v, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


@dataclass(frozen=True)
class ItemView:
    """One published advice item. Numbers only when status is OK."""
    key: str
    status: str
    value: float | None = None
    valid_until: datetime | None = None
    confidence: str | None = None
    blockers: tuple[tuple[str, str], ...] = ()
    reason_codes: tuple[str, ...] = ()
    summary: Mapping | None = None               # the OK recommendation (unrecorded); None otherwise

    def __post_init__(self) -> None:
        if self.key not in ADVICE_ITEMS:
            raise ValueError(f"unknown advice item {self.key!r}")
        _check_view(self)

    @property
    def unit(self) -> str:
        return ITEM_UNITS[self.key]

    @staticmethod
    def from_advice(advice: Advice, *, key: str | None = None, valid_until: datetime | None = None) -> "ItemView":
        """The view of a V1.1 Advice (explain.Advice, the single answer format). A non-OK advice keeps only its codes and
        texts: an INSUFFICIENT fallback recommendation is never published."""
        k = key or advice.kind
        status = {ADVICE_OK: ItemStatus.OK, ADVICE_BLOCKED: ItemStatus.BLOCKED,
                  ADVICE_INSUFFICIENT: ItemStatus.INSUFFICIENT_DATA}.get(advice.status, ItemStatus.BLOCKED)
        reasons = tuple(r.code for r in advice.reasons)
        blockers = tuple((b.code, b.text) for b in advice.blocking)
        if status != ItemStatus.OK:
            return ItemView(k, status, None, None, advice.confidence.label, blockers, reasons, None)
        rec = json.loads(json.dumps(advice.to_dict()["recommendation"], allow_nan=False))
        raw = rec.get(ITEM_VALUE_KEYS[k]) if isinstance(rec, dict) else None
        value = float(raw) if finite_number(raw) else None
        return ItemView(k, status, value, valid_until, advice.confidence.label, blockers, reasons, rec)


@dataclass(frozen=True)
class ForecastView:
    """One published forecast (predicted_day_load, pv_tomorrow, predicted_morning_soc). Numbers only when status is OK."""
    key: str
    status: str
    value: float | None = None
    p10: float | None = None
    p90: float | None = None
    valid_until: datetime | None = None
    confidence: str | None = None
    blockers: tuple[tuple[str, str], ...] = ()
    reason_codes: tuple[str, ...] = ()
    summary: Mapping | None = None

    def __post_init__(self) -> None:
        if self.key not in FORECAST_ITEMS:
            raise ValueError(f"unknown forecast {self.key!r}")
        _check_view(self)
        for name in ("p10", "p90"):
            v = getattr(self, name)
            if v is not None and (self.status != ItemStatus.OK or not finite_number(v)):
                raise ValueError(f"{self.key}.{name}: a number only for an OK forecast")
        if self.key == "pv_tomorrow" and self.summary is not None and not set(self.summary) <= PV_TOMORROW_SUMMARY_KEYS:
            raise ValueError(f"pv_tomorrow.summary: only the PV forecast keys {sorted(PV_TOMORROW_SUMMARY_KEYS)}, got "
                             f"{sorted(map(str, set(self.summary) - PV_TOMORROW_SUMMARY_KEYS))}")

    @property
    def unit(self) -> str:
        return ITEM_UNITS[self.key]


def _check_view(v) -> None:
    if v.status not in ItemStatus.ALL:
        raise ValueError(f"{v.key}: unknown item status {v.status!r}")
    object.__setattr__(v, "blockers", _pairs(v.blockers))
    object.__setattr__(v, "reason_codes", tuple(_code(c) for c in v.reason_codes))
    if len(v.blockers) > MAX_BLOCKERS or len(v.reason_codes) > MAX_REASON_CODES:
        raise ValueError(f"{v.key}: too many blockers / reason codes for the entity byte budget")
    if v.value is not None and not finite_number(v.value):
        raise ValueError(f"{v.key}: the value must be a finite number or None")
    if v.status != ItemStatus.OK:
        if v.value is not None or v.summary is not None or v.valid_until is not None:
            raise ValueError(f"{v.key}: a {v.status} item carries no number, summary or validity")
    if v.status == ItemStatus.BLOCKED and not v.blockers:
        raise ValueError(f"{v.key}: a BLOCKED item names at least one blocker")
    if v.valid_until is not None and not (isinstance(v.valid_until, datetime) and v.valid_until.tzinfo is not None):
        raise ValueError(f"{v.key}: valid_until must be aware")
    if v.summary is not None:
        _require_json(v.summary, f"{v.key}.summary")
        if _json_bytes(v.summary) > MAX_SUMMARY_BYTES:
            raise ValueError(f"{v.key}: the summary exceeds {MAX_SUMMARY_BYTES} bytes")
        object.__setattr__(v, "summary", MappingProxyType(dict(v.summary)))


def withheld_item(key: str, reason: str) -> ItemView:
    return ItemView(key, ItemStatus.WITHHELD, reason_codes=(reason,))


def withheld_forecast(key: str, reason: str) -> ForecastView:
    return ForecastView(key, ItemStatus.WITHHELD, reason_codes=(reason,))


# ---------------------------------------------------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------------------------------------------------

def _contains_key(v: object, key: str) -> bool:
    if isinstance(v, Mapping):
        return key in v or any(_contains_key(x, key) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(_contains_key(x, key) for x in v)
    return False


def _known_input(name: object) -> bool:
    """A name an input-age row may carry: an ecco_core.state signal or a SITE_READING_KEYS reading."""
    return isinstance(name, str) and (name in SITE_READING_KEYS or spec_for(name) is not None)


def _check_input_ages(rows: tuple) -> None:
    """Each row is exactly {name, age_s, limit_s, status}: a known input, ages that are None or finite >= 0, a known status;
    names unique. Nothing else can ride along (the all-OPEN invariant exempts only age_s and limit_s)."""
    seen: set[str] = set()
    for a in rows:
        if not isinstance(a, Mapping) or set(a) != INPUT_AGE_KEYS:
            raise ValueError(f"an input-age row is exactly {sorted(INPUT_AGE_KEYS)}")
        if not _known_input(a["name"]) or a["name"] in seen:
            raise ValueError(f"input-age name {a['name']!r} is not a known, unique signal or reading")
        seen.add(a["name"])
        if a["status"] not in INPUT_AGE_STATUSES:
            raise ValueError(f"input-age status must be one of {INPUT_AGE_STATUSES}")
        for k in ("age_s", "limit_s"):
            if a[k] is not None and not (finite_number(a[k]) and a[k] >= 0):
                raise ValueError(f"input-age {k} must be None or a finite number >= 0")


def _check_self_test(st: Mapping | None) -> None:
    """{check code: 'PASS' | 'FAIL: <text>'} only."""
    if st is None:
        return
    if not isinstance(st, Mapping):
        raise ValueError("self_test must be a mapping of check code to 'PASS' or 'FAIL: ...'")
    for k, v in st.items():
        if not (isinstance(k, str) and 0 < len(k) <= MAX_CODE_CHARS):
            raise ValueError("a self_test check code is a short string")
        if not (v == "PASS" or (isinstance(v, str) and v.startswith("FAIL: "))):
            raise ValueError(f"self_test[{k}] must be 'PASS' or 'FAIL: ...'")


def _check_blocks(env: "AdvisoryEnvelope") -> None:
    """The pre-declared blocks carry only their declared keys; accuracy only measured figures; prices and a value only with a
    VERIFIED tariff; a value or plan only while charge_target is OK."""
    for name, keys in BLOCK_KEYS.items():
        b = getattr(env, name)
        if b is None:
            continue
        if not isinstance(b, Mapping) or not set(b) <= keys:
            raise ValueError(f"{name} carries only {sorted(keys)}")
    acc = env.accuracy
    if acc is not None:
        for k in ("mae_7d", "coverage_7d"):
            if acc.get(k) is not None and not (finite_number(acc[k]) and acc[k] >= 0):
                raise ValueError(f"accuracy.{k} must be None or a finite number >= 0")
        n = acc.get("n")
        if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and n >= 0):
            raise ValueError("accuracy.n must be None or an int >= 0")
    tariff = env.tariff or {}
    verified = tariff.get("provenance") in VERIFIED_TARIFF_PROVENANCES
    if tariff.get("price_range") is not None and not verified:
        raise ValueError("tariff.price_range is published only with a VERIFIED tariff provenance")
    ct_ok = env.items[ADVICE_ITEMS.index("charge_target")].status == ItemStatus.OK
    if env.value is not None and not (verified and ct_ok):
        raise ValueError("a value block is published only with a VERIFIED tariff and an OK charge_target")
    if env.plan is not None and not ct_ok:
        raise ValueError("a plan block is published only while charge_target is OK")


def _check_gated_ok(env: "AdvisoryEnvelope") -> None:
    """No OK item or forecast while data quality is BLOCKED, while a decision it depends on is not RECORDED, or while any
    decision that can gate it is INVALID (the envelope's own status map; assemble_envelope also checks provenance)."""
    labels = env.decisions
    for v in env.items + env.forecasts:  # type: ignore[operator]
        if v.status != ItemStatus.OK:
            continue
        if env.data_quality == DataQuality.BLOCKED:
            raise ValueError(f"{v.key} cannot be OK while data quality is BLOCKED")
        need = [d for d in ITEM_GATES[v.key] if labels[display_label(d)] != DecisionStatus.RECORDED]
        bad = [d for d in DECISION_IDS if labels[display_label(d)] == DecisionStatus.INVALID
               and (d == "D7" or v.key in items_gated_by(d))]
        if need or bad:
            raise ValueError(f"{v.key} cannot be OK: {', '.join(display_label(d) for d in need + bad)} not satisfied")


@dataclass(frozen=True)
class AdvisoryEnvelope:
    """One cycle's published result. Frozen; SHADOW only; obeys the null rule (see the module docstring)."""
    status: str
    generated_at: datetime
    versions: Versions
    items: tuple[ItemView, ...]
    forecasts: tuple[ForecastView, ...]
    data_quality: str
    decisions: Mapping[str, str]                 # {"I-D1": "OPEN", ...}
    provenance_ok: bool
    pause_control: str
    valid_until: datetime | None = None
    next_run_at: datetime | None = None
    blockers: tuple[tuple[str, str], ...] = ()
    reason_codes: tuple[str, ...] = ()
    self_test: Mapping | None = None             # {check: "PASS" | "FAIL: ..."} (unrecorded)
    input_ages: tuple = ()                       # ({"name", "age_s", "limit_s", "status"}, ...) (unrecorded)
    tariff: Mapping | None = None                # {provenance, window, price_range}
    value: Mapping | None = None                 # {range_gbp, assumptions, baselines}
    plan: Mapping | None = None                  # {precharge_by, headroom_ceiling_pct, reserve_runout_at}
    accuracy: Mapping | None = None              # {mae_7d, coverage_7d, n}
    drift: None = None                           # reserved, always None in v0.1
    calibration: None = None                     # reserved, always None in v0.1
    engine_comparison: Mapping | None = None     # only when charge_target is OK
    scorecard_report: Mapping | None = None      # NOT published; never contains 'recommended'
    last_good: Mapping | None = None             # {generated_at, values}; only under a null-rule status (unrecorded)
    contract_version: str = CONTRACT_VERSION
    mode: str = MODE
    applies_nothing: bool = True

    def __post_init__(self) -> None:
        if self.mode != MODE or self.applies_nothing is not True:
            raise ValueError("an AdvisoryEnvelope is SHADOW only: mode must be 'SHADOW' and applies_nothing True")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"contract_version must be {CONTRACT_VERSION!r}")
        if self.status not in SystemStatus.ALL:
            raise ValueError(f"unknown status {self.status!r}")
        if self.data_quality not in DataQuality.ALL:
            raise ValueError(f"unknown data quality {self.data_quality!r}")
        if self.pause_control not in PAUSE_CONTROL_STATES:
            raise ValueError(f"pause_control must be one of {PAUSE_CONTROL_STATES}")
        for name in ("generated_at", "valid_until", "next_run_at"):
            t = getattr(self, name)
            if t is not None and not (isinstance(t, datetime) and t.tzinfo is not None):
                raise ValueError(f"{name} must be an aware datetime")
        if not isinstance(self.generated_at, datetime):
            raise ValueError("generated_at is required")
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "forecasts", tuple(self.forecasts))
        if tuple(i.key for i in self.items) != ADVICE_ITEMS or not all(isinstance(i, ItemView) for i in self.items):
            raise ValueError(f"items must be ItemViews for exactly {ADVICE_ITEMS}, in order")
        if tuple(f.key for f in self.forecasts) != FORECAST_ITEMS or not all(isinstance(f, ForecastView) for f in self.forecasts):
            raise ValueError(f"forecasts must be ForecastViews for exactly {FORECAST_ITEMS}, in order")
        if set(self.decisions) != {display_label(d) for d in DECISION_IDS} or not set(self.decisions.values()) <= set(DecisionStatus.ALL):
            raise ValueError("decisions must map every I-D label to OPEN / RECORDED / INVALID")
        object.__setattr__(self, "decisions", MappingProxyType({display_label(d): self.decisions[display_label(d)] for d in DECISION_IDS}))
        object.__setattr__(self, "blockers", _pairs(self.blockers))
        object.__setattr__(self, "reason_codes", tuple(_code(c) for c in self.reason_codes))
        object.__setattr__(self, "input_ages", tuple(self.input_ages))
        if len(self.blockers) > MAX_BLOCKERS or len(self.reason_codes) > MAX_REASON_CODES or len(self.input_ages) > MAX_INPUT_AGES:
            raise ValueError("too many blockers / reason codes / input ages for the entity byte budget")
        if self.drift is not None or self.calibration is not None:
            raise ValueError("drift and calibration are reserved and always None in v0.1")
        if self.scorecard_report is not None and _contains_key(self.scorecard_report, "recommended"):
            raise ValueError("a scorecard_report never contains 'recommended'")
        ct = self.items[ADVICE_ITEMS.index("charge_target")]
        if self.engine_comparison is not None and ct.status != ItemStatus.OK:
            raise ValueError("engine_comparison is emitted only when charge_target is OK")
        if self.status in SystemStatus.NULL:
            if any(i.status != ItemStatus.WITHHELD for i in self.items + self.forecasts):  # type: ignore[operator]
                raise ValueError(f"under {self.status} every item and forecast is WITHHELD (null rule)")
            if any(getattr(self, n) is not None for n in ("tariff", "value", "plan", "accuracy", "engine_comparison")):
                raise ValueError(f"under {self.status} no tariff, diagnostic, value or plan block is published (null rule)")
        elif self.last_good is not None:
            raise ValueError("last_good is carried only under a null-rule status")
        for name in ("tariff", "value", "plan", "accuracy", "engine_comparison", "scorecard_report", "last_good", "self_test"):
            _require_json(getattr(self, name), name)
            if name != "scorecard_report" and getattr(self, name) is not None and _json_bytes(getattr(self, name)) > MAX_BLOCK_BYTES:
                raise ValueError(f"{name} exceeds {MAX_BLOCK_BYTES} bytes")
        _check_self_test(self.self_test)
        _check_input_ages(self.input_ages)
        _require_json([dict(a) for a in self.input_ages], "input_ages")
        if any(_json_bytes(dict(a)) > MAX_INPUT_AGE_BYTES for a in self.input_ages):
            raise ValueError(f"an input-age entry exceeds {MAX_INPUT_AGE_BYTES} bytes")
        _check_blocks(self)
        _check_gated_ok(self)

    def item(self, key: str) -> ItemView | ForecastView:
        for v in self.items + self.forecasts:  # type: ignore[operator]
            if v.key == key:
                return v
        raise KeyError(key)

    def to_dict(self) -> dict:
        def view(v) -> dict:
            d = {f.name: getattr(v, f.name) for f in fields(v)}
            d["blockers"] = [{"code": c, "text": t} for c, t in v.blockers]
            d["reason_codes"] = list(v.reason_codes)
            d["valid_until"] = _iso(v.valid_until)
            d["summary"] = None if v.summary is None else dict(v.summary)
            d["unit"] = v.unit
            return d
        return {
            "contract_version": self.contract_version, "mode": self.mode, "applies_nothing": self.applies_nothing,
            "status": self.status, "generated_at": _iso(self.generated_at), "valid_until": _iso(self.valid_until),
            "next_run_at": _iso(self.next_run_at), "versions": {f.name: getattr(self.versions, f.name) for f in fields(self.versions)},
            "items": [view(i) for i in self.items], "forecasts": [view(f) for f in self.forecasts],
            "data_quality": self.data_quality, "decisions": dict(self.decisions), "provenance_ok": self.provenance_ok,
            "pause_control": self.pause_control, "blockers": [{"code": c, "text": t} for c, t in self.blockers],
            "reason_codes": list(self.reason_codes), "self_test": None if self.self_test is None else dict(self.self_test),
            "input_ages": [dict(a) for a in self.input_ages], "tariff": self.tariff, "value": self.value, "plan": self.plan,
            "accuracy": self.accuracy, "drift": None, "calibration": None, "engine_comparison": self.engine_comparison,
            "scorecard_report": self.scorecard_report, "last_good": self.last_good,
        }


def envelope_summary(env: AdvisoryEnvelope) -> dict:
    """{generated_at, status, values}: what the next cycle receives as `previous` and what last_good carries."""
    values = {v.key: v.value for v in env.items + env.forecasts if v.status == ItemStatus.OK and v.value is not None}  # type: ignore[operator]
    return {"generated_at": _iso(env.generated_at), "status": env.status, "values": dict(sorted(values.items()))}


def derive_status(*, paused: bool | None, self_test_failed: bool, stale: bool, starting: bool, data_quality: str,
                  item_statuses: tuple[str, ...]) -> str:
    """The system status by precedence PAUSED > SELF_TEST_FAILED > STALE > STARTING > BLOCKED > INSUFFICIENT_DATA >
    NO_ADVICE > OK. BLOCKED: data quality is BLOCKED, or no advice item is OK and at least one is BLOCKED. A missing pause
    control (None) is not paused."""
    if paused is True:
        return SystemStatus.PAUSED
    if self_test_failed:
        return SystemStatus.SELF_TEST_FAILED
    if stale:
        return SystemStatus.STALE
    if starting:
        return SystemStatus.STARTING
    st = tuple(item_statuses)
    if data_quality == DataQuality.BLOCKED:
        return SystemStatus.BLOCKED
    if ItemStatus.OK not in st:
        if ItemStatus.BLOCKED in st:
            return SystemStatus.BLOCKED
        if ItemStatus.INSUFFICIENT_DATA in st:
            return SystemStatus.INSUFFICIENT_DATA
        return SystemStatus.NO_ADVICE
    return SystemStatus.OK


def _pause_control(paused: bool | None) -> str:
    return "MISSING" if paused is None else ("ON" if paused else "OFF")


def _null_envelope(status: str, now: datetime, versions: Versions, decisions: DecisionSet,
                   accept_provenance, reason: str, *, paused: bool | None, next_run_at: datetime | None = None,
                   self_test: Mapping | None = None, blockers=(), last_good: Mapping | None = None) -> AdvisoryEnvelope:
    return AdvisoryEnvelope(
        status=status, generated_at=now, versions=versions,
        items=tuple(withheld_item(k, reason) for k in ADVICE_ITEMS),
        forecasts=tuple(withheld_forecast(k, reason) for k in FORECAST_ITEMS),
        data_quality=DataQuality.UNKNOWN, decisions=decisions.status_map(),
        provenance_ok=decisions.provenance_ok(accept_provenance), pause_control=_pause_control(paused),
        valid_until=None, next_run_at=next_run_at, blockers=tuple(blockers), reason_codes=(reason,),
        self_test=self_test, last_good=last_good)


def starting_envelope(now: datetime, versions: Versions, *, decisions: DecisionSet = DecisionSet(),
                      accept_provenance=DEFAULT_ACCEPT_PROVENANCE, paused: bool | None = False,
                      next_run_at: datetime | None = None) -> AdvisoryEnvelope:
    return _null_envelope(SystemStatus.STARTING, now, versions, decisions, accept_provenance, "STARTING", paused=paused,
                          next_run_at=next_run_at)


def paused_envelope(now: datetime, versions: Versions, *, decisions: DecisionSet = DecisionSet(),
                    accept_provenance=DEFAULT_ACCEPT_PROVENANCE, next_run_at: datetime | None = None) -> AdvisoryEnvelope:
    return _null_envelope(SystemStatus.PAUSED, now, versions, decisions, accept_provenance, "PAUSED", paused=True,
                          next_run_at=next_run_at)


def self_test_failed_envelope(now: datetime, versions: Versions, failures: Mapping[str, str], *,
                              decisions: DecisionSet = DecisionSet(), accept_provenance=DEFAULT_ACCEPT_PROVENANCE,
                              paused: bool | None = False) -> AdvisoryEnvelope:
    fl = dict(sorted((_code(str(k)[:MAX_CODE_CHARS]), str(v)[:80]) for k, v in failures.items())[:8])
    if not fl:
        fl = {"SELF_TEST": "failed without a named check"}
    return _null_envelope(SystemStatus.SELF_TEST_FAILED, now, versions, decisions, accept_provenance, "SELF_TEST_FAILED",
                          paused=paused, self_test={k: "FAIL: " + v for k, v in fl.items()},
                          blockers=tuple((k, v) for k, v in list(fl.items())[:MAX_BLOCKERS]))


def with_last_good(env: AdvisoryEnvelope, previous: AdvisoryEnvelope | Mapping | None) -> AdvisoryEnvelope:
    """`env` (a null-rule envelope) carrying the previous envelope's OK values in the unrecorded last_good attribute."""
    if previous is None:
        return env
    if isinstance(previous, AdvisoryEnvelope) and previous.status in SystemStatus.NULL and previous.last_good is not None:
        return replace(env, last_good=dict(previous.last_good))      # a null-rule previous passes its own last_good on
    summary = envelope_summary(previous) if isinstance(previous, AdvisoryEnvelope) else dict(previous)
    lg = {"generated_at": summary.get("generated_at"), "values": dict(summary.get("values") or {})}
    return replace(env, last_good=lg)


def with_next_run_at(env: AdvisoryEnvelope, next_run_at: datetime | None) -> AdvisoryEnvelope:
    """`env` with the time the runtime next runs a cycle (the status attribute `next_run_at`); nothing else changes and the
    result is checked as a whole again. run_cycle is pure and knows no schedule, so the runtime sets it before it publishes
    a computed or STALE envelope. Refused (ValueError): a naive time, or one before the envelope's generated_at."""
    if next_run_at is not None:
        if not (isinstance(next_run_at, datetime) and next_run_at.tzinfo is not None):
            raise ValueError("next_run_at must be an aware datetime or None")
        if next_run_at < env.generated_at:
            raise ValueError("next_run_at cannot be before the envelope's generated_at")
    return replace(env, next_run_at=next_run_at)


def stale_from(previous: AdvisoryEnvelope, now: datetime, *, paused: bool | None = None) -> AdvisoryEnvelope:
    """STALE: the previous envelope is past its validity (or the cycle did not run). Nothing numeric is published; the last
    values move to last_good. A pause control that is ON gives PAUSED instead (PAUSED > STALE), still with last_good."""
    pc = paused if paused is not None else (None if previous.pause_control == "MISSING" else previous.pause_control == "ON")
    status, reason = (SystemStatus.PAUSED, "PAUSED") if pc is True else (SystemStatus.STALE, "STALE")
    blockers = () if pc is True else (("STALE", "the last result is older than its validity; nothing is shown until a fresh cycle"),)
    env = AdvisoryEnvelope(
        status=status, generated_at=now, versions=previous.versions,
        items=tuple(withheld_item(k, reason) for k in ADVICE_ITEMS),
        forecasts=tuple(withheld_forecast(k, reason) for k in FORECAST_ITEMS),
        data_quality=DataQuality.UNKNOWN, decisions=previous.decisions, provenance_ok=previous.provenance_ok,
        pause_control=_pause_control(pc), valid_until=None, next_run_at=previous.next_run_at,
        blockers=blockers, reason_codes=(reason,))
    return with_last_good(env, previous)


def assemble_envelope(now: datetime, versions: Versions, *, items: tuple[ItemView, ...], forecasts: tuple[ForecastView, ...],
                      data_quality: str, decisions: DecisionSet, accept_provenance=DEFAULT_ACCEPT_PROVENANCE,
                      paused: bool | None = False, valid_until: datetime | None = None, next_run_at: datetime | None = None,
                      blockers=(), reason_codes=(), self_test: Mapping | None = None, input_ages=(),
                      tariff: Mapping | None = None, value: Mapping | None = None, plan: Mapping | None = None,
                      accuracy: Mapping | None = None, engine_comparison: Mapping | None = None,
                      scorecard_report: Mapping | None = None) -> AdvisoryEnvelope:
    """A computed cycle's envelope; the status is derived (derive_status). A paused cycle is refused here: use
    paused_envelope. Refused as well (ValueError), so a body can never publish a gated number:
      * an OK item or forecast whose decisions are not satisfied under `accept_provenance` (site_decisions.gate with no
        conditional context: unconditional gates and every INVALID decision that can gate it);
      * an OK item or forecast while data quality is BLOCKED;
      * an OK item or forecast without a validity that covers `now`, or an OK cycle without an envelope validity (so an
        expired item can never leave the status at OK);
      * a tariff price range or value block without a VERIFIED tariff, a value or plan block without an OK charge_target."""
    if paused is True:
        raise ValueError("a paused cycle publishes paused_envelope")
    acc = frozenset(accept_provenance)
    views = tuple(items) + tuple(forecasts)
    for v in views:
        if getattr(v, "status", None) != ItemStatus.OK:
            continue
        if blocking(gate(v.key, decisions, GateContext(), acc)):
            raise ValueError(f"{v.key} is OK but a decision it depends on is not satisfied under the accepted provenance")
        if v.valid_until is None or v.valid_until < now:
            raise ValueError(f"{v.key} is OK but has no validity covering now")
        if valid_until is None or valid_until < now:
            raise ValueError("a cycle with an OK item needs an envelope valid_until covering now")
    status = derive_status(paused=paused, self_test_failed=False, stale=False, starting=False, data_quality=data_quality,
                           item_statuses=tuple(i.status for i in items))
    rc = tuple(reason_codes)
    if paused is None and "PAUSE_CONTROL_MISSING" not in rc:
        rc = rc + ("PAUSE_CONTROL_MISSING",)
    return AdvisoryEnvelope(status=status, generated_at=now, versions=versions, items=tuple(items), forecasts=tuple(forecasts),
                            data_quality=data_quality, decisions=decisions.status_map(),
                            provenance_ok=decisions.provenance_ok(acc), pause_control=_pause_control(paused),
                            valid_until=valid_until, next_run_at=next_run_at, blockers=tuple(blockers)[:MAX_BLOCKERS],
                            reason_codes=rc[:MAX_REASON_CODES], self_test=self_test,
                            input_ages=tuple(input_ages)[:MAX_INPUT_AGES], tariff=tariff, value=value, plan=plan,
                            accuracy=accuracy, engine_comparison=engine_comparison, scorecard_report=scorecard_report)


# ---------------------------------------------------------------------------------------------------------------------
# entity payloads (THE mapping)
# ---------------------------------------------------------------------------------------------------------------------

STATUS_RECORDED = ("mode", "applies_nothing", "contract_version", "integration_version", "engine_version", "git_sha",
                   "config_hash", "generated_at", "valid_until", "next_run_at", "blockers", "reason_codes", "decisions",
                   "provenance_ok", "pause_control", "data_quality", "tariff", "value", "plan", "accuracy", "drift",
                   "calibration", "kind", "status")
STATUS_UNRECORDED = ("self_test", "input_ages", "last_good")
ITEM_RECORDED = ("mode", "applies_nothing", "contract_version", "kind", "status", "generated_at", "unit", "valid_until",
                 "confidence", "blockers", "reason_codes")
ITEM_UNRECORDED = ("advice", "engine_comparison")
FORECAST_RECORDED = ITEM_RECORDED + ("p10", "p90")
FORECAST_UNRECORDED = ("advice",)
DIAG_RECORDED = ("mode", "applies_nothing", "contract_version", "kind", "status", "generated_at", "unit", "coverage_7d", "n",
                 "reason_codes")
FRESH_RECORDED = ("mode", "applies_nothing", "contract_version", "kind", "status", "generated_at", "valid_until")
RECORDED_ATTRIBUTES = frozenset(STATUS_RECORDED + ITEM_RECORDED + FORECAST_RECORDED + DIAG_RECORDED + FRESH_RECORDED)
UNRECORDED_ATTRIBUTES = frozenset(STATUS_UNRECORDED + ITEM_UNRECORDED + FORECAST_UNRECORDED)
# where a finite number may legitimately appear while every decision is OPEN (the all-OPEN invariant): pv_tomorrow and
# the diagnostics; on the status entity only input_ages[].age_s / limit_s and accuracy.{mae_7d, coverage_7d, n} (self_test
# carries strings only). Documentation: the frozen test_intel_shadow_cycle_contract.py hard-codes its own copy, so a change
# here never widens it.
NUMERIC_EXEMPT_ENTITY_KEYS = ("pv_tomorrow",) + DIAGNOSTIC_ENTITY_KEYS
NUMERIC_EXEMPT_STATUS_ATTRIBUTES = ("input_ages", "accuracy")


def _numeric_allowed(env: AdvisoryEnvelope, v, now: datetime) -> bool:
    return (env.status not in SystemStatus.NULL and v.status == ItemStatus.OK and v.valid_until is not None
            and now <= v.valid_until)


def _view_advice(v, allowed: bool) -> dict:
    if allowed and v.summary is not None:
        return dict(v.summary)
    return {"status": v.status, "blocker_codes": [c for c, _t in v.blockers]}


def to_entity_payloads(env: AdvisoryEnvelope, now: datetime | None = None) -> dict[str, tuple[object, dict, dict]]:
    """{entity_id: (state, recorded_attributes, unrecorded_attributes)} for the eleven integration entities. `now` defaults
    to the envelope's generated_at. Raises ValueError when an entity would exceed MAX_ENTITY_JSON_BYTES, and when the
    envelope is not SHADOW / applies_nothing / this contract version (re-checked here, so an object mutated after
    construction is never published)."""
    if not isinstance(env, AdvisoryEnvelope) or env.mode != MODE or env.applies_nothing is not True \
            or env.contract_version != CONTRACT_VERSION:
        raise ValueError("only a SHADOW, applies-nothing envelope of this contract version is ever published")
    now = env.generated_at if now is None else now
    base = {"mode": env.mode, "applies_nothing": env.applies_nothing, "contract_version": env.contract_version}
    gen = _iso(env.generated_at)
    out: dict[str, tuple[object, dict, dict]] = {}
    out[ENTITY_IDS["status"]] = (env.status, {
        **base, "integration_version": env.versions.integration_version, "engine_version": env.versions.engine_version,
        "git_sha": env.versions.git_sha, "config_hash": env.versions.config_hash, "generated_at": gen,
        "valid_until": _iso(env.valid_until), "next_run_at": _iso(env.next_run_at),
        "blockers": [{"code": c, "text": t} for c, t in env.blockers], "reason_codes": list(env.reason_codes),
        "decisions": dict(env.decisions), "provenance_ok": env.provenance_ok, "pause_control": env.pause_control,
        "data_quality": env.data_quality, "tariff": env.tariff, "value": env.value, "plan": env.plan,
        "accuracy": env.accuracy, "drift": None, "calibration": None, "kind": "status", "status": env.status,
    }, {"self_test": None if env.self_test is None else dict(env.self_test), "input_ages": [dict(a) for a in env.input_ages],
        "last_good": env.last_good})
    for v in env.items:
        ok = _numeric_allowed(env, v, now)
        rec = {**base, "kind": v.key, "status": v.status, "generated_at": gen, "unit": v.unit,
               "valid_until": _iso(v.valid_until) if ok else None, "confidence": v.confidence,
               "blockers": [{"code": c, "text": t} for c, t in v.blockers], "reason_codes": list(v.reason_codes)}
        unrec = {"advice": _view_advice(v, ok),
                 "engine_comparison": env.engine_comparison if (v.key == "charge_target" and ok) else None}
        out[ENTITY_IDS[v.key]] = (v.value if ok else None, rec, unrec)
    for f in env.forecasts:
        ok = _numeric_allowed(env, f, now)
        rec = {**base, "kind": f.key, "status": f.status, "generated_at": gen, "unit": f.unit,
               "valid_until": _iso(f.valid_until) if ok else None, "confidence": f.confidence,
               "blockers": [{"code": c, "text": t} for c, t in f.blockers], "reason_codes": list(f.reason_codes),
               "p10": f.p10 if ok else None, "p90": f.p90 if ok else None}
        out[ENTITY_IDS[f.key]] = (f.value if ok else None, rec, {"advice": _view_advice(f, ok)})
    null = env.status in SystemStatus.NULL
    acc = env.accuracy or {}
    mae = acc.get("mae_7d") if not null else None
    out[ENTITY_IDS["accuracy"]] = (mae if finite_number(mae) else None, {
        **base, "kind": "accuracy", "status": env.status, "generated_at": gen, "unit": "kWh",
        "coverage_7d": acc.get("coverage_7d") if not null else None, "n": acc.get("n") if not null else None,
        "reason_codes": []}, {})
    out[ENTITY_IDS["data_quality"]] = (None if null else env.data_quality, {
        **base, "kind": "data_quality", "status": env.status, "generated_at": gen, "unit": None, "coverage_7d": None,
        "n": None, "reason_codes": list(env.reason_codes)}, {})
    fresh = (not null) and env.valid_until is not None and now <= env.valid_until
    out[ENTITY_IDS["fresh"]] = (fresh, {**base, "kind": "fresh", "status": env.status, "generated_at": gen,
                                        "valid_until": _iso(env.valid_until)}, {})
    for eid, (state, rec, unrec) in out.items():
        n = entity_json_bytes(state, rec, unrec)
        if n > MAX_ENTITY_JSON_BYTES:
            raise ValueError(f"{eid}: {n} bytes exceeds the {MAX_ENTITY_JSON_BYTES} byte budget")
    return out


def entity_json_bytes(state: object, recorded: Mapping, unrecorded: Mapping) -> int:
    return len(json.dumps({"state": state, "attributes": {**recorded, **unrecorded}}, allow_nan=False,
                          separators=(",", ":"), sort_keys=True).encode("utf-8"))


# ---------------------------------------------------------------------------------------------------------------------
# the cycle protocol
# ---------------------------------------------------------------------------------------------------------------------

@runtime_checkable
class RunCycle(Protocol):
    """run_cycle(inputs) -> AdvisoryEnvelope: pure (no clock read, no I/O), never raises, SHADOW only."""

    def __call__(self, inputs: CycleInputs) -> AdvisoryEnvelope: ...
