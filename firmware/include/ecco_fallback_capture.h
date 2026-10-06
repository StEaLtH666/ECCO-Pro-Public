#pragma once

// FB-B1: Fallback Profile REVIEW (capture side) - PURE MODEL.
//
// FB-B1 is the READ-ONLY "Review Current Configuration" flow: a gate, four
// distinct FC03 reads (230/3, 241/53, 230/3, 241/53), a 31-word compare and a
// RAM-only candidate, plus the text entities that publish all of it. Every
// decision the firmware lambdas take is a PURE function of plain values and
// lives here; the lambdas only gather RAM flags into the POD structs below
// (used as lambda locals only - never as the type of a firmware global), make ONE call per
// decision and publish the result. This header is deliberately STANDALONE and
// BEHAVIOUR-FREE:
//   - it includes only standard headers and the FB-B0 model header; no ESPHome
//     header, no storage, no inverter bus, no entity, no clock: time is always
//     a parameter (`now_ms`);
//   - nothing here runs unless a caller calls it, and it declares no durable
//     record, key or tag;
//   - everything is constexpr, text included (TextBuf, no formatted-print library), so the
//     golden vectors and golden strings at the bottom are static_asserts
//     evaluated by registry/tests/test_fallback_capture_host_compile.py
//     (host C++ compile, -fsyntax-only -Wall -Wextra -Werror) and re-derived
//     from the Python mirror.
//
// Offline mirror: registry/fallback_capture.py (same names, same behaviour).
//
// ENTRY POINTS (one line each; every one is documented at its definition)
//   words / pass buffers   store_block_230  store_block_241  first_diff  reg_of  words_of  profile_from_words
//   L2 (capture policy)    capture_refusals  capture_warnings  sv_text  review_eligible  review_evaluate
//   fresh FBP / FBW read   evaluate_read  (note_read x2, divergence rule, next_seen_hw_gen, RE-compose)
//   gate (V1-V7)           gate_decide  probe_result  latch_get  latch_set  latch_text
//   housekeeping (10 s)    candidate_expired  exp_seconds  lease_domain_nonclear  breaker_fired  writes_fingerprint
//   entities               epc_name (B1)  b2_text b3_text b4_text b5_text b6_text b7_text b8_text  and the B9 builders
//   live match (B10, FB-B3) live_match  b10_text  b10_seed_text  live_trust  fence_tick  export_hazard  live_effective_class
//
// WHO CALLS WHAT (each firmware lambda gathers plain values into the POD structs, makes these calls, publishes)
//   boot lambda        evaluate_read (no baseline), epc_name, b2_text, b7_text, b8_text, b3_text, b4_text, b5_text and
//                      b6_text (NONE forms), b9_seed_text
//   review gate        gate_decide - called a second time with ProbeResults when it answers GATE_NEED_PROBE, each
//                      marker read turned into a probe code by probe_result; then review_in_progress_text and b3_text
//   read handlers      store_block_230 / store_block_241 into pass 1 (R1, R2) or pass 2 (R3, R4); the READ_* codes
//   REVIEW final       review_integrity_ok, read_fail_text, first_diff / pass_mismatch_text, evaluate_read (baseline =
//                      the RAM mirror), review_evaluate, candidate_ready_text / not_saveable_text, b3_text .. b8_text
//   housekeeping tick  breaker_fired / breaker_text, candidate_expired / review_expired_text, lease_domain_nonclear /
//                      review_cleared_domain_text, writes_fingerprint / review_cleared_writes_text, exp_seconds / b3_text
//   invalidation       b3_text (IDLE form), b4_text, b5_text / b6_text (NONE forms), invalidate_reason_publishes
//   live match tick    (10 s, after the housekeeping lambdas) fence_tick over bus_hot / lease_domain_nonclear / writes_fingerprint,
//                      then live_match over the profile mirror, the poll caches and the RAM legs, then b10_text; boot: b10_seed_text
//
// Discipline (pinned by the offline suites): standard headers + the FB-B0
// model header only; every namespace-scope object is constexpr; no `static`,
// no `inline`; one namespace.

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "ecco_fallback_durable_model.h"

