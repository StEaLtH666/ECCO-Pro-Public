"""Python reference model of the Fallback Profile V1 / Failback State V1
data contracts (FB-A).

firmware/include/ecco_fallback_profile.h is the C++ side of the same
contract. FB-A is deliberately BEHAVIOUR-FREE: the header is standalone (no
ESPHome include, not listed in the firmware's `esphome: includes:`, included
by no production source), and nothing commits, loads or classifies either
record. This module is the independent mirror the offline tests hold the
header to: registry/tests/test_fallback_profile_schema.py re-derives the
header's compile-time golden vectors and golden-case tables from it, and
registry/tests/test_fallback_profile_host_compile.py makes a host C++
compiler evaluate those same static_asserts.

FallbackProfileV1 - 96 bytes, natural C layout, no implicit padding:

    offset  0  u32  magic           PROFILE_MAGIC (0x45434650)
    offset  4  u16  schema          1
    offset  6  u16  size            96
    offset  8  u32  generation      >= 1 (0 is CORRUPT)
    offset 12  u32  captured_epoch  0 when the clock was invalid at capture
    offset 16  u16  flags           bit0 INVALIDATED; bits 1-15 MUST be 0
    offset 18  u16  reg244          E1 (restricted): MUST be 2
    offset 20  u16  reg256_261[6]   E1: 500..V1_TOU_POWER_MAX_W (8000)
    offset 32  u16  reg268_273[6]   E1: 0..100
    offset 44  u16  reg274_279[6]   E1 bits 0-1 only: word in {0,1}
    offset 56  u16  reg232          CTX, bit 0 only (bits 1-15 informational)
    offset 58  u16  reg243          CTX, full word
    offset 60  u16  reg248          CTX, bit 0 only (bits 1-15 informational)
    offset 62  u16  reg250_255[6]   CTX, full word
    offset 74  u16  reg230          INFO
    offset 76  u16  reg245          INFO
    offset 78  u16  reg247          INFO
    offset 80  u32  reserved0       MUST be 0
    offset 84  u32  reserved1       MUST be 0
    offset 88  u64  binding         FNV-1a-64(b"ECCO-FALLBACK-PROFILE-v1" + bytes[0:88])

FailbackStateV1 - 80 bytes, natural C layout, no implicit padding:

    offset  0  u32  magic               FAILBACK_MAGIC (0x45434642)
    offset  4  u16  schema              1
    offset  6  u16  size                80
    offset  8  u8   state               FAILBACK_* (0..4)
    offset  9  u8   reason              FAILBACK_REASON_* (0..2)
    offset 10  u8   result              FAILBACK_RESULT_* (0..11)
    offset 11  u8   flags               bit0 lease_preempted, bit1 apply_committed,
                                        bit2 divergence_reboot_used; bits 3-7 MUST be 0
    offset 12  u32  event_seq
    offset 16  u32  event_epoch
    offset 20  u32  profile_generation  0 iff no profile is bound
    offset 24  u8   apply_attempts
    offset 25  u8   verify_mismatches
    offset 26  u16  from_244
    offset 28  u16  from_256_261[6]
    offset 40  u16  from_268_279[12]
    offset 64  u64  profile_binding     0 iff no profile is bound
    offset 72  u64  binding             FNV-1a-64(b"ECCO-FAILBACK-STATE-v1" + bytes[0:72])

Every multi-byte field is serialised field by field, little-endian, so
"bytes[0:N]" is exactly the stored record on the (little-endian) ESP32.

Pure: no I/O except firmware_tou_power_ceiling_w(), which only reads the
firmware YAML text so the tests can pin V1_TOU_POWER_MAX_W against the
configured ${ecco_inverter_tou_power_ceiling_w}. Profile validity never
depends on that runtime/site value.
"""

from __future__ import annotations

import ctypes
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

# ---------------------------------------------------------------------------
# Hashes. Two DIFFERENT algorithms, never to be confused:
#   - FNV-1a-64 (xor, then multiply): the records' content binding.
#   - FNV-1 32-bit (multiply, then xor): esphome::fnv1_hash(), which
#     ecco_durable::key_for() uses to derive the NVS preference key of a tag.
# ---------------------------------------------------------------------------
FNV1A64_OFFSET_BASIS = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3
FNV1_32_OFFSET_BASIS = 0x811C9DC5
FNV1_32_PRIME = 0x01000193
_U64 = 0xFFFFFFFFFFFFFFFF


