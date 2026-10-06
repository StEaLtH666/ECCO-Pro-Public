#pragma once

// FB-A: Fallback Profile V1 and Failback State V1 - DATA CONTRACTS ONLY.
//
// This header freezes the two durable record layouts, their FNV-1a-64
// bindings, the V1 register classification and context-compare granularity,
// the V1 domain rules, the numeric state/reason/result codes and two pure
// record classifiers, before any Fallback behaviour exists. It is
// deliberately STANDALONE and BEHAVIOUR-FREE:
//   - it includes only standard headers (no ESPHome, storage or other ECCO
//     header) and is included by NO production source: it is not listed in
//     the firmware's `esphome: includes:`;
//   - no durable storage access, no inverter bus access, no entity
//     references, no globals, no API action, nothing that runs at
//     static-init time;
//   - everything is constexpr. The static_asserts at the bottom are evaluated
//     by registry/tests/test_fallback_profile_host_compile.py (host C++
//     compile, -fsyntax-only -Wall -Werror) and re-derived from the Python
//     mirror by registry/tests/test_fallback_profile_schema.py.
// See docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md Addendum B, which
// records where this V1 contract supersedes the section 4-8 draft.
//
// Offline mirror: registry/fallback_profile.py (byte-for-byte).

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace ecco_fallback {

// The bindings are defined over the STORED bytes of each record, produced
// field by field, little-endian, by the constexpr encoders below (never by
// hashing the in-memory struct). On a little-endian target those bytes are
// also exactly the in-memory record.
static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "ecco_fallback records assume a little-endian target");

// ---------------------------------------------------------------------------
// Hashes: two DIFFERENT algorithms, never to be confused.
//   FNV-1a-64 (xor, then multiply): the records' content bindings. Same
//     canonical constants as ecco_recovery_evidence.h (the offline suite pins
//     that; this header deliberately includes no other ECCO header).
//   FNV-1 32-bit (multiply, then xor): esphome::fnv1_hash(), which
//     ecco_durable::key_for() uses to turn a tag into a preference key.
//     tag_key_fnv1_32() below is a constexpr replica used only to pin keys.
// ---------------------------------------------------------------------------
constexpr uint64_t FNV1A64_OFFSET_BASIS = 0xCBF29CE484222325ULL;
constexpr uint64_t FNV1A64_PRIME = 0x100000001B3ULL;
constexpr uint32_t FNV1_32_OFFSET_BASIS = 0x811C9DC5u;
constexpr uint32_t FNV1_32_PRIME = 0x01000193u;

constexpr uint64_t fnv1a64_step(uint64_t hash, uint8_t byte) { return (hash ^ byte) * FNV1A64_PRIME; }

// Hashes a string literal's characters; its terminating NUL is NOT hashed.
template<size_t N> constexpr uint64_t fnv1a64_literal(uint64_t hash, const char (&s)[N]) {
  for (size_t i = 0; i + 1 < N; i++)
    hash = fnv1a64_step(hash, (uint8_t) s[i]);
  return hash;
}

constexpr uint32_t tag_key_fnv1_32(const char *tag) {
  uint32_t hash = FNV1_32_OFFSET_BASIS;
  for (; *tag != '\0'; tag++) {
    hash *= FNV1_32_PRIME;
    hash ^= (uint8_t) *tag;
  }
  return hash;
}

// Known-answer vectors for both algorithms.
static_assert(fnv1a64_literal(FNV1A64_OFFSET_BASIS, "") == 0xCBF29CE484222325ULL, "FNV-1a-64 known answer ('')");
static_assert(fnv1a64_literal(FNV1A64_OFFSET_BASIS, "a") == 0xAF63DC4C8601EC8CULL, "FNV-1a-64 known answer ('a')");
static_assert(fnv1a64_literal(FNV1A64_OFFSET_BASIS, "foobar") == 0x85944171F73967E8ULL, "FNV-1a-64 known answer ('foobar')");
static_assert(tag_key_fnv1_32("") == 0x811C9DC5u, "FNV-1 32 known answer ('')");
static_assert(tag_key_fnv1_32("a") == 0x050C5D7Eu, "FNV-1 32 known answer ('a')");
static_assert(tag_key_fnv1_32("foobar") == 0x31F0B262u, "FNV-1 32 known answer ('foobar')");

// ---------------------------------------------------------------------------
// Declared schema tags. NOT active durable keys: no firmware call site
// commits or loads either tag in FB-A, and they are not declared in
// ecco_durable_snapshot.h, whose active-tag set is unchanged. The offline
// suite checks their preference keys collide with no existing, retired or
// documented prospective tag.
// ---------------------------------------------------------------------------
constexpr char FALLBACK_PROFILE_TAG[] = "ecco_fallback_profile_v1";
constexpr char FAILBACK_STATE_TAG[] = "ecco_failback_state_v1";
static_assert(tag_key_fnv1_32(FALLBACK_PROFILE_TAG) == 0x5FEE6196u, "FB-A preference key: ecco_fallback_profile_v1");
static_assert(tag_key_fnv1_32(FAILBACK_STATE_TAG) == 0x808485C3u, "FB-A preference key: ecco_failback_state_v1");

// ---------------------------------------------------------------------------
// V1 register classification and context-compare granularity
// ---------------------------------------------------------------------------
//   E1    eventually writable by a future Fallback apply:
//           244 (restricted: see reg244_write_permitted()), 256-261,
//           268-273, 274-279 bits 0-1 only.
//   CTX   compared only, NEVER written:
//           232 bit 0 only (bits 1-15 informational), 243 full word,
//           248 bit 0 only (bits 1-15 informational), 250-255 full word.
//   INFO  captured and reported only: 230, 245, 247. (230 is INFO, not E1:
//         this intentionally supersedes the architecture draft's section 4.2.)
//   EXCLUDED  everything else, explicitly including 22-24, 246, 249 and
//           262-267.
// register_class_mask() is the set of bits the class applies to (for CTX:
// the bits a context comparison compares). EXCLUDED has mask 0.
enum RegisterClass : uint8_t {
  REG_EXCLUDED = 0,
  REG_E1 = 1,
  REG_CTX = 2,
  REG_INFO = 3,
};

constexpr RegisterClass register_class(uint16_t addr) {
  if (addr == 244 || (addr >= 256 && addr <= 261) || (addr >= 268 && addr <= 279))
    return REG_E1;
  if (addr == 232 || addr == 243 || addr == 248 || (addr >= 250 && addr <= 255))
    return REG_CTX;
  if (addr == 230 || addr == 245 || addr == 247)
    return REG_INFO;
  return REG_EXCLUDED;
}

constexpr uint16_t REG232_CTX_MASK = 0x0001;
constexpr uint16_t REG248_CTX_MASK = 0x0001;
constexpr uint16_t SLOT_SOURCE_BITS_MASK = 0x0003;  // 274-279: only bits 0-1 are E1

constexpr uint16_t register_class_mask(uint16_t addr) {
  if (register_class(addr) == REG_EXCLUDED)
    return 0;
  if (addr == 232)
    return REG232_CTX_MASK;
  if (addr == 248)
    return REG248_CTX_MASK;
  if (addr >= 274 && addr <= 279)
    return SLOT_SOURCE_BITS_MASK;
  return 0xFFFF;
}

// A CTX register matches when its compared bits are equal. (Only meaningful
// for REG_CTX addresses; nothing calls it in FB-A.)
constexpr bool ctx_matches(uint16_t addr, uint16_t profile_value, uint16_t live_value) {
  return register_class(addr) == REG_CTX &&
         (profile_value & register_class_mask(addr)) == (live_value & register_class_mask(addr));
}

// ---------------------------------------------------------------------------
// V1 domain rules - SCHEMA constants, never a runtime/site value
// ---------------------------------------------------------------------------
//   244      exactly 2 (Zero Export). A future Fallback may only ever write
//            244 0 -> 2, never 2 -> 0; a live 244 = 1 is unsupported and must
//            block (reg244_write_permitted() is false for everything but 0 -> 2).
//   256-261  V1_TOU_POWER_MIN_W .. V1_TOU_POWER_MAX_W (500..8000). This is a
//            schema bound, not ${ecco_inverter_tou_power_ceiling_w}: if a site
//            later lowers its configured ceiling, that must be an apply-time
//            BLOCKED (FAILBACK_RESULT_BLOCKED_SITE_CEILING), never a stored
//            profile silently turning from VALID into CORRUPT_DOMAIN. The
//            offline suite pins that 8000 currently equals the configured
//            ceiling.
//   268-273  0..SOC_MAX.
//   274-279  bits 0-1 in {0,1}; bits 2-15 zero - i.e. the word is 0 or 1.
//   CTX / INFO fields are never domain-checked by the classifiers here;
//   capture-time checks (e.g. HHMM slot times) belong to FB-B.
constexpr uint16_t REG244_PROFILE_REQUIRED = 2;
constexpr uint16_t V1_TOU_POWER_MIN_W = 500;
constexpr uint16_t V1_TOU_POWER_MAX_W = 8000;
constexpr uint16_t SOC_MAX = 100;

