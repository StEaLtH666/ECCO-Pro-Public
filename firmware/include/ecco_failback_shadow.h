#pragma once

// FB-C2: Failback Shadow EVALUATOR - PURE MODEL.
//
// FB-C2 turns the FB-C1 shadow instrumentation into a real "what would a future failback engine do now" evaluator. It is
// SHADOW ONLY: every decision in here is a pure function of plain values, nothing here can run unless the one 1 s
// shadow tick calls it, and the result is only ever published as text. There is no authority in this header or behind
// it: no bus access, no storage access, no entity, no clock (time is always a parameter), no declared durable record.
//
//   - it includes only standard headers and the FB-B shared model header ecco_fallback_capture.h (which brings the FB-A
//     and FB-B0 models along);
//   - every namespace-scope object is constexpr; there is no `static`, no `inline` and no state, so identical inputs
//     give identical outputs (golden vectors pin this);
//   - it re-implements NOTHING that FB-B1 / FB-B3 already decide. The per-domain classifiers (classify_fp / dump / r244 /
//     bus), the live-cache trust rule (live_trust, the write fence compare), the four comparison masks, the tri-state
//     export hazard and the effective profile class are the ecco_fbcap:: functions the Live Match (B10) uses; this file
//     only adds the shadow-specific layers on top of them (the evidence of a clear lease domain, the S4 first-match
//     precedence table, the plan -> FB-A mapping and the text builders).
//
// Architecture: docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md sections 6-8 (FINAL wins), design/S4 sections 2-9.
// Offline mirror: registry/failback_shadow.py (same names, same behaviour).
//
// ENTRY POINTS
//   evaluate(const ShadowInputs &)        one deterministic plan (S4 3.4: E0 E1 S1 S2 then L1..L26) + every telemetry mask
//   plan_name / reason_name_ok            the Verdict text and the reason range check
//   inputs_text(in, plan)                 the Inputs entity text (<= 200 characters)
//   state_name(phase, would_latched, stable)   the State entity text
//   close_outcome / kind_for_edge         the FB-F latch model the episode machine needs (E1 kind, E4 outcome)
//
// Collector contract (the 1 s tick gathers plain values into the POD structs below, makes the call, publishes):
//   the tick evaluates ONCE per tick in MODE_IF_LOST (S3 11.4). That readiness plan is the Verdict (FINAL 8.5, S3 9.2, S5 2.3:
//   outside an episode "what would happen if HA were lost now"; inside an episode MODE_IF_LOST and MODE_ACTUAL give the same
//   plan, so it is also the continuation) and the plan a LOST edge freezes. MODE_ACTUAL (the supervision rows S1 / S2) stays
//   for the decision-table goldens; its NO_ACTION / WOULD_REFUSE_STARTS are never published. The shadow never probes storage,
//   so the durable leg of a lease domain is always "not probed" and its evidence comes from the boot load (see domain_state).

#include <array>
#include <cstddef>
#include <cstdint>

#include "ecco_fallback_capture.h"

