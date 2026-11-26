#!/usr/bin/env python3
"""runtime/sources.py and runtime/history_source.py: HA state views -> Snapshot + SiteReadings, recorder rows -> History.

  * 'unavailable' / 'unknown' / empty / non-numeric / non-finite / an unsupported unit -> MISSING, never 0; a unit
    attribute that is not a string (a list, a mapping, a number) is unsupported, never an exception;
  * a canonical false zero with a valid raw SOC -> the raw value is used; a canonical zero alone -> missing;
  * unchanged values with a moving poll-text change -> fresh (the quality layer, fed by these observation times);
  * a frozen poll text -> stale; a replayed poll text after a reconnect -> no new change; the first sighting is not a change;
  * a missing poll-text mapping -> no liveness reading -> the quality layer BLOCKs (LIVENESS_MISSING);
  * the entity map is strict (unknown keys, placeholders and malformed specs are refused), and its refusal text names
    the field path only, never the offending value (that is kept for a debug line); the configuration poll's liveness
    entity or online entity equal to the telemetry poll-text entity is refused (A33, RT-3), in either key order; two
    boolean gate readings (tou.enabled, tou.grid_charge_enabled, supervision.stable) on one entity are refused (A36,
    RR-3), in either key order, by field path only; any of them on the configuration poll's online entity (either
    direction, either key order) and battery.soc_raw_pct on the battery.soc signal's entity are refused (A39, RT3-1 /
    RT3B-1, RT3B-2), by field path only;
  * a rate table from the day events (A38 Part B, CCR-RT-DAYS): the list form (2 or 3 `{entity, attribute}` in day
    order) parses for the two rate tables only, each part as strictly as the single form, the same entity twice is
    refused by position; the rows merge in mapped order (144 rows for three days, the engine's parse unchanged); a part
    that is unusable, has no attribute, a null or an empty list contributes nothing (the next day before publication,
    the previous day missing); a repeated row (same start and end as instants, same rate) is collapsed; a conflicting
    repeat, a partial overlap, rows out of order (the events mapped in reverse, or one event's rows reversed), a
    contributing attribute that is not a list and a row whose times are unusable refuse the whole table; a gap is kept
    for the engine (TARIFF_GAP); nothing contributing is TABLE_MISSING; the merged reading is as old as its oldest
    contributing part (1200 s: not fresh under 900 s), a refused fresh_by time withholds it, a part dated in the future
    makes it future-dated (not fresh); 'the same rate' is exact (RT4B-1, A42): rates 0.0001 GBP/kWh apart (0.30 against
    0.3001) are refused (TABLE_ROWS_OVERLAP) in either event order, an int and a float of equal value collapse;
  * one rate event under two tariff tables (A42, RT4-2): the same entity and attribute named by two of
    tariff.import_rates, tariff.export_rates and tariff.events, every day event of a list counted, is refused by field
    path only (the later key in code order against the earlier, whatever the site file's key order); the same entity
    under another attribute is accepted;
  * the source notes (A42, RT4-1 (b)): every note made anywhere in this suite is a contract key (NOTE_KEYS) and a code
    of the closed SOURCE_NOTE_CODES, and every code of it is produced on its refusal path, so a note never carries an
    entity id, an attribute name, a state text or a site number; the vocabulary matches the code literals of
    runtime/sources.py (a new literal is either a note code or a declared non-note code); public_notes keeps every such
    note and withholds (counts) anything else; engine_link.compute puts exactly public_notes' list in the diagnostics
    (RV8-4: forged notes added to a real build are withheld and counted, the real ones kept, no forged text anywhere);
  * the diagnostics' signal names (A45, RV9-3): the snapshot names a PV forecast observation with its source name (site
    text); public_signals shows a contract signal by its name and a PV forecast observation as pv.forecast.<day>.s<NNN>
    only, in order, and withholds (counts) any other name; engine_link.compute puts exactly that list in the
    diagnostics, with no source name anywhere in them;
  * the TOU slot table, schema v2 (foundation contract 13.2): exactly six slots of six entities each are accepted (five,
    seven, the start / target-only v1 shape, an unknown field and one entity used twice are refused); every slot entity
    is fetched; the dongle's literal 'None' is a value, Home Assistant's 'unavailable' / 'unknown' is null; flags_raw is
    a whole number 0..65535; an unknown start makes that start and the previous end null and the table is still
    published (never a v1 table, never a guess);
  * the configuration-poll liveness (13.3): published only from config_liveness_at (keyword only) and only while the
    configuration-online entity is exactly 'on', never parsed from the poll text; every configuration-poll reading is
    observed at the older of the telemetry and configuration liveness times and withheld without either (the quality
    layer then blocks the items resting on them);
  * the overlay (13.2): NONE only when every entity is exactly 'off', ACTIVE when any is exactly 'on', else withheld;
  * the raise-only reserve preference (13.7, A2 runtime half): unmapped -> no reading; mapped -> a reading every cycle,
    its number in 0..100, otherwise value None (never dropped, never 0);
  * `fresh_by: refreshed_at` (a bridge sensor's render time) can only make a reading older; a stale, unparseable, naive,
    future or disagreeing render time withholds the reading (the item BLOCKs);
  * attribute readings (CCR-R1): a numeric reading aged by its own report time may name `attribute` (and one nested
    `key`); a non-numeric value is MISSING; unknown spec keys are still refused;
  * the harness's owner decisions give the TOU classification inputs an I-D6 limit exactly when the engine accepts them;
  * only generic placeholder-style ids (test_*) are used here.
Plain script, offline; exits 1 on any failure.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(1, str(Path(__file__).resolve().parent))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


from custom_components.ecco_intelligence.runtime import engine_link, history_source, sources  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence import tariff as tf  # noqa: E402
from intelligence.advisory_contract import CycleInputs, SiteFacts, Versions  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.quality import assess_inputs  # noqa: E402

UTC = timezone.utc
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)


def view(state, unit=None, changed=None, reported=None, attrs=None, updated=None):
    a = dict(attrs or {})
    if unit is not None:
        a["unit_of_measurement"] = unit
    ch = changed or NOW - timedelta(hours=1)
    return {"state": state, "attributes": a, "last_changed": ch, "last_updated": updated or ch,
            "last_reported": reported or ch}


EMAP = sources.parse_entity_map(H.site_profile())


def states_fresh(now=NOW, **over):
    """Views for every mapped entity (values changed 3 h ago, as the dongle publishes only changes)."""
    class _S:
        def __init__(self):
            self._states = {}

        def seed(self, entity_id, state, attributes=None, *, changed_at=None, reported_at=None):
            self._states[entity_id] = view(state, None, changed_at, reported_at or now, attributes)
    s = _S()
    H.seed_fresh_states(s, now)
    out = dict(s._states)
    out.update(over)
    return out


def ages_for(src, decisions=None, now=NOW):
    ds = decisions if decisions is not None else sd.DecisionSet.from_mapping(H.owner_decisions(), source="site_local")
    inputs = CycleInputs(now=now, snapshot=src.snapshot, site_readings=src.site_readings, decisions=ds,
                         site_facts=SiteFacts(6.0, 51.5, -0.1))
    return assess_inputs(inputs)


def fresh(q, key):
    st = q.ages.get(key)
    return st is not None and st.fresh


def blocks(q, code, item, input_key=None):
    """True when the quality layer BLOCKs `item` with `code` (for `input_key`, when given). The minimal CycleInputs here
    carry no history, so every item is blocked for that reason; a test names the finding it is about."""
    return any(f.code == code and f.severity == "BLOCK" and f.subject == item
               and (input_key is None or ("input", input_key) in f.evidence) for f in q.findings)


def refused(prof) -> sources.EntityMapError | None:
    try:
        sources.parse_entity_map(prof)
    except sources.EntityMapError as exc:
        return exc
    return None


def with_readings(**changes):
    """A site profile whose reading map is READING_MAP with `changes` (a value None removes the key)."""
    rm = {k: v for k, v in H.READING_MAP.items() if k not in changes or changes[k] is not None}
    rm.update({k: v for k, v in changes.items() if v is not None})
    return H.site_profile(readings=rm)


LIVE = NOW - timedelta(seconds=20)                    # the telemetry poll text's change time
CFG = NOW - timedelta(seconds=H.CONFIG_POLL_AGE_S)    # the configuration poll text's change time


ALL_RESULTS: list = []                                # every build() result, for the A42 source-notes check


def build(states=None, emap=None, live=LIVE, cfg=CFG, history_end=NOW - timedelta(minutes=50)):
    src = sources.build_sources(NOW, states if states is not None else states_fresh(), emap or EMAP, live, history_end,
                                config_liveness_at=cfg)
    ALL_RESULTS.append(src)
    return src


def rmap(src):
    return {r.key: r for r in src.site_readings}


print("== value parsing: missing is never 0")
for raw in ("unavailable", "unknown", "", "  ", "none", "abc", "nan", "inf", "-inf", "1,5", "0x10", "true", "1_000"):
    x, note = sources.numeric_value(view(raw, "W"), "W")
    check(f"state {raw!r} -> missing (never 0)", x is None, f"{x} {note}")
check("a None view -> missing", sources.numeric_value(None, "W")[0] is None)
check("'450' W -> 450.0", sources.numeric_value(view("450", "W"), "W")[0] == 450.0)
check("'0.45' kW -> 450.0 W", sources.numeric_value(view("0.45", "kW"), "W")[0] == 450.0)
check("'12' with an unsupported unit (mA) -> missing", sources.numeric_value(view("12", "mA"), "W")[0] is None)
check("'12' with no unit attribute -> taken in the canonical unit", sources.numeric_value(view("12"), "W")[0] == 12.0)
check("'0' W is a real 0 W (a power reading, not a false zero)", sources.numeric_value(view("0", "W"), "W")[0] == 0.0)
for label, odd in (("a list", ["W"]), ("a mapping", {"u": "W"}), ("a number", 1), ("a boolean", True)):
    try:
        res = sources.numeric_value(view("5", odd), "W")
        check(f"a unit attribute that is {label} -> missing, UNIT_UNSUPPORTED (no exception)", res == (None, "UNIT_UNSUPPORTED"),
              str(res))
    except Exception as exc:  # noqa: BLE001
        check(f"a unit attribute that is {label} -> missing, UNIT_UNSUPPORTED (no exception)", False, type(exc).__name__)
check("booleans are not numbers", sources.parse_number(True) is None and sources.parse_number(False) is None)
check("bool_value: on/off/true/false; anything else None",
      sources.bool_value(view("on")) is True and sources.bool_value(view("off")) is False
      and sources.bool_value(view("unavailable")) is None and sources.bool_value(view("1")) is None)
check("hhmm: '1:00' / '04:30:00' / '24:00' normalised, '25:00' / '12:60' / 'x' refused",
      sources.hhmm("1:00") == "01:00" and sources.hhmm("04:30:00") == "04:30" and sources.hhmm("24:00") == "24:00"
      and sources.hhmm("25:00") is None and sources.hhmm("12:60") is None and sources.hhmm("x") is None)
check("published_text: the dongle's literal 'None' is a value; only 'unavailable' / 'unknown' / '' / absent are null; "
      "nothing is trimmed or case-folded",
      sources.published_text(view("None")) == "None" and sources.published_text(view("Grid + Generator")) == "Grid + Generator"
      and sources.published_text(view(" Grid")) == " Grid" and sources.published_text(view("unavailable")) is None
      and sources.published_text(view("unknown")) is None and sources.published_text(view("")) is None
      and sources.published_text(None) is None and sources.published_text({"state": 1}) is None)
check("whole_number: '1' / '1.0' / '65535' read, '1.5' / '65536' / '-1' / 'None' / 'abc' refused",
      sources.whole_number(view("1"), 0, 65535) == 1 and sources.whole_number(view("1.0"), 0, 65535) == 1
      and sources.whole_number(view("65535"), 0, 65535) == 65535
      and all(sources.whole_number(view(s), 0, 65535) is None for s in ("1.5", "65536", "-1", "None", "abc", "unavailable")))
check("parse_time: an aware ISO text or datetime is read; a naive, date-only or junk value is refused",
      sources.parse_time("2030-01-15T20:58:00+00:00") == NOW - timedelta(minutes=2)
      and sources.parse_time(NOW) == NOW and sources.parse_time("2030-01-15T20:58:00") is None
      and sources.parse_time(datetime(2030, 1, 15)) is None and sources.parse_time("2030-01-15") is None
      and sources.parse_time("x") is None and sources.parse_time(5) is None and sources.parse_time("9" * 100) is None)

print("== the entity map is strict")
_slots = H.tou_slot_spec()
bad_maps = {
    "unknown top key": {"shadow_runtime": {"signals": {}, "extra": 1}},
    "unknown signal": {"shadow_runtime": {"signals": {"battery.socx": {"entity": "sensor.test_a"}}}},
    "placeholder id": {"shadow_runtime": {"signals": {"battery.soc": {"entity": "sensor.<slug>_ecco_battery_soc"}}}},
    "upper-case id": {"shadow_runtime": {"signals": {"battery.soc": {"entity": "sensor.Test_A"}}}},
    "unknown reading": {"shadow_runtime": {"readings": {"battery.socx": {"entity": "sensor.test_a"}}}},
    "unknown spec key": {"shadow_runtime": {"readings": {"battery.soc_raw_pct": {"entity": "sensor.test_a", "x": 1}}}},
    "healthy_states missing": {"shadow_runtime": {"signals": {"inverter.healthy": {"entity": "sensor.test_a"}}}},
    "bad sign": {"shadow_runtime": {"signals": {"grid.power": {"entity": "sensor.test_a", "sign": 2}}}},
    "seven TOU slots": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": _slots + [_slots[0]]}}}},
    "five TOU slots": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": _slots[:5]}}}},
    "the v1 TOU spec (start and target only)": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": [
        {"start": s["start"], "target_soc": s["target_soc"]} for s in _slots]}}}},
    "a TOU slot without its charge source": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": [
        {k: v for k, v in s.items() if k != "charge_source"} for s in _slots]}}}},
    "an unknown TOU slot field": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": [
        dict(s, voltage="sensor.test_v%d" % i) for i, s in enumerate(_slots)]}}}},
    "a TOU slot entity used twice": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": [
        dict(s, charge_source=_slots[0]["charge_source"]) if i == 3 else s for i, s in enumerate(_slots)]}}}},
    "TOU slots not a list": {"shadow_runtime": {"readings": {"tou.slot_table": {"slots": {"1": _slots[0]}}}}},
    "table without attribute": {"shadow_runtime": {"readings": {"tariff.import_rates": {"entity": "event.test_a"}}}},
    "config liveness without the online entity": {"shadow_runtime": {"readings": {
        "liveness.config_poll_changed_at": {"entity": "sensor.test_config_poll_text"}}}},
    "config liveness with an invalid online entity": {"shadow_runtime": {"readings": {
        "liveness.config_poll_changed_at": {"entity": "sensor.test_c", "online_entity": "binary_sensor.<slug>_online"}}}},
    "overlay as a plain entity": {"shadow_runtime": {"readings": {"tou.overlay_state": {"entity": "binary_sensor.test_o"}}}},
    "overlay with no entities": {"shadow_runtime": {"readings": {"tou.overlay_state": {"entities": []}}}},
    "overlay listing one entity twice": {"shadow_runtime": {"readings": {"tou.overlay_state": {
        "entities": ["binary_sensor.test_o", "binary_sensor.test_o"]}}}},
    "overlay with seventeen entities": {"shadow_runtime": {"readings": {"tou.overlay_state": {
        "entities": [f"binary_sensor.test_o{i}" for i in range(17)]}}}},
}
for label, prof in bad_maps.items():
    check(f"refused: {label}", refused(prof) is not None)
check("no shadow_runtime block -> EMPTY_MAP (present False)", sources.parse_entity_map({"site": {}}) is sources.EMPTY_MAP)
echo_maps = {
    "an invalid entity id": ({"shadow_runtime": {"signals": {"battery.soc": {"entity": "sensor.Site_Private_Name"}}}},
                             "Site_Private_Name"),
    "an unknown signal key": ({"shadow_runtime": {"signals": {"sensor.site_private_key": {"entity": "sensor.test_a"}}}},
                              "site_private_key"),
    "an unknown top key": ({"shadow_runtime": {"site_private_top": {}}}, "site_private_top"),
    "a bad source name": ({"shadow_runtime": {"pv_forecast_sources": {"tomorrow": {"Site-Private-Src": "sensor.test_a"}}}},
                          "Site-Private-Src"),
    "a source's invalid id": ({"shadow_runtime": {"pv_forecast_sources": {"tomorrow": {"site_private_src": "sensor.X"}}}},
                              "site_private_src"),
    "a TOU slot entity used twice": ({"shadow_runtime": {"readings": {"tou.slot_table": {"slots": [
        dict(s, mode="sensor.site_private_twice") if i in (1, 4) else s for i, s in enumerate(_slots)]}}}},
        "site_private_twice"),
    "an invalid overlay entity": ({"shadow_runtime": {"readings": {"tou.overlay_state": {
        "entities": ["binary_sensor.Site_Private_Overlay"]}}}}, "Site_Private_Overlay"),
    "an invalid online entity": ({"shadow_runtime": {"readings": {"liveness.config_poll_changed_at": {
        "entity": "sensor.test_c", "online_entity": "binary_sensor.Site_Private_Online"}}}}, "Site_Private_Online"),
    "an unknown fresh_by attribute": ({"shadow_runtime": {"readings": {"limits.max_grid_charge_w": {
        "entity": "sensor.test_a", "fresh_by": "site_private_attr"}}}}, "site_private_attr"),
    "an invalid attribute name": ({"shadow_runtime": {"readings": {"capacity.fe1_wh_per_pct": {
        "entity": "sensor.test_a", "attribute": "Site-Private-Attr"}}}}, "Site-Private-Attr"),
}
for label, (prof, secret) in echo_maps.items():
    exc = refused(prof)
    if exc is None:
        check(f"refused without echoing the value: {label}", False, "accepted")
        continue
    check(f"refused without echoing the value: {label}", secret not in str(exc) and secret not in exc.public, str(exc))
    if label != "a source's invalid id":          # a source name is replaced by its position, even in the detail
        check(f"... the value is kept in the debug detail: {label}", secret in exc.detail, exc.detail)
print("== A33 (RT-3): the configuration poll's liveness entity and online entity differ from the telemetry poll text")
_tel_spec = H.READING_MAP[sd.LIVENESS_KEY]
_cfg_spec = H.READING_MAP[sd.CONFIG_LIVENESS_KEY]
_cfg_path = f"shadow_runtime.readings.{sd.CONFIG_LIVENESS_KEY}"
_tel_path = f"shadow_runtime.readings.{sd.LIVENESS_KEY}"
for _field, _path in (("entity", _cfg_path), ("online_entity", f"{_cfg_path}.online_entity")):
    for _order in ("the telemetry key first", "the configuration key first"):
        _pair = [(sd.LIVENESS_KEY, _tel_spec), (sd.CONFIG_LIVENESS_KEY, dict(_cfg_spec, **{_field: _tel_spec["entity"]}))]
        _rm = dict(_pair if _order == "the telemetry key first" else _pair[::-1])
        exc = refused(H.site_profile(readings=dict(H.READING_MAP, **_rm) if _order == "the telemetry key first" else
                                     dict(_rm, **{k: v for k, v in H.READING_MAP.items() if k not in _rm})))
        check(f"refused: the configuration-poll {_field} equal to the telemetry poll-text entity ({_order}), by field path "
              "only (the entity id only in the debug detail)",
              exc is not None and exc.public.startswith(f"{_path}: the same entity as {_tel_path}")
              and _tel_spec["entity"] not in exc.public and _tel_spec["entity"] in exc.detail,
              "accepted" if exc is None else exc.public)
check("non-vacuity: distinct telemetry and configuration poll texts and online entity are accepted (the harness map)",
      refused(H.site_profile()) is None and EMAP.readings[sd.CONFIG_LIVENESS_KEY]["entity"] != _tel_spec["entity"]
      and EMAP.readings[sd.CONFIG_LIVENESS_KEY]["online_entity"] != _tel_spec["entity"])
check("with the telemetry poll text unmapped nothing is compared (that map is accepted; the missing telemetry liveness "
      "BLOCKs through the quality layer)",
      refused(H.site_profile(readings={sd.CONFIG_LIVENESS_KEY: dict(_cfg_spec, entity=_tel_spec["entity"])})) is None)
print("== A36 (RR-3): the boolean gate readings (the two TOU enables, supervision.stable) each need their own entity")
check("the boolean gate readings are exactly supervision.stable, tou.enabled and tou.grid_charge_enabled (every 'bool' "
      "site reading, in the contract's order: a new one joins the check)",
      sources.BOOL_GATE_KEYS == ("supervision.stable", "tou.enabled", "tou.grid_charge_enabled")
      and sources.BOOL_GATE_KEYS == tuple(k for k, u in ac.SITE_READING_KEYS.items() if u == "bool"),
      str(sources.BOOL_GATE_KEYS))
_rp = "shadow_runtime.readings."
for _later, _earlier in (("tou.grid_charge_enabled", "tou.enabled"), ("tou.enabled", "supervision.stable"),
                         ("tou.grid_charge_enabled", "supervision.stable")):
    _shared = H.READING_MAP[_earlier]["entity"]
    for _order in ("in the contract's order", "in reverse order"):
        _rm = dict(H.READING_MAP, **{_later: {"entity": _shared}})
        if _order == "in reverse order":
            _rm = dict(reversed(list(_rm.items())))
        exc = refused(H.site_profile(readings=_rm))
        check(f"refused: {_later} mapped to the entity of {_earlier} ({_order} in the site file), by field path only "
              "(the entity id only in the debug detail)",
              exc is not None and exc.public.startswith(f"{_rp}{_later}: the same entity as {_rp}{_earlier}")
              and _shared not in exc.public and _shared in exc.detail, "accepted" if exc is None else exc.public)
_ge = H.READING_MAP["tou.grid_charge_enabled"]["entity"]
exc = refused(H.site_profile(readings=dict(H.READING_MAP, **{"tou.enabled": {"entity": _ge},
                                                             "supervision.stable": {"entity": _ge}})))
check("all three on one entity: refused at the first pair in the contract's order (tou.enabled against supervision.stable)",
      exc is not None and exc.public.startswith(f"{_rp}tou.enabled: the same entity as {_rp}supervision.stable"),
      "accepted" if exc is None else exc.public)
check("non-vacuity: the harness map (three distinct entities) is accepted and keeps all three",
      refused(H.site_profile()) is None and len({EMAP.readings[k]["entity"] for k in sources.BOOL_GATE_KEYS}) == 3)
check("only mapped gates are compared: one enable alone, or both enables on distinct entities without supervision.stable, "
      "is accepted",
      refused(H.site_profile(readings={"tou.enabled": {"entity": _ge}})) is None
      and refused(H.site_profile(readings={k: v for k, v in H.READING_MAP.items() if k != "supervision.stable"})) is None)
print("== A39 (RT3-1 / RT3B-1): no boolean gate reading on the configuration poll's online entity")
_online = H.READING_MAP[sd.CONFIG_LIVENESS_KEY]["online_entity"]
_online_path = f"{_rp}{sd.CONFIG_LIVENESS_KEY}.online_entity"
for _gate in sources.BOOL_GATE_KEYS:
    for _order in ("in the contract's order", "in reverse order"):
        _rm = dict(H.READING_MAP, **{_gate: {"entity": _online}})
        if _order == "in reverse order":
            _rm = dict(reversed(list(_rm.items())))
        exc = refused(H.site_profile(readings=_rm))
        check(f"refused: {_gate} mapped to the configuration-online entity ({_order} in the site file), by field path only "
              "(the entity id only in the debug detail)",
              exc is not None and exc.public.startswith(f"{_rp}{_gate}: the same entity as {_online_path}")
              and _online not in exc.public and _online in exc.detail, "accepted" if exc is None else exc.public)
    _gate_eid = H.READING_MAP[_gate]["entity"]
    exc = refused(H.site_profile(readings=dict(H.READING_MAP, **{sd.CONFIG_LIVENESS_KEY: dict(
        H.READING_MAP[sd.CONFIG_LIVENESS_KEY], online_entity=_gate_eid)})))
    check(f"refused: the configuration-online entity mapped to {_gate}'s entity (the reverse copy-paste), by field path only",
          exc is not None and exc.public.startswith(f"{_rp}{_gate}: the same entity as {_online_path}")
          and _gate_eid not in exc.public and _gate_eid in exc.detail, "accepted" if exc is None else exc.public)
check("non-vacuity: the harness map's online entity differs from every boolean gate and the map is accepted",
      refused(H.site_profile()) is None and _online not in {EMAP.readings[k]["entity"] for k in sources.BOOL_GATE_KEYS})
check("without the configuration-poll liveness mapped nothing is compared with it (a gate alone is accepted)",
      refused(H.site_profile(readings={"tou.enabled": {"entity": _online}})) is None)
print("== A39 (RT3B-2): battery.soc_raw_pct never on the battery.soc signal's entity and attribute")
_canon = H.SIGNAL_MAP["battery.soc"]["entity"]
exc = refused(with_readings(**{"battery.soc_raw_pct": {"entity": _canon}}))
check("refused: battery.soc_raw_pct mapped to the canonical battery.soc entity, by field path only (the entity id only in "
      "the debug detail)",
      exc is not None and exc.public.startswith("shadow_runtime.readings.battery.soc_raw_pct: the same entity as "
                                                "shadow_runtime.signals.battery.soc")
      and _canon not in exc.public and _canon in exc.detail, "accepted" if exc is None else exc.public)
_raw = H.READING_MAP["battery.soc_raw_pct"]["entity"]
exc = refused(H.site_profile(signals=dict(H.SIGNAL_MAP, **{"battery.soc": {"entity": _raw}})))
check("refused: the battery.soc signal mapped to the raw SOC reading's entity (the reverse copy-paste)",
      exc is not None and exc.public.startswith("shadow_runtime.readings.battery.soc_raw_pct: the same entity as")
      and _raw not in exc.public, "accepted" if exc is None else exc.public)
check("non-vacuity: distinct raw and canonical SOC entities (the harness map) are accepted; either one alone is accepted",
      refused(H.site_profile()) is None and _raw != _canon
      and refused(with_readings(**{"battery.soc_raw_pct": None})) is None
      and refused(H.site_profile(signals={k: v for k, v in H.SIGNAL_MAP.items() if k != "battery.soc"},
                                 readings=dict(H.READING_MAP, **{"battery.soc_raw_pct": {"entity": _canon}}))) is None)
st_odd = states_fresh(**{H.eid("sensor", "battery_output_power"): view("400", ["W"])})
try:
    src_odd = sources.build_sources(NOW, st_odd, EMAP, NOW - timedelta(seconds=20))
    odd_obs = src_odd.snapshot.get("battery.power")
    check("one mapped entity with a list-valued unit: that signal is missing, the rest is built (no exception)",
          odd_obs is not None and odd_obs.value is None and ("battery.power", "UNIT_UNSUPPORTED") in src_odd.notes
          and src_odd.snapshot.get("grid.power").value is not None, f"{odd_obs} {src_odd.notes[:4]}")
except Exception as exc:  # noqa: BLE001
    check("one mapped entity with a list-valued unit: that signal is missing, the rest is built (no exception)", False,
          type(exc).__name__)
check("the test map parses and names only test_* ids",
      EMAP.present and all(e.split(".", 1)[1].startswith("test_") for e in EMAP.entity_ids()), str(EMAP.entity_ids()[:3]))

print("== the TOU slot table, schema v2 (13.2): the spec and the fetched ids")
_ids = set(EMAP.entity_ids())
check("the v2 spec (exactly six slots, each mapping all six entities) is accepted",
      len(EMAP.readings["tou.slot_table"]["slots"]) == ac.TOU_SLOT_TABLE_ROWS
      and all(set(s) == set(sources.TOU_SLOT_FIELDS) for s in EMAP.readings["tou.slot_table"]["slots"]))
check("entity_ids() covers all 36 slot entities (start, target, charge source, power, flags, mode)",
      {H.slot_eid(i, f) for i in range(1, 7) for f in H.TOU_SLOT_FIELDS} <= _ids
      and len({H.slot_eid(i, f) for i in range(1, 7) for f in H.TOU_SLOT_FIELDS}) == 36)
check("entity_ids() covers the configuration-poll text, the configuration-online entity, both enables, every overlay "
      "entity and the raise helper",
      {H.CONFIG_POLL_TEXT, H.CONFIG_ONLINE, H.TOU_ENABLED, H.GRID_CHARGE_ENABLED, H.RESERVE_RAISE_HELPER,
       *H.OVERLAY_ENTITIES} <= _ids)
check("the slot fields map onto the contract's row keys (slot and end are derived, never mapped)",
      set(sources.TOU_SLOT_FIELD_ROW_KEYS.values()) | {"slot", "end"} == set(ac.TOU_SLOT_ROW_KEYS)
      and tuple(sources.TOU_SLOT_FIELD_ROW_KEYS) == sources.TOU_SLOT_FIELDS == tuple(H.TOU_SLOT_FIELDS))

print("== the TOU slot table, schema v2: the value")
src = build()
rk = rmap(src)
tbl = rk["tou.slot_table"].value
check("six rows in slot order, each with exactly the contract's row keys in order",
      len(tbl) == 6 and [r["slot"] for r in tbl] == [1, 2, 3, 4, 5, 6]
      and all(tuple(r) == ac.TOU_SLOT_ROW_KEYS for r in tbl), str(tbl[:1]))
check("each slot ends at the next start; slot 6 runs into slot 1",
      [r["start"] for r in tbl] == H.TOU_STARTS and [r["end"] for r in tbl] == H.TOU_STARTS[1:] + H.TOU_STARTS[:1])
check("the charge source and mode pass through as published: 'Grid' on the grid slot, the literal 'None' elsewhere "
      "(a value, never null)",
      [r["charge_source"] for r in tbl] == ["Grid", "None", "None", "None", "None", "None"]
      and all(r["mode"] == "None" for r in tbl), str([(r["charge_source"], r["mode"]) for r in tbl]))
check("flags_raw is an int (1 on the grid slot, 0 elsewhere); power in W; target in %",
      [r["flags_raw"] for r in tbl] == [1, 0, 0, 0, 0, 0] and all(type(r["flags_raw"]) is int for r in tbl)
      and all(r["power_w"] == 5000.0 for r in tbl) and [r["target_soc_pct"] for r in tbl] == [80.0] + [20.0] * 5)
check("no field is null on a complete table (no note)", ("tou.slot_table", "SLOT_FIELD_UNKNOWN") not in src.notes
      and all(r[k] is not None for r in tbl for k in ac.TOU_SLOT_ROW_KEYS))


def slot_case(field, i, state, unit=None):
    st = states_fresh(**{H.slot_eid(i, field): view(state, unit)})
    s = build(st)
    return rmap(s).get("tou.slot_table"), s.notes


for state in ("unavailable", "unknown"):
    r_, notes_ = slot_case("charge_source", 3, state)
    t_ = r_.value if r_ else None
    check(f"a charge source {state!r} -> that field null, the other rows unchanged, the table still published (note)",
          t_ is not None and t_[2]["charge_source"] is None and t_[0]["charge_source"] == "Grid"
          and t_[1]["charge_source"] == "None" and ("tou.slot_table", "SLOT_FIELD_UNKNOWN") in notes_, str(t_ and t_[2]))
    r_, _n = slot_case("mode", 2, state)
    check(f"a mode {state!r} -> that field null", r_ is not None and r_.value[1]["mode"] is None)
r_, _n = slot_case("charge_source", 4, "Grid + Generator")
check("'Grid + Generator' passes through exactly (the planning layer classifies it)",
      r_.value[3]["charge_source"] == "Grid + Generator")
r_, _n = slot_case("mode", 4, "Unknown 0x14")
check("the dongle's 'Unknown 0x14' mode passes through exactly (the planning layer refuses it)",
      r_.value[3]["mode"] == "Unknown 0x14")
r_, _n = slot_case("charge_source", 5, "none")
check("a lower-case 'none' is passed through as received, never folded into the dongle's 'None'",
      r_.value[4]["charge_source"] == "none")
st_abs = states_fresh()
del st_abs[H.slot_eid(2, "charge_source")]
check("an absent slot entity -> that field null", rmap(build(st_abs))["tou.slot_table"].value[1]["charge_source"] is None)
for state, want in (("1.0", 1), ("1.5", None), ("65536", None), ("-1", None), ("abc", None), ("unavailable", None),
                    ("65535", 65535)):
    r_, _n = slot_case("flags_raw", 1, state)
    check(f"flags_raw {state!r} -> {want!r}", r_.value[0]["flags_raw"] == want, str(r_.value[0]["flags_raw"]))
for state, unit, want in (("4.5", "kW", 4500.0), ("-5", "W", None), ("unavailable", "W", None), ("12", "mA", None),
                          ("0", "W", 0.0)):
    r_, _n = slot_case("power", 1, state, unit)
    check(f"slot power {state!r} {unit} -> {want!r} (0 W is a real 0: the planning layer blocks it)",
          r_.value[0]["power_w"] == want, str(r_.value[0]["power_w"]))
for state, want in (("140", None), ("-1", None), ("unknown", None), ("100", 100.0), ("0", 0.0)):
    r_, _n = slot_case("target_soc", 2, state, "%")
    check(f"slot target {state!r} % -> {want!r}", r_.value[1]["target_soc_pct"] == want)
r_, notes_ = slot_case("start", 3, "unknown")
t_ = r_.value if r_ else None
check("one slot start unknown -> that start and the previous slot's end null; six rows still published (the planning "
      "layer refuses the ring; never a shorter or v1 table)",
      t_ is not None and len(t_) == 6 and t_[2]["start"] is None and t_[1]["end"] is None and t_[2]["end"] == "16:00"
      and t_[0]["end"] == "04:30" and ("tou.slot_table", "SLOT_FIELD_UNKNOWN") in notes_, str(t_ and t_[1:3]))
r_, _n = slot_case("start", 3, "25:00")
check("an invalid start time -> null", r_.value[2]["start"] is None and r_.value[1]["end"] is None)
check("the runtime never builds a v1 table: every row carries the charge source, flags, mode and power keys",
      all({"charge_source", "flags_raw", "mode", "power_w"} <= set(r) for r in tbl))

print("== the configuration-poll liveness (13.3)")
check("the liveness reading is published from config_liveness_at: value = observed_at = that time, source the poll text",
      rk[sd.CONFIG_LIVENESS_KEY].value == CFG and rk[sd.CONFIG_LIVENESS_KEY].observed_at == CFG
      and rk[sd.CONFIG_LIVENESS_KEY].source == f"ha:{H.CONFIG_POLL_TEXT}" and not rk[sd.CONFIG_LIVENESS_KEY].problems())
_numeric_text = states_fresh(**{H.CONFIG_POLL_TEXT: view("1234", changed=NOW - timedelta(seconds=5))})
_none = build(_numeric_text, cfg=None)
check("... never parsed from the poll text's state (a numeric text with no change time passed -> no reading)",
      sd.CONFIG_LIVENESS_KEY not in rmap(_none) and (sd.CONFIG_LIVENESS_KEY, "NO_CONFIRMED_POLL_CHANGE") in _none.notes)
for state in ("off", "On", "on ", "ON", "unavailable", "unknown", "true", ""):
    s_ = build(states_fresh(**{H.CONFIG_ONLINE: view(state)}))
    check(f"configuration-online {state!r} (not exactly 'on') -> the configuration-poll observation is withheld",
          sd.CONFIG_LIVENESS_KEY not in rmap(s_) and (sd.CONFIG_LIVENESS_KEY, "CONFIGURATION_NOT_ONLINE") in s_.notes)
_st_no_online = states_fresh()
del _st_no_online[H.CONFIG_ONLINE]
check("configuration-online absent -> withheld", sd.CONFIG_LIVENESS_KEY not in rmap(build(_st_no_online)))
for label, t in (("in the future", NOW + timedelta(seconds=30)), ("naive", datetime(2030, 1, 15, 20, 59))):
    check(f"a configuration-poll change time {label} -> withheld", sd.CONFIG_LIVENESS_KEY not in rmap(build(cfg=t)))
_offline = build(states_fresh(**{H.CONFIG_ONLINE: view("off")}))
_unmapped = build(emap=sources.parse_entity_map(with_readings(**{sd.CONFIG_LIVENESS_KEY: None})))
for label, s_ in (("no change time", build(cfg=None)), ("configuration offline", _offline),
                  ("configuration liveness not mapped", _unmapped)):
    got = rmap(s_)
    check(f"{label}: every configuration-poll reading is withheld (NO_CONFIG_LIVENESS)",
          not (set(sd.CONFIG_POLL_READINGS) & set(got))
          and all((k, "NO_CONFIG_LIVENESS") in s_.notes for k in sd.CONFIG_POLL_READINGS),
          str(sorted(set(sd.CONFIG_POLL_READINGS) & set(got))))
    check(f"... the other dongle readings and signals are still there ({label})",
          {"battery.soc_raw_pct", "stop.dump_soc_pct", "inverter.clock_offset_s", sd.LIVENESS_KEY} <= set(got)
          and s_.snapshot.get("battery.soc").value == 55.0)
q_off = ages_for(_offline)
check("... and the quality layer then finds no fresh TOU table, so the charge-window items BLOCK (CHARGE_WINDOW_UNKNOWN)",
      not fresh(q_off, "tou.slot_table")
      and all(blocks(q_off, "CHARGE_WINDOW_UNKNOWN", i) for i in ("charge_target", "predicted_morning_soc")),
      str(sorted({(f.code, f.subject) for f in q_off.findings if f.severity == "BLOCK"})[:6]))
check("the configuration-poll readings are exactly the contract's set (no reading left on the telemetry time alone)",
      set(sd.CONFIG_POLL_READINGS) <= set(rk) and set(sd.CONFIG_POLL_READINGS) == {
          "tou.slot_table", "tou.current_target_soc_pct", "tou.enabled", "tou.grid_charge_enabled",
          "protection.shutdown_soc_pct", "capacity.reg204_ah"})
for label, live, cfg in (("the configuration poll is older", NOW - timedelta(seconds=20), NOW - timedelta(seconds=200)),
                         ("the telemetry poll is older", NOW - timedelta(seconds=150), NOW - timedelta(seconds=30))):
    got = rmap(build(live=live, cfg=cfg))
    older = min(live, cfg)
    check(f"{label}: every configuration-poll reading is observed at the older of the two times",
          all(got[k].observed_at == older for k in sd.CONFIG_POLL_READINGS),
          str({k: got[k].observed_at.isoformat() for k in sd.CONFIG_POLL_READINGS}))
    check(f"... the other dongle readings keep the telemetry time ({label})",
          all(got[k].observed_at == live for k in ("battery.soc_raw_pct", "stop.dump_soc_pct", "inverter.clock_offset_s")))
_nolive = build(live=None)
check("no telemetry liveness -> the configuration-poll readings are withheld as well (the older time is unknown)",
      not (set(sd.CONFIG_POLL_READINGS) & set(rmap(_nolive))) and sd.CONFIG_LIVENESS_KEY in rmap(_nolive))
check("both enables are read as booleans", rk["tou.enabled"].value is True and rk["tou.grid_charge_enabled"].value is True
      and rmap(build(states_fresh(**{H.TOU_ENABLED: view("off")})))["tou.enabled"].value is False)
check("an unavailable enable -> no reading (NOT_BOOLEAN)",
      "tou.grid_charge_enabled" not in rmap(build(states_fresh(**{H.GRID_CHARGE_ENABLED: view("unavailable")}))))

print("== the TOU overlay (13.2)")


def overlay_case(states_by_index=None):
    states_by_index = states_by_index or {}
    over = {H.OVERLAY_ENTITIES[i]: view(s) for i, s in states_by_index.items() if s is not None}
    st = states_fresh(**over)
    for i, s in states_by_index.items():
        if s is None:
            del st[H.OVERLAY_ENTITIES[i]]
    s_ = build(st)
    return rmap(s_).get("tou.overlay_state"), s_.notes


ov, _n = overlay_case()
check("every overlay entity exactly 'off' -> NONE", ov is not None and ov.value == "NONE" and not ov.problems())
ov, _n = overlay_case({1: "on"})
check("one overlay entity 'on' -> ACTIVE", ov is not None and ov.value == "ACTIVE")
ov, _n = overlay_case({0: "on", 2: "unavailable"})
check("'on' with another entity unavailable -> ACTIVE (an active overlay is known)", ov is not None and ov.value == "ACTIVE")
for label, case in (("unavailable", {2: "unavailable"}), ("unknown", {0: "unknown"}), ("'On' (not exactly on)", {1: "On"}),
                    ("'Off' (not exactly off)", {1: "Off"}), ("absent", {0: None}), ("'false'", {2: "false"})):
    ov, notes_ = overlay_case(case)
    check(f"one overlay entity {label}, the rest off -> no overlay reading at all", ov is None
          and ("tou.overlay_state", "OVERLAY_STATE_UNKNOWN") in notes_, str(ov))
_ov_times = states_fresh(**{H.OVERLAY_ENTITIES[0]: view("off", reported=NOW - timedelta(minutes=7)),
                            H.OVERLAY_ENTITIES[1]: view("off", reported=NOW - timedelta(minutes=2))})
_ov_r = rmap(build(_ov_times))["tou.overlay_state"]
if "tou.overlay_state" in sd.DONGLE_READINGS:
    check("the overlay is dongle telemetry: observed at the telemetry poll-text change time", _ov_r.observed_at == LIVE)
else:
    check("the overlay (until it joins DONGLE_READINGS) is observed at the OLDEST of its entities' times",
          _ov_r.observed_at == NOW - timedelta(minutes=7), str(_ov_r.observed_at))

print("== the raise-only reserve preference (13.7, A2 runtime half)")
sd_key = "pref.advisory_reserve_raise_pct"
_pref = rk.get(sd_key)
check("mapped and '0' -> the reading 0.0 (usable; never above any floor)", _pref is not None and _pref.value == 0.0
      and _pref.unit == "%" and not _pref.problems())
_p55 = rmap(build(states_fresh(**{H.RESERVE_RAISE_HELPER: view("55", "%", changed=NOW - timedelta(days=2))})))[sd_key]
check("mapped and '55' % -> 55.0, observed at its own state's time (a preference does not age)",
      _p55.value == 55.0 and _p55.observed_at == NOW - timedelta(days=2))
for state, unit in (("unavailable", "%"), ("unknown", "%"), ("abc", "%"), ("140", "%"), ("-1", "%"), ("nan", "%"),
                    ("55", "W"), ("100.5", "%")):
    s_ = build(states_fresh(**{H.RESERVE_RAISE_HELPER: view(state, unit)}))
    got = rmap(s_).get(sd_key)
    check(f"mapped and {state!r} {unit} -> still a reading, value None (never dropped, never 0)",
          got is not None and got.value is None and not got.problems() and any(k == sd_key for k, _c in s_.notes),
          str(got))
_st_nohelper = states_fresh()
del _st_nohelper[H.RESERVE_RAISE_HELPER]
_pa = rmap(build(_st_nohelper)).get(sd_key)
check("mapped but the entity absent -> a reading, value None, observed at the cycle time",
      _pa is not None and _pa.value is None and _pa.observed_at == NOW and not _pa.problems(), str(_pa))
check("100 and 0 are usable bounds", rmap(build(states_fresh(**{H.RESERVE_RAISE_HELPER: view("100", "%")})))[sd_key].value
      == 100.0)
_unm = build(emap=sources.parse_entity_map(with_readings(**{sd_key: None})))
check("not mapped -> no reading at all (only an unmapped helper means 'no raise')", sd_key not in rmap(_unm))
for label, spec in (("fresh_by", {"entity": H.RESERVE_RAISE_HELPER, "fresh_by": "refreshed_at"}),
                    ("attribute", {"entity": H.RESERVE_RAISE_HELPER, "attribute": "value"})):
    check(f"the raise helper takes no {label} (refused)", refused(with_readings(**{sd_key: spec})) is not None)

print("== fresh_by: refreshed_at (a bridge sensor's render time; it can only make a reading older)")
BRIDGE = "sensor.test_config_max_grid_charge_power"
FB_MAP = sources.parse_entity_map(with_readings(**{"limits.max_grid_charge_w": {"entity": BRIDGE, "fresh_by": "refreshed_at"}}))


def bridge(refreshed, updated, reported=NOW, state="5000"):
    attrs = {"unit_of_measurement": "W"}
    if refreshed is not ...:
        attrs["refreshed_at"] = refreshed
    return view(state, None, changed=NOW - timedelta(hours=5), reported=reported, attrs=attrs, updated=updated)


t120 = NOW - timedelta(seconds=120)
fb_ok = build(states_fresh(**{BRIDGE: bridge(t120.isoformat(), t120)}), FB_MAP)
check("refreshed_at equal to last_updated (both 120 s ago, last_reported now) -> observed 120 s ago, older than the "
      "plain rule's newest timestamp", rmap(fb_ok)["limits.max_grid_charge_w"].observed_at == t120
      and sources.observed_time(bridge(t120.isoformat(), t120)) == NOW)
fb_dt = build(states_fresh(**{BRIDGE: bridge(t120, t120)}), FB_MAP)
check("a datetime-valued refreshed_at is read too", rmap(fb_dt)["limits.max_grid_charge_w"].observed_at == t120)
fb_tol = build(states_fresh(**{BRIDGE: bridge((t120 - timedelta(seconds=3)).isoformat(), t120)}), FB_MAP)
check("refreshed_at 3 s before last_updated (one render) -> the older of the two",
      rmap(fb_tol)["limits.max_grid_charge_w"].observed_at == t120 - timedelta(seconds=3))
q_ok = ages_for(fb_ok)
check("... fresh under its 300 s I-D6 limit, so it blocks nothing",
      fresh(q_ok, "limits.max_grid_charge_w")
      and not blocks(q_ok, "INPUT_NOT_FRESH", "charge_target", "limits.max_grid_charge_w"))
stale_cases = {
    "a stale refreshed_at while another attribute keeps changing (last_updated now)":
        bridge((NOW - timedelta(hours=1)).isoformat(), NOW - timedelta(seconds=2)),
    "refreshed_at 6 s from last_updated": bridge((t120 - timedelta(seconds=6)).isoformat(), t120),
    "refreshed_at 30 s in the future": bridge((NOW + timedelta(seconds=30)).isoformat(), NOW),
    "refreshed_at 3 s in the future, within the tolerance of last_updated":
        bridge((NOW + timedelta(seconds=3)).isoformat(), NOW - timedelta(seconds=1)),
    "a naive refreshed_at": bridge("2030-01-15T20:58:00", t120),
    "an unparseable refreshed_at": bridge("yesterday", t120),
    "a numeric refreshed_at": bridge(1234567890, t120),
    "no refreshed_at attribute": bridge(..., t120),
}
for label, v in stale_cases.items():
    s_ = build(states_fresh(**{BRIDGE: v}), FB_MAP)
    q_ = ages_for(s_)
    check(f"{label} -> the reading is withheld (a FRESH_BY_ note) and the items requiring it BLOCK",
          "limits.max_grid_charge_w" not in rmap(s_) and any(k == "limits.max_grid_charge_w" and c.startswith("FRESH_BY_")
                                                            for k, c in s_.notes)
          and not fresh(q_, "limits.max_grid_charge_w")
          and blocks(q_, "INPUT_NOT_FRESH", "charge_target", "limits.max_grid_charge_w"),
          f"{[n for n in s_.notes if n[0] == 'limits.max_grid_charge_w']}")
check("non-vacuity: without fresh_by the same stale-render sensor counts as just reported (the rule is what blocks it)",
      rmap(build(states_fresh(**{"sensor.test_max_grid_charge_power": stale_cases[
          "a stale refreshed_at while another attribute keeps changing (last_updated now)"]})))[
          "limits.max_grid_charge_w"].observed_at == NOW)
_sig_map = sources.parse_entity_map(H.site_profile(signals={**H.SIGNAL_MAP, "reserve.ha_minimum_soc": {
    "entity": "sensor.test_config_minimum_reserve_soc", "fresh_by": "refreshed_at"}}))
_sig_ok = build(states_fresh(**{"sensor.test_config_minimum_reserve_soc": view(
    "20", "%", changed=NOW - timedelta(hours=2), reported=NOW, attrs={"refreshed_at": t120.isoformat()}, updated=t120)}),
    _sig_map)
check("fresh_by on the (non-dongle) reserve helper signal: observed at the render time",
      _sig_ok.snapshot.get("reserve.ha_minimum_soc").observed_at == t120
      and _sig_ok.snapshot.get("reserve.ha_minimum_soc").value == 20.0)
_sig_bad = build(states_fresh(**{"sensor.test_config_minimum_reserve_soc": view(
    "20", "%", changed=NOW - timedelta(hours=2), reported=NOW, attrs={"refreshed_at": "junk"}, updated=NOW)}), _sig_map)
check("... an unusable render time -> the signal has no observation time (never fresh) and a FRESH_BY_ note",
      _sig_bad.snapshot.get("reserve.ha_minimum_soc").observed_at is None
      and ("reserve.ha_minimum_soc", "FRESH_BY_UNPARSEABLE") in _sig_bad.notes)
for label, prof in (
        ("on a dongle reading", with_readings(**{"stop.dump_soc_pct": {"entity": "sensor.test_a", "fresh_by": "refreshed_at"}})),
        ("on a configuration-poll reading", with_readings(**{"tou.enabled": {"entity": "binary_sensor.test_a",
                                                                             "fresh_by": "refreshed_at"}})),
        ("on the telemetry liveness", with_readings(**{sd.LIVENESS_KEY: {"entity": "sensor.test_a", "fresh_by": "refreshed_at"}})),
        ("on a preference", with_readings(**{"pref.wear_cost_p_per_kwh": {"entity": "sensor.test_a", "fresh_by": "refreshed_at"}})),
        ("on a supervision reading (a dongle reading aged by the telemetry poll since WP-1)",
         with_readings(**{"supervision.stable": {"entity": "binary_sensor.test_a", "fresh_by": "refreshed_at"}})),
        ("on a dongle signal", H.site_profile(signals={**H.SIGNAL_MAP, "battery.soc": {"entity": "sensor.test_a",
                                                                                       "fresh_by": "refreshed_at"}})),
        ("naming another attribute", with_readings(**{"limits.max_grid_charge_w": {"entity": "sensor.test_a",
                                                                                   "fresh_by": "last_updated"}}))):
    check(f"fresh_by {label} -> refused", refused(prof) is not None)
check("fresh_by on a bridge-fed reading aged by its own report time (enum, table, number) is accepted",
      refused(with_readings(**{"capacity.fe1_basis": {"entity": "sensor.test_b", "fresh_by": "refreshed_at"},
                               "tariff.events": {"entity": "event.test_c", "attribute": "events",
                                                 "fresh_by": "refreshed_at"},
                               "efficiency.helper_pct": {"entity": "sensor.test_d", "fresh_by": "refreshed_at"}})) is None)

print("== attribute readings (CCR-R1)")
MODEL = "sensor.test_battery_runtime_model"
ATTR_MAP = sources.parse_entity_map(with_readings(**{"capacity.fe1_wh_per_pct": {"entity": MODEL, "attribute": "model",
                                                                                 "key": "learned_wh_per_pct"}}))


def model_view(value, state="ok"):
    return view(state, changed=NOW - timedelta(minutes=10), reported=NOW - timedelta(minutes=1),
                attrs={"model": {"learned_wh_per_pct": value, "basis": "measured"}, "flat_wh_per_pct": value})


_a = rmap(build(states_fresh(**{MODEL: model_view(342.0)}), ATTR_MAP)).get("capacity.fe1_wh_per_pct")
check("a nested attribute number is read (attribute 'model', key 'learned_wh_per_pct'), observed at its state's time",
      _a is not None and _a.value == 342.0 and _a.observed_at == NOW - timedelta(minutes=1) and not _a.problems(), str(_a))
_a2 = rmap(build(states_fresh(**{MODEL: model_view("341.5")}), ATTR_MAP))["capacity.fe1_wh_per_pct"]
check("... a numeric text too", _a2.value == 341.5)
_flat = sources.parse_entity_map(with_readings(**{"capacity.fe1_wh_per_pct": {"entity": MODEL,
                                                                              "attribute": "flat_wh_per_pct"}}))
check("a top-level attribute number is read", rmap(build(states_fresh(**{MODEL: model_view(300)}), _flat))[
    "capacity.fe1_wh_per_pct"].value == 300.0)
for label, v in (("non-numeric text", "abc"), ("a boolean", True), ("null", None), ("a list", [1]), ("not finite", "inf")):
    s_ = build(states_fresh(**{MODEL: model_view(v)}), ATTR_MAP)
    check(f"an attribute value that is {label} -> MISSING (no reading, never 0)", "capacity.fe1_wh_per_pct" not in rmap(s_)
          and any(k == "capacity.fe1_wh_per_pct" for k, _c in s_.notes))
s_ = build(states_fresh(**{MODEL: view("ok", attrs={"model": 5})}), ATTR_MAP)
check("a key under an attribute that is not a mapping -> MISSING (ATTRIBUTE_MISSING)",
      ("capacity.fe1_wh_per_pct", "ATTRIBUTE_MISSING") in s_.notes)
s_ = build(states_fresh(**{MODEL: model_view(342.0, state="unavailable")}), ATTR_MAP)
check("the entity unavailable -> MISSING although the attribute holds a number", "capacity.fe1_wh_per_pct" not in rmap(s_))
for label, spec in (("an unknown spec key", {"entity": MODEL, "attribute": "model", "x": 1}),
                    ("a key without an attribute", {"entity": MODEL, "key": "learned_wh_per_pct"}),
                    ("a non-text attribute", {"entity": MODEL, "attribute": 5})):
    check(f"refused: {label}", refused(with_readings(**{"capacity.fe1_wh_per_pct": spec})) is not None)
check("refused: an attribute on a dongle reading (dongle values map to dongle entities)",
      refused(with_readings(**{"battery.soc_raw_pct": {"entity": MODEL, "attribute": "soc"}})) is not None)
check("refused: an attribute on a non-numeric reading aged by its own report time (enum)",
      refused(with_readings(**{"capacity.fe1_basis": {"entity": MODEL, "attribute": "basis"}})) is not None)
check("refused: an attribute on a supervision reading (bool, a dongle reading since WP-1)",
      refused(with_readings(**{"supervision.stable": {"entity": MODEL, "attribute": "stable"}})) is not None)
_af = sources.parse_entity_map(with_readings(**{"capacity.fe1_wh_per_pct": {"entity": MODEL, "attribute": "model",
                                                                            "key": "learned_wh_per_pct",
                                                                            "fresh_by": "refreshed_at"}}))
_afv = view("ok", changed=t120, reported=NOW, updated=t120,
            attrs={"model": {"learned_wh_per_pct": 342.0}, "refreshed_at": t120.isoformat()})
check("an attribute reading may take fresh_by as well", rmap(build(states_fresh(**{MODEL: _afv}), _af))[
    "capacity.fe1_wh_per_pct"].observed_at == t120)

print("== A38 Part B (CCR-RT-DAYS): a rate table read from the day events, merged in day order")
PREV, CUR, NEXT = "event.test_previous_day_rates", "event.test_current_day_rates", "event.test_next_day_rates"
DAY_SPEC = [{"entity": PREV, "attribute": "rates"}, {"entity": CUR, "attribute": "rates"},
            {"entity": NEXT, "attribute": "rates"}]
DAYS_MAP = sources.parse_entity_map(with_readings(**{"tariff.import_rates": DAY_SPEC}))
IMP = "tariff.import_rates"


def day_rows(d: int, *, rate: float | None = None, fmt=lambda t: t.isoformat()) -> list[dict]:
    """The 48 half-hour rows of 2030-01-<d> (UTC, January: local time), 7.5 p from 00:30 to 05:30 and 30 p otherwise."""
    t0 = datetime(2030, 1, d, tzinfo=UTC)
    return [{"start": fmt(t0 + timedelta(minutes=30 * i)), "end": fmt(t0 + timedelta(minutes=30 * (i + 1))),
             "value_inc_vat": rate if rate is not None else (0.075 if 1 <= i < 11 else 0.30)} for i in range(48)]


def ev(rows=..., age_s: float = 300.0, state: str | None = None, extra: dict | None = None) -> dict:
    """A day event's view: its rows under `rates` (`...`: no such attribute), reported `age_s` before NOW."""
    t = NOW - timedelta(seconds=age_s)
    attrs = dict(extra or {})
    if rows is not ...:
        attrs["rates"] = rows
    return view(state if state is not None else t.isoformat(), attrs=attrs, changed=t, reported=t)


