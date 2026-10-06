#pragma once

// FB-B0: Fallback durable foundation - PURE MODEL.
//
// This header is the host-compilable half of the Fallback Profile durable
// primitive (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md
// sections 4-5; design/S2_fbb_durable_final.md, whose PART A overrides its
// PART B). It freezes:
//   - FailbackProvisionV1 (FBW), the 48-byte witness / high-water record
//     under tag ecco_failback_provision_v1, with its FNV-1a-64 binding and
//     four published golden vectors;
//   - classify_witness(), compose_profile_class() (rules B1-B15, B2a, B5 with
//     hw_generation == 1), the effective profile classes 0..8 and why codes;
//   - the generation rules, the SAVE / INVALIDATE class permissions and the
//     single writer-usable predicate (VALID && WHY_NONE);
//   - the per-key outcome table (COMMITTED / NOT_COMMITTED / UNKNOWN_REBOOT)
//     and the two-key transaction, witness FIRST;
//   - the per-boot read-anomaly latch transitions;
//   - read_direct_t / commit_transition_t: templates over an NVS POLICY, so
//     the exact code that will run on the device is also what the host
//     fault-injection tests execute (S2 Part A A4).
//
// It is behaviour-free: nothing here runs unless a caller instantiates the
// templates, and FB-B0 adds NO caller (pinned by
// registry/tests/test_fallback_durable_model.py). The only I/O-facing file
// is ecco_fallback_durable.h, a branch-free adapter binding the policy to
// ESPHome's preference store; it is the ONLY file allowed to contain the
// IDF blob setter.
//
// Discipline (pinned): standard headers + the FB-A header only; none of the
// storage / preference / bus / entity tokens banned in FB-A's header appear
// here, comments included; every namespace-scope object is constexpr except
// the single per-boot write latch (a C++17 inline variable).
//
// Offline mirror: registry/fallback_durable.py (C++-exact).

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "ecco_fallback_profile.h"

namespace ecco_fbdurable {

using ecco_fallback::FallbackProfileV1;
using ecco_fallback::FailbackStateV1;

// ---------------------------------------------------------------------------
// Keys. ESPHome stores a preference under the DECIMAL string of its 32-bit
// key (FNV-1 32 of the tag), namespace "esphome". FBP and FBW are written
// ONLY by commit_transition_t (no preference object ever exists for them);
// FBS has no writer at all in FB-B.
// ---------------------------------------------------------------------------
constexpr char FAILBACK_PROVISION_TAG[] = "ecco_failback_provision_v1";
constexpr uint32_t FALLBACK_PROFILE_KEY = 0x5FEE6196u;    // "1609458070"
constexpr uint32_t FAILBACK_PROVISION_KEY = 0x3BA3DF61u;  // "1000595297"
constexpr uint32_t FAILBACK_STATE_KEY = 0x808485C3u;      // "2156168643" (read-only: never written in FB-B)
static_assert(ecco_fallback::tag_key_fnv1_32(ecco_fallback::FALLBACK_PROFILE_TAG) == FALLBACK_PROFILE_KEY,
              "FBP key == FNV-1 32 of ecco_fallback_profile_v1");
static_assert(ecco_fallback::tag_key_fnv1_32(FAILBACK_PROVISION_TAG) == FAILBACK_PROVISION_KEY,
              "FBW key == FNV-1 32 of ecco_failback_provision_v1");
static_assert(ecco_fallback::tag_key_fnv1_32(ecco_fallback::FAILBACK_STATE_TAG) == FAILBACK_STATE_KEY,
              "FBS key == FNV-1 32 of ecco_failback_state_v1");

// The key string exactly as ESPHome's uint32_to_str() renders it: base 10,
// no sign, no leading zeros ("0" for 0), NUL-terminated, at most 10 digits.
using KeyString = std::array<char, 11>;
constexpr KeyString decimal_key(uint32_t key) {
  KeyString out{};
  char rev[10] = {};
  size_t n = 0;
  do {
    rev[n++] = (char) ('0' + (key % 10u));
    key /= 10u;
  } while (key != 0u);
  for (size_t i = 0; i < n; i++)
    out[i] = rev[n - 1 - i];
  return out;
}
template<size_t N> constexpr bool key_string_is(const KeyString &k, const char (&s)[N]) {
  static_assert(N >= 1 && N <= 11, "decimal key literal is at most 10 digits");
  for (size_t i = 0; i < N; i++) {
    if (k[i] != s[i])
      return false;
  }
  return true;
}
static_assert(key_string_is(decimal_key(FALLBACK_PROFILE_KEY), "1609458070"), "FBP decimal key string");
static_assert(key_string_is(decimal_key(FAILBACK_PROVISION_KEY), "1000595297"), "FBW decimal key string");
static_assert(key_string_is(decimal_key(FAILBACK_STATE_KEY), "2156168643"), "FBS decimal key string");
static_assert(key_string_is(decimal_key(0u), "0") && key_string_is(decimal_key(4294967295u), "4294967295") &&
                  key_string_is(decimal_key(10u), "10"),
              "decimal key strings: 0, 10, UINT32_MAX");

// ---------------------------------------------------------------------------
// ESP-IDF error codes the model classifies. Numeric mirror of esp_err.h /
// nvs.h (IDF 5.5.5): the I/O adapter static_asserts each one against the
// real macro, so a drift fails the native compile.
// ---------------------------------------------------------------------------
constexpr int32_t IDF_OK = 0;
constexpr int32_t IDF_ERR_NVS_NOT_INITIALIZED = 0x1101;
constexpr int32_t IDF_ERR_NVS_NOT_FOUND = 0x1102;
constexpr int32_t IDF_ERR_NVS_READ_ONLY = 0x1104;
constexpr int32_t IDF_ERR_NVS_INVALID_HANDLE = 0x1107;

// ---------------------------------------------------------------------------
// Outcome enums. In EVERY outcome / readback / error-class enum value 0 is
// the fail-closed state (UNKNOWN_REBOOT, "not read", "other error"), so
// zero-initialised memory can never read as success (S2 Part A m2).
// ---------------------------------------------------------------------------

// nvs set-blob result class. Only three codes are PROVABLY returned before
// any flash access in IDF 5.5.5 (handle lookup, read-only handle, storage
// not active); every other code - raw flash errors, NOT_FOUND from the
// old-value erase, NO_MEM, NOT_ENOUGH_SPACE (whose clean-up can erase the
// OLD chunk), ... - is OTHER (architecture 4.3, V-1, N9).
enum WriteErrClass : uint8_t {
  WERR_OTHER = 0,
  WERR_OK = 1,
  WERR_PRE_WRITE = 2,
};

constexpr WriteErrClass classify_write_err(int32_t e) {
  return e == IDF_OK ? WERR_OK
         : (e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY || e == IDF_ERR_NVS_NOT_INITIALIZED)
             ? WERR_PRE_WRITE
             : WERR_OTHER;
}

// What the direct readback after a write showed, relative to the intended
// and the prior record.
enum ReadbackClass : uint8_t {
  RB_NOT_READ = 0,
  RB_INTENDED = 1,
  RB_PRIOR = 2,
  RB_OTHER_BYTES = 3,
  RB_ABSENT_UNEXPECTED = 4,
  RB_WRONG_SIZE = 5,
  RB_READ_ERROR = 6,
  RB_UNAVAILABLE = 7,
};

enum KeyOutcome : uint8_t {
  KEY_UNKNOWN_REBOOT = 0,
  KEY_COMMITTED = 1,
  KEY_NOT_COMMITTED = 2,
  KEY_NOT_ATTEMPTED = 3,
};

enum TxnOutcome : uint8_t {
  TXN_UNKNOWN_REBOOT = 0,
  TXN_COMMITTED = 1,
  TXN_NOT_COMMITTED = 2,
  TXN_REFUSED_LATCHED = 3,  // refused with NOTHING written (see TxnRefusal for why)
};

// Why a transaction was refused before any write (diagnostics only; every
// refusal writes nothing and leaves the store unchanged).
enum TxnRefusal : uint8_t {
  REFUSAL_UNSET = 0,
  REFUSAL_NONE = 1,                 // not refused: the witness write was attempted
  REFUSAL_LATCHED = 2,              // an earlier UNKNOWN_REBOOT this boot latched all FB writes
  REFUSAL_INVALID_TRANSITION = 3,   // the intended records failed pre-validation (PO6/PO7/PO12/PO14)
  REFUSAL_STORAGE_UNAVAILABLE = 4,  // preference handle is 0
  REFUSAL_STORAGE_UNHEALTHY = 5,    // A1(b): the NVS health gate failed immediately before the commit
};

static_assert(WERR_OTHER == 0 && WERR_OK != 0 && WERR_PRE_WRITE != 0, "WriteErrClass: 0 is the fail-closed class");
static_assert(RB_NOT_READ == 0 && RB_INTENDED != 0 && RB_PRIOR != 0, "ReadbackClass: 0 is 'not read'");
static_assert(KEY_UNKNOWN_REBOOT == 0 && KEY_COMMITTED != 0 && KEY_NOT_COMMITTED != 0 && KEY_NOT_ATTEMPTED != 0,
              "KeyOutcome: 0 is UNKNOWN_REBOOT; success values are non-zero");
static_assert(TXN_UNKNOWN_REBOOT == 0 && TXN_COMMITTED != 0 && TXN_NOT_COMMITTED != 0 && TXN_REFUSED_LATCHED != 0,
              "TxnOutcome: 0 is UNKNOWN_REBOOT; success values are non-zero");
static_assert(REFUSAL_UNSET == 0 && REFUSAL_NONE != 0, "TxnRefusal: 0 is unset");
static_assert(KeyOutcome{} == KEY_UNKNOWN_REBOOT && TxnOutcome{} == TXN_UNKNOWN_REBOOT && ReadbackClass{} == RB_NOT_READ &&
                  WriteErrClass{} == WERR_OTHER,
              "zero-initialised outcomes fail closed");

// The load status and stored length of a record as read immediately before
// the transaction (the prior bytes themselves are passed alongside).
struct PriorDesc {
  uint8_t load;
  uint32_t stored_len;
};

// Readback relative to intended / prior. `rb_eq_*` are full-record byte
// comparisons made by the caller; RB_PRIOR needs a positive match of the
// prior: equal bytes for a present record, ABSENT for an absent one, and the
// same stored length for a wrong-size one.
constexpr ReadbackClass readback_class(uint8_t rb_load, uint32_t rb_len, bool rb_eq_intended, PriorDesc prior,
                                       bool rb_eq_prior_bytes) {
  return rb_load == ecco_fallback::LOAD_OK
             ? (rb_eq_intended ? RB_INTENDED
                               : (prior.load == ecco_fallback::LOAD_OK && rb_eq_prior_bytes) ? RB_PRIOR : RB_OTHER_BYTES)
         : rb_load == ecco_fallback::LOAD_ABSENT
             ? (prior.load == ecco_fallback::LOAD_ABSENT ? RB_PRIOR : RB_ABSENT_UNEXPECTED)
         : rb_load == ecco_fallback::LOAD_WRONG_SIZE
             ? ((prior.load == ecco_fallback::LOAD_WRONG_SIZE && prior.stored_len == rb_len) ? RB_PRIOR : RB_WRONG_SIZE)
         : rb_load == ecco_fallback::LOAD_STORAGE_UNAVAILABLE ? RB_UNAVAILABLE
                                                              : RB_READ_ERROR;
}

// Per-key outcome (architecture 4.3). Exactly two definite cells:
//   (OK, readback == intended, store healthy)           -> COMMITTED
//   (pre-write code, readback == prior, store healthy)  -> NOT_COMMITTED
// Every other cell - including any cell where the NVS health gate failed
// after the write (A1(c)) - is UNKNOWN_REBOOT. NOT_ATTEMPTED is never
// produced here (only a key that was never written carries it).
constexpr KeyOutcome classify_key_outcome(WriteErrClass e, ReadbackClass r, bool healthy_after) {
  return !healthy_after ? KEY_UNKNOWN_REBOOT
         : (e == WERR_OK && r == RB_INTENDED) ? KEY_COMMITTED
         : (e == WERR_PRE_WRITE && r == RB_PRIOR) ? KEY_NOT_COMMITTED
                                                  : KEY_UNKNOWN_REBOOT;
}

constexpr bool key_outcome_table_holds() {
  for (int e = 0; e <= 2; e++) {
    for (int r = 0; r <= 7; r++) {
      for (int h = 0; h <= 1; h++) {
        const KeyOutcome o = classify_key_outcome((WriteErrClass) e, (ReadbackClass) r, h != 0);
        const bool commit_cell = e == WERR_OK && r == RB_INTENDED && h == 1;
        const bool not_commit_cell = e == WERR_PRE_WRITE && r == RB_PRIOR && h == 1;
        if (o == KEY_NOT_ATTEMPTED)
          return false;
        if ((o == KEY_COMMITTED) != commit_cell || (o == KEY_NOT_COMMITTED) != not_commit_cell)
          return false;
        if (!commit_cell && !not_commit_cell && o != KEY_UNKNOWN_REBOOT)
          return false;
      }
    }
  }
  return true;
}
static_assert(key_outcome_table_holds(), "per-key outcome table: 2 definite cells, every other cell UNKNOWN_REBOOT");
static_assert(classify_write_err(0) == WERR_OK && classify_write_err(0x1107) == WERR_PRE_WRITE &&
                  classify_write_err(0x1104) == WERR_PRE_WRITE && classify_write_err(0x1101) == WERR_PRE_WRITE &&
                  classify_write_err(0x1102) == WERR_OTHER && classify_write_err(0x107) == WERR_OTHER &&
                  classify_write_err(0x101) == WERR_OTHER && classify_write_err(0x1105) == WERR_OTHER &&
                  classify_write_err(0x1108) == WERR_OTHER && classify_write_err(-1) == WERR_OTHER,
              "write error classes: exactly INVALID_HANDLE / READ_ONLY / NOT_INITIALIZED are pre-write");

// ---------------------------------------------------------------------------
// FailbackProvisionV1 (FBW) - 48 bytes, layout frozen for the life of the
// product. The witness LEADS: every profile write is preceded, in the same
// synchronous call, by a COMMITTED witness whose hw_generation / hw_binding
// name the new profile record, so hw >= every committed generation and a
// resurrected older record is detectable (architecture 4.5).
// ---------------------------------------------------------------------------
constexpr uint32_t PROVISION_MAGIC = 0x45434657u;  // 'ECFW'
constexpr uint16_t PROVISION_SCHEMA = 1;
constexpr uint16_t PROVISION_SIZE = 48;
constexpr size_t PROVISION_BOUND_BYTES = 40;  // binding covers stored bytes [0, 40)
constexpr char PROVISION_BINDING_DOMAIN[] = "ECCO-FAILBACK-PROVISION-v1";
static_assert(sizeof(PROVISION_BINDING_DOMAIN) - 1 == 26, "provision binding domain is 26 bytes, no NUL");
static_assert(PROVISION_MAGIC != ecco_fallback::PROFILE_MAGIC && PROVISION_MAGIC != ecco_fallback::FAILBACK_MAGIC &&
                  PROVISION_MAGIC != 0x45434356u && PROVISION_MAGIC != 0x4543534Au,
              "FBW magic differs from ECFP, ECFB, ECCV and ECSJ");

enum ProvisionOp : uint8_t {
  PROV_OP_INVALID = 0,
  PROV_OP_SAVE = 1,
  PROV_OP_INVALIDATE = 2,
  PROV_OP_REPLACE_CORRUPT = 3,
};

struct FailbackProvisionV1 {
  uint32_t magic;             // 0   PROVISION_MAGIC
  uint16_t schema;            // 4   1
  uint16_t size;              // 6   48
  uint32_t hw_generation;     // 8   high-water: generation of the last profile transition attempted (>= 1)
  uint32_t prior_generation;  // 12  authentic generation stored when that transition began; 0 = none
  uint64_t hw_binding;        // 16  binding of the record written at hw_generation
  uint64_t prior_binding;     // 24  binding of that prior record; 0 iff prior_generation == 0
  uint32_t hw_tag_key;        // 32  preference key holding the hw record (FALLBACK_PROFILE_KEY for V1)
  uint16_t hw_record_schema;  // 36  schema of the hw record (1 for FallbackProfileV1)
  uint8_t last_op;            // 38  ProvisionOp
  uint8_t flags;              // 39  must be 0
  uint64_t binding;           // 40  provision_binding()
};
static_assert(sizeof(FailbackProvisionV1) == 48, "FailbackProvisionV1 must be exactly 48 bytes");
static_assert(offsetof(FailbackProvisionV1, magic) == 0 && offsetof(FailbackProvisionV1, schema) == 4 &&
                  offsetof(FailbackProvisionV1, size) == 6 && offsetof(FailbackProvisionV1, hw_generation) == 8 &&
                  offsetof(FailbackProvisionV1, prior_generation) == 12 && offsetof(FailbackProvisionV1, hw_binding) == 16 &&
                  offsetof(FailbackProvisionV1, prior_binding) == 24 && offsetof(FailbackProvisionV1, hw_tag_key) == 32 &&
                  offsetof(FailbackProvisionV1, hw_record_schema) == 36 && offsetof(FailbackProvisionV1, last_op) == 38 &&
                  offsetof(FailbackProvisionV1, flags) == 39 && offsetof(FailbackProvisionV1, binding) == 40,
              "FailbackProvisionV1 field offsets");
static_assert(std::is_trivially_copyable<FailbackProvisionV1>::value, "FBW record must be trivially copyable");
static_assert(std::is_standard_layout<FailbackProvisionV1>::value, "FBW record must be standard layout");

using ProvisionBytes = std::array<uint8_t, PROVISION_SIZE>;

constexpr ProvisionBytes encode_provision(const FailbackProvisionV1 &w) {
  ProvisionBytes b{};
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, magic), w.magic, 4);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, schema), w.schema, 2);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, size), w.size, 2);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, hw_generation), w.hw_generation, 4);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, prior_generation), w.prior_generation, 4);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, hw_binding), w.hw_binding, 8);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, prior_binding), w.prior_binding, 8);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, hw_tag_key), w.hw_tag_key, 4);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, hw_record_schema), w.hw_record_schema, 2);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, last_op), w.last_op, 1);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, flags), w.flags, 1);
  ecco_fallback::put_le(b, offsetof(FailbackProvisionV1, binding), w.binding, 8);
  return b;
}