namespace ecco_failback_shadow {

// ---------------------------------------------------------------------------
// Constants (S4 3.7: telemetry only, never a write)
// ---------------------------------------------------------------------------
constexpr uint32_t kOwnerGraceMs = 10000u;  // an operation flag with no running owner is "settling" below this age, "stuck" at or above
constexpr uint32_t kCipStuckMs = 60000u;    // the RTC correction lock counts as stuck after this
constexpr uint8_t NONE_U8 = 0xFFu;          // "-" in every optional u8 field

enum Mode : uint8_t { MODE_ACTUAL = 0, MODE_IF_LOST = 1 };

// Plan codes (S4 8.1; numeric values frozen from FB-C2 on, never reused). 16 is reserved and never produced.
enum PlanCode : uint8_t {
  PLAN_NOT_EVALUATED = 0,
  PLAN_NO_ACTION = 1,
  PLAN_WOULD_REFUSE_STARTS = 2,
  PLAN_WOULD_PREEMPT_DUMP = 10,
  PLAN_WOULD_PREEMPT_FREE_POWER = 11,
  PLAN_WAIT_DUMP_RESTORE = 12,
  PLAN_WAIT_FREE_POWER_RESTORE = 13,
  PLAN_WAIT_WRITE_IN_FLIGHT = 14,
  PLAN_WAIT_LIVE_DATA = 15,
  PLAN_WAIT_MANUAL_TOU_RECOVERY = 16,  // reserved for a future Manual TOU journal
  PLAN_BLOCKED_RECOVERY_METADATA = 20,
  PLAN_BLOCKED_DURABLE_UNKNOWN = 21,
  PLAN_BLOCKED_OPERATOR_NEEDED = 22,
  PLAN_BLOCKED_PROFILE_CORRUPT = 23,
  PLAN_BLOCKED_PROFILE_UNAVAILABLE = 24,
  PLAN_BLOCKED_SITE_CEILING = 25,
  PLAN_BLOCKED_CONTEXT_MISMATCH = 26,
  PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN = 27,
  PLAN_BLOCKED_NO_PROFILE = 30,
  PLAN_BLOCKED_PROFILE_INVALIDATED = 31,
  PLAN_WOULD_ALREADY_MATCH = 40,
  PLAN_WOULD_APPLY_PROFILE = 41,
  PLAN_WOULD_REMAIN_LATCHED = 50,  // emitted by the episode layer only, never by evaluate()
};

enum BlockingDomain : uint8_t {
  BD_NONE = 0, BD_SUPERVISION = 1, BD_BOOT = 2, BD_DUMP = 3, BD_FP = 4, BD_R244 = 5,
  BD_BUS = 6, BD_MTOU = 7, BD_MTOU_JOURNAL = 8, BD_FBP = 9, BD_SITE = 10, BD_LIVE = 11,
};

// S4 3.3: C0 class, obligation kind and clear evidence. 0 is the fail-closed value of each.
enum C0 : uint8_t { C0_UNKNOWN = 0, C0_OBLIGATION = 1, C0_CLEAR_PROVEN = 2 };
enum Kind : uint8_t {
  KIND_NONE = 0, KIND_ACTIVE = 1, KIND_STARTING = 2, KIND_RESTORE_REQUIRED = 3, KIND_ENDING = 4,
  KIND_PENDING_CLEAR = 5, KIND_OPERATOR_NEEDED = 6, KIND_IN_FLIGHT = 7,
  KIND_DURABLE_UNREADABLE = 16, KIND_METADATA_CORRUPT = 17, KIND_BOOT_NOT_LOADED = 19, KIND_DIVERGED = 20,
  KIND_BUS_OR_LOCK_STUCK = 21, KIND_PROBE_PENDING = 23,  // 23: FB-E / FB-F only, never produced here
};
enum Evidence : uint8_t {
  EV_NONE = 0, EV_MARKER_CLEAR_BOOT = 1, EV_MARKER_CLEAR_RUNTIME = 2, EV_MARKER_CLEAR_PROBE = 3, EV_MARKER_ABSENT = 4,
  EV_NO_DURABLE_RECORD = 5, EV_NOT_IMPLEMENTED = 6, EV_IDLE = 7,
};

// Domain slots of ShadowPlan::dom, in the S4 tie-break order.
enum DomSlot : uint8_t { DS_DUMP = 0, DS_FP = 1, DS_R244 = 2, DS_BUS = 3, DS_MTOU = 4, DS_MTOU_JOURNAL = 5, DS_FBP = 6 };
constexpr size_t DOM_COUNT = 7;

// Reason codes (S4 8.3; RAM-only, numeric, append-only: 209 and 306 are intentionally unused). 510 and 511 are the FB-C2
// appendices for the two profile cases the FINAL document adds to the profile table (a VALID record whose witness is not
// consistent, and a stale record).
enum Reason : uint16_t {
  RS_NONE = 0,
  RS_SUP_STABLE = 1, RS_SUP_STARTUP = 2, RS_SUP_SUSPECT = 3, RS_SUP_UNSTABLE = 4, RS_SUP_LOST = 5,
  RS_SUP_RETURNED_EPISODE_OPEN = 6, RS_IF_LOST_READINESS = 7, RS_BOOT_NOT_LOADED = 10, RS_INPUT_INVALID = 11,
  RS_DUMP_ACTIVE = 101, RS_DUMP_STARTING = 102, RS_DUMP_RESTORE_DUE = 103, RS_DUMP_RESTORE_BACKOFF = 104,
  RS_DUMP_RESTORE_RUNNING = 105, RS_DUMP_CLEAR_PENDING = 106, RS_DUMP_OPERATOR_NEEDED = 107,
  RS_DUMP_OPERATOR_NEEDED_EXPORT_LIVE = 108, RS_DUMP_FORCE_QUEUED = 109, RS_DUMP_METADATA_CORRUPT = 110,
  RS_DUMP_MARKER_UNREADABLE = 111, RS_DUMP_MARKER_DIVERGED = 112, RS_DUMP_PROBE_UNREADABLE = 113,
  RS_DUMP_PROBE_MALFORMED = 114, RS_DUMP_MARKER_EVIDENCE_VANISHED = 115, RS_DUMP_MARKER_LOST = 116,
  RS_DUMP_MARKER_ABSENT_UNPROVEN = 117, RS_DUMP_RAM_INCONSISTENT = 118, RS_DUMP_OP_FLAG_STUCK = 119,
  RS_DUMP_OP_FLAG_SETTLING = 120,
  RS_FP_ACTIVE = 201, RS_FP_STARTING = 202, RS_FP_RESTORE_DUE = 203, RS_FP_RESTORE_BACKOFF = 204,
  RS_FP_RESTORE_RUNNING = 205, RS_FP_OPERATOR_ACTION_RUNNING = 206, RS_FP_CLEAR_PENDING = 207,
  RS_FP_OPERATOR_NEEDED = 208, RS_FP_METADATA_CORRUPT = 210, RS_FP_MARKER_UNREADABLE = 211, RS_FP_MARKER_DIVERGED = 212,
  RS_FP_PROBE_UNREADABLE = 213, RS_FP_PROBE_MALFORMED = 214, RS_FP_MARKER_EVIDENCE_VANISHED = 215,
  RS_FP_MARKER_LOST = 216, RS_FP_MARKER_ABSENT_UNPROVEN = 217, RS_FP_RAM_INCONSISTENT = 218, RS_FP_OP_FLAG_STUCK = 219,
  RS_FP_OP_FLAG_SETTLING = 220,
  RS_R244_HELD = 301, RS_R244_HELD_DRIFT_GUARD = 302, RS_R244_CLEAR_PENDING_OPERATOR = 303, RS_R244_APPLY_RUNNING = 304,
  RS_R244_RESTORE_RUNNING = 305, RS_R244_METADATA_CORRUPT = 307, RS_R244_MARKER_UNREADABLE = 308,
  RS_R244_MARKER_DIVERGED = 309, RS_R244_PROBE_UNREADABLE = 310, RS_R244_PROBE_MALFORMED = 311,
  RS_R244_MARKER_EVIDENCE_VANISHED = 312, RS_R244_RAM_INCONSISTENT = 313, RS_R244_OP_FLAG_STUCK = 314,
  RS_R244_MARKER_ABSENT_UNPROVEN = 315, RS_R244_OP_FLAG_SETTLING = 316,
  RS_MTOU_APPLY_RUNNING = 401, RS_FBB_CAPTURE_RUNNING = 402, RS_RTC_CORRECTION_RUNNING = 403,
  RS_LOCK_HELD_OWNER_RUNNING = 404, RS_LOCK_HELD_NO_KNOWN_OWNER = 405, RS_RTC_LOCK_STUCK = 406,
  RS_LOCK_HELD_SETTLING = 407, RS_MTOU_JOURNAL_OBLIGATION = 410,
  RS_PROFILE_NOT_CAPTURED = 501, RS_PROFILE_INVALIDATED = 502, RS_PROFILE_CORRUPT = 503, RS_PROFILE_CORRUPT_DOMAIN = 504,
  RS_PROFILE_UNREADABLE = 505, RS_PROFILE_LOST = 506, RS_PROFILE_SAVE_UNCONFIRMED = 507,
  RS_PROFILE_CHANGED_SINCE_LOST = 508, RS_PROFILE_ABSENT_UNPROVEN = 509, RS_PROFILE_NOT_WRITER_USABLE = 510,
  RS_PROFILE_STALE = 511,
  RS_SITE_CEILING_BELOW_PROFILE = 601,
  RS_LIVE_CACHE_INVALID = 610, RS_LIVE_CACHE_STALE = 611, RS_LIVE_POLLING_OFF = 612, RS_LIVE_CACHE_PRE_FENCE = 613,
  RS_LIVE_NOT_LATCHED = 614,
  RS_CTX_SLOT_TIMES = 620, RS_CTX_243 = 621, RS_CTX_232_BIT0 = 622, RS_CTX_248_BIT0 = 623, RS_CTX_MULTIPLE = 624,
  RS_LIVE_244_ESSENTIALS = 630, RS_LIVE_244_UNRECOGNISED = 631, RS_LIVE_POWER_OUT_OF_RANGE = 632,
  RS_LIVE_SOC_OUT_OF_RANGE = 633, RS_LIVE_SOURCE_WORD_UNSUPPORTED = 634, RS_LIVE_MULTIPLE_OUT_OF_DOMAIN = 635,
  RS_MATCH_E1_AND_CTX = 701, RS_E1_DELTA = 702,
};

// The precedence row that produced the plan (tests and telemetry only). L1..L26 are the numbers of S4 3.4; the
// two FB-C2 appendices sit between them numerically (they share the "profile unusable" group).
enum Row : uint8_t {
  ROW_NONE = 0,
  ROW_L1 = 1, ROW_L2 = 2, ROW_L3 = 3, ROW_L4 = 4, ROW_L5 = 5, ROW_L6 = 6, ROW_L7 = 7, ROW_L8 = 8, ROW_L9 = 9, ROW_L10 = 10,
  ROW_L12 = 12, ROW_L13 = 13, ROW_L14 = 14, ROW_L15 = 15, ROW_L16 = 16, ROW_L17 = 17, ROW_L18 = 18, ROW_L19 = 19,
  ROW_L20 = 20, ROW_L21 = 21, ROW_L22 = 22, ROW_L23 = 23, ROW_L24 = 24, ROW_L25 = 25, ROW_L26 = 26,
  ROW_L15_STALE = 28, ROW_L20_NOT_USABLE = 29,
  ROW_E0 = 90, ROW_E1 = 91, ROW_S1 = 92, ROW_S2 = 93,
};

// e1 / cx / in letters of the Inputs entity (S3 9.2): N not evaluable, M match, D differ, O overlay (the cache is not a baseline).
enum CmpState : uint8_t { CMP_N = 0, CMP_M = 1, CMP_D = 2, CMP_O = 3 };
constexpr char cmp_char(uint8_t s) { return s == CMP_M ? 'M' : s == CMP_D ? 'D' : s == CMP_O ? 'O' : 'N'; }

// Projected E1 frames (S4 3.5 / FINAL 6.7 `blk`). Never a 230 / 245 / 247 step and never a CTX word.
constexpr uint8_t FR_F244 = 1u;       // 244 0 -> 2, the only permitted 244 write
constexpr uint8_t FR_F256_DOWN = 2u;
constexpr uint8_t FR_F268_279 = 4u;
constexpr uint8_t FR_F256_UP = 8u;

// FB-F latch model (S3 7.2): the outcome at the close of a shadow episode and the kind of the next one.
enum Fbf : uint8_t { FBF_NONE = 0, FBF_A = 1, FBF_P = 2 };       // would await ACK / would self-clear
enum EpKind : uint8_t { EPK_NONE = 0, EPK_N = 1, EPK_L = 2 };    // FB-F would open a new episode / would do nothing new

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------
struct SupIn {
  uint8_t state = 0;  // supervision_state: 0 STARTUP, 1 SUPERVISED, 2 SUSPECT, 3 LOST
  bool p_stable = false;
  bool episode_open = false;  // shadow phase OPEN or HA_BACK
};

// What the shared ecco_fbcap::GateInputs does not carry about one lease domain (all assigned by the 1 s tick).
struct DomExtra {
  bool backoff = false;          // a restore retry is waiting for its backoff (FP / Dump)
  uint32_t orphan_ms = 0;        // how long an operation flag has been set with no running owner (0 = not orphaned)
  bool used_since_boot = false;  // the domain was seen busy since the boot load
  bool retry_on_raw = false;     // FP: free_power_operator_needed as loaded; Dump / R244: false (that evidence is not retained)
  bool force_bypass = false;     // Dump only: dump_force_restore_bypass
};
struct R244Extra {
  bool lav = false;  // reg244_last_applied_valid
  uint16_t la = 0;   // reg244_last_applied_value
};
struct BusExtra {
  bool any_owner_running = false;  // some inverter-write owner script is running
  uint32_t mwip_orphan_ms = 0;     // how long manual_write_in_progress has been set with no running owner (0 = not)
  uint32_t cip_held_ms = 0;        // how long the RTC correction lock has been held (0 = not held)
};
// The Free Power original, for the one-level projection after a pre-empt (FP snapshot registers, valid iff the FP snapshot is).
struct FpSnapshot {
  bool valid = false;
  uint16_t r232 = 0;
  std::array<uint16_t, 6> r256{};
  std::array<uint16_t, 6> r268{};
  std::array<uint16_t, 6> r274{};
};
// The profile identity bound at the LOST edge (S4 6.2). `bound` is true exactly while an episode is open.
struct EpProf {
  bool bound = false;
  uint8_t cls = 0;
  uint32_t gen = 0;
  uint64_t binding = 0;
};

struct ShadowInputs {
  uint8_t mode = MODE_ACTUAL;
  SupIn sup{};
  // The shared B10 input record: RAM legs of every lease domain, the bus, the profile mirror (class, overlay, anomaly, stored
  // record), the live-cache trust terms (with the write fence already folded into cache.fence_seq), the 31 live words in
  // REGS order and the Dump original. Fail-closed defaults: an unfilled record never reads as trusted.
  ecco_fbcap::LiveMatchInputs lm{};
  uint8_t profile_why = ecco_fbdurable::WHY_PROFILE_READ;  // EpcWhy of the mirror; the default is "not usable"
  bool not_captured_proven = false;  // true only for a witness present with generation 0, a state FB-B0 never produces
  bool absence_witness = false;      // reserved for FB-D; the shadow always passes false
  bool fp_lease_ctx_unknown = false; // free_power_lease_context_reg244 == -1
  DomExtra fp{};
  DomExtra dump{};
  DomExtra r244{};
  R244Extra r244x{};
  BusExtra bus{};
  uint8_t mtou_journal = 0;  // 0 = NOT_IMPLEMENTED; any other value is an invalid input
  EpProf ep{};
  FpSnapshot fp_snap{};
};

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
struct DomView {
  uint8_t c0 = C0_UNKNOWN;
  uint8_t kind = KIND_NONE;
  uint8_t evidence = EV_NONE;
  uint8_t detail = 0;  // Dump: containment state << 4; FBP: the effective class
};

struct ShadowPlan {
  uint8_t plan = PLAN_NOT_EVALUATED;
  uint16_t reason = RS_NONE;
  uint8_t blocking_domain = BD_NONE;
  uint8_t row = ROW_NONE;
  uint8_t fba_state = NONE_U8;          // Policy-B projection: ecco_fallback::FailbackState, or 0xFF = RAM-only
  uint8_t fba_result = NONE_U8;         // ecco_fallback::FailbackResult, or 0xFF
  uint8_t fba_result_policy_a = NONE_U8;
  uint8_t projected_after = PLAN_NOT_EVALUATED;
  uint8_t alt_plan_absence_accepted = PLAN_NOT_EVALUATED;
  uint8_t export_hazard = ecco_fbcap::EH_UNKNOWN;
  // FINAL 8.2's obligation term of export_hazard: a FP / Dump / R244 domain is not clear and is neither ACTIVE nor STARTING.
  // Only an evaluated plan sets it (false for E0 / E1). The soak counts export-hazard time only while it holds.
  bool hazard_obligation = false;
  uint8_t ca = ecco_fbcap::CQ_BOOT;     // the cache-quality term (ecco_fbcap::CacheQuality)
  bool would_refuse_starts = false;
  bool would_preempt_fp = false;
  bool would_preempt_dump = false;
  bool would_apply = false;
  bool would_write_244 = false;
  bool absence_relied = false;
  bool durable_leg_projected = false;
  bool fp_stale_operator_needed = false;
  bool dump_stale_operator_needed = false;  // a retained Dump retry with a present CLEAR marker (the tick passes no such evidence today)
  bool r244_lav_marker_absent = false;
  bool fp_ctx_unknown = false;
  bool profile_changed_since_lost = false;
  bool dump_force_bypass_armed = false;
  bool sup_returned_episode_open = false;
  bool masks_valid = false;                 // the four masks below are meaningful
  uint32_t e1_delta_mask = 0;               // bit0 244; bits 1-6 256-261; bits 7-12 268-273; bits 13-18 274-279
  uint32_t out_of_domain_mask = 0;          // same layout, over the live words
  uint16_t ctx_mismatch_mask = 0;           // bit0 232.b0; bit1 243; bit2 248.b0; bits 3-8 250-255
  uint8_t info_mismatch_mask = 0;           // bit0 230; bit1 245; bit2 247; bit3 232 bits1-15; bit4 248 bits1-15
  uint8_t delta_count = NONE_U8;            // popcount(e1_delta_mask), 0xFF when the masks are not valid
  uint8_t e1_state = CMP_N;
  uint8_t cx_state = CMP_N;
  uint8_t in_state = CMP_N;
  uint8_t projected_frames = 0;             // FR_* bits, only while the plan is WOULD_APPLY_PROFILE
  uint8_t projected_frame_count = 0;
  std::array<DomView, DOM_COUNT> dom{};
};

// ---------------------------------------------------------------------------
// Names
// ---------------------------------------------------------------------------
constexpr const char *plan_name(uint8_t plan) {
  switch (plan) {
    case PLAN_NO_ACTION: return "NO_ACTION";
    case PLAN_WOULD_REFUSE_STARTS: return "WOULD_REFUSE_STARTS";
    case PLAN_WOULD_PREEMPT_DUMP: return "WOULD_PREEMPT_DUMP";
    case PLAN_WOULD_PREEMPT_FREE_POWER: return "WOULD_PREEMPT_FREE_POWER";
    case PLAN_WAIT_DUMP_RESTORE: return "WAIT_DUMP_RESTORE";
    case PLAN_WAIT_FREE_POWER_RESTORE: return "WAIT_FREE_POWER_RESTORE";
    case PLAN_WAIT_WRITE_IN_FLIGHT: return "WAIT_WRITE_IN_FLIGHT";
    case PLAN_WAIT_LIVE_DATA: return "WAIT_LIVE_DATA";
    case PLAN_WAIT_MANUAL_TOU_RECOVERY: return "WAIT_MANUAL_TOU_RECOVERY";
    case PLAN_BLOCKED_RECOVERY_METADATA: return "BLOCKED_RECOVERY_METADATA";
    case PLAN_BLOCKED_DURABLE_UNKNOWN: return "BLOCKED_DURABLE_UNKNOWN";
    case PLAN_BLOCKED_OPERATOR_NEEDED: return "BLOCKED_OPERATOR_NEEDED";
    case PLAN_BLOCKED_PROFILE_CORRUPT: return "BLOCKED_PROFILE_CORRUPT";
    case PLAN_BLOCKED_PROFILE_UNAVAILABLE: return "BLOCKED_PROFILE_UNAVAILABLE";
    case PLAN_BLOCKED_SITE_CEILING: return "BLOCKED_SITE_CEILING";
    case PLAN_BLOCKED_CONTEXT_MISMATCH: return "BLOCKED_CONTEXT_MISMATCH";
    case PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN: return "BLOCKED_LIVE_OUT_OF_DOMAIN";
    case PLAN_BLOCKED_NO_PROFILE: return "BLOCKED_NO_PROFILE";
    case PLAN_BLOCKED_PROFILE_INVALIDATED: return "BLOCKED_PROFILE_INVALIDATED";
    case PLAN_WOULD_ALREADY_MATCH: return "WOULD_ALREADY_MATCH";
    case PLAN_WOULD_APPLY_PROFILE: return "WOULD_APPLY_PROFILE";
    case PLAN_WOULD_REMAIN_LATCHED: return "WOULD_REMAIN_LATCHED";
    default: return "NOT_EVALUATED";  // 0 and every unknown value: fail-closed
  }
}

constexpr char sup_char(uint8_t state) { return state == 0 ? 'U' : state == 1 ? 'O' : state == 2 ? 'S' : 'L'; }

// The displayed `ECCO Failback Shadow State` (S3 3.7, first match; the not-ready string is published by nobody).
constexpr const char *state_name(uint8_t phase, bool would_latched, bool stable) {
  return phase == 1 ? "SHADOW_EPISODE"
         : phase == 2 ? "SHADOW_EPISODE_HA_BACK"
         : would_latched ? "SHADOW_WOULD_AWAIT_ACK"
         : !stable ? "SHADOW_WATCH"
                   : "SHADOW_IDLE";
}

// ---------------------------------------------------------------------------
// FB-F latch model (S3 3.3 / 7.2)
// ---------------------------------------------------------------------------
// The kind of a new shadow episode: FB-F would do nothing new while its record is still latched from an earlier episode.
constexpr uint8_t kind_for_edge(bool would_latched) { return would_latched ? (uint8_t) EPK_L : (uint8_t) EPK_N; }
// At the close of an episode FB-F would self-clear only a kind-N episode whose edge plan was "already at the profile"
// (policy B); every other close would stay latched awaiting an acknowledgement.
constexpr uint8_t close_outcome(uint8_t ep_kind, uint8_t edge_plan) {
  return (ep_kind == EPK_N && edge_plan == PLAN_WOULD_ALREADY_MATCH) ? (uint8_t) FBF_P : (uint8_t) FBF_A;
}
constexpr bool close_latches(uint8_t fbf) { return fbf == FBF_A; }

// ---------------------------------------------------------------------------
// Plan -> FB-A (state, result), Policy B (S4 8.1). 0xFF = RAM-only: FB-A has no record for it.
// ---------------------------------------------------------------------------
struct FbaPair {
  uint8_t state = NONE_U8;
  uint8_t result = NONE_U8;
};
constexpr FbaPair fba_for_plan(uint8_t plan) {
  switch (plan) {
    case PLAN_WOULD_PREEMPT_DUMP:
    case PLAN_WOULD_PREEMPT_FREE_POWER:
    case PLAN_WAIT_DUMP_RESTORE:
    case PLAN_WAIT_FREE_POWER_RESTORE:
    case PLAN_WAIT_WRITE_IN_FLIGHT:
    case PLAN_WAIT_LIVE_DATA:
    case PLAN_WAIT_MANUAL_TOU_RECOVERY:
      return {(uint8_t) ecco_fallback::FAILBACK_PREEMPT_REQUIRED, (uint8_t) ecco_fallback::FAILBACK_RESULT_NONE};
    case PLAN_BLOCKED_RECOVERY_METADATA:
    case PLAN_BLOCKED_OPERATOR_NEEDED:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_LEASE_RESTORE_LOCKED};
    case PLAN_BLOCKED_DURABLE_UNKNOWN:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_MARKER_DIVERGENCE};
    case PLAN_BLOCKED_PROFILE_CORRUPT:
    case PLAN_BLOCKED_PROFILE_UNAVAILABLE:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_PROFILE_UNAVAILABLE};
    case PLAN_BLOCKED_SITE_CEILING:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_SITE_CEILING};
    case PLAN_BLOCKED_CONTEXT_MISMATCH:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_CONTEXT_MISMATCH};
    case PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN:
      return {(uint8_t) ecco_fallback::FAILBACK_BLOCKED, (uint8_t) ecco_fallback::FAILBACK_RESULT_BLOCKED_LIVE_OUT_OF_DOMAIN};
    case PLAN_BLOCKED_NO_PROFILE:
    case PLAN_BLOCKED_PROFILE_INVALIDATED:
      return {(uint8_t) ecco_fallback::FAILBACK_LATCHED_COMPLETE, (uint8_t) ecco_fallback::FAILBACK_RESULT_PREEMPTED_NO_PROFILE};
    case PLAN_WOULD_ALREADY_MATCH:
      return {(uint8_t) ecco_fallback::FAILBACK_LATCHED_COMPLETE, (uint8_t) ecco_fallback::FAILBACK_RESULT_ALREADY_AT_PROFILE};
    case PLAN_WOULD_APPLY_PROFILE:
      return {(uint8_t) ecco_fallback::FAILBACK_LATCHED_COMPLETE, (uint8_t) ecco_fallback::FAILBACK_RESULT_APPLIED_VERIFIED};
    default:
      return {NONE_U8, NONE_U8};  // 0, 1, 2, 50 and anything unknown: RAM-only
  }
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------
// One lease domain after the shared classifier and the shadow's durable-leg evidence rule.
struct DomState {
  uint8_t c0 = C0_UNKNOWN;
  uint8_t kind = KIND_NONE;
  uint8_t evidence = EV_NONE;
  uint8_t slot_kind = ecco_fbcap::OBL_UNSET;    // the ecco_fbcap::ObligationKind it came from
  uint8_t slot_basis = ecco_fbcap::BASIS_NONE;
  bool marker_lost = false;                     // clear by RAM, absent at boot, and a retry record was loaded: the marker vanished
  bool stale_operator_needed = false;           // a stale `operator needed` with a present CLEAR marker (non-blocking flag)
};

