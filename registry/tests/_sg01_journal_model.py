"""Offline model of the SG-01 Free Power START journal record.

SG-01 Phase 0 introduced this module as TEST-SIDE infrastructure only. Since
SG-01 Phase 1/2 the record is REAL production state:
firmware/include/ecco_durable_snapshot.h defines FreePowerStartJournal,
FREE_POWER_START_JOURNAL_TAG, free_power_start_journal_binding() and
free_power_start_journal_valid(), and
firmware/ecco_clock_dongle_stage3_4_free_power.yaml commits the journal
before each START write and loads it at boot. This module is the independent
Python mirror the offline tests hold the firmware to: the header's
compile-time golden vectors (static_assert) are re-derived here by
registry/tests/test_sg01_journal_phase1_2.py, so the C++ build and this model
must agree byte-for-byte.

Schema (SG-01 approved blueprint) - 16 bytes, natural C layout:

    offset 0   uint32  magic           JOURNAL_MAGIC (0x4543534A)
    offset 4   uint8   start_attempted a PREFIX mask of the four START write
                                       stages; valid values 0, 1, 3, 7, 15
    offset 5   uint8   flags           bit0 = START_VERIFIED; any other bit
                                       is invalid; START_VERIFIED is only
                                       valid together with mask 15
    offset 6   uint16  reserved        MUST be zero
    offset 8   uint64  binding         FNV-1a-64 over the START snapshot

Why the masks are 0/1/3/7/15: Free Power START issues its four mutation
writes as a strict prefix - B1 = reg232, B2 = reg230, B3 = regs 268-279,
B4 = regs 256-261, each gated on every earlier success (PR #45,
registry/tests/test_free_power_write_sequencing_hardening.py). A journal that
records "attempted" progress can therefore only ever hold a prefix mask.

Tag: `ecco_free_power_start_journal_v1`.

Binding - FNV-1a 64-bit (offset basis 0xcbf29ce484222325, prime
0x100000001b3) over, in order:

    domain  b"ECCO-FP-START-JOURNAL-v1"   (24 ASCII bytes, no terminator)
    end_epoch                             u32 little-endian
    reg230, reg232, reg256..261, reg268..279,
    reg230_intended, reg_tou_power_intended,
    reg244_lease_context_plus1            each u16 little-endian, in
                                          FreePowerSnapshotData field order

`active_persisted` and `restore_requested` are deliberately EXCLUDED: they are
lifecycle flags that legitimately change during a transaction, so binding to
them would make a journal fail to match its own snapshot.
"""

from __future__ import annotations

import ctypes
import struct

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
JOURNAL_KIND = "FreePowerStartJournal"
JOURNAL_TAG = "ecco_free_power_start_journal_v1"
JOURNAL_MAGIC = 0x4543534A  # 'ECSJ' as a big-endian reading of the constant
JOURNAL_SIZE = 16
JOURNAL_VALID_START_ATTEMPTED_MASKS = (0, 1, 3, 7, 15)
# The mask START commits immediately before each write stage (header:
# FREE_POWER_START_JOURNAL_MASK_B1..B4).
JOURNAL_MASK_B1, JOURNAL_MASK_B2, JOURNAL_MASK_B3, JOURNAL_MASK_B4 = 0x01, 0x03, 0x07, 0x0F
JOURNAL_FLAG_START_VERIFIED = 0x01
JOURNAL_KNOWN_FLAGS = JOURNAL_FLAG_START_VERIFIED
JOURNAL_FIELDS = ["magic", "start_attempted", "flags", "reserved", "binding"]

# Explicit little-endian layout: 4 + 1 + 1 + 2 + 8 = 16, no padding needed
# (every field already sits on its natural alignment).
_STRUCT = struct.Struct("<IBBHQ")
assert _STRUCT.size == JOURNAL_SIZE


class JournalC(ctypes.Structure):
    """ctypes mirror with NATIVE C layout - proves the 16-byte logical size
    does not depend on struct's packed `<` mode (uint64 lands on offset 8)."""

    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("start_attempted", ctypes.c_uint8),
        ("flags", ctypes.c_uint8),
        ("reserved", ctypes.c_uint16),
        ("binding", ctypes.c_uint64),
    ]


def pack_journal(record) -> bytes:
    """Serialises anything exposing the five journal fields."""
    return _STRUCT.pack(*(int(getattr(record, f)) for f in JOURNAL_FIELDS))


def unpack_journal(data: bytes) -> dict:
    if len(data) != JOURNAL_SIZE:
        raise ValueError(f"journal is {JOURNAL_SIZE} bytes, got {len(data)}")
    return dict(zip(JOURNAL_FIELDS, _STRUCT.unpack(data)))