constexpr FailbackProvisionV1 decode_provision(const ProvisionBytes &b) {
  FailbackProvisionV1 w{};
  w.magic = (uint32_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, magic), 4);
  w.schema = (uint16_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, schema), 2);
  w.size = (uint16_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, size), 2);
  w.hw_generation = (uint32_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, hw_generation), 4);
  w.prior_generation = (uint32_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, prior_generation), 4);
  w.hw_binding = ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, hw_binding), 8);
  w.prior_binding = ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, prior_binding), 8);
  w.hw_tag_key = (uint32_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, hw_tag_key), 4);
  w.hw_record_schema = (uint16_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, hw_record_schema), 2);
  w.last_op = (uint8_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, last_op), 1);
  w.flags = (uint8_t) ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, flags), 1);
  w.binding = ecco_fallback::get_le(b, offsetof(FailbackProvisionV1, binding), 8);
  return w;
}

// FNV-1a-64(PROVISION_BINDING_DOMAIN || stored bytes [0, 40)).
constexpr uint64_t provision_binding(const FailbackProvisionV1 &w) {
  const ProvisionBytes b = encode_provision(w);
  uint64_t h = ecco_fallback::fnv1a64_literal(ecco_fallback::FNV1A64_OFFSET_BASIS, PROVISION_BINDING_DOMAIN);
  for (size_t i = 0; i < PROVISION_BOUND_BYTES; i++)
    h = ecco_fallback::fnv1a64_step(h, b[i]);
  return h;
}

constexpr FailbackProvisionV1 seal_provision(FailbackProvisionV1 w) {
  w.binding = provision_binding(w);
  return w;
}