constexpr bool reg244_domain_valid(uint16_t v) { return v == REG244_PROFILE_REQUIRED; }
constexpr bool tou_power_domain_valid(uint16_t v) { return v >= V1_TOU_POWER_MIN_W && v <= V1_TOU_POWER_MAX_W; }
constexpr bool soc_domain_valid(uint16_t v) { return v <= SOC_MAX; }
constexpr bool slot_source_domain_valid(uint16_t v) {
  return (v & (uint16_t) ~SLOT_SOURCE_BITS_MASK) == 0 && (v & SLOT_SOURCE_BITS_MASK) <= 1;
}
// A FROM snapshot of live 244 taken before an apply: 0 or 2 (a live 1 blocks
// before any commit, so it can never be captured as FROM).
constexpr bool from_244_domain_valid(uint16_t v) { return v == 0 || v == REG244_PROFILE_REQUIRED; }
constexpr bool reg244_write_permitted(uint16_t live, uint16_t target) {
  return live == 0 && target == REG244_PROFILE_REQUIRED;
}

// ---------------------------------------------------------------------------
// Load result - the LOCAL enum both pure classifiers take, so FB-A does not
// depend on ecco_durable's production I/O. 0..3 deliberately share their
// numbers with ecco_durable::LoadStatus (SG-06); STORAGE_UNAVAILABLE is the
// "NVS handle unusable" outcome of the architecture's section 8.5.
// ---------------------------------------------------------------------------
enum RecordLoad : uint8_t {
  LOAD_OK = 0,
  LOAD_ABSENT = 1,               // proven absent (ESP_ERR_NVS_NOT_FOUND only)
  LOAD_WRONG_SIZE = 2,           // something is stored under the tag, but not this record's size
  LOAD_READ_ERROR = 3,           // existence UNKNOWN
  LOAD_STORAGE_UNAVAILABLE = 4,  // existence UNKNOWN
};

// ---------------------------------------------------------------------------
// FallbackProfileV1 - 96 bytes, explicit layout, no implicit padding
// ---------------------------------------------------------------------------
// Generation rules:
//   - generation 0 is CORRUPT; every valid present profile has generation >= 1;
//   - every durable profile commit (CAPTURE or INVALIDATE) strictly increases
//     it (profile_generation_advances());
//   - it is ONE logical counter shared across schema versions: a future
//     schema continues from the highest generation ever committed.
// INVALIDATE preserves the captured payload verbatim and changes only
// generation (+1), the INVALIDATED flag and, accordingly, the binding
// (invalidate_profile()). INVALIDATED is one-way for that record generation:
// only a fresh CAPTURE creates a VALID profile again.
constexpr uint32_t PROFILE_MAGIC = 0x45434650u;  // 'ECFP'
constexpr uint16_t PROFILE_SCHEMA = 1;
constexpr uint16_t PROFILE_SIZE = 96;
constexpr size_t PROFILE_BOUND_BYTES = 88;  // binding covers stored bytes [0, 88)
constexpr uint16_t PROFILE_FLAG_INVALIDATED = 0x0001;
constexpr uint16_t PROFILE_KNOWN_FLAGS = PROFILE_FLAG_INVALIDATED;  // bits 1-15 must be zero

struct FallbackProfileV1 {
  uint32_t magic;           // 0   PROFILE_MAGIC
  uint16_t schema;          // 4   PROFILE_SCHEMA
  uint16_t size;            // 6   PROFILE_SIZE
  uint32_t generation;      // 8   >= 1
  uint32_t captured_epoch;  // 12  0 if the clock was invalid at capture
  uint16_t flags;           // 16  bit0 INVALIDATED
  uint16_t reg244;          // 18  E1
  uint16_t reg256_261[6];   // 20  E1
  uint16_t reg268_273[6];   // 32  E1
  uint16_t reg274_279[6];   // 44  E1 (bits 0-1)
  uint16_t reg232;          // 56  CTX (bit 0)
  uint16_t reg243;          // 58  CTX
  uint16_t reg248;          // 60  CTX (bit 0)
  uint16_t reg250_255[6];   // 62  CTX
  uint16_t reg230;          // 74  INFO
  uint16_t reg245;          // 76  INFO
  uint16_t reg247;          // 78  INFO
  uint32_t reserved0;       // 80  must be 0
  uint32_t reserved1;       // 84  must be 0
  uint64_t binding;         // 88  profile_binding()
};
static_assert(sizeof(FallbackProfileV1) == 96, "FallbackProfileV1 must be exactly 96 bytes");
static_assert(offsetof(FallbackProfileV1, magic) == 0 && offsetof(FallbackProfileV1, schema) == 4 &&
                  offsetof(FallbackProfileV1, size) == 6 && offsetof(FallbackProfileV1, generation) == 8 &&
                  offsetof(FallbackProfileV1, captured_epoch) == 12 && offsetof(FallbackProfileV1, flags) == 16 &&
                  offsetof(FallbackProfileV1, reg244) == 18 && offsetof(FallbackProfileV1, reg256_261) == 20 &&
                  offsetof(FallbackProfileV1, reg268_273) == 32 && offsetof(FallbackProfileV1, reg274_279) == 44 &&
                  offsetof(FallbackProfileV1, reg232) == 56 && offsetof(FallbackProfileV1, reg243) == 58 &&
                  offsetof(FallbackProfileV1, reg248) == 60 && offsetof(FallbackProfileV1, reg250_255) == 62 &&
                  offsetof(FallbackProfileV1, reg230) == 74 && offsetof(FallbackProfileV1, reg245) == 76 &&
                  offsetof(FallbackProfileV1, reg247) == 78 && offsetof(FallbackProfileV1, reserved0) == 80 &&
                  offsetof(FallbackProfileV1, reserved1) == 84 && offsetof(FallbackProfileV1, binding) == 88,
              "FallbackProfileV1 field offsets");
static_assert(std::is_trivially_copyable<FallbackProfileV1>::value, "ecco_durable record must be trivially copyable");
static_assert(std::is_standard_layout<FallbackProfileV1>::value, "FallbackProfileV1 must be standard layout");

// ---------------------------------------------------------------------------
// FailbackStateV1 - 80 bytes, explicit layout, no implicit padding
// ---------------------------------------------------------------------------
constexpr uint32_t FAILBACK_MAGIC = 0x45434642u;  // 'ECFB'
constexpr uint16_t FAILBACK_SCHEMA = 1;
constexpr uint16_t FAILBACK_SIZE = 80;
constexpr size_t FAILBACK_BOUND_BYTES = 72;  // binding covers stored bytes [0, 72)

// Durable codes: numerically pinned, never implicit. Any other value is CORRUPT.
enum FailbackState : uint8_t {
  FAILBACK_CLEAR = 0,
  FAILBACK_PREEMPT_REQUIRED = 1,
  FAILBACK_APPLY_IN_PROGRESS = 2,
  FAILBACK_LATCHED_COMPLETE = 3,
  FAILBACK_BLOCKED = 4,
};

enum FailbackReason : uint8_t {
  FAILBACK_REASON_NONE = 0,              // only in CLEAR
  FAILBACK_REASON_SUPERVISION_LOST = 1,  // automatic, on confirmed loss of HA supervision
  FAILBACK_REASON_OPERATOR_APPLY = 2,    // operator-initiated manual profile apply (PR D)
};
constexpr uint8_t FAILBACK_REASON_MAX = FAILBACK_REASON_OPERATOR_APPLY;

enum FailbackResult : uint8_t {
  FAILBACK_RESULT_NONE = 0,  // CLEAR, PREEMPT_REQUIRED, APPLY_IN_PROGRESS
  // LATCHED_COMPLETE results
  FAILBACK_RESULT_PREEMPTED_ONLY = 1,
  FAILBACK_RESULT_PREEMPTED_NO_PROFILE = 2,
  FAILBACK_RESULT_ALREADY_AT_PROFILE = 3,
  FAILBACK_RESULT_APPLIED_VERIFIED = 4,
  // BLOCKED results
  FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED = 5,
  FAILBACK_RESULT_BLOCKED_MARKER_DIVERGENCE = 6,
  FAILBACK_RESULT_BLOCKED_PROFILE_UNAVAILABLE = 7,
  FAILBACK_RESULT_BLOCKED_CONTEXT_MISMATCH = 8,
  FAILBACK_RESULT_BLOCKED_LIVE_OUT_OF_DOMAIN = 9,
  FAILBACK_RESULT_BLOCKED_SITE_CEILING = 10,
  FAILBACK_RESULT_BLOCKED_APPLY_FAILED = 11,
};
constexpr uint8_t FAILBACK_RESULT_MAX = FAILBACK_RESULT_BLOCKED_APPLY_FAILED;