struct Finding {
  uint8_t row = ROW_NONE;
  uint8_t plan = PLAN_NOT_EVALUATED;
  uint16_t reason = RS_NONE;
  uint8_t dom = BD_NONE;
};

// Abstract reason kinds, mapped to the per-domain numeric codes by dom_reason().
enum Rk : uint8_t {
  RK_ACTIVE, RK_STARTING, RK_DUE, RK_BACKOFF, RK_RESTORE_RUNNING, RK_OP_ACTION_RUNNING, RK_CLEAR_PENDING,
  RK_OPERATOR_NEEDED, RK_OPERATOR_NEEDED_EXPORT_LIVE, RK_FORCE_QUEUED, RK_METADATA_CORRUPT, RK_MARKER_UNREADABLE,
  RK_DIVERGED, RK_PROBE_UNREADABLE, RK_PROBE_MALFORMED, RK_LOST, RK_ABSENT_UNPROVEN, RK_RAM_INCONSISTENT, RK_STUCK,
  RK_SETTLING, RK_HELD, RK_HELD_DRIFT_GUARD, RK_CLEAR_PENDING_OPERATOR, RK_APPLY_RUNNING,
};

constexpr uint16_t dump_reason(uint8_t k) {
  switch (k) {
    case RK_ACTIVE: return RS_DUMP_ACTIVE;
    case RK_STARTING: return RS_DUMP_STARTING;
    case RK_DUE: return RS_DUMP_RESTORE_DUE;
    case RK_BACKOFF: return RS_DUMP_RESTORE_BACKOFF;
    case RK_RESTORE_RUNNING: return RS_DUMP_RESTORE_RUNNING;
    case RK_CLEAR_PENDING: return RS_DUMP_CLEAR_PENDING;
    case RK_OPERATOR_NEEDED: return RS_DUMP_OPERATOR_NEEDED;
    case RK_OPERATOR_NEEDED_EXPORT_LIVE: return RS_DUMP_OPERATOR_NEEDED_EXPORT_LIVE;
    case RK_FORCE_QUEUED: return RS_DUMP_FORCE_QUEUED;
    case RK_METADATA_CORRUPT: return RS_DUMP_METADATA_CORRUPT;
    case RK_MARKER_UNREADABLE: return RS_DUMP_MARKER_UNREADABLE;
    case RK_DIVERGED: return RS_DUMP_MARKER_DIVERGED;
    case RK_PROBE_UNREADABLE: return RS_DUMP_PROBE_UNREADABLE;
    case RK_PROBE_MALFORMED: return RS_DUMP_PROBE_MALFORMED;
    case RK_LOST: return RS_DUMP_MARKER_LOST;
    case RK_ABSENT_UNPROVEN: return RS_DUMP_MARKER_ABSENT_UNPROVEN;
    case RK_STUCK: return RS_DUMP_OP_FLAG_STUCK;
    case RK_SETTLING: return RS_DUMP_OP_FLAG_SETTLING;
    default: return RS_DUMP_RAM_INCONSISTENT;
  }
}
constexpr uint16_t fp_reason(uint8_t k) {
  switch (k) {
    case RK_ACTIVE: return RS_FP_ACTIVE;
    case RK_STARTING: return RS_FP_STARTING;
    case RK_DUE: return RS_FP_RESTORE_DUE;
    case RK_BACKOFF: return RS_FP_RESTORE_BACKOFF;
    case RK_RESTORE_RUNNING: return RS_FP_RESTORE_RUNNING;
    case RK_OP_ACTION_RUNNING: return RS_FP_OPERATOR_ACTION_RUNNING;
    case RK_CLEAR_PENDING: return RS_FP_CLEAR_PENDING;
    case RK_OPERATOR_NEEDED: return RS_FP_OPERATOR_NEEDED;
    case RK_METADATA_CORRUPT: return RS_FP_METADATA_CORRUPT;
    case RK_MARKER_UNREADABLE: return RS_FP_MARKER_UNREADABLE;
    case RK_DIVERGED: return RS_FP_MARKER_DIVERGED;
    case RK_PROBE_UNREADABLE: return RS_FP_PROBE_UNREADABLE;
    case RK_PROBE_MALFORMED: return RS_FP_PROBE_MALFORMED;
    case RK_LOST: return RS_FP_MARKER_LOST;
    case RK_ABSENT_UNPROVEN: return RS_FP_MARKER_ABSENT_UNPROVEN;
    case RK_STUCK: return RS_FP_OP_FLAG_STUCK;
    case RK_SETTLING: return RS_FP_OP_FLAG_SETTLING;
    default: return RS_FP_RAM_INCONSISTENT;
  }
}
constexpr uint16_t r244_reason(uint8_t k) {
  switch (k) {
    case RK_HELD: return RS_R244_HELD;
    case RK_HELD_DRIFT_GUARD: return RS_R244_HELD_DRIFT_GUARD;
    case RK_CLEAR_PENDING_OPERATOR: return RS_R244_CLEAR_PENDING_OPERATOR;
    case RK_APPLY_RUNNING: return RS_R244_APPLY_RUNNING;
    case RK_RESTORE_RUNNING: return RS_R244_RESTORE_RUNNING;
    case RK_METADATA_CORRUPT: return RS_R244_METADATA_CORRUPT;
    case RK_MARKER_UNREADABLE: return RS_R244_MARKER_UNREADABLE;
    case RK_DIVERGED: return RS_R244_MARKER_DIVERGED;
    case RK_PROBE_UNREADABLE: return RS_R244_PROBE_UNREADABLE;
    case RK_PROBE_MALFORMED: return RS_R244_PROBE_MALFORMED;
    case RK_ABSENT_UNPROVEN: return RS_R244_MARKER_ABSENT_UNPROVEN;
    case RK_STUCK: return RS_R244_OP_FLAG_STUCK;
    case RK_SETTLING: return RS_R244_OP_FLAG_SETTLING;
    default: return RS_R244_RAM_INCONSISTENT;
  }
}
constexpr uint16_t dom_reason(uint8_t dom, uint8_t k) {
  return dom == BD_DUMP ? dump_reason(k) : dom == BD_FP ? fp_reason(k) : r244_reason(k);
}