constexpr FailbackProvisionV1 make_provision(uint32_t hw_generation, uint64_t hw_binding, uint32_t prior_generation,
                                             uint64_t prior_binding, uint32_t hw_tag_key, uint16_t hw_record_schema,
                                             uint8_t last_op) {
  FailbackProvisionV1 w{};
  w.magic = PROVISION_MAGIC;
  w.schema = PROVISION_SCHEMA;
  w.size = PROVISION_SIZE;
  w.hw_generation = hw_generation;
  w.prior_generation = prior_generation;
  w.hw_binding = hw_binding;
  w.prior_binding = prior_binding;
  w.hw_tag_key = hw_tag_key;
  w.hw_record_schema = hw_record_schema;
  w.last_op = last_op;
  w.flags = 0;
  return seal_provision(w);
}

// Byte-exact record equality over the field-by-field little-endian stored
// bytes (padding-free layouts, so this is the in-memory record on the LE
// target; constexpr-safe in gnu++17, unlike std::array's operator==).
template<size_t N> constexpr bool bytes_equal(const std::array<uint8_t, N> &a, const std::array<uint8_t, N> &b) {
  for (size_t i = 0; i < N; i++) {
    if (a[i] != b[i])
      return false;
  }
  return true;
}
constexpr bool records_equal(const FallbackProfileV1 &a, const FallbackProfileV1 &b) {
  return bytes_equal(ecco_fallback::encode_profile(a), ecco_fallback::encode_profile(b));
}
constexpr bool records_equal(const FailbackProvisionV1 &a, const FailbackProvisionV1 &b) {
  return bytes_equal(encode_provision(a), encode_provision(b));
}

// The FIRST failing rule, in precedence order (all -> W_CORRUPT).
enum WitnessDefect : uint8_t {
  WIT_DEFECT_NONE = 0,
  WIT_DEFECT_MAGIC = 1,
  WIT_DEFECT_SCHEMA = 2,  // a different schema under this tag is corruption, never a migration
  WIT_DEFECT_SIZE = 3,
  WIT_DEFECT_BINDING = 4,
  WIT_DEFECT_FLAGS = 5,
  WIT_DEFECT_HW = 6,         // hw_generation == 0
  WIT_DEFECT_PRIOR = 7,      // prior_generation >= hw_generation, or (prior_generation == 0) != (prior_binding == 0)
  WIT_DEFECT_OP = 8,         // last_op not in {1, 2, 3}
  WIT_DEFECT_TAG = 9,        // hw_tag_key == 0
  WIT_DEFECT_RECSCHEMA = 10  // hw_record_schema == 0
};

constexpr WitnessDefect witness_defect(const FailbackProvisionV1 &w) {
  if (w.magic != PROVISION_MAGIC)
    return WIT_DEFECT_MAGIC;
  if (w.schema != PROVISION_SCHEMA)
    return WIT_DEFECT_SCHEMA;
  if (w.size != PROVISION_SIZE)
    return WIT_DEFECT_SIZE;
  if (w.binding != provision_binding(w))
    return WIT_DEFECT_BINDING;
  if (w.flags != 0)
    return WIT_DEFECT_FLAGS;
  if (w.hw_generation == 0)
    return WIT_DEFECT_HW;
  if (w.prior_generation >= w.hw_generation || (w.prior_generation == 0) != (w.prior_binding == 0))
    return WIT_DEFECT_PRIOR;
  if (w.last_op != PROV_OP_SAVE && w.last_op != PROV_OP_INVALIDATE && w.last_op != PROV_OP_REPLACE_CORRUPT)
    return WIT_DEFECT_OP;
  if (w.hw_tag_key == 0)
    return WIT_DEFECT_TAG;
  if (w.hw_record_schema == 0)
    return WIT_DEFECT_RECSCHEMA;
  return WIT_DEFECT_NONE;
}

// Numbering mirrors ecco_fallback::FailbackRecordClass; 0 = UNREADABLE.
enum WitnessClass : uint8_t {
  W_UNREADABLE = 0,
  W_ABSENT = 1,
  W_CORRUPT = 2,
  W_VALID = 3,
};

// Load status first (the record is never inspected unless load == OK), then
// the defect rules.
constexpr WitnessClass classify_witness(uint8_t load, const FailbackProvisionV1 &w) {
  if (load == ecco_fallback::LOAD_ABSENT)
    return W_ABSENT;
  if (load == ecco_fallback::LOAD_WRONG_SIZE)
    return W_CORRUPT;
  if (load != ecco_fallback::LOAD_OK)
    return W_UNREADABLE;
  return witness_defect(w) == WIT_DEFECT_NONE ? W_VALID : W_CORRUPT;
}

// ---------------------------------------------------------------------------
// Effective profile class: FB-A class x witness relation x per-boot read
// anomaly (architecture 4.6; S2 section 2.5 as amended by Part A m7).
// ---------------------------------------------------------------------------
enum EffectiveProfileClass : uint8_t {
  EPC_UNREADABLE = 0,
  EPC_NOT_CAPTURED = 1,
  EPC_CORRUPT = 2,
  EPC_CORRUPT_DOMAIN = 3,
  EPC_INVALIDATED = 4,
  EPC_VALID = 5,
  EPC_PROFILE_LOST = 6,
  EPC_SAVE_UNCONFIRMED = 7,  // RAM overlay after an UNKNOWN_REBOOT this boot; never produced by compose
  EPC_PROFILE_STALE = 8,
};
static_assert((int) EPC_UNREADABLE == (int) ecco_fallback::PROFILE_UNREADABLE &&
                  (int) EPC_NOT_CAPTURED == (int) ecco_fallback::PROFILE_NOT_CAPTURED &&
                  (int) EPC_CORRUPT == (int) ecco_fallback::PROFILE_CORRUPT &&
                  (int) EPC_CORRUPT_DOMAIN == (int) ecco_fallback::PROFILE_CORRUPT_DOMAIN &&
                  (int) EPC_INVALIDATED == (int) ecco_fallback::PROFILE_INVALIDATED &&
                  (int) EPC_VALID == (int) ecco_fallback::PROFILE_VALID,
              "effective classes 0..5 share FB-A ProfileClass numbering");

enum EpcWhy : uint8_t {
  WHY_NONE = 0,
  WHY_INTERRUPTED = 1,
  WHY_ROLLBACK = 2,
  WHY_MISMATCH = 3,
  WHY_SUPERSEDED = 4,
  WHY_WIT_LAGGING = 5,
  WHY_WIT_MISSING = 6,
  WHY_WIT_CORRUPT = 7,
  WHY_PROFILE_READ = 8,
  WHY_WITNESS_READ = 9,
  WHY_READ_ANOMALY = 10,
  WHY_FIRST_SAVE_UNCONFIRMED = 11,
  WHY_LOST_WIT_CORRUPT = 12,
};

// The rule that decided (diagnostics / tests). B2a is numbered 16.
enum ComposeRule : uint8_t {
  RULE_NONE = 0,
  RULE_B1 = 1,
  RULE_B2 = 2,
  RULE_B3 = 3,
  RULE_B4 = 4,
  RULE_B5 = 5,
  RULE_B6 = 6,
  RULE_B7 = 7,
  RULE_B8 = 8,
  RULE_B9 = 9,
  RULE_B10 = 10,
  RULE_B11 = 11,
  RULE_B12 = 12,
  RULE_B13 = 13,
  RULE_B14 = 14,
  RULE_B15 = 15,
  RULE_B2A = 16,
};

struct EffectiveProfile {
  uint8_t cls;
  uint8_t why;
  uint8_t rule;
};

// Authentic = binding verified, generation trusted.
constexpr bool fba_authentic(uint8_t fba_cls) {
  return fba_cls == ecco_fallback::PROFILE_VALID || fba_cls == ecco_fallback::PROFILE_INVALIDATED ||
         fba_cls == ecco_fallback::PROFILE_CORRUPT_DOMAIN;
}

// First matching row wins. `anomaly_bits` is the per-boot read-anomaly
// latch (ReadLatch::read_anomaly): any bit set means an EARLIER read this
// boot was unreadable, or a record seen present vanished, or the store was
// unhealthy - the current read notwithstanding (B2a).
constexpr EffectiveProfile compose_profile_class(uint8_t p_load, const FallbackProfileV1 &p, uint8_t w_load,
                                                 const FailbackProvisionV1 &w, uint8_t anomaly_bits) {
  const uint8_t c = ecco_fallback::classify_profile(p_load, p);
  const uint8_t wc = classify_witness(w_load, w);
  if (c == ecco_fallback::PROFILE_UNREADABLE)
    return {EPC_UNREADABLE, WHY_PROFILE_READ, RULE_B1};
  if (wc == W_UNREADABLE)
    return {EPC_UNREADABLE, WHY_WITNESS_READ, RULE_B2};
  if (anomaly_bits != 0)
    return {EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A};
  if (c == ecco_fallback::PROFILE_CORRUPT)
    return {EPC_CORRUPT, WHY_NONE, RULE_B3};
  if (c == ecco_fallback::PROFILE_NOT_CAPTURED) {
    if (wc == W_ABSENT)
      return {EPC_NOT_CAPTURED, WHY_NONE, RULE_B4};
    if (wc == W_VALID && w.prior_generation == 0 && w.last_op == PROV_OP_SAVE && w.hw_generation == 1)
      return {EPC_PROFILE_LOST, WHY_FIRST_SAVE_UNCONFIRMED, RULE_B5};
    if (wc == W_VALID)
      return {EPC_PROFILE_LOST, WHY_NONE, RULE_B6};
    return {EPC_PROFILE_LOST, WHY_LOST_WIT_CORRUPT, RULE_B7};  // wc == W_CORRUPT
  }
  // c is authentic here: VALID, INVALIDATED or CORRUPT_DOMAIN.
  if (wc == W_VALID) {
    if (p.generation > w.hw_generation)
      return {c, WHY_WIT_LAGGING, RULE_B8};
    if (w.hw_tag_key != FALLBACK_PROFILE_KEY || w.hw_record_schema != ecco_fallback::PROFILE_SCHEMA)
      return {EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9};
    if (p.generation == w.hw_generation && p.binding == w.hw_binding)
      return {c, WHY_NONE, RULE_B10};
    if (p.generation == w.hw_generation)
      return {EPC_PROFILE_STALE, WHY_MISMATCH, RULE_B11};
    if (p.generation == w.prior_generation && p.binding == w.prior_binding)
      return {EPC_PROFILE_STALE, WHY_INTERRUPTED, RULE_B12};
    return {EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13};
  }
  if (wc == W_ABSENT)
    return {c, WHY_WIT_MISSING, RULE_B14};
  return {c, WHY_WIT_CORRUPT, RULE_B15};  // wc == W_CORRUPT
}