ABSENT = object()


def days(prev=None, cur=None, nxt=None, emap=None):
    """build() with the three day events (defaults: the 14th 600 s old, the 15th 300 s old, the 16th 120 s old); a part
    given as ABSENT has no state at all."""
    parts = {PREV: prev if prev is not None else ev(day_rows(14), 600), CUR: cur if cur is not None else ev(day_rows(15), 300),
             NEXT: nxt if nxt is not None else ev(day_rows(16), 120)}
    st = states_fresh(**{k: v for k, v in parts.items() if v is not ABSENT})
    for k, v in parts.items():
        if v is ABSENT:
            st.pop(k, None)
    return build(st, emap or DAYS_MAP)


def tbl(src):
    return rmap(src).get(IMP)


def tnotes(src):
    return [c for k, c in src.notes if k == IMP]


def starts(rows):
    return [sources.parse_time(r["start"]) for r in rows]


check("the rate key the merge compares is the engine's (intelligence.tariff.PRICE_KEY); only the rate tables take day "
      "events, 2 or 3 of them",
      sources.DAY_RATE_ROW_KEY == tf.PRICE_KEY and set(sources.DAY_TABLE_KEYS) == {"tariff.import_rates", "tariff.export_rates"}
      and all(ac.SITE_READING_KEYS[k] == "table" for k in sources.DAY_TABLE_KEYS)
      and (sources.DAY_PARTS_MIN, sources.DAY_PARTS_MAX) == (2, 3))