// Flags.
//   lease_preempted         the event pre-empted at least one lease.
//   apply_committed         set in the SAME durable commit that enters
//                           APPLY_IN_PROGRESS and stores from_*, BEFORE any
//                           Fallback register write. Once set for an event,
//                           no retry may recapture or rewrite FROM
//                           (failback_from_capture_permitted()); it is
//                           cleared only by the terminal transition to CLEAR.
//   divergence_reboot_used  the one quiescent divergence reboot was spent.
constexpr uint8_t FAILBACK_FLAG_LEASE_PREEMPTED = 0x01;
constexpr uint8_t FAILBACK_FLAG_APPLY_COMMITTED = 0x02;
constexpr uint8_t FAILBACK_FLAG_DIVERGENCE_REBOOT_USED = 0x04;
constexpr uint8_t FAILBACK_KNOWN_FLAGS = FAILBACK_FLAG_LEASE_PREEMPTED | FAILBACK_FLAG_APPLY_COMMITTED |
                                         FAILBACK_FLAG_DIVERGENCE_REBOOT_USED;  // bits 3-7 must be zero

struct FailbackStateV1 {
  uint32_t magic;               // 0   FAILBACK_MAGIC
  uint16_t schema;              // 4   FAILBACK_SCHEMA
  uint16_t size;                // 6   FAILBACK_SIZE
  uint8_t state;                // 8   FailbackState
  uint8_t reason;               // 9   FailbackReason
  uint8_t result;               // 10  FailbackResult
  uint8_t flags;                // 11  FAILBACK_FLAG_*
  uint32_t event_seq;           // 12  monotonic episode counter; preserved by CLEAR
  uint32_t event_epoch;         // 16
  uint32_t profile_generation;  // 20  0 iff no profile is bound
  uint8_t apply_attempts;       // 24
  uint8_t verify_mismatches;    // 25
  uint16_t from_244;            // 26  FROM = live values stored by the apply_committed commit
  uint16_t from_256_261[6];     // 28
  uint16_t from_268_279[12];    // 40
  uint64_t profile_binding;     // 64  0 iff no profile is bound
  uint64_t binding;             // 72  failback_binding()
};
static_assert(sizeof(FailbackStateV1) == 80, "FailbackStateV1 must be exactly 80 bytes");
static_assert(offsetof(FailbackStateV1, magic) == 0 && offsetof(FailbackStateV1, schema) == 4 &&
                  offsetof(FailbackStateV1, size) == 6 && offsetof(FailbackStateV1, state) == 8 &&
                  offsetof(FailbackStateV1, reason) == 9 && offsetof(FailbackStateV1, result) == 10 &&
                  offsetof(FailbackStateV1, flags) == 11 && offsetof(FailbackStateV1, event_seq) == 12 &&
                  offsetof(FailbackStateV1, event_epoch) == 16 && offsetof(FailbackStateV1, profile_generation) == 20 &&
                  offsetof(FailbackStateV1, apply_attempts) == 24 && offsetof(FailbackStateV1, verify_mismatches) == 25 &&
                  offsetof(FailbackStateV1, from_244) == 26 && offsetof(FailbackStateV1, from_256_261) == 28 &&
                  offsetof(FailbackStateV1, from_268_279) == 40 && offsetof(FailbackStateV1, profile_binding) == 64 &&
                  offsetof(FailbackStateV1, binding) == 72,
              "FailbackStateV1 field offsets");
static_assert(std::is_trivially_copyable<FailbackStateV1>::value, "ecco_durable record must be trivially copyable");
static_assert(std::is_standard_layout<FailbackStateV1>::value, "FailbackStateV1 must be standard layout");

// ---------------------------------------------------------------------------
// Field-by-field little-endian serialisation and FNV-1a-64 bindings
// ---------------------------------------------------------------------------
using ProfileBytes = std::array<uint8_t, PROFILE_SIZE>;
using FailbackBytes = std::array<uint8_t, FAILBACK_SIZE>;

template<size_t N> constexpr void put_le(std::array<uint8_t, N> &b, size_t off, uint64_t v, size_t width) {
  for (size_t i = 0; i < width; i++)
    b[off + i] = (uint8_t) ((v >> (8 * i)) & 0xFF);
}
template<size_t N> constexpr uint64_t get_le(const std::array<uint8_t, N> &b, size_t off, size_t width) {
  uint64_t v = 0;
  for (size_t i = 0; i < width; i++)
    v |= (uint64_t) b[off + i] << (8 * i);
  return v;
}

constexpr ProfileBytes encode_profile(const FallbackProfileV1 &p) {
  ProfileBytes b{};
  put_le(b, offsetof(FallbackProfileV1, magic), p.magic, 4);
  put_le(b, offsetof(FallbackProfileV1, schema), p.schema, 2);
  put_le(b, offsetof(FallbackProfileV1, size), p.size, 2);
  put_le(b, offsetof(FallbackProfileV1, generation), p.generation, 4);
  put_le(b, offsetof(FallbackProfileV1, captured_epoch), p.captured_epoch, 4);
  put_le(b, offsetof(FallbackProfileV1, flags), p.flags, 2);
  put_le(b, offsetof(FallbackProfileV1, reg244), p.reg244, 2);
  for (size_t i = 0; i < 6; i++) {
    put_le(b, offsetof(FallbackProfileV1, reg256_261) + 2 * i, p.reg256_261[i], 2);
    put_le(b, offsetof(FallbackProfileV1, reg268_273) + 2 * i, p.reg268_273[i], 2);
    put_le(b, offsetof(FallbackProfileV1, reg274_279) + 2 * i, p.reg274_279[i], 2);
    put_le(b, offsetof(FallbackProfileV1, reg250_255) + 2 * i, p.reg250_255[i], 2);
  }
  put_le(b, offsetof(FallbackProfileV1, reg232), p.reg232, 2);
  put_le(b, offsetof(FallbackProfileV1, reg243), p.reg243, 2);
  put_le(b, offsetof(FallbackProfileV1, reg248), p.reg248, 2);
  put_le(b, offsetof(FallbackProfileV1, reg230), p.reg230, 2);
  put_le(b, offsetof(FallbackProfileV1, reg245), p.reg245, 2);
  put_le(b, offsetof(FallbackProfileV1, reg247), p.reg247, 2);
  put_le(b, offsetof(FallbackProfileV1, reserved0), p.reserved0, 4);
  put_le(b, offsetof(FallbackProfileV1, reserved1), p.reserved1, 4);
  put_le(b, offsetof(FallbackProfileV1, binding), p.binding, 8);
  return b;
}

constexpr FallbackProfileV1 decode_profile(const ProfileBytes &b) {
  FallbackProfileV1 p{};
  p.magic = (uint32_t) get_le(b, offsetof(FallbackProfileV1, magic), 4);
  p.schema = (uint16_t) get_le(b, offsetof(FallbackProfileV1, schema), 2);
  p.size = (uint16_t) get_le(b, offsetof(FallbackProfileV1, size), 2);
  p.generation = (uint32_t) get_le(b, offsetof(FallbackProfileV1, generation), 4);
  p.captured_epoch = (uint32_t) get_le(b, offsetof(FallbackProfileV1, captured_epoch), 4);
  p.flags = (uint16_t) get_le(b, offsetof(FallbackProfileV1, flags), 2);
  p.reg244 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg244), 2);
  for (size_t i = 0; i < 6; i++) {
    p.reg256_261[i] = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg256_261) + 2 * i, 2);
    p.reg268_273[i] = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg268_273) + 2 * i, 2);
    p.reg274_279[i] = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg274_279) + 2 * i, 2);
    p.reg250_255[i] = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg250_255) + 2 * i, 2);
  }
  p.reg232 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg232), 2);
  p.reg243 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg243), 2);
  p.reg248 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg248), 2);
  p.reg230 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg230), 2);
  p.reg245 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg245), 2);
  p.reg247 = (uint16_t) get_le(b, offsetof(FallbackProfileV1, reg247), 2);
  p.reserved0 = (uint32_t) get_le(b, offsetof(FallbackProfileV1, reserved0), 4);
  p.reserved1 = (uint32_t) get_le(b, offsetof(FallbackProfileV1, reserved1), 4);
  p.binding = get_le(b, offsetof(FallbackProfileV1, binding), 8);
  return p;
}