def fnv1a_64(data: bytes, h: int = FNV1A64_OFFSET_BASIS) -> int:
    for b in data:
        h = ((h ^ b) * FNV1A64_PRIME) & _U64
    return h


def fnv1_32(tag: str) -> int:
    """esphome/core/helpers.cpp fnv1_hash(const char*): classic FNV-1."""
    h = FNV1_32_OFFSET_BASIS
    for b in tag.encode("ascii"):
        h = (h * FNV1_32_PRIME) & 0xFFFFFFFF
        h ^= b
    return h


def tag_key_fnv1_32(tag: str) -> int:
    """ecco_durable::key_for(tag) == esphome::fnv1_hash(tag)."""
    return fnv1_32(tag)


# ---------------------------------------------------------------------------
# Register classification (V1)
# ---------------------------------------------------------------------------
REG_EXCLUDED, REG_E1, REG_CTX, REG_INFO = 0, 1, 2, 3
REGISTER_CLASS_NAMES = {REG_EXCLUDED: "EXCLUDED", REG_E1: "E1", REG_CTX: "CTX", REG_INFO: "INFO"}

# address -> (class, mask of the bits the class applies to / are compared).
# Anything not listed is EXCLUDED with mask 0, explicitly including 22-24,
# 246, 249 and 262-267.
REGISTER_TABLE: dict[int, tuple[int, int]] = {
    244: (REG_E1, 0xFFFF),
    **{a: (REG_E1, 0xFFFF) for a in range(256, 262)},
    **{a: (REG_E1, 0xFFFF) for a in range(268, 274)},
    **{a: (REG_E1, 0x0003) for a in range(274, 280)},
    232: (REG_CTX, 0x0001),
    243: (REG_CTX, 0xFFFF),
    248: (REG_CTX, 0x0001),
    **{a: (REG_CTX, 0xFFFF) for a in range(250, 256)},
    230: (REG_INFO, 0xFFFF),
    245: (REG_INFO, 0xFFFF),
    247: (REG_INFO, 0xFFFF),
}
EXPLICITLY_EXCLUDED = (22, 23, 24, 246, 249, *range(262, 268))


def register_class(addr: int) -> int:
    return REGISTER_TABLE.get(addr, (REG_EXCLUDED, 0))[0]


def register_class_mask(addr: int) -> int:
    return REGISTER_TABLE.get(addr, (REG_EXCLUDED, 0))[1]


def ctx_matches(addr: int, profile_value: int, live_value: int) -> bool:
    """A CTX register matches when the compared bits are equal (232 and 248:
    bit 0 only; 243 and 250-255: the full word)."""
    if register_class(addr) != REG_CTX:
        raise ValueError(f"register {addr} is not a CTX register")
    mask = register_class_mask(addr)
    return (profile_value & mask) == (live_value & mask)


# ---------------------------------------------------------------------------
# Domain rules (schema constants, never a runtime/site value)
# ---------------------------------------------------------------------------
REG244_PROFILE_REQUIRED = 2
V1_TOU_POWER_MIN_W = 500
V1_TOU_POWER_MAX_W = 8000
SOC_MAX = 100
SLOT_SOURCE_BITS_MASK = 0x0003
REG232_CTX_MASK = 0x0001
REG248_CTX_MASK = 0x0001


def firmware_tou_power_ceiling_w(firmware_path: Path = FIRMWARE_PATH) -> int:
    """The firmware's ${ecco_inverter_tou_power_ceiling_w} substitution.
    Used ONLY by tests to pin V1_TOU_POWER_MAX_W against it."""
    text = firmware_path.read_text(encoding="utf-8")
    m = re.search(r'^  ecco_inverter_tou_power_ceiling_w: "(\d+)"$', text, re.M)
    if not m:
        raise ValueError("ecco_inverter_tou_power_ceiling_w substitution not found")
    return int(m.group(1))