constexpr bool load_in_range(uint8_t l) { return l <= ecco_fbcap::BOOT_LOAD_READ_ERROR || l == ecco_fbcap::BOOT_LOAD_NOT_LOADED; }

// S4 E0: every enum input in range. The shadow never turns an out-of-range input into a verdict about the inverter.
constexpr bool inputs_valid(const ShadowInputs &in) {
  const ecco_fbcap::GateInputs &g = in.lm.g;
  return in.mode <= MODE_IF_LOST && in.sup.state <= 3 && g.fp.free_power_marker_state <= ecco_fbcap::MARKER_STATE_PENDING_CLEAR &&
         g.dump.dump_marker_state <= ecco_fbcap::MARKER_STATE_PENDING_CLEAR &&
         g.r244.reg244_marker_state <= ecco_fbcap::MARKER_STATE_PENDING_CLEAR && g.dump.dump_containment_state <= 8 &&
         in.lm.cls <= ecco_fbdurable::EPC_PROFILE_STALE && in.profile_why <= ecco_fbdurable::WHY_LOST_WIT_CORRUPT &&
         in.mtou_journal == 0 && load_in_range(g.fp.free_power_marker_boot_load) &&
         load_in_range(g.dump.dump_marker_boot_load) && load_in_range(g.r244.reg244_marker_boot_load);
}

constexpr uint8_t popcount32(uint32_t v) {
  uint8_t n = 0;
  for (; v != 0u; v &= (v - 1u))
    n++;
  return n;
}

constexpr uint8_t kind_of_slot(uint8_t slot_kind) {
  switch (slot_kind) {
    case ecco_fbcap::OBL_ACTIVE: return KIND_ACTIVE;
    case ecco_fbcap::OBL_STARTING: return KIND_STARTING;
    case ecco_fbcap::OBL_RESTORE_REQUIRED: return KIND_RESTORE_REQUIRED;
    case ecco_fbcap::OBL_PENDING_CLEAR: return KIND_PENDING_CLEAR;
    case ecco_fbcap::OBL_ENDING: return KIND_ENDING;
    case ecco_fbcap::OBL_OPERATOR_NEEDED: return KIND_OPERATOR_NEEDED;
    case ecco_fbcap::UNK_DURABLE_UNREADABLE: return KIND_DURABLE_UNREADABLE;
    case ecco_fbcap::UNK_METADATA_CORRUPT: return KIND_METADATA_CORRUPT;
    case ecco_fbcap::UNK_BOOT_NOT_LOADED: return KIND_BOOT_NOT_LOADED;
    case ecco_fbcap::UNK_DIVERGED: return KIND_DIVERGED;
    case ecco_fbcap::UNK_BUS_OR_LOCK_STUCK: return KIND_BUS_OR_LOCK_STUCK;
    default: return KIND_NONE;
  }
}

