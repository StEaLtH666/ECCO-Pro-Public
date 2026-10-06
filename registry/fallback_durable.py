"""Python mirror of the FB-B0 Fallback durable model (C++-exact).

firmware/include/ecco_fallback_durable_model.h is the C++ side. FB-B0 is
BEHAVIOUR-FREE: the headers are compiled into the firmware (esphome:
includes) but nothing calls them yet. This module is the independent mirror
the offline suites hold the header to:
  - registry/tests/test_fallback_durable_model.py parses the header's
    compile-time golden vectors and golden-case tables and re-derives every
    value from here;
  - registry/tests/test_fallback_durable_host_compile.py runs the REAL C++
    templates against a fault-injecting fake NVS and requires byte-for-byte
    agreement with this module on every scenario;
  - registry/tests/_fbb_harness.py drives these functions against its direct
    NVS model when simulating firmware.

FailbackProvisionV1 (FBW) - 48 bytes, natural C layout, no implicit padding:

    offset  0  u32  magic             PROVISION_MAGIC (0x45434657, 'ECFW')
    offset  4  u16  schema            1
    offset  6  u16  size              48
    offset  8  u32  hw_generation     high-water generation (>= 1)
    offset 12  u32  prior_generation  authentic generation when that transition began; 0 = none
    offset 16  u64  hw_binding        binding of the record written at hw_generation
    offset 24  u64  prior_binding     binding of the prior record; 0 iff prior_generation == 0
    offset 32  u32  hw_tag_key        preference key of the hw record (0x5FEE6196 for V1)
    offset 36  u16  hw_record_schema  1
    offset 38  u8   last_op           1 SAVE, 2 INVALIDATE, 3 REPLACE_CORRUPT
    offset 39  u8   flags             MUST be 0
    offset 40  u64  binding           FNV-1a-64(b"ECCO-FAILBACK-PROVISION-v1" + bytes[0:40])

Semantics that deliberately follow the C++ and NOT the FB-A Python mirror:
invalidate_profile_cxx() is the C++ ecco_fallback::invalidate_profile(),
which does not re-check permission (it wraps the generation at 2^32 and
re-seals anything); callers gate it with profile_invalidate_permitted(),
exactly like the firmware must (V8).

The NVS policy protocol (the C++ policy, in Python shape):
    handle() -> int                         0 = storage unavailable
    set_blob(key, data: bytes) -> int       esp_err_t
    get_blob(key, capacity) -> (err, length, data)
                                            capacity None = size probe
    get_stats() -> int                      IDF_OK iff no INVALID page
    now_us() -> int

Pure: stdlib only, no I/O of its own.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_profile as fp  # noqa: E402

LOAD_OK, LOAD_ABSENT, LOAD_WRONG_SIZE, LOAD_READ_ERROR, LOAD_STORAGE_UNAVAILABLE = (
    fp.LOAD_OK, fp.LOAD_ABSENT, fp.LOAD_WRONG_SIZE, fp.LOAD_READ_ERROR, fp.LOAD_STORAGE_UNAVAILABLE)

# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
FAILBACK_PROVISION_TAG = "ecco_failback_provision_v1"
FALLBACK_PROFILE_KEY = 0x5FEE6196
FAILBACK_PROVISION_KEY = 0x3BA3DF61
FAILBACK_STATE_KEY = 0x808485C3


def decimal_key(key: int) -> str:
    """ESPHome uint32_to_str(): base 10, no sign, no leading zeros."""
    if not 0 <= key <= 0xFFFFFFFF:
        raise ValueError("preference keys are 32-bit")
    return str(key)


# ---------------------------------------------------------------------------
# ESP-IDF error codes (esp_err.h / nvs.h, IDF 5.5.5). The model header
# mirrors only the five it classifies; the rest are used by the fault
# harness to exercise the OTHER class.
# ---------------------------------------------------------------------------
IDF_OK = 0
IDF_FAIL = -1
IDF_ERR_NO_MEM = 0x101
IDF_ERR_INVALID_ARG = 0x102
IDF_ERR_INVALID_STATE = 0x103
IDF_ERR_INVALID_SIZE = 0x104
IDF_ERR_TIMEOUT = 0x107
IDF_ERR_FLASH_BASE = 0x6000
IDF_ERR_FLASH_OP_FAIL = 0x6001
IDF_ERR_FLASH_OP_TIMEOUT = 0x6002
IDF_ERR_FLASH_PROTECTED = 0x6003
IDF_ERR_NVS_BASE = 0x1100
IDF_ERR_NVS_NOT_INITIALIZED = 0x1101
IDF_ERR_NVS_NOT_FOUND = 0x1102
IDF_ERR_NVS_TYPE_MISMATCH = 0x1103
IDF_ERR_NVS_READ_ONLY = 0x1104
IDF_ERR_NVS_NOT_ENOUGH_SPACE = 0x1105
IDF_ERR_NVS_INVALID_NAME = 0x1106
IDF_ERR_NVS_INVALID_HANDLE = 0x1107
IDF_ERR_NVS_REMOVE_FAILED = 0x1108
IDF_ERR_NVS_KEY_TOO_LONG = 0x1109
IDF_ERR_NVS_PAGE_FULL = 0x110A
IDF_ERR_NVS_INVALID_STATE = 0x110B
IDF_ERR_NVS_INVALID_LENGTH = 0x110C
IDF_ERR_NVS_NO_FREE_PAGES = 0x110D
IDF_ERR_NVS_VALUE_TOO_LONG = 0x110E
IDF_ERR_NVS_PART_NOT_FOUND = 0x110F
IDF_ERR_NVS_NEW_VERSION_FOUND = 0x1110
IDF_ERR_NVS_CONTENT_DIFFERS = 0x1118
PRE_WRITE_CODES = (IDF_ERR_NVS_INVALID_HANDLE, IDF_ERR_NVS_READ_ONLY, IDF_ERR_NVS_NOT_INITIALIZED)

# ---------------------------------------------------------------------------
# Outcome enums (0 is always the fail-closed value)
# ---------------------------------------------------------------------------
WERR_OTHER, WERR_OK, WERR_PRE_WRITE = 0, 1, 2
(RB_NOT_READ, RB_INTENDED, RB_PRIOR, RB_OTHER_BYTES, RB_ABSENT_UNEXPECTED, RB_WRONG_SIZE, RB_READ_ERROR,
 RB_UNAVAILABLE) = range(8)
KEY_UNKNOWN_REBOOT, KEY_COMMITTED, KEY_NOT_COMMITTED, KEY_NOT_ATTEMPTED = 0, 1, 2, 3
TXN_UNKNOWN_REBOOT, TXN_COMMITTED, TXN_NOT_COMMITTED, TXN_REFUSED_LATCHED = 0, 1, 2, 3
(REFUSAL_UNSET, REFUSAL_NONE, REFUSAL_LATCHED, REFUSAL_INVALID_TRANSITION, REFUSAL_STORAGE_UNAVAILABLE,
 REFUSAL_STORAGE_UNHEALTHY) = range(6)

WERR_NAMES = {0: "OTHER", 1: "OK", 2: "PRE_WRITE"}
RB_NAMES = {0: "NOT_READ", 1: "INTENDED", 2: "PRIOR", 3: "OTHER_BYTES", 4: "ABSENT_UNEXPECTED", 5: "WRONG_SIZE",
            6: "READ_ERROR", 7: "UNAVAILABLE"}
KEY_NAMES = {0: "UNKNOWN_REBOOT", 1: "COMMITTED", 2: "NOT_COMMITTED", 3: "NOT_ATTEMPTED"}
TXN_NAMES = {0: "UNKNOWN_REBOOT", 1: "COMMITTED", 2: "NOT_COMMITTED", 3: "REFUSED_LATCHED"}
REFUSAL_NAMES = {0: "UNSET", 1: "NONE", 2: "LATCHED", 3: "INVALID_TRANSITION", 4: "STORAGE_UNAVAILABLE",
                 5: "STORAGE_UNHEALTHY"}


def classify_write_err(e: int) -> int:
    if e == IDF_OK:
        return WERR_OK
    if e in PRE_WRITE_CODES:
        return WERR_PRE_WRITE
    return WERR_OTHER


def readback_class(rb_load: int, rb_len: int, rb_eq_intended: bool, prior_load: int, prior_len: int,
                   rb_eq_prior_bytes: bool) -> int:
    if rb_load == LOAD_OK:
        if rb_eq_intended:
            return RB_INTENDED
        return RB_PRIOR if (prior_load == LOAD_OK and rb_eq_prior_bytes) else RB_OTHER_BYTES
    if rb_load == LOAD_ABSENT:
        return RB_PRIOR if prior_load == LOAD_ABSENT else RB_ABSENT_UNEXPECTED
    if rb_load == LOAD_WRONG_SIZE:
        return RB_PRIOR if (prior_load == LOAD_WRONG_SIZE and prior_len == rb_len) else RB_WRONG_SIZE
    if rb_load == LOAD_STORAGE_UNAVAILABLE:
        return RB_UNAVAILABLE
    return RB_READ_ERROR


def classify_key_outcome(e: int, r: int, healthy_after: bool) -> int:
    if not healthy_after:
        return KEY_UNKNOWN_REBOOT
    if e == WERR_OK and r == RB_INTENDED:
        return KEY_COMMITTED
    if e == WERR_PRE_WRITE and r == RB_PRIOR:
        return KEY_NOT_COMMITTED
    return KEY_UNKNOWN_REBOOT


# ---------------------------------------------------------------------------
# FailbackProvisionV1
# ---------------------------------------------------------------------------
PROVISION_MAGIC = 0x45434657
PROVISION_SCHEMA = 1
PROVISION_SIZE = 48
PROVISION_BOUND_BYTES = 40
PROVISION_BINDING_DOMAIN = b"ECCO-FAILBACK-PROVISION-v1"
PROV_OP_INVALID, PROV_OP_SAVE, PROV_OP_INVALIDATE, PROV_OP_REPLACE_CORRUPT = 0, 1, 2, 3
PROV_OP_NAMES = {1: "SAVE", 2: "INVALIDATE", 3: "REPLACE_CORRUPT"}

PROVISION_LAYOUT = [
    ("magic", "I", 1), ("schema", "H", 1), ("size", "H", 1), ("hw_generation", "I", 1), ("prior_generation", "I", 1),
    ("hw_binding", "Q", 1), ("prior_binding", "Q", 1), ("hw_tag_key", "I", 1), ("hw_record_schema", "H", 1),
    ("last_op", "B", 1), ("flags", "B", 1), ("binding", "Q", 1),
]
PROVISION_OFFSETS = fp.offsets_of(PROVISION_LAYOUT)
_PROVISION_STRUCT = fp.struct_for(PROVISION_LAYOUT)
assert _PROVISION_STRUCT.size == PROVISION_SIZE


def blank_provision(**overrides) -> dict:
    rec = {f: 0 for f, _c, _n in PROVISION_LAYOUT}
    rec.update(overrides)
    return rec


def pack_provision(w: dict) -> bytes:
    return _PROVISION_STRUCT.pack(*(int(w[f]) for f, _c, _n in PROVISION_LAYOUT))


def unpack_provision(data: bytes) -> dict:
    if len(data) != PROVISION_SIZE:
        raise ValueError(f"FailbackProvisionV1 is {PROVISION_SIZE} bytes, got {len(data)}")
    return dict(zip((f for f, _c, _n in PROVISION_LAYOUT), _PROVISION_STRUCT.unpack(bytes(data))))


def provision_binding(record_or_bytes) -> int:
    raw = record_or_bytes if isinstance(record_or_bytes, (bytes, bytearray)) else pack_provision(record_or_bytes)
    return fp.fnv1a_64(PROVISION_BINDING_DOMAIN + bytes(raw[:PROVISION_BOUND_BYTES]))


def seal_provision(w: dict) -> dict:
    out = dict(w)
    out["binding"] = provision_binding(out)
    return out


def make_provision(hw_generation: int, hw_binding: int, prior_generation: int, prior_binding: int,
                   hw_tag_key: int, hw_record_schema: int, last_op: int) -> dict:
    return seal_provision(blank_provision(
        magic=PROVISION_MAGIC, schema=PROVISION_SCHEMA, size=PROVISION_SIZE, hw_generation=hw_generation,
        prior_generation=prior_generation, hw_binding=hw_binding, prior_binding=prior_binding, hw_tag_key=hw_tag_key,
        hw_record_schema=hw_record_schema, last_op=last_op, flags=0))


(WIT_DEFECT_NONE, WIT_DEFECT_MAGIC, WIT_DEFECT_SCHEMA, WIT_DEFECT_SIZE, WIT_DEFECT_BINDING, WIT_DEFECT_FLAGS,
 WIT_DEFECT_HW, WIT_DEFECT_PRIOR, WIT_DEFECT_OP, WIT_DEFECT_TAG, WIT_DEFECT_RECSCHEMA) = range(11)
W_UNREADABLE, W_ABSENT, W_CORRUPT, W_VALID = 0, 1, 2, 3
WITNESS_CLASS_NAMES = {0: "UNR", 1: "ABS", 2: "CORR", 3: "OK"}


def _as_provision(record) -> dict:
    return unpack_provision(bytes(record)) if isinstance(record, (bytes, bytearray)) else record


def witness_defect(w) -> int:
    w = _as_provision(w)
    if w["magic"] != PROVISION_MAGIC:
        return WIT_DEFECT_MAGIC
    if w["schema"] != PROVISION_SCHEMA:
        return WIT_DEFECT_SCHEMA
    if w["size"] != PROVISION_SIZE:
        return WIT_DEFECT_SIZE
    if w["binding"] != provision_binding(w):
        return WIT_DEFECT_BINDING
    if w["flags"] != 0:
        return WIT_DEFECT_FLAGS
    if w["hw_generation"] == 0:
        return WIT_DEFECT_HW
    if w["prior_generation"] >= w["hw_generation"] or (w["prior_generation"] == 0) != (w["prior_binding"] == 0):
        return WIT_DEFECT_PRIOR
    if w["last_op"] not in (PROV_OP_SAVE, PROV_OP_INVALIDATE, PROV_OP_REPLACE_CORRUPT):
        return WIT_DEFECT_OP
    if w["hw_tag_key"] == 0:
        return WIT_DEFECT_TAG
    if w["hw_record_schema"] == 0:
        return WIT_DEFECT_RECSCHEMA
    return WIT_DEFECT_NONE


def classify_witness(load: int, w) -> int:
    if load == LOAD_ABSENT:
        return W_ABSENT
    if load == LOAD_WRONG_SIZE:
        return W_CORRUPT
    if load != LOAD_OK:
        return W_UNREADABLE
    return W_VALID if witness_defect(w) == WIT_DEFECT_NONE else W_CORRUPT


# ---------------------------------------------------------------------------
# Effective profile class
# ---------------------------------------------------------------------------
(EPC_UNREADABLE, EPC_NOT_CAPTURED, EPC_CORRUPT, EPC_CORRUPT_DOMAIN, EPC_INVALIDATED, EPC_VALID, EPC_PROFILE_LOST,
 EPC_SAVE_UNCONFIRMED, EPC_PROFILE_STALE) = range(9)
EPC_NAMES = {0: "UNREADABLE", 1: "NOT_CAPTURED", 2: "CORRUPT", 3: "CORRUPT_DOMAIN", 4: "INVALIDATED", 5: "VALID",
             6: "PROFILE_LOST", 7: "SAVE_UNCONFIRMED", 8: "PROFILE_STALE"}
(WHY_NONE, WHY_INTERRUPTED, WHY_ROLLBACK, WHY_MISMATCH, WHY_SUPERSEDED, WHY_WIT_LAGGING, WHY_WIT_MISSING,
 WHY_WIT_CORRUPT, WHY_PROFILE_READ, WHY_WITNESS_READ, WHY_READ_ANOMALY, WHY_FIRST_SAVE_UNCONFIRMED,
 WHY_LOST_WIT_CORRUPT) = range(13)
WHY_NAMES = {0: "-", 1: "INT", 2: "RBK", 3: "MIS", 4: "SUP", 5: "LAG", 6: "MISS", 7: "CORR", 8: "PRD", 9: "WRD",
             10: "ANOM", 11: "FIRST", 12: "LWC"}
RULE_NONE, RULE_B2A = 0, 16  # RULE_B1..RULE_B15 are 1..15


def fba_authentic(fba_cls: int) -> bool:
    return fba_cls in (fp.PROFILE_VALID, fp.PROFILE_INVALIDATED, fp.PROFILE_CORRUPT_DOMAIN)


def compose_profile_class(p_load: int, p, w_load: int, w, anomaly_bits: int) -> tuple[int, int, int]:
    """Mirror of ecco_fbdurable::compose_profile_class(): (cls, why, rule)."""
    c = fp.classify_profile(p_load, p)
    wc = classify_witness(w_load, w)
    if c == fp.PROFILE_UNREADABLE:
        return EPC_UNREADABLE, WHY_PROFILE_READ, 1
    if wc == W_UNREADABLE:
        return EPC_UNREADABLE, WHY_WITNESS_READ, 2
    if anomaly_bits != 0:
        return EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A
    if c == fp.PROFILE_CORRUPT:
        return EPC_CORRUPT, WHY_NONE, 3
    wr = _as_provision(w) if w_load == LOAD_OK else None
    if c == fp.PROFILE_NOT_CAPTURED:
        if wc == W_ABSENT:
            return EPC_NOT_CAPTURED, WHY_NONE, 4
        if wc == W_VALID and wr["prior_generation"] == 0 and wr["last_op"] == PROV_OP_SAVE and wr["hw_generation"] == 1:
            return EPC_PROFILE_LOST, WHY_FIRST_SAVE_UNCONFIRMED, 5
        if wc == W_VALID:
            return EPC_PROFILE_LOST, WHY_NONE, 6
        return EPC_PROFILE_LOST, WHY_LOST_WIT_CORRUPT, 7
    pr = fp._as_profile(p)
    g, b = pr["generation"], pr["binding"]
    if wc == W_VALID:
        if g > wr["hw_generation"]:
            return c, WHY_WIT_LAGGING, 8
        if wr["hw_tag_key"] != FALLBACK_PROFILE_KEY or wr["hw_record_schema"] != fp.PROFILE_SCHEMA:
            return EPC_PROFILE_STALE, WHY_SUPERSEDED, 9
        if g == wr["hw_generation"] and b == wr["hw_binding"]:
            return c, WHY_NONE, 10
        if g == wr["hw_generation"]:
            return EPC_PROFILE_STALE, WHY_MISMATCH, 11
        if g == wr["prior_generation"] and b == wr["prior_binding"]:
            return EPC_PROFILE_STALE, WHY_INTERRUPTED, 12
        return EPC_PROFILE_STALE, WHY_ROLLBACK, 13
    if wc == W_ABSENT:
        return c, WHY_WIT_MISSING, 14
    return c, WHY_WIT_CORRUPT, 15


def profile_writer_usable(cls: int, why: int) -> bool:
    return cls == EPC_VALID and why == WHY_NONE


def save_class_permitted(cls: int) -> bool:
    return cls in (EPC_NOT_CAPTURED, EPC_CORRUPT, EPC_CORRUPT_DOMAIN, EPC_INVALIDATED, EPC_VALID, EPC_PROFILE_LOST,
                   EPC_PROFILE_STALE)


def save_requires_replace_phrase(cls: int) -> bool:
    return cls == EPC_CORRUPT


def invalidate_class_permitted(cls: int) -> bool:
    return cls == EPC_VALID


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
GENERATION_MAX = 0xFFFFFFFF


def save_generation_base(fba_cls: int, g: int, wc: int, hw: int, seen_hw_gen: int) -> int:
    return max(g if fba_authentic(fba_cls) else 0, hw if wc == W_VALID else 0, seen_hw_gen)


def save_generation_available(base: int) -> bool:
    return base != GENERATION_MAX


def invalidate_generation_permitted(g: int, wc: int, hw: int, seen_hw_gen: int) -> bool:
    return g < GENERATION_MAX and g + 1 > (hw if wc == W_VALID else 0) and g + 1 > seen_hw_gen


def next_seen_hw_gen(seen_hw_gen: int, fba_cls: int, g: int, wc: int, hw: int) -> int:
    return max(seen_hw_gen, g if fba_authentic(fba_cls) else 0, hw if wc == W_VALID else 0)


def invalidate_profile_cxx(p: dict) -> dict:
    """C++ ecco_fallback::invalidate_profile(): UNCONDITIONAL - no
    permission check, the u32 generation wraps, the result is re-sealed.
    Callers must gate it with fp.profile_invalidate_permitted()."""
    out = fp._copy(p)
    out["generation"] = (p["generation"] + 1) & 0xFFFFFFFF
    out["flags"] = (p["flags"] | fp.PROFILE_FLAG_INVALIDATED) & 0xFFFF
    return fp.seal_profile(out)


# ---------------------------------------------------------------------------
# Per-boot read latch
# ---------------------------------------------------------------------------
KEY_BIT_PROFILE, KEY_BIT_WITNESS, ANOMALY_BIT_UNHEALTHY = 0x01, 0x02, 0x04


def note_read(present_seen: int, read_anomaly: int, key_bit: int, load: int, healthy_after: bool) -> tuple[int, int]:
    if load in (LOAD_OK, LOAD_WRONG_SIZE):
        present_seen |= key_bit
    elif load == LOAD_ABSENT:
        if present_seen & key_bit:
            read_anomaly |= key_bit
    else:
        read_anomaly |= key_bit
    if not healthy_after:
        read_anomaly |= ANOMALY_BIT_UNHEALTHY
    return present_seen, read_anomaly


def note_committed(present_seen: int, read_anomaly: int, key_bit: int) -> tuple[int, int]:
    return present_seen | key_bit, read_anomaly


# ---------------------------------------------------------------------------
# FBS slot (read-only)
# ---------------------------------------------------------------------------
FBS_UNREADABLE, FBS_CLEAR_ABSENT, FBS_CLEAR_VALID, FBS_OBLIGATION, FBS_CORRUPT = range(5)


def fbs_slot(load: int, s) -> int:
    c = fp.classify_failback(load, s)
    if c == fp.FAILBACK_RECORD_ABSENT:
        return FBS_CLEAR_ABSENT
    if c == fp.FAILBACK_RECORD_CORRUPT:
        return FBS_CORRUPT
    if c == fp.FAILBACK_RECORD_VALID:
        return FBS_CLEAR_VALID if fp._as_failback(s)["state"] == fp.FAILBACK_CLEAR else FBS_OBLIGATION
    return FBS_UNREADABLE


def fbs_slot_clear(slot: int) -> bool:
    return slot in (FBS_CLEAR_ABSENT, FBS_CLEAR_VALID)


# ---------------------------------------------------------------------------
# Transition pre-validation
# ---------------------------------------------------------------------------
def _pbytes(p) -> bytes:
    return bytes(p) if isinstance(p, (bytes, bytearray)) else fp.pack_profile(p)


def _wbytes(w) -> bytes:
    return bytes(w) if isinstance(w, (bytes, bytearray)) else pack_provision(w)


def validate_transition(w_new, w_prior, w_pd: tuple[int, int], p_new, p_prior, p_pd: tuple[int, int]) -> bool:
    wn, pn = _as_provision(w_new), fp._as_profile(p_new)
    if classify_witness(LOAD_OK, wn) != W_VALID:
        return False
    if wn["hw_tag_key"] != FALLBACK_PROFILE_KEY or wn["hw_record_schema"] != fp.PROFILE_SCHEMA:
        return False
    if wn["hw_generation"] != pn["generation"] or wn["hw_binding"] != pn["binding"]:
        return False
    op = wn["last_op"]
    new_cls = fp.classify_profile(LOAD_OK, pn)
    if (new_cls != fp.PROFILE_INVALIDATED) if op == PROV_OP_INVALIDATE else (new_cls != fp.PROFILE_VALID):
        return False
    prior_cls, _why, _rule = compose_profile_class(p_pd[0], p_prior, w_pd[0], w_prior, 0)
    if not save_class_permitted(prior_cls):
        return False
    if (op == PROV_OP_REPLACE_CORRUPT) != (prior_cls == EPC_CORRUPT) and op != PROV_OP_INVALIDATE:
        return False
    pp = fp._as_profile(p_prior)
    if op == PROV_OP_INVALIDATE and (
            not invalidate_class_permitted(prior_cls) or not fp.profile_invalidate_permitted(pp)
            or _pbytes(pn) != _pbytes(invalidate_profile_cxx(pp))):
        return False
    prior_fba = fp.classify_profile(p_pd[0], pp)
    authentic = fba_authentic(prior_fba)
    if wn["prior_generation"] != (pp["generation"] if authentic else 0) or \
            wn["prior_binding"] != (pp["binding"] if authentic else 0):
        return False
    wp = _as_provision(w_prior)
    prior_wc = classify_witness(w_pd[0], wp)
    base = save_generation_base(prior_fba, pp["generation"], prior_wc, wp["hw_generation"], 0)
    if not save_generation_available(base) or pn["generation"] < base + 1:
        return False
    if p_pd[0] == LOAD_OK and _pbytes(pn) == _pbytes(pp):
        return False
    if w_pd[0] == LOAD_OK and _wbytes(wn) == _wbytes(wp):
        return False
    return True


# ---------------------------------------------------------------------------
# Direct NVS read / write / transaction (mirrors of the C++ templates)
# ---------------------------------------------------------------------------
@dataclass
class ReadDiag:
    probe_err: int = IDF_OK
    data_err: int = IDF_OK
    stored_len: int = 0


def storage_healthy(nvs) -> bool:
    return nvs.get_stats() == IDF_OK


def read_direct(nvs, key: int, size: int) -> tuple[int, bytes, ReadDiag]:
    """Two-step direct read. Returns (RecordLoad, record bytes, diag); the
    bytes are all-zero unless the load is OK (C++: out = T{})."""
    d = ReadDiag()
    zero = bytes(size)
    if nvs.handle() == 0:
        d.probe_err = IDF_ERR_NVS_INVALID_HANDLE
        return LOAD_STORAGE_UNAVAILABLE, zero, d
    e, length, _ = nvs.get_blob(key, None)
    d.probe_err = e
    if e == IDF_ERR_NVS_NOT_FOUND:
        return LOAD_ABSENT, zero, d
    if e in (IDF_ERR_NVS_INVALID_HANDLE, IDF_ERR_NVS_NOT_INITIALIZED):
        return LOAD_STORAGE_UNAVAILABLE, zero, d
    if e != IDF_OK:
        return LOAD_READ_ERROR, zero, d
    d.stored_len = length
    if length != size:
        return LOAD_WRONG_SIZE, zero, d
    e, got, data = nvs.get_blob(key, size)
    d.data_err = e
    if e != IDF_OK or got != size or data is None or len(data) != size:
        return LOAD_READ_ERROR, zero, d
    return LOAD_OK, bytes(data), d


@dataclass
class ReadLatch:
    present_seen: int = 0
    read_anomaly: int = 0


@dataclass
class PairRead:
    p: bytes
    w: bytes
    dp: ReadDiag
    dw: ReadDiag
    p_load: int
    w_load: int
    healthy: bool
    cls: int
    why: int
    rule: int


def read_pair(nvs, latch: ReadLatch) -> PairRead:
    p_load, p, dp = read_direct(nvs, FALLBACK_PROFILE_KEY, fp.PROFILE_SIZE)
    w_load, w, dw = read_direct(nvs, FAILBACK_PROVISION_KEY, PROVISION_SIZE)
    healthy = storage_healthy(nvs)
    latch.present_seen, latch.read_anomaly = note_read(latch.present_seen, latch.read_anomaly, KEY_BIT_PROFILE, p_load,
                                                       healthy)
    latch.present_seen, latch.read_anomaly = note_read(latch.present_seen, latch.read_anomaly, KEY_BIT_WITNESS, w_load,
                                                       healthy)
    cls, why, rule = compose_profile_class(p_load, p, w_load, w, latch.read_anomaly)
    return PairRead(p, w, dp, dw, p_load, w_load, healthy, cls, why, rule)


@dataclass
class WriteLatch:
    """The C++ inline bool s_write_latched, one per simulated boot."""
    write_latched: bool = False


@dataclass
class KeyReport:
    err: int = 0
    rb_load: int = 0
    rb_diag: ReadDiag = field(default_factory=ReadDiag)
    rb_class: int = RB_NOT_READ
    healthy_after: bool = False
    outcome: int = KEY_UNKNOWN_REBOOT
    us: int = 0


@dataclass
class TxnResult:
    w: KeyReport = field(default_factory=KeyReport)
    p: KeyReport = field(default_factory=KeyReport)
    w_rb: bytes = bytes(PROVISION_SIZE)
    p_rb: bytes = bytes(fp.PROFILE_SIZE)
    witness_advanced: bool = False
    refusal: int = REFUSAL_UNSET


WRITE_TARGETS = {FAILBACK_PROVISION_KEY: PROVISION_SIZE, FALLBACK_PROFILE_KEY: fp.PROFILE_SIZE}


def write_one(nvs, latch: WriteLatch, key: int, intended: bytes, prior_bytes: bytes, prior_load: int,
              prior_len: int, rep: KeyReport) -> tuple[int, bytes]:
    if key not in WRITE_TARGETS or len(intended) != WRITE_TARGETS[key]:
        raise ValueError("write_one may target only FBW and FBP (exclusivity pin X2)")
    t0 = nvs.now_us()
    err = IDF_ERR_NVS_INVALID_HANDLE if nvs.handle() == 0 else nvs.set_blob(key, bytes(intended))
    rep.err = err
    rep.rb_load, readback, rep.rb_diag = read_direct(nvs, key, len(intended))
    rc = readback_class(rep.rb_load, rep.rb_diag.stored_len, readback == bytes(intended), prior_load, prior_len,
                        readback == bytes(prior_bytes))
    healthy = storage_healthy(nvs)
    o = classify_key_outcome(classify_write_err(err), rc, healthy)
    if o == KEY_UNKNOWN_REBOOT:
        latch.write_latched = True
    rep.rb_class, rep.healthy_after, rep.outcome = rc, healthy, o
    rep.us = (nvs.now_us() - t0) & 0xFFFFFFFF
    return o, readback


def commit_transition(nvs, latch: WriteLatch, w_new, w_prior, w_pd: tuple[int, int], p_new, p_prior,
                      p_pd: tuple[int, int]) -> tuple[int, TxnResult]:
    """Mirror of ecco_fbdurable::commit_transition_t(). Records may be dicts
    or raw bytes; w_pd / p_pd are (load, stored_len)."""
    r = TxnResult()
    r.w.outcome = KEY_NOT_ATTEMPTED
    r.p.outcome = KEY_NOT_ATTEMPTED
    if latch.write_latched:
        r.refusal = REFUSAL_LATCHED
        return TXN_REFUSED_LATCHED, r
    if not validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd):
        r.refusal = REFUSAL_INVALID_TRANSITION
        return TXN_REFUSED_LATCHED, r
    if nvs.handle() == 0:
        r.refusal = REFUSAL_STORAGE_UNAVAILABLE
        return TXN_REFUSED_LATCHED, r
    if not storage_healthy(nvs):
        r.refusal = REFUSAL_STORAGE_UNHEALTHY
        return TXN_REFUSED_LATCHED, r
    r.refusal = REFUSAL_NONE
    ow, r.w_rb = write_one(nvs, latch, FAILBACK_PROVISION_KEY, _wbytes(w_new), _wbytes(w_prior), w_pd[0], w_pd[1], r.w)
    if ow == KEY_NOT_COMMITTED:
        return TXN_NOT_COMMITTED, r
    if ow != KEY_COMMITTED:
        return TXN_UNKNOWN_REBOOT, r
    op, r.p_rb = write_one(nvs, latch, FALLBACK_PROFILE_KEY, _pbytes(p_new), _pbytes(p_prior), p_pd[0], p_pd[1], r.p)
    if op == KEY_COMMITTED:
        return TXN_COMMITTED, r
    if op == KEY_NOT_COMMITTED:
        r.witness_advanced = True
        return TXN_NOT_COMMITTED, r
    return TXN_UNKNOWN_REBOOT, r


def mirror_after(o: int, r: TxnResult, p_prior: bytes, p_prior_load: int, w_prior: bytes,
                 w_prior_load: int) -> tuple[bytes, bytes, int, int]:
    """(profile bytes, witness bytes, profile load, witness load) for the RAM mirror."""
    if o == TXN_COMMITTED:
        return r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load
    if o == TXN_NOT_COMMITTED:
        if r.p.outcome != KEY_NOT_ATTEMPTED:
            return r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load
        return bytes(p_prior), r.w_rb, p_prior_load, r.w.rb_load
    return bytes(p_prior), bytes(w_prior), p_prior_load, w_prior_load


def u64(v: int) -> int:
    return v & 0xFFFFFFFFFFFFFFFF


def pack_u16_at(raw: bytes, off: int, val: int) -> bytes:
    out = bytearray(raw)
    struct.pack_into("<H", out, off, val & 0xFFFF)
    return bytes(out)