def reg244_domain_valid(v: int) -> bool:
    return v == REG244_PROFILE_REQUIRED


def tou_power_domain_valid(v: int) -> bool:
    return V1_TOU_POWER_MIN_W <= v <= V1_TOU_POWER_MAX_W


def soc_domain_valid(v: int) -> bool:
    return 0 <= v <= SOC_MAX


def slot_source_domain_valid(v: int) -> bool:
    return (v & ~SLOT_SOURCE_BITS_MASK & 0xFFFF) == 0 and (v & SLOT_SOURCE_BITS_MASK) <= 1


def from_244_domain_valid(v: int) -> bool:
    """A FROM snapshot of 244 (live before apply): 0 or 2. A live 1 blocks
    before any commit, so it can never be captured as FROM."""
    return v in (0, REG244_PROFILE_REQUIRED)


def reg244_write_permitted(live: int, target: int) -> bool:
    """The only register-244 write a future Fallback may ever issue: 0 -> 2."""
    return live == 0 and target == REG244_PROFILE_REQUIRED


# ---------------------------------------------------------------------------
# Shared load result (the LOCAL enum the pure classifiers take)
# ---------------------------------------------------------------------------
LOAD_OK, LOAD_ABSENT, LOAD_WRONG_SIZE, LOAD_READ_ERROR, LOAD_STORAGE_UNAVAILABLE = 0, 1, 2, 3, 4


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
_CTYPE = {"B": ctypes.c_uint8, "H": ctypes.c_uint16, "I": ctypes.c_uint32, "Q": ctypes.c_uint64}


def struct_for(layout, byte_order: str = "<") -> struct.Struct:
    return struct.Struct(byte_order + "".join(f"{n}{c}" if n > 1 else c for _f, c, n in layout))


def c_fields(layout):
    return [(f, _CTYPE[c] * n if n > 1 else _CTYPE[c]) for f, c, n in layout]


def offsets_of(layout) -> dict:
    out, off = {}, 0
    for f, c, n in layout:
        out[f] = off
        off += struct.calcsize(c) * n
    return out


def _flatten(record: dict, layout) -> list[int]:
    out: list[int] = []
    for f, _c, n in layout:
        v = record[f]
        if n > 1:
            if len(v) != n:
                raise ValueError(f"{f} needs {n} values, got {len(v)}")
            out.extend(int(x) for x in v)
        else:
            out.append(int(v))
    return out


def _unflatten(values, layout) -> dict:
    out, i = {}, 0
    for f, _c, n in layout:
        out[f] = list(values[i:i + n]) if n > 1 else values[i]
        i += n
    return out


def _copy(record: dict) -> dict:
    return {k: (list(v) if isinstance(v, list) else v) for k, v in record.items()}


# ---------------------------------------------------------------------------
# FallbackProfileV1
# ---------------------------------------------------------------------------
PROFILE_MAGIC = 0x45434650
PROFILE_SCHEMA = 1
PROFILE_SIZE = 96
PROFILE_BOUND_BYTES = 88
PROFILE_FLAG_INVALIDATED = 0x0001
PROFILE_KNOWN_FLAGS = PROFILE_FLAG_INVALIDATED
PROFILE_BINDING_DOMAIN = b"ECCO-FALLBACK-PROFILE-v1"
FALLBACK_PROFILE_TAG = "ecco_fallback_profile_v1"

