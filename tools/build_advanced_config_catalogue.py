#!/usr/bin/env python3
"""Generate the catalogue of the ECCO Advanced / Experimental Configuration card (read-only).

    python tools/build_advanced_config_catalogue.py            # (re)write the generated catalogue module
    python tools/build_advanced_config_catalogue.py --check    # exit 1 if the committed module is stale; writes nothing
    python tools/build_advanced_config_catalogue.py --report   # print the entity-link report; writes nothing

INPUTS (all READ-ONLY; this tool never writes to any of them):
  registry/inverter_capabilities.yaml     the capability registry: every record, its evidence and its write policy
  registry/advanced_config_overlay.yaml   presentation overlay: sections, danger classes, lock reasons, explanations, the
                                          Global Power panel. It can only RESTRICT a record's status, never promote it.
  firmware/<main firmware YAML>           entity names, and how the six steady poll windows decode each register into an
                                          entity (used to link records to Home Assistant entities and to derive raw values)

OUTPUT: frontend/ecco-advanced-config-card/src/catalogue.generated.ts - a deterministic TypeScript module (sorted keys,
LF line endings, no timestamps, no input hashes) that the card bundles.

The generator fails closed: a malformed input, an overlay that tries to promote a status, a record id the registry does not
have, an entity link that contradicts the firmware decode, a reserved token or an output the site renderer would refuse all
raise GeneratorError and nothing is written.

Standard library + PyYAML. No network. No Home Assistant or inverter access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_REL = "registry/inverter_capabilities.yaml"
OVERLAY_REL = "registry/advanced_config_overlay.yaml"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
OUTPUT_REL = "frontend/ecco-advanced-config-card/src/catalogue.generated.ts"

CATALOGUE_SCHEMA = "ecco-advanced-config-catalogue/1"
OVERLAY_SCHEMA = "ecco-advanced-config-overlay/1"
DEFAULT_SLUG = "ecco_clock_dongle"

# Status ladder: an overlay may move a record DOWN this list (more restrictive), never up.
STATUS_ORDER = ("PROVEN", "EXPERIMENTAL", "READ_ONLY", "LOCKED", "UNSUPPORTED")
STATUS_RANK = {s: i for i, s in enumerate(STATUS_ORDER)}

# Registry live_proof_status -> mapping-evidence code (see the card README).
EVIDENCE_BY_PROOF = {
    "live_proven_write": "M3",
    "live_proven_read": "M2",
    "documented_not_live_proven": "M1",
    "repository_inferred_read_only": "M0",
    "inferred_do_not_write": "M0",
    "unknown": "MX",
}
DANGER_CODES = ("D0", "D1", "D2", "D3", "D4")
SECTION_COUNT = 9

# ESPHome platform -> Home Assistant domain (a text_sensor is a `sensor` in Home Assistant).
HA_DOMAIN = {"sensor": "sensor", "text_sensor": "sensor", "binary_sensor": "binary_sensor", "number": "number",
             "select": "select", "switch": "switch", "button": "button"}

# The six steady read windows (owner script/button, start register, count). The firmware must still contain exactly these.
STEADY_WINDOWS = (
    ("read_inverter_clock", 22, 3, "rtc"),
    ("poll_inverter_telemetry", 59, 58, "telemetry"),
    ("poll_inverter_telemetry", 150, 47, "telemetry"),
    ("poll_inverter_configuration_dispatch", 200, 41, "configuration"),
    ("poll_inverter_configuration_dispatch", 241, 53, "configuration"),
    ("poll_inverter_configuration_dispatch", 330, 1, "configuration"),
)

# Tokens no file under frontend/ may carry (the repo's fallback / shadow scans). Assembled so this file never trips them.
RESERVED_TOKENS = ("ecco_" + "fallback", "FALLBACK" + "_PROFILE", "FAILBACK" + "_STATE", "ecco_" + "failback",
                   "failback" + "_shadow", "ecco_" + "shadow_", "Shadow" + " Recovery", "fbc" + "_raw_")
# Words that must never describe a control this card could operate.
WRITE_VOCABULARY = ("callService", "callWS", "sendMessage", "perform_action", "XMLHttpRequest", "WebSocket")

OVERLAY_TOP_KEYS = {"schema", "notes", "controller_note", "sections", "category_sections", "section_rules",
                    "category_danger", "records", "entity_links", "global_power"}
OVERLAY_RECORD_KEYS = {"section", "danger", "restrict", "lock_reason", "explanation", "interactions", "options_note"}
GLOBAL_POWER_KEYS = {"record", "register", "title", "owner_confirmation", "hardware_maximum_w", "hardware_maximum_evidence",
                     "hardware_maximum_note", "regulatory_allowance_w", "regulatory_note", "write_status", "write_blockers",
                     "limitations", "future_controls"}
FUTURE_CONTROL_KEYS = ("unlock", "staged_value", "permitted_range", "apply", "verification", "previous_value", "history")


class GeneratorError(Exception):
    """An input is malformed or a rule would be broken. Nothing has been written."""


# ---------------------------------------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------------------------------------
def _firmware_loader():
    base = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

    class FirmwareLoader(base):  # type: ignore[misc, valid-type]
        """SafeLoader that keeps ESPHome's custom tags (!lambda, !secret, ...) as plain values."""

    def _tagged(loader, _suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_mapping(node, deep=True)

    FirmwareLoader.add_multi_constructor("!", _tagged)
    return FirmwareLoader


def read_text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError as ex:
        raise GeneratorError(f"cannot read {rel}: {ex}") from None


def load_registry(text: str) -> list[dict]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as ex:
        raise GeneratorError(f"{REGISTRY_REL}: not valid YAML ({ex})") from None
    if not isinstance(data, dict) or data.get("schema_version") != 2 or not isinstance(data.get("capabilities"), list):
        raise GeneratorError(f"{REGISTRY_REL}: expected schema_version 2 with a capabilities list")
    seen = set()
    for i, rec in enumerate(data["capabilities"]):
        if not isinstance(rec, dict):
            raise GeneratorError(f"{REGISTRY_REL}: capability #{i} is not a mapping")
        for key in ("id", "name", "category", "current_access", "write_policy", "live_proof_status"):
            if not isinstance(rec.get(key), str) or not rec[key]:
                raise GeneratorError(f"{REGISTRY_REL}: capability #{i} has no {key}")
        if rec["id"] in seen:
            raise GeneratorError(f"{REGISTRY_REL}: duplicate capability id {rec['id']!r}")
        seen.add(rec["id"])
        if rec["live_proof_status"] not in EVIDENCE_BY_PROOF:
            raise GeneratorError(f"{REGISTRY_REL}: {rec['id']}: unknown live_proof_status {rec['live_proof_status']!r}")
        if rec["current_access"] not in ("read_only", "read_write", "write_only"):
            raise GeneratorError(f"{REGISTRY_REL}: {rec['id']}: unknown current_access {rec['current_access']!r}")
        if rec["write_policy"] not in ("R0", "W1", "W2", "W3", "WX"):
            raise GeneratorError(f"{REGISTRY_REL}: {rec['id']}: unknown write_policy {rec['write_policy']!r}")
    return data["capabilities"]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise GeneratorError(f"{OVERLAY_REL}: {msg}")


def load_overlay(text: str, registry_ids: set[str]) -> dict:
    try:
        ov = yaml.safe_load(text)
    except yaml.YAMLError as ex:
        raise GeneratorError(f"{OVERLAY_REL}: not valid YAML ({ex})") from None
    _require(isinstance(ov, dict), "the top level must be a mapping")
    unknown = set(ov) - OVERLAY_TOP_KEYS
    _require(not unknown, f"unknown top-level key(s) {sorted(unknown)}")
    _require(ov.get("schema") == OVERLAY_SCHEMA, f"schema must be {OVERLAY_SCHEMA!r}")
    sections = ov.get("sections")
    _require(isinstance(sections, list) and len(sections) == SECTION_COUNT, f"sections must list exactly {SECTION_COUNT} sections")
    ids = []
    for s in sections:
        _require(isinstance(s, dict) and set(s) == {"id", "title", "summary"}
                 and all(isinstance(s[k], str) and s[k] for k in s), f"bad section entry {s!r}")
        ids.append(s["id"])
    _require(len(set(ids)) == len(ids), "duplicate section id")
    section_ids = set(ids)
    cat = ov.get("category_sections")
    _require(isinstance(cat, dict) and all(isinstance(k, str) and v in section_ids for k, v in cat.items()),
             "category_sections must map registry categories to section ids")
    rules = ov.get("section_rules") or []
    _require(isinstance(rules, list), "section_rules must be a list")
    for r in rules:
        _require(isinstance(r, dict) and set(r) == {"id_pattern", "section"} and r["section"] in section_ids,
                 f"bad section rule {r!r}")
        try:
            re.compile(r["id_pattern"])
        except re.error as ex:
            raise GeneratorError(f"{OVERLAY_REL}: section rule pattern {r['id_pattern']!r}: {ex}") from None
    danger = ov.get("category_danger")
    _require(isinstance(danger, dict) and all(v in DANGER_CODES for v in danger.values()),
             "category_danger must map registry categories to D0-D4")
    recs = ov.get("records") or {}
    _require(isinstance(recs, dict), "records must be a mapping")
    for rid, spec in recs.items():
        _require(rid in registry_ids, f"records: {rid!r} is not a registry record")
        _require(isinstance(spec, dict), f"records: {rid}: must be a mapping")
        bad = set(spec) - OVERLAY_RECORD_KEYS
        _require(not bad, f"records: {rid}: unknown key(s) {sorted(bad)}")
        if "section" in spec:
            _require(spec["section"] in section_ids, f"records: {rid}: unknown section {spec['section']!r}")
        if "danger" in spec:
            _require(spec["danger"] in DANGER_CODES, f"records: {rid}: danger must be D0-D4")
        if "restrict" in spec:
            _require(spec["restrict"] in STATUS_RANK, f"records: {rid}: restrict must be one of {list(STATUS_ORDER)}")
            _require(isinstance(spec.get("lock_reason"), str) and spec["lock_reason"].strip(),
                     f"records: {rid}: a restriction needs a lock_reason")
        for k in ("lock_reason", "explanation", "options_note"):
            if k in spec:
                _require(isinstance(spec[k], str) and spec[k].strip(), f"records: {rid}: {k} must be non-empty text")
        if "interactions" in spec:
            _require(isinstance(spec["interactions"], list) and all(isinstance(x, str) and x for x in spec["interactions"]),
                     f"records: {rid}: interactions must be a list of text")
    links = ov.get("entity_links") or {}
    _require(isinstance(links, dict), "entity_links must be a mapping")
    for rid, fid in links.items():
        _require(rid in registry_ids, f"entity_links: {rid!r} is not a registry record")
        _require(isinstance(fid, str) and re.fullmatch(r"[a-z][a-z0-9_]*", fid or ""), f"entity_links: {rid}: bad firmware id")
    gp = ov.get("global_power")
    _require(isinstance(gp, dict), "global_power must be a mapping")
    bad = set(gp) - GLOBAL_POWER_KEYS
    _require(not bad, f"global_power: unknown key(s) {sorted(bad)}")
    missing = {"record", "register", "title", "owner_confirmation", "write_status", "write_blockers", "limitations",
               "future_controls"} - set(gp)
    _require(not missing, f"global_power: missing key(s) {sorted(missing)}")
    _require(gp["record"] in registry_ids, "global_power.record is not a registry record")
    _require(isinstance(gp["register"], int) and not isinstance(gp["register"], bool), "global_power.register must be an integer")
    hw = gp.get("hardware_maximum_w")
    _require(hw is None or (isinstance(hw, int) and not isinstance(hw, bool) and hw > 0),
             "global_power.hardware_maximum_w must be null or a positive integer")
    if hw is not None:
        _require(isinstance(gp.get("hardware_maximum_evidence"), str) and gp["hardware_maximum_evidence"].strip(),
                 "global_power.hardware_maximum_w needs hardware_maximum_evidence (a maximum is never assumed)")
    reg_allow = gp.get("regulatory_allowance_w")
    _require(reg_allow is None or (isinstance(reg_allow, int) and not isinstance(reg_allow, bool) and reg_allow >= 0),
             "global_power.regulatory_allowance_w must be null or a non-negative integer")
    _require(gp["write_status"] in ("not_implemented", "disabled"), "global_power.write_status must be not_implemented or disabled")
    oc = gp["owner_confirmation"]
    _require(isinstance(oc, dict) and set(oc) == {"date", "statement"} and all(isinstance(v, str) and v for v in oc.values()),
             "global_power.owner_confirmation needs a date and a statement")
    _require(isinstance(gp["write_blockers"], list) and gp["write_blockers"] and all(isinstance(x, str) and x for x in gp["write_blockers"]),
             "global_power.write_blockers must be a non-empty list of text")
    _require(isinstance(gp["limitations"], list) and all(isinstance(x, str) and x for x in gp["limitations"]),
             "global_power.limitations must be a list of text")
    fc = gp["future_controls"]
    _require(isinstance(fc, dict) and set(fc) == set(FUTURE_CONTROL_KEYS)
             and all(isinstance(v, str) and v for v in fc.values()), f"global_power.future_controls needs exactly {list(FUTURE_CONTROL_KEYS)}")
    for k in ("notes", "controller_note"):
        if k in ov:
            _require(isinstance(ov[k], str) and ov[k].strip(), f"{k} must be non-empty text")
    return ov


# ---------------------------------------------------------------------------------------------------------------------------
# Firmware: entities and steady-poll decode
# ---------------------------------------------------------------------------------------------------------------------------
def slugify(name: str) -> str:
    """Home Assistant's object-id slug of an entity name (lower case, runs of other characters -> one underscore)."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def firmware_entities(fw: dict) -> dict[str, dict]:
    """{firmware id: {platform, domain, name, object}} for every named entity of a Home Assistant-facing platform."""
    out: dict[str, dict] = {}
    for platform, domain in HA_DOMAIN.items():
        for e in fw.get(platform) or []:
            if isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("id"), str):
                if e["id"] in out:
                    raise GeneratorError(f"{FIRMWARE_REL}: duplicate entity id {e['id']!r}")
                out[e["id"]] = {"platform": platform, "domain": domain, "name": e["name"], "object": slugify(e["name"])}
    if not out:
        raise GeneratorError(f"{FIRMWARE_REL}: no named entities found")
    return out


def _walk_reads(node, owner, found):
    """Collect (owner id, start, count, [lambda text]) for every read_holding_registers action under node."""
    if isinstance(node, dict):
        if isinstance(node.get("id"), str) and ("then" in node or "on_press" in node):
            owner = node["id"]
        for k, v in node.items():
            if k == "modbus_client.read_holding_registers" and isinstance(v, dict):
                lambdas = []
                resp = v.get("on_response")
                steps = resp.get("then") if isinstance(resp, dict) else resp
                for step in steps or []:
                    if isinstance(step, dict) and isinstance(step.get("lambda"), str):
                        lambdas.append(step["lambda"])
                found.append((owner, v.get("start_address"), v.get("count"), lambdas))
            _walk_reads(v, owner, found)
    elif isinstance(node, list):
        for v in node:
            _walk_reads(v, owner, found)


def steady_windows(fw: dict) -> list[dict]:
    found: list = []
    _walk_reads(fw, None, found)
    windows = []
    for owner, start, count, poll_class in STEADY_WINDOWS:
        hits = [f for f in found if f[0] == owner and f[1] == start and f[2] == count]
        if len(hits) != 1 or not hits[0][3]:
            raise GeneratorError(f"{FIRMWARE_REL}: expected exactly one steady read {start}/{count} in {owner} with a decode "
                                 f"lambda, found {len(hits)} (the firmware changed: review the generator)")
        windows.append({"owner": owner, "start": start, "count": count, "poll_class": poll_class, "lambda": "\n".join(hits[0][3])})
    return windows


_VALUES = re.compile(r"values\[(\d+)\]")
_IDENT = re.compile(r"\b[A-Za-z_]\w*\b")
_PUBLISH = re.compile(r"id\((\w+)\)\.publish_state\((.*)\)\s*$", re.S)
_DECL = re.compile(r"^(?:(?:const\s+)?(?:u?int(?:8|16|32|64)_t|int|unsigned|float|double|auto|bool)\s+)?([A-Za-z_]\w*)\s*=(?!=)\s*(.+)$", re.S)
_SNPRINTF = re.compile(r"snprintf\(\s*([A-Za-z_]\w*)\s*,(.*)\)\s*$", re.S)
_ASSIGN_TARGET = re.compile(r"\b([A-Za-z_]\w*)\s*(?:[+\-*/|&^%]|<<|>>)?=(?!=)")
_BARE_DECL = re.compile(r"^(?:const\s+)?(?:char|u?int(?:8|16|32|64)_t|int|unsigned|float|double|bool)\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$")
_CASE = re.compile(r"^case\s+(\d+)\s*:\s*")
_LINEAR = re.compile(r"^(?:static_cast<(u?int16_t)>\()?values\[(\d+)\]\)?(?:\s*\*\s*([0-9]*\.?[0-9]+)f?)?$")
_OFFSET = re.compile(r"^\((?:static_cast<(u?int16_t)>\()?values\[(\d+)\]\)?\s*-\s*(\d+)\)\s*\*\s*([0-9]*\.?[0-9]+)f?$")
_BIT = re.compile(r"^\(values\[(\d+)\]\s*&\s*(0x[0-9A-Fa-f]+)\)\s*!=\s*0$")
_BIT_EQ = re.compile(r"^\(([A-Za-z_]\w*|values\[\d+\])\s*&\s*(0x[0-9A-Fa-f]+)\)\s*==\s*(0x[0-9A-Fa-f]+)$")
_BIT_NE = re.compile(r"^\(([A-Za-z_]\w*)\s*&\s*(0x[0-9A-Fa-f]+)\)\s*!=\s*0$")
_TERNARY_BIT = re.compile(r'^\(values\[(\d+)\]\s*&\s*(0x[0-9A-Fa-f]+)\)\s*\?\s*"([^"]*)"\s*:\s*"([^"]*)"$')
_FUNC = re.compile(r"^(format_time|charge_source|tou_mode)\(values\[(\d+)\]\)$")
_STRING = re.compile(r'^"([^"\\]*)"$')


def _strip_comments(code: str) -> str:
    out = []
    for line in code.split("\n"):
        in_str = False
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str
            elif not in_str and line.startswith("//", i):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def _statements(code: str):
    """Yield (kind, text) with kind 'stmt', 'open' (block header) or 'close'. Paren-aware; strings are skipped."""
    buf, depth, in_str, prev = [], 0, False, ""
    for ch in code:
        if in_str:
            buf.append(ch)
            if ch == '"' and prev != "\\":
                in_str = False
        elif ch == '"':
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == ";" and depth == 0:
            yield "stmt", "".join(buf).strip()
            buf = []
        elif ch == "{" and depth == 0:
            yield "open", "".join(buf).strip()
            buf = []
        elif ch == "}" and depth == 0:
            if "".join(buf).strip():
                yield "stmt", "".join(buf).strip()
            buf = []
            yield "close", ""
        else:
            buf.append(ch)
        prev = ch
    if "".join(buf).strip():
        yield "stmt", "".join(buf).strip()


def _shape(expr: str, var_shapes: dict) -> dict:
    e = " ".join(expr.split())
    m = _LINEAR.match(e)
    if m:
        return {"kind": "linear", "signed": m.group(1) == "int16_t", "scale": float(m.group(3)) if m.group(3) else 1.0, "offset": 0}
    m = _OFFSET.match(e)
    if m:
        return {"kind": "linear", "signed": m.group(1) == "int16_t", "scale": float(m.group(4)), "offset": int(m.group(3))}
    m = _BIT.match(e)
    if m:
        return {"kind": "bit", "mask": int(m.group(2), 16)}
    m = _TERNARY_BIT.match(e)
    if m:
        return {"kind": "bit_text", "mask": int(m.group(2), 16), "set_text": m.group(3), "clear_text": m.group(4)}
    m = _BIT_EQ.match(e)
    if m:
        return {"kind": "bit_equals", "mask": int(m.group(2), 16), "equals": int(m.group(3), 16)}
    m = _BIT_NE.match(e)
    if m:
        return {"kind": "bit", "mask": int(m.group(2), 16)}
    m = _FUNC.match(e)
    if m:
        return {"kind": {"format_time": "hhmm", "charge_source": "tou_charge", "tou_mode": "tou_mode"}[m.group(1)]}
    if e in var_shapes:
        return dict(var_shapes[e])
    return {"kind": "derived"}


def decode_window(window: dict) -> dict[str, dict]:
    """{entity id: {"indices": set, "shape": dict, "cases": {raw: text}}} for one steady window's decode lambda."""
    code = _strip_comments(window["lambda"])
    var_idx: dict[str, set] = {}
    var_shapes: dict[str, dict] = {}
    stack: list[set] = []
    out: dict[str, dict] = {}

    def refs(text: str) -> set:
        idx = {int(n) for n in _VALUES.findall(text)}
        for name in _IDENT.findall(text):
            idx |= var_idx.get(name, set())
        return idx

    for kind, text in _statements(code):
        if kind == "open":
            header = text
            m = re.search(r"switch\s*\((.*)\)\s*$", header, re.S)
            stack.append(refs(m.group(1)) if m else set())
            continue
        if kind == "close":
            if stack:
                stack.pop()
            continue
        case_val = None
        m = _CASE.match(text)
        if m:
            case_val = int(m.group(1))
            text = text[m.end():].strip()
        elif text.startswith("default:"):
            text = text[len("default:"):].strip()
        m = _PUBLISH.search(text)
        if m and text.startswith("id("):
            ent, expr = m.group(1), m.group(2)
            ctx = set().union(*stack) if stack else set()
            idx = refs(expr) | ctx
            slot = out.setdefault(ent, {"indices": set(), "shape": None, "cases": {}})
            slot["indices"] |= idx
            sm = _STRING.match(" ".join(expr.split()))
            if case_val is not None and sm:
                slot["cases"][case_val] = sm.group(1)
                slot["shape"] = slot["shape"] or {"kind": "enum"}
            elif slot["shape"] is None:
                slot["shape"] = _shape(expr, var_shapes) if not ctx else {"kind": "enum"}
            continue
        # A write to a variable REPLACES what it holds (C++ semantics): snprintf overwrites its buffer, an assignment
        # overwrites its target (a self-reference such as `x = -x` keeps x's own indices through refs()).
        m = _SNPRINTF.search(text)
        if m:
            var_idx[m.group(1)] = refs(m.group(2))
            var_shapes[m.group(1)] = {"kind": "derived"}
            continue
        m = _DECL.match(text)
        if m and not text.startswith("id("):
            name, rhs = m.group(1), m.group(2)
            fresh = name not in var_shapes
            var_idx[name] = refs(rhs)
            lm = _LINEAR.match(" ".join(rhs.split()))
            var_shapes[name] = ({"kind": "linear", "signed": lm.group(1) == "int16_t", "scale": 1.0, "offset": 0}
                                if fresh and lm and not lm.group(3) else {"kind": "derived"})
            continue
        m = _BARE_DECL.match(text)
        if m:
            var_idx[m.group(1)] = set()
            var_shapes.pop(m.group(1), None)
            continue
        # Any other statement that assigns to a known variable (e.g. `if (x < 0) x = -x`) makes its value non-linear:
        # no raw value may be derived from it any more.
        for name in _ASSIGN_TARGET.findall(text):
            if name in var_shapes:
                var_shapes[name] = {"kind": "derived"}
    return out


def firmware_decode(fw: dict) -> tuple[dict[str, dict], list[dict]]:
    """{entity id: {"registers": sorted list, "shape", "cases", "window", "poll_class"}} over the six steady windows."""
    windows = steady_windows(fw)
    decoded: dict[str, dict] = {}
    for w in windows:
        for ent, info in decode_window(w).items():
            regs = sorted(w["start"] + i for i in info["indices"] if 0 <= i < w["count"])
            if not regs:
                continue
            if ent in decoded:
                raise GeneratorError(f"{FIRMWARE_REL}: entity {ent!r} is published by two steady windows")
            decoded[ent] = {"registers": regs, "shape": info["shape"] or {"kind": "derived"},
                            "cases": dict(sorted(info["cases"].items())),
                            "window": f"{w['start']}-{w['start'] + w['count'] - 1}", "poll_class": w["poll_class"]}
    return decoded, windows


# ---------------------------------------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------------------------------------
def registers_of(rec: dict) -> list[dict]:
    regs = []
    for r in ((rec.get("modbus") or {}).get("registers") or []):
        if isinstance(r, dict) and isinstance(r.get("address"), int):
            regs.append({"address": r["address"], "bits": str(r["bits"]) if r.get("bits") is not None else None})
    return regs


def derived_status(rec: dict) -> str:
    if rec["live_proof_status"] == "unknown" or rec["write_policy"] == "WX":
        return "UNSUPPORTED"
    if rec["current_access"] in ("read_write", "write_only"):
        return "PROVEN" if rec["live_proof_status"] == "live_proven_write" else "EXPERIMENTAL"
    return "READ_ONLY"


DEFAULT_LOCK_REASON = {
    "PROVEN": "A hardware-tested ECCO write path exists elsewhere in ECCO (its own guarded controls). This page is read-only "
              "and cannot change it.",
    "EXPERIMENTAL": "A firmware write path exists but is not hardware-proven for this record. This page is read-only.",
    "READ_ONLY": "ECCO has no write path for this setting. It is shown for inspection only.",
    "LOCKED": "Safety-critical: permanently read-only on this installation.",
    "UNSUPPORTED": "The register or meaning is not established (registry evidence: unknown). It is never offered as a control.",
}


def section_of(rec: dict, ov: dict) -> str:
    spec = (ov.get("records") or {}).get(rec["id"], {})
    if "section" in spec:
        return spec["section"]
    for rule in ov.get("section_rules") or []:
        if re.fullmatch(rule["id_pattern"], rec["id"]):
            return rule["section"]
    cat = ov["category_sections"].get(rec["category"])
    if cat is None:
        raise GeneratorError(f"{OVERLAY_REL}: no section for registry category {rec['category']!r} (record {rec['id']})")
    return cat


def danger_of(rec: dict, ov: dict) -> str:
    spec = (ov.get("records") or {}).get(rec["id"], {})
    if "danger" in spec:
        return spec["danger"]
    d = ov["category_danger"].get(rec["category"])
    if d is None:
        raise GeneratorError(f"{OVERLAY_REL}: no danger class for registry category {rec['category']!r} (record {rec['id']})")
    return d


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    return " ".join(str(v).split())


def normalize_ha_text(text: str | None) -> str | None:
    """Registry text names ESPHome text sensors by their ESPHome platform; Home Assistant puts them in the `sensor` domain."""
    if text is None:
        return None
    return re.sub(r"(?<![A-Za-z0-9_.])text_sensor\.(" + DEFAULT_SLUG + r"_)", r"sensor.\1", text)


def link_entity(rec: dict, ents: dict, decoded: dict, links: dict) -> tuple[str | None, str | None]:
    """(firmware entity id, link source) for a record, or (None, None)."""
    by_obj = {(e["domain"], e["object"]): fid for fid, e in ents.items()}
    if rec["id"] in links:
        fid = links[rec["id"]]
        if fid not in ents:
            raise GeneratorError(f"{OVERLAY_REL}: entity_links: {rec['id']}: no firmware entity {fid!r}")
        return fid, "overlay"
    for raw in rec.get("entity_ha_raw") or []:
        if not isinstance(raw, str) or "." not in raw:
            continue
        dom, _, obj = raw.partition(".")
        dom = HA_DOMAIN.get(dom, dom)
        if obj.startswith(DEFAULT_SLUG + "_"):
            obj = obj[len(DEFAULT_SLUG) + 1:]
        if (dom, obj) in by_obj:
            return by_obj[(dom, obj)], "registry"
        if obj in ents and ents[obj]["domain"] == dom:
            return obj, "registry"
    regs = {r["address"] for r in registers_of(rec)}
    if regs:
        cands = sorted(fid for fid, d in decoded.items() if set(d["registers"]) == regs and fid in ents
                       and not ents[fid]["name"].endswith((" Raw", " Raw Flags")))
        if len(cands) == 1:
            return cands[0], "firmware_decode"
    return None, None


def raw_entity(rec: dict, ents: dict, decoded: dict) -> str | None:
    regs = {r["address"] for r in registers_of(rec)}
    if not regs:
        return None
    cands = sorted(fid for fid, d in decoded.items() if set(d["registers"]) == regs and fid in ents
                   and ents[fid]["name"].endswith((" Raw", " Raw Flags")))
    return cands[0] if len(cands) == 1 else None


def options_of(rec: dict, dec: dict | None) -> dict:
    """Available options / range, labelled by where they come from. A firmware ceiling is never called a hardware maximum."""
    opts: dict = {}
    if dec and dec.get("cases"):
        opts["enum"] = [{"raw": int(k), "label": v} for k, v in sorted(dec["cases"].items())]
        opts["enum_source"] = "firmware decode"
    elif isinstance(rec.get("enum_mapping"), dict) and rec["enum_mapping"]:
        items = []
        for k, v in rec["enum_mapping"].items():
            try:
                raw = int(str(k), 0)
            except ValueError:
                continue
            items.append({"raw": raw, "label": str(v)})
        if items:
            opts["enum"] = sorted(items, key=lambda x: x["raw"])
            opts["enum_source"] = "capability registry"
    for k in ("safe_min", "safe_max"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            opts[k] = v
    hw = ((rec.get("limits") or {}).get("hardware") or {})
    if isinstance(hw, dict) and hw:
        src = str(hw.get("source", ""))
        val = hw.get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and "firmware_substitution" in src:
            opts["firmware_ceiling"] = val
            opts["firmware_ceiling_note"] = ("ECCO firmware compile-time ceiling (a site setting), not a verified inverter "
                                             "hardware maximum.")
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            opts["registry_limit"] = val
        else:
            opts["hardware_maximum"] = None
    if rec.get("bounds_note"):
        opts["bounds_note"] = _text(rec["bounds_note"])
    return opts


def build_items(registry: list[dict], ov: dict, ents: dict, decoded: dict) -> list[dict]:
    items = []
    recs_ov = ov.get("records") or {}
    links = ov.get("entity_links") or {}
    for rec in registry:
        spec = recs_ov.get(rec["id"], {})
        base = derived_status(rec)
        final = base
        lock_reason = DEFAULT_LOCK_REASON[base]
        if "restrict" in spec:
            want = spec["restrict"]
            if STATUS_RANK[want] < STATUS_RANK[base]:
                raise GeneratorError(f"{OVERLAY_REL}: records: {rec['id']}: restrict {want} would PROMOTE the derived status "
                                     f"{base} (the overlay may only restrict)")
            final = want
            lock_reason = spec["lock_reason"]
        elif "lock_reason" in spec:
            lock_reason = spec["lock_reason"]
        regs = registers_of(rec)
        fid, link_src = link_entity(rec, ents, decoded, links)
        dec = decoded.get(fid) if fid else None
        if fid and dec and regs and not ({r["address"] for r in regs} & set(dec["registers"])):
            raise GeneratorError(f"{rec['id']}: linked entity {fid!r} decodes registers {dec['registers']} but the record is "
                                 f"{[r['address'] for r in regs]} (fix the registry link or the overlay entity_links)")
        rid = raw_entity(rec, ents, decoded)
        entity = None
        if fid:
            e = ents[fid]
            entity = {"domain": e["domain"], "object": e["object"], "firmware_id": fid, "name": e["name"], "link": link_src}
        raw = None
        if rid:
            e = ents[rid]
            raw = {"domain": e["domain"], "object": e["object"], "firmware_id": rid, "name": e["name"]}
        modbus = rec.get("modbus") or {}
        unit = modbus.get("unit") if isinstance(modbus.get("unit"), str) else None
        decode = None
        if dec:
            decode = {"kind": dec["shape"]["kind"], "window": dec["window"], "registers": dec["registers"]}
            for k in ("signed", "scale", "offset", "mask", "equals", "set_text", "clear_text"):
                if k in dec["shape"]:
                    decode[k] = dec["shape"][k]
        poll_class = dec["poll_class"] if dec else None
        if poll_class is None and regs:
            a = regs[0]["address"]
            poll_class = "rtc" if a <= 24 else "telemetry" if a < 200 else "configuration"
        item = {
            "id": rec["id"],
            "name": rec["name"],
            "category": rec["category"],
            "section": section_of(rec, ov),
            "registers": regs,
            "datatype": modbus.get("datatype") if isinstance(modbus.get("datatype"), str) else None,
            "unit": unit,
            "status": final,
            "status_derived": base,
            "evidence": EVIDENCE_BY_PROOF[rec["live_proof_status"]],
            "live_proof_status": rec["live_proof_status"],
            "write_policy": rec["write_policy"],
            "current_access": rec["current_access"],
            "danger": danger_of(rec, ov),
            "lock_reason": lock_reason,
            "entity": entity,
            "raw_entity": raw,
            "decode": decode,
            "poll_class": poll_class,
            "options": options_of(rec, dec),
            "description": normalize_ha_text(_text(rec.get("description"))),
            "explanation": spec.get("explanation"),
            "safety_impact": normalize_ha_text(_text(rec.get("safety_impact"))),
            "write_policy_reason": normalize_ha_text(_text(rec.get("write_policy_reason"))),
            "notes": normalize_ha_text(_text(rec.get("notes"))),
            "interactions": spec.get("interactions") or [],
            "options_note": spec.get("options_note"),
            "provenance": {
                "registry_record": rec["id"],
                "firmware_evidence": normalize_ha_text(_text(rec.get("firmware_evidence"))),
                "ha_evidence": normalize_ha_text(_text(rec.get("ha_evidence"))),
                "implementation_status": _text(rec.get("implementation_status")),
            },
        }
        items.append({k: v for k, v in item.items() if v is not None})
    return items


def build_global_power(ov: dict, items: list[dict]) -> dict:
    gp = ov["global_power"]
    rec = [i for i in items if i["id"] == gp["record"]]
    if len(rec) != 1:
        raise GeneratorError(f"{OVERLAY_REL}: global_power.record {gp['record']!r} not in the catalogue")
    item = rec[0]
    if [r["address"] for r in item["registers"]] != [gp["register"]]:
        raise GeneratorError(f"global_power: record {item['id']} is registers {[r['address'] for r in item['registers']]}, "
                             f"not register {gp['register']}")
    if item["status"] == "PROVEN":
        raise GeneratorError("global_power: the record is PROVEN writable, but Global Power writes are not implemented in this phase")
    return {
        "record": gp["record"],
        "register": gp["register"],
        "title": gp["title"],
        "owner_confirmation": gp["owner_confirmation"],
        "hardware_maximum_w": gp.get("hardware_maximum_w"),
        "hardware_maximum_evidence": gp.get("hardware_maximum_evidence"),
        "hardware_maximum_note": gp.get("hardware_maximum_note"),
        "regulatory_allowance_w": gp.get("regulatory_allowance_w"),
        "regulatory_note": gp.get("regulatory_note"),
        "write_status": gp["write_status"],
        "write_blockers": gp["write_blockers"],
        "limitations": gp["limitations"],
        "future_controls": gp["future_controls"],
    }


# ---------------------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------------------
def build_catalogue(root: Path = ROOT) -> dict:
    registry = load_registry(read_text(root, REGISTRY_REL))
    ov = load_overlay(read_text(root, OVERLAY_REL), {r["id"] for r in registry})
    try:
        fw = yaml.load(read_text(root, FIRMWARE_REL), Loader=_firmware_loader())  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as ex:
        raise GeneratorError(f"{FIRMWARE_REL}: not valid YAML ({ex})") from None
    if not isinstance(fw, dict):
        raise GeneratorError(f"{FIRMWARE_REL}: the top level must be a mapping")
    ents = firmware_entities(fw)
    decoded, windows = firmware_decode(fw)
    for name in ("telemetry_online", "configuration_online"):
        if name not in ents or ents[name]["domain"] != "binary_sensor":
            raise GeneratorError(f"{FIRMWARE_REL}: the {name} binary sensor is missing (freshness gates)")
    items = build_items(registry, ov, ents, decoded)
    section_ids = [s["id"] for s in ov["sections"]]
    used = {i["section"] for i in items}
    empty = [s for s in section_ids if s not in used]
    if empty:
        raise GeneratorError(f"{OVERLAY_REL}: section(s) {empty} would be empty")
    items.sort(key=lambda i: (section_ids.index(i["section"]),
                              min((r["address"] for r in i["registers"]), default=99999), i["id"]))
    cat = {
        "schema": CATALOGUE_SCHEMA,
        "generator": "tools/build_advanced_config_catalogue.py",
        "inputs": [REGISTRY_REL, OVERLAY_REL, "firmware main YAML (entity names and steady-poll decode only)"],
        "read_only": True,
        "default_entity_prefix_note": "Entity ids are built at run time from the card's entity_prefix option.",
        "notes": ov.get("notes"),
        "controller_note": ov.get("controller_note"),
        "sections": ov["sections"],
        "freshness_gates": {
            "telemetry": {"domain": "binary_sensor", "object": ents["telemetry_online"]["object"]},
            "configuration": {"domain": "binary_sensor", "object": ents["configuration_online"]["object"]},
        },
        "steady_windows": [f"{w['start']}-{w['start'] + w['count'] - 1}" for w in windows],
        "record_count": len(items),
        "items": items,
        "global_power": build_global_power(ov, items),
    }
    return portable_numbers({k: v for k, v in cat.items() if v is not None})


def portable_numbers(obj):
    """Numbers that print identically in Python's json and JavaScript's JSON.stringify, so the card's own tests can
    re-verify CATALOGUE_SHA256: an integral float becomes an int (1.0 -> 1), and a float the two languages would spell
    differently (Python uses an exponent below 1e-4, JavaScript only from 1e21) is refused."""
    if isinstance(obj, dict):
        return {k: portable_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [portable_numbers(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise GeneratorError(f"non-finite number {obj!r} in the catalogue")
        if obj.is_integer() and abs(obj) < 2 ** 53:
            return int(obj)
        if abs(obj) < 1e-4 or abs(obj) >= 1e16:
            raise GeneratorError(f"number {obj!r} has no portable JSON spelling")
    return obj


def canonical(cat: dict) -> str:
    return json.dumps(cat, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def render_module(cat: dict) -> str:
    digest = hashlib.sha256(canonical(cat).encode("utf-8")).hexdigest()
    body = json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False)
    return ("// GENERATED by tools/build_advanced_config_catalogue.py - do not edit by hand.\n"
            "// Read-only inputs: registry/inverter_capabilities.yaml, registry/advanced_config_overlay.yaml and the firmware's\n"
            "// entity names / steady-poll decode. Regenerate with: python tools/build_advanced_config_catalogue.py\n"
            "import type { Catalogue } from \"./types.ts\";\n\n"
            f"export const CATALOGUE_SHA256 = \"{digest}\";\n\n"
            f"export const CATALOGUE: Catalogue = {body};\n")


def validate_output(text: str, root: Path = ROOT) -> None:
    for tok in RESERVED_TOKENS:
        if tok in text:
            raise GeneratorError(f"generated catalogue contains the reserved token {tok!r} (frontend/ must not carry it)")
    for word in WRITE_VOCABULARY:
        if word in text:
            raise GeneratorError(f"generated catalogue contains write vocabulary {word!r}")
    sys.path.insert(0, str(root / "tools"))
    try:
        import ecco_site_render as R  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    actions = R.firmware_actions(root)
    try:
        ident, _ = R.render_text(OUTPUT_REL, text, R.Site(), actions)
        custom, _ = R.render_text(OUTPUT_REL, text, R.Site(device_slug="probe_dongle"), actions)
    except R.RenderError as ex:
        raise GeneratorError(f"the site renderer would refuse the generated catalogue: {ex}") from None
    if ident != text:
        raise GeneratorError("the default site render is not the identity for the generated catalogue")
    if any(f"{d}.{DEFAULT_SLUG}_" in custom for d in R.DOMAINS):
        raise GeneratorError("a default-slug entity id survives a custom render of the generated catalogue")


def generate(root: Path = ROOT) -> str:
    text = render_module(build_catalogue(root))
    validate_output(text, root)
    return text


def link_report(root: Path = ROOT) -> str:
    cat = build_catalogue(root)
    by_link: dict = {}
    lines = []
    for it in cat["items"]:
        src = (it.get("entity") or {}).get("link", "none")
        by_link[src] = by_link.get(src, 0) + 1
        if src == "none":
            lines.append(f"  unlinked  {it['id']}  registers={[r['address'] for r in it['registers']]}")
    head = [f"records: {cat['record_count']}", "entity links: " + ", ".join(f"{k}={v}" for k, v in sorted(by_link.items()))]
    return "\n".join(head + lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed module is stale; write nothing")
    ap.add_argument("--report", action="store_true", help="print the entity-link report; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.report:
            print(link_report(root))
            return 0
        text = generate(root)
    except GeneratorError as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2
    out = root / OUTPUT_REL
    if args.check:
        current = out.read_text(encoding="utf-8") if out.is_file() else None
        if current != text:
            print(f"STALE: {OUTPUT_REL} differs from the generator output (run the generator)", file=sys.stderr)
            return 1
        print(f"OK: {OUTPUT_REL} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