_parts = DAYS_MAP.readings[IMP].get("parts", ())
check("the three-event form parses: three {entity, attribute} parts in mapped order, every day event fetched",
      [p["entity"] for p in _parts] == [PREV, CUR, NEXT] and all(p["attribute"] == "rates" for p in _parts)
      and {PREV, CUR, NEXT} <= set(DAYS_MAP.entity_ids()), str(_parts))
check("two events (current, next) and the export table's list form parse too; the single form is unchanged",
      refused(with_readings(**{IMP: DAY_SPEC[1:]})) is None
      and refused(with_readings(**{"tariff.export_rates": [{"entity": "event.test_export_current_day_rates",
                                                            "attribute": "rates"},
                                                           {"entity": "event.test_export_next_day_rates",
                                                            "attribute": "rates"}]})) is None
      and dict(EMAP.readings[IMP]) == {"entity": "event.test_your_import_rates", "attribute": "rates"})
check("fresh_by may be named on a part", refused(with_readings(**{IMP: [DAY_SPEC[0], dict(DAY_SPEC[1], fresh_by="refreshed_at"),
                                                                     DAY_SPEC[2]]})) is None)
_ip = f"shadow_runtime.readings.{IMP}"
for label, spec, path in (
        ("a list for tariff.events (periods, not day rates)", None, "shadow_runtime.readings.tariff.events"),
        ("one part in a list", DAY_SPEC[:1], _ip),
        ("four parts", DAY_SPEC + [{"entity": "event.test_fourth_day_rates", "attribute": "rates"}], _ip),
        ("an empty list", [], _ip),
        ("a part without its attribute", [DAY_SPEC[0], {"entity": CUR}, DAY_SPEC[2]], f"{_ip}[2]"),
        ("a part with an unknown key", [DAY_SPEC[0], dict(DAY_SPEC[1], day="current"), DAY_SPEC[2]], f"{_ip}[2]"),
        ("a part that is not an object", [DAY_SPEC[0], CUR, DAY_SPEC[2]], f"{_ip}[2]"),
        ("a part with a placeholder entity", [DAY_SPEC[0], {"entity": "event.<slug>_current_day_rates",
                                                            "attribute": "rates"}, DAY_SPEC[2]], f"{_ip}[2]"),
        ("a part naming another fresh_by attribute", [DAY_SPEC[0], dict(DAY_SPEC[1], fresh_by="last_updated"),
                                                      DAY_SPEC[2]], f"{_ip}[2]"),
        ("the same entity listed twice", [DAY_SPEC[0], DAY_SPEC[1], dict(DAY_SPEC[0])], f"{_ip}[3]"),
        ("the same entity twice under different attributes", [DAY_SPEC[0], dict(DAY_SPEC[0], attribute="other_rates")],
         f"{_ip}[2]")):
    prof = (with_readings(**{"tariff.events": [{"entity": "event.test_a", "attribute": "events"},
                                               {"entity": "event.test_b", "attribute": "events"}]}) if spec is None
            else with_readings(**{IMP: spec}))
    exc = refused(prof)
    check(f"refused: {label}, by field path ({path})", exc is not None and exc.public.startswith(path),
          "accepted" if exc is None else exc.public)
