"""Home Assistant state views -> an ecco_core Snapshot plus SiteReadings (no homeassistant import; pure).

The caller (coordinator.py) turns each HA State into a plain view

    {"state": str, "attributes": {...}, "last_changed": aware datetime, "last_updated": ..., "last_reported": ... | None}

and passes only the entities the site file names. Every entity id comes from the site file's `shadow_runtime` block
(parse_entity_map); none is written in code.

Rules (each one tested in tests/test_runtime_sources.py):

  * 'unavailable', 'unknown', an empty or non-numeric state, a non-finite number or an unsupported unit (a unit attribute
    that is not a string included) is MISSING (no value), never 0;
  * the raw SOC (`battery.soc_raw_pct`) is preferred for the `battery.soc` signal; the canonical SOC is used only without a
    usable raw reading, and a canonical value of exactly 0 with no raw confirmation is MISSING (a known false zero);
  * the observation time of every dongle-sourced input (site_decisions.DONGLE_SIGNALS / DONGLE_READINGS) is the time the
    dongle's poll text last CHANGED as seen here (track_liveness): the dongle publishes only changed values, so an unchanged
    reading is fresh while the poll text keeps moving, and a frozen poll text makes every dongle input stale;
  * a poll text seen for the first time, or replayed unchanged after a reconnect, is not a new poll; a poll text that is not
    mapped, not published yet ('Waiting') or unavailable gives no liveness reading at all (the quality layer then BLOCKs);
  * the configuration-poll liveness reading (site_decisions.CONFIG_LIVENESS_KEY) is published only from the change time the
    coordinator passes as `config_liveness_at` (its second liveness memory), never parsed from the poll text's state, and
    only while the mapped configuration-online entity's state is exactly 'on'; the observation time of every
    configuration-poll reading (site_decisions.CONFIG_POLL_READINGS) is the OLDER of the telemetry and the configuration
    liveness times, and without either it has none (the reading is withheld, so the quality layer BLOCKs);
  * the TOU slot table (schema v2, advisory_contract.TOU_SLOT_*) is built from exactly six mapped slots of six entities
    each; a field that is unknown is null (never 0, never a guess): the charge source and mode pass through exactly as
    published (the dongle's literal 'None' is a value; only Home Assistant's 'unavailable' / 'unknown' are null), the
    target and power go through the numeric reader, flags_raw must be a whole number 0..65535, and `end` is the next
    slot's start; a start / target-only (v1) table is never built;
  * the TOU overlay reading (tou.overlay_state) is NONE only when every mapped overlay entity is exactly 'off', ACTIVE
    when any is exactly 'on', and withheld otherwise (an entity missing or in any other state);
  * the raise-only reserve preference (pref.advisory_reserve_raise_pct), once mapped, is published every cycle: its number
    when the state is a finite percentage in 0..100, otherwise value None (never dropped, never 0); unmapped, nothing;
  * every other reading's observation time is the newest of its state's last_reported / last_updated / last_changed; a
    spec with `fresh_by: refreshed_at` takes the older of that attribute and last_updated instead, and refuses the time
    (the reading is withheld) when the attribute is unparseable, naive, in the future or more than FRESH_BY_TOLERANCE_S
    from last_updated: it can only make a reading older;
  * a reading aged by its own report time may take its number from an attribute (`attribute`, optionally one nested
    `key`): a non-numeric or absent value is MISSING;
  * a table reading copies the mapped attribute's rows only when the entity's state is usable and the attribute is a
    list (otherwise TABLE_MISSING); a rate table (DAY_TABLE_KEYS) may instead list two or three `{entity, attribute}`
    day events in day order (previous, current, next; A38 Part B, CCR-RT-DAYS), and then (merge_day_tables): a part
    whose entity is unusable, or whose attribute is absent or an empty list, contributes nothing; a contributing
    attribute that is not a list refuses the whole table; the rows are concatenated in mapped order, a row repeating an
    earlier row's start, end and rate is dropped, and a row whose times are unusable, any other overlap and rows out of
    order refuse the whole table; a gap (the current-day event unusable between the other two) is passed on unchanged,
    never filled, and the engine's parse rule refuses a table with a gap (TARIFF_GAP), so that tariff is unusable for the
    cycle; the merged reading is observed at the oldest contributing part's own time (any part's time unknown: no time;
    a part dated in the future: that future time); nothing contributing is TABLE_MISSING; the same entity listed twice
    is refused by the map;
  * the configuration-poll liveness entity and its online entity must each differ from the telemetry poll-text entity
    (A33, RT-3: a copy-paste error would age every configuration-poll reading by the telemetry poll); the map is refused;
  * no two boolean gate readings (supervision.stable, tou.enabled, tou.grid_charge_enabled: each must read true for the
    items it gates) may name the same entity (A36, RR-3: a copy-paste error between the two TOU enables would let one
    enable's 'on' stand for the other, so a fail-closed check would be skipped), and none may name the configuration
    poll's online entity (A39, RT3-1 / RT3B-1: that entity reads 'on' while the configuration poll is online, so the
    gate's own flag would never be read); the map is refused;
  * `battery.soc_raw_pct` may not name the same entity and attribute as the `battery.soc` signal (A39, RT3B-2: the raw
    reading is preferred, so the canonical sensor's known false zero would pass as a raw 0); the map is refused;
  * no entity and attribute may be named by two of the tariff tables (tariff.import_rates, tariff.export_rates,
    tariff.events), every day event of a list counted (A42, RT4-2: one rate event under two keys would let its freshness
    stand in for the other key's own event); the same entity under another attribute is allowed; the map is refused;
  * a refused entity map (EntityMapError) names the field path and what is wrong, never the offending value (an entity id,
    a key or a source name from the site file): its text reaches the status entity and the diagnostics download. The value
    is kept in EntityMapError.detail for a debug log line;
  * every note (SourceResult.notes) is a contract key and a code from the closed SOURCE_NOTE_CODES, never an entity id,
    an attribute name, a state text or a site number, so the diagnostics download shows them unredacted (A42, RT4-1 (b):
    a refused rate table's code is visible there); public_notes keeps only notes of that kind;
  * the diagnostics download lists the snapshot's signals by contract name and a PV forecast observation by its day and
    position only (A45, RV9-3): the observation's own name carries the site file's source name, which is site text;
    public_signals withholds any other name.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from ecco_core.state import NORMALIZED, RAW, Observation, Snapshot
from intelligence.advisory_contract import (OPTIONAL_READING_KEYS, SITE_READING_KEYS, TOU_OVERLAY_STATES, TOU_SLOT_ROW_KEYS,
                                            TOU_SLOT_TABLE_ROWS, SiteReading)
from intelligence.inputs import forecast_observations
from intelligence.site_decisions import (CONFIG_LIVENESS_KEY, CONFIG_POLL_READINGS, DONGLE_READINGS, DONGLE_SIGNALS,
                                         LIVENESS_KEY)

MAP_BLOCK = "shadow_runtime"
SIGNAL_KEYS = ("battery.soc", "battery.power", "grid.power", "house.power", "pv.power", "inverter.healthy",
               "reserve.ha_minimum_soc")
POWER_SIGNALS = ("battery.power", "grid.power", "house.power", "pv.power")
FORECAST_DAYS = ("today", "tomorrow")
MISSING_STATES = frozenset({"unavailable", "unknown", "none", "null", ""})
HA_NO_STATE = frozenset({"unavailable", "unknown"})   # Home Assistant's own 'no state' (a published text is never these)
NOT_PUBLISHED_TEXTS = frozenset({"waiting"})          # the dongle's poll text before it has NTP time
ENTITY_ID_PATTERN = r"(?!_)[a-z0-9_]+(?<!_)\.(?!_)[a-z0-9_]+(?<!_)"
ATTRIBUTE_PATTERN = r"[a-z][a-z0-9_]{0,63}"
NUMBER_PATTERN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
HHMM_PATTERN = r"([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?"
MAX_TABLE_ROWS = 200                                  # a safety cap on a copied attribute table (not an owner value)
# A38 Part B (CCR-RT-DAYS): a rate table may read the tariff integration's day events in day order (previous, current,
# next) and the runtime hands the engine one merged list of rows; the engine's parse, unit and coverage rules then apply
# unchanged. Only the rate tables: tariff.events holds periods, not one day's rates.
DAY_TABLE_KEYS = ("tariff.import_rates", "tariff.export_rates")
DAY_PARTS_MIN, DAY_PARTS_MAX = 2, 3
# A42 (RT4-2): the tariff tables, in code order. No entity and attribute may be named by two of them (every day event of
# a list counted): one rate event under two keys would be read for both.
TARIFF_TABLE_KEYS = ("tariff.import_rates", "tariff.export_rates", "tariff.events")
DAY_RATE_ROW_KEY = "value_inc_vat"                    # intelligence.tariff.PRICE_KEY (test_runtime_sources pins the two)
MAX_TIME_TEXT = 64                                    # a safety cap on a time attribute's length (not an owner value)
# the TOU slot table (schema v2): exactly TOU_SLOT_TABLE_ROWS slots, each mapping these six entities (site-file field ->
# the value's row key); `slot` and `end` are derived, never mapped
TOU_SLOT_TABLE_KEY = "tou.slot_table"
TOU_SLOT_FIELDS = ("start", "target_soc", "charge_source", "power", "flags_raw", "mode")
TOU_SLOT_FIELD_ROW_KEYS = MappingProxyType({"start": "start", "target_soc": "target_soc_pct",
                                            "charge_source": "charge_source", "power": "power_w",
                                            "flags_raw": "flags_raw", "mode": "mode"})
FLAGS_RAW_MAX = 0xFFFF                                # the slot flags word is one 16-bit register
# the TOU overlay (Free Power, Dump to Grid, a manual write): one reading from several binary entities
OVERLAY_KEY = "tou.overlay_state"
OVERLAY_NONE, OVERLAY_ACTIVE = TOU_OVERLAY_STATES
MAX_OVERLAY_ENTITIES = 16                             # a safety cap (not an owner value)
OVERLAY_OFF, OVERLAY_ON = "off", "on"                 # compared exactly (no case folding, no trimming)
# the configuration-poll liveness spec names the dongle's configuration-online binary sensor; only this exact state counts
CONFIG_ONLINE_STATE = "on"
# the raise-only advisory reserve preference (foundation contract section 13.7)
PREF_RESERVE_RAISE_KEY = "pref.advisory_reserve_raise_pct"
# `fresh_by`: a reading fed by the configuration bridge carries its own render time; it may only make the reading older
FRESH_BY_ATTRIBUTES = ("refreshed_at",)
FRESH_BY_TOLERANCE_S = 5.0                            # attribute vs last_updated: the same render, so seconds apart at most
# accepted unit_of_measurement per canonical unit -> factor to the canonical unit; a missing attribute is taken as canonical
UNIT_FACTORS: Mapping[str, Mapping[str, float]] = MappingProxyType({
    "%": MappingProxyType({"%": 1.0}),
    "W": MappingProxyType({"W": 1.0, "kW": 1000.0}),
    "kWh": MappingProxyType({"kWh": 1.0, "Wh": 0.001}),
    "s": MappingProxyType({"s": 1.0, "min": 60.0}),
    "Ah": MappingProxyType({"Ah": 1.0}),
    "Wh/%": MappingProxyType({"Wh/%": 1.0}),
    "p/kWh": MappingProxyType({"p/kWh": 1.0, "GBP/kWh": 100.0}),
})
NON_NUMERIC_UNITS = frozenset({"table", "enum", "bool", "datetime"})
SIGNAL_UNITS = MappingProxyType({"battery.soc": "%", "battery.power": "W", "grid.power": "W", "house.power": "W",
                                 "pv.power": "W", "reserve.ha_minimum_soc": "%"})


def ages_by_own_time(key: str) -> bool:
    """True for a signal or reading whose observation time is its own state's report time: not dongle-sourced, not read by
    the configuration poll, not a liveness time, not a preference (preferences do not age) and not the overlay. Only such
    a key may name `fresh_by` or (a numeric reading) an `attribute`."""
    return not (key in DONGLE_SIGNALS or key in DONGLE_READINGS or key in CONFIG_POLL_READINGS
                or key in (LIVENESS_KEY, CONFIG_LIVENESS_KEY, OVERLAY_KEY, TOU_SLOT_TABLE_KEY)
                or key in OPTIONAL_READING_KEYS)


# ---------------------------------------------------------------------------------------------------------------------
# the entity map (from the site file)
# ---------------------------------------------------------------------------------------------------------------------

def valid_entity_id(v: object) -> bool:
    return isinstance(v, str) and re.fullmatch(ENTITY_ID_PATTERN, v) is not None


class EntityMapError(ValueError):
    """A refused shadow_runtime block. `public` (also str()) holds the field path and the problem only, never the offending
    value; `detail` adds that value, for the coordinator's debug log line only."""

    def __init__(self, public: str, detail: str | None = None) -> None:
        super().__init__(public)
        self.public = public
        self.detail = detail or public