constexpr FailbackBytes encode_failback(const FailbackStateV1 &s) {
  FailbackBytes b{};
  put_le(b, offsetof(FailbackStateV1, magic), s.magic, 4);
  put_le(b, offsetof(FailbackStateV1, schema), s.schema, 2);
  put_le(b, offsetof(FailbackStateV1, size), s.size, 2);
  put_le(b, offsetof(FailbackStateV1, state), s.state, 1);
  put_le(b, offsetof(FailbackStateV1, reason), s.reason, 1);
  put_le(b, offsetof(FailbackStateV1, result), s.result, 1);
  put_le(b, offsetof(FailbackStateV1, flags), s.flags, 1);
  put_le(b, offsetof(FailbackStateV1, event_seq), s.event_seq, 4);
  put_le(b, offsetof(FailbackStateV1, event_epoch), s.event_epoch, 4);
  put_le(b, offsetof(FailbackStateV1, profile_generation), s.profile_generation, 4);
  put_le(b, offsetof(FailbackStateV1, apply_attempts), s.apply_attempts, 1);
  put_le(b, offsetof(FailbackStateV1, verify_mismatches), s.verify_mismatches, 1);
  put_le(b, offsetof(FailbackStateV1, from_244), s.from_244, 2);
  for (size_t i = 0; i < 6; i++)
    put_le(b, offsetof(FailbackStateV1, from_256_261) + 2 * i, s.from_256_261[i], 2);
  for (size_t i = 0; i < 12; i++)
    put_le(b, offsetof(FailbackStateV1, from_268_279) + 2 * i, s.from_268_279[i], 2);
  put_le(b, offsetof(FailbackStateV1, profile_binding), s.profile_binding, 8);
  put_le(b, offsetof(FailbackStateV1, binding), s.binding, 8);
  return b;
}

constexpr FailbackStateV1 decode_failback(const FailbackBytes &b) {
  FailbackStateV1 s{};
  s.magic = (uint32_t) get_le(b, offsetof(FailbackStateV1, magic), 4);
  s.schema = (uint16_t) get_le(b, offsetof(FailbackStateV1, schema), 2);
  s.size = (uint16_t) get_le(b, offsetof(FailbackStateV1, size), 2);
  s.state = (uint8_t) get_le(b, offsetof(FailbackStateV1, state), 1);
  s.reason = (uint8_t) get_le(b, offsetof(FailbackStateV1, reason), 1);
  s.result = (uint8_t) get_le(b, offsetof(FailbackStateV1, result), 1);
  s.flags = (uint8_t) get_le(b, offsetof(FailbackStateV1, flags), 1);
  s.event_seq = (uint32_t) get_le(b, offsetof(FailbackStateV1, event_seq), 4);
  s.event_epoch = (uint32_t) get_le(b, offsetof(FailbackStateV1, event_epoch), 4);
  s.profile_generation = (uint32_t) get_le(b, offsetof(FailbackStateV1, profile_generation), 4);
  s.apply_attempts = (uint8_t) get_le(b, offsetof(FailbackStateV1, apply_attempts), 1);
  s.verify_mismatches = (uint8_t) get_le(b, offsetof(FailbackStateV1, verify_mismatches), 1);
  s.from_244 = (uint16_t) get_le(b, offsetof(FailbackStateV1, from_244), 2);
  for (size_t i = 0; i < 6; i++)
    s.from_256_261[i] = (uint16_t) get_le(b, offsetof(FailbackStateV1, from_256_261) + 2 * i, 2);
  for (size_t i = 0; i < 12; i++)
    s.from_268_279[i] = (uint16_t) get_le(b, offsetof(FailbackStateV1, from_268_279) + 2 * i, 2);
  s.profile_binding = get_le(b, offsetof(FailbackStateV1, profile_binding), 8);
  s.binding = get_le(b, offsetof(FailbackStateV1, binding), 8);
  return s;
}

// Binding domains: exactly these ASCII bytes; the NUL terminator is NOT hashed.
constexpr char PROFILE_BINDING_DOMAIN[] = "ECCO-FALLBACK-PROFILE-v1";
constexpr char FAILBACK_BINDING_DOMAIN[] = "ECCO-FAILBACK-STATE-v1";
static_assert(sizeof(PROFILE_BINDING_DOMAIN) - 1 == 24, "profile binding domain is 24 bytes, no NUL");
static_assert(sizeof(FAILBACK_BINDING_DOMAIN) - 1 == 22, "failback binding domain is 22 bytes, no NUL");

// FNV-1a-64(PROFILE_BINDING_DOMAIN || stored bytes [0, 88)).
constexpr uint64_t profile_binding(const FallbackProfileV1 &p) {
  const ProfileBytes b = encode_profile(p);
  uint64_t h = fnv1a64_literal(FNV1A64_OFFSET_BASIS, PROFILE_BINDING_DOMAIN);
  for (size_t i = 0; i < PROFILE_BOUND_BYTES; i++)
    h = fnv1a64_step(h, b[i]);
  return h;
}

// FNV-1a-64(FAILBACK_BINDING_DOMAIN || stored bytes [0, 72)).
constexpr uint64_t failback_binding(const FailbackStateV1 &s) {
  const FailbackBytes b = encode_failback(s);
  uint64_t h = fnv1a64_literal(FNV1A64_OFFSET_BASIS, FAILBACK_BINDING_DOMAIN);
  for (size_t i = 0; i < FAILBACK_BOUND_BYTES; i++)
    h = fnv1a64_step(h, b[i]);
  return h;
}

constexpr FallbackProfileV1 seal_profile(FallbackProfileV1 p) {
  p.binding = profile_binding(p);
  return p;
}
constexpr FailbackStateV1 seal_failback(FailbackStateV1 s) {
  s.binding = failback_binding(s);
  return s;
}

// ---------------------------------------------------------------------------
// Profile validation and classification
// ---------------------------------------------------------------------------
// The E1 domain. CTX and INFO fields are deliberately not constrained.
constexpr bool profile_domain_valid(const FallbackProfileV1 &p) {
  if (!reg244_domain_valid(p.reg244))
    return false;
  for (size_t i = 0; i < 6; i++) {
    if (!tou_power_domain_valid(p.reg256_261[i]) || !soc_domain_valid(p.reg268_273[i]) ||
        !slot_source_domain_valid(p.reg274_279[i]))
      return false;
  }
  return true;
}

// The FIRST failing rule, in the V1 precedence order.
enum ProfileDefect : uint8_t {
  PROFILE_DEFECT_NONE = 0,
  PROFILE_DEFECT_MAGIC = 1,
  PROFILE_DEFECT_SCHEMA = 2,  // schema != 1 under the v1 tag is corruption, never a migration
  PROFILE_DEFECT_SIZE = 3,
  PROFILE_DEFECT_BINDING = 4,
  PROFILE_DEFECT_RESERVED = 5,
  PROFILE_DEFECT_FLAGS = 6,
  PROFILE_DEFECT_GENERATION = 7,
  PROFILE_DEFECT_DOMAIN = 8,
};

constexpr ProfileDefect profile_defect(const FallbackProfileV1 &p) {
  if (p.magic != PROFILE_MAGIC)
    return PROFILE_DEFECT_MAGIC;
  if (p.schema != PROFILE_SCHEMA)
    return PROFILE_DEFECT_SCHEMA;
  if (p.size != PROFILE_SIZE)
    return PROFILE_DEFECT_SIZE;
  if (p.binding != profile_binding(p))
    return PROFILE_DEFECT_BINDING;
  if (p.reserved0 != 0 || p.reserved1 != 0)
    return PROFILE_DEFECT_RESERVED;
  if ((p.flags & (uint16_t) ~PROFILE_KNOWN_FLAGS) != 0)
    return PROFILE_DEFECT_FLAGS;
  if (p.generation == 0)
    return PROFILE_DEFECT_GENERATION;
  if (!profile_domain_valid(p))
    return PROFILE_DEFECT_DOMAIN;
  return PROFILE_DEFECT_NONE;
}

// 0 is UNREADABLE so a zero-initialised mirror never reads as VALID or NOT_CAPTURED.
enum ProfileClass : uint8_t {
  PROFILE_UNREADABLE = 0,
  PROFILE_NOT_CAPTURED = 1,
  PROFILE_CORRUPT = 2,
  PROFILE_CORRUPT_DOMAIN = 3,
  PROFILE_INVALIDATED = 4,
  PROFILE_VALID = 5,
};

// Load status first, and the record is never inspected unless load == OK:
//   ABSENT -> NOT_CAPTURED (the ONLY route to it); WRONG_SIZE -> CORRUPT;
//   READ_ERROR / STORAGE_UNAVAILABLE / any unknown value -> UNREADABLE.
// Then profile_defect(): magic, schema, size, binding, reserved, flags,
// generation -> CORRUPT; E1 domain -> CORRUPT_DOMAIN. Only a record with no
// defect can be INVALIDATED; otherwise VALID. Domain validation precedes
// INVALIDATED so an out-of-domain record never masquerades as a benign
// invalidation.
constexpr ProfileClass classify_profile(uint8_t load, const FallbackProfileV1 &p) {
  if (load == LOAD_ABSENT)
    return PROFILE_NOT_CAPTURED;
  if (load == LOAD_WRONG_SIZE)
    return PROFILE_CORRUPT;
  if (load != LOAD_OK)
    return PROFILE_UNREADABLE;
  const ProfileDefect d = profile_defect(p);
  if (d == PROFILE_DEFECT_DOMAIN)
    return PROFILE_CORRUPT_DOMAIN;
  if (d != PROFILE_DEFECT_NONE)
    return PROFILE_CORRUPT;
  if (p.flags & PROFILE_FLAG_INVALIDATED)
    return PROFILE_INVALIDATED;
  return PROFILE_VALID;
}