exc = refused(with_readings(**{IMP: [DAY_SPEC[0], DAY_SPEC[1], dict(DAY_SPEC[0])]}))
check("... the duplicate is named by position against the first listing, never by its id (the id only in the debug detail)",
      exc is not None and exc.public.startswith(f"{_ip}[3]: the same entity as {_ip}[1]") and PREV not in exc.public
      and PREV in exc.detail, "accepted" if exc is None else exc.public)

s3 = days()
r3 = tbl(s3)
check("three days merge: one list of 144 rows in day order (the 14th 00:00 to the 17th 00:00), no note",
      r3 is not None and len(r3.value) == 144 and starts(r3.value) == sorted(starts(r3.value))
      and len(set(starts(r3.value))) == 144 and r3.value[0]["start"] == "2030-01-14T00:00:00+00:00"
      and r3.value[-1]["end"] == "2030-01-17T00:00:00+00:00" and not tnotes(s3) and not r3.problems(),
      "None" if r3 is None else f"{len(r3.value)} {tnotes(s3)}")
check("... observed at the OLDEST contributing part's own time (the previous day's, 600 s), so the merged age is the most "
      "conservative; the source names the parts that contributed",
      r3.observed_at == NOW - timedelta(seconds=600) and r3.source == f"ha:{PREV}+{CUR}+{NEXT}", f"{r3.observed_at} {r3.source}")