// The ONE writer-usable predicate (S2 Part A A5, decision D10): only a
// VALID profile whose witness is consistent (rule B10). VALID with a
// lagging (B8), missing (B14) or corrupt (B15) witness is not usable by any
// future profile-driven writer ("re-save to re-arm").
constexpr bool profile_writer_usable(uint8_t cls, uint8_t why) { return cls == EPC_VALID && why == WHY_NONE; }

// SAVE may replace every class except UNREADABLE (never overwritten; a
// reboot re-derives it) and SAVE_UNCONFIRMED (reboot first). CORRUPT only
// with the distinct REPLACE CORRUPT confirmation (narrow overturn of
// charter C1; architecture 4.6).
constexpr bool save_class_permitted(uint8_t cls) {
  return cls == EPC_NOT_CAPTURED || cls == EPC_CORRUPT || cls == EPC_CORRUPT_DOMAIN || cls == EPC_INVALIDATED ||
         cls == EPC_VALID || cls == EPC_PROFILE_LOST || cls == EPC_PROFILE_STALE;
}
constexpr bool save_requires_replace_phrase(uint8_t cls) { return cls == EPC_CORRUPT; }
// INVALIDATE: effective class exactly VALID (any witness relation B8 / B10 /
// B14 / B15); FB-A profile_invalidate_permitted() is checked separately.
constexpr bool invalidate_class_permitted(uint8_t cls) { return cls == EPC_VALID; }

// ---------------------------------------------------------------------------
// Generation (architecture 3.9; S2 Part A m11). One logical counter that
// never goes backwards, even after a loss.
// ---------------------------------------------------------------------------
constexpr uint32_t GENERATION_MAX = 0xFFFFFFFFu;

constexpr uint32_t max3(uint32_t a, uint32_t b, uint32_t c) { return a > b ? (a > c ? a : c) : (b > c ? b : c); }

// SAVE base = max(authentic prior generation, witness hw if W_VALID,
// per-boot seen high-water); the new generation is base + 1 and SAVE is
// refused when base == GENERATION_MAX (never wraps).
constexpr uint32_t save_generation_base(uint8_t fba_cls, uint32_t g, uint8_t wc, uint32_t hw, uint32_t seen_hw_gen) {
  return max3(fba_authentic(fba_cls) ? g : 0u, wc == W_VALID ? hw : 0u, seen_hw_gen);
}
constexpr bool save_generation_available(uint32_t base) { return base != GENERATION_MAX; }

// INVALIDATE writes g + 1 (FB-A invalidate_profile) and additionally
// requires g + 1 > max(hw, seen_hw_gen).
constexpr bool invalidate_generation_permitted(uint32_t g, uint8_t wc, uint32_t hw, uint32_t seen_hw_gen) {
  return g < GENERATION_MAX && g + 1u > (wc == W_VALID ? hw : 0u) && g + 1u > seen_hw_gen;
}

// seen_hw_gen: RAM high-water, updated on every authentic read.
constexpr uint32_t next_seen_hw_gen(uint32_t seen_hw_gen, uint8_t fba_cls, uint32_t g, uint8_t wc, uint32_t hw) {
  return max3(seen_hw_gen, fba_authentic(fba_cls) ? g : 0u, wc == W_VALID ? hw : 0u);
}

// ---------------------------------------------------------------------------
// Per-boot read discipline (S2 5.4 R-D3 / R-D4, Part A A1(a)). RAM only;
// a reboot is the only reset.
// ---------------------------------------------------------------------------
constexpr uint8_t KEY_BIT_PROFILE = 0x01;
constexpr uint8_t KEY_BIT_WITNESS = 0x02;
constexpr uint8_t ANOMALY_BIT_UNHEALTHY = 0x04;

struct ReadLatch {
  uint8_t present_seen;  // bit0 FBP, bit1 FBW: read OK / WRONG_SIZE, or written COMMITTED, this boot
  uint8_t read_anomaly;  // sticky: bit0/bit1 per key, bit2 NVS health gate failed after a read
};

// One FBP or FBW read. READ_ERROR / STORAGE_UNAVAILABLE / any unknown load,
// or ABSENT for a key already seen present this boot (FB-B never deletes
// keys, so a same-boot vanish is always an anomaly), sets the key's anomaly
// bit; an unhealthy store after the read sets ANOMALY_BIT_UNHEALTHY. Bits are
// never cleared.
constexpr ReadLatch note_read(ReadLatch s, uint8_t key_bit, uint8_t load, bool healthy_after) {
  ReadLatch out = s;
  if (load == ecco_fallback::LOAD_OK || load == ecco_fallback::LOAD_WRONG_SIZE)
    out.present_seen = (uint8_t) (out.present_seen | key_bit);
  else if (load == ecco_fallback::LOAD_ABSENT) {
    if (s.present_seen & key_bit)
      out.read_anomaly = (uint8_t) (out.read_anomaly | key_bit);
  } else
    out.read_anomaly = (uint8_t) (out.read_anomaly | key_bit);
  if (!healthy_after)
    out.read_anomaly = (uint8_t) (out.read_anomaly | ANOMALY_BIT_UNHEALTHY);
  return out;
}
constexpr ReadLatch note_committed(ReadLatch s, uint8_t key_bit) {
  return ReadLatch{(uint8_t) (s.present_seen | key_bit), s.read_anomaly};
}

constexpr bool read_latch_transitions_hold() {
  using ecco_fallback::LOAD_ABSENT;
  using ecco_fallback::LOAD_OK;
  using ecco_fallback::LOAD_READ_ERROR;
  using ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  using ecco_fallback::LOAD_WRONG_SIZE;
  const ReadLatch z{0, 0};
  const ReadLatch seen = note_read(z, KEY_BIT_PROFILE, LOAD_OK, true);
  return seen.present_seen == KEY_BIT_PROFILE && seen.read_anomaly == 0 &&
         note_read(z, KEY_BIT_WITNESS, LOAD_WRONG_SIZE, true).present_seen == KEY_BIT_WITNESS &&
         note_read(z, KEY_BIT_PROFILE, LOAD_ABSENT, true).read_anomaly == 0 &&           // absent, never seen: fine
         note_read(seen, KEY_BIT_PROFILE, LOAD_ABSENT, true).read_anomaly == KEY_BIT_PROFILE &&  // same-boot vanish
         note_read(seen, KEY_BIT_WITNESS, LOAD_ABSENT, true).read_anomaly == 0 &&         // bits are per key
         note_read(z, KEY_BIT_WITNESS, LOAD_READ_ERROR, true).read_anomaly == KEY_BIT_WITNESS &&
         note_read(z, KEY_BIT_PROFILE, LOAD_STORAGE_UNAVAILABLE, true).read_anomaly == KEY_BIT_PROFILE &&
         note_read(z, KEY_BIT_PROFILE, 9, true).read_anomaly == KEY_BIT_PROFILE &&          // unknown load
         note_read(z, KEY_BIT_PROFILE, LOAD_OK, false).read_anomaly == ANOMALY_BIT_UNHEALTHY &&
         note_read(note_read(z, KEY_BIT_PROFILE, LOAD_READ_ERROR, true), KEY_BIT_PROFILE, LOAD_OK, true).read_anomaly ==
             KEY_BIT_PROFILE &&  // sticky
         note_committed(z, KEY_BIT_WITNESS).present_seen == KEY_BIT_WITNESS;
}
static_assert(read_latch_transitions_hold(), "FB-B0 per-boot read latch: sticky anomaly bits, same-boot vanish, health bit");

// ---------------------------------------------------------------------------
// Failback-state (FBS) slot for FB-B's gates: read-only, never written.
// ABSENT or a VALID CLEAR record is clear; any other VALID state is an
// open episode; CORRUPT and UNREADABLE block (architecture 3.4).
// ---------------------------------------------------------------------------
enum FbsSlot : uint8_t {
  FBS_UNREADABLE = 0,
  FBS_CLEAR_ABSENT = 1,
  FBS_CLEAR_VALID = 2,
  FBS_OBLIGATION = 3,
  FBS_CORRUPT = 4,
};
constexpr FbsSlot fbs_slot(uint8_t load, const FailbackStateV1 &s) {
  const uint8_t c = ecco_fallback::classify_failback(load, s);
  return c == ecco_fallback::FAILBACK_RECORD_ABSENT                                        ? FBS_CLEAR_ABSENT
         : c == ecco_fallback::FAILBACK_RECORD_CORRUPT                                     ? FBS_CORRUPT
         : c == ecco_fallback::FAILBACK_RECORD_VALID && s.state == ecco_fallback::FAILBACK_CLEAR ? FBS_CLEAR_VALID
         : c == ecco_fallback::FAILBACK_RECORD_VALID                                       ? FBS_OBLIGATION
                                                                                           : FBS_UNREADABLE;
}
constexpr bool fbs_slot_clear(uint8_t slot) { return slot == FBS_CLEAR_ABSENT || slot == FBS_CLEAR_VALID; }