def _doc_key(k: object) -> bool:
    return isinstance(k, str) and k.startswith("_")


def _strict(obj: object, allowed: tuple[str, ...], required: tuple[str, ...], what: str) -> dict:
    if not isinstance(obj, Mapping):
        raise EntityMapError(f"{what} must be an object")
    out = {}
    for k, v in obj.items():
        if _doc_key(k):
            continue
        if k not in allowed:
            raise EntityMapError(f"{what}: an unknown key (expected one of the documented keys)",
                                 f"{what}: unknown key {k!r}")
        out[k] = v
    for k in required:                                # `required` is a code constant, never site text
        if k not in out:
            raise EntityMapError(f"{what}: {k!r} is required")
    return out


def _entity(v: object, what: str) -> str:
    if not valid_entity_id(v):
        raise EntityMapError(f"{what}: not a valid entity id (a placeholder left in the site file?)",
                             f"{what}: {v!r} is not a valid entity id")
    return v


def _attribute_name(v: object, what: str) -> str:
    if not (isinstance(v, str) and re.fullmatch(ATTRIBUTE_PATTERN, v)):
        raise EntityMapError(f"{what} must be a plain attribute name", f"{what}: {v!r} is not a plain attribute name")
    return v


def _fresh_by(s: Mapping, key: str, what: str) -> dict:
    """The optional `fresh_by` of a spec, validated: only for a key aged by its own report time, only a documented
    attribute. Returns {} or {"fresh_by": name}."""
    if "fresh_by" not in s:
        return {}
    if not ages_by_own_time(key):
        raise EntityMapError(f"{what}.fresh_by is only for a reading aged by its own report time (not a dongle, "
                             "configuration-poll, liveness, overlay or preference key)")
    if s["fresh_by"] not in FRESH_BY_ATTRIBUTES:
        raise EntityMapError(f"{what}.fresh_by must be one of {list(FRESH_BY_ATTRIBUTES)}",
                             f"{what}.fresh_by: {s['fresh_by']!r} is not one of {list(FRESH_BY_ATTRIBUTES)}")
    return {"fresh_by": s["fresh_by"]}


