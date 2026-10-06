#!/usr/bin/env python3
"""Offline extractor for the ECCO firmware's inverter write surface.

READ-ONLY ANALYSIS. This tool parses the ESPHome firmware YAML as text,
builds a structured model of every Modbus read/write the firmware can
issue and of the ownership flags each write path acquires, and reports
it. It performs no I/O against Home Assistant, ESPHome, or the inverter,
and it never writes to the firmware file.

Why this exists
---------------
`registry/tests/test_reg244_proof_harness_logic.py` proved that
structural facts about the firmware CAN be asserted offline, but it did
so with hand-written `str.find()` offsets and exact C++ message-literal
matches scoped to two scripts. That is brittle (any wording change
breaks it) and it does not generalise - the other nine write paths get
no structural coverage at all.

This module extracts the same class of facts ONCE, into a structure, so
that:

  * the register ownership/conflict matrix is derived from the firmware
    rather than maintained by hand in a document, and
  * invariants ("every script that writes a register acquires the shared
    write mutex before its first write") can be asserted across EVERY
    write path uniformly - see
    registry/tests/test_write_surface_invariants.py.

Limitations (stated, not papered over)
--------------------------------------
This is a text/structure extractor, not an ESPHome compiler or a
simulator. It knows nothing about C++ semantics, control flow, or what
the inverter does. A fact it reports is "this is what the source file
says", never "this is what the hardware does". Values written from
`!lambda` expressions are recorded as expressions, not evaluated.

Fail-closed extent and coverage (2026-09-28 safety-gap audit)
-------------------------------------------------------------
Two ways this extractor used to be able to under-report the write
surface silently are now refused instead:

  * Write EXTENT. A write's register count is only ever taken from a
    shape whose element count is certain: a static YAML `values:` list,
    or a `!lambda` (block `|-` or inline '...') whose every `return` is a
    flat literal `std::vector<uint16_t>{...}` initialiser with the same
    element count. Anything else (a vector built with push_back, a
    helper call, conditional returns of different lengths, a missing or
    lambda start_address, ...) is recorded as UNKNOWN EXTENT - it is
    never assumed to be one register. `ModbusOp.addresses` raises
    `WriteExtentUnknown` for such a write, so every consumer of the write
    surface fails rather than under-counting, and the CLI exits non-zero.
  * Write COVERAGE. The per-script extractor above only models writes
    inside `script:` entries. `bus_access_findings()` independently walks
    the WHOLE parsed firmware YAML tree (plus its `esphome: includes:` C++
    headers) and flags, for review, every bus access it cannot classify:
    a Modbus write action outside a `script:` entry (button, interval,
    api action, on_boot, sensor trigger, ...), any `modbus_client.*`
    action other than the two modelled ones, raw C++ use of the Modbus
    bus or its UART, a `modbus_controller` component, a raw `uart.write`,
    unscanned YAML (`packages:`/`!include`) or `external_components`, and
    any disagreement between the tree walk and the text extractor about
    which script issues which write. This is a conservative DETECTION
    layer, not a full ESPHome parser: it can over-flag, never silently
    pass an unmodelled writer it can see.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIRMWARE = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

# Ownership/interlock flags the firmware uses to arbitrate access to the
# single physical Modbus channel. Ordered most-shared first. These names
# are the current ad hoc ownership model; the audit
# (docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md) proposes replacing
# them with one owner record, at which point this list becomes the
# migration checklist.
OWNERSHIP_FLAGS = (
    "manual_write_in_progress",
    "correction_in_progress",
    "free_power_operation_in_progress",
    "reg244_apply_in_progress",
    "dump_operation_in_progress",
)

# Persisted (restore_value: yes) flags that represent an outstanding
# obligation surviving a reboot.
OBLIGATION_FLAGS = (
    "free_power_snapshot_valid",
    "free_power_active_persisted",
    "free_power_restore_requested",
    "reg244_snapshot_valid",
    "reg244_last_applied_valid",
    "dump_snapshot_valid",
    "dump_active_persisted",
    "dump_restore_requested",
)

_ARM_SWITCHES = ("manual_config_write_enable", "free_power_write_enable", "dump_write_enable")

# The two `modbus_client.*` actions this extractor models. Any other
# `modbus_client.*` action is reported by bus_access_findings().
_MODELLED_MODBUS_ACTIONS = ("read_holding_registers", "write_multiple_registers")

# Methods of the Modbus bus component that only QUERY bus state (used by the
# start gates' bus-quiescence check). Any other `id(<modbus bus>)->method`
# call in a lambda is raw bus access and is reported.
_READ_ONLY_BUS_METHODS = ("tx_buffer_empty", "tx_blocked")

# C++ spellings that would issue Modbus traffic without going through a
# `modbus_client.*` YAML action (ESPHome's modbus_controller command API).
_RAW_MODBUS_CPP = re.compile(
    r"\bModbusCommandItem\b|\bcreate_write_\w+\s*\(|\bqueue_command\s*\(|\bsend_raw\s*\("
    r"|\bmodbus_controller::|\bmodbus::Modbus\b"
)


class WriteExtentUnknown(ValueError):
    """A write's register extent could not be determined with certainty."""