PROFILE_LAYOUT = [
    ("magic", "I", 1), ("schema", "H", 1), ("size", "H", 1), ("generation", "I", 1),
    ("captured_epoch", "I", 1), ("flags", "H", 1), ("reg244", "H", 1),
    ("reg256_261", "H", 6), ("reg268_273", "H", 6), ("reg274_279", "H", 6),
    ("reg232", "H", 1), ("reg243", "H", 1), ("reg248", "H", 1), ("reg250_255", "H", 6),
    ("reg230", "H", 1), ("reg245", "H", 1), ("reg247", "H", 1),
    ("reserved0", "I", 1), ("reserved1", "I", 1), ("binding", "Q", 1),
]
PROFILE_OFFSETS = offsets_of(PROFILE_LAYOUT)
# Profile field -> register address(es) it records, in array order.
PROFILE_REGISTER_FIELDS = {
    "reg244": (244,), "reg256_261": tuple(range(256, 262)), "reg268_273": tuple(range(268, 274)),
    "reg274_279": tuple(range(274, 280)), "reg232": (232,), "reg243": (243,), "reg248": (248,),
    "reg250_255": tuple(range(250, 256)), "reg230": (230,), "reg245": (245,), "reg247": (247,),
}
# The captured payload: everything except generation, flags and binding
# (the only fields INVALIDATE may change).
PROFILE_INVALIDATE_MUTABLE_FIELDS = ("generation", "flags", "binding")


class FallbackProfileV1C(ctypes.Structure):
    """NATIVE C layout mirror (no packing) - proves 96 bytes and the offsets."""

    _fields_ = c_fields(PROFILE_LAYOUT)


def pack_profile(record: dict, byte_order: str = "<") -> bytes:
    return struct_for(PROFILE_LAYOUT, byte_order).pack(*_flatten(record, PROFILE_LAYOUT))


def unpack_profile(data: bytes) -> dict:
    if len(data) != PROFILE_SIZE:
        raise ValueError(f"FallbackProfileV1 is {PROFILE_SIZE} bytes, got {len(data)}")
    return _unflatten(struct_for(PROFILE_LAYOUT).unpack(data), PROFILE_LAYOUT)


def profile_binding(record_or_bytes) -> int:
    raw = record_or_bytes if isinstance(record_or_bytes, (bytes, bytearray)) else pack_profile(record_or_bytes)
    return fnv1a_64(PROFILE_BINDING_DOMAIN + bytes(raw[:PROFILE_BOUND_BYTES]))


def seal_profile(record: dict) -> dict:
    out = _copy(record)
    out["binding"] = profile_binding(out)
    return out


def blank_profile(**overrides) -> dict:
    rec = {f: ([0] * n if n > 1 else 0) for f, _c, n in PROFILE_LAYOUT}
    rec.update(overrides)
    return rec


(PROFILE_DEFECT_NONE, PROFILE_DEFECT_MAGIC, PROFILE_DEFECT_SCHEMA, PROFILE_DEFECT_SIZE, PROFILE_DEFECT_BINDING,
 PROFILE_DEFECT_RESERVED, PROFILE_DEFECT_FLAGS, PROFILE_DEFECT_GENERATION, PROFILE_DEFECT_DOMAIN) = range(9)
PROFILE_DEFECT_NAMES = {
    PROFILE_DEFECT_NONE: "NONE", PROFILE_DEFECT_MAGIC: "MAGIC", PROFILE_DEFECT_SCHEMA: "SCHEMA",
    PROFILE_DEFECT_SIZE: "SIZE", PROFILE_DEFECT_BINDING: "BINDING", PROFILE_DEFECT_RESERVED: "RESERVED",
    PROFILE_DEFECT_FLAGS: "FLAGS", PROFILE_DEFECT_GENERATION: "GENERATION", PROFILE_DEFECT_DOMAIN: "DOMAIN",
}

# 0 is UNREADABLE so a zero-initialised mirror is never VALID or NOT_CAPTURED.
(PROFILE_UNREADABLE, PROFILE_NOT_CAPTURED, PROFILE_CORRUPT, PROFILE_CORRUPT_DOMAIN,
 PROFILE_INVALIDATED, PROFILE_VALID) = range(6)
PROFILE_CLASS_NAMES = {
    PROFILE_UNREADABLE: "UNREADABLE", PROFILE_NOT_CAPTURED: "NOT_CAPTURED", PROFILE_CORRUPT: "CORRUPT",
    PROFILE_CORRUPT_DOMAIN: "CORRUPT_DOMAIN", PROFILE_INVALIDATED: "INVALIDATED", PROFILE_VALID: "VALID",
}


def profile_domain_valid(p: dict) -> bool:
    return (reg244_domain_valid(p["reg244"])
            and all(tou_power_domain_valid(v) for v in p["reg256_261"])
            and all(soc_domain_valid(v) for v in p["reg268_273"])
            and all(slot_source_domain_valid(v) for v in p["reg274_279"]))