// One lease domain: the shared classifier's verdict (RAM legs, durable leg NOT probed) plus the evidence of a clear domain.
//   The shared classifier answers UNK_NOT_PROBED when every RAM leg is clear. The shadow never probes storage, so it can
//   only judge the durable leg from what the boot load retained (S4 2.10, S3 11.5):
//     boot load OK                     CLEAR, evidence MARKER_CLEAR_BOOT       (a marker was present at boot)
//     boot load ABSENT, used since boot CLEAR, evidence MARKER_CLEAR_RUNTIME    (a runtime marker may now exist, not verified)
//     boot load ABSENT, never used     CLEAR, evidence MARKER_ABSENT           (the absence is NOT proof: rule R3 blocks it)
//   and a retained "operator needed" with an absent marker proves the marker was lost (DIVERGED, MARKER_LOST).
constexpr DomState domain_state(const ecco_fbcap::SlotClass &slot, uint8_t boot_load, const DomExtra &x, bool force_clear) {
  DomState s{};
  s.slot_kind = slot.kind;
  s.slot_basis = slot.basis;
  if (force_clear) {  // the one-level projection after a pre-empt / restore
    s.c0 = C0_CLEAR_PROVEN;
    s.kind = KIND_NONE;
    s.evidence = EV_MARKER_CLEAR_RUNTIME;
    return s;
  }
  if (slot.kind == ecco_fbcap::UNK_NOT_PROBED) {
    const bool absent_now = boot_load == ecco_fbcap::BOOT_LOAD_ABSENT && !x.used_since_boot;
    if (absent_now && x.retry_on_raw) {
      s.c0 = C0_UNKNOWN;
      s.kind = KIND_DIVERGED;
      s.marker_lost = true;
      return s;
    }
    s.c0 = C0_CLEAR_PROVEN;
    s.kind = KIND_NONE;
    s.evidence = absent_now ? (uint8_t) EV_MARKER_ABSENT
                 : boot_load == ecco_fbcap::BOOT_LOAD_OK ? (uint8_t) EV_MARKER_CLEAR_BOOT
                                                         : (uint8_t) EV_MARKER_CLEAR_RUNTIME;
    s.stale_operator_needed = x.retry_on_raw && !absent_now;
    return s;
  }
  s.kind = kind_of_slot(slot.kind);
  const bool unknown = s.kind >= KIND_DURABLE_UNREADABLE;
  s.c0 = unknown ? (uint8_t) C0_UNKNOWN : (uint8_t) C0_OBLIGATION;
  if (slot.kind == ecco_fbcap::UNK_BUS_OR_LOCK_STUCK && slot.basis == ecco_fbcap::BASIS_OP_FLAG_UNATTRIBUTED) {
    // a domain operation flag with no running owner: attributed to the domain, in flight until the grace has passed
    s.c0 = C0_OBLIGATION;
    s.kind = x.orphan_ms >= kOwnerGraceMs ? (uint8_t) KIND_BUS_OR_LOCK_STUCK : (uint8_t) KIND_IN_FLIGHT;
    if (s.kind == KIND_BUS_OR_LOCK_STUCK)
      s.c0 = C0_UNKNOWN;
  }
  return s;
}

// The S4 2.4-2.6 decision of one lease domain (before the cross-domain precedence of 3.4).
constexpr Finding lease_finding(uint8_t dom, const DomState &s, const ShadowInputs &in, bool hazard_yes, bool r244_drift,
                                bool skip_l6) {
  Finding f{};
  f.dom = dom;
  const bool is_dump = dom == BD_DUMP;
  const bool is_fp = dom == BD_FP;
  if (s.c0 == C0_CLEAR_PROVEN) {
    if (s.evidence == EV_MARKER_ABSENT && !in.absence_witness && !skip_l6) {
      f.row = ROW_L6;
      f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
      f.reason = dom_reason(dom, RK_ABSENT_UNPROVEN);
    }
    return f;
  }
  if (s.marker_lost) {
    f.row = ROW_L4;
    f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
    f.reason = dom_reason(dom, RK_LOST);
    return f;
  }
  switch (s.kind) {
    case KIND_ACTIVE:
    case KIND_STARTING:
      if (is_dump || is_fp) {
        f.row = is_dump ? ROW_L1 : ROW_L2;
        f.plan = is_dump ? PLAN_WOULD_PREEMPT_DUMP : PLAN_WOULD_PREEMPT_FREE_POWER;
        f.reason = dom_reason(dom, s.kind == KIND_ACTIVE ? RK_ACTIVE : RK_STARTING);
      } else {  // R244: an apply in flight (a held test is OPERATOR_NEEDED, never ACTIVE)
        f.row = ROW_L10;
        f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
        f.reason = RS_R244_APPLY_RUNNING;
      }
      break;
    case KIND_ENDING:
      if (dom == BD_R244) {
        f.row = ROW_L10;
        f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
        f.reason = RS_R244_RESTORE_RUNNING;
      } else {
        f.row = is_dump ? ROW_L8 : ROW_L9;
        f.plan = is_dump ? PLAN_WAIT_DUMP_RESTORE : PLAN_WAIT_FREE_POWER_RESTORE;
        f.reason = dom_reason(dom, s.slot_basis == ecco_fbcap::BASIS_OPERATOR_ACTION_RUNNING ? RK_OP_ACTION_RUNNING
                                                                                            : RK_RESTORE_RUNNING);
      }
      break;
    case KIND_RESTORE_REQUIRED:
      f.row = is_dump ? ROW_L8 : ROW_L9;
      f.plan = is_dump ? PLAN_WAIT_DUMP_RESTORE : PLAN_WAIT_FREE_POWER_RESTORE;
      f.reason = dom_reason(dom, (is_dump ? in.dump.backoff : in.fp.backoff) ? RK_BACKOFF : RK_DUE);
      break;
    case KIND_PENDING_CLEAR:
      if (dom == BD_R244) {
        f.row = ROW_L5;
        f.plan = PLAN_BLOCKED_OPERATOR_NEEDED;
        f.reason = RS_R244_CLEAR_PENDING_OPERATOR;
      } else {
        f.row = is_dump ? ROW_L8 : ROW_L9;
        f.plan = is_dump ? PLAN_WAIT_DUMP_RESTORE : PLAN_WAIT_FREE_POWER_RESTORE;
        f.reason = dom_reason(dom, RK_CLEAR_PENDING);
      }
      break;
    case KIND_OPERATOR_NEEDED:
      if (is_dump && in.dump.force_bypass) {  // D7a: a queued Force restore is consumed by the next watchdog tick
        f.row = ROW_L8;
        f.plan = PLAN_WAIT_DUMP_RESTORE;
        f.reason = RS_DUMP_FORCE_QUEUED;
      } else {
        f.row = ROW_L5;
        f.plan = PLAN_BLOCKED_OPERATOR_NEEDED;
        f.reason = dom == BD_R244 ? (r244_drift ? (uint16_t) RS_R244_HELD_DRIFT_GUARD : (uint16_t) RS_R244_HELD)
                   : is_dump      ? (hazard_yes ? (uint16_t) RS_DUMP_OPERATOR_NEEDED_EXPORT_LIVE : (uint16_t) RS_DUMP_OPERATOR_NEEDED)
                                  : (uint16_t) RS_FP_OPERATOR_NEEDED;
      }
      break;
    case KIND_IN_FLIGHT:
      f.row = ROW_L10;
      f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
      f.reason = dom_reason(dom, RK_SETTLING);
      break;
    case KIND_BUS_OR_LOCK_STUCK:
      f.row = ROW_L7;
      f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
      f.reason = dom_reason(dom, RK_STUCK);
      break;
    case KIND_DURABLE_UNREADABLE:
      if (s.slot_basis == ecco_fbcap::BASIS_BOOT_READ_ERROR) {
        f.row = ROW_L3;
        f.plan = PLAN_BLOCKED_RECOVERY_METADATA;
        f.reason = dom_reason(dom, RK_MARKER_UNREADABLE);
      } else {
        f.row = ROW_L4;
        f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
        f.reason = dom_reason(dom, RK_PROBE_UNREADABLE);
      }
      break;
    case KIND_METADATA_CORRUPT:
      if (s.slot_basis == ecco_fbcap::BASIS_BOOT_LOCKOUT) {
        f.row = ROW_L3;
        f.plan = PLAN_BLOCKED_RECOVERY_METADATA;
        f.reason = dom_reason(dom, RK_METADATA_CORRUPT);
      } else {
        f.row = ROW_L4;
        f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
        f.reason = dom_reason(dom, RK_PROBE_MALFORMED);
      }
      break;
    case KIND_DIVERGED:
      f.row = ROW_L4;
      f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
      f.reason = dom_reason(dom, (s.slot_basis == ecco_fbcap::BASIS_GHOST_RR || s.slot_basis == ecco_fbcap::BASIS_GHOST_PC)
                                     ? RK_DIVERGED
                                     : RK_RAM_INCONSISTENT);
      break;
    default:  // KIND_BOOT_NOT_LOADED with boot_loaded true: the boot-load retention is missing for this domain
      f.row = ROW_L4;
      f.plan = PLAN_BLOCKED_DURABLE_UNKNOWN;
      f.reason = dom_reason(dom, RK_RAM_INCONSISTENT);
      break;
  }
  return f;
}