_slots, _bad = tf.parse_rates(r3.value)
check("... the engine's own parse takes the merged list unchanged (144 contiguous slots, no finding)",
      len(_slots) == 144 and not _bad, str(_bad[:1]))
for label, nxt in (("published as an empty list", ev([], 5000)), ("its attribute absent", ev(..., 5000)),
                   ("its attribute null", ev(None, 5000)),
                   ("its entity 'unavailable' (rows left in its attributes)", ev(day_rows(16), 5000, state="unavailable")),
                   ("its entity 'unknown'", ev(day_rows(16), 5000, state="unknown")), ("its entity absent", ABSENT)):
    s_ = days(nxt=nxt)
    r_ = tbl(s_)
    check(f"the next day not published ({label}): it contributes nothing; the other two merge (96 rows to the 16th 00:00), "
          "observed at the older of those two (its own 5000 s age does not count)",
          r_ is not None and len(r_.value) == 96 and r_.value[-1]["end"] == "2030-01-16T00:00:00+00:00"
          and r_.observed_at == NOW - timedelta(seconds=600) and r_.source == f"ha:{PREV}+{CUR}" and not tnotes(s_),
          "None" if r_ is None else f"{len(r_.value)} {r_.observed_at} {tnotes(s_)}")
s_ = days(prev=ev(day_rows(14), 600, state="unavailable"))
r_ = tbl(s_)
check("the previous day missing (unavailable): the current and next days merge (96 rows from the 15th 00:00), observed "
      "at the current day's 300 s",
      r_ is not None and len(r_.value) == 96 and r_.value[0]["start"] == "2030-01-15T00:00:00+00:00"
      and r_.observed_at == NOW - timedelta(seconds=300), "None" if r_ is None else str(len(r_.value)))
_z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")                                  # noqa: E731
for label, prev_rows in (("the same text", day_rows(15)), ("as UTC 'Z' texts", day_rows(15, fmt=_z)),
                         ("as aware datetimes (as Home Assistant holds them)", day_rows(15, fmt=lambda t: t)),
                         ("at a +01:00 offset", day_rows(15, fmt=lambda t: t.astimezone(timezone(timedelta(hours=1))).isoformat()))):
    s_ = days(prev=ev(prev_rows, 600))
    r_ = tbl(s_)
    check(f"duplicate rows collapsed: the previous-day event still holds the current day ({label}): each repeated row (same "
          "start, end as instants and rate) is dropped, 96 rows, every start once",
          r_ is not None and len(r_.value) == 96 and len(set(starts(r_.value))) == 96 and not tnotes(s_)
          and not tf.parse_rates(r_.value)[1], "None" if r_ is None else f"{len(r_.value)} {tnotes(s_)}")
_dup_in_part = day_rows(15)
_dup_in_part.insert(5, dict(_dup_in_part[4]))
r_ = tbl(days(cur=ev(_dup_in_part, 300)))
check("... a row repeated inside one event is collapsed too", r_ is not None and len(r_.value) == 144)
check("non-vacuity: without the collapse the engine refuses the same rows (TARIFF_OVERLAP)",
      [f.code for f in tf.parse_rates(day_rows(15) + day_rows(15) + day_rows(16))[1]] == ["TARIFF_OVERLAP"])