def profile_domain_defects(p: dict) -> list[str]:
    """Diagnostic detail only: which E1 registers are out of domain."""
    bad = [] if reg244_domain_valid(p["reg244"]) else ["reg244"]
    bad += [f"reg{a}" for a, v in zip(range(256, 262), p["reg256_261"]) if not tou_power_domain_valid(v)]
    bad += [f"reg{a}" for a, v in zip(range(268, 274), p["reg268_273"]) if not soc_domain_valid(v)]
    bad += [f"reg{a}" for a, v in zip(range(274, 280), p["reg274_279"]) if not slot_source_domain_valid(v)]
    return bad


def profile_defect(p: dict) -> int:
    """Mirror of ecco_fallback::profile_defect(): the FIRST failing rule, in
    the V1 precedence order."""
    if p["magic"] != PROFILE_MAGIC:
        return PROFILE_DEFECT_MAGIC
    if p["schema"] != PROFILE_SCHEMA:
        return PROFILE_DEFECT_SCHEMA
    if p["size"] != PROFILE_SIZE:
        return PROFILE_DEFECT_SIZE
    if p["binding"] != profile_binding(p):
        return PROFILE_DEFECT_BINDING
    if p["reserved0"] != 0 or p["reserved1"] != 0:
        return PROFILE_DEFECT_RESERVED
    if p["flags"] & ~PROFILE_KNOWN_FLAGS & 0xFFFF:
        return PROFILE_DEFECT_FLAGS
    if p["generation"] == 0:
        return PROFILE_DEFECT_GENERATION
    if not profile_domain_valid(p):
        return PROFILE_DEFECT_DOMAIN
    return PROFILE_DEFECT_NONE


def _as_profile(record) -> dict:
    return unpack_profile(bytes(record)) if isinstance(record, (bytes, bytearray)) else record


def classify_profile(load_result: int, record) -> int:
    """Mirror of ecco_fallback::classify_profile(). `record` (dict or 96
    raw bytes) is not inspected unless load_result is LOAD_OK."""
    if load_result == LOAD_ABSENT:
        return PROFILE_NOT_CAPTURED
    if load_result == LOAD_WRONG_SIZE:
        return PROFILE_CORRUPT
    if load_result != LOAD_OK:
        return PROFILE_UNREADABLE
    p = _as_profile(record)
    d = profile_defect(p)
    if d == PROFILE_DEFECT_DOMAIN:
        return PROFILE_CORRUPT_DOMAIN
    if d != PROFILE_DEFECT_NONE:
        return PROFILE_CORRUPT
    if p["flags"] & PROFILE_FLAG_INVALIDATED:
        return PROFILE_INVALIDATED
    return PROFILE_VALID


def profile_generation_advances(previous: int, nxt: int) -> bool:
    """Every durable profile commit (CAPTURE or INVALIDATE) strictly
    increases the generation. The generation is one logical counter shared
    across schema versions: a future V2 continues from the highest V1."""
    return nxt > previous


def profile_invalidate_permitted(p: dict) -> bool:
    """Only a VALID profile may be invalidated (INVALIDATED is one-way for a
    record generation) and its generation must still be able to advance."""
    return classify_profile(LOAD_OK, p) == PROFILE_VALID and p["generation"] < 0xFFFFFFFF


def invalidate_profile(p: dict) -> dict:
    """INVALIDATE: generation + 1, INVALIDATED set, re-bound. The captured
    payload is preserved verbatim - nothing else changes."""
    if not profile_invalidate_permitted(p):
        raise ValueError("INVALIDATE not permitted for this record")
    out = _copy(p)
    out["generation"] = p["generation"] + 1
    out["flags"] = p["flags"] | PROFILE_FLAG_INVALIDATED
    return seal_profile(out)