namespace ecco_fbcap {

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
constexpr uint32_t CANDIDATE_TTL_MS = 120000u;  // candidate lifetime; expiry is applied by the 10 s tick
constexpr uint32_t IDLE_WAIT_MS = 7000u;        // wait_until bus idle, before R1
constexpr uint32_t STEP_WAIT_MS = 3000u;        // wait_until per read step
constexpr uint32_t BREAKER_MS = 30000u;         // leaked-operation breaker age
constexpr uint32_t LOCK_STUCK_MS = 300000u;     // the shared write lock counts as stuck after this
constexpr size_t TEXT_CAP = 200;                // hard cap of every published text
constexpr size_t REG_COUNT = 31;                // the 31 captured register words
constexpr size_t REFUSAL_MAX = 40;              // 1 + 6 + 6 + 18 + 6 + 1 = 38 L2 refusals at most
constexpr uint16_t DUMP_CONTROLLER_MAX_W = 3000;  // W2: the Dump controller's maximum ceiling

enum Purpose : uint8_t { PURPOSE_NONE = 0, PURPOSE_REVIEW = 1 };

enum CaptureState : uint8_t {
  CAPTURE_IDLE = 0,
  CAPTURE_READING = 1,
  CAPTURE_CANDIDATE_READY = 2,
  CAPTURE_CANDIDATE_NOT_SAVEABLE = 3,
  CAPTURE_SAVING = 4,  // FB-B2: a SAVE is in flight (the candidate is consumed; INVALIDATE is synchronous and never shows)
};

// Why a read step did not deliver its words. 0 = none.
enum ReadFail : uint8_t {
  READ_NONE = 0,
  READ_NO_RESPONSE = 1,
  READ_EXCEPTION = 2,
  READ_NOT_SENT = 3,
  READ_NONSTANDARD = 4,
  READ_SHORT = 5,
  READ_BOUNDED_WAIT = 6,
  READ_IDLE_TIMEOUT = 7,
};

// Result of one durable lease-marker probe (a direct read, never retried).
enum ProbeCode : uint8_t {
  PROBE_NONE = 0,  // not probed
  PROBE_ABSENT = 1,
  PROBE_CLEAR = 2,
  PROBE_RESTORE_REQUIRED = 3,
  PROBE_PENDING_CLEAR = 4,
  PROBE_MALFORMED = 5,
  PROBE_UNREADABLE = 6,
};

// The sticky runtime probe latch: a u16, one nibble per lease domain. It is
// only ever SET (latch_set), never cleared within a boot.
enum LatchCode : uint8_t {
  LATCH_NONE = 0,
  LATCH_UNREADABLE = 1,
  LATCH_MALFORMED = 2,
  LATCH_GHOST_RR = 3,
  LATCH_GHOST_PC = 4,
};
enum LeaseDomain : uint8_t { DOM_FP = 0, DOM_DUMP = 1, DOM_R244 = 2 };

// Marker record facts (equal ecco_durable::VALID_MARKER_MAGIC and MARKER_*;
// restated here so this header stays pure).
constexpr uint32_t MARKER_RECORD_MAGIC = 0x45434356u;
constexpr uint8_t MARKER_STATE_CLEAR = 0;
constexpr uint8_t MARKER_STATE_RESTORE_REQUIRED = 1;
constexpr uint8_t MARKER_STATE_PENDING_CLEAR = 2;

// SG-06 marker boot load (equal ecco_durable::LoadStatus 0..3) and the
// "never assigned" initial value of the three *_marker_boot_load variables.
constexpr uint8_t BOOT_LOAD_OK = 0;
constexpr uint8_t BOOT_LOAD_ABSENT = 1;
constexpr uint8_t BOOT_LOAD_WRONG_SIZE = 2;
constexpr uint8_t BOOT_LOAD_READ_ERROR = 3;
constexpr uint8_t BOOT_LOAD_NOT_LOADED = 255;

// Obligation kinds (charter C0 vocabulary) and the basis of the verdict.
// 0 is the fail-closed value: it never reads as clear.
enum ObligationKind : uint8_t {
  OBL_UNSET = 0,
  OBL_CLEAR_PROVEN = 1,
  OBL_ACTIVE = 2,
  OBL_STARTING = 3,
  OBL_RESTORE_REQUIRED = 4,
  OBL_PENDING_CLEAR = 5,
  OBL_ENDING = 6,
  OBL_OPERATOR_NEEDED = 7,
  UNK_DURABLE_UNREADABLE = 8,
  UNK_METADATA_CORRUPT = 9,
  UNK_BOOT_NOT_LOADED = 10,
  UNK_DIVERGED = 11,
  UNK_BUS_OR_LOCK_STUCK = 12,
  UNK_NOT_PROBED = 13,
  BUS_BUSY = 14,
};
enum ObligationBasis : uint8_t {
  BASIS_NONE = 0,
  BASIS_MARKER_CLEAR = 1,
  BASIS_ABSENT = 2,
  BASIS_NO_DURABLE_STATE = 3,
  BASIS_BOOT_READ_ERROR = 4,
  BASIS_BOOT_LOCKOUT = 5,
  BASIS_RUNTIME_PROBE = 6,
  BASIS_GHOST_RR = 7,
  BASIS_GHOST_PC = 8,
  BASIS_RAM_INCONSISTENT = 9,
  BASIS_OP_FLAG_UNATTRIBUTED = 10,
  BASIS_LEASE = 11,
  BASIS_PRE_COMMIT = 12,
  BASIS_COMMITTED = 13,
  BASIS_RESTORE_RUNNING = 14,
  BASIS_OPERATOR_ACTION_RUNNING = 15,
  BASIS_FBS_EPISODE = 16,
  BASIS_BUS_IDLE = 17,
  BASIS_BUS_TXN = 18,
  BASIS_LOCK_STUCK = 19,
};

// The six obligation slots, in the order the gate reports them.
enum Slot : uint8_t { SLOT_BUS = 0, SLOT_FBS = 1, SLOT_FP = 2, SLOT_DUMP = 3, SLOT_R244 = 4, SLOT_MTOU = 5 };
constexpr uint8_t SLOT_NONE = 0xFF;

enum GateCode : uint8_t {
  GATE_UNSET = 0,  // no decision (fail-closed)
  GATE_ACCEPT = 1,
  GATE_NEED_PROBE = 2,
  GATE_REFUSE_IN_FLIGHT = 3,  // V1: touches nothing
  GATE_REFUSE_NOT_LOADED = 4,
  GATE_REFUSE_ARMS = 5,
  GATE_REFUSE_BUS = 6,
  GATE_REFUSE_FBS = 7,
  GATE_REFUSE_FP = 8,
  GATE_REFUSE_DUMP = 9,
  GATE_REFUSE_R244 = 10,
  GATE_REFUSE_MTOU = 11,
};

// L2 refusal kinds. A refusal item is (kind << 8) | slot (slot 1..6, 0 when it has none).
enum RefusalKind : uint8_t {
  RF_NONE = 0,
  RF_244X = 1,
  RF_PWRL = 2,
  RF_PWRH = 3,
  RF_SOCH = 4,
  RF_SRCG = 5,
  RF_MODE = 6,
  RF_BITS = 7,
  RF_HHMM = 8,
  RF_243X = 9,
  RF_CLASS = 10,    // text only: the stored profile class does not permit a Save (slot = class)
  RF_ANOMALY = 11,  // text only: a stored-profile read anomaly this boot
};

// B2 `w=` values, in grammar order.
enum WitnessView : uint8_t { WVIEW_OK = 0, WVIEW_LAG = 1, WVIEW_MISS = 2, WVIEW_CORR = 3, WVIEW_UNR = 4, WVIEW_ABS = 5 };

// Manual TOU has no durable state today. The day it gets a journal this must
// be wired as a probe-backed domain like FP / DUMP / R244 (pinned by a test).
constexpr bool MTOU_JOURNAL_NOT_IMPLEMENTED = true;

// ---------------------------------------------------------------------------
// TextBuf: a constexpr text builder. No formatted-print library, no heap. Every put_* stops
// at TEXT_CAP and sets `overflow`; the NUL terminator is always present.
// ---------------------------------------------------------------------------
struct TextBuf {
  char buf[TEXT_CAP + 1];
  uint16_t len;
  bool overflow;
  constexpr TextBuf() : buf{}, len(0), overflow(false) {}
  constexpr const char *c_str() const { return buf; }
  constexpr size_t size() const { return len; }
};

constexpr void put_char(TextBuf &t, char c) {
  if (t.len >= TEXT_CAP) {
    t.overflow = true;
    return;
  }
  t.buf[t.len] = c;
  t.len = (uint16_t) (t.len + 1);
  t.buf[t.len] = '\0';
}

constexpr void put(TextBuf &t, const char *s) {
  for (; *s != '\0'; s++)
    put_char(t, *s);
}

// Decimal, zero padded to at least min_digits (never truncated).
constexpr void put_u(TextBuf &t, uint32_t v, uint8_t min_digits = 0) {
  char rev[10] = {};
  uint8_t n = 0;
  do {
    rev[n++] = (char) ('0' + (v % 10u));
    v /= 10u;
  } while (v != 0u);
  for (uint8_t i = n; i < min_digits; i++)
    put_char(t, '0');
  while (n > 0)
    put_char(t, rev[--n]);
}

// Uppercase hex, zero padded to at least min_digits (never truncated).
constexpr void put_hex(TextBuf &t, uint64_t v, uint8_t min_digits) {
  char rev[16] = {};
  uint8_t n = 0;
  do {
    const uint8_t d = (uint8_t) (v & 0xFu);
    rev[n++] = (char) (d < 10 ? '0' + d : 'A' + (d - 10));
    v >>= 4;
  } while (v != 0u);
  for (uint8_t i = n; i < min_digits; i++)
    put_char(t, '0');
  while (n > 0)
    put_char(t, rev[--n]);
}

// Exact comparison against a string literal (used by the golden static_asserts).
template<size_t N> constexpr bool text_is(const char (&lit)[N], const TextBuf &t) {
  if (t.size() != N - 1)
    return false;
  for (size_t i = 0; i + 1 < N; i++) {
    if (t.buf[i] != lit[i])
      return false;
  }
  return true;
}
template<size_t N> constexpr bool str_is(const char *s, const char (&lit)[N]) {
  for (size_t i = 0; i + 1 < N; i++) {
    if (s[i] != lit[i])
      return false;
  }
  return s[N - 1] == '\0';
}

// ---------------------------------------------------------------------------
// Names (every one TOTAL: an out-of-range value renders its fail-closed form)
// ---------------------------------------------------------------------------
// B1: the effective profile class. 7 renders SAVE_UNCONFIRMED although FB-B1
// never produces it.
constexpr const char *epc_name(uint8_t cls) {
  switch (cls) {
    case ecco_fbdurable::EPC_NOT_CAPTURED:
      return "NOT_CAPTURED";
    case ecco_fbdurable::EPC_CORRUPT:
      return "CORRUPT";
    case ecco_fbdurable::EPC_CORRUPT_DOMAIN:
      return "CORRUPT_DOMAIN";
    case ecco_fbdurable::EPC_INVALIDATED:
      return "INVALIDATED";
    case ecco_fbdurable::EPC_VALID:
      return "VALID";
    case ecco_fbdurable::EPC_PROFILE_LOST:
      return "PROFILE_LOST";
    case ecco_fbdurable::EPC_SAVE_UNCONFIRMED:
      return "SAVE_UNCONFIRMED";
    case ecco_fbdurable::EPC_PROFILE_STALE:
      return "PROFILE_STALE";
    default:
      return "UNREADABLE";
  }
}

constexpr const char *ld_name(uint8_t load) {
  return load == ecco_fallback::LOAD_OK                   ? "OK"
         : load == ecco_fallback::LOAD_ABSENT             ? "ABS"
         : load == ecco_fallback::LOAD_WRONG_SIZE         ? "WSZ"
         : load == ecco_fallback::LOAD_STORAGE_UNAVAILABLE ? "UNAV"
                                                           : "RERR";
}

constexpr const char *df_name(uint8_t defect) {
  switch (defect) {
    case ecco_fallback::PROFILE_DEFECT_MAGIC:
      return "MAGIC";
    case ecco_fallback::PROFILE_DEFECT_SCHEMA:
      return "SCHEMA";
    case ecco_fallback::PROFILE_DEFECT_SIZE:
      return "SIZE";
    case ecco_fallback::PROFILE_DEFECT_BINDING:
      return "BINDING";
    case ecco_fallback::PROFILE_DEFECT_RESERVED:
      return "RESERVED";
    case ecco_fallback::PROFILE_DEFECT_FLAGS:
      return "FLAGS";
    case ecco_fallback::PROFILE_DEFECT_GENERATION:
      return "GEN";
    case ecco_fallback::PROFILE_DEFECT_DOMAIN:
      return "DOMAIN";
    default:
      return "-";
  }
}

constexpr const char *w_name(uint8_t code) {
  return code == WVIEW_OK     ? "OK"
         : code == WVIEW_LAG  ? "LAG"
         : code == WVIEW_MISS ? "MISS"
         : code == WVIEW_CORR ? "CORR"
         : code == WVIEW_ABS  ? "ABS"
                              : "UNR";
}

constexpr const char *op_name(uint8_t last_op) {
  return last_op == ecco_fbdurable::PROV_OP_SAVE             ? "SAVE"
         : last_op == ecco_fbdurable::PROV_OP_INVALIDATE     ? "INV"
         : last_op == ecco_fbdurable::PROV_OP_REPLACE_CORRUPT ? "RC"
                                                             : "-";
}

constexpr const char *why_name(uint8_t why) {
  switch (why) {
    case ecco_fbdurable::WHY_INTERRUPTED:
      return "INT";
    case ecco_fbdurable::WHY_ROLLBACK:
      return "RBK";
    case ecco_fbdurable::WHY_MISMATCH:
      return "MIS";
    case ecco_fbdurable::WHY_SUPERSEDED:
      return "SUP";
    case ecco_fbdurable::WHY_WIT_LAGGING:
      return "LAG";
    case ecco_fbdurable::WHY_WIT_MISSING:
      return "MISS";
    case ecco_fbdurable::WHY_WIT_CORRUPT:
      return "CORR";
    case ecco_fbdurable::WHY_PROFILE_READ:
      return "PRD";
    case ecco_fbdurable::WHY_WITNESS_READ:
      return "WRD";
    case ecco_fbdurable::WHY_READ_ANOMALY:
      return "ANOM";
    case ecco_fbdurable::WHY_FIRST_SAVE_UNCONFIRMED:
      return "FIRST";
    case ecco_fbdurable::WHY_LOST_WIT_CORRUPT:
      return "LWC";
    default:
      return "-";
  }
}

constexpr const char *capture_state_name(uint8_t state) {
  return state == CAPTURE_READING                  ? "READING"
         : state == CAPTURE_CANDIDATE_READY        ? "CANDIDATE_READY"
         : state == CAPTURE_CANDIDATE_NOT_SAVEABLE ? "CANDIDATE_NOT_SAVEABLE"
         : state == CAPTURE_SAVING                 ? "SAVING"
                                                   : "IDLE";
}

constexpr const char *domain_label(uint8_t slot) {
  return slot == SLOT_FP     ? "Free Power"
         : slot == SLOT_DUMP ? "Dump to Grid"
         : slot == SLOT_R244 ? "Register 244 test"
         : slot == SLOT_FBS  ? "Failback record"
                             : "";
}

// The register block a step reads (steps 1 and 3 read 230/3, steps 2 and 4 read 241/53).
constexpr const char *block_name(uint8_t step) {
  return (step == 1 || step == 3) ? "230/3" : (step == 2 || step == 4) ? "241/53" : "?";
}

// B2 `w=`: the witness as seen from the profile (S2 section 3.2).
constexpr uint8_t w_view(uint8_t fba_cls, uint8_t wc, uint32_t generation, uint32_t hw_generation) {
  const bool authentic = ecco_fbdurable::fba_authentic(fba_cls);
  if (wc == ecco_fbdurable::W_UNREADABLE)
    return WVIEW_UNR;
  if (wc == ecco_fbdurable::W_ABSENT)
    return authentic ? WVIEW_MISS : WVIEW_ABS;
  if (wc == ecco_fbdurable::W_CORRUPT)
    return WVIEW_CORR;
  return (authentic && generation > hw_generation) ? WVIEW_LAG : WVIEW_OK;
}

// ---------------------------------------------------------------------------
// The 31 captured words: canonical order, index map, pass buffers
// ---------------------------------------------------------------------------
// Canonical order == FallbackProfileV1 field order; word k sits at byte offset 18 + 2k.
using CaptureWords = std::array<uint16_t, REG_COUNT>;

constexpr std::array<uint16_t, REG_COUNT> REGS = {244, 256, 257, 258, 259, 260, 261, 268, 269, 270, 271,
                                                  272, 273, 274, 275, 276, 277, 278, 279, 232, 243, 248,
                                                  250, 251, 252, 253, 254, 255, 230, 245, 247};

constexpr uint16_t reg_of(int k) { return (k >= 0 && k < (int) REG_COUNT) ? REGS[(size_t) k] : (uint16_t) 0; }

constexpr CaptureWords words_of(const ecco_fallback::FallbackProfileV1 &p) {
  CaptureWords w{};
  w[0] = p.reg244;
  for (size_t i = 0; i < 6; i++) {
    w[1 + i] = p.reg256_261[i];
    w[7 + i] = p.reg268_273[i];
    w[13 + i] = p.reg274_279[i];
    w[22 + i] = p.reg250_255[i];
  }
  w[19] = p.reg232;
  w[20] = p.reg243;
  w[21] = p.reg248;
  w[28] = p.reg230;
  w[29] = p.reg245;
  w[30] = p.reg247;
  return w;
}

// q: the profile record carrying `w` with the CONSTANT magic / schema / size
// and generation, epoch, flags, reserved and binding all zero.
constexpr ecco_fallback::FallbackProfileV1 profile_from_words(const CaptureWords &w) {
  ecco_fallback::FallbackProfileV1 p{};
  p.magic = ecco_fallback::PROFILE_MAGIC;
  p.schema = ecco_fallback::PROFILE_SCHEMA;
  p.size = ecco_fallback::PROFILE_SIZE;
  p.reg244 = w[0];
  for (size_t i = 0; i < 6; i++) {
    p.reg256_261[i] = w[1 + i];
    p.reg268_273[i] = w[7 + i];
    p.reg274_279[i] = w[13 + i];
    p.reg250_255[i] = w[22 + i];
  }
  p.reg232 = w[19];
  p.reg243 = w[20];
  p.reg248 = w[21];
  p.reg230 = w[28];
  p.reg245 = w[29];
  p.reg247 = w[30];
  return p;
}

// The index map is proved against the real record layout and the register
// classification: word k is the register REGS[k], at byte offset 18 + 2k.
constexpr bool index_map_matches_layout() {
  CaptureWords w{};
  for (size_t k = 0; k < REG_COUNT; k++)
    w[k] = (uint16_t) (0x1000 + k);
  const ecco_fallback::ProfileBytes b = ecco_fallback::encode_profile(profile_from_words(w));
  const CaptureWords back = words_of(profile_from_words(w));
  for (size_t k = 0; k < REG_COUNT; k++) {
    if (ecco_fallback::get_le(b, 18 + 2 * k, 2) != w[k] || back[k] != w[k])
      return false;
    const ecco_fallback::RegisterClass want =
        k < 19 ? ecco_fallback::REG_E1 : k < 28 ? ecco_fallback::REG_CTX : ecco_fallback::REG_INFO;
    if (ecco_fallback::register_class(REGS[k]) != want)
      return false;
    for (size_t j = 0; j < k; j++) {
      if (REGS[j] == REGS[k])
        return false;
    }
  }
  return true;
}
static_assert(index_map_matches_layout(), "FB-B1 capture: the 31-word index map matches FallbackProfileV1");

// R1 / R3 handler: words 19 (232) and 28 (230) from the 230/3 reply. `values`
// is any container with size() and operator[] (std::span, std::vector, std::array).
// False (nothing stored) unless exactly 3 values arrived.
template<class V> constexpr bool store_block_230(CaptureWords &w, const V &values) {
  if (values.size() != 3)
    return false;
  w[19] = (uint16_t) values[REGS[19] - 230];
  w[28] = (uint16_t) values[REGS[28] - 230];
  return true;
}

// R2 / R4 handler: the other 29 words from the 241/53 reply (word k = values[REGS[k] - 241]).
template<class V> constexpr bool store_block_241(CaptureWords &w, const V &values) {
  if (values.size() != 53)
    return false;
  for (size_t k = 0; k < REG_COUNT; k++) {
    if (k == 19 || k == 28)
      continue;
    w[k] = (uint16_t) values[REGS[k] - 241];
  }
  return true;
}

// First differing word index, or -1 when the two passes agree on all 31 words.
constexpr int first_diff(const CaptureWords &a, const CaptureWords &b) {
  for (size_t k = 0; k < REG_COUNT; k++) {
    if (a[k] != b[k])
      return (int) k;
  }
  return -1;
}

// ---------------------------------------------------------------------------
// L2 capture refusals and L2w warnings (live words, never the classifier)
// ---------------------------------------------------------------------------
// L2 never feeds ecco_fallback::classify_profile and the classifier never
// reads L2: a stored profile classifies by FB-A alone (pinned by a test).
constexpr bool hhmm_decodable(uint16_t raw) { return raw / 100 <= 23 && raw % 100 <= 59; }
constexpr bool on_5min_grid(uint16_t raw) { return (raw % 100) % 5 == 0; }

// Every start decodable, every gap d_i = (m_{i+1} - m_i + 1440) mod 1440 > 0 and the gaps sum to 1440.
constexpr bool ring_valid(const CaptureWords &w) {
  int minutes[6] = {};
  for (size_t i = 0; i < 6; i++) {
    if (!hhmm_decodable(w[22 + i]))
      return false;
    minutes[i] = (w[22 + i] / 100) * 60 + (w[22 + i] % 100);
  }
  int sum = 0;
  for (size_t i = 0; i < 6; i++) {
    const int d = (minutes[(i + 1) % 6] - minutes[i] + 1440) % 1440;
    if (d <= 0)
      return false;
    sum += d;
  }
  return sum == 1440;
}

struct Refusals {
  std::array<uint16_t, REFUSAL_MAX> item{};
  uint8_t count = 0;
};

constexpr void refusal_add(Refusals &r, uint8_t kind, uint8_t slot) {
  if (r.count < REFUSAL_MAX) {
    r.item[r.count] = (uint16_t) ((kind << 8) | slot);
    r.count = (uint8_t) (r.count + 1);
  }
}
constexpr uint8_t refusal_kind(uint16_t item) { return (uint8_t) (item >> 8); }
constexpr uint8_t refusal_slot(uint16_t item) { return (uint8_t) (item & 0xFFu); }

// Order: 244X; PWRL / PWRH slots 1-6; SOCH slots 1-6; per slot SRCG, MODE, BITS;
// HHMM slots 1-6; 243X. `ceiling_w` is the site's configured TOU power ceiling
// (the substitution, today 8000); a power above min(8000, ceiling) is PWRH.
// Not refused, ever: 232, 248, 230, 245, 247, and a 5-minute grid or ring
// problem (those are warnings W5 / W6).
constexpr Refusals capture_refusals(const CaptureWords &w, uint32_t ceiling_w) {
  Refusals r{};
  if (!ecco_fallback::reg244_domain_valid(w[0]))
    refusal_add(r, RF_244X, 0);
  for (uint8_t n = 1; n <= 6; n++) {
    const uint16_t pw = w[n];
    if (pw < ecco_fallback::V1_TOU_POWER_MIN_W)
      refusal_add(r, RF_PWRL, n);
    else if (!ecco_fallback::tou_power_domain_valid(pw) || (uint32_t) pw > ceiling_w)
      refusal_add(r, RF_PWRH, n);
  }
  for (uint8_t n = 1; n <= 6; n++) {
    if (!ecco_fallback::soc_domain_valid(w[6 + n]))
      refusal_add(r, RF_SOCH, n);
  }
  for (uint8_t n = 1; n <= 6; n++) {
    const uint16_t src = w[12 + n];
    if (!ecco_fallback::slot_source_domain_valid(src)) {
      if ((src & 0x0003u) > 1u)
        refusal_add(r, RF_SRCG, n);
      if ((src & 0x001Cu) != 0u)
        refusal_add(r, RF_MODE, n);
      if ((src & 0xFFE0u) != 0u)
        refusal_add(r, RF_BITS, n);
    }
  }
  for (uint8_t n = 1; n <= 6; n++) {
    if (!hhmm_decodable(w[21 + n]))
      refusal_add(r, RF_HHMM, n);
  }
  if (w[20] > 1)
    refusal_add(r, RF_243X, 0);
  return r;
}

// Bit n-1 = Wn.
//   W1 looks like a Free Power overlay   W2 uniform ceiling <= 3000 W (Dump residue)
//   W3 TOU master (248 bit0) off         W4 grid charging (232 bit0) off while a slot selects Grid
//   W5 a slot start is off the 5-minute grid      W6 the slot times are not a valid 24 h ring
constexpr uint16_t capture_warnings(const CaptureWords &w) {
  uint16_t mask = 0;
  bool all_soc = true, all_grid = true, all_equal = true, any_grid_source = false, any_off_grid = false;
  for (size_t i = 0; i < 6; i++) {
    all_soc = all_soc && w[7 + i] == 100;
    all_grid = all_grid && w[13 + i] == 1;
    all_equal = all_equal && w[1 + i] == w[1];
    any_grid_source = any_grid_source || (w[13 + i] & 0x0003u) == 1u;
    any_off_grid = any_off_grid || (hhmm_decodable(w[22 + i]) && !on_5min_grid(w[22 + i]));
  }
  if (all_soc && all_grid && (w[19] & 1u) != 0)
    mask = (uint16_t) (mask | (1u << 0));
  if (all_equal && w[1] <= DUMP_CONTROLLER_MAX_W)
    mask = (uint16_t) (mask | (1u << 1));
  if ((w[21] & 1u) == 0)
    mask = (uint16_t) (mask | (1u << 2));
  if ((w[19] & 1u) == 0 && any_grid_source)
    mask = (uint16_t) (mask | (1u << 3));
  if (any_off_grid)
    mask = (uint16_t) (mask | (1u << 4));
  if (!ring_valid(w))
    mask = (uint16_t) (mask | (1u << 5));
  return mask;
}

constexpr void put_refusal_code(TextBuf &t, uint16_t item) {
  switch (refusal_kind(item)) {
    case RF_244X:
      put(t, "244X");
      return;
    case RF_243X:
      put(t, "243X");
      return;
    case RF_PWRL:
      put(t, "PWRL");
      break;
    case RF_PWRH:
      put(t, "PWRH");
      break;
    case RF_SOCH:
      put(t, "SOCH");
      break;
    case RF_SRCG:
      put(t, "SRCG");
      break;
    case RF_MODE:
      put(t, "MODE");
      break;
    case RF_BITS:
      put(t, "BITS");
      break;
    case RF_HHMM:
      put(t, "HHMM");
      break;
    default:
      return;
  }
  put_u(t, refusal_slot(item));
}

// B3 `sv=` after an L2 evaluation: OK, or NO:c1[,c2[,c3]][+N] (N = the refusals beyond the first three).
constexpr TextBuf sv_text(const Refusals &r) {
  TextBuf t;
  if (r.count == 0) {
    put(t, "OK");
    return t;
  }
  put(t, "NO:");
  for (uint8_t i = 0; i < r.count && i < 3; i++) {
    if (i != 0)
      put_char(t, ',');
    put_refusal_code(t, r.item[i]);
  }
  if (r.count > 3) {
    put_char(t, '+');
    put_u(t, (uint32_t) (r.count - 3));
  }
  return t;
}

// B3 `warn=` list: W1,W3 ... or -.
constexpr TextBuf warn_text(uint16_t mask) {
  TextBuf t;
  bool any = false;
  for (uint8_t n = 1; n <= 6; n++) {
    if ((mask & (1u << (n - 1))) != 0) {
      if (any)
        put_char(t, ',');
      put_char(t, 'W');
      put_u(t, n);
      any = true;
    }
  }
  if (!any)
    put_char(t, '-');
  return t;
}

// Eligible (CANDIDATE_READY) iff no L2 refusal AND the effective class permits a Save AND no read anomaly.
constexpr bool review_eligible(const Refusals &r, uint8_t cls, uint8_t read_anomaly) {
  return r.count == 0 && ecco_fbdurable::save_class_permitted(cls) && read_anomaly == 0;
}

// ---------------------------------------------------------------------------
// Candidate id (S1 9.3): FNV-1a-64 over
//   "ECCO-FALLBACK-PROFILE-CANDIDATE-v1" (34 bytes, no NUL) || u32le(salt) || u32le(seq) || u8(prior class) ||
//   u32le(prior generation) || u64le(prior binding) || encode_profile(q)[0, 88)
// q = the candidate words with the CONSTANT magic / schema / size and
// generation, epoch, flags, reserved all zero.
// ---------------------------------------------------------------------------
constexpr char CANDIDATE_DOMAIN[] = "ECCO-FALLBACK-PROFILE-CANDIDATE-v1";
static_assert(sizeof(CANDIDATE_DOMAIN) - 1 == 34, "candidate id domain is 34 bytes, no NUL");

// Little-endian FNV-1a-64 step over the low `width` bytes of v.
constexpr uint64_t step_le(uint64_t h, uint64_t v, size_t width) {
  for (size_t i = 0; i < width; i++)
    h = ecco_fallback::fnv1a64_step(h, (uint8_t) ((v >> (8 * i)) & 0xFFu));
  return h;
}

constexpr uint64_t candidate_id_over(const ecco_fallback::FallbackProfileV1 &q, uint32_t salt, uint32_t seq,
                                     uint8_t prior_class, uint32_t prior_generation, uint64_t prior_binding) {
  uint64_t h = ecco_fallback::fnv1a64_literal(ecco_fallback::FNV1A64_OFFSET_BASIS, CANDIDATE_DOMAIN);
  h = step_le(h, salt, 4);
  h = step_le(h, seq, 4);
  h = step_le(h, prior_class, 1);
  h = step_le(h, prior_generation, 4);
  h = step_le(h, prior_binding, 8);
  const ecco_fallback::ProfileBytes b = ecco_fallback::encode_profile(q);
  for (size_t i = 0; i < ecco_fallback::PROFILE_BOUND_BYTES; i++)
    h = ecco_fallback::fnv1a64_step(h, b[i]);
  return h;
}

// THE locked reading (constants in q).
constexpr uint64_t candidate_id(uint32_t salt, uint32_t seq, uint8_t prior_class, uint32_t prior_generation,
                                uint64_t prior_binding, const CaptureWords &words) {
  return candidate_id_over(profile_from_words(words), salt, seq, prior_class, prior_generation, prior_binding);
}

// The REJECTED reading (q magic / schema / size = 0). TEST-ONLY: no firmware lambda calls it; it exists solely so
// a golden proves the two readings differ (it keeps the S1 9.3 choice of the constants reading pinned).
constexpr uint64_t candidate_id_alt_zero_header_reading(uint32_t salt, uint32_t seq, uint8_t prior_class,
                                                        uint32_t prior_generation, uint64_t prior_binding,
                                                        const CaptureWords &words) {
  ecco_fallback::FallbackProfileV1 q = profile_from_words(words);
  q.magic = 0;
  q.schema = 0;
  q.size = 0;
  return candidate_id_over(q, salt, seq, prior_class, prior_generation, prior_binding);
}

// B4: the 16-hex candidate id of a saveable candidate, else -.
constexpr TextBuf id_text(uint64_t candidate) {
  TextBuf t;
  put_hex(t, candidate, 16);
  return t;
}
constexpr TextBuf b4_text(bool saveable, uint64_t candidate) {
  if (saveable)
    return id_text(candidate);
  TextBuf t;
  put_char(t, '-');
  return t;
}

// ---------------------------------------------------------------------------
// Compare masks: candidate words `a` against the stored profile's words `b`
// ---------------------------------------------------------------------------
// dx (19 bits, shown %05X): bit k = a[k] != b[k] for k = 0..18 (244; 256-261; 268-273; 274-279),
// the FULL word, also for 274-279.
constexpr uint32_t e1_delta_mask(const CaptureWords &a, const CaptureWords &b) {
  uint32_t m = 0;
  for (size_t k = 0; k < 19; k++) {
    if (a[k] != b[k])
      m |= (1u << k);
  }
  return m;
}

// dc (9 bits, shown %03X): bit0 232.b0, bit1 243, bit2 248.b0, bits3-8 250-255 (FB-A ctx_matches semantics).
constexpr uint16_t ctx_mismatch_mask(const CaptureWords &a, const CaptureWords &b) {
  uint16_t m = 0;
  for (size_t i = 0; i < 9; i++) {
    const size_t k = 19 + i;
    if (!ecco_fallback::ctx_matches(REGS[k], b[k], a[k]))
      m = (uint16_t) (m | (1u << i));
  }
  return m;
}

// di (5 bits, shown %02X): bit0 230, bit1 245, bit2 247 (full word), bit3 232 bits 1-15, bit4 248 bits 1-15.
constexpr uint8_t info_mismatch_mask(const CaptureWords &a, const CaptureWords &b) {
  uint8_t m = 0;
  if (a[28] != b[28])
    m = (uint8_t) (m | 0x01u);
  if (a[29] != b[29])
    m = (uint8_t) (m | 0x02u);
  if (a[30] != b[30])
    m = (uint8_t) (m | 0x04u);
  if (((a[19] ^ b[19]) & 0xFFFEu) != 0)
    m = (uint8_t) (m | 0x08u);
  if (((a[21] ^ b[21]) & 0xFFFEu) != 0)
    m = (uint8_t) (m | 0x10u);
  return m;
}

// The dx layout over LIVE words: bit0 244 not in {0, 2}, bits 1-6 power, 7-12 SOC, 13-18 source.
constexpr uint32_t out_of_domain_mask(const CaptureWords &w) {
  uint32_t m = ecco_fallback::from_244_domain_valid(w[0]) ? 0u : 1u;
  for (size_t i = 0; i < 6; i++) {
    if (!ecco_fallback::tou_power_domain_valid(w[1 + i]))
      m |= (1u << (1 + i));
    if (!ecco_fallback::soc_domain_valid(w[7 + i]))
      m |= (1u << (7 + i));
    if (!ecco_fallback::slot_source_domain_valid(w[13 + i]))
      m |= (1u << (13 + i));
  }
  return m;
}

// ---------------------------------------------------------------------------
// Same-boot divergence rule (S1 9.2 mechanism 2)
// ---------------------------------------------------------------------------
// FBP and FBW have exactly one writer and FB-B1 writes neither, so a fresh read
// whose load code or bytes differ from the last read of that key this boot
// (the RAM mirror) sets that key's anomaly bit, even when it is neither
// READ_ERROR nor ABSENT (e.g. a VALID record that reads back CORRUPT). Bytes
// are the field-by-field stored bytes; a non-OK load reads as all zero bytes.
constexpr bool diverged(uint8_t last_load, uint8_t new_load, bool bytes_equal) {
  return last_load != new_load || !bytes_equal;
}
constexpr bool profile_diverged(uint8_t last_load, const ecco_fallback::ProfileBytes &last_bytes, uint8_t new_load,
                                const ecco_fallback::ProfileBytes &new_bytes) {
  return diverged(last_load, new_load, ecco_fbdurable::bytes_equal(last_bytes, new_bytes));
}
constexpr bool witness_diverged(uint8_t last_load, const ecco_fbdurable::ProvisionBytes &last_bytes, uint8_t new_load,
                                const ecco_fbdurable::ProvisionBytes &new_bytes) {
  return diverged(last_load, new_load, ecco_fbdurable::bytes_equal(last_bytes, new_bytes));
}

// One fresh FBP + FBW read (boot, and REVIEW-final step 4): the per-key latch
// notes, the ONE health result, the divergence rule against the RAM mirror
// (only when `baseline_valid`), the seen high-water and the RE-composed class.
struct ReadInputs {
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fallback::FallbackProfileV1 p{};
  uint8_t w_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fbdurable::FailbackProvisionV1 w{};
  bool healthy = false;
  uint8_t present_seen = 0;
  uint8_t read_anomaly = 0;
  uint32_t seen_hw_gen = 0;
  bool baseline_valid = false;
  uint8_t last_p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fallback::ProfileBytes last_p_bytes{};
  uint8_t last_w_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;
  ecco_fbdurable::ProvisionBytes last_w_bytes{};
};

struct ReadEval {
  ecco_fbdurable::ReadLatch latch{};  // present_seen / read_anomaly AFTER the notes and the divergence rule
  uint8_t p_fba_class = 0;            // ecco_fallback::classify_profile(p_load, p)
  uint8_t w_class = 0;                // ecco_fbdurable::classify_witness(w_load, w)
  uint8_t cls = 0;                    // effective class (composed with the widened latch)
  uint8_t why = 0;
  uint8_t rule = 0;
  uint32_t seen_hw_gen = 0;
  bool p_diverged = false;
  bool w_diverged = false;
};

constexpr ReadEval evaluate_read(const ReadInputs &in) {
  ReadEval out{};
  ecco_fbdurable::ReadLatch latch{in.present_seen, in.read_anomaly};
  latch = ecco_fbdurable::note_read(latch, ecco_fbdurable::KEY_BIT_PROFILE, in.p_load, in.healthy);
  latch = ecco_fbdurable::note_read(latch, ecco_fbdurable::KEY_BIT_WITNESS, in.w_load, in.healthy);
  out.p_diverged = in.baseline_valid &&
                   profile_diverged(in.last_p_load, in.last_p_bytes, in.p_load, ecco_fallback::encode_profile(in.p));
  out.w_diverged = in.baseline_valid && witness_diverged(in.last_w_load, in.last_w_bytes, in.w_load,
                                                         ecco_fbdurable::encode_provision(in.w));
  if (out.p_diverged)
    latch.read_anomaly = (uint8_t) (latch.read_anomaly | ecco_fbdurable::KEY_BIT_PROFILE);
  if (out.w_diverged)
    latch.read_anomaly = (uint8_t) (latch.read_anomaly | ecco_fbdurable::KEY_BIT_WITNESS);
  out.latch = latch;
  out.p_fba_class = ecco_fallback::classify_profile(in.p_load, in.p);
  out.w_class = ecco_fbdurable::classify_witness(in.w_load, in.w);
  const ecco_fbdurable::EffectiveProfile e =
      ecco_fbdurable::compose_profile_class(in.p_load, in.p, in.w_load, in.w, latch.read_anomaly);
  out.cls = e.cls;
  out.why = e.why;
  out.rule = e.rule;
  out.seen_hw_gen = ecco_fbdurable::next_seen_hw_gen(in.seen_hw_gen, out.p_fba_class, in.p.generation, out.w_class,
                                                     in.w.hw_generation);
  return out;
}

// ---------------------------------------------------------------------------
// REVIEW-final evaluation
// ---------------------------------------------------------------------------
// S2 3.1 prior fingerprint: authentic -> (generation, binding); CORRUPT with
// LOAD_OK -> the raw fields (untrusted); CORRUPT with WRONG_SIZE -> (0, stored
// length); everything else (NOT_CAPTURED, PROFILE_LOST, UNREADABLE) -> (0, 0).
struct PriorFingerprint {
  uint32_t generation = 0;
  uint64_t binding = 0;
};
constexpr PriorFingerprint prior_fingerprint(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p,
                                             uint32_t stored_len) {
  const uint8_t c = ecco_fallback::classify_profile(p_load, p);
  if (ecco_fbdurable::fba_authentic(c))
    return {p.generation, p.binding};
  if (c == ecco_fallback::PROFILE_CORRUPT && p_load == ecco_fallback::LOAD_OK)
    return {p.generation, p.binding};
  if (c == ecco_fallback::PROFILE_CORRUPT && p_load == ecco_fallback::LOAD_WRONG_SIZE)
    return {0u, (uint64_t) stored_len};
  return {0u, 0u};
}

// IE11: the u32 sum of the five write-attempt counters (manual_write_attempts, reg244_apply_attempts,
// reg244_restore_attempts, free_power_start_attempts, dump_start_attempts).
constexpr uint32_t writes_fingerprint(uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e) {
  return (uint32_t) (a + b + c + d + e);
}

// Wrap-safe: a candidate older than the TTL (>= 120000 ms) is expired.
constexpr bool candidate_expired(uint32_t now_ms, uint32_t born_ms) {
  return (uint32_t) (now_ms - born_ms) >= CANDIDATE_TTL_MS;
}
// B3 `exp=`: floor((120000 - age) / 1000), 0 once expired.
constexpr uint32_t exp_seconds(uint32_t now_ms, uint32_t born_ms) {
  const uint32_t age = (uint32_t) (now_ms - born_ms);
  return age >= CANDIDATE_TTL_MS ? 0u : (CANDIDATE_TTL_MS - age) / 1000u;
}

// The REVIEW final lambda's integrity check: an operation is in flight and its purpose is REVIEW.
constexpr bool review_integrity_ok(bool op_in_progress, uint8_t op_purpose) {
  return op_in_progress && op_purpose == PURPOSE_REVIEW;
}

struct ReviewInputs {
  CaptureWords words{};                  // pass 2
  uint32_t ceiling_w = ecco_fallback::V1_TOU_POWER_MAX_W;
  uint8_t cls = 0;                       // effective class after the fresh read
  uint8_t read_anomaly = 0;              // latch.read_anomaly after the fresh read
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;  // the fresh FBP read
  ecco_fallback::FallbackProfileV1 p{};
  uint32_t p_stored_len = 0;             // ReadDiag.stored_len of that read
  uint32_t salt = 0;                     // fallback_profile_boot_salt
  uint32_t seq_next = 0;                 // fallback_profile_cand_seq + 1
};

struct ReviewVerdict {
  Refusals refusals{};
  uint16_t warnings = 0;
  bool eligible = false;
  bool has_stored = false;  // a TRUSTED stored profile exists (stored_trusted): dx / dc / di are meaningful
  uint32_t prior_generation = 0;
  uint64_t prior_binding = 0;
  uint64_t id = 0;          // the candidate id when eligible, else 0
  uint32_t dx = 0;
  uint16_t dc = 0;
  uint8_t di = 0;
  TextBuf sv;
};

// The stored profile is TRUSTED: the FB-A record is authentic (VALID, INVALIDATED or CORRUPT_DOMAIN, hence also STALE)
// AND the effective class is not UNREADABLE (an earlier read anomaly, a witness that cannot be read, ...). ONE
// predicate for the review masks (has_stored: dx / dc / di) and for the saved views (saved_view: B7 / B8), so the
// operator is never shown "identical to the saved profile" (dx=00000, dc=000, di=00) next to a B7 / B8 `v=NONE`
// and a B1 UNREADABLE for the same stored profile.
constexpr bool stored_trusted(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint8_t cls) {
  return ecco_fbdurable::fba_authentic(ecco_fallback::classify_profile(p_load, p)) &&
         cls != ecco_fbdurable::EPC_UNREADABLE;
}

constexpr ReviewVerdict review_evaluate(const ReviewInputs &in) {
  ReviewVerdict v{};
  v.refusals = capture_refusals(in.words, in.ceiling_w);
  v.warnings = capture_warnings(in.words);
  v.eligible = review_eligible(v.refusals, in.cls, in.read_anomaly);
  const PriorFingerprint f = prior_fingerprint(in.p_load, in.p, in.p_stored_len);
  v.prior_generation = f.generation;
  v.prior_binding = f.binding;
  v.has_stored = stored_trusted(in.p_load, in.p, in.cls);
  if (v.has_stored) {
    const CaptureWords stored = words_of(in.p);
    v.dx = e1_delta_mask(in.words, stored);
    v.dc = ctx_mismatch_mask(in.words, stored);
    v.di = info_mismatch_mask(in.words, stored);
  }
  if (v.eligible)
    v.id = candidate_id(in.salt, in.seq_next, in.cls, f.generation, f.binding, in.words);
  v.sv = sv_text(v.refusals);
  return v;
}

// ---------------------------------------------------------------------------
// Gate inputs. The field names ARE the firmware global ids, so a lambda line
// `gi.fp.free_power_snapshot_valid = <the global of that name>;` is
// greppable on both sides.
//
// DEFAULTS ARE NOT UNIFORMLY FAIL-CLOSED - the firmware lambdas MUST assign
// EVERY field they use, explicitly (the firmware test suite pins this by parsing
// the field lists of these structs). A forgotten assignment fails closed ONLY for:
//   boot_loaded = false, fbs_slot = FBS_UNREADABLE, the three *_marker_boot_load =
//   BOOT_LOAD_NOT_LOADED (255), ProbeResults = PROBE_NONE (the gate then only asks for
//   probes and never accepts), SlotClass = OBL_UNSET, and in ReadInputs / ReviewInputs
//   the load codes (UNAVAILABLE), `healthy` (false), ReviewInputs.cls (UNREADABLE) and
//   ReviewInputs.words (all zero, refused by L2).
// Every other default is the PERMISSIVE idle value ("nothing is running, nothing is set"),
// so a forgotten assignment silently fails OPEN:
//   GateInputs: the three write-arm booleans; EVERY BusInputs field (the eleven busy
//   flags, diag_write_lock_held, the lock timestamps); FpDomain / DumpDomain /
//   R244Domain: *_recovery_metadata_corrupt, *_snapshot_valid, *_marker_state,
//   *_operator_needed, *_active_persisted, *_restore_requested, dump_containment_state
//   and every run_* bit; GateInputs.probe_latch (0 = no memory of an earlier bad
//   probe: the sticky latch would be forgotten and the caller would write that loss
//   back).
//   ReadInputs: baseline_valid (false switches the S1 9.2 divergence rule off),
//   present_seen, read_anomaly (the sticky anomaly latch) and seen_hw_gen.
//   ReviewInputs: read_anomaly, salt, seq_next (a constant candidate id) and
//   ceiling_w (8000, the loosest legal ceiling).
// The one deliberately unassigned field is `expired` (REVIEW never reads the clock).
// ---------------------------------------------------------------------------
struct BusInputs {  // FBP_TXN_BUSY terms + the stuck-lock diagnostic
  bool manual_write_in_progress = false;
  bool correction_in_progress = false;
  bool verification_pending = false;
  bool verification_read_active = false;
  bool free_power_operation_in_progress = false;
  bool free_power_recovery_force_in_progress = false;
  bool free_power_recovery_accept_in_progress = false;
  bool reg244_apply_in_progress = false;
  bool dump_operation_in_progress = false;
  bool fallback_profile_op_in_progress = false;
  bool fallback_profile_capture_dispatch_running = false;  // the capture dispatch script's is_running()
  bool diag_write_lock_held = false;
  uint32_t diag_write_lock_since_ms = 0;
  uint32_t now_ms = 0;  // the lambda's current millisecond uptime
};

struct FpDomain {
  uint8_t free_power_marker_boot_load = BOOT_LOAD_NOT_LOADED;
  bool free_power_recovery_metadata_corrupt = false;
  bool free_power_snapshot_valid = false;
  uint8_t free_power_marker_state = MARKER_STATE_CLEAR;
  bool free_power_operator_needed = false;
  bool free_power_active_persisted = false;
  bool free_power_restore_requested = false;
  bool expired = false;       // REVIEW does not read the clock: the lambda passes false
  bool run_start = false;     // is_running(): start_free_power_override
  bool run_restore = false;   // is_running(): restore_free_power_snapshot(_dispatch)
  bool run_operator = false;  // is_running(): free_power_recovery_review / force_restore / accept_current_state (+ dispatches)
};

struct DumpDomain {
  uint8_t dump_marker_boot_load = BOOT_LOAD_NOT_LOADED;
  bool dump_recovery_metadata_corrupt = false;
  uint8_t dump_containment_state = 0;
  bool dump_snapshot_valid = false;
  uint8_t dump_marker_state = MARKER_STATE_CLEAR;
  bool dump_operator_needed = false;
  bool dump_active_persisted = false;
  bool dump_restore_requested = false;  // never a clear-term
  bool expired = false;
  bool run_start = false;    // is_running(): start_dump_to_grid_override
  bool run_restore = false;  // is_running(): restore_dump_to_grid_snapshot
};

struct R244Domain {
  uint8_t reg244_marker_boot_load = BOOT_LOAD_NOT_LOADED;
  bool reg244_recovery_metadata_corrupt = false;
  bool reg244_snapshot_valid = false;
  uint8_t reg244_marker_state = MARKER_STATE_CLEAR;
  bool run_apply = false;    // is_running(): apply_reg244_settings
  bool run_restore = false;  // is_running(): restore_reg244_snapshot
};

struct GateInputs {
  bool boot_loaded = false;  // fallback_profile_boot_loaded
  uint8_t fbs_slot = ecco_fbdurable::FBS_UNREADABLE;  // fallback_profile_fbs_slot
  uint16_t probe_latch = 0;  // fallback_profile_probe_latch
  bool free_power_write_enable = false;      // the three write arms' .state
  bool dump_write_enable = false;
  bool manual_config_write_enable = false;
  BusInputs bus{};
  FpDomain fp{};
  DumpDomain dump{};
  R244Domain r244{};
};

struct ProbeResults {  // one ProbeCode per lease marker; PROBE_NONE = not probed
  uint8_t fp = PROBE_NONE;
  uint8_t dump = PROBE_NONE;
  uint8_t r244 = PROBE_NONE;
};

struct SlotClass {  // {kind, basis}; the default (OBL_UNSET) is never clear
  uint8_t kind = OBL_UNSET;
  uint8_t basis = BASIS_NONE;
};

// ---------------------------------------------------------------------------
// Marker probe and the sticky latch
// ---------------------------------------------------------------------------
// One marker read (ecco_fbdurable::read_direct_t load code + the record's magic and state).
constexpr uint8_t probe_result(uint8_t load, uint32_t magic, uint8_t state) {
  if (load == ecco_fallback::LOAD_ABSENT)
    return PROBE_ABSENT;
  if (load == ecco_fallback::LOAD_WRONG_SIZE)
    return PROBE_MALFORMED;
  if (load != ecco_fallback::LOAD_OK)
    return PROBE_UNREADABLE;
  if (magic != MARKER_RECORD_MAGIC)
    return PROBE_MALFORMED;
  if (state == MARKER_STATE_CLEAR)
    return PROBE_CLEAR;
  if (state == MARKER_STATE_RESTORE_REQUIRED)
    return PROBE_RESTORE_REQUIRED;
  if (state == MARKER_STATE_PENDING_CLEAR)
    return PROBE_PENDING_CLEAR;
  return PROBE_MALFORMED;
}

// The latch code a probe result sets (LATCH_NONE for CLEAR, ABSENT and "not probed").
constexpr uint8_t probe_latch_code(uint8_t probe) {
  return probe == PROBE_UNREADABLE          ? LATCH_UNREADABLE
         : probe == PROBE_MALFORMED         ? LATCH_MALFORMED
         : probe == PROBE_RESTORE_REQUIRED  ? LATCH_GHOST_RR
         : probe == PROBE_PENDING_CLEAR     ? LATCH_GHOST_PC
                                            : LATCH_NONE;
}

constexpr uint8_t latch_get(uint16_t latch, uint8_t domain) {
  return domain <= 3 ? (uint8_t) ((latch >> (4 * domain)) & 0xFu) : (uint8_t) 0;
}
// SET-ONLY: a non-zero nibble is never changed and code 0 never writes.
constexpr uint16_t latch_set(uint16_t latch, uint8_t domain, uint8_t code) {
  if (domain > 3 || code == 0 || latch_get(latch, domain) != 0)
    return latch;
  return (uint16_t) (latch | ((code & 0xFu) << (4 * domain)));
}
// B3 `latch=`: the latched domains in the order FP,DP,R4 ("FP,R4"), or -.
constexpr TextBuf latch_text(uint16_t latch) {
  TextBuf t;
  bool any = false;
  for (uint8_t dom = DOM_FP; dom <= DOM_R244; dom++) {
    if (latch_get(latch, dom) != 0) {
      if (any)
        put_char(t, ',');
      put(t, dom == DOM_FP ? "FP" : dom == DOM_DUMP ? "DP" : "R4");
      any = true;
    }
  }
  if (!any)
    put_char(t, '-');
  return t;
}

// ---------------------------------------------------------------------------
// Per-domain classifiers (S1 4.4). Rows are evaluated top to bottom and the
// first match wins. `probe` is the durable leg: PROBE_NONE = not probed, which
// is how a RAM-clear lease domain shows (UNK_NOT_PROBED). The boot truth is
// the PAIR (*_marker_boot_load, *_recovery_metadata_corrupt): READ_ERROR + the
// flag is UNKNOWN (unreadable at boot), the flag alone is a hard lockout.
// ---------------------------------------------------------------------------
// Rows 1-4, shared by FP, DUMP and R244. OBL_UNSET = no early row matched.
constexpr SlotClass early_rows(bool boot_loaded, uint8_t load, bool corrupt, uint8_t latch_code) {
  if (!boot_loaded || load > BOOT_LOAD_READ_ERROR)
    return {UNK_BOOT_NOT_LOADED, BASIS_NONE};
  if (corrupt && load == BOOT_LOAD_READ_ERROR)
    return {UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR};
  if (corrupt)
    return {UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT};
  if (load == BOOT_LOAD_WRONG_SIZE || load == BOOT_LOAD_READ_ERROR)  // boot truth contradicts the flag
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  if (latch_code == LATCH_UNREADABLE)
    return {UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE};
  if (latch_code == LATCH_MALFORMED)
    return {UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE};
  if (latch_code == LATCH_GHOST_RR)
    return {UNK_DIVERGED, BASIS_GHOST_RR};
  if (latch_code == LATCH_GHOST_PC)
    return {UNK_DIVERGED, BASIS_GHOST_PC};
  if (latch_code != LATCH_NONE)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  return {OBL_UNSET, BASIS_NONE};
}

// The durable-leg rows, reached only when every RAM leg is clear.
constexpr SlotClass probe_rows(uint8_t probe) {
  if (probe == PROBE_NONE)
    return {UNK_NOT_PROBED, BASIS_NONE};
  if (probe == PROBE_RESTORE_REQUIRED)
    return {UNK_DIVERGED, BASIS_GHOST_RR};
  if (probe == PROBE_PENDING_CLEAR)
    return {UNK_DIVERGED, BASIS_GHOST_PC};
  if (probe == PROBE_MALFORMED)
    return {UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE};
  if (probe == PROBE_CLEAR)
    return {OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR};
  if (probe == PROBE_ABSENT)
    return {OBL_CLEAR_PROVEN, BASIS_ABSENT};
  return {UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE};
}

constexpr SlotClass classify_fp(const GateInputs &g, uint8_t probe) {
  const FpDomain &d = g.fp;
  const BusInputs &b = g.bus;
  const SlotClass early = early_rows(g.boot_loaded, d.free_power_marker_boot_load,
                                     d.free_power_recovery_metadata_corrupt, latch_get(g.probe_latch, DOM_FP));
  if (early.kind != OBL_UNSET)
    return early;
  const bool sv = d.free_power_snapshot_valid;
  const uint8_t ms = d.free_power_marker_state;
  if (b.free_power_recovery_force_in_progress || b.free_power_recovery_accept_in_progress || d.run_operator)
    return {OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING};
  if (d.run_restore)
    return {OBL_ENDING, BASIS_RESTORE_RUNNING};
  if (d.run_start && !sv)
    return {OBL_STARTING, BASIS_PRE_COMMIT};
  if (d.run_start && sv)
    return {OBL_STARTING, BASIS_COMMITTED};
  if (b.free_power_operation_in_progress)
    return {UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED};
  if (sv && ms == MARKER_STATE_PENDING_CLEAR)
    return {OBL_PENDING_CLEAR, BASIS_NONE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED && d.free_power_operator_needed)
    return {OBL_OPERATOR_NEEDED, BASIS_NONE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED && d.free_power_active_persisted && !d.free_power_restore_requested &&
      !d.expired)
    return {OBL_ACTIVE, BASIS_LEASE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED)
    return {OBL_RESTORE_REQUIRED, BASIS_NONE};
  if (sv)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  if (d.free_power_active_persisted || d.free_power_restore_requested || ms != MARKER_STATE_CLEAR)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  return probe_rows(probe);
}

constexpr SlotClass classify_dump(const GateInputs &g, uint8_t probe) {
  const DumpDomain &d = g.dump;
  const BusInputs &b = g.bus;
  const SlotClass early = early_rows(g.boot_loaded, d.dump_marker_boot_load, d.dump_recovery_metadata_corrupt,
                                     latch_get(g.probe_latch, DOM_DUMP));
  if (early.kind != OBL_UNSET)
    return early;
  const bool sv = d.dump_snapshot_valid;
  const uint8_t ms = d.dump_marker_state;
  if (d.dump_containment_state != 0)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  if (d.run_restore)
    return {OBL_ENDING, BASIS_RESTORE_RUNNING};
  if (d.run_start && !sv)
    return {OBL_STARTING, BASIS_PRE_COMMIT};
  if (d.run_start && sv)
    return {OBL_STARTING, BASIS_COMMITTED};
  if (b.dump_operation_in_progress)
    return {UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED};
  if (sv && ms == MARKER_STATE_PENDING_CLEAR)
    return {OBL_PENDING_CLEAR, BASIS_NONE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED && d.dump_operator_needed)
    return {OBL_OPERATOR_NEEDED, BASIS_NONE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED && d.dump_active_persisted && !d.dump_restore_requested && !d.expired)
    return {OBL_ACTIVE, BASIS_LEASE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED)
    return {OBL_RESTORE_REQUIRED, BASIS_NONE};
  if (sv)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  if (d.dump_active_persisted || d.dump_operator_needed || ms != MARKER_STATE_CLEAR)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  return probe_rows(probe);
}

constexpr SlotClass classify_r244(const GateInputs &g, uint8_t probe) {
  const R244Domain &d = g.r244;
  const BusInputs &b = g.bus;
  const SlotClass early = early_rows(g.boot_loaded, d.reg244_marker_boot_load, d.reg244_recovery_metadata_corrupt,
                                     latch_get(g.probe_latch, DOM_R244));
  if (early.kind != OBL_UNSET)
    return early;
  const bool sv = d.reg244_snapshot_valid;
  const uint8_t ms = d.reg244_marker_state;
  if (d.run_restore)
    return {OBL_ENDING, BASIS_RESTORE_RUNNING};
  if (d.run_apply && !sv)
    return {OBL_STARTING, BASIS_PRE_COMMIT};
  if (d.run_apply && sv)
    return {OBL_STARTING, BASIS_COMMITTED};
  if (b.reg244_apply_in_progress)
    return {UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED};
  if (sv && ms == MARKER_STATE_PENDING_CLEAR)
    return {OBL_PENDING_CLEAR, BASIS_NONE};
  if (sv && ms == MARKER_STATE_RESTORE_REQUIRED)
    return {OBL_OPERATOR_NEEDED, BASIS_NONE};
  if (sv)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  if (ms != MARKER_STATE_CLEAR)
    return {UNK_DIVERGED, BASIS_RAM_INCONSISTENT};
  return probe_rows(probe);
}

// FBP_TXN_BUSY: any transaction owns or may own the inverter.
constexpr bool bus_busy(const BusInputs &b) {
  return b.manual_write_in_progress || b.correction_in_progress || b.verification_pending ||
         b.verification_read_active || b.free_power_operation_in_progress ||
         b.free_power_recovery_force_in_progress || b.free_power_recovery_accept_in_progress ||
         b.reg244_apply_in_progress || b.dump_operation_in_progress || b.fallback_profile_op_in_progress ||
         b.fallback_profile_capture_dispatch_running;
}
constexpr uint32_t lock_age_ms(const BusInputs &b) { return (uint32_t) (b.now_ms - b.diag_write_lock_since_ms); }
// FBP_LOCK_STUCK (decision D11): the shared write lock held for >= 300 s according to the read-only diagnostic.
constexpr bool lock_stuck(const BusInputs &b) {
  return b.manual_write_in_progress && b.diag_write_lock_held && lock_age_ms(b) >= LOCK_STUCK_MS;
}

// The most specific owner of a busy bus; the generic mutex holder comes last.
constexpr const char *bus_owner_text(const BusInputs &b) {
  return (b.free_power_operation_in_progress || b.free_power_recovery_force_in_progress ||
          b.free_power_recovery_accept_in_progress)
             ? "Free Power"
         : b.reg244_apply_in_progress    ? "Register 244 test"
         : b.dump_operation_in_progress  ? "Dump to Grid"
         : (b.fallback_profile_op_in_progress || b.fallback_profile_capture_dispatch_running) ? "Fallback Profile"
         : b.correction_in_progress      ? "clock correction"
         : (b.verification_pending || b.verification_read_active) ? "clock verification"
         : b.manual_write_in_progress    ? "manual write"
                                         : "none";
}

// The owner named in the BUS refusal. The Free Power / Dump to Grid controller ticks hold the shared write lock through
// manual_write_in_progress ALONE (they never set free_power_operation_in_progress / dump_operation_in_progress), so
// bus_owner_text() would call an ACTIVE lease "manual write" while the vector says FP:AC / DP:AC. When the generic mutex
// flag is the ONLY owner flag set and the gate's own classification of a lease slot says OBL_ACTIVE, that domain is
// named (Free Power before Dump to Grid, the order of the owner chain); in every other case this is bus_owner_text().
// Wording only: the slot precedence and every refusal code are unchanged.
constexpr const char *bus_owner_text_with_leases(const BusInputs &b, const SlotClass &fp_slot, const SlotClass &dump_slot) {
  const bool mutex_only =
      b.manual_write_in_progress &&
      !(b.correction_in_progress || b.verification_pending || b.verification_read_active ||
        b.free_power_operation_in_progress || b.free_power_recovery_force_in_progress ||
        b.free_power_recovery_accept_in_progress || b.reg244_apply_in_progress || b.dump_operation_in_progress ||
        b.fallback_profile_op_in_progress || b.fallback_profile_capture_dispatch_running);
  if (mutex_only && fp_slot.kind == OBL_ACTIVE)
    return "Free Power";
  if (mutex_only && dump_slot.kind == OBL_ACTIVE)
    return "Dump to Grid";
  return bus_owner_text(b);
}

constexpr SlotClass classify_bus(const GateInputs &g) {
  if (lock_stuck(g.bus))
    return {UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK};
  if (bus_busy(g.bus))
    return {BUS_BUSY, BASIS_BUS_TXN};
  return {OBL_CLEAR_PROVEN, BASIS_BUS_IDLE};
}

// FBS is read once at boot into fallback_profile_fbs_slot and never probed at runtime.
constexpr SlotClass classify_fbs(const GateInputs &g) {
  if (!g.boot_loaded)
    return {UNK_BOOT_NOT_LOADED, BASIS_NONE};
  if (g.fbs_slot == ecco_fbdurable::FBS_CLEAR_ABSENT)
    return {OBL_CLEAR_PROVEN, BASIS_ABSENT};
  if (g.fbs_slot == ecco_fbdurable::FBS_CLEAR_VALID)
    return {OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR};
  if (g.fbs_slot == ecco_fbdurable::FBS_OBLIGATION)
    return {OBL_ACTIVE, BASIS_FBS_EPISODE};
  if (g.fbs_slot == ecco_fbdurable::FBS_CORRUPT)
    return {UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT};
  return {UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR};  // FBS_UNREADABLE and any unknown value
}

// MTOU_JOURNAL_NOT_IMPLEMENTED: Manual TOU has no durable state; its in-flight
// state is exactly the shared mutex, so the slot is clear iff the BUS slot is clear.
constexpr SlotClass classify_mtou(const GateInputs &g) {
  if (!g.boot_loaded)
    return {UNK_BOOT_NOT_LOADED, BASIS_NONE};
  if (MTOU_JOURNAL_NOT_IMPLEMENTED && classify_bus(g).kind == OBL_CLEAR_PROVEN)
    return {OBL_CLEAR_PROVEN, BASIS_NO_DURABLE_STATE};
  return {UNK_NOT_PROBED, BASIS_NONE};
}

// The S5 alphabet entry of one slot (BUS reads OK / BY / LK).
constexpr const char *obl_code(uint8_t kind, uint8_t basis) {
  switch (kind) {
    case OBL_CLEAR_PROVEN:
      return basis == BASIS_MARKER_CLEAR      ? "CM"
             : basis == BASIS_ABSENT          ? "CA"
             : basis == BASIS_NO_DURABLE_STATE ? "CN"
             : basis == BASIS_BUS_IDLE        ? "OK"
                                              : "UR";
    case OBL_ACTIVE:
      return "AC";
    case OBL_STARTING:
      return "ST";
    case OBL_RESTORE_REQUIRED:
      return "RR";
    case OBL_PENDING_CLEAR:
      return "PC";
    case OBL_ENDING:
      return "EN";
    case OBL_OPERATOR_NEEDED:
      return "ON";
    case UNK_METADATA_CORRUPT:
      return "MC";
    case UNK_BOOT_NOT_LOADED:
      return "BL";
    case UNK_DIVERGED:
      return "DV";
    case UNK_BUS_OR_LOCK_STUCK:
      return "LK";
    case UNK_NOT_PROBED:
      return "NP";
    case BUS_BUSY:
      return "BY";
    default:
      return "UR";  // UNK_DURABLE_UNREADABLE, OBL_UNSET and anything unknown
  }
}

// B3 `obl=` value: FP:xx,DP:xx,R4:xx,MT:xx,FS:xx,BUS:xx
constexpr TextBuf vector_text(const SlotClass &fp, const SlotClass &dump, const SlotClass &r244, const SlotClass &mtou,
                              const SlotClass &fbs, const SlotClass &bus) {
  TextBuf t;
  put(t, "FP:");
  put(t, obl_code(fp.kind, fp.basis));
  put(t, ",DP:");
  put(t, obl_code(dump.kind, dump.basis));
  put(t, ",R4:");
  put(t, obl_code(r244.kind, r244.basis));
  put(t, ",MT:");
  put(t, obl_code(mtou.kind, mtou.basis));
  put(t, ",FS:");
  put(t, obl_code(fbs.kind, fbs.basis));
  put(t, ",BUS:");
  put(t, obl_code(bus.kind, bus.basis));
  return t;
}

constexpr bool slot_ram_clear(const SlotClass &c) { return c.kind == OBL_CLEAR_PROVEN || c.kind == UNK_NOT_PROBED; }

// ---------------------------------------------------------------------------
// Gate texts: REVIEW REFUSED - ...
// ---------------------------------------------------------------------------
constexpr char REFUSED_PREFIX[] = "REVIEW REFUSED - ";
constexpr char NOT_COMPLETED_PREFIX[] = "REVIEW NOT COMPLETED - ";

constexpr TextBuf refused_in_flight_text() {
  TextBuf t;
  put(t, REFUSED_PREFIX);
  put(t, "another Fallback Profile operation is in progress");
  return t;
}
constexpr TextBuf refused_not_loaded_text() {
  TextBuf t;
  put(t, REFUSED_PREFIX);
  put(t, "durable state not loaded yet (starting up)");
  return t;
}
constexpr TextBuf refused_arms_text() {
  TextBuf t;
  put(t, REFUSED_PREFIX);
  put(t, "a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first");
  return t;
}

// One slot's refusal (S1 4.5). `owner` names the bus owner, `lock_age_s` the stuck lock age in seconds,
// `dump_containment` the Dump K detail.
constexpr TextBuf refusal_text(uint8_t slot, const SlotClass &c, uint8_t dump_containment, const char *owner,
                               uint32_t lock_age_s) {
  TextBuf t;
  const char *d = domain_label(slot);
  put(t, REFUSED_PREFIX);
  if (slot == SLOT_BUS) {
    if (c.kind == UNK_BUS_OR_LOCK_STUCK) {
      put(t, "inverter write lock held for ");
      put_u(t, lock_age_s);
      put(t, " s (possible leak); a reboot may be required");
    } else {
      put(t, "another inverter transaction is in progress (");
      put(t, owner);
      put(t, "); try again shortly");
    }
    return t;
  }
  if (c.kind == UNK_BOOT_NOT_LOADED)
    return refused_not_loaded_text();
  if (c.kind == UNK_DURABLE_UNREADABLE) {
    if (c.basis == BASIS_RUNTIME_PROBE) {
      put(t, d);
      put(t, " recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read "
             "absent: verify live settings first; do not erase NVS");
    } else {
      put(t, d);
      put(t, " recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback "
             "never proceeds past it");
    }
    return t;
  }
  if (c.kind == UNK_METADATA_CORRUPT) {
    put(t, d);
    if (c.basis == BASIS_RUNTIME_PROBE) {
      put(t, " recovery marker is malformed (found at runtime); review blocked until reboot, which re-derives it as "
             "a hard lockout");
    } else {
      put(t, " recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not "
             "erase NVS");
      if (slot == SLOT_DUMP && dump_containment != 0) {
        put(t, "; containment K=");
        put_u(t, dump_containment);
      }
    }
    return t;
  }
  if (c.kind == UNK_DIVERGED) {
    put(t, d);
    if (c.basis == BASIS_GHOST_RR || c.basis == BASIS_GHOST_PC) {
      put(t, " stored marker says ");
      put(t, c.basis == BASIS_GHOST_RR ? "RESTORE_REQUIRED" : "PENDING_CLEAR");
      put(t, " but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore "
             "its saved original)");
    } else {
      put(t, " in-memory recovery state is inconsistent; a reboot must re-derive it before review");
    }
    return t;
  }
  if (c.kind == UNK_BUS_OR_LOCK_STUCK) {
    put(t, d);
    put(t, " in-progress flag is set with no running operation (possible leak); a reboot re-derives it");
    return t;
  }
  if (c.kind == OBL_ACTIVE) {
    if (c.basis == BASIS_FBS_EPISODE) {
      put(t, "a failback episode record exists; only the firmware that created it can resolve it");
    } else {
      put(t, d);
      put(t, " is active; live settings are a temporary overlay - end it first");
    }
    return t;
  }
  if (c.kind == OBL_RESTORE_REQUIRED) {
    put(t, d);
    put(t, " must restore original settings first");
    return t;
  }
  if (c.kind == OBL_PENDING_CLEAR) {
    put(t, d);
    put(t, " restore verified; durable clear still pending");
    if (slot == SLOT_R244)
      put(t, " - press Restore Original (armed)");
    return t;
  }
  if (c.kind == OBL_OPERATOR_NEEDED) {
    put(t, d);
    put(t, " needs an operator recovery action first");
    return t;
  }
  if (c.kind == OBL_STARTING) {
    put(t, "a ");
    put(t, d);
    put(t, " start is in progress; live settings are about to become a temporary overlay");
    return t;
  }
  if (c.kind == OBL_ENDING) {
    put(t, "a ");
    put(t, d);
    put(t, " restore or recovery action is running; try again when it finishes");
    return t;
  }
  put(t, d);
  put(t, " state does not permit a review");
  return t;
}

// ---------------------------------------------------------------------------
// The gate: V1-V7 in ONE pure call
// ---------------------------------------------------------------------------
struct GateResult {
  uint8_t code = GATE_UNSET;
  uint8_t slot = SLOT_NONE;  // the first non-clear slot of a slot refusal
  bool probe_fp = false;     // GATE_NEED_PROBE: probe these markers
  bool probe_dump = false;
  bool probe_r244 = false;
  uint16_t latch = 0;        // the probe latch AFTER this decision (set-only)
  SlotClass bus{};
  SlotClass fbs{};
  SlotClass fp{};
  SlotClass dump{};
  SlotClass r244{};
  SlotClass mtou{};
  TextBuf obl;   // B3 obl= value (empty for GATE_REFUSE_IN_FLIGHT)
  TextBuf text;  // the REVIEW REFUSED text of a refusal
};

constexpr bool arms_on(const GateInputs &g) {
  return g.free_power_write_enable || g.dump_write_enable || g.manual_config_write_enable;
}

// V1 in-flight (touches nothing) -> V2 boot loaded -> V3 arms -> V4 BUS -> V5 FBS -> V6 FP, DUMP, R244, MTOU RAM legs
// -> V7 durable probes. The RAM legs are ALWAYS evaluated (the vector is complete); the three marker probes are
// consumed only when every other slot is clear: with all RAM legs clear and a lease marker not probed yet the
// answer is GATE_NEED_PROBE (the flagged probes) and the caller calls again with the results. A domain whose
// RAM leg is clear and whose probe came back UNREADABLE / MALFORMED / RESTORE_REQUIRED / PENDING_CLEAR is
// latched (never cleared, never probed again this boot) and refuses.
constexpr GateResult gate_decide(const GateInputs &g, const ProbeResults &pr) {
  GateResult r{};
  r.latch = g.probe_latch;
  if (g.bus.fallback_profile_op_in_progress || g.bus.fallback_profile_capture_dispatch_running) {
    r.code = GATE_REFUSE_IN_FLIGHT;
    r.text = refused_in_flight_text();
    return r;
  }
  r.bus = classify_bus(g);
  r.fbs = classify_fbs(g);
  r.fp = classify_fp(g, pr.fp);
  r.dump = classify_dump(g, pr.dump);
  r.r244 = classify_r244(g, pr.r244);
  r.mtou = classify_mtou(g);
  r.obl = vector_text(r.fp, r.dump, r.r244, r.mtou, r.fbs, r.bus);
  if (classify_fp(g, PROBE_NONE).kind == UNK_NOT_PROBED)
    r.latch = latch_set(r.latch, DOM_FP, probe_latch_code(pr.fp));
  if (classify_dump(g, PROBE_NONE).kind == UNK_NOT_PROBED)
    r.latch = latch_set(r.latch, DOM_DUMP, probe_latch_code(pr.dump));
  if (classify_r244(g, PROBE_NONE).kind == UNK_NOT_PROBED)
    r.latch = latch_set(r.latch, DOM_R244, probe_latch_code(pr.r244));
  if (!g.boot_loaded) {
    r.code = GATE_REFUSE_NOT_LOADED;
    r.text = refused_not_loaded_text();
    return r;
  }
  if (arms_on(g)) {
    r.code = GATE_REFUSE_ARMS;
    r.text = refused_arms_text();
    return r;
  }
  const SlotClass slots[6] = {r.bus, r.fbs, r.fp, r.dump, r.r244, r.mtou};
  const uint8_t codes[6] = {GATE_REFUSE_BUS,  GATE_REFUSE_FBS,  GATE_REFUSE_FP,
                            GATE_REFUSE_DUMP, GATE_REFUSE_R244, GATE_REFUSE_MTOU};
  for (uint8_t slot = 0; slot < 6; slot++) {
    if (!slot_ram_clear(slots[slot])) {
      r.code = codes[slot];
      r.slot = slot;
      r.text = refusal_text(slot, slots[slot], g.dump.dump_containment_state,
                            bus_owner_text_with_leases(g.bus, r.fp, r.dump), lock_age_ms(g.bus) / 1000u);
      return r;
    }
  }
  r.probe_fp = r.fp.kind == UNK_NOT_PROBED;
  r.probe_dump = r.dump.kind == UNK_NOT_PROBED;
  r.probe_r244 = r.r244.kind == UNK_NOT_PROBED;
  r.code = (r.probe_fp || r.probe_dump || r.probe_r244) ? GATE_NEED_PROBE : GATE_ACCEPT;
  return r;
}

// ---------------------------------------------------------------------------
// Housekeeping tick (10 s, RAM only)
// ---------------------------------------------------------------------------
// IE7: the first lease domain whose RAM legs are not clear (SLOT_FP / SLOT_DUMP / SLOT_R244), else SLOT_NONE.
// Only boot_loaded, probe_latch, bus, fp, dump and r244 of `g` are read.
constexpr uint8_t lease_domain_nonclear(const GateInputs &g) {
  if (!slot_ram_clear(classify_fp(g, PROBE_NONE)))
    return SLOT_FP;
  if (!slot_ram_clear(classify_dump(g, PROBE_NONE)))
    return SLOT_DUMP;
  if (!slot_ram_clear(classify_r244(g, PROBE_NONE)))
    return SLOT_R244;
  return SLOT_NONE;
}

// Leak breaker: an operation flag set, no dispatch running and older than BREAKER_MS.
constexpr bool breaker_fired(bool op_in_progress, bool dispatch_running, uint32_t now_ms, uint32_t started_ms) {
  return op_in_progress && !dispatch_running && (uint32_t) (now_ms - started_ms) > BREAKER_MS;
}

// ---------------------------------------------------------------------------
// B1-B8 grammars: k=v;, fixed key order, every key always present, `-` = n/a,
// values in [A-Za-z0-9_.,:/>+-], hard cap 200
// ---------------------------------------------------------------------------
// B2 Summary: g;id;at;ld;df;w;hw;op;why;werr;us. g / id / at only for an AUTHENTIC record; df only for a
// LOAD_OK CORRUPT / CORRUPT_DOMAIN record; hw / op only for a valid witness. `why` is the why of the
// effective composition of the mirror; werr / us are 0 in FB-B1 (both render -).
constexpr TextBuf b2_text(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint8_t w_load,
                          const ecco_fbdurable::FailbackProvisionV1 &w, uint8_t why, uint32_t last_err,
                          uint32_t last_us) {
  TextBuf t;
  const uint8_t fba = ecco_fallback::classify_profile(p_load, p);
  const bool authentic = ecco_fbdurable::fba_authentic(fba);
  const uint8_t wc = ecco_fbdurable::classify_witness(w_load, w);
  const bool witness_ok = wc == ecco_fbdurable::W_VALID;
  put(t, "g=");
  if (authentic)
    put_u(t, p.generation);
  else
    put_char(t, '-');
  put(t, ";id=");
  if (authentic)
    put_hex(t, p.binding, 16);
  else
    put_char(t, '-');
  put(t, ";at=");
  if (authentic)
    put_u(t, p.captured_epoch);
  else
    put_char(t, '-');
  put(t, ";ld=");
  put(t, ld_name(p_load));
  put(t, ";df=");
  if (p_load == ecco_fallback::LOAD_OK &&
      (fba == ecco_fallback::PROFILE_CORRUPT || fba == ecco_fallback::PROFILE_CORRUPT_DOMAIN))
    put(t, df_name((uint8_t) ecco_fallback::profile_defect(p)));
  else
    put_char(t, '-');
  put(t, ";w=");
  put(t, w_name(w_view(fba, wc, p.generation, w.hw_generation)));
  put(t, ";hw=");
  if (witness_ok)
    put_u(t, w.hw_generation);
  else
    put_char(t, '-');
  put(t, ";op=");
  put(t, witness_ok ? op_name(w.last_op) : "-");
  put(t, ";why=");
  put(t, why_name(why));
  put(t, ";werr=");
  if (last_err == 0) {
    put_char(t, '-');
  } else {
    put_char(t, 'E');
    put_hex(t, last_err, 1);
  }
  put(t, ";us=");
  if (last_us == 0)
    put_char(t, '-');
  else
    put_u(t, last_us);
  return t;
}

// Grammar widths of the two caller-supplied B3 values: the obl vector `FP:xx,DP:xx,R4:xx,MT:xx,FS:xx,BUS:xx` is
// 36 characters and the widest sv `NO:c1,c2,c3+N` is 23 (26 leaves headroom). With both bounded, B3 is at most
// 172 characters whatever the other arguments are, so it can never reach TEXT_CAP.
constexpr size_t B3_OBL_MAX = 36;
constexpr size_t B3_SV_MAX = 26;

// True iff `s` is a usable B3 value: non-null, non-empty and NUL-terminated within `max_chars` characters (at
// most max_chars + 1 bytes are read, so an unterminated or over-long buffer cannot run away).
constexpr bool b3_value_fits(const char *s, size_t max_chars) {
  if (s == nullptr || s[0] == '\0')
    return false;
  for (size_t i = 1; i <= max_chars; i++) {
    if (s[i] == '\0')
      return true;
  }
  return false;
}

// B3 Review: st;prior;exp;warn;obl;latch;sv. prior / exp / warn / sv are `-` unless a candidate (or a
// not-saveable preview) exists. `obl` is the persisted vector text; `sv` the L2 verdict.
// ROBUSTNESS RULE (every key is ALWAYS present, whatever the caller passes): an `obl` that is null, empty or
// longer than B3_OBL_MAX renders `-` (never evaluated), and likewise an `sv` that is null, empty or longer than
// B3_SV_MAX renders `-`; a value is never cut mid-way, so a truncated vector can never read as a real one. The
// producers (vector_text, sv_text) stay inside the bounds, so the rule only matters for a corrupted caller value.
// The charset of the two values is the caller's contract (they come from vector_text and sv_text).
constexpr TextBuf b3_text(uint8_t capture_state, bool have_cand, uint8_t prior_cls, uint32_t exp_s, uint16_t warn_mask,
                          const char *obl, uint16_t latch, const char *sv) {
  TextBuf t;
  put(t, "st=");
  put(t, capture_state_name(capture_state));
  put(t, ";prior=");
  if (have_cand)
    put(t, epc_name(prior_cls));
  else
    put_char(t, '-');
  put(t, ";exp=");
  if (have_cand)
    put_u(t, exp_s);
  else
    put_char(t, '-');
  put(t, ";warn=");
  if (have_cand)
    put(t, warn_text(warn_mask).c_str());
  else
    put_char(t, '-');
  put(t, ";obl=");
  if (b3_value_fits(obl, B3_OBL_MAX))
    put(t, obl);
  else
    put_char(t, '-');
  put(t, ";latch=");
  put(t, latch_text(latch).c_str());
  put(t, ";sv=");
  if (have_cand && b3_value_fits(sv, B3_SV_MAX))
    put(t, sv);
  else
    put_char(t, '-');
  return t;
}

// `<HHMM %04u>/<W>/<SOC>/<SRC full word>` of slot n (1-6).
constexpr void put_slot_tuple(TextBuf &t, const CaptureWords &w, uint8_t n) {
  put_u(t, w[21 + n], 4);
  put_char(t, '/');
  put_u(t, w[n]);
  put_char(t, '/');
  put_u(t, w[6 + n]);
  put_char(t, '/');
  put_u(t, w[12 + n]);
}
constexpr void put_slots_body(TextBuf &t, const CaptureWords &w) {
  put(t, "244=");
  put_u(t, w[0]);
  for (uint8_t n = 1; n <= 6; n++) {
    put_char(t, ';');
    put_u(t, n);
    put_char(t, '=');
    put_slot_tuple(t, w, n);
  }
}
constexpr void put_context_body(TextBuf &t, const CaptureWords &w) {
  put(t, "232=");
  put_hex(t, w[19], 4);
  put(t, ";243=");
  put_u(t, w[20]);
  put(t, ";248=");
  put_hex(t, w[21], 4);
  put(t, ";ring=");
  put(t, ring_valid(w) ? "OK" : "BAD");
  put(t, ";230=");
  put_u(t, w[28]);
  put(t, ";245=");
  put_u(t, w[29]);
  put(t, ";247=");
  put_hex(t, w[30], 4);
}

// B5 Review Slots (candidate only): v=CAND|NONE;g=-;244;1..6;dx (dx is - without a TRUSTED stored profile: see stored_trusted).
constexpr TextBuf b5_text(bool have_cand, const CaptureWords &w, bool have_stored, uint32_t dx) {
  TextBuf t;
  if (!have_cand) {
    put(t, "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-");
    return t;
  }
  put(t, "v=CAND;g=-;");
  put_slots_body(t, w);
  put(t, ";dx=");
  if (have_stored)
    put_hex(t, dx, 5);
  else
    put_char(t, '-');
  return t;
}

// B6 Review Context (candidate only): v;232;243;248;ring;230;245;247;dc;di.
constexpr TextBuf b6_text(bool have_cand, const CaptureWords &w, bool have_stored, uint16_t dc, uint8_t di) {
  TextBuf t;
  if (!have_cand) {
    put(t, "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-");
    return t;
  }
  put(t, "v=CAND;");
  put_context_body(t, w);
  put(t, ";dc=");
  if (have_stored)
    put_hex(t, dc, 3);
  else
    put_char(t, '-');
  put(t, ";di=");
  if (have_stored)
    put_hex(t, di, 2);
  else
    put_char(t, '-');
  return t;
}

// The SAVED form of B7 (the widest of the two saved views); the caller checks `overflow`.
constexpr void put_b7_saved(TextBuf &t, const ecco_fallback::FallbackProfileV1 &p) {
  put(t, "v=SAVED;g=");
  put_u(t, p.generation);
  put_char(t, ';');
  put_slots_body(t, words_of(p));
  put(t, ";dx=-;b=");
  put_hex(t, p.binding >> 32, 8);
}

// SAVED view: ONE predicate decides B7 AND B8, so the two entities can never disagree about whether a saved
// profile exists. True iff the stored profile is trusted (stored_trusted: authentic - VALID, INVALIDATED,
// CORRUPT_DOMAIN, hence also STALE - and the effective class is not UNREADABLE) and the B7 SAVED text fits TEXT_CAP
// (the review masks share the first clause, not the length one). An authentic CORRUPT_DOMAIN record with
// every value 5 digits wide would make B7 exceed 200 characters: then NEITHER view claims a saved profile (both
// publish their NONE form) instead of B7 saying "none" next to a B8 that says "saved".
constexpr bool saved_view(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint8_t cls) {
  if (!stored_trusted(p_load, p, cls))
    return false;
  TextBuf probe;
  put_b7_saved(probe, p);
  return !probe.overflow;
}

// B7 Slots (saved profile only): v=SAVED|NONE;g;244;1..6;dx=-;b (b = the high 32 bits of the binding). When
// saved_view() is false (not authentic, UNREADABLE, or over 200 characters) the NONE form is published, never a
// truncated text.
constexpr TextBuf b7_text(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint8_t cls) {
  TextBuf t;
  if (saved_view(p_load, p, cls)) {
    put_b7_saved(t, p);
    return t;
  }
  put(t, "v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-");
  return t;
}

// B8 Context (saved profile only): v;232;243;248;ring;230;245;247;dc=-;di=-;b. Same predicate as B7.
constexpr TextBuf b8_text(uint8_t p_load, const ecco_fallback::FallbackProfileV1 &p, uint8_t cls) {
  TextBuf t;
  if (saved_view(p_load, p, cls)) {
    put(t, "v=SAVED;");
    put_context_body(t, words_of(p));
    put(t, ";dc=-;di=-;b=");
    put_hex(t, p.binding >> 32, 8);
    return t;
  }
  put(t, "v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-");
  return t;
}

// ---------------------------------------------------------------------------
// B9 Last Action-Result texts: `<OUTCOME> - detail`, <= 200, and never a word
// the Energy Actions card patterns match (pinned, case-insensitive).
// ---------------------------------------------------------------------------
constexpr TextBuf b9_seed_text() {
  TextBuf t;
  put(t, "No Fallback Profile action since boot");
  return t;
}
constexpr TextBuf review_in_progress_text() {
  TextBuf t;
  put(t, "review in progress (read-only)");
  return t;
}
constexpr TextBuf candidate_ready_text() {
  TextBuf t;
  put(t, "CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within "
         "120 s");
  return t;
}
constexpr TextBuf review_expired_text() {
  TextBuf t;
  put(t, "REVIEW EXPIRED - candidate expired (120 s); review again");
  return t;
}
constexpr TextBuf review_cleared_domain_text(uint8_t slot) {
  TextBuf t;
  put(t, "REVIEW CLEARED - a temporary operation started (");
  put(t, domain_label(slot));
  put_char(t, ')');
  return t;
}
constexpr TextBuf review_cleared_writes_text() {
  TextBuf t;
  put(t, "REVIEW CLEARED - another ECCO write started since Review");
  return t;
}
constexpr TextBuf breaker_text(bool lock_held) {
  TextBuf t;
  put(t, "INTERNAL - Fallback Profile operation state reset by watchdog; ");
  put(t, lock_held ? "write lock still held - reboot required" : "write lock free");
  return t;
}
constexpr TextBuf internal_context_text() {
  TextBuf t;
  put(t, "INTERNAL - Fallback Profile dispatch context invalid; nothing written");
  return t;
}

// The invalidation script publishes B9 only for a non-empty reason that does not start with "superseded".
constexpr char REASON_SUPERSEDED[] = "superseded";
constexpr bool invalidate_reason_publishes(const char *reason) {
  if (reason == nullptr || reason[0] == '\0')
    return false;
  for (size_t i = 0; i + 1 < sizeof(REASON_SUPERSEDED); i++) {
    if (reason[i] != REASON_SUPERSEDED[i])
      return true;
  }
  return false;
}

// REVIEW NOT COMPLETED - <why a read step delivered nothing>. `step` (1-4) names the block; `exception_code` is
// the reply's exception code (0 = not available).
constexpr TextBuf read_fail_text(uint8_t code, uint8_t step, uint8_t exception_code) {
  TextBuf t;
  put(t, NOT_COMPLETED_PREFIX);
  const char *blk = block_name(step);
  switch (code) {
    case READ_NO_RESPONSE:
      put(t, "no response reading registers ");
      put(t, blk);
      break;
    case READ_EXCEPTION:
      if (exception_code != 0) {
        put(t, "inverter returned exception code 0x");
        put_hex(t, exception_code, 2);
        put(t, " on registers ");
      } else {
        put(t, "inverter returned an exception on registers ");
      }
      put(t, blk);
      break;
    case READ_NOT_SENT:
      put(t, "read of registers ");
      put(t, blk);
      put(t, " could not be queued");
      break;
    case READ_NONSTANDARD:
      put(t, "non-standard reply reading registers ");
      put(t, blk);
      break;
    case READ_SHORT:
      put(t, "short reply reading registers ");
      put(t, blk);
      break;
    case READ_BOUNDED_WAIT:
      put(t, "read of registers ");
      put(t, blk);
      put(t, " did not complete within 3 s");
      break;
    case READ_IDLE_TIMEOUT:
      put(t, "inverter bus stayed busy for 7 s; press Review again");
      break;
    default:
      put(t, "read did not complete (unknown cause)");
      break;
  }
  return t;
}

// REVIEW NOT COMPLETED - the two passes disagree; names the FIRST differing register (canonical order).
constexpr TextBuf pass_mismatch_text(const CaptureWords &a, const CaptureWords &b) {
  TextBuf t;
  const int k = first_diff(a, b);
  put(t, NOT_COMPLETED_PREFIX);
  put(t, "live configuration changed during the read (register ");
  put_u(t, reg_of(k));
  put(t, ": ");
  put_u(t, k >= 0 ? a[(size_t) k] : (uint16_t) 0);
  put(t, " then ");
  put_u(t, k >= 0 ? b[(size_t) k] : (uint16_t) 0);
  put(t, "); another controller may be editing - review again");
  return t;
}

constexpr void put_reason_text(TextBuf &t, uint16_t item, const CaptureWords &w) {
  const uint8_t kind = refusal_kind(item);
  const uint8_t n = refusal_slot(item);
  switch (kind) {
    case RF_244X:
      if (w[0] == 0)
        put(t, "244=0 Allow Export - V1 can only save a Zero Export profile");
      else if (w[0] == 1)
        put(t, "244=1 Essentials - unsupported in V1");
      else {
        put(t, "244=");
        put_u(t, w[0]);
        put(t, " unrecognised");
      }
      return;
    case RF_PWRL:
      put(t, "slot ");
      put_u(t, n);
      put(t, " power ");
      put_u(t, w[n]);
      put(t, " W < 500 W (V1 minimum)");
      return;
    case RF_PWRH:
      put(t, "slot ");
      put_u(t, n);
      put(t, " power ");
      put_u(t, w[n]);
      if (w[n] > ecco_fallback::V1_TOU_POWER_MAX_W)
        put(t, " W > 8000 W");
      else
        put(t, " W is above this site's configured ceiling");
      return;
    case RF_SOCH:
      put(t, "slot ");
      put_u(t, n);
      put(t, " SOC ");
      put_u(t, w[6 + n]);
      put(t, " % > 100");
      return;
    case RF_SRCG:
      put(t, "slot ");
      put_u(t, n);
      put(t, " source Generator / Grid+Generator unsupported in V1");
      return;
    case RF_MODE:
      put(t, "slot ");
      put_u(t, n);
      put(t, " mode General/Backup/Charge unsupported in V1");
      return;
    case RF_BITS:
      put(t, "slot ");
      put_u(t, n);
      put(t, " undecoded bits 0x");
      put_hex(t, w[12 + n] & 0xFFE0u, 4);
      put(t, " set");
      return;
    case RF_HHMM:
      put(t, "slot ");
      put_u(t, n);
      put(t, " start ");
      put_u(t, w[21 + n]);
      put(t, " is not a valid HHMM time");
      return;
    case RF_243X:
      put(t, "243=");
      put_u(t, w[20]);
      put(t, " is not a recognised energy-management mode (0 or 1)");
      return;
    case RF_CLASS:
      if (n == ecco_fbdurable::EPC_UNREADABLE)
        put(t, "stored profile UNREADABLE; reboot to re-derive it");
      else if (n == ecco_fbdurable::EPC_SAVE_UNCONFIRMED)
        put(t, "previous save outcome unknown; reboot to re-verify");
      else
        put(t, "stored profile state does not permit saving");
      return;
    default:
      put(t, "stored profile read anomaly this boot; reboot to re-derive it");
      return;
  }
}

// CANDIDATE NOT SAVEABLE - <first 2 reasons>[; +N more]. Reasons: the L2 refusals in code order, then the
// stored-profile class (or the read anomaly). B5 / B6 still show the values.
constexpr TextBuf not_saveable_text(const Refusals &r, const CaptureWords &w, uint8_t cls, uint8_t read_anomaly) {
  TextBuf t;
  uint16_t extra = 0;
  bool has_extra = false;
  if (!ecco_fbdurable::save_class_permitted(cls)) {
    extra = (uint16_t) ((RF_CLASS << 8) | cls);
    has_extra = true;
  } else if (read_anomaly != 0) {
    extra = (uint16_t) (RF_ANOMALY << 8);
    has_extra = true;
  }
  const uint32_t total = (uint32_t) r.count + (has_extra ? 1u : 0u);
  if (total == 0) {
    put(t, "CANDIDATE NOT SAVEABLE - reason unavailable");
    return t;
  }
  put(t, "CANDIDATE NOT SAVEABLE - ");
  for (uint32_t i = 0; i < total && i < 2; i++) {
    if (i != 0)
      put(t, "; ");
    put_reason_text(t, i < r.count ? r.item[i] : extra, w);
  }
  if (total > 2) {
    put(t, "; +");
    put_u(t, total - 2);
    put(t, " more");
  }
  return t;
}

// ---------------------------------------------------------------------------
// FB-B3: Live Match (B10), the live-cache trust rule and the write fence
// ---------------------------------------------------------------------------
// ONE comparison for every consumer. The four masks above (e1_delta_mask, ctx_mismatch_mask, info_mismatch_mask,
// out_of_domain_mask) are the only comparison code in the firmware; live_match() composes them with the trust terms in the
// order FINAL section 3.8 / S5 3.8 fix, and FB-C2 must call this same function. Pure: no clock, no global, no entity, no
// bus, no storage - the 10 s housekeeping lambda gathers plain values, makes ONE call and publishes the text.
//
// The live words are the poll caches in canonical order (REGS): the existing manual_cfg_*_raw words plus RAW_CACHE_EXT
// (fbc_raw_230 / 243 / 245 / 247 / 248, assigned ONLY by the existing config poll response handlers).
//
// Every value in here fails CLOSED: the default of a trust term is "untrusted", a missing profile / cache / boot load
// reads UNKNOWN, NO_PROFILE or PAUSED - never MATCH.
constexpr uint32_t LIVE_FENCE_OFFSET = 2u;            // PR53 technique: Block A of an in-flight poll is pre-fence
constexpr uint32_t LIVE_CACHE_MAX_AGE_MS = 180000u;   // two 60 s polls plus margin (ecco_dump_cfg_stale_ms)

// B10 `m=`. 0 is the fail-closed value.
enum LiveMatch : uint8_t {
  LM_UNKNOWN = 0,
  LM_NO_PROFILE = 1,
  LM_PAUSED = 2,
  LM_PAUSED_IO = 3,
  LM_OUT_OF_DOMAIN = 4,
  LM_EXPORT = 5,
  LM_CONTEXT = 6,
  LM_DRIFT = 7,
  LM_MATCH = 8,
};
constexpr const char *lm_name(uint8_t m) {
  switch (m) {
    case LM_NO_PROFILE:
      return "NO_PROFILE";
    case LM_PAUSED:
      return "PAUSED";
    case LM_PAUSED_IO:
      return "PAUSED_IO";
    case LM_OUT_OF_DOMAIN:
      return "OUT_OF_DOMAIN";
    case LM_EXPORT:
      return "EXPORT";
    case LM_CONTEXT:
      return "CONTEXT";
    case LM_DRIFT:
      return "DRIFT";
    case LM_MATCH:
      return "MATCH";
    default:
      return "UNKNOWN";
  }
}

// B10 `ca=`: the first failing term of the live-cache trust rule, as one letter. 0 is the fail-closed value.
enum CacheQuality : uint8_t {
  CQ_BOOT = 0,         // B: the boot load has not completed (B10-only letter)
  CQ_INVALID = 1,      // I: no valid cache (cache flag false, configuration offline, or no Block B response yet)
  CQ_POLL_OFF = 2,     // O: configuration polling is off
  CQ_STALE = 3,        // S: the last Block B response is older than LIVE_CACHE_MAX_AGE_MS
  CQ_PRE_FENCE = 4,    // P: the cached data may pre-date a write / lease edge (write fence)
  CQ_NOT_FILLED = 5,   // M: RAW_CACHE_EXT has never been filled
  CQ_FRESH = 6,        // F: every term passes
};
constexpr char cq_char(uint8_t q) {
  switch (q) {
    case CQ_INVALID:
      return 'I';
    case CQ_POLL_OFF:
      return 'O';
    case CQ_STALE:
      return 'S';
    case CQ_PRE_FENCE:
      return 'P';
    case CQ_NOT_FILLED:
      return 'M';
    case CQ_FRESH:
      return 'F';
    default:
      return 'B';
  }
}

// B10 `eh=`: the tri-state export hazard. Zero-initialised it reads UNKNOWN, which is never shown as "no".
enum ExportHazard : uint8_t { EH_UNKNOWN = 0, EH_NO = 1, EH_YES = 2 };
constexpr char eh_char(uint8_t e) { return e == EH_NO ? '0' : e == EH_YES ? '1' : 'U'; }

// B10 `elig=`: advisory pre-capture eligibility computed on the cache (SAVE always re-reads fresh).
enum Eligibility : uint8_t { ELIG_UNK = 0, ELIG_OVL = 1, ELIG_NO = 2, ELIG_OK = 3 };
constexpr const char *elig_name(uint8_t e) { return e == ELIG_OVL ? "OVL" : e == ELIG_NO ? "NO" : e == ELIG_OK ? "OK" : "UNK"; }

// ---- the write fence ------------------------------------------------------
// The cached words are only meaningful for a comparison if no inverter write or lease transition happened between the
// poll that produced them and now. cfg_block_b_dispatch_seq is bumped immediately BEFORE a Block B read is sent, so a
// response whose dispatch generation is >= (dispatch_seq at the fence moment + LIVE_FENCE_OFFSET) was produced by a poll
// whose Block A AND Block B were both sent after the fence. Two fences, both monotonic and RAM-only:
//   seq       any "hot" tick: the shared write lock or another bus owner is held, a lease domain is not clear, one of the
//             five write-attempt counters moved since the last tick (catches a hold shorter than the 10 s tick), a
//             lease domain just turned clear (the obligation -> clear edge), or this is the first tick of the boot
//   edge_seq  the lease subset: raised while a lease domain is not clear and on the obligation -> clear edge (the cache
//             may hold a Free Power / Dump overlay until a post-clear poll) - reported as PAUSED, not UNKNOWN
constexpr uint8_t FENCE_SEEDED = 1u;
constexpr uint8_t FENCE_PREV_LEASE = 2u;
struct FenceState {  // four RAM scalars in the firmware
  uint32_t seq = 0;
  uint32_t edge_seq = 0;
  uint32_t writes_fp = 0;  // the writes_fingerprint of the previous tick
  uint8_t flags = 0;       // FENCE_SEEDED | FENCE_PREV_LEASE
};
struct FenceSample {  // fail-closed defaults: a forgotten field makes the tick hot
  bool bus_hot = true;          // bus_busy(): any ECCO write transaction owns or may own the inverter
  bool lease_nonclear = true;   // lease_domain_nonclear() != SLOT_NONE
  uint32_t writes_fp = 0;       // writes_fingerprint(...)
  uint32_t dispatch_seq = 0;    // cfg_block_b_dispatch_seq
};
constexpr uint32_t fence_target(uint32_t dispatch_seq) { return (uint32_t) (dispatch_seq + LIVE_FENCE_OFFSET); }
constexpr uint32_t seq_max(uint32_t a, uint32_t b) { return a > b ? a : b; }
constexpr FenceState fence_tick(const FenceState &s, const FenceSample &t) {
  FenceState n = s;
  const bool seeded = (s.flags & FENCE_SEEDED) != 0;
  const bool prev_lease = (s.flags & FENCE_PREV_LEASE) != 0;
  const bool edge = seeded && prev_lease && !t.lease_nonclear;
  const bool hot = !seeded || t.bus_hot || t.lease_nonclear || edge || t.writes_fp != s.writes_fp;
  const uint32_t target = fence_target(t.dispatch_seq);
  if (hot)
    n.seq = seq_max(n.seq, target);
  if (t.lease_nonclear || edge)
    n.edge_seq = seq_max(n.edge_seq, target);
  n.writes_fp = t.writes_fp;
  n.flags = (uint8_t) (FENCE_SEEDED | (t.lease_nonclear ? FENCE_PREV_LEASE : 0u));
  return n;
}
// The fence has passed iff the cached data came from a poll dispatched at or after it.
constexpr bool fence_passed(uint32_t response_dispatch_seq, uint32_t fence_seq) { return response_dispatch_seq >= fence_seq; }

// ---- the live-cache trust rule (S3 11.5 / S4 7.6) ----------------------------
struct LiveCache {  // fail-closed defaults
  bool cache_valid = false;               // manual_config_raw_cache_valid
  bool online = false;                    // configuration_online.state
  bool polling = false;                   // configuration_polling.state
  bool filled = false;                    // fbc_raw_filled
  uint32_t block_b_seq = 0;               // cfg_block_b_seq
  uint32_t block_b_ok_ms = 0;             // cfg_block_b_ok_ms
  uint32_t now_ms = 0;
  uint32_t response_dispatch_seq = 0;     // cfg_block_b_response_dispatch_seq
  uint32_t fence_seq = 0xFFFFFFFFu;       // the write fence (pre-fence until proven otherwise)
};
constexpr uint8_t live_trust(const LiveCache &c, bool boot_loaded) {
  if (!boot_loaded)
    return CQ_BOOT;
  if (!c.cache_valid || !c.online || c.block_b_seq == 0)
    return CQ_INVALID;
  if (!c.polling)
    return CQ_POLL_OFF;
  if ((uint32_t) (c.now_ms - c.block_b_ok_ms) > LIVE_CACHE_MAX_AGE_MS)
    return CQ_STALE;
  if (!fence_passed(c.response_dispatch_seq, c.fence_seq))
    return CQ_PRE_FENCE;
  if (!c.filled)
    return CQ_NOT_FILLED;
  return CQ_FRESH;
}

// ---- the tri-state export hazard (S4 4.2, one predicate for every domain) ----------
// `bad_domain`: a lease domain that is not clear and whose kind is neither ACTIVE nor STARTING (a guarded running lease
// is not a hazard). `dump_original_allows_export`: SG-02's D5 exemption - a loaded Dump original that was itself Allow
// Export with 256-261 unchanged.
constexpr uint8_t export_hazard(bool live_trusted, uint16_t live244, bool bad_domain, bool dump_original_allows_export) {
  if (!live_trusted)
    return EH_UNKNOWN;
  if (live244 != 0)
    return EH_NO;
  if (!bad_domain)
    return EH_NO;
  if (dump_original_allows_export)
    return EH_NO;
  return EH_YES;
}

// ---- inputs / result ---------------------------------------------------------
struct LiveMatchInputs {
  GateInputs g{};                         // boot_loaded, probe_latch, bus, fp, dump, r244: the RAM legs, never probed
  bool mtou_running = true;               // any apply_manual_slot1..6 is_running()
  uint8_t cls = ecco_fbdurable::EPC_UNREADABLE;  // fallback_profile_class: the COMPOSED class, WITHOUT the overlay
  bool write_outcome_unknown = true;      // the RAM overlay of an UNKNOWN write outcome this boot (applied HERE)
  uint8_t read_anomaly = 1;               // fallback_profile_read_anomaly
  uint8_t p_load = ecco_fallback::LOAD_STORAGE_UNAVAILABLE;  // fallback_profile_load
  ecco_fallback::FallbackProfileV1 p{};   // the stored profile mirror
  LiveCache cache{};
  uint32_t edge_fence_seq = 0xFFFFFFFFu;  // FenceState::edge_seq
  CaptureWords live{};                    // the 31 cached words (REGS order)
  bool dump_data_loaded = false;          // dump_snapshot_data_loaded
  uint16_t dump_snapshot_reg244 = 0xFFFFu;
  std::array<uint16_t, 6> dump_snapshot_reg256_261{};
  uint32_t ceiling_w = 8000u;             // ${ecco_inverter_tou_power_ceiling_w}
};

struct LiveMatchResult {
  uint8_t m = LM_UNKNOWN;
  uint8_t ca = CQ_BOOT;
  bool compared = false;                  // dx / cx / ox / ix are meaningful (m in OUT_OF_DOMAIN..MATCH)
  uint32_t dx = 0;
  uint16_t cx = 0;
  uint32_t ox = 0;
  uint8_t ix = 0;
  uint8_t eh = EH_UNKNOWN;
  bool obl_valid = false;                 // the boot load completed: the four RAM-leg slots are meaningful
  SlotClass fp{};
  SlotClass dump{};
  SlotClass r244{};
  SlotClass bus{};
  uint8_t elig = ELIG_UNK;
  Refusals ew{};                          // the L2 refusals on the cached words (only shown when elig == ELIG_NO)
};

// The effective class of the stored profile for every Live Match purpose: the SAVE_UNCONFIRMED overlay (an UNKNOWN write
// outcome this boot) and a read anomaly make a stored profile unusable whatever the composed class still says
// (FB-B2 carry-forward: a pre-transaction VALID must not read as usable after an unconfirmed write).
constexpr uint8_t live_effective_class(uint8_t cls, bool write_outcome_unknown, uint8_t read_anomaly) {
  return write_outcome_unknown ? (uint8_t) ecco_fbdurable::EPC_SAVE_UNCONFIRMED
         : read_anomaly != 0 ? (uint8_t) ecco_fbdurable::EPC_UNREADABLE
                             : cls;
}

constexpr bool lease_slot_hazard(const SlotClass &c) {
  return !slot_ram_clear(c) && c.kind != OBL_ACTIVE && c.kind != OBL_STARTING;
}

// First match wins (FINAL 3.8, S5 3.8 as amended by Part A H3 / A.3 item 10):
//   1 effective class != VALID (or the record is not an authentic VALID one)  NO_PROFILE
//   2 the boot load has not completed                                        UNKNOWN  (ca=B)
//   3 a lease domain is not clear, or the lease fence has not passed          PAUSED
//   4 the bus is not idle or a Manual TOU apply runs                          PAUSED_IO
//   5 the cache is not trustworthy (ca != F)                                  UNKNOWN
//   6 a live E1 word is outside the V1 domain (ox != 0)                       OUT_OF_DOMAIN
//   7 dx bit0 set and live 244 == 0 (Allow Export)                            EXPORT
//   8 a CTX word differs (cx != 0)                                            CONTEXT
//   9 an E1 word differs (dx != 0)                                            DRIFT
//  10 otherwise                                                               MATCH
constexpr LiveMatchResult live_match(const LiveMatchInputs &in) {
  LiveMatchResult r{};
  const bool boot_loaded = in.g.boot_loaded;
  r.ca = live_trust(in.cache, boot_loaded);
  const bool trusted = r.ca == CQ_FRESH;
  r.obl_valid = boot_loaded;
  r.fp = classify_fp(in.g, PROBE_NONE);
  r.dump = classify_dump(in.g, PROBE_NONE);
  r.r244 = classify_r244(in.g, PROBE_NONE);
  r.bus = classify_bus(in.g);
  const bool lease_nonclear = !slot_ram_clear(r.fp) || !slot_ram_clear(r.dump) || !slot_ram_clear(r.r244);
  const bool edge_pending = !fence_passed(in.cache.response_dispatch_seq, in.edge_fence_seq);
  const bool bus_not_idle = r.bus.kind != OBL_CLEAR_PROVEN || in.mtou_running;

  // masks: always derived from the stored profile and the cached words; published only when the comparison is meaningful
  const uint8_t eff = live_effective_class(in.cls, in.write_outcome_unknown, in.read_anomaly);
  const bool profile_valid = eff == ecco_fbdurable::EPC_VALID &&
                             ecco_fallback::classify_profile(in.p_load, in.p) == ecco_fallback::PROFILE_VALID;
  const CaptureWords stored = words_of(in.p);
  const uint32_t dx = e1_delta_mask(in.live, stored);
  const uint16_t cx = ctx_mismatch_mask(in.live, stored);
  const uint32_t ox = out_of_domain_mask(in.live);
  const uint8_t ix = info_mismatch_mask(in.live, stored);

  // export hazard and eligibility are independent of the profile
  const bool dump_exempt = in.dump_data_loaded && in.dump_snapshot_reg244 == 0 && in.live[1] == in.dump_snapshot_reg256_261[0] &&
                           in.live[2] == in.dump_snapshot_reg256_261[1] && in.live[3] == in.dump_snapshot_reg256_261[2] &&
                           in.live[4] == in.dump_snapshot_reg256_261[3] && in.live[5] == in.dump_snapshot_reg256_261[4] &&
                           in.live[6] == in.dump_snapshot_reg256_261[5];
  r.eh = export_hazard(trusted, in.live[0], lease_slot_hazard(r.fp) || lease_slot_hazard(r.dump) || lease_slot_hazard(r.r244),
                       dump_exempt);
  if (!boot_loaded || r.ca == CQ_BOOT)
    r.elig = ELIG_UNK;
  else if (lease_nonclear || edge_pending)
    r.elig = ELIG_OVL;
  else if (bus_not_idle || !trusted)
    r.elig = ELIG_UNK;
  else {
    r.ew = capture_refusals(in.live, in.ceiling_w);
    r.elig = r.ew.count == 0 ? (uint8_t) ELIG_OK : (uint8_t) ELIG_NO;
  }

  if (!profile_valid) {
    r.m = LM_NO_PROFILE;
  } else if (!boot_loaded) {
    r.m = LM_UNKNOWN;
  } else if (lease_nonclear || edge_pending) {
    r.m = LM_PAUSED;
  } else if (bus_not_idle) {
    r.m = LM_PAUSED_IO;
  } else if (!trusted) {
    r.m = LM_UNKNOWN;
  } else {
    r.compared = true;
    r.dx = dx;
    r.cx = cx;
    r.ox = ox;
    r.ix = ix;
    r.m = ox != 0 ? (uint8_t) LM_OUT_OF_DOMAIN
          : ((dx & 1u) != 0 && in.live[0] == 0) ? (uint8_t) LM_EXPORT
          : cx != 0 ? (uint8_t) LM_CONTEXT
          : dx != 0 ? (uint8_t) LM_DRIFT
                    : (uint8_t) LM_MATCH;
  }
  return r;
}

// B10 `obl=`: the four RAM-leg slots in the fixed order FP,DP,R4,BUS. A lease domain that is clear by its RAM legs
// reads CR (it is never probed at this cadence); every other state keeps its alphabet code; BUS reads OK / BY / LK.
constexpr const char *b10_lease_code(const SlotClass &c) { return slot_ram_clear(c) ? "CR" : obl_code(c.kind, c.basis); }

// B10: m;dx;cx;ox;ix;eh;obl;ca;elig;ew - every key always present, `-` = not applicable, <= 200 characters.
// dx / ox are 5 hex digits, cx 3, ix 2; the four masks are `-` unless the comparison ran.
constexpr TextBuf b10_text(const LiveMatchResult &r) {
  TextBuf t;
  put(t, "m=");
  put(t, lm_name(r.m));
  put(t, ";dx=");
  if (r.compared)
    put_hex(t, r.dx, 5);
  else
    put_char(t, '-');
  put(t, ";cx=");
  if (r.compared)
    put_hex(t, r.cx, 3);
  else
    put_char(t, '-');
  put(t, ";ox=");
  if (r.compared)
    put_hex(t, r.ox, 5);
  else
    put_char(t, '-');
  put(t, ";ix=");
  if (r.compared)
    put_hex(t, r.ix, 2);
  else
    put_char(t, '-');
  put(t, ";eh=");
  put_char(t, eh_char(r.eh));
  put(t, ";obl=");
  if (r.obl_valid) {
    put(t, "FP:");
    put(t, b10_lease_code(r.fp));
    put(t, ",DP:");
    put(t, b10_lease_code(r.dump));
    put(t, ",R4:");
    put(t, b10_lease_code(r.r244));
    put(t, ",BUS:");
    put(t, obl_code(r.bus.kind, r.bus.basis));
  } else {
    put_char(t, '-');
  }
  put(t, ";ca=");
  put_char(t, cq_char(r.ca));
  put(t, ";elig=");
  put(t, elig_name(r.elig));
  put(t, ";ew=");
  if (r.elig == ELIG_NO && r.ew.count != 0) {
    for (uint8_t i = 0; i < r.ew.count && i < 3; i++) {
      if (i != 0)
        put_char(t, ',');
      put_refusal_code(t, r.ew.item[i]);
    }
    if (r.ew.count > 3) {
      put_char(t, '+');
      put_u(t, (uint32_t) (r.ew.count - 3));
    }
  } else {
    put_char(t, '-');
  }
  return t;
}

// The boot seed: no comparison has run, nothing is known (exactly what live_match() returns before the boot load completes).
constexpr TextBuf b10_seed_text() { return b10_text(LiveMatchResult{}); }

// ---- GOLDENS-BEGIN ----

// ---------------------------------------------------------------------------
// Compile-time golden vectors and golden-case tables. registry/tests/
// test_fallback_capture_host_compile.py parses every labelled static_assert
// below and requires the Python mirror to reproduce each value / string
// EXACTLY; the model suite re-derives the classifier tables from
// registry/fallback_capture.py.
// ---------------------------------------------------------------------------

// A typical VALID profile (FB-A's golden) and a consistent witness for it.
constexpr ecco_fallback::FallbackProfileV1 GOLDEN_PROFILE = ecco_fallback::GOLDEN_PROFILE_V1;
constexpr CaptureWords GOLDEN_WORDS = words_of(GOLDEN_PROFILE);
constexpr ecco_fbdurable::FailbackProvisionV1 golden_witness(uint32_t hw_generation, uint32_t prior_generation,
                                                             uint64_t prior_binding, uint8_t last_op,
                                                             uint32_t hw_key, uint16_t hw_record_schema) {
  ecco_fbdurable::FailbackProvisionV1 w{};
  w.magic = ecco_fbdurable::PROVISION_MAGIC;
  w.schema = ecco_fbdurable::PROVISION_SCHEMA;
  w.size = ecco_fbdurable::PROVISION_SIZE;
  w.hw_generation = hw_generation;
  w.prior_generation = prior_generation;
  w.hw_binding = GOLDEN_PROFILE.binding;
  w.prior_binding = prior_binding;
  w.hw_tag_key = hw_key;
  w.hw_record_schema = hw_record_schema;
  w.last_op = last_op;
  w.binding = ecco_fbdurable::provision_binding(w);
  return w;
}
constexpr ecco_fbdurable::FailbackProvisionV1 GOLDEN_WITNESS =
    golden_witness(7u, 6u, 0x1122334455667788ULL, ecco_fbdurable::PROV_OP_SAVE, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1);

// Fixture helpers (golden expressions only; nothing in the firmware calls them).
constexpr CaptureWords golden_words_with(CaptureWords w, size_t k, uint16_t v) {
  w[k] = v;
  return w;
}
constexpr CaptureWords golden_words_all(uint16_t v) {
  CaptureWords w{};
  for (size_t k = 0; k < REG_COUNT; k++)
    w[k] = v;
  return w;
}
// Everything RAM-clear, boot loaded, every lease marker loaded ABSENT at boot, FBS absent, no probe yet.
constexpr GateInputs golden_gate_clear() {
  GateInputs g{};
  g.boot_loaded = true;
  g.fbs_slot = ecco_fbdurable::FBS_CLEAR_ABSENT;
  g.fp.free_power_marker_boot_load = BOOT_LOAD_ABSENT;
  g.dump.dump_marker_boot_load = BOOT_LOAD_ABSENT;
  g.r244.reg244_marker_boot_load = BOOT_LOAD_ABSENT;
  return g;
}

// ---- classifier golden cases (S1 4.4: rows evaluated top to bottom, first match wins) ----
// FP columns: bl boot_loaded | ld free_power_marker_boot_load | cor free_power_recovery_metadata_corrupt |
//   frc ..._force_in_progress | acc ..._accept_in_progress | opf free_power_operation_in_progress |
//   snp free_power_snapshot_valid | ms free_power_marker_state | opn free_power_operator_needed |
//   act free_power_active_persisted | rrq free_power_restore_requested | expd expired | rst run_start |
//   rrs run_restore | rop run_operator | lat probe latch code | prb probe | kind | basis
struct FpCaseRow {
  uint8_t bl, ld, cor, frc, acc, opf, snp, ms, opn, act, rrq, expd, rst, rrs, rop, lat, prb, kind, basis;
};
// clang-format off
constexpr FpCaseRow FP_CASES[] = {
    // row 1: boot truth not loaded
    {0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},          // !boot_loaded
    {1, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},          // marker load never assigned
    {1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},            // load outside 0..3
    // row 2: corrupt flag + boot READ_ERROR (UNKNOWN), outranks everything below
    {1, 3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    {1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 2, 2, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    // row 3: corrupt flag, any other load (hard lockout)
    {1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    // row 2b: boot WRONG_SIZE / READ_ERROR but the flag is clear (RAM contradicts boot truth)
    {1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 4: the sticky runtime probe latch
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, UNK_DIVERGED, BASIS_GHOST_PC},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},        // unknown latch code
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 3, 2, UNK_DIVERGED, BASIS_GHOST_RR},              // latch outranks a running start and a probe
    // row 5: an operator action (force, accept, review) is running
    {1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING},
    {1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING},   // outranks a restore
    // row 6: a restore is running
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},
    {1, 1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},          // outranks a running start
    // rows 7, 8: a start is running, before / after its snapshot commit
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, OBL_STARTING, BASIS_PRE_COMMIT},
    {1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, OBL_STARTING, BASIS_COMMITTED},
    // row 9: the operation flag with no attributed script
    {1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED},
    {1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED},
    // row 10: snapshot valid + PENDING_CLEAR
    {1, 0, 0, 0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, OBL_PENDING_CLEAR, BASIS_NONE},
    {1, 0, 0, 0, 0, 0, 1, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, OBL_PENDING_CLEAR, BASIS_NONE},              // outranks operator_needed
    // row 11: snapshot valid + RESTORE_REQUIRED + operator needed
    {1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},
    {1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},            // outranks ACTIVE
    // row 12: ACTIVE lease
    {1, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, OBL_ACTIVE, BASIS_LEASE},
    // row 13: RESTORE_REQUIRED (restore requested, expired, or not active)
    {1, 0, 0, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    {1, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    {1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    // row 14: snapshot valid, any other marker state
    {1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 0, 0, 0, 0, 0, 1, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 15: no snapshot but obligation state set
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},        // a probe never rescues non-clear RAM
    // row 16: RAM clear, not probed (a stale operator_needed is NOT a term)
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_NOT_PROBED, BASIS_NONE},
    {1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, UNK_NOT_PROBED, BASIS_NONE},
    // rows 17-21: the durable leg
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, UNK_DIVERGED, BASIS_GHOST_PC},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, OBL_CLEAR_PROVEN, BASIS_ABSENT},
    {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR},        // boot load OK + marker CLEAR
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},  // unknown probe code
};
// clang-format on