def refused_table(s_, code):
    return tbl(s_) is None and tnotes(s_) == [code]


_conf = day_rows(15)
_conf[20] = dict(_conf[20], value_inc_vat=0.31)
check("a conflicting overlap: the previous-day event holds the current day with one rate changed (same start and end, "
      "another rate) -> the whole table is refused (TABLE_ROWS_OVERLAP, no reading)",
      refused_table(days(prev=ev(_conf, 600)), "TABLE_ROWS_OVERLAP"), str(tnotes(days(prev=ev(_conf, 600)))))
for label, odd in (("a numeric text", "0.30"), ("a boolean", True)):
    _c2, _c3 = day_rows(15), day_rows(15)
    _c2[20] = dict(_c2[20], value_inc_vat=odd)
    _c3[20] = dict(_c3[20], value_inc_vat=odd)
    check(f"... a repeated row whose rate is {label} in both events (not a finite number: equality not confirmed) is "
          "refused the same way", refused_table(days(prev=ev(_c2, 600), cur=ev(_c3, 300)), "TABLE_ROWS_OVERLAP"))
# RT4B-1 (A42): 'the same rate' is exactly equal, with no tolerance
_near = day_rows(15)
_near[20] = dict(_near[20], value_inc_vat=0.3001)
check("RT4B-1: a repeated row whose rate is 0.0001 GBP/kWh away (the previous-day event's 0.3001 against the current "
      "day's 0.30) -> the whole table is refused (TABLE_ROWS_OVERLAP: only an exactly equal rate collapses)",
      refused_table(days(prev=ev(_near, 600)), "TABLE_ROWS_OVERLAP"), str(tnotes(days(prev=ev(_near, 600)))))
check("... and the other way round (0.30 kept first, 0.3001 repeated in the current-day event)",
      refused_table(days(prev=ev(day_rows(15), 600), cur=ev(_near, 300)), "TABLE_ROWS_OVERLAP"),
      str(tnotes(days(prev=ev(day_rows(15), 600), cur=ev(_near, 300)))))
for label, a_, b_ in (("0 (int) and 0.0 (float)", 0, 0.0), ("1 (int) and 1.0 (float)", 1, 1.0)):
    _ia, _fb = day_rows(15), day_rows(15)
    _ia[20] = dict(_ia[20], value_inc_vat=a_)
    _fb[20] = dict(_fb[20], value_inc_vat=b_)
    s_ = days(prev=ev(_ia, 600), cur=ev(_fb, 300))
    r_ = tbl(s_)
    check(f"... an int and a float of equal value ({label}) in a repeated row are the same rate: collapsed (96 rows, no "
          "note), the first event's row kept",
          r_ is not None and len(r_.value) == 96 and not tnotes(s_)
          and r_.value[20]["value_inc_vat"] == a_ and type(r_.value[20]["value_inc_vat"]) is type(a_),
          "None" if r_ is None else f"{len(r_.value)} {r_.value[20]}")
_part = day_rows(14) + [{"start": "2030-01-15T00:00:00+00:00", "end": "2030-01-15T00:15:00+00:00", "value_inc_vat": 0.30}]
check("a partial overlap (a row of the next event starts before the previous row ends) -> refused (TABLE_ROWS_OVERLAP)",
      refused_table(days(prev=ev(_part, 600)), "TABLE_ROWS_OVERLAP"))
_rev_map = sources.parse_entity_map(with_readings(**{IMP: DAY_SPEC[::-1]}))
check("the day events mapped in reverse order (next, current, previous) -> rows out of order, refused "
      "(TABLE_ROWS_OUT_OF_ORDER)", refused_table(days(emap=_rev_map), "TABLE_ROWS_OUT_OF_ORDER"),
      str(tnotes(days(emap=_rev_map))))
check("rows out of order inside one event -> refused (TABLE_ROWS_OUT_OF_ORDER; the runtime never sorts)",
      refused_table(days(cur=ev(day_rows(15)[::-1], 300)), "TABLE_ROWS_OUT_OF_ORDER"))
s_ = days(cur=ev(day_rows(15), 300, state="unavailable"))
r_ = tbl(s_)
check("a gap (the current-day event unavailable): the previous and next days merge with the gap kept (96 rows), and the "
      "engine's own rule refuses it (TARIFF_GAP)",
      r_ is not None and len(r_.value) == 96 and [f.code for f in tf.parse_rates(r_.value)[1]] == ["TARIFF_GAP"],
      "None" if r_ is None else str(tf.parse_rates(r_.value)[1][:1]))
for label, odd in (("a mapping", {"rates": day_rows(15)}), ("a text", "0.30"), ("a number", 0.3)):
    check(f"a contributing part whose attribute is {label} (not a list) -> the whole table is refused (TABLE_PART_NOT_LIST)",
          refused_table(days(cur=ev(odd, 300)), "TABLE_PART_NOT_LIST"), str(tnotes(days(cur=ev(odd, 300)))))
r_ = tbl(days(cur=ev({"rates": []}, 300, state="unavailable")))
check("... a non-list attribute on an unavailable entity contributes nothing (the entity is not usable)",
      r_ is not None and len(r_.value) == 96)
for label, row in (("a row with a naive start", {"start": "2030-01-16T00:00:00", "end": "2030-01-16T00:30:00+00:00"}),
                   ("a row with an unparseable end", {"start": "2030-01-16T00:00:00+00:00", "end": "midnight"}),
                   ("a row with no end", {"start": "2030-01-16T00:00:00+00:00"}),
                   ("a text in place of a row", "00:00-00:30")):
    bad_rows = [row] + day_rows(16)[1:]
    if isinstance(row, dict):
        row["value_inc_vat"] = 0.30
    check(f"{label} -> the whole table is refused (TABLE_ROW_TIME_UNUSABLE: its order cannot be checked)",
          refused_table(days(nxt=ev(bad_rows, 120)), "TABLE_ROW_TIME_UNUSABLE"), str(tnotes(days(nxt=ev(bad_rows, 120)))))
nothing = days(prev=ev([], 600), cur=ev(..., 300), nxt=ABSENT)
check("nothing contributes (an empty list, an absent attribute, an absent entity) -> TABLE_MISSING, no reading, as the "
      "single form", refused_table(nothing, "TABLE_MISSING"), str(tnotes(nothing)))
_big = [{"start": (NOW + timedelta(minutes=5 * i)).isoformat(), "end": (NOW + timedelta(minutes=5 * (i + 1))).isoformat(),
         "value_inc_vat": 0.30} for i in range(sources.MAX_TABLE_ROWS + 10)]
r_ = tbl(days(prev=ABSENT, cur=ABSENT, nxt=ev(_big, 120)))
check("a part's rows are copied as the single form copies them (at most MAX_TABLE_ROWS)",
      r_ is not None and len(r_.value) == sources.MAX_TABLE_ROWS)

# the age of the merged reading: the oldest contributing part, judged by the quality layer with the reading's I-D6 limit
old_prev = days(prev=ev(day_rows(14), 1200))
q_old, q_ok = ages_for(old_prev), ages_for(days())
check("age from the oldest part: the previous-day event 1200 s old (the others 300 s and 120 s) -> the merged reading is "
      "1200 s old and NOT fresh under its 900 s I-D6 limit; with every part inside the limit it is fresh",
      tbl(old_prev).observed_at == NOW - timedelta(seconds=1200) and not fresh(q_old, IMP) and fresh(q_ok, IMP)
      and q_old.ages[IMP].age_s == 1200.0, f"{q_old.ages.get(IMP)} {q_ok.ages.get(IMP)}")
_fb_map = sources.parse_entity_map(with_readings(**{IMP: [DAY_SPEC[0], dict(DAY_SPEC[1], fresh_by="refreshed_at"),
                                                          DAY_SPEC[2]]}))
_t250 = NOW - timedelta(seconds=250)
_cur_fb = view(_t250.isoformat(), attrs={"rates": day_rows(15), "refreshed_at": "junk"}, changed=_t250, reported=NOW)
s_ = days(cur=_cur_fb, emap=_fb_map)
check("a part whose fresh_by time is refused (an unparseable refreshed_at) -> no observation time for the whole: the "
      "reading is withheld with that part's FRESH_BY_ note",
      tbl(s_) is None and tnotes(s_) == ["FRESH_BY_UNPARSEABLE"], str(tnotes(s_)))
_cur_fb_ok = view(_t250.isoformat(), attrs={"rates": day_rows(15), "refreshed_at": (_t250 - timedelta(seconds=2)).isoformat()},
                  changed=_t250, reported=NOW, updated=_t250)
r_ = tbl(days(prev=ev(day_rows(14), 100), cur=_cur_fb_ok, emap=_fb_map))
check("... a usable fresh_by time counts as that part's own time (here the oldest: 252 s)",
      r_ is not None and r_.observed_at == _t250 - timedelta(seconds=2), "None" if r_ is None else str(r_.observed_at))
_fut = ev(day_rows(16), -60)
s_ = days(nxt=_fut)
q_fut = ages_for(s_)
check("a part dated 60 s in the future -> the merged reading is dated there (never hidden behind an older part's time): "
      "not fresh (READING_IN_FUTURE)",
      tbl(s_).observed_at == NOW + timedelta(seconds=60) and not fresh(q_fut, IMP)
      and any(f.code == "READING_IN_FUTURE" and f.subject == IMP for f in q_fut.findings), str(tbl(s_).observed_at))

print("== A42 (RT4-2): one rate event under two tariff tables is refused (entity and attribute, every list part)")
_tp = "shadow_runtime.readings."
_EXP, _EVT = "tariff.export_rates", "tariff.events"
check("the tariff tables compared are the import rates, the export rates and the events, in that code order: every "
      "table reading but the TOU slot table",
      sources.TARIFF_TABLE_KEYS == ("tariff.import_rates", "tariff.export_rates", "tariff.events")
      and set(sources.TARIFF_TABLE_KEYS)
      == {k for k, u in ac.SITE_READING_KEYS.items() if u == "table"} - {"tou.slot_table"})
_EXP_CUR = {"entity": "event.test_export_current_day_rates", "attribute": "rates"}
for label, changes, path in (
        ("the export rates (single form) on the import rates' current-day event",
         {IMP: DAY_SPEC, _EXP: dict(DAY_SPEC[1])}, f"{_tp}{_EXP}: the same entity and attribute as {_tp}{IMP}[2]"),
        ("an export day event (list form) equal to the import rates' next-day event",
         {IMP: DAY_SPEC, _EXP: [_EXP_CUR, dict(DAY_SPEC[2])]},
         f"{_tp}{_EXP}[2]: the same entity and attribute as {_tp}{IMP}[3]"),
        ("the export rates' first day event equal to the import rates' first (both two-event lists)",
         {IMP: DAY_SPEC[1:], _EXP: [dict(DAY_SPEC[1]), _EXP_CUR]},
         f"{_tp}{_EXP}[1]: the same entity and attribute as {_tp}{IMP}[1]"),
        ("the single forms of the import and export rates on one event",
         {IMP: {"entity": "event.test_rates", "attribute": "rates"},
          _EXP: {"entity": "event.test_rates", "attribute": "rates"}},
         f"{_tp}{_EXP}: the same entity and attribute as {_tp}{IMP}"),
        ("the events table on an import day event, under the same attribute",
         {IMP: DAY_SPEC, _EVT: dict(DAY_SPEC[0])}, f"{_tp}{_EVT}: the same entity and attribute as {_tp}{IMP}[1]"),
        ("the events table on the export rates' event, under the same attribute",
         {_EXP: {"entity": "event.test_export_rates", "attribute": "rates"},
          _EVT: {"entity": "event.test_export_rates", "attribute": "rates"}},
         f"{_tp}{_EVT}: the same entity and attribute as {_tp}{_EXP}")):
    exc = refused(with_readings(**changes))
    check(f"refused: {label} ({path}), by field path only (the id only in the debug detail)",
          exc is not None and exc.public.startswith(path) and "event.test" not in exc.public and "event.test" in exc.detail,
          "accepted" if exc is None else exc.public)
_rm = {_EXP: dict(DAY_SPEC[1]), **{k: v for k, v in H.READING_MAP.items() if k not in (IMP, _EXP)}, IMP: DAY_SPEC}
exc = refused(H.site_profile(readings=_rm))
check("... the site file's key order does not matter (the export rates listed first): the export rates are named against "
      "the import rates, in code order",
      exc is not None and exc.public.startswith(f"{_tp}{_EXP}: the same entity and attribute as {_tp}{IMP}[2]"),
      "accepted" if exc is None else exc.public)
for label, changes in (
        ("one entity holding the import and the export rates under separate attributes",
         {IMP: {"entity": "event.test_rates", "attribute": "import_rates"},
          _EXP: {"entity": "event.test_rates", "attribute": "export_rates"}}),
        ("the events table on an import day event's entity under its own attribute",
         {IMP: DAY_SPEC, _EVT: {"entity": CUR, "attribute": "events"}}),
        ("the import and export rates each as their own day events",
         {IMP: DAY_SPEC, _EXP: [_EXP_CUR, {"entity": "event.test_export_next_day_rates", "attribute": "rates"}]})):
    exc = refused(with_readings(**changes))
    check(f"accepted: {label} (the entity and attribute pair differs)", exc is None, "" if exc is None else exc.public)