// BUS (B1-B4) and MTOU (T1). The shared classify_bus answers LOCK_STUCK only after 300 s of the write-lock diagnostic; the
// shadow's own owner timers (S4 2.9) catch the 10 s orphan and the 60 s RTC lock.
constexpr Finding bus_finding(const ShadowInputs &in, const ecco_fbcap::SlotClass &bus) {
  Finding f{};
  f.dom = BD_BUS;
  const ecco_fbcap::BusInputs &b = in.lm.g.bus;
  const bool orphan = b.manual_write_in_progress && !in.bus.any_owner_running && in.bus.mwip_orphan_ms >= kOwnerGraceMs;
  const bool cip_stuck = b.correction_in_progress && in.bus.cip_held_ms >= kCipStuckMs;
  if (cip_stuck || orphan || bus.kind == ecco_fbcap::UNK_BUS_OR_LOCK_STUCK) {
    f.row = ROW_L7;
    f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
    f.reason = cip_stuck ? (uint16_t) RS_RTC_LOCK_STUCK : (uint16_t) RS_LOCK_HELD_NO_KNOWN_OWNER;
    return f;
  }
  if (bus.kind == ecco_fbcap::BUS_BUSY) {
    f.row = ROW_L10;
    f.plan = PLAN_WAIT_WRITE_IN_FLIGHT;
    f.reason = (b.fallback_profile_capture_dispatch_running || b.fallback_profile_op_in_progress) ? (uint16_t) RS_FBB_CAPTURE_RUNNING
               : b.correction_in_progress                                                            ? (uint16_t) RS_RTC_CORRECTION_RUNNING
               : (b.manual_write_in_progress && in.bus.any_owner_running)                            ? (uint16_t) RS_LOCK_HELD_OWNER_RUNNING
                                                                                                     : (uint16_t) RS_LOCK_HELD_SETTLING;
  }
  return f;
}

constexpr Finding mk(uint8_t row, uint8_t plan, uint16_t reason, uint8_t dom) {
  Finding f{};
  f.row = row;
  f.plan = plan;
  f.reason = reason;
  f.dom = dom;
  return f;
}

constexpr uint16_t ctx_reason(uint16_t m) {
  const uint8_t cats = (uint8_t) (((m & 0x001u) ? 1 : 0) + ((m & 0x002u) ? 1 : 0) + ((m & 0x004u) ? 1 : 0) + ((m & 0x1F8u) ? 1 : 0));
  if (cats > 1)
    return RS_CTX_MULTIPLE;
  return (m & 0x001u) ? (uint16_t) RS_CTX_232_BIT0 : (m & 0x002u) ? (uint16_t) RS_CTX_243 : (m & 0x004u) ? (uint16_t) RS_CTX_248_BIT0
                                                                                                          : (uint16_t) RS_CTX_SLOT_TIMES;
}

// dx / ox layout: bit0 244, bits 1-6 power, 7-12 SOC, 13-18 source.
constexpr uint16_t ood_reason(uint32_t m, uint16_t live244) {
  const uint8_t cats = (uint8_t) (((m & 0x00001u) ? 1 : 0) + ((m & 0x0007Eu) ? 1 : 0) + ((m & 0x01F80u) ? 1 : 0) + ((m & 0x7E000u) ? 1 : 0));
  if (cats > 1)
    return RS_LIVE_MULTIPLE_OUT_OF_DOMAIN;
  return (m & 0x00001u) ? (live244 == 1 ? (uint16_t) RS_LIVE_244_ESSENTIALS : (uint16_t) RS_LIVE_244_UNRECOGNISED)
         : (m & 0x0007Eu) ? (uint16_t) RS_LIVE_POWER_OUT_OF_RANGE
         : (m & 0x01F80u) ? (uint16_t) RS_LIVE_SOC_OUT_OF_RANGE
                          : (uint16_t) RS_LIVE_SOURCE_WORD_UNSUPPORTED;
}

constexpr bool meaningful_class(uint8_t eff) {
  return eff == ecco_fbdurable::EPC_VALID || eff == ecco_fbdurable::EPC_INVALIDATED || eff == ecco_fbdurable::EPC_CORRUPT_DOMAIN;
}

constexpr uint16_t live_reason(uint8_t ca) {
  return ca == ecco_fbcap::CQ_INVALID ? (uint16_t) RS_LIVE_CACHE_INVALID
         : ca == ecco_fbcap::CQ_POLL_OFF ? (uint16_t) RS_LIVE_POLLING_OFF
         : ca == ecco_fbcap::CQ_STALE ? (uint16_t) RS_LIVE_CACHE_STALE
         : ca == ecco_fbcap::CQ_PRE_FENCE ? (uint16_t) RS_LIVE_CACHE_PRE_FENCE
                                          : (uint16_t) RS_LIVE_NOT_LATCHED;  // CQ_NOT_FILLED and the boot term
}

// The first finding with a given row, scanning the domains in the S4 tie-break order DUMP -> FP -> R244 -> BUS -> MTOU.
constexpr Finding pick_row(const std::array<Finding, 5> &f, uint8_t row) {
  for (size_t i = 0; i < f.size(); i++) {
    if (f[i].row == row)
      return f[i];
  }
  return Finding{};
}

// Applies the overrides of the one-level projections to a copy of the live words (FP original / Dump original).
constexpr ecco_fbcap::CaptureWords projected_live(const ShadowInputs &in, uint8_t clear_dom, bool use_snapshot) {
  ecco_fbcap::CaptureWords w = in.lm.live;
  if (!use_snapshot) {
    return w;
  } else if (clear_dom == BD_FP) {
    w[19] = in.fp_snap.r232;
    for (size_t i = 0; i < 6; i++) {
      w[1 + i] = in.fp_snap.r256[i];
      w[7 + i] = in.fp_snap.r268[i];
      w[13 + i] = in.fp_snap.r274[i];
    }
  } else if (clear_dom == BD_DUMP) {
    w[0] = in.lm.dump_snapshot_reg244;
    for (size_t i = 0; i < 6; i++)
      w[1 + i] = in.lm.dump_snapshot_reg256_261[i];
  }
  return w;
}