constexpr bool fp_case_holds(const FpCaseRow &c) {
  GateInputs g{};
  g.boot_loaded = c.bl != 0;
  g.probe_latch = latch_set(0, DOM_FP, c.lat);
  g.fp.free_power_marker_boot_load = c.ld;
  g.fp.free_power_recovery_metadata_corrupt = c.cor != 0;
  g.bus.free_power_recovery_force_in_progress = c.frc != 0;
  g.bus.free_power_recovery_accept_in_progress = c.acc != 0;
  g.bus.free_power_operation_in_progress = c.opf != 0;
  g.fp.free_power_snapshot_valid = c.snp != 0;
  g.fp.free_power_marker_state = c.ms;
  g.fp.free_power_operator_needed = c.opn != 0;
  g.fp.free_power_active_persisted = c.act != 0;
  g.fp.free_power_restore_requested = c.rrq != 0;
  g.fp.expired = c.expd != 0;
  g.fp.run_start = c.rst != 0;
  g.fp.run_restore = c.rrs != 0;
  g.fp.run_operator = c.rop != 0;
  const SlotClass s = classify_fp(g, c.prb);
  return s.kind == c.kind && s.basis == c.basis;
}
constexpr bool fp_cases_hold() {
  for (size_t i = 0; i < sizeof(FP_CASES) / sizeof(FP_CASES[0]); i++) {
    if (!fp_case_holds(FP_CASES[i]))
      return false;
  }
  return true;
}
static_assert(fp_cases_hold(), "FB-B1 classifier golden cases: FP");