# Classification of a LOADED journal, mirroring the firmware's
# ecco_durable::free_power_start_journal_valid() (which returns only a bool;
# the distinct codes here exist for test diagnostics). load_record() itself
# only checks size, exactly like the real header - it never validates content.
JOURNAL_OK = "ok"
JOURNAL_BAD_MAGIC = "bad_magic"
JOURNAL_BAD_START_ATTEMPTED = "bad_start_attempted"
JOURNAL_BAD_FLAGS = "bad_flags"
JOURNAL_BAD_RESERVED = "bad_reserved"
JOURNAL_BAD_VERIFIED_PARTIAL = "bad_verified_partial"
JOURNAL_BAD_BINDING = "bad_binding"


def classify_journal(record, expected_binding=None) -> str:
    """Schema (and, when `expected_binding` is given, binding) classification
    of a journal that WAS loaded (load_record()==true).

    Order is stable: magic, start_attempted mask, unknown flag bits, reserved,
    START_VERIFIED-with-partial-mask, binding. Without `expected_binding` the
    binding is not checked (schema-only classification).
    """
    if int(record.magic) != JOURNAL_MAGIC:
        return JOURNAL_BAD_MAGIC
    if int(record.start_attempted) not in JOURNAL_VALID_START_ATTEMPTED_MASKS:
        return JOURNAL_BAD_START_ATTEMPTED
    if int(record.flags) & ~JOURNAL_KNOWN_FLAGS & 0xFF:
        return JOURNAL_BAD_FLAGS
    if int(record.reserved) != 0:
        return JOURNAL_BAD_RESERVED
    if int(record.flags) & JOURNAL_FLAG_START_VERIFIED and int(record.start_attempted) != JOURNAL_MASK_B4:
        return JOURNAL_BAD_VERIFIED_PARTIAL
    if expected_binding is not None and int(record.binding) != int(expected_binding):
        return JOURNAL_BAD_BINDING
    return JOURNAL_OK


def journal_valid(record, expected_binding) -> bool:
    """Python mirror of ecco_durable::free_power_start_journal_valid()."""
    return classify_journal(record, expected_binding) == JOURNAL_OK


# ---------------------------------------------------------------------------
# Binding mirror
# ---------------------------------------------------------------------------
FNV64_OFFSET_BASIS = 0xCBF29CE484222325
FNV64_PRIME = 0x100000001B3
BINDING_DOMAIN = b"ECCO-FP-START-JOURNAL-v1"

# FreePowerSnapshotData field order, minus the excluded lifecycle flags.
BINDING_U16_FIELDS = (
    ["reg230", "reg232"]
    + [f"reg{n}" for n in range(256, 262)]
    + [f"reg{n}" for n in range(268, 280)]
    + ["reg230_intended", "reg_tou_power_intended", "reg244_lease_context_plus1"]
)
BINDING_FIELDS = ["end_epoch"] + BINDING_U16_FIELDS
BINDING_EXCLUDED_FIELDS = ("active_persisted", "restore_requested")


def fnv1a_64(data: bytes) -> int:
    h = FNV64_OFFSET_BASIS
    for b in data:
        h ^= b
        h = (h * FNV64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def _field(snapshot, name):
    return snapshot[name] if isinstance(snapshot, dict) else getattr(snapshot, name)


def binding_input_bytes(snapshot) -> bytes:
    """The exact byte string the binding hashes (after the domain)."""
    out = BINDING_DOMAIN + struct.pack("<I", int(_field(snapshot, "end_epoch")) & 0xFFFFFFFF)
    for name in BINDING_U16_FIELDS:
        value = int(_field(snapshot, name))
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{name}={value} does not fit a uint16")
        out += struct.pack("<H", value)
    return out


def journal_binding(snapshot) -> int:
    """`snapshot` is a dict or any object exposing the FreePowerSnapshotData
    fields (the sim's Record works). Extra fields, including the excluded
    active_persisted / restore_requested, are ignored."""
    return fnv1a_64(binding_input_bytes(snapshot))


# The firmware's RAM mirror of the journal (start_free_power_override /
# on_boot globals).
RAM_GLOBALS = ("free_power_start_journal_valid", "free_power_start_journal_mask",
               "free_power_start_journal_flags", "free_power_start_journal_binding")


def ram_after_b1(binding: int) -> dict:
    """The journal RAM mirror immediately after START's successful B1 commit
    - the state a simulation of START's post-commit tail begins from."""
    return dict(zip(RAM_GLOBALS, (True, JOURNAL_MASK_B1, 0, binding)))


def blank_snapshot(**overrides) -> dict:
    """A FreePowerSnapshotData-shaped dict (all fields present, zeroed)."""
    snap = {"end_epoch": 0, "active_persisted": 0, "restore_requested": 0}
    snap.update({name: 0 for name in BINDING_U16_FIELDS})
    snap.update(overrides)
    return snap