// ---------------------------------------------------------------------------
// The evaluator core. depth 0 is the public call; depth 1 is one of the two best-effort re-runs (projected_after and
// alt_plan_absence_accepted), which never recurse further and never change `plan`.
// ---------------------------------------------------------------------------
constexpr ShadowPlan eval_core(const ShadowInputs &in, bool skip_l6, uint8_t clear_dom, bool use_snapshot, uint8_t depth) {
  ShadowPlan r{};
  const ecco_fbcap::GateInputs &g = in.lm.g;
  r.would_refuse_starts = !in.sup.p_stable || in.sup.episode_open || in.mode == MODE_IF_LOST;
  r.sup_returned_episode_open = in.sup.episode_open && in.sup.state != 3;
  // ---- E0 / E1 -----------------------------------------------------------------------------------------------------------
  if (!inputs_valid(in)) {
    r.row = ROW_E0;
    r.reason = RS_INPUT_INVALID;
    r.blocking_domain = BD_BOOT;
    return r;
  }
  if (!g.boot_loaded) {
    r.row = ROW_E1;
    r.reason = RS_BOOT_NOT_LOADED;
    r.blocking_domain = BD_BOOT;
    return r;
  }

  // ---- shared classification (the same ecco_fbcap functions the Live Match uses; the durable leg is never probed) ----------
  const ecco_fbcap::SlotClass sl_fp = ecco_fbcap::classify_fp(g, ecco_fbcap::PROBE_NONE);
  const ecco_fbcap::SlotClass sl_dump = ecco_fbcap::classify_dump(g, ecco_fbcap::PROBE_NONE);
  const ecco_fbcap::SlotClass sl_r244 = ecco_fbcap::classify_r244(g, ecco_fbcap::PROBE_NONE);
  const ecco_fbcap::SlotClass sl_bus = ecco_fbcap::classify_bus(g);
  const DomState ds_dump = domain_state(sl_dump, g.dump.dump_marker_boot_load, in.dump, clear_dom == BD_DUMP);
  const DomState ds_fp = domain_state(sl_fp, g.fp.free_power_marker_boot_load, in.fp, clear_dom == BD_FP);
  const DomState ds_r244 = domain_state(sl_r244, g.r244.reg244_marker_boot_load, in.r244, clear_dom == BD_R244);

  // ---- live trust and the comparison masks (shared helpers) --------------------------------------------------------------
  const uint8_t ca = ecco_fbcap::live_trust(in.lm.cache, g.boot_loaded);
  const bool trusted = ca == ecco_fbcap::CQ_FRESH;
  r.ca = ca;
  const uint8_t eff = ecco_fbcap::live_effective_class(in.lm.cls, in.lm.write_outcome_unknown, in.lm.read_anomaly);
  const ecco_fbcap::CaptureWords live = projected_live(in, clear_dom, use_snapshot);
  const bool prof_valid_rec = ecco_fallback::classify_profile(in.lm.p_load, in.lm.p) == ecco_fallback::PROFILE_VALID;
  r.masks_valid = trusted && (eff == ecco_fbdurable::EPC_VALID || eff == ecco_fbdurable::EPC_CORRUPT_DOMAIN);
  if (r.masks_valid) {
    const ecco_fbcap::CaptureWords stored = ecco_fbcap::words_of(in.lm.p);
    r.e1_delta_mask = ecco_fbcap::e1_delta_mask(live, stored);
    r.ctx_mismatch_mask = ecco_fbcap::ctx_mismatch_mask(live, stored);
    r.out_of_domain_mask = ecco_fbcap::out_of_domain_mask(live);
    r.info_mismatch_mask = ecco_fbcap::info_mismatch_mask(live, stored);
    r.delta_count = popcount32(r.e1_delta_mask);
  }

  // ---- export hazard: the shared tri-state predicate over the shadow's own domain classification ------------------------------
  const bool bad_domain = (ds_dump.c0 != C0_CLEAR_PROVEN && ds_dump.kind != KIND_ACTIVE && ds_dump.kind != KIND_STARTING) ||
                          (ds_fp.c0 != C0_CLEAR_PROVEN && ds_fp.kind != KIND_ACTIVE && ds_fp.kind != KIND_STARTING) ||
                          (ds_r244.c0 != C0_CLEAR_PROVEN && ds_r244.kind != KIND_ACTIVE && ds_r244.kind != KIND_STARTING);
  const bool dump_exempt = in.lm.dump_data_loaded && in.lm.dump_snapshot_reg244 == 0 && live[1] == in.lm.dump_snapshot_reg256_261[0] &&
                           live[2] == in.lm.dump_snapshot_reg256_261[1] && live[3] == in.lm.dump_snapshot_reg256_261[2] &&
                           live[4] == in.lm.dump_snapshot_reg256_261[3] && live[5] == in.lm.dump_snapshot_reg256_261[4] &&
                           live[6] == in.lm.dump_snapshot_reg256_261[5];
  r.export_hazard = ecco_fbcap::export_hazard(trusted, live[0], bad_domain, dump_exempt);
  r.hazard_obligation = bad_domain;

  // ---- per-domain findings --------------------------------------------------------------------------------------------------
  const bool r244_drift = trusted && in.r244x.lav && live[0] != in.r244x.la;
  const bool hazard_yes = r.export_hazard == ecco_fbcap::EH_YES;
  // order: DUMP, FP, R244, BUS, MTOU
  std::array<Finding, 5> fnd{};
  fnd[0] = lease_finding(BD_DUMP, ds_dump, in, hazard_yes, false, skip_l6);
  fnd[1] = lease_finding(BD_FP, ds_fp, in, hazard_yes, false, skip_l6);
  fnd[2] = lease_finding(BD_R244, ds_r244, in, hazard_yes, r244_drift, skip_l6);
  fnd[3] = bus_finding(in, sl_bus);
  if (in.lm.mtou_running) {
    fnd[4].row = ROW_L10;
    fnd[4].plan = PLAN_WAIT_WRITE_IN_FLIGHT;
    fnd[4].reason = RS_MTOU_APPLY_RUNNING;
    fnd[4].dom = BD_MTOU;
  }

  // ---- telemetry flags (computed whenever their inputs exist, independent of the winning row) ------------------------------------
  r.absence_relied = ds_dump.evidence == EV_MARKER_ABSENT || ds_fp.evidence == EV_MARKER_ABSENT || ds_r244.evidence == EV_MARKER_ABSENT;
  r.durable_leg_projected = ds_dump.evidence == EV_MARKER_CLEAR_BOOT || ds_dump.evidence == EV_MARKER_CLEAR_RUNTIME ||
                            ds_fp.evidence == EV_MARKER_CLEAR_BOOT || ds_fp.evidence == EV_MARKER_CLEAR_RUNTIME ||
                            ds_r244.evidence == EV_MARKER_CLEAR_BOOT || ds_r244.evidence == EV_MARKER_CLEAR_RUNTIME;
  r.fp_stale_operator_needed = ds_fp.stale_operator_needed;
  r.dump_stale_operator_needed = ds_dump.stale_operator_needed;
  r.r244_lav_marker_absent = in.r244x.lav && ds_r244.evidence == EV_MARKER_ABSENT;
  r.fp_ctx_unknown = in.fp_lease_ctx_unknown && ds_fp.kind == KIND_RESTORE_REQUIRED;
  r.dump_force_bypass_armed = in.dump.force_bypass;

  // ---- domain views ----------------------------------------------------------------------------------------------------------------
  r.dom[DS_DUMP] = {ds_dump.c0, ds_dump.kind, ds_dump.evidence, (uint8_t) (g.dump.dump_containment_state << 4)};
  r.dom[DS_FP] = {ds_fp.c0, ds_fp.kind, ds_fp.evidence, 0};
  r.dom[DS_R244] = {ds_r244.c0, ds_r244.kind, ds_r244.evidence, 0};
  {
    const bool stuck = fnd[3].row == ROW_L7;
    const bool busy = fnd[3].row == ROW_L10;
    r.dom[DS_BUS] = stuck ? DomView{C0_UNKNOWN, KIND_BUS_OR_LOCK_STUCK, EV_NONE, 0}
                    : busy ? DomView{C0_OBLIGATION, KIND_IN_FLIGHT, EV_NONE, 0}
                           : DomView{C0_CLEAR_PROVEN, KIND_NONE, EV_IDLE, 0};
    r.dom[DS_MTOU] = in.lm.mtou_running ? DomView{C0_OBLIGATION, KIND_IN_FLIGHT, EV_NONE, 0}
                                        : DomView{C0_CLEAR_PROVEN, KIND_NONE, EV_NO_DURABLE_RECORD, 0};
    r.dom[DS_MTOU_JOURNAL] = DomView{C0_CLEAR_PROVEN, KIND_NONE, EV_NOT_IMPLEMENTED, 0};
  }
  r.dom[DS_FBP] = DomView{C0_UNKNOWN, KIND_NONE, EV_NONE, eff};

  // overlay: the cache is not a stable baseline while a lease is not clear or a writer holds a lock (S3 11.5)
  const bool overlay = ds_dump.c0 != C0_CLEAR_PROVEN || ds_fp.c0 != C0_CLEAR_PROVEN || ds_r244.c0 != C0_CLEAR_PROVEN ||
                       g.bus.manual_write_in_progress || g.bus.correction_in_progress;
  r.e1_state = !r.masks_valid ? (uint8_t) CMP_N : overlay ? (uint8_t) CMP_O : r.e1_delta_mask == 0 ? (uint8_t) CMP_M : (uint8_t) CMP_D;
  r.cx_state = !r.masks_valid ? (uint8_t) CMP_N : overlay ? (uint8_t) CMP_O : r.ctx_mismatch_mask == 0 ? (uint8_t) CMP_M : (uint8_t) CMP_D;
  r.in_state = !r.masks_valid ? (uint8_t) CMP_N : r.info_mismatch_mask == 0 ? (uint8_t) CMP_M : (uint8_t) CMP_D;

  // ---- the first-match precedence (S4 3.4) ---------------------------------------------------------------------------------------
  const bool effective_lost = in.mode == MODE_IF_LOST || in.sup.state == 3 || in.sup.episode_open;
  Finding w{};
  if (!effective_lost) {
    w.row = in.sup.p_stable ? (uint8_t) ROW_S1 : (uint8_t) ROW_S2;
    w.plan = in.sup.p_stable ? (uint8_t) PLAN_NO_ACTION : (uint8_t) PLAN_WOULD_REFUSE_STARTS;
    w.reason = in.sup.p_stable ? (uint16_t) RS_SUP_STABLE
               : in.sup.state == 0 ? (uint16_t) RS_SUP_STARTUP
               : in.sup.state == 2 ? (uint16_t) RS_SUP_SUSPECT
                                   : (uint16_t) RS_SUP_UNSTABLE;
    w.dom = in.sup.p_stable ? (uint8_t) BD_NONE : (uint8_t) BD_SUPERVISION;
  } else {
    const uint8_t rows[10] = {ROW_L1, ROW_L2, ROW_L3, ROW_L4, ROW_L5, ROW_L6, ROW_L7, ROW_L8, ROW_L9, ROW_L10};
    for (size_t i = 0; i < 10 && w.row == ROW_NONE; i++)
      w = pick_row(fnd, rows[i]);
    if (w.row == ROW_NONE) {
      // L12: the profile identity changed under an open episode
      const bool changed = in.sup.episode_open && in.ep.bound &&
                           (in.ep.cls != eff || (meaningful_class(eff) && (in.lm.p.generation != in.ep.gen || in.lm.p.binding != in.ep.binding)));
      r.profile_changed_since_lost = changed;
      if (changed)
        w = mk(ROW_L12, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_CHANGED_SINCE_LOST, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_SAVE_UNCONFIRMED)
        w = mk(ROW_L13, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_SAVE_UNCONFIRMED, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_UNREADABLE)
        w = mk(ROW_L14, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_UNREADABLE, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_PROFILE_LOST)
        w = mk(ROW_L15, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_LOST, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_PROFILE_STALE)
        w = mk(ROW_L15_STALE, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_STALE, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_CORRUPT)
        w = mk(ROW_L16, PLAN_BLOCKED_PROFILE_CORRUPT, RS_PROFILE_CORRUPT, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_CORRUPT_DOMAIN)
        w = mk(ROW_L17, PLAN_BLOCKED_PROFILE_CORRUPT, RS_PROFILE_CORRUPT_DOMAIN, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_NOT_CAPTURED && !in.not_captured_proven)
        w = mk(ROW_L18, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_ABSENT_UNPROVEN, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_NOT_CAPTURED)
        w = mk(ROW_L19, PLAN_BLOCKED_NO_PROFILE, RS_PROFILE_NOT_CAPTURED, BD_FBP);
      else if (eff == ecco_fbdurable::EPC_INVALIDATED)
        w = mk(ROW_L20, PLAN_BLOCKED_PROFILE_INVALIDATED, RS_PROFILE_INVALIDATED, BD_FBP);
      else if (!prof_valid_rec)  // a VALID class over a record FB-A does not classify VALID: fail closed
        w = mk(ROW_L14, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_UNREADABLE, BD_FBP);
      else if (!ecco_fbdurable::profile_writer_usable(eff, in.profile_why))
        w = mk(ROW_L20_NOT_USABLE, PLAN_BLOCKED_PROFILE_UNAVAILABLE, RS_PROFILE_NOT_WRITER_USABLE, BD_FBP);
      else {
        // fbp VALID and usable from here on
        r.dom[DS_FBP].c0 = C0_CLEAR_PROVEN;
        bool above = false;
        for (size_t i = 0; i < 6; i++) {
          if (in.lm.p.reg256_261[i] > in.lm.ceiling_w)
            above = true;
        }
        if (above)
          w = mk(ROW_L21, PLAN_BLOCKED_SITE_CEILING, RS_SITE_CEILING_BELOW_PROFILE, BD_SITE);
        else if (!trusted)
          w = mk(ROW_L22, PLAN_WAIT_LIVE_DATA, live_reason(ca), BD_LIVE);
        else if (r.ctx_mismatch_mask != 0)
          w = mk(ROW_L23, PLAN_BLOCKED_CONTEXT_MISMATCH, ctx_reason(r.ctx_mismatch_mask), BD_LIVE);
        else if (r.out_of_domain_mask != 0)
          w = mk(ROW_L24, PLAN_BLOCKED_LIVE_OUT_OF_DOMAIN, ood_reason(r.out_of_domain_mask, live[0]), BD_LIVE);
        else if (r.e1_delta_mask == 0)
          w = mk(ROW_L25, PLAN_WOULD_ALREADY_MATCH, RS_MATCH_E1_AND_CTX, BD_NONE);
        else
          w = mk(ROW_L26, PLAN_WOULD_APPLY_PROFILE, RS_E1_DELTA, BD_NONE);
      }
    }
  }
  r.plan = w.plan;
  r.reason = w.reason;
  r.blocking_domain = w.dom;
  r.row = w.row;

  // ---- derived outputs -------------------------------------------------------------------------------------------------------------
  r.would_preempt_fp = r.plan == PLAN_WOULD_PREEMPT_FREE_POWER;
  r.would_preempt_dump = r.plan == PLAN_WOULD_PREEMPT_DUMP;
  r.would_apply = r.plan == PLAN_WOULD_APPLY_PROFILE;
  if (r.would_apply) {
    const ecco_fbcap::CaptureWords stored = ecco_fbcap::words_of(in.lm.p);
    uint8_t fr = 0;
    if (live[0] == 0 && (r.e1_delta_mask & 1u) != 0)
      fr |= FR_F244;
    for (size_t i = 0; i < 6; i++) {
      if (stored[1 + i] < live[1 + i])
        fr |= FR_F256_DOWN;
      if (stored[1 + i] > live[1 + i])
        fr |= FR_F256_UP;
    }
    if ((r.e1_delta_mask & 0x7FF80u) != 0u)
      fr |= FR_F268_279;
    r.projected_frames = fr;
    r.projected_frame_count = popcount32(fr);
    r.would_write_244 = (fr & FR_F244) != 0;
  }
  const FbaPair fba = fba_for_plan(r.plan);
  r.fba_state = fba.state;
  r.fba_result = fba.result;
  const bool profile_or_live_row = (r.row >= ROW_L12 && r.row <= ROW_L26) || r.row == ROW_L15_STALE || r.row == ROW_L20_NOT_USABLE;
  r.fba_result_policy_a = (fba.state != NONE_U8 && profile_or_live_row) ? (uint8_t) ecco_fallback::FAILBACK_RESULT_PREEMPTED_ONLY : fba.result;
  r.projected_after = r.plan;
  r.alt_plan_absence_accepted = r.plan;

  // ---- the two best-effort one-level re-runs (S4 3.5) -------------------------------------------------------------------------------
  if (depth == 0) {
    if (r.row == ROW_L6)
      r.alt_plan_absence_accepted = eval_core(in, true, clear_dom, use_snapshot, 1).plan;
    if (r.row == ROW_L1 || r.row == ROW_L2 || r.row == ROW_L8 || r.row == ROW_L9) {
      const uint8_t dom = r.blocking_domain;  // BD_DUMP or BD_FP
      // a pending clear leaves the hardware at the original already: the live words stand; every other case needs the original
      const bool pc = (dom == BD_DUMP ? ds_dump.kind : ds_fp.kind) == KIND_PENDING_CLEAR;
      const bool snap_ok = pc || (dom == BD_FP ? in.fp_snap.valid : in.lm.dump_data_loaded);
      r.projected_after = snap_ok ? eval_core(in, skip_l6, dom, !pc, 1).plan : (uint8_t) PLAN_WAIT_LIVE_DATA;
    }
  }
  return r;
}