// ---------------------------------------------------------------------------
// Transition pre-validation (PO6, PO7, PO12, PO14). commit_transition_t
// refuses - writing nothing - unless the intended pair is exactly a legal
// successor of the prior pair it was built from.
// ---------------------------------------------------------------------------
constexpr bool validate_transition(const FailbackProvisionV1 &w_new, const FailbackProvisionV1 &w_prior, PriorDesc w_pd,
                                   const FallbackProfileV1 &p_new, const FallbackProfileV1 &p_prior, PriorDesc p_pd) {
  // The intended witness is a valid V1 witness naming the V1 profile record it precedes.
  if (classify_witness(ecco_fallback::LOAD_OK, w_new) != W_VALID)
    return false;
  if (w_new.hw_tag_key != FALLBACK_PROFILE_KEY || w_new.hw_record_schema != ecco_fallback::PROFILE_SCHEMA)
    return false;
  if (w_new.hw_generation != p_new.generation || w_new.hw_binding != p_new.binding)
    return false;
  const uint8_t op = w_new.last_op;
  const uint8_t new_cls = ecco_fallback::classify_profile(ecco_fallback::LOAD_OK, p_new);
  if (op == PROV_OP_INVALIDATE ? new_cls != ecco_fallback::PROFILE_INVALIDATED : new_cls != ecco_fallback::PROFILE_VALID)
    return false;
  // The prior pair: never UNREADABLE; CORRUPT only via REPLACE_CORRUPT; INVALIDATE only from VALID.
  const EffectiveProfile prior = compose_profile_class(p_pd.load, p_prior, w_pd.load, w_prior, 0);
  if (!save_class_permitted(prior.cls))
    return false;
  if ((op == PROV_OP_REPLACE_CORRUPT) != (prior.cls == EPC_CORRUPT) && op != PROV_OP_INVALIDATE)
    return false;
  if (op == PROV_OP_INVALIDATE &&
      (!invalidate_class_permitted(prior.cls) || !ecco_fallback::profile_invalidate_permitted(p_prior) ||
       !records_equal(p_new, ecco_fallback::invalidate_profile(p_prior))))
    return false;
  // prior_* names the authentic prior record, else 0/0.
  const uint8_t prior_fba = ecco_fallback::classify_profile(p_pd.load, p_prior);
  const bool authentic = fba_authentic(prior_fba);
  if (w_new.prior_generation != (authentic ? p_prior.generation : 0u) ||
      w_new.prior_binding != (authentic ? p_prior.binding : 0u))
    return false;
  // Generation strictly increases past the authentic prior and a valid prior witness.
  const uint8_t prior_wc = classify_witness(w_pd.load, w_prior);
  const uint32_t base = save_generation_base(prior_fba, p_prior.generation, prior_wc, w_prior.hw_generation, 0u);
  if (!save_generation_available(base) || p_new.generation < base + 1u)
    return false;
  // The bytes really change on both keys.
  if (p_pd.load == ecco_fallback::LOAD_OK && records_equal(p_new, p_prior))
    return false;
  if (w_pd.load == ecco_fallback::LOAD_OK && records_equal(w_new, w_prior))
    return false;
  return true;
}

// ---------------------------------------------------------------------------
// The NVS policy. A policy type provides (all non-template members):
//   uint32_t handle() const;           preference handle; 0 = storage unavailable
//   int32_t  set_blob(uint32_t key, const void *data, size_t len);
//   int32_t  get_blob(uint32_t key, void *out, size_t *len);    out == nullptr: size probe
//   int32_t  get_stats() const;        IDF_OK iff no NVS page is INVALID (RAM-only)
//   uint32_t now_us() const;           microsecond clock for duration fields
// The production policy is ecco_fbdurable::EspNvs (ecco_fallback_durable.h);
// the host tests provide a fault-injecting fake.
// ---------------------------------------------------------------------------

// A1: the NVS health gate (the store reports no INVALID page).
template<class Nvs> bool storage_healthy(const Nvs &nvs) { return nvs.get_stats() == IDF_OK; }

struct ReadDiag {
  int32_t probe_err;
  int32_t data_err;
  uint32_t stored_len;
};

// Two-step direct read (architecture 4.1): a size probe (index only), then
// a data read with payload CRC, into a zeroed buffer. Returns FB-A
// RecordLoad. NEVER retried by callers in the same logical step: the first
// read may already have erased a damaged chunk (a CRC-bad data read returns
// NOT_FOUND after erasing it, which is READ_ERROR here, never ABSENT). Also
// the read-only probe primitive for other domains' records (FBS, markers).
template<class T, class Nvs> uint8_t read_direct_t(Nvs &nvs, uint32_t key, T &out, ReadDiag &d) {
  static_assert(std::is_trivially_copyable<T>::value && std::is_standard_layout<T>::value, "POD record");
  d = ReadDiag{IDF_OK, IDF_OK, 0};
  out = T{};
  if (nvs.handle() == 0) {
    d.probe_err = IDF_ERR_NVS_INVALID_HANDLE;
    return ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  }
  size_t len = 0;
  int32_t e = nvs.get_blob(key, nullptr, &len);
  d.probe_err = e;
  if (e == IDF_ERR_NVS_NOT_FOUND)
    return ecco_fallback::LOAD_ABSENT;  // "not readable NOW", never proof of "never written"
  if (e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_NOT_INITIALIZED)
    return ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  if (e != IDF_OK)
    return ecco_fallback::LOAD_READ_ERROR;
  d.stored_len = (uint32_t) len;
  if (len != sizeof(T))
    return ecco_fallback::LOAD_WRONG_SIZE;
  T tmp{};
  size_t got = sizeof(T);
  e = nvs.get_blob(key, &tmp, &got);
  d.data_err = e;
  if (e != IDF_OK || got != sizeof(T))
    return ecco_fallback::LOAD_READ_ERROR;  // incl. NOT_FOUND = CRC-erased by THIS read
  out = tmp;
  return ecco_fallback::LOAD_OK;
}

// Read FBP then FBW, apply the health gate and the read latch, and compose.
// The single read path for boot, REVIEW and the SAVE / INVALIDATE fresh prior.
struct PairRead {
  FallbackProfileV1 p;
  FailbackProvisionV1 w;
  ReadDiag dp;
  ReadDiag dw;
  uint8_t p_load;
  uint8_t w_load;
  uint8_t healthy;
  EffectiveProfile e;
};
template<class Nvs> PairRead read_pair_t(Nvs &nvs, ReadLatch &latch) {
  PairRead r{};
  r.p_load = read_direct_t(nvs, FALLBACK_PROFILE_KEY, r.p, r.dp);
  r.w_load = read_direct_t(nvs, FAILBACK_PROVISION_KEY, r.w, r.dw);
  const bool healthy = storage_healthy(nvs);
  latch = note_read(latch, KEY_BIT_PROFILE, r.p_load, healthy);
  latch = note_read(latch, KEY_BIT_WITNESS, r.w_load, healthy);
  r.healthy = healthy ? 1 : 0;
  r.e = compose_profile_class(r.p_load, r.p, r.w_load, r.w, latch.read_anomaly);
  return r;
}

// The per-boot write latch (PO13): set by any UNKNOWN_REBOOT key outcome,
// checked first by every transaction, cleared ONLY by a reboot (RAM).
inline bool s_write_latched = false;
inline bool write_latched() { return s_write_latched; }

struct KeyReport {
  int32_t err;
  uint8_t rb_load;
  ReadDiag rb_diag;
  uint8_t rb_class;
  uint8_t healthy_after;
  uint8_t outcome;
  uint32_t us;
};

struct TxnResult {
  KeyReport w;
  KeyReport p;
  FailbackProvisionV1 w_rb;
  FallbackProfileV1 p_rb;
  uint8_t witness_advanced;
  uint8_t refusal;
};

// Exclusivity (pin X2): the ONLY (record, key) pairs a write may target.
// There is no key parameter and no FBS writer; adding a target is a
// deliberate, pinned change (FB-E's FBS is the only planned third one).
template<class T, uint32_t KEY> struct WriteTarget {
  static constexpr bool allowed = false;
};
template<> struct WriteTarget<FailbackProvisionV1, FAILBACK_PROVISION_KEY> {
  static constexpr bool allowed = true;
};
template<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {
  static constexpr bool allowed = true;
};

// One key: write, direct readback, health gate, classify. No retry, no
// loop, no commit call (a no-op in IDF 5.5.5).
template<class T, uint32_t KEY, class Nvs>
KeyOutcome write_one_(Nvs &nvs, const T &intended, const T &prior_bytes, PriorDesc prior, T &readback, KeyReport &rep) {
  static_assert(WriteTarget<T, KEY>::allowed,
                "ecco_fbdurable: write_one_ may target only (FailbackProvisionV1, FAILBACK_PROVISION_KEY) and "
                "(FallbackProfileV1, FALLBACK_PROFILE_KEY) - exclusivity pin X2");
  const uint32_t t0 = nvs.now_us();
  const int32_t err = nvs.handle() == 0 ? IDF_ERR_NVS_INVALID_HANDLE : nvs.set_blob(KEY, &intended, sizeof(T));
  rep.err = err;
  rep.rb_load = read_direct_t(nvs, KEY, readback, rep.rb_diag);
  const ReadbackClass rc = readback_class(rep.rb_load, rep.rb_diag.stored_len, records_equal(readback, intended), prior,
                                          records_equal(readback, prior_bytes));
  const bool healthy = storage_healthy(nvs);
  const KeyOutcome o = classify_key_outcome(classify_write_err(err), rc, healthy);
  if (o == KEY_UNKNOWN_REBOOT)
    s_write_latched = true;
  rep.rb_class = rc;
  rep.healthy_after = healthy ? 1 : 0;
  rep.outcome = o;
  rep.us = nvs.now_us() - t0;
  return o;
}

// The ONLY entry point that writes FB records. Witness FIRST, then the
// profile, and the profile only if the witness COMMITTED (PO12). Refusals
// (latched, invalid transition, handle 0, unhealthy store) write nothing.
template<class Nvs>
TxnOutcome commit_transition_t(Nvs &nvs, const FailbackProvisionV1 &w_new, const FailbackProvisionV1 &w_prior,
                               PriorDesc w_pd, const FallbackProfileV1 &p_new, const FallbackProfileV1 &p_prior,
                               PriorDesc p_pd, TxnResult &r) {
  r = TxnResult{};
  r.w.outcome = KEY_NOT_ATTEMPTED;
  r.p.outcome = KEY_NOT_ATTEMPTED;
  if (s_write_latched) {
    r.refusal = REFUSAL_LATCHED;
    return TXN_REFUSED_LATCHED;
  }
  if (!validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd)) {
    r.refusal = REFUSAL_INVALID_TRANSITION;
    return TXN_REFUSED_LATCHED;
  }
  if (nvs.handle() == 0) {
    r.refusal = REFUSAL_STORAGE_UNAVAILABLE;
    return TXN_REFUSED_LATCHED;
  }
  if (!storage_healthy(nvs)) {
    r.refusal = REFUSAL_STORAGE_UNHEALTHY;
    return TXN_REFUSED_LATCHED;
  }
  r.refusal = REFUSAL_NONE;
  const KeyOutcome ow = write_one_<FailbackProvisionV1, FAILBACK_PROVISION_KEY>(nvs, w_new, w_prior, w_pd, r.w_rb, r.w);
  if (ow == KEY_NOT_COMMITTED)
    return TXN_NOT_COMMITTED;  // nothing changed on flash
  if (ow != KEY_COMMITTED)
    return TXN_UNKNOWN_REBOOT;  // the profile is NOT attempted
  const KeyOutcome op = write_one_<FallbackProfileV1, FALLBACK_PROFILE_KEY>(nvs, p_new, p_prior, p_pd, r.p_rb, r.p);
  if (op == KEY_COMMITTED)
    return TXN_COMMITTED;
  if (op == KEY_NOT_COMMITTED) {
    r.witness_advanced = 1;  // FBW new, FBP old: PROFILE_STALE (INTERRUPTED) now
    return TXN_NOT_COMMITTED;
  }
  return TXN_UNKNOWN_REBOOT;
}

