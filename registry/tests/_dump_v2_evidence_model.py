"""Offline model of the Dump-to-Grid V2 durable record and its ownership evidence.

firmware/include/ecco_durable_snapshot.h defines DumpToGridSnapshotData (V2,
tag `ecco_dump_to_grid_snapshot_data_v2`) and the retired
DumpToGridSnapshotDataV1 layout. This module is the independent Python mirror
the offline tests hold the header and the firmware to:

  - byte layouts of V1 and V2 (natural C layout, little-endian), pinned
    against the header's static_asserts by
    registry/tests/test_dump_v2_ownership_evidence.py;
  - the resolution of the header's tag constants/aliases, so a mutated header
    (e.g. DUMP_TO_GRID_DATA_TAG aliased back to V1) flows straight into the
    simulator;
  - the REFERENCE ownership classifier the later Dump PR will implement in
    firmware. It is test-side ONLY: nothing in this PR's firmware reads the
    evidence or classifies anything.

V1 layout - 24 bytes: 22 data + 2 tail padding (end_epoch forces 4-byte
alignment):

    offset 0   uint32  end_epoch
    offset 4   uint8   active_persisted
    offset 5   uint8   restore_requested
    offset 6   uint16  reg244
    offset 8   uint16  reg256 .. offset 18 reg261   (ORIGINAL snapshot)
    offset 20  uint16  reg_dump_power_intended
    offset 22  --      2 bytes padding

V2 layout - 24 bytes, no padding: V1 plus

    offset 22  uint16  reg_dump_power_pending

Same size, so the stored-size check in load_record() cannot tell them apart;
only the tag bump does.

Ownership evidence (per register i of 256-261): Dump may have left live ONLY
ORIGINAL[i], reg_dump_power_intended or reg_dump_power_pending.
"""

from __future__ import annotations

import ctypes
import re
import struct

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
V2_KIND = "DumpToGridSnapshotData"
V1_KIND = "DumpToGridSnapshotDataV1"
V1_TAG = "ecco_dump_to_grid_snapshot_data_v1"
V2_TAG = "ecco_dump_to_grid_snapshot_data_v2"
VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"
RECORD_SIZE = 24
# Dump V2 rollback tombstone written under V1_TAG by every V2 START (header:
# DUMP_V1_TOMBSTONE_REG244). Pre-V2 loaders accept a V1 record only if reg244 <= 2.
V1_TOMBSTONE_REG244 = 0xFFFF

V1_FIELDS = ["end_epoch", "active_persisted", "restore_requested", "reg244",
             "reg256", "reg257", "reg258", "reg259", "reg260", "reg261", "reg_dump_power_intended"]
V2_FIELDS = V1_FIELDS + ["reg_dump_power_pending"]
ORIGINAL_FIELDS = [f"reg{r}" for r in range(256, 262)]
CEILING_REGS = tuple(range(256, 262))

# Explicit little-endian layouts (the ESP32 is little-endian). V1's trailing
# `2x` is its tail padding; V2 has none.
_V1_STRUCT = struct.Struct("<IBB8H2x")
_V2_STRUCT = struct.Struct("<IBB9H")
assert _V1_STRUCT.size == RECORD_SIZE and _V2_STRUCT.size == RECORD_SIZE

# Offsets the header's static_asserts pin (field -> byte offset).
V2_OFFSETS = {"end_epoch": 0, "active_persisted": 4, "restore_requested": 5, "reg244": 6,
              "reg256": 8, "reg257": 10, "reg258": 12, "reg259": 14, "reg260": 16, "reg261": 18,
              "reg_dump_power_intended": 20, "reg_dump_power_pending": 22}


class V1C(ctypes.Structure):
    """ctypes mirror with NATIVE C layout - proves the 24-byte size comes from
    alignment, not from struct's packed `<` mode."""

    _fields_ = [("end_epoch", ctypes.c_uint32), ("active_persisted", ctypes.c_uint8),
                ("restore_requested", ctypes.c_uint8)] + [(f, ctypes.c_uint16) for f in V1_FIELDS[3:]]


class V2C(ctypes.Structure):
    _fields_ = [("end_epoch", ctypes.c_uint32), ("active_persisted", ctypes.c_uint8),
                ("restore_requested", ctypes.c_uint8)] + [(f, ctypes.c_uint16) for f in V2_FIELDS[3:]]


def _get(record, name):
    return record[name] if isinstance(record, dict) else getattr(record, name)