# ---------------------------------------------------------------------------
# FailbackStateV1
# ---------------------------------------------------------------------------
FAILBACK_MAGIC = 0x45434642
FAILBACK_SCHEMA = 1
FAILBACK_SIZE = 80
FAILBACK_BOUND_BYTES = 72
FAILBACK_BINDING_DOMAIN = b"ECCO-FAILBACK-STATE-v1"
FAILBACK_STATE_TAG = "ecco_failback_state_v1"
# Documented as optional (architecture section 8.1 / 4.3, PR B); not declared
# by FB-A, but included in the key-collision check so it stays usable.
PROSPECTIVE_TAGS = ("ecco_failback_provision_v1",)

FAILBACK_CLEAR = 0
FAILBACK_PREEMPT_REQUIRED = 1
FAILBACK_APPLY_IN_PROGRESS = 2
FAILBACK_LATCHED_COMPLETE = 3
FAILBACK_BLOCKED = 4
FAILBACK_STATE_NAMES = {0: "CLEAR", 1: "PREEMPT_REQUIRED", 2: "APPLY_IN_PROGRESS", 3: "LATCHED_COMPLETE", 4: "BLOCKED"}

FAILBACK_REASON_NONE = 0
FAILBACK_REASON_SUPERVISION_LOST = 1
FAILBACK_REASON_OPERATOR_APPLY = 2
FAILBACK_REASON_NAMES = {0: "NONE", 1: "SUPERVISION_LOST", 2: "OPERATOR_APPLY"}

FAILBACK_RESULT_NAMES = {
    0: "NONE",
    1: "PREEMPTED_ONLY", 2: "PREEMPTED_NO_PROFILE", 3: "ALREADY_AT_PROFILE", 4: "APPLIED_VERIFIED",
    5: "BLOCKED_LEASE_RESTORE_LOCKED", 6: "BLOCKED_MARKER_DIVERGENCE", 7: "BLOCKED_PROFILE_UNAVAILABLE",
    8: "BLOCKED_CONTEXT_MISMATCH", 9: "BLOCKED_LIVE_OUT_OF_DOMAIN", 10: "BLOCKED_SITE_CEILING",
    11: "BLOCKED_APPLY_FAILED",
}
FAILBACK_RESULT_NONE = 0
FAILBACK_RESULT_APPLIED_VERIFIED = 4
LATCHED_RESULTS = (1, 2, 3, 4)
BLOCKED_RESULTS = tuple(range(5, 12))

FAILBACK_FLAG_LEASE_PREEMPTED = 0x01
FAILBACK_FLAG_APPLY_COMMITTED = 0x02
FAILBACK_FLAG_DIVERGENCE_REBOOT_USED = 0x04
FAILBACK_KNOWN_FLAGS = 0x07

FAILBACK_LAYOUT = [
    ("magic", "I", 1), ("schema", "H", 1), ("size", "H", 1), ("state", "B", 1), ("reason", "B", 1),
    ("result", "B", 1), ("flags", "B", 1), ("event_seq", "I", 1), ("event_epoch", "I", 1),
    ("profile_generation", "I", 1), ("apply_attempts", "B", 1), ("verify_mismatches", "B", 1),
    ("from_244", "H", 1), ("from_256_261", "H", 6), ("from_268_279", "H", 12),
    ("profile_binding", "Q", 1), ("binding", "Q", 1),
]
FAILBACK_OFFSETS = offsets_of(FAILBACK_LAYOUT)
FAILBACK_FROM_FIELDS = ("from_244", "from_256_261", "from_268_279")


class FailbackStateV1C(ctypes.Structure):
    _fields_ = c_fields(FAILBACK_LAYOUT)


def pack_failback(record: dict, byte_order: str = "<") -> bytes:
    return struct_for(FAILBACK_LAYOUT, byte_order).pack(*_flatten(record, FAILBACK_LAYOUT))


def unpack_failback(data: bytes) -> dict:
    if len(data) != FAILBACK_SIZE:
        raise ValueError(f"FailbackStateV1 is {FAILBACK_SIZE} bytes, got {len(data)}")
    return _unflatten(struct_for(FAILBACK_LAYOUT).unpack(data), FAILBACK_LAYOUT)