def _slot_table_spec(spec: object, what: str) -> Mapping:
    s = _strict(spec, ("slots",), ("slots",), what)
    slots = s["slots"]
    if not (isinstance(slots, list) and len(slots) == TOU_SLOT_TABLE_ROWS):
        raise EntityMapError(f"{what}.slots must list exactly {TOU_SLOT_TABLE_ROWS} slots in slot order, each mapping "
                             f"{list(TOU_SLOT_FIELDS)}")
    parsed = []
    seen: dict[str, str] = {}
    for i, sl in enumerate(slots, start=1):
        t = _strict(sl, TOU_SLOT_FIELDS, TOU_SLOT_FIELDS, f"{what}.slots[{i}]")
        row = {}
        for field in TOU_SLOT_FIELDS:                 # code order, so paths and the mapping never depend on site text
            path = f"{what}.slots[{i}].{field}"
            eid = _entity(t[field], path)
            if eid in seen:                           # a copy-paste error could hide a second grid slot
                raise EntityMapError(f"{path}: the same entity as {seen[eid]} (every slot field needs its own entity)",
                                     f"{path}: {eid!r} is also {seen[eid]}")
            seen[eid] = path
            row[field] = eid
        parsed.append(MappingProxyType(row))
    return MappingProxyType({"slots": tuple(parsed)})


def _overlay_spec(spec: object, what: str) -> Mapping:
    s = _strict(spec, ("entities",), ("entities",), what)
    ents = s["entities"]
    if not (isinstance(ents, list) and 1 <= len(ents) <= MAX_OVERLAY_ENTITIES):
        raise EntityMapError(f"{what}.entities must list 1..{MAX_OVERLAY_ENTITIES} binary entity ids")
    out: list[str] = []
    for i, e in enumerate(ents, start=1):
        eid = _entity(e, f"{what}.entities[{i}]")
        if eid in out:
            raise EntityMapError(f"{what}.entities[{i}]: listed twice", f"{what}.entities[{i}]: {eid!r} listed twice")
        out.append(eid)
    return MappingProxyType({"entities": tuple(out)})


def _table_part(key: str, spec: object, what: str) -> Mapping:
    """One `{entity, attribute}` table spec (optionally `fresh_by`)."""
    s = _strict(spec, ("entity", "attribute", "fresh_by"), ("entity", "attribute"), what)
    return MappingProxyType({"entity": _entity(s["entity"], what),
                             "attribute": _attribute_name(s["attribute"], f"{what}.attribute"),
                             **_fresh_by(s, key, what)})


def _table_spec(key: str, spec: object, what: str) -> Mapping:
    """A table reading's spec: one `{entity, attribute}` (unchanged), or, for a rate table (DAY_TABLE_KEYS), a list of
    DAY_PARTS_MIN..DAY_PARTS_MAX of them in day order (previous, current, next; A38 Part B), returned as {"parts": (...)}.
    Each part is checked exactly as the single form is; the same entity listed twice is refused (by position only)."""
    if not isinstance(spec, list):
        return _table_part(key, spec, what)
    if key not in DAY_TABLE_KEYS:
        raise EntityMapError(f"{what}: only a rate table ({', '.join(DAY_TABLE_KEYS)}) may list day events; map one "
                             "{entity, attribute}")
    if not DAY_PARTS_MIN <= len(spec) <= DAY_PARTS_MAX:
        raise EntityMapError(f"{what} must be one {{entity, attribute}} or a list of {DAY_PARTS_MIN} or {DAY_PARTS_MAX} "
                             "of them in day order (previous, current, next)")
    parts: list[Mapping] = []
    seen: dict[str, str] = {}
    for i, p in enumerate(spec, start=1):
        path = f"{what}[{i}]"
        part = _table_part(key, p, path)
        eid = part["entity"]
        if eid in seen:                               # a copy-paste error would read one day twice and another not at all
            raise EntityMapError(f"{path}: the same entity as {seen[eid]} (each day event is listed once)",
                                 f"{path}: {eid!r} is also {seen[eid]}")
        seen[eid] = path
        parts.append(part)
    return MappingProxyType({"parts": tuple(parts)})


def _reading_spec(key: str, spec: object, what: str) -> Mapping:
    unit = SITE_READING_KEYS[key]
    if key == TOU_SLOT_TABLE_KEY:
        return _slot_table_spec(spec, what)
    if key == OVERLAY_KEY:
        return _overlay_spec(spec, what)
    if key == CONFIG_LIVENESS_KEY:
        s = _strict(spec, ("entity", "online_entity"), ("entity", "online_entity"), what)
        return MappingProxyType({"entity": _entity(s["entity"], what),
                                 "online_entity": _entity(s["online_entity"], f"{what}.online_entity")})
    if unit == "table":
        return _table_spec(key, spec, what)
    if unit not in NON_NUMERIC_UNITS and ages_by_own_time(key):
        s = _strict(spec, ("entity", "attribute", "key", "fresh_by"), ("entity",), what)
        out: dict[str, Any] = {"entity": _entity(s["entity"], what)}
        if "attribute" in s:
            out["attribute"] = _attribute_name(s["attribute"], f"{what}.attribute")
            if "key" in s:
                out["key"] = _attribute_name(s["key"], f"{what}.key")
        elif "key" in s:
            raise EntityMapError(f"{what}.key needs an attribute")
        return MappingProxyType({**out, **_fresh_by(s, key, what)})
    s = _strict(spec, ("entity", "fresh_by"), ("entity",), what)
    return MappingProxyType({"entity": _entity(s["entity"], what), **_fresh_by(s, key, what)})


@dataclass(frozen=True)
class EntityMap:
    """Which entity feeds which signal or reading. `present` is False when the site file has no shadow_runtime block (then
    nothing is mapped and the quality layer blocks every item that needs an input)."""
    signals: Mapping[str, Mapping[str, Any]]
    readings: Mapping[str, Mapping[str, Any]]
    pv_forecast_sources: Mapping[str, Mapping[str, str]]
    present: bool

    def entity_ids(self) -> tuple[str, ...]:
        """Every entity id the map names (the coordinator fetches exactly these): plain entities, the configuration-online
        entity, the overlay entities, all six entities of every TOU slot and every day event of a rate table."""
        ids: set[str] = set()
        for spec in list(self.signals.values()) + list(self.readings.values()):
            for k in ("entity", "online_entity"):
                if k in spec:
                    ids.add(spec[k])
            ids.update(spec.get("entities", ()))
            for slot in spec.get("slots", ()):
                ids.update(slot.values())
            ids.update(part["entity"] for part in spec.get("parts", ()))
        for day in self.pv_forecast_sources.values():
            ids.update(day.values())
        return tuple(sorted(ids))


EMPTY_MAP = EntityMap(MappingProxyType({}), MappingProxyType({}), MappingProxyType({}), False)


def _distinct_poll_texts(readings: Mapping[str, Mapping]) -> None:
    """A33 (RT-3): the configuration poll's liveness entity and its online entity must not be the telemetry poll-text
    entity. A copy-paste error there would age every configuration-poll reading by the telemetry poll, so a configuration
    poll that stopped while the telemetry poll moves would still look fresh. Refused by field path only (the entity id
    goes to the debug detail); checked after every reading is parsed, so the order in the site file does not matter."""
    tel, cfg = readings.get(LIVENESS_KEY), readings.get(CONFIG_LIVENESS_KEY)
    if tel is None or cfg is None:
        return
    tel_path = f"{MAP_BLOCK}.readings.{LIVENESS_KEY}"
    cfg_path = f"{MAP_BLOCK}.readings.{CONFIG_LIVENESS_KEY}"
    for field, path in (("entity", cfg_path), ("online_entity", f"{cfg_path}.online_entity")):
        if cfg.get(field) == tel.get("entity"):
            raise EntityMapError(f"{path}: the same entity as {tel_path} (the configuration poll needs its own poll text "
                                 "and online entity)", f"{path}: {cfg.get(field)!r} is also {tel_path}")