def pack_v1(record, padding: bytes = b"\x00\x00") -> bytes:
    """V1 bytes as flash holds them. `padding` models the 2 tail-padding
    bytes: zero when the firmware value-initialised the record (`{}`), but
    NOT guaranteed by the language, and never something V2 may rely on."""
    body = _V1_STRUCT.pack(*(int(_get(record, f)) for f in V1_FIELDS))
    return body[:22] + bytes(padding)


def pack_v2(record) -> bytes:
    return _V2_STRUCT.pack(*(int(_get(record, f)) for f in V2_FIELDS))


def unpack_v1(data: bytes) -> dict:
    if len(data) != RECORD_SIZE:
        raise ValueError(f"record is {RECORD_SIZE} bytes, got {len(data)}")
    return dict(zip(V1_FIELDS, _V1_STRUCT.unpack(data)))


def unpack_v2(data: bytes) -> dict:
    if len(data) != RECORD_SIZE:
        raise ValueError(f"record is {RECORD_SIZE} bytes, got {len(data)}")
    return dict(zip(V2_FIELDS, _V2_STRUCT.unpack(data)))


PACK = {V1_KIND: pack_v1, V2_KIND: pack_v2}
UNPACK = {V1_KIND: unpack_v1, V2_KIND: unpack_v2}


# ---------------------------------------------------------------------------
# Header tag resolution
# ---------------------------------------------------------------------------
_TAG_LITERAL = re.compile(r'constexpr const char \*(\w+)\s*=\s*"([^"]+)";')
_TAG_ALIAS = re.compile(r"constexpr const char \*(\w+)\s*=\s*([A-Z_][A-Z0-9_]*);")


def header_tags(header_text: str) -> dict:
    """Every `constexpr const char *NAME = ...;` in the header, aliases
    resolved to their literal (e.g. DUMP_TO_GRID_DATA_TAG -> the V2 string)."""
    tags = dict(_TAG_LITERAL.findall(header_text))
    aliases = dict(_TAG_ALIAS.findall(header_text))
    for _ in range(len(aliases) + 1):
        for name, target in aliases.items():
            if target in tags:
                tags[name] = tags[target]
    unresolved = set(aliases) - set(tags)
    if unresolved:
        raise ValueError(f"unresolved tag aliases: {sorted(unresolved)}")
    return tags


def esphome_fnv1_hash(text: str) -> int:
    """esphome::fnv1_hash() (esphome/core/helpers.cpp): 32-bit FNV-1
    (multiply, THEN xor) - what ecco_durable::key_for() turns a tag into, and
    whose decimal string is the actual NVS key."""
    h = 2166136261
    for c in text.encode("ascii"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= c
    return h


# ---------------------------------------------------------------------------
# Reference ownership classifier (test-side ONLY - not in firmware yet)
# ---------------------------------------------------------------------------
ORIGINAL = "ORIGINAL"
DUMP_OWNED = "DUMP_OWNED"
FOREIGN = "FOREIGN"


def evidence_set(record, reg: int) -> set:
    """Every value register `reg` (256..261) may hold because of Dump itself,
    per the durable V2 record: ORIGINAL[reg], intended, pending."""
    if reg not in CEILING_REGS:
        raise ValueError(f"register {reg} is not a Dump ceiling register")
    return {int(_get(record, f"reg{reg}")), int(_get(record, "reg_dump_power_intended")),
            int(_get(record, "reg_dump_power_pending"))}


def classify_register(record, reg: int, live: int) -> str:
    """The later firmware classifier's per-register rule, as specified:
    ORIGINAL if live == ORIGINAL[reg]; else DUMP_OWNED if live is the
    intended or the pending ceiling; else FOREIGN. ORIGINAL wins a tie."""
    live = int(live)
    if live == int(_get(record, f"reg{reg}")):
        return ORIGINAL
    if live in (int(_get(record, "reg_dump_power_intended")), int(_get(record, "reg_dump_power_pending"))):
        return DUMP_OWNED
    return FOREIGN


def classify_bank(record, bank: dict) -> dict:
    """{reg: classification} for all six ceiling registers."""
    return {r: classify_register(record, r, bank.get(r, 0)) for r in CEILING_REGS}


def uncovered(record, bank: dict) -> dict:
    """{reg: live} for every ceiling register whose live value is NOT in the
    record's evidence set - empty means the evidence contains the bank."""
    return {r: int(bank.get(r, 0)) for r in CEILING_REGS if int(bank.get(r, 0)) not in evidence_set(record, r)}