// RAM-mirror rule (PO5; S2 1.8): after COMMITTED / NOT_COMMITTED the mirror
// comes ONLY from the readbacks (the profile from its readback if it was
// attempted, else from the fresh prior read); after UNKNOWN_REBOOT or a
// refusal the pre-transaction values are kept. Never from the intended bytes.
struct MirrorRecords {
  FallbackProfileV1 p;
  FailbackProvisionV1 w;
  uint8_t p_load;
  uint8_t w_load;
};
constexpr MirrorRecords mirror_after(TxnOutcome o, const TxnResult &r, const FallbackProfileV1 &p_prior, uint8_t p_prior_load,
                                     const FailbackProvisionV1 &w_prior, uint8_t w_prior_load) {
  if (o == TXN_COMMITTED)
    return MirrorRecords{r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load};
  if (o == TXN_NOT_COMMITTED) {
    if (r.p.outcome != KEY_NOT_ATTEMPTED)
      return MirrorRecords{r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load};
    return MirrorRecords{p_prior, r.w_rb, p_prior_load, r.w.rb_load};
  }
  return MirrorRecords{p_prior, w_prior, p_prior_load, w_prior_load};
}

// ---------------------------------------------------------------------------
// Compile-time golden vectors (architecture 4.5). The offline suite parses
// these and re-derives every value from the Python mirror.
// ---------------------------------------------------------------------------
constexpr FallbackProfileV1 profile_with_generation(FallbackProfileV1 p, uint32_t g) {
  p.generation = g;
  return ecco_fallback::seal_profile(p);
}

// W-FIRST: the witness of a first SAVE of the FB-A golden payload at generation 1.
constexpr FailbackProvisionV1 GOLDEN_PROVISION_FIRST =
    make_provision(1u, profile_with_generation(ecco_fallback::GOLDEN_PROFILE_V1, 1u).binding, 0u, 0u,
                   FALLBACK_PROFILE_KEY, ecco_fallback::PROFILE_SCHEMA, PROV_OP_SAVE);
// W-INV: the witness of invalidating GOLDEN_PROFILE_V1 (g7 -> g8).
constexpr FailbackProvisionV1 GOLDEN_PROVISION_INV =
    make_provision(8u, ecco_fallback::invalidate_profile(ecco_fallback::GOLDEN_PROFILE_V1).binding, 7u,
                   ecco_fallback::GOLDEN_PROFILE_V1.binding, FALLBACK_PROFILE_KEY, ecco_fallback::PROFILE_SCHEMA,
                   PROV_OP_INVALIDATE);

static_assert(provision_binding(FailbackProvisionV1{}) == 0x1FDA24BEF28230CFULL, "FBW golden vector W-ZERO");
static_assert(provision_binding(decode_provision(ProvisionBytes{
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF})) ==
                  0x06E1F1CA2CBB0327ULL,
              "FBW golden vector W-FF");
static_assert(profile_with_generation(ecco_fallback::GOLDEN_PROFILE_V1, 1u).binding == 0xB74CE0FA6297474DULL,
              "FB-A golden payload at generation 1 (the W-FIRST hw_binding)");
static_assert(GOLDEN_PROVISION_FIRST.binding == 0xA8B8788B4C915BB6ULL, "FBW golden vector W-FIRST");
static_assert(GOLDEN_PROVISION_INV.binding == 0x9E8AEC8F7D7DF2D7ULL, "FBW golden vector W-INV");
static_assert(ecco_fallback::GOLDEN_PROFILE_V1.binding == 0xD852A4FA2DF7DBA3ULL &&
                  ecco_fallback::invalidate_profile(ecco_fallback::GOLDEN_PROFILE_V1).binding == 0xF49A36C9C9720301ULL,
              "the FNV-1a-64 replica reproduces FB-A's own golden vectors");
static_assert(records_equal(decode_provision(encode_provision(GOLDEN_PROVISION_INV)), GOLDEN_PROVISION_INV) &&
                  provision_binding(decode_provision(encode_provision(GOLDEN_PROVISION_INV))) == GOLDEN_PROVISION_INV.binding,
              "FBW encode/decode round trip");
static_assert(classify_witness(ecco_fallback::LOAD_OK, GOLDEN_PROVISION_FIRST) == W_VALID &&
                  classify_witness(ecco_fallback::LOAD_OK, GOLDEN_PROVISION_INV) == W_VALID,
              "both golden witnesses classify W_VALID");

// Witness golden cases. Each row: take encode_provision(base) (0 = FIRST,
// 1 = INV), overwrite the u16 (little-endian) at `off_a` with `val_a`, then
// at `off_b` with `val_b` (GOLDEN_NO_MUTATION = skip), decode, re-seal if
// `reseal`; then witness_defect() must be `defect` and classify_witness(load)
// `expected`. The u16 at offset 38 is (flags << 8) | last_op.
struct WitnessGoldenCase {
  uint8_t base;
  uint8_t load;
  uint8_t off_a;
  uint16_t val_a;
  uint8_t off_b;
  uint16_t val_b;
  uint8_t reseal;
  uint8_t defect;
  uint8_t expected;
};