constexpr bool profile_generation_advances(uint32_t previous, uint32_t next) { return next > previous; }

constexpr bool profile_invalidate_permitted(const FallbackProfileV1 &p) {
  return classify_profile(LOAD_OK, p) == PROFILE_VALID && p.generation < 0xFFFFFFFFu;
}

// INVALIDATE: generation + 1, INVALIDATED set, re-bound; the payload is
// preserved verbatim. Callers must check profile_invalidate_permitted() first.
constexpr FallbackProfileV1 invalidate_profile(FallbackProfileV1 p) {
  p.generation = p.generation + 1;
  p.flags = (uint16_t) (p.flags | PROFILE_FLAG_INVALIDATED);
  return seal_profile(p);
}

// ---------------------------------------------------------------------------
// Failback record validation and classification
// ---------------------------------------------------------------------------
// CLEAR contract: a CLEAR record carries ONLY event_seq (the monotonic
// episode counter operator actions bind to). reason, result, flags,
// event_epoch, profile_generation, profile_binding, both counters and every
// from_* are zero; the last episode's outcome is not retained.
constexpr FailbackStateV1 failback_clear_record(uint32_t event_seq) {
  FailbackStateV1 s{};
  s.magic = FAILBACK_MAGIC;
  s.schema = FAILBACK_SCHEMA;
  s.size = FAILBACK_SIZE;
  s.state = FAILBACK_CLEAR;
  s.event_seq = event_seq;
  return seal_failback(s);
}

constexpr bool failback_from_all_zero(const FailbackStateV1 &s) {
  if (s.from_244 != 0)
    return false;
  for (size_t i = 0; i < 6; i++) {
    if (s.from_256_261[i] != 0)
      return false;
  }
  for (size_t i = 0; i < 12; i++) {
    if (s.from_268_279[i] != 0)
      return false;
  }
  return true;
}

// FROM values stored by the apply_committed commit: 244 in {0,2}, 256-261
// in 500..8000, 268-273 <= 100, 274-279 with no bit outside bit 0 set.
constexpr bool failback_from_domain_valid(const FailbackStateV1 &s) {
  if (!from_244_domain_valid(s.from_244))
    return false;
  for (size_t i = 0; i < 6; i++) {
    if (!tou_power_domain_valid(s.from_256_261[i]) || !soc_domain_valid(s.from_268_279[i]) ||
        !slot_source_domain_valid(s.from_268_279[6 + i]))
      return false;
  }
  return true;
}

constexpr bool failback_result_is_latched(uint8_t r) {
  return r >= FAILBACK_RESULT_PREEMPTED_ONLY && r <= FAILBACK_RESULT_APPLIED_VERIFIED;
}
constexpr bool failback_result_is_blocked(uint8_t r) {
  return r >= FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED && r <= FAILBACK_RESULT_BLOCKED_APPLY_FAILED;
}

// Cross-field invariants of a V1 failback record.
constexpr bool failback_invariants_hold(const FailbackStateV1 &s) {
  const bool committed = (s.flags & FAILBACK_FLAG_APPLY_COMMITTED) != 0;
  // profile_generation == 0 iff no profile is bound (profile_binding == 0).
  if ((s.profile_generation == 0) != (s.profile_binding == 0))
    return false;
  // All from_* are zero iff apply_committed is clear; when set, FROM is in domain
  // and a profile is bound.
  if (failback_from_all_zero(s) == committed)
    return false;
  if (committed && (!failback_from_domain_valid(s) || s.profile_generation == 0))
    return false;
  // Apply counters only exist after the apply_committed commit.
  if (!committed && (s.apply_attempts != 0 || s.verify_mismatches != 0))
    return false;
  switch (s.state) {
    case FAILBACK_CLEAR:
      return s.reason == FAILBACK_REASON_NONE && s.result == FAILBACK_RESULT_NONE && s.flags == 0 &&
             s.event_epoch == 0 && s.profile_generation == 0 && s.apply_attempts == 0 && s.verify_mismatches == 0;
    case FAILBACK_PREEMPT_REQUIRED:
      return s.reason != FAILBACK_REASON_NONE && s.event_seq != 0 && !committed && s.result == FAILBACK_RESULT_NONE;
    case FAILBACK_APPLY_IN_PROGRESS:
      return s.reason != FAILBACK_REASON_NONE && s.event_seq != 0 && committed && s.result == FAILBACK_RESULT_NONE;
    case FAILBACK_LATCHED_COMPLETE:
      return s.reason != FAILBACK_REASON_NONE && s.event_seq != 0 && failback_result_is_latched(s.result) &&
             committed == (s.result == FAILBACK_RESULT_APPLIED_VERIFIED);
    case FAILBACK_BLOCKED:
      return s.reason != FAILBACK_REASON_NONE && s.event_seq != 0 && failback_result_is_blocked(s.result);
    default:
      return false;
  }
}

// The FIRST failing rule, in precedence order.
enum FailbackDefect : uint8_t {
  FAILBACK_DEFECT_NONE = 0,
  FAILBACK_DEFECT_MAGIC = 1,
  FAILBACK_DEFECT_SCHEMA = 2,
  FAILBACK_DEFECT_SIZE = 3,
  FAILBACK_DEFECT_BINDING = 4,
  FAILBACK_DEFECT_FLAGS = 5,
  FAILBACK_DEFECT_STATE = 6,
  FAILBACK_DEFECT_REASON = 7,
  FAILBACK_DEFECT_RESULT = 8,
  FAILBACK_DEFECT_INVARIANT = 9,
};

constexpr FailbackDefect failback_defect(const FailbackStateV1 &s) {
  if (s.magic != FAILBACK_MAGIC)
    return FAILBACK_DEFECT_MAGIC;
  if (s.schema != FAILBACK_SCHEMA)
    return FAILBACK_DEFECT_SCHEMA;
  if (s.size != FAILBACK_SIZE)
    return FAILBACK_DEFECT_SIZE;
  if (s.binding != failback_binding(s))
    return FAILBACK_DEFECT_BINDING;
  if ((s.flags & (uint8_t) ~FAILBACK_KNOWN_FLAGS) != 0)
    return FAILBACK_DEFECT_FLAGS;
  if (s.state > FAILBACK_BLOCKED)
    return FAILBACK_DEFECT_STATE;
  if (s.reason > FAILBACK_REASON_MAX)
    return FAILBACK_DEFECT_REASON;
  if (s.result > FAILBACK_RESULT_MAX)
    return FAILBACK_DEFECT_RESULT;
  if (!failback_invariants_hold(s))
    return FAILBACK_DEFECT_INVARIANT;
  return FAILBACK_DEFECT_NONE;
}

enum FailbackRecordClass : uint8_t {
  FAILBACK_RECORD_UNREADABLE = 0,
  FAILBACK_RECORD_ABSENT = 1,  // distinct from a present, valid CLEAR record
  FAILBACK_RECORD_CORRUPT = 2,
  FAILBACK_RECORD_VALID = 3,
};

// Load status first (the record is never inspected unless load == OK), then
// failback_defect(). A VALID record's state is then read from the record.
constexpr FailbackRecordClass classify_failback(uint8_t load, const FailbackStateV1 &s) {
  if (load == LOAD_ABSENT)
    return FAILBACK_RECORD_ABSENT;
  if (load == LOAD_WRONG_SIZE)
    return FAILBACK_RECORD_CORRUPT;
  if (load != LOAD_OK)
    return FAILBACK_RECORD_UNREADABLE;
  return failback_defect(s) == FAILBACK_DEFECT_NONE ? FAILBACK_RECORD_VALID : FAILBACK_RECORD_CORRUPT;
}

// FROM may be captured only while apply_committed is clear.
constexpr bool failback_from_capture_permitted(const FailbackStateV1 &s) {
  return (s.flags & FAILBACK_FLAG_APPLY_COMMITTED) == 0;
}

// ---------------------------------------------------------------------------
// Whole-table digests (pinned below; mirrored by registry/fallback_profile.py)
// ---------------------------------------------------------------------------
constexpr char REGISTER_TABLE_DIGEST_DOMAIN[] = "ECCO-FALLBACK-REGISTER-CLASS-v1";
constexpr char DOMAIN_DIGEST_DOMAIN[] = "ECCO-FALLBACK-DOMAIN-v1";

// FNV-1a-64 over (class, mask lo, mask hi) for every u16 address.
constexpr uint64_t register_class_digest() {
  uint64_t h = fnv1a64_literal(FNV1A64_OFFSET_BASIS, REGISTER_TABLE_DIGEST_DOMAIN);
  for (uint32_t a = 0; a <= 0xFFFF; a++) {
    const uint16_t mask = register_class_mask((uint16_t) a);
    h = fnv1a64_step(h, (uint8_t) register_class((uint16_t) a));
    h = fnv1a64_step(h, (uint8_t) (mask & 0xFF));
    h = fnv1a64_step(h, (uint8_t) (mask >> 8));
  }
  return h;
}