// DUMP columns: bl | ld dump_marker_boot_load | cor dump_recovery_metadata_corrupt | cnt dump_containment_state |
//   opf dump_operation_in_progress | snp dump_snapshot_valid | ms dump_marker_state | opn dump_operator_needed |
//   act dump_active_persisted | rrq dump_restore_requested | expd expired | rst run_start | rrs run_restore |
//   lat probe latch code | prb probe | kind | basis
struct DumpCaseRow {
  uint8_t bl, ld, cor, cnt, opf, snp, ms, opn, act, rrq, expd, rst, rrs, lat, prb, kind, basis;
};
// clang-format off
constexpr DumpCaseRow DUMP_CASES[] = {
    // row 1
    {0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    {1, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    {1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    // row 2: corrupt + boot READ_ERROR (containment K = 8)
    {1, 3, 1, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    {1, 3, 1, 8, 1, 1, 1, 1, 1, 1, 0, 1, 1, 2, 2, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    // row 3: corrupt (hard lockout, detail K)
    {1, 0, 1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 2, 1, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    // row 2b
    {1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 4: latch
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, UNK_DIVERGED, BASIS_GHOST_PC},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 4, 2, UNK_DIVERGED, BASIS_GHOST_PC},
    // row 5: containment state without the corrupt flag
    {1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 7, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 6: restore running
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},
    {1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},               // outranks a running start
    // rows 7, 8
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, OBL_STARTING, BASIS_PRE_COMMIT},
    {1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, OBL_STARTING, BASIS_COMMITTED},
    // row 9
    {1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED},
    {1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED},
    // row 10
    {1, 0, 0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, OBL_PENDING_CLEAR, BASIS_NONE},
    {1, 0, 0, 0, 0, 1, 2, 1, 1, 0, 0, 0, 0, 0, 0, OBL_PENDING_CLEAR, BASIS_NONE},
    // row 11 (includes the live-244-is-0 lockout)
    {1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},
    {1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},
    // row 12
    {1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, OBL_ACTIVE, BASIS_LEASE},
    // row 13 (dump_restore_requested only blocks the ACTIVE reading, it is never a clear-term)
    {1, 0, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    {1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    {1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, OBL_RESTORE_REQUIRED, BASIS_NONE},
    // row 14
    {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 0, 0, 0, 0, 1, 9, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 15
    {1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 2, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // rows 16-21
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, UNK_NOT_PROBED, BASIS_NONE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, UNK_NOT_PROBED, BASIS_NONE},                       // restore_requested alone is no obligation
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, UNK_DIVERGED, BASIS_GHOST_PC},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, OBL_CLEAR_PROVEN, BASIS_ABSENT},
};
// clang-format on

constexpr bool dump_case_holds(const DumpCaseRow &c) {
  GateInputs g{};
  g.boot_loaded = c.bl != 0;
  g.probe_latch = latch_set(0, DOM_DUMP, c.lat);
  g.dump.dump_marker_boot_load = c.ld;
  g.dump.dump_recovery_metadata_corrupt = c.cor != 0;
  g.dump.dump_containment_state = c.cnt;
  g.bus.dump_operation_in_progress = c.opf != 0;
  g.dump.dump_snapshot_valid = c.snp != 0;
  g.dump.dump_marker_state = c.ms;
  g.dump.dump_operator_needed = c.opn != 0;
  g.dump.dump_active_persisted = c.act != 0;
  g.dump.dump_restore_requested = c.rrq != 0;
  g.dump.expired = c.expd != 0;
  g.dump.run_start = c.rst != 0;
  g.dump.run_restore = c.rrs != 0;
  const SlotClass s = classify_dump(g, c.prb);
  return s.kind == c.kind && s.basis == c.basis;
}
constexpr bool dump_cases_hold() {
  for (size_t i = 0; i < sizeof(DUMP_CASES) / sizeof(DUMP_CASES[0]); i++) {
    if (!dump_case_holds(DUMP_CASES[i]))
      return false;
  }
  return true;
}
static_assert(dump_cases_hold(), "FB-B1 classifier golden cases: DUMP");

// R244 columns: bl | ld reg244_marker_boot_load | cor reg244_recovery_metadata_corrupt |
//   opf reg244_apply_in_progress | snp reg244_snapshot_valid | ms reg244_marker_state | rap run_apply |
//   rrs run_restore | lat probe latch code | prb probe | kind | basis
struct R244CaseRow {
  uint8_t bl, ld, cor, opf, snp, ms, rap, rrs, lat, prb, kind, basis;
};
// clang-format off
constexpr R244CaseRow R244_CASES[] = {
    // row 1
    {0, 255, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    {1, 255, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    {1, 4, 0, 0, 0, 0, 0, 0, 0, 0, UNK_BOOT_NOT_LOADED, BASIS_NONE},
    // row 2, 3, 2b
    {1, 3, 1, 0, 0, 0, 0, 0, 0, 0, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    {1, 3, 1, 1, 1, 1, 1, 1, 2, 2, UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR},
    {1, 0, 1, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 1, 1, 0, 0, 0, 0, 0, 0, 0, UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT},
    {1, 2, 0, 0, 0, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // row 4: latch
    {1, 1, 0, 0, 0, 0, 0, 0, 1, 0, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 2, 0, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 3, 0, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 4, 0, UNK_DIVERGED, BASIS_GHOST_PC},
    // row 5: restore running
    {1, 1, 0, 0, 0, 0, 0, 1, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},
    {1, 1, 0, 1, 1, 1, 1, 1, 0, 0, OBL_ENDING, BASIS_RESTORE_RUNNING},
    // rows 6, 7: an apply is running
    {1, 1, 0, 0, 0, 0, 1, 0, 0, 0, OBL_STARTING, BASIS_PRE_COMMIT},
    {1, 1, 0, 0, 1, 0, 1, 0, 0, 0, OBL_STARTING, BASIS_COMMITTED},
    // row 8: the apply flag with no running script
    {1, 1, 0, 1, 0, 0, 0, 0, 0, 0, UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED},
    // row 9: PENDING_CLEAR needs an armed manual Restore press
    {1, 0, 0, 0, 1, 2, 0, 0, 0, 0, OBL_PENDING_CLEAR, BASIS_NONE},
    // row 10: RESTORE_REQUIRED is operator-resolved only
    {1, 0, 0, 0, 1, 1, 0, 0, 0, 0, OBL_OPERATOR_NEEDED, BASIS_NONE},
    // row 11, 12
    {1, 0, 0, 0, 1, 0, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 0, 0, 0, 1, 7, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 1, 0, 0, 0, 0, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    {1, 1, 0, 0, 0, 2, 0, 0, 0, 2, UNK_DIVERGED, BASIS_RAM_INCONSISTENT},
    // rows 13-18
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 0, UNK_NOT_PROBED, BASIS_NONE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 3, UNK_DIVERGED, BASIS_GHOST_RR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 4, UNK_DIVERGED, BASIS_GHOST_PC},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 5, UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 6, UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 2, OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR},
    {1, 1, 0, 0, 0, 0, 0, 0, 0, 1, OBL_CLEAR_PROVEN, BASIS_ABSENT},
};
// clang-format on

constexpr bool r244_case_holds(const R244CaseRow &c) {
  GateInputs g{};
  g.boot_loaded = c.bl != 0;
  g.probe_latch = latch_set(0, DOM_R244, c.lat);
  g.r244.reg244_marker_boot_load = c.ld;
  g.r244.reg244_recovery_metadata_corrupt = c.cor != 0;
  g.bus.reg244_apply_in_progress = c.opf != 0;
  g.r244.reg244_snapshot_valid = c.snp != 0;
  g.r244.reg244_marker_state = c.ms;
  g.r244.run_apply = c.rap != 0;
  g.r244.run_restore = c.rrs != 0;
  const SlotClass s = classify_r244(g, c.prb);
  return s.kind == c.kind && s.basis == c.basis;
}
constexpr bool r244_cases_hold() {
  for (size_t i = 0; i < sizeof(R244_CASES) / sizeof(R244_CASES[0]); i++) {
    if (!r244_case_holds(R244_CASES[i]))
      return false;
  }
  return true;
}
static_assert(r244_cases_hold(), "FB-B1 classifier golden cases: R244");

// ---- GENERATED-GOLDENS-BEGIN (registry/tests/test_fallback_capture_host_compile.py --emit-goldens) ----
static_assert((CANDIDATE_TTL_MS) == 120000, "FB-B1 value: constant CANDIDATE_TTL_MS");
static_assert((IDLE_WAIT_MS) == 7000, "FB-B1 value: constant IDLE_WAIT_MS");
static_assert((STEP_WAIT_MS) == 3000, "FB-B1 value: constant STEP_WAIT_MS");
static_assert((BREAKER_MS) == 30000, "FB-B1 value: constant BREAKER_MS");
static_assert((LOCK_STUCK_MS) == 300000, "FB-B1 value: constant LOCK_STUCK_MS");
static_assert((TEXT_CAP) == 200, "FB-B1 value: constant TEXT_CAP");
static_assert((REG_COUNT) == 31, "FB-B1 value: constant REG_COUNT");
static_assert((B3_OBL_MAX) == 36, "FB-B1 value: constant B3_OBL_MAX");
static_assert((B3_SV_MAX) == 26, "FB-B1 value: constant B3_SV_MAX");
static_assert(str_is(epc_name(0), "UNREADABLE"), "FB-B1 name: epc_name 0");
static_assert(str_is(epc_name(1), "NOT_CAPTURED"), "FB-B1 name: epc_name 1");
static_assert(str_is(epc_name(2), "CORRUPT"), "FB-B1 name: epc_name 2");
static_assert(str_is(epc_name(3), "CORRUPT_DOMAIN"), "FB-B1 name: epc_name 3");
static_assert(str_is(epc_name(4), "INVALIDATED"), "FB-B1 name: epc_name 4");
static_assert(str_is(epc_name(5), "VALID"), "FB-B1 name: epc_name 5");
static_assert(str_is(epc_name(6), "PROFILE_LOST"), "FB-B1 name: epc_name 6");
static_assert(str_is(epc_name(7), "SAVE_UNCONFIRMED"), "FB-B1 name: epc_name 7");
static_assert(str_is(epc_name(8), "PROFILE_STALE"), "FB-B1 name: epc_name 8");
static_assert(str_is(epc_name(9), "UNREADABLE"), "FB-B1 name: epc_name 9");
static_assert(str_is(epc_name(11), "UNREADABLE"), "FB-B1 name: epc_name 11");
static_assert(str_is(epc_name(255), "UNREADABLE"), "FB-B1 name: epc_name 255");
static_assert(str_is(ld_name(0), "OK"), "FB-B1 name: ld_name 0");
static_assert(str_is(ld_name(1), "ABS"), "FB-B1 name: ld_name 1");
static_assert(str_is(ld_name(2), "WSZ"), "FB-B1 name: ld_name 2");
static_assert(str_is(ld_name(3), "RERR"), "FB-B1 name: ld_name 3");
static_assert(str_is(ld_name(4), "UNAV"), "FB-B1 name: ld_name 4");
static_assert(str_is(ld_name(5), "RERR"), "FB-B1 name: ld_name 5");
static_assert(str_is(ld_name(6), "RERR"), "FB-B1 name: ld_name 6");
static_assert(str_is(df_name(0), "-"), "FB-B1 name: df_name 0");
static_assert(str_is(df_name(1), "MAGIC"), "FB-B1 name: df_name 1");
static_assert(str_is(df_name(2), "SCHEMA"), "FB-B1 name: df_name 2");
static_assert(str_is(df_name(3), "SIZE"), "FB-B1 name: df_name 3");
static_assert(str_is(df_name(4), "BINDING"), "FB-B1 name: df_name 4");
static_assert(str_is(df_name(5), "RESERVED"), "FB-B1 name: df_name 5");
static_assert(str_is(df_name(6), "FLAGS"), "FB-B1 name: df_name 6");
static_assert(str_is(df_name(7), "GEN"), "FB-B1 name: df_name 7");
static_assert(str_is(df_name(8), "DOMAIN"), "FB-B1 name: df_name 8");
static_assert(str_is(df_name(9), "-"), "FB-B1 name: df_name 9");
static_assert(str_is(df_name(10), "-"), "FB-B1 name: df_name 10");
static_assert(str_is(w_name(0), "OK"), "FB-B1 name: w_name 0");
static_assert(str_is(w_name(1), "LAG"), "FB-B1 name: w_name 1");
static_assert(str_is(w_name(2), "MISS"), "FB-B1 name: w_name 2");
static_assert(str_is(w_name(3), "CORR"), "FB-B1 name: w_name 3");
static_assert(str_is(w_name(4), "UNR"), "FB-B1 name: w_name 4");
static_assert(str_is(w_name(5), "ABS"), "FB-B1 name: w_name 5");
static_assert(str_is(w_name(6), "UNR"), "FB-B1 name: w_name 6");
static_assert(str_is(w_name(7), "UNR"), "FB-B1 name: w_name 7");
static_assert(str_is(op_name(0), "-"), "FB-B1 name: op_name 0");
static_assert(str_is(op_name(1), "SAVE"), "FB-B1 name: op_name 1");
static_assert(str_is(op_name(2), "INV"), "FB-B1 name: op_name 2");
static_assert(str_is(op_name(3), "RC"), "FB-B1 name: op_name 3");
static_assert(str_is(op_name(4), "-"), "FB-B1 name: op_name 4");
static_assert(str_is(op_name(5), "-"), "FB-B1 name: op_name 5");
static_assert(str_is(why_name(0), "-"), "FB-B1 name: why_name 0");
static_assert(str_is(why_name(1), "INT"), "FB-B1 name: why_name 1");
static_assert(str_is(why_name(2), "RBK"), "FB-B1 name: why_name 2");
static_assert(str_is(why_name(3), "MIS"), "FB-B1 name: why_name 3");
static_assert(str_is(why_name(4), "SUP"), "FB-B1 name: why_name 4");
static_assert(str_is(why_name(5), "LAG"), "FB-B1 name: why_name 5");
static_assert(str_is(why_name(6), "MISS"), "FB-B1 name: why_name 6");
static_assert(str_is(why_name(7), "CORR"), "FB-B1 name: why_name 7");
static_assert(str_is(why_name(8), "PRD"), "FB-B1 name: why_name 8");
static_assert(str_is(why_name(9), "WRD"), "FB-B1 name: why_name 9");
static_assert(str_is(why_name(10), "ANOM"), "FB-B1 name: why_name 10");
static_assert(str_is(why_name(11), "FIRST"), "FB-B1 name: why_name 11");
static_assert(str_is(why_name(12), "LWC"), "FB-B1 name: why_name 12");
static_assert(str_is(why_name(13), "-"), "FB-B1 name: why_name 13");
static_assert(str_is(why_name(14), "-"), "FB-B1 name: why_name 14");
static_assert(str_is(capture_state_name(0), "IDLE"), "FB-B1 name: capture_state_name 0");
static_assert(str_is(capture_state_name(1), "READING"), "FB-B1 name: capture_state_name 1");
static_assert(str_is(capture_state_name(2), "CANDIDATE_READY"), "FB-B1 name: capture_state_name 2");
static_assert(str_is(capture_state_name(3), "CANDIDATE_NOT_SAVEABLE"), "FB-B1 name: capture_state_name 3");
static_assert(str_is(capture_state_name(4), "SAVING"), "FB-B1 name: capture_state_name 4");
static_assert(str_is(capture_state_name(5), "IDLE"), "FB-B1 name: capture_state_name 5");
static_assert(str_is(domain_label(0), ""), "FB-B1 name: domain_label 0");
static_assert(str_is(domain_label(1), "Failback record"), "FB-B1 name: domain_label 1");
static_assert(str_is(domain_label(2), "Free Power"), "FB-B1 name: domain_label 2");
static_assert(str_is(domain_label(3), "Dump to Grid"), "FB-B1 name: domain_label 3");
static_assert(str_is(domain_label(4), "Register 244 test"), "FB-B1 name: domain_label 4");
static_assert(str_is(domain_label(5), ""), "FB-B1 name: domain_label 5");
static_assert(str_is(domain_label(6), ""), "FB-B1 name: domain_label 6");
static_assert(str_is(block_name(0), "?"), "FB-B1 name: block_name 0");
static_assert(str_is(block_name(1), "230/3"), "FB-B1 name: block_name 1");
static_assert(str_is(block_name(2), "241/53"), "FB-B1 name: block_name 2");
static_assert(str_is(block_name(3), "230/3"), "FB-B1 name: block_name 3");
static_assert(str_is(block_name(4), "241/53"), "FB-B1 name: block_name 4");
static_assert(str_is(block_name(5), "?"), "FB-B1 name: block_name 5");
static_assert(str_is(block_name(6), "?"), "FB-B1 name: block_name 6");
static_assert(str_is(obl_code(OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR), "CM"), "FB-B1 name: obl_code OBL_CLEAR_PROVEN BASIS_MARKER_CLEAR");
static_assert(str_is(obl_code(OBL_CLEAR_PROVEN, BASIS_ABSENT), "CA"), "FB-B1 name: obl_code OBL_CLEAR_PROVEN BASIS_ABSENT");
static_assert(str_is(obl_code(OBL_CLEAR_PROVEN, BASIS_NO_DURABLE_STATE), "CN"), "FB-B1 name: obl_code OBL_CLEAR_PROVEN BASIS_NO_DURABLE_STATE");
static_assert(str_is(obl_code(OBL_CLEAR_PROVEN, BASIS_BUS_IDLE), "OK"), "FB-B1 name: obl_code OBL_CLEAR_PROVEN BASIS_BUS_IDLE");
static_assert(str_is(obl_code(OBL_CLEAR_PROVEN, BASIS_NONE), "UR"), "FB-B1 name: obl_code OBL_CLEAR_PROVEN BASIS_NONE");
static_assert(str_is(obl_code(OBL_ACTIVE, BASIS_LEASE), "AC"), "FB-B1 name: obl_code OBL_ACTIVE BASIS_LEASE");
static_assert(str_is(obl_code(OBL_STARTING, BASIS_PRE_COMMIT), "ST"), "FB-B1 name: obl_code OBL_STARTING BASIS_PRE_COMMIT");
static_assert(str_is(obl_code(OBL_RESTORE_REQUIRED, BASIS_NONE), "RR"), "FB-B1 name: obl_code OBL_RESTORE_REQUIRED BASIS_NONE");
static_assert(str_is(obl_code(OBL_PENDING_CLEAR, BASIS_NONE), "PC"), "FB-B1 name: obl_code OBL_PENDING_CLEAR BASIS_NONE");
static_assert(str_is(obl_code(OBL_ENDING, BASIS_RESTORE_RUNNING), "EN"), "FB-B1 name: obl_code OBL_ENDING BASIS_RESTORE_RUNNING");
static_assert(str_is(obl_code(OBL_OPERATOR_NEEDED, BASIS_NONE), "ON"), "FB-B1 name: obl_code OBL_OPERATOR_NEEDED BASIS_NONE");
static_assert(str_is(obl_code(UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR), "UR"), "FB-B1 name: obl_code UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(str_is(obl_code(UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT), "MC"), "FB-B1 name: obl_code UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(str_is(obl_code(UNK_BOOT_NOT_LOADED, BASIS_NONE), "BL"), "FB-B1 name: obl_code UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(str_is(obl_code(UNK_DIVERGED, BASIS_GHOST_RR), "DV"), "FB-B1 name: obl_code UNK_DIVERGED BASIS_GHOST_RR");
static_assert(str_is(obl_code(UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK), "LK"), "FB-B1 name: obl_code UNK_BUS_OR_LOCK_STUCK BASIS_LOCK_STUCK");
static_assert(str_is(obl_code(UNK_NOT_PROBED, BASIS_NONE), "NP"), "FB-B1 name: obl_code UNK_NOT_PROBED BASIS_NONE");
static_assert(str_is(obl_code(BUS_BUSY, BASIS_BUS_TXN), "BY"), "FB-B1 name: obl_code BUS_BUSY BASIS_BUS_TXN");
static_assert(str_is(obl_code(OBL_UNSET, BASIS_NONE), "UR"), "FB-B1 name: obl_code OBL_UNSET BASIS_NONE");
static_assert((first_diff(words_of(profile_from_words(GOLDEN_WORDS)), GOLDEN_WORDS)) == -1, "FB-B1 value: index map: words_of(profile_from_words(GOLDEN_WORDS)) == GOLDEN_WORDS");
static_assert((reg_of(-1)) == 0, "FB-B1 value: reg_of -1");
static_assert((reg_of(0)) == 244, "FB-B1 value: reg_of 0");
static_assert((reg_of(1)) == 256, "FB-B1 value: reg_of 1");
static_assert((reg_of(6)) == 261, "FB-B1 value: reg_of 6");
static_assert((reg_of(7)) == 268, "FB-B1 value: reg_of 7");
static_assert((reg_of(12)) == 273, "FB-B1 value: reg_of 12");
static_assert((reg_of(13)) == 274, "FB-B1 value: reg_of 13");
static_assert((reg_of(18)) == 279, "FB-B1 value: reg_of 18");
static_assert((reg_of(19)) == 232, "FB-B1 value: reg_of 19");
static_assert((reg_of(20)) == 243, "FB-B1 value: reg_of 20");
static_assert((reg_of(21)) == 248, "FB-B1 value: reg_of 21");
static_assert((reg_of(22)) == 250, "FB-B1 value: reg_of 22");
static_assert((reg_of(27)) == 255, "FB-B1 value: reg_of 27");
static_assert((reg_of(28)) == 230, "FB-B1 value: reg_of 28");
static_assert((reg_of(29)) == 245, "FB-B1 value: reg_of 29");
static_assert((reg_of(30)) == 247, "FB-B1 value: reg_of 30");
static_assert((reg_of(31)) == 0, "FB-B1 value: reg_of 31");
static_assert((reg_of(100)) == 0, "FB-B1 value: reg_of 100");
static_assert(([]{ for (size_t k = 0; k < REG_COUNT; k++) { if (first_diff(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, k, 12345u)) != (int) k) return false; } return first_diff(GOLDEN_WORDS, GOLDEN_WORDS) == -1; }()) == 1, "FB-B1 value: first_diff: every single-word change is found at its own index");
static_assert((first_diff(GOLDEN_WORDS, golden_words_with(golden_words_with(GOLDEN_WORDS, 5, 1u), 9, 2u))) == 5, "FB-B1 value: first_diff: the FIRST of two differences (5 and 9)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[0]; }()) == 1003, "FB-B1 value: store_block_241 / 230: word 0 (register 244)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[1]; }()) == 1015, "FB-B1 value: store_block_241 / 230: word 1 (register 256)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[6]; }()) == 1020, "FB-B1 value: store_block_241 / 230: word 6 (register 261)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[7]; }()) == 1027, "FB-B1 value: store_block_241 / 230: word 7 (register 268)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[12]; }()) == 1032, "FB-B1 value: store_block_241 / 230: word 12 (register 273)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[13]; }()) == 1033, "FB-B1 value: store_block_241 / 230: word 13 (register 274)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[18]; }()) == 1038, "FB-B1 value: store_block_241 / 230: word 18 (register 279)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[19]; }()) == 2002, "FB-B1 value: store_block_241 / 230: word 19 (register 232)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[20]; }()) == 1002, "FB-B1 value: store_block_241 / 230: word 20 (register 243)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[21]; }()) == 1007, "FB-B1 value: store_block_241 / 230: word 21 (register 248)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[22]; }()) == 1009, "FB-B1 value: store_block_241 / 230: word 22 (register 250)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[27]; }()) == 1014, "FB-B1 value: store_block_241 / 230: word 27 (register 255)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[28]; }()) == 2000, "FB-B1 value: store_block_241 / 230: word 28 (register 230)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[29]; }()) == 1004, "FB-B1 value: store_block_241 / 230: word 29 (register 245)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); return w[30]; }()) == 1006, "FB-B1 value: store_block_241 / 230: word 30 (register 247)");
static_assert(([]{ std::array<uint16_t, 53> a{}; std::array<uint16_t, 3> b{}; for (size_t i = 0; i < 53; i++) a[i] = (uint16_t) (1000 + i); for (size_t i = 0; i < 3; i++) b[i] = (uint16_t) (2000 + i); CaptureWords w{}; store_block_241(w, a); store_block_230(w, b); uint64_t h = ecco_fallback::FNV1A64_OFFSET_BASIS; for (size_t k = 0; k < REG_COUNT; k++) h = step_le(h, w[k], 2); return h; }()) == 0x63B2630475E87306ULL, "FB-B1 value: store_block_241 / 230: digest of all 31 stored words");
static_assert(([]{ std::array<uint16_t, 52> a{}; a[3] = 7; std::array<uint16_t, 4> b{}; b[0] = 9; CaptureWords w{}; const bool x = store_block_241(w, a); const bool y = store_block_230(w, b); return (x ? 100 : 0) + (y ? 10 : 0) + w[0] + w[28]; }()) == 0, "FB-B1 value: store_block_241: a wrong size stores nothing and reports it");
static_assert(text_is("OK", sv_text(capture_refusals(GOLDEN_WORDS, 8000u))), "FB-B1 text: sv_text: golden words");
static_assert(text_is("NO:244X", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 0u), 8000u))), "FB-B1 text: sv_text: 244=0");
static_assert(text_is("NO:244X", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 1u), 8000u))), "FB-B1 text: sv_text: 244=1");
static_assert(text_is("NO:244X", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 3u), 8000u))), "FB-B1 text: sv_text: 244=3");
static_assert(text_is("NO:PWRL1", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 1, 499u), 8000u))), "FB-B1 text: sv_text: power 499 (slot 1)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 1, 500u), 8000u))), "FB-B1 text: sv_text: power 500 (slot 1)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 6, 8000u), 8000u))), "FB-B1 text: sv_text: power 8000 (slot 6)");
static_assert(text_is("NO:PWRH6", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 6, 8001u), 8000u))), "FB-B1 text: sv_text: power 8001 (slot 6)");
static_assert(text_is("NO:PWRL3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 3, 0u), 8000u))), "FB-B1 text: sv_text: power 0 (slot 3)");
static_assert(text_is("NO:PWRH1,PWRH2", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 2, 6000u), 5000u))), "FB-B1 text: sv_text: power 6000 above a 5000 ceiling");
static_assert(text_is("NO:PWRH1", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 2, 5000u), 5000u))), "FB-B1 text: sv_text: power 5000 at a 5000 ceiling");
static_assert(text_is("NO:PWRH2", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 2, 9000u), 10000u))), "FB-B1 text: sv_text: power 9000 above 8000 and a 10000 ceiling");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 8, 100u), 8000u))), "FB-B1 text: sv_text: SOC 100 (slot 2)");
static_assert(text_is("NO:SOCH2", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 8, 101u), 8000u))), "FB-B1 text: sv_text: SOC 101 (slot 2)");
static_assert(text_is("NO:SOCH6", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 12, 65535u), 8000u))), "FB-B1 text: sv_text: SOC 65535 (slot 6)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(golden_words_with(GOLDEN_WORDS, 13, 0u), 14, 1u), 8000u))), "FB-B1 text: sv_text: source 0 and 1");
static_assert(text_is("NO:SRCG3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 2u), 8000u))), "FB-B1 text: sv_text: source 2 (slot 3)");
static_assert(text_is("NO:SRCG3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 3u), 8000u))), "FB-B1 text: sv_text: source 3 (slot 3)");
static_assert(text_is("NO:MODE3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 4u), 8000u))), "FB-B1 text: sv_text: source 4 = mode (slot 3)");
static_assert(text_is("NO:MODE4", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 16, 28u), 8000u))), "FB-B1 text: sv_text: source 0x1C = mode (slot 4)");
static_assert(text_is("NO:BITS3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 32u), 8000u))), "FB-B1 text: sv_text: source 0x20 = bits (slot 3)");
static_assert(text_is("NO:BITS6", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 18, 32768u), 8000u))), "FB-B1 text: sv_text: source 0x8000 = bits (slot 6)");
static_assert(text_is("NO:SRCG3,MODE3,BITS3", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 39u), 8000u))), "FB-B1 text: sv_text: source 0x27 = all three (slot 3)");
static_assert(text_is("NO:MODE1", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 13, 5u), 8000u))), "FB-B1 text: sv_text: source 5 = mode only (slot 1)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 25, 2359u), 8000u))), "FB-B1 text: sv_text: HHMM 2359 (slot 4)");
static_assert(text_is("NO:HHMM4", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 25, 2400u), 8000u))), "FB-B1 text: sv_text: HHMM 2400 (slot 4)");
static_assert(text_is("NO:HHMM4", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 25, 60u), 8000u))), "FB-B1 text: sv_text: HHMM 60 (slot 4)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 25, 59u), 8000u))), "FB-B1 text: sv_text: HHMM 59 (slot 4)");
static_assert(text_is("NO:HHMM6", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 27, 65535u), 8000u))), "FB-B1 text: sv_text: HHMM 65535 (slot 6)");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 20, 0u), 8000u))), "FB-B1 text: sv_text: 243 = 0 and 1");
static_assert(text_is("NO:243X", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 20, 2u), 8000u))), "FB-B1 text: sv_text: 243 = 2");
static_assert(text_is("NO:243X", sv_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 20, 65535u), 8000u))), "FB-B1 text: sv_text: 243 = 65535");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 19, 65535u), 21, 65535u), 28, 65535u), 29, 65535u), 30, 65535u), 8000u))), "FB-B1 text: sv_text: 232, 248, 230, 245, 247 never refuse");
static_assert(text_is("OK", sv_text(capture_refusals(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 3u), 23, 3u), 8000u))), "FB-B1 text: sv_text: off-grid and ring-breaking times never refuse");
static_assert(text_is("NO:244X,PWRL1,PWRH2+1", sv_text(capture_refusals(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 0u), 2, 9000u), 8, 101u), 8000u))), "FB-B1 text: sv_text: four refusals: +1");
static_assert(text_is("NO:244X,PWRL1,PWRH2", sv_text(capture_refusals(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 0u), 2, 9000u), 8000u))), "FB-B1 text: sv_text: three refusals: no +N");
static_assert(text_is("NO:244X,PWRH1,PWRH2+35", sv_text(capture_refusals(golden_words_all(65535u), 8000u))), "FB-B1 text: sv_text: every field wrong: 38 refusals, +35");
static_assert(text_is("NO:PWRL2,", sv_text([]{ Refusals r{}; refusal_add(r, RF_PWRL, 2); refusal_add(r, RF_CLASS, 5); return r; }())), "FB-B1 text: sv_text: a text-only RF_CLASS item renders no code");
static_assert(text_is("NO:,244X", sv_text([]{ Refusals r{}; refusal_add(r, RF_ANOMALY, 0); refusal_add(r, RF_244X, 0); return r; }())), "FB-B1 text: sv_text: a text-only RF_ANOMALY item renders no code");
static_assert(text_is("NO:,,243X", sv_text([]{ Refusals r{}; refusal_add(r, RF_NONE, 3); refusal_add(r, 200, 7); refusal_add(r, RF_243X, 0); return r; }())), "FB-B1 text: sv_text: RF_NONE and an unknown kind render no code");
static_assert((ReviewVerdict{}.sv.size()) == 0, "FB-B1 value: ReviewVerdict default sv is empty (the mirror used to default to -)");
static_assert((capture_refusals(golden_words_all(65535u), 8000u).count) == 38, "FB-B1 value: capture_refusals: the all-0xFFFF words give 38 refusals (the maximum)");
static_assert((capture_refusals(GOLDEN_WORDS, 8000u).count) == 0, "FB-B1 value: capture_refusals: the golden words give none");
static_assert((capture_warnings(GOLDEN_WORDS)) == 0, "FB-B1 value: capture_warnings: golden words");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 7, 100u), 8, 100u), 9, 100u), 10, 100u), 11, 100u), 12, 100u), 13, 1u), 14, 1u), 15, 1u), 16, 1u), 17, 1u), 18, 1u))) == 1, "FB-B1 value: capture_warnings: W1 FP overlay look-alike");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 7, 100u), 8, 100u), 9, 100u), 10, 100u), 11, 100u), 12, 100u), 13, 1u), 14, 1u), 15, 1u), 16, 1u), 17, 1u), 18, 1u), 19, 16u))) == 8, "FB-B1 value: capture_warnings: W1 needs 232 bit0");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 1, 3000u), 2, 3000u), 3, 3000u), 4, 3000u), 5, 3000u), 6, 3000u))) == 2, "FB-B1 value: capture_warnings: W2 uniform 3000 W");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 1, 3001u), 2, 3001u), 3, 3001u), 4, 3001u), 5, 3001u), 6, 3001u))) == 0, "FB-B1 value: capture_warnings: W2 uniform 3001 W is not Dump residue");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 1, 500u), 2, 500u), 3, 500u), 4, 500u), 5, 500u), 6, 500u))) == 2, "FB-B1 value: capture_warnings: W2 uniform 500 W");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 21, 0u))) == 4, "FB-B1 value: capture_warnings: W3 248 bit0 off");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 21, 3u))) == 0, "FB-B1 value: capture_warnings: W3 248 upper bits do not matter");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 19, 16u))) == 8, "FB-B1 value: capture_warnings: W4 grid source while 232 bit0 off");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 19, 16u), 13, 0u), 14, 0u), 15, 0u), 16, 0u), 17, 0u), 18, 0u))) == 0, "FB-B1 value: capture_warnings: W4 needs a grid (1) source");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 23, 531u))) == 16, "FB-B1 value: capture_warnings: W5 off the 5-minute grid");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 23, 2461u))) == 32, "FB-B1 value: capture_warnings: W5 ignores an undecodable start");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 23, 0u))) == 32, "FB-B1 value: capture_warnings: W6 duplicate start");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 23, 2200u))) == 32, "FB-B1 value: capture_warnings: W6 out of order");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 0u), 23, 800u), 24, 1600u), 25, 200u), 26, 1000u), 27, 1800u))) == 32, "FB-B1 value: capture_warnings: W6 wraps the ring twice");
static_assert((capture_warnings(golden_words_with(GOLDEN_WORDS, 24, 2400u))) == 32, "FB-B1 value: capture_warnings: W6 undecodable start");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 2300u), 23, 300u), 24, 800u), 25, 1200u), 26, 1600u), 27, 2000u))) == 0, "FB-B1 value: capture_warnings: a valid unsorted ring (rotated start) has no W6");
static_assert((capture_warnings(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 1, 3000u), 2, 3000u), 3, 3000u), 4, 3000u), 5, 3000u), 6, 3000u), 7, 100u), 8, 100u), 9, 100u), 10, 100u), 11, 100u), 12, 100u), 13, 1u), 14, 1u), 15, 1u), 16, 1u), 17, 1u), 18, 1u), 19, 17u), 21, 0u), 23, 531u), 24, 531u))) == 55, "FB-B1 value: capture_warnings: every warning at once");
static_assert((capture_warnings(golden_words_all(0u))) == 38, "FB-B1 value: capture_warnings: all words zero");
static_assert((capture_warnings(golden_words_all(65535u))) == 32, "FB-B1 value: capture_warnings: all words 0xFFFF");
static_assert((ring_valid(GOLDEN_WORDS)) == 1, "FB-B1 value: ring_valid: golden words");
static_assert((ring_valid(golden_words_with(GOLDEN_WORDS, 23, 0u))) == 0, "FB-B1 value: ring_valid: W6 duplicate start");
static_assert((ring_valid(golden_words_with(GOLDEN_WORDS, 24, 2400u))) == 0, "FB-B1 value: ring_valid: undecodable 2400");
static_assert((ring_valid(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 0u), 23, 800u), 24, 1600u), 25, 200u), 26, 1000u), 27, 1800u))) == 0, "FB-B1 value: ring_valid: wraps twice");
static_assert((ring_valid(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 2300u), 23, 300u), 24, 800u), 25, 1200u), 26, 1600u), 27, 2000u))) == 1, "FB-B1 value: ring_valid: rotated start");
static_assert((ring_valid(golden_words_all(0u))) == 0, "FB-B1 value: ring_valid: all zero");
static_assert((ring_valid(golden_words_with(golden_words_with(GOLDEN_WORDS, 27, 2359u), 26, 2300u))) == 1, "FB-B1 value: ring_valid: one slot at 2359");
static_assert((hhmm_decodable(0)) == 1, "FB-B1 value: hhmm_decodable 0");
static_assert((hhmm_decodable(59)) == 1, "FB-B1 value: hhmm_decodable 59");
static_assert((hhmm_decodable(60)) == 0, "FB-B1 value: hhmm_decodable 60");
static_assert((hhmm_decodable(99)) == 0, "FB-B1 value: hhmm_decodable 99");
static_assert((hhmm_decodable(100)) == 1, "FB-B1 value: hhmm_decodable 100");
static_assert((hhmm_decodable(2359)) == 1, "FB-B1 value: hhmm_decodable 2359");
static_assert((hhmm_decodable(2360)) == 0, "FB-B1 value: hhmm_decodable 2360");
static_assert((hhmm_decodable(2399)) == 0, "FB-B1 value: hhmm_decodable 2399");
static_assert((hhmm_decodable(2400)) == 0, "FB-B1 value: hhmm_decodable 2400");
static_assert((hhmm_decodable(65535)) == 0, "FB-B1 value: hhmm_decodable 65535");
static_assert((hhmm_decodable(1259)) == 1, "FB-B1 value: hhmm_decodable 1259");
static_assert((hhmm_decodable(1260)) == 0, "FB-B1 value: hhmm_decodable 1260");
static_assert((on_5min_grid(0)) == 1, "FB-B1 value: on_5min_grid 0");
static_assert((on_5min_grid(5)) == 1, "FB-B1 value: on_5min_grid 5");
static_assert((on_5min_grid(1)) == 0, "FB-B1 value: on_5min_grid 1");
static_assert((on_5min_grid(530)) == 1, "FB-B1 value: on_5min_grid 530");
static_assert((on_5min_grid(531)) == 0, "FB-B1 value: on_5min_grid 531");
static_assert((on_5min_grid(2355)) == 1, "FB-B1 value: on_5min_grid 2355");
static_assert((on_5min_grid(2359)) == 0, "FB-B1 value: on_5min_grid 2359");
static_assert((on_5min_grid(60)) == 1, "FB-B1 value: on_5min_grid 60");
static_assert((on_5min_grid(65)) == 1, "FB-B1 value: on_5min_grid 65");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 5, 0)) == 1, "FB-B1 value: review_eligible: clean, VALID");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 1, 0)) == 1, "FB-B1 value: review_eligible: clean, NOT_CAPTURED");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 2, 0)) == 1, "FB-B1 value: review_eligible: clean, CORRUPT");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 0, 0)) == 0, "FB-B1 value: review_eligible: clean, UNREADABLE");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 7, 0)) == 0, "FB-B1 value: review_eligible: clean, SAVE_UNCONFIRMED");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 8, 0)) == 1, "FB-B1 value: review_eligible: clean, STALE");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 6, 0)) == 1, "FB-B1 value: review_eligible: clean, LOST");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 5, 4)) == 0, "FB-B1 value: review_eligible: clean, VALID, anomaly");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 5, 1)) == 0, "FB-B1 value: review_eligible: clean, VALID, anomaly 1 (profile key)");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 5, 2)) == 0, "FB-B1 value: review_eligible: clean, VALID, anomaly 2 (witness key)");
static_assert((review_eligible(capture_refusals(GOLDEN_WORDS, 8000u), 5, 3)) == 0, "FB-B1 value: review_eligible: clean, VALID, anomaly 3");
static_assert((review_eligible(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 0u), 8000u), 5, 0)) == 0, "FB-B1 value: review_eligible: refused, VALID");
static_assert((candidate_id(1u, 1u, 1, 0u, 0x0ULL, GOLDEN_WORDS)) == 0x1D63D8CBC6CB4D55ULL, "FB-B1 value: candidate_id (constants reading, THE locked one) 1/1/1/0");
static_assert((candidate_id_alt_zero_header_reading(1u, 1u, 1, 0u, 0x0ULL, GOLDEN_WORDS)) == 0xA8085CFF57C3D9D2ULL, "FB-B1 value: candidate_id_alt_zero_header_reading (rejected reading) 1/1/1/0");
static_assert((candidate_id(3735928559u, 2u, 5, 7u, 0xD852A4FA2DF7DBA3ULL, GOLDEN_WORDS)) == 0x51235C0108AEE8F4ULL, "FB-B1 value: candidate_id (constants reading, THE locked one) DEADBEEF/2/5/7");
static_assert((candidate_id_alt_zero_header_reading(3735928559u, 2u, 5, 7u, 0xD852A4FA2DF7DBA3ULL, GOLDEN_WORDS)) == 0x288590F51189AD63ULL, "FB-B1 value: candidate_id_alt_zero_header_reading (rejected reading) DEADBEEF/2/5/7");
static_assert((candidate_id(4294967295u, 4294967295u, 8, 4294967295u, 0xFFFFFFFFFFFFFFFFULL, GOLDEN_WORDS)) == 0xF2953BF6B583F88EULL, "FB-B1 value: candidate_id (constants reading, THE locked one) FFFFFFFF/4294967295/8/4294967295");
static_assert((candidate_id_alt_zero_header_reading(4294967295u, 4294967295u, 8, 4294967295u, 0xFFFFFFFFFFFFFFFFULL, GOLDEN_WORDS)) == 0xCD3169A5EFA32E75ULL, "FB-B1 value: candidate_id_alt_zero_header_reading (rejected reading) FFFFFFFF/4294967295/8/4294967295");
static_assert((candidate_id(0u, 0u, 0, 0u, 0x0ULL, GOLDEN_WORDS)) == 0x4D584A0EC49950F2ULL, "FB-B1 value: candidate_id (constants reading, THE locked one) 0/0/0/0");
static_assert((candidate_id_alt_zero_header_reading(0u, 0u, 0, 0u, 0x0ULL, GOLDEN_WORDS)) == 0x10F8ABB29A11DF09ULL, "FB-B1 value: candidate_id_alt_zero_header_reading (rejected reading) 0/0/0/0");
static_assert((candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS) != candidate_id_alt_zero_header_reading(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS)) == 1, "FB-B1 value: candidate id: the two q readings differ");
static_assert(([]{ const uint64_t base = candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS); if (candidate_id(2u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 2u, 1, 0u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 1u, 2, 0u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 1u, 1, 1u, 0ULL, GOLDEN_WORDS) == base || candidate_id(1u, 1u, 1, 0u, 1ULL, GOLDEN_WORDS) == base) return false; for (size_t k = 0; k < REG_COUNT; k++) { if (candidate_id(1u, 1u, 1, 0u, 0ULL, golden_words_with(GOLDEN_WORDS, k, (uint16_t) (GOLDEN_WORDS[k] ^ 1u))) == base) return false; } return true; }()) == 1, "FB-B1 value: candidate id: every input changes the id (salt, seq, class, generation, binding, each of the 31 words)");
static_assert(text_is("1D63D8CBC6CB4D55", id_text(candidate_id(1u, 1u, 1, 0u, 0ULL, GOLDEN_WORDS))), "FB-B1 text: id_text: a 16-digit id");
static_assert(text_is("00000000000000AB", id_text(0x00000000000000ABULL)), "FB-B1 text: id_text: leading zeros are kept");
static_assert(text_is("1D63D8CBC6CB4D55", b4_text(true, 0x1D63D8CBC6CB4D55ULL)), "FB-B1 text: b4_text: saveable");
static_assert(text_is("-", b4_text(false, 0x1D63D8CBC6CB4D55ULL)), "FB-B1 text: b4_text: not saveable");
static_assert((e1_delta_mask(GOLDEN_WORDS, GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: identical");
static_assert((ctx_mismatch_mask(GOLDEN_WORDS, GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: identical");
static_assert((info_mismatch_mask(GOLDEN_WORDS, GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: identical");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 0, 0u), GOLDEN_WORDS)) == 1, "FB-B1 value: e1_delta_mask: 244");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 0, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 244");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 0, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 244");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 1, 1u), GOLDEN_WORDS)) == 2, "FB-B1 value: e1_delta_mask: 256");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 1, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 256");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 1, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 256");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 6, 1u), GOLDEN_WORDS)) == 64, "FB-B1 value: e1_delta_mask: 261");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 6, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 261");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 6, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 261");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 7, 1u), GOLDEN_WORDS)) == 128, "FB-B1 value: e1_delta_mask: 268");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 7, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 268");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 7, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 268");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 12, 1u), GOLDEN_WORDS)) == 4096, "FB-B1 value: e1_delta_mask: 273");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 12, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 273");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 12, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 273");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 13, 3u), GOLDEN_WORDS)) == 8192, "FB-B1 value: e1_delta_mask: 274 full word 1 -> 3");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 13, 3u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 274 full word 1 -> 3");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 13, 3u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 274 full word 1 -> 3");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 13, 32769u), GOLDEN_WORDS)) == 8192, "FB-B1 value: e1_delta_mask: 274 full word 1 -> 0x8001");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 13, 32769u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 274 full word 1 -> 0x8001");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 13, 32769u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 274 full word 1 -> 0x8001");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 18, 2u), GOLDEN_WORDS)) == 262144, "FB-B1 value: e1_delta_mask: 279");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 18, 2u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 279");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 18, 2u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 279");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 19, 16u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 232 bit0");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 16u), GOLDEN_WORDS)) == 1, "FB-B1 value: ctx_mismatch_mask: 232 bit0");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 16u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 232 bit0");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 19, 19u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 232 bit1 (info only)");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 19u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 232 bit1 (info only)");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 19u), GOLDEN_WORDS)) == 8, "FB-B1 value: info_mismatch_mask: 232 bit1 (info only)");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 19, 65521u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 232 all upper bits");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 65521u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 232 all upper bits");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 19, 65521u), GOLDEN_WORDS)) == 8, "FB-B1 value: info_mismatch_mask: 232 all upper bits");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 20, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 243");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 20, 0u), GOLDEN_WORDS)) == 2, "FB-B1 value: ctx_mismatch_mask: 243");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 20, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 243");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 21, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 248 bit0");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 0u), GOLDEN_WORDS)) == 4, "FB-B1 value: ctx_mismatch_mask: 248 bit0");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 248 bit0");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 21, 3u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 248 upper bits");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 3u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 248 upper bits");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 3u), GOLDEN_WORDS)) == 16, "FB-B1 value: info_mismatch_mask: 248 upper bits");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 21, 2u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 248 bit0 and upper bits");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 2u), GOLDEN_WORDS)) == 4, "FB-B1 value: ctx_mismatch_mask: 248 bit0 and upper bits");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 21, 2u), GOLDEN_WORDS)) == 16, "FB-B1 value: info_mismatch_mask: 248 bit0 and upper bits");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 22, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 250");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 22, 1u), GOLDEN_WORDS)) == 8, "FB-B1 value: ctx_mismatch_mask: 250");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 22, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 250");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 27, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 255");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 27, 1u), GOLDEN_WORDS)) == 256, "FB-B1 value: ctx_mismatch_mask: 255");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 27, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: info_mismatch_mask: 255");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 28, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 230");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 28, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 230");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 28, 1u), GOLDEN_WORDS)) == 1, "FB-B1 value: info_mismatch_mask: 230");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 29, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 245");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 29, 1u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 245");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 29, 1u), GOLDEN_WORDS)) == 2, "FB-B1 value: info_mismatch_mask: 245");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 30, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 247 bit0");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 30, 0u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 247 bit0");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 30, 0u), GOLDEN_WORDS)) == 4, "FB-B1 value: info_mismatch_mask: 247 bit0");
static_assert((e1_delta_mask(golden_words_with(GOLDEN_WORDS, 30, 32769u), GOLDEN_WORDS)) == 0, "FB-B1 value: e1_delta_mask: 247 upper bits");
static_assert((ctx_mismatch_mask(golden_words_with(GOLDEN_WORDS, 30, 32769u), GOLDEN_WORDS)) == 0, "FB-B1 value: ctx_mismatch_mask: 247 upper bits");
static_assert((info_mismatch_mask(golden_words_with(GOLDEN_WORDS, 30, 32769u), GOLDEN_WORDS)) == 4, "FB-B1 value: info_mismatch_mask: 247 upper bits");
static_assert((e1_delta_mask(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 65533u), 1, 57535u), 2, 65035u), 3, 61535u), 4, 62535u), 5, 63535u), 6, 64535u), 7, 65435u), 8, 65515u), 9, 65535u), 10, 65485u), 11, 65435u), 12, 65505u), 13, 65534u), 14, 65535u), 15, 65534u), 16, 65535u), 17, 65535u), 18, 65534u), 19, 65518u), 20, 65534u), 21, 65534u), 22, 65535u), 23, 65005u), 24, 64535u), 25, 63935u), 26, 63435u), 27, 63205u), 28, 65350u), 29, 57535u), 30, 65534u), GOLDEN_WORDS)) == 524287, "FB-B1 value: e1_delta_mask: every word");
static_assert((ctx_mismatch_mask(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 65533u), 1, 57535u), 2, 65035u), 3, 61535u), 4, 62535u), 5, 63535u), 6, 64535u), 7, 65435u), 8, 65515u), 9, 65535u), 10, 65485u), 11, 65435u), 12, 65505u), 13, 65534u), 14, 65535u), 15, 65534u), 16, 65535u), 17, 65535u), 18, 65534u), 19, 65518u), 20, 65534u), 21, 65534u), 22, 65535u), 23, 65005u), 24, 64535u), 25, 63935u), 26, 63435u), 27, 63205u), 28, 65350u), 29, 57535u), 30, 65534u), GOLDEN_WORDS)) == 511, "FB-B1 value: ctx_mismatch_mask: every word");
static_assert((info_mismatch_mask(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 65533u), 1, 57535u), 2, 65035u), 3, 61535u), 4, 62535u), 5, 63535u), 6, 64535u), 7, 65435u), 8, 65515u), 9, 65535u), 10, 65485u), 11, 65435u), 12, 65505u), 13, 65534u), 14, 65535u), 15, 65534u), 16, 65535u), 17, 65535u), 18, 65534u), 19, 65518u), 20, 65534u), 21, 65534u), 22, 65535u), 23, 65005u), 24, 64535u), 25, 63935u), 26, 63435u), 27, 63205u), 28, 65350u), 29, 57535u), 30, 65534u), GOLDEN_WORDS)) == 31, "FB-B1 value: info_mismatch_mask: every word");
static_assert((e1_delta_mask(golden_words_all(65535u), GOLDEN_WORDS)) == 524287, "FB-B1 value: e1_delta_mask: all words 0xFFFF");
static_assert((ctx_mismatch_mask(golden_words_all(65535u), GOLDEN_WORDS)) == 506, "FB-B1 value: ctx_mismatch_mask: all words 0xFFFF");
static_assert((info_mismatch_mask(golden_words_all(65535u), GOLDEN_WORDS)) == 31, "FB-B1 value: info_mismatch_mask: all words 0xFFFF");
static_assert((e1_delta_mask(golden_words_all(0u), GOLDEN_WORDS)) == 310783, "FB-B1 value: e1_delta_mask: all words zero");
static_assert((ctx_mismatch_mask(golden_words_all(0u), GOLDEN_WORDS)) == 503, "FB-B1 value: ctx_mismatch_mask: all words zero");
static_assert((info_mismatch_mask(golden_words_all(0u), GOLDEN_WORDS)) == 15, "FB-B1 value: info_mismatch_mask: all words zero");
static_assert((out_of_domain_mask(GOLDEN_WORDS)) == 0, "FB-B1 value: out_of_domain_mask: golden words");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 0, 0u))) == 0, "FB-B1 value: out_of_domain_mask: 244 = 0 is a valid FROM");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 0, 1u))) == 1, "FB-B1 value: out_of_domain_mask: 244 = 1");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 1, 499u))) == 2, "FB-B1 value: out_of_domain_mask: power 499");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 6, 8001u))) == 64, "FB-B1 value: out_of_domain_mask: power 8001");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 7, 101u))) == 128, "FB-B1 value: out_of_domain_mask: SOC 101");
static_assert((out_of_domain_mask(golden_words_with(GOLDEN_WORDS, 18, 2u))) == 262144, "FB-B1 value: out_of_domain_mask: source 2");
static_assert((out_of_domain_mask(golden_words_all(65535u))) == 524287, "FB-B1 value: out_of_domain_mask: all 0xFFFF");
static_assert((out_of_domain_mask(golden_words_all(0u))) == 126, "FB-B1 value: out_of_domain_mask: all zero");
static_assert((candidate_expired(0u, 0u)) == 0, "FB-B1 value: candidate_expired born=0 age=0 (now=0)");
static_assert((candidate_expired(1u, 0u)) == 0, "FB-B1 value: candidate_expired born=0 age=1 (now=1)");
static_assert((candidate_expired(119998u, 0u)) == 0, "FB-B1 value: candidate_expired born=0 age=119998 (now=119998)");
static_assert((candidate_expired(119999u, 0u)) == 0, "FB-B1 value: candidate_expired born=0 age=119999 (now=119999)");
static_assert((candidate_expired(120000u, 0u)) == 1, "FB-B1 value: candidate_expired born=0 age=120000 (now=120000)");
static_assert((candidate_expired(120001u, 0u)) == 1, "FB-B1 value: candidate_expired born=0 age=120001 (now=120001)");
static_assert((candidate_expired(4000000000u, 0u)) == 1, "FB-B1 value: candidate_expired born=0 age=4000000000 (now=4000000000)");
static_assert((candidate_expired(1000u, 1000u)) == 0, "FB-B1 value: candidate_expired born=1000 age=0 (now=1000)");
static_assert((candidate_expired(1001u, 1000u)) == 0, "FB-B1 value: candidate_expired born=1000 age=1 (now=1001)");
static_assert((candidate_expired(120998u, 1000u)) == 0, "FB-B1 value: candidate_expired born=1000 age=119998 (now=120998)");
static_assert((candidate_expired(120999u, 1000u)) == 0, "FB-B1 value: candidate_expired born=1000 age=119999 (now=120999)");
static_assert((candidate_expired(121000u, 1000u)) == 1, "FB-B1 value: candidate_expired born=1000 age=120000 (now=121000)");
static_assert((candidate_expired(121001u, 1000u)) == 1, "FB-B1 value: candidate_expired born=1000 age=120001 (now=121001)");
static_assert((candidate_expired(4000001000u, 1000u)) == 1, "FB-B1 value: candidate_expired born=1000 age=4000000000 (now=4000001000)");
static_assert((candidate_expired(4294960000u, 4294960000u)) == 0, "FB-B1 value: candidate_expired born=4294960000 age=0 (now=4294960000)");
static_assert((candidate_expired(4294960001u, 4294960000u)) == 0, "FB-B1 value: candidate_expired born=4294960000 age=1 (now=4294960001)");
static_assert((candidate_expired(112702u, 4294960000u)) == 0, "FB-B1 value: candidate_expired born=4294960000 age=119998 (now=112702)");
static_assert((candidate_expired(112703u, 4294960000u)) == 0, "FB-B1 value: candidate_expired born=4294960000 age=119999 (now=112703)");
static_assert((candidate_expired(112704u, 4294960000u)) == 1, "FB-B1 value: candidate_expired born=4294960000 age=120000 (now=112704)");
static_assert((candidate_expired(112705u, 4294960000u)) == 1, "FB-B1 value: candidate_expired born=4294960000 age=120001 (now=112705)");
static_assert((candidate_expired(3999992704u, 4294960000u)) == 1, "FB-B1 value: candidate_expired born=4294960000 age=4000000000 (now=3999992704)");
static_assert((candidate_expired(4294967295u, 4294967295u)) == 0, "FB-B1 value: candidate_expired born=4294967295 age=0 (now=4294967295)");
static_assert((candidate_expired(0u, 4294967295u)) == 0, "FB-B1 value: candidate_expired born=4294967295 age=1 (now=0)");
static_assert((candidate_expired(119997u, 4294967295u)) == 0, "FB-B1 value: candidate_expired born=4294967295 age=119998 (now=119997)");
static_assert((candidate_expired(119998u, 4294967295u)) == 0, "FB-B1 value: candidate_expired born=4294967295 age=119999 (now=119998)");
static_assert((candidate_expired(119999u, 4294967295u)) == 1, "FB-B1 value: candidate_expired born=4294967295 age=120000 (now=119999)");
static_assert((candidate_expired(120000u, 4294967295u)) == 1, "FB-B1 value: candidate_expired born=4294967295 age=120001 (now=120000)");
static_assert((candidate_expired(3999999999u, 4294967295u)) == 1, "FB-B1 value: candidate_expired born=4294967295 age=4000000000 (now=3999999999)");
static_assert((exp_seconds(0u + 1000u, 1000u)) == 120, "FB-B1 value: exp_seconds age 0 ms");
static_assert((exp_seconds(1u + 1000u, 1000u)) == 119, "FB-B1 value: exp_seconds age 1 ms");
static_assert((exp_seconds(999u + 1000u, 1000u)) == 119, "FB-B1 value: exp_seconds age 999 ms");
static_assert((exp_seconds(1000u + 1000u, 1000u)) == 119, "FB-B1 value: exp_seconds age 1000 ms");
static_assert((exp_seconds(1001u + 1000u, 1000u)) == 118, "FB-B1 value: exp_seconds age 1001 ms");
static_assert((exp_seconds(59999u + 1000u, 1000u)) == 60, "FB-B1 value: exp_seconds age 59999 ms");
static_assert((exp_seconds(60000u + 1000u, 1000u)) == 60, "FB-B1 value: exp_seconds age 60000 ms");
static_assert((exp_seconds(60001u + 1000u, 1000u)) == 59, "FB-B1 value: exp_seconds age 60001 ms");
static_assert((exp_seconds(118999u + 1000u, 1000u)) == 1, "FB-B1 value: exp_seconds age 118999 ms");
static_assert((exp_seconds(119000u + 1000u, 1000u)) == 1, "FB-B1 value: exp_seconds age 119000 ms");
static_assert((exp_seconds(119001u + 1000u, 1000u)) == 0, "FB-B1 value: exp_seconds age 119001 ms");
static_assert((exp_seconds(119999u + 1000u, 1000u)) == 0, "FB-B1 value: exp_seconds age 119999 ms");
static_assert((exp_seconds(120000u + 1000u, 1000u)) == 0, "FB-B1 value: exp_seconds age 120000 ms");
static_assert((exp_seconds(120001u + 1000u, 1000u)) == 0, "FB-B1 value: exp_seconds age 120001 ms");
static_assert((exp_seconds(4000000000u + 1000u, 1000u)) == 0, "FB-B1 value: exp_seconds age 4000000000 ms");
static_assert((exp_seconds(60999u, 4294967295u - 4294u)) == 54, "FB-B1 value: exp_seconds across the 2^32 wrap (age 61000)");
static_assert((writes_fingerprint(1u, 2u, 3u, 4u, 5u)) == 15, "FB-B1 value: writes_fingerprint (1, 2, 3, 4, 5)");
static_assert((writes_fingerprint(0u, 0u, 0u, 0u, 0u)) == 0, "FB-B1 value: writes_fingerprint (0, 0, 0, 0, 0)");
static_assert((writes_fingerprint(4294967295u, 1u, 0u, 0u, 0u)) == 0, "FB-B1 value: writes_fingerprint (4294967295, 1, 0, 0, 0)");
static_assert((writes_fingerprint(4294967295u, 4294967295u, 0u, 0u, 2u)) == 0, "FB-B1 value: writes_fingerprint (4294967295, 4294967295, 0, 0, 2)");
static_assert((writes_fingerprint(10u, 20u, 30u, 40u, 50u)) == 150, "FB-B1 value: writes_fingerprint (10, 20, 30, 40, 50)");
static_assert((writes_fingerprint(2147483647u, 2147483647u, 2u, 0u, 0u)) == 0, "FB-B1 value: writes_fingerprint (2147483647, 2147483647, 2, 0, 0)");
static_assert((review_integrity_ok(true, 1)) == 1, "FB-B1 value: review_integrity_ok op=True purpose=1");
static_assert((review_integrity_ok(true, 0)) == 0, "FB-B1 value: review_integrity_ok op=True purpose=0");
static_assert((review_integrity_ok(false, 1)) == 0, "FB-B1 value: review_integrity_ok op=False purpose=1");
static_assert((review_integrity_ok(false, 0)) == 0, "FB-B1 value: review_integrity_ok op=False purpose=0");
static_assert((review_integrity_ok(true, 2)) == 0, "FB-B1 value: review_integrity_ok op=True purpose=2");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 7, "FB-B1 value: prior_fingerprint generation: authentic VALID");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0xD852A4FA2DF7DBA3ULL, "FB-B1 value: prior_fingerprint binding: authentic VALID");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 8, "FB-B1 value: prior_fingerprint generation: authentic INVALIDATED");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0xF49A36C9C9720301ULL, "FB-B1 value: prior_fingerprint binding: authentic INVALIDATED");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 9, "FB-B1 value: prior_fingerprint generation: authentic CORRUPT_DOMAIN");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0x125B6A7CC6C9DD6AULL, "FB-B1 value: prior_fingerprint binding: authentic CORRUPT_DOMAIN");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 4660; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 7, "FB-B1 value: prior_fingerprint generation: CORRUPT + LOAD_OK keeps the raw fields");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 4660; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0xA53CDFCB77EF8197ULL, "FB-B1 value: prior_fingerprint binding: CORRUPT + LOAD_OK keeps the raw fields");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 11; return p; }(), 0u).generation) == 11, "FB-B1 value: prior_fingerprint generation: CORRUPT binding defect keeps the raw fields");
static_assert((prior_fingerprint(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 11; return p; }(), 0u).binding) == 0xD852A4FA2DF7DBA3ULL, "FB-B1 value: prior_fingerprint binding: CORRUPT binding defect keeps the raw fields");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 40u).generation) == 0, "FB-B1 value: prior_fingerprint generation: CORRUPT + WRONG_SIZE: (0, stored length)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 40u).binding) == 40, "FB-B1 value: prior_fingerprint binding: CORRUPT + WRONG_SIZE: (0, stored length)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 65535u).generation) == 0, "FB-B1 value: prior_fingerprint generation: CORRUPT + WRONG_SIZE: stored length 65535 (the 16-bit edge)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 65535u).binding) == 65535, "FB-B1 value: prior_fingerprint binding: CORRUPT + WRONG_SIZE: stored length 65535 (the 16-bit edge)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 65536u).generation) == 0, "FB-B1 value: prior_fingerprint generation: CORRUPT + WRONG_SIZE: stored length 65536");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 65536u).binding) == 65536, "FB-B1 value: prior_fingerprint binding: CORRUPT + WRONG_SIZE: stored length 65536");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 70000u).generation) == 0, "FB-B1 value: prior_fingerprint generation: CORRUPT + WRONG_SIZE: stored length 70000 (above 16 bits)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 70000u).binding) == 70000, "FB-B1 value: prior_fingerprint binding: CORRUPT + WRONG_SIZE: stored length 70000 (above 16 bits)");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 4294967295u).generation) == 0, "FB-B1 value: prior_fingerprint generation: CORRUPT + WRONG_SIZE: stored length 4294967295");
static_assert((prior_fingerprint(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 4294967295u).binding) == 4294967295u, "FB-B1 value: prior_fingerprint binding: CORRUPT + WRONG_SIZE: stored length 4294967295");
static_assert((prior_fingerprint(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 0, "FB-B1 value: prior_fingerprint generation: NOT_CAPTURED");
static_assert((prior_fingerprint(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0, "FB-B1 value: prior_fingerprint binding: NOT_CAPTURED");
static_assert((prior_fingerprint(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 0, "FB-B1 value: prior_fingerprint generation: READ_ERROR");
static_assert((prior_fingerprint(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0, "FB-B1 value: prior_fingerprint binding: READ_ERROR");
static_assert((prior_fingerprint(4, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).generation) == 0, "FB-B1 value: prior_fingerprint generation: UNAVAILABLE");
static_assert((prior_fingerprint(4, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0u).binding) == 0, "FB-B1 value: prior_fingerprint binding: UNAVAILABLE");
static_assert(([]{ ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = 2; in.p_load = 2; in.p_stored_len = 97u; return review_evaluate(in).prior_binding; }()) == 97, "FB-B1 value: review_evaluate: prior_binding of a WRONG_SIZE record with stored length 97");
static_assert(([]{ ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = 2; in.p_load = 2; in.p_stored_len = 70000u; return review_evaluate(in).prior_binding; }()) == 70000, "FB-B1 value: review_evaluate: prior_binding of a WRONG_SIZE record with stored length 70000");
static_assert(([]{ ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = 2; in.p_load = 2; in.p_stored_len = 4294967295u; return review_evaluate(in).prior_binding; }()) == 4294967295u, "FB-B1 value: review_evaluate: prior_binding of a WRONG_SIZE record with stored length 4294967295");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 1; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 1");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 3; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 3");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 4; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 4");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 6; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 6");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 7; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 7");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 8; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic VALID record, effective class 8");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 1; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 1");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 3; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 3");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 4; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 4");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 6; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 6");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 7; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 7");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 8; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic INVALIDATED record, effective class 8");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 1; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 1");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 3; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 3");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 4; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 4");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 6; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 6");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 7; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 7");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 8; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 1, "FB-B1 value: review_evaluate has_stored: authentic CORRUPT_DOMAIN record, effective class 8");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: CORRUPT (bad magic) record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: CORRUPT (bad magic) record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: CORRUPT (bad magic) record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 1; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: ABSENT record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 1; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: ABSENT record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 1; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: ABSENT record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 2; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 40u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: WRONG_SIZE record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 2; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 40u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: WRONG_SIZE record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 2; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 40u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: WRONG_SIZE record, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 3; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: READ_ERROR record, effective class 0");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 2; in.p_load = 3; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: READ_ERROR record, effective class 2");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 3; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(); in.p_stored_len = 0u; return review_evaluate(in).has_stored; }()) == 0, "FB-B1 value: review_evaluate has_stored: READ_ERROR record, effective class 5");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 0)) == 0, "FB-B1 value: stored_trusted: the golden profile under effective class 0");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 1)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 1");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 2)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 2");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 3)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 3");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 4)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 4");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 5)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 5");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 6)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 6");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 7)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 7");
static_assert((stored_trusted(0, GOLDEN_PROFILE, 8)) == 1, "FB-B1 value: stored_trusted: the golden profile under effective class 8");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).dx; }()) == 8195, "FB-B1 value: review_evaluate dx: a candidate that differs from the authentic golden profile, effective class 5 (masks computed)");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).dc; }()) == 1, "FB-B1 value: review_evaluate dc: a candidate that differs from the authentic golden profile, effective class 5 (masks computed)");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).di; }()) == 1, "FB-B1 value: review_evaluate di: a candidate that differs from the authentic golden profile, effective class 5 (masks computed)");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/499/100/3;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=02003", []{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); return b5_text(true, in.words, v.has_stored, v.dx); }()), "FB-B1 text: b5_text from the review verdict: a candidate that differs from the authentic golden profile, effective class 5");
static_assert(text_is("v=CAND;232=0010;243=1;248=0001;ring=OK;230=1;245=8000;247=0001;dc=001;di=01", []{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 5; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); return b6_text(true, in.words, v.has_stored, v.dc, v.di); }()), "FB-B1 text: b6_text from the review verdict: a candidate that differs from the authentic golden profile, effective class 5");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).dx; }()) == 0, "FB-B1 value: review_evaluate dx: a candidate that differs from the authentic golden profile, effective class 0 (not trusted: 0)");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).dc; }()) == 0, "FB-B1 value: review_evaluate dc: a candidate that differs from the authentic golden profile, effective class 0 (not trusted: 0)");
static_assert(([]{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = GOLDEN_PROFILE; return review_evaluate(in).di; }()) == 0, "FB-B1 value: review_evaluate di: a candidate that differs from the authentic golden profile, effective class 0 (not trusted: 0)");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/499/100/3;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-", []{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); return b5_text(true, in.words, v.has_stored, v.dx); }()), "FB-B1 text: b5_text from the review verdict: a candidate that differs from the authentic golden profile, effective class 0");
static_assert(text_is("v=CAND;232=0010;243=1;248=0001;ring=OK;230=1;245=8000;247=0001;dc=-;di=-", []{ ReviewInputs in; in.words = golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 13, 3u), 19, 16u), 28, 1u); in.cls = 0; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); return b6_text(true, in.words, v.has_stored, v.dc, v.di); }()), "FB-B1 text: b6_text from the review verdict: a candidate that differs from the authentic golden profile, effective class 0");
static_assert((diverged(0, 0, true)) == 0, "FB-B1 value: diverged: last load 0, new load 0, bytes equal True");
static_assert((diverged(0, 0, false)) == 1, "FB-B1 value: diverged: last load 0, new load 0, bytes equal False");
static_assert((diverged(0, 3, true)) == 1, "FB-B1 value: diverged: last load 0, new load 3, bytes equal True");
static_assert((diverged(1, 1, true)) == 0, "FB-B1 value: diverged: last load 1, new load 1, bytes equal True");
static_assert((diverged(3, 3, false)) == 1, "FB-B1 value: diverged: last load 3, new load 3, bytes equal False");
static_assert((diverged(4, 1, true)) == 1, "FB-B1 value: diverged: last load 4, new load 1, bytes equal True");
static_assert((profile_diverged(0, ecco_fallback::encode_profile(GOLDEN_PROFILE), 0, ecco_fallback::encode_profile(GOLDEN_PROFILE))) == 0, "FB-B1 value: profile_diverged: identical load and bytes");
static_assert((profile_diverged(0, ecco_fallback::encode_profile(GOLDEN_PROFILE), 3, ecco_fallback::encode_profile(GOLDEN_PROFILE))) == 1, "FB-B1 value: profile_diverged: a different load");
static_assert((profile_diverged(0, ecco_fallback::encode_profile(GOLDEN_PROFILE), 0, ecco_fallback::encode_profile([]{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }()))) == 1, "FB-B1 value: profile_diverged: different bytes");
static_assert((profile_diverged(1, ecco_fallback::ProfileBytes{}, 3, ecco_fallback::ProfileBytes{})) == 1, "FB-B1 value: profile_diverged: same zero bytes under two non-OK loads is a load change");
static_assert((profile_diverged(3, ecco_fallback::ProfileBytes{}, 3, ecco_fallback::ProfileBytes{})) == 0, "FB-B1 value: profile_diverged: same non-OK load, zero bytes");
static_assert((witness_diverged(0, ecco_fbdurable::encode_provision(GOLDEN_WITNESS), 0, ecco_fbdurable::encode_provision(GOLDEN_WITNESS))) == 0, "FB-B1 value: witness_diverged: identical");
static_assert((witness_diverged(0, ecco_fbdurable::encode_provision(GOLDEN_WITNESS), 0, ecco_fbdurable::encode_provision(golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1)))) == 1, "FB-B1 value: witness_diverged: different bytes");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.cls; }()) == 5, "FB-B1 value: evaluate_read [consistent read]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.why; }()) == 0, "FB-B1 value: evaluate_read [consistent read]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.rule; }()) == 10, "FB-B1 value: evaluate_read [consistent read]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [consistent read]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 0, "FB-B1 value: evaluate_read [consistent read]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 7, "FB-B1 value: evaluate_read [consistent read]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [consistent read]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [consistent read]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [consistent read]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS);  const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [consistent read]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.why; }()) == 10, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.rule; }()) == 16, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 1, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 8, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 1, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [the profile bytes changed (a resealed record)]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [the witness bytes changed]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.why; }()) == 10, "FB-B1 value: evaluate_read [the witness bytes changed]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.rule; }()) == 16, "FB-B1 value: evaluate_read [the witness bytes changed]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [the witness bytes changed]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 2, "FB-B1 value: evaluate_read [the witness bytes changed]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 8, "FB-B1 value: evaluate_read [the witness bytes changed]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [the witness bytes changed]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [the witness bytes changed]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [the witness bytes changed]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.w = golden_witness(8u, 7u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 1, "FB-B1 value: evaluate_read [the witness bytes changed]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.why; }()) == 8, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.rule; }()) == 1, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 2, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 1, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 7, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 0, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 1, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 3; in.p = ecco_fallback::FallbackProfileV1{}; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [the profile load changed to READ_ERROR]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.why; }()) == 10, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.rule; }()) == 16, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 1, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 7, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 1, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 1, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.present_seen = 3; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [the profile now reads ABSENT after being seen]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.cls; }()) == 5, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.why; }()) == 5, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.rule; }()) == 8, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 0, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 8, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return ecco_fallback::seal_profile(p); }(); const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [a changed record is not divergence without a baseline]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.why; }()) == 10, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.rule; }()) == 16, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 4, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 7, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.healthy = false; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [the health gate reported unhealthy after the read]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.cls; }()) == 0, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.why; }()) == 10, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.rule; }()) == 16, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 1, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 7, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.read_anomaly = 1; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [an earlier anomaly stays sticky]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.cls; }()) == 5, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.why; }()) == 0, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.rule; }()) == 10, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 3, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 0, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 40, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 5, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 3, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.seen_hw_gen = 40; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [seen_hw_gen is only ever raised]: w_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.cls; }()) == 1, "FB-B1 value: evaluate_read [first boot read, nothing stored]: cls");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.why; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: why");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.rule; }()) == 4, "FB-B1 value: evaluate_read [first boot read, nothing stored]: rule");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.latch.present_seen; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: latch.present_seen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.latch.read_anomaly; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: latch.read_anomaly");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.seen_hw_gen; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: seen_hw_gen");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.p_fba_class; }()) == 1, "FB-B1 value: evaluate_read [first boot read, nothing stored]: p_fba_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.w_class; }()) == 1, "FB-B1 value: evaluate_read [first boot read, nothing stored]: w_class");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.p_diverged; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: p_diverged");
static_assert(([]{ ReadInputs in; in.p_load = 0; in.p = GOLDEN_PROFILE; in.w_load = 0; in.w = GOLDEN_WITNESS; in.healthy = true; in.baseline_valid = true; in.last_p_load = 0; in.last_p_bytes = ecco_fallback::encode_profile(GOLDEN_PROFILE); in.last_w_load = 0; in.last_w_bytes = ecco_fbdurable::encode_provision(GOLDEN_WITNESS); in.baseline_valid = false; in.p_load = 1; in.p = ecco_fallback::FallbackProfileV1{}; in.w_load = 1; in.w = ecco_fbdurable::FailbackProvisionV1{}; const ReadEval e = evaluate_read(in); return e.w_diverged; }()) == 0, "FB-B1 value: evaluate_read [first boot read, nothing stored]: w_diverged");
static_assert(([]{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return e.cls; }()) == 0, "FB-B1 value: FW0 pipeline [valid FBP + unreadable witness]: the effective class");
static_assert(([]{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return v.has_stored; }()) == 0, "FB-B1 value: FW0 pipeline [valid FBP + unreadable witness]: has_stored");
static_assert(([]{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return v.eligible; }()) == 0, "FB-B1 value: FW0 pipeline [valid FBP + unreadable witness]: eligible");
static_assert(text_is("v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-", []{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return b5_text(true, in.words, v.has_stored, v.dx); }()), "FB-B1 text: FW0 pipeline [valid FBP + unreadable witness]: b5_text dx is -");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-", []{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return b6_text(true, in.words, v.has_stored, v.dc, v.di); }()), "FB-B1 text: FW0 pipeline [valid FBP + unreadable witness]: b6_text dc and di are -");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", []{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return b7_text(0, GOLDEN_PROFILE, e.cls); }()), "FB-B1 text: FW0 pipeline [valid FBP + unreadable witness]: b7_text is the NONE form");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", []{ ReadInputs ri; ri.p_load = 0; ri.p = GOLDEN_PROFILE; ri.w_load = 3; ri.w = ecco_fbdurable::FailbackProvisionV1{}; ri.healthy = true; const ReadEval e = evaluate_read(ri); ReviewInputs in; in.words = GOLDEN_WORDS; in.cls = e.cls; in.read_anomaly = e.latch.read_anomaly; in.p_load = 0; in.p = GOLDEN_PROFILE; const ReviewVerdict v = review_evaluate(in); (void) v; return b8_text(0, GOLDEN_PROFILE, e.cls); }()), "FB-B1 text: FW0 pipeline [valid FBP + unreadable witness]: b8_text is the NONE form");
static_assert((probe_result(1, MARKER_RECORD_MAGIC, 0)) == 1, "FB-B1 value: probe_result: absent");
static_assert((probe_result(0, MARKER_RECORD_MAGIC, 0)) == 2, "FB-B1 value: probe_result: clear");
static_assert((probe_result(0, MARKER_RECORD_MAGIC, 1)) == 3, "FB-B1 value: probe_result: restore required");
static_assert((probe_result(0, MARKER_RECORD_MAGIC, 2)) == 4, "FB-B1 value: probe_result: pending clear");
static_assert((probe_result(0, MARKER_RECORD_MAGIC, 3)) == 5, "FB-B1 value: probe_result: unknown state 3");
static_assert((probe_result(0, MARKER_RECORD_MAGIC, 255)) == 5, "FB-B1 value: probe_result: unknown state 255");
static_assert((probe_result(0, 305419896u, 0)) == 5, "FB-B1 value: probe_result: bad magic");
static_assert((probe_result(0, 0u, 1)) == 5, "FB-B1 value: probe_result: zero magic");
static_assert((probe_result(2, MARKER_RECORD_MAGIC, 0)) == 5, "FB-B1 value: probe_result: wrong size");
static_assert((probe_result(3, MARKER_RECORD_MAGIC, 0)) == 6, "FB-B1 value: probe_result: read error");
static_assert((probe_result(4, MARKER_RECORD_MAGIC, 0)) == 6, "FB-B1 value: probe_result: storage unavailable");
static_assert((probe_result(9, MARKER_RECORD_MAGIC, 0)) == 6, "FB-B1 value: probe_result: unknown load 9");
static_assert((probe_latch_code(0)) == 0, "FB-B1 value: probe_latch_code 0");
static_assert((probe_latch_code(1)) == 0, "FB-B1 value: probe_latch_code 1");
static_assert((probe_latch_code(2)) == 0, "FB-B1 value: probe_latch_code 2");
static_assert((probe_latch_code(3)) == 3, "FB-B1 value: probe_latch_code 3");
static_assert((probe_latch_code(4)) == 4, "FB-B1 value: probe_latch_code 4");
static_assert((probe_latch_code(5)) == 2, "FB-B1 value: probe_latch_code 5");
static_assert((probe_latch_code(6)) == 1, "FB-B1 value: probe_latch_code 6");
static_assert((probe_latch_code(7)) == 0, "FB-B1 value: probe_latch_code 7");
static_assert((latch_set(0, DOM_FP, 1)) == 1, "FB-B1 value: latch: set FP=1");
static_assert((latch_set(0, DOM_DUMP, 2)) == 32, "FB-B1 value: latch: set DUMP=2");
static_assert((latch_set(0, DOM_R244, 4)) == 1024, "FB-B1 value: latch: set R244=4");
static_assert((latch_set(latch_set(0, DOM_FP, 1), DOM_FP, 3)) == 1, "FB-B1 value: latch: a set nibble is never changed");
static_assert((latch_set(0x0010, DOM_DUMP, 0)) == 16, "FB-B1 value: latch: code 0 never writes");
static_assert((latch_set(0x0001, DOM_R244, 2)) == 513, "FB-B1 value: latch: another domain still sets");
static_assert((latch_set(0x0001, 5, 2)) == 1, "FB-B1 value: latch: an unknown domain is ignored");
static_assert((latch_get(0x0321, DOM_FP)) == 1, "FB-B1 value: latch: get FP");
static_assert((latch_get(0x0321, DOM_DUMP)) == 2, "FB-B1 value: latch: get DUMP");
static_assert((latch_get(0x0321, DOM_R244)) == 3, "FB-B1 value: latch: get R244");
static_assert((latch_get(0xFFFF, 9)) == 0, "FB-B1 value: latch: get an unknown domain");
static_assert(text_is("-", latch_text(0x0000)), "FB-B1 text: latch_text 0x0000");
static_assert(text_is("FP", latch_text(0x0001)), "FB-B1 text: latch_text 0x0001");
static_assert(text_is("DP", latch_text(0x0010)), "FB-B1 text: latch_text 0x0010");
static_assert(text_is("R4", latch_text(0x0100)), "FB-B1 text: latch_text 0x0100");
static_assert(text_is("FP,DP", latch_text(0x0011)), "FB-B1 text: latch_text 0x0011");
static_assert(text_is("FP,R4", latch_text(0x0101)), "FB-B1 text: latch_text 0x0101");
static_assert(text_is("DP,R4", latch_text(0x0110)), "FB-B1 text: latch_text 0x0110");
static_assert(text_is("FP,DP,R4", latch_text(0x0111)), "FB-B1 text: latch_text 0x0111");
static_assert(text_is("-", latch_text(0x1000)), "FB-B1 text: latch_text 0x1000");
static_assert(text_is("FP", latch_text(0x0004)), "FB-B1 text: latch_text 0x0004");
static_assert(text_is("-", latch_text(0xF000)), "FB-B1 text: latch_text 0xF000");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only manual_write_in_progress");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text(b); }(), "manual write"), "FB-B1 name: bus_owner_text with only manual_write_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.correction_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only correction_in_progress");
static_assert(str_is([]{ BusInputs b; b.correction_in_progress = true; return bus_owner_text(b); }(), "clock correction"), "FB-B1 name: bus_owner_text with only correction_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.verification_pending = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only verification_pending");
static_assert(str_is([]{ BusInputs b; b.verification_pending = true; return bus_owner_text(b); }(), "clock verification"), "FB-B1 name: bus_owner_text with only verification_pending");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.verification_read_active = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only verification_read_active");
static_assert(str_is([]{ BusInputs b; b.verification_read_active = true; return bus_owner_text(b); }(), "clock verification"), "FB-B1 name: bus_owner_text with only verification_read_active");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only free_power_operation_in_progress");
static_assert(str_is([]{ BusInputs b; b.free_power_operation_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with only free_power_operation_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_recovery_force_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only free_power_recovery_force_in_progress");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_force_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with only free_power_recovery_force_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_recovery_accept_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only free_power_recovery_accept_in_progress");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_accept_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with only free_power_recovery_accept_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.reg244_apply_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only reg244_apply_in_progress");
static_assert(str_is([]{ BusInputs b; b.reg244_apply_in_progress = true; return bus_owner_text(b); }(), "Register 244 test"), "FB-B1 name: bus_owner_text with only reg244_apply_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.dump_operation_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only dump_operation_in_progress");
static_assert(str_is([]{ BusInputs b; b.dump_operation_in_progress = true; return bus_owner_text(b); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text with only dump_operation_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_op_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only fallback_profile_op_in_progress");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_op_in_progress = true; return bus_owner_text(b); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text with only fallback_profile_op_in_progress");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_capture_dispatch_running = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with only fallback_profile_capture_dispatch_running");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_capture_dispatch_running = true; return bus_owner_text(b); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text with only fallback_profile_capture_dispatch_running");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.correction_in_progress = true; b.verification_pending = true; b.verification_read_active = true; b.free_power_operation_in_progress = true; b.free_power_recovery_force_in_progress = true; b.free_power_recovery_accept_in_progress = true; b.reg244_apply_in_progress = true; b.dump_operation_in_progress = true; b.fallback_profile_op_in_progress = true; b.fallback_profile_capture_dispatch_running = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with several owners: all eleven flags");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.correction_in_progress = true; g.bus.verification_pending = true; g.bus.verification_read_active = true; g.bus.free_power_operation_in_progress = true; g.bus.free_power_recovery_force_in_progress = true; g.bus.free_power_recovery_accept_in_progress = true; g.bus.reg244_apply_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.fallback_profile_op_in_progress = true; g.bus.fallback_profile_capture_dispatch_running = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: all eleven flags");
static_assert(str_is([]{ BusInputs b; b.free_power_operation_in_progress = true; b.dump_operation_in_progress = true; b.reg244_apply_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with several owners: Free Power operation + Dump + R244");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Free Power operation + Dump + R244");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_force_in_progress = true; b.manual_write_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with several owners: Free Power force + manual write");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_recovery_force_in_progress = true; g.bus.manual_write_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Free Power force + manual write");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_accept_in_progress = true; b.correction_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with several owners: Free Power accept + clock correction");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_recovery_accept_in_progress = true; g.bus.correction_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Free Power accept + clock correction");
static_assert(str_is([]{ BusInputs b; b.free_power_operation_in_progress = true; b.reg244_apply_in_progress = true; return bus_owner_text(b); }(), "Free Power"), "FB-B1 name: bus_owner_text with several owners: Free Power outranks Register 244 test");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Free Power outranks Register 244 test");
static_assert(str_is([]{ BusInputs b; b.reg244_apply_in_progress = true; b.dump_operation_in_progress = true; return bus_owner_text(b); }(), "Register 244 test"), "FB-B1 name: bus_owner_text with several owners: Register 244 test outranks Dump to Grid");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.reg244_apply_in_progress = true; g.bus.dump_operation_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Register 244 test outranks Dump to Grid");
static_assert(str_is([]{ BusInputs b; b.reg244_apply_in_progress = true; b.fallback_profile_op_in_progress = true; b.correction_in_progress = true; b.manual_write_in_progress = true; return bus_owner_text(b); }(), "Register 244 test"), "FB-B1 name: bus_owner_text with several owners: Register 244 test outranks the Fallback Profile and the clocks");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.reg244_apply_in_progress = true; g.bus.fallback_profile_op_in_progress = true; g.bus.correction_in_progress = true; g.bus.manual_write_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Register 244 test outranks the Fallback Profile and the clocks");
static_assert(str_is([]{ BusInputs b; b.dump_operation_in_progress = true; b.fallback_profile_op_in_progress = true; return bus_owner_text(b); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text with several owners: Dump to Grid outranks the Fallback Profile");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.dump_operation_in_progress = true; g.bus.fallback_profile_op_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Dump to Grid outranks the Fallback Profile");
static_assert(str_is([]{ BusInputs b; b.dump_operation_in_progress = true; b.verification_pending = true; return bus_owner_text(b); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text with several owners: Dump to Grid outranks a clock");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.dump_operation_in_progress = true; g.bus.verification_pending = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: Dump to Grid outranks a clock");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_op_in_progress = true; b.correction_in_progress = true; return bus_owner_text(b); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text with several owners: the Fallback Profile operation outranks clock correction");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_op_in_progress = true; g.bus.correction_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: the Fallback Profile operation outranks clock correction");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_capture_dispatch_running = true; b.verification_read_active = true; return bus_owner_text(b); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text with several owners: the Fallback Profile dispatch outranks clock verification");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_capture_dispatch_running = true; g.bus.verification_read_active = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: the Fallback Profile dispatch outranks clock verification");
static_assert(str_is([]{ BusInputs b; b.correction_in_progress = true; b.verification_pending = true; b.verification_read_active = true; return bus_owner_text(b); }(), "clock correction"), "FB-B1 name: bus_owner_text with several owners: clock correction outranks clock verification");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.correction_in_progress = true; g.bus.verification_pending = true; g.bus.verification_read_active = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: clock correction outranks clock verification");
static_assert(str_is([]{ BusInputs b; b.verification_pending = true; b.manual_write_in_progress = true; return bus_owner_text(b); }(), "clock verification"), "FB-B1 name: bus_owner_text with several owners: clock verification outranks the manual write");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.verification_pending = true; g.bus.manual_write_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: clock verification outranks the manual write");
static_assert(str_is([]{ BusInputs b; b.verification_read_active = true; b.manual_write_in_progress = true; return bus_owner_text(b); }(), "clock verification"), "FB-B1 name: bus_owner_text with several owners: a verification read with the manual write");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.verification_read_active = true; g.bus.manual_write_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus with several owners: a verification read with the manual write");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{UNK_NOT_PROBED, BASIS_NONE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, Free Power ACTIVE");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{UNK_NOT_PROBED, BASIS_NONE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, Dump ACTIVE");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, both ACTIVE (Free Power first)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{UNK_NOT_PROBED, BASIS_NONE}, SlotClass{UNK_NOT_PROBED, BASIS_NONE}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, no lease ACTIVE");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{}, SlotClass{}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, the all-zero SlotClass (fail-closed default) is not a lease");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_RESTORE_REQUIRED, BASIS_NONE}, SlotClass{OBL_RESTORE_REQUIRED, BASIS_NONE}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, leases restore-required (not ACTIVE)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_OPERATOR_NEEDED, BASIS_NONE}, SlotClass{OBL_OPERATOR_NEEDED, BASIS_NONE}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, leases operator-needed (not ACTIVE)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{UNK_DIVERGED, BASIS_RAM_INCONSISTENT}, SlotClass{UNK_DIVERGED, BASIS_RAM_INCONSISTENT}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, leases diverged (not ACTIVE)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_STARTING, BASIS_COMMITTED}, SlotClass{OBL_STARTING, BASIS_COMMITTED}); }(), "manual write"), "FB-B1 name: bus_owner_text_with_leases: the mutex alone, leases starting (not ACTIVE)");
static_assert(str_is([]{ BusInputs b; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "none"), "FB-B1 name: bus_owner_text_with_leases: no flag at all, both ACTIVE");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.correction_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock correction"), "FB-B1 name: bus_owner_text_with_leases: the mutex + correction_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.verification_pending = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock verification"), "FB-B1 name: bus_owner_text_with_leases: the mutex + verification_pending + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.verification_read_active = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock verification"), "FB-B1 name: bus_owner_text_with_leases: the mutex + verification_read_active + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.free_power_operation_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: the mutex + free_power_operation_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.free_power_recovery_force_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: the mutex + free_power_recovery_force_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.free_power_recovery_accept_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: the mutex + free_power_recovery_accept_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.reg244_apply_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Register 244 test"), "FB-B1 name: bus_owner_text_with_leases: the mutex + reg244_apply_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.dump_operation_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text_with_leases: the mutex + dump_operation_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.fallback_profile_op_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text_with_leases: the mutex + fallback_profile_op_in_progress + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.manual_write_in_progress = true; b.fallback_profile_capture_dispatch_running = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text_with_leases: the mutex + fallback_profile_capture_dispatch_running + both leases ACTIVE (a named owner outranks a lease)");
static_assert(str_is([]{ BusInputs b; b.correction_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock correction"), "FB-B1 name: bus_owner_text_with_leases: correction_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.verification_pending = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock verification"), "FB-B1 name: bus_owner_text_with_leases: verification_pending without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.verification_read_active = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "clock verification"), "FB-B1 name: bus_owner_text_with_leases: verification_read_active without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.free_power_operation_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: free_power_operation_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_force_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: free_power_recovery_force_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.free_power_recovery_accept_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Free Power"), "FB-B1 name: bus_owner_text_with_leases: free_power_recovery_accept_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.reg244_apply_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Register 244 test"), "FB-B1 name: bus_owner_text_with_leases: reg244_apply_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.dump_operation_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Dump to Grid"), "FB-B1 name: bus_owner_text_with_leases: dump_operation_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_op_in_progress = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text_with_leases: fallback_profile_op_in_progress without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ BusInputs b; b.fallback_profile_capture_dispatch_running = true; return bus_owner_text_with_leases(b, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}); }(), "Fallback Profile"), "FB-B1 name: bus_owner_text_with_leases: fallback_profile_capture_dispatch_running without the mutex + both leases ACTIVE (the plain answer)");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 301000u; g.bus.dump_operation_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "LK"), "FB-B1 name: classify_bus: a stuck lock outranks a busy bus (LK, not BY)");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 2000u; g.bus.now_ms = 301000u; g.bus.dump_operation_in_progress = true; const SlotClass c = classify_bus(g); return obl_code(c.kind, c.basis); }(), "BY"), "FB-B1 name: classify_bus: a lock held 299999 ms with other owners is still BY");
static_assert((lock_stuck([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 300999u; return b; }())) == 0, "FB-B1 value: lock_stuck: lock held 299999 ms");
static_assert((bus_busy([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 300999u; return b; }())) == 1, "FB-B1 value: bus_busy: lock held 299999 ms");
static_assert((lock_age_ms([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 300999u; return b; }())) == 299999, "FB-B1 value: lock_age_ms: lock held 299999 ms");
static_assert((lock_stuck([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 301000u; return b; }())) == 1, "FB-B1 value: lock_stuck: lock held 300000 ms");
static_assert((bus_busy([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 301000u; return b; }())) == 1, "FB-B1 value: bus_busy: lock held 300000 ms");
static_assert((lock_age_ms([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 301000u; return b; }())) == 300000, "FB-B1 value: lock_age_ms: lock held 300000 ms");
static_assert((lock_stuck([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = false; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 0, "FB-B1 value: lock_stuck: lock held, diagnostic says not held");
static_assert((bus_busy([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = false; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 1, "FB-B1 value: bus_busy: lock held, diagnostic says not held");
static_assert((lock_age_ms([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = false; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 998999, "FB-B1 value: lock_age_ms: lock held, diagnostic says not held");
static_assert((lock_stuck([]{ BusInputs b; b.manual_write_in_progress = false; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 0, "FB-B1 value: lock_stuck: diagnostic held but the mutex is free");
static_assert((bus_busy([]{ BusInputs b; b.manual_write_in_progress = false; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 0, "FB-B1 value: bus_busy: diagnostic held but the mutex is free");
static_assert((lock_age_ms([]{ BusInputs b; b.manual_write_in_progress = false; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 1000u; b.now_ms = 999999u; return b; }())) == 998999, "FB-B1 value: lock_age_ms: diagnostic held but the mutex is free");
static_assert((lock_stuck([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 4294967000u; b.now_ms = 299704u; return b; }())) == 1, "FB-B1 value: lock_stuck: lock age across the 2^32 wrap");
static_assert((bus_busy([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 4294967000u; b.now_ms = 299704u; return b; }())) == 1, "FB-B1 value: bus_busy: lock age across the 2^32 wrap");
static_assert((lock_age_ms([]{ BusInputs b; b.manual_write_in_progress = true; b.diag_write_lock_held = true; b.diag_write_lock_since_ms = 4294967000u; b.now_ms = 299704u; return b; }())) == 300000, "FB-B1 value: lock_age_ms: lock age across the 2^32 wrap");
static_assert((lock_stuck([]{ BusInputs b; return b; }())) == 0, "FB-B1 value: lock_stuck: idle bus");
static_assert((bus_busy([]{ BusInputs b; return b; }())) == 0, "FB-B1 value: bus_busy: idle bus");
static_assert((lock_age_ms([]{ BusInputs b; return b; }())) == 0, "FB-B1 value: lock_age_ms: idle bus");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 0; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "UR"), "FB-B1 name: classify_fbs slot 0");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 1; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "CA"), "FB-B1 name: classify_fbs slot 1");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 2; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "CM"), "FB-B1 name: classify_fbs slot 2");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 3; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "AC"), "FB-B1 name: classify_fbs slot 3");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 4; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "MC"), "FB-B1 name: classify_fbs slot 4");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 5; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "UR"), "FB-B1 name: classify_fbs slot 5");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = 6; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "UR"), "FB-B1 name: classify_fbs slot 6");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const SlotClass c = classify_fbs(g); return obl_code(c.kind, c.basis); }(), "BL"), "FB-B1 name: classify_fbs: boot not loaded");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); const SlotClass c = classify_mtou(g); return obl_code(c.kind, c.basis); }(), "CN"), "FB-B1 name: classify_mtou: bus clear");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const SlotClass c = classify_mtou(g); return obl_code(c.kind, c.basis); }(), "NP"), "FB-B1 name: classify_mtou: bus busy");
static_assert(str_is([]{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const SlotClass c = classify_mtou(g); return obl_code(c.kind, c.basis); }(), "BL"), "FB-B1 name: classify_mtou: boot not loaded");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 524034, "FB-B1 value: gate_decide [all clear, nothing probed yet]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [all clear, nothing probed yet]: obl");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [all clear, nothing probed yet]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65281, "FB-B1 value: gate_decide [all clear, all probes clean]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return r.obl; }()), "FB-B1 text: gate_decide [all clear, all probes clean]: obl");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return r.text; }()), "FB-B1 text: gate_decide [all clear, all probes clean]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_CLEAR, PROBE_NONE, PROBE_NONE}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 261890, "FB-B1 value: gate_decide [all clear, FP probed only (the rest still pending)]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:CM,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_CLEAR, PROBE_NONE, PROBE_NONE}); return r.obl; }()), "FB-B1 text: gate_decide [all clear, FP probed only (the rest still pending)]: obl");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_CLEAR, PROBE_NONE, PROBE_NONE}); return r.text; }()), "FB-B1 text: gate_decide [all clear, FP probed only (the rest still pending)]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_op_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65283, "FB-B1 value: gate_decide [V1 an operation is in flight]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_op_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V1 an operation is in flight]: obl");
static_assert(text_is("REVIEW REFUSED - another Fallback Profile operation is in progress", []{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_op_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V1 an operation is in flight]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_capture_dispatch_running = true; g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65283, "FB-B1 value: gate_decide [V1 the capture dispatch is running]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_capture_dispatch_running = true; g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V1 the capture dispatch is running]: obl");
static_assert(text_is("REVIEW REFUSED - another Fallback Profile operation is in progress", []{ GateInputs g = golden_gate_clear(); g.bus.fallback_profile_capture_dispatch_running = true; g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V1 the capture dispatch is running]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65284, "FB-B1 value: gate_decide [V2 durable state not loaded]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:BL,DP:BL,R4:BL,MT:BL,FS:BL,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V2 durable state not loaded]: obl");
static_assert(text_is("REVIEW REFUSED - durable state not loaded yet (starting up)", []{ GateInputs g = golden_gate_clear(); g.boot_loaded = false; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V2 durable state not loaded]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65285, "FB-B1 value: gate_decide [V3 Free Power arm on]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V3 Free Power arm on]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V3 Free Power arm on]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65285, "FB-B1 value: gate_decide [V3 Dump arm on]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V3 Dump arm on]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V3 Dump arm on]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.manual_config_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65285, "FB-B1 value: gate_decide [V3 Manual configuration arm on]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.manual_config_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V3 Manual configuration arm on]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = golden_gate_clear(); g.manual_config_write_enable = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V3 Manual configuration arm on]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65285, "FB-B1 value: gate_decide [V3 outranks a busy bus]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V3 outranks a busy bus]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = golden_gate_clear(); g.free_power_write_enable = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V3 outranks a busy bus]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 manual write holds the bus]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.correction_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 clock correction holds the bus]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.correction_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 clock correction holds the bus]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.correction_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 clock correction holds the bus]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 the write lock is stuck]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:NP,FS:CA,BUS:LK", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 the write lock is stuck]: obl");
static_assert(text_is("REVIEW REFUSED - inverter write lock held for 480 s (possible leak); a reboot may be required", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 the write lock is stuck]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; g.bus.correction_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 several owners at once (Free Power, Dump, R244, clock correction): the text names Free Power]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:LK,DP:LK,R4:LK,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; g.bus.correction_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 several owners at once (Free Power, Dump, R244, clock correction): the text names Free Power]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.dump_operation_in_progress = true; g.bus.reg244_apply_in_progress = true; g.bus.correction_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 several owners at once (Free Power, Dump, R244, clock correction): the text names Free Power]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 Free Power holds the bus (and the lease flag)]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:LK,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 Free Power holds the bus (and the lease flag)]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.free_power_operation_in_progress = true; g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 Free Power holds the bus (and the lease flag)]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 manual write holds the bus while a Dump lease is ACTIVE (the Dump controller tick): the text names Dump to Grid]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while a Dump lease is ACTIVE (the Dump controller tick): the text names Dump to Grid]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while a Dump lease is ACTIVE (the Dump controller tick): the text names Dump to Grid]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 manual write holds the bus while a Free Power lease is ACTIVE (the Free Power controller tick): the text names Free Power]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while a Free Power lease is ACTIVE (the Free Power controller tick): the text names Free Power]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while a Free Power lease is ACTIVE (the Free Power controller tick): the text names Free Power]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 manual write holds the bus while both leases are ACTIVE: the text names Free Power]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:AC,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while both leases are ACTIVE: the text names Free Power]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 manual write holds the bus while both leases are ACTIVE: the text names Free Power]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.correction_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 clock correction with the manual write and an ACTIVE Dump lease: the named owner outranks the lease]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.correction_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 clock correction with the manual write and an ACTIVE Dump lease: the named owner outranks the lease]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (clock correction); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.correction_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 clock correction with the manual write and an ACTIVE Dump lease: the named owner outranks the lease]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 6, "FB-B1 value: gate_decide [V4 the write lock is stuck while a Dump lease is ACTIVE: the stuck text is unchanged]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:LK", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V4 the write lock is stuck while a Dump lease is ACTIVE: the stuck text is unchanged]: obl");
static_assert(text_is("REVIEW REFUSED - inverter write lock held for 480 s (possible leak); a reboot may be required", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; g.bus.diag_write_lock_held = true; g.bus.diag_write_lock_since_ms = 1000u; g.bus.now_ms = 481000u; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V4 the write lock is stuck while a Dump lease is ACTIVE: the stuck text is unchanged]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 777, "FB-B1 value: gate_decide [V6 the same ACTIVE Dump lease with the bus free is refused at its own slot]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 the same ACTIVE Dump lease with the bus free is refused at its own slot]: obl");
static_assert(text_is("REVIEW REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 the same ACTIVE Dump lease with the bus free is refused at its own slot]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65285, "FB-B1 value: gate_decide [V3 the arms outrank a busy bus with an ACTIVE Dump lease]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:AC,R4:NP,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V3 the arms outrank a busy bus with an ACTIVE Dump lease]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", []{ GateInputs g = golden_gate_clear(); g.dump_write_enable = true; g.bus.manual_write_in_progress = true; g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V3 the arms outrank a busy bus with an ACTIVE Dump lease]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 263, "FB-B1 value: gate_decide [V5 FBS episode]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:AC,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V5 FBS episode]: obl");
static_assert(text_is("REVIEW REFUSED - a failback episode record exists; only the firmware that created it can resolve it", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V5 FBS episode]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CORRUPT; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 263, "FB-B1 value: gate_decide [V5 FBS corrupt]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:MC,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CORRUPT; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V5 FBS corrupt]: obl");
static_assert(text_is("REVIEW REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CORRUPT; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V5 FBS corrupt]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_UNREADABLE; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 263, "FB-B1 value: gate_decide [V5 FBS unreadable at boot]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:NP,MT:CN,FS:UR,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_UNREADABLE; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V5 FBS unreadable at boot]: obl");
static_assert(text_is("REVIEW REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_UNREADABLE; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V5 FBS unreadable at boot]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CLEAR_VALID; const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 65281, "FB-B1 value: gate_decide [V5 FBS valid and CLEAR passes]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:CA,DP:CM,R4:CA,MT:CN,FS:CM,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CLEAR_VALID; const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return r.obl; }()), "FB-B1 text: gate_decide [V5 FBS valid and CLEAR passes]: obl");
static_assert(text_is("", []{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_CLEAR_VALID; const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_ABSENT}); return r.text; }()), "FB-B1 text: gate_decide [V5 FBS valid and CLEAR passes]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 520, "FB-B1 value: gate_decide [V6 Free Power lease active]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:AC,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 Free Power lease active]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power is active; live settings are a temporary overlay - end it first", []{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_boot_load = 0; g.fp.free_power_snapshot_valid = true; g.fp.free_power_marker_state = 1; g.fp.free_power_active_persisted = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 Free Power lease active]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_operator_needed = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 777, "FB-B1 value: gate_decide [V6 Dump needs an operator]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:ON,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_operator_needed = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 Dump needs an operator]: obl");
static_assert(text_is("REVIEW REFUSED - Dump to Grid needs an operator recovery action first", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_snapshot_valid = true; g.dump.dump_marker_state = 1; g.dump.dump_operator_needed = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 Dump needs an operator]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 3; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 777, "FB-B1 value: gate_decide [V6 Dump hard lockout with containment K]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:MC,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 3; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 Dump hard lockout with containment K]: obl");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS; containment K=3", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 0; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 3; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 Dump hard lockout with containment K]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 3; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 8; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 777, "FB-B1 value: gate_decide [V6 Dump boot READ_ERROR (K = 8)]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:UR,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 3; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 8; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 Dump boot READ_ERROR (K = 8)]: obl");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", []{ GateInputs g = golden_gate_clear(); g.dump.dump_marker_boot_load = 3; g.dump.dump_recovery_metadata_corrupt = true; g.dump.dump_containment_state = 8; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 Dump boot READ_ERROR (K = 8)]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.r244.reg244_snapshot_valid = true; g.r244.reg244_marker_state = 2; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 1034, "FB-B1 value: gate_decide [V6 R244 pending clear]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:PC,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.r244.reg244_snapshot_valid = true; g.r244.reg244_marker_state = 2; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 R244 pending clear]: obl");
static_assert(text_is("REVIEW REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", []{ GateInputs g = golden_gate_clear(); g.r244.reg244_snapshot_valid = true; g.r244.reg244_marker_state = 2; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 R244 pending clear]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.r244.run_apply = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 1034, "FB-B1 value: gate_decide [V6 R244 apply running]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:ST,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.r244.run_apply = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 R244 apply running]: obl");
static_assert(text_is("REVIEW REFUSED - a Register 244 test start is in progress; live settings are about to become a temporary overlay", []{ GateInputs g = golden_gate_clear(); g.r244.run_apply = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 R244 apply running]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fp.run_start = true; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 520, "FB-B1 value: gate_decide [V6 FP start running before its commit]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:ST,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fp.run_start = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 FP start running before its commit]: obl");
static_assert(text_is("REVIEW REFUSED - a Free Power start is in progress; live settings are about to become a temporary overlay", []{ GateInputs g = golden_gate_clear(); g.fp.run_start = true; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 FP start running before its commit]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1; g.r244.reg244_marker_state = 1; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 520, "FB-B1 value: gate_decide [V6 first non-clear wins: FP before Dump before R244]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:DV,DP:DV,R4:DV,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1; g.r244.reg244_marker_state = 1; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 first non-clear wins: FP before Dump before R244]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power in-memory recovery state is inconsistent; a reboot must re-derive it before review", []{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1; g.r244.reg244_marker_state = 1; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 first non-clear wins: FP before Dump before R244]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 16777736, "FB-B1 value: gate_decide [V6 a latched domain refuses (FP, unreadable)]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 a latched domain refuses (FP, unreadable)]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 a latched domain refuses (FP, unreadable)]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0300; const GateResult r = gate_decide(g, ProbeResults{}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 0x30000040AULL, "FB-B1 value: gate_decide [V6 a latched domain refuses (R244, ghost restore required)]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:NP,DP:NP,R4:DV,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0300; const GateResult r = gate_decide(g, ProbeResults{}); return r.obl; }()), "FB-B1 text: gate_decide [V6 a latched domain refuses (R244, ghost restore required)]: obl");
static_assert(text_is("REVIEW REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore its saved original)", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0300; const GateResult r = gate_decide(g, ProbeResults{}); return r.text; }()), "FB-B1 text: gate_decide [V6 a latched domain refuses (R244, ghost restore required)]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_CLEAR, PROBE_ABSENT}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 16777736, "FB-B1 value: gate_decide [V7 FP marker unreadable at runtime]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:UR,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_CLEAR, PROBE_ABSENT}); return r.obl; }()), "FB-B1 text: gate_decide [V7 FP marker unreadable at runtime]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_CLEAR, PROBE_ABSENT}); return r.text; }()), "FB-B1 text: gate_decide [V7 FP marker unreadable at runtime]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_MALFORMED, PROBE_ABSENT}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 536871689, "FB-B1 value: gate_decide [V7 Dump marker malformed]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:CA,DP:MC,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_MALFORMED, PROBE_ABSENT}); return r.obl; }()), "FB-B1 text: gate_decide [V7 Dump marker malformed]: obl");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery marker is malformed (found at runtime); review blocked until reboot, which re-derives it as a hard lockout", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_MALFORMED, PROBE_ABSENT}); return r.text; }()), "FB-B1 text: gate_decide [V7 Dump marker malformed]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_RESTORE_REQUIRED}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 0x30000040AULL, "FB-B1 value: gate_decide [V7 R244 ghost restore required]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:CA,DP:CM,R4:DV,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_RESTORE_REQUIRED}); return r.obl; }()), "FB-B1 text: gate_decide [V7 R244 ghost restore required]: obl");
static_assert(text_is("REVIEW REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore its saved original)", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_ABSENT, PROBE_CLEAR, PROBE_RESTORE_REQUIRED}); return r.text; }()), "FB-B1 text: gate_decide [V7 R244 ghost restore required]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_CLEAR, PROBE_CLEAR}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 67109384, "FB-B1 value: gate_decide [V7 FP ghost pending clear]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:DV,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_CLEAR, PROBE_CLEAR}); return r.obl; }()), "FB-B1 text: gate_decide [V7 FP ghost pending clear]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power stored marker says PENDING_CLEAR but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore its saved original)", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_CLEAR, PROBE_CLEAR}); return r.text; }()), "FB-B1 text: gate_decide [V7 FP ghost pending clear]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_MALFORMED}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 0x211000208ULL, "FB-B1 value: gate_decide [V7 all three unreadable]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:UR,DP:UR,R4:MC,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_MALFORMED}); return r.obl; }()), "FB-B1 text: gate_decide [V7 all three unreadable]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = golden_gate_clear();  const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_MALFORMED}); return r.text; }()), "FB-B1 text: gate_decide [V7 all three unreadable]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_UNREADABLE, PROBE_ABSENT}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 285213192, "FB-B1 value: gate_decide [V7 a set latch is never rewritten]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:UR,DP:UR,R4:CA,MT:CN,FS:CA,BUS:OK", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_UNREADABLE, PROBE_ABSENT}); return r.obl; }()), "FB-B1 text: gate_decide [V7 a set latch is never rewritten]: obl");
static_assert(text_is("REVIEW REFUSED - Free Power recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", []{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0001; const GateResult r = gate_decide(g, ProbeResults{PROBE_PENDING_CLEAR, PROBE_UNREADABLE, PROBE_ABSENT}); return r.text; }()), "FB-B1 text: gate_decide [V7 a set latch is never rewritten]: text");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_UNREADABLE}); return (uint64_t) r.code | ((uint64_t) r.slot << 8) | ((uint64_t) ((r.probe_fp ? 4 : 0) + (r.probe_dump ? 2 : 0) + (r.probe_r244 ? 1 : 0)) << 16) | ((uint64_t) r.latch << 24); }()) == 0x111000006ULL, "FB-B1 value: gate_decide [V7 a probe result is still latched when another slot already refuses]: code | slot << 8 | probe flags << 16 | latch << 24");
static_assert(text_is("FP:UR,DP:UR,R4:UR,MT:NP,FS:CA,BUS:BY", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_UNREADABLE}); return r.obl; }()), "FB-B1 text: gate_decide [V7 a probe result is still latched when another slot already refuses]: obl");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (manual write); try again shortly", []{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; const GateResult r = gate_decide(g, ProbeResults{PROBE_UNREADABLE, PROBE_UNREADABLE, PROBE_UNREADABLE}); return r.text; }()), "FB-B1 text: gate_decide [V7 a probe result is still latched when another slot already refuses]: text");
static_assert(([]{ GateInputs g = golden_gate_clear();  return lease_domain_nonclear(g); }()) == 255, "FB-B1 value: lease_domain_nonclear: nothing running");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fp.run_start = true; return lease_domain_nonclear(g); }()) == 2, "FB-B1 value: lease_domain_nonclear: FP start running");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.dump.run_restore = true; return lease_domain_nonclear(g); }()) == 3, "FB-B1 value: lease_domain_nonclear: Dump restore running");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.r244.run_apply = true; return lease_domain_nonclear(g); }()) == 4, "FB-B1 value: lease_domain_nonclear: R244 apply running");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fp.free_power_marker_state = 1; g.dump.dump_marker_state = 1; return lease_domain_nonclear(g); }()) == 2, "FB-B1 value: lease_domain_nonclear: FP and Dump");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.bus.manual_write_in_progress = true; return lease_domain_nonclear(g); }()) == 255, "FB-B1 value: lease_domain_nonclear: only the bus is busy (not a lease domain)");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.fbs_slot = ecco_fbdurable::FBS_OBLIGATION; return lease_domain_nonclear(g); }()) == 255, "FB-B1 value: lease_domain_nonclear: FBS episode is not a lease domain");
static_assert(([]{ GateInputs g = golden_gate_clear(); g.probe_latch = 0x0010; return lease_domain_nonclear(g); }()) == 3, "FB-B1 value: lease_domain_nonclear: a latched domain");
static_assert((breaker_fired(true, false, 30000u, 0u)) == 0, "FB-B1 value: breaker_fired op=True running=False age=30000 start=0");
static_assert((breaker_fired(true, false, 30001u, 0u)) == 1, "FB-B1 value: breaker_fired op=True running=False age=30001 start=0");
static_assert((breaker_fired(true, true, 99999u, 0u)) == 0, "FB-B1 value: breaker_fired op=True running=True age=99999 start=0");
static_assert((breaker_fired(false, false, 99999u, 0u)) == 0, "FB-B1 value: breaker_fired op=False running=False age=99999 start=0");
static_assert((breaker_fired(true, false, 29999u, 0u)) == 0, "FB-B1 value: breaker_fired op=True running=False age=29999 start=0");
static_assert((breaker_fired(true, false, 0u, 4294937295u)) == 1, "FB-B1 value: breaker_fired op=True running=False age=30001 start=4294937295");
static_assert((breaker_fired(true, false, 4294967295u, 4294937295u)) == 0, "FB-B1 value: breaker_fired op=True running=False age=30000 start=4294937295");
static_assert((breaker_fired(true, false, 4000000005u, 5u)) == 1, "FB-B1 value: breaker_fired op=True running=False age=4000000000 start=5");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: consistent VALID");
static_assert(text_is("g=-;id=-;at=-;ld=ABS;df=-;w=ABS;hw=-;op=-;why=-;werr=-;us=-", b2_text(1, ecco_fallback::FallbackProfileV1{}, 1, ecco_fbdurable::FailbackProvisionV1{}, 0, 0u, 0u)), "FB-B1 text: b2_text: both absent (fresh device)");
static_assert(text_is("g=-;id=-;at=-;ld=ABS;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(1, ecco_fallback::FallbackProfileV1{}, 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: profile lost: FBP absent, witness valid");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=MISS;hw=-;op=-;why=MISS;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 1, ecco_fbdurable::FailbackProvisionV1{}, 6, 0u, 0u)), "FB-B1 text: b2_text: VALID with the witness missing");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=LAG;hw=6;op=SAVE;why=LAG;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 0, golden_witness(6u, 5u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 5, 0u, 0u)), "FB-B1 text: b2_text: VALID with a lagging witness");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=CORR;hw=-;op=-;why=CORR;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 0, []{ ecco_fbdurable::FailbackProvisionV1 w = golden_witness(7u, 6u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1); w.binding ^= 1u; return w; }(), 7, 0u, 0u)), "FB-B1 text: b2_text: VALID with a corrupt witness");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=UNR;hw=-;op=-;why=WRD;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 3, ecco_fbdurable::FailbackProvisionV1{}, 9, 0u, 0u)), "FB-B1 text: b2_text: VALID with an unreadable witness");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=INV;why=-;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 0, golden_witness(7u, 6u, 0x1122334455667788ULL, 2, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 0, 0u, 0u)), "FB-B1 text: b2_text: witness INVALIDATE op");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=RC;why=-;werr=-;us=-", b2_text(0, GOLDEN_PROFILE, 0, golden_witness(7u, 6u, 0x1122334455667788ULL, 3, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 0, 0u, 0u)), "FB-B1 text: b2_text: witness REPLACE_CORRUPT op");
static_assert(text_is("g=-;id=-;at=-;ld=ABS;df=-;w=OK;hw=1;op=SAVE;why=FIRST;werr=-;us=-", b2_text(1, ecco_fallback::FallbackProfileV1{}, 0, golden_witness(1u, 0u, 0x0ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 11, 0u, 0u)), "FB-B1 text: b2_text: witness first-save-unconfirmed shape");
static_assert(text_is("g=7;id=9CF13EC2B1C62BD0;at=5;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=MIS;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 7; p.captured_epoch = 5; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 3, 0u, 0u)), "FB-B1 text: b2_text: stale: mismatch");
static_assert(text_is("g=8;id=F49A36C9C9720301;at=1790000000;ld=OK;df=-;w=OK;hw=8;op=INV;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 0, golden_witness(8u, 7u, 0x1122334455667788ULL, 2, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 0, 0u, 0u)), "FB-B1 text: b2_text: INVALIDATED");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=MAGIC;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: bad magic");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=SCHEMA;w=ABS;hw=-;op=-;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.schema = 2; return ecco_fallback::seal_profile(p); }(), 1, ecco_fbdurable::FailbackProvisionV1{}, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: bad schema");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=SIZE;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.size = 95; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: bad size field");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=BINDING;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 8; return p; }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: bad binding");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=RESERVED;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reserved0 = 1; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: reserved bits");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=FLAGS;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 2; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: unknown flag");
static_assert(text_is("g=-;id=-;at=-;ld=OK;df=GEN;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 0; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT: generation 0");
static_assert(text_is("g=7;id=D9A7A727E2D42B9C;at=1790000000;ld=OK;df=DOMAIN;w=OK;hw=7;op=SAVE;why=LAG;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; return ecco_fallback::seal_profile(p); }(), 0, GOLDEN_WITNESS, 5, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT_DOMAIN: 244 = 1 (authentic)");
static_assert(text_is("g=4294967295;id=BBED7780106442DB;at=4294967295;ld=OK;df=DOMAIN;w=LAG;hw=4294967294;op=SAVE;why=LAG;werr=-;us=-", b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 0, golden_witness(4294967294u, 4294967293u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 5, 0u, 0u)), "FB-B1 text: b2_text: CORRUPT_DOMAIN: worst widths");
static_assert(text_is("g=-;id=-;at=-;ld=WSZ;df=-;w=OK;hw=7;op=SAVE;why=-;werr=-;us=-", b2_text(2, ecco_fallback::FallbackProfileV1{}, 0, GOLDEN_WITNESS, 0, 0u, 0u)), "FB-B1 text: b2_text: wrong stored size");
static_assert(text_is("g=-;id=-;at=-;ld=RERR;df=-;w=OK;hw=7;op=SAVE;why=PRD;werr=-;us=-", b2_text(3, ecco_fallback::FallbackProfileV1{}, 0, GOLDEN_WITNESS, 8, 0u, 0u)), "FB-B1 text: b2_text: profile read error");
static_assert(text_is("g=-;id=-;at=-;ld=UNAV;df=-;w=UNR;hw=-;op=-;why=PRD;werr=-;us=-", b2_text(4, ecco_fallback::FallbackProfileV1{}, 4, ecco_fbdurable::FailbackProvisionV1{}, 8, 0u, 0u)), "FB-B1 text: b2_text: storage unavailable");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=E1107;us=1234", b2_text(0, GOLDEN_PROFILE, 0, GOLDEN_WITNESS, 0, 4359u, 1234u)), "FB-B1 text: b2_text: werr and us set (the FB-B2 shape)");
static_assert(text_is("g=7;id=D852A4FA2DF7DBA3;at=1790000000;ld=OK;df=-;w=OK;hw=7;op=SAVE;why=-;werr=EFFFFFFFF;us=4294967295", b2_text(0, GOLDEN_PROFILE, 0, GOLDEN_WITNESS, 0, 4294967295u, 4294967295u)), "FB-B1 text: b2_text: werr and us at their widest");
static_assert(text_is("v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=1A2B3", b5_text(true, GOLDEN_WORDS, true, 0x1A2B3u)), "FB-B1 text: b5_text: golden, with stored dx 0x1A2B3");
static_assert(text_is("v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-", b5_text(true, GOLDEN_WORDS, false, 0x1A2B3u)), "FB-B1 text: b5_text: golden, no authentic stored profile");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=1FF;di=1F", b6_text(true, GOLDEN_WORDS, true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: golden, with stored dc 0x1FF di 0x1F");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-", b6_text(true, GOLDEN_WORDS, false, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: golden, no authentic stored profile");
static_assert(text_is("v=CAND;g=-;244=65535;1=65535/65535/65535/65535;2=65535/65535/65535/65535;3=65535/65535/65535/65535;4=65535/65535/65535/65535;5=65535/65535/65535/65535;6=65535/65535/65535/65535;dx=1A2B3", b5_text(true, golden_words_all(65535u), true, 0x1A2B3u)), "FB-B1 text: b5_text: all 0xFFFF, with stored dx 0x1A2B3");
static_assert(text_is("v=CAND;g=-;244=65535;1=65535/65535/65535/65535;2=65535/65535/65535/65535;3=65535/65535/65535/65535;4=65535/65535/65535/65535;5=65535/65535/65535/65535;6=65535/65535/65535/65535;dx=-", b5_text(true, golden_words_all(65535u), false, 0x1A2B3u)), "FB-B1 text: b5_text: all 0xFFFF, no authentic stored profile");
static_assert(text_is("v=CAND;232=FFFF;243=65535;248=FFFF;ring=BAD;230=65535;245=65535;247=FFFF;dc=1FF;di=1F", b6_text(true, golden_words_all(65535u), true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: all 0xFFFF, with stored dc 0x1FF di 0x1F");
static_assert(text_is("v=CAND;232=FFFF;243=65535;248=FFFF;ring=BAD;230=65535;245=65535;247=FFFF;dc=-;di=-", b6_text(true, golden_words_all(65535u), false, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: all 0xFFFF, no authentic stored profile");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/0/0/0;2=0000/0/0/0;3=0000/0/0/0;4=0000/0/0/0;5=0000/0/0/0;6=0000/0/0/0;dx=1A2B3", b5_text(true, golden_words_all(0u), true, 0x1A2B3u)), "FB-B1 text: b5_text: all zero, with stored dx 0x1A2B3");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/0/0/0;2=0000/0/0/0;3=0000/0/0/0;4=0000/0/0/0;5=0000/0/0/0;6=0000/0/0/0;dx=-", b5_text(true, golden_words_all(0u), false, 0x1A2B3u)), "FB-B1 text: b5_text: all zero, no authentic stored profile");
static_assert(text_is("v=CAND;232=0000;243=0;248=0000;ring=BAD;230=0;245=0;247=0000;dc=1FF;di=1F", b6_text(true, golden_words_all(0u), true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: all zero, with stored dc 0x1FF di 0x1F");
static_assert(text_is("v=CAND;232=0000;243=0;248=0000;ring=BAD;230=0;245=0;247=0000;dc=-;di=-", b6_text(true, golden_words_all(0u), false, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: all zero, no authentic stored profile");
static_assert(text_is("v=CAND;g=-;244=2;1=65535/8000/100/65535;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=65535/1000/30/1;dx=1A2B3", b5_text(true, golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 65535u), 27, 65535u), 13, 65535u), true, 0x1A2B3u)), "FB-B1 text: b5_text: five-digit HHMM and SRC, with stored dx 0x1A2B3");
static_assert(text_is("v=CAND;g=-;244=2;1=65535/8000/100/65535;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=65535/1000/30/1;dx=-", b5_text(true, golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 65535u), 27, 65535u), 13, 65535u), false, 0x1A2B3u)), "FB-B1 text: b5_text: five-digit HHMM and SRC, no authentic stored profile");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=BAD;230=185;245=8000;247=0001;dc=1FF;di=1F", b6_text(true, golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 65535u), 27, 65535u), 13, 65535u), true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: five-digit HHMM and SRC, with stored dc 0x1FF di 0x1F");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=BAD;230=185;245=8000;247=0001;dc=-;di=-", b6_text(true, golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 22, 65535u), 27, 65535u), 13, 65535u), false, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: five-digit HHMM and SRC, no authentic stored profile");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/499/100/1;2=0530/500/101/0;3=1000/4000/0/3;4=2400/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=1A2B3", b5_text(true, golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 15, 3u), 25, 2400u), true, 0x1A2B3u)), "FB-B1 text: b5_text: a mix, with stored dx 0x1A2B3");
static_assert(text_is("v=CAND;g=-;244=0;1=0000/499/100/1;2=0530/500/101/0;3=1000/4000/0/3;4=2400/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-", b5_text(true, golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 15, 3u), 25, 2400u), false, 0x1A2B3u)), "FB-B1 text: b5_text: a mix, no authentic stored profile");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=BAD;230=185;245=8000;247=0001;dc=1FF;di=1F", b6_text(true, golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 15, 3u), 25, 2400u), true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: a mix, with stored dc 0x1FF di 0x1F");
static_assert(text_is("v=CAND;232=0011;243=1;248=0001;ring=BAD;230=185;245=8000;247=0001;dc=-;di=-", b6_text(true, golden_words_with(golden_words_with(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 15, 3u), 25, 2400u), false, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: a mix, no authentic stored profile");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-", b5_text(false, GOLDEN_WORDS, true, 0x1A2B3u)), "FB-B1 text: b5_text: no candidate (NONE form)");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-", b6_text(false, GOLDEN_WORDS, true, 0x1FFu, 0x1Fu)), "FB-B1 text: b6_text: no candidate (NONE form)");
static_assert(text_is("v=CAND;g=-;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=7FFFF", b5_text(true, GOLDEN_WORDS, true, 0x7FFFFu)), "FB-B1 text: b5_text: dx 0x7FFFF");
static_assert((b5_text(true, golden_words_all(65535u), true, 0x7FFFFu).size()) == 185, "FB-B1 value: b5_text: worst case fits (all words 0xFFFF, dx 7FFFF)");
static_assert((b6_text(true, golden_words_all(65535u), true, 0x1FFu, 0x1Fu).size()) == 85, "FB-B1 value: b6_text: worst case fits");
static_assert(text_is("v=SAVED;g=7;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=D852A4FA", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 5)), "FB-B1 text: b7_text: VALID");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=D852A4FA", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 5)), "FB-B1 text: b8_text: VALID");
static_assert(text_is("v=SAVED;g=8;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=F49A36C9", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 4)), "FB-B1 text: b7_text: INVALIDATED");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=F49A36C9", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 4)), "FB-B1 text: b8_text: INVALIDATED");
static_assert(text_is("v=SAVED;g=9;244=1;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=125B6A7C", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b7_text: CORRUPT_DOMAIN");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=125B6A7C", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b8_text: CORRUPT_DOMAIN");
static_assert(text_is("v=SAVED;g=7;244=2;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=D852A4FA", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 8)), "FB-B1 text: b7_text: PROFILE_STALE over an authentic record");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=D852A4FA", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 8)), "FB-B1 text: b8_text: PROFILE_STALE over an authentic record");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0)), "FB-B1 text: b7_text: UNREADABLE class over an authentic record");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0)), "FB-B1 text: b8_text: UNREADABLE class over an authentic record");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 1)), "FB-B1 text: b7_text: NOT_CAPTURED");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 1)), "FB-B1 text: b8_text: NOT_CAPTURED");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(), 2)), "FB-B1 text: b7_text: CORRUPT");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(), 2)), "FB-B1 text: b8_text: CORRUPT");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 6)), "FB-B1 text: b7_text: PROFILE_LOST");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 6)), "FB-B1 text: b8_text: PROFILE_LOST");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 2)), "FB-B1 text: b7_text: wrong size");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 2)), "FB-B1 text: b8_text: wrong size");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0)), "FB-B1 text: b7_text: read error");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0)), "FB-B1 text: b8_text: read error");
static_assert(text_is("v=SAVED;g=4294967295;244=2;1=65535/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=65535/1000/30/1;dx=-;b=380FD594", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 4294967295; p.reg250_255[0] = 65535; p.reg250_255[5] = 65535; return ecco_fallback::seal_profile(p); }(), 5)), "FB-B1 text: b7_text: worst widths, domain-valid VALID");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=BAD;230=185;245=8000;247=0001;dc=-;di=-;b=380FD594", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 4294967295; p.reg250_255[0] = 65535; p.reg250_255[5] = 65535; return ecco_fallback::seal_profile(p); }(), 5)), "FB-B1 text: b8_text: worst widths, domain-valid VALID");
static_assert(text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b7_text: CORRUPT_DOMAIN with every value 5 digits (over 200: the NONE form)");
static_assert(text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b8_text: CORRUPT_DOMAIN with every value 5 digits (over 200: the NONE form)");
static_assert(text_is("v=SAVED;g=4294967295;244=65535;1=0000/8000/100/1;2=0530/500/20/0;3=1000/4000/0/1;4=1600/3000/50/0;5=2100/2000/100/0;6=2330/1000/30/1;dx=-;b=50E0F719", b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.generation = 4294967295; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b7_text: CORRUPT_DOMAIN with narrower values still fits");
static_assert(text_is("v=SAVED;232=0011;243=1;248=0001;ring=OK;230=185;245=8000;247=0001;dc=-;di=-;b=50E0F719", b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.generation = 4294967295; return ecco_fallback::seal_profile(p); }(), 3)), "FB-B1 text: b8_text: CORRUPT_DOMAIN with narrower values still fits");
static_assert((b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 4294967295; p.reg250_255[0] = 65535; p.reg250_255[5] = 65535; return ecco_fallback::seal_profile(p); }(), 5).size()) == 146, "FB-B1 value: b7_text: the domain-valid worst case is below 200 chars");
static_assert(([]{ const ecco_fallback::FallbackProfileV1 rec = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(); return text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, rec, 3)) && text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, rec, 3)); }()) == 1, "FB-B1 value: B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class 3 gives the NONE form in BOTH views");
static_assert(([]{ const ecco_fallback::FallbackProfileV1 rec = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(); return text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, rec, 4)) && text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, rec, 4)); }()) == 1, "FB-B1 value: B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class 4 gives the NONE form in BOTH views");
static_assert(([]{ const ecco_fallback::FallbackProfileV1 rec = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(); return text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, rec, 5)) && text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, rec, 5)); }()) == 1, "FB-B1 value: B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class 5 gives the NONE form in BOTH views");
static_assert(([]{ const ecco_fallback::FallbackProfileV1 rec = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(); return text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, rec, 8)) && text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, rec, 8)); }()) == 1, "FB-B1 value: B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class 8 gives the NONE form in BOTH views");
static_assert(([]{ const ecco_fallback::FallbackProfileV1 rec = []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(); return text_is("v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-", b7_text(0, rec, 0)) && text_is("v=NONE;232=-;243=-;248=-;ring=-;230=-;245=-;247=-;dc=-;di=-;b=-", b8_text(0, rec, 0)); }()) == 1, "FB-B1 value: B7 and B8 agree: the all-5-digit authentic CORRUPT_DOMAIN record under effective class 0 gives the NONE form in BOTH views");
static_assert(([]{ bool ok = true; ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 5).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 5).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 4).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.flags = 1; p.generation = 8; return ecco_fallback::seal_profile(p); }(), 4).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 3).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 1; p.generation = 9; return ecco_fallback::seal_profile(p); }(), 3).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 8).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 8).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0).buf[2]); ok = ok && (b7_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 1).buf[2] == b8_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 1).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(), 2).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.magic = 1; return ecco_fallback::seal_profile(p); }(), 2).buf[2]); ok = ok && (b7_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 6).buf[2] == b8_text(1, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 6).buf[2]); ok = ok && (b7_text(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 2).buf[2] == b8_text(2, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 2).buf[2]); ok = ok && (b7_text(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0).buf[2] == b8_text(3, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; return ecco_fallback::seal_profile(p); }(), 0).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 4294967295; p.reg250_255[0] = 65535; p.reg250_255[5] = 65535; return ecco_fallback::seal_profile(p); }(), 5).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.generation = 4294967295; p.reg250_255[0] = 65535; p.reg250_255[5] = 65535; return ecco_fallback::seal_profile(p); }(), 5).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 3).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 3).buf[2]); ok = ok && (b7_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.generation = 4294967295; return ecco_fallback::seal_profile(p); }(), 3).buf[2] == b8_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.generation = 4294967295; return ecco_fallback::seal_profile(p); }(), 3).buf[2]); return ok; }()) == 1, "FB-B1 value: B7 and B8 agree: both views give the same SAVED / NONE verdict on every fixture of the B7 / B8 table");
static_assert(text_is("st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-", b3_text(0, false, 0, 0u, 0x0u, "-", 0x0u, "-")), "FB-B1 text: b3_text: boot value (IDLE, nothing evaluated)");
static_assert(text_is("st=READING;prior=-;exp=-;warn=-;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=-", b3_text(1, false, 0, 0u, 0x0u, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "-")), "FB-B1 text: b3_text: READING with the persisted vector");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=OK", b3_text(2, true, 5, 120u, 0x0u, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "OK")), "FB-B1 text: b3_text: CANDIDATE_READY typical");
static_assert(text_is("st=CANDIDATE_READY;prior=NOT_CAPTURED;exp=57;warn=W1,W6;obl=FP:CM,DP:CM,R4:CM,MT:CN,FS:CM,BUS:OK;latch=-;sv=OK", b3_text(2, true, 1, 57u, 0x21u, "FP:CM,DP:CM,R4:CM,MT:CN,FS:CM,BUS:OK", 0x0u, "OK")), "FB-B1 text: b3_text: CANDIDATE_READY, exp 57, warnings W1,W6");
static_assert(text_is("st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;exp=119;warn=-;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=OK", b3_text(3, true, 0, 119u, 0x0u, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "OK")), "FB-B1 text: b3_text: CANDIDATE_NOT_SAVEABLE typical");
static_assert(text_is("st=CANDIDATE_NOT_SAVEABLE;prior=VALID;exp=3;warn=W3;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=NO:244X,PWRL1+2", b3_text(3, true, 5, 3u, 0x4u, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "NO:244X,PWRL1+2")), "FB-B1 text: b3_text: CANDIDATE_NOT_SAVEABLE with refusals");
static_assert(text_is("st=IDLE;prior=-;exp=-;warn=-;obl=FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK;latch=FP;sv=-", b3_text(0, false, 5, 100u, 0x3Fu, "FP:UR,DP:NP,R4:NP,MT:CN,FS:CA,BUS:OK", 0x1u, "NO:244X")), "FB-B1 text: b3_text: IDLE after a refusal: vector and latch kept, the rest -");
static_assert(text_is("st=IDLE;prior=-;exp=-;warn=-;obl=FP:UR,DP:MC,R4:DV,MT:CN,FS:CA,BUS:OK;latch=FP,DP,R4;sv=-", b3_text(0, false, 0, 0u, 0x0u, "FP:UR,DP:MC,R4:DV,MT:CN,FS:CA,BUS:OK", 0x211u, "-")), "FB-B1 text: b3_text: latch FP,DP,R4");
static_assert(text_is("st=CANDIDATE_NOT_SAVEABLE;prior=SAVE_UNCONFIRMED;exp=120;warn=W1,W2,W3,W4,W5,W6;obl=FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK;latch=FP,DP,R4;sv=NO:PWRL1,PWRL2,PWRL3+35", b3_text(3, true, 7, 120u, 0x3Fu, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0x111u, "NO:PWRL1,PWRL2,PWRL3+35")), "FB-B1 text: b3_text: worst case widths");
static_assert(text_is("st=CANDIDATE_READY;prior=PROFILE_STALE;exp=9;warn=-;obl=-;latch=-;sv=-", b3_text(2, true, 8, 9u, 0x0u, "", 0x0u, "")), "FB-B1 text: b3_text: an empty obl and an empty sv fall back to -");
static_assert(text_is("st=CANDIDATE_READY;prior=PROFILE_STALE;exp=10;warn=W4;obl=FP:CM,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK;latch=-;sv=OK", b3_text(2, true, 8, 10u, 0x8u, "FP:CM,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK", 0x0u, "OK")), "FB-B1 text: b3_text: prior PROFILE_STALE");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=-;latch=-;sv=OK", b3_text(2, true, 5, 120u, 0x0u, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OKX", 0x0u, "OK")), "FB-B1 text: b3_text: an obl of 37 characters falls back to - (never cut)");
static_assert(text_is("st=CANDIDATE_NOT_SAVEABLE;prior=VALID;exp=120;warn=W1,W2,W3,W4,W5,W6;obl=-;latch=FP,DP,R4;sv=NO:244X", b3_text(3, true, 5, 120u, 0x3Fu, "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 0x111u, "NO:244X")), "FB-B1 text: b3_text: an obl of 300 characters falls back to - and every key is still present");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=NO:PPPPPPPPPPPPPPPPPPPPPPP", b3_text(2, true, 5, 120u, 0x0u, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "NO:PPPPPPPPPPPPPPPPPPPPPPP")), "FB-B1 text: b3_text: an sv of exactly 26 characters is kept");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=-", b3_text(2, true, 5, 120u, 0x0u, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "NO:PPPPPPPPPPPPPPPPPPPPPPPP")), "FB-B1 text: b3_text: an sv of 27 characters falls back to -");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=120;warn=-;obl=FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=-", b3_text(2, true, 5, 120u, 0x0u, "FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS")), "FB-B1 text: b3_text: an sv of 300 characters falls back to -");
static_assert(text_is("st=CANDIDATE_NOT_SAVEABLE;prior=SAVE_UNCONFIRMED;exp=120;warn=W1,W2,W3,W4,W5,W6;obl=-;latch=FP,DP,R4;sv=-", b3_text(3, true, 7, 120u, 0x3Fu, "OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO", 0x111u, "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS")), "FB-B1 text: b3_text: an over-long obl AND sv: the latch and every key survive");
static_assert(text_is("st=IDLE;prior=-;exp=-;warn=-;obl=FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK;latch=-;sv=-", b3_text(0, false, 0, 0u, 0x0u, "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK", 0x0u, "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS")), "FB-B1 text: b3_text: an over-long sv without a candidate is - like any sv");
static_assert(text_is("st=CANDIDATE_READY;prior=VALID;exp=9;warn=-;obl=-;latch=-;sv=-", b3_text(2, true, 5, 9u, 0x0u, nullptr, 0x0u, nullptr)), "FB-B1 text: b3_text: a null obl and a null sv fall back to -");
static_assert((b3_value_fits("", 5)) == 0, "FB-B1 value: b3_value_fits 0 chars, max 5");
static_assert((b3_value_fits("a", 1)) == 1, "FB-B1 value: b3_value_fits 1 chars, max 1");
static_assert((b3_value_fits("ab", 1)) == 0, "FB-B1 value: b3_value_fits 2 chars, max 1");
static_assert((b3_value_fits("abc", 3)) == 1, "FB-B1 value: b3_value_fits 3 chars, max 3");
static_assert((b3_value_fits("abcd", 3)) == 0, "FB-B1 value: b3_value_fits 4 chars, max 3");
static_assert((b3_value_fits("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 36)) == 1, "FB-B1 value: b3_value_fits 36 chars, max 36");
static_assert((b3_value_fits("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 36)) == 0, "FB-B1 value: b3_value_fits 37 chars, max 36");
static_assert((b3_value_fits("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", 36)) == 0, "FB-B1 value: b3_value_fits 300 chars, max 36");
static_assert((b3_value_fits("XXXXXXXXXXXXXXXXXXXXXXXXXX", 26)) == 1, "FB-B1 value: b3_value_fits 26 chars, max 26");
static_assert((b3_value_fits("XXXXXXXXXXXXXXXXXXXXXXXXXXX", 26)) == 0, "FB-B1 value: b3_value_fits 27 chars, max 26");
static_assert((b3_value_fits(nullptr, 5)) == 0, "FB-B1 value: b3_value_fits: a null value");
static_assert(text_is("-", warn_text(0x0u)), "FB-B1 text: warn_text 0x00");
static_assert(text_is("W1", warn_text(0x1u)), "FB-B1 text: warn_text 0x01");
static_assert(text_is("W2", warn_text(0x2u)), "FB-B1 text: warn_text 0x02");
static_assert(text_is("W3", warn_text(0x4u)), "FB-B1 text: warn_text 0x04");
static_assert(text_is("W4", warn_text(0x8u)), "FB-B1 text: warn_text 0x08");
static_assert(text_is("W5", warn_text(0x10u)), "FB-B1 text: warn_text 0x10");
static_assert(text_is("W6", warn_text(0x20u)), "FB-B1 text: warn_text 0x20");
static_assert(text_is("W1,W6", warn_text(0x21u)), "FB-B1 text: warn_text 0x21");
static_assert(text_is("W1,W2,W3,W4,W5,W6", warn_text(0x3Fu)), "FB-B1 text: warn_text 0x3F");
static_assert(text_is("-", warn_text(0x40u)), "FB-B1 text: warn_text 0x40");
static_assert(text_is("FP:CM,DP:NP,R4:AC,MT:CN,FS:MC,BUS:BY", vector_text(SlotClass{OBL_CLEAR_PROVEN, BASIS_MARKER_CLEAR}, SlotClass{UNK_NOT_PROBED, BASIS_NONE}, SlotClass{OBL_ACTIVE, BASIS_LEASE}, SlotClass{OBL_CLEAR_PROVEN, BASIS_NO_DURABLE_STATE}, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, SlotClass{BUS_BUSY, BASIS_BUS_TXN})), "FB-B1 text: vector_text: a mixed vector");
static_assert(text_is("FP:UR,DP:UR,R4:UR,MT:UR,FS:UR,BUS:UR", vector_text(SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{}, SlotClass{})), "FB-B1 text: vector_text: the all-zero SlotClass renders UR everywhere (fail-closed)");
static_assert(text_is("No Fallback Profile action since boot", b9_seed_text()), "FB-B1 text: b9_seed_text");
static_assert(text_is("review in progress (read-only)", review_in_progress_text()), "FB-B1 text: review_in_progress_text");
static_assert(text_is("CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s", candidate_ready_text()), "FB-B1 text: candidate_ready_text");
static_assert(text_is("REVIEW EXPIRED - candidate expired (120 s); review again", review_expired_text()), "FB-B1 text: review_expired_text");
static_assert(text_is("REVIEW CLEARED - another ECCO write started since Review", review_cleared_writes_text()), "FB-B1 text: review_cleared_writes_text");
static_assert(text_is("INTERNAL - Fallback Profile dispatch context invalid; nothing written", internal_context_text()), "FB-B1 text: internal_context_text");
static_assert(text_is("REVIEW CLEARED - a temporary operation started (Free Power)", review_cleared_domain_text(2)), "FB-B1 text: review_cleared_domain_text 2");
static_assert(text_is("REVIEW CLEARED - a temporary operation started (Dump to Grid)", review_cleared_domain_text(3)), "FB-B1 text: review_cleared_domain_text 3");
static_assert(text_is("REVIEW CLEARED - a temporary operation started (Register 244 test)", review_cleared_domain_text(4)), "FB-B1 text: review_cleared_domain_text 4");
static_assert(text_is("INTERNAL - Fallback Profile operation state reset by watchdog; write lock still held - reboot required", breaker_text(true)), "FB-B1 text: breaker_text lock_held=True");
static_assert(text_is("INTERNAL - Fallback Profile operation state reset by watchdog; write lock free", breaker_text(false)), "FB-B1 text: breaker_text lock_held=False");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(0, 1, 0)), "FB-B1 text: read_fail_text code 0 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(0, 2, 0)), "FB-B1 text: read_fail_text code 0 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(0, 3, 0)), "FB-B1 text: read_fail_text code 0 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(0, 4, 0)), "FB-B1 text: read_fail_text code 0 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - no response reading registers 230/3", read_fail_text(1, 1, 0)), "FB-B1 text: read_fail_text code 1 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - no response reading registers 241/53", read_fail_text(1, 2, 0)), "FB-B1 text: read_fail_text code 1 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - no response reading registers 230/3", read_fail_text(1, 3, 0)), "FB-B1 text: read_fail_text code 1 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - no response reading registers 241/53", read_fail_text(1, 4, 0)), "FB-B1 text: read_fail_text code 1 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned an exception on registers 230/3", read_fail_text(2, 1, 0)), "FB-B1 text: read_fail_text code 2 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned an exception on registers 241/53", read_fail_text(2, 2, 0)), "FB-B1 text: read_fail_text code 2 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned an exception on registers 230/3", read_fail_text(2, 3, 0)), "FB-B1 text: read_fail_text code 2 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned an exception on registers 241/53", read_fail_text(2, 4, 0)), "FB-B1 text: read_fail_text code 2 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 230/3 could not be queued", read_fail_text(3, 1, 0)), "FB-B1 text: read_fail_text code 3 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 241/53 could not be queued", read_fail_text(3, 2, 0)), "FB-B1 text: read_fail_text code 3 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 230/3 could not be queued", read_fail_text(3, 3, 0)), "FB-B1 text: read_fail_text code 3 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 241/53 could not be queued", read_fail_text(3, 4, 0)), "FB-B1 text: read_fail_text code 3 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - non-standard reply reading registers 230/3", read_fail_text(4, 1, 0)), "FB-B1 text: read_fail_text code 4 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - non-standard reply reading registers 241/53", read_fail_text(4, 2, 0)), "FB-B1 text: read_fail_text code 4 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - non-standard reply reading registers 230/3", read_fail_text(4, 3, 0)), "FB-B1 text: read_fail_text code 4 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - non-standard reply reading registers 241/53", read_fail_text(4, 4, 0)), "FB-B1 text: read_fail_text code 4 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - short reply reading registers 230/3", read_fail_text(5, 1, 0)), "FB-B1 text: read_fail_text code 5 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - short reply reading registers 241/53", read_fail_text(5, 2, 0)), "FB-B1 text: read_fail_text code 5 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - short reply reading registers 230/3", read_fail_text(5, 3, 0)), "FB-B1 text: read_fail_text code 5 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - short reply reading registers 241/53", read_fail_text(5, 4, 0)), "FB-B1 text: read_fail_text code 5 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 230/3 did not complete within 3 s", read_fail_text(6, 1, 0)), "FB-B1 text: read_fail_text code 6 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 241/53 did not complete within 3 s", read_fail_text(6, 2, 0)), "FB-B1 text: read_fail_text code 6 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 230/3 did not complete within 3 s", read_fail_text(6, 3, 0)), "FB-B1 text: read_fail_text code 6 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - read of registers 241/53 did not complete within 3 s", read_fail_text(6, 4, 0)), "FB-B1 text: read_fail_text code 6 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", read_fail_text(7, 1, 0)), "FB-B1 text: read_fail_text code 7 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", read_fail_text(7, 2, 0)), "FB-B1 text: read_fail_text code 7 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", read_fail_text(7, 3, 0)), "FB-B1 text: read_fail_text code 7 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - inverter bus stayed busy for 7 s; press Review again", read_fail_text(7, 4, 0)), "FB-B1 text: read_fail_text code 7 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(8, 1, 0)), "FB-B1 text: read_fail_text code 8 step 1");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(8, 2, 0)), "FB-B1 text: read_fail_text code 8 step 2");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(8, 3, 0)), "FB-B1 text: read_fail_text code 8 step 3");
static_assert(text_is("REVIEW NOT COMPLETED - read did not complete (unknown cause)", read_fail_text(8, 4, 0)), "FB-B1 text: read_fail_text code 8 step 4");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned exception code 0x02 on registers 241/53", read_fail_text(READ_EXCEPTION, 2, 2)), "FB-B1 text: read_fail_text: exception code 0x02 on step 2");
static_assert(text_is("REVIEW NOT COMPLETED - inverter returned exception code 0xFF on registers 230/3", read_fail_text(READ_EXCEPTION, 1, 255)), "FB-B1 text: read_fail_text: exception code 0xFF on step 1");
static_assert(text_is("REVIEW NOT COMPLETED - short reply reading registers ?", read_fail_text(READ_SHORT, 9, 0)), "FB-B1 text: read_fail_text: an unknown step");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 244: 2 then 0); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, 0, 0u))), "FB-B1 text: pass_mismatch_text: first difference is register 244");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 256: 8000 then 501); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, 1, 501u))), "FB-B1 text: pass_mismatch_text: first difference is 256");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 274: 1 then 3); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(golden_words_with(GOLDEN_WORDS, 13, 3u), 25, 1u))), "FB-B1 text: pass_mismatch_text: first is 274 (index 13)");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 232: 17 then 19); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, 19, 19u))), "FB-B1 text: pass_mismatch_text: 232 (index 19)");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 247: 1 then 65535); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(GOLDEN_WORDS, 30, 65535u))), "FB-B1 text: pass_mismatch_text: 247 (index 30)");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 260: 2000 then 1); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, golden_words_with(golden_words_with(GOLDEN_WORDS, 20, 0u), 5, 1u))), "FB-B1 text: pass_mismatch_text: both at 5 and 20: the lower index");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 0: 0 then 0); another controller may be editing - review again", pass_mismatch_text(GOLDEN_WORDS, GOLDEN_WORDS)), "FB-B1 text: pass_mismatch_text: the passes agree");
static_assert(text_is("REVIEW NOT COMPLETED - live configuration changed during the read (register 244: 65535 then 0); another controller may be editing - review again", pass_mismatch_text(golden_words_all(65535u), golden_words_all(0u))), "FB-B1 text: pass_mismatch_text: widest values");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 0u), 8000u), golden_words_with(GOLDEN_WORDS, 0, 0u), 5, 0)), "FB-B1 text: not_saveable_text: one refusal");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile; slot 1 power 499 W < 500 W (V1 minimum)", not_saveable_text(capture_refusals(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8000u), golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 5, 0)), "FB-B1 text: not_saveable_text: two refusals");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile; slot 1 power 499 W < 500 W (V1 minimum); +1 more", not_saveable_text(capture_refusals(golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 8000u), golden_words_with(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 499u), 8, 101u), 5, 0)), "FB-B1 text: not_saveable_text: three refusals: +1 more");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=65535 unrecognised; slot 1 power 65535 W > 8000 W; +36 more", not_saveable_text(capture_refusals(golden_words_all(65535u), 8000u), golden_words_all(65535u), 5, 0)), "FB-B1 text: not_saveable_text: every refusal: +36 more");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile UNREADABLE; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 0, 4)), "FB-B1 text: not_saveable_text: class only: UNREADABLE");
static_assert(text_is("CANDIDATE NOT SAVEABLE - previous save outcome unknown; reboot to re-verify", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 7, 0)), "FB-B1 text: not_saveable_text: class only: SAVE_UNCONFIRMED");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile state does not permit saving", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 9, 0)), "FB-B1 text: not_saveable_text: class only: a class that does not permit saving");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 5, 4)), "FB-B1 text: not_saveable_text: anomaly with a permitted class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 5, 1)), "FB-B1 text: not_saveable_text: anomaly 1 (the profile key bit) with a permitted VALID class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 5, 2)), "FB-B1 text: not_saveable_text: anomaly 2 (the witness key bit) with a permitted class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile read anomaly this boot; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 5, 3)), "FB-B1 text: not_saveable_text: anomaly 3 (both key bits) with a permitted class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile; stored profile read anomaly this boot; reboot to re-derive it", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 0u), 8000u), golden_words_with(GOLDEN_WORDS, 0, 0u), 5, 1)), "FB-B1 text: not_saveable_text: a refusal and anomaly 1 with a permitted class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - stored profile UNREADABLE; reboot to re-derive it", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 0, 1)), "FB-B1 text: not_saveable_text: anomaly 1 with a class that does not permit saving: the class reason wins");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=1 Essentials - unsupported in V1; stored profile UNREADABLE; reboot to re-derive it", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 1u), 8000u), golden_words_with(GOLDEN_WORDS, 0, 1u), 0, 4)), "FB-B1 text: not_saveable_text: a refusal and the class");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=0 Allow Export - V1 can only save a Zero Export profile; slot 1 power 0 W < 500 W (V1 minimum); +1 more", not_saveable_text(capture_refusals(golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 0u), 8000u), golden_words_with(golden_words_with(GOLDEN_WORDS, 0, 0u), 1, 0u), 0, 0)), "FB-B1 text: not_saveable_text: two refusals and the class: +1 more");
static_assert(text_is("CANDIDATE NOT SAVEABLE - reason unavailable", not_saveable_text(capture_refusals(GOLDEN_WORDS, 8000u), GOLDEN_WORDS, 5, 0)), "FB-B1 text: not_saveable_text: no reason at all");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 244=7 unrecognised", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 0, 7u), 8000u), golden_words_with(GOLDEN_WORDS, 0, 7u), 5, 0)), "FB-B1 text: not_saveable_text: 244 = 7 is unrecognised");
static_assert(text_is("CANDIDATE NOT SAVEABLE - reason unavailable", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 1, 6000u), 8000u), golden_words_with(GOLDEN_WORDS, 1, 6000u), 5, 0)), "FB-B1 text: not_saveable_text: power above a 5000 ceiling is reported as site ceiling");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 3 SOC 101 % > 100", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 9, 101u), 8000u), golden_words_with(GOLDEN_WORDS, 9, 101u), 5, 0)), "FB-B1 text: not_saveable_text: SOC");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 3 source Generator / Grid+Generator unsupported in V1; slot 3 mode General/Backup/Charge unsupported in V1; +1 more", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 15, 39u), 8000u), golden_words_with(GOLDEN_WORDS, 15, 39u), 5, 0)), "FB-B1 text: not_saveable_text: source flags");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 2 start 2400 is not a valid HHMM time", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 23, 2400u), 8000u), golden_words_with(GOLDEN_WORDS, 23, 2400u), 5, 0)), "FB-B1 text: not_saveable_text: HHMM");
static_assert(text_is("CANDIDATE NOT SAVEABLE - 243=7 is not a recognised energy-management mode (0 or 1)", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 20, 7u), 8000u), golden_words_with(GOLDEN_WORDS, 20, 7u), 5, 0)), "FB-B1 text: not_saveable_text: 243");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 2 power 8001 W > 8000 W", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 2, 8001u), 8000u), golden_words_with(GOLDEN_WORDS, 2, 8001u), 5, 0)), "FB-B1 text: not_saveable_text: power 8001");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 3 power 0 W < 500 W (V1 minimum)", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 3, 0u), 8000u), golden_words_with(GOLDEN_WORDS, 3, 0u), 5, 0)), "FB-B1 text: not_saveable_text: power 0");
static_assert(text_is("CANDIDATE NOT SAVEABLE - slot 1 power 6000 W is above this site's configured ceiling", not_saveable_text(capture_refusals(golden_words_with(GOLDEN_WORDS, 1, 6000u), 5000u), golden_words_with(GOLDEN_WORDS, 1, 6000u), 5, 0)), "FB-B1 text: not_saveable_text: a site ceiling of 5000 (the PWRH reason names the site)");
static_assert((invalidate_reason_publishes("")) == 0, "FB-B1 value: invalidate_reason_publishes ''");
static_assert((invalidate_reason_publishes("superseded")) == 0, "FB-B1 value: invalidate_reason_publishes 'superseded'");
static_assert((invalidate_reason_publishes("superseded by a new Review")) == 0, "FB-B1 value: invalidate_reason_publishes 'superseded by a new Review'");
static_assert((invalidate_reason_publishes("expired")) == 1, "FB-B1 value: invalidate_reason_publishes 'expired'");
static_assert((invalidate_reason_publishes("REVIEW EXPIRED - candidate expired (120 s); review again")) == 1, "FB-B1 value: invalidate_reason_publishes 'REVIEW EXPIRED - candidate expired (120 s); review again'");
static_assert((invalidate_reason_publishes("supersede")) == 1, "FB-B1 value: invalidate_reason_publishes 'supersede'");
static_assert((invalidate_reason_publishes("s")) == 1, "FB-B1 value: invalidate_reason_publishes 's'");
static_assert((invalidate_reason_publishes(nullptr)) == 0, "FB-B1 value: invalidate_reason_publishes: a null reason");
static_assert(text_is("REVIEW REFUSED - Register 244 test is active; live settings are a temporary overlay - end it first", refusal_text(SLOT_R244, SlotClass{OBL_ACTIVE, BASIS_LEASE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("REVIEW REFUSED - a failback episode record exists; only the firmware that created it can resolve it", refusal_text(SLOT_R244, SlotClass{OBL_ACTIVE, BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("REVIEW REFUSED - a Register 244 test start is in progress; live settings are about to become a temporary overlay", refusal_text(SLOT_R244, SlotClass{OBL_STARTING, BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("REVIEW REFUSED - a Register 244 test start is in progress; live settings are about to become a temporary overlay", refusal_text(SLOT_R244, SlotClass{OBL_STARTING, BASIS_COMMITTED}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_STARTING BASIS_COMMITTED");
static_assert(text_is("REVIEW REFUSED - Register 244 test must restore original settings first", refusal_text(SLOT_R244, SlotClass{OBL_RESTORE_REQUIRED, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_RESTORE_REQUIRED BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Register 244 test restore verified; durable clear still pending - press Restore Original (armed)", refusal_text(SLOT_R244, SlotClass{OBL_PENDING_CLEAR, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - a Register 244 test restore or recovery action is running; try again when it finishes", refusal_text(SLOT_R244, SlotClass{OBL_ENDING, BASIS_OPERATOR_ACTION_RUNNING}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_ENDING BASIS_OPERATOR_ACTION_RUNNING");
static_assert(text_is("REVIEW REFUSED - a Register 244 test restore or recovery action is running; try again when it finishes", refusal_text(SLOT_R244, SlotClass{OBL_ENDING, BASIS_RESTORE_RUNNING}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_ENDING BASIS_RESTORE_RUNNING");
static_assert(text_is("REVIEW REFUSED - Register 244 test needs an operator recovery action first", refusal_text(SLOT_R244, SlotClass{OBL_OPERATOR_NEEDED, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 OBL_OPERATOR_NEEDED BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Register 244 test recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", refusal_text(SLOT_R244, SlotClass{UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("REVIEW REFUSED - Register 244 test recovery marker became unreadable at runtime; review blocked until reboot. After reboot it may read absent: verify live settings first; do not erase NVS", refusal_text(SLOT_R244, SlotClass{UNK_DURABLE_UNREADABLE, BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_DURABLE_UNREADABLE BASIS_RUNTIME_PROBE");
static_assert(text_is("REVIEW REFUSED - Register 244 test recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", refusal_text(SLOT_R244, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("REVIEW REFUSED - Register 244 test recovery marker is malformed (found at runtime); review blocked until reboot, which re-derives it as a hard lockout", refusal_text(SLOT_R244, SlotClass{UNK_METADATA_CORRUPT, BASIS_RUNTIME_PROBE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_METADATA_CORRUPT BASIS_RUNTIME_PROBE");
static_assert(text_is("REVIEW REFUSED - durable state not loaded yet (starting up)", refusal_text(SLOT_R244, SlotClass{UNK_BOOT_NOT_LOADED, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_BOOT_NOT_LOADED BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Register 244 test stored marker says RESTORE_REQUIRED but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore its saved original)", refusal_text(SLOT_R244, SlotClass{UNK_DIVERGED, BASIS_GHOST_RR}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_DIVERGED BASIS_GHOST_RR");
static_assert(text_is("REVIEW REFUSED - Register 244 test stored marker says PENDING_CLEAR but memory says clear; review blocked until reboot, which re-derives it (the domain may then restore its saved original)", refusal_text(SLOT_R244, SlotClass{UNK_DIVERGED, BASIS_GHOST_PC}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_DIVERGED BASIS_GHOST_PC");
static_assert(text_is("REVIEW REFUSED - Register 244 test in-memory recovery state is inconsistent; a reboot must re-derive it before review", refusal_text(SLOT_R244, SlotClass{UNK_DIVERGED, BASIS_RAM_INCONSISTENT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_DIVERGED BASIS_RAM_INCONSISTENT");
static_assert(text_is("REVIEW REFUSED - Register 244 test in-progress flag is set with no running operation (possible leak); a reboot re-derives it", refusal_text(SLOT_R244, SlotClass{UNK_BUS_OR_LOCK_STUCK, BASIS_OP_FLAG_UNATTRIBUTED}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_BUS_OR_LOCK_STUCK BASIS_OP_FLAG_UNATTRIBUTED");
static_assert(text_is("REVIEW REFUSED - Register 244 test state does not permit a review", refusal_text(SLOT_R244, SlotClass{UNK_NOT_PROBED, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_R244 UNK_NOT_PROBED BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Free Power is active; live settings are a temporary overlay - end it first", refusal_text(SLOT_FP, SlotClass{OBL_ACTIVE, BASIS_LEASE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("REVIEW REFUSED - a failback episode record exists; only the firmware that created it can resolve it", refusal_text(SLOT_FP, SlotClass{OBL_ACTIVE, BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("REVIEW REFUSED - a Free Power start is in progress; live settings are about to become a temporary overlay", refusal_text(SLOT_FP, SlotClass{OBL_STARTING, BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("REVIEW REFUSED - Free Power restore verified; durable clear still pending", refusal_text(SLOT_FP, SlotClass{OBL_PENDING_CLEAR, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Free Power recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", refusal_text(SLOT_FP, SlotClass{UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("REVIEW REFUSED - Free Power recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", refusal_text(SLOT_FP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FP UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("REVIEW REFUSED - Dump to Grid is active; live settings are a temporary overlay - end it first", refusal_text(SLOT_DUMP, SlotClass{OBL_ACTIVE, BASIS_LEASE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("REVIEW REFUSED - a failback episode record exists; only the firmware that created it can resolve it", refusal_text(SLOT_DUMP, SlotClass{OBL_ACTIVE, BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("REVIEW REFUSED - a Dump to Grid start is in progress; live settings are about to become a temporary overlay", refusal_text(SLOT_DUMP, SlotClass{OBL_STARTING, BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("REVIEW REFUSED - Dump to Grid restore verified; durable clear still pending", refusal_text(SLOT_DUMP, SlotClass{OBL_PENDING_CLEAR, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", refusal_text(SLOT_DUMP, SlotClass{UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", refusal_text(SLOT_DUMP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_DUMP UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("REVIEW REFUSED - Failback record is active; live settings are a temporary overlay - end it first", refusal_text(SLOT_FBS, SlotClass{OBL_ACTIVE, BASIS_LEASE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS OBL_ACTIVE BASIS_LEASE");
static_assert(text_is("REVIEW REFUSED - a failback episode record exists; only the firmware that created it can resolve it", refusal_text(SLOT_FBS, SlotClass{OBL_ACTIVE, BASIS_FBS_EPISODE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS OBL_ACTIVE BASIS_FBS_EPISODE");
static_assert(text_is("REVIEW REFUSED - a Failback record start is in progress; live settings are about to become a temporary overlay", refusal_text(SLOT_FBS, SlotClass{OBL_STARTING, BASIS_PRE_COMMIT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS OBL_STARTING BASIS_PRE_COMMIT");
static_assert(text_is("REVIEW REFUSED - Failback record restore verified; durable clear still pending", refusal_text(SLOT_FBS, SlotClass{OBL_PENDING_CLEAR, BASIS_NONE}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS OBL_PENDING_CLEAR BASIS_NONE");
static_assert(text_is("REVIEW REFUSED - Failback record recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it", refusal_text(SLOT_FBS, SlotClass{UNK_DURABLE_UNREADABLE, BASIS_BOOT_READ_ERROR}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS UNK_DURABLE_UNREADABLE BASIS_BOOT_READ_ERROR");
static_assert(text_is("REVIEW REFUSED - Failback record recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", refusal_text(SLOT_FBS, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 0, "x", 0u)), "FB-B1 text: refusal_text SLOT_FBS UNK_METADATA_CORRUPT BASIS_BOOT_LOCKOUT");
static_assert(text_is("REVIEW REFUSED - Dump to Grid recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS; containment K=5", refusal_text(SLOT_DUMP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 5, "", 0u)), "FB-B1 text: refusal_text SLOT_DUMP corrupt with containment K=5");
static_assert(text_is("REVIEW REFUSED - Free Power recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS", refusal_text(SLOT_FP, SlotClass{UNK_METADATA_CORRUPT, BASIS_BOOT_LOCKOUT}, 5, "", 0u)), "FB-B1 text: refusal_text SLOT_FP corrupt ignores the Dump K");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Free Power); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "Free Power", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner Free Power");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Register 244 test); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "Register 244 test", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner Register 244 test");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Dump to Grid); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "Dump to Grid", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner Dump to Grid");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (Fallback Profile); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "Fallback Profile", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner Fallback Profile");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (clock correction); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "clock correction", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner clock correction");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (clock verification); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "clock verification", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner clock verification");
static_assert(text_is("REVIEW REFUSED - another inverter transaction is in progress (manual write); try again shortly", refusal_text(SLOT_BUS, SlotClass{BUS_BUSY, BASIS_BUS_TXN}, 0, "manual write", 0u)), "FB-B1 text: refusal_text SLOT_BUS busy, owner manual write");
static_assert(text_is("REVIEW REFUSED - inverter write lock held for 300 s (possible leak); a reboot may be required", refusal_text(SLOT_BUS, SlotClass{UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK}, 0, "", 300u)), "FB-B1 text: refusal_text SLOT_BUS stuck, 300 s");
static_assert(text_is("REVIEW REFUSED - inverter write lock held for 4294967 s (possible leak); a reboot may be required", refusal_text(SLOT_BUS, SlotClass{UNK_BUS_OR_LOCK_STUCK, BASIS_LOCK_STUCK}, 0, "", 4294967u)), "FB-B1 text: refusal_text SLOT_BUS stuck, 4294967 s");
static_assert(text_is("REVIEW REFUSED - another Fallback Profile operation is in progress", refused_in_flight_text()), "FB-B1 text: refused_in_flight_text");
static_assert(text_is("REVIEW REFUSED - durable state not loaded yet (starting up)", refused_not_loaded_text()), "FB-B1 text: refused_not_loaded_text");
static_assert(text_is("REVIEW REFUSED - a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first", refused_arms_text()), "FB-B1 text: refused_arms_text");
static_assert(((b2_text(0, []{ ecco_fallback::FallbackProfileV1 p = GOLDEN_PROFILE; p.reg244 = 65535; p.reg256_261[0] = 65535; p.reg256_261[1] = 65535; p.reg256_261[2] = 65535; p.reg256_261[3] = 65535; p.reg256_261[4] = 65535; p.reg256_261[5] = 65535; p.reg268_273[0] = 65535; p.reg268_273[1] = 65535; p.reg268_273[2] = 65535; p.reg268_273[3] = 65535; p.reg268_273[4] = 65535; p.reg268_273[5] = 65535; p.reg274_279[0] = 65535; p.reg274_279[1] = 65535; p.reg274_279[2] = 65535; p.reg274_279[3] = 65535; p.reg274_279[4] = 65535; p.reg274_279[5] = 65535; p.reg250_255[0] = 65535; p.reg250_255[1] = 65535; p.reg250_255[2] = 65535; p.reg250_255[3] = 65535; p.reg250_255[4] = 65535; p.reg250_255[5] = 65535; p.reg232 = 65535; p.reg243 = 65535; p.reg248 = 65535; p.reg230 = 65535; p.reg245 = 65535; p.reg247 = 65535; p.generation = 4294967295; p.captured_epoch = 4294967295; return ecco_fallback::seal_profile(p); }(), 0, golden_witness(4294967294u, 4294967293u, 0x1122334455667788ULL, 1, ecco_fbdurable::FALLBACK_PROFILE_KEY, 1), 5, 4294967295u, 4294967295u)).size()) == 127, "FB-B1 value: length of the b2 worst case");
static_assert((b3_text(3, true, 7, 120u, 0x3Fu, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0x0111u, "NO:PWRL1,PWRL2,PWRL3+35").size()) == 162, "FB-B1 value: length of the b3 worst case");
static_assert((b3_text(3, true, 7, 4294967295u, 0xFFFFu, "FP:UR,DP:UR,R4:UR,MT:NP,FS:UR,BUS:LK", 0xFFFFu, "NNNNNNNNNNNNNNNNNNNNNNNNNN").size()) == 172, "FB-B1 value: length of the b3 absolute worst case (every argument at its maximum: 172)");
// ---- GENERATED-GOLDENS-END ----

}  // namespace ecco_fbcap