print("== A42 (RT4-1 (b)): every source note is a contract key and a constant code; every code is produced")
_GCL = "sensor.test_max_grid_charge_power"
_GCL_FB = sources.parse_entity_map(with_readings(**{"limits.max_grid_charge_w": {"entity": _GCL,
                                                                                  "fresh_by": "refreshed_at"}}))


def _fb_view(refreshed, updated):
    return {"state": "5000", "attributes": {"unit_of_measurement": "W", "refreshed_at": refreshed},
            "last_changed": NOW - timedelta(hours=1), "last_updated": updated, "last_reported": NOW}


for over in ({H.eid("sensor", "battery_shutdown"): view("unavailable", "%")},          # MISSING_STATE
             {H.eid("sensor", "battery_shutdown"): view("abc", "%")},                  # NOT_NUMERIC
             {H.eid("sensor", "battery_shutdown"): view("12", "mA")},                  # UNIT_UNSUPPORTED
             {H.eid("sensor", "battery_soc"): view("150", "%")},                       # OUT_OF_RANGE (the raw SOC)
             {H.RESERVE_RAISE_HELPER: view("140", "%")},                               # OUT_OF_RANGE (the preference)
             {H.TOU_ENABLED: view("maybe")},                                           # NOT_BOOLEAN
             {H.slot_eid(3, "power"): view("unavailable", "W")},                       # SLOT_FIELD_UNKNOWN
             {H.OVERLAY_ENTITIES[0]: view("unknown")},                                 # OVERLAY_STATE_UNKNOWN
             {"event.test_your_import_rates": view("unavailable")},                    # TABLE_MISSING (single form)
             {H.CONFIG_ONLINE: view("off")}):                                          # CONFIGURATION_NOT_ONLINE
    build(states_fresh(**over))
build(live=None, cfg=None)                                                             # NO_CONFIRMED_POLL_CHANGE, NO_*
build(states_fresh(**{"sensor.test_canonical_battery_soc": view("0", "%")}),                # CANONICAL_ZERO_UNCONFIRMED
      sources.parse_entity_map(with_readings(**{"battery.soc_raw_pct": None})))
build({}, sources.EMPTY_MAP)                                                           # NOT_MAPPED
build(states_fresh(**{MODEL: view("ok", attrs={"model": 5})}), ATTR_MAP)              # ATTRIBUTE_MISSING
for refreshed, updated in (("junk", NOW), ((NOW + timedelta(seconds=60)).isoformat(), NOW),
                           ((NOW - timedelta(seconds=30)).isoformat(), None),
                           ((NOW - timedelta(seconds=100)).isoformat(), NOW)):
    build(states_fresh(**{_GCL: _fb_view(refreshed, updated)}), _GCL_FB)             # the four FRESH_BY_ refusals
_all_notes = [n for r_ in ALL_RESULTS for n in r_.notes]
_codes = {n[1] for n in _all_notes if isinstance(n, tuple) and len(n) == 2}
check(f"every note made in this suite ({len(_all_notes)} notes over {len(ALL_RESULTS)} builds) is a contract key (a signal "
      "or a site reading key) and a code of SOURCE_NOTE_CODES",
      bool(_all_notes) and all(isinstance(n, tuple) and len(n) == 2 and n[0] in sources.NOTE_KEYS
                               and n[1] in sources.SOURCE_NOTE_CODES for n in _all_notes),
      str([n for n in _all_notes if n[0] not in sources.NOTE_KEYS or n[1] not in sources.SOURCE_NOTE_CODES][:5]))
check("... and every code of SOURCE_NOTE_CODES is produced on its refusal path (the merge's TABLE_* codes, the FRESH_BY_ "
      "refusals, missing, non-numeric, an unsupported unit, out of range, not boolean, the false zero, an unknown slot "
      "field or overlay, no mapping, no poll change, the configuration offline, no observation time)",
      _codes == sources.SOURCE_NOTE_CODES, f"missing {sorted(sources.SOURCE_NOTE_CODES - _codes)}")
check("NOTE_KEYS is exactly the signal keys and the site reading keys (no site text)",
      sources.NOTE_KEYS == frozenset(sources.SIGNAL_KEYS) | frozenset(ac.SITE_READING_KEYS))
_pub_all = [sources.public_notes(r_.notes) for r_ in ALL_RESULTS]
check("public_notes keeps every note made here, in order, as [key, code], and withholds none",
      all(w == 0 and shown == [list(n) for n in r_.notes] for (shown, w), r_ in zip(_pub_all, ALL_RESULTS)))
_SITE_TEXT = ("test_", "event.", "sensor.", "binary_sensor.", "input_number.", "abc", "maybe", "junk", "mA", "150", "140",
              "5000", "rates", "refreshed_at", "model", "Grid", "None", "Normal")
_leaks = sorted({t for shown, _w in _pub_all for k, c in shown for t in _SITE_TEXT
                 if t in c or (k not in sources.NOTE_KEYS and t in k)})
check("no note shown carries an entity id, an attribute name, a state text, a unit or a number of the site",
      not _leaks, str(_leaks))
_forged = (("tariff.import_rates", "TABLE_ROWS_OVERLAP"), ("sensor.test_dongle_battery_soc", "MISSING_STATE"),
           ("tariff.import_rates", "event.test_current_day_rates"), ("tariff.import_rates", "TABLE_ROWS_OVERLAP", "x"),
           ["battery.soc", "NOT_NUMERIC"], ("battery.soc", 5))
check("public_notes withholds (counts) any other note: an entity id as the key or the code, a third element, a list or "
      "a non-text code",
      sources.public_notes(_forged) == ([["tariff.import_rates", "TABLE_ROWS_OVERLAP"]], 5)
      and sources.public_notes(None) == ([], 0), str(sources.public_notes(_forged)))
_tree = ast.parse(Path(sources.__file__).read_text(encoding="utf-8"))
_vocab = next(n for n in ast.walk(_tree) if isinstance(n, ast.Assign)
              and any(getattr(t, "id", None) == "SOURCE_NOTE_CODES" for t in n.targets))