class _Lambda(str):
    """The C++ source of a `!lambda` scalar, kept distinct from plain text."""


class _FirmwareLoader(yaml.SafeLoader):
    """SafeLoader that keeps ESPHome's custom tags as plain values."""


def _construct_tagged(loader: _FirmwareLoader, suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        return _Lambda(value) if suffix == "lambda" else value
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_FirmwareLoader.add_multi_constructor("!", _construct_tagged)


def _load_firmware_yaml(text: str):
    return yaml.load(text, Loader=_FirmwareLoader)


@dataclass
class ModbusOp:
    """One `modbus_client.*` action inside a script or button handler."""

    kind: str  # "read" | "write"
    start_address: int | None  # None only for a write whose start is not a literal
    count: int | None  # reads: declared count. writes: element count when CERTAIN.
    value_expr: str | None  # writes only: the raw `values:` expression text.
    offset: int  # character offset within the enclosing block, for ordering
    # writes only: why the extent is unknown (None when it is certain).
    extent_unknown_reason: str | None = None

    @property
    def extent_known(self) -> bool:
        if self.kind != "write":
            return True
        return self.start_address is not None and self.count is not None

    @property
    def addresses(self) -> list[int]:
        if not self.extent_known:
            raise WriteExtentUnknown(
                f"write at start_address={self.start_address}: {self.extent_unknown_reason}"
            )
        # Reads without a declared count keep the historical 1-register default.
        n = self.count if self.count is not None else 1
        return list(range(self.start_address, self.start_address + n))


@dataclass
class WritePath:
    """One firmware script (or button handler) that can touch the bus."""

    name: str
    kind: str  # "script" | "button"
    body: str
    ops: list[ModbusOp] = field(default_factory=list)
    # Ownership flags this block SETS to true, mapped to first offset.
    acquires: dict[str, int] = field(default_factory=dict)
    # Ownership flags this block TESTS (reads) anywhere, mapped to first offset.
    checks: dict[str, int] = field(default_factory=dict)
    releases: list[str] = field(default_factory=list)
    arms_checked: list[str] = field(default_factory=list)
    obligations_set: list[str] = field(default_factory=list)
    obligations_cleared: list[str] = field(default_factory=list)
    delays_ms: list[int] = field(default_factory=list)
    dispatches: list[str] = field(default_factory=list)
    # Offsets of every `wait_until:` step (completion-driven sequencing -
    # see ecco_durable / the 2026-09-21 durability/sequencing hotfix) and
    # of every `ecco_durable::commit_record(` call (a checked, synchronous
    # preferences commit, as opposed to "assign a restore_value: yes global
    # then wait").
    wait_until_offsets: list[int] = field(default_factory=list)
    durable_commit_offsets: list[int] = field(default_factory=list)

    @property
    def writes(self) -> list[ModbusOp]:
        return [o for o in self.ops if o.kind == "write"]

    @property
    def reads(self) -> list[ModbusOp]:
        return [o for o in self.ops if o.kind == "read"]

    @property
    def written_addresses(self) -> set[int]:
        out: set[int] = set()
        for op in self.writes:
            out.update(op.addresses)
        return out

    @property
    def first_write_offset(self) -> int | None:
        w = self.writes
        return min(o.offset for o in w) if w else None

    def durable_commits_before(self, offset: int | None) -> int:
        """How many ecco_durable::commit_record() calls precede `offset`."""
        if offset is None:
            return len(self.durable_commit_offsets)
        return sum(1 for o in self.durable_commit_offsets if o < offset)


def _parse_int(text: str) -> int:
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def _strip_cpp_comments_and_literals(code: str) -> str:
    """Remove C++ comments and blank out string/char literal contents.

    A `//`, `,` or `return` inside a log format string, or a `,` inside a
    comment within an initialiser list, must not change what the element
    counter below sees.
    """
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
        elif ch == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif ch in "\"'":
            quote = ch
            i += 1
            while i < n and code[i] != quote:
                i += 2 if code[i] == "\\" else 1
            i += 1
            out.append(quote * 2)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _matching_close(text: str, open_pos: int) -> int | None:
    """Index of the bracket closing the one at `open_pos`, or None."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] in "({[":
            depth += 1
        elif text[i] in ")}]":
            depth -= 1
            if depth == 0:
                return i
    return None


def _top_level_elements(inner: str) -> list[str] | None:
    """Split an initialiser list body on its top-level commas."""
    parts, depth, current = [], 0, []
    for ch in inner:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
            if depth < 0:
                return None
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if depth != 0:
        return None
    parts.append("".join(current))
    parts = [p.strip() for p in parts]
    if parts and parts[-1] == "":  # C++ permits one trailing comma
        parts.pop()
    return parts


_VECTOR_RETURN = re.compile(r"^\s*std::vector<\s*(?:std::)?uint16_t\s*>\s*\{")


def _lambda_value_count(code: str) -> tuple[int | None, str | None]:
    """Element count of a `values: !lambda` body, or (None, reason).

    The count is only reported when it is CERTAIN from the source text:
    every `return` statement must be exactly `return std::vector<uint16_t>{
    e1, ..., eN };` (a flat literal initialiser list - nothing after the
    closing brace), and all of them must agree on N. Anything else - a
    vector built up with push_back/resize, a helper call, a nested lambda,
    a ( )-constructor, an iterator-pair initialiser, returns of different
    lengths - is reported as unknown rather than guessed.
    """
    clean = _strip_cpp_comments_and_literals(code)
    returns = [m.end() for m in re.finditer(r"\breturn\b", clean)]
    if not returns:
        return None, "values: lambda has no return statement"
    counts: set[int] = set()
    for pos in returns:
        tail = clean[pos:]
        vm = _VECTOR_RETURN.match(tail)
        if not vm:
            return None, "a values: lambda return is not a literal std::vector<uint16_t>{...}"
        close = _matching_close(tail, vm.end() - 1)
        if close is None or not re.match(r"\s*;", tail[close + 1 :]):
            return None, "a values: lambda return is not a single literal std::vector<uint16_t>{...};"
        elements = _top_level_elements(tail[vm.end() : close])
        if elements is None or any(e == "" for e in elements):
            return None, "values: initialiser list could not be split into elements"
        if any(re.search(r"\bbegin\s*\(|\bend\s*\(|\.\.\.", e) for e in elements):
            return None, "values: initialiser list looks like an iterator range/pack, not N elements"
        counts.add(len(elements))
    if len(counts) != 1:
        return None, f"values: lambda returns differ in element count {sorted(counts)}"
    n = counts.pop()
    if n == 0:
        return None, "values: lambda returns an empty vector"
    return n, None


def _static_value_count(values: list) -> tuple[int | None, str | None]:
    if not values:
        return None, "values: static list is empty"
    return len(values), None


def _action_mapping(body: str, key_start: int) -> dict | None:
    """Parse the YAML mapping of the action whose key starts at `key_start`.

    Returns None when `key_start` is not a YAML action key (e.g. it sits in
    a comment) or the mapping does not parse. The action's own lines are
    the key line plus every following line indented deeper than the key
    (or blank), exactly YAML's own block rule.
    """
    line_start = body.rfind("\n", 0, key_start) + 1
    prefix = body[line_start:key_start]
    if not re.fullmatch(r"\s*(?:-\s+)?", prefix):
        return None
    key_col = len(prefix)
    lines = body[key_start:].split("\n")
    kept = [" " * key_col + lines[0]]
    for line in lines[1:]:
        if line.strip() and (len(line) - len(line.lstrip(" "))) <= key_col:
            break
        kept.append(line)
    try:
        doc = _load_firmware_yaml("\n".join(line[key_col:] for line in kept))
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or len(doc) != 1:
        return None
    mapping = next(iter(doc.values()))
    return mapping if isinstance(mapping, dict) else None


def _write_op(body: str, key_start: int) -> ModbusOp:
    """Model one `modbus_client.write_multiple_registers` action.

    Never guesses: a start address or element count that is not certain
    from the source leaves the op's extent UNKNOWN, with a reason.
    """
    mapping = _action_mapping(body, key_start)
    if mapping is None:
        return ModbusOp("write", None, None, None, key_start, "action mapping could not be parsed")
    start = mapping.get("start_address")
    values = mapping.get("values")
    value_expr: str | None = None
    if isinstance(values, _Lambda):
        value_expr = str(values)
        count, reason = _lambda_value_count(value_expr)
    elif isinstance(values, list):
        value_expr = repr(values)
        count, reason = _static_value_count(values)
    elif values is None:
        count, reason = None, "no values: key"
    else:
        value_expr = str(values)
        count, reason = None, f"unsupported values: shape {type(values).__name__}"
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        start = None
        reason = reason or "start_address is not a literal register number"
    return ModbusOp("write", start, count, value_expr, key_start, reason)


def _split_blocks(text: str) -> list[tuple[str, str, str]]:
    """Split the firmware into named top-level blocks.

    Yields (kind, name, body) for every `  - id: <name>` script entry and
    every `  - platform: template` button entry that has an `id:`. Blocks
    run until the next sibling at the same two-space indent, or the next
    top-level YAML key.
    """
    # Section boundaries so we can tell a script id from a button id.
    sections: list[tuple[int, str]] = [
        (m.start(), m.group(1)) for m in re.finditer(r"^([a-z_]+):\s*$", text, re.M)
    ]

    def section_of(pos: int) -> str:
        name = "?"
        for p, n in sections:
            if p <= pos:
                name = n
            else:
                break
        return name

    # Every sibling entry at two-space indent starts a candidate block.
    starts = [m.start() for m in re.finditer(r"^  - (?:id|platform):", text, re.M)]
    boundaries = starts + [len(text)]
    # A top-level section header also terminates the preceding block.
    section_positions = sorted(p for p, _ in sections)

    blocks: list[tuple[str, str, str]] = []
    for i, start in enumerate(starts):
        end = boundaries[i + 1]
        for p in section_positions:
            if start < p < end:
                end = p
                break
        body = text[start:end]
        # The block's own id is either `  - id: <name>` (script entries)
        # or a `    id: <name>` line directly under `  - platform: ...`.
        # Deeper-indented `id:` keys belong to nested actions
        # (`script.execute:`, `button.press:`) and must not be matched.
        m = re.search(r"^(?:  - id|    id):\s*([A-Za-z0-9_]+)\s*$", body, re.M)
        if not m:
            continue
        sect = section_of(start)
        kind = "script" if sect == "script" else ("button" if sect == "button" else sect)
        blocks.append((kind, m.group(1), body))
    return blocks


def _extract_ops(body: str) -> list[ModbusOp]:
    ops: list[ModbusOp] = []
    for m in re.finditer(
        r"modbus_client\.(read_holding_registers|write_multiple_registers):", body
    ):
        line_start = body.rfind("\n", 0, m.start()) + 1
        if not re.fullmatch(r"\s*(?:-\s+)?", body[line_start : m.start()]):
            # Not in YAML action-key position (a `#` comment, a lambda's
            # C++ comment or string). bus_access_findings() cross-checks
            # this extractor against the parsed YAML tree, so a real action
            # skipped here would still be reported.
            continue
        if m.group(1).startswith("write"):
            # Writes are modelled from the action's real YAML mapping, and
            # an extent that is not certain is recorded as UNKNOWN - never
            # skipped and never defaulted to one register.
            ops.append(_write_op(body, m.start()))
            continue
        # Reads: the action's own mapping ends at the next sibling list
        # item at the action's indentation or shallower. Slicing a generous
        # window and taking the FIRST start_address/count is safe because
        # those keys always precede the on_* handlers.
        window = body[m.end() : m.end() + 3000]
        sa = re.search(r"start_address:\s*(0x[0-9A-Fa-f]+|\d+)", window)
        if not sa:
            continue
        cm = re.search(r"\bcount:\s*(\d+)", window)
        ops.append(
            ModbusOp(
                kind="read",
                start_address=_parse_int(sa.group(1)),
                count=int(cm.group(1)) if cm else None,
                value_expr=None,
                offset=m.start(),
            )
        )
    return ops


def _first_offset(body: str, pattern: str) -> int | None:
    m = re.search(pattern, body)
    return m.start() if m else None


def analyze(firmware_path: Path = DEFAULT_FIRMWARE) -> dict:
    text = firmware_path.read_text(encoding="utf-8")
    paths: list[WritePath] = []

    for kind, name, body in _split_blocks(text):
        ops = _extract_ops(body)
        wp = WritePath(name=name, kind=kind, body=body, ops=ops)

        for flag in OWNERSHIP_FLAGS:
            off = _first_offset(body, rf"id\({flag}\)\s*=\s*true")
            if off is not None:
                wp.acquires[flag] = off
            # A "check" is any read of the flag that is not an assignment.
            for m in re.finditer(rf"id\({flag}\)(?!\s*=[^=])", body):
                wp.checks.setdefault(flag, m.start())
            if re.search(rf"id\({flag}\)\s*=\s*false", body):
                wp.releases.append(flag)

        for sw in _ARM_SWITCHES:
            if re.search(rf"id\({sw}\)\.state", body):
                wp.arms_checked.append(sw)

        for flag in OBLIGATION_FLAGS:
            if re.search(rf"id\({flag}\)\s*=\s*true", body):
                wp.obligations_set.append(flag)
            if re.search(rf"id\({flag}\)\s*=\s*false", body):
                wp.obligations_cleared.append(flag)

        wp.delays_ms = [int(d) for d in re.findall(r"delay:\s*(\d+)ms", body)]
        wp.dispatches = re.findall(r"script\.execute:\s*\n\s*id:\s*(\w+)", body)
        wp.wait_until_offsets = [m.start() for m in re.finditer(r"wait_until:", body)]
        wp.durable_commit_offsets = [
            m.start() for m in re.finditer(r"ecco_durable::commit_record\(", body)
        ]

        if ops or wp.acquires or wp.dispatches:
            paths.append(wp)

    return {
        "firmware": str(firmware_path),
        "paths": paths,
        "text": text,
        "unknown_extent_writes": unknown_extent_writes(paths),
        "bus_access_findings": bus_access_findings(firmware_path, text, paths),
    }


# ---------------------------------------------------------------------------
# Fail-closed coverage checks (see the module docstring)
# ---------------------------------------------------------------------------


def unknown_extent_writes(paths: list[WritePath]) -> list[dict]:
    """Every write whose register extent is not certain from the source."""
    out = []
    for p in paths:
        for op in p.writes:
            if not op.extent_known:
                out.append(
                    {
                        "path": p.name,
                        "kind": p.kind,
                        "start_address": op.start_address,
                        "reason": op.extent_unknown_reason,
                    }
                )
    return out


def _component_ids(section) -> set[str]:
    items = section if isinstance(section, list) else [section]
    return {i["id"] for i in items if isinstance(i, dict) and isinstance(i.get("id"), str)}


def bus_access_findings(firmware_path: Path, text: str, paths: list[WritePath]) -> list[dict]:
    """Every inverter-bus access the write-surface model does not cover.

    Walks the whole parsed YAML tree - not just `script:` entries - so a
    writer added anywhere else (button, interval, api action, on_boot,
    entity trigger, ...) is reported instead of silently falling outside
    write_surface(). An empty list is the only passing result.
    """
    findings: list[dict] = []

    def flag(where: str, reason: str) -> None:
        findings.append({"where": where, "reason": reason})

    try:
        doc = _load_firmware_yaml(text)
    except yaml.YAMLError as exc:
        return [{"where": str(firmware_path), "reason": f"firmware YAML does not parse: {exc}"}]
    if not isinstance(doc, dict):
        return [{"where": str(firmware_path), "reason": "firmware YAML is not a mapping"}]

    modbus_ids = _component_ids(doc.get("modbus")) or {"inverter_modbus"}
    uart_ids = _component_ids(doc.get("uart")) or {"inverter_uart"}
    bus_call = re.compile(r"\bid\(\s*(\w+)\s*\)\s*(?:->|\.)\s*(\w+)")

    for key in ("packages", "external_components", "modbus_controller"):
        if key in doc:
            flag(key, f"top-level `{key}:` can add bus writers this analysis does not see")
    if re.search(r"!include\b", text):
        flag("!include", "`!include` pulls in YAML this analysis does not see")

    def scan_code(where: str, code: str) -> None:
        for m in bus_call.finditer(code):
            target, method = m.group(1), m.group(2)
            if target in modbus_ids and method not in _READ_ONLY_BUS_METHODS:
                flag(where, f"raw C++ call id({target})->{method}() on the Modbus bus")
            elif target in uart_ids:
                flag(where, f"raw C++ call id({target})->{method}() on the Modbus UART")
        if _RAW_MODBUS_CPP.search(code):
            flag(where, "C++ Modbus command API used outside a modbus_client action")

    tree_script_writes: Counter = Counter()

    def walk(node, where: str, script_id: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{where}/{k}"
                if isinstance(k, str) and k.startswith("modbus_client."):
                    action = k.split(".", 1)[1]
                    if action not in _MODELLED_MODBUS_ACTIONS:
                        flag(here, f"unmodelled Modbus action `{k}` (may write)")
                    elif action.startswith("write") and script_id is None:
                        flag(here, "Modbus write outside any `script:` entry - not in the write surface")
                    elif action.startswith("write"):
                        start = v.get("start_address") if isinstance(v, dict) else None
                        tree_script_writes[(script_id, start if isinstance(start, int) else None)] += 1
                elif k == "uart.write":
                    flag(here, "raw `uart.write` action")
                elif k == "platform" and v == "modbus_controller":
                    flag(here, "`modbus_controller` entity can write registers outside any script")
                walk(v, here, script_id)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{where}[{i}]", script_id)
        elif isinstance(node, str):
            scan_code(where, _strip_cpp_comments_and_literals(node))

    for top_key, section in doc.items():
        if top_key == "script" and isinstance(section, list):
            for i, entry in enumerate(section):
                sid = entry.get("id") if isinstance(entry, dict) else None
                sid = sid if isinstance(sid, str) else None
                walk(entry, f"script[{sid or i}]", sid)
                if sid is None:
                    flag(f"script[{i}]", "script entry without a plain `id:` - writes cannot be attributed")
        else:
            walk(section, str(top_key), None)

    # The text extractor (which write_surface() is built from) and the tree
    # walk must agree exactly on which script issues which write; any
    # difference means the text block splitter mis-attributed or missed one.
    text_script_writes: Counter = Counter(
        (p.name, op.start_address) for p in paths if p.kind == "script" for op in p.writes
    )
    if text_script_writes != tree_script_writes:
        missing = tree_script_writes - text_script_writes
        extra = text_script_writes - tree_script_writes
        flag(
            "script",
            "text extractor and YAML tree disagree on script writes: "
            f"only in YAML tree {sorted(missing.items(), key=str)}, "
            f"only in text extractor {sorted(extra.items(), key=str)}",
        )

    # C++ headers compiled into the firmware can reach the bus too.
    esphome = doc.get("esphome") if isinstance(doc.get("esphome"), dict) else {}
    for inc in esphome.get("includes") or []:
        header = firmware_path.parent / str(inc)
        if not header.is_file():
            flag(f"esphome/includes/{inc}", "included file not found - cannot be scanned")
            continue
        code = _strip_cpp_comments_and_literals(header.read_text(encoding="utf-8"))
        scan_code(f"esphome/includes/{inc}", code)
        if re.search(r"\b(?:" + "|".join(map(re.escape, modbus_ids | uart_ids)) + r")\b", code):
            flag(f"esphome/includes/{inc}", "included C++ references the Modbus bus/UART")

    return findings


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------


def write_surface(paths: list[WritePath]) -> dict[int, list[str]]:
    """address -> sorted list of script names that write it."""
    out: dict[int, set[str]] = {}
    for p in paths:
        if p.kind != "script":
            continue
        for addr in p.written_addresses:
            out.setdefault(addr, set()).add(p.name)
    return {a: sorted(v) for a, v in sorted(out.items())}


def conflict_matrix(paths: list[WritePath]) -> list[dict]:
    """Every register written by more than one script."""
    surface = write_surface(paths)
    return [
        {"address": a, "writers": w} for a, w in surface.items() if len(w) > 1
    ]


def unguarded_write_paths(paths: list[WritePath]) -> list[dict]:
    """Scripts that write without first setting the shared write mutex.

    `manual_write_in_progress` is the closest thing the firmware has to a
    single "the bus is owned" flag: Free Power, the six TOU slot writers
    and both register 244 scripts all set it. A write path that never
    sets it is outside that arbitration.
    """
    out = []
    for p in paths:
        if p.kind != "script" or not p.writes:
            continue
        fw_off = p.first_write_offset
        acq = p.acquires.get("manual_write_in_progress")
        if acq is None:
            out.append({"script": p.name, "reason": "never sets manual_write_in_progress"})
        elif fw_off is not None and acq > fw_off:
            out.append(
                {"script": p.name, "reason": "sets manual_write_in_progress AFTER its first write"}
            )
    return out


def lock_taken_without_check(paths: list[WritePath]) -> list[dict]:
    """Scripts that set manual_write_in_progress=true without first
    verifying it was actually free.

    `unguarded_write_paths()` above only proves a script SETS the flag
    before its first write - that is "took the lock", not "checked the
    lock". A script that never reads the flag (or only reads it AFTER
    already taking it) could stomp a lock another transaction is already
    holding and then race it on the bus. `WritePath.checks[flag]` records
    the offset of the EARLIEST non-assignment read of the flag anywhere in
    the script body; a genuine pre-acquire guard requires that offset to
    exist and to precede the acquire offset.
    """
    out = []
    for p in paths:
        if p.kind != "script" or not p.writes:
            continue
        acq = p.acquires.get("manual_write_in_progress")
        if acq is None:
            continue  # reported separately by unguarded_write_paths()
        check_off = p.checks.get("manual_write_in_progress")
        if check_off is None or check_off > acq:
            out.append(
                {
                    "script": p.name,
                    "reason": "sets manual_write_in_progress=true without checking it was free first",
                }
            )
    return out


def ownership_blind_spots(paths: list[WritePath]) -> list[dict]:
    """For each writing script, which ownership flags it never consults."""
    out = []
    for p in paths:
        if p.kind != "script" or not p.writes:
            continue
        missing = [f for f in OWNERSHIP_FLAGS if f not in p.checks and f not in p.acquires]
        if missing:
            out.append({"script": p.name, "does_not_check": missing})
    return out


def _fmt_addresses(addrs: list[int]) -> str:
    """Collapse a sorted address list into compact ranges."""
    if not addrs:
        return "-"
    addrs = sorted(addrs)
    parts, run_start, prev = [], addrs[0], addrs[0]
    for a in addrs[1:]:
        if a == prev + 1:
            prev = a
            continue
        parts.append(f"{run_start}" if run_start == prev else f"{run_start}-{prev}")
        run_start = prev = a
    parts.append(f"{run_start}" if run_start == prev else f"{run_start}-{prev}")
    return ", ".join(parts)


def render_report(result: dict) -> str:
    paths: list[WritePath] = result["paths"]
    writers = [p for p in paths if p.kind == "script" and p.writes]
    lines: list[str] = []
    a = lines.append

    a(f"ECCO firmware write-surface analysis: {result['firmware']}")
    a("")
    a("=== Write paths (scripts issuing write_multiple_registers) ===")
    a("")
    a(f"{'script':<30} | {'writes':<28} | {'acquires':<50} | arm")
    a("-" * 30 + "-+-" + "-" * 28 + "-+-" + "-" * 50 + "-+----")
    for p in sorted(writers, key=lambda x: x.name):
        acq = ", ".join(sorted(p.acquires)) or "NONE"
        arm = ", ".join(p.arms_checked) or "NONE"
        addrs = _fmt_addresses(sorted(p.written_addresses))
        a(f"{p.name:<30} | {addrs:<28} | {acq:<50} | {arm}")

    a("")
    a("=== Full write surface (register -> writers) ===")
    a("")
    for addr, names in write_surface(paths).items():
        a(f"  {addr:>5}  {', '.join(names)}")

    a("")
    a("=== Shared registers (written by more than one path) ===")
    a("")
    cm = conflict_matrix(paths)
    if not cm:
        a("  (none)")
    for row in cm:
        a(f"  {row['address']:>5}  {', '.join(row['writers'])}")

    a("")
    a("=== Write paths outside the shared write mutex ===")
    a("")
    ug = unguarded_write_paths(paths)
    if not ug:
        a("  (none)")
    for row in ug:
        a(f"  {row['script']}: {row['reason']}")

    a("")
    a("=== Ownership blind spots (flags a writing script never consults) ===")
    a("")
    for row in ownership_blind_spots(paths):
        a(f"  {row['script']}: {', '.join(row['does_not_check'])}")

    a("")
    a("=== Lock taken without checking it was free first ===")
    a("")
    ltwc = lock_taken_without_check(paths)
    if not ltwc:
        a("  (none)")
    for row in ltwc:
        a(f"  {row['script']}: {row['reason']}")

    a("")
    a("=== Sequencing model ===")
    a("")
    a("  Some write paths still pace their Modbus sequence with fixed `delay:`")
    a("  steps; others (2026-09-21 durability/sequencing hotfix) instead use")
    a("  `wait_until:` on a terminal flag set by the operation's own callback,")
    a("  and commit recovery data via a checked ecco_durable::commit_record()")
    a("  call rather than a delay-and-hope. Per path:")
    for p in sorted(writers, key=lambda x: x.name):
        a(
            f"    {p.name:<32}delays={p.delays_ms} "
            f"wait_until={len(p.wait_until_offsets)} durable_commits={len(p.durable_commit_offsets)}"
        )

    a("")
    a("NOTE: this is a source-structure analysis. It reports what the firmware")
    a("file says, never what the inverter does.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--firmware", type=Path, default=DEFAULT_FIRMWARE)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    if not args.firmware.is_file():
        print(f"firmware not found: {args.firmware}", file=sys.stderr)
        return 2

    result = analyze(args.firmware)
    unknown = result["unknown_extent_writes"]
    findings = result["bus_access_findings"]
    if unknown or findings:
        # Fail closed: the write surface cannot be stated with certainty, so
        # no (under-counting) report is printed at all.
        if args.json:
            print(
                json.dumps(
                    {
                        "firmware": result["firmware"],
                        "error": "write surface cannot be determined with certainty",
                        "unknown_extent_writes": unknown,
                        "bus_access_findings": findings,
                    },
                    indent=2,
                )
            )
        else:
            print(f"ECCO firmware write-surface analysis: {result['firmware']}")
            print("")
            print("FAILED - the write surface cannot be determined with certainty.")
            if unknown:
                print("")
                print("=== Writes with UNKNOWN register extent (never assumed to be one register) ===")
                print("")
                for row in unknown:
                    print(f"  {row['path']} ({row['kind']}) start_address={row['start_address']}: {row['reason']}")
            if findings:
                print("")
                print("=== Unclassified inverter-bus access (review required) ===")
                print("")
                for row in findings:
                    print(f"  {row['where']}: {row['reason']}")
        return 3
    if args.json:
        paths: list[WritePath] = result["paths"]
        print(
            json.dumps(
                {
                    "firmware": result["firmware"],
                    "write_surface": {str(k): v for k, v in write_surface(paths).items()},
                    "conflicts": conflict_matrix(paths),
                    "unguarded": unguarded_write_paths(paths),
                    "blind_spots": ownership_blind_spots(paths),
                    "lock_taken_without_check": lock_taken_without_check(paths),
                },
                indent=2,
            )
        )
    else:
        print(render_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