def failback_binding(record_or_bytes) -> int:
    raw = record_or_bytes if isinstance(record_or_bytes, (bytes, bytearray)) else pack_failback(record_or_bytes)
    return fnv1a_64(FAILBACK_BINDING_DOMAIN + bytes(raw[:FAILBACK_BOUND_BYTES]))


def seal_failback(record: dict) -> dict:
    out = _copy(record)
    out["binding"] = failback_binding(out)
    return out


def blank_failback(**overrides) -> dict:
    rec = {f: ([0] * n if n > 1 else 0) for f, _c, n in FAILBACK_LAYOUT}
    rec.update(overrides)
    return rec


def failback_clear_record(event_seq: int) -> dict:
    """The ONE canonical CLEAR record: event_seq is preserved (it is the
    monotonic episode counter operator actions bind to); every other episode
    field - reason, result, flags, epoch, profile binding/generation, counters
    and FROM - is zero. The last episode's outcome is not retained."""
    return seal_failback(blank_failback(magic=FAILBACK_MAGIC, schema=FAILBACK_SCHEMA, size=FAILBACK_SIZE,
                                        state=FAILBACK_CLEAR, event_seq=event_seq))


def failback_from_all_zero(s: dict) -> bool:
    return s["from_244"] == 0 and not any(s["from_256_261"]) and not any(s["from_268_279"])


def failback_from_domain_valid(s: dict) -> bool:
    return (from_244_domain_valid(s["from_244"])
            and all(tou_power_domain_valid(v) for v in s["from_256_261"])
            and all(soc_domain_valid(v) for v in s["from_268_279"][:6])
            and all(slot_source_domain_valid(v) for v in s["from_268_279"][6:]))


def failback_invariant_defects(s: dict) -> list[str]:
    """Every cross-field rule that fails (diagnostic detail; the header only
    reports FAILBACK_DEFECT_INVARIANT)."""
    bad = []
    committed = bool(s["flags"] & FAILBACK_FLAG_APPLY_COMMITTED)
    st = s["state"]
    if (s["profile_generation"] == 0) != (s["profile_binding"] == 0):
        bad.append("profile_generation==0 iff profile_binding==0")
    if failback_from_all_zero(s) == committed:
        bad.append("all from_* zero iff apply_committed clear")
    if committed and not failback_from_domain_valid(s):
        bad.append("from_* domain")
    if committed and s["profile_generation"] == 0:
        bad.append("apply_committed requires a bound profile")
    if not committed and (s["apply_attempts"] or s["verify_mismatches"]):
        bad.append("apply counters require apply_committed")
    if st == FAILBACK_CLEAR:
        if (s["reason"], s["result"], s["flags"], s["event_epoch"], s["profile_generation"], s["apply_attempts"],
                s["verify_mismatches"], s["profile_binding"]) != (0,) * 8 or not failback_from_all_zero(s):
            bad.append("CLEAR carries only event_seq")
    else:
        if s["reason"] == FAILBACK_REASON_NONE:
            bad.append("non-CLEAR needs a reason")
        if s["event_seq"] == 0:
            bad.append("non-CLEAR needs event_seq >= 1")
    if st == FAILBACK_PREEMPT_REQUIRED and (committed or s["result"] != FAILBACK_RESULT_NONE):
        bad.append("PREEMPT_REQUIRED: no apply commit, no result")
    if st == FAILBACK_APPLY_IN_PROGRESS and (not committed or s["result"] != FAILBACK_RESULT_NONE):
        bad.append("APPLY_IN_PROGRESS: apply_committed set, no result")
    if st == FAILBACK_LATCHED_COMPLETE and (s["result"] not in LATCHED_RESULTS
                                           or committed != (s["result"] == FAILBACK_RESULT_APPLIED_VERIFIED)):
        bad.append("LATCHED_COMPLETE: latched result; apply_committed iff APPLIED_VERIFIED")
    if st == FAILBACK_BLOCKED and s["result"] not in BLOCKED_RESULTS:
        bad.append("BLOCKED: blocked result")
    return bad