_in_vocab = {id(n) for n in ast.walk(_vocab)}
_literals = {n.value for n in ast.walk(_tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and id(n) not in _in_vocab and re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+", n.value)}
_NON_NOTE = {"UNIT_ASSUMED_CANONICAL", "POLL_TEXT_CHANGED", "POLL_TEXT_CHANGE_TIME_UNUSABLE", "POLL_TEXT_FIRST_SIGHT",
             "POLL_TEXT_UNAVAILABLE", "POLL_TEXT_UNCHANGED"}
check("the vocabulary matches runtime/sources.py's code literals: every SOURCE_NOTE_CODES code is used in its code, and "
      "every other code literal is a declared non-note code (the liveness memory's notes, a value read in the canonical "
      "unit)", sources.SOURCE_NOTE_CODES <= _literals and _literals - sources.SOURCE_NOTE_CODES == _NON_NOTE,
      f"unused {sorted(sources.SOURCE_NOTE_CODES - _literals)} "
      f"undeclared {sorted(_literals - sources.SOURCE_NOTE_CODES - _NON_NOTE)}")

print("== A45 (RV9-3): the diagnostics list the signals by contract name, a PV forecast by its day and position only")
PV_LABELS = ("test_pv_label_qa", "test_pv_label_qz", "test_pv_label_qy")     # distinctive source names (site text)
PV_SECOND = "sensor.test_solar_forecast_tomorrow_second"
_pv_prof = H.site_profile()
_pv_prof["shadow_runtime"]["pv_forecast_sources"] = {
    "tomorrow": {PV_LABELS[1]: "sensor.test_solar_forecast_tomorrow", PV_LABELS[0]: PV_SECOND},
    "today": {PV_LABELS[2]: "sensor.test_solar_forecast_today"}}
EMAP_PV = sources.parse_entity_map(_pv_prof)
PV_STATES = states_fresh(**{PV_SECOND: view("4.0", "kWh", changed=NOW - timedelta(hours=1))})
PV_POSITIONS = ["pv.forecast.today.s000", "pv.forecast.tomorrow.s000", "pv.forecast.tomorrow.s001"]
_raw_sig = build(PV_STATES, EMAP_PV).snapshot.signals()
_shown_sig, _withheld_sig = sources.public_signals(_raw_sig)
check("the snapshot names each PV forecast observation with its source name (the site text the download must not show)",
      all(any(lab in n for n in _raw_sig) for lab in PV_LABELS), str([n for n in _raw_sig if n.startswith("pv.forecast.")]))
check("public_signals shows every contract signal by its name and each PV forecast observation as "
      "pv.forecast.<day>.s<position> (the sources in name order), in the snapshot's order, none withheld",
      _shown_sig == [n.split("_", 1)[0] if n.startswith("pv.forecast.") else n for n in _raw_sig]
      and [n for n in _shown_sig if n.startswith("pv.forecast.")] == PV_POSITIONS
      and {"battery.soc", "pv.power", "history.hourly"} <= set(_shown_sig) and _withheld_sig == 0, str(_shown_sig))
check("... and no source name in what it shows", not [lab for lab in PV_LABELS if lab in repr(_shown_sig)], str(_shown_sig))
_forged_sig = ("battery.soc", f"pv.forecast.tomorrow.s000_{PV_LABELS[0]}", "sensor.test_dongle_battery_soc",
               "pv.forecast.tomorrow.s000", f"pv.forecast.tomorrow.sx_{PV_LABELS[0]}",
               f"pv.forecast.remaining_today.s000_{PV_LABELS[0]}", f"pv.forecast.next_week.s000_{PV_LABELS[0]}",
               PV_LABELS[1], 5, None)
check("public_signals withholds (counts) any other name: an entity id, a forecast name without its source part or "
      "without a position, a day the runtime does not map, a source name alone, a name that is not text",
      sources.public_signals(_forged_sig) == (["battery.soc", "pv.forecast.tomorrow.s000"], 8)
      and sources.public_signals(None) == ([], 0), str(sources.public_signals(_forged_sig)))

print("== snapshot and readings")
src = build()
soc = src.snapshot.get("battery.soc")
check("raw SOC preferred (kind raw)", soc is not None and soc.value == 55.0 and soc.kind == "raw")
check("dongle signals are observed at the poll-text change time", all(
    src.snapshot.get(s).observed_at == LIVE for s in ("battery.soc", "battery.power", "grid.power", "house.power", "pv.power",
                                                      "inverter.healthy")))
rk = rmap(src)
check("dongle readings outside the configuration poll are observed at the poll-text change time",
      all(rk[k].observed_at == LIVE for k in ("battery.soc_raw_pct", "stop.dump_soc_pct", "inverter.clock_offset_s")))
check("configuration-poll readings are observed at the older poll time (here the configuration poll, 30 s ago)",
      all(rk[k].observed_at == CFG for k in ("tou.slot_table", "protection.shutdown_soc_pct", "capacity.reg204_ah",
                                             "tou.current_target_soc_pct", "tou.enabled", "tou.grid_charge_enabled")))
check("other readings carry their own report time", rk["limits.max_grid_charge_w"].observed_at == NOW)
check("the liveness reading carries the change time as its value", rk["liveness.dongle_poll_changed_at"].value == LIVE)
check("tariff tables are copied from the mapped attribute", isinstance(rk["tariff.import_rates"].value, list)
      and rk["tariff.import_rates"].value[0]["value_inc_vat"] == 0.075)
check("every reading uses the contract unit and passes SiteReading.problems()", all(not r.problems() for r in src.site_readings))

st = states_fresh(**{"sensor.test_canonical_battery_soc": view("0", "%")})
src0 = build(st)
check("a canonical false zero with a valid raw SOC -> raw used", src0.snapshot.get("battery.soc").value == 55.0)
emap_noraw = sources.parse_entity_map(with_readings(**{"battery.soc_raw_pct": None}))
src1 = build(st, emap_noraw)
check("a canonical zero with no raw reading -> missing (never 0)", src1.snapshot.get("battery.soc").value is None)
src2 = build(states_fresh(), emap_noraw)
check("a non-zero canonical SOC is used when no raw reading is mapped",
      src2.snapshot.get("battery.soc").value == 55.0 and src2.snapshot.get("battery.soc").kind == "normalized")
st3 = states_fresh(**{H.eid("sensor", "battery_soc"): view("unavailable", "%")})
src3 = build(st3)
check("raw unavailable -> the canonical value (non-zero) is used",
      src3.snapshot.get("battery.soc").value == 55.0 and "battery.soc_raw_pct" not in {r.key for r in src3.site_readings})
st4 = states_fresh(**{H.eid("sensor", "battery_soc"): view("unavailable", "%"),
                      "sensor.test_canonical_battery_soc": view("unknown", "%")})
src4 = build(st4)
check("both SOC entities unusable -> battery.soc missing", src4.snapshot.get("battery.soc").value is None)
st5 = states_fresh(**{H.eid("sensor", "grid_power_ct_clamp"): view("unavailable", "W")})
check("an unavailable power -> missing", build(st5).snapshot.get("grid.power").value is None)
st7 = states_fresh(**{H.eid("sensor", "battery_soc"): view("140", "%")})
check("a raw SOC outside 0..100 is refused", build(st7).snapshot.get("battery.soc").value == 55.0)

print("== freshness, judged by the quality layer from these times")
q = ages_for(build())
check("unchanged values with moving poll texts -> fresh", q.ages["battery.soc"].fresh and q.ages["grid.power"].fresh
      and q.ages["tou.slot_table"].fresh, str({k: q.ages[k].fresh for k in ("battery.soc", "grid.power", "tou.slot_table")}))
check("... although the values themselves last changed 3 h ago", all(
    states_fresh()[e]["last_changed"] <= NOW - timedelta(hours=3) for e in (H.eid("sensor", "battery_soc"),)))
check("non-vacuity: on these fresh inputs the quality layer has a charge window (no CHARGE_WINDOW_UNKNOWN) and finds "
      "the TOU table and the grid-charge limit fresh",
      not any(blocks(q, "CHARGE_WINDOW_UNKNOWN", i) for i in ("charge_target", "predicted_morning_soc"))
      and not blocks(q, "INPUT_NOT_FRESH", "charge_target", "limits.max_grid_charge_w"),
      str(sorted({(f.code, f.subject) for f in q.findings if f.severity == "BLOCK"})[:6]))
q2 = ages_for(build(live=NOW - timedelta(hours=2)))
check("a frozen poll text (last change 2 h ago) -> dongle inputs stale",
      not q2.ages["battery.soc"].fresh and not q2.ages["grid.power"].fresh and not fresh(q2, "tou.slot_table"))
check("... and every item that needs them is blocked", {"charge_target", "export_event", "dump_to_grid"} <= q2.blocked_items)
emap_nolive = sources.parse_entity_map(with_readings(**{"liveness.dongle_poll_changed_at": None}))
src_nl = build(emap=emap_nolive)
q3 = ages_for(src_nl)
check("a missing poll-text mapping -> no liveness reading", "liveness.dongle_poll_changed_at" not in {r.key for r in src_nl.site_readings}
      and ("liveness.dongle_poll_changed_at", "NOT_MAPPED") in src_nl.notes)
check("... -> the quality layer BLOCKs (LIVENESS_MISSING)", any(f.code == "LIVENESS_MISSING" and f.severity == "BLOCK"
                                                               for f in q3.findings))
check("... and no dongle input is fresh", not q3.ages["battery.soc"].fresh)
q4 = ages_for(build(live=None))
check("no confirmed poll change yet -> BLOCK as well", any(f.code == "LIVENESS_MISSING" for f in q4.findings))

print("== the build_sources signature (WP-0 fixed it; the configuration-poll time is keyword only)")
_bs = inspect.signature(sources.build_sources).parameters
check("build_sources takes config_liveness_at, keyword only, default None (after the unchanged positional parameters)",
      list(_bs) == ["now", "states", "emap", "liveness_at", "history_end", "config_liveness_at"]
      and _bs["config_liveness_at"].kind == inspect.Parameter.KEYWORD_ONLY and _bs["config_liveness_at"].default is None
      and _bs["history_end"].default is None, str(list(_bs)))
try:
    sources.build_sources(NOW, states_fresh(), EMAP, LIVE, NOW - timedelta(minutes=50), CFG)
    check("... it can never be passed by position", False, "accepted positionally")
except TypeError:
    check("... it can never be passed by position", True)
check("... and a caller that passes none (the default) gets no configuration-poll reading at all (fail closed)",
      not (set(sd.CONFIG_POLL_READINGS) | {sd.CONFIG_LIVENESS_KEY}) & set(rmap(sources.build_sources(
          NOW, states_fresh(), EMAP, LIVE, NOW - timedelta(minutes=50)))))

print("== the harness's owner decisions and the engine's I-D6 keys")
_ds = sd.DecisionSet.from_mapping(H.owner_decisions(), source="site_local")
_lim = H.owner_decisions()["I-D6"]["value"]["limits_s"]
check("the harness's decisions are valid under the loaded engine (I-D6 satisfied, never INVALID)",
      _ds.satisfied("D6") and not any(f.severity == "BLOCK" for f in sd.freshness_limits(_ds)[1]),
      str(sd.freshness_limits(_ds)[1][:2]))
check("the TOU classification inputs get an I-D6 limit exactly when the engine accepts them as I-D6 keys",
      all((k in _lim) == (k in sd.FRESHNESS_OVERRIDE_KEYS) for k in H.TOU_I_D6_KEYS)
      and H.engine_override_keys() == frozenset(sd.FRESHNESS_OVERRIDE_KEYS))
check("the configuration-poll liveness and the raise preference are never I-D6 keys in the harness",
      sd.CONFIG_LIVENESS_KEY not in _lim and "pref.advisory_reserve_raise_pct" not in _lim)
_real_sd = sys.modules["intelligence.site_decisions"]
try:                                                  # an engine whose freshness rules know the TOU keys (WP-1 on)
    sys.modules["intelligence.site_decisions"] = type(sys)("stub_site_decisions")
    sys.modules["intelligence.site_decisions"].FRESHNESS_OVERRIDE_KEYS = tuple(sd.FRESHNESS_OVERRIDE_KEYS) + H.TOU_I_D6_KEYS
    _lim_on = H.owner_decisions()["I-D6"]["value"]["limits_s"]
    sys.modules["intelligence.site_decisions"].FRESHNESS_OVERRIDE_KEYS = tuple(
        k for k in sd.FRESHNESS_OVERRIDE_KEYS if k not in H.TOU_I_D6_KEYS)
    _lim_off = H.owner_decisions()["I-D6"]["value"]["limits_s"]
finally:
    sys.modules["intelligence.site_decisions"] = _real_sd
check("... an engine that accepts them gets a 300 s limit for each; one that does not gets none",
      all(_lim_on.get(k) == 300.0 for k in H.TOU_I_D6_KEYS) and not any(k in _lim_off for k in H.TOU_I_D6_KEYS),
      f"{sorted(k for k in _lim_on if k.startswith('tou.'))} {sorted(k for k in _lim_off if k.startswith('tou.'))}")

print("== engine_link: the caller's assessments come from the bridge and agree with quality")
job = engine_link.EngineJob(now=NOW, states=states_fresh(), entity_map=EMAP, liveness_at=NOW - timedelta(seconds=20),
                            plan=history_source.plan_history(H.site_profile()), statistics=None,
                            base_cfg=SiteConfig(pv_array_kwp=6.0), site_facts=SiteFacts(6.0, 51.5, -0.1),
                            decisions=sd.DecisionSet.from_mapping(H.owner_decisions(), source="site_local"),
                            outcome_metrics=None, paused=False, previous=None, versions=Versions())
seen = {}


def spy(inputs):
    seen["inputs"] = inputs
    from intelligence.shadow_cycle import run_cycle
    return run_cycle(inputs)


env, diag, hist = engine_link.compute(job, spy)
ci = seen["inputs"]
check("caller assessments are passed (one per bridge signal)", {a[0] for a in ci.caller_assessments} ==
      {"battery.soc", "inverter.healthy", "house.power", "pv.power", "reserve.ha_minimum_soc"})
check("the LiveInputs come from the same snapshot", ci.live is not None and ci.live.soc_pct == 55.0)
check("the default acceptance applies (OWNER_RECORD only)", ci.accept_provenance == sd.DEFAULT_ACCEPT_PROVENANCE)
check("no CALLER_FRESHNESS_DISAGREES on consistent inputs", "CALLER_FRESHNESS_DISAGREES" not in env.reason_codes,
      str(env.reason_codes))
check("I-D6 overrides reach the FreshnessPolicy only for ecco_core signals",
      set(engine_link.advisory_overrides(job.decisions)) <= {"battery.soc", "history.hourly", "inverter.healthy", "house.power",
                                                              "pv.power", "battery.power", "grid.power", "reserve.ha_minimum_soc"})
check("all-OPEN decisions give no unresolved override", set(engine_link.advisory_overrides(sd.DecisionSet())) ==
      {"battery.soc", "history.hourly"})
_env_pv, diag_pv, _hist_pv = engine_link.compute(dataclasses.replace(job, states=PV_STATES, entity_map=EMAP_PV), spy)
_engine_sig = seen["inputs"].snapshot.signals()
check("A45 (RV9-3): engine_link.compute gives the diagnostics the signal names public_signals shows (the engine itself "
      "still sees each source name), so no PV forecast source name reaches the diagnostics; none withheld",
      all(any(lab in n for n in _engine_sig) for lab in PV_LABELS)
      and diag_pv.get("signals") == sources.public_signals(_engine_sig)[0]
      and [n for n in diag_pv["signals"] if n.startswith("pv.forecast.")] == PV_POSITIONS
      and diag_pv.get("signals_withheld") == 0
      and not [lab for lab in PV_LABELS if lab in json.dumps(diag_pv, default=str)], str(diag_pv.get("signals")))
# RV8-4: build_sources makes only public notes, so the link from compute to public_notes is pinned with forged ones
_FORGED_NOTES = (("sensor.test_forged_note_entity", "MISSING_STATE"), ("tariff.import_rates", "test_forged_attribute"),
                 ("battery.soc", "NOT_NUMERIC", "test_forged_third"))
_real_build = sources.build_sources
_built: list = []


def _forging_build(*a, **kw):
    r_ = _real_build(*a, **kw)
    _built.append(r_)
    return dataclasses.replace(r_, notes=tuple(r_.notes) + _FORGED_NOTES)


sources.build_sources = _forging_build
try:
    _env_fg, diag_fg, _hist_fg = engine_link.compute(job, spy)
finally:
    sources.build_sources = _real_build
_real_notes = _built[0].notes if _built else ()
_dump_fg = json.dumps(diag_fg, default=str)
check("RV8-4: engine_link.compute puts only public_notes' notes in the diagnostics: forged notes (an entity id as the "
      "key, an attribute name as the code, a third element) are withheld and counted, the real ones are kept in order, "
      "and no forged text appears anywhere in the diagnostics",
      len(_built) == 1 and len(_real_notes) >= 1 and diag_fg.get("source_notes") == [list(n) for n in _real_notes]
      and diag_fg.get("source_notes_withheld") == len(_FORGED_NOTES)
      and not [t for t in ("test_forged_note_entity", "test_forged_attribute", "test_forged_third") if t in _dump_fg],
      f"{diag_fg.get('source_notes')} withheld {diag_fg.get('source_notes_withheld')} built {len(_built)}")

print("== history_source")
plan = history_source.plan_history(H.site_profile())
check("the plan queries only valid ids", len(plan.statistic_ids) == len(set(H.SOURCE_ENTITIES.values()) | {"sensor.test_solar_forecast_today"}))
ex = __import__("json").loads((H.REPO / "intelligence" / "profiles" / "site_profile.example.json").read_text(encoding="utf-8"))
plan_ex = history_source.plan_history(ex)
check("the example profile's <placeholder> ids are never queried", not any("<" in s for s in plan_ex.statistic_ids)
      and len(plan_ex.skipped) > 0, f"{plan_ex.statistic_ids[:3]} {len(plan_ex.skipped)}")
stats = H.synthetic_statistics(NOW, days=10)
rows, trunc = history_source.rows_from_statistics(stats)
check("rows are converted (start_ts int, all stat keys)", rows and set(rows[0]) == {"statistic_id", "start_ts", "mean", "min", "max",
                                                                                    "state", "sum"} and not trunc)
rows_c, trunc_c = history_source.rows_from_statistics(stats, cap=100)
check("the row cap keeps the newest rows and says so", len(rows_c) == 100 and trunc_c
      and rows_c[-1]["start_ts"] == max(r["start_ts"] for r in rows))
bad = {"sensor.test_x": [{"start": float("nan"), "mean": 1.0}, {"start": NOW.timestamp(), "mean": float("inf")}, "junk"]}
rows_b, _ = history_source.rows_from_statistics(bad)
check("non-finite starts are dropped and non-finite values become None", len(rows_b) == 1 and rows_b[0]["mean"] is None)
hist, newest = history_source.build(plan, rows, SiteConfig(pv_array_kwp=6.0), NOW)
check("a History is built, newest hour ending before now", hist is not None and newest is not None and newest <= NOW)
gap = H.synthetic_statistics(NOW, days=10, gap=(60, 30), drop_newest_hours=8)
hg, ng = history_source.build(plan, history_source.rows_from_statistics(gap)[0], SiteConfig(pv_array_kwp=6.0), NOW)
check("recorder gaps stay gaps (fewer hours) and the newest hour is older", hg is not None and len(hg) < len(hist)
      and ng <= NOW - timedelta(hours=8))
check("no rows -> no history", history_source.build(plan, [], SiteConfig(), NOW) == (None, None))
check("the window ends at the start of the current hour",
      history_source.window(NOW + timedelta(minutes=17))[1] == NOW)

_late = [n for r_ in ALL_RESULTS for n in r_.notes]
check(f"A42: every note of every build in this suite ({len(ALL_RESULTS)} builds, the later sections included) is a contract "
      "key and a SOURCE_NOTE_CODES code, and public_notes withholds none",
      all(isinstance(n, tuple) and len(n) == 2 and n[0] in sources.NOTE_KEYS and n[1] in sources.SOURCE_NOTE_CODES
          for n in _late) and all(sources.public_notes(r_.notes)[1] == 0 for r_ in ALL_RESULTS),
      str([n for n in _late if n[0] not in sources.NOTE_KEYS or n[1] not in sources.SOURCE_NOTE_CODES][:5]))


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime sources:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime sources checks passed")