// clang-format off
constexpr WitnessGoldenCase WITNESS_GOLDEN_CASES[] = {
  // load status first; the record is never inspected unless load == OK
  {0, ecco_fallback::LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_VALID},
  {1, ecco_fallback::LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_VALID},
  {1, ecco_fallback::LOAD_ABSENT, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_ABSENT},
  {1, ecco_fallback::LOAD_WRONG_SIZE, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_CORRUPT},
  {1, ecco_fallback::LOAD_READ_ERROR, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_UNREADABLE},
  {1, ecco_fallback::LOAD_STORAGE_UNAVAILABLE, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_UNREADABLE},
  {1, 5, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_UNREADABLE},
  {1, 255, 0xFF, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_NONE, W_UNREADABLE},
  {1, ecco_fallback::LOAD_ABSENT, 0, 0x0000, 2, 0x0000, 0, WIT_DEFECT_MAGIC, W_ABSENT},
  {1, ecco_fallback::LOAD_READ_ERROR, 0, 0x0000, 2, 0x0000, 0, WIT_DEFECT_MAGIC, W_UNREADABLE},
  {1, ecco_fallback::LOAD_WRONG_SIZE, 38, 0x0002, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_CORRUPT},
  // 1 magic ('ECFW' = 0x45434657: low u16 0x4657, high u16 0x4543)
  {1, ecco_fallback::LOAD_OK, 0, 0x4650, 0xFF, 0x0000, 1, WIT_DEFECT_MAGIC, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 2, 0x4544, 0xFF, 0x0000, 1, WIT_DEFECT_MAGIC, W_CORRUPT},
  // 2 schema (schema 2 under the v1 tag is corruption)
  {1, ecco_fallback::LOAD_OK, 4, 0x0000, 0xFF, 0x0000, 1, WIT_DEFECT_SCHEMA, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 4, 0x0002, 0xFF, 0x0000, 1, WIT_DEFECT_SCHEMA, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 4, 0xFFFF, 0xFF, 0x0000, 1, WIT_DEFECT_SCHEMA, W_CORRUPT},
  // 3 size
  {1, ecco_fallback::LOAD_OK, 6, 47, 0xFF, 0x0000, 1, WIT_DEFECT_SIZE, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 6, 49, 0xFF, 0x0000, 1, WIT_DEFECT_SIZE, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 6, 96, 0xFF, 0x0000, 1, WIT_DEFECT_SIZE, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 6, 0, 0xFF, 0x0000, 1, WIT_DEFECT_SIZE, W_CORRUPT},
  // 4 binding (NOT re-sealed)
  {1, ecco_fallback::LOAD_OK, 40, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 46, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 8, 0x0009, 0xFF, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 24, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  {0, ecco_fallback::LOAD_OK, 32, 0x0000, 0xFF, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  // 5 flags
  {1, ecco_fallback::LOAD_OK, 38, 0x0102, 0xFF, 0x0000, 1, WIT_DEFECT_FLAGS, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x8002, 0xFF, 0x0000, 1, WIT_DEFECT_FLAGS, W_CORRUPT},
  // 6 hw_generation == 0
  {1, ecco_fallback::LOAD_OK, 8, 0x0000, 10, 0x0000, 1, WIT_DEFECT_HW, W_CORRUPT},
  {0, ecco_fallback::LOAD_OK, 8, 0x0000, 0xFF, 0x0000, 1, WIT_DEFECT_HW, W_CORRUPT},
  // 7 prior: prior_generation >= hw_generation, or zero-ness mismatch with prior_binding
  {1, ecco_fallback::LOAD_OK, 12, 0x0008, 0xFF, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 12, 0x0009, 0xFF, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 12, 0x0000, 14, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {0, ecco_fallback::LOAD_OK, 12, 0x0001, 0xFF, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {0, ecco_fallback::LOAD_OK, 24, 0x0001, 0xFF, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 12, 0x0006, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},
  {1, ecco_fallback::LOAD_OK, 8, 0xFFFF, 10, 0xFFFF, 1, WIT_DEFECT_NONE, W_VALID},
  // 8 op
  {1, ecco_fallback::LOAD_OK, 38, 0x0000, 0xFF, 0x0000, 1, WIT_DEFECT_OP, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x0004, 0xFF, 0x0000, 1, WIT_DEFECT_OP, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x00FF, 0xFF, 0x0000, 1, WIT_DEFECT_OP, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x0001, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},
  {1, ecco_fallback::LOAD_OK, 38, 0x0003, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},
  // 9 tag (a non-zero foreign tag is a VALID witness; compose rule B9 handles it)
  {1, ecco_fallback::LOAD_OK, 32, 0x0000, 34, 0x0000, 1, WIT_DEFECT_TAG, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 32, 0x1234, 34, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},
  // 10 hw_record_schema (a non-zero foreign schema is VALID here; B9 handles it)
  {1, ecco_fallback::LOAD_OK, 36, 0x0000, 0xFF, 0x0000, 1, WIT_DEFECT_RECSCHEMA, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 36, 0x0002, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},
  // precedence between the rules (first failing rule wins)
  {1, ecco_fallback::LOAD_OK, 0, 0x0000, 4, 0x0002, 1, WIT_DEFECT_MAGIC, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 4, 0x0002, 6, 47, 1, WIT_DEFECT_SCHEMA, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 6, 47, 38, 0x0102, 0, WIT_DEFECT_SIZE, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x0102, 8, 0x0000, 0, WIT_DEFECT_BINDING, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x0102, 8, 0x0000, 1, WIT_DEFECT_FLAGS, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 8, 0x0000, 38, 0x0000, 1, WIT_DEFECT_HW, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 12, 0x0009, 38, 0x0000, 1, WIT_DEFECT_PRIOR, W_CORRUPT},
  {1, ecco_fallback::LOAD_OK, 38, 0x0000, 36, 0x0000, 1, WIT_DEFECT_OP, W_CORRUPT},
  // a tag with only its low half zeroed is non-zero (not TAG); the zero record schema then fails
  {1, ecco_fallback::LOAD_OK, 32, 0x0000, 36, 0x0000, 1, WIT_DEFECT_RECSCHEMA, W_CORRUPT},
};
// clang-format on

constexpr FailbackProvisionV1 witness_golden_base(uint8_t base) {
  return base == 0 ? GOLDEN_PROVISION_FIRST : GOLDEN_PROVISION_INV;
}

constexpr bool run_witness_golden_case(const WitnessGoldenCase &c) {
  ProvisionBytes b = encode_provision(witness_golden_base(c.base));
  if (c.off_a != ecco_fallback::GOLDEN_NO_MUTATION)
    ecco_fallback::put_le(b, c.off_a, c.val_a, 2);
  if (c.off_b != ecco_fallback::GOLDEN_NO_MUTATION)
    ecco_fallback::put_le(b, c.off_b, c.val_b, 2);
  FailbackProvisionV1 w = decode_provision(b);
  if (c.reseal)
    w = seal_provision(w);
  return witness_defect(w) == c.defect && classify_witness(c.load, w) == c.expected;
}

constexpr bool witness_golden_cases_hold() {
  for (const auto &c : WITNESS_GOLDEN_CASES) {
    if (!run_witness_golden_case(c))
      return false;
  }
  return true;
}
static_assert(witness_golden_cases_hold(), "FB-B0 witness classifier golden cases");

// Compose golden cases over named record variants. Profile variants:
//   0 GOLD7  FB-A GOLDEN_PROFILE_V1 (VALID, g7, binding G)
//   1 INV8   invalidate_profile(GOLD7) (INVALIDATED, g8)
//   2 DOM7   GOLD7 with 244 = 0, re-sealed (CORRUPT_DOMAIN, authentic g7)
//   3 BAD7   GOLD7 with a broken binding (CORRUPT; its generation is untrusted)
//   4 GOLD9  GOLD7 at generation 9, re-sealed
//   5 GOLD5  GOLD7 at generation 5, re-sealed
//   6 ALT7   GOLD7 with another captured_epoch, re-sealed (VALID, g7, binding != G)
//   7 ZERO   the all-zero record
// Witness variants (all V1 tag/schema unless stated; last_op SAVE unless stated):
//   0 HW7_G        hw 7 / G, prior 6 / 0x6666              (consistent with GOLD7)
//   1 HW7_X        hw 7 / 0x1234, prior 6 / 0x6666         (mismatch)
//   2 HW6          hw 6 / 0x5555, prior 5 / 0x4444         (lagging behind g7)
//   3 HW8_SAVE_P7  hw 8 / 0x8888, prior 7 / G              (GOLD7 was the interrupted prior)
//   4 HW9_P8       hw 9 / 0x9999, prior 8 / 0x8888         (rollback for g7)
//   5 FOREIGN_TAG  hw 7 / G, tag 0x12345678
//   6 FOREIGN_SCH  hw 7 / G, record schema 2
//   7 FOREIGN_LAG  hw 6 / 0x5555, tag 0x12345678           (g7 newer than the witness)
//   8 FIRST        W-FIRST: hw 1, prior 0 / 0, op SAVE
//   9 FIRST_INVOP  hw 1, prior 0 / 0, op INVALIDATE
//  10 H2_P0        hw 2 / 0x2222, prior 0 / 0, op SAVE     (interrupted save-after-loss, not B5)
//  11 INV          W-INV: hw 8 / INV8 binding, prior 7 / G, op INVALIDATE
//  12 HW7_DOM      hw 7 / DOM7 binding, prior 6 / 0x6666
//  13 BAD          W-INV with a broken binding (W_CORRUPT)
//  14 ZERO         the all-zero record
constexpr uint8_t PV_GOLD7 = 0, PV_INV8 = 1, PV_DOM7 = 2, PV_BAD7 = 3, PV_GOLD9 = 4, PV_GOLD5 = 5, PV_ALT7 = 6, PV_ZERO = 7;
constexpr uint8_t WV_HW7_G = 0, WV_HW7_X = 1, WV_HW6 = 2, WV_HW8_SAVE_P7 = 3, WV_HW9_P8 = 4, WV_FOREIGN_TAG = 5,
                  WV_FOREIGN_SCH = 6, WV_FOREIGN_LAG = 7, WV_FIRST = 8, WV_FIRST_INVOP = 9, WV_H2_P0 = 10, WV_INV = 11,
                  WV_HW7_DOM = 12, WV_BAD = 13, WV_ZERO = 14;

constexpr FallbackProfileV1 profile_variant(uint8_t v) {
  FallbackProfileV1 p = ecco_fallback::GOLDEN_PROFILE_V1;
  if (v == PV_INV8)
    return ecco_fallback::invalidate_profile(p);
  if (v == PV_DOM7) {
    p.reg244 = 0;
    return ecco_fallback::seal_profile(p);
  }
  if (v == PV_BAD7) {
    p.binding = p.binding + 1u;
    return p;
  }
  if (v == PV_GOLD9)
    return profile_with_generation(p, 9u);
  if (v == PV_GOLD5)
    return profile_with_generation(p, 5u);
  if (v == PV_ALT7) {
    p.captured_epoch = p.captured_epoch + 60u;
    return ecco_fallback::seal_profile(p);
  }
  if (v == PV_ZERO)
    return FallbackProfileV1{};
  return p;
}

constexpr FailbackProvisionV1 witness_variant(uint8_t v) {
  constexpr uint32_t K = FALLBACK_PROFILE_KEY;
  constexpr uint16_t S = ecco_fallback::PROFILE_SCHEMA;
  const uint64_t G = ecco_fallback::GOLDEN_PROFILE_V1.binding;
  if (v == WV_HW7_G)
    return make_provision(7u, G, 6u, 0x6666u, K, S, PROV_OP_SAVE);
  if (v == WV_HW7_X)
    return make_provision(7u, 0x1234u, 6u, 0x6666u, K, S, PROV_OP_SAVE);
  if (v == WV_HW6)
    return make_provision(6u, 0x5555u, 5u, 0x4444u, K, S, PROV_OP_SAVE);
  if (v == WV_HW8_SAVE_P7)
    return make_provision(8u, 0x8888u, 7u, G, K, S, PROV_OP_SAVE);
  if (v == WV_HW9_P8)
    return make_provision(9u, 0x9999u, 8u, 0x8888u, K, S, PROV_OP_SAVE);
  if (v == WV_FOREIGN_TAG)
    return make_provision(7u, G, 6u, 0x6666u, 0x12345678u, S, PROV_OP_SAVE);
  if (v == WV_FOREIGN_SCH)
    return make_provision(7u, G, 6u, 0x6666u, K, 2u, PROV_OP_SAVE);
  if (v == WV_FOREIGN_LAG)
    return make_provision(6u, 0x5555u, 5u, 0x4444u, 0x12345678u, S, PROV_OP_SAVE);
  if (v == WV_FIRST)
    return GOLDEN_PROVISION_FIRST;
  if (v == WV_FIRST_INVOP)
    return make_provision(1u, profile_with_generation(ecco_fallback::GOLDEN_PROFILE_V1, 1u).binding, 0u, 0u, K, S,
                          PROV_OP_INVALIDATE);
  if (v == WV_H2_P0)
    return make_provision(2u, 0x2222u, 0u, 0u, K, S, PROV_OP_SAVE);
  if (v == WV_INV)
    return GOLDEN_PROVISION_INV;
  if (v == WV_HW7_DOM)
    return make_provision(7u, profile_variant(PV_DOM7).binding, 6u, 0x6666u, K, S, PROV_OP_SAVE);
  if (v == WV_BAD) {
    FailbackProvisionV1 w = GOLDEN_PROVISION_INV;
    w.binding = w.binding + 1u;
    return w;
  }
  return FailbackProvisionV1{};
}

struct ComposeGoldenCase {
  uint8_t p_load;
  uint8_t p_variant;
  uint8_t w_load;
  uint8_t w_variant;
  uint8_t anomaly;
  uint8_t cls;
  uint8_t why;
  uint8_t rule;
};

// clang-format off
constexpr ComposeGoldenCase COMPOSE_GOLDEN_CASES[] = {
  // B1: this FBP read is unreadable (READ_ERROR, STORAGE_UNAVAILABLE, unknown load); B1 precedes B2
  {ecco_fallback::LOAD_READ_ERROR, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_UNREADABLE, WHY_PROFILE_READ, RULE_B1},
  {ecco_fallback::LOAD_STORAGE_UNAVAILABLE, PV_ZERO, ecco_fallback::LOAD_ABSENT, WV_ZERO, 0, EPC_UNREADABLE, WHY_PROFILE_READ, RULE_B1},
  {ecco_fallback::LOAD_READ_ERROR, PV_ZERO, ecco_fallback::LOAD_READ_ERROR, WV_ZERO, 0, EPC_UNREADABLE, WHY_PROFILE_READ, RULE_B1},
  {7, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_UNREADABLE, WHY_PROFILE_READ, RULE_B1},
  // B2: this FBW read is unreadable; B2 precedes B2a and B3
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_READ_ERROR, WV_ZERO, 0, EPC_UNREADABLE, WHY_WITNESS_READ, RULE_B2},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_STORAGE_UNAVAILABLE, WV_ZERO, 0, EPC_UNREADABLE, WHY_WITNESS_READ, RULE_B2},
  {ecco_fallback::LOAD_WRONG_SIZE, PV_ZERO, ecco_fallback::LOAD_READ_ERROR, WV_ZERO, 1, EPC_UNREADABLE, WHY_WITNESS_READ, RULE_B2},
  {ecco_fallback::LOAD_OK, PV_GOLD7, 5, WV_HW7_G, 0, EPC_UNREADABLE, WHY_WITNESS_READ, RULE_B2},
  // B2a: an EARLIER read anomaly this boot, whatever this read shows; precedes B3
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW7_G, 1, EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A},
  {ecco_fallback::LOAD_OK, PV_BAD7, ecco_fallback::LOAD_OK, WV_HW7_G, 2, EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_ABSENT, WV_ZERO, 4, EPC_UNREADABLE, WHY_READ_ANOMALY, RULE_B2A},
  // B3: structural CORRUPT (incl. WRONG_SIZE) precedes every witness relation
  {ecco_fallback::LOAD_WRONG_SIZE, PV_ZERO, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_CORRUPT, WHY_NONE, RULE_B3},
  {ecco_fallback::LOAD_OK, PV_BAD7, ecco_fallback::LOAD_ABSENT, WV_ZERO, 0, EPC_CORRUPT, WHY_NONE, RULE_B3},
  {ecco_fallback::LOAD_OK, PV_BAD7, ecco_fallback::LOAD_OK, WV_BAD, 0, EPC_CORRUPT, WHY_NONE, RULE_B3},
  {ecco_fallback::LOAD_OK, PV_BAD7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_CORRUPT, WHY_NONE, RULE_B3},
  // B4: both ABSENT (factory-fresh or wiped: cannot be told apart)
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_ABSENT, WV_ZERO, 0, EPC_NOT_CAPTURED, WHY_NONE, RULE_B4},
  // B5: first SAVE not confirmed (hw 1, prior 0, op SAVE)
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_FIRST, 0, EPC_PROFILE_LOST, WHY_FIRST_SAVE_UNCONFIRMED, RULE_B5},
  // B6: the profile existed (m7: an interrupted save-after-loss at hw 2 is NOT B5)
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_H2_P0, 0, EPC_PROFILE_LOST, WHY_NONE, RULE_B6},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_PROFILE_LOST, WHY_NONE, RULE_B6},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_FIRST_INVOP, 0, EPC_PROFILE_LOST, WHY_NONE, RULE_B6},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_INV, 0, EPC_PROFILE_LOST, WHY_NONE, RULE_B6},
  // B7: ABSENT with a corrupt witness (baseline unknown)
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_OK, WV_BAD, 0, EPC_PROFILE_LOST, WHY_LOST_WIT_CORRUPT, RULE_B7},
  {ecco_fallback::LOAD_ABSENT, PV_ZERO, ecco_fallback::LOAD_WRONG_SIZE, WV_ZERO, 0, EPC_PROFILE_LOST, WHY_LOST_WIT_CORRUPT, RULE_B7},
  // B8: a record NEWER than the witness (witness rollback / loss); B8 precedes B9
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW6, 0, EPC_VALID, WHY_WIT_LAGGING, RULE_B8},
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_FOREIGN_LAG, 0, EPC_VALID, WHY_WIT_LAGGING, RULE_B8},
  {ecco_fallback::LOAD_OK, PV_INV8, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_INVALIDATED, WHY_WIT_LAGGING, RULE_B8},
  {ecco_fallback::LOAD_OK, PV_GOLD9, ecco_fallback::LOAD_OK, WV_INV, 0, EPC_VALID, WHY_WIT_LAGGING, RULE_B8},
  // B9: the witness names another tag / schema: any v1 record is SUPERSEDED; precedes B10
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_FOREIGN_TAG, 0, EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9},
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_FOREIGN_SCH, 0, EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9},
  {ecco_fallback::LOAD_OK, PV_DOM7, ecco_fallback::LOAD_OK, WV_FOREIGN_TAG, 0, EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9},
  // B10: consistent (the only writer-usable relation)
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_VALID, WHY_NONE, RULE_B10},
  {ecco_fallback::LOAD_OK, PV_INV8, ecco_fallback::LOAD_OK, WV_INV, 0, EPC_INVALIDATED, WHY_NONE, RULE_B10},
  {ecco_fallback::LOAD_OK, PV_DOM7, ecco_fallback::LOAD_OK, WV_HW7_DOM, 0, EPC_CORRUPT_DOMAIN, WHY_NONE, RULE_B10},
  // B11: same generation, different binding
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW7_X, 0, EPC_PROFILE_STALE, WHY_MISMATCH, RULE_B11},
  {ecco_fallback::LOAD_OK, PV_ALT7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_PROFILE_STALE, WHY_MISMATCH, RULE_B11},
  {ecco_fallback::LOAD_OK, PV_DOM7, ecco_fallback::LOAD_OK, WV_HW7_G, 0, EPC_PROFILE_STALE, WHY_MISMATCH, RULE_B11},
  // B12: the stored record is exactly the prior of an interrupted (or reverted) transition
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW8_SAVE_P7, 0, EPC_PROFILE_STALE, WHY_INTERRUPTED, RULE_B12},
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_INV, 0, EPC_PROFILE_STALE, WHY_INTERRUPTED, RULE_B12},
  // B13: an older record that is not the named prior
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW9_P8, 0, EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13},
  {ecco_fallback::LOAD_OK, PV_GOLD5, ecco_fallback::LOAD_OK, WV_HW8_SAVE_P7, 0, EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13},
  {ecco_fallback::LOAD_OK, PV_ALT7, ecco_fallback::LOAD_OK, WV_HW8_SAVE_P7, 0, EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13},
  {ecco_fallback::LOAD_OK, PV_INV8, ecco_fallback::LOAD_OK, WV_HW9_P8, 0, EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13},
  // B14 / B15: witness missing / corrupt - the class survives, the relation is flagged
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_ABSENT, WV_ZERO, 0, EPC_VALID, WHY_WIT_MISSING, RULE_B14},
  {ecco_fallback::LOAD_OK, PV_DOM7, ecco_fallback::LOAD_ABSENT, WV_ZERO, 0, EPC_CORRUPT_DOMAIN, WHY_WIT_MISSING, RULE_B14},
  {ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_BAD, 0, EPC_VALID, WHY_WIT_CORRUPT, RULE_B15},
  {ecco_fallback::LOAD_OK, PV_INV8, ecco_fallback::LOAD_WRONG_SIZE, WV_ZERO, 0, EPC_INVALIDATED, WHY_WIT_CORRUPT, RULE_B15},
};
// clang-format on