# A36 (RR-3): the boolean gate readings. Each must read true for the items it gates (the TOU enable and the grid-charge
# enable for the charge-window items, the supervision stable flag for export and Dump), so two of them mapped to one
# entity would let that entity pass both checks while the other flag is off: a fail-closed check silently skipped.
BOOL_GATE_KEYS = tuple(k for k, unit in SITE_READING_KEYS.items() if unit == "bool")


def _distinct_bool_gates(readings: Mapping[str, Mapping]) -> None:
    """A36 (RR-3): no two boolean gate readings (BOOL_GATE_KEYS: supervision.stable, tou.enabled and
    tou.grid_charge_enabled) may name the same entity. A copy-paste error between the two TOU enables would let the TOU
    enable's 'on' stand for an off grid-charge enable (or the reverse), so charge-window advice would stand while one
    enable is off. A39 (RT3-1 / RT3B-1): none of them may name the configuration poll's online entity either, a gate of
    the same class (it must read exactly 'on'): it reads 'on' whenever the configuration poll is online, so the gate's
    own flag (an enable that is off, supervision that is not stable) would never be read. Refused by field path only
    (the entity id goes to the debug detail), in code order (the online entity first), so the order in the site file
    does not matter."""
    seen: dict[str, str] = {}
    cfg = readings.get(CONFIG_LIVENESS_KEY)
    if cfg is not None and cfg.get("online_entity") is not None:
        seen[cfg["online_entity"]] = f"{MAP_BLOCK}.readings.{CONFIG_LIVENESS_KEY}.online_entity"
    for key in BOOL_GATE_KEYS:
        spec = readings.get(key)
        eid = spec.get("entity") if spec is not None else None
        if eid is None:
            continue
        path = f"{MAP_BLOCK}.readings.{key}"
        if eid in seen:
            raise EntityMapError(f"{path}: the same entity as {seen[eid]} (each enable and gate flag, and the "
                                 "configuration-online entity, needs its own entity)", f"{path}: {eid!r} is also {seen[eid]}")
        seen[eid] = path


RAW_SOC_KEY = "battery.soc_raw_pct"


def _distinct_soc_sources(signals: Mapping[str, Mapping], readings: Mapping[str, Mapping]) -> None:
    """A39 (RT3B-2): `battery.soc_raw_pct` may not name the same entity and attribute as the `battery.soc` signal. The
    raw reading is preferred whenever it is in range, so the canonical sensor read as 'raw' would turn its known false
    zero (which counts as missing without a raw confirmation) into a raw 0, and the morning SOC would rest on it while
    the battery does not discharge. Refused by field path only (the entity id goes to the debug detail)."""
    raw, canon = readings.get(RAW_SOC_KEY), signals.get("battery.soc")
    if raw is None or canon is None:
        return
    if raw.get("entity") == canon.get("entity") and raw.get("attribute") == canon.get("attribute"):
        path, other = f"{MAP_BLOCK}.readings.{RAW_SOC_KEY}", f"{MAP_BLOCK}.signals.battery.soc"
        raise EntityMapError(f"{path}: the same entity as {other} (the raw SOC needs its own entity: the canonical SOC's "
                             "false zero would read as a raw 0)", f"{path}: {raw.get('entity')!r} is also {other}")


def _distinct_tariff_events(readings: Mapping[str, Mapping]) -> None:
    """A42 (RT4-2): no entity and attribute may be named by two of the tariff tables (TARIFF_TABLE_KEYS: the import
    rates, the export rates and the events), every day event of a list counted. One event under two keys is read for
    both: an import day event copied into the export mapping leaves the real export event unread, so a stale export event
    would no longer BLOCK export and Dump advice (its freshness stands in), and the export rows would be the import's.
    The same entity under another attribute is allowed (one entity may hold import and export rates in separate
    attributes); a site whose import and export rates share one attribute cannot map both (fail-closed). Within one list
    _table_spec already refuses the same entity twice. Refused by field path only (the entity id and attribute go to the
    debug detail), in code order (the later key against the earlier), so the order in the site file does not matter."""
    seen: dict[tuple[str, str], str] = {}
    for key in TARIFF_TABLE_KEYS:
        spec = readings.get(key)
        if spec is None:
            continue
        base = f"{MAP_BLOCK}.readings.{key}"
        parts = spec.get("parts")
        named = [(f"{base}[{i}]", p) for i, p in enumerate(parts, start=1)] if parts is not None else [(base, spec)]
        for path, part in named:
            pair = (part.get("entity"), part.get("attribute"))
            if pair in seen:
                raise EntityMapError(f"{path}: the same entity and attribute as {seen[pair]} (each tariff table reads its "
                                     "own events)", f"{path}: {pair[0]!r} attribute {pair[1]!r} is also {seen[pair]}")
            seen[pair] = path


def parse_entity_map(profile: Mapping | None) -> EntityMap:
    """The strict reader of the site file's shadow_runtime block. Unknown keys, invalid entity ids (placeholders included)
    and malformed specs raise EntityMapError (a ValueError); '_'-prefixed keys are documentation. No block -> EMPTY_MAP.
    Every field path below is built from code constants or keys already checked against them."""
    if not isinstance(profile, Mapping) or MAP_BLOCK not in profile:
        return EMPTY_MAP
    block = _strict(profile[MAP_BLOCK], ("signals", "readings", "pv_forecast_sources"), (), MAP_BLOCK)
    signals: dict[str, Mapping] = {}
    for key, spec in _strict(block.get("signals", {}), SIGNAL_KEYS, (), f"{MAP_BLOCK}.signals").items():
        what = f"{MAP_BLOCK}.signals.{key}"
        if key == "inverter.healthy":
            s = _strict(spec, ("entity", "healthy_states"), ("entity", "healthy_states"), what)
            hs = s["healthy_states"]
            if not (isinstance(hs, list) and hs and all(isinstance(x, str) and x for x in hs)):
                raise EntityMapError(f"{what}.healthy_states must be a non-empty list of state strings")
            signals[key] = MappingProxyType({"entity": _entity(s["entity"], what), "healthy_states": tuple(hs)})
        elif key in POWER_SIGNALS:
            s = _strict(spec, ("entity", "sign"), ("entity",), what)
            sign = s.get("sign", 1)
            if sign not in (1, -1) or isinstance(sign, bool):
                raise EntityMapError(f"{what}.sign must be 1 or -1")
            signals[key] = MappingProxyType({"entity": _entity(s["entity"], what), "sign": sign})
        else:
            s = _strict(spec, ("entity", "fresh_by"), ("entity",), what)
            signals[key] = MappingProxyType({"entity": _entity(s["entity"], what), **_fresh_by(s, key, what)})
    readings: dict[str, Mapping] = {}
    for key, spec in _strict(block.get("readings", {}), tuple(SITE_READING_KEYS), (), f"{MAP_BLOCK}.readings").items():
        readings[key] = _reading_spec(key, spec, f"{MAP_BLOCK}.readings.{key}")
    _distinct_poll_texts(readings)
    _distinct_bool_gates(readings)
    _distinct_soc_sources(signals, readings)
    _distinct_tariff_events(readings)
    pv: dict[str, Mapping] = {}
    for day, names in _strict(block.get("pv_forecast_sources", {}), FORECAST_DAYS, (), f"{MAP_BLOCK}.pv_forecast_sources").items():
        what = f"{MAP_BLOCK}.pv_forecast_sources.{day}"
        if not isinstance(names, Mapping):
            raise EntityMapError(f"{what} must be an object of source name -> entity id")
        out = {}
        for i, (name, eid) in enumerate(names.items(), start=1):     # paths by position: a source name is site text
            if _doc_key(name):
                continue
            if not (isinstance(name, str) and re.fullmatch(ATTRIBUTE_PATTERN, name)):
                raise EntityMapError(f"{what}[{i}]: not a plain source name",
                                     f"{what}[{i}]: {name!r} is not a plain source name")
            out[name] = _entity(eid, f"{what}[{i}]")
        pv[day] = MappingProxyType(dict(sorted(out.items())))
    return EntityMap(MappingProxyType(signals), MappingProxyType(readings), MappingProxyType(pv), True)