(FAILBACK_DEFECT_NONE, FAILBACK_DEFECT_MAGIC, FAILBACK_DEFECT_SCHEMA, FAILBACK_DEFECT_SIZE, FAILBACK_DEFECT_BINDING,
 FAILBACK_DEFECT_FLAGS, FAILBACK_DEFECT_STATE, FAILBACK_DEFECT_REASON, FAILBACK_DEFECT_RESULT,
 FAILBACK_DEFECT_INVARIANT) = range(10)


def failback_defect(s: dict) -> int:
    if s["magic"] != FAILBACK_MAGIC:
        return FAILBACK_DEFECT_MAGIC
    if s["schema"] != FAILBACK_SCHEMA:
        return FAILBACK_DEFECT_SCHEMA
    if s["size"] != FAILBACK_SIZE:
        return FAILBACK_DEFECT_SIZE
    if s["binding"] != failback_binding(s):
        return FAILBACK_DEFECT_BINDING
    if s["flags"] & ~FAILBACK_KNOWN_FLAGS & 0xFF:
        return FAILBACK_DEFECT_FLAGS
    if s["state"] > FAILBACK_BLOCKED:
        return FAILBACK_DEFECT_STATE
    if s["reason"] not in FAILBACK_REASON_NAMES:
        return FAILBACK_DEFECT_REASON
    if s["result"] not in FAILBACK_RESULT_NAMES:
        return FAILBACK_DEFECT_RESULT
    if failback_invariant_defects(s):
        return FAILBACK_DEFECT_INVARIANT
    return FAILBACK_DEFECT_NONE


FAILBACK_RECORD_UNREADABLE, FAILBACK_RECORD_ABSENT, FAILBACK_RECORD_CORRUPT, FAILBACK_RECORD_VALID = 0, 1, 2, 3
FAILBACK_RECORD_NAMES = {0: "UNREADABLE", 1: "ABSENT", 2: "CORRUPT", 3: "VALID"}


def _as_failback(record) -> dict:
    return unpack_failback(bytes(record)) if isinstance(record, (bytes, bytearray)) else record


def classify_failback(load_result: int, record) -> int:
    """Mirror of ecco_fallback::classify_failback(). ABSENT is distinct from
    a present CLEAR record; bytes are not inspected unless load is OK."""
    if load_result == LOAD_ABSENT:
        return FAILBACK_RECORD_ABSENT
    if load_result == LOAD_WRONG_SIZE:
        return FAILBACK_RECORD_CORRUPT
    if load_result != LOAD_OK:
        return FAILBACK_RECORD_UNREADABLE
    return FAILBACK_RECORD_VALID if failback_defect(_as_failback(record)) == FAILBACK_DEFECT_NONE \
        else FAILBACK_RECORD_CORRUPT


def failback_from_capture_permitted(s: dict) -> bool:
    """FROM may be captured only while apply_committed is clear: once the
    write-ahead commit stored FROM for this event, no retry may recapture or
    rewrite it (it is cleared only by the terminal transition to CLEAR)."""
    return not s["flags"] & FAILBACK_FLAG_APPLY_COMMITTED


# ---------------------------------------------------------------------------
# Whole-table digests (mirrors of the header's compile-time digests)
# ---------------------------------------------------------------------------
REGISTER_TABLE_DIGEST_DOMAIN = b"ECCO-FALLBACK-REGISTER-CLASS-v1"
DOMAIN_DIGEST_DOMAIN = b"ECCO-FALLBACK-DOMAIN-v1"


def register_class_digest(table=None) -> int:
    """FNV-1a-64 over (class, mask lo, mask hi) for every u16 address."""
    table = REGISTER_TABLE if table is None else table
    h = fnv1a_64(REGISTER_TABLE_DIGEST_DOMAIN)
    for addr in range(0x10000):
        cls, mask = table.get(addr, (REG_EXCLUDED, 0))
        h = fnv1a_64(bytes((cls, mask & 0xFF, mask >> 8)), h)
    return h


def domain_digest(predicate) -> int:
    """FNV-1a-64 over one validity byte (0/1) per u16 value 0..0xFFFF."""
    h = fnv1a_64(DOMAIN_DIGEST_DOMAIN)
    for v in range(0x10000):
        h = ((h ^ (1 if predicate(v) else 0)) * FNV1A64_PRIME) & _U64
    return h