enum DomainKind : uint8_t {
  DOMAIN_REG244 = 0,
  DOMAIN_TOU_POWER = 1,
  DOMAIN_SOC = 2,
  DOMAIN_SLOT_SOURCE = 3,
  DOMAIN_FROM_244 = 4,
};

constexpr bool domain_value_valid(uint8_t kind, uint16_t v) {
  return kind == DOMAIN_REG244        ? reg244_domain_valid(v)
         : kind == DOMAIN_TOU_POWER   ? tou_power_domain_valid(v)
         : kind == DOMAIN_SOC         ? soc_domain_valid(v)
         : kind == DOMAIN_SLOT_SOURCE ? slot_source_domain_valid(v)
         : kind == DOMAIN_FROM_244    ? from_244_domain_valid(v)
                                      : false;
}

// FNV-1a-64 over one validity byte (0/1) per u16 value 0..0xFFFF.
constexpr uint64_t domain_digest(uint8_t kind) {
  uint64_t h = fnv1a64_literal(FNV1A64_OFFSET_BASIS, DOMAIN_DIGEST_DOMAIN);
  for (uint32_t v = 0; v <= 0xFFFF; v++)
    h = fnv1a64_step(h, domain_value_valid(kind, (uint16_t) v) ? 1 : 0);
  return h;
}

// ---------------------------------------------------------------------------
// Compile-time golden vectors and golden-case tables. The offline suite
// parses these and re-derives every value from the Python mirror.
// ---------------------------------------------------------------------------

// GOLDEN_PROFILE_V1: a typical VALID profile.
constexpr FallbackProfileV1 GOLDEN_PROFILE_V1 = seal_profile(FallbackProfileV1{
    PROFILE_MAGIC, PROFILE_SCHEMA, PROFILE_SIZE, 7u, 1790000000u, 0x0000, 2,
    {8000, 500, 4000, 3000, 2000, 1000}, {100, 20, 0, 50, 100, 30}, {1, 0, 1, 0, 0, 1},
    0x0011, 1, 1, {0, 530, 1000, 1600, 2100, 2330}, 185, 8000, 1, 0u, 0u, 0});