constexpr bool run_compose_golden_case(const ComposeGoldenCase &c) {
  const EffectiveProfile e = compose_profile_class(c.p_load, profile_variant(c.p_variant), c.w_load,
                                                   witness_variant(c.w_variant), c.anomaly);
  return e.cls == c.cls && e.why == c.why && e.rule == c.rule;
}

constexpr bool compose_golden_cases_hold() {
  for (const auto &c : COMPOSE_GOLDEN_CASES) {
    if (!run_compose_golden_case(c))
      return false;
  }
  return true;
}
static_assert(compose_golden_cases_hold(), "FB-B0 compose_profile_class golden cases (B1-B15, B2a)");

// Writer-usable: VALID with a consistent witness only.
static_assert(profile_writer_usable(EPC_VALID, WHY_NONE) && !profile_writer_usable(EPC_VALID, WHY_WIT_LAGGING) &&
                  !profile_writer_usable(EPC_VALID, WHY_WIT_MISSING) && !profile_writer_usable(EPC_VALID, WHY_WIT_CORRUPT) &&
                  !profile_writer_usable(EPC_INVALIDATED, WHY_NONE) && !profile_writer_usable(EPC_PROFILE_STALE, WHY_NONE) &&
                  !profile_writer_usable(EPC_SAVE_UNCONFIRMED, WHY_NONE) && !profile_writer_usable(EPC_UNREADABLE, WHY_NONE),
              "FB-B0: only VALID && WHY_NONE is writer-usable");

// Generation: never backwards after a loss; never wraps.
static_assert(save_generation_base(ecco_fallback::PROFILE_NOT_CAPTURED, 0u, W_ABSENT, 0u, 0u) == 0u &&
                  save_generation_base(ecco_fallback::PROFILE_VALID, 7u, W_VALID, 7u, 0u) == 7u &&
                  save_generation_base(ecco_fallback::PROFILE_NOT_CAPTURED, 0u, W_VALID, 12u, 0u) == 12u &&
                  save_generation_base(ecco_fallback::PROFILE_CORRUPT, 99u, W_VALID, 12u, 0u) == 12u &&
                  save_generation_base(ecco_fallback::PROFILE_CORRUPT, 99u, W_CORRUPT, 12u, 0u) == 0u &&
                  save_generation_base(ecco_fallback::PROFILE_VALID, 7u, W_CORRUPT, 12u, 0u) == 7u &&
                  save_generation_base(ecco_fallback::PROFILE_NOT_CAPTURED, 0u, W_ABSENT, 0u, 5u) == 5u &&
                  !save_generation_available(GENERATION_MAX) && save_generation_available(GENERATION_MAX - 1u),
              "FB-B0 SAVE generation base = max(authentic g, W_VALID hw, seen)");
static_assert(invalidate_generation_permitted(7u, W_VALID, 7u, 7u) && !invalidate_generation_permitted(7u, W_VALID, 8u, 0u) &&
                  !invalidate_generation_permitted(7u, W_ABSENT, 0u, 8u) && !invalidate_generation_permitted(GENERATION_MAX, W_ABSENT, 0u, 0u) &&
                  invalidate_generation_permitted(GENERATION_MAX - 1u, W_VALID, GENERATION_MAX - 1u, 0u),
              "FB-B0 INVALIDATE requires g < max and g + 1 > max(hw, seen)");

}  // namespace ecco_fbdurable