constexpr ShadowPlan evaluate(const ShadowInputs &in) { return eval_core(in, false, 0xFFu, false, 0); }

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------
// One lease domain in the Inputs entity: C<basis M|R|A> | O<kind> | U<kind>.
constexpr void put_dom(ecco_fbcap::TextBuf &t, const DomView &d) {
  if (d.c0 == C0_CLEAR_PROVEN) {
    ecco_fbcap::put_char(t, 'C');
    ecco_fbcap::put_char(t, d.evidence == EV_MARKER_CLEAR_BOOT ? 'M' : d.evidence == EV_MARKER_CLEAR_RUNTIME ? 'R'
                                                                   : d.evidence == EV_MARKER_ABSENT ? 'A' : '-');
  } else {
    ecco_fbcap::put_char(t, d.c0 == C0_OBLIGATION ? 'O' : 'U');
    ecco_fbcap::put_u(t, d.kind);
  }
}

// `sup;st;fp;dp;r4;mt;pc;g;pb;e1;cx;in;ca;d;blk;lk;pl;rs;alt;pa`, every key always present, <= 200 characters. `plan` is the
// readiness (MODE_IF_LOST) evaluation; `in` supplies the supervision state and the profile identity. `alt` and `pa` are the FINAL 8.5
// one-level re-runs, appended after S3 9.2's keys (append-only): `alt` = alt_plan_absence_accepted (the plan if absence were
// accepted; equal to `pl` unless row L6 fired), `pa` = projected_after (the plan after the awaited pre-empt / restore; equal to
// `pl` unless rows L1 / L2 / L8 / L9 fired).
constexpr ecco_fbcap::TextBuf inputs_text(const ShadowInputs &in, const ShadowPlan &plan) {
  ecco_fbcap::TextBuf t;
  const uint8_t eff = ecco_fbcap::live_effective_class(in.lm.cls, in.lm.write_outcome_unknown, in.lm.read_anomaly);
  ecco_fbcap::put(t, "sup=");
  ecco_fbcap::put_char(t, sup_char(in.sup.state));
  ecco_fbcap::put(t, ";st=");
  ecco_fbcap::put_char(t, in.sup.p_stable ? '1' : '0');
  ecco_fbcap::put(t, ";fp=");
  put_dom(t, plan.dom[DS_FP]);
  ecco_fbcap::put(t, ";dp=");
  put_dom(t, plan.dom[DS_DUMP]);
  ecco_fbcap::put(t, ";r4=");
  put_dom(t, plan.dom[DS_R244]);
  ecco_fbcap::put(t, ";mt=-;pc=");
  ecco_fbcap::put_u(t, eff);
  ecco_fbcap::put(t, ";g=");
  if (meaningful_class(eff))
    ecco_fbcap::put_u(t, in.lm.p.generation);
  else
    ecco_fbcap::put_char(t, '-');
  ecco_fbcap::put(t, ";pb=");
  if (meaningful_class(eff))
    ecco_fbcap::put_hex(t, in.lm.p.binding >> 32, 8);
  else
    ecco_fbcap::put_char(t, '-');
  ecco_fbcap::put(t, ";e1=");
  ecco_fbcap::put_char(t, cmp_char(plan.e1_state));
  ecco_fbcap::put(t, ";cx=");
  ecco_fbcap::put_char(t, cmp_char(plan.cx_state));
  ecco_fbcap::put(t, ";in=");
  ecco_fbcap::put_char(t, cmp_char(plan.in_state));
  ecco_fbcap::put(t, ";ca=");
  ecco_fbcap::put_char(t, ecco_fbcap::cq_char(plan.ca));
  ecco_fbcap::put(t, ";d=");
  if (plan.delta_count == NONE_U8)
    ecco_fbcap::put_char(t, '-');
  else
    ecco_fbcap::put_u(t, plan.delta_count);
  ecco_fbcap::put(t, ";blk=");
  ecco_fbcap::put_hex(t, plan.projected_frames, 1);
  ecco_fbcap::put(t, ";lk=");
  ecco_fbcap::put_u(t, (uint32_t) ((in.lm.g.bus.manual_write_in_progress ? 1u : 0u) | (in.lm.g.bus.correction_in_progress ? 2u : 0u)));
  ecco_fbcap::put(t, ";pl=");
  ecco_fbcap::put_u(t, plan.plan);
  ecco_fbcap::put(t, ";rs=");
  ecco_fbcap::put_u(t, plan.reason);
  ecco_fbcap::put(t, ";alt=");
  ecco_fbcap::put_u(t, plan.alt_plan_absence_accepted);
  ecco_fbcap::put(t, ";pa=");
  ecco_fbcap::put_u(t, plan.projected_after);
  return t;
}

// ---- static self-checks (the golden tables live in the offline suites) ---------------------------------------------------------
static_assert(kOwnerGraceMs == 10000u && kCipStuckMs == 60000u, "FB-C2: shadow thresholds");
static_assert(ecco_fbcap::LIVE_CACHE_MAX_AGE_MS >= 125000u && ecco_fbcap::LIVE_CACHE_MAX_AGE_MS <= 300000u,
              "FB-C2: the shared live-cache age bound lies in the architecture's 125-300 s window");
static_assert(ecco_fbcap::LIVE_FENCE_OFFSET == 2u, "FB-C2: the shared write-fence offset");
static_assert(evaluate(ShadowInputs{}).plan == PLAN_NOT_EVALUATED && evaluate(ShadowInputs{}).fba_state == NONE_U8,
              "FB-C2: a zero-initialised input evaluates to NOT_EVALUATED (RAM-only)");
static_assert(evaluate(ShadowInputs{}).export_hazard == ecco_fbcap::EH_UNKNOWN, "FB-C2: a zero-initialised plan reads export hazard UNKNOWN");
static_assert(!evaluate(ShadowInputs{}).hazard_obligation,
              "FB-C2: an unevaluated plan (E0 / E1) reports no export-hazard obligation (the soak counts no hazard time for it)");
static_assert(close_outcome(EPK_N, PLAN_WOULD_ALREADY_MATCH) == FBF_P && close_outcome(EPK_L, PLAN_WOULD_ALREADY_MATCH) == FBF_A &&
                  close_outcome(EPK_N, PLAN_BLOCKED_NO_PROFILE) == FBF_A,
              "FB-C2: only a kind-N episode whose edge plan was ALREADY_MATCH self-clears");

}  // namespace ecco_failback_shadow