// GOLDEN_FAILBACK_V1[]: one VALID record per shape.
//   [0] CLEAR (event_seq 42)
//   [1] PREEMPT_REQUIRED, lease pre-empted, profile bound
//   [2] APPLY_IN_PROGRESS, apply_committed, FROM stored, 1 attempt
//   [3] LATCHED_COMPLETE / APPLIED_VERIFIED
//   [4] BLOCKED / CONTEXT_MISMATCH before any apply commit
//   [5] BLOCKED / PROFILE_UNAVAILABLE with no profile bound
constexpr FailbackStateV1 GOLDEN_FAILBACK_V1[] = {
    failback_clear_record(42u),
    seal_failback(FailbackStateV1{FAILBACK_MAGIC, FAILBACK_SCHEMA, FAILBACK_SIZE, FAILBACK_PREEMPT_REQUIRED,
                                  FAILBACK_REASON_SUPERVISION_LOST, FAILBACK_RESULT_NONE, 0x01, 43u, 1790003600u, 7u, 0,
                                  0, 0, {0, 0, 0, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
                                  GOLDEN_PROFILE_V1.binding, 0}),
    seal_failback(FailbackStateV1{FAILBACK_MAGIC, FAILBACK_SCHEMA, FAILBACK_SIZE, FAILBACK_APPLY_IN_PROGRESS,
                                  FAILBACK_REASON_SUPERVISION_LOST, FAILBACK_RESULT_NONE, 0x03, 43u, 1790003600u, 7u, 1,
                                  0, 0, {3000, 3000, 3000, 3000, 3000, 3000}, {50, 50, 50, 50, 50, 50, 0, 1, 0, 1, 0, 1},
                                  GOLDEN_PROFILE_V1.binding, 0}),
    seal_failback(FailbackStateV1{FAILBACK_MAGIC, FAILBACK_SCHEMA, FAILBACK_SIZE, FAILBACK_LATCHED_COMPLETE,
                                  FAILBACK_REASON_SUPERVISION_LOST, FAILBACK_RESULT_APPLIED_VERIFIED, 0x03, 43u,
                                  1790003600u, 7u, 1, 0, 0, {3000, 3000, 3000, 3000, 3000, 3000},
                                  {50, 50, 50, 50, 50, 50, 0, 1, 0, 1, 0, 1}, GOLDEN_PROFILE_V1.binding, 0}),
    seal_failback(FailbackStateV1{FAILBACK_MAGIC, FAILBACK_SCHEMA, FAILBACK_SIZE, FAILBACK_BLOCKED,
                                  FAILBACK_REASON_SUPERVISION_LOST, FAILBACK_RESULT_BLOCKED_CONTEXT_MISMATCH, 0x01, 43u,
                                  1790003600u, 7u, 0, 0, 0, {0, 0, 0, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
                                  GOLDEN_PROFILE_V1.binding, 0}),
    seal_failback(FailbackStateV1{FAILBACK_MAGIC, FAILBACK_SCHEMA, FAILBACK_SIZE, FAILBACK_BLOCKED,
                                  FAILBACK_REASON_SUPERVISION_LOST, FAILBACK_RESULT_BLOCKED_PROFILE_UNAVAILABLE, 0x01,
                                  43u, 1790003600u, 0u, 0, 0, 0, {0, 0, 0, 0, 0, 0},
                                  {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}, 0u, 0}),
};

// Binding golden vectors.
static_assert(profile_binding(FallbackProfileV1{}) == 0xE791999218542996ULL, "FB-A profile binding: all-zero record");
static_assert(GOLDEN_PROFILE_V1.binding == 0xD852A4FA2DF7DBA3ULL, "FB-A profile binding: GOLDEN_PROFILE_V1");
static_assert(profile_binding(decode_profile(ProfileBytes{
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF})) ==
                  0x7AFF993D890619BEULL,
              "FB-A profile binding: all-0xFF record");
static_assert(invalidate_profile(GOLDEN_PROFILE_V1).binding == 0xF49A36C9C9720301ULL,
              "FB-A profile binding: GOLDEN_PROFILE_V1 invalidated");
static_assert(failback_binding(FailbackStateV1{}) == 0x361632E14E017175ULL, "FB-A failback binding: all-zero record");
static_assert(failback_binding(decode_failback(FailbackBytes{
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                  0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF})) ==
                  0xAB2995F5E9B16BADULL,
              "FB-A failback binding: all-0xFF record");
static_assert(GOLDEN_FAILBACK_V1[0].binding == 0xBA58658F8B00DC5AULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[0]");
static_assert(GOLDEN_FAILBACK_V1[1].binding == 0xC868ECA3DEF25B2FULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[1]");
static_assert(GOLDEN_FAILBACK_V1[2].binding == 0xD99E025FBCEE0D76ULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[2]");
static_assert(GOLDEN_FAILBACK_V1[3].binding == 0xF688BEFF3990B9CBULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[3]");
static_assert(GOLDEN_FAILBACK_V1[4].binding == 0x0C8C8FADFB41B066ULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[4]");
static_assert(GOLDEN_FAILBACK_V1[5].binding == 0xDA1FCEA2E8446C54ULL, "FB-A failback binding: GOLDEN_FAILBACK_V1[5]");

// Encoding round trips.
static_assert(decode_profile(encode_profile(GOLDEN_PROFILE_V1)).binding == GOLDEN_PROFILE_V1.binding &&
                  profile_binding(decode_profile(encode_profile(GOLDEN_PROFILE_V1))) == GOLDEN_PROFILE_V1.binding,
              "FB-A profile encode/decode round trip");
static_assert(decode_failback(encode_failback(GOLDEN_FAILBACK_V1[2])).binding == GOLDEN_FAILBACK_V1[2].binding &&
                  failback_binding(decode_failback(encode_failback(GOLDEN_FAILBACK_V1[2]))) ==
                      GOLDEN_FAILBACK_V1[2].binding,
              "FB-A failback encode/decode round trip");

// Whole-table digests.
static_assert(register_class_digest() == 0xC4750687575E1D21ULL, "FB-A register classification digest");
static_assert(domain_digest(DOMAIN_REG244) == 0x7D27181471F2DA26ULL, "FB-A 244 domain digest");
static_assert(domain_digest(DOMAIN_TOU_POWER) == 0x5B7DE13F7D7B102AULL, "FB-A 256-261 domain digest");
static_assert(domain_digest(DOMAIN_SOC) == 0x9D72CB01EAA01F12ULL, "FB-A 268-273 domain digest");
static_assert(domain_digest(DOMAIN_SLOT_SOURCE) == 0x5F00C83A88E1D8B9ULL, "FB-A 274-279 domain digest");
static_assert(domain_digest(DOMAIN_FROM_244) == 0x4FEA9B042F0FAC57ULL, "FB-A FROM 244 domain digest");

// Register 244: 0 -> 2 is the ONLY permitted transition.
static_assert(reg244_write_permitted(0, 2) && !reg244_write_permitted(2, 0) && !reg244_write_permitted(2, 2) &&
                  !reg244_write_permitted(1, 2) && !reg244_write_permitted(0, 1) && !reg244_write_permitted(1, 0) &&
                  !reg244_write_permitted(0, 0) && !reg244_write_permitted(3, 2) && !reg244_write_permitted(0xFFFF, 2),
              "FB-A: register 244 may only ever be written 0 -> 2");

// Context compare granularity.
static_assert(ctx_matches(232, 0x0001, 0xFFFF) && !ctx_matches(232, 0x0001, 0xFFFE) && ctx_matches(248, 0x0000, 0xFFFE) &&
                  !ctx_matches(248, 0x0001, 0x0000) && !ctx_matches(243, 0x0001, 0x0003) &&
                  !ctx_matches(250, 0x0530, 0x0531) && ctx_matches(255, 2330, 2330) && !ctx_matches(230, 1, 1) &&
                  !ctx_matches(244, 2, 2),
              "FB-A: 232/248 compare bit 0 only; 243/250-255 the full word; non-CTX never matches");

// INVALIDATE: payload verbatim, generation + 1, one-way.
static_assert(classify_profile(LOAD_OK, invalidate_profile(GOLDEN_PROFILE_V1)) == PROFILE_INVALIDATED &&
                  invalidate_profile(GOLDEN_PROFILE_V1).generation == GOLDEN_PROFILE_V1.generation + 1 &&
                  profile_invalidate_permitted(GOLDEN_PROFILE_V1) &&
                  !profile_invalidate_permitted(invalidate_profile(GOLDEN_PROFILE_V1)),
              "FB-A: INVALIDATE advances the generation and is one-way");
static_assert(profile_generation_advances(7, 8) && !profile_generation_advances(8, 8) && !profile_generation_advances(8, 7),
              "FB-A: every profile commit strictly increases the generation");

// FROM capture: permitted only while apply_committed is clear.
static_assert(failback_from_capture_permitted(GOLDEN_FAILBACK_V1[1]) &&
                  !failback_from_capture_permitted(GOLDEN_FAILBACK_V1[2]) &&
                  !failback_from_capture_permitted(GOLDEN_FAILBACK_V1[3]) &&
                  failback_from_capture_permitted(GOLDEN_FAILBACK_V1[4]),
              "FB-A: no FROM recapture once apply_committed is set");

// Profile golden cases. Each row: take encode_profile(GOLDEN_PROFILE_V1),
// overwrite the u16 (little-endian) at byte offset `off_a` with `val_a`, then
// at `off_b` with `val_b` (GOLDEN_NO_MUTATION = skip), decode, re-seal the
// binding if `reseal`, then profile_defect() must be `defect` and
// classify_profile(load, ...) must be `expected`.
constexpr uint8_t GOLDEN_NO_MUTATION = 0xFF;

struct ProfileGoldenCase {
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
constexpr ProfileGoldenCase PROFILE_GOLDEN_CASES[] = {
  // load status first; the record is never inspected unless load == OK
  {LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_ABSENT, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_NOT_CAPTURED},
  {LOAD_WRONG_SIZE, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_CORRUPT},
  {LOAD_READ_ERROR, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_UNREADABLE},
  {LOAD_STORAGE_UNAVAILABLE, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_UNREADABLE},
  {5, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_UNREADABLE},
  {255, 0xFF, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_NONE, PROFILE_UNREADABLE},
  {LOAD_ABSENT, 0, 0x0000, 2, 0x0000, 0, PROFILE_DEFECT_MAGIC, PROFILE_NOT_CAPTURED},
  {LOAD_READ_ERROR, 0, 0x0000, 2, 0x0000, 0, PROFILE_DEFECT_MAGIC, PROFILE_UNREADABLE},
  {LOAD_STORAGE_UNAVAILABLE, 18, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_UNREADABLE},
  {5, 16, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_UNREADABLE},
  {LOAD_WRONG_SIZE, 16, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_CORRUPT},
  {LOAD_ABSENT, 16, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_NOT_CAPTURED},
  // 1 magic
  {LOAD_OK, 0, 0x4651, 0xFF, 0x0000, 1, PROFILE_DEFECT_MAGIC, PROFILE_CORRUPT},
  {LOAD_OK, 2, 0x4544, 0xFF, 0x0000, 1, PROFILE_DEFECT_MAGIC, PROFILE_CORRUPT},
  // 2 schema (schema 2 under the v1 tag is corruption)
  {LOAD_OK, 4, 0x0000, 0xFF, 0x0000, 1, PROFILE_DEFECT_SCHEMA, PROFILE_CORRUPT},
  {LOAD_OK, 4, 0x0002, 0xFF, 0x0000, 1, PROFILE_DEFECT_SCHEMA, PROFILE_CORRUPT},
  {LOAD_OK, 4, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_SCHEMA, PROFILE_CORRUPT},
  // 3 size
  {LOAD_OK, 6, 95, 0xFF, 0x0000, 1, PROFILE_DEFECT_SIZE, PROFILE_CORRUPT},
  {LOAD_OK, 6, 97, 0xFF, 0x0000, 1, PROFILE_DEFECT_SIZE, PROFILE_CORRUPT},
  {LOAD_OK, 6, 80, 0xFF, 0x0000, 1, PROFILE_DEFECT_SIZE, PROFILE_CORRUPT},
  {LOAD_OK, 6, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_SIZE, PROFILE_CORRUPT},
  // 4 binding (NOT re-sealed)
  {LOAD_OK, 88, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 94, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 76, 0x0000, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 20, 7999, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 8, 0x0008, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x0001, 0xFF, 0x0000, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  // 5 reserved
  {LOAD_OK, 80, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  {LOAD_OK, 82, 0x8000, 0xFF, 0x0000, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  {LOAD_OK, 84, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  {LOAD_OK, 86, 0x8000, 0xFF, 0x0000, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  // 6 flags
  {LOAD_OK, 16, 0x0002, 0xFF, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x0003, 0xFF, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x8000, 0xFF, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  // 7 generation
  {LOAD_OK, 8, 0x0000, 0xFF, 0x0000, 1, PROFILE_DEFECT_GENERATION, PROFILE_CORRUPT},
  {LOAD_OK, 8, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 10, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 8, 0x0000, 10, 0x0001, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 12, 0x0000, 14, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  // 8 domain: 244
  {LOAD_OK, 18, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 18, 1, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 18, 3, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 18, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  // 8 domain: 256-261 (first and last slot), schema bound 500..8000
  {LOAD_OK, 20, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 20, 499, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 20, 500, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 20, 8000, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 20, 8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 20, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 30, 499, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 30, 8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 30, 500, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  // 8 domain: 268-273 (0xFFFF / 0x8000 are the u16 encodings of negative values)
  {LOAD_OK, 32, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 32, 100, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 32, 101, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 32, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 32, 0x8000, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 42, 101, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  // 8 domain: 274-279
  {LOAD_OK, 44, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 46, 1, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 44, 2, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 3, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 0x0004, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 0x0005, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 0x0040, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 0x0100, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 44, 0x8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 54, 2, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 54, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  // CTX / INFO: recorded, never domain-constrained
  {LOAD_OK, 56, 0x0000, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 56, 0xFFFE, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 56, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 58, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 60, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 62, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 72, 9999, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 74, 0, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 74, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 76, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  {LOAD_OK, 78, 0xFFFF, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID},
  // INVALIDATED is last: only a defect-free record is INVALIDATED
  {LOAD_OK, 16, 0x0001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_INVALIDATED},
  {LOAD_OK, 16, 0x0001, 56, 0xFFFF, 1, PROFILE_DEFECT_NONE, PROFILE_INVALIDATED},
  {LOAD_OK, 16, 0x0001, 18, 0, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN},
  {LOAD_OK, 16, 0x0001, 8, 0, 1, PROFILE_DEFECT_GENERATION, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x0001, 80, 1, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x0001, 4, 2, 1, PROFILE_DEFECT_SCHEMA, PROFILE_CORRUPT},
  // precedence between the structural rules (first failing rule wins)
  {LOAD_OK, 0, 0x0000, 4, 0x0002, 1, PROFILE_DEFECT_MAGIC, PROFILE_CORRUPT},
  {LOAD_OK, 4, 0x0002, 6, 95, 1, PROFILE_DEFECT_SCHEMA, PROFILE_CORRUPT},
  {LOAD_OK, 6, 95, 80, 0x0001, 0, PROFILE_DEFECT_SIZE, PROFILE_CORRUPT},
  {LOAD_OK, 80, 0x0001, 16, 0x0002, 0, PROFILE_DEFECT_BINDING, PROFILE_CORRUPT},
  {LOAD_OK, 80, 0x0001, 16, 0x0002, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
  {LOAD_OK, 16, 0x0002, 8, 0x0000, 1, PROFILE_DEFECT_FLAGS, PROFILE_CORRUPT},
  {LOAD_OK, 8, 0x0000, 18, 0, 1, PROFILE_DEFECT_GENERATION, PROFILE_CORRUPT},
  {LOAD_OK, 80, 0x0001, 20, 499, 1, PROFILE_DEFECT_RESERVED, PROFILE_CORRUPT},
};
// clang-format on

constexpr bool run_profile_golden_case(const ProfileGoldenCase &c) {
  ProfileBytes b = encode_profile(GOLDEN_PROFILE_V1);
  if (c.off_a != GOLDEN_NO_MUTATION)
    put_le(b, c.off_a, c.val_a, 2);
  if (c.off_b != GOLDEN_NO_MUTATION)
    put_le(b, c.off_b, c.val_b, 2);
  FallbackProfileV1 p = decode_profile(b);
  if (c.reseal)
    p = seal_profile(p);
  return profile_defect(p) == c.defect && classify_profile(c.load, p) == c.expected;
}

constexpr bool profile_golden_cases_hold() {
  for (const auto &c : PROFILE_GOLDEN_CASES) {
    if (!run_profile_golden_case(c))
      return false;
  }
  return true;
}
static_assert(profile_golden_cases_hold(), "FB-A profile classifier golden cases");

// Failback golden cases: same scheme over encode_failback(GOLDEN_FAILBACK_V1[base]).
// The u16 at offset 8 is (reason << 8) | state, at 10 is (flags << 8) | result,
// at 24 is (verify_mismatches << 8) | apply_attempts.
struct FailbackGoldenCase {
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
constexpr FailbackGoldenCase FAILBACK_GOLDEN_CASES[] = {
  // every base is VALID; load status first; ABSENT is not a present CLEAR record
  {0, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {1, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {3, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {5, LOAD_OK, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {0, LOAD_ABSENT, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_ABSENT},
  {2, LOAD_ABSENT, 0, 0x0000, 2, 0x0000, 0, FAILBACK_DEFECT_MAGIC, FAILBACK_RECORD_ABSENT},
  {2, LOAD_WRONG_SIZE, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_READ_ERROR, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_UNREADABLE},
  {2, LOAD_STORAGE_UNAVAILABLE, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_UNREADABLE},
  {0, 5, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_UNREADABLE},
  {0, 255, 0xFF, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_UNREADABLE},
  {2, LOAD_READ_ERROR, 0, 0x0000, 2, 0x0000, 0, FAILBACK_DEFECT_MAGIC, FAILBACK_RECORD_UNREADABLE},
  // structure
  {2, LOAD_OK, 0, 0x4643, 0xFF, 0x0000, 1, FAILBACK_DEFECT_MAGIC, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 2, 0x4544, 0xFF, 0x0000, 1, FAILBACK_DEFECT_MAGIC, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 4, 0x0002, 0xFF, 0x0000, 1, FAILBACK_DEFECT_SCHEMA, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 6, 72, 0xFF, 0x0000, 1, FAILBACK_DEFECT_SIZE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 6, 96, 0xFF, 0x0000, 1, FAILBACK_DEFECT_SIZE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 72, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_BINDING, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 78, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_BINDING, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 64, 0x0000, 0xFF, 0x0000, 0, FAILBACK_DEFECT_BINDING, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 28, 3001, 0xFF, 0x0000, 0, FAILBACK_DEFECT_BINDING, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x0B00, 0xFF, 0x0000, 1, FAILBACK_DEFECT_FLAGS, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x8300, 0xFF, 0x0000, 1, FAILBACK_DEFECT_FLAGS, FAILBACK_RECORD_CORRUPT},
  // enums: state / reason / result out of range
  {2, LOAD_OK, 8, 0x0105, 0xFF, 0x0000, 1, FAILBACK_DEFECT_STATE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x01FF, 0xFF, 0x0000, 1, FAILBACK_DEFECT_STATE, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 8, 0x0005, 0xFF, 0x0000, 1, FAILBACK_DEFECT_STATE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x0302, 0xFF, 0x0000, 1, FAILBACK_DEFECT_REASON, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0xFF02, 0xFF, 0x0000, 1, FAILBACK_DEFECT_REASON, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x030C, 0xFF, 0x0000, 1, FAILBACK_DEFECT_RESULT, FAILBACK_RECORD_CORRUPT},
  {4, LOAD_OK, 10, 0x01FF, 0xFF, 0x0000, 1, FAILBACK_DEFECT_RESULT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x0202, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  // APPLY_IN_PROGRESS [2]: apply_committed, FROM domain, counters, bound profile
  {2, LOAD_OK, 10, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x0200, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 10, 0x0700, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 10, 0x0305, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x0002, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 12, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 26, 1, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 26, 2, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 26, 3, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 28, 499, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 28, 500, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 38, 8000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 38, 8001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 40, 100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 50, 101, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 52, 1, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 52, 2, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 52, 0x0040, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 62, 3, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 20, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 24, 0x0201, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {2, LOAD_OK, 24, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  // PREEMPT_REQUIRED [1]: no apply commit, zero FROM, zero counters, no result
  {1, LOAD_OK, 10, 0x0300, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 28, 3000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 26, 2, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 24, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 24, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 10, 0x0101, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 8, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 12, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 10, 0x0500, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {1, LOAD_OK, 10, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {1, LOAD_OK, 20, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {1, LOAD_OK, 64, 0x0000, 66, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {1, LOAD_OK, 8, 0x0102, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  // CLEAR [0]: carries only event_seq
  {0, LOAD_OK, 12, 0xFFFF, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {0, LOAD_OK, 12, 0x0000, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {0, LOAD_OK, 8, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 10, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 10, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 10, 0x0400, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 16, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 20, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 24, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 28, 500, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 64, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {0, LOAD_OK, 20, 0x0001, 64, 0x0001, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  // LATCHED_COMPLETE [3]: latched result; apply_committed iff APPLIED_VERIFIED
  {3, LOAD_OK, 10, 0x0303, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {3, LOAD_OK, 10, 0x0305, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {3, LOAD_OK, 10, 0x0104, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {3, LOAD_OK, 10, 0x0300, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {4, LOAD_OK, 8, 0x0103, 10, 0x0101, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 8, 0x0103, 10, 0x0103, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 8, 0x0103, 10, 0x0104, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {5, LOAD_OK, 8, 0x0103, 10, 0x0102, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  // BLOCKED [4]/[5]: blocked result, with or without an apply commit
  {4, LOAD_OK, 10, 0x0101, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {4, LOAD_OK, 10, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {4, LOAD_OK, 10, 0x010B, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 10, 0x0105, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 10, 0x0500, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {4, LOAD_OK, 10, 0x0508, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  {4, LOAD_OK, 10, 0x0308, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {5, LOAD_OK, 20, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {5, LOAD_OK, 64, 0x0001, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT},
  {5, LOAD_OK, 20, 0x0001, 64, 0x0001, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID},
  // precedence between the structural rules
  {2, LOAD_OK, 0, 0x0000, 4, 0x0002, 1, FAILBACK_DEFECT_MAGIC, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 4, 0x0002, 6, 72, 1, FAILBACK_DEFECT_SCHEMA, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 6, 72, 8, 0x0105, 0, FAILBACK_DEFECT_SIZE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x0B00, 8, 0x0105, 0, FAILBACK_DEFECT_BINDING, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x0B00, 8, 0x0105, 1, FAILBACK_DEFECT_FLAGS, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x0305, 10, 0x030C, 1, FAILBACK_DEFECT_STATE, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 8, 0x0302, 10, 0x030C, 1, FAILBACK_DEFECT_REASON, FAILBACK_RECORD_CORRUPT},
  {2, LOAD_OK, 10, 0x030C, 26, 1, 1, FAILBACK_DEFECT_RESULT, FAILBACK_RECORD_CORRUPT},
};
// clang-format on

constexpr bool run_failback_golden_case(const FailbackGoldenCase &c) {
  FailbackBytes b = encode_failback(GOLDEN_FAILBACK_V1[c.base]);
  if (c.off_a != GOLDEN_NO_MUTATION)
    put_le(b, c.off_a, c.val_a, 2);
  if (c.off_b != GOLDEN_NO_MUTATION)
    put_le(b, c.off_b, c.val_b, 2);
  FailbackStateV1 s = decode_failback(b);
  if (c.reseal)
    s = seal_failback(s);
  return failback_defect(s) == c.defect && classify_failback(c.load, s) == c.expected;
}

constexpr bool failback_golden_cases_hold() {
  for (const auto &c : FAILBACK_GOLDEN_CASES) {
    if (!run_failback_golden_case(c))
      return false;
  }
  return true;
}
static_assert(failback_golden_cases_hold(), "FB-A failback classifier golden cases");

}  // namespace ecco_fallback