# ---------------------------------------------------------------------------------------------------------------------
# value parsing (missing is None, never 0)
# ---------------------------------------------------------------------------------------------------------------------

def _aware(t: object) -> bool:
    return isinstance(t, datetime) and t.tzinfo is not None and t.tzinfo.utcoffset(t) is not None


def state_text(view: Mapping | None) -> str | None:
    """The state string, or None when the entity is absent, 'unavailable', 'unknown' or empty."""
    if not isinstance(view, Mapping):
        return None
    s = view.get("state")
    if not isinstance(s, str) or s.strip().lower() in MISSING_STATES:
        return None
    return s.strip()


def published_text(view: Mapping | None) -> str | None:
    """The state exactly as published (no trimming, no case change), or None when the entity is absent, its state is
    Home Assistant's own 'unavailable' / 'unknown', or empty. Unlike state_text, the dongle's literal 'None' (a slot with
    no charge source, a slot with mode none) is a value, never missing."""
    if not isinstance(view, Mapping):
        return None
    s = view.get("state")
    if not isinstance(s, str) or s == "" or s in HA_NO_STATE:
        return None
    return s


def parse_number(v: object) -> float | None:
    """A finite number from a state string (or a plain int / float); anything else None. Booleans are not numbers."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.lower() in MISSING_STATES or not re.fullmatch(NUMBER_PATTERN, s):
        return None
    x = float(s)
    return x if math.isfinite(x) else None


def numeric_value(view: Mapping | None, unit: str) -> tuple[float | None, str]:
    """(value in the canonical `unit`, note). The unit attribute must be one this unit accepts (absent = canonical)."""
    text = state_text(view)
    if text is None:
        return None, "MISSING_STATE"
    x = parse_number(text)
    if x is None:
        return None, "NOT_NUMERIC"
    attrs = view.get("attributes") if isinstance(view.get("attributes"), Mapping) else {}
    uom = attrs.get("unit_of_measurement")
    factors = UNIT_FACTORS.get(unit, MappingProxyType({unit: 1.0}))
    if uom is None:
        return x, "UNIT_ASSUMED_CANONICAL"
    if not isinstance(uom, str) or uom not in factors:    # a list / dict / number unit is unsupported (never a crash)
        return None, "UNIT_UNSUPPORTED"
    return x * factors[uom], "OK"


def _attributes(view: Mapping | None) -> Mapping:
    a = view.get("attributes") if isinstance(view, Mapping) else None
    return a if isinstance(a, Mapping) else {}


def attribute_number(view: Mapping | None, attribute: str, key: str | None = None) -> tuple[float | None, str]:
    """(the number held by an attribute, or by one key of a mapping attribute, note). The entity's own state must be usable
    (an unavailable entity's attributes are not current); a missing, non-numeric, boolean or non-finite value is None. An
    attribute carries no unit of its own, so the value is taken in the reading's canonical unit."""
    if state_text(view) is None:
        return None, "MISSING_STATE"
    v = _attributes(view).get(attribute)
    if key is not None:
        v = v.get(key) if isinstance(v, Mapping) else None
    if v is None:
        return None, "ATTRIBUTE_MISSING"
    x = parse_number(v)
    if x is None:
        return None, "NOT_NUMERIC"
    return x, "UNIT_ASSUMED_CANONICAL"


def whole_number(view: Mapping | None, lo: int, hi: int) -> int | None:
    """A whole number lo..hi from the state ('1' or '1.0'); anything else (fractional, out of range, missing) None."""
    x = parse_number(state_text(view))
    if x is None or not lo <= x <= hi or x != math.floor(x):
        return None
    return int(x)


def bool_value(view: Mapping | None) -> bool | None:
    text = state_text(view)
    if text is None:
        return None
    return {"on": True, "true": True, "off": False, "false": False}.get(text.lower())


def hhmm(v: object) -> str | None:
    """'H:MM', 'HH:MM' or 'HH:MM:SS' -> 'HH:MM' (24:00 kept); anything else None."""
    if not isinstance(v, str):
        return None
    m = re.fullmatch(HHMM_PATTERN, v.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not ((h < 24 and mi < 60) or (h == 24 and mi == 0)):
        return None
    return f"{h:02d}:{mi:02d}"


def parse_time(v: object) -> datetime | None:
    """An aware datetime from an aware datetime or an ISO 8601 text with an offset; a naive or unparseable value None."""
    if isinstance(v, datetime):
        return v if _aware(v) else None
    if not isinstance(v, str) or not v.strip() or len(v) > MAX_TIME_TEXT:
        return None
    try:
        t = datetime.fromisoformat(v.strip())
    except ValueError:
        return None
    return t if _aware(t) else None


def _json_scalar(v: object) -> bool:
    return v is None or isinstance(v, (str, bool)) or (isinstance(v, (int, float)) and math.isfinite(v))


def _plain(v: object, depth: int = 0) -> object:
    """A JSON-safe copy (str / finite number / bool / None, lists and string-keyed mappings, depth <= 3); else None."""
    if isinstance(v, datetime):
        return v.isoformat()
    if _json_scalar(v):
        return v
    if depth >= 3:
        return None
    if isinstance(v, Mapping):
        return {str(k): _plain(x, depth + 1) for k, x in v.items() if isinstance(k, str)}
    if isinstance(v, (list, tuple)):
        return [_plain(x, depth + 1) for x in v]
    return None


def observed_time(view: Mapping | None) -> datetime | None:
    """The newest of last_reported / last_updated / last_changed (aware), or None."""
    if not isinstance(view, Mapping):
        return None
    ts = [view.get(k) for k in ("last_reported", "last_updated", "last_changed")]
    ts = [t for t in ts if _aware(t)]
    return max(ts) if ts else None


def fresh_by_time(view: Mapping | None, attribute: str, now: datetime) -> tuple[datetime | None, str]:
    """(observation time, note) of a state that carries its own render time in `attribute`: the older of that time and
    last_updated. None (refused) when the attribute is missing, unparseable or naive, lies after `now`, or is more than
    FRESH_BY_TOLERANCE_S from last_updated (a stale render time while another attribute keeps changing, or the reverse).
    It never returns a time newer than last_updated, so it can only make a reading older."""
    if not isinstance(view, Mapping):
        return None, "MISSING_STATE"
    t = parse_time(_attributes(view).get(attribute))
    if t is None:
        return None, "FRESH_BY_UNPARSEABLE"
    if (now - t).total_seconds() < 0:
        return None, "FRESH_BY_IN_FUTURE"
    lu = view.get("last_updated")
    if not _aware(lu):
        return None, "FRESH_BY_NO_LAST_UPDATED"
    if abs((t - lu).total_seconds()) > FRESH_BY_TOLERANCE_S:
        return None, "FRESH_BY_DISAGREES"
    return min(t, lu), "OK"


def _own_time(spec: Mapping, view: Mapping | None, now: datetime) -> tuple[datetime | None, str]:
    """A reading's or signal's own observation time: fresh_by when the spec names it, else observed_time."""
    if "fresh_by" in spec:
        return fresh_by_time(view, spec["fresh_by"], now)
    return observed_time(view), "OK"


# ---------------------------------------------------------------------------------------------------------------------
# liveness: the dongle's poll text
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LivenessMemory:
    """The last poll text seen, when it was seen to change, and whether that change was observed (not a first sighting)."""
    text: str
    changed_at: datetime | None
    confirmed: bool


def poll_text(view: Mapping | None) -> str | None:
    """A poll text's state, or None while it is absent, unavailable, unknown, empty or not yet published ('Waiting')."""
    text = state_text(view)
    return None if text is None or text.lower() in NOT_PUBLISHED_TEXTS else text


def track_liveness(view: Mapping | None, memory: LivenessMemory | None, now: datetime
                   ) -> tuple[datetime | None, LivenessMemory | None, str]:
    """(the poll-text change time to use as liveness, the new memory, a note).

    A change counts only when the text differs from the text seen before (a reconnect that replays the old text gives
    the old change time); the first sighting after start-up is not a change; an unpublished ('Waiting') or unavailable
    text keeps the last confirmed change time, which simply grows old; a change time in the future is unusable."""
    text = poll_text(view)
    last = memory.changed_at if (memory is not None and memory.confirmed) else None
    if last is not None and (now - last).total_seconds() < 0:
        last = None
    if text is None:
        return last, memory, "POLL_TEXT_UNAVAILABLE"
    if memory is not None and text == memory.text:
        return last, memory, "POLL_TEXT_UNCHANGED"
    changed = view.get("last_changed") if isinstance(view, Mapping) else None
    if not _aware(changed) or (now - changed).total_seconds() < 0:
        return last, LivenessMemory(text, None, False), "POLL_TEXT_CHANGE_TIME_UNUSABLE"
    if memory is None:
        return None, LivenessMemory(text, changed, False), "POLL_TEXT_FIRST_SIGHT"
    return changed, LivenessMemory(text, changed, True), "POLL_TEXT_CHANGED"


# ---------------------------------------------------------------------------------------------------------------------
# the snapshot and the readings
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceResult:
    snapshot: Snapshot
    site_readings: tuple[SiteReading, ...]
    notes: tuple[tuple[str, str], ...]            # (signal or reading key, code): diagnostics only, never published


# A42 (RT4-1 (b)): the closed vocabulary of the notes' codes. A note is (a contract key: one of SIGNAL_KEYS or
# advisory_contract.SITE_READING_KEYS, one of these code constants); it never carries an entity id, an attribute name, a
# state text or a site number, so the diagnostics download shows the notes unredacted, and a refused rate table's code
# (TABLE_*) is visible there. tests/test_runtime_sources.py produces every code and pins that no other note is made.
SOURCE_NOTE_CODES = frozenset({
    "NOT_MAPPED", "NO_CONFIRMED_POLL_CHANGE", "CONFIGURATION_NOT_ONLINE", "NO_CONFIG_LIVENESS", "NO_OBSERVATION_TIME",
    "MISSING_STATE", "NOT_NUMERIC", "UNIT_UNSUPPORTED", "ATTRIBUTE_MISSING", "OUT_OF_RANGE", "NOT_BOOLEAN",
    "CANONICAL_ZERO_UNCONFIRMED", "SLOT_FIELD_UNKNOWN", "OVERLAY_STATE_UNKNOWN",
    "FRESH_BY_UNPARSEABLE", "FRESH_BY_IN_FUTURE", "FRESH_BY_NO_LAST_UPDATED", "FRESH_BY_DISAGREES",
    "TABLE_MISSING", "TABLE_PART_NOT_LIST", "TABLE_ROW_TIME_UNUSABLE", "TABLE_ROWS_OVERLAP", "TABLE_ROWS_OUT_OF_ORDER",
})
NOTE_KEYS = frozenset(SIGNAL_KEYS) | frozenset(SITE_READING_KEYS)


def public_notes(notes: object) -> tuple[list[list[str]], int]:
    """([key, code] for every note that is a contract key (NOTE_KEYS) and a SOURCE_NOTE_CODES code, in order; the number
    of other notes, withheld). build_sources makes no other note (tested on every refusal path), so nothing is withheld;
    the filter keeps the diagnostics download free of site text should a later change make one. Pure; never raises."""
    shown: list[list[str]] = []
    withheld = 0
    for n in notes if isinstance(notes, (list, tuple)) else ():
        if (isinstance(n, tuple) and len(n) == 2 and isinstance(n[0], str) and isinstance(n[1], str)
                and n[0] in NOTE_KEYS and n[1] in SOURCE_NOTE_CODES):
            shown.append([n[0], n[1]])
        else:
            withheld += 1
    return shown, withheld


# A45 (RV9-3): a PV forecast observation is named pv.forecast.<day>.s<position>_<source name>
# (intelligence.inputs.forecast_observations), and the source name is site text. The diagnostics download shows it by
# its day and position only; the other names a snapshot holds here are the contract signals and the history marker.
FORECAST_SIGNAL_PATTERN = r"pv\.forecast\.(" + "|".join(FORECAST_DAYS) + r")\.s([0-9]{3,})_.*"
PUBLIC_SIGNAL_NAMES = frozenset(SIGNAL_KEYS) | {"history.hourly"}


def public_signals(names: object) -> tuple[list[str], int]:
    """(the snapshot's signal names as the diagnostics download shows them, in order; the number of other names,
    withheld). A contract signal name (SIGNAL_KEYS, history.hourly) is shown as it is; a PV forecast observation as
    pv.forecast.<day>.s<position>, without its source name; any other name is withheld, so no site text reaches the
    download should a later change name an observation otherwise. Pure; never raises."""
    shown: list[str] = []
    withheld = 0
    for n in names if isinstance(names, (list, tuple)) else ():
        m = re.fullmatch(FORECAST_SIGNAL_PATTERN, n, re.S) if isinstance(n, str) else None
        if isinstance(n, str) and n in PUBLIC_SIGNAL_NAMES:
            shown.append(n)
        elif m is not None:
            shown.append(f"pv.forecast.{m.group(1)}.s{m.group(2)}")
        else:
            withheld += 1
    return shown, withheld


def _src(eid: str) -> str:
    return f"ha:{eid}"


def _in_range(x: float | None, lo: float, hi: float | None) -> float | None:
    return x if x is not None and x >= lo and (hi is None or x <= hi) else None


def _oldest(times: list[datetime | None]) -> datetime | None:
    """The oldest of several observation times, or None when any is unknown (an unknown part makes the whole unknown)."""
    return min(times) if times and all(t is not None for t in times) else None


def slot_table_value(spec: Mapping, states: Mapping[str, Mapping]) -> tuple[list[dict], datetime | None, str]:
    """(the schema v2 table, the oldest observation time of its entities or None, note). Always six rows in slot order
    with exactly advisory_contract.TOU_SLOT_ROW_KEYS; an unknown field is None (the planning layer refuses the table)."""
    rows: list[dict] = []
    times: list[datetime | None] = []
    for i, sl in enumerate(spec["slots"], start=1):
        views = {field: states.get(sl[field]) for field in TOU_SLOT_FIELDS}
        times += [observed_time(v) for v in views.values()]
        rows.append({
            "slot": i,
            "start": hhmm(state_text(views["start"])),
            "end": None,
            "target_soc_pct": _in_range(numeric_value(views["target_soc"], "%")[0], 0.0, 100.0),
            "charge_source": published_text(views["charge_source"]),
            "flags_raw": whole_number(views["flags_raw"], 0, FLAGS_RAW_MAX),
            "mode": published_text(views["mode"]),
            "power_w": _in_range(numeric_value(views["power"], "W")[0], 0.0, None),
        })
    n = len(rows)
    for i in range(n):
        rows[i]["end"] = rows[(i + 1) % n]["start"]
    rows = [{k: r[k] for k in TOU_SLOT_ROW_KEYS} for r in rows]
    unknown = any(r[k] is None for r in rows for k in TOU_SLOT_ROW_KEYS)
    return rows, _oldest(times), ("SLOT_FIELD_UNKNOWN" if unknown else "OK")


def overlay_value(spec: Mapping, states: Mapping[str, Mapping]) -> tuple[str | None, datetime | None, str]:
    """(NONE / ACTIVE / None, the oldest observation time of the entities or None, note): ACTIVE when any entity is exactly
    'on'; NONE only when every entity is exactly 'off'; otherwise (missing, unavailable, any other state) no value."""
    views = [states.get(e) for e in spec["entities"]]
    raw = [v.get("state") if isinstance(v, Mapping) else None for v in views]
    at = _oldest([observed_time(v) for v in views])
    if any(r == OVERLAY_ON for r in raw):
        return OVERLAY_ACTIVE, at, "OK"
    if all(r == OVERLAY_OFF for r in raw):
        return OVERLAY_NONE, at, "OK"
    return None, at, "OVERLAY_STATE_UNKNOWN"


def _row_span(row: object) -> tuple[datetime, datetime] | None:
    """(start, end) of a rate row as aware datetimes, or None when the row is not a mapping or either time is unusable."""
    if not isinstance(row, Mapping):
        return None
    a, b = parse_time(row.get("start")), parse_time(row.get("end"))
    return (a, b) if a is not None and b is not None else None


def _same_rate(x: object, y: object) -> bool:
    """Both rates finite numbers (never booleans) and equal."""
    def num(v: object) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return num(x) and num(y) and float(x) == float(y)


def merge_day_rows(rows: list) -> tuple[list | None, str]:
    """(the merged rows, "OK") or (None, the refusal code) for the rows of a rate table's day events, concatenated in
    mapped order (A38 Part B). A row with the same start and end (as instants) and the same rate as an earlier row is
    dropped (a day event that still holds the day before); a row whose start or end is unusable (TABLE_ROW_TIME_UNUSABLE),
    a row with the start and end of an earlier row but another rate, or one starting before the previous row ends
    (TABLE_ROWS_OVERLAP), and one starting before the previous row starts (TABLE_ROWS_OUT_OF_ORDER) refuse the whole
    table. A gap is kept, never filled: the engine's parse rule refuses a table with a gap (TARIFF_GAP), so that tariff
    is unusable for the cycle. Pure; never raises."""
    out: list = []
    rates: dict[tuple[datetime, datetime], object] = {}
    last: tuple[datetime, datetime] | None = None
    for r in rows:
        span = _row_span(r)
        if span is None:
            return None, "TABLE_ROW_TIME_UNUSABLE"
        rate = r.get(DAY_RATE_ROW_KEY)
        if span in rates:
            if _same_rate(rates[span], rate):
                continue
            return None, "TABLE_ROWS_OVERLAP"
        if last is not None and span[0] < last[1]:
            return None, "TABLE_ROWS_OUT_OF_ORDER" if span[0] < last[0] else "TABLE_ROWS_OVERLAP"
        rates[span] = rate
        out.append(r)
        last = span
    return out, "OK"


def merge_day_tables(spec: Mapping, states: Mapping[str, Mapping], now: datetime
                     ) -> tuple[list | None, datetime | None, str, str]:
    """(merged rows or None, the observation time, note, source) of a rate table mapped as day events (A38 Part B,
    spec {"parts": (...)} in day order). A part whose entity is absent or unusable (state_text None), or whose attribute
    is absent, None or an empty list, contributes nothing (a next-day event before publication). A contributing part
    whose attribute is anything but a list refuses the whole table (TABLE_PART_NOT_LIST). Each contributing part's rows
    are copied as the single form copies them (at most MAX_TABLE_ROWS, JSON-safe) and concatenated in mapped order, then
    merge_day_rows applies. The observation time is the oldest of the contributing parts' own times (_own_time: the
    single form's rule, `fresh_by` included; _most_conservative), None when any of them has none (the reading is then
    withheld, with that part's FRESH_BY_ note when it has one), and a future-dated part's time when one lies after
    `now`. Nothing contributing: TABLE_MISSING, as the single form."""
    rows: list = []
    times: list[datetime | None] = []
    time_note = "OK"
    used: list[str] = []
    for part in spec["parts"]:
        view = states.get(part["entity"])
        if state_text(view) is None:
            continue
        attr = _attributes(view).get(part["attribute"])
        if attr is None:
            continue
        if not isinstance(attr, (list, tuple)):
            return None, None, "TABLE_PART_NOT_LIST", "ha:day_events"
        if len(attr) == 0:
            continue
        at, note = _own_time(part, view, now)
        times.append(at)
        if note != "OK" and time_note == "OK":
            time_note = note
        rows += [_plain(r) for r in list(attr)[:MAX_TABLE_ROWS]]
        used.append(part["entity"])
    src = "ha:" + "+".join(used) if used else "ha:day_events"
    if not used:
        return None, None, "TABLE_MISSING", src
    merged, note = merge_day_rows(rows)
    if merged is None:
        return None, None, note, src
    return merged, _most_conservative(times, now), time_note, src


def _most_conservative(times: list[datetime | None], now: datetime) -> datetime | None:
    """The merged reading's observation time: None when any part's time is unknown; a part dated after `now` makes the
    whole as future-dated as that part (the quality layer then never counts it fresh, as it would not count that part
    alone); otherwise the oldest part's time (A38 Part B)."""
    known = _oldest(times)
    if known is None:
        return None
    future = [t for t in times if t is not None and (now - t).total_seconds() < 0]
    return max(future) if future else known


def _reading_value(key: str, spec: Mapping, states: Mapping[str, Mapping], now: datetime
                   ) -> tuple[object, datetime | None, str, str]:
    """(value or None, the reading's own observation time, note, source) for one mapped reading other than liveness."""
    unit = SITE_READING_KEYS[key]
    if key == TOU_SLOT_TABLE_KEY:
        table, at, note = slot_table_value(spec, states)
        return table, at, note, "ha:tou_slots"
    if key == OVERLAY_KEY:
        value, at, note = overlay_value(spec, states)
        return value, at, note, "ha:tou_overlay"
    if unit == "table" and "parts" in spec:
        return merge_day_tables(spec, states, now)
    view = states.get(spec["entity"])
    at, time_note = _own_time(spec, view, now)
    src = _src(spec["entity"])
    if unit == "table":
        rows = _attributes(view).get(spec["attribute"])
        if state_text(view) is None or not isinstance(rows, (list, tuple)):
            return None, at, "TABLE_MISSING", src
        return [_plain(r) for r in list(rows)[:MAX_TABLE_ROWS]], at, time_note, src
    if unit == "enum":
        text = state_text(view)
        return text, at, ("MISSING_STATE" if text is None else time_note), src
    if unit == "bool":
        b = bool_value(view)
        return b, at, ("NOT_BOOLEAN" if b is None else time_note), src
    if "attribute" in spec:
        x, note = attribute_number(view, spec["attribute"], spec.get("key"))
    else:
        x, note = numeric_value(view, unit)
    if key == PREF_RESERVE_RAISE_KEY and x is not None and not 0.0 <= x <= 100.0:
        x, note = None, "OUT_OF_RANGE"
    return x, at, (note if x is None or time_note == "OK" else time_note), src


def _config_liveness(now: datetime, states: Mapping[str, Mapping], emap: EntityMap, config_liveness_at: datetime | None,
                     notes: list[tuple[str, str]]) -> tuple[datetime | None, SiteReading | None]:
    """(the configuration-poll liveness time to use, its reading): the coordinator's change time, only while the mapped
    configuration-online entity is exactly 'on' and the time is aware and not in the future."""
    spec = emap.readings.get(CONFIG_LIVENESS_KEY)
    if spec is None:
        notes.append((CONFIG_LIVENESS_KEY, "NOT_MAPPED"))
        return None, None
    online = states.get(spec["online_entity"])
    if not (isinstance(online, Mapping) and online.get("state") == CONFIG_ONLINE_STATE):
        notes.append((CONFIG_LIVENESS_KEY, "CONFIGURATION_NOT_ONLINE"))
        return None, None
    if not (_aware(config_liveness_at) and (now - config_liveness_at).total_seconds() >= 0):
        notes.append((CONFIG_LIVENESS_KEY, "NO_CONFIRMED_POLL_CHANGE"))
        return None, None
    return config_liveness_at, SiteReading(CONFIG_LIVENESS_KEY, config_liveness_at, SITE_READING_KEYS[CONFIG_LIVENESS_KEY],
                                           config_liveness_at, _src(spec["entity"]))


def build_sources(now: datetime, states: Mapping[str, Mapping], emap: EntityMap, liveness_at: datetime | None,
                  history_end: datetime | None = None, *, config_liveness_at: datetime | None = None) -> SourceResult:
    """The Snapshot (as_of = now) and the SiteReadings for one cycle. Nothing here judges freshness: the bridge and the
    quality layer do, from the observation times set here.

    `liveness_at` and `config_liveness_at` (keyword only) are the times the dongle's telemetry-poll and configuration-poll
    texts last changed, from the coordinator's two liveness memories. The configuration-poll liveness reading
    (site_decisions.CONFIG_LIVENESS_KEY) is published only from `config_liveness_at`, and only while the mapped
    configuration-online entity is exactly 'on'; every configuration-poll reading is observed at the older of the two
    times, and is withheld without either (INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.3)."""
    notes: list[tuple[str, str]] = []
    obs: list[Observation] = []
    readings: list[SiteReading] = []
    live_ok = _aware(liveness_at) and (now - liveness_at).total_seconds() >= 0
    dongle_at = liveness_at if live_ok else None

    # readings (both liveness times first)
    live_spec = emap.readings.get(LIVENESS_KEY)
    if live_spec is None:
        notes.append((LIVENESS_KEY, "NOT_MAPPED"))
    elif dongle_at is None:
        notes.append((LIVENESS_KEY, "NO_CONFIRMED_POLL_CHANGE"))
    else:
        readings.append(SiteReading(LIVENESS_KEY, dongle_at, SITE_READING_KEYS[LIVENESS_KEY], dongle_at,
                                    _src(live_spec["entity"])))
    config_at, config_reading = _config_liveness(now, states, emap, config_liveness_at, notes)
    if config_reading is not None:
        readings.append(config_reading)
    config_poll_at = _oldest([dongle_at, config_at])  # a configuration-poll value is as old as the older of the two polls
    raw_soc: tuple[float, str, str] | None = None
    for key in sorted(emap.readings):
        if key in (LIVENESS_KEY, CONFIG_LIVENESS_KEY):
            continue
        value, own_at, note, source = _reading_value(key, emap.readings[key], states, now)
        if key == PREF_RESERVE_RAISE_KEY:             # never dropped while mapped; an unusable value is None, never 0
            if value is None:
                notes.append((key, note))
            readings.append(SiteReading(key, value, SITE_READING_KEYS[key],
                                        observed_time(states.get(emap.readings[key]["entity"])) or now, source))
            continue
        if key in CONFIG_POLL_READINGS:
            at = config_poll_at
            no_time = "NO_CONFIG_LIVENESS" if config_at is None else "NO_OBSERVATION_TIME"
        elif key in DONGLE_READINGS:
            at, no_time = dongle_at, "NO_OBSERVATION_TIME"
        else:
            at, no_time = own_at, (note if note.startswith("FRESH_BY_") else "NO_OBSERVATION_TIME")
        if value is None or at is None:
            notes.append((key, note if value is None else no_time))
            continue
        if key == TOU_SLOT_TABLE_KEY and note != "OK":
            notes.append((key, note))                 # published with its unknown fields null
        if key == "battery.soc_raw_pct":
            if not 0.0 <= value <= 100.0:
                notes.append((key, "OUT_OF_RANGE"))
                continue
            raw_soc = (value, source, state_text(states.get(emap.readings[key]["entity"])) or "")
        readings.append(SiteReading(key, value, SITE_READING_KEYS[key], at, source))

    # signals
    for key in SIGNAL_KEYS:
        spec = emap.signals.get(key)
        at_dongle = key in DONGLE_SIGNALS
        if key == "battery.soc" and raw_soc is not None:
            obs.append(Observation("battery.soc", raw_soc[0], dongle_at, raw_soc[1], RAW, raw=raw_soc[2],
                                   quality=("raw_soc_preferred",)))
            continue
        if spec is None:
            if key == "battery.soc" and "battery.soc_raw_pct" in emap.readings:
                obs.append(Observation("battery.soc", None, dongle_at, "ha:raw_soc", RAW, quality=("raw_soc_missing",)))
            else:
                notes.append((key, "NOT_MAPPED"))
            continue
        view = states.get(spec["entity"])
        if at_dongle:
            at = dongle_at
        else:
            at, time_note = _own_time(spec, view, now)
            if at is None and time_note != "OK":
                notes.append((key, time_note))
        raw = state_text(view)
        if key == "inverter.healthy":
            value = None if raw is None else (raw in spec["healthy_states"])
            obs.append(Observation(key, value, at, _src(spec["entity"]), NORMALIZED, raw=raw))
            continue
        x, note = numeric_value(view, SIGNAL_UNITS[key])
        quality: tuple[str, ...] = ()
        if x is not None and key in POWER_SIGNALS:
            x = x * spec["sign"]
        if key == "battery.soc":
            quality = ("canonical_soc",)
            if x is not None and x == 0.0:
                x, note, quality = None, "CANONICAL_ZERO_UNCONFIRMED", ("canonical_zero_unconfirmed",)
        if x is not None and key in ("battery.soc", "reserve.ha_minimum_soc") and not 0.0 <= x <= 100.0:
            x, note = None, "OUT_OF_RANGE"
        if x is None:
            notes.append((key, note))
        obs.append(Observation(key, x, at, _src(spec["entity"]), NORMALIZED, raw=raw, quality=quality))

    if _aware(history_end):
        obs.append(Observation("history.hourly", True, history_end, "recorder:statistics", NORMALIZED))
    for day in FORECAST_DAYS:
        srcs = emap.pv_forecast_sources.get(day, {})
        if not srcs:
            continue
        raw_vals = {name: numeric_value(states.get(eid), "kWh")[0] for name, eid in srcs.items()}
        times = [observed_time(states.get(eid)) for eid in srcs.values()]
        known = [t for t in times if t is not None]
        obs += forecast_observations(day, raw_vals, max(known) if known else None)
    return SourceResult(Snapshot.of(now, obs), tuple(readings), tuple(notes))
